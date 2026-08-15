"""Gate script for batch E2 (the paid runs).

Run from the repository root:

    python spec_checks/spec_check_e2.py

Exit code 0 when every assertion E2 answers for passes, 1 otherwise. Needs no
API key and makes no network request: the three runs this batch paid for are
frozen artefacts by the time this runs, and every number here is recomputed from
them.

Session one, T-E2.1, is what the assertions below cover.

01 is the three runs themselves: the ledger of them names three arms, each
arm's produced PDF is where it says with the digest it says, each arm left the
checkpoints the metrics read, and the three PDFs are three different files
rather than one copied three times.

02 is the independence the whole design rests on. The two ``chain_off`` arms
must carry different cache keys and must have been served nothing, so that
neither can be a replay of the other; and they must actually disagree
somewhere, because two arms that came back identical would mean the sampling
never happened. Their batch composition must nevertheless be identical: that is
what makes them two draws of one configuration rather than two experiments.

03 is the attribution table. The rule D3 GAP-01 states is recomputed from the
three text columns for every row, so a reader can check the verdict without
trusting the tool; the reported verdict is checked to differ from it only where
the batch evidence says it must; and the whole report is regenerated into a
temporary directory and compared byte for byte, because a deterministic report
over frozen inputs is the only kind that can be checked years later.

04 is the chain A/B at metric level: six runs, conservation holding in all of
them, and the `7->8` boundary answered the same way by every one -- which is the
zero discriminative power the ledger now claims and the contract now records.

05 is the paperwork the numbers live in: the ledger no longer holds the "needs
three runs" status, the rows this session added are there, and the gap register
closes over them.

06 and 07 are scope and registration. 08 is the negative twin: the analysis tool
cannot reach a model or a credential, and only the runners may.

Session two, T-E2.2, is 10 through 13.

10 is the splice judge's answer contract, checked over the whole table rather
than sampled: every category, severity and window name is one the configuration
declares, every row carries the judge and the transport it was answered under,
and a refusal, if there is one, is recorded as a refusal rather than dropped.

11 is the test point set: it is the corpus adjudication's positives, recomputed
here from the ground truth, and the seam the paper argues from carries the three
arms the plan asked for plus the robustness arm.

12 is the replay: the judgement table is regenerated with no transport at all
and compared byte for byte, which is only possible if every reply is cached and
no provenance leaked into it.

13 and 14 are the ruling. The manual review draft came back answered, so 13
asserts that every judged row was put to a human and answered, and 14 recomputes
the headline from the answers: the rows whose windows do not target the
adjudicated splice are marked and set aside, the agreement is counted over what
is left, and the documents quoting the number have to quote that one.
"""

from __future__ import annotations

import contextlib
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

from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Every session of batch E2, in order. The scope assertion reads the union of
# the deltas the tags that exist introduced, plus the working tree while the
# last of them is still uncut.
BATCH_TAGS = ("batch-e2.1", "batch-e2.2", "batch-e2.3")

PYTHON = sys.executable

RESULTS = ROOT / "docs" / "eval" / "results_e2"
ATTRIBUTION = RESULTS / "drift_attribution.json"
METRICS = RESULTS / "eval_report.Courier-en.json"
RESULTS_README = RESULTS / "README.md"
JUDGEMENTS = RESULTS / "splice_judgements.json"
MANUAL_REVIEW = RESULTS / "splice_manual_review.json"
PROTOCOL = ROOT / "docs" / "eval" / "splice_protocol.md"
JUDGE_CONFIG = ROOT / "configs" / "splice_judge.json"
JUDGE_PROMPT = ROOT / "prompts" / "splice_judge_mqm.md"

RUN_DIR = ROOT / "examples" / "output" / "e2" / "r1"
RUNNER = ROOT / "tools" / "run_drift_trio.py"
ANALYSIS = ROOT / "tools" / "drift_attribution.py"
JUDGE = ROOT / "tools" / "splice_judge.py"

# The ground truth the test point set is derived from, read here so the gate
# recomputes the set rather than trusting the report's own count.
CHAIN_LABELS = ROOT / "corpus" / "chain_labels.user.json"

# The arms the plan asks the seam to be measured on: the three-way, plus the
# second off draw as the robustness arm.
SEAM_ARMS = ("upstream", "chain_off_1", "chain_off_2", "chain_on")

# Human fields a review draft carries. This batch exports them empty: the
# corpus owner fills them, and a machine session that filled one would be
# writing the ruling it is supposed to be checked by.
HUMAN_FIELDS = ("human_agrees", "human_errors", "human_note")

# How the ruling marks a row whose windows do not target the adjudicated
# splice. Such a row tests nothing and is kept out of the agreement count.
PROTOCOL_INVALID = "PROTOCOL-INVALID"

LEDGER = ROOT / "docs" / "eval" / "evidence_ledger.md"
GAPS = ROOT / "docs" / "eval" / "gap_register.md"
CONTRACT = ROOT / "docs" / "eval" / "metric_contract.md"

REFERENCE_ARM = "chain_off_1"
CONTROL_ARM = "chain_off_2"
TREATMENT_ARM = "chain_on"
ARMS = (TREATMENT_ARM, REFERENCE_ARM, CONTROL_ARM)
OFF_ARMS = (REFERENCE_ARM, CONTROL_ARM)

# The checkpoints tools/eval_report.py reads out of a working directory. An arm
# missing any of them has no metrics, whatever else it produced.
REQUIRED_CHECKPOINTS = (
    "checkpoint.08_chain_builder.xml",
    "checkpoint.09_il_translated.xml",
    "checkpoint.11_typesetting.xml",
)

# The adjudicated boundary the double-evidence table is about.
SEAM = "7->8"

# Paths this batch may change: the evaluation documents and their results, the
# tools that produced them, the bounded configuration, the plan and this gate.
# Ground truth and the extension package are not here, and neither is upstream.
ALLOWED_PREFIXES = (
    "configs/",
    "docs/eval/",
    "plans/",
    "spec_checks/",
    "tools/",
)
ALLOWED_FILES = {
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "prompts/splice_judge_mqm.md",
    # Outside the whitelist PLAN_E2 declares; see W-E2-03. The two conventions
    # this batch discovered belong in the file every session reads first.
    "CLAUDE.md",
}

# Prefixes no session of this batch may touch: the corpus rulings are the user's
# and read-only to a machine session, and no upstream file is in scope at all.
FORBIDDEN_PREFIXES = ("corpus/", "reviews/", "babeldoc/")

# A backticked token is treated as a repository path when it starts with one of
# these, which is what keeps a relative reference like `results_e1/README.md`
# out of the existence check.
TOP_LEVEL = (
    "babeldoc/",
    "configs/",
    "corpus/",
    "docs/",
    "examples/",
    "plans/",
    "prompts/",
    "reviews/",
    "spec_checks/",
    "tools/",
)

BACKTICKED = re.compile(r"`([^`\n]+)`")
FENCED = re.compile(r"```.*?```", re.S)

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Assertions that read a produced artefact rather than one built here, or that
# re-run a tool over one. Skipped by the fast tier during iteration.
PIPELINE_TIER = (
    "check_01b_each_arm_left_the_checkpoints_the_metrics_read",
    "check_03c_the_report_regenerates_byte_for_byte",
    "check_12_the_judgements_replay_from_cache_byte_for_byte",
)

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_e2")


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
    """This batch's delta: the tags that exist, plus the tree while one is not cut."""
    paths: set[str] = set()
    uncut = False
    for tag in BATCH_TAGS:
        code, _ = git_output(["rev-parse", "--verify", f"{tag}^{{commit}}"])
        if code != 0:
            uncut = True
            continue
        _, listing = git_output(["diff", "--name-only", f"{tag}^..{tag}"])
        paths |= {line.strip() for line in listing.splitlines() if line.strip()}
    if not uncut:
        return paths
    for args in (["diff", "--name-only", "HEAD"], ["diff", "--name-only", "--cached"]):
        _, listing = git_output(args)
        paths |= {line.strip() for line in listing.splitlines() if line.strip()}
    _, untracked = git_output(["status", "--porcelain", "--untracked-files=all"])
    for line in untracked.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def digest_of(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def runs_by_arm() -> dict[str, dict]:
    report = read_json(ATTRIBUTION)
    return {run["arm"]: run for run in report.get("runs", ())}


# --- 01 the three runs ---------------------------------------------------------


def check_01a_three_runs_with_registered_digests() -> None:
    """Positive 1a: three arms, each PDF where it says with the digest it says.

    The produced PDFs are too large to track, so what is tracked is the digest
    and what this asserts is that the digest still names a file on disk. That is
    the same arrangement `spec_check_e0.py` uses for the baseline PDFs.
    """
    faults = []
    if not ATTRIBUTION.is_file():
        record("check_01a_three_runs_with_registered_digests", False, "no report")
        return
    ledger = runs_by_arm()
    missing = [arm for arm in ARMS if arm not in ledger]
    if missing:
        faults.append(f"arms absent from the run ledger: {missing}")
    for arm in ARMS:
        run = ledger.get(arm)
        if run is None:
            continue
        name = run.get("mono_pdf")
        declared = run.get("mono_pdf_sha256")
        if not name or not declared:
            faults.append(f"{arm}: no produced PDF registered")
            continue
        path = RUN_DIR / name
        if not path.is_file():
            faults.append(f"{arm}: {path} is absent")
            continue
        actual = digest_of(path)
        if actual != declared:
            faults.append(f"{arm}: {name} digest {actual[:12]} != {declared[:12]}")
    digests = {
        arm: ledger[arm].get("mono_pdf_sha256") for arm in ARMS if arm in ledger
    }
    if len(set(digests.values())) != len(digests):
        faults.append(f"two arms produced the same PDF: {digests}")
    record(
        "check_01a_three_runs_with_registered_digests", not faults, "; ".join(faults[:5])
    )


def check_01b_each_arm_left_the_checkpoints_the_metrics_read() -> None:
    """Positive 1b: every arm's working directory carries what a metric reads."""
    faults = []
    ledger = runs_by_arm()
    for arm in ARMS:
        run = ledger.get(arm)
        if run is None:
            faults.append(f"{arm}: no run record")
            continue
        working = ROOT / run["working_dir"]
        for name in REQUIRED_CHECKPOINTS:
            if not (working / name).is_file():
                faults.append(f"{arm}: {name} is absent")
        if not (RUN_DIR / arm / "prompt_trace.json").is_file():
            faults.append(f"{arm}: prompt trace is absent")
    record(
        "check_01b_each_arm_left_the_checkpoints_the_metrics_read",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 02 independence -----------------------------------------------------------


def check_02a_the_two_off_arms_carry_different_cache_keys() -> None:
    """Positive 2a: neither off arm could have been served the other's answers.

    Three things together say that. The keys differ, so the two arms file into
    different namespaces; both report zero cache hits, so neither was served
    anything at all; and both spent, so both actually asked.
    """
    faults = []
    ledger = runs_by_arm()
    keys = {arm: ledger.get(arm, {}).get("cache_key_sha256") for arm in ARMS}
    if None in keys.values():
        faults.append(f"a run record carries no cache key: {keys}")
    elif len(set(keys.values())) != len(keys):
        faults.append(f"two arms share a cache key: {keys}")
    for arm in OFF_ARMS:
        run = ledger.get(arm, {})
        if run.get("cache_namespace") is None:
            faults.append(f"{arm}: declares no cache namespace")
        if run.get("cache_hits") != 0:
            faults.append(f"{arm}: {run.get('cache_hits')} cache hit(s), not a fresh draw")
        if not run.get("api_calls"):
            faults.append(f"{arm}: no API call, so nothing was sampled")
    if ledger.get(TREATMENT_ARM, {}).get("cache_namespace") is not None:
        faults.append(f"{TREATMENT_ARM}: declares a namespace and cannot replay the frozen one")
    record(
        "check_02a_the_two_off_arms_carry_different_cache_keys",
        not faults,
        "; ".join(faults[:5]),
    )


def check_02b_the_off_arms_differ_in_text_and_agree_in_batching() -> None:
    """Positive 2b: two draws of one configuration, and they are two.

    Identical answers would mean one arm replayed the other; different batches
    would mean they were not one configuration. Both halves have to hold.
    """
    report = read_json(ATTRIBUTION)
    premises = report["premises"]
    result = report["attribution"]
    faults = []
    if not premises.get("documents_identical_before_translation"):
        faults.append(f"the arms translated different documents: {premises.get('faults')}")
    if not premises.get("off_arm_batches_identical"):
        faults.append(f"the off arms asked about different batches: {premises.get('off_arm_batch_faults')}")
    if not result.get("noise_population"):
        faults.append("the two off arms agree everywhere, which is a cache replay")
    differing = [row for row in result["rows"] if not row["off1_equals_off2"]]
    if not differing:
        faults.append("no changed row differs between the off arms")
    record(
        "check_02b_the_off_arms_differ_in_text_and_agree_in_batching",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 03 the attribution table --------------------------------------------------


def check_03a_the_gap01_rule_recomputes_from_the_three_columns() -> None:
    """Positive 3a: every verdict D3 GAP-01 states is recomputable by a reader.

    This is the assertion that makes the table evidence rather than an opinion:
    the rule takes the three text columns and the chain membership and nothing
    else, so it is recomputed here from the report's own cells.
    """
    result = read_json(ATTRIBUTION)["attribution"]
    faults = []
    counts: dict[str, int] = {}
    for row in result["rows"]:
        if row["chain_member"]:
            expected = "chain_member"
        elif row["off1"] != row["off2"]:
            expected = "sampling_noise"
        else:
            expected = "rebatch_effect"
        if row["gap01_verdict"] != expected:
            faults.append(f"{row['reference']}: {row['gap01_verdict']} != {expected}")
        counts[expected] = counts.get(expected, 0) + 1
        if row["off1"] == row["on"]:
            faults.append(f"{row['reference']}: is in the changed set and did not change")
    if counts != result["gap01_verdict_counts"]:
        faults.append(f"counts {result['gap01_verdict_counts']} != recomputed {counts}")
    record(
        "check_03a_the_gap01_rule_recomputes_from_the_three_columns",
        not faults,
        "; ".join(faults[:5]),
    )


def check_03b_the_batch_evidence_only_moves_the_rows_it_may() -> None:
    """Positive 3b: the reported verdict differs from the stated rule only where the batch did not move.

    The batch column is the second discriminator, and it is allowed to overturn
    exactly one branch: a row the two off draws agree about, whose batch stayed
    put, is a third draw rather than a recomposition. Everywhere else the two
    verdicts have to be the same word.
    """
    result = read_json(ATTRIBUTION)["attribution"]
    faults = []
    a12 = [row for row in result["rows"] if row["batch_moved"]]
    for row in result["rows"]:
        if row["gap01_verdict"] == "rebatch_effect" and not row["batch_moved"]:
            if row["verdict"] != "run_variance":
                faults.append(f"{row['reference']}: unmoved batch kept {row['verdict']}")
        elif row["verdict"] != row["gap01_verdict"]:
            faults.append(
                f"{row['reference']}: {row['verdict']} != {row['gap01_verdict']} "
                "with no batch evidence to justify it"
            )
    listed = [row["reference"] for row in a12]
    if listed != result["changed_and_recomposed"]:
        faults.append("the A-12 set does not match the rows whose batch moved")
    recomputed: dict[str, int] = {}
    for row in a12:
        recomputed[row["verdict"]] = recomputed.get(row["verdict"], 0) + 1
    if recomputed != result["changed_and_recomposed_verdicts"]:
        faults.append(
            f"A-12 set verdicts {result['changed_and_recomposed_verdicts']} "
            f"!= recomputed {recomputed}"
        )
    members = sum(1 for row in a12 if row["chain_member"])
    if members != 4:
        faults.append(f"{members} chain members in the A-12 set, expected the 4 the corpus has")
    record(
        "check_03b_the_batch_evidence_only_moves_the_rows_it_may",
        not faults,
        "; ".join(faults[:5]),
    )


def check_03c_the_report_regenerates_byte_for_byte() -> None:
    """Positive 3c: the attribution is a pure function of the frozen runs."""
    with tempfile.TemporaryDirectory(prefix="spec_e2_") as tmp:
        proc = subprocess.run(  # noqa: S603
            [PYTHON, str(ANALYSIS), "--out", tmp],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            record(
                "check_03c_the_report_regenerates_byte_for_byte",
                False,
                (proc.stderr or proc.stdout)[-800:],
            )
            return
        again = Path(tmp) / ATTRIBUTION.name
        same = again.read_bytes() == ATTRIBUTION.read_bytes()
    record(
        "check_03c_the_report_regenerates_byte_for_byte",
        same,
        "a second run produced different bytes",
    )


# --- 04 the chain A/B at metric level ------------------------------------------


def check_04_the_chain_ab_is_measured_on_every_arm() -> None:
    """Positive 4: six runs, conservation holding, and one verdict at the seam.

    The seam is the adjudicated mid-sentence split. Every arm answering it the
    same way is the finding, not a defect of this gate: it is the zero
    discriminative power the contract records, and it is asserted so that a
    later change to the metric that broke it would be noticed here.
    """
    faults = []
    if not METRICS.is_file():
        record("check_04_the_chain_ab_is_measured_on_every_arm", False, "no metrics report")
        return
    report = read_json(METRICS)
    runs = {run["label"]: run for run in report["runs"]}
    expected = [arm for arm in ARMS] + [f"{arm}_pdf" for arm in ARMS]
    missing = [label for label in expected if label not in runs]
    if missing:
        faults.append(f"arms not measured: {missing}")
    verdicts = {}
    for label, run in runs.items():
        if not run["conservation"]["holds"]:
            faults.append(f"{label}: conservation does not hold")
        series = ((run.get("mid_break_rate") or {}).get("series") or {}).get("page") or {}
        seam = [item for item in series.get("boundaries", ()) if item["label"] == SEAM]
        if not seam:
            faults.append(f"{label}: the {SEAM} boundary is absent")
            continue
        if seam[0]["truth_category"] != "linked":
            faults.append(f"{label}: {SEAM} is not read as an adjudicated link")
        verdicts[label] = seam[0]["verdict"]
    if len(set(verdicts.values())) != 1:
        faults.append(f"the arms disagree at {SEAM}: {verdicts}")
    record(
        "check_04_the_chain_ab_is_measured_on_every_arm", not faults, "; ".join(faults[:5])
    )


# --- 05 the paperwork ----------------------------------------------------------


def _classified_ledger_rows() -> tuple[dict[str, str], str]:
    """Every ledger row's status, and which status word means "citable".

    The status words are the ledger's own declaration and are not spelled here:
    a gate that hard-coded them would be asserting its own copy of the
    vocabulary rather than the document's. The citable one is identified the way
    `spec_check_e0.py` identifies it, as the status most rows carry.
    """
    document = LEDGER.read_text(encoding="utf-8")
    marker = re.search(r"<!--\s*status-vocabulary:(.*?)-->", document, re.S)
    statuses = BACKTICKED.findall(marker.group(1)) if marker else []
    classified: dict[str, str] = {}
    tally = dict.fromkeys(statuses, 0)
    for match in re.finditer(r"^\| ([A-G]-\d+) \|(.*)$", document, re.M):
        cell = match.group(2).strip().strip("|").split("|")[-1]
        found = min(
            ((cell.index(term), term) for term in statuses if term in cell),
            default=None,
        )
        if found is None:
            continue
        classified[match.group(1)] = found[1]
        tally[found[1]] += 1
    citable = max(tally, key=lambda term: tally[term]) if tally else ""
    return classified, citable


def check_05a_the_ledger_no_longer_needs_three_runs() -> None:
    """Positive 5a: the status this batch exists to retire is retired.

    A-12 is the row D3 GAP-01 held open, so its status now being the citable one
    is the whole delivery of session one stated in the ledger's own terms; and
    the status word it used to carry may not be left on any row, because this
    batch is the run matrix that answers it.
    """
    classified, citable = _classified_ledger_rows()
    faults = []
    if not citable:
        faults.append("the ledger declares no status vocabulary")
    for identifier in ("A-18", "A-19", "A-20", "A-21", "G-09"):
        if identifier not in classified:
            faults.append(f"the ledger has no row {identifier}")
        elif classified[identifier] != citable:
            faults.append(f"{identifier} is not citable")
    if classified.get("A-12") != citable:
        faults.append("A-12 is still not citable, which is what R1 was run for")
    for identifier in ("A-22", "A-23", "A-24", "C-06"):
        if identifier not in classified:
            faults.append(f"the ledger has no row {identifier}")
        elif classified[identifier] != citable:
            faults.append(f"{identifier} is not citable")
    # Session two closes the last three open rows: A-09 and E-12 by restatement,
    # E-09 by the synthetic coverage declaration. No row of this ledger may
    # carry any other status now, and this is the assertion that says so.
    open_rows = {
        identifier: status
        for identifier, status in classified.items()
        if status != citable
    }
    if open_rows:
        faults.append(f"a row is still open: {open_rows}")
    record(
        "check_05a_the_ledger_no_longer_needs_three_runs", not faults, "; ".join(faults[:5])
    )


def check_05b_the_gap_register_closes_over_the_new_rows() -> None:
    """Positive 5b: GAP-01 is answered and the row it downgraded is answered too."""
    gaps = GAPS.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    faults = []
    if "GAP-01" not in gaps:
        faults.append("GAP-01 is gone from the register")
    for identifier in ("A-18", "A-19", "A-21"):
        if identifier not in gaps:
            faults.append(f"the register does not cite {identifier}")
    if "A-09" not in gaps:
        faults.append("A-09 is restated in the ledger and unanswered in the register")
    if "results_e2" not in contract:
        faults.append("the metric contract does not record this batch's A/B")
    # Session two: every gap whose answer this batch is has to say so, and the
    # contract has to carry the protocol the judge ran under.
    for identifier in ("GAP-03", "GAP-04", "GAP-06", "GAP-10", "GAP-13"):
        if identifier not in gaps:
            faults.append(f"{identifier} is gone from the register")
    for identifier in ("A-22", "C-06"):
        if identifier not in gaps:
            faults.append(f"the register does not cite {identifier}")
    if "splice_protocol.md" not in contract:
        faults.append("the metric contract does not name the M10 protocol")
    record(
        "check_05b_the_gap_register_closes_over_the_new_rows",
        not faults,
        "; ".join(faults[:5]),
    )


def check_05c_every_path_this_batch_cites_exists() -> None:
    """Negative 5c: no dead link in what this session wrote."""
    faults = []
    for document in (RESULTS_README, RESULTS / "drift_attribution.md", PROTOCOL):
        if not document.is_file():
            faults.append(f"{document.name} is absent")
            continue
        body = FENCED.sub("", document.read_text(encoding="utf-8"))
        for token in BACKTICKED.findall(body):
            token = token.strip()
            if not token.startswith(TOP_LEVEL) or " " in token:
                continue
            if not (ROOT / token).exists():
                faults.append(f"{document.name}: {token} does not exist")
    record(
        "check_05c_every_path_this_batch_cites_exists", not faults, "; ".join(faults[:5])
    )


# --- 06 and 07 scope and registration ------------------------------------------


def check_06_no_upstream_and_no_ground_truth_change() -> None:
    """Negative 6: the batch delta stays inside the declared paths."""
    changed = changed_paths()
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    faults = []
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    for prefix in FORBIDDEN_PREFIXES:
        touched = sorted(path for path in changed if path.startswith(prefix))
        if touched:
            faults.append(f"{prefix} changed: {touched}")
    record("check_06_no_upstream_and_no_ground_truth_change", not faults, "; ".join(faults))


def check_07_the_runner_registers_this_gate() -> None:
    """Positive 7: the sweep runs this gate, after the batch it builds on."""
    source = (ROOT / "spec_checks" / "run_all.py").read_text(encoding="utf-8")
    listed = re.findall(r'"(spec_check_[a-z0-9_]+\.py)"', source)
    name = Path(__file__).name
    faults = []
    if name not in listed:
        faults.append("run_all.py does not list this gate")
    elif "spec_check_e1.py" in listed and listed.index(name) < listed.index(
        "spec_check_e1.py"
    ):
        faults.append("this gate runs before the batch it reads the results of")
    record("check_07_the_runner_registers_this_gate", not faults, "; ".join(faults))


# --- 08 the negative twin ------------------------------------------------------


def check_08a_only_the_runner_may_spend() -> None:
    """Negative 8a: the analysis tool reaches no model and no credential.

    Two files in this batch are allowed to hold a key: the one that made the
    three runs and the one that asked the judge. Everything that turns those
    runs into numbers has to be re-runnable by someone with no account -- and
    the judge tool has to be able to do that too, which is what its offline
    switch is asserted for in 12.
    """
    faults = []
    forbidden = ("openai", "OPENAI_API_KEY", "api_key", "httpx", "os.environ")
    body = ANALYSIS.read_text(encoding="utf-8")
    for token in forbidden:
        if token in body:
            faults.append(f"{ANALYSIS.name} names {token}")
    if "OPENAI_API_KEY" not in RUNNER.read_text(encoding="utf-8"):
        faults.append(f"{RUNNER.name} does not read a credential, so it cannot have run")
    # The judge tool names no variable of its own: it reads the one its
    # configuration declares, which is why the literal is absent here and the
    # two tokens below are what say it reaches a credential at all.
    judge_body = JUDGE.read_text(encoding="utf-8")
    for token in ("os.environ", "api_key_env"):
        if token not in judge_body:
            faults.append(f"{JUDGE.name} does not name {token}, so it cannot have run")
    # The credential is read from the environment, never from a setting: the
    # configuration names the variable and holds no value.
    config = read_json(JUDGE_CONFIG)
    if config.get("api_key_env") != "OPENAI_API_KEY":
        faults.append("the judge configuration does not name the credential variable")
    for key, value in config.items():
        if isinstance(value, str) and value.startswith("sk-"):
            faults.append(f"the judge configuration holds a credential under {key}")
    record("check_08a_only_the_runner_may_spend", not faults, "; ".join(faults[:5]))


def check_08b_ascii_prose() -> None:
    """Negative 8b: every file this batch adds under tools/ and here is ASCII."""
    faults = []
    for path in (RUNNER, ANALYSIS, JUDGE, Path(__file__)):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.isascii():
                offenders = [
                    unicodedata.name(char, hex(ord(char)))
                    for char in line
                    if not char.isascii()
                ]
                faults.append(f"{path.name}:{number} {offenders[:2]}")
    record("check_08b_ascii_prose", not faults, "; ".join(faults[:5]))


# --- 10 to 13 the splice judge -------------------------------------------------


def check_10_every_judgement_answers_within_the_declared_vocabularies() -> None:
    """Positive 10: the whole annotation table, not a sample of it.

    An annotation is only evidence if the words in it mean what the protocol
    says they mean, so every category, severity and window name is checked
    against the configuration's own lists -- read from the file rather than
    restated here, because a gate holding its own copy of a vocabulary would be
    asserting the copy. Each row also has to name the judge and the transport it
    was answered under: a number whose provenance is not on its own row cannot
    be quoted years later.
    """
    faults = []
    if not JUDGEMENTS.is_file():
        record(
            "check_10_every_judgement_answers_within_the_declared_vocabularies",
            False,
            "no judgement table",
        )
        return
    config = read_json(JUDGE_CONFIG)
    categories = set(config["mqm_categories"])
    severities = set(config["mqm_severities"])
    report = read_json(JUDGEMENTS)
    rows = report["rows"]
    if not rows:
        faults.append("the table is empty")
    prompt_digest = digest_of(JUDGE_PROMPT)
    tally: dict[str, int] = {}
    for row in rows:
        where = f"{row.get('point')} [{row.get('arm')}]"
        if row.get("judge_model") != config["model"]:
            faults.append(f"{where}: judged by {row.get('judge_model')}")
        transport = row.get("judge_transport") or {}
        for name in ("token_parameter", "temperature", "max_output_tokens"):
            if transport.get(name) != config.get(name):
                faults.append(f"{where}: {name} {transport.get(name)!r} is not the configured one")
        if row.get("prompt_file_sha256") != prompt_digest:
            faults.append(f"{where}: was asked with another prompt file")
        if row.get("status") not in ("annotated", "judge_refused"):
            faults.append(f"{where}: status {row.get('status')!r}")
        if row.get("status") == "judge_refused":
            if not row.get("refusal_reason"):
                faults.append(f"{where}: refused with no reason recorded")
            continue
        if not (row.get("reading") or "").strip():
            faults.append(f"{where}: annotated with no reading")
        for error in row.get("errors", ()):
            if error.get("category") not in categories:
                faults.append(f"{where}: category {error.get('category')!r} is undeclared")
            if error.get("severity") not in severities:
                faults.append(f"{where}: severity {error.get('severity')!r} is undeclared")
            if error.get("window") not in ("source", "tail", "head"):
                faults.append(f"{where}: window {error.get('window')!r} is undeclared")
            if not (error.get("span") or "").strip():
                faults.append(f"{where}: an error carries no span")
            if len(row["errors"]) > config["max_errors"]:
                faults.append(f"{where}: more errors than the configuration allows")
            name = f"{error.get('category')}/{error.get('severity')}"
            tally[name] = tally.get(name, 0) + 1
    if tally != report.get("error_tally"):
        faults.append(f"the tally {report.get('error_tally')} != recomputed {tally}")
    record(
        "check_10_every_judgement_answers_within_the_declared_vocabularies",
        not faults,
        "; ".join(faults[:5]),
    )


def check_11_the_test_points_are_the_adjudicated_positives() -> None:
    """Positive 11: the point set is the ground truth's, and the seam has its arms.

    The set is recomputed from `corpus/chain_labels.user.json` here, so a point
    silently dropped from the run would show up as a missing row rather than as
    a smaller table nobody counted. The seam is the boundary the paper argues
    from and is the one place the plan names the arms of.
    """
    faults = []
    labels = read_json(CHAIN_LABELS)
    expected = set()
    for sample, entry in labels.items():
        if not isinstance(entry, dict):
            continue
        for boundary, ruling in entry.items():
            if isinstance(ruling, dict) and ruling.get("link"):
                expected.add(f"{Path(sample).stem} {boundary}")
    report = read_json(JUDGEMENTS)
    measured = {row["point"] for row in report["rows"]}
    missing = sorted(expected - measured)
    stray = sorted(measured - expected)
    if missing:
        faults.append(f"adjudicated positives not judged: {missing}")
    if stray:
        faults.append(f"judged points the ground truth does not call linked: {stray}")
    seam_point = None
    for point in measured:
        if point.endswith(f" {SEAM}") and point.startswith("Courier-en"):
            seam_point = point
    if seam_point is None:
        faults.append(f"the {SEAM} seam is absent")
    else:
        arms = {row["arm"] for row in report["rows"] if row["point"] == seam_point}
        absent = sorted(set(SEAM_ARMS) - arms)
        if absent:
            faults.append(f"the seam is missing arms {absent}")
    if not PROTOCOL.is_file():
        faults.append("the protocol document is absent")
    record(
        "check_11_the_test_points_are_the_adjudicated_positives",
        not faults,
        "; ".join(faults[:5]),
    )


def check_12_the_judgements_replay_from_cache_byte_for_byte() -> None:
    """Positive 12: the paid run is the run a reader can regenerate.

    With ``--offline`` the tool builds no transport at all, so a point that is
    not cached stops the run. Passing therefore says two things at once: every
    reply is in the project database, and no cache provenance leaked into the
    table -- an ``attempts`` column would have made these two runs differ.
    """
    with tempfile.TemporaryDirectory(prefix="spec_e2_judge_") as tmp:
        proc = subprocess.run(  # noqa: S603
            [
                PYTHON,
                str(JUDGE),
                "--out",
                tmp,
                "--offline",
                "--cost-out",
                str(Path(tmp) / "judge_cost.json"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            record(
                "check_12_the_judgements_replay_from_cache_byte_for_byte",
                False,
                (proc.stderr or proc.stdout)[-800:],
            )
            return
        faults = []
        again = Path(tmp) / JUDGEMENTS.name
        if not again.is_file():
            faults.append(f"{JUDGEMENTS.name} was not regenerated")
        elif again.read_bytes() != JUDGEMENTS.read_bytes():
            faults.append(f"{JUDGEMENTS.name} regenerated with different bytes")
        # The review draft is compared by its rows rather than its bytes: once
        # answered it is a ruling, and 13 asserts that a run leaves it alone.
        draft = Path(tmp) / MANUAL_REVIEW.name
        if draft.is_file():
            drafted = {item["id"] for item in read_json(draft).get("items", ())}
            ruled = {item["id"] for item in read_json(MANUAL_REVIEW).get("items", ())}
            if drafted != ruled:
                faults.append("the ruling covers different rows than a fresh draft")
        cost = read_json(Path(tmp) / "judge_cost.json")
        if cost.get("transport_requests"):
            faults.append(f"the replay spent {cost['transport_requests']} request(s)")
    record(
        "check_12_the_judgements_replay_from_cache_byte_for_byte",
        not faults,
        "; ".join(faults[:5]),
    )


def check_13_the_manual_review_is_ruled_and_covers_every_row() -> None:
    """Positive 13: the human's list exists, is answered, and answers everything.

    This assertion was the other way round when the draft was exported: it
    asserted the human fields were empty, because a machine session that filled
    one would be writing the ruling it is meant to be checked by. The ruling is
    in, so what it asserts now is that every judged row was answered, that no
    answer names a row nobody judged, and that the machine has not since
    overwritten it -- a run of the tool leaves a ruled draft alone, and a
    regenerated blank in its place would show up here as an unanswered row.
    """
    faults = []
    if not MANUAL_REVIEW.is_file():
        record(
            "check_13_the_manual_review_is_ruled_and_covers_every_row",
            False,
            "no review draft",
        )
        return
    review = read_json(MANUAL_REVIEW)
    items = review.get("items") or []
    if len(items) < 5:
        faults.append(f"{len(items)} review items, fewer than the five GAP-03 asks for")
    judged = {f"{row['point']} [{row['arm']}]" for row in read_json(JUDGEMENTS)["rows"]}
    listed = {item.get("id") for item in items}
    for missing in sorted(judged - listed):
        faults.append(f"judged row not put to a human: {missing}")
    for stray in sorted(listed - judged):
        faults.append(f"review item that is not a judged row: {stray}")
    for item in items:
        if item.get("human_agrees") not in (True, False):
            faults.append(f"{item.get('id')}: human_agrees is unanswered")
        if not (item.get("human_note") or "").strip():
            faults.append(f"{item.get('id')}: human_note is unanswered")
        if item.get("human_agrees") is False and not item.get("human_errors"):
            faults.append(f"{item.get('id')}: disagrees without giving an annotation")
        for field in ("source_window", "tail_window", "head_window"):
            if not (item.get(field) or "").strip():
                faults.append(f"{item.get('id')}: {field} is empty")
    record(
        "check_13_the_manual_review_is_ruled_and_covers_every_row",
        not faults,
        "; ".join(faults[:5]),
    )


def check_14_the_agreement_is_recomputed_from_the_ruling() -> None:
    """Positive 14: the headline agreement is the ruling's own arithmetic.

    The ruling splits its rows in two. A row whose windows do not target the
    adjudicated splice cannot test anything and is marked with the declared
    marker; what is left is the valid set, and the agreement is counted over
    that set alone. Both are recomputed here from the file, and the documents
    that quote the number have to quote the one that comes out -- a denominator
    that quietly included the invalid rows would show up as a mismatch here
    rather than as a footnote nobody checked.
    """
    faults = []
    review = read_json(MANUAL_REVIEW)
    items = review.get("items") or []
    invalid = [
        item
        for item in items
        if (item.get("human_note") or "").strip().startswith(PROTOCOL_INVALID)
    ]
    valid = [item for item in items if item not in invalid]
    agree = [item for item in valid if item.get("human_agrees") is True]
    if not valid:
        faults.append("every row is protocol invalid, so nothing was tested")
    if not invalid:
        faults.append(f"no row carries {PROTOCOL_INVALID}, which the ruling records")
    headline = f"{len(agree)}/{len(valid)}"
    for document in (LEDGER, RESULTS_README, PROTOCOL):
        body = document.read_text(encoding="utf-8")
        if headline not in body:
            faults.append(f"{document.name} does not quote the agreement {headline}")
        if PROTOCOL_INVALID not in body:
            faults.append(f"{document.name} does not name the {PROTOCOL_INVALID} rule")
    # An invalid row is invalid for every arm of its point: the window selection
    # is a property of the boundary, not of the run that was measured at it.
    by_point: dict[str, set[bool]] = {}
    for item in items:
        by_point.setdefault(item["point"], set()).add(item in invalid)
    split = sorted(point for point, kinds in by_point.items() if len(kinds) > 1)
    if split:
        faults.append(f"a point is invalid on some arms only: {split}")
    record(
        "check_14_the_agreement_is_recomputed_from_the_ruling",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 09 the sweep --------------------------------------------------------------


def check_09_sweep() -> None:
    """Positive 9: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_09_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_09_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01a_three_runs_with_registered_digests,
        check_01b_each_arm_left_the_checkpoints_the_metrics_read,
        check_02a_the_two_off_arms_carry_different_cache_keys,
        check_02b_the_off_arms_differ_in_text_and_agree_in_batching,
        check_03a_the_gap01_rule_recomputes_from_the_three_columns,
        check_03b_the_batch_evidence_only_moves_the_rows_it_may,
        check_03c_the_report_regenerates_byte_for_byte,
        check_04_the_chain_ab_is_measured_on_every_arm,
        check_05a_the_ledger_no_longer_needs_three_runs,
        check_05b_the_gap_register_closes_over_the_new_rows,
        check_05c_every_path_this_batch_cites_exists,
        check_06_no_upstream_and_no_ground_truth_change,
        check_07_the_runner_registers_this_gate,
        check_08a_only_the_runner_may_spend,
        check_08b_ascii_prose,
        check_10_every_judgement_answers_within_the_declared_vocabularies,
        check_11_the_test_points_are_the_adjudicated_positives,
        check_12_the_judgements_replay_from_cache_byte_for_byte,
        check_13_the_manual_review_is_ruled_and_covers_every_row,
        check_14_the_agreement_is_recomputed_from_the_ruling,
        check_09_sweep,
    ]
    for check in checks:
        name = check.__name__
        if harness.FAST_TIER and name in PIPELINE_TIER:
            harness.fast_skip(name)
            continue
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(name, False, f"raised {exc!r}")
    print(f"\nspec_check_e2: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_e2")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
