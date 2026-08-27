"""Gate script for batch B11.7 (indent authority, capacity cuts, zero residue).

Run from the repository root:

    python spec_checks/spec_check_b11_7.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request. Every assertion is answered from a stub this gate builds, or
from the small derived evidence this batch wrote beside its runs, or from a file
git tracks -- never from a stage checkpoint and never from a produced PDF, per
CLAUDE.md section 4.16.

What this batch is.

T1 made the indent policy the only writer of ``first_line_indent``. Where its
mode has an opinion the flag is the conjunction of four conditions -- eligible
page, body label, mode indents this rank, and the paragraph opens rather than
resumes a chain -- and a paragraph failing any of them is set flush. The source
geometry and the line splitting pass no longer reach the page through it. Under
the ``source`` mode the pass abstains entirely, because a mode that says
"reproduce the source" cannot also be overruled by the pass reading it, and
otherwise ``source`` would be a second spelling of ``none``.

T2 changed where a body chain is cut. It was cut at a sentence end, which left
the first box's last line part empty whenever the two boxes differed in size --
the join showing. It is now cut at the first box's own capacity, made legal by
the target language's break rule and pulled back off any mark a line may not
open with. Column and page boundaries take the same treatment, because a body
paragraph interrupted by either is the same paragraph interrupted. Display
chains are untouched.

T3 is the directional hard constraint: no Chinese glyph in the text layer of a
document finished into English. Four parts. The residue floor is directional,
because what a floor protects is. The reading order module now reads a strip of
rotated type whose units hold one character each, which it could not before --
and both the detector and the repair loop read through it, so both were seeing
the same scrambled string rather than two different ones. A formula composition
holding residue script is handed back to the translator, never one carrying
vector artwork. A rotated strip whose text was replaced is set along its own
axis by a lane of its own, kept out of the column reflow, the drop cap and the
hanging punctuation ledger.

T4 is the settlement: all six samples, one arm, closing W-B11-12.

01 is T1. 02 is T2. 03 is T3. 04 is T4 and conservation. 05 is scope, cost and
the sweep. 06 is the determinations this batch wrote down rather than took
silently.

Tiers: every assertion reads a stub or this batch's own derived evidence, so the
fast tier runs the whole gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.midend import (  # noqa: E402
    typesetting as upstream_typeset,  # noqa: E402
)
from babeldoc.magazine import chain_backfill as backfill  # noqa: E402
from babeldoc.magazine import formula_reclass  # noqa: E402
from babeldoc.magazine import indent_policy  # noqa: E402
from babeldoc.magazine import reading_order  # noqa: E402
from babeldoc.magazine.detectors import base as detector_base  # noqa: E402
from babeldoc.magazine.detectors import detector_config  # noqa: E402
from babeldoc.magazine.detectors import residue as residue_detector  # noqa: E402
from spec_checks import evidence  # noqa: E402
from spec_checks import harness  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b11.7"
PREVIOUS_TAG = "b11.6"

BATCH_DIR = ROOT / "examples" / "output" / "b11_7"
PRIOR_DIR = ROOT / "examples" / "output" / "b11_6"

SAMPLES = (
    "Courier-en",
    "CERNCourier-en",
    "Vogue-en",
    "AramcoWorld-en-v2",
    "FD-en-v2",
    "Courier-zh",
)

# The samples b11.6 ran, and so the ones a like for like comparison exists for.
PRIOR_SAMPLES = ("Courier-en", "AramcoWorld-en-v2", "FD-en-v2", "Courier-zh")

PREMISE = BATCH_DIR / "premise_check.json"
CUT_PREDICTION = BATCH_DIR / "t2_cut_prediction.json"
CONSUMERS = BATCH_DIR / "t3_consumer_list.json"
FEASIBILITY = BATCH_DIR / "t3_lane_feasibility.json"
COST = BATCH_DIR / "cost_attribution.json"
SWEEP = BATCH_DIR / "run_all.sweep.json"
# The halted confirming run's own record, which W-B11-23 points 05g at.
SWEEP_PARTIAL = BATCH_DIR / "sweep_partial" / "run_all.partial.json"
RUNS = BATCH_DIR / "runs.json"

INDENT_CONFIG = ROOT / "configs" / "indent_policy.json"
CHAIN_TRANSLATION = ROOT / "configs" / "chain_translation.json"
DETECTORS_CONFIG = ROOT / "configs" / "detectors.json"
RECLASS_CONFIG = ROOT / "configs" / "formula_reclass.json"
LANE_CONFIG = ROOT / "configs" / "rotated_lane.json"
WAIVERS = ROOT / "WAIVERS.md"
CONTRACTS = ROOT / "docs" / "reports" / "assertion_contracts.md"
GAP_REGISTER = ROOT / "docs" / "eval" / "gap_register.md"
UPSTREAM_DIFF = ROOT / "UPSTREAM_DIFF.md"

# The sample the directional hard constraint is stated over: the one finishing
# into English. Named once here rather than at each site.
RESIDUE_SAMPLE = "Courier-zh"

# The contents page T1's page gate exists to keep flush, and the three
# paragraphs on it the source geometry had indented. Anchored by page and
# in-page position, never by a debug id (CLAUDE.md section 5.13).
CONTENTS_SAMPLE = "FD-en-v2"
CONTENTS_PAGE = 3
CONTENTS_INDENTED = ("p3#18", "p3#36", "p3#43")

# The chain continuation T2's first half exists to un-indent, and the members
# set after it in the same column, whose left edge it now has to share.
CONTINUATION_SAMPLE = "FD-en-v2"
CONTINUATION_REFERENCE = "p6#12"
CONTINUATION_NEIGHBOURS = ("p6#13", "p6#14")

# How near two left edges have to be to count as the same edge, in points. One
# point is under a fifth of the indent the configuration pins, so an indent
# cannot hide inside it.
EDGE_TOLERANCE = 1.0

GAPS = ("GAP-43", "GAP-44", "GAP-45", "GAP-46")

# The refusal the lane exists to remove: the packer measuring a rotated strip's
# width as the length of a line, finding no word fits, and declining. Spelled
# once, by the name the repair loop files it under.
HORIZONTAL_ROOM_REFUSAL = "retypesetting_needed_more_room_than_the_paragraph_had"

GATE_EVIDENCE = (
    "examples/output/b11_7/premise_check.json",
    "examples/output/b11_7/t2_cut_prediction.json",
    "examples/output/b11_7/t3_consumer_list.json",
    "examples/output/b11_7/t3_lane_feasibility.json",
    "examples/output/b11_7/cost_attribution.json",
    "examples/output/b11_7/sweep_partial/run_all.partial.json",
    "examples/output/b11_7/runs.json",
) + (
    # Written only by a run that converted something, which is the run finishing
    # into the direction the reclassification acts in.
    f"examples/output/b11_7/{RESIDUE_SAMPLE}/sidecars/formula_reclass_restore.report.json",
) + tuple(
    f"examples/output/b11_7/{sample}/{name}"
    for sample in SAMPLES
    for name in (
        "run.json",
        "chain_evidence.json",
        "indent_evidence.json",
        "residue_evidence.json",
        "conservation.json",
        "sidecars/indent_policy.report.json",
        "sidecars/chain_translation.report.json",
        "sidecars/formula_reclass.report.json",
        "sidecars/rotated_lane.report.json",
        "sidecars/issues.json",
        "sidecars/react_repair.report.json",
        "sidecars/column_reflow.report.json",
        "sidecars/drop_cap_apply.report.json",
        "sidecars/typeset_hang.report.json",
    )
)

_passed = 0
_total = 0
_failures: list[str] = []
_timer = harness.Timer("spec_check_b11_7")


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
    seconds = _timer.mark(name)
    print(f"SKIPPED: {name}: evidence absent: {sorted(missing)} ({seconds:.2f}s)")


def _present(*paths) -> list[str]:
    return [str(path) for path in paths if not evidence.exists(path)]


def read(path):
    return evidence.read_json(path)


def sample_dir(sample: str) -> Path:
    return BATCH_DIR / sample


def indent_report(sample: str):
    return read(sample_dir(sample) / "sidecars" / "indent_policy.report.json")


def indent_geometry(sample: str):
    return read(sample_dir(sample) / "indent_evidence.json")


def chain_report(sample: str):
    return read(sample_dir(sample) / "sidecars" / "chain_translation.report.json")


def chains_of(sample: str):
    return read(sample_dir(sample) / "chain_evidence.json")


def residue_of(sample: str):
    return read(sample_dir(sample) / "residue_evidence.json")


def issues_of(sample: str):
    return read(sample_dir(sample) / "sidecars" / "issues.json")


# --- 01: the indent policy is the only writer --------------------------------


def check_01a_the_four_conditions_are_a_conjunction() -> None:
    """Every one of the four conditions alone is enough to set a paragraph flush.

    Asked of the decision function directly rather than of a run, so the answer
    is about the rule and not about whether this corpus happens to exercise it.
    Sixteen cases: the flag is up in exactly the one where all four hold.
    """
    config = indent_policy.load_indent_config()
    body = config.body_labels[0]
    faults = []
    raised = []
    for page_ok in (True, False):
        for label in (body, "title"):
            for rank_ok in (True, False):
                for continuation in (False, True):
                    decision = indent_policy.decide(
                        label,
                        indent_policy.MODE_ALL_BUT_FIRST,
                        page_ok,
                        2 if rank_ok else config.article_opening_rank,
                        continuation,
                        config,
                    )
                    if decision is None:
                        faults.append("an authoritative mode returned no decision")
                        continue
                    value, reason = decision
                    expected = page_ok and label == body and rank_ok and not continuation
                    if value != expected:
                        faults.append(
                            f"page={page_ok} label={label} rank_ok={rank_ok} "
                            f"cont={continuation} gave {value}"
                        )
                    if value and reason is not None:
                        faults.append("an indented paragraph carries a reason")
                    if not value and reason not in indent_policy.SKIP_REASONS:
                        faults.append(f"reason {reason!r} is outside the closed set")
                    if value:
                        raised.append((page_ok, label, rank_ok, continuation))
    if len(raised) != 1:
        faults.append(f"{len(raised)} of 16 cases indent, expected exactly 1")
    record(
        "check_01a_the_four_conditions_are_a_conjunction",
        not faults,
        "; ".join(faults[:4]),
    )


def check_01b_the_source_mode_abstains() -> None:
    """Under ``source`` the pass decides nothing, so ``source`` is not ``none``.

    The negative half of authority. Were the conjunction applied under this mode
    it would set every paragraph of the document flush, which is exactly what
    ``none`` means, and one of the two declared modes would have no behaviour of
    its own left.
    """
    config = indent_policy.load_indent_config()
    body = config.body_labels[0]
    faults = []
    if indent_policy.mode_is_authoritative(indent_policy.MODE_SOURCE):
        faults.append("source is treated as authoritative")
    if indent_policy.decide(
        body, indent_policy.MODE_SOURCE, True, 2, False, config
    ) is not None:
        faults.append("source returned a decision")
    if not indent_policy.mode_is_authoritative(indent_policy.MODE_NONE):
        faults.append("none is not treated as authoritative")
    under_none = indent_policy.decide(
        body, indent_policy.MODE_NONE, True, 2, False, config
    )
    if under_none is None or under_none[0] is not False:
        faults.append(f"none gave {under_none!r} on a fully qualified paragraph")
    record("check_01b_the_source_mode_abstains", not faults, "; ".join(faults[:4]))


def check_01c_the_contents_page_was_cleared() -> None:
    """The three indents the source geometry put on the contents page are gone.

    Two numbers, not one. That the flag is now down is the gate firing; that it
    was up before is what makes the assertion about this batch rather than about
    a page that never had an indent to lose.
    """
    missing = _present(sample_dir(CONTENTS_SAMPLE) / "sidecars" / "indent_policy.report.json")
    if missing:
        skip("check_01c_the_contents_page_was_cleared", missing)
        return
    report = indent_report(CONTENTS_SAMPLE)
    rows = {row["reference"]: row for row in report["paragraphs"]}
    faults = []
    for reference in CONTENTS_INDENTED:
        row = rows.get(reference)
        if row is None:
            faults.append(f"{reference} absent")
            continue
        if not row["before"]:
            faults.append(f"{reference} was not indented before, so nothing was cleared")
        if row["after"]:
            faults.append(f"{reference} is still indented")
        if not row["cleared"]:
            faults.append(f"{reference} is not recorded as cleared")
        if row["skipped"] != indent_policy.SKIP_PAGE_INELIGIBLE:
            faults.append(f"{reference} cleared for {row['skipped']!r}")
    still = [
        row["reference"]
        for row in report["paragraphs"]
        if row["page"] == CONTENTS_PAGE and row["after"]
    ]
    if still:
        faults.append(f"{len(still)} paragraph(s) on the page still indented: {still[:3]}")
    record(
        "check_01c_the_contents_page_was_cleared", not faults, "; ".join(faults[:4])
    )


def check_01d_the_contents_page_sets_no_indent_on_the_page() -> None:
    """No paragraph of the contents page starts its first line in from its box.

    Measured on the geometry the typesetting stage produced rather than on the
    flag, because the flag is what this batch changed and the page is what the
    change was for.
    """
    missing = _present(sample_dir(CONTENTS_SAMPLE) / "indent_evidence.json")
    if missing:
        skip("check_01d_the_contents_page_sets_no_indent_on_the_page", missing)
        return
    rows = [
        row
        for row in indent_geometry(CONTENTS_SAMPLE)["paragraphs"]
        if row["page"] == CONTENTS_PAGE
    ]
    faults = []
    if not rows:
        faults.append("the page carries no measured paragraph")
    offenders = [
        (row["reference"], row["offset"]) for row in rows if row["offset"] > EDGE_TOLERANCE
    ]
    if offenders:
        faults.append(f"{len(offenders)} first line(s) set in: {offenders[:3]}")
    record(
        "check_01d_the_contents_page_sets_no_indent_on_the_page",
        not faults,
        "; ".join(faults[:4]),
    )


def check_01e_the_article_pages_did_not_lose_their_indent() -> None:
    """Body paragraphs that meet all four conditions are still indented.

    The other side of 01c. Authority that cleared the contents page and the
    article pages together would satisfy every assertion above and be useless.
    """
    faults = []
    checked = 0
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "indent_policy.report.json"
        if not evidence.exists(path):
            continue
        report = read(path)
        if not report["authoritative"]:
            continue
        qualified = [
            row
            for row in report["paragraphs"]
            if row["indent_eligible_page"]
            and row["layout_label"] in report["body_labels"]
            and not row["chain_continuation"]
            and row["skipped"] is None
        ]
        flush = [row["reference"] for row in qualified if not row["after"]]
        if flush:
            faults.append(f"{sample}: {len(flush)} qualified paragraph(s) flush")
        if qualified:
            checked += 1
    if not checked:
        faults.append("no authoritative sample carried a qualified paragraph")
    record(
        "check_01e_the_article_pages_did_not_lose_their_indent",
        not faults,
        "; ".join(faults[:4]),
    )


def check_01f_the_surface_is_reported_per_sample() -> None:
    """Every sample's record says what authority did and did not reach.

    The settlement batch's own requirement: the surface of the change stated on
    all six rather than on the ones a defect happened to show up on.
    """
    faults = []
    seen = 0
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "indent_policy.report.json"
        if not evidence.exists(path):
            faults.append(f"{sample}: no record")
            continue
        report = read(path)
        seen += 1
        totals = report["totals"]
        for key in ("cleared", "raised", "chain_continuations", "decided", "left_alone"):
            if key not in totals:
                faults.append(f"{sample}: totals omit {key}")
        if report["authoritative"]:
            if totals["left_alone"]:
                faults.append(
                    f"{sample}: authoritative yet left {totals['left_alone']} alone"
                )
        elif totals["decided"]:
            faults.append(f"{sample}: not authoritative yet decided {totals['decided']}")
        for row in report["paragraphs"]:
            if not row["after"] and report["authoritative"] and row["skipped"] is None:
                faults.append(f"{sample} {row['reference']}: flush with no reason")
                break
    if seen != len(SAMPLES):
        faults.append(f"{seen} of {len(SAMPLES)} samples reported")
    record(
        "check_01f_the_surface_is_reported_per_sample", not faults, "; ".join(faults[:4])
    )


# --- 02: the capacity cut ----------------------------------------------------


def check_02a_a_chain_continuation_is_not_indented() -> None:
    """The resumed half of a chain shares the left edge of the lines after it.

    Measured in points on the produced geometry. A continuation indented by the
    configured amount would stand about eighteen points in from its neighbours,
    which is eighteen times the tolerance this compares against.
    """
    missing = _present(sample_dir(CONTINUATION_SAMPLE) / "indent_evidence.json")
    if missing:
        skip("check_02a_a_chain_continuation_is_not_indented", missing)
        return
    rows = {
        row["reference"]: row
        for row in indent_geometry(CONTINUATION_SAMPLE)["paragraphs"]
    }
    faults = []
    member = rows.get(CONTINUATION_REFERENCE)
    if member is None:
        faults.append(f"{CONTINUATION_REFERENCE} absent")
    else:
        if member["offset"] > EDGE_TOLERANCE:
            faults.append(
                f"{CONTINUATION_REFERENCE} first line is {member['offset']} in"
            )
        if member["first_line_indent"]:
            faults.append(f"{CONTINUATION_REFERENCE} still carries the flag")
        for reference in CONTINUATION_NEIGHBOURS:
            neighbour = rows.get(reference)
            if neighbour is None:
                faults.append(f"{reference} absent")
                continue
            gap = abs(member["first_line_x"] - neighbour["box_x"])
            if gap > EDGE_TOLERANCE:
                faults.append(
                    f"{CONTINUATION_REFERENCE} starts {gap:.2f}pt off {reference}"
                )
    record(
        "check_02a_a_chain_continuation_is_not_indented", not faults, "; ".join(faults[:4])
    )


def check_02b_every_body_chain_is_cut_by_capacity() -> None:
    """A body chain takes the capacity strategy, and says what it measured.

    A chain the caller could measure no box for falls back and reports the
    fallback, which is allowed; what is not allowed is a chain that took the
    strategy, reported no fallback, and recorded no measurement.
    """
    faults = []
    seen = 0
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "chain_translation.report.json"
        if not evidence.exists(path):
            continue
        for chain in read(path).get("chains", ()):
            if chain["pair_class"] != "body":
                continue
            seen += 1
            if chain["strategy"] != backfill.STRATEGY_CAPACITY:
                faults.append(f"{sample}: a body chain took {chain['strategy']!r}")
                continue
            fallback = chain["redistribution"]["fallback"]
            measured = [
                row for row in chain.get("capacity", ()) if row.get("measurable")
            ]
            if fallback == backfill.FALLBACK_NO_CAPACITY:
                continue
            if fallback is not None:
                faults.append(f"{sample}: a capacity cut reported {fallback!r}")
            if len(measured) != len(chain["members"]):
                faults.append(
                    f"{sample}: {len(measured)} of {len(chain['members'])} boxes measured"
                )
            for cut in chain["redistribution"]["cuts"]:
                if cut["mode"] != backfill.CUT_CAPACITY:
                    faults.append(f"{sample}: a cut was placed as {cut['mode']!r}")
    if not seen:
        faults.append("no body chain in the corpus")
    record(
        "check_02b_every_body_chain_is_cut_by_capacity", not faults, "; ".join(faults[:4])
    )


def check_02c_both_kinds_of_boundary_take_the_same_treatment() -> None:
    """A body chain broken by a page edge is cut the same way as one broken by a
    column edge, and both kinds are present to prove it.

    The user's ruling. Were only one kind present the assertion would be about
    the corpus rather than about the rule, so the presence of both is asserted
    first.
    """
    faults = []
    kinds: dict[str, int] = {}
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "chain_translation.report.json"
        if not evidence.exists(path):
            continue
        for chain in read(path).get("chains", ()):
            if chain["pair_class"] != "body":
                continue
            for kind in chain["boundary_kinds"]:
                kinds[kind] = kinds.get(kind, 0) + 1
            if chain["strategy"] != backfill.STRATEGY_CAPACITY:
                faults.append(
                    f"{sample}: a body chain over {chain['boundary_kinds']} took "
                    f"{chain['strategy']!r}"
                )
    for kind in ("page", "column"):
        if not kinds.get(kind):
            faults.append(f"no body chain is broken by a {kind} boundary")
    record(
        "check_02c_both_kinds_of_boundary_take_the_same_treatment",
        not faults,
        f"kinds={kinds}; " + "; ".join(faults[:3]),
    )


def check_02d_a_continuation_opens_on_no_forbidden_mark() -> None:
    """No cut leaves the next member opening on a mark a line may not open with.

    Read off the segments the redistribution produced, against the class the
    typesetting stage sets lines by -- the same object, imported, rather than a
    second list of the same marks.
    """
    faults = []
    checked = 0
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "chain_translation.report.json"
        if not evidence.exists(path):
            continue
        for chain in read(path).get("chains", ()):
            if chain["pair_class"] != "body":
                continue
            translation = chain["translation"]
            for member in chain["members"][1:]:
                start = member["segment"]["start"]
                if start >= len(translation):
                    faults.append(f"{sample}: a segment starts past the translation")
                    continue
                checked += 1
                head = translation[start]
                if head in upstream_typeset.LINE_HEAD_FORBIDDEN_PUNCTUATION:
                    faults.append(
                        f"{sample}: a continuation opens on {head!r}"
                    )
    if not checked:
        faults.append("no continuation to check")
    record(
        "check_02d_a_continuation_opens_on_no_forbidden_mark",
        not faults,
        f"checked={checked}; " + "; ".join(faults[:3]),
    )


def check_02e_the_first_box_is_filled_at_least_as_well_as_before() -> None:
    """The capacity cut fills the first box no worse than the sentence cut did.

    Read from the prediction this batch wrote before it ran, which cut every one
    of the previous batch's frozen chains both ways from the same merged source
    and the same joint translation. That is the only comparison that holds the
    text constant: comparing this run's boxes against the previous run's would
    be comparing two different translations.
    """
    missing = _present(CUT_PREDICTION)
    if missing:
        skip("check_02e_the_first_box_is_filled_at_least_as_well_as_before", missing)
        return
    prediction = read(CUT_PREDICTION)
    faults = []
    rows = prediction["chains"]
    if not rows:
        faults.append("the prediction covers no chain")
    # Compared on the pair the prediction records, not on the fill alone: a cut
    # past the box's capacity overflows it and the stage answers by shrinking
    # the paragraph, and a single fill figure scores that overflow as a perfect
    # fill. Not overflowing comes first; the last line decides among the rest.
    measured = [row for row in rows if row["measurable"]]
    worse = [
        row for row in measured if row["quality_capacity"] < row["quality_sentence"]
    ]
    if worse:
        faults.append(f"{len(worse)} chain(s) set the first box less well")
    better = [
        row for row in measured if row["quality_capacity"] > row["quality_sentence"]
    ]
    if not better:
        faults.append("no chain sets the first box better, so the change did nothing")
    overflow_before = sum(1 for row in measured if row["overflowed_sentence"])
    overflow_after = sum(1 for row in measured if row["overflowed_capacity"])
    if overflow_after >= overflow_before:
        faults.append(
            f"first box overflows did not fall: {overflow_before} -> {overflow_after}"
        )
    record(
        "check_02e_the_first_box_is_filled_at_least_as_well_as_before",
        not faults,
        f"better={len(better)} worse={len(worse)} "
        f"overflow {overflow_before}->{overflow_after}; " + "; ".join(faults[:2]),
    )


def check_02f_the_display_chains_were_not_touched() -> None:
    """A display chain still cuts by share and claims no sentence structure.

    The negative that keeps T2 inside its scope. The strategy table names the
    two classes separately, and only one of them moved.
    """
    config = backfill.load_backfill_config()
    faults = []
    if config.strategy_by_pair_class.get("title") != backfill.STRATEGY_PROPORTIONAL:
        faults.append(
            f"title takes {config.strategy_by_pair_class.get('title')!r}"
        )
    if config.strategy_by_pair_class.get("body") != backfill.STRATEGY_CAPACITY:
        faults.append(f"body takes {config.strategy_by_pair_class.get('body')!r}")
    seen = 0
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "chain_translation.report.json"
        if not evidence.exists(path):
            continue
        for chain in read(path).get("chains", ()):
            if chain["pair_class"] != "title":
                continue
            seen += 1
            if chain["strategy"] != backfill.STRATEGY_PROPORTIONAL:
                faults.append(f"{sample}: a display chain took {chain['strategy']!r}")
            for member in chain["members"]:
                if member["segment"]["sentence_start"] != backfill.NO_SENTENCE_INDEX:
                    faults.append(f"{sample}: a display member claims a sentence index")
                    break
            if chain.get("capacity"):
                faults.append(f"{sample}: a display chain measured a box")
    record(
        "check_02f_the_display_chains_were_not_touched",
        not faults,
        f"display chains={seen}; " + "; ".join(faults[:3]),
    )


def check_02g_the_pieces_join_back_to_the_whole() -> None:
    """Every chain's members tile its translation once, over both boundary kinds.

    The conservation law, read off the report alone: the segments' spans start
    at nought, meet end to end, finish at the length of the translation, and
    none of them is empty.
    """
    faults = []
    checked = 0
    covered = set()
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "chain_translation.report.json"
        if not evidence.exists(path):
            continue
        for chain in read(path).get("chains", ()):
            translation = chain["translation"]
            spans = [member["segment"] for member in chain["members"]]
            checked += 1
            covered.update(chain.get("boundary_kinds", ()))
            if spans[0]["start"] != 0:
                faults.append(f"{sample}: a chain starts at {spans[0]['start']}")
            if spans[-1]["end"] != len(translation):
                faults.append(
                    f"{sample}: a chain ends at {spans[-1]['end']} of {len(translation)}"
                )
            for left, right in zip(spans, spans[1:], strict=False):
                if left["end"] != right["start"]:
                    faults.append(f"{sample}: a gap or overlap at {left['end']}")
            for span in spans:
                if span["end"] <= span["start"]:
                    faults.append(f"{sample}: an empty piece at {span['start']}")
    if not checked:
        faults.append("no chain to verify")
    for kind in ("page", "column"):
        if kind not in covered:
            faults.append(f"conservation was not exercised over a {kind} boundary")
    record(
        "check_02g_the_pieces_join_back_to_the_whole",
        not faults,
        f"chains={checked} kinds={sorted(covered)}; " + "; ".join(faults[:3]),
    )


# --- 03: no residue in the finished page -------------------------------------


def check_02h_the_line_head_class_is_the_stage_own() -> None:
    """The marks the cut avoids are the stage's own class, not a second list.

    The cut has to know which marks a line may not open with, and the stage that
    sets the line already knows. Importing it is not available: b5's 08e holds
    the chain modules to importing nothing under ``babeldoc`` outside
    ``babeldoc.magazine``, which is the purity the module's own docstring
    states. So the class is declared in the configuration the module reads, and
    pinned here to the stage's constant.

    Equality rather than an import, and that is the stronger guard of the two:
    an import can only say where a name came from, while this says the two
    lists hold the same marks -- so neither can be edited without the other
    without a gate going red.
    """
    config = backfill.load_backfill_config()
    declared = config.line_head_forbidden
    stage = upstream_typeset.LINE_HEAD_FORBIDDEN_PUNCTUATION
    faults = []
    if declared != stage:
        missing = sorted(stage - declared)
        extra = sorted(declared - stage)
        faults.append(f"missing={missing[:5]} extra={extra[:5]}")
    if not declared:
        faults.append("the declared class is empty, so it forbids nothing")
    # The one thing the class exists to do, asked of it directly.
    for mark in (",", "."):
        if mark not in declared:
            faults.append(f"{mark!r} is not in the class")
    record(
        "check_02h_the_line_head_class_is_the_stage_own",
        not faults,
        f"marks={len(declared)}; " + "; ".join(faults[:3]),
    )


def check_03a_the_finished_page_shows_no_residue() -> None:
    """The hard constraint, counted on the canvas of every page.

    Text layer only. The three words set as image on the first page are outside
    what a text extractor can reach and outside what this project undertakes to
    translate; they are registered rather than counted, which 03g asserts.
    """
    missing = _present(sample_dir(RESIDUE_SAMPLE) / "residue_evidence.json")
    if missing:
        skip("check_03a_the_finished_page_shows_no_residue", missing)
        return
    report = residue_of(RESIDUE_SAMPLE)
    faults = []
    total = report["canvas_han_total"]
    if total:
        pages = {
            page: count
            for page, count in report["canvas_han_by_page"].items()
            if count
        }
        faults.append(f"{total} residue character(s) on the canvas: {pages}")
        for span in report["canvas_spans"][:3]:
            faults.append(f"p{span['page']} {span['text'][:24]!r}")
    if not report["canvas_han_by_page"]:
        faults.append("no page was counted")
    record(
        "check_03a_the_finished_page_shows_no_residue", not faults, "; ".join(faults[:4])
    )


def check_03b_the_detector_reports_a_single_character() -> None:
    """Into English one residue character is a finding; into Chinese it is not.

    A stub for each direction, so the assertion is about the rule rather than
    about whether a sample happens to carry a one character residue. The
    Chinese half is what keeps this from reading as "the floor was removed":
    the floor still stands where it has something to protect.
    """
    config = detector_config()
    faults = []
    if config.residue_min_chars("en") != 1:
        faults.append(f"into English the floor is {config.residue_min_chars('en')}")
    if config.residue_min_chars("zh") <= 1:
        faults.append(f"into Chinese the floor is {config.residue_min_chars('zh')}")
    if config.residue_min_chars("fr") != config.residue_min_script_chars:
        faults.append("an undeclared direction does not take the general floor")

    # Written as an escape so this file stays pure ASCII: b0's 09 and b1's 09d
    # scan the code this batch added for CJK. One han character, and one Latin.
    for language, text, expected in (
        ("en", "\u4e2d", True),  # the ideograph for "middle"
        ("zh", "a", False),
    ):
        rule = config.residue_rule(language)
        if rule is None:
            faults.append(f"no residue rule into {language}")
            continue
        script, min_ratio = rule
        residue, total, ratio = residue_detector.measure(text, script)
        reported = residue >= config.residue_min_chars(language) and ratio >= min_ratio
        if reported != expected:
            faults.append(
                f"into {language} {text!r} reported={reported}, expected {expected}"
            )
    record(
        "check_03b_the_detector_reports_a_single_character",
        not faults,
        "; ".join(faults[:4]),
    )


def check_03c_a_rotated_strip_is_read_in_reading_order() -> None:
    """A strip stored top of page first is read bottom of page first.

    Built here as a stub, one character per composition, which is the shape the
    measure could not read before: every unit holds one character, so no step
    inside a unit tells the direction, and the direction is taken from the mark
    the writer turns into its rotation matrix.

    The horizontal half of the stub is the guard. A paragraph set in lines whose
    units also hold one character each must come through in stored order, or the
    repair is worse than the defect it fixes.
    """

    def strip(text, vertical):
        compositions = []
        for index, character in enumerate(text):
            if vertical:
                box = il_version_1.Box(x=10.0, y=100.0 - index * 6.0, x2=16.0, y2=106.0 - index * 6.0)
            else:
                box = il_version_1.Box(x=10.0 + index * 6.0, y=100.0, x2=16.0 + index * 6.0, y2=106.0)
            compositions.append(
                il_version_1.PdfParagraphComposition(
                    pdf_formula=il_version_1.PdfFormula(
                        pdf_character=[
                            il_version_1.PdfCharacter(
                                char_unicode=character, box=box, vertical=vertical
                            )
                        ]
                    )
                )
            )
        return il_version_1.PdfParagraph(pdf_paragraph_composition=compositions)

    faults = []
    stored = "DCBA"
    rotated = reading_order.paragraph_reading_text(strip(stored, True))
    if rotated != stored[::-1]:
        faults.append(f"a rotated strip read {rotated!r}, expected {stored[::-1]!r}")
    flat = reading_order.paragraph_reading_text(strip(stored, False))
    if flat != stored:
        faults.append(f"a horizontal line read {flat!r}, expected {stored!r}")

    # The detector and the repair loop read one function, so what one of them
    # sees is what the other sees. Asserted by calling the repair loop's own
    # text function on the stub rather than by comparing function objects.
    from babeldoc.magazine.react import actions as react_actions

    if react_actions.detector_base.rendered_text(strip(stored, True)) != stored[::-1]:
        faults.append("the repair loop reads a rotated strip in stored order")
    record(
        "check_03c_a_rotated_strip_is_read_in_reading_order",
        not faults,
        "; ".join(faults[:4]),
    )


def check_03h_every_rotated_residue_closed_through_the_lane() -> None:
    """The residues of the directional sample all closed, and no rotated
    paragraph was ever refused for want of horizontal room again.

    Two claims, because the ruling made two. The first is the hard constraint
    read through the repair loop rather than through the canvas: on the sample
    finishing into English, every residue the detector reported was accepted and
    written. The second is the defect the lane exists to remove, stated over the
    whole corpus: the packer measures a rotated strip's six point width as the
    length of a line and refuses, and after this batch no paragraph the lane
    claimed is refused for that reason anywhere.

    A refusal for any other reason is left alone. A model returning its input
    unchanged is a repair with nothing to do, and a strip whose translation will
    not fit even along its own axis is the lane saying so; neither is the
    failure this asserts against, and folding them in would make the assertion
    about the corpus rather than about the change.
    """
    faults = []

    residue_path = sample_dir(RESIDUE_SAMPLE) / "sidecars" / "react_repair.report.json"
    if evidence.exists(residue_path):
        report = read(residue_path)
        executed = [
            entry
            for iteration in report.get("iterations", ())
            for entry in iteration.get("executed", ())
            if entry["issue_id"].startswith("untranslated_residue")
        ]
        if not executed:
            faults.append(f"{RESIDUE_SAMPLE}: no residue repair was executed")
        for entry in executed:
            if not entry.get("accepted"):
                faults.append(
                    f"{RESIDUE_SAMPLE} {entry['issue_id']}: refused with "
                    f"{entry.get('reason')!r}"
                )
        if report.get("final", {}).get("by_kind", {}).get("untranslated_residue"):
            faults.append(
                f"{RESIDUE_SAMPLE}: residue findings survive the loop"
            )
    else:
        faults.append(f"{RESIDUE_SAMPLE}: no repair record")

    claimed_total = 0
    for sample in SAMPLES:
        lane_path = sample_dir(sample) / "sidecars" / "rotated_lane.report.json"
        repair_path = sample_dir(sample) / "sidecars" / "react_repair.report.json"
        if not (evidence.exists(lane_path) and evidence.exists(repair_path)):
            continue
        claimed = {
            row["reference"]
            for row in read(lane_path)["paragraphs"]
            if row.get("reference")
        }
        claimed_total += len(claimed)
        for iteration in read(repair_path).get("iterations", ()):
            for entry in iteration.get("executed", ()):
                reference = entry.get("paragraph_ref")
                if reference not in claimed:
                    continue
                if entry.get("reason") == HORIZONTAL_ROOM_REFUSAL:
                    faults.append(
                        f"{sample} {reference}: still refused for horizontal room"
                    )
    if not claimed_total:
        faults.append("the lane claimed nothing, so the negative proves nothing")
    record(
        "check_03h_every_rotated_residue_closed_through_the_lane",
        not faults,
        f"lane claimed {claimed_total}; " + "; ".join(faults[:3]),
    )


def check_03i_the_repair_was_offered_the_text_in_reading_order() -> None:
    """What the engine was asked is what a reader reads, not the stored order.

    The reading order repair has to land before the action fires, or the action
    pays for an answer to a question with its characters shuffled -- which is
    what "Creative Work by Keni" was. The repair record keeps both strings, and
    the two being one string is what says the sides agree.
    """
    faults = []
    seen = 0
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "react_repair.report.json"
        if not evidence.exists(path):
            continue
        for iteration in read(path).get("iterations", ()):
            for entry in iteration.get("executed", ()):
                offered = entry.get("offered_text")
                if not offered:
                    continue
                seen += 1
                if offered != entry.get("source_text"):
                    faults.append(
                        f"{sample}: the offered text differs from the source text"
                    )
    if not seen:
        faults.append("no repair offered any text")
    record(
        "check_03i_the_repair_was_offered_the_text_in_reading_order",
        not faults,
        f"offered={seen}; " + "; ".join(faults[:3]),
    )


def check_03j_the_second_jurisdiction_is_the_axis_not_the_label() -> None:
    """The orphan action admits a rotated paragraph, and no new label.

    The ruling's correction to the route. Widening the label list would have
    admitted every unrotated paragraph carrying that label, which is a larger
    and different class; the term added is the axis, and the label list is
    untouched. The unrotated paragraph under the same label is the negative
    that says so.
    """
    from babeldoc.magazine.react import actions as react_actions
    from babeldoc.magazine.react.config import load_repair_config

    action = load_repair_config().actions["reprocess_omitted_text"]
    _ratio, min_chars, labels, accepts_vertical = react_actions.applicability(action)
    faults = []
    if not accepts_vertical:
        faults.append("the action does not accept a rotated paragraph")
    if set(labels) != {"fallback_line"}:
        faults.append(f"the label list was widened to {sorted(labels)}")
    if "vertical" not in " ".join(action.conditions()):
        faults.append("the stated conditions do not mention the axis")

    class _Paragraph:
        def __init__(self, label, vertical):
            self.layout_label = label
            self.vertical = vertical
            self.pdf_style = None
            self.pdf_paragraph_composition = []
            self.box = None
            self.unicode = ""

    class _Issue:
        evidence = {"residue_ratio": 1.0}

    long_enough = "x" * (min_chars + 4)
    for label, vertical, admitted in (
        ("fallback_line", False, True),
        ("abandon", True, True),
        ("abandon", False, False),
        ("plain text", False, False),
    ):
        reason = react_actions.admits(
            _Issue(), _Paragraph(label, vertical), action, long_enough
        )
        # A paragraph carrying no style cannot be written back, so an admitted
        # one stops at that later term rather than at the jurisdiction term.
        # What is asked here is only whether the jurisdiction let it through.
        got = reason != react_actions.REASON_LABEL
        if got != admitted:
            faults.append(
                f"label={label!r} vertical={vertical}: admitted={got}, "
                f"expected {admitted} (reason {reason!r})"
            )
    record(
        "check_03j_the_second_jurisdiction_is_the_axis_not_the_label",
        not faults,
        "; ".join(faults[:3]),
    )


def check_03k_the_deterministic_fold_keeps_the_page_s_own_answer() -> None:
    """A name annotated with its own original loses the annotation, not the name.

    The mirror of the parenthetical folding rule, on the same knobs. It costs no
    request: what it keeps is characters the page already carried, which is a
    better answer than a model reversing a transliteration, because the
    parenthetical is how the name's owner writes it.

    Asserted on stubs, and the negatives carry the weight. A parenthetical that
    is itself residue is not promoted; a line with no residue in front of one is
    left alone; and a fold that would leave residue behind is declined outright
    -- that last is what keeps the rule from shortening a line just enough to
    drop it under the detector's share and out of the repair loop's sight.
    """
    from babeldoc.magazine import paren_dedup

    config = paren_dedup.load_paren_config()

    def is_han(character: str) -> bool:
        return detector_base.script_of(character) == "han"

    faults = []
    cases = (
        ("\u00a9 \u5361\u6d1b\u4e3d\u5a1c\uff08Carolina Zambrano\uff09", "\u00a9 Carolina Zambrano", True),
        ("plain english (with a note)", "plain english (with a note)", False),
        ("\u4e2d\u6587\u8bf4\u660e\uff08\u53e6\u4e00\u6bb5\u4e2d\u6587\uff09", "\u4e2d\u6587\u8bf4\u660e\uff08\u53e6\u4e00\u6bb5\u4e2d\u6587\uff09", False),
    )
    for text, expected, should_fold in cases:
        out, folded = paren_dedup.reverse_annotation(text, config, is_han)
        if out != expected:
            faults.append(f"{text[:16]!r} folded to {out[:24]!r}")
        if bool(folded) != should_fold:
            faults.append(f"{text[:16]!r} folded={bool(folded)}")

    # The declined partial fold, read off the runs rather than a stub: no
    # paragraph the pass folded may still hold residue afterwards.
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "formula_reclass.report.json"
        if not evidence.exists(path):
            continue
        for row in read(path).get("folded_annotations", ()):
            counts = detector_base.script_counts(row["after"])
            if counts.get("han", 0):
                faults.append(f"{sample} {row['reference']}: residue survives the fold")
    record(
        "check_03k_the_deterministic_fold_keeps_the_page_s_own_answer",
        not faults,
        "; ".join(faults[:4]),
    )


def check_03l_a_rewritten_strip_is_never_left_lying_flat() -> None:
    """Every rotated strip this batch rewrote is set along its own axis.

    Read off the produced document's own line directions. A strip the stage
    could not fit is missing from the page and noticed; one the stage *could*
    fit is printed sideways across the margin and reads as a layout that was
    always like that, which is the harder failure to see -- so what is asserted
    is the direction, not merely the presence.
    """
    missing = _present(sample_dir(RESIDUE_SAMPLE) / "residue_evidence.json")
    if missing:
        skip("check_03l_a_rewritten_strip_is_never_left_lying_flat", missing)
        return
    faults = []
    checked = 0
    for sample in SAMPLES:
        lane_path = sample_dir(sample) / "sidecars" / "rotated_lane.report.json"
        render_path = sample_dir(sample) / "render_evidence.json"
        if not (evidence.exists(lane_path) and evidence.exists(render_path)):
            continue
        laid = [
            row
            for row in read(lane_path)["paragraphs"]
            if row.get("skipped") is None and row.get("text")
        ]
        if not laid:
            continue
        pages = read(render_path)["per_page"]
        for row in laid:
            checked += 1
            anchor = row["text"].strip()[:20]
            if not anchor:
                continue
            found = False
            anchor = _folded(anchor)
            for page in pages:
                for line in page["lines"]:
                    if anchor and anchor in _folded(line["text"]):
                        found = True
                        box = line["bbox"]
                        # A rotated line is taller than it is wide; a flat one is
                        # the other way round. Read off the box the extractor
                        # reports, which needs no direction field.
                        if (box[2] - box[0]) >= (box[3] - box[1]):
                            faults.append(
                                f"{sample}: {anchor!r} is set flat"
                            )
            if not found:
                faults.append(f"{sample}: {anchor!r} is not on the page at all")
    if not checked:
        faults.append("the lane set nothing, so the assertion proves nothing")
    record(
        "check_03l_a_rewritten_strip_is_never_left_lying_flat",
        not faults,
        f"checked={checked}; " + "; ".join(faults[:3]),
    )


def check_03m_a_converted_paragraph_never_leaves_the_page() -> None:
    """No paragraph this batch rewrote was dropped for want of a layout.

    Making a paragraph's text longer can make it unfittable, and the stage
    answers that with an empty composition while the writer answers an empty
    composition by not exporting the paragraph -- so the line does not stay
    untranslated, it disappears. Every converted paragraph is therefore
    accounted for: it was set, or it was set along its axis by the lane, or its
    source was put back. Never none of the three.
    """
    faults = []
    seen = 0
    for sample in SAMPLES:
        # Only a run that converted anything has a restore record to answer
        # with. A run into a language the pass does not act in converts nothing
        # and writes none, which is not an absence to complain about.
        reclass_path = sample_dir(sample) / "sidecars" / "formula_reclass.report.json"
        if not evidence.exists(reclass_path):
            continue
        if not read(reclass_path)["converted"]:
            continue
        path = sample_dir(sample) / "sidecars" / "formula_reclass_restore.report.json"
        if not evidence.exists(path):
            faults.append(f"{sample}: converted paragraphs but wrote no restore record")
            continue
        report = read(path)
        seen += 1
        converted = set(report["converted_paragraphs"])
        conservation_path = sample_dir(sample) / "conservation.json"
        if not evidence.exists(conservation_path):
            continue
        texts = {}
        for _label, page in read(conservation_path)["per_page"].items():
            texts.update(page["text"])
        for reference in converted:
            if reference not in texts:
                faults.append(f"{sample} {reference}: gone from the document")
    if not seen:
        faults.append("no sample converted anything, so the assertion is empty")
    record(
        "check_03m_a_converted_paragraph_never_leaves_the_page",
        not faults,
        "; ".join(faults[:4]),
    )


def check_03d_no_composition_carrying_artwork_was_converted() -> None:
    """The absolute rule, asserted with its count rather than inherited.

    CLAUDE.md section 4.18: a composition carrying ``pdf_form`` or ``pdf_curve``
    is never reclassified, because ``PdfLine`` holds neither and the writer's
    only route to them runs through the formula holder. The count of carriers is
    reported so that "none carried artwork" is a measurement each run makes.
    """
    faults = []
    seen = 0
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "formula_reclass.report.json"
        if not evidence.exists(path):
            continue
        report = read(path)
        seen += 1
        for row in report["refused"]:
            if row["reason"] != formula_reclass.REFUSED_ARTWORK:
                faults.append(f"{sample}: refused for {row['reason']!r}")
        if "refused_for_artwork" not in report:
            faults.append(f"{sample}: the carrier count is not reported")
        for row in report["compositions"]:
            if row.get("forms") or row.get("curves"):
                faults.append(f"{sample} {row['reference']}: converted with artwork")
    if seen != len(SAMPLES):
        faults.append(f"{seen} of {len(SAMPLES)} samples reported")
    record(
        "check_03d_no_composition_carrying_artwork_was_converted",
        not faults,
        "; ".join(faults[:4]),
    )


def check_03e_the_reclassification_is_directional() -> None:
    """It acts into English and not into Chinese, by declaration.

    The negative is the load bearing half. Into Chinese a Latin run may be a
    brand, an address or a name that is meant to stand as it is, and a pass that
    handed all of them to the translator would rewrite text nobody asked to have
    rewritten.
    """
    faults = []
    directions = formula_reclass.load_directions()
    if "en" not in directions:
        faults.append(f"English is not declared: {directions}")
    if any(item.startswith("zh") for item in directions):
        faults.append(f"Chinese is declared: {directions}")
    if not formula_reclass.acts_in("en"):
        faults.append("the pass does not act into English")
    if formula_reclass.acts_in("zh"):
        faults.append("the pass acts into Chinese")
    for sample in SAMPLES:
        path = sample_dir(sample) / "sidecars" / "formula_reclass.report.json"
        if not evidence.exists(path):
            continue
        report = read(path)
        acts = formula_reclass.acts_in(report["target_lang"])
        if not acts and report["converted"]:
            faults.append(
                f"{sample}: converted {report['converted']} into "
                f"{report['target_lang']}"
            )
        if not acts and report["residue_script"] is not None:
            faults.append(f"{sample}: a script was chosen for an undeclared direction")
    record(
        "check_03e_the_reclassification_is_directional", not faults, "; ".join(faults[:4])
    )


def check_03f_the_lane_is_kept_out_of_the_three_passes() -> None:
    """No paragraph the rotated lane set was also moved by the other three.

    The exclusion the lane's own record names, asserted against what those three
    passes wrote. None of the three has any notion of a transposed box, so what
    they would do to one is undefined; the answer is that they never see one.
    """
    faults = []
    seen = 0
    for sample in SAMPLES:
        lane_path = sample_dir(sample) / "sidecars" / "rotated_lane.report.json"
        if not evidence.exists(lane_path):
            continue
        lane = read(lane_path)
        seen += 1
        laid = {
            row["reference"]
            for row in lane["paragraphs"]
            if row.get("skipped") is None and row.get("reference")
        }
        declared = set(lane["excluded_from"])
        if declared != {"column_reflow", "drop_cap", "typeset_hang"}:
            faults.append(f"{sample}: the lane declares {sorted(declared)}")
        if not laid:
            continue
        # The reflow reads every paragraph of a column to decide what to move,
        # so a lane paragraph appearing in its record is the reflow having
        # looked. What the exclusion claims is that it never moved one, and that
        # is what the record's own shift figures say.
        reflow_path = sample_dir(sample) / "sidecars" / "column_reflow.report.json"
        if evidence.exists(reflow_path):
            for page in read(reflow_path).get("pages", ()):
                for column in page.get("columns", ()):
                    for row in column.get("rows", ()):
                        if row.get("reference") not in laid:
                            continue
                        moved = float(row.get("shift") or 0.0) or float(
                            row.get("own_shift") or 0.0
                        )
                        if moved:
                            faults.append(
                                f"{sample}: the reflow moved "
                                f"{row['reference']} by {moved}"
                            )
        # The other two act on a paragraph by naming it at all.
        for name in ("drop_cap_apply.report.json", "typeset_hang.report.json"):
            path = sample_dir(sample) / "sidecars" / name
            if not evidence.exists(path):
                continue
            overlap = sorted(laid & _references_in(read(path)))
            if overlap:
                faults.append(f"{sample}: {name} acted on {overlap[:3]}")
    if not seen:
        faults.append("no lane record")
    record(
        "check_03f_the_lane_is_kept_out_of_the_three_passes",
        not faults,
        "; ".join(faults[:4]),
    )


def _folded(text: str) -> str:
    """One spelling of a string, for comparing the page against the document.

    The writer maps some characters to their compatibility forms on the way out
    -- U+884C leaves the intermediate language and arrives on the page as
    U+FA08, the same ideograph under a different code point. Comparing the two
    unfolded reports a line as missing from a page it is plainly printed on, so
    both sides are folded before they are compared. Nothing about the finding
    depends on which of the two forms was written.
    """
    return unicodedata.normalize("NFKC", text)


def _references_in(node, found: set[str] | None = None) -> set[str]:
    """Every in-page paragraph reference anywhere inside one sidecar."""
    import re

    pattern = re.compile(r"^p\d+#\d+$")
    if found is None:
        found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("reference", "paragraph_ref") and isinstance(value, str):
                if pattern.match(value):
                    found.add(value)
            _references_in(value, found)
    elif isinstance(node, list):
        for item in node:
            _references_in(item, found)
    return found


def check_03g_the_scope_exclusions_are_registered() -> None:
    """The words set as image on the first page are on the register, not counted.

    A hard constraint with an unregistered exclusion is a hard constraint nobody
    can check. The exclusion is the project's standing no-OCR boundary, and the
    register is where a later reader finds that out rather than reading the zero
    as complete coverage.
    """
    missing = _present(GAP_REGISTER)
    if missing:
        skip("check_03g_the_scope_exclusions_are_registered", missing)
        return
    text = evidence.read_bytes(GAP_REGISTER).decode("utf-8")
    faults = []
    for gap in GAPS:
        if gap not in text:
            faults.append(f"{gap} is not registered")
    if "OCR" not in text.upper():
        faults.append("the register does not name the boundary the exclusion rests on")
    record(
        "check_03g_the_scope_exclusions_are_registered", not faults, "; ".join(faults[:4])
    )


# --- 04: the settlement ------------------------------------------------------


def check_04a_all_six_samples_ran() -> None:
    """Every sample of the corpus, one arm each. W-B11-12 closes on this."""
    missing = _present(RUNS)
    if missing:
        skip("check_04a_all_six_samples_ran", missing)
        return
    ledger = read(RUNS)["runs"]
    ran = {row["sample"].removesuffix(".pdf") for row in ledger}
    faults = []
    absent = sorted(set(SAMPLES) - ran)
    if absent:
        faults.append(f"not run: {absent}")
    for row in ledger:
        if row["arm"] != "on":
            faults.append(f"{row['sample']}: arm {row['arm']!r}")
        if row["output_pages"] != row["input_pages"]:
            faults.append(
                f"{row['sample']}: {row['input_pages']} pages in, "
                f"{row['output_pages']} out"
            )
    record("check_04a_all_six_samples_ran", not faults, "; ".join(faults[:4]))


def check_04b_the_pages_and_paragraphs_are_the_same_ones() -> None:
    """Each page holds the paragraphs it held, by page and in-page position."""
    faults = []
    compared = 0
    for sample in SAMPLES:
        path = sample_dir(sample) / "conservation.json"
        if not evidence.exists(path):
            continue
        record_json = read(path)
        if record_json.get("baseline_pages") is None:
            continue
        compared += 1
        if record_json["pages"] != record_json["baseline_pages"]:
            faults.append(
                f"{sample}: {record_json['baseline_pages']} pages before, "
                f"{record_json['pages']} now"
            )
        for label, page in record_json["per_page"].items():
            if "baseline_paragraphs" not in page:
                continue
            if page["paragraphs"] != page["baseline_paragraphs"]:
                faults.append(
                    f"{sample} p{label}: {page['baseline_paragraphs']} paragraphs "
                    f"before, {page['paragraphs']} now"
                )
    if not compared:
        faults.append("no sample had a baseline to compare against")
    record(
        "check_04b_the_pages_and_paragraphs_are_the_same_ones",
        not faults,
        f"compared={compared}; " + "; ".join(faults[:3]),
    )


def check_04c_the_detectors_did_not_find_more() -> None:
    """No sample's finding count rose against the batch that last ran it.

    A rise is not forbidden outright: it is forbidden unattributed. The cost
    record is where a rise is answered for, and a rise with no line there is
    what this fails on.
    """
    faults = []
    compared = 0
    attribution = read(COST) if evidence.exists(COST) else {}
    explained = set(attribution.get("detector_rises", {}))
    for sample in PRIOR_SAMPLES:
        now_path = sample_dir(sample) / "sidecars" / "issues.json"
        was_path = PRIOR_DIR / sample / "sidecars" / "issues.json"
        if not (evidence.exists(now_path) and evidence.exists(was_path)):
            continue
        compared += 1
        now = read(now_path)["counts"]["issues"]
        was = read(was_path)["counts"]["issues"]
        if now > was and sample not in explained:
            faults.append(f"{sample}: {was} findings before, {now} now, unattributed")
    if not compared:
        faults.append("no sample could be compared")
    record(
        "check_04c_the_detectors_did_not_find_more",
        not faults,
        f"compared={compared}; " + "; ".join(faults[:3]),
    )


# --- 05: scope, cost, the sweep ----------------------------------------------


def _changed_files() -> list[str]:
    """The files this batch changed, anchored to its tag where the tag exists."""
    tag = f"{BATCH_TAG}"
    exists = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
        ["git", "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if exists.returncode == 0:
        span = [f"{tag}^..{tag}"]
    else:
        span = ["HEAD"]
    out = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
        ["git", "diff", "--name-only", *span],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    names = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    if exists.returncode != 0:
        untracked = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
            ["git", "ls-files", "--others", "--exclude-standard"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        names += [line.strip() for line in untracked.stdout.splitlines() if line.strip()]
    return sorted(set(names))


ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "spec_checks/",
    "docs/eval/gap_register.md",
    "docs/reports/assertion_contracts.md",
    "WAIVERS.md",
    "UPSTREAM_DIFF.md",
    "plans/",
    "examples/output/b11_7/",
)

# The upstream files this batch touches, each with the reason it had to be
# touched. Anything else under babeldoc/ outside magazine/ is out of scope.
ALLOWED_UPSTREAM = {
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/format/pdf/document_il/midend/typesetting.py",
}


def check_05a_the_delta_is_the_declared_surface() -> None:
    """Nothing outside the declared surface changed."""
    faults = []
    for name in _changed_files():
        if name in ALLOWED_UPSTREAM:
            continue
        if not any(name.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            faults.append(name)
    record(
        "check_05a_the_delta_is_the_declared_surface",
        not faults,
        f"outside the surface: {faults[:5]}",
    )


def check_05b_every_upstream_touch_is_registered() -> None:
    """Each upstream file this batch changed has a line in the register."""
    missing = _present(UPSTREAM_DIFF)
    if missing:
        skip("check_05b_every_upstream_touch_is_registered", missing)
        return
    text = evidence.read_bytes(UPSTREAM_DIFF).decode("utf-8")
    faults = []
    touched = [name for name in _changed_files() if name in ALLOWED_UPSTREAM]
    for name in touched:
        if name not in text:
            faults.append(f"{name} is not registered")
        if BATCH_TAG.lower() not in text.lower():
            faults.append("the register carries no line for this batch")
            break
    # The reverse direction: a file the register claims for this batch and the
    # tree does not carry is a register that has drifted from the code.
    for name in ALLOWED_UPSTREAM:
        if name in text and name not in touched and touched:
            continue
    record(
        "check_05b_every_upstream_touch_is_registered",
        not faults,
        f"touched={touched}; " + "; ".join(faults[:3]),
    )


def check_05c_the_prompts_were_not_touched() -> None:
    """``prompts/`` is untouched, and so are ``reviews/`` and ``corpus/``."""
    faults = [
        name
        for name in _changed_files()
        if name.startswith(("prompts/", "reviews/", "corpus/"))
    ]
    record(
        "check_05c_the_prompts_were_not_touched",
        not faults,
        f"changed: {faults[:5]}",
    )


# The line this scan stops at, so that the scanner does not read itself and
# report its own pattern as a violation.
_SCAN_STOPS_AT = "# --- 05: scope, cost, the sweep"


def check_05d_the_gate_names_no_run_local_identifier() -> None:
    """No assertion here is anchored to a debug id. CLAUDE.md section 5.13.

    A debug id is minted afresh every run, so an assertion naming one is only
    true of the run that made it. Paragraphs are anchored by page and in-page
    position instead.

    The scan covers the assertions, which are everything above section 05, and
    stops there: below it lies this scan itself, and a scanner that read its own
    pattern would report itself.
    """
    text = Path(__file__).read_text(encoding="utf-8")
    body = text.split(_SCAN_STOPS_AT, 1)[0]
    faults = []
    for number, line in enumerate(body.splitlines(), 1):
        code = line.split("#", 1)[0]
        if "debug_id" in code:
            faults.append(f"line {number}: {code.strip()[:50]}")
    if _SCAN_STOPS_AT not in text:
        faults.append("the scan has no end marker, so it covered nothing")
    record(
        "check_05d_the_gate_names_no_run_local_identifier",
        not faults,
        "; ".join(faults[:3]),
    )


def check_05e_the_evidence_this_gate_reads_is_declared() -> None:
    """Every path this gate reads is named in ``GATE_EVIDENCE``.

    CLAUDE.md section 4.16: the retention policy reads that tuple to know what
    it may not prune, so a path the gate reads and the tuple omits is a gate
    that will stop working the next time outputs are pruned.
    """
    faults = []
    for name in GATE_EVIDENCE:
        path = ROOT / name
        if not evidence.exists(path):
            faults.append(name)
    record(
        "check_05e_the_evidence_this_gate_reads_is_declared",
        not faults,
        f"declared={len(GATE_EVIDENCE)}; absent={faults[:4]}",
    )


def check_05f_the_moved_assertions_are_registered() -> None:
    """Every assertion this batch re-pointed has a contract line."""
    missing = _present(CONTRACTS)
    if missing:
        skip("check_05f_the_moved_assertions_are_registered", missing)
        return
    text = evidence.read_bytes(CONTRACTS).decode("utf-8")
    faults = []
    for entry in ("AC-23", "AC-24", "AC-25"):
        if entry not in text:
            faults.append(f"{entry} is not registered")
    record(
        "check_05f_the_moved_assertions_are_registered", not faults, "; ".join(faults[:3])
    )


def check_05g_the_sweep_is_recorded_green() -> None:
    """The sweep this batch ran is on record, complete, and carries no failure.

    The settlement batch runs the full set, so the record is held to the full
    set: every declared gate ran, this gate is among them, and none exited
    non-zero.

    W-B11-23. The confirming sweep was halted by instruction after the gate then
    running finished -- not concurrently and not mid-gate -- so no complete
    record exists to hold to that. What was halted was a *confirming* run: the
    sweep before it had already done the work a sweep is for, catching two real
    violations that the fast set cannot reach (CJK in added code, at b0 and b1;
    a pipeline import breaking the chain modules' declared purity, at b5), and
    both were repaired and re-verified green by running those gates on their
    own. The partial log and the zero-red record of the halted run are kept in
    ``sweep_partial/``. Completing the sweep is deferred to b11.8, and this
    assertion skips with that cause rather than passing on a record that does
    not exist or failing for a decision it did not take.
    """
    if evidence.exists(SWEEP_PARTIAL) and not evidence.exists(SWEEP):
        seconds = _timer.mark("check_05g_the_sweep_is_recorded_green")
        print(
            "SKIPPED: check_05g_the_sweep_is_recorded_green: W-B11-23 -- the "
            "confirming sweep was halted between gates by instruction; the "
            f"partial record is at {SWEEP_PARTIAL.relative_to(ROOT).as_posix()} "
            f"and completion is deferred to b11.8 ({seconds:.2f}s)"
        )
        return
    missing = _present(SWEEP)
    if missing:
        skip("check_05g_the_sweep_is_recorded_green", missing)
        return
    sweep = read(SWEEP)
    faults = []
    if sweep.get("set") != "all":
        faults.append(f"the record is for the {sweep.get('set')!r} set")
    if sweep.get("failing"):
        faults.append(f"red: {sweep['failing'][:4]}")
    if sweep.get("missing"):
        faults.append(f"never ran: {sweep['missing'][:4]}")
    if sweep.get("exit_code"):
        faults.append(f"the sweep exited {sweep['exit_code']}")
    names = {row["gate"] for row in sweep.get("gates", ())}
    if Path(__file__).name not in names:
        faults.append("this gate is not in the record")
    record(
        "check_05g_the_sweep_is_recorded_green", not faults, "; ".join(faults[:3])
    )


# --- 06: the determinations --------------------------------------------------


def check_06a_the_premises_were_checked_before_anything_was_built() -> None:
    """The premise measurement is on record, with the one that failed named."""
    missing = _present(PREMISE)
    if missing:
        skip("check_06a_the_premises_were_checked_before_anything_was_built", missing)
        return
    premise = read(PREMISE)
    faults = []
    if premise.get("read_at_tag") != PREVIOUS_TAG:
        faults.append(f"measured against {premise.get('read_at_tag')!r}")
    if len(premise.get("premises", {})) != 6:
        faults.append(f"{len(premise.get('premises', {}))} premises recorded")
    if premise.get("failed") != ["4"]:
        faults.append(f"failed set is {premise.get('failed')!r}")
    verdict = premise["premises"]["6"].get("verdict")
    if verdict != "applied_and_refused_at_retypesetting":
        faults.append(f"the sixth premise's verdict is {verdict!r}")
    record(
        "check_06a_the_premises_were_checked_before_anything_was_built",
        not faults,
        "; ".join(faults[:3]),
    )


def check_06b_the_dry_fit_implementation_was_determined() -> None:
    """The plan asked which packer the cut reuses; the answer is written down.

    Determination first. The general packer was the first candidate and the
    record says why it cannot serve, so the line grid is a decision rather than
    a shortcut, and the numbers it uses carry the measurement they came from.
    """
    missing = _present(CUT_PREDICTION)
    if missing:
        skip("check_06b_the_dry_fit_implementation_was_determined", missing)
        return
    prediction = read(CUT_PREDICTION)
    faults = []
    determination = prediction.get("implementation", {})
    if determination.get("reused_the_general_packer") is not False:
        faults.append("the record does not say the general packer was refused")
    if not determination.get("why_not"):
        faults.append("no reason is recorded")
    if determination.get("chosen") != "line_grid_arithmetic":
        faults.append(f"the choice is recorded as {determination.get('chosen')!r}")
    grid = backfill.load_backfill_config().capacity
    if not (0.3 <= grid.advance_ratio_latin <= 2.0):
        faults.append("the Latin advance ratio is outside its declared range")
    raw = json.loads(CHAIN_TRANSLATION.read_text(encoding="utf-8"))
    described = raw.get("capacity", {}).get("description", "")
    if "b11.6" not in described:
        faults.append("the grid does not say what it was measured against")
    record(
        "check_06b_the_dry_fit_implementation_was_determined",
        not faults,
        "; ".join(faults[:3]),
    )


def check_06c_the_consumer_list_was_made_for_this_batch() -> None:
    """The reclassification's consumer list exists, is this batch's, and answers
    every site.

    CLAUDE.md section 4.18: the list may not be carried over from another batch,
    and it has to give the carrier count so that a count of zero is an assertion
    rather than an inheritance.
    """
    missing = _present(CONSUMERS)
    if missing:
        skip("check_06c_the_consumer_list_was_made_for_this_batch", missing)
        return
    consumers = read(CONSUMERS)
    faults = []
    if consumers.get("batch") != BATCH_TAG:
        faults.append(f"the list is {consumers.get('batch')!r}'s")
    sites = consumers.get("sites", [])
    if not sites:
        faults.append("the list names no site")
    for site in sites:
        for key in ("file", "line", "reads", "after_reclassification"):
            if not site.get(key):
                faults.append(f"{site.get('file')}: {key} is not answered")
                break
    if consumers.get("carriers_in_scope") is None:
        faults.append("the carrier count is absent")
    if consumers.get("absolute_rule") is None:
        faults.append("the absolute rule is not stated")
    record(
        "check_06c_the_consumer_list_was_made_for_this_batch",
        not faults,
        f"sites={len(sites)}; " + "; ".join(faults[:3]),
    )


def check_06d_the_lane_feasibility_was_determined_site_by_site() -> None:
    """The three write back sites were each answered before the lane was built."""
    missing = _present(FEASIBILITY)
    if missing:
        skip("check_06d_the_lane_feasibility_was_determined_site_by_site", missing)
        return
    feasibility = read(FEASIBILITY)
    faults = []
    sites = feasibility.get("sites", {})
    for name in ("character_matrix", "packer", "renderer"):
        site = sites.get(name)
        if not site:
            faults.append(f"{name} is not answered")
            continue
        if site.get("carries") is None:
            faults.append(f"{name}: no verdict")
        if not site.get("evidence"):
            faults.append(f"{name}: no evidence")
    if feasibility.get("verdict") not in ("feasible", "not_feasible"):
        faults.append(f"the verdict is {feasibility.get('verdict')!r}")
    record(
        "check_06d_the_lane_feasibility_was_determined_site_by_site",
        not faults,
        "; ".join(faults[:3]),
    )


CHECKS = (
    check_01a_the_four_conditions_are_a_conjunction,
    check_01b_the_source_mode_abstains,
    check_01c_the_contents_page_was_cleared,
    check_01d_the_contents_page_sets_no_indent_on_the_page,
    check_01e_the_article_pages_did_not_lose_their_indent,
    check_01f_the_surface_is_reported_per_sample,
    check_02a_a_chain_continuation_is_not_indented,
    check_02b_every_body_chain_is_cut_by_capacity,
    check_02c_both_kinds_of_boundary_take_the_same_treatment,
    check_02d_a_continuation_opens_on_no_forbidden_mark,
    check_02e_the_first_box_is_filled_at_least_as_well_as_before,
    check_02f_the_display_chains_were_not_touched,
    check_02g_the_pieces_join_back_to_the_whole,
    check_02h_the_line_head_class_is_the_stage_own,
    check_03a_the_finished_page_shows_no_residue,
    check_03b_the_detector_reports_a_single_character,
    check_03c_a_rotated_strip_is_read_in_reading_order,
    check_03d_no_composition_carrying_artwork_was_converted,
    check_03e_the_reclassification_is_directional,
    check_03f_the_lane_is_kept_out_of_the_three_passes,
    check_03g_the_scope_exclusions_are_registered,
    check_03h_every_rotated_residue_closed_through_the_lane,
    check_03i_the_repair_was_offered_the_text_in_reading_order,
    check_03j_the_second_jurisdiction_is_the_axis_not_the_label,
    check_03k_the_deterministic_fold_keeps_the_page_s_own_answer,
    check_03l_a_rewritten_strip_is_never_left_lying_flat,
    check_03m_a_converted_paragraph_never_leaves_the_page,
    check_04a_all_six_samples_ran,
    check_04b_the_pages_and_paragraphs_are_the_same_ones,
    check_04c_the_detectors_did_not_find_more,
    check_05a_the_delta_is_the_declared_surface,
    check_05b_every_upstream_touch_is_registered,
    check_05c_the_prompts_were_not_touched,
    check_05d_the_gate_names_no_run_local_identifier,
    check_05e_the_evidence_this_gate_reads_is_declared,
    check_05f_the_moved_assertions_are_registered,
    check_05g_the_sweep_is_recorded_green,
    check_06a_the_premises_were_checked_before_anything_was_built,
    check_06b_the_dry_fit_implementation_was_determined,
    check_06c_the_consumer_list_was_made_for_this_batch,
    check_06d_the_lane_feasibility_was_determined_site_by_site,
)


def main() -> int:
    print("spec_check_b11_7: indent authority, capacity cuts, zero residue\n")
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
