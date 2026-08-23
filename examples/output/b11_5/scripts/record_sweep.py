"""Record one fast sweep as this batch's derived evidence.

The gate asserts that the fast set ran green, and it must not launch a sweep to
find out: a gate that starts a sweep nests one inside another, and an
interrupted nested sweep leaves an orphan holding the sweep lock. So the sweep
is run by hand and its own completion marker is copied here, under this batch's
directory, where the retention policy protects it as declared gate evidence.

Reads examples/output/run_all.done.json, writes
examples/output/b11_5/run_all.fast.json.

Usage:
    python record_sweep.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from spec_checks import run_all  # noqa: E402

MARKER = ROOT / "examples" / "output" / "run_all.done.json"
OUT = ROOT / "examples" / "output" / "b11_5" / "run_all.fast.json"


def main() -> int:
    if not MARKER.is_file():
        raise SystemExit(f"no completion marker at {MARKER}")
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    if marker.get("set") != "fast":
        raise SystemExit(f"the marker is for the {marker.get('set')!r} set")

    expected = run_all.selected_gates("fast")
    ran = [row["gate"] for row in marker["gates"]]
    record = {
        "set": marker["set"],
        "exit_code": marker["exit_code"],
        "started_at": marker["started_at"],
        "finished_at": marker["finished_at"],
        "elapsed_seconds": marker["elapsed_seconds"],
        "gates_run": len(marker["gates"]),
        "gates_declared": len(expected),
        "missing": sorted(set(expected) - set(ran)),
        "failing": sorted(
            row["gate"] for row in marker["gates"] if row["exit_code"] != 0
        ),
        "gates": marker["gates"],
    }
    OUT.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"{record['gates_run']}/{record['gates_declared']} gates, "
        f"failing={record['failing']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
