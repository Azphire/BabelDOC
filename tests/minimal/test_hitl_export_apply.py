from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.glossary import Glossary
from babeldoc.glossary import GlossaryEntry
from babeldoc.magazine import drop_cap
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import hitl
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import ArticlePolicyEvidence
from babeldoc.magazine.article_ir import ArticleRegionSlot
from babeldoc.magazine.article_ir import SourceElementRef
from tests.minimal.test_drop_cap_keep_flatten import RuntimeConfig
from tests.minimal.test_drop_cap_keep_flatten import document_digest
from tests.minimal.test_drop_cap_keep_flatten import make_document
from tests.minimal.test_drop_cap_keep_flatten import ordinary_paragraph
from tests.minimal.test_drop_cap_keep_flatten import source_drop_cap_paragraph

ROOT = Path(__file__).resolve().parents[2]
FIXED_DECISIONS = ROOT / "reviews" / "Courier-en.decisions.json"
FIXED_BLOB = "39b40b848671f41b3a6415cedbc4a0ecefc586ec"

# The fourteen terms reviews/Courier-en.decisions.json rules on, laid over the
# fixture's paragraphs so this document really does say what the file rules
# about. The rulings are only checked against the source now, so a fixture whose
# pages never mention a ruled name would have every ruling skipped as absent and
# the applied counts below would assert nothing.
FIXED_TERM_PARAGRAPHS: tuple[tuple[str, ...], ...] = (
    ("Marcelo Silva de Sousa", "Lagipoiva Cherelle Jackson"),
    ("Daniel Robinson", "David Jefferson"),
    ("The UNESCO Courier",),
    ("CourierT H E UNESCO",),
    ("Yang Sha", "Du Junzhi"),
    ("Sisco Auala", "Anna Ruohonen"),
    ("Jim Al-Khalili", "Chimamanda Ngozi Adichie"),
    ("Ora Marek-Martinez", "Katerina Markelova"),
)


def fixture_paragraph_text(index: int) -> str:
    named = " and ".join(FIXED_TERM_PARAGRAPHS[index])
    return f"ordinary paragraph {index} names {named}"


def git_blob_id(data: bytes) -> str:
    data = data.replace(b"\r\n", b"\n")
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def isolate_review_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path]:
    source = tmp_path / "source-reviews"
    generated = tmp_path / "generated-reviews"
    source.mkdir(parents=True)
    monkeypatch.setattr(hitl, "SOURCE_REVIEWS_DIR", source)
    monkeypatch.setattr(hitl, "GENERATED_REVIEWS_DIR", generated)
    return source, generated


def write_decisions(source: Path, sample: str, payload: dict) -> Path:
    path = source / f"{sample}.decisions.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def selected_fixture(
    tmp_path: Path,
    *,
    sample: str = "Courier-en",
    candidate: bool = True,
) -> tuple[RuntimeConfig, il.Document, ArticleDocumentIR]:
    page_seven = [
        ordinary_paragraph(fixture_paragraph_text(index))
        for index in range(len(FIXED_TERM_PARAGRAPHS))
    ]
    page_seven.append(
        source_drop_cap_paragraph() if candidate else ordinary_paragraph("not candidate")
    )
    docs = make_document(page_seven, physical_page=7, total_pages=8)
    page_box = il.Box(0.0, 0.0, 180.0, 120.0)
    docs.page.append(
        il.Page(
            page_number=7,
            unit="pt",
            mediabox=il.Mediabox(box=page_box),
            cropbox=il.Cropbox(box=copy.deepcopy(page_box)),
            pdf_paragraph=[],
        )
    )
    docs.page[0].page_kind = "body"
    docs.page[0].page_kind_conf = 0.81
    docs.page[0].page_kind_source = "machine"
    article_id = "article-selected"
    elements = tuple(
        SourceElementRef(
            source_ref=f"p1#{index}",
            page=1,
            column=0,
            reading_order=index,
            role="body",
            source_box=(
                float(paragraph.box.x),
                float(paragraph.box.y),
                float(paragraph.box.x2),
                float(paragraph.box.y2),
            ),
            source_text_hash=hashlib.sha256(
                (paragraph.unicode or "").encode("utf-8")
            ).hexdigest(),
            style_hash=drop_cap_intent.style_hash(paragraph.pdf_style),
        )
        for index, paragraph in enumerate(page_seven)
    )
    article = ArticleIR(
        article_id=article_id,
        pages=(1, 2),
        elements=elements,
        slots=(
            ArticleRegionSlot(
                article_id=article_id,
                page=1,
                column=0,
                slot_order=0,
                box=(0.0, 0.0, 180.0, 120.0),
                fixed_obstacle_refs=(),
                capacity_hint=21600.0,
            ),
            ArticleRegionSlot(
                article_id=article_id,
                page=2,
                column=0,
                slot_order=1,
                box=(0.0, 0.0, 180.0, 120.0),
                fixed_obstacle_refs=(),
                capacity_hint=21600.0,
            ),
        ),
        chain_ids=(),
        policy_evidence=(
            ArticlePolicyEvidence(1, "body", None, None, True),
            ArticlePolicyEvidence(2, "body", None, None, True),
        ),
    )
    article_ir = ArticleDocumentIR(
        articles=(article,),
        by_page={1: article_id, 2: article_id},
        by_element={element.source_ref: article_id for element in elements},
        by_chain={},
    )
    config = RuntimeConfig(tmp_path / "work", sample=sample, language="zh-CN")
    return config, docs, article_ir


def assert_no_requests(config: RuntimeConfig) -> None:
    assert config.translator.requests == 0
    assert config.term_translator.requests == 0


def test_no_decisions_exports_machine_review_without_html_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, generated = isolate_review_paths(monkeypatch, tmp_path)
    config, docs, article_ir = selected_fixture(tmp_path, sample="NoDecision")
    state = hitl.begin_run(config, docs)
    hitl.page_kind_pass(config, docs, state)
    report = hitl.before_translation(config, docs, article_ir, state)
    assert state.page_pass_completed and state.translation_pass_completed
    assert state.decisions is None and report["decisions_file"] is None
    assert (config.working_dir / "NoDecision.review.json").is_file()
    assert (generated / "NoDecision.review.json").is_file()
    assert list(source.iterdir()) == []
    assert not list(tmp_path.rglob("*.html"))
    assert report["passes"] == {
        "page_kinds": True,
        "before_translation": True,
    }
    assert state.glossary_freeze is not None
    assert state.glossary_freeze.entry_count == 0
    assert_no_requests(config)


def test_fixed_decisions_apply_terms_scope_and_physical_drop_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_bytes = FIXED_DECISIONS.read_bytes()
    assert git_blob_id(fixed_bytes) == FIXED_BLOB
    fixed = json.loads(fixed_bytes)
    assert len(fixed["terms"]) == 14
    assert set(fixed["terms"]) == {
        term for paragraph in FIXED_TERM_PARAGRAPHS for term in paragraph
    }
    assert fixed["page_kinds"] == {"1": "toc"}
    assert fixed["drop_caps"]["p7#8"] == "keep"
    source, generated = isolate_review_paths(monkeypatch, tmp_path)
    copied = write_decisions(source, "Courier-en", fixed)
    copied_before = copied.read_bytes()
    config, docs, article_ir = selected_fixture(tmp_path)
    state = hitl.begin_run(config, docs)
    assert state.physical_to_local == {7: 1, 8: 2}
    hitl.page_kind_pass(config, docs, state)
    assert state.page_pass_completed and not state.translation_pass_started
    assert docs.page[0].page_kind == "body"
    report = hitl.before_translation(config, docs, article_ir, state)
    assert state.translation_pass_completed
    assert report["applied"]["terms"]["ruled"] == 14
    assert report["applied"]["terms_conservation"] == {
        "ruled": 14,
        "applied": 14,
        "skipped": 0,
    }
    assert not any(item["section"] == "terms" for item in report["skipped"])
    assert report["decisions_sha256"] == hashlib.sha256(copied_before).hexdigest()
    assert state.glossary_freeze is not None
    assert state.glossary_freeze.entry_count == 14
    assert [item["paragraph"] for item in report["applied"]["drop_caps"]] == [
        "p7#8"
    ]
    skipped = {
        (item["section"], item["key"], item["reason"])
        for item in report["skipped"]
    }
    assert ("page_kinds", "1", hitl.OUT_OF_SELECTED_SCOPE) in skipped
    assert ("drop_caps", "p4#3", hitl.OUT_OF_SELECTED_SCOPE) in skipped
    assert ("drop_caps", "p5#5", hitl.OUT_OF_SELECTED_SCOPE) in skipped
    assert not any(item[1] == "p7#8" for item in skipped)
    intent = drop_cap_intent.intent_for(config, "p7#8")
    assert intent is not None and intent.decision == "keep"
    assert intent.article_id == article_ir.by_element["p1#8"]
    assert docs.page[0].pdf_paragraph[8].drop_cap_decision == "keep"
    assert copied.read_bytes() == copied_before
    assert FIXED_DECISIONS.read_bytes() == fixed_bytes
    assert (config.working_dir / "Courier-en.review.json").is_file()
    assert (generated / "Courier-en.review.json").is_file()
    assert not list(tmp_path.rglob("*.html"))
    assert_no_requests(config)
    with pytest.raises(hitl.HitlError, match="already attempted"):
        hitl.before_translation(config, docs, article_ir, state)


def test_selected_page_kind_is_applied_in_first_hitl_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _generated = isolate_review_paths(monkeypatch, tmp_path)
    write_decisions(
        source,
        "SelectedKind",
        {
            "sample": "SelectedKind",
            "terms": {},
            "page_kinds": {"7": "toc"},
            "drop_caps": {},
        },
    )
    config, docs, _article_ir = selected_fixture(tmp_path, sample="SelectedKind")
    state = hitl.begin_run(config, docs)
    hitl.page_kind_pass(config, docs, state)
    assert state.page_pass_completed and not state.translation_pass_started
    assert docs.page[0].page_kind == "toc"
    assert docs.page[0].page_kind_conf == 1.0
    assert docs.page[0].page_kind_source == "human"
    assert state.report["applied"]["page_kinds"][0]["page"] == 7
    assert_no_requests(config)


@pytest.mark.parametrize(
    ("sample", "section", "value", "message"),
    [
        ("BadPageKind", "page_kinds", {"7": "not-a-kind"}, "page type"),
        ("MissingRef", "drop_caps", {"p7#99": "keep"}, "no such paragraph"),
        ("BadVerdict", "drop_caps", {"p7#8": "decorate"}, "outside"),
        ("StemMismatch", "sample", "AnotherSample", "does not bind input"),
    ],
)
def test_invalid_decisions_fail_before_page_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample: str,
    section: str,
    value,
    message: str,
) -> None:
    source, _generated = isolate_review_paths(monkeypatch, tmp_path)
    payload = {
        "sample": sample,
        "terms": {},
        "page_kinds": {},
        "drop_caps": {},
    }
    payload[section] = value
    write_decisions(source, sample, payload)
    config, docs, _article_ir = selected_fixture(tmp_path, sample=sample)
    before = document_digest(docs)
    state = hitl.begin_run(config, docs)
    with pytest.raises(hitl.HitlError, match=message):
        hitl.page_kind_pass(config, docs, state)
    assert document_digest(docs) == before
    assert state.page_pass_started and not state.page_pass_completed
    assert not drop_cap_intent.intents_for(config)
    assert state.glossary_freeze is None
    assert not list(tmp_path.rglob("*.html"))
    assert_no_requests(config)


def assert_prepare_rollback(
    config: RuntimeConfig,
    docs: il.Document,
    state: hitl.HitlRunState,
    before: dict,
) -> None:
    shared = config.shared_context_cross_split_part
    assert document_digest(docs) == before["document"]
    assert shared.user_glossaries is before["user_ref"]
    assert list(shared.user_glossaries) == before["users"]
    assert shared.auto_extracted_glossary is before["auto"]
    assert state.draft == before["draft"]
    assert state.report == before["report"]
    assert state.glossary_freeze is None
    assert state.translation_pass_started and not state.translation_pass_completed
    assert drop_cap_intent.current_generation(config) == before["generation"]
    assert [
        intent.as_record()
        for intent in drop_cap_intent.intents_for(config).values()
    ] == before["intents"]
    assert_no_requests(config)


def prepare_snapshot(
    config: RuntimeConfig,
    docs: il.Document,
    state: hitl.HitlRunState,
) -> dict:
    shared = config.shared_context_cross_split_part
    return {
        "document": document_digest(docs),
        "user_ref": shared.user_glossaries,
        "users": list(shared.user_glossaries),
        "auto": shared.auto_extracted_glossary,
        "draft": copy.deepcopy(state.draft),
        "report": copy.deepcopy(state.report),
        "generation": drop_cap_intent.current_generation(config),
        "intents": [
            intent.as_record()
            for intent in drop_cap_intent.intents_for(config).values()
        ],
    }


@pytest.mark.parametrize(
    ("sample", "drop_caps", "message"),
    [
        (
            "HashMismatch",
            {"p7#8": {"decision": "keep", "source_hash": "stale-hash"}},
            "source text hash",
        ),
        ("NonCandidate", {"p7#0": "keep"}, "not a current drop-cap candidate"),
    ],
)
def test_selected_hash_or_noncandidate_failure_rolls_back_prepare_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample: str,
    drop_caps: dict,
    message: str,
) -> None:
    source, _generated = isolate_review_paths(monkeypatch, tmp_path)
    write_decisions(
        source,
        sample,
        {
            "sample": sample,
            "terms": {"human term": "human target"},
            "page_kinds": {},
            "drop_caps": drop_caps,
        },
    )
    config, docs, article_ir = selected_fixture(tmp_path, sample=sample)
    shared = config.shared_context_cross_split_part
    shared.user_glossaries.append(
        Glossary("existing", [GlossaryEntry("existing source", "existing target")])
    )
    shared.auto_extracted_glossary = Glossary(
        "auto", [GlossaryEntry("auto source", "auto target")]
    )
    state = hitl.begin_run(config, docs)
    hitl.page_kind_pass(config, docs, state)
    before = prepare_snapshot(config, docs, state)
    with pytest.raises(hitl.HitlError, match=message):
        hitl.before_translation(config, docs, article_ir, state)
    assert_prepare_rollback(config, docs, state, before)
    with pytest.raises(hitl.HitlError, match="already attempted"):
        hitl.before_translation(config, docs, article_ir, state)


def test_late_prepare_exception_restores_terms_intents_and_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = json.loads(FIXED_DECISIONS.read_text(encoding="utf-8"))
    source, _generated = isolate_review_paths(monkeypatch, tmp_path)
    write_decisions(source, "Courier-en", fixed)
    config, docs, article_ir = selected_fixture(tmp_path)
    shared = config.shared_context_cross_split_part
    shared.user_glossaries.append(
        Glossary("existing", [GlossaryEntry("existing source", "existing target")])
    )
    shared.auto_extracted_glossary = Glossary(
        "auto", [GlossaryEntry("auto source", "auto target")]
    )
    state = hitl.begin_run(config, docs)
    hitl.page_kind_pass(config, docs, state)
    before = prepare_snapshot(config, docs, state)

    class SentinelError(Exception):
        pass

    marker = SentinelError("injected after term and decision apply")

    def fail_after_apply(*_args, **_kwargs):
        raise marker

    monkeypatch.setattr(drop_cap, "apply", fail_after_apply)
    with pytest.raises(SentinelError) as raised:
        hitl.before_translation(config, docs, article_ir, state)
    assert raised.value is marker
    assert_prepare_rollback(config, docs, state, before)
    assert not list(tmp_path.rglob("*.html"))


def test_prepare_transaction_does_not_copy_unrelated_page_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = json.loads(FIXED_DECISIONS.read_text(encoding="utf-8"))
    source, _generated = isolate_review_paths(monkeypatch, tmp_path)
    write_decisions(source, "Courier-en", fixed)
    config, docs, article_ir = selected_fixture(tmp_path)

    class UncopyablePagePayload:
        def __deepcopy__(self, _memo):
            raise AssertionError("unrelated page payload was deep-copied")

    payload = UncopyablePagePayload()
    docs.page[0].pdf_xobject.append(payload)
    state = hitl.begin_run(config, docs)
    hitl.page_kind_pass(config, docs, state)

    report = hitl.before_translation(config, docs, article_ir, state)

    assert report["passes"]["before_translation"] is True
    assert state.translation_pass_completed is True
    assert docs.page[0].pdf_xobject[-1] is payload
