from __future__ import annotations

import hashlib
import json

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.article_context import EMPTY_CONTEXT
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import ArticlePolicyEvidence
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.chain_translation import plan_chain_translation
from tests.minimal.fakes import RecordingTracker
from tests.minimal.fakes import StubChainTranslator
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph


class _QueuedEngine:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.llm_calls: list[tuple[str, dict]] = []

    def llm_translate(self, prompt: str, **kwargs) -> str:
        self.llm_calls.append((prompt, kwargs))
        if not self.responses:
            raise AssertionError("unexpected model call")
        return self.responses.pop(0)


def _fixture(tmp_path, *, three_member_title: bool = False):
    label = "title" if three_member_title else "text"
    first = _paragraph(
        "The recovery remained difficult",
        "member-0",
        (60.0, 0.0, 110.0, 20.0),
        label=label,
        chain_id="runtime-chain",
        chain_index=0,
    )
    second = _paragraph(
        "and the outlook uncertain.",
        "member-1",
        (0.0, 0.0, 50.0, 20.0),
        label=label,
        chain_id="runtime-chain",
        chain_index=1,
    )
    members = [first, second]
    pages = [_page(0, members)]
    element_rows = [
        ("p1#1", 1, 0, 4, second),
        ("p1#0", 1, 1, 9, first),
    ]
    if three_member_title:
        third = _paragraph(
            "under the same conditions.",
            "member-2",
            (0.0, 0.0, 50.0, 20.0),
            label=label,
            chain_id="runtime-chain",
            chain_index=2,
        )
        members.append(third)
        pages = [_page(0, members[:2]), _page(1, members[2:])]
        element_rows.append(("p2#0", 2, 0, 10, third))
    elements = tuple(
        SourceElementRef(
            source_ref=source_ref,
            page=page,
            column=column,
            reading_order=reading_order,
            role=label,
            source_box=(
                float(paragraph.box.x),
                float(paragraph.box.y),
                float(paragraph.box.x2),
                float(paragraph.box.y2),
            ),
            source_text_hash=hashlib.sha256(
                paragraph.unicode.encode("utf-8")
            ).hexdigest(),
            style_hash="fixed-style",
        )
        for source_ref, page, column, reading_order, paragraph in element_rows
    )
    refs = tuple(row[0] for row in element_rows)
    article_pages = (1, 2) if three_member_title else (1,)
    article = ArticleIR(
        article_id="article-a",
        pages=article_pages,
        elements=elements,
        slots=(),
        chain_ids=("canonical-chain",),
        policy_evidence=tuple(
            ArticlePolicyEvidence(page, "member", "feature", None, True)
            for page in article_pages
        ),
    )
    article_ir = ArticleDocumentIR(
        articles=(article,),
        by_page=dict.fromkeys(article_pages, "article-a"),
        by_element=dict.fromkeys(refs, "article-a"),
        by_chain={"canonical-chain": "article-a"},
        by_chain_member=dict.fromkeys(refs, "canonical-chain"),
    )
    document = il_version_1.Document(page=pages, total_pages=len(pages))
    translator = StubChainTranslator(tmp_path, "")
    translator.translation_config.lang_out = "en"
    return document, article_ir, members, translator


def test_confirmed_reading_order_conflict_reaches_joint_translation(tmp_path):
    document, article_ir, members, translator = _fixture(tmp_path)
    target = "The recovery remained difficult and the outlook uncertain."
    translator.translate_engine = _QueuedEngine(
        [
            json.dumps(
                {
                    "action": "confirm_joint_chain",
                    "reason": "The second fragment directly completes the first.",
                }
            ),
            json.dumps([{"id": 0, "output": target}]),
        ]
    )

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    report = plan.as_record()
    topology = report["topology_adjudication"]
    record = topology["records"][0]
    assert topology["counts"] == {
        "detected": 1,
        "decision_calls": 1,
        "confirmed": 1,
        "admitted": 1,
        "applied": 1,
    }
    assert len(translator.translate_engine.llm_calls) == 2
    assert "<CHAIN_BOUNDARY>" in translator.translate_engine.llm_calls[0][0]
    assert report["counts"]["translator_calls"] == 1
    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.as_record()["result_state"] == "joint_success"
    assert entry.as_record()["ordered_source_refs"] == ["p1#0", "p1#1"]
    assert [fragment.slot_order for fragment in entry.allocation.fragments] == [0, 1]
    assert all(plan.claim.claims_paragraph(member) for member in members)
    assert record["detected"]
    assert record["confirmed"]
    assert record["admitted"]
    assert record["applied"]
    assert record["issue"]["reading_orders"] == [9, 4]
    assert record["issue"]["chain_indices"] == [0, 1]
    assert record["final_chain_result_state"] == "joint_success"
    assert record["joint_translator_call_count"] == 1


def test_topology_decision_cannot_override_other_or_invalid_conflicts(tmp_path):
    document, article_ir, _members, translator = _fixture(tmp_path / "invalid-json")
    translator.translate_engine = _QueuedEngine(["not-json"])

    invalid_reply_plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    invalid_report = invalid_reply_plan.as_record()
    invalid_record = invalid_report["topology_adjudication"]["records"][0]
    assert not invalid_reply_plan.entries
    assert not invalid_reply_plan.claim
    assert len(translator.translate_engine.llm_calls) == 1
    assert invalid_report["counts"]["translator_calls"] == 0
    assert invalid_report["outcomes"][0]["fallback_reason"] == (
        "invalid_chain_topology"
    )
    assert invalid_record["decision"]["status"] == "invalid_decision_reply"
    assert invalid_record["admission"]["status"] == "admission_refused"
    assert invalid_record["final_chain_result_state"] == "protected_untranslated"

    document, article_ir, _members, translator = _fixture(
        tmp_path / "other-conflict", three_member_title=True
    )
    translator.translate_engine = _QueuedEngine(
        [json.dumps({"action": "confirm_joint_chain", "reason": "would confirm"})]
    )

    other_conflict_plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    other_report = other_conflict_plan.as_record()
    other_record = other_report["topology_adjudication"]["records"][0]
    assert not other_conflict_plan.entries
    assert not other_conflict_plan.claim
    assert translator.translate_engine.llm_calls == []
    assert other_report["counts"]["translator_calls"] == 0
    assert other_report["topology_adjudication"]["counts"]["decision_calls"] == 0
    assert other_report["outcomes"][0]["fallback_reason"] == ("invalid_chain_topology")
    assert other_record["decision"]["status"] == "admission_refused"
    assert other_record["admission"]["reason"] == (
        "other_topology_conflict:cross_page_title_shape"
    )
    assert other_record["final_chain_result_state"] == "protected_untranslated"
