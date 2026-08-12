"""Freeze one really translated document as the fixture the gate detects on.

The detectors answer about a document the translator has finished with, and
this repository holds exactly one such document that cost a credential: the
typesetting checkpoint of the batch b7.5 second pass over Courier-en. That
checkpoint is five megabytes of laid out characters, almost all of which no
detector reads, and it is not tracked.

So this trims it to what the detectors do read and writes the result beside the
gate. Kept, per page: the media and crop boxes, the page number and unit, the
page kind and its provenance, every artwork box, and every paragraph's box,
style, orientation, layout label, debug id and rendered text. Dropped:
characters, curves, forms, fonts, layouts, rectangles and base operations.

The rendered text is preserved exactly, as one unicode composition per
paragraph holding the string the full composition renders as, so every detector
measures the same characters it would have measured on the full checkpoint. The
gate asserts that equality rather than assuming it: it runs the detectors over
the fixture and checks the finding this batch exists for is among them.

Usage:
    python build_fixture.py [<source checkpoint>]
"""

from __future__ import annotations

import hashlib
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine.detectors import base  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b8"
FIXTURE_NAME = "Courier-en.typeset.fixture.xml"
PROVENANCE_NAME = "Courier-en.typeset.fixture.json"

DEFAULT_SOURCE = (
    ROOT
    / "examples"
    / "output"
    / "b7_5"
    / "pass2"
    / "work"
    / "Courier-en"
    / "checkpoint.11_typesetting.xml"
)


def trim_paragraph(paragraph):
    text = base.rendered_text(paragraph)
    composition = il_version_1.PdfParagraphComposition(
        pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
            unicode=text
        )
    )
    return il_version_1.PdfParagraph(
        box=paragraph.box,
        pdf_style=paragraph.pdf_style,
        pdf_paragraph_composition=[composition],
        xobj_id=paragraph.xobj_id,
        unicode=paragraph.unicode,
        vertical=paragraph.vertical,
        debug_id=paragraph.debug_id,
        layout_label=paragraph.layout_label,
        layout_id=paragraph.layout_id,
        chain_id=paragraph.chain_id,
        chain_index=paragraph.chain_index,
    )


def trim_page(page):
    return il_version_1.Page(
        mediabox=page.mediabox,
        cropbox=page.cropbox,
        pdf_xobject=[
            il_version_1.PdfXobject(box=xobject.box, xobj_id=xobject.xobj_id)
            for xobject in page.pdf_xobject or ()
        ],
        pdf_paragraph=[
            trim_paragraph(paragraph) for paragraph in page.pdf_paragraph or ()
        ],
        pdf_figure=[
            il_version_1.PdfFigure(box=figure.box) for figure in page.pdf_figure or ()
        ],
        page_number=page.page_number,
        unit=page.unit,
        page_kind=page.page_kind,
        page_kind_conf=page.page_kind_conf,
        page_kind_source=page.page_kind_source,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    source = Path(argv[0]) if argv else DEFAULT_SOURCE
    if not source.exists():
        print(f"source checkpoint not beside this tree: {source}")
        return 1

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs = checkpoint_module.load_checkpoint(source)

    trimmed = il_version_1.Document(
        page=[trim_page(page) for page in docs.page], total_pages=docs.total_pages
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fixture = OUT_DIR / FIXTURE_NAME
    fixture.write_text(
        checkpoint_module.to_checkpoint_xml(trimmed), encoding="utf-8"
    )

    provenance = {
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_bytes": source.stat().st_size,
        "fixture_bytes": fixture.stat().st_size,
        "pages": len(trimmed.page),
        "paragraphs": sum(len(page.pdf_paragraph) for page in trimmed.page),
        "kept": [
            "page: mediabox, cropbox, pageNumber, unit, pageKind, pageKindConf, "
            "pageKindSource, pdfXobject boxes, pdfFigure boxes",
            "paragraph: box, pdfStyle, vertical, unicode, debugId, layoutLabel, "
            "layoutId, chainId, chainIndex, rendered text as one unicode "
            "composition",
        ],
        "dropped": [
            "characters, curves, forms, fonts, page layouts, rectangles, "
            "base operations"
        ],
    }
    with (OUT_DIR / PROVENANCE_NAME).open("w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(provenance, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
