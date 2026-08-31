"""The B16 repair action: refit with the first line advanced past an ornament.

The loop's backstop for what T1's healing cannot reach: a paragraph whose
translated ink still stands on an ornament-grade path. The action re-sets
the paragraph in its own source box with a repair-owned clearance width --
the same channel the typesetting stage reads for captured avoidances -- and
every admission is deterministic and fail-closed: not an ornament finding,
not a fixed asset at the stated position, not in the first line's band, or
not fitting after the advance each refuse with their own name, and a refused
repair restores the paragraph and the width store to what they were.
"""

from __future__ import annotations

import copy

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import indent_policy
from babeldoc.magazine import minimal_detection
from babeldoc.magazine import minimal_repair
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.detectors.base import Issue
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import _page

Box = il_version_1.Box

SOURCE_BOX = (10.0, 60.0, 110.0, 90.0)
ORNAMENT = (10.5, 80.0, 16.0, 86.0)


def _style():
    return il_version_1.PdfStyle(
        font_id="body", font_size=10.0, graphic_state=il_version_1.GraphicState()
    )


def _chars(text: str, x: float, y: float = 80.0, y2: float = 88.0):
    return [
        il_version_1.PdfCharacter(
            pdf_style=_style(),
            box=Box(x + index * 5.0, y, x + (index + 1) * 5.0, y2),
            char_unicode=character,
        )
        for index, character in enumerate(text)
    ]


def _typeset_paragraph(text: str, first_x: float):
    """A paragraph as detection saw it: laid out characters on one line."""
    run = il_version_1.PdfSameStyleCharacters(
        box=Box(*SOURCE_BOX), pdf_style=_style()
    )
    run.pdf_character = _chars(text, first_x)
    return il_version_1.PdfParagraph(
        box=Box(*SOURCE_BOX),
        pdf_style=_style(),
        unicode=text,
        debug_id="overlapped",
        layout_label="plain text",
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(pdf_same_style_characters=run)
        ],
    )


class ClearanceTypesetter:
    """Renders the way the real stage does: first line starts past the width."""

    def __init__(self, translation_config, *, honor_clearance=True):
        self.font_mapper = FixedWidthMapper()
        self.translation_config = translation_config
        self.honor_clearance = honor_clearance
        self.calls = 0

    def render_paragraph(self, paragraph, page, fonts):
        self.calls += 1
        offset = (
            indent_policy.functional_clearance_width(
                self.translation_config, paragraph
            )
            or 0.0
            if self.honor_clearance
            else 0.0
        )
        run = il_version_1.PdfSameStyleCharacters(
            box=copy.deepcopy(paragraph.box), pdf_style=_style()
        )
        run.pdf_character = _chars(
            paragraph.unicode or "", float(paragraph.box.x) + offset
        )
        paragraph.pdf_paragraph_composition = [
            il_version_1.PdfParagraphComposition(pdf_same_style_characters=run)
        ]


def fixture(*, ornament=ORNAMENT, first_x=None):
    text = "overlap"
    paragraph = _typeset_paragraph(
        text, SOURCE_BOX[0] if first_x is None else first_x
    )
    page = _page(0, [paragraph])
    page.pdf_curve = [
        il_version_1.PdfCurve(
            box=Box(*ornament),
            graphic_state=il_version_1.GraphicState(),
            fill_background=True,
            stroke_path=False,
        )
    ]
    docs = il_version_1.Document(page=[page], total_pages=1)
    element = SourceElementRef(
        source_ref="p1#0",
        page=1,
        column=0,
        reading_order=0,
        role="body",
        source_box=SOURCE_BOX,
        source_text_hash="hash",
        style_hash="style",
    )
    article_ir = ArticleDocumentIR(
        articles=(ArticleIR("article-a", (1,), (element,), (), (), ()),),
        by_page={1: "article-a"},
        by_element={"p1#0": "article-a"},
        by_chain={},
    )
    baseline = minimal_detection.capture_baseline(
        docs, article_ir, labeled_pages=((7, docs.page[0]),)
    )
    return docs, article_ir, baseline, paragraph


def issue_for(paragraph, *, evidence_extra=None, bbox=ORNAMENT):
    evidence = {
        "iou": 0.01,
        "artwork_source": "pdf_curve",
        "artwork_index": 0,
        "asset_class": "ornament_path",
        "ornament_bbox": list(bbox),
        "intersection_box": list(bbox),
        "intersection_area_pt2": 30.0,
        "min_intersection_area_pt2": 4.0,
        "debug_id": paragraph.debug_id,
        "layout_label": paragraph.layout_label,
        "excerpt": paragraph.unicode,
    }
    evidence.update(evidence_extra or {})
    return Issue(
        kind="text_figure_overlap",
        page=7,
        paragraph_refs=("p7#0",),
        geometry=None,
        severity="medium",
        evidence=evidence,
        detector="text_figure_overlap",
    )


def config():
    return minimal_repair.load_repair_config()


class TestAdmission:
    def test_an_ornament_overlap_is_admitted(self):
        docs, article_ir, baseline, paragraph = fixture()
        refused = minimal_repair.admits_refit(
            issue_for(paragraph), docs, baseline, article_ir, frozenset(), config()
        )
        assert refused is None

    def test_an_artwork_overlap_is_not_this_action_to_take(self):
        docs, article_ir, baseline, paragraph = fixture()
        issue = issue_for(
            paragraph,
            evidence_extra={"asset_class": None, "artwork_source": "pdf_figure"},
        )
        refused = minimal_repair.admits_refit(
            issue, docs, baseline, article_ir, frozenset(), config()
        )
        assert refused == "overlap_not_ornament"

    def test_an_ornament_outside_the_inventory_is_refused(self):
        docs, article_ir, baseline, paragraph = fixture()
        shifted = (ORNAMENT[0] + 5.0, ORNAMENT[1], ORNAMENT[2] + 5.0, ORNAMENT[3])
        refused = minimal_repair.admits_refit(
            issue_for(paragraph, bbox=shifted),
            docs,
            baseline,
            article_ir,
            frozenset(),
            config(),
        )
        assert refused == "ornament_not_fixed_asset"

    def test_an_ornament_under_a_later_line_is_declined(self):
        low = (10.5, 62.0, 16.0, 68.0)
        docs, article_ir, baseline, paragraph = fixture(ornament=low)
        refused = minimal_repair.admits_refit(
            issue_for(paragraph, bbox=low),
            docs,
            baseline,
            article_ir,
            frozenset(),
            config(),
        )
        assert refused == "clearance_not_head_form"


class TestExecution:
    def _run(self, *, honor_clearance=True, clearance_pt=None, ornament=ORNAMENT):
        docs, article_ir, baseline, paragraph = fixture(ornament=ornament)
        translation_config = type("Cfg", (), {})()
        typesetter = ClearanceTypesetter(
            translation_config, honor_clearance=honor_clearance
        )
        target = minimal_repair._refit_target(
            issue_for(paragraph, bbox=ornament),
            docs,
            baseline,
            article_ir,
            typesetter,
            frozenset(),
            config(),
            translation_config=translation_config,
            clearance_pt=clearance_pt,
        )
        return target, paragraph, translation_config

    def test_the_repair_clears_the_ornament_and_keeps_every_character(self):
        target, paragraph, translation_config = self._run()
        assert minimal_repair._ink_ornament_area(paragraph, ORNAMENT) == 0.0
        text = "".join(
            character.char_unicode
            for character in minimal_repair.paragraph_characters(paragraph)
        )
        assert text == "overlap"
        store = getattr(translation_config, indent_policy.REPAIR_CLEARANCE_ATTR)
        assert store["overlapped"] == pytest.approx(
            ORNAMENT[2] - SOURCE_BOX[0] + minimal_repair.DEFAULT_CLEARANCE_PT
        )
        assert minimal_repair._box_tuple(paragraph.box) == SOURCE_BOX

    def test_a_render_that_ignores_the_width_is_refused_and_restored(self):
        docs, article_ir, baseline, paragraph = fixture()
        before = copy.deepcopy(paragraph.pdf_paragraph_composition)
        translation_config = type("Cfg", (), {})()
        typesetter = ClearanceTypesetter(translation_config, honor_clearance=False)
        with pytest.raises(minimal_repair._RepairRefusalError) as caught:
            minimal_repair._refit_target(
                issue_for(paragraph),
                docs,
                baseline,
                article_ir,
                typesetter,
                frozenset(),
                config(),
                translation_config=translation_config,
                clearance_pt=None,
            )
        assert caught.value.reason == "clearance_no_fit"
        store = getattr(
            translation_config, indent_policy.REPAIR_CLEARANCE_ATTR, {}
        )
        assert "overlapped" not in store
        rendered = [
            character.box.x
            for character in minimal_repair.paragraph_characters(paragraph)
        ]
        expected = [
            character.box.x
            for composition in before
            for character in composition.pdf_same_style_characters.pdf_character
        ]
        assert rendered == expected

    def test_an_advance_wider_than_the_box_is_refused_before_rendering(self):
        wide = (10.5, 80.0, 108.0, 86.0)
        docs, article_ir, baseline, paragraph = fixture(ornament=wide)
        translation_config = type("Cfg", (), {})()
        typesetter = ClearanceTypesetter(translation_config)
        with pytest.raises(minimal_repair._RepairRefusalError) as caught:
            minimal_repair._refit_target(
                issue_for(paragraph, bbox=wide),
                docs,
                baseline,
                article_ir,
                typesetter,
                frozenset(),
                config(),
                translation_config=translation_config,
                clearance_pt=None,
            )
        assert caught.value.reason == "clearance_no_fit"
        assert typesetter.calls == 0


class TestSchema:
    def test_the_mapping_hangs_the_overlap_on_the_refit(self):
        assert config().permitted_actions("text_figure_overlap") == (
            minimal_repair.REFIT_OWNED,
            minimal_repair.NO_OP,
        )
        assert dict(config().issue_actions)["fragment_cluster"] == (
            minimal_repair.RETYPESET_REGION,
        )

    def test_out_of_range_clearance_is_a_violation(self):
        from babeldoc.magazine import llm_decide

        parameter = llm_decide.load_decide_config().parameters_for(
            minimal_repair.REFIT_OWNED
        )["clearance_pt"]
        value, violation = parameter.coerce(9)
        assert value is None and "outside" in violation
        value, violation = parameter.coerce(2)
        assert value == 2.0 and violation == ""
