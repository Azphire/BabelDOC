"""Gate: the tail-fill sidecar is internally consistent and lists, not counts.

From B14 on, a claim about rendered column tails cites tail_fill.report.json.
A summary that drifted from its own rows -- a share computed over different
rows than the listed ones, a dangling tail counted but not itemized -- would
turn the sidecar into the kind of evidence that cannot be checked. Every
claim here is recomputable from the report alone.

Claims, per work directory given:

S1  The summary's counts equal what the rows say (boundaries, measured,
    chained, unchained, by_boundary).
S2  The fill distribution and full-line share recompute exactly from the
    rows' fill ratios under the declared full_line_fill_min.
S3  Every rendered last line of at most short_tail_max_chars ink characters
    appears in the short-tail list, itemized with its text -- and nothing
    else does. A list, never a bare count.
S4  Every rebalance attempt is itemized with its outcome, and the applied
    count equals the attempts that say "applied".

Usage:
    python tools/spec_check_b14_t2.py <work_dir> [<work_dir>...]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_NAME = "tail_fill.report.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load(work: Path) -> dict:
    return json.loads((work / REPORT_NAME).read_text(encoding="utf-8"))


def s1_counts_equal_rows(work: Path) -> str:
    report = _load(work)
    rows = report["boundaries"]
    summary = report["summary"]
    _require(summary["boundaries"] == len(rows), "boundary count drifted")
    _require(
        summary["measured"]
        == sum(1 for row in rows if row["last_line"] is not None),
        "measured count drifted",
    )
    _require(
        summary["chained"] == sum(1 for row in rows if row["chained"]),
        "chained count drifted",
    )
    _require(
        summary["unchained"] == sum(1 for row in rows if not row["chained"]),
        "unchained count drifted",
    )
    for kind, count in summary["by_boundary"].items():
        _require(
            count == sum(1 for row in rows if row["boundary"] == kind),
            f"by_boundary[{kind}] drifted",
        )
    return f"{len(rows)} row(s) agree with their summary"


def s2_distribution_recomputes(work: Path) -> str:
    report = _load(work)
    rows = report["boundaries"]
    summary = report["summary"]
    fills = [
        row["last_line"]["fill_ratio"]
        for row in rows
        if row["last_line"] is not None
        and row["last_line"]["fill_ratio"] is not None
    ]
    if not fills:
        _require(
            summary["fill_ratio"]["median"] is None,
            "a median with no measured fills",
        )
        return "no measured fills, and the summary says so"
    _require(
        abs(summary["fill_ratio"]["min"] - min(fills)) < 1e-3,
        "min drifted",
    )
    _require(
        abs(summary["fill_ratio"]["median"] - statistics.median(fills)) < 1e-3,
        "median drifted",
    )
    threshold = summary["full_line_fill_min"]
    share = sum(1 for value in fills if value >= threshold) / len(fills)
    _require(
        abs(summary["full_line_share"] - share) < 1e-3,
        f"full-line share drifted: {summary['full_line_share']} vs {share}",
    )
    return f"distribution recomputes over {len(fills)} fill(s)"


def s3_short_tails_are_itemized(work: Path) -> str:
    report = _load(work)
    rows = report["boundaries"]
    summary = report["summary"]
    ceiling = summary["short_tail_max_chars"]
    expected = {
        (row["prev_ref"], row["next_ref"])
        for row in rows
        if row["last_line"] is not None
        and 0 < row["last_line"]["chars"] <= ceiling
    }
    listed = {
        (tail["prev_ref"], tail["next_ref"]) for tail in summary["short_tails"]
    }
    _require(
        listed == expected,
        f"short-tail list disagrees with the rows: listed {sorted(listed)}, "
        f"rows say {sorted(expected)}",
    )
    for tail in summary["short_tails"]:
        _require(
            isinstance(tail.get("text"), str) and tail["text"],
            f"{tail['prev_ref']}: a listed tail without its text is a count",
        )
    return f"{len(listed)} short tail(s), each itemized with its text"


def s4_rebalance_is_itemized(work: Path) -> str:
    report = _load(work)
    rebalance = report["rebalance"]
    applied = sum(
        1
        for attempt in rebalance["attempts"]
        if attempt["outcome"] == "applied"
    )
    _require(
        rebalance["applied"] == applied,
        f"applied count {rebalance['applied']} vs {applied} itemized",
    )
    for attempt in rebalance["attempts"]:
        _require(
            bool(attempt.get("outcome")) and bool(attempt.get("prev_ref")),
            "a rebalance attempt without outcome or reference",
        )
    return (
        f"{applied} applied of {len(rebalance['attempts'])} attempt(s), "
        f"each itemized"
    )


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: spec_check_b14_t2.py <work_dir> [<work_dir>...]")
        return 2
    failures = 0
    for raw in argv:
        work = Path(raw)
        for name, claim in (
            ("S1", s1_counts_equal_rows),
            ("S2", s2_distribution_recomputes),
            ("S3", s3_short_tails_are_itemized),
            ("S4", s4_rebalance_is_itemized),
        ):
            try:
                print(f"{name}  OK  [{work.name}] {claim(work)}")
            except AssertionError as error:
                print(f"{name}  FAIL  [{work.name}] {error}")
                failures += 1
    if failures:
        return 1
    print("spec_check_b14_t2: all claims hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
