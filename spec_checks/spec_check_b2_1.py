"""Gate script for batch B2.1 (feature definition repairs, penalty scoring).

Run from the repository root:

    python spec_checks/spec_check_b2_1.py

Exit code 0 when every assertion in plans/PLAN_B2_1.md passes, 1 otherwise.
Requires no API key: the pipeline is exercised with skip_translation and
only_parse_generate_pdf. The three earlier gates are re-run as subprocesses, so
this script takes a while.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.docvision.doclayout import DocLayoutModel  # noqa: E402
from babeldoc.format.pdf import high_level  # noqa: E402
from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.format.pdf.translation_config import WatermarkOutputMode  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import page_features  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402

PYTHON = sys.executable
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output" / "b2_1"

# Page level IL attributes that must stay unset while the switch is off.
PAGE_ATTRIBUTES = ("pageKind", "pageKindConf", "pageKindSource")

# Files this batch is allowed to change, per PLAN_B2_1 negative assertion 7.
# The gate script itself is on the list because the plan requires it as a
# deliverable. Report artefacts live under examples/, which git ignores.
ALLOWED_CHANGES = {
    "babeldoc/magazine/page_features.py",
    "babeldoc/magazine/taxonomy.py",
    "configs/page_features.json",
    "configs/page_types.json",
    "spec_checks/spec_check_b1.py",
    "spec_checks/spec_check_b2_1.py",
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

# Marker that flags a corpus sample as a magazine, per its manifest notes.
MAGAZINE_NOTE_MARKER = "magazine"

# Directories excluded from the "no page type name in code" scan.
TYPE_NAME_SCAN_ROOT = ROOT / "babeldoc"
TYPE_NAME_SCAN_SKIP = {"__pycache__", "tests", "test"}

EARLIER_GATES = ("spec_check_b0.py", "spec_check_b1.py", "spec_check_b2.py")

CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b2_1_"))


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def record(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


# --- pipeline helpers -------------------------------------------------------


def run_all_stages(pdf: Path, name: str, classify: bool) -> Path:
    """Run every non-translation stage; return the checkpoint directory."""
    stage_dir = _tmp_root / f"stages_{name}_{int(classify)}"
    config = TranslationConfig(
        translator=None,
        input_file=pdf,
        lang_in="en",
        lang_out="zh",
        doc_layout_model=DocLayoutModel.load_onnx(),
        output_dir=stage_dir / "out",
        working_dir=stage_dir / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=False,
        skip_translation=True,
        magazine_checkpoint=True,
        magazine_page_classify=classify,
    )
    high_level.translate(config)
    suffix = "classified" if classify else "stages"
    checkpoint_dir = OUTPUT_DIR / f"{name}.{suffix}"
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True)
    for item in sorted(Path(config.working_dir).glob(f"{CHECKPOINT_PREFIX}*")):
        shutil.copyfile(item, checkpoint_dir / item.name)
    return checkpoint_dir


def run_parse_only(pdf: Path, name: str) -> tuple[Path, Path]:
    """Dry run with the classifier left at its default, for the render diff."""
    stage_dir = _tmp_root / f"parse_only_{name}"
    config = TranslationConfig(
        translator=None,
        input_file=pdf,
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        output_dir=stage_dir / "out",
        working_dir=stage_dir / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=False,
        only_parse_generate_pdf=True,
        magazine_checkpoint=True,
    )
    result = high_level.translate(config)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    produced_pdf = OUTPUT_DIR / f"{name}.b2_1.pdf"
    shutil.copyfile(result.mono_pdf_path, produced_pdf)
    checkpoint_dir = OUTPUT_DIR / f"{name}.checkpoints"
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True)
    for item in sorted(Path(config.working_dir).glob(f"{CHECKPOINT_PREFIX}*")):
        shutil.copyfile(item, checkpoint_dir / item.name)
    return produced_pdf, checkpoint_dir


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


def changed_files() -> set[str]:
    """Every path in the working tree delta against HEAD."""
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


def image_pages(pdf: Path) -> dict[int, int]:
    """Number of raster images each page of a PDF carries, by 0-based index."""
    with pymupdf.open(pdf) as doc:
        return {
            index: len(page.get_images(full=True)) for index, page in enumerate(doc)
        }


# --- assertions -------------------------------------------------------------


def check_01_image_area(manifest: dict, classified: dict[str, Path]) -> None:
    """Magazine pages carrying artwork score above zero, bare pages score zero."""
    feature_config = page_features.load_feature_config()
    mismatches: list[str] = []
    pages_checked = 0
    positives = 0
    samples = 0
    for entry in manifest["samples"]:
        if MAGAZINE_NOTE_MARKER not in entry.get("notes", ""):
            continue
        samples += 1
        name = Path(entry["file"]).stem
        truth = image_pages(INPUT_DIR / entry["file"])
        docs = checkpoint_module.load_checkpoint(
            classifier_checkpoint(classified[name])
        )
        for page in docs.page:
            pages_checked += 1
            ratio = page_features.extract_page_features(page, docs, feature_config)[
                "image_area_ratio"
            ]
            expected = truth.get(page.page_number, 0) > 0
            if expected:
                positives += 1
            if (ratio > 0.0) != expected:
                mismatches.append(
                    f"{name}#{page.page_number}: ratio={ratio:.3f} "
                    f"images={truth.get(page.page_number, 0)}"
                )
    record(
        "01 image_area_ratio is positive exactly on the pages that carry artwork",
        not mismatches and samples > 0 and positives > 0,
        f"samples={samples} pages={pages_checked} with_artwork={positives} "
        f"mismatches={mismatches}",
    )


def check_02_columns(classified: dict[str, Path]) -> None:
    """The column estimate must discriminate, not sit at its ceiling."""
    feature_config = page_features.load_feature_config()
    ceiling = float(int(feature_config["column_count_max"]))
    observed: list[float] = []
    discriminating: list[str] = []
    for name, directory in classified.items():
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        for page in docs.page:
            value = page_features.extract_page_features(page, docs, feature_config)[
                "column_count_estimate"
            ]
            observed.append(value)
            if 0.0 < value < ceiling:
                discriminating.append(f"{name}#{page.page_number}={value:.0f}")
    record(
        "02 the column estimate is no longer pinned at its ceiling",
        bool(discriminating),
        f"ceiling={ceiling:.0f} below_ceiling={discriminating} "
        f"distribution={sorted(observed)}",
    )


def check_03_last_page(classified: dict[str, Path]) -> None:
    feature_config = page_features.load_feature_config()
    problems: list[str] = []
    checked = 0
    for name, directory in classified.items():
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        if not docs.page:
            problems.append(f"{name}: no pages")
            continue
        last = max(docs.page, key=lambda page: page.page_number or 0)
        checked += 1
        position = page_features.extract_page_features(last, docs, feature_config)[
            "page_relative_position"
        ]
        if position != 1.0:
            problems.append(f"{name}#{last.page_number}: {position}")
    record(
        "03 the last page of every sample sits at relative position 1.0",
        not problems and checked > 0,
        f"samples={checked} problems={problems}",
    )


def check_04_penalties_and_purity(classified: dict[str, Path]) -> None:
    """Negative weights validate and score in range; features stay pure."""
    valid = json.loads((ROOT / "configs" / "page_types.json").read_text("utf-8"))

    # A vocabulary carrying a penalty must be accepted.
    penalised = json.loads(json.dumps(valid))
    penalised["page_types"][0]["rules"].append(
        {
            "feature": "text_coverage_ratio",
            "op": "ge",
            "threshold": 0.9,
            "weight": -1.0,
        }
    )
    try:
        taxonomy_module.parse_taxonomy(penalised, "penalised")
        accepted = True
        reason = ""
    except taxonomy_module.TaxonomyError as exc:
        accepted = False
        reason = str(exc)
    record(
        "04a a vocabulary carrying a negative weight validates",
        accepted,
        f"reason={reason}",
    )

    # Zero weight and penalty-only types must still be rejected.
    survived: list[str] = []
    mutations = {
        "zero weight": lambda d: d["page_types"][0]["rules"][0].update({"weight": 0}),
        "penalty only type": lambda d: d["page_types"][0].update(
            {
                "rules": [
                    dict(rule, weight=-abs(rule["weight"]))
                    for rule in d["page_types"][0]["rules"]
                ]
            }
        ),
    }
    for label, mutate in mutations.items():
        broken = json.loads(json.dumps(valid))
        mutate(broken)
        try:
            taxonomy_module.parse_taxonomy(broken, "mutated")
        except taxonomy_module.TaxonomyError:
            continue
        survived.append(label)
    record(
        "04b zero weight and penalty only types are still rejected",
        not survived,
        f"survived={survived}",
    )

    # Scores stay in 0..1 under the live vocabulary and under the penalised one.
    feature_config = page_features.load_feature_config()
    live = taxonomy_module.load_taxonomy()
    probe = taxonomy_module.parse_taxonomy(penalised, "penalised")
    out_of_range: list[str] = []
    unstable: list[str] = []
    ratio_offenders: list[str] = []
    pages_checked = 0
    for name, directory in classified.items():
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        for page in docs.page:
            pages_checked += 1
            first = page_features.extract_page_features(page, docs, feature_config)
            second = page_features.extract_page_features(page, docs, feature_config)
            if first != second or list(first) != list(page_features.FEATURE_NAMES):
                unstable.append(f"{name}#{page.page_number}")
            for feature in page_features.RATIO_FEATURES:
                if not 0.0 <= first[feature] <= 1.0:
                    ratio_offenders.append(
                        f"{name}#{page.page_number}:{feature}={first[feature]}"
                    )
            for vocabulary in (live, probe):
                for kind, score in taxonomy_module.score_page_types(
                    first, vocabulary
                ).items():
                    if not 0.0 <= score <= 1.0:
                        out_of_range.append(f"{name}#{page.page_number}:{kind}={score}")
    record(
        "04c every score stays within 0..1 with penalties in play",
        not out_of_range and pages_checked > 0,
        f"pages={pages_checked} offenders={out_of_range[:3]}",
    )
    record(
        "04d feature extraction stays pure and in range under the new definitions",
        not unstable and not ratio_offenders and pages_checked > 0,
        f"unstable={unstable[:3]} ratio_offenders={ratio_offenders[:3]}",
    )


def check_05_earlier_gates() -> None:
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
            f"05 {gate} still passes",
            proc.returncode == 0,
            f"exit={proc.returncode} {summary[-1] if summary else ''} "
            f"failures={failures[:3]}",
        )


def check_06_default_off(
    manifest: dict, produced_pdfs: dict[str, Path], default_dirs: list[Path]
) -> None:
    hits: list[str] = []
    scanned = 0
    for directory in default_dirs:
        for xml_path in sorted(directory.glob("*.xml")):
            scanned += 1
            text = xml_path.read_text(encoding="utf-8")
            hits.extend(
                f"{directory.name}/{xml_path.name}: {attribute}"
                for attribute in PAGE_ATTRIBUTES
                if attribute in text
            )
    record(
        "06a with the switch off no checkpoint carries a page kind attribute",
        not hits and scanned > 0,
        f"scanned={scanned} hits={hits[:5]}",
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


def check_07_change_scope() -> None:
    changed = changed_files()
    unexpected = sorted(changed - ALLOWED_CHANGES)
    record(
        "07a this batch changes only the files the plan allows",
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
        "07b this batch touches no upstream file",
        not upstream,
        f"upstream={upstream}",
    )


def check_08_no_type_names_and_no_cjk() -> None:
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
        "08a no page type name appears anywhere under babeldoc/",
        not offenders and scanned > 0,
        f"types={len(names)} files={scanned} offenders={offenders[:5]}",
    )

    cjk: list[str] = []
    for relative in sorted(ALLOWED_CHANGES):
        path = ROOT / relative
        if not path.exists():
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if has_cjk(line):
                cjk.append(f"{relative}:{number}")
    record(
        "08b no CJK characters in the files this batch changed",
        not cjk,
        f"offenders={cjk[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    use_project_cache(ROOT)
    warmup()

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    classified: dict[str, Path] = {}
    default_dirs: list[Path] = []
    produced_pdfs: dict[str, Path] = {}
    for entry in manifest["samples"]:
        name = Path(entry["file"]).stem
        pdf = INPUT_DIR / entry["file"]
        classified[name] = run_all_stages(pdf, name, classify=True)
        default_dirs.append(run_all_stages(pdf, name, classify=False))
        produced_pdf, parse_only_dir = run_parse_only(pdf, name)
        produced_pdfs[name] = produced_pdf
        default_dirs.append(parse_only_dir)

    check_01_image_area(manifest, classified)
    check_02_columns(classified)
    check_03_last_page(classified)
    check_04_penalties_and_purity(classified)
    check_06_default_off(manifest, produced_pdfs, default_dirs)
    check_07_change_scope()
    check_08_no_type_names_and_no_cjk()
    check_05_earlier_gates()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    print(f"spec_check_b2_1: {len(_results) - len(failed)}/{len(_results)} passed")
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
