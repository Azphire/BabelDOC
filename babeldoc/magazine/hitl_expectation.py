"""Canonical protocol for source-bound manual HITL expectations.

This module owns the data contract only. It deliberately does not bind review
decisions, mutate ArticleIR, apply translations, or inspect rendered output.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Final

MANUAL_EXPECTATION_SCHEMA_VERSION: Final = "babeldoc.manual-constraint-expectation.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STAGE_ORDER: Final = ("delivery", "target", "typeset", "final_pdf")
_EXPECTATION_KEYS: Final = frozenset(
    {
        "schema_version",
        "expectation_id",
        "kind",
        "human_value",
        "source_occurrence_refs",
        "selected_occurrence_refs",
        "source_binding_sha256",
        "stage_evidence",
    }
)
_EVIDENCE_KEYS: Final = frozenset({"stage", "status", "evidence_refs"})


class ManualExpectationProtocolError(ValueError):
    """Raised when a manual expectation violates the canonical protocol."""


class ManualConstraintKind(str, Enum):
    """Closed vocabulary for manual constraint kinds."""

    TERM = "term"
    PAGE_POLICY = "page_policy"
    DROP_CAP = "drop_cap"


class ManualConstraintStage(str, Enum):
    """Closed vocabulary for evidence-producing pipeline stages."""

    DELIVERY = "delivery"
    TARGET = "target"
    TYPESET = "typeset"
    FINAL_PDF = "final_pdf"


class ManualConstraintStatus(str, Enum):
    """Closed vocabulary for a stage's verification state."""

    PENDING = "pending"
    PASS = "pass"  # noqa: S105 - closed status token, not a credential.
    FAIL = "fail"
    NOT_EXERCISED = "not_exercised"
    NOT_SELECTED = "not_selected"
    NOT_APPLICABLE = "not_applicable"


def _strict_keys(
    record: Mapping[str, Any],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    actual = frozenset(record)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        parts: list[str] = []
        if missing:
            parts.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(unknown)}")
        raise ManualExpectationProtocolError(f"{label}: {'; '.join(parts)}")


def _non_empty_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ManualExpectationProtocolError(
            f"{label} must be a non-empty, whitespace-trimmed string"
        )
    if any(ord(character) < 0x20 for character in value):
        raise ManualExpectationProtocolError(
            f"{label} must not contain control characters"
        )
    return value


def _canonical_refs(
    values: tuple[str, ...],
    *,
    label: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ManualExpectationProtocolError(f"{label} must be a tuple")
    cleaned = tuple(_non_empty_string(value, label=f"{label} item") for value in values)
    if not allow_empty and not cleaned:
        raise ManualExpectationProtocolError(f"{label} must not be empty")
    if len(set(cleaned)) != len(cleaned):
        raise ManualExpectationProtocolError(f"{label} must contain unique refs")
    return tuple(sorted(cleaned))


@dataclass(frozen=True, slots=True)
class ManualConstraintEvidence:
    """Immutable evidence state for one manual-constraint stage."""

    stage: ManualConstraintStage
    status: ManualConstraintStatus
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            stage = ManualConstraintStage(self.stage)
        except (TypeError, ValueError) as exc:
            raise ManualExpectationProtocolError(
                f"unknown manual constraint stage: {self.stage!r}"
            ) from exc
        try:
            status = ManualConstraintStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ManualExpectationProtocolError(
                f"unknown manual constraint status: {self.status!r}"
            ) from exc
        refs = _canonical_refs(
            self.evidence_refs,
            label=f"{stage.value} evidence_refs",
            allow_empty=True,
        )
        if status is ManualConstraintStatus.PENDING and refs:
            raise ManualExpectationProtocolError(
                f"{stage.value} pending status cannot carry evidence refs"
            )
        if status is not ManualConstraintStatus.PENDING and not refs:
            raise ManualExpectationProtocolError(
                f"{stage.value} {status.value} status requires evidence refs"
            )
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "evidence_refs", refs)

    def to_record(self) -> dict[str, Any]:
        """Return the strict JSON-compatible evidence record."""

        return {
            "evidence_refs": list(self.evidence_refs),
            "stage": self.stage.value,
            "status": self.status.value,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ManualConstraintEvidence:
        """Parse one evidence record, rejecting missing and unknown fields."""

        if not isinstance(record, Mapping):
            raise ManualExpectationProtocolError(
                "stage_evidence item must be an object"
            )
        _strict_keys(record, _EVIDENCE_KEYS, label="stage_evidence item")
        refs = record["evidence_refs"]
        if not isinstance(refs, list) or not all(
            isinstance(value, str) for value in refs
        ):
            raise ManualExpectationProtocolError(
                "stage_evidence evidence_refs must be an array of strings"
            )
        return cls(
            stage=record["stage"],
            status=record["status"],
            evidence_refs=tuple(refs),
        )


@dataclass(frozen=True, slots=True)
class ManualConstraintExpectation:
    """Sole canonical, source-bound representation of one manual expectation."""

    expectation_id: str
    kind: ManualConstraintKind
    human_value: str
    source_occurrence_refs: tuple[str, ...]
    selected_occurrence_refs: tuple[str, ...]
    source_binding_sha256: str
    stage_evidence: tuple[ManualConstraintEvidence, ...]
    schema_version: str = MANUAL_EXPECTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MANUAL_EXPECTATION_SCHEMA_VERSION:
            raise ManualExpectationProtocolError(
                "unsupported manual expectation schema_version: "
                f"{self.schema_version!r}"
            )
        expectation_id = _non_empty_string(self.expectation_id, label="expectation_id")
        try:
            kind = ManualConstraintKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ManualExpectationProtocolError(
                f"unknown manual constraint kind: {self.kind!r}"
            ) from exc
        human_value = _non_empty_string(self.human_value, label="human_value")
        source_refs = _canonical_refs(
            self.source_occurrence_refs,
            label="source_occurrence_refs",
            allow_empty=False,
        )
        selected_refs = _canonical_refs(
            self.selected_occurrence_refs,
            label="selected_occurrence_refs",
            allow_empty=True,
        )
        if not set(selected_refs).issubset(source_refs):
            raise ManualExpectationProtocolError(
                "selected_occurrence_refs must be a subset of source_occurrence_refs"
            )
        if not isinstance(self.source_binding_sha256, str) or not _SHA256_RE.fullmatch(
            self.source_binding_sha256
        ):
            raise ManualExpectationProtocolError(
                "source_binding_sha256 must be 64 lowercase hexadecimal characters"
            )
        if not isinstance(self.stage_evidence, tuple):
            raise ManualExpectationProtocolError("stage_evidence must be a tuple")
        if not all(
            isinstance(item, ManualConstraintEvidence) for item in self.stage_evidence
        ):
            raise ManualExpectationProtocolError(
                "stage_evidence must contain ManualConstraintEvidence items"
            )
        stages = tuple(item.stage.value for item in self.stage_evidence)
        if stages != _STAGE_ORDER:
            raise ManualExpectationProtocolError(
                "stage_evidence must contain delivery, target, typeset, and "
                "final_pdf exactly once in canonical order"
            )
        object.__setattr__(self, "expectation_id", expectation_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "human_value", human_value)
        object.__setattr__(self, "source_occurrence_refs", source_refs)
        object.__setattr__(self, "selected_occurrence_refs", selected_refs)

    def to_record(self) -> dict[str, Any]:
        """Return the strict JSON-compatible expectation record."""

        return {
            "expectation_id": self.expectation_id,
            "human_value": self.human_value,
            "kind": self.kind.value,
            "schema_version": self.schema_version,
            "selected_occurrence_refs": list(self.selected_occurrence_refs),
            "source_binding_sha256": self.source_binding_sha256,
            "source_occurrence_refs": list(self.source_occurrence_refs),
            "stage_evidence": [item.to_record() for item in self.stage_evidence],
        }

    def to_json_bytes(self) -> bytes:
        """Serialize with stable UTF-8 bytes and a final newline."""

        return (
            json.dumps(
                self.to_record(),
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            )
            + "\n"
        ).encode("utf-8")

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ManualConstraintExpectation:
        """Parse one expectation, rejecting missing and unknown fields."""

        if not isinstance(record, Mapping):
            raise ManualExpectationProtocolError(
                "manual expectation record must be an object"
            )
        _strict_keys(record, _EXPECTATION_KEYS, label="manual expectation")
        source_refs = record["source_occurrence_refs"]
        selected_refs = record["selected_occurrence_refs"]
        evidence = record["stage_evidence"]
        if not isinstance(source_refs, list) or not all(
            isinstance(value, str) for value in source_refs
        ):
            raise ManualExpectationProtocolError(
                "source_occurrence_refs must be an array of strings"
            )
        if not isinstance(selected_refs, list) or not all(
            isinstance(value, str) for value in selected_refs
        ):
            raise ManualExpectationProtocolError(
                "selected_occurrence_refs must be an array of strings"
            )
        if not isinstance(evidence, list):
            raise ManualExpectationProtocolError("stage_evidence must be an array")
        return cls(
            schema_version=record["schema_version"],
            expectation_id=record["expectation_id"],
            kind=record["kind"],
            human_value=record["human_value"],
            source_occurrence_refs=tuple(source_refs),
            selected_occurrence_refs=tuple(selected_refs),
            source_binding_sha256=record["source_binding_sha256"],
            stage_evidence=tuple(
                ManualConstraintEvidence.from_record(item) for item in evidence
            ),
        )

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> ManualConstraintExpectation:
        """Decode one canonical record with duplicate-key rejection."""

        def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ManualExpectationProtocolError(f"duplicate JSON field: {key}")
                result[key] = value
            return result

        def reject_constant(value: str) -> None:
            raise ManualExpectationProtocolError(
                f"non-finite JSON value is not allowed: {value}"
            )

        try:
            decoded = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=reject_pairs,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManualExpectationProtocolError(
                "manual expectation payload must be valid UTF-8 JSON"
            ) from exc
        return cls.from_record(decoded)


def pending_stage_evidence() -> tuple[ManualConstraintEvidence, ...]:
    """Return the canonical initial evidence state for all four stages."""

    return tuple(
        ManualConstraintEvidence(
            stage=ManualConstraintStage(stage),
            status=ManualConstraintStatus.PENDING,
        )
        for stage in _STAGE_ORDER
    )


def manual_constraint_expectation_schema() -> dict[str, Any]:
    """Return the closed JSON Schema for one expectation record."""

    def evidence_schema(stage: str) -> dict[str, Any]:
        return {
            "additionalProperties": False,
            "allOf": [
                {
                    "else": {"properties": {"evidence_refs": {"minItems": 1}}},
                    "if": {"properties": {"status": {"const": "pending"}}},
                    "then": {"properties": {"evidence_refs": {"maxItems": 0}}},
                }
            ],
            "properties": {
                "evidence_refs": {
                    "items": {"minLength": 1, "type": "string"},
                    "type": "array",
                    "uniqueItems": True,
                },
                "stage": {"const": stage, "type": "string"},
                "status": {
                    "enum": [item.value for item in ManualConstraintStatus],
                    "type": "string",
                },
            },
            "required": sorted(_EVIDENCE_KEYS),
            "type": "object",
        }

    return {
        "$id": MANUAL_EXPECTATION_SCHEMA_VERSION,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "expectation_id": {"minLength": 1, "type": "string"},
            "human_value": {"minLength": 1, "type": "string"},
            "kind": {
                "enum": [item.value for item in ManualConstraintKind],
                "type": "string",
            },
            "schema_version": {
                "const": MANUAL_EXPECTATION_SCHEMA_VERSION,
                "type": "string",
            },
            "selected_occurrence_refs": {
                "items": {"minLength": 1, "type": "string"},
                "type": "array",
                "uniqueItems": True,
            },
            "source_binding_sha256": {
                "pattern": "^[0-9a-f]{64}$",
                "type": "string",
            },
            "source_occurrence_refs": {
                "items": {"minLength": 1, "type": "string"},
                "minItems": 1,
                "type": "array",
                "uniqueItems": True,
            },
            "stage_evidence": {
                "items": False,
                "maxItems": 4,
                "minItems": 4,
                "prefixItems": [evidence_schema(stage) for stage in _STAGE_ORDER],
                "type": "array",
            },
        },
        "required": sorted(_EXPECTATION_KEYS),
        "type": "object",
    }


__all__ = [
    "MANUAL_EXPECTATION_SCHEMA_VERSION",
    "ManualConstraintEvidence",
    "ManualConstraintExpectation",
    "ManualConstraintKind",
    "ManualConstraintStage",
    "ManualConstraintStatus",
    "ManualExpectationProtocolError",
    "manual_constraint_expectation_schema",
    "pending_stage_evidence",
]
