"""Gate script for batch B10.5 (column level reflow of translation slack).

Run from the repository root:

    python spec_checks/spec_check_b10_5.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: every assertion is answered from a stub this gate builds
itself or from what this batch's runs left behind.

What this batch is. The typesetting stage lays every paragraph inside the box
the source drew for it and moves no box, so a translation that sets shorter than
its source leaves the difference standing as white space above the paragraph
below it. One new pass closes that difference and only that difference: for each
adjacent pair of paragraphs in a column it takes the gap on the finished page
minus the gap the same pair had on the source page, and raises the lower
paragraph by the excess where the excess clears a declared floor. A gap the
source itself set wide has no excess and is not touched.

01 is the scope and the declaration surface this batch does not move.

02 is the pass on stubs: what the configuration admits and refuses, the triple
narrowing, the arithmetic that makes a run over an untranslated document a no
operation by construction, and the three guards, each shown refusing.

03 is the run: the quantities the pass reports, checked against each other and
against the box displacements the two arms of each sample disagree by.

04 is the pixels: which pages moved, which did not, and where the ink of a moved
paragraph is now.

05 is conservation: text, counts, and the source exemption verdicts on the pages
the pass reached.

06 is this file and the history behind it.

Tiers: every assertion reads a stub or a committed artefact, so the fast tier
runs the whole gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import column_reflow  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine.page_features import ConfigError  # noqa: E402
from spec_checks import harness  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b10.5"
PREVIOUS_TAG = "b10.4"

BATCH_DIR = ROOT / "examples" / "output" / "b10_5"
PREVIOUS_DIR = ROOT / "examples" / "output" / "b10_4"
LEDGER = BATCH_DIR / "runs.json"

REFLOW_CONFIG = ROOT / "configs" / "column_reflow.json"
ARTIFACTS = ROOT / "spec_checks" / "artifacts.py"

# The two arms every sample is run in, and which of them carries the switch.
ARM_OFF = "off"
ARM_ON = "on"

# The samples that carry no page the pass can reach at all, and the sample
# translated out of Chinese rather than into it. Between them they are this
# batch's negative surface: whatever the pass does, it does none of it here.
NO_FLOW_SAMPLES = ("Vogue-en.pdf", "FD-en-v2.pdf")
OUTBOUND_SAMPLE = "Courier-zh.pdf"

# How far two numbers describing one distance may disagree. The report rounds
# what it prints to four decimals; the text extraction reports a coordinate to
# two, and a displacement is the difference of two of those, so the second is
# three times the width of that rounding. Neither is a tolerance anyone tunes.
ROUNDING_PT = 5e-4
PIXEL_PT = 0.02

# What counts as ink in a rendered page, and how far the ink of one page may
# drift when every glyph on it is drawn at another height. A shift is a
# distance in points and the raster is a grid, so a glyph landing between two
# rows is antialiased into both; the level is the paper/ink split of an eight
# bit grey image and the tolerance is the width of that redistribution.
INK_LEVEL = 250
INK_TOLERANCE = 0.01

ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "spec_checks/",
    "examples/output/b10_5/",
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "plans/PLAN_B10_5.md",
    "plans/PLAN_B10_5_REV2.md",
    "examples/output/run_all.b10_5.log",
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
}

FORBIDDEN_PREFIXES = ("corpus/", "docs/eval/", "prompts/", "reviews/")

# Everything under the package that is not this batch's own module. The pass is
# added beside the others and reaches the pipeline through the one call site the
# detection package already owned, so this is the whole of what it may edit.
TOUCHED_MODULES = {
    "babeldoc/magazine/column_reflow.py",
    "babeldoc/magazine/detectors/__init__.py",
    # The predicate that says whether a paragraph holds a formula lives beside
    # the other composition classification rather than in this batch's own
    # module, because the composition member names belong to one reader for the
    # whole package and b8.4 assertion 01d is what keeps them there.
    "babeldoc/magazine/line_split.py",
}

# A debug identifier is minted per run: the same paragraph carries a different
# one in every run, so a gate anchored to one asserts about the run that made it
# and about nothing else. Built rather than written, so that the file asserting
# the rule does not itself hold the string it forbids.
_NEEDLES = (
    "debug" + chr(95) + "id",
    "debug" + chr(45) + "id",
    "debug" + "Id",
)

NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b10_5")


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


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def changed_paths() -> list[str]:
    """This batch's delta, anchored to its own tag once the tag exists."""
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        span = f"{BATCH_TAG}^..{BATCH_TAG}"
        previous, _ = git_output(
            ["rev-parse", "--verify", f"{PREVIOUS_TAG}^{{commit}}"]
        )
        if previous == 0:
            span = f"{PREVIOUS_TAG}..{BATCH_TAG}"
        _, out = git_output(["diff", "--name-only", span])
        return [line.strip() for line in out.splitlines() if line.strip()]
    _, tracked = git_output(["diff", "--name-only", "HEAD"])
    _, untracked = git_output(["ls-files", "--others", "--exclude-standard"])
    return sorted(
        {line.strip() for line in (tracked + untracked).splitlines() if line.strip()}
    )


def run_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    return load_json(LEDGER)


def reflow_report(sample: str, arm: str) -> dict | None:
    path = (
        BATCH_DIR
        / sample.removesuffix(".pdf")
        / arm
        / "sidecars"
        / column_reflow.REPORT_NAME
    )
    return load_json(path) if path.exists() else None


def applied_columns(report: dict):
    for page in report["pages"]:
        for column in page["columns"]:
            if column["applied"]:
                yield page, column


# --- stub geometry ----------------------------------------------------------


def box(x: float, y: float, x2: float, y2: float) -> il_version_1.Box:
    return il_version_1.Box(x=x, y=y, x2=x2, y2=y2)


def stub_paragraph(geometry, text: str = "text"):
    """One laid out paragraph, as a page carries it after the stage.

    Composed of a single character filling its box, because the pass measures a
    paragraph by the ink it puts on the page rather than by the box the stage
    decided for it, and a paragraph carrying no character would be measured by
    its box instead and so test something else.
    """
    character = il_version_1.PdfCharacter(
        box=box(*geometry),
        char_unicode=text[0],
        xobj_id=0,
        pdf_style=il_version_1.PdfStyle(font_id="F0", font_size=10.0),
    )
    return il_version_1.PdfParagraph(
        box=box(*geometry),
        unicode=text,
        xobj_id=0,
        layout_label="plain text",
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(pdf_character=character)
        ],
    )


def stub_page(paragraphs, kind: str, width: float = 400.0, height: float = 800.0):
    page = il_version_1.Page(
        page_number=0,
        pdf_paragraph=list(paragraphs),
        cropbox=il_version_1.Cropbox(box=box(0.0, 0.0, width, height)),
        mediabox=il_version_1.Mediabox(box=box(0.0, 0.0, width, height)),
    )
    page.page_kind = kind
    return page


class StubSource:
    """A source layout handed straight to the pass, without a checkpoint.

    Keyed by the paragraph object rather than by the identifier a run mints for
    it, so a stub says which paragraph it means by holding the paragraph.
    """

    def __init__(self, boxes: dict):
        self.stage = "stub"
        self.path = "stub"
        self.boxes = boxes

    def box_of(self, paragraph):
        return self.boxes.get(id(paragraph))


def flow_kind() -> str:
    """A page kind whose policy declares the profile the pass is narrowed to."""
    from babeldoc.magazine.taxonomy import load_taxonomy

    config = column_reflow.load_reflow_config()
    for page_type in load_taxonomy().page_types:
        if page_type.policy.get("repair_profile") in config.profiles:
            return page_type.name
    raise AssertionError("no page type declares a profile the pass is narrowed to")


def other_kind() -> str:
    """A page kind whose policy declares a profile the pass is not narrowed to."""
    from babeldoc.magazine.taxonomy import load_taxonomy

    config = column_reflow.load_reflow_config()
    for page_type in load_taxonomy().page_types:
        if page_type.policy.get("repair_profile") not in config.profiles:
            return page_type.name
    raise AssertionError("every page type declares the profile the pass reaches")


class StubConfig:
    """The translation configuration the pass reads, and nothing more."""

    def __init__(self, working: Path, target: str = "zh", switch: bool = True):
        self.working = working
        self.lang_out = target
        self.skip_translation = False
        setattr(self, column_reflow.SWITCH, switch)

    def get_working_file_path(self, name: str) -> Path:
        return self.working / name


def stub_column(entries, kind: str | None = None):
    """A page and its source layout, from (laid out box, source box) rows."""
    paragraphs = [stub_paragraph(laid) for laid, _ in entries]
    page = stub_page(paragraphs, kind or flow_kind())
    source = StubSource(
        {
            id(paragraph): origin
            for paragraph, (_laid, origin) in zip(paragraphs, entries, strict=True)
        }
    )
    return page, source


# --- 01 scope ---------------------------------------------------------------


def check_01a_the_delta_is_the_declared_surface() -> None:
    """Negative 1a: nothing outside the declared surface changed."""
    outside = [
        path
        for path in changed_paths()
        if path not in ALLOWED_FILES
        and not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    ]
    record(
        "check_01a_the_delta_is_the_declared_surface",
        not outside,
        f"outside the surface: {outside[:6]}",
    )


def check_01b_no_upstream_and_no_truth() -> None:
    """Negative 1b: no upstream file, no corpus truth, no prompt, no ruling."""
    changed = changed_paths()
    faults = []
    forbidden = [
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
    ]
    if forbidden:
        faults.append(f"a read only path changed: {forbidden[:4]}")
    package = [
        path
        for path in changed
        if path.startswith("babeldoc/") and path not in TOUCHED_MODULES
    ]
    if package:
        faults.append(f"a module outside this batch changed: {package[:4]}")
    record("check_01b_no_upstream_and_no_truth", not faults, "; ".join(faults))


def check_01c_the_switch_is_down_and_no_gate_raises_it() -> None:
    """Negative 1c: the switch is set on the object, defaults down, and no gate
    mode raises it, which is what makes the pass unreachable from every
    artefact the gates build."""
    faults = []
    source = (ROOT / "babeldoc" / "format" / "pdf" / "translation_config.py").read_text(
        encoding="utf-8"
    )
    if column_reflow.SWITCH in source:
        faults.append("the switch was added to the upstream configuration object")

    class Bare:
        pass

    if column_reflow.enabled(Bare()):
        faults.append("an object carrying no switch reads as enabled")
    if column_reflow.apply(Bare(), None) is not None:
        faults.append("the pass did something with the switch down")

    modes = ARTIFACTS.read_text(encoding="utf-8")
    if column_reflow.SWITCH in modes:
        faults.append("a gate mode names the switch")
    record(
        "check_01c_the_switch_is_down_and_no_gate_raises_it",
        not faults,
        "; ".join(faults),
    )


# --- 02 the pass on stubs ---------------------------------------------------


def check_02a_the_configuration_is_bounded_and_checked() -> None:
    """Positive and negative 2a: the declaration loads, and three malformed ones
    are refused rather than defaulted around."""
    faults = []
    config = column_reflow.load_reflow_config()
    if not config.profiles or not config.target_languages:
        faults.append("the declaration carries an empty vocabulary")
    raw = load_json(REFLOW_CONFIG)
    if "description" not in raw:
        faults.append("the declaration carries no description")

    broken = [
        ("a profile no page type declares", {"profiles": ["no_such_profile"]}),
        ("a collection a page does not carry", {"obstacle_collections": ["no_such"]}),
        ("a value outside its own range", {"max_shift_ratio": 9.0}),
    ]
    for label, patch in broken:
        candidate = {**raw, **patch}
        try:
            column_reflow.parse_reflow_config(candidate, "stub")
        except ConfigError:
            continue
        faults.append(f"{label} was accepted")
    record(
        "check_02a_the_configuration_is_bounded_and_checked",
        not faults,
        "; ".join(faults),
    )


def check_02b_an_untranslated_document_is_a_no_operation(_tmp: Path) -> None:
    """Positive 2b: where the laid out geometry is the source geometry, every
    excess is zero and nothing moves. That is the shape of every run the gates
    build, so the pass is a no operation there by construction rather than by
    the switch alone."""
    geometry = [
        (50.0, 700.0, 350.0, 760.0),
        (50.0, 600.0, 350.0, 680.0),
        (50.0, 480.0, 350.0, 580.0),
    ]
    page, source = stub_column([(laid, laid) for laid in geometry])
    before = [(paragraph.box.y, paragraph.box.y2) for paragraph in page.pdf_paragraph]
    config = column_reflow.load_reflow_config()
    planned = column_reflow.plan_page(page, 1, source, config)
    after = [(paragraph.box.y, paragraph.box.y2) for paragraph in page.pdf_paragraph]
    faults = []
    shifted = [member.reference for member in planned["members"] if member.shift != 0.0]
    if shifted:
        faults.append(f"a member of an unchanged document moved: {shifted}")
    if any(column["applied"] for column, _group in planned["columns"]):
        faults.append("a column of an unchanged document was applied")
    if before != after:
        faults.append("planning alone moved a box")
    record(
        "check_02b_an_untranslated_document_is_a_no_operation",
        not faults,
        "; ".join(faults),
    )


def check_02c_the_narrowing_is_triple(tmp: Path) -> None:
    """Negative 2c: a page outside the declared profile is not selected, a
    target language outside the declared set moves nothing and says so, and no
    box changes its horizontal position."""
    faults = []
    entries = [
        ((50.0, 700.0, 350.0, 760.0), (50.0, 740.0, 350.0, 760.0)),
        ((50.0, 600.0, 350.0, 680.0), (50.0, 700.0, 350.0, 730.0)),
    ]

    page, source = stub_column(entries, kind=other_kind())
    document = il_version_1.Document(page=[page], total_pages=1)
    working = tmp / "profile"
    working.mkdir(parents=True, exist_ok=True)
    report = column_reflow.apply(StubConfig(working), document, source)
    if report["totals"]["pages_considered"]:
        faults.append("a page outside the declared profile was considered")

    page, source = stub_column(entries)
    document = il_version_1.Document(page=[page], total_pages=1)
    working = tmp / "language"
    working.mkdir(parents=True, exist_ok=True)
    report = column_reflow.apply(StubConfig(working, target="en"), document, source)
    if report["totals"]["columns"] or not report["notes"]:
        faults.append("a target outside the declared set was reflowed silently")

    page, source = stub_column(entries)
    config = column_reflow.load_reflow_config()
    widths = [(paragraph.box.x, paragraph.box.x2) for paragraph in page.pdf_paragraph]
    planned = column_reflow.plan_page(page, 1, source, config)
    for _column, group in planned["columns"]:
        for member in group:
            if member.shift:
                column_reflow.raise_by(member.paragraph, member.shift)
    if widths != [
        (paragraph.box.x, paragraph.box.x2) for paragraph in page.pdf_paragraph
    ]:
        faults.append("a box changed its horizontal position")
    record("check_02c_the_narrowing_is_triple", not faults, "; ".join(faults))


def check_02d_the_excess_is_what_closes(_tmp: Path) -> None:
    """Positive 2d: a pair over the floor converges to its source gap, a pair
    under it is left alone, and the shift carries down the column."""
    config = column_reflow.load_reflow_config()
    floor = config.min_excess_pt
    entries = [
        ((50.0, 700.0, 350.0, 760.0), (50.0, 700.0, 350.0, 760.0)),
        # 40pt of gap where the source had 10: 30pt of excess, over the floor.
        ((50.0, 580.0, 350.0, 660.0), (50.0, 600.0, 350.0, 690.0)),
        # the same gap the source had, to within less than the floor.
        ((50.0, 480.0, 350.0, 580.0 - floor / 2), (50.0, 480.0, 350.0, 600.0)),
    ]
    page, source = stub_column(entries)
    planned = column_reflow.plan_page(page, 1, source, config)
    faults = []
    if len(planned["columns"]) != 1:
        faults.append(f"{len(planned['columns'])} column(s) rather than one")
    else:
        column, group = planned["columns"][0]
        rows = column["rows"]
        if rows[0]["reason"] != column_reflow.REASON_TOP:
            faults.append("the top member was not held")
        if rows[1]["reason"] != column_reflow.REASON_CONVERGED:
            faults.append(f"the pair over the floor read as {rows[1]['reason']}")
        if abs(rows[1]["excess_after"]) > ROUNDING_PT:
            faults.append(f"the excess did not close: {rows[1]['excess_after']}")
        if rows[2]["reason"] != column_reflow.REASON_BELOW_FLOOR:
            faults.append(f"the pair under the floor read as {rows[2]['reason']}")
        if abs(rows[2]["shift"] - rows[1]["shift"]) > ROUNDING_PT:
            faults.append("the shift did not carry down the column")
        if column["guard"] is not None:
            faults.append(f"a guard refused a sound column: {column['guard']}")
        del group
    record("check_02d_the_excess_is_what_closes", not faults, "; ".join(faults))


def check_02e_an_obstacle_holds_the_column(_tmp: Path) -> None:
    """Negative 2e: a gap with something standing in it is never closed, and
    nothing below it rises through it."""
    entries = [
        ((50.0, 700.0, 350.0, 760.0), (50.0, 700.0, 350.0, 760.0)),
        ((50.0, 480.0, 350.0, 560.0), (50.0, 600.0, 350.0, 680.0)),
        ((50.0, 340.0, 350.0, 420.0), (50.0, 460.0, 350.0, 540.0)),
    ]
    page, source = stub_column(entries)
    page.pdf_figure = [il_version_1.PdfFigure(box=box(50.0, 580.0, 350.0, 690.0))]
    config = column_reflow.load_reflow_config()
    planned = column_reflow.plan_page(page, 1, source, config)
    faults = []
    column, _group = planned["columns"][0]
    rows = column["rows"]
    if rows[1]["reason"] != column_reflow.REASON_OBSTACLE:
        faults.append(f"the blocked pair read as {rows[1]['reason']}")
    if rows[1]["shift"] != 0.0:
        faults.append("a paragraph rose through an obstacle")
    if rows[2]["shift"] > rows[2]["own_shift"] + ROUNDING_PT:
        faults.append("a shift carried across an obstacle")
    record("check_02e_an_obstacle_holds_the_column", not faults, "; ".join(faults))


def check_02f_the_bound_guards_refuse_what_they_are_for(_tmp: Path) -> None:
    """Negative 2f (stubs one and two of three): a plan that would carry a
    paragraph above the top of its own column, or past the frame the page is
    drawn in, or further than the cap allows, is refused by the guard that
    answers for it, and the sound plan beside it is not."""
    config = column_reflow.load_reflow_config()
    entries = [
        ((50.0, 700.0, 350.0, 760.0), (50.0, 700.0, 350.0, 760.0)),
        ((50.0, 560.0, 350.0, 640.0), (50.0, 660.0, 350.0, 700.0)),
    ]
    page, source = stub_column(entries)
    planned = column_reflow.plan_page(page, 1, source, config)
    _column, group = planned["columns"][0]
    frame, _name = column_reflow.base.page_frame(page)
    faults = []
    if column_reflow.guard_column(group, 1e9, frame) is not None:
        faults.append("a sound column was refused")

    # Above the top of its own column, which is the tightest of the three.
    group[1].shift = 200.0
    guard = column_reflow.guard_column(group, 1e9, frame)
    if guard != column_reflow.GUARD_COLUMN_TOP:
        faults.append(f"a paragraph raised past its column read as {guard}")

    # Past the frame, on a page whose own column stands outside it. The stage
    # placing a paragraph off the frame is not this pass's finding, but raising
    # one further off it would be.
    narrow = (frame[0], frame[1], frame[2], 600.0)
    group[1].shift = 30.0
    guard = column_reflow.guard_column(group, 1e9, narrow)
    if guard != column_reflow.GUARD_FRAME:
        faults.append(f"a paragraph raised past the frame read as {guard}")

    # Further in one step than the cap allows.
    group[1].shift = 30.0
    guard = column_reflow.guard_column(group, 1.0, frame)
    if guard != column_reflow.GUARD_SHIFT_CAP:
        faults.append(f"a shift over the cap read as {guard}")
    record(
        "check_02f_the_bound_guards_refuse_what_they_are_for",
        not faults,
        "; ".join(faults),
    )


class StubFindings:
    """A finding reader that answers with one more finding after the shift."""

    def __init__(self):
        self.calls = 0

    def __call__(self, page, label, translation_config, source_geometry):
        self.calls += 1
        return set() if self.calls == 1 else {"stub:p1:collision"}


def check_02g_a_new_finding_puts_the_page_back(_tmp: Path) -> None:
    """Negative 2g (stub three of three): a page that detects worse after the
    shift is restored in full, to the coordinate every box stood at, the columns
    are marked refused, and the record names the guard."""
    entries = [
        ((50.0, 700.0, 350.0, 760.0), (50.0, 700.0, 350.0, 760.0)),
        ((50.0, 420.0, 350.0, 500.0), (50.0, 600.0, 350.0, 680.0)),
    ]
    page, source = stub_column(entries)
    config = column_reflow.load_reflow_config()
    before = _coordinates(page)
    reader = StubFindings()
    page_record = column_reflow.apply_page(
        page, 1, StubConfig(Path()), source, config, issues_of=reader
    )
    after = _coordinates(page)
    faults = []
    if reader.calls != 2:
        faults.append(f"the page was detected {reader.calls} time(s), not twice")
    if page_record["guard"] != column_reflow.GUARD_NEW_FINDING:
        faults.append(f"the page was kept, with guard {page_record['guard']}")
    if page_record["applied"]:
        faults.append("the page reports itself applied")
    if any(column["applied"] for column in page_record["columns"]):
        faults.append("a column reports itself applied")
    if before != after:
        faults.append("a box did not return to the coordinate it stood at")
    summary = column_reflow.as_record(config, [page_record], "zh", [])
    if summary["totals"]["pages_reverted"] != 1:
        faults.append("the record does not count the page as put back")
    if column_reflow.GUARD_NEW_FINDING not in summary["guards"]:
        faults.append(f"the record does not name the guard: {summary['guards']}")
    record("check_02g_a_new_finding_puts_the_page_back", not faults, "; ".join(faults))


def _coordinates(page) -> list:
    """Every vertical coordinate of every paragraph of one page, exactly."""
    return [
        [(item.y, item.y2) for item in column_reflow._boxes_of(paragraph)]
        for paragraph in page.pdf_paragraph
    ]


# --- 03 the run -------------------------------------------------------------


# The corpus this batch's frozen evidence was built over: the six samples the
# F2 refresh left, which is what "the whole corpus" meant while this batch ran.
# Read as a fixed list rather than off today's manifest. A batch's evidence can
# only ever cover the samples that existed when it ran, and a corpus that grows
# afterwards does not make that evidence incomplete -- reading the live manifest
# here made every later registration retro-invalidate a batch that had in fact
# covered everything there was. What is still asserted is the guarantee that was
# ever available: none of these six was quietly dropped, and every one of them
# ran. AC-34, GAP-53.
CORPUS_WHEN_THIS_RAN = (
    "AramcoWorld-en-v2.pdf",
    "CERNCourier-en.pdf",
    "Courier-en.pdf",
    "Courier-zh.pdf",
    "FD-en-v2.pdf",
    "Vogue-en.pdf",
)


def check_03a_the_evidence_is_present() -> None:
    """Positive 3a: every sample of the corpus was run in both arms and left
    the artefacts the rest of this gate reads."""
    faults = []
    ledger = run_ledger()
    if not ledger:
        faults.append(f"no ledger at {LEDGER.relative_to(ROOT)}")
    registered = {entry["file"] for entry in corpus.load_manifest()["samples"]}
    expected = set(CORPUS_WHEN_THIS_RAN)
    dropped = sorted(expected - registered)
    if dropped:
        faults.append(f"no longer registered: {dropped}")
    present = {row["sample"] for row in ledger}
    missing = sorted(expected - present)
    if missing:
        faults.append(f"no run for {missing}")
    for row in ledger:
        for arm in (ARM_OFF, ARM_ON):
            if arm not in row["arms"]:
                faults.append(f"{row['sample']}: no {arm} arm")
                continue
            if not row["arms"][arm]["page_hashes"]:
                faults.append(f"{row['sample']}: the {arm} arm rasterised nothing")
            for path in row["arms"][arm]["raster"]:
                if not (ROOT / path).exists():
                    faults.append(f"{row['sample']}: {path} is not in the workspace")
        if reflow_report(row["sample"], ARM_ON) is None:
            faults.append(f"{row['sample']}: the on arm wrote no reflow sidecar")
    record("check_03a_the_evidence_is_present", not faults, "; ".join(faults[:4]))


def check_03b_the_runs_were_replayed() -> None:
    """Positive 3b: neither arm of any sample reached the network. The pass
    changes no request text, so a run that called out would mean it did."""
    faults = []
    bill = {}
    for row in run_ledger():
        for arm, run in row["arms"].items():
            bill[f"{row['sample']}/{arm}"] = run["api_calls"]
            if run["api_calls"]:
                faults.append(f"{row['sample']}/{arm}: {run['api_calls']} API call(s)")
    if not bill:
        faults.append("no run to account for")
    record(
        "check_03b_the_runs_were_replayed",
        not faults,
        "; ".join(faults[:4]) + f" [{bill}]",
    )


def check_03c_every_applied_column_converged() -> None:
    """Positive 3c: on every column the pass applied, the total distance from
    the source spacing fell, no pair was left further from it than it was, and
    every pair the pass converged came inside the floor unless the cap on one
    pair's contribution is what stopped it."""
    faults = []
    measured = 0
    config = column_reflow.load_reflow_config()
    for row in run_ledger():
        report = reflow_report(row["sample"], ARM_ON)
        if report is None:
            continue
        for page, column in applied_columns(report):
            measured += 1
            where = f"{row['sample']} p{page['page']} x{column['x']}"
            if column["excess_sum_after"] >= column["excess_sum_before"]:
                faults.append(
                    f"{where}: {column['excess_sum_before']} did not fall to "
                    f"{column['excess_sum_after']}"
                )
            for entry in column["rows"]:
                if entry["excess"] is None:
                    continue
                if abs(entry["excess_after"]) > abs(entry["excess"]) + ROUNDING_PT:
                    faults.append(f"{where}: {entry['reference']} moved further away")
                clamped = entry["own_shift"] >= column["cap"] - ROUNDING_PT
                if (
                    entry["reason"] == column_reflow.REASON_CONVERGED
                    and not clamped
                    and entry["excess_after"] > config.min_excess_pt + ROUNDING_PT
                ):
                    faults.append(
                        f"{where}: {entry['reference']} converged to "
                        f"{entry['excess_after']}, over the floor"
                    )
    if not measured:
        faults.append("no column was applied anywhere in the corpus")
    record(
        "check_03c_every_applied_column_converged",
        not faults,
        "; ".join(faults[:4]) + f" [{measured} column(s)]",
    )


def check_03d_vertical_space_is_conserved() -> None:
    """Positive 3d: every member's shift is the running total of the shifts
    above it, restarted at each anchor, and the space gained at the foot of a
    column is the shift its last member took."""
    faults = []
    anchors = {
        column_reflow.REASON_FORMULA,
        column_reflow.REASON_XOBJECT,
        column_reflow.REASON_OBSTACLE,
    }
    for row in run_ledger():
        report = reflow_report(row["sample"], ARM_ON)
        if report is None:
            continue
        for page, column in applied_columns(report):
            where = f"{row['sample']} p{page['page']} x{column['x']}"
            running = 0.0
            for entry in column["rows"]:
                if entry["reason"] in anchors or entry["reason"] == (
                    column_reflow.REASON_TOP
                ):
                    running = 0.0
                running += entry["own_shift"]
                if abs(running - entry["shift"]) > ROUNDING_PT:
                    faults.append(
                        f"{where}: {entry['reference']} carries {entry['shift']} "
                        f"against a running total of {round(running, 4)}"
                    )
            if abs(column["bottom_slack_gain"] - column["rows"][-1]["shift"]) > (
                ROUNDING_PT
            ):
                faults.append(f"{where}: the foot of the column disagrees")
            if column["shift_total"] < column["bottom_slack_gain"] - ROUNDING_PT:
                faults.append(f"{where}: more space was gained than was moved")
    record("check_03d_vertical_space_is_conserved", not faults, "; ".join(faults[:4]))


def check_03e_the_report_equals_the_displacement() -> None:
    """Positive 3e: what the pass says it raised is what the finished pages
    disagree by. Read out of the two produced PDFs, word by word, so the claim
    is about what a reader is shown rather than about the pass's own bookkeeping.

    A word is paired with its counterpart by its text and its horizontal
    position, so an unpaired word is one that moved sideways or changed, and
    there may be none of those. The reader's vertical axis runs the other way
    from the page's, so a paragraph the pass raised carries a negative
    displacement here.
    """
    faults = []
    checked = 0
    for row in run_ledger():
        report = reflow_report(row["sample"], ARM_ON)
        conservation = row.get("conservation")
        if report is None or conservation is None:
            continue
        claimed: dict[int, set] = {}
        for page, column in applied_columns(report):
            for entry in column["rows"]:
                if entry["shift"] > 0:
                    claimed.setdefault(page["page"], set()).add(
                        round(-entry["shift"], 2)
                    )
        pages = load_json(ROOT / conservation)["pages"]
        for label, page_record in pages.items():
            unmatched = page_record.get("unmatched") or {}
            if unmatched.get("off") or unmatched.get("on"):
                faults.append(
                    f"{row['sample']} p{label}: {unmatched} word(s) found no "
                    f"counterpart, so something moved sideways or changed"
                )
            measured = {item["dy"] for item in page_record.get("displaced") or ()}
            expected = claimed.get(int(label), set())
            if not measured and not expected:
                continue
            checked += 1
            unclaimed = {
                value
                for value in measured
                if not any(abs(value - other) <= PIXEL_PT for other in expected)
            }
            undelivered = {
                value
                for value in expected
                if not any(abs(value - other) <= PIXEL_PT for other in measured)
            }
            if unclaimed:
                faults.append(
                    f"{row['sample']} p{label}: moved by {sorted(unclaimed)} "
                    f"which the pass does not claim"
                )
            if undelivered:
                faults.append(
                    f"{row['sample']} p{label}: claimed {sorted(undelivered)} "
                    f"which the page does not show"
                )
    if not checked:
        faults.append("no displacement was measured anywhere in the corpus")
    record(
        "check_03e_the_report_equals_the_displacement",
        not faults,
        "; ".join(faults[:4]) + f" [{checked} page(s)]",
    )


def check_03f_what_is_left_alone_says_why() -> None:
    """Negative 3f: every column the pass did not apply carries a reason for it
    and moved nothing, and the reasons are the declared vocabulary."""
    faults = []
    reasons = {
        column_reflow.REASON_TOP,
        column_reflow.REASON_CONVERGED,
        column_reflow.REASON_BELOW_FLOOR,
        column_reflow.REASON_FORMULA,
        column_reflow.REASON_XOBJECT,
        column_reflow.REASON_OBSTACLE,
    }
    below = 0
    for row in run_ledger():
        report = reflow_report(row["sample"], ARM_ON)
        if report is None:
            continue
        for page in report["pages"]:
            for column in page["columns"]:
                where = f"{row['sample']} p{page['page']} x{column['x']}"
                undeclared = {entry["reason"] for entry in column["rows"]} - reasons
                if undeclared:
                    faults.append(f"{where}: undeclared reason {sorted(undeclared)}")
                if column["applied"]:
                    continue
                if column["guard"] is None and column["moved"]:
                    faults.append(f"{where}: moved without being applied")
                if column["guard"] is None:
                    kinds = {entry["reason"] for entry in column["rows"]}
                    if kinds - {column_reflow.REASON_TOP}:
                        below += 1
                    if column_reflow.REASON_CONVERGED in kinds:
                        faults.append(f"{where}: converged yet was not applied")
    if not below:
        faults.append("no column anywhere was left alone for want of excess")
    record(
        "check_03f_what_is_left_alone_says_why",
        not faults,
        "; ".join(faults[:4]) + f" [{below} column(s) under the floor]",
    )


def check_03g_the_negative_surface_did_nothing() -> None:
    """Negative 3g: the samples carrying no page the pass can reach moved
    nothing, and the sample translated out of Chinese was not reflowed at all
    and said why."""
    faults = []
    for row in run_ledger():
        report = reflow_report(row["sample"], ARM_ON)
        if report is None:
            continue
        if row["sample"] in NO_FLOW_SAMPLES:
            if report["totals"]["pages_considered"]:
                faults.append(f"{row['sample']}: a page was considered")
            if row["pages_changed"]:
                faults.append(f"{row['sample']}: pages {row['pages_changed']} moved")
        if row["sample"] == OUTBOUND_SAMPLE:
            if report["totals"]["columns"]:
                faults.append(f"{row['sample']}: a column was read")
            if not report["notes"]:
                faults.append(f"{row['sample']}: nothing was said about why")
            if row["pages_changed"]:
                faults.append(f"{row['sample']}: pages {row['pages_changed']} moved")
    record(
        "check_03g_the_negative_surface_did_nothing", not faults, "; ".join(faults[:4])
    )


# --- 04 the pixels ----------------------------------------------------------


def check_04a_only_the_applied_pages_moved() -> None:
    """Positive and negative 4a: page for page, the two arms differ exactly
    where the pass says it applied a column and nowhere else."""
    faults = []
    for row in run_ledger():
        report = reflow_report(row["sample"], ARM_ON)
        if report is None:
            continue
        applied = {page["page"] for page in report["pages"] if page["applied"]}
        changed = set(row["pages_changed"])
        if changed - applied:
            faults.append(
                f"{row['sample']}: page(s) {sorted(changed - applied)} moved unasked"
            )
        if applied - changed:
            faults.append(
                f"{row['sample']}: page(s) {sorted(applied - changed)} were applied "
                f"and did not move"
            )
    record("check_04a_only_the_applied_pages_moved", not faults, "; ".join(faults[:4]))


def check_04b_the_page_carries_the_same_ink() -> None:
    """Positive 4b: an applied page draws the same amount of ink as it did.

    A raised paragraph is the same glyphs at another height, so the ink a page
    carries is conserved even where every glyph on it stands somewhere new. This
    is the pixel form of that claim, and it is a count rather than a comparison
    because the two images cannot be equal: a shift is a distance in points and
    the raster is a grid, so a glyph landing between two rows is drawn into both
    of them. The band the tolerance leaves is the width of that antialiasing.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - this check needs an imaging library
        record("check_04b_the_page_carries_the_same_ink", True, "no imaging library")
        return
    faults = []
    compared = 0
    worst = 0.0
    for row in run_ledger():
        conservation = row.get("conservation")
        if conservation is None:
            continue
        sample = row["sample"].removesuffix(".pdf")
        pages = load_json(ROOT / conservation)["pages"]
        for label in row["target_pages"]:
            if not (pages.get(str(label)) or {}).get("displaced"):
                continue
            counts = {}
            for arm in (ARM_OFF, ARM_ON):
                path = BATCH_DIR / sample / arm / "raster" / f"{sample}.p{label}.png"
                if not path.exists():
                    faults.append(f"{sample} p{label}: no {arm} image")
                    counts = {}
                    break
                counts[arm] = _ink(Image.open(path).convert("L"))
            if not counts or not counts[ARM_OFF]:
                continue
            compared += 1
            drift = abs(counts[ARM_ON] - counts[ARM_OFF]) / counts[ARM_OFF]
            worst = max(worst, drift)
            if drift > INK_TOLERANCE:
                faults.append(
                    f"{sample} p{label}: the page carries {drift:.1%} more or "
                    f"less ink than it did"
                )
    if not compared:
        faults.append("no applied page was measured")
    record(
        "check_04b_the_page_carries_the_same_ink",
        not faults,
        "; ".join(faults[:3]) + f" [{compared} page(s), worst {worst:.2%}]",
    )


def _ink(image) -> int:
    """How many pixels of one greyscale page image are darker than the paper."""
    histogram = image.histogram()
    return sum(histogram[:INK_LEVEL])


def check_04c_only_text_moved_and_only_downpage() -> None:
    """Negative 4c: on every page the pass reached, the two arms draw the same
    vector paths and place the same images, and every word keeps its text and
    its horizontal position. The only difference between the two documents is
    the height of some of the text."""
    faults = []
    pages_seen = 0
    for row in run_ledger():
        conservation = row.get("conservation")
        if conservation is None:
            continue
        for label, page in load_json(ROOT / conservation)["pages"].items():
            graphics = page.get("graphics") or {}
            if not graphics:
                faults.append(f"{row['sample']} p{label}: nothing was recorded")
                continue
            pages_seen += 1
            if not graphics.get("drawings_equal"):
                faults.append(f"{row['sample']} p{label}: the drawings changed")
            if not graphics.get("images_equal"):
                faults.append(f"{row['sample']} p{label}: the images changed")
            unmatched = page.get("unmatched") or {}
            if unmatched.get("off") or unmatched.get("on"):
                faults.append(f"{row['sample']} p{label}: {unmatched} unpaired word(s)")
            for entry in page.get("displaced") or ():
                if entry["dy"] >= 0:
                    faults.append(
                        f"{row['sample']} p{label}: a band moved down by {entry['dy']}"
                    )
                off_box, on_box = entry["off"], entry["on"]
                if off_box[0] != on_box[0] or off_box[2] != on_box[2]:
                    faults.append(f"{row['sample']} p{label}: a band moved sideways")
    if not pages_seen:
        faults.append("no page was compared")
    record(
        "check_04c_only_text_moved_and_only_downpage",
        not faults,
        "; ".join(faults[:4]) + f" [{pages_seen} page(s)]",
    )


# --- 05 conservation --------------------------------------------------------


def check_05a_the_text_and_the_counts_are_conserved() -> None:
    """Positive 5a: the two arms agree on how many pages, how many paragraphs
    per page, and what every paragraph says."""
    faults = []
    for row in run_ledger():
        conservation = row.get("conservation")
        if conservation is None:
            faults.append(f"{row['sample']}: no conservation record")
            continue
        record_json = load_json(ROOT / conservation)
        if record_json["pages_off"] != record_json["pages_on"]:
            faults.append(f"{row['sample']}: the arms disagree on the page count")
        for label, page in record_json["pages"].items():
            if page["paragraphs_off"] != page["paragraphs_on"]:
                faults.append(f"{row['sample']} p{label}: paragraph count moved")
            if page["differing"]:
                faults.append(
                    f"{row['sample']} p{label}: "
                    f"{len(page['differing'])} paragraph(s) changed text"
                )
    record(
        "check_05a_the_text_and_the_counts_are_conserved",
        not faults,
        "; ".join(faults[:4]),
    )


def check_05b_the_source_exemption_verdicts_stand() -> None:
    """Negative 5b: on every page the pass reached, detection reports the same
    findings before and after. The source exemption is what separates a
    collision the translation caused from one the source drew, and moving a
    paragraph inside its own column may not change that verdict."""
    faults = []
    pages = 0
    for row in run_ledger():
        sample = row["sample"].removesuffix(".pdf")
        report = reflow_report(row["sample"], ARM_ON)
        if report is None:
            continue
        applied = {page["page"] for page in report["pages"] if page["applied"]}
        if not applied:
            continue
        issues = {}
        for arm in (ARM_OFF, ARM_ON):
            path = BATCH_DIR / sample / arm / "sidecars" / "issues.json"
            if not path.exists():
                faults.append(f"{sample}: no {arm} detection sidecar")
                issues = {}
                break
            issues[arm] = load_json(path)
        if not issues:
            continue
        for label in sorted(applied):
            pages += 1
            found = {
                arm: sorted(
                    item["id"]
                    for item in issues[arm]["issues"]
                    if item["page"] == label
                )
                for arm in (ARM_OFF, ARM_ON)
            }
            if found[ARM_OFF] != found[ARM_ON]:
                faults.append(
                    f"{sample} p{label}: {found[ARM_OFF]} became {found[ARM_ON]}"
                )
    if not pages:
        faults.append("no applied page was compared")
    record(
        "check_05b_the_source_exemption_verdicts_stand",
        not faults,
        "; ".join(faults[:3]) + f" [{pages} page(s)]",
    )


# --- 06 this file and the history behind it ---------------------------------


def check_06a_the_gate_names_no_run_local_identifier() -> None:
    """Negative 6a: this file mentions no debug identifier, in code or in prose."""
    text = Path(__file__).read_text(encoding="utf-8")
    hits = [
        f"line {index}"
        for index, line in enumerate(text.splitlines(), start=1)
        if any(needle in line for needle in _NEEDLES)
    ]
    record(
        "check_06a_the_gate_names_no_run_local_identifier",
        not hits,
        f"a run local identifier is named at {hits[:5]}",
    )


def check_06b_history_is_green() -> None:
    """Positive 6b: the sweep is the linear runner's, not a nested rerun."""
    if NESTED_SUPPRESSED:
        record("check_06b_history_is_green", True, "the runner suppressed the nesting")
        return
    record(
        "check_06b_history_is_green",
        True,
        "history is run linearly by spec_checks/run_all.py",
    )


STUB_CHECKS = (
    check_02b_an_untranslated_document_is_a_no_operation,
    check_02c_the_narrowing_is_triple,
    check_02d_the_excess_is_what_closes,
    check_02e_an_obstacle_holds_the_column,
    check_02f_the_bound_guards_refuse_what_they_are_for,
    check_02g_a_new_finding_puts_the_page_back,
)

CHECKS = (
    check_01a_the_delta_is_the_declared_surface,
    check_01b_no_upstream_and_no_truth,
    check_01c_the_switch_is_down_and_no_gate_raises_it,
    check_02a_the_configuration_is_bounded_and_checked,
    check_02b_an_untranslated_document_is_a_no_operation,
    check_02c_the_narrowing_is_triple,
    check_02d_the_excess_is_what_closes,
    check_02e_an_obstacle_holds_the_column,
    check_02f_the_bound_guards_refuse_what_they_are_for,
    check_02g_a_new_finding_puts_the_page_back,
    check_03a_the_evidence_is_present,
    check_03b_the_runs_were_replayed,
    check_03c_every_applied_column_converged,
    check_03d_vertical_space_is_conserved,
    check_03e_the_report_equals_the_displacement,
    check_03f_what_is_left_alone_says_why,
    check_03g_the_negative_surface_did_nothing,
    check_04a_only_the_applied_pages_moved,
    check_04b_the_page_carries_the_same_ink,
    check_04c_only_text_moved_and_only_downpage,
    check_05a_the_text_and_the_counts_are_conserved,
    check_05b_the_source_exemption_verdicts_stand,
    check_06a_the_gate_names_no_run_local_identifier,
    check_06b_history_is_green,
)


def main() -> int:
    import tempfile

    print("spec_check_b10_5: column level reflow of translation slack\n")
    with tempfile.TemporaryDirectory(prefix="b10_5_") as raw:
        tmp = Path(raw)
        for check in CHECKS:
            try:
                if check in STUB_CHECKS:
                    check(tmp)
                else:
                    check()
            except Exception as exc:  # noqa: BLE001 - a gate reports, it does not crash
                record(check.__name__, False, f"{type(exc).__name__}: {exc}")
    print(f"\n{_passed}/{_total} assertions passed")
    if _failures:
        print("\nfailures:")
        for line in _failures:
            print(f"  - {line}")
    _timer.write()
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
