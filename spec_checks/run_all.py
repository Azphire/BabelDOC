"""Run every batch gate once, in batch order.

Run from the repository root:

    python spec_checks/run_all.py

Each gate is invoked with SPEC_NO_NESTED=1, which suppresses the re-runs of
earlier gates the later ones perform on their own. Those nested re-runs are
what make a full sweep quadratic in the number of batches; here every gate is
executed exactly once and the runner is the thing that guarantees coverage.
Exit code 0 when every gate passes, 1 otherwise.

Two independent axes narrow a run, and they are not the same thing.

``--set`` chooses **which gates run**. Every gate declares a module level
``GATE_SET``: ``sweep`` where it asks the artifact builder for documents, so a
cold slot re-runs the pipeline over the corpus, and ``fast`` where it answers
from stubs it builds itself and from evidence a batch froze. ``--set all`` is
the default and is what a release runs.

``--fast`` chooses **which assertions run inside a gate**: it sets
SPEC_FAST_TIER, and the gates skip their pipeline-tier assertions. It narrows
every gate rather than the list of them.

Both can be combined. ``--set fast`` alone still runs every assertion of every
gate it selects, which is the combination a per-batch discipline wants.

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
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_DIR = ROOT / "spec_checks"
PYTHON = sys.executable

# Everything this runner and the gates below it print is UTF-8, declared on both
# sides of every hop rather than left to the platform. A console picks an
# encoding from the terminal; a redirect into a file picks one from the locale,
# which on a Windows workstation is a legacy codepage that cannot carry the
# characters a corpus of magazines puts into a filename or a note. The failure
# it produces is not a mangled line but a raised UnicodeEncodeError, so a sweep
# that ran for hours ends with no summary at all.
IO_ENCODING = "utf-8"

# What an unencodable character becomes. A replacement mark in a gate's echoed
# output is a legible sweep; a raise is not one.
IO_ERRORS = "replace"

for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        with contextlib.suppress(Exception):
            reconfigure(encoding=IO_ENCODING, errors=IO_ERRORS)

# Completion marker for a caller polling a sweep it launched in the background.
DONE_PATH = ROOT / "examples" / "output" / "run_all.done.json"

# Every key the marker carries; a reader may rely on all of them being present.
DONE_FIELDS = ("exit_code", "elapsed_seconds", "started_at", "finished_at", "gates")

sys.path.insert(0, str(ROOT))

from spec_checks import artifacts  # noqa: E402
from spec_checks import frozen  # noqa: E402
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
    "spec_check_b9_1.py",
    "spec_check_b9_2.py",
    "spec_check_b11_4.py",
    "spec_check_b11_5.py",
    "spec_check_e0.py",
    "spec_check_e1.py",
    "spec_check_e2.py",
    "spec_check_b9_2r.py",
    "spec_check_b9_3.py",
    "spec_check_b9_4.py",
    "spec_check_b9_5.py",
    "spec_check_b9_6.py",
    "spec_check_b9_7.py",
    "spec_check_b10_1.py",
    "spec_check_b10_2.py",
    "spec_check_b10_3.py",
    "spec_check_b10_4.py",
    "spec_check_b10_5.py",
    "spec_check_f3.py",
    "spec_check_b11_1.py",
    "spec_check_b11_2.py",
    "spec_check_b11_3.py",
    "spec_check_b11_6.py",
    "spec_check_b11_7.py",
    "spec_check_magazine_runtime_profile.py",
    "spec_check_article_flow_ir.py",
    "spec_check_run_trace.py",
    "spec_check_fixed_asset_guard.py",
    "spec_check_chain_single_request.py",
    "spec_check_chain_slot_backfill.py",
    "spec_check_article_cross_column.py",
    "spec_check_article_cross_page.py",
    "spec_check_repair_transaction.py",
    "spec_check_reflow_compliance.py",
    "spec_check_drop_cap_intent.py",
    "spec_check_drop_cap_english.py",
    "spec_check_drop_cap_chinese.py",
    "spec_check_drop_cap_repair_guard.py",
    "spec_check_pdf_compliance.py",
    "spec_check_gate_registration.py",
)


# The two sets a gate belongs to, and how a gate says which. Every gate declares
# a module level ``GATE_SET``; it is read out of the source rather than imported,
# because importing a gate runs its module body.
#
# The split is not a stopwatch reading. A ``sweep`` gate asks the artifact
# builder for documents, so a cold slot means re-running the whole pipeline over
# the corpus to answer one assertion -- b10.1 measured 147 minutes across 27
# gates on a warm cache, and 18 of them are of this kind. A ``fast`` gate answers
# from stubs it builds itself and from evidence a batch froze, which is seconds
# to a couple of minutes each. Both sets are always correct to run; what differs
# is what they cost, and therefore how often a discipline can afford them.
SETS = ("fast", "sweep")
SET_ALL = "all"

_GATE_SET = re.compile(r'^GATE_SET\s*=\s*"([a-z]+)"', re.M)


def gate_set(gate: str) -> str:
    """The set one gate declares. Raises where it declares none.

    A gate with no declaration is not defaulted into either set: which one it
    belongs to is a property of what it drives, the author of the gate is who
    knows that, and a gate silently defaulted into ``fast`` would be a pipeline
    rebuild nobody scheduled.
    """
    source = (GATE_DIR / gate).read_text(encoding="utf-8")
    match = _GATE_SET.search(source)
    if match is None:
        raise ValueError(f"{gate} declares no GATE_SET")
    if match.group(1) not in SETS:
        raise ValueError(f"{gate} declares GATE_SET {match.group(1)!r}")
    return match.group(1)


def selected_gates(name: str) -> list[str]:
    """The gates one selection runs, in the runner's order."""
    if name == SET_ALL:
        return list(GATES)
    return [gate for gate in GATES if gate_set(gate) == name]


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_gate(gate: str, fast: bool = False) -> tuple[int, float, str]:
    """Run one gate, echoing its output as it arrives.

    Returns its exit code, its wall clock duration and the summary line it
    printed, which carries the passed/total count.

    The frozen evidence is digested before and after. A gate that rewrote a
    tracked file under ``spec_checks/frozen.FROZEN_PREFIXES`` fails here whether
    or not it noticed doing so, and the paths are named: batch b9.2 lost a
    frozen fold matrix to an assertion that recomputed it in place, and no
    assertion in that gate was looking for it.
    """
    env = dict(os.environ)
    env["SPEC_NO_NESTED"] = "1"
    if fast:
        env["SPEC_FAST_TIER"] = "1"
    # Unbuffered, so the echoed output tracks the gate rather than lagging a
    # block behind it on a run that takes minutes.
    env["PYTHONUNBUFFERED"] = "1"
    # The gate writes into a pipe, which has no terminal to take an encoding
    # from, so it is told the one this end decodes with instead of falling back
    # to the platform's.
    env["PYTHONIOENCODING"] = f"{IO_ENCODING}:{IO_ERRORS}"

    before = frozen.snapshot()
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
        encoding=IO_ENCODING,
        errors=IO_ERRORS,
        bufsize=1,
    )
    for line in process.stdout or ():
        line = line.rstrip()
        if line.startswith(prefix):
            summary = line
        print(f"    {line}")
    code = process.wait()
    written = frozen.changed(before)
    if written:
        print(f"    FROZEN EVIDENCE WRITTEN by {gate}: {written}")
        print("    a gate may read and compare frozen evidence; it may not write it")
        code = code or 1
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


def prune_outputs(requested: bool) -> None:
    """Apply the output retention policy, when the caller has asked for it.

    At the end rather than at the start: a sweep reads what earlier sweeps left
    and writes what this one produces, and both are inside the batches the
    policy keeps whole. Its failure is reported and is never the sweep's, since
    a policy that could not reclaim disk has not invalidated a gate result.

    Asked for rather than automatic, because running the gates used to be the
    only way the policy was ever applied and that made a gate sweep a destroying
    action: whoever ran the gates to read a batch's evidence was, in the same
    command, taking the evidence of the batch two behind it. Reading a record
    must not be what erases another record, so reclaiming disk is now its own
    request -- this flag, or tools/prune_outputs.py --apply directly.
    """
    if not requested:
        print(
            "  output retention: not applied (pass --prune-outputs, or run "
            "tools/prune_outputs.py --apply, to reclaim disk)"
        )
        return
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "tools" / "prune_outputs.py"), "--apply"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding=IO_ENCODING,
        errors=IO_ERRORS,
        env={**os.environ, "PYTHONIOENCODING": f"{IO_ENCODING}:{IO_ERRORS}"},
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
    selection: str = SET_ALL,
) -> Path:
    DONE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exit_code": exit_code,
        "set": selection,
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
        "--set",
        dest="gate_set",
        choices=(SET_ALL, *SETS),
        default=SET_ALL,
        help=(
            "which set of gates to run: fast (drives no pipeline build), "
            "sweep (asks the artifact builder for documents), or all"
        ),
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="drop every cached pipeline artefact before running",
    )
    parser.add_argument(
        "--prune-outputs",
        action="store_true",
        help=(
            "apply the output retention policy once the sweep has finished; "
            "without it nothing under examples/output/ is removed"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    missing = [gate for gate in GATES if not (GATE_DIR / gate).exists()]
    if missing:
        print(f"missing gate scripts: {missing}")
        return 1

    # Read every declaration before anything runs, so a gate that forgot one is
    # a refusal at the start rather than a gap discovered by a green sweep that
    # quietly left it out.
    try:
        gates = selected_gates(args.gate_set)
    except ValueError as exc:
        print(f"run_all refused to start: {exc}")
        return 1
    if not gates:
        print(f"run_all refused to start: no gate is in the {args.gate_set!r} set")
        return 1

    # Before anything is cleared, timed or built: two sweeps sharing one cache
    # corrupt each other's slots, and the completion marker this one is about to
    # overwrite belongs to the sweep already running.
    try:
        artifacts.acquire_sweep_lock()
    except artifacts.SweepInProgress as exc:
        print(f"run_all refused to start: {exc}")
        return 2
    try:
        with contextlib.ExitStack() as closing:
            closing.callback(artifacts.release_sweep_lock)
            return _sweep(args, gates)
    except artifacts.SweepInProgress as exc:  # re-taken after --clear-cache
        print(f"run_all refused to continue: {exc}")
        return 2


def _sweep(args: argparse.Namespace, gates: list[str]) -> int:
    """One sweep over the selected gates, with the cache already claimed.

    Separate from ``main`` only so the lock is released on every exit path
    including a raise; ``main`` is still where the sweep is ordered and where
    the selection is resolved.
    """
    started_at = datetime.now().astimezone().isoformat()
    started = time.monotonic()

    harness.clear_timing()
    if args.clear_cache:
        print(f"gate cache cleared: {artifacts.clear_cache()} slot(s)")
        # Clearing removes the cache root and the lock inside it with it.
        artifacts.acquire_sweep_lock()
    artifacts.clear_stats()
    govern_cache()

    print(f"gates to run, in order ({args.gate_set} set, {len(gates)} of {len(GATES)}):")
    for gate in gates:
        print(f"  {gate}")
    if args.fast:
        print("fast tier: pipeline-tier assertions are skipped")
    print(f"artifact cache: {artifacts.CACHE_ROOT}")
    print(f"workspace fingerprint: {artifacts.workspace_fingerprint()[:16]}")
    print()

    results: list[tuple[str, int, float, str]] = []
    for gate in gates:
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
    prune_outputs(args.prune_outputs)

    exit_code = 1 if failed else 0
    marker = write_done(
        exit_code, time.monotonic() - started, started_at, results, args.gate_set
    )
    print(f"  completion marker: {marker}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
