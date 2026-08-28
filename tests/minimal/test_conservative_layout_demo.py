from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import BoundedTypesettingError
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.format.pdf.document_il.midend.typesetting import TypesettingUnit
from babeldoc.magazine import article_flow
from babeldoc.magazine import layout_report
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import SourceElementRef
from tests.minimal.fakes import FixedWidthFont
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph
from tests.minimal.fakes import document_digest
from tools.verify_magazine_demo import VerificationError
from tools.verify_magazine_demo import verify_layout


class RenderFont(FixedWidthFont):
    @staticmethod
    def has_glyph(_codepoint: int) -> int:
        return 1


class RenderMapper(FixedWidthMapper):
    def __init__(self) -> None:
        self.base_font = RenderFont()
        self.fontid2font = {self.base_font.font_id: self.base_font}


class Config:
    def __init__(self, work: Path, lang_out: str = "zh") -> None:
        self.work = work
        self.lang_out = lang_out
        self.magazine_column_reflow = False
        self.progress_monitor = None
        self.watermark_output_mode = None

    def get_working_file_path(self, name: str):
        self.work.mkdir(parents=True, exist_ok=True)
        return self.work / name

    @staticmethod
    def raise_if_cancelled() -> None:
        return None


def _flow_report() -> dict:
    return {
        "article_flow_applied": False,
        "status": "disabled",
        "totals": {"placements": 0},
    }


def _original_character_paragraph(text: str, debug_id: str, box):
    style = il_version_1.PdfStyle(font_id="body", font_size=10.0)
    characters = [
        il_version_1.PdfCharacter(
            char_unicode=character,
            box=il_version_1.Box(
                box[0] + index * 5.0,
                box[1],
                box[0] + (index + 1) * 5.0,
                box[1] + 10.0,
            ),
            pdf_style=style,
            xobj_id=-1,
        )
        for index, character in enumerate(text)
    ]
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*box),
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
        layout_label="text",
        xobj_id=-1,
    )


def _article_ir(paragraphs, boxes) -> ArticleDocumentIR:
    elements = tuple(
        SourceElementRef(
            source_ref=f"p1#{index}",
            page=1,
            column=max(0, index - 1),
            reading_order=index,
            role="text",
            source_box=box,
            source_text_hash=hashlib.sha256(paragraph.unicode.encode()).hexdigest(),
            style_hash=f"style-{index}",
        )
        for index, (paragraph, box) in enumerate(zip(paragraphs, boxes, strict=True))
    )
    chain_ids = ("chain-1",) if len(elements) >= 4 else ()
    article = ArticleIR(
        article_id="article-1",
        pages=(1,),
        elements=elements,
        slots=(),
        chain_ids=chain_ids,
        policy_evidence=(),
    )
    refs = tuple(element.source_ref for element in elements)
    return ArticleDocumentIR(
        articles=(article,),
        by_page={1: article.article_id},
        by_element=dict.fromkeys(refs, article.article_id),
        by_chain=(
            {"chain-1": article.article_id}
            if chain_ids
            else {}
        ),
        by_chain_member=(
            {refs[2]: "chain-1", refs[3]: "chain-1"}
            if chain_ids
            else {}
        ),
    )


def test_minimal_configuration_fixes_ordinary_article_flow_off():
    config = SimpleNamespace()
    minimal_pipeline.configure(config)
    assert config.magazine_column_reflow is False
    with pytest.raises(minimal_pipeline.MinimalPipelineStateError, match="conflicting"):
        minimal_pipeline.configure(
            SimpleNamespace(magazine_column_reflow=True)
        )


def test_disabled_article_flow_writes_report_without_document_mutation(tmp_path):
    paragraph = _paragraph("body", "body", (0.0, 0.0, 50.0, 15.0))
    document = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    article_ir = _article_ir([paragraph], [(0.0, 0.0, 50.0, 15.0)])
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    before = document_digest(document)

    report = article_flow.apply(
        config,
        document,
        article_ir,
        typesetter=typesetter,
    )

    assert report["article_flow_applied"] is False
    assert report["status"] == "disabled"
    assert report["totals"]["placements"] == 0
    assert document_digest(document) == before
    assert json.loads((tmp_path / article_flow.REPORT_NAME).read_text()) == report


def test_pipeline_prepares_frozen_holders_after_disabled_flow(monkeypatch, tmp_path):
    source_box = (10.0, 10.0, 90.0, 30.0)
    paragraph = _paragraph("pipeline body", "pipeline", source_box)
    paragraph.xobj_id = -1
    document = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    article_ir = _article_ir([paragraph], [source_box])
    config = Config(tmp_path)
    minimal_pipeline.configure(config)
    state = config.magazine_state
    state._structure_started = True
    state._structure_document_identity = id(document)
    state._article_document_ir = article_ir
    typesetter = Typesetting(config, RenderMapper())
    monkeypatch.setattr(minimal_pipeline.paren_dedup, "apply", lambda *_args: None)
    monkeypatch.setattr(minimal_pipeline.indent_policy, "apply", lambda *_args: None)

    report = minimal_pipeline.after_translation(config, document, typesetter)
    container = layout_report.source_container(paragraph, 1)

    assert report["article_flow_applied"] is False
    assert container is not None
    assert container.role == "body"
    assert container.source_box == source_box
    typesetter.render_page(document.page[0])
    assert layout_report.finalize()["totals"]["success"] == 1


@pytest.mark.parametrize("lang_out", ("zh", "en"))
def test_intro_columns_body_and_chain_keep_each_source_x_band(tmp_path, lang_out):
    boxes = (
        (0.0, 70.0, 120.0, 90.0),
        (0.0, 30.0, 30.0, 50.0),
        (45.0, 30.0, 75.0, 50.0),
        (90.0, 30.0, 120.0, 50.0),
    )
    paragraphs = [
        _paragraph(text, f"p-{index}", box)
        for index, (text, box) in enumerate(
            zip(("wide introduction", "left", "middle", "right"), boxes, strict=True)
        )
    ]
    for paragraph in paragraphs:
        paragraph.xobj_id = -1
    for chain_index, paragraph in enumerate(paragraphs[2:]):
        paragraph.chain_id = "raw-chain"
        paragraph.chain_index = chain_index
    document = il_version_1.Document(page=[_page(0, paragraphs)], total_pages=1)
    article_ir = _article_ir(paragraphs, boxes)
    config = Config(tmp_path, lang_out)
    typesetter = Typesetting(config, RenderMapper())
    original_texts = [paragraph.unicode for paragraph in paragraphs]

    layout_report.prepare(
        config,
        document,
        article_ir,
        article_flow_report=_flow_report(),
        eligible_roles=("text",),
    )
    typesetter.render_page(document.page[0])
    report = layout_report.finalize()

    assert len(document.page[0].pdf_paragraph) == 4
    assert [paragraph.unicode for paragraph in paragraphs] == original_texts
    assert [
        tuple(getattr(paragraph.box, name) for name in ("x", "y", "x2", "y2"))
        for paragraph in paragraphs
    ] == list(boxes)
    assert [item["role"] for item in report["elements"]] == [
        "body",
        "body",
        "chain",
        "chain",
    ]
    assert all(item["source_box"] == item["allocation_box"] for item in report["elements"])
    assert all(item["source_box"] == item["final_holder_box"] for item in report["elements"])
    assert all(item["status"] == "success" for item in report["elements"])


def test_single_block_and_prose_use_their_own_source_units(monkeypatch, tmp_path):
    boxes = (
        (0.0, 70.0, 80.0, 90.0),
        (0.0, 35.0, 80.0, 65.0),
        (0.0, 0.0, 80.0, 30.0),
    )
    paragraphs = [
        _paragraph(text, f"unit-{index}", box)
        for index, (text, box) in enumerate(
            zip(("single", "block text", "prose text"), boxes, strict=True)
        )
    ]
    for paragraph in paragraphs:
        paragraph.xobj_id = -1
    document = il_version_1.Document(page=[_page(0, paragraphs)], total_pages=1)
    empty_ir = ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={})
    kinds = ("single_visual_line", "block", "prose_exempt")
    units = {
        id(paragraph): SimpleNamespace(
            source_ref=f"p1#{index}",
            record_kind=kinds[index],
            source_box=boxes[index],
        )
        for index, paragraph in enumerate(paragraphs)
    }
    monkeypatch.setattr(
        layout_report.line_split,
        "source_unit",
        lambda paragraph, _physical_page: units.get(id(paragraph)),
    )
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())

    layout_report.prepare(
        config,
        document,
        empty_ir,
        article_flow_report=_flow_report(),
        eligible_roles=("text",),
    )
    typesetter.render_page(document.page[0])
    report = layout_report.finalize()

    assert [item["role"] for item in report["elements"]] == list(kinds)
    assert all(item["status"] == "success" for item in report["elements"])
    assert all(item["source_box"] == item["final_holder_box"] for item in report["elements"])


def test_fixed_companion_is_not_a_target_holder_and_remains_untouched(
    monkeypatch, tmp_path
):
    fixed = _original_character_paragraph(
        "50", "fixed-folio", (0.0, 70.0, 20.0, 90.0)
    )
    translated = _paragraph("translated", "record", (25.0, 70.0, 100.0, 90.0))
    translated.xobj_id = -1
    document = il_version_1.Document(
        page=[_page(0, [fixed, translated])], total_pages=1
    )
    empty_ir = ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={})
    units = {
        id(fixed): SimpleNamespace(
            source_ref="p1#0",
            record_kind="single_visual_line",
            source_box=(0.0, 70.0, 20.0, 90.0),
            fixed_companion=True,
        ),
        id(translated): SimpleNamespace(
            source_ref="p1#1",
            record_kind="single_visual_line",
            source_box=(25.0, 70.0, 100.0, 90.0),
            fixed_companion=False,
        ),
    }
    monkeypatch.setattr(
        layout_report.line_split,
        "source_unit",
        lambda paragraph, _physical_page: units.get(id(paragraph)),
    )
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    fixed_box = copy.deepcopy(fixed.box)
    fixed_characters = list(
        fixed.pdf_paragraph_composition[0]
        .pdf_same_style_characters.pdf_character
    )
    fixed_character_state = copy.deepcopy(fixed_characters)

    layout_report.prepare(
        config,
        document,
        empty_ir,
        article_flow_report=_flow_report(),
        eligible_roles=("text",),
    )
    typesetter.render_paragraph(fixed, document.page[0], {"body": RenderFont()})
    typesetter.render_paragraph(
        translated, document.page[0], {"body": RenderFont()}
    )
    report = layout_report.finalize()

    assert fixed.box == fixed_box
    assert fixed.scale == 1.0
    assert len(fixed.pdf_paragraph_composition) == len(fixed_characters)
    assert all(
        composition.pdf_character is character
        and composition.pdf_formula is None
        and composition.pdf_same_style_characters is None
        for composition, character in zip(
            fixed.pdf_paragraph_composition,
            fixed_characters,
            strict=True,
        )
    )
    assert fixed_characters == fixed_character_state
    assert [item["source_ref"] for item in report["elements"]] == ["p1#1"]
    assert report["elements"][0]["status"] == "success"


def test_untranslated_vertical_furniture_is_excluded_and_untouched(
    monkeypatch, tmp_path
):
    vertical_box = (52.0214, 71.825, 57.9964, 304.7845)
    vertical = _original_character_paragraph(
        "vertical source", "vertical", vertical_box
    )
    vertical.vertical = True
    horizontal_box = (70.0, 71.825, 120.0, 101.825)
    horizontal = _paragraph("译文", "horizontal", horizontal_box)
    horizontal.xobj_id = -1
    document = il_version_1.Document(
        page=[_page(0, [vertical, horizontal])], total_pages=1
    )
    empty_ir = ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={})
    units = {
        id(vertical): SimpleNamespace(
            source_ref="p1#0",
            record_kind="block",
            source_box=vertical_box,
            fixed_companion=False,
        ),
        id(horizontal): SimpleNamespace(
            source_ref="p1#1",
            record_kind="single_visual_line",
            source_box=horizontal_box,
            fixed_companion=False,
        ),
    }
    monkeypatch.setattr(
        layout_report.line_split,
        "source_unit",
        lambda paragraph, _physical_page: units.get(id(paragraph)),
    )
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    vertical_box_before = copy.deepcopy(vertical.box)
    vertical_characters = list(
        vertical.pdf_paragraph_composition[0]
        .pdf_same_style_characters.pdf_character
    )
    vertical_character_state = copy.deepcopy(vertical_characters)

    layout_report.prepare(
        config,
        document,
        empty_ir,
        article_flow_report=_flow_report(),
        eligible_roles=("text",),
    )
    typesetter.render_paragraph(vertical, document.page[0], {"body": RenderFont()})
    typesetter.render_paragraph(
        horizontal, document.page[0], {"body": RenderFont()}
    )
    report = layout_report.finalize()

    assert vertical.box == vertical_box_before
    assert vertical.scale == 1.0
    assert all(
        composition.pdf_character is character
        for composition, character in zip(
            vertical.pdf_paragraph_composition,
            vertical_characters,
            strict=True,
        )
    )
    assert vertical_characters == vertical_character_state
    assert [item["source_ref"] for item in report["elements"]] == ["p1#1"]
    assert report["elements"][0]["source_box"] == list(horizontal_box)
    assert report["elements"][0]["status"] == "success"


def test_original_passthrough_composition_is_generically_protected(tmp_path):
    source = _original_character_paragraph(
        "12", "short-untranslated", (0.0, 70.0, 20.0, 90.0)
    )
    translated_box = (25.0, 70.0, 100.0, 90.0)
    translated = _paragraph("目标", "translated", translated_box)
    translated.xobj_id = -1
    source_characters = list(
        source.pdf_paragraph_composition[0]
        .pdf_same_style_characters.pdf_character
    )
    for index, character in enumerate(source_characters, start=1):
        character.render_order = 11
        character.sub_render_order = index
    formula_box = il_version_1.Box(10.0, 70.0, 15.0, 80.0)
    formula_character = il_version_1.PdfCharacter(
        char_unicode="x",
        box=formula_box,
        visual_bbox=il_version_1.VisualBbox(box=formula_box),
        pdf_style=source.pdf_style,
        render_order=12,
        sub_render_order=1,
        xobj_id=-1,
    )
    formula = il_version_1.PdfFormula(
        box=formula_box,
        pdf_character=[formula_character],
        x_offset=0.0,
        y_offset=0.0,
        x_advance=5.0,
    )
    source.pdf_paragraph_composition.append(
        il_version_1.PdfParagraphComposition(pdf_formula=formula)
    )
    source.unicode = "12x"
    document = il_version_1.Document(
        page=[_page(0, [source, translated])], total_pages=1
    )
    empty_ir = ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={})
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    source_box = copy.deepcopy(source.box)
    source_character_state = copy.deepcopy(source_characters)
    formula_state = copy.deepcopy(formula)

    layout_report.prepare(
        config,
        document,
        empty_ir,
        article_flow_report=_flow_report(),
        eligible_roles=("text",),
    )
    typesetter.render_paragraph(source, document.page[0], {"body": RenderFont()})
    typesetter.render_paragraph(
        translated, document.page[0], {"body": RenderFont()}
    )
    report = layout_report.finalize()

    assert source.box == source_box
    assert source.scale == 1.0
    assert len(source.pdf_paragraph_composition) == 3
    assert all(
        composition.pdf_line is None
        and composition.pdf_same_style_characters is None
        and composition.pdf_same_style_unicode_characters is None
        and (
            composition.pdf_character is not None
            or composition.pdf_formula is not None
        )
        for composition in source.pdf_paragraph_composition
    )
    assert [
        composition.pdf_character
        for composition in source.pdf_paragraph_composition[:2]
    ] == source_characters
    assert source.pdf_paragraph_composition[2].pdf_formula is formula
    assert source_characters == source_character_state
    assert formula == formula_state
    assert [item["source_ref"] for item in report["elements"]] == ["p1#1"]
    assert report["elements"][0]["status"] == "success"


def test_protected_generated_unicode_composition_fails_closed(tmp_path):
    source = _paragraph(
        "unexpected generated target",
        "protected-unicode",
        (0.0, 0.0, 100.0, 20.0),
    )
    source.vertical = True
    document = il_version_1.Document(page=[_page(0, [source])], total_pages=1)
    config = Config(tmp_path)
    typesetter = Typesetting(config, RenderMapper())
    original_compositions = source.pdf_paragraph_composition

    layout_report.prepare(
        config,
        document,
        ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={}),
        article_flow_report=_flow_report(),
        eligible_roles=("text",),
    )

    with pytest.raises(BoundedTypesettingError, match="non-passthrough"):
        typesetter.render_paragraph(
            source,
            document.page[0],
            {"body": RenderFont()},
        )

    assert source.pdf_paragraph_composition is original_compositions


def test_minimum_scale_overflow_is_reported_without_expansion_or_text_loss(
    monkeypatch, tmp_path
):
    source_box = (0.0, 0.0, 50.0, 10.0)
    target = "x" * 21  # 105pt at scale 1; still 52.5pt at the fixed 0.5 minimum.
    paragraph = _paragraph(target, "overflow", source_box)
    paragraph.xobj_id = -1
    document = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    empty_ir = ArticleDocumentIR(articles=(), by_page={}, by_element={}, by_chain={})
    unit = SimpleNamespace(
        source_ref="p1#0",
        record_kind="single_visual_line",
        source_box=source_box,
    )
    monkeypatch.setattr(
        layout_report.line_split,
        "source_unit",
        lambda held, _physical_page: unit if held is paragraph else None,
    )
    config = Config(tmp_path, "en")
    typesetter = Typesetting(config, RenderMapper())
    original_compositions = paragraph.pdf_paragraph_composition

    layout_report.prepare(
        config,
        document,
        empty_ir,
        article_flow_report=_flow_report(),
        eligible_roles=("text",),
    )
    with pytest.raises(BoundedTypesettingError, match="does not fit"):
        typesetter.render_paragraph(
            paragraph,
            document.page[0],
            {"body": RenderFont()},
        )

    report = json.loads((tmp_path / layout_report.REPORT_NAME).read_text())
    item = report["elements"][0]
    assert item["status"] == "overflow"
    assert item["overflow_reason"] == "minimum_readable_scale_exhausted"
    assert item["source_box"] == item["final_holder_box"]
    assert paragraph.pdf_paragraph_composition is original_compositions
    assert paragraph.unicode == target
    assert tuple(getattr(paragraph.box, name) for name in ("x", "y", "x2", "y2")) == source_box


def test_bounded_prose_wraps_hanging_punctuation_inside_source_x2():
    source_box = (0.0, 0.0, 50.0, 30.0)
    target = "汉" * 10 + "。"
    paragraph = _paragraph(target, "hung-punctuation", source_box)
    paragraph.xobj_id = -1
    page = _page(0, [paragraph])
    typesetter = Typesetting(SimpleNamespace(lang_out="zh"), RenderMapper())
    style = il_version_1.PdfStyle(font_id="body", font_size=10.0)
    units = [
        TypesettingUnit(
            unicode=character,
            font=typesetter.font_mapper.base_font,
            font_size=10.0,
            style=style,
            xobj_id=-1,
        )
        for character in target
    ]

    ordinary, ordinary_fits = typesetter._layout_typesetting_units(
        units,
        il_version_1.Box(*source_box),
        1.0,
        1.5,
        paragraph,
        True,
    )
    assert ordinary_fits
    assert max(unit.box.x2 for unit in ordinary) > source_box[2]

    laid_out = typesetter.retypeset_bounded_source_unit(
        paragraph,
        page,
        units,
        SimpleNamespace(
            source_ref="p1#0",
            source_box=source_box,
            record_kind="prose_exempt",
        ),
    )

    assert max(unit.box.x2 for unit in laid_out) <= source_box[2]
    assert len({unit.layout_line_index for unit in laid_out}) == 2
    assert paragraph.unicode == target


def _offset_formula_unit(
    typesetter: Typesetting,
    *,
    height: float,
    y_offset: float,
) -> list[TypesettingUnit]:
    style = il_version_1.PdfStyle(font_id="body", font_size=height)
    formula_box = il_version_1.Box(0.0, 0.0, 5.0, height)
    formula_character = il_version_1.PdfCharacter(
        char_unicode="|",
        box=formula_box,
        visual_bbox=il_version_1.VisualBbox(box=formula_box),
        pdf_style=style,
        advance=5.0,
        xobj_id=-1,
    )
    return [
        TypesettingUnit(
            unicode="A",
            font=typesetter.font_mapper.base_font,
            font_size=height,
            style=style,
            xobj_id=-1,
        ),
        TypesettingUnit(
            formular=il_version_1.PdfFormula(
                box=formula_box,
                pdf_character=[formula_character],
                x_offset=0.0,
                y_offset=y_offset,
                x_advance=5.0,
            )
        ),
    ]


def test_bounded_candidate_shrinks_until_actual_formula_ink_is_contained():
    source_box = (583.7255859375, 3.114, 626.2633828125, 10.3037109375)
    height = source_box[3] - source_box[1]
    paragraph = _paragraph("generated timestamp", "offset-ink", source_box)
    paragraph.xobj_id = -1
    page = _page(0, [paragraph])
    typesetter = Typesetting(SimpleNamespace(lang_out="en"), RenderMapper())
    units = _offset_formula_unit(
        typesetter,
        height=height,
        y_offset=-1.7914171875,
    )

    initial, initial_fits = typesetter._layout_typesetting_units(
        units,
        il_version_1.Box(*source_box),
        1.0,
        1.3,
        paragraph,
        True,
        False,
    )
    assert initial_fits
    assert min(unit.box.y for unit in initial) == pytest.approx(1.3225828125)

    laid_out = typesetter.retypeset_bounded_source_unit(
        paragraph,
        page,
        units,
        SimpleNamespace(
            source_ref="p3#20",
            source_box=source_box,
            record_kind="single_visual_line",
        ),
    )

    assert paragraph.scale == pytest.approx(0.8)
    bounds = (
        min(unit.box.x for unit in laid_out),
        min(unit.box.y for unit in laid_out),
        max(unit.box.x2 for unit in laid_out),
        max(unit.box.y2 for unit in laid_out),
    )
    assert source_box[0] <= bounds[0]
    assert source_box[1] <= bounds[1]
    assert bounds[2] <= source_box[2]
    assert bounds[3] <= source_box[3]


def test_bounded_actual_ink_overflow_at_minimum_scale_fails_closed():
    source_box = (0.0, 0.0, 50.0, 10.0)
    paragraph = _paragraph("target", "offset-ink-overflow", source_box)
    paragraph.xobj_id = -1
    page = _page(0, [paragraph])
    typesetter = Typesetting(SimpleNamespace(lang_out="en"), RenderMapper())
    units = _offset_formula_unit(
        typesetter,
        height=10.0,
        y_offset=-11.0,
    )
    original_compositions = paragraph.pdf_paragraph_composition

    with pytest.raises(BoundedTypesettingError, match="does not fit"):
        typesetter.retypeset_bounded_source_unit(
            paragraph,
            page,
            units,
            SimpleNamespace(
                source_ref="p1#0",
                source_box=source_box,
                record_kind="single_visual_line",
            ),
        )

    assert paragraph.pdf_paragraph_composition is original_compositions
    assert paragraph.scale is None


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_layout_verifier_accepts_containment_and_rejects_escape(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    expectations = tmp_path / "expectations.json"
    _write_json(
        expectations,
        {
            "sample_id": "synthetic-layout",
            "source_sha256": hashlib.sha256(b"source").hexdigest(),
            "direction": "en-zh",
            "layout_regions": [
                {
                    "role": "multi_column_page",
                    "physical_page": 1,
                    "source_box": [0.0, 0.0, 100.0, 100.0],
                }
            ],
        },
    )
    _write_json(tmp_path / "article_flow.report.json", _flow_report())
    item = {
        "source_ref": "p1#0",
        "role": "body",
        "source_box": [10.0, 10.0, 40.0, 40.0],
        "allocation_box": [10.0, 10.0, 40.0, 40.0],
        "final_holder_box": [10.0, 10.0, 40.0, 40.0],
        "final_text_box": [11.0, 11.0, 39.0, 39.0],
        "status": "success",
        "overflow_reason": None,
        "article_flow_applied": False,
    }
    _write_json(
        tmp_path / layout_report.REPORT_NAME,
        {
            "article_flow_applied": False,
            "elements": [item],
            "totals": {"elements": 1, "success": 1, "overflow": 0, "pending": 0},
        },
    )

    result = verify_layout(expectations, source, output, tmp_path, "en", "zh")
    assert result["status"] == "pass"

    item["final_text_box"] = [11.0, 11.0, 41.0, 39.0]
    _write_json(
        tmp_path / layout_report.REPORT_NAME,
        {
            "article_flow_applied": False,
            "elements": [item],
            "totals": {"elements": 1, "success": 1, "overflow": 0, "pending": 0},
        },
    )
    with pytest.raises(VerificationError, match="final text left"):
        verify_layout(expectations, source, output, tmp_path, "en", "zh")
