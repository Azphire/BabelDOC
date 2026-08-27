"""Offline checks for the frozen six-action repair tool wire schema."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

from openai.lib._pydantic import _ensure_strict_json_schema

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.element_roles import ElementRole  # noqa: E402
from babeldoc.magazine.react.config import load_repair_config  # noqa: E402
from babeldoc.magazine.react.decide import CachedDecisionClient  # noqa: E402
from babeldoc.magazine.react.decide import EngineTransport  # noqa: E402
from babeldoc.magazine.repair_contract import (  # noqa: E402
    ACTION_DETECTOR_CLOSURE_VERSION,
)
from babeldoc.magazine.repair_contract import RepairAction  # noqa: E402
from babeldoc.magazine.repair_contract import RepairContractError  # noqa: E402
from babeldoc.magazine.repair_contract import RepairDecision  # noqa: E402
from babeldoc.magazine.repair_contract import RepairIssueEvidence  # noqa: E402
from babeldoc.magazine.repair_contract import RepairIssueKind  # noqa: E402
from babeldoc.magazine.repair_contract import RepairKnowledgeState  # noqa: E402
from babeldoc.magazine.repair_contract import RepairTarget  # noqa: E402
from babeldoc.translator.repair_tool_schema import RepairToolContext  # noqa: E402
from babeldoc.translator.repair_tool_schema import (  # noqa: E402
    decode_repair_tool_arguments,
)
from babeldoc.translator.repair_tool_schema import load_repair_tool_config  # noqa: E402
from babeldoc.translator.repair_tool_schema import (  # noqa: E402
    repair_tool_parameters_schema,
)
from babeldoc.translator.tool_call import ToolCallProtocolError  # noqa: E402
from babeldoc.translator.tool_call import ToolCallResult  # noqa: E402
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


def repair_state(action: RepairAction) -> RepairKnowledgeState:
    digest = "a" * 64
    issue = RepairIssueEvidence(
        issue_id="issue-1",
        kind=RepairIssueKind.UNTRANSLATED_RESIDUE,
        physical_page=1,
        article_refs=("article-a",),
        element_refs=("element-1",),
        text_excerpt="bounded",
        metric_vector=(("residue_chars", 12),),
    )
    return RepairKnowledgeState(
        document_semantic_sha256=digest,
        physical_page_selection_sha256=digest,
        article_knowledge_state_sha256=digest,
        run_trace_generation=0,
        issues=(issue,),
        page_policies=((1, digest),),
        article_regions=(("article-a", ()),),
        element_roles=(("element-1", ElementRole.BODY),),
        chain_states=(),
        legal_slot_digests=(),
        fixed_asset_inventory_sha256=digest,
        manual_constraint_refs=(),
        protected_refs=(),
        allowed_actions=tuple(sorted((RepairAction.NO_ACTION, action))),
        action_detector_closure_version=ACTION_DETECTOR_CLOSURE_VERSION,
        limits=(("max_actions", 1),),
    )


def check_c19_parameter_preflight() -> None:
    repair = load_repair_config()
    valid = {}
    refused = {}
    for action_name, slot_names in repair.decision_action_parameter_slots.items():
        if action_name == "no_action":
            continue
        action = RepairAction(action_name)
        supplied = {name: NON_NULL[name] for name in slot_names}
        state = repair_state(action)
        decision = RepairDecision(
            action=action,
            issue_ids=("issue-1",),
            target=RepairTarget(
                physical_pages=(1,),
                article_refs=("article-a",),
                element_refs=("element-1",),
            ),
            parameters=tuple(sorted(supplied.items())),
            state_sha256=state.sha256(),
        )
        state.preflight(decision)
        valid[action_name] = dict(decision.parameters)
        tampered = dict(supplied)
        first = slot_names[0]
        slot = repair.decision_parameter_slots[first]
        tampered[first] = (
            int(slot["maximum"]) + 1
            if slot["type"] == "integer"
            else "unsupported_profile"
        )
        bad = RepairDecision(
            action=action,
            issue_ids=decision.issue_ids,
            target=decision.target,
            parameters=tuple(sorted(tampered.items())),
            state_sha256=state.sha256(),
        )
        try:
            state.preflight(bad)
        except RepairContractError:
            refused[action_name] = True
        else:
            refused[action_name] = False
    no_action_state = repair_state(RepairAction.REPROCESS_OMITTED_TEXT)
    no_action = RepairDecision(
        action=RepairAction.NO_ACTION,
        issue_ids=(),
        target=RepairTarget(),
        parameters=(),
        state_sha256=no_action_state.sha256(),
    )
    no_action_state.preflight(no_action)
    check(
        "04 C19 preflight consumes the unique matrix and refuses every tampered profile",
        set(valid) == set(CONFIG.actions) - {"no_action"}
        and all(refused.values())
        and no_action.parameters == ()
        and CONFIG.parameter_slots
        == repair.decision_parameter_slots,
    )


class FakeStructuredEngine:
    def __init__(self, arguments=None, error=None) -> None:
        self.arguments = arguments
        self.error = error
        self.tool_call_attempt_count = 0
        self.tool_call_cache_hit_count = 0
        self.tool_calls = 0
        self.text_calls = 0
        self.request = None

    @staticmethod
    def supports_tool_calls() -> bool:
        return True

    def llm_tool_call(self, **request):
        self.tool_calls += 1
        self.tool_call_attempt_count += 1
        self.request = request
        if self.error is not None:
            raise self.error
        return ToolCallResult(
            tool_name=CONFIG.tool_name,
            arguments=self.arguments,
            provider_call_id="fake-call",
            finish_reason="tool_calls",
        )

    def llm_translate(self, *_args, **_kwargs):
        self.text_calls += 1
        raise AssertionError("text fallback must not execute")


class UnsupportedEngine(FakeStructuredEngine):
    @staticmethod
    def supports_tool_calls() -> bool:
        return False


def check_production_adapter() -> None:
    state = repair_state(RepairAction.REPROCESS_OMITTED_TEXT)
    sample = wire("reprocess_omitted_text")
    sample["state_sha256"] = state.sha256()
    issue = SimpleNamespace(
        id="issue-1",
        kind="untranslated_residue",
        severity="high",
        page=1,
        article_refs=("article-a",),
        paragraph_refs=("element-1",),
        evidence={"residue_chars": 12, "excerpt": "bounded"},
    )
    engine = FakeStructuredEngine(sample)
    client = CachedDecisionClient(
        load_repair_config(),
        transport=EngineTransport(engine),
        identity="fake/structured",
        ignore_cache=True,
        request_limits={"attempt_timeout_seconds": 7.0, "max_attempts": 1},
    )
    decision, request = client.decide([issue], repair_state=state)
    no_action_wire = wire("no_action")
    no_action_wire["state_sha256"] = state.sha256()
    no_action_engine = FakeStructuredEngine(no_action_wire)
    no_action, _no_action_request = CachedDecisionClient(
        load_repair_config(),
        transport=EngineTransport(no_action_engine),
        identity="fake/no-action",
    ).decide([issue], repair_state=state)

    content_only = FakeStructuredEngine(
        error=ToolCallProtocolError("content-only JSON is not a tool call")
    )
    refused, refused_request = CachedDecisionClient(
        load_repair_config(),
        transport=EngineTransport(content_only),
        identity="fake/content-only",
    ).decide([issue], repair_state=state)
    unsupported_engine = UnsupportedEngine()
    unsupported, unsupported_request = CachedDecisionClient(
        load_repair_config(),
        transport=EngineTransport(unsupported_engine),
        identity="fake/unsupported",
    ).decide([issue], repair_state=state)
    record = decision.to_record() if decision is not None else {}
    check(
        "05 production uses one forced named call and C19 typed preflight; content-only never falls back",
        decision is not None
        and decision.action is RepairAction.REPROCESS_OMITTED_TEXT
        and dict(decision.parameters) == {"max_source_chars": 1200}
        and engine.tool_calls == 1
        and engine.text_calls == 0
        and engine.request["tool_name"] == "select_repair_action"
        and engine.request["state_sha256"] == state.sha256()
        and engine.request["request_limits"]["attempt_timeout_seconds"] == 7.0
        and request.logical_calls == 1
        and request.provider_attempts == 1
        and no_action is not None
        and no_action.action is RepairAction.NO_ACTION
        and no_action.parameters == ()
        and no_action.target == RepairTarget()
        and refused is None
        and content_only.tool_calls == 1
        and content_only.text_calls == 0
        and refused_request.violations == ["ToolCallProtocolError"]
        and unsupported is None
        and unsupported_engine.tool_calls == 0
        and unsupported_engine.text_calls == 0
        and unsupported_request.violations
        == ["STRUCTURED_TOOL_CALLS_UNSUPPORTED"]
        and "reason" not in record
        and "raw" not in record
        and not hasattr(request, "prompt_text")
        and all("request_head" not in row for row in request.calls),
    )


def main() -> int:
    check_schema_shape_and_actions()
    check_negative_cases_do_not_reach_handler()
    check_schema_is_not_mutated()
    check_c19_parameter_preflight()
    check_production_adapter()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(
        f"spec_check_repair_tool_schema: "
        f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
