"""Deterministic monotonic acceptance for layout and repair transactions."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("repair_acceptance.json")

POLICY_TYPED_LEXICOGRAPHIC = "typed_lexicographic"


class AcceptanceConfigError(ValueError):
    """Raised when the acceptance policy cannot be interpreted safely."""


@dataclass(frozen=True, slots=True)
class MetricVector:
    schema_version: str
    severity: str
    dimensions: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class MeasuredIssue:
    """A non-detector objective or guard expressed in the issue contract."""

    issue_id: str
    kind: str
    severity: str
    evidence: dict
    severity_vector: MetricVector

    @property
    def id(self) -> str:
        return self.issue_id


def measured_issue(
    issue_id: str,
    kind: str,
    severity: str,
    evidence: dict,
    fields,
    *,
    schema_version: str = "1",
) -> MeasuredIssue:
    return MeasuredIssue(
        issue_id=issue_id,
        kind=kind,
        severity=severity,
        evidence=dict(evidence),
        severity_vector=MetricVector(
            schema_version,
            severity,
            tuple((name, evidence.get(name)) for name in fields),
        ),
    )


@dataclass(frozen=True, slots=True)
class AcceptancePolicy:
    schema_version: str
    policy: str
    severity_order: tuple[str, ...]
    reject_new_at_or_above: str
    require_total_nonincrease: bool
    require_kind_nonincrease: bool
    require_persistent_nonworsening: bool
    require_strict_improvement: bool

    def rank(self, severity: str) -> int:
        try:
            return self.severity_order.index(severity)
        except ValueError as error:
            raise AcceptanceConfigError(
                f"severity {severity!r} is outside {list(self.severity_order)}"
            ) from error

    @property
    def rejection_rank(self) -> int:
        return self.rank(self.reject_new_at_or_above)

    def as_record(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "policy": self.policy,
            "severity_order": list(self.severity_order),
            "reject_new_at_or_above": self.reject_new_at_or_above,
            "require_total_nonincrease": self.require_total_nonincrease,
            "require_kind_nonincrease": self.require_kind_nonincrease,
            "require_persistent_nonworsening": (
                self.require_persistent_nonworsening
            ),
            "require_strict_improvement": self.require_strict_improvement,
        }


def parse_acceptance_policy(raw: object, source: str) -> AcceptancePolicy:
    if not isinstance(raw, dict):
        raise AcceptanceConfigError(f"{source}: root must be an object")
    schema_version = raw.get("schema_version")
    policy = raw.get("policy")
    severity_order = raw.get("severity_order")
    rejection = raw.get("reject_new_at_or_above")
    if not isinstance(schema_version, str) or not schema_version:
        raise AcceptanceConfigError(f"{source}: schema_version must be a string")
    if policy != POLICY_TYPED_LEXICOGRAPHIC:
        raise AcceptanceConfigError(
            f"{source}: policy must be {POLICY_TYPED_LEXICOGRAPHIC!r}"
        )
    if (
        not isinstance(severity_order, list)
        or not severity_order
        or not all(isinstance(item, str) and item for item in severity_order)
        or len(set(severity_order)) != len(severity_order)
    ):
        raise AcceptanceConfigError(
            f"{source}: severity_order must contain unique strings"
        )
    if rejection not in severity_order:
        raise AcceptanceConfigError(
            f"{source}: reject_new_at_or_above is outside severity_order"
        )
    flags = (
        "require_total_nonincrease",
        "require_kind_nonincrease",
        "require_persistent_nonworsening",
        "require_strict_improvement",
    )
    for name in flags:
        if not isinstance(raw.get(name), bool):
            raise AcceptanceConfigError(f"{source}: {name} must be boolean")
    return AcceptancePolicy(
        schema_version=schema_version,
        policy=policy,
        severity_order=tuple(severity_order),
        reject_new_at_or_above=str(rejection),
        require_total_nonincrease=raw["require_total_nonincrease"],
        require_kind_nonincrease=raw["require_kind_nonincrease"],
        require_persistent_nonworsening=raw[
            "require_persistent_nonworsening"
        ],
        require_strict_improvement=raw["require_strict_improvement"],
    )


@lru_cache(maxsize=2)
def load_acceptance_policy(path: str | None = None) -> AcceptancePolicy:
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as stream:
        raw = json.load(stream)
    return parse_acceptance_policy(raw, config_path.name)


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    accepted: bool
    policy: str
    before_total: int
    after_total: int
    before_by_kind: dict[str, int]
    after_by_kind: dict[str, int]
    resolved_ids: tuple[str, ...]
    new_ids: tuple[str, ...]
    new_high_severity_ids: tuple[str, ...]
    worsened_ids: tuple[str, ...]
    uncomparable_ids: tuple[str, ...]
    improved_ids: tuple[str, ...]
    strict_improvement: bool
    reasons: tuple[str, ...]

    def as_record(self) -> dict:
        return {
            "accepted": self.accepted,
            "policy": self.policy,
            "before": {
                "total": self.before_total,
                "by_kind": dict(self.before_by_kind),
            },
            "after": {
                "total": self.after_total,
                "by_kind": dict(self.after_by_kind),
            },
            "resolved_ids": list(self.resolved_ids),
            "new_ids": list(self.new_ids),
            "new_high_severity_ids": list(self.new_high_severity_ids),
            "worsened_ids": list(self.worsened_ids),
            "uncomparable_ids": list(self.uncomparable_ids),
            "improved_ids": list(self.improved_ids),
            "strict_improvement": self.strict_improvement,
            "reasons": list(self.reasons),
        }


def _index(issues) -> tuple[dict[str, object], tuple[str, ...]]:
    indexed: dict[str, object] = {}
    duplicates = []
    for issue in issues:
        if issue.id in indexed:
            duplicates.append(issue.id)
        indexed[issue.id] = issue
    return indexed, tuple(sorted(set(duplicates)))


def _vector(issue) -> MetricVector:
    vector = issue.severity_vector
    if vector is None:
        return MetricVector("1", issue.severity, ())
    return vector


def _compare_persistent(
    before, after, policy: AcceptancePolicy
) -> tuple[str, bool]:
    if before.kind != after.kind:
        return "uncomparable", False
    before_vector = _vector(before)
    after_vector = _vector(after)
    if (
        before_vector.schema_version != policy.schema_version
        or after_vector.schema_version != policy.schema_version
        or before_vector.severity != before.severity
        or after_vector.severity != after.severity
    ):
        return "uncomparable", False
    if (
        len({name for name, _value in before_vector.dimensions})
        != len(before_vector.dimensions)
        or len({name for name, _value in after_vector.dimensions})
        != len(after_vector.dimensions)
    ):
        return "uncomparable", False
    before_metrics = dict(before_vector.dimensions)
    after_metrics = dict(after_vector.dimensions)
    if before_metrics.keys() != after_metrics.keys():
        return "uncomparable", False
    improved = False
    if policy.rank(after.severity) > policy.rank(before.severity):
        return "worsened", False
    if policy.rank(after.severity) < policy.rank(before.severity):
        improved = True
    for name in before_metrics:
        left = before_metrics[name]
        right = after_metrics[name]
        if isinstance(left, bool) or isinstance(right, bool):
            return "uncomparable", False
        if not isinstance(left, int | float) or not isinstance(right, int | float):
            return "uncomparable", False
        if not math.isfinite(left) or not math.isfinite(right):
            return "uncomparable", False
        if right > left:
            return "worsened", False
        if right < left:
            improved = True
    return "improved" if improved else "unchanged", improved


def compare_issues(
    before,
    after,
    policy: AcceptancePolicy,
) -> AcceptanceResult:
    """Compare two issue collections without reading or mutating external state."""
    before = tuple(before)
    after = tuple(after)
    before_index, before_duplicates = _index(before)
    after_index, after_duplicates = _index(after)
    before_by_kind = dict(sorted(Counter(item.kind for item in before).items()))
    after_by_kind = dict(sorted(Counter(item.kind for item in after).items()))
    before_ids = set(before_index)
    after_ids = set(after_index)
    resolved = tuple(sorted(before_ids - after_ids))
    new = tuple(sorted(after_ids - before_ids))
    new_high = tuple(
        issue_id
        for issue_id in new
        if policy.rank(after_index[issue_id].severity) >= policy.rejection_rank
    )
    worsened = []
    uncomparable = []
    improved = []
    for issue_id in sorted(before_ids & after_ids):
        verdict, changed = _compare_persistent(
            before_index[issue_id], after_index[issue_id], policy
        )
        if verdict == "worsened":
            worsened.append(issue_id)
        elif verdict == "uncomparable":
            uncomparable.append(issue_id)
        elif changed:
            improved.append(issue_id)

    total_increased = len(after_index) > len(before_index)
    kinds_increased = tuple(
        kind
        for kind in sorted(set(before_by_kind) | set(after_by_kind))
        if after_by_kind.get(kind, 0) > before_by_kind.get(kind, 0)
    )
    strict = bool(
        len(after_index) < len(before_index)
        or any(
            after_by_kind.get(kind, 0) < before_by_kind.get(kind, 0)
            for kind in set(before_by_kind) | set(after_by_kind)
        )
        or improved
    )
    reasons = []
    duplicates = tuple(sorted(set(before_duplicates) | set(after_duplicates)))
    if duplicates:
        reasons.append(f"duplicate_issue_ids:{','.join(duplicates)}")
    if policy.require_total_nonincrease and total_increased:
        reasons.append("total_issue_count_increased")
    if policy.require_kind_nonincrease and kinds_increased:
        reasons.append(f"issue_kind_count_increased:{','.join(kinds_increased)}")
    if new_high:
        reasons.append("new_high_severity_issue")
    if policy.require_persistent_nonworsening and worsened:
        reasons.append("persistent_issue_severity_worsened")
    if policy.require_persistent_nonworsening and uncomparable:
        reasons.append("persistent_issue_severity_uncomparable")
    if policy.require_strict_improvement and not strict:
        reasons.append("no_strict_improvement")
    return AcceptanceResult(
        accepted=not reasons,
        policy=policy.policy,
        before_total=len(before_index),
        after_total=len(after_index),
        before_by_kind=before_by_kind,
        after_by_kind=after_by_kind,
        resolved_ids=resolved,
        new_ids=new,
        new_high_severity_ids=new_high,
        worsened_ids=tuple(worsened),
        uncomparable_ids=tuple(uncomparable),
        improved_ids=tuple(improved),
        strict_improvement=strict,
        reasons=tuple(reasons),
    )
