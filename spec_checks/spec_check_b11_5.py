"""Gate script for batch B11.5 (a pinned label, a self-ironic false positive,
an indent policy, and three masthead rulings).

Run from the repository root:

    python spec_checks/spec_check_b11_5.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request. Every assertion is answered from a stub this gate builds or
from the small derived evidence this batch wrote beside its run -- never from a
stage checkpoint and never from a produced PDF, per CLAUDE.md section 4.16.

What this batch is.

T1 pinned ``F&D`` to itself in the ruling file. b11.3 had removed ``.*Mono``
from the broad formula font pattern, which turned the masthead label from a
formula into text and so sent it to be translated; the page began saying
"Finance and Development" where the source says ``F&D``. The repair is a
glossary keep, not a formula annotation: annotating something wrongly so that
the right thing happens is the shape GAP-35 had just registered.

T2 exempted the corner mark rule beside an enlarged initial. The rule fires when
a character is markedly smaller than the one before it, which is how a
superscript is told from its text -- and which is also, exactly, the shape a
drop cap creates. Its own comment claims to account for that and it does not. So
the letters after a drop cap were carried as a formula, untranslated, and the
drop cap merge refused to act because its tail was a formula. The exemption
suppresses one predicate inside one bounded span. Measured over the whole
corpus by driving the real stage twice: two reclassified runs, nothing
reclassified the other way, no graphic changing hands.

T3 gave the first line indent a policy. It had been read off the source
geometry per paragraph, which reproduces the source language's convention on a
page set in another language. A mode is now declared per target language; zh is
``all``.

T4 put three masthead entries the name harvest could not shape-match to a
person, and one ruling covered each.

T5 registered three gaps and corrected one observation the plan had recorded
with the wrong shape.

01 is T1: the label, in the record and on the page.
02 is T1's second half: the two assertions b11.4 left red.
03 is T2: the frozen predicate, the measurement, the inventory, the page, the
   guards.
04 is T3: the policy, its surface, its fallback, and the pin on the amount.
05 is T4: the rulings and the gaps.
06 is conservation, cost and scope.

Tiers: every assertion reads a stub or this batch's own derived evidence, so the
fast tier runs the whole gate.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import indent_policy  # noqa: E402
from babeldoc.format.pdf.document_il.midend import styles_and_formulas as sf  # noqa: E402
from spec_checks import evidence  # noqa: E402
from spec_checks import harness  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b11.5"
PREVIOUS_TAG = "b11.4"

SAMPLE = "FD-en-v2"
BATCH_DIR = ROOT / "examples" / "output" / "b11_5"
PRIOR_DIR = ROOT / "examples" / "output" / "b11_4"
RUN_DIR = BATCH_DIR / SAMPLE

PREMISE = BATCH_DIR / "premise_check.json"
FREEZE = BATCH_DIR / "t2_predicate_freeze.json"
MEASUREMENT = BATCH_DIR / "t2_measurement.json"
REVIEW = BATCH_DIR / "t2_review.json"
INVENTORY = BATCH_DIR / "t2_consumer_inventory.json"
RULINGS = BATCH_DIR / "t4_rulings.json"
DRAFT = BATCH_DIR / "t4_draft.json"
COST = BATCH_DIR / "cost_attribution.json"
SWEEP = BATCH_DIR / "run_all.fast.json"

RUN = RUN_DIR / "run.json"
RENDER = RUN_DIR / "render_evidence.json"
INDENT = RUN_DIR / "indent_evidence.json"
CONSERVATION = RUN_DIR / "conservation.json"
SIDECARS = RUN_DIR / "sidecars"

# What this gate reads and the retention policy must therefore not remove.
# CLAUDE.md section 4.16: all of it is derived evidence this batch extracted at
# run time, and none of it is a checkpoint or a PDF.
GATE_EVIDENCE = (
    "examples/output/b11_5/premise_check.json",
    "examples/output/b11_5/t2_predicate_freeze.json",
    "examples/output/b11_5/t2_measurement.json",
    "examples/output/b11_5/t2_review.json",
    "examples/output/b11_5/t2_consumer_inventory.json",
    "examples/output/b11_5/t4_draft.json",
    "examples/output/b11_5/t4_rulings.json",
    "examples/output/b11_5/cost_attribution.json",
    "examples/output/b11_5/run_all.fast.json",
    "examples/output/b11_5/FD-en-v2/run.json",
    "examples/output/b11_5/FD-en-v2/render_evidence.json",
    "examples/output/b11_5/FD-en-v2/indent_evidence.json",
    "examples/output/b11_5/FD-en-v2/conservation.json",
    "examples/output/b11_5/FD-en-v2/sidecars/short_unit.report.json",
    "examples/output/b11_5/FD-en-v2/sidecars/drop_cap.report.json",
    "examples/output/b11_5/FD-en-v2/sidecars/drop_cap_apply.report.json",
    "examples/output/b11_5/FD-en-v2/sidecars/indent_policy.report.json",
    "examples/output/b11_5/FD-en-v2/sidecars/issues.json",
    "examples/output/b11_5/FD-en-v2/sidecars/title_typeset.report.json",
)

# Chinese strings this gate matches are written as escapes so the file stays
# pure ASCII: b0's 09, b1's 09d and b2's 11c all scan spec_checks/*.py for CJK.
# Each escape is glossed in English beside it.
LABEL = "F&D"
LABEL_TRANSLATED = "\u8d22\u653f\u4e0e\u53d1\u5c55"  # Finance and Development
LABEL_PAGES = (3, 5, 6, 8)
HEADER_BAND = 60.0

# The three ruled masthead rows, and the page they stand on.
RULED_ROWS = {
    "Huong (Vanessa) Le": "\u9999\uff08\u51e1\u59ae\u838e\uff09\u00b7\u9ece",
    "S M Ali Abbas": "S\u00b7M\u00b7\u963f\u91cc\u00b7\u963f\u5df4\u65af",
    "2communiqu\u00e9": "\u4e8c\u53f7\u516c\u62a5",
}
MASTHEAD_PAGE = 5

# The drop cap paragraph, by page and by the source it opens with. Never by a
# debug id: CLAUDE.md section 5.13.
DROP_CAP_PAGE = 8
DROP_CAP_REFERENCE = "p8#9"
DROP_CAP_SOURCE_HEAD = "When it comes to international trade"
# The residue T2 removes, as the source spells it. A word rather than a letter
# run, so the search cannot match inside a longer Latin word.
RESIDUE = "hen"
BIG_GLYPH = 15.0
LINE_SPACING_TOLERANCE = 1.5

# The two files this batch changed upstream, and the register each is in.
UPSTREAM_FILES = (
    "babeldoc/format/pdf/document_il/midend/styles_and_formulas.py",
    "babeldoc/format/pdf/high_level.py",
)
UPSTREAM_DIFF = ROOT / "UPSTREAM_DIFF.md"
WAIVERS = ROOT / "WAIVERS.md"
CONTRACTS = ROOT / "docs" / "reports" / "assertion_contracts.md"
GAP_REGISTER = ROOT / "docs" / "eval" / "gap_register.md"
B11_2_GATE = ROOT / "spec_checks" / "spec_check_b11_2.py"
TYPESETTING = (
    ROOT / "babeldoc" / "format" / "pdf" / "document_il" / "midend" / "typesetting.py"
)
INDENT_CONFIG = ROOT / "configs" / "indent_policy.json"
ADJACENT_CONFIG = ROOT / "configs" / "initial_adjacent.json"

GAPS = ("GAP-38", "GAP-39", "GAP-40")

# The delta this batch is allowed.
ALLOWED_PREFIXES = (
    "babeldoc/format/pdf/document_il/midend/styles_and_formulas.py",
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/magazine/indent_policy.py",
    # The plan's surface names configs/ as a whole; the three files this batch
    # writes there are the two it declares and the sidecar inventory, which
    # gained a row because a new pass writes a new report.
    "configs/",
    "reviews/FD-en-v2.decisions.json",
    "spec_checks/spec_check_b11_2.py",
    "spec_checks/spec_check_b11_5.py",
    # Three gates the ruling update reached. Adding rows to the ruling moves its
    # digest, and three gates pin that digest; CLAUDE.md 4.12 says an authorised
    # update repins rather than fails, so they were repinned with a change
    # record. W-B11-17.
    "spec_checks/spec_check_b7_5.py",
    "spec_checks/spec_check_b9_5.py",
    "spec_checks/spec_check_b11_4.py",
    "spec_checks/run_all.py",
    "docs/eval/gap_register.md",
    "docs/reports/assertion_contracts.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "plans/PLAN_B11_5.md",
    "plans/PLAN_B11_5_REV2.md",
    "examples/output/b11_5/",
)

# Trees this batch reads and never writes.
READ_ONLY_TREES = (
    "prompts/",
    "corpus/",
    "examples/output/b10_5/",
    "examples/output/b11_4/",
)

ARTEFACT_CEILING_BYTES = 1_000_000_000

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b11_5")


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


def skip(name: str, missing) -> None:
    global _total
    _total += 1
    seconds = _timer.mark(name)
    print(f"SKIPPED: {name}: evidence absent: {sorted(missing)} ({seconds:.2f}s)")


def load(path: Path):
    return evidence.read_json(path)


def sidecar(name: str):
    return load(SIDECARS / name)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalise(text: str) -> str:
    """One string, folded the way a font substitution may have written it.

    A rendered document can carry a CJK compatibility ideograph where the source
    string carries the unified one -- this batch's own ruling renders U+F9E9 for
    U+91CC -- so a comparison of what was ruled against what was set has to fold
    that difference or it fails on a page that is right.
    """
    return unicodedata.normalize("NFKC", text)


def page_lines(page: dict) -> list[dict]:
    return page["lines"]


def page_blob(page: dict) -> str:
    """One page's text, rebuilt band by band from the extracted lines.

    Rebuilt rather than taken from the extractor's own page text, because a run
    of separately positioned characters is reported as one line each and a name
    is then split across them; joining by vertical band puts the name back
    together.
    """
    bands: dict[int, list[tuple[float, str]]] = {}
    for line in page_lines(page):
        bands.setdefault(round(line["bbox"][1]), []).append(
            (line["bbox"][0], line["text"])
        )
    return "\n".join(
        "".join(text for _, text in sorted(items)) for _, items in sorted(bands.items())
    )


def document_blob(render: dict) -> str:
    return "\n".join(page_blob(page) for page in render["per_page"])


def changed_paths() -> list[str]:
    """This batch's delta, anchored to its own tag where the tag exists."""
    tag = subprocess.run(  # noqa: S603
        ["git", "tag", "--list", BATCH_TAG],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if tag:
        argv = ["git", "diff", "--name-only", f"{BATCH_TAG}^..{BATCH_TAG}"]
    else:
        argv = ["git", "status", "--porcelain"]
    proc = subprocess.run(  # noqa: S603
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,  # noqa: S607
    )
    paths = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        paths.append(line if tag else line.split(maxsplit=1)[-1].strip('"'))
    return sorted(set(paths))


# --- documents built here ------------------------------------------------------


def style(font: str, size: float):
    return il_version_1.PdfStyle(
        font_id=font,
        font_size=size,
        graphic_state=il_version_1.GraphicState(),
    )


def character(text: str, size: float, x: float, y: float = 100.0):
    return il_version_1.PdfCharacter(
        char_unicode=text,
        pdf_style=style("T1_0", size),
        box=il_version_1.Box(x=x, y=y, x2=x + size, y2=y + size),
        visual_bbox=il_version_1.VisualBbox(
            box=il_version_1.Box(x=x, y=y, x2=x + size, y2=y + size)
        ),
        xobj_id=0,
        advance=size,
    )


def run_of(text: str, size: float, start: float = 0.0):
    return [
        character(char, size, start + index * size)
        for index, char in enumerate(text)
    ]


def opening_paragraph(initial_size: float, body: str = "hen it comes to trade"):
    """A paragraph opening with one enlarged character, as a drop cap does."""
    head = run_of("W", initial_size, 0.0)
    tail = run_of(body, 9.25, initial_size)
    return il_version_1.PdfParagraph(
        unicode="W" + body,
        layout_label="plain text",
        pdf_style=style("T1_1", 9.25),
        box=il_version_1.Box(x=0.0, y=100.0, x2=400.0, y2=140.0),
        first_line_indent=False,
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    box=il_version_1.Box(x=0.0, y=100.0, x2=initial_size, y2=140.0),
                    pdf_style=style("T1_0", initial_size),
                    pdf_character=head,
                )
            ),
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    box=il_version_1.Box(x=initial_size, y=100.0, x2=400.0, y2=110.0),
                    pdf_style=style("T1_1", 9.25),
                    pdf_character=tail,
                )
            ),
        ],
    )


def formula_tail_paragraph(initial_size: float = 39.36):
    """The same opening, with its tail still annotated as a formula."""
    paragraph = opening_paragraph(initial_size)
    tail = paragraph.pdf_paragraph_composition[1].pdf_same_style_characters
    paragraph.pdf_paragraph_composition[1] = il_version_1.PdfParagraphComposition(
        pdf_formula=il_version_1.PdfFormula(
            box=tail.box, pdf_character=list(tail.pdf_character)
        )
    )
    return paragraph


class StubConfig:
    """The few translation config members the passes under test read."""

    def __init__(self, working: Path, lang_out: str = "zh", **switches):
        self._working = working
        self.lang_out = lang_out
        for name, value in switches.items():
            setattr(self, name, value)

    def get_working_file_path(self, name: str) -> str:
        return str(self._working / name)


def labeled_document(paragraphs):
    return il_version_1.Document(
        page=[
            il_version_1.Page(
                page_number=0,
                pdf_paragraph=list(paragraphs),
                mediabox=il_version_1.Mediabox(
                    box=il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
                ),
                cropbox=il_version_1.Cropbox(
                    box=il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
                ),
            )
        ]
    )


# --- 01 T1: the label, in the record and on the page ---------------------------


def check_01a_the_label_is_recorded_as_unchanged() -> None:
    """Positive 1a: every short unit for the label answers with the label.

    Two facts, not one. That the reply equals the source says the ruling reached
    the model; that the writer skipped the paragraph says the source rendering
    was kept rather than recomposed at the same string, which is the difference
    b11.1's identity branch exists to make and which is invisible in the text.
    """
    faults = []
    report = sidecar("short_unit.report.json")
    units = [unit for unit in report["units"] if unit["source"] == LABEL]
    if len(units) != 5:
        faults.append(f"{len(units)} unit(s) for the label, expected 5")
    for unit in units:
        if unit["translated"] != LABEL:
            faults.append(f"{unit['paragraph']}: answered {unit['translated']!r}")
        if not unit["identity_skipped"]:
            faults.append(f"{unit['paragraph']}: was recomposed, not skipped")
    record("check_01a_the_label_is_recorded_as_unchanged", not faults,
           "; ".join(faults[:4]))


def check_01b_the_label_is_set_in_its_source_form() -> None:
    """Positive 1b: the label stands on the page and its translation nowhere.

    Both halves are needed. The label being present does not by itself say the
    translated form is absent -- a page could carry both -- and it is the
    translated form on a masthead that GAP-36 is about.
    """
    faults = []
    render = load(RENDER)
    pages = {page["page"]: page for page in render["per_page"]}
    for label in LABEL_PAGES:
        page = pages.get(label)
        if page is None:
            faults.append(f"p{label}: absent")
            continue
        header = [
            span
            for line in page_lines(page)
            for span in line["spans"]
            if span["bbox"][1] < HEADER_BAND
        ]
        if not any(span["text"].strip() == LABEL for span in header):
            faults.append(f"p{label}: no {LABEL} in the header band")
    if LABEL_TRANSLATED in document_blob(render):
        faults.append("the translated form of the label is on a page")
    record("check_01b_the_label_is_set_in_its_source_form", not faults,
           "; ".join(faults[:4]))


def check_01c_the_ruling_is_pinned_in_the_run_record() -> None:
    """Positive 1c: the run says which ruling it ran under, by hash.

    A record that names the entry without pinning the file cannot tell a run
    under this ruling from a run under a later one.
    """
    faults = []
    run = load(RUN)
    ruling = run.get("ruling") or {}
    if ruling.get("terms", {}).get(LABEL) != LABEL:
        faults.append(f"the run's ruling does not keep {LABEL} as itself")
    digest = ruling.get("sha256")
    if not digest or len(digest) != 64:
        faults.append("the ruling file is not pinned by hash")
    else:
        current = sha256_of(ROOT / "reviews" / f"{SAMPLE}.decisions.json")
        if current != digest:
            faults.append("the ruling changed after the run")
    record("check_01c_the_ruling_is_pinned_in_the_run_record", not faults,
           "; ".join(faults[:4]))


def check_01d_the_repair_is_not_a_formula_annotation() -> None:
    """Negative 1d: nothing was annotated as a formula to keep the label.

    The plan's whole argument for a glossary keep is that the other road --
    calling the label a formula so it is carried across untranslated -- gets the
    right page for the wrong reason, which is GAP-35's shape. So the label must
    not be a formula anywhere in the produced document, and the font pattern
    b11.3 narrowed must not have been widened back.
    """
    faults = []
    audit = sidecar("source_audit.report.json")
    text = json.dumps(audit, ensure_ascii=False)
    if f'"{LABEL}"' in text and "pdf_formula" in text:
        rows = [
            row
            for row in (audit.get("rows") or audit.get("compositions") or [])
            if isinstance(row, dict)
            and row.get("text", "").strip() == LABEL
            and row.get("kind") == "pdf_formula"
        ]
        if rows:
            faults.append(f"the label is a formula in {len(rows)} place(s)")
    helper = (
        ROOT
        / "babeldoc"
        / "format"
        / "pdf"
        / "document_il"
        / "utils"
        / "formular_helper.py"
    ).read_text(encoding="utf-8")
    if ".*Mono" in helper:
        faults.append("the broad font pattern was widened back to .*Mono")
    record("check_01d_the_repair_is_not_a_formula_annotation", not faults,
           "; ".join(faults[:4]))


# --- 02 T1's second half: what b11.4 left red ----------------------------------


def check_02a_the_label_assertion_now_reads_this_run() -> None:
    """Positive 2a: b11.2's 6d no longer stands on a frozen document.

    Asserted on the gate's source rather than by running it, because running a
    sibling gate from inside a gate is the nested sweep CLAUDE.md section 17
    warns about. What the claim itself says is asserted directly below.
    """
    faults = []
    text = B11_2_GATE.read_text(encoding="utf-8")
    body = text.split("def check_06d_", 1)
    if len(body) != 2:
        faults.append("6d is not in the b11.2 gate")
    else:
        block = body[1].split("\ndef ", 1)[0]
        if "pymupdf" in block or ".pdf" in block:
            faults.append("6d still opens a produced document")
        if "render_evidence" not in text:
            faults.append("6d does not read the extracted render evidence")
    if "examples/output/b11_5/FD-en-v2/render_evidence.json" not in text:
        faults.append("the b11.2 gate does not declare what 6d now reads")
    if "AC-15" not in CONTRACTS.read_text(encoding="utf-8"):
        faults.append("the re-pointing is not registered in the contracts ledger")
    record("check_02a_the_label_assertion_now_reads_this_run", not faults,
           "; ".join(faults[:4]))


def check_02b_the_label_stands_on_one_line_today() -> None:
    """Positive 2b: 6d's own claim, evaluated on this run's evidence.

    The claim b11.1 T1 established and b11.3 silently broke: on every page it
    appears, the label occupies one line rather than being recomposed on to two.
    Evaluated here so that this batch proves it of its own output rather than
    citing another gate's verdict.
    """
    faults = []
    render = load(RENDER)
    pages = {page["page"]: page for page in render["per_page"]}
    for label in (5, 6, 8):
        page = pages.get(label)
        if page is None:
            faults.append(f"p{label}: absent")
            continue
        spans = [
            span
            for line in page_lines(page)
            for span in line["spans"]
            if span["text"].strip() == LABEL
        ]
        if not spans:
            faults.append(f"p{label}: the label is not on the page")
            continue
        for one in spans:
            for other in spans:
                if one is other:
                    continue
                if abs(one["bbox"][0] - other["bbox"][0]) > 0.5:
                    continue
                if abs(one["bbox"][1] - other["bbox"][1]) < 8.0:
                    continue
                faults.append(f"p{label}: the label stands on two lines")
    record("check_02b_the_label_stands_on_one_line_today", not faults,
           "; ".join(faults[:4]))


def check_02c_the_unrecoverable_control_is_reported_as_such() -> None:
    """Positive 2c: b11.2's 0b is SKIPPED with its cause, not quietly halved.

    Its control is gone and cannot return (GAP-37). Running only its positive
    half and reporting green is the shape that let GAP-36 survive two batches,
    so the assertion says it cannot be executed.
    """
    faults = []
    text = B11_2_GATE.read_text(encoding="utf-8")
    block = text.split("def check_00b_", 1)
    if len(block) != 2:
        faults.append("0b is not in the b11.2 gate")
    else:
        body = block[1].split("\ndef ", 1)[0]
        if "skip(" not in body:
            faults.append("0b does not report SKIPPED when its control is empty")
        if "GAP-37" not in body:
            faults.append("0b does not name the cause")
    if "AC-16" not in CONTRACTS.read_text(encoding="utf-8"):
        faults.append("the conversion is not registered in the contracts ledger")
    record("check_02c_the_unrecoverable_control_is_reported_as_such", not faults,
           "; ".join(faults[:4]))


def check_02d_the_fast_sweep_is_recorded_green() -> None:
    """Positive 2d: the fast set ran and every gate of it passed.

    Read from the record the sweep wrote rather than by launching a sweep from
    inside a gate, which would nest and can orphan the sweep lock.
    """
    if not SWEEP.is_file():
        skip("check_02d_the_fast_sweep_is_recorded_green", [str(SWEEP)])
        return
    from spec_checks import run_all as runner

    faults = []
    summary = load(SWEEP)
    ran = {row["gate"] for row in summary["gates"]}
    expected = set(runner.selected_gates("fast"))
    if ran != expected:
        faults.append(f"the record covers {len(ran)} of {len(expected)} fast gates")
    failing = [
        row["gate"] for row in summary["gates"]
        if row["exit_code"] != 0 and row["gate"] != Path(__file__).name
    ]
    if failing:
        faults.append(f"{failing[:3]} failed")
    own = [row for row in summary["gates"] if row["gate"] == Path(__file__).name]
    if not own:
        faults.append("this gate is not in the fast set")
    record("check_02d_the_fast_sweep_is_recorded_green", not faults,
           "; ".join(faults[:4]))


# --- 03 T2: the exemption ------------------------------------------------------


def check_03a_the_predicate_was_frozen_before_it_was_measured() -> None:
    """Positive 3a: one hash, in the freeze, in the measurement and in the run.

    The freeze exists so that the numbers cannot have been chosen to make a
    measurement come out. That is only worth anything if the thing measured and
    the thing shipped are the thing frozen, so all three records are compared to
    the file as it stands.
    """
    faults = []
    current = sha256_of(ADJACENT_CONFIG)
    freeze = load(FREEZE)
    if freeze["sha256"] != current:
        faults.append("the configuration changed after it was frozen")
    if load(MEASUREMENT)["predicate_sha256"] != current:
        faults.append("the measurement was taken under a different configuration")
    if load(RUN).get("initial_adjacent_sha256") != current:
        faults.append("the run was made under a different configuration")
    declared = json.loads(ADJACENT_CONFIG.read_text(encoding="utf-8"))
    for key in ("initial_adjacent_ratio", "initial_adjacent_chars",
                "initial_adjacent_tolerance"):
        if key not in declared:
            faults.append(f"{key} is not declared")
            continue
        if f"{key}_allowed_range" not in declared:
            faults.append(f"{key} has no declared range")
    record("check_03a_the_predicate_was_frozen_before_it_was_measured", not faults,
           "; ".join(faults[:4]))


def check_03b_the_measurement_covers_the_corpus_both_ways() -> None:
    """Positive 3b: six samples, and the reverse direction counted, not assumed.

    A one directional count would say the change repairs two things and say
    nothing about what it breaks. The reverse count and the graphics count are
    what make the claim two sided.
    """
    faults = []
    measurement = load(MEASUREMENT)
    totals = measurement["totals"]
    if totals["samples"] != 6:
        faults.append(f"{totals['samples']} sample(s) measured, expected 6")
    if totals["reclassified"] != len(measurement["reclassified"]):
        faults.append("the reclassified total disagrees with its rows")
    if totals["reverse"] != 0:
        faults.append(f"{totals['reverse']} composition(s) became formulas")
    if totals["pages_with_graphics_moved"] != 0:
        faults.append("a page's curve or form count moved")
    if "process_page" not in measurement["method"]:
        faults.append("the measurement does not say it drove the real stage")
    record("check_03b_the_measurement_covers_the_corpus_both_ways", not faults,
           "; ".join(faults[:4]))


def check_03c_no_reclassified_run_carries_a_graphic() -> None:
    """Negative 3c: the absolute item of CLAUDE.md section 4.18, as a count.

    PdfLine has neither pdf_form nor pdf_curve and pdf_creater is the only place
    those are drawn from a formula, so reclassifying a composition that carries
    one loses the graphic with no error anywhere. The count is taken rather than
    inherited, which is what makes zero an assertion.
    """
    faults = []
    measurement = load(MEASUREMENT)
    carriers = [
        row for row in measurement["reclassified"]
        if row["pdf_form"] or row["pdf_curve"]
    ]
    if carriers:
        faults.append(f"{len(carriers)} reclassified run(s) carry a graphic")
    if measurement["totals"]["carrying_pdf_form_or_curve"] != len(carriers):
        faults.append("the carrier total disagrees with its rows")
    inventory = load(INVENTORY)
    absolute = inventory["absolute_item"]
    if absolute["carrying_pdf_form_or_curve"] != 0:
        faults.append("the inventory records a carrier")
    if absolute["page_level_graphics_moved"] != 0:
        faults.append("the inventory records a page whose graphics moved")
    record("check_03c_no_reclassified_run_carries_a_graphic", not faults,
           "; ".join(faults[:4]))


def check_03d_the_inventory_was_made_for_this_batch() -> None:
    """Positive 3d: a consumer inventory built against this tree, not reused.

    CLAUDE.md section 4.18 forbids reuse. The inventory proves it is not reused
    by locating every site it names in the current tree by anchor text; this
    re-checks that here so a site that moves after the inventory was written
    fails a gate rather than sitting in a file nobody re-runs.
    """
    faults = []
    inventory = load(INVENTORY)
    if inventory["rule"] != "CLAUDE.md 4.18":
        faults.append("the inventory does not name the rule it answers")
    if inventory["sites_total"] < 15:
        faults.append(f"only {inventory['sites_total']} site(s) inventoried")
    for site in inventory["sites"]:
        path = ROOT / site["file"]
        if not path.is_file():
            faults.append(f"{site['file']} is gone")
            continue
        if site["anchor"] not in path.read_text(encoding="utf-8"):
            faults.append(f"{site['file']}: the anchor has moved")
        if not site.get("verdict"):
            faults.append(f"{site['file']}: no verdict")
    render_site = [
        site for site in inventory["sites"] if site.get("absolute")
    ]
    if not render_site:
        faults.append("no site is marked as the absolute one")
    record("check_03d_the_inventory_was_made_for_this_batch", not faults,
           "; ".join(faults[:4]))


def check_03e_every_reclassified_run_was_judged() -> None:
    """Positive 3e: the stopping condition was evaluated, row by row.

    The plan makes one finding a stop: a real superscript or a real formula
    among the reclassified runs. A review that reports a verdict without a row
    for each of them has not evaluated the condition.
    """
    faults = []
    review = load(REVIEW)
    measurement = load(MEASUREMENT)
    judged = review["reclassified"]
    if len(judged) != measurement["totals"]["reclassified"]:
        faults.append("the review does not cover every reclassified run")
    for row in judged:
        if "judgement" not in row or len(row["judgement"]) < 40:
            faults.append(f"{row.get('sample')}: no judgement")
        if row.get("is_true_superscript") is not False:
            faults.append(f"{row.get('sample')}: a true superscript was accepted")
    if review["verdict"].startswith("triggered"):
        faults.append("the stopping condition fired and the task continued")
    intersection = review["intersection_with_b11_3_corner_mark_tally"]
    if intersection["in_this_family"] + len(intersection["out_of_family"]) < 3:
        faults.append("the intersection with b11.3's tally is not accounted for")
    record("check_03e_every_reclassified_run_was_judged", not faults,
           "; ".join(faults[:4]))


def check_03f_the_opening_word_reaches_the_page_whole() -> None:
    """Positive 3f: the drop cap paragraph is set at one size, with no residue.

    Three things at once, because the defect was three things at once: an
    enlarged Chinese character where the source had an enlarged Latin one, a gap
    beside it where the run stood proud of the line, and the source letters
    themselves left untranslated in the middle of it.
    """
    faults = []
    render = load(RENDER)
    page = next(p for p in render["per_page"] if p["page"] == DROP_CAP_PAGE)
    column = [
        line for line in page_lines(page)
        if 360 < line["bbox"][0] < 540 and line["bbox"][1] < 260
    ]
    if not column:
        faults.append("the column is not on the page")
    big = [line for line in column if line["max_size"] > BIG_GLYPH]
    if big:
        faults.append(f"{len(big)} oversized glyph(s) remain: {big[0]['text']!r}")
    tops = sorted({round(line["bbox"][1], 2) for line in column})
    gaps = [round(b - a, 3) for a, b in zip(tops, tops[1:], strict=False)]
    if gaps:
        smallest = min(gaps)
        worst = max(gaps)
        if worst > smallest * LINE_SPACING_TOLERANCE:
            faults.append(f"line spacing runs {smallest} to {worst}")
    if re.search(rf"\b{RESIDUE}\b", document_blob(render)):
        faults.append("the source residue is still on a page")
    record("check_03f_the_opening_word_reaches_the_page_whole", not faults,
           "; ".join(faults[:4]))


def check_03g_the_initial_was_merged_into_its_text() -> None:
    """Positive 3g: the drop cap merge acted, where before it reported nothing.

    b11.4 recorded this same paragraph, under the same ruling, with zero
    characters merged: the guard refused because the tail was a formula. The
    count is the mechanism half of what the page shows.
    """
    faults = []
    report = sidecar("drop_cap_apply.report.json")
    rows = [
        row for row in report["decisions"]
        if row["paragraph"] == DROP_CAP_REFERENCE
    ]
    if len(rows) != 1:
        faults.append(f"{len(rows)} decision(s) for {DROP_CAP_REFERENCE}")
    for row in rows:
        if row["decision"] != "flatten":
            faults.append(f"decided {row['decision']!r}")
        if not row["merged"] or row["characters_merged"] < 1:
            faults.append("nothing was merged")
        if not row["unicode_before"].startswith(DROP_CAP_SOURCE_HEAD[:12]):
            faults.append("the paragraph is not the one this names")
    record("check_03g_the_initial_was_merged_into_its_text", not faults,
           "; ".join(faults[:4]))


def check_03h_a_kept_drop_cap_is_not_merged() -> None:
    """Negative 3h: the exemption did not make every verdict a merge.

    Keeping a drop cap is a legitimate ruling and the enlarged style run is how
    it is carried, so a paragraph ruled ``keep`` must come through untouched
    even though its tail is now mergeable. Driven on a stub, both verdicts, so
    the difference is the verdict and nothing else.
    """
    faults = []
    config = drop_cap.load_drop_cap_config()

    kept = opening_paragraph(39.36)
    before = len(kept.pdf_paragraph_composition)
    outcome = drop_cap._unchanged(kept, config)
    if outcome["characters_merged"] != 0:
        faults.append("the unchanged record claims a merge")
    if len(kept.pdf_paragraph_composition) != before:
        faults.append("a kept paragraph was recomposed")

    flattened = opening_paragraph(39.36)
    acted = drop_cap.flatten(flattened, config)
    if not acted["merged"] or acted["characters_merged"] < 2:
        faults.append("a flattened paragraph was not merged")
    if len(flattened.pdf_paragraph_composition) != 1:
        faults.append("the flattened paragraph is still in two compositions")
    record("check_03h_a_kept_drop_cap_is_not_merged", not faults,
           "; ".join(faults[:4]))


def check_03i_a_formula_tail_still_refuses_the_merge() -> None:
    """Negative 3i: the guard itself was not touched.

    The repair is that fewer things are formulas, not that formulas became
    mergeable. A paragraph whose tail really is a formula must still be left
    alone, or the engine would be asked to reflow a unit it is required to carry
    whole.
    """
    faults = []
    config = drop_cap.load_drop_cap_config()
    paragraph = formula_tail_paragraph()
    outcome = drop_cap.flatten(paragraph, config)
    if outcome["merged"] or outcome["characters_merged"] != 0:
        faults.append("a formula tail was merged")
    if paragraph.pdf_paragraph_composition[1].pdf_formula is None:
        faults.append("the formula was rewritten")
    record("check_03i_a_formula_tail_still_refuses_the_merge", not faults,
           "; ".join(faults[:4]))


def check_03j_the_exemption_reaches_only_an_enlarged_opening() -> None:
    """Negative 3j: an ordinary paragraph gets no exemption at all.

    The span is the whole reach of this change, so a paragraph that does not
    open with an enlarged run must produce an empty one. Measured on stubs at
    both sides of the declared ratio.
    """
    faults = []
    ratio, reach, _ = sf.load_initial_adjacent()

    plain = opening_paragraph(9.25)
    if sf.initial_adjacent_exemption(plain) != (0, 0):
        faults.append("a paragraph set at one size was given an exemption")

    under = opening_paragraph(9.25 * ratio - 0.5)
    if sf.initial_adjacent_exemption(under) != (0, 0):
        faults.append("a run under the declared ratio was given an exemption")

    over = opening_paragraph(9.25 * ratio + 0.5)
    span = sf.initial_adjacent_exemption(over)
    if span != (1, 1 + reach):
        faults.append(f"an enlarged opening produced {span}, expected {(1, 1 + reach)}")
    record("check_03j_the_exemption_reaches_only_an_enlarged_opening", not faults,
           "; ".join(faults[:4]))


def check_03k_the_detectors_did_not_find_more() -> None:
    """Negative 3k: nothing this batch changed raised a detector count.

    Compared against b11.4, which is the same tree but for this batch's four
    repairs. A count that fell is fine and one that rose is not: the repair is
    meant to remove an untranslated residue, not to trade it for something else.
    """
    faults = []
    try:
        before = load(PRIOR_DIR / SAMPLE / "sidecars" / "issues.json")
    except evidence.EvidenceMissing as missing:
        skip("check_03k_the_detectors_did_not_find_more", [str(missing)])
        return
    after = sidecar("issues.json")
    for kind, count in (after["counts"]["by_kind"]).items():
        was = before["counts"]["by_kind"].get(kind, 0)
        if count > was:
            faults.append(f"{kind}: {was} -> {count}")
    if after["counts"]["issues"] > before["counts"]["issues"]:
        faults.append(
            f"issues {before['counts']['issues']} -> {after['counts']['issues']}"
        )
    record("check_03k_the_detectors_did_not_find_more", not faults,
           "; ".join(faults[:4]))


# --- 04 T3: the indent policy --------------------------------------------------


def check_04a_every_body_paragraph_is_indented() -> None:
    """Positive 4a: the declared mode reached every paragraph it declares for.

    zh declares ``all``, so a body paragraph without the flag is the policy
    failing to apply rather than a paragraph the source happened not to indent.
    """
    faults = []
    report = sidecar(indent_policy.REPORT_NAME)
    if report["mode"] != "all" or report["mode_source"] != "declared":
        faults.append(f"ran under {report['mode']!r} from {report['mode_source']!r}")
    body = [
        row for row in report["paragraphs"]
        if row["layout_label"] in report["body_labels"]
    ]
    if not body:
        faults.append("no body paragraph was seen")
    missing = [row["reference"] for row in body if not row["after"]]
    if missing:
        faults.append(f"{len(missing)} body paragraph(s) unindented: {missing[:3]}")
    undecided = [row["reference"] for row in body if not row["decided"]]
    if undecided:
        faults.append(f"{len(undecided)} body paragraph(s) undecided")
    record("check_04a_every_body_paragraph_is_indented", not faults,
           "; ".join(faults[:4]))


def check_04b_nothing_outside_the_body_was_decided() -> None:
    """Negative 4b: titles, captions and the rest were left as they were.

    The surface is the whole safety of this pass. A rule written for running
    text is wrong for a heading and wrong for a masthead list, so anything
    outside the declared labels must come through undecided -- not merely
    unchanged, which a rule that happened to agree would also produce.
    """
    faults = []
    report = sidecar(indent_policy.REPORT_NAME)
    outside = [
        row for row in report["paragraphs"]
        if row["layout_label"] not in report["body_labels"]
    ]
    if not outside:
        faults.append("no paragraph outside the body labels was seen")
    decided = [row["reference"] for row in outside if row["decided"]]
    if decided:
        faults.append(f"{len(decided)} outside paragraph(s) decided: {decided[:3]}")
    moved = [
        row["reference"] for row in outside if row["before"] != row["after"]
    ]
    if moved:
        faults.append(f"{len(moved)} outside paragraph(s) changed")
    labels = {row["layout_label"] for row in outside}
    if "title" not in labels:
        faults.append("no title was among them, so the negative proves nothing")
    record("check_04b_nothing_outside_the_body_was_decided", not faults,
           "; ".join(faults[:4]))


def check_04c_the_switch_down_changes_nothing(tmp_path: Path | None = None) -> None:
    """Negative 4c: with the switch down the document comes back untouched.

    Driven rather than reasoned: the pass is run over a stub document with the
    switch down and with it up, and what is compared is the flag on every
    paragraph. A default that had drifted up would fail here.
    """
    import tempfile

    faults = []
    with tempfile.TemporaryDirectory() as directory:
        working = Path(directory)
        paragraphs = [opening_paragraph(9.25), opening_paragraph(9.25)]
        paragraphs[1].layout_label = "title"
        document = labeled_document(paragraphs)
        before = [bool(p.first_line_indent) for p in paragraphs]

        down = StubConfig(working, magazine_indent_policy=False)
        if indent_policy.apply(down, document) is not None:
            faults.append("the pass acted with its switch down")
        if [bool(p.first_line_indent) for p in paragraphs] != before:
            faults.append("a flag moved with the switch down")

        absent = StubConfig(working)
        if indent_policy.apply(absent, document) is not None:
            faults.append("the pass acted with no switch set at all")
        if [bool(p.first_line_indent) for p in paragraphs] != before:
            faults.append("a flag moved with no switch set")

        up = StubConfig(working, magazine_indent_policy=True)
        report = indent_policy.apply(up, document)
        if report is None:
            faults.append("the pass did not act with its switch up")
        elif [bool(p.first_line_indent) for p in paragraphs] == before:
            faults.append("the switch up changed nothing, so the negative is empty")
    record("check_04c_the_switch_down_changes_nothing", not faults,
           "; ".join(faults[:4]))


def check_04d_the_indent_is_on_the_page() -> None:
    """Positive 4d: the flag became an offset the reader can see.

    The flag and the offset are two different things and neither implies the
    other: the stage could read the flag and set nothing. Measured on the laid
    out document, over every multi-line body paragraph, because a one line
    paragraph has no second line to be offset from.
    """
    faults = []
    document = load(INDENT)
    report = sidecar(indent_policy.REPORT_NAME)
    labels = set(report["body_labels"])
    body = [
        row for row in document["paragraphs"]
        if row["layout_label"] in labels and row["lines"] > 1
    ]
    if len(body) < 10:
        faults.append(f"only {len(body)} multi-line body paragraph(s) to measure")
    flat = [row["reference"] for row in body if row["offset"] < 5.0]
    if flat:
        faults.append(f"{len(flat)} set flush: {flat[:3]}")
    on_page = [row for row in body if row["page"] == DROP_CAP_PAGE]
    if not on_page:
        faults.append(f"nothing to measure on p{DROP_CAP_PAGE}")
    record("check_04d_the_indent_is_on_the_page", not faults,
           "; ".join(faults[:4]))


def check_04e_an_unclaimed_language_falls_back() -> None:
    """Negative 4e: a target language no entry claims keeps today's behaviour.

    The fallback is what makes this pass safe to leave on for a corpus whose
    other directions nobody has ruled about. Matched by longest prefix, as every
    other by-target table in this project is, so a region tag reaches its
    language's rule.
    """
    faults = []
    config = indent_policy.load_indent_config()
    if config.mode_for("zh") != ("all", "declared"):
        faults.append(f"zh resolves to {config.mode_for('zh')}")
    if config.mode_for("zh-CN")[0] != "all":
        faults.append("a region tag does not reach its language's rule")
    for tag in ("en", "fr", "ja"):
        mode, origin = config.mode_for(tag)
        if origin != "fallback" or mode != indent_policy.MODE_SOURCE:
            faults.append(f"{tag} resolves to {mode!r} from {origin!r}")
    if indent_policy.decide("plain text", indent_policy.MODE_SOURCE, False, 1, config) is not None:
        faults.append("the source mode decided something")
    record("check_04e_an_unclaimed_language_falls_back", not faults,
           "; ".join(faults[:4]))


def check_04f_the_declared_amount_matches_the_stage() -> None:
    """Positive 4f: the number in the configuration is the number the stage uses.

    ``indent_em`` is a pin and not a control: the amount lives in the
    typesetting stage and this pass decides only whether a paragraph is
    indented. Declaring it without holding the stage to it would let the file
    describe a page it does not produce, so the multiplier is read out of the
    stage's source and compared. W-B11-16 records what this number is.
    """
    faults = []
    config = indent_policy.load_indent_config()
    source = TYPESETTING.read_text(encoding="utf-8")
    match = re.search(
        r"if paragraph\.first_line_indent:\s*\n\s*current_x \+= space_width \* (\d+)",
        source,
    )
    if match is None:
        faults.append("the stage no longer applies the indent as a space multiple")
    elif int(match.group(1)) != config.indent_em:
        faults.append(
            f"the stage uses {match.group(1)}, the configuration declares "
            f"{config.indent_em}"
        )
    if "W-B11-16" not in WAIVERS.read_text(encoding="utf-8"):
        faults.append("the pin is not registered")
    record("check_04f_the_declared_amount_matches_the_stage", not faults,
           "; ".join(faults[:4]))


def check_04g_the_two_writers_of_the_flag_do_not_meet() -> None:
    """Negative 4g: the title pass and this one act on disjoint paragraphs.

    Both write ``first_line_indent``. The title pass writes it after the stage
    and only on titles; this one writes it before the stage and only on body
    labels. If the two sets overlapped, whichever ran last would silently
    decide, so the disjointness is asserted from both ends on this run's own
    records.
    """
    faults = []
    indent = sidecar(indent_policy.REPORT_NAME)
    mine = {
        row["reference"] for row in indent["paragraphs"] if row["decided"]
    }
    try:
        titles = sidecar("title_typeset.report.json")
    except evidence.EvidenceMissing as missing:
        skip("check_04g_the_two_writers_of_the_flag_do_not_meet", [str(missing)])
        return
    theirs = set()
    for row in titles.get("paragraphs") or titles.get("records") or []:
        reference = row.get("reference") or row.get("paragraph")
        if reference:
            theirs.add(reference)
    overlap = sorted(mine & theirs)
    if overlap:
        faults.append(f"{len(overlap)} paragraph(s) written by both: {overlap[:3]}")
    if not mine:
        faults.append("this pass decided nothing, so the negative proves nothing")
    record("check_04g_the_two_writers_of_the_flag_do_not_meet", not faults,
           "; ".join(faults[:4]))


# --- 05 T4: the rulings and the gaps -------------------------------------------


def check_05a_the_three_rows_were_ruled_by_a_person() -> None:
    """Positive 5a: every drafted row carries a verdict, and the file holds it.

    The draft exists to be filled in by a person and the batch is not allowed
    past an empty verdict. Both halves are asserted: the draft is complete, and
    what it says is what the ruling file now says.
    """
    faults = []
    draft = load(DRAFT)
    rulings = load(RULINGS)
    decisions = json.loads(
        (ROOT / "reviews" / f"{SAMPLE}.decisions.json").read_text(encoding="utf-8")
    )
    for row in draft["rows"]:
        if not row.get("verdict"):
            faults.append(f"{row['source']!r} is unruled")
    for source, target in RULED_ROWS.items():
        if decisions["terms"].get(source) != target:
            faults.append(
                f"{source!r} is ruled {decisions['terms'].get(source)!r} in the file"
            )
    if rulings["decisions_sha256_after"] != sha256_of(
        ROOT / "reviews" / f"{SAMPLE}.decisions.json"
    ):
        faults.append("the ruling file changed after the rulings were recorded")
    if draft["prompt_sha256"] != rulings["prompt_sha256"]:
        faults.append("the draft and the record name different prompts")
    record("check_05a_the_three_rows_were_ruled_by_a_person", not faults,
           "; ".join(faults[:4]))


def check_05b_the_rulings_are_on_the_page() -> None:
    """Positive 5b: each ruled form is set where the entry stands.

    Normalised before comparing, because a rendered document can carry a CJK
    compatibility ideograph where the ruling carries the unified one, and this
    batch's own ruling does exactly that.
    """
    faults = []
    render = load(RENDER)
    page = next(
        (p for p in render["per_page"] if p["page"] == MASTHEAD_PAGE), None
    )
    if page is None:
        record("check_05b_the_rulings_are_on_the_page", False,
               f"p{MASTHEAD_PAGE} is absent")
        return
    blob = normalise(page_blob(page))
    for source, target in RULED_ROWS.items():
        if normalise(target) not in blob:
            faults.append(f"{source!r}: the ruled form is not on the page")
        if source in blob:
            faults.append(f"{source!r}: the source form is still on the page")
    record("check_05b_the_rulings_are_on_the_page", not faults,
           "; ".join(faults[:4]))


def check_05c_the_shape_blind_spots_are_registered() -> None:
    """Positive 5c: three shapes registered as a gap rather than patched.

    The rule was left alone deliberately: three regexes for three shapes would
    turn a shape rule into a list of shapes already seen. What the batch owes
    instead is a gap entry that says so.
    """
    faults = []
    text = GAP_REGISTER.read_text(encoding="utf-8")
    for gap in GAPS:
        if f"## {gap} " not in text:
            faults.append(f"{gap} is not registered")
    harvest = text.split("## GAP-39", 1)
    if len(harvest) != 2:
        faults.append("GAP-39 has no body")
    else:
        body = harvest[1].split("\n## ", 1)[0]
        for source in RULED_ROWS:
            if source not in body:
                faults.append(f"GAP-39 does not name {source!r}")
    harvest_config = ROOT / "babeldoc" / "magazine" / "name_harvest.py"
    if not harvest_config.is_file():
        faults.append("the harvest module is gone")
    record("check_05c_the_shape_blind_spots_are_registered", not faults,
           "; ".join(faults[:4]))


def check_05d_the_corrected_observation_says_it_was_corrected() -> None:
    """Positive 5d: the observation the plan misdescribed is registered as measured.

    The plan recorded T5.2 as a one-character-per-line strip on a named
    paragraph. The run shows that paragraph on one line and shows a different
    paragraph scaled down instead. Registering the plan's wording would send a
    later reader to repair something that is not there, so the entry has to
    carry both the measurement and the correction.
    """
    faults = []
    text = GAP_REGISTER.read_text(encoding="utf-8")
    body = text.split("## GAP-40", 1)
    if len(body) != 2:
        faults.append("GAP-40 has no body")
    else:
        entry = body[1].split("\n## ", 1)[0]
        if "scale" not in entry:
            faults.append("GAP-40 does not record the scale it measured")
        if "PLAN_B11_5_REV2" not in entry:
            faults.append("GAP-40 does not say which plan it corrects")
        if "p5#9" not in entry or "p5#16" not in entry:
            faults.append("GAP-40 does not anchor both paragraphs")
    record("check_05d_the_corrected_observation_says_it_was_corrected", not faults,
           "; ".join(faults[:4]))


# --- 06 conservation, cost and scope -------------------------------------------


def check_06a_the_document_is_the_same_document() -> None:
    """Positive 6a: nine pages, and every paragraph anchor the baseline has.

    The four repairs are meant to change how text is set and which text is sent,
    never how many paragraphs there are. Anchored on page and index, never on a
    debug id (CLAUDE.md section 5.13).
    """
    faults = []
    conservation = load(CONSERVATION)
    if conservation["pages"] != 9:
        faults.append(f"{conservation['pages']} page(s)")
    if conservation.get("baseline_pages") not in (None, 9):
        faults.append(f"baseline has {conservation['baseline_pages']} page(s)")
    for label, row in sorted(conservation["per_page"].items(), key=lambda kv: int(kv[0])):
        baseline = row.get("baseline_paragraphs")
        if baseline is None:
            continue
        if row["paragraphs"] != baseline:
            faults.append(f"p{label}: {baseline} -> {row['paragraphs']} paragraph(s)")
        missing = sorted(set(row.get("baseline_text", {})) - set(row["text"]))
        if missing:
            faults.append(f"p{label}: lost anchors {missing[:3]}")
    run = load(RUN)
    if run["output_pages"] != run["input_pages"]:
        faults.append(f"{run['input_pages']} in, {run['output_pages']} out")
    record("check_06a_the_document_is_the_same_document", not faults,
           "; ".join(faults[:4]))


def check_06b_every_new_request_has_a_cause() -> None:
    """Positive 6b: the ledger balances and no new prompt is unexplained.

    The identity alone says how many calls were made, not why. What this adds is
    that every prompt this run built and the previous run did not is attributed
    to one of this batch's tasks.
    """
    faults = []
    run = load(RUN)
    if run["requests"] - run["cache_hits"] != run["api_calls"]:
        faults.append("the ledger does not balance")
    cost = load(COST)
    if cost["unattributed"]:
        faults.append(f"{len(cost['unattributed'])} unattributed prompt(s)")
    if not cost["covers_api_calls"]:
        faults.append(
            f"{cost['prompts_new_to_this_run']} new prompt(s) do not cover "
            f"{cost['ledger']['api_calls']} call(s)"
        )
    if sum(cost["by_cause"].values()) != cost["prompts_new_to_this_run"]:
        faults.append("the causes do not sum to the new prompts")
    record("check_06b_every_new_request_has_a_cause", not faults,
           "; ".join(faults[:4]))


def check_06c_the_batch_is_inside_its_budget() -> None:
    """Positive 6c: this batch's directory is under the ceiling the plan set."""
    total = sum(
        path.stat().st_size for path in BATCH_DIR.rglob("*") if path.is_file()
    )
    record(
        "check_06c_the_batch_is_inside_its_budget",
        total < ARTEFACT_CEILING_BYTES,
        f"{total / 1e9:.2f} GB, ceiling {ARTEFACT_CEILING_BYTES / 1e9:.2f} GB",
    )


def check_06d_the_delta_is_inside_the_declared_scope() -> None:
    """Negative 6d: nothing outside the declared surface was written."""
    faults = []
    for path in changed_paths():
        if not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            faults.append(path)
    record("check_06d_the_delta_is_inside_the_declared_scope", not faults,
           f"outside the surface: {faults[:4]}")


def check_06e_the_read_only_trees_were_not_written() -> None:
    """Negative 6e: the prompt files and the corpus were read and not touched.

    ``prompts/`` in particular: T4 put three names to the transliteration
    prompt, and the plan forbids changing a word of it, so a run that had
    reworded it to get a better candidate would fail here.
    """
    faults = []
    for path in changed_paths():
        for tree in READ_ONLY_TREES:
            if path.startswith(tree):
                faults.append(path)
    record("check_06e_the_read_only_trees_were_not_written", not faults,
           f"written: {faults[:4]}")


def check_06f_the_upstream_edits_are_registered() -> None:
    """Positive 6f: both upstream files are in the register, per function.

    One of them is outside the plan's declared surface and is there because the
    plan named a window with no magazine hook in it; that is a waiver, and a
    waiver that is not written down is a scope creep.
    """
    faults = []
    register = UPSTREAM_DIFF.read_text(encoding="utf-8")
    if "## B11.5" not in register:
        faults.append("this batch has no section in the register")
    for path in UPSTREAM_FILES:
        if path not in register.split("## B11.5", 1)[-1]:
            faults.append(f"{path} is not registered for this batch")
    waivers = WAIVERS.read_text(encoding="utf-8")
    if "W-B11-15" not in waivers:
        faults.append("the scope extension is not waived")
    record("check_06f_the_upstream_edits_are_registered", not faults,
           "; ".join(faults[:4]))


def check_06g_the_gate_declares_what_it_reads() -> None:
    """Positive 6g: every declared evidence path exists and is read.

    The declaration is what the retention policy walks around (CLAUDE.md section
    4.16), so a path declared and never read grows the protected set for
    nothing, and a path read and never declared is one prune away from stranding
    this gate.
    """
    faults = []
    source = Path(__file__).read_text(encoding="utf-8")
    for entry in GATE_EVIDENCE:
        path = ROOT / entry
        if path == SWEEP:
            # Declared so the retention policy walks around it, and exempt from
            # the existence check for one reason: it is the record of a sweep
            # this gate runs inside. Requiring it here would make the gate fail
            # the very sweep that produces it. Its absence is not passed over --
            # 2d reports it, as a skip naming the missing file.
            continue
        try:
            evidence.read_bytes(path)
        except evidence.EvidenceMissing:
            faults.append(f"{entry} is in neither the workspace nor the archive")
    for name in ("render_evidence.json", "indent_evidence.json",
                 "t2_measurement.json", "t2_consumer_inventory.json"):
        if not any(name in entry for entry in GATE_EVIDENCE):
            faults.append(f"{name} is read but not declared")
        if name not in source:
            faults.append(f"{name} is declared but not read")
    record("check_06g_the_gate_declares_what_it_reads", not faults,
           "; ".join(faults[:4]))


def check_06h_no_assertion_anchors_on_a_run_local_identifier() -> None:
    """Negative 6h: nothing here is pinned to a debug id.

    A debug id is minted afresh on every run, so an assertion naming one is an
    assertion about the run that produced it. CLAUDE.md section 5.13.
    """
    faults = []
    source = Path(__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.fullmatch(r"[A-Za-z0-9]{5}", node.value) and not node.value.isalpha():
                faults.append(f"a five-character token {node.value!r}")
        if isinstance(node, ast.Attribute) and node.attr == "debug_id":
            faults.append("an attribute read of the identifier")
    # The evidence this gate reads, checked the same way: a row anchored on a
    # run local identifier would let an assertion written against it pass only
    # for the run that minted it.
    for path, key in (
        (CONSERVATION, None),
        (SIDECARS / indent_policy.REPORT_NAME, "paragraphs"),
    ):
        try:
            data = load(path)
        except evidence.EvidenceMissing:
            continue
        rows = data.get(key) or [] if key else []
        for row in rows:
            reference = row.get("reference")
            if reference and not re.fullmatch(r"p\d+#\d+", reference):
                faults.append(f"{path.name} anchors a row on {reference!r}")
                break
    record("check_06h_no_assertion_anchors_on_a_run_local_identifier", not faults,
           "; ".join(sorted(set(faults))[:4]))


def check_06i_the_premises_were_checked_before_anything_moved() -> None:
    """Positive 6i: the batch recorded a premise check, and it halted once.

    This batch's first plan was stopped on a false premise and replaced; the
    record of that stop is what makes the replacement a revision rather than a
    rewrite. CLAUDE.md section 5.14(a) and (b).
    """
    faults = []
    try:
        premise = load(PREMISE)
    except evidence.EvidenceMissing as missing:
        skip("check_06i_the_premises_were_checked_before_anything_moved",
             [str(missing)])
        return
    if premise.get("status") != "HALTED-ON-PREMISE-MISMATCH":
        faults.append("the premise record does not say the batch halted")
    verdicts = {key: row["verdict"] for key, row in premise["premises"].items()}
    if "FAIL" not in verdicts.values():
        faults.append("the record shows no failed premise")
    original = ROOT / "plans" / "PLAN_B11_5.md"
    revision = ROOT / "plans" / "PLAN_B11_5_REV2.md"
    if not original.is_file():
        faults.append("the superseded plan was deleted rather than kept")
    elif "SUPERSEDED" not in original.read_text(encoding="utf-8")[:2000]:
        faults.append("the superseded plan is not marked as superseded at its head")
    if not revision.is_file():
        faults.append("the revision is not in the tree")
    else:
        text = revision.read_text(encoding="utf-8")
        if "PLAN_B11_5" not in text:
            faults.append("the revision does not name what it supersedes")
    record("check_06i_the_premises_were_checked_before_anything_moved", not faults,
           "; ".join(faults[:4]))


CHECKS = (
    check_01a_the_label_is_recorded_as_unchanged,
    check_01b_the_label_is_set_in_its_source_form,
    check_01c_the_ruling_is_pinned_in_the_run_record,
    check_01d_the_repair_is_not_a_formula_annotation,
    check_02a_the_label_assertion_now_reads_this_run,
    check_02b_the_label_stands_on_one_line_today,
    check_02c_the_unrecoverable_control_is_reported_as_such,
    check_02d_the_fast_sweep_is_recorded_green,
    check_03a_the_predicate_was_frozen_before_it_was_measured,
    check_03b_the_measurement_covers_the_corpus_both_ways,
    check_03c_no_reclassified_run_carries_a_graphic,
    check_03d_the_inventory_was_made_for_this_batch,
    check_03e_every_reclassified_run_was_judged,
    check_03f_the_opening_word_reaches_the_page_whole,
    check_03g_the_initial_was_merged_into_its_text,
    check_03h_a_kept_drop_cap_is_not_merged,
    check_03i_a_formula_tail_still_refuses_the_merge,
    check_03j_the_exemption_reaches_only_an_enlarged_opening,
    check_03k_the_detectors_did_not_find_more,
    check_04a_every_body_paragraph_is_indented,
    check_04b_nothing_outside_the_body_was_decided,
    check_04c_the_switch_down_changes_nothing,
    check_04d_the_indent_is_on_the_page,
    check_04e_an_unclaimed_language_falls_back,
    check_04f_the_declared_amount_matches_the_stage,
    check_04g_the_two_writers_of_the_flag_do_not_meet,
    check_05a_the_three_rows_were_ruled_by_a_person,
    check_05b_the_rulings_are_on_the_page,
    check_05c_the_shape_blind_spots_are_registered,
    check_05d_the_corrected_observation_says_it_was_corrected,
    check_06a_the_document_is_the_same_document,
    check_06b_every_new_request_has_a_cause,
    check_06c_the_batch_is_inside_its_budget,
    check_06d_the_delta_is_inside_the_declared_scope,
    check_06e_the_read_only_trees_were_not_written,
    check_06f_the_upstream_edits_are_registered,
    check_06g_the_gate_declares_what_it_reads,
    check_06h_no_assertion_anchors_on_a_run_local_identifier,
    check_06i_the_premises_were_checked_before_anything_moved,
)


def main() -> int:
    print("spec_check_b11_5: a pinned label, an exempted rule, an indent policy\n")
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
