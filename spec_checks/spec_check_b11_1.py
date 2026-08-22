"""Gate script for batch B11.1 (identity write back, bounded hang, name policy).

Run from the repository root:

    python spec_checks/spec_check_b11_1.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: every assertion is answered from a stub this gate builds
itself, from what this batch's run froze, or from the produced PDFs where the
workspace still holds them.

What this batch is. Three changes, two of them upstream.

T1. The writer that applies a translation to a paragraph opens with a short
circuit for the case where the translation says what the source said. The
comparison was written against the input *object* rather than against the text
that object carries, so it was never true and the branch was dead: a reply
identical to its source was recomposed and relaid out anyway, in the font the
translation maps to rather than the one the source drew, and a three character
label whose box only fitted its own logo font came out folded on to two lines.
The comparison now reads the text, under a normalisation used for the decision
alone, and the branch does what it always said it did.

T2. A hung punctuation unit is exempt from the width check that ends a line,
which is correct and was unbounded. A run of them accumulated past the box edge
and struck through the column rule the page draws beyond it. The exemption now
carries a declared ceiling, and past it the hung run is pulled back on to the
next line together with the unit before it, so the new line does not open with
punctuation.

T3. The person name policy moves from ``transliterate`` to ``translate``: a
name is written in the target script and the source form is not put after it.
One value changes; the four policy texts and their pins do not.

01 is T1: the label on the page, the mechanism in the sidecar, and the whole set
of paragraphs the revived branch reaches.

02 is T2: the determination the bound was decided on, the page after it, the
bound refusing and admitting on stubs, and the configuration.

03 is T3: the names on the page and the prompt behind them.

04 is conservation and cost.

05 is scope: what this batch changed and what it did not.

Tiers: every assertion reads a stub, a committed artefact or a workspace PDF, so
the fast tier runs the whole gate.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il.midend import typesetting  # noqa: E402
from babeldoc.magazine.page_features import ConfigError  # noqa: E402
from spec_checks import harness  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b11.1"
PREVIOUS_TAG = "f3"

SAMPLE = "FD-en-v2"
BATCH_DIR = ROOT / "examples" / "output" / "b11_1"
RUN_DIR = BATCH_DIR / SAMPLE
ISOLATION_DIR = BATCH_DIR / f"{SAMPLE}.t12"
BASELINE_DIR = BATCH_DIR / f"{SAMPLE}.probe"
EVIDENCE = RUN_DIR / "evidence"

RUN_PDF = RUN_DIR / f"{SAMPLE}.b11_1.pdf"
BASELINE_PDF = (
    ROOT / "examples" / "output" / "F3" / "cold" / SAMPLE / f"{SAMPLE}.f3.pdf"
)
F3_SIDECARS = ROOT / "examples" / "output" / "F3" / "cold" / SAMPLE / "sidecars"

HANG_CONFIG = ROOT / "configs" / "typeset_hang.json"
STYLE_CONFIG = ROOT / "configs" / "translation_style.json"

# The delta this batch is allowed. A path outside it is a failure whatever it
# holds; a path inside it is not thereby required to have changed.
ALLOWED_PREFIXES = (
    "babeldoc/format/pdf/document_il/midend/il_translator.py",
    "babeldoc/format/pdf/document_il/midend/typesetting.py",
    "babeldoc/magazine/short_unit.py",
    "configs/translation_style.json",
    "configs/typeset_hang.json",
    "spec_checks/spec_check_b11_1.py",
    "spec_checks/run_all.py",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "docs/reports/assertion_contracts.md",
    "plans/PLAN_B11_1.md",
    "examples/output/b11_1/",
    # Two gates this batch's own arrival made false, and the archive that
    # arrival produced. Registered as W-B11-03 rather than left implicit: a
    # widened surface that is not written down is a surface never declared.
    # See contracts AC-09, AC-10 and AC-11.
    "spec_checks/spec_check_b10_4.py",
    "spec_checks/spec_check_e0.py",
    "docs/reports/archive/b10_4.zip",
)

# Trees this batch reads and never writes.
READ_ONLY_TREES = ("prompts/", "reviews/", "corpus/")

# Two spans of one label split across lines stand at the same left edge and a
# line apart. Both numbers are tolerances on a measurement, not thresholds on a
# decision: the layout either put the label on one line or it did not.
SAME_LEFT_EDGE = 0.5
LINE_APART = 8.0

# The five names the batch is verified on, by the Latin form the old policy put
# in brackets after the target form. Read off the page, not off a word list.
NAME_ANCHORS = (
    "Josh Lipsky",
    "Nicholas Mulder",
    "Kim Ruhl",
    "Chantal Jahchan",
    "Andreas Adriano",
)

# The detectors whose finding counts this batch may not raise.
NO_NEW_HARM = ("out_of_page", "text_text_collision")

# How a text difference between this run and the baseline, on a paragraph the
# revived short circuit now leaves standing, is accounted for.
KIND_NORMALISED = "normalisation_equal"
KIND_PLACEHOLDER = "baseline_placeholder_residue"
KIND_RESAMPLED = "baseline_translated"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b11_1")


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
        _, out = git_output(["diff", "--name-only", f"{BATCH_TAG}^..{BATCH_TAG}"])
        return [line.strip() for line in out.splitlines() if line.strip()]
    _, tracked = git_output(["diff", "--name-only", "HEAD"])
    _, untracked = git_output(["ls-files", "--others", "--exclude-standard"])
    return sorted(
        {line.strip() for line in (tracked + untracked).splitlines() if line.strip()}
    )


def evidence(name: str):
    return load_json(EVIDENCE / name)


def normalised(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def spans_of(pdf: Path, page_index: int, keep) -> list[dict]:
    import pymupdf

    found = []
    with pymupdf.open(pdf) as document:
        for block in document[page_index].get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if not keep(span):
                        continue
                    found.append(
                        {
                            "text": span["text"],
                            "font": span["font"],
                            "size": round(span["size"], 2),
                            "bbox": [round(value, 2) for value in span["bbox"]],
                        }
                    )
    return found


def split_pairs(spans: list[dict]) -> list[tuple[dict, dict]]:
    """Pairs of spans standing at one left edge, a line apart: one label folded."""
    pairs = []
    for upper in spans:
        for lower in spans:
            if upper is lower:
                continue
            if abs(upper["bbox"][0] - lower["bbox"][0]) > SAME_LEFT_EDGE:
                continue
            if lower["bbox"][1] - upper["bbox"][1] < LINE_APART:
                continue
            pairs.append((upper, lower))
    return pairs


# --- 01 the identity write back ------------------------------------------------


def check_01a_the_folded_label_is_one_line() -> None:
    """Positive 1a: what the baseline drew on two lines this run draws on one.

    The claim is about pixels, so it is answered off the two PDFs where the
    workspace holds them and off the frozen measurement otherwise, and the
    frozen measurement is compared against the recomputation where both exist.
    """
    frozen = evidence("pixel_evidence.json")
    band = frozen["head_band_points"]
    faults = []
    for pdf, key in ((BASELINE_PDF, "baseline_head_band"), (RUN_PDF, "run_head_band")):
        if not pdf.exists():
            print(f"SKIPPED: recomputation :: {pdf} is not in the workspace")
            continue
        for page in frozen["head_pages"]:
            fresh = spans_of(pdf, page - 1, lambda span: span["bbox"][1] < band)
            if fresh != frozen[key][str(page)]:
                faults.append(f"{key} p{page} recomputes differently from the frozen")
    for page in frozen["head_pages"]:
        was = frozen["baseline_head_band"][str(page)]
        now = frozen["run_head_band"][str(page)]
        folded = split_pairs(was)
        if not folded:
            faults.append(f"p{page}: the baseline folded no label, so nothing to fix")
            continue
        for upper, lower in folded:
            joined = upper["text"] + lower["text"]
            matching = [span for span in now if span["text"] == joined]
            if len(matching) != 1:
                faults.append(
                    f"p{page}: {joined!r} stands {len(matching)} times, wanted once"
                )
                continue
            single = matching[0]
            if "\n" in single["text"]:
                faults.append(f"p{page}: {joined!r} still carries a line break")
            height = single["bbox"][3] - single["bbox"][1]
            if height > single["size"] * 1.6:
                faults.append(
                    f"p{page}: {joined!r} is {height:.1f}pt tall at {single['size']}pt"
                )
        if split_pairs(now):
            faults.append(f"p{page}: a label is still split across two lines")
    record("check_01a_the_folded_label_is_one_line", not faults, "; ".join(faults[:6]))


def check_01b_the_writer_reports_what_it_skipped() -> None:
    """Positive 1b: the short unit sidecar says which units were left standing.

    The flag is the mechanism claim, and the composition digests beside it are
    the proof of what the flag means: a paragraph the writer skipped carries out
    of translation the composition it carried in.
    """
    report = load_json(RUN_DIR / "sidecars" / "short_unit.report.json")
    table = {
        row["ref"]: row
        for row in evidence("identity_writeback.json")["paragraphs"]
        if row["arm"] == "run"
    }
    faults = []
    identical = [
        unit for unit in report["units"] if unit["source"] == unit["translated"]
    ]
    if not identical:
        faults.append("no short unit reply equalled its source, so nothing to skip")
    for unit in report["units"]:
        expected = unit["source"] == unit["translated"]
        if unit.get("identity_skipped") is not expected:
            faults.append(
                f"{unit['paragraph']}: identity_skipped is "
                f"{unit.get('identity_skipped')!r}, wanted {expected!r}"
            )
        if not expected:
            continue
        row = table.get(unit["paragraph"])
        if row is None:
            faults.append(f"{unit['paragraph']}: skipped but absent from the table")
            continue
        if row["composition_sha256_before"] != row["composition_sha256_after"]:
            faults.append(f"{unit['paragraph']}: composition was rewritten after all")
        if not row["baseline_composition_rebuilt"]:
            faults.append(
                f"{unit['paragraph']}: the baseline did not rebuild it either, "
                f"so this batch changed nothing here"
            )
    record(
        "check_01b_the_writer_reports_what_it_skipped", not faults, "; ".join(faults[:6])
    )


def classify(row: dict) -> str | None:
    """How one paragraph's text came to differ from what the baseline wrote."""
    if not row["text_differs_from_baseline"]:
        return None
    if normalised(row["baseline_written"]) == normalised(row["source"]):
        return KIND_NORMALISED
    if re.fullmatch(r"(?:\{[^{}]*\}|[\d,.\s])+", row["baseline_written"] or ""):
        return KIND_PLACEHOLDER
    return KIND_RESAMPLED


def check_01c_the_whole_reached_set_is_accounted_for() -> None:
    """Positive 1c: every paragraph the branch reaches, and what changed on it.

    Two arms are recorded. The one that carries this batch's new prompt cannot
    separate a layout change from a fresh reply, so the sharp claim is made on
    the other: with the prompt held at the baseline's, the revived branch
    rewrites no text at all. Both arms have to satisfy the weaker claim, which
    is that a skipped paragraph carries its source and its own composition.
    """
    rows = evidence("identity_writeback.json")["paragraphs"]
    faults = []
    for arm in ("run", "isolation"):
        arm_rows = [row for row in rows if row["arm"] == arm]
        if not arm_rows:
            faults.append(f"{arm}: no paragraph recorded")
            continue
        for row in arm_rows:
            if row["composition_sha256_before"] != row["composition_sha256_after"]:
                faults.append(f"{arm} {row['ref']}: composition differs")
            kind = classify(row)
            if kind == KIND_RESAMPLED and arm == "isolation":
                faults.append(
                    f"isolation {row['ref']}: the baseline translated it and this "
                    f"arm did not, at an unchanged prompt"
                )
    record(
        "check_01c_the_whole_reached_set_is_accounted_for",
        not faults,
        "; ".join(faults[:6]),
    )


def check_01d_the_comparison_reads_the_text() -> None:
    """Negative 1d: the branch is reached by text and not by object identity."""
    from babeldoc.format.pdf.document_il.midend.il_translator import (
        _is_identity_write_back,
    )

    class Input:
        def __init__(self, unicode: str) -> None:
            self.unicode = unicode

    cases = (
        ("F&D", Input("F&D"), True, "an unchanged reply is identity"),
        (" F&D\n", Input("F&D"), True, "surrounding space is not what was said"),
        ("！", Input("!"), True, "a width variant is the same mark"),
        ("译文", Input("source"), False, "a translation is not identity"),
        ("", Input(""), True, "two empty texts are identity"),
        ("x", "x", True, "a non input falls back to the plain comparison"),
        ("x", "y", False, "a non input that differs is not identity"),
        ("x", object(), False, "an object is never equal to a string"),
    )
    faults = [
        f"{why}: got {_is_identity_write_back(text, given)!r}"
        for text, given, want, why in cases
        if _is_identity_write_back(text, given) is not want
    ]
    source = (
        ROOT / "babeldoc/format/pdf/document_il/midend/il_translator.py"
    ).read_text(encoding="utf-8")
    if "if translated_text == translate_input:" in source:
        faults.append("the dead comparison is still in the writer")
    record("check_01d_the_comparison_reads_the_text", not faults, "; ".join(faults[:6]))


# --- 02 the bound on hung punctuation ------------------------------------------


def check_02a_the_determination_stands() -> None:
    """Positive 2a: the overflow was the hang and not the box.

    The bound is only the right repair where the box itself stays inside the
    rule the page draws; a box already past the rule would be a different
    defect. The four numbers the determination was made on are frozen and
    rechecked here against each other.
    """
    frozen = evidence("hang_determination.json")
    before = frozen["before"]
    faults = []
    rule = before["column_rule_x"]
    if rule is None:
        faults.append("no vertical rule stands right of the box, so nothing to cross")
    elif before["box_x2"] >= rule:
        faults.append(
            f"box_x2 {before['box_x2']} is not left of the rule at {rule}: the "
            f"box is the defect, not the hang"
        )
    crossing = [
        row for row in before["overflow_by_span"] if row["crosses_rule"]
    ]
    if not crossing:
        faults.append("the baseline crossed no rule, so there was nothing to bound")
    if before["rightmost_ink_x"] <= before["box_x2"]:
        faults.append("the baseline hung nothing past the box")
    record("check_02a_the_determination_stands", not faults, "; ".join(faults[:6]))


def check_02b_the_mark_no_longer_reaches_the_rule() -> None:
    """Positive 2b: the pull quote's ink stops left of the rule, and stays bound."""
    frozen = evidence("hang_determination.json")
    before, after = frozen["before"], frozen["after"]
    faults = []
    rule = before["column_rule_x"]
    if rule is not None and after["rightmost_ink_x"] >= rule:
        faults.append(
            f"the mark still ends at {after['rightmost_ink_x']} against a rule at {rule}"
        )
    if RUN_PDF.exists():
        fresh = spans_of(
            RUN_PDF,
            3 - 1,
            lambda span: span["size"] > 18 and span["bbox"][0] > 200,
        )
        if fresh != after["spans"]:
            faults.append("the frozen spans do not recompute off the produced PDF")
    else:
        print(f"SKIPPED: recomputation :: {RUN_PDF} is not in the workspace")
    report = load_json(RUN_DIR / "sidecars" / "typeset_hang.report.json")
    if report["counts"].get(typesetting.HANG_UNCHANGED):
        faults.append(
            f"{report['counts'][typesetting.HANG_UNCHANGED]} hangs were left "
            f"unbounded because their retreat was refused"
        )
    for paragraph in report["paragraphs"]:
        for line in paragraph["lines"]:
            if line["verdict"] != typesetting.HANG_KEPT:
                continue
            if line["overflow"] > line["limit"]:
                faults.append(
                    f"{paragraph['paragraph']} line {line['line']}: hung "
                    f"{line['overflow']} past a limit of {line['limit']}"
                )
    if not report["paragraphs"]:
        faults.append("the sidecar records no hang at all, so it proves nothing")
    record(
        "check_02b_the_mark_no_longer_reaches_the_rule", not faults, "; ".join(faults[:6])
    )


class StubUnit:
    """The narrowest thing the line layout reads a typesetting unit through."""

    def __init__(self, text: str, width: float, hung: bool) -> None:
        self.unicode = text
        self.width = width
        self.height = width
        self.is_hung_punctuation = hung
        self.is_space = False
        self.is_cjk_char = True
        self.is_cannot_appear_in_line_end_punctuation = False
        self.mixed_character_blacklist = False
        self.font_size = width
        self.char = None
        self.box = None
        self.placed: tuple[float, float] | None = None

    def try_get_unicode(self) -> str:
        return self.unicode

    def relocate(self, x: float, y: float, scale: float) -> StubUnit:
        placed = StubUnit(self.unicode, self.width, self.is_hung_punctuation)
        placed.placed = (x, y)
        placed.box = type("Box", (), {"x": x, "y": y, "x2": x + self.width * scale,
                                      "y2": y + self.height * scale})()
        return placed


class StubFont:
    def char_lengths(self, text: str, size: float):
        return [size]


def lay_out(units: list[StubUnit], width: float, hang_log: list[dict]):
    """Drive the real line layout over stub units inside a box of one line."""
    layout = object.__new__(typesetting.Typesetting)
    layout.font_mapper = type("Mapper", (), {"base_font": StubFont()})()
    layout.is_cjk = True
    box = type("Box", (), {"x": 0.0, "y": -1000.0, "x2": width, "y2": 0.0})()
    paragraph = type("Paragraph", (), {"first_line_indent": False})()
    return typesetting.Typesetting._layout_typesetting_units(
        layout,
        units,
        box,
        1.0,
        1.0,
        paragraph,
        False,
        hang_log,
    )


def check_02c_a_line_of_punctuation_alone_keeps_the_old_behaviour() -> None:
    """Negative 2c: a retreat that would empty its line is refused and said so."""
    faults = []
    if typesetting.Typesetting._hang_retreat([]) is not None:
        faults.append("an empty line offered a retreat")
    only_hung = [{"is_hung": True, "placement_index": index} for index in range(3)]
    if typesetting.Typesetting._hang_retreat(only_hung) is not None:
        faults.append("a line of punctuation alone offered a retreat")
    one_unit = [{"is_hung": False, "placement_index": 0}]
    if typesetting.Typesetting._hang_retreat(one_unit) is not None:
        faults.append("a line of one unit offered a retreat that would empty it")
    healthy = [
        {"is_hung": False, "placement_index": 0},
        {"is_hung": False, "placement_index": 1},
        {"is_hung": True, "placement_index": 2},
        {"is_hung": True, "placement_index": 3},
    ]
    retreat = typesetting.Typesetting._hang_retreat(healthy)
    if retreat is None or retreat["placement_index"] != 1:
        faults.append(f"the retreat starts at {retreat} rather than the unit before")

    em = typesetting.load_hang_max_em()
    hang_log: list[dict] = []
    units = [StubUnit("。", 10.0, True), StubUnit("。", 10.0, True)]
    lay_out(units, 5.0, hang_log)
    verdicts = [line["verdict"] for line in hang_log]
    if typesetting.HANG_PULLED_BACK in verdicts:
        faults.append("a line of punctuation alone was pulled back")
    if typesetting.HANG_UNCHANGED not in verdicts:
        faults.append(f"a refused retreat was not recorded: {verdicts}")
    if em <= 0:
        faults.append(f"the declared ceiling is {em}, so nothing can hang")
    record(
        "check_02c_a_line_of_punctuation_alone_keeps_the_old_behaviour",
        not faults,
        "; ".join(faults[:6]),
    )


def check_02d_a_hang_inside_the_bound_is_not_pulled_back() -> None:
    """Negative 2d: the bound admits what it declares and refuses just past it.

    Two lines differing only in how far the mark ends past the box: the one
    inside the ceiling hangs, the one outside it retreats. Nothing about the
    ceiling's value is asserted here beyond that it is the thing separating them.
    """
    em = typesetting.load_hang_max_em()
    faults = []
    body_width, box_width = 10.0, 25.0
    # Two body units fill the box; the mark then ends `mark` past its edge.
    for mark, want in (
        (em * body_width * 0.9, typesetting.HANG_KEPT),
        (em * body_width * 1.1, typesetting.HANG_PULLED_BACK),
    ):
        units = [
            StubUnit("字", body_width, False),
            StubUnit("字", body_width, False),
            StubUnit("。", box_width - 2 * body_width + mark, True),
        ]
        hang_log: list[dict] = []
        lay_out(units, box_width, hang_log)
        verdicts = [line["verdict"] for line in hang_log]
        if verdicts != [want]:
            faults.append(f"a mark {mark:.2f}pt past the box recorded {verdicts}")
    record(
        "check_02d_a_hang_inside_the_bound_is_not_pulled_back",
        not faults,
        "; ".join(faults[:6]),
    )


def check_02e_the_ceiling_is_declared_and_bounded(tmp: Path) -> None:
    """Positive 2e: the length lives in configuration, bounded, and nowhere else."""
    faults = []
    raw = load_json(HANG_CONFIG)
    if "hang_max_em_allowed_range" not in raw:
        faults.append("the ceiling declares no allowed range")
    if set(raw) - {"description", "hang_max_em", "hang_max_em_allowed_range"}:
        faults.append(f"unexpected keys: {sorted(set(raw) - {'description'})}")
    broken = tmp / "typeset_hang.json"
    with broken.open("w", encoding="utf-8") as f:
        json.dump({**raw, "hang_max_em": 99.0}, f)
    try:
        typesetting.load_hang_max_em(str(broken))
    except ConfigError:
        pass
    else:
        faults.append("a ceiling outside its own range was accepted")
    source = (
        ROOT / "babeldoc/format/pdf/document_il/midend/typesetting.py"
    ).read_text(encoding="utf-8")
    if re.search(r"hang_limit\s*=\s*[0-9]", source):
        faults.append("the ceiling is written as a number in the code")
    record(
        "check_02e_the_ceiling_is_declared_and_bounded", not faults, "; ".join(faults[:6])
    )


# --- 03 the person name policy -------------------------------------------------


def check_03a_no_name_carries_its_source_form() -> None:
    """Positive 3a: the annotation the old policy allowed is gone from the page."""
    frozen = evidence("pixel_evidence.json")
    faults = []
    if frozen["run_name_annotations"]["name_shaped"]:
        faults.append(
            f"name shaped annotations remain: "
            f"{frozen['run_name_annotations']['name_shaped'][:3]}"
        )
    if not frozen["baseline_name_annotations"]["name_shaped"]:
        faults.append("the baseline carried none either, so nothing was shown")
    if RUN_PDF.exists() and BASELINE_PDF.exists():
        import pymupdf

        for pdf, key in ((RUN_PDF, "run"), (BASELINE_PDF, "baseline")):
            with pymupdf.open(pdf) as document:
                text = "".join(
                    document[index].get_text().replace("\n", "")
                    for index in range(document.page_count)
                )
            for anchor in NAME_ANCHORS:
                present = anchor in text
                if key == "run" and present:
                    faults.append(f"{anchor} still stands on the produced page")
                if key == "baseline" and not present:
                    faults.append(f"{anchor} was not on the baseline page either")
    else:
        print("SKIPPED: recomputation :: a produced PDF is not in the workspace")
    record(
        "check_03a_no_name_carries_its_source_form", not faults, "; ".join(faults[:6])
    )


def check_03b_the_policy_was_selected_and_nothing_was_rewritten() -> None:
    """Positive 3b: one value moved and every policy text stands as it stood."""
    faults = []
    run = load_json(RUN_DIR / "run.json")
    style = load_json(STYLE_CONFIG)
    selected = style["person_names"]
    if selected != "translate":
        faults.append(f"the selected policy is {selected!r}")
    if run["translation_style"]["person_names"] != selected:
        faults.append("the run recorded a different policy from the configuration")
    pinned = style["person_names_policy_sha256"][selected]["zh"]
    if run["translation_style"]["system_prompt_sha256"] != pinned:
        faults.append("the prompt the run built is not the pinned policy text")
    code, previous = git_output(["show", f"{PREVIOUS_TAG}:configs/translation_style.json"])
    if code != 0:
        print(f"SKIPPED: recomputation :: {PREVIOUS_TAG} is not in this repository")
    else:
        was = json.loads(previous)
        if was["person_names_policies"] != style["person_names_policies"]:
            faults.append("a policy text changed, and this batch may only select one")
        if was["person_names_policy_sha256"] != style["person_names_policy_sha256"]:
            faults.append("a policy pin changed")
        moved = {
            key
            for key in set(was) | set(style)
            if was.get(key) != style.get(key)
        }
        if moved != {"person_names"}:
            faults.append(f"the batch moved {sorted(moved)}, not person_names alone")
    record(
        "check_03b_the_policy_was_selected_and_nothing_was_rewritten",
        not faults,
        "; ".join(faults[:6]),
    )


# --- 04 conservation and cost --------------------------------------------------


def check_04a_the_document_is_conserved() -> None:
    """Positive 4a: pages, paragraph counts and paragraph names all hold."""
    faults = []
    run = load_json(RUN_DIR / "conservation.json")
    baseline = load_json(BASELINE_DIR / "conservation.json")
    if run["pages"] != baseline["pages"] or run["pages"] != run["baseline_pages"]:
        faults.append(
            f"pages {run['pages']} against {baseline['pages']} and "
            f"{run['baseline_pages']}"
        )
    for label, page in baseline["per_page"].items():
        mine = run["per_page"].get(label)
        if mine is None:
            faults.append(f"page {label} is missing")
            continue
        if mine["paragraphs"] != page["paragraphs"]:
            faults.append(
                f"page {label}: {page['paragraphs']} paragraphs became "
                f"{mine['paragraphs']}"
            )
        if set(mine["text"]) != set(page["text"]):
            faults.append(f"page {label}: the paragraph names moved")
    record("check_04a_the_document_is_conserved", not faults, "; ".join(faults[:6]))


def check_04b_every_call_is_attributed() -> None:
    """Positive 4b: what the run spent, and what it says it spent it on."""
    faults = []
    run = load_json(RUN_DIR / "run.json")
    if run["requests"] != run["cache_hits"] + run["api_calls"]:
        faults.append("the request ledger does not add up")
    repair = load_json(RUN_DIR / "sidecars" / "react_repair.report.json")
    if repair["api_calls"] != len(repair["api_attributions"]):
        faults.append(
            f"the repair loop made {repair['api_calls']} calls and attributes "
            f"{len(repair['api_attributions'])}"
        )
    record("check_04b_every_call_is_attributed", not faults, "; ".join(faults[:6]))


def check_04c_the_page_carries_no_new_harm() -> None:
    """Negative 4c: the detectors this batch could break report no more than before."""
    faults = []
    was = load_json(F3_SIDECARS / "issues.json")
    now = load_json(RUN_DIR / "sidecars" / "issues.json")
    for kind in NO_NEW_HARM:
        before = was["counts"]["by_kind"].get(kind, 0)
        after = now["counts"]["by_kind"].get(kind, 0)
        if after > before:
            faults.append(f"{kind}: {before} became {after}")
    if now["counts"]["issues"] > was["counts"]["issues"]:
        faults.append(
            f"total findings {was['counts']['issues']} became {now['counts']['issues']}"
        )
    record("check_04c_the_page_carries_no_new_harm", not faults, "; ".join(faults[:6]))


# --- 05 scope ------------------------------------------------------------------


def check_05a_the_delta_is_the_declared_surface() -> None:
    """Negative 5a: nothing outside the declared surface changed."""
    changed = changed_paths()
    stray = [
        path
        for path in changed
        if not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    ]
    faults = [f"outside the surface: {stray[:6]}"] if stray else []
    if not changed:
        faults.append("no path changed at all, so there is nothing to check")
    for tree in READ_ONLY_TREES:
        touched = [path for path in changed if path.startswith(tree)]
        if touched:
            faults.append(f"{tree} is read only and {touched[:3]} changed")
    record(
        "check_05a_the_delta_is_the_declared_surface", not faults, "; ".join(faults[:6])
    )


def check_05b_the_gate_names_no_run_local_identifier() -> None:
    """Negative 5b: no assertion is anchored to an identifier a rerun reassigns."""
    # Assembled rather than written out, so this assertion does not match itself.
    run_local = "debug" + "_id"
    source = Path(__file__).read_text(encoding="utf-8")
    faults = []
    if re.search(rf"\b{run_local}\b", source):
        faults.append(f"this gate names {run_local}")
    for name in ("identity_writeback.json", "hang_determination.json"):
        frozen = json.dumps(evidence(name), ensure_ascii=False)
        if f'"{run_local}"' in frozen:
            faults.append(f"{name} carries a {run_local}")
    record(
        "check_05b_the_gate_names_no_run_local_identifier",
        not faults,
        "; ".join(faults[:6]),
    )


def check_05c_the_upstream_edits_are_registered() -> None:
    """Positive 5c: both upstream changes stand in the registry under this batch."""
    registry = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    rows = [line for line in registry.splitlines() if "| B11.1 |" in line]
    faults = []
    for symbol in ("post_translate_paragraph", "_layout_typesetting_units"):
        if not any(symbol in row for row in rows):
            faults.append(f"{symbol} is not registered under this batch")
    record(
        "check_05c_the_upstream_edits_are_registered", not faults, "; ".join(faults[:6])
    )


# The checks that need a scratch directory to write a mutated configuration to.
STUB_CHECKS = (check_02e_the_ceiling_is_declared_and_bounded,)

CHECKS = (
    check_01a_the_folded_label_is_one_line,
    check_01b_the_writer_reports_what_it_skipped,
    check_01c_the_whole_reached_set_is_accounted_for,
    check_01d_the_comparison_reads_the_text,
    check_02a_the_determination_stands,
    check_02b_the_mark_no_longer_reaches_the_rule,
    check_02c_a_line_of_punctuation_alone_keeps_the_old_behaviour,
    check_02d_a_hang_inside_the_bound_is_not_pulled_back,
    check_02e_the_ceiling_is_declared_and_bounded,
    check_03a_no_name_carries_its_source_form,
    check_03b_the_policy_was_selected_and_nothing_was_rewritten,
    check_04a_the_document_is_conserved,
    check_04b_every_call_is_attributed,
    check_04c_the_page_carries_no_new_harm,
    check_05a_the_delta_is_the_declared_surface,
    check_05b_the_gate_names_no_run_local_identifier,
    check_05c_the_upstream_edits_are_registered,
)


def main() -> int:
    import tempfile

    print("spec_check_b11_1: identity write back, bounded hang, name policy\n")
    with tempfile.TemporaryDirectory(prefix="b11_1_") as raw:
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
