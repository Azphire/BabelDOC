"""The split B16 taught the indent policy: style is decided, avoidance is kept.

The source flag ``first_line_indent`` conflates two meanings. A stylistic
indent is a language convention and the policy's to give or withhold. A
functional avoidance -- a caption's first line starting past a printed
triangle, a pull quote opening right of an oversized quotation mark -- is a
statement about where ink ends, and no paragraph convention has authority
over it. B15's Courier run showed the cost of conflating them: the policy
cleared two captions' flags and the translated first lines were set over the
triangles they had been clearing (docs/reports/B16/_t0_premise_findings.md).

These fixtures pin the split at every joint: the geometric classifier that
says what an ornament is, the pre-translation capture that measures the
avoidance, the policy's loss of the right to clear a functional flag, and
the width the typesetting stage is handed in place of its em approximation.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import fixed_assets
from babeldoc.magazine import indent_policy
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.page_features import ConfigError
from tests.minimal.fakes import _page


def _char(x: float, y: float, x2: float, y2: float, glyph: str = "x"):
    return il_version_1.PdfCharacter(
        box=Box(x, y, x2, y2),
        char_unicode=glyph,
        pdf_style=il_version_1.PdfStyle(font_id="body", font_size=10.0),
    )


def _lined_paragraph(
    debug_id: str,
    box: tuple[float, float, float, float],
    first_char_x: float,
    *,
    line_y: float,
    line_y2: float,
    label: str = "figure_caption",
    indent: bool = True,
):
    """A paragraph whose first line starts at ``first_char_x``, as the source drew it."""
    chars = [
        _char(first_char_x, line_y, first_char_x + 5.0, line_y2),
        _char(first_char_x + 5.0, line_y, first_char_x + 10.0, line_y2),
    ]
    line = il_version_1.PdfLine(box=Box(first_char_x, line_y, box[2], line_y2))
    line.pdf_character = chars
    second_line = il_version_1.PdfLine(box=Box(box[0], box[1], box[2], line_y))
    second_line.pdf_character = [_char(box[0], box[1], box[0] + 5.0, line_y)]
    return il_version_1.PdfParagraph(
        box=Box(*box),
        pdf_style=il_version_1.PdfStyle(font_id="body", font_size=10.0),
        unicode="source caption",
        debug_id=debug_id,
        layout_label=label,
        first_line_indent=indent,
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(pdf_line=line),
            il_version_1.PdfParagraphComposition(pdf_line=second_line),
        ],
    )


def _ornament(x: float, y: float, x2: float, y2: float, *, fill: bool = True):
    return il_version_1.PdfCurve(
        box=Box(x, y, x2, y2),
        graphic_state=il_version_1.GraphicState(),
        fill_background=fill,
        stroke_path=not fill,
    )


def _config(tmp_path: Path, lang_out: str = "zh"):
    work = tmp_path / "work"

    def working_file(name: str) -> str:
        work.mkdir(parents=True, exist_ok=True)
        return str(work / name)

    return SimpleNamespace(
        magazine_indent_policy=True,
        lang_out=lang_out,
        get_working_file_path=working_file,
    )


def _empty_ir():
    return ArticleDocumentIR(
        articles=(), by_page={}, by_element={}, by_chain={}
    )


THRESHOLDS = fixed_assets.load_ornament_thresholds()


class TestOrnamentClassifier:
    def test_small_filled_curve_is_an_ornament(self):
        assert fixed_assets.is_ornament_curve(
            _ornament(10.0, 80.0, 16.0, 86.0), THRESHOLDS
        )

    def test_stroke_only_curve_is_not(self):
        assert not fixed_assets.is_ornament_curve(
            _ornament(10.0, 80.0, 16.0, 86.0, fill=False), THRESHOLDS
        )

    def test_background_block_is_refused_by_area(self):
        # 40 x 40 = 1600 pt^2: each side within the side bound, the area over
        # the area bound. The ceiling is what keeps color blocks out.
        assert not fixed_assets.is_ornament_curve(
            _ornament(0.0, 0.0, 40.0, 40.0), THRESHOLDS
        )

    def test_long_rule_is_refused_by_side(self):
        # 100 x 2 = 200 pt^2: under the area bound, over the side bound.
        assert not fixed_assets.is_ornament_curve(
            _ornament(0.0, 50.0, 100.0, 52.0), THRESHOLDS
        )

    def test_degenerate_box_is_refused(self):
        assert not fixed_assets.is_ornament_curve(
            _ornament(10.0, 10.0, 10.0, 10.0), THRESHOLDS
        )

    def test_out_of_range_threshold_config_is_refused(self, tmp_path):
        bad = tmp_path / "ornament_assets.json"
        bad.write_text(
            json.dumps(
                {
                    "ornament_max_area_pt2": 6000,
                    "ornament_max_area_pt2_allowed_range": "50..5000",
                    "ornament_max_side_pt": 40,
                    "ornament_max_side_pt_allowed_range": "8..120",
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError):
            fixed_assets.load_ornament_thresholds(str(bad))


class TestCapture:
    def test_ornament_in_the_leading_strip_is_functional(self, tmp_path):
        paragraph = _lined_paragraph(
            "cap-1", (10.0, 60.0, 110.0, 90.0), 30.0, line_y=80.0, line_y2=88.0
        )
        page = _page(0, [paragraph])
        page.pdf_curve = [_ornament(12.0, 80.0, 18.0, 86.0)]
        docs = il_version_1.Document(page=[page], total_pages=1)
        config = _config(tmp_path)

        plan = indent_policy.capture_clearance(config, docs)

        assert plan is not None and len(plan.entries) == 1
        entry = plan.entries[0]
        assert entry.canonical_ref == "p1#0"
        assert entry.asset_class == fixed_assets.ORNAMENT_ASSET_CLASS
        assert entry.indent_pt == pytest.approx(20.0)
        assert entry.width_pt == pytest.approx(
            20.0 + indent_policy.load_indent_config().functional_clearance_pt
        )
        assert getattr(config, indent_policy.CLEARANCE_PLAN_ATTR) is plan

    def test_bare_stylistic_indent_stays_stylistic(self, tmp_path):
        paragraph = _lined_paragraph(
            "cap-2", (10.0, 60.0, 110.0, 90.0), 30.0, line_y=80.0, line_y2=88.0
        )
        docs = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
        plan = indent_policy.capture_clearance(_config(tmp_path), docs)

        assert plan is not None and plan.entries == ()
        assert plan.totals["stylistic"] == 1

    def test_ground_artwork_under_the_paragraph_does_not_count(self, tmp_path):
        paragraph = _lined_paragraph(
            "cap-3", (10.0, 60.0, 110.0, 90.0), 30.0, line_y=80.0, line_y2=88.0
        )
        page = _page(0, [paragraph])
        page.pdf_figure = [
            il_version_1.PdfFigure(box=Box(0.0, 0.0, 120.0, 100.0))
        ]
        docs = il_version_1.Document(page=[page], total_pages=1)
        plan = indent_policy.capture_clearance(_config(tmp_path), docs)

        assert plan is not None and plan.entries == ()
        assert plan.totals["stylistic"] == 1

    def test_intruding_artwork_is_functional(self, tmp_path):
        paragraph = _lined_paragraph(
            "cap-4", (10.0, 60.0, 110.0, 90.0), 30.0, line_y=80.0, line_y2=88.0
        )
        page = _page(0, [paragraph])
        page.pdf_figure = [
            il_version_1.PdfFigure(box=Box(5.0, 75.0, 25.0, 95.0))
        ]
        docs = il_version_1.Document(page=[page], total_pages=1)
        plan = indent_policy.capture_clearance(_config(tmp_path), docs)

        assert plan is not None and len(plan.entries) == 1
        assert plan.entries[0].asset_class == "pdf_figure"

    def test_same_style_run_shape_still_measures(self, tmp_path):
        """The real post-styles shape: one style run spanning both lines.

        This is the shape the first Courier rerun met -- every raised flag
        fell to ``no_leading_line`` because the reader trusted the leading
        composition to be a line. The measurement must come off the
        characters, whatever the styles pass wrapped them in.
        """
        chars = [
            _char(30.0, 80.0, 35.0, 88.0),
            _char(35.0, 80.0, 40.0, 88.0),
            _char(10.0, 68.0, 15.0, 76.0),
        ]
        run = il_version_1.PdfSameStyleCharacters(
            box=Box(10.0, 68.0, 110.0, 88.0),
            pdf_style=il_version_1.PdfStyle(font_id="body", font_size=10.0),
        )
        run.pdf_character = chars
        paragraph = il_version_1.PdfParagraph(
            box=Box(10.0, 60.0, 110.0, 90.0),
            pdf_style=il_version_1.PdfStyle(font_id="body", font_size=10.0),
            unicode="source caption",
            debug_id="cap-run",
            layout_label="figure_caption",
            first_line_indent=True,
            pdf_paragraph_composition=[
                il_version_1.PdfParagraphComposition(pdf_same_style_characters=run)
            ],
        )
        page = _page(0, [paragraph])
        page.pdf_curve = [_ornament(12.0, 80.0, 18.0, 86.0)]
        docs = il_version_1.Document(page=[page], total_pages=1)

        plan = indent_policy.capture_clearance(_config(tmp_path), docs)

        assert plan is not None and len(plan.entries) == 1
        entry = plan.entries[0]
        assert entry.indent_pt == pytest.approx(20.0)
        assert entry.strip == (10.0, 80.0, 30.0, 88.0)

    def test_switch_down_captures_nothing(self, tmp_path):
        config = _config(tmp_path)
        config.magazine_indent_policy = False
        docs = il_version_1.Document(page=[], total_pages=0)
        assert indent_policy.capture_clearance(config, docs) is None
        assert getattr(config, indent_policy.CLEARANCE_PLAN_ATTR) is None


class TestPolicyProtection:
    def _run(self, tmp_path, *, with_ornament: bool):
        paragraph = _lined_paragraph(
            "cap-9", (10.0, 60.0, 110.0, 90.0), 30.0, line_y=80.0, line_y2=88.0
        )
        page = _page(0, [paragraph])
        if with_ornament:
            page.pdf_curve = [_ornament(12.0, 80.0, 18.0, 86.0)]
        docs = il_version_1.Document(page=[page], total_pages=1)
        config = _config(tmp_path)
        indent_policy.capture_clearance(config, docs)
        record = indent_policy.apply(config, docs, _empty_ir())
        return record, paragraph

    def test_policy_may_not_clear_a_functional_flag(self, tmp_path):
        record, paragraph = self._run(tmp_path, with_ornament=True)
        row = record["paragraphs"][0]
        assert row["functional_clearance"] is True
        assert row["before"] is True and row["after"] is True
        assert row["decided"] is False and row["skipped"] is None
        assert row["clearance_width_pt"] == pytest.approx(22.0)
        assert paragraph.first_line_indent is True
        assert record["totals"]["functional_clearance"] == 1

    def test_the_same_flag_without_an_asset_is_cleared_as_before(self, tmp_path):
        record, paragraph = self._run(tmp_path, with_ornament=False)
        row = record["paragraphs"][0]
        assert row["functional_clearance"] is False
        assert row["before"] is True and row["after"] is False
        assert row["decided"] is True
        assert paragraph.first_line_indent is False

    def test_a_dropped_functional_flag_is_restored(self, tmp_path):
        paragraph = _lined_paragraph(
            "cap-8", (10.0, 60.0, 110.0, 90.0), 30.0, line_y=80.0, line_y2=88.0
        )
        page = _page(0, [paragraph])
        page.pdf_curve = [_ornament(12.0, 80.0, 18.0, 86.0)]
        docs = il_version_1.Document(page=[page], total_pages=1)
        config = _config(tmp_path)
        indent_policy.capture_clearance(config, docs)
        paragraph.first_line_indent = False  # a writer between capture and apply
        record = indent_policy.apply(config, docs, _empty_ir())
        assert record["paragraphs"][0]["after"] is True
        assert paragraph.first_line_indent is True


class TestTypesettingLookup:
    def test_functional_width_is_served_by_debug_id(self, tmp_path):
        paragraph = _lined_paragraph(
            "cap-7", (10.0, 60.0, 110.0, 90.0), 30.0, line_y=80.0, line_y2=88.0
        )
        page = _page(0, [paragraph])
        page.pdf_curve = [_ornament(12.0, 80.0, 18.0, 86.0)]
        docs = il_version_1.Document(page=[page], total_pages=1)
        config = _config(tmp_path)
        indent_policy.capture_clearance(config, docs)

        width = indent_policy.functional_clearance_width(config, paragraph)
        assert width == pytest.approx(22.0)

        stranger = _lined_paragraph(
            "someone-else", (10.0, 10.0, 110.0, 40.0), 30.0, line_y=30.0, line_y2=38.0
        )
        assert indent_policy.functional_clearance_width(config, stranger) is None

    def test_no_plan_means_the_em_approximation(self):
        config = SimpleNamespace()
        paragraph = SimpleNamespace(debug_id="cap-7")
        assert indent_policy.functional_clearance_width(config, paragraph) is None


class TestConfigBounds:
    def test_out_of_range_clearance_is_refused(self):
        with indent_policy.CONFIG_PATH.open(encoding="utf-8") as f:
            raw = json.load(f)
        raw["functional_clearance_pt"] = 9
        with pytest.raises(indent_policy.IndentPolicyError):
            indent_policy.parse_indent_config(raw, "indent_policy.json")

    def test_shipped_config_declares_the_clearance(self):
        config = indent_policy.load_indent_config()
        assert 0 <= config.functional_clearance_pt <= 8
