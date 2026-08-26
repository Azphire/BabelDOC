"""Gate script for batch B11.8 (keep redefined, the opening set both ways).

Run from the repository root:

    python spec_checks/spec_check_b11_8.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request. Every assertion is answered from a stub this gate builds, or
from the small derived evidence this batch wrote beside its runs, or from a file
git tracks -- never from a stage checkpoint and never from a produced PDF, per
CLAUDE.md section 4.16.

What this batch is.

T1 redefined the ``keep`` verdict. The merge pass now merges under either
verdict, so the engine is offered byte identical text whichever way a candidate
was ruled: an initial standing in a style run of its own is an initial the engine
can carry across untranslated, and that is true however the finished page is set.
What a verdict decides is therefore only what happens once the translation is
back. The per target language defaults follow: both declared languages declare
``keep``, because both languages have a convention for an opening initial.

T2 is the proposition that follows from T1 and is the reason it is safe: a
candidate ruled ``keep`` here is offered exactly the bytes the same candidate
ruled ``flatten`` was offered in b11.7. Both texts and both digests are written
into this batch's evidence, so the comparison outlives the runs.

T3 is the lane. ``babeldoc/magazine/drop_cap_render.py`` re-packs one paragraph
inside its own box: the opening character is set ``lines * advance`` tall with
its em box top on the first line's em box top, the lines beside it begin past a
reserve, and the line under it runs the full measure. The advance is measured off
the paragraph's own baselines, so nothing declares a line spacing twice. Two
regimes, one skeleton: a square block on an em grid where the target sets on one,
a tall letter measured from its own advance where it sets Latin.

T4 is the sweep debt. This batch runs no full sweep, by the ruling recorded in
W-B11-23 as revised, and pays down part of what the sweep alone could see by
giving the two static violation classes a cheap variant that runs in the fast
tier: Chinese characters in code this batch added, and a chain module importing
from the translation pipeline.

01 is T3 read geometrically. 02 is T3 read off the page. 03 is the negative
baseline. 04 is T2 and the cost. 05 is the fail plain branches. 06 is the ruling
and its pins. 07 is T4. 08 is conservation. 09 is scope.

Tiers: every assertion reads a stub or this batch's own derived evidence, so the
fast tier runs the whole gate.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import drop_cap_render as lane  # noqa: E402
from spec_checks import evidence  # noqa: E402
from spec_checks import harness  # noqa: E402
from spec_checks import spec_check_b0  # noqa: E402
from spec_checks import spec_check_b5  # noqa: E402
from spec_checks import spec_check_b7_5  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b11.8"
PREVIOUS_TAG = "b11.7"

BATCH_DIR = ROOT / "examples" / "output" / "b11_8"
PRIOR_DIR = ROOT / "examples" / "output" / "b11_7"

# The whole run scope. The first two were what premise 4 enumerated: of the six
# samples the corpus held when this batch began, they are the two carrying a
# drop cap candidate. The third arrived mid batch, when the corpus owner
# registered two Chinese source samples; it is the one of those two the parser
# can read, and it is what turns the Latin regime from a stub into a reading.
SAMPLES = ("Courier-en", "FD-en-v2", "HuaweiTech-zh")

# The samples that ran before this batch, and so the ones a state can be
# conserved against and a request compared with. A sample running for the first
# time has neither, and naming which is which is what keeps "unchanged" from
# being asserted about a comparison nobody made.
BASELINE_SAMPLES = ("Courier-en", "FD-en-v2")

# The sample registered mid batch that this pipeline cannot read: over four
# fifths of its characters arrive as CID references, which is the upstream
# extraction guard's own refusal and not this batch's. GAP-50.
UNREADABLE_SAMPLE = "Vogue-zh"

# Every anchor, by page and in-page position and by the character it opens with.
# Never by a debug id, which is reassigned every run (CLAUDE.md section 5.13).
# The three Chinese glyphs are written as escapes so this file stays pure ASCII,
# which b0's 09, b1's 09d and b2's 11c all require of spec_checks/*.py.
ANCHORS = {
    "Courier-en": {
        "p4#3": "\u65e9",  # zao, the opening character of "long before"
        "p5#5": "\u5728",  # zai, the opening character of "on the river"
        "p7#8": "\u4e16",  # shi, the opening character of "the world has"
    },
    "FD-en-v2": {
        "p8#9": "\u5728",  # zai, the opening character of "when it comes to"
    },
    # The other direction, on a real page rather than a stub. The source sinks
    # a Chinese initial and the translation sinks the Latin letter its own first
    # word opens with, which is the whole of what "both ways" means here.
    "HuaweiTech-zh": {
        "p4#11": "C",  # the opening letter of the English first word
    },
}

PREMISE = BATCH_DIR / "premise_check.json"
RUNS = BATCH_DIR / "runs.json"
COST = BATCH_DIR / "cost_attribution.json"
SWEEP = BATCH_DIR / "run_all.fast.json"
SYMMETRY = BATCH_DIR / "xml_symmetry.json"

RENDER_CONFIG = ROOT / "configs" / "drop_cap_render.json"
DROP_CAP_CONFIG = ROOT / "configs" / "drop_cap.json"
HITL_CONFIG = ROOT / "configs" / "hitl.json"
WAIVERS = ROOT / "WAIVERS.md"
GAP_REGISTER = ROOT / "docs" / "eval" / "gap_register.md"
UPSTREAM_DIFF = ROOT / "UPSTREAM_DIFF.md"
CONTRACTS = ROOT / "docs" / "reports" / "assertion_contracts.md"

# How near two measurements have to be to count as the same, in points. A
# hundredth of a point is below what any of these quantities is rounded to.
EPSILON = 0.01
# How near two drawn left edges have to be to count as one edge, in points.
EDGE_TOLERANCE = 0.5
# The multiple of the line advance a gap inside a paragraph may not exceed. The
# shape b11.5 recorded had one line of 13.87 points followed by a gap of 41.33,
# which is three times the advance; anything over one and a half is a hole.
HOLE_RATIO = 1.5
# How short a drawn line has to be, in characters, before it reads as a fragment
# left lying rather than as a line of type. The shape b11.5 recorded had three.
STRANDED_LINE_CHARS = 4

GAPS = ("GAP-47", "GAP-48", "GAP-49", "GAP-50", "GAP-51", "GAP-52", "GAP-53")

# The pins this batch moved, each because the corpus owner wrote the file it
# stands for while this batch was being built. A pin that moved has to carry the
# batch's own note beside it, which is what CLAUDE.md section 4.12 asks: the pin
# anchors "no machine edited this file", not "this file never changes".
REPINNED = (
    "reviews/Courier-en.decisions.json",
    "reviews/FD-en-v2.decisions.json",
    "corpus/page_labels.json",
    "corpus/registry.user.json",
    "corpus/chain_labels.user.json",
)

GATE_EVIDENCE = (
    "examples/output/b11_8/premise_check.json",
    "examples/output/b11_8/runs.json",
    "examples/output/b11_8/cost_attribution.json",
    "examples/output/b11_8/run_all.fast.json",
    "examples/output/b11_8/xml_symmetry.json",
) + tuple(
    f"examples/output/b11_8/{sample}/{name}"
    for sample in SAMPLES
    for name in (
        "run.json",
        "render_evidence.json",
        "dropcap_evidence.json",
        "request_equivalence.json",
        "conservation.json",
        "sidecars/drop_cap_render.report.json",
        "sidecars/drop_cap_apply.report.json",
        "sidecars/issues.json",
        "sidecars/react_repair.report.json",
        "sidecars/column_reflow.report.json",
    )
) + tuple(
    f"examples/output/b11_7/{sample}/sidecars/issues.json"
    for sample in BASELINE_SAMPLES
)

_passed = 0
_total = 0
_failures: list[str] = []
_timer = harness.Timer("spec_check_b11_8")


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


def dropcap_evidence(sample: str):
    return read(sample_dir(sample) / "dropcap_evidence.json")


def lane_rows(sample: str) -> dict:
    """Every paragraph the lane decided about, keyed by its reference."""
    body = dropcap_evidence(sample)["lane"]
    return {row["paragraph"]: row for row in body["paragraphs"]}


def page_heights(sample: str) -> dict:
    """Each page's height, so a box in PDF coordinates can be found on it."""
    body = read(sample_dir(sample) / "render_evidence.json")
    return {page["page"]: page["size"][1] for page in body["per_page"]}


def anchor_spans(sample: str, reference: str) -> tuple[list[dict], list[dict]]:
    """The spans standing where one anchor put its ink, split by size.

    The first list is what was drawn at the enlarged size and the second is the
    body. The band is the lane's own record of where it put the ink rather than
    the paragraph's box, because a box is taller than the lines set in it and
    the next paragraph's first line can begin inside the difference. Read off
    the page in the viewer's coordinates, which run down from the top, so the
    reach is turned over before it is used.
    """
    row = lane_rows(sample)[reference]
    body = dropcap_evidence(sample)
    height = page_heights(sample)[row["page"]]
    box, reach = row["box"], row["reach"]
    top = height - reach[3]
    bottom = height - reach[1]
    large: list[dict] = []
    small: list[dict] = []
    for page in body["anchor_pages"]:
        if page["page"] != row["page"]:
            continue
        for line in page["lines"]:
            for span in line["spans"]:
                x0, y0, x1, y1 = span["bbox"]
                if x0 < box[0] - 1.0 or x1 > box[2] + 1.0:
                    continue
                middle = (y0 + y1) / 2.0
                if middle < top - 2.0 or middle > bottom + 2.0:
                    continue
                if span["size"] > row["body_size"] * HOLE_RATIO:
                    large.append(span)
                elif abs(span["size"] - row["body_size"]) <= 0.1:
                    small.append(span)
    return large, small


def body_lines(spans: list[dict], advance: float) -> list[tuple[float, float]]:
    """Each drawn body line as its top and its left edge, topmost first.

    Grouped with a tolerance rather than on an exact top, because a line set in
    two fonts carries two ascents and so two span tops; two spans belong to one
    line when their tops differ by less than half a line advance, which no two
    real lines ever do.
    """
    groups: list[list] = []
    for span in sorted(spans, key=lambda item: item["bbox"][1]):
        if groups and span["bbox"][1] - groups[-1][0] < advance * 0.5:
            groups[-1][1].append(span)
        else:
            groups.append([span["bbox"][1], [span]])
    return [
        (
            top,
            min(span["bbox"][0] for span in members),
            "".join(
                span["text"]
                for span in sorted(members, key=lambda item: item["bbox"][0])
            ),
        )
        for top, members in groups
    ]


# --- 01: the shape, read off the lane's own record ---------------------------


def check_01a_every_anchor_was_set() -> None:
    """Each of the four anchors was set, and nothing else was decided about."""
    missing = _present(*(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES))
    if missing:
        skip("check_01a_every_anchor_was_set", missing)
        return
    faults = []
    for sample, anchors in ANCHORS.items():
        rows = lane_rows(sample)
        if set(rows) != set(anchors):
            faults.append(f"{sample}: decided about {sorted(rows)}")
            continue
        for reference, glyph in anchors.items():
            row = rows[reference]
            if not row["set"] or row["reverted"]:
                faults.append(f"{sample} {reference}: {row['revert_reason']}")
            if row["initial"] != glyph:
                faults.append(f"{sample} {reference}: opens with {row['initial']!r}")
            if row["decision"] != lane.kept_verdict():
                faults.append(f"{sample} {reference}: verdict {row['decision']!r}")
    record("check_01a_every_anchor_was_set", not faults, f"{faults[:4]}")


def check_01b_the_initial_is_as_tall_as_the_lines_it_stands_against() -> None:
    """The set size is the declared line count times the measured advance.

    Which is the whole of where the size comes from: no line spacing is declared
    in a configuration, so a column set at any body size gets an initial in
    proportion to the lines it actually stands against.
    """
    missing = _present(*(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES))
    if missing:
        skip("check_01b_the_initial_is_as_tall_as_the_lines_it_stands_against", missing)
        return
    faults = []
    for sample in SAMPLES:
        body = dropcap_evidence(sample)["lane"]
        lines = body["regime_lines"]
        for row in body["paragraphs"]:
            if not row["set"]:
                continue
            expected = lines * row["line_advance"]
            if abs(row["initial_size"] - expected) > EPSILON:
                faults.append(
                    f"{sample} {row['paragraph']}: {row['initial_size']} != "
                    f"{lines} x {row['line_advance']}"
                )
    record(
        "check_01b_the_initial_is_as_tall_as_the_lines_it_stands_against",
        not faults,
        f"{faults[:4]}",
    )


def check_01c_the_lines_beside_it_share_one_reserve() -> None:
    """Every line beside the initial begins at the reserve, and none is missing."""
    missing = _present(*(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES))
    if missing:
        skip("check_01c_the_lines_beside_it_share_one_reserve", missing)
        return
    faults = []
    for sample in SAMPLES:
        body = dropcap_evidence(sample)["lane"]
        lines = body["regime_lines"]
        for row in body["paragraphs"]:
            if not row["set"]:
                continue
            shifts = row["first_line_shifts"]
            if len(shifts) != lines or any(shift is None for shift in shifts):
                faults.append(f"{sample} {row['paragraph']}: shifts={shifts}")
                continue
            if any(abs(shift - row["reserve"]) > EPSILON for shift in shifts):
                faults.append(
                    f"{sample} {row['paragraph']}: shifts={shifts} "
                    f"reserve={row['reserve']}"
                )
    record("check_01c_the_lines_beside_it_share_one_reserve", not faults, f"{faults[:4]}")


def check_01d_the_line_under_it_runs_the_full_measure() -> None:
    """The first line past the initial begins at the paragraph's own left edge."""
    missing = _present(*(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES))
    if missing:
        skip("check_01d_the_line_under_it_runs_the_full_measure", missing)
        return
    faults = []
    for sample in SAMPLES:
        for row in dropcap_evidence(sample)["lane"]["paragraphs"]:
            if not row["set"]:
                continue
            resume = row["resume_shift"]
            if resume is None or abs(resume) > EPSILON:
                faults.append(f"{sample} {row['paragraph']}: resume={resume}")
    record(
        "check_01d_the_line_under_it_runs_the_full_measure", not faults, f"{faults[:4]}"
    )


def check_01e_nothing_was_set_outside_its_own_box() -> None:
    """Every set paragraph's ink stands inside the box it was given."""
    missing = _present(*(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES))
    if missing:
        skip("check_01e_nothing_was_set_outside_its_own_box", missing)
        return
    faults = []
    for sample in SAMPLES:
        body = dropcap_evidence(sample)["lane"]
        slack = body["edge_slack_pt"]
        for row in body["paragraphs"]:
            if not row["set"]:
                continue
            box, reach = row["box"], row["reach"]
            if (
                reach[0] < box[0] - slack
                or reach[1] < box[1] - slack
                or reach[2] > box[2] + slack
                or reach[3] > box[3] + slack
            ):
                faults.append(f"{sample} {row['paragraph']}: reach={reach} box={box}")
    record("check_01e_nothing_was_set_outside_its_own_box", not faults, f"{faults[:4]}")


def check_01f_the_lane_declares_what_it_is_kept_from() -> None:
    """The lane names the pass it is excluded from and the one it runs before."""
    missing = _present(*(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES))
    if missing:
        skip("check_01f_the_lane_declares_what_it_is_kept_from", missing)
        return
    faults = []
    for sample in SAMPLES:
        body = dropcap_evidence(sample)["lane"]
        if body.get("excluded_from") != ["typeset_hang"]:
            faults.append(f"{sample}: excluded_from={body.get('excluded_from')}")
        if body.get("compatible_with") != ["column_reflow"]:
            faults.append(f"{sample}: compatible_with={body.get('compatible_with')}")
    record("check_01f_the_lane_declares_what_it_is_kept_from", not faults, f"{faults}")


def check_01g_no_lane_paragraph_was_re_set_by_the_repair_loop() -> None:
    """The repair loop touched no paragraph the lane had set.

    Prevention would be a filter inside the loop and this is detection instead,
    which is the choice this batch took and registered: a paragraph the loop
    re-typesets loses its initial, and a red gate is what makes that loud rather
    than silent. GAP-48 carries the coded exclusion.
    """
    paths = [sample_dir(s) / "sidecars" / "react_repair.report.json" for s in SAMPLES]
    missing = _present(*paths, *(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES))
    if missing:
        skip("check_01g_no_lane_paragraph_was_re_set_by_the_repair_loop", missing)
        return
    faults = []
    for sample in SAMPLES:
        blob = json.dumps(
            read(sample_dir(sample) / "sidecars" / "react_repair.report.json"),
            ensure_ascii=False,
        )
        mentioned = set(re.findall(r'"(p\d+#\d+)"', blob))
        overlap = sorted(mentioned & set(lane_rows(sample)))
        if overlap:
            faults.append(f"{sample}: {overlap}")
    record(
        "check_01g_no_lane_paragraph_was_re_set_by_the_repair_loop",
        not faults,
        f"{faults}",
    )


# --- 02: the same shape, read off the page ------------------------------------


def check_02a_one_enlarged_glyph_stands_in_each_anchor() -> None:
    """Exactly one span of each anchor is enlarged, and it is the initial."""
    missing = _present(
        *(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES),
        *(sample_dir(s) / "render_evidence.json" for s in SAMPLES),
    )
    if missing:
        skip("check_02a_one_enlarged_glyph_stands_in_each_anchor", missing)
        return
    faults = []
    for sample, anchors in ANCHORS.items():
        rows = lane_rows(sample)
        for reference, glyph in anchors.items():
            large, _ = anchor_spans(sample, reference)
            if len(large) != 1:
                faults.append(f"{sample} {reference}: {len(large)} enlarged spans")
                continue
            span = large[0]
            if span["text"].strip() != glyph:
                faults.append(f"{sample} {reference}: enlarged text {span['text']!r}")
            if abs(span["size"] - rows[reference]["initial_size"]) > 0.05:
                faults.append(
                    f"{sample} {reference}: drawn at {span['size']} and set at "
                    f"{rows[reference]['initial_size']}"
                )
    record(
        "check_02a_one_enlarged_glyph_stands_in_each_anchor", not faults, f"{faults[:4]}"
    )


def check_02b_the_drawn_lines_step_by_one_advance() -> None:
    """Every drawn body line of an anchor stands one advance under the last.

    Which is the negative baseline stated positively: the shape b11.5 recorded
    had a gap of three advances between its first two lines.
    """
    missing = _present(
        *(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES),
        *(sample_dir(s) / "render_evidence.json" for s in SAMPLES),
    )
    if missing:
        skip("check_02b_the_drawn_lines_step_by_one_advance", missing)
        return
    faults = []
    for sample, anchors in ANCHORS.items():
        rows = lane_rows(sample)
        for reference in anchors:
            _, small = anchor_spans(sample, reference)
            advance = rows[reference]["line_advance"]
            lines = body_lines(small, advance)
            steps = [
                round(lines[i + 1][0] - lines[i][0], 3) for i in range(len(lines) - 1)
            ]
            wide = [step for step in steps if step > advance * HOLE_RATIO]
            if wide:
                faults.append(f"{sample} {reference}: gaps {wide} over {advance}")
            if len(lines) < rows[reference]["lines_after"]:
                faults.append(
                    f"{sample} {reference}: {len(lines)} drawn lines and "
                    f"{rows[reference]['lines_after']} set"
                )
    record("check_02b_the_drawn_lines_step_by_one_advance", not faults, f"{faults[:4]}")


def check_02c_the_drawn_reserve_is_the_declared_one() -> None:
    """The first lines start a reserve in and the line after them starts flush."""
    missing = _present(
        *(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES),
        *(sample_dir(s) / "render_evidence.json" for s in SAMPLES),
    )
    if missing:
        skip("check_02c_the_drawn_reserve_is_the_declared_one", missing)
        return
    faults = []
    for sample, anchors in ANCHORS.items():
        rows = lane_rows(sample)
        count = dropcap_evidence(sample)["lane"]["regime_lines"]
        for reference in anchors:
            row = rows[reference]
            _, small = anchor_spans(sample, reference)
            lines = body_lines(small, row["line_advance"])
            if len(lines) <= count:
                faults.append(f"{sample} {reference}: only {len(lines)} drawn lines")
                continue
            beside = [left - row["box"][0] for _top, left, _text in lines[:count]]
            under = lines[count][1] - row["box"][0]
            if any(abs(offset - row["reserve"]) > EDGE_TOLERANCE for offset in beside):
                faults.append(
                    f"{sample} {reference}: beside={[round(v, 2) for v in beside]} "
                    f"reserve={row['reserve']}"
                )
            if abs(under) > EDGE_TOLERANCE:
                faults.append(f"{sample} {reference}: resumes at {round(under, 2)}")
    record("check_02c_the_drawn_reserve_is_the_declared_one", not faults, f"{faults[:4]}")


# --- 03: the negative baseline ------------------------------------------------


def check_03a_no_anchor_shows_the_shape_b11_5_recorded() -> None:
    """No hole and no stranded Latin fragment stands in an anchor.

    The two halves of the shape b11.5 recorded on FD p8#9: a glyph of 39.36
    points where the body is 9.25, with a 27.5 point hole under it, and the
    letters ``hen`` left lying between the two as a run of their own. Both are
    asked about here, on every anchor rather than on the one that showed them.
    """
    missing = _present(
        *(sample_dir(s) / "dropcap_evidence.json" for s in SAMPLES),
        *(sample_dir(s) / "render_evidence.json" for s in SAMPLES),
    )
    if missing:
        skip("check_03a_no_anchor_shows_the_shape_b11_5_recorded", missing)
        return
    faults = []
    for sample, anchors in ANCHORS.items():
        rows = lane_rows(sample)
        for reference in anchors:
            row = rows[reference]
            large, small = anchor_spans(sample, reference)
            # A second enlarged run is the "one towering glyph plus a hole" half.
            if len(large) > 1:
                faults.append(
                    f"{sample} {reference}: {len(large)} enlarged runs: "
                    f"{[s['text'] for s in large]}"
                )
            drawn = body_lines(small, row["line_advance"])
            # The stranded fragment half. What b11.5 recorded was three letters
            # of the first word occupying a line of their own between the
            # initial and the rest of the paragraph, so the test is at the line
            # and not at the span: an inline word of two letters is ordinary and
            # a line of two letters is not. The last line is exempt, because a
            # paragraph is allowed to end wherever its text ends.
            for _top, _left, text in drawn[:-1]:
                stripped = text.strip()
                if len(stripped) <= STRANDED_LINE_CHARS:
                    faults.append(f"{sample} {reference}: stranded line {stripped!r}")
            steps = [
                round(b[0] - a[0], 3)
                for a, b in zip(drawn, drawn[1:], strict=False)
            ]
            if any(step > row["line_advance"] * HOLE_RATIO for step in steps):
                faults.append(f"{sample} {reference}: a hole stands in it")
    record(
        "check_03a_no_anchor_shows_the_shape_b11_5_recorded", not faults, f"{faults[:4]}"
    )


def check_03b_the_detectors_did_not_find_more() -> None:
    """No detector counts more on a sample than it counted before the lane ran."""
    paths = [sample_dir(s) / "sidecars" / "issues.json" for s in BASELINE_SAMPLES]
    prior = [PRIOR_DIR / s / "sidecars" / "issues.json" for s in BASELINE_SAMPLES]
    missing = _present(*paths, *prior)
    if missing:
        skip("check_03b_the_detectors_did_not_find_more", missing)
        return
    faults = []
    for sample in BASELINE_SAMPLES:
        now = read(sample_dir(sample) / "sidecars" / "issues.json")
        before = read(PRIOR_DIR / sample / "sidecars" / "issues.json")
        after = now["counts"]["by_kind"]
        first = before["counts"]["by_kind"]
        for kind in sorted(set(after) | set(first)):
            if after.get(kind, 0) > first.get(kind, 0):
                faults.append(
                    f"{sample} {kind}: {first.get(kind, 0)} -> {after.get(kind, 0)}"
                )
    record("check_03b_the_detectors_did_not_find_more", not faults, f"{faults[:5]}")


# --- 04: the translation path was not touched ---------------------------------


def check_04a_the_request_is_byte_identical_under_either_verdict() -> None:
    """Every anchor was offered the bytes the flatten run offered it."""
    paths = [sample_dir(s) / "request_equivalence.json" for s in BASELINE_SAMPLES]
    missing = _present(*paths)
    if missing:
        skip("check_04a_the_request_is_byte_identical_under_either_verdict", missing)
        return
    faults = []
    for sample in BASELINE_SAMPLES:
        body = read(sample_dir(sample) / "request_equivalence.json")
        for row in body["candidates"]:
            if row["decision"] != lane.kept_verdict():
                faults.append(f"{sample} {row['paragraph']}: ruled {row['decision']!r}")
            if row["baseline_decision"] != drop_cap.DECISION_FLATTEN:
                faults.append(
                    f"{sample} {row['paragraph']}: the baseline ruled "
                    f"{row['baseline_decision']!r}"
                )
            if not row["identical"]:
                faults.append(
                    f"{sample} {row['paragraph']}: {row['offered_sha256']} != "
                    f"{row['baseline_offered_sha256']}"
                )
        if body["totals"]["unresolved"]:
            faults.append(f"{sample}: {body['totals']['unresolved']} unresolved")
    record(
        "check_04a_the_request_is_byte_identical_under_either_verdict",
        not faults,
        f"{faults[:4]}",
    )


def check_04b_the_merge_ran_under_the_kept_verdict() -> None:
    """Every anchor was merged, which is what makes the request the same one."""
    paths = [sample_dir(s) / "sidecars" / "drop_cap_apply.report.json" for s in SAMPLES]
    missing = _present(*paths)
    if missing:
        skip("check_04b_the_merge_ran_under_the_kept_verdict", missing)
        return
    keep = lane.kept_verdict()
    faults = []
    for sample in SAMPLES:  # every sample, whichever way it is translated
        body = read(sample_dir(sample) / "sidecars" / "drop_cap_apply.report.json")
        if body["totals"]["by_decision"].get(drop_cap.DECISION_FLATTEN):
            faults.append(f"{sample}: a paragraph was still ruled flatten")
        if body["totals"]["by_decision"].get(keep) != body["totals"]["decided"]:
            faults.append(f"{sample}: by_decision={body['totals']['by_decision']}")
        for row in body["decisions"]:
            if not row["merged"]:
                faults.append(f"{sample} {row['paragraph']}: not merged")
    record("check_04b_the_merge_ran_under_the_kept_verdict", not faults, f"{faults[:4]}")


def check_04c_no_request_was_paid_for() -> None:
    """The ledger identity holds and this batch sent nothing new."""
    missing = _present(RUNS, COST)
    if missing:
        skip("check_04c_no_request_was_paid_for", missing)
        return
    ledger = read(RUNS)["runs"]
    cost = read(COST)
    faults = []
    for entry in ledger:
        if entry["api_calls"] != entry["requests"] - entry["cache_hits"]:
            faults.append(f"{entry['sample']}: ledger identity broken")
    attributed = sum(
        row["attribution"]["first_run"]
        + row["attribution"]["repair"]
        + row["attribution"]["other_new"]
        for row in cost["runs"]
    )
    if attributed != cost["totals"]["api_calls"]:
        faults.append(
            f"{attributed} attributed and {cost['totals']['api_calls']} sent"
        )
    # The proposition is about the samples that ran before: nothing this batch
    # changed made one of them build a request the cache had no answer for. A
    # sample running for the first time pays for every request it builds, and
    # that is the corpus growing rather than this batch spending.
    for row in cost["runs"]:
        if row["first_run"]:
            continue
        if row["attribution"]["other_new"]:
            faults.append(
                f"{row['sample']}: {row['attribution']['other_new']} unexplained"
            )
    if cost["totals"]["api_calls"] != sum(entry["api_calls"] for entry in ledger):
        faults.append("the attribution and the ledger disagree about the total")
    record("check_04c_no_request_was_paid_for", not faults, f"{faults}")


# --- 05: the fail plain branches ----------------------------------------------


def _stub_paragraph(
    text: str,
    size: float,
    advance: float,
    width: float,
    lines: int,
    depth: int = 0,
):
    """A paragraph of ``lines`` lines of ``text``, laid out as the stage lays one.

    Built rather than read, so the branch under test is exercised whether or not
    the corpus happens to contain a paragraph that would exercise it. ``depth``
    is how many further line advances of room the box has under the last line,
    which is what a real column set short of its box has and what a reserve
    costing one extra line needs.
    """
    characters = []
    per_line = max(1, int(width // size))
    baseline = 700.0
    index = 0
    for line in range(lines):
        for column in range(per_line):
            glyph = text[index % len(text)]
            index += 1
            x = 100.0 + column * size
            y = baseline - line * advance
            characters.append(
                il_version_1.PdfCharacter(
                    char_unicode=glyph,
                    advance=size,
                    box=il_version_1.Box(x=x, y=y, x2=x + size, y2=y + size),
                    pdf_style=il_version_1.PdfStyle(font_id="F1", font_size=size),
                )
            )
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(
            x=100.0,
            y=baseline - (lines - 1 + depth) * advance,
            x2=100.0 + width,
            y2=baseline + size,
        ),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    pdf_character=characters
                )
            )
        ],
        unicode="".join(c.char_unicode for c in characters),
    )


def _set_stub(paragraph, regime_name: str):
    config = lane.load_render_config()
    regime = config.regimes[regime_name]
    base = lane._blank("p1#0", 1, lane.kept_verdict(), "stub", regime.name)
    return lane.set_one(paragraph, regime, config, base)


def check_05a_an_opening_mark_is_never_enlarged() -> None:
    """A paragraph opening on a quotation mark is refused and says so."""
    quoted = _stub_paragraph("\u201c\u4e00\u4e8c\u4e09", 10.0, 15.0, 200.0, 6)
    outcome = _set_stub(quoted, lane.REGIME_SINK)
    record(
        "check_05a_an_opening_mark_is_never_enlarged",
        not outcome["set"]
        and outcome["reverted"]
        and outcome["revert_reason"] == lane.REVERT_NOT_A_LETTER,
        f"set={outcome['set']} reason={outcome['revert_reason']}",
    )


def check_05b_a_column_too_narrow_is_refused() -> None:
    """A column with no readable line left beside the reserve is refused."""
    config = lane.load_render_config()
    regime = config.regimes[lane.REGIME_SINK]
    size = 10.0
    advance = 15.0
    # The reserve alone is the initial plus its gutter; leave under the declared
    # minimum line beside it and the attempt has to be refused.
    width = regime.lines * advance + config.min_line_capacity_em * size - size
    narrow = _stub_paragraph("\u4e00\u4e8c\u4e09\u56db", size, advance, width, 6)
    outcome = _set_stub(narrow, lane.REGIME_SINK)
    record(
        "check_05b_a_column_too_narrow_is_refused",
        not outcome["set"]
        and outcome["revert_reason"] == lane.REVERT_TOO_NARROW,
        f"width={width} set={outcome['set']} reason={outcome['revert_reason']}",
    )


def check_05c_a_paragraph_with_no_line_under_the_initial_is_refused() -> None:
    """A paragraph as short as the initial is tall is refused rather than set."""
    config = lane.load_render_config()
    regime = config.regimes[lane.REGIME_SINK]
    short = _stub_paragraph("\u4e00\u4e8c\u4e09\u56db", 10.0, 15.0, 200.0, regime.lines)
    outcome = _set_stub(short, lane.REGIME_SINK)
    record(
        "check_05c_a_paragraph_with_no_line_under_the_initial_is_refused",
        not outcome["set"] and outcome["revert_reason"] == lane.REVERT_TOO_FEW_LINES,
        f"set={outcome['set']} reason={outcome['revert_reason']}",
    )


def check_05d_a_refusal_puts_the_paragraph_back_exactly() -> None:
    """Nothing a refused attempt touched is left moved.

    The narrow column is refused before anything moves; the one that has to be
    put back is the attempt that lays the whole paragraph out and then finds it
    reaches past its box, so that is the one measured here.
    """
    config = lane.load_render_config()
    regime = config.regimes[lane.REGIME_SINK]
    # Tall enough to be set, and filled to its box, so adding a reserve pushes
    # the last line out of the bottom.
    paragraph = _stub_paragraph("\u4e00\u4e8c\u4e09\u56db", 10.0, 15.0, 120.0, 5)
    before = [
        (c.box.x, c.box.y, c.box.x2, c.box.y2, c.pdf_style.font_size)
        for c in lane.paragraph_characters(paragraph)
    ]
    outcome = lane.set_one(
        paragraph,
        regime,
        config,
        lane._blank("p1#0", 1, lane.kept_verdict(), "stub", regime.name),
    )
    after = [
        (c.box.x, c.box.y, c.box.x2, c.box.y2, c.pdf_style.font_size)
        for c in lane.paragraph_characters(paragraph)
    ]
    if outcome["set"]:
        record(
            "check_05d_a_refusal_puts_the_paragraph_back_exactly",
            False,
            "the stub built to overflow was set instead of refused",
        )
        return
    record(
        "check_05d_a_refusal_puts_the_paragraph_back_exactly",
        before == after and outcome["revert_reason"] == lane.REVERT_WILL_NOT_FIT,
        f"reason={outcome['revert_reason']} moved={before != after}",
    )


def check_05e_the_latin_regime_sets_a_tall_letter() -> None:
    """The other direction, on a stub, under the reading a real page gives.

    The corpus does now carry a Latin regime anchor -- HuaweiTech-zh p4#11 --
    and the 01 and 02 groups read it like any other. This stays because a stub
    asks the rule a question the corpus cannot: it puts a Latin paragraph under
    the regime with nothing else varying, so a pass here is about the rule and
    not about that one page. What the corpus still does not offer is a second
    anchor, which is what GAP-47 now records.
    """
    config = lane.load_render_config()
    regime = config.regimes[lane.REGIME_INITIAL]
    paragraph = _stub_paragraph("Lorem ipsum dolor ", 10.0, 13.0, 220.0, 6, depth=2)
    outcome = _set_stub(paragraph, lane.REGIME_INITIAL)
    faults = []
    if not outcome["set"]:
        faults.append(f"refused: {outcome['revert_reason']}")
    else:
        if abs(outcome["initial_size"] - regime.lines * outcome["line_advance"]) > EPSILON:
            faults.append(f"size={outcome['initial_size']}")
        # The tall letter is measured from its own advance rather than rounded
        # up to the em grid, which is the whole of what the two grids differ
        # over: a reserve on the grid is a whole number of body sizes and this
        # one is not.
        on_grid = outcome["reserve"] % outcome["body_size"]
        if abs(on_grid) < EPSILON or abs(on_grid - outcome["body_size"]) < EPSILON:
            faults.append(f"reserve={outcome['reserve']} was rounded to the grid")
        if any(
            shift is None or abs(shift - outcome["reserve"]) > EPSILON
            for shift in outcome["first_line_shifts"]
        ):
            faults.append(f"shifts={outcome['first_line_shifts']}")
        if outcome["resume_shift"] != 0:
            faults.append(f"resume={outcome['resume_shift']}")
    record("check_05e_the_latin_regime_sets_a_tall_letter", not faults, f"{faults}")


def check_05f_a_word_is_never_broken_in_the_latin_regime() -> None:
    """Under the word rule every drawn line begins on a word edge."""
    paragraph = _stub_paragraph("Lorem ipsum dolor ", 10.0, 13.0, 220.0, 6, depth=2)
    outcome = _set_stub(paragraph, lane.REGIME_INITIAL)
    if not outcome["set"]:
        record(
            "check_05f_a_word_is_never_broken_in_the_latin_regime",
            False,
            f"refused: {outcome['revert_reason']}",
        )
        return
    characters = lane.paragraph_characters(paragraph)
    text = "".join(c.char_unicode or "" for c in characters)
    body = [
        c
        for c in characters
        if abs(float(c.pdf_style.font_size) - outcome["body_size"]) < EPSILON
    ]
    by_line: dict[float, list] = {}
    for character in body:
        by_line.setdefault(round(character.box.y, 2), []).append(character)
    words = {word for word in text.split(" ") if word}
    faults = []
    for baseline in sorted(by_line, reverse=True)[1:]:
        line = sorted(by_line[baseline], key=lambda c: c.box.x)
        opening = "".join(c.char_unicode or "" for c in line).lstrip()
        if not opening:
            continue
        head = opening.split(" ")[0]
        if head not in words:
            faults.append(f"a line opens on {head!r}")
    record("check_05f_a_word_is_never_broken_in_the_latin_regime", not faults, f"{faults}")


# --- 06: the ruling and its pins ----------------------------------------------


def check_06a_no_ruling_still_carries_the_other_verdict() -> None:
    """Every drop cap ruling on file names the kept verdict."""
    keep = lane.kept_verdict()
    register = (
        evidence.read_bytes(GAP_REGISTER).decode("utf-8")
        if evidence.exists(GAP_REGISTER)
        else ""
    )
    faults = []
    for path in sorted((ROOT / "reviews").glob("*.decisions.json")):
        with path.open(encoding="utf-8") as f:
            body = json.load(f)
        section = body.get("drop_caps")
        if section is None or isinstance(section, dict):
            for reference, verdict in (section or {}).items():
                if verdict != keep:
                    faults.append(f"{path.name} {reference}={verdict}")
            continue
        # A ruling in a shape the review loader rejects reaches no run at all.
        # It belongs to the corpus owner and this batch does not rewrite it, so
        # what the gate can hold is that the batch said so rather than let the
        # file look applied. GAP-51.
        if path.name not in register:
            faults.append(f"{path.name} is unloadable and is not registered")
    record("check_06a_no_ruling_still_carries_the_other_verdict", not faults, f"{faults}")


def check_06b_the_rulings_are_pinned_at_what_they_now_carry() -> None:
    """Each pinned ruling matches the file, and the re-pin is written down."""
    import hashlib

    text = (ROOT / "spec_checks" / "spec_check_b7_5.py").read_text(encoding="utf-8")
    faults = []
    repinned = []
    for relative, pinned in spec_check_b7_5.TRUTH_DIGESTS.items():
        path = ROOT / relative
        if not path.is_file():
            faults.append(f"{relative} is not on disk")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != pinned:
            faults.append(f"{relative}: {actual} != {pinned}")
    for relative in REPINNED:
        if relative not in spec_check_b7_5.TRUTH_DIGESTS:
            faults.append(f"{relative} is not pinned at all")
            continue
        window = text[max(0, text.find(relative) - 3200) : text.find(relative)]
        if BATCH_TAG not in window:
            faults.append(f"{relative}: the pin carries no {BATCH_TAG} note")
        repinned.append(relative)
    record(
        "check_06b_the_rulings_are_pinned_at_what_they_now_carry",
        not faults,
        f"{faults[:4]}",
    )


def check_06c_the_defaults_declare_the_kept_verdict() -> None:
    """Both declared target languages default to the kept verdict."""
    config = drop_cap.load_drop_cap_config()
    keep = lane.kept_verdict()
    faults = [
        f"{tag}={verdict}"
        for tag, verdict in config.defaults.items()
        if verdict != keep
    ]
    record("check_06c_the_defaults_declare_the_kept_verdict", not faults, f"{faults}")


def check_06d_the_vocabulary_did_not_grow() -> None:
    """No verdict was added: the redefinition is of a word, not a new word."""
    verdicts = drop_cap.decision_vocabulary()
    record(
        "check_06d_the_vocabulary_did_not_grow",
        tuple(verdicts) == ("keep", "flatten"),
        f"vocabulary={list(verdicts)}",
    )


def check_06e_the_render_regimes_are_declared_not_coded() -> None:
    """The two regimes and the language table are read from the configuration."""
    config = lane.load_render_config()
    source = (ROOT / "babeldoc" / "magazine" / "drop_cap_render.py").read_text(
        encoding="utf-8"
    )
    faults = []
    if sorted(config.regimes) != ["initial", "sink"]:
        faults.append(f"regimes={sorted(config.regimes)}")
    if sorted(config.by_target) != ["en", "zh"]:
        faults.append(f"targets={sorted(config.by_target)}")
    for regime in config.regimes.values():
        if regime.lines < 2 or regime.lines > 3:
            faults.append(f"{regime.name}: {regime.lines} lines")
    # No number the shape depends on may stand as a literal in the module.
    for literal in ("1.5", "2.0", "0.25", "13.8", "9.2"):
        if re.search(rf"=\s*{re.escape(literal)}\b", source):
            faults.append(f"the module carries the literal {literal}")
    record(
        "check_06e_the_render_regimes_are_declared_not_coded", not faults, f"{faults}"
    )


# --- 07: the two static classes, now cheap ------------------------------------


def cjk_offences(named_sources) -> list[str]:
    """Every line of the given sources carrying a Chinese character.

    The rule b0's 09 and b1's 09d apply to a full sweep, applied here to text
    handed in, so it costs a read rather than a pipeline run and so that this
    gate can prove the rule fires by handing it a line that breaks it.
    """
    return [
        f"{name}:{number}"
        for name, text in named_sources
        for number, line in enumerate(text.splitlines(), start=1)
        if spec_check_b0.has_cjk(line)
    ]


def pipeline_import_offences(named_sources) -> list[str]:
    """Every import of the translation pipeline in the given sources.

    The rule b5's 08e applies to the two chain modules, applied here the same
    way and for the same reason.
    """
    return [
        f"{name}: {line.strip()}"
        for name, text in named_sources
        for line in text.splitlines()
        if line.startswith(("import ", "from "))
        and "babeldoc" in line
        and "babeldoc.magazine" not in line
    ]


def _added_python_lines() -> list[tuple[str, str]]:
    """This batch's added lines, as one text per file it added them to."""
    span = _diff_span()
    out = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
        ["git", "diff", "--unified=0", *span, "--", "*.py"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    by_file: dict[str, list[str]] = {}
    current = None
    for line in out.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and current:
            by_file.setdefault(current, []).append(line[1:])
    if span == ["HEAD"]:
        untracked = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
            ["git", "ls-files", "--others", "--exclude-standard", "--", "*.py"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        for name in untracked.stdout.split():
            path = ROOT / name
            if path.is_file():
                by_file.setdefault(name, []).extend(
                    path.read_text(encoding="utf-8").splitlines()
                )
    return [(name, "\n".join(lines)) for name, lines in sorted(by_file.items())]


def check_07a_this_batch_added_no_chinese_to_the_code() -> None:
    """The sweep only class, checked without a sweep."""
    offences = cjk_offences(_added_python_lines())
    record(
        "check_07a_this_batch_added_no_chinese_to_the_code",
        not offences,
        f"{offences[:5]}",
    )


def check_07b_the_chain_modules_still_import_nothing_upstream() -> None:
    """The other sweep only class, checked without a sweep."""
    sources = [
        (name, (ROOT / name).read_text(encoding="utf-8"))
        for name in (spec_check_b5.MODULE, spec_check_b5.STAGE_MODULE)
    ]
    offences = pipeline_import_offences(sources)
    record(
        "check_07b_the_chain_modules_still_import_nothing_upstream",
        not offences,
        f"{offences[:5]}",
    )


def check_07c_both_cheap_checks_fire_on_a_stub() -> None:
    """Each rule goes red once on text built to break it.

    A check that has never failed is a check nobody has reason to believe. The
    Chinese character below is written as an escape so this file stays ASCII.
    """
    dirty = [("stub.py", 'LABEL = "\u4e2d\u6587"  # a Chinese string literal')]
    clean = [("stub.py", 'LABEL = "plain ascii"')]
    impure = [("stub.py", "from babeldoc.format.pdf import high_level")]
    pure = [("stub.py", "from babeldoc.magazine import drop_cap")]
    faults = []
    if not cjk_offences(dirty):
        faults.append("the Chinese rule passed a line that breaks it")
    if cjk_offences(clean):
        faults.append("the Chinese rule failed a line that keeps it")
    if not pipeline_import_offences(impure):
        faults.append("the purity rule passed an import that breaks it")
    if pipeline_import_offences(pure):
        faults.append("the purity rule failed an import that keeps it")
    record("check_07c_both_cheap_checks_fire_on_a_stub", not faults, f"{faults}")


def check_07d_the_sweep_debt_is_carried_forward() -> None:
    """W-B11-23 names the batch that owes the sweep, and it is not this one."""
    missing = _present(WAIVERS)
    if missing:
        skip("check_07d_the_sweep_debt_is_carried_forward", missing)
        return
    text = evidence.read_bytes(WAIVERS).decode("utf-8")
    line = next((row for row in text.splitlines() if "W-B11-23" in row), "")
    faults = []
    if not line:
        faults.append("W-B11-23 is not on file")
    else:
        # The revision marker, the batch the debt moved to, and the one
        # instruction the revision had to carry forward rather than drop.
        # The batch name is written as escapes so this file stays ASCII;
        # it reads "the performance batch".
        performance_batch = '\u6027\u80fd\u6279'
        for token, complaint in (
            ("revised@b11.8", "the waiver carries no revision marker"),
            (performance_batch, "the waiver does not name the batch the debt moved to"),
            ("b2_1", "the waiver dropped the b2_1 instruction"),
        ):
            if token not in line:
                faults.append(complaint)
    record("check_07d_the_sweep_debt_is_carried_forward", not faults, f"{faults}")


# --- 07e/07f: the one upstream change, and its blast radius -------------------


def check_07e_the_two_writers_agree_about_a_deferred_field() -> None:
    """The same deferred instruction, written both ways, reads back the same.

    The schema declares the field a string and the frontend sometimes fills it
    with a wrapper that renders that string on demand. The JSON writer asked for
    it and the XML writer did not, so a document holding one could be written as
    JSON and not as XML -- and the checkpoint is XML. This asserts the symmetry
    itself rather than a proxy for it: the materialised bytes, out of one writer
    and out of the other, are the same bytes.
    """
    missing = _present(SYMMETRY)
    if missing:
        skip("check_07e_the_two_writers_agree_about_a_deferred_field", missing)
        return
    body = read(SYMMETRY)["lazy"]
    faults = []
    if not body["identical"]:
        faults.append(
            f"json={body['from_json']!r} xml={body['from_xml']!r} "
            f"materialized={body['materialized']!r}"
        )
    if not body["materialized"]:
        faults.append("the wrapper materialised to nothing, so nothing was compared")
    record(
        "check_07e_the_two_writers_agree_about_a_deferred_field",
        not faults,
        f"{faults}",
    )


def check_07f_a_document_without_one_renders_as_it_did() -> None:
    """Negative: the change reaches only the documents it is about.

    A stub carrying no deferred field was rendered to XML before the converter
    was registered and again after, and the two are compared byte for byte. A
    difference would mean a serialiser change that had reached documents it had
    no business reaching.
    """
    missing = _present(SYMMETRY)
    if missing:
        skip("check_07f_a_document_without_one_renders_as_it_did", missing)
        return
    body = read(SYMMETRY)
    faults = []
    before = (body.get("plain") or {}).get("sha256")
    after = (body.get("plain_after") or {}).get("sha256")
    if not before:
        faults.append("no rendering was frozen before the change")
    if before and after and before != after:
        faults.append(f"the plain rendering moved: {before} -> {after}")
    if not body.get("plain_unchanged"):
        faults.append("the record does not report the rendering unchanged")
    record(
        "check_07f_a_document_without_one_renders_as_it_did", not faults, f"{faults}"
    )


# --- 08: conservation ---------------------------------------------------------


def check_08a_the_pages_and_paragraphs_are_the_same_ones() -> None:
    """Every page keeps its paragraph count and every paragraph its text."""
    paths = [sample_dir(s) / "conservation.json" for s in BASELINE_SAMPLES]
    missing = _present(*paths)
    if missing:
        skip("check_08a_the_pages_and_paragraphs_are_the_same_ones", missing)
        return
    faults = []
    for sample in BASELINE_SAMPLES:
        body = read(sample_dir(sample) / "conservation.json")
        if body["baseline_pages"] != body["pages"]:
            faults.append(
                f"{sample}: {body['pages']} pages against {body['baseline_pages']}"
            )
        for label, page in sorted(body["per_page"].items()):
            if page["paragraphs"] != page.get("baseline_paragraphs"):
                faults.append(
                    f"{sample} p{label}: {page['paragraphs']} paragraphs against "
                    f"{page.get('baseline_paragraphs')}"
                )
            moved = [
                reference
                for reference, text in page["text"].items()
                if page.get("baseline_text", {}).get(reference) != text
            ]
            if moved:
                faults.append(f"{sample} p{label}: text changed at {moved[:3]}")
    record(
        "check_08a_the_pages_and_paragraphs_are_the_same_ones", not faults, f"{faults[:4]}"
    )


def check_08b_the_reflow_saw_the_finished_shape() -> None:
    """The column reflow ran after the lane and reverted no page.

    Which is what "compatible with" means here: the lane leaves the paragraph
    inside the box the reflow measures from, and the reflow measures the ink the
    lane left rather than the ink that was there before it.
    """
    paths = [sample_dir(s) / "sidecars" / "column_reflow.report.json" for s in SAMPLES]
    missing = _present(*paths)
    if missing:
        skip("check_08b_the_reflow_saw_the_finished_shape", missing)
        return
    faults = []
    for sample in SAMPLES:
        body = read(sample_dir(sample) / "sidecars" / "column_reflow.report.json")
        if body["totals"]["pages_reverted"]:
            faults.append(f"{sample}: {body['totals']['pages_reverted']} pages reverted")
    record("check_08b_the_reflow_saw_the_finished_shape", not faults, f"{faults}")


# --- 09: scope ----------------------------------------------------------------


def _diff_span() -> list[str]:
    exists = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
        ["git", "rev-parse", "--verify", "--quiet", f"{BATCH_TAG}^{{commit}}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if exists.returncode == 0:
        return [f"{BATCH_TAG}^..{BATCH_TAG}"]
    return ["HEAD"]


def _changed_files() -> list[str]:
    """The files this batch changed, anchored to its tag where the tag exists."""
    span = _diff_span()
    out = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
        ["git", "diff", "--name-only", *span],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    names = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    if span == ["HEAD"]:
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
    "reviews/",
    # Ground truth the corpus owner wrote during this batch and this batch did
    # not: two Chinese source samples were registered while the lane was being
    # built. Named file by file rather than as the whole directory, so that a
    # third truth file appearing in a diff is still a finding. W-B11-26.
    "corpus/page_labels.json",
    "corpus/registry.user.json",
    # Rebuilt from the registry by tools/corpus_sync.py, which is what a
    # manifest is: the machine's copy of what the owner declared, with the
    # hashes and page counts measured off the sample files.
    "corpus/manifest.json",
    "corpus/chain_labels.user.json",
    "docs/reports/assertion_contracts.md",
    "corpus/page_labels.CHANGELOG.md",
    "docs/eval/gap_register.md",
    "docs/reports/assertion_contracts.md",
    "WAIVERS.md",
    "UPSTREAM_DIFF.md",
    "plans/",
    "examples/output/b11_8/",
)

# The one upstream file this batch touches, with the reason it had to be.
ALLOWED_UPSTREAM = {
    "babeldoc/format/pdf/high_level.py": (
        "the render lane runs after typesetting and before detection, and the "
        "pipeline has no other window at that point"
    ),
    "babeldoc/format/pdf/document_il/xml_converter.py": (
        "the XML writer had no answer for a deferred passthrough instruction "
        "that the JSON writer beside it already materialises, so a document "
        "holding one could be written one way and not the other"
    ),
}


def check_09a_the_delta_is_the_declared_surface() -> None:
    """Nothing outside the declared surface changed."""
    faults = [
        name
        for name in _changed_files()
        if name not in ALLOWED_UPSTREAM
        and not any(name.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    ]
    record("check_09a_the_delta_is_the_declared_surface", not faults, f"{faults[:5]}")


def check_09b_the_upstream_touch_is_registered() -> None:
    """The upstream file this batch changed has a line in the register."""
    missing = _present(UPSTREAM_DIFF)
    if missing:
        skip("check_09b_the_upstream_touch_is_registered", missing)
        return
    text = evidence.read_bytes(UPSTREAM_DIFF).decode("utf-8")
    touched = [name for name in _changed_files() if name in ALLOWED_UPSTREAM]
    faults = []
    for name in touched:
        if name not in text:
            faults.append(f"{name} is not registered")
    if touched and BATCH_TAG.lower() not in text.lower():
        faults.append("the register carries no line for this batch")
    record("check_09b_the_upstream_touch_is_registered", not faults, f"{faults}")


def check_09c_the_prompts_were_not_touched() -> None:
    """No prompt changed: this batch never reaches a prompt."""
    faults = [name for name in _changed_files() if name.startswith("prompts/")]
    record("check_09c_the_prompts_were_not_touched", not faults, f"{faults}")


def check_09d_the_ruling_files_were_not_written_by_this_batch() -> None:
    """The rulings this batch reads are the owner's, unchanged by the machine.

    The corpus owner rewrote the four verdicts before this batch began, which is
    premise 1 and is recorded in premise_check.json. What this batch does to
    those files is re-pin their digests, and nothing else.
    """
    missing = _present(PREMISE)
    if missing:
        skip("check_09d_the_ruling_files_were_not_written_by_this_batch", missing)
        return
    body = read(PREMISE)["premises"]["1_vocabulary_and_rulings"]
    faults = []
    if body["non_keep_verdicts_remaining"]:
        faults.append(f"still ruled otherwise: {body['non_keep_verdicts_remaining']}")
    if not body.get("difference"):
        faults.append("the premise records no note about who wrote the rulings")
    for name, entry in body["rulings"].items():
        if entry["crlf_bytes"]:
            faults.append(f"{name}: {entry['crlf_bytes']} CRLF line endings")
    record(
        "check_09d_the_ruling_files_were_not_written_by_this_batch",
        not faults,
        f"{faults}",
    )


def check_09e_the_gate_names_no_run_local_identifier() -> None:
    """No assertion of this gate anchors on a debug id."""
    text = Path(__file__).read_text(encoding="utf-8")
    # Assembled rather than spelled, so that this assertion does not find
    # itself: a gate that names the thing it forbids would fail on its own
    # source and never on anyone's.
    attribute = "debug" + "_id"
    serialised = "debug" + "Id"
    faults = []
    if re.search(attribute + r'\s*[=:]\s*["\']', text):
        faults.append("a debug id is compared against a literal")
    if serialised in text:
        faults.append("the serialised debug id name appears")
    record("check_09e_the_gate_names_no_run_local_identifier", not faults, f"{faults}")


def check_09f_the_evidence_this_gate_reads_is_declared() -> None:
    """Every path this gate reads is named in GATE_EVIDENCE and exists."""
    missing = [name for name in GATE_EVIDENCE if not evidence.exists(ROOT / name)]
    record(
        "check_09f_the_evidence_this_gate_reads_is_declared",
        not missing,
        f"absent: {missing[:5]}",
    )


def check_09g_the_premises_were_checked_before_anything_was_built() -> None:
    """The premise record exists, holds, and names the two differences."""
    missing = _present(PREMISE)
    if missing:
        skip("check_09g_the_premises_were_checked_before_anything_was_built", missing)
        return
    body = read(PREMISE)
    faults = []
    if not body["all_hold"]:
        faults.append(
            [name for name, row in body["premises"].items() if not row["holds"]]
        )
    if sorted(body["differences"]) != [
        "1_vocabulary_and_rulings",
        "4_candidate_enumeration",
    ]:
        faults.append(f"differences={body['differences']}")
    record(
        "check_09g_the_premises_were_checked_before_anything_was_built",
        not faults,
        f"{faults}",
    )


def check_09h_the_open_gaps_are_registered() -> None:
    """Both gaps this batch leaves are in the register."""
    missing = _present(GAP_REGISTER)
    if missing:
        skip("check_09h_the_open_gaps_are_registered", missing)
        return
    text = evidence.read_bytes(GAP_REGISTER).decode("utf-8")
    faults = [name for name in GAPS if name not in text]
    record("check_09h_the_open_gaps_are_registered", not faults, f"missing {faults}")


def check_09i_the_fast_sweep_is_recorded_green() -> None:
    """The fast set ran and every gate in it passed."""
    missing = _present(SWEEP)
    if missing:
        skip("check_09i_the_fast_sweep_is_recorded_green", missing)
        return
    body = read(SWEEP)
    faults = []
    if body["exit_code"] != 0:
        faults.append(f"exit={body['exit_code']}")
    if body["failing"]:
        faults.append(f"failing={body['failing']}")
    if body["missing"]:
        faults.append(f"missing={body['missing']}")
    if body["gates_run"] != body["gates_declared"]:
        faults.append(f"{body['gates_run']} of {body['gates_declared']} ran")
    record("check_09i_the_fast_sweep_is_recorded_green", not faults, f"{faults}")


CHECKS = (
    check_01a_every_anchor_was_set,
    check_01b_the_initial_is_as_tall_as_the_lines_it_stands_against,
    check_01c_the_lines_beside_it_share_one_reserve,
    check_01d_the_line_under_it_runs_the_full_measure,
    check_01e_nothing_was_set_outside_its_own_box,
    check_01f_the_lane_declares_what_it_is_kept_from,
    check_01g_no_lane_paragraph_was_re_set_by_the_repair_loop,
    check_02a_one_enlarged_glyph_stands_in_each_anchor,
    check_02b_the_drawn_lines_step_by_one_advance,
    check_02c_the_drawn_reserve_is_the_declared_one,
    check_03a_no_anchor_shows_the_shape_b11_5_recorded,
    check_03b_the_detectors_did_not_find_more,
    check_04a_the_request_is_byte_identical_under_either_verdict,
    check_04b_the_merge_ran_under_the_kept_verdict,
    check_04c_no_request_was_paid_for,
    check_05a_an_opening_mark_is_never_enlarged,
    check_05b_a_column_too_narrow_is_refused,
    check_05c_a_paragraph_with_no_line_under_the_initial_is_refused,
    check_05d_a_refusal_puts_the_paragraph_back_exactly,
    check_05e_the_latin_regime_sets_a_tall_letter,
    check_05f_a_word_is_never_broken_in_the_latin_regime,
    check_06a_no_ruling_still_carries_the_other_verdict,
    check_06b_the_rulings_are_pinned_at_what_they_now_carry,
    check_06c_the_defaults_declare_the_kept_verdict,
    check_06d_the_vocabulary_did_not_grow,
    check_06e_the_render_regimes_are_declared_not_coded,
    check_07a_this_batch_added_no_chinese_to_the_code,
    check_07b_the_chain_modules_still_import_nothing_upstream,
    check_07c_both_cheap_checks_fire_on_a_stub,
    check_07d_the_sweep_debt_is_carried_forward,
    check_07e_the_two_writers_agree_about_a_deferred_field,
    check_07f_a_document_without_one_renders_as_it_did,
    check_08a_the_pages_and_paragraphs_are_the_same_ones,
    check_08b_the_reflow_saw_the_finished_shape,
    check_09a_the_delta_is_the_declared_surface,
    check_09b_the_upstream_touch_is_registered,
    check_09c_the_prompts_were_not_touched,
    check_09d_the_ruling_files_were_not_written_by_this_batch,
    check_09e_the_gate_names_no_run_local_identifier,
    check_09f_the_evidence_this_gate_reads_is_declared,
    check_09g_the_premises_were_checked_before_anything_was_built,
    check_09h_the_open_gaps_are_registered,
    check_09i_the_fast_sweep_is_recorded_green,
)


def main() -> int:
    print("spec_check_b11_8: keep redefined, the opening set both ways\n")
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
