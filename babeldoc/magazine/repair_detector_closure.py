"""Versioned action-to-detector closure for the bounded repair controller."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.repair_contract import ACTION_DETECTOR_CLOSURE_VERSION
from babeldoc.magazine.repair_contract import RepairAction
from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("repair_detector_closure.json")

REQUIRED_CONSERVATION_DETECTORS = frozenset(
    {
        "untranslated_residue",
        "out_of_page",
        "text_text_collision",
        "text_figure_overlap",
        "article_ownership",
        "chain_conservation",
        "render_coverage",
        "fixed_asset_drift",
        "instruction_compliance",
    }
)

_ROOT_KEYS = frozenset(
    {"schema_version", "complete_detector_suite", "closures", "description"}
)
_CLOSURE_KEYS = frozenset(
    {
        "trigger_issue_kinds",
        "primary_detectors",
        "conservation_detectors",
        "potential_side_effect_kinds",
        "required_state",
    }
)


class RepairDetectorClosureError(ValueError):
    """The action-to-detector closure cannot fail closed."""


@dataclass(frozen=True, slots=True)
class ActionDetectorClosure:
    action: RepairAction
    trigger_issue_kinds: tuple[str, ...]
    primary_detectors: tuple[str, ...]
    conservation_detectors: tuple[str, ...]
    potential_side_effect_kinds: tuple[str, ...]
    required_state: tuple[str, ...]

    def to_record(self) -> dict:
        return {
            "trigger_issue_kinds": list(self.trigger_issue_kinds),
            "primary_detectors": list(self.primary_detectors),
            "conservation_detectors": list(self.conservation_detectors),
            "potential_side_effect_kinds": list(
                self.potential_side_effect_kinds
            ),
            "required_state": list(self.required_state),
        }


@dataclass(frozen=True, slots=True)
class RepairDetectorClosureConfig:
    complete_detector_suite: tuple[str, ...]
    closures: tuple[ActionDetectorClosure, ...]
    schema_version: str = ACTION_DETECTOR_CLOSURE_VERSION

    def action(self, action: RepairAction | str) -> ActionDetectorClosure:
        try:
            resolved = RepairAction(action)
        except ValueError as exc:
            raise RepairDetectorClosureError(
                f"unknown repair action: {action!r}"
            ) from exc
        for closure in self.closures:
            if closure.action is resolved:
                return closure
        raise RepairDetectorClosureError(
            f"repair detector closure omits {resolved.value}"
        )

    def to_record(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "complete_detector_suite": list(self.complete_detector_suite),
            "closures": {
                closure.action.value: closure.to_record()
                for closure in self.closures
            },
        }


@dataclass(frozen=True, slots=True)
class DetectorClosureRun:
    """Evidence that primary ordering and the complete suite both ran."""

    action: RepairAction
    registry_version: str
    ran_detectors: tuple[str, ...]
    conservation_invariants_passed: bool

    def require_complete(self, config: RepairDetectorClosureConfig) -> None:
        if self.registry_version != config.schema_version:
            raise RepairDetectorClosureError(
                "detector closure registry version changed"
            )
        expected = set(config.complete_detector_suite)
        actual = set(self.ran_detectors)
        if actual != expected or len(actual) != len(self.ran_detectors):
            raise RepairDetectorClosureError(
                "complete detector suite was not rerun"
            )
        closure = config.action(self.action)
        if not set(closure.primary_detectors).issubset(actual):
            raise RepairDetectorClosureError(
                "primary detector closure was not rerun"
            )
        if not set(closure.conservation_detectors).issubset(actual):
            raise RepairDetectorClosureError(
                "conservation detector closure was not rerun"
            )
        if not self.conservation_invariants_passed:
            raise RepairDetectorClosureError(
                "repair conservation invariants failed"
            )


def _strings(value, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise RepairDetectorClosureError(
            f"{label} must be an array of non-empty strings"
        )
    if not allow_empty and not value:
        raise RepairDetectorClosureError(f"{label} must not be empty")
    if len(value) != len(set(value)):
        raise RepairDetectorClosureError(f"{label} must contain unique values")
    return tuple(value)


def parse_repair_detector_closure(
    raw: object,
    source: str,
    *,
    known_detectors,
    known_issue_kinds,
) -> RepairDetectorClosureConfig:
    if not isinstance(raw, dict):
        raise RepairDetectorClosureError(f"{source}: root must be an object")
    missing = sorted(_ROOT_KEYS - set(raw))
    unknown = sorted(set(raw) - _ROOT_KEYS)
    if missing or unknown:
        raise RepairDetectorClosureError(
            f"{source}: root fields differ: missing={missing}, unknown={unknown}"
        )
    if raw["schema_version"] != ACTION_DETECTOR_CLOSURE_VERSION:
        raise RepairDetectorClosureError(f"{source}: unsupported schema_version")
    detector_set = set(known_detectors)
    issue_set = set(known_issue_kinds)
    complete = _strings(raw["complete_detector_suite"], "complete_detector_suite")
    if set(complete) != detector_set:
        raise RepairDetectorClosureError(
            "complete_detector_suite must equal the registry"
        )
    closures_raw = raw["closures"]
    if not isinstance(closures_raw, dict):
        raise RepairDetectorClosureError(f"{source}: closures must be an object")
    expected_actions = {action.value for action in RepairAction}
    if set(closures_raw) != expected_actions:
        raise RepairDetectorClosureError(
            "closures must cover the closed action vocabulary"
        )
    closures = []
    for action in RepairAction:
        record = closures_raw[action.value]
        if not isinstance(record, dict) or set(record) != _CLOSURE_KEYS:
            raise RepairDetectorClosureError(
                f"{source}: invalid closure for {action.value}"
            )
        allow_empty = action is RepairAction.NO_ACTION
        triggers = _strings(
            record["trigger_issue_kinds"],
            f"{action.value}.trigger_issue_kinds",
            allow_empty=allow_empty,
        )
        primary = _strings(
            record["primary_detectors"],
            f"{action.value}.primary_detectors",
            allow_empty=allow_empty,
        )
        conservation = _strings(
            record["conservation_detectors"],
            f"{action.value}.conservation_detectors",
            allow_empty=allow_empty,
        )
        side_effects = _strings(
            record["potential_side_effect_kinds"],
            f"{action.value}.potential_side_effect_kinds",
            allow_empty=allow_empty,
        )
        required = _strings(
            record["required_state"],
            f"{action.value}.required_state",
            allow_empty=allow_empty,
        )
        if set(primary) - detector_set or set(conservation) - detector_set:
            raise RepairDetectorClosureError(
                f"{action.value}: closure names unknown detector"
            )
        if set(triggers) - issue_set or set(side_effects) - issue_set:
            raise RepairDetectorClosureError(
                f"{action.value}: closure names unknown issue kind"
            )
        if action is not RepairAction.NO_ACTION and not REQUIRED_CONSERVATION_DETECTORS.issubset(
            conservation
        ):
            raise RepairDetectorClosureError(
                f"{action.value}: closure omits global conservation detectors"
            )
        closures.append(
            ActionDetectorClosure(
                action,
                triggers,
                primary,
                conservation,
                side_effects,
                required,
            )
        )
    return RepairDetectorClosureConfig(complete, tuple(closures))


@lru_cache(maxsize=2)
def load_repair_detector_closure(path: str | None = None):
    from babeldoc.magazine import detectors

    source = CONFIG_PATH if path is None else Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    return parse_repair_detector_closure(
        raw,
        source.name,
        known_detectors=tuple(sorted(detectors.DETECTORS)),
        known_issue_kinds=detectors.detector_kinds(),
    )
