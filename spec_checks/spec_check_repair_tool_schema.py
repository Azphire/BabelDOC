"""Offline checks for the frozen six-action repair tool wire schema."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

from openai.lib._pydantic import _ensure_strict_json_schema

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.translator.repair_tool_schema import RepairToolContext  # noqa: E402
from babeldoc.translator.repair_tool_schema import (  # noqa: E402
    decode_repair_tool_arguments,
)
from babeldoc.translator.repair_tool_schema import load_repair_tool_config  # noqa: E402
from babeldoc.translator.repair_tool_schema import (  # noqa: E402
    repair_tool_parameters_schema,
)
from babeldoc.translator.tool_call import ToolCallSchemaError  # noqa: E402
from babeldoc.translator.tool_call import validate_schema  # noqa: E402

STATE = "1" * 64
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail else ''}")


CONFIG = load_repair_tool_config()
NON_NULL = {
    "max_source_chars": 1200,
    "fit_profile": "balanced",
    "spacing_profile": "preserve",
    "minimum_scale_profile": "conservative",
    "wrap_policy": "preserve_words",
    "collision_axis": "least_overlap",
}


def wire(action: str) -> dict:
    parameters = dict.fromkeys(CONFIG.parameter_slots)
    for name in CONFIG.actions[action]:
        parameters[name] = NON_NULL[name]
    if action == "no_action":
        issue_ids = []
        target = {
            "physical_page_number": None,
            "article_id": None,
            "element_refs": [],
        }
    else:
        issue_ids = ["issue-1"]
        target = {
            "physical_page_number": 1,
            "article_id": "article-a",
            "element_refs": ["element-1"],
        }
    return {
        "action": action,
        "issue_ids": issue_ids,
        "target": target,
        "parameters": parameters,
        "state_sha256": STATE,
    }


def context(allowed=None) -> RepairToolContext:
    allowed = allowed or tuple(name for name in CONFIG.actions if name != "no_action")
    return RepairToolContext(
        state_sha256=STATE,
        issue_actions={"issue-1": tuple(allowed)},
        element_owners={
            "element-1": (1, "article-a"),
            "element-other-article": (1, "article-b"),
            "element-page-9": (9, "article-a"),
        },
        unsupported_pages=(9,),
    )


def check_schema_shape_and_actions() -> None:
    schema = repair_tool_parameters_schema()
    provider_normalized = copy.deepcopy(schema)
    _ensure_strict_json_schema(
        provider_normalized,
        path=(),
        root=provider_normalized,
    )
    objects = [
        schema,
        schema["properties"]["target"],
        schema["properties"]["parameters"],
    ]
    strict = all(
        item["additionalProperties"] is False
        and set(item["required"]) == set(item["properties"])
        for item in objects
    )
    decoded = {}
    for action in CONFIG.actions:
        sample = wire(action)
        validate_schema(sample, schema)
        decoded[action] = decode_repair_tool_arguments(sample, context())
    canonical = all(
        decoded[action]["parameters"]
        == {name: NON_NULL[name] for name in CONFIG.actions[action]}
        for action in CONFIG.actions
    )
    check(
        "01 provider schema is strict and all six actions canonicalise",
        strict
        and provider_normalized == schema
        and canonical
        and decoded["no_action"]["parameters"] == {}
        and CONFIG.schema_version == "repair-decision-wire.v1"
        and CONFIG.tool_name == "select_repair_action",
    )


def check_negative_cases_do_not_reach_handler() -> None:
    cases: list[tuple[str, dict, RepairToolContext]] = []
    unknown_action = wire("no_action")
    unknown_action["action"] = "freeform_repair"
    cases.append(("unknown action", unknown_action, context()))

    extra = wire("no_action")
    extra["reason"] = "free text must not enter control logic"
    cases.append(("extra reason", extra, context()))

    box = wire("reprocess_omitted_text")
    box["target"]["box"] = [0, 0, 1, 1]
    cases.append(("coordinate box", box, context()))

    free_text = wire("contain_overflowing_heading")
    free_text["parameters"]["wrap_policy"] = "rewrite with this prompt"
    cases.append(("free text parameter", free_text, context()))

    stale = wire("resolve_text_collision")
    stale["state_sha256"] = "2" * 64
    cases.append(("stale state", stale, context()))

    wrong_kind = wire("resolve_text_collision")
    cases.append(("wrong issue kind", wrong_kind, context(("reprocess_omitted_text",))))

    cross_owner = wire("retypeset_article_region")
    cross_owner["target"]["element_refs"] = ["element-other-article"]
    cases.append(("cross owner", cross_owner, context()))

    unsupported = wire("reallocate_continuity_chain")
    unsupported["target"] = {
        "physical_page_number": 9,
        "article_id": "article-a",
        "element_refs": ["element-page-9"],
    }
    cases.append(("unsupported page", unsupported, context()))

    unknown_ref = wire("reprocess_omitted_text")
    unknown_ref["target"]["element_refs"] = ["missing-element"]
    cases.append(("unknown ref", unknown_ref, context()))

    out_of_range = wire("reprocess_omitted_text")
    out_of_range["parameters"]["max_source_chars"] = 20001
    cases.append(("out of range", out_of_range, context()))

    no_action_nonempty = wire("no_action")
    no_action_nonempty["issue_ids"] = ["issue-1"]
    cases.append(("no_action nonempty", no_action_nonempty, context()))

    unused = wire("resolve_text_collision")
    unused["parameters"]["fit_profile"] = "balanced"
    cases.append(("unused slot non-null", unused, context()))

    missing_wire_slot = wire("resolve_text_collision")
    del missing_wire_slot["parameters"]["wrap_policy"]
    cases.append(("wire slot missing", missing_wire_slot, context()))

    required_null = wire("resolve_text_collision")
    required_null["parameters"]["collision_axis"] = None
    cases.append(("required slot null", required_null, context()))

    handler_calls: list[dict] = []
    failures: list[str] = []
    for label, sample, state in cases:
        try:
            decision = decode_repair_tool_arguments(sample, state)
        except ToolCallSchemaError:
            continue
        handler_calls.append(decision)
        failures.append(label)
    check(
        "02 unknown/extra/text/stale/kind/owner/page/ref/range/matrix negatives stop before handler",
        not handler_calls and not failures,
        ", ".join(failures),
    )


def check_schema_is_not_mutated() -> None:
    first = repair_tool_parameters_schema()
    changed = copy.deepcopy(first)
    changed["properties"]["action"]["enum"].append("invented")
    second = repair_tool_parameters_schema()
    check(
        "03 schema calls return independent provider documents",
        "invented" not in second["properties"]["action"]["enum"],
    )


def main() -> int:
    check_schema_shape_and_actions()
    check_negative_cases_do_not_reach_handler()
    check_schema_is_not_mutated()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(
        f"spec_check_repair_tool_schema: "
        f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
