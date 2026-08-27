"""Source-bound delivery evidence for manual HITL constraints.

The canonical expectation value type lives in :mod:`hitl_expectation`.  This
module owns only its execution evidence: it builds an immutable inventory from
one validated v4 decision projection and advances delivery/target stages from
bounded runtime facts.  It never infers the expected value from model output.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Final

from babeldoc.magazine import hitl_binding
from babeldoc.magazine.hitl_expectation import ManualConstraintEvidence
from babeldoc.magazine.hitl_expectation import ManualConstraintExpectation
from babeldoc.magazine.hitl_expectation import ManualConstraintKind
from babeldoc.magazine.hitl_expectation import ManualConstraintStage
from babeldoc.magazine.hitl_expectation import ManualConstraintStatus
from babeldoc.magazine.hitl_expectation import pending_stage_evidence
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import load_taxonomy

MANUAL_DELIVERY_SCHEMA_VERSION: Final = "babeldoc.manual-constraint-delivery.v1"
PAGE_POLICY_OBSERVABLES_SCHEMA_VERSION: Final = (
    "babeldoc.page-policy-observables.v1"
)
TERM_NORMALIZATION_VERSION: Final = "unicode-nfc-exact-whitespace-v1"
TERM_ELIGIBILITY_VALUES: Final = frozenset({"eligible", "protected_fixed"})
POLICY_FIELDS: Final = (
    "translate",
    "chain_eligible",
    "starts_article",
    "opens_article",
    "preserve_line_structure",
    "indent_eligible",
    "repair_profile",
)
PAGE_POLICY_OBSERVABLES_PATH: Final = config_path("page_policy_observables.json")
MANUAL_DELIVERY_REPORT_NAME: Final = "manual_constraint_delivery.report.json"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ManualConstraintDeliveryError(ValueError):
    """Raised before partial evidence can be admitted to the inventory."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bounded_ref(prefix: str, value: str) -> str:
    return f"{prefix}:sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def normalize_term(value: str) -> str:
    """Apply the one closed normalization policy used for target assertions."""

    if not isinstance(value, str):
        raise ManualConstraintDeliveryError("term value must be a string")
    return " ".join(unicodedata.normalize("NFC", value).split())


def _stage(
    expectation: ManualConstraintExpectation,
    stage: ManualConstraintStage,
    status: ManualConstraintStatus,
    refs: Iterable[str],
) -> ManualConstraintExpectation:
    evidence = ManualConstraintEvidence(
        stage=stage,
        status=status,
        evidence_refs=tuple(refs),
    )
    replaced = tuple(
        evidence if item.stage is stage else item for item in expectation.stage_evidence
    )
    return replace(expectation, stage_evidence=replaced)


def _initial_stage_evidence(selected: bool) -> tuple[ManualConstraintEvidence, ...]:
    if selected:
        return pending_stage_evidence()
    evidence = pending_stage_evidence()
    for stage in (ManualConstraintStage.DELIVERY, ManualConstraintStage.TARGET):
        item = ManualConstraintEvidence(
            stage=stage,
            status=ManualConstraintStatus.NOT_SELECTED,
            evidence_refs=("projection:not-selected",),
        )
        evidence = tuple(item if current.stage is stage else current for current in evidence)
    return evidence


def _review_indexes(review: Mapping[str, Any]) -> dict[str, dict[str, Mapping[str, Any]]]:
    indexes: dict[str, dict[str, Mapping[str, Any]]] = {
        "page_kinds": {},
        "terms": {},
        "drop_caps": {},
    }
    for section, key in (
        ("page_kinds", "page"),
        ("terms", "source"),
        ("drop_caps", "reference"),
    ):
        for candidate in review.get(section) or ():
            indexes[section][str(candidate[key])] = candidate
    return indexes


def _drop_cap_value(raw: object) -> str:
    if isinstance(raw, Mapping):
        decision = raw.get("decision")
        if isinstance(decision, str) and decision:
            return decision
    if isinstance(raw, str) and raw:
        return raw
    raise ManualConstraintDeliveryError("drop-cap human decision has no verdict")


@dataclass(frozen=True, slots=True)
class TermConstraint:
    expectation_id: str
    source: str
    occurrence_ref: str
    physical_page: int
    stable_source_ref: str
    source_span: tuple[int, int]
    role: str
    eligibility: str
    eligibility_rule_id: str


@dataclass(frozen=True, slots=True)
class PagePolicyConstraint:
    expectation_id: str
    physical_page: int
    page_kind: str
    stable_ref: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class DropCapConstraint:
    expectation_id: str
    reference: str
    physical_page: int
    stable_ref: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class TermDeliveryEvidence:
    occurrence_ref: str
    physical_page: int
    paragraph_ref: str
    eligibility: str
    eligibility_rule_id: str
    request_sha256: str | None = None
    glossary_sha256: str | None = None
    fixed_asset_ref: str | None = None


@dataclass(frozen=True, slots=True)
class TermTargetEvidence:
    occurrence_ref: str
    physical_page: int
    paragraph_ref: str
    target_text: str | None
    mapping_count: int
    target_span: tuple[int, int] | None = None
    fixed_asset_ref: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyConsumption:
    expectation_id: str
    physical_page: int
    page_kind: str
    field: str
    consumer: str
    runtime_event: str
    policy_sha256: str
    value_sha256: str

    def to_record(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "expectation_id": self.expectation_id,
            "field": self.field,
            "page_kind": self.page_kind,
            "physical_page": self.physical_page,
            "policy_sha256": self.policy_sha256,
            "runtime_event": self.runtime_event,
            "value_sha256": self.value_sha256,
        }


@dataclass(frozen=True, slots=True)
class DropCapDeliveryEvidence:
    reference: str
    physical_page: int
    paragraph_ref: str
    fingerprint: str
    decision: str


@dataclass(frozen=True, slots=True)
class DropCapTargetEvidence:
    reference: str
    physical_page: int
    paragraph_ref: str
    ownership_ref: str
    translated_first_character: str
    decision: str
    flatten_status: str


@dataclass(frozen=True, slots=True)
class ManualConstraintInventory:
    """Immutable runtime state derived only from one validated v4 envelope."""

    source_binding_sha256: str
    expectations: tuple[ManualConstraintExpectation, ...]
    term_constraints: tuple[TermConstraint, ...]
    page_constraints: tuple[PagePolicyConstraint, ...]
    drop_cap_constraints: tuple[DropCapConstraint, ...]
    term_deliveries: tuple[TermDeliveryEvidence, ...] = ()
    policy_consumptions: tuple[PolicyConsumption, ...] = ()
    unsupported_pages_at_article_ir: tuple[int, ...] = ()
    schema_version: str = MANUAL_DELIVERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MANUAL_DELIVERY_SCHEMA_VERSION:
            raise ManualConstraintDeliveryError("unknown manual delivery schema")
        if not _HEX64.fullmatch(self.source_binding_sha256):
            raise ManualConstraintDeliveryError("invalid source binding digest")
        identifiers = [item.expectation_id for item in self.expectations]
        if identifiers != sorted(identifiers) or len(set(identifiers)) != len(
            identifiers
        ):
            raise ManualConstraintDeliveryError(
                "expectation inventory must have sorted unique identifiers"
            )

    def by_id(self) -> dict[str, ManualConstraintExpectation]:
        return {item.expectation_id: item for item in self.expectations}

    def with_expectations(
        self, expectations: Mapping[str, ManualConstraintExpectation]
    ) -> ManualConstraintInventory:
        if set(expectations) != {item.expectation_id for item in self.expectations}:
            raise ManualConstraintDeliveryError("expectation inventory changed shape")
        return replace(
            self,
            expectations=tuple(expectations[key] for key in sorted(expectations)),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "expectations": [item.to_record() for item in self.expectations],
            "policy_consumptions": [
                item.to_record() for item in self.policy_consumptions
            ],
            "schema_version": self.schema_version,
            "source_binding_sha256": self.source_binding_sha256,
            "unsupported_pages_at_article_ir": list(
                self.unsupported_pages_at_article_ir
            ),
        }

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_record(),
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")


def inventory_from_bound(
    bound: hitl_binding.BoundDecisionProjection,
) -> ManualConstraintInventory:
    """Create the complete immutable denominator from human v4 decisions."""

    source_digest = hitl_binding.source_binding_sha256(
        bound.decisions["source_binding"]
    )
    indexes = _review_indexes(bound.review)
    selected = set(bound.selected_pages)
    expectations: list[ManualConstraintExpectation] = []
    term_constraints: list[TermConstraint] = []
    page_constraints: list[PagePolicyConstraint] = []
    drop_constraints: list[DropCapConstraint] = []

    for source, human_target in sorted(bound.decisions["terms"].items()):
        candidate = indexes["terms"].get(str(source))
        if candidate is None or not candidate.get("occurrences"):
            raise ManualConstraintDeliveryError(
                f"term decision {source!r} has no bound occurrence"
            )
        all_refs = tuple(item["source_ref"] for item in candidate["occurrences"])
        for occurrence in candidate["occurrences"]:
            eligibility = str(occurrence["translation_eligibility"])
            if eligibility not in TERM_ELIGIBILITY_VALUES:
                raise ManualConstraintDeliveryError(
                    f"unknown term eligibility {eligibility!r}"
                )
            occurrence_ref = str(occurrence["source_ref"])
            page = int(occurrence["physical_page"])
            expectation_id = f"term:{_digest([source, occurrence_ref])}"
            is_selected = page in selected
            expectations.append(
                ManualConstraintExpectation(
                    expectation_id=expectation_id,
                    kind=ManualConstraintKind.TERM,
                    human_value=str(human_target),
                    source_occurrence_refs=all_refs,
                    selected_occurrence_refs=(occurrence_ref,) if is_selected else (),
                    source_binding_sha256=source_digest,
                    stage_evidence=_initial_stage_evidence(is_selected),
                )
            )
            term_constraints.append(
                TermConstraint(
                    expectation_id=expectation_id,
                    source=str(source),
                    occurrence_ref=occurrence_ref,
                    physical_page=page,
                    stable_source_ref=str(occurrence["stable_source_ref"]),
                    source_span=tuple(int(value) for value in occurrence["source_span"]),
                    role=str(occurrence["role"]),
                    eligibility=eligibility,
                    eligibility_rule_id=str(occurrence["eligibility_rule_id"]),
                )
            )

    for raw_page, page_kind in sorted(
        bound.decisions["page_kinds"].items(), key=lambda item: int(item[0])
    ):
        page = int(raw_page)
        candidate = indexes["page_kinds"].get(str(page))
        if candidate is None:
            raise ManualConstraintDeliveryError(f"page decision {page} has no candidate")
        occurrence_ref = str(candidate["stable_ref"])
        expectation_id = f"page-policy:{page}:{_digest([page_kind, occurrence_ref])}"
        is_selected = page in selected
        expectations.append(
            ManualConstraintExpectation(
                expectation_id=expectation_id,
                kind=ManualConstraintKind.PAGE_POLICY,
                human_value=str(page_kind),
                source_occurrence_refs=(occurrence_ref,),
                selected_occurrence_refs=(occurrence_ref,) if is_selected else (),
                source_binding_sha256=source_digest,
                stage_evidence=_initial_stage_evidence(is_selected),
            )
        )
        page_constraints.append(
            PagePolicyConstraint(
                expectation_id=expectation_id,
                physical_page=page,
                page_kind=str(page_kind),
                stable_ref=occurrence_ref,
                fingerprint=str(candidate["fingerprint"]),
            )
        )

    for reference, raw_decision in sorted(bound.decisions["drop_caps"].items()):
        candidate = indexes["drop_caps"].get(str(reference))
        if candidate is None:
            raise ManualConstraintDeliveryError(
                f"drop-cap decision {reference!r} has no candidate"
            )
        page = int(candidate["physical_page"])
        stable_ref = str(candidate["stable_ref"])
        decision = _drop_cap_value(raw_decision)
        expectation_id = f"drop-cap:{_digest([reference, stable_ref])}"
        is_selected = page in selected
        expectations.append(
            ManualConstraintExpectation(
                expectation_id=expectation_id,
                kind=ManualConstraintKind.DROP_CAP,
                human_value=decision,
                source_occurrence_refs=(stable_ref,),
                selected_occurrence_refs=(stable_ref,) if is_selected else (),
                source_binding_sha256=source_digest,
                stage_evidence=_initial_stage_evidence(is_selected),
            )
        )
        drop_constraints.append(
            DropCapConstraint(
                expectation_id=expectation_id,
                reference=str(reference),
                physical_page=page,
                stable_ref=stable_ref,
                fingerprint=str(candidate["fingerprint"]),
            )
        )

    return ManualConstraintInventory(
        source_binding_sha256=source_digest,
        expectations=tuple(sorted(expectations, key=lambda item: item.expectation_id)),
        term_constraints=tuple(term_constraints),
        page_constraints=tuple(page_constraints),
        drop_cap_constraints=tuple(drop_constraints),
    )


def _selected_ids(inventory: ManualConstraintInventory, kind: ManualConstraintKind) -> set[str]:
    return {
        item.expectation_id
        for item in inventory.expectations
        if item.kind is kind and item.selected_occurrence_refs
    }


def _one_per_reference(
    evidence: Iterable[Any], *, label: str
) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for item in evidence:
        reference = item.occurrence_ref if hasattr(item, "occurrence_ref") else item.reference
        if reference in indexed:
            raise ManualConstraintDeliveryError(
                f"{label} repeats mapping for {reference}"
            )
        indexed[reference] = item
    return indexed


def record_term_delivery(
    inventory: ManualConstraintInventory,
    evidence: Iterable[TermDeliveryEvidence],
) -> ManualConstraintInventory:
    """Prove every selected occurrence reached its request or fixed asset."""

    supplied = _one_per_reference(evidence, label="term delivery")
    constraints = {
        item.occurrence_ref: item
        for item in inventory.term_constraints
        if item.expectation_id in _selected_ids(inventory, ManualConstraintKind.TERM)
    }
    if set(supplied) != set(constraints):
        raise ManualConstraintDeliveryError(
            "term delivery occurrence denominator differs "
            f"(missing={sorted(set(constraints) - set(supplied))}, "
            f"unknown={sorted(set(supplied) - set(constraints))})"
        )
    changed = inventory.by_id()
    for reference, actual in supplied.items():
        expected = constraints[reference]
        if (
            actual.physical_page != expected.physical_page
            or actual.eligibility != expected.eligibility
            or actual.eligibility_rule_id != expected.eligibility_rule_id
        ):
            raise ManualConstraintDeliveryError(
                f"term delivery source binding changed for {reference}"
            )
        if expected.eligibility == "protected_fixed":
            if actual.request_sha256 is not None or not actual.fixed_asset_ref:
                raise ManualConstraintDeliveryError(
                    f"protected occurrence {reference} needs untouched asset evidence "
                    "and must not enter a request"
                )
            status = ManualConstraintStatus.NOT_APPLICABLE
            refs = (
                f"occurrence:{reference}",
                f"fixed-asset:{actual.fixed_asset_ref}",
                f"eligibility-rule:{expected.eligibility_rule_id}",
            )
        else:
            if not actual.request_sha256 or not _HEX64.fullmatch(actual.request_sha256):
                raise ManualConstraintDeliveryError(
                    f"eligible occurrence {reference} needs a request digest"
                )
            if not actual.glossary_sha256 or not _HEX64.fullmatch(actual.glossary_sha256):
                raise ManualConstraintDeliveryError(
                    f"eligible occurrence {reference} needs a glossary digest"
                )
            if not actual.paragraph_ref:
                raise ManualConstraintDeliveryError(
                    f"eligible occurrence {reference} needs a paragraph ref"
                )
            status = ManualConstraintStatus.PASS
            refs = (
                f"occurrence:{reference}",
                f"paragraph:{actual.paragraph_ref}",
                f"request:sha256:{actual.request_sha256}",
                f"glossary:sha256:{actual.glossary_sha256}",
                f"eligibility-rule:{expected.eligibility_rule_id}",
            )
        changed[expected.expectation_id] = _stage(
            changed[expected.expectation_id],
            ManualConstraintStage.DELIVERY,
            status,
            refs,
        )
    return replace(
        inventory.with_expectations(changed),
        term_deliveries=tuple(sorted(supplied.values(), key=lambda item: item.occurrence_ref)),
    )


def record_term_targets(
    inventory: ManualConstraintInventory,
    evidence: Iterable[TermTargetEvidence],
) -> ManualConstraintInventory:
    """Assert exact target mappings at the bound page and paragraph."""

    supplied = _one_per_reference(evidence, label="term target")
    constraints = {
        item.occurrence_ref: item
        for item in inventory.term_constraints
        if item.expectation_id in _selected_ids(inventory, ManualConstraintKind.TERM)
    }
    deliveries = {item.occurrence_ref: item for item in inventory.term_deliveries}
    if set(supplied) != set(constraints) or set(deliveries) != set(constraints):
        raise ManualConstraintDeliveryError(
            "term target requires exactly one delivered mapping per selected occurrence"
        )
    changed = inventory.by_id()
    seen_target_spans: set[tuple[str, tuple[int, int]]] = set()
    for reference, actual in supplied.items():
        constraint = constraints[reference]
        delivered = deliveries[reference]
        if (
            actual.physical_page != constraint.physical_page
            or actual.paragraph_ref != delivered.paragraph_ref
        ):
            raise ManualConstraintDeliveryError(
                f"term target {reference} appeared on the wrong page or paragraph"
            )
        expectation = changed[constraint.expectation_id]
        if constraint.eligibility == "protected_fixed":
            if (
                actual.mapping_count != 0
                or actual.target_text is not None
                or actual.target_span is not None
            ):
                raise ManualConstraintDeliveryError(
                    f"protected occurrence {reference} cannot claim a target mapping"
                )
            if not actual.fixed_asset_ref or actual.fixed_asset_ref != delivered.fixed_asset_ref:
                raise ManualConstraintDeliveryError(
                    f"protected occurrence {reference} lost its fixed asset evidence"
                )
            status = ManualConstraintStatus.NOT_APPLICABLE
            refs = (
                f"occurrence:{reference}",
                f"fixed-asset:{actual.fixed_asset_ref}",
                "target:untouched",
            )
        else:
            if actual.mapping_count != 1:
                raise ManualConstraintDeliveryError(
                    f"term target {reference} must have exactly one mapping"
                )
            if actual.target_text is None or normalize_term(actual.target_text) != normalize_term(
                expectation.human_value
            ):
                raise ManualConstraintDeliveryError(
                    f"term target {reference} does not equal the human value"
                )
            if (
                actual.target_span is None
                or len(actual.target_span) != 2
                or actual.target_span[0] < 0
                or actual.target_span[1] - actual.target_span[0]
                != len(normalize_term(actual.target_text))
            ):
                raise ManualConstraintDeliveryError(
                    f"term target {reference} needs one exact target span"
                )
            span_key = (actual.paragraph_ref, actual.target_span)
            if span_key in seen_target_spans:
                raise ManualConstraintDeliveryError(
                    f"term target {reference} duplicates another target span"
                )
            seen_target_spans.add(span_key)
            status = ManualConstraintStatus.PASS
            refs = (
                f"occurrence:{reference}",
                f"paragraph:{actual.paragraph_ref}",
                f"target-span:{actual.target_span[0]}-{actual.target_span[1]}",
                _bounded_ref("target", actual.target_text),
                f"normalization:{TERM_NORMALIZATION_VERSION}",
            )
        changed[constraint.expectation_id] = _stage(
            expectation,
            ManualConstraintStage.TARGET,
            status,
            refs,
        )
    return inventory.with_expectations(changed)


@lru_cache(maxsize=1)
def load_page_policy_observables(path: str | None = None) -> Mapping[str, Any]:
    config = PAGE_POLICY_OBSERVABLES_PATH if path is None else Path(path)
    raw = json.loads(config.read_text(encoding="utf-8"))
    expected_root = {"schema_version", "owner", "fields"}
    if set(raw) != expected_root:
        raise ManualConstraintDeliveryError(
            f"{config.name}: fields differ from {sorted(expected_root)}"
        )
    if raw["schema_version"] != PAGE_POLICY_OBSERVABLES_SCHEMA_VERSION:
        raise ManualConstraintDeliveryError(f"{config.name}: unknown schema version")
    if raw["owner"] != "C20B-manual-delivery-target-base":
        raise ManualConstraintDeliveryError(f"{config.name}: canonical owner changed")
    if tuple(raw["fields"]) != POLICY_FIELDS:
        raise ManualConstraintDeliveryError(
            f"{config.name}: must declare all seven policy fields in canonical order"
        )
    base = {"consumer", "runtime_event", "target_observable", "final_observable"}
    c20c_extension = {"typeset_observable", "final_pdf_observable"}
    required = base | c20c_extension
    for field, declaration in raw["fields"].items():
        if not isinstance(declaration, dict) or set(declaration) != required:
            raise ManualConstraintDeliveryError(
                f"{config.name}: {field} must declare {sorted(required)}"
            )
        if not all(isinstance(value, str) and value for value in declaration.values()):
            raise ManualConstraintDeliveryError(
                f"{config.name}: {field} declarations must be non-empty strings"
            )
    return raw


def page_policy_sha256(page_kind: str) -> str:
    taxonomy = load_taxonomy()
    policy = taxonomy.policy_of(page_kind)
    if policy is None:
        raise ManualConstraintDeliveryError(f"unknown page kind {page_kind!r}")
    return _digest(
        {
            "page_kind": page_kind,
            "policy": policy,
            "taxonomy_version": taxonomy.version,
        }
    )


def record_page_policy_delivery(
    inventory: ManualConstraintInventory,
) -> ManualConstraintInventory:
    """Bind every selected manual page kind to its current taxonomy policy."""

    load_page_policy_observables()
    selected = _selected_ids(inventory, ManualConstraintKind.PAGE_POLICY)
    changed = inventory.by_id()
    for constraint in inventory.page_constraints:
        if constraint.expectation_id not in selected:
            continue
        digest = page_policy_sha256(constraint.page_kind)
        changed[constraint.expectation_id] = _stage(
            changed[constraint.expectation_id],
            ManualConstraintStage.DELIVERY,
            ManualConstraintStatus.PASS,
            (
                f"page:{constraint.physical_page}",
                f"candidate:{constraint.stable_ref}",
                f"policy:sha256:{digest}",
            ),
        )
    return inventory.with_expectations(changed)


def record_page_policy_event(
    inventory: ManualConstraintInventory,
    runtime_event: str,
    *,
    executed_pages: Iterable[int],
    unsupported_pages: Iterable[int] | None = None,
) -> ManualConstraintInventory:
    """Record actual reads made by the consumer assigned to one runtime event."""

    config = load_page_policy_observables()
    fields = [
        (field, declaration)
        for field, declaration in config["fields"].items()
        if declaration["runtime_event"] == runtime_event
    ]
    if not fields:
        raise ManualConstraintDeliveryError(f"unknown policy runtime event {runtime_event!r}")
    executed = {int(page) for page in executed_pages}
    selected_ids = _selected_ids(inventory, ManualConstraintKind.PAGE_POLICY)
    expected_pages = {
        item.physical_page
        for item in inventory.page_constraints
        if item.expectation_id in selected_ids
    }
    missing = expected_pages - executed
    if missing:
        raise ManualConstraintDeliveryError(
            f"policy consumer {runtime_event} did not execute for pages {sorted(missing)}"
        )
    taxonomy = load_taxonomy()
    observations = {
        (item.expectation_id, item.field): item
        for item in inventory.policy_consumptions
    }
    for constraint in inventory.page_constraints:
        if constraint.expectation_id not in selected_ids:
            continue
        policy = taxonomy.policy_of(constraint.page_kind)
        if policy is None:
            raise ManualConstraintDeliveryError(
                f"unknown page kind {constraint.page_kind!r}"
            )
        policy_digest = page_policy_sha256(constraint.page_kind)
        for field, declaration in fields:
            observation = PolicyConsumption(
                expectation_id=constraint.expectation_id,
                physical_page=constraint.physical_page,
                page_kind=constraint.page_kind,
                field=field,
                consumer=declaration["consumer"],
                runtime_event=runtime_event,
                policy_sha256=policy_digest,
                value_sha256=_digest(policy[field]),
            )
            observations[(constraint.expectation_id, field)] = observation
    guarded = inventory.unsupported_pages_at_article_ir
    if unsupported_pages is not None:
        guarded = tuple(sorted({int(page) for page in unsupported_pages}))
    return replace(
        inventory,
        policy_consumptions=tuple(
            observations[key] for key in sorted(observations)
        ),
        unsupported_pages_at_article_ir=guarded,
    )


def finalize_page_policy_targets(
    inventory: ManualConstraintInventory,
    *,
    unsupported_pages: Iterable[int] | None = None,
) -> ManualConstraintInventory:
    """Close page target evidence only after all seven consumers executed."""

    final_unsupported = (
        inventory.unsupported_pages_at_article_ir
        if unsupported_pages is None
        else tuple(sorted({int(page) for page in unsupported_pages}))
    )
    if final_unsupported != inventory.unsupported_pages_at_article_ir:
        raise ManualConstraintDeliveryError(
            "manual page kind changed the same-page multi-article unsupported guard"
        )
    selected = _selected_ids(inventory, ManualConstraintKind.PAGE_POLICY)
    changed = inventory.by_id()
    observed = {
        item.expectation_id: set() for item in inventory.page_constraints
    }
    for item in inventory.policy_consumptions:
        observed.setdefault(item.expectation_id, set()).add(item.field)
    for constraint in inventory.page_constraints:
        if constraint.expectation_id not in selected:
            continue
        missing = set(POLICY_FIELDS) - observed.get(constraint.expectation_id, set())
        if missing:
            raise ManualConstraintDeliveryError(
                f"page {constraint.physical_page} policy consumers missing {sorted(missing)}"
            )
        evidence_refs = [
            f"consumer:{item.field}:{item.consumer}:policy-sha256:{item.policy_sha256}"
            for item in inventory.policy_consumptions
            if item.expectation_id == constraint.expectation_id
        ]
        if constraint.physical_page in final_unsupported:
            evidence_refs.append("guard:same-page-multi-article:unsupported-preserved")
        changed[constraint.expectation_id] = _stage(
            changed[constraint.expectation_id],
            ManualConstraintStage.TARGET,
            ManualConstraintStatus.PASS,
            evidence_refs,
        )
    return inventory.with_expectations(changed)


def record_drop_cap_delivery(
    inventory: ManualConstraintInventory,
    evidence: Iterable[DropCapDeliveryEvidence],
) -> ManualConstraintInventory:
    supplied = _one_per_reference(evidence, label="drop-cap delivery")
    selected = _selected_ids(inventory, ManualConstraintKind.DROP_CAP)
    constraints = {
        item.reference: item
        for item in inventory.drop_cap_constraints
        if item.expectation_id in selected
    }
    if set(supplied) != set(constraints):
        raise ManualConstraintDeliveryError(
            "drop-cap delivery denominator differs from selected decisions"
        )
    changed = inventory.by_id()
    for reference, actual in supplied.items():
        expected = constraints[reference]
        expectation = changed[expected.expectation_id]
        if (
            actual.physical_page != expected.physical_page
            or actual.paragraph_ref != expected.reference
            or actual.fingerprint != expected.fingerprint
            or actual.decision != expectation.human_value
        ):
            raise ManualConstraintDeliveryError(
                f"drop-cap delivery is stale or ambiguous for {reference}"
            )
        changed[expected.expectation_id] = _stage(
            expectation,
            ManualConstraintStage.DELIVERY,
            ManualConstraintStatus.PASS,
            (
                f"paragraph:{actual.paragraph_ref}",
                f"candidate-fingerprint:{actual.fingerprint}",
                f"decision:{actual.decision}",
            ),
        )
    return inventory.with_expectations(changed)


def record_drop_cap_targets(
    inventory: ManualConstraintInventory,
    evidence: Iterable[DropCapTargetEvidence],
) -> ManualConstraintInventory:
    supplied = _one_per_reference(evidence, label="drop-cap target")
    selected = _selected_ids(inventory, ManualConstraintKind.DROP_CAP)
    constraints = {
        item.reference: item
        for item in inventory.drop_cap_constraints
        if item.expectation_id in selected
    }
    if set(supplied) != set(constraints):
        raise ManualConstraintDeliveryError(
            "drop-cap target denominator differs from selected decisions"
        )
    changed = inventory.by_id()
    for reference, actual in supplied.items():
        constraint = constraints[reference]
        expectation = changed[constraint.expectation_id]
        if (
            actual.physical_page != constraint.physical_page
            or actual.paragraph_ref != constraint.reference
            or actual.decision != expectation.human_value
            or not actual.ownership_ref
            or len(normalize_term(actual.translated_first_character)) != 1
        ):
            raise ManualConstraintDeliveryError(
                f"drop-cap target ownership is wrong for {reference}"
            )
        if actual.flatten_status != "applied":
            raise ManualConstraintDeliveryError(
                f"drop-cap target {reference} did not complete the flatten execution point"
            )
        changed[constraint.expectation_id] = _stage(
            expectation,
            ManualConstraintStage.TARGET,
            ManualConstraintStatus.PASS,
            (
                f"paragraph:{actual.paragraph_ref}",
                f"owner:{actual.ownership_ref}",
                _bounded_ref("translated-first-character", actual.translated_first_character),
                f"verdict:{actual.decision}",
                f"flatten-status:{actual.flatten_status}",
            ),
        )
    return inventory.with_expectations(changed)


def write_inventory_report(
    inventory: ManualConstraintInventory, translation_config
) -> Path:
    """Write bounded refs/digests only; never prompts or provider responses."""

    path = Path(
        translation_config.get_working_file_path(MANUAL_DELIVERY_REPORT_NAME)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(inventory.to_json_bytes())
    return path
