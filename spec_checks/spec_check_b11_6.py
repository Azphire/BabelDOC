"""Gate script for batch B11.6 (an indent double gate, and in-page column chains).

Run from the repository root:

    python spec_checks/spec_check_b11_6.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request. Every assertion is answered from a stub this gate builds, or
from the small derived evidence this batch wrote beside its runs, or from a file
git tracks -- never from a stage checkpoint and never from a produced PDF, per
CLAUDE.md section 4.16.

What this batch is.

T1 gave the indent policy a second gate. The first, which b11.5 shipped, is the
layout label: only running body text is decided. That was not enough, because a
contents page and a masthead set their records under a body label, so the
Chinese convention reached 79 paragraphs of furniture on one nine page sample.
The second gate is the page: a page whose kind does not declare
``indent_eligible`` is skipped whole, and the flag on it stays whatever the
source geometry said.

T1's second half, the box level gate, was specified determination first:
measure, then decide. The measurement is in ``t1_boxed_measure.json`` and the
reading in ``t1_boxed_review.json``. It did not ship, and 06 is why: the
declared predicate has a floor on the panel's area and no ceiling, and a filled
curve covering the whole sheet clears that floor, so the rule catches 230 of the
corpus's 428 body paragraphs with 208 of them merely printed on the paper.
GAP-41 carries it.

T2 gave the chain detector a second kind of boundary: between two columns of one
page. Four declared gates stand in front of it -- a page of records yields none,
assembly is exclusive so an edge skipping a column already handed over to is
dropped, the score and threshold are the page level ones with the two
in-page constants stated, and a column head with a display line set tight above
it is refused. Against the 24 ruled pairs the detector takes all 16 that
continue and refuses 7 of the 8 that do not; the eighth is GAP-42.

01 is T1's page gate: what it stopped, what it kept, and that it is declarative.
02 is T2's connection set against the ruling, gate by gate.
03 is T2 downstream: the joint translation, the sentences it repaired, and the
   two halves of a chain set in their own columns.
04 is conservation: join equals whole, the page and paragraph counts, the
   detectors.
05 is scope, cost and the sweep.
06 is the two determinations this batch wrote down rather than took silently.

Tiers: every assertion reads a stub or this batch's own derived evidence, so the
fast tier runs the whole gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import chain_backfill as backfill  # noqa: E402
from babeldoc.magazine import chain_signals as cs  # noqa: E402
from babeldoc.magazine import indent_policy  # noqa: E402
from babeldoc.magazine.taxonomy import OPTIONAL_BOOLEAN_POLICY_KEYS  # noqa: E402
from babeldoc.magazine.taxonomy import OPTIONAL_POLICY_DEFAULTS  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import evidence  # noqa: E402
from spec_checks import harness  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b11.6"
PREVIOUS_TAG = "b11.5"

BATCH_DIR = ROOT / "examples" / "output" / "b11_6"
PRIOR_DIR = ROOT / "examples" / "output" / "b11_5"

SAMPLES = ("Courier-en", "AramcoWorld-en-v2", "FD-en-v2", "Courier-zh")

PREMISE = BATCH_DIR / "premise_check.json"
BOXED_MEASURE = BATCH_DIR / "t1_boxed_measure.json"
BOXED_REVIEW = BATCH_DIR / "t1_boxed_review.json"
PREDICTION = BATCH_DIR / "t2_prediction.json"
COST = BATCH_DIR / "cost_attribution.json"
SWEEP = BATCH_DIR / "run_all.fast.json"
RUNS = BATCH_DIR / "runs.json"

ADJUDICATION = ROOT / "reviews" / "column_pairs.adjudication.json"
CHAIN_CONFIG = ROOT / "configs" / "chain_detection.json"
INDENT_CONFIG = ROOT / "configs" / "indent_policy.json"
PAGE_TYPES = ROOT / "configs" / "page_types.json"
WAIVERS = ROOT / "WAIVERS.md"
CONTRACTS = ROOT / "docs" / "reports" / "assertion_contracts.md"
GAP_REGISTER = ROOT / "docs" / "eval" / "gap_register.md"
UPSTREAM_DIFF = ROOT / "UPSTREAM_DIFF.md"

# The adjudication is the gate's truth and the corpus owner's to write, so its
# digest is pinned here. CLAUDE.md section 4.12: the pin anchors "no machine
# changed this", and an authorised update repins with a change record rather
# than failing the gate.
#
#   was: (none -- the file is new in this batch)
#   now: 1956eb9b5796ed4bce97e3d338e957e194908a7d8699d1e1edf5274ebea06755
#   what: the 24 ruled column pairs, transcribed from the PLAN B11.6 appendix
#   who: the corpus owner, through the appendix
#   why: T2 needs a truth file its connection set can be measured against
ADJUDICATION_SHA = "1956eb9b5796ed4bce97e3d338e957e194908a7d8699d1e1edf5274ebea06755"

# The one ruled pair the four gates do not refuse, named exactly so that a
# second survivor would be a failure rather than a quiet widening. GAP-42.
KNOWN_SURVIVOR = ("Courier-zh", "p4:c3->c4")

# The words the ruling uses for a pair whose tail already hands over to the
# column beside it, so the edge that skips past that column adds nothing.
REDUNDANT_REASON = "covered by the adjacent edge"

GAPS = ("GAP-41", "GAP-42")

# The contents page whose indent the page gate exists to stop, and the batch
# whose record shows it un-gated.
CONTENTS_SAMPLE = "FD-en-v2"
CONTENTS_PAGE = 3

# The two FD-en-v2 column pairs whose repair is this batch's evidence face, by
# the source words at the break rather than by any run local identifier.
SUPPLY_TAIL = "sup-"
SUPPLY_HEAD = "ply chains"
FERTILIZER_TAIL = "fertilizer"
FERTILIZER_HEAD = "costs"

# What the plan names as the reading the joint translation has to produce: the
# two halves of the broken clause standing in one sentence of the output.
# Written as escapes so this file stays pure ASCII: b0's 09, b1's 09d and b2's
# 11c all scan spec_checks/*.py for CJK. Each is glossed in English beside it.
FERTILIZER_ZH_DEPENDS = "\u4f9d\u8d56"  # depends on
FERTILIZER_ZH_COST = "\u6210\u672c"  # cost
SUPPLY_ZH = "\u4f9b\u5e94\u94fe"  # supply chain

# The delta this batch is allowed.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/chain_builder.py",
    "babeldoc/magazine/chain_signals.py",
    "babeldoc/magazine/indent_policy.py",
    # Outside the plan's enumerated surface and registered for it: the policy
    # flag T1 reads has to be admitted by the vocabulary loader, and the tool
    # the plan asks T2 to share a function with has to import that function.
    # W-B11-18.
    "babeldoc/magazine/taxonomy.py",
    "tools/column_continuity.py",
    "configs/",
    "reviews/column_pairs.adjudication.json",
    "spec_checks/spec_check_b11_6.py",
    # Three gates whose propositions this batch moved, each registered, and one
    # whose authorised consumer list it joins: the indent pass now reads the
    # page kind, and two gates build a page carrying one. W-B11-19.
    "spec_checks/spec_check_b4.py",
    "spec_checks/spec_check_b11_2.py",
    "spec_checks/spec_check_b11_5.py",
    "spec_checks/spec_check_b1.py",
    "spec_checks/spec_check_b5.py",
    "spec_checks/spec_check_e0.py",
    "spec_checks/run_all.py",
    "docs/eval/gap_register.md",
    "docs/reports/assertion_contracts.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "plans/PLAN_B11_6.md",
    "examples/output/b11_6/",
)

# Trees this batch reads and never writes.
READ_ONLY_TREES = (
    "prompts/",
    "corpus/",
    "examples/output/b10_5/",
    "examples/output/b11_2/",
    "examples/output/b11_5/",
)

# Every upstream file. This batch touches none of them.
UPSTREAM_PREFIX = "babeldoc/"
MAGAZINE_PREFIX = "babeldoc/magazine/"

# What this gate reads and the retention policy must therefore not remove.
GATE_EVIDENCE = (
    "examples/output/b11_6/premise_check.json",
    "examples/output/b11_6/t1_boxed_measure.json",
    "examples/output/b11_6/t1_boxed_review.json",
    "examples/output/b11_6/t2_prediction.json",
    "examples/output/b11_6/cost_attribution.json",
    "examples/output/b11_6/run_all.fast.json",
    "examples/output/b11_6/runs.json",
    "examples/output/b11_6/Courier-en/run.json",
    "examples/output/b11_6/Courier-en/chain_evidence.json",
    "examples/output/b11_6/Courier-en/indent_evidence.json",
    "examples/output/b11_6/Courier-en/conservation.json",
    "examples/output/b11_6/Courier-en/sidecars/indent_policy.report.json",
    "examples/output/b11_6/Courier-en/sidecars/chain_translation.report.json",
    "examples/output/b11_6/Courier-en/sidecars/issues.json",
    "examples/output/b11_6/AramcoWorld-en-v2/run.json",
    "examples/output/b11_6/AramcoWorld-en-v2/chain_evidence.json",
    "examples/output/b11_6/AramcoWorld-en-v2/indent_evidence.json",
    "examples/output/b11_6/AramcoWorld-en-v2/conservation.json",
    "examples/output/b11_6/AramcoWorld-en-v2/sidecars/indent_policy.report.json",
    "examples/output/b11_6/AramcoWorld-en-v2/sidecars/chain_translation.report.json",
    "examples/output/b11_6/AramcoWorld-en-v2/sidecars/issues.json",
    "examples/output/b11_6/FD-en-v2/run.json",
    "examples/output/b11_6/FD-en-v2/chain_evidence.json",
    "examples/output/b11_6/FD-en-v2/indent_evidence.json",
    "examples/output/b11_6/FD-en-v2/conservation.json",
    "examples/output/b11_6/FD-en-v2/render_evidence.json",
    "examples/output/b11_6/FD-en-v2/sidecars/indent_policy.report.json",
    "examples/output/b11_6/FD-en-v2/sidecars/chain_translation.report.json",
    "examples/output/b11_6/FD-en-v2/sidecars/issues.json",
    "examples/output/b11_6/Courier-zh/run.json",
    "examples/output/b11_6/Courier-zh/chain_evidence.json",
    "examples/output/b11_6/Courier-zh/indent_evidence.json",
    "examples/output/b11_6/Courier-zh/conservation.json",
    "examples/output/b11_6/Courier-zh/sidecars/indent_policy.report.json",
    "examples/output/b11_6/Courier-zh/sidecars/chain_translation.report.json",
    "examples/output/b11_6/Courier-zh/sidecars/issues.json",
)

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b11_6")


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


def run_dir(sample: str) -> Path:
    return BATCH_DIR / sample


def chain_evidence(sample: str) -> dict:
    return load(run_dir(sample) / "chain_evidence.json")


def indent_report(sample: str) -> dict:
    return load(run_dir(sample) / "sidecars" / indent_policy.REPORT_NAME)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def ruled_pairs() -> list[dict]:
    with ADJUDICATION.open(encoding="utf-8") as f:
        return json.load(f)["pairs"]


def boundary_label(pair: dict) -> str:
    return f"p{pair['page']}:c{pair['tail_column']}->c{pair['head_column']}"


def edges_of(sample: str) -> set[str]:
    return {edge["boundary"] for edge in chain_evidence(sample)["edges"]}


def boundary_rows(sample: str) -> dict[str, dict]:
    return {row["boundary"]: row for row in chain_evidence(sample)["boundaries"]}


# --- documents built here ------------------------------------------------------


def a_kind_with(flag: bool) -> str | None:
    """A page kind whose policy declares the indent flag, or does not.

    Read out of the vocabulary rather than typed in, so the fixture states the
    property it needs rather than a name that could stop having it.
    """
    for page_type in load_taxonomy().page_types:
        declared = bool(
            page_type.policy.get(indent_policy.PAGE_ELIGIBILITY_POLICY_FLAG, False)
        )
        if declared == flag:
            return page_type.name
    return None


def a_body_paragraph(text: str = "one two three four five"):
    style = il_version_1.PdfStyle(
        font_id="F1", font_size=9.0, graphic_state=il_version_1.GraphicState()
    )
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(x=40.0, y=700.0, x2=300.0, y2=740.0),
        layout_label="plain text",
        unicode=text,
        first_line_indent=False,
        pdf_style=style,
        pdf_paragraph_composition=[],
    )


def a_page(paragraphs, kind: str | None):
    return il_version_1.Page(
        page_number=0,
        page_kind=kind,
        page_kind_conf=None if kind is None else 1.0,
        pdf_paragraph=list(paragraphs),
        mediabox=il_version_1.Mediabox(
            box=il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
        ),
        cropbox=il_version_1.Cropbox(
            box=il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
        ),
    )


class StubConfig:
    """The few translation config members the pass under test reads."""

    def __init__(self, working: Path, lang_out: str = "zh", **switches):
        self._working = working
        self.lang_out = lang_out
        for name, value in switches.items():
            setattr(self, name, value)

    def get_working_file_path(self, name: str) -> str:
        return str(self._working / name)


# --- 01 T1: the page gate ------------------------------------------------------


def check_01a_the_contents_page_is_left_as_the_source_set_it() -> None:
    """Positive 1a: on the contents page the pass now decides nothing.

    Two numbers, not one. That nothing was decided is the gate firing; that
    nothing was changed is what the reader sees, and it is the stronger of the
    two, because a pass that decided and happened to agree would satisfy the
    first alone. Both are read beside b11.5's own record of the same sample,
    where the same page carries 29 decisions and 26 changes, so the assertion
    says what moved rather than only what stands.
    """
    faults = []
    try:
        now = indent_report(CONTENTS_SAMPLE)
        before = evidence.read_json(
            PRIOR_DIR / CONTENTS_SAMPLE / "sidecars" / indent_policy.REPORT_NAME
        )
    except evidence.EvidenceMissing as missing:
        skip("check_01a_the_contents_page_is_left_as_the_source_set_it", [str(missing)])
        return

    page = next(
        (row for row in now["page_records"] if row["page"] == CONTENTS_PAGE), None
    )
    if page is None:
        faults.append(f"no record for p{CONTENTS_PAGE}")
    elif page["indent_eligible"]:
        faults.append(f"p{CONTENTS_PAGE} is {page['page_kind']!r} and is eligible")
    elif page["decided"]:
        faults.append(f"p{CONTENTS_PAGE} decided {page['decided']}")

    mine = [row for row in now["paragraphs"] if row["page"] == CONTENTS_PAGE]
    theirs = [row for row in before["paragraphs"] if row["page"] == CONTENTS_PAGE]
    if not mine:
        faults.append(f"no paragraph on p{CONTENTS_PAGE}")
    decided = [row["reference"] for row in mine if row["decided"]]
    if decided:
        faults.append(f"{len(decided)} decided: {decided[:3]}")
    changed = [row["reference"] for row in mine if row["before"] != row["after"]]
    if changed:
        faults.append(f"{len(changed)} changed: {changed[:3]}")
    skipped = {row["skipped"] for row in mine}
    if skipped != {indent_policy.SKIP_PAGE_INELIGIBLE}:
        faults.append(f"reasons on the page are {sorted(skipped)}")
    was_changed = sum(1 for row in theirs if row["before"] != row["after"])
    if was_changed <= 0:
        faults.append("b11.5 changed nothing there, so the negative proves nothing")
    record(
        "check_01a_the_contents_page_is_left_as_the_source_set_it",
        not faults,
        f"b11.5 changed {was_changed} there; " + "; ".join(faults[:4]),
    )


def check_01b_the_article_pages_keep_every_indent() -> None:
    """Positive 1b: on an eligible page the policy still reaches every paragraph.

    The page gate is only safe if it takes nothing it should not. Measured per
    sample over the eligible pages: every body paragraph on one is decided and
    indented, and the count matches what b11.5 decided on those same pages of
    the sample it ran. A gate that had swallowed an article page would show as a
    page with body paragraphs and no decisions.

    A run whose target language no entry claims takes the declared fallback,
    which is to reproduce the source, and decides nothing anywhere. Such a run
    is not asked to have decided; it is asked to have decided *nothing*, which
    is the fallback working and is checked here rather than passed over. One of
    the four samples translates into English and is exactly that case.
    """
    faults = []
    seen = 0
    fallback_runs = 0
    for sample in SAMPLES:
        try:
            report = indent_report(sample)
        except evidence.EvidenceMissing as missing:
            faults.append(f"{sample}: {missing}")
            continue
        labels = set(report["body_labels"])
        eligible = {
            row["page"] for row in report["page_records"] if row["indent_eligible"]
        }
        if report["mode"] == indent_policy.MODE_SOURCE:
            fallback_runs += 1
            if report["mode_source"] != "fallback":
                faults.append(f"{sample}: the source mode was declared, not fallen back to")
            decided = [row["reference"] for row in report["paragraphs"] if row["decided"]]
            if decided:
                faults.append(f"{sample}: the fallback decided {decided[:3]}")
            continue
        if not eligible:
            continue
        for row in report["paragraphs"]:
            if row["page"] not in eligible or row["layout_label"] not in labels:
                continue
            seen += 1
            if not row["decided"]:
                faults.append(f"{sample} {row['reference']} undecided on an article page")
            if not row["after"]:
                faults.append(f"{sample} {row['reference']} unindented")
    if seen < 20:
        faults.append(f"only {seen} body paragraph(s) on eligible pages")
    if fallback_runs < 1:
        faults.append("no run took the fallback, so that half proves nothing")

    try:
        before = evidence.read_json(
            PRIOR_DIR / CONTENTS_SAMPLE / "sidecars" / indent_policy.REPORT_NAME
        )
        now = indent_report(CONTENTS_SAMPLE)
    except evidence.EvidenceMissing:
        before = now = None
    if before is not None:
        eligible = {
            row["page"] for row in now["page_records"] if row["indent_eligible"]
        }
        theirs = sum(
            1
            for row in before["paragraphs"]
            if row["decided"] and row["page"] in eligible
        )
        mine = sum(
            1 for row in now["paragraphs"] if row["decided"] and row["page"] in eligible
        )
        if mine != theirs:
            faults.append(
                f"{CONTENTS_SAMPLE}: b11.5 decided {theirs} on the eligible pages, "
                f"this run decided {mine}"
            )
    record(
        "check_01b_the_article_pages_keep_every_indent",
        not faults,
        f"body paragraphs on eligible pages={seen}, fallback runs={fallback_runs}; "
        + "; ".join(faults[:4]),
    )


def check_01c_an_undeclared_page_is_skipped_whole() -> None:
    """Negative 1c: every ineligible page comes back untouched, and says why.

    Not merely unchanged: every paragraph on such a page has to carry the page
    reason rather than the label reason, because a page skipped for its kind and
    a paragraph skipped for its label are different findings and a sidecar that
    conflated them would answer neither.
    """
    faults = []
    pages = 0
    for sample in SAMPLES:
        try:
            report = indent_report(sample)
        except evidence.EvidenceMissing as missing:
            faults.append(f"{sample}: {missing}")
            continue
        ineligible = {
            row["page"] for row in report["page_records"] if not row["indent_eligible"]
        }
        pages += len(ineligible)
        for row in report["paragraphs"]:
            if row["page"] not in ineligible:
                continue
            if row["decided"]:
                faults.append(f"{sample} {row['reference']} decided on an ineligible page")
            if row["skipped"] != indent_policy.SKIP_PAGE_INELIGIBLE:
                faults.append(
                    f"{sample} {row['reference']} skipped as {row['skipped']!r}"
                )
            if row["before"] != row["after"]:
                faults.append(f"{sample} {row['reference']} moved")
    if pages < 4:
        faults.append(f"only {pages} ineligible page(s) in the corpus run")
    record(
        "check_01c_an_undeclared_page_is_skipped_whole",
        not faults,
        f"ineligible pages={pages}; " + "; ".join(faults[:4]),
    )


def check_01d_the_gate_is_declared_and_not_named() -> None:
    """Positive 1d: the flag lives in the vocabulary and the code names no type.

    Three facts. The flag is registered as an optional boolean, so a vocabulary
    written before it still loads and every consumer meets a declared default.
    Exactly the two article types declare it, which is the plan's surface. And
    the pass reads it by the flag's name, never by a page type's, which is
    CLAUDE.md section 4.2.
    """
    faults = []
    flag = indent_policy.PAGE_ELIGIBILITY_POLICY_FLAG
    if OPTIONAL_POLICY_DEFAULTS.get(flag, None) is not False:
        faults.append(f"{flag} does not default to false")
    if flag not in OPTIONAL_BOOLEAN_POLICY_KEYS:
        faults.append(f"{flag} is not validated as a boolean")
    taxonomy = load_taxonomy()
    declaring = sorted(
        page_type.name
        for page_type in taxonomy.page_types
        if page_type.policy.get(flag, False)
    )
    if len(declaring) != 2:
        faults.append(f"{len(declaring)} type(s) declare it: {declaring}")
    # Read from the file rather than from the loaded policy: the loader merges
    # the declared defaults in, so every loaded policy carries the key and only
    # the file says who wrote it down.
    with PAGE_TYPES.open(encoding="utf-8") as f:
        written = json.load(f)
    for entry in written["page_types"]:
        if flag in entry["policy"] and entry["name"] not in declaring:
            faults.append(f"{entry['name']} declares it and does not hold it")
        if entry["name"] in declaring and flag not in entry["policy"]:
            faults.append(f"{entry['name']} holds it without declaring it")
    source = (ROOT / "babeldoc" / "magazine" / "indent_policy.py").read_text(
        encoding="utf-8"
    )
    for page_type in taxonomy.page_types:
        if f'"{page_type.name}"' in source or f"'{page_type.name}'" in source:
            faults.append(f"the pass names the page type {page_type.name!r}")
    if f'"{flag}"' not in source:
        faults.append("the pass does not read the flag by name")
    record(
        "check_01d_the_gate_is_declared_and_not_named",
        not faults,
        f"declaring={declaring}; " + "; ".join(faults[:4]),
    )


def check_01e_the_gate_is_driven_not_reasoned() -> None:
    """Positive 1e: the pass is run over three stubs and answers three ways.

    A page whose kind declares the flag is decided; a page whose kind does not is
    untouched; a page carrying no kind at all is untouched, which is the case no
    corpus document supplies and the one an undeclared page falls into.
    """
    faults = []
    eligible_kind = a_kind_with(True)
    ineligible_kind = a_kind_with(False)
    if eligible_kind is None or ineligible_kind is None:
        faults.append("the vocabulary offers no pair of kinds to drive this with")
    else:
        with tempfile.TemporaryDirectory() as directory:
            working = Path(directory)
            cases = {
                "eligible": (eligible_kind, True),
                "ineligible": (ineligible_kind, False),
                "no kind": (None, False),
            }
            for name, (kind, should_decide) in cases.items():
                paragraph = a_body_paragraph()
                document = il_version_1.Document(page=[a_page([paragraph], kind)])
                config = StubConfig(working, magazine_indent_policy=True)
                report = indent_policy.apply(config, document)
                if report is None:
                    faults.append(f"{name}: the pass did not act")
                    continue
                decided = report["totals"]["decided"]
                if bool(decided) != should_decide:
                    faults.append(f"{name}: decided {decided}")
                if bool(paragraph.first_line_indent) != should_decide:
                    faults.append(
                        f"{name}: the flag is {paragraph.first_line_indent!r}"
                    )
                if not should_decide:
                    row = report["paragraphs"][0]
                    if row["skipped"] != indent_policy.SKIP_PAGE_INELIGIBLE:
                        faults.append(f"{name}: skipped as {row['skipped']!r}")
    record(
        "check_01e_the_gate_is_driven_not_reasoned",
        not faults,
        "; ".join(faults[:4]),
    )


# --- 02 T2: the connection set --------------------------------------------------


def check_02a_the_ruling_is_a_filled_in_truth_file() -> None:
    """Positive 2a: the adjudication is present, complete and unmodified.

    It is the corpus owner's file and the gate's truth, so what is asserted is
    the shape a filled ruling has -- a verdict and a reason on every one of the
    24 pairs, and the split the plan's appendix states -- and that its digest is
    the pinned one, which is the machine having written nothing since.
    """
    faults = []
    if not ADJUDICATION.is_file():
        skip("check_02a_the_ruling_is_a_filled_in_truth_file", [str(ADJUDICATION)])
        return
    with ADJUDICATION.open(encoding="utf-8") as f:
        ruling = json.load(f)
    pairs = ruling["pairs"]
    if len(pairs) != 24:
        faults.append(f"{len(pairs)} pairs")
    for pair in pairs:
        if not isinstance(pair.get("continues"), bool):
            faults.append(f"{boundary_label(pair)} has no verdict")
        if not (pair.get("reason") or "").strip():
            faults.append(f"{boundary_label(pair)} has no reason")
    true_pairs = sum(1 for pair in pairs if pair["continues"])
    if (true_pairs, len(pairs) - true_pairs) != (16, 8):
        faults.append(f"the split is {true_pairs}/{len(pairs) - true_pairs}")
    digest = sha256_of(ADJUDICATION)
    if digest != ADJUDICATION_SHA:
        faults.append(f"digest {digest[:16]} is not the pin {ADJUDICATION_SHA[:16]}")
    if ruling.get("ruled_by") != "user":
        faults.append(f"ruled_by is {ruling.get('ruled_by')!r}")
    record(
        "check_02a_the_ruling_is_a_filled_in_truth_file",
        not faults,
        "; ".join(faults[:4]),
    )


def check_02b_every_pair_that_continues_became_an_edge() -> None:
    """Positive 2b: the detector takes all 16 pairs the ruling says continue."""
    faults = []
    missing = []
    for pair in ruled_pairs():
        if not pair["continues"]:
            continue
        try:
            edges = edges_of(pair["sample"])
        except evidence.EvidenceMissing as absent:
            faults.append(f"{pair['sample']}: {absent}")
            continue
        if boundary_label(pair) not in edges:
            missing.append(f"{pair['sample']} {boundary_label(pair)}")
    if missing:
        faults.append(f"{len(missing)} not taken: {missing[:3]}")
    record(
        "check_02b_every_pair_that_continues_became_an_edge",
        not faults,
        "; ".join(faults[:4]),
    )


def check_02c_no_pair_that_does_not_continue_became_an_edge() -> None:
    """Negative 2c: seven of the eight are refused, and the eighth is named.

    The exception is not a tolerance: it is one boundary, named by sample and by
    columns, and registered as GAP-42. A second survivor fails here, and so does
    the named one disappearing without the register following, because an
    assertion that quietly stopped needing its exception is an assertion nobody
    would notice had changed.
    """
    faults = []
    survivors = []
    for pair in ruled_pairs():
        if pair["continues"]:
            continue
        try:
            edges = edges_of(pair["sample"])
        except evidence.EvidenceMissing as absent:
            faults.append(f"{pair['sample']}: {absent}")
            continue
        if boundary_label(pair) in edges:
            survivors.append((pair["sample"], boundary_label(pair)))
    if sorted(survivors) != [KNOWN_SURVIVOR]:
        faults.append(f"survivors={sorted(survivors)}, expected [{KNOWN_SURVIVOR}]")
    register = GAP_REGISTER.read_text(encoding="utf-8")
    if "GAP-42" not in register:
        faults.append("GAP-42 is not registered")
    elif KNOWN_SURVIVOR[1] not in register:
        faults.append(f"GAP-42 does not name {KNOWN_SURVIVOR[1]}")
    record(
        "check_02c_no_pair_that_does_not_continue_became_an_edge",
        not faults,
        "; ".join(faults[:4]),
    )


def check_02d_a_redundant_skip_is_dropped_and_its_text_still_reached() -> None:
    """Negative 2d: the five skipping edges lose, and lose to the adjacent one.

    Two halves. The skipping edge is not an edge, and the report says it was
    dropped for wanting a tail another edge already held -- not merely that it
    is absent, which a boundary that had stopped scoring would also produce. And
    the tail it was dropped for is the tail of an edge that was taken, which is
    the form the plan calls correct: the content the skip claimed is reached by
    the adjacent handover instead.
    """
    faults = []
    checked = 0
    for pair in ruled_pairs():
        # The ruling's own reason, not the pairing: a skipping pairing can be
        # ruled false for a different reason, and one is -- the review page pair
        # 02f covers, which is refused by the head clearance gate and never
        # reaches assembly at all.
        if pair["continues"] or REDUNDANT_REASON not in pair["reason"]:
            continue
        sample = pair["sample"]
        label = boundary_label(pair)
        try:
            report = chain_evidence(sample)
        except evidence.EvidenceMissing as absent:
            faults.append(f"{sample}: {absent}")
            continue
        checked += 1
        dropped = next(
            (row for row in report["dropped_edges"] if row["boundary"] == label), None
        )
        if dropped is None:
            faults.append(f"{sample} {label} is not in the dropped list")
            continue
        if dropped["dropped_reason"] != cs.DROPPED_TAIL_TAKEN:
            faults.append(f"{sample} {label} dropped as {dropped['dropped_reason']!r}")
        rows = boundary_rows(sample)
        row = rows.get(label)
        if row is None or row.get("tail") is None:
            faults.append(f"{sample} {label} has no recorded tail")
            continue
        tail_reference = row["tail"]["reference"]
        taken = {edge["boundary"] for edge in report["edges"]}
        holder = [
            other
            for other in taken
            if rows.get(other, {}).get("tail")
            and rows[other]["tail"]["reference"] == tail_reference
        ]
        if not holder:
            faults.append(f"{sample} {label}: its tail hands on to nothing")
        elif any(
            rows[other]["pairing"] != cs.PAIRING_COLUMN_ADJACENT for other in holder
        ):
            faults.append(f"{sample} {label}: the holder is not the adjacent edge")
    if checked != 5:
        faults.append(f"{checked} skipping pair(s) checked, expected 5")
    record(
        "check_02d_a_redundant_skip_is_dropped_and_its_text_still_reached",
        not faults,
        "; ".join(faults[:4]),
    )


def check_02e_a_page_of_records_yields_no_column_boundary() -> None:
    """Negative 2e: the first gate refuses the contents page whole.

    Not one pair on the page refused -- no pair on the page scored at all. The
    report carries one row for the page with the flag's name as its reason, and
    the row is checked to be the only thing the page produced, because a page
    that had produced pairs and refused them one by one would be a different
    mechanism wearing the same result.
    """
    faults = []
    try:
        report = chain_evidence(CONTENTS_SAMPLE)
    except evidence.EvidenceMissing as absent:
        skip("check_02e_a_page_of_records_yields_no_column_boundary", [str(absent)])
        return
    rows = [
        row
        for row in report["boundaries"]
        if row["kind"] == cs.BOUNDARY_COLUMN and row["tail_page"] == CONTENTS_PAGE
    ]
    if len(rows) != 1:
        faults.append(f"p{CONTENTS_PAGE} produced {len(rows)} column row(s)")
    elif rows[0]["reason"] != cs.REASON_LINE_STRUCTURE:
        faults.append(f"the reason is {rows[0]['reason']!r}")
    elif rows[0]["tail_column"] is not None:
        faults.append("the row names a pair of columns rather than the page")
    if any(row["linked"] for row in rows):
        faults.append("a boundary on the page linked")
    # The flag is the vocabulary's, and the page's kind has to be one declaring
    # it, or the assertion would pass on a page nothing was refused for.
    kind = None
    for row in load(run_dir(CONTENTS_SAMPLE) / "sidecars" / indent_policy.REPORT_NAME)[
        "page_records"
    ]:
        if row["page"] == CONTENTS_PAGE:
            kind = row["page_kind"]
    policy = load_taxonomy().policy_of(kind)
    if not (policy and policy.get(cs.LINE_STRUCTURE_POLICY_FLAG, False)):
        faults.append(f"p{CONTENTS_PAGE} is {kind!r}, which declares no line structure")
    record(
        "check_02e_a_page_of_records_yields_no_column_boundary",
        not faults,
        "; ".join(faults[:4]),
    )


def check_02f_a_head_under_a_display_line_is_refused() -> None:
    """Negative 2f: the fourth gate refuses a pair the score would have taken.

    The hard case it was written for. What makes it an assertion about the gate
    rather than about the threshold is the score: the pair is recorded as
    scoring at or above ``link_min_score`` and as not linked, with the gate's own
    reason. A pair that had simply fallen below the threshold would prove that
    the weights moved, which is a different and unwanted event.
    """
    faults = []
    target = None
    for pair in ruled_pairs():
        if pair["continues"]:
            continue
        if "unit" not in pair["reason"]:
            continue
        target = pair
    if target is None:
        faults.append("the ruling no longer holds the review page pair")
        record("check_02f_a_head_under_a_display_line_is_refused", False,
               "; ".join(faults))
        return
    sample = target["sample"]
    label = boundary_label(target)
    try:
        rows = boundary_rows(sample)
        report = chain_evidence(sample)
    except evidence.EvidenceMissing as absent:
        skip("check_02f_a_head_under_a_display_line_is_refused", [str(absent)])
        return
    row = rows.get(label)
    if row is None:
        faults.append(f"{sample} {label} was not scored at all")
    else:
        if row["score"] is None or row["score"] < report["link_min_score"]:
            faults.append(f"{sample} {label} scored {row['score']}")
        if row["linked"]:
            faults.append(f"{sample} {label} linked")
        if row["reason"] != cs.REASON_HEAD_NOT_CLEAR:
            faults.append(f"{sample} {label} refused as {row['reason']!r}")
    record(
        "check_02f_a_head_under_a_display_line_is_refused",
        not faults,
        f"{sample} {label}; " + "; ".join(faults[:4]),
    )


def check_02g_the_four_gates_are_declarations() -> None:
    """Positive 2g: every gate is a declared parameter, bounded, and read by name.

    The four are the line structure flag, the assembly priority, the threshold
    with the two in-page constants, and the head clearance. Each is asserted at
    the declaration rather than at a call site, and the seventh signal is
    asserted absent from the weights, which is what makes "recorded, not scored"
    a fact rather than a comment.
    """
    faults = []
    config = cs.load_chain_config()
    with CHAIN_CONFIG.open(encoding="utf-8") as f:
        raw = json.load(f)

    if raw.get(cs.HEAD_CLEAR_GAP_KEY) is None:
        faults.append(f"{cs.HEAD_CLEAR_GAP_KEY} is not declared")
    if f"{cs.HEAD_CLEAR_GAP_KEY}{cs.RANGE_SUFFIX}" not in raw:
        faults.append(f"{cs.HEAD_CLEAR_GAP_KEY} declares no range")
    if list(config[cs.BOUNDARY_PRIORITY_KEY]) != [
        cs.BOUNDARY_PAGE,
        cs.PAIRING_COLUMN_ADJACENT,
        cs.PAIRING_BODY_NEXT,
    ]:
        faults.append(f"the priority is {list(config[cs.BOUNDARY_PRIORITY_KEY])}")
    blocking = set(config[cs.HEAD_BLOCK_CLASSES_KEY])
    declared = set(config[cs.CLASS_LABELS_KEY])
    if not blocking or not blocking <= declared:
        faults.append(f"blocking classes {sorted(blocking)} against {sorted(declared)}")
    if cs.IN_PAGE_COLUMN_POSITION != 1.0 or cs.IN_PAGE_OPENER_PRIOR != 0.0:
        faults.append("the in-page constants are not the declared ones")
    if f"{cs.WEIGHT_PREFIX}{cs.HYPHEN_SIGNAL}" in raw:
        faults.append("the hyphen signal carries a weight")
    if cs.HYPHEN_SIGNAL in cs.SIGNAL_NAMES:
        faults.append("the hyphen signal is a scored signal")

    # A configuration naming a class nobody declared has to be refused, or the
    # gate would be a comment rather than a check.
    broken = dict(raw)
    broken[cs.HEAD_BLOCK_CLASSES_KEY] = ["no_such_class"]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "chain_detection.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        try:
            cs.load_chain_config(str(path))
        except cs.ChainConfigError:
            pass
        else:
            faults.append("an undeclared blocking class was accepted")
    record(
        "check_02g_the_four_gates_are_declarations",
        not faults,
        "; ".join(faults[:4]),
    )


def check_02h_the_page_boundaries_did_not_move() -> None:
    """Negative 2h: adding a second kind of boundary took none of the first.

    The risk exclusive assembly creates: a column edge holding an end a page
    edge needed would silently shorten a cross page chain. Measured against the
    b10.5 on arm's own chain report, sample by sample, over the page boundaries
    it linked.
    """
    faults = []
    compared = 0
    for sample in SAMPLES:
        try:
            report = chain_evidence(sample)
            baseline = evidence.read_json(
                f"examples/output/b10_5/{sample}/on/work/{sample}/chain_report.json"
            )
        except evidence.EvidenceMissing as absent:
            faults.append(f"{sample}: {absent}")
            continue
        compared += 1
        was = sorted(
            row["boundary"] for row in baseline["boundaries"] if row.get("linked")
        )
        now = sorted(
            edge["boundary"]
            for edge in report["edges"]
            if edge["kind"] == cs.BOUNDARY_PAGE
        )
        if was != now:
            faults.append(f"{sample}: b10.5 linked {was}, this run took {now}")
    if compared < len(SAMPLES):
        faults.append(f"only {compared} sample(s) compared")
    record(
        "check_02h_the_page_boundaries_did_not_move",
        not faults,
        f"compared={compared}; " + "; ".join(faults[:4]),
    )


# --- 03 T2 downstream: the translation and the page ----------------------------


def _chain_holding(sample: str, tail: str, head: str) -> dict | None:
    """The chain whose two member sources end and begin with the given words."""
    for chain in chain_evidence(sample)["chains"]:
        members = chain["members"]
        if len(members) < 2:
            continue
        for first, second in zip(members, members[1:], strict=False):
            if first["source"].rstrip().endswith(tail) and second["source"].lstrip(
            ).startswith(head):
                return chain
    return None


def _survivor_members(sample: str, report: dict) -> set[str]:
    """The two paragraph references of the boundary GAP-42 names, or none.

    The one ruled pair the gates do not refuse is a caption block beside a photo
    spread rather than two columns of running text, so its two halves are not
    set in a column grid and their boxes do overlap. That is the register's
    finding rather than a second defect, so 03c excludes exactly this chain and
    fails on any other.
    """
    if sample != KNOWN_SURVIVOR[0]:
        return set()
    row = next(
        (
            item
            for item in report["boundaries"]
            if item["boundary"] == KNOWN_SURVIVOR[1]
        ),
        None,
    )
    if row is None or not row.get("tail") or not row.get("head"):
        return set()
    return {row["tail"]["reference"], row["head"]["reference"]}


def check_03a_the_broken_clause_is_one_sentence() -> None:
    """Positive 3a: the clause split across a column break comes back whole.

    The reading the plan names. Before this batch each half was translated on
    its own, so the second opened mid clause and the first ended in mid air. The
    evidence is the joint translation: the words for depending and for cost
    stand in one sentence of it, and the sentence is not the one the member
    boundary would have cut. Anchored by the source words at the break, never by
    a run local identifier.
    """
    faults = []
    try:
        chain = _chain_holding(CONTENTS_SAMPLE, FERTILIZER_TAIL, FERTILIZER_HEAD)
    except evidence.EvidenceMissing as absent:
        skip("check_03a_the_broken_clause_is_one_sentence", [str(absent)])
        return
    if chain is None:
        faults.append(
            f"no chain ends on {FERTILIZER_TAIL!r} and resumes on {FERTILIZER_HEAD!r}"
        )
        record("check_03a_the_broken_clause_is_one_sentence", False, "; ".join(faults))
        return
    joint = chain["joint_translation"] or ""
    if not joint:
        faults.append("the chain carries no joint translation")
    profile = backfill.select_profile("zh", backfill.load_backfill_config())
    sentences = backfill.split_sentences(joint, profile)
    together = [
        sentence
        for sentence in sentences
        if FERTILIZER_ZH_DEPENDS in sentence and FERTILIZER_ZH_COST in sentence
    ]
    if not together:
        faults.append(
            "no single sentence of the joint translation carries both halves"
        )
    if len(chain["pages"]) != 1:
        faults.append(f"the chain spans {chain['pages']}, so it is not an in-page one")
    record(
        "check_03a_the_broken_clause_is_one_sentence",
        not faults,
        f"sentences={len(sentences)}; " + "; ".join(faults[:4]),
    )


def check_03b_a_word_broken_at_the_break_is_closed_up() -> None:
    """Positive 3b: a hyphenated word split across the columns is one word again.

    Two facts. The detector recorded the hyphen -- and recorded it without
    weighing it, which 02g asserts separately. And the merge closed the two
    halves up, which shows in the joint translation carrying the word the halves
    spell rather than two fragments.
    """
    faults = []
    try:
        report = chain_evidence(CONTENTS_SAMPLE)
        chain = _chain_holding(CONTENTS_SAMPLE, SUPPLY_TAIL, SUPPLY_HEAD)
    except evidence.EvidenceMissing as absent:
        skip("check_03b_a_word_broken_at_the_break_is_closed_up", [str(absent)])
        return
    if chain is None:
        faults.append(f"no chain ends on {SUPPLY_TAIL!r}")
        record("check_03b_a_word_broken_at_the_break_is_closed_up", False,
               "; ".join(faults))
        return
    joint = chain["joint_translation"] or ""
    if SUPPLY_ZH not in joint:
        faults.append(f"the joint translation does not carry {SUPPLY_ZH!r}")
    hyphenated = [
        row
        for row in report["boundaries"]
        if row["kind"] == cs.BOUNDARY_COLUMN and row.get("tail_ends_on_hyphen")
    ]
    if not hyphenated:
        faults.append("no column boundary recorded a hyphen tail")
    elif not any(row["linked"] for row in hyphenated):
        faults.append("the hyphenated boundary did not link")
    record(
        "check_03b_a_word_broken_at_the_break_is_closed_up",
        not faults,
        "; ".join(faults[:4]),
    )


def check_03c_each_half_is_set_in_its_own_column() -> None:
    """Positive 3c: a joint translation is still laid out column by column.

    The whole point of the arrangement: one request, two boxes. For every chain
    whose members sit on one page, the boxes they were laid out in must not
    overlap horizontally -- they are different columns of the same page -- and
    each must carry text. A backfill that had written the joint translation into
    one box would show as an empty second member.
    """
    faults = []
    checked = 0
    overlapping = []
    for sample in SAMPLES:
        try:
            report = chain_evidence(sample)
        except evidence.EvidenceMissing as absent:
            faults.append(f"{sample}: {absent}")
            continue
        excluded = _survivor_members(sample, report)
        for chain in report["chains"]:
            if len(chain["pages"]) != 1:
                continue
            members = chain["members"]
            checked += 1
            for member in members:
                laid = member.get("laid_out") or {}
                if not (laid.get("text") or "").strip():
                    faults.append(f"{sample} {member['reference_at_build']} is empty")
            boxes = [
                (member.get("laid_out") or {}).get("box")
                for member in members
            ]
            if any(box is None for box in boxes):
                faults.append(f"{sample}: a member has no laid out box")
                continue
            references = {member["reference_at_build"] for member in members}
            for first, second in zip(boxes, boxes[1:], strict=False):
                if min(first[2], second[2]) - max(first[0], second[0]) > 0:
                    overlapping.append((sample, sorted(references), references == excluded))
    stray = [row for row in overlapping if not row[2]]
    if stray:
        faults.append(f"{len(stray)} chain(s) share a band: {stray[:2]}")
    if checked < 3:
        faults.append(f"only {checked} in-page chain(s) to measure")
    record(
        "check_03c_each_half_is_set_in_its_own_column",
        not faults,
        f"in-page chains={checked}, sharing a band={len(overlapping)} "
        f"(the registered one included); " + "; ".join(faults[:4]),
    )


# --- 04 conservation -----------------------------------------------------------


def check_04a_the_pieces_join_back_to_the_whole() -> None:
    """Positive 4a: join equals whole, in-page chains included.

    Read off each run's own chain translation record: the segments of a chain
    tile its joint translation once, in order, with no gap and no overlap, and
    the concatenation is the translation character for character.
    """
    faults = []
    chains = 0
    in_page = 0
    for sample in SAMPLES:
        try:
            report = chain_evidence(sample)
        except evidence.EvidenceMissing as absent:
            faults.append(f"{sample}: {absent}")
            continue
        for chain in report["chains"]:
            joint = chain["joint_translation"]
            segments = chain["joint_segments"]
            if joint is None or segments is None:
                continue
            chains += 1
            if len(chain["pages"]) == 1:
                in_page += 1
            cursor = 0
            for segment in segments:
                if segment["start"] != cursor:
                    faults.append(f"{sample}: a segment starts at {segment['start']}")
                if segment["end"] < segment["start"]:
                    faults.append(f"{sample}: a segment runs backwards")
                if segment["chars"] <= 0:
                    faults.append(f"{sample}: a member received nothing")
                cursor = segment["end"]
            if cursor != len(joint):
                faults.append(
                    f"{sample}: the segments cover {cursor} of {len(joint)} characters"
                )
    if in_page < 3:
        faults.append(f"only {in_page} in-page chain(s) among {chains}")
    record(
        "check_04a_the_pieces_join_back_to_the_whole",
        not faults,
        f"chains={chains} in_page={in_page}; " + "; ".join(faults[:4]),
    )


def check_04b_the_pages_and_paragraphs_are_the_same_ones() -> None:
    """Negative 4b: nothing was created, destroyed or renumbered.

    Page count and per-page paragraph count against the b10.5 on arm each run
    answers to, over the references themselves rather than over totals, so a
    page that lost one paragraph and gained another would not cancel out.
    """
    faults = []
    compared = 0
    for sample in SAMPLES:
        try:
            record_ = load(run_dir(sample) / "conservation.json")
        except evidence.EvidenceMissing as absent:
            faults.append(f"{sample}: {absent}")
            continue
        if record_.get("baseline_pages") is None:
            faults.append(f"{sample}: no baseline to compare against")
            continue
        compared += 1
        if record_["pages"] != record_["baseline_pages"]:
            faults.append(
                f"{sample}: {record_['pages']} pages against "
                f"{record_['baseline_pages']}"
            )
        for label, page in record_["per_page"].items():
            mine = sorted(page["text"])
            theirs = sorted(page.get("baseline_text") or {})
            if mine != theirs:
                faults.append(
                    f"{sample} p{label}: {len(mine)} references against {len(theirs)}"
                )
    if compared < len(SAMPLES):
        faults.append(f"only {compared} sample(s) compared")
    record(
        "check_04b_the_pages_and_paragraphs_are_the_same_ones",
        not faults,
        f"compared={compared}; " + "; ".join(faults[:4]),
    )


def check_04c_the_detectors_did_not_find_more() -> None:
    """Negative 4c: the layout detectors report no more findings than before.

    Compared against the b10.5 on arm of the same sample, which is the run every
    sample here answers to. A joint translation redistributed across two columns
    could overset one of them, and this is where that would show.
    """
    faults = []
    compared = 0
    for sample in SAMPLES:
        try:
            mine = load(run_dir(sample) / "sidecars" / "issues.json")
            theirs = evidence.read_json(
                f"examples/output/b10_5/{sample}/on/sidecars/issues.json"
            )
        except evidence.EvidenceMissing as absent:
            faults.append(f"{sample}: {absent}")
            continue
        compared += 1
        mine_count = len(mine.get("issues") or mine.get("findings") or [])
        their_count = len(theirs.get("issues") or theirs.get("findings") or [])
        if mine_count > their_count:
            faults.append(f"{sample}: {mine_count} findings against {their_count}")
    if compared < len(SAMPLES):
        faults.append(f"only {compared} sample(s) compared")
    record(
        "check_04c_the_detectors_did_not_find_more",
        not faults,
        f"compared={compared}; " + "; ".join(faults[:4]),
    )


# --- 05 scope, cost, sweep ------------------------------------------------------


def check_05a_the_delta_is_the_declared_surface() -> None:
    """Negative 5a: nothing outside the allowed surface was written."""
    faults = []
    changed = changed_paths()
    stray = [
        path
        for path in changed
        if not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    ]
    if stray:
        faults.append(f"outside the surface: {stray[:5]}")
    for path in changed:
        for tree in READ_ONLY_TREES:
            if path.startswith(tree):
                faults.append(f"{path} is in a read only tree")
    record(
        "check_05a_the_delta_is_the_declared_surface",
        not faults,
        f"changed={len(changed)}; " + "; ".join(faults[:4]),
    )


def check_05b_no_upstream_file_was_touched() -> None:
    """Negative 5b: the delta reaches no upstream file and no prompt.

    The plan's own line: upstream zero, and not a word of ``prompts/``. Asserted
    over the delta and over the upstream register, which must have gained
    nothing for this batch.
    """
    faults = []
    for path in changed_paths():
        if path.startswith(UPSTREAM_PREFIX) and not path.startswith(MAGAZINE_PREFIX):
            faults.append(f"{path} is upstream")
        if path.startswith("prompts/"):
            faults.append(f"{path} is a prompt")
    register = UPSTREAM_DIFF.read_text(encoding="utf-8")
    if BATCH_TAG in register or "b11_6" in register:
        faults.append("the upstream register names this batch")
    record(
        "check_05b_no_upstream_file_was_touched",
        not faults,
        "; ".join(faults[:4]),
    )


def check_05c_every_new_request_has_a_cause() -> None:
    """Positive 5c: the ledger closes, and every new request is accounted for.

    Three claims of different strength, kept apart deliberately. The ledger
    identity holds for every sample. Every chain that was expected to send a
    request did send one, which is the mechanism working rather than the cost
    being small. And on the one sample whose prior run is the batch immediately
    before, every new request is this batch's -- a merge or a batch recomposed
    around a claimed member -- with nothing carried over. The other three were
    last run several batches ago, so their remaining new requests are recorded
    with the batches between rather than claimed here; a gate that claimed them
    would be asserting something it cannot see.
    """
    faults = []
    try:
        cost = load(COST)
        ledger = load(RUNS)
    except evidence.EvidenceMissing as absent:
        skip("check_05c_every_new_request_has_a_cause", [str(absent)])
        return
    for row in ledger["runs"]:
        expected = row["requests"] - row["cache_hits"]
        if row["api_calls"] != expected:
            faults.append(f"{row['sample']}: {row['api_calls']} against {expected}")
    if not cost["every_ledger_identity_holds"]:
        faults.append("a sample's ledger does not close")
    if cost["unattributed"]:
        faults.append(f"{len(cost['unattributed'])} unattributed request(s)")
    if not cost["every_new_chain_sent_a_request"]:
        faults.append("a chain that should have sent a request did not")
    if not cost["sharp_sample_is_wholly_attributed"]:
        faults.append(f"{cost['sharp_sample']} carries a request this batch cannot claim")
    total = sum(row["api_calls"] for row in ledger["runs"])
    if cost["totals"]["api_calls"] != total:
        faults.append(f"the attribution counts {cost['totals']['api_calls']} of {total}")
    if cost["totals"]["merge_rows"] <= 0:
        faults.append("no request was attributed to a chain merge")
    record(
        "check_05c_every_new_request_has_a_cause",
        not faults,
        f"api_calls={total} merges={cost['totals']['merge_rows']} "
        f"claims={cost['totals']['claim_rows']}; " + "; ".join(faults[:4]),
    )


def check_05d_the_fast_sweep_is_recorded_green() -> None:
    """Positive 5d: the fast set ran, whole, and nothing else in it failed.

    Read from this batch's copy of the runner's completion marker rather than by
    launching a sweep: a gate that starts one nests a sweep inside a sweep, and
    an interrupted nested sweep leaves an orphan holding the lock.

    This gate's own row is not read for its exit code, and cannot be. The
    marker is written by the sweep that produced it, and this gate is red in
    that sweep for exactly one reason -- the marker did not exist yet, which is
    what 05f reports. A record in which this gate is green is therefore a record
    of a sweep that ran after itself, which is not a thing. b11.5's 02d is
    written the same way and for the same reason. What is asserted here is that
    every *other* fast gate was green, that none was skipped, and that this one
    was in the set; that this one is green is what the full sweep says, and it
    says it about the tree rather than about a file.
    """
    faults = []
    try:
        sweep = load(SWEEP)
    except evidence.EvidenceMissing as absent:
        skip("check_05d_the_fast_sweep_is_recorded_green", [str(absent)])
        return
    own = Path(__file__).name
    if sweep["set"] != "fast":
        faults.append(f"the marker is for the {sweep['set']!r} set")
    others = [gate for gate in sweep["failing"] if gate != own]
    if others:
        faults.append(f"failing: {others}")
    if sweep["missing"]:
        faults.append(f"not run: {sweep['missing']}")
    if own not in [row["gate"] for row in sweep["gates"]]:
        faults.append("this gate was not in the sweep")
    record(
        "check_05d_the_fast_sweep_is_recorded_green",
        not faults,
        f"gates={sweep.get('gates_run')}; " + "; ".join(faults[:4]),
    )


def check_05e_the_gate_names_no_run_local_identifier() -> None:
    """Negative 5e: no assertion here is anchored to a debug id.

    CLAUDE.md section 5.13. A debug id is reassigned every run, so an assertion
    holding one is only about the run that produced it. Checked over this gate's
    own source, which is where such an anchor would appear.
    """
    faults = []
    source = Path(__file__).read_text(encoding="utf-8")
    # Assembled rather than written out, so this check does not report itself.
    needle = "debug" + "_id"
    for match in re.finditer(needle, source):
        line = source[: match.start()].count("\n") + 1
        faults.append(f"line {line} names a run local identifier")
    record(
        "check_05e_the_gate_names_no_run_local_identifier",
        not faults,
        "; ".join(faults[:3]),
    )


def check_05f_the_evidence_this_gate_reads_is_declared() -> None:
    """Positive 5f: every file this gate reads is declared and present.

    CLAUDE.md section 4.16: the retention policy walks the declaration, so a
    file read but not declared is a file that can be taken away under a gate
    still asserting about it.
    """
    faults = []
    missing = []
    for name in GATE_EVIDENCE:
        try:
            evidence.read_bytes(name)
        except evidence.EvidenceMissing:
            missing.append(name)
    if missing:
        faults.append(f"declared but absent: {missing[:3]}")
    source = Path(__file__).read_text(encoding="utf-8")
    for name in ("premise_check.json", "t1_boxed_measure.json", "t1_boxed_review.json",
                 "t2_prediction.json", "cost_attribution.json", "run_all.fast.json"):
        if name not in source:
            faults.append(f"{name} is declared and never read")
    record(
        "check_05f_the_evidence_this_gate_reads_is_declared",
        not faults,
        f"declared={len(GATE_EVIDENCE)}; " + "; ".join(faults[:4]),
    )


# --- 06 the two determinations --------------------------------------------------


def check_06a_the_premises_were_checked_before_anything_was_built() -> None:
    """Positive 6a: the plan's seven premises were verified, and hold."""
    faults = []
    try:
        premises = load(PREMISE)
    except evidence.EvidenceMissing as absent:
        skip("check_06a_the_premises_were_checked_before_anything_was_built",
             [str(absent)])
        return
    if premises["base_tag"] != PREVIOUS_TAG:
        faults.append(f"checked against {premises['base_tag']!r}")
    if sorted(premises["premises"]) != [str(n) for n in range(1, 8)]:
        faults.append(f"premises {sorted(premises['premises'])}")
    for name, entry in premises["premises"].items():
        if not entry["holds"]:
            faults.append(f"premise {name} does not hold")
    record(
        "check_06a_the_premises_were_checked_before_anything_was_built",
        not faults,
        "; ".join(faults[:4]),
    )


def check_06b_the_boxed_gate_was_measured_before_it_was_refused() -> None:
    """Positive 6b: T1's second half was decided from a measurement, and did not ship.

    The determination-first arrangement, asserted as a sequence rather than as a
    result: the measurement lists what the declared rule catches; the review
    rules on every instance the measurement caught in a panel smaller than the
    page; the determination records that the gate does not ship, with its cause;
    and the configuration carries no boxed parameter, which is that decision on
    disk rather than in prose.
    """
    faults = []
    try:
        measure = load(BOXED_MEASURE)
        review = load(BOXED_REVIEW)
    except evidence.EvidenceMissing as absent:
        skip("check_06b_the_boxed_gate_was_measured_before_it_was_refused",
             [str(absent)])
        return
    caught = sum(
        result["counts"]["inside"]
        for result in measure["samples"].values()
        if "counts" in result
    )
    body = sum(
        result["counts"]["body_paragraphs"]
        for result in measure["samples"].values()
        if "counts" in result
    )
    if caught <= 0:
        faults.append("the rule catches nothing, so the reading is empty")
    if review["totals"]["inside"] != caught:
        faults.append(
            f"the review read {review['totals']['inside']} of {caught} instances"
        )
    if review["totals"]["reviewed"] <= 0:
        faults.append("no instance was reviewed by hand")
    if review["boxed_exclusion_ships"] is not False:
        faults.append("the review says the gate ships")
    if review["totals"]["inside_a_full_page_panel"] <= 0:
        faults.append("no full page panel in the catch, so the cause is not shown")

    with INDENT_CONFIG.open(encoding="utf-8") as f:
        config = json.load(f)
    boxed = [key for key in config if "box" in key.lower()]
    if boxed:
        faults.append(f"the configuration carries {boxed}")
    source = (ROOT / "babeldoc" / "magazine" / "indent_policy.py").read_text(
        encoding="utf-8"
    )
    if "fill_background" in source:
        faults.append("the pass reads a filled panel after all")
    register = GAP_REGISTER.read_text(encoding="utf-8")
    if "GAP-41" not in register:
        faults.append("GAP-41 is not registered")
    record(
        "check_06b_the_boxed_gate_was_measured_before_it_was_refused",
        not faults,
        f"caught {caught} of {body} body paragraphs, "
        f"{review['totals']['inside_a_full_page_panel']} on the paper; "
        + "; ".join(faults[:4]),
    )


def check_06c_the_prediction_and_the_run_agree() -> None:
    """Positive 6c: the offline prediction and the run reached the same set.

    The prediction drove the shipped code over the frozen b10.5 checkpoints
    before a request was spent. It is not the batch's evidence -- the run is --
    and the reason to keep it is exactly this comparison: two independent
    passes over the same documents, one of which never called the engine,
    agreeing on which column pairs became edges.
    """
    faults = []
    try:
        prediction = load(PREDICTION)
    except evidence.EvidenceMissing as absent:
        skip("check_06c_the_prediction_and_the_run_agree", [str(absent)])
        return
    for pair in ruled_pairs():
        sample = pair["sample"]
        label = boundary_label(pair)
        predicted = any(
            edge["boundary"] == label
            for edge in prediction["samples"].get(sample, {}).get("edges", ())
        )
        try:
            actual = label in edges_of(sample)
        except evidence.EvidenceMissing as absent:
            faults.append(f"{sample}: {absent}")
            continue
        if predicted != actual:
            faults.append(
                f"{sample} {label}: predicted {predicted}, the run gave {actual}"
            )
    summary = prediction.get("against_the_ruling") or {}
    if summary.get("true_taken") != 16 or summary.get("false_taken") != 1:
        faults.append(
            f"the prediction took {summary.get('true_taken')}/16 true and "
            f"{summary.get('false_taken')}/8 false"
        )
    record(
        "check_06c_the_prediction_and_the_run_agree",
        not faults,
        "; ".join(faults[:4]),
    )


def check_06d_the_moved_assertions_are_registered() -> None:
    """Positive 6d: every proposition this batch moved is written down.

    Three gates changed what they assert, and one deviation from the plan's
    surface was taken. Each has a register entry, and the entry has to name the
    gate it belongs to, or the register would be a list of numbers.
    """
    faults = []
    contracts = CONTRACTS.read_text(encoding="utf-8")
    for name, gate in (
        ("AC-18", "spec_check_b4.py"),
        ("AC-19", "spec_check_b11_2.py"),
        ("AC-20", "spec_check_b11_5.py"),
        ("AC-21", "spec_check_b5.py"),
        ("AC-22", "spec_check_b11_5.py"),
    ):
        if name not in contracts:
            faults.append(f"{name} is not registered")
        elif gate not in contracts.split(name, 1)[1][:1200]:
            faults.append(f"{name} does not name {gate}")
    waivers = WAIVERS.read_text(encoding="utf-8")
    for name, named in (
        ("W-B11-18", ("taxonomy.py", "column_continuity.py")),
        (
            "W-B11-19",
            (
                "spec_check_b4.py",
                "spec_check_b11_2.py",
                "spec_check_b11_5.py",
                "spec_check_b1.py",
                "spec_check_b5.py",
                "spec_check_e0.py",
            ),
        ),
    ):
        if name not in waivers:
            faults.append(f"{name} is not registered")
            continue
        entry = waivers.split(name, 1)[1][:1600]
        for path in named:
            if path not in entry:
                faults.append(f"{name} does not name {path}")
    register = GAP_REGISTER.read_text(encoding="utf-8")
    for gap in GAPS:
        if gap not in register:
            faults.append(f"{gap} is not registered")
    record(
        "check_06d_the_moved_assertions_are_registered",
        not faults,
        "; ".join(faults[:4]),
    )


CHECKS = (
    check_01a_the_contents_page_is_left_as_the_source_set_it,
    check_01b_the_article_pages_keep_every_indent,
    check_01c_an_undeclared_page_is_skipped_whole,
    check_01d_the_gate_is_declared_and_not_named,
    check_01e_the_gate_is_driven_not_reasoned,
    check_02a_the_ruling_is_a_filled_in_truth_file,
    check_02b_every_pair_that_continues_became_an_edge,
    check_02c_no_pair_that_does_not_continue_became_an_edge,
    check_02d_a_redundant_skip_is_dropped_and_its_text_still_reached,
    check_02e_a_page_of_records_yields_no_column_boundary,
    check_02f_a_head_under_a_display_line_is_refused,
    check_02g_the_four_gates_are_declarations,
    check_02h_the_page_boundaries_did_not_move,
    check_03a_the_broken_clause_is_one_sentence,
    check_03b_a_word_broken_at_the_break_is_closed_up,
    check_03c_each_half_is_set_in_its_own_column,
    check_04a_the_pieces_join_back_to_the_whole,
    check_04b_the_pages_and_paragraphs_are_the_same_ones,
    check_04c_the_detectors_did_not_find_more,
    check_05a_the_delta_is_the_declared_surface,
    check_05b_no_upstream_file_was_touched,
    check_05c_every_new_request_has_a_cause,
    check_05d_the_fast_sweep_is_recorded_green,
    check_05e_the_gate_names_no_run_local_identifier,
    check_05f_the_evidence_this_gate_reads_is_declared,
    check_06a_the_premises_were_checked_before_anything_was_built,
    check_06b_the_boxed_gate_was_measured_before_it_was_refused,
    check_06c_the_prediction_and_the_run_agree,
    check_06d_the_moved_assertions_are_registered,
)


def main() -> int:
    print("spec_check_b11_6: an indent double gate, and in-page column chains\n")
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
