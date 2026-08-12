"""Gate script for batch B0 (infrastructure: checkpoints, corpus, render diff, cache).

Run from the repository root:

    python spec_checks/spec_check_b0.py

Exit code 0 when every assertion in plans/PLAN_B0.md passes, 1 otherwise.
Requires no API key: the pipeline is exercised with skip_translation and
only_parse_generate_pdf.
"""

from __future__ import annotations

import json
import logging
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
from babeldoc.magazine import cache_setup  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

PYTHON = sys.executable
# Tag that freezes this batch; once it exists the scope assertions read the
# delta it introduced instead of the working tree.
BATCH_TAG = "batch-b0"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
INPUT_DIR = ROOT / "examples" / "input"
UPSTREAM_DIFF = ROOT / "UPSTREAM_DIFF.md"

# Upstream source files this batch is allowed to modify (PLAN_B0 negative
# assertion 8). Non-Python upstream files are allow-listed separately because
# T0.3 mandates the .gitignore entries for examples/output and examples/cache.
ALLOWED_UPSTREAM_PY = {
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/format/pdf/translation_config.py",
    "babeldoc/translator/cache.py",
}
ALLOWED_UPSTREAM_OTHER = {".gitignore"}

# Trees and root documents owned by the magazine extension. The upstream scope
# assertions ignore them: the allow lists above describe upstream files only,
# and later batches keep these project paths dirty.
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

# Project-owned trees whose files must be free of non-ASCII comments. The
# corpus tree is not among them: its files are adjudications of documents rather
# than prose about code, and a Chinese edition in the corpus is adjudicated by
# quoting the Chinese it splits. What governs those files is their validators
# and their ownership.
NEW_CODE_GLOBS = (
    "babeldoc/magazine/*.py",
    "tools/*.py",
    "spec_checks/*.py",
    "configs/*.json",
)

# CJK / fullwidth / CJK-punctuation ranges, kept as code points so that this
# gate script stays pure ASCII itself.
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


# Checks that need an artefact built during this run. run_all --fast skips
# them; everything else here reads source, git, configuration or a corpus
# fixture that is already on disk.
PIPELINE_TIER = (
    "check_02_03_checkpoints",
    "check_06_default_off",
    "check_07_baseline_render",
)

# Row count used to prove that eviction is disabled; MAX_CACHE_ROWS + 1.
CLEANUP_PROBE_ROWS = 50_001
# Engine name for the cache probe rows; must stay within the 20 char column.
PROBE_ENGINE = "b0-cache-probe"

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b0_"))
_timer = harness.Timer("spec_check_b0")


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


def run_checkpoint_pipeline(pdf: Path, tag: str, enable_checkpoint: bool) -> Path:
    """Run every non-translation stage over ``pdf`` and return the working dir."""
    mode = "stages" if enable_checkpoint else "stages_plain"
    with _timer.phase(f"pipeline:{mode}:{tag}"):
        return artifacts.get_artifacts(pdf, mode).working_dir


def run_parse_only(pdf: Path, tag: str) -> Path:
    """Dry run with only_parse_generate_pdf and return the produced mono PDF."""
    with _timer.phase(f"pipeline:parse_only:{tag}"):
        return artifacts.get_artifacts(pdf, "parse_only").mono_pdf


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


def check_01_module_api() -> None:
    ok = callable(checkpoint_module.dump_checkpoint) and callable(
        checkpoint_module.load_checkpoint
    )
    record(
        "01 checkpoint.py exposes dump_checkpoint/load_checkpoint",
        ok,
        str(Path(checkpoint_module.__file__).relative_to(ROOT)),
    )


def check_02_03_checkpoints(work_dir: Path) -> None:
    xmls = sorted(work_dir.glob("checkpoint.*.xml"))
    ordinals = [int(p.name.split(".")[1].split("_")[0]) for p in xmls]
    strictly_increasing = all(
        a < b for a, b in zip(ordinals, ordinals[1:], strict=False)
    )
    record(
        "02 checkpoint XML count >= 5 with strictly increasing ordinals",
        len(xmls) >= 5 and strictly_increasing,
        f"{len(xmls)} files, ordinals={ordinals}",
    )
    if not xmls:
        record("03 checkpoint round trip", False, "no checkpoint to load")
        return

    target = xmls[-1]
    docs = checkpoint_module.load_checkpoint(target)
    pages_ok = docs.total_pages == len(docs.page)

    # Serialised through the checkpoint layer rather than the bare converter:
    # the canonical form of a checkpoint is the form that layer writes, and a
    # document holding a codepoint XML cannot carry has no bare form at all.
    first_xml = checkpoint_module.to_checkpoint_xml(docs)
    rewritten = _tmp_root / "rewritten.xml"
    with rewritten.open("w", encoding="utf-8") as f:
        f.write(first_xml)
    second_xml = checkpoint_module.to_checkpoint_xml(
        checkpoint_module.load_checkpoint(rewritten)
    )
    record(
        "03 load_checkpoint round trip is idempotent",
        pages_ok and first_xml == second_xml,
        f"{target.name}: total_pages={docs.total_pages} pages={len(docs.page)} "
        f"xml_equal={first_xml == second_xml}",
    )


def check_04_render_diff(baseline_pdf: Path) -> None:
    same = render_diff(baseline_pdf, baseline_pdf, _tmp_root / "rd_same")
    record("04a render_diff self comparison exits 0", same == 0, f"exit={same}")

    trimmed = _tmp_root / "trimmed.pdf"
    with pymupdf.open(baseline_pdf) as doc:
        doc.delete_page(0)
        doc.save(trimmed)
    structural = render_diff(baseline_pdf, trimmed, _tmp_root / "rd_trimmed")
    record(
        "04b render_diff page-count mismatch exits 2",
        structural == 2,
        f"exit={structural}",
    )


def check_05_corpus() -> None:
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "tools" / "corpus_check.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    record(
        "05 corpus_check passes",
        proc.returncode == 0,
        proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "",
    )


def check_06_default_off(work_dir: Path) -> None:
    leftovers = sorted(p.name for p in work_dir.glob("checkpoint.*"))
    record(
        "06 magazine_checkpoint default False writes no checkpoint files",
        not leftovers,
        f"found={leftovers}",
    )


def check_07_baseline_render(manifest: dict) -> None:
    for entry in manifest["samples"]:
        name = Path(entry["file"]).stem
        baseline = ROOT / entry["baseline"]["pdf"]
        produced = run_parse_only(INPUT_DIR / entry["file"], f"parse_only_{name}")
        code = render_diff(baseline, produced, _tmp_root / f"rd_baseline_{name}")
        record(
            f"07 dry run matches baseline render ({entry['file']})",
            code == 0,
            f"exit={code}",
        )


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def batch_revisions() -> list[str]:
    """Revision arguments selecting the delta this batch introduced.

    Once the batch is tagged that is the tag against its parent, so a later
    batch can re-run this gate without its own changes counting here. Before
    the tag exists it is the working tree against HEAD.
    """
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{BATCH_TAG}^{{commit}}"])
    return [f"{BATCH_TAG}^", BATCH_TAG] if code == 0 else ["HEAD"]


def changed_upstream_files() -> set[str]:
    """Upstream paths this batch changed."""
    _, listing = git_output(["diff", "--name-only", *batch_revisions()])
    return {
        path
        for path in (line.strip() for line in listing.splitlines())
        if path
        and path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    }


def check_08_upstream_scope() -> None:
    changed = changed_upstream_files()
    changed_py = {p for p in changed if p.endswith(".py")}
    changed_other = changed - changed_py
    record(
        "08a modified upstream python files within allowed set",
        changed_py <= ALLOWED_UPSTREAM_PY,
        f"changed={sorted(changed_py)}",
    )
    record(
        "08b modified upstream non-python files within allowed set",
        changed_other <= ALLOWED_UPSTREAM_OTHER,
        f"changed={sorted(changed_other)}",
    )

    registry = UPSTREAM_DIFF.read_text(encoding="utf-8")
    unregistered = sorted(p for p in changed_py if p not in registry)
    record(
        "08c every modified upstream python file registered in UPSTREAM_DIFF.md",
        not unregistered,
        f"unregistered={unregistered}",
    )

    from babeldoc.const import CACHE_FOLDER
    from babeldoc.translator import cache as cache_module

    cache_module.init_db()
    default_path_ok = Path(cache_module.db.database) == CACHE_FOLDER / "cache.v1.db"
    cleanup_ok = cache_module._cleanup_enabled is True
    record(
        "08d init_db() with no arguments keeps upstream defaults",
        default_path_ok and cleanup_ok,
        f"path={cache_module.db.database} cleanup_enabled={cache_module._cleanup_enabled}",
    )


def check_09_ascii_comments() -> None:
    offenders: list[str] = []
    for pattern in NEW_CODE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if has_cjk(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")

    _, diff = git_output(
        ["diff", "-U0", *batch_revisions(), "--", *sorted(ALLOWED_UPSTREAM_PY)]
    )
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            if has_cjk(line):
                offenders.append(f"added upstream line: {line.strip()}")

    record(
        "09 no CJK characters in new or added code",
        not offenders,
        f"offenders={offenders[:5]}",
    )


def check_10_cache() -> None:
    from babeldoc.translator import cache as cache_module
    from babeldoc.translator.translator import BaseTranslator

    class StubTranslator(BaseTranslator):
        name = "b0-stub"

        def __init__(self):
            super().__init__("en", "zh", ignore_cache=False)
            self.calls = 0

        def do_translate(self, text, rate_limit_params: dict = None):
            self.calls += 1
            return f"translated::{text}"

        def do_llm_translate(self, text, rate_limit_params: dict = None):
            raise NotImplementedError

    db_path = cache_setup.use_project_cache(ROOT)
    record(
        "10a use_project_cache redirects the database",
        Path(cache_module.db.database) == db_path
        and db_path == ROOT / "examples" / "cache" / "cache.v1.db",
        str(db_path),
    )

    global_db = Path(cache_module.CACHE_FOLDER) / "cache.v1.db"
    global_mtime = global_db.stat().st_mtime if global_db.exists() else None

    marker = f"b0 cache probe {time.time_ns()}"
    stub = StubTranslator()
    first = stub.translate(marker)
    calls_after_first = stub.calls
    second = stub.translate(marker)
    record(
        "10b second translate is served from cache",
        calls_after_first == 1 and stub.calls == 1 and first == second,
        f"calls={stub.calls} first==second={first == second}",
    )
    record("10c project cache database file exists", db_path.exists(), str(db_path))

    model = cache_module._TranslationCache
    model.delete().where(model.translate_engine == PROBE_ENGINE).execute()
    rows = [
        {
            "translate_engine": PROBE_ENGINE,
            "translate_engine_params": "{}",
            "original_text": f"probe-{index}",
            "translation": f"value-{index}",
        }
        for index in range(CLEANUP_PROBE_ROWS)
    ]
    with cache_module.db.atomic():
        for start in range(0, len(rows), 5000):
            model.insert_many(rows[start : start + 5000]).execute()
    before = model.select().count()
    cache_module.TranslationCache(PROBE_ENGINE)._cleanup()
    after = model.select().count()
    record(
        "10d row eviction disabled for the project cache",
        after >= before and before >= CLEANUP_PROBE_ROWS,
        f"rows before={before} after={after}",
    )
    model.delete().where(model.translate_engine == PROBE_ENGINE).execute()

    if global_mtime is None:
        record("10e global cache database untouched", True, "global database absent")
    else:
        record(
            "10e global cache database untouched",
            global_db.stat().st_mtime == global_mtime,
            f"mtime {global_mtime} -> {global_db.stat().st_mtime}",
        )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    with _timer.phase("warmup"):
        warmup()

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)
    sample = manifest["samples"][-1]
    sample_pdf = INPUT_DIR / sample["file"]
    baseline_pdf = ROOT / sample["baseline"]["pdf"]

    check_01_module_api()

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        check_02_03_checkpoints(run_checkpoint_pipeline(sample_pdf, "ckpt_on", True))
        check_06_default_off(run_checkpoint_pipeline(sample_pdf, "ckpt_off", False))
        check_07_baseline_render(manifest)

    check_04_render_diff(baseline_pdf)
    check_05_corpus()
    check_08_upstream_scope()
    check_09_ascii_comments()
    check_10_cache()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b0")
    artifacts.print_stats("spec_check_b0")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b0: {len(_results) - len(failed)}/{len(_results)} passed")
    if failed:
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
