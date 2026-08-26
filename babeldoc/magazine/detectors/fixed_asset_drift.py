"""Count, bounding-box, digest, and page-size drift of fixed assets."""

from __future__ import annotations

from babeldoc.magazine import fixed_assets
from babeldoc.magazine.detectors import base

NAME = "fixed_asset_drift"
KIND = "fixed_asset_drift"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False
REQUIRES_FIXED_INVENTORY = True
REQUIRES_CURRENT_INVENTORY = True
FINAL_ONLY = True


def _asset_issue(context, comparison, reference, reason):
    before = context.fixed_inventory.by_ref.get(reference)
    after = context.current_inventory.by_ref.get(reference)
    page = before.page if before is not None else after.page if after is not None else 0
    boxes = [
        None if before is None else before.bbox,
        None if after is None else after.bbox,
    ]
    return base.Issue(
        kind=KIND,
        page=page,
        paragraph_refs=(),
        geometry=base.union_box(boxes),
        severity=context.severity_of(KIND),
        evidence={
            "asset_ref": reference,
            "reason": reason,
            "asset_type": (
                before.asset_type if before is not None else after.asset_type
            ),
            "bbox_before": None if before is None else before.bbox,
            "bbox_after": None if after is None else after.bbox,
            "digest_before": None if before is None else before.digest,
            "digest_after": None if after is None else after.digest,
            "count_before": comparison.count_before,
            "count_after": comparison.count_after,
            "drift_count": 1,
            "identity_ref": reason,
        },
        detector=NAME,
        detected_at_iteration=context.iteration,
    )


def detect(context: base.DetectionContext) -> list[base.Issue]:
    comparison = fixed_assets.compare(
        context.fixed_inventory,
        context.current_inventory,
        context.config.fixed_asset_bbox_tolerance_pt,
    )
    found = []
    for reason, references in (
        ("added", comparison.added),
        ("removed", comparison.removed),
        ("bbox_changed", comparison.bbox_changed),
        ("digest_changed", comparison.digest_changed),
    ):
        found.extend(
            _asset_issue(context, comparison, reference, reason)
            for reference in references
        )
    for page in comparison.page_size_changed:
        found.append(
            base.Issue(
                kind=KIND,
                page=page,
                paragraph_refs=(),
                geometry=None,
                severity=context.severity_of(KIND),
                evidence={
                    "asset_ref": f"p{page}:page_size",
                    "reason": "page_size_changed",
                    "count_before": comparison.count_before,
                    "count_after": comparison.count_after,
                    "drift_count": 1,
                    "identity_ref": "page_size_changed",
                },
                detector=NAME,
                detected_at_iteration=context.iteration,
            )
        )
    return found
