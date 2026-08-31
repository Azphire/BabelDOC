"""B18 T1 -- a Latin word is never split mid-glyph.

A word unit (a target whose meaningful glyphs all refuse a line break) is
fitted on a single line: first widened into its deterministic corridor at
the policy size, then shrunk to exactly fit, and only past the path's own
minimum scale does the standing escalation take over.  A multi-word text
may wrap at whitespace, never inside a word; the terminal legacy fallback
that still splits must leave a per-case record.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import (
    BoundedTypesettingError,
)
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.format.pdf.document_il.midend.typesetting import TypesettingUnit
from babeldoc.format.pdf.document_il.midend.typesetting import _word_unit_core
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph


class RenderFont:
    font_id = "body"
    name = "body"
    is_bold = False
    is_italic = False
    is_monospaced = False
    is_serif = True

    @staticmethod
    def char_lengths(text: str, font_size: float):
        return tuple(font_size * 0.5 for _character in text)

    @staticmethod
    def has_glyph(_codepoint: int) -> int:
        return 1


class RenderMapper:
    def __init__(self) -> None:
        self.base_font = RenderFont()
        self.fontid2font = {self.base_font.font_id: self.base_font}

    def map(self, _original_font, _character: str):
        return self.base_font


class Config:
    def __init__(self, work: Path, lang_out: str = "en") -> None:
        self.work = work
        self.lang_out = lang_out
        self.progress_monitor = None

    def get_working_file_path(self, name: str):
        self.work.mkdir(parents=True, exist_ok=True)
        return self.work / name

    @staticmethod
    def raise_if_cancelled() -> None:
        return None


def _units(typesetter: Typesetting, text: str, font_size: float = 10.0):
    style = il_version_1.PdfStyle(font_id="body", font_size=font_size)
    return [
        TypesettingUnit(
            unicode=character,
            font=typesetter.font_mapper.base_font,
            font_size=font_size,
            style=style,
            xobj_id=-1,
        )
        for character in text
    ]


def _single_word_page(word_box, neighbor_x: float):
    """One word-unit paragraph plus a neighbour column blocking at x."""
    word = _paragraph("innovation", "word-1", word_box)
    word.xobj_id = -1
    neighbor = _paragraph(
        "occupied", "neighbor-1", (neighbor_x, 0.0, neighbor_x + 15.0, 100.0)
    )
    neighbor.xobj_id = -1
    page = _page(0, [word, neighbor])
    return word, neighbor, page


def test_word_unit_core_recognises_only_unbreakable_runs():
    typesetter = Typesetting(SimpleNamespace(lang_out="en"), RenderMapper())
    assert _word_unit_core(_units(typesetter, "innovation")) is not None
    # 尾随空白归一化后仍是词单元
    assert _word_unit_core(_units(typesetter, "innovation ")) is not None
    # 内部空白、CJK、单字符都不是
    assert _word_unit_core(_units(typesetter, "two words")) is None
    assert _word_unit_core(_units(typesetter, "创新")) is None
    assert _word_unit_core(_units(typesetter, "i")) is None


def test_word_unit_widens_into_corridor_at_policy_size(tmp_path):
    # 10 字形 × 5pt = 政策字号下需 50pt;源框仅 12pt 宽,走廊到 100-2。
    word, neighbor, page = _single_word_page((10.0, 60.0, 22.0, 74.0), 100.0)
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    units = _units(typesetter, "innovation")

    typesetter.retypeset_with_precomputed_scale(word, page, units, 1.0)

    chars = [
        comp.pdf_character
        for comp in word.pdf_paragraph_composition
        if comp.pdf_character is not None
    ]
    assert len(chars) == len("innovation")
    # 单行:所有字符同一基线带
    tops = {round(float(char.box.y), 2) for char in chars}
    assert len(tops) == 1
    # 政策字号原样(未缩)
    assert word.scale == pytest.approx(1.0)
    # 扩宽越过源框、止于邻居墨迹减净空,与邻居零相交
    ink_x2 = max(float(char.box.x2) for char in chars)
    assert ink_x2 > 22.0
    assert ink_x2 <= float(neighbor.box.x)
    record = typesetter._word_fit_records[-1]
    assert record["kind"] == "word_unit"
    assert record["outcome"] == "fit_policy"
    assert record["expanded"] is True


def test_word_unit_shrinks_to_exact_fit_when_corridor_is_tight(tmp_path):
    # 走廊 40-10-2=28pt,词需 50pt → 有界缩放,单行完整
    word, neighbor, page = _single_word_page((10.0, 60.0, 22.0, 74.0), 40.0)
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    units = _units(typesetter, "innovation")

    typesetter.retypeset_with_precomputed_scale(word, page, units, 1.0)

    chars = [
        comp.pdf_character
        for comp in word.pdf_paragraph_composition
        if comp.pdf_character is not None
    ]
    assert len(chars) == len("innovation")
    tops = {round(float(char.box.y), 2) for char in chars}
    assert len(tops) == 1
    assert 0.4 < float(word.scale) < 0.7
    ink_x2 = max(float(char.box.x2) for char in chars)
    assert ink_x2 <= float(neighbor.box.x)
    assert typesetter._word_fit_records[-1]["outcome"] == "fit_scaled"


def test_bounded_word_unit_fails_closed_past_minimum_scale(tmp_path):
    # bounded 路径:盒子不许扩,min readable scale 下仍不进 → 既有 fail-closed
    word = _paragraph("innovation", "word-b", (10.0, 60.0, 22.0, 74.0))
    word.xobj_id = -1
    page = _page(0, [word])
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    units = _units(typesetter, "innovation")

    with pytest.raises(BoundedTypesettingError):
        typesetter.retypeset_bounded_text(
            word,
            page,
            units,
            source_ref="p1#0",
            source_box=(10.0, 60.0, 22.0, 74.0),
            minimum_scale=0.6,
            maximum_lines=None,
        )
    outcomes = [rec["outcome"] for rec in typesetter._word_fit_records]
    assert "corridor_exhausted" in outcomes


def test_word_unit_exhaustion_falls_back_to_recorded_legacy_break(tmp_path):
    # 走廊被邻居挤死(可用 6pt),30 字形词到 min_scale 0.1 仍不进 →
    # 既有升级路径(终局兜底可劈)接手,且劈词逐条在报,文本零丢失。
    long_word = "x" * 30
    word = _paragraph(long_word, "word-x", (10.0, 20.0, 14.0, 90.0))
    word.xobj_id = -1
    neighbor = _paragraph("occupied", "neighbor-x", (16.0, 0.0, 30.0, 100.0))
    neighbor.xobj_id = -1
    page = _page(0, [word, neighbor])
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    units = _units(typesetter, long_word)

    typesetter.retypeset_with_precomputed_scale(word, page, units, 1.0)

    chars = [
        comp.pdf_character
        for comp in word.pdf_paragraph_composition
        if comp.pdf_character is not None
    ]
    assert len(chars) == len(long_word)  # no text loss
    outcomes = {rec["outcome"] for rec in typesetter._word_fit_records}
    assert "corridor_exhausted" in outcomes
    assert "naked_break_legacy" in outcomes


def test_multiword_wraps_at_whitespace_never_inside_a_word():
    typesetter = Typesetting(SimpleNamespace(lang_out="en"), RenderMapper())
    paragraph = _paragraph("hello world", "multi-1", (0.0, 0.0, 40.0, 40.0))
    paragraph.xobj_id = -1
    units = _units(typesetter, "hello world")

    laid_out, fits = typesetter._layout_typesetting_units(
        units,
        il_version_1.Box(0.0, 0.0, 40.0, 40.0),
        1.0,
        1.3,
        paragraph,
        True,
        forbid_naked_split=True,
    )
    assert fits
    lines = {unit.layout_line_index for unit in laid_out}
    assert len(lines) == 2  # wrapped at the space
    # 每行文本都是完整词
    by_line: dict[int, str] = {}
    for unit in laid_out:
        by_line.setdefault(unit.layout_line_index, "")
        by_line[unit.layout_line_index] += unit.try_get_unicode() or ""
    assert sorted(text.strip() for text in by_line.values()) == [
        "hello",
        "world",
    ]


def test_forbid_naked_split_rejects_scale_instead_of_stacking_characters():
    # 词比行宽还宽:旧行为逐字符堆叠“适配”,新行为判此 scale 失败
    typesetter = Typesetting(SimpleNamespace(lang_out="en"), RenderMapper())
    paragraph = _paragraph("innovation", "narrow-1", (0.0, 0.0, 12.0, 90.0))
    paragraph.xobj_id = -1
    units = _units(typesetter, "innovation")

    laid_out, fits = typesetter._layout_typesetting_units(
        units,
        il_version_1.Box(0.0, 0.0, 12.0, 90.0),
        1.0,
        1.3,
        paragraph,
        True,
        forbid_naked_split=True,
    )
    assert not fits
    assert laid_out == []

    # 兜底模式仍可劈,但每一刀都有事件
    events: list = []
    laid_out, fits = typesetter._layout_typesetting_units(
        units,
        il_version_1.Box(0.0, 0.0, 12.0, 90.0),
        1.0,
        1.3,
        paragraph,
        False,
        forbid_naked_split=False,
        naked_split_events=events,
    )
    assert fits
    assert events, "a legacy split must be attributable"


def test_word_fit_report_is_written(tmp_path):
    word, _neighbor, page = _single_word_page((10.0, 60.0, 22.0, 74.0), 100.0)
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    units = _units(typesetter, "innovation")
    typesetter.retypeset_with_precomputed_scale(word, page, units, 1.0)
    typesetter._flush_word_fit_report()

    report = json.loads((tmp_path / "word_fit.report.json").read_text("utf-8"))
    assert report["schema_version"] == 1
    assert report["counts"].get("word_unit:fit_policy") == 1
    assert report["records"][0]["debug_id"] == "word-1"
