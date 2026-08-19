"""The layout as the source drew it, for detectors that compare against it.

A finished page can carry two text blocks standing on top of one another for
two entirely different reasons. The translation grew and pushed one into the
other, which is a defect. Or the source itself set them that way -- a headline
painted twice, once solid and once in a texture layer; a strap band printed
across the foot of a montage; a folio sitting inside a table of contents entry
-- which is a design, and moving it would be the defect. Nothing about the
finished page separates the two, because on the finished page they look the
same.

What separates them is the page before anything was translated. So this module
loads the layout boxes of that page and hands them to the detector as a lookup,
and the detector reports a collision only where the source had none.

Where the source layout is read from
------------------------------------

The XML checkpoint of the stage named in ``configs/detectors.json``, in the
run's own working directory -- the directory the detection sidecar is written
to, which is where the pipeline dumps its checkpoints. The stage is declared
rather than hard coded, and is validated against the declared stage order, so
the file asked for is one the pipeline writes.

The checkpoint is written only where ``magazine_checkpoint`` is up. With it
down there is no source layout to compare against, and a detector that needs
one says so and does not run, rather than reporting every overlap on the page
as though the translation had caused it.

How a finished paragraph finds its source
-----------------------------------------

By ``debug_id``. The paragraph finder mints one per paragraph and every stage
after it carries the id unchanged, so within one run the id is the identity of
the paragraph across the whole pipeline. The one pass that mints derived ids is
line splitting, which names each line after the paragraph it came out of; the
separator it uses is what this module cuts back to, so a line finds the box its
parent occupied.

A paragraph with no id, or with one the source checkpoint does not carry, has
no source layout to be compared against. The watermark the typesetting stage
appends is exactly that case, and it spans most of the page. Such a paragraph
is left out of the comparison entirely rather than treated as having had no
source overlap, because "the source did not draw this" is not evidence that the
translation moved anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine import checkpoint
from babeldoc.magazine.detectors import base
from babeldoc.magazine.line_split import LINE_ID_SEPARATOR

logger = logging.getLogger(__name__)


def root_id(debug_id: str | None) -> str | None:
    """The source paragraph's id behind a possibly derived one."""
    if not debug_id:
        return None
    return debug_id.split(LINE_ID_SEPARATOR, 1)[0]


@dataclass(frozen=True)
class SourceGeometry:
    """Where every paragraph of the untranslated document stood."""

    stage: str
    path: str
    boxes: dict[str, tuple[float, float, float, float]]

    def box_of(self, paragraph) -> tuple[float, float, float, float] | None:
        """Where this paragraph's source counterpart stood, if it has one."""
        key = root_id(getattr(paragraph, "debug_id", None))
        if key is None:
            return None
        return self.boxes.get(key)


def checkpoint_path(working_dir, stage: str) -> Path | None:
    """The checkpoint file for one stage in one working directory, if present.

    Resolved through the checkpoint module's own container logic, so a run whose
    checkpoints were packed into an archive is read the same as one whose
    checkpoints are still loose files.
    """
    if working_dir is None:
        return None
    stem = checkpoint.checkpoint_stem(stage)
    found = checkpoint.checkpoint_paths(Path(working_dir), f"{stem}.xml")
    return found[0] if found else None


def _stamp(path: Path) -> tuple[str, int, int]:
    """What identifies one checkpoint file for caching: name, time and size."""
    member = checkpoint.archive_member(path)
    target = member[0] if member is not None else path
    stat = target.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=4)
def _boxes_of(stamp: tuple[str, int, int]) -> dict:
    """Every source paragraph box of one checkpoint, keyed by its id.

    Cached on the file's identity rather than its name alone, so a rerun that
    wrote a new checkpoint into the same working directory is read again. The
    repair loop detects several times over one document and would otherwise
    parse the same file once per iteration.
    """
    docs = checkpoint.load_checkpoint(stamp[0])
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for page in docs.page or ():
        for paragraph in page.pdf_paragraph or ():
            key = root_id(paragraph.debug_id)
            if key is None or key in boxes:
                continue
            box, _source = base.rendered_box(paragraph)
            if box is not None:
                boxes[key] = box
    return boxes


def load(working_dir, stage: str) -> SourceGeometry | None:
    """The source layout of one run, or None where the run did not keep it.

    Never raises. This is read on the way into a detection pass, which is on the
    path that produces the document, and a comparison that cannot be made is a
    detector that does not run rather than a translation that does not finish.
    """
    path = None
    try:
        path = checkpoint_path(working_dir, stage)
        if path is None:
            return None
        return SourceGeometry(
            stage=stage, path=path.name, boxes=_boxes_of(_stamp(path))
        )
    except Exception as exc:  # noqa: BLE001 - a missing comparison is never fatal
        logger.warning(
            "detection: the source layout of stage %s could not be read from %s "
            "(%s); the detectors that compare against it will not run",
            stage,
            path if path is not None else working_dir,
            exc,
        )
        return None
