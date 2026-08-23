"""Gate script for batch B11.3 (the formula mislabel: its criterion and its repair).

Run from the repository root:

    python spec_checks/spec_check_b11_3.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request. Every assertion is answered from a stub this gate builds, or
from the small derived evidence this batch wrote beside its run -- never from a
stage checkpoint and never from a produced PDF, which is what CLAUDE.md section
4.16 asks of a gate written after b11.2.

What this batch is. b11.2 found that ten untranslated units on FD were refused
at one line, because a paragraph whose every composition is a formula reads as
placeholder only, and it named the cause without repairing it: StylesAndFormulas
had annotated ordinary text as formula. This batch wrote down what that means,
measured how much of it there is, and repaired one branch of it.

T1 wrote the criterion before the repair and before any measurement. It
enumerates the nine branches of the annotation disjunction with their source
locations and their configuration channels, and it defines a mislabel with
general signals only: a letter run long enough to be a word, no mathematical
symbols, and no independent formula evidence. Two exemptions, both independent
detectors. Corner mark is deliberately NOT an exemption, and the reason is
measured: that branch fires on genuine superscripts and on small-caps running
text alike.

T2 applied it to all six samples: 68 mislabels in 39 paragraphs, and what each
one costs downstream in four classes. Reverse sampling of thirty unflagged
compositions found seventeen the criterion misses, all of them one to three
characters, which is why the count is reported as a lower bound.

T3 repaired the font branch. The broad formula-font pattern called any face
whose name contains Mono a formula font; a name describing metrics says nothing
about content. The two arms are the same stage over the same input differing in
one pattern, and the before arm reproduces the frozen annotation exactly, which
is what makes the after arm's number mean anything.

T4 ran five samples against the b10.5 on arm.

01 is the premise check and the criterion's own shape.
02 is T1: the paths, the self-check, and that the criterion names nothing local.
03 is T2: the measurement, the exposure classes, the reverse sample.
04 is T3: the repair, its control, and the reference regression.
05 is the consumer inventory and the mid-cycle revision.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec_checks import evidence  # noqa: E402
from spec_checks import harness  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b11.3"
PREVIOUS_TAG = "b11.2"

BATCH_DIR = ROOT / "examples" / "output" / "b11_3"
BASELINE_BATCH = ROOT / "examples" / "output" / "b10_5"

PREMISE = BATCH_DIR / "premise_check.json"
PATHS_TABLE = BATCH_DIR / "annotation_paths.json"
CRITERION_CONFIG = BATCH_DIR / "criterion_config.json"
T1 = BATCH_DIR / "t1_formula_criterion.json"
T2 = BATCH_DIR / "t2_measurement_before.json"
REVERSE = BATCH_DIR / "t2_reverse_sample_review.json"
INVENTORY = BATCH_DIR / "t3_consumer_inventory.json"
REFERENCE = BATCH_DIR / "t3_reference_set.json"
T3 = BATCH_DIR / "t3_repair.json"
REVISION = BATCH_DIR / "midcycle_revision.json"
RUNS = BATCH_DIR / "runs.json"
T4 = BATCH_DIR / "t4_conservation.json"

CRITERION_SOURCE = BATCH_DIR / "scripts" / "formula_criterion.py"

# What this gate reads and the retention policy must therefore not remove.
# CLAUDE.md section 4.16: all of it is derived evidence this batch extracted at
# run time, and none of it is a checkpoint or a PDF.
GATE_EVIDENCE = (
    "examples/output/b11_3/premise_check.json",
    "examples/output/b11_3/annotation_paths.json",
    "examples/output/b11_3/criterion_config.json",
    "examples/output/b11_3/t1_formula_criterion.json",
    "examples/output/b11_3/t2_measurement_before.json",
    "examples/output/b11_3/t2_reverse_sample_review.json",
    "examples/output/b11_3/t3_consumer_inventory.json",
    "examples/output/b11_3/t3_reference_set.json",
    "examples/output/b11_3/t3_repair.json",
    "examples/output/b11_3/midcycle_revision.json",
    "examples/output/b11_3/runs.json",
    "examples/output/b11_3/t4_conservation.json",
    "examples/output/b11_3/scripts/formula_criterion.py",
)

CORPUS = ("AramcoWorld-en-v2", "CERNCourier-en", "Courier-en",
          "Courier-zh", "FD-en-v2", "Vogue-en")

# The five the plan declares for the regression run. Courier-zh is measured
# offline and not run, on the ground b11.2 recorded.
REGRESSION_SAMPLES = ("AramcoWorld-en-v2", "CERNCourier-en", "Courier-en",
                      "FD-en-v2", "Vogue-en")

FORMULAR_HELPER = (ROOT / "babeldoc" / "format" / "pdf" / "document_il" / "utils"
                   / "formular_helper.py")
STYLES_AND_FORMULAS = (ROOT / "babeldoc" / "format" / "pdf" / "document_il"
                       / "midend" / "styles_and_formulas.py")
RETENTION = ROOT / "configs" / "output_retention.json"

# The four exposure classes T2 is required to fill.
EXPOSURE_CLASSES = ("i_paragraph_refused_as_placeholder_only",
                    "ii_sent_with_placeholders_in_the_request",
                    "iii_not_sent_for_another_reason",
                    "iv_no_observable_consequence")

# The nine branches of the annotation disjunction.
BRANCHES = ("layout_formula", "character_class_start", "character_class_middle",
            "formula_font", "vertical", "dummy_space", "visual_bbox_disjoint",
            "corner_mark", "space_inherits")

# The alternative the repair removed, and the ones it must have left alone.
REMOVED_ALTERNATIVE = ".*Mono"
KEPT_ALTERNATIVES = ("CM[^RB]", "LINE", "LCIRCLE", "TeX-", "rsfs", "txsy",
                     "wasy", "stmary", ".*Code", ".*Sym", ".*Math",
                     "AdvP4C4E74", "AdvPSSym", "AdvP4C4E59")

# The delta this batch is allowed. output_retention.json is here by the
# mid-cycle revision the user adjudicated; W-B11-10 records it.
ALLOWED_PREFIXES = (
    "babeldoc/format/pdf/document_il/utils/formular_helper.py",
    "configs/output_retention.json",
    "spec_checks/spec_check_b11_3.py",
    "spec_checks/spec_check_e0.py",
    "spec_checks/run_all.py",
    "docs/reports/assertion_contracts.md",
    "docs/eval/gap_register.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "plans/PLAN_B11_3.md",
    "examples/output/b11_3/",
)

# Trees this batch reads and never writes.
READ_ONLY_TREES = ("prompts/", "corpus/", "reviews/",
                   "babeldoc/format/pdf/document_il/midend/styles_and_formulas.py",
                   "babeldoc/format/pdf/document_il/utils/paragraph_helper.py",
                   "babeldoc/format/pdf/document_il/midend/il_translator.py",
                   "babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py")

# Chinese tokens this gate matches are written as escapes so the file stays
# pure ASCII: b0's 09, b1's 09d and b2's 11c all scan spec_checks/*.py for
# CJK. Each escape is the character it replaced, glossed in English beside it.
_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b11_3")


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


def load(path: Path):
    return evidence.read_json(path)


def _is_ordinary_word(text: str) -> bool:
    """Whether a five-character string is a word rather than a minted identifier.

    The paragraph finder's alphabet mixes cases and digits, so a run of five
    letters that is all one case is prose. Same reading as
    spec_check_b11_2.check_07d, so the two gates cannot disagree about what the
    shape is.
    """
    return text.isalpha() and (text.islower() or text.isupper())


def changed_paths() -> list[str]:
    """This batch's delta, anchored to its own tag where the tag exists."""
    tag = subprocess.run(  # noqa: S603
        ["git", "tag", "--list", BATCH_TAG],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip()
    if tag:
        argv = ["git", "diff", "--name-only", f"{BATCH_TAG}^..{BATCH_TAG}"]
    else:
        argv = ["git", "status", "--porcelain"]
    proc = subprocess.run(  # noqa: S603
        argv, cwd=ROOT, capture_output=True, text=True, check=False,  # noqa: S607
    )
    paths = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        paths.append(line if tag else line.split(maxsplit=1)[-1].strip('"'))
    return sorted(set(paths))


# --- 01 the premise check and the criterion's shape ---------------------------


def check_01a_the_premises_were_all_checked() -> None:
    """Positive 1a: eight premises, each with a reading and a verdict."""
    data = load(PREMISE)
    faults = []
    rows = data.get("rows") or []
    if len(rows) != 8:
        faults.append(f"expected eight premises, found {len(rows)}")
    for row in rows:
        if not row.get("verdict"):
            faults.append(f"premise {row.get('n')} carries no verdict")
        if not (row.get("reading") or row.get("first_reading")):
            faults.append(f"premise {row.get('n')} carries no reading")
    record("check_01a_the_premises_were_all_checked", not faults,
           "; ".join(faults[:4]))


def check_01b_the_two_repaired_premises_name_their_repair() -> None:
    """Positive 1b: the premises that did not hold as written say what was done.

    Premise 1 failed on a missing tag and premise 5 on a moved line. Neither was
    waved through: one names the tag it created and the reading it then got, the
    other names both line numbers and the edit that moved it.
    """
    data = load(PREMISE)
    rows = {row["n"]: row for row in data.get("rows") or []}
    faults = []
    first = rows.get(1, {})
    if "repair" not in first or "second_reading" not in first:
        faults.append("premise 1 does not record a repair and a second reading")
    if "32/32" not in str(first.get("second_reading", "")):
        faults.append("premise 1's second reading is not the full gate")
    fifth = rows.get(5, {})
    repin = fifth.get("repin") or {}
    if not repin.get("was") or not repin.get("now"):
        faults.append("premise 5 does not record both line numbers")
    if repin.get("was") == repin.get("now"):
        faults.append("premise 5's repin does not move")
    record("check_01b_the_two_repaired_premises_name_their_repair", not faults,
           "; ".join(faults[:4]))


def check_01c_every_threshold_is_bounded_and_reasoned() -> None:
    """Positive 1c: no bare literal. CLAUDE.md section 4.4.

    Every condition carries a value, an inclusive range that contains it, and a
    reason. A threshold whose reason names a sample would be a threshold fitted
    to a sample, so the reason is scanned for the corpus names too.
    """
    config = load(CRITERION_CONFIG)
    faults = []
    conditions = config.get("conditions") or {}
    if not conditions:
        faults.append("the criterion declares no conditions")
    for name, cond in conditions.items():
        if "value" not in cond:
            faults.append(f"{name} has no value")
            continue
        bounds = cond.get("range")
        if not bounds or len(bounds) != 2:
            faults.append(f"{name} has no two-ended range")
        elif not bounds[0] <= cond["value"] <= bounds[1]:
            faults.append(f"{name} value {cond['value']} outside {bounds}")
        if not cond.get("why"):
            faults.append(f"{name} carries no reason")
        for sample in CORPUS:
            if sample.lower() in str(cond.get("why", "")).lower():
                faults.append(f"{name}'s reason names the sample {sample}")
    record("check_01c_every_threshold_is_bounded_and_reasoned", not faults,
           "; ".join(faults[:4]))


def check_01d_the_corner_mark_is_not_an_exemption() -> None:
    """Negative 1d: the criterion refuses the exemption that would have hidden a class.

    Not a matter of taste. The corner-mark branch fires on genuine superscripts
    and on small-caps running text alike, so exempting it would have excused
    every mislabel that arrives that way. The criterion must declare it a
    non-exemption, and the measurement must show that branch actually producing
    mislabels -- otherwise the declaration costs nothing.
    """
    config = load(CRITERION_CONFIG)
    measurement = load(T2)
    faults = []
    if "corner_mark" not in (config.get("not_an_exemption") or {}):
        faults.append("corner_mark is not declared a non-exemption")
    if "corner_mark" in (config.get("exemptions") or {}):
        faults.append("corner_mark is declared an exemption")
    found = (measurement.get("by_annotation_path") or {}).get("corner_mark", 0)
    if found <= 0:
        faults.append("no mislabel is attributed to the corner-mark branch, so "
                      "the non-exemption is untested")
    record("check_01d_the_corner_mark_is_not_an_exemption", not faults,
           "; ".join(faults[:4]))


# --- 02 T1: the paths, the self-check, the vocabulary -------------------------


def check_02a_every_branch_is_enumerated_with_its_channel() -> None:
    """Positive 2a: nine branches, each with a source location and a channel verdict."""
    table = load(PATHS_TABLE)
    faults = []
    seen = {b["id"]: b for b in table.get("branches") or []}
    for name in BRANCHES:
        if name not in seen:
            faults.append(f"branch {name} is not enumerated")
            continue
        branch = seen[name]
        if not (branch.get("line") or branch.get("lines")):
            faults.append(f"branch {name} carries no source location")
        if "config_channel" not in branch:
            faults.append(f"branch {name} does not say whether it has a channel")
        if not branch.get("config_note"):
            faults.append(f"branch {name} carries no note on its channel")
    if len(seen) != len(BRANCHES):
        faults.append(f"expected {len(BRANCHES)} branches, found {len(seen)}")
    record("check_02a_every_branch_is_enumerated_with_its_channel", not faults,
           "; ".join(faults[:4]))


def check_02b_the_configurable_surface_verdict_is_recorded() -> None:
    """Positive 2b: the plan's conditional candidate got an answer, with a count.

    The plan said that if the mislabel came from a configuration-driven path a
    configuration repair should be preferred, and that if there were no channel
    the fact had to be recorded. The answer is neither: a channel exists at one
    branch of nine. That count is asserted against the enumeration rather than
    taken from the prose, so the two cannot drift apart.
    """
    table = load(PATHS_TABLE)
    faults = []
    summary = table.get("config_channel_summary") or {}
    branches = table.get("branches") or []
    narrowing = [b for b in branches
                 if b.get("config_channel")
                 and "widening only" not in (b.get("config_note") or "")]
    with_channel = [b for b in branches if b.get("config_channel")]
    if summary.get("with_a_narrowing_config_channel") != len(narrowing):
        faults.append(
            f"summary says {summary.get('with_a_narrowing_config_channel')} "
            f"narrowing channels, the enumeration has {len(narrowing)}")
    if summary.get("with_any_config_channel") != len(with_channel):
        faults.append(
            f"summary says {summary.get('with_any_config_channel')} channels, "
            f"the enumeration has {len(with_channel)}")
    if summary.get("branches_total") != len(branches):
        faults.append("summary's branch total disagrees with the enumeration")
    if not summary.get("statement"):
        faults.append("no verdict is recorded on the configurable surface")
    record("check_02b_the_configurable_surface_verdict_is_recorded", not faults,
           "; ".join(faults[:4]))


def check_02c_the_self_check_passed_on_both_sides() -> None:
    """Positive 2c: genuine formulas survive the criterion and known mislabels do not.

    Both sides, because a criterion that flags nothing passes the first on its
    own. The negative side is required to be drawn from more than one sample, so
    the criterion cannot be demonstrated on the publication it was found in.
    """
    data = load(T1)
    faults = []
    check = data.get("self_check") or {}
    if not check.get("passed"):
        faults.append("the self-check did not pass")
    for fault in (check.get("genuine_faults") or []):
        faults.append(f"genuine: {fault}")
    for fault in (check.get("mislabel_faults") or []):
        faults.append(f"mislabel: {fault}")
    genuine = check.get("genuine_formulas") or []
    if not genuine:
        faults.append("no genuine formula was evaluated")
    for row in genuine:
        if row.get("is_mislabel"):
            faults.append(f"a genuine formula was flagged: {row.get('text')!r}")
    examples = check.get("mislabel_examples") or []
    if len({row.get("sample") for row in examples}) < 3:
        faults.append("the mislabel examples come from fewer than three samples")
    for row in examples:
        if not row.get("is_mislabel"):
            faults.append(f"a known mislabel was missed: {row.get('text')!r}")
    record("check_02c_the_self_check_passed_on_both_sides", not faults,
           "; ".join(faults[:4]))


def check_02d_the_criterion_names_nothing_local() -> None:
    """Negative 2d: the criterion is written in general signals only.

    Scans the criterion module and its configuration for a publication name, for
    anything shaped like a paragraph identifier the finder mints, and for a page
    anchor. What is forbidden is a value, so string literals are read rather
    than field names.
    """
    faults = []
    minted = re.compile(r"^[A-Za-z0-9]{5}(#L\d+)?$")
    anchor = re.compile(r"^p\d+#\d+$")
    source = CRITERION_SOURCE.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value
        if minted.match(text) and not _is_ordinary_word(text):
            faults.append(f"the criterion names a minted identifier: {text!r}")
        if anchor.match(text):
            faults.append(f"the criterion names a page anchor: {text!r}")
        for sample in CORPUS:
            if sample.lower() in text.lower():
                faults.append(f"the criterion names the sample {sample}")
    blob = json.dumps(load(CRITERION_CONFIG), ensure_ascii=False)
    for sample in CORPUS:
        if sample.lower() in blob.lower():
            faults.append(f"the criterion configuration names the sample {sample}")
    record("check_02d_the_criterion_names_nothing_local", not faults,
           "; ".join(faults[:4]))


# --- 03 T2: the measurement ---------------------------------------------------


def check_03a_the_measurement_covers_the_whole_corpus() -> None:
    """Positive 3a: six samples measured, and the totals add up to the rows."""
    data = load(T2)
    faults = []
    by_sample = data.get("by_sample") or {}
    missing = [s for s in CORPUS if s not in by_sample]
    if missing:
        faults.append(f"samples not measured: {missing}")
    rows = data.get("rows") or []
    if len(rows) != (data.get("totals") or {}).get("mislabels"):
        faults.append("the mislabel total disagrees with the row count")
    if sum(by_sample.values()) != len(rows):
        faults.append("the per-sample counts do not add up to the rows")
    for row in rows:
        if not row.get("exposure_class"):
            faults.append("a mislabel carries no exposure class")
            break
        if not row.get("conditions_met"):
            faults.append("a mislabel does not record which conditions it met")
            break
    record("check_03a_the_measurement_covers_the_whole_corpus", not faults,
           "; ".join(faults[:4]))


def check_03b_all_four_exposure_classes_are_filled() -> None:
    """Positive 3b: the four classes are all accounted for, and the third names its sites.

    The third class is the one the plan asked for by name: it does not presume a
    cause, it is filled by measurement, and each row records the source location
    of the refusal it actually met. Its purpose is that a paragraph still not
    sent after the repair can be told apart from one the repair failed on.
    """
    data = load(T2)
    faults = []
    counts = (data.get("exposure") or {}).get("counts") or {}
    for name in EXPOSURE_CLASSES:
        if name not in counts:
            faults.append(f"exposure class {name} is not counted")
    if sum(counts.values()) != (data.get("totals") or {}).get("mislabels"):
        faults.append("the exposure counts do not add up to the mislabels")
    third = [r for r in data.get("rows") or []
             if r.get("exposure_class") == "iii_not_sent_for_another_reason"]
    for row in third:
        site = row.get("exposure_site") or ""
        if ".py:" not in site:
            faults.append(f"a third-class row names no source location: {site!r}")
            break
    if third and not any(".py:" in (r.get("exposure_site") or "") for r in third):
        faults.append("no third-class row carries a source location")
    record("check_03b_all_four_exposure_classes_are_filled", not faults,
           "; ".join(faults[:4]))


def check_03c_the_reverse_sample_is_reviewed_and_its_limit_declared() -> None:
    """Positive 3c: the draw is reproducible, reviewed by hand, and its finding kept.

    The reverse sample is what stops a criterion that simply misses things from
    passing as one that found everything. It found seventeen misses, so the
    count has to be reported as a lower bound rather than as a total, and the
    review must not contain a genuine formula that was wrongly flagged.
    """
    measurement = load(T2)
    review = load(REVERSE)
    faults = []
    draw = measurement.get("reverse_sample") or {}
    if draw.get("seed") is None:
        faults.append("the draw records no seed")
    if not draw.get("n"):
        faults.append("the draw is empty")
    if draw.get("n") != len(review.get("rows") or []):
        faults.append("the review does not cover the draw")
    counts = review.get("counts") or {}
    if counts.get("wrongly_flagged_genuine_formula") != 0:
        faults.append("the review reports a genuine formula wrongly flagged")
    reviewed = {}
    for row in review.get("rows") or []:
        if not row.get("verdict"):
            faults.append("a reviewed row carries no verdict")
            break
        reviewed[row["verdict"]] = reviewed.get(row["verdict"], 0) + 1
    if reviewed.get("missed_text_fragment", 0) != counts.get("missed_text_fragment"):
        faults.append("the review's miss count disagrees with its rows")
    if counts.get("missed_text_fragment", 0) > 0:
        blob = json.dumps(review, ensure_ascii=False).lower()
        if "lower bound" not in blob:
            faults.append("misses were found but the count is not called a lower bound")
    record("check_03c_the_reverse_sample_is_reviewed_and_its_limit_declared",
           not faults, "; ".join(faults[:4]))


# --- 04 T3: the repair --------------------------------------------------------


def check_04a_the_repair_is_the_one_alternative() -> None:
    """Positive 4a: exactly one alternative left the broad pattern, and the rest stand.

    Read out of the source rather than out of the report. The precise
    mathematics pattern and the text-face allow-list must be untouched, because
    the repair's whole claim is that it narrowed one heuristic and changed no
    other tier of the decision.
    """
    source = FORMULAR_HELPER.read_text(encoding="utf-8")
    faults = []
    broad = source[source.index("broad_formula_font_pattern = ("):]
    broad = broad[:broad.index("\n        )")]
    if REMOVED_ALTERNATIVE in broad:
        faults.append(f"{REMOVED_ALTERNATIVE} is still in the broad pattern")
    for kept in KEPT_ALTERNATIVES:
        if kept not in broad:
            faults.append(f"the broad pattern lost {kept}")
    for tier in ("precise_formula_font_pattern", "pattern_text"):
        if tier not in source:
            faults.append(f"{tier} is gone")
    if "MiriamMonoCLM" not in source:
        faults.append("the precise pattern no longer names its monospace faces, "
                      "so the claim that they are still answered for is false")
    record("check_04a_the_repair_is_the_one_alternative", not faults,
           "; ".join(faults[:4]))


def check_04b_the_harness_reproduces_the_frozen_annotation() -> None:
    """Positive 4b: the before arm matches the checkpoints on disk, sample for sample.

    Without this the after arm says nothing: a harness that does not reproduce
    the original cannot be trusted to have changed only what it claims.
    """
    data = load(T3)
    faults = []
    control = data.get("harness_control") or {}
    if not control.get("passed"):
        faults.append(f"the before arm does not reproduce the frozen annotation: "
                      f"{control.get('mismatches')}")
    before = data.get("before") or {}
    if set(before.get("by_sample") or {}) != set(CORPUS):
        faults.append("the before arm does not cover the corpus")
    record("check_04b_the_harness_reproduces_the_frozen_annotation", not faults,
           "; ".join(faults[:4]))


def check_04c_the_mislabels_fell_and_none_were_introduced() -> None:
    """Positive 4c: the count went down, the font branch is empty, nothing new appeared.

    No target was set for how far it should fall, per the plan; what is asserted
    is the direction, that the branch the repair aimed at is now empty, and that
    the branches it did not aim at are untouched.
    """
    data = load(T3)
    faults = []
    delta = data.get("delta") or {}
    before = delta.get("mislabels_before")
    after = delta.get("mislabels_after")
    if not isinstance(before, int) or not isinstance(after, int):
        faults.append("the delta does not carry both counts")
    elif after >= before:
        faults.append(f"the mislabel count did not fall: {before} -> {after}")
    if delta.get("introduced"):
        faults.append(f"the repair introduced {delta['introduced']} new mislabels")
    paths_after = (data.get("after") or {}).get("by_annotation_path") or {}
    paths_before = (data.get("before") or {}).get("by_annotation_path") or {}
    if paths_after.get("formula_font"):
        faults.append("the font branch still produces mislabels")
    if not paths_before.get("formula_font"):
        faults.append("the font branch produced none before, so the repair is untested")
    if paths_after.get("vertical") != paths_before.get("vertical"):
        faults.append("the vertical branch moved, and this repair does not touch it")
    record("check_04c_the_mislabels_fell_and_none_were_introduced", not faults,
           "; ".join(faults[:4]))


def check_04d_the_reference_formulas_survived() -> None:
    """Positive 4d: every pinned genuine formula is still annotated as one.

    The adjudication made this a gate assertion rather than a look. The pinned
    set is hashed and the hash is carried into the repair's evidence, so a set
    trimmed to whatever the repair happened to leave standing would not match.
    """
    reference = load(REFERENCE)
    data = load(T3)
    faults = []
    regression = data.get("reference_regression") or {}
    if not regression.get("passed"):
        faults.append("the reference regression did not pass")
    for lost in (regression.get("lost") or []):
        faults.append(f"a genuine formula is no longer annotated: {lost.get('text')!r}")
    for wrong in (regression.get("wrongly_flagged_as_mislabel") or []):
        faults.append(f"a genuine formula is now flagged: {wrong.get('text')!r}")
    items = reference.get("items") or []
    if not items:
        faults.append("the reference set is empty")
    if regression.get("pinned") != len(items):
        faults.append("the repair checked a different number of items than are pinned")
    if regression.get("still_annotated_as_formula") != len(items):
        faults.append("not every pinned formula survived")
    digest = hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if digest != reference.get("items_sha256"):
        faults.append("the reference set does not match its own hash")
    if digest != data.get("reference_items_sha256"):
        faults.append("the repair was checked against a different reference set")
    if len({i.get("sample") for i in items}) < 2:
        faults.append("the reference set comes from a single sample")
    record("check_04d_the_reference_formulas_survived", not faults,
           "; ".join(faults[:4]))


def check_04e_one_criterion_answered_before_and_after() -> None:
    """Negative 4e: the question did not change between the two measurements.

    A fall in the count means a change in the pipeline only if the criterion was
    the same on both sides. The hash of the criterion module is carried by the
    measurement, by the repair and by the self-check, and all three must equal
    the file on disk.
    """
    faults = []
    digest = hashlib.sha256(CRITERION_SOURCE.read_bytes()).hexdigest()
    for name, path in (("t2", T2), ("t3", T3), ("t1", T1)):
        carried = load(path).get("criterion_sha256")
        if carried != digest:
            faults.append(f"{name} was produced with a different criterion: "
                          f"{carried} vs {digest}")
    config_digest = hashlib.sha256(CRITERION_CONFIG.read_bytes()).hexdigest()
    for name, path in (("t1", T1), ("t2", T2)):
        carried = load(path).get("config_sha256")
        if carried and carried != config_digest:
            faults.append(f"{name} was produced with a different configuration")
    record("check_04e_one_criterion_answered_before_and_after", not faults,
           "; ".join(faults[:4]))


def check_04f_the_repair_special_cases_nothing() -> None:
    """Negative 4f: no publication, page or sample string entered the repaired file.

    The repair is allowed to be expressed in the criterion's vocabulary and in
    nothing else. Scans the string literals of the file that changed.
    """
    faults = []
    source = FORMULAR_HELPER.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for sample in CORPUS:
            if sample.lower() in node.value.lower():
                faults.append(f"the repaired file names the sample {sample}")
    for sample in CORPUS:
        if sample.lower() in source.lower():
            faults.append(f"the repaired file mentions {sample} somewhere")
    record("check_04f_the_repair_special_cases_nothing", not faults,
           "; ".join(faults[:4]))


def check_04g_the_annotator_itself_was_not_touched() -> None:
    """Negative 4g: the landing site is the decider, not the stage.

    The plan named StylesAndFormulas; the code put the decision in
    formular_helper. The correction is registered, and what makes it a
    correction rather than a second change is that the stage is untouched.
    """
    faults = []
    changed = changed_paths()
    stage = "babeldoc/format/pdf/document_il/midend/styles_and_formulas.py"
    if stage in changed:
        faults.append("styles_and_formulas.py moved, but the repair claims it did not")
    helper = "babeldoc/format/pdf/document_il/utils/formular_helper.py"
    if changed and helper not in changed:
        faults.append("the repaired file is not in the delta")
    register = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    if "formular_helper.py" not in register:
        faults.append("the repaired file is not on the upstream register")
    for needed in ("\u4e0a\u6e38\u539f\u884c\u4e3a", "\u672c\u9879\u76ee\u6539\u540e\u884c\u4e3a"):  # upstream behaviour, behaviour after this project
        if needed not in register:
            faults.append(f"the register does not record {needed}")
    waivers = (ROOT / "WAIVERS.md").read_text(encoding="utf-8")
    if "W-B11-11" not in waivers:
        faults.append("the landing-site correction is not registered")
    record("check_04g_the_annotator_itself_was_not_touched", not faults,
           "; ".join(faults[:4]))


# --- 05 the inventory and the revision ----------------------------------------


def check_05a_every_consumer_was_enumerated_before_the_change() -> None:
    """Positive 5a: the consumers of the annotation are listed with their effects.

    The adjudication made this a precondition of touching the annotation. A list
    that only names locations would not have served its purpose, so each entry
    must also say what changes for that reader.
    """
    data = load(INVENTORY)
    faults = []
    sites = [s for g in data.get("consumers") or [] for s in g.get("sites") or []]
    if len(sites) < 15:
        faults.append(f"only {len(sites)} consumers enumerated, which is too few "
                      "to be the whole of them")
    for site in sites:
        if not site.get("file") or not site.get("line"):
            faults.append("a consumer carries no source location")
            break
        if not site.get("effect_of_one_fewer_formula"):
            faults.append(f"{site.get('file')} does not say what changes for it")
            break
    if not data.get("the_one_that_can_lose_something"):
        faults.append("the inventory does not name the consumer that can lose data")
    files = {s.get("file") for s in sites}
    for needed in ("babeldoc/format/pdf/document_il/backend/pdf_creater.py",
                   "babeldoc/format/pdf/document_il/utils/paragraph_helper.py",
                   "babeldoc/format/pdf/document_il/midend/typesetting.py",
                   "babeldoc/magazine/line_split.py",
                   "babeldoc/magazine/column_reflow.py"):
        if needed not in files:
            faults.append(f"the inventory misses {needed}")
    record("check_05a_every_consumer_was_enumerated_before_the_change", not faults,
           "; ".join(faults[:4]))


def check_05b_the_revision_narrows_and_is_recorded() -> None:
    """Positive 5b: the surface widened by adjudication, and only in the safe direction.

    Three conditions: the path was not yet taken, there is an explicit record,
    and the change can only tighten. The third is checked against the file
    rather than taken on the record's word -- the registered paths must be
    present and the three numeric parameters must be untouched.
    """
    revision = load(REVISION)
    retention = load(RETENTION)
    faults = []
    conditions = revision.get("conditions") or {}
    for name in ("only_a_path_not_yet_taken", "explicit_adjudication_record",
                 "narrows_only_never_widens"):
        if not (conditions.get(name) or {}).get("holds"):
            faults.append(f"revision condition {name} is not recorded as holding")
        if not (conditions.get(name) or {}).get("how"):
            faults.append(f"revision condition {name} carries no reasoning")
    protected = retention.get("protected_paths") or []
    registered = [p for p in protected if "checkpoint.06_styles_and_formulas" in p]
    if len(registered) != (revision.get("registered_paths") or {}).get("count"):
        faults.append("the revision's count disagrees with the policy file")
    for path in registered:
        if not (ROOT / path).exists():
            faults.append(f"a registered path is not on disk: {path}")
            break
    if retention.get("archive_max_file_kb") != 2048:
        faults.append("the archive ceiling moved, which the revision forbids")
    waivers = (ROOT / "WAIVERS.md").read_text(encoding="utf-8")
    if "W-B11-10" not in waivers:
        faults.append("the surface extension is not registered in WAIVERS.md")
    record("check_05b_the_revision_narrows_and_is_recorded", not faults,
           "; ".join(faults[:4]))


def check_05c_conservation_holds_against_the_baseline() -> None:
    """Positive 5c: pages, paragraph counts and page-local anchors all conserved.

    The repair turns compositions that were formulas into text, and the
    inventory says that changes what line splitting may cut and what column
    reflow may move. So the quantities those passes could disturb are the ones
    asserted here.
    """
    data = load(T4)
    faults = []
    samples = data.get("samples") or {}
    if set(samples) != set(REGRESSION_SAMPLES):
        faults.append(f"conservation covers {sorted(samples)}, "
                      f"not {sorted(REGRESSION_SAMPLES)}")
    for name, row in samples.items():
        conservation = row.get("conservation") or {}
        if not conservation.get("present"):
            faults.append(f"{name} has no conservation record")
            continue
        if not conservation.get("page_count_conserved"):
            faults.append(f"{name}: page count moved")
        if not conservation.get("paragraph_counts_conserved"):
            faults.append(f"{name}: paragraph counts moved "
                          f"{conservation.get('paragraph_count_differences')}")
        if not conservation.get("anchor_sets_conserved"):
            faults.append(f"{name}: page-local anchors moved on pages "
                          f"{conservation.get('pages_whose_anchor_set_moved')}")
    if not (data.get("totals") or {}).get("conservation_holds_everywhere"):
        faults.append("the summary does not report conservation holding")
    record("check_05c_conservation_holds_against_the_baseline", not faults,
           "; ".join(faults[:4]))


def check_05d_no_detector_count_rose() -> None:
    """Negative 5d: nothing got worse, measured against the tree before the repair.

    Against b11.2 rather than b10.5, and that choice is the assertion's whole
    point: b10.5 predates b11.1's name policy, so a comparison with it charges
    this batch for changes it did not make. AC-13 requires a per-paragraph box
    and text attribution for any rise; the way to satisfy it is to have none.
    """
    data = load(T4)
    faults = []
    rose = (data.get("totals") or {}).get("kinds_that_rose_anywhere")
    if rose:
        faults.append(f"detector counts rose without attribution: {rose}")
    for name, row in (data.get("samples") or {}).items():
        counts = row.get("detector_counts") or {}
        if "previous_b11_2" not in counts:
            faults.append(f"{name} was not compared against the previous tree")
    record("check_05d_no_detector_count_rose", not faults, "; ".join(faults[:4]))


def check_05e_every_baseline_residue_has_a_disposition() -> None:
    """Positive 5e: the residues are accounted for one by one, not as a total.

    b11.2 showed a falling total can be a false positive going away rather than
    a defect being repaired, so a total is not evidence. Every baseline residue
    carries a verdict, and the two comparisons are both kept.
    """
    data = load(T4)
    faults = []
    # The declaration says what the matching key was; the rows are then checked
    # for actually carrying no per-run identifier, since a declaration on its own
    # is only a claim.
    if "excerpt" not in (data.get("matched_by") or ""):
        faults.append("the comparison does not declare a text matching key")
    for name, row in (data.get("samples") or {}).items():
        for key in ("residue_disposition_vs_b10_5", "residue_disposition_vs_b11_2"):
            disposition = row.get(key)
            if not disposition:
                faults.append(f"{name} carries no {key}")
                continue
            rows = disposition.get("rows") or []
            if len(rows) != disposition.get("baseline_total"):
                faults.append(f"{name} {key}: not every residue has a row")
            for entry in rows:
                if not entry.get("verdict"):
                    faults.append(f"{name} {key}: a residue carries no verdict")
                    break
                if "debug_id" in entry:
                    faults.append(f"{name} {key}: a row is keyed on a minted id")
                    break
            if (disposition.get("gone", 0) + disposition.get("still", 0)
                    != disposition.get("baseline_total")):
                faults.append(f"{name} {key}: the verdicts do not add up")
    record("check_05e_every_baseline_residue_has_a_disposition", not faults,
           "; ".join(faults[:4]))


def check_05f_the_caption_is_no_longer_placeholders() -> None:
    """Positive 5f: the paragraph the plan names by hand carries its own words now.

    This is the exposure class the repair had to reach through, not merely
    around: the paragraph was always sent, so the refusal was never the problem.
    Its request carried placeholders where its words should have been, and the
    spaces between them did not come back.
    """
    data = load(T4)
    faults = []
    caption = data.get("caption") or {}
    if not caption.get("present"):
        faults.append("the caption paragraph is not in the tracking record")
    else:
        if caption.get("request_is_placeholders"):
            faults.append("the request is still placeholders")
        if not caption.get("request_carries_the_words"):
            faults.append("the request does not carry the source words")
    record("check_05f_the_caption_is_no_longer_placeholders", not faults,
           "; ".join(faults[:4]))


# --- 06 conservation, cost and scope ------------------------------------------


def check_06a_the_run_set_is_the_declared_one() -> None:
    """Positive 6a: five samples, one arm, and every call attributed."""
    data = load(RUNS)
    faults = []
    runs = data.get("runs") or []
    ran = sorted(r.get("sample", "").removesuffix(".pdf") for r in runs)
    if ran != sorted(REGRESSION_SAMPLES):
        faults.append(f"ran {ran}, declared {sorted(REGRESSION_SAMPLES)}")
    for run in runs:
        if run.get("arm") != "on":
            faults.append(f"{run.get('sample')} is not the on arm")
        if run.get("requests") is None or run.get("cache_hits") is None:
            faults.append(f"{run.get('sample')} does not record its calls")
            continue
        if run["requests"] - run["cache_hits"] != run.get("api_calls"):
            faults.append(f"{run.get('sample')}'s calls do not reconcile")
    record("check_06a_the_run_set_is_the_declared_one", not faults,
           "; ".join(faults[:4]))


def check_06b_no_off_arm_was_produced() -> None:
    """Negative 6b: single arm by default. CLAUDE.md section 4.14."""
    faults = []
    if BATCH_DIR.exists():
        for path in BATCH_DIR.rglob("off"):
            if path.is_dir():
                faults.append(f"an off arm exists: {path.relative_to(ROOT)}")
    record("check_06b_no_off_arm_was_produced", not faults, "; ".join(faults[:4]))


def check_06c_the_delta_is_the_declared_surface() -> None:
    """Negative 6c: this batch changed nothing outside what it declared."""
    faults = []
    changed = changed_paths()
    for path in changed:
        if not any(path == prefix or path.startswith(prefix)
                   for prefix in ALLOWED_PREFIXES):
            faults.append(f"outside the declared surface: {path}")
    for path in changed:
        for tree in READ_ONLY_TREES:
            if path == tree or path.startswith(tree):
                faults.append(f"a read only path moved: {path}")
    record("check_06c_the_delta_is_the_declared_surface", not faults,
           "; ".join(faults[:4]))


def check_06d_the_gate_names_no_run_local_identifier() -> None:
    """Negative 6d: no assertion here is anchored to a minted identifier.

    CLAUDE.md section 5.13. The evidence this batch wrote does carry those
    identifiers -- inside one run that is what they are for -- but the gate must
    not, since a gate outlives the run that minted them. What is forbidden is a
    value, not a field name, so this reads every string literal in the file.
    """
    shape = re.compile(r"^[A-Za-z0-9]{5}(#L\d+)?$")
    source = Path(__file__).read_text(encoding="utf-8")
    faults = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if shape.match(node.value) and not _is_ordinary_word(node.value):
                faults.append(f"line {node.lineno}: {node.value!r}")
    record("check_06d_the_gate_names_no_run_local_identifier", not faults,
           "; ".join(faults[:4]))


def check_06e_the_evidence_this_gate_reads_is_declared() -> None:
    """Positive 6e: GATE_EVIDENCE names what is read, and none of it is a checkpoint.

    CLAUDE.md section 4.16. The point of the declaration is that the retention
    policy can route around it; the point of the second half is that a gate
    written after b11.2 must read derived evidence rather than the stage
    products that cannot be archived.
    """
    faults = []
    for name in GATE_EVIDENCE:
        path = ROOT / name
        if not path.exists():
            faults.append(f"declared evidence is missing: {name}")
        if "checkpoint." in name:
            faults.append(f"a checkpoint is read directly: {name}")
        if name.endswith(".pdf"):
            faults.append(f"a produced document is read directly: {name}")
        if path.exists() and path.stat().st_size > 2048 * 1024:
            faults.append(f"declared evidence is over the archive ceiling: {name}")
    record("check_06e_the_evidence_this_gate_reads_is_declared", not faults,
           "; ".join(faults[:4]))


CHECKS = (
    check_01a_the_premises_were_all_checked,
    check_01b_the_two_repaired_premises_name_their_repair,
    check_01c_every_threshold_is_bounded_and_reasoned,
    check_01d_the_corner_mark_is_not_an_exemption,
    check_02a_every_branch_is_enumerated_with_its_channel,
    check_02b_the_configurable_surface_verdict_is_recorded,
    check_02c_the_self_check_passed_on_both_sides,
    check_02d_the_criterion_names_nothing_local,
    check_03a_the_measurement_covers_the_whole_corpus,
    check_03b_all_four_exposure_classes_are_filled,
    check_03c_the_reverse_sample_is_reviewed_and_its_limit_declared,
    check_04a_the_repair_is_the_one_alternative,
    check_04b_the_harness_reproduces_the_frozen_annotation,
    check_04c_the_mislabels_fell_and_none_were_introduced,
    check_04d_the_reference_formulas_survived,
    check_04e_one_criterion_answered_before_and_after,
    check_04f_the_repair_special_cases_nothing,
    check_04g_the_annotator_itself_was_not_touched,
    check_05a_every_consumer_was_enumerated_before_the_change,
    check_05b_the_revision_narrows_and_is_recorded,
    check_05c_conservation_holds_against_the_baseline,
    check_05d_no_detector_count_rose,
    check_05e_every_baseline_residue_has_a_disposition,
    check_05f_the_caption_is_no_longer_placeholders,
    check_06a_the_run_set_is_the_declared_one,
    check_06b_no_off_arm_was_produced,
    check_06c_the_delta_is_the_declared_surface,
    check_06d_the_gate_names_no_run_local_identifier,
    check_06e_the_evidence_this_gate_reads_is_declared,
)


def main() -> int:
    print("spec_check_b11_3: the formula mislabel, its criterion and its repair\n")
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
