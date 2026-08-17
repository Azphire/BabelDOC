"""Gate script for batch B9.2R (the recovery batch).

Run from the repository root:

    python spec_checks/spec_check_b9_2r.py

Exit code 0 when every assertion this batch answers for passes, 1 otherwise.
Needs no API key, makes no network request and runs no pipeline: this batch
pays off a debt left by batch b9.2 and changes no pipeline behaviour.

What went wrong, since every assertion here is a fence around one part of it.
Batch b9.2 session one declared an empty output directory for itself. That
moved the retention policy's protection window forward by one batch, batch b8.4
fell out of it, and the untracked half of that batch's smoke run -- page level
rasters and every stage checkpoint -- was deleted at the end of the sweep. Three
assertions in three later gates read those files. One of them re-ran its tool
with the tracked result file as the tool's output path, so the tool found no
inputs, wrote a degenerate result over the frozen one, and the assertion then
reported that the recomputation differed from a file it had just destroyed.

01 is the downgrade. The four ledger rows whose artefacts are gone carry the
status this batch introduces, the ledger declares that status and counts it, and
the gap register carries a section that names all four. The citations themselves
are the corpus owner's text and are not asserted here beyond their presence: the
point of the downgrade is that the wording survives and the artefact does not.

02 is the soul of the batch, and it is negative. Frozen evidence is read-only.
02a re-enacts the accident exactly -- the tool is invoked the way the gate used
to invoke it, with the tracked path as its output -- and requires it to refuse.
02b runs the two gates that re-run tools and requires every tracked file under
the frozen prefixes to come back byte for byte, which is asserted over a real
absence: the inputs those gates want are the ones b9.2 deleted. 02c removes a
dependency that is still present, artificially and reversibly, and requires the
same. 02d is the static form: no gate may name a frozen directory as a tool's
output.

03 is the retention policy. The configured protection list covers what the E0
gate registers by path and SHA-256, no registered path is selected for removal
anywhere in the real tree, and the archive pass has put the evicted batches'
small text into git. 03d is the negative twin: bulk products are still removed,
because an archive of the intermediate language would be the disk bill the
policy exists to avoid.

04 is the cache lock. A second sweep is refused while a first holds the cache,
a lock whose process is gone is not a holder, and nothing an interrupted build
left is still on the disk.

05 is scope and registration: no upstream file, no ground truth, no ruling; the
runner runs this gate; the convention this batch installed is in CLAUDE.md and
is pinned by digest.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec_checks import artifacts  # noqa: E402
from spec_checks import frozen  # noqa: E402
from spec_checks import harness  # noqa: E402

from tools import prune_outputs  # noqa: E402

BATCH_TAG = "batch-b9.2r"

PYTHON = sys.executable

EVAL_DIR = ROOT / "docs" / "eval"
LEDGER = EVAL_DIR / "evidence_ledger.md"
GAPS = EVAL_DIR / "gap_register.md"
LOPO_RESULT = EVAL_DIR / "results_e1" / "lopo_v2.json"
LOPO_TOOL = ROOT / "tools" / "lopo.py"

RETENTION_CONFIG = ROOT / "configs" / "output_retention.json"
OUTPUT_DIR = ROOT / "examples" / "output"
ARCHIVE_DIR = ROOT / "docs" / "reports" / "archive"

E0_GATE = ROOT / "spec_checks" / "spec_check_e0.py"
E1_GATE = ROOT / "spec_checks" / "spec_check_e1.py"
E2_GATE = ROOT / "spec_checks" / "spec_check_e2.py"
RUNNER = ROOT / "spec_checks" / "run_all.py"

# A dependency of the E2 attribution that is still on the disk. Small, so
# hiding it and putting it back costs one rename each way, and load bearing: the
# analysis tool reads it before anything else.
REMOVABLE_DEPENDENCY = OUTPUT_DIR / "e2" / "r1" / "runs.json"
HIDDEN_SUFFIX = ".b9_2r_hidden"

# The status this batch adds to the ledger's vocabulary. ASCII, so it can be
# named here; the four Chinese statuses that were already there cannot be, and
# are read out of the document wherever they are needed.
PRUNED_STATUS = "artifact pruned, sha recorded"

# The rows whose artefacts the b9.2 sweep deleted. Fixed here rather than
# derived, because the whole assertion is that this specific set was downgraded
# and no other row was touched to make a count come out.
DOWNGRADED_ROWS = ("A-26", "E-02", "E-06", "E-13")

# The gap register section that answers for them.
GAP = "GAP-19"

# The clause batch b9.2r added to CLAUDE.md section 4, pinned by digest. The
# clause is written in the project's working language and this file is ASCII, so
# the pin is what "recorded verbatim" means here: the text is in CLAUDE.md, the
# digest is the assertion that it is the text this gate was written against.
#
# Anchors are checked too, because a digest says only that something changed and
# these are the terms the clause has to keep naming for the mechanisms below to
# be the ones it describes.
CLAUSE_NUMBER = "13"
CLAUSE_DIGEST = "30930be777068552e386655b54f73a810b3e71eec9697cb413473125574fd78b"
CLAUSE_ANCHORS = (
    "docs/eval/results_*",
    "SKIPPED/FAIL",
    "protected_paths",
    "configs/output_retention.json",
    "spec_checks/spec_check_e0.py",
    "archive_patterns",
    "archive_max_file_kb",
    "docs/reports/archive/<batch>.zip",
    "corpus/manifest.json",
    PRUNED_STATUS,
)

# What the policy must keep whole. Read from the configuration rather than
# written here; this is the value the batch settled on and the assertion is that
# it is still the one the b8.4 gate's fabricated tree was measured against.
EXPECTED_KEEP_RECENT = 2

# Paths this batch may change. No pipeline package, no ground truth, no ruling:
# a recovery batch pays off documentation and gate debt.
ALLOWED_PREFIXES = (
    "configs/",
    "docs/eval/",
    "docs/reports/",
    "plans/",
    "spec_checks/",
    "tools/",
)
ALLOWED_FILES = {
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
}

# Prefixes no session of this batch may touch.
FORBIDDEN_PREFIXES = ("babeldoc/", "corpus/", "reviews/", "prompts/")

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Assertions that run another gate as a subprocess. Skipped by the fast tier.
PIPELINE_TIER = (
    "check_02b_the_evaluation_gates_write_no_frozen_file",
    "check_02c_a_removed_dependency_still_writes_nothing",
)

BACKTICKED = re.compile(r"`([^`\n]+)`")
ROW_ID = re.compile(r"^([A-G])-(\d+)$")
STATUS_MARKER = "status-vocabulary:"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b9_2r")


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


def ledger_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in text_of(LEDGER).splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and ROW_ID.match(cells[0]):
            rows[cells[0]] = cells
    return rows


def status_vocabulary() -> set[str]:
    for line in text_of(LEDGER).splitlines():
        if STATUS_MARKER in line:
            return set(BACKTICKED.findall(line))
    return set()


def run_gate(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        [PYTHON, str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1", "PYTHONUNBUFFERED": "1"},
    )


def clause_text() -> str | None:
    """The CLAUDE.md clause this batch added, as one line, or None.

    Located by its number at the start of a line, which is ASCII whatever the
    clause itself is written in.
    """
    for line in text_of(ROOT / "CLAUDE.md").splitlines():
        if line.startswith(f"{CLAUSE_NUMBER}. "):
            return line
    return None


# --- 01 the downgrade ----------------------------------------------------------


def check_01a_the_four_rows_carry_the_pruned_status() -> None:
    """Positive 1a: the rows whose artefacts are gone say so, and only those.

    The status word has to be the first one in the cell, because that is the
    rule the ledger states for counting itself: a cell that also carries the
    citable qualifiers -- and these do, since the wording is still citable -- is
    counted under whichever word comes first.
    """
    vocabulary = status_vocabulary()
    rows = ledger_rows()
    faults = []
    if PRUNED_STATUS not in vocabulary:
        faults.append("the ledger does not declare the pruned status")
    for identifier in DOWNGRADED_ROWS:
        if identifier not in rows:
            faults.append(f"the ledger has no row {identifier}")
            continue
        cell = rows[identifier][-1]
        if PRUNED_STATUS not in cell:
            faults.append(f"{identifier} does not carry the pruned status")
        elif cell.index(PRUNED_STATUS) != min(
            cell.index(term) for term in vocabulary if term in cell
        ):
            faults.append(f"{identifier} counts under another status")
    carrying = sorted(
        identifier
        for identifier, cells in rows.items()
        if PRUNED_STATUS in cells[-1]
    )
    if carrying != sorted(DOWNGRADED_ROWS):
        faults.append(f"the pruned status is on {carrying}")
    record("check_01a_the_four_rows_carry_the_pruned_status", not faults, "; ".join(faults))


def check_01b_the_gap_register_answers_for_all_four() -> None:
    """Positive 1b: one section names every downgraded row and refuses the rebuild.

    A downgrade nobody wrote a reason for is indistinguishable from a number
    quietly going missing. The section has to name the rows, and it has to carry
    the wording a citation of them is bound to, which is what makes the
    downgrade a contract rather than a note.
    """
    gaps = text_of(GAPS)
    faults = []
    sections = re.findall(r"^#+\s*(GAP-\d+)", gaps, re.M)
    if GAP not in sections:
        record(
            "check_01b_the_gap_register_answers_for_all_four",
            False,
            f"the register has no {GAP} section",
        )
        return
    start = gaps.index(f"{GAP}")
    following = [
        gaps.index(f"### {name}", start)
        for name in sections
        if f"### {name}" in gaps[start + 1 :] and gaps.index(f"### {name}", start) > start
    ]
    section = gaps[start : min(following)] if following else gaps[start:]
    for identifier in DOWNGRADED_ROWS:
        if identifier not in section:
            faults.append(f"{GAP} does not name {identifier}")
    if PRUNED_STATUS not in section:
        faults.append(f"{GAP} does not name the status it assigns")
    # The two artefacts of the loss the section has to be explicit about: what
    # cannot be quoted, and that a rerun does not restore it.
    for anchor in ("prompt", "gate_cache"):
        if anchor not in section:
            faults.append(f"{GAP} does not discuss {anchor}")
    record("check_01b_the_gap_register_answers_for_all_four", not faults, "; ".join(faults))


def check_01c_the_retired_paths_are_registered_and_absent() -> None:
    """Positive/negative 1c: the deleted artefacts are listed, and are really gone.

    The register is the ledger's own negative assertion area and the E0 gate
    already asserts that everything in it is absent. What is asserted here is
    that this batch's losses entered it: a downgrade whose paths were left out
    of the register would read, to the next reader, as evidence that is still
    fetchable.
    """
    document = text_of(LEDGER)
    begin, end = "<!-- absent-paths:begin -->", "<!-- absent-paths:end -->"
    faults = []
    if begin not in document or end not in document:
        record(
            "check_01c_the_retired_paths_are_registered_and_absent",
            False,
            "the ledger carries no retired-artefact register",
        )
        return
    block = document[document.index(begin) : document.index(end)]
    listed = [token for token in BACKTICKED.findall(block) if "/" in token]
    b8_4 = [token for token in listed if token.startswith("examples/output/b8_4/")]
    if len(b8_4) < 5:
        faults.append(f"the register lists {len(b8_4)} b8.4 path(s), expected the five")
    for token in b8_4:
        if (ROOT / token).exists():
            faults.append(f"{token} is registered as retired and is in the tree")
    record(
        "check_01c_the_retired_paths_are_registered_and_absent",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 02 frozen evidence is read-only -------------------------------------------


def check_02a_the_accident_now_refuses() -> None:
    """Negative 2a: the invocation that destroyed the fold matrix is refused.

    Not a paraphrase of it: the tool is run with the tracked path as its output,
    which is what the assertion in the E1 gate used to do and what the tool's
    own default still is. With the inputs gone it has nothing to compute, and a
    tool that writes what it could not compute over the file it could not
    compute it from is the whole defect. It has to exit non-zero and leave the
    bytes alone.
    """
    before = LOPO_RESULT.read_bytes()
    proc = subprocess.run(  # noqa: S603
        [
            PYTHON,
            str(LOPO_TOOL),
            "--out",
            str(LOPO_RESULT.parent),
            "--name",
            LOPO_RESULT.stem,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    faults = []
    if proc.returncode == 0:
        faults.append("the tool reported success over inputs that are not there")
    if LOPO_RESULT.read_bytes() != before:
        faults.append("the tool overwrote the tracked fold matrix")
    if "untouched" not in (proc.stdout or ""):
        faults.append("the tool did not say it left the target alone")
    record("check_02a_the_accident_now_refuses", not faults, "; ".join(faults))


def check_02b_the_evaluation_gates_write_no_frozen_file() -> None:
    """Negative 2b: the two gates that re-run tools leave the record alone.

    Asserted over a real absence rather than a simulated one -- the inputs these
    gates want are the ones the b9.2 sweep deleted -- so a gate that recomputed
    in place would be caught here by the same mechanism that failed to catch it
    then. Each gate also has to still pass: a skip that names its missing path is
    the outcome, not a failure.
    """
    faults = []
    for gate in (E1_GATE, E2_GATE):
        before = frozen.snapshot()
        proc = run_gate(gate)
        written = frozen.changed(before)
        if written:
            faults.append(f"{gate.name} wrote {written}")
        if proc.returncode != 0:
            faults.append(f"{gate.name} exited {proc.returncode}")
        if "SKIPPED" in (proc.stdout or "") and "frozen dependency absent" not in (
            proc.stdout or ""
        ):
            faults.append(f"{gate.name} skipped without naming a missing path")
    record(
        "check_02b_the_evaluation_gates_write_no_frozen_file",
        not faults,
        "; ".join(faults[:4]),
    )


def check_02c_a_removed_dependency_still_writes_nothing() -> None:
    """Negative 2c: hide an input that is present, and the record does not move.

    The assertion above runs against inputs that are already gone, which proves
    the state this repository is in. This one proves the rule for an input that
    is here: a small, load bearing dependency of the E2 attribution is renamed
    aside, the gate is run, and every frozen file has to come back byte for
    byte. The rename is undone whatever happens, including on a raised
    assertion.
    """
    if not REMOVABLE_DEPENDENCY.is_file():
        record(
            "check_02c_a_removed_dependency_still_writes_nothing",
            False,
            f"{REMOVABLE_DEPENDENCY.relative_to(ROOT)} is not there to remove",
        )
        return
    hidden = REMOVABLE_DEPENDENCY.with_name(REMOVABLE_DEPENDENCY.name + HIDDEN_SUFFIX)
    before = frozen.snapshot()
    faults = []
    try:
        REMOVABLE_DEPENDENCY.replace(hidden)
        proc = run_gate(E2_GATE)
        written = frozen.changed(before)
        if written:
            faults.append(f"the gate wrote {written} with its input removed")
        if proc.returncode == 0:
            faults.append("the gate passed with a dependency removed")
    finally:
        with contextlib.suppress(OSError):
            hidden.replace(REMOVABLE_DEPENDENCY)
    if not REMOVABLE_DEPENDENCY.is_file():
        faults.append("the removed dependency was not put back")
    record(
        "check_02c_a_removed_dependency_still_writes_nothing",
        not faults,
        "; ".join(faults[:4]),
    )


def check_02d_no_gate_names_a_frozen_directory_as_an_output() -> None:
    """Negative 2d: the static form of the same rule, over every gate.

    A recomputation writes to a temporary directory. This reads every gate for
    the shape that caused the loss: a subprocess argument list carrying an
    output flag whose value is a frozen path. It is a syntactic check and it
    catches the syntactic mistake, which is the one that was made; 2a to 2c
    cover the behaviour.
    """
    flags = {"--out", "--output", "--out-dir", "-o"}
    frozen_names = {"RESULTS", "EVAL_DIR", "LOPO_RESULT", "ATTRIBUTION", "JUDGEMENTS"}

    def offenders(source: str, label: str) -> list[str]:
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.List):
                continue
            items = [ast.unparse(element) for element in node.elts]
            for index, item in enumerate(items[:-1]):
                if item.strip("'\"") not in flags:
                    continue
                value = items[index + 1]
                if any(name in value for name in frozen_names) and "tmp" not in value:
                    found.append(f"{label}: {item} {value}")
        return found

    # Positive control first. A negative assertion whose detector has quietly
    # stopped matching passes forever, and the shape it looks for is a
    # string-matching one, so it is worth one synthetic offender to know.
    control = "subprocess.run([PYTHON, str(TOOL), '--out', str(RESULTS)])"
    faults = []
    if not offenders(control, "control"):
        faults.append("the detector does not recognise the shape that caused the loss")

    for path in sorted((ROOT / "spec_checks").glob("spec_check_*.py")):
        faults.extend(offenders(text_of(path), path.name))
    # This gate is the one exception and states why: 2a re-enacts the accident
    # on purpose, and its whole assertion is that the write does not happen.
    allowed = f"{Path(__file__).name}: '--out' str(LOPO_RESULT.parent)"
    faults = [fault for fault in faults if fault != allowed]
    record(
        "check_02d_no_gate_names_a_frozen_directory_as_an_output",
        not faults,
        "; ".join(faults[:5]),
    )


def check_02e_the_runner_digests_the_record_around_every_gate() -> None:
    """Positive 2e: the mechanical guard exists and covers every gate.

    The cooperative layer is per assertion and can be forgotten. This is the
    layer that cannot: the runner takes a digest before each gate and compares
    after, so a write through a tool three subprocesses down fails the gate that
    caused it whether or not anybody predicted the path.
    """
    tree = ast.parse(text_of(RUNNER))
    faults = []
    driver = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "Popen"
                for inner in ast.walk(node)
            )
        ),
        None,
    )
    if driver is None:
        record(
            "check_02e_the_runner_digests_the_record_around_every_gate",
            False,
            "the runner starts no gate process",
        )
        return
    body = ast.unparse(driver)
    for needle in ("frozen.snapshot()", "frozen.changed("):
        if needle not in body:
            faults.append(f"the gate runner does not call {needle}")
    if "code = code or 1" not in body:
        faults.append("a written frozen file does not fail the gate")
    if not frozen.frozen_paths():
        faults.append("the frozen prefixes cover no tracked file, so the guard is idle")
    record(
        "check_02e_the_runner_digests_the_record_around_every_gate",
        not faults,
        "; ".join(faults),
    )


# --- 03 the retention policy ---------------------------------------------------


def _e0_registered_paths() -> tuple[set[str], set[str]]:
    """The two evidence tiers the E0 gate registers, as path strings.

    Read out of that gate's source rather than imported, because importing it
    would run it. The lists are module level tuples of literals, so they are
    read as literals.
    """
    tree = ast.parse(text_of(E0_GATE))
    values: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id in ("TRACKED_EVIDENCE", "WORKSPACE_EVIDENCE"):
            with contextlib.suppress(ValueError):
                values[target.id] = ast.literal_eval(node.value)
    tracked = {str(item) for item in values.get("TRACKED_EVIDENCE", ())}
    workspace = {str(pair[0]) for pair in values.get("WORKSPACE_EVIDENCE", ())}
    return tracked, workspace


def check_03a_the_protection_list_covers_what_e0_registers() -> None:
    """Positive 3a: the policy protects the evidence intake, by path.

    The tracked-file guard says nothing about the second tier -- those files are
    kept out of git by size, which is the whole reason they are registered by
    path and digest -- so the policy has to name them itself. Both tiers are
    required, because a file entering git later should not silently drop out of
    the policy's own list.
    """
    config = prune_outputs.load_config()
    listed = {str(entry) for entry in config[prune_outputs.PROTECTED_PATHS_KEY]}
    tracked, workspace = _e0_registered_paths()
    faults = []
    if not workspace:
        faults.append("the E0 gate registers no path-and-digest evidence")
    for entry in sorted(tracked | workspace):
        if entry not in listed:
            faults.append(f"{entry} is registered by E0 and not protected")
    if int(config[prune_outputs.KEEP_RECENT_KEY]) != EXPECTED_KEEP_RECENT:
        faults.append(
            f"keep_recent_batches is {config[prune_outputs.KEEP_RECENT_KEY]}, "
            f"not {EXPECTED_KEEP_RECENT}"
        )
    record(
        "check_03a_the_protection_list_covers_what_e0_registers",
        not faults,
        "; ".join(faults[:5]),
    )


def check_03b_no_registered_path_is_ever_selected() -> None:
    """Negative 3b: the policy would not remove a registered path, anywhere.

    Over the real tree, which is the only place the question matters, and over a
    fabricated one where a registered path is deliberately put inside an evicted
    batch directory -- the position that made b8.4's files removable in the first
    place. The registered entry has to survive that position.
    """
    config = prune_outputs.load_config()
    files, directories = prune_outputs.registered_paths(config)
    faults = []
    if not files:
        faults.append("the policy registers no path, so this proves nothing")
    doomed, _recent = prune_outputs.prunable(OUTPUT_DIR, config)
    trespass = sorted(
        path.relative_to(ROOT).as_posix()
        for path in doomed
        if prune_outputs.is_registered(path, files, directories)
    )
    if trespass:
        faults.append(f"would remove registered paths: {trespass[:3]}")

    # The same question with the registered path where it is most exposed: in an
    # evicted batch directory, under a name the keep patterns do not save.
    registered = sorted(files)[0]
    root = Path(tempfile.mkdtemp(prefix="spec_b9_2r_outputs_"))
    try:
        for name in ("b1", "b7_5", "b8"):
            (root / name).mkdir(parents=True)
            (root / name / f"{name}.report.md").write_text("r", encoding="utf-8")
        # Two files in the same exposed position, alike in every way the policy
        # can see except that one is registered. The unregistered one is the
        # control: without it, a policy that had simply stopped selecting
        # anything would pass this.
        planted = root / "b1" / "planted.bin"
        planted.write_bytes(b"0" * 16)
        control = root / "b1" / "control.bin"
        control.write_bytes(b"0" * 16)
        widened = dict(config)
        widened[prune_outputs.PROTECTED_PATHS_KEY] = [
            *config[prune_outputs.PROTECTED_PATHS_KEY],
            str(planted),
        ]
        doomed, _ = prune_outputs.prunable(root, widened)
        selected = {path.name for path in doomed}
        if "planted.bin" in selected:
            faults.append("a registered path inside an evicted batch was selected")
        if "control.bin" not in selected:
            faults.append("the fabricated tree selected nothing at all")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if registered and not Path(registered).exists():
        faults.append(f"the first registered path is not on the disk: {registered}")
    record(
        "check_03b_no_registered_path_is_ever_selected", not faults, "; ".join(faults[:5])
    )


def check_03c_the_archive_holds_the_evicted_batches() -> None:
    """Positive 3c: every evicted batch's small text is in git, in its archive.

    The failure this closes is not the deletion; it is that an evicted batch's
    surviving report and log stayed on the disk untracked, so a clone of this
    repository received none of them. Each archive has to be a readable zip, its
    members have to be named by the subtree they came from, and the whole set
    has to be tracked.
    """
    faults = []
    if not ARCHIVE_DIR.is_dir():
        record(
            "check_03c_the_archive_holds_the_evicted_batches",
            False,
            f"{ARCHIVE_DIR.relative_to(ROOT)} does not exist",
        )
        return
    _, listing = git_output(["ls-files", "--", str(ARCHIVE_DIR)])
    tracked = {line.strip() for line in listing.splitlines() if line.strip()}
    archives = sorted(ARCHIVE_DIR.glob("*.zip"))
    if len(archives) < 5:
        faults.append(f"{len(archives)} archive(s), which is too few to be the sweep's")
    members = 0
    for archive in archives:
        relative = archive.relative_to(ROOT).as_posix()
        if relative not in tracked:
            faults.append(f"{relative} is not tracked")
        if not zipfile.is_zipfile(archive):
            faults.append(f"{relative} is not a zip")
            continue
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            if not names:
                faults.append(f"{relative} is empty")
            for name in names:
                if "/" not in name:
                    faults.append(f"{relative}: member {name} carries no subtree")
            # Readable, not merely present: a zip whose entries cannot be
            # decompressed is the same loss with a file in the way.
            for name in names[:3]:
                if not bundle.read(name) and name.endswith(".log"):
                    faults.append(f"{relative}: member {name} is empty")
        members += len(names)
    if members < 10:
        faults.append(f"{members} archived member(s) across the whole set")

    # And the pass is additive: over an unchanged tree, a second run adds no
    # member and leaves the archive byte for byte, so a sweep that found nothing
    # new produces no diff for the next commit to carry.
    #
    # Asserted on a fabricated tree rather than on the live one, and that is a
    # finding rather than a convenience: the gates of a sweep write into the very
    # batch directories the policy has evicted, and the policy runs after the
    # last gate. Measured live, this assertion reports pending work every time --
    # correctly, since the sweep really has produced newly archivable text that
    # nothing has archived yet.
    config = prune_outputs.load_config()
    root = Path(tempfile.mkdtemp(prefix="spec_b9_2r_archive_"))
    destination = Path(tempfile.mkdtemp(prefix="spec_b9_2r_into_"))
    try:
        for name in ("b1", "b7_5", "b8"):
            (root / name).mkdir(parents=True)
            (root / name / f"{name}.report.md").write_text("r", encoding="utf-8")
        first = prune_outputs.archive_evicted(root, config, True, destination)
        if not first:
            faults.append("the archive pass selected nothing on a tree that has text")
        packed = destination / "b1.zip"
        stamped = packed.read_bytes() if packed.is_file() else b""
        second = prune_outputs.archive_evicted(root, config, True, destination)
        if second:
            faults.append(f"a second pass added: {[members for _, members in second][:2]}")
        if packed.is_file() and packed.read_bytes() != stamped:
            faults.append("a second pass rewrote an archive it added nothing to")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(destination, ignore_errors=True)
    record(
        "check_03c_the_archive_holds_the_evicted_batches", not faults, "; ".join(faults[:5])
    )


def check_03d_the_bulk_is_still_removed() -> None:
    """Negative 3d: archiving did not turn the policy into a keep-everything rule.

    The archive is for small text. A produced PDF, a checkpoint and anything
    over the configured ceiling must still be outside it, or the policy has
    stopped bounding the disk it exists to bound.
    """
    config = prune_outputs.load_config()
    patterns = tuple(config[prune_outputs.ARCHIVE_PATTERNS_KEY])
    ceiling = int(config[prune_outputs.ARCHIVE_MAX_KB_KEY]) * 1024
    faults = []
    root = Path(tempfile.mkdtemp(prefix="spec_b9_2r_bulk_"))
    try:
        for name in ("b1", "b7_5", "b8"):
            (root / name).mkdir(parents=True)
            (root / name / f"{name}.report.md").write_text("r", encoding="utf-8")
        old = root / "b1"
        (old / "product.pdf").write_bytes(b"0" * 4096)
        (old / "checkpoint.01.xml").write_text("<x/>", encoding="utf-8")
        (old / "huge.json").write_bytes(b"0" * (ceiling + 1))
        (old / "small.json").write_text("{}", encoding="utf-8")
        selected = prune_outputs.archivable(root, config)
        names = {
            path.name for paths in selected.values() for path in paths
        }
        for unwanted in ("product.pdf", "checkpoint.01.xml", "huge.json"):
            if unwanted in names:
                faults.append(f"{unwanted} was selected for the archive")
        if "small.json" not in names:
            faults.append("a small sidecar was not selected for the archive")
        doomed, _ = prune_outputs.prunable(root, config)
        removed = {path.name for path in doomed}
        for wanted in ("product.pdf", "checkpoint.01.xml", "huge.json"):
            if wanted not in removed:
                faults.append(f"{wanted} would not be removed")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if "*.pdf" in patterns or "*.xml" in patterns:
        faults.append(f"the archive patterns reach bulk products: {patterns}")
    record("check_03d_the_bulk_is_still_removed", not faults, "; ".join(faults[:5]))


# --- 04 the cache lock ---------------------------------------------------------


def check_04a_a_second_sweep_is_refused() -> None:
    """Negative 4a: while one sweep holds the cache, another will not start.

    A live foreign holder is written into the lock -- a real process, so the
    liveness test has something true to find -- and the acquisition has to raise
    with that holder named. Then the holder is killed and the lock has to become
    free without anybody removing the file, because a sweep that was killed must
    not lock this repository out for the length of the staleness window.

    Run against a temporary cache root rather than the real one, for the reason
    the assertion is about: when the runner performs this gate, the runner is
    itself the sweep holding the real lock, and a test that wrote into it would
    be the concurrent access it exists to forbid.
    """
    faults = []
    probe = Path(tempfile.mkdtemp(prefix="spec_b9_2r_lock_"))
    real_root, real_lock = artifacts.CACHE_ROOT, artifacts.SWEEP_LOCK
    other = subprocess.Popen(  # noqa: S603
        [PYTHON, "-c", "import time; time.sleep(120)"],
        cwd=ROOT,
    )
    try:
        artifacts.CACHE_ROOT = probe
        artifacts.SWEEP_LOCK = probe / real_lock.name
        if artifacts.sweep_lock_holder() is not None:
            faults.append("a fresh cache root reported a holder")
        with artifacts.SWEEP_LOCK.open("w", encoding="utf-8") as f:
            json.dump({"pid": other.pid, "started": time.time()}, f)
        try:
            artifacts.acquire_sweep_lock()
            faults.append("a second sweep acquired the cache")
        except artifacts.SweepInProgress as exc:
            if str(other.pid) not in str(exc):
                faults.append("the refusal does not name the holder")
        if artifacts.sweep_lock_holder() is None:
            faults.append("a live holder read as free")
        # And the race the first version of the lock lost: with no lock on the
        # disk at all, two acquisitions in a row must not both succeed. The
        # exclusive create is what makes the second one see a file.
        artifacts.SWEEP_LOCK.unlink()
        with contextlib.suppress(artifacts.SweepInProgress):
            first = subprocess.Popen(  # noqa: S603
                [PYTHON, "-c", "import time; time.sleep(120)"],
                cwd=ROOT,
            )
            try:
                handle = os.open(
                    artifacts.SWEEP_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                with os.fdopen(handle, "w", encoding="utf-8") as f:
                    json.dump({"pid": first.pid, "started": time.time()}, f)
                try:
                    artifacts.acquire_sweep_lock()
                    faults.append("an exclusively created lock did not refuse a second")
                except artifacts.SweepInProgress:
                    pass
            finally:
                first.kill()
                first.wait()
        with artifacts.SWEEP_LOCK.open("w", encoding="utf-8") as f:
            json.dump({"pid": other.pid, "started": time.time()}, f)
        other.kill()
        other.wait()
        if artifacts.sweep_lock_holder() is not None:
            faults.append("a dead holder still holds the cache")
        artifacts.acquire_sweep_lock()
        artifacts.release_sweep_lock()
        if artifacts.SWEEP_LOCK.exists():
            faults.append("releasing the lock left it on the disk")
    finally:
        artifacts.CACHE_ROOT, artifacts.SWEEP_LOCK = real_root, real_lock
        if other.poll() is None:
            other.kill()
            other.wait()
        shutil.rmtree(probe, ignore_errors=True)
    record("check_04a_a_second_sweep_is_refused", not faults, "; ".join(faults))


def check_04b_the_runner_takes_the_lock_before_anything() -> None:
    """Positive 4b: the sweep claims the cache before it clears or builds.

    Order is the assertion. A sweep that took the lock after clearing statistics
    or trimming the cache would already have written into a running sweep's
    state by the time it discovered it should not have started, and the same
    goes for the completion marker a caller polls.
    """
    tree = ast.parse(text_of(RUNNER))
    main = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        ),
        None,
    )
    faults = []
    if main is None:
        record(
            "check_04b_the_runner_takes_the_lock_before_anything",
            False,
            "the runner has no main",
        )
        return
    body = ast.unparse(main).splitlines()
    acquired = [i for i, line in enumerate(body) if "acquire_sweep_lock()" in line]
    if not acquired:
        faults.append("the runner never claims the cache")
    if "release_sweep_lock" not in ast.unparse(main):
        faults.append("the runner never gives the cache back")
    for later in ("clear_stats", "govern_cache", "write_done", "run_gate("):
        positions = [i for i, line in enumerate(body) if later in line]
        if positions and acquired and min(positions) < min(acquired):
            faults.append(f"{later} runs before the lock is taken")
    record(
        "check_04b_the_runner_takes_the_lock_before_anything", not faults, "; ".join(faults)
    )


def check_04c_no_interrupted_build_is_still_on_the_disk() -> None:
    """Negative 4c: the cache holds no staging directory nobody is building in.

    One was found holding 270 MB when this batch opened, kept alive by a lock
    whose process had been gone for weeks: the staleness window was the only
    test, and it is a day long. With the pid test in place such a directory is
    reclaimable immediately, and this asserts there is none left.
    """
    faults = []
    artifacts.drop_abandoned()
    remaining = artifacts.abandoned_staging()
    if remaining:
        faults.append(f"abandoned staging directories: {[p.name for p in remaining]}")
    # And the mechanism that finds them: a staging directory whose lock names a
    # pid that is gone must be abandoned, whatever its timestamp says. Probed
    # outside the cache root, so a sweep running this gate does not find a
    # fabricated staging directory in its own cache.
    root = Path(tempfile.mkdtemp(prefix="spec_b9_2r_staging_"))
    staging = root / f"probe{artifacts.STAGING_SUFFIX}"
    try:
        staging.mkdir(parents=True, exist_ok=True)
        with (staging / artifacts.STAGING_LOCK).open("w", encoding="utf-8") as f:
            json.dump({"pid": 2, "started": time.time()}, f)
        if artifacts._lock_is_live(staging):
            faults.append("a lock naming a dead pid read as a live build")
        with (staging / artifacts.STAGING_LOCK).open("w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "started": time.time()}, f)
        if not artifacts._lock_is_live(staging):
            faults.append("this process's own build read as abandoned")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    record(
        "check_04c_no_interrupted_build_is_still_on_the_disk", not faults, "; ".join(faults)
    )


# --- 05 scope, registration and the convention ---------------------------------


def check_05a_no_upstream_no_ground_truth_no_ruling() -> None:
    """Negative 5a: a recovery batch touches documents, tools and gates.

    Nothing under babeldoc/, so no pipeline behaviour moved and the evidence
    this batch is reasoning about is still the evidence it was produced from;
    nothing under corpus/ or reviews/, which are the corpus owner's.
    """
    changed = changed_paths()
    faults = []
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    if stray:
        faults.append(f"outside the declared paths: {stray[:5]}")
    for prefix in FORBIDDEN_PREFIXES:
        touched = sorted(path for path in changed if path.startswith(prefix))
        if touched:
            faults.append(f"{prefix} changed: {touched[:3]}")
    record("check_05a_no_upstream_no_ground_truth_no_ruling", not faults, "; ".join(faults))


def check_05b_the_runner_registers_this_gate() -> None:
    """Positive 5b: the sweep runs this gate, and runs it after the batch gates."""
    source = text_of(RUNNER)
    name = Path(__file__).name
    faults = []
    listed = re.findall(r'"(spec_check_[a-z0-9_]+\.py)"', source)
    if name not in listed:
        faults.append("run_all.py does not list this gate")
    else:
        position = listed.index(name)
        for earlier in ("spec_check_e0.py", "spec_check_e1.py", "spec_check_e2.py"):
            if earlier in listed and listed.index(earlier) > position:
                faults.append(f"{earlier} runs after this gate")
    record("check_05b_the_runner_registers_this_gate", not faults, "; ".join(faults))


def check_05c_the_convention_is_in_claude_md_and_pinned() -> None:
    """Positive 5c: the rule this batch installed is written where sessions read it.

    A mechanism with no clause behind it is a mechanism the next session may
    reasonably remove. The clause is pinned by digest and by the terms it has to
    keep naming, so a rewrite that dropped the archive or the protection list
    would be caught here rather than two batches later by another loss.
    """
    clause = clause_text()
    faults = []
    if clause is None:
        record(
            "check_05c_the_convention_is_in_claude_md_and_pinned",
            False,
            f"CLAUDE.md carries no clause {CLAUSE_NUMBER}",
        )
        return
    for anchor in CLAUSE_ANCHORS:
        if anchor not in clause:
            faults.append(f"the clause does not name {anchor}")
    digest = hashlib.sha256(clause.encode("utf-8")).hexdigest()
    if CLAUSE_DIGEST and digest != CLAUSE_DIGEST:
        faults.append(f"the clause digest is {digest[:16]}, pinned {CLAUSE_DIGEST[:16]}")
    if not CLAUSE_DIGEST:
        faults.append(f"the clause is not pinned; its digest is {digest}")
    record(
        "check_05c_the_convention_is_in_claude_md_and_pinned", not faults, "; ".join(faults)
    )


def check_05d_ascii_prose_in_the_gate() -> None:
    """Negative 5d: this gate carries no non-ASCII prose.

    The documents it reads are in the project's working language; the code that
    reads them is not, and the one term it does name -- the status this batch
    adds -- was chosen in ASCII for that reason.
    """
    faults = []
    for number, line in enumerate(text_of(Path(__file__)).splitlines(), start=1):
        if not line.isascii():
            offenders = [
                unicodedata.name(char, hex(ord(char)))
                for char in line
                if not char.isascii()
            ]
            faults.append(f"line {number}: {offenders[:3]}")
    record("check_05d_ascii_prose_in_the_gate", not faults, "; ".join(faults[:5]))


def check_05e_the_gate_spends_nothing() -> None:
    """Negative 5e: no pipeline, no translator, no credential.

    A recovery batch that could build a pipeline artefact could also produce a
    substitute for the artefacts that were lost, which is the one thing the
    downgrade in 01 exists to refuse.
    """
    source = text_of(Path(__file__))
    faults = []
    for forbidden in ("translator", "openai", "high_level", "doclayout"):
        if re.search(rf"^\s*(import|from)\s+.*{forbidden}", source, re.MULTILINE):
            faults.append(f"imports {forbidden}")
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    if suffix in source.replace('"_API" + "_KEY"', ""):
        faults.append("names a credential variable")
    record("check_05e_the_gate_spends_nothing", not faults, "; ".join(faults))


def check_06_sweep() -> None:
    """Positive 6: every gate passes, this one included."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_06_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(RUNNER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_06_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01a_the_four_rows_carry_the_pruned_status,
        check_01b_the_gap_register_answers_for_all_four,
        check_01c_the_retired_paths_are_registered_and_absent,
        check_02a_the_accident_now_refuses,
        check_02b_the_evaluation_gates_write_no_frozen_file,
        check_02c_a_removed_dependency_still_writes_nothing,
        check_02d_no_gate_names_a_frozen_directory_as_an_output,
        check_02e_the_runner_digests_the_record_around_every_gate,
        check_03a_the_protection_list_covers_what_e0_registers,
        check_03b_no_registered_path_is_ever_selected,
        check_03c_the_archive_holds_the_evicted_batches,
        check_03d_the_bulk_is_still_removed,
        check_04a_a_second_sweep_is_refused,
        check_04b_the_runner_takes_the_lock_before_anything,
        check_04c_no_interrupted_build_is_still_on_the_disk,
        check_05a_no_upstream_no_ground_truth_no_ruling,
        check_05b_the_runner_registers_this_gate,
        check_05c_the_convention_is_in_claude_md_and_pinned,
        check_05d_ascii_prose_in_the_gate,
        check_05e_the_gate_spends_nothing,
        check_06_sweep,
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
    print(f"\nspec_check_b9_2r: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_b9_2r")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
