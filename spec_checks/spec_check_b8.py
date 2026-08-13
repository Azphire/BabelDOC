"""Gate script for batch B8 session one (issue framework and detectors).

Run from the repository root:

    python spec_checks/spec_check_b8.py

Exit code 0 when every assertion T8.0 and T8.1 answer for passes, 1 otherwise.
Needs no API key and makes no network request: every run it performs is a dry
run of the parsing and classifying stages, and the one really translated
document it reads was frozen by an earlier batch.

01 is the configuration. Every bound is declared and respected, every issue
kind carries a declared weight, and every repair profile the page type
vocabulary declares is answered by a detector list -- that last one is the
binding between the two files, and without it a page kind could quietly fall to
the default profile forever. The negative probes are what prove the validator
refuses rather than repairs.

02 is the detectors, one at a time, on documents built here. Each gets a
positive case, a negative one, and the boundary its threshold sits on, because
a detector that fires on everything and a detector that fires on nothing both
pass a positive-only test. The escalation detector is checked for carrying
rather than for deciding: what it emits has to be what the chain pass wrote.

03 is the live evidence. The residue detector has to find `p6#15` -- the
fallback line the batch b7.5 passes measured twice as untranslated -- in the
frozen typesetting checkpoint of the run that measured it. This is the standing
requirement of the batch, and it is asserted against a real document rather
than a built one. Beside it is the corpus census, which is where the report
only detectors report.

04 is the default and the conservation. With the switch down nothing is
written; with it up the document is unchanged, byte for byte in its own
serialisation, and the run produces the same intermediate language and the same
render as the run without it.

05 is determinism: the same document detected twice gives the same record.

06 is the scope. No page type name and no repair profile name is a literal in
the detector package, so the profile is reached through policy alone. The
upstream delta is the two files this batch declared, both registered. The prose
is ASCII and no detector reaches a network client.

07 is the authorised maintenance this session carried out ahead of the batch:
the gate cache ceiling, the ruling-reach report and the review column that make
a ruling that reached nothing visible, and the sweep artefact that no longer
sits in git.

Tiers: 03b and 04c need pipeline artefacts and belong to the pipeline tier; the
rest are static, 03a included -- the fixture is frozen and reading it spends
nothing.
"""

from __future__ import annotations

import ast
import copy
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import chain_translation  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.detectors import base as detector_base  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b8.1"

PYTHON = sys.executable

PACKAGE = ROOT / "babeldoc" / "magazine" / "detectors"
CONFIG = "configs/detectors.json"
HITL_MODULE = "babeldoc/magazine/hitl.py"
OUTPUT_DIR = ROOT / "examples" / "output" / "b8"
FIXTURE = OUTPUT_DIR / "Courier-en.typeset.fixture.xml"
FIXTURE_PROVENANCE = OUTPUT_DIR / "Courier-en.typeset.fixture.json"
CENSUS_NAME = "corpus_detection.json"
CENSUS_TABLE = "corpus_detection.md"

# The finding this batch exists for, by the reference the review layer names it
# with, and the label the layout parser gave it.
LIVE_REFERENCE = "p6#15"
LIVE_PAGE = 6
LIVE_LABEL = "fallback_line"

# The sweep artefact T8.0 took out of git.
UNTRACKED_TABLE = "examples/output/b7_2/drop_cap_candidates.md"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = (
    "check_03b_corpus_census",
    "check_04c_switch_down_run",
)

# Paths this session may change. The two upstream files are the declared hook
# points and nothing else under babeldoc/ outside the extension package is in
# it.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "prompts/",
    "reviews/",
    "tools/",
    "spec_checks/",
    "plans/",
    "examples/output/",
)
ALLOWED_FILES = {"UPSTREAM_DIFF.md", "WAIVERS.md"}
ALLOWED_UPSTREAM = {
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/format/pdf/translation_config.py",
}

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b8_"))

# The gate never writes a review draft into the working tree it asserts about.
os.environ[hitl.REVIEWS_ENV] = str(_tmp_root / "reviews")

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b8")


def record(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _total
    _total += 1
    seconds = _timer.mark(name)
    if ok:
        _passed += 1
        print(f"PASS: {name} ({seconds:.2f}s)")
    else:
        _failures.append(f"{name}: {detail}")
        print(f"FAIL: {name}: {detail} ({seconds:.2f}s)")


def skip(name: str) -> None:
    global _total
    _total += 1
    _timer.mark(name)
    harness.fast_skip(name)


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def changed_paths() -> set[str]:
    """This batch's delta: its tag where it exists, the working tree otherwise."""
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^..{BATCH_TAG}"])
        return {line.strip() for line in listing.splitlines() if line.strip()}
    _, listing = git_output(["diff", "--name-only", "HEAD"])
    paths = {line.strip() for line in listing.splitlines() if line.strip()}
    _, untracked = git_output(["status", "--porcelain", "--untracked-files=all"])
    for line in untracked.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def sample_pdfs() -> list[Path]:
    manifest = corpus.load_manifest()
    return [ROOT / "examples" / "input" / entry["file"] for entry in manifest["samples"]]


def raw_config() -> dict:
    with (ROOT / CONFIG).open(encoding="utf-8") as f:
        return json.load(f)


def parse(raw: dict):
    """The configuration as the package validates it, against the real names."""
    return detector_base.parse_detector_config(
        raw,
        "probe.json",
        set(detectors.DETECTORS),
        {module.KIND for module in detectors.DETECTORS.values()},
    )


# --- documents built here -----------------------------------------------------


def style(font: str = "f", size: float = 10.0):
    return il_version_1.PdfStyle(
        font_id=font, font_size=size, graphic_state=il_version_1.GraphicState()
    )


def paragraph(
    text: str,
    box: tuple[float, float, float, float] = (0.0, 0.0, 100.0, 10.0),
    label: str = "plain text",
    font: str = "f",
    size: float = 10.0,
    debug_id: str | None = None,
):
    """One paragraph carrying its text the way a typeset one carries it."""
    composition = il_version_1.PdfParagraphComposition(
        pdf_same_style_unicode_characters=(
            il_version_1.PdfSameStyleUnicodeCharacters(unicode=text)
        )
    )
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*box),
        pdf_style=style(font, size),
        pdf_paragraph_composition=[composition],
        unicode=text,
        layout_label=label,
        debug_id=debug_id,
    )


def page(paragraphs, number: int = 0, kind: str | None = None, figures=()):
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=il_version_1.Box(0.0, 0.0, 600.0, 800.0)),
        cropbox=il_version_1.Cropbox(box=il_version_1.Box(0.0, 0.0, 600.0, 800.0)),
        pdf_paragraph=list(paragraphs),
        pdf_figure=[il_version_1.PdfFigure(box=il_version_1.Box(*box)) for box in figures],
        page_number=number,
        unit="point",
        page_kind=kind,
    )


def document(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


def kind_with(flag: str, value) -> str | None:
    """A page kind whose policy carries ``flag`` set to ``value``.

    Chosen from the vocabulary at run time rather than named here, so this gate
    holds no page type literal either.
    """
    for page_type in load_taxonomy().page_types:
        if page_type.policy.get(flag) == value:
            return page_type.name
    return None


def detect(docs, language: str = "zh", working_dir: Path | None = None, **kwargs):
    config = kwargs.pop("config", None) or detectors.detector_config()
    context = detectors.build_context(docs, config, language, working_dir, **kwargs)
    return detectors.run_detectors(context), context


def kinds(issues) -> list[str]:
    return [issue.kind for issue in issues]


# --- 01 the configuration -----------------------------------------------------


def check_01a_config_bounds() -> None:
    """Positive 1a: every bound is declared, respected and referred to."""
    faults = []
    raw = raw_config()
    config = parse(raw)
    for key, value in raw.items():
        if key.endswith("_allowed_range") or key == "description":
            continue
        if isinstance(value, int | float) and not isinstance(value, bool):
            if f"{key}_allowed_range" not in raw:
                faults.append(f"{key} declares no allowed range")
    vocabulary = set(raw["severity_vocabulary"])
    for kind, weight in raw["severity"].items():
        if weight not in vocabulary:
            faults.append(f"severity.{kind} is outside the vocabulary")
    declared = {module.KIND for module in detectors.DETECTORS.values()}
    if declared - set(config.severity):
        faults.append(f"kinds with no weight: {sorted(declared - set(config.severity))}")
    for language in config.residue_directions:
        if language not in config.residue_ratios:
            faults.append(f"direction {language} has no ratio")
    record("check_01a_config_bounds", not faults, "; ".join(faults))


def check_01b_profiles_cover_the_vocabulary() -> None:
    """Positive 1b: every declared repair profile has a detector list."""
    config = detectors.detector_config()
    declared = {
        page_type.policy[detector_base.REPAIR_PROFILE_POLICY_FLAG]
        for page_type in load_taxonomy().page_types
    }
    missing = sorted(declared - set(config.profile_detectors))
    unused = sorted(set(config.profile_detectors) - declared)
    faults = []
    if missing:
        faults.append(f"profiles with no detector list: {missing}")
    if unused:
        faults.append(f"detector lists no page type claims: {unused}")
    if config.default_profile not in config.profile_detectors:
        faults.append("the default profile has no detector list")
    record("check_01b_profiles_cover_the_vocabulary", not faults, "; ".join(faults))


def check_01c_config_negative_probes() -> None:
    """Negative 1c: a malformed configuration is refused rather than repaired."""
    probes = {
        "out of range": {"overlap_min_iou": 9.0},
        "unknown script": {"residue_directions": {"zh": "runic"}},
        "direction with no ratio": {"residue_directions": {"zz": "latin"}},
        "severity outside vocabulary": {"severity": {"untranslated_residue": "urgent"}},
        "kind with no severity": {"severity": {"fragment_cluster": "low"}},
        "profile names no detector": {"profile_detectors": {"flow": ["nonsense"]}},
        "default profile absent": {"default_profile": "nowhere"},
        "missing range": {"overlap_min_iou_allowed_range": None},
    }
    faults = []
    for label, patch in probes.items():
        raw = raw_config()
        for key, value in patch.items():
            if value is None:
                raw.pop(key, None)
            else:
                raw[key] = value
        try:
            parse(raw)
        except detectors.DetectorError:
            continue
        except Exception as exc:  # noqa: BLE001 - a wrong exception is a fault
            faults.append(f"{label}: raised {exc!r}")
            continue
        faults.append(f"{label}: accepted")
    record("check_01c_config_negative_probes", not faults, "; ".join(faults))


# --- 02 the detectors ---------------------------------------------------------


def check_02a_residue() -> None:
    """Positive/negative/boundary 2a: residue is directional and floored."""
    config = detectors.detector_config()
    script, ratio = config.residue_rule("zh")
    floor = config.residue_min_script_chars
    latin = "a" * floor
    # Written as an escape rather than as itself, so this file stays ASCII.
    han_character = "\u4e2d"
    han = han_character * floor
    faults = []

    def one(text, language="zh", policy=None, **kwargs):
        docs = document([page([paragraph(text)])])
        context = detectors.build_context(docs, config, language, None, **kwargs)
        if policy is not None:
            context.pages = [
                detector_base.PageView(view.label, view.page, policy)
                for view in context.pages
            ]
        issues = detectors.run_detectors(context)
        return [issue for issue in issues if issue.kind == "untranslated_residue"]

    if not one(latin):
        faults.append("a paragraph of source script was not reported")
    if one(han):
        faults.append("a translated paragraph was reported")
    if one("a" * (floor - 1)):
        faults.append("a paragraph under the character floor was reported")
    # The boundary: a mixture sitting exactly on the declared share reports, one
    # character of the target script more does not.
    total = max(floor * 4, 20)
    residue_chars = int(round(ratio * total))
    on_boundary = "a" * residue_chars + han_character * (total - residue_chars)
    below = "a" * (residue_chars - 1) + han_character * (total - residue_chars + 1)
    if not one(on_boundary):
        faults.append(f"the boundary share {ratio} did not report")
    if one(below):
        faults.append("one character below the boundary reported")
    # Direction: the same Han text is residue in a document finished into the
    # language whose declared residue script it is.
    if "en" in config.residue_directions and not one(han, "en"):
        faults.append("the reverse direction did not report")
    # A page whose kind declares no translation is out of scope. The policy is
    # supplied here rather than taken from a page type, so the guard is asserted
    # whether or not the current vocabulary happens to declare such a type.
    if one(latin, "zh", policy={detector_base.TRANSLATE_POLICY_FLAG: False}):
        faults.append("a page whose policy declares no translation was scanned")
    if not one(latin, "zh", policy={detector_base.TRANSLATE_POLICY_FLAG: True}):
        faults.append("a page whose policy declares translation was not scanned")
    if script != "latin":
        faults.append(f"the declared residue script into zh is {script}")
    record("check_02a_residue", not faults, "; ".join(faults))


def check_02b_fragment() -> None:
    """Positive/negative/boundary 2b: a cluster is short, aligned and close."""
    config = detectors.detector_config()
    count = config.fragment_min_cluster
    height = 10.0
    gap = config.fragment_max_line_gap_ratio * height
    profile = next(
        name
        for name, names in config.profile_detectors.items()
        if "fragment_cluster" in names
    )
    kind = kind_with(detector_base.REPAIR_PROFILE_POLICY_FLAG, profile)
    faults = []

    def stack(number, spacing, font="f", width=100.0, text="short"):
        rows = []
        top = 700.0
        for index in range(number):
            bottom = top - height
            rows.append(
                paragraph(
                    text,
                    (0.0, bottom, width, top),
                    font=font,
                    debug_id=f"d{index}",
                )
            )
            top = bottom - spacing
        return document([page(rows, kind=kind)])

    def clusters(docs):
        issues, _ = detect(docs)
        return [issue for issue in issues if issue.kind == "fragment_cluster"]

    if len(clusters(stack(count, gap / 2))) != 1:
        faults.append("a run at the minimum size was not reported as one cluster")
    if clusters(stack(count - 1, gap / 2)):
        faults.append("a run one member short was reported")
    if not clusters(stack(count, gap)):
        faults.append("the boundary gap did not report")
    if clusters(stack(count, gap * 1.01 + 0.01)):
        faults.append("a run past the boundary gap reported")
    if clusters(
        document(
            [
                page(
                    [
                        paragraph("short", (0.0, 700.0 - i * 20, 100.0, 710.0 - i * 20),
                                  font=f"f{i}")
                        for i in range(count)
                    ],
                    kind=kind,
                )
            ]
        )
    ):
        faults.append("a run set in different fonts reported")
    if clusters(stack(count, gap / 2, text="x" * (config.fragment_max_chars + 1))):
        faults.append("a run of long paragraphs reported")
    record("check_02b_fragment", not faults, "; ".join(faults))


def check_02c_overlap() -> None:
    """Positive/negative/boundary 2c: overlap is measured over the union."""
    config = detectors.detector_config()
    profile = next(
        name
        for name, names in config.profile_detectors.items()
        if "text_figure_overlap" in names
    )
    kind = kind_with(detector_base.REPAIR_PROFILE_POLICY_FLAG, profile)
    faults = []

    def overlaps(figure):
        docs = document(
            [
                page(
                    [paragraph("text", (0.0, 0.0, 100.0, 100.0), label="plain text")],
                    kind=kind,
                    figures=[figure],
                )
            ]
        )
        issues, _ = detect(docs)
        return [issue for issue in issues if issue.kind == "text_figure_overlap"]

    if not overlaps((0.0, 0.0, 100.0, 100.0)):
        faults.append("a figure exactly under the paragraph was not reported")
    if overlaps((500.0, 500.0, 600.0, 600.0)):
        faults.append("a figure elsewhere on the page was reported")
    # A square figure sharing a corner, walked across the bound: at every
    # offset the detector's verdict has to be the arithmetic one, which is a
    # sharper statement than one hand placed boundary and does not depend on
    # where the rounding of a solved offset falls.
    bound = config.overlap_min_iou
    paragraph_box = (0.0, 0.0, 100.0, 100.0)
    # Two 100 by 100 boxes offset by d share (100-d)^2 and cover
    # 2*10000-(100-d)^2, so the share is s/(20000-s) with s the shared area.
    solved = 100.0 - (20000.0 * bound / (1.0 + bound)) ** 0.5
    crossings = 0
    for step in (-2.0, -1.0, -0.05, 0.0, 0.05, 1.0, 2.0):
        offset = solved + step
        figure = (offset, offset, offset + 100.0, offset + 100.0)
        arithmetic = detector_base.intersection_over_union(paragraph_box, figure)
        expected = arithmetic >= bound
        if bool(overlaps(figure)) != expected:
            faults.append(
                f"at offset {offset:.3f} the share is {arithmetic:.4f} and the "
                f"detector said {not expected}"
            )
        crossings += int(expected)
    if crossings in (0, 7):
        faults.append("the walk never crossed the bound, so it tested nothing")
    record("check_02c_overlap", not faults, "; ".join(faults))


def check_02d_escalation_carries() -> None:
    """Positive 2d: the escalation detector restates, and invents nothing."""
    working = _tmp_root / "escalation"
    working.mkdir(parents=True, exist_ok=True)
    reasons = (chain_translation.ESCALATION_TOKEN_BUDGET, chain_translation.ESCALATION_PLACEHOLDER, chain_translation.ESCALATION_CONSERVATION)
    escalated = [
        {
            "chain_id": f"c{index}",
            "reason": reason,
            "detail": f"detail {index}",
            "members": [
                {"debug_id": f"m{index}", "chain_index": 0, "page_index": 0,
                 "layout_label": "plain text"},
                {"debug_id": f"n{index}", "chain_index": 1, "page_index": 1,
                 "layout_label": "plain text"},
            ],
        }
        for index, reason in enumerate(reasons)
    ]
    with (working / chain_translation.REPORT_NAME).open("w", encoding="utf-8") as f:
        json.dump({"escalated": escalated, "counts": {}}, f)

    docs = document(
        [
            page([paragraph("one", debug_id=f"m{index}") for index in range(3)], 0),
            page([paragraph("two", debug_id=f"n{index}") for index in range(3)], 1),
        ]
    )
    issues, _ = detect(docs, working_dir=working)
    raised = [issue for issue in issues if issue.kind == "chain_escalation"]
    faults = []
    if len(raised) != len(escalated):
        faults.append(f"{len(raised)} issue(s) from {len(escalated)} escalation(s)")
    if {issue.evidence["reason"] for issue in raised} != set(reasons):
        faults.append("the reasons were not carried through")
    if {issue.evidence["chain_id"] for issue in raised} != {"c0", "c1", "c2"}:
        faults.append("the chain ids were not carried through")
    for issue in raised:
        if len(issue.paragraph_refs) != 2:
            faults.append(f"{issue.id} resolved {len(issue.paragraph_refs)} member(s)")
    empty = _tmp_root / "escalation_empty"
    empty.mkdir(parents=True, exist_ok=True)
    with (empty / chain_translation.REPORT_NAME).open("w", encoding="utf-8") as f:
        json.dump({"escalated": [], "counts": {}}, f)
    if [issue for issue in detect(docs, working_dir=empty)[0] if issue.kind == "chain_escalation"]:
        faults.append("an empty report produced an issue")
    if [issue for issue in detect(docs)[0] if issue.kind == "chain_escalation"]:
        faults.append("a run with no chain report produced an issue")
    record("check_02d_escalation_carries", not faults, "; ".join(faults))


def check_02e_profile_selects() -> None:
    """Positive 2e: which detectors run is decided by the profile, per page."""
    config = detectors.detector_config()
    faults = []
    for profile, names in sorted(config.profile_detectors.items()):
        kind = kind_with(detector_base.REPAIR_PROFILE_POLICY_FLAG, profile)
        if kind is None:
            faults.append(f"no page type declares profile {profile}")
            continue
        docs = document([page([paragraph("text")], kind=kind)])
        context = detectors.build_context(docs, config, "zh", None)
        selected = {
            name
            for name, views in detectors._selected(context).items()  # noqa: SLF001
            if views
        }
        if selected != set(names):
            faults.append(f"{profile}: ran {sorted(selected)} for {sorted(names)}")
    # A page carrying no kind falls to the declared default rather than to none.
    docs = document([page([paragraph("text")], kind=None)])
    context = detectors.build_context(docs, config, "zh", None)
    fallback = {
        name for name, views in detectors._selected(context).items() if views  # noqa: SLF001
    }
    if fallback != set(config.profile_detectors[config.default_profile]):
        faults.append(f"an unclassified page ran {sorted(fallback)}")
    record("check_02e_profile_selects", not faults, "; ".join(faults))


def check_02f_translation_requirement() -> None:
    """Negative 2f: a detector needing a translation is skipped without one."""
    docs = document([page([paragraph("a" * 40)])])
    issues, context = detect(docs, translation_performed=False)
    requiring = {
        name
        for name, module in detectors.DETECTORS.items()
        if module.REQUIRES_TRANSLATION
    }
    faults = []
    if any(issue.detector in requiring for issue in issues):
        faults.append("a detector needing a translation ran without one")
    for name in requiring:
        if not any(note.startswith(f"{name}:") for note in context.notes):
            faults.append(f"{name} was skipped without saying so")
    if not detect(docs, translation_performed=True)[0]:
        faults.append("the same document reported nothing with a translation")
    record("check_02f_translation_requirement", not faults, "; ".join(faults))


# --- 03 the live evidence -----------------------------------------------------


def load_fixture():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return checkpoint_module.load_checkpoint(FIXTURE)


def check_03a_live_residue() -> None:
    """Positive 3a: the standing fallback line finding is detected."""
    faults = []
    if not FIXTURE.exists() or not FIXTURE_PROVENANCE.exists():
        record("check_03a_live_residue", False, "the frozen fixture is not here")
        return
    with FIXTURE_PROVENANCE.open(encoding="utf-8") as f:
        provenance = json.load(f)
    docs = load_fixture()
    if len(docs.page) != provenance["pages"]:
        faults.append("the fixture does not hold the pages its provenance claims")
    issues, _ = detect(docs, "zh")
    residue = [issue for issue in issues if issue.kind == "untranslated_residue"]
    live = [issue for issue in residue if LIVE_REFERENCE in issue.paragraph_refs]
    if not live:
        faults.append(
            f"{LIVE_REFERENCE} was not detected; residue found at "
            f"{sorted(ref for issue in residue for ref in issue.paragraph_refs)}"
        )
    else:
        finding = live[0]
        if finding.page != LIVE_PAGE:
            faults.append(f"{LIVE_REFERENCE} was reported on page {finding.page}")
        if finding.evidence["layout_label"] != LIVE_LABEL:
            faults.append(
                f"{LIVE_REFERENCE} carries label {finding.evidence['layout_label']}"
            )
        if finding.geometry is None:
            faults.append(f"{LIVE_REFERENCE} was reported with no geometry")
        for key in ("id", "kind", "page", "paragraph_refs", "geometry", "severity",
                    "evidence", "detector", "detected_at_iteration"):
            if key not in finding.as_record():
                faults.append(f"the issue record omits {key}")
    record("check_03a_live_residue", not faults, "; ".join(faults))


def census_rows() -> list[dict]:
    rows = []
    for pdf in sample_pdfs():
        built = artifacts.get_artifacts(pdf, "detected")
        path = built.working_dir / detectors.REPORT_NAME
        with path.open(encoding="utf-8") as f:
            report = json.load(f)
        rows.append({"sample": pdf.stem, "report": report})
    return rows


def write_census(rows: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    names = sorted(detectors.DETECTORS)
    with (OUTPUT_DIR / CENSUS_NAME).open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, sort_keys=True, ensure_ascii=False)
    lines = [
        "# Corpus detection census",
        "",
        "Written by `spec_checks/spec_check_b8.py`, one dry run per sample with",
        "`magazine_detect` up. These runs perform no translation, so the two",
        "detectors that answer about a translated document are skipped and say",
        "so in their sidecar; what the residue detector finds is asserted",
        "against the frozen translated fixture instead.",
        "",
        "| sample | pages scanned | " + " | ".join(names) + " | skipped |",
        "| --- | ---: | " + " | ".join("---:" for _ in names) + " | --- |",
    ]
    for row in rows:
        report = row["report"]
        by_detector = {
            name: sum(1 for issue in report["issues"] if issue["detector"] == name)
            for name in names
        }
        scanned = {
            label
            for pages in report["pages_by_detector"].values()
            for label in pages
        }
        skipped = sorted(note.split(":", 1)[0] for note in report["notes"])
        lines.append(
            f"| {row['sample']} | {len(scanned)} | "
            + " | ".join(str(by_detector[name]) for name in names)
            + f" | {', '.join(skipped) or '-'} |"
        )
    lines += ["", "## What the report only detectors found", ""]
    lines += ["| sample | detector | page | paragraphs | evidence |", "| --- | --- | ---: | --- | --- |"]
    empty = True
    for row in rows:
        for issue in row["report"]["issues"]:
            evidence = issue["evidence"]
            summary = (
                f"members={evidence['member_count']} "
                f"labels={','.join(evidence['layout_labels'])}"
                if issue["kind"] == "fragment_cluster"
                else f"iou={evidence.get('iou')} on {evidence.get('artwork_source')}"
            )
            lines.append(
                f"| {row['sample']} | {issue['detector']} | {issue['page']} | "
                f"{', '.join(issue['paragraph_refs'])} | {summary} |"
            )
            empty = False
    if empty:
        lines.append("| _none_ | | | | |")
    (OUTPUT_DIR / CENSUS_TABLE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_03b_corpus_census() -> None:
    """Positive 3b: every sample produces a sidecar, and it is self consistent."""
    rows = census_rows()
    faults = []
    for row in rows:
        report = row["report"]
        if report["counts"]["issues"] != len(report["issues"]):
            faults.append(f"{row['sample']}: the count and the list disagree")
        by_kind: dict[str, int] = {}
        for issue in report["issues"]:
            by_kind[issue["kind"]] = by_kind.get(issue["kind"], 0) + 1
        if by_kind != report["counts"]["by_kind"]:
            faults.append(f"{row['sample']}: the per kind counts disagree")
        for issue in report["issues"]:
            if issue["severity"] not in raw_config()["severity_vocabulary"]:
                faults.append(f"{row['sample']}: {issue['id']} carries no weight")
                break
        requiring = {
            name
            for name, module in detectors.DETECTORS.items()
            if module.REQUIRES_TRANSLATION
        }
        skipped = {note.split(":", 1)[0] for note in report["notes"]}
        if not requiring <= skipped:
            faults.append(f"{row['sample']}: {sorted(requiring - skipped)} not skipped")
    write_census(rows)
    record("check_03b_corpus_census", not faults and bool(rows), "; ".join(faults[:4]))


# --- 04 the default and the conservation --------------------------------------


def check_04a_switch_down() -> None:
    """Negative 4a: with the switch down nothing is detected and nothing written."""
    docs = load_fixture()

    class Down:
        magazine_detect = False

        def get_working_file_path(self, name: str) -> str:
            return str(_tmp_root / "down" / name)

    (_tmp_root / "down").mkdir(parents=True, exist_ok=True)
    issues = detectors.detect_issues(Down(), docs)
    faults = []
    if issues:
        faults.append("the switch down produced issues")
    if (_tmp_root / "down" / detectors.REPORT_NAME).exists():
        faults.append("the switch down wrote a sidecar")
    record("check_04a_switch_down", not faults, "; ".join(faults))


def check_04b_detection_writes_nothing() -> None:
    """Negative 4b: detecting leaves the document byte for byte as it was."""
    docs = load_fixture()
    before = checkpoint_module.to_checkpoint_xml(docs)
    snapshot = copy.deepcopy(docs)
    issues, _ = detect(docs, "zh")
    after = checkpoint_module.to_checkpoint_xml(docs)
    faults = []
    if before != after:
        faults.append("the serialised document moved")
    if checkpoint_module.to_checkpoint_xml(snapshot) != after:
        faults.append("the document differs from the copy taken before detection")
    if not issues:
        faults.append("nothing was detected, so the assertion proves nothing")
    record("check_04b_detection_writes_nothing", not faults, "; ".join(faults))


# Identities the pipeline mints afresh on every run. Two runs of one pipeline
# over one document never agree on them, and nothing outside the run they were
# minted in reads them, so they are renumbered rather than compared.
_MINTED_ID = re.compile(r'(debug_id|chainId)="([^"]*)"')


def anonymous(path: Path) -> str:
    """One checkpoint with every minted identity renumbered by first sight.

    Renumbered rather than blanked, so two paragraphs that share a chain in one
    run and not in the other still compare unequal.
    """
    seen: dict[tuple[str, str], int] = {}

    def rename(match: re.Match) -> str:
        key = (match.group(1), match.group(2))
        number = seen.setdefault(key, len(seen))
        return f'{match.group(1)}="#{number}"'

    return _MINTED_ID.sub(rename, path.read_text(encoding="utf-8"))


def check_04c_switch_down_run() -> None:
    """Negative 4c: the switch changes the sidecars and no rendered pixel."""
    faults = []
    for pdf in sample_pdfs():
        detecting = artifacts.get_artifacts(pdf, "detected")
        plain = artifacts.get_artifacts(pdf, "grouped")
        if (plain.working_dir / detectors.REPORT_NAME).exists():
            faults.append(f"{pdf.stem}: a sidecar was written with the switch down")
        if not (detecting.working_dir / detectors.REPORT_NAME).exists():
            faults.append(f"{pdf.stem}: no sidecar was written with the switch up")
            continue
        stem = checkpoint_module.checkpoint_stem("typesetting")
        left = detecting.working_dir / f"{stem}.xml"
        right = plain.working_dir / f"{stem}.xml"
        if left.exists() and right.exists():
            # Debug ids are minted per run, so two runs of one pipeline over one
            # document never agree on them; everything else in the serialisation
            # has to agree exactly.
            if anonymous(left) != anonymous(right):
                faults.append(f"{pdf.stem}: the intermediate language moved")
        else:
            faults.append(f"{pdf.stem}: a typesetting checkpoint is missing")
        if detecting.mono_pdf and plain.mono_pdf:
            proc = subprocess.run(  # noqa: S603
                [
                    PYTHON,
                    str(ROOT / "tools" / "render_diff.py"),
                    str(plain.mono_pdf),
                    str(detecting.mono_pdf),
                    "--out",
                    str(_tmp_root / f"render_{pdf.stem}"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                faults.append(f"{pdf.stem}: the render differs, exit={proc.returncode}")
    record("check_04c_switch_down_run", not faults, "; ".join(faults[:4]))


# --- 05 determinism -----------------------------------------------------------


def check_05_determinism() -> None:
    """Positive 5: the same document detected twice gives the same record."""
    records = []
    for _ in range(2):
        docs = load_fixture()
        config = detectors.detector_config()
        context = detectors.build_context(docs, config, "zh", None)
        found = detectors.run_detectors(context)
        records.append(
            json.dumps(detectors.as_record(context, found), sort_keys=True)
        )
    record("check_05_determinism", records[0] == records[1], "the records differ")


# --- 06 the scope -------------------------------------------------------------


def check_06a_no_vocabulary_literals() -> None:
    """Negative 6a: no page type and no repair profile is named in the code."""
    taxonomy = load_taxonomy()
    declared = set(taxonomy.names()) | {
        page_type.policy[detector_base.REPAIR_PROFILE_POLICY_FLAG]
        for page_type in taxonomy.page_types
    }
    faults = []
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in declared:
                faults.append(f"{path.name}:{node.lineno} names {node.value!r}")
    record("check_06a_no_vocabulary_literals", not faults, "; ".join(faults[:5]))


def check_06b_upstream_scope() -> None:
    """Negative 6b: the upstream delta is the two declared hook files."""
    changed = changed_paths()
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES
        and not path.startswith(ALLOWED_PREFIXES)
        and not path.startswith("babeldoc/")
    )
    faults = []
    outside = sorted(set(upstream) - ALLOWED_UPSTREAM)
    if outside:
        faults.append(f"upstream files outside the declared hooks: {outside}")
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    if "corpus/registry.user.json" in changed:
        faults.append("the corpus registry was edited")
    registry = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    for path in upstream:
        if path not in registry:
            faults.append(f"{path} is not registered")
    if detectors.SWITCH not in registry:
        faults.append("the detection switch is not registered")
    record("check_06b_upstream_scope", not faults, "; ".join(faults))


def check_06c_ascii_prose() -> None:
    """Negative 6c: the files this session adds carry no non-ASCII prose."""
    faults = []
    files = [path.relative_to(ROOT).as_posix() for path in sorted(PACKAGE.glob("*.py"))]
    files += [CONFIG, HITL_MODULE, f"spec_checks/{Path(__file__).name}"]
    for relative in files:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{relative}:{number}")
    record("check_06c_ascii_prose", not faults, "; ".join(faults[:5]))


def check_06d_no_request_path() -> None:
    """Negative 6d: no detector can send anything anywhere."""
    forbidden = ("vlm_client", "translator", "requests", "httpx", "urllib", "socket")
    faults = []
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                if any(part in name.split(".") for part in forbidden):
                    faults.append(f"{path.name}:{node.lineno} imports {name}")
    record("check_06d_no_request_path", not faults, "; ".join(faults))


# --- 07 the authorised maintenance --------------------------------------------


def check_07a_gate_cache_ceiling() -> None:
    """Positive 7a: the cache ceiling was raised, and stays inside its bound."""
    with (ROOT / "configs" / "gate_cache.json").open(encoding="utf-8") as f:
        raw = json.load(f)
    low, high = (float(part) for part in raw["gate_cache_max_gb_allowed_range"].split(".."))
    value = float(artifacts.load_cache_config()["gate_cache_max_gb"])
    faults = []
    if value != 16:
        faults.append(f"the ceiling is {value}")
    if not low <= value <= high:
        faults.append("the ceiling is outside its own range")
    record("check_07a_gate_cache_ceiling", not faults, "; ".join(faults))


class WorkingDir:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def get_working_file_path(self, name: str) -> str:
        return str(self.directory / name)


class RulingConfig:
    """A translation config with only what the third hook touches."""

    def __init__(self, directory: Path, export: bool, apply: bool) -> None:
        self.working = WorkingDir(directory)
        self.input_file = "Sample.pdf"
        self.magazine_hitl_export = export
        self.magazine_hitl_apply = apply

    def get_working_file_path(self, name: str) -> str:
        return self.working.get_working_file_path(name)


def write_tracking(directory: Path, records: list[dict]) -> None:
    payload = {"page": [{"paragraph": records}], "cross_page": [], "cross_column": []}
    with (directory / hitl.TRACKING_NAME).open("w", encoding="utf-8") as f:
        json.dump(payload, f)


def check_07b_ruling_reach() -> None:
    """Positive 7b: a ruling that reached nothing says so, loudly and in writing."""
    directory = _tmp_root / "ruling"
    config = RulingConfig(directory, export=True, apply=True)
    # One paragraph offered exactly what it renders, one offered the markup its
    # style runs imply, which is the shape the b7.5 passes measured.
    write_tracking(
        directory,
        [
            {"input": "the reached term", "pdf_unicode": "the reached term"},
            {
                "input": "<style id='1'>Courier</style>{v3}H E UNESCO",
                "pdf_unicode": "CourierT H E UNESCO",
            },
        ],
    )
    draft = hitl._draft(config)  # noqa: SLF001
    draft[hitl.TERMS_SECTION] = [
        {"source": "the reached term", "auto_target": "x"},
        {"source": "CourierT H E UNESCO", "auto_target": "y"},
    ]
    report = hitl._report(config)  # noqa: SLF001
    report[hitl.TERMS_SECTION] = {
        "glossary": hitl.DECISIONS_GLOSSARY,
        "entries": [
            {"source": "the reached term", "target": "A"},
            {"source": "CourierT H E UNESCO", "target": "B"},
        ],
    }

    logs: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record_):
            logs.append(record_.getMessage())

    logger = logging.getLogger("babeldoc.magazine.hitl")
    handler = Capture(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        hitl.after_translate(config)
    finally:
        logger.removeHandler(handler)

    faults = []
    with (directory / hitl.REPORT_NAME).open(encoding="utf-8") as f:
        written = json.load(f)
    matches = {
        entry["source"]: entry["matched_prompt_count"]
        for entry in written[hitl.TERMS_SECTION]["matches"]
    }
    if matches.get("the reached term") != 1:
        faults.append(f"a reached term counted {matches.get('the reached term')}")
    if matches.get("CourierT H E UNESCO") != 0:
        faults.append("a ruling that matched nothing was counted as reaching something")
    if not any("matched no input" in message for message in logs):
        faults.append("no warning was logged for the ruling that reached nothing")
    if hitl.MATCH_DEFINITION not in json.dumps(written):
        faults.append("the report does not say what it counted")

    with (hitl.review_path("Sample")).open(encoding="utf-8") as f:
        exported = json.load(f)
    rows = {row["source"]: row.get(hitl.TRANSLATOR_VIEW_COLUMN) for row in exported[hitl.TERMS_SECTION]}
    if rows.get("the reached term") is not None:
        faults.append("a paragraph offered what it renders carries a view column")
    if "style id" not in (rows.get("CourierT H E UNESCO") or ""):
        faults.append("the offered text was not carried into the draft")
    if hitl.TRANSLATOR_VIEW_COLUMN not in hitl._COLUMNS[hitl.TERMS_SECTION]:  # noqa: SLF001
        faults.append("the review page does not show the column")
    if hitl.TRANSLATOR_VIEW_COLUMN not in hitl.review_html_path("Sample").read_text(
        encoding="utf-8"
    ):
        faults.append("the rendered page does not show the column")

    # With both switches down the hook reads nothing and writes nothing.
    quiet = _tmp_root / "ruling_down"
    down = RulingConfig(quiet, export=False, apply=False)
    write_tracking(quiet, [{"input": "a", "pdf_unicode": "a"}])
    hitl.after_translate(down)
    if (quiet / hitl.REPORT_NAME).exists():
        faults.append("the hook wrote a report with both switches down")
    record("check_07b_ruling_reach", not faults, "; ".join(faults))


def check_07c_table_untracked() -> None:
    """Negative 7c: the regenerated candidate table is no longer in git."""
    _, tracked = git_output(["ls-files", "--", UNTRACKED_TABLE])
    faults = []
    if tracked.strip():
        faults.append(f"{UNTRACKED_TABLE} is still tracked")
    record("check_07c_table_untracked", not faults, "; ".join(faults))


# --- 08 the sweep -------------------------------------------------------------


def check_08_sweep() -> None:
    """Positive 8: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_08_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_08_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks = [
        check_01a_config_bounds,
        check_01b_profiles_cover_the_vocabulary,
        check_01c_config_negative_probes,
        check_02a_residue,
        check_02b_fragment,
        check_02c_overlap,
        check_02d_escalation_carries,
        check_02e_profile_selects,
        check_02f_translation_requirement,
        check_03a_live_residue,
        check_03b_corpus_census,
        check_04a_switch_down,
        check_04b_detection_writes_nothing,
        check_04c_switch_down_run,
        check_05_determinism,
        check_06a_no_vocabulary_literals,
        check_06b_upstream_scope,
        check_06c_ascii_prose,
        check_06d_no_request_path,
        check_07a_gate_cache_ceiling,
        check_07b_ruling_reach,
        check_07c_table_untracked,
        check_08_sweep,
    ]
    try:
        for check in checks:
            if harness.FAST_TIER and check.__name__ in PIPELINE_TIER:
                skip(check.__name__)
                continue
            try:
                check()
            except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
                record(check.__name__, False, f"raised {exc!r}")
        print(f"\nspec_check_b8: {_passed}/{_total} assertions passed")
        for failure in _failures:
            print(f"  - {failure}")
        _timer.write()
        _timer.print_summary()
        artifacts.write_stats("spec_check_b8")
        artifacts.print_stats("spec_check_b8")
    finally:
        pass
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
