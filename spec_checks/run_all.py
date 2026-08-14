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

A sweep ends by applying the output retention policy in
``tools/prune_outputs.py``, which is what keeps ``examples/output/`` from
growing without bound, and then by writing ``run_all.done.json`` next to the other gate outputs,
carrying the exit code, the total wall clock and the timestamps. A caller that
launched the sweep in the background reads completion from that file rather
than from a wrapper's return, which a detached process cannot be relied on to
deliver.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_DIR = ROOT / "spec_checks"
PYTHON = sys.executable

# Completion marker for a caller polling a sweep it launched in the background.
DONE_PATH = ROOT / "examples" / "output" / "run_all.done.json"

# Every key the marker carries; a reader may rely on all of them being present.
DONE_FIELDS = ("exit_code", "elapsed_seconds", "started_at", "finished_at", "gates")

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
    "spec_check_b2_7.py",
    "spec_check_b3.py",
    "spec_check_b3_3.py",
    "spec_check_b4.py",
    "spec_check_b5.py",
    "spec_check_b6.py",
    "spec_check_b6_2.py",
    "spec_check_b7.py",
    "spec_check_b7_2.py",
    "spec_check_b7_3.py",
    "spec_check_b7_5.py",
    "spec_check_b8.py",
    "spec_check_b8_2.py",
    "spec_check_b8_3.py",
    "spec_check_b8_4.py",
    "spec_check_e0.py",
    "spec_check_e1.py",
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


def govern_cache() -> None:
    """Report the cache size and trim it back under its configured ceiling."""
    limit_bytes = artifacts.max_cache_bytes()
    limit_gb = limit_bytes / artifacts.BYTES_PER_GB
    size = artifacts.cache_size_bytes()
    print(
        f"gate cache size: {size / artifacts.BYTES_PER_GB:.2f} GB "
        f"of {limit_gb:g} GB allowed"
    )
    dropped, freed = artifacts.trim_cache(limit_bytes)
    if dropped:
        print(
            f"gate cache trimmed: {dropped} least recently used slot(s) dropped, "
            f"{freed / artifacts.BYTES_PER_GB:.2f} GB reclaimed"
        )


def prune_outputs() -> None:
    """Apply the output retention policy, which is what bounds this directory.

    At the end rather than at the start: a sweep reads what earlier sweeps left
    and writes what this one produces, and both are inside the batches the
    policy keeps whole. Its failure is reported and is never the sweep's, since
    a policy that could not reclaim disk has not invalidated a gate result.
    """
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "tools" / "prune_outputs.py"), "--apply"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in (proc.stdout or "").splitlines():
        print(f"  {line}")
    if proc.returncode != 0:
        print(f"  output retention failed: {(proc.stderr or '')[-500:]}")


def write_done(
    exit_code: int,
    elapsed: float,
    started_at: str,
    results: list[tuple[str, int, float, str]],
) -> Path:
    DONE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exit_code": exit_code,
        "elapsed_seconds": round(elapsed, 3),
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(),
        "gates": [
            {"gate": gate, "exit_code": code, "seconds": round(seconds, 3)}
            for gate, code, seconds, _ in results
        ],
    }
    with DONE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return DONE_PATH


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

    started_at = datetime.now().astimezone().isoformat()
    started = time.monotonic()

    harness.clear_timing()
    if args.clear_cache:
        print(f"gate cache cleared: {artifacts.clear_cache()} slot(s)")
    artifacts.clear_stats()
    govern_cache()

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
    print(
        f"  in-sweep trims: {cache['swept_slots']} slot(s) dropped before "
        f"publishing, {cache['swept_bytes'] / artifacts.BYTES_PER_GB:.2f} GB "
        f"reclaimed; cache now "
        f"{artifacts.cache_size_bytes() / artifacts.BYTES_PER_GB:.2f} GB"
    )
    print()
    report_timing(results)
    print()
    prune_outputs()

    exit_code = 1 if failed else 0
    marker = write_done(exit_code, time.monotonic() - started, started_at, results)
    print(f"  completion marker: {marker}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
