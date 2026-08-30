"""What the repair loop actually changed, as two pictures of the same page.

A report that says an action was accepted and its acceptance vector improved is
still asking to be taken on trust. The claim a reader can check is the page
itself, before the loop touched it and after, rendered from the same document at
the same size.

So a run that keeps at least one action renders the pre-repair document to a
PDF of its own and rasterises, for each page an accepted action wrote to, that
page from the pre-repair PDF and the same page from the finished one. A run that
keeps nothing renders nothing: there is no repair to show, and a pair of
identical pictures would be evidence of nothing while looking like evidence of
something.

The pre-repair PDF is written through the ordinary writer, from a snapshot of
the document taken before the loop began, into a directory of its own. It is
evidence and not a deliverable, and it is never written where the run's own
output goes.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

EVIDENCE_DIR = "evidence"
BEFORE_PDF_NAME = "before_repair.pdf"
BEFORE_SUFFIX = "before"
AFTER_SUFFIX = "after"

# What the pages are rasterised at. Large enough to read a heading and see a
# paragraph's shape; small enough that a dozen pages is not a burden.
RENDER_DPI = 150


class RepairEvidenceError(RuntimeError):
    """Raised when evidence was asked for and could not be produced."""


# How much deeper than the interpreter default the snapshot may recurse. A
# magazine's intermediate representation is a wide tree rather than a deep one,
# but a large document still walks far enough through deepcopy's own frames to
# reach the default ceiling, and hitting it must not be what decides whether a
# run finishes.
_RECURSION_HEADROOM = 40_000


def capture(docs):
    """The document as it stood before the loop, kept whole.

    A deepcopy rather than a page-level snapshot: the pre-repair PDF is written
    from this, so it has to be a document the writer can walk on its own, and
    it must not share a single mutable node with the document the loop is about
    to change.

    The recursion ceiling is lifted for the copy and put back afterwards. It is
    raised rather than the copy being rewritten iteratively because the depth is
    deepcopy's own and not the document's, and lowering it again immediately
    keeps the change from reaching anything else.
    """
    import sys

    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(max(previous, _RECURSION_HEADROOM))
    try:
        return copy.deepcopy(docs)
    finally:
        sys.setrecursionlimit(previous)


def evidence_dir(config) -> Path:
    path = Path(config.get_working_file_path(EVIDENCE_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_before_pdf(config, snapshot_docs, temp_pdf_path, mediabox_data) -> Path:
    """Render the pre-repair document to a PDF of its own.

    Written through the same writer the run's own output goes through, so the
    two pictures differ by the repair and not by how they were drawn. The
    configuration is shadowed rather than mutated: the run's own output
    directory and watermark choice are not this function's to change.
    """
    from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater
    from babeldoc.format.pdf.translation_config import WatermarkOutputMode

    directory = evidence_dir(config)
    shadow = copy.copy(config)
    shadow.output_dir = directory
    shadow.watermark_output_mode = WatermarkOutputMode.NoWatermark
    shadow.no_dual = True
    shadow.debug = False
    result = PDFCreater(temp_pdf_path, snapshot_docs, shadow, mediabox_data).write(
        shadow
    )
    produced = getattr(result, "no_watermark_mono_pdf_path", None) or getattr(
        result, "mono_pdf_path", None
    )
    if not produced:
        raise RepairEvidenceError("the pre-repair document produced no PDF")
    target = directory / BEFORE_PDF_NAME
    Path(produced).replace(target)
    return target


def render_pages(pdf_path, pages, directory: Path, suffix: str) -> dict[int, Path]:
    """Rasterise the named physical pages of one PDF, one file each."""
    import pymupdf

    directory.mkdir(parents=True, exist_ok=True)
    written: dict[int, Path] = {}
    with pymupdf.open(str(pdf_path)) as document:
        for page in sorted({int(item) for item in pages}):
            index = page - 1
            if index < 0 or index >= document.page_count:
                logger.warning(
                    "page %s is outside %s and was not rendered", page, pdf_path
                )
                continue
            pixmap = document[index].get_pixmap(dpi=RENDER_DPI)
            target = directory / f"p{page}.{suffix}.png"
            pixmap.save(str(target))
            written[page] = target
    return written


def pairs(directory: Path, pages) -> dict[int, tuple[Path, Path]]:
    """The before/after pair for each page, where both halves are present."""
    found: dict[int, tuple[Path, Path]] = {}
    for page in sorted({int(item) for item in pages}):
        before = directory / f"p{page}.{BEFORE_SUFFIX}.png"
        after = directory / f"p{page}.{AFTER_SUFFIX}.png"
        if before.is_file() and after.is_file():
            found[page] = (before, after)
    return found
