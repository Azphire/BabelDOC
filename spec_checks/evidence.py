"""Read a batch's evidence, from the workspace or from the archive behind it.

A gate stands on what its batch produced. Most of that is never committed --
it is too big -- so the output retention policy takes it two batches later, and
before it does, ``tools/prune_outputs.py`` packs every small text file of the
batch into ``docs/reports/archive/<batch>.zip``, which git tracks. Until now
nothing read that archive back: a gate looked in the workspace, found nothing,
and reported SKIPPED, so a file that had been carefully archived was as good as
gone.

This module closes that half. ``read_bytes`` and ``read_json`` resolve a path
under ``examples/output/`` to the workspace copy when there is one and to the
archive member standing for it when there is not, and raise ``EvidenceMissing``
naming both places when neither has it. A gate written against these reads its
evidence for as long as the archive holds it rather than for as long as the
retention window does.

What this does not do is make an unarchivable file readable. The archive admits
what ``archive_patterns`` names and what fits inside ``archive_max_file_kb``, so
a stage checkpoint of tens of megabytes was never in it and is not recoverable
here; that is what the extraction rule in CLAUDE.md section 4 answers, by having
a batch write the small derived file its gate will actually read. This module is
the reading half of that arrangement and assumes the writing half was done.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "examples" / "output"
ARCHIVE_DIR = ROOT / "docs" / "reports" / "archive"


class EvidenceMissing(FileNotFoundError):
    """Neither the workspace nor the archive holds the evidence asked for."""


def archive_member(path: Path | str) -> tuple[Path, str] | None:
    """The archive and member name standing for one path, or None.

    Only paths under ``examples/output/<batch>/`` have one: the archive is keyed
    by batch directory and its members are named relative to ``examples/output``,
    which is how ``prune_outputs.archive_evicted`` writes them.
    """
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    try:
        relative = target.resolve().relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 2:
        return None
    return ARCHIVE_DIR / f"{parts[0]}.zip", relative.as_posix()


def read_bytes(path: Path | str) -> bytes:
    """One evidence file's bytes, from the workspace or from the archive."""
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    if target.is_file():
        return target.read_bytes()
    resolved = archive_member(target)
    if resolved is not None:
        archive, member = resolved
        if archive.is_file():
            with zipfile.ZipFile(archive) as bundle:
                try:
                    return bundle.read(member)
                except KeyError:
                    pass
    places = [str(target)]
    if resolved is not None:
        places.append(f"{resolved[0]}::{resolved[1]}")
    raise EvidenceMissing("; ".join(places))


def read_json(path: Path | str):
    """One evidence file, parsed, from the workspace or from the archive."""
    return json.loads(read_bytes(path).decode("utf-8"))


def source_of(path: Path | str) -> str:
    """Where a read of this path would come from: workspace, archive or neither.

    For an assertion that wants to say which copy it stood on, and for the gate
    that proves the fallback is reached rather than merely present.
    """
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    if target.is_file():
        return "workspace"
    resolved = archive_member(target)
    if resolved is not None:
        archive, member = resolved
        if archive.is_file():
            with zipfile.ZipFile(archive) as bundle:
                if member in bundle.namelist():
                    return "archive"
    return "missing"


def exists(path: Path | str) -> bool:
    return source_of(path) != "missing"
