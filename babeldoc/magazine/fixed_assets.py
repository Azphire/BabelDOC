"""Stable inventory and conservation checks for fixed visual page assets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import is_dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path

REPORT_NAME = "fixed_asset_inventory.report.json"

PAGE_ASSET_COLLECTIONS = (
    "pdf_figure",
    "pdf_xobject",
    "pdf_form",
    "pdf_curve",
    "pdf_rectangle",
    "pdf_character",
)
ARTWORK_COLLECTIONS = ("pdf_figure", "pdf_xobject")
FORMULA_CHILD_COLLECTIONS = ("pdf_curve", "pdf_form")

# Ornament-grade vector paths: the small filled curves a magazine sets beside
# text -- a triangle before a caption, an oversized quotation mark opening a
# pull quote. One classifier serves both consumers -- the indent clearance
# capture that restores the source's avoidance, and the overlap detector that
# reports text set over one -- so the two can never disagree about what an
# ornament is. The judgement is geometric alone; nothing here reads color or
# path content.
ORNAMENT_CONFIG_PATH = config_path("ornament_assets.json")
ORNAMENT_ASSET_CLASS = "ornament_path"
FORMULA_TYPE = "pdf_formula"
FURNITURE_TYPE = "pdf_paragraph_furniture"
ROTATED_PARAGRAPH_TYPE = "pdf_paragraph_rotated"

# A short oversized character run the display glyph pass pinned at its source
# position (babeldoc/magazine/display_glyph.py). The label is how a pinned
# paragraph is recognised everywhere, and the enumerator below is the one
# reader both consumers share -- the indent clearance capture and the overlap
# detector -- so the two can never disagree about what a display glyph is.
DISPLAY_GLYPH_LABEL = "display_glyph"
DISPLAY_GLYPH_ASSET_CLASS = "display_glyph"


def paragraph_reference(page: int, index: int) -> str:
    return f"p{page}#{index}"


@dataclass(frozen=True, slots=True)
class AssetRecord:
    reference: str
    asset_type: str
    page: int
    bbox: tuple[float, float, float, float] | None
    digest: str
    movable: bool
    protected: bool
    formula_ref: str | None = None
    figure_ref: str | None = None
    asset_class: str | None = None

    def to_record(self) -> dict:
        return {
            "reference": self.reference,
            "asset_type": self.asset_type,
            "page": self.page,
            "bbox": None if self.bbox is None else list(self.bbox),
            "digest": self.digest,
            "movable": self.movable,
            "protected": self.protected,
            "formula_ref": self.formula_ref,
            "figure_ref": self.figure_ref,
            "asset_class": self.asset_class,
        }


@dataclass(frozen=True, slots=True)
class FixedAssetInventory:
    assets: tuple[AssetRecord, ...]
    page_sizes: tuple[tuple[int, tuple | None, tuple | None], ...]

    @property
    def by_ref(self) -> dict[str, AssetRecord]:
        return {asset.reference: asset for asset in self.assets}

    @property
    def protected_paragraph_refs(self) -> frozenset[str]:
        return frozenset(
            asset.reference
            for asset in self.assets
            if asset.asset_type in (FURNITURE_TYPE, ROTATED_PARAGRAPH_TYPE)
            and asset.protected
        )

    def page_assets(self, page: int) -> tuple[AssetRecord, ...]:
        return tuple(asset for asset in self.assets if asset.page == page)

    def to_record(self) -> dict:
        return {
            "count": len(self.assets),
            "assets": [asset.to_record() for asset in self.assets],
            "page_sizes": [
                {
                    "page": page,
                    "mediabox": None if media is None else list(media),
                    "cropbox": None if crop is None else list(crop),
                }
                for page, media, crop in self.page_sizes
            ],
        }


@dataclass(frozen=True, slots=True)
class OrnamentThresholds:
    """The declared bounds under which a filled curve counts as an ornament."""

    max_area_pt2: float
    max_side_pt: float


@lru_cache(maxsize=2)
def load_ornament_thresholds(path: str | None = None) -> OrnamentThresholds:
    """Load and validate ``configs/ornament_assets.json``."""
    config_file = ORNAMENT_CONFIG_PATH if path is None else Path(path)
    with config_file.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_file.name}: root must be an object")
    parameters = validate_bounded_config(raw, config_file)
    missing = sorted(
        {"ornament_max_area_pt2", "ornament_max_side_pt"} - set(parameters)
    )
    if missing:
        raise ConfigError(f"{config_file.name}: missing parameters {missing}")
    return OrnamentThresholds(
        max_area_pt2=float(parameters["ornament_max_area_pt2"]),
        max_side_pt=float(parameters["ornament_max_side_pt"]),
    )


def is_ornament_curve(curve, thresholds: OrnamentThresholds) -> bool:
    """Whether one ``pdf_curve`` is ornament-grade, judged by shape alone.

    A fill under both declared bounds. The area ceiling keeps background
    color blocks and large illustrations out; degenerate boxes paint no ink
    a line could stand on and are refused outright. ``debug_info`` is not
    consulted -- the frontend stamps it truthy on real curves too.
    """
    if not getattr(curve, "fill_background", False):
        return False
    box = getattr(curve, "box", None)
    if box is None:
        return False
    width = float(box.x2) - float(box.x)
    height = float(box.y2) - float(box.y)
    if width <= 0 or height <= 0:
        return False
    if width * height > thresholds.max_area_pt2:
        return False
    return max(width, height) <= thresholds.max_side_pt


def ornament_curves(
    page, thresholds: OrnamentThresholds
) -> tuple[tuple[int, tuple[float, float, float, float]], ...]:
    """Every ornament-grade curve of one page: (index into pdf_curve, bbox)."""
    found = []
    for index, curve in enumerate(getattr(page, "pdf_curve", None) or ()):
        if is_ornament_curve(curve, thresholds):
            box = curve.box
            found.append(
                (
                    index,
                    (float(box.x), float(box.y), float(box.x2), float(box.y2)),
                )
            )
    return tuple(found)


def display_glyph_paragraphs(
    page,
) -> tuple[tuple[int, tuple[float, float, float, float]], ...]:
    """Every pinned display glyph of one page: (index into pdf_paragraph, bbox)."""
    found = []
    for index, paragraph in enumerate(getattr(page, "pdf_paragraph", None) or ()):
        if getattr(paragraph, "layout_label", None) != DISPLAY_GLYPH_LABEL:
            continue
        box = getattr(paragraph, "box", None)
        if box is None:
            continue
        found.append(
            (index, (float(box.x), float(box.y), float(box.x2), float(box.y2)))
        )
    return tuple(found)


@dataclass(frozen=True, slots=True)
class InventoryComparison:
    holds: bool
    count_before: int
    count_after: int
    added: tuple[str, ...]
    removed: tuple[str, ...]
    bbox_changed: tuple[str, ...]
    digest_changed: tuple[str, ...]
    page_size_changed: tuple[int, ...]

    def to_record(self) -> dict:
        return {
            "holds": self.holds,
            "count_before": self.count_before,
            "count_after": self.count_after,
            "added": list(self.added),
            "removed": list(self.removed),
            "bbox_changed": list(self.bbox_changed),
            "digest_changed": list(self.digest_changed),
            "page_size_changed": list(self.page_size_changed),
        }


def _stable_value(value, *, root: bool = False):
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _stable_value(getattr(value, field.name))
            for field in fields(value)
            if not (root and field.name == "box")
        }
    if isinstance(value, Mapping):
        return {
            str(key): _stable_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple):
        return [_stable_value(item) for item in value]
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def content_digest(value) -> str:
    payload = json.dumps(
        _stable_value(value, root=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _box(value) -> tuple[float, float, float, float] | None:
    return _box_tuple(getattr(value, "box", None))


def _page_box(value) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    return _box_tuple(getattr(value, "box", value))


def _box_tuple(value) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    coordinates = tuple(getattr(value, name, None) for name in ("x", "y", "x2", "y2"))
    if any(coordinate is None for coordinate in coordinates):
        return None
    return tuple(float(coordinate) for coordinate in coordinates)


def _record(
    reference: str,
    asset_type: str,
    page: int,
    value,
    *,
    formula_ref: str | None = None,
    figure_ref: str | None = None,
    asset_class: str | None = None,
) -> AssetRecord:
    return AssetRecord(
        reference=reference,
        asset_type=asset_type,
        page=page,
        bbox=_box(value),
        digest=content_digest(value),
        movable=False,
        protected=True,
        formula_ref=formula_ref,
        figure_ref=figure_ref,
        asset_class=asset_class,
    )


def _article_refs(article_document_ir, run_trace) -> tuple[set[str] | None, set[int]]:
    if article_document_ir is not None:
        return (
            set(article_document_ir.by_element),
            {item.page for item in article_document_ir.unsupported_pages},
        )
    if run_trace is None:
        return None, set()
    sources = getattr(run_trace, "sources", {})
    return (
        {reference for reference, source in sources.items() if source.article_id},
        set(getattr(run_trace, "unsupported_pages", ())),
    )


def _flow_owned_refs(references) -> frozenset[str]:
    held = frozenset(references)
    for reference in held:
        if not isinstance(reference, str):
            raise ValueError(f"invalid flow-owned paragraph ref: {reference!r}")
        page, separator, index = reference.partition("#")
        if (
            separator != "#"
            or not page.startswith("p")
            or not page[1:].isdigit()
            or not index.isdigit()
            or int(page[1:]) < 1
        ):
            raise ValueError(f"invalid flow-owned paragraph ref: {reference!r}")
    return held


def build_inventory(
    docs,
    *,
    article_document_ir=None,
    run_trace=None,
    protected_paragraph_labels=(),
    flow_owned_paragraph_refs=(),
) -> FixedAssetInventory:
    """Freeze every fixed asset under stable page/source references."""
    article_refs, unsupported_pages = _article_refs(article_document_ir, run_trace)
    flow_owned_refs = _flow_owned_refs(flow_owned_paragraph_refs)
    if article_document_ir is not None:
        article_refs.update(flow_owned_refs)
    protected_labels = frozenset(protected_paragraph_labels)
    assets: list[AssetRecord] = []
    page_sizes = []
    for position, page in enumerate(docs.page or ()):
        page_number = position + 1
        page_sizes.append(
            (
                page_number,
                _page_box(getattr(page, "mediabox", None)),
                _page_box(getattr(page, "cropbox", None)),
            )
        )
        for collection in PAGE_ASSET_COLLECTIONS:
            for index, item in enumerate(getattr(page, collection, None) or ()):
                reference = f"p{page_number}:{collection}#{index}"
                assets.append(
                    _record(
                        reference,
                        collection,
                        page_number,
                        item,
                        figure_ref=reference if collection == "pdf_figure" else None,
                        asset_class=(
                            ORNAMENT_ASSET_CLASS
                            if collection == "pdf_curve"
                            and is_ornament_curve(item, load_ornament_thresholds())
                            else None
                        ),
                    )
                )
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph or ()):
            source_ref = paragraph_reference(page_number, paragraph_index)
            fixed_paragraph = (
                bool(getattr(paragraph, "vertical", False))
                or getattr(paragraph, "layout_label", None) in protected_labels
                or page_number in unsupported_pages
                or (article_refs is not None and source_ref not in article_refs)
            )
            display_glyph = (
                getattr(paragraph, "layout_label", None) == DISPLAY_GLYPH_LABEL
            )
            if fixed_paragraph or display_glyph:
                asset_type = (
                    ROTATED_PARAGRAPH_TYPE
                    if bool(getattr(paragraph, "vertical", False))
                    else FURNITURE_TYPE
                )
                assets.append(
                    _record(
                        source_ref,
                        asset_type,
                        page_number,
                        paragraph,
                        asset_class=(
                            DISPLAY_GLYPH_ASSET_CLASS if display_glyph else None
                        ),
                    )
                )
            for composition_index, composition in enumerate(
                paragraph.pdf_paragraph_composition or ()
            ):
                formula = getattr(composition, FORMULA_TYPE, None)
                if formula is None:
                    continue
                formula_ref = f"{source_ref}:{FORMULA_TYPE}#{composition_index}"
                assets.append(
                    _record(
                        formula_ref,
                        FORMULA_TYPE,
                        page_number,
                        formula,
                        formula_ref=formula_ref,
                    )
                )
                for collection in FORMULA_CHILD_COLLECTIONS:
                    for child_index, child in enumerate(
                        getattr(formula, collection, None) or ()
                    ):
                        assets.append(
                            _record(
                                f"{formula_ref}:{collection}#{child_index}",
                                collection,
                                page_number,
                                child,
                                formula_ref=formula_ref,
                            )
                        )
    return FixedAssetInventory(
        assets=tuple(sorted(assets, key=lambda asset: asset.reference)),
        page_sizes=tuple(page_sizes),
    )


def _bbox_equal(left, right, tolerance: float) -> bool:
    if left is None or right is None:
        return left is right
    return all(abs(a - b) <= tolerance for a, b in zip(left, right, strict=True))


def compare(
    before: FixedAssetInventory,
    after: FixedAssetInventory,
    bbox_tolerance_pt: float,
) -> InventoryComparison:
    left = before.by_ref
    right = after.by_ref
    added = tuple(sorted(set(right) - set(left)))
    removed = tuple(sorted(set(left) - set(right)))
    common = sorted(set(left).intersection(right))
    bbox_changed = tuple(
        reference
        for reference in common
        if not _bbox_equal(
            left[reference].bbox, right[reference].bbox, bbox_tolerance_pt
        )
    )
    digest_changed = tuple(
        reference
        for reference in common
        if left[reference].digest != right[reference].digest
    )
    before_sizes = {page: (media, crop) for page, media, crop in before.page_sizes}
    after_sizes = {page: (media, crop) for page, media, crop in after.page_sizes}
    page_size_changed = tuple(
        page
        for page in sorted(set(before_sizes).union(after_sizes))
        if before_sizes.get(page) != after_sizes.get(page)
    )
    holds = not (
        added or removed or bbox_changed or digest_changed or page_size_changed
    )
    return InventoryComparison(
        holds=holds,
        count_before=len(before.assets),
        count_after=len(after.assets),
        added=added,
        removed=removed,
        bbox_changed=bbox_changed,
        digest_changed=digest_changed,
        page_size_changed=page_size_changed,
    )


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
