"""The bounded rebalance: a dangling chained tail merges forward, verified.

The simulation can misplace a cut; the rebalance is the post-typesetting
floor under it. It moves the rendered dangling line's characters whole into
the member the chain hands over to, holds the chain conservation law over
the move, and rolls the move back when either member stops fitting.
"""

from __future__ import annotations

from babeldoc.format.pdf.document_il.midend.typesetting import (
    BoundedTypesettingError,
)
from babeldoc.magazine import tail_fill
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.chain_signals import paragraph_characters

from tests.minimal.test_tail_fill import document
from tests.minimal.test_tail_fill import paragraph


class FakeTypesetter:
    """Just enough of the typesetter for the rebalance to run its course."""

    def __init__(self, refuse_after: int | None = None):
        self.font_mapper = type("Mapper", (), {"fontid2font": {}})()
        self.calls = 0
        self.refuse_after = refuse_after

    def create_typesetting_units(self, paragraph, fonts):
        return []

    def retypeset_bounded_text(self, paragraph, page, units, **kwargs):
        self.calls += 1
        if self.refuse_after is not None and self.calls > self.refuse_after:
            raise BoundedTypesettingError("member_does_not_fit")


def members():
    prev = paragraph(
        [("这是一整行的十个字啊", 80.0), ("家、", 65.0)], (10.0, 60.0, 110.0, 92.0)
    )
    nxt = paragraph([("资源管理者以及决策者", 80.0)], (150.0, 60.0, 250.0, 92.0))
    return prev, nxt


def test_two_char_tail_merges_forward_and_conserves_text() -> None:
    prev, nxt = members()
    joined_before = (prev.unicode or "") + (nxt.unicode or "")
    docs = document({4: [prev, nxt]})
    applied, reason, moved = tail_fill._rebalance_one(
        FakeTypesetter(),
        prev,
        docs.page[0],
        nxt,
        docs.page[0],
        load_chain_config(),
    )
    assert applied, reason
    assert moved == 2
    assert prev.unicode == "这是一整行的十个字啊"
    assert nxt.unicode == "家、资源管理者以及决策者"
    assert (prev.unicode or "") + (nxt.unicode or "") == joined_before
    # The characters themselves moved: the next member now opens with them.
    next_chars = paragraph_characters(nxt)
    assert "".join(c.char_unicode for c in next_chars[:2]) == "家、"
    assert all("家" != c.char_unicode for c in paragraph_characters(prev))


def test_a_member_that_stops_fitting_rolls_the_move_back() -> None:
    prev, nxt = members()
    docs = document({4: [prev, nxt]})
    before_prev = prev.unicode
    before_next = nxt.unicode
    before_boxes = [
        (c.char_unicode, c.box.x, c.box.y)
        for c in paragraph_characters(prev) + paragraph_characters(nxt)
    ]
    applied, reason, moved = tail_fill._rebalance_one(
        FakeTypesetter(refuse_after=1),
        prev,
        docs.page[0],
        nxt,
        docs.page[0],
        load_chain_config(),
    )
    assert not applied and moved == 0
    assert reason.startswith("retypeset_refused:")
    assert prev.unicode == before_prev and nxt.unicode == before_next
    after_boxes = [
        (c.char_unicode, c.box.x, c.box.y)
        for c in paragraph_characters(prev) + paragraph_characters(nxt)
    ]
    assert after_boxes == before_boxes


def test_a_whole_member_tail_is_left_alone() -> None:
    prev = paragraph([("家、", 65.0)], (10.0, 60.0, 110.0, 92.0))
    nxt = paragraph([("资源管理者", 80.0)], (150.0, 60.0, 250.0, 92.0))
    docs = document({4: [prev, nxt]})
    applied, reason, _ = tail_fill._rebalance_one(
        FakeTypesetter(), prev, docs.page[0], nxt, docs.page[0], load_chain_config()
    )
    assert not applied
    assert reason == "tail_is_the_whole_member"


def test_conservation_checker_is_the_chain_law() -> None:
    assert tail_fill._verified_conservation("甲乙丙", "丁戊", "甲乙", "丙丁戊")
    # A move that loses a character is refused by the law, not by luck.
    assert not tail_fill._verified_conservation("甲乙丙", "丁戊", "甲乙", "丁戊")


def test_budget_zero_disables_the_rebalance(tmp_path) -> None:
    prev, nxt = members()
    docs = document({4: [prev, nxt]})
    rows = [
        {
            "prev_ref": "p4#0",
            "next_ref": "p4#1",
            "chained": True,
            "last_line": {"chars": 2, "terminal_punct": False, "text": "家、"},
        }
    ]
    record = tail_fill.rebalance(
        None,
        docs,
        rows,
        FakeTypesetter(),
        {"tail_rebalance_max": 0, "tail_min_chars": 3},
    )
    assert record["enabled"] is False
    assert record["applied"] == 0
    assert prev.unicode == "这是一整行的十个字啊家、"
