"""Run every batch gate once, in batch order.

Run from the repository root:

    python spec_checks/run_all.py

Each gate is invoked with SPEC_NO_NESTED=1, which suppresses the re-runs of
earlier gates the later ones perform on their own. Those nested re-runs are
what make a full sweep quadratic in the number of batches; here every gate is
executed exactly once and the runner is the thing that guarantees coverage.
Exit code 0 when every gate passes, 1 otherwise.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_DIR = ROOT / "spec_checks"
PYTHON = sys.executable

# Batch order. A gate may depend on artefacts an earlier one produced, so the
# sequence is the delivery order rather than alphabetical.
GATES = (
    "spec_check_b0.py",
    "spec_check_b1.py",
    "spec_check_b2.py",
    "spec_check_b2_1.py",
    "spec_check_b2_2.py",
    "spec_check_b2_3.py",
)


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_gate(gate: str) -> tuple[int, float, str]:
    """Run one gate, echoing its output as it arrives.

    Returns its exit code, its wall clock duration and the summary line it
    printed, which carries the passed/total count.
    """
    env = dict(os.environ)
    env["SPEC_NO_NESTED"] = "1"
    # Unbuffered, so the echoed output tracks the gate rather than lagging a
    # block behind it on a run that takes minutes.
    env["PYTHONUNBUFFERED"] = "1"

    started = time.monotonic()
    summary = ""
    prefix = gate.removesuffix(".py")
    process = subprocess.Popen(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(GATE_DIR / gate)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    for line in process.stdout or ():
        line = line.rstrip()
        if line.startswith(prefix):
            summary = line
        print(f"    {line}")
    code = process.wait()
    return code, time.monotonic() - started, summary


def main() -> int:
    missing = [gate for gate in GATES if not (GATE_DIR / gate).exists()]
    if missing:
        print(f"missing gate scripts: {missing}")
        return 1

    print("gates to run, in order:")
    for gate in GATES:
        print(f"  {gate}")
    print()

    results: list[tuple[str, int, float, str]] = []
    for gate in GATES:
        print(f"=== {gate} start {stamp()} ===")
        code, seconds, summary = run_gate(gate)
        print(f"=== {gate} end {stamp()} exit={code} elapsed={seconds:.1f}s ===")
        print()
        results.append((gate, code, seconds, summary))

    failed = [gate for gate, code, _, _ in results if code != 0]
    print("run_all summary")
    for gate, code, seconds, summary in results:
        state = "PASS" if code == 0 else "FAIL"
        print(f"  [{state}] {gate} {seconds:7.1f}s  {summary}")
    total = sum(seconds for _, _, seconds, _ in results)
    print(f"  {len(results) - len(failed)}/{len(results)} gates passed in {total:.1f}s")
    for gate in failed:
        print(f"  FAILED: {gate}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
