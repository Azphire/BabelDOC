"""Shared gate harness: per-assertion timing and the two execution tiers.

Timing
------

A gate routes every ``record`` (and ``skip``) call through a :class:`Timer`.
The timer holds a cursor over the wall clock and charges the interval that a
call closes to the assertion named in that call, so the cost of reaching an
assertion is attributed to it rather than pooled into one gate total.

Work that is not an assertion -- model warm up and the pipeline runs a gate
performs before it starts checking -- is charged to named phases instead. That
split is the whole point: a gate that grew slower is then readable as either
slower assertions or slower builds, which are different defects with different
fixes.

Each gate writes its measurements to ``examples/output/gate_timing/`` and
``spec_checks/run_all.py`` summarises them. Time between the process start and
the first phase (interpreter start and imports) is not attributed here; the
runner reports it as the residual against the gate's own wall clock.

Tiers
-----

``static`` assertions read source, schema, configuration, git history and
pre-built corpus fixtures, and so need no pipeline run in the session.
``pipeline`` assertions need an artefact built during the run. ``run_all
--fast`` sets ``SPEC_FAST_TIER`` and the gates then execute the static tier
only, printing one skip line per pipeline-tier check.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMING_DIR = ROOT / "examples" / "output" / "gate_timing"

# Set by spec_checks/run_all.py --fast. A gate consults it to decide whether to
# build artefacts at all.
FAST_TIER = os.environ.get("SPEC_FAST_TIER") == "1"

# How many slow assertions the per-gate summary prints.
TOP_SLOW = 5


def fast_skip(name: str) -> None:
    """Announce a pipeline-tier check that the fast tier does not run."""
    print(f"SKIPPED: fast tier :: {name}")


class Timer:
    """Wall clock attribution for one gate process."""

    def __init__(self, gate: str) -> None:
        self.gate = gate
        self.assertions: list[tuple[str, float]] = []
        self.phases: list[tuple[str, float]] = []
        self._cursor = time.monotonic()

    def mark(self, name: str) -> float:
        """Close the open interval and charge it to ``name``."""
        now = time.monotonic()
        seconds = now - self._cursor
        self._cursor = now
        self.assertions.append((name, seconds))
        return seconds

    @contextlib.contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Charge everything done inside the block to a named phase."""
        start = time.monotonic()
        try:
            yield
        finally:
            now = time.monotonic()
            self.phases.append((name, now - start))
            # The cursor moves past the phase so the next assertion is not
            # billed for a build it did not perform.
            self._cursor = now

    def slowest(self, limit: int = TOP_SLOW) -> list[tuple[str, float]]:
        return sorted(self.assertions, key=lambda item: -item[1])[:limit]

    def print_summary(self) -> None:
        if not self.assertions and not self.phases:
            return
        phase_total = sum(seconds for _, seconds in self.phases)
        assertion_total = sum(seconds for _, seconds in self.assertions)
        print(
            f"timing {self.gate}: phases={phase_total:.1f}s "
            f"assertions={assertion_total:.1f}s"
        )
        for name, seconds in self.slowest():
            print(f"  slow assertion {seconds:8.1f}s  {name}")

    def write(self) -> Path:
        TIMING_DIR.mkdir(parents=True, exist_ok=True)
        path = TIMING_DIR / f"{self.gate}.json"
        payload = {
            "gate": self.gate,
            "assertions": [[name, seconds] for name, seconds in self.assertions],
            "phases": [[name, seconds] for name, seconds in self.phases],
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        return path


def load_timing(gate: str) -> dict | None:
    path = TIMING_DIR / f"{gate}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def clear_timing() -> None:
    if not TIMING_DIR.is_dir():
        return
    for path in TIMING_DIR.glob("*.json"):
        path.unlink()
