"""Bounded post-typesetting detection for the minimal magazine pipeline."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from babeldoc.magazine import fixed_assets
from babeldoc.magazine.detectors import collision
from babeldoc.magazine.detectors import detector_config
from babeldoc.magazine.detectors import fixed_asset_drift
from babeldoc.magazine.detectors import fragment
from babeldoc.magazine.detectors import page_bounds
from babeldoc.magazine.detectors import residue
from babeldoc.magazine.detectors.base import DetectionContext
from babeldoc.magazine.detectors.base import DetectorConfig
from babeldoc.magazine.detectors.base import Issue
from babeldoc.magazine.detectors.base import PageView
from babeldoc.magazine.detectors.base import union_box

SCHEMA_VERSION = "minimal-detection.v1"
CHAIN_REPORT_NAME = "chain_translation.report.json"
SOURCE_GEOMETRY_STAGE = "styles_and_formulas"
SOURCE_GEOMETRY_PATH = "memory:styles_and_formulas"
SIDECAR_NAMES = frozenset({"issues.before.json", "issues.after.json"})

ISSUE_KINDS = (
    "untranslated_residue",
    "out_of_page",
    "text_text_collision",
    "fragment_cluster",
    "chain_conservation",
    "fixed_asset_drift",
)

_PAGE_DETECTORS = (
    residue,
    page_bounds,
    collision,
    fragment,
)
_SOURCE_REF = re.compile(r"p([1-9][0-9]*)#(0|[1-9][0-9]*)\Z")


class MinimalDetectionError(ValueError):
    """Raised when fixed detection evidence is internally inconsistent."""


def _source_ref(reference: object) -> tuple[int, int]:
    match = _SOURCE_REF.fullmatch(reference) if isinstance(reference, str) else None
    if match is None:
        raise MinimalDetectionError(f"invalid paragraph reference: {reference!r}")
    return int(match.group(1)), int(match.group(2))


def _finite_box(value: object, where: str) -> tuple[float, float, float, float]:
    if not isinstance(value, tuple | list) or len(value) != 4:
        raise MinimalDetectionError(f"{where} must be a four-coordinate box")
    box = tuple(float(coordinate) for coordinate in value)
    if not all(math.isfinite(coordinate) for coordinate in box):
        raise MinimalDetectionError(f"{where} contains a non-finite coordinate")
    if box[0] > box[2] or box[1] > box[3]:
        raise MinimalDetectionError(f"{where} coordinates are not ordered")
    return box


@dataclass(frozen=True, slots=True)
class SourceGeometrySnapshot:
    """Canonical source boxes keyed by physical paragraph reference."""

    stage: str
    path: str
    boxes: Mapping[str, tuple[float, float, float, float]]
    local_refs: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.stage != SOURCE_GEOMETRY_STAGE or self.path != SOURCE_GEOMETRY_PATH:
            raise MinimalDetectionError("source geometry must use the fixed memory stage")
        boxes = dict(self.boxes)
        local_refs = dict(self.local_refs)
        if len(local_refs) != len(set(local_refs.values())):
            raise MinimalDetectionError("source geometry local refs must be unique")
        for physical_ref, local_ref in local_refs.items():
            _source_ref(physical_ref)
            _source_ref(local_ref)
        if not set(boxes).issubset(local_refs):
            raise MinimalDetectionError("source geometry boxes require mapped refs")
        boxes = {
            reference: _finite_box(box, f"source geometry box {reference}")
            for reference, box in boxes.items()
        }
        object.__setattr__(self, "boxes", MappingProxyType(boxes))
        object.__setattr__(
            self,
            "local_refs",
            MappingProxyType(local_refs),
        )

    def box_for(self, physical_ref: str):
        return self.boxes.get(physical_ref)

    def local_ref(self, physical_ref: str) -> str | None:
        return self.local_refs.get(physical_ref)

    def to_record(self) -> dict:
        return {
            "stage": self.stage,
            "path": self.path,
            "paragraphs": len(self.local_refs),
            "boxes": len(self.boxes),
        }


@dataclass(frozen=True, slots=True)
class DetectionBaseline:
    """Source evidence plus the fixed inventory for the current layout stage."""

    document_identity: int
    article_document_identity: int
    physical_labels: tuple[int, ...]
    physical_to_local: Mapping[int, int]
    source_geometry: SourceGeometrySnapshot
    fixed_inventory: fixed_assets.FixedAssetInventory

    def __post_init__(self) -> None:
        labels = self.physical_labels
        if (
            not labels
            or any(
                not isinstance(label, int)
                or isinstance(label, bool)
                or label < 1
                for label in labels
            )
            or len(labels) != len(set(labels))
        ):
            raise MinimalDetectionError("physical page labels must be non-empty and unique")
        physical_to_local = dict(self.physical_to_local)
        expected_mapping = {
            label: position for position, label in enumerate(labels, start=1)
        }
        if (
            physical_to_local != expected_mapping
            or any(
                not isinstance(local, int)
                or isinstance(local, bool)
                for local in physical_to_local.values()
            )
        ):
            raise MinimalDetectionError(
                "physical-to-local pages must be a complete selected-page bijection"
            )
        for physical_ref, local_ref in self.source_geometry.local_refs.items():
            physical_page, _physical_index = _source_ref(physical_ref)
            local_page, _local_index = _source_ref(local_ref)
            if physical_to_local.get(physical_page) != local_page:
                raise MinimalDetectionError(
                    "source geometry physical/local page mapping is inconsistent"
                )
        object.__setattr__(
            self,
            "physical_to_local",
            MappingProxyType(physical_to_local),
        )

    @property
    def local_to_physical(self) -> dict[int, int]:
        return {local: physical for physical, local in self.physical_to_local.items()}

    def physical_ref(self, local_ref: str) -> str:
        page, index = _source_ref(local_ref)
        physical = self.local_to_physical.get(page)
        if physical is None:
            raise MinimalDetectionError(
                f"local paragraph reference is outside selected pages: {local_ref}"
            )
        return f"p{physical}#{index}"


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """One completed detector pass and its written sidecar."""

    issues: tuple[Issue, ...]
    record: dict
    report_path: Path


def mirror_after(
    before: DetectionResult,
    working_dir: str | Path,
    *,
    restored_from_before: bool,
    reason: str,
) -> DetectionResult:
    """Write the final after-sidecar without claiming another detection pass."""
    if not isinstance(before, DetectionResult):
        raise MinimalDetectionError("mirrored detection requires a DetectionResult")
    if not isinstance(restored_from_before, bool):
        raise MinimalDetectionError("restored_from_before must be boolean")
    if not isinstance(reason, str) or not reason:
        raise MinimalDetectionError("mirrored detection requires a typed reason")
    record = deepcopy(before.record)
    record["mirrored_after"] = {
        "restored_from_before": restored_from_before,
        "reason": reason,
        "detection_passes_added": 0,
    }
    record["restored_from_before"] = restored_from_before
    report_path = _write_sidecar(Path(working_dir), "issues.after.json", record)
    return DetectionResult(before.issues, record, report_path)


def _validated_labels(docs, labeled_pages) -> tuple[int, ...]:
    rows = tuple(labeled_pages)
    if len(rows) != len(docs.page or ()):
        raise MinimalDetectionError("labeled pages must cover the selected document")
    labels = []
    for position, row in enumerate(rows):
        if not isinstance(row, tuple | list) or len(row) != 2:
            raise MinimalDetectionError("each labeled page must be a label/page pair")
        label, page = row
        if (
            not isinstance(label, int)
            or isinstance(label, bool)
            or label < 1
            or page is not docs.page[position]
        ):
            raise MinimalDetectionError("labeled pages do not match document order")
        labels.append(label)
    if len(labels) != len(set(labels)):
        raise MinimalDetectionError("selected pages have duplicate physical labels")
    return tuple(labels)


def _article_elements(article_document_ir) -> dict[str, object]:
    elements = {
        element.source_ref: element
        for article in article_document_ir.articles
        for element in article.elements
    }
    if set(elements) != set(article_document_ir.by_element):
        raise MinimalDetectionError("canonical ArticleDocumentIR indexes disagree")
    return elements


def capture_baseline(
    docs,
    article_document_ir,
    *,
    labeled_pages,
) -> DetectionBaseline:
    """Freeze source boxes and fixed assets before target layout can mutate them.

    ``labeled_pages`` must be the exact result of ``hitl.labeled_pages(docs)``.
    It is supplied by the already-wired pipeline so this module does not import
    the HITL/taxonomy closure merely to read page numbers.
    """
    labels = _validated_labels(docs, labeled_pages)
    elements = _article_elements(article_document_ir)
    boxes = {}
    local_refs = {}
    for local_ref, element in sorted(elements.items()):
        page, index = _source_ref(local_ref)
        if page > len(labels) or index >= len(docs.page[page - 1].pdf_paragraph or ()):
            raise MinimalDetectionError(
                f"canonical source reference is not present in docs: {local_ref}"
            )
        physical_ref = f"p{labels[page - 1]}#{index}"
        local_refs[physical_ref] = local_ref
        if element.source_box is not None:
            boxes[physical_ref] = _finite_box(
                element.source_box,
                f"canonical source box {local_ref}",
            )
    geometry = SourceGeometrySnapshot(
        stage=SOURCE_GEOMETRY_STAGE,
        path=SOURCE_GEOMETRY_PATH,
        boxes=boxes,
        local_refs=local_refs,
    )
    return DetectionBaseline(
        document_identity=id(docs),
        article_document_identity=id(article_document_ir),
        physical_labels=labels,
        physical_to_local={label: position + 1 for position, label in enumerate(labels)},
        source_geometry=geometry,
        fixed_inventory=fixed_assets.build_inventory(
            docs,
            article_document_ir=article_document_ir,
        ),
    )


def refresh_fixed_inventory(
    baseline: DetectionBaseline,
    docs,
    article_document_ir,
    *,
    flow_report: dict | None,
) -> DetectionBaseline:
    """Refresh only fixed assets after formal typesetting, preserving source evidence."""
    if not isinstance(baseline, DetectionBaseline):
        raise MinimalDetectionError("fixed refresh requires a DetectionBaseline")
    if baseline.document_identity != id(docs):
        raise MinimalDetectionError("fixed refresh baseline belongs to another document")
    if baseline.article_document_identity != id(article_document_ir):
        raise MinimalDetectionError("fixed refresh baseline belongs to another ArticleIR")
    if len(docs.page or ()) != len(baseline.physical_labels):
        raise MinimalDetectionError("fixed refresh document page count changed")
    _article_elements(article_document_ir)
    flow_owned_refs = _committed_flow_refs(flow_report, article_document_ir)
    return replace(
        baseline,
        fixed_inventory=fixed_assets.build_inventory(
            docs,
            article_document_ir=article_document_ir,
            flow_owned_paragraph_refs=flow_owned_refs,
        ),
    )


def _committed_flow_refs(flow_report, article_document_ir) -> frozenset[str]:
    if flow_report is None:
        return frozenset()
    if not isinstance(flow_report, dict):
        raise MinimalDetectionError("article flow report must be an object")
    segments = flow_report.get("cross_page_segments", ())
    if not isinstance(segments, list):
        raise MinimalDetectionError("article flow report segments must be a list")
    committed = set()
    for position, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise MinimalDetectionError(f"flow segment {position} must be an object")
        status = segment.get("status")
        action_status = segment.get("action_status")
        if status == "applied" and action_status != "committed":
            raise MinimalDetectionError("an applied flow segment is not committed")
        if status != "applied":
            continue
        references = segment.get("committed_flow_owned_refs", ())
        if not isinstance(references, list):
            raise MinimalDetectionError("committed flow-owned refs must be a list")
        for reference in references:
            _source_ref(reference)
            if reference in article_document_ir.by_element:
                raise MinimalDetectionError(
                    "flow-owned refs may name only additional render holders"
                )
            committed.add(reference)
    return frozenset(committed)


def committed_flow_refs(flow_report, article_document_ir) -> frozenset[str]:
    """Return only render-holder refs committed by successful article flow."""
    return _committed_flow_refs(flow_report, article_document_ir)


def _repair_owned_binding(
    value,
    *,
    baseline: DetectionBaseline,
    docs,
    article_document_ir,
    committed_flow_refs,
) -> tuple[str, str] | None:
    if value is None:
        return None
    if (
        not isinstance(value, tuple | list)
        or len(value) != 2
        or not all(isinstance(item, str) for item in value)
    ):
        raise MinimalDetectionError(
            "repair-owned binding must be one physical/local ref pair"
        )
    physical_ref, local_ref = value
    physical_page, physical_index = _source_ref(physical_ref)
    local_page, local_index = _source_ref(local_ref)
    if (
        baseline.physical_to_local.get(physical_page) != local_page
        or physical_index != local_index
    ):
        raise MinimalDetectionError("repair-owned physical/local refs disagree")
    paragraphs = docs.page[local_page - 1].pdf_paragraph or ()
    if local_index >= len(paragraphs):
        raise MinimalDetectionError("repair-owned paragraph is not present in docs")
    if local_ref in article_document_ir.by_element:
        raise MinimalDetectionError("repair-owned exclusion is only for an orphan")
    if local_ref in committed_flow_refs:
        raise MinimalDetectionError("repair-owned exclusion overlaps article flow")
    records = [
        asset
        for asset in baseline.fixed_inventory.assets
        if asset.reference == local_ref
    ]
    if len(records) != 1 or records[0].asset_type != fixed_assets.FURNITURE_TYPE:
        raise MinimalDetectionError(
            "repair-owned exclusion must name one frozen furniture paragraph"
        )
    return physical_ref, local_ref


def _without_fixed_ref(inventory, reference: str | None):
    if reference is None:
        return inventory
    return fixed_assets.FixedAssetInventory(
        assets=tuple(
            asset for asset in inventory.assets if asset.reference != reference
        ),
        page_sizes=inventory.page_sizes,
    )


def _chain_geometry(
    baseline: DetectionBaseline,
    local_refs,
) -> tuple[float, float, float, float] | None:
    """Return frozen source geometry without consulting mutable render holders."""
    boxes = []
    for local_ref in local_refs:
        physical_ref = baseline.physical_ref(local_ref)
        box = baseline.source_geometry.box_for(physical_ref)
        if box is not None:
            boxes.append(box)
    return union_box(boxes)


def _required_mapping(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise MinimalDetectionError(f"{where} must be an object")
    return value


def _required_list(value, where: str) -> list:
    if not isinstance(value, list):
        raise MinimalDetectionError(f"{where} must be a list")
    return value


def _required_text(value, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise MinimalDetectionError(f"{where} must be text")
    return value


def _nonnegative_integer(value, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MinimalDetectionError(f"{where} must be a non-negative integer")
    return value


def _optional_integer(value, where: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_integer(value, where)


_CHAIN_STATES = frozenset(
    {"joint_success", "protected_untranslated", "failed_with_issue"}
)
_CHAIN_SKIP_MECHANISMS = frozenset({"cross_page", "cross_column", "page_batch"})


def _chain_refs(value, where: str, article_document_ir) -> tuple[str, ...]:
    refs = _required_list(value, where)
    if not refs:
        raise MinimalDetectionError(f"{where} must not be empty")
    for reference in refs:
        _source_ref(reference)
        if reference not in article_document_ir.by_element:
            raise MinimalDetectionError(
                f"{where} ref is outside canonical IR: {reference}"
            )
    return tuple(refs)


def _allocation_violations(chain_id: str, chain: dict, local_refs) -> list[str]:
    translation = _required_text(
        chain.get("translation"),
        f"chain {chain_id}.translation",
        allow_empty=True,
    )
    allocation = _required_mapping(
        chain.get("allocation"),
        f"chain {chain_id}.allocation",
    )
    fragments = _required_list(
        allocation.get("fragments"),
        f"chain {chain_id}.allocation.fragments",
    )
    violations = []
    if not translation:
        violations.append("empty_whole_target")
    if allocation.get("verified") is not True:
        violations.append("allocation_not_verified")
    if len(fragments) != len(local_refs):
        violations.append("fragment_member_count")
    cursor = 0
    released = False
    for fragment_index, raw_fragment in enumerate(fragments):
        item = _required_mapping(
            raw_fragment,
            f"chain {chain_id}.fragment {fragment_index}",
        )
        target_range = item.get("target_range")
        if (
            not isinstance(target_range, list)
            or len(target_range) != 2
            or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in target_range
            )
        ):
            raise MinimalDetectionError(
                f"chain {chain_id} fragment {fragment_index} has invalid range"
            )
        start, end = target_range
        status = item.get("status")
        is_released = status == "released"
        if status not in {"allocated", "released"}:
            raise MinimalDetectionError(
                f"chain {chain_id} fragment {fragment_index} has invalid status"
            )
        if start != cursor or end < start:
            violations.append("target_range_discontinuity")
        if item.get("chars") != end - start:
            violations.append("fragment_char_count")
        if fragment_index < len(local_refs) and item.get("source_ref") != local_refs[
            fragment_index
        ]:
            violations.append("fragment_source_order")
        if is_released:
            released = True
            if start != end:
                violations.append("released_fragment_not_empty")
        elif released or start == end:
            violations.append("released_fragment_not_trailing")
        cursor = max(cursor, end)
    if cursor != len(translation):
        violations.append("whole_target_range")
    if allocation.get("whole_target_chars") != len(translation):
        violations.append("whole_target_char_count")
    return violations


def _chain_issue(
    *,
    baseline: DetectionBaseline,
    article_document_ir,
    config: DetectorConfig,
    pass_index: int,
    chain_id: str,
    local_refs: tuple[str, ...],
    violations: list[str],
    evidence: dict | None = None,
) -> Issue:
    physical_refs = tuple(baseline.physical_ref(item) for item in local_refs)
    owners = tuple(
        sorted(
            {
                article_document_ir.by_element[item]
                for item in local_refs
                if item in article_document_ir.by_element
            }
        )
    )
    page = (
        _source_ref(physical_refs[0])[0]
        if physical_refs
        else baseline.physical_labels[0]
    )
    details = {} if evidence is None else dict(evidence)
    details.update(
        {
            "chain_id": chain_id,
            "violations": sorted(set(violations)),
            "violation_count": len(set(violations)),
            "identity_ref": chain_id,
        }
    )
    return Issue(
        kind="chain_conservation",
        page=page,
        paragraph_refs=physical_refs,
        geometry=_chain_geometry(baseline, local_refs),
        severity=config.severity["chain_conservation"],
        evidence=details,
        detector="chain_conservation",
        detected_at_iteration=pass_index,
        article_refs=owners,
        source_refs=local_refs,
    )


def _chain_findings(
    working_dir: Path,
    baseline: DetectionBaseline,
    article_document_ir,
    config: DetectorConfig,
    pass_index: int,
    translation_performed: bool,
) -> tuple[list[Issue], dict]:
    path = working_dir / CHAIN_REPORT_NAME
    if not path.is_file():
        evidence = {
            "status": (
                "missing_after_translation"
                if translation_performed
                else "skipped_translation_not_performed"
            ),
            "path": str(path),
            "chains": 0,
            "violations": int(translation_performed),
            "typed_skip": not translation_performed,
        }
        if not translation_performed:
            return [], evidence
        issue = _chain_issue(
            baseline=baseline,
            article_document_ir=article_document_ir,
            config=config,
            pass_index=pass_index,
            chain_id="chain-report",
            local_refs=(),
            violations=["translated_chain_report_missing"],
            evidence={"report_path": str(path)},
        )
        return [issue], evidence
    report = _required_mapping(
        json.loads(path.read_text(encoding="utf-8")),
        CHAIN_REPORT_NAME,
    )
    _required_text(report.get("language"), f"{CHAIN_REPORT_NAME}.language")
    if not isinstance(report.get("applied"), bool):
        raise MinimalDetectionError(f"{CHAIN_REPORT_NAME}.applied must be boolean")
    if not isinstance(report.get("align_enabled"), bool):
        raise MinimalDetectionError(
            f"{CHAIN_REPORT_NAME}.align_enabled must be boolean"
        )
    counts = _required_mapping(
        report.get("counts"),
        f"{CHAIN_REPORT_NAME}.counts",
    )
    count_values = {
        name: _nonnegative_integer(
            counts.get(name),
            f"{CHAIN_REPORT_NAME}.counts.{name}",
        )
        for name in (
            "chains",
            "merged",
            "escalated",
            "merged_members",
            "skips",
            "translator_calls",
            "alignment_requests",
            "aligned_cuts",
        )
    }
    chains = _required_list(report.get("chains"), f"{CHAIN_REPORT_NAME}.chains")
    outcomes = _required_list(
        report.get("outcomes"),
        f"{CHAIN_REPORT_NAME}.outcomes",
    )
    escalated = _required_list(
        report.get("escalated"),
        f"{CHAIN_REPORT_NAME}.escalated",
    )
    skips = _required_list(report.get("skips"), f"{CHAIN_REPORT_NAME}.skips")
    short_units = report.get("short_units")
    short_unit_counts = None
    if short_units is not None:
        short_units = _required_mapping(
            short_units,
            f"{CHAIN_REPORT_NAME}.short_units",
        )
        short_unit_counts = {
            name: _nonnegative_integer(
                short_units.get(name),
                f"{CHAIN_REPORT_NAME}.short_units.{name}",
            )
            for name in ("admitted", "refused", "requests")
        }

    root_violations = []
    if report["applied"] is not True:
        root_violations.append("chain_plan_not_applied")

    outcome_rows = []
    outcomes_by_id: dict[str, list[dict]] = {}
    member_identity_to_ref = {}
    claimed_refs = set()
    for position, raw_outcome in enumerate(outcomes):
        outcome = _required_mapping(raw_outcome, f"outcome {position}")
        chain_id = _required_text(outcome.get("chain_id"), f"outcome {position}.chain_id")
        canonical_chain_id = _required_text(
            outcome.get("canonical_chain_id"),
            f"outcome {chain_id}.canonical_chain_id",
        )
        article_id = outcome.get("article_id")
        if article_id is not None:
            _required_text(article_id, f"outcome {chain_id}.article_id")
        local_refs = _chain_refs(
            outcome.get("ordered_source_refs"),
            f"outcome {chain_id}.ordered_source_refs",
            article_document_ir,
        )
        calls = _nonnegative_integer(
            outcome.get("translator_call_count"),
            f"outcome {chain_id}.translator_call_count",
        )
        result_state = _required_text(
            outcome.get("result_state"),
            f"outcome {chain_id}.result_state",
        )
        if result_state not in _CHAIN_STATES:
            raise MinimalDetectionError(
                f"outcome {chain_id} has invalid result_state {result_state!r}"
            )
        members = _required_list(
            outcome.get("members"),
            f"outcome {chain_id}.members",
        )
        if len(members) != len(local_refs):
            raise MinimalDetectionError(
                f"outcome {chain_id} member list disagrees with ordered refs"
            )
        for member_index, (raw_member, local_ref) in enumerate(
            zip(members, local_refs, strict=True)
        ):
            member = _required_mapping(
                raw_member,
                f"outcome {chain_id}.member {member_index}",
            )
            if member.get("source_ref") != local_ref:
                raise MinimalDetectionError(
                    f"outcome {chain_id} member order disagrees with source refs"
                )
            chain_index = _optional_integer(
                member.get("chain_index"),
                f"outcome {chain_id}.member {member_index}.chain_index",
            )
            page_index = _nonnegative_integer(
                member.get("page_index"),
                f"outcome {chain_id}.member {member_index}.page_index",
            )
            debug_id = member.get("debug_id")
            if debug_id is not None:
                _required_text(
                    debug_id,
                    f"outcome {chain_id}.member {member_index}.debug_id",
                    allow_empty=True,
                )
            identity = (chain_id, chain_index, debug_id, page_index)
            if identity in member_identity_to_ref:
                root_violations.append("duplicate_outcome_member_identity")
            member_identity_to_ref[identity] = local_ref
        violations = []
        if calls != 1:
            violations.append("translator_call_count")
        if len(local_refs) != len(set(local_refs)):
            violations.append("duplicate_source_ref")
        if claimed_refs.intersection(local_refs):
            root_violations.append("source_ref_claimed_by_multiple_chains")
        claimed_refs.update(local_refs)
        if result_state != "joint_success":
            violations.append("non_joint_success")
        row = {
            "chain_id": chain_id,
            "canonical_chain_id": canonical_chain_id,
            "article_id": article_id,
            "translator_call_count": calls,
            "result_state": result_state,
            "local_refs": local_refs,
            "violations": violations,
            "raw": outcome,
        }
        outcome_rows.append(row)
        outcomes_by_id.setdefault(chain_id, []).append(row)
    if any(len(rows) != 1 for rows in outcomes_by_id.values()):
        root_violations.append("duplicate_chain_outcome")

    entry_rows = []
    entries_by_id: dict[str, list[dict]] = {}
    for position, raw_chain in enumerate(chains):
        chain = _required_mapping(raw_chain, f"chain {position}")
        chain_id = _required_text(chain.get("chain_id"), f"chain {position}.chain_id")
        local_refs = _chain_refs(
            chain.get("ordered_source_refs"),
            f"chain {chain_id}.ordered_source_refs",
            article_document_ir,
        )
        calls = _nonnegative_integer(
            chain.get("translator_call_count"),
            f"chain {chain_id}.translator_call_count",
        )
        state = _required_text(
            chain.get("result_state"),
            f"chain {chain_id}.result_state",
        )
        members = _required_list(chain.get("members"), f"chain {chain_id}.members")
        if len(members) != len(local_refs):
            raise MinimalDetectionError(
                f"chain {chain_id} member list disagrees with ordered refs"
            )
        for member_index, raw_member in enumerate(members):
            member = _required_mapping(
                raw_member,
                f"chain {chain_id}.member {member_index}",
            )
            _optional_integer(
                member.get("chain_index"),
                f"chain {chain_id}.member {member_index}.chain_index",
            )
            _nonnegative_integer(
                member.get("page_index"),
                f"chain {chain_id}.member {member_index}.page_index",
            )
            _nonnegative_integer(
                member.get("source_chars"),
                f"chain {chain_id}.member {member_index}.source_chars",
            )
            _required_mapping(
                member.get("segment"),
                f"chain {chain_id}.member {member_index}.segment",
            )
        canonical_chain_id = _required_text(
            chain.get("canonical_chain_id"),
            f"chain {chain_id}.canonical_chain_id",
        )
        article_id = _required_text(
            chain.get("article_id"),
            f"chain {chain_id}.article_id",
        )
        violations = _allocation_violations(chain_id, chain, local_refs)
        if calls != 1:
            violations.append("translator_call_count")
        if len(local_refs) != len(set(local_refs)):
            violations.append("duplicate_source_ref")
        if state != "joint_success":
            violations.append("chain_entry_not_joint_success")
        row = {
            "chain_id": chain_id,
            "canonical_chain_id": canonical_chain_id,
            "article_id": article_id,
            "translator_call_count": calls,
            "result_state": state,
            "local_refs": local_refs,
            "violations": violations,
        }
        entry_rows.append(row)
        entries_by_id.setdefault(chain_id, []).append(row)
    if any(len(rows) != 1 for rows in entries_by_id.values()):
        root_violations.append("duplicate_chain_entry")

    for outcome in outcome_rows:
        entries = entries_by_id.get(outcome["chain_id"], ())
        if outcome["result_state"] == "joint_success":
            if len(entries) != 1:
                outcome["violations"].append("successful_outcome_without_unique_entry")
            else:
                entry = entries[0]
                for name in (
                    "canonical_chain_id",
                    "article_id",
                    "translator_call_count",
                    "local_refs",
                ):
                    if entry[name] != outcome[name]:
                        outcome["violations"].append(f"entry_{name}_mismatch")
                outcome["violations"].extend(entry["violations"])
        elif entries:
            outcome["violations"].append("failed_outcome_has_chain_entry")
    if set(entries_by_id).difference(outcomes_by_id):
        root_violations.append("chain_entry_without_outcome")

    escalated_ids = []
    for position, raw_escalated in enumerate(escalated):
        item = _required_mapping(raw_escalated, f"escalated {position}")
        chain_id = _required_text(
            item.get("chain_id"),
            f"escalated {position}.chain_id",
        )
        rows = outcomes_by_id.get(chain_id, ())
        if len(rows) != 1 or item != rows[0]["raw"]:
            root_violations.append("escalated_outcome_mismatch")
        escalated_ids.append(chain_id)
    expected_escalated = sorted(
        row["chain_id"]
        for row in outcome_rows
        if row["result_state"] != "joint_success"
    )
    if sorted(escalated_ids) != expected_escalated:
        root_violations.append("escalated_set_mismatch")

    skip_refs = []
    skip_identities = set()
    short_unit_skip_count = 0
    for position, raw_skip in enumerate(skips):
        skip = _required_mapping(raw_skip, f"skip {position}")
        chain_id = _required_text(
            skip.get("chain_id"),
            f"skip {position}.chain_id",
            allow_empty=True,
        )
        chain_index = _optional_integer(
            skip.get("chain_index"),
            f"skip {position}.chain_index",
        )
        page_index = _nonnegative_integer(
            skip.get("page_index"),
            f"skip {position}.page_index",
        )
        debug_id = skip.get("debug_id")
        if debug_id is not None:
            _required_text(
                debug_id,
                f"skip {position}.debug_id",
                allow_empty=True,
            )
        if skip.get("reason") != "chain_member":
            raise MinimalDetectionError(f"skip {position} has invalid reason")
        taken_by = skip.get("taken_by")
        if taken_by not in {"chain", "short_unit"}:
            raise MinimalDetectionError(f"skip {position} has invalid owner")
        result_state = skip.get("result_state")
        declined_by = _required_list(
            skip.get("declined_by"),
            f"skip {position}.declined_by",
        )
        if (
            len(declined_by) != len(set(declined_by))
            or not set(declined_by).issubset(_CHAIN_SKIP_MECHANISMS)
        ):
            raise MinimalDetectionError(f"skip {position} has invalid decline records")
        identity = (taken_by, chain_id, chain_index, debug_id, page_index)
        if identity in skip_identities:
            root_violations.append("duplicate_skip_identity")
        skip_identities.add(identity)
        if taken_by == "chain":
            if result_state not in _CHAIN_STATES:
                root_violations.append("chain_skip_result_state_missing_or_invalid")
            member_identity = (chain_id, chain_index, debug_id, page_index)
            local_ref = member_identity_to_ref.get(member_identity)
            if local_ref is None:
                root_violations.append("dangling_chain_skip")
                continue
            skip_refs.append(local_ref)
            rows = outcomes_by_id.get(chain_id, ())
            if len(rows) != 1 or result_state != rows[0]["result_state"]:
                root_violations.append("skip_result_state_mismatch")
        else:
            short_unit_skip_count += 1
            if chain_id != "" or chain_index is not None:
                root_violations.append("short_unit_skip_owner_fields_invalid")
            if result_state is not None:
                root_violations.append("short_unit_skip_result_state_invalid")
    if len(skip_refs) != len(set(skip_refs)):
        root_violations.append("duplicate_skip_source_ref")
    if set(skip_refs) != claimed_refs:
        root_violations.append("claim_member_set_mismatch")
    if short_unit_counts is None:
        if short_unit_skip_count:
            root_violations.append("short_unit_skips_without_report")
    else:
        if short_unit_skip_count > short_unit_counts["admitted"]:
            root_violations.append("short_unit_skip_count_exceeds_admitted")
        if short_unit_counts["requests"] > short_unit_counts["admitted"]:
            root_violations.append("short_unit_requests_exceed_admitted")

    if count_values["chains"] != len(outcomes):
        root_violations.append("count_chains_mismatch")
    if count_values["merged"] != len(chains):
        root_violations.append("count_merged_mismatch")
    if count_values["escalated"] != len(escalated):
        root_violations.append("count_escalated_mismatch")
    if count_values["skips"] != len(skips):
        root_violations.append("count_skips_mismatch")
    if count_values["merged_members"] != sum(
        len(row["local_refs"]) for row in entry_rows
    ):
        root_violations.append("count_merged_members_mismatch")
    if count_values["translator_calls"] != sum(
        row["translator_call_count"] for row in outcome_rows
    ):
        root_violations.append("count_translator_calls_mismatch")

    records = []
    found = []
    for row in outcome_rows:
        violations = sorted(set(row["violations"]))
        records.append(
            {
                "chain_id": row["chain_id"],
                "translator_call_count": row["translator_call_count"],
                "result_state": row["result_state"],
                "members": len(row["local_refs"]),
                "violations": violations,
            }
        )
        if violations:
            found.append(
                _chain_issue(
                    baseline=baseline,
                    article_document_ir=article_document_ir,
                    config=config,
                    pass_index=pass_index,
                    chain_id=row["chain_id"],
                    local_refs=row["local_refs"],
                    violations=violations,
                    evidence={
                        "translator_call_count": row["translator_call_count"],
                        "result_state": row["result_state"],
                        "member_count": len(row["local_refs"]),
                    },
                )
            )
    root_violations = sorted(set(root_violations))
    if root_violations:
        found.append(
            _chain_issue(
                baseline=baseline,
                article_document_ir=article_document_ir,
                config=config,
                pass_index=pass_index,
                chain_id="chain-report",
                local_refs=tuple(sorted(claimed_refs)),
                violations=root_violations,
                evidence={"report_path": str(path)},
            )
        )
    return found, {
        "status": "available",
        "path": str(path),
        "applied": report["applied"],
        "chains": len(outcomes),
        "merged": len(chains),
        "escalated": len(escalated),
        "skips": len(skips),
        "violations": sum(bool(item["violations"]) for item in records)
        + bool(root_violations),
        "root_violations": root_violations,
        "records": records,
    }


def _with_contract(issue: Issue, baseline, article_document_ir, config) -> Issue:
    local_refs = tuple(
        reference
        for reference in (
            baseline.source_geometry.local_ref(item) for item in issue.paragraph_refs
        )
        if reference is not None
    )
    if issue.source_refs:
        local_refs = issue.source_refs
    owners = tuple(
        sorted(
            {
                article_document_ir.by_element[reference]
                for reference in local_refs
                if reference in article_document_ir.by_element
            }
        )
    )
    evidence = dict(issue.evidence)
    if local_refs:
        evidence["local_paragraph_refs"] = list(local_refs)
    return replace(issue, evidence=evidence).with_severity_fields(
        config.progress_fields(issue.kind)
    ).with_contract(
        suggested_action_type=config.suggested_action(issue.kind),
        article_refs=owners,
        source_refs=local_refs,
    )


def _write_sidecar(working_dir: Path, sidecar_name: str, record: dict) -> Path:
    if sidecar_name not in SIDECAR_NAMES:
        raise MinimalDetectionError(
            f"sidecar name must be one of {sorted(SIDECAR_NAMES)}"
        )
    path = working_dir / sidecar_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def detect(
    docs,
    article_document_ir,
    baseline: DetectionBaseline,
    *,
    language: str | None,
    translation_performed: bool,
    working_dir: str | Path,
    sidecar_name: str,
    pass_index: int,
    flow_report: dict | None = None,
    config: DetectorConfig | None = None,
    repair_owned_binding: tuple[str, str] | None = None,
) -> DetectionResult:
    """Run the closed six-detector set once and write the named sidecar."""
    if baseline.document_identity != id(docs):
        raise MinimalDetectionError("detection baseline belongs to another document")
    if baseline.article_document_identity != id(article_document_ir):
        raise MinimalDetectionError("detection baseline belongs to another ArticleIR")
    if not isinstance(pass_index, int) or isinstance(pass_index, bool) or pass_index < 0:
        raise MinimalDetectionError("detection pass index must be a non-negative integer")
    pages = docs.page or ()
    if len(pages) != len(baseline.physical_labels):
        raise MinimalDetectionError("selected document page count changed after baseline")
    config = detector_config() if config is None else config
    views = [
        PageView(label=label, page=page, policy=None)
        for label, page in zip(baseline.physical_labels, pages, strict=True)
    ]
    committed_flow_refs = _committed_flow_refs(flow_report, article_document_ir)
    if repair_owned_binding is not None and pass_index != 1:
        raise MinimalDetectionError(
            "repair-owned exclusion is allowed only on candidate pass 1"
        )
    repair_binding = _repair_owned_binding(
        repair_owned_binding,
        baseline=baseline,
        docs=docs,
        article_document_ir=article_document_ir,
        committed_flow_refs=committed_flow_refs,
    )
    repair_local_ref = None if repair_binding is None else repair_binding[1]
    current_inventory = fixed_assets.build_inventory(
        docs,
        article_document_ir=article_document_ir,
        flow_owned_paragraph_refs=committed_flow_refs.union(
            () if repair_local_ref is None else (repair_local_ref,)
        ),
    )
    fixed_baseline = _without_fixed_ref(
        baseline.fixed_inventory,
        repair_local_ref,
    )
    fixed_comparison = fixed_assets.compare(
        fixed_baseline,
        current_inventory,
        config.fixed_asset_bbox_tolerance_pt,
    )
    context = DetectionContext(
        pages=views,
        config=config,
        language=language,
        iteration=pass_index,
        translation_performed=translation_performed,
        working_dir=Path(working_dir),
        source_geometry=baseline.source_geometry,
        article_document_ir=article_document_ir,
        fixed_inventory=fixed_baseline,
        current_inventory=current_inventory,
        finalized=True,
    )
    issues = []
    skips = []
    for module in _PAGE_DETECTORS:
        if module is residue and not translation_performed:
            skip = {
                "detector": residue.NAME,
                "reason": "translation_not_performed",
                "typed": True,
            }
            skips.append(skip)
            context.file(residue.NAME, {**skip, "status": "skipped"})
            context.notes.append(
                "untranslated_residue: translation was not performed; detector skipped"
            )
            continue
        detected = module.detect(context)
        issues.extend(detected)
        context.file(
            module.NAME,
            {"status": "completed", "issue_count": len(detected)},
        )
    chain_issues, chain_evidence = _chain_findings(
        Path(working_dir),
        baseline,
        article_document_ir,
        config,
        pass_index,
        translation_performed,
    )
    issues.extend(chain_issues)
    context.file(
        "chain_conservation",
        {
            "status": chain_evidence["status"],
            "issue_count": len(chain_issues),
        },
    )
    fixed_issues = fixed_asset_drift.detect(context)
    local_to_physical = baseline.local_to_physical
    fixed_issues = [
        replace(issue, page=local_to_physical.get(issue.page, issue.page))
        for issue in fixed_issues
    ]
    issues.extend(fixed_issues)
    context.file(
        fixed_asset_drift.NAME,
        {"status": "completed", "issue_count": len(fixed_issues)},
    )
    contracted = tuple(
        sorted(
            (
                _with_contract(issue, baseline, article_document_ir, config)
                for issue in issues
            ),
            key=Issue.sort_key,
        )
    )
    by_kind = dict.fromkeys(ISSUE_KINDS, 0)
    for issue in contracted:
        if issue.kind not in by_kind:
            raise MinimalDetectionError(f"unexpected issue kind: {issue.kind}")
        by_kind[issue.kind] += 1
    record = {
        "schema_version": SCHEMA_VERSION,
        "pass_index": pass_index,
        "translation_performed": translation_performed,
        "physical_to_local": {
            str(physical): local
            for physical, local in baseline.physical_to_local.items()
        },
        "source_geometry": baseline.source_geometry.to_record(),
        "flow_owned_paragraph_refs": sorted(committed_flow_refs),
        "repair_owned_paragraph": (
            None
            if repair_binding is None
            else {
                "physical_ref": repair_binding[0],
                "local_ref": repair_binding[1],
                "symmetric_fixed_exclusion": True,
            }
        ),
        "counts": {"issues": len(contracted), "by_kind": by_kind},
        "notes": list(context.notes),
        "skips": skips,
        "detector_records": {
            name: list(rows) for name, rows in sorted(context.records.items())
        },
        "chain_conservation": chain_evidence,
        "fixed_comparison": fixed_comparison.to_record(),
        "issues": [issue.as_record() for issue in contracted],
    }
    report_path = _write_sidecar(Path(working_dir), sidecar_name, record)
    return DetectionResult(contracted, record, report_path)
