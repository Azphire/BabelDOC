"""Gate script for batch B11.2 (evidence preservation, residue determination,
exposure probe, in-page column measurement).

Run from the repository root:

    python spec_checks/spec_check_b11_2.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: every assertion is answered from a stub this gate builds, or
from the small derived evidence this batch wrote beside its runs.

What this batch is. Five tasks, three of them determinations that changed no
behaviour at all.

T0 preserved the evidence the batch needed before it could touch anything. The
retention policy keeps two batch directories; creating this batch's own
directory pushes b10.5 out of that window, and b10.5's stage checkpoints are
tens of megabytes, which is over the archive ceiling, so they would have been
deleted and not archived. They are now registered in ``protected_paths``.

T1 determined, for each of the eighteen untranslated residues on FD, what text
was actually sent for it. The answer was not the one the plan expected: eleven
were never sent at all, and ten of those were refused at one line, because a
paragraph whose every composition is a formula reads as placeholder only.

T2 counted, over the b10.5 on arm, how much of the corpus b11.1's two upstream
changes reach, and that count chose the samples this batch ran.

T3 measured whether a sentence runs on across a column break inside one page,
read only, and found that the known true positive is not scored at all because a
display line in its own band sits between the two text columns.

T4 answered the retention failure that stranded eight assertions in three older
gates. The eight are not recoverable and stay SKIPPED; what this batch added is
prospective -- gates declare the evidence they read, gates can read the archive,
and a gate sweep no longer applies the policy unless asked.

T5 pinned one glossary term and tightened the identity criterion to byte
equality.

00 is T0: the policy, and the sweep.
01 is T1: the determination table and the two b11.1 observations.
02 is T2: the probe, and that the run set is the set the probe named.
03 is T2's regression: conservation against the b10.5 on arm.
04 is T3: read only, and what it found.
05 is T4: the eight named and registered, and the archive fallback reached.
06 is T5.
07 is conservation, cost and scope.

Tiers: every assertion reads a stub or this batch's own derived evidence, so the
fast tier runs the whole gate.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec_checks import evidence  # noqa: E402
from spec_checks import harness  # noqa: E402
from tools import prune_outputs  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b11.2"
PREVIOUS_TAG = "b11.1"

BATCH_DIR = ROOT / "examples" / "output" / "b11_2"
BASELINE_BATCH = ROOT / "examples" / "output" / "b10_5"

EXPOSURE = BATCH_DIR / "exposure.report.json"
T0_EVIDENCE = BATCH_DIR / "t0_preservation.json"
T1_TABLE = BATCH_DIR / "t1_residue_classification.json"
T1_REFUSALS = BATCH_DIR / "t1_class_c_refusals.json"
T1_OBSERVATIONS = BATCH_DIR / "t1_b11_1_observations.json"
T3_REPORT = BATCH_DIR / "column_continuity.report.json"
T4_MATRIX = BATCH_DIR / "t4_recoverability.json"
T2_ATTRIBUTION = BATCH_DIR / "t2_regression_attribution.json"
RUNS = BATCH_DIR / "runs.json"

# What this gate reads and the retention policy must therefore not remove. The
# declaration CLAUDE.md section 4.16 requires, and what tools/prune_outputs.py
# reads out of every gate.
GATE_EVIDENCE = (
    "examples/output/b11_2/exposure.report.json",
    "examples/output/b11_2/t0_preservation.json",
    "examples/output/b11_2/t1_residue_classification.json",
    "examples/output/b11_2/t1_class_c_refusals.json",
    "examples/output/b11_2/t1_b11_1_observations.json",
    "examples/output/b11_2/column_continuity.report.json",
    "examples/output/b11_2/t4_recoverability.json",
    "examples/output/b11_2/t2_regression_attribution.json",
    "examples/output/b11_2/runs.json",
)

CORPUS = (
    "AramcoWorld-en-v2",
    "CERNCourier-en",
    "Courier-en",
    "Courier-zh",
    "FD-en-v2",
    "Vogue-en",
)

# The files T0 registered, as a shape rather than a list: six samples, the on
# arm, and the five working files the acceptance names.
PROTECTED_NAMES = (
    "checkpoint.09_il_translated.json",
    "checkpoint.09_il_translated.xml",
    "checkpoint.11_typesetting.json",
    "checkpoint.11_typesetting.xml",
    "translate_tracking.json",
)

# The assertions the retention failure stranded, by the gate that owns them.
# Named here because GAP-31 is a claim about exactly these and no others.
STRANDED = {
    "spec_check_b10_1.py": (
        "check_02b_the_flattened_column_starts_level_with_its_neighbour",
    ),
    "spec_check_b10_3.py": (
        "check_05b_every_record_is_set_as_its_own_characters_are",
        "check_06a2_a_blanked_member_occupies_nothing",
        "check_06b_the_two_halves_of_a_text_agree",
        "check_06e_the_evidence_is_present",
    ),
    "spec_check_b10_4.py": (
        "check_04f_the_short_labels_reach_a_request_and_land",
        "check_05e_the_ruling_reached_the_pages_it_names",
        "check_06a_the_evidence_is_present",
    ),
}

GAP_REGISTER = ROOT / "docs" / "eval" / "gap_register.md"
CLAUDE = ROOT / "CLAUDE.md"
RETENTION = ROOT / "configs" / "output_retention.json"
IL_TRANSLATOR = (
    ROOT / "babeldoc" / "format" / "pdf" / "document_il" / "midend" / "il_translator.py"
)
DECISIONS = ROOT / "reviews" / "FD-en-v2.decisions.json"

# The term this batch pinned, and where it has to show on the page.
PINNED_TERM = "Masthead"
PINNED_TARGET = "报头"
MASTHEAD_PAGE = 5

# The label that must still stand on one line after the criterion was tightened,
# and the pages it stands on.
SINGLE_LINE_LABEL = "F&D"
SINGLE_LINE_PAGES = (5, 6, 8)
SAME_LEFT_EDGE = 0.5
LINE_APART = 8.0

# The delta this batch is allowed.
ALLOWED_PREFIXES = (
    "babeldoc/format/pdf/document_il/midend/il_translator.py",
    "configs/output_retention.json",
    "docs/eval/gap_register.md",
    "docs/reports/assertion_contracts.md",
    "reviews/FD-en-v2.decisions.json",
    "spec_checks/evidence.py",
    "spec_checks/run_all.py",
    "spec_checks/spec_check_b7_5.py",
    "spec_checks/spec_check_b8_4.py",
    "spec_checks/spec_check_b9_5.py",
    "spec_checks/spec_check_b11_1.py",
    "spec_checks/spec_check_b11_2.py",
    "spec_checks/spec_check_e0.py",
    "tools/column_continuity.py",
    "tools/prune_outputs.py",
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "plans/PLAN_B11_2.md",
    "plans/PLAN_B11_2_REV2.md",
    "examples/output/b11_2/",
    "examples/output/run_all.b11_2.fast.log",
)

# Trees this batch reads and never writes. The ruling file is not among them:
# this batch was told to write one term into it.
READ_ONLY_TREES = ("prompts/", "corpus/", "babeldoc/magazine/chain_builder.py",
                   "babeldoc/magazine/chain_signals.py")

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b11_2")


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


# --- 00 T0: the evidence this batch stands on is not removable ----------------


def check_00a_the_baseline_working_files_are_registered() -> None:
    """Positive 0a: every file T0 names is on the policy's protected list.

    Thirty of them: six samples, the on arm, and the five working files the
    acceptance names. Read as a shape rather than compared to a copied list, so
    a file quietly dropped from either side fails here.
    """
    config = prune_outputs.load_config()
    listed = {str(entry) for entry in config[prune_outputs.PROTECTED_PATHS_KEY]}
    faults = []
    for sample in CORPUS:
        for name in PROTECTED_NAMES:
            entry = (
                f"examples/output/b10_5/{sample}/on/work/{sample}/{name}"
            )
            if entry not in listed:
                faults.append(f"{entry} is not protected")
            if not (ROOT / entry).is_file():
                faults.append(f"{entry} is not on the disk")
    record("check_00a_the_baseline_working_files_are_registered",
           not faults, "; ".join(faults[:4]))


def check_00b_the_policy_would_not_remove_them() -> None:
    """Positive 0b: with this batch's directory present, the policy spares them.

    The condition is the real one -- ``examples/output/b11_2/`` exists, so b10.5
    is outside the keep window -- and the control is that the policy is selecting
    other files of b10.5 at the same time. Without the control a policy that had
    simply stopped selecting anything would pass.
    """
    faults = []
    if not BATCH_DIR.is_dir():
        faults.append("this batch has no directory, so b10.5 is not evicted")
    config = prune_outputs.load_config()
    grouped = prune_outputs.batch_directories(prune_outputs.OUTPUT_DIR)
    recent = sorted(grouped, reverse=True)[: int(config[prune_outputs.KEEP_RECENT_KEY])]
    if (10, 5) in recent:
        faults.append("b10.5 is still inside the keep window; the test proves nothing")
    doomed, _ = prune_outputs.prunable(prune_outputs.OUTPUT_DIR, config)
    targets = {
        (ROOT / f"examples/output/b10_5/{s}/on/work/{s}/{n}").resolve()
        for s in CORPUS for n in PROTECTED_NAMES
    }
    trespass = sorted(
        p.relative_to(ROOT).as_posix() for p in doomed if p.resolve() in targets
    )
    if trespass:
        faults.append(f"would remove {trespass[:3]}")
    control = [p for p in doomed if "b10_5" in p.parts]
    if not control:
        faults.append("the policy selected nothing at all in b10.5")
    record("check_00b_the_policy_would_not_remove_them", not faults,
           "; ".join(faults[:4]))


def check_00c_a_gate_sweep_is_not_a_destroying_action() -> None:
    """Positive 0c: the sweep applies the policy only when it is asked to.

    The second of T0's two layers, and independent of the first: the runner is
    driven here with and without the request, with the subprocess stubbed, so
    what is asserted is that nothing is launched rather than that a flag exists.
    """
    from spec_checks import run_all as runner

    faults = []
    calls: list[list[str]] = []

    def record_call(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    original = runner.subprocess.run
    runner.subprocess.run = record_call
    try:
        runner.prune_outputs(False)
        if calls:
            faults.append("a sweep applied the policy without being asked")
        runner.prune_outputs(True)
        if not calls:
            faults.append("the policy cannot be applied even when asked")
    finally:
        runner.subprocess.run = original
    if runner.build_parser().parse_args([]).prune_outputs:
        faults.append("the runner asks for the policy by default")
    record("check_00c_a_gate_sweep_is_not_a_destroying_action", not faults,
           "; ".join(faults[:4]))


def check_00d_the_acceptance_was_recorded_against_a_real_sweep() -> None:
    """Positive 0d: T0's acceptance was taken from a sweep that actually ran."""
    faults = []
    if not T0_EVIDENCE.is_file():
        record("check_00d_the_acceptance_was_recorded_against_a_real_sweep",
               False, f"no {T0_EVIDENCE}")
        return
    payload = load(T0_EVIDENCE)
    live = payload.get("live_sweep_acceptance") or {}
    if payload.get("verdict") != "PASS":
        faults.append(f"policy acceptance verdict is {payload.get('verdict')}")
    if payload.get("registered_files") != len(CORPUS) * len(PROTECTED_NAMES):
        faults.append(f"registered {payload.get('registered_files')} files")
    if payload.get("registered_selected_for_removal"):
        faults.append("the record says registered files were selected")
    if not payload.get("control_other_b10_5_files_selected"):
        faults.append("the record has no control")
    if live.get("verdict") != "PASS":
        faults.append("no passing live sweep acceptance")
    if live.get("missing_after_the_sweep") != 0:
        faults.append(f"{live.get('missing_after_the_sweep')} files went missing")
    log = ROOT / (live.get("log") or "")
    if live.get("log") and not log.is_file():
        faults.append(f"the sweep log it cites is absent: {live.get('log')}")
    record("check_00d_the_acceptance_was_recorded_against_a_real_sweep",
           not faults, "; ".join(faults[:4]))


# --- 01 T1: the determination ------------------------------------------------


def check_01a_every_residue_is_determined() -> None:
    """Positive 1a: each residue carries a class and the evidence behind it.

    A determination assertion: it holds the table to being complete and to
    naming its evidence, and does not assert what the classes came out as. What
    the answer was belongs to the batch report, and pinning it here would make a
    later run that legitimately answers differently look like a regression.
    """
    faults = []
    payload = load(T1_TABLE)
    rows = payload.get("rows") or []
    if payload.get("undetermined"):
        faults.append(f"undetermined rows: {payload['undetermined']}")
    if not rows:
        faults.append("the table is empty")
    vocabulary = set(payload.get("class_vocabulary") or {})
    for row in rows:
        ref = row.get("issue_id")
        if row.get("class") not in vocabulary:
            faults.append(f"{ref}: class {row.get('class')!r} is outside the vocabulary")
        if not row.get("reason"):
            faults.append(f"{ref}: no reason")
        if row.get("aligned_by") in (None, "unresolved"):
            faults.append(f"{ref}: not aligned to a paragraph")
        if row.get("sent_to_translator"):
            if row.get("input") is None:
                faults.append(f"{ref}: sent, and no request text recorded")
        elif not row.get("refused_at"):
            faults.append(f"{ref}: not sent, and no refusal site named")
    record("check_01a_every_residue_is_determined", not faults,
           "; ".join(faults[:4]))


def check_01b_the_ninth_page_residue_is_determined_on_its_own() -> None:
    """Positive 1b: the page 9 residue is answered separately, as it was asked.

    It is not one of the masthead lines and not one of the rotated credits: a
    whole sentence of running text, on a page the ruling does not declare. The
    plan asked for it by name, so the table has to carry a row for it whose
    evidence stands on its own.
    """
    faults = []
    rows = (load(T1_TABLE).get("rows") or [])
    ninth = [r for r in rows if r.get("page") == 9 and r.get("sent_to_translator")]
    if not ninth:
        faults.append("no page 9 residue was recorded as having been sent")
    for row in ninth:
        if not row.get("source_text"):
            faults.append("the page 9 row records no source text")
        if row.get("input") is None:
            faults.append("the page 9 row records no request text")
    record("check_01b_the_ninth_page_residue_is_determined_on_its_own",
           not faults, "; ".join(faults[:4]))


def check_01c_every_refusal_names_a_line() -> None:
    """Positive 1c: a residue that was never sent says where it was refused.

    The plan required the short circuit to be located to a line rather than
    named as a category, so every refusal site is asserted to carry a file and a
    line number, and the paragraphs behind them to be on record.
    """
    faults = []
    rows = load(T1_TABLE).get("rows") or []
    refusals = load(T1_REFUSALS) if T1_REFUSALS.is_file() else {}
    for row in rows:
        if row.get("sent_to_translator"):
            continue
        site = row.get("refused_at") or ""
        if ".py:" not in site:
            faults.append(f"{row.get('issue_id')}: {site!r} names no line")
    if not refusals:
        faults.append("no per paragraph refusal record was written")
    for did, entry in refusals.items():
        if not entry.get("refused_by") and entry.get("refused_by") != []:
            faults.append(f"{did}: no verdict list")
    record("check_01c_every_refusal_names_a_line", not faults,
           "; ".join(faults[:4]))


def check_01d_the_two_b11_1_observations_are_attributed() -> None:
    """Positive 1d: the residue count moving and the double space each have a cause."""
    faults = []
    if not T1_OBSERVATIONS.is_file():
        record("check_01d_the_two_b11_1_observations_are_attributed", False,
               f"no {T1_OBSERVATIONS}")
        return
    payload = load(T1_OBSERVATIONS)
    first = payload.get("observation_1_count_moved") or {}
    second = payload.get("observation_2_double_space") or {}
    if not first.get("finding"):
        faults.append("the count observation has no finding")
    if not first.get("excerpts_no_longer_present"):
        faults.append("the count observation names no excerpt")
    if not second.get("finding"):
        faults.append("the double space observation has no finding")
    trace = second.get("trace") or {}
    if set(trace) != {"b10_5_on", "b11_1"}:
        faults.append("the double space observation traces fewer than two runs")
    for arm, stages in trace.items():
        if not stages or any(v is None for v in stages.values()):
            faults.append(f"{arm}: a stage of the trace is missing")
    record("check_01d_the_two_b11_1_observations_are_attributed", not faults,
           "; ".join(faults[:4]))


def check_01e_the_table_pairs_nothing_by_position() -> None:
    """Negative 1e: no row was aligned by a paragraph position number.

    GAP-32: the same paragraph is p5#5 in one sidecar and p5#6 in another,
    because the position is the paragraph's index in its page at the stage that
    wrote the file. Every row therefore has to say it was aligned by an
    identifier or by text.
    """
    faults = []
    payload = load(T1_TABLE)
    if "GAP-32" not in (payload.get("alignment") or ""):
        faults.append("the table does not declare the alignment rule it followed")
    for row in payload.get("rows") or []:
        how = row.get("aligned_by") or ""
        if not (how.startswith("debug_id") or how.startswith("text")):
            faults.append(f"{row.get('issue_id')}: aligned by {how!r}")
    record("check_01e_the_table_pairs_nothing_by_position", not faults,
           "; ".join(faults[:4]))


# --- 02 T2: the probe, and the range it set ----------------------------------


def check_02a_every_sample_carries_both_counts() -> None:
    """Positive 2a: the probe answered for all six samples, twice each."""
    faults = []
    report = load(EXPOSURE)
    samples = report.get("samples") or {}
    for sample in CORPUS:
        row = samples.get(sample)
        if row is None:
            faults.append(f"{sample}: not probed")
            continue
        for key in ("identity_exposure", "hang_exposure"):
            if not isinstance(row.get(key), int):
                faults.append(f"{sample}: no {key}")
        if row.get("must_run") != bool(row.get("identity_exposure")
                                       or row.get("hang_exposure")):
            faults.append(f"{sample}: must_run disagrees with its own counts")
    if not report.get("note"):
        faults.append("the probe does not state the bound its baseline puts on it")
    record("check_02a_every_sample_carries_both_counts", not faults,
           "; ".join(faults[:4]))


def check_02b_the_range_run_is_the_range_the_probe_named() -> None:
    """Positive 2b: the samples run are exactly the samples the probe selected.

    This is what makes the range of the batch auditable rather than declared:
    the probe chose, and the ledger has to agree with it in both directions.
    """
    faults = []
    report = load(EXPOSURE)
    named = set(report.get("must_run") or ())
    zero = set(report.get("zero_exposure") or ())
    if named & zero:
        faults.append(f"a sample is in both lists: {sorted(named & zero)}")
    if named | zero != set(CORPUS):
        faults.append("the two lists do not cover the corpus")
    if not RUNS.is_file():
        record("check_02b_the_range_run_is_the_range_the_probe_named", False,
               f"no {RUNS}")
        return
    ran = {r["sample"].removesuffix(".pdf") for r in load(RUNS).get("runs") or []}
    if ran != named:
        faults.append(f"ran {sorted(ran)}, probe named {sorted(named)}")
    for sample in zero:
        if (BATCH_DIR / sample).exists():
            faults.append(f"{sample} has products and was named zero exposure")
    record("check_02b_the_range_run_is_the_range_the_probe_named", not faults,
           "; ".join(faults[:4]))


def check_02c_no_off_arm_was_produced() -> None:
    """Negative 2c: this batch's products carry one arm, and the rule is written.

    CLAUDE.md section 4.14 has to say both halves -- that an unstated plan means
    one arm, and that two arms have to be asked for by name -- or the clause
    permits the reading it was written to close.
    """
    faults = []
    for path in BATCH_DIR.rglob("*"):
        if path.is_dir() and path.name in ("off", "on"):
            faults.append(f"an arm directory exists: {path.relative_to(ROOT)}")
    text = CLAUDE.read_text(encoding="utf-8")
    clause = [line for line in text.splitlines() if line.startswith("14. ")]
    if not clause:
        faults.append("CLAUDE.md carries no clause 14")
    else:
        body = clause[0]
        if "未在 PLAN 中明写要求双臂时" not in body:
            faults.append("the clause does not cover the unstated case")
        if "点名说明理由" not in body:
            faults.append("the clause does not require two arms to be asked for")
    record("check_02c_no_off_arm_was_produced", not faults, "; ".join(faults[:4]))


# --- 03 T2's regression -------------------------------------------------------


def check_03a_the_documents_are_conserved() -> None:
    """End to end 3a: every run sample keeps the baseline's pages and paragraphs.

    Pages, paragraph counts per page, and the page ordinal references
    themselves, against the b10.5 on arm each run answers to.
    """
    faults = []
    if not RUNS.is_file():
        record("check_03a_the_documents_are_conserved", False, f"no {RUNS}")
        return
    checked = 0
    for run in load(RUNS).get("runs") or []:
        sample = run["sample"].removesuffix(".pdf")
        path = ROOT / (run.get("conservation") or "")
        if not run.get("conservation") or not path.is_file():
            faults.append(f"{sample}: no conservation record")
            continue
        record_ = load(path)
        if record_.get("baseline_pages") is None:
            faults.append(f"{sample}: the baseline could not be read")
            continue
        checked += 1
        if record_["pages"] != record_["baseline_pages"]:
            faults.append(
                f"{sample}: {record_['pages']} pages against "
                f"{record_['baseline_pages']}"
            )
        for label, page in (record_.get("per_page") or {}).items():
            if page.get("baseline_paragraphs") is None:
                continue
            if page["paragraphs"] != page["baseline_paragraphs"]:
                faults.append(
                    f"{sample} p{label}: {page['paragraphs']} paragraphs against "
                    f"{page['baseline_paragraphs']}"
                )
            if set(page.get("text") or {}) != set(page.get("baseline_text") or {}):
                faults.append(f"{sample} p{label}: the reference set moved")
    if not checked:
        faults.append("no sample was compared against its baseline")
    record("check_03a_the_documents_are_conserved", not faults,
           "; ".join(faults[:4]))


def check_03b_every_detector_rise_is_attributed() -> None:
    """End to end 3b: a finding kind rises only where the batch accounts for it.

    The plan asks for a rise to be answered with a per paragraph attribution
    rather than tolerated, so a rise is admitted here only against evidence, and
    the evidence has to be of a particular kind: every paragraph the new finding
    names must stand in exactly the box it stood in for the baseline and carry
    exactly the text it carried. That is the difference between a detector
    reading the same page differently and a page that has changed. A rise with
    no attribution row, or one whose paragraphs moved or were rewritten, fails.
    """
    faults = []
    if not RUNS.is_file():
        record("check_03b_every_detector_rise_is_attributed", False, f"no {RUNS}")
        return
    attribution = load(T2_ATTRIBUTION) if T2_ATTRIBUTION.is_file() else {"samples": {}}
    accounted = attribution.get("samples") or {}
    compared = 0
    for run in load(RUNS).get("runs") or []:
        sample = run["sample"].removesuffix(".pdf")
        now = BATCH_DIR / sample / "sidecars" / "issues.json"
        before = BASELINE_BATCH / sample / "on" / "sidecars" / "issues.json"
        if not now.is_file() or not before.is_file():
            faults.append(f"{sample}: a detection sidecar is missing")
            continue
        compared += 1
        after_counts = load(now)["counts"]["by_kind"]
        base_counts = load(before)["counts"]["by_kind"]
        for kind, count in after_counts.items():
            baseline = base_counts.get(kind, 0)
            if count <= baseline:
                continue
            row = (accounted.get(sample) or {}).get(kind)
            if row is None:
                faults.append(
                    f"{sample}: {kind} rose {baseline} to {count} with no attribution"
                )
                continue
            if row.get("now") != count or row.get("baseline") != baseline:
                faults.append(f"{sample}: the attribution for {kind} counts differently")
            new_findings = row.get("new_findings") or []
            if len(new_findings) != count - baseline:
                faults.append(f"{sample}: {kind} names {len(new_findings)} of the rise")
            for finding in new_findings:
                paragraphs = finding.get("paragraphs") or []
                if not paragraphs:
                    faults.append(f"{sample}: {finding.get('issue_id')} names no paragraph")
                for entry in paragraphs:
                    if not entry.get("box_unchanged"):
                        faults.append(
                            f"{sample} {entry.get('ref')}: the box moved, so the rise "
                            f"is a displacement rather than a reading"
                        )
                    if not entry.get("text_unchanged"):
                        faults.append(
                            f"{sample} {entry.get('ref')}: the text changed"
                        )
    if not compared:
        faults.append("no sample was compared")
    if not attribution.get("finding"):
        faults.append("the attribution states no finding")
    record("check_03b_every_detector_rise_is_attributed", not faults,
           "; ".join(faults[:4]))


def check_03c_the_heading_fitter_does_not_work_harder() -> None:
    """End to end 3c: the hang bound did not drive headings on to the floor.

    b11.1's ruling asked for this coupling to be watched beyond FD: a retreat
    costs a line, a line costs scale, and scale is what the heading fitter
    spends. Where a count does rise the run's own report has to say which
    paragraphs did it, so the rise is attributed rather than tolerated.
    """
    faults = []
    if not RUNS.is_file():
        record("check_03c_the_heading_fitter_does_not_work_harder", False,
               f"no {RUNS}")
        return
    for run in load(RUNS).get("runs") or []:
        sample = run["sample"].removesuffix(".pdf")
        now = BATCH_DIR / sample / "sidecars" / "title_typeset.report.json"
        before = (
            BASELINE_BATCH / sample / "on" / "sidecars" / "title_typeset.report.json"
        )
        if not now.is_file() or not before.is_file():
            continue
        after = load(now).get("counts") or {}
        base = load(before).get("counts") or {}
        for key in ("floor_reached", "escalations"):
            if after.get(key, 0) > base.get(key, 0):
                faults.append(
                    f"{sample}: {key} {after.get(key)} against {base.get(key)}"
                )
    record("check_03c_the_heading_fitter_does_not_work_harder", not faults,
           "; ".join(faults[:4]))


# --- 04 T3: read only, and what it measured -----------------------------------


def check_04a_the_measurement_writes_nothing_it_reads() -> None:
    """Negative 4a: running the tool leaves every product it reads byte for byte.

    Digested before and after a real run of it, over the six working
    directories, so the claim is proved rather than asserted from the tool's
    own description of itself.
    """
    import tools.column_continuity as column_continuity

    faults = []
    watched = []
    for sample in CORPUS:
        work = BASELINE_BATCH / sample / "on" / "work" / sample
        for name in (column_continuity.SOURCE_STAGE, "issues.json",
                     "translate_tracking.json"):
            path = work / name
            if path.is_file():
                watched.append(path)
    if not watched:
        record("check_04a_the_measurement_writes_nothing_it_reads", False,
               "nothing to watch")
        return

    def digests():
        return {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched
        }

    before = digests()
    with tempfile.TemporaryDirectory(prefix="b11_2_t3_") as raw:
        out = Path(raw) / "column_continuity.report.json"
        column_continuity.main(["--out", str(out)])
        if not out.is_file():
            faults.append("the tool wrote no report")
    after = digests()
    for path, digest in before.items():
        if after.get(path) != digest:
            faults.append(f"{path.relative_to(ROOT).as_posix()} changed")
    record("check_04a_the_measurement_writes_nothing_it_reads", not faults,
           "; ".join(faults[:3]))


def check_04b_every_suggested_link_carries_both_sides() -> None:
    """Positive 4b: a pair the report suggests can be judged by reading it.

    This is a measurement batch: the output is a list a person rules on, so a
    suggested pair that does not carry the text on both sides of the break is
    not a finding anybody can check.
    """
    faults = []
    report = load(T3_REPORT)
    suggested = 0
    for sample, result in (report.get("samples") or {}).items():
        for row in result.get("rows") or []:
            if not row.get("would_link"):
                continue
            suggested += 1
            for key in ("tail_text", "head_text", "tail_last_line",
                        "head_first_line"):
                if not row.get(key):
                    faults.append(f"{sample} p{row.get('page')}: no {key}")
            if not row.get("signals"):
                faults.append(f"{sample} p{row.get('page')}: no signal values")
    if not suggested:
        faults.append("the report suggests no pair at all")
    record("check_04b_every_suggested_link_carries_both_sides", not faults,
           "; ".join(faults[:4]))


def check_04c_the_known_true_positive_is_on_record() -> None:
    """Positive 4c: what happened to the pair the plan named is recorded.

    FD page 6: a noun phrase broken across two text columns. The assertion is
    that the report answers for it either way -- captured or not -- because the
    answer is the finding, and a report that simply did not mention it would
    look the same as one where it scored.
    """
    faults = []
    report = load(T3_REPORT)
    rows = [
        row for row in (report.get("samples") or {}).get("FD-en-v2", {}).get("rows", [])
        if row.get("page") == 6
    ]
    if not rows:
        faults.append("no page 6 pair is on record for FD")
    named = [
        row for row in rows
        if "fertilizer" in (row.get("tail_last_line") or "")
        or "fertilizer" in (row.get("tail_text") or "")
    ]
    if not named:
        faults.append("the pair the plan named is not in the report")
    for row in named:
        if row.get("would_link") is None and "not_scored" not in row:
            faults.append("the pair is neither scored nor marked unscored")
    unscored = [row for row in rows if "not_scored" in row]
    if not unscored:
        faults.append(
            "no page 6 pair was refused by the pairing rules, so the report "
            "cannot be showing why strict adjacency misses this handover"
        )
    if "column_position" not in (report.get("constants") or {}):
        faults.append("the constant signal is not declared as a constant")
    if report.get("constants", {}).get("opener_prior") != 0.0:
        faults.append("the opener prior was not zeroed")
    if not report.get("unweighed_signal"):
        faults.append("the hyphen signal is not declared as unweighed")
    record("check_04c_the_known_true_positive_is_on_record", not faults,
           "; ".join(faults[:4]))


def check_04d_the_chain_stage_was_not_touched() -> None:
    """Negative 4d: T3 reused the detector and did not modify it."""
    faults = []
    changed = set(changed_paths())
    for path in ("babeldoc/magazine/chain_builder.py",
                 "babeldoc/magazine/chain_signals.py",
                 "configs/chain_detection.json"):
        if path in changed:
            faults.append(f"{path} was modified")
    source = (ROOT / "tools" / "column_continuity.py").read_text(encoding="utf-8")
    if "chain_signals.page_candidates" not in source:
        faults.append("the tool does not reuse the detector's candidate walk")
    record("check_04d_the_chain_stage_was_not_touched", not faults,
           "; ".join(faults[:4]))


# --- 05 T4 --------------------------------------------------------------------


def check_05a_the_stranded_assertions_are_named_and_registered() -> None:
    """Positive 5a: the eight assertions are named, and the register says why.

    They are not recoverable: the evidence is in neither the workspace nor the
    archive, and section 4.13 forbids replacing a pruned frozen product by
    re-running the batch. So the assertion is not that they pass -- it is that
    each one is named in the gate that owns it, that the recoverability matrix
    covers it, and that GAP-31 carries the finding. A gate that quietly stopped
    reporting one of them would fail here.
    """
    faults = []
    for gate, names in STRANDED.items():
        source = (ROOT / "spec_checks" / gate).read_text(encoding="utf-8")
        for name in names:
            if f"def {name}(" not in source:
                faults.append(f"{gate}: {name} is gone")
    matrix = load(T4_MATRIX)
    covered = set(matrix.get("assertions") or {})
    expected = {f"{gate.removeprefix('spec_check_').removesuffix('.py')}/{name}"
                for gate, names in STRANDED.items() for name in names}
    missing = sorted(expected - covered)
    if missing:
        faults.append(f"the matrix does not cover {missing[:2]}")
    register = GAP_REGISTER.read_text(encoding="utf-8")
    if "GAP-31" not in register:
        faults.append("GAP-31 is not registered")
    for gate, names in STRANDED.items():
        for name in names:
            if name not in register:
                faults.append(f"GAP-31 does not name {name}")
    record("check_05a_the_stranded_assertions_are_named_and_registered",
           not faults, "; ".join(faults[:4]))


def check_05b_no_stranded_assertion_reports_a_pass() -> None:
    """Negative 5b: none of the eight is reported as passing.

    The failure this guards against is the tempting one: making a stranded
    assertion green by pointing it at something else. Each owning gate is run
    and each of the eight has to come back SKIPPED.
    """
    faults = []
    for gate, names in STRANDED.items():
        proc = subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "spec_checks" / gate)],  # noqa: S607
            cwd=ROOT, capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
            env={**__import__("os").environ, "SPEC_NO_NESTED": "1",
                 "PYTHONIOENCODING": "utf-8:replace"},
        )
        output = proc.stdout or ""
        for name in names:
            if f"SKIPPED: {name}" not in output:
                faults.append(f"{gate}: {name} is not reported SKIPPED")
    record("check_05b_no_stranded_assertion_reports_a_pass", not faults,
           "; ".join(faults[:4]))


def check_05c_a_gate_can_read_the_archive_when_the_workspace_cannot() -> None:
    """Positive 5c: the fallback is reached, on a real archive and a built one.

    Two cases. A file b10.4 produced that the retention policy took and the
    archive kept, read through the reader with nothing in the workspace; and a
    fabricated archive, so the assertion does not depend on what any particular
    batch happens to still hold.
    """
    faults = []
    real = ROOT / (
        "examples/output/b10_4/Courier-zh/work/Courier-zh/chain_report.json"
    )
    if real.exists():
        faults.append("the pruned file is back in the workspace; this proves nothing")
    else:
        if evidence.source_of(real) != "archive":
            faults.append("the reader does not resolve it to the archive")
        else:
            try:
                evidence.read_json(real)
            except Exception as exc:  # noqa: BLE001
                faults.append(f"the archived read failed: {exc}")

    with tempfile.TemporaryDirectory(prefix="b11_2_archive_") as raw:
        tmp = Path(raw)
        import zipfile

        batch = "b1"
        member = f"{batch}/made/up/thing.json"
        archive = tmp / f"{batch}.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(member, json.dumps({"built": True}))
        saved = evidence.ARCHIVE_DIR
        evidence.ARCHIVE_DIR = tmp
        try:
            target = evidence.OUTPUT_DIR / batch / "made" / "up" / "thing.json"
            if target.exists():
                faults.append("the fabricated path exists in the workspace")
            elif evidence.read_json(target) != {"built": True}:
                faults.append("the fabricated archive did not read back")
            missing = evidence.OUTPUT_DIR / batch / "made" / "up" / "absent.json"
            try:
                evidence.read_bytes(missing)
                faults.append("a wholly missing file did not raise")
            except evidence.EvidenceMissing as exc:
                if "zip" not in str(exc):
                    faults.append("the failure does not name the archive it tried")
        finally:
            evidence.ARCHIVE_DIR = saved
    record("check_05c_a_gate_can_read_the_archive_when_the_workspace_cannot",
           not faults, "; ".join(faults[:4]))


def check_05d_a_gate_declares_the_evidence_it_reads() -> None:
    """Positive 5d: this gate's declaration is honoured by the policy.

    The other half of the rule CLAUDE.md section 4.16 states. The declaration is
    read the way the policy reads it, every path in it has to exist, and a
    fabricated tree checks that a declared path inside an evicted batch is
    spared while its unregistered neighbour is taken.
    """
    faults = []
    declared_files, declared_dirs = prune_outputs.gate_evidence()
    for entry in GATE_EVIDENCE:
        path = (ROOT / entry).resolve()
        if path not in declared_files:
            faults.append(f"{entry} is not seen by the policy")
        if not (ROOT / entry).exists():
            faults.append(f"{entry} does not exist")

    config = prune_outputs.load_config()
    root = Path(tempfile.mkdtemp(prefix="b11_2_evidence_"))
    try:
        for name in ("b1", "b7_5", "b8"):
            (root / name).mkdir(parents=True)
            (root / name / f"{name}.report.md").write_text("r", encoding="utf-8")
        planted = root / "b1" / "planted.bin"
        planted.write_bytes(b"0" * 16)
        control = root / "b1" / "control.bin"
        control.write_bytes(b"0" * 16)
        saved = prune_outputs.gate_evidence
        prune_outputs.gate_evidence = lambda: ({planted.resolve()}, ())
        try:
            doomed, _ = prune_outputs.prunable(root, config)
        finally:
            prune_outputs.gate_evidence = saved
        selected = {p.name for p in doomed}
        if "planted.bin" in selected:
            faults.append("a declared path inside an evicted batch was selected")
        if "control.bin" not in selected:
            faults.append("the fabricated tree selected nothing at all")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    record("check_05d_a_gate_declares_the_evidence_it_reads", not faults,
           "; ".join(faults[:4]))


def check_05e_the_three_rules_are_written_down() -> None:
    """Positive 5e: the clauses this batch was told to add are in CLAUDE.md."""
    faults = []
    text = CLAUDE.read_text(encoding="utf-8")
    wanted = {
        "14": ("单臂默认",),
        "15": ("归档", "豁免"),
        "16": ("衍生件", "GATE_EVIDENCE", "spec_checks/evidence.py"),
    }
    for number, anchors in wanted.items():
        clause = [line for line in text.splitlines() if line.startswith(f"{number}. ")]
        body = clause[0] if clause else ""
        if not body:
            faults.append(f"CLAUDE.md carries no clause {number}")
            continue
        for anchor in anchors:
            if anchor not in body:
                faults.append(f"clause {number} does not name {anchor!r}")
    record("check_05e_the_three_rules_are_written_down", not faults,
           "; ".join(faults[:4]))


# --- 06 T5 --------------------------------------------------------------------


def check_06a_the_pinned_term_is_on_the_page() -> None:
    """End to end 6a: the ruling carries the term and FD renders it.

    The ruling is read for the term and the produced page for the ink, so the
    assertion spans the whole path rather than either end of it.
    """
    import pymupdf

    faults = []
    ruling = load(DECISIONS)
    if ruling.get("terms", {}).get(PINNED_TERM) != PINNED_TARGET:
        faults.append(f"the ruling does not pin {PINNED_TERM}")
    pdf = BATCH_DIR / "FD-en-v2" / "FD-en-v2.b11_2.pdf"
    if not pdf.is_file():
        faults.append(f"no produced document at {pdf.name}")
    else:
        with pymupdf.open(pdf) as document:
            text = document[MASTHEAD_PAGE - 1].get_text()
        if PINNED_TARGET not in text:
            faults.append(f"page {MASTHEAD_PAGE} does not render {PINNED_TARGET}")
        if PINNED_TERM in text:
            faults.append(f"page {MASTHEAD_PAGE} still renders {PINNED_TERM}")
    if not RUNS.is_file():
        faults.append("no run ledger to carry the ruling digest")
    else:
        for run in load(RUNS).get("runs") or []:
            if run["sample"].removesuffix(".pdf") != "FD-en-v2":
                continue
            if not (run.get("ruling") or {}).get("sha256"):
                faults.append("the run record carries no ruling digest")
    record("check_06a_the_pinned_term_is_on_the_page", not faults,
           "; ".join(faults[:4]))


def check_06b_the_identity_criterion_is_byte_equality() -> None:
    """Positive 6b: the criterion decides on bytes, and normalisation only records.

    Exercised on the real functions rather than read out of the source: a pair
    that differs only by compatibility composition must no longer be called
    identical, and must be the pair the recording notices.
    """
    from babeldoc.format.pdf.document_il.midend import il_translator

    class Input:
        def __init__(self, unicode):
            self.unicode = unicode

    faults = []
    cases = (
        ("F&D", "F&D", True, False),
        ("请阅读中文版!", "请阅读中文版！", False, True),
        ("F&D", " F&D ", False, True),
        ("F&D", "金融与发展", False, False),
    )
    for source, translated, identical, nfkc_only in cases:
        got = il_translator._is_identity_write_back(translated, Input(source))
        if got != identical:
            faults.append(
                f"identity({source!r}, {translated!r}) is {got}, expected {identical}"
            )
        near = il_translator._is_nfkc_only_identity(translated, Input(source))
        if near != nfkc_only:
            faults.append(
                f"nfkc only({source!r}, {translated!r}) is {near}, "
                f"expected {nfkc_only}"
            )
    source = IL_TRANSLATOR.read_text(encoding="utf-8")
    if il_translator.NFKC_ONLY_COUNT_KEY not in source:
        faults.append("the count key is not declared")
    if "_normalised_for_identity(translated_text) == _normalised_for_identity(" in \
            source.split("def _is_identity_write_back")[1].split("def ")[0]:
        faults.append("the deciding comparison still normalises")
    record("check_06b_the_identity_criterion_is_byte_equality", not faults,
           "; ".join(faults[:4]))


def check_06c_the_near_identities_are_recorded() -> None:
    """Positive 6c: the pairs the tightening changed are counted and listed."""
    faults = []
    from babeldoc.format.pdf.document_il.midend import il_translator

    seen = 0
    for run in (load(RUNS).get("runs") or []) if RUNS.is_file() else []:
        sample = run["sample"].removesuffix(".pdf")
        path = BATCH_DIR / sample / "sidecars" / il_translator.IDENTITY_REPORT_NAME
        if not path.is_file():
            continue
        seen += 1
        payload = load(path)
        count = payload.get(il_translator.NFKC_ONLY_COUNT_KEY)
        rows = payload.get("paragraphs") or []
        if count != len(rows):
            faults.append(f"{sample}: count {count} against {len(rows)} rows")
        for row in rows:
            if not row.get("source") or not row.get("translated"):
                faults.append(f"{sample}: a row carries fewer than two texts")
            if row.get("source") == row.get("translated"):
                faults.append(f"{sample}: a byte equal pair was recorded as near")
    if not seen:
        faults.append(
            "no sample wrote the record, so the tightening changed nothing "
            "anywhere and that itself is unrecorded"
        )
    record("check_06c_the_near_identities_are_recorded", not faults,
           "; ".join(faults[:4]))


def check_06d_the_short_label_is_still_one_line() -> None:
    """Negative 6d: tightening the criterion did not refold the label.

    b11.1's whole first task was to stop this label being recomposed on to two
    lines. A stricter criterion sends more paragraphs down the recomposing path,
    so the label is measured again on every page it stands on.
    """
    import pymupdf

    faults = []
    pdf = BATCH_DIR / "FD-en-v2" / "FD-en-v2.b11_2.pdf"
    if not pdf.is_file():
        record("check_06d_the_short_label_is_still_one_line", False,
               f"no produced document at {pdf.name}")
        return
    with pymupdf.open(pdf) as document:
        for label in SINGLE_LINE_PAGES:
            spans = []
            for block in document[label - 1].get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        if span["text"].strip() == SINGLE_LINE_LABEL:
                            spans.append(span)
            if not spans:
                faults.append(f"p{label}: the label is not on the page")
                continue
            for one in spans:
                for other in spans:
                    if one is other:
                        continue
                    if abs(one["bbox"][0] - other["bbox"][0]) > SAME_LEFT_EDGE:
                        continue
                    if abs(one["bbox"][1] - other["bbox"][1]) < LINE_APART:
                        continue
                    faults.append(f"p{label}: the label stands on two lines")
    record("check_06d_the_short_label_is_still_one_line", not faults,
           "; ".join(faults[:4]))


# --- 07 cost and scope --------------------------------------------------------


def check_07a_every_call_is_attributed() -> None:
    """Positive 7a: the ledger accounts for every request each run made."""
    faults = []
    if not RUNS.is_file():
        record("check_07a_every_call_is_attributed", False, f"no {RUNS}")
        return
    for run in load(RUNS).get("runs") or []:
        sample = run["sample"]
        requests = run.get("requests")
        hits = run.get("cache_hits")
        calls = run.get("api_calls")
        if None in (requests, hits, calls):
            faults.append(f"{sample}: the ledger is incomplete")
            continue
        if requests - hits != calls:
            faults.append(f"{sample}: {requests} - {hits} is not {calls}")
        if calls < 0:
            faults.append(f"{sample}: negative api calls")
    record("check_07a_every_call_is_attributed", not faults, "; ".join(faults[:4]))


def check_07b_the_delta_is_the_declared_surface() -> None:
    """Negative 7b: this batch changed nothing outside what it declared."""
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
    record("check_07b_the_delta_is_the_declared_surface", not faults,
           "; ".join(faults[:4]))


def check_07c_the_upstream_edit_is_registered() -> None:
    """Positive 7c: the one upstream file this batch touched is on the register."""
    faults = []
    register = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    if "il_translator.py" not in register:
        faults.append("il_translator.py is not registered")
    if BATCH_TAG not in register and "b11.2" not in register:
        faults.append("this batch has no row on the register")
    changed = changed_paths()
    upstream = [
        path for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    ]
    for path in upstream:
        if path != "babeldoc/format/pdf/document_il/midend/il_translator.py":
            faults.append(f"an unregistered upstream file moved: {path}")
    record("check_07c_the_upstream_edit_is_registered", not faults,
           "; ".join(faults[:4]))


def check_07d_the_gate_names_no_run_local_identifier() -> None:
    """Negative 7d: no assertion here is anchored to a minted identifier.

    CLAUDE.md section 5.13. The determination this batch made does use those
    identifiers -- inside one run that is what they are for -- but the gate must
    not, since a gate outlives the run that minted them. What is forbidden is a
    *value*, not the field name, so this reads every string literal in the file
    and refuses any that is shaped like one the paragraph finder mints: five
    characters of mixed case and digits, optionally with a line suffix.
    """
    import ast
    import re

    shape = re.compile(r"^[A-Za-z0-9]{5}(#L\d+)?$")
    source = Path(__file__).read_text(encoding="utf-8")
    faults = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value
        if not shape.match(text):
            continue
        # A word of five letters is not a minted identifier; those mix cases or
        # carry digits, which is what the finder's alphabet produces.
        if text.isalpha() and (text.islower() or text.isupper()):
            continue
        faults.append(f"line {node.lineno}: {text!r}")
    record("check_07d_the_gate_names_no_run_local_identifier", not faults,
           "; ".join(faults[:3]))


CHECKS = (
    check_00a_the_baseline_working_files_are_registered,
    check_00b_the_policy_would_not_remove_them,
    check_00c_a_gate_sweep_is_not_a_destroying_action,
    check_00d_the_acceptance_was_recorded_against_a_real_sweep,
    check_01a_every_residue_is_determined,
    check_01b_the_ninth_page_residue_is_determined_on_its_own,
    check_01c_every_refusal_names_a_line,
    check_01d_the_two_b11_1_observations_are_attributed,
    check_01e_the_table_pairs_nothing_by_position,
    check_02a_every_sample_carries_both_counts,
    check_02b_the_range_run_is_the_range_the_probe_named,
    check_02c_no_off_arm_was_produced,
    check_03a_the_documents_are_conserved,
    check_03b_every_detector_rise_is_attributed,
    check_03c_the_heading_fitter_does_not_work_harder,
    check_04a_the_measurement_writes_nothing_it_reads,
    check_04b_every_suggested_link_carries_both_sides,
    check_04c_the_known_true_positive_is_on_record,
    check_04d_the_chain_stage_was_not_touched,
    check_05a_the_stranded_assertions_are_named_and_registered,
    check_05b_no_stranded_assertion_reports_a_pass,
    check_05c_a_gate_can_read_the_archive_when_the_workspace_cannot,
    check_05d_a_gate_declares_the_evidence_it_reads,
    check_05e_the_three_rules_are_written_down,
    check_06a_the_pinned_term_is_on_the_page,
    check_06b_the_identity_criterion_is_byte_equality,
    check_06c_the_near_identities_are_recorded,
    check_06d_the_short_label_is_still_one_line,
    check_07a_every_call_is_attributed,
    check_07b_the_delta_is_the_declared_surface,
    check_07c_the_upstream_edit_is_registered,
    check_07d_the_gate_names_no_run_local_identifier,
)


def main() -> int:
    print("spec_check_b11_2: evidence preservation, residue determination, "
          "exposure probe, in-page column measurement\n")
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
