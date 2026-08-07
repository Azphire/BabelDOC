"""Gate script for batch B2.2 (document level percentile features, corpus registry).

Run from the repository root:

    python spec_checks/spec_check_b2_2.py

Exit code 0 when every assertion in plans/PLAN_B2_2.md passes, 1 otherwise.
Requires no API key: the pipeline is exercised with skip_translation and
only_parse_generate_pdf. The four earlier gates are re-run as subprocesses, so
this script takes a while.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine import page_features  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402
from babeldoc.magazine.page_classifier import REPORT_NAME  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

PYTHON = sys.executable
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
REGISTRY_PATH = ROOT / "corpus" / "registry.user.json"
INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output" / "b2_2"

# The commit this batch builds on; the raw feature definitions and the page
# type vocabulary must be identical to it.
PREVIOUS_TAG = "batch-b2.1"

# Tag that freezes this batch; once it exists the scope and freeze assertions
# read this batch's own delta instead of the working tree.
BATCH_TAG = "batch-b2.2"

# Files this batch is allowed to change, per PLAN_B2_2 negative assertion 9.
ALLOWED_CHANGES = {
    "CLAUDE.md",
    "babeldoc/magazine/corpus.py",
    "babeldoc/magazine/page_classifier.py",
    "babeldoc/magazine/page_features.py",
    "babeldoc/magazine/taxonomy.py",
    "configs/page_features.json",
    "corpus/manifest.json",
    "corpus/registry.user.json",
    "plans/PLAN_B2_2.md",
    "spec_checks/spec_check_b2_1.py",
    "spec_checks/spec_check_b2_2.py",
    "tools/build_baseline.py",
    "tools/corpus_check.py",
    "tools/corpus_sync.py",
    "tools/page_classify_report.py",
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

# Directories excluded from the "no page type name in code" scan.
TYPE_NAME_SCAN_ROOT = ROOT / "babeldoc"
TYPE_NAME_SCAN_SKIP = {"__pycache__", "tests", "test"}

# Sources that may name the registry; none of them may open it for writing.
REGISTRY_WRITE_SCAN = (ROOT / "babeldoc" / "magazine", ROOT / "tools")
_WRITE_PATTERN = re.compile(r"write_text|write_bytes|\"w\"|'w'|\"wb\"|'wb'")

EARLIER_GATES = (
    "spec_check_b0.py",
    "spec_check_b1.py",
    "spec_check_b2.py",
    "spec_check_b2_1.py",
)

# Set by spec_checks/run_all.py, which runs every gate once in order. The
# nested re-run below is the fallback for running this file on its own; under
# the runner it would repeat work the runner already covers, exponentially so.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Checks that need an artefact built during this run. run_all --fast skips
# them; the validator, corpus, freeze and scope assertions read files that are
# already on disk.
PIPELINE_TIER = (
    "check_01_percentiles",
    "check_02_determinism",
    "check_04_reports",
    "check_06_baselines",
    "check_07_conservation",
    "check_09_raw_features_frozen",
)

CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# Documents whose prose is Chinese by design; the CJK scan covers code only.
CJK_SCAN_SUFFIXES = (".py", ".json")

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b2_2_"))
_timer = harness.Timer("spec_check_b2_2")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


# --- pipeline helpers -------------------------------------------------------


def run_classified(pdf: Path, name: str) -> tuple[Path, Path]:
    """Run every non-translation stage with the classifier on.

    Returns the checkpoint directory and the classifier sidecar report.
    """
    with _timer.phase(f"pipeline:classified:{name}"):
        built = artifacts.get_artifacts(pdf, "classified")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = OUTPUT_DIR / f"{name}.classified"
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True)
    for item in sorted(built.working_dir.glob(f"{CHECKPOINT_PREFIX}*")):
        shutil.copyfile(item, checkpoint_dir / item.name)
    report = OUTPUT_DIR / f"{name}.{REPORT_NAME}"
    shutil.copyfile(built.working_dir / REPORT_NAME, report)
    return checkpoint_dir, report


def run_parse_only(pdf: Path, name: str) -> Path:
    """Dry run with the classifier at its default, for the render diff."""
    with _timer.phase(f"pipeline:parse_only_plain:{name}"):
        built = artifacts.get_artifacts(pdf, "parse_only_plain")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    produced = OUTPUT_DIR / f"{name}.b2_2.pdf"
    shutil.copyfile(built.mono_pdf, produced)
    return produced


def classifier_checkpoint(directory: Path) -> Path:
    stem = checkpoint_module.checkpoint_stem("page_classifier")
    return directory / f"{stem}.xml"


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


def git_show(revision: str, path: str) -> bytes:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", "show", f"{revision}:{path}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def batch_tag_exists() -> bool:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", "rev-parse", "-q", "--verify", f"{BATCH_TAG}^{{commit}}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def current_bytes(path: str) -> bytes:
    """This batch's version of a tracked file.

    Once the batch is tagged that is the tagged content, so a later batch
    editing the same file does not make this gate read its work.
    """
    if batch_tag_exists():
        return git_show(BATCH_TAG, path)
    return (ROOT / path).read_bytes()


def changed_files() -> set[str]:
    """Every path this batch changed.

    Before the batch is committed that is the working tree delta against HEAD.
    Once the batch is tagged the same delta is the tag against its parent, so a
    later batch can re-run this gate without its own changes counting here.
    """
    if batch_tag_exists():
        proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
            ["git", "diff", "--name-only", f"{BATCH_TAG}^", BATCH_TAG],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return {line.strip() for line in proc.stdout.splitlines() if line.strip()}

    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    paths: set[str] = set()
    for line in proc.stdout.splitlines():
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        if entry:
            paths.add(entry.strip('"'))
    return paths


def feature_module_at(revision: str, alias: str) -> ModuleType:
    """Import the feature extractor as it stood at a given revision."""
    path = _tmp_root / f"page_features_{alias}.py"
    path.write_bytes(git_show(revision, "babeldoc/magazine/page_features.py"))
    spec = importlib.util.spec_from_file_location(f"page_features_{alias}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def previous_feature_module() -> ModuleType:
    return feature_module_at(PREVIOUS_TAG, "previous")


def current_feature_module() -> ModuleType:
    """The feature extractor this batch delivered.

    Read from the tag once it exists, so a later batch editing the extractor
    is compared against its own baseline rather than against this one.
    """
    if batch_tag_exists():
        return feature_module_at(BATCH_TAG, "batch")
    return page_features


def synthetic_document(page_count: int) -> il_version_1.Document:
    """A document of bare pages, used to pin down the midrank edge cases."""
    pages = [
        il_version_1.Page(
            page_number=index,
            cropbox=il_version_1.Cropbox(
                box=il_version_1.Box(x=0.0, y=0.0, x2=100.0, y2=100.0)
            ),
            mediabox=il_version_1.Mediabox(
                box=il_version_1.Box(x=0.0, y=0.0, x2=100.0, y2=100.0)
            ),
            page_layout=[],
        )
        for index in range(page_count)
    ]
    return il_version_1.Document(page=pages, total_pages=page_count)


# --- assertions -------------------------------------------------------------


def check_01_percentiles(classified: dict[str, Path]) -> None:
    """Every percentile key is present, open ranged and discriminating."""
    config = page_features.load_feature_config()
    expected_keys = set(page_features.percentile_feature_names(config))
    missing: list[str] = []
    out_of_range: list[str] = []
    raw_drift: list[str] = []
    discriminating: set[str] = set()
    pages_checked = 0
    for name, directory in classified.items():
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        vectors = page_features.extract_document_features(docs, config)
        for page, vector in zip(docs.page, vectors, strict=True):
            pages_checked += 1
            absent = sorted(expected_keys - set(vector))
            if absent:
                missing.append(f"{name}#{page.page_number}: {absent}")
            for key in expected_keys & set(vector):
                value = vector[key]
                if not 0.0 < value < 1.0:
                    out_of_range.append(f"{name}#{page.page_number}:{key}={value}")
                if value != 0.5:
                    discriminating.add(f"{name}:{key}")
            raw = page_features.extract_page_features(page, docs, config)
            if any(vector[key] != value for key, value in raw.items()):
                raw_drift.append(f"{name}#{page.page_number}")
            if set(raw) != set(page_features.FEATURE_NAMES):
                raw_drift.append(f"{name}#{page.page_number}: raw key set")
    record(
        "01a every page carries every percentile key inside the open range 0..1",
        not missing and not out_of_range and pages_checked > 0,
        f"pages={pages_checked} missing={missing[:3]} out_of_range={out_of_range[:3]}",
    )
    record(
        "01b the raw keys of a document level vector equal the per page ones",
        not raw_drift,
        f"drift={raw_drift[:3]}",
    )
    record(
        "01c percentiles discriminate on the live corpus",
        bool(discriminating),
        f"features_with_spread={len(discriminating)}",
    )

    # Midrank edge cases, asserted through the public entry point.
    single = page_features.extract_document_features(synthetic_document(1), config)
    single_wrong = {
        key: value
        for key, value in single[0].items()
        if key in expected_keys and value != 0.5
    }
    record(
        "01d a single page document sits at 0.5 on every percentile",
        not single_wrong and len(single) == 1,
        f"offenders={single_wrong}",
    )
    constant = page_features.extract_document_features(synthetic_document(5), config)
    constant_wrong = [
        f"page{index}:{key}={value}"
        for index, vector in enumerate(constant)
        for key, value in vector.items()
        if key in expected_keys and value != 0.5
    ]
    record(
        "01e a feature that is constant across a document sits at 0.5 everywhere",
        not constant_wrong and len(constant) == 5,
        f"offenders={constant_wrong[:3]}",
    )


def check_02_determinism(classified: dict[str, Path]) -> None:
    config = page_features.load_feature_config()
    unstable: list[str] = []
    for name, directory in classified.items():
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        first = page_features.extract_document_features(docs, config)
        second = page_features.extract_document_features(docs, config)
        if [sorted(v.items()) for v in first] != [sorted(v.items()) for v in second]:
            unstable.append(name)
    record(
        "02 the document level extractor is deterministic",
        not unstable and bool(classified),
        f"samples={len(classified)} unstable={unstable}",
    )


def check_03_validator() -> None:
    valid = json.loads((ROOT / "configs" / "page_types.json").read_text("utf-8"))
    config = page_features.load_feature_config()
    legal = page_features.percentile_feature_names(config)[0]
    raw_without_percentile = next(
        name
        for name in page_features.FEATURE_NAMES
        if name not in config["percentile_features"]
    )

    def with_rule(feature: str) -> dict:
        mutated = json.loads(json.dumps(valid))
        # Above the midrank a constant feature column lands on: positive
        # evidence on a percentile at or below it is refused for a reason of
        # its own, and this probe is about the feature name being resolvable.
        mutated["page_types"][0]["rules"].append(
            {"feature": feature, "op": "ge", "threshold": 0.55, "weight": 1.0}
        )
        return mutated

    try:
        taxonomy_module.parse_taxonomy(with_rule(legal), "legal")
        accepted, reason = True, ""
    except taxonomy_module.TaxonomyError as exc:
        accepted, reason = False, str(exc)
    record(
        "03a the validator accepts a percentile reference from the configured list",
        accepted,
        f"feature={legal} reason={reason}",
    )

    survived: list[str] = []
    for feature in (
        f"{raw_without_percentile}{page_features.PERCENTILE_SUFFIX}",
        f"not_a_feature{page_features.PERCENTILE_SUFFIX}",
        "not_a_feature",
    ):
        try:
            taxonomy_module.parse_taxonomy(with_rule(feature), "illegal")
        except taxonomy_module.TaxonomyError:
            continue
        survived.append(feature)
    record(
        "03b the validator rejects a percentile of an unlisted or unknown feature",
        not survived,
        f"unlisted={raw_without_percentile} survived={survived}",
    )


def check_04_reports(classified: dict[str, Path], reports: dict[str, Path]) -> None:
    """Sidecar and HTML review page both show raw and percentile columns."""
    config = page_features.load_feature_config()
    percentile_names = list(page_features.percentile_feature_names(config))
    problems: list[str] = []
    pages_checked = 0
    for name, report_path in reports.items():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        docs = checkpoint_module.load_checkpoint(
            classifier_checkpoint(classified[name])
        )
        vectors = page_features.extract_document_features(docs, config)
        if len(report["pages"]) != len(vectors):
            problems.append(
                f"{name}: {len(report['pages'])} records for {len(vectors)}"
            )
            continue
        for record_entry, vector in zip(report["pages"], vectors, strict=True):
            pages_checked += 1
            # The sidecar is written with sorted keys, so only the key set is
            # meaningful here; the order lives in FEATURE_NAMES.
            if sorted(record_entry.get("features", {})) != sorted(
                page_features.FEATURE_NAMES
            ):
                problems.append(f"{name}#{record_entry['page_number']}: raw column")
            if sorted(record_entry.get("features_pctl", {})) != sorted(
                percentile_names
            ):
                problems.append(f"{name}#{record_entry['page_number']}: pctl column")
                continue
            merged = dict(record_entry["features"]) | dict(
                record_entry["features_pctl"]
            )
            if merged != vector:
                problems.append(f"{name}#{record_entry['page_number']}: value drift")
    record(
        "04a the classifier sidecar reports raw and percentile columns",
        not problems and pages_checked > 0,
        f"pages={pages_checked} problems={problems[:3]}",
    )

    sample = sorted(reports)[0]
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [
            PYTHON,
            str(ROOT / "tools" / "page_classify_report.py"),
            str(INPUT_DIR / f"{sample}.pdf"),
            "--checkpoint",
            str(classifier_checkpoint(classified[sample])),
            "--out",
            str(OUTPUT_DIR),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    html_path = OUTPUT_DIR / f"{sample}.classify.html"
    text = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    header = "<th>feature</th><th>raw</th><th>pctl</th>" in text
    record(
        "04b the HTML review page carries a raw and a pctl column",
        proc.returncode == 0 and header,
        f"exit={proc.returncode} header={header} path={html_path.name}",
    )


def check_05_corpus(manifest: dict) -> None:
    """Registry, manifest and sample files agree in all three directions."""
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "tools" / "corpus_check.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    grouped = "publications:" in proc.stdout
    record(
        "05a corpus_check passes and prints the per publication breakdown",
        proc.returncode == 0 and grouped,
        f"exit={proc.returncode} grouped={grouped}",
    )

    entries = corpus_module.load_registry(REGISTRY_PATH)
    by_file = {entry["file"]: entry for entry in entries}
    semantic_drift: list[str] = []
    mechanical_drift: list[str] = []
    for sample in manifest["samples"]:
        entry = by_file.get(sample["file"])
        if entry is None:
            semantic_drift.append(f"{sample['file']}: not registered")
            continue
        for field in corpus_module.SEMANTIC_FIELDS:
            if sample.get(field) != entry.get(field):
                semantic_drift.append(f"{sample['file']}:{field}")
        path = INPUT_DIR / sample["file"]
        if corpus_module.sha256_file(path) != sample["sha256"]:
            mechanical_drift.append(f"{sample['file']}: sha256")
        if corpus_module.page_count(path) != sample["pages"]:
            mechanical_drift.append(f"{sample['file']}: pages")
    unregistered = sorted(set(corpus_module.registered_pdfs()) - set(by_file))
    record(
        "05b every manifest semantic field is a verbatim registry copy",
        not semantic_drift and len(manifest["samples"]) == len(entries),
        f"samples={len(manifest['samples'])} drift={semantic_drift[:3]}",
    )
    record(
        "05c the mechanical fields match the sample files and none is unregistered",
        not mechanical_drift and not unregistered,
        f"drift={mechanical_drift[:3]} unregistered={unregistered}",
    )

    # An unregistered sample, a bad role and a missing publication are errors.
    rejected: dict[str, bool] = {}
    broken_registry = {
        "unregistered sample": lambda data: data["entries"].pop(),
        "unknown corpus_role": lambda data: data["entries"][0].update(
            {"corpus_role": ["not_a_role"]}
        ),
        "missing publication": lambda data: data["entries"][0].pop("publication"),
    }
    for label, mutate in broken_registry.items():
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        mutate(data)
        path = _tmp_root / f"registry_{label.replace(' ', '_')}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        broken = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
            [
                PYTHON,
                str(ROOT / "tools" / "corpus_check.py"),
                "--registry",
                str(path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        rejected[label] = broken.returncode != 0
    record(
        "05d corpus_check errors on an unregistered sample and on a bad field",
        all(rejected.values()),
        f"rejected={rejected}",
    )

    sync = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "tools" / "corpus_sync.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    record(
        "05e the manifest on disk equals a fresh rebuild from the registry",
        sync.returncode == 0,
        f"exit={sync.returncode} {sync.stdout.strip().splitlines()[-1:]}",
    )


def check_06_baselines(manifest: dict, produced_pdfs: dict[str, Path]) -> None:
    """End to end: every sample has a baseline and still renders identically."""
    missing: list[str] = []
    for entry in manifest["samples"]:
        baseline = entry.get("baseline")
        if not baseline:
            missing.append(f"{entry['file']}: no baseline")
            continue
        pdf = ROOT / baseline["pdf"]
        if not pdf.exists():
            missing.append(f"{entry['file']}: {baseline['pdf']} absent")
        elif corpus_module.sha256_file(pdf) != baseline["sha256"]:
            missing.append(f"{entry['file']}: baseline sha256")
        if not (ROOT / baseline["checkpoints"]).is_dir():
            missing.append(f"{entry['file']}: checkpoints absent")
    record(
        "06a every sample carries a built baseline with the recorded hash",
        not missing and bool(manifest["samples"]),
        f"samples={len(manifest['samples'])} problems={missing[:3]}",
    )

    for entry in manifest["samples"]:
        name = Path(entry["file"]).stem
        baseline = ROOT / entry["baseline"]["pdf"]
        code = render_diff(baseline, produced_pdfs[name], _tmp_root / f"rd_{name}")
        record(
            f"06b dry run still renders identically to the baseline ({name})",
            code == 0,
            f"exit={code}",
        )


def check_07_conservation(manifest: dict, classified: dict[str, Path]) -> None:
    """Page and paragraph counts survive the classifier stage."""
    problems: list[str] = []
    totals: list[str] = []
    pages_by_file = {
        Path(entry["file"]).stem: entry["pages"] for entry in manifest["samples"]
    }
    for name, directory in classified.items():
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        stem = checkpoint_module.checkpoint_stem("styles_and_formulas")
        before = checkpoint_module.load_checkpoint(directory / f"{stem}.xml")
        pages = len(docs.page)
        paragraphs = sum(len(page.pdf_paragraph) for page in docs.page)
        before_paragraphs = sum(len(page.pdf_paragraph) for page in before.page)
        totals.append(f"{name}: {pages}p/{paragraphs}par")
        if pages != pages_by_file[name]:
            problems.append(
                f"{name}: {pages} pages, manifest says {pages_by_file[name]}"
            )
        if len(before.page) != pages or before_paragraphs != paragraphs:
            problems.append(
                f"{name}: {before_paragraphs} paragraphs before, {paragraphs} after"
            )
    record(
        "07 the classifier stage conserves page and paragraph counts",
        not problems and bool(classified),
        f"{totals} problems={problems[:3]}",
    )


def check_08_frozen_thresholds() -> None:
    """The vocabulary and every pre-existing threshold are untouched."""
    current = current_bytes("configs/page_types.json")
    previous = git_show(PREVIOUS_TAG, "configs/page_types.json")
    record(
        "08a configs/page_types.json is byte identical to the previous batch",
        current.replace(b"\r\n", b"\n") == previous.replace(b"\r\n", b"\n"),
        f"bytes now={len(current)} then={len(previous)}",
    )

    old = json.loads(git_show(PREVIOUS_TAG, "configs/page_features.json"))
    new = json.loads(current_bytes("configs/page_features.json"))
    changed = [
        key
        for key, value in old.items()
        if key != "description" and new.get(key) != value
    ]
    added = sorted(set(new) - set(old))
    record(
        "08b no pre-existing feature parameter or allowed range changed value",
        not changed and added == ["percentile_features"],
        f"changed={changed} added={added}",
    )


def check_09_raw_features_frozen(classified: dict[str, Path]) -> None:
    """Raw per page features are bit identical to the previous batch."""
    previous = previous_feature_module()
    current = current_feature_module()
    old_config = previous.load_feature_config(
        str(ROOT / "configs" / "page_features.json")
    )
    new_config = current.load_feature_config(
        str(ROOT / "configs" / "page_features.json")
    )
    drift: list[str] = []
    pages_checked = 0
    for name, directory in classified.items():
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        for page in docs.page:
            pages_checked += 1
            before = previous.extract_page_features(page, docs, old_config)
            after = current.extract_page_features(page, docs, new_config)
            if sorted(before.items()) != sorted(after.items()):
                differing = sorted(
                    key for key in before if before[key] != after.get(key)
                )
                drift.append(f"{name}#{page.page_number}: {differing}")
    record(
        f"09 raw features are bit identical to {PREVIOUS_TAG}",
        not drift and pages_checked > 0,
        f"pages={pages_checked} drift={drift[:3]}",
    )


def check_10_change_scope() -> None:
    changed = changed_files()
    unexpected = sorted(changed - ALLOWED_CHANGES)
    record(
        "10a this batch changes only the files the plan allows",
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
        "10b this batch touches no upstream file",
        not upstream,
        f"upstream={upstream}",
    )

    writers: list[str] = []
    scanned = 0
    for directory in REGISTRY_WRITE_SCAN:
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            scanned += 1
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "REGISTRY_PATH" in line and _WRITE_PATTERN.search(line):
                    writers.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    record(
        "10c no code opens the user owned registry for writing",
        not writers and scanned > 0,
        f"files={scanned} writers={writers}",
    )


def check_11_no_type_names_and_no_cjk() -> None:
    vocabulary = taxonomy_module.load_taxonomy()
    names = vocabulary.names()
    patterns = {
        name: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        for name in names
    }
    offenders: list[str] = []
    scanned = 0
    for path in sorted(TYPE_NAME_SCAN_ROOT.rglob("*.py")):
        if set(path.relative_to(ROOT).parts) & TYPE_NAME_SCAN_SKIP:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders.extend(
            f"{path.relative_to(ROOT).as_posix()}: {name}"
            for name, pattern in patterns.items()
            if pattern.search(text)
        )
    record(
        "11a no page type name appears anywhere under babeldoc/",
        not offenders and scanned > 0,
        f"types={len(names)} files={scanned} offenders={offenders[:5]}",
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
        "11b no CJK characters in the code and configuration this batch changed",
        not cjk and checked > 0,
        f"files={checked} offenders={cjk[:5]}",
    )


def check_12_earlier_gates() -> None:
    if NESTED_SUPPRESSED:
        print("SKIPPED: nested run suppressed")
        return
    for gate in EARLIER_GATES:
        proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
            [PYTHON, str(ROOT / "spec_checks" / gate)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        summary = [
            line
            for line in proc.stdout.splitlines()
            if line.startswith(gate.replace(".py", ""))
        ]
        failures = [
            line for line in proc.stdout.splitlines() if line.startswith("[FAIL")
        ]
        record(
            f"12 {gate} still passes on the new corpus",
            proc.returncode == 0,
            f"exit={proc.returncode} {summary[-1] if summary else ''} "
            f"failures={failures[:3]}",
        )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    with _timer.phase("warmup"):
        use_project_cache(ROOT)
        warmup()

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        classified: dict[str, Path] = {}
        reports: dict[str, Path] = {}
        produced_pdfs: dict[str, Path] = {}
        for entry in manifest["samples"]:
            name = Path(entry["file"]).stem
            pdf = INPUT_DIR / entry["file"]
            classified[name], reports[name] = run_classified(pdf, name)
            produced_pdfs[name] = run_parse_only(pdf, name)

        check_01_percentiles(classified)
        check_02_determinism(classified)
        check_04_reports(classified, reports)
        check_06_baselines(manifest, produced_pdfs)
        check_07_conservation(manifest, classified)
        check_09_raw_features_frozen(classified)

    check_03_validator()
    check_05_corpus(manifest)
    check_08_frozen_thresholds()
    check_10_change_scope()
    check_11_no_type_names_and_no_cjk()
    check_12_earlier_gates()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b2_2")
    artifacts.print_stats("spec_check_b2_2")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b2_2: {len(_results) - len(failed)}/{len(_results)} passed")
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
