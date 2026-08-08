"""Gate script for batch B2 (page features, page type vocabulary, PageClassifier).

Run from the repository root:

    python spec_checks/spec_check_b2.py

Exit code 0 when every assertion in plans/PLAN_B2.md passes, 1 otherwise.
Requires no API key: the pipeline is exercised with skip_translation and
only_parse_generate_pdf.
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
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine import page_features  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402
from babeldoc.magazine.page_classifier import REPORT_NAME  # noqa: E402
from babeldoc.magazine.page_classifier import SOURCE  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

PYTHON = sys.executable
# Tag that freezes this batch; once it exists the scope assertions read the
# delta it introduced instead of the working tree.
BATCH_TAG = "batch-b2"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
LABELS_PATH = ROOT / "corpus" / "page_labels.json"
INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output" / "b2"
STAGE_CONFIG = ROOT / "configs" / "checkpoint_stages.json"
UPSTREAM_DIFF = ROOT / "UPSTREAM_DIFF.md"

# Checks that need an artefact built during this run. run_all --fast skips
# them; 06c is skipped inside check_06_ground_truth, whose 06a and 06b validate
# the ground truth file itself and need no run.
PIPELINE_TIER = (
    "check_02_pure_features",
    "check_03_written_fields",
    "check_04_checkpoint_order",
    "check_05_report_tool",
    "check_06_ground_truth (06c only)",
    "check_07_default_off",
    "check_09_no_paragraph_fields",
)

# Page level IL attributes this batch is the first writer of.
PAGE_ATTRIBUTES = ("pageKind", "pageKindConf", "pageKindSource")
# Paragraph level B1 attributes that must stay untouched until a later batch.
PARAGRAPH_ATTRIBUTES = (
    "chainId",
    "chainIndex",
    "dropCapCandidate",
    "dropCapDecision",
    "segmentSentenceStart",
    "segmentSentenceEnd",
)

# Upstream files this batch is allowed to touch.
ALLOWED_UPSTREAM_B2 = {
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/format/pdf/translation_config.py",
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

NEW_CODE_GLOBS = (
    "babeldoc/magazine/*.py",
    "tools/*.py",
    "spec_checks/*.py",
    "configs/*.json",
    "corpus/*.json",
)

# Directories excluded from the "no page type name in code" scan, per PLAN_B2
# assertion 8. configs and prompts are outside babeldoc/ already.
TYPE_NAME_SCAN_ROOT = ROOT / "babeldoc"
TYPE_NAME_SCAN_SKIP = {"__pycache__", "tests", "test"}

# Modules that would mean the extension reaches the network or an LLM.
NETWORK_MARKERS = ("openai", "requests", "httpx")

# The magazine modules allowed to hold a model client. B2 had none, and the
# assertion below was the statement that the extension was reachable offline in
# its entirety. B3 introduced the project's first model call point in one named
# module, so the assertion now states the same thing about every other module:
# the client is one declared file rather than something that spread.
MODEL_CLIENT_MODULES = ("vlm_client.py",)

CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

_results: list[tuple[str, bool, str]] = []
_skipped: list[str] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b2_"))
_timer = harness.Timer("spec_check_b2")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


def skip(name: str, detail: str) -> None:
    _timer.mark(name)
    _skipped.append(name)
    print(f"[SKIPPED] {name} :: {detail}")


# --- pipeline helpers -------------------------------------------------------


def freeze_checkpoints(working_dir: Path, target: Path) -> Path:
    """Copy the checkpoints of a run into ``target``, replacing what was there."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for item in sorted(working_dir.glob(f"{CHECKPOINT_PREFIX}*")):
        shutil.copyfile(item, target / item.name)
    return target


def run_all_stages(pdf: Path, name: str, classify: bool) -> tuple[Path, Path]:
    """Run every non-translation stage; return (checkpoint dir, working dir)."""
    mode = "classified" if classify else "stages"
    with _timer.phase(f"pipeline:{mode}:{name}"):
        built = artifacts.get_artifacts(pdf, mode)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = freeze_checkpoints(
        built.working_dir, OUTPUT_DIR / f"{name}.{mode}"
    )
    return checkpoint_dir, built.working_dir


def run_parse_only(pdf: Path, name: str) -> tuple[Path, Path]:
    """Dry run with the classifier left at its default, for the render diff."""
    with _timer.phase(f"pipeline:parse_only:{name}"):
        built = artifacts.get_artifacts(pdf, "parse_only")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    produced_pdf = OUTPUT_DIR / f"{name}.b2.pdf"
    shutil.copyfile(built.mono_pdf, produced_pdf)
    checkpoint_dir = freeze_checkpoints(
        built.working_dir, OUTPUT_DIR / f"{name}.checkpoints"
    )
    return produced_pdf, checkpoint_dir


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


def scanned_python_sources() -> list[Path]:
    return [
        path
        for path in sorted(TYPE_NAME_SCAN_ROOT.rglob("*.py"))
        if not set(path.relative_to(ROOT).parts) & TYPE_NAME_SCAN_SKIP
    ]


# --- assertions -------------------------------------------------------------


def check_01_configs() -> None:
    problems: list[str] = []
    try:
        feature_config = page_features.load_feature_config()
    except page_features.ConfigError as exc:
        feature_config = {}
        problems.append(f"page_features.json: {exc}")
    try:
        vocabulary = taxonomy_module.load_taxonomy()
    except page_features.ConfigError as exc:
        vocabulary = None
        problems.append(f"page_types.json: {exc}")
    record(
        "01a both configuration files load and validate",
        not problems,
        f"problems={problems}",
    )
    if vocabulary is None:
        record("01b seed vocabulary has at least 15 types", False, "not loaded")
        record("01c every type declares all three policy keys", False, "not loaded")
        return
    record(
        "01b seed vocabulary has at least 15 types",
        len(vocabulary.page_types) >= 15,
        f"types={len(vocabulary.page_types)}",
    )
    # Required keys must all be present, and nothing may appear beyond them and
    # the optional flags the parser declares and fills a default in for.
    declarable = taxonomy_module.POLICY_KEYS | set(
        taxonomy_module.OPTIONAL_POLICY_DEFAULTS
    )
    incomplete = [
        page_type.name
        for page_type in vocabulary.page_types
        if not taxonomy_module.POLICY_KEYS <= set(page_type.policy)
        or not set(page_type.policy) <= declarable
    ]
    record(
        "01c every type declares all three policy keys",
        not incomplete,
        f"incomplete={incomplete} parameters={len(feature_config)}",
    )

    # A malformed vocabulary must be rejected, not silently accepted.
    rejected = 0
    valid = json.loads((ROOT / "configs" / "page_types.json").read_text("utf-8"))
    mutations = {
        "unknown feature": lambda d: d["page_types"][0]["rules"][0].update(
            {"feature": "not_a_feature"}
        ),
        "illegal op": lambda d: d["page_types"][0]["rules"][0].update({"op": "eq"}),
        "non positive weight": lambda d: d["page_types"][0]["rules"][0].update(
            {"weight": 0}
        ),
        "missing policy key": lambda d: d["page_types"][0]["policy"].pop("translate"),
        "duplicate name": lambda d: d["page_types"].append(
            json.loads(json.dumps(d["page_types"][0]))
        ),
    }
    survived: list[str] = []
    for label, mutate in mutations.items():
        broken = json.loads(json.dumps(valid))
        mutate(broken)
        try:
            taxonomy_module.parse_taxonomy(broken, "mutated")
        except taxonomy_module.TaxonomyError:
            rejected += 1
        else:
            survived.append(label)
    record(
        "01d the validator rejects every malformed vocabulary probe",
        not survived and rejected == len(mutations),
        f"survived={survived}",
    )


def check_02_pure_features(checkpoint_dirs: list[Path]) -> None:
    feature_config = page_features.load_feature_config()
    unstable: list[str] = []
    out_of_range: list[str] = []
    pages_checked = 0
    for directory in checkpoint_dirs:
        for xml_path in sorted(directory.glob("*.xml")):
            docs = checkpoint_module.load_checkpoint(xml_path)
            for page in docs.page:
                pages_checked += 1
                first = page_features.extract_page_features(page, docs, feature_config)
                second = page_features.extract_page_features(page, docs, feature_config)
                if first != second or list(first) != list(page_features.FEATURE_NAMES):
                    unstable.append(f"{xml_path.name}#{page.page_number}")
                for name in page_features.RATIO_FEATURES:
                    if not 0.0 <= first[name] <= 1.0:
                        out_of_range.append(
                            f"{xml_path.name}#{page.page_number}:{name}={first[name]}"
                        )
    record(
        "02a repeated extraction returns bit identical feature vectors",
        not unstable and pages_checked > 0,
        f"pages={pages_checked} unstable={unstable[:3]}",
    )
    record(
        "02b every ratio feature stays within 0..1",
        not out_of_range,
        f"offenders={out_of_range[:3]}",
    )


def check_03_written_fields(runs: dict[str, tuple[Path, Path]]) -> None:
    problems: list[str] = []
    reports: list[str] = []
    pages_seen = 0
    for name, (checkpoint_dir, working_dir) in runs.items():
        stem = checkpoint_module.checkpoint_stem("page_classifier")
        xml_path = checkpoint_dir / f"{stem}.xml"
        if not xml_path.exists():
            problems.append(f"{name}: {stem}.xml missing")
            continue
        docs = checkpoint_module.load_checkpoint(xml_path)
        for page in docs.page:
            pages_seen += 1
            if not page.page_kind:
                problems.append(f"{name}#{page.page_number}: empty pageKind")
            if page.page_kind_conf is None or not 0.0 <= page.page_kind_conf <= 1.0:
                problems.append(
                    f"{name}#{page.page_number}: conf={page.page_kind_conf}"
                )
            if page.page_kind_source != SOURCE:
                problems.append(
                    f"{name}#{page.page_number}: source={page.page_kind_source!r}"
                )

        report_path = working_dir / REPORT_NAME
        if not report_path.exists():
            reports.append(f"{name}: {REPORT_NAME} missing")
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if len(report.get("pages", [])) != len(docs.page):
            reports.append(
                f"{name}: report has {len(report.get('pages', []))} pages, "
                f"IL has {len(docs.page)}"
            )
        manifest = working_dir / taxonomy_module.RUN_MANIFEST_NAME
        if not manifest.exists():
            reports.append(f"{name}: config manifest missing")
    record(
        "03a every classified page carries kind, confidence and source",
        not problems and pages_seen > 0,
        f"pages={pages_seen} problems={problems[:3]}",
    )
    record(
        "03b the sidecar report exists and covers every page",
        not reports,
        f"problems={reports[:3]}",
    )


def check_04_checkpoint_order(checkpoint_dirs: list[Path]) -> None:
    with STAGE_CONFIG.open(encoding="utf-8") as f:
        stages = json.load(f)["stages"]
    declared = {name: index + 1 for index, name in enumerate(stages)}
    problems: list[str] = []
    scanned = 0
    for directory in checkpoint_dirs:
        ordinals = []
        for xml_path in sorted(directory.glob("*.xml")):
            scanned += 1
            _, tail = xml_path.name.split(CHECKPOINT_PREFIX, 1)
            ordinal_text, _, rest = tail.partition("_")
            stage = rest.rsplit(".", 1)[0]
            ordinal = int(ordinal_text)
            ordinals.append(ordinal)
            if declared.get(stage) != ordinal:
                problems.append(
                    f"{directory.name}/{xml_path.name}: declared "
                    f"{declared.get(stage)} != {ordinal}"
                )
        if any(a >= b for a, b in zip(ordinals, ordinals[1:], strict=False)):
            problems.append(f"{directory.name}: ordinals not increasing {ordinals}")
    record(
        "04 checkpoint ordinals increase and match checkpoint_stages.json",
        not problems and scanned > 0,
        f"scanned={scanned} problems={problems[:3]}",
    )


def check_05_report_tool(magazine: dict, checkpoint_dir: Path) -> None:
    pdf = INPUT_DIR / magazine["file"]
    stem = checkpoint_module.checkpoint_stem("page_classifier")
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [
            PYTHON,
            str(ROOT / "tools" / "page_classify_report.py"),
            str(pdf),
            "--checkpoint",
            str(checkpoint_dir / f"{stem}.xml"),
            "--out",
            str(OUTPUT_DIR),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    target = OUTPUT_DIR / f"{pdf.stem}.classify.html"
    if proc.returncode != 0 or not target.exists():
        record(
            "05 the review tool renders one HTML page per magazine page",
            False,
            f"exit={proc.returncode} stderr={proc.stderr.strip()[:200]}",
        )
        return
    rendered = target.read_text(encoding="utf-8").count('<div class="page">')
    with pymupdf.open(pdf) as doc:
        expected = doc.page_count
    record(
        "05 the review tool renders one HTML page per magazine page",
        rendered == expected,
        f"html_pages={rendered} pdf_pages={expected} -> {target.name}",
    )


def classified_kinds(checkpoint_dir: Path) -> dict[str, str]:
    """Page kind per 1-based page number, the numbering the labels use."""
    xml_path = (
        checkpoint_dir / f"{checkpoint_module.checkpoint_stem('page_classifier')}.xml"
    )
    docs = checkpoint_module.load_checkpoint(xml_path)
    kinds: dict[str, str] = {}
    for position, page in enumerate(docs.page):
        index = page.page_number if page.page_number is not None else position
        kinds[str(index + 1)] = page.page_kind
    return kinds


def check_06_ground_truth(runs: dict[str, tuple[Path, Path]], manifest: dict) -> None:
    vocabulary = taxonomy_module.load_taxonomy()
    known = set(vocabulary.names())
    # Two page types with the same policy are interchangeable to everything
    # downstream, so agreement is measured at that level as well.
    policy_of = {
        page_type.name: tuple(sorted(page_type.policy.items()))
        for page_type in vocabulary.page_types
    }

    pages_by_file = {sample["file"]: sample["pages"] for sample in manifest["samples"]}
    raw = corpus_module.load_page_labels(LABELS_PATH)
    errors = corpus_module.validate_page_labels(
        raw, known, LABELS_PATH.name, pages_by_file
    )
    record(
        "06a the page label ground truth validates against the vocabulary",
        not errors,
        f"errors={errors[:5]}",
    )

    probes = {
        "empty array": {"a.pdf": {"1": []}},
        "undeclared type name": {"a.pdf": {"1": [sorted(known)[0], "not_a_page_type"]}},
        "repeated element": {"a.pdf": {"1": [sorted(known)[0], sorted(known)[0]]}},
        "non string element": {"a.pdf": {"1": [7]}},
        "page number not 1-based": {"a.pdf": {"zero": [sorted(known)[0]]}},
    }
    survived = [
        label
        for label, probe in probes.items()
        if not corpus_module.validate_page_labels(probe, known, "probe")
    ]
    record(
        "06b the label validator rejects every malformed probe",
        not survived,
        f"survived={survived}",
    )

    name = "06c classification agrees with the human page labels"
    if harness.FAST_TIER:
        harness.fast_skip(name)
        return
    if errors:
        skip(name, f"{LABELS_PATH.name} is malformed; agreement is not measurable")
        return
    labelled = {
        file_name: pages
        for file_name, pages in corpus_module.normalize_page_labels(raw).items()
        if pages
    }
    if not labelled:
        skip(name, f"{LABELS_PATH.name} is empty; no ground truth to check")
        return

    publication_of = {
        sample["file"]: sample.get("publication", "") for sample in manifest["samples"]
    }
    minimum = page_features.load_feature_config()["label_agreement_min"]
    # publication -> [kind hits, policy hits, labelled pages]
    tallies: dict[str, list[int]] = {}
    misses: list[str] = []
    for file_name, expected_by_page in labelled.items():
        stem = Path(file_name).stem
        publication = publication_of.get(file_name, file_name)
        if stem not in runs:
            misses.append(f"{file_name}: not in the corpus run")
            continue
        actual_kinds = classified_kinds(runs[stem][0])
        tally = tallies.setdefault(publication, [0, 0, 0])
        for page_number, accepted in expected_by_page.items():
            tally[2] += 1
            actual = actual_kinds.get(page_number)
            if actual in accepted:
                tally[0] += 1
                tally[1] += 1
                continue
            if actual in policy_of and any(
                policy_of[actual] == policy_of[candidate] for candidate in accepted
            ):
                tally[1] += 1
            misses.append(f"{file_name}#{page_number}: {actual!r} not in {accepted}")

    kind_hits = sum(tally[0] for tally in tallies.values())
    policy_hits = sum(tally[1] for tally in tallies.values())
    total = sum(tally[2] for tally in tallies.values())
    rate = kind_hits / total if total else 0.0
    policy_rate = policy_hits / total if total else 0.0

    print("    label agreement by publication (kind / policy / labelled pages):")
    for publication in sorted(tallies):
        hits, policy, count = tallies[publication]
        print(
            f"      {publication}: kind={hits / count:.3f} ({hits}/{count}) "
            f"policy={policy / count:.3f} ({policy}/{count})"
        )
    record(
        name,
        total > 0 and rate >= minimum,
        f"kind_agreement={rate:.3f} ({kind_hits}/{total}), "
        f"policy_agreement={policy_rate:.3f} ({policy_hits}/{total}), "
        f"minimum={minimum}, misses={misses[:5]}",
    )


def check_07_default_off(
    manifest: dict, produced_pdfs: dict[str, Path], checkpoint_dirs: list[Path]
) -> None:
    hits: list[str] = []
    scanned = 0
    for directory in checkpoint_dirs:
        for xml_path in sorted(directory.glob("*.xml")):
            scanned += 1
            text = xml_path.read_text(encoding="utf-8")
            hits.extend(
                f"{directory.name}/{xml_path.name}: {attribute}"
                for attribute in PAGE_ATTRIBUTES
                if attribute in text
            )
    record(
        "07a with the switch off no checkpoint carries a page kind attribute",
        not hits and scanned > 0,
        f"scanned={scanned} hits={hits[:5]}",
    )
    for entry in manifest["samples"]:
        name = Path(entry["file"]).stem
        baseline = ROOT / entry["baseline"]["pdf"]
        code = render_diff(baseline, produced_pdfs[name], _tmp_root / f"rd_{name}")
        record(
            f"07b dry run still renders identically to the baseline ({name})",
            code == 0,
            f"exit={code}",
        )


def check_08_no_type_names_in_code() -> None:
    vocabulary = taxonomy_module.load_taxonomy()
    names = vocabulary.names()
    patterns = {
        name: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        for name in names
    }
    offenders: list[str] = []
    scanned = 0
    for path in scanned_python_sources():
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in patterns.items():
            if pattern.search(text):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}: {name}")
    record(
        "08 no page type name appears anywhere under babeldoc/",
        not offenders and scanned > 0,
        f"types={len(names)} files={scanned} offenders={offenders[:5]}",
    )


def check_09_no_paragraph_fields(checkpoint_dirs: list[Path]) -> None:
    hits: list[str] = []
    scanned = 0
    for directory in checkpoint_dirs:
        for xml_path in sorted(directory.glob("*.xml")):
            scanned += 1
            text = xml_path.read_text(encoding="utf-8")
            hits.extend(
                f"{directory.name}/{xml_path.name}: {attribute}"
                for attribute in PARAGRAPH_ATTRIBUTES
                if attribute in text
            )
    record(
        "09 no produced checkpoint carries a paragraph level B1 attribute",
        not hits and scanned > 0,
        f"scanned={scanned} hits={hits[:5]}",
    )


def check_10_offline() -> None:
    offenders: list[str] = []
    scanned = 0
    exempt = 0
    for path in sorted((ROOT / "babeldoc" / "magazine").glob("*.py")):
        if path.name in MODEL_CLIENT_MODULES:
            exempt += 1
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8")
        offenders.extend(
            f"{path.name}: {marker}" for marker in NETWORK_MARKERS if marker in text
        )
    record(
        "10 the magazine package contains no network or LLM client",
        not offenders and scanned > 0 and exempt == len(MODEL_CLIENT_MODULES),
        f"modules={scanned} declared_clients={list(MODEL_CLIENT_MODULES)} "
        f"present={exempt} offenders={offenders}",
    )


def check_11_upstream_scope() -> None:
    changed = changed_upstream_files()
    record(
        "11a this batch touches only the two registered upstream files",
        changed <= ALLOWED_UPSTREAM_B2,
        f"changed={sorted(changed)}",
    )
    registry = UPSTREAM_DIFF.read_text(encoding="utf-8")
    unregistered = sorted(path for path in changed if path not in registry)
    record(
        "11b every modified upstream file is registered in UPSTREAM_DIFF.md",
        not unregistered,
        f"unregistered={unregistered}",
    )

    offenders: list[str] = []
    for pattern in NEW_CODE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if has_cjk(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
    _, diff = git_output(
        ["diff", "-U0", *batch_revisions(), "--", *sorted(ALLOWED_UPSTREAM_B2)]
    )
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++") and has_cjk(line):
            offenders.append(f"added upstream line: {line.strip()}")
    record(
        "11c no CJK characters in new or added code",
        not offenders,
        f"offenders={offenders[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    with _timer.phase("warmup"):
        use_project_cache(ROOT)
        warmup()

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)
    magazines = [entry for entry in manifest["samples"] if entry.get("magazine")]
    if not magazines:
        record("00 the corpus registers at least one magazine sample", False, "none")
        return 1

    check_01_configs()

    classified: dict[str, tuple[Path, Path]] = {}
    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
        check_06_ground_truth(classified, manifest)
    else:
        default_checkpoints: list[Path] = []
        produced_pdfs: dict[str, Path] = {}
        for entry in manifest["samples"]:
            name = Path(entry["file"]).stem
            pdf = INPUT_DIR / entry["file"]
            classified[name] = run_all_stages(pdf, name, classify=True)
            off_dir, _ = run_all_stages(pdf, name, classify=False)
            default_checkpoints.append(off_dir)
            produced_pdf, parse_only_dir = run_parse_only(pdf, name)
            produced_pdfs[name] = produced_pdf
            default_checkpoints.append(parse_only_dir)

        classified_dirs = [directory for directory, _ in classified.values()]
        check_02_pure_features(classified_dirs + default_checkpoints)
        check_03_written_fields(classified)
        check_04_checkpoint_order(classified_dirs + default_checkpoints)
        check_05_report_tool(
            magazines[0], classified[Path(magazines[0]["file"]).stem][0]
        )
        check_06_ground_truth(classified, manifest)
        check_07_default_off(manifest, produced_pdfs, default_checkpoints)
        check_09_no_paragraph_fields(classified_dirs + default_checkpoints)

    check_08_no_type_names_in_code()
    check_10_offline()
    check_11_upstream_scope()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b2")
    artifacts.print_stats("spec_check_b2")
    _timer.write()
    _timer.print_summary()
    print(
        f"spec_check_b2: {len(_results) - len(failed)}/{len(_results)} passed, "
        f"{len(_skipped)} skipped"
    )
    for name in failed:
        print(f"  FAILED: {name}")
    for name in _skipped:
        print(f"  SKIPPED: {name}")
    shutil.rmtree(_tmp_root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
