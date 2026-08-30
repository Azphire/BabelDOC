"""The tail-fill sidecar measures the finished page, by hand-checkable numbers.

From B14 on a claim about column tails cites this pass; these tests pin its
arithmetic to values computed by hand on a synthetic paragraph, so the sidecar
cannot drift into describing something other than the rendered last line.
"""

from __future__ import annotations

import json
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.magazine import tail_fill
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import SourceElementRef


class RuntimeConfig:
    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir
        self.magazine_tail_fill = True

    def get_working_file_path(self, name: str) -> str:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return str(self.working_dir / name)


def character(text: str, x: float, baseline: float, width: float = 10.0):
    return il.PdfCharacter(
        char_unicode=text,
        box=il.Box(x=x, y=baseline, x2=x + width, y2=baseline + 10.0),
        pdf_style=il.PdfStyle(
            font_id="body", font_size=10.0, graphic_state=il.GraphicState()
        ),
        advance=width,
    )


def paragraph(lines: list[tuple[str, float]], box: tuple) -> il.PdfParagraph:
    """Each entry is (text, baseline); characters start at the box left."""
    characters = []
    for text, baseline in lines:
        for position, glyph in enumerate(text):
            characters.append(character(glyph, box[0] + position * 10.0, baseline))
    return il.PdfParagraph(
        box=il.Box(*box),
        unicode="".join(text for text, _ in lines),
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=item) for item in characters
        ],
        layout_label="plain text",
    )


def element(ref: str, page: int, column: int, order: int) -> SourceElementRef:
    return SourceElementRef(
        source_ref=ref,
        page=page,
        column=column,
        reading_order=order,
        role="plain text",
        source_box=None,
        source_text_hash="0" * 64,
        style_hash="0" * 64,
    )


def document(paragraphs_by_page: dict[int, list]) -> il.Document:
    return il.Document(
        page=[
            il.Page(
                page_number=page_label - 1,
                mediabox=il.Mediabox(box=il.Box(0.0, 0.0, 400.0, 300.0)),
                cropbox=il.Cropbox(box=il.Box(0.0, 0.0, 400.0, 300.0)),
                pdf_paragraph=paragraphs,
            )
            for page_label, paragraphs in sorted(paragraphs_by_page.items())
        ],
        total_pages=len(paragraphs_by_page),
    )


def article_ir(elements: list[SourceElementRef]) -> ArticleDocumentIR:
    article = ArticleIR(
        article_id="article-fixture",
        pages=tuple(sorted({item.page for item in elements})),
        elements=tuple(elements),
        slots=(),
        chain_ids=(),
        policy_evidence=(),
    )
    return ArticleDocumentIR(
        articles=(article,),
        by_page={page: article.article_id for page in article.pages},
        by_element={item.source_ref: article.article_id for item in elements},
        by_chain={},
    )


def test_cross_column_tail_is_measured_by_hand_checkable_numbers(tmp_path) -> None:
    # The handing-over paragraph: a full 10-char line and a 3-char last line
    # of 10 pt glyphs in a 100 pt box, so the fill ratio is exactly 0.3.
    prev = paragraph([("这是一整行的十个字啊", 80.0), ("尾巴字", 65.0)], (10.0, 60.0, 110.0, 92.0))
    nxt = paragraph([("接续的下一段文本内容", 80.0)], (150.0, 60.0, 250.0, 92.0))
    docs = document({4: [prev, nxt]})
    ir = article_ir([element("p4#0", 4, 0, 10), element("p4#1", 4, 1, 11)])
    config = RuntimeConfig(tmp_path)
    record = tail_fill.apply(config, docs, article_document_ir=ir)
    assert record["status"] == "success"
    assert len(record["boundaries"]) == 1
    row = record["boundaries"][0]
    assert row["prev_ref"] == "p4#0"
    assert row["next_ref"] == "p4#1"
    assert row["boundary"] == tail_fill.BOUNDARY_COLUMN
    assert row["chained"] is False
    line = row["last_line"]
    assert line["chars"] == 3
    assert line["ink_width_pt"] == 30.0
    assert line["measure_pt"] == 100.0
    assert line["fill_ratio"] == 0.3
    assert line["terminal_punct"] is False
    assert line["lines"] == 2
    summary = record["summary"]
    assert summary["boundaries"] == 1
    assert summary["fill_ratio"]["median"] == 0.3
    assert summary["full_line_share"] == 0.0
    # A 3-char tail is above the 1-2 char dangling list's ceiling.
    assert summary["short_tails"] == []
    report = json.loads(
        (tmp_path / tail_fill.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert report["boundaries"][0]["last_line"]["fill_ratio"] == 0.3


def test_two_char_dangling_tail_lands_in_the_short_list(tmp_path) -> None:
    prev = paragraph([("这是一整行的十个字啊", 80.0), ("家、", 65.0)], (10.0, 60.0, 110.0, 92.0))
    nxt = paragraph([("接续文本", 80.0)], (150.0, 60.0, 250.0, 92.0))
    docs = document({4: [prev, nxt]})
    ir = article_ir([element("p4#0", 4, 0, 10), element("p4#1", 4, 1, 11)])
    record = tail_fill.apply(RuntimeConfig(tmp_path), docs, article_document_ir=ir)
    summary = record["summary"]
    assert len(summary["short_tails"]) == 1
    tail = summary["short_tails"][0]
    assert tail["chars"] == 2
    assert tail["text"] == "家、"
    assert tail["terminal_punct"] is False


def test_terminal_punctuation_is_read_with_the_chain_vocabulary(tmp_path) -> None:
    prev = paragraph([("这是一整行的十个字啊", 80.0), ("结束了。", 65.0)], (10.0, 60.0, 110.0, 92.0))
    nxt = paragraph([("新的段落", 80.0)], (150.0, 60.0, 250.0, 92.0))
    docs = document({4: [prev, nxt]})
    ir = article_ir([element("p4#0", 4, 0, 10), element("p4#1", 4, 1, 11)])
    record = tail_fill.apply(RuntimeConfig(tmp_path), docs, article_document_ir=ir)
    assert record["boundaries"][0]["last_line"]["terminal_punct"] is True


def test_chain_cut_is_measured_even_without_an_article_pair(tmp_path) -> None:
    prev = paragraph([("这是一整行的十个字啊", 80.0), ("挂尾", 65.0)], (10.0, 60.0, 110.0, 92.0))
    nxt = paragraph([("接续文本", 80.0)], (150.0, 60.0, 250.0, 92.0))
    docs = document({4: [prev, nxt]})
    config = RuntimeConfig(tmp_path)
    chain_report = {
        "chains": [
            {
                "chain_id": "AbCdE",
                "boundary_kinds": ["column"],
                "allocation": {
                    "fragments": [
                        {"slot_order": 0, "source_ref": "p4#0"},
                        {"slot_order": 1, "source_ref": "p4#1"},
                    ]
                },
            }
        ]
    }
    (tmp_path / tail_fill.CHAIN_REPORT_NAME).write_text(
        json.dumps(chain_report), encoding="utf-8"
    )
    record = tail_fill.apply(config, docs, article_document_ir=None)
    assert len(record["boundaries"]) == 1
    row = record["boundaries"][0]
    assert row["chained"] is True
    assert row["chain_id"] == "AbCdE"
    assert row["last_line"]["chars"] == 2
    assert record["summary"]["chained"] == 1


def test_switch_off_measures_nothing(tmp_path) -> None:
    config = RuntimeConfig(tmp_path)
    config.magazine_tail_fill = False
    assert tail_fill.apply(config, document({1: []})) is None
    assert not (tmp_path / tail_fill.REPORT_NAME).exists()
