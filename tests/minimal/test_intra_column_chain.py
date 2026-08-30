"""Intra-column band boundaries: a wrap's stacked measures chain up.

A wrap around a photo or pull quote leaves one running paragraph as stacked
bands -- wide, narrow, wide -- each a paragraph of its own, translated and
set alone, which is what broke Courier-en p4 into sentence shards. The third
boundary kind links consecutive stacked body bands under deterministic gates
(overlap, gap bound, unterminated tail, clear head), enters the existing
exclusive assembly at the lowest declared priority, and rides the existing
joint translation and redistribution unchanged.
"""

from __future__ import annotations

from babeldoc.magazine import chain_backfill as backfill
from babeldoc.magazine.chain_builder import _accepted_edges
from babeldoc.magazine.chain_builder import _chains_from
from babeldoc.magazine.chain_signals import BOUNDARY_INTRA_COLUMN
from babeldoc.magazine.chain_signals import evaluate_column_boundaries
from babeldoc.magazine.chain_signals import evaluate_intra_column_boundaries
from babeldoc.magazine.chain_signals import load_chain_config

from tests.minimal.test_chain_demo import _detector_page
from tests.minimal.test_chain_demo import _detector_paragraph
from tests.minimal.test_chain_demo import _policy

WIDE_TOP = "the wide measure continues without any stop at its"
NARROW = "narrow measure beside the photograph keeps going"
WIDE_BOTTOM = "and the wide measure resumes below the photograph"


def _stacked_page(top_text=WIDE_TOP, gap: float = 4.0):
    # Box height is 30pt, so consecutive bottoms step by 30 plus the gap.
    step = 30.0 + gap
    top = _detector_paragraph(top_text, "band-top", left=40, bottom=100 + 2 * step)
    middle = _detector_paragraph(NARROW, "band-middle", left=40, bottom=100 + step)
    bottom = _detector_paragraph(WIDE_BOTTOM, "band-bottom", left=40, bottom=100)
    return _detector_page(0, [top, middle, bottom]), (top, middle, bottom)


def test_three_stacked_bands_link_into_one_chain() -> None:
    config = load_chain_config()
    page, (top, middle, bottom) = _stacked_page()
    verdicts = evaluate_intra_column_boundaries(page, 0, _policy, config)
    linked = [verdict for verdict in verdicts if verdict.linked]
    assert len(linked) == 2
    assert all(verdict.kind == BOUNDARY_INTRA_COLUMN for verdict in linked)
    assert all(verdict.score is None for verdict in linked)
    assert all(verdict.pair == "body->body" for verdict in linked)

    edges, dropped = _accepted_edges(verdicts, config["boundary_priority"])
    assert len(edges) == 2 and dropped == []
    chains = _chains_from(edges)
    assert len(chains) == 1
    assert [paragraph.debug_id for paragraph in chains[0]] == [
        "band-top",
        "band-middle",
        "band-bottom",
    ]


def test_a_terminated_tail_breaks_the_chain() -> None:
    config = load_chain_config()
    page, _bands = _stacked_page(top_text=WIDE_TOP + ".")
    verdicts = evaluate_intra_column_boundaries(page, 0, _policy, config)
    linked = [verdict for verdict in verdicts if verdict.linked]
    assert len(linked) == 1
    refused = [verdict for verdict in verdicts if not verdict.linked]
    assert len(refused) == 1
    assert refused[0].values["tail_no_terminal_punct"] == 0.0
    chains = _chains_from(
        _accepted_edges(verdicts, config["boundary_priority"])[0]
    )
    assert [paragraph.debug_id for paragraph in chains[0]] == [
        "band-middle",
        "band-bottom",
    ]


def test_a_gap_beyond_the_bound_is_no_boundary() -> None:
    config = load_chain_config()
    wide_gap = float(config["intra_column_chain_max_gap_pt"]) + 10.0
    page, _bands = _stacked_page(gap=wide_gap)
    verdicts = evaluate_intra_column_boundaries(page, 0, _policy, config)
    assert [verdict for verdict in verdicts if verdict.eligible] == []


def test_a_stack_and_a_column_edge_join_into_one_path() -> None:
    """The p4 shape: band above band in one column, then over to the next.

    The intra edge hands band-top on to band-bottom, the column edge hands
    band-bottom on to the next column's head, and exclusive assembly lets a
    body paragraph resume once and hand on once, so the three make one path.
    """
    config = load_chain_config()
    upper = _detector_paragraph(WIDE_TOP, "stack-upper", left=40, bottom=94)
    lower = _detector_paragraph(NARROW, "stack-lower", left=40, bottom=60)
    next_head = _detector_paragraph(
        "into the following body column", "column-head", left=330, bottom=600
    )
    page = _detector_page(0, [upper, lower, next_head])
    verdicts = [
        *evaluate_column_boundaries(page, 0, _policy, config),
        *evaluate_intra_column_boundaries(page, 0, _policy, config),
    ]
    edges, _dropped = _accepted_edges(verdicts, config["boundary_priority"])
    chains = _chains_from(edges)
    assert len(chains) == 1
    assert [paragraph.debug_id for paragraph in chains[0]] == [
        "stack-upper",
        "stack-lower",
        "column-head",
    ]


def test_conservation_holds_over_three_banded_members() -> None:
    merge = backfill.merge_chain_text(("a" * 50, "b" * 30, "c" * 40))
    translated = "译" * 120
    result = backfill.redistribute(
        merge,
        translated,
        "zh",
        backfill.STRATEGY_TAIL_ALIGNED,
        align_enabled=False,
        cut_positions=[52, 81],
        cut_estimates=[50, 79],
    )
    report = backfill.verify_redistribution(merge, translated, result)
    assert report.ok, report
    assert [len(segment.text) for segment in result.segments] == [52, 29, 39]
