"""Gate script for batch B10.3 (fragment stitch, record grouping, record style).

Run from the repository root:

    python spec_checks/spec_check_b10_3.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: every assertion is answered from a stub this gate builds
itself or from what this batch's replay left behind.

What this batch is. T1 adds a pass that puts a written unit the paragraph finder
left in pieces back together before the translator sees it, under two geometric
rules -- pieces side by side on one line, pieces stacked in one column -- and a
third for a dropped initial that arrived as its own fragment. T2 stops the line
structure pass from assuming a record is a line: inside one paragraph the
distances between lines decide, and a distance far above the paragraph's own
median is where one record ends. T3 gives every paragraph that pass builds the
style its own characters are set in rather than the style of the paragraph it
came out of. T4 takes the minority of a stitched unit to the style its majority
is set in. T5 is the initial rule of T1.

01 is the scope, and the declaration surface the batch says it does not move.

02 is T1 on stubs: each rule, each guard, the face read by name, and the page
exemption.

03 is T1 on the corpus: the five pieces of one sentence on Courier-en p4 and the
two stranded initials on CERNCourier-en p3.

04 is T2: the two branches on stubs, the mechanism invariant on the corpus, and
Courier-en p1, whose blocks are all evenly leaded and whose record account is
therefore the one the batch before it produced.

05 is T3 and T4: the style of every record against the majority of its own
characters, and the account of what that changed.

06 is conservation, the double write, and the request account.

Tiers: every assertion is static, so the fast tier runs the whole gate.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.utils.layout_helper import (  # noqa: E402
    get_char_unicode_string,
)
from babeldoc.magazine import fragment_stitch  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build.
GATE_SET = "fast"

BATCH_TAG = "b10.3"

BATCH_DIR = ROOT / "examples" / "output" / "b10_3"
LEDGER = BATCH_DIR / "runs.json"
BASELINE_DIR = ROOT / "examples" / "output" / "F2"

STITCH_MODULE = ROOT / "babeldoc" / "magazine" / "fragment_stitch.py"
SPLIT_MODULE = ROOT / "babeldoc" / "magazine" / "line_split.py"
STITCH_CONFIG = ROOT / "configs" / "fragment_stitch.json"
SPLIT_CONFIG = ROOT / "configs" / "line_split.json"

TARGETS = {
    "Vogue-en": (3,),
    "CERNCourier-en": (2, 3),
    "Courier-en": (1, 4),
    "AramcoWorld-en-v2": (3,),
    "FD-en-v2": (3,),
}

# The stitch this batch is anchored to, by the pieces the paragraph finder left
# and the sentence they hold between them. Named here rather than searched for:
# a gate that looked for "whatever was stitched" would assert about the run
# rather than against it.
# Anchored by the reference the page gives a paragraph, not by its identity: a
# ``debug_id`` is minted per run and the same paragraph carries a different one
# in every run, which is the miss B10.2's cache key was rebuilt around.
ANCHOR_STITCH = {
    "sample": "Courier-en",
    "page": 4,
    "paragraph": "p4#4",
    "members": 5,
    "sentence": (
        "There are many more examples of how traditional knowledge has proven "
        "its worth, in areas as diverse as water management, agroforestry, "
        "health and fishing."
    ),
}

# The two stranded initials of CERNCourier-en p3, which F2 recorded as defect
# A7 and B10.2 re-attributed to the dropped initial rather than to a collision
# the detector should raise. Each is the first letters of the paragraph beside
# it, drawn as two fragments of one character each.
ANCHOR_INITIALS = {
    "sample": "CERNCourier-en",
    "page": 3,
    "paragraphs": ("p3#11", "p3#22"),
    "members": 3,
    "openings": ("The European Strategy", "The Strategy process"),
}

# The page whose record account this batch does not move, and why it does not:
# every block of it is evenly leaded, so no distance reaches the bound and the
# line is the record, which is what the pass did before this batch. The claim is
# about the *records*, not about the finished page: T3 restyles fifteen of them
# and the page therefore prints differently. See the batch report.
UNMOVED_RECORDS = {"sample": "Courier-en", "page": 1}

ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "spec_checks/",
    "examples/output/b10_3/",
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "plans/PLAN_B10_3.md",
    "plans/PLAN_B10_3_REV2.md",
    "examples/output/run_all.b10_3.log",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
}

FORBIDDEN_PREFIXES = ("corpus/", "reviews/", "prompts/", "tools/", "docs/eval/")

# The declaration layer this batch says it does not move: the policy flag stays
# what it was and no page type gains or loses one. Record grouping is a reading
# of the page, so it needed nothing declared for it.
FROZEN_DECLARATIONS = (
    "configs/page_types.json",
    "babeldoc/magazine/taxonomy.py",
)

BODY_FONT = "body"
OTHER_FONT = "other"

NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b10_3")


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


# --- evidence ------------------------------------------------------------------


def sidecar(sample: str, name: str):
    path = BATCH_DIR / sample / "sidecars" / name
    if not path.exists():
        return None
    return load_json(path)


def stitch_report(sample: str):
    return sidecar(sample, fragment_stitch.REPORT_NAME)


def split_report(sample: str):
    return sidecar(sample, line_split.REPORT_NAME)


def parity_of(sample: str):
    path = BATCH_DIR / sample / "parity.json"
    if not path.exists():
        return None
    return load_json(path)


def conservation_of(sample: str):
    path = BATCH_DIR / sample / "conservation.json"
    if not path.exists():
        return None
    return load_json(path)


def missing_evidence(samples) -> list[str]:
    absent = []
    for sample in samples:
        if stitch_report(sample) is None:
            absent.append(f"{sample}/{fragment_stitch.REPORT_NAME}")
        if split_report(sample) is None:
            absent.append(f"{sample}/{line_split.REPORT_NAME}")
    return absent


def skip(name: str, missing) -> None:
    global _total
    _total += 1
    seconds = _timer.mark(name)
    print(f"SKIPPED: {name}: evidence absent: {sorted(missing)} ({seconds:.2f}s)")


# --- documents built here -------------------------------------------------------


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


def run_of(text: str, x: float, y: float, size: float, font: str, width: float = 5.0):
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


def paragraph(compositions, label="plain text", debug_id="built", font=BODY_FONT,
              size=10.0):
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
        pdf_style=style(font, size),
        pdf_paragraph_composition=list(compositions),
        xobj_id=-1,
        unicode="".join(item.char_unicode or "" for item in characters),
        vertical=False,
        first_line_indent=False,
        debug_id=debug_id,
        layout_label=label,
        layout_id=1,
        render_order=1,
    )


def piece(text: str, x: float, y: float, *, font=BODY_FONT, size=10.0, label="plain text",
          debug_id="piece", width: float = 5.0):
    """One paragraph holding one line of text, as the finder can leave it."""
    return paragraph(
        [run_of(text, x, y, size, font, width)],
        label=label,
        debug_id=debug_id,
        font=font,
        size=size,
    )


def page(paragraphs, kind: str | None = None, number: int = 0, fonts=None,
         xobjects=None):
    built = il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=il_version_1.Box(0.0, 0.0, 631.5, 807.0)),
        cropbox=il_version_1.Cropbox(box=il_version_1.Box(0.0, 0.0, 631.5, 807.0)),
        pdf_paragraph=list(paragraphs),
        page_number=number,
        unit="point",
    )
    built.page_kind = kind
    built.pdf_font = list(fonts or ())
    built.pdf_xobject = list(xobjects or ())
    return built


def font(font_id: str, name: str):
    return il_version_1.PdfFont(font_id=font_id, name=name, xref_id=1, encoding_length=1)


def document(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


class Config:
    """The attributes these passes read off a translation configuration."""

    def __init__(self, directory: Path, stitch: object = True, split: object = True):
        self.directory = Path(directory)
        self.min_text_length = 5
        if stitch is not None:
            setattr(self, fragment_stitch.SWITCH, stitch)
        if split is not None:
            setattr(self, line_split.SWITCH, split)

    def get_working_file_path(self, name: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        return str(self.directory / name)


def stitch_config() -> fragment_stitch.StitchConfig:
    return fragment_stitch.load_stitch_config()


def split_config() -> line_split.LineSplitConfig:
    return line_split.load_line_split_config()


def stitch_to(docs, **attributes):
    directory = Path(tempfile.mkdtemp(prefix="spec_b10_3_"))
    return (
        fragment_stitch.apply(
            Config(directory, **attributes), hitl.labeled_pages(docs)
        ),
        directory,
    )


def split_to(docs, **attributes):
    directory = Path(tempfile.mkdtemp(prefix="spec_b10_3_"))
    return (
        line_split.apply(Config(directory, **attributes), hitl.labeled_pages(docs)),
        directory,
    )


def texts_of(page_object) -> list[str]:
    return [item.unicode or "" for item in page_object.pdf_paragraph]


def declared_kind() -> str:
    settings = stitch_config()
    for page_type in load_taxonomy().page_types:
        if settings.declared(page_type.policy):
            return page_type.name
    raise AssertionError("no page type declares the exemption flag")


def undeclared_kind() -> str:
    settings = stitch_config()
    for page_type in load_taxonomy().page_types:
        if not settings.declared(page_type.policy):
            return page_type.name
    raise AssertionError("every page type declares the exemption flag")


# --- 01 scope --------------------------------------------------------------------


def check_01a_the_delta_is_the_declared_surface() -> None:
    """Negative 1a: nothing changed outside the surface this batch declares."""
    stray = sorted(
        path
        for path in changed_paths()
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "check_01a_the_delta_is_the_declared_surface",
        not stray,
        f"outside the declared surface: {stray}",
    )


def check_01b_no_upstream_no_prompt_no_truth() -> None:
    """Negative 1b: no upstream file, no prompt, no ruling, no ground truth."""
    changed = changed_paths()
    faults = []
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    if upstream:
        faults.append(f"upstream touched: {upstream}")
    forbidden = sorted(
        path for path in changed if path.startswith(FORBIDDEN_PREFIXES)
    )
    if forbidden:
        faults.append(f"a read only tree was written: {forbidden}")
    record(
        "check_01b_no_upstream_no_prompt_no_truth", not faults, "; ".join(faults)
    )


def check_01c_the_declaration_layer_is_untouched() -> None:
    """Negative 1c: the policy flag and its vocabulary are byte unchanged.

    Record grouping is read off the page, so it needed nothing declared for it.
    The first revision of the plan proposed a policy key per page type and was
    withdrawn because one page type carries both shapes at once; this assertion
    is what says the withdrawal held.
    """
    changed = changed_paths()
    moved = sorted(path for path in FROZEN_DECLARATIONS if path in changed)
    faults = []
    if moved:
        faults.append(f"a declaration this batch froze moved: {moved}")
    settings = stitch_config()
    if tuple(settings.policy_flags) != tuple(split_config().policy_flags):
        faults.append(
            "the stitch exemption and the split declaration read different flags: "
            f"{settings.policy_flags} against {split_config().policy_flags}"
        )
    record(
        "check_01c_the_declaration_layer_is_untouched", not faults, "; ".join(faults)
    )


def check_01d_the_pass_names_no_page_type() -> None:
    """Negative 1d: neither pass mentions a page type by name."""
    names = {page_type.name for page_type in load_taxonomy().page_types}
    faults = []
    for path in (STITCH_MODULE, SPLIT_MODULE):
        source = text_of(path)
        named = sorted(name for name in names if f'"{name}"' in source)
        if named:
            faults.append(f"{path.name} names {named}")
    record("check_01d_the_pass_names_no_page_type", not faults, "; ".join(faults))


def check_01e_the_switch_is_down_by_default() -> None:
    """Negative 1e: a configuration that says nothing runs neither new pass."""

    class Bare:
        def get_working_file_path(self, name: str) -> str:  # pragma: no cover
            raise AssertionError("the pass wrote with its switch down")

    docs = document([page([piece("anything at all here", 80.0, 500.0)], None)])
    before = copy.deepcopy(texts_of(docs.page[0]))
    faults = []
    if fragment_stitch.apply(Bare(), hitl.labeled_pages(docs)) is not None:
        faults.append("the stitch ran with no switch set")
    if texts_of(docs.page[0]) != before:
        faults.append("the document changed with the switch down")
    record("check_01e_the_switch_is_down_by_default", not faults, "; ".join(faults))


def check_01f_the_configuration_is_bounded() -> None:
    """Positive 1f: every knob carries a range and every vocabulary is closed."""
    raw = load_json(STITCH_CONFIG)
    faults = []
    # The keys that are neither a bound nor a vocabulary are read from the
    # module that declares them, so a structural key added to the file is
    # skipped here without this list being edited again. B10.4 adds one: the
    # name of the run attribute that lets a declared page be stitched.
    structural = set(fragment_stitch._STRUCTURAL_KEYS)
    for key, value in raw.items():
        if key in structural or key.endswith("_allowed_range"):
            continue
        if isinstance(value, list):
            if not value:
                faults.append(f"{key} is an empty vocabulary")
            continue
        if f"{key}_allowed_range" not in raw:
            faults.append(f"{key} carries no range")
    # A structural key still has to be something: the switch names a run
    # attribute, so it has to be a bare identifier and nothing else.
    for key in structural:
        if key == "description" or key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str) or not value.isidentifier():
            faults.append(f"{key} is not the name of a run attribute")
    split_raw = load_json(SPLIT_CONFIG)
    if "record_gap_ratio_allowed_range" not in split_raw:
        faults.append("record_gap_ratio carries no range")
    else:
        low, _, high = split_raw["record_gap_ratio_allowed_range"].partition("..")
        if float(low) <= 1.0:
            faults.append(
                f"record_gap_ratio may be set to {low}, at or below which every "
                "distance is a boundary and every line is its own record"
            )
        if not float(low) <= split_raw["record_gap_ratio"] <= float(high):
            faults.append("record_gap_ratio is outside its own range")
    record("check_01f_the_configuration_is_bounded", not faults, "; ".join(faults))


# --- 02 T1 on stubs ---------------------------------------------------------------


def broken_word_page(kind=None, left="how t", right="raditional knowledge",
                     right_font=BODY_FONT):
    """Two pieces of one word standing side by side on one line."""
    return page(
        [
            piece(left, 80.0, 500.0, debug_id="left"),
            piece(right, 80.0 + 5.0 * len(left) + 1.0, 500.0, font=right_font,
                  debug_id="right"),
        ],
        kind,
    )


def check_02a_the_inline_rule_joins_a_broken_word() -> None:
    """Positive 2a: two halves of one word become one paragraph, and one blank.

    The page keeps its paragraph count: the member that was merged away is left
    where it stood holding nothing, so every index that named a paragraph before
    the pass still names it.
    """
    docs = document([broken_word_page(undeclared_kind())])
    result, _ = stitch_to(docs)
    texts = texts_of(docs.page[0])
    faults = []
    if len(texts) != 2:
        faults.append(f"the page holds {len(texts)} paragraph(s)")
    elif texts[0].replace(" ", "") != "howtraditionalknowledge":
        faults.append(f"the merged text is {texts[0]!r}")
    elif texts[1] != "":
        faults.append(f"the blanked member still says {texts[1]!r}")
    blanked = docs.page[0].pdf_paragraph[1]
    if blanked.pdf_paragraph_composition:
        faults.append("the blanked member is still drawn")
    # And occupies no space either. The typesetting stage trims a paragraph's
    # lower edge back to clear whatever stands below it, so a blanked member
    # keeping its box squeezes the unit it was merged into and the stage shrinks
    # the text to fit -- which is what the first run of this batch produced on
    # Courier-en p4, at half size.
    if blanked.box is not None:
        faults.append("the blanked member still occupies its band")
    if result is None or result["totals"]["stitches"] != 1:
        faults.append(f"the report counts {result and result['totals']}")
    elif result["totals"]["blanked_paragraphs"] != result["totals"]["merged_paragraphs"] - 1:
        faults.append("the blank count does not follow the merge count")
    record("check_02a_the_inline_rule_joins_a_broken_word", not faults, "; ".join(faults))


def check_02b_two_whole_paragraphs_are_not_joined() -> None:
    """Negative 2b: the unit guard, both halves of it, on the same geometry.

    The geometry that joins two halves of a word joins any two boxes near each
    other, and running text is made of boxes near each other. So the guard is
    asserted twice over: a left piece that finished its sentence is refused
    however close the next one stands, and two pieces neither of which is short
    enough to be a piece are refused as well.
    """
    settings = stitch_config()
    long_text = "x" * (settings.max_fragment_chars + 5)
    cases = (
        ("ends its sentence", "the end.", "and the next thing"),
        ("neither is a piece", long_text, long_text),
    )
    faults = []
    for what, left, right in cases:
        docs = document([broken_word_page(undeclared_kind(), left=left, right=right)])
        result, _ = stitch_to(docs)
        if result is None or result["totals"]["stitches"]:
            faults.append(f"{what}: the pair was joined")
    record("check_02b_two_whole_paragraphs_are_not_joined", not faults, "; ".join(faults))


def check_02c_the_face_is_read_by_name_not_by_id() -> None:
    """Positive 2c: one typeface reached under two ids is one face.

    A font id is scoped to the page or to the form that draws it, so the same
    typeface carries a different id inside every form. On CERNCourier-en p3 the
    two halves of one word carry ``TT3`` and ``C2_0`` and one name, and an id
    comparison would call them two faces and refuse the join.
    """
    faults = []
    fonts = [font(BODY_FONT, "Merriweather"), font(OTHER_FONT, "Merriweather")]
    built = broken_word_page(undeclared_kind(), right_font=OTHER_FONT)
    built.pdf_font = fonts
    result, _ = stitch_to(document([built]))
    if result is None or result["totals"]["stitches"] != 1:
        faults.append("two ids of one typeface were not joined")

    apart = broken_word_page(undeclared_kind(), right_font=OTHER_FONT)
    apart.pdf_font = [font(BODY_FONT, "Merriweather"), font(OTHER_FONT, "Helvetica")]
    result, _ = stitch_to(document([apart]))
    if result is None or result["totals"]["stitches"]:
        faults.append("two typefaces were joined")
    record(
        "check_02c_the_face_is_read_by_name_not_by_id", not faults, "; ".join(faults)
    )


def check_02d_the_vertical_rule_chains_a_column() -> None:
    """Positive 2d: pieces stacked in one column become one unit.

    Inline first and vertical over what inline produced, which is the order the
    Courier-en p4 case needs: two rows of two pieces each have no horizontal
    overlap with each other until each row is whole.
    """
    built = page(
        [
            piece("There are many more examples of how t", 80.0, 500.0, debug_id="a"),
            piece("raditional knowledge", 268.0, 500.0, debug_id="b"),
            piece("has proven its worth, in areas as", 80.0, 488.0, debug_id="c"),
            piece("diverse as water", 248.0, 488.0, debug_id="d"),
        ],
        undeclared_kind(),
    )
    docs = document([built])
    result, _ = stitch_to(docs)
    texts = texts_of(docs.page[0])
    faults = []
    if result is None or result["totals"]["stitches"] != 1:
        faults.append(f"the report counts {result and result['totals']}")
    elif result["stitches"][0]["members"] != 4:
        faults.append(f"the unit holds {result['stitches'][0]['members']} member(s)")
    elif result["stitches"][0]["rule"] != fragment_stitch.RULE_VERTICAL:
        faults.append(f"the rule is {result['stitches'][0]['rule']}")
    # The pieces in order, not a particular spacing between them: the text of a
    # merged unit is written by the pipeline's own character joiner, which
    # inserts a space between two characters only where their boxes say a line
    # ended, and two boxes that overlap vertically do not say so. See the batch
    # report for the one case on the corpus where that reads as a missing space.
    cursor = 0
    for fragment in ("how t", "raditional knowledge", "has proven", "water"):
        found = texts[0].find(fragment, cursor) if texts else -1
        if found < 0:
            faults.append(f"{fragment!r} is not in the merged text {texts[0]!r}")
            break
        cursor = found + len(fragment)
    if len(texts) != 4 or any(texts[1:]):
        faults.append("the members were not left in place holding nothing")
    record(
        "check_02d_the_vertical_rule_chains_a_column", not faults, "; ".join(faults)
    )


def check_02e_a_declared_page_is_never_stitched() -> None:
    """Negative 2e: a page whose lines are records is left alone entirely.

    Joining two paragraphs of such a page would undo the thing the line
    structure pass exists to do, so the exemption is the whole page rather than
    a narrowing inside it.
    """
    docs = document([broken_word_page(declared_kind())])
    before = copy.deepcopy(texts_of(docs.page[0]))
    result, _ = stitch_to(docs)
    faults = []
    if result is None or result["totals"]["stitches"]:
        faults.append("a declared page was stitched")
    if texts_of(docs.page[0]) != before:
        faults.append("a declared page was changed")
    if result is not None and result["totals"]["exempt_pages"] != 1:
        faults.append("the exemption was not recorded")
    record(
        "check_02e_a_declared_page_is_never_stitched", not faults, "; ".join(faults)
    )


def check_02f_page_furniture_is_not_stitched() -> None:
    """Negative 2f: a fragmented printing slug is left fragmented.

    Furniture comes apart as readily as running text and putting it together
    repairs nothing, because nothing translates it. What the stitch exists for
    is a broken translation unit, and the labels it may act on are declared.
    """
    settings = stitch_config()
    faults = []
    if "abandon" in settings.layout_labels:
        faults.append("the label vocabulary admits page furniture")
    built = broken_word_page(undeclared_kind())
    for item in built.pdf_paragraph:
        item.layout_label = "abandon"
    result, _ = stitch_to(document([built]))
    if result is None or result["totals"]["stitches"]:
        faults.append("furniture was stitched")
    record("check_02f_page_furniture_is_not_stitched", not faults, "; ".join(faults))


# --- 03 T1 on the corpus ----------------------------------------------------------


def check_03a_the_five_pieces_reach_the_translator_as_one_request() -> None:
    """Positive 3a: Courier-en p4's broken sentence is one request holding it.

    The anchor case of the batch. Five paragraphs, two of them labelled in a way
    the translator never sends at all, holding one sentence between them. The
    assertion is not that the request is the sentence -- the fifth piece runs on
    past its full stop -- but that the sentence is *in* one request, whole.
    """
    name = "check_03a_the_five_pieces_reach_the_translator_as_one_request"
    sample = ANCHOR_STITCH["sample"]
    report = stitch_report(sample)
    parity = parity_of(sample)
    if report is None or parity is None:
        skip(name, [f"{sample}/fragment_stitch.report.json", f"{sample}/parity.json"])
        return
    faults = []
    found = [
        item
        for item in report["stitches"]
        if item["page"] == ANCHOR_STITCH["page"]
        and item["paragraph"] == ANCHOR_STITCH["paragraph"]
        and item["members"] == ANCHOR_STITCH["members"]
    ]
    if not found:
        faults.append(
            f"{ANCHOR_STITCH['paragraph']} did not take {ANCHOR_STITCH['members']} "
            "pieces; the page records "
            f"{[(item['paragraph'], item['members']) for item in report['stitches'] if item['page'] == ANCHOR_STITCH['page']]}"
        )
    else:
        stitched = found[0]
        if ANCHOR_STITCH["sentence"] not in " ".join(stitched["text"].split()):
            faults.append(f"the merged text does not hold the sentence: {stitched['text'][:120]!r}")
        if stitched["rule"] != fragment_stitch.RULE_VERTICAL:
            faults.append(f"the rule recorded is {stitched['rule']}")
        carrying = [
            text
            for text in parity["introduced"]
            if ANCHOR_STITCH["sentence"] in " ".join(text.split())
        ]
        if len(carrying) != 1:
            faults.append(
                f"{len(carrying)} request(s) of this run carry the sentence, expected one"
            )
        broken = [
            text for text in parity["withdrawn"] if text.strip() == "raditional knowledge"
        ]
        if not broken:
            faults.append("F2's half-word request is not recorded as withdrawn")
    record(name, not faults, "; ".join(faults))


def check_03b_the_stranded_initials_are_taken_into_the_body() -> None:
    """Positive 3b: CERNCourier-en p3's two ``Th`` fragments join their paragraph.

    Defect A7 of the F2 review, and the overlap B10.2 re-attributed away from
    the collision detector: the pair is a source design the detector rightly
    exempts, and what is wrong with the page is that the body paragraph begins
    ``e European Strategy``. It is closed by the inline rule rather than by the
    dropped initial rule, and the reason is measured in 3c.
    """
    name = "check_03b_the_stranded_initials_are_taken_into_the_body"
    sample = ANCHOR_INITIALS["sample"]
    report = stitch_report(sample)
    if report is None:
        skip(name, [f"{sample}/fragment_stitch.report.json"])
        return
    faults = []
    on_page = {
        item["paragraph"]: item
        for item in report["stitches"]
        if item["page"] == ANCHOR_INITIALS["page"]
    }
    for reference, opening in zip(
        ANCHOR_INITIALS["paragraphs"], ANCHOR_INITIALS["openings"], strict=True
    ):
        stitched = on_page.get(reference)
        if stitched is None:
            faults.append(f"{reference} was not stitched; page holds {sorted(on_page)}")
            continue
        if stitched["members"] != ANCHOR_INITIALS["members"]:
            faults.append(f"{reference} took {stitched['members']} piece(s)")
        if not stitched["text"].startswith(opening):
            faults.append(f"{reference} reads {stitched['text'][:40]!r}, expected {opening!r}")
        if stitched["rule"] != fragment_stitch.RULE_INLINE:
            faults.append(f"{reference} was joined by {stitched['rule']}")
    record(name, not faults, "; ".join(faults))


def check_03c_the_initial_rule_reports_what_it_refused() -> None:
    """Positive 3c: every pair shaped like an initial is on the record.

    The dropped initial rule accepts nothing on this corpus, and that is a
    measurement rather than an omission: the fragments it was written for are
    set at the *same* size as the body they belong to, so the size ratio that
    identifies a dropped initial reads 1.0 against a bound of 1.6. Each is
    filed with the ratio that refused it. The rule is kept because the shape it
    describes is real and the bound is the right one for it; what closes these
    particular fragments is the inline rule, which does not care about size.
    """
    name = "check_03c_the_initial_rule_reports_what_it_refused"
    samples = sorted(TARGETS)
    absent = [s for s in samples if stitch_report(s) is None]
    if absent:
        skip(name, absent)
        return
    settings = stitch_config()
    faults = []
    accepted = 0
    for sample in samples:
        report = stitch_report(sample)
        for candidate in report["initial_candidates"]:
            for key in ("font_ratio", "left_offset", "top_offset", "accepted"):
                if key not in candidate:
                    faults.append(f"{sample}: a candidate omits {key}")
            if candidate.get("accepted"):
                accepted += 1
                if candidate["font_ratio"] < settings.initial_min_font_ratio:
                    faults.append(
                        f"{sample}: a pair below the bound was accepted at "
                        f"{candidate['font_ratio']}"
                    )
        if report["totals"]["initial_accepted"] != sum(
            1 for item in report["initial_candidates"] if item["accepted"]
        ):
            faults.append(f"{sample}: the accepted total does not match the candidates")
        # At most, not exactly: the census is taken before anything is folded,
        # so a pair this rule would admit may already have been taken by the
        # inline rule, which runs first and reads no size. A stitch filed under
        # the initial rule with no admissible pair behind it is the fault.
        by_rule = report["by_rule"]
        if by_rule.get(fragment_stitch.RULE_INITIAL, 0) > report["totals"]["initial_accepted"]:
            faults.append(
                f"{sample}: {by_rule.get(fragment_stitch.RULE_INITIAL, 0)} stitch(es) "
                f"under the initial rule, {report['totals']['initial_accepted']} "
                "pair(s) it would admit"
            )
    print(f"    initial candidates accepted across the corpus: {accepted}")
    record(name, not faults, "; ".join(faults))


# --- 04 T2 ------------------------------------------------------------------------


def stacked_paragraph(gaps, debug_id="stacked", size=10.0):
    """One paragraph of several lines at chosen distances, top line first."""
    runs = []
    y = 500.0
    for ordinal, gap in enumerate((0.0, *gaps)):
        y -= size + gap
        runs.append(run_of(f"line {ordinal} of the record", 80.0, y, size, BODY_FONT))
    return paragraph(runs, debug_id=debug_id)


def check_04a_an_evenly_leaded_block_is_one_record_per_line() -> None:
    """Positive 4a: with no distance above the bound the line is the record.

    The conservative branch and the one that keeps a grid of entries set one to
    a line coming out as entries. Reading such a block as a single record would
    be the other extreme and the worse one.
    """
    characters = line_split.paragraph_characters(stacked_paragraph((2.0, 2.0, 2.0)))
    settings = split_config()
    lines = line_split.recover_lines(characters, settings)
    groups = line_split.record_groups(characters, lines, settings)
    faults = []
    if len(lines) != 4:
        faults.append(f"the block recovered {len(lines)} line(s)")
    if len(groups) != len(lines):
        faults.append(f"{len(lines)} evenly leaded lines became {len(groups)} record(s)")
    if any(len(group) != 1 for group in groups):
        faults.append("a record holds more than the line it is")
    record(
        "check_04a_an_evenly_leaded_block_is_one_record_per_line",
        not faults,
        "; ".join(faults),
    )


def check_04b_a_block_set_apart_is_grouped_at_the_space() -> None:
    """Positive 4b: a distance above the bound is where one record ends.

    Three tight lines, a space, then three more. Both branches of the rule are
    live: the bound is read against the paragraph's own median, so the same
    figures at another leading give the same answer.
    """
    settings = split_config()
    tight, wide = 2.0, 2.0 * settings.record_gap_ratio + 1.0
    characters = line_split.paragraph_characters(
        stacked_paragraph((tight, tight, wide, tight, tight))
    )
    lines = line_split.recover_lines(characters, settings)
    groups = line_split.record_groups(characters, lines, settings)
    faults = []
    if len(lines) != 6:
        faults.append(f"the block recovered {len(lines)} line(s)")
    if [len(group) for group in groups] != [3, 3]:
        faults.append(f"the records hold {[len(group) for group in groups]} line(s)")
    record(
        "check_04b_a_block_set_apart_is_grouped_at_the_space",
        not faults,
        "; ".join(faults),
    )


def check_04c_the_boundary_is_the_mechanism_and_nothing_else() -> None:
    """Positive 4c: on the corpus, every boundary is a distance above the bound.

    The invariant that says the grouping is the printer's mechanism rather than
    a fit to a known page: recomputed over the run's own record counts, a
    paragraph reports more than one record if and only if some distance in it
    reached the bound, and never otherwise.
    """
    name = "check_04c_the_boundary_is_the_mechanism_and_nothing_else"
    samples = sorted(TARGETS)
    absent = [s for s in samples if split_report(s) is None]
    if absent:
        skip(name, absent)
        return
    faults = []
    grouped = 0
    for sample in samples:
        for item in split_report(sample)["splits"]:
            lines, records = item["lines"], item["records"]
            counts = item["record_lines"]
            if sum(counts) != lines:
                faults.append(f"{sample} {item['paragraph']}: {counts} does not sum to {lines}")
            if len(counts) != records:
                faults.append(f"{sample} {item['paragraph']}: {records} records, {len(counts)} counts")
            if records == lines and any(count != 1 for count in counts):
                faults.append(f"{sample} {item['paragraph']}: ungrouped yet uneven")
            if records != lines:
                grouped += 1
                if records >= lines:
                    faults.append(f"{sample} {item['paragraph']}: grouping added records")
    print(f"    paragraphs whose records are not their lines: {grouped}")
    record(name, not faults, "; ".join(faults))


def check_04d_the_evenly_leaded_page_keeps_its_record_account() -> None:
    """Positive 4d: Courier-en p1's records are the ones the run before produced.

    Its blocks are all evenly leaded -- an entry line and the byline under it,
    twice the leading apart at the widest -- so no distance reaches the bound
    and the record account is unchanged, paragraph for paragraph and text for
    text, against the F2 run. This is the assertion that says record grouping
    did not quietly redraw a page it had no evidence to redraw.

    It is an assertion about the *records*, and deliberately not about the
    finished page: T3 gives fifteen of those records the style their own
    characters are set in rather than the byline style they inherited, so the
    page prints differently on purpose. See the batch report.
    """
    name = "check_04d_the_evenly_leaded_page_keeps_its_record_account"
    sample, label = UNMOVED_RECORDS["sample"], UNMOVED_RECORDS["page"]
    mine = split_report(sample)
    baseline_path = BASELINE_DIR / sample / "work" / sample / line_split.REPORT_NAME
    if mine is None or not baseline_path.exists():
        skip(name, [f"{sample}/{line_split.REPORT_NAME}", str(baseline_path)])
        return
    baseline = load_json(baseline_path)
    faults = []
    was = [item for item in baseline["splits"] if item["page"] == label]
    now = [item for item in mine["splits"] if item["page"] == label]
    if len(was) != len(now):
        faults.append(f"{len(was)} split(s) in F2, {len(now)} here")
    for before, after in zip(was, now, strict=False):
        if before["paragraph"] != after["paragraph"]:
            faults.append(f"{before['paragraph']} became {after['paragraph']}")
        if before["lines"] != after["lines"]:
            faults.append(f"{after['paragraph']}: {before['lines']} lines became {after['lines']}")
        if after["records"] != after["lines"]:
            faults.append(f"{after['paragraph']}: {after['lines']} lines became {after['records']} records")
    exempt_before = [item["paragraph"] for item in baseline["exemptions"] if item["page"] == label]
    exempt_now = [item["paragraph"] for item in mine["exemptions"] if item["page"] == label]
    if exempt_before != exempt_now:
        faults.append(f"the exempt set moved: {exempt_before} against {exempt_now}")
    record(name, not faults, "; ".join(faults))


def check_04e_the_fragment_census_falls_and_what_is_left_is_the_rule() -> None:
    """Positive 4e: the census falls, and every survivor is on an exempt page.

    The batch plan expected the eight fragment clusters of Vogue-en p3 to go to
    nothing. Four of them do. What is asserted instead is the property that
    holds across the whole corpus and says more than the count would: after this
    batch the census reports **no cluster at all on a page the stitch was
    allowed to act on**. Every surviving cluster stands on a page whose declared
    policy says its lines are records, where the stitch does not run by design
    and where a run of short paragraphs is a run of records rather than a broken
    unit -- which is what a census of that page is measuring.

    The count is recorded per sample as well, in the direction it can only move.
    """
    name = "check_04e_the_fragment_census_falls_and_what_is_left_is_the_rule"
    faults = []
    lines = []
    for sample in sorted(TARGETS):
        mine = sidecar(sample, "issues.json")
        baseline_path = BASELINE_DIR / sample / "work" / sample / "issues.json"
        report = split_report(sample)
        if mine is None or not baseline_path.exists() or report is None:
            skip(name, [f"{sample}/issues.json", str(baseline_path)])
            return
        baseline = load_json(baseline_path)
        was = baseline["counts"]["by_kind"].get("fragment_cluster", 0)
        now = mine["counts"]["by_kind"].get("fragment_cluster", 0)
        lines.append(f"{sample}: {was} -> {now}")
        if now > was:
            faults.append(f"{sample}: the census rose, {was} to {now}")
        exempt = {entry["page"] for entry in report["pages"] if entry["declared"]}
        for issue in mine["issues"]:
            if issue["kind"] != "fragment_cluster":
                continue
            if issue["page"] not in exempt:
                faults.append(
                    f"{sample} p{issue['page']}: a cluster survives on a page the "
                    f"stitch was free to act on: {issue['evidence']['excerpt'][:60]!r}"
                )
    total_before = sum(int(line.split(" -> ")[0].split(": ")[1]) for line in lines)
    total_after = sum(int(line.split(" -> ")[1]) for line in lines)
    if total_after >= total_before:
        faults.append(f"the corpus census did not fall: {total_before} to {total_after}")
    print("    fragment clusters: " + "; ".join(lines))
    print(f"    corpus total {total_before} -> {total_after}, all survivors on exempt pages")
    record(name, not faults, "; ".join(faults[:4]))


# --- 05 T3 and T4 ------------------------------------------------------------------


def check_05a_a_record_carries_its_own_setting() -> None:
    """Positive 5a: a title line and the byline under it no longer share a style.

    The parent's base style is whatever the paragraph mostly was, and on a
    contents page mostly bylines that prints every entry title at byline size.
    Each record now takes the style its own characters are mostly set in.
    """
    entry = paragraph(
        [
            run_of("Brazil: lessons from the water people", 80.0, 528.0, 10.0, BODY_FONT),
            run_of("Marcelo Silva de Sousa and one more name here", 80.0, 516.0, 7.0,
                   OTHER_FONT, 4.0),
        ],
        debug_id="entry",
        font=OTHER_FONT,
        size=7.0,
    )
    docs = document([page([entry], declared_kind())])
    split_to(docs)
    built = docs.page[0].pdf_paragraph
    faults = []
    if len(built) != 2:
        faults.append(f"the record became {len(built)} paragraph(s)")
    else:
        title, byline = built
        if (title.pdf_style.font_id, title.pdf_style.font_size) != (BODY_FONT, 10.0):
            faults.append(
                f"the title record is set in {title.pdf_style.font_id} at "
                f"{title.pdf_style.font_size}"
            )
        if (byline.pdf_style.font_id, byline.pdf_style.font_size) != (OTHER_FONT, 7.0):
            faults.append(
                f"the byline record is set in {byline.pdf_style.font_id} at "
                f"{byline.pdf_style.font_size}"
            )
    record("check_05a_a_record_carries_its_own_setting", not faults, "; ".join(faults))


def check_05b_every_record_is_set_as_its_own_characters_are() -> None:
    """Positive 5b: on the corpus, no record is set otherwise.

    Recomputed from the run's own checkpoint rather than read back from the
    report: the report says how many records were restyled, and this says every
    record in the document carries the majority style of the characters inside
    it, which is the property the count is a count of.
    """
    name = "check_05b_every_record_is_set_as_its_own_characters_are"
    from babeldoc.magazine.checkpoint import load_checkpoint

    sample = "CERNCourier-en"
    working = BATCH_DIR / sample / "work" / sample
    path = working / "checkpoint.07_page_classifier.xml"
    report = split_report(sample)
    if not path.exists() or report is None:
        skip(name, [str(path)])
        return
    built = {
        identity
        for item in report["splits"]
        for identity in item["line_paragraphs"]
    }
    docs = load_checkpoint(path)
    faults = []
    checked = 0
    for page_object in docs.page:
        for item in page_object.pdf_paragraph or ():
            if item.debug_id not in built:
                continue
            checked += 1
            majority = line_split.record_style(line_split.paragraph_characters(item))
            if majority is None:
                continue
            if not line_split.same_style(item.pdf_style, majority):
                faults.append(
                    f"{item.debug_id} is set in {item.pdf_style.font_id}/"
                    f"{item.pdf_style.font_size}, its characters in "
                    f"{majority.font_id}/{majority.font_size}"
                )
    if not checked:
        faults.append("no record of the run was found in the checkpoint")
    print(f"    records checked against their own characters: {checked}")
    record(name, not faults, "; ".join(faults[:4]))


def check_05c_a_stitched_unit_is_one_style_throughout() -> None:
    """Positive 5c: the minority of a merged unit is taken to the majority.

    A unit set in two styles reaches the translator as a rich text request, with
    a placeholder around each run, and what the pieces of a broken word want is
    to be one run. The count of characters that moved is in the record rather
    than silent.
    """
    built = broken_word_page(undeclared_kind(), right_font=OTHER_FONT)
    built.pdf_font = [font(BODY_FONT, "Merriweather"), font(OTHER_FONT, "Merriweather")]
    docs = document([built])
    result, _ = stitch_to(docs)
    merged = docs.page[0].pdf_paragraph[0]
    characters = line_split.paragraph_characters(merged)
    faults = []
    faces = {item.pdf_style.font_id for item in characters}
    if len(faces) != 1:
        faults.append(f"the merged unit is set in {sorted(faces)}")
    if len(merged.pdf_paragraph_composition) != 1:
        faults.append(
            f"the merged unit holds {len(merged.pdf_paragraph_composition)} run(s)"
        )
    if result is None or not result["stitches"]:
        faults.append("nothing was stitched")
    else:
        row = result["stitches"][0]
        if not row["style_normalized"] or row["restyled_characters"] < 1:
            faults.append(f"the record says {row['style_normalized']}/{row['restyled_characters']}")
    record(
        "check_05c_a_stitched_unit_is_one_style_throughout", not faults, "; ".join(faults)
    )


# --- 06 conservation, the double write, the request account -------------------------


def check_06a_the_page_keeps_its_paragraphs() -> None:
    """Positive 6a: a stitch removes nothing and renumbers nothing.

    The hard constraint of the batch: the merged members stay where they stood
    holding nothing, so a paragraph reference minted before this pass still
    resolves after it, and the account of a run can be set against the account
    of the run before it.
    """
    name = "check_06a_the_page_keeps_its_paragraphs"
    samples = sorted(TARGETS)
    absent = [s for s in samples if stitch_report(s) is None]
    if absent:
        skip(name, absent)
        return
    faults = []
    for sample in samples:
        report = stitch_report(sample)
        for entry in report["pages"]:
            page_stitches = [
                item for item in report["stitches"] if item["page"] == entry["page"]
            ]
            blanked = sum(item["members"] - 1 for item in page_stitches)
            if blanked != entry["blanked"]:
                faults.append(f"{sample} p{entry['page']}: {blanked} against {entry['blanked']}")
        conservation = conservation_of(sample)
        if conservation is None:
            continue
        if conservation["pages"] != conservation["baseline_pages"]:
            faults.append(
                f"{sample}: {conservation['baseline_pages']} pages in F2, "
                f"{conservation['pages']} here"
            )
    record(name, not faults, "; ".join(faults))


def check_06a2_a_blanked_member_occupies_nothing() -> None:
    """Positive 6a2: on the corpus, no merged-away member still holds a band.

    The invariant behind the second half of a stitch. Read off each run's own
    checkpoint: the members named in the report are found on the page, and each
    carries neither composition nor box.
    """
    name = "check_06a2_a_blanked_member_occupies_nothing"
    from babeldoc.magazine.checkpoint import load_checkpoint

    faults = []
    checked = 0
    for sample in sorted(TARGETS):
        report = stitch_report(sample)
        path = BATCH_DIR / sample / "work" / sample / "checkpoint.07_page_classifier.xml"
        if report is None or not path.exists() or not report["stitches"]:
            continue
        blanked = {
            identity
            for item in report["stitches"]
            for identity in item["member_debug_ids"][1:]
        }
        docs = load_checkpoint(path)
        for page_object in docs.page:
            for item in page_object.pdf_paragraph or ():
                if item.debug_id not in blanked:
                    continue
                checked += 1
                if item.pdf_paragraph_composition:
                    faults.append(f"{sample} {item.debug_id} is still drawn")
                if item.box is not None:
                    faults.append(f"{sample} {item.debug_id} still holds a band")
                if item.unicode:
                    faults.append(f"{sample} {item.debug_id} still says something")
    if not checked:
        skip(name, ["no blanked member found in any run's checkpoint"])
        return
    print(f"    blanked members carrying nothing: {checked}")
    record(name, not faults, "; ".join(faults[:4]))


def check_06b_the_two_halves_of_a_text_agree() -> None:
    """Positive 6b: a stitched paragraph's text is the text of its characters.

    The double write constraint, asserted where this batch writes: the merged
    paragraph's ``unicode`` and the characters its composition was rebuilt from
    normalise to one string, so the halves cannot drift apart here. B10.1
    recorded a paragraph where they had; this says none is added.
    """
    name = "check_06b_the_two_halves_of_a_text_agree"
    from babeldoc.magazine.checkpoint import load_checkpoint

    faults = []
    checked = 0
    for sample in sorted(TARGETS):
        report = stitch_report(sample)
        path = BATCH_DIR / sample / "work" / sample / "checkpoint.07_page_classifier.xml"
        if report is None or not path.exists() or not report["stitches"]:
            continue
        wanted = {item["debug_id"]: item for item in report["stitches"]}
        docs = load_checkpoint(path)
        for page_object in docs.page:
            for item in page_object.pdf_paragraph or ():
                if item.debug_id not in wanted:
                    continue
                checked += 1
                characters = line_split.paragraph_characters(item)
                rebuilt = get_char_unicode_string(characters)
                if unicodedata.normalize("NFKC", rebuilt) != unicodedata.normalize(
                    "NFKC", item.unicode or ""
                ):
                    faults.append(f"{sample} {item.debug_id}: the two halves differ")
    if not checked:
        skip(name, ["no stitched paragraph found in any run's checkpoint"])
        return
    print(f"    stitched paragraphs whose halves agree: {checked}")
    record(name, not faults, "; ".join(faults[:4]))


def check_06c_the_request_account_closes() -> None:
    """Positive 6c: every request is either F2's or on this batch's whitelist.

    Unlike the two batches before it this one changes request text on purpose,
    so what is asserted is not that nothing moved but that the account closes:
    the requests this run sent are the ones F2 sent, minus a withdrawn set, plus
    an introduced set, and both sets are written down.
    """
    name = "check_06c_the_request_account_closes"
    samples = sorted(TARGETS)
    absent = [s for s in samples if parity_of(s) is None]
    if absent:
        skip(name, absent)
        return
    faults = []
    introduced = withdrawn = 0
    for sample in samples:
        parity = parity_of(sample)
        if parity["unchanged_requests"] + len(parity["introduced"]) != parity["requests"]:
            faults.append(
                f"{sample}: {parity['unchanged_requests']} unchanged plus "
                f"{len(parity['introduced'])} introduced is not {parity['requests']}"
            )
        if parity["unchanged_requests"] + len(parity["withdrawn"]) != parity["baseline_requests"]:
            faults.append(
                f"{sample}: the baseline account does not close"
            )
        unread = sorted(set(parity["groups_present"]) - set(parity["groups_read"]))
        if unread:
            faults.append(f"{sample}: the tracking holds groups the comparison did not read: {unread}")
        introduced += len(parity["introduced"])
        withdrawn += len(parity["withdrawn"])
    print(f"    requests withdrawn: {withdrawn}, introduced: {introduced}")
    record(name, not faults, "; ".join(faults))


def check_06d_the_repair_ledger_equals_its_bill() -> None:
    """Positive 6d: the repair loop still files one row per call it makes.

    B10.2's invariant, carried forward. This batch's API spend is the
    translator's, which is accounted for in 6c; the loop's own spend is
    accounted for here, and the two do not mix.
    """
    name = "check_06d_the_repair_ledger_equals_its_bill"
    samples = sorted(TARGETS)
    reports = {s: sidecar(s, "react_repair.report.json") for s in samples}
    absent = [s for s, item in reports.items() if item is None]
    if absent:
        skip(name, absent)
        return
    faults = []
    for sample, report in reports.items():
        if report.get("api_calls") != len(report.get("api_attributions") or ()):
            faults.append(
                f"{sample}: {report.get('api_calls')} call(s), "
                f"{len(report.get('api_attributions') or ())} attribution(s)"
            )
    record(name, not faults, "; ".join(faults))


# The products of this batch that a clone receives, and the one it does not.
# The whole translated document was never committed -- only the target pages of
# it were -- so it is the one product the output retention policy can take once
# two later batches exist. A frozen product that has been pruned may not be
# replaced by re-running the batch, which is why its absence is reported as
# pruned rather than as a run that failed to produce it.
COMMITTED_PRODUCTS = ("pages_pdf", "parity", "conservation")
PRUNABLE_PRODUCTS = ("pdf",)


def check_06e_the_evidence_is_present() -> None:
    """Positive 6e: every sample of the evidence table produced its products."""
    name = "check_06e_the_evidence_is_present"
    if not LEDGER.exists():
        skip(name, [str(LEDGER)])
        return
    rows = {row["sample"].removesuffix(".pdf"): row for row in load_json(LEDGER)}
    faults = []
    pruned = []
    for sample, pages in TARGETS.items():
        row = rows.get(sample)
        if row is None:
            faults.append(f"{sample} is not in the ledger")
            continue
        if tuple(row["target_pages"]) != pages:
            faults.append(f"{sample} was written out on {row['target_pages']}")
        for key in (*COMMITTED_PRODUCTS, *PRUNABLE_PRODUCTS):
            if not row.get(key):
                faults.append(f"{sample} names no {key}")
            elif not (ROOT / row[key]).exists():
                if key in PRUNABLE_PRODUCTS:
                    pruned.append(row[key])
                else:
                    faults.append(f"{sample} is missing {key}")
        if len(row.get("raster") or ()) != len(pages):
            faults.append(f"{sample} rendered {len(row.get('raster') or ())} page(s)")
    if faults:
        record(name, False, "; ".join(faults))
        return
    if pruned:
        skip(name, pruned)
        return
    record(name, True)


def check_07_history_is_green() -> None:
    """Positive 7: every earlier gate of the fast set still passes."""
    if NESTED_SUPPRESSED:
        record("check_07_history_is_green", True, "run by spec_checks/run_all.py")
        return
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "spec_checks" / "run_all.py"), "--set", "fast"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    record("check_07_history_is_green", proc.returncode == 0, (proc.stdout or "")[-800:])


CHECKS = (
    check_01a_the_delta_is_the_declared_surface,
    check_01b_no_upstream_no_prompt_no_truth,
    check_01c_the_declaration_layer_is_untouched,
    check_01d_the_pass_names_no_page_type,
    check_01e_the_switch_is_down_by_default,
    check_01f_the_configuration_is_bounded,
    check_02a_the_inline_rule_joins_a_broken_word,
    check_02b_two_whole_paragraphs_are_not_joined,
    check_02c_the_face_is_read_by_name_not_by_id,
    check_02d_the_vertical_rule_chains_a_column,
    check_02e_a_declared_page_is_never_stitched,
    check_02f_page_furniture_is_not_stitched,
    check_03a_the_five_pieces_reach_the_translator_as_one_request,
    check_03b_the_stranded_initials_are_taken_into_the_body,
    check_03c_the_initial_rule_reports_what_it_refused,
    check_04a_an_evenly_leaded_block_is_one_record_per_line,
    check_04b_a_block_set_apart_is_grouped_at_the_space,
    check_04c_the_boundary_is_the_mechanism_and_nothing_else,
    check_04d_the_evenly_leaded_page_keeps_its_record_account,
    check_04e_the_fragment_census_falls_and_what_is_left_is_the_rule,
    check_05a_a_record_carries_its_own_setting,
    check_05b_every_record_is_set_as_its_own_characters_are,
    check_05c_a_stitched_unit_is_one_style_throughout,
    check_06a_the_page_keeps_its_paragraphs,
    check_06a2_a_blanked_member_occupies_nothing,
    check_06b_the_two_halves_of_a_text_agree,
    check_06c_the_request_account_closes,
    check_06d_the_repair_ledger_equals_its_bill,
    check_06e_the_evidence_is_present,
    check_07_history_is_green,
)


def main() -> int:
    print("spec_check_b10_3: fragment stitch, record grouping, record style\n")
    for check in CHECKS:
        try:
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
