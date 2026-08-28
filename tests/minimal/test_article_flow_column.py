from __future__ import annotations

from types import SimpleNamespace

from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import PdfStyle
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import article_flow
from babeldoc.magazine import cross_page_reflow
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import ArticlePolicyEvidence
from babeldoc.magazine.article_ir import ArticleRegionSlot
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.article_ir import UnsupportedArticlePage
from tests.minimal.fakes import FixedWidthFont
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph
from tests.minimal.fakes import document_digest

FLOW_CONFIG = article_flow.ArticleFlowConfig(
    eligible_roles=("body", "text"),
    asset_bbox_tolerance_pt=0.000001,
    minimum_slot_height_pt=1.0,
)
FLOW_TARGET = "甲乙丙丁戊己庚辛"


def flow_runtime(tmp_path):
    def working_file(name: str):
        return tmp_path / name

    config = SimpleNamespace(
        lang_out="zh",
        magazine_column_reflow=True,
        get_working_file_path=working_file,
    )
    return config, Typesetting(config, font_mapper=FixedWidthMapper())


def source_element(
    source_ref: str,
    *,
    page: int,
    column: int,
    reading_order: int,
    role: str = "body",
    box: tuple[float, float, float, float] = (0.0, 0.0, 25.0, 15.0),
) -> SourceElementRef:
    return SourceElementRef(
        source_ref=source_ref,
        page=page,
        column=column,
        reading_order=reading_order,
        role=role,
        source_box=box,
        source_text_hash=f"source-{source_ref}",
        style_hash=f"style-{source_ref}",
    )


def region_slot(
    *,
    page: int,
    column: int,
    slot_order: int,
    box: tuple[float, float, float, float],
) -> ArticleRegionSlot:
    return ArticleRegionSlot(
        article_id="article-1",
        page=page,
        column=column,
        slot_order=slot_order,
        box=box,
        fixed_obstacle_refs=(),
        capacity_hint=1.0,
    )


def canonical_ir(
    elements: tuple[SourceElementRef, ...],
    slots: tuple[ArticleRegionSlot, ...],
    *,
    pages: tuple[int, ...] | None = None,
    unsupported_pages: tuple[UnsupportedArticlePage, ...] = (),
) -> ArticleDocumentIR:
    held_pages = pages or tuple(sorted({element.page for element in elements}))
    article = ArticleIR(
        article_id="article-1",
        pages=held_pages,
        elements=elements,
        slots=slots,
        chain_ids=(),
        policy_evidence=tuple(
            ArticlePolicyEvidence(
                page=page,
                role="article",
                page_kind="body",
                reason=None,
                article_reflow_allowed=True,
            )
            for page in held_pages
        ),
    )
    return ArticleDocumentIR(
        articles=(article,),
        by_page=dict.fromkeys(held_pages, article.article_id),
        by_element={element.source_ref: article.article_id for element in elements},
        by_chain={},
        unsupported_pages=unsupported_pages,
    )


def boundary(
    paragraph,
    *,
    source_ref: str = "p1#0",
    source_page: int = 1,
    target: str = FLOW_TARGET,
    suffix: str = "0",
) -> article_flow.ParagraphBoundaryToken:
    return article_flow.ParagraphBoundaryToken(
        source_ref=source_ref,
        source_page=source_page,
        source_slot_id=f"source-holder:{source_ref}",
        paragraph_order=0,
        request_id=f"request-{suffix}",
        fragment_id=f"fragment-{suffix}",
        target_start=0,
        target_end=len(target),
        text=target,
        first_line_indent=False,
        spacing_before=0.0,
        style=PdfStyle(font_id="body", font_size=10.0),
        original_font=FixedWidthFont(),
        paragraph=paragraph,
    )


def local_segment(
    *,
    page: int,
    source_refs: tuple[str, ...],
    slots: tuple[article_flow.ArticleFlowSlot, ...],
    boundaries: tuple[article_flow.ParagraphBoundaryToken, ...],
    suffix: str = "0",
    protected: tuple[article_flow.ProtectedElement, ...] = (),
) -> article_flow.ArticleFlowSegment:
    return article_flow.ArticleFlowSegment(
        segment_id=f"local-{suffix}",
        article_id="article-1",
        page=page,
        ordered_source_refs=source_refs,
        ordered_slots=slots,
        boundaries=boundaries,
        protected_elements=protected,
    )


def flow_slot(
    *,
    page: int,
    column: int,
    order: int,
    suffix: str,
    box: tuple[float, float, float, float] = (0.0, 0.0, 25.0, 15.0),
) -> article_flow.ArticleFlowSlot:
    return article_flow.ArticleFlowSlot(
        slot_id=f"slot-{suffix}",
        article_id="article-1",
        page=page,
        column=column,
        slot_order=order,
        box=box,
        obstacle_refs=(),
    )


def cross_segment(
    local_segments: tuple[article_flow.ArticleFlowSegment, ...],
    document,
    article_document_ir: ArticleDocumentIR,
):
    inventory = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    return cross_page_reflow._cross_segment(local_segments, (), inventory)


def test_same_page_column_slots_are_stable_and_long_target_is_conserved(
    monkeypatch, tmp_path
):
    paragraph = _paragraph(FLOW_TARGET, "body", (0.0, 0.0, 25.0, 15.0))
    document = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    elements = (source_element("p1#0", page=1, column=0, reading_order=0),)
    slots = (
        region_slot(page=1, column=0, slot_order=0, box=(0.0, 0.0, 25.0, 15.0)),
        region_slot(
            page=1, column=1, slot_order=1, box=(60.0, 0.0, 85.0, 15.0)
        ),
    )
    article_document_ir = canonical_ir(elements, slots)
    local = local_segment(
        page=1,
        source_refs=("p1#0",),
        slots=(
            flow_slot(page=1, column=0, order=0, suffix="left"),
            flow_slot(
                page=1,
                column=1,
                order=1,
                suffix="right",
                box=(60.0, 0.0, 85.0, 15.0),
            ),
        ),
        boundaries=(boundary(paragraph),),
    )
    unified = cross_segment((local,), document, article_document_ir)
    monkeypatch.setattr(
        cross_page_reflow,
        "build_cross_page_segments",
        lambda *_args, **_kwargs: ((unified,), ()),
    )
    config, typesetter = flow_runtime(tmp_path)

    report = cross_page_reflow.apply(
        config,
        document,
        article_document_ir,
        typesetter=typesetter,
        config=FLOW_CONFIG,
    )

    result = report["cross_page_segments"][0]
    assert result["status"] == "applied"
    placements = result["placements"]
    assert [item["column"] for item in placements] == [0, 1]
    assert [item["slot_order"] for item in placements] == [0, 1]
    assert "".join(document.page[0].pdf_paragraph[index].unicode for index in range(2)) == FLOW_TARGET
    assert sum(item["chars"] for item in placements) == len(FLOW_TARGET)
    assert placements[0]["target_range"][1] == placements[1]["target_range"][0]


def test_short_target_releases_only_the_trailing_holder(monkeypatch, tmp_path):
    first = _paragraph("甲乙", "first", (0.0, 0.0, 25.0, 15.0))
    second = _paragraph("unused", "second", (0.0, 20.0, 25.0, 35.0))
    document = il_version_1.Document(page=[_page(0, [first, second])], total_pages=1)
    elements = (
        source_element("p1#0", page=1, column=0, reading_order=0),
        source_element(
            "p1#1",
            page=1,
            column=0,
            reading_order=1,
            box=(0.0, 20.0, 25.0, 35.0),
        ),
    )
    article_document_ir = canonical_ir(
        elements,
        (region_slot(page=1, column=0, slot_order=0, box=(0.0, 0.0, 25.0, 15.0)),),
    )
    local = local_segment(
        page=1,
        source_refs=("p1#0", "p1#1"),
        slots=(flow_slot(page=1, column=0, order=0, suffix="short"),),
        boundaries=(boundary(first, target="甲乙"),),
    )
    unified = cross_segment((local,), document, article_document_ir)
    monkeypatch.setattr(
        cross_page_reflow,
        "build_cross_page_segments",
        lambda *_args, **_kwargs: ((unified,), ()),
    )
    config, typesetter = flow_runtime(tmp_path)

    report = cross_page_reflow.apply(
        config,
        document,
        article_document_ir,
        typesetter=typesetter,
        config=FLOW_CONFIG,
    )

    result = report["cross_page_segments"][0]
    assert result["status"] == "applied"
    assert result["released_holders"] == ["p1#1"]
    assert document.page[0].pdf_paragraph[0].unicode == "甲乙"
    assert document.page[0].pdf_paragraph[1].unicode == ""


def test_protected_roles_formula_vertical_and_furniture_remain_fixed(tmp_path):
    title = _paragraph("title", "title", (0.0, 80.0, 25.0, 95.0), label="title")
    formula = _paragraph("formula", "formula", (0.0, 60.0, 25.0, 75.0))
    formula.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_formula=il_version_1.PdfFormula(
                box=Box(0.0, 60.0, 25.0, 75.0),
                pdf_character=[
                    il_version_1.PdfCharacter(
                        box=Box(0.0, 60.0, 5.0, 70.0), char_unicode="x"
                    )
                ],
            )
        )
    ]
    vertical = _paragraph("vertical", "vertical", (30.0, 40.0, 45.0, 75.0))
    vertical.vertical = True
    table = _paragraph("table", "table", (0.0, 20.0, 25.0, 35.0), label="table")
    body = _paragraph("body", "body", (60.0, 0.0, 85.0, 15.0))
    furniture = _paragraph("folio", "folio", (90.0, 0.0, 115.0, 10.0))
    page = _page(0, [title, formula, vertical, table, body, furniture])
    page.pdf_figure = [il_version_1.PdfFigure(box=Box(90.0, 70.0, 115.0, 95.0))]
    document = il_version_1.Document(page=[page], total_pages=1)
    roles = ("title", "body", "body", "table", "body")
    boxes = tuple(
        (item.box.x, item.box.y, item.box.x2, item.box.y2)
        for item in (title, formula, vertical, table, body)
    )
    elements = tuple(
        source_element(
            f"p1#{index}",
            page=1,
            column=0 if index < 4 else 1,
            reading_order=index,
            role=roles[index],
            box=boxes[index],
        )
        for index in range(5)
    )
    article_document_ir = canonical_ir(
        elements,
        (region_slot(page=1, column=1, slot_order=0, box=boxes[4]),),
    )
    inventory = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    config, typesetter = flow_runtime(tmp_path)

    segments = article_flow.build_page_segments(
        document,
        article_document_ir.articles[0],
        1,
        inventory,
        FLOW_CONFIG,
        typesetter,
    )

    protected = {
        item.reference: item.reason
        for segment in segments
        for item in segment.protected_elements
    }
    assert protected["p1#0"] == "role_not_eligible"
    assert protected["p1#1"] == "formula"
    assert protected["p1#2"] == "rotated_text"
    assert protected["p1#3"] == "role_not_eligible"
    assert protected["p1#5"] == "fixed_asset"
    assert any(reference.startswith("p1:pdf_figure#") for reference in protected)
    assert fixed_assets.content_digest(vertical) == inventory.by_ref["p1#2"].digest
    assert fixed_assets.content_digest(furniture) == inventory.by_ref["p1#5"].digest

    report = cross_page_reflow.apply(
        config,
        document,
        article_document_ir,
        typesetter=typesetter,
        config=FLOW_CONFIG,
    )
    after = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    assert report["totals"]["segments_applied"] == 1
    assert fixed_assets.compare(inventory, after, 0.000001).holds
    assert fixed_assets.content_digest(vertical) == inventory.by_ref["p1#2"].digest
    assert fixed_assets.content_digest(furniture) == inventory.by_ref["p1#5"].digest


def test_same_page_multi_article_evidence_is_inert(tmp_path):
    paragraph = _paragraph("unchanged", "body", (0.0, 0.0, 25.0, 15.0))
    document = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    unsupported = UnsupportedArticlePage(
        page=1,
        reason="same_page_multi_article",
        evidence_refs=("p1#0",),
    )
    article_document_ir = canonical_ir(
        (source_element("p1#0", page=1, column=0, reading_order=0),),
        (),
        unsupported_pages=(unsupported,),
    )
    config, typesetter = flow_runtime(tmp_path)
    before = document_digest(document)

    report = cross_page_reflow.apply(
        config,
        document,
        article_document_ir,
        typesetter=typesetter,
        config=FLOW_CONFIG,
    )

    assert document_digest(document) == before
    assert report["pages"][0]["status"] == "skipped"
    assert report["pages"][0]["reason"] == article_flow.SKIP_UNSUPPORTED
    assert report["totals"]["segments_applied"] == 0
