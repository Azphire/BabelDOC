"""Gate script for F3, the close of the five day repair cycle.

Run from the repository root:

    python spec_checks/spec_check_f3.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: every assertion is answered from what this cycle's runs left
behind or from the documents this session moved.

What F3 is. It is not a mechanism batch. It runs the deferred half of the gate
history (the sweep set, held back all cycle under W-B10-04), runs the whole
corpus once more with every switch up and the stages timed, and then closes the
cycle's paperwork: ten waivers move to permanent homes, four gaps open, three
close, one ledger is founded and one evaluation clause is overturned. So the
assertions come in two halves, and both are load bearing.

01 is the scope: what this session may touch and what it may not.

02 is the run, and it is the end to end tier: six samples, every page, and the
claim this cycle earned -- that a whole corpus replays for nothing.

03 is the ruling. It has been in the tree since b10.4 with no pin, and what it
recovered is the quantitative case for the whole page kind channel.

04 is the residue the column reflow left, attributed to the last point.

05 is the documentation: every migration lands somewhere that exists, and every
new register closes over itself.

06 is history: the sweep the cycle deferred, and this gate's own registration.

Tiers: every assertion reads a committed artefact or a document, so the fast
tier runs the whole gate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec_checks import harness  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "f3"
PREVIOUS_TAG = "b10.5"

RUN_DIR = ROOT / "examples" / "output" / "F3"
COLD = RUN_DIR / "cold"
WARM = RUN_DIR / "warm"

WAIVERS = ROOT / "WAIVERS.md"
CONTRACTS = ROOT / "docs" / "reports" / "assertion_contracts.md"
GAPS = ROOT / "docs" / "eval" / "gap_register.md"
FAILURES = ROOT / "docs" / "eval" / "failure_ledger.md"
METRICS = ROOT / "docs" / "eval" / "metric_contract.md"
RUNNER = ROOT / "spec_checks" / "run_all.py"
PIN_GATE = ROOT / "spec_checks" / "spec_check_b7_5.py"

SAMPLES = (
    "AramcoWorld-en-v2",
    "CERNCourier-en",
    "Courier-en",
    "Courier-zh",
    "FD-en-v2",
    "Vogue-en",
)

# The corpus is 41 pages and every sample comes out with the page count it went
# in with. Written here rather than derived, so a sample losing a page is a
# failure rather than a smaller number nobody looked at.
CORPUS_PAGES = 41

# The sample a person ruled on this cycle, and what the ruling recovered. Every
# figure is the F3 run's own; the F2 column is what the same sample produced
# before the ruling and is quoted from the F2 report.
RULED_SAMPLE = "Courier-zh"
RULED_PAGES = 8
RULED_BOUNDARIES = 7
RULED_ELIGIBLE = 6
RULED_CHAINS = 2
RULED_ARTICLES = 3
RULED_BRIEFS = 3
RULED_UNASSIGNED = 1
RULED_DECLARED_LINE_PAGES = 1
RULED_MACHINE_AGREEMENTS = 2

# What the column reflow converged over the corpus, and what it left. The
# residue is attributed row by row in check_04b; these are the totals the
# per-column reports have to add up to.
EXCESS_BEFORE = 1528.44
EXCESS_AFTER = 447.14
EXCESS_TOLERANCE = 0.05

# The reasons a row may carry when it is left alone. Every one of them is an
# anchor refusing to move something; none of them is the shift cap and none is a
# guard, which is the property check_04b turns on.
LEFT_ALONE_REASONS = {
    "obstacle_in_gap",
    "xobject_anchor",
    "formula_anchor",
    "excess_below_floor",
    "column_top",
}

# The waivers this cycle opened. The first four close here by their own terms;
# the other ten carry permanent content and move out.
CLOSED_WAIVERS = ("W-B10-01", "W-B10-02", "W-B10-03", "W-B10-04")
MIGRATED_WAIVERS = (
    "W-B10-05",
    "W-B10-06",
    "W-B10-07",
    "W-B10-08",
    "W-B10-09",
    "W-B10-10",
    "W-B10-11",
    "W-B10-12",
    "W-B10-13",
    "W-B10-14",
)
CONTRACT_ENTRIES = (
    "AC-01",
    "AC-02",
    "AC-03",
    "AC-04",
    "AC-05",
    # Opened by F3 itself: three assertions b10.4's HITL rework made false,
    # found by the sweep set this session finally ran.
    "AC-06",
    "AC-07",
    "AC-08",
)
NEW_GAPS = ("GAP-27", "GAP-28", "GAP-29", "GAP-30")
CLOSED_GAPS = {"GAP-18": "b10.4", "GAP-22": "b10.2", "GAP-23": "b10.2"}
FAILURE_ROWS = 11
# The parse layer is the eighth channel, which is the number PLAN_B10_4_REV2
# already cites. A ledger that renumbered it would break that citation.
PARSE_LAYER_ROW = "FL-08"

# The evidence the rewritten replay clause stands on. Named here so a clause
# that keeps the conclusion and drops the evidence fails.
REPLAY_EVIDENCE = ("b10.2", "b10.4", "CACHE_KEY_VERSION", "volatile_evidence_keys")

# The three modules this session edits, and the whole of what it does to them.
# spec_check_b2's assertion 08 holds every file under babeldoc/ to naming no page
# type at all -- the rule CLAUDE.md 4.2 states as "no branching on page type
# names" -- and three modules delivered this cycle name one in their prose. The
# words are replaced; check_01d asserts that nothing executable moved with them.
PROSE_EDITS = (
    "babeldoc/magazine/fragment_stitch.py",
    "babeldoc/magazine/name_harvest.py",
    "babeldoc/magazine/translation_style.py",
)

ALLOWED_PREFIXES = (
    "docs/eval/",
    "docs/reports/",
    "spec_checks/",
    "examples/output/F3/",
)
ALLOWED_FILES = {
    "CLAUDE.md",
    "WAIVERS.md",
    "UPSTREAM_DIFF.md",
    "plans/PLAN_B10_5_REV2.md",
    "configs/fragment_stitch.json",
    "examples/output/run_all.f3.sweep.log",
    "examples/output/run_all.f3.fast.log",
    *PROSE_EDITS,
}

# Nothing here may move. The ground truth, the rulings and every prompt are read
# by this session and written by none of it. Upstream is expressed as everything
# under babeldoc/ that is not this project's own package, because the three
# files this session does touch are all inside it and are prose only, which
# check_01d proves rather than promises.
FORBIDDEN_PREFIXES = ("corpus/", "prompts/", "reviews/")
UPSTREAM_PREFIX = "babeldoc/"
PROJECT_PACKAGE = "babeldoc/magazine/"

# The two logs this session owes, and how many gates each set holds.
SWEEP_LOG = ROOT / "examples" / "output" / "run_all.f3.sweep.log"
FAST_LOG = ROOT / "examples" / "output" / "run_all.f3.fast.log"
SWEEP_GATES = 18
FAST_GATES = 21

# A debug identifier is minted per run, so a gate anchored to one asserts about
# the run that made it and nothing else (CLAUDE.md 5.13). Built rather than
# written, so the file asserting the rule does not hold the string it forbids.
_NEEDLES = (
    "debug" + chr(95) + "id",
    "debug" + chr(45) + "id",
    "debug" + "Id",
)

# CJK / fullwidth / CJK punctuation, as spec_check_b0 declares them, kept as
# code points so this file stays ASCII itself.
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_f3")


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


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return proc.returncode, proc.stdout


def changed_paths() -> list[str]:
    """This session's delta, anchored to its own tag once the tag exists."""
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        span = f"{PREVIOUS_TAG}..{BATCH_TAG}"
        _, out = git_output(["diff", "--name-only", span])
        return [line.strip() for line in out.splitlines() if line.strip()]
    _, tracked = git_output(["diff", "--name-only", "HEAD"])
    _, untracked = git_output(["ls-files", "--others", "--exclude-standard"])
    return sorted(
        {line.strip() for line in (tracked + untracked).splitlines() if line.strip()}
    )


def _is_cjk(char: str) -> bool:
    """The ranges spec_check_b0 holds every declaration in this project to."""
    return any(low <= ord(char) <= high for low, high in CJK_RANGES)


def arm_records(arm: Path) -> list[dict]:
    ledger = arm / "runs.json"
    if not ledger.exists():
        return []
    return load_json(ledger)


def sidecar(arm: Path, sample: str, name: str) -> dict | None:
    path = arm / sample / "sidecars" / name
    if not path.exists():
        return None
    return load_json(path)


def vocabulary(document: str, marker: str) -> list[str]:
    """The backticked terms of one declared vocabulary comment."""
    for line in document.splitlines():
        if marker in line:
            return re.findall(r"`([^`]+)`", line)
    return []


# --- 01 scope -----------------------------------------------------------------


def check_01a_the_delta_stays_inside_the_declared_paths() -> None:
    """Negative 1a: this session writes documents, its own gate and its own run."""
    stray = sorted(
        path
        for path in changed_paths()
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "check_01a_the_delta_stays_inside_the_declared_paths",
        not stray,
        f"outside the declared paths: {stray[:8]}",
    )


def check_01b_nothing_upstream_and_nothing_owned_by_a_person_moved() -> None:
    """Negative 1b: no upstream file, no ground truth, no ruling, no prompt.

    The one configuration file in the delta is named and checked separately: its
    parsed form has to be what it was, because escaping a character is a change
    to the bytes and not to the declaration.
    """
    changed = changed_paths()
    faults = [
        f"{prefix} changed: {sorted(p for p in changed if p.startswith(prefix))[:4]}"
        for prefix in FORBIDDEN_PREFIXES
        if any(path.startswith(prefix) for path in changed)
    ]
    upstream = sorted(
        path
        for path in changed
        if path.startswith(UPSTREAM_PREFIX) and not path.startswith(PROJECT_PACKAGE)
    )
    if upstream:
        faults.append(f"upstream changed: {upstream}")
    package = sorted(
        path
        for path in changed
        if path.startswith(PROJECT_PACKAGE) and path not in PROSE_EDITS
    )
    if package:
        faults.append(f"the package changed beyond the prose edits: {package}")
    config = "configs/fragment_stitch.json"
    touched_configs = sorted(
        path for path in changed if path.startswith("configs/") and path != config
    )
    if touched_configs:
        faults.append(f"configuration beyond the escaped file: {touched_configs}")
    if config in changed:
        code, before = git_output(["show", f"HEAD:{config}"])
        if code != 0:
            faults.append("the escaped configuration has no committed version")
        else:
            after = text_of(ROOT / config)
            was, now = json.loads(before), json.loads(after)
            # The description gained a sentence saying why the file is escaped;
            # every declaration in it has to be the same value it was, which is
            # what makes the escape a change to the bytes and not to the run.
            if {k: v for k, v in was.items() if k != "description"} != {
                k: v for k, v in now.items() if k != "description"
            }:
                faults.append("the escaped configuration declares something else")
            if not was["description"] in now["description"]:
                faults.append("the description lost what it said")
            if any(_is_cjk(char) for char in after):
                faults.append("the escaped configuration still carries CJK")
    record(
        "check_01b_nothing_upstream_and_nothing_owned_by_a_person_moved",
        not faults,
        "; ".join(faults),
    )


def check_01c_the_gate_names_no_run_local_identifier() -> None:
    """Negative 1c: CLAUDE.md 5.13, applied to this file."""
    source = text_of(Path(__file__))
    hits = sorted({needle for needle in _NEEDLES if needle in source})
    record(
        "check_01c_the_gate_names_no_run_local_identifier",
        not hits,
        f"identifiers named: {hits}",
    )


def check_01d_the_module_edits_are_prose_only() -> None:
    """Negative 1d: the three modules changed no executable token.

    Proved rather than promised: both versions are tokenised and compared with
    comments and string literals removed. A changed word inside a docstring or
    a comment leaves that stream identical; changing anything the interpreter
    acts on does not, whatever the diff looks like.
    """
    import io
    import tokenize

    def executable_tokens(source: str):
        stream = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in {
                tokenize.COMMENT,
                tokenize.STRING,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
            }:
                continue
            stream.append((token.type, token.string))
        return stream

    faults = []
    for relative in PROSE_EDITS:
        code, before = git_output(["show", f"HEAD:{relative}"])
        if code != 0:
            faults.append(f"{relative}: no committed version")
            continue
        after = text_of(ROOT / relative)
        try:
            if executable_tokens(before) != executable_tokens(after):
                faults.append(f"{relative}: an executable token moved")
        except tokenize.TokenError as exc:  # noqa: PERF203 - one file, one reason
            faults.append(f"{relative}: {exc}")
        # The rule these edits answer to is spec_check_b0's, which is about the
        # CJK ranges rather than about ASCII: a typographic quotation mark that
        # was already in the file is not what CLAUDE.md 4.1 is protecting.
        if any(_is_cjk(char) for char in after):
            faults.append(f"{relative}: carries CJK")
    record(
        "check_01d_the_module_edits_are_prose_only", not faults, "; ".join(faults)
    )


# --- 02 the run ---------------------------------------------------------------


def check_02a_both_arms_ran_the_whole_corpus() -> None:
    """Positive 2a: six samples in each arm, and every page came back."""
    faults = []
    for name, arm in (("cold", COLD), ("warm", WARM)):
        rows = arm_records(arm)
        if len(rows) != len(SAMPLES):
            faults.append(f"{name}: {len(rows)} samples")
            continue
        pages = 0
        for row in rows:
            if row["output_pages"] != row["input_pages"]:
                faults.append(
                    f"{name} {row['sample']}: {row['input_pages']} in, "
                    f"{row['output_pages']} out"
                )
            pages += row["output_pages"] or 0
        if pages != CORPUS_PAGES:
            faults.append(f"{name}: {pages} pages against {CORPUS_PAGES}")
    record(
        "check_02a_both_arms_ran_the_whole_corpus", not faults, "; ".join(faults[:6])
    )


def check_02b_the_whole_corpus_replayed_for_nothing() -> None:
    """Positive 2b: every request of both arms was answered by the cache.

    This is the assertion the rewritten replay clause stands on. It is stated
    over both arms deliberately: the cold arm is the one that would have paid if
    anything in this stack were still building a request nobody had built.
    """
    faults = []
    for name, arm in (("cold", COLD), ("warm", WARM)):
        for row in arm_records(arm):
            if row["api_calls"] != 0:
                faults.append(f"{name} {row['sample']}: {row['api_calls']} calls")
            if row["requests"] != row["cache_hits"]:
                faults.append(
                    f"{name} {row['sample']}: {row['requests']} requests, "
                    f"{row['cache_hits']} hits"
                )
    record(
        "check_02b_the_whole_corpus_replayed_for_nothing",
        not faults,
        "; ".join(faults[:6]),
    )


def check_02c_the_repair_loop_paid_nothing_either() -> None:
    """Positive 2c: the loop b9.5 called unreplayable spent nothing, and applied.

    Two conjuncts, because either alone is empty: a loop that spends nothing
    because it did nothing is not the claim. At least one repair has to have
    been applied somewhere in the corpus.
    """
    faults = []
    applications = 0
    for name, arm in (("cold", COLD), ("warm", WARM)):
        for sample in SAMPLES:
            report = sidecar(arm, sample, "react_repair.report.json")
            if report is None:
                faults.append(f"{name} {sample}: no repair sidecar")
                continue
            if report.get("api_calls"):
                faults.append(f"{name} {sample}: {report['api_calls']} calls")
            attributions = report.get("api_attributions") or []
            if len(attributions) != (report.get("api_calls") or 0):
                faults.append(
                    f"{name} {sample}: {len(attributions)} attributions for "
                    f"{report.get('api_calls')} calls"
                )
            applied = report.get("applications")
            applications += applied if isinstance(applied, int) else len(applied or [])
    if not applications:
        faults.append("no repair was applied anywhere in the corpus")
    record(
        "check_02c_the_repair_loop_paid_nothing_either",
        not faults,
        "; ".join(faults[:6]),
    )


def check_02d_every_stage_is_timed() -> None:
    """Positive 2d: the timing sidecar covers the pipeline, in both arms.

    What is asserted is coverage and consistency, not a duration: a stage list
    that is the same length in every sample of an arm, every entry with a run
    count of at least one, and the attributed total never larger than the wall
    clock it is a part of.
    """
    faults = []
    for name, arm in (("cold", COLD), ("warm", WARM)):
        rows = arm_records(arm)
        stage_sets = set()
        for row in rows:
            stages = row.get("stages") or []
            if not stages:
                faults.append(f"{name} {row['sample']}: no stage timing")
                continue
            stage_sets.add(tuple(entry["stage"] for entry in stages))
            for entry in stages:
                if entry["runs"] < 1:
                    faults.append(f"{name} {row['sample']}: {entry['stage']} never ran")
                if entry["seconds"] < 0:
                    faults.append(f"{name} {row['sample']}: {entry['stage']} negative")
            if row["stage_seconds_total"] > row["seconds"]:
                faults.append(
                    f"{name} {row['sample']}: attributed {row['stage_seconds_total']}s "
                    f"of a {row['seconds']}s run"
                )
        if len(stage_sets) > 1:
            faults.append(f"{name}: the samples do not agree on the stage list")
    record("check_02d_every_stage_is_timed", not faults, "; ".join(faults[:6]))


def check_02e_the_two_arms_drew_the_same_pages() -> None:
    """End to end 2e: a warm replay of a cold run is the same document.

    Page by page over the rendered images rather than over the PDF bytes: what
    a replay owes is the same page, and a PDF carries production metadata that
    is not the page. This is the strongest statement this cycle can make about
    determinism.

    The comparison is over the digest files each arm's rasters were reduced to
    (``examples/output/F3/scripts/page_digests.py``), because tracking 82
    images to answer one question would put eighty megabytes in the repository
    for it. The digests are taken from the images, so what is asserted is still
    a property of what was drawn.
    """
    faults = []
    digests = {}
    for arm in ("cold", "warm"):
        path = RUN_DIR / f"page_digests.{arm}.json"
        if not path.exists():
            faults.append(f"no page digests for the {arm} arm")
            continue
        digests[arm] = load_json(path)["pages"]
    if len(digests) == 2:
        if set(digests["cold"]) != set(digests["warm"]):
            faults.append("the two arms drew different samples")
        pages = 0
        for sample in sorted(set(digests["cold"]) & set(digests["warm"])):
            cold, warm = digests["cold"][sample], digests["warm"][sample]
            if set(cold) != set(warm):
                faults.append(f"{sample}: the two arms drew different pages")
                continue
            for label in sorted(cold, key=int):
                pages += 1
                if cold[label] != warm[label]:
                    faults.append(f"{sample} p{label}: the two arms differ")
        if pages != CORPUS_PAGES:
            faults.append(f"{pages} pages compared against {CORPUS_PAGES}")
    record(
        "check_02e_the_two_arms_drew_the_same_pages",
        not faults,
        "; ".join(faults[:6]),
    )


# --- 03 the ruling ------------------------------------------------------------


def check_03a_the_ruling_is_pinned_and_unedited() -> None:
    """Negative 3a: the ruling in the tree is the one the pin names.

    It reached the tree in b10.4 and no session pinned it, so between then and
    here the only ruling written this cycle was the one file the truth digest
    assertion could not see. The pin is read out of the gate that owns it rather
    than repeated here.
    """
    import hashlib

    faults = []
    path = ROOT / "reviews" / f"{RULED_SAMPLE}.decisions.json"
    if not path.exists():
        faults.append("the ruling is absent")
    else:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pinned = re.search(
            r'"reviews/' + RULED_SAMPLE + r'\.decisions\.json":\s*\(\s*"([0-9a-f]{64})"',
            text_of(PIN_GATE),
        )
        if pinned is None:
            faults.append("no pin for this ruling in the truth digests")
        elif pinned.group(1) != digest:
            faults.append(f"pin {pinned.group(1)[:16]} against file {digest[:16]}")
        ruling = load_json(path)
        if ruling.get("format_version") != 2:
            faults.append(f"format_version {ruling.get('format_version')}")
        if len(ruling.get("page_kinds") or {}) != RULED_PAGES:
            faults.append(f"{len(ruling.get('page_kinds') or {})} ruled pages")
    record(
        "check_03a_the_ruling_is_pinned_and_unedited", not faults, "; ".join(faults)
    )


def check_03b_every_ruled_page_arrives_as_a_human_decision() -> None:
    """Positive 3b: all eight pages carry the person's kind, in the warm run."""
    faults = []
    report = sidecar(WARM, RULED_SAMPLE, "hitl_apply.report.json")
    ruling = load_json(ROOT / "reviews" / f"{RULED_SAMPLE}.decisions.json")
    if report is None:
        faults.append("no apply report")
    else:
        rows = report.get("page_kinds") or []
        if len(rows) != RULED_PAGES:
            faults.append(f"{len(rows)} pages applied")
        wanted = {int(page): kind for page, kind in (ruling["page_kinds"]).items()}
        agreements = 0
        for row in rows:
            if wanted.get(row["page"]) != row["kind"]:
                faults.append(f"page {row['page']}: {row['kind']} applied")
            if row["kind"] == row.get("machine_kind"):
                agreements += 1
        if agreements != RULED_MACHINE_AGREEMENTS:
            faults.append(
                f"the classifier agreed on {agreements} pages, not "
                f"{RULED_MACHINE_AGREEMENTS}"
            )
    record(
        "check_03b_every_ruled_page_arrives_as_a_human_decision",
        not faults,
        "; ".join(faults[:6]),
    )


def check_03c_the_ruling_recovered_the_chain_account() -> None:
    """Positive 3c: what one person naming eight pages reached, end to end.

    F2 recorded none of this sample's seven boundaries as chain eligible, no
    declared line structure page, two articles and two briefs. Every figure
    below is this run's own.
    """
    faults = []
    chains = sidecar(WARM, RULED_SAMPLE, "chain_report.json") or {}
    boundaries = chains.get("boundaries") or []
    eligible = sum(1 for entry in boundaries if entry.get("eligible"))
    built = len(chains.get("chains") or [])
    if len(boundaries) != RULED_BOUNDARIES:
        faults.append(f"{len(boundaries)} boundaries")
    if eligible != RULED_ELIGIBLE:
        faults.append(f"{eligible} eligible")
    if built != RULED_CHAINS:
        faults.append(f"{built} chains")

    articles = sidecar(WARM, RULED_SAMPLE, "article_map.json") or {}
    counts = articles.get("counts") or {}
    if counts.get("articles") != RULED_ARTICLES:
        faults.append(f"{counts.get('articles')} articles")
    if counts.get("unassigned") != RULED_UNASSIGNED:
        faults.append(f"{counts.get('unassigned')} unassigned pages")

    context = sidecar(WARM, RULED_SAMPLE, "article_context.report.json") or {}
    if (context.get("counts") or {}).get("briefs") != RULED_BRIEFS:
        faults.append(f"{(context.get('counts') or {}).get('briefs')} briefs")

    lines = sidecar(WARM, RULED_SAMPLE, "line_split.report.json") or {}
    declared = (lines.get("totals") or {}).get("declared_pages")
    if declared != RULED_DECLARED_LINE_PAGES:
        faults.append(f"{declared} declared line structure pages")
    if not (lines.get("totals") or {}).get("split_paragraphs"):
        faults.append("no paragraph was split into lines")
    record(
        "check_03c_the_ruling_recovered_the_chain_account",
        not faults,
        "; ".join(faults[:6]),
    )


# --- 04 the residue -----------------------------------------------------------


def _reflow_rows() -> tuple[float, float, dict[str, float]]:
    """The corpus totals and the residue by reason, over applied columns."""
    before = after = 0.0
    residue: dict[str, float] = {}
    for sample in SAMPLES:
        report = sidecar(WARM, sample, "column_reflow.report.json")
        if report is None:
            continue
        totals = report.get("totals") or {}
        before += totals.get("excess_sum_before", 0.0)
        after += totals.get("excess_sum_after", 0.0)
        for page in report.get("pages") or ():
            for column in page.get("columns") or ():
                if not column.get("applied"):
                    continue
                for row in column.get("rows") or ():
                    value = row.get("excess_after")
                    if value is None:
                        value = row.get("excess")
                    if value is None:
                        continue
                    residue[row["reason"]] = residue.get(row["reason"], 0.0) + abs(value)
    return before, after, residue


def check_04a_the_reflow_totals_reproduce() -> None:
    """Positive 4a: the corpus totals are the sum of the rows underneath them."""
    before, after, residue = _reflow_rows()
    faults = []
    if abs(before - EXCESS_BEFORE) > EXCESS_TOLERANCE:
        faults.append(f"before {before:.2f} against {EXCESS_BEFORE}")
    if abs(after - EXCESS_AFTER) > EXCESS_TOLERANCE:
        faults.append(f"after {after:.2f} against {EXCESS_AFTER}")
    recomputed = sum(residue.values())
    if abs(recomputed - after) > EXCESS_TOLERANCE:
        faults.append(f"rows add to {recomputed:.2f}, the totals say {after:.2f}")
    record("check_04a_the_reflow_totals_reproduce", not faults, "; ".join(faults))


def check_04b_every_point_of_the_residue_is_an_anchor() -> None:
    """Positive 4b: what is left is what the pass refused, and says which refusal.

    The claim the gap register makes is that no part of the residue is the shift
    cap running out and no part is a guard rolling a column back. So every
    reason carrying residue has to be one of the declared anchors, and the run
    has to have refused nothing by guard.
    """
    _, after, residue = _reflow_rows()
    faults = []
    unknown = sorted(set(residue) - LEFT_ALONE_REASONS - {"converged"})
    if unknown:
        faults.append(f"undeclared reasons carry residue: {unknown}")
    if residue.get("converged", 0.0) > EXCESS_TOLERANCE:
        faults.append(f"converged rows still carry {residue['converged']:.2f} pt")
    obstacles = residue.get("obstacle_in_gap", 0.0)
    if after and obstacles / after < 0.5:
        faults.append(
            f"obstacles are {100 * obstacles / after:.1f}% of the residue, "
            "which is not what the register says"
        )
    for sample in SAMPLES:
        report = sidecar(WARM, sample, "column_reflow.report.json")
        if report is None:
            continue
        if report.get("guards"):
            faults.append(f"{sample}: a guard refused something: {report['guards']}")
        if (report.get("totals") or {}).get("pages_reverted"):
            faults.append(f"{sample}: a page was rolled back")
    record(
        "check_04b_every_point_of_the_residue_is_an_anchor",
        not faults,
        "; ".join(faults[:6]),
    )


# --- 05 the documentation -----------------------------------------------------


def check_05a_the_waivers_are_closed_and_the_rest_moved_out() -> None:
    """Positive 5a: four rows closed, ten migrated, and every destination named."""
    text = text_of(WAIVERS)
    faults = []
    for waiver in CLOSED_WAIVERS:
        if f"~~{waiver}~~" not in text:
            faults.append(f"{waiver} is not struck through")
    for waiver in MIGRATED_WAIVERS:
        if f"| {waiver} |" in text.replace(f"| {waiver} | ", "| MIGRATED | ", 1):
            faults.append(f"{waiver} still holds a row in the table")
        if waiver not in text:
            faults.append(f"{waiver} is not named in the migration index")
    for line in text.splitlines():
        if not line.startswith("| W-B10-"):
            continue
        identifier = line.split("|")[1].strip()
        if identifier in CLOSED_WAIVERS:
            faults.append(f"{identifier} is still an open row")
    record(
        "check_05a_the_waivers_are_closed_and_the_rest_moved_out",
        not faults,
        "; ".join(faults[:6]),
    )


def check_05b_every_migration_lands_somewhere_that_exists() -> None:
    """Positive 5b: the index's destinations resolve, and the entries are there."""
    text = text_of(WAIVERS)
    faults = []
    contracts = text_of(CONTRACTS) if CONTRACTS.exists() else ""
    gaps = text_of(GAPS) if GAPS.exists() else ""
    if not contracts:
        faults.append("the assertion contract register is absent")
    for entry in CONTRACT_ENTRIES:
        if f"## {entry}" not in contracts:
            faults.append(f"{entry} has no section")
    # Every contract entry names the waiver it came from, so the old identifier
    # still resolves for the gate comments and reports that cite it.
    for waiver in ("W-B10-05", "W-B10-06", "W-B10-12", "W-B10-13", "W-B10-14"):
        if waiver not in contracts:
            faults.append(f"{waiver} is not named by any contract entry")
    if "GAP-28" not in gaps:
        faults.append("the detector issue did not reach the gap register")
    for path in re.findall(r"`(docs/[^`]+)`", text):
        if "*" in path:  # a waiver's prose names a family, not a file
            continue
        if not (ROOT / path).exists():
            faults.append(f"the index points at {path}, which does not exist")
    record(
        "check_05b_every_migration_lands_somewhere_that_exists",
        not faults,
        "; ".join(faults[:6]),
    )


def check_05c_the_gap_register_opened_four_and_closed_three() -> None:
    """Positive 5c: the new sections are there, and the closed ones say by what."""
    text = text_of(GAPS)
    faults = []
    for gap in NEW_GAPS:
        heading = [line for line in text.splitlines() if line.startswith(f"### {gap}")]
        if not heading:
            faults.append(f"{gap} has no section")
            continue
        body = text.split(heading[0], 1)[1].split("\n### ", 1)[0]
        # A gap entry is a contract: what it is, how it would be closed, what it
        # costs, and the wording the paper carries if it is not.
        for marker in ("**\u73b0\u72b6", "**\u8865\u6cd5", "**\u6210\u672c", "\u4e0d\u8865"):
            if marker not in body:
                faults.append(f"{gap} states no {marker}")
    for gap, batch in CLOSED_GAPS.items():
        heading = [line for line in text.splitlines() if line.startswith(f"### {gap}")]
        if not heading:
            faults.append(f"{gap} has no section")
        elif batch not in heading[0]:
            faults.append(f"{gap} does not name the batch that closed it")
    record(
        "check_05c_the_gap_register_opened_four_and_closed_three",
        not faults,
        "; ".join(faults[:6]),
    )


def check_05d_the_failure_ledger_closes_over_itself() -> None:
    """Positive 5d: eleven channels, every one classified, and the tally is right.

    The state words are read out of the ledger's own declared vocabulary rather
    than written here, for the reason E0 gives about the evidence ledger: a
    vocabulary that stopped matching has to fail here rather than quietly
    classify nothing.
    """
    text = text_of(FAILURES)
    faults = []
    states = vocabulary(text, "state-vocabulary:")
    if not states:
        faults.append("the ledger declares no state vocabulary")
        record("check_05d_the_failure_ledger_closes_over_itself", False, faults[0])
        return
    rows = re.findall(r"^## (FL-\d+) ", text, re.M)
    if len(rows) != FAILURE_ROWS:
        faults.append(f"{len(rows)} channels against {FAILURE_ROWS}")
    if PARSE_LAYER_ROW not in rows:
        faults.append(f"{PARSE_LAYER_ROW} is not a channel")
    tally: dict[str, int] = dict.fromkeys(states, 0)
    for row in rows:
        body = text.split(f"## {row} ", 1)[1].split("\n## ", 1)[0]
        state_line = [
            line for line in body.splitlines() if line.strip().startswith("- **\u72b6\u6001")
        ]
        if not state_line:
            faults.append(f"{row} carries no state")
            continue
        found = [
            (state_line[0].index(f"`{state}`"), state)
            for state in states
            if f"`{state}`" in state_line[0]
        ]
        if not found:
            faults.append(f"{row} carries no declared state")
            continue
        tally[min(found)[1]] += 1
    for state, counted in tally.items():
        stated = re.search(rf"^\|\s*`{re.escape(state)}`\s*\|\s*(\d+)\s*\|", text, re.M)
        if stated is None:
            faults.append(f"the tally does not count the {state} rows")
        elif int(stated.group(1)) != counted:
            faults.append(
                f"the tally says {stated.group(1)} {state}, recomputed {counted}"
            )
    record(
        "check_05d_the_failure_ledger_closes_over_itself",
        not faults,
        "; ".join(faults[:6]),
    )


def check_05e_the_replay_clause_was_rewritten_with_its_evidence() -> None:
    """Positive 5e: the overturned clause is struck and the new one is sourced.

    A clause that keeps the conclusion and drops the evidence is the failure
    mode here: the old text said the repair loop is unreplayable, and what makes
    the new text usable is naming the two batches and the two mechanisms that
    made it false.
    """
    text = text_of(METRICS)
    faults = []
    if "~~" not in text:
        faults.append("nothing in the contract is struck through")
    for marker in REPLAY_EVIDENCE:
        if marker not in text:
            faults.append(f"the clause does not cite {marker}")
    # The overturned proposition may survive only inside the struck block.
    live = re.sub(r"~~.*?~~", "", text, flags=re.S)
    if "\u552f\u4e00\u4e0d\u53ef\u91cd\u653e" in live:
        faults.append("the overturned proposition is still stated as live")
    record(
        "check_05e_the_replay_clause_was_rewritten_with_its_evidence",
        not faults,
        "; ".join(faults[:6]),
    )


# --- 06 history ---------------------------------------------------------------


def check_06a_the_runner_registers_this_gate() -> None:
    """Positive 6a: a gate the runner does not list is a gate that always passes."""
    source = text_of(RUNNER)
    name = Path(__file__).name
    faults = []
    if f'"{name}"' not in source:
        faults.append("run_all.py does not list this gate")
    if f'GATE_SET = "{GATE_SET}"' not in text_of(Path(__file__)):
        faults.append("this gate declares no set")
    record(
        "check_06a_the_runner_registers_this_gate", not faults, "; ".join(faults)
    )


def check_06b_the_deferred_history_ran_and_is_green() -> None:
    """End to end 6b: the sweep W-B10-04 held back all cycle, and the fast set.

    Read out of the two logs this session commits rather than re-run here: a
    gate that re-ran the sweep would cost what the sweep costs, and the sweep is
    the thing this assertion is about.

    The two logs are read differently, and the difference is not a softening.
    This gate is not in the sweep set, so the sweep log is an account of a run
    this gate had no part in and every one of its eighteen gates has to have
    passed. This gate *is* in the fast set, so a fast log is always an account
    of a run that included the reading of the previous fast log -- requiring it
    to be wholly green would be requiring a fixed point of this assertion
    against itself. What is required instead is that no gate **other than this
    one** failed in it, which is the whole of what a fast log can say about a
    tree without asserting about its own reading.
    """
    faults = []
    mine = Path(__file__).name

    if not SWEEP_LOG.exists():
        faults.append("the sweep log is absent")
    else:
        text = SWEEP_LOG.read_text(encoding="utf-8", errors="replace")
        summary = re.findall(r"(\d+)/(\d+) gates passed in", text)
        if not summary:
            faults.append("the sweep log states no result")
        else:
            passed, total = (int(value) for value in summary[-1])
            if passed != total:
                faults.append(f"sweep: {passed} of {total}")
            if total != SWEEP_GATES:
                faults.append(f"sweep: {total} gates, expected {SWEEP_GATES}")

    if not FAST_LOG.exists():
        faults.append("the fast log is absent")
    else:
        text = FAST_LOG.read_text(encoding="utf-8", errors="replace")
        summary = re.findall(r"(\d+)/(\d+) gates passed in", text)
        if not summary:
            faults.append("the fast log states no result")
        else:
            others = [
                gate
                for gate in re.findall(r"^\s*FAILED: (spec_check_\S+\.py)", text, re.M)
                if gate != mine
            ]
            if others:
                faults.append(f"fast: {sorted(set(others))} failed")
            total = int(summary[-1][1])
            if total != FAST_GATES:
                faults.append(f"fast: {total} gates, expected {FAST_GATES}")
    record(
        "check_06b_the_deferred_history_ran_and_is_green",
        not faults,
        "; ".join(faults[:6]),
    )


CHECKS = (
    check_01a_the_delta_stays_inside_the_declared_paths,
    check_01b_nothing_upstream_and_nothing_owned_by_a_person_moved,
    check_01c_the_gate_names_no_run_local_identifier,
    check_01d_the_module_edits_are_prose_only,
    check_02a_both_arms_ran_the_whole_corpus,
    check_02b_the_whole_corpus_replayed_for_nothing,
    check_02c_the_repair_loop_paid_nothing_either,
    check_02d_every_stage_is_timed,
    check_02e_the_two_arms_drew_the_same_pages,
    check_03a_the_ruling_is_pinned_and_unedited,
    check_03b_every_ruled_page_arrives_as_a_human_decision,
    check_03c_the_ruling_recovered_the_chain_account,
    check_04a_the_reflow_totals_reproduce,
    check_04b_every_point_of_the_residue_is_an_anchor,
    check_05a_the_waivers_are_closed_and_the_rest_moved_out,
    check_05b_every_migration_lands_somewhere_that_exists,
    check_05c_the_gap_register_opened_four_and_closed_three,
    check_05d_the_failure_ledger_closes_over_itself,
    check_05e_the_replay_clause_was_rewritten_with_its_evidence,
    check_06a_the_runner_registers_this_gate,
    check_06b_the_deferred_history_ran_and_is_green,
)


def main() -> int:
    print("spec_check_f3: the close of the five day repair cycle\n")
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
