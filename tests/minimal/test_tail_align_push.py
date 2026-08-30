"""The tail aligned cut's forward branch.

The pull back closes a member on a line it filled -- but only backwards, so a
share estimate standing inside a member's first line was refused outright
(``min_lines``) and the cut stayed mid-line, which is the Courier-en p4#20
shape: four measured line ends, ``kept_lines: 0``, ``moved_chars: 0``. The
push is the one move left that still ends the member on a full line:
advancing to the end of the line the estimate stands in, bounded by the
window that keeps every later member a character and by ``push_max_chars``.
"""

from __future__ import annotations

import json

import pytest
from babeldoc.magazine import chain_backfill as backfill

# The p4#20 replay: line ends measured at these offsets, the estimate below
# the first of them, so no pull-back candidate exists at all.
P4_LINE_ENDS = (23, 47, 71, 95)


def test_refused_pull_back_pushes_to_the_current_line_end() -> None:
    position, reason = backfill.tail_aligned_cut(
        20, P4_LINE_ENDS, 1, 100, 1, True, 24
    )
    assert (position, reason) == (23, backfill.TAIL_ALIGN_PUSHED)


def test_push_stays_put_beyond_its_char_bound() -> None:
    # The nearest line end is 40 characters past the estimate; filling that
    # line would drag most of the member forward, so the estimate stands.
    position, reason = backfill.tail_aligned_cut(20, (60, 90), 1, 100, 1, True, 24)
    assert (position, reason) == (20, backfill.TAIL_ALIGN_MIN_LINES)


def test_push_never_empties_a_later_member() -> None:
    # high == 21 is the last position leaving every later member a character;
    # the only line ends sit beyond it, so the push finds no candidate.
    position, reason = backfill.tail_aligned_cut(20, (23, 47), 1, 21, 1, True, 24)
    assert (position, reason) == (20, backfill.TAIL_ALIGN_MIN_LINES)


def test_push_disabled_is_the_standing_behaviour() -> None:
    position, reason = backfill.tail_aligned_cut(20, P4_LINE_ENDS, 1, 100, 1)
    assert (position, reason) == (20, backfill.TAIL_ALIGN_MIN_LINES)


def test_pull_back_still_wins_where_it_is_legal() -> None:
    position, reason = backfill.tail_aligned_cut(
        50, P4_LINE_ENDS, 1, 100, 1, True, 24
    )
    assert (position, reason) == (47, backfill.TAIL_ALIGN_MOVED)


def _merge_of(*members: str) -> backfill.ChainMerge:
    return backfill.merge_chain_text(members)


def test_conservation_holds_under_a_pushed_cut() -> None:
    merge = _merge_of("x" * 40, "y" * 60)
    translated = "甲" * 100
    result = backfill.redistribute(
        merge,
        translated,
        "zh",
        backfill.STRATEGY_TAIL_ALIGNED,
        align_enabled=False,
        cut_positions=[44],
        cut_estimates=[40],
    )
    report = backfill.verify_redistribution(merge, translated, result)
    assert report.ok, report
    assert [len(segment.text) for segment in result.segments] == [44, 56]


def test_conservation_holds_under_a_pulled_cut() -> None:
    merge = _merge_of("x" * 40, "y" * 60)
    translated = "甲" * 100
    result = backfill.redistribute(
        merge,
        translated,
        "zh",
        backfill.STRATEGY_TAIL_ALIGNED,
        align_enabled=False,
        cut_positions=[23],
        cut_estimates=[40],
    )
    report = backfill.verify_redistribution(merge, translated, result)
    assert report.ok, report
    assert [len(segment.text) for segment in result.segments] == [23, 77]


def test_shipped_config_carries_the_push_bounds() -> None:
    config = backfill.load_backfill_config()
    assert config.tail_align_allow_push is True
    assert 1 <= config.tail_align_push_max_chars <= 80


def _write_config(tmp_path, mutate):
    raw = json.loads(backfill.CONFIG_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "chain_translation.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_allow_push_must_be_a_boolean(tmp_path) -> None:
    path = _write_config(
        tmp_path, lambda raw: raw["tail_align"].__setitem__("allow_push", "yes")
    )
    with pytest.raises(backfill.BackfillConfigError):
        backfill.load_backfill_config(path)


def test_push_max_chars_is_range_bounded(tmp_path) -> None:
    path = _write_config(
        tmp_path, lambda raw: raw["tail_align"].__setitem__("push_max_chars", 400)
    )
    with pytest.raises(backfill.BackfillConfigError):
        backfill.load_backfill_config(path)
