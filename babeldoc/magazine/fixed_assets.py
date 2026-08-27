"""Stable inventory and conservation checks for fixed visual page assets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import is_dataclass
from enum import Enum
from pathlib import Path

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
FORMULA_TYPE = "pdf_formula"
FURNITURE_TYPE = "pdf_paragraph_furniture"


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
            if asset.asset_type == FURNITURE_TYPE and asset.protected
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


def build_inventory(
    docs,
    *,
    article_document_ir=None,
    run_trace=None,
    protected_paragraph_labels=(),
) -> FixedAssetInventory:
    """Freeze every fixed asset under stable page/source references."""
    article_refs, unsupported_pages = _article_refs(article_document_ir, run_trace)
    protected_labels = frozenset(protected_paragraph_labels)
    assets: list[AssetRecord] = []
    page_sizes = []
    from babeldoc.magazine.page_identity import physical_page_number

    for page in docs.page or ():
        page_number = int(physical_page_number(page))
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
                    )
                )
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph or ()):
            source_ref = paragraph_reference(page_number, paragraph_index)
            fixed_paragraph = (
                getattr(paragraph, "layout_label", None) in protected_labels
                or page_number in unsupported_pages
                or (article_refs is not None and source_ref not in article_refs)
            )
            if fixed_paragraph:
                assets.append(
                    _record(source_ref, FURNITURE_TYPE, page_number, paragraph)
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
