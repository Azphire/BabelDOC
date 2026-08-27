"""Offline checks for the HITL source-binding protocol seed."""

from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.hitl_expectation import (  # noqa: E402
    MANUAL_EXPECTATION_SCHEMA_VERSION,
)
from babeldoc.magazine.hitl_expectation import ManualConstraintEvidence  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintExpectation  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintKind  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintStage  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintStatus  # noqa: E402
from babeldoc.magazine.hitl_expectation import (  # noqa: E402
    ManualExpectationProtocolError,
)
from babeldoc.magazine.hitl_expectation import (  # noqa: E402
    manual_constraint_expectation_schema,
)
from babeldoc.magazine.hitl_expectation import pending_stage_evidence  # noqa: E402


def _sample() -> ManualConstraintExpectation:
    return ManualConstraintExpectation(
        expectation_id="term:abb-review",
        kind=ManualConstraintKind.TERM,
        human_value="ABB Review",
        source_occurrence_refs=("page:7/paragraph:2/span:0-11", "page:2/p:4"),
        selected_occurrence_refs=("page:2/p:4",),
        source_binding_sha256="a" * 64,
        stage_evidence=pending_stage_evidence(),
    )


def _assert_protocol_error(callback: Callable[[], Any], needle: str) -> None:
    try:
        callback()
    except ManualExpectationProtocolError as exc:
        assert needle in str(exc), (needle, str(exc))
    else:
        raise AssertionError("expected ManualExpectationProtocolError")


def check_closed_enums() -> None:
    assert [item.value for item in ManualConstraintKind] == [
        "term",
        "page_policy",
        "drop_cap",
    ]
    assert [item.value for item in ManualConstraintStage] == [
        "delivery",
        "target",
        "typeset",
        "final_pdf",
    ]
    assert [item.value for item in ManualConstraintStatus] == [
        "pending",
        "pass",
        "fail",
        "not_exercised",
        "not_selected",
        "not_applicable",
    ]


def check_strict_schema() -> None:
    schema = manual_constraint_expectation_schema()
    assert schema["$id"] == MANUAL_EXPECTATION_SCHEMA_VERSION
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    evidence = schema["properties"]["stage_evidence"]
    assert evidence["minItems"] == evidence["maxItems"] == 4
    assert evidence["items"] is False
    assert [
        item["properties"]["stage"]["const"] for item in evidence["prefixItems"]
    ] == ["delivery", "target", "typeset", "final_pdf"]
    for item_schema in evidence["prefixItems"]:
        assert item_schema["additionalProperties"] is False
        assert set(item_schema["required"]) == set(item_schema["properties"])
        assert "not_exercised" in item_schema["properties"]["status"]["enum"]
    # The caller cannot mutate a later schema result through an earlier one.
    schema["properties"].clear()
    assert manual_constraint_expectation_schema()["properties"]


def check_canonical_serialization() -> None:
    expectation = _sample()
    first = expectation.to_json_bytes()
    second = _sample().to_json_bytes()
    assert first == second
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")
    assert expectation.source_occurrence_refs == (
        "page:2/p:4",
        "page:7/paragraph:2/span:0-11",
    )
    decoded = json.loads(first)
    assert list(decoded) == sorted(decoded)
    assert decoded["stage_evidence"] == [
        {"evidence_refs": [], "stage": stage, "status": "pending"}
        for stage in ("delivery", "target", "typeset", "final_pdf")
    ]


def check_round_trip() -> None:
    expected = _sample()
    restored = ManualConstraintExpectation.from_json_bytes(expected.to_json_bytes())
    assert restored == expected
    assert restored.to_json_bytes() == expected.to_json_bytes()


def check_unknown_and_missing_top_level_fields() -> None:
    record = _sample().to_record()
    unknown = copy.deepcopy(record)
    unknown["model_inferred_value"] = "forbidden"
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(unknown), "unknown fields"
    )
    missing = copy.deepcopy(record)
    del missing["human_value"]
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(missing), "missing fields"
    )


def check_unknown_and_missing_evidence_fields() -> None:
    record = _sample().to_record()
    unknown = copy.deepcopy(record)
    unknown["stage_evidence"][0]["provider_response"] = "forbidden"
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(unknown), "unknown fields"
    )
    missing = copy.deepcopy(record)
    del missing["stage_evidence"][0]["evidence_refs"]
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(missing), "missing fields"
    )


def check_binding_and_occurrence_invariants() -> None:
    record = _sample().to_record()
    bad_sha = copy.deepcopy(record)
    bad_sha["source_binding_sha256"] = "A" * 64
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(bad_sha),
        "64 lowercase hexadecimal",
    )
    outside = copy.deepcopy(record)
    outside["selected_occurrence_refs"] = ["page:99/p:1"]
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(outside), "must be a subset"
    )
    duplicates = copy.deepcopy(record)
    duplicates["source_occurrence_refs"].append(duplicates["source_occurrence_refs"][0])
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(duplicates), "unique refs"
    )


def check_stage_status_and_evidence_invariants() -> None:
    record = _sample().to_record()
    wrong_order = copy.deepcopy(record)
    wrong_order["stage_evidence"].reverse()
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(wrong_order),
        "canonical order",
    )
    unknown_status = copy.deepcopy(record)
    unknown_status["stage_evidence"][0]["status"] = "skipped"
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(unknown_status),
        "unknown manual constraint status",
    )
    no_evidence = copy.deepcopy(record)
    no_evidence["stage_evidence"][0]["status"] = "not_exercised"
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(no_evidence),
        "requires evidence refs",
    )
    pending_with_evidence = copy.deepcopy(record)
    pending_with_evidence["stage_evidence"][0]["evidence_refs"] = ["request:sha256:abc"]
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(pending_with_evidence),
        "pending status cannot carry evidence refs",
    )
    exercised = ManualConstraintEvidence(
        stage=ManualConstraintStage.DELIVERY,
        status=ManualConstraintStatus.NOT_EXERCISED,
        evidence_refs=("reason:no-selected-eligible-occurrence",),
    )
    assert exercised.status is ManualConstraintStatus.NOT_EXERCISED


def check_immutable_value_graph() -> None:
    expectation = _sample()
    assert isinstance(expectation.source_occurrence_refs, tuple)
    assert isinstance(expectation.stage_evidence, tuple)
    assert all(
        isinstance(item.evidence_refs, tuple) for item in expectation.stage_evidence
    )
    try:
        expectation.human_value = "model output"  # type: ignore[misc]
    except (dataclasses.FrozenInstanceError, AttributeError):
        pass
    else:
        raise AssertionError("ManualConstraintExpectation must be immutable")


def check_unique_type_ownership() -> None:
    owners: list[Path] = []
    for path in sorted((ROOT / "babeldoc").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == (
                "ManualConstraintExpectation"
            ):
                owners.append(path.relative_to(ROOT))
    assert owners == [Path("babeldoc/magazine/hitl_expectation.py")], owners


PROTOCOL_CHECKS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("closed kind/stage/status enums", check_closed_enums),
    ("closed JSON schema", check_strict_schema),
    ("canonical serialization", check_canonical_serialization),
    ("canonical round-trip", check_round_trip),
    ("unknown/missing expectation fields", check_unknown_and_missing_top_level_fields),
    ("unknown/missing evidence fields", check_unknown_and_missing_evidence_fields),
    (
        "source binding and occurrence invariants",
        check_binding_and_occurrence_invariants,
    ),
    ("stage/status/evidence invariants", check_stage_status_and_evidence_invariants),
    ("immutable value graph", check_immutable_value_graph),
    ("unique type ownership", check_unique_type_ownership),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("protocol",),
        default="protocol",
        help="bounded phase to run",
    )
    args = parser.parse_args()
    if args.phase != "protocol":
        raise AssertionError(args.phase)

    failures = 0
    print("HITL source-binding protocol checks")
    for label, check in PROTOCOL_CHECKS:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - gate reports every assertion.
            failures += 1
            print(f"FAIL: {label}: {exc}")
        else:
            print(f"PASS: {label}")
    passed = len(PROTOCOL_CHECKS) - failures
    print(f"RESULT: {passed}/{len(PROTOCOL_CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
