"""Read-only protection for the evidence a gate reads and must never write.

Why this module exists
---------------------

Batch b9.2 lost a set of untracked artefacts to the output retention policy,
and the two assertions that read them did not report the loss: one of them
re-ran its tool with the tracked result file as the output path, so the tool
saw no inputs, wrote a degenerate result over the frozen one, and the
assertion then reported that the recomputation "differs" -- with the frozen
copy already destroyed. The evidence and the check on it were the same file.

So the rule this module enforces: a produced number that git tracks is frozen.
A gate may read it, recompute beside it and compare, and may report that the
comparison could not be made. A gate may not write it. Recomputation goes to a
temporary directory and the comparison is on bytes; a missing input is reported
as a skip that names the path, never as a recomputation from thin air.

What is frozen
--------------

Every file git tracks under ``FROZEN_PREFIXES``. Tracked is the operative word:
these are the files a clone receives, which is what makes them the record. An
untracked file in the same directory is a work product and is not the subject
here.

How it is enforced
------------------

Two layers, because they catch different mistakes.

``snapshot`` / ``changed`` are the mechanical layer, called by
``spec_checks/run_all.py`` around every gate: whichever gate wrote a frozen
file is named and fails, whether or not anybody predicted that it could. This
is deliberately blind to intent -- a write through a tool three subprocesses
down is caught the same as a direct one.

``absent`` / ``skip`` are the cooperative layer, called by the assertions that
re-run a tool over produced inputs. They turn "the inputs are gone" into a skip
that names what is gone, which is the outcome the b9.2 loss should have had.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Where the frozen produced evidence lives. The evaluation batches write their
# results here and later batches quote them; nothing else in the repository has
# the property that a gate both reads a file and could plausibly rewrite it.
FROZEN_PREFIXES = ("docs/eval/",)

_HASH_CHUNK_BYTES = 1 << 20


def _git(args: list[str]) -> str:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for the gates
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_paths() -> list[str]:
    """Every tracked path under the frozen prefixes, repository relative."""
    listing = _git(["ls-files", "--", *FROZEN_PREFIXES])
    return sorted(line.strip() for line in listing.splitlines() if line.strip())


def snapshot() -> dict[str, str]:
    """Digest of every frozen file, keyed by its repository relative path.

    A tracked path that is not on the disk is recorded as absent rather than
    skipped, so a gate that deleted one is caught as surely as one that
    rewrote it.
    """
    state: dict[str, str] = {}
    for relative in frozen_paths():
        path = ROOT / relative
        state[relative] = _digest(path) if path.is_file() else "absent"
    return state


def changed(before: dict[str, str], after: dict[str, str] | None = None) -> list[str]:
    """Frozen paths whose bytes moved between two snapshots.

    A path present in only one of the two snapshots counts: an assertion that
    created a frozen-looking file, or removed one, has written the record just
    as much as one that edited a file in place.
    """
    now = snapshot() if after is None else after
    moved = [key for key in sorted(set(before) | set(now)) if before.get(key) != now.get(key)]
    return moved


def absent(paths) -> list[str]:
    """Which of the required inputs are not on the disk, repository relative.

    The answer an assertion needs before it re-runs a tool: an empty list means
    the recomputation can be attempted, and a non-empty one is the skip reason.
    """
    missing = []
    for item in paths:
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            with_root = path
            try:
                relative = with_root.relative_to(ROOT).as_posix()
            except ValueError:
                relative = with_root.as_posix()
            missing.append(relative)
    return sorted(missing)


def skip(name: str, missing: list[str], limit: int = 4) -> None:
    """Announce an assertion that cannot run because its inputs are gone.

    Prints the paths rather than a count. The whole failure mode this module
    answers is a message that said a comparison had failed when what had
    happened was that the thing being compared was not there.
    """
    shown = ", ".join(missing[:limit])
    if len(missing) > limit:
        shown += f", and {len(missing) - limit} more"
    print(f"SKIPPED: {name} (frozen dependency absent: {shown})")
