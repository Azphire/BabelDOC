"""Gate script for batch B2.5 (gate artefact cache, tiered execution, timing).

Run from the repository root:

    python spec_checks/spec_check_b2_5.py

Exit code 0 when every assertion in plans/PLAN_B2_5.md passes, 1 otherwise.
Requires no API key: the pipeline is exercised with skip_translation and
only_parse_generate_pdf.

The batch changes how the gates obtain their evidence, never what they assert,
so the load-bearing assertion here is 08: the set of assertion descriptions
across the gate scripts may grow but no member of it may change or disappear.

Three assertions drive whole gate processes or a whole sweep (04, 05, 07).
Under spec_checks/run_all.py they are suppressed, the same SPEC_NO_NESTED
contract the earlier gates use; running this file on its own executes them.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

PYTHON = sys.executable
# Tag that freezes this batch; once it exists the scope assertions read the
# delta it introduced instead of the working tree.
BATCH_TAG = "batch-b2.5"
# The commit this batch builds on; assertion descriptions are compared to it.
PREVIOUS_TAG = "batch-b2.4"

MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
LABELS_PATH = ROOT / "corpus" / "page_labels.json"
INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output" / "b2_5"

# Gate scripts that existed at PREVIOUS_TAG, whose assertion descriptions this
# batch may extend but not rewrite.
FROZEN_GATES = (
    "spec_checks/spec_check_b0.py",
    "spec_checks/spec_check_b1.py",
    "spec_checks/spec_check_b2.py",
    "spec_checks/spec_check_b2_1.py",
    "spec_checks/spec_check_b2_2.py",
    "spec_checks/spec_check_b2_3.py",
)

# Files this batch is allowed to change, per PLAN_B2_5 negative assertion 9.
# The plan document itself is on the list although the plan's own enumeration
# omits it: every earlier batch commits its plan, and the file is part of this
# batch's record rather than of its behaviour.
ALLOWED_CHANGES = {
    "CLAUDE.md",
    "babeldoc/magazine/corpus.py",
    "plans/PLAN_B2_5.md",
    "spec_checks/artifacts.py",
    "spec_checks/harness.py",
    "spec_checks/run_all.py",
    "spec_checks/spec_check_b0.py",
    "spec_checks/spec_check_b1.py",
    "spec_checks/spec_check_b2.py",
    "spec_checks/spec_check_b2_1.py",
    "spec_checks/spec_check_b2_2.py",
    "spec_checks/spec_check_b2_3.py",
    "spec_checks/spec_check_b2_5.py",
    "tools/render_diff.py",
}

# Trees and root documents owned by the magazine extension; the upstream scope
# assertion ignores them.
PROJECT_OWNED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "corpus/",
    "examples/",
    "plans/",
    "prompts/",
    "spec_checks/",
    "tools/",
)
PROJECT_OWNED_FILES = {"CLAUDE.md", "UPSTREAM_DIFF.md", "WAIVERS.md"}

# The one assertion the plan expects to stay red until a tuning batch reaches
# the agreement threshold.
EXPECTED_RED = "06c classification agrees with the human page labels"

# Ceiling the plan puts on a fast-tier sweep.
FAST_TIER_BUDGET_SECONDS = 300

# Sample and mode used to compare the cached path against a direct build. The
# smallest sample keeps the comparison affordable; the classifier mode gives it
# the richest checkpoint set to compare.
COMPARISON_MODE = "classified"

# An assertion description starts with its ordinal: two digits, an optional
# sub-letter, then a space.
_ASSERTION_NAME = re.compile(r"^\d\d[a-z]?\s")

# The pipeline stamps every paragraph with a fresh random debug label on each
# run, so two builds of one sample never match byte for byte from
# paragraph_finder onwards. Nothing in this project reads the label; upstream
# uses it for log lines and for identity within a single run. Comparing
# checkpoints therefore means comparing them modulo this label, and 01b is what
# keeps that honest by showing two direct builds differ the same way.
_DEBUG_LABEL = re.compile(r'\sdebug_id="[^"]*"')

# Gates that re-run their predecessors when executed on their own; those are
# the ones the nesting switch has to reach.
NESTING_GATES = (
    "spec_checks/spec_check_b2_1.py",
    "spec_checks/spec_check_b2_2.py",
    "spec_checks/spec_check_b2_3.py",
)

# Set by spec_checks/run_all.py. The three assertions that drive whole gate
# processes are the fallback for running this file on its own; under the runner
# they would repeat the sweep that is already in progress.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# Documents whose prose is Chinese by design; the CJK scan covers code only.
CJK_SCAN_SUFFIXES = (".py", ".json")

# Checks that need an artefact built during this run.
PIPELINE_TIER = ("check_01_cache_equivalence",)

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b2_5_"))
_timer = harness.Timer("spec_check_b2_5")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


# --- helpers ----------------------------------------------------------------


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def batch_tag_exists() -> bool:
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{BATCH_TAG}^{{commit}}"])
    return code == 0


def changed_files() -> set[str]:
    """Every path this batch changed.

    Before the batch is committed that is the working tree delta against HEAD.
    Once the batch is tagged the same delta is the tag against its parent, so a
    later batch can re-run this gate without its own changes counting here.
    """
    if batch_tag_exists():
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^", BATCH_TAG])
        return {line.strip() for line in listing.splitlines() if line.strip()}

    _, listing = git_output(["status", "--porcelain", "--untracked-files=all"])
    paths: set[str] = set()
    for line in listing.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def assertion_names(source: str) -> set[str]:
    """Every assertion description a gate script spells out.

    Both plain strings and f-strings count; a formatted placeholder collapses
    to ``{}`` so that a description carrying a sample name compares by shape.
    """
    names: set[str] = set()

    def render(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    parts.append(piece.value)
                else:
                    parts.append("{}")
            return "".join(parts)
        return None

    for node in ast.walk(ast.parse(source)):
        text = render(node)
        if text and _ASSERTION_NAME.match(text):
            names.add(text)
    return names


def render_diff(pdf_a: Path, pdf_b: Path, out_dir: Path) -> int:
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [
            PYTHON,
            str(ROOT / "tools" / "render_diff.py"),
            str(pdf_a),
            str(pdf_b),
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode


def canonical_checkpoints(directory: Path, strip_labels: bool = True) -> dict[str, str]:
    """Checkpoint name -> canonical XML, the form byte comparison must use."""
    converter = XMLConverter()
    out: dict[str, str] = {}
    for path in sorted(directory.glob(f"{CHECKPOINT_PREFIX}*.xml")):
        xml = converter.to_xml(checkpoint_module.load_checkpoint(path))
        out[path.name] = _DEBUG_LABEL.sub("", xml) if strip_labels else xml
    return out


def differing(left: dict[str, str], right: dict[str, str]) -> list[str]:
    return sorted(name for name in left if left[name] != right.get(name))


# --- assertions -------------------------------------------------------------


def check_01_cache_equivalence(sample: Path) -> None:
    """A cached artefact and a directly built one carry the same checkpoints."""
    cached = artifacts.get_artifacts(sample, COMPARISON_MODE)
    first = artifacts.build_into(sample, COMPARISON_MODE, _tmp_root / "direct_a")
    second = artifacts.build_into(sample, COMPARISON_MODE, _tmp_root / "direct_b")

    from_cache = canonical_checkpoints(cached.working_dir)
    direct_a = canonical_checkpoints(first.working_dir)
    direct_b = canonical_checkpoints(second.working_dir)
    missing = sorted(set(direct_a) - set(from_cache))
    extra = sorted(set(from_cache) - set(direct_a))
    record(
        "01a cached and directly built checkpoints are equal in canonical form",
        bool(direct_a)
        and not missing
        and not extra
        and not differing(from_cache, direct_a),
        f"sample={sample.name} mode={COMPARISON_MODE} "
        f"checkpoints={len(direct_a)} missing={missing} extra={extra} "
        f"differing={differing(from_cache, direct_a)}",
    )

    # Two direct builds carry the same per-run labels the cache comparison had
    # to normalise, which is what shows the normalisation is not covering for
    # the cache: serving an artefact differs from rebuilding it no more than
    # rebuilding it twice differs from itself.
    raw_a = canonical_checkpoints(first.working_dir, strip_labels=False)
    raw_b = canonical_checkpoints(second.working_dir, strip_labels=False)
    record(
        "01b the normalised difference is the pipeline's own per-run labelling",
        not differing(direct_a, direct_b) and bool(differing(raw_a, raw_b)),
        f"normalised_differences={differing(direct_a, direct_b)} "
        f"raw_differences={differing(raw_a, raw_b)}",
    )


def check_02_fingerprint_sensitivity() -> None:
    """One byte of configuration changes the cache key, and only while set."""
    target = ROOT / "configs" / "page_features.json"
    original = target.read_bytes()
    before = artifacts.workspace_fingerprint(refresh=True)
    try:
        target.write_bytes(original + b"\n")
        mutated = artifacts.workspace_fingerprint(refresh=True)
    finally:
        target.write_bytes(original)
    restored = artifacts.workspace_fingerprint(refresh=True)

    record(
        "02a a one byte configuration edit mints a new workspace fingerprint",
        before != mutated,
        f"before={before[:16]} mutated={mutated[:16]}",
    )
    record(
        "02b restoring the file restores the fingerprint",
        restored == before and target.read_bytes() == original,
        f"restored={restored[:16]}",
    )


def check_03_render_diff_shortcut(baseline: Path) -> None:
    """Identical bytes answer from the hash, with nothing rasterised."""
    out_dir = _tmp_root / "rd_shortcut"
    code = render_diff(baseline, baseline, out_dir)
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    rasters = sorted(path.name for path in out_dir.glob("*.png"))
    record(
        "03a comparing a file with itself exits 0 through the hash shortcut",
        code == 0 and report.get("identical_bytes") is True,
        f"exit={code} identical_bytes={report.get('identical_bytes')}",
    )
    record(
        "03b the shortcut rasterises no page",
        not rasters and report.get("pages") == [],
        f"rasters={rasters} pages={len(report.get('pages', []))}",
    )

    # The shortcut must not swallow the real comparison: a genuinely different
    # pair still goes through the rasteriser.
    trimmed = _tmp_root / "trimmed.pdf"
    with pymupdf.open(baseline) as doc:
        doc.delete_page(0)
        doc.save(trimmed)
    out_dir = _tmp_root / "rd_structural"
    structural = render_diff(baseline, trimmed, out_dir)
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    record(
        "03c a differing pair still takes the rasterising path",
        structural == 2 and report.get("identical_bytes") is False,
        f"exit={structural} identical_bytes={report.get('identical_bytes')}",
    )


def check_04_fast_tier() -> None:
    """The fast tier finishes inside its budget with the static tier green."""
    name = "04 run_all --fast is green inside its budget"
    if NESTED_SUPPRESSED:
        print(f"SKIPPED: nested run suppressed :: {name}")
        return
    started = time.monotonic()
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py"), "--fast"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    seconds = time.monotonic() - started
    skipped = sum(
        1 for line in proc.stdout.splitlines() if line.strip().startswith("SKIPPED:")
    )
    record(
        name,
        proc.returncode == 0 and seconds < FAST_TIER_BUDGET_SECONDS,
        f"exit={proc.returncode} elapsed={seconds:.1f}s "
        f"budget={FAST_TIER_BUDGET_SECONDS}s pipeline_tier_skips={skipped}",
    )


def check_05_full_sweep() -> None:
    """The full sweep is green apart from the assertion the plan expects red."""
    name = "05 the full run_all sweep is green apart from the expected red"
    if NESTED_SUPPRESSED:
        print(f"SKIPPED: nested run suppressed :: {name}")
        return
    started = time.monotonic()
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    seconds = time.monotonic() - started
    # run_all echoes two kinds of [FAIL] line: one per failed assertion, and
    # one per gate in its closing summary. Only the assertion lines say what
    # actually failed, so the gate lines are counted separately; a gate whose
    # sole red is the expected one is not itself an unexpected failure.
    assertion_failures = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith("[FAIL]")
        and not line.strip().split()[1].endswith(".py")
    ]
    gate_failures = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith("[FAIL]") and line.strip().split()[1].endswith(".py")
    ]
    unexpected = [line for line in assertion_failures if EXPECTED_RED not in line]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "run_all.full.log").write_text(proc.stdout, encoding="utf-8")
    record(
        name,
        not unexpected and bool(assertion_failures),
        f"elapsed={seconds:.1f}s expected_red={EXPECTED_RED!r} "
        f"red_assertions={len(assertion_failures)} unexpected={unexpected[:3]} "
        f"gates_reporting_red={[line.split()[1] for line in gate_failures]}",
    )


def check_06_label_bounds(manifest: dict) -> None:
    """A page number past the end of its sample is rejected, not silently missed."""
    known = set(taxonomy_module.load_taxonomy().names())
    pages_by_file = {sample["file"]: sample["pages"] for sample in manifest["samples"]}
    raw = corpus_module.load_page_labels(LABELS_PATH)
    errors = corpus_module.validate_page_labels(
        raw, known, LABELS_PATH.name, pages_by_file
    )
    record(
        "06a the shipped ground truth validates against the page count bound",
        not errors,
        f"errors={errors[:5]}",
    )

    sample_name, total = next(iter(pages_by_file.items()))
    a_type = sorted(known)[0]
    probe = {sample_name: {str(total + 1): [a_type]}}
    rejected = corpus_module.validate_page_labels(probe, known, "probe", pages_by_file)
    unbounded = corpus_module.validate_page_labels(probe, known, "probe")
    record(
        "06b a page number past the end of a sample is rejected",
        bool(rejected) and not unbounded,
        f"page={total + 1} of {sample_name} ({total} pages) "
        f"rejected={rejected} without_bound={unbounded}",
    )


def check_07_fallbacks() -> None:
    """The nesting switch survives, and a gate with no cache builds its own."""
    missing = [
        gate
        for gate in NESTING_GATES
        if "SPEC_NO_NESTED" not in (ROOT / gate).read_text(encoding="utf-8")
    ]
    runner = (ROOT / "spec_checks" / "run_all.py").read_text(encoding="utf-8")
    record(
        "07a the nesting suppression contract is intact",
        not missing and 'env["SPEC_NO_NESTED"] = "1"' in runner,
        f"gates_without_switch={missing}",
    )

    name = "07b a gate with an empty cache still passes by building its own"
    if NESTED_SUPPRESSED:
        print(f"SKIPPED: nested run suppressed :: {name}")
        return
    fresh = _tmp_root / "empty_cache"
    env = dict(os.environ)
    env["SPEC_CACHE_ROOT"] = str(fresh)
    env["SPEC_NO_NESTED"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "spec_checks" / "spec_check_b1.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    built = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith("artifact cache ")
    ]
    record(
        name,
        proc.returncode == 0 and fresh.is_dir(),
        f"exit={proc.returncode} cache_root_created={fresh.is_dir()} {built[-1:]}",
    )


def check_08_assertions_frozen() -> None:
    """No assertion description was rewritten or dropped, only added."""
    lost: list[str] = []
    added = 0
    compared = 0
    for gate in FROZEN_GATES:
        code, previous = git_output(["show", f"{PREVIOUS_TAG}:{gate}"])
        if code != 0:
            lost.append(f"{gate}: not present at {PREVIOUS_TAG}")
            continue
        compared += 1
        before = assertion_names(previous)
        now = assertion_names((ROOT / gate).read_text(encoding="utf-8"))
        lost.extend(f"{gate}: {name!r}" for name in sorted(before - now))
        added += len(now - before)
    record(
        "08 every assertion description from the previous batch survives verbatim",
        not lost and compared == len(FROZEN_GATES),
        f"gates={compared} lost={lost[:5]} newly_added={added}",
    )


def check_09_change_scope() -> None:
    changed = changed_files()
    unexpected = sorted(changed - ALLOWED_CHANGES)
    record(
        "09a this batch changes only the files the plan allows",
        not unexpected,
        f"changed={sorted(changed)} unexpected={unexpected}",
    )
    upstream = sorted(
        path
        for path in changed
        if path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    )
    record(
        "09b this batch touches no upstream file",
        not upstream,
        f"upstream={upstream}",
    )

    cjk: list[str] = []
    checked = 0
    for relative in sorted(ALLOWED_CHANGES):
        path = ROOT / relative
        if not path.exists() or path.suffix not in CJK_SCAN_SUFFIXES:
            continue
        checked += 1
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if has_cjk(line):
                cjk.append(f"{relative}:{number}")
    record(
        "09c no CJK characters in the code this batch changed",
        not cjk and checked > 0,
        f"files={checked} offenders={cjk[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    with _timer.phase("warmup"):
        use_project_cache(ROOT)
        warmup()

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)
    smallest = min(manifest["samples"], key=lambda entry: entry["pages"])
    sample = INPUT_DIR / smallest["file"]
    baseline = ROOT / smallest["baseline"]["pdf"]

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        with _timer.phase(f"pipeline:{COMPARISON_MODE}:{sample.stem}"):
            check_01_cache_equivalence(sample)

    check_02_fingerprint_sensitivity()
    check_03_render_diff_shortcut(baseline)
    check_06_label_bounds(manifest)
    check_08_assertions_frozen()
    check_09_change_scope()
    check_07_fallbacks()
    check_04_fast_tier()
    check_05_full_sweep()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b2_5")
    artifacts.print_stats("spec_check_b2_5")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b2_5: {len(_results) - len(failed)}/{len(_results)} passed")
    for name in failed:
        print(f"  FAILED: {name}")
    shutil.rmtree(_tmp_root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
