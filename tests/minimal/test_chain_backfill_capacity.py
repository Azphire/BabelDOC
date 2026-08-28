from __future__ import annotations

from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import PdfStyle
from babeldoc.format.pdf.document_il.midend.typesetting import FIT_ALL
from babeldoc.format.pdf.document_il.midend.typesetting import FIT_PREFIX
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine.article_context import EMPTY_CONTEXT
from babeldoc.magazine.chain_translation import ESCALATION_OVERFLOW
from babeldoc.magazine.chain_translation import plan_chain_translation
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import RecordingTracker
from tests.minimal.fakes import document_digest
from tests.minimal.fakes import make_chain_fixture


def _typesetter() -> Typesetting:
    config = type("Config", (), {"lang_out": "zh"})()
    return Typesetting(config, font_mapper=FixedWidthMapper())


def _fit(text, width, *, protected=()):
    return _typesetter().fit_text_to_slot(
        text,
        PdfStyle(font_id="body", font_size=10.0),
        "zh",
        Box(0.0, 0.0, width, 15.0),
        paragraph_start=False,
        protected_ranges=protected,
        minimum_font_size=4.0,
        fit_tolerance=0.01,
        line_skip=1.5,
    )


def test_real_typesetter_finds_maximum_legal_prefix():
    result = _fit("甲乙丙丁戊己", 25.0)
    assert result.status == FIT_PREFIX
    assert result.consumed_range == (0, 5)
    assert result.text == "甲乙丙丁戊"
    assert len(result.line_metrics) == 1


def test_capacity_protects_placeholder_and_punctuation_boundaries():
    placeholder = _fit("abc [[X]] def", 20.0, protected=((4, 9),))
    assert placeholder.text == "abc "
    assert placeholder.consumed_range[1] not in range(5, 9)

    closing = _fit("甲乙，丙", 15.0)
    assert closing.text == "甲乙，"
    opening = _fit("甲乙《丙", 15.0)
    assert opening.text == "甲乙"


def test_capacity_plan_is_non_mutating_and_conserves_whole_target(tmp_path):
    target = "译" * 12
    document, article_ir, paragraphs, translator = make_chain_fixture(
        target, tmp_path
    )
    before = document_digest(document)

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    assert document_digest(document) == before
    assert len(plan.entries) == 1
    allocation = plan.entries[0].allocation
    assert "".join(fragment.text for fragment in allocation.fragments) == target
    released = [fragment.released for fragment in allocation.fragments]
    assert released == sorted(released)
    assert all(
        fragment.measurement_record["fit_status"] in {FIT_ALL, FIT_PREFIX, "released"}
        for fragment in allocation.fragments
    )

    plan.apply()
    assert len(translator.il_translator.posted) == len(paragraphs)
    assert set(translator.il_translator.posted) == {
        id(paragraph) for paragraph in paragraphs
    }
    assert "".join(paragraph.unicode for paragraph in paragraphs) == target


def test_capacity_overflow_has_no_partial_apply(tmp_path):
    target = "溢" * 41
    document, article_ir, paragraphs, translator = make_chain_fixture(
        target, tmp_path
    )
    before = document_digest(document)

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    assert document_digest(document) == before
    assert not plan.entries
    assert plan.outcomes[0]["reason"] == ESCALATION_OVERFLOW
    plan.apply()
    assert not translator.il_translator.posted
    assert all(paragraph.unicode == "source member" for paragraph in paragraphs)


def test_second_writeback_failure_rolls_back_every_member(tmp_path):
    target = "译" * 12
    document, article_ir, paragraphs, translator = make_chain_fixture(
        target, tmp_path
    )
    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )
    before = document_digest(document)
    translator.il_translator.fail_post_at = 2

    plan.apply()

    assert translator.il_translator.post_attempts == 2
    assert document_digest(document) == before
    assert not plan.entries
    assert plan.outcomes[0]["result_state"] == "failed_with_issue"
