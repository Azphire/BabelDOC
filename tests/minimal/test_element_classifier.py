from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.element_classifier import ElementClassifier

PAGE_WIDTH = 600.0
PAGE_HEIGHT = 800.0


def _paragraph(text, label, box, font_size):
    style = il_version_1.PdfStyle(font_id="test-font", font_size=font_size)
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*box),
        pdf_style=style,
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        pdf_style=style,
                        unicode=text,
                    )
                )
            )
        ],
        unicode=text,
        layout_label=label,
    )


def _document(paragraphs, *, page_kind):
    frame = il_version_1.Box(0.0, 0.0, PAGE_WIDTH, PAGE_HEIGHT)
    page = il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=frame),
        cropbox=il_version_1.Cropbox(box=frame),
        pdf_paragraph=paragraphs,
        page_number=0,
        page_kind=page_kind,
        page_kind_conf=1.0,
        page_kind_source="test",
        unit="point",
    )
    return il_version_1.Document(page=[page], total_pages=1)


def _classifier(tmp_path: Path):
    config = SimpleNamespace(get_working_file_path=lambda name: str(tmp_path / name))
    return ElementClassifier(config)


def _report(tmp_path: Path):
    return json.loads(
        (tmp_path / "element_classification.report.json").read_text(encoding="utf-8")
    )


def test_article_opener_keeps_main_title_and_separates_byline_from_body(tmp_path):
    title = _paragraph("A Shared Horizon", "title", (60, 650, 520, 740), 36)
    byline = _paragraph("By Example Writer", "title", (60, 610, 230, 630), 10)
    body = _paragraph(
        "Ordinary running text remains part of the article body.",
        "plain text",
        (60, 380, 270, 560),
        10,
    )
    document = _document([title, byline, body], page_kind="article_opener")

    _classifier(tmp_path).process(document)

    assert [item.layout_label for item in document.page[0].pdf_paragraph] == [
        "title",
        "byline",
        "plain text",
    ]
    records = {item["source_ref"]: item for item in _report(tmp_path)["elements"]}
    assert records["p1#0"]["final_role"] == "title"
    assert records["p1#1"]["final_role"] == "byline"
    assert records["p1#2"]["final_role"] == "body"
    assert records["p1#1"]["evidence"]["main_title_gap_ratio"] is not None


@pytest.mark.parametrize(
    "quote",
    [
        "“知识只有在共同守护时，才能继续照亮未来。”",
        '"Knowledge can endure when communities guard it together."',
    ],
)
def test_display_quote_caption_and_low_evidence_fallback(tmp_path, quote):
    ordinary = _paragraph(
        "Ordinary body text establishes the page typography.",
        "plain text",
        (60, 500, 250, 670),
        10,
    )
    pull_quote = _paragraph(quote, "plain text", (90, 280, 500, 350), 18)
    caption = _paragraph(
        "Figure caption",
        "figure_caption",
        (330, 80, 540, 105),
        8,
    )
    weak_display = _paragraph("Section note", "title", (330, 400, 500, 420), 12)
    document = _document(
        [ordinary, pull_quote, caption, weak_display],
        page_kind="article_body",
    )

    _classifier(tmp_path).process(document)

    assert [item.layout_label for item in document.page[0].pdf_paragraph] == [
        "plain text",
        "pull_quote",
        "figure_caption",
        "other_display",
    ]
    records = {item["source_ref"]: item for item in _report(tmp_path)["elements"]}
    assert records["p1#1"]["final_role"] == "pull_quote"
    assert records["p1#2"]["final_role"] == "caption"
    assert records["p1#2"]["operation_label"] == "figure_caption"
    assert records["p1#3"]["final_role"] == "other_display"
