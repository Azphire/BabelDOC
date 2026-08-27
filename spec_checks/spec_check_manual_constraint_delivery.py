"""Offline gate for source-bound manual delivery and target evidence."""

from __future__ import annotations

import ast
import dataclasses
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.hitl_binding import BoundDecisionProjection  # noqa: E402
from babeldoc.magazine.hitl_binding import canonical_sha256  # noqa: E402
from babeldoc.magazine.hitl_binding import load_toml_semantic_config  # noqa: E402
from babeldoc.magazine.hitl_binding import semantic_config_sha256  # noqa: E402
from babeldoc.magazine.hitl_delivery import DropCapDeliveryEvidence  # noqa: E402
from babeldoc.magazine.hitl_delivery import DropCapTargetEvidence  # noqa: E402
from babeldoc.magazine.hitl_delivery import ManualConstraintDeliveryError  # noqa: E402
from babeldoc.magazine.hitl_delivery import TermDeliveryEvidence  # noqa: E402
from babeldoc.magazine.hitl_delivery import TermTargetEvidence  # noqa: E402
from babeldoc.magazine.hitl_delivery import finalize_page_policy_targets  # noqa: E402
from babeldoc.magazine.hitl_delivery import inventory_from_bound  # noqa: E402
from babeldoc.magazine.hitl_delivery import load_page_policy_observables  # noqa: E402
from babeldoc.magazine.hitl_delivery import page_policy_sha256  # noqa: E402
from babeldoc.magazine.hitl_delivery import record_drop_cap_delivery  # noqa: E402
from babeldoc.magazine.hitl_delivery import record_drop_cap_targets  # noqa: E402
from babeldoc.magazine.hitl_delivery import record_page_policy_delivery  # noqa: E402
from babeldoc.magazine.hitl_delivery import record_page_policy_event  # noqa: E402
from babeldoc.magazine.hitl_delivery import record_term_delivery  # noqa: E402
from babeldoc.magazine.hitl_delivery import record_term_targets  # noqa: E402
from babeldoc.magazine.hitl_delivery import write_inventory_report  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintKind  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintStatus  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402


def _occurrence(
    reference: str,
    page: int,
    eligibility: str,
    *,
    start: int,
) -> dict[str, Any]:
    record = {
        "source_ref": reference,
        "physical_page": page,
        "stable_source_ref": reference.split(":span:", 1)[0],
        "source_span": [start, start + len("ABB 评论")],
        "role": "BODY" if eligibility == "eligible" else "FIXED_ASSET",
        "translation_eligibility": eligibility,
        "eligibility_rule_id": f"term-occurrence-eligibility.v1:{eligibility}",
    }
    record["fingerprint"] = canonical_sha256(record)
    return record


def _candidate(base: dict[str, Any]) -> dict[str, Any]:
    record = dict(base)
    if "fingerprint" not in record:
        record["fingerprint"] = canonical_sha256(record)
    return record


def _bound() -> BoundDecisionProjection:
    eligible = _occurrence("p2#pdf-block-1:span:4-10", 2, "eligible", start=4)
    protected = _occurrence(
        "p3#pdf-block-2:span:0-6", 3, "protected_fixed", start=0
    )
    unselected = _occurrence(
        "p8#pdf-block-3:span:9-15", 8, "eligible", start=9
    )
    term_candidate = _candidate(
        {
            "source": "ABB 评论",
            "stable_ref": "term:abb-comment",
            "occurrences": [eligible, protected, unselected],
        }
    )
    pages = [
        _candidate(
            {
                "page": page,
                "stable_ref": f"page:{page}",
                "physical_page": page,
            }
        )
        for page in (2, 3, 8)
    ]
    drops = [
        _candidate(
            {
                "reference": reference,
                "stable_ref": f"drop:{reference}",
                "physical_page": page,
            }
        )
        for reference, page in (("p3#0", 3), ("p8#0", 8))
    ]
    source_binding = {
        "schema_version": "hitl-source-binding.v1",
        "source_pdf_sha256": "1" * 64,
        "source_page_count": 8,
    }
    decisions = {
        "source_binding": source_binding,
        "terms": {"ABB 评论": "ABB Review"},
        "page_kinds": {"2": "editorial", "3": "toc", "8": "article_opener"},
        "drop_caps": {
            "p3#0": {"decision": "keep"},
            "p8#0": {"decision": "flatten"},
        },
    }
    review = {
        "terms": [term_candidate],
        "page_kinds": pages,
        "drop_caps": drops,
    }
    return BoundDecisionProjection(
        path=Path("fixture.decisions.json"),
        terms={"ABB 评论": "ABB Review"},
        page_kinds={2: "editorial", 3: "toc"},
        drop_caps={"p3#0": {"decision": "keep"}},
        projection_report=(),
        decisions=decisions,
        review=review,
        artifact_sha256={},
        selected_pages=(2, 3),
    )


def _assert_error(callback: Callable[[], Any], needle: str) -> None:
    try:
        callback()
    except ManualConstraintDeliveryError as exc:
        assert needle in str(exc), (needle, str(exc))
    else:
        raise AssertionError("expected ManualConstraintDeliveryError")


def _term_delivery_evidence() -> tuple[TermDeliveryEvidence, ...]:
    return (
        TermDeliveryEvidence(
            occurrence_ref="p2#pdf-block-1:span:4-10",
            physical_page=2,
            paragraph_ref="p2#0",
            eligibility="eligible",
            eligibility_rule_id="term-occurrence-eligibility.v1:eligible",
            request_sha256="a" * 64,
            glossary_sha256="b" * 64,
        ),
        TermDeliveryEvidence(
            occurrence_ref="p3#pdf-block-2:span:0-6",
            physical_page=3,
            paragraph_ref="p3#fixed-asset-0",
            eligibility="protected_fixed",
            eligibility_rule_id=(
                "term-occurrence-eligibility.v1:protected_fixed"
            ),
            fixed_asset_ref="asset:p3#image-0",
        ),
    )


def _term_target_evidence(target: str = "ABB Review") -> tuple[TermTargetEvidence, ...]:
    return (
        TermTargetEvidence(
            occurrence_ref="p2#pdf-block-1:span:4-10",
            physical_page=2,
            paragraph_ref="p2#0",
            target_text=target,
            mapping_count=1,
            target_span=(0, len(target)),
        ),
        TermTargetEvidence(
            occurrence_ref="p3#pdf-block-2:span:0-6",
            physical_page=3,
            paragraph_ref="p3#fixed-asset-0",
            target_text=None,
            mapping_count=0,
            fixed_asset_ref="asset:p3#image-0",
        ),
    )


def check_inventory_denominator_and_human_values() -> None:
    inventory = inventory_from_bound(_bound())
    terms = [
        item for item in inventory.expectations if item.kind is ManualConstraintKind.TERM
    ]
    assert len(terms) == 3
    assert {item.human_value for item in terms} == {"ABB Review"}
    assert all(len(item.source_occurrence_refs) == 3 for item in terms)
    assert sum(bool(item.selected_occurrence_refs) for item in terms) == 2
    unselected = next(item for item in terms if not item.selected_occurrence_refs)
    assert unselected.stage_evidence[0].status is ManualConstraintStatus.NOT_SELECTED
    assert unselected.stage_evidence[1].status is ManualConstraintStatus.NOT_SELECTED
    assert all(
        item.status is ManualConstraintStatus.PENDING
        for item in unselected.stage_evidence[2:]
    )


def check_term_delivery_and_target_exactness() -> None:
    inventory = inventory_from_bound(_bound())
    delivered = record_term_delivery(inventory, _term_delivery_evidence())
    selected = [
        item
        for item in delivered.expectations
        if item.kind is ManualConstraintKind.TERM and item.selected_occurrence_refs
    ]
    assert {item.stage_evidence[0].status for item in selected} == {
        ManualConstraintStatus.PASS,
        ManualConstraintStatus.NOT_APPLICABLE,
    }
    targeted = record_term_targets(delivered, _term_target_evidence())
    assert {item.human_value for item in targeted.expectations if item.kind.value == "term"} == {
        "ABB Review"
    }
    selected = [
        item
        for item in targeted.expectations
        if item.kind is ManualConstraintKind.TERM and item.selected_occurrence_refs
    ]
    assert {item.stage_evidence[1].status for item in selected} == {
        ManualConstraintStatus.PASS,
        ManualConstraintStatus.NOT_APPLICABLE,
    }
    assert all(
        item.stage_evidence[2].status is ManualConstraintStatus.PENDING
        and item.stage_evidence[3].status is ManualConstraintStatus.PENDING
        for item in targeted.expectations
    )


def check_fake_model_cannot_change_human_value() -> None:
    inventory = record_term_delivery(
        inventory_from_bound(_bound()), _term_delivery_evidence()
    )
    before = inventory.to_json_bytes()
    _assert_error(
        lambda: record_term_targets(inventory, _term_target_evidence("模型改写")),
        "does not equal the human value",
    )
    assert inventory.to_json_bytes() == before
    assert all(
        item.human_value == "ABB Review"
        for item in inventory.expectations
        if item.kind is ManualConstraintKind.TERM
    )


def check_term_wrong_location_missing_and_duplicate_fail() -> None:
    inventory = inventory_from_bound(_bound())
    evidence = list(_term_delivery_evidence())
    _assert_error(
        lambda: record_term_delivery(inventory, evidence[:1]), "denominator differs"
    )
    _assert_error(
        lambda: record_term_delivery(inventory, [*evidence, evidence[0]]),
        "repeats mapping",
    )
    delivered = record_term_delivery(inventory, evidence)
    targets = list(_term_target_evidence())
    targets[0] = dataclasses.replace(targets[0], physical_page=3)
    _assert_error(
        lambda: record_term_targets(delivered, targets), "wrong page or paragraph"
    )
    targets = list(_term_target_evidence())
    targets[0] = dataclasses.replace(targets[0], paragraph_ref="p2#99")
    _assert_error(
        lambda: record_term_targets(delivered, targets), "wrong page or paragraph"
    )
    targets = list(_term_target_evidence())
    targets[0] = dataclasses.replace(targets[0], mapping_count=2)
    _assert_error(
        lambda: record_term_targets(delivered, targets), "exactly one mapping"
    )
    targets = list(_term_target_evidence())
    targets[0] = dataclasses.replace(targets[0], target_span=None)
    _assert_error(
        lambda: record_term_targets(delivered, targets), "exact target span"
    )


def check_protected_occurrence_is_explicit() -> None:
    inventory = inventory_from_bound(_bound())
    evidence = list(_term_delivery_evidence())
    evidence[1] = dataclasses.replace(
        evidence[1], request_sha256="c" * 64, fixed_asset_ref=None
    )
    _assert_error(
        lambda: record_term_delivery(inventory, evidence),
        "must not enter a request",
    )
    evidence = list(_term_delivery_evidence())
    evidence[1] = dataclasses.replace(evidence[1], fixed_asset_ref=None)
    _assert_error(
        lambda: record_term_delivery(inventory, evidence),
        "untouched asset evidence",
    )


def check_page_policy_matrix_and_consumers() -> None:
    config = load_page_policy_observables()
    assert tuple(config["fields"]) == (
        "translate",
        "chain_eligible",
        "starts_article",
        "opens_article",
        "preserve_line_structure",
        "indent_eligible",
        "repair_profile",
    )
    taxonomy = load_taxonomy()
    for page_type in taxonomy.page_types:
        expected = canonical_sha256(
            {
                "page_kind": page_type.name,
                "policy": page_type.policy,
                "taxonomy_version": taxonomy.version,
            }
        )
        assert page_policy_sha256(page_type.name) == expected

    inventory = record_page_policy_delivery(inventory_from_bound(_bound()))
    _assert_error(
        lambda: finalize_page_policy_targets(inventory), "policy consumers missing"
    )
    for event in (
        "line_split_complete",
        "article_ir_complete",
        "translation_complete",
        "indent_policy_complete",
        "repair_complete",
    ):
        inventory = record_page_policy_event(
            inventory,
            event,
            executed_pages=(2, 3),
            unsupported_pages=(3,) if event == "article_ir_complete" else None,
        )
    assert len(inventory.policy_consumptions) == 2 * 7
    _assert_error(
        lambda: finalize_page_policy_targets(inventory, unsupported_pages=()),
        "unsupported guard",
    )
    inventory = finalize_page_policy_targets(inventory, unsupported_pages=(3,))
    selected = [
        item
        for item in inventory.expectations
        if item.kind is ManualConstraintKind.PAGE_POLICY
        and item.selected_occurrence_refs
    ]
    assert all(
        item.stage_evidence[0].status is ManualConstraintStatus.PASS
        and item.stage_evidence[1].status is ManualConstraintStatus.PASS
        for item in selected
    )
    assert any(
        "guard:same-page-multi-article:unsupported-preserved" in item.stage_evidence[1].evidence_refs
        for item in selected
    )


def check_loaded_but_unexecuted_policy_fails() -> None:
    inventory = record_page_policy_delivery(inventory_from_bound(_bound()))
    _assert_error(
        lambda: record_page_policy_event(
            inventory, "translation_complete", executed_pages=(2,)
        ),
        "did not execute",
    )
    inventory = record_page_policy_event(
        inventory, "translation_complete", executed_pages=(2, 3)
    )
    _assert_error(
        lambda: finalize_page_policy_targets(inventory), "policy consumers missing"
    )


def _drop_delivery() -> tuple[DropCapDeliveryEvidence, ...]:
    candidate = next(
        item for item in _bound().review["drop_caps"] if item["reference"] == "p3#0"
    )
    return (
        DropCapDeliveryEvidence(
            reference="p3#0",
            physical_page=3,
            paragraph_ref="p3#0",
            fingerprint=candidate["fingerprint"],
            decision="keep",
        ),
    )


def _drop_target() -> tuple[DropCapTargetEvidence, ...]:
    return (
        DropCapTargetEvidence(
            reference="p3#0",
            physical_page=3,
            paragraph_ref="p3#0",
            ownership_ref="p3#0:target-fragment-0",
            translated_first_character="评",
            decision="keep",
            flatten_status="applied",
        ),
    )


def check_drop_cap_binding_and_target() -> None:
    inventory = inventory_from_bound(_bound())
    delivery = _drop_delivery()
    stale = dataclasses.replace(delivery[0], fingerprint="0" * 64)
    _assert_error(
        lambda: record_drop_cap_delivery(inventory, (stale,)),
        "stale or ambiguous",
    )
    delivered = record_drop_cap_delivery(inventory, delivery)
    wrong = dataclasses.replace(_drop_target()[0], paragraph_ref="p3#1")
    _assert_error(
        lambda: record_drop_cap_targets(delivered, (wrong,)), "ownership is wrong"
    )
    failed = dataclasses.replace(_drop_target()[0], flatten_status="failed")
    _assert_error(
        lambda: record_drop_cap_targets(delivered, (failed,)),
        "flatten execution point",
    )
    targeted = record_drop_cap_targets(delivered, _drop_target())
    expectation = next(
        item
        for item in targeted.expectations
        if item.kind is ManualConstraintKind.DROP_CAP
        and item.selected_occurrence_refs
    )
    assert expectation.stage_evidence[1].status is ManualConstraintStatus.PASS
    assert expectation.stage_evidence[2].status is ManualConstraintStatus.PENDING
    assert expectation.stage_evidence[3].status is ManualConstraintStatus.PENDING


def check_report_is_bounded_and_canonical() -> None:
    inventory = record_term_targets(
        record_term_delivery(inventory_from_bound(_bound()), _term_delivery_evidence()),
        _term_target_evidence(),
    )
    with tempfile.TemporaryDirectory(prefix="hitl-delivery-") as directory:
        config = SimpleNamespace(
            get_working_file_path=lambda name: str(Path(directory) / name)
        )
        path = write_inventory_report(inventory, config)
        payload = path.read_bytes()
        assert payload == inventory.to_json_bytes()
        decoded = json.loads(payload)
        assert decoded["schema_version"] == "babeldoc.manual-constraint-delivery.v1"
        lowered = payload.lower()
        assert b"raw_provider_response" not in lowered
        assert b"translation prompt" not in lowered
        assert b"model output" not in lowered
        assert payload.endswith(b"\n") and not payload.endswith(b"\n\n")


def check_canonical_expectation_has_one_owner() -> None:
    owners = []
    for path in sorted((ROOT / "babeldoc").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.ClassDef)
            and node.name == "ManualConstraintExpectation"
            for node in ast.walk(tree)
        ):
            owners.append(path.relative_to(ROOT))
    assert owners == [Path("babeldoc/magazine/hitl_expectation.py")], owners


def check_binder_and_builtin_runtime_model_identity_match() -> None:
    values = load_toml_semantic_config(ROOT / "babeldoc.zh-en.toml")
    runtime_model_type = type(
        "OnnxModel",
        (),
        {"__module__": "babeldoc.docvision.doclayout"},
    )
    runtime_values = {**values, "doc_layout_model": runtime_model_type()}
    assert semantic_config_sha256(values) == semantic_config_sha256(runtime_values)


CHECKS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("inventory denominator and human values", check_inventory_denominator_and_human_values),
    ("term delivery and target exactness", check_term_delivery_and_target_exactness),
    ("fake model cannot change human value", check_fake_model_cannot_change_human_value),
    (
        "term wrong location missing and duplicate fail",
        check_term_wrong_location_missing_and_duplicate_fail,
    ),
    ("protected occurrence is explicit", check_protected_occurrence_is_explicit),
    ("page policy matrix and consumers", check_page_policy_matrix_and_consumers),
    ("loaded but unexecuted policy fails", check_loaded_but_unexecuted_policy_fails),
    ("drop cap binding and target", check_drop_cap_binding_and_target),
    ("report is bounded and canonical", check_report_is_bounded_and_canonical),
    ("canonical expectation has one owner", check_canonical_expectation_has_one_owner),
    (
        "binder and built-in runtime model identity match",
        check_binder_and_builtin_runtime_model_identity_match,
    ),
)


def main() -> int:
    for name, check in CHECKS:
        check()
        print(f"PASS: {name}")
    print(f"PASS: manual constraint delivery ({len(CHECKS)}/{len(CHECKS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
