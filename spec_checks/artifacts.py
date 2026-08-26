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

That opening trim bounds what a sweep *starts* from and not what it reaches: a
sweep whose fingerprint is new builds a full generation on top of a cache that
was already at the ceiling, and nothing would reclaim the difference until the
next sweep began. So a build also fits itself in before it publishes -- it
measures what it is about to add, sweeps least recently used slots until that
much room exists, and only then moves the staging directory into place. The
sweep is best effort by construction: a slot it cannot remove is left where it
is and the build publishes anyway. A cache over its ceiling is a disk bill,
while a build that raised rather than published is a gate that cannot run.
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
    "configs/gate_cache.json": (
        "description",
        "gate_cache_max_gb",
        "staging_stale_after_seconds",
    ),
    "configs/vlm.json": ("description", "base_url", "api_key_env", "timeout_seconds"),
    # Every key of the retention policy. It governs what is deleted from
    # examples/output/ after a sweep has finished and is read by nothing on a
    # pipeline path, so no value in it can reach a produced artefact. Listing
    # the whole file rather than a few keys is deliberate: tightening the policy
    # should cost a review, not an hour of rebuilds.
    "configs/output_retention.json": (
        "description",
        "keep_recent_batches",
        "keep_patterns",
        "archive_patterns",
        "archive_max_file_kb",
        "protected_paths",
        "baseline_archive",
    ),
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
    # The detected run with the repair loop on, which is the pair the b8.2
    # switch-down comparison is made of. The repair switch is not a constructor
    # parameter (W-B8-01), so it is set on the built configuration instead.
    "repaired": {
        "layout_model": "onnx",
        "skip_translation": True,
        "magazine_checkpoint": True,
        "magazine_page_classify": True,
        "magazine_chain_detect": True,
        "magazine_article_group": True,
        "magazine_detect": True,
        "attributes": {"magazine_repair": True},
    },
}

# Settings that are not constructor parameters and are set on the built
# configuration object instead.
ATTRIBUTES_KEY = "attributes"

# Suffix marking a build in progress. A directory carrying it is never a slot.
STAGING_SUFFIX = ".partial"

# Held for the length of one sweep. It sits beside the generation directories
# rather than inside one, because the thing being serialised is access to the
# cache as a whole: the trim, the abandoned-staging sweep and the make-room pass
# all reach across generations.
SWEEP_LOCK = CACHE_ROOT / "sweep.lock"

# Written into a staging directory while its build runs, and removed before the
# directory is published. It is what exempts a build from the sweep it triggers
# itself, and its absence is what makes an interrupted build's leftovers
# reclaimable rather than invisible.
STAGING_LOCK = "building.json"

_fingerprint: str | None = None
_stats = {
    "hit": 0,
    "built": 0,
    "build_seconds": 0.0,
    "swept_slots": 0,
    "swept_bytes": 0,
}


class BuildIncomplete(RuntimeError):  # noqa: N818 - retained gate API
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

    staging = slot.with_name(slot.name + STAGING_SUFFIX)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    _take_lock(staging)

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

    # Fit what is about to be published into the budget before publishing it,
    # so a sweep that builds a whole new generation stays under the ceiling
    # while it runs rather than only at the start of the next sweep.
    room = make_room(directory_bytes(staging))
    if room["dropped_slots"]:
        print(
            f"gate cache swept before publishing {slot.name}: "
            f"{room['dropped_slots']} slot(s), "
            f"{room['freed_bytes'] / BYTES_PER_GB:.2f} GB reclaimed"
        )
    if room["single_slot_over_budget"]:
        print(
            f"gate cache: {slot.name} is {room['incoming_bytes'] / BYTES_PER_GB:.2f} GB "
            f"on its own against a {room['max_bytes'] / BYTES_PER_GB:g} GB ceiling; "
            f"published anyway, no sweep can make it fit"
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
                "cache_room": room,
            },
            f,
            indent=2,
        )

    # Publish atomically, so an interrupted build is never mistaken for a hit.
    # The lock goes first: a published slot is not a build in progress, and one
    # carrying a lock would exempt itself from every later sweep.
    with contextlib.suppress(OSError):
        (staging / STAGING_LOCK).unlink()
    staging.replace(slot)
    _stats["built"] += 1
    _stats["build_seconds"] += seconds


def _slots() -> list[Path]:
    """Every published cache slot, across all fingerprint generations.

    A staging directory is not one, whether or not it has reached the point of
    carrying a ``meta.json``: it belongs to a build in progress, and a sweep
    that removed it would delete the very thing it is making room for.
    """
    if not CACHE_ROOT.is_dir():
        return []
    return [
        path
        for generation in CACHE_ROOT.iterdir()
        if generation.is_dir() and generation.name != STATS_DIR.name
        for path in generation.iterdir()
        if path.is_dir()
        and not path.name.endswith(STAGING_SUFFIX)
        and (path / "meta.json").exists()
    ]


def _take_lock(staging: Path) -> Path:
    """Declare a staging directory as belonging to a build in progress."""
    path = staging / STAGING_LOCK
    with path.open("w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "started": time.time()}, f)
    return path


def pid_is_running(pid: object) -> bool:
    """Whether a process with this pid exists, as far as the platform will say.

    Two things this is not. It is not proof that the pid is the *same* process
    that wrote the lock -- pids are reused -- which is why the configured
    staleness window still applies on top of it. And it is not a permission
    check: a process owned by somebody else counts as running, because the
    question is whether the pid is taken, not whether it can be signalled.

    An answer this cannot establish is reported as running, so an unreadable
    platform never turns into a sweep deleting a live build's staging tree.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # PROCESS_QUERY_LIMITED_INFORMATION: enough to read an exit code, and
        # granted for a process this account could not otherwise touch.
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            # ERROR_INVALID_PARAMETER is what a pid that does not exist gives;
            # anything else (access denied above all) means it does.
            return kernel32.GetLastError() != 87
        try:
            # A pid whose process has exited stays valid while somebody holds a
            # handle to it, so the handle alone does not answer the question.
            # STILL_ACTIVE is the exit code of a process that has not exited.
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _lock_is_live(staging: Path) -> bool:
    """Whether a staging directory still belongs to a build that is running.

    This process's own builds are known by their pid and are never in doubt.
    Another process's lock is believed while its pid is still taken and while
    the configuration's staleness window has not run out -- either condition
    failing makes the directory what an interrupted build leaves, which is what
    it almost always is.

    The pid test is what the staleness window alone could not do. A killed
    sweep used to hold its staging tree, and the disk under it, for the whole
    window: a day, for tens of gigabytes, with nothing running.
    """
    path = staging / STAGING_LOCK
    try:
        with path.open(encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        return False
    if lock.get("pid") == os.getpid():
        return True
    if not pid_is_running(lock.get("pid")):
        return False
    started = lock.get("started")
    if isinstance(started, bool) or not isinstance(started, int | float):
        return False
    return time.time() - float(started) < staging_stale_after_seconds()


def _staging_dirs() -> list[Path]:
    """Every staging directory in the cache, whether live or abandoned."""
    if not CACHE_ROOT.is_dir():
        return []
    return [
        path
        for generation in CACHE_ROOT.iterdir()
        if generation.is_dir() and generation.name != STATS_DIR.name
        for path in generation.iterdir()
        if path.is_dir() and path.name.endswith(STAGING_SUFFIX)
    ]


def abandoned_staging() -> list[Path]:
    """Staging directories no build is working in: dead weight on the disk."""
    return [path for path in _staging_dirs() if not _lock_is_live(path)]


def drop_abandoned() -> tuple[int, int]:
    """Remove what interrupted builds left behind. Returns directories and bytes.

    Unconditional rather than budget driven. A staging directory can never be
    served as a hit, so keeping one under the ceiling buys nothing, and the
    reason one is here at all is that some earlier build did not finish.
    """
    dropped = 0
    freed = 0
    for path in abandoned_staging():
        size = directory_bytes(path)
        parent = path.parent
        shutil.rmtree(path, ignore_errors=True)
        remaining = directory_bytes(path) if path.exists() else 0
        if remaining >= size:
            continue
        dropped += 1
        freed += size - remaining
        with contextlib.suppress(OSError):
            if parent != STATS_DIR and not any(parent.iterdir()):
                parent.rmdir()
    return dropped, freed


class SweepInProgress(RuntimeError):  # noqa: N818 - reads as its sibling above
    """Raised when another sweep already holds the cache."""


def _read_lock(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        return {}
    return lock if isinstance(lock, dict) else {}


def sweep_lock_holder() -> dict | None:
    """The sweep currently holding the cache, or None if it is free.

    A lock whose pid is gone, or whose age has run past the staleness window,
    is not a holder: it is what a killed sweep left behind.
    """
    lock = _read_lock(SWEEP_LOCK)
    if not lock:
        return None
    if lock.get("pid") == os.getpid():
        return lock
    if not pid_is_running(lock.get("pid")):
        return None
    started = lock.get("started")
    if isinstance(started, bool) or not isinstance(started, int | float):
        return None
    if time.time() - float(started) >= staging_stale_after_seconds():
        return None
    return lock


def acquire_sweep_lock() -> Path:
    """Claim the cache for this process's sweep, or refuse to start.

    Two sweeps sharing one cache are not merely slower. They build the same
    slots into the same staging directories, and each one's publish step sweeps
    least recently used slots to make room for what it is about to add -- so the
    second sweep can reclaim the very generation the first is serving hits from,
    and both come away with artefacts neither can account for. There is no
    partial-credit version of this: the second sweep is refused, immediately and
    with the holder named, so the operator knows which process to wait for.
    """
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": os.getpid(), "started": time.time()})

    # Create exclusively first, so two sweeps launched in the same instant do
    # not both read an absent lock and both proceed. That is not a hypothetical:
    # the first version of this checked for a holder and then wrote, and a pair
    # of sweeps started together sailed through the gap between the two steps.
    try:
        handle = os.open(SWEEP_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        handle = None
    if handle is not None:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(payload)
        return SWEEP_LOCK

    # A lock is on the disk. Whether it means anything is the holder's business:
    # this process's own, a dead process's and an expired one are all free.
    holder = sweep_lock_holder()
    if holder is not None and holder.get("pid") != os.getpid():
        age = time.time() - float(holder.get("started") or 0.0)
        raise SweepInProgress(
            f"another sweep holds {SWEEP_LOCK}: pid {holder.get('pid')}, "
            f"started {age / 60:.1f} minute(s) ago. Wait for it to finish, or "
            f"remove that file if you know the process is gone."
        )
    with SWEEP_LOCK.open("w", encoding="utf-8") as f:
        f.write(payload)
    return SWEEP_LOCK


def release_sweep_lock() -> None:
    """Give the cache back, if this process is the one holding it."""
    if _read_lock(SWEEP_LOCK).get("pid") == os.getpid():
        with contextlib.suppress(OSError):
            SWEEP_LOCK.unlink()


def directory_bytes(path: Path) -> int:
    """Bytes a directory tree occupies, ignoring what vanishes while counting.

    A file removed by a concurrent sweep between the listing and the ``stat``
    is not an error here: it is a file that no longer costs anything, which is
    the answer being measured.
    """
    total = 0
    for entry in path.rglob("*"):
        with contextlib.suppress(OSError):
            if entry.is_file():
                total += entry.stat().st_size
    return total


def _slot_bytes(slot: Path) -> int:
    return directory_bytes(slot)


def _mtime(path: Path) -> float:
    """Last use of a slot; a slot that vanished sorts first and is skipped."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def load_cache_config(path: Path | None = None) -> dict[str, Parameter]:
    """Load and validate ``configs/gate_cache.json``."""
    config_path = CACHE_CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = validate_bounded_config(raw, config_path)
    for name in ("gate_cache_max_gb", "staging_stale_after_seconds"):
        if name not in parameters:
            raise KeyError(f"{config_path.name}: missing parameter {name}")
    return parameters


def cache_size_bytes() -> int:
    """What the cache costs: its slots, plus what interrupted builds left.

    A staging directory belonging to a running build is not counted, because it
    is what a build is about to publish rather than what the cache is holding,
    and the build accounts for it as the incoming size it fits into the budget.
    """
    return sum(_slot_bytes(path) for path in [*_slots(), *abandoned_staging()])


def trim_cache(max_bytes: int) -> tuple[int, int]:
    """Drop slots until the cache fits in ``max_bytes``. Least recent go first.

    A slot's mtime is its last use rather than its build time: ``get_artifacts``
    stamps it on every hit, so a generation that a sweep still serves from
    survives a trim even when a newer one exists.

    What an interrupted build left goes first and goes whether or not the cache
    is over its ceiling, since it is the one thing here that could never be
    served. Returns the number of directories dropped and the bytes reclaimed.
    """
    dropped, freed = drop_abandoned()
    sized = [(slot, _slot_bytes(slot)) for slot in _slots()]
    total = sum(size for _, size in sized)
    if total <= max_bytes:
        return dropped, freed

    sized.sort(key=lambda item: _mtime(item[0]))
    # Counted apart from what the abandoned sweep reclaimed, because the target
    # is the size of the published slots and that is what ``total`` measures.
    reclaimed = 0
    for slot, size in sized:
        if total - reclaimed <= max_bytes:
            break
        parent = slot.parent
        shutil.rmtree(slot, ignore_errors=True)
        # What the removal actually reclaimed. A slot holding a file another
        # process still has open survives on Windows, and counting it as freed
        # would end the loop believing in room that does not exist.
        remaining = _slot_bytes(slot) if slot.exists() else 0
        if remaining >= size:
            continue
        dropped += 1
        reclaimed += size - remaining
        freed += size - remaining
        # A generation directory left with nothing in it is noise in the
        # listing; the stats directory is not a generation and is never touched.
        with contextlib.suppress(OSError):
            if parent != STATS_DIR and not any(parent.iterdir()):
                parent.rmdir()
    return dropped, freed


def max_cache_bytes() -> int:
    """The configured ceiling, in bytes."""
    return int(float(load_cache_config()["gate_cache_max_gb"]) * BYTES_PER_GB)


def staging_stale_after_seconds() -> float:
    """How long another process's build lock is believed."""
    return float(load_cache_config()["staging_stale_after_seconds"])


def make_room(incoming_bytes: int) -> dict:
    """Sweep least recently used slots until ``incoming_bytes`` fits the budget.

    Returns what it did, for the caller to record: the ceiling it worked to,
    what the cache held before and after, how much it reclaimed, and whether
    the slot about to be published overruns the ceiling on its own.

    The single slot larger than the whole budget is not an error and is not
    refused. Nothing can be swept to make it fit, so it publishes and the
    overrun is reported: a gate cache that declined to hold what a gate just
    built would make that gate rebuild it on every sweep, which costs more than
    the disk it was protecting.
    """
    max_bytes = max_cache_bytes()
    before = cache_size_bytes()
    overrun = incoming_bytes > max_bytes
    room = max(0, max_bytes - incoming_bytes)
    # Unconditional: a cache already inside the ceiling still has nothing to
    # gain from what an interrupted build left, and the sweep's own early
    # return is what keeps a slot from being dropped when there is room.
    dropped, freed = trim_cache(room)
    _stats["swept_slots"] += dropped
    _stats["swept_bytes"] += freed
    return {
        "max_bytes": max_bytes,
        "incoming_bytes": incoming_bytes,
        "before_bytes": before,
        "after_bytes": before - freed,
        "dropped_slots": dropped,
        "freed_bytes": freed,
        "single_slot_over_budget": overrun,
    }


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
    total = dict.fromkeys(_stats, 0)
    total["build_seconds"] = 0.0
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
