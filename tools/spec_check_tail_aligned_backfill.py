"""Gate: a paragraph the layout broke is cut at the last full line, not at capacity.

The claim under test is that a body chain hands its continuation a whole line's
worth of text rather than the remainder of a part line. This script asserts both
halves of that: the rule that places the cut holds on its own, with no PDF and
no typesetter in sight, and a real measured allocation over the fixed width
fixture moves the cut where the rule says, conserves the translation, and falls
to the capacity level rather than failing when the move overruns the next box.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import Box  # noqa: E402
from babeldoc.format.pdf.document_il import PdfStyle  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting  # noqa: E402
from babeldoc.magazine import chain_backfill as backfill  # noqa: E402
from babeldoc.magazine.article_context import EMPTY_CONTEXT  # noqa: E402
from babeldoc.magazine.chain_translation import plan_chain_translation  # noqa: E402
from tests.minimal.fakes import FixedWidthMapper  # noqa: E402
from tests.minimal.fakes import RecordingTracker  # noqa: E402
from tests.minimal.fakes import document_digest  # noqa: E402
from tests.minimal.fakes import make_chain_fixture  # noqa: E402

# The fixed width fixture's geometry.  The fake font makes a character half its
# size wide, and the planner measures at the smallest readable application
# scale, so a fifty point column takes twenty characters to the line and its
# height decides how many lines there are.  The right hand column is given one
# line in the case that has to overrun it.
TALL_LEFT = (0.0, 0.0, 50.0, 70.0)
TALL_RIGHT = (60.0, 0.0, 110.0, 70.0)
ONE_LINE_RIGHT = (60.0, 0.0, 110.0, 10.0)


class CheckError(AssertionError):
    """Raised when one assertion of this gate does not hold."""


def require(condition: object, detail: str) -> None:
    if not condition:
        raise CheckError(detail)


# --- symbol level: the rule, with no box anywhere near it --------------------

LINE_ENDS = (10, 22, 34, 46)


def s1_estimate_retreats_to_the_last_full_line() -> str:
    position, reason = backfill.tail_aligned_cut(40, LINE_ENDS, 1, 60, 1)
    require(
        (position, reason) == (34, backfill.TAIL_ALIGN_MOVED),
        f"an estimate at 40 over {LINE_ENDS} gave {(position, reason)}, not (34, moved)",
    )
    return f"40 -> {position} ({reason})"


def s2_an_estimate_already_at_a_line_end_stands() -> str:
    position, reason = backfill.tail_aligned_cut(34, LINE_ENDS, 1, 60, 1)
    require(
        (position, reason) == (34, backfill.TAIL_ALIGN_ALREADY_FULL),
        f"an estimate at 34 gave {(position, reason)}, not (34, already_full)",
    )
    return f"34 -> {position} ({reason})"


def s3_an_estimate_inside_the_first_line_stands() -> str:
    low = 1
    position, reason = backfill.tail_aligned_cut(6, LINE_ENDS, low, 60, 1)
    require(
        (position, reason) == (6, backfill.TAIL_ALIGN_MIN_LINES),
        f"an estimate at 6 gave {(position, reason)}, not (6, min_lines)",
    )
    require(position >= low, f"the cut at {position} fell below the low bound {low}")
    return f"6 -> {position} ({reason}), not below {low}"


def s4_no_measured_line_leaves_the_estimate() -> str:
    position, reason = backfill.tail_aligned_cut(6, (), 1, 60, 1)
    require(
        (position, reason) == (6, backfill.TAIL_ALIGN_NO_LINE_END),
        f"an unmeasured box gave {(position, reason)}, not (6, no_line_end)",
    )
    return f"6 -> {position} ({reason})"


def s5_unmeasured_cuts_report_the_fallback() -> str:
    config = backfill.load_backfill_config()
    merge = backfill.merge_chain_text(["源" * 6, "源" * 4], config)
    result = backfill.redistribute(
        merge,
        "译" * 40,
        "zh",
        backfill.STRATEGY_TAIL_ALIGNED,
        config,
        aligned_lengths=None,
        align_enabled=False,
        cut_positions=None,
    )
    require(
        result.fallback == backfill.FALLBACK_NO_LINE_ENDS,
        f"the fallback was {result.fallback!r}, not {backfill.FALLBACK_NO_LINE_ENDS!r}",
    )
    require(
        "".join(segment.text for segment in result.segments) == "译" * 40,
        "the share fallback did not conserve the translation",
    )
    return f"fallback={result.fallback}, pieces conserved"


def _config_variant(root: Path, name: str, mutate: Callable[[dict], None]) -> Path:
    raw = json.loads(backfill.CONFIG_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    path = root / name
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _refused(path: Path) -> str:
    try:
        backfill.load_backfill_config(str(path))
    except backfill.BackfillConfigError as error:
        return str(error)
    raise CheckError(f"{path.name} was accepted; it should have been refused")


def s6_an_unimplemented_cascade_level_is_refused(root: Path) -> str:
    path = _config_variant(
        root,
        "cascade-unimplemented.json",
        lambda raw: raw["strategies"].__setitem__(
            "slot_cascade", ["tail_aligned", "no_such_strategy"]
        ),
    )
    detail = _refused(path)
    require(
        "no_such_strategy" in detail,
        f"the refusal did not name the offending level: {detail}",
    )
    return detail.split(";")[0]


def s7_an_out_of_range_bound_is_refused(root: Path) -> str:
    path = _config_variant(
        root,
        "tail-align-out-of-range.json",
        lambda raw: raw["tail_align"].__setitem__("min_kept_lines", 9),
    )
    detail = _refused(path)
    require(
        "min_kept_lines" in detail,
        f"the refusal did not name the offending bound: {detail}",
    )
    return detail


# --- run level: the same rule, over the real measured allocation -------------


def _consumed_in_lines(text: str, box, lines: int, font_size: float) -> int:
    """What the real packer takes from ``text`` when only ``lines`` are allowed.

    Measured here from the same font size the allocation recorded, so the gate
    reads the box the planner read without repeating how the planner chose the
    scale it read it at.
    """
    typesetter = Typesetting(
        type("Config", (), {"lang_out": "zh"})(), font_mapper=FixedWidthMapper()
    )

    def fit(bottom: float):
        return typesetter.fit_text_to_slot(
            text,
            PdfStyle(font_id="body", font_size=float(font_size)),
            "zh",
            Box(box[0], bottom, box[2], box[3]),
            paragraph_start=False,
            minimum_font_size=4.0,
            fit_tolerance=0.01,
            line_skip=1.5,
        )

    whole = fit(box[1])
    return fit(whole.line_metrics[lines - 1].bounds[1] - 0.01).consumed_range[1]


def _plan(target: str, work: Path, boxes, sources):
    document, article_ir, paragraphs, translator = make_chain_fixture(
        target, work, boxes=boxes, sources=sources
    )
    before = document_digest(document)
    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )
    require(
        document_digest(document) == before,
        "planning mutated the document before it was applied",
    )
    return plan, document, paragraphs, translator


def _moved_fixture(work: Path):
    """Two equal boxes and unequal sources, so the share lands inside a line."""
    return _plan(
        "译" * 40,
        work,
        boxes=(TALL_LEFT, TALL_RIGHT),
        sources=("源" * 6, "源" * 4),
    )


def e1_the_cut_moves_back_to_a_measured_line_end(work: Path) -> str:
    plan, _document, _paragraphs, _translator = _moved_fixture(work / "e1")
    require(len(plan.entries) == 1, f"{len(plan.entries)} chains were planned, not 1")
    allocation = plan.entries[0].allocation
    require(
        allocation.strategy == backfill.STRATEGY_TAIL_ALIGNED,
        f"the chain was cut by {allocation.strategy!r}, not tail_aligned",
    )
    first = allocation.fragments[0]
    require(
        first.tail_align is not None
        and first.tail_align["reason"] == backfill.TAIL_ALIGN_MOVED,
        f"the first cut recorded {first.tail_align}, not a move",
    )
    kept = first.tail_align["kept_lines"]
    # B14: the cut probes read the full-size grid (tail_align.cut_scale),
    # while the fragment's own measurement record keeps the capacity scale.
    # The expected count is therefore measured at the size the cut was chosen
    # on, recovered from the recorded pair rather than recomputed here.
    cut_size = (
        first.measurement_record["measurement_font_size"]
        / first.measurement_record["measurement_scale"]
    ) * first.tail_align.get("cut_scale", 1.0)
    expected = _consumed_in_lines(
        "译" * 40,
        TALL_LEFT,
        kept,
        cut_size,
    )
    require(
        len(first.text) == expected,
        f"the first member took {len(first.text)} characters, not the "
        f"{expected} the packer puts on {kept} lines",
    )
    require(
        first.tail_align["ideal"] > len(first.text),
        "the cut did not move earlier than the share that proposed it",
    )
    return (
        f"{first.tail_align['ideal']} -> {len(first.text)} chars on {kept} lines, "
        f"{first.tail_align['moved_chars']} moved on"
    )


def e2_the_moved_cut_conserves_the_translation(work: Path) -> str:
    target = "译" * 40
    plan, _document, paragraphs, translator = _moved_fixture(work / "e2")
    allocation = plan.entries[0].allocation
    joined = "".join(fragment.text for fragment in allocation.fragments)
    require(joined == target, "the fragments do not join back to the translation")
    require(
        all(fragment.text for fragment in allocation.fragments),
        "a member was given no text at all",
    )
    plan.apply()
    require(
        "".join(paragraph.unicode for paragraph in paragraphs) == target,
        "what was written back does not join to the translation",
    )
    require(
        len(translator.il_translator.posted) == len(paragraphs),
        "not every member was written back",
    )
    return f"{len(allocation.fragments)} pieces join to {len(target)} characters"


def e3_an_overrun_next_box_falls_to_capacity(work: Path) -> str:
    target = "译" * 45
    plan, document, paragraphs, translator = _plan(
        target,
        work / "e3",
        boxes=(TALL_LEFT, ONE_LINE_RIGHT),
        sources=("源" * 6, "源" * 4),
    )
    require(len(plan.entries) == 1, f"{len(plan.entries)} chains were planned, not 1")
    entry = plan.entries[0]
    record = entry.as_record()
    require(
        record["redistribution"]["strategy"] == backfill.STRATEGY_CAPACITY,
        f"the sidecar says {record['redistribution']['strategy']!r}, not capacity",
    )
    require(
        entry.strategy == backfill.STRATEGY_CAPACITY,
        f"the entry says {entry.strategy!r}, not capacity",
    )
    require(
        record["cut_displacement"] == [],
        f"a capacity cut recorded a displacement: {record['cut_displacement']}",
    )
    require(
        all(fragment.tail_align is None for fragment in entry.allocation.fragments),
        "a capacity plan carried a tail alignment",
    )
    require(
        "".join(fragment.text for fragment in entry.allocation.fragments) == target,
        "the capacity fallback did not conserve the translation",
    )
    require(
        not translator.il_translator.posted
        and all(
            paragraph.unicode.startswith("源") for paragraph in paragraphs
        ),
        "the abandoned tail aligned level wrote part of itself back",
    )
    plan.apply()
    require(
        "".join(paragraph.unicode for paragraph in paragraphs) == target,
        "the capacity fallback wrote back something other than the translation",
    )
    return (
        f"tail_aligned refused, capacity placed "
        f"{[len(f.text) for f in entry.allocation.fragments]}"
    )


def e4_the_last_member_is_never_pulled_back(work: Path) -> str:
    plan, _document, _paragraphs, _translator = _plan(
        "译" * 40,
        work / "e4",
        boxes=(TALL_LEFT, TALL_RIGHT, TALL_LEFT),
        sources=("源" * 5, "源" * 3, "源" * 2),
    )
    require(len(plan.entries) == 1, f"{len(plan.entries)} chains were planned, not 1")
    entry = plan.entries[0]
    count = len(entry.allocation.fragments)
    displacement = entry.as_record()["cut_displacement"]
    require(displacement, "no interior cut was recorded at all")
    highest = max(row["index"] for row in displacement)
    require(
        highest <= count - 2,
        f"a displacement was recorded for member {highest} of {count}",
    )
    require(
        entry.allocation.fragments[-1].tail_align is None,
        "the last member carried a tail alignment",
    )
    reasons = {row["reason"] for row in displacement}
    require(
        reasons <= set(backfill.TAIL_ALIGN_REASONS),
        f"a displacement carried an undeclared reason: {reasons}",
    )
    return f"{len(displacement)} cuts over {count} members, highest index {highest}"


def e5_the_capacity_only_cascade_still_runs(work: Path) -> str:
    """The configuration this change replaced must remain a working one."""
    root = work / "e5-config"
    root.mkdir(parents=True, exist_ok=True)
    path = _config_variant(
        root,
        "capacity-only.json",
        lambda raw: (
            raw["strategies"].__setitem__("slot_cascade", ["capacity"]),
            raw["strategies"]["by_pair_class"].__setitem__("body", "capacity"),
        ),
    )
    held = backfill.load_backfill_config(str(path))
    require(
        held.slot_cascade == (backfill.STRATEGY_CAPACITY,),
        f"the variant parsed to {held.slot_cascade}, not a capacity only cascade",
    )
    original = backfill.load_backfill_config
    backfill.load_backfill_config = lambda *_args, **_kwargs: held
    try:
        plan, _document, _paragraphs, _translator = _moved_fixture(work / "e5")
    finally:
        backfill.load_backfill_config = original
    require(len(plan.entries) == 1, f"{len(plan.entries)} chains were planned, not 1")
    allocation = plan.entries[0].allocation
    require(
        allocation.strategy == backfill.STRATEGY_CAPACITY,
        f"the capacity only cascade produced {allocation.strategy!r}",
    )
    require(
        "".join(fragment.text for fragment in allocation.fragments) == "译" * 40,
        "the capacity only cascade did not conserve the translation",
    )
    return f"pieces {[len(f.text) for f in allocation.fragments]} under capacity only"


PURE_CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("S1", s1_estimate_retreats_to_the_last_full_line),
    ("S2", s2_an_estimate_already_at_a_line_end_stands),
    ("S3", s3_an_estimate_inside_the_first_line_stands),
    ("S4", s4_no_measured_line_leaves_the_estimate),
    ("S5", s5_unmeasured_cuts_report_the_fallback),
)

CONFIG_CHECKS: tuple[tuple[str, Callable[[Path], str]], ...] = (
    ("S6", s6_an_unimplemented_cascade_level_is_refused),
    ("S7", s7_an_out_of_range_bound_is_refused),
)

RUN_CHECKS: tuple[tuple[str, Callable[[Path], str]], ...] = (
    ("E1", e1_the_cut_moves_back_to_a_measured_line_end),
    ("E2", e2_the_moved_cut_conserves_the_translation),
    ("E3", e3_an_overrun_next_box_falls_to_capacity),
    ("E4", e4_the_last_member_is_never_pulled_back),
    ("E5", e5_the_capacity_only_cascade_still_runs),
)


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        checks: list[tuple[str, Callable[[], str]]] = [
            *PURE_CHECKS,
            *((name, (lambda f=check: f(tmp))) for name, check in CONFIG_CHECKS),
            *((name, (lambda f=check: f(tmp))) for name, check in RUN_CHECKS),
        ]
        for name, check in checks:
            try:
                detail = check()
            except Exception as error:  # noqa: BLE001 - the gate reports, never raises
                failures += 1
                print(f"{name} FAIL  {type(error).__name__}: {error}")
            else:
                print(f"{name} ok    {detail}")
    total = len(PURE_CHECKS) + len(CONFIG_CHECKS) + len(RUN_CHECKS)
    print(f"\n{total - failures}/{total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
