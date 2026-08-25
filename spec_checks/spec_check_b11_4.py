"""Gate script for batch B11.4 (the vertical branch: what it really detects).

Run from the repository root:

    python spec_checks/spec_check_b11_4.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request. Every assertion is answered from a stub this gate builds or
from the small derived evidence this batch wrote beside its run -- never from a
stage checkpoint and never from a produced PDF, per CLAUDE.md section 4.16.

What this batch is. b11.3 measured sixty-eight formula mislabels and found that
thirty-nine of them arrive through one branch, ``or char.vertical`` at
styles_and_formulas.py:446. This batch asks what that branch is actually
detecting, and answers before deciding whether to touch it.

T0 preserved first. The stage-05 checkpoints -- the last taken before any
formula exists, and the only input from which "what these characters were
before" can be read -- were in use and unprotected (GAP-34). Twelve are now on
the protected list, and the acceptance shows the policy sparing them while it
goes on selecting other files of the same batch.

T1 froze the criterion before measuring. Three classes from two signals, the
text matrix and the font's writing mode, and nothing else.

T2 found that the intermediate language does not carry either signal:
``char.vertical`` is set from ``matrix[0] == 0 and matrix[3] == 0`` alone, so
both had to be recovered by re-parsing the source PDFs. Of 977 vertical
characters in the corpus, 977 are rotated horizontal text and none is set in a
vertical-mode font. The branch has never once fired on vertical writing.

T3 determined not to repair. All thirty-nine are excluded from translation, and
that is the outcome the content wants: re-annotating them as text would send
rotated credit rails to the model and lay the replies out horizontally over the
artwork, because typesetting.py:861 builds a translated character with
vertical=False. The annotation is wrong about what the content is and right
about what to do with it, so the finding is registered rather than repaired.

00 is T0: the retention acceptance and its control.
01 is T1: the criterion frozen ahead of the measurement, and its self-check.
02 is T2: the classification, its completeness and its join.
03 is the downstream cost table and the hazard count.
04 is the reverse sample.
05 is T3: the determination, the repair branch, and the gap entry.
06 is T4 and T5: the two rules, the ruled term, conservation and scope.

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
from tools import prune_outputs  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b11.4"

BATCH_DIR = ROOT / "examples" / "output" / "b11_4"
BASELINE_BATCH = ROOT / "examples" / "output" / "b10_5"

PREMISE = BATCH_DIR / "premise_check.json"
T0 = BATCH_DIR / "t0_retention.json"
FREEZE = BATCH_DIR / "t1_criterion_freeze.json"
SELFCHECK = BATCH_DIR / "t1_selfcheck.json"
CLASSIFICATION = BATCH_DIR / "t2_classification.json"
COST = BATCH_DIR / "t2_downstream_cost.json"
REVERSE = BATCH_DIR / "t2_reverse_sample.json"
INVENTORY = BATCH_DIR / "t3_consumer_inventory.json"
DETERMINATION = BATCH_DIR / "t3_determination.json"
T5 = BATCH_DIR / "t5_conservation.json"

CRITERION_SOURCE = BATCH_DIR / "scripts" / "vertical_criterion.py"
CRITERION_CONFIG = BATCH_DIR / "vertical_criterion_config.json"

# What this gate reads and the retention policy must therefore not remove.
# CLAUDE.md section 4.16: all of it is derived evidence this batch extracted at
# run time, and none of it is a checkpoint or a PDF.
GATE_EVIDENCE = (
    "examples/output/b11_4/premise_check.json",
    "examples/output/b11_4/t0_retention.json",
    "examples/output/b11_4/t1_criterion_freeze.json",
    "examples/output/b11_4/t1_selfcheck.json",
    "examples/output/b11_4/t2_classification.json",
    "examples/output/b11_4/t2_downstream_cost.json",
    "examples/output/b11_4/t2_reverse_sample.json",
    "examples/output/b11_4/t3_consumer_inventory.json",
    "examples/output/b11_4/t3_determination.json",
    "examples/output/b11_4/t5_conservation.json",
    "examples/output/b11_4/vertical_criterion_config.json",
    "examples/output/b11_4/scripts/vertical_criterion.py",
)

CORPUS = ("AramcoWorld-en-v2", "CERNCourier-en", "Courier-en",
          "Courier-zh", "FD-en-v2", "Vogue-en")

# The two stages T0 protects, and the count each contributes: six samples times
# the two serialisations.
PROTECTED_STAGES = ("checkpoint.05_paragraph_finder",
                    "checkpoint.06_styles_and_formulas")
PER_STAGE = 12

# The branch this batch is about, and the file that holds it. Both must be
# untouched: the determination is not to repair.
STYLES_AND_FORMULAS = (ROOT / "babeldoc" / "format" / "pdf" / "document_il"
                       / "midend" / "styles_and_formulas.py")
VERTICAL_BRANCH = "or char.vertical"

# The four downstream cost columns, every one of which every row must answer.
COST_COLUMNS = ("a_placeholder_pollution", "b_excluded_from_translation",
                "c_grouping_broken", "d_render_disagrees_with_source")

# The three classes. `undetermined` is not among them and must not appear.
CLASSES = ("R", "V", "U")

MISLABEL_ROWS = 39

# The delta this batch is allowed. No pipeline file is here, because the
# determination is to register rather than to repair. The three older gates are
# here for one mechanical repair this batch's full sweep forced: b0's 09, b1's
# 09d and b2's 11c forbid CJK anywhere under spec_checks/*.py, and b11.1 through
# b11.3 had left fourteen such lines behind. Those three gates are in the sweep
# set, which no batch since F3 had run, so nothing caught it until now. The
# literals were replaced by escapes of the same characters; W-B11-13 records it.
ALLOWED_PREFIXES = (
    "configs/output_retention.json",
    "docs/eval/gap_register.md",
    "spec_checks/spec_check_b11_1.py",
    "spec_checks/spec_check_b11_2.py",
    "spec_checks/spec_check_b11_3.py",
    "spec_checks/spec_check_b11_4.py",
    "spec_checks/run_all.py",
    "docs/reports/archive/",
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "plans/PLAN_B11_4.md",
    "examples/output/b11_4/",
)

# Trees this batch reads and never writes. This is tighter than the plan's
# declared surface in one place, deliberately: the plan allowed
# reviews/FD-en-v2.decisions.json for T5, but the term T5 asks for was already
# in it, filed by the corpus owner and landed with b11.2. So the ruling is here
# among the read-only trees, which is what CLAUDE.md section 5.12 wants of it
# whenever a machine session has nothing to add to it.
READ_ONLY_TREES = ("prompts/", "corpus/", "reviews/",
                   "babeldoc/",
                   "examples/output/b11_3/",
                   "examples/output/b10_5/")

# Headings this gate looks for inside Chinese prose, written as escapes so that
# the gate file itself stays pure ASCII. spec_check_b1's 09d scans
# spec_checks/*.py for CJK, and it is the same reasoning that keeps its own
# CJK_RANGES as code points.
WHAT_WOULD_MAKE_IT_HARMFUL = "\u4f55\u79cd\u53d8\u66f4\u4f1a\u4f7f\u5176\u53d8\u4e3a\u6709\u5bb3"  # what change would make this harmful
WHY_UNREPAIRED = "\u672a\u4fee\u7684\u539f\u56e0"  # why it was not repaired
WHY_HARMLESS = "\u4e3a\u4f55\u65e0\u5bb3"  # why it is harmless
CONSUMER_INVENTORY = "\u6d88\u8d39\u8005\u6e05\u5355"  # consumer inventory

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b11_4")


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


def sha256_of(path: Path) -> str:
    return hashlib.sha256(evidence.read_bytes(path)).hexdigest()


def protected_entry(sample: str, stage: str, ext: str) -> str:
    return f"examples/output/b10_5/{sample}/on/work/{sample}/{stage}.{ext}"


# The code point ranges b0, b1 and b2 forbid under spec_checks/*.py, kept as
# numbers here for the same reason those gates keep theirs that way.
_CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))


def _cjk_literals(source: str) -> set:
    """Every Chinese string constant a module evaluates to."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(any(low <= ord(c) <= high for low, high in _CJK_RANGES)
                   for c in node.value):
                found.add(node.value)
    return found


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


# --- 00 T0: the stage-05 preservation ----------------------------------------


def check_00a_both_stages_are_registered() -> None:
    """Positive 0a: twenty-four files, both stages, on the policy's list.

    Read as a shape rather than compared to a copied list, so a file quietly
    dropped from either side fails here. Stage 06 is b11.3's registration and is
    asserted alongside stage 05, because T0's acceptance is that both survive.
    """
    config = prune_outputs.load_config()
    listed = {str(entry) for entry in config[prune_outputs.PROTECTED_PATHS_KEY]}
    faults = []
    for stage in PROTECTED_STAGES:
        for sample in CORPUS:
            for ext in ("json", "xml"):
                entry = protected_entry(sample, stage, ext)
                if entry not in listed:
                    faults.append(f"{entry} is not protected")
                if not (ROOT / entry).is_file():
                    faults.append(f"{entry} is not on the disk")
    record("check_00a_both_stages_are_registered", not faults,
           "; ".join(faults[:4]))


def check_00b_the_policy_spares_them_and_still_selects() -> None:
    """Positive 0b: the acceptance ran under the real condition, with a control.

    Three things must hold together. This batch has a directory, so b10.5 is
    outside the keep window and everything in it is eligible. All twenty-four
    survive with a size on record. And the policy is selecting other files of
    b10.5 in the same pass -- without that control, a policy that had stopped
    selecting anything at all would pass.
    """
    data = load(T0)
    faults = []
    if not data.get("batch_directory_present"):
        faults.append("the acceptance ran without this batch's directory present")
    if data.get("b10_5_inside_keep_window"):
        faults.append("b10.5 was still inside the keep window; the test proves nothing")
    if data.get("target_count") != PER_STAGE * 2:
        faults.append(f"expected {PER_STAGE * 2} targets, found {data.get('target_count')}")
    for name in ("stage_05_count", "stage_06_count"):
        if data.get(name) != PER_STAGE:
            faults.append(f"{name} is {data.get(name)}, expected {PER_STAGE}")
    if data.get("survivors") != PER_STAGE * 2:
        faults.append(f"only {data.get('survivors')} of {PER_STAGE * 2} survived")
    for row in data.get("targets") or []:
        if row.get("selected_for_removal"):
            faults.append(f"the policy would remove {row.get('path')}")
            break
        if not row.get("size_bytes"):
            faults.append(f"{row.get('path')} has no size on record")
            break
    if not data.get("control_other_b10_5_files_selected"):
        faults.append("the control is empty: the policy selected nothing at all in b10.5")
    after = data.get("post_sweep_verification") or {}
    if not after:
        faults.append("no verification was taken after a real sweep")
    else:
        if not after.get("all_unchanged_after_the_sweep"):
            faults.append(f"files moved across the sweep: {after.get('faults')}")
        if after.get("files_rechecked") != PER_STAGE * 2:
            faults.append("the post-sweep recheck did not cover every target")
        # The strongest form of this acceptance: the policy was not asked what it
        # would take, it was allowed to take it. The disk filled during this
        # session, the user directed the apply, and 1573 files went. These
        # twenty-four did not.
        real = after.get("destructive_prune") or {}
        if not real:
            faults.append("no destructive prune is on record")
        else:
            if not real.get("all_survived_byte_for_byte"):
                faults.append(f"a protected file did not survive the prune: "
                              f"{real.get('faults')}")
            if real.get("protected_targets_rechecked") != PER_STAGE * 2:
                faults.append("the post-prune recheck did not cover every target")
            if not real.get("files_removed"):
                faults.append("the prune removed nothing, so it proves nothing")
            for name in real.get("archives_written") or []:
                if not (ROOT / name).is_file():
                    faults.append(f"an archive the prune wrote is missing: {name}")
    record("check_00b_the_policy_spares_them_and_still_selects", not faults,
           "; ".join(faults[:4]))


def check_00c_the_registration_did_not_widen_anything_else() -> None:
    """Negative 0c: only the protected list moved.

    W-B11-12 promises the archive ceiling and the archive patterns are untouched
    and that no directory was registered in place of files. Checked against the
    configuration rather than taken on the waiver's word.
    """
    config = prune_outputs.load_config()
    faults = []
    if int(config[prune_outputs.ARCHIVE_MAX_KB_KEY]) != 2048:
        faults.append("the archive ceiling moved, which the waiver forbids")
    if tuple(config[prune_outputs.ARCHIVE_PATTERNS_KEY]) != ("*.report.md", "*.json", "*.log"):
        faults.append("the archive patterns moved, which the waiver forbids")
    for entry in config[prune_outputs.PROTECTED_PATHS_KEY]:
        text = str(entry)
        if "checkpoint.05_paragraph_finder" in text and not text.endswith((".json", ".xml")):
            faults.append(f"a directory was registered rather than a file: {text}")
    waivers = (ROOT / "WAIVERS.md").read_text(encoding="utf-8")
    if "W-B11-12" not in waivers:
        faults.append("the stage-05 registration is not registered in WAIVERS.md")
    record("check_00c_the_registration_did_not_widen_anything_else", not faults,
           "; ".join(faults[:4]))


# --- 01 T1: the criterion, frozen ahead of the measurement -------------------


def check_01a_the_criterion_hash_matches_the_freeze() -> None:
    """Positive 1a: what was hashed before the measurement is what is on disk.

    The freeze exists so that the criterion cannot be adjusted afterwards to
    suit the numbers. Both files are pinned, source and configuration, because
    the thresholds live in the second.
    """
    frozen = load(FREEZE)
    faults = []
    if not frozen.get("frozen_before_measurement"):
        faults.append("the freeze does not claim to precede the measurement")
    pairs = ((CRITERION_SOURCE, "criterion_source_sha256"),
             (CRITERION_CONFIG, "criterion_config_sha256"))
    for path, key in pairs:
        actual = sha256_of(path)
        if actual != frozen.get(key):
            faults.append(f"{path.name} hashes {actual[:12]}, "
                          f"frozen as {str(frozen.get(key))[:12]}")
    measured = load(CLASSIFICATION).get("criterion_sha256")
    if measured != frozen.get("criterion_source_sha256"):
        faults.append("the measurement was taken with a different criterion than the "
                      "one frozen")
    record("check_01a_the_criterion_hash_matches_the_freeze", not faults,
           "; ".join(faults[:4]))


def check_01b_the_criterion_names_nothing_local() -> None:
    """Negative 1b: no publication, sample or sample string appears in it.

    CLAUDE.md section 4.5. The criterion may speak of matrices and writing modes
    and of nothing that identifies a particular document.
    """
    text = evidence.read_bytes(CRITERION_SOURCE).decode("utf-8")
    config_text = evidence.read_bytes(CRITERION_CONFIG).decode("utf-8")
    faults = []
    for name in (*CORPUS, "UNESCO", "Courier", "Vogue", "Aramco", "CERN"):
        for where, body in (("source", text), ("config", config_text)):
            if name.lower() in body.lower():
                faults.append(f"the criterion {where} names {name}")
    record("check_01b_the_criterion_names_nothing_local", not faults,
           "; ".join(faults[:4]))


def check_01c_the_threshold_is_inside_its_declared_range() -> None:
    """Positive 1c: the one bounded parameter carries a range and sits in it.

    CLAUDE.md section 4.4: a numeric threshold is declared with its permitted
    interval, so that a value moved out of bounds fails rather than silently
    applying.
    """
    config = json.loads(evidence.read_bytes(CRITERION_CONFIG).decode("utf-8"))
    faults = []
    conditions = config.get("conditions") or {}
    if not conditions:
        faults.append("the criterion declares no bounded conditions")
    for name, entry in conditions.items():
        value = entry.get("value")
        bounds = entry.get("range")
        if value is None or not bounds or len(bounds) != 2:
            faults.append(f"{name} carries no value or no range")
            continue
        if not (float(bounds[0]) <= float(value) <= float(bounds[1])):
            faults.append(f"{name}={value} is outside {bounds}")
        if not entry.get("why"):
            faults.append(f"{name} carries no reasoning")
    record("check_01c_the_threshold_is_inside_its_declared_range", not faults,
           "; ".join(faults[:4]))


def check_01d_the_self_check_covers_both_directions() -> None:
    """Positive 1d: reviewed cases on the side that fires, and on the sides that do not.

    The plan asks for review on both sides. Only one class occurs in this
    corpus, so the honest form of "both directions" is: the class with instances
    is reviewed against real glyphs, and the classes without are exercised
    against the predicate and recorded as never having met a real one. A self
    check that quietly omitted the empty classes would read as coverage it does
    not have.
    """
    data = load(SELFCHECK)
    faults = []
    if not data.get("seed"):
        faults.append("the draw records no seed")
    samples = data.get("samples") or {}
    for name in CLASSES:
        if name not in samples:
            faults.append(f"class {name} is missing from the self check")
            continue
        entry = samples[name]
        if entry.get("population"):
            if not entry.get("reviewed"):
                faults.append(f"class {name} has instances but none was reviewed")
            for case in entry.get("cases") or []:
                if case.get("class") != name:
                    faults.append(f"a case filed under {name} classifies as "
                                  f"{case.get('class')}")
                    break
                if not (case.get("geometry") or {}).get("run_travels"):
                    faults.append(f"a {name} case carries no independent geometry")
                    break
                if case.get("matrix") is None or case.get("font_is_vertical") is None:
                    faults.append(f"a {name} case carries no matrix or writing mode")
                    break
        elif not entry.get("note"):
            faults.append(f"class {name} is empty and says nothing about being empty")
    if not data.get("predicate_cases_all_agree"):
        faults.append("the predicate disagrees with its own stated classes")
    cases = data.get("predicate_cases") or []
    if {case.get("expected") for case in cases} != set(CLASSES):
        faults.append("the predicate cases do not exercise all three classes")
    record("check_01d_the_self_check_covers_both_directions", not faults,
           "; ".join(faults[:4]))


# --- 02 T2: the classification -----------------------------------------------


def check_02a_every_mislabel_is_classified() -> None:
    """Positive 2a: thirty-nine rows, each with a class and no undetermined."""
    data = load(CLASSIFICATION)
    faults = []
    rows = data.get("rows") or []
    if len(rows) != MISLABEL_ROWS:
        faults.append(f"expected {MISLABEL_ROWS} rows, found {len(rows)}")
    tally = data.get("class_tally") or {}
    if sum(tally.values()) != len(rows):
        faults.append("the tally does not account for every row")
    for row in rows:
        if row.get("vertical_class") not in CLASSES:
            faults.append(f"{row.get('sample')} {row.get('anchor')} is classified "
                          f"{row.get('vertical_class')!r}")
            break
    for name in ("undetermined", "unknown", "mixed"):
        if name in tally:
            faults.append(f"the tally carries a {name!r} class")
    record("check_02a_every_mislabel_is_classified", not faults,
           "; ".join(faults[:4]))


def check_02b_every_row_carries_its_matrix_evidence() -> None:
    """Positive 2b: the four matrix entries and the writing mode, per row.

    The class is a conclusion; these are what it was drawn from. A row that
    carries the conclusion without the evidence cannot be re-judged by anyone.
    """
    data = load(CLASSIFICATION)
    faults = []
    for row in data.get("rows") or []:
        matrix = row.get("matrix_witness")
        if not matrix or len(matrix) != 4:
            faults.append(f"{row.get('sample')} {row.get('anchor')} has no four-entry "
                          "matrix")
            break
        if row.get("font_is_vertical_witness") is None:
            faults.append(f"{row.get('sample')} {row.get('anchor')} records no font "
                          "writing mode")
            break
        if not row.get("n_joined"):
            faults.append(f"{row.get('sample')} {row.get('anchor')} joined no character")
            break
    record("check_02b_every_row_carries_its_matrix_evidence", not faults,
           "; ".join(faults[:4]))


def check_02c_the_join_to_the_re_parse_is_exact() -> None:
    """Positive 2c: no row was matched approximately.

    The matrix is not in the intermediate language and had to be recovered by
    re-parsing the source PDF. That recovery is only worth anything if the
    character stream it produced is the same one the frozen checkpoint holds,
    and an exact bounding-box join over every character is what shows it. One
    miss and the recovery is describing a different parse.
    """
    data = load(CLASSIFICATION)
    faults = []
    if data.get("join_misses") != 0:
        faults.append(f"{data.get('join_misses')} characters did not join")
    if "matrix_recovered_from" not in data:
        faults.append("the evidence does not say where the matrix came from")
    for row in data.get("rows") or []:
        if row.get("n_joined") != row.get("n_vertical_chars"):
            faults.append(f"{row.get('sample')} {row.get('anchor')}: "
                          f"{row.get('n_joined')} of {row.get('n_vertical_chars')} joined")
            break
    record("check_02c_the_join_to_the_re_parse_is_exact", not faults,
           "; ".join(faults[:4]))


def check_02d_the_finding_is_stated_corpus_wide() -> None:
    """Positive 2d: the classification covers every vertical character, not just the flagged ones.

    Thirty-nine rows say what the branch did to the mislabels. The claim the
    batch actually makes -- that the branch is a rotation detector -- is about
    the branch, so it has to be answered over every character the branch fires
    on.
    """
    data = load(DETERMINATION)
    faults = []
    wide = data.get("classification", {}).get("corpus_wide_classification") or {}
    total = data.get("classification", {}).get("corpus_wide_vertical_characters")
    if not wide or total is None:
        faults.append("no corpus-wide classification is recorded")
    elif sum(wide.values()) != total:
        faults.append("the corpus-wide tally does not sum to the character count")
    selfcheck = load(SELFCHECK)
    if selfcheck.get("population_total") != total:
        faults.append("the self check and the determination disagree about how many "
                      "vertical characters there are")
    if selfcheck.get("population") != wide:
        faults.append("the self check and the determination disagree about the classes")
    record("check_02d_the_finding_is_stated_corpus_wide", not faults,
           "; ".join(faults[:4]))


# --- 03 the downstream cost and the hazard -----------------------------------


def check_03a_every_row_answers_all_four_columns() -> None:
    """Positive 3a: thirty-nine rows times four columns, none left blank.

    "No hit in any column" must be written down as such rather than left to be
    inferred from an absence, because that row is the evidence the determination
    rests on.
    """
    data = load(COST)
    faults = []
    rows = data.get("rows") or []
    if len(rows) != MISLABEL_ROWS:
        faults.append(f"expected {MISLABEL_ROWS} rows, found {len(rows)}")
    for row in rows:
        hits = row.get("hits") or {}
        for column in COST_COLUMNS:
            if not isinstance(row.get(column), bool):
                faults.append(f"{row.get('sample')} {row.get('anchor')} leaves "
                              f"{column} unanswered")
                break
        if set(hits) != {"a", "b", "c", "d"}:
            faults.append(f"{row.get('sample')} {row.get('anchor')} has an incomplete "
                          "hit record")
            break
        if not isinstance(row.get("any_hit"), bool):
            faults.append(f"{row.get('sample')} {row.get('anchor')} does not state "
                          "whether anything was hit")
            break
        if row.get("any_hit") != any(hits.values()):
            faults.append(f"{row.get('sample')} {row.get('anchor')}: any_hit disagrees "
                          "with its own columns")
            break
    totals = data.get("totals") or {}
    for column in COST_COLUMNS:
        if column not in totals:
            faults.append(f"the totals do not carry {column}")
    if totals.get("no_hit_in_any_category") is None:
        faults.append("the totals do not state how many rows hit nothing")
    record("check_03a_every_row_answers_all_four_columns", not faults,
           "; ".join(faults[:4]))


def check_03b_each_column_total_agrees_with_its_rows() -> None:
    """Positive 3b: the summary is a count of the table and not a claim beside it."""
    data = load(COST)
    rows = data.get("rows") or []
    totals = data.get("totals") or {}
    faults = []
    for column in COST_COLUMNS:
        counted = sum(1 for row in rows if row.get(column))
        if totals.get(column) != counted:
            faults.append(f"{column}: totals say {totals.get(column)}, rows say {counted}")
    counted = sum(1 for row in rows if not row.get("any_hit"))
    if totals.get("no_hit_in_any_category") != counted:
        faults.append("the no-hit total disagrees with the rows")
    record("check_03b_each_column_total_agrees_with_its_rows", not faults,
           "; ".join(faults[:4]))


def check_03c_the_exclusion_column_names_its_gate() -> None:
    """Positive 3c: a row excluded from translation says which line refused it.

    "Not sent" is only evidence if it names the gate that did not send it.
    Otherwise it is indistinguishable from a row the measurement failed to find.
    """
    data = load(COST)
    faults = []
    for row in data.get("rows") or []:
        if row.get("b_excluded_from_translation") and not row.get("b_reason"):
            faults.append(f"{row.get('sample')} {row.get('anchor')} is excluded with "
                          "no reason given")
            break
        if not row.get("b_excluded_from_translation") and row.get("b_reason"):
            faults.append(f"{row.get('sample')} {row.get('anchor')} was sent but "
                          "carries an exclusion reason")
            break
        if row.get("c_grouping_broken") and not row.get("c_evidence"):
            faults.append(f"{row.get('sample')} {row.get('anchor')} claims broken "
                          "grouping with no evidence")
            break
    record("check_03c_the_exclusion_column_names_its_gate", not faults,
           "; ".join(faults[:4]))


def check_03d_the_hazard_carriers_are_counted() -> None:
    """Positive 3d: the absolute prohibition is a count, not an inheritance.

    A composition carrying pdf_form or pdf_curve must never be re-annotated,
    because PdfLine has no field to receive either. The count is asserted so
    that a later corpus holding a carrier fails here instead of inheriting this
    batch's answer. Where the count is not zero, the determination must show
    those entries were left alone; where there is no repair at all, that is
    stated explicitly rather than passing by default.
    """
    classification = load(CLASSIFICATION)
    inventory = load(INVENTORY)
    determination = load(DETERMINATION)
    faults = []
    counted = sum(1 for row in classification.get("rows") or []
                  if row.get("carries_pdf_form") or row.get("carries_pdf_curve"))
    if classification.get("harmful_carriers") != counted:
        faults.append("the carrier count disagrees with the rows")
    hazard = inventory.get("hazard_check") or {}
    if hazard.get("carrying_pdf_form") != sum(1 for row in classification.get("rows") or []
                                              if row.get("carries_pdf_form")):
        faults.append("the inventory's form count disagrees with the classification")
    if hazard.get("carrying_pdf_curve") != sum(1 for row in classification.get("rows") or []
                                               if row.get("carries_pdf_curve")):
        faults.append("the inventory's curve count disagrees with the classification")
    if hazard.get("compositions_examined") != MISLABEL_ROWS:
        faults.append("the hazard check did not examine every row")
    stated = (determination.get("hazard_class") or {}).get(
        "compositions_carrying_pdf_form_or_pdf_curve")
    if stated != counted:
        faults.append("the determination's carrier count disagrees with the evidence")
    if counted:
        if determination.get("decision") == "do not repair":
            faults.append("carriers exist and no repair was made; they must be shown "
                          "to have been left alone by a repair that happened")
    elif determination.get("decision") != "do not repair":
        faults.append("the vacuous case must be satisfied by a zero count or by there "
                      "being no repair, and neither is stated")
    record("check_03d_the_hazard_carriers_are_counted", not faults,
           "; ".join(faults[:4]))


def check_03e_the_inventory_was_rebuilt_and_covers_the_render_path() -> None:
    """Positive 3e: a fresh inventory, and the three sites that decide the question.

    CLAUDE.md section 4.18 forbids reusing a previous batch's list. The three
    sites named here are the ones that make re-annotation harmful, and an
    inventory that omitted any of them would have reached the opposite verdict.
    """
    data = load(INVENTORY)
    faults = []
    if not data.get("rebuilt_not_reused"):
        faults.append("the inventory does not say it was rebuilt")
    sites = " ".join(entry.get("site", "") for entry in data.get("sites") or [])
    required = ("il_translator_llm_only.py:642", "typesetting.py:1727",
                "line_split.py:292", "pdf_creater.py:867")
    for name in required:
        if name.split(":")[0] not in sites:
            faults.append(f"the inventory does not reach {name}")
    for entry in data.get("sites") or []:
        if not entry.get("if_reannotated"):
            faults.append(f"{entry.get('site')} does not answer what re-annotation does")
            break
        if not entry.get("today"):
            faults.append(f"{entry.get('site')} does not say what happens today")
            break
    record("check_03e_the_inventory_was_rebuilt_and_covers_the_render_path", not faults,
           "; ".join(faults[:4]))


# --- 04 the reverse sample ---------------------------------------------------


def check_04a_the_reverse_sample_is_seeded_and_reviewed() -> None:
    """Positive 4a: seed, draw, verdicts, and a count stated as a bound.

    GAP-33 established the discipline: thirty draws fix the order of magnitude,
    not the value, so the number is a lower bound and must say so.
    """
    data = load(REVERSE)
    faults = []
    if not data.get("seed"):
        faults.append("no seed is recorded")
    if not data.get("count_is_a_lower_bound"):
        faults.append("the count is not declared to be a lower bound")
    cases = data.get("cases") or []
    if len(cases) != data.get("draw_size"):
        faults.append(f"{len(cases)} cases drawn against a declared draw of "
                      f"{data.get('draw_size')}")
    if not data.get("population_size"):
        faults.append("the population the draw came from is not recorded")
    if data.get("population_size", 0) < len(cases):
        faults.append("the draw is larger than the population it came from")
    for case in cases:
        if not case.get("review_verdict"):
            faults.append(f"{case.get('sample')} {case.get('anchor')} carries no verdict")
            break
        if not case.get("why_b11_3_passed_it_over"):
            faults.append(f"{case.get('sample')} {case.get('anchor')} does not say why "
                          "it was passed over")
            break
    review = data.get("review") or {}
    if not review.get("missed_mislabels_is_a_lower_bound"):
        faults.append("the review does not state its count as a bound")
    if review.get("reviewed") != len(cases):
        faults.append("the review count disagrees with the cases")
    record("check_04a_the_reverse_sample_is_seeded_and_reviewed", not faults,
           "; ".join(faults[:4]))


# --- 05 T3: the determination ------------------------------------------------


def check_05a_the_determination_follows_from_the_measurement() -> None:
    """Positive 5a: the numbers in the verdict are the numbers in the tables.

    A determination that restates its evidence loosely can drift from it. Each
    figure it quotes is compared to the artefact that produced it.
    """
    determination = load(DETERMINATION)
    classification = load(CLASSIFICATION)
    cost = load(COST)
    faults = []
    stated = determination.get("classification") or {}
    tally = classification.get("class_tally") or {}
    if stated.get("R_rotated_text") != tally.get("R", 0):
        faults.append("the determination's R count disagrees with the classification")
    if stated.get("join_misses") != classification.get("join_misses"):
        faults.append("the determination's join count disagrees with the classification")
    quoted = determination.get("downstream_cost") or {}
    totals = cost.get("totals") or {}
    for column in COST_COLUMNS:
        if quoted.get(column) != totals.get(column):
            faults.append(f"the determination's {column} disagrees with the cost table")
    if determination.get("decision") not in ("repair", "do not repair"):
        faults.append("the determination states no decision")
    record("check_05a_the_determination_follows_from_the_measurement", not faults,
           "; ".join(faults[:4]))


def check_05b_the_repair_branch_is_honoured() -> None:
    """Positive 5b: whichever branch was taken, its obligations are met.

    The plan makes this conditional. Repaired: two arms, the before arm
    reproducing the frozen annotation, and no newly introduced mislabel. Not
    repaired: a gap entry that records the mislabel, why it is harmless, and --
    the part a later reader needs -- what change would make it harmful.
    """
    determination = load(DETERMINATION)
    faults = []
    register = (ROOT / "docs" / "eval" / "gap_register.md").read_text(encoding="utf-8")
    if determination.get("decision") == "do not repair":
        entry = determination.get("gap_registered")
        if not entry:
            faults.append("no gap entry is named")
        elif f"## {entry}" not in register:
            faults.append(f"{entry} is not in the gap register")
        else:
            section = register.split(f"## {entry}", 1)[1].split("\n## ", 1)[0]
            if WHAT_WOULD_MAKE_IT_HARMFUL not in section:
                faults.append(f"{entry} does not say what would make this harmful")
            if WHY_UNREPAIRED not in section and WHY_HARMLESS not in section:
                faults.append(f"{entry} does not say why it is harmless")
        if not determination.get("what_would_make_this_harmful"):
            faults.append("the determination itself does not carry the warning line")
    else:
        for name in ("before_arm", "after_arm"):
            if name not in determination:
                faults.append(f"a repair was made but no {name} is recorded")
    record("check_05b_the_repair_branch_is_honoured", not faults,
           "; ".join(faults[:4]))


def check_05c_the_rotated_reflow_question_is_answered() -> None:
    """Positive 5c: the plan's one required answer, and it names its code.

    The plan required this batch to say whether class R re-annotated as text
    would be reflowed horizontally over the artwork. An answer is only worth
    recording if it points at the lines that decide it, so those are asserted to
    be present and to be real.
    """
    data = load(DETERMINATION)
    faults = []
    answer = data.get("the_question_the_plan_required_an_answer_to") or {}
    for name in ("question", "answer", "consequence_for_the_shape_of_any_repair"):
        if not answer.get(name):
            faults.append(f"the answer carries no {name}")
    body = json.dumps(answer, ensure_ascii=False)
    for name in ("typesetting.py:861", "pdf_creater.py:111"):
        if name not in body:
            faults.append(f"the answer does not cite {name}")
    # Read as constructs rather than at the line numbers the answer cites. The
    # citation itself is asserted above and is left as b11.4 wrote it, because
    # it records what that batch looked at; what this pair checks is that the
    # code the answer rests on is still there. A line number is not that code:
    # b11.7 added a module level constant to the typesetting stage and every
    # line under it moved, which turned this red without anything the answer
    # said becoming untrue. AC-27.
    typesetting = (ROOT / "babeldoc" / "format" / "pdf" / "document_il" / "midend"
                   / "typesetting.py").read_text(encoding="utf-8")
    creater = (ROOT / "babeldoc" / "format" / "pdf" / "document_il" / "backend"
               / "pdf_creater.py").read_text(encoding="utf-8")
    if "vertical=False" not in typesetting:
        faults.append("the typesetting stage no longer builds a character with "
                      "vertical=False; the cited answer has gone stale")
    if "char.vertical" not in creater:
        faults.append("the writer no longer branches on char.vertical; the "
                      "cited answer has gone stale")
    record("check_05c_the_rotated_reflow_question_is_answered", not faults,
           "; ".join(faults[:4]))


def check_05d_the_branch_itself_was_not_touched() -> None:
    """Negative 5d: the determination was to register, so the code still reads as before.

    The disjunct at styles_and_formulas.py:446 must still be there. A batch that
    concluded "do not repair" and then repaired anyway would be the one failure
    this assertion exists to catch.
    """
    determination = load(DETERMINATION)
    faults = []
    text = STYLES_AND_FORMULAS.read_text(encoding="utf-8")
    if determination.get("decision") == "do not repair":
        if VERTICAL_BRANCH not in text:
            faults.append("the vertical disjunct is gone, but the decision was not to "
                          "repair")
        changed = changed_paths()
        touched = [p for p in changed if p.startswith("babeldoc/")]
        if touched:
            faults.append(f"pipeline files changed under a no-repair decision: "
                          f"{touched[:3]}")
        upstream = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
        if BATCH_TAG in upstream:
            faults.append("UPSTREAM_DIFF.md registers a change for a batch that made "
                          "none")
    record("check_05d_the_branch_itself_was_not_touched", not faults,
           "; ".join(faults[:4]))


# --- 06 T4, T5, conservation and scope ---------------------------------------


def check_06a_the_two_rules_are_in_claude_md() -> None:
    """Positive 6a: both rules, and both halves of each.

    Each rule has two parts, and a rule recorded with only its first half is a
    rule that will be half followed. The gate-output rule must carry both the
    prohibition and the two operational notes; the inventory rule must carry
    both the requirement and the absolute prohibition on re-annotating a
    graphic carrier.
    """
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    faults = []
    first = ("SPEC_NO_NESTED", "sweep.lock", "/dev/null")
    for token in first:
        if token not in text:
            faults.append(f"the gate-output rule does not mention {token}")
    second = ("pdf_form", "pdf_curve", "pdf_creater.py:867")
    for token in second:
        if token not in text:
            faults.append(f"the consumer-inventory rule does not mention {token}")
    if CONSUMER_INVENTORY not in text:
        faults.append("the consumer-inventory rule is not stated")
    record("check_06a_the_two_rules_are_in_claude_md", not faults,
           "; ".join(faults[:4]))


def check_06b_the_ruled_term_reached_the_page() -> None:
    """Positive 6b: the anchor the plan names carries the ruled term.

    Anchored by page-local index and by the term itself, never by a debug_id
    (CLAUDE.md section 5.13). The ruling file's hash is on the run record, and
    the ruling is the corpus owner's: this batch verified it and did not write
    it.
    """
    data = load(T5)
    faults = []
    term = data.get("ruled_term") or {}
    if not term.get("holds"):
        faults.append(f"{term.get('anchor')} renders {term.get('rendered')!r}, "
                      f"expected {term.get('expected')!r}")
    if not term.get("ruling_sha256"):
        faults.append("the ruling hash is not on the run record")
    ruling = ROOT / "reviews" / "FD-en-v2.decisions.json"
    if ruling.is_file():
        # The row this batch verified, and only that row. The whole file's
        # digest was compared here until b11.5, which is one batch too long: a
        # ruling is a living document that gains rows as its owner rules, so a
        # digest of the whole of it fails the next time the owner writes one and
        # says nothing about the row this assertion is about. The question the
        # digest was asking -- did a machine edit this file on its own -- is
        # asked where it belongs, against the pin that carries a change record
        # for every move (spec_check_b7_5's TRUTH_DIGESTS, CLAUDE.md 4.12).
        from spec_checks import spec_check_b7_5

        terms = json.loads(ruling.read_text(encoding="utf-8")).get("terms") or {}
        if terms.get("Masthead") != term.get("expected"):
            faults.append("the ruling does not carry the term the plan names")
        pinned = spec_check_b7_5.TRUTH_DIGESTS.get("reviews/FD-en-v2.decisions.json")
        actual = hashlib.sha256(ruling.read_bytes()).hexdigest()
        if pinned != actual:
            faults.append("the ruling on disk is not the one that is pinned")
        if not term.get("ruling_sha256"):
            faults.append("the run did not record which ruling it read")
    else:
        faults.append("the ruling file is missing")
    record("check_06b_the_ruled_term_reached_the_page", not faults,
           "; ".join(faults[:4]))


def check_06c_conservation_holds_against_the_unchanged_tree() -> None:
    """Positive 6c: pages, paragraph counts and anchors, against b11.3.

    b11.3 is the baseline that means something here. It repaired the formula
    font branch between b10.5 and now, and three of the faces it moved are this
    sample's, so a difference against b10.5 is that repair rather than this
    batch. This batch changed no pipeline code, so anything moving against b11.3
    must be the model sampling and must be bounded by the calls that reached it.
    """
    data = load(T5)
    faults = []
    against = data.get("against_b11_3") or {}
    if not against.get("page_count_conserved"):
        faults.append("the page count moved")
    if not against.get("paragraph_counts_conserved"):
        faults.append(f"paragraph counts moved: {against.get('paragraph_count_differences')}")
    if data.get("kinds_that_rose_against_b11_3"):
        faults.append(f"detector counts rose: {data.get('kinds_that_rose_against_b11_3')}")
    attribution = data.get("api_call_attribution") or {}
    if not attribution.get("bound_holds"):
        faults.append(f"{attribution.get('anchors_that_moved')} anchors moved against "
                      f"{attribution.get('api_calls')} api calls")
    if attribution.get("anchors_that_moved") != against.get("anchors_whose_text_differs"):
        faults.append("the attribution disagrees with the comparison")
    if not data.get("why_two_baselines"):
        faults.append("the evidence does not say why it carries two baselines")
    if (data.get("against_b10_5") or {}).get("anchors") != against.get("anchors"):
        faults.append("the two baselines were read over different anchor sets")
    record("check_06c_conservation_holds_against_the_unchanged_tree", not faults,
           "; ".join(faults[:4]))


def check_06d_the_delta_is_inside_the_declared_scope() -> None:
    """Negative 6d: nothing changed outside what the plan allows."""
    faults = []
    for path in changed_paths():
        if not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            faults.append(f"out of scope: {path}")
    record("check_06d_the_delta_is_inside_the_declared_scope", not faults,
           "; ".join(sorted(faults)[:6]))


def check_06e_the_read_only_trees_were_not_written() -> None:
    """Negative 6e: prompts, corpus, rulings, the pipeline and the frozen batches.

    b11.3's and b10.5's evidence is read by this batch and must come out of it
    byte for byte, which is CLAUDE.md section 4.13.
    """
    faults = []
    for path in changed_paths():
        for tree in READ_ONLY_TREES:
            if path.startswith(tree):
                faults.append(f"{path} is under the read-only tree {tree}")
    record("check_06e_the_read_only_trees_were_not_written", not faults,
           "; ".join(sorted(faults)[:6]))


def check_06f_the_gate_declares_what_it_reads() -> None:
    """Positive 6f: GATE_EVIDENCE names what is read, and none of it is a checkpoint.

    CLAUDE.md section 4.16. The declaration is what the retention policy reads
    to route around this gate's evidence, so an entry that is not on the disk,
    or one that is a checkpoint the archive could never hold, is a fault.
    """
    faults = []
    declared = set(GATE_EVIDENCE)
    for name in GATE_EVIDENCE:
        if "checkpoint." in name or name.endswith(".pdf"):
            faults.append(f"{name} is a checkpoint or a PDF and cannot be archived")
        if not (ROOT / name).is_file():
            faults.append(f"{name} is declared but not on the disk")
    for path in (PREMISE, T0, FREEZE, SELFCHECK, CLASSIFICATION, COST, REVERSE,
                 INVENTORY, DETERMINATION, T5, CRITERION_CONFIG, CRITERION_SOURCE):
        relative = path.relative_to(ROOT).as_posix()
        if relative not in declared:
            faults.append(f"{relative} is read but not declared")
    record("check_06f_the_gate_declares_what_it_reads", not faults,
           "; ".join(faults[:4]))


def check_06g_the_premises_were_checked_and_their_corrections_recorded() -> None:
    """Positive 6g: six premises, each with a verdict, corrections written down.

    CLAUDE.md section 5.2 asks a session to stop where a premise does not hold.
    Three of these carry line-number or path corrections and one carries a count
    correction, and the point of this assertion is that a correction is recorded
    rather than quietly absorbed.
    """
    data = load(PREMISE)
    faults = []
    rows = data.get("premises") or []
    if len(rows) != 6:
        faults.append(f"expected six premises, found {len(rows)}")
    for row in rows:
        if row.get("holds") is None:
            faults.append(f"premise {row.get('id')} carries no verdict")
        if not row.get("evidence"):
            faults.append(f"premise {row.get('id')} carries no evidence")
    if not any(row.get("corrected") for row in rows):
        faults.append("no correction is recorded, but the premises needed some")
    if not data.get("verdict"):
        faults.append("the premise check reaches no overall verdict")
    record("check_06g_the_premises_were_checked_and_their_corrections_recorded",
           not faults, "; ".join(faults[:4]))


def check_06h_no_assertion_anchors_on_a_debug_id() -> None:
    """Negative 6h: this gate names no debug_id, and neither does its evidence.

    CLAUDE.md section 5.13. A debug_id is reassigned on every run, so an
    assertion holding one is true only of the run that minted it.
    """
    faults = []
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.fullmatch(r"[A-Za-z0-9]{5}", node.value) and not node.value.isalpha():
                faults.append(f"a five-character token {node.value!r} looks like a "
                              "debug_id")
    for path in (CLASSIFICATION, COST):
        data = load(path)
        for row in data.get("rows") or []:
            if not re.fullmatch(r"p\d+#\d+", row.get("anchor") or ""):
                faults.append(f"{path.name} anchors a row on {row.get('anchor')!r}")
                break
    record("check_06h_no_assertion_anchors_on_a_debug_id", not faults,
           "; ".join(faults[:4]))


def check_06i_the_gate_files_are_ascii_and_kept_their_literals() -> None:
    """Positive 6i: the CJK repair changed the encoding and not the question.

    b0's 09, b1's 09d and b2's 11c forbid CJK under spec_checks/*.py. Four gate
    files were rewritten to satisfy them, and the only way that is a safe change
    is if every Chinese string each file matches on is still the same string.
    Both halves are asserted: the files are pure ASCII, and the set of Chinese
    literals each one evaluates to is unchanged against the commit before this
    batch.
    """
    faults = []
    for name in ("spec_check_b11_1.py", "spec_check_b11_2.py",
                 "spec_check_b11_3.py", "spec_check_b11_4.py"):
        path = ROOT / "spec_checks" / name
        text = path.read_text(encoding="utf-8")
        if not text.isascii():
            faults.append(f"{name} still carries non-ASCII")
        proc = subprocess.run(  # noqa: S603
            ["git", "show", f"HEAD:spec_checks/{name}"],  # noqa: S607
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        if proc.returncode != 0:
            continue  # a file HEAD does not carry yet is new and has nothing to keep
        before = _cjk_literals(proc.stdout)
        after = _cjk_literals(text)
        if before - after:
            faults.append(f"{name} lost the literals {sorted(before - after)[:2]}")
    record("check_06i_the_gate_files_are_ascii_and_kept_their_literals", not faults,
           "; ".join(faults[:4]))


CHECKS = (
    check_00a_both_stages_are_registered,
    check_00b_the_policy_spares_them_and_still_selects,
    check_00c_the_registration_did_not_widen_anything_else,
    check_01a_the_criterion_hash_matches_the_freeze,
    check_01b_the_criterion_names_nothing_local,
    check_01c_the_threshold_is_inside_its_declared_range,
    check_01d_the_self_check_covers_both_directions,
    check_02a_every_mislabel_is_classified,
    check_02b_every_row_carries_its_matrix_evidence,
    check_02c_the_join_to_the_re_parse_is_exact,
    check_02d_the_finding_is_stated_corpus_wide,
    check_03a_every_row_answers_all_four_columns,
    check_03b_each_column_total_agrees_with_its_rows,
    check_03c_the_exclusion_column_names_its_gate,
    check_03d_the_hazard_carriers_are_counted,
    check_03e_the_inventory_was_rebuilt_and_covers_the_render_path,
    check_04a_the_reverse_sample_is_seeded_and_reviewed,
    check_05a_the_determination_follows_from_the_measurement,
    check_05b_the_repair_branch_is_honoured,
    check_05c_the_rotated_reflow_question_is_answered,
    check_05d_the_branch_itself_was_not_touched,
    check_06a_the_two_rules_are_in_claude_md,
    check_06b_the_ruled_term_reached_the_page,
    check_06c_conservation_holds_against_the_unchanged_tree,
    check_06d_the_delta_is_inside_the_declared_scope,
    check_06e_the_read_only_trees_were_not_written,
    check_06f_the_gate_declares_what_it_reads,
    check_06g_the_premises_were_checked_and_their_corrections_recorded,
    check_06h_no_assertion_anchors_on_a_debug_id,
    check_06i_the_gate_files_are_ascii_and_kept_their_literals,
)


def main() -> int:
    print("spec_check_b11_4: the vertical branch, what it detects and what it costs\n")
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
