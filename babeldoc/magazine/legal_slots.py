"""Canonical obstacle-free regions shared by chain and article flow.

ArticleIR owns article envelopes.  This module is the only place that turns
those envelopes into writable rectangles: every fixed visual asset, protected
role, and foreign article region is subtracted before a consumer sees a slot.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from babeldoc.magazine.element_roles import PROTECTED_ROLES

LEGAL_SLOT_SCHEMA_VERSION = "legal-slots.v1"
DEFAULT_MINIMUM_FRAGMENT_WIDTH_PT = 1.0
DEFAULT_MINIMUM_FRAGMENT_HEIGHT_PT = 1.0
DEFAULT_MINIMUM_FRAGMENT_AREA_PT2 = 1.0

BoxTuple = tuple[float, float, float, float]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_record(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class SlotObstacle:
    reference: str
    page: int
    box: BoxTuple
    reason: str

    def to_record(self) -> dict:
        return {
            "reference": self.reference,
            "page": self.page,
            "box": list(self.box),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LegalSlot:
    slot_id: str
    article_id: str
    page: int
    column: int
    slot_order: int
    source_slot_order: int
    box: BoxTuple
    obstacle_refs: tuple[str, ...]

    @property
    def fixed_obstacle_refs(self) -> tuple[str, ...]:
        """Compatibility name used by the pre-C18 allocation record."""
        return self.obstacle_refs

    @property
    def capacity_hint(self) -> float:
        return (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])

    def to_record(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "article_id": self.article_id,
            "page": self.page,
            "column": self.column,
            "slot_order": self.slot_order,
            "source_slot_order": self.source_slot_order,
            "box": list(self.box),
            "obstacle_refs": list(self.obstacle_refs),
        }


@dataclass(frozen=True, slots=True)
class LegalSlotPlan:
    slots: tuple[LegalSlot, ...]
    obstacle_refs: tuple[str, ...]
    unsupported_pages: tuple[int, ...]
    digest: str
    schema_version: str = LEGAL_SLOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LEGAL_SLOT_SCHEMA_VERSION:
            raise ValueError("unsupported legal-slot schema")
        expected = tuple(range(len(self.slots)))
        if tuple(slot.slot_order for slot in self.slots) != expected:
            raise ValueError("legal slots must have contiguous canonical order")
        if any(slot.page in self.unsupported_pages for slot in self.slots):
            raise ValueError("unsupported pages cannot expose legal slots")
        if self.digest != digest_record(self.digest_material()):
            raise ValueError("legal-slot digest does not match its canonical plan")

    def digest_material(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "slots": [slot.to_record() for slot in self.slots],
            "obstacle_refs": list(self.obstacle_refs),
            "unsupported_pages": list(self.unsupported_pages),
        }

    def to_record(self) -> dict:
        return {**self.digest_material(), "digest": self.digest}

    def article_slots(self, article_id: str) -> tuple[LegalSlot, ...]:
        return tuple(slot for slot in self.slots if slot.article_id == article_id)

    def region_slots(
        self, article_id: str, page: int, column: int
    ) -> tuple[LegalSlot, ...]:
        return tuple(
            slot
            for slot in self.slots
            if slot.article_id == article_id
            and slot.page == page
            and slot.column == column
        )


def _valid_box(box) -> BoxTuple | None:
    if box is None or len(box) != 4:
        return None
    result = tuple(float(value) for value in box)
    if result[2] <= result[0] or result[3] <= result[1]:
        return None
    return result


def _intersects(left: BoxTuple, right: BoxTuple) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def _large_enough(
    box: BoxTuple,
    *,
    minimum_width: float,
    minimum_height: float,
    minimum_area: float,
) -> bool:
    width = box[2] - box[0]
    height = box[3] - box[1]
    return (
        width >= minimum_width
        and height >= minimum_height
        and width * height >= minimum_area
    )


def subtract_rectangle(
    region: BoxTuple, obstacle: BoxTuple
) -> tuple[BoxTuple, ...]:
    """Return non-overlapping fragments of ``region - obstacle``."""
    if not _intersects(region, obstacle):
        return (region,)
    x1, y1, x2, y2 = region
    ox1 = max(x1, obstacle[0])
    oy1 = max(y1, obstacle[1])
    ox2 = min(x2, obstacle[2])
    oy2 = min(y2, obstacle[3])
    candidates = (
        (x1, oy2, x2, y2),
        (x1, y1, x2, oy1),
        (x1, oy1, ox1, oy2),
        (ox2, oy1, x2, oy2),
    )
    return tuple(
        candidate
        for candidate in candidates
        if candidate[2] > candidate[0] and candidate[3] > candidate[1]
    )


def fragment_envelope(
    envelope: BoxTuple,
    obstacles: Iterable[SlotObstacle],
    *,
    minimum_width: float = DEFAULT_MINIMUM_FRAGMENT_WIDTH_PT,
    minimum_height: float = DEFAULT_MINIMUM_FRAGMENT_HEIGHT_PT,
    minimum_area: float = DEFAULT_MINIMUM_FRAGMENT_AREA_PT2,
) -> tuple[tuple[BoxTuple, tuple[str, ...]], ...]:
    """Subtract every obstacle with true two-dimensional fragmentation."""
    regions: list[tuple[BoxTuple, frozenset[str]]] = [(envelope, frozenset())]
    ordered = sorted(
        obstacles,
        key=lambda item: (item.box[1], item.box[0], item.box[3], item.box[2], item.reference),
    )
    for obstacle in ordered:
        next_regions = []
        for region, refs in regions:
            if not _intersects(region, obstacle.box):
                next_regions.append((region, refs))
                continue
            for fragment in subtract_rectangle(region, obstacle.box):
                if _large_enough(
                    fragment,
                    minimum_width=minimum_width,
                    minimum_height=minimum_height,
                    minimum_area=minimum_area,
                ):
                    next_regions.append((fragment, refs | {obstacle.reference}))
        regions = next_regions
    return tuple(
        (box, tuple(sorted(refs)))
        for box, refs in sorted(
            regions,
            key=lambda item: (-item[0][3], item[0][0], -item[0][1], item[0][2]),
        )
    )


def _inventory_obstacles(inventory) -> tuple[SlotObstacle, ...]:
    if inventory is None:
        return ()
    return tuple(
        SlotObstacle(asset.reference, int(asset.page), box, "fixed_visual_asset")
        for asset in inventory.assets
        if asset.protected and (box := _valid_box(asset.bbox)) is not None
    )


def plan_legal_slots(
    article_document_ir,
    fixed_inventory=None,
    *,
    extra_obstacles: Iterable[SlotObstacle] = (),
    minimum_width: float = DEFAULT_MINIMUM_FRAGMENT_WIDTH_PT,
    minimum_height: float = DEFAULT_MINIMUM_FRAGMENT_HEIGHT_PT,
    minimum_area: float = DEFAULT_MINIMUM_FRAGMENT_AREA_PT2,
) -> LegalSlotPlan:
    """Build one deterministic obstacle-free plan for every supported article."""
    unsupported = tuple(
        sorted(item.page for item in article_document_ir.unsupported_pages)
    )
    obstacles = list(_inventory_obstacles(fixed_inventory))
    for article in article_document_ir.articles:
        for element in article.elements:
            box = _valid_box(element.source_box)
            if box is not None and element.role in PROTECTED_ROLES:
                obstacles.append(
                    SlotObstacle(element.source_ref, element.page, box, "protected_role")
                )
    obstacles.extend(extra_obstacles)

    draft: list[tuple[object, BoxTuple, tuple[str, ...]]] = []
    for article in article_document_ir.articles:
        for source_slot in article.slots:
            if source_slot.page in unsupported:
                continue
            region_obstacles = [
                item for item in obstacles if item.page == source_slot.page
            ]
            # A supported page currently has exactly one owner, but retain the
            # foreign-region rule so the planner remains fail-closed if that
            # invariant is ever relaxed.
            for other in article_document_ir.articles:
                if other.article_id == article.article_id:
                    continue
                for other_slot in other.slots:
                    if other_slot.page != source_slot.page:
                        continue
                    box = _valid_box(other_slot.box)
                    if box is not None:
                        region_obstacles.append(
                            SlotObstacle(
                                f"article-region:{other.article_id}:"
                                f"{other_slot.slot_order}",
                                other_slot.page,
                                box,
                                "other_article_region",
                            )
                        )
            for box, refs in fragment_envelope(
                source_slot.box,
                region_obstacles,
                minimum_width=minimum_width,
                minimum_height=minimum_height,
                minimum_area=minimum_area,
            ):
                draft.append((source_slot, box, refs))

    draft.sort(
        key=lambda item: (
            item[0].slot_order,
            -item[1][3],
            item[1][0],
            -item[1][1],
            item[1][2],
        )
    )
    slots = []
    for order, (source_slot, box, refs) in enumerate(draft):
        material = {
            "schema_version": LEGAL_SLOT_SCHEMA_VERSION,
            "article_id": source_slot.article_id,
            "page": source_slot.page,
            "column": source_slot.column,
            "source_slot_order": source_slot.slot_order,
            "box": list(box),
            "obstacle_refs": list(refs),
        }
        slots.append(
            LegalSlot(
                slot_id=f"legal-slot-{digest_record(material)}",
                article_id=source_slot.article_id,
                page=source_slot.page,
                column=source_slot.column,
                slot_order=order,
                source_slot_order=source_slot.slot_order,
                box=box,
                obstacle_refs=refs,
            )
        )
    obstacle_refs = tuple(sorted({item.reference for item in obstacles}))
    material = {
        "schema_version": LEGAL_SLOT_SCHEMA_VERSION,
        "slots": [slot.to_record() for slot in slots],
        "obstacle_refs": list(obstacle_refs),
        "unsupported_pages": list(unsupported),
    }
    return LegalSlotPlan(
        slots=tuple(slots),
        obstacle_refs=obstacle_refs,
        unsupported_pages=unsupported,
        digest=digest_record(material),
    )


def slot_for_source_box(
    plan: LegalSlotPlan,
    *,
    article_id: str,
    page: int,
    column: int,
    source_box: BoxTuple | None,
) -> LegalSlot | None:
    """Select the fragment containing the source element centre, deterministically."""
    candidates = plan.region_slots(article_id, page, column)
    if not candidates:
        return None
    box = _valid_box(source_box)
    if box is None:
        return candidates[0]
    centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    containing = [
        slot
        for slot in candidates
        if slot.box[0] <= centre[0] <= slot.box[2]
        and slot.box[1] <= centre[1] <= slot.box[3]
    ]
    return (containing or list(candidates))[0]
