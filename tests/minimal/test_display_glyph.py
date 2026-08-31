"""The display glyph pass: a short oversized run in running text is pinned.

The fixtures mirror the shape the pass exists for -- a feature number drawn
at several times the body size inside a contents blurb -- without naming any
sample: an oversized character mid-paragraph is split out and pinned, an
opening-position run is left for the drop cap lane, moderate emphasis and
all-large titles are never touched, and the character set is conserved
across the split.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.magazine import display_glyph
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.line_split import paragraph_characters


def _mixed_paragraph(
    runs: list[tuple[str, float]], *, x: float = 60.0, y: float = 300.0
) -> il.PdfParagraph:
    """One paragraph whose characters are set in the given (text, size) runs."""
    characters = []
    cursor = x
    top = y
    for text, size in runs:
        style = il.PdfStyle(font_id="body", font_size=size)
        for glyph in text:
            advance = size * 0.55
            characters.append(
                il.PdfCharacter(
                    char_unicode=glyph,
                    box=il.Box(cursor, top, cursor + advance, top + size),
                    pdf_style=style,
                    advance=advance,
                    xobj_id=0,
                )
            )
            cursor += advance
    box = il.Box(x, top, cursor, top + max(size for _, size in runs))
    return il.PdfParagraph(
        unicode="".join(text for text, _ in runs),
        box=box,
        pdf_style=il.PdfStyle(font_id="body", font_size=runs[0][1]),
        layout_label="plain text",
        debug_id="host",
        vertical=False,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_characters=il.PdfSameStyleCharacters(
                    box=box,
                    pdf_style=il.PdfStyle(font_id="body", font_size=runs[0][1]),
                    pdf_character=characters,
                )
            )
        ],
    )


def _config(tmp_path: Path, on: bool = True):
    return SimpleNamespace(
        magazine_display_glyph=on,
        get_working_file_path=lambda name: str(tmp_path / name),
    )


def _apply(tmp_path: Path, paragraphs, on: bool = True):
    page = il.Page(page_number=3, pdf_paragraph=list(paragraphs))
    docs = il.Document(page=[page], total_pages=3)
    record = display_glyph.apply(_config(tmp_path, on), docs)
    return record, page


def test_an_inline_giant_is_pinned_and_the_characters_are_conserved(
    tmp_path,
) -> None:
    host = _mixed_paragraph(
        [("A title line here ", 8.0), ("8", 65.0)]
    )
    before = len(paragraph_characters(host))

    record, page = _apply(tmp_path, [host])

    assert record["counts"] == {"pinned": 1, "refused": 0}
    assert len(page.pdf_paragraph) == 2
    pinned = page.pdf_paragraph[1]
    assert pinned.layout_label == "display_glyph"
    assert pinned.unicode == "8"
    assert pinned.pdf_style.font_size == 65.0
    # Pinned at the character's own source box, to the point.
    glyph_chars = paragraph_characters(pinned)
    assert float(pinned.box.x) == float(glyph_chars[0].box.x)
    # The host lost exactly the glyph and nothing else (the rebuild reads the
    # text off the characters, which normalises the trailing space away).
    assert host.unicode.rstrip() == "A title line here"
    assert len(paragraph_characters(host)) + len(glyph_chars) == before
    # The single-source enumerator sees it where the detectors will look.
    glyphs = fixed_assets.display_glyph_paragraphs(page)
    assert [index for index, _ in glyphs] == [1]


def test_an_opening_position_run_is_left_for_the_drop_cap_lane(tmp_path) -> None:
    host = _mixed_paragraph([("T", 24.0), ("he rest of the opening line", 8.0)])

    record, page = _apply(tmp_path, [host])

    assert record["counts"]["pinned"] == 0
    assert [item["reason"] for item in record["refused"]] == [
        display_glyph.REFUSED_OPENING_POSITION
    ]
    assert len(page.pdf_paragraph) == 1
    assert host.unicode == "The rest of the opening line"


def test_moderate_emphasis_below_the_ratio_is_not_split(tmp_path) -> None:
    host = _mixed_paragraph(
        [("body text before ", 8.0), ("14", 12.0), (" and after", 8.0)]
    )

    record, page = _apply(tmp_path, [host])

    assert record["counts"] == {"pinned": 0, "refused": 0}
    assert len(page.pdf_paragraph) == 1


def test_an_all_large_title_is_its_own_median_and_never_touched(tmp_path) -> None:
    host = _mixed_paragraph([("BIG", 38.0)])

    record, page = _apply(tmp_path, [host])

    assert record["counts"] == {"pinned": 0, "refused": 0}
    assert len(page.pdf_paragraph) == 1


def test_a_long_oversized_run_is_a_heading_and_stays(tmp_path) -> None:
    host = _mixed_paragraph(
        [("body copy leading in ", 8.0), ("HEADLINE", 24.0)]
    )

    record, page = _apply(tmp_path, [host])

    assert record["counts"] == {"pinned": 0, "refused": 0}


def test_an_oversized_word_goes_back_to_the_flow(tmp_path) -> None:
    # A big topic word over a section label translates to something; pinning
    # it would silently exempt that translation. Recorded, not pinned.
    host = _mixed_paragraph([("编者按 ", 12.0), ("创新", 30.0)])

    record, page = _apply(tmp_path, [host])

    assert record["counts"]["pinned"] == 0
    assert [item["reason"] for item in record["refused"]] == [
        display_glyph.REFUSED_LETTERED_RUN
    ]
    assert len(page.pdf_paragraph) == 1


def test_the_switch_down_leaves_the_page_alone(tmp_path) -> None:
    host = _mixed_paragraph([("A line ", 8.0), ("8", 65.0)])
    record, page = _apply(tmp_path, [host], on=False)
    assert record is None
    assert len(page.pdf_paragraph) == 1


def test_inventory_records_the_pinned_glyph_as_its_own_asset_class(
    tmp_path,
) -> None:
    host = _mixed_paragraph([("A line here to hold ", 8.0), ("8", 65.0)])
    _record, page = _apply(tmp_path, [host])
    docs = il.Document(page=[page], total_pages=3)

    inventory = fixed_assets.build_inventory(docs)

    glyph_assets = [
        asset
        for asset in inventory.assets
        if asset.asset_class == fixed_assets.DISPLAY_GLYPH_ASSET_CLASS
    ]
    assert len(glyph_assets) == 1
    assert glyph_assets[0].protected is True
    assert glyph_assets[0].asset_type == fixed_assets.FURNITURE_TYPE


def test_translation_paths_refuse_a_pinned_glyph(tmp_path) -> None:
    from babeldoc.format.pdf.document_il.midend.il_translator import (
        DocumentTranslateTracker,
    )
    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator

    host = _mixed_paragraph([("A line here to hold ", 8.0), ("8888", 65.0)])
    _record, page = _apply(tmp_path, [host])
    pinned = page.pdf_paragraph[1]
    assert pinned.unicode == "8888"

    translator = object.__new__(ILTranslator)
    translator.coverage_snapshot = None
    translator.translation_config = SimpleNamespace(
        magazine_coverage_snapshot=None
    )
    tracker = DocumentTranslateTracker().new_page().new_paragraph()
    assert translator.pre_translate_paragraph(pinned, tracker, {}, {}) == (
        None,
        None,
    )
