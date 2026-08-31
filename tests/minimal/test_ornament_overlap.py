"""The overlap detector's B16 extension: ornament-grade curves are artwork too.

Courier's caption triangles and ITU's pull-quote quotation marks are filled
vector paths -- ``pdf_curve``, not figure or xobject -- so the artwork walk
never saw them, and the union ratio never would have: a 30 pt^2 triangle
shares a vanishing fraction of its union with any paragraph set over it.
These fixtures pin the extension: an ornament under text is one finding with
shared-ink evidence, a background block never enters the inventory, an
untouched ornament reports nothing, and an artwork hit still wins the name.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.detectors import detector_config
from babeldoc.magazine.detectors import overlap
from babeldoc.magazine.detectors.base import PageView
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph


def _curve(x: float, y: float, x2: float, y2: float, *, fill: bool = True):
    return il_version_1.PdfCurve(
        box=Box(x, y, x2, y2),
        graphic_state=il_version_1.GraphicState(),
        fill_background=fill,
        stroke_path=not fill,
    )


def _context(page):
    return SimpleNamespace(
        pages=[PageView(label=1, page=page, policy=None)],
        config=detector_config(),
        iteration=0,
        severity_of=lambda kind: detector_config().severity[kind],
    )


def _detect(page):
    return overlap.detect(_context(page))


class TestOrnamentOverlap:
    def test_text_over_an_ornament_is_one_finding(self):
        paragraph = _paragraph("caption text", "cap-1", (10.0, 60.0, 110.0, 90.0))
        page = _page(0, [paragraph])
        page.pdf_curve = [_curve(12.0, 80.0, 18.0, 86.0)]

        issues = _detect(page)

        assert len(issues) == 1
        issue = issues[0]
        assert issue.kind == "text_figure_overlap"
        assert issue.paragraph_refs == ("p1#0",)
        evidence = issue.evidence
        assert evidence["asset_class"] == fixed_assets.ORNAMENT_ASSET_CLASS
        assert evidence["artwork_source"] == "pdf_curve"
        assert evidence["ornament_bbox"] == [12.0, 80.0, 18.0, 86.0]
        assert evidence["intersection_box"] == [12.0, 80.0, 18.0, 86.0]
        assert evidence["intersection_area_pt2"] == pytest.approx(36.0)
        assert evidence["min_intersection_area_pt2"] == pytest.approx(
            detector_config().ornament_overlap_min_pt2
        )

    def test_an_untouched_ornament_reports_nothing(self):
        paragraph = _paragraph("caption text", "cap-2", (10.0, 60.0, 110.0, 90.0))
        page = _page(0, [paragraph])
        page.pdf_curve = [_curve(10.0, 92.0, 16.0, 98.0)]

        assert _detect(page) == []

    def test_a_background_block_is_not_an_ornament(self):
        # Filled, squarely under the text, and far over the area bound: the
        # classifier refuses it, so the shared-ink test never runs.
        paragraph = _paragraph("body text", "cap-3", (10.0, 20.0, 110.0, 90.0))
        page = _page(0, [paragraph])
        page.pdf_curve = [_curve(0.0, 0.0, 120.0, 100.0)]

        assert _detect(page) == []

    def test_a_graze_below_the_ink_bound_reports_nothing(self):
        # 1 x 2 = 2 pt^2 shared, under the 4 pt^2 default.
        paragraph = _paragraph("caption text", "cap-4", (10.0, 60.0, 110.0, 90.0))
        page = _page(0, [paragraph])
        page.pdf_curve = [_curve(9.0, 88.0, 11.0, 92.0)]

        assert _detect(page) == []

    def test_healed_ink_beside_an_ornament_reports_nothing(self):
        """A first line indented past the triangle owns a box that still
        covers it; the measurement is the ink, or the healed avoidance would
        be reported as the defect it just repaired."""
        chars = [
            il_version_1.PdfCharacter(
                box=Box(30.0 + offset, 80.0, 35.0 + offset, 88.0),
                char_unicode="x",
            )
            for offset in (0.0, 5.0)
        ]
        line = il_version_1.PdfLine(box=Box(30.0, 80.0, 40.0, 88.0))
        line.pdf_character = chars
        paragraph = il_version_1.PdfParagraph(
            box=Box(10.0, 60.0, 110.0, 90.0),
            pdf_style=il_version_1.PdfStyle(font_id="body", font_size=10.0),
            unicode="healed caption",
            debug_id="cap-heal",
            layout_label="figure_caption",
            pdf_paragraph_composition=[
                il_version_1.PdfParagraphComposition(pdf_line=line)
            ],
        )
        page = _page(0, [paragraph])
        page.pdf_curve = [_curve(12.0, 80.0, 18.0, 86.0)]

        assert _detect(page) == []

    def test_an_artwork_hit_keeps_the_name(self):
        # A paragraph over both a comparable figure and an ornament is one
        # defect with the figure as its worst witness: the issue id is built
        # from the paragraph reference, and two findings would share it.
        paragraph = _paragraph("body text", "cap-5", (10.0, 20.0, 110.0, 90.0))
        page = _page(0, [paragraph])
        page.pdf_figure = [
            il_version_1.PdfFigure(box=Box(10.0, 20.0, 110.0, 95.0))
        ]
        page.pdf_curve = [_curve(12.0, 80.0, 18.0, 86.0)]

        issues = _detect(page)

        assert len(issues) == 1
        assert issues[0].evidence["artwork_source"] == "pdf_figure"
        assert "asset_class" not in issues[0].evidence

    def test_severity_vector_still_carries_iou(self):
        paragraph = _paragraph("caption text", "cap-6", (10.0, 60.0, 110.0, 90.0))
        page = _page(0, [paragraph])
        page.pdf_curve = [_curve(12.0, 80.0, 18.0, 86.0)]

        issue = _detect(page)[0].with_severity_fields(
            detector_config().progress_fields("text_figure_overlap")
        )
        dimensions = dict(issue.severity_vector.dimensions)
        assert dimensions["iou"] == issue.evidence["iou"] > 0


class TestInventoryMarker:
    def test_only_ornament_curves_carry_the_class(self):
        page = _page(0, [])
        page.pdf_curve = [
            _curve(12.0, 80.0, 18.0, 86.0),
            _curve(0.0, 0.0, 120.0, 100.0),
        ]
        document = il_version_1.Document(page=[page], total_pages=1)

        inventory = fixed_assets.build_inventory(document)

        ornament = inventory.by_ref["p1:pdf_curve#0"]
        block = inventory.by_ref["p1:pdf_curve#1"]
        assert ornament.asset_class == fixed_assets.ORNAMENT_ASSET_CLASS
        assert block.asset_class is None
        assert (
            inventory.to_record()["assets"][0]["asset_class"]
            in (fixed_assets.ORNAMENT_ASSET_CLASS, None)
        )

    def test_config_default_is_declared_in_range(self):
        value = detector_config().ornament_overlap_min_pt2
        assert 1 <= value <= 50
