from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
    ILTranslatorLLMOnly,
)
from babeldoc.magazine.article_context import CachedBriefClient
from babeldoc.magazine.article_context import plan_article_context
from tests.minimal.fakes import make_article_context_fixture


class RecordingBriefTransport:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt_text: str) -> str:
        self.prompts.append(prompt_text)
        return json.dumps(
            {
                "title_translation": f"brief-{len(self.prompts)}",
                "register": "measured feature prose",
                "names": [],
            }
        )


class ForbiddenCache:
    def get(self, _key):
        raise AssertionError("brief cache must remain bypassed")

    def set(self, _key, _value):
        raise AssertionError("brief cache must remain bypassed")


def _translator(tmp_path: Path):
    def working_file(name: str):
        return tmp_path / name

    return SimpleNamespace(
        translation_config=SimpleNamespace(
            lang_out="zh",
            get_working_file_path=working_file,
        ),
        translate_engine=object(),
    )


def test_article_briefs_use_one_bounded_fake_request_per_article(tmp_path):
    document, article_ir, paragraphs = make_article_context_fixture()
    transport = RecordingBriefTransport()
    client = CachedBriefClient(
        transport=transport,
        cache=ForbiddenCache(),
        identity="recording-fake/zh",
        ignore_cache=True,
    )

    context = plan_article_context(
        _translator(tmp_path), document, article_ir, client=client
    )

    assert context.article_document_ir is article_ir
    assert len(transport.prompts) == 2
    first = context.brief_for_page(document.page[0])
    assert first
    assert context.brief_for_page(document.page[1]) == first
    assert context.brief_for_page(document.page[2]) != first
    assert context.brief_for_page_pair(document.page[0], document.page[1]) == first
    assert context.brief_for_page_pair(document.page[1], document.page[2]) is None
    assert context.brief_for_page(document.page[0]) == context.brief_for_page(
        document.page[1]
    )
    assert paragraphs[1].chain_id == paragraphs[2].chain_id

    report = json.loads((tmp_path / "article_context.report.json").read_text())
    assert report["counts"] == {
        "articles": 2,
        "requested": 2,
        "briefs": 2,
        "failed": 0,
        "from_cache": 0,
        "requests": 2,
    }
    assert all(row["attempts"] == 1 for row in report["articles"])


def test_cross_article_pair_never_inherits_an_article_brief(tmp_path):
    document, article_ir, _paragraphs = make_article_context_fixture()
    transport = RecordingBriefTransport()
    client = CachedBriefClient(
        transport=transport,
        cache=ForbiddenCache(),
        ignore_cache=True,
    )
    context = plan_article_context(
        _translator(tmp_path), document, article_ir, client=client
    )

    assert context.brief_for_page_pair(document.page[1], document.page[2]) is None
    assert len(transport.prompts) == len(article_ir.articles)


def test_article_brief_is_numbered_context_not_glossary_input():
    class RecordingGlossary:
        name = "recording"

        def __init__(self) -> None:
            self.queries = []

        def get_active_entries_for_text(self, text):
            self.queries.append(text)
            return []

    glossary = RecordingGlossary()
    driver = object.__new__(ILTranslatorLLMOnly)
    driver.translation_config = SimpleNamespace(
        lang_out="zh", custom_system_prompt=None
    )
    driver._cached_glossaries = [glossary]

    prompt = driver._build_llm_prompt(
        json_input_str='[{"id": 0, "input": "batch source only"}]',
        title_paragraph=SimpleNamespace(unicode="global title", debug_id="global"),
        local_title_paragraph=SimpleNamespace(unicode="local title", debug_id="local"),
        batch_text_for_glossary_matching="batch source only",
        article_brief="ARTICLE_BRIEF_SENTINEL",
    )

    assert "3. ARTICLE_BRIEF_SENTINEL" in prompt
    assert glossary.queries == ["batch source only"]
