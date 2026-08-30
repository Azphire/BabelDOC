from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine import title_typeset
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import SourceElementRef
from tests.minimal.fakes import FixedWidthFont
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph
from tests.minimal.fakes import document_digest
from tools.verify_magazine_demo import VerificationError
from tools.verify_magazine_demo import verify_title


class RenderFont(FixedWidthFont):
    @staticmethod
    def has_glyph(_codepoint: int) -> int:
        return 1


class RenderMapper(FixedWidthMapper):
    def __init__(self) -> None:
        self.base_font = RenderFont()
        self.fontid2font = {self.base_font.font_id: self.base_font}


class FullWidthRenderFont(RenderFont):
    @staticmethod
    def char_lengths(text: str, font_size: float):
        return tuple(font_size for _character in text)


class FullWidthRenderMapper(FixedWidthMapper):
    def __init__(self) -> None:
        self.base_font = FullWidthRenderFont()
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


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _article_ir(
    paragraphs,
    boxes,
    *,
    roles=None,
    runtime_chain_id: str | None = None,
) -> ArticleDocumentIR:
    roles = roles or ["title"] * len(paragraphs)
    elements = tuple(
        SourceElementRef(
            source_ref=f"p1#{index}",
            page=1,
            column=0,
            reading_order=index,
            role=role,
            source_box=box,
            source_text_hash=_sha256(paragraph.unicode),
            style_hash=f"style-{index}",
        )
        for index, (paragraph, box, role) in enumerate(
            zip(paragraphs, boxes, roles, strict=True)
        )
    )
    canonical_chain_id = "canonical-title" if runtime_chain_id else None
    article = ArticleIR(
        article_id="article-1",
        pages=(1,),
        elements=elements,
        slots=(),
        chain_ids=(() if canonical_chain_id is None else (canonical_chain_id,)),
        policy_evidence=(),
    )
    refs = tuple(item.source_ref for item in elements)
    return ArticleDocumentIR(
        articles=(article,),
        by_page={1: article.article_id},
        by_element=dict.fromkeys(refs, article.article_id),
        by_chain=(
            {} if canonical_chain_id is None else {canonical_chain_id: article.article_id}
        ),
        by_chain_member=(
            {}
            if canonical_chain_id is None
            else dict.fromkeys(refs, canonical_chain_id)
        ),
    )


def _document(paragraphs):
    return il_version_1.Document(page=[_page(0, list(paragraphs))], total_pages=1)


def _run_title(
    monkeypatch,
    tmp_path: Path,
    target: str,
    paragraph,
    source_box,
    mapper=None,
):
    document = _document([paragraph])
    article_ir = _article_ir([paragraph], [source_box])
    config = Config(tmp_path, target)
    typesetter = Typesetting(config, mapper or RenderMapper())
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)
    title_typeset.prepare(config, document, article_ir, typesetter)

    # Formal Typesetting is deliberately allowed to alter the current holder.
    # The title pass must use the frozen pre-formal ArticleIR box and the same
    # formal Typesetting/font mapper object.
    typesetter.render_page(document.page[0])
    report = title_typeset.apply(config, document, typesetter)
    return report, document, typesetter


@pytest.mark.parametrize(
    ("target", "width"),
    [
        ("童眼看流亡", 70.0),
        ("世界知识产权青年大使", 110.0),
    ],
)
def test_required_chinese_titles_are_complete_single_lines(
    monkeypatch, tmp_path, target, width
):
    source_box = (5.0, 50.0, width, 70.0)
    paragraph = _paragraph(target, "zh-title", source_box, label="title")
    paragraph.xobj_id = -1

    report, _document_value, _typesetter = _run_title(
        monkeypatch, tmp_path, "zh-CN", paragraph, source_box
    )

    row = report["titles"][0]
    assert report["same_formal_typesetter"] is True
    assert report["policy"] == {"minimum_scale": 0.4, "maximum_lines": 1}
    assert row["source_box"] == list(source_box)
    assert row["final_holder_box"] == list(source_box)
    assert row["lines"] == 1
    assert row["target_sha256"] == _sha256(target)
    assert row["rendered_target_sha256"] == _sha256(target)
    assert paragraph.unicode == target


def test_fd_chinese_title_uses_direction_minimum_scale_without_expansion(
    monkeypatch, tmp_path
):
    target = "重新思考自由贸易"
    source_box = (38.588, 144.688, 151.036, 210.32)
    paragraph = _paragraph(target, "fd-title", source_box, label="title")
    paragraph.xobj_id = -1
    paragraph.pdf_style.font_size = 32.0
    holder = paragraph.pdf_paragraph_composition[0]
    holder.pdf_same_style_unicode_characters.pdf_style.font_size = 32.0

    report, _document_value, _typesetter = _run_title(
        monkeypatch,
        tmp_path,
        "zh-CN",
        paragraph,
        source_box,
        FullWidthRenderMapper(),
    )

    row = report["titles"][0]
    rendered = "".join(
        composition.pdf_character.char_unicode
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    )
    assert report["policy"] == {"minimum_scale": 0.4, "maximum_lines": 1}
    assert row["lines"] == 1
    assert row["scale"] >= 0.4 - 1e-9
    assert row["scale"] < 0.5 - 1e-9
    assert rendered == target
    assert row["target_sha256"] == _sha256(target)
    assert row["rendered_target_sha256"] == _sha256(target)
    assert row["source_box"] == list(source_box)
    assert row["final_holder_box"] == list(source_box)
    final_box = row["final_text_box"]
    assert final_box is not None
    assert final_box[0] >= source_box[0] - 1e-3
    assert final_box[1] >= source_box[1] - 1e-3
    assert final_box[2] <= source_box[2] + 1e-3
    assert final_box[3] <= source_box[3] + 1e-3


def test_styled_translation_markup_freezes_plain_visual_target(
    monkeypatch, tmp_path
):
    source_box = (5.0, 50.0, 100.0, 70.0)
    markup = "<style id='1'>铁路？</style><style id='3'>铁路？</style>"
    visible = "铁路？"
    paragraph = _paragraph(markup, "styled-title", source_box, label="title")
    paragraph.xobj_id = -1
    first_style = il_version_1.PdfStyle(
        font_id="body",
        font_size=10.0,
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction="0 g"
        ),
    )
    second_style = il_version_1.PdfStyle(
        font_id="body",
        font_size=10.0,
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction="1 0 0 rg"
        ),
    )
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=first_style,
                    unicode="铁路？",
                )
            )
        ),
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=first_style,
                    unicode="debug overlay",
                    debug_info=True,
                )
            )
        ),
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=second_style,
                    unicode="铁路？",
                )
            )
        ),
    ]

    report, _document_value, _typesetter = _run_title(
        monkeypatch, tmp_path, "zh", paragraph, source_box
    )

    row = report["titles"][0]
    assert row["target_chars"] == 3
    assert row["target_sha256"] == _sha256(visible)
    assert row["rendered_target_sha256"] == _sha256(visible)
    assert row["pre_dedup_visual_target"] == visible * 2
    assert row["pre_dedup_target_chars"] == 6
    assert row["duplicate_layers_dropped"] == 1
    proof = row["target_segments"][0]["duplicate_layer"]
    assert proof["split_composition_index"] == 1
    assert proof["dropped_layer_count"] == 1
    assert proof["style_proof"][0]["kept_style_sequence"] == (
        proof["style_proof"][0]["dropped_style_sequence"]
    )
    assert paragraph.unicode == visible
    rendered = "".join(
        composition.pdf_character.char_unicode
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    )
    assert rendered == visible
    assert "style" not in rendered
    assert "debug" not in rendered

    source = tmp_path / "dedup-source.pdf"
    output = tmp_path / "dedup-output.pdf"
    source.write_bytes(b"dedup-source")
    output.write_bytes(b"dedup-output")
    expectations = tmp_path / "dedup-expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": "synthetic-title-dedup",
                "source_sha256": hashlib.sha256(b"dedup-source").hexdigest(),
                "direction": "en-zh",
                "titles": [{"anchor": "p1#0", "source_box": list(source_box)}],
            }
        ),
        encoding="utf-8",
    )
    assert verify_title(
        expectations, source, output, tmp_path, "en", "zh"
    )["status"] == "pass"

    proof["style_proof"][0]["dropped_style_sequence"][0]["font_size"] = 9.0
    (tmp_path / title_typeset.REPORT_NAME).write_text(
        json.dumps(report), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="duplicate style proof"):
        verify_title(expectations, source, output, tmp_path, "en", "zh")


def test_repeated_wording_inside_one_generated_holder_is_not_deduplicated(
    monkeypatch, tmp_path
):
    target = "铁路？铁路？"
    source_box = (5.0, 50.0, 100.0, 70.0)
    paragraph = _paragraph(target, "one-holder-repeat", source_box, label="title")
    paragraph.xobj_id = -1

    report, _document_value, _typesetter = _run_title(
        monkeypatch, tmp_path, "zh", paragraph, source_box
    )

    row = report["titles"][0]
    assert row["visual_target"] == target
    assert row["target_chars"] == 6
    assert row["duplicate_layers_dropped"] == 0
    assert row["target_segments"][0]["duplicate_layer"] is None
    assert paragraph.unicode == target


def test_equal_composition_text_with_unequal_sizes_is_not_deduplicated(
    monkeypatch, tmp_path
):
    target = "铁路？铁路？"
    source_box = (5.0, 50.0, 100.0, 70.0)
    paragraph = _paragraph(target, "unequal-style-repeat", source_box, label="title")
    paragraph.xobj_id = -1
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=il_version_1.PdfStyle(
                        font_id="body", font_size=10.0
                    ),
                    unicode="铁路？",
                )
            )
        ),
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=il_version_1.PdfStyle(
                        font_id="body", font_size=8.0
                    ),
                    unicode="铁路？",
                )
            )
        ),
    ]

    report, _document_value, _typesetter = _run_title(
        monkeypatch, tmp_path, "zh", paragraph, source_box
    )

    row = report["titles"][0]
    assert row["visual_target"] == target
    assert row["target_chars"] == 6
    assert row["duplicate_layers_dropped"] == 0
    assert row["target_segments"][0]["duplicate_layer"] is None
    assert paragraph.unicode == target


def test_exact_multirun_layers_deduplicate_only_at_the_midpoint(
    monkeypatch, tmp_path
):
    source_box = (5.0, 50.0, 100.0, 70.0)
    paragraph = _paragraph("铁路？铁路？", "multirun-overpaint", source_box, label="title")
    paragraph.xobj_id = -1
    styles = (
        il_version_1.PdfStyle(font_id="body", font_size=10.0),
        il_version_1.PdfStyle(font_id="body", font_size=8.0),
    )
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=styles[position % 2],
                    unicode=text,
                )
            )
        )
        for position, text in enumerate(("铁路", "？", "铁路", "？"))
    ]

    report, _document_value, _typesetter = _run_title(
        monkeypatch, tmp_path, "zh", paragraph, source_box
    )

    row = report["titles"][0]
    proof = row["target_segments"][0]["duplicate_layer"]
    assert row["visual_target"] == "铁路？"
    assert proof["split_composition_index"] == 2
    assert len(proof["style_proof"]) == 2
    assert paragraph.unicode == "铁路？"


def test_formula_carrier_prevents_intra_paragraph_duplicate_guess():
    source_box = (5.0, 50.0, 100.0, 70.0)
    paragraph = _paragraph("A+A+", "formula-repeat", source_box, label="title")
    style = il_version_1.PdfStyle(font_id="body", font_size=10.0)
    formula = il_version_1.PdfFormula(
        box=il_version_1.Box(0.0, 0.0, 5.0, 10.0),
        pdf_character=[
            il_version_1.PdfCharacter(
                pdf_style=style,
                box=il_version_1.Box(0.0, 0.0, 5.0, 10.0),
                char_unicode="+",
                xobj_id=-1,
            )
        ],
        x_offset=0.0,
        y_offset=0.0,
        x_advance=5.0,
    )
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=style,
                    unicode="A",
                )
            )
        ),
        il_version_1.PdfParagraphComposition(pdf_formula=copy.deepcopy(formula)),
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=style,
                    unicode="A",
                )
            )
        ),
        il_version_1.PdfParagraphComposition(pdf_formula=copy.deepcopy(formula)),
    ]

    target, compositions, segment = title_typeset._generated_target(
        paragraph, "p1#0"
    )

    assert target == "A+A+"
    assert len(compositions) == 4
    assert segment["duplicate_layer"] is None


def test_source_only_title_compositions_are_not_claimed_as_generated_target(
    monkeypatch, tmp_path
):
    source_box = (5.0, 50.0, 90.0, 70.0)
    paragraph = _paragraph("SOURCE", "source-only-title", source_box, label="title")
    paragraph.xobj_id = -1
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_character=il_version_1.PdfCharacter(
                pdf_style=paragraph.pdf_style,
                box=il_version_1.Box(5.0, 50.0, 10.0, 60.0),
                char_unicode="S",
                xobj_id=-1,
            )
        )
    ]
    document = _document([paragraph])
    article_ir = _article_ir([paragraph], [source_box])
    config = Config(tmp_path, "zh")
    typesetter = Typesetting(config, RenderMapper())
    before = document_digest(document)
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)

    title_typeset.prepare(config, document, article_ir, typesetter)
    report = title_typeset.apply(config, document, typesetter)

    assert report["titles"] == []
    assert report["exclusions"] == [
        {
            "source_ref": "p1#0",
            "layout_label": "title",
            "reason": "no_generated_target",
        }
    ]
    assert document_digest(document) == before


def test_long_english_title_is_complete_inside_finite_line_limit(
    monkeypatch, tmp_path
):
    target = "The complete translated title remains readable"
    source_box = (5.0, 35.0, 105.0, 75.0)
    paragraph = _paragraph(target, "en-title", source_box, label="paragraph_title")
    paragraph.xobj_id = -1

    report, _document_value, _typesetter = _run_title(
        monkeypatch, tmp_path, "en-GB", paragraph, source_box
    )

    row = report["titles"][0]
    assert report["policy"] == {"minimum_scale": 0.4, "maximum_lines": 3}
    assert 1 < row["lines"] <= 3
    assert row["rendered_target_sha256"] == _sha256(target)
    assert paragraph.unicode == target
    rendered = "".join(
        composition.pdf_character.char_unicode
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    )
    assert rendered == target


def test_wipo_english_title_preserves_wrapped_spaces_in_source_box(
    monkeypatch, tmp_path
):
    target = "Prince of Soca Music in Grenada and Youth Ambassador for WIPO"
    source_box = (41.4017, 542.086, 522.1217, 708.454)
    paragraph = _paragraph(target, "wipo-title", source_box, label="title")
    paragraph.xobj_id = -1
    paragraph.pdf_style.font_size = 24.0
    holder = paragraph.pdf_paragraph_composition[0]
    holder.pdf_same_style_unicode_characters.pdf_style.font_size = 24.0

    report, _document_value, _typesetter = _run_title(
        monkeypatch, tmp_path, "en-GB", paragraph, source_box
    )

    row = report["titles"][0]
    rendered = "".join(
        composition.pdf_character.char_unicode
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    )
    assert rendered == target
    assert rendered.count(" ") == target.count(" ")
    assert 1 < row["lines"] <= 3
    assert row["source_box"] == list(source_box)
    assert row["final_holder_box"] == list(source_box)
    assert row["rendered_target_sha256"] == _sha256(target)
    final_box = row["final_text_box"]
    assert final_box is not None
    assert final_box[0] >= source_box[0] - 1e-3
    assert final_box[1] >= source_box[1] - 1e-3
    assert final_box[2] <= source_box[2] + 1e-3
    assert final_box[3] <= source_box[3] + 1e-3


def test_wipo_article_title_uses_english_minimum_scale_without_expansion(
    monkeypatch, tmp_path
):
    target = "The New Key for Musicians to Build Their Brand"
    source_box = (42.5057, 280.4621, 553.2257, 325.7741)
    paragraph = _paragraph(target, "wipo-article-title", source_box, label="title")
    paragraph.xobj_id = -1
    paragraph.pdf_style.font_size = 48.0
    holder = paragraph.pdf_paragraph_composition[0]
    holder.pdf_same_style_unicode_characters.pdf_style.font_size = 48.0

    report, _document_value, _typesetter = _run_title(
        monkeypatch, tmp_path, "en", paragraph, source_box
    )

    row = report["titles"][0]
    rendered = "".join(
        composition.pdf_character.char_unicode
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    )
    assert report["policy"] == {"minimum_scale": 0.4, "maximum_lines": 3}
    assert row["lines"] == 1
    assert row["scale"] >= 0.4 - 1e-9
    assert row["scale"] < 0.5 - 1e-9
    assert rendered == target
    assert rendered.count(" ") == target.count(" ")
    assert row["target_sha256"] == _sha256(target)
    assert row["rendered_target_sha256"] == _sha256(target)
    assert row["source_box"] == list(source_box)
    assert row["final_holder_box"] == list(source_box)
    final_box = row["final_text_box"]
    assert final_box is not None
    assert final_box[0] >= source_box[0] - 1e-3
    assert final_box[1] >= source_box[1] - 1e-3
    assert final_box[2] <= source_box[2] + 1e-3
    assert final_box[3] <= source_box[3] + 1e-3


def test_toc_records_captions_credits_and_folios_are_excluded_unchanged(
    monkeypatch, tmp_path
):
    labels = ["title", "title", "title", "caption", "credit", "folio"]
    record_kinds = ["single_visual_line", "block", "prose_exempt"]
    boxes = [
        (5.0, 80.0 - index * 12.0, 80.0, 90.0 - index * 12.0)
        for index in range(len(labels))
    ]
    paragraphs = [
        _paragraph(f"target-{index}", f"excluded-{index}", box, label=label)
        for index, (box, label) in enumerate(zip(boxes, labels, strict=True))
    ]
    for paragraph in paragraphs:
        paragraph.xobj_id = -1
    units = {
        id(paragraphs[index]): type(
            "Unit", (), {"record_kind": record_kinds[index]}
        )()
        for index in range(3)
    }
    monkeypatch.setattr(
        title_typeset.line_split,
        "source_unit",
        lambda paragraph, _page: units.get(id(paragraph)),
    )
    document = _document(paragraphs)
    article_ir = _article_ir(paragraphs, boxes)
    config = Config(tmp_path, "zh")
    typesetter = Typesetting(config, RenderMapper())
    before = document_digest(document)

    title_typeset.prepare(config, document, article_ir, typesetter)
    report = title_typeset.apply(config, document, typesetter)

    assert document_digest(document) == before
    assert report["titles"] == []
    assert [item["reason"] for item in report["exclusions"]] == [
        "toc:single_visual_line",
        "toc:block",
        "toc:prose_exempt",
        "caption",
        "credit",
        "folio",
    ]


def test_two_member_title_chain_has_one_complete_owner_and_no_residue(
    monkeypatch, tmp_path
):
    runtime_chain_id = "runtime-title"
    boxes = ((5.0, 55.0, 95.0, 70.0), (5.0, 40.0, 95.0, 55.0))
    fragments = ("完整译文", "只有一个承载者")
    paragraphs = [
        _paragraph(
            fragment,
            f"title-member-{index}",
            box,
            label="title",
            chain_id=runtime_chain_id,
            chain_index=index,
        )
        for index, (fragment, box) in enumerate(zip(fragments, boxes, strict=True))
    ]
    for paragraph in paragraphs:
        paragraph.xobj_id = -1
    document = _document(paragraphs)
    article_ir = _article_ir(
        paragraphs,
        boxes,
        runtime_chain_id=runtime_chain_id,
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
                        "canonical_chain_id": "canonical-title",
                        "pair_class": "title",
                        "outcome": "joint_success",
                        "runtime_source_refs": ["p1#0", "p1#1"],
                        "translation": whole,
                        "ordered_fragments": list(fragments),
                        "whole_target_sha256": _sha256(whole),
                        "source_boxes": [list(box) for box in boxes],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)

    title_typeset.prepare(config, document, article_ir, typesetter)
    typesetter.render_page(document.page[0])
    report = title_typeset.apply(config, document, typesetter)

    row = report["titles"][0]
    assert row["source_box"] == [5.0, 40.0, 95.0, 70.0]
    assert row["member_refs"] == ["p1#0", "p1#1"]
    assert row["suppressed_refs"] == ["p1#1"]
    assert row["suppressed_holders"] == [
        {"source_ref": "p1#1", "final_chars": 0, "composition_count": 0}
    ]
    assert row["target_sha256"] == _sha256(whole)
    assert paragraphs[0].unicode == whole
    assert paragraphs[1].unicode == ""
    assert paragraphs[1].pdf_paragraph_composition == []


def test_cross_page_title_chain_renders_each_fragment_in_its_own_page(
    monkeypatch, tmp_path
):
    runtime_chain_id = "runtime-cross-page-title"
    boxes = ((5.0, 50.0, 95.0, 65.0), (5.0, 50.0, 95.0, 65.0))
    fragments = ("跨頁標題", "完成部分")
    paragraphs = [
        _paragraph(
            fragment,
            f"cross-page-title-{index}",
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
        article_id="article-cross-page-title",
        pages=(1, 2),
        elements=elements,
        slots=(),
        chain_ids=("canonical-cross-page-title",),
        policy_evidence=(),
    )
    refs = tuple(item.source_ref for item in elements)
    article_ir = ArticleDocumentIR(
        articles=(article,),
        by_page={1: article.article_id, 2: article.article_id},
        by_element=dict.fromkeys(refs, article.article_id),
        by_chain={"canonical-cross-page-title": article.article_id},
        by_chain_member=dict.fromkeys(refs, "canonical-cross-page-title"),
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
                        "canonical_chain_id": "canonical-cross-page-title",
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
    assert [row["source_ref"] for row in rows] == list(refs)
    assert [row["member_refs"] for row in rows] == [[refs[0]], [refs[1]]]
    assert all(row["suppressed_refs"] == [] for row in rows)
    assert all(row["chain_member_refs"] == list(refs) for row in rows)
    assert all(row["chain_target_sha256"] == _sha256(whole) for row in rows)
    assert all(row["chain_boundary_kinds"] == ["page"] for row in rows)
    assert "".join(paragraph.unicode for paragraph in paragraphs) == whole
    assert all(paragraph.pdf_paragraph_composition for paragraph in paragraphs)


def test_unproved_title_chain_fails_before_suppressing_any_holder(
    monkeypatch, tmp_path
):
    boxes = ((5.0, 55.0, 95.0, 70.0), (5.0, 40.0, 95.0, 55.0))
    paragraphs = [
        _paragraph(
            "fragment",
            f"member-{index}",
            box,
            label="title",
            chain_id="runtime-title",
            chain_index=index,
        )
        for index, box in enumerate(boxes)
    ]
    document = _document(paragraphs)
    article_ir = _article_ir(
        paragraphs,
        boxes,
        runtime_chain_id="runtime-title",
    )
    config = Config(tmp_path, "zh")
    typesetter = Typesetting(config, RenderMapper())
    before = document_digest(document)
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)

    with pytest.raises(
        title_typeset.TitleTypesetError,
        match="joint-success ownership proof",
    ):
        title_typeset.prepare(config, document, article_ir, typesetter)

    assert document_digest(document) == before


def test_impossible_title_fails_closed_and_restores_post_formal_state(
    monkeypatch, tmp_path
):
    target = "这个标题在最小缩放下仍然无法容纳"
    source_box = (5.0, 50.0, 12.0, 60.0)
    paragraph = _paragraph(target, "overflow-title", source_box, label="title")
    paragraph.xobj_id = -1
    document = _document([paragraph])
    article_ir = _article_ir([paragraph], [source_box])
    config = Config(tmp_path, "zh")
    typesetter = Typesetting(config, RenderMapper())
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)
    title_typeset.prepare(config, document, article_ir, typesetter)
    typesetter.render_page(document.page[0])
    before = document_digest(document)

    # A title that will not fit rolls the pass back whole and is skipped, but it
    # no longer ends the run: the caller gets the failure report instead of an
    # exception, so the document still goes on to produce a PDF.
    returned = title_typeset.apply(config, document, typesetter)
    assert returned["status"] == "failure"

    assert document_digest(document) == before
    report = json.loads(
        (tmp_path / title_typeset.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert report["status"] == "failure"
    assert report["totals"] == {
        "duplicate_layers_dropped": 0,
        "excluded": 0,
        "failure": 1,
        "owners": 1,
        "rolled_back": 0,
        "success": 0,
        "suppressed_trailing_holders": 0,
    }
    assert report["titles"][0]["failure_reason"]


def test_late_title_overflow_rolls_back_every_prior_owner(monkeypatch, tmp_path):
    boxes = ((5.0, 70.0, 95.0, 90.0), (5.0, 20.0, 12.0, 30.0))
    paragraphs = [
        _paragraph("首个标题", "first-owner", boxes[0], label="title"),
        _paragraph(
            "第二个标题在最小缩放下仍然无法容纳",
            "second-owner-overflow",
            boxes[1],
            label="title",
        ),
    ]
    for paragraph in paragraphs:
        paragraph.xobj_id = -1
    paragraphs[0].unicode = (
        "<style id='1'>首个标题</style><style id='3'>首个标题</style>"
    )
    paragraphs[0].pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=il_version_1.PdfStyle(
                        font_id="body", font_size=10.0
                    ),
                    unicode="首个标题",
                )
            )
        )
        for _paint in range(2)
    ]
    document = _document(paragraphs)
    article_ir = _article_ir(paragraphs, boxes)
    config = Config(tmp_path, "zh")
    typesetter = Typesetting(config, RenderMapper())
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)
    title_typeset.prepare(config, document, article_ir, typesetter)
    typesetter.render_page(document.page[0])
    before_document = document_digest(document)
    before_paragraphs = [copy.deepcopy(paragraph) for paragraph in paragraphs]

    # A title that will not fit rolls the pass back whole and is skipped, but it
    # no longer ends the run: the caller gets the failure report instead of an
    # exception, so the document still goes on to produce a PDF.
    returned = title_typeset.apply(config, document, typesetter)
    assert returned["status"] == "failure"

    assert document_digest(document) == before_document
    assert paragraphs == before_paragraphs
    report = json.loads(
        (tmp_path / title_typeset.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert [row["status"] for row in report["titles"]] == [
        "rolled_back",
        "failure",
    ]
    assert report["titles"][0]["duplicate_layers_dropped"] == 1
    assert report["totals"] == {
        "duplicate_layers_dropped": 0,
        "excluded": 0,
        "failure": 1,
        "owners": 2,
        "rolled_back": 1,
        "success": 0,
        "suppressed_trailing_holders": 0,
    }


def test_apply_rejects_a_second_typesetter_instance(monkeypatch, tmp_path):
    source_box = (5.0, 50.0, 90.0, 70.0)
    paragraph = _paragraph("唯一实例", "identity-title", source_box, label="title")
    document = _document([paragraph])
    article_ir = _article_ir([paragraph], [source_box])
    config = Config(tmp_path, "zh")
    formal = Typesetting(config, RenderMapper())
    foreign = Typesetting(config, RenderMapper())
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)
    title_typeset.prepare(config, document, article_ir, formal)

    try:
        with pytest.raises(
            title_typeset.TitleTypesetError,
            match="formal Typesetting identity changed",
        ):
            title_typeset.apply(config, document, foreign)
    finally:
        title_typeset.discard()


def test_pipeline_orders_title_between_formal_layout_and_dropcap(
    monkeypatch, tmp_path
):
    paragraph = _paragraph("target", "pipeline-title", (5.0, 50.0, 90.0, 70.0))
    document = _document([paragraph])
    article_ir = _article_ir([paragraph], [(5.0, 50.0, 90.0, 70.0)])
    config = Config(tmp_path, "zh")
    minimal_pipeline.configure(config)
    state = config.magazine_state
    typesetter = Typesetting(config, RenderMapper())
    state._article_document_ir = article_ir
    state._structure_document_identity = id(document)
    state._translation_prep_completed = True
    state._flow_started = True
    state._flow_completed = True
    state._flow_document_identity = id(document)
    state._typesetter_identity = id(typesetter)
    state._flow_report = {"article_flow_applied": False}
    order = []
    monkeypatch.setattr(
        minimal_pipeline.layout_report,
        "finalize",
        lambda: order.append("layout") or {"status": "success"},
    )
    monkeypatch.setattr(
        minimal_pipeline.title_typeset,
        "apply",
        lambda held_config, held_docs, held_typesetter: (
            order.append("title")
            or {
                "same": held_config is config
                and held_docs is document
                and held_typesetter is typesetter
            }
        ),
    )
    monkeypatch.setattr(
        minimal_pipeline,
        "_refresh_detection_fixed_baseline",
        lambda *_args: order.append("refresh") or object(),
    )
    monkeypatch.setattr(
        minimal_pipeline.drop_cap_render,
        "apply",
        lambda *_args, **_kwargs: order.append("dropcap") or {"status": "success"},
    )
    monkeypatch.setattr(
        minimal_pipeline,
        "_detect_and_repair",
        lambda *_args, **_kwargs: order.append("detect"),
    )

    minimal_pipeline.after_typesetting(config, document, typesetter)

    assert order == ["layout", "title", "refresh", "dropcap", "detect"]


def test_title_verifier_matches_frozen_anchor_and_fails_on_digest_damage(
    monkeypatch, tmp_path
):
    target = "受限标题"
    source_box = (5.0, 50.0, 90.0, 70.0)
    paragraph = _paragraph(target, "verified-title", source_box, label="title")
    paragraph.xobj_id = -1
    work = tmp_path / "work"
    report, _document_value, _typesetter = _run_title(
        monkeypatch, work, "zh", paragraph, source_box
    )
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": "synthetic-title",
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "direction": "en-zh",
                "titles": [{"anchor": "p1#0", "source_box": list(source_box)}],
            }
        ),
        encoding="utf-8",
    )
    (work / "line_split.report.json").write_text(
        json.dumps({"source_units": []}), encoding="utf-8"
    )

    result = verify_title(expectations, source, output, work, "en", "zh")
    assert result == {
        "check": "title",
        "sample_id": "synthetic-title",
        "titles": 1,
        "owners": 1,
        "status": "pass",
    }

    report["titles"][0]["rendered_target_sha256"] = "0" * 64
    (work / title_typeset.REPORT_NAME).write_text(
        json.dumps(report), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="target conservation"):
        verify_title(expectations, source, output, work, "en", "zh")


def test_title_failure_does_not_clear_unrelated_fields(monkeypatch, tmp_path):
    """The transactional snapshot is deliberately narrower than a document copy."""
    target = "无法容纳的标题文本"
    box = (5.0, 50.0, 11.0, 60.0)
    paragraph = _paragraph(target, "field-snapshot", box, label="title")
    paragraph.xobj_id = -1
    document = _document([paragraph])
    document.page[0].base_operations = copy.deepcopy(
        document.page[0].base_operations
    )
    article_ir = _article_ir([paragraph], [box])
    config = Config(tmp_path, "zh")
    typesetter = Typesetting(config, RenderMapper())
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)
    title_typeset.prepare(config, document, article_ir, typesetter)
    untouched = document.page[0].base_operations

    # A title that will not fit rolls the pass back whole and is skipped, but it
    # no longer ends the run: the caller gets the failure report instead of an
    # exception, so the document still goes on to produce a PDF.
    returned = title_typeset.apply(config, document, typesetter)
    assert returned["status"] == "failure"

    assert document.page[0].base_operations is untouched
