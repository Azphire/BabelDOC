"""Typed detector evidence contract for later drop-cap geometry passes."""

from __future__ import annotations

from dataclasses import dataclass

from babeldoc.magazine.run_trace import parse_source_ref

BoxTuple = tuple[float, float, float, float]
SCHEMA_VERSION = "drop-cap-geometry.v1"


@dataclass(frozen=True, slots=True)
class BoxEvidence:
    box: BoxTuple
    source: str

    def __post_init__(self) -> None:
        if len(self.box) != 4 or self.box[0] > self.box[2] or self.box[1] > self.box[3]:
            raise ValueError("drop-cap evidence boxes must contain ordered coordinates")
        if not self.source:
            raise ValueError("drop-cap box evidence requires a source")

    def to_record(self) -> dict:
        return {"box": list(self.box), "source": self.source}


@dataclass(frozen=True, slots=True)
class ColorEvidence:
    fill: str | None
    stroke: str | None
    contrast_ratio: float | None

    def __post_init__(self) -> None:
        if self.contrast_ratio is not None and self.contrast_ratio < 0:
            raise ValueError("drop-cap contrast ratio must be non-negative")

    def to_record(self) -> dict:
        return {
            "fill": self.fill,
            "stroke": self.stroke,
            "contrast_ratio": self.contrast_ratio,
        }


@dataclass(frozen=True, slots=True)
class DropCapGeometryContract:
    source_ref: str
    page: int
    article_id: str | None
    character_count: int | None
    policy: str | None
    ink: BoxEvidence | None
    reserve: BoxEvidence | None
    collision: tuple[BoxEvidence, ...] | None
    color: ColorEvidence | None

    def __post_init__(self) -> None:
        page, _index = parse_source_ref(self.source_ref)
        if page != self.page:
            raise ValueError("drop-cap source ref must agree with its page")
        if self.character_count is not None and self.character_count < 0:
            raise ValueError("drop-cap character count must be non-negative")

    def missing_fields(self) -> tuple[str, ...]:
        values = {
            "character_count": self.character_count,
            "policy": self.policy,
            "ink": self.ink,
            "reserve": self.reserve,
            "collision": self.collision,
            "color": self.color,
        }
        return tuple(name for name, value in values.items() if value is None)

    def to_record(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "source_ref": self.source_ref,
            "page": self.page,
            "article_id": self.article_id,
            "character_count": self.character_count,
            "policy": self.policy,
            "ink": None if self.ink is None else self.ink.to_record(),
            "reserve": None if self.reserve is None else self.reserve.to_record(),
            "collision": None
            if self.collision is None
            else [item.to_record() for item in self.collision],
            "color": None if self.color is None else self.color.to_record(),
            "missing_fields": list(self.missing_fields()),
        }
