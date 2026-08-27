"""Run-scoped diagnostic overlays kept outside the semantic document IL."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

SCHEMA_VERSION = "debug-overlay.v1"
SIDECAR_NAME = "debug_overlay.report.json"
MAX_ITEMS_PER_PAGE = 20_000
MAX_TEXT_LENGTH = 256
MAX_ABS_COORDINATE = 10_000_000.0


class ElementProvenance(str, Enum):
    SOURCE = "source"
    DERIVED_SEMANTIC = "derived_semantic"
    DEBUG_OVERLAY = "debug_overlay"


class OverlayProducer(str, Enum):
    LAYOUT_PARSER = "layout_parser"
    TABLE_PARSER = "table_parser"
    PARAGRAPH_FINDER = "paragraph_finder"
    DETECT_SCANNED = "detect_scanned"
    ADD_DEBUG_INFORMATION = "add_debug_information"
    ACTIVE_FRONTEND_CHAR_BOX = "active_frontend_char_box"
    LEGACY_FRONTEND_CHAR_BOX = "legacy_frontend_char_box"
    LEGACY_CHECKPOINT_ADAPTER = "legacy_checkpoint_adapter"


class OverlayKind(str, Enum):
    LABEL = "label"
    BOX = "box"
    LINE = "line"
    POINT = "point"


class OverlayCategory(str, Enum):
    LAYOUT = "layout"
    PARAGRAPH = "paragraph"
    FORMULA = "formula"
    FORM = "form"
    XOBJECT = "xobject"
    CHARACTER_BOX = "character_box"
    SCAN_SCORE = "scan_score"
    PAGE = "page"
    LEGACY_CONTAMINATION = "legacy_contamination"


class OverlayStyle(str, Enum):
    BLUE = "blue"
    GREEN = "green"
    ORANGE = "orange"
    PINK = "pink"
    TEAL = "teal"
    YELLOW = "yellow"
    INDIGO = "indigo"


BoxTuple = tuple[float, float, float, float]
PointTuple = tuple[float, float]


class DebugOverlayError(ValueError):
    """Raised when a diagnostic producer violates the overlay contract."""


class DebugArtifactError(RuntimeError):
    """Raised when a validated semantic PDF cannot be copied with overlays."""

    def __init__(self, output_path: str | Path, cause: BaseException):
        self.output_path = Path(output_path)
        self.cause = cause
        super().__init__(
            f"debug artifact failed for {self.output_path.name}: "
            f"{type(cause).__name__}: {cause}"
        )


def box_tuple(value) -> BoxTuple:
    if value is None:
        raise DebugOverlayError("overlay box is required")
    if isinstance(value, (tuple, list)):
        values = value
    else:
        values = [getattr(value, name, None) for name in ("x", "y", "x2", "y2")]
    if len(values) != 4 or any(item is None for item in values):
        raise DebugOverlayError("overlay box must contain four coordinates")
    return tuple(float(item) for item in values)  # type: ignore[return-value]


def _validated_box(value, page_bounds) -> BoxTuple:
    result = box_tuple(value)
    if not all(math.isfinite(item) and abs(item) <= MAX_ABS_COORDINATE for item in result):
        raise DebugOverlayError("overlay box coordinates must be finite and bounded")
    if result[0] > result[2] or result[1] > result[3]:
        raise DebugOverlayError("overlay box coordinates must be ordered")
    bounds = box_tuple(page_bounds)
    if not (
        bounds[0] <= result[0] <= result[2] <= bounds[2]
        and bounds[1] <= result[1] <= result[3] <= bounds[3]
    ):
        raise DebugOverlayError("overlay box must remain inside its physical page")
    return result


@dataclass(frozen=True, slots=True)
class DebugOverlayItem:
    source_page_number: int
    producer: OverlayProducer
    kind: OverlayKind
    category: OverlayCategory
    box: BoxTuple | None
    points: tuple[PointTuple, ...]
    text: str | None
    style: OverlayStyle
    related_semantic_ref: str | None
    provenance: ElementProvenance = ElementProvenance.DEBUG_OVERLAY

    def to_record(self) -> dict:
        return {
            "source_page_number": self.source_page_number,
            "producer": self.producer.value,
            "kind": self.kind.value,
            "category": self.category.value,
            "box": None if self.box is None else list(self.box),
            "points": [list(point) for point in self.points],
            "text": self.text,
            "style": self.style.value,
            "related_semantic_ref": self.related_semantic_ref,
            "provenance": self.provenance.value,
        }


class DebugOverlayLedger:
    """Bounded, thread-safe diagnostics that checkpoint serializers cannot see."""

    schema_version = SCHEMA_VERSION

    def __init__(self) -> None:
        self._items: list[DebugOverlayItem] = []
        self._page_counts: dict[int, int] = {}
        self._lock = threading.RLock()

    @property
    def items(self) -> tuple[DebugOverlayItem, ...]:
        with self._lock:
            return tuple(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def add(
        self,
        *,
        source_page_number: int,
        producer: OverlayProducer | str,
        kind: OverlayKind | str,
        category: OverlayCategory | str,
        page_bounds,
        box=None,
        points=(),
        text: str | None = None,
        style: OverlayStyle | str = OverlayStyle.GREEN,
        related_semantic_ref: str | None = None,
    ) -> DebugOverlayItem:
        if source_page_number < 1:
            raise DebugOverlayError("physical source page number must be positive")
        producer = OverlayProducer(producer)
        kind = OverlayKind(kind)
        category = OverlayCategory(category)
        style = OverlayStyle(style)
        if text is not None:
            text = str(text).replace("\x00", "")
            if len(text) > MAX_TEXT_LENGTH:
                text = text[:MAX_TEXT_LENGTH]
        checked_box = None if box is None else _validated_box(box, page_bounds)
        checked_points: list[PointTuple] = []
        bounds = box_tuple(page_bounds)
        for raw_point in points:
            if len(raw_point) != 2:
                raise DebugOverlayError("overlay points must contain two coordinates")
            point = (float(raw_point[0]), float(raw_point[1]))
            if not all(math.isfinite(item) for item in point):
                raise DebugOverlayError("overlay point coordinates must be finite")
            if not (bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]):
                raise DebugOverlayError("overlay point must remain inside its physical page")
            checked_points.append(point)
        if kind in (OverlayKind.BOX, OverlayKind.LABEL) and checked_box is None:
            raise DebugOverlayError(f"{kind.value} overlay requires a box")
        if kind == OverlayKind.LABEL and not text:
            raise DebugOverlayError("label overlay requires text")
        if kind in (OverlayKind.LINE, OverlayKind.POINT) and not checked_points:
            raise DebugOverlayError(f"{kind.value} overlay requires points")
        item = DebugOverlayItem(
            source_page_number=source_page_number,
            producer=producer,
            kind=kind,
            category=category,
            box=checked_box,
            points=tuple(checked_points),
            text=text,
            style=style,
            related_semantic_ref=related_semantic_ref,
        )
        with self._lock:
            count = self._page_counts.get(source_page_number, 0)
            if count >= MAX_ITEMS_PER_PAGE:
                raise DebugOverlayError("overlay item count exceeds the per-page limit")
            self._items.append(item)
            self._page_counts[source_page_number] = count + 1
        return item

    def add_box(self, **kwargs) -> DebugOverlayItem:
        return self.add(kind=OverlayKind.BOX, **kwargs)

    def add_label(self, **kwargs) -> DebugOverlayItem:
        return self.add(kind=OverlayKind.LABEL, **kwargs)

    def to_record(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "count": len(self),
            "items": [item.to_record() for item in self.items],
        }

    def digest(self) -> str:
        payload = json.dumps(
            self.to_record(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def write(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(self.to_record(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination


def ledger_for(translation_config) -> DebugOverlayLedger:
    ledger = getattr(translation_config, "debug_overlay_ledger", None)
    if ledger is None:
        ledger = DebugOverlayLedger()
        translation_config.debug_overlay_ledger = ledger
    if not isinstance(ledger, DebugOverlayLedger):
        raise DebugOverlayError("translation config carries an invalid overlay ledger")
    return ledger


def physical_page_number(page) -> int:
    return int(page.page_number) + 1


def page_bounds(page):
    holder = getattr(page, "cropbox", None) or getattr(page, "mediabox", None)
    bounds = None if holder is None else getattr(holder, "box", None)
    if bounds is None:
        raise DebugOverlayError("overlay producer requires physical page bounds")
    return bounds
