from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.format.pdf.document_il.midend import styles_and_formulas
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import drop_cap_render
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.line_split import paragraph_characters
from tests.minimal.test_drop_cap_keep_flatten import RuntimeConfig
from tests.minimal.test_drop_cap_keep_flatten import direct_intent
from tests.minimal.test_drop_cap_keep_flatten import document_digest
from tests.minimal.test_drop_cap_keep_flatten import english_render_paragraph
from tests.minimal.test_drop_cap_keep_flatten import geometry_guard
from tests.minimal.test_drop_cap_keep_flatten import make_article_ir
from tests.minimal.test_drop_cap_keep_flatten import make_document
from tests.minimal.test_drop_cap_keep_flatten import metric_for
from tests.minimal.test_drop_cap_keep_flatten import pdf_character
from tests.minimal.test_drop_cap_keep_flatten import pdf_style
from tests.minimal.test_drop_cap_keep_flatten import register_render_intents


def test_english_raised_initial_preserves_text_color_and_font() -> None:
    paragraph = english_render_paragraph()
    source_text = paragraph.unicode
    characters = paragraph_characters(paragraph)
    target_font = characters[2].pdf_style.font_id
    before_count = len(characters)
    config = drop_cap_render.load_render_config()
    regime = config.regime_for("en")
    assert regime is not None
    outcome = drop_cap_render.set_one(
        paragraph,
        regime,
        config,
        drop_cap_render._blank("p7#8", 7, "keep", "en", regime.name),
        intent=direct_intent(drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL),
        glyph_metric_resolver=metric_for,
        geometry_guard=geometry_guard(width=160.0),
    )
    assert outcome["set"], outcome
    assert outcome["initial"] == "A"
    assert outcome["initial_char_count"] == 1
    assert outcome["reserve_lines"] == 1
    assert outcome["second_line_start_x"] == outcome["body_box"][0]
    assert abs(outcome["ink_bottom_delta"]) <= config.ink_bottom_tolerance_pt
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
    assert sum(character.char_unicode == "A" for character in characters) == 1


class ValidFont:
    def has_glyph(self, codepoint: int) -> int:
        return codepoint

    def glyph_bbox(self, _codepoint: int):
        return (0.02, -0.1, 0.66, 0.75)

    def glyph_advance(self, _codepoint: int) -> float:
        return 0.68


def test_glyph_metric_valid_unavailable_and_unexpected_semantics() -> None:
    typesetter = object.__new__(Typesetting)
    sample = pdf_character("A", 0.0, 0.0)
    typesetter.font_mapper = SimpleNamespace(fontid2font={"target-body": ValidFont()})
    measured = typesetter.glyph_ink_metrics(sample)
    assert measured is not None
    assert measured.ink_box_em == (0.02, -0.1, 0.66, 0.75)
    assert measured.advance_em == 0.68
    assert measured.font_id == "target-body"

    class RuntimeUnavailable(ValidFont):
        def has_glyph(self, _codepoint: int) -> int:
            raise RuntimeError("font unavailable")

    typesetter.font_mapper = SimpleNamespace(
        fontid2font={"target-body": RuntimeUnavailable()}
    )
    assert typesetter.glyph_ink_metrics(sample) is None

    class NonFinite(ValidFont):
        def glyph_bbox(self, _codepoint: int):
            return (0.02, float("nan"), 0.66, 0.75)

    typesetter.font_mapper = SimpleNamespace(fontid2font={"target-body": NonFinite()})
    assert typesetter.glyph_ink_metrics(sample) is None
    bad_size = copy.deepcopy(sample)
    bad_size.pdf_style.font_size = float("inf")
    assert typesetter.glyph_ink_metrics(bad_size) is None

    class SentinelError(Exception):
        pass

    marker = SentinelError("mapper bug")

    class Unexpected(ValidFont):
        def has_glyph(self, _codepoint: int) -> int:
            raise marker

    typesetter.font_mapper = SimpleNamespace(fontid2font={"target-body": Unexpected()})
    with pytest.raises(SentinelError) as raised:
        typesetter.glyph_ink_metrics(sample)
    assert raised.value is marker


def test_initial_adjacent_exemption_is_bounded_to_enlarged_opening() -> None:
    characters = [
        il.PdfCharacter(char_unicode="A", pdf_style=pdf_style(font_size=30.0)),
        *[
            il.PdfCharacter(char_unicode=glyph, pdf_style=pdf_style(font_size=10.0))
            for glyph in "bcdefghijk"
        ],
    ]
    paragraph = il.PdfParagraph(
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_line=il.PdfLine(pdf_character=characters)
            )
        ]
    )
    assert styles_and_formulas.initial_adjacent_exemption(paragraph) == (1, 9)
    characters[0].pdf_style.font_size = 10.0
    assert styles_and_formulas.initial_adjacent_exemption(paragraph) == (0, 0)


def test_english_collision_keeps_fixed_assets_and_document_unchanged(
    tmp_path: Path,
) -> None:
    body = english_render_paragraph()
    title_characters = [
        pdf_character(glyph, 12.0 + index * 8.0, 92.0, width=8.0)
        for index, glyph in enumerate("FIXED TITLE")
    ]
    title = il.PdfParagraph(
        box=il.Box(8.0, 88.0, 115.0, 118.0),
        pdf_style=title_characters[0].pdf_style,
        unicode="FIXED TITLE",
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=character)
            for character in title_characters
        ],
        layout_label="title",
    )
    docs = make_document([body, title])
    article_ir = make_article_ir([body, title], canonical_count=1)
    config = RuntimeConfig(tmp_path / "fixed-assets")
    register_render_intents(config, [body])
    before_document = document_digest(docs)
    before_assets = fixed_assets.build_inventory(
        docs,
        article_document_ir=article_ir,
    )
    report = drop_cap_render.apply(
        config,
        docs,
        article_document_ir=article_ir,
        typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
    )
    after_assets = fixed_assets.build_inventory(
        docs,
        article_document_ir=article_ir,
    )
    assert report is not None
    assert report["paragraphs"][0]["revert_reason"] == (
        drop_cap_render.REVERT_COLLISION
    )
    assert document_digest(docs) == before_document
    assert fixed_assets.compare(before_assets, after_assets, 0.000001).holds
