"""Keep examples/output/ to the size the retention policy declares.

Every batch of this project leaves its evidence under ``examples/output/``, and
nothing has ever removed any of it. That is right while a batch is live: its
gate reads its artefacts and its report is written from them. It stops being
right two batches later, when what is read back is the delivery report and the
run log and nothing else, and what is still on the disk is tens of gigabytes of
intermediate language nobody will open again.

So: the newest batch directories keep everything, earlier ones keep their
reports and their logs, and three things are never touched whatever the policy
says -- a file git tracks, a file the corpus manifest names, and any directory
that is not a batch directory at all. The last of those is what leaves the gate
cache and the timing records to the mechanisms that already govern them.

Nothing is removed unless ``--apply`` is passed. The default is a dry run that
prints what it would do, because a tool that deletes evidence is one whose
first answer should be a list rather than an action.

Usage:
    python tools/prune_outputs.py [--apply] [--root examples/output]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
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

# A batch directory: the letter, a batch number, and the sub-batch numbers
# under it. Anything after that is a name rather than a number and does not
# order the directory -- ``b5_smoke`` is part of batch 5 and is kept or pruned
# with it.
_BATCH_DIR = re.compile(r"^b(\d+)((?:_\d+)*)")

KEEP_RECENT_KEY = "keep_recent_batches"
KEEP_PATTERNS_KEY = "keep_patterns"
BASELINE_ARCHIVE_KEY = "baseline_archive"


def load_config(path: Path | None = None) -> dict:
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = dict(validate_bounded_config(raw, config_path))
    for name in (KEEP_RECENT_KEY, KEEP_PATTERNS_KEY, BASELINE_ARCHIVE_KEY):
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
                doomed.append(item)
    return doomed, recent


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
