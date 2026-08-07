"""Shared pipeline artefacts for the gate scripts.

Six gates need the same handful of pipeline runs over the same five samples. A
full sweep performs 63 `high_level.translate` calls that reduce to 21 distinct
(sample, mode) pairs, so five sixths of the work is one gate rebuilding what
another already built. This module builds each pair once and hands the result
to whoever asks for it.

The assertions are unaffected. A gate still checks the same artefacts for the
same properties; only the provenance changes, from "this gate built it" to
"the sweep built it once".

Cache key
---------

The key is (sample content hash, mode, workspace fingerprint). The fingerprint
covers `git rev-parse HEAD`, the working tree's own diff against it, and the
contents of every file under `configs/`, so any change to code or configuration
mints a new key and no run can be served an artefact built by different code.
Files that are new and not yet committed are folded in as well: `git diff HEAD`
cannot see them, and a new module under `babeldoc/magazine/` is exactly how
this project adds pipeline behaviour, so leaving them out would be the one
remaining way to eat a stale artefact.

The key is deliberately coarse. Editing a gate script invalidates every entry
even though gate scripts cannot change pipeline output; that is the safe
direction to be wrong in, and `run_all --fast` is the answer for iterating
without paying for builds at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.docvision.doclayout import DocLayoutModel  # noqa: E402
from babeldoc.format.pdf import high_level  # noqa: E402
from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.format.pdf.translation_config import WatermarkOutputMode  # noqa: E402

# SPEC_CACHE_ROOT lets a gate point the cache somewhere disposable, which is
# how the no-cache fallback is proved without destroying the real cache.
CACHE_ROOT = Path(
    os.environ.get("SPEC_CACHE_ROOT", ROOT / "examples" / "output" / "gate_cache")
)
STATS_DIR = CACHE_ROOT / "stats"
CONFIG_DIR = ROOT / "configs"

# Read size for incremental hashing; a pure I/O buffer, not a tuning knob.
_HASH_CHUNK_BYTES = 1 << 20

# The pipeline configurations the gates actually ask for, taken from a survey
# of every TranslationConfig the six gate scripts build. The layout model is
# named rather than instantiated so that a mode that is never requested never
# loads an ONNX session.
MODES: dict[str, dict] = {
    # Dry run that stops after IL creation, with checkpoints. Used for the
    # baseline render diff and for IL-shape assertions.
    "parse_only": {
        "layout_model": "parse_only",
        "only_parse_generate_pdf": True,
        "magazine_checkpoint": True,
    },
    # The same dry run with checkpoints left at their default. b2_2 and b2_3
    # want only the produced PDF from it.
    "parse_only_plain": {
        "layout_model": "parse_only",
        "only_parse_generate_pdf": True,
    },
    # Every non-translation stage, classifier off.
    "stages": {
        "layout_model": "onnx",
        "skip_translation": True,
        "magazine_checkpoint": True,
        "magazine_page_classify": False,
    },
    # The same with checkpoints off, which is what proves the switch defaults
    # to writing nothing.
    "stages_plain": {
        "layout_model": "onnx",
        "skip_translation": True,
        "magazine_checkpoint": False,
    },
    # Every non-translation stage with the page classifier on.
    "classified": {
        "layout_model": "onnx",
        "skip_translation": True,
        "magazine_checkpoint": True,
        "magazine_page_classify": True,
    },
}

_fingerprint: str | None = None
_stats = {"hit": 0, "built": 0, "build_seconds": 0.0}


@dataclass
class Artifacts:
    """One built (sample, mode) pair, served from the cache directory."""

    working_dir: Path
    mono_pdf: Path | None
    mode: str
    sample: Path
    from_cache: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _git(args: list[str], binary: bool = False):
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for the gates
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def workspace_fingerprint(refresh: bool = False) -> str:
    """Digest of everything that can change what a pipeline run produces."""
    global _fingerprint
    if _fingerprint is not None and not refresh:
        return _fingerprint

    digest = hashlib.sha256()
    digest.update(_git(["rev-parse", "HEAD"]).strip().encode())
    digest.update(_git(["diff", "--binary", "HEAD"], binary=True))

    # Files git does not track yet still reach the interpreter.
    for relative in sorted(
        line.strip()
        for line in _git(["ls-files", "--others", "--exclude-standard"]).splitlines()
        if line.strip()
    ):
        path = ROOT / relative
        if not path.is_file():
            continue
        digest.update(relative.encode())
        digest.update(sha256_file(path).encode())

    for path in sorted(CONFIG_DIR.glob("*")):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(sha256_file(path).encode())

    _fingerprint = digest.hexdigest()
    return _fingerprint


def cache_slot(sample: Path, mode: str) -> Path:
    if mode not in MODES:
        raise KeyError(f"unknown artefact mode {mode!r}; declared are {sorted(MODES)}")
    return (
        CACHE_ROOT / workspace_fingerprint()[:16] / f"{sha256_file(sample)[:16]}.{mode}"
    )


def _layout_model(name: str):
    return DocLayoutModel.load_onnx() if name == "onnx" else _ParseOnlyDocLayoutModel()


def build_into(sample: Path, mode: str, destination: Path) -> Artifacts:
    """Run one (sample, mode) pair into ``destination``, ignoring the cache.

    The gate for this batch uses it to prove that a cached artefact equals a
    directly built one, so the two paths must share this function rather than
    each spell the configuration out.
    """
    settings = dict(MODES[mode])
    layout = settings.pop("layout_model")
    destination.mkdir(parents=True, exist_ok=True)

    config = TranslationConfig(
        translator=None,
        input_file=sample,
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_layout_model(layout),
        output_dir=destination / "out",
        working_dir=destination / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=False,
        **settings,
    )
    result = high_level.translate(config)
    mono = getattr(result, "mono_pdf_path", None)
    return Artifacts(
        working_dir=Path(config.working_dir),
        mono_pdf=Path(mono) if mono else None,
        mode=mode,
        sample=sample,
        from_cache=False,
    )


def _build(sample: Path, mode: str, slot: Path) -> None:
    """Run the pipeline for one (sample, mode) pair into ``slot``."""
    settings = dict(MODES[mode])
    layout = settings.pop("layout_model")

    staging = slot.with_name(slot.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    config = TranslationConfig(
        translator=None,
        input_file=sample,
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_layout_model(layout),
        output_dir=staging / "out",
        working_dir=staging / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=False,
        **settings,
    )
    started = time.monotonic()
    result = high_level.translate(config)
    seconds = time.monotonic() - started

    mono = getattr(result, "mono_pdf_path", None)
    if mono:
        shutil.copyfile(mono, staging / "mono.pdf")
    # TranslationConfig appends the input stem to the working directory it was
    # given, so the resolved path is recorded rather than reconstructed.
    working = Path(config.working_dir).relative_to(staging).as_posix()
    with (staging / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(
            {
                "sample": sample.name,
                "sample_sha256": sha256_file(sample),
                "mode": mode,
                "fingerprint": workspace_fingerprint(),
                "working_subdir": working,
                "build_seconds": seconds,
            },
            f,
            indent=2,
        )

    # Publish atomically, so an interrupted build is never mistaken for a hit.
    staging.replace(slot)
    _stats["built"] += 1
    _stats["build_seconds"] += seconds


def get_artifacts(sample: Path, mode: str) -> Artifacts:
    """Return the artefacts for one (sample, mode) pair, building on a miss."""
    slot = cache_slot(sample, mode)
    hit = (slot / "meta.json").exists()
    if not hit:
        _build(sample, mode, slot)
    else:
        _stats["hit"] += 1

    with (slot / "meta.json").open(encoding="utf-8") as f:
        meta = json.load(f)
    mono = slot / "mono.pdf"
    return Artifacts(
        working_dir=slot / meta["working_subdir"],
        mono_pdf=mono if mono.exists() else None,
        mode=mode,
        sample=sample,
        from_cache=hit,
    )


def stats() -> dict:
    return dict(_stats)


def write_stats(gate: str) -> Path:
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    path = STATS_DIR / f"{gate}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(_stats, f, indent=2)
        f.write("\n")
    return path


def print_stats(gate: str) -> None:
    print(
        f"artifact cache {gate}: hit={_stats['hit']} built={_stats['built']} "
        f"build_seconds={_stats['build_seconds']:.1f}"
    )


def load_all_stats() -> dict:
    total = {"hit": 0, "built": 0, "build_seconds": 0.0}
    if not STATS_DIR.is_dir():
        return total
    for path in sorted(STATS_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            entry = json.load(f)
        for key in total:
            total[key] += entry.get(key, 0)
    return total


def clear_stats() -> None:
    if STATS_DIR.is_dir():
        shutil.rmtree(STATS_DIR, ignore_errors=True)


def clear_cache() -> int:
    """Remove every cached artefact. Returns the number of slots dropped."""
    if not CACHE_ROOT.is_dir():
        return 0
    slots = [
        path
        for generation in CACHE_ROOT.iterdir()
        if generation.is_dir() and generation.name != "stats"
        for path in generation.iterdir()
        if path.is_dir()
    ]
    shutil.rmtree(CACHE_ROOT, ignore_errors=True)
    return len(slots)


def main(argv: list[str] | None = None) -> int:
    """Command line surface, used by run_all --clear-cache and for inspection."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--clear-cache":
        print(f"gate cache cleared: {clear_cache()} slot(s)")
        return 0
    print(f"fingerprint: {workspace_fingerprint()}")
    print(f"cache root:  {CACHE_ROOT}")
    if CACHE_ROOT.is_dir():
        for generation in sorted(CACHE_ROOT.iterdir()):
            if not generation.is_dir() or generation.name == "stats":
                continue
            slots = sorted(p.name for p in generation.iterdir() if p.is_dir())
            current = " (current)" if generation.name == _fingerprint[:16] else ""
            print(f"  {generation.name}{current}: {len(slots)} slot(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
