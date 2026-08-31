"""The bounded repair loop: decide, act, measure, and keep only what improved.

One iteration walks the declared rounds once -- one round per detector kind, in
the order ``configs/decision_rounds.json`` gives -- and each round asks the model
for a nomination, holds it against the deterministic admission rule, and applies
what survives. At the end of the iteration the document is measured again and
the whole iteration is accepted or rolled back as one thing.

Two properties are what make this a loop rather than a sequence of hopeful
edits.

The first is that acceptance is measured over the iteration, not the action. An
action that fixes one defect and opens another is not an improvement, and it is
only visible as such once everything the iteration did is on the page together.
So the comparison is run once, at the end, against the whole iteration's work,
and a rejected iteration is rolled back entire -- not the last action, all of
them -- and the loop stops. Rolling back and continuing would mean the next
iteration starts from a document the loop has already failed to improve, and
the same decision would be taken again.

The second is that everything is bounded in advance: how many iterations, how
many actions inside one, how many findings a round may consider, how many
paragraphs the whole run may touch. Every stop has a name from a closed set, so
"the loop did nothing" is always distinguishable from "the loop had nothing to
do" and from "the loop ran out of budget", which are three different facts about
a document and were previously one silence.

Nothing here decides what an action does or whether a finding may be acted on.
The first is the action's, the second is the admission rule's, and this module
may overrule neither.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from babeldoc.magazine import acceptance
from babeldoc.magazine import llm_decide
from babeldoc.magazine import minimal_detection
from babeldoc.magazine import minimal_repair
from babeldoc.magazine import transaction as transaction_module

logger = logging.getLogger(__name__)

TERMINATION_NAME = "termination.json"
SCHEMA_VERSION = "mapek-loop.v1"

# Why a run stopped. Closed: a stop outside this set is a bug, not a new
# outcome, and the distinctions are the point -- "nothing to do" and "nothing
# was allowed" and "out of budget" are three different facts.
NO_ISSUES = "no_issues"
ALL_CANDIDATES_REFUSED = "all_candidates_refused"
ITERATION_REJECTED = "iteration_rejected"
BUDGET_ITERATIONS = "budget_iterations"
BUDGET_ACTIONS = "budget_actions"
BUDGET_ELEMENTS = "budget_elements"
NO_USABLE_DECISION = "no_usable_decision"
CONVERGED_ALL_TREATED = "converged_all_treated"
TERMINATIONS = (
    NO_ISSUES,
    ALL_CANDIDATES_REFUSED,
    ITERATION_REJECTED,
    BUDGET_ITERATIONS,
    BUDGET_ACTIONS,
    BUDGET_ELEMENTS,
    NO_USABLE_DECISION,
    CONVERGED_ALL_TREATED,
)

# Which action answers a nomination, and which rule decides whether it may.
_ADMISSIONS = {
    minimal_repair.TRANSLATE_ORPHAN: minimal_repair.admits_orphan,
    minimal_repair.REFIT_OWNED: minimal_repair.admits_refit,
    minimal_repair.CONTAIN_HEADING: minimal_repair.admits_heading,
    minimal_repair.RETYPESET_REGION: minimal_repair.admits_region,
    minimal_repair.REALLOCATE_CHAIN: minimal_repair.admits_chain_reallocation,
}


class RepairLoopError(ValueError):
    """Raised when the loop's inputs or configuration are malformed."""


@dataclass(frozen=True)
class LoopBudget:
    """Everything one run is bounded by, from the one configuration."""

    max_iterations: int
    max_actions_per_iteration: int
    max_candidate_issues_per_round: int
    max_affected_elements_per_run: int


@dataclass
class AppliedAction:
    """One action that reached the document, and what it wrote."""

    iteration: int
    kind: str
    action: str
    issue_ids: tuple[str, ...]
    parameters: dict
    reason: str
    written_refs: tuple[str, ...]
    pages: tuple[int, ...]

    def as_record(self) -> dict:
        return {
            "iteration": self.iteration,
            "kind": self.kind,
            "action": self.action,
            "issue_ids": list(self.issue_ids),
            "parameters": dict(self.parameters),
            "reason": self.reason,
            "written_refs": list(self.written_refs),
            "pages": list(self.pages),
        }


@dataclass
class LoopResult:
    """What the run did, why it stopped, and what it left standing."""

    termination: str
    iterations: int
    accepted_actions: list[AppliedAction] = field(default_factory=list)
    refusals: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    acceptances: list[dict] = field(default_factory=list)
    affected_elements: int = 0
    translator_requests: int = 0
    detection_passes_added: int = 0
    final_detection: object | None = None
    rolled_back: bool = False

    @property
    def accepted(self) -> bool:
        return bool(self.accepted_actions)

    def as_record(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "termination": self.termination,
            "iterations": self.iterations,
            "rolled_back": self.rolled_back,
            "affected_elements": self.affected_elements,
            "translator_requests": self.translator_requests,
            "detection_passes_added": self.detection_passes_added,
            "accepted_actions": [item.as_record() for item in self.accepted_actions],
            "refusals": list(self.refusals),
            "decisions": list(self.decisions),
            "acceptances": list(self.acceptances),
            "residual_issues": (
                []
                if self.final_detection is None
                else [
                    {
                        "id": issue.id,
                        "kind": issue.kind,
                        "page": issue.page,
                        "severity": issue.severity,
                        "paragraph_refs": list(issue.paragraph_refs),
                    }
                    for issue in self.final_detection.issues
                ]
            ),
        }


def load_budget(config=None) -> LoopBudget:
    """The run's ceilings, read from the one file that declares them."""
    raw = json.loads(
        minimal_repair.CONFIG_PATH.read_text(encoding="utf-8")
        if config is None
        else config
    )
    decide = llm_decide.parse_decide_config(raw, minimal_repair.CONFIG_PATH.name)
    return LoopBudget(
        max_iterations=int(
            minimal_repair._bounded_number(raw, "max_iterations", integer=True)
        ),
        max_actions_per_iteration=int(
            minimal_repair._bounded_number(
                raw, "max_actions_per_iteration", integer=True
            )
        ),
        # The same ceiling the decision step reads, not a second declaration.
        max_candidate_issues_per_round=decide.max_issues_per_round,
        max_affected_elements_per_run=int(
            minimal_repair._bounded_number(
                raw, "max_affected_elements_per_run", integer=True
            )
        ),
    )


def _candidates(issues, kind: str, limit: int) -> list:
    """The findings of one kind a round may consider, worst first."""
    of_kind = [issue for issue in issues if issue.kind == kind]
    of_kind.sort(key=lambda issue: issue.sort_key())
    return of_kind[:limit]


def _admit(
    action: str,
    issue,
    docs,
    baseline,
    article_document_ir,
    translation_config,
    flow_refs,
    config,
) -> str | None:
    """Why this nomination may not be acted on, or None when it may."""
    rule = _ADMISSIONS.get(action)
    if rule is None:
        return "action_has_no_admission_rule"
    if action == minimal_repair.TRANSLATE_ORPHAN:
        # The orphan rule is the one that also has to know what the run may
        # spend a translator request on, so it takes the run configuration.
        return rule(
            issue,
            docs,
            baseline,
            article_document_ir,
            translation_config,
            flow_refs,
            config,
        )
    return rule(issue, docs, baseline, article_document_ir, flow_refs, config)


def _apply(
    action: str,
    issue,
    docs,
    baseline,
    article_document_ir,
    typesetter,
    translation_config,
    flow_refs,
    config,
    parameters: dict,
) -> tuple[tuple, int]:
    """Run one admitted action, returning what it wrote and what it spent.

    The second number is translator requests. Only one action asks for text
    that does not exist yet, and the run report accounts for every request
    separately from the ordinary translation, so an action that spends one has
    to say so rather than have it counted as ordinary work.
    """
    if action == minimal_repair.TRANSLATE_ORPHAN:
        target, requests = minimal_repair._translate_orphan(
            issue,
            docs,
            baseline,
            article_document_ir,
            typesetter,
            translation_config,
            flow_refs,
            config,
        )
        return (target,), requests
    if action == minimal_repair.CONTAIN_HEADING:
        target = minimal_repair._contain_heading(
            issue,
            docs,
            baseline,
            article_document_ir,
            typesetter,
            flow_refs,
            config,
            minimum_scale=parameters.get("heading_min_scale"),
            maximum_lines=(
                None
                if parameters.get("heading_max_lines") is None
                else int(parameters["heading_max_lines"])
            ),
        )
        return (target,), 0
    if action == minimal_repair.RETYPESET_REGION:
        return (
            minimal_repair._retypeset_region(
                issue,
                docs,
                baseline,
                article_document_ir,
                typesetter,
                flow_refs,
                config,
                minimum_scale=parameters.get("region_min_scale"),
            ),
            0,
        )
    if action == minimal_repair.REALLOCATE_CHAIN:
        return (
            minimal_repair._reallocate_chain_cut(
                issue,
                docs,
                baseline,
                article_document_ir,
                typesetter,
                flow_refs,
                config,
                language=getattr(translation_config, "lang_out", None),
            ),
            0,
        )
    if action == minimal_repair.REFIT_OWNED:
        return (
            (
                minimal_repair._refit_target(
                    issue,
                    docs,
                    baseline,
                    article_document_ir,
                    typesetter,
                    flow_refs,
                    config,
                    translation_config=translation_config,
                    clearance_pt=parameters.get("clearance_pt"),
                ),
            ),
            0,
        )
    raise RepairLoopError(f"the loop cannot apply {action!r}")


def repair_loop(
    before: minimal_detection.DetectionResult,
    docs,
    article_document_ir,
    baseline: minimal_detection.DetectionBaseline,
    typesetter,
    translation_config,
    flow_report,
    detect_after: Callable[[str | None], minimal_detection.DetectionResult],
    *,
    client=None,
    config=None,
    budget: LoopBudget | None = None,
    decide_config=None,
    working_dir: Path | str | None = None,
) -> LoopResult:
    """Run bounded iterations, keeping only an iteration that improved."""
    if not isinstance(before, minimal_detection.DetectionResult):
        raise RepairLoopError("the loop requires the before DetectionResult")
    if baseline.document_identity != id(docs):
        raise RepairLoopError("the loop baseline belongs to another document")
    if not callable(detect_after):
        raise RepairLoopError("detect_after must be callable")
    config = minimal_repair.load_repair_config() if config is None else config
    decide_config = (
        llm_decide.load_decide_config() if decide_config is None else decide_config
    )
    budget = load_budget() if budget is None else budget
    working_dir = (
        before.report_path.parent if working_dir is None else Path(working_dir)
    )
    flow_refs = minimal_repair._flow_refs(flow_report, article_document_ir)
    policy = acceptance.load_acceptance_policy()
    order = llm_decide.kind_order()

    result = LoopResult(termination=NO_ISSUES, iterations=0, final_detection=before)
    if not before.issues:
        result.final_detection = minimal_detection.mirror_after(
            before, working_dir, restored_from_before=False, reason=NO_ISSUES
        )
        _write_termination(working_dir, result)
        return result

    standing = before
    considered_any = False
    for iteration in range(1, budget.max_iterations + 1):
        snapshot = transaction_module.TransactionSnapshot.capture(docs)
        applied: list[AppliedAction] = []
        actions_left = budget.max_actions_per_iteration
        stop = None
        abandoned = False

        for kind in order:
            if actions_left <= 0:
                stop = BUDGET_ACTIONS
                break
            if result.affected_elements >= budget.max_affected_elements_per_run:
                stop = BUDGET_ELEMENTS
                break
            candidates = _candidates(
                standing.issues, kind, budget.max_candidate_issues_per_round
            )
            if not candidates:
                continue
            considered_any = True
            if client is None:
                continue
            decision = llm_decide.decide_round(
                kind,
                candidates,
                client,
                decide_config,
                working_dir=working_dir,
                iteration=iteration,
            )
            result.decisions.append(
                {"iteration": iteration, **decision.as_record()}
            )
            if decision.outcome == llm_decide.ABANDONED_AFTER_RETRY:
                abandoned = True
            if not decision.acts:
                continue
            offered = {issue.id: issue for issue in candidates}
            for issue_id in decision.issue_ids:
                if actions_left <= 0:
                    stop = BUDGET_ACTIONS
                    break
                if (
                    result.affected_elements
                    >= budget.max_affected_elements_per_run
                ):
                    stop = BUDGET_ELEMENTS
                    break
                issue = offered.get(issue_id)
                if issue is None:
                    continue
                refused = _admit(
                    decision.action,
                    issue,
                    docs,
                    baseline,
                    article_document_ir,
                    translation_config,
                    flow_refs,
                    config,
                )
                if refused is not None:
                    result.refusals.append(
                        {
                            "iteration": iteration,
                            "kind": kind,
                            "action": decision.action,
                            "issue_id": issue_id,
                            "reason": refused,
                        }
                    )
                    continue
                try:
                    targets, requests = _apply(
                        decision.action,
                        issue,
                        docs,
                        baseline,
                        article_document_ir,
                        typesetter,
                        translation_config,
                        flow_refs,
                        config,
                        dict(decision.parameters),
                    )
                except minimal_repair._RepairRefusalError as refusal:
                    result.refusals.append(
                        {
                            "iteration": iteration,
                            "kind": kind,
                            "action": decision.action,
                            "issue_id": issue_id,
                            "reason": refusal.reason,
                        }
                    )
                    continue
                # An action costs one from the action budget and one from the
                # element budget per paragraph it wrote, charged the moment it
                # lands rather than at the end of the iteration.
                actions_left -= 1
                result.affected_elements += len(targets)
                result.translator_requests += requests
                applied.append(
                    AppliedAction(
                        iteration=iteration,
                        kind=kind,
                        action=decision.action,
                        issue_ids=(issue_id,),
                        parameters=dict(decision.parameters),
                        reason=decision.reason,
                        written_refs=tuple(
                            target.physical_ref for target in targets
                        ),
                        pages=tuple(
                            sorted({target.local_page for target in targets})
                        ),
                    )
                )
            if stop is not None:
                break

        if not applied:
            snapshot.not_executed()
            result.iterations = iteration
            # Nothing was applied, and why matters. A round the model gave up
            # on is not a round it decided to leave alone, and neither is a
            # round whose every nomination the admission rule threw out.
            if stop is not None:
                result.termination = stop
            elif client is None or abandoned:
                result.termination = NO_USABLE_DECISION
            elif result.refusals:
                result.termination = ALL_CANDIDATES_REFUSED
            else:
                # Every round was looked at and every one chose to act on
                # nothing, which is the loop saying it is finished.
                result.termination = CONVERGED_ALL_TREATED
            break

        after = detect_after(None)
        result.detection_passes_added += 1
        comparison = acceptance.compare_issues(
            standing.issues, after.issues, policy
        )
        result.acceptances.append(
            {"iteration": iteration, **comparison.as_record()}
        )
        if not comparison.accepted:
            # The iteration is rolled back entire, not action by action: it is
            # the iteration that was measured and the iteration that failed.
            snapshot.rollback()
            result.iterations = iteration
            result.termination = ITERATION_REJECTED
            result.rolled_back = True
            result.final_detection = detect_after(None)
            result.detection_passes_added += 1
            break

        snapshot.commit()
        result.accepted_actions.extend(applied)
        result.iterations = iteration
        standing = after
        result.final_detection = after
        if not after.issues:
            result.termination = NO_ISSUES
            break
        if stop is not None:
            result.termination = stop
            break
        result.termination = (
            BUDGET_ITERATIONS
            if iteration == budget.max_iterations
            else CONVERGED_ALL_TREATED
        )

    if not result.accepted_actions:
        # A run that kept nothing still owes the same after-sidecar the one-shot
        # pass writes, so the finished run reads the same whichever ran.
        result.final_detection = minimal_detection.mirror_after(
            before,
            working_dir,
            restored_from_before=result.rolled_back,
            reason=result.termination,
        )
    _write_termination(working_dir, result)
    return result


def _write_termination(working_dir: Path | str, result: LoopResult) -> Path:
    """File what the run did beside the findings it left standing."""
    path = Path(working_dir) / TERMINATION_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.as_record(), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path
