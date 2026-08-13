"""Freeze the orphan lines of a really translated document, in full.

The b8.1 fixture keeps every paragraph as the string it renders as, which is
everything the detectors read and nothing the repair needs: a rebuilt run takes
its style from the paragraph's own characters, and laying it out again resolves
that style's font id against the page's font list. Both are dropped there.

So this is a second, narrower freeze of the same b7.5 second pass checkpoint:
the pages carrying an untranslated orphan, with those orphan paragraphs kept
exactly as the run left them -- characters, styles, formula grouping, boxes --
and every other paragraph of those pages kept as its rendered text, so the
arithmetic the loop does over a page is the arithmetic it would do over the
real one. The page font list is kept whole, because that is what a font id
resolves against.

Usage:
    python build_orphan_fixture.py [<source checkpoint>]
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
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine.detectors import base  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import writeback  # noqa: E402
from babeldoc.magazine.react.config import ORPHAN_LABELS_KEY  # noqa: E402
from babeldoc.magazine.react.config import load_repair_config  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b8"
FIXTURE_NAME = "Courier-en.orphans.fixture.xml"
PROVENANCE_NAME = "Courier-en.orphans.fixture.json"

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


def orphan_labels() -> tuple[str, ...]:
    config = load_repair_config(
        None, tuple(sorted(module.KIND for module in detectors.DETECTORS.values()))
    )
    return tuple(config.actions[actions.NAME].applicability[ORPHAN_LABELS_KEY])


def trimmed(paragraph):
    """One paragraph as its rendered text, the way the b8.1 fixture keeps them."""
    return il_version_1.PdfParagraph(
        box=paragraph.box,
        pdf_style=paragraph.pdf_style,
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        unicode=base.rendered_text(paragraph)
                    )
                )
            )
        ],
        xobj_id=paragraph.xobj_id,
        unicode=paragraph.unicode,
        vertical=paragraph.vertical,
        debug_id=paragraph.debug_id,
        layout_label=paragraph.layout_label,
        scale=paragraph.scale,
        optimal_scale=paragraph.optimal_scale,
    )


def referenced_fonts(paragraph) -> set[str]:
    """Font ids the orphan's own characters name, which is what has to resolve."""
    style = writeback.paragraph_style(paragraph)
    return {style.font_id} if style is not None and style.font_id else set()


def keep(page, labels: tuple[str, ...]) -> tuple[il_version_1.Page, list[int]]:
    kept: list[int] = []
    paragraphs = []
    needed: set[str] = set()
    for index, paragraph in enumerate(page.pdf_paragraph or ()):
        if (paragraph.layout_label or "") in labels and writeback.can_write_back(
            paragraph
        ):
            paragraphs.append(paragraph)
            kept.append(index)
            needed |= referenced_fonts(paragraph)
        else:
            paragraphs.append(trimmed(paragraph))
    # Only the fonts an orphan resolves against: a font is metric tables, and
    # nothing else in this fixture is laid out again.
    return (
        il_version_1.Page(
            mediabox=page.mediabox,
            cropbox=page.cropbox,
            pdf_font=[
                font for font in page.pdf_font or () if font.font_id in needed
            ],
            pdf_xobject=[
                il_version_1.PdfXobject(
                    box=xobject.box,
                    xobj_id=xobject.xobj_id,
                    pdf_font=[
                        font
                        for font in xobject.pdf_font or ()
                        if font.font_id in needed
                    ],
                )
                for xobject in page.pdf_xobject or ()
            ],
            pdf_paragraph=paragraphs,
            pdf_figure=[
                il_version_1.PdfFigure(box=figure.box)
                for figure in page.pdf_figure or ()
            ],
            page_number=page.page_number,
            unit=page.unit,
            page_kind=page.page_kind,
            page_kind_conf=page.page_kind_conf,
            page_kind_source=page.page_kind_source,
        ),
        kept,
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

    labels = orphan_labels()
    pages = []
    held: dict[str, list[int]] = {}
    for position, page in enumerate(docs.page):
        trimmed_page, kept = keep(page, labels)
        if not kept:
            continue
        pages.append(trimmed_page)
        held[str(position + 1)] = kept

    trimmed_document = il_version_1.Document(page=pages, total_pages=len(pages))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fixture = OUT_DIR / FIXTURE_NAME
    fixture.write_text(
        checkpoint_module.to_checkpoint_xml(trimmed_document), encoding="utf-8"
    )

    provenance = {
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "fixture_bytes": fixture.stat().st_size,
        "orphan_labels": list(labels),
        "pages": len(pages),
        "paragraphs": sum(len(page.pdf_paragraph) for page in pages),
        "orphans_by_source_page": held,
        "kept": [
            "page: mediabox, cropbox, pageNumber, unit, pageKind and its "
            "provenance, the whole pdfFont list, pdfXobject boxes and fonts, "
            "pdfFigure boxes",
            "orphan paragraph: everything, as the run left it",
            "every other paragraph: box, pdfStyle, orientation, label, scales "
            "and rendered text as one unicode composition",
        ],
        "dropped": [
            "page characters, curves, forms, layouts, rectangles and base "
            "operations; the compositions of non-orphan paragraphs"
        ],
    }
    with (OUT_DIR / PROVENANCE_NAME).open("w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(provenance, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
