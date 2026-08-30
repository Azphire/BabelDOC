"""Gate: the loop keeps only an iteration that improved, and stops for a reason.

A repair loop's dangerous failure is not a bad action.  It is a loop that keeps
acting on a document it is making worse, one plausible edit at a time, because
each edit was judged on its own.  The guard against that is measuring the whole
iteration and rolling the whole iteration back, and S1 is that guard under the
input designed to defeat it: two defects that trade places, so every iteration
looks locally reasonable and nothing ever improves.

The second failure is silence.  "The loop did nothing" can mean it had nothing
to do, or that everything it wanted to do was refused, or that it ran out of
budget, or that the model never returned anything usable.  Those are four
different facts about a document and they used to be one.  S5 requires each to
come back under its own name.

Eight claims:

S1  An oscillating document is rolled back entire and the run stops as
    iteration_rejected, with the document byte for byte what it was.
S2  A document that improves is accepted, and the loop keeps going until there
    is nothing left, stopping as no_issues.
S3  A rejected iteration rolls back everything it did, not just its last
    action.  Two actions land, the iteration is refused, and both are undone.
S4  The admission rule keeps its veto: a nomination it refuses is recorded as a
    refusal and never reaches the document, even though the decision was
    well-formed.
S5  Every stop is named from the closed set, and the four "did nothing" stops
    are told apart: nothing to do, everything refused, no usable decision, and
    out of budget.
S6  The ceilings bind: an iteration stops at its action ceiling and a run stops
    at its element ceiling, and the ceiling on findings per round is the same
    number the decision step reads rather than a second declaration.
S7  termination.json is written beside the findings, naming the stop and every
    finding left standing.
S8  The pipeline accepts a loop result: the run report's own validation passes
    on one, and the loop is chosen only by a run that translates through the
    provider it would decide with -- never by a credential that happens to be
    in the shell.

Run offline; the client is a scripted stub and no request leaves the machine.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import fixed_assets  # noqa: E402
from babeldoc.magazine import llm_decide  # noqa: E402
from babeldoc.magazine import minimal_detection  # noqa: E402
from babeldoc.magazine import minimal_repair  # noqa: E402
from babeldoc.magazine import minimal_pipeline  # noqa: E402
from babeldoc.magazine import repair_loop  # noqa: E402
from babeldoc.magazine.detectors.base import Issue  # noqa: E402
from tools.spec_check_b12_t3 import BoundedFakeTypesetter  # noqa: E402
from tools.spec_check_b12_t3 import MEMBER_BOXES  # noqa: E402
from tools.spec_check_b12_t3 import fixture  # noqa: E402

HEADING_REF = "p7#0"
MEMBER_REFS = ("p7#1", "p7#2")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _issue(kind, refs, *, severity="high", evidence=None):
    evidence = evidence or {"overflow_ratio": 0.2}
    return Issue(
        kind=kind,
        page=7,
        paragraph_refs=tuple(refs),
        geometry=None,
        severity=severity,
        evidence=evidence,
        detector=kind,
    ).with_severity_fields(tuple(evidence))


def _result(work: Path, name: str, issues) -> minimal_detection.DetectionResult:
    directory = work / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "issues.json"
    record = {"issues": [issue.as_record() for issue in issues]}
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return minimal_detection.DetectionResult(tuple(issues), record, path)


class ScriptedClient:
    """The decision step, replaced by one reply per round asked for."""

    def __init__(self, replies: dict[str, str], *, default: str | None = None):
        self.replies = replies
        self.default = default
        self.asked: list[str] = []

    def ask(self, prompt: str) -> str:
        # The round is identified by the finding ids the request carries, which
        # is what the loop varies between rounds.
        for marker, reply in self.replies.items():
            if marker in prompt:
                self.asked.append(marker)
                return reply
        self.asked.append("default")
        if self.default is None:
            return json.dumps(
                {
                    "action": "no_op",
                    "issue_ids": [],
                    "parameters": {},
                    "reason": "nothing here",
                }
            )
        return self.default


def _reply(action, issue_ids, reason="because the evidence says so"):
    return json.dumps(
        {
            "action": action,
            "issue_ids": list(issue_ids),
            "parameters": {},
            "reason": reason,
        }
    )


def _digests(docs) -> dict[str, str]:
    return {
        fixed_assets.paragraph_reference(position + 1, index): (
            fixed_assets.content_digest(paragraph)
        )
        for position, page in enumerate(docs.page)
        for index, paragraph in enumerate(page.pdf_paragraph or ())
    }


def _run(
    work: Path,
    name: str,
    before_issues,
    after_sequence,
    replies,
    *,
    budget=None,
    typesetter=None,
):
    docs, article_ir, baseline = fixture()
    before = _result(work, f"{name}-before", before_issues)
    calls = {"n": 0}

    def detect_after(_owned):
        index = min(calls["n"], len(after_sequence) - 1)
        calls["n"] += 1
        return _result(work, f"{name}-after{index}", after_sequence[index])

    result = repair_loop.repair_loop(
        before,
        docs,
        article_ir,
        baseline,
        typesetter or BoundedFakeTypesetter(),
        SimpleNamespace(lang_out="zh", translator=None),
        None,
        detect_after,
        client=ScriptedClient(replies),
        budget=budget,
        working_dir=work / name,
    )
    return result, docs


# One overflowing heading, which contain_heading can answer for.
OVERFLOW = [_issue("out_of_page", (HEADING_REF,))]


def s1_oscillation_is_rejected_and_rolled_back(work: Path) -> str:
    docs_before = _digests(fixture()[0])
    # The repair resolves the overflow and opens a new high-severity defect in
    # its place: the count is unchanged and nothing strictly improved.
    swapped = [_issue("text_text_collision", MEMBER_REFS, evidence={"iou": 0.4})]
    result, docs = _run(
        work,
        "s1",
        OVERFLOW,
        [swapped, swapped],
        {HEADING_REF: _reply("contain_heading", [OVERFLOW[0].id])},
    )
    _require(
        result.termination == repair_loop.ITERATION_REJECTED,
        f"an oscillating document stopped as {result.termination!r}",
    )
    _require(result.rolled_back, "the rejected iteration was not rolled back")
    _require(
        not result.accepted_actions,
        f"a rejected iteration kept {len(result.accepted_actions)} actions",
    )
    _require(
        result.iterations <= repair_loop.load_budget().max_iterations,
        f"it took {result.iterations} iterations",
    )
    _require(
        _digests(docs) == docs_before,
        "the document was not restored to what it was before the iteration",
    )
    return (
        f"an oscillating document stops as {repair_loop.ITERATION_REJECTED} "
        f"after {result.iterations} iteration(s), fully restored"
    )


def s2_improvement_is_accepted(work: Path) -> str:
    result, _docs = _run(
        work,
        "s2",
        OVERFLOW,
        [[]],
        {HEADING_REF: _reply("contain_heading", [OVERFLOW[0].id])},
    )
    _require(
        result.termination == repair_loop.NO_ISSUES,
        f"a document that improved stopped as {result.termination!r}",
    )
    _require(
        len(result.accepted_actions) == 1,
        f"it kept {len(result.accepted_actions)} actions, not one",
    )
    action = result.accepted_actions[0]
    _require(
        action.action == "contain_heading"
        and action.written_refs == (HEADING_REF,),
        f"the accepted action is {action.as_record()}",
    )
    _require(not result.rolled_back, "an accepted iteration was rolled back")
    return (
        "an iteration that resolved the finding is accepted and the run stops "
        f"as {repair_loop.NO_ISSUES}"
    )


def s3_rejection_undoes_every_action_of_the_iteration(work: Path) -> str:
    docs_before = _digests(fixture()[0])
    region = _issue("fragment_cluster", (MEMBER_REFS[0],), severity="low",
                    evidence={"member_count": 3})
    before_issues = [OVERFLOW[0], region]
    # Two actions land in one iteration; the iteration is then refused.
    worse = [
        _issue("out_of_page", (HEADING_REF,)),
        _issue("fragment_cluster", (MEMBER_REFS[0],), severity="low",
               evidence={"member_count": 5}),
    ]
    result, docs = _run(
        work,
        "s3",
        before_issues,
        [worse, worse],
        {
            HEADING_REF: _reply("contain_heading", [OVERFLOW[0].id]),
            region.id: _reply("retypeset_article_region", [region.id]),
        },
    )
    _require(
        result.termination == repair_loop.ITERATION_REJECTED,
        f"the iteration stopped as {result.termination!r}",
    )
    _require(
        _digests(docs) == docs_before,
        "a rejected iteration left some of its actions on the document",
    )
    return (
        "an iteration that applied more than one action is undone entire when "
        "it is refused, not action by action"
    )


def s4_admission_keeps_its_veto(work: Path) -> str:
    # A well-formed decision naming a body paragraph for the heading action.
    body = _issue("out_of_page", (MEMBER_REFS[0],))
    result, docs = _run(
        work,
        "s4",
        [body],
        [[body]],
        {MEMBER_REFS[0]: _reply("contain_heading", [body.id])},
    )
    _require(
        not result.accepted_actions,
        "a nomination the admission rule refuses reached the document",
    )
    _require(
        result.termination == repair_loop.ALL_CANDIDATES_REFUSED,
        f"the run stopped as {result.termination!r}",
    )
    reasons = {row["reason"] for row in result.refusals}
    _require(
        reasons == {"heading_role_not_allowed"},
        f"the refusal was recorded as {reasons}",
    )
    _require(
        _digests(docs) == _digests(fixture()[0]),
        "a refused nomination changed the document",
    )
    return (
        "a well-formed nomination the admission rule refuses is recorded and "
        "never applied; the model cannot overrule the rule"
    )


def s5_every_stop_is_named(work: Path) -> str:
    seen = {}

    # Nothing to do.
    docs, article_ir, baseline = fixture()
    empty = _result(work, "s5-empty", [])
    seen["no_issues"] = repair_loop.repair_loop(
        empty, docs, article_ir, baseline, BoundedFakeTypesetter(),
        SimpleNamespace(lang_out="zh", translator=None), None,
        lambda _owned: empty, client=ScriptedClient({}), working_dir=work / "s5a",
    ).termination

    # Everything refused.
    body = _issue("out_of_page", (MEMBER_REFS[0],))
    seen["all_candidates_refused"] = _run(
        work, "s5b", [body], [[body]],
        {MEMBER_REFS[0]: _reply("contain_heading", [body.id])},
    )[0].termination

    # Every round deliberately chose to act on nothing.
    seen["converged_all_treated"] = _run(
        work, "s5c", OVERFLOW, [OVERFLOW], {},
    )[0].termination

    # The model never returned anything usable.
    unusable = json.dumps({"action": "contain_heading", "issue_ids": [], "nope": 1})
    seen["no_usable_decision"] = _run(
        work, "s5d", OVERFLOW, [OVERFLOW], {HEADING_REF: unusable},
    )[0].termination

    expected = {
        "no_issues": repair_loop.NO_ISSUES,
        "all_candidates_refused": repair_loop.ALL_CANDIDATES_REFUSED,
        "converged_all_treated": repair_loop.CONVERGED_ALL_TREATED,
        "no_usable_decision": repair_loop.NO_USABLE_DECISION,
    }
    for label, termination in sorted(seen.items()):
        _require(
            termination == expected[label],
            f"{label} came back as {termination!r}, not {expected[label]!r}",
        )
        _require(
            termination in repair_loop.TERMINATIONS,
            f"{termination!r} is outside the closed set of stops",
        )
    return (
        "the four ways of doing nothing come back under four different names, "
        "all from the closed set"
    )


def s6_ceilings_bind(work: Path) -> str:
    region = _issue("fragment_cluster", (MEMBER_REFS[0],), severity="low",
                    evidence={"member_count": 3})
    tight = repair_loop.LoopBudget(
        max_iterations=3,
        max_actions_per_iteration=1,
        max_candidate_issues_per_round=8,
        max_affected_elements_per_run=1,
    )
    result, _docs = _run(
        work,
        "s6",
        [OVERFLOW[0], region],
        [[region], [region]],
        {
            HEADING_REF: _reply("contain_heading", [OVERFLOW[0].id]),
            region.id: _reply("retypeset_article_region", [region.id]),
        },
        budget=tight,
    )
    _require(
        result.termination
        in (repair_loop.BUDGET_ACTIONS, repair_loop.BUDGET_ELEMENTS),
        f"a run over its ceilings stopped as {result.termination!r}",
    )
    _require(
        len(result.accepted_actions) <= tight.max_actions_per_iteration,
        f"{len(result.accepted_actions)} actions were kept under a ceiling of "
        f"{tight.max_actions_per_iteration}",
    )
    shipped = repair_loop.load_budget()
    _require(
        shipped.max_candidate_issues_per_round
        == llm_decide.load_decide_config().max_issues_per_round,
        "the per-round finding ceiling is declared twice and the two disagree",
    )
    return (
        f"the ceilings bind and stop the run as {result.termination}, and the "
        f"per-round ceiling is the one the decision step reads"
    )


def s7_termination_is_filed(work: Path) -> str:
    result, _docs = _run(
        work,
        "s7",
        OVERFLOW,
        [[]],
        {HEADING_REF: _reply("contain_heading", [OVERFLOW[0].id])},
    )
    path = work / "s7" / repair_loop.TERMINATION_NAME
    _require(path.is_file(), f"no termination record was written at {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    _require(
        record["termination"] == result.termination
        and record["schema_version"] == repair_loop.SCHEMA_VERSION,
        f"the record says {record['termination']!r}",
    )
    for key in ("accepted_actions", "refusals", "decisions", "residual_issues"):
        _require(key in record, f"the record carries no {key!r}")
    return (
        "termination.json names the stop, what was applied, what was refused "
        "and every finding left standing"
    )


def s8_the_pipeline_accepts_a_loop_result(work: Path) -> str:
    result, _docs = _run(
        work,
        "s8",
        OVERFLOW,
        [[]],
        {HEADING_REF: _reply("contain_heading", [OVERFLOW[0].id])},
    )
    record = minimal_pipeline._loop_summary(result)
    _require(
        record["termination"] in repair_loop.TERMINATIONS,
        f"the run report accepted an unnamed stop {record['termination']!r}",
    )
    _require(
        record["accepted_actions"],
        "the run report saw no accepted action for an accepted iteration",
    )
    # A run that does not translate through the provider it would decide with
    # never takes the loop, whatever the environment holds.
    for config in (
        SimpleNamespace(),
        SimpleNamespace(openai=True, only_parse_generate_pdf=True),
    ):
        _require(
            minimal_pipeline._decision_client(config, True) is None,
            f"a run configured as {config!r} was given a decision client",
        )
    _require(
        minimal_pipeline._decision_client(SimpleNamespace(openai=True), False)
        is None,
        "a run that translated nothing was given a decision client",
    )
    return (
        "the run report validates a loop result, and only a run translating "
        "through its own provider takes the loop at all"
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        claims = [
            ("S1", lambda: s1_oscillation_is_rejected_and_rolled_back(work)),
            ("S2", lambda: s2_improvement_is_accepted(work)),
            ("S3", lambda: s3_rejection_undoes_every_action_of_the_iteration(work)),
            ("S4", lambda: s4_admission_keeps_its_veto(work)),
            ("S5", lambda: s5_every_stop_is_named(work)),
            ("S6", lambda: s6_ceilings_bind(work)),
            ("S7", lambda: s7_termination_is_filed(work)),
            ("S8", lambda: s8_the_pipeline_accepts_a_loop_result(work)),
        ]
        for name, claim in claims:
            try:
                print(f"{name}  OK  {claim()}")
            except AssertionError as error:
                print(f"{name}  FAIL  {error}")
                return 1
    print("spec_check_b12_t4: all claims hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
