"""Flow-created blank regions normalized by canonical article capacity."""

from __future__ import annotations

from babeldoc.magazine.detectors import base

NAME = "abnormal_blank"
KIND = "abnormal_blank"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False
REQUIRES_ARTICLE_IR = True
REQUIRES_RUN_TRACE = True
REQUIRES_FIXED_INVENTORY = True
FINAL_ONLY = True

FLOW_BLANK_REASONS = (
    "unused_cross_page_capacity",
    "unused_page_local_capacity",
)


def _area(box) -> float:
    if box is None:
        return 0.0
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(left, right):
    box = (
        max(left[0], right[0]),
        max(left[1], right[1]),
        min(left[2], right[2]),
        min(left[3], right[3]),
    )
    return None if _area(box) <= 0 else box


def _union_area(boxes) -> float:
    present = [box for box in boxes if box is not None and _area(box) > 0]
    if not present:
        return 0.0
    xs = sorted({coordinate for box in present for coordinate in (box[0], box[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:], strict=False):
        intervals = sorted(
            (box[1], box[3])
            for box in present
            if box[0] < right and box[2] > left
        )
        if not intervals:
            continue
        covered = 0.0
        start, end = intervals[0]
        for next_start, next_end in intervals[1:]:
            if next_start > end:
                covered += end - start
                start, end = next_start, next_end
            else:
                end = max(end, next_end)
        covered += end - start
        area += (right - left) * covered
    return area


def _hard_boundary(article, page: int, unsupported: set[int]) -> bool:
    if page in unsupported:
        return True
    evidence = [item for item in article.policy_evidence if item.page == page]
    return bool(evidence) and not all(item.article_reflow_allowed for item in evidence)


def detect(context: base.DetectionContext) -> list[base.Issue]:
    article_ir = context.article_document_ir
    trace = context.run_trace
    unsupported = {item.page for item in article_ir.unsupported_pages}
    found = []
    for flow_slot_id, flow_slot in sorted(trace.flow_slots.items()):
        if (
            not flow_slot.active
            or flow_slot.status != "released"
            or flow_slot.reason not in FLOW_BLANK_REASONS
            or flow_slot.box is None
        ):
            continue
        article = article_ir.article(flow_slot.article_id)
        if article is None or _hard_boundary(article, flow_slot.page, unsupported):
            continue
        article_slots = [
            slot for slot in article.slots if slot.page == flow_slot.page
        ]
        total_area = sum(_area(slot.box) for slot in article_slots)
        total_capacity = sum(max(0.0, slot.capacity_hint) for slot in article_slots)
        if total_area <= 0 or total_capacity <= 0:
            found.append(
                base.Issue(
                    kind="detector_prerequisite_missing",
                    page=flow_slot.page,
                    paragraph_refs=(),
                    geometry=base.union_box([flow_slot.box]),
                    severity=context.severity_of("detector_prerequisite_missing"),
                    evidence={
                        "prerequisite": "article_slot_capacity",
                        "required_by": NAME,
                        "flow_slot_id": flow_slot_id,
                        "violation_count": 1,
                        "identity_ref": flow_slot_id,
                    },
                    detector=NAME,
                    detected_at_iteration=context.iteration,
                    article_refs=(article.article_id,),
                )
            )
            continue
        fixed_boxes = [
            _intersection(flow_slot.box, asset.bbox)
            for asset in context.fixed_inventory.page_assets(flow_slot.page)
            if asset.bbox is not None
        ]
        blank_area = max(0.0, _area(flow_slot.box) - _union_area(fixed_boxes))
        blank_capacity = 0.0
        for slot in article_slots:
            shared = _intersection(flow_slot.box, slot.box)
            slot_area = _area(slot.box)
            if shared is not None and slot_area > 0:
                blank_capacity += slot.capacity_hint * _area(shared) / slot_area
        fixed_share = 0.0 if _area(flow_slot.box) <= 0 else _union_area(fixed_boxes) / _area(flow_slot.box)
        blank_capacity *= max(0.0, 1.0 - fixed_share)
        area_ratio = blank_area / total_area
        capacity_ratio = blank_capacity / total_capacity
        if (
            area_ratio < context.config.abnormal_blank_min_area_ratio
            or capacity_ratio < context.config.abnormal_blank_min_capacity_ratio
        ):
            continue
        source_refs = () if flow_slot.source_ref is None else (flow_slot.source_ref,)
        found.append(
            base.Issue(
                kind=KIND,
                page=flow_slot.page,
                paragraph_refs=source_refs,
                geometry=base.union_box([flow_slot.box]),
                severity=context.severity_of(KIND),
                evidence={
                    "flow_slot_id": flow_slot_id,
                    "flow_reason": flow_slot.reason,
                    "blank_area": round(blank_area, 4),
                    "article_slot_area": round(total_area, 4),
                    "blank_area_ratio": round(area_ratio, 6),
                    "blank_capacity": round(blank_capacity, 4),
                    "article_slot_capacity": round(total_capacity, 4),
                    "blank_capacity_ratio": round(capacity_ratio, 6),
                    "fixed_asset_area": round(_union_area(fixed_boxes), 4),
                    "violation_count": 1,
                    "identity_ref": flow_slot_id,
                },
                detector=NAME,
                detected_at_iteration=context.iteration,
                article_refs=(article.article_id,),
                source_refs=source_refs,
            )
        )
    return found
