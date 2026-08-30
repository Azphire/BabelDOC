"""Stratified column boundaries: an embedded box's own columns chain up.

Page-wide bands conflate column systems that share an x range: an embedded
box setting three narrow columns under a two-column article puts its first
column into the article's band, which hides the article's own handover and
leaves the box's later columns paired with nothing (Courier-en p4: the LINKS
box's second column ended "hosts the Indigenous and" and its third column
started a fresh paragraph). The fourth boundary kind rebuilds the column
systems from geometry -- stacked units, vertical strata, bands within a
stratum -- and pairs adjacent bands under the same deterministic gates the
intra-column kind uses.
"""

from __future__ import annotations

from types import SimpleNamespace

from babeldoc.magazine.chain_builder import _accepted_edges
from babeldoc.magazine.chain_builder import _chains_from
from babeldoc.magazine.chain_builder import _textually_continuous
from babeldoc.magazine.chain_signals import BOUNDARY_STRATIFIED
from babeldoc.magazine.chain_signals import evaluate_column_boundaries
from babeldoc.magazine.chain_signals import evaluate_intra_column_boundaries
from babeldoc.magazine.chain_signals import evaluate_stratified_column_boundaries
from babeldoc.magazine.chain_signals import load_chain_config

from tests.minimal.test_chain_demo import _detector_page
from tests.minimal.test_chain_demo import _detector_paragraph
from tests.minimal.test_chain_demo import _policy

MAIN_LEFT = "the main article runs on and its sentence hands over at"
MAIN_RIGHT = "into the right main column where the sentence finishes."
BOX_A_TOP = "established long ago, the boxed program does its work."
BOX_A_BOTTOM = "the box aims to build dialogue hosted by the"
BOX_B = "council and its members to secure a role for the"
BOX_C = "United Nations bodies that value it."


def _boxed_page(box_b_text: str = BOX_B):
    """A two-column article over an embedded three-column box.

    The article columns live in one vertical stratum (bottoms 500), the box
    columns in another (extents within 90..154). The box's first column is
    two stacked paragraphs, the upper one ended, the lower one handing on.
    """
    main_left = _detector_paragraph(MAIN_LEFT, "main-left", left=40, bottom=500)
    main_right = _detector_paragraph(MAIN_RIGHT, "main-right", left=330, bottom=500)
    a_top = _detector_paragraph(BOX_A_TOP, "box-a-top", left=40, bottom=124)
    a_bottom = _detector_paragraph(BOX_A_BOTTOM, "box-a-bottom", left=40, bottom=90)
    b = _detector_paragraph(box_b_text, "box-b", left=260, bottom=100)
    c = _detector_paragraph(BOX_C, "box-c", left=470, bottom=100)
    return _detector_page(0, [main_left, main_right, a_top, a_bottom, b, c])


def test_embedded_box_three_column_sequence_chains() -> None:
    config = load_chain_config()
    page = _boxed_page()
    verdicts = [
        *evaluate_column_boundaries(page, 0, _policy, config),
        *evaluate_intra_column_boundaries(page, 0, _policy, config),
        *evaluate_stratified_column_boundaries(page, 0, _policy, config),
    ]
    stratified = [v for v in verdicts if v.kind == BOUNDARY_STRATIFIED and v.tail]
    linked_pairs = {
        (v.tail.paragraph.debug_id, v.head.paragraph.debug_id)
        for v in stratified
        if v.linked
    }
    # The box hands over between its own columns, and the hidden main-article
    # handover surfaces because the box no longer stands in for its band.
    assert ("box-a-bottom", "box-b") in linked_pairs
    assert ("box-b", "box-c") in linked_pairs
    assert ("main-left", "main-right") in linked_pairs

    edges, _dropped = _accepted_edges(
        verdicts,
        config["boundary_priority"],
        tuple(config["continuation_carry_words"]),
    )
    chains = _chains_from(edges)
    by_ids = sorted(
        [paragraph.debug_id for paragraph in chain] for chain in chains
    )
    assert ["box-a-bottom", "box-b", "box-c"] in by_ids
    assert ["main-left", "main-right"] in by_ids
    # The ended paragraph above the handover stays outside every chain.
    assert all("box-a-top" not in ids for ids in by_ids)


def test_a_terminated_box_tail_does_not_hand_over() -> None:
    config = load_chain_config()
    page = _boxed_page(box_b_text=BOX_B.rsplit(" ", 3)[0] + ".")
    verdicts = evaluate_stratified_column_boundaries(page, 0, _policy, config)
    linked_pairs = {
        (v.tail.paragraph.debug_id, v.head.paragraph.debug_id)
        for v in verdicts
        if v.linked and v.tail
    }
    assert ("box-b", "box-c") not in linked_pairs
    assert ("box-a-bottom", "box-b") in linked_pairs


def test_carry_word_tail_hands_over_to_a_proper_noun() -> None:
    def verdict(tail_text: str, head_text: str):
        return SimpleNamespace(
            tail=SimpleNamespace(paragraph=SimpleNamespace(unicode=tail_text)),
            head=SimpleNamespace(paragraph=SimpleNamespace(unicode=head_text)),
        )

    carry = tuple(load_chain_config()["continuation_carry_words"])
    pair = verdict("instruments like the", "United Nations Declaration")
    assert _textually_continuous(pair, carry) is True
    assert _textually_continuous(pair, ()) is False
    fresh = verdict("the previous story ended here.", "Newly Started Headline")
    assert _textually_continuous(fresh, carry) is False
