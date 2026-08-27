"""Atomic validation and commit for semantic geometry updates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

BoxTuple = tuple[float, float, float, float]


class GeometryRole(str, Enum):
    PROCESSABLE_TEXT = "processable_text"
    MARKER = "marker"
    PASSTHROUGH = "passthrough"


@dataclass(frozen=True, slots=True)
class GeometryWriteRefusalError(ValueError):
    stage: str
    source_page: int
    stable_ref: str
    role: GeometryRole
    before: BoxTuple
    candidate: BoxTuple
    reason: str

    def __str__(self) -> str:
        return (
            f"geometry_write_refused stage={self.stage} source_page={self.source_page} "
            f"stable_ref={self.stable_ref} role={self.role.value} "
            f"before={self.before} candidate={self.candidate} reason={self.reason}"
        )


@dataclass(frozen=True, slots=True)
class GeometryWriteResult:
    committed: bool
    refusal: GeometryWriteRefusalError | None = None


def _tuple(value) -> BoxTuple:
    if isinstance(value, (tuple, list)):
        values = value
    else:
        values = [getattr(value, name, None) for name in ("x", "y", "x2", "y2")]
    if len(values) != 4 or any(item is None for item in values):
        raise ValueError("geometry box must contain four coordinates")
    return tuple(float(item) for item in values)  # type: ignore[return-value]


def _reason(candidate: BoxTuple, bounds: BoxTuple, role: GeometryRole) -> str | None:
    if not all(math.isfinite(item) for item in candidate):
        return "candidate coordinates are not finite"
    if candidate[0] > candidate[2] or candidate[1] > candidate[3]:
        return "candidate coordinates are reversed"
    if role == GeometryRole.PROCESSABLE_TEXT and (
        candidate[0] == candidate[2] or candidate[1] == candidate[3]
    ):
        return "processable text requires positive area"
    if not (
        bounds[0] <= candidate[0] <= candidate[2] <= bounds[2]
        and bounds[1] <= candidate[1] <= candidate[3] <= bounds[3]
    ):
        return "candidate is outside page bounds"
    return None


def propose_box_updates(
    proposals,
    *,
    page_bounds,
    stage: str,
    source_page: int,
) -> GeometryWriteResult:
    """Validate all candidates, then commit all of them or none of them."""
    bounds = _tuple(page_bounds)
    normalized = []
    for target, candidate, stable_ref, role in proposals:
        role = GeometryRole(role)
        before = _tuple(target)
        wanted = _tuple(candidate)
        reason = _reason(wanted, bounds, role)
        if reason is not None:
            return GeometryWriteResult(
                committed=False,
                refusal=GeometryWriteRefusalError(
                    stage=stage,
                    source_page=source_page,
                    stable_ref=str(stable_ref),
                    role=role,
                    before=before,
                    candidate=wanted,
                    reason=reason,
                ),
            )
        normalized.append((target, wanted))
    for target, wanted in normalized:
        target.x, target.y, target.x2, target.y2 = wanted
    return GeometryWriteResult(committed=True)


def propose_box_update(
    target,
    candidate,
    *,
    page_bounds,
    stage: str,
    source_page: int,
    stable_ref: str,
    role: GeometryRole = GeometryRole.PROCESSABLE_TEXT,
) -> GeometryWriteResult:
    return propose_box_updates(
        ((target, candidate, stable_ref, role),),
        page_bounds=page_bounds,
        stage=stage,
        source_page=source_page,
    )
