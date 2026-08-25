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

By the stable ``pN#k`` source reference frozen after the structural stages.
Where RunTrace is available its canonical source boxes are used after the
checkpoint has been validated. Standalone callers use the same positional
reference over the checkpoint itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine import checkpoint
from babeldoc.magazine.detectors import base
from babeldoc.magazine.line_split import LINE_ID_SEPARATOR

logger = logging.getLogger(__name__)


AVAILABLE = "available"
MISSING = "missing"
INVALID = "invalid"


class SourceGeometryStatus(str, Enum):
    AVAILABLE = AVAILABLE
    MISSING = MISSING
    INVALID = INVALID


def root_id(debug_id: str | None) -> str | None:
    """Normalize a legacy diagnostic id without using it for decisions."""
    if not debug_id:
        return None
    return debug_id.split(LINE_ID_SEPARATOR, 1)[0]


@dataclass(frozen=True)
class SourceGeometry:
    """Where every paragraph of the untranslated document stood."""

    stage: str
    path: str
    boxes: dict[str, tuple[float, float, float, float]]

    def box_for(self, source_ref: str) -> tuple[float, float, float, float] | None:
        """Where one stable source reference stood."""
        return self.boxes.get(source_ref)


@dataclass(frozen=True)
class SourceGeometryResult:
    """Typed checkpoint outcome used by every source-dependent consumer."""

    status: SourceGeometryStatus
    stage: str
    checkpoint: str | None
    geometry: SourceGeometry | None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.status is SourceGeometryStatus.AVAILABLE

    def issue(self) -> dict | None:
        if self.available:
            return None
        return {
            "code": f"source_checkpoint_{self.status.value}",
            "status": self.status.value,
            "stage": self.stage,
            "checkpoint": self.checkpoint,
            "blocked": True,
            "reason": self.reason,
        }

    def to_record(self) -> dict:
        return {
            "status": self.status.value,
            "stage": self.stage,
            "checkpoint": self.checkpoint,
            "paragraphs": 0 if self.geometry is None else len(self.geometry.boxes),
            "reason": self.reason,
        }


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
    """Every source paragraph box keyed by stable positional reference.

    Cached on the file's identity rather than its name alone, so a rerun that
    wrote a new checkpoint into the same working directory is read again. The
    repair loop detects several times over one document and would otherwise
    parse the same file once per iteration.
    """
    docs = checkpoint.load_checkpoint(stamp[0])
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for page_index, page in enumerate(docs.page or ()):
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph or ()):
            key = f"p{page_index + 1}#{paragraph_index}"
            box, _source = base.rendered_box(paragraph)
            if box is not None:
                boxes[key] = box
    return boxes


def load(working_dir, stage: str, run_trace=None) -> SourceGeometryResult:
    """Read and validate the source checkpoint without hiding its failure mode."""
    path = None
    try:
        path = checkpoint_path(working_dir, stage)
        if path is None:
            return SourceGeometryResult(
                status=SourceGeometryStatus.MISSING,
                stage=stage,
                checkpoint=None,
                geometry=None,
                reason="the declared source checkpoint is absent",
            )
        boxes = _boxes_of(_stamp(path))
        if run_trace is not None:
            traced = {
                reference: source.source_box
                for reference, source in run_trace.sources.items()
                if source.source_box is not None
            }
            if traced:
                boxes = traced
        geometry = SourceGeometry(stage=stage, path=path.name, boxes=boxes)
        return SourceGeometryResult(
            status=SourceGeometryStatus.AVAILABLE,
            stage=stage,
            checkpoint=path.name,
            geometry=geometry,
        )
    except Exception as exc:  # noqa: BLE001 - failure is returned as typed state
        logger.warning(
            "detection: the source layout of stage %s could not be read from %s "
            "(%s); source-dependent actions are blocked",
            stage,
            path if path is not None else working_dir,
            exc,
        )
        return SourceGeometryResult(
            status=SourceGeometryStatus.INVALID,
            stage=stage,
            checkpoint=None if path is None else path.name,
            geometry=None,
            reason=f"{type(exc).__name__}: {exc}",
        )
