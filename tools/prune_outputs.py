"""Keep examples/output/ to the size the retention policy declares.

Every batch of this project leaves its evidence under ``examples/output/``, and
nothing has ever removed any of it. That is right while a batch is live: its
gate reads its artefacts and its report is written from them. It stops being
right two batches later, when what is read back is the delivery report and the
run log and nothing else, and what is still on the disk is tens of gigabytes of
intermediate language nobody will open again.

So: the newest batch directories keep everything, earlier ones keep their
reports and their logs, and four things are never touched whatever the policy
says -- a file git tracks, a file the corpus manifest names, a path the
configuration's ``protected_paths`` registers, and any directory that is not a
batch directory at all. The last of those is what leaves the gate cache and the
timing records to the mechanisms that already govern them.

``protected_paths`` exists because of what batch b9.2 lost. The evidence intake
``spec_checks/spec_check_e0.py`` registers by path and SHA-256 is precisely the
evidence that is *not* tracked -- it is kept out of git by size -- so the
tracked-file guard says nothing about it, and it cannot be rebuilt. It is now
named here and the gate for that batch asserts the two lists still agree.

Archiving
---------

An eviction used to be indistinguishable from a loss. A batch leaving the
retention window kept its report and its log in place, untracked, and lost
everything else; two batches later somebody needed one of the sidecars, and
what was on the disk was nothing. So before an evicted batch loses anything,
every file of it matching ``archive_patterns`` and no larger than
``archive_max_file_kb`` is packed into ``docs/reports/archive/<batch>.zip``,
which is tracked. Small text -- reports, JSON sidecars, logs -- costs almost
nothing compressed and is the only part anybody reads back. The bulk still
goes: an archive of the intermediate language would be the disk bill this tool
exists to avoid.

The archive is additive and never rewritten. A member already inside is left
alone and an archive with nothing to add is not touched at all, so a sweep that
changes nothing leaves no diff for the next commit to carry.

Nothing is removed unless ``--apply`` is passed. The default is a dry run that
prints what it would do, because a tool that deletes evidence is one whose
first answer should be a list rather than an action.

Usage:
    python tools/prune_outputs.py [--apply] [--root examples/output]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.checkpoint import CHECKPOINT_ARCHIVE_SUFFIX  # noqa: E402
from babeldoc.magazine.checkpoint import write_checkpoint_archive  # noqa: E402
from babeldoc.magazine.page_features import validate_bounded_config  # noqa: E402

CONFIG_PATH = ROOT / "configs" / "output_retention.json"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
OUTPUT_DIR = ROOT / "examples" / "output"
BASELINE_DIR = OUTPUT_DIR / "baseline"

# Where an evicted batch's small text is kept, in git. Under docs/ rather than
# under examples/output/ so the policy this tool applies can never reach it.
ARCHIVE_DIR = ROOT / "docs" / "reports" / "archive"

# A batch directory: the letter, a batch number, and the sub-batch numbers
# under it. Anything after that is a name rather than a number and does not
# order the directory -- ``b5_smoke`` is part of batch 5 and is kept or pruned
# with it.
_BATCH_DIR = re.compile(r"^b(\d+)((?:_\d+)*)")

KEEP_RECENT_KEY = "keep_recent_batches"
KEEP_PATTERNS_KEY = "keep_patterns"
BASELINE_ARCHIVE_KEY = "baseline_archive"
PROTECTED_PATHS_KEY = "protected_paths"
ARCHIVE_PATTERNS_KEY = "archive_patterns"
ARCHIVE_MAX_KB_KEY = "archive_max_file_kb"

REQUIRED_KEYS = (
    KEEP_RECENT_KEY,
    KEEP_PATTERNS_KEY,
    BASELINE_ARCHIVE_KEY,
    PROTECTED_PATHS_KEY,
    ARCHIVE_PATTERNS_KEY,
    ARCHIVE_MAX_KB_KEY,
)


def load_config(path: Path | None = None) -> dict:
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = dict(validate_bounded_config(raw, config_path))
    for name in REQUIRED_KEYS:
        if name not in parameters:
            raise KeyError(f"{config_path.name}: missing parameter {name}")
    return parameters


def batch_key(name: str) -> tuple[int, ...] | None:
    """The batch a directory belongs to, as a sortable tuple, or None."""
    match = _BATCH_DIR.match(name)
    if match is None:
        return None
    tail = match.group(2)
    return (int(match.group(1)), *(int(part) for part in tail.split("_") if part))


def tracked_paths(root: Path) -> set[Path]:
    """Every file git tracks under ``root``, resolved."""
    proc = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--", str(root)],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        (ROOT / line.strip()).resolve()
        for line in proc.stdout.splitlines()
        if line.strip()
    }


def manifest_paths() -> set[Path]:
    """Every path the corpus manifest names, and the archive standing for it."""
    if not MANIFEST_PATH.is_file():
        return set()
    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)
    kept: set[Path] = set()
    for entry in manifest.get("samples", ()):
        baseline = entry.get("baseline") or {}
        for value in baseline.values():
            if not isinstance(value, str) or "/" not in value:
                continue
            path = (ROOT / value).resolve()
            kept.add(path)
            kept.add(path.with_name(path.name + CHECKPOINT_ARCHIVE_SUFFIX))
    return kept


def registered_paths(config: dict) -> tuple[set[Path], tuple[Path, ...]]:
    """The configured protection list, split into exact files and directories.

    An entry ending in a separator stands for everything below it, which is how
    a whole logs directory is registered without naming its files.
    """
    files: set[Path] = set()
    directories: list[Path] = []
    for entry in config[PROTECTED_PATHS_KEY]:
        text = str(entry)
        target = (ROOT / text.rstrip("/")).resolve()
        if text.endswith("/"):
            directories.append(target)
        else:
            files.add(target)
    return files, tuple(directories)


def gate_evidence() -> tuple[set[Path], tuple[Path, ...]]:
    """What the gates themselves say they still read, split into files and dirs.

    ``protected_paths`` answers for evidence a person registered by hand, which
    means it answers a batch late: the b10.1, b10.3 and b10.4 gates each stood on
    a working file nobody had thought to name, and the policy took all three
    while every one of those gates was still in the sweep. A gate is the only
    thing that knows what it reads, so it says so itself -- a module level
    ``GATE_EVIDENCE`` naming repository relative paths, an entry ending in a
    separator standing for everything below it.

    Read out of the source rather than imported, for the reason ``GATE_SET`` is:
    importing a gate runs its module body. A gate that declares nothing
    contributes nothing, so this is additive to every gate that has not been
    given a declaration yet.
    """
    files: set[Path] = set()
    directories: list[Path] = []
    gate_dir = ROOT / "spec_checks"
    if not gate_dir.is_dir():
        return files, ()
    for gate in sorted(gate_dir.glob("spec_check_*.py")):
        try:
            tree = ast.parse(gate.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id != "GATE_EVIDENCE":
                continue
            try:
                declared = ast.literal_eval(node.value)
            except ValueError:
                continue
            for entry in declared:
                text = str(entry)
                resolved = (ROOT / text.rstrip("/")).resolve()
                if text.endswith("/"):
                    directories.append(resolved)
                else:
                    files.add(resolved)
    return files, tuple(directories)


def is_registered(path: Path, files: set[Path], directories: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    if resolved in files:
        return True
    return any(directory in resolved.parents for directory in directories)


def batch_name(key: tuple[int, ...]) -> str:
    """The batch a key stands for, written the way a directory name writes it."""
    return "b" + "_".join(str(part) for part in key)


def batch_directories(root: Path) -> dict[tuple[int, ...], list[Path]]:
    """Batch directories under ``root``, grouped by the batch they belong to."""
    grouped: dict[tuple[int, ...], list[Path]] = {}
    if not root.is_dir():
        return grouped
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        key = batch_key(path.name)
        if key is None:
            continue
        grouped.setdefault(key, []).append(path)
    return grouped


def kept_by_pattern(path: Path, patterns) -> bool:
    return any(path.match(pattern) for pattern in patterns)


def prunable(root: Path, config: dict) -> tuple[list[Path], list[tuple[int, ...]]]:
    """The files the policy would remove, and the batches being kept whole."""
    grouped = batch_directories(root)
    keep_recent = int(config[KEEP_RECENT_KEY])
    recent = sorted(grouped, reverse=True)[:keep_recent]
    protected = tracked_paths(root) | manifest_paths()
    registered_files, registered_dirs = registered_paths(config)
    declared_files, declared_dirs = gate_evidence()
    registered_files = registered_files | declared_files
    registered_dirs = registered_dirs + declared_dirs
    patterns = tuple(config[KEEP_PATTERNS_KEY])

    doomed: list[Path] = []
    for key in sorted(grouped):
        if key in recent:
            continue
        for directory in grouped[key]:
            for item in sorted(directory.rglob("*")):
                if not item.is_file():
                    continue
                if item.resolve() in protected or kept_by_pattern(item, patterns):
                    continue
                if is_registered(item, registered_files, registered_dirs):
                    continue
                doomed.append(item)
    return doomed, recent


def archivable(root: Path, config: dict) -> dict[str, list[Path]]:
    """What each evicted batch would contribute to its archive, by batch name.

    Everything in the batch that matches ``archive_patterns`` and is inside the
    size cap, whether or not the policy is about to delete it: a file the keep
    patterns leave in place is still untracked, and leaving it out of the
    archive is what made a clone of this repository lose the reports of every
    evicted batch. A file git already tracks is left out, since the archive
    exists to get untracked evidence into git and it is already there.
    """
    grouped = batch_directories(root)
    keep_recent = int(config[KEEP_RECENT_KEY])
    recent = set(sorted(grouped, reverse=True)[:keep_recent])
    tracked = tracked_paths(root)
    patterns = tuple(config[ARCHIVE_PATTERNS_KEY])
    ceiling = int(config[ARCHIVE_MAX_KB_KEY]) * 1024

    selected: dict[str, list[Path]] = {}
    for key in sorted(grouped):
        if key in recent:
            continue
        chosen: list[Path] = []
        for directory in grouped[key]:
            for item in sorted(directory.rglob("*")):
                if not item.is_file() or item.resolve() in tracked:
                    continue
                if not kept_by_pattern(item, patterns):
                    continue
                try:
                    if item.stat().st_size > ceiling:
                        continue
                except OSError:
                    continue
                chosen.append(item)
        if chosen:
            selected[batch_name(key)] = chosen
    return selected


def archive_evicted(
    root: Path,
    config: dict,
    apply_changes: bool,
    archive_dir: Path | None = None,
) -> list[tuple[Path, list[str]]]:
    """Add each evicted batch's small text to its archive. Returns what was added.

    Additive by construction: a member already in the archive is not written
    again and an archive with nothing to add is not opened for writing, so a
    second pass over an unchanged tree leaves the archive byte for byte as it
    was. Member names are relative to ``root``, so the archive reads as the
    subtree it came from.

    ``archive_dir`` defaults to the tracked archive and exists so a caller can
    exercise the pass against a disposable destination.
    """
    destination = ARCHIVE_DIR if archive_dir is None else Path(archive_dir)
    added: list[tuple[Path, list[str]]] = []
    for name, files in sorted(archivable(root, config).items()):
        archive = destination / f"{name}.zip"
        present: set[str] = set()
        if archive.is_file():
            with zipfile.ZipFile(archive) as bundle:
                present = set(bundle.namelist())
        members = []
        for item in files:
            try:
                member = item.relative_to(root).as_posix()
            except ValueError:
                member = item.name
            if member not in present:
                members.append((member, item))
        if not members:
            continue
        if apply_changes:
            destination.mkdir(parents=True, exist_ok=True)
            mode = "a" if archive.is_file() else "w"
            with zipfile.ZipFile(
                archive, mode, compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as bundle:
                for member, item in members:
                    bundle.write(item, member)
        added.append((archive, [member for member, _ in members]))
    return added


def archive_baselines(config: dict, apply_changes: bool) -> list[tuple[Path, int, int]]:
    """Pack each frozen baseline checkpoint directory into its archive.

    The archive is what every reader resolves a checkpoint directory to, so this
    changes where the bytes are and nothing about what can be read. Returns one
    row per directory: the directory, what it cost and what the archive costs.
    """
    rows: list[tuple[Path, int, int]] = []
    if not BASELINE_DIR.is_dir():
        return rows
    for pattern in config[BASELINE_ARCHIVE_KEY]:
        for directory in sorted(BASELINE_DIR.glob(pattern)):
            if not directory.is_dir():
                continue
            files = sorted(item for item in directory.iterdir() if item.is_file())
            before = sum(item.stat().st_size for item in files)
            archive = directory.with_name(directory.name + CHECKPOINT_ARCHIVE_SUFFIX)
            if not apply_changes:
                rows.append((directory, before, 0))
                continue
            write_checkpoint_archive(files, archive)
            after = archive.stat().st_size
            shutil.rmtree(directory, ignore_errors=True)
            rows.append((directory, before, after))
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="remove what the policy says to remove; without it nothing is written",
    )
    parser.add_argument(
        "--root",
        default=str(OUTPUT_DIR),
        help="the output directory to apply the policy to",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    root = Path(args.root)

    archived = archive_baselines(config, args.apply)
    for directory, before, after in archived:
        if args.apply:
            print(
                f"baseline archived: {directory.name} "
                f"{before / (1 << 20):.1f} MB -> {after / (1 << 20):.1f} MB"
            )
        else:
            print(
                f"baseline would be archived: {directory.name} "
                f"({before / (1 << 20):.1f} MB)"
            )

    # Before anything is removed: an eviction that archived nothing is what made
    # batch b9.2's loss silent.
    for archive, members in archive_evicted(root, config, args.apply):
        verb = "archived" if args.apply else "would archive"
        print(
            f"evidence {verb}: {archive.relative_to(ROOT).as_posix()} "
            f"+{len(members)} member(s)"
        )
        for member in members[:10]:
            print(f"    {member}")
        if len(members) > 10:
            print(f"    ... and {len(members) - 10} more")

    doomed, recent = prunable(root, config)
    total = 0
    for item in doomed:
        try:
            total += item.stat().st_size
        except OSError:
            continue
    kept = ", ".join("b" + "_".join(str(part) for part in key) for key in recent)
    print(
        f"output retention: {len(doomed)} file(s), "
        f"{total / (1 << 30):.2f} GB, in batches older than [{kept}]"
    )
    if not args.apply:
        for item in doomed[:10]:
            print(f"  would remove {item.relative_to(ROOT).as_posix()}")
        if len(doomed) > 10:
            print(f"  ... and {len(doomed) - 10} more")
        return 0

    removed = 0
    for item in doomed:
        try:
            item.unlink()
            removed += 1
        except OSError as exc:
            print(f"  left in place: {item.name} ({exc})")
    # Directories emptied by the pass are noise in a listing and are removed
    # from the leaves up; one still holding a kept file simply refuses.
    for key, directories in sorted(batch_directories(root).items()):
        if key in recent:
            continue
        for directory in directories:
            for path in sorted(directory.rglob("*"), reverse=True):
                if path.is_dir():
                    try:
                        path.rmdir()
                    except OSError:
                        continue
    print(f"output retention: {removed} file(s) removed, {total / (1 << 30):.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
