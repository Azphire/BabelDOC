from __future__ import annotations

import copy

import pytest
from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import fixed_assets
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph
from tests.minimal.test_article_flow_column import canonical_ir
from tests.minimal.test_article_flow_column import region_slot
from tests.minimal.test_article_flow_column import source_element


def asset_fixture():
    formula = _paragraph("formula", "formula", (0.0, 60.0, 25.0, 75.0))
    formula.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_formula=il_version_1.PdfFormula(
                box=Box(0.0, 60.0, 25.0, 75.0),
                pdf_character=[
                    il_version_1.PdfCharacter(
                        box=Box(1.0, 61.0, 4.0, 70.0), char_unicode="x"
                    )
                ],
                pdf_curve=[
                    il_version_1.PdfCurve(box=Box(4.0, 61.0, 9.0, 62.0))
                ],
                pdf_form=[
                    il_version_1.PdfForm(box=Box(10.0, 61.0, 14.0, 70.0))
                ],
            )
        )
    ]
    vertical = _paragraph("vertical", "vertical", (30.0, 50.0, 45.0, 80.0))
    vertical.vertical = True
    furniture = _paragraph("folio", "folio", (0.0, 0.0, 20.0, 10.0))
    other_furniture = _paragraph("rule", "rule", (90.0, 0.0, 110.0, 10.0))
    page = _page(0, [formula, vertical, furniture, other_furniture])
    page.pdf_figure = [il_version_1.PdfFigure(box=Box(80.0, 70.0, 110.0, 95.0))]
    page.pdf_xobject = [
        il_version_1.PdfXobject(
            box=Box(50.0, 70.0, 75.0, 95.0),
            base_operations=il_version_1.BaseOperations(value="q Q"),
            xobj_id=1,
        )
    ]
    page.pdf_form = [il_version_1.PdfForm(box=Box(5.0, 40.0, 15.0, 50.0))]
    page.pdf_curve = [il_version_1.PdfCurve(box=Box(20.0, 40.0, 40.0, 41.0))]
    page.pdf_rectangle = [
        il_version_1.PdfRectangle(box=Box(45.0, 40.0, 60.0, 50.0))
    ]
    page.pdf_character = [
        il_version_1.PdfCharacter(
            box=Box(65.0, 40.0, 70.0, 50.0), char_unicode="A"
        )
    ]
    document = il_version_1.Document(page=[page], total_pages=1)
    elements = (
        source_element(
            "p1#0",
            page=1,
            column=0,
            reading_order=0,
            box=(0.0, 60.0, 25.0, 75.0),
        ),
        source_element(
            "p1#1",
            page=1,
            column=1,
            reading_order=1,
            box=(30.0, 50.0, 45.0, 80.0),
        ),
    )
    article_document_ir = canonical_ir(
        elements,
        (region_slot(page=1, column=0, slot_order=0, box=(0.0, 60.0, 25.0, 75.0)),),
    )
    return document, article_document_ir


def test_inventory_covers_all_fixed_assets_and_is_stable():
    document, article_document_ir = asset_fixture()

    inventory = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    repeated = fixed_assets.build_inventory(
        copy.deepcopy(document), article_document_ir=article_document_ir
    )

    assert inventory == repeated
    assert {
        "p1:pdf_figure#0",
        "p1:pdf_xobject#0",
        "p1:pdf_form#0",
        "p1:pdf_curve#0",
        "p1:pdf_rectangle#0",
        "p1:pdf_character#0",
        "p1#0:pdf_formula#0",
        "p1#0:pdf_formula#0:pdf_curve#0",
        "p1#0:pdf_formula#0:pdf_form#0",
        "p1#1",
        "p1#2",
        "p1#3",
    }.issubset(inventory.by_ref)
    assert inventory.by_ref["p1#1"].asset_type == fixed_assets.ROTATED_PARAGRAPH_TYPE
    assert inventory.by_ref["p1#2"].asset_type == fixed_assets.FURNITURE_TYPE
    assert inventory.page_sizes == (
        (1, (0.0, 0.0, 120.0, 100.0), (0.0, 0.0, 120.0, 100.0)),
    )


@pytest.mark.parametrize(
    ("mutation", "evidence"),
    (
        (
            lambda document: setattr(document.page[0].pdf_xobject[0], "xobj_id", 99),
            "digest_changed",
        ),
        (
            lambda document: setattr(document.page[0].pdf_figure[0].box, "x", 79.0),
            "bbox_changed",
        ),
        (
            lambda document: document.page[0].pdf_figure.append(
                il_version_1.PdfFigure(box=Box(1.0, 1.0, 2.0, 2.0))
            ),
            "added",
        ),
        (
            lambda document: setattr(document.page[0].mediabox.box, "x2", 121.0),
            "page_size_changed",
        ),
    ),
)
def test_compare_detects_content_bbox_count_and_page_shell_drift(mutation, evidence):
    document, article_document_ir = asset_fixture()
    before = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    changed = copy.deepcopy(document)
    mutation(changed)

    comparison = fixed_assets.compare(
        before,
        fixed_assets.build_inventory(
            changed, article_document_ir=article_document_ir
        ),
        0.000001,
    )

    assert not comparison.holds
    assert getattr(comparison, evidence)


def test_formula_character_content_is_part_of_the_formula_digest():
    document, article_document_ir = asset_fixture()
    before = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    changed = copy.deepcopy(document)
    formula = changed.page[0].pdf_paragraph[0].pdf_paragraph_composition[0].pdf_formula
    formula.pdf_character[0].char_unicode = "y"

    comparison = fixed_assets.compare(
        before,
        fixed_assets.build_inventory(
            changed, article_document_ir=article_document_ir
        ),
        0.000001,
    )

    assert "p1#0:pdf_formula#0" in comparison.digest_changed


def test_flow_owned_refs_are_explicit_and_unknown_refs_remain_furniture():
    document, article_document_ir = asset_fixture()
    default = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    explicit = fixed_assets.build_inventory(
        document,
        article_document_ir=article_document_ir,
        flow_owned_paragraph_refs=("p1#2",),
    )

    assert "p1#2" in default.protected_paragraph_refs
    assert "p1#2" not in explicit.protected_paragraph_refs
    assert "p1#3" in explicit.protected_paragraph_refs
    assert explicit.by_ref["p1#3"].asset_type == fixed_assets.FURNITURE_TYPE


@pytest.mark.parametrize("reference", ("p0#1", "p1", "p1#x", 42))
def test_flow_owned_ref_format_fails_fast(reference):
    document, article_document_ir = asset_fixture()

    with pytest.raises(ValueError, match="invalid flow-owned paragraph ref"):
        fixed_assets.build_inventory(
            document,
            article_document_ir=article_document_ir,
            flow_owned_paragraph_refs=(reference,),
        )
