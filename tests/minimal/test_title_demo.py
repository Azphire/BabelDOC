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
):
    document = _document([paragraph])
    article_ir = _article_ir([paragraph], [source_box])
    config = Config(tmp_path, target)
    typesetter = Typesetting(config, RenderMapper())
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
    assert report["policy"] == {"minimum_scale": 0.5, "maximum_lines": 1}
    assert row["source_box"] == list(source_box)
    assert row["final_holder_box"] == list(source_box)
    assert row["lines"] == 1
    assert row["target_sha256"] == _sha256(target)
    assert row["rendered_target_sha256"] == _sha256(target)
    assert paragraph.unicode == target


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
    assert report["policy"] == {"minimum_scale": 0.5, "maximum_lines": 3}
    assert 1 < row["lines"] <= 3
    assert row["rendered_target_sha256"] == _sha256(target)
    assert paragraph.unicode == target
    rendered = "".join(
        composition.pdf_character.char_unicode
        for composition in paragraph.pdf_paragraph_composition
        if composition.pdf_character is not None
    )
    assert rendered == target


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

    with pytest.raises(title_typeset.TitleTypesetError, match="does not fit"):
        title_typeset.apply(config, document, typesetter)

    assert document_digest(document) == before
    report = json.loads((tmp_path / title_typeset.REPORT_NAME).read_text())
    assert report["status"] == "failure"
    assert report["totals"] == {
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
    document = _document(paragraphs)
    article_ir = _article_ir(paragraphs, boxes)
    config = Config(tmp_path, "zh")
    typesetter = Typesetting(config, RenderMapper())
    monkeypatch.setattr(title_typeset.line_split, "source_unit", lambda *_args: None)
    title_typeset.prepare(config, document, article_ir, typesetter)
    typesetter.render_page(document.page[0])
    before_document = document_digest(document)
    before_paragraphs = [copy.deepcopy(paragraph) for paragraph in paragraphs]

    with pytest.raises(title_typeset.TitleTypesetError, match="does not fit"):
        title_typeset.apply(config, document, typesetter)

    assert document_digest(document) == before_document
    assert paragraphs == before_paragraphs
    report = json.loads((tmp_path / title_typeset.REPORT_NAME).read_text())
    assert [row["status"] for row in report["titles"]] == [
        "rolled_back",
        "failure",
    ]
    assert report["totals"] == {
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
        lambda *_args: order.append("detect"),
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

    with pytest.raises(title_typeset.TitleTypesetError):
        title_typeset.apply(config, document, typesetter)

    assert document.page[0].base_operations is untouched
