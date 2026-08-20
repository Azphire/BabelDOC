"""Gate script for batch B2.3 (evidence forensics, positive evidence guard).

Run from the repository root:

    python spec_checks/spec_check_b2_3.py

Exit code 0 when every assertion in plans/PLAN_B2_3.md passes, 1 otherwise.
Requires no API key: the pipeline is exercised with skip_translation and
only_parse_generate_pdf. Five earlier gates are re-run as subprocesses, so this
script takes a while.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from bisect import bisect_left
from bisect import bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402
from babeldoc.magazine.page_classifier import REPORT_NAME  # noqa: E402
from babeldoc.magazine.page_features import FEATURE_NAMES  # noqa: E402
from babeldoc.magazine.page_features import PERCENTILE_SUFFIX  # noqa: E402
from babeldoc.magazine.page_features import extract_document_features  # noqa: E402
from babeldoc.magazine.page_features import load_feature_config  # noqa: E402
from babeldoc.magazine.page_features import percentile_feature_names  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It asks the artifact builder
# for documents, so a cold slot means re-running the pipeline over the
# corpus -- minutes per sample -- and it runs on the cycle's full sweep
# rather than on every batch.
GATE_SET = "sweep"

PYTHON = sys.executable
# Tag that freezes this batch; once it exists the scope assertions read the
# delta it introduced instead of the working tree.
BATCH_TAG = "batch-b2.3"
# The commit this batch builds on; the page type vocabulary must be identical
# to it apart from the guard switch this batch introduces.
PREVIOUS_TAG = "batch-b2.2"

MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output" / "b2_3"

# The switch T2.3b adds. It is the only key this batch may add to the taxonomy.
GUARD_KEY = "require_positive_evidence"

# Features computed from the paragraphs of a page, so a page carrying none of
# them reports every one as zero. The forensic assertion separates these from
# the features a page can still carry with no paragraph on it at all.
PARAGRAPH_DERIVED = frozenset(
    {
        "text_coverage_ratio",
        "paragraph_count",
        "mean_paragraph_chars",
        "short_paragraph_ratio",
        "numeric_token_density",
        "leader_dot_line_ratio",
        "title_label_ratio",
        "distinct_font_size_count",
        "max_font_size_ratio",
        "column_count_estimate",
    }
)

# Files this batch is allowed to change, per PLAN_B2_3 negative assertion 7.
# CLAUDE.md and the plan carry the plan revision the plan author made during
# this session, which that assertion excludes from the whitelist check; they
# are listed so the scan stays exact rather than filtered.
# spec_checks/run_all.py and the SPEC_NO_NESTED switch it drives are on the
# list because the gate runner replaces the nested re-runs; that widening was
# authorized in the same session as the plan revision.
ALLOWED_CHANGES = {
    "CLAUDE.md",
    "babeldoc/magazine/taxonomy.py",
    "configs/page_types.json",
    "plans/PLAN_B2_3.md",
    "spec_checks/run_all.py",
    "spec_checks/spec_check_b0.py",
    "spec_checks/spec_check_b1.py",
    "spec_checks/spec_check_b2.py",
    "spec_checks/spec_check_b2_1.py",
    "spec_checks/spec_check_b2_2.py",
    "spec_checks/spec_check_b2_3.py",
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

EARLIER_GATES = (
    "spec_check_b0.py",
    "spec_check_b1.py",
    "spec_check_b2.py",
    "spec_check_b2_1.py",
    "spec_check_b2_2.py",
)

# Set by spec_checks/run_all.py, which runs every gate once in order. The
# nested re-run below is the fallback for running this file on its own; under
# the runner it would repeat work the runner already covers, exponentially so.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Checks that need an artefact built during this run. run_all --fast skips
# them; the synthetic-page, validator, freeze and scope assertions build their
# own documents in memory or read files that are already on disk.
PIPELINE_TIER = (
    "check_01_forensics",
    "check_03_corpus_regression",
    "check_06_end_to_end",
)

CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# Documents whose prose is Chinese by design; the CJK scan covers code only.
CJK_SCAN_SUFFIXES = (".py", ".json")

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b2_3_"))
_timer = harness.Timer("spec_check_b2_3")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


# --- pipeline and git helpers ----------------------------------------------


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
    produced = OUTPUT_DIR / f"{name}.b2_3.pdf"
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


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def git_show(revision: str, path: str) -> bytes:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", "show", f"{revision}:{path}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def batch_tag_exists() -> bool:
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{BATCH_TAG}^{{commit}}"])
    return code == 0


def current_bytes(path: str) -> bytes:
    """This batch's version of a tracked file."""
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
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^", BATCH_TAG])
        return {line.strip() for line in listing.splitlines() if line.strip()}

    _, listing = git_output(["status", "--porcelain", "--untracked-files=all"])
    paths: set[str] = set()
    for line in listing.splitlines():
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        if entry:
            paths.add(entry.strip('"'))
    return paths


# --- scoring helpers --------------------------------------------------------


def midranks(values: list[float]) -> list[float]:
    """Midrank of every value among its own column.

    Spelled out here rather than imported, so the forensic assertion checks the
    reported percentiles against the definition the report documents instead of
    against the implementation that produced them.
    """
    ordered = sorted(values)
    total = len(values)
    ranks = []
    for value in values:
        below = bisect_left(ordered, value)
        equal = bisect_right(ordered, value) - below
        ranks.append((below + 0.5 * equal) / total)
    return ranks


def taxonomies() -> tuple[taxonomy_module.Taxonomy, taxonomy_module.Taxonomy]:
    """The shipped vocabulary with the guard on, and the same one with it off."""
    guarded = taxonomy_module.load_taxonomy()
    return guarded, dataclasses.replace(guarded, require_positive_evidence=False)


def blank_page(number: int) -> il_version_1.Page:
    return il_version_1.Page(
        page_number=number,
        cropbox=il_version_1.Cropbox(
            box=il_version_1.Box(x=0.0, y=0.0, x2=100.0, y2=100.0)
        ),
        mediabox=il_version_1.Mediabox(
            box=il_version_1.Box(x=0.0, y=0.0, x2=100.0, y2=100.0)
        ),
        page_layout=[],
    )


# --- assertions -------------------------------------------------------------


def check_01_forensics(reports: dict[str, Path]) -> None:
    """T2.3a: the percentile table is sound and states what the raw values say.

    The B2.2 report described a zero paragraph page as carrying only zeros
    while its image_area_ratio percentile sat at the top of its document. The
    two are reconciled here as data: percentiles are recomputable from the
    reported raw column, and a page with no paragraph still carries the
    features that do not come from paragraphs.
    """
    percentile_names = percentile_feature_names(load_feature_config())
    mismatches: list[str] = []
    pages_checked = 0
    for name, path in sorted(reports.items()):
        report = json.loads(path.read_text(encoding="utf-8"))
        pages = report["pages"]
        pages_checked += len(pages)
        for key in percentile_names:
            raw = key[: -len(PERCENTILE_SUFFIX)]
            expected = midranks([page["features"][raw] for page in pages])
            for page, value in zip(pages, expected, strict=True):
                if page["features_pctl"][key] != value:
                    mismatches.append(
                        f"{name}#{page['page_number']}.{key}: "
                        f"{page['features_pctl'][key]} != {value}"
                    )
    record(
        "01a every reported percentile is the midrank of its own reported raw column",
        not mismatches and pages_checked > 0,
        f"pages={pages_checked} mismatches={mismatches[:3]}",
    )

    blank_pages: list[tuple[str, dict]] = []
    contradictions: list[str] = []
    for name, path in sorted(reports.items()):
        report = json.loads(path.read_text(encoding="utf-8"))
        for page in report["pages"]:
            if page["features"]["paragraph_count"] != 0.0:
                continue
            blank_pages.append((name, page))
            nonzero_derived = sorted(
                key for key in PARAGRAPH_DERIVED if page["features"][key] != 0.0
            )
            if nonzero_derived:
                contradictions.append(
                    f"{name}#{page['page_number']}: {nonzero_derived}"
                )
    record(
        "01b a page with no paragraph reports every paragraph derived feature as zero",
        bool(blank_pages) and not contradictions,
        f"blank_pages={[(n, p['page_number']) for n, p in blank_pages]} "
        f"contradictions={contradictions[:3]}",
    )

    # The claim under investigation: such a page is not all zeros. At least one
    # of them carries positive artwork area, which is what put its percentile
    # at the top of its own document rather than at the tie value of 0.5.
    carriers = [
        (
            name,
            page["page_number"],
            page["features"]["image_area_ratio"],
            page["features_pctl"]["image_area_ratio" + PERCENTILE_SUFFIX],
        )
        for name, page in blank_pages
        if page["features"]["image_area_ratio"] > 0.0
    ]
    tops = [entry for entry in carriers if entry[3] > 0.5]
    record(
        "01c a zero paragraph page still carries positive image area, "
        "which its percentile reflects",
        bool(tops),
        f"carriers={carriers} above_tie={len(tops)}",
    )

    # The remaining candidate explanation, a midrank defect on an all equal
    # column, is refuted directly: such a column lands on the tie value.
    constant_columns: list[str] = []
    wrong: list[str] = []
    for name, path in sorted(reports.items()):
        report = json.loads(path.read_text(encoding="utf-8"))
        pages = report["pages"]
        for key in percentile_names:
            raw = key[: -len(PERCENTILE_SUFFIX)]
            column = [page["features"][raw] for page in pages]
            if len(set(column)) != 1:
                continue
            constant_columns.append(f"{name}.{raw}")
            if any(page["features_pctl"][key] != 0.5 for page in pages):
                wrong.append(f"{name}.{key}")
    record(
        "01d a feature constant across a document sits at the tie value on every page",
        bool(constant_columns) and not wrong,
        f"columns={len(constant_columns)} wrong={wrong[:3]}",
    )


def check_02_empty_page_scores_nothing() -> None:
    """T2.3b: a page with nothing on it is evidence for no type at all."""
    guarded, unguarded = taxonomies()
    config = load_feature_config()

    document = il_version_1.Document(total_pages=2)
    document.page.extend(blank_page(index) for index in range(2))
    features = extract_document_features(document, config)[0]

    carried = sorted(key for key in FEATURE_NAMES if features[key] != 0.0)
    record(
        "02a the synthetic page carries no paragraph and no artwork",
        carried == ["page_relative_position"],
        f"non zero raw features={carried}",
    )

    scored = taxonomy_module.score_page_types(features, guarded)
    nonzero = sorted(name for name, value in scored.items() if value != 0.0)
    before = taxonomy_module.score_page_types(features, unguarded)
    record(
        "02b the synthetic page scores zero on every declared type",
        len(scored) == len(guarded.page_types) and not nonzero,
        f"types={len(scored)} nonzero={nonzero} "
        f"without the guard top={max(before.items(), key=lambda kv: kv[1])}",
    )

    verdict = taxonomy_module.classify(features, guarded)
    record(
        "02c the synthetic page falls to the declared default at zero confidence",
        verdict.kind == guarded.default_type and verdict.confidence == 0.0,
        f"kind={verdict.kind} conf={verdict.confidence} default={guarded.default_type}",
    )

    # The same holds for the literal all zero vector, which is what a page with
    # no paragraph at the very front of a long document would produce.
    zero = dict.fromkeys(FEATURE_NAMES, 0.0)
    zero.update(dict.fromkeys(percentile_feature_names(config), 0.5))
    zero_scores = taxonomy_module.score_page_types(zero, guarded)
    zero_verdict = taxonomy_module.classify(zero, guarded)
    record(
        "02d the all zero feature vector scores zero everywhere and takes the default",
        not any(zero_scores.values())
        and zero_verdict.kind == guarded.default_type
        and zero_verdict.confidence == 0.0,
        f"nonzero={[k for k, v in zero_scores.items() if v]} "
        f"kind={zero_verdict.kind} conf={zero_verdict.confidence}",
    )


def check_03_corpus_regression(classified: dict[str, Path]) -> None:
    """The guard changes no page that had evidence for its verdict."""
    guarded, unguarded = taxonomies()
    config = load_feature_config()

    verdicts = 0
    out_of_range: list[str] = []
    unverdicted: list[str] = []
    regressions: list[str] = []
    guard_only: list[str] = []
    zeroed_cells = 0
    for name, directory in sorted(classified.items()):
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        for page, features in zip(
            docs.page, extract_document_features(docs, config), strict=True
        ):
            verdicts += 1
            after = taxonomy_module.classify(features, guarded)
            before = taxonomy_module.classify(features, unguarded)
            where = f"{name}#{page.page_number}"
            if not after.kind:
                unverdicted.append(where)
            if not 0.0 <= after.confidence <= 1.0:
                out_of_range.append(f"{where}: {after.confidence}")
            zeroed_cells += sum(
                1 for key in after.scores if after.scores[key] != before.scores[key]
            )
            had_evidence = any(
                page_type.name == before.kind and page_type.has_evidence(features)
                for page_type in guarded.page_types
            )
            if had_evidence and after.kind != before.kind:
                regressions.append(f"{where}: {before.kind} -> {after.kind}")
            elif after.kind != before.kind:
                guard_only.append(f"{where}: {before.kind} -> {after.kind}")

    record(
        "03a every corpus page still receives a verdict with a confidence in 0..1",
        verdicts > 0 and not unverdicted and not out_of_range,
        f"pages={verdicts} unverdicted={unverdicted} out_of_range={out_of_range[:3]}",
    )
    record(
        "03b no page whose winning type had positive evidence changed verdict",
        not regressions,
        f"pages={verdicts} regressions={regressions[:5]} "
        f"changed_without_evidence={guard_only}",
    )
    record(
        "03c the guard does withdraw score from types a page shows no sign of",
        zeroed_cells > 0,
        f"page/type cells zeroed={zeroed_cells}",
    )


def check_04_validator() -> None:
    """The validator enforces the guard's precondition and the switch itself."""
    valid = json.loads((ROOT / "configs" / "page_types.json").read_text("utf-8"))

    accepted = True
    detail = ""
    try:
        shipped = taxonomy_module.parse_taxonomy(valid, "page_types.json")
    except taxonomy_module.TaxonomyError as error:  # pragma: no cover - gate path
        accepted = False
        detail = str(error)
        shipped = None
    record(
        "04a the shipped vocabulary validates",
        accepted,
        detail or f"types={len(shipped.names()) if shipped else 0}",
    )

    without_evidence = [
        page_type.name
        for page_type in (shipped.page_types if shipped else ())
        if not page_type.evidence_rules
    ]
    record(
        "04b every shipped type carries at least one positive weight ge/gt rule",
        shipped is not None and not without_evidence,
        f"types={len(shipped.names()) if shipped else 0} "
        f"without_evidence={without_evidence}",
    )

    rejected: dict[str, bool] = {}

    # A type reachable only by what a page lacks.
    mutated = json.loads(json.dumps(valid))
    mutated["page_types"][0]["rules"] = [
        {"feature": "text_coverage_ratio", "op": "le", "threshold": 0.2, "weight": 2.0},
        {"feature": "paragraph_count", "op": "lt", "threshold": 6.0, "weight": 1.0},
    ]
    rejected["type without a ge/gt positive rule"] = _rejects(mutated)

    # A type whose only ge rule is a penalty is equally unreachable by evidence.
    mutated = json.loads(json.dumps(valid))
    mutated["page_types"][0]["rules"] = [
        {"feature": "text_coverage_ratio", "op": "le", "threshold": 0.2, "weight": 2.0},
        {"feature": "image_area_ratio", "op": "ge", "threshold": 0.4, "weight": -1.0},
    ]
    rejected["type whose only ge rule is a penalty"] = _rejects(mutated)

    mutated = json.loads(json.dumps(valid))
    mutated.pop(GUARD_KEY)
    rejected[f"missing {GUARD_KEY}"] = _rejects(mutated)

    mutated = json.loads(json.dumps(valid))
    mutated[GUARD_KEY] = "true"
    rejected[f"non boolean {GUARD_KEY}"] = _rejects(mutated)

    record(
        "04c the validator rejects a type with no positive evidence rule "
        "and a malformed switch",
        all(rejected.values()),
        f"rejected={rejected}",
    )


def _rejects(raw: dict) -> bool:
    try:
        taxonomy_module.parse_taxonomy(raw, "mutated.json")
    except taxonomy_module.TaxonomyError:
        return True
    return False


def check_05_vocabulary_frozen() -> None:
    """Negative 6: nothing but the switch changed in the vocabulary."""
    current = json.loads(current_bytes("configs/page_types.json"))
    previous = json.loads(git_show(PREVIOUS_TAG, "configs/page_types.json"))

    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    record(
        "05a the taxonomy gains only the guard switch and loses no key",
        added == [GUARD_KEY] and not removed,
        f"added={added} removed={removed}",
    )

    # description is the file's own prose and documents the new switch; every
    # other top level key, the rule set included, must be untouched.
    drifted = [
        key
        for key, value in previous.items()
        if key != "description" and current.get(key) != value
    ]
    record(
        "05b every pre-existing threshold, weight and policy is unchanged",
        not drifted,
        f"drifted={drifted}",
    )

    rules_before = {entry["name"]: entry["rules"] for entry in previous["page_types"]}
    rules_after = {entry["name"]: entry["rules"] for entry in current["page_types"]}
    rule_drift = sorted(
        name for name in rules_before if rules_before[name] != rules_after.get(name)
    )
    record(
        "05c no page type gained, lost or retuned a rule",
        not rule_drift and set(rules_before) == set(rules_after),
        f"types={len(rules_after)} drift={rule_drift}",
    )


def check_06_end_to_end(
    manifest: dict,
    classified: dict[str, Path],
    reports: dict[str, Path],
    produced_pdfs: dict[str, Path],
) -> None:
    """End to end: the corpus still runs, conserves and renders identically."""
    problems: list[str] = []
    totals: list[str] = []
    pages_by_file = {
        Path(entry["file"]).stem: entry["pages"] for entry in manifest["samples"]
    }
    for name, directory in sorted(classified.items()):
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        stem = checkpoint_module.checkpoint_stem("styles_and_formulas")
        before = checkpoint_module.load_checkpoint(directory / f"{stem}.xml")
        pages = len(docs.page)
        paragraphs = sum(len(page.pdf_paragraph) for page in docs.page)
        totals.append(f"{name}:{pages}p/{paragraphs}par")
        if pages != pages_by_file[name]:
            problems.append(
                f"{name}: {pages} pages, manifest says {pages_by_file[name]}"
            )
        if (
            len(before.page) != pages
            or sum(len(page.pdf_paragraph) for page in before.page) != paragraphs
        ):
            problems.append(f"{name}: paragraph count moved across the stage")
        unset = [
            page.page_number
            for page in docs.page
            if not page.page_kind or page.page_kind_source is None
        ]
        if unset:
            problems.append(f"{name}: pages without a kind {unset}")
    record(
        "06a the classifier stage conserves pages and paragraphs and labels every page",
        not problems and bool(classified),
        f"{totals} problems={problems[:3]}",
    )

    # The sidecar is the artefact a tuning session reads; it must agree with a
    # fresh scoring of the same checkpoint under the guard.
    guarded, _ = taxonomies()
    config = load_feature_config()
    drift: list[str] = []
    for name, directory in sorted(classified.items()):
        report = json.loads(reports[name].read_text(encoding="utf-8"))
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(directory))
        for page, features, entry in zip(
            docs.page,
            extract_document_features(docs, config),
            report["pages"],
            strict=True,
        ):
            verdict = taxonomy_module.classify(features, guarded)
            if (
                entry["kind"] != verdict.kind
                or entry["conf"] != verdict.confidence
                or entry["scores"] != verdict.scores
                or page.page_kind != verdict.kind
            ):
                drift.append(f"{name}#{page.page_number}")
    record(
        "06b the sidecar report and the IL carry the guarded scores",
        not drift,
        f"drift={drift[:5]}",
    )

    for entry in manifest["samples"]:
        name = Path(entry["file"]).stem
        baseline = ROOT / entry["baseline"]["pdf"]
        code = render_diff(baseline, produced_pdfs[name], _tmp_root / f"rd_{name}")
        record(
            f"06c dry run still renders identically to the baseline ({name})",
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
        "07c no CJK characters in the code and configuration this batch changed",
        not cjk and checked > 0,
        f"files={checked} offenders={cjk[:5]}",
    )

    names = taxonomy_module.load_taxonomy().names()
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
        "07d no page type name appears anywhere under babeldoc/",
        not offenders and scanned > 0,
        f"types={len(names)} files={scanned} offenders={offenders[:5]}",
    )


def check_08_earlier_gates() -> None:
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
            f"08 {gate} still passes",
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
            if corpus_module.sha256_file(pdf) != entry["sha256"]:
                print(f"corpus sample {entry['file']} does not match the manifest hash")
                return 1
            classified[name], reports[name] = run_classified(pdf, name)
            produced_pdfs[name] = run_parse_only(pdf, name)

        check_01_forensics(reports)
        check_03_corpus_regression(classified)
        check_06_end_to_end(manifest, classified, reports, produced_pdfs)

    check_02_empty_page_scores_nothing()
    check_04_validator()
    check_05_vocabulary_frozen()
    check_07_change_scope()
    check_08_earlier_gates()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b2_3")
    artifacts.print_stats("spec_check_b2_3")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b2_3: {len(_results) - len(failed)}/{len(_results)} passed")
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
