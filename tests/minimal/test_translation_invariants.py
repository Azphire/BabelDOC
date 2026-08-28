from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import babeldoc.format.pdf.document_il.midend.il_translator_llm_only as llm_module
import pytest
from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import PdfStyle
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
    ILTranslatorLLMOnly,
)
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine.chain_translation import ChainClaim
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import RecordingExecutor
from tests.minimal.fakes import RecordingTracker
from tests.minimal.fakes import make_article_context_fixture


def _page_driver():
    driver = object.__new__(ILTranslatorLLMOnly)
    driver.translation_config = SimpleNamespace(
        raise_if_cancelled=lambda: None,
        min_text_length=1,
        shared_context_cross_split_part=SimpleNamespace(
            first_paragraph=None,
            recent_title_paragraph=None,
        ),
    )
    driver.shared_context_cross_split_part = SimpleNamespace(
        recent_title_paragraph=None,
        snapshot_title_paragraph=lambda paragraph: paragraph,
    )
    driver.calc_token_count = len
    driver.mid = 0
    return driver


def test_ordinary_non_chain_paragraph_is_scheduled_once_with_article_brief():
    document, article_ir, paragraphs = make_article_context_fixture()
    driver = _page_driver()
    executor = RecordingExecutor()
    context = llm_module.ArticleContext(
        article_document_ir=article_ir,
        page_index={id(page): index for index, page in enumerate(document.page)},
        article_of_page={0: "article-a", 1: "article-a", 2: "article-b"},
        brief_of_article={"article-a": "shared brief"},
    )

    driver.process_page(
        document.page[1],
        executor,
        tracker=RecordingTracker(),
        translated_ids=set(),
        chain_claim=ChainClaim(),
        article_context=context,
    )

    assert len(executor.submissions) == 1
    batch = executor.submissions[0][1][0]
    assert batch.paragraphs.count(paragraphs[3]) == 1
    assert executor.submissions[0][2]["article_brief"] == "shared brief"


def test_missing_and_wrong_document_identity_fail_before_translation():
    document, article_ir, _paragraphs = make_article_context_fixture()
    missing = object.__new__(ILTranslatorLLMOnly)
    missing.translation_config = SimpleNamespace()
    with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
        missing.translate(document)

    wrong = object.__new__(ILTranslatorLLMOnly)
    wrong.translation_config = SimpleNamespace(
        magazine_state=minimal_pipeline.MagazineState(
            _article_document_ir=article_ir,
            _structure_started=True,
            _structure_document_identity=id(object()),
        )
    )
    with pytest.raises(ValueError, match="different document"):
        wrong.translate(document)
    assert minimal_pipeline.get_article_document_ir(wrong.translation_config) is article_ir


def test_second_structure_build_attempt_fails_without_replacing_ir():
    document, article_ir, _paragraphs = make_article_context_fixture()
    config = SimpleNamespace(
        magazine_state=minimal_pipeline.MagazineState(
            _article_document_ir=article_ir,
            _structure_started=True,
            _structure_document_identity=id(document),
        )
    )

    with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
        minimal_pipeline.after_styles(config, document)
    assert minimal_pipeline.get_article_document_ir(config) is article_ir


def test_chain_apply_runs_after_both_executor_contexts_exit(monkeypatch, tmp_path):
    document, article_ir, _paragraphs = make_article_context_fixture()
    events: list[str] = []
    active = 0

    class Executor:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            nonlocal active
            active += 1
            events.append("executor-enter")
            return self

        def __exit__(self, *_args):
            nonlocal active
            active -= 1
            events.append("executor-exit")

    claim = ChainClaim()
    claim.freeze()

    class Plan:
        def __init__(self):
            self.claim = claim

        def apply(self, _pbar):
            assert active == 0
            events.append("apply")

    monkeypatch.setattr(llm_module, "PriorityThreadPoolExecutor", Executor)
    monkeypatch.setattr(
        llm_module,
        "plan_article_context",
        lambda *_args: events.append("context-plan")
        or llm_module.ArticleContext(article_document_ir=article_ir),
    )
    monkeypatch.setattr(
        llm_module,
        "plan_chain_translation",
        lambda *_args: events.append("chain-plan") or Plan(),
    )

    driver = object.__new__(ILTranslatorLLMOnly)
    state = minimal_pipeline.MagazineState(
        _article_document_ir=article_ir,
        _structure_started=True,
        _structure_document_identity=id(document),
    )

    @contextmanager
    def stage_start(*_args):
        yield None

    driver.translation_config = SimpleNamespace(
        magazine_state=state,
        magazine_article_context=True,
        magazine_chain_translate=True,
        progress_monitor=SimpleNamespace(stage_start=stage_start),
        shared_context_cross_split_part=SimpleNamespace(
            first_paragraph=object(), recent_title_paragraph=None
        ),
        pool_max_workers=1,
        debug=False,
        working_dir=None,
        get_working_file_path=lambda name: tmp_path / name,
    )
    driver.il_translator = SimpleNamespace(docs=None)
    driver.shared_context_cross_split_part = SimpleNamespace()
    driver.process_cross_page_paragraph = lambda *_args: events.append("cross-page")
    driver.process_cross_column_paragraph = lambda *_args: events.append(
        "cross-column"
    )
    driver.process_page = lambda *_args: events.append("ordinary")
    driver.total_count = driver.ok_count = driver.fallback_count = 0

    driver.translate(document)

    assert events.index("context-plan") < events.index("executor-enter")
    assert events.index("chain-plan") < events.index("executor-enter")
    assert events[-1] == "apply"


@pytest.mark.parametrize("failure_site", ["mapper", "line-packer"])
def test_unexpected_capacity_errors_propagate(monkeypatch, failure_site):
    class ExplodingMapper(FixedWidthMapper):
        def map(self, original_font, character):
            if failure_site == "mapper":
                raise RuntimeError("mapper exploded")
            return super().map(original_font, character)

    typesetter = Typesetting(
        SimpleNamespace(lang_out="zh"), font_mapper=ExplodingMapper()
    )
    if failure_site == "line-packer":
        monkeypatch.setattr(
            typesetter,
            "_layout_typesetting_units",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("packer exploded")),
        )

    with pytest.raises(RuntimeError, match="exploded"):
        typesetter.fit_text_to_slot(
            "甲乙",
            PdfStyle(font_id="body", font_size=10.0),
            "zh",
            Box(0.0, 0.0, 20.0, 15.0),
            paragraph_start=False,
            minimum_font_size=4.0,
            fit_tolerance=0.01,
            line_skip=1.5,
        )
