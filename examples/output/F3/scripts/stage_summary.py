"""Aggregate the stage timing sidecar of one arm into a table.

The unattributed remainder is reported rather than distributed: a stage's clock
runs between the progress events that open and close it, and everything a run
does outside those windows -- checkpoint serialisation, the extension passes
that hang off a stage's edge, the model load -- lands in the remainder. That
number is a finding, not an error term.

Usage:
    python stage_summary.py [--arm warm]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "examples" / "output" / "F3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="warm")
    args = parser.parse_args(argv)

    arm = OUT_DIR / args.arm
    rows = json.loads((arm / "runs.json").read_text(encoding="utf-8"))

    totals: dict[str, float] = {}
    runs: dict[str, int] = {}
    order: list[str] = []
    wall = attributed = 0.0
    per_sample = []
    for row in rows:
        wall += row["seconds"]
        attributed += row["stage_seconds_total"]
        per_sample.append(
            (
                Path(row["sample"]).stem,
                row["seconds"],
                row["stage_seconds_total"],
                row["output_pages"],
            )
        )
        for entry in row["stages"]:
            if entry["stage"] not in order:
                order.append(entry["stage"])
            totals[entry["stage"]] = totals.get(entry["stage"], 0.0) + entry["seconds"]
            runs[entry["stage"]] = runs.get(entry["stage"], 0) + entry["runs"]

    print(f"arm: {args.arm}")
    print(f"{'sample':22} {'wall':>8} {'stages':>8} {'rest':>8} {'pages':>6}")
    for sample, seconds, stages, pages in per_sample:
        print(
            f"{sample:22} {seconds:8.1f} {stages:8.1f} {seconds - stages:8.1f} "
            f"{pages:6}"
        )
    print(
        f"{'TOTAL':22} {wall:8.1f} {attributed:8.1f} {wall - attributed:8.1f}"
    )
    print()
    print(f"{'stage':44} {'seconds':>9} {'share':>7} {'runs':>5}")
    for stage in sorted(order, key=lambda name: -totals[name]):
        print(
            f"{stage:44} {totals[stage]:9.1f} {100 * totals[stage] / wall:6.1f}% "
            f"{runs[stage]:5}"
        )
    print(
        f"{'unattributed remainder':44} {wall - attributed:9.1f} "
        f"{100 * (wall - attributed) / wall:6.1f}%"
    )

    destination = OUT_DIR / f"stage_summary.{args.arm}.json"
    with destination.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "arm": args.arm,
                "wall_seconds": round(wall, 1),
                "attributed_seconds": round(attributed, 1),
                "unattributed_seconds": round(wall - attributed, 1),
                "stages": [
                    {
                        "stage": stage,
                        "seconds": round(totals[stage], 1),
                        "runs": runs[stage],
                    }
                    for stage in sorted(order, key=lambda name: -totals[name])
                ],
                "samples": [
                    {
                        "sample": sample,
                        "seconds": seconds,
                        "stage_seconds": stages,
                        "pages": pages,
                    }
                    for sample, seconds, stages, pages in per_sample
                ],
            },
            f,
            indent=2,
        )
        f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
