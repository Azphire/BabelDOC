"""Gate: the evidence exists exactly when there is a repair to show.

A before/after pair is a strong claim and an easy one to fake by accident. Two
renders of the same unchanged page look like evidence of a repair while being
evidence of none; and a repair that happened but rendered nothing leaves a
report asserting an improvement nobody can check. Both failures are silent, and
both are one missing condition away.

So the claim here is a biconditional, checked in both directions: a page has a
picture pair if and only if an accepted action wrote to it. S1 is the forward
half, S2 the reverse -- a run that kept nothing must render nothing at all.

Six claims:

S1  Every page an accepted action wrote to has both halves of its pair.
S2  A run that accepted nothing produces no pair, no evidence directory
    content, and no pre-repair PDF.
S3  A page no accepted action touched gets no pair, even when the run did
    accept repairs elsewhere.
S4  Every case the report prints names a page that the before-sidecar has a
    finding on, so a case cannot be reconciled to nothing.
S5  The report writes a row for every kind in the closed vocabulary, including
    the kinds with no repairs, and states zero rather than omitting them.
S6  A batch with no accepted repair still produces a report, and that report
    says so in words rather than by being empty.

Run offline; the runs are synthesized on disk and nothing is rendered from a
real PDF.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import repair_evidence  # noqa: E402
from babeldoc.magazine.detectors import DETECTOR_NAMES  # noqa: E402
from tools import mapek_report  # noqa: E402

TOUCHED_PAGE = 7
UNTOUCHED_PAGE = 9


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _issue(issue_id: str, kind: str, page: int) -> dict:
    return {
        "id": issue_id,
        "kind": kind,
        "page": page,
        "severity": "high",
        "paragraph_refs": [f"p{page}#0"],
        "evidence": {"overflow_ratio": 0.31, "excerpt": "a heading over the edge"},
    }


def _make_run(
    directory: Path,
    *,
    accepted: bool,
    pages=(TOUCHED_PAGE,),
    render=True,
) -> Path:
    """One sample's run directory, as the pipeline would have left it."""
    directory.mkdir(parents=True, exist_ok=True)
    before = _issue("finding-1", "out_of_page", TOUCHED_PAGE)
    stale = _issue("finding-2", "fragment_cluster", UNTOUCHED_PAGE)
    (directory / mapek_report.BEFORE_NAME).write_text(
        json.dumps(
            {
                "issues": [before, stale],
                "counts": {"by_kind": {"out_of_page": 1, "fragment_cluster": 1}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / mapek_report.AFTER_NAME).write_text(
        json.dumps(
            {
                "issues": [] if accepted else [before, stale],
                "counts": {
                    "by_kind": (
                        {} if accepted else {"out_of_page": 1, "fragment_cluster": 1}
                    )
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    actions = (
        [
            {
                "iteration": 1,
                "kind": "out_of_page",
                "action": "contain_heading",
                "issue_ids": ["finding-1"],
                "parameters": {"heading_min_scale": 0.5},
                "reason": "the heading reaches past the page edge",
                "written_refs": [f"p{TOUCHED_PAGE}#0"],
                "pages": list(pages),
            }
        ]
        if accepted
        else []
    )
    (directory / mapek_report.TERMINATION_NAME).write_text(
        json.dumps(
            {
                "schema_version": "mapek-loop.v1",
                "termination": "no_issues" if accepted else "all_candidates_refused",
                "iterations": 1,
                "rolled_back": False,
                "accepted_actions": actions,
                "refusals": (
                    []
                    if accepted
                    else [
                        {
                            "iteration": 1,
                            "kind": "out_of_page",
                            "action": "contain_heading",
                            "issue_id": "finding-1",
                            "reason": "heading_role_not_allowed",
                        }
                    ]
                ),
                "decisions": [
                    {
                        "kind": "out_of_page",
                        "outcome": "decided",
                        "action": "contain_heading",
                        "issue_ids": ["finding-1"],
                    }
                ],
                "residual_issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if accepted and render:
        evidence = directory / repair_evidence.EVIDENCE_DIR
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / repair_evidence.BEFORE_PDF_NAME).write_bytes(b"%PDF-1.7\n")
        for page in pages:
            for suffix in (
                repair_evidence.BEFORE_SUFFIX,
                repair_evidence.AFTER_SUFFIX,
            ):
                (evidence / f"p{page}.{suffix}.png").write_bytes(b"\x89PNG\r\n")
    return directory


def s1_accepted_pages_have_pairs(work: Path) -> str:
    run = mapek_report.load(_make_run(work / "s1", accepted=True))
    pairs = mapek_report._evidence(run)
    pages = {
        page for action in run.accepted_actions for page in action["pages"]
    }
    _require(pages, "the fixture accepted an action that named no page")
    _require(
        set(pairs) == pages,
        f"pages {sorted(pages)} were written to but only {sorted(pairs)} have "
        f"a picture pair",
    )
    for page, (before, after) in pairs.items():
        _require(
            before.is_file() and after.is_file(),
            f"page {page} is missing half of its pair",
        )
    return (
        f"every page an accepted action wrote to has both halves of its pair "
        f"({sorted(pages)})"
    )


def s2_a_run_that_kept_nothing_renders_nothing(work: Path) -> str:
    directory = _make_run(work / "s2", accepted=False)
    run = mapek_report.load(directory)
    _require(not run.accepted_actions, "the fixture kept an action")
    _require(
        not mapek_report._evidence(run),
        "a run that kept nothing produced a picture pair",
    )
    evidence = directory / repair_evidence.EVIDENCE_DIR
    _require(
        not evidence.exists() or not list(evidence.iterdir()),
        f"a run that kept nothing left files in {evidence}",
    )
    _require(
        not (evidence / repair_evidence.BEFORE_PDF_NAME).exists(),
        "a run that kept nothing wrote a pre-repair PDF",
    )
    return "a run that kept nothing renders no pair and no pre-repair PDF"


def s3_untouched_pages_get_no_pair(work: Path) -> str:
    run = mapek_report.load(_make_run(work / "s3", accepted=True))
    pairs = mapek_report._evidence(run)
    _require(
        UNTOUCHED_PAGE not in pairs,
        f"page {UNTOUCHED_PAGE} was never written to and still has a pair",
    )
    _require(
        any(
            issue["page"] == UNTOUCHED_PAGE for issue in run.issues("before")
        ),
        "the fixture has no finding on the untouched page, so this proves "
        "nothing",
    )
    return (
        f"page {UNTOUCHED_PAGE} carries a finding, was not repaired, and has "
        f"no pair"
    )


def s4_every_case_reconciles_to_a_finding(work: Path) -> str:
    run = mapek_report.load(_make_run(work / "s4", accepted=True))
    before_pages = {issue["page"] for issue in run.issues("before")}
    before_ids = {issue["id"] for issue in run.issues("before")}
    for action in run.accepted_actions:
        for issue_id in action["issue_ids"]:
            _require(
                issue_id in before_ids,
                f"the case names finding {issue_id!r}, which the before "
                f"sidecar does not carry",
            )
        for page in action["pages"]:
            _require(
                page in before_pages,
                f"the case names page {page}, which carries no finding",
            )
    return (
        "every accepted case names a finding and a page the before-sidecar "
        "actually carries"
    )


def s5_report_states_zero_rather_than_omitting(work: Path) -> str:
    run = mapek_report.load(_make_run(work / "s5", accepted=True))
    out = work / "s5-report.md"
    out.write_text(mapek_report.render([run], out), encoding="utf-8")
    text = out.read_text(encoding="utf-8")
    for kind in DETECTOR_NAMES:
        _require(
            f"`{kind}`" in text,
            f"the report omits {kind!r} instead of writing it as zero",
        )
    _require(
        "| `abnormal_blank` | 0 | 0 | 0 | 0 |" in text,
        "a kind with nothing to report is not written as zero",
    )
    _require(
        "contain_heading" in text and "p7.before.png" in text,
        "the accepted case does not carry its action and its pictures",
    )
    return (
        f"all {len(DETECTOR_NAMES)} kinds appear in the report, and the ones "
        f"with nothing to report say zero"
    )


def s6_an_empty_batch_still_reports(work: Path) -> str:
    run = mapek_report.load(_make_run(work / "s6", accepted=False))
    out = work / "s6-report.md"
    out.write_text(mapek_report.render([run], out), encoding="utf-8")
    text = out.read_text(encoding="utf-8")
    _require(
        "No repair was accepted" in text,
        "a batch with no accepted repair does not say so",
    )
    _require(
        "all_candidates_refused" in text,
        "the report does not say why the run stopped",
    )
    _require(
        ".png" not in text,
        "a batch with no accepted repair still points at pictures",
    )
    return (
        "a batch with no accepted repair produces a report that says so and "
        "points at no pictures"
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        claims = [
            ("S1", lambda: s1_accepted_pages_have_pairs(work)),
            ("S2", lambda: s2_a_run_that_kept_nothing_renders_nothing(work)),
            ("S3", lambda: s3_untouched_pages_get_no_pair(work)),
            ("S4", lambda: s4_every_case_reconciles_to_a_finding(work)),
            ("S5", lambda: s5_report_states_zero_rather_than_omitting(work)),
            ("S6", lambda: s6_an_empty_batch_still_reports(work)),
        ]
        for name, claim in claims:
            try:
                print(f"{name}  OK  {claim()}")
            except AssertionError as error:
                print(f"{name}  FAIL  {error}")
                return 1
    print("spec_check_b12_t5: all claims hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
