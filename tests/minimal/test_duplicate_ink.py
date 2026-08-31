"""One line painted twice is printed once, and the source decides which copy.

The shape under test is bull-zh page 3's photo credit: the source paints
``（图/国际原子能机构）`` on two consecutive lines at the same left margin, and
hides the upper copy under the photograph it credits. Both copies were
translated and both were set, and because a Latin line does not sit inside its
box the way the Chinese line it replaced did, the hidden copy reached out from
under the photograph's bottom edge.

Positive: two stacked copies, one wholly covered by artwork, leave one printed
paragraph and the covered one is the one withheld. Negative: the same text
printed twice at opposite ends of a page is two labels and neither is touched.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.magazine import duplicate_ink


def style() -> il.PdfStyle:
    return il.PdfStyle(
        font_id="body", font_size=11.0, graphic_state=il.GraphicState()
    )


def paragraph(text: str, box: tuple[float, float, float, float]) -> il.PdfParagraph:
    shared = style()
    return il.PdfParagraph(
        box=il.Box(*box),
        pdf_style=shared,
        unicode=text,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_unicode_characters=il.PdfSameStyleUnicodeCharacters(
                    unicode=text, pdf_style=shared
                )
            )
        ],
        layout_label="plain text",
    )


def page(paragraphs, figures=()) -> il.Page:
    box = il.Box(0.0, 0.0, 595.0, 842.0)
    return il.Page(
        page_number=2,
        unit="pt",
        mediabox=il.Mediabox(box=il.Box(0.0, 0.0, 595.0, 842.0)),
        cropbox=il.Cropbox(box=box),
        pdf_paragraph=list(paragraphs),
        pdf_figure=[il.PdfFigure(box=il.Box(*item)) for item in figures],
    )


class RuntimeConfig:
    """The smallest object the pass reads, with no source file to open."""

    def __init__(self, working_dir):
        self.working_dir = working_dir
        self.magazine_duplicate_ink = True
        self.input_file = None

    def get_working_file_path(self, name: str) -> str:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return str(self.working_dir / name)


# The measured bull-zh page 3 geometry, in the intermediate language's own
# bottom-up space: the two credit copies and the photograph that covers the
# upper one whole.
CREDIT = "(图/国际原子能机构)"
UPPER = (21.6246, 48.6812, 120.1186, 58.9772)
LOWER = (21.6246, 35.2167, 120.1186, 45.5127)
PHOTO = (1.66, 48.59, 202.91, 163.76)


def test_the_copy_the_artwork_covers_is_the_one_withheld(tmp_path):
    subject = page([paragraph(CREDIT, UPPER), paragraph(CREDIT, LOWER)], [PHOTO])
    config = RuntimeConfig(tmp_path)
    record = duplicate_ink.apply(config, [(3, subject)])

    assert record["totals"] == {
        "groups": 1,
        "copies": 2,
        "withheld": 1,
        "kept": 1,
    }
    group = record["groups"][0]
    assert group["kept"] == "p3#1"
    assert group["keep_reason"] == duplicate_ink.KEPT_MOST_UNCOVERED
    covered, visible = group["copies"]
    assert covered["reference"] == "p3#0"
    assert covered["uncovered_fraction"] == 0.0
    assert covered["withheld"] is True
    assert covered["reason"] == duplicate_ink.WITHHELD_DUPLICATE
    assert visible["uncovered_fraction"] == 1.0
    assert visible["withheld"] is False

    # The withheld copy is emptied, not removed: every index that named a
    # paragraph before still names the same one.
    assert len(subject.pdf_paragraph) == 2
    assert subject.pdf_paragraph[0].unicode == ""
    assert subject.pdf_paragraph[0].pdf_paragraph_composition == []
    assert subject.pdf_paragraph[1].unicode == CREDIT
    assert subject.pdf_paragraph[1].pdf_paragraph_composition


def test_the_same_label_printed_in_two_places_is_two_labels(tmp_path):
    far = (21.6246, 700.0, 120.1186, 710.2955)
    subject = page([paragraph(CREDIT, far), paragraph(CREDIT, LOWER)], [PHOTO])
    record = duplicate_ink.apply(RuntimeConfig(tmp_path), [(3, subject)])

    assert record["totals"]["groups"] == 0
    assert [item.unicode for item in subject.pdf_paragraph] == [CREDIT, CREDIT]


def test_a_copy_two_lines_away_is_left_alone(tmp_path):
    """The gap bound is a multiple of the copies' own height, not a distance."""
    config = duplicate_ink.load_duplicate_ink_config()
    height = UPPER[3] - UPPER[1]
    just_too_far = (
        UPPER[0],
        UPPER[1] + height * config.max_line_gap_ratio + height + 0.5,
        UPPER[2],
        UPPER[3] + height * config.max_line_gap_ratio + height + 0.5,
    )
    subject = page([paragraph(CREDIT, UPPER), paragraph(CREDIT, just_too_far)])
    record = duplicate_ink.apply(RuntimeConfig(tmp_path), [(3, subject)])
    assert record["totals"]["groups"] == 0


def test_the_switch_decides_whether_the_pass_runs(tmp_path):
    subject = page([paragraph(CREDIT, UPPER), paragraph(CREDIT, LOWER)], [PHOTO])
    config = RuntimeConfig(tmp_path)
    config.magazine_duplicate_ink = False
    assert duplicate_ink.apply(config, [(3, subject)]) is None
    assert [item.unicode for item in subject.pdf_paragraph] == [CREDIT, CREDIT]


class TestConfigBounds:
    def test_out_of_range_gap_is_refused(self):
        with duplicate_ink.CONFIG_PATH.open(encoding="utf-8") as f:
            raw = json.load(f)
        raw["max_line_gap_ratio"] = 5.0
        with pytest.raises(duplicate_ink.DuplicateInkError):
            duplicate_ink.parse_duplicate_ink_config(raw, "duplicate_ink.json")

    def test_a_config_naming_another_switch_is_refused(self):
        with duplicate_ink.CONFIG_PATH.open(encoding="utf-8") as f:
            raw = json.load(f)
        raw["switch"] = "magazine_something_else"
        with pytest.raises(duplicate_ink.DuplicateInkError):
            duplicate_ink.parse_duplicate_ink_config(raw, "duplicate_ink.json")

    def test_shipped_config_is_within_its_own_bounds(self):
        config = duplicate_ink.load_duplicate_ink_config()
        assert 0.0 <= config.min_overlap_fraction <= 1.0
        assert 0.0 <= config.max_line_gap_ratio <= 4.0
        assert 1 <= config.min_text_chars <= 40


def test_overlapping_artwork_covers_a_point_once():
    """The union, not the sum: two overlapping figures do not cover twice."""
    box = (0.0, 0.0, 10.0, 10.0)
    blockers = [(0.0, 0.0, 6.0, 10.0), (4.0, 0.0, 10.0, 10.0)]
    assert duplicate_ink.uncovered_fraction(box, blockers) == 0.0
    assert duplicate_ink.uncovered_fraction(box, [(0.0, 0.0, 5.0, 10.0)]) == 0.5


def test_artwork_evidence_degrades_to_nothing_without_a_readable_file():
    subject = page([paragraph(CREDIT, UPPER)], [PHOTO])
    config = SimpleNamespace(input_file="no-such-file.pdf")
    assert duplicate_ink.artwork_boxes(config, subject, 3) == [PHOTO]
