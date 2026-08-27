"""Fast C19 checks for one-action repair methodology and strict acceptance."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import acceptance
from babeldoc.magazine import fixed_assets
from babeldoc.magazine import run_trace
from babeldoc.magazine.detectors import DETECTORS
from babeldoc.magazine.detectors import detector_kinds
from babeldoc.magazine.detectors.base import Issue
from babeldoc.magazine.element_roles import ElementRole
from babeldoc.magazine.repair_contract import ACTION_DETECTOR_CLOSURE_VERSION
from babeldoc.magazine.repair_contract import RepairAction
from babeldoc.magazine.repair_contract import RepairContractError
from babeldoc.magazine.repair_contract import RepairDecision
from babeldoc.magazine.repair_contract import RepairIssueEvidence
from babeldoc.magazine.repair_contract import RepairIssueKind
from babeldoc.magazine.repair_contract import RepairKnowledgeState
from babeldoc.magazine.repair_contract import RepairTarget
from babeldoc.magazine.repair_contract import StaleRepairStateError
from babeldoc.magazine.repair_contract import require_one_decision
from babeldoc.magazine.repair_detector_closure import CONFIG_PATH as CLOSURE_PATH
from babeldoc.magazine.repair_detector_closure import DetectorClosureRun
from babeldoc.magazine.repair_detector_closure import load_repair_detector_closure
from babeldoc.magazine.repair_detector_closure import parse_repair_detector_closure
from babeldoc.magazine.transaction import TransactionSnapshot

GATE_SET = "fast"
ROOT = Path(__file__).resolve().parents[1]
POLICY = acceptance.load_acceptance_policy()


def measured(issue_id: str, kind: str, amount, severity: str = "medium"):
    return acceptance.measured_issue(
        issue_id,
        kind,
        severity,
        {"amount": amount},
        ("amount",),
        schema_version=POLICY.schema_version,
    )


def compare(before, after, targets, **overrides):
    flags = {
        "closure_complete": True,
        "conservation_holds": True,
        "touched_scope_valid": True,
    }
    flags.update(overrides)
    return acceptance.compare_repair_action(
        before,
        after,
        POLICY,
        action=RepairAction.RESOLVE_TEXT_COLLISION,
        target_issue_ids=targets,
        **flags,
    )


def _state(document_digest: str = "a" * 64) -> RepairKnowledgeState:
    return RepairKnowledgeState(
        document_semantic_sha256=document_digest,
        physical_page_selection_sha256="b" * 64,
        article_knowledge_state_sha256="c" * 64,
        run_trace_generation=2,
        issues=(
            RepairIssueEvidence(
                issue_id="collision:p1:p1#0+p1#1",
                kind=RepairIssueKind.TEXT_TEXT_COLLISION,
                physical_page=1,
                article_refs=("article-1",),
                element_refs=("p1#0", "p1#1"),
                text_excerpt="bounded collision",
                metric_vector=(("coverage", 0.8),),
            ),
        ),
        page_policies=((1, "d" * 64),),
        article_regions=(("article-1", ("legal-slot-1",)),),
        element_roles=(("p1#0", ElementRole.BODY), ("p1#1", ElementRole.BODY)),
        chain_states=(),
        legal_slot_digests=(("legal-slot-1", "e" * 64),),
        fixed_asset_inventory_sha256="f" * 64,
        manual_constraint_refs=("manual:term:1",),
        protected_refs=("p1#9",),
        allowed_actions=(RepairAction.RESOLVE_TEXT_COLLISION,),
        action_detector_closure_version=ACTION_DETECTOR_CLOSURE_VERSION,
        limits=(("max_actions", 3), ("max_touched_elements", 4)),
    )


def _decision(state: RepairKnowledgeState) -> RepairDecision:
    return RepairDecision(
        action=RepairAction.RESOLVE_TEXT_COLLISION,
        issue_ids=("collision:p1:p1#0+p1#1",),
        target=RepairTarget(
            physical_pages=(1,),
            article_refs=("article-1",),
            element_refs=("p1#0",),
            legal_slot_refs=("legal-slot-1",),
        ),
        parameters=(("collision_axis", "least_overlap"),),
        state_sha256=state.sha256(),
    )


def box(x: float, y: float, x2: float, y2: float) -> il_version_1.Box:
    return il_version_1.Box(x=x, y=y, x2=x2, y2=y2)


def document() -> il_version_1.Document:
    paragraph = il_version_1.PdfParagraph(
        box=box(10, 10, 80, 22),
        unicode="source text",
        layout_label="plain text",
        drop_cap_decision="keep",
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        unicode="source text",
                        pdf_style=il_version_1.PdfStyle(
                            font_id="F0", font_size=10
                        ),
                    )
                )
            )
        ],
    )
    page = il_version_1.Page(
        page_number=0,
        pdf_paragraph=[paragraph],
        pdf_figure=[il_version_1.PdfFigure(box=box(2, 2, 8, 8))],
        cropbox=il_version_1.Cropbox(box=box(0, 0, 100, 100)),
        mediabox=il_version_1.Mediabox(box=box(0, 0, 100, 100)),
    )
    return il_version_1.Document(page=[page], total_pages=1)


def _raises(error_type, callback) -> bool:
    try:
        callback()
    except error_type:
        return True
    return False


def methodology_checks() -> dict[str, bool]:
    target_a = measured("collision:p1:a", "text_text_collision", 8)
    target_b = measured("collision:p1:b", "text_text_collision", 6)
    unrelated = measured("bounds:p1:c", "out_of_page", 4, "high")

    case_a = compare(
        (target_a, target_b),
        (measured(target_a.id, target_a.kind, 3),),
        (target_a.id,),
    )
    case_b = compare(
        (target_a,),
        (measured(target_a.id, target_a.kind, 3),),
        (target_a.id,),
    )
    case_c = compare(
        (target_a, target_b),
        (measured(target_a.id, target_a.kind, 8),),
        (target_b.id,),
    )
    case_d = compare(
        (target_a, target_b),
        (measured(target_a.id, target_a.kind, 9),),
        (target_b.id,),
    )
    case_e = compare((target_a, unrelated), (unrelated,), (target_a.id,))
    case_f = compare(
        (target_a, unrelated),
        (measured(unrelated.id, unrelated.kind, 5, "high"),),
        (target_a.id,),
    )
    case_g = compare(
        (target_a, target_b, unrelated),
        (unrelated, measured("fragment:p1:new", "fragment_cluster", 2, "low")),
        (target_a.id, target_b.id),
    )

    duplicate = compare(
        (target_a, target_a, target_b), (), (target_a.id, target_b.id)
    )
    changed_kind = compare(
        (target_a, target_b),
        (measured(target_a.id, "out_of_page", 2),),
        (target_b.id,),
    )
    nonfinite = compare(
        (target_a, target_b),
        (measured(target_a.id, target_a.kind, float("nan")),),
        (target_b.id,),
    )
    missing_metric = acceptance.measured_issue(
        target_a.id,
        target_a.kind,
        "medium",
        {},
        (),
        schema_version=POLICY.schema_version,
    )
    uncomparable = compare(
        (target_a, target_b), (missing_metric,), (target_b.id,)
    )

    state = _state()
    decision = _decision(state)
    next_state = _state("1" * 64)
    next_decision = _decision(next_state)
    state.preflight(decision)
    next_state.preflight(next_decision)

    closure = load_repair_detector_closure()
    closure_run = DetectorClosureRun(
        RepairAction.RESOLVE_TEXT_COLLISION,
        closure.schema_version,
        closure.complete_detector_suite,
        True,
    )
    closure_run.require_complete(closure)
    closure_raw = json.loads(CLOSURE_PATH.read_text(encoding="utf-8"))
    missing_action = copy.deepcopy(closure_raw)
    missing_action["closures"].pop("no_action")
    missing_conservation = copy.deepcopy(closure_raw)
    missing_conservation["closures"]["resolve_text_collision"][
        "conservation_detectors"
    ].remove("fixed_asset_drift")

    docs = document()
    trace = run_trace.RunTrace()
    inventory = fixed_assets.build_inventory(docs, run_trace=trace)
    article_state = {"generation": 5, "sha256": "state-before"}
    manual = [{"expectation": "manual:1", "status": "pending"}]
    repair_records = [{"status": "baseline"}]
    snapshot = TransactionSnapshot.capture(
        docs,
        run_trace=trace,
        fixed_inventory=inventory,
        fixed_inventory_builder=lambda: fixed_assets.build_inventory(
            docs, run_trace=trace
        ),
        article_state=article_state,
        manual_expectations=manual,
        repair_records=repair_records,
        repair_knowledge_state=state,
    )
    before_generation = trace.current_generation
    snapshot.begin_generation("methodology_rollback")
    docs.page[0].pdf_paragraph[0].unicode = "mutated"
    article_state["generation"] = 6
    manual[0]["status"] = "pass"
    repair_records.append({"status": "partial"})
    rollback = snapshot.rollback()

    stable_before = Issue(
        kind="out_of_page",
        page=1,
        paragraph_refs=("p1#0",),
        geometry={"box": [0, 0, 10, 10]},
        severity="high",
        evidence={"overflow_max": 4.0},
        detector="out_of_page",
    )
    stable_after = Issue(
        kind="out_of_page",
        page=1,
        paragraph_refs=("p1#0",),
        geometry={"box": [1, 0, 11, 10]},
        severity="high",
        evidence={"overflow_max": 2.0},
        detector="out_of_page",
    )

    source = (ROOT / "babeldoc/magazine/react/controller.py").read_text(
        encoding="utf-8"
    )
    prepare_at = source.index("prepared = self._prepare_round")
    generation_at = source.index(
        'transaction.begin_generation(f"react_iteration_{iteration}")'
    )

    return {
        "A strict count drop and every target-kind persistent improvement commits": case_a.accepted,
        "B unchanged count with metric improvement rolls back": not case_b.accepted
        and "total_issue_count_did_not_decrease" in case_b.reasons,
        "C target-kind persistent unchanged rolls back": not case_c.accepted
        and "target_kind_persistent_issue_not_improved" in case_c.reasons,
        "D target-kind persistent worsening rolls back": not case_d.accepted,
        "E unrelated persistent issue may remain unchanged": case_e.accepted,
        "F unrelated persistent issue may not worsen": not case_f.accepted
        and "non_target_persistent_issue_worsened" in case_f.reasons,
        "G every new issue rejects the action": not case_g.accepted
        and "new_issue_introduced" in case_g.reasons,
        "H duplicate changed-kind NaN and missing metrics reject": all(
            not result.accepted
            for result in (duplicate, changed_kind, nonfinite, uncomparable)
        ),
        "I one iteration rejects a batch of two actions": _raises(
            RepairContractError,
            lambda: require_one_decision((decision, decision)),
        ),
        "J next action binds the newly committed state digest": (
            decision.state_sha256 != next_decision.state_sha256
            and _raises(
                StaleRepairStateError,
                lambda: next_state.preflight(decision),
            )
        ),
        "K detector closure is complete and malformed closure fails startup": (
            set(closure.complete_detector_suite) == set(DETECTORS)
            and _raises(
                ValueError,
                lambda: parse_repair_detector_closure(
                    missing_action,
                    "missing-action",
                    known_detectors=tuple(DETECTORS),
                    known_issue_kinds=detector_kinds(),
                ),
            )
            and _raises(
                ValueError,
                lambda: parse_repair_detector_closure(
                    missing_conservation,
                    "missing-conservation",
                    known_detectors=tuple(DETECTORS),
                    known_issue_kinds=detector_kinds(),
                ),
            )
        ),
        "L rollback restores document state trace assets manual and records": (
            rollback["rollback_verification"]["verified"]
            and docs.page[0].pdf_paragraph[0].unicode == "source text"
            and article_state == {"generation": 5, "sha256": "state-before"}
            and manual == [{"expectation": "manual:1", "status": "pending"}]
            and repair_records == [{"status": "baseline"}]
            and trace.current_generation == before_generation
            and rollback["before"]["repair_knowledge_state"] == state.sha256()
            and rollback["rollback_verification"]["restored"][
                "repair_knowledge_state"
            ]
            == state.sha256()
        ),
        "M stable issue identity excludes geometry and current metrics": (
            stable_before.id == stable_after.id
        ),
        "N full after suite retains unrelated findings and closure cannot omit them": (
            case_e.accepted
            and not compare(
                (target_a, unrelated),
                (),
                (target_a.id,),
                closure_complete=False,
            ).accepted
        ),
        "controller prepares one round before opening its sole generation": (
            "kind, offered = plan[0]" in source
            and prepare_at < generation_at
            and "compare_repair_action" in source
        ),
    }


def main() -> int:
    checks = methodology_checks()
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    passed = sum(checks.values())
    if passed != len(checks):
        print(f"spec_check_repair_methodology_contract: {passed}/{len(checks)} passed")
        return 1
    print(f"spec_check_repair_methodology_contract: PASS {passed}/{len(checks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
