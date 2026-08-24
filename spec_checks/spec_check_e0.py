"""Gate script for batch E0 (the evaluation-phase inventory).

Run from the repository root:

    python spec_checks/spec_check_e0.py

Exit code 0 when every assertion E0 answers for passes, 1 otherwise. Needs no
API key, makes no network request and runs no pipeline: E0 delivers three
documents and nothing else, so every assertion here is a static read of those
documents and of the files they cite.

01 is presence and shape: the three documents exist, and every ledger row
carries a citable path, a provenance token and a status drawn from the
document's own declared vocabulary. The vocabularies are read out of the ledger
rather than written here, so this file states no term of a language it does not
otherwise use.

02 is the soul of the batch: zero tolerance for a dead link. Every repository
path any of the three documents cites must exist. A ledger whose citations do
not resolve is worse than no ledger, because it reads as evidence.

02b is the same question asked of durability rather than of existence. The
evidence the ledger stands on falls into two tiers, and the tiers are asserted
differently because they survive differently. What is tracked is asserted to be
tracked, so a clone carries it; what is deliberately not tracked -- the six
produced baseline PDFs, kept out by size -- is asserted by an explicit list of
path and SHA-256, which is the only durable statement that can be made about a
file a clone will not receive.

03 is its negative twin. The ledger carries a bounded register of artefacts that
were retired by the output retention policy, and every path inside that register
must NOT exist. If one comes back, the register is wrong and the entries that
depend on it were mis-classified.

04 is the metric contract against the background chapter: every ``eq:`` label
the contract cites must resolve to a ``\\label{...}`` in the chapter source.

05 is cross-closure between the ledger and the gap register: every ledger row
the ledger classifies as needing a recomputation or a three-run design is named
in the gap register, and every ledger id the gap register names exists. The two
documents are a contract only if they close over each other.

06 is the ledger discipline made mechanical. A sample of the headline numbers is
grepped out of the file each row cites, which is what "read the number back from
its source" means when a machine does it. This is the assertion that fails when
a number is transcribed from memory.

07 is the scope: this batch touches documentation and its own gate, and nothing
else. Working-tree state that predates the batch is named explicitly rather than
tolerated by a loose pattern, and it is consulted only while the batch tag does
not yet exist; once tagged, the delta is the tag's own.

Every assertion is static. There is no pipeline tier.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build:
# every document it asserts on is a stub it builds itself or evidence a
# batch froze, so it answers in seconds to a couple of minutes and runs on
# every batch.
GATE_SET = "fast"

BATCH_TAG = "batch-e0"

PYTHON = sys.executable

EVAL_DIR = ROOT / "docs" / "eval"
LEDGER = EVAL_DIR / "evidence_ledger.md"
CONTRACT = EVAL_DIR / "metric_contract.md"
GAPS = EVAL_DIR / "gap_register.md"
DOCUMENTS = (LEDGER, CONTRACT, GAPS)

CHAPTER = ROOT / "docs" / "dissertation" / "background_chapter.tex"

# The retired-artefact register, delimited so a reader and this gate agree on
# where it starts and ends without either parsing prose.
ABSENT_BEGIN = "<!-- absent-paths:begin -->"
ABSENT_END = "<!-- absent-paths:end -->"

# The two vocabularies the ledger declares for itself, as marked comments. Read
# from the document so the terms live in one place only.
STATUS_MARKER = "status-vocabulary:"
PROVENANCE_MARKER = "provenance-vocabulary:"

# A ledger row identifier: a group letter and a number, as the ledger's first
# column writes them.
ROW_ID = re.compile(r"^([A-G])-(\d+)$")

# Anything inside backticks. A citation is one of these that looks like a
# repository path; the rest are field names, identifiers and quoted values.
BACKTICKED = re.compile(r"`([^`\n]+)`")

# A repository path: one of the top level directories this project declares in
# CLAUDE.md section 3, followed by a separator. Line anchors are written outside
# the backticks precisely so they do not have to be stripped here.
PATH_ROOTS = (
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

# Files that sit at the repository root and carry no separator to recognise them
# by. They are citations like any other and a dead one is as bad.
ROOT_FILES = (
    "CLAUDE.md",
    "README.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "pyproject.toml",
)

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Batch gates the runner deliberately places after this one. The recovery batch
# b9.2r asserts about this gate and about the two that follow it -- it runs them
# and reads their output -- so it cannot precede them, and it produces no
# artefact any citation here resolves to. Batch b9.3 follows it for the ordering
# reason alone: it builds every document it asserts on, cites nothing this gate
# inventories, and its own coverage of the read-only guard is over the state
# b9.2r established. Batch b9.4 follows for the same reason: its documents are
# built in its own file, the frozen artefacts it reads are its batch's and the
# corpus run's, and it cites nothing this gate inventories. Batch b9.5 follows on
# the same terms: its documents and its repair loop are built inside its own
# file, and the two documents it does read under docs/eval it reads as prose
# this gate already holds to its own rules. Batch b9.6 follows on those terms
# too: it asserts over the decision records its own batch froze and reads one
# document under docs/eval as prose, and cites nothing this gate inventories.
# Batch b9.7 follows on the same terms again: its evidence is the decision
# records its own batch froze, the fixtures it reads belong to b9.5 and b9.6,
# and it reads no document under docs/eval at all. Batch b10.1 follows on the
# same terms once more: its evidence is the replay its own batch froze under
# examples/output/b10_1 and the F2 run beside it, and it reads no document under
# docs/eval. Batch b10.2 follows on the same terms as the one before it: its
# evidence is the replay its own batch froze under examples/output/b10_2 and the
# collision census batch b9.5 froze beside it, both of which it reads rather than
# produces for anybody here, and it reads no document under docs/eval at all.
# Batch b10.3 follows on the same terms: its evidence is the replay its own batch
# froze under examples/output/b10_3 and the F2 run it compares against, it reads
# no document under docs/eval, and it produces nothing this gate inventories.
# Batch b10.4 follows on the same terms once more: its evidence is the run its own
# batch froze under examples/output/b10_4, the b10.3 sidecars it compares two
# record pages against, and the F2 ledger it reads the frozen policy digest from.
# It reads no document under docs/eval and produces nothing this gate inventories.
# Batch b10.5 follows on the same terms again: its evidence is the pair of runs
# its own batch froze under examples/output/b10_5, every other assertion it makes
# is against a stub it builds itself, and it reads no document under docs/eval.
# Batch b11.1 follows on the same terms once more: its evidence is the single
# sample run its own batch froze under examples/output/b11_1 and the f3 run it
# compares that against, every other assertion it makes is against a stub it
# builds itself, and it reads no document under docs/eval.
AFTER_THIS_GATE = (
    "spec_check_b9_2r.py",
    "spec_check_b9_3.py",
    "spec_check_b9_4.py",
    "spec_check_b9_5.py",
    "spec_check_b9_6.py",
    "spec_check_b9_7.py",
    "spec_check_b10_1.py",
    "spec_check_b10_2.py",
    "spec_check_b10_3.py",
    "spec_check_b10_4.py",
    "spec_check_b10_5.py",
    "spec_check_b11_1.py",
    "spec_check_b11_2.py",
    "spec_check_b11_3.py",
    "spec_check_b11_6.py",
)

# Paths this batch may change. Nothing under babeldoc/, nothing under configs/,
# nothing under corpus/ or reviews/: E0 is an inventory and writes documents.
ALLOWED_PREFIXES = ("docs/eval/",)
ALLOWED_FILES = {
    "plans/PLAN_E0.md",
    "spec_checks/spec_check_e0.py",
    "spec_checks/run_all.py",
}

# Working-tree state this batch found already present and did not produce. It is
# ignored only on the branch that compares against HEAD, which is the state
# before the batch is tagged; the tagged delta contains what was committed and
# nothing else, so this set stops mattering the moment the tag exists.
PRE_EXISTING_PREFIXES = (
    "docs/dissertation/",
    "docs/dissertation_assets/",
    "examples/baseline/",
)
PRE_EXISTING_FILES = {
    "examples/ci/test.pdf",
    "examples/output/b8/corpus_detection.json",
}

# The evidence intake decided under gap register GAP-07, tier one: what a clone
# receives. Directories stand for every file below them.
TRACKED_EVIDENCE = (
    "docs/dissertation/background_chapter.tex",
    "examples/baseline/manifest.json",
    "examples/baseline/baseline.report.md",
    "examples/baseline/integrity/tree_sha256_before.txt",
    "examples/baseline/integrity/tree_sha256_after.txt",
    "examples/baseline/logs/",
    "examples/baseline/cache/cache.v1.db",
    "examples/output/vlm_ablation/gpt-4o/vlm_eval.report.json",
    "examples/output/vlm_ablation/gpt-4o/vlm_eval.summary.txt",
    "examples/output/vlm_ablation/gpt-4o-mini/vlm_eval.report.json",
    "examples/output/vlm_ablation/gpt-4o-mini/vlm_eval.summary.txt",
    "examples/output/vlm_ablation/gpt-5.6-sol/vlm_eval.report.json",
    "examples/output/vlm_ablation/gpt-5.6-sol/vlm_eval.summary.txt",
    "examples/output/vlm_ablation/gpt-5.6-terra/vlm_eval.report.json",
    "examples/output/vlm_ablation/gpt-5.6-terra/vlm_eval.summary.txt",
    "examples/output/b4/run_all.b4_2.final.log",
    "examples/output/b2_7/run_all.full.log",
    "examples/output/run_all.b8_3.log",
)

# Tier two: the produced baseline PDFs, kept out of git by size. Each is named
# with the digest recorded for it in the baseline manifest, which is tracked, so
# a workspace copy that drifted from what the manifest describes is caught here
# rather than at the point somebody measures it.
WORKSPACE_EVIDENCE = (
    (
        "examples/baseline/pdf/Courier-en/Courier-en.no_watermark.zh.mono.pdf",
        "d78d442beb91d63450ffc354a50b04fecb9b24585490bc6f6708734b79faf688",
    ),
    (
        "examples/baseline/pdf/Vogue-en/Vogue-en.no_watermark.zh.mono.pdf",
        "b4e9ad6dcd9f2928f2cfab6280ee4afcaaab3a6c30554aa1f8f49da3ceebb086",
    ),
    (
        "examples/baseline/pdf/CERNCourier-en/CERNCourier-en.no_watermark.zh.mono.pdf",
        "c78bce91b62018f9162c40c31798e64023f6d65dc2818fe2ac77f5eeacbe6a54",
    ),
    (
        "examples/baseline/pdf/AramcoWorld-en-v2/"
        "AramcoWorld-en-v2.no_watermark.zh.mono.pdf",
        "9d45fc58f62a1634c6684f8f341fb3fd6ef725f2f586fd024704ad0c8adf0ba2",
    ),
    (
        "examples/baseline/pdf/FD-en-v2/FD-en-v2.no_watermark.zh.mono.pdf",
        "7b2d99895be0f37ace61a9879c06142b4d6d9e2d3ce50b16fa2411cbacc6943f",
    ),
    (
        "examples/baseline/pdf/Courier-zh/Courier-zh.no_watermark.en.mono.pdf",
        "71ca4c37ea0990a4a4dadb3d33db9e85dc5844213bbf371bccdbd7e3e2cd5aeb",
    ),
)

# The ledger discipline, sampled. Each entry is a row id, the number as the
# ledger writes it, and the file the row cites for it. The needle is matched
# against the file's text, so a transcription error fails here.
SAMPLED_NUMBERS = (
    ("A-01", "1.000 (26/26)", "examples/output/b4/run_all.b4_2.final.log"),
    ("A-02", "1.000 (28/28)", "examples/output/run_all.b8_3.log"),
    ("A-06", "826", "examples/output/b5_smoke/smoke.report.md"),
    ("A-08", "471.28", "examples/output/b5_smoke/smoke.report.md"),
    ("A-10", "0.0289", "examples/output/b5_smoke/smoke.report.md"),
    ("A-14", "34 853", "examples/output/b5_smoke/smoke.report.md"),
    ("B-01", "overall: 28/31", "examples/output/b2_7/run_all.full.log"),
    ("B-04", "0.879 (29/33)", "examples/output/run_all.b8_3.log"),
    ("B-06", "page kind 2/8, boundaries 5/7", "examples/output/run_all.b8_3.log"),
    ("B-07", "4.286", "examples/output/b7_5/refresh.report.md"),
    ("C-01", '"rate": 0.9032', "examples/output/vlm_ablation/gpt-4o/vlm_eval.report.json"),
    ("D-06", '"auto_glossary_kept": 141', "examples/output/b7_3/smoke.report.md"),
    ("D-09", "123 prompts", "examples/output/b7_5/refresh.report.md"),
    ("E-01", "0.630", "examples/output/b8/smoke.report.md"),
    ("E-02", "d06294a6b05e9374", "examples/output/b8/smoke.report.md"),
    ("E-04", "229 462", "examples/output/b8/smoke.report.md"),
    ("E-06", '"box_held": true', "examples/output/b8_4/smoke/evidence.json"),
    ("E-11", "30 635", "examples/output/b8_4/smoke.report.md"),
    ("F-01", "801.4", "examples/baseline/manifest.json"),
    ("F-03", "415", "examples/baseline/manifest.json"),
    ("G-01", "0.995", "examples/output/b5_smoke/smoke.report.md"),
)

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_e0")


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


def tracked_paths() -> set[str]:
    """Every path the index holds, which is what a clone would receive."""
    _, listing = git_output(["ls-files"])
    return {line.strip() for line in listing.splitlines() if line.strip()}


def digest_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def looks_like_path(token: str) -> bool:
    return token.startswith(PATH_ROOTS) or token in ROOT_FILES


def absent_block(document: str) -> str:
    """The retired-artefact register of the ledger, or an empty string."""
    if ABSENT_BEGIN not in document or ABSENT_END not in document:
        return ""
    start = document.index(ABSENT_BEGIN) + len(ABSENT_BEGIN)
    return document[start : document.index(ABSENT_END)]


def cited_paths(document: str) -> list[str]:
    """Every repository path a document cites outside the retired register."""
    block = absent_block(document)
    body = document.replace(block, "") if block else document
    return [token for token in BACKTICKED.findall(body) if looks_like_path(token)]


def vocabulary(document: str, marker: str) -> set[str]:
    """The backticked terms of one declared vocabulary comment."""
    for line in document.splitlines():
        if marker in line:
            return set(BACKTICKED.findall(line))
    return set()


def ledger_rows(document: str) -> list[tuple[str, list[str]]]:
    """Every ledger table row, as its identifier and its cells."""
    rows = []
    for line in document.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and ROW_ID.match(cells[0]):
            rows.append((cells[0], cells))
    return rows


# --- 01 presence and shape ----------------------------------------------------


def check_01a_the_three_documents_exist() -> None:
    """Positive 1a: E0's whole delivery is present and is not a stub."""
    faults = []
    for path in DOCUMENTS:
        if not path.is_file():
            faults.append(f"missing {path.relative_to(ROOT)}")
            continue
        if len(text_of(path)) < 2000:
            faults.append(f"{path.relative_to(ROOT)} is too short to be the document")
    record("check_01a_the_three_documents_exist", not faults, "; ".join(faults))


def check_01b_every_ledger_row_carries_its_provenance() -> None:
    """Positive 1b: a row cites a path, states where it lives and states a status.

    The three vocabularies are the ledger's own declarations, read back out of
    it. A row that cites no path is a number without a source, which is the one
    thing this document exists to make impossible.
    """
    document = text_of(LEDGER)
    statuses = vocabulary(document, STATUS_MARKER)
    provenances = vocabulary(document, PROVENANCE_MARKER)
    rows = ledger_rows(document)
    faults = []
    if not statuses:
        faults.append("the ledger declares no status vocabulary")
    if not provenances:
        faults.append("the ledger declares no provenance vocabulary")
    if len(rows) < 40:
        faults.append(f"only {len(rows)} ledger row(s) parsed")
    for identifier, cells in rows:
        row = " | ".join(cells)
        if not [token for token in BACKTICKED.findall(row) if looks_like_path(token)]:
            faults.append(f"{identifier}: cites no repository path")
        if not any(re.search(rf"\b{term}\b", row) for term in provenances):
            faults.append(f"{identifier}: states no provenance")
        if not any(term in cells[-1] for term in statuses):
            faults.append(f"{identifier}: status {cells[-1]!r} is outside the vocabulary")
    record(
        "check_01b_every_ledger_row_carries_its_provenance",
        not faults,
        "; ".join(faults[:5]),
    )


def check_01c_the_status_summary_agrees_with_the_rows() -> None:
    """Positive 1c: the summary counts what the tables actually hold.

    A row is counted under whichever status word appears first in its status
    cell, which is the rule the ledger states for itself. The summary is a table
    of ``| term | count | ...`` rows, so the count is read from the cell beside
    the term rather than from prose.
    """
    document = text_of(LEDGER)
    statuses = vocabulary(document, STATUS_MARKER)
    counted: dict[str, int] = dict.fromkeys(statuses, 0)
    rows = ledger_rows(document)
    faults = []
    for identifier, cells in rows:
        cell = cells[-1]
        first = min(
            ((cell.index(term), term) for term in statuses if term in cell),
            default=None,
        )
        if first is None:
            faults.append(f"{identifier}: no status word")
            continue
        counted[first[1]] += 1

    declared: dict[str, int] = {}
    for line in document.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        for term in statuses:
            if cells[0].strip("* `") == term and cells[1].isdigit():
                declared[term] = int(cells[1])
    if set(declared) != set(statuses):
        faults.append(f"the summary declares {sorted(declared)} of {sorted(statuses)}")
    for term, count in sorted(declared.items()):
        if counted.get(term) != count:
            faults.append(f"{term}: summary says {count}, tables hold {counted.get(term)}")
    if sum(declared.values()) != len(rows):
        faults.append(f"summary totals {sum(declared.values())} against {len(rows)} rows")
    record(
        "check_01c_the_status_summary_agrees_with_the_rows",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 02 the soul assertion ----------------------------------------------------


def check_02_no_dead_link() -> None:
    """Positive 2: every path the three documents cite exists.

    Zero tolerance, and deliberately not scoped to the ledger: a metric contract
    naming a tool that is not there, or a gap register naming a config that was
    renamed, is the same failure. Directories count as existing, since some
    citations are of a directory as a whole.
    """
    faults = []
    for path in DOCUMENTS:
        for token in cited_paths(text_of(path)):
            if not (ROOT / token).exists():
                faults.append(f"{path.name} -> {token}")
    record("check_02_no_dead_link", not faults, f"{len(faults)} dead: {faults[:8]}")


def check_02b_the_evidence_is_tiered() -> None:
    """Positive 2b: the durable tier is tracked, the rest is named with its digest.

    Two assertions rather than one, because the two tiers fail differently. A
    file in the first tier that is not in the index is evidence one clone away
    from being lost, which is the whole of GAP-07. A file in the second tier is
    known not to travel; what can still be asserted is that the copy standing
    here is the copy the manifest describes, so it is named by path and digest
    and both are checked. A second-tier file that turned up in the index is a
    failure too: the tiers are a decision, not an accident, and a twelve
    megabyte PDF entering git silently is how a repository stops being cloneable.
    """
    tracked = tracked_paths()
    faults = []
    for entry in TRACKED_EVIDENCE:
        if entry.endswith("/"):
            if not any(path.startswith(entry) for path in tracked):
                faults.append(f"{entry} holds nothing tracked")
            continue
        if entry not in tracked:
            faults.append(f"{entry} is not tracked")
    for relative, expected in WORKSPACE_EVIDENCE:
        if relative in tracked:
            faults.append(f"{relative} is tracked and the tiering says it is not")
        path = ROOT / relative
        if not path.is_file():
            faults.append(f"{relative} is absent from the workspace")
            continue
        actual = digest_of(path)
        if actual != expected:
            faults.append(f"{relative}: sha256 {actual[:16]} against {expected[:16]}")
    record("check_02b_the_evidence_is_tiered", not faults, "; ".join(faults[:6]))


def check_03_the_retired_register_is_actually_retired() -> None:
    """Negative 3: every path in the retired register is absent from the tree.

    The register exists so that entries depending on a vanished artefact are
    classified honestly. A path that came back invalidates that classification,
    so its presence is a failure of the ledger rather than good news.
    """
    document = text_of(LEDGER)
    block = absent_block(document)
    faults = []
    if not block.strip():
        faults.append("the ledger carries no retired-artefact register")
    listed = [token for token in BACKTICKED.findall(block) if looks_like_path(token)]
    if len(listed) < 5:
        faults.append(f"the register lists only {len(listed)} path(s)")
    for token in listed:
        if (ROOT / token).exists():
            faults.append(f"{token} is in the tree but is registered as retired")
    record(
        "check_03_the_retired_register_is_actually_retired",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 04 the metric contract against the chapter --------------------------------


def check_04_every_equation_label_resolves() -> None:
    """Positive 4: every ``eq:`` label the contract cites is in the chapter.

    The contract's whole value is that a metric's definition has one home. A
    label that does not resolve means the contract points at nothing, which is
    the documentation form of a dead link.
    """
    faults = []
    if not CHAPTER.is_file():
        record(
            "check_04_every_equation_label_resolves",
            False,
            f"the background chapter is not at {CHAPTER.relative_to(ROOT)}",
        )
        return
    chapter = text_of(CHAPTER)
    labels = {
        match.group(1)
        for match in re.finditer(r"\\label\{(eq:[^}]+)\}", chapter)
    }
    cited = {
        token
        for token in BACKTICKED.findall(text_of(CONTRACT))
        if token.startswith("eq:")
    }
    if not cited:
        faults.append("the contract cites no equation label at all")
    for token in sorted(cited - labels):
        faults.append(f"{token} resolves to nothing in the chapter")
    record("check_04_every_equation_label_resolves", not faults, "; ".join(faults))


# --- 05 cross-closure ----------------------------------------------------------


def check_05_the_ledger_and_the_gap_register_close_over_each_other() -> None:
    """Positive 5: the open items of one document are the subject of the other.

    Every row the ledger says cannot be cited as it stands has to be answered
    somewhere in the gap register, and every row identifier the gap register
    names has to exist in the ledger. Without both directions the two documents
    can drift apart while each stays internally consistent.
    """
    document = text_of(LEDGER)
    statuses = vocabulary(document, STATUS_MARKER)
    # The open statuses are those that are not the plainly citable one, which is
    # identified structurally: it is the status the summary counts most of.
    rows = ledger_rows(document)
    tally = {term: 0 for term in statuses}
    classified: dict[str, str] = {}
    for identifier, cells in rows:
        cell = cells[-1]
        found = min(
            ((cell.index(term), term) for term in statuses if term in cell),
            default=None,
        )
        if found is None:
            continue
        tally[found[1]] += 1
        classified[identifier] = found[1]
    citable = max(tally, key=lambda term: tally[term])
    open_rows = sorted(
        identifier for identifier, term in classified.items() if term != citable
    )

    gaps = text_of(GAPS)
    faults = []
    # This used to require at least one open row, on the reasoning that a ledger
    # with none had stopped parsing. Batch E2 closed the last three, so the
    # premise is now the classification itself: every row has to carry a word
    # from the declared vocabulary. A vocabulary that stopped matching leaves
    # rows unclassified and still fails here; a ledger with nothing open no
    # longer does, because that is a state this project can reach. See W-E2-02.
    unclassified = sorted(
        identifier for identifier, _ in rows if identifier not in classified
    )
    if not classified:
        faults.append("no ledger row carries a status, so the vocabulary did not parse")
    elif unclassified:
        faults.append(f"rows carrying no declared status: {unclassified}")
    for identifier in open_rows:
        if identifier not in gaps:
            faults.append(f"{identifier} is open in the ledger and absent from the gaps")
    known = {identifier for identifier, _ in rows}
    for match in re.finditer(r"\b([A-G]-\d+)\b", gaps):
        if match.group(1) not in known:
            faults.append(f"the gap register names {match.group(1)}, which has no row")

    # The other direction, added in E2: a ledger row that answers to a gap has
    # to name a gap the register actually carries. Rows now cite gaps by number
    # for their citable wording -- a mistyped or retired number would otherwise
    # send a reader to a section that is not there.
    registered = set(re.findall(r"^#+\s*(GAP-\d+)", gaps, re.M))
    for cited in sorted(set(re.findall(r"\bGAP-\d+\b", document))):
        if cited not in registered:
            faults.append(f"the ledger cites {cited}, which the register has no section for")

    # And the summary has to be the rows. The ledger states its own tallies in
    # prose and in a table; recomputing them here is what keeps a row added at
    # the bottom from being invisible in the counts a reader quotes.
    for status, counted in tally.items():
        stated = re.search(
            rf"^\|\s*{re.escape(status)}\s*\|\s*(\d+)\s*\|", document, re.M
        )
        if stated is None:
            faults.append(f"the summary does not count the {status} rows")
        elif int(stated.group(1)) != counted:
            faults.append(
                f"the summary counts {stated.group(1)} {status} rows, recomputed {counted}"
            )
    groups: dict[str, int] = {}
    for identifier in classified:
        groups[identifier[0]] = groups.get(identifier[0], 0) + 1
    # The ledger is written in Chinese and this file is ASCII, so the phrases
    # the tally is stated under are escapes: the heading "group row count", the
    # counter word the total is written with, and the full width colon.
    group_line = "\u5206\u7ec4\u884c\u6570"
    counter = "\u6761"
    stated_groups = re.search(rf"{group_line}[:\uff1a]([^\n]*)", document)
    if stated_groups is None:
        faults.append("the ledger states no group tally")
    else:
        pairs = dict(re.findall(r"([A-G])\s*(\d+)", stated_groups.group(1)))
        for group, counted in sorted(groups.items()):
            if int(pairs.get(group, -1)) != counted:
                faults.append(
                    f"group {group}: the summary says {pairs.get(group)}, recomputed {counted}"
                )
        total = re.search(rf"(\d+)\s*{counter}", stated_groups.group(1))
        if total is None or int(total.group(1)) != len(classified):
            faults.append(
                f"the summary total is {None if total is None else total.group(1)}, "
                f"recomputed {len(classified)}"
            )
    record(
        "check_05_the_ledger_and_the_gap_register_close_over_each_other",
        not faults,
        "; ".join(sorted(set(faults))[:6]),
    )


# --- 06 the ledger discipline, mechanised --------------------------------------


def check_06_sampled_numbers_are_in_the_files_they_cite() -> None:
    """Positive 6: a sample of the ledger's numbers is read back from its source.

    This is the assertion that makes the ledger a ledger. Each sampled row names
    a file and a number, and the number has to occur in that file. A number
    transcribed from a previous session's summary rather than read out of the
    artefact fails here, which is exactly the discipline E0 exists to install.
    """
    document = text_of(LEDGER)
    rows = dict(ledger_rows(document))
    faults = []
    for identifier, needle, relative in SAMPLED_NUMBERS:
        if identifier not in rows:
            faults.append(f"{identifier}: no such ledger row")
            continue
        row = " | ".join(rows[identifier])
        if relative not in row:
            faults.append(f"{identifier}: the row does not cite {relative}")
        source = ROOT / relative
        if not source.is_file():
            faults.append(f"{identifier}: {relative} is not a file")
            continue
        try:
            body = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            faults.append(f"{identifier}: {relative} unreadable ({exc})")
            continue
        if needle not in body:
            faults.append(f"{identifier}: {needle!r} is not in {relative}")
    record(
        "check_06_sampled_numbers_are_in_the_files_they_cite",
        not faults,
        "; ".join(faults[:6]),
    )


# --- 07 the scope --------------------------------------------------------------


def check_07a_no_code_and_no_configuration_changed() -> None:
    """Negative 7a: the batch writes documents, its own gate and the runner.

    Nothing under babeldoc/, configs/, prompts/, corpus/ or reviews/. The
    ground truth, the rulings and the frozen baseline are read-only for an
    inventory batch, and a diff touching any of them means the inventory
    modified what it was counting.
    """
    changed = changed_paths()
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES
        and not path.startswith(ALLOWED_PREFIXES)
        and path not in PRE_EXISTING_FILES
        and not path.startswith(PRE_EXISTING_PREFIXES)
    )
    faults = []
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    for prefix in ("babeldoc/", "configs/", "prompts/", "corpus/", "reviews/"):
        touched = sorted(path for path in changed if path.startswith(prefix))
        if touched:
            faults.append(f"{prefix} changed: {touched}")
    record("check_07a_no_code_and_no_configuration_changed", not faults, "; ".join(faults))


def check_07b_the_runner_registers_this_gate() -> None:
    """Positive 7b: the sweep runs this gate, after every batch gate.

    A gate the runner does not know about is a gate that passes forever. E0 sits
    after every ``b`` gate because its citations are of what those batches left;
    the evaluation gates that follow it cite what it inventoried, so being last
    is not the property -- being after the batches is.

    The property is about citation, not about the letter a gate's name starts
    with, so a batch gate that cites nothing E0 inventories and instead reads E0
    is exempt and is named in ``AFTER_THIS_GATE``.
    """
    source = text_of(ROOT / "spec_checks" / "run_all.py")
    name = Path(__file__).name
    faults = []
    listed = re.findall(r'"(spec_check_[a-z0-9_]+\.py)"', source)
    if name not in listed:
        faults.append("run_all.py does not list this gate")
    else:
        position = listed.index(name)
        late = [
            gate
            for gate in listed[position + 1 :]
            if gate.startswith("spec_check_b") and gate not in AFTER_THIS_GATE
        ]
        if late:
            faults.append(f"batch gates run after this one: {late}")
    record("check_07b_the_runner_registers_this_gate", not faults, "; ".join(faults))


def check_07c_ascii_prose_in_the_gate() -> None:
    """Negative 7c: this gate carries no non-ASCII prose.

    The documents are written in the project's working language; the code that
    reads them is not. Both vocabularies this gate needs are read out of the
    ledger for exactly that reason.
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
    record("check_07c_ascii_prose_in_the_gate", not faults, "; ".join(faults[:5]))


def check_07d_the_gate_runs_nothing() -> None:
    """Negative 7d: no pipeline, no translator, no credential.

    E0 asserts about documents. A gate that could build a pipeline artefact
    would make an inventory batch cost what a run costs, and one that could read
    a credential would make it possible for it to spend one.
    """
    source = text_of(Path(__file__))
    faults = []
    for forbidden in ("translator", "openai", "build_artifact", "high_level"):
        if re.search(rf"^\s*(import|from)\s+.*{forbidden}", source, re.MULTILINE):
            faults.append(f"imports {forbidden}")
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    if suffix in source.replace('"_API" + "_KEY"', ""):
        faults.append("names a credential variable")
    record("check_07d_the_gate_runs_nothing", not faults, "; ".join(faults))


# --- 08 the sweep --------------------------------------------------------------


def check_08_sweep() -> None:
    """Positive 8: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_08_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_08_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01a_the_three_documents_exist,
        check_01b_every_ledger_row_carries_its_provenance,
        check_01c_the_status_summary_agrees_with_the_rows,
        check_02_no_dead_link,
        check_02b_the_evidence_is_tiered,
        check_03_the_retired_register_is_actually_retired,
        check_04_every_equation_label_resolves,
        check_05_the_ledger_and_the_gap_register_close_over_each_other,
        check_06_sampled_numbers_are_in_the_files_they_cite,
        check_07a_no_code_and_no_configuration_changed,
        check_07b_the_runner_registers_this_gate,
        check_07c_ascii_prose_in_the_gate,
        check_07d_the_gate_runs_nothing,
        check_08_sweep,
    ]
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(check.__name__, False, f"raised {exc!r}")
    print(f"\nspec_check_e0: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_e0")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
