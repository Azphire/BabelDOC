from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
    ILTranslatorLLMOnly,
)
from babeldoc.format.pdf.document_il.midend.typesetting import BoundedTypesettingError
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.format.pdf.document_il.midend.typesetting import TypesettingUnit
from babeldoc.magazine import drop_cap_render
from babeldoc.magazine import layout_report
from babeldoc.magazine import line_split
from babeldoc.magazine import minimal_detection
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine.article_context import EMPTY_CONTEXT
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.chain_builder import ChainBuilder
from babeldoc.magazine.chain_translation import plan_chain_translation
from tests.minimal.fakes import FixedWidthFont
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import RecordingTracker
from tests.minimal.fakes import StubChainTranslator
from tools.verify_magazine_demo import VerificationError
from tools.verify_magazine_demo import _frozen_box_equal
from tools.verify_magazine_demo import verify_toc


class RenderFont(FixedWidthFont):
    @staticmethod
    def has_glyph(_codepoint: int) -> int:
        return 1


def test_frozen_truth_tolerates_only_subpoint_pdf_normalization_drift():
    frozen = [104.47, 687.9936, 448.212, 736.6976]

    assert _frozen_box_equal(frozen, [104.47, 688.2576, 448.212, 736.6976])
    assert not _frozen_box_equal(frozen, [104.47, 688.4946, 448.212, 736.6976])


def test_typesetting_removes_only_proven_text_clip_form_shadows(
    tmp_path, monkeypatch,
):
    paragraph = _paragraph(["source text"], "shadow-owner", left=50, bottom=400)
    config, document, _report = _apply(tmp_path, [paragraph])
    page = document.page[0]
    paragraph = page.pdf_paragraph[0]
    style = paragraph.pdf_style
    paragraph.unicode = "目标文本"
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    unicode=paragraph.unicode,
                    pdf_style=style,
                )
            )
        )
    ]
    shadow = il_version_1.PdfCharacter(
        char_unicode="s",
        box=il_version_1.Box(51, 401, 54, 409),
        pdf_style=style,
    )
    formula = il_version_1.PdfCharacter(
        char_unicode="x",
        box=il_version_1.Box(55, 401, 58, 409),
        pdf_style=style,
        formula_layout_id=7,
    )
    outside = il_version_1.PdfCharacter(
        char_unicode="z",
        box=il_version_1.Box(500, 500, 503, 508),
        pdf_style=style,
    )
    page.pdf_character = [shadow, formula, outside]
    clipped_box = il_version_1.Box(51, 401, 70, 409)
    clipped_raster = il_version_1.PdfForm(
        box=clipped_box,
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction="0 0 10 8 re W n",
        ),
        form_type="image",
    )
    text_clip = il_version_1.PdfForm(
        box=il_version_1.Box(51, 401, 70, 409),
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction=(
                "0 0 10 8 re W n BT /C0 1 Tf 7 Tr "
                "1 0 0 1 0 0 Tm [<0001>] TJ ET"
            ),
        ),
        form_type="image",
    )
    ordinary_overlapping_image = il_version_1.PdfForm(
        box=il_version_1.Box(72, 401, 90, 409),
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction="0 0 18 8 re W n",
        ),
        form_type="image",
    )
    lone_text_clip = il_version_1.PdfForm(
        box=il_version_1.Box(92, 401, 104, 409),
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction=(
                "BT /C0 1 Tf 7 Tr 1 0 0 1 0 0 Tm [<0003>] TJ ET"
            ),
        ),
        form_type="image",
    )
    outside_raster = il_version_1.PdfForm(
        box=il_version_1.Box(500, 500, 520, 510),
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction="0 0 20 10 re W n",
        ),
        form_type="image",
    )
    outside_text_clip = il_version_1.PdfForm(
        box=il_version_1.Box(500, 500, 520, 510),
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction=(
                "BT /C0 1 Tf 7 Tr 1 0 0 1 0 0 Tm [<0002>] TJ ET"
            ),
        ),
        form_type="image",
    )
    page.pdf_form = [
        clipped_raster,
        text_clip,
        ordinary_overlapping_image,
        lone_text_clip,
        outside_raster,
        outside_text_clip,
    ]

    layout_report.prepare(
        config,
        document,
        ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={}),
        article_flow_report={"article_flow_applied": False},
        eligible_roles=(),
    )
    # The formal layout registry is the authoritative translated-owner proof.
    # A later source-unit registry reset must not resurrect page-level source ink.
    monkeypatch.setattr(line_split, "source_unit", lambda *_args: None)
    try:
        Typesetting(
            SimpleNamespace(lang_out="zh"), RenderMapper()
        )._remove_translated_source_shadows(page)
    finally:
        layout_report.discard()

    # Page-level characters were not the real Aramco residue layer.  Do not
    # broadly delete them merely because they overlap a translated holder.
    assert page.pdf_character == [shadow, formula, outside]
    assert page.pdf_form == [
        ordinary_overlapping_image,
        lone_text_clip,
        outside_raster,
        outside_text_clip,
    ]


class RenderMapper(FixedWidthMapper):
    def __init__(self):
        self.base_font = RenderFont()
        self.fontid2font = {self.base_font.font_id: self.base_font}


class Config:
    def __init__(self, work: Path):
        self.working_dir = work
        self.input_file = str(work / "synthetic.pdf")
        self.magazine_page_classify = True
        self.magazine_line_structure = True
        self.magazine_chain_detect = True
        self.min_text_length = 1
        self.split_strategy = None

    def get_working_file_path(self, name: str) -> str:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return str(self.working_dir / name)


def _paragraph(
    lines: list[str],
    debug_id: str,
    *,
    left: float,
    bottom: float,
    faces: list[str] | None = None,
    char_width: float = 3.0,
) -> il_version_1.PdfParagraph:
    faces = faces or ["body"] * len(lines)
    assert len(faces) == len(lines)
    characters = []
    for row, (text, face) in enumerate(zip(lines, faces, strict=True)):
        y = bottom + (len(lines) - row - 1) * 14.0
        style = il_version_1.PdfStyle(font_id=face, font_size=10.0)
        for column, character in enumerate(text):
            characters.append(
                il_version_1.PdfCharacter(
                    char_unicode=character,
                    box=il_version_1.Box(
                        left + column * char_width,
                        y,
                        left + (column + 1) * char_width,
                        y + 10.0,
                    ),
                    pdf_style=style,
                )
            )
    text = "".join(lines)
    width = max((len(line) for line in lines), default=1) * char_width
    style = il_version_1.PdfStyle(font_id=faces[0], font_size=10.0)
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(
            left,
            bottom,
            left + width,
            bottom + max(10.0, (len(lines) - 1) * 14.0 + 10.0),
        ),
        pdf_style=style,
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    pdf_style=style,
                    pdf_character=characters,
                )
            )
        ],
        unicode=text,
        debug_id=debug_id,
        layout_label="plain text",
        xobj_id=-1,
    )


def _page(paragraphs, *, number: int = 0, kind: str = "toc"):
    frame = il_version_1.Box(0.0, 0.0, 600.0, 700.0)
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=frame),
        cropbox=il_version_1.Cropbox(box=frame),
        pdf_font=[
            il_version_1.PdfFont(font_id="body", name="Test-Regular"),
            il_version_1.PdfFont(font_id="title", name="Test-Bold"),
            il_version_1.PdfFont(font_id="byline", name="Test-Italic"),
        ],
        pdf_paragraph=list(paragraphs),
        base_operations=il_version_1.BaseOperations(value=""),
        page_number=number,
        page_kind=kind,
        page_kind_conf=1.0,
        unit="point",
    )


def _apply(tmp_path: Path, paragraphs):
    config = Config(tmp_path)
    page = _page(paragraphs)
    document = il_version_1.Document(page=[page], total_pages=1)
    before = "".join(
        character.char_unicode or ""
        for paragraph in page.pdf_paragraph
        for character in line_split.paragraph_characters(paragraph)
    )
    report = line_split.apply(config, [(1, page)])
    after = "".join(
        character.char_unicode or ""
        for paragraph in page.pdf_paragraph
        for character in line_split.paragraph_characters(paragraph)
    )
    assert before == after
    return config, document, report


@pytest.mark.parametrize(
    ("title", "byline"),
    (
        ("Feature title ........ 12", "By Ada Example"),
        ("专题标题…………12", "作者：示例"),
    ),
)
def test_title_folio_and_byline_are_two_bilingual_single_items(
    tmp_path, title, byline
):
    _config, document, report = _apply(
        tmp_path,
        [
            _paragraph(
                [title, byline],
                "title-byline",
                left=50.0,
                bottom=500.0,
                faces=["title", "byline"],
            )
        ],
    )
    assert [paragraph.unicode for paragraph in document.page[0].pdf_paragraph] == [
        title,
        byline,
    ]
    children = report["source_units"][0]["ordered_children"]
    assert [child["record_kind"] for child in children] == [
        line_split.RECORD_SINGLE,
        line_split.RECORD_SINGLE,
    ]
    assert [child["child_order"] for child in children] == [0, 1]
    assert len({child["source_ref"] for child in children}) == 2


def test_adjacent_singles_stay_separate_and_uniform_block_and_prose_stay_whole(
    tmp_path,
):
    single_a = _paragraph(["First ........ 4"], "single-a", left=50, bottom=620)
    single_b = _paragraph(["Second ....... 8"], "single-b", left=50, bottom=590)
    block = _paragraph(
        ["A uniform block title", "continues on its second line"],
        "block",
        left=50,
        bottom=500,
    )
    prose = _paragraph(
        ["中文长段落" * 5] * 6,
        "editorial",
        left=340,
        bottom=450,
    )
    _config, document, report = _apply(
        tmp_path, [single_a, single_b, block, prose]
    )

    assert document.page[0].pdf_paragraph == [single_a, single_b, block, prose]
    kinds = {
        unit["debug_id"]: unit["record_kind"] for unit in report["source_units"]
    }
    assert kinds == {
        "single-a": line_split.RECORD_SINGLE,
        "single-b": line_split.RECORD_SINGLE,
        "block": line_split.RECORD_BLOCK,
        "editorial": line_split.RECORD_PROSE,
    }
    config = line_split.load_line_split_config()
    assert line_split.examine(block, config).reason == (
        line_split.REASON_UNIFORM_STYLING
    )
    assert line_split.examine(prose, config).reason == (
        line_split.REASON_UNIFORM_STYLING
    )
    assert len({unit["source_ref"] for unit in report["source_units"]}) == 4
    assert all(len(unit["source_text_sha256"]) == 64 for unit in report["source_units"])


def test_non_record_page_registers_only_long_prose_without_splitting(tmp_path):
    ordinary = _paragraph(
        ["An ordinary body paragraph."],
        "ordinary-body",
        left=50,
        bottom=620,
    )
    prose = _paragraph(
        ["中文长段落" * 5] * 6,
        "editorial-prose",
        left=50,
        bottom=500,
    )
    page = _page([ordinary, prose], number=2, kind="editorial")
    document = il_version_1.Document(page=[page], total_pages=1)
    config = Config(tmp_path)

    report = line_split.apply(
        config,
        [(3, page)],
        policy_of=lambda _kind: {"preserve_line_structure": False},
    )

    assert document.page[0].pdf_paragraph == [ordinary, prose]
    assert report["pages"][0]["declared"] is False
    assert report["pages"][0]["split_paragraphs"] == 0
    assert report["pages"][0]["exempt_paragraphs"] == 1
    assert report["pages"][0]["source_characters_sha256"] == (
        report["pages"][0]["result_characters_sha256"]
    )
    assert line_split.source_unit(ordinary, 3) is None
    held = line_split.source_unit(prose, 3)
    assert held is not None
    assert held.parent_ref == "p3#1"
    assert held.record_kind == line_split.RECORD_PROSE
    assert not line_split.excludes_chain_endpoint(prose, 3)
    assert [
        (unit["parent_ref"], unit["record_kind"])
        for unit in report["source_units"]
    ] == [("p3#1", line_split.RECORD_PROSE)]

    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    expectations = tmp_path / "editorial-expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": "editorial-prose",
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "direction": "zh-en",
                "toc_records": [
                    {
                        "anchor": "p3#1",
                        "kind": line_split.RECORD_PROSE,
                        "source_box": report["source_units"][0]["source_band"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert verify_toc(
        expectations,
        source,
        output,
        tmp_path,
        "zh",
        "en",
    )["status"] == "pass"


def test_ruling_owner_resolves_untouched_body_beside_units_but_not_split_parent(
    tmp_path,
):
    registered_prose = _paragraph(
        ["中文长段落" * 5] * 6,
        "registered-prose",
        left=50,
        bottom=500,
    )
    untouched_body = _paragraph(
        ["O n the river, an ordinary opening paragraph continues."],
        "dropcap-body",
        left=330,
        bottom=500,
        faces=["body"],
    )
    page = _page(
        [registered_prose, untouched_body],
        number=4,
        kind="article_opener",
    )
    config = Config(tmp_path / "untouched")
    report = line_split.apply(
        config,
        [(5, page)],
        policy_of=lambda _kind: {"preserve_line_structure": False},
    )

    assert [unit["parent_ref"] for unit in report["source_units"]] == [
        "p5#0"
    ]
    assert line_split.source_unit(untouched_body, 5) is None
    assert line_split.resolve_parent_index(page, 5, "p5#1") == 1

    split_parent = _paragraph(
        ["Contents ........ 2", "By Example"],
        "split-owner",
        left=50,
        bottom=400,
        faces=["title", "byline"],
    )
    _split_config, split_document, split_report = _apply(
        tmp_path / "split",
        [split_parent],
    )
    assert len(split_report["source_units"]) == 2
    assert split_report["source_units"][0]["parent_ref"] == "p1#0"
    assert split_report["source_units"][1]["parent_ref"] == "p1#0"
    assert (
        line_split.resolve_parent_index(
            split_document.page[0],
            1,
            "p1#0",
        )
        is None
    )


def test_long_uniform_horizontal_prose_does_not_capture_vertical_furniture(
    tmp_path,
):
    prose = _paragraph(
        ["中文长段落" * 5] * 6,
        "horizontal-prose",
        left=50,
        bottom=500,
    )
    vertical = _paragraph(
        ["v" * 25] * 3,
        "vertical-furniture",
        left=350,
        bottom=500,
        char_width=0.1,
    )

    _config, document, report = _apply(tmp_path, [prose, vertical])

    assert document.page[0].pdf_paragraph == [prose, vertical]
    config = line_split.load_line_split_config()
    vertical_examination = line_split.examine(vertical, config)
    assert vertical_examination.reason == line_split.REASON_UNIFORM_STYLING
    assert len(vertical_examination.lines) == 3
    assert len(vertical.unicode) > config.max_line_chars
    assert {
        unit["debug_id"]: unit["record_kind"]
        for unit in report["source_units"]
    } == {
        "horizontal-prose": line_split.RECORD_PROSE,
        "vertical-furniture": line_split.RECORD_BLOCK,
    }


def test_long_body_with_one_fallback_glyph_stays_one_prose_unit(tmp_path):
    body = _paragraph(
        [
            "原子能机构总部设在维也纳国际中心。外地和联络办事",
            "处设在日内瓦、纽约、东京和多伦多。原子能机构在摩纳哥、塞",
            "伯斯多夫和维也纳运营着科学实验室。此外，原子能机构还向",
            "设在意大利的里雅斯特的阿布杜斯·萨拉姆国际理论物理中",
            "心提供支持和资金。",
        ],
        "body-with-fallback",
        left=290.387,
        bottom=90.535,
        faces=["body"] * 5,
        char_width=3.0,
    )
    fallback = il_version_1.PdfStyle(font_id="fallback", font_size=10.0)
    middle_dot = next(
        character
        for character in line_split.paragraph_characters(body)
        if character.char_unicode == "·"
    )
    middle_dot.pdf_style = fallback

    toc_record = _paragraph(
        ["Feature title", "By Example", "Next record"],
        "styled-toc-records",
        left=50,
        bottom=600,
        faces=["title", "byline", "title"],
    )
    uniform_block = _paragraph(
        ["Short uniform", "three line", "record block"],
        "short-uniform-block",
        left=180,
        bottom=450,
        faces=["body"] * 3,
    )
    config = line_split.load_line_split_config()

    body_examination = line_split.examine(body, config)
    toc_examination = line_split.examine(toc_record, config)
    block_examination = line_split.examine(uniform_block, config)

    assert len(body_examination.lines) == 5
    assert body_examination.mean_line_chars == 22.8
    assert body_examination.heterogeneous is False
    assert body_examination.reason == line_split.REASON_UNIFORM_STYLING
    assert toc_examination.heterogeneous is True
    assert toc_examination.admitted
    assert block_examination.reason == line_split.REASON_UNIFORM_STYLING
    assert not line_split._is_prose_exempt(uniform_block, block_examination, config)

    _config, document, report = _apply(
        tmp_path,
        [body, toc_record, uniform_block],
    )

    units_by_parent = {}
    for unit in report["source_units"]:
        units_by_parent.setdefault(unit["parent_ref"], []).append(unit)
    assert document.page[0].pdf_paragraph[0] is body
    assert [(unit["record_kind"], unit["debug_id"]) for unit in units_by_parent["p1#0"]] == [
        (line_split.RECORD_PROSE, "body-with-fallback")
    ]
    assert [unit["record_kind"] for unit in units_by_parent["p1#1"]] == [
        line_split.RECORD_SINGLE,
        line_split.RECORD_SINGLE,
        line_split.RECORD_SINGLE,
    ]
    assert [(unit["record_kind"], unit["debug_id"]) for unit in units_by_parent["p1#2"]] == [
        (line_split.RECORD_BLOCK, "short-uniform-block")
    ]
    exemption = next(
        item for item in report["exemptions"] if item["paragraph"] == "p1#0"
    )
    assert exemption == {
        "page": 1,
        "paragraph": "p1#0",
        "debug_id": "body-with-fallback",
        "lines": 5,
        "mean_line_chars": 22.8,
        "heterogeneous": False,
        "reason": line_split.REASON_UNIFORM_STYLING,
    }


def test_spanning_decorative_glyph_keeps_proven_multiline_source_as_block(tmp_path):
    paragraph = _paragraph(
        ["Banjo on the Atlas", "WRITTEN BY EXAMPLE", "A descriptive deck"],
        "spanning-folio",
        left=100,
        bottom=500,
        faces=["title", "byline", "body"],
    )
    folio_style = il_version_1.PdfStyle(font_id="title", font_size=65.0)
    folio = il_version_1.PdfCharacter(
        char_unicode="8",
        box=il_version_1.Box(90.0, 500.0, 120.0, 565.0),
        pdf_style=folio_style,
    )
    paragraph.pdf_paragraph_composition.append(
        il_version_1.PdfParagraphComposition(
            pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                pdf_style=folio_style,
                pdf_character=[folio],
            )
        )
    )
    paragraph.unicode += "8"

    _config, document, report = _apply(tmp_path, [paragraph])

    assert document.page[0].pdf_paragraph == [paragraph]
    assert report["source_units"][0]["record_kind"] == line_split.RECORD_BLOCK


def test_split_aliases_are_unique_chain_uses_new_refs_and_prose_joint_succeeds(
    tmp_path,
):
    records = _paragraph(
        ["Contents ........ 2", "By Example"],
        "records",
        left=210,
        bottom=300,
        faces=["title", "byline"],
    )
    tail = _paragraph(
        [
            "the unfinished source continues through the lower body column",
            "without ending here and with enough running text to remain prose",
        ],
        "tail",
        left=40,
        bottom=30,
        char_width=2.5,
    )
    head = _paragraph(
        [
            "into the following body column where the same sentence resumes",
            "and remains a prose unit with enough running text for exemption",
        ],
        "head",
        left=330,
        bottom=630,
        char_width=2.5,
    )
    config, document, report = _apply(tmp_path, [records, head, tail])

    ChainBuilder(config).process(document)
    assert records.chain_id is None
    assert [paragraph.chain_id for paragraph in document.page[0].pdf_paragraph[:2]] == [
        None,
        None,
    ]
    assert tail.chain_id is not None and tail.chain_id == head.chain_id
    assert [tail.chain_index, head.chain_index] == [0, 1]
    assert [unit["source_ref"] for unit in report["source_units"]] == [
        "p1#0",
        "p1#1",
        "p1#2",
        "p1#3",
    ]
    assert report["source_units"][0]["parent"]["source_ref"] == "p1#0"

    translator = StubChainTranslator(
        tmp_path,
        json.dumps([{"id": 0, "output": "完整连续译文"}], ensure_ascii=False),
    )
    empty_ir = ArticleDocumentIR(
        articles=(),
        by_page={},
        by_element={},
        by_chain={},
        by_chain_member={},
        unsupported_pages=(),
    )
    plan = plan_chain_translation(
        translator,
        document,
        RecordingTracker(),
        EMPTY_CONTEXT,
        empty_ir,
    )
    assert len(plan.entries) == 1
    assert len(translator.translate_engine.llm_calls) == 1
    plan.apply()
    chain_report = json.loads(
        (tmp_path / "chain_translation.report.json").read_text(encoding="utf-8")
    )
    assert chain_report["chains"][0]["outcome"] == "joint_success"


def _target_composition(text: str):
    style = il_version_1.PdfStyle(font_id="body", font_size=10.0)
    return [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
                pdf_style=style,
                unicode=text,
            )
        )
    ]


def _union_box(boxes):
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _box_record(box):
    return [box.x, box.y, box.x2, box.y2]


@pytest.mark.parametrize(
    ("lines", "expected_kind", "target"),
    (
        (["Short item"], line_split.RECORD_SINGLE, "译文"),
        (["block first", "block second"], line_split.RECORD_BLOCK, "block target wraps"),
        (["p" * 60, "q" * 60], line_split.RECORD_PROSE, "ordinary prose target wraps"),
    ),
)
def test_three_record_kinds_render_inside_their_source_container(
    tmp_path, lines, expected_kind, target
):
    paragraph = _paragraph(lines, "bounded", left=50, bottom=400, char_width=8)
    _config, document, report = _apply(tmp_path, [paragraph])
    assert report["source_units"][0]["record_kind"] == expected_kind
    source_box = tuple(report["source_units"][0]["source_band"])
    paragraph.unicode = target
    paragraph.pdf_paragraph_composition = _target_composition(target)

    typesetter = Typesetting(SimpleNamespace(lang_out="zh"), RenderMapper())
    typesetter.render_paragraph(
        paragraph,
        document.page[0],
        {"body": RenderFont()},
    )

    assert tuple(getattr(paragraph.box, name) for name in ("x", "y", "x2", "y2")) == source_box
    rendered = [
        composition.pdf_character
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    ]
    assert "".join(character.char_unicode for character in rendered) == target
    assert all(
        source_box[0] <= character.box.x <= character.box.x2 <= source_box[2]
        and source_box[1] <= character.box.y <= character.box.y2 <= source_box[3]
        for character in rendered
    )
    if expected_kind == line_split.RECORD_SINGLE:
        assert len({round(character.box.y, 3) for character in rendered}) == 1


def test_rich_formula_single_attempts_exact_minimum_readable_scale():
    source_box = (93.6923, 126.6545, 566.9849, 142.9345)
    paragraph = _paragraph(
        ["source navigation line"],
        "minimum-scale-single",
        left=source_box[0],
        bottom=source_box[1],
    )
    paragraph.box = il_version_1.Box(*source_box)
    page = _page([paragraph], number=2)
    typesetter = Typesetting(SimpleNamespace(lang_out="zh"), RenderMapper())
    target = "2 首次预览 风味 问答 作者专栏 评论 活动 在线内容 测验"
    styles = (
        il_version_1.PdfStyle(font_id="body", font_size=10.0),
        il_version_1.PdfStyle(font_id="title", font_size=10.0),
    )
    units = [
        TypesettingUnit(
            unicode=character,
            font=typesetter.font_mapper.base_font,
            font_size=10.0,
            style=styles[index % len(styles)],
            xobj_id=-1,
        )
        for index, character in enumerate(target)
    ]
    rich_width = sum(unit.width for unit in units)
    required_width = 900.0
    formula_width = required_width - rich_width
    formula_box = il_version_1.Box(0.0, 0.0, formula_width, 10.0)
    formula_character = il_version_1.PdfCharacter(
        char_unicode="|",
        box=formula_box,
        visual_bbox=il_version_1.VisualBbox(box=formula_box),
        pdf_style=styles[0],
        advance=formula_width,
        xobj_id=-1,
    )
    units.insert(
        len(units) // 2,
        TypesettingUnit(
            formular=il_version_1.PdfFormula(
                box=formula_box,
                pdf_character=[formula_character],
                x_offset=0.0,
                y_offset=0.0,
                x_advance=formula_width,
            )
        ),
    )
    available_width = source_box[2] - source_box[0]
    assert sum(unit.width for unit in units) == pytest.approx(required_width)
    assert required_width * 0.5 < available_width < required_width * 0.55

    typesetter.retypeset_bounded_source_unit(
        paragraph,
        page,
        units,
        SimpleNamespace(
            source_box=source_box,
            source_ref="p3#16",
            record_kind=line_split.RECORD_SINGLE,
        ),
    )

    assert paragraph.scale == pytest.approx(0.5)
    rendered = [
        composition.pdf_character
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    ]
    assert len({round(character.box.y, 3) for character in rendered}) == 1
    assert all(
        source_box[0] <= character.box.x <= character.box.x2 <= source_box[2]
        for character in rendered
    )


def test_formula_baseline_offset_does_not_create_a_false_layout_line():
    source_box = (93.6923, 126.6545, 566.9849, 142.9345)
    paragraph = _paragraph(
        ["source navigation line"],
        "formula-baseline-single",
        left=source_box[0],
        bottom=source_box[1],
    )
    paragraph.box = il_version_1.Box(*source_box)
    paragraph.first_line_indent = False
    page = _page([paragraph], number=2)
    typesetter = Typesetting(SimpleNamespace(lang_out="zh"), RenderMapper())
    body_style = il_version_1.PdfStyle(font_id="body", font_size=10.0)
    folio_style = il_version_1.PdfStyle(font_id="title", font_size=14.0)
    chunks = (
        ("2 ", folio_style),
        ("首次预览", body_style),
        ("风味 ", body_style),
        ("问答 ", body_style),
        ("作者专栏 ", body_style),
        ("评论 ", body_style),
        ("活动 ", body_style),
        ("在线内容 ", body_style),
        ("测验", body_style),
    )
    formula_widths = (13.3636, 13.8117, 20.5456, 21.2877, 19.9016, 20.3706, 20.1537)
    units = []
    for index, (text, style) in enumerate(chunks):
        units.extend(
            TypesettingUnit(
                unicode=character,
                font=typesetter.font_mapper.base_font,
                font_size=style.font_size,
                style=style,
                xobj_id=-1,
            )
            for character in text
        )
        if index >= len(formula_widths):
            continue
        width = formula_widths[index]
        formula_box = il_version_1.Box(0.0, 0.0, width, 10.2)
        formula_character = il_version_1.PdfCharacter(
            char_unicode="|",
            box=formula_box,
            visual_bbox=il_version_1.VisualBbox(box=formula_box),
            pdf_style=body_style,
            advance=width,
            xobj_id=-1,
        )
        units.append(
            TypesettingUnit(
                formular=il_version_1.PdfFormula(
                    box=formula_box,
                    pdf_character=[formula_character],
                    x_offset=3.65,
                    y_offset=-1.008,
                    x_advance=0.0,
                )
            )
        )

    assert sum(unit.width for unit in units) < source_box[2] - source_box[0]
    typesetter.retypeset_bounded_source_unit(
        paragraph,
        page,
        units,
        SimpleNamespace(
            source_box=source_box,
            source_ref="p3#16",
            record_kind=line_split.RECORD_SINGLE,
        ),
    )

    assert paragraph.scale == pytest.approx(1.0)
    rendered = [
        composition.pdf_character
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    ]
    # Formula glyphs retain their intentional baseline offset, while the line
    # packer records that no wrap occurred.
    assert len({round(character.box.y, 3) for character in rendered}) > 1
    assert all(
        source_box[0] <= character.box.x <= character.box.x2 <= source_box[2]
        and source_box[1]
        <= character.box.y
        <= character.box.y2
        <= source_box[3]
        for character in rendered
    )


def test_single_visual_line_still_rejects_a_real_packer_wrap():
    source_box = (0.0, 0.0, 100.0, 100.0)
    paragraph = _paragraph(
        ["source"],
        "real-wrap-single",
        left=source_box[0],
        bottom=source_box[1],
    )
    paragraph.box = il_version_1.Box(*source_box)
    paragraph.first_line_indent = False
    page = _page([paragraph])
    typesetter = Typesetting(SimpleNamespace(lang_out="zh"), RenderMapper())
    style = il_version_1.PdfStyle(font_id="body", font_size=10.0)
    units = [
        TypesettingUnit(
            unicode="译",
            font=typesetter.font_mapper.base_font,
            font_size=10.0,
            style=style,
            xobj_id=-1,
        )
        for _index in range(50)
    ]

    # Height is ample, so the only violated contract is the real second line.
    with pytest.raises(BoundedTypesettingError, match="does not fit"):
        typesetter.retypeset_bounded_source_unit(
            paragraph,
            page,
            units,
            SimpleNamespace(
                source_box=source_box,
                source_ref="p1#0",
                record_kind=line_split.RECORD_SINGLE,
            ),
        )


def test_bounded_overflow_fails_without_text_loss_or_container_borrowing(tmp_path):
    paragraph = _paragraph(["tiny"], "overflow", left=50, bottom=400, char_width=5)
    _config, document, report = _apply(tmp_path, [paragraph])
    source_box = tuple(report["source_units"][0]["source_band"])
    target = "target text that cannot possibly fit one tiny source band"
    paragraph.unicode = target
    original = _target_composition(target)
    paragraph.pdf_paragraph_composition = original
    typesetter = Typesetting(SimpleNamespace(lang_out="en"), RenderMapper())

    with pytest.raises(BoundedTypesettingError, match="does not fit"):
        typesetter.render_paragraph(
            paragraph,
            document.page[0],
            {"body": RenderFont()},
        )

    assert paragraph.pdf_paragraph_composition is original
    assert paragraph.pdf_paragraph_composition[0].pdf_same_style_unicode_characters.unicode == target
    assert tuple(getattr(paragraph.box, name) for name in ("x", "y", "x2", "y2")) == source_box


def test_pipeline_orders_line_split_between_hitl_and_chain(monkeypatch, tmp_path):
    events = []
    empty_ir = ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={})

    class Classifier:
        vlm_enabled = False

        def __init__(self, _config):
            pass

        def process(self, docs):
            events.append("classifier")
            return docs

    class Builder:
        def __init__(self, _config):
            pass

        def process(self, docs):
            events.append("chain")
            return docs

    class Articles:
        def __init__(self, _config):
            pass

        def process(self, _docs):
            events.append("article")
            return empty_ir

    monkeypatch.setattr(minimal_pipeline, "PageClassifier", Classifier)
    monkeypatch.setattr(minimal_pipeline, "ChainBuilder", Builder)
    monkeypatch.setattr(minimal_pipeline, "ArticleBuilder", Articles)
    monkeypatch.setattr(minimal_pipeline.hitl, "begin_run", lambda *_args: object())
    monkeypatch.setattr(
        minimal_pipeline.hitl,
        "page_kind_pass",
        lambda *_args: events.append("hitl"),
    )
    monkeypatch.setattr(
        minimal_pipeline.hitl,
        "labeled_pages",
        lambda _docs: [],
    )
    monkeypatch.setattr(
        minimal_pipeline.line_split,
        "apply",
        lambda *_args: events.append("line_split"),
    )
    config = Config(tmp_path)
    minimal_pipeline.configure(config)
    minimal_pipeline.after_styles(
        config,
        il_version_1.Document(page=[], total_pages=0),
    )
    assert events == ["classifier", "hitl", "line_split", "chain", "article"]


def test_toc_verifier_checks_direction_alias_kind_container_and_conservation(tmp_path):
    paragraph = _paragraph(["Record ........ 9"], "truth", left=50, bottom=400)
    _config, _document, report = _apply(tmp_path, [paragraph])
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": "synthetic",
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "direction": "en-zh",
                "toc_records": [
                    {
                        "anchor": "p1#0",
                        "kind": line_split.RECORD_SINGLE,
                        "source_box": report["source_units"][0]["source_band"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert verify_toc(
        expectations, source, output, tmp_path, "en", "zh"
    )["status"] == "pass"

    damaged = json.loads((tmp_path / line_split.REPORT_NAME).read_text(encoding="utf-8"))
    damaged["pages"][0]["characters_after"] += 1
    (tmp_path / line_split.REPORT_NAME).write_text(
        json.dumps(damaged), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="character count changed"):
        verify_toc(expectations, source, output, tmp_path, "en", "zh")


def test_toc_verifier_accepts_frozen_parent_children_and_multi_anchor_semantics(
    tmp_path,
):
    block = _paragraph(
        ["How a long feature title", "continues as one uniform block"],
        "block-parent",
        left=80,
        bottom=550,
    )
    folio = _paragraph(["4"], "folio-parent", left=45, bottom=600, char_width=12)
    split = _paragraph(
        ["Exile through a child’s eyes ........ 26", "Photos: Example"],
        "single-parent",
        left=80,
        bottom=300,
        faces=["title", "byline"],
    )
    prose = _paragraph(
        ["p" * 60, "q" * 60],
        "prose-parent",
        left=330,
        bottom=500,
    )
    _config, _document, report = _apply(tmp_path, [block, folio, split, prose])
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    parent_by_ref = {
        unit["parent_ref"]: unit["parent"] for unit in report["source_units"]
    }
    expectations = tmp_path / "frozen-shape.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": "frozen-shape",
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "direction": "en-zh",
                "toc_records": [
                    {
                        "anchor": ["p1#0", "p1#1"],
                        "kind": line_split.RECORD_BLOCK,
                        "source_box": _union_box(
                            [
                                parent_by_ref["p1#0"]["source_box"],
                                parent_by_ref["p1#1"]["source_box"],
                            ]
                        ),
                    },
                    {
                        "anchor": "p1#2",
                        "kind": line_split.RECORD_SINGLE,
                        "source_box": parent_by_ref["p1#2"]["source_box"],
                    },
                    {
                        "anchor": "p1#3",
                        "kind": line_split.RECORD_PROSE,
                        "source_box": parent_by_ref["p1#3"]["source_box"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = verify_toc(expectations, source, output, tmp_path, "en", "zh")
    assert result == {
        "check": "toc",
        "sample_id": "frozen-shape",
        "records": 3,
        "status": "pass",
    }

    damaged = json.loads((tmp_path / line_split.REPORT_NAME).read_text(encoding="utf-8"))
    damaged["source_units"][0]["source_band"][2] += 100
    (tmp_path / line_split.REPORT_NAME).write_text(
        json.dumps(damaged), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="flat child audit disagrees"):
        verify_toc(expectations, source, output, tmp_path, "en", "zh")


def test_visual_parent_groups_are_one_translation_item_without_merging_records(
    tmp_path,
):
    bull_title = _paragraph(
        ["8 Future foundations"],
        "bull-title",
        left=257,
        bottom=522,
    )
    bull_subtitle = _paragraph(
        ["Graduate reflections"],
        "bull-subtitle",
        left=274,
        bottom=506,
    )
    independent = _paragraph(
        ["10 Independent record"],
        "independent",
        left=257,
        bottom=470,
    )
    fd_single_folio = _paragraph(
        ["50"],
        "fd-single-folio",
        left=388,
        bottom=430,
    )
    fd_single_title = _paragraph(
        ["How Much Does the World Work?"],
        "fd-single-title",
        left=388,
        bottom=416,
    )
    fd_block_folio = _paragraph(
        ["20"],
        "fd-block-folio",
        left=48,
        bottom=360,
    )
    fd_block_title = _paragraph(
        ["Understanding", "Geoeconomics"],
        "fd-block-title",
        left=48,
        bottom=335,
        faces=["title", "title"],
    )
    fd_block_subtitle = _paragraph(
        ["How new tools explain power", "Authors remain with the subtitle"],
        "fd-block-subtitle",
        left=48,
        bottom=304,
        # The real FD fixture changes face within this visual subtitle.  It is
        # split first, then must be coalesced with the tight title as one block.
        faces=["body", "title"],
    )
    paragraphs = [
        bull_title,
        bull_subtitle,
        independent,
        fd_single_folio,
        fd_single_title,
        fd_block_folio,
        fd_block_title,
        fd_block_subtitle,
    ]
    expected_boxes = {
        "bull": _union_box(
            [_box_record(bull_title.box), _box_record(bull_subtitle.box)]
        ),
        "independent": _box_record(independent.box),
        "fd_single": _union_box(
            [_box_record(fd_single_folio.box), _box_record(fd_single_title.box)]
        ),
        "fd_block": _union_box(
            [
                _box_record(fd_block_folio.box),
                _box_record(fd_block_title.box),
                _box_record(fd_block_subtitle.box),
            ]
        ),
    }

    _config, document, report = _apply(tmp_path, paragraphs)
    group_by_parent = {
        parent["source_ref"]: unit
        for unit in report["source_units"]
        for parent in unit["source_parents"]
    }
    assert group_by_parent["p1#0"] is group_by_parent["p1#1"]
    assert group_by_parent["p1#0"]["parent_refs"] == ["p1#0", "p1#1"]
    assert group_by_parent["p1#0"]["record_kind"] == line_split.RECORD_BLOCK
    assert document.page[0].pdf_paragraph[0].unicode == (
        "8 Future foundations\nGraduate reflections"
    )
    assert line_split.characters_text(
        line_split.paragraph_characters(document.page[0].pdf_paragraph[0])
    ) == "8 Future foundationsGraduate reflections"
    assert line_split.resolve_parent_index(document.page[0], 1, "p1#0") == 0
    assert line_split.resolve_parent_index(document.page[0], 1, "p1#1") == 0
    assert line_split.excludes_chain_endpoint(
        document.page[0].pdf_paragraph[0],
        1,
    )
    assert group_by_parent["p1#2"]["parent_refs"] == ["p1#2"]
    assert group_by_parent["p1#3"]["fixed_companion"] is True
    folio_index = int(group_by_parent["p1#3"]["source_ref"].split("#")[1])
    fixed_folio = document.page[0].pdf_paragraph[folio_index]
    assert fixed_folio.unicode is None
    assert line_split.characters_text(
        line_split.paragraph_characters(fixed_folio)
    ) == "50"
    driver = object.__new__(ILTranslatorLLMOnly)
    driver.translation_config = SimpleNamespace(min_text_length=1)
    assert not driver._should_translate_paragraph(fixed_folio)
    assert group_by_parent["p1#4"]["record_kind"] == line_split.RECORD_SINGLE
    assert group_by_parent["p1#6"] is group_by_parent["p1#7"]
    assert group_by_parent["p1#6"]["record_kind"] == line_split.RECORD_BLOCK
    assert len(document.page[0].pdf_paragraph) == len(paragraphs) - 2

    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    expectations = tmp_path / "visual-groups.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": "visual-groups",
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "direction": "en-zh",
                "toc_records": [
                    {
                        "anchor": ["p1#0", "p1#1"],
                        "kind": line_split.RECORD_BLOCK,
                        "source_box": expected_boxes["bull"],
                    },
                    {
                        "anchor": "p1#2",
                        "kind": line_split.RECORD_SINGLE,
                        "source_box": expected_boxes["independent"],
                    },
                    {
                        "anchor": ["p1#3", "p1#4"],
                        "kind": line_split.RECORD_SINGLE,
                        "source_box": expected_boxes["fd_single"],
                    },
                    {
                        "anchor": ["p1#5", "p1#6", "p1#7"],
                        "kind": line_split.RECORD_BLOCK,
                        "source_box": expected_boxes["fd_block"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    assert verify_toc(
        expectations,
        source,
        output,
        tmp_path,
        "en",
        "zh",
    )["status"] == "pass"


@pytest.mark.parametrize(
    ("first_text", "second_text"),
    (
        ("8 First record", "10 Next record"),
        ("First record", "Next record"),
    ),
)
def test_tight_independent_neighbors_stay_separate(
    tmp_path,
    first_text,
    second_text,
):
    first = _paragraph(
        [first_text],
        "first-record",
        left=257,
        bottom=522,
    )
    second = _paragraph(
        [second_text],
        "next-record",
        left=274,
        bottom=506,
    )

    _config, document, report = _apply(tmp_path, [first, second])

    assert document.page[0].pdf_paragraph == [first, second]
    assert [unit["parent_refs"] for unit in report["source_units"]] == [
        ["p1#0"],
        ["p1#1"],
    ]
    assert [unit["record_kind"] for unit in report["source_units"]] == [
        line_split.RECORD_SINGLE,
        line_split.RECORD_SINGLE,
    ]


def test_short_masthead_label_and_value_form_one_readable_bounded_block(tmp_path):
    label = _paragraph(
        ["主办单位"],
        "masthead-label",
        left=36.52734375,
        bottom=549.51915,
        faces=["title"],
        char_width=8.0,
    )
    label.box = il_version_1.Box(
        36.52734375,
        549.51915,
        71.47265625,
        557.6754,
    )
    value = _paragraph(
        ["国际原子能机构新闻和宣传办公室"],
        "masthead-value",
        left=36.5625,
        bottom=534.27005625,
        faces=["body"],
        char_width=8.0,
    )
    value.box = il_version_1.Box(
        36.5625,
        534.27005625,
        170.6484375,
        542.8833375,
    )
    config = Config(tmp_path)
    config.min_text_length = 5
    page = _page([label, value], number=1, kind="masthead")
    document = il_version_1.Document(page=[page], total_pages=1)
    source_characters = "".join(
        line_split.characters_text(line_split.paragraph_characters(paragraph))
        for paragraph in page.pdf_paragraph
    )

    report = line_split.apply(config, [(2, page)])

    assert len(page.pdf_paragraph) == 1
    merged = page.pdf_paragraph[0]
    assert line_split.characters_text(
        line_split.paragraph_characters(merged)
    ) == source_characters
    assert merged.unicode == "主办单位\n国际原子能机构新闻和宣传办公室"
    assert report["source_units"][0]["parent_refs"] == ["p2#0", "p2#1"]
    assert report["source_units"][0]["record_kind"] == line_split.RECORD_BLOCK
    assert report["short_lines"] == []
    driver = object.__new__(ILTranslatorLLMOnly)
    driver.translation_config = SimpleNamespace(min_text_length=5)
    assert driver._should_translate_paragraph(merged)

    target = (
        "Organizer International Atomic Energy Agency News and Public "
        "Information Office"
    )
    merged.unicode = target
    merged.pdf_paragraph_composition = _target_composition(target)
    Typesetting(SimpleNamespace(lang_out="en"), RenderMapper()).render_paragraph(
        merged,
        document.page[0],
        {"body": RenderFont(), "title": RenderFont()},
    )

    source_box = (36.52734375, 534.27005625, 170.6484375, 557.6754)
    assert tuple(
        getattr(merged.box, name) for name in ("x", "y", "x2", "y2")
    ) == source_box
    rendered = [
        composition.pdf_character
        for composition in merged.pdf_paragraph_composition
        if composition.pdf_character is not None
    ]
    assert "".join(character.char_unicode for character in rendered) == target
    assert len({round(character.box.y, 3) for character in rendered}) > 1
    assert merged.scale >= 0.5
    assert all(
        source_box[0] <= character.box.x <= character.box.x2 <= source_box[2]
        and source_box[1] <= character.box.y <= character.box.y2 <= source_box[3]
        for character in rendered
    )


def test_short_label_rule_does_not_merge_a_misaligned_independent_record(tmp_path):
    label = _paragraph(
        ["Label"],
        "short-heading",
        left=50,
        bottom=522,
        faces=["title"],
    )
    independent = _paragraph(
        ["A substantially longer independent record"],
        "independent-record",
        left=60,
        bottom=506,
        faces=["body"],
    )
    config = Config(tmp_path)
    config.min_text_length = 6
    page = _page([label, independent], kind="masthead")

    report = line_split.apply(config, [(1, page)])

    assert page.pdf_paragraph == [label, independent]
    assert [unit["parent_refs"] for unit in report["source_units"]] == [
        ["p1#0"],
        ["p1#1"],
    ]


def test_unicode_only_debug_furniture_is_not_a_bounded_source_unit(tmp_path):
    style = il_version_1.PdfStyle(font_id="body", font_size=4.0)
    overlay = il_version_1.PdfParagraph(
        box=il_version_1.Box(49.0, 309.89225, 59.0, 310.0),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=style,
                    unicode="abandon",
                    debug_info=True,
                )
            )
        ],
        unicode="abandon",
        xobj_id=-1,
    )
    _config, document, report = _apply(tmp_path, [overlay])
    assert report["source_units"] == []
    assert line_split.source_unit(overlay, 1) is None
    assert document.page[0].pdf_paragraph == [overlay]


def test_nested_figure_text_is_fixed_artwork_not_a_translation_unit(tmp_path):
    publication_line = _paragraph(
        ["2020年2月 国际原子能机构旗舰出版物"],
        "nested-publication-line",
        left=105.8,
        bottom=767.0,
        char_width=1.5,
    )
    publication_line.box = il_version_1.Box(
        105.816090625,
        766.730422266,
        155.3577994,
        769.8028,
    )
    cover_title = _paragraph(
        ["核 安保"],
        "nested-cover-title",
        left=71.25,
        bottom=643.0,
        char_width=8.0,
    )
    cover_title.unicode = "核 安 保"
    cover_title.box = il_version_1.Box(
        71.248580859,
        641.161757422,
        130.835384511,
        661.0026,
    )
    for paragraph, xobj_id in ((publication_line, 7), (cover_title, 15)):
        paragraph.xobj_id = xobj_id
        for character in line_split.paragraph_characters(paragraph):
            character.xobj_id = (
                None if (character.char_unicode or "").isspace() else xobj_id
            )
    artwork = (publication_line, cover_title)
    source_characters = [
        character
        for paragraph in artwork
        for character in line_split.paragraph_characters(paragraph)
    ]
    original_character_state = [
        (
            id(character),
            character.char_unicode,
            tuple(
                getattr(character.box, name)
                for name in ("x", "y", "x2", "y2")
            ),
        )
        for character in source_characters
    ]
    caption = _paragraph(
        ["Independent figure caption"],
        "ordinary-caption",
        left=70,
        bottom=590,
        char_width=2.0,
    )
    caption.xobj_id = 0
    for character in line_split.paragraph_characters(caption):
        character.xobj_id = 0
    page = _page([publication_line, cover_title, caption], kind="masthead")
    page.pdf_xobject = [
        il_version_1.PdfXobject(
            box=il_version_1.Box(105.328, 765.954, 157.224, 770.067),
            base_operations=il_version_1.BaseOperations(value="q Q"),
            xobj_id=7,
            xref_id=12323,
        ),
        il_version_1.PdfXobject(
            # The real Form metadata stops below the source glyph ink.  The
            # shared figure still contains both, and every non-space glyph
            # independently names this XObject.
            box=il_version_1.Box(69.3868, 636.986, 201.272, 659.359),
            base_operations=il_version_1.BaseOperations(value="q Q"),
            xobj_id=15,
            xref_id=12342,
        ),
    ]
    page.page_layout = [
        il_version_1.PageLayout(
            box=il_version_1.Box(59, 586, 211, 800),
            id=9,
            conf=0.9686747,
            class_name="figure",
        )
    ]
    config = Config(tmp_path)

    report = line_split.apply(config, [(2, page)])

    assert report["totals"]["fixed_artwork"] == 2
    assert [item["source_ref"] for item in report["fixed_artwork"]] == [
        "p2#0",
        "p2#1",
    ]
    assert [item["xobj_id"] for item in report["fixed_artwork"]] == [7, 15]
    assert [
        item["synthetic_whitespace_characters"]
        for item in report["fixed_artwork"]
    ] == [1, 1]
    assert [
        item["paragraph_inside_xobject"] for item in report["fixed_artwork"]
    ] == [True, False]
    assert [unit["debug_id"] for unit in report["source_units"]] == [
        "ordinary-caption"
    ]
    assert all(paragraph.unicode is None for paragraph in artwork)
    assert all(line_split.source_unit(paragraph, 2) is None for paragraph in artwork)
    assert [
        (
            id(character),
            character.char_unicode,
            tuple(
                getattr(character.box, name)
                for name in ("x", "y", "x2", "y2")
            ),
        )
        for paragraph in artwork
        for character in line_split.paragraph_characters(paragraph)
    ] == original_character_state
    driver = object.__new__(ILTranslatorLLMOnly)
    driver.translation_config = SimpleNamespace(min_text_length=1)
    assert all(not driver._should_translate_paragraph(paragraph) for paragraph in artwork)
    assert driver._should_translate_paragraph(caption)

    document = il_version_1.Document(page=[page], total_pages=1)
    layout_report.prepare(
        config,
        document,
        ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={}),
        article_flow_report={"article_flow_applied": False},
        eligible_roles=(),
    )
    try:
        typesetter = Typesetting(SimpleNamespace(lang_out="en"), RenderMapper())
        for paragraph in artwork:
            assert layout_report.is_protected_source(paragraph)
            typesetter.render_paragraph(paragraph, page, {"body": RenderFont()})
    finally:
        layout_report.discard()
    assert all(
        composition.pdf_character is not None
        for paragraph in artwork
        for composition in paragraph.pdf_paragraph_composition
    )
    assert [
        (
            id(character),
            character.char_unicode,
            tuple(
                getattr(character.box, name)
                for name in ("x", "y", "x2", "y2")
            ),
        )
        for paragraph in artwork
        for character in line_split.paragraph_characters(paragraph)
    ] == original_character_state


@pytest.mark.parametrize(
    "counterexample",
    (
        "root_figure_caption",
        "outside_figure",
        "foreign_nonspace_owner",
        "generated_mixed_content",
    ),
)
def test_embedded_artwork_proof_does_not_capture_ordinary_text(
    tmp_path,
    counterexample,
):
    paragraph = _paragraph(
        ["Ordinary translatable record"],
        counterexample,
        left=110,
        bottom=610,
        char_width=1.5,
    )
    paragraph.xobj_id = 0 if counterexample == "root_figure_caption" else 7
    for character in line_split.paragraph_characters(paragraph):
        character.xobj_id = paragraph.xobj_id
    page = _page([paragraph], kind="masthead")
    if counterexample != "root_figure_caption":
        page.pdf_xobject = [
            il_version_1.PdfXobject(
                box=il_version_1.Box(108, 608, 154, 623),
                base_operations=il_version_1.BaseOperations(value="q Q"),
                xobj_id=7,
                xref_id=124,
            )
        ]
    page.page_layout = [
        il_version_1.PageLayout(
            box=(
                il_version_1.Box(70, 560, 210, 690)
                if counterexample != "outside_figure"
                else il_version_1.Box(300, 300, 400, 400)
            ),
            id=10,
            conf=0.99,
            class_name="figure",
        )
    ]
    if counterexample == "generated_mixed_content":
        paragraph.pdf_paragraph_composition.append(
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        pdf_style=paragraph.pdf_style,
                        unicode="generated target",
                    )
                )
            )
        )
    elif counterexample == "foreign_nonspace_owner":
        line_split.paragraph_characters(paragraph)[0].xobj_id = None
    config = Config(tmp_path)

    report = line_split.apply(config, [(2, page)])

    assert report["fixed_artwork"] == []
    assert len(report["source_units"]) == 1
    assert paragraph.unicode == "Ordinary translatable record"
    driver = object.__new__(ILTranslatorLLMOnly)
    driver.translation_config = SimpleNamespace(min_text_length=1)
    assert driver._should_translate_paragraph(paragraph)


def test_debug_overlays_do_not_renumber_physical_parent_aliases(tmp_path):
    style = il_version_1.PdfStyle(font_id="body", font_size=4.0)

    def overlay(index: int):
        return il_version_1.PdfParagraph(
            box=il_version_1.Box(10.0, 600.0 - index, 20.0, 600.1 - index),
            pdf_paragraph_composition=[
                il_version_1.PdfParagraphComposition(
                    pdf_same_style_unicode_characters=(
                        il_version_1.PdfSameStyleUnicodeCharacters(
                            pdf_style=style,
                            unicode=f"debug-{index}",
                            debug_info=True,
                        )
                    )
                )
            ],
            unicode=f"debug-{index}",
            xobj_id=-1,
        )

    overlays = [overlay(index) for index in range(6)]
    source = _paragraph(["Real record ........ 4"], "physical", left=50, bottom=400)
    assert line_split.resolve_parent_index(
        _page([*overlays, source]), 1, "p1#0"
    ) == 6
    _config, document, report = _apply(tmp_path, [*overlays, source])

    assert len(report["source_units"]) == 1
    actual = report["source_units"][0]
    assert actual["parent_ref"] == "p1#0"
    assert actual["runtime_parent_ref"] == "p1#6"
    assert actual["source_ref"] == actual["runtime_source_ref"] == "p1#6"
    assert actual["parent"]["source_ref"] == "p1#0"
    assert actual["parent"]["runtime_source_ref"] == "p1#6"
    held = line_split.source_unit(document.page[0].pdf_paragraph[6], 1)
    assert held is not None
    assert held.parent_ref == "p1#0"
    assert held.runtime_parent_ref == held.source_ref == "p1#6"
    assert line_split.resolve_parent_index(document.page[0], 1, "p1#0") == 6


def test_debug_overlay_identity_survives_typesetting_but_mixed_text_does_not():
    style = il_version_1.PdfStyle(font_id="body", font_size=0.4)
    unicode_overlay = il_version_1.PdfParagraph(
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        pdf_style=style,
                        unicode="Form[Fm390]",
                        debug_info=True,
                    )
                )
            )
        ]
    )
    rendered_debug = il_version_1.PdfCharacter(
        char_unicode="D",
        debug_info=True,
    )
    rendered_real = il_version_1.PdfCharacter(
        char_unicode="R",
        debug_info=False,
    )
    rendered_overlay = il_version_1.PdfParagraph(
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(pdf_character=rendered_debug)
        ]
    )
    mixed = il_version_1.PdfParagraph(
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(pdf_character=rendered_debug),
            il_version_1.PdfParagraphComposition(pdf_character=rendered_real),
        ]
    )

    assert line_split.is_debug_overlay(unicode_overlay)
    assert line_split.is_debug_overlay(rendered_overlay)
    assert not line_split.is_debug_overlay(mixed)


def test_debug_overlay_text_is_excluded_from_the_quality_gate_and_restored(tmp_path):
    style = il_version_1.PdfStyle(font_id="body", font_size=0.4)
    characters = [
        il_version_1.PdfCharacter(
            char_unicode=character,
            box=il_version_1.Box(10.0, 1390.0, 11.0, 1391.0),
            pdf_style=style,
            debug_info=True,
        )
        for character in "Form[Fm390]"
    ]
    overlay = il_version_1.PdfParagraph(
        box=il_version_1.Box(10.0, 1390.0, 30.0, 1391.0),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    box=il_version_1.Box(10.0, 1390.0, 30.0, 1391.0),
                    pdf_style=style,
                    pdf_character=characters,
                )
            )
        ],
        unicode="Form[Fm390]",
        xobj_id=-1,
    )
    compositions = overlay.pdf_paragraph_composition
    document = il_version_1.Document(
        page=[_page([overlay])],
        total_pages=1,
    )
    empty_ir = ArticleDocumentIR(
        articles=(),
        by_page={},
        by_element={},
        by_chain={},
    )

    with minimal_pipeline._without_debug_overlay_text(document):
        assert overlay.pdf_paragraph_composition == []
        assert overlay.unicode is None
        baseline = minimal_detection.capture_baseline(
            document,
            empty_ir,
            labeled_pages=[(1, document.page[0])],
        )
    assert overlay.pdf_paragraph_composition is compositions
    assert overlay.unicode == "Form[Fm390]"

    with minimal_pipeline._without_debug_overlay_text(document):
        refreshed = minimal_detection.refresh_fixed_inventory(
            baseline,
            document,
            empty_ir,
            flow_report=None,
        )
        result = minimal_detection.detect(
            document,
            empty_ir,
            refreshed,
            language="en",
            translation_performed=False,
            working_dir=tmp_path,
            sidecar_name="issues.before.json",
            pass_index=0,
        )
    assert result.issues == ()
    assert overlay.pdf_paragraph_composition is compositions
    assert overlay.unicode == "Form[Fm390]"


def test_zero_drop_cap_intents_do_not_copy_unrelated_page_graph(tmp_path):
    config = Config(tmp_path)
    config.lang_out = "en"
    config.magazine_drop_cap_render = True
    page = _page([_paragraph(["ordinary"], "ordinary", left=50, bottom=400)])

    class UncopyablePagePayload:
        def __deepcopy__(self, _memo):
            raise AssertionError("zero-intent render copied unrelated page state")

    payload = UncopyablePagePayload()
    page.pdf_xobject.append(payload)
    document = il_version_1.Document(page=[page], total_pages=1)
    empty_ir = ArticleDocumentIR(
        articles=(),
        by_page={},
        by_element={},
        by_chain={},
    )

    report = drop_cap_render.apply(
        config,
        document,
        article_document_ir=empty_ir,
        typesetting_stage=object(),
    )

    assert report is not None
    assert report["totals"]["decided"] == report["totals"]["set"] == 0
    assert report["paragraphs"] == []
    assert page.pdf_xobject[-1] is payload
    assert json.loads(
        (tmp_path / drop_cap_render.REPORT_NAME).read_text(encoding="utf-8")
    ) == report


def test_nonempty_drop_cap_intents_keep_the_render_transaction(
    tmp_path,
    monkeypatch,
):
    config = Config(tmp_path)
    config.magazine_drop_cap_render = True
    document = il_version_1.Document(page=[], total_pages=0)
    empty_ir = ArticleDocumentIR(
        articles=(),
        by_page={},
        by_element={},
        by_chain={},
    )
    events = []
    expected = {"path": "active"}

    class Transaction:
        def __init__(self, *_args):
            events.append("transaction")

        def __enter__(self):
            return self

        def commit(self):
            events.append("commit")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        drop_cap_render.drop_cap_intent,
        "intents_for",
        lambda _config: {"p1#0": object()},
    )
    monkeypatch.setattr(drop_cap_render, "_RenderPassTransaction", Transaction)
    monkeypatch.setattr(
        drop_cap_render,
        "_apply_render_pass",
        lambda *_args, **_kwargs: expected,
    )

    assert drop_cap_render.apply(
        config,
        document,
        article_document_ir=empty_ir,
    ) is expected
    assert events == ["transaction", "commit"]
