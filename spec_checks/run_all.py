"""Run every batch gate once, in batch order.

Run from the repository root:

    python spec_checks/run_all.py

Each gate is invoked with SPEC_NO_NESTED=1, which suppresses the re-runs of
earlier gates the later ones perform on their own. Those nested re-runs are
what make a full sweep quadratic in the number of batches; here every gate is
executed exactly once and the runner is the thing that guarantees coverage.
Exit code 0 when every gate passes, 1 otherwise.

Every gate reports where its wall clock went, split into pipeline builds and
per-assertion intervals; the runner prints the slowest assertions of each gate
and a corpus-wide build total, so a sweep that grows slower says which of the
two grew.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_DIR = ROOT / "spec_checks"
PYTHON = sys.executable

sys.path.insert(0, str(ROOT))

from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Batch order. A gate may depend on artefacts an earlier one produced, so the
# sequence is the delivery order rather than alphabetical.
GATES = (
    "spec_check_b0.py",
    "spec_check_b1.py",
    "spec_check_b2.py",
    "spec_check_b2_1.py",
    "spec_check_b2_2.py",
    "spec_check_b2_3.py",
    "spec_check_b2_5.py",
)


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_gate(gate: str, fast: bool = False) -> tuple[int, float, str]:
    """Run one gate, echoing its output as it arrives.

    Returns its exit code, its wall clock duration and the summary line it
    printed, which carries the passed/total count.
    """
    env = dict(os.environ)
    env["SPEC_NO_NESTED"] = "1"
    if fast:
        env["SPEC_FAST_TIER"] = "1"
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


def report_timing(results: list[tuple[str, int, float, str]]) -> None:
    """Print where the sweep spent its time, per gate and in total."""
    build_total = 0.0
    assertion_total = 0.0
    slowest: list[tuple[float, str, str]] = []
    print("run_all timing")
    for gate, _, wall, _ in results:
        timing = harness.load_timing(gate.removesuffix(".py"))
        if timing is None:
            print(f"  {gate}: no timing recorded")
            continue
        builds = sum(seconds for _, seconds in timing["phases"])
        assertions = sum(seconds for _, seconds in timing["assertions"])
        build_total += builds
        assertion_total += assertions
        slowest.extend((seconds, gate, name) for name, seconds in timing["assertions"])
        print(
            f"  {gate}: build={builds:.1f}s assertions={assertions:.1f}s "
            f"unattributed={wall - builds - assertions:.1f}s"
        )
        for name, seconds in sorted(timing["phases"], key=lambda item: -item[1])[:3]:
            print(f"      build {seconds:8.1f}s  {name}")
        for name, seconds in sorted(timing["assertions"], key=lambda item: -item[1])[
            : harness.TOP_SLOW
        ]:
            print(f"      assert {seconds:7.1f}s  {name}")
    print(f"  build total={build_total:.1f}s assertion total={assertion_total:.1f}s")
    print("  slowest assertions across the sweep:")
    for seconds, gate, name in sorted(slowest, reverse=True)[: harness.TOP_SLOW]:
        print(f"      {seconds:8.1f}s  {gate} :: {name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fast",
        action="store_true",
        help="run the static tier only; pipeline-tier assertions are skipped",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="drop every cached pipeline artefact before running",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    missing = [gate for gate in GATES if not (GATE_DIR / gate).exists()]
    if missing:
        print(f"missing gate scripts: {missing}")
        return 1

    harness.clear_timing()
    if args.clear_cache:
        print(f"gate cache cleared: {artifacts.clear_cache()} slot(s)")
    artifacts.clear_stats()

    print("gates to run, in order:")
    for gate in GATES:
        print(f"  {gate}")
    if args.fast:
        print("fast tier: pipeline-tier assertions are skipped")
    print(f"artifact cache: {artifacts.CACHE_ROOT}")
    print(f"workspace fingerprint: {artifacts.workspace_fingerprint()[:16]}")
    print()

    results: list[tuple[str, int, float, str]] = []
    for gate in GATES:
        print(f"=== {gate} start {stamp()} ===")
        code, seconds, summary = run_gate(gate, fast=args.fast)
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
    cache = artifacts.load_all_stats()
    requests = cache["hit"] + cache["built"]
    share = f"{cache['hit'] / requests:.0%}" if requests else "n/a"
    print(
        f"  artifact cache: {cache['hit']} hit / {cache['built']} built "
        f"({share} served from cache), {cache['build_seconds']:.1f}s spent building"
    )
    print()
    report_timing(results)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
