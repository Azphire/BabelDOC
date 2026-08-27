"""Typeset and final-PDF validation for canonical manual expectations.

The expectation protocol remains owned by :mod:`hitl_expectation`.  This module
only consumes that type and returns updated instances of the same type; it does
not define a parallel expectation envelope.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from enum import Enum
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from babeldoc.magazine.hitl_expectation import ManualConstraintExpectation
from babeldoc.magazine.hitl_expectation import ManualConstraintKind
from babeldoc.magazine.hitl_expectation import ManualConstraintStage
from babeldoc.magazine.hitl_expectation import ManualConstraintStatus
from babeldoc.magazine.page_identity import PageSelectionMap
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import load_taxonomy

SCHEMA_VERSION = "manual-constraint-final.v1"
NORMALIZATION_VERSION = "nfc-whitespace-v1"
PAGE_POLICY_CONFIG = config_path("page_policy_observables.json")
PAGE_TAXONOMY_CONFIG = config_path("page_types.json")

Box = tuple[float, float, float, float]


class ManualValidationError(ValueError):
    """Structured manual evidence is malformed or its policy is unknown."""


class ValidationScope(str, Enum):
    PARSE_ONLY = "parse_only"
    FULL_TRANSLATION = "full_translation"


class TranslationEligibility(str, Enum):
    ELIGIBLE = "eligible"
    PROTECTED_FIXED = "protected_fixed"


@dataclass(frozen=True, slots=True)
class ManualOccurrenceObservation:
    """Occurrence-bound evidence from typesetting and the semantic target PDF."""

    occurrence_ref: str
    physical_page: int
    output_index: int
    article_id: str
    eligibility: TranslationEligibility
    policy_rule_id: str
    source_article_id: str | None = None
    typeset_text_fragments: tuple[str, ...] = ()
    typeset_fragment_refs: tuple[str, ...] = ()
    typeset_boxes: tuple[Box, ...] = ()
    final_text: str | None = None
    final_glyph_boxes: tuple[Box, ...] = ()
    target_region: Box | None = None
    page_box: Box | None = None
    typeset_observables: Mapping[str, bool] = field(default_factory=dict)
    final_pdf_observables: Mapping[str, bool] = field(default_factory=dict)
    source_fixed_asset_sha256: str | None = None
    final_fixed_asset_sha256: str | None = None
    source_fixed_asset_box: Box | None = None
    final_fixed_asset_box: Box | None = None
    untouched: bool = False
    drop_cap_character: str | None = None
    drop_cap_language: str | None = None

    def __post_init__(self) -> None:
        if not self.occurrence_ref or self.occurrence_ref != self.occurrence_ref.strip():
            raise ManualValidationError("occurrence_ref must be non-empty and trimmed")
        if self.physical_page < 1 or self.output_index < 0:
            raise ManualValidationError("physical_page/output_index are out of range")
        if not self.article_id or self.article_id != self.article_id.strip():
            raise ManualValidationError("article_id must be non-empty and trimmed")
        if (
            not self.source_article_id
            or self.source_article_id != self.source_article_id.strip()
        ):
            raise ManualValidationError("source_article_id must be non-empty and trimmed")
        if not all(isinstance(item, str) for item in self.typeset_text_fragments):
            raise ManualValidationError("typeset_text_fragments must contain strings")
        if not all(
            isinstance(item, str) and item
            for item in self.typeset_fragment_refs
        ):
            raise ManualValidationError(
                "typeset_fragment_refs must contain non-empty strings"
            )
        try:
            eligibility = TranslationEligibility(self.eligibility)
        except (TypeError, ValueError) as exc:
            raise ManualValidationError("unknown translation eligibility") from exc
        if not self.policy_rule_id or self.policy_rule_id != self.policy_rule_id.strip():
            raise ManualValidationError("policy_rule_id must be non-empty and trimmed")
        for name, box in (
            ("target_region", self.target_region),
            ("page_box", self.page_box),
            ("source_fixed_asset_box", self.source_fixed_asset_box),
            ("final_fixed_asset_box", self.final_fixed_asset_box),
        ):
            if box is not None:
                _validate_box(box, name)
        for box in self.typeset_boxes:
            _validate_box(box, "typeset_boxes item")
        for box in self.final_glyph_boxes:
            _validate_box(box, "final_glyph_boxes item")
        for name, values in (
            ("typeset_observables", self.typeset_observables),
            ("final_pdf_observables", self.final_pdf_observables),
        ):
            if not isinstance(values, Mapping) or not all(
                isinstance(key, str) and key and isinstance(value, bool)
                for key, value in values.items()
            ):
                raise ManualValidationError(f"{name} must map strings to booleans")
        object.__setattr__(self, "eligibility", eligibility)
        object.__setattr__(
            self,
            "typeset_observables",
            MappingProxyType(dict(sorted(self.typeset_observables.items()))),
        )
        object.__setattr__(
            self,
            "final_pdf_observables",
            MappingProxyType(dict(sorted(self.final_pdf_observables.items()))),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "occurrence_ref": self.occurrence_ref,
            "physical_page": self.physical_page,
            "output_index": self.output_index,
            "article_id": self.article_id,
            "source_article_id": self.source_article_id,
            "eligibility": self.eligibility.value,
            "policy_rule_id": self.policy_rule_id,
            "typeset_text_fragments": list(self.typeset_text_fragments),
            "typeset_fragment_refs": list(self.typeset_fragment_refs),
            "typeset_boxes": [list(box) for box in self.typeset_boxes],
            "final_text": self.final_text,
            "final_glyph_boxes": [list(box) for box in self.final_glyph_boxes],
            "target_region": None if self.target_region is None else list(self.target_region),
            "page_box": None if self.page_box is None else list(self.page_box),
            "typeset_observables": dict(self.typeset_observables),
            "final_pdf_observables": dict(self.final_pdf_observables),
            "source_fixed_asset_sha256": self.source_fixed_asset_sha256,
            "final_fixed_asset_sha256": self.final_fixed_asset_sha256,
            "source_fixed_asset_box": (
                None
                if self.source_fixed_asset_box is None
                else list(self.source_fixed_asset_box)
            ),
            "final_fixed_asset_box": (
                None
                if self.final_fixed_asset_box is None
                else list(self.final_fixed_asset_box)
            ),
            "untouched": self.untouched,
            "drop_cap_character": self.drop_cap_character,
            "drop_cap_language": self.drop_cap_language,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]):
        if not isinstance(record, Mapping):
            raise ManualValidationError("manual observation must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(record) - allowed
        required = {
            "occurrence_ref",
            "physical_page",
            "output_index",
            "article_id",
            "source_article_id",
            "eligibility",
            "policy_rule_id",
        }
        missing = required - set(record)
        if unknown or missing:
            raise ManualValidationError(
                f"manual observation fields missing={sorted(missing)} unknown={sorted(unknown)}"
            )
        values = dict(record)
        for name in (
            "typeset_text_fragments",
            "typeset_fragment_refs",
        ):
            values[name] = tuple(values.get(name, ()))
        for name in (
            "typeset_boxes",
            "final_glyph_boxes",
        ):
            values[name] = tuple(tuple(float(item) for item in box) for box in values.get(name, ()))
        for name in (
            "target_region",
            "page_box",
            "source_fixed_asset_box",
            "final_fixed_asset_box",
        ):
            if values.get(name) is not None:
                values[name] = tuple(float(item) for item in values[name])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class ManualValidationResult:
    scope: ValidationScope
    status: str
    expectations: tuple[ManualConstraintExpectation, ...]
    issues: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]

    @property
    def accepted(self) -> bool:
        return self.status in {"pass", "parse_gate_pass"}

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "normalization_version": NORMALIZATION_VERSION,
            "scope": self.scope.value,
            "status": self.status,
            "accepted": self.accepted,
            "expectations": [item.to_record() for item in self.expectations],
            "issues": [dict(item) for item in self.issues],
            "evidence": [dict(item) for item in self.evidence],
        }


def _validate_box(box, label: str) -> None:
    if (
        not isinstance(box, tuple)
        or len(box) != 4
        or not all(isinstance(value, int | float) for value in box)
        or not all(math.isfinite(value) for value in box)
        or box[2] <= box[0]
        or box[3] <= box[1]
    ):
        raise ManualValidationError(f"{label} must be a non-empty four-number box")


def _contains(outer: Box, inner: Box, tolerance: float = 0.5) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def _box_close(left: Box | None, right: Box | None, tolerance: float = 0.5) -> bool:
    return left is not None and right is not None and all(
        abs(a - b) <= tolerance for a, b in zip(left, right, strict=True)
    )


def normalize_manual_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFC", value).split())


@lru_cache(maxsize=1)
def load_page_policy_observables() -> dict[str, Any]:
    raw = json.loads(PAGE_POLICY_CONFIG.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "babeldoc.page-policy-observables.v1":
        raise ManualValidationError("unsupported page policy observable schema")
    if raw.get("owner") != "C20B-manual-delivery-target-base":
        raise ManualValidationError("page policy observable owner is not canonical")
    expected_fields = (
        "translate",
        "chain_eligible",
        "starts_article",
        "opens_article",
        "preserve_line_structure",
        "indent_eligible",
        "repair_profile",
    )
    fields = raw.get("fields")
    if not isinstance(fields, dict) or tuple(fields) != expected_fields:
        raise ManualValidationError("page policy fields are not canonical")
    base_keys = {
        "consumer",
        "runtime_event",
        "target_observable",
        "final_observable",
    }
    extension_keys = {"typeset_observable", "final_pdf_observable"}
    observables = {}
    for field_name, declaration in fields.items():
        if set(declaration) != base_keys | extension_keys or not all(
            isinstance(value, str) and value for value in declaration.values()
        ):
            raise ManualValidationError(
                f"page policy observable {field_name} is not a strict C20C extension"
            )
        observables[field_name] = {
            "typeset": declaration["typeset_observable"],
            "final_pdf": declaration["final_pdf_observable"],
        }
    taxonomy = load_taxonomy()
    resolved = {}
    for page_type in taxonomy.page_types:
        policy = dict(page_type.policy)
        if set(policy) != set(expected_fields) or policy["repair_profile"] is None:
            raise ManualValidationError(
                f"taxonomy page kind {page_type.name!r} has incomplete policy"
            )
        resolved[page_type.name] = policy
    if not resolved:
        raise ManualValidationError("page taxonomy is empty")
    return {
        "schema_version": raw["schema_version"],
        "owner": raw["owner"],
        "fields": fields,
        "observables": observables,
        "resolved_page_kinds": resolved,
    }


def resolve_page_policy(human_value: str) -> dict[str, Any]:
    config = load_page_policy_observables()
    if human_value in config["resolved_page_kinds"]:
        return dict(config["resolved_page_kinds"][human_value])
    try:
        decoded = json.loads(human_value)
    except json.JSONDecodeError as exc:
        raise ManualValidationError(f"unknown page kind {human_value!r}") from exc
    expected = set(config["observables"])
    if not isinstance(decoded, dict) or set(decoded) != expected:
        raise ManualValidationError("manual page policy value must contain every field")
    return decoded


def _evidence_ref(expectation_id: str, stage: str, material: Any) -> str:
    payload = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"manual:{expectation_id}:{stage}:{digest}"


def _stage_ready(expectation: ManualConstraintExpectation) -> bool:
    allowed = {ManualConstraintStatus.PASS, ManualConstraintStatus.NOT_APPLICABLE}
    return all(
        expectation.evidence_for(stage).status in allowed
        for stage in (ManualConstraintStage.DELIVERY, ManualConstraintStage.TARGET)
    )


def _base_holds(
    observation: ManualOccurrenceObservation,
    page_selection_map: PageSelectionMap,
) -> tuple[bool, list[str]]:
    reasons = []
    mapped = page_selection_map.output_index_of(observation.physical_page)
    if mapped is None or int(mapped) != observation.output_index:
        reasons.append("wrong_output_page")
    if observation.source_article_id != observation.article_id:
        reasons.append("wrong_article")
    boxes = observation.typeset_boxes + observation.final_glyph_boxes
    if observation.page_box is None or any(
        not _contains(observation.page_box, box) for box in boxes
    ):
        reasons.append("box_outside_page")
    if observation.target_region is None or any(
        not _contains(observation.target_region, box) for box in boxes
    ):
        reasons.append("box_outside_bound_region")
    return not reasons, reasons


def _protected_holds(observation: ManualOccurrenceObservation) -> tuple[bool, list[str]]:
    reasons = []
    if not observation.policy_rule_id.startswith("protected-fixed.v"):
        reasons.append("unknown_protected_fixed_rule")
    if (
        observation.source_fixed_asset_sha256 is None
        or observation.source_fixed_asset_sha256
        != observation.final_fixed_asset_sha256
    ):
        reasons.append("fixed_asset_fingerprint_changed")
    if not _box_close(
        observation.source_fixed_asset_box,
        observation.final_fixed_asset_box,
    ):
        reasons.append("fixed_asset_position_changed")
    if not observation.untouched:
        reasons.append("fixed_asset_untouched_evidence_missing")
    return not reasons, reasons


def _term_holds(
    expectation: ManualConstraintExpectation,
    observation: ManualOccurrenceObservation,
) -> tuple[bool, bool, list[str]]:
    reasons = []
    expected = normalize_manual_text(expectation.human_value)
    typeset = normalize_manual_text("".join(observation.typeset_text_fragments))
    final = normalize_manual_text(observation.final_text)
    typeset_holds = (
        bool(observation.typeset_fragment_refs)
        and len(observation.typeset_fragment_refs)
        == len(observation.typeset_text_fragments)
        and bool(observation.typeset_boxes)
        and typeset == expected
    )
    final_holds = bool(observation.final_glyph_boxes) and final == expected
    if not typeset_holds:
        reasons.append("typeset_term_mismatch")
    if not final_holds:
        reasons.append("final_term_mismatch")
    return typeset_holds, final_holds, reasons


def _page_policy_holds(
    expectation: ManualConstraintExpectation,
    observation: ManualOccurrenceObservation,
) -> tuple[bool, bool, list[str]]:
    resolve_page_policy(expectation.human_value)
    observables = load_page_policy_observables()["observables"]
    expected_typeset = {item["typeset"] for item in observables.values()}
    expected_final = {item["final_pdf"] for item in observables.values()}
    typeset_holds = (
        set(observation.typeset_observables) == expected_typeset
        and all(observation.typeset_observables.values())
    )
    final_holds = (
        set(observation.final_pdf_observables) == expected_final
        and all(observation.final_pdf_observables.values())
    )
    reasons = []
    if not typeset_holds:
        reasons.append("page_policy_typeset_observable_failed")
    if not final_holds:
        reasons.append("page_policy_final_observable_failed")
    return typeset_holds, final_holds, reasons


def _drop_cap_decision(human_value: str) -> str:
    try:
        decoded = json.loads(human_value)
    except json.JSONDecodeError:
        decoded = human_value
    if isinstance(decoded, dict):
        decoded = decoded.get("decision")
    if decoded not in {"keep", "flatten"}:
        raise ManualValidationError("drop-cap human value must decide keep or flatten")
    return str(decoded)


def _drop_cap_holds(
    expectation: ManualConstraintExpectation,
    observation: ManualOccurrenceObservation,
) -> tuple[bool, bool, list[str]]:
    decision = _drop_cap_decision(expectation.human_value)
    shared_typeset = {
        "drop_cap_owner_matches",
        "drop_cap_first_character_matches",
        "drop_cap_layout_generation_matches",
        "drop_cap_geometry_legal",
        f"drop_cap_{decision}_style_geometry",
    }
    shared_final = {
        "drop_cap_owner_matches",
        "drop_cap_occurs_once",
        "drop_cap_first_character_matches",
        "drop_cap_geometry_legal",
        f"drop_cap_{decision}_style_geometry",
    }
    character_holds = (
        observation.drop_cap_character is not None
        and len(observation.drop_cap_character) == 1
    )
    language_holds = observation.drop_cap_language in {"en", "zh"}
    typeset_holds = (
        character_holds
        and language_holds
        and set(observation.typeset_observables) == shared_typeset
        and all(observation.typeset_observables.values())
    )
    final_holds = (
        character_holds
        and language_holds
        and set(observation.final_pdf_observables) == shared_final
        and all(observation.final_pdf_observables.values())
    )
    reasons = []
    if not typeset_holds:
        reasons.append("drop_cap_typeset_observable_failed")
    if not final_holds:
        reasons.append("drop_cap_final_observable_failed")
    return typeset_holds, final_holds, reasons


def bind_final_pdf_observations(
    output_document,
    page_selection_map: PageSelectionMap,
    observations: tuple[ManualOccurrenceObservation, ...],
) -> tuple[ManualOccurrenceObservation, ...]:
    """Replace claimed final text/boxes with extraction from the bound region."""

    import pymupdf

    bound = []
    for observation in observations:
        if observation.target_region is None:
            bound.append(observation)
            continue
        output_index = page_selection_map.output_index_of(observation.physical_page)
        if (
            output_index is None
            or int(output_index) != observation.output_index
            or not 0 <= observation.output_index < len(output_document)
        ):
            bound.append(replace(observation, final_text="", final_glyph_boxes=()))
            continue
        page = output_document[observation.output_index]
        clip = pymupdf.Rect(observation.target_region)
        raw = page.get_text("rawdict", clip=clip)
        characters = []
        boxes = []
        for block in raw.get("blocks", ()):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", ()):
                for span in line.get("spans", ()):
                    for character in span.get("chars", ()):
                        characters.append(character.get("c", ""))
                        if character.get("bbox") is not None:
                            boxes.append(tuple(float(value) for value in character["bbox"]))
        final_observables = dict(observation.final_pdf_observables)
        if observation.drop_cap_character is not None:
            normalized = normalize_manual_text("".join(characters))
            final_observables["drop_cap_occurs_once"] = (
                normalized.count(observation.drop_cap_character) == 1
            )
            final_observables["drop_cap_first_character_matches"] = (
                normalized.startswith(observation.drop_cap_character)
            )
            final_observables["drop_cap_geometry_legal"] = bool(boxes) and all(
                _contains(observation.target_region, box) for box in boxes
            )
        bound.append(
            replace(
                observation,
                final_text="".join(characters),
                final_glyph_boxes=tuple(boxes),
                page_box=tuple(float(value) for value in page.cropbox),
                final_pdf_observables=final_observables,
            )
        )
    return tuple(bound)


def evaluate_manual_constraints(
    expectations: tuple[ManualConstraintExpectation, ...],
    observations: tuple[ManualOccurrenceObservation, ...],
    page_selection_map: PageSelectionMap,
    *,
    scope: ValidationScope | str = ValidationScope.FULL_TRANSLATION,
) -> ManualValidationResult:
    """Evaluate occurrence-bound typeset/final evidence without output-derived truth."""

    scope = ValidationScope(scope)
    if scope is ValidationScope.PARSE_ONLY:
        updated = []
        for expectation in expectations:
            updates = {
                stage: (
                    ManualConstraintStatus.NOT_EXERCISED,
                    (f"scope:parse_only:{stage.value}",),
                )
                for stage in ManualConstraintStage
            }
            updated.append(expectation.with_stage_updates(updates))
        return ManualValidationResult(
            scope=scope,
            status="parse_gate_pass",
            expectations=tuple(updated),
            issues=(),
            evidence=(),
        )

    counts = Counter(item.occurrence_ref for item in observations)
    indexed = {item.occurrence_ref: item for item in observations}
    selected_union = {
        reference
        for expectation in expectations
        for reference in expectation.selected_occurrence_refs
    }
    issues: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for reference, count in sorted(counts.items()):
        if count != 1:
            issues.append(
                {"code": "manual_occurrence_duplicate", "occurrence_ref": reference}
            )
        if reference not in selected_union:
            issues.append(
                {"code": "manual_occurrence_unexpected", "occurrence_ref": reference}
            )

    updated = []
    for expectation in expectations:
        selected = expectation.selected_occurrence_refs
        if not selected:
            refs = (f"manual:{expectation.expectation_id}:not_selected",)
            updated.append(
                expectation.with_stage_updates(
                    {
                        ManualConstraintStage.TYPESET: (
                            ManualConstraintStatus.NOT_SELECTED,
                            refs,
                        ),
                        ManualConstraintStage.FINAL_PDF: (
                            ManualConstraintStatus.NOT_SELECTED,
                            refs,
                        ),
                    }
                )
            )
            continue
        missing = [reference for reference in selected if counts[reference] != 1]
        prerequisite = _stage_ready(expectation)
        typeset_all = prerequisite and not missing
        final_all = prerequisite and not missing
        protected_count = 0
        expectation_evidence = []
        for reference in selected:
            observation = indexed.get(reference)
            if observation is None or counts[reference] != 1:
                issues.append(
                    {
                        "code": "manual_occurrence_missing",
                        "expectation_id": expectation.expectation_id,
                        "occurrence_ref": reference,
                    }
                )
                continue
            base_holds, reasons = _base_holds(observation, page_selection_map)
            if observation.eligibility is TranslationEligibility.PROTECTED_FIXED:
                protected_count += 1
                occurrence_holds, protected_reasons = _protected_holds(observation)
                typeset_holds = final_holds = base_holds and occurrence_holds
                reasons.extend(protected_reasons)
            elif expectation.kind is ManualConstraintKind.TERM:
                typeset_holds, final_holds, kind_reasons = _term_holds(
                    expectation, observation
                )
                typeset_holds = base_holds and typeset_holds
                final_holds = base_holds and final_holds
                reasons.extend(kind_reasons)
            elif expectation.kind is ManualConstraintKind.PAGE_POLICY:
                typeset_holds, final_holds, kind_reasons = _page_policy_holds(
                    expectation, observation
                )
                typeset_holds = base_holds and typeset_holds
                final_holds = base_holds and final_holds
                reasons.extend(kind_reasons)
            elif expectation.kind is ManualConstraintKind.DROP_CAP:
                typeset_holds, final_holds, kind_reasons = _drop_cap_holds(
                    expectation, observation
                )
                typeset_holds = base_holds and typeset_holds
                final_holds = base_holds and final_holds
                reasons.extend(kind_reasons)
            else:  # pragma: no cover - canonical enum already prevents this.
                typeset_holds = final_holds = False
                reasons.append("unknown_manual_kind")
            typeset_all = typeset_all and typeset_holds
            final_all = final_all and final_holds
            row = {
                "expectation_id": expectation.expectation_id,
                "occurrence_ref": reference,
                "physical_page": observation.physical_page,
                "output_index": observation.output_index,
                "article_id": observation.article_id,
                "eligibility": observation.eligibility.value,
                "policy_rule_id": observation.policy_rule_id,
                "typeset_holds": typeset_holds,
                "final_pdf_holds": final_holds,
                "reasons": sorted(set(reasons)),
            }
            expectation_evidence.append(row)
            evidence.append(row)
            for reason in sorted(set(reasons)):
                issues.append(
                    {
                        "code": reason,
                        "expectation_id": expectation.expectation_id,
                        "occurrence_ref": reference,
                    }
                )
        if not prerequisite:
            issues.append(
                {
                    "code": "manual_delivery_target_prerequisite_failed",
                    "expectation_id": expectation.expectation_id,
                }
            )
        material = {
            "schema_version": SCHEMA_VERSION,
            "expectation_id": expectation.expectation_id,
            "evidence": expectation_evidence,
        }
        typeset_ref = _evidence_ref(expectation.expectation_id, "typeset", material)
        final_ref = _evidence_ref(expectation.expectation_id, "final_pdf", material)
        all_protected = protected_count == len(selected)
        typeset_status = (
            ManualConstraintStatus.NOT_APPLICABLE
            if all_protected and typeset_all
            else ManualConstraintStatus.PASS
            if typeset_all
            else ManualConstraintStatus.FAIL
        )
        final_status = (
            ManualConstraintStatus.NOT_APPLICABLE
            if all_protected and final_all
            else ManualConstraintStatus.PASS
            if final_all
            else ManualConstraintStatus.FAIL
        )
        updated.append(
            expectation.with_stage_updates(
                {
                    ManualConstraintStage.TYPESET: (
                        typeset_status,
                        (typeset_ref,),
                    ),
                    ManualConstraintStage.FINAL_PDF: (
                        final_status,
                        (final_ref,),
                    ),
                }
            )
        )

    final_statuses = {
        item.evidence_for(ManualConstraintStage.FINAL_PDF).status
        for item in updated
    }
    invalid_final = final_statuses & {
        ManualConstraintStatus.FAIL,
        ManualConstraintStatus.PENDING,
        ManualConstraintStatus.NOT_EXERCISED,
    }
    status = "fail" if issues or invalid_final else "pass"
    return ManualValidationResult(
        scope=scope,
        status=status,
        expectations=tuple(updated),
        issues=tuple(issues),
        evidence=tuple(evidence),
    )


__all__ = [
    "ManualOccurrenceObservation",
    "ManualValidationError",
    "ManualValidationResult",
    "NORMALIZATION_VERSION",
    "SCHEMA_VERSION",
    "TranslationEligibility",
    "ValidationScope",
    "bind_final_pdf_observations",
    "evaluate_manual_constraints",
    "load_page_policy_observables",
    "normalize_manual_text",
    "resolve_page_policy",
]
