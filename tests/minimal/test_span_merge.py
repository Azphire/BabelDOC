"""The span merge: a word split across a style boundary is rejoined.

CERN Courier's footer set ``Volume 66 Number 4 July/August 2026`` with the
small-cap initial of each word on one side of a style boundary and the rest on
the other, letterspaced throughout; the two halves translated separately and
the page printed ``J七月 / A八月``.  These tests pin the shape rule: a
lowercase continuation across a letter-sized gap merges (either orientation),
a word-sized gap does not, and a run at drop cap scale is left for the drop
cap lane.
"""

from __future__ import annotations

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.magazine import span_merge
from babeldoc.magazine.echo_retry import _within_length
from babeldoc.magazine.span_merge import SKIP_SIZE_RATIO
from babeldoc.magazine.span_merge import merge_paragraph

from tests.minimal.test_drop_cap_keep_flatten import pdf_style

BODY_SIZE = 10.0


def characters(text: str, x: float, style, *, gap: float = 0.0, y: float = 100.0):
    """Characters laid left to right, ``gap`` points between neighbours."""
    built = []
    cursor = x
    for glyph in text:
        width = BODY_SIZE * 0.5
        built.append(
            il.PdfCharacter(
                char_unicode=glyph,
                box=il.Box(cursor, y, cursor + width, y + BODY_SIZE),
                pdf_style=style,
                advance=width,
                xobj_id=0,
            )
        )
        cursor += width + gap
    return built, cursor


def span_composition(chars, style):
    holder = il.PdfSameStyleCharacters(
        box=None, pdf_style=style, pdf_character=list(chars)
    )
    return il.PdfParagraphComposition(pdf_same_style_characters=holder)


def line_composition(chars):
    holder = il.PdfLine(box=None, pdf_character=list(chars))
    return il.PdfParagraphComposition(pdf_line=holder)


def paragraph_of(*compositions, style=None):
    return il.PdfParagraph(
        unicode="",
        box=il.Box(0, 0, 500, 120),
        pdf_style=style or pdf_style(font_size=BODY_SIZE),
        pdf_paragraph_composition=list(compositions),
        debug_id="span-merge-test",
        layout_label="plain text",
    )


def config():
    return span_merge.load_span_merge_config()


RATIO = 2.0


def visible(paragraph) -> str:
    return span_merge._paragraph_text(paragraph)


def test_initial_span_merges_into_word_continuation():
    """``<style>V</style>olume``, contiguous: the initial joins the word."""
    initial_style = pdf_style(font_id="smallcaps", font_size=BODY_SIZE)
    body = pdf_style(font_size=BODY_SIZE)
    left, cursor = characters("V", 0.0, initial_style)
    right, _ = characters("olume", cursor + 0.2, body)
    para = paragraph_of(
        span_composition(left, initial_style), span_composition(right, body)
    )
    before = visible(para)
    merges, skips = merge_paragraph(para, config(), RATIO)
    assert [item["word"] for item in merges] == ["Volume"]
    assert merges[0]["direction"] == "left_into_right"
    assert skips == []
    assert visible(para) == before == "Volume"
    # The emptied initial span is gone; the word stands in one container,
    # styled as the continuation is.
    assert len(para.pdf_paragraph_composition) == 1
    holder = para.pdf_paragraph_composition[0].pdf_same_style_characters
    assert [c.char_unicode for c in holder.pdf_character] == list("Volume")
    assert holder.pdf_character[0].pdf_style is body


def test_letterspaced_flow_initial_joins_span():
    """Bare ``J`` before a letterspaced ``uly`` span: the CERN footer shape."""
    body = pdf_style(font_size=BODY_SIZE)
    caps = pdf_style(font_id="smallcaps", font_size=BODY_SIZE)
    left, cursor = characters("J", 0.0, body)
    right, _ = characters("uly", cursor + 3.0, caps, gap=3.0)
    para = paragraph_of(line_composition(left), span_composition(right, caps))
    before = visible(para)
    merges, skips = merge_paragraph(para, config(), RATIO)
    assert [item["word"] for item in merges] == ["July"]
    assert merges[0]["direction"] == "left_into_right"
    assert visible(para) == before
    holder = para.pdf_paragraph_composition[-1].pdf_same_style_characters
    assert [c.char_unicode for c in holder.pdf_character] == list("July")
    # The moved letter takes the span's style: one word, one voice.
    assert holder.pdf_character[0].pdf_style is caps


def test_word_gap_is_not_a_split_word():
    """A lettered span before a separate word does not swallow it."""
    marker = pdf_style(font_id="smallcaps", font_size=BODY_SIZE)
    body = pdf_style(font_size=BODY_SIZE)
    left, cursor = characters("A", 0.0, marker)
    # A full space-width gap: this is "A text", not "Atext".
    right, _ = characters("text", cursor + 3.0, body)
    para = paragraph_of(span_composition(left, marker), line_composition(right))
    before = visible(para)
    merges, skips = merge_paragraph(para, config(), RATIO)
    assert merges == [] and skips == []
    assert visible(para) == before


def test_uppercase_continuation_is_refused_with_a_record():
    """Contiguous but not a continuation: recorded, not merged."""
    marker = pdf_style(font_id="smallcaps", font_size=BODY_SIZE)
    body = pdf_style(font_size=BODY_SIZE)
    left, cursor = characters("A", 0.0, marker)
    right, _ = characters("BC", cursor + 0.2, body)
    para = paragraph_of(span_composition(left, marker), line_composition(right))
    merges, skips = merge_paragraph(para, config(), RATIO)
    assert merges == []
    assert [item["skip"] for item in skips] == ["not_lowercase_continuation"]


def test_drop_cap_scale_initial_is_left_for_the_drop_cap_lane():
    """An oversized initial is the drop cap's letter, not this pass's."""
    huge = pdf_style(font_id="display", font_size=BODY_SIZE * 2.5)
    body = pdf_style(font_size=BODY_SIZE)
    left = [
        il.PdfCharacter(
            char_unicode="V",
            box=il.Box(0, 100, 12.5, 100 + BODY_SIZE * 2.5),
            pdf_style=huge,
            advance=12.5,
            xobj_id=0,
        )
    ]
    right, _ = characters("olume", 12.7, body)
    para = paragraph_of(span_composition(left, huge), span_composition(right, body))
    merges, skips = merge_paragraph(para, config(), RATIO)
    assert merges == []
    assert [item["skip"] for item in skips] == [SKIP_SIZE_RATIO]


def test_real_space_at_the_boundary_is_a_word_break():
    """Regression for Courier p2#5's ``andtheza``: a real space character
    before the boundary means the words already broke, whatever the gaps say."""
    body = pdf_style(font_size=BODY_SIZE)
    caps = pdf_style(font_id="smallcaps", font_size=BODY_SIZE)
    left, cursor = characters("and the ", 0.0, body)
    right, _ = characters("za", cursor + 0.1, caps)
    para = paragraph_of(line_composition(left), span_composition(right, caps))
    before = visible(para)
    merges, skips = merge_paragraph(para, config(), RATIO)
    assert merges == [] and skips == []
    assert visible(para) == before


def test_source_line_lengths_reads_geometry_not_composition_kind():
    """A stacked list arriving as one styled span still counts its lines."""
    from babeldoc.format.pdf.document_il.midend.il_translator import (
        _source_line_lengths,
    )

    style = pdf_style(font_size=BODY_SIZE)
    chars = []
    for row, name in enumerate(["Subir Lall", "Papa Diaye", "Uma Rao"]):
        line, _ = characters(name, 0.0, style, y=100.0 - row * 14.0)
        chars.extend(line)
    para = paragraph_of(span_composition(chars, style))
    assert _source_line_lengths(para) == [9, 9, 6]


def test_echo_retry_length_gate_reads_lines():
    """A stacked list qualifies by its lines; a long single line does not."""
    long_text = "x" * 152
    assert _within_length("Aqib Aslam", None, 80)
    assert _within_length(long_text, [30, 25, 28, 31, 22], 80)
    assert not _within_length(long_text, None, 80)
    assert not _within_length(long_text, [152], 80)
    assert not _within_length(long_text, [30, 120], 80)
