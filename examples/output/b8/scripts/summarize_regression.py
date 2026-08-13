"""B8.3 regression face: what the loop did on every sample, side by side.

The main evidence sample gets its own analysis; this is the other question,
which is whether the same configuration is safe on documents nobody tuned it
against. One row per sample: what was found, what the decision named, what the
applicability rule refused and why, how the loop stopped, and whether the
document came through conserved.

The escalation detector is called out separately. It carries findings the chain
translator raised about itself, and until a real run raises one it has never
been seen outside a fixture, so the first live instance is worth recording as
its own item rather than as a number in a column.

Usage:
    python summarize_regression.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine.detectors import escalation  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402

SMOKE_DIR = ROOT / "examples" / "output" / "b8" / "smoke"
LEDGER = SMOKE_DIR / "runs.json"
SUMMARY = SMOKE_DIR / "regression.json"


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def rejection_histogram(repair: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for iteration in repair.get("iterations", ()):
        rows = [
            *iteration.get("applicability", ()),
            *(row for row in iteration.get("executed", ()) if not row.get("changed")),
        ]
        for row in rows:
            # A refusal states its violations after the reason name; the name is
            # what is counted, so a histogram has as many columns as there are
            # declared reasons rather than one per failure text.
            reason = str(row.get("reason", "")).split(":", 1)[0]
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def main() -> int:
    rows = []
    escalations = []
    for entry in load_json(LEDGER):
        working = ROOT / entry["working_dir"]
        repair = load_json(working / controller.REPORT_NAME)
        issues = load_json(working / detectors.REPORT_NAME)
        conservation = repair["conservation"]
        first = repair["iterations"][0] if repair["iterations"] else {}
        decision = first.get("decision") or {}
        rows.append(
            {
                "sample": entry["sample"],
                "seconds": entry["seconds"],
                "requests": entry["requests"],
                "api_calls": entry["api_calls"],
                "pages": conservation["pages_before"],
                "paragraphs": conservation["paragraphs_before"],
                "detected_first": first.get("detected", {}).get("total", 0),
                "detected_by_kind": first.get("detected", {}).get("by_kind", {}),
                "decision_action": decision.get("action"),
                "decision_named": len(decision.get("issue_ids", ()) or ()),
                "iterations_run": repair["iterations_run"],
                "stopped_because": repair["stopped_because"],
                "applications": repair["applications"],
                "repaired_refs": conservation["touched_refs"],
                "rejections": rejection_histogram(repair),
                "conservation": conservation["verdict"],
                "final_total": repair["final"]["total"],
                "final_by_kind": repair["final"]["by_kind"],
                "notes": issues.get("notes", []),
            }
        )
        for issue in issues.get("issues", ()):
            if issue["detector"] == escalation.NAME:
                escalations.append({"sample": entry["sample"], "issue": issue})

    summary = {
        "samples": rows,
        "totals": {
            "samples": len(rows),
            "documents_conserved": sum(
                1 for row in rows if row["conservation"] == controller.CONSERVED
            ),
            "paragraphs_repaired": sum(len(row["repaired_refs"]) for row in rows),
            "api_calls": sum(row["api_calls"] for row in rows),
        },
        "escalation_findings": escalations,
    }
    with SUMMARY.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"wrote {SUMMARY.relative_to(ROOT)}")
    for row in rows:
        print(
            f"  {row['sample']:<24} detected={row['detected_first']:<3} "
            f"named={row['decision_named']:<3} repaired={len(row['repaired_refs']):<3} "
            f"iters={row['iterations_run']} {row['conservation']:<10} "
            f"{row['stopped_because']}"
        )
    print(f"  escalation findings: {len(escalations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
