"""Frozen provider schema and transport-side decoder for repair decisions.

The decoder returns the C19 domain shape but does not call a repair handler.
The future controller adapter must still pass the result through C19's
deterministic preflight before mutation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.react.config import RepairConfig
from babeldoc.magazine.react.config import load_repair_config
from babeldoc.translator.tool_call import ToolCallSchemaError
from babeldoc.translator.tool_call import validate_schema

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "repair_tool_call.json"


@dataclass(frozen=True)
class RepairToolConfig:
    schema_version: str
    tool_name: str
    max_issue_ids: int
    max_element_refs: int
    max_identifier_chars: int
    repair_config: RepairConfig

    @property
    def parameter_slots(self) -> Mapping[str, Mapping[str, object]]:
        return self.repair_config.decision_parameter_slots

    @property
    def actions(self) -> Mapping[str, tuple[str, ...]]:
        return self.repair_config.decision_action_parameter_slots


@dataclass(frozen=True)
class RepairToolContext:
    """The bounded current-state catalogue available before C19 preflight."""

    state_sha256: str
    issue_actions: Mapping[str, tuple[str, ...]]
    element_owners: Mapping[str, tuple[int, str]]
    unsupported_pages: tuple[int, ...] = ()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ToolCallSchemaError(message)


@lru_cache(maxsize=1)
def load_repair_tool_config(path: str | None = None) -> RepairToolConfig:
    source = CONFIG_PATH if path is None else Path(path)
    with source.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    required = {
        "schema_version",
        "tool_name",
        "max_issue_ids",
        "max_element_refs",
        "max_identifier_chars",
    }
    _require(set(raw) == required, "repair tool config has unknown or missing keys")
    _require(
        raw["schema_version"] == "repair-decision-wire.v1",
        "repair tool config has an unknown schema version",
    )
    _require(raw["tool_name"] == "select_repair_action", "repair tool name changed")
    repair = load_repair_config()
    _require(
        repair.decision_schema_version == raw["schema_version"],
        "transport and canonical repair decision schema versions differ",
    )
    return RepairToolConfig(
        schema_version=raw["schema_version"],
        tool_name=raw["tool_name"],
        max_issue_ids=int(raw["max_issue_ids"]),
        max_element_refs=int(raw["max_element_refs"]),
        max_identifier_chars=int(raw["max_identifier_chars"]),
        repair_config=repair,
    )


def _nullable(slot: Mapping[str, object]) -> dict[str, object]:
    result = dict(slot)
    declared = result.get("type")
    result["type"] = [declared, "null"]
    if "enum" in result:
        result["enum"] = [*result["enum"], None]
    return result


def repair_tool_parameters_schema(
    config: RepairToolConfig | None = None,
) -> dict[str, object]:
    config = config or load_repair_tool_config()
    identifier = {
        "type": "string",
        "minLength": 1,
        "maxLength": config.max_identifier_chars,
        "pattern": r"[A-Za-z0-9_.:-]+",
    }
    nullable_identifier = dict(identifier)
    nullable_identifier["type"] = ["string", "null"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "action",
            "issue_ids",
            "target",
            "parameters",
            "state_sha256",
        ],
        "properties": {
            "action": {"type": "string", "enum": list(config.actions)},
            "issue_ids": {
                "type": "array",
                "items": identifier,
                "maxItems": config.max_issue_ids,
                "uniqueItems": True,
            },
            "target": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "physical_page_number",
                    "article_id",
                    "element_refs",
                ],
                "properties": {
                    "physical_page_number": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": 1000000,
                    },
                    "article_id": nullable_identifier,
                    "element_refs": {
                        "type": "array",
                        "items": identifier,
                        "maxItems": config.max_element_refs,
                        "uniqueItems": True,
                    },
                },
            },
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": list(config.parameter_slots),
                "properties": {
                    key: _nullable(value)
                    for key, value in config.parameter_slots.items()
                },
            },
            "state_sha256": {
                "type": "string",
                "minLength": 64,
                "maxLength": 64,
                "pattern": r"[0-9a-f]{64}",
            },
        },
    }


def decode_repair_tool_arguments(
    wire: Mapping[str, object],
    context: RepairToolContext,
    config: RepairToolConfig | None = None,
) -> dict[str, object]:
    """Validate wire slots/state/owners and return null-free domain arguments."""
    config = config or load_repair_tool_config()
    validate_schema(wire, repair_tool_parameters_schema(config))
    _require(wire["state_sha256"] == context.state_sha256, "stale repair state")
    action = wire["action"]
    issue_ids = wire["issue_ids"]
    target = wire["target"]
    supplied = wire["parameters"]
    required_slots = set(config.actions[action])
    non_null_slots = {name for name, value in supplied.items() if value is not None}
    _require(
        non_null_slots == required_slots,
        f"{action}: non-null parameter slots do not match its matrix",
    )

    if action == "no_action":
        _require(issue_ids == [], "no_action must have no issue ids")
        _require(
            target
            == {
                "physical_page_number": None,
                "article_id": None,
                "element_refs": [],
            },
            "no_action must have an empty target",
        )
    else:
        _require(bool(issue_ids), f"{action}: issue_ids must not be empty")
        for issue_id in issue_ids:
            allowed = context.issue_actions.get(issue_id)
            _require(allowed is not None, f"unknown issue id {issue_id}")
            _require(action in allowed, f"{issue_id}: wrong action for issue kind")
        page = target["physical_page_number"]
        article = target["article_id"]
        refs = target["element_refs"]
        _require(
            isinstance(page, int) and not isinstance(page, bool),
            f"{action}: target page is required",
        )
        _require(isinstance(article, str), f"{action}: target article is required")
        _require(bool(refs), f"{action}: target element refs are required")
        _require(page not in context.unsupported_pages, "target page is unsupported")
        for ref in refs:
            owner = context.element_owners.get(ref)
            _require(owner is not None, f"unknown element ref {ref}")
            _require(owner == (page, article), f"cross-owner target ref {ref}")

    canonical_parameters = {
        name: value for name, value in supplied.items() if value is not None
    }
    canonical_parameters = dict(
        config.repair_config.decision_parameters(action, canonical_parameters)
    )
    return {
        "action": action,
        "issue_ids": list(issue_ids),
        "target": {
            "physical_page_number": target["physical_page_number"],
            "article_id": target["article_id"],
            "element_refs": list(target["element_refs"]),
        },
        "parameters": canonical_parameters,
        "state_sha256": wire["state_sha256"],
    }
