"""The fragment stitch, wired and narrowed to its inline rule.

The pass existed complete -- rules, guards, report -- with no caller: the
switch was pinned true and ``apply`` was never invoked, so Courier-en p4 still
sent ``There are many more examples of how t`` and ``raditional knowledge``
to the translator as two requests. These are the module's first tests: the
inline rule puts an x-cut line back together, the guards refuse what is not
one broken unit, and the shipped configuration declares the inline rule alone
-- vertical would union a wide band with the column under it into one
rectangle overriding wrap-around geometry, and initial would restyle an
oversized opening letter to the body majority, destroying the drop cap lane's
frozen evidence.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.magazine import fragment_stitch
from babeldoc.magazine.line_split import paragraph_characters

from tests.minimal.test_drop_cap_keep_flatten import pdf_style

LEFT_TEXT = "There are many more examples of how t"
RIGHT_TEXT = "raditional knowledge"


def line_paragraph(
    text: str,
    x: float,
    y: float,
    *,
    label: str = "plain text",
    font_id: str = "body",
    font_size: float = 9.2,
    char_width: float = 4.0,
    debug_id: str = "frag",
) -> il.PdfParagraph:
    style = pdf_style(font_id, font_size)
    characters = [
        il.PdfCharacter(
            char_unicode=glyph,
            box=il.Box(
                x + index * char_width,
                y,
                x + (index + 1) * char_width,
                y + font_size,
            ),
            pdf_style=style,
            advance=char_width,
            xobj_id=0,
        )
        for index, glyph in enumerate(text)
    ]
    box = il.Box(x, y, x + len(text) * char_width, y + font_size)
    return il.PdfParagraph(
        unicode=text,
        box=box,
        pdf_style=style,
        layout_label=label,
        debug_id=debug_id,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_characters=il.PdfSameStyleCharacters(
                    box=box, pdf_style=style, pdf_character=characters
                )
            )
        ],
    )


def cut_line_page(
    x: float | None = None,
    y: float = 639.2,
    font_size: float = 9.2,
) -> il.Page:
    left = line_paragraph(LEFT_TEXT, 68.0, 639.2, debug_id="left")
    right = line_paragraph(
        RIGHT_TEXT,
        68.0 + len(LEFT_TEXT) * 4.0 + 0.7 if x is None else x,
        y,
        label="fallback_line",
        font_size=font_size,
        debug_id="right",
    )
    page = il.Page(
        pdf_paragraph=[left, right],
        pdf_font=[il.PdfFont(font_id="body", name="ABC+TheSans")],
        page_number=3,
    )
    page.page_kind = "feature"
    return page


def test_inline_rule_reunites_a_mid_word_cut() -> None:
    page = cut_line_page()
    config = fragment_stitch.load_stitch_config()
    records, _candidates = fragment_stitch.process_page(page, 4, config)
    assert len(records) == 1
    assert records[0]["rule"] == fragment_stitch.RULE_INLINE
    assert records[0]["members"] == 2

    first, second = page.pdf_paragraph
    assert first.unicode == LEFT_TEXT + RIGHT_TEXT
    assert "how traditional knowledge" in first.unicode
    assert len(paragraph_characters(first)) == len(LEFT_TEXT) + len(RIGHT_TEXT)
    # The merged-away member keeps its slot and gives up its paint and box.
    assert second.pdf_paragraph_composition == []
    assert second.unicode == ""
    assert second.box is None
    assert len(page.pdf_paragraph) == 2


def test_pieces_on_different_lines_stay_apart() -> None:
    page = cut_line_page(y=627.3)
    records, _candidates = fragment_stitch.process_page(
        page, 4, fragment_stitch.load_stitch_config()
    )
    assert records == []


def test_a_gap_beyond_the_bound_stays_apart() -> None:
    config = fragment_stitch.load_stitch_config()
    gap = config.max_inline_gap_ratio * 9.2 + 2.0
    page = cut_line_page(x=68.0 + len(LEFT_TEXT) * 4.0 + gap)
    records, _candidates = fragment_stitch.process_page(page, 4, config)
    assert records == []


def test_a_style_break_stays_apart() -> None:
    page = cut_line_page(font_size=12.0)
    records, _candidates = fragment_stitch.process_page(
        page, 4, fragment_stitch.load_stitch_config()
    )
    assert records == []


def test_a_finished_sentence_stays_apart() -> None:
    left = line_paragraph(LEFT_TEXT[:-1] + ".", 68.0, 639.2, debug_id="left")
    right = line_paragraph(
        RIGHT_TEXT,
        68.0 + len(LEFT_TEXT) * 4.0 + 0.7,
        639.2,
        label="fallback_line",
        debug_id="right",
    )
    page = il.Page(
        pdf_paragraph=[left, right],
        pdf_font=[il.PdfFont(font_id="body", name="ABC+TheSans")],
        page_number=3,
    )
    page.page_kind = "feature"
    records, _candidates = fragment_stitch.process_page(
        page, 4, fragment_stitch.load_stitch_config()
    )
    assert records == []


def test_shipped_rules_declare_inline_alone() -> None:
    assert fragment_stitch.load_stitch_config().rules == ("inline",)


def test_vertical_shapes_are_not_stitched_under_shipped_rules() -> None:
    upper = line_paragraph("continues without a stop", 68.0, 651.0, debug_id="up")
    lower = line_paragraph("and carries on below", 68.0, 639.2, debug_id="down")
    page = il.Page(
        pdf_paragraph=[upper, lower],
        pdf_font=[il.PdfFont(font_id="body", name="ABC+TheSans")],
        page_number=3,
    )
    page.page_kind = "feature"
    records, _candidates = fragment_stitch.process_page(
        page, 4, fragment_stitch.load_stitch_config()
    )
    assert records == []


def _config_for(tmp_path: Path, **attributes):
    def get_working_file_path(name: str) -> str:
        return str(tmp_path / name)

    return SimpleNamespace(
        get_working_file_path=get_working_file_path,
        input_file=str(tmp_path / "absent.pdf"),
        **attributes,
    )


def test_apply_honours_the_switch(tmp_path) -> None:
    page = cut_line_page()
    config = _config_for(tmp_path, magazine_fragment_stitch=False)
    record = fragment_stitch.apply(
        config, [(4, page)], policy_of=lambda _kind: {}
    )
    assert record is None
    assert page.pdf_paragraph[1].unicode == RIGHT_TEXT


def test_apply_stitches_and_writes_the_report(tmp_path) -> None:
    page = cut_line_page()
    config = _config_for(tmp_path, magazine_fragment_stitch=True)
    record = fragment_stitch.apply(
        config, [(4, page)], policy_of=lambda _kind: {}
    )
    assert record is not None
    assert record["totals"]["stitches"] == 1
    assert record["rules"] == ["inline"]
    assert (tmp_path / fragment_stitch.REPORT_NAME).is_file()
    assert page.pdf_paragraph[0].unicode == LEFT_TEXT + RIGHT_TEXT
