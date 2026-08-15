"""Gate script for batch E1 (the metric implementations).

Run from the repository root:

    python spec_checks/spec_check_e1.py

Exit code 0 when every assertion E1 answers for passes, 1 otherwise. Needs no
API key, makes no network request and runs no pipeline. Every metric this batch
delivers is deterministic by construction, and this gate is the demonstration:
each one is driven over documents built here, whose answers can be worked out by
hand, so a failure names the metric rather than the corpus.

01 is the configuration: every parameter the metrics read is bounded, and the
metrics package refuses a configuration that is not.

02 is the mid-unit page-break rate over synthetic pages, verdict by verdict:
closed, open, the display continuation that is not a defect, the boundary the
method cannot answer for, and the two denominators the rate and its strict form
divide by. The boundary cases the plan names are here -- an empty page, a page
with one element, a document with one page and therefore no boundary.

03 is the block conservation invariant at each of its three levels, holding and
failing, and the one thing it must never do: come out true because nobody
looked.

04 is LTCR against the pairwise definition, with the relation to the legacy
share asserted rather than described. Three properties are checked over
constructed groupings: the legacy share bounds LTCR from above, the two reach
1.0 together and only together, and LTCR is zero exactly when the legacy share
is 1/k, which is the reading the legacy measure gives a term nobody rendered
twice the same way.

05 is the layout geometry: Overlap and Alignment against values computed by
hand from the definitions, the identity pair, the g function's domain at both
ends, the degenerate element, and the image pairing including the unpaired case.

06 is the entry point over a frozen working directory, which is the only
assertion here that reads a produced artefact. It is in the pipeline tier
because it depends on a run this batch did not make.

07 is the scope: this batch adds a metrics package, a tool, a configuration and
its own gate, and touches the evaluation documents. Nothing under prompts/ or
corpus/ or reviews/, and no upstream file at all.

08 is the negative twin of the whole batch: no metric may reach a translator, a
model client or a credential, and none may name a publication.

The rest is the second session, which computed rather than implemented.

10 is the mid-unit rate's stratification: the strata are read off the corpus
ruling and its note, and the headline rate is deaf to a boundary no producer
could have closed.

11 is the leave-one-publication-out matrix: on disk, arithmetically consistent,
and recomputing to the same bytes.

12 is the two geometry paths measured against each other on the one artefact
both can read, with the deviation written into the contract rather than assumed.

13 is the corpus sweep: every registered sample in every configuration this
repository holds, or a stated reason there is no such run.

14 is the policy column ledger row C-04 was missing, recomputed offline for
every model tier.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.metrics import MetricError  # noqa: E402
from babeldoc.magazine.metrics import conservation  # noqa: E402
from babeldoc.magazine.metrics import layout_geometry  # noqa: E402
from babeldoc.magazine.metrics import load_metrics_config  # noqa: E402
from babeldoc.magazine.metrics import ltcr  # noqa: E402
from babeldoc.magazine.metrics import mid_break_rate  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Both sessions of batch E1, in order. The scope assertion reads the union of
# the deltas the tags that exist introduced, plus the working tree while the
# last of them is still uncut, so a session does not stop covering itself the
# moment the session before it is frozen.
BATCH_TAGS = ("batch-e1.1", "batch-e1.2")

PYTHON = sys.executable

PACKAGE = ROOT / "babeldoc" / "magazine" / "metrics"
CONFIG = ROOT / "configs" / "metrics.json"
TOOL = ROOT / "tools" / "eval_report.py"
LOPO_TOOL = ROOT / "tools" / "lopo.py"
CONTRACT = ROOT / "docs" / "eval" / "metric_contract.md"

# What the second session computed. Tracked, because the whole point of B-02 is
# that a matrix nobody wrote down is a matrix nobody has.
RESULTS = ROOT / "docs" / "eval" / "results_e1"
LOPO_RESULT = RESULTS / "lopo_v2.json"
CORPUS_RESULT = RESULTS / "eval_corpus.json"
POLICY_RESULT = RESULTS / "vlm_policy_c04.json"

# A frozen working directory the entry point is driven over. Produced by batch
# b8.4; this batch makes no run of its own.
FROZEN_RUN = (
    ROOT / "examples" / "output" / "b8_4" / "smoke" / "Courier-en" / "work" / "Courier-en"
)
FROZEN_SAMPLE = "Courier-en.pdf"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Assertions that read a produced artefact rather than one built here, skipped
# by the fast tier during iteration and run before any tag is cut.
PIPELINE_TIER = (
    "check_06_the_entry_point_over_a_frozen_run",
    "check_11b_the_fold_matrix_recomputes_bit_for_bit",
)

# Paths this session may change. The metrics package, the tool, the bounded
# configuration, the evaluation documents, this gate and the runner; plus the
# evidence intake T-E1.0 carried out, which is files entering git and nothing
# being edited. The two docs/dissertation prefixes are that intake: the chapter
# the metric contract resolves its equation labels against, and the rasters and
# evidence section the ledger cites for the chain A/B figure.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/metrics/",
    "configs/",
    "docs/dissertation/",
    "docs/dissertation_assets/",
    "docs/eval/",
    "examples/baseline/",
    "examples/output/",
    "plans/",
    "spec_checks/",
    "tools/",
)
# ``.gitignore`` is here for one line: the repository ignores every ``*.json``
# and un-ignores the directories whose JSON is meant to be kept, and the results
# of this session are such a directory. Without it the fold matrix would be
# produced, reported and silently never committed, which is B-02 happening a
# second time. Registered as W-E1-01.
ALLOWED_FILES = {".gitignore", "UPSTREAM_DIFF.md", "WAIVERS.md"}

# Everything under babeldoc/ that is not the new package is upstream or an
# earlier batch's, with one exception: the term consistency tool's measurement
# core moved into the metrics package, so the tool changed too and is inside
# tools/ where the whitelist already allows it.
EXTENSION_PREFIX = "babeldoc/magazine/"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_e1")


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
    _, listing = git_output(["diff", "--name-only", "HEAD"])
    paths |= {line.strip() for line in listing.splitlines() if line.strip()}
    _, staged = git_output(["diff", "--name-only", "--cached"])
    paths |= {line.strip() for line in staged.splitlines() if line.strip()}
    _, untracked = git_output(["status", "--porcelain", "--untracked-files=all"])
    for line in untracked.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


# --- building documents to measure --------------------------------------------


def _box(x, y, x2, y2):
    return il_version_1.Box(x=x, y=y, x2=x2, y2=y2)


def _character(text: str, x: float, y: float, size: float = 10.0):
    return il_version_1.PdfCharacter(
        char_unicode=text, box=_box(x, y, x + size, y + size)
    )


def _paragraph(
    text: str,
    x: float,
    y: float,
    width: float,
    label: str = "plain text",
    *,
    lines: int = 1,
    chain_id: str | None = None,
    chain_index: int | None = None,
    sentence: tuple[int, int] | None = None,
    vertical: bool = False,
):
    """One paragraph whose characters sit on ``lines`` bands, the last one last.

    The text is laid on the final band and the earlier bands carry filler, so a
    metric reading "the last rendered line" has more than one line to be wrong
    about.
    """
    size = 10.0
    compositions = []
    for band in range(lines - 1):
        for position, char in enumerate("filler"):
            compositions.append(
                il_version_1.PdfParagraphComposition(
                    pdf_character=_character(
                        char, x + position * size, y + (lines - 1 - band) * 12.0, size
                    )
                )
            )
    for position, char in enumerate(text):
        compositions.append(
            il_version_1.PdfParagraphComposition(
                pdf_character=_character(char, x + position * size, y, size)
            )
        )
    return il_version_1.PdfParagraph(
        box=_box(x, y, x + width, y + 12.0 * lines),
        unicode=text,
        layout_label=label,
        debug_id=f"{label}-{x:.0f}-{y:.0f}",
        vertical=vertical,
        chain_id=chain_id,
        chain_index=chain_index,
        segment_sentence_start=None if sentence is None else sentence[0],
        segment_sentence_end=None if sentence is None else sentence[1],
        pdf_paragraph_composition=compositions,
    )


def _page(paragraphs, number: int = 0, figures=(), width: float = 600.0, height: float = 800.0):
    return il_version_1.Page(
        page_number=number,
        mediabox=il_version_1.Mediabox(box=_box(0.0, 0.0, width, height)),
        cropbox=il_version_1.Cropbox(box=_box(0.0, 0.0, width, height)),
        pdf_paragraph=list(paragraphs),
        page_layout=[
            il_version_1.PageLayout(
                id=index, box=box, conf=1.0, class_name="figure"
            )
            for index, box in enumerate(figures)
        ],
    )


def _document(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


# --- 01 the configuration ------------------------------------------------------


def check_01a_every_parameter_is_bounded() -> None:
    """Positive 1a: the metrics configuration declares a range for every number."""
    with CONFIG.open(encoding="utf-8") as f:
        raw = json.load(f)
    faults = []
    for key, value in raw.items():
        if key == "description" or key.endswith("_allowed_range"):
            continue
        if isinstance(value, list):
            if not value or any(not isinstance(item, str) or not item for item in value):
                faults.append(f"{key} is not a vocabulary")
            continue
        if f"{key}_allowed_range" not in raw:
            faults.append(f"{key} has no allowed range")
    config = load_metrics_config()
    if config.ltcr_min_paragraphs < 2:
        faults.append("ltcr_min_paragraphs below 2 leaves C(k,2) with no pair")
    if not 0.0 < config.alignment_max_delta < 1.0:
        faults.append("alignment_max_delta is outside the domain of g")
    record("check_01a_every_parameter_is_bounded", not faults, "; ".join(faults))


def check_01b_an_unbounded_parameter_is_refused(tmp: Path) -> None:
    """Negative 1b: a configuration missing a range does not load.

    The rule is only a rule if breaking it fails. A number without its bound is
    a threshold nobody agreed to, which is the thing configs/ exists to stop.
    """
    with CONFIG.open(encoding="utf-8") as f:
        raw = json.load(f)
    raw.pop("min_element_area_ratio_allowed_range", None)
    path = tmp / "unbounded.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    faults = []
    try:
        load_metrics_config(str(path))
    except MetricError:
        pass
    except Exception as exc:  # noqa: BLE001 - any other failure is the wrong one
        faults.append(f"raised {exc!r} rather than MetricError")
    else:
        faults.append("an unbounded parameter loaded")
    record("check_01b_an_unbounded_parameter_is_refused", not faults, "; ".join(faults))


# --- 02 the mid-unit page-break rate ------------------------------------------


def check_02a_verdicts_over_synthetic_pages() -> None:
    """Positive 2a: each verdict is produced by the page shape that should produce it.

    Four boundaries over five pages: a tail closing on a full stop, a tail
    stopping mid-word, a display continuation with no sentence interval, and a
    vertical tail the method refuses to judge.
    """
    chain_config = load_chain_config()
    pages = [
        _page([_paragraph("A sentence ends here.", 40.0, 700.0, 500.0, lines=3)], 0),
        _page([_paragraph("and it carries on", 40.0, 700.0, 500.0, lines=3)], 1),
        _page(
            [
                _paragraph(
                    "Display half one",
                    40.0,
                    700.0,
                    500.0,
                    label="title",
                    chain_id="c1",
                    chain_index=0,
                    sentence=(-1, -1),
                )
            ],
            2,
        ),
        _page(
            [
                _paragraph(
                    "Display half two",
                    40.0,
                    700.0,
                    500.0,
                    label="title",
                    chain_id="c1",
                    chain_index=1,
                    sentence=(-1, -1),
                    vertical=True,
                )
            ],
            3,
        ),
        _page([_paragraph("A closing page.", 40.0, 700.0, 500.0)], 4),
    ]
    result = mid_break_rate.measure(_document(pages), chain_config)
    series = result["series"][mid_break_rate.PAGE_SERIES]
    verdicts = [item["verdict"] for item in series["boundaries"]]
    expected = [
        mid_break_rate.CLOSED,
        mid_break_rate.OPEN,
        mid_break_rate.DESIGNED,
        mid_break_rate.AXIS_UNSUPPORTED,
    ]
    faults = []
    if verdicts != expected:
        faults.append(f"verdicts {verdicts} against {expected}")
    # One open boundary of four; the strict form drops the designed one from the
    # denominator and the unsupported one is outside it either way: 1/2.
    if series["rate"] != 0.25:
        faults.append(f"rate {series['rate']} against 0.25")
    if series["strict_rate"] != 0.5:
        faults.append(f"strict rate {series['strict_rate']} against 0.5")
    last = series["boundaries"][1]["tail"]["last_character"]
    if last != "n":
        faults.append(f"the open tail's last character is {last!r}, not the line's")
    record("check_02a_verdicts_over_synthetic_pages", not faults, "; ".join(faults))


def check_02b_the_last_line_is_read_not_the_string() -> None:
    """Positive 2b: the character read is the last rendered line's, not the field's.

    A paragraph whose ``unicode`` ends in a full stop while its final rendered
    band ends mid-word has to come out open. This is the whole reason the metric
    is defined on geometry, and the only assertion that can tell the two apart.
    """
    chain_config = load_chain_config()
    paragraph = _paragraph("a line that stops mid senten", 40.0, 700.0, 500.0, lines=2)
    paragraph.unicode = "a string that ends with a full stop."
    pages = [_page([paragraph], 0), _page([_paragraph("Next.", 40.0, 700.0, 500.0)], 1)]
    result = mid_break_rate.measure(_document(pages), chain_config)
    boundary = result["series"][mid_break_rate.PAGE_SERIES]["boundaries"][0]
    record(
        "check_02b_the_last_line_is_read_not_the_string",
        boundary["verdict"] == mid_break_rate.OPEN
        and boundary["tail"]["last_character"] == "n",
        f"verdict={boundary['verdict']} last={boundary['tail']['last_character']!r}",
    )


def check_02c_boundary_shapes() -> None:
    """Positive 2c: the edges of the definition -- one page, an empty page, one element.

    A one-page document has no boundary and therefore no rate, and ``None`` is
    the answer rather than zero. An empty page offers no tail, which is its own
    verdict and enters no numerator. A page with one paragraph is an ordinary
    tail and has to be judged like any other.
    """
    chain_config = load_chain_config()
    faults = []

    single = mid_break_rate.measure(
        _document([_page([_paragraph("Alone.", 40.0, 700.0, 500.0)], 0)]), chain_config
    )
    if single["series"][mid_break_rate.PAGE_SERIES]["boundaries_total"] != 0:
        faults.append("a one page document produced a boundary")
    if single["rate"] is not None:
        faults.append(f"a one page document has a rate of {single['rate']}")

    empty = mid_break_rate.measure(
        _document([_page([], 0), _page([_paragraph("After.", 40.0, 700.0, 500.0)], 1)]),
        chain_config,
    )
    boundary = empty["series"][mid_break_rate.PAGE_SERIES]["boundaries"][0]
    if boundary["verdict"] != mid_break_rate.NO_TAIL:
        faults.append(f"an empty page gave the verdict {boundary['verdict']}")
    if boundary["tail"] is not None:
        faults.append("an empty page produced a tail")
    if empty["series"][mid_break_rate.PAGE_SERIES]["strict_rate"] is not None:
        faults.append("a document with no answerable boundary produced a strict rate")

    lonely = mid_break_rate.measure(
        _document(
            [
                _page([_paragraph("one element open", 40.0, 700.0, 500.0)], 0),
                _page([_paragraph("Second.", 40.0, 700.0, 500.0)], 1),
            ]
        ),
        chain_config,
    )
    if lonely["rate"] != 1.0:
        faults.append(f"a single element tail gave {lonely['rate']} rather than 1.0")
    record("check_02c_boundary_shapes", not faults, "; ".join(faults))


def check_02d_the_column_series_is_separate() -> None:
    """Positive 2d: column boundaries are counted, and counted apart from pages.

    Two columns on one page make one column boundary and no page boundary. A
    metric that merged the two series would report a two column page as having
    a page break it does not have.
    """
    chain_config = load_chain_config()
    page = _page(
        [
            _paragraph("left column runs on", 40.0, 700.0, 220.0),
            _paragraph("right column ends.", 330.0, 700.0, 220.0),
        ],
        0,
    )
    result = mid_break_rate.measure(_document([page]), chain_config)
    columns = result["series"][mid_break_rate.COLUMN_SERIES]
    pages = result["series"][mid_break_rate.PAGE_SERIES]
    faults = []
    if pages["boundaries_total"] != 0:
        faults.append(f"{pages['boundaries_total']} page boundary on a one page document")
    if columns["boundaries_total"] != 1:
        faults.append(f"{columns['boundaries_total']} column boundaries, not 1")
    elif columns["boundaries"][0]["verdict"] != mid_break_rate.OPEN:
        faults.append(f"the column tail read {columns['boundaries'][0]['verdict']}")
    record("check_02d_the_column_series_is_separate", not faults, "; ".join(faults))


def check_02e_the_ender_set_comes_from_the_detector() -> None:
    """Negative 2e: the metric writes down no sentence ender of its own.

    Every mark it treats as closing a sentence has to be in
    ``configs/chain_detection.json``. A metric carrying a second list would let
    a retune move the detector and leave the measurement behind.
    """
    chain_config = load_chain_config()
    terminals = set(chain_config["terminal_punctuation"])
    source = (PACKAGE / "mid_break_rate.py").read_text(encoding="utf-8")
    faults = []
    for mark in terminals:
        if f'"{mark}"' in source or f"'{mark}'" in source:
            faults.append(f"the ender {mark!r} is written into the metric")
    # And the metric honours a mark the configuration declares: a CJK full stop
    # closes a boundary exactly as a Latin one does.
    pages = [
        _page(
            [_paragraph("a full line ending on a mark" + "\u3002", 40.0, 700.0, 500.0)],
            0,
        ),
        _page([_paragraph("A following page of text.", 40.0, 700.0, 500.0)], 1),
    ]
    result = mid_break_rate.measure(_document(pages), chain_config)
    verdict = result["series"][mid_break_rate.PAGE_SERIES]["boundaries"][0]["verdict"]
    if verdict != mid_break_rate.CLOSED:
        faults.append(f"a declared CJK ender read {verdict}")
    record(
        "check_02e_the_ender_set_comes_from_the_detector", not faults, "; ".join(faults)
    )


# --- 03 the conservation invariant --------------------------------------------


def _chain_report(translation: str, spans, escalated=()) -> dict:
    return {
        "chains": [
            {
                "chain_id": "c1",
                "translation": translation,
                "members": [
                    {"debug_id": f"m{index}", "segment": {"start": start, "end": end}}
                    for index, (start, end) in enumerate(spans)
                ],
            }
        ],
        "counts": {"merged_members": len(spans) + len(escalated)},
        "escalated": list(escalated),
    }


def check_03a_the_three_levels_hold_and_fail() -> None:
    """Positive 3a: each level says yes to conservation and no to its own breach."""
    faults = []
    good = conservation.chain_level(_chain_report("abcdef", [(0, 3), (3, 6)]))
    if not good.holds:
        faults.append(f"a tiling chain failed: {good.failures}")
    gap = conservation.chain_level(_chain_report("abcdef", [(0, 2), (3, 6)]))
    if gap.holds:
        faults.append("a chain with a gap passed")
    short = conservation.chain_level(_chain_report("abcdef", [(0, 3), (3, 5)]))
    if short.holds:
        faults.append("a chain leaving a character unrendered passed")
    escalated = conservation.chain_level(
        _chain_report("abcdef", [(0, 6)], escalated=[{"debug_id": "m1"}])
    )
    if not escalated.holds:
        faults.append(f"an explicitly escalated member failed: {escalated.failures}")
    unaccounted = _chain_report("abcdef", [(0, 6)])
    unaccounted["counts"]["merged_members"] = 3
    if conservation.chain_level(unaccounted).holds:
        faults.append("a member that is neither rendered nor escalated passed")

    conserving = {
        "conservation": {
            "pages_before": 8,
            "pages_after": 8,
            "paragraphs_before": 132,
            "paragraphs_after": 132,
            "touched_refs": ["p6#15"],
            "changed_refs": ["p6#15"],
            "changed_outside_touched": [],
            "verdict": "conserved",
        }
    }
    if not conservation.repair_level(conserving).holds:
        faults.append("a conserving repair failed")
    for field, value in (
        ("paragraphs_after", 131),
        ("pages_after", 9),
    ):
        broken = {"conservation": dict(conserving["conservation"], **{field: value})}
        if conservation.repair_level(broken).holds:
            faults.append(f"a repair changing {field} passed")
    stray = {
        "conservation": dict(
            conserving["conservation"], changed_refs=["p6#15", "p1#2"]
        )
    }
    if conservation.repair_level(stray).holds:
        faults.append("a repair changing a paragraph it never touched passed")

    if not conservation.document_level(8, 8).holds:
        faults.append("an eight page document against itself failed")
    if conservation.document_level(8, 7).holds:
        faults.append("a document that lost a page passed")
    record("check_03a_the_three_levels_hold_and_fail", not faults, "; ".join(faults))


def check_03b_absent_evidence_is_not_a_pass() -> None:
    """Negative 3b: a level with nothing to read is None, and never True.

    The most dangerous number this evaluation could produce is a conservation
    verdict of true arrived at by having no evidence to contradict it.
    """
    faults = []
    for verdict in (
        conservation.chain_level(None),
        conservation.repair_level(None),
        conservation.repair_level({}),
        conservation.document_level(None, 8),
        conservation.document_level(8, None),
    ):
        if verdict.holds is not None:
            faults.append(f"{verdict.level} answered {verdict.holds} with no evidence")
    empty = conservation.measure()
    if empty["holds"] is not None:
        faults.append(f"a run with no evidence at all answered {empty['holds']}")
    if sorted(empty["levels_absent"]) != sorted(conservation.LEVELS):
        faults.append(f"absent levels {empty['levels_absent']}")
    partial = conservation.measure(chain_report=_chain_report("ab", [(0, 2)]))
    if partial["holds"] is not True:
        faults.append("a run with one holding level did not report it")
    if partial["levels_present"] != [conservation.CHAIN_LEVEL]:
        faults.append(f"present levels {partial['levels_present']}")
    record("check_03b_absent_evidence_is_not_a_pass", not faults, "; ".join(faults))


# --- 04 LTCR -------------------------------------------------------------------


def _renderings(groups: list[int], filler_length: int = 40, base: int = 0x8000) -> list[str]:
    """One translation per paragraph, ``groups`` saying how many share a rendering.

    Built from disjoint code point ranges so that a substring shared by two
    translations can only be a shared rendering, and padded so the candidate
    search has an outside to filter against.
    """
    texts = []
    for index, size in enumerate(groups):
        rendering = "".join(map(chr, range(base + index * 16, base + index * 16 + 4)))
        for position in range(size):
            start = 0x9000 + (index * 8 + position) * filler_length
            filler = "".join(map(chr, range(start, start + filler_length)))
            texts.append(rendering + filler)
    return texts


def check_04a_the_pairwise_count_is_the_definition() -> None:
    """Positive 4a: LTCR is the agreeing pairs over C(k,2), on hand-built groupings."""
    config = ltcr.load_config()
    faults = []
    for groups in ([4], [3, 1], [2, 2], [1, 1, 1, 1], [2, 1]):
        inside = _renderings(groups)
        outside = _renderings([1], filler_length=60, base=0x4E00)
        result = ltcr.ltcr_of(inside, outside, config)
        k = sum(groups)
        expected_pairs = sum(size * (size - 1) // 2 for size in groups)
        total = k * (k - 1) // 2
        if result["pairs_agreeing"] != expected_pairs:
            faults.append(
                f"{groups}: {result['pairs_agreeing']} agreeing pairs against "
                f"{expected_pairs} (groups found {result['group_sizes']})"
            )
        if result["pairs_total"] != total:
            faults.append(f"{groups}: C(k,2) came out {result['pairs_total']}")
        if not math.isclose(result["ltcr"], expected_pairs / total):
            faults.append(f"{groups}: ltcr {result['ltcr']}")
    record("check_04a_the_pairwise_count_is_the_definition", not faults, "; ".join(faults))


def check_04b_the_relation_to_the_legacy_share() -> None:
    """Positive 4b: the three properties relating LTCR to what b6.3 measured.

    Stated in the module docstring and asserted here rather than trusted: the
    legacy share bounds LTCR above, the two reach 1.0 together and only
    together, and LTCR is zero exactly when the legacy share is 1/k. The two do
    not agree at k = 2, and the case is in the table below so that the
    disagreement is pinned rather than discovered later.
    """
    config = ltcr.load_config()
    faults = []
    for groups in ([4], [3, 1], [2, 2], [2, 1], [1, 1], [5], [3, 2], [1, 1, 1]):
        inside = _renderings(groups)
        outside = _renderings([1], filler_length=60, base=0x4E00)
        result = ltcr.ltcr_of(inside, outside, config)
        value = result["ltcr"]
        legacy = result["legacy_share"]
        if value is None or legacy is None:
            faults.append(f"{groups}: unmeasured")
            continue
        if value > legacy + 1e-12:
            faults.append(f"{groups}: ltcr {value} above legacy {legacy}")
        if (value == 1.0) != (legacy == 1.0):
            faults.append(f"{groups}: ltcr {value} and legacy {legacy} disagree at 1.0")
        k = sum(groups)
        if (value == 0.0) != math.isclose(legacy, 1 / k):
            faults.append(f"{groups}: ltcr {value} and legacy {legacy} disagree at 0")
    record("check_04b_the_relation_to_the_legacy_share", not faults, "; ".join(faults))


def check_04c_the_unmeasurable_is_not_measured() -> None:
    """Negative 4c: a term with fewer than two renderings has no LTCR at all.

    C(1,2) is zero and a ratio over it is not a small number, it is no number.
    The boundary case has to come back as None rather than as 0.0 or 1.0.
    """
    config = ltcr.load_config()
    faults = []
    for inside in ([], ["one rendering only"]):
        result = ltcr.ltcr_of(inside, [], config)
        if result["ltcr"] is not None or result["pairs_total"] != 0:
            faults.append(f"{len(inside)} rendering(s) gave {result}")
    summary = ltcr.summarise([], load_metrics_config().report_float_digits)
    if summary["ltcr"] is not None:
        faults.append(f"an empty term set summarised to {summary['ltcr']}")
    record("check_04c_the_unmeasurable_is_not_measured", not faults, "; ".join(faults))


def check_04d_the_corpus_rule_sums_rather_than_averages() -> None:
    """Positive 4d: a corpus LTCR sums numerators and denominators, per lyu2021ltcr.

    Two terms, one of four paragraphs fully consistent and one of two that are
    not, come to 6/7 and not to the 0.5 an average of the two ratios would give.
    """
    digits = load_metrics_config().report_float_digits
    rows = [
        {"ltcr": 1.0, "pairs_agreeing": 6, "pairs_total": 6, "legacy_share": 1.0},
        {"ltcr": 0.0, "pairs_agreeing": 0, "pairs_total": 1, "legacy_share": 0.5},
    ]
    summary = ltcr.summarise(rows, digits)
    record(
        "check_04d_the_corpus_rule_sums_rather_than_averages",
        math.isclose(summary["ltcr"], 6 / 7, rel_tol=1e-6)
        and summary["pairs_total"] == 7,
        f"{summary}",
    )


# --- 05 the layout geometry ----------------------------------------------------


def _element(left, bottom, right, top, kind="paragraph"):
    return layout_geometry.Element(
        kind=kind, left=left, bottom=bottom, right=right, top=top
    )


def check_05a_overlap_against_hand_computed_values() -> None:
    """Positive 5a: eq:overlap over boxes whose answer can be worked out on paper.

    Two identical unit-quarter boxes overlap one another completely, so each
    term is 1 and the per-element mean is 1. Two disjoint boxes give 0. One box
    covering a quarter of another gives (1/4 + 1)/2 by the asymmetry of the
    definition, which divides the shared area by each element's own area in turn.
    """
    config = load_metrics_config()
    faults = []
    same = [_element(0.0, 0.0, 0.5, 0.5), _element(0.0, 0.0, 0.5, 0.5)]
    if not math.isclose(layout_geometry.overlap(same, config)["value"], 1.0):
        faults.append(f"identical boxes gave {layout_geometry.overlap(same, config)}")
    apart = [_element(0.0, 0.0, 0.4, 0.4), _element(0.5, 0.5, 0.9, 0.9)]
    if layout_geometry.overlap(apart, config)["value"] != 0.0:
        faults.append("disjoint boxes overlapped")
    nested = [_element(0.0, 0.0, 1.0, 1.0), _element(0.0, 0.0, 0.5, 0.5)]
    expected = (0.25 / 1.0 + 0.25 / 0.25) / 2
    if not math.isclose(layout_geometry.overlap(nested, config)["value"], expected):
        faults.append(
            f"a nested pair gave {layout_geometry.overlap(nested, config)['value']} "
            f"against {expected}"
        )
    alone = layout_geometry.overlap([_element(0.0, 0.0, 0.5, 0.5)], config)
    if alone["value"] != 0.0:
        faults.append(f"a single element gave {alone['value']}")
    empty = layout_geometry.overlap([], config)
    if empty["value"] is not None:
        faults.append(f"an empty page gave {empty['value']}")
    record("check_05a_overlap_against_hand_computed_values", not faults, "; ".join(faults))


def check_05b_alignment_and_the_domain_of_g() -> None:
    """Positive 5b: eq:alignment, its identity case, and both ends of g's domain.

    Two boxes sharing a left edge have a minimum deviation of zero on that
    coordinate, so g(0) = 0 and the page's Alignment is 0. A page of fewer than
    two elements has no minimum to take and is None rather than 0. And the pole
    at x = 1 is not reachable: two elements at opposite edges of the unit page
    are clamped, so the value is finite.
    """
    config = load_metrics_config()
    faults = []
    aligned = [_element(0.1, 0.1, 0.4, 0.4), _element(0.1, 0.6, 0.4, 0.9)]
    value = layout_geometry.alignment(aligned, config)["value"]
    if value != 0.0:
        faults.append(f"two left aligned boxes gave {value}")
    lonely = layout_geometry.alignment([_element(0.0, 0.0, 0.5, 0.5)], config)
    if lonely["value"] is not None:
        faults.append(f"a one element page gave {lonely['value']}")
    extreme = [
        _element(0.0, 0.0, 0.0, 0.0 + 1e-9),
        _element(1.0, 1.0 - 1e-9, 1.0, 1.0),
    ]
    far = layout_geometry.alignment(extreme, config)["value"]
    if far is not None and not math.isfinite(far):
        faults.append("elements at opposite edges produced a non-finite value")
    offset = [_element(0.1, 0.1, 0.4, 0.4), _element(0.2, 0.6, 0.5, 0.9)]
    expected = -math.log(1 - 0.1)
    got = layout_geometry.alignment(offset, config)["value"]
    if not math.isclose(got, expected, rel_tol=1e-9):
        faults.append(f"a tenth of a page offset gave {got} against {expected}")
    record("check_05b_alignment_and_the_domain_of_g", not faults, "; ".join(faults))


def check_05c_degenerate_elements_are_dropped() -> None:
    """Negative 5c: a zero area element takes no part and is counted as dropped.

    eq:overlap divides by A(b_i). A zero area box has no such quantity, so it
    leaves both roles rather than being given a value that would be an arbitrary
    choice dressed as a measurement.
    """
    config = load_metrics_config()
    elements = [
        _element(0.0, 0.0, 0.5, 0.5),
        _element(0.0, 0.0, 0.5, 0.5),
        _element(0.2, 0.2, 0.2, 0.2),
    ]
    result = layout_geometry.overlap(elements, config)
    faults = []
    if result["dropped"] != 1:
        faults.append(f"{result['dropped']} dropped, not 1")
    if result["elements"] != 2:
        faults.append(f"{result['elements']} elements kept, not 2")
    if not math.isclose(result["value"], 1.0):
        faults.append(f"the degenerate element moved the value to {result['value']}")
    record("check_05c_degenerate_elements_are_dropped", not faults, "; ".join(faults))


def check_05d_image_pairing_and_the_unpaired_case() -> None:
    """Positive 5d: images pair by nearest area, and a lost one costs the score.

    An image in the same place scores 1. A document that lost one of two images
    scores the surviving pair over two, because the denominator is the larger of
    the two counts; a metric dividing by the pairs it happened to make would
    report losing an image as perfect placement.
    """
    config = load_metrics_config()
    faults = []
    source = [_element(0.1, 0.1, 0.4, 0.4, "figure"), _element(0.6, 0.6, 0.9, 0.9, "figure")]
    identical = layout_geometry.image_placement_iou(source, list(source), config)
    if not math.isclose(identical["value"], 1.0):
        faults.append(f"identical images scored {identical['value']}")
    lost = layout_geometry.image_placement_iou(source, [source[0]], config)
    if not math.isclose(lost["value"], 0.5):
        faults.append(f"a lost image scored {lost['value']} rather than 0.5")
    if lost["unpaired_source"] != 1:
        faults.append(f"{lost['unpaired_source']} unpaired source images")
    none = layout_geometry.image_placement_iou([], [], config)
    if none["value"] is not None:
        faults.append(f"a page with no images scored {none['value']}")
    refused = layout_geometry.image_placement_iou(
        [_element(0.0, 0.0, 0.9, 0.9, "figure")],
        [_element(0.0, 0.0, 0.05, 0.05, "figure")],
        config,
    )
    if refused["pairs"] != 0:
        faults.append("two images of wildly different areas were paired")
    record("check_05d_image_pairing_and_the_unpaired_case", not faults, "; ".join(faults))


def check_05e_the_deltas_over_a_whole_document() -> None:
    """Positive 5e: image area delta and page count delta over a built document.

    The identity pair is the case worth pinning: a document measured against
    itself has a delta of zero on every one of them, which is what makes a
    non-zero delta elsewhere mean something.
    """
    config = load_metrics_config()
    pages = [
        _page(
            [_paragraph("Body text here.", 40.0, 700.0, 500.0)],
            0,
            figures=[_box(100.0, 100.0, 300.0, 300.0)],
        ),
        _page([_paragraph("More body text.", 40.0, 700.0, 500.0)], 1),
    ]
    same = layout_geometry.measure(pages, pages, config)
    faults = []
    summary = same["summary"]
    for key in ("overlap_delta", "alignment_delta", "image_area_delta"):
        if summary[key] != 0.0:
            faults.append(f"the identity pair moved {key} to {summary[key]}")
    if summary["image_placement_iou"] != 1.0:
        faults.append(f"the identity pair scored {summary['image_placement_iou']}")
    if same["page_count_delta"]["value"] != 0 or not same["page_count_delta"]["conserved"]:
        faults.append(f"page count delta {same['page_count_delta']}")

    bigger = [
        _page(
            [_paragraph("Body text here.", 40.0, 700.0, 500.0)],
            0,
            figures=[_box(100.0, 100.0, 400.0, 300.0)],
        ),
        pages[1],
    ]
    grown = layout_geometry.measure(pages, bigger, config)
    if grown["summary"]["image_area_delta"] != 0.5:
        faults.append(
            f"a half again wider image gave {grown['summary']['image_area_delta']}"
        )
    shorter = layout_geometry.measure(pages, pages[:1], config)
    if shorter["page_count_delta"]["value"] != -1:
        faults.append(f"a lost page gave {shorter['page_count_delta']['value']}")
    if shorter["pages_compared"] != 1:
        faults.append(f"{shorter['pages_compared']} pages compared, not 1")
    record("check_05e_the_deltas_over_a_whole_document", not faults, "; ".join(faults))


# --- 06 the entry point --------------------------------------------------------


def check_06_the_entry_point_over_a_frozen_run() -> None:
    """Positive 6: the tool measures a real working directory, twice, identically.

    Determinism is the claim every one of these metrics rests on, and the only
    way to assert it is to run one twice. The artefact is batch b8.4's; this
    batch makes no run.
    """
    if not FROZEN_RUN.is_dir():
        record(
            "check_06_the_entry_point_over_a_frozen_run",
            False,
            f"{FROZEN_RUN.relative_to(ROOT)} is not there",
        )
        return
    import tools.eval_report as tool

    faults = []
    first = tool.measure_run("once", FROZEN_RUN, FROZEN_SAMPLE)
    second = tool.measure_run("twice", FROZEN_RUN, FROZEN_SAMPLE)
    first["label"] = second["label"] = "run"
    if json.dumps(first, sort_keys=True) != json.dumps(second, sort_keys=True):
        faults.append("two measurements of one directory differ")
    if first["absent"]:
        faults.append(f"the frozen run could not answer: {first['absent']}")
    breaks = first["mid_break_rate"]
    if breaks["pages"] != 8:
        faults.append(f"{breaks['pages']} pages, not 8")
    series = breaks["series"][mid_break_rate.PAGE_SERIES]
    if series["boundaries_total"] != 7:
        faults.append(f"{series['boundaries_total']} page boundaries, not 7")
    # Ledger row A-04 adjudicates two of Courier-en's seven boundaries as links,
    # and the metric carries that adjudication through onto the boundaries.
    adjudicated = sum(1 for item in series["boundaries"] if item["truth_link"])
    if adjudicated != 2:
        faults.append(f"{adjudicated} adjudicated links carried through, not 2")
    if first["conservation"]["holds"] is not True:
        faults.append(f"the frozen run did not conserve: {first['conservation']}")
    terms = first["ltcr"]["summary"]
    if terms["ltcr"] is None:
        faults.append("the frozen run produced no LTCR")
    elif terms["legacy_mean_share"] is not None and terms["ltcr"] > terms[
        "legacy_mean_share"
    ] + 1e-9:
        faults.append(
            f"LTCR {terms['ltcr']} above the legacy share {terms['legacy_mean_share']}"
        )
    geometry = first["layout_geometry"]["summary"]
    if geometry["overlap_source"] is None or geometry["alignment_source"] is None:
        faults.append("the frozen run produced no layout geometry")
    record("check_06_the_entry_point_over_a_frozen_run", not faults, "; ".join(faults))


# --- 10 the stratification of the mid-unit rate --------------------------------


def _stratified_document():
    """Six pages whose five boundaries cover every stratum, verdicts by hand.

    Read with the ruling below: an open linked tail, a closed trap, an open
    trap, a closed clean tail, and an open tail the ruling says nothing about.
    """
    return _document(
        [
            _page([_paragraph("and it runs on", 40.0, 700.0, 500.0)], 0),
            _page([_paragraph("A closed one.", 40.0, 700.0, 500.0)], 1),
            _page([_paragraph("dangling here", 40.0, 700.0, 500.0)], 2),
            _page([_paragraph("Ends properly.", 40.0, 700.0, 500.0)], 3),
            _page([_paragraph("cut mid sentence", 40.0, 700.0, 500.0)], 4),
            _page([_paragraph("The last page.", 40.0, 700.0, 500.0)], 5),
        ]
    )


_RULING = {
    "1->2": {"link": True, "note": "a unit is cut here"},
    "2->3": {"link": False, "note": "TRAP: the continuation is outside the excerpt"},
    "3->4": {"link": False, "note": "TRAP: the same, and this one dangles"},
    "4->5": {"link": False, "note": "a clean boundary, nothing crosses"},
}


def check_10a_the_strata_are_read_from_the_ruling_and_the_note() -> None:
    """Positive 10a: each boundary lands in the stratum the adjudication put it in.

    The ruling gives the linked boundaries and the declared marker gives the
    traps, so the three strata are a reading of the ground truth file and not a
    second opinion about it. A boundary the ruling is silent about is
    ``unlabelled`` -- not clean, which would be a claim nobody made.
    """
    config = load_metrics_config()
    chain_config = load_chain_config()
    truth = mid_break_rate.adjudications_of(_RULING, config.truth_trap_markers)
    result = mid_break_rate.measure(
        _stratified_document(), chain_config, truth, config
    )
    series = result["series"][mid_break_rate.PAGE_SERIES]
    faults = []
    expected = [
        (mid_break_rate.LINKED, mid_break_rate.OPEN),
        (mid_break_rate.TRAP, mid_break_rate.CLOSED),
        (mid_break_rate.TRAP, mid_break_rate.OPEN),
        (mid_break_rate.CLEAN, mid_break_rate.CLOSED),
        (mid_break_rate.UNLABELLED, mid_break_rate.OPEN),
    ]
    actual = [
        (item["truth_category"], item["verdict"]) for item in series["boundaries"]
    ]
    if actual != expected:
        faults.append(f"{actual} against {expected}")

    stratified = result["stratified"]
    # One open of the two answerable linkable boundaries; three opens of the
    # five boundaries there are; one of the two traps open.
    for key, value in (
        ("mbr_linkable", 0.5),
        ("mbr_linkable_open", 1),
        ("mbr_linkable_denominator", 2),
        ("mbr_all", 0.6),
        ("mbr_all_denominator", 5),
        ("source_inherited_open", 1),
        ("trap_boundaries", 2),
        ("unlabelled_boundaries", 1),
    ):
        if stratified[key] != value:
            faults.append(f"{key}={stratified[key]} against {value}")
    if stratified["strata"][mid_break_rate.TRAP]["boundaries_total"] != 2:
        faults.append("the trap stratum lost a boundary")
    record(
        "check_10a_the_strata_are_read_from_the_ruling_and_the_note",
        not faults,
        "; ".join(faults),
    )


def check_10b_a_trap_cannot_move_the_headline() -> None:
    """Negative 10b: openness the excerpt caused never enters the headline rate.

    The whole reason for the stratification. Two documents differing only in
    whether a trap tail dangles have to report the same linkable rate, because
    no producer could have closed that boundary either way; the difference has
    to show in the all-boundaries rate and in the inherited count, where it is
    attributed to the excerpt.
    """
    config = load_metrics_config()
    chain_config = load_chain_config()
    truth = mid_break_rate.adjudications_of(_RULING, config.truth_trap_markers)
    dangling = mid_break_rate.measure(
        _stratified_document(), chain_config, truth, config
    )["stratified"]

    closed_trap = _stratified_document()
    closed_trap.page[2].pdf_paragraph[0] = _paragraph(
        "no longer dangling.", 40.0, 700.0, 500.0
    )
    repaired = mid_break_rate.measure(closed_trap, chain_config, truth, config)[
        "stratified"
    ]

    faults = []
    if dangling["mbr_linkable"] != repaired["mbr_linkable"]:
        faults.append(
            f"the headline moved from {dangling['mbr_linkable']} to "
            f"{repaired['mbr_linkable']} on a trap"
        )
    if dangling["mbr_all"] == repaired["mbr_all"]:
        faults.append("the all-boundaries rate did not notice the trap at all")
    if (dangling["source_inherited_open"], repaired["source_inherited_open"]) != (1, 0):
        faults.append(
            f"inherited open {dangling['source_inherited_open']} then "
            f"{repaired['source_inherited_open']}"
        )
    # And with no ruling at all there is no stratification, rather than one
    # where every boundary silently counts as clean.
    unruled = mid_break_rate.measure(_stratified_document(), chain_config)
    if unruled["stratified"] is not None:
        faults.append("a sample with no adjudication was stratified anyway")
    record("check_10b_a_trap_cannot_move_the_headline", not faults, "; ".join(faults))


# --- 11 the leave-one-publication-out matrix -----------------------------------


def check_11a_the_fold_matrix_is_on_disk_and_adds_up() -> None:
    """Positive 11a: the matrix is a tracked file whose folds are consistent.

    B-02's lesson is that a number whose matrix was never written down cannot be
    checked, restored or defended, so the assertion is on the file. Each fold's
    held out and in-fold halves must partition the corpus exactly -- the pages
    add up, the hits add up, and no sample appears in both halves -- and the
    protocol must state that no fold refits anything, since the whole reading of
    the matrix depends on that.
    """
    if not LOPO_RESULT.is_file():
        record(
            "check_11a_the_fold_matrix_is_on_disk_and_adds_up",
            False,
            f"{LOPO_RESULT.relative_to(ROOT)} is not there",
        )
        return
    with LOPO_RESULT.open(encoding="utf-8") as f:
        report = json.load(f)
    faults = []
    protocol = report["protocol"]
    if protocol["refit_per_fold"] is not False:
        faults.append("the protocol claims a per fold refit this repository cannot do")
    for field in ("refit_note", "tuning_contact"):
        if not protocol.get(field):
            faults.append(f"the protocol states no {field}")
    if report["missing"]:
        faults.append(f"samples the matrix could not classify: {report['missing']}")

    everything = report["corpus"]["all"]
    if not report["folds"]:
        faults.append("no folds")
    for fold in report["folds"]:
        held = fold["held_out"]
        rest = fold["in_fold"]
        if held["labelled_pages"] + rest["labelled_pages"] != everything[
            "labelled_pages"
        ]:
            faults.append(f"{fold['held_out_publication']}: pages do not partition")
        for key in ("kind_hits", "policy_hits"):
            if held[key] + rest[key] != everything[key]:
                faults.append(f"{fold['held_out_publication']}: {key} do not partition")
        if set(held["samples"]) & set(rest["samples"]):
            faults.append(f"{fold['held_out_publication']}: a sample is in both halves")
        if not held["samples"]:
            faults.append(f"{fold['held_out_publication']}: nothing held out")
    # The policy column can never be below the kind column: a kind hit is a
    # policy hit by construction.
    for row in report["samples"]:
        if row["policy_hits"] < row["kind_hits"]:
            faults.append(f"{row['file']}: policy below kind")
    record(
        "check_11a_the_fold_matrix_is_on_disk_and_adds_up", not faults, "; ".join(faults)
    )


def check_11b_the_fold_matrix_recomputes_bit_for_bit() -> None:
    """Positive 11b: running the tool again reproduces the tracked file exactly.

    Determinism is the property that makes a frozen number checkable, and the
    only way to assert it is to run the thing twice. The tool writes where the
    tracked copy is, so this also catches a matrix that was hand edited after
    the tool produced it.
    """
    if not LOPO_RESULT.is_file():
        record(
            "check_11b_the_fold_matrix_recomputes_bit_for_bit",
            False,
            f"{LOPO_RESULT.relative_to(ROOT)} is not there",
        )
        return
    before = LOPO_RESULT.read_bytes()
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(LOPO_TOOL), "--out", str(RESULTS), "--name", LOPO_RESULT.stem],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    after = LOPO_RESULT.read_bytes()
    faults = []
    if proc.returncode != 0:
        faults.append(f"the tool exited {proc.returncode}: {proc.stdout[-400:]}")
    if before != after:
        faults.append("the recomputed matrix differs from the tracked one")
    record(
        "check_11b_the_fold_matrix_recomputes_bit_for_bit", not faults, "; ".join(faults)
    )


# --- 12 the two geometry paths --------------------------------------------------


def check_12a_the_paths_are_compared_where_both_can_read() -> None:
    """Positive 12a: the fork product is measured down both paths, and differenced.

    An upstream column exists only because a PDF can be measured without a
    checkpoint. Whether it may be read beside a fork column is a question about
    the two methods, and it is answered on the one artefact both can read: the
    fork's own product, measured through the intermediate language and through
    extraction, with the deviation reported per metric.
    """
    if not CORPUS_RESULT.is_file():
        record(
            "check_12a_the_paths_are_compared_where_both_can_read",
            False,
            f"{CORPUS_RESULT.relative_to(ROOT)} is not there",
        )
        return
    with CORPUS_RESULT.open(encoding="utf-8") as f:
        report = json.load(f)
    faults = []
    for sample in report["samples"]:
        comparison = sample["method_comparison"]
        if comparison is None:
            faults.append(f"{sample['sample']}: no method comparison")
            continue
        if not comparison["metrics"]:
            faults.append(f"{sample['sample']}: the comparison names no metric")
        for name, row in comparison["metrics"].items():
            if row["relative_delta"] is not None and row["comparable"] is None:
                faults.append(f"{sample['sample']} {name}: a delta with no verdict")
        counts = comparison["elements"]
        if counts["pdf_extraction_produced"] <= 0:
            faults.append(f"{sample['sample']}: the extraction path found no element")
        verdicts = comparison["boundary_verdicts"]
        if verdicts["shared"] <= 0 and sample["pages"] and sample["pages"] > 1:
            faults.append(f"{sample['sample']}: no boundary shared by the two paths")
    record(
        "check_12a_the_paths_are_compared_where_both_can_read",
        not faults,
        "; ".join(faults[:5]),
    )


def check_12b_the_deviation_is_in_the_contract() -> None:
    """Negative 12b: no metric is declared comparable anywhere but the contract.

    A deviation measured and left in a JSON file is a deviation nobody will read
    before quoting a number across the two columns. Every metric the sweep found
    incomparable has to be named in the metric contract, and the contract has to
    state the bound it was judged against.
    """
    if not CORPUS_RESULT.is_file():
        record(
            "check_12b_the_deviation_is_in_the_contract",
            False,
            f"{CORPUS_RESULT.relative_to(ROOT)} is not there",
        )
        return
    with CORPUS_RESULT.open(encoding="utf-8") as f:
        report = json.load(f)
    contract = CONTRACT.read_text(encoding="utf-8")
    incomparable = sorted(
        {
            name
            for sample in report["samples"]
            for name, row in (sample["method_comparison"] or {}).get(
                "metrics", {}
            ).items()
            if row["comparable"] is False
        }
    )
    faults = [name for name in incomparable if name not in contract]
    bound = next(
        (
            sample["method_comparison"]["bound"]
            for sample in report["samples"]
            if sample["method_comparison"]
        ),
        None,
    )
    if bound is None:
        faults.append("no bound was recorded")
    elif str(bound) not in contract:
        faults.append(f"the contract does not state the bound {bound}")
    if not incomparable:
        faults.append("no metric was judged: the comparison found nothing to say")
    record(
        "check_12b_the_deviation_is_in_the_contract",
        not faults,
        f"unnamed in the contract: {faults[:5]}",
    )


# --- 13 the corpus sweep --------------------------------------------------------


def check_13a_every_sample_in_every_configuration() -> None:
    """Positive 13a: the sweep covers the registered corpus, or says why it does not.

    One file per registered sample, each carrying the configurations this
    repository holds artefacts for. A configuration that is absent is named
    under ``missing`` with the path that was looked for, because a run silently
    dropped from a table is a run whose absence gets read as a result.
    """
    if not CORPUS_RESULT.is_file():
        record(
            "check_13a_every_sample_in_every_configuration",
            False,
            f"{CORPUS_RESULT.relative_to(ROOT)} is not there",
        )
        return
    with CORPUS_RESULT.open(encoding="utf-8") as f:
        report = json.load(f)
    manifest = corpus_module.load_manifest()
    registered = {entry["file"] for entry in manifest["samples"]}
    measured = {sample["sample"] for sample in report["samples"]}
    faults = []
    if measured != registered:
        faults.append(f"measured {sorted(measured)} against {sorted(registered)}")
    for sample in report["samples"]:
        stem = Path(sample["sample"]).stem
        if not (RESULTS / f"eval_report.{stem}.json").is_file():
            faults.append(f"{sample['sample']}: no per sample file")
        labels = {run["label"] for run in sample["runs"]}
        for label in report["labels"]:
            if label not in labels and not any(
                line.startswith(f"{label}:") for line in sample["missing"]
            ):
                faults.append(f"{sample['sample']}: {label} neither run nor explained")
        for run in sample["runs"]:
            if run["conservation"]["holds"] is False:
                faults.append(f"{sample['sample']} {run['label']}: did not conserve")
    record(
        "check_13a_every_sample_in_every_configuration", not faults, "; ".join(faults[:5])
    )


def check_13b_the_unmeasurable_boundaries_are_counted() -> None:
    """Negative 13b: no run hides a boundary behind the axis it cannot measure.

    ``axis_unsupported`` is the verdict for a tail the method has no reading end
    for, and it enters no rate. That is only honest if the count is reported, so
    every run states it, and every run also states how many paragraphs of the
    document were set on that axis at all -- a zero of the first with a zero of
    the second is a document with nothing to miss, and a zero of the first with
    a positive second is the check having been made.
    """
    if not CORPUS_RESULT.is_file():
        record(
            "check_13b_the_unmeasurable_boundaries_are_counted",
            False,
            f"{CORPUS_RESULT.relative_to(ROOT)} is not there",
        )
        return
    with CORPUS_RESULT.open(encoding="utf-8") as f:
        report = json.load(f)
    faults = []
    for sample in report["samples"]:
        for run in sample["runs"]:
            series = run["page_series"]
            if "axis_unsupported_count" not in series:
                faults.append(f"{sample['sample']} {run['label']}: no count")
                continue
            if "vertical_paragraphs" not in run["mid_break_rate"]:
                faults.append(f"{sample['sample']} {run['label']}: no vertical tally")
                continue
            swallowed = series["axis_unsupported_count"]
            answerable = series["answerable"]
            if swallowed + answerable + series["no_tail_count"] != series[
                "boundaries_total"
            ]:
                faults.append(f"{sample['sample']} {run['label']}: verdicts do not sum")
    record(
        "check_13b_the_unmeasurable_boundaries_are_counted",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 14 the policy column -------------------------------------------------------


def check_14_the_policy_column_exists_for_every_tier() -> None:
    """Positive 14: ledger row C-04's missing column, computed for all four tiers.

    The conclusion the ledger carries is about the policy level and the produced
    reports only ever carried the kind level. The column is recomputed from the
    frozen reports, which costs nothing and reaches no model, and it has to obey
    the one property it cannot violate: a kind hit is a policy hit, so the policy
    column is never below the kind column.
    """
    if not POLICY_RESULT.is_file():
        record(
            "check_14_the_policy_column_exists_for_every_tier",
            False,
            f"{POLICY_RESULT.relative_to(ROOT)} is not there",
        )
        return
    with POLICY_RESULT.open(encoding="utf-8") as f:
        report = json.load(f)
    faults = []
    if len(report["tiers"]) < 4:
        faults.append(f"{len(report['tiers'])} tiers, not the four the ledger names")
    for tier in report["tiers"]:
        for column in ("deterministic", "combined"):
            kind = tier["kind_agreement"][column]
            policy = tier["policy_agreement"][column]
            if policy["total"] != kind["total"]:
                faults.append(f"{tier['model']} {column}: denominators differ")
            if policy["hits"] < kind["hits"]:
                faults.append(f"{tier['model']} {column}: policy below kind")
        if tier["policy_gain"][""] > 0:
            faults.append(
                f"{tier['model']}: gains {tier['policy_gain']['']} at the policy "
                "level, which the ledger says no tier does"
            )
        if not Path(ROOT / tier["report"]).is_file():
            faults.append(f"{tier['model']}: {tier['report']} is not there")
    record(
        "check_14_the_policy_column_exists_for_every_tier", not faults, "; ".join(faults)
    )


# --- 07 the scope --------------------------------------------------------------


def check_07a_no_upstream_and_no_ground_truth_change() -> None:
    """Negative 7a: the batch stays inside its whitelist.

    Nothing under prompts/, corpus/ or reviews/: the rulings and the ground
    truth are what the metrics are measured against, and a batch that edited one
    while implementing the other would have measured its own homework.
    """
    changed = changed_paths()
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    faults = []
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    for prefix in ("prompts/", "corpus/", "reviews/"):
        touched = sorted(path for path in changed if path.startswith(prefix))
        if touched:
            faults.append(f"{prefix} changed: {touched}")
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith(EXTENSION_PREFIX)
    )
    if upstream:
        faults.append(f"upstream files changed: {upstream}")
    outside_metrics = sorted(
        path
        for path in changed
        if path.startswith(EXTENSION_PREFIX)
        and not path.startswith("babeldoc/magazine/metrics/")
    )
    if outside_metrics:
        faults.append(f"the extension package changed outside metrics/: {outside_metrics}")
    record("check_07a_no_upstream_and_no_ground_truth_change", not faults, "; ".join(faults))


def check_07b_the_runner_registers_this_gate() -> None:
    """Positive 7b: the sweep runs this gate, after the inventory it cites."""
    source = (ROOT / "spec_checks" / "run_all.py").read_text(encoding="utf-8")
    listed = re.findall(r'"(spec_check_[a-z0-9_]+\.py)"', source)
    name = Path(__file__).name
    faults = []
    if name not in listed:
        faults.append("run_all.py does not list this gate")
    elif "spec_check_e0.py" in listed and listed.index(name) < listed.index(
        "spec_check_e0.py"
    ):
        faults.append("this gate runs before the inventory it cites")
    record("check_07b_the_runner_registers_this_gate", not faults, "; ".join(faults))


def check_07c_ascii_prose() -> None:
    """Negative 7c: every file this batch adds is ASCII, as the code always is."""
    faults = []
    files = sorted(PACKAGE.glob("*.py")) + [TOOL, LOPO_TOOL, CONFIG, Path(__file__)]
    for path in files:
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
    record("check_07c_ascii_prose", not faults, "; ".join(faults[:5]))


def check_07d_every_metric_carries_its_definition() -> None:
    """Positive 7d: each metric module states its own definition, and the contract agrees.

    A metric whose definition lives only in somebody's memory of a meeting is
    the failure mode the contract exists to prevent. Each module's docstring has
    to carry either a maths block of its own or the equation label it defers to,
    and every label a module cites has to resolve in the background chapter.
    """
    chapter = (ROOT / "docs" / "dissertation" / "background_chapter.tex").read_text(
        encoding="utf-8"
    )
    labels = set(re.findall(r"\\label\{(eq:[^}]+)\}", chapter))
    faults = []
    for name in ("mid_break_rate", "conservation", "ltcr", "layout_geometry"):
        source = (PACKAGE / f"{name}.py").read_text(encoding="utf-8")
        docstring = source.split('"""')[1] if '"""' in source else ""
        cited = set(re.findall(r"eq:[a-z_]+", docstring))
        if ".. math::" not in docstring and not cited:
            faults.append(f"{name} states neither a formula nor an equation label")
        for label in sorted(cited - labels):
            faults.append(f"{name} cites {label}, which the chapter does not define")
    contract = CONTRACT.read_text(encoding="utf-8")
    for name in ("mid_break_rate", "conservation", "ltcr", "layout_geometry"):
        if name not in contract and name.replace("_", " ") not in contract:
            faults.append(f"the contract does not mention {name}")
    record("check_07d_every_metric_carries_its_definition", not faults, "; ".join(faults))


# --- 08 what a metric may never do ---------------------------------------------


def check_08a_no_metric_can_spend_anything() -> None:
    """Negative 8a: no metric imports a translator, a model client or a credential.

    A metric that could make a request is a metric whose answer depends on when
    it was run. Every number here has to be recomputable from a frozen artefact
    at no cost, which is the property that makes the whole evaluation replayable.
    """
    faults = []
    for path in sorted(PACKAGE.glob("*.py")) + [TOOL, LOPO_TOOL]:
        source = path.read_text(encoding="utf-8")
        for forbidden in ("translator", "openai", "vlm_client", "gate_cache", "httpx"):
            if re.search(rf"^\s*(import|from)\s+.*{forbidden}", source, re.MULTILINE):
                faults.append(f"{path.name} imports {forbidden}")
        suffix = "_API" + "_KEY"
        if suffix in source:
            faults.append(f"{path.name} names a credential")
    record("check_08a_no_metric_can_spend_anything", not faults, "; ".join(faults))


def check_08b_no_metric_names_a_publication() -> None:
    """Negative 8b: nothing in the package or the configuration names a magazine.

    The general signal rule. A metric that recognised a publication would be
    measuring that publication rather than the property it claims to measure,
    and the corpus is small enough that one such special case would carry a
    whole result.
    """
    names = ("courier", "unesco", "aramco", "vogue", "cern")
    faults = []
    for path in sorted(PACKAGE.glob("*.py")) + [CONFIG]:
        body = path.read_text(encoding="utf-8").casefold()
        for name in names:
            if name in body:
                faults.append(f"{path.name} names {name}")
    record("check_08b_no_metric_names_a_publication", not faults, "; ".join(faults))


def check_08c_the_metrics_are_not_on_the_translation_path() -> None:
    """Negative 8c: nothing on the pipeline imports the metrics package.

    A measurement that ran during a translation could change what it measures.
    The package is for tools and gates, and the pipeline has to stay ignorant of
    it; the only importer outside the evaluation is the term consistency tool,
    which is a tool.
    """
    faults = []
    for path in sorted((ROOT / "babeldoc").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("babeldoc/magazine/metrics/"):
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*(import|from)\s+.*magazine\.metrics", source, re.MULTILINE):
            faults.append(relative)
    record("check_08c_the_metrics_are_not_on_the_translation_path", not faults, "; ".join(faults))


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
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="spec_e1_"))
    checks = [
        check_01a_every_parameter_is_bounded,
        lambda: check_01b_an_unbounded_parameter_is_refused(tmp),
        check_02a_verdicts_over_synthetic_pages,
        check_02b_the_last_line_is_read_not_the_string,
        check_02c_boundary_shapes,
        check_02d_the_column_series_is_separate,
        check_02e_the_ender_set_comes_from_the_detector,
        check_03a_the_three_levels_hold_and_fail,
        check_03b_absent_evidence_is_not_a_pass,
        check_04a_the_pairwise_count_is_the_definition,
        check_04b_the_relation_to_the_legacy_share,
        check_04c_the_unmeasurable_is_not_measured,
        check_04d_the_corpus_rule_sums_rather_than_averages,
        check_05a_overlap_against_hand_computed_values,
        check_05b_alignment_and_the_domain_of_g,
        check_05c_degenerate_elements_are_dropped,
        check_05d_image_pairing_and_the_unpaired_case,
        check_05e_the_deltas_over_a_whole_document,
        check_06_the_entry_point_over_a_frozen_run,
        check_10a_the_strata_are_read_from_the_ruling_and_the_note,
        check_10b_a_trap_cannot_move_the_headline,
        check_11a_the_fold_matrix_is_on_disk_and_adds_up,
        check_11b_the_fold_matrix_recomputes_bit_for_bit,
        check_12a_the_paths_are_compared_where_both_can_read,
        check_12b_the_deviation_is_in_the_contract,
        check_13a_every_sample_in_every_configuration,
        check_13b_the_unmeasurable_boundaries_are_counted,
        check_14_the_policy_column_exists_for_every_tier,
        check_07a_no_upstream_and_no_ground_truth_change,
        check_07b_the_runner_registers_this_gate,
        check_07c_ascii_prose,
        check_07d_every_metric_carries_its_definition,
        check_08a_no_metric_can_spend_anything,
        check_08b_no_metric_names_a_publication,
        check_08c_the_metrics_are_not_on_the_translation_path,
        check_09_sweep,
    ]
    for check in checks:
        name = getattr(check, "__name__", "check_01b_an_unbounded_parameter_is_refused")
        if harness.FAST_TIER and name in PIPELINE_TIER:
            print(f"SKIPPED: {name} (fast tier)")
            continue
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(name, False, f"raised {exc!r}")
    print(f"\nspec_check_e1: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_e1")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
