"""B18 T3 -- a two-member title chain is joint-fitted before it is released.

Allocation side: when every cascade level fails, the two member boxes are
read as one logical band -- one common scale, one word-boundary cut both
boxes can hold, chosen nearest the boxes' own width shares; an extreme
title that stays infeasible at the title minimum scale still releases
exactly as before, with the probe naming why.  Render side: both proven
chain members set at one common scale.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import chain_backfill as backfill
from babeldoc.magazine import title_typeset
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.chain_translation import STRATEGY_JOINT_FIT
from babeldoc.magazine.chain_translation import ChainPlan
from tests.minimal.fakes import FixedWidthFont
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import StubChainTranslator
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- allocation: the joint-fit band ------------------------------------------


def _plan(tmp_path: Path) -> ChainPlan:
    translator = StubChainTranslator(tmp_path, "[]")
    translator.translation_config.lang_out = "en"
    return ChainPlan(translator)


def _member(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        style=SimpleNamespace(font_size=30.0),
        page_index=index,
        source_ref=f"p{index + 2}#0",
    )


def _fake_measure_factory(char_width: float = 6.0):
    """Capacity is the slot width over the scaled character width."""

    def factory(style_of):
        def measure(text, member, slot, order, ranges=(), floor=None):
            _style, scale = style_of(member)
            box = tuple(float(value) for value in slot.box)
            capacity = int((box[2] - box[0]) / (char_width * scale))
            consumed = min(len(text), capacity)
            return SimpleNamespace(
                status="fit_all" if consumed == len(text) else "fit_prefix",
                consumed_range=(0, consumed),
            )

        return measure

    return factory


def test_joint_fit_finds_a_word_boundary_cut_at_one_common_scale(tmp_path):
    plan = _plan(tmp_path)
    translated = "Indigenous knowledge in context"
    merge = backfill.merge_chain_text(["土著知识", "背景下"], plan.config)
    members = [_member(0), _member(1)]
    slots = (
        SimpleNamespace(box=(0.0, 0.0, 120.0, 15.0)),
        SimpleNamespace(box=(0.0, 0.0, 66.0, 15.0)),
    )
    probe: dict = {}

    fitted = plan._attempt_joint_fit(
        merge,
        translated,
        members,
        slots,
        (),
        _fake_measure_factory(),
        0.5,
        probe=probe,
    )

    assert fitted is not None
    split, _measure, _style_of = fitted
    cut = probe["cut"]
    # 切点在词边界
    assert translated[cut - 1].isspace() and not translated[cut].isspace()
    # 两段拼回逐字节一致(守恒)
    assert "".join(segment.text for segment in split.segments) == translated
    # 公共 scale 在 title 最小值与政策字号之间,并被记录
    assert 0.5 <= probe["common_scale"] <= 1.0
    # 两段各自入各框:按假测量模型逐段复核
    factory = _fake_measure_factory()
    style_of = _style_of
    measure = factory(style_of)
    for order, (member, slot, segment) in enumerate(
        zip(members, slots, split.segments, strict=True)
    ):
        result = measure(segment.text, member, slot, order)
        assert result.consumed_range[1] == len(segment.text)


def test_joint_fit_refuses_when_the_band_is_infeasible_at_minimum_scale(
    tmp_path,
):
    plan = _plan(tmp_path)
    translated = "an extremely long title that no band this small could hold"
    merge = backfill.merge_chain_text(["甲", "乙"], plan.config)
    members = [_member(0), _member(1)]
    slots = (
        SimpleNamespace(box=(0.0, 0.0, 24.0, 15.0)),
        SimpleNamespace(box=(0.0, 0.0, 12.0, 15.0)),
    )
    probe: dict = {}

    fitted = plan._attempt_joint_fit(
        merge,
        translated,
        members,
        slots,
        (),
        _fake_measure_factory(),
        0.5,
        probe=probe,
    )

    assert fitted is None
    assert probe["reason"] == "infeasible_at_minimum_scale"


def test_joint_fit_is_recorded_as_its_own_strategy_name():
    assert STRATEGY_JOINT_FIT == "joint_fit"


# --- render: both chain members at one common scale ---------------------------


class RenderFont(FixedWidthFont):
    @staticmethod
    def has_glyph(_codepoint: int) -> int:
        return 1


class RenderMapper(FixedWidthMapper):
    def __init__(self) -> None:
        self.base_font = RenderFont()
        self.fontid2font = {self.base_font.font_id: self.base_font}


class Config:
    def __init__(self, work: Path, target: str) -> None:
        self.work = work
        self.lang_out = target
        self.magazine_title_typeset = True
        self.progress_monitor = None
        self.watermark_output_mode = None

    def get_working_file_path(self, name: str):
        self.work.mkdir(parents=True, exist_ok=True)
        return self.work / name

    @staticmethod
    def raise_if_cancelled() -> None:
        return None


def test_cross_page_chain_members_render_at_one_common_scale(
    monkeypatch, tmp_path
):
    runtime_chain_id = "runtime-joint-scale"
    boxes = ((5.0, 50.0, 95.0, 65.0), (5.0, 50.0, 95.0, 65.0))
    # 成员二的份额远长于成员一:各搜各的 scale 时两者不同。
    fragments = ("跨頁標題", "完成部分" * 6)
    paragraphs = [
        _paragraph(
            fragment,
            f"joint-scale-{index}",
            box,
            label="title",
            chain_id=runtime_chain_id,
            chain_index=index,
        )
        for index, (fragment, box) in enumerate(zip(fragments, boxes, strict=True))
    ]
    for paragraph in paragraphs:
        paragraph.xobj_id = -1
    document = il_version_1.Document(
        page=[_page(0, [paragraphs[0]]), _page(1, [paragraphs[1]])],
        total_pages=2,
    )
    elements = tuple(
        SourceElementRef(
            source_ref=f"p{index + 1}#0",
            page=index + 1,
            column=0,
            reading_order=index,
            role="title",
            source_box=boxes[index],
            source_text_hash=_sha256(paragraph.unicode),
            style_hash=f"style-{index}",
        )
        for index, paragraph in enumerate(paragraphs)
    )
    article = ArticleIR(
        article_id="article-joint-scale",
        pages=(1, 2),
        elements=elements,
        slots=(),
        chain_ids=("canonical-joint-scale",),
        policy_evidence=(),
    )
    refs = tuple(item.source_ref for item in elements)
    article_ir = ArticleDocumentIR(
        articles=(article,),
        by_page={1: article.article_id, 2: article.article_id},
        by_element=dict.fromkeys(refs, article.article_id),
        by_chain={"canonical-joint-scale": article.article_id},
        by_chain_member=dict.fromkeys(refs, "canonical-joint-scale"),
    )
    config = Config(tmp_path, "zh")
    typesetter = Typesetting(config, RenderMapper())
    whole = "".join(fragments)
    (tmp_path / title_typeset.CHAIN_REPORT_NAME).write_text(
        json.dumps(
            {
                "chains": [
                    {
                        "chain_id": runtime_chain_id,
                        "canonical_chain_id": "canonical-joint-scale",
                        "pair_class": "title",
                        "outcome": "joint_success",
                        "runtime_source_refs": list(refs),
                        "translation": whole,
                        "ordered_fragments": list(fragments),
                        "whole_target_sha256": _sha256(whole),
                        "source_boxes": [list(box) for box in boxes],
                        "boundary_kinds": ["page"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)

    title_typeset.prepare(config, document, article_ir, typesetter)
    for page in document.page:
        typesetter.render_page(page)
    report = title_typeset.apply(config, document, typesetter)

    rows = report["titles"]
    assert report["status"] == "success"
    assert len(rows) == 2
    scales = [row["scale"] for row in rows]
    assert scales[0] == scales[1]
    for row in rows:
        assert row["joint_fit"]["common_scale"] == scales[0]
        assert row["joint_fit"]["member_refs"] == list(refs)
        assert row["joint_fit"]["baseline"] == "source_top_offset"
    assert report["totals"]["joint_fit_members"] == 2
    # 文本守恒:成员并集与联译逐字节一致
    assert "".join(paragraph.unicode for paragraph in paragraphs) == whole
