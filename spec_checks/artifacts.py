"""Shared pipeline artefacts for the gate scripts.

Most gates need the same handful of pipeline runs over the same samples, and a
full sweep asks for each of them several times over. The requests collapse to a
much smaller set of distinct (sample, mode) pairs, so without this module most
of a sweep is a gate rebuilding what another already built. This module builds
each pair once and hands the result to whoever asks for it.

The assertions are unaffected. A gate still checks the same artefacts for the
same properties; only the provenance changes, from "this gate built it" to
"the sweep built it once".

Cache key
---------

The key is (sample content hash, mode, workspace fingerprint). The fingerprint
covers `git rev-parse HEAD` and, restricted to the paths in
``FINGERPRINT_PATHS``, the working tree's diff against it plus the files git
does not track yet. Those two trees are everything a pipeline run reads: the
package that runs it and the configuration it is steered by. `git diff HEAD`
cannot see a new file, and a new module under `babeldoc/magazine/` is exactly
how this project adds pipeline behaviour, so untracked files are folded in
rather than left as the one remaining way to eat a stale artefact.

Everything else in the repository is outside the key. A gate script or a plan
document cannot change what the pipeline produces, so an edit to one no longer
discards a cache that took an hour to fill.

Within those paths the key stays deliberately coarse: any byte of any module or
configuration file invalidates every entry, whether or not that byte could have
reached the run. That is the safe direction to be wrong in, and `run_all --fast`
is the answer for iterating without paying for builds at all.

``FINGERPRINT_EXCLUDED_KEYS`` is the one exception, and it is narrow: a few
named configuration keys steer how a request leaves this machine or how the
gate cache governs itself, and none of them can reach a produced artefact. A
file listed there enters the fingerprint through its parsed form with those
keys removed, and is kept out of the git-derived half so the same exclusion
holds whether or not it is committed yet.

Size
----

Every distinct fingerprint opens a new generation directory and old generations
are never read again, so the cache only grows. `run_all` reports its size at
startup and trims it back under ``gate_cache_max_gb`` from
``configs/gate_cache.json``, least recently used slot first.
"""

from __future__ import annotations

import contextlib
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
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402
from babeldoc.magazine.page_features import Parameter  # noqa: E402
from babeldoc.magazine.page_features import validate_bounded_config  # noqa: E402

# SPEC_CACHE_ROOT lets a gate point the cache somewhere disposable, which is
# how the no-cache fallback is proved without destroying the real cache.
CACHE_ROOT = Path(
    os.environ.get("SPEC_CACHE_ROOT", ROOT / "examples" / "output" / "gate_cache")
)
STATS_DIR = CACHE_ROOT / "stats"
CONFIG_DIR = ROOT / "configs"
CACHE_CONFIG_PATH = CONFIG_DIR / "gate_cache.json"

# Repository paths whose content reaches a pipeline run: the package that
# performs it and the configuration that steers it. Everything outside them is
# outside the cache key.
FINGERPRINT_PATHS = ("babeldoc", "configs")

# Configuration keys that cannot reach a produced artefact: an endpoint, the
# name of the environment variable a credential is read from, a wall clock
# limit, and the ceiling the gate cache applies to itself. A file listed here is
# digested from its parsed form with these keys and their ``_allowed_range``
# siblings dropped, so its remaining keys still invalidate the cache and a move
# to another endpoint no longer does.
FINGERPRINT_EXCLUDED_KEYS: dict[str, tuple[str, ...]] = {
    "configs/gate_cache.json": ("description", "gate_cache_max_gb"),
    "configs/vlm.json": ("description", "base_url", "api_key_env", "timeout_seconds"),
}

# Keeps the excluded files out of the git-derived half of the fingerprint. Their
# retained keys still enter it through the configuration loop, which reads them
# from disk whether git tracks them or not.
_EXCLUDE_PATHSPECS = tuple(f":(exclude){path}" for path in FINGERPRINT_EXCLUDED_KEYS)

# Read size for incremental hashing; a pure I/O buffer, not a tuning knob.
_HASH_CHUNK_BYTES = 1 << 20

BYTES_PER_GB = 1 << 30

# The pipeline configurations the gates actually ask for, taken from a survey
# of every TranslationConfig the gate scripts build. The layout model is named
# rather than instantiated so that a mode that is never requested never loads an
# ONNX session.
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
    # The same with chain detection on, which is the only mode in which the
    # paragraph level chain fields are written at all.
    "chained": {
        "layout_model": "onnx",
        "skip_translation": True,
        "magazine_checkpoint": True,
        "magazine_page_classify": True,
        "magazine_chain_detect": True,
    },
    # The same again with article grouping on. It is its own mode rather than a
    # flag on the one above because the pair is what the switch-down comparison
    # is made of.
    "grouped": {
        "layout_model": "onnx",
        "skip_translation": True,
        "magazine_checkpoint": True,
        "magazine_page_classify": True,
        "magazine_chain_detect": True,
        "magazine_article_group": True,
    },
    # The grouped run with drop cap marking on, which is the pair the b7.2
    # switch-down comparison is made of. The marking switch is not a constructor
    # parameter (W-B7-02), so it is set on the built configuration instead.
    "drop_capped": {
        "layout_model": "onnx",
        "skip_translation": True,
        "magazine_checkpoint": True,
        "magazine_page_classify": True,
        "magazine_chain_detect": True,
        "magazine_article_group": True,
        "attributes": {"magazine_drop_cap_mark": True},
    },
    # The grouped run with post typesetting detection on, which is the pair the
    # b8 switch-down comparison is made of.
    "detected": {
        "layout_model": "onnx",
        "skip_translation": True,
        "magazine_checkpoint": True,
        "magazine_page_classify": True,
        "magazine_chain_detect": True,
        "magazine_article_group": True,
        "magazine_detect": True,
    },
}

# Settings that are not constructor parameters and are set on the built
# configuration object instead.
ATTRIBUTES_KEY = "attributes"

_fingerprint: str | None = None
_stats = {"hit": 0, "built": 0, "build_seconds": 0.0}


class BuildIncomplete(RuntimeError):
    """Raised when a run finished without producing what its mode promises."""


def _incomplete(working: Path, mono: object, mode: str) -> list[str]:
    """What a finished run owes its mode and did not deliver.

    Every mode produces a mono PDF. A mode that asks for checkpoints owes at
    least one, and one is enough: which stages appear is the business of the
    gates that read them, not of the cache.
    """
    missing: list[str] = []
    if not mono:
        missing.append("mono PDF")
    if MODES[mode].get("magazine_checkpoint") and not list(
        working.glob(f"{CHECKPOINT_PREFIX}*.xml")
    ):
        missing.append("checkpoint")
    return missing


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


def config_digest(path: Path) -> str:
    """Digest of one configuration file, minus the keys outside the cache key.

    A file with no declared exclusions is digested from its bytes, so formatting
    counts for it; a file with exclusions is digested from its parsed content,
    which is the only form in which a single key can be left out.
    """
    excluded = FINGERPRINT_EXCLUDED_KEYS.get(path.relative_to(ROOT).as_posix())
    if excluded is None:
        return sha256_file(path)
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    dropped = {key for name in excluded for key in (name, f"{name}_allowed_range")}
    kept = {key: value for key, value in raw.items() if key not in dropped}
    payload = json.dumps(kept, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


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
    digest.update(
        _git(
            [
                "diff",
                "--binary",
                "HEAD",
                "--",
                *FINGERPRINT_PATHS,
                *_EXCLUDE_PATHSPECS,
            ],
            binary=True,
        )
    )

    # Files git does not track yet still reach the interpreter.
    for relative in sorted(
        line.strip()
        for line in _git(
            [
                "ls-files",
                "--others",
                "--exclude-standard",
                "--",
                *FINGERPRINT_PATHS,
                *_EXCLUDE_PATHSPECS,
            ]
        ).splitlines()
        if line.strip()
    ):
        path = ROOT / relative
        if not path.is_file():
            continue
        digest.update(relative.encode())
        digest.update(sha256_file(path).encode())

    # Read directly rather than through git, so a configuration file git is set
    # to ignore still counts; the classifier reads the file either way.
    for path in sorted(CONFIG_DIR.glob("*")):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(config_digest(path).encode())

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
    attributes = settings.pop(ATTRIBUTES_KEY, {})
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
    for name, value in attributes.items():
        setattr(config, name, value)
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
    attributes = settings.pop(ATTRIBUTES_KEY, {})

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
    for name, value in attributes.items():
        setattr(config, name, value)
    started = time.monotonic()
    result = high_level.translate(config)
    seconds = time.monotonic() - started

    mono = getattr(result, "mono_pdf_path", None)
    if mono:
        shutil.copyfile(mono, staging / "mono.pdf")
    # TranslationConfig appends the input stem to the working directory it was
    # given, so the resolved path is recorded rather than reconstructed.
    working = Path(config.working_dir).relative_to(staging).as_posix()

    # A run the pipeline reported as finished can still have produced nothing:
    # `translate` swallows some failures and hands back a result with no PDF.
    # Publishing that leaves a slot every later hit serves as an empty working
    # directory, and a gate reading it scores zero agreement against ground
    # truth rather than reporting that nothing was built. Refusing to publish
    # keeps the failure loud and leaves the evidence in the staging directory.
    missing = _incomplete(staging / working, mono, mode)
    if missing:
        raise BuildIncomplete(
            f"{sample.name} [{mode}]: the run produced no {', '.join(missing)}; "
            f"the slot was not published and the run is left at {staging}"
        )

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


def _slots() -> list[Path]:
    """Every published cache slot, across all fingerprint generations."""
    if not CACHE_ROOT.is_dir():
        return []
    return [
        path
        for generation in CACHE_ROOT.iterdir()
        if generation.is_dir() and generation.name != STATS_DIR.name
        for path in generation.iterdir()
        if path.is_dir() and (path / "meta.json").exists()
    ]


def _slot_bytes(slot: Path) -> int:
    return sum(path.stat().st_size for path in slot.rglob("*") if path.is_file())


def load_cache_config(path: Path | None = None) -> dict[str, Parameter]:
    """Load and validate ``configs/gate_cache.json``."""
    config_path = CACHE_CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = validate_bounded_config(raw, config_path)
    if "gate_cache_max_gb" not in parameters:
        raise KeyError(f"{config_path.name}: missing parameter gate_cache_max_gb")
    return parameters


def cache_size_bytes() -> int:
    return sum(_slot_bytes(slot) for slot in _slots())


def trim_cache(max_bytes: int) -> tuple[int, int]:
    """Drop slots until the cache fits in ``max_bytes``. Least recent go first.

    A slot's mtime is its last use rather than its build time: ``get_artifacts``
    stamps it on every hit, so a generation that a sweep still serves from
    survives a trim even when a newer one exists.

    Returns the number of slots dropped and the bytes reclaimed.
    """
    sized = [(slot, _slot_bytes(slot)) for slot in _slots()]
    total = sum(size for _, size in sized)
    if total <= max_bytes:
        return 0, 0

    sized.sort(key=lambda item: item[0].stat().st_mtime)
    dropped = 0
    freed = 0
    for slot, size in sized:
        if total - freed <= max_bytes:
            break
        parent = slot.parent
        shutil.rmtree(slot, ignore_errors=True)
        dropped += 1
        freed += size
        # A generation directory left with nothing in it is noise in the
        # listing; the stats directory is not a generation and is never touched.
        with contextlib.suppress(OSError):
            if parent != STATS_DIR and not any(parent.iterdir()):
                parent.rmdir()
    return dropped, freed


def get_artifacts(sample: Path, mode: str) -> Artifacts:
    """Return the artefacts for one (sample, mode) pair, building on a miss."""
    slot = cache_slot(sample, mode)
    hit = (slot / "meta.json").exists()
    if not hit:
        _build(sample, mode, slot)
    else:
        _stats["hit"] += 1
        # Recency for the trim, which is the only reader of this timestamp.
        with contextlib.suppress(OSError):
            os.utime(slot, None)

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
