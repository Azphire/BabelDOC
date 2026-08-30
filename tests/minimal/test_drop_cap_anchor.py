"""The target initial's ink anchors to the source initial's ink, not its box.

The source metric box carries the ascent whitespace of a towering glyph, and
the typeset grid hangs the first line off that box top, so before B14 the
rendered initial floated the whole whitespace above where the source ink
started. The anchor captured at mark time says how far below its metric box
top the source ink actually began; the render moves the grid down by the
difference and the initial follows. A missing source metric moves nothing and
says so in the report.
"""

from __future__ import annotations

from types import SimpleNamespace

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import drop_cap_render
from tests.minimal.test_drop_cap_chinese import paragraph_snapshot
from tests.minimal.test_drop_cap_keep_flatten import chinese_render_paragraph
from tests.minimal.test_drop_cap_keep_flatten import direct_intent
from tests.minimal.test_drop_cap_keep_flatten import geometry_guard
from tests.minimal.test_drop_cap_keep_flatten import metric_for

# The fixture paragraph in chinese_render_paragraph: box top 92, first line
# baseline 80 at size 10 with CJK ink top 0.90 em, so the grid leaves a
# 3.0 pt gap between box top and first-line ink before any anchor applies.
FIXTURE_BOX_TOP = 92.0
FIXTURE_TYPESET_GAP = 3.0
# An ascent whitespace of 12 pt (>= 5 pt as the gate demands).
SOURCE_INK_OFFSET = 12.0


def anchored_intent(offset: float | None):
    base = direct_intent(drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL)
    anchor = None
    if offset is not None:
        anchor = drop_cap_intent.SourceAnchor(
            ink_top_offset_pt=offset,
            ink_top_em=0.68,
            source_font_size=30.0,
            metric_source=drop_cap_intent.ANCHOR_METRIC_GLYPH_BBOX,
            evidence=("font:/source-initial", "cid:65"),
        )
    return SimpleNamespace(**vars(base), source_anchor=anchor)


def render(intent):
    paragraph = chinese_render_paragraph()
    config = drop_cap_render.load_render_config()
    regime = config.regime_for("zh-CN")
    assert regime is not None
    outcome = drop_cap_render.set_one(
        paragraph,
        regime,
        config,
        drop_cap_render._blank("p7#8", 7, "keep", "zh-CN", regime.name),
        intent=intent,
        glyph_metric_resolver=metric_for,
        geometry_guard=geometry_guard(),
    )
    return paragraph, outcome


def test_anchored_initial_ink_top_matches_source_ink_top() -> None:
    paragraph, outcome = render(anchored_intent(SOURCE_INK_OFFSET))
    assert outcome["set"], outcome
    source_ink_top = FIXTURE_BOX_TOP - SOURCE_INK_OFFSET
    assert abs(outcome["initial_ink_box"][3] - source_ink_top) <= 0.5
    anchor = outcome["anchor"]
    assert anchor["fallback"] is None
    assert anchor["gap_source_pt"] == SOURCE_INK_OFFSET
    assert anchor["gap_typeset_pt"] == FIXTURE_TYPESET_GAP
    assert anchor["shift_pt"] == SOURCE_INK_OFFSET - FIXTURE_TYPESET_GAP
    # The hung grid followed: the first line's ink top moved with the anchor.
    assert abs(outcome["first_line_ink_top"] - source_ink_top) <= 0.5
    # Conservation: the anchor moves geometry, never the character set.
    text = paragraph.unicode
    snapshot = paragraph_snapshot(paragraph)
    assert "".join(entry[0] for entry in snapshot[1]) == text


def test_missing_source_metric_keeps_grid_and_reports_fallback() -> None:
    _, unanchored = render(
        direct_intent(drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL)
    )
    assert unanchored["set"], unanchored
    anchor = unanchored["anchor"]
    assert anchor["fallback"] == drop_cap_intent.ANCHOR_METRIC_FALLBACK
    assert anchor["shift_pt"] == 0.0
    # The grid stands where the pre-anchor behavior put it: first-line ink
    # right under the metric box top.
    expected = FIXTURE_BOX_TOP - FIXTURE_TYPESET_GAP
    assert abs(unanchored["initial_ink_box"][3] - expected) <= 0.5


def test_oversized_offset_is_clamped_by_the_paragraph_bottom() -> None:
    paragraph, outcome = render(anchored_intent(40.0))
    assert outcome["set"], outcome
    anchor = outcome["anchor"]
    # Dry body ink bottom is 49.0 and the box bottom is 20.0, so only 29 pt
    # of room exists; the desired 37 pt shift is clamped to what fits.
    assert anchor["shift_desired_pt"] == 37.0
    assert anchor["shift_pt"] == 29.0
    body_ink = outcome["body_ink_box"]
    assert body_ink[1] >= paragraph.box.y - 1.0


def font_fixture() -> il.PdfFont:
    return il.PdfFont(
        name="Source-Initial",
        font_id="source-initial",
        xref_id=77,
        pdf_font_char_bounding_box=[
            il.PdfFontCharBoundingBox(x=20.0, y=-15.0, x2=620.0, y2=680.0, char_id=65)
        ],
    )


def source_initial_character() -> il.PdfCharacter:
    return il.PdfCharacter(
        char_unicode="A",
        pdf_character_id=65,
        box=il.Box(x=10.0, y=65.0, x2=28.0, y2=95.0),
        pdf_style=il.PdfStyle(
            font_id="source-initial",
            font_size=30.0,
            graphic_state=il.GraphicState(),
        ),
        advance=18.0,
    )


def test_freeze_source_anchor_reads_the_font_ink_table() -> None:
    page = il.Page(pdf_font=[font_fixture()])
    anchor = drop_cap_intent.freeze_source_anchor(page, source_initial_character())
    assert anchor.metric_source == drop_cap_intent.ANCHOR_METRIC_GLYPH_BBOX
    # ink top = 65 + 0.68 * 30 = 85.4, so the offset below the box top is 9.6.
    assert anchor.ink_top_offset_pt == 9.6
    assert anchor.ink_top_em == 0.68
    assert anchor.source_font_size == 30.0
    assert anchor.ink_top_offset_pt >= 5.0


def test_freeze_source_anchor_without_glyph_entry_falls_back() -> None:
    character = source_initial_character()
    character.pdf_character_id = 999
    page = il.Page(pdf_font=[font_fixture()])
    anchor = drop_cap_intent.freeze_source_anchor(page, character)
    assert anchor.ink_top_offset_pt is None
    assert anchor.metric_source == drop_cap_intent.ANCHOR_METRIC_FALLBACK
    assert any("no-glyph-ink-box" in item for item in anchor.evidence)


def test_freeze_source_anchor_lands_in_the_intent_record() -> None:
    page = il.Page(pdf_font=[font_fixture()])
    character = source_initial_character()
    paragraph = il.PdfParagraph(unicode="A big opening")
    intent = drop_cap_intent.build_intent(
        source_ref="p1#0",
        article_id="article-fixture",
        paragraph=paragraph,
        source_character=character,
        target_policy=drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL,
        config_version=1,
        decision_version=1,
        source_anchor=drop_cap_intent.freeze_source_anchor(page, character),
    )
    record = intent.as_record()
    assert record["source_anchor"]["ink_top_offset_pt"] == 9.6
    assert (
        record["source_anchor"]["metric_source"]
        == drop_cap_intent.ANCHOR_METRIC_GLYPH_BBOX
    )
