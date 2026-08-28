from __future__ import annotations

import copy

import pytest
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import drop_cap_render
from babeldoc.magazine.line_split import paragraph_characters
from tests.minimal.test_drop_cap_keep_flatten import chinese_render_paragraph
from tests.minimal.test_drop_cap_keep_flatten import direct_intent
from tests.minimal.test_drop_cap_keep_flatten import geometry_guard
from tests.minimal.test_drop_cap_keep_flatten import metric_for


def paragraph_snapshot(paragraph) -> tuple:
    return (
        paragraph.unicode,
        tuple(
            (
                character.char_unicode,
                character.pdf_style.font_id,
                character.pdf_style.font_size,
                character.pdf_style.graphic_state.passthrough_per_char_instruction,
                tuple(
                    getattr(character.box, name)
                    for name in ("x", "y", "x2", "y2")
                ),
                character.advance,
            )
            for character in paragraph_characters(paragraph)
        ),
    )


def test_chinese_two_line_inset_preserves_text_color_and_font() -> None:
    paragraph = chinese_render_paragraph()
    source_text = paragraph.unicode
    characters = paragraph_characters(paragraph)
    target_font = characters[2].pdf_style.font_id
    before_count = len(characters)
    config = drop_cap_render.load_render_config()
    regime = config.regime_for("zh-CN")
    assert regime is not None
    outcome = drop_cap_render.set_one(
        paragraph,
        regime,
        config,
        drop_cap_render._blank("p7#8", 7, "keep", "zh-CN", regime.name),
        intent=direct_intent(drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL),
        glyph_metric_resolver=metric_for,
        geometry_guard=geometry_guard(),
    )
    assert outcome["set"], outcome
    assert outcome["initial"] == "中"
    assert outcome["initial_char_count"] == 1
    assert outcome["reserve_lines"] == 2
    assert abs(outcome["ink_top_delta"]) <= config.ink_anchor_tolerance_pt
    assert abs(outcome["ink_bottom_delta"]) <= config.ink_anchor_tolerance_pt
    reserve_edge = outcome["initial_ink_box"][2] + outcome["gutter"]
    assert all(
        position >= reserve_edge - config.ink_anchor_tolerance_pt
        for position in outcome["body_start_x"]
    )
    assert outcome["third_line_start_x"] == outcome["body_box"][0]
    characters = paragraph_characters(paragraph)
    target = characters[outcome["_target_index"]]
    instruction = target.pdf_style.graphic_state.passthrough_per_char_instruction
    assert target.pdf_style.font_id == target_font
    assert "0.2 0.4 0.6 rg" in instruction
    assert "0.6 0.4 0.2 RG" in instruction
    assert "/GSfixture gs" in instruction
    assert len(characters) == before_count
    assert paragraph.unicode == source_text
    assert "".join(character.char_unicode or "" for character in characters) == (
        source_text
    )


def test_chinese_unavailable_metric_is_typed_and_restores_paragraph() -> None:
    paragraph = chinese_render_paragraph()
    before = paragraph_snapshot(paragraph)
    config = drop_cap_render.load_render_config()
    regime = config.regime_for("zh-CN")
    assert regime is not None
    outcome = drop_cap_render.set_one(
        paragraph,
        regime,
        config,
        drop_cap_render._blank("p7#8", 7, "keep", "zh-CN", regime.name),
        intent=direct_intent(drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL),
        glyph_metric_resolver=lambda _character: None,
        geometry_guard=geometry_guard(),
    )
    assert not outcome["set"]
    assert outcome["revert_reason"] == drop_cap_render.REVERT_NO_METRICS
    assert paragraph_snapshot(paragraph) == before


def test_chinese_collision_is_typed_and_restores_paragraph() -> None:
    paragraph = chinese_render_paragraph()
    before = copy.deepcopy(paragraph_snapshot(paragraph))
    config = drop_cap_render.load_render_config()
    regime = config.regime_for("zh-CN")
    assert regime is not None
    outcome = drop_cap_render.set_one(
        paragraph,
        regime,
        config,
        drop_cap_render._blank("p7#8", 7, "keep", "zh-CN", regime.name),
        intent=direct_intent(drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL),
        glyph_metric_resolver=metric_for,
        geometry_guard=geometry_guard(
            obstacles=(("fixed:title", (20.0, 55.0, 65.0, 95.0)),)
        ),
    )
    assert not outcome["set"]
    assert outcome["revert_reason"] == drop_cap_render.REVERT_COLLISION
    assert paragraph_snapshot(paragraph) == before


def test_chinese_unexpected_metric_error_propagates_same_object() -> None:
    paragraph = chinese_render_paragraph()
    config = drop_cap_render.load_render_config()
    regime = config.regime_for("zh-CN")
    assert regime is not None

    class SentinelError(Exception):
        pass

    marker = SentinelError("metric resolver bug")

    def fail(_character):
        raise marker

    with pytest.raises(SentinelError) as raised:
        drop_cap_render.set_one(
            paragraph,
            regime,
            config,
            drop_cap_render._blank("p7#8", 7, "keep", "zh-CN", regime.name),
            intent=direct_intent(drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL),
            glyph_metric_resolver=fail,
            geometry_guard=geometry_guard(),
        )
    assert raised.value is marker
