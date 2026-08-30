"""An unchanged translation keeps its source composition.

The write-back path calls a translation unchanged by normalized comparison --
NFC, interior whitespace folded, outer whitespace stripped, nothing wider --
and an unchanged paragraph keeps the exact composition objects it came with.
That identity is what the protected-source chain reads downstream:
``layout_report._has_generated_target`` stays false, so the paragraph is
frozen as source furniture and passed through, character for character.
"""

from __future__ import annotations

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator
from babeldoc.magazine import layout_report


class _Tracker:
    def __init__(self):
        self.output = None

    def set_output(self, text):
        self.output = text

    def last_llm_translate_tracker(self):
        return None


def source_paragraph(text: str) -> il.PdfParagraph:
    style = il.PdfStyle(font_id="body", font_size=10.0)
    characters = [
        il.PdfCharacter(char_unicode=char, pdf_style=style) for char in text
    ]
    composition = il.PdfParagraphComposition(
        pdf_same_style_characters=il.PdfSameStyleCharacters(
            pdf_character=characters, pdf_style=style
        )
    )
    return il.PdfParagraph(
        unicode=text,
        pdf_paragraph_composition=[composition],
        pdf_style=style,
    )


def run_post_translate(paragraph: il.PdfParagraph, translated: str):
    translator = object.__new__(ILTranslator)
    translate_input = ILTranslator.TranslateInput(
        paragraph.unicode, [], paragraph.pdf_style
    )
    tracker = _Tracker()
    rewritten = translator.post_translate_paragraph(
        paragraph, tracker, translate_input, translated
    )
    assert tracker.output == translated
    return rewritten


def test_byte_identical_output_keeps_the_source_composition() -> None:
    paragraph = source_paragraph("WIPO Magazine")
    held = paragraph.pdf_paragraph_composition
    held_first = held[0]
    rewritten = run_post_translate(paragraph, "WIPO Magazine")
    assert rewritten is False
    assert paragraph.pdf_paragraph_composition is held
    assert paragraph.pdf_paragraph_composition[0] is held_first
    assert paragraph.unicode == "WIPO Magazine"
    assert not layout_report._has_generated_target(paragraph)


def test_whitespace_only_difference_keeps_the_source_composition() -> None:
    paragraph = source_paragraph("WIPO  Magazine ")
    held_first = paragraph.pdf_paragraph_composition[0]
    rewritten = run_post_translate(paragraph, " WIPO Magazine")
    assert rewritten is False
    assert paragraph.pdf_paragraph_composition[0] is held_first
    assert paragraph.unicode == "WIPO  Magazine "
    assert not layout_report._has_generated_target(paragraph)


def test_nfc_variant_keeps_the_source_composition() -> None:
    # e + combining acute against the precomposed letter.
    paragraph = source_paragraph("Café")
    rewritten = run_post_translate(paragraph, "Café")
    assert rewritten is False
    assert not layout_report._has_generated_target(paragraph)


def test_real_translation_still_rewrites_the_composition() -> None:
    paragraph = source_paragraph("Long before satellites")
    held_first = paragraph.pdf_paragraph_composition[0]
    rewritten = run_post_translate(paragraph, "早在卫星之前")
    assert rewritten is True
    assert paragraph.unicode == "早在卫星之前"
    assert paragraph.pdf_paragraph_composition
    assert paragraph.pdf_paragraph_composition[0] is not held_first
    assert layout_report._has_generated_target(paragraph)
