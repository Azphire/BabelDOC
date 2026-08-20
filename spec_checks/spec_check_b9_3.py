"""Gate script for batch B9.3, session one: line structure preservation.

Run from the repository root:

    python spec_checks/spec_check_b9_3.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key, makes
no network request and builds no pipeline: every document here is built in this
file, which is what lets the mechanics be asserted one property at a time.

What this batch does. A contents or imprint page does not set running text; it
sets records, one to a line. The paragraph finder assembles the lines of one
layout region into one paragraph, so a record's title, leader dots, folio and
byline reach the translator as one stream and come back laid out as a wrapped
block in which no line is the record it was. On a page whose declared policy
raises ``preserve_line_structure``, ``babeldoc/magazine/line_split.py`` cuts
every paragraph back into its source lines and gives each line a paragraph of
its own.

01 is the record split: a built entry -- title, leader run, folio, then a byline
on the next line -- comes out as two paragraphs cut at the source line boundary,
each keeping the measure of the paragraph it came from and its own band, and
carrying the parent's label, chain fields and a distinct identity.

02 is what is not cut. A line set in two fonts is still one line: the record is
the unit, and the mixed setting inside it is the translator's problem. A formula
is never cut either, and goes whole to the line its first character is on.

03 is the negative that matters most: a page the policy does not declare is
byte for byte the page it was, and so is a page carrying no kind at all.

04 is the conserved quantity. Cutting a paragraph into its lines does not change
how many lines a page has, and the paragraph count grows by exactly the lines
the split produced beyond the paragraphs it consumed.

05 is the chains. The pass runs between the classifier and the chain builder, so
no chain index is left pointing at a paragraph that no longer exists; the types
that declare the flag are not chain eligible in the shipped vocabulary; and a
chain field that was on a paragraph is on every line of it.

06 is the switch: down by default, and with it down this pass reads nothing,
writes no sidecar and returns the document unchanged.

07 is the policy consumption. The flag is declared in the vocabulary and named
in the pass's own configuration; the pass names no page type; a page with no
policy is not declared; and the configuration is refused when a bound is broken
or a flag no type declares is named.

08 is the sidecar, whose per-split record shape is declared in the configuration
and asserted against what the pass builds.

09 is scope: no upstream file, no ground truth, no ruling, and the frozen
evidence guard now covers the tracked evidence under examples/output/, which is
the item this session carried over from b9.2r.

10 is the sweep.

11 is what session two narrowed. A declared page is not records all the way
down -- a contents page can carry an editorial column beside the entries -- and
cutting prose into lines hands the translator half a sentence. Two bounds
narrow the split and both have to hold: the paragraph's mean line must be no
longer than a record's, and its lines must not all be set in the same faces.
The truth table over the two is asserted on built documents, the exemption is
asserted to reach the sidecar with the reason that caused it, and both bounds
are asserted to be live rather than decorative by relaxing each one.

12 is the calibration and the acceptance, replayed from frozen evidence: the
page the bounds were calibrated on is committed as a fixture, both measured
sides and the shipped thresholds are recomputed from it here, and the run
evidence the acceptance rests on is read back and checked for the properties
the batch claims -- nothing outside a declared page, the editorial column left
whole, and every line the translator's floor skipped listed.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from babeldoc.magazine.checkpoint import to_checkpoint_xml  # noqa: E402
from babeldoc.magazine.taxonomy import OPTIONAL_BOOLEAN_POLICY_KEYS  # noqa: E402
from babeldoc.magazine.taxonomy import OPTIONAL_POLICY_DEFAULTS  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import frozen  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build:
# every document it asserts on is a stub it builds itself or evidence a
# batch froze, so it answers in seconds to a couple of minutes and runs on
# every batch.
GATE_SET = "fast"

BATCH_TAG = "batch-b9.3"

PYTHON = sys.executable

RUNNER = ROOT / "spec_checks" / "run_all.py"
MODULE = ROOT / "babeldoc" / "magazine" / "line_split.py"
HOOK = ROOT / "babeldoc" / "magazine" / "hitl.py"
CONFIG = ROOT / "configs" / "line_split.json"
TAXONOMY_CONFIG = ROOT / "configs" / "page_types.json"
HIGH_LEVEL = ROOT / "babeldoc" / "format" / "pdf" / "high_level.py"

# Session two's evidence, all of it committed under the batch's output tree.
EVIDENCE_DIR = ROOT / "examples" / "output" / "b9_3"
CALIBRATION = EVIDENCE_DIR / "calibration.json"
EVIDENCE = EVIDENCE_DIR / "evidence.json"
CALIBRATION_FIXTURE = (
    EVIDENCE_DIR / "fixtures" / "Courier-en.p1.checkpoints.zip"
)
CALIBRATION_MEMBER = "checkpoint.07_page_classifier.xml"

# The policy key this batch introduces, named once here and read from the
# pass's own configuration everywhere else.
FLAG = "preserve_line_structure"

# Paths this session may change.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "spec_checks/",
    "examples/output/b9_3/",
    # The sweep ends by applying the output retention policy, and a batch that
    # falls out of the keep window is archived into this tree before its
    # untracked artefacts are removed. The archive is the policy's own product,
    # written by running the gates rather than by editing anything.
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "plans/PLAN_B9_3.md",
    # The sweep's own log, kept beside the batch trees it reports on.
    "examples/output/run_all.b9_3.log",
}

# Prefixes no session of this batch may touch.
FORBIDDEN_PREFIXES = ("corpus/", "reviews/", "prompts/", "docs/eval/")

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# The font ids the built documents set text in.
BODY_FONT = "body"
LEADER_FONT = "leader"
BYLINE_FONT = "byline"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b9_3")


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


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    """This session's delta: its tag where it exists, the working tree otherwise."""
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


# --- documents built here ------------------------------------------------------


def style(font: str, size: float):
    return il_version_1.PdfStyle(
        font_id=font,
        font_size=size,
        graphic_state=il_version_1.GraphicState(),
    )


def character(text: str, x: float, y: float, width: float, size: float, font: str):
    box = il_version_1.Box(x=x, y=y, x2=x + width, y2=y + size)
    return il_version_1.PdfCharacter(
        char_unicode=text,
        box=box,
        visual_bbox=il_version_1.VisualBbox(box=copy.deepcopy(box)),
        pdf_style=style(font, size),
        advance=width,
        vertical=False,
        xobj_id=-1,
    )


def run_of(text: str, x: float, y: float, size: float, font: str, width: float):
    """One style run laid on one band, as the styling stage leaves it."""
    characters = []
    cursor = x
    for letter in text:
        characters.append(character(letter, cursor, y, width, size, font))
        cursor += width
    box = il_version_1.Box(x=x, y=y, x2=cursor, y2=y + size)
    return il_version_1.PdfParagraphComposition(
        pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
            box=box,
            pdf_style=style(font, size),
            pdf_character=characters,
        )
    )


def paragraph(
    compositions,
    label: str = "plain text",
    debug_id: str = "built",
    chain_id: str | None = None,
    chain_index: int | None = None,
):
    characters = [
        item
        for composition in compositions
        for item in line_split.composition_characters(
            composition, line_split.composition_kind(composition)
        )
    ]
    boxes = [item.box for item in characters]
    box = il_version_1.Box(
        x=min(item.x for item in boxes),
        y=min(item.y for item in boxes),
        x2=max(item.x2 for item in boxes),
        y2=max(item.y2 for item in boxes),
    )
    return il_version_1.PdfParagraph(
        box=box,
        pdf_style=style(BODY_FONT, 10.0),
        pdf_paragraph_composition=list(compositions),
        xobj_id=-1,
        unicode="".join(item.char_unicode or "" for item in characters),
        vertical=False,
        first_line_indent=False,
        debug_id=debug_id,
        layout_label=label,
        layout_id=1,
        render_order=1,
        chain_id=chain_id,
        chain_index=chain_index,
    )


def entry_paragraph(debug_id: str = "entry", **fields):
    """One contents record as the finder leaves it: entry line, then a byline.

    Two source lines twelve points apart, the upper one set as three style runs
    -- title, leader dots, folio -- because that is what a leader in a smaller
    face makes of one line, and the lower one a byline in a third face. This is
    the shape the whole batch exists for.
    """
    title = run_of("Brazil: lessons from the water people", 80.0, 528.0, 10.0, BODY_FONT, 5.0)
    leader = run_of(" ..... ", 265.0, 528.0, 8.0, LEADER_FONT, 3.0)
    folio = run_of("9", 288.0, 528.0, 10.0, BODY_FONT, 5.0)
    byline = run_of("Marcelo Silva de Sousa", 80.0, 516.0, 7.0, BYLINE_FONT, 4.0)
    return paragraph([title, leader, folio, byline], debug_id=debug_id, **fields)


def mixed_line_paragraph():
    """One line only, set in two faces. A record with mixed setting inside it."""
    left = run_of("China: the radiant health", 80.0, 470.0, 10.0, BODY_FONT, 5.0)
    right = run_of(" Yang Sha", 205.0, 470.0, 7.0, BYLINE_FONT, 4.0)
    return paragraph([left, right], debug_id="mixed")


def formula_paragraph():
    """Two lines, the upper one carrying an inline formula that must stay whole."""
    lead = run_of("energy is", 80.0, 400.0, 10.0, BODY_FONT, 5.0)
    formula = il_version_1.PdfParagraphComposition(
        pdf_formula=il_version_1.PdfFormula(
            box=il_version_1.Box(x=130.0, y=400.0, x2=160.0, y2=410.0),
            pdf_character=[
                character("E", 130.0, 400.0, 10.0, 10.0, BODY_FONT),
                character("=", 140.0, 400.0, 10.0, 10.0, BODY_FONT),
                character("m", 150.0, 400.0, 10.0, 10.0, BODY_FONT),
            ],
        )
    )
    tail = run_of("and nothing else", 80.0, 388.0, 10.0, BYLINE_FONT, 5.0)
    return paragraph([lead, formula, tail], debug_id="formula")


# What a prose column reads like, cycled to whatever measure a case asks for.
PROSE = (
    "Indigenous knowledge has long been ignored and is now receiving renewed "
    "interest across the sciences as the consequences of mechanization mount "
)


def block_paragraph(line_chars: int, middle_face: str, debug_id: str):
    """Three source lines of one block, at a chosen measure and setting.

    ``line_chars`` is how many characters each line carries, which is what the
    measure bound reads: a record line is short because the record is short and
    a prose line runs the measure of its column. ``middle_face`` is the face the
    middle line is set in, which is what the setting bound reads: the same face
    as its neighbours is a column, another face is what a leader or a byline
    does to the line it stands on.
    """
    text = PROSE * 8
    runs = []
    for ordinal in range(3):
        piece = text[ordinal * line_chars : (ordinal + 1) * line_chars]
        face = middle_face if ordinal == 1 else BODY_FONT
        runs.append(run_of(piece, 80.0, 400.0 - 12.0 * ordinal, 10.0, face, 5.0))
    return paragraph(runs, debug_id=debug_id)


# The four corners of the two bounds, by the two things they read. Only the
# corner that is short and set in more than one face may be cut.
LONG_LINE_CHARS = 70
SHORT_LINE_CHARS = 20


def truth_table():
    """One built paragraph per corner, with the answer the bounds owe it."""
    return (
        ("short_heterogeneous", SHORT_LINE_CHARS, BYLINE_FONT, None),
        (
            "short_homogeneous",
            SHORT_LINE_CHARS,
            BODY_FONT,
            line_split.REASON_UNIFORM_STYLING,
        ),
        ("long_heterogeneous", LONG_LINE_CHARS, BYLINE_FONT, line_split.REASON_LONG_LINES),
        ("long_homogeneous", LONG_LINE_CHARS, BODY_FONT, line_split.REASON_LONG_LINES),
    )


def page(paragraphs, kind: str | None, number: int = 0):
    built = il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=il_version_1.Box(0.0, 0.0, 631.5, 807.0)),
        cropbox=il_version_1.Cropbox(box=il_version_1.Box(0.0, 0.0, 631.5, 807.0)),
        pdf_paragraph=list(paragraphs),
        page_number=number,
        unit="point",
    )
    built.page_kind = kind
    return built


def document(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


class Config:
    """The attributes this pass reads off a translation configuration."""

    def __init__(self, directory: Path, switch: object = True, minimum: int = 5):
        self.directory = Path(directory)
        self.min_text_length = minimum
        if switch is not None:
            setattr(self, line_split.SWITCH, switch)

    def get_working_file_path(self, name: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        return str(self.directory / name)


def config() -> line_split.LineSplitConfig:
    return line_split.load_line_split_config()


def declared_kinds() -> list[str]:
    """Every page type the shipped vocabulary declares the flag on."""
    settings = config()
    return [
        page_type.name
        for page_type in load_taxonomy().page_types
        if settings.declared(page_type.policy)
    ]


def undeclared_kind() -> str:
    settings = config()
    for page_type in load_taxonomy().page_types:
        if not settings.declared(page_type.policy):
            return page_type.name
    raise AssertionError("every page type declares the flag")


def apply_to(docs, **attributes) -> tuple[dict | None, Path]:
    directory = Path(tempfile.mkdtemp(prefix="spec_b9_3_"))
    result = line_split.apply(
        Config(directory, **attributes), hitl.labeled_pages(docs)
    )
    return result, directory


def line_texts(page_object) -> list[str]:
    return [item.unicode or "" for item in page_object.pdf_paragraph]


# --- 01 the record split -------------------------------------------------------


def check_01a_a_record_is_cut_at_its_source_line() -> None:
    """Positive 1a: an entry and its byline come out as two paragraphs.

    Cut where the source cut it: the leader dots and the folio stay with the
    title they belong to, because they were set on that line, and the byline is
    its own record because it was set on the next one.
    """
    built = document([page([entry_paragraph()], declared_kinds()[0])])
    result, _ = apply_to(built)
    texts = line_texts(built.page[0])
    faults = []
    if len(texts) != 2:
        faults.append(f"the record became {len(texts)} paragraph(s): {texts}")
    else:
        if not texts[0].startswith("Brazil: lessons"):
            faults.append(f"the entry line is {texts[0]!r}")
        if "....." not in texts[0] or not texts[0].rstrip().endswith("9"):
            faults.append(f"the leader and folio left the entry line: {texts[0]!r}")
        if texts[1].strip() != "Marcelo Silva de Sousa":
            faults.append(f"the byline line is {texts[1]!r}")
    if result is None or result["totals"]["split_paragraphs"] != 1:
        faults.append(f"the report counts {result and result['totals']}")
    record("check_01a_a_record_is_cut_at_its_source_line", not faults, "; ".join(faults))


def check_01b_each_line_keeps_the_measure_and_its_own_band() -> None:
    """Positive 1b: the box is the parent's width and the line's own height.

    The measure, because a record was set across the column it stood in and a
    box drawn tight around a short byline would leave its translation nowhere to
    grow. The band, because that is what puts each record back where it was.
    """
    source = entry_paragraph()
    parent = copy.deepcopy(source.box)
    built = document([page([source], declared_kinds()[0])])
    apply_to(built)
    lines = built.page[0].pdf_paragraph
    faults = []
    for line in lines:
        if (line.box.x, line.box.x2) != (parent.x, parent.x2):
            faults.append(
                f"{line.debug_id} measures {line.box.x}..{line.box.x2}, "
                f"parent {parent.x}..{parent.x2}"
            )
    if len(lines) == 2:
        upper, lower = lines
        if not upper.box.y > lower.box.y:
            faults.append("the lines are not in top to bottom order")
        if upper.box.y2 - upper.box.y >= parent.y2 - parent.y:
            faults.append("a line band is as tall as the paragraph it came from")
        if lower.box.y != parent.y or upper.box.y2 != parent.y2:
            faults.append("the split does not span the paragraph it replaced")
    record(
        "check_01b_each_line_keeps_the_measure_and_its_own_band",
        not faults,
        "; ".join(faults),
    )


def check_01c_every_line_carries_the_parents_identity() -> None:
    """Positive 1c: label, chain fields and geometry carry; identity does not.

    A line paragraph is the same paragraph in every respect a later stage reads
    off it, and a different one in the single respect that has to distinguish
    them: two paragraphs sharing a debug id are two paragraphs the translator's
    own bookkeeping cannot tell apart.
    """
    source = entry_paragraph(chain_id="chain-1", chain_index=4)
    built = document([page([source], declared_kinds()[0])])
    apply_to(built)
    lines = built.page[0].pdf_paragraph
    faults = []
    ids = [line.debug_id for line in lines]
    if len(set(ids)) != len(ids) or None in ids:
        faults.append(f"the line identities are {ids}")
    if any(not (item or "").startswith("entry") for item in ids):
        faults.append(f"a line identity does not name its parent: {ids}")
    for line in lines:
        for field in ("layout_label", "layout_id", "xobj_id", "chain_id", "chain_index"):
            if getattr(line, field) != getattr(source, field):
                faults.append(f"{field} is {getattr(line, field)!r} on {line.debug_id}")
    if lines and lines[-1].first_line_indent:
        faults.append("a continuation line carries a first line indent")
    record(
        "check_01c_every_line_carries_the_parents_identity", not faults, "; ".join(faults)
    )


# --- 02 what is not cut --------------------------------------------------------


def check_02a_a_mixed_setting_inside_one_line_is_not_subdivided() -> None:
    """Negative 2a: a line set in two faces is one record, not two.

    The line is the record. What is set inside it in another face -- a byline
    run on the same line as the title, a folio in a smaller size -- is the
    translator's problem and not a boundary.
    """
    source = mixed_line_paragraph()
    before = to_checkpoint_xml(document([page([copy.deepcopy(source)], None)]))
    built = document([page([source], declared_kinds()[0])])
    result, _ = apply_to(built)
    faults = []
    paragraphs = built.page[0].pdf_paragraph
    if len(paragraphs) != 1:
        faults.append(f"one line became {len(paragraphs)} paragraph(s)")
    elif len(paragraphs[0].pdf_paragraph_composition) != 2:
        faults.append(
            f"the style runs became "
            f"{len(paragraphs[0].pdf_paragraph_composition)} composition(s)"
        )
    if result is not None and result["totals"]["split_paragraphs"]:
        faults.append("the report claims a split")
    # And the paragraph is the object it was, not a rebuild that happens to
    # match: a pass that reassembled an untouched paragraph would be rewriting
    # geometry it had no reason to touch.
    after = to_checkpoint_xml(document([page([paragraphs[0]], None)]))
    if after != before:
        faults.append("an unsplit paragraph was rebuilt")
    record(
        "check_02a_a_mixed_setting_inside_one_line_is_not_subdivided",
        not faults,
        "; ".join(faults),
    )


def check_02b_a_formula_is_never_cut() -> None:
    """Negative 2b: an inline formula goes whole to one line.

    A formula is a unit of its own, and half of one is not a smaller formula.
    """
    built = document([page([formula_paragraph()], declared_kinds()[0])])
    apply_to(built)
    paragraphs = built.page[0].pdf_paragraph
    faults = []
    if len(paragraphs) != 2:
        faults.append(f"the paragraph became {len(paragraphs)} line(s)")
    formulas = [
        composition.pdf_formula
        for item in paragraphs
        for composition in item.pdf_paragraph_composition
        if composition.pdf_formula is not None
    ]
    if len(formulas) != 1:
        faults.append(f"{len(formulas)} formula(s) survived the split")
    elif len(formulas[0].pdf_character) != 3:
        faults.append(f"the formula lost characters: {len(formulas[0].pdf_character)}")
    record("check_02b_a_formula_is_never_cut", not faults, "; ".join(faults))


# --- 03 a page the policy does not declare -------------------------------------


def check_03a_an_undeclared_page_is_byte_identical() -> None:
    """Negative 3a: the pass reaches only the pages the policy declares.

    Compared as serialised intermediate language rather than field by field: the
    claim is that nothing at all moved, and a field nobody thought to compare is
    exactly where a leak would be.
    """
    faults = []
    for kind in (undeclared_kind(), None, "a kind no vocabulary declares"):
        built = document([page([entry_paragraph()], kind)])
        before = to_checkpoint_xml(built)
        result, directory = apply_to(built)
        if to_checkpoint_xml(built) != before:
            faults.append(f"the document moved on a page of kind {kind!r}")
        if result is not None and result["totals"]["split_paragraphs"]:
            faults.append(f"a split was recorded on a page of kind {kind!r}")
        if not (directory / line_split.REPORT_NAME).is_file():
            faults.append("the pass wrote no report at all")
    record(
        "check_03a_an_undeclared_page_is_byte_identical", not faults, "; ".join(faults)
    )


def check_03b_a_declared_page_does_not_reach_its_neighbours() -> None:
    """Negative 3b: two pages, one declared, and only that one changes."""
    built = document(
        [
            page([entry_paragraph(debug_id="left")], declared_kinds()[0], number=0),
            page([entry_paragraph(debug_id="right")], undeclared_kind(), number=1),
        ]
    )
    untouched = to_checkpoint_xml(document([page([entry_paragraph(debug_id="right")], None)]))
    apply_to(built)
    faults = []
    if len(built.page[0].pdf_paragraph) != 2:
        faults.append("the declared page was not split")
    neighbour = built.page[1]
    rebuilt = to_checkpoint_xml(document([page(neighbour.pdf_paragraph, None)]))
    if rebuilt != untouched:
        faults.append("the undeclared page moved")
    record(
        "check_03b_a_declared_page_does_not_reach_its_neighbours",
        not faults,
        "; ".join(faults),
    )


# --- 04 the conserved quantity -------------------------------------------------


def check_04a_the_page_holds_the_same_lines_after_the_split() -> None:
    """Positive 4a: splitting redistributes lines, it does not create them.

    Asserted from the pass's own report, which records the count before and
    after each page, and independently from the page: the paragraphs afterwards
    are the paragraphs before plus one for every line beyond the first of each
    paragraph that was cut.
    """
    built = document(
        [
            page(
                [entry_paragraph(debug_id="a"), mixed_line_paragraph(), formula_paragraph()],
                declared_kinds()[0],
            )
        ]
    )
    before = len(built.page[0].pdf_paragraph)
    result, _ = apply_to(built)
    faults = []
    rows = result["pages"]
    if len(rows) != 1:
        faults.append(f"{len(rows)} page row(s)")
    elif rows[0]["lines_before"] != rows[0]["lines_after"]:
        faults.append(
            f"lines {rows[0]['lines_before']} -> {rows[0]['lines_after']}"
        )
    extra = sum(item["lines"] - 1 for item in result["splits"])
    after = len(built.page[0].pdf_paragraph)
    if after != before + extra:
        faults.append(f"paragraphs {before} -> {after}, expected {before + extra}")
    if extra != 2:
        faults.append(f"the built page produced {extra} extra paragraph(s)")
    record(
        "check_04a_the_page_holds_the_same_lines_after_the_split",
        not faults,
        "; ".join(faults),
    )


def check_04b_no_character_is_lost_or_duplicated() -> None:
    """Positive 4b: the split is a partition of the paragraph's characters.

    Identity, not equality: every character object of the paragraph appears in
    exactly one line, so nothing was copied and nothing was dropped.
    """
    source = entry_paragraph()
    original = [id(item) for item in line_split.paragraph_characters(source)]
    built = document([page([source], declared_kinds()[0])])
    apply_to(built)
    seen = [
        id(item)
        for line in built.page[0].pdf_paragraph
        for item in line_split.paragraph_characters(line)
    ]
    faults = []
    if sorted(seen) != sorted(original):
        faults.append(
            f"{len(original)} character(s) in, {len(seen)} out, "
            f"{len(set(seen))} distinct"
        )
    record("check_04b_no_character_is_lost_or_duplicated", not faults, "; ".join(faults))


# --- 05 the chains -------------------------------------------------------------


def check_05a_the_split_runs_before_the_chain_builder() -> None:
    """Positive 5a: the window, read off the pipeline and off the hook.

    The classifier settles the kind this pass reads, and the chain builder
    records paragraph positions this pass would invalidate, so the pass belongs
    between them. The only extension owned call in that window is the page kind
    hook, and inside that hook the pass has to run after a human ruling is
    applied or it would read a kind the run went on to overrule.
    """
    pipeline = text_of(HIGH_LEVEL)
    faults = []
    positions = {
        name: pipeline.find(name)
        for name in (
            "PageClassifier(translation_config)",
            "hitl.after_page_classify(",
            "ChainBuilder(translation_config)",
        )
    }
    if any(value < 0 for value in positions.values()):
        faults.append(f"the pipeline does not carry {positions}")
    elif not (
        positions["PageClassifier(translation_config)"]
        < positions["hitl.after_page_classify("]
        < positions["ChainBuilder(translation_config)"]
    ):
        faults.append(f"the hook is not in the window: {positions}")

    hook = next(
        (
            node
            for node in ast.walk(ast.parse(text_of(HOOK)))
            if isinstance(node, ast.FunctionDef) and node.name == "after_page_classify"
        ),
        None,
    )
    if hook is None:
        faults.append("the hook does not exist")
    else:
        body = ast.unparse(hook)
        lines = body.splitlines()
        calls = [i for i, line in enumerate(lines) if "line_split.apply(" in line]
        rulings = [i for i, line in enumerate(lines) if "apply_page_kinds(" in line]
        if not calls:
            faults.append("the hook does not call the pass")
        elif rulings and min(calls) < max(rulings):
            faults.append("the pass runs before a page kind ruling is applied")
    if line_split.WINDOW_SWITCH != "magazine_page_classify":
        faults.append(f"the window switch is {line_split.WINDOW_SWITCH}")
    record(
        "check_05a_the_split_runs_before_the_chain_builder", not faults, "; ".join(faults)
    )


def check_05b_a_declared_page_is_not_chain_eligible() -> None:
    """Positive 5b: no chain runs through a page whose paragraphs get cut.

    Read off the shipped vocabulary rather than assumed. A type that both
    declared the flag and joined chains would have its chain indices rewritten
    under it, and this is the assertion that says the vocabulary does not.
    """
    faults = []
    kinds = declared_kinds()
    if len(kinds) < 2:
        faults.append(f"the vocabulary declares the flag on {kinds}")
    for page_type in load_taxonomy().page_types:
        if page_type.name in kinds and page_type.policy.get("chain_eligible"):
            faults.append(f"{page_type.name} declares the flag and joins chains")
    record(
        "check_05b_a_declared_page_is_not_chain_eligible", not faults, "; ".join(faults)
    )


# --- 06 the switch -------------------------------------------------------------


def check_06a_the_switch_is_down_by_default() -> None:
    """Negative 6a: with nobody setting it, the pass does nothing at all.

    Three states, because they fail differently: the attribute absent, which is
    how every run that predates this batch reaches the pass; the attribute
    false; and the document, which has to come back byte for byte in both.
    """
    faults = []
    for switch in (None, False):
        built = document([page([entry_paragraph()], declared_kinds()[0])])
        before = to_checkpoint_xml(built)
        result, directory = apply_to(built, switch=switch)
        if result is not None:
            faults.append(f"switch={switch!r} produced a report")
        if to_checkpoint_xml(built) != before:
            faults.append(f"switch={switch!r} changed the document")
        if (directory / line_split.REPORT_NAME).exists():
            faults.append(f"switch={switch!r} wrote a sidecar")
    if line_split.enabled(object()):
        faults.append("an object with no switch reads as enabled")
    record("check_06a_the_switch_is_down_by_default", not faults, "; ".join(faults))


# --- 07 the policy is consumed, and no page type is named ----------------------


def check_07a_the_flag_is_declared_in_the_vocabulary() -> None:
    """Positive 7a: the key exists, defaults false, and is declared on types."""
    raw = json.loads(text_of(TAXONOMY_CONFIG))
    faults = []
    if OPTIONAL_POLICY_DEFAULTS.get(FLAG) is not False:
        faults.append(f"the default is {OPTIONAL_POLICY_DEFAULTS.get(FLAG)!r}")
    if FLAG not in OPTIONAL_BOOLEAN_POLICY_KEYS:
        faults.append("the flag is not validated as a boolean")
    raising = [
        entry["name"]
        for entry in raw["page_types"]
        if entry["policy"].get(FLAG) is True
    ]
    if len(raising) < 2:
        faults.append(f"the vocabulary raises the flag on {raising}")
    for page_type in load_taxonomy().page_types:
        if page_type.name not in raising and page_type.policy[FLAG] is not False:
            faults.append(f"{page_type.name} is {page_type.policy[FLAG]!r}")
    if FLAG not in config().policy_flags:
        faults.append(f"{CONFIG.name} does not name the flag")
    record(
        "check_07a_the_flag_is_declared_in_the_vocabulary", not faults, "; ".join(faults)
    )


def check_07b_the_pass_names_no_page_type() -> None:
    """Negative 7b: the code branches on the policy and never on a kind.

    Over the pass and over the hook it runs from, against every name the shipped
    vocabulary declares. A pass that named one would be a pass whose behaviour
    could not be retuned in the configuration.
    """
    names = [page_type.name for page_type in load_taxonomy().page_types]
    faults = []
    for path in (MODULE, HOOK):
        source = text_of(path)
        for name in names:
            if re.search(rf"['\"]{re.escape(name)}['\"]", source):
                faults.append(f"{path.name} names {name}")
    if "page_kind ==" in text_of(MODULE):
        faults.append("the pass compares a page kind")
    record("check_07b_the_pass_names_no_page_type", not faults, "; ".join(faults))


def check_07c_a_page_with_no_policy_is_not_declared() -> None:
    """Negative 7c: an absent policy is a refusal, not a default of true."""
    settings = config()
    faults = []
    for policy in (None, {}, {"chain_eligible": True}, {FLAG: False}):
        if settings.declared(policy):
            faults.append(f"{policy!r} read as declared")
    if not settings.declared({FLAG: True}):
        faults.append("a raised flag did not read as declared")
    record(
        "check_07c_a_page_with_no_policy_is_not_declared", not faults, "; ".join(faults)
    )


def check_07d_the_configuration_is_bounded() -> None:
    """Negative 7d: a broken bound and an undeclared flag are both refused.

    The shipped file loads, which is the positive half; the three mutations
    below are the negative one, and each of them is a way the pass could
    otherwise be steered by a number nobody declared a range for.
    """
    raw = json.loads(text_of(CONFIG))
    faults = []
    with contextlib.suppress(Exception):
        line_split.parse_line_split_config(raw, CONFIG.name)
    mutations = {
        "out of range": {**raw, "scan_step": 99.0},
        "no declared range": {
            key: value for key, value in raw.items() if key != "scan_step_allowed_range"
        },
        "undeclared flag": {**raw, "policy_flags": ["no_type_declares_this"]},
        "empty vocabulary": {**raw, "policy_flags": []},
    }
    for reason, mutated in mutations.items():
        try:
            line_split.parse_line_split_config(mutated, CONFIG.name)
        except line_split.LineSplitError:
            continue
        except Exception as exc:  # noqa: BLE001 - a wrong error type is a fault
            faults.append(f"{reason} raised {exc!r}")
            continue
        faults.append(f"{reason} was accepted")
    try:
        line_split.parse_line_split_config(raw, CONFIG.name)
    except Exception as exc:  # noqa: BLE001 - the shipped file must load
        faults.append(f"the shipped configuration is refused: {exc!r}")
    record("check_07d_the_configuration_is_bounded", not faults, "; ".join(faults))


# --- 08 the sidecar ------------------------------------------------------------


def check_08a_the_report_has_the_declared_shape() -> None:
    """Positive 8a: one split record carries exactly the declared fields.

    The mapping the batch owes the next session: which paragraph became which
    lines. Its shape is declared in the configuration and the pass refuses to
    write a record that does not match, so the two cannot drift apart silently.
    """
    built = document([page([entry_paragraph()], declared_kinds()[0])])
    result, directory = apply_to(built)
    written = json.loads((directory / line_split.REPORT_NAME).read_text("utf-8"))
    faults = []
    expected = set(config().sidecar_fields)
    for item in written["splits"]:
        if set(item) != expected:
            faults.append(f"a record carries {sorted(item)}, declared {sorted(expected)}")
    if written != result:
        faults.append("the returned record and the written one differ")
    if written["switch"] != line_split.SWITCH:
        faults.append(f"the report names switch {written['switch']}")
    mapping = written["splits"][0]
    if mapping["lines"] != len(mapping["line_paragraphs"]):
        faults.append("the mapping does not list one identity per line")
    if mapping["debug_id"] != "entry":
        faults.append(f"the mapping names {mapping['debug_id']!r} as its source")
    record("check_08a_the_report_has_the_declared_shape", not faults, "; ".join(faults))


def check_08b_a_record_of_the_wrong_shape_is_refused() -> None:
    """Negative 8b: the shape assertion is live, not decorative."""
    settings = config()
    faults = []
    if not settings.sidecar_fields:
        faults.append("the configuration declares no record shape")
    source = text_of(MODULE)
    if "sidecar_fields" not in source:
        faults.append("the pass does not read the declared shape")
    built = document([page([entry_paragraph()], declared_kinds()[0])])
    original = settings.sidecar_fields
    try:
        object.__setattr__(settings, "sidecar_fields", (*original, "invented"))
        try:
            apply_to(built)
            faults.append("a record missing a declared field was written")
        except line_split.LineSplitError:
            pass
    finally:
        object.__setattr__(settings, "sidecar_fields", original)
    record(
        "check_08b_a_record_of_the_wrong_shape_is_refused", not faults, "; ".join(faults)
    )


def check_08c_the_short_line_inventory_is_reported() -> None:
    """Positive 8c: lines the translator's length floor will skip are listed.

    The floor is a translation configuration this batch does not move, so a
    short byline comes out in the source language. What the pass owes is the
    list, so a reader of the output knows which lines were never offered.
    """
    built = document([page([entry_paragraph()], declared_kinds()[0])])
    result, _ = apply_to(built, minimum=30)
    faults = []
    listed = [item["text"] for item in result["short_lines"]]
    if "Marcelo Silva de Sousa" not in listed:
        faults.append(f"the short byline is not listed: {listed}")
    if result["totals"]["short_lines"] != len(listed):
        faults.append("the total and the list disagree")
    if result["min_text_length"] != 30:
        faults.append(f"the report says the floor is {result['min_text_length']}")
    generous, _ = apply_to(
        document([page([entry_paragraph()], declared_kinds()[0])]), minimum=1
    )
    if generous["short_lines"]:
        faults.append("a floor of one still reported short lines")
    record(
        "check_08c_the_short_line_inventory_is_reported", not faults, "; ".join(faults)
    )


# --- 11 what may be cut, and what may not --------------------------------------


def check_11a_the_two_bounds_are_an_and() -> None:
    """Positive 11a: all four corners of the two bounds, on one built page.

    Only the paragraph that is both short lined and set in more than one face
    is cut. Long and mixed is prose with an inset; short and uniform is a
    heading or a wrapped title; long and uniform is a column. Each of the three
    stays whole, which is the assertion the editorial column of a real contents
    page rests on.
    """
    built = document(
        [
            page(
                [
                    block_paragraph(chars, face, name)
                    for name, chars, face, _ in truth_table()
                ],
                declared_kinds()[0],
            )
        ]
    )
    result, _ = apply_to(built)
    faults = []
    split = {item["debug_id"] for item in result["splits"]}
    exempt = {item["debug_id"]: item["reason"] for item in result["exemptions"]}
    for name, _, _, expected in truth_table():
        if expected is None:
            if name not in split:
                faults.append(f"{name} was not cut")
            if name in exempt:
                faults.append(f"{name} was cut and exempted at once")
            continue
        if name in split:
            faults.append(f"{name} was cut")
        elif exempt.get(name) != expected:
            faults.append(f"{name} exempted for {exempt.get(name)!r}, not {expected!r}")
    # The built measures have to sit on the sides the case names, or the table
    # above is testing a bound the documents never reach.
    settings = config()
    for name, chars, face, _ in truth_table():
        examination = line_split.examine(block_paragraph(chars, face, name), settings)
        long_side = examination.mean_line_chars > settings.max_line_chars
        if long_side != (chars == LONG_LINE_CHARS):
            faults.append(
                f"{name} measures {examination.mean_line_chars} against "
                f"a bound of {settings.max_line_chars}"
            )
        if examination.heterogeneous != (face != BODY_FONT):
            faults.append(f"{name} reads heterogeneous={examination.heterogeneous}")
    record("check_11a_the_two_bounds_are_an_and", not faults, "; ".join(faults))


def check_11b_an_exemption_reaches_the_sidecar_with_its_reason() -> None:
    """Positive 11b: what was left whole is as readable as what was cut.

    The record's shape is declared in the configuration like the split record's,
    the reason is a member of the declared vocabulary, and the paragraph itself
    comes out of the pass as the object it went in as.
    """
    source = block_paragraph(LONG_LINE_CHARS, BODY_FONT, "column")
    before = to_checkpoint_xml(document([page([copy.deepcopy(source)], None)]))
    built = document([page([source], declared_kinds()[0])])
    result, directory = apply_to(built)
    written = json.loads((directory / line_split.REPORT_NAME).read_text("utf-8"))
    faults = []
    settings = config()
    expected = set(settings.exemption_fields)
    for item in written["exemptions"]:
        if set(item) != expected:
            faults.append(
                f"an exemption carries {sorted(item)}, declared {sorted(expected)}"
            )
        if item["reason"] not in settings.exemption_reasons:
            faults.append(f"an exemption names {item['reason']!r}")
    if written != result:
        faults.append("the returned record and the written one differ")
    if written["totals"]["exempt_paragraphs"] != len(written["exemptions"]):
        faults.append("the total and the list disagree")
    if written["max_line_chars"] != settings.max_line_chars:
        faults.append("the report does not carry the measure bound it ran under")
    if written["require_style_heterogeneity"] != settings.require_style_heterogeneity:
        faults.append("the report does not carry the setting bound it ran under")
    after = to_checkpoint_xml(document([page(built.page[0].pdf_paragraph, None)]))
    if after != before:
        faults.append("an exempted paragraph was rebuilt")
    record(
        "check_11b_an_exemption_reaches_the_sidecar_with_its_reason",
        not faults,
        "; ".join(faults),
    )


def check_11c_each_bound_is_live_and_bounded() -> None:
    """Negative 11c: relax a bound and the answer moves; break one and it is refused.

    A narrowing nobody can turn off is a narrowing nobody can measure. Each
    bound is relaxed in turn on a paragraph the other one admits, and the
    paragraph then splits; each is then broken and the configuration is refused.
    """
    raw = json.loads(text_of(CONFIG))
    faults = []

    def cut_with(mutation: dict, chars: int, face: str) -> bool:
        settings = line_split.parse_line_split_config({**raw, **mutation}, CONFIG.name)
        built = block_paragraph(chars, face, "probe")
        return line_split.split_paragraph(built, settings) is not None

    if cut_with({}, SHORT_LINE_CHARS, BODY_FONT):
        faults.append("a uniform block is cut under the shipped bounds")
    if not cut_with({"require_style_heterogeneity": 0}, SHORT_LINE_CHARS, BODY_FONT):
        faults.append("the setting bound cannot be relaxed")
    if cut_with({}, LONG_LINE_CHARS, BYLINE_FONT):
        faults.append("a long measure is cut under the shipped bounds")
    if not cut_with({"max_line_chars": 400.0}, LONG_LINE_CHARS, BYLINE_FONT):
        faults.append("the measure bound cannot be relaxed")

    mutations = {
        "measure out of range": {"max_line_chars": 4000.0},
        "setting out of range": {"require_style_heterogeneity": 7},
        "reason nobody implements": {"exemption_reasons": ["long_lines", "invented"]},
    }
    for reason, mutated in mutations.items():
        try:
            line_split.parse_line_split_config({**raw, **mutated}, CONFIG.name)
        except line_split.LineSplitError:
            continue
        except Exception as exc:  # noqa: BLE001 - a wrong error type is a fault
            faults.append(f"{reason} raised {exc!r}")
            continue
        faults.append(f"{reason} was accepted")
    dropped = {key: value for key, value in raw.items() if key != "exemption_fields"}
    try:
        line_split.parse_line_split_config(dropped, CONFIG.name)
        faults.append("a configuration declaring no exemption shape was accepted")
    except line_split.LineSplitError:
        pass
    record("check_11c_each_bound_is_live_and_bounded", not faults, "; ".join(faults))


# --- 12 the calibration and the acceptance, replayed from frozen evidence ------


def check_12a_the_calibration_replays_on_the_frozen_page() -> None:
    """Positive 12a: the bounds are recomputed from the page they were set on.

    The page is a contents grid sharing its measure with an editorial column,
    which is the only shape on which both sides of the bound can be measured at
    once. The fixture is that page as the run left it before the split; this
    recomputes every paragraph's measure and setting, and asserts that the
    shipped bound sits strictly between the widest paragraph it admits and the
    narrowest column it exempts, with the margins the calibration recorded.
    """
    name = "check_12a_the_calibration_replays_on_the_frozen_page"
    missing = frozen.absent([CALIBRATION, CALIBRATION_FIXTURE])
    if missing:
        frozen.skip(name, missing)
        return
    from babeldoc.magazine.checkpoint import load_checkpoint

    recorded = json.loads(text_of(CALIBRATION))
    settings = config()
    document_in = load_checkpoint(CALIBRATION_FIXTURE / CALIBRATION_MEMBER)
    page_in = document_in.page[0]
    measured = []
    for index, paragraph_in in enumerate(page_in.pdf_paragraph or ()):
        examination = line_split.examine(paragraph_in, settings)
        if examination is None:
            continue
        measured.append(
            {
                "paragraph": line_split.paragraph_reference(1, index),
                "lines": len(examination.lines),
                "mean_line_chars": examination.mean_line_chars,
                "heterogeneous": examination.heterogeneous,
                "reason": examination.reason,
            }
        )
    faults = []
    if measured != recorded["paragraphs"]:
        differing = [
            item["paragraph"]
            for item, kept in zip(measured, recorded["paragraphs"], strict=False)
            if item != kept
        ]
        faults.append(
            f"the replay differs from the record on {differing[:4]} "
            f"({len(measured)} measured, {len(recorded['paragraphs'])} recorded)"
        )
    admitted = [item for item in measured if item["reason"] is None]
    exempted_long = [
        item for item in measured if item["reason"] == line_split.REASON_LONG_LINES
    ]
    if not admitted or not exempted_long:
        faults.append("the fixture no longer carries both sides of the bound")
    else:
        widest = max(item["mean_line_chars"] for item in admitted)
        narrowest = min(item["mean_line_chars"] for item in exempted_long)
        if not widest < settings.max_line_chars < narrowest:
            faults.append(
                f"the bound {settings.max_line_chars} does not separate "
                f"{widest} from {narrowest}"
            )
        for key, value in (
            ("widest_admitted", widest),
            ("narrowest_exempted", narrowest),
        ):
            if recorded["measure_bound"][key] != value:
                faults.append(
                    f"{key} replays as {value}, "
                    f"recorded {recorded['measure_bound'][key]}"
                )
        if recorded["measure_bound"]["value"] != settings.max_line_chars:
            faults.append(
                "the calibration records a bound the configuration does not ship"
            )
    if recorded["setting_bound"]["value"] != settings.require_style_heterogeneity:
        faults.append(
            "the calibration records a setting the configuration does not ship"
        )
    record(name, not faults, "; ".join(faults))


def check_12b_the_acceptance_evidence_holds() -> None:
    """Positive 12b: the run evidence says what the batch claims it says.

    Read back rather than recomputed: the arms cost API calls and this gate
    spends nothing. Four claims, and the third is the one that had to be
    weakened to stay true. The split is confined to the declared pages, proved
    on the document as it stands before a single request is built. Every
    editorial paragraph of the shared page was offered to the translator whole,
    and for the measure bound rather than by accident. Downstream of the split
    the confinement does not hold -- pages nobody touched are translated
    differently -- and what is asserted there is that every such page is
    accounted for by a channel the evidence names, not that none exists. And
    every line the length floor skipped is listed.
    """
    name = "check_12b_the_acceptance_evidence_holds"
    missing = frozen.absent([EVIDENCE])
    if missing:
        frozen.skip(name, missing)
        return
    evidence = json.loads(text_of(EVIDENCE))
    faults = []
    for sample, entry in sorted(evidence["samples"].items()):
        if entry["structure_confined_to_declared"] is not True:
            faults.append(
                f"{sample}: the split reached {entry['structure_differing_pages']}, "
                f"declared {entry['declared_pages']}"
            )
        if entry["structure_differing_control"]:
            faults.append(
                f"{sample}: the control moved the document before translation on "
                f"{entry['structure_differing_control']}"
            )
        if entry["split_pages_outside_declared"]:
            faults.append(
                f"{sample}: split recorded on undeclared page(s) "
                f"{entry['split_pages_outside_declared']}"
            )
        for item in entry["short_lines"]:
            if set(item) != {"page", "paragraph", "debug_id", "text"}:
                faults.append(f"{sample}: a short line record carries {sorted(item)}")
        if entry["short_line_count"] != len(entry["short_lines"]):
            faults.append(f"{sample}: the short line total and the list disagree")
    for sample, entry in sorted(evidence["spillover"].items()):
        if entry["unexplained"]:
            faults.append(
                f"{sample}: page(s) {entry['unexplained']} moved with no channel "
                f"reaching them"
            )
    prose = evidence["prose_exemption"]
    if not prose["paragraphs"] or prose["exempted"] != prose["paragraphs"]:
        faults.append(
            f"{prose['exempted']} of {prose['paragraphs']} editorial paragraph(s) "
            f"were left whole"
        )
    if prose["offered_whole"] != prose["paragraphs"]:
        faults.append(
            f"{prose['offered_whole']} of {prose['paragraphs']} reached the "
            f"translator as one text"
        )
    if prose["counterfactual_requests"] <= prose["paragraphs"]:
        faults.append("the counterfactual is not a counterfactual")
    for item in prose["evidence"]:
        if item["reason"] != line_split.REASON_LONG_LINES:
            faults.append(f"{item['paragraph']} was left whole for {item['reason']!r}")
    record(name, not faults, "; ".join(faults))


# --- 09 scope, registration and the frozen prefix ------------------------------


def check_09a_no_upstream_no_ground_truth_no_ruling() -> None:
    """Negative 9a: this session changes extension code, configuration and gates."""
    changed = changed_paths()
    faults = []
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    if stray:
        faults.append(f"outside the declared paths: {stray[:5]}")
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    if upstream:
        faults.append(f"upstream changed: {upstream}")
    for prefix in FORBIDDEN_PREFIXES:
        touched = sorted(path for path in changed if path.startswith(prefix))
        if touched:
            faults.append(f"{prefix} changed: {touched[:3]}")
    record("check_09a_no_upstream_no_ground_truth_no_ruling", not faults, "; ".join(faults))


def check_09b_the_runner_registers_this_gate() -> None:
    """Positive 9b: the sweep runs this gate, after the batch it follows."""
    source = text_of(RUNNER)
    name = Path(__file__).name
    faults = []
    listed = re.findall(r'"(spec_check_[a-z0-9_]+\.py)"', source)
    if name not in listed:
        faults.append("run_all.py does not list this gate")
    elif "spec_check_b9_2r.py" in listed and listed.index(
        "spec_check_b9_2r.py"
    ) > listed.index(name):
        faults.append("this gate runs before the batch it follows")
    record("check_09b_the_runner_registers_this_gate", not faults, "; ".join(faults))


def check_09c_the_frozen_guard_covers_the_output_evidence() -> None:
    """Positive 9c: the read-only guard reaches tracked evidence in examples/output.

    Carried over from b9.2r, which installed the guard over ``docs/eval/`` while
    the loss it answered was in ``examples/output/``. Detection only: the guard
    names the gate that moved a committed byte. Proved on a simulated snapshot
    rather than by moving one, since writing frozen evidence to test the frozen
    evidence guard is the mistake itself.
    """
    faults = []
    if "examples/output/" not in frozen.FROZEN_PREFIXES:
        faults.append(f"the prefixes are {frozen.FROZEN_PREFIXES}")
    paths = frozen.frozen_paths()
    covered = [path for path in paths if path.startswith("examples/output/")]
    if not covered:
        faults.append("no tracked file under examples/output/ is covered")
    if not any(path.startswith("docs/eval/") for path in paths):
        faults.append("the guard lost its original coverage")
    before = frozen.snapshot()
    if covered:
        moved = frozen.changed(before, {**before, covered[0]: "different"})
        if moved != [covered[0]]:
            faults.append(f"a moved byte under examples/output/ reported {moved}")
        if frozen.changed(before, dict(before)):
            faults.append("an unchanged snapshot reported a write")
    record(
        "check_09c_the_frozen_guard_covers_the_output_evidence",
        not faults,
        "; ".join(faults),
    )


def check_09d_the_gate_spends_nothing() -> None:
    """Negative 9d: no pipeline, no translator, no credential, ASCII prose."""
    source = text_of(Path(__file__))
    faults = []
    for forbidden in ("translator", "openai", "high_level", "doclayout"):
        if re.search(rf"^\s*(import|from)\s+.*{forbidden}", source, re.MULTILINE):
            faults.append(f"imports {forbidden}")
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    if suffix in source.replace('"_API" + "_KEY"', ""):
        faults.append("names a credential variable")
    for number, line in enumerate(source.splitlines(), start=1):
        if not line.isascii():
            offenders = [
                unicodedata.name(char, hex(ord(char)))
                for char in line
                if not char.isascii()
            ]
            faults.append(f"line {number}: {offenders[:3]}")
    for path in (MODULE, CONFIG):
        for number, line in enumerate(text_of(path).splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{path.name} line {number} is not ASCII")
    record("check_09d_the_gate_spends_nothing", not faults, "; ".join(faults[:5]))


def check_10_sweep() -> None:
    """Positive 10: every gate passes, this one included."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_10_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(RUNNER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_10_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01a_a_record_is_cut_at_its_source_line,
        check_01b_each_line_keeps_the_measure_and_its_own_band,
        check_01c_every_line_carries_the_parents_identity,
        check_02a_a_mixed_setting_inside_one_line_is_not_subdivided,
        check_02b_a_formula_is_never_cut,
        check_03a_an_undeclared_page_is_byte_identical,
        check_03b_a_declared_page_does_not_reach_its_neighbours,
        check_04a_the_page_holds_the_same_lines_after_the_split,
        check_04b_no_character_is_lost_or_duplicated,
        check_05a_the_split_runs_before_the_chain_builder,
        check_05b_a_declared_page_is_not_chain_eligible,
        check_06a_the_switch_is_down_by_default,
        check_07a_the_flag_is_declared_in_the_vocabulary,
        check_07b_the_pass_names_no_page_type,
        check_07c_a_page_with_no_policy_is_not_declared,
        check_07d_the_configuration_is_bounded,
        check_08a_the_report_has_the_declared_shape,
        check_08b_a_record_of_the_wrong_shape_is_refused,
        check_08c_the_short_line_inventory_is_reported,
        check_11a_the_two_bounds_are_an_and,
        check_11b_an_exemption_reaches_the_sidecar_with_its_reason,
        check_11c_each_bound_is_live_and_bounded,
        check_12a_the_calibration_replays_on_the_frozen_page,
        check_12b_the_acceptance_evidence_holds,
        check_09a_no_upstream_no_ground_truth_no_ruling,
        check_09b_the_runner_registers_this_gate,
        check_09c_the_frozen_guard_covers_the_output_evidence,
        check_09d_the_gate_spends_nothing,
        check_10_sweep,
    ]
    for check in checks:
        name = check.__name__
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(name, False, f"raised {exc!r}")
    print(f"\nspec_check_b9_3: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_b9_3")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
