"""The geometry of a produced PDF, read from the file instead of from the IL.

Every other metric in this package reads an intermediate language checkpoint,
which is a luxury only a run of this fork leaves behind. The upstream baseline is
six PDFs and nothing else: no checkpoint, no paragraph objects, no layout labels.
Measuring the fork against a baseline it cannot measure is not a comparison, so
this module builds the smallest thing the other metrics already know how to read
-- an ``il_version_1.Document`` -- out of what a PDF viewer can see.

What it puts in it:

*One paragraph per text block.* ``pymupdf`` returns the page's text as blocks of
lines of spans of positioned characters. A block becomes a ``PdfParagraph`` whose
box is the block's box and whose characters are the block's characters with their
own boxes, which is exactly the shape the line banding and the tail reading of
``mid_break_rate`` need. A block has no layout class, so every one of them is
labelled with ``pdf_block_label`` from ``configs/metrics.json``; the label has to
be one the endpoint filter admits or this path would offer no tail at all.

*One figure per raster image.* ``get_image_info`` reports where each image was
drawn on the page. They become ``pdf_figure`` elements, which the image measures
already read.

*Coordinates flipped.* ``pymupdf`` measures down from the top left of the page
rectangle and the intermediate language measures up from the bottom left, so
every box is flipped on the way in and the page frame is the page rectangle at
the origin. Both sides of any comparison this module takes part in are built the
same way, so the flip cancels; what it buys is that the same metric code runs
over both paths without knowing which it is looking at.

**A block is not a paragraph.** This is the whole caveat of the path and the
reason ``tools/eval_report.py`` measures a fork run down both of them. A text
block is a run of lines a viewer found close enough together to group; a
``PdfParagraph`` is what the layout parser and the paragraph finder concluded a
paragraph was, which on a dense page is a very different partition of the same
ink. Element counts drive Overlap and Alignment directly, so the two paths do not
produce comparable values of either, and the measured size of that gap is
recorded in ``docs/eval/metric_contract.md`` rather than assumed to be small.
Nothing here corrects for it: a metric that quietly reconciled two methods would
be reporting the correction.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.metrics import MetricError
from babeldoc.magazine.metrics import MetricsConfig
from babeldoc.magazine.metrics import load_metrics_config

# The block kind pymupdf gives a run of text; anything else on a page is an
# image block, which this module reads from the image table instead.
TEXT_BLOCK = 0


def _box(bbox, rect) -> il_version_1.Box:
    """One viewer rectangle as the intermediate language would have stored it.

    Two changes of frame at once: the origin moves to the page rectangle's own
    corner, so a page whose box does not start at zero still lands on a frame
    that does, and the vertical axis is inverted, since the viewer measures down
    from the top and the intermediate language measures up from the bottom.
    """
    x0, y0, x1, y1 = (float(value) for value in bbox)
    return il_version_1.Box(
        x=min(x0, x1) - float(rect.x0),
        y=float(rect.y1) - max(y0, y1),
        x2=max(x0, x1) - float(rect.x0),
        y2=float(rect.y1) - min(y0, y1),
    )


def _characters(line: dict, rect) -> list[il_version_1.PdfCharacter]:
    characters = []
    for span in line.get("spans", ()):
        for character in span.get("chars", ()):
            bbox = character.get("bbox")
            text = character.get("c")
            if bbox is None or text is None:
                continue
            characters.append(
                il_version_1.PdfCharacter(char_unicode=text, box=_box(bbox, rect))
            )
    return characters


def _is_vertical(block: dict) -> bool:
    """Whether the block's lines run down the page rather than across it.

    ``dir`` is the unit vector a line is written along. The test is which of its
    two components dominates, which needs no threshold: a line at exactly 45
    degrees is not a page anybody set, and the tie falls to horizontal, where the
    tail reading at least has a defined answer.
    """
    for line in block.get("lines", ()):
        direction = line.get("dir")
        if direction and abs(direction[1]) > abs(direction[0]):
            return True
    return False


def _paragraph_of(
    block: dict, index: int, page_number: int, rect, label: str
) -> il_version_1.PdfParagraph | None:
    compositions = []
    text = []
    for line in block.get("lines", ()):
        for character in _characters(line, rect):
            compositions.append(
                il_version_1.PdfParagraphComposition(pdf_character=character)
            )
            text.append(character.char_unicode)
    if not compositions:
        return None
    return il_version_1.PdfParagraph(
        box=_box(block["bbox"], rect),
        unicode="".join(text),
        layout_label=label,
        debug_id=f"p{page_number}#{index}",
        vertical=_is_vertical(block),
        pdf_paragraph_composition=compositions,
    )


def page_from_pdf(page, index: int, label: str) -> il_version_1.Page:
    """One viewer page as a document page the other metrics can read."""
    rect = page.rect
    frame = il_version_1.Box(
        x=0.0, y=0.0, x2=float(rect.width), y2=float(rect.height)
    )
    raw = page.get_text("rawdict")

    paragraphs = []
    for position, block in enumerate(raw.get("blocks", ())):
        if block.get("type") != TEXT_BLOCK:
            continue
        paragraph = _paragraph_of(block, position, index + 1, rect, label)
        if paragraph is not None:
            paragraphs.append(paragraph)

    figures = [
        il_version_1.PdfFigure(box=_box(image["bbox"], rect))
        for image in page.get_image_info()
        if image.get("bbox") is not None
    ]

    return il_version_1.Page(
        page_number=index,
        mediabox=il_version_1.Mediabox(box=frame),
        cropbox=il_version_1.Cropbox(box=frame),
        pdf_paragraph=paragraphs,
        pdf_figure=figures,
    )


def document_from_pdf(
    path: Path | str, config: MetricsConfig | None = None
) -> il_version_1.Document:
    """A whole PDF as a document, one page at a time, reading nothing else."""
    config = config or load_metrics_config()
    if not config.pdf_block_label:
        raise MetricError("pdf_block_label declares no label for an extracted block")
    label = config.pdf_block_label[0]
    source = Path(path)
    if not source.is_file():
        raise MetricError(f"{source} is not a file")
    pages = []
    with pymupdf.open(source) as document:
        for index in range(document.page_count):
            pages.append(page_from_pdf(document[index], index, label))
    return il_version_1.Document(page=pages, total_pages=len(pages))
