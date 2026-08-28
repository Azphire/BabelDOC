from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
    ILTranslatorLLMOnly,
)
from babeldoc.magazine import minimal_detection
from babeldoc.magazine.article_context import EMPTY_CONTEXT
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.chain_builder import ChainBuilder
from babeldoc.magazine.chain_builder import _accepted_edges
from babeldoc.magazine.chain_signals import REASON_NONADJACENT_PHYSICAL_PAGE
from babeldoc.magazine.chain_signals import evaluate_boundary
from babeldoc.magazine.chain_signals import evaluate_column_boundaries
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.chain_translation import plan_chain_translation
from tests.minimal.fakes import Placeholder
from tests.minimal.fakes import RecordingExecutor
from tests.minimal.fakes import RecordingParagraphTracker
from tests.minimal.fakes import RecordingTracker
from tests.minimal.fakes import TranslateInput
from tests.minimal.fakes import make_chain_fixture
from tools.verify_magazine_demo import VerificationError
from tools.verify_magazine_demo import verify_chain

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "tests" / "fixtures" / "demo" / "sample_matrix.json"
PAGE_WIDTH = 600.0
PAGE_HEIGHT = 700.0
CHAR_WIDTH = 6.0


def _expectations():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    return [
        json.loads((ROOT / row["expectations_path"]).read_text(encoding="utf-8"))
        for row in matrix
    ]


def _three_member_fixture(tmp_path, target: str, language: str):
    document, article_ir, paragraphs, translator = make_chain_fixture(target, tmp_path)
    document.page[1].pdf_paragraph = [paragraphs[2]]
    paragraphs = paragraphs[:3]
    article = article_ir.articles[0]
    refs = ("p1#0", "p1#1", "p2#0")
    # Deliberately remove ArticleIR region slots.  Planning must use the three
    # immutable SourceElementRef.source_box values instead.
    article = replace(
        article,
        elements=article.elements[:3],
        slots=(),
    )
    translator.expected_source_boxes = [
        element.source_box for element in article.elements
    ]
    article_ir = ArticleDocumentIR(
        articles=(),
        by_page={},
        by_element={},
        by_chain={},
        by_chain_member={},
        unsupported_pages=(),
    )
    translator.translation_config.lang_out = language
    return document, article_ir, paragraphs, translator


def _ordinary_driver():
    driver = object.__new__(ILTranslatorLLMOnly)
    driver.translation_config = SimpleNamespace(
        raise_if_cancelled=lambda: None,
        min_text_length=1,
        shared_context_cross_split_part=SimpleNamespace(
            first_paragraph=None,
            recent_title_paragraph=None,
        ),
    )
    driver.shared_context_cross_split_part = SimpleNamespace(
        recent_title_paragraph=None,
        snapshot_title_paragraph=lambda paragraph: paragraph,
    )
    driver.mid = 0
    driver.calc_token_count = len
    return driver


def _detector_paragraph(text, debug_id, *, left, bottom):
    characters = []
    for row in range(2):
        y = bottom + (1 - row) * 20.0
        for column, character in enumerate(text):
            characters.append(
                il_version_1.PdfCharacter(
                    char_unicode=character if row else "x",
                    box=il_version_1.Box(
                        x=left + column * CHAR_WIDTH,
                        y=y,
                        x2=left + (column + 1) * CHAR_WIDTH,
                        y2=y + 10.0,
                    ),
                )
            )
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(
            x=left,
            y=bottom,
            x2=left + len(text) * CHAR_WIDTH,
            y2=bottom + 30.0,
        ),
        pdf_style=il_version_1.PdfStyle(font_id="F0", font_size=10.0),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    pdf_character=characters
                )
            )
        ],
        unicode=text,
        debug_id=debug_id,
        layout_label="plain text",
    )


def _detector_page(number, paragraphs):
    frame = il_version_1.Box(0.0, 0.0, PAGE_WIDTH, PAGE_HEIGHT)
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=frame),
        cropbox=il_version_1.Cropbox(box=frame),
        pdf_font=[il_version_1.PdfFont(font_id="F0", name="Test-Regular")],
        pdf_paragraph=paragraphs,
        base_operations=il_version_1.BaseOperations(value=""),
        page_number=number,
        unit="point",
        page_kind="feature",
        page_kind_conf=1.0,
    )


def _policy(_kind):
    # Deliberately false: page classification is a soft prior, while complete
    # paragraph continuity evidence remains authoritative.
    return {
        "chain_eligible": False,
        "preserve_line_structure": False,
        "starts_article": False,
    }


def test_frozen_truth_covers_both_directions_boundaries_and_negatives():
    coverage = {}
    for expectation in _expectations():
        direction = expectation["direction"]
        held = coverage.setdefault(direction, {"transitions": set(), "negative": 0})
        for chain in expectation["chains"]:
            assert chain["role"] == "body"
            held["transitions"].update(chain["transitions"])
            for member in chain["ordered_members"]:
                assert len(member["source_text_sha256"]) == 64
                assert len(member["source_box"]) == 4
        held["negative"] += len(expectation["negative_chain_pairs"])

    assert set(coverage) == {"en-zh", "zh-en"}
    for held in coverage.values():
        assert held["transitions"] == {"cross_column", "cross_page"}
        assert held["negative"] >= 1


@pytest.mark.parametrize(
    ("tail_text", "head_text"),
    (
        ("the unfinished source continues", "into the following body column"),
        (
            "这是尚未结束并继续的正文内容仍然需要继续",
            "进入下一个正文栏并继续完成全部正文内容",
        ),
    ),
)
def test_detector_finds_bilingual_column_and_page_positive(tail_text, head_text):
    config = load_chain_config()
    column_tail = _detector_paragraph(tail_text, "column-tail", left=40, bottom=30)
    column_head = _detector_paragraph(head_text, "column-head", left=330, bottom=600)
    column_page = _detector_page(0, [column_head, column_tail])
    column_verdicts = evaluate_column_boundaries(column_page, 0, _policy, config)
    column_edges, _dropped = _accepted_edges(
        column_verdicts, config["boundary_priority"]
    )
    assert [(edge.tail.paragraph, edge.head.paragraph) for edge in column_edges] == [
        (column_tail, column_head)
    ]

    page_tail = _detector_page(
        1, [_detector_paragraph(tail_text, "page-tail", left=330, bottom=20)]
    )
    page_head = _detector_page(
        2, [_detector_paragraph(head_text, "page-head", left=40, bottom=620)]
    )
    page_verdict = evaluate_boundary(page_tail, page_head, 1, 2, _policy, config)
    page_edges, _dropped = _accepted_edges([page_verdict], config["boundary_priority"])
    assert page_verdict.linked
    assert len(page_edges) == 1


def test_detector_rejects_adjacent_negative_and_nonadjacent_physical_pages():
    config = load_chain_config()
    tail = _detector_paragraph(
        "independent contents record by author", "negative-tail", left=40, bottom=30
    )
    head = _detector_paragraph(
        "Another independent contents record", "negative-head", left=330, bottom=600
    )
    verdicts = evaluate_column_boundaries(
        _detector_page(0, [tail, head]), 0, _policy, config
    )
    edges, _dropped = _accepted_edges(verdicts, config["boundary_priority"])
    assert edges == []

    builder = object.__new__(ChainBuilder)
    builder.config = config
    builder.taxonomy = SimpleNamespace(policy_of=_policy)
    docs = il_version_1.Document(
        page=[_detector_page(0, [tail]), _detector_page(2, [head])],
        total_pages=3,
    )
    page_rows = [row for row in builder._score_boundaries(docs) if row.kind == "page"]
    assert len(page_rows) == 1
    assert page_rows[0].reason == REASON_NONADJACENT_PHYSICAL_PAGE
    assert not page_rows[0].linked


@pytest.mark.parametrize("closer", [")", "）", "]", "】"])
def test_detector_treats_closing_bracket_as_terminal_evidence(closer):
    config = load_chain_config()
    tail = _detector_paragraph(
        f"Image credit (Battistella{closer}",
        "caption-tail",
        left=40,
        bottom=30,
    )
    head = _detector_paragraph(
        "正文从这里开始并形成一个独立的完整段落",
        "body-head",
        left=330,
        bottom=600,
    )

    verdicts = evaluate_column_boundaries(
        _detector_page(7, [tail, head]), 7, _policy, config
    )
    scored = [verdict for verdict in verdicts if verdict.pair == "body->body"]
    edges, _dropped = _accepted_edges(verdicts, config["boundary_priority"])

    assert len(scored) == 1
    assert scored[0].values["tail_no_terminal_punct"] == 0.0
    assert not scored[0].linked
    assert edges == []


@pytest.mark.parametrize(
    ("language", "target"),
    (("zh", "连续正文译文内容"), ("en", "one two three")),
)
def test_three_member_column_page_chain_uses_one_call_and_member_boxes(
    tmp_path, language, target
):
    document, article_ir, paragraphs, translator = _three_member_fixture(
        tmp_path, target, language
    )
    expected_boxes = translator.expected_source_boxes

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    assert len(plan.entries) == 1
    assert len(translator.translate_engine.llm_calls) == 1
    entry = plan.entries[0]
    assert entry.boundary_kinds == ["column", "page"]
    assert all(fragment.text for fragment in entry.allocation.fragments)
    assert "".join(fragment.text for fragment in entry.allocation.fragments) == target
    assert [fragment.box for fragment in entry.allocation.fragments] == expected_boxes
    assert not any(fragment.released for fragment in entry.allocation.fragments)

    # A committed chain is invisible to the ordinary producer on both pages.
    ordinary = _ordinary_driver()
    for page in document.page:
        executor = RecordingExecutor()
        ordinary.process_page(
            page,
            executor,
            tracker=RecordingTracker(),
            translated_ids=set(),
            chain_claim=plan.claim,
        )
        assert not executor.submissions

    plan.apply()
    assert "".join(paragraph.unicode for paragraph in paragraphs) == target
    report = json.loads(
        (tmp_path / "chain_translation.report.json").read_text(encoding="utf-8")
    )
    chain = report["chains"][0]
    assert chain["joint_call_count"] == 1
    assert chain["outcome"] == "joint_success"
    assert chain["fallback_reason"] is None
    assert chain["ordered_fragments"]
    assert chain["source_boxes"] == chain["fragment_boxes"]


def test_sparse_physical_refs_are_reported_without_changing_runtime_refs(tmp_path):
    document, article_ir, _paragraphs, translator = make_chain_fixture(
        "连续译文内容足够", tmp_path
    )
    document.page[0].page_number = 5
    document.page[1].page_number = 6
    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )
    assert len(plan.entries) == 1
    plan.apply()
    report = json.loads(
        (tmp_path / "chain_translation.report.json").read_text(encoding="utf-8")
    )
    chain = report["chains"][0]
    assert chain["ordered_source_refs"] == ["p6#0", "p6#1", "p7#0", "p7#1"]
    assert chain["runtime_source_refs"] == ["p1#0", "p1#1", "p2#0", "p2#1"]
    assert [item["source_ref"] for item in chain["allocation"]["fragments"]] == [
        "p6#0",
        "p6#1",
        "p7#0",
        "p7#1",
    ]
    assert [
        item["runtime_source_ref"] for item in chain["allocation"]["fragments"]
    ] == ["p1#0", "p1#1", "p2#0", "p2#1"]


def test_missing_inline_rich_text_wrapper_degrades_to_base_style(tmp_path):
    target = "完整的连续译文足够分配到三个正文框"
    document, article_ir, paragraphs, translator = _three_member_fixture(
        tmp_path, target, "zh"
    )
    left = "<style id='1'>"
    right = "</style>"
    paragraphs[0].unicode = f"source {left}the{right} member"
    rich_text = SimpleNamespace(
        left_regex_pattern=re.escape(left),
        right_regex_pattern=re.escape(right),
    )
    translator.il_translator.prepared[id(paragraphs[0])] = TranslateInput(
        paragraphs[0].pdf_style, placeholders=[rich_text]
    )

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    assert len(plan.entries) == 1
    assert len(translator.translate_engine.llm_calls) == 1
    assert all(fragment.text for fragment in plan.entries[0].allocation.fragments)
    assert (
        "".join(
            fragment.text for fragment in plan.entries[0].allocation.fragments
        )
        == target
    )
    plan.apply()
    assert "".join(paragraph.unicode for paragraph in paragraphs) == target


@pytest.mark.parametrize("placeholder_kind", ["formula", "original"])
def test_missing_formula_or_original_placeholder_still_fails_closed(
    tmp_path, placeholder_kind
):
    target = "完整的连续译文没有保护标记"
    document, article_ir, paragraphs, translator = _three_member_fixture(
        tmp_path, target, "zh"
    )
    protected_marker = "[[KEEP]]"
    paragraphs[0].unicode = f"source {protected_marker} member"
    translate_input = TranslateInput(paragraphs[0].pdf_style)
    if placeholder_kind == "formula":
        translate_input.placeholders = [Placeholder(protected_marker)]
    else:
        translate_input.original_placeholder_tokens = {protected_marker: 1}
    translator.il_translator.prepared[id(paragraphs[0])] = translate_input

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    assert not plan.entries
    assert not plan.claim
    assert plan.outcomes[0]["fallback_reason"] == "placeholder_bearing"


def test_planning_failure_releases_to_ordinary_once_and_verifier_rejects(
    tmp_path,
):
    document, article_ir, paragraphs, translator = make_chain_fixture(
        "unused", tmp_path
    )
    baseline = minimal_detection.capture_baseline(
        document,
        article_ir,
        labeled_pages=((1, document.page[0]), (2, document.page[1])),
    )
    document.page[0].page_number = 5
    document.page[1].page_number = 6
    translator.translate_engine.response = "not-json"

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    assert not plan.entries
    assert len(plan.claim) == 0
    scheduled = []
    ordinary = _ordinary_driver()
    translated_ids = set()
    for page in document.page:
        executor = RecordingExecutor()
        ordinary.process_page(
            page,
            executor,
            tracker=RecordingTracker(),
            translated_ids=translated_ids,
            chain_claim=plan.claim,
        )
        for _function, args, _kwargs in executor.submissions:
            scheduled.extend(args[0].paragraphs)
    assert {id(paragraph) for paragraph in scheduled} == {
        id(paragraph) for paragraph in paragraphs
    }
    assert len(scheduled) == len(paragraphs)

    plan.apply()
    result = minimal_detection.detect(
        document,
        article_ir,
        baseline,
        language="zh",
        translation_performed=True,
        working_dir=tmp_path,
        sidecar_name="issues.after.json",
        pass_index=1,
    )
    chain_record = result.record["chain_conservation"]
    violations = {
        violation for row in chain_record["records"] for violation in row["violations"]
    }
    assert "non_joint_success" in violations
    report = json.loads(
        (tmp_path / "chain_translation.report.json").read_text(encoding="utf-8")
    )
    assert report["outcomes"][0]["fallback_reason"] == "translation_unavailable"
    assert report["outcomes"][0]["ordered_source_refs"] == [
        "p6#0",
        "p6#1",
        "p7#0",
        "p7#1",
    ]
    assert report["outcomes"][0]["runtime_source_refs"] == [
        "p1#0",
        "p1#1",
        "p2#0",
        "p2#1",
    ]
    assert report["skips"] == []


class _ShortParagraphTracker(RecordingParagraphTracker):
    def set_pdf_unicode(self, _value):
        pass

    def set_input(self, _value):
        pass

    def set_placeholders(self, _value):
        pass

    def set_original_placeholders(self, _value):
        pass


class _ShortTracker(RecordingTracker):
    def new_paragraph(self):
        return _ShortParagraphTracker()


def test_released_short_members_enter_short_unit_once(tmp_path):
    document, article_ir, paragraphs, translator = make_chain_fixture(
        "unused", tmp_path
    )
    for index, paragraph in enumerate(paragraphs):
        paragraph.unicode = "Label"
        paragraph.box.y = index * 20.0
        paragraph.box.y2 = index * 20.0 + 10.0
    translator.translation_config.magazine_short_unit = True
    translator.translation_config.min_text_length = 10
    translator.translation_config.input_file = None
    translator.il_translator.translation_config = SimpleNamespace(
        disable_rich_text_translate=False
    )
    translator.il_translator.support_llm_translate = True

    def get_translate_input(paragraph, _fonts, _disable):
        item = TranslateInput(paragraph.pdf_style)
        item.unicode = paragraph.unicode
        return item

    translator.il_translator.get_translate_input = get_translate_input
    responses = iter(
        (
            "not-json",
            json.dumps(
                [{"id": 0, "output": "甲"}, {"id": 1, "output": "乙"}],
                ensure_ascii=False,
            ),
            json.dumps(
                [{"id": 0, "output": "丙"}, {"id": 1, "output": "丁"}],
                ensure_ascii=False,
            ),
        )
    )

    def translate(prompt, **kwargs):
        translator.translate_engine.llm_calls.append((prompt, kwargs))
        return next(responses)

    translator.translate_engine.llm_translate = translate
    plan = plan_chain_translation(
        translator, document, _ShortTracker(), EMPTY_CONTEXT, article_ir
    )

    assert not plan.entries
    assert len(plan.short_units.units) == len(paragraphs)
    assert len(translator.translate_engine.llm_calls) == 3
    assert len(plan.claim) == len(paragraphs)
    assert {record.taken_by for record in plan.claim.records()} == {"short_unit"}
    plan.apply()
    assert [paragraph.unicode for paragraph in paragraphs] == ["甲", "乙", "丙", "丁"]


def test_chain_verifier_checks_truth_translation_and_ordinary_exclusion(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"synthetic-source")
    output.write_bytes(b"synthetic-output")
    work = tmp_path / "work"
    work.mkdir()
    truth_refs = ("p5#1", "p5#2")
    refs = ("p5#7", "p5#8")
    boxes = ([10.0, 182.9865, 30.0, 200.0], [40.0, 50.0, 60.0, 70.0])
    actual_boxes = (
        [10.0, 182.9864999999998, 30.0, 200.0],
        [40.0, 50.0, 60.0, 70.0],
    )
    hashes = ("a" * 64, "b" * 64)
    expectations = {
        "sample_id": "synthetic",
        "direction": "en-zh",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "chains": [
            {
                "id": "truth",
                "role": "body",
                "ordered_members": [
                    {
                        "physical_page": 5,
                        "source_text_sha256": hashes[index],
                        "source_box": boxes[index],
                        "diagnostic_ref": f"styles_and_formulas.json:{reference}",
                    }
                    for index, reference in enumerate(truth_refs)
                ],
                "transitions": ["cross_column"],
            }
        ],
        "negative_chain_pairs": [],
    }
    expectations_path = tmp_path / "expectations.json"
    expectations_path.write_text(json.dumps(expectations), encoding="utf-8")
    detector_chain = {
        "chain_id": "raw",
        "members": [
            {
                "source_ref": reference,
                "physical_page": 5,
                "source_text_sha256": hashes[index],
                "source_box": actual_boxes[index],
                "role": "plain text",
                "chain_index": index,
                "order": index,
            }
            for index, reference in enumerate(refs)
        ],
    }
    detector_report = {"chains": [detector_chain]}
    (work / "chain_report.json").write_text(
        json.dumps(detector_report), encoding="utf-8"
    )
    fragments = ["译文", "继续"]
    whole_hash = hashlib.sha256("".join(fragments).encode("utf-8")).hexdigest()
    translated_chain = {
        "chain_id": "raw",
        "ordered_source_refs": list(refs),
        "runtime_source_refs": ["p2#1", "p2#2"],
        "source_boxes": list(actual_boxes),
        "merged_source_sha256": "c" * 64,
        "joint_call_count": 1,
        "whole_target_sha256": whole_hash,
        "ordered_fragments": fragments,
        "fragment_boxes": list(actual_boxes),
        "boundary_kinds": ["column"],
        "members": [
            {
                "source_ref": reference,
                "runtime_source_ref": f"p2#{index + 1}",
                "chain_index": index,
            }
            for index, reference in enumerate(refs)
        ],
        "outcome": "joint_success",
        "fallback_reason": None,
    }
    translation_report = {
        "applied": True,
        "chains": [translated_chain],
        "outcomes": [translated_chain],
        "skips": [
            {
                "chain_id": "raw",
                "chain_index": index,
                "taken_by": "chain",
                "declined_by": (
                    ["page_batch"]
                    if index == 0
                    else ["cross_column", "page_batch"]
                ),
            }
            for index in range(2)
        ],
    }
    (work / "chain_translation.report.json").write_text(
        json.dumps(translation_report, ensure_ascii=False), encoding="utf-8"
    )
    trace_report = {
        "requests": [
            {
                "request_kind": "continuity_chain",
                "ordered_source_refs": ["p2#1", "p2#2"],
            }
        ]
    }
    (work / "run_trace.report.json").write_text(
        json.dumps(trace_report), encoding="utf-8"
    )

    result = verify_chain(expectations_path, source, output, work, "en", "zh")
    assert result["status"] == "pass"

    missing_page_batch = json.loads(json.dumps(translation_report))
    missing_page_batch["skips"][0]["declined_by"] = ["cross_column"]
    (work / "chain_translation.report.json").write_text(
        json.dumps(missing_page_batch), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="skip does not prove exclusion"):
        verify_chain(expectations_path, source, output, work, "en", "zh")
    (work / "chain_translation.report.json").write_text(
        json.dumps(translation_report), encoding="utf-8"
    )

    (work / "run_trace.report.json").unlink()
    result = verify_chain(expectations_path, source, output, work, "en", "zh")
    assert result["status"] == "pass"
    (work / "run_trace.report.json").write_text(
        json.dumps(trace_report), encoding="utf-8"
    )

    trace = json.loads((work / "run_trace.report.json").read_text(encoding="utf-8"))
    trace["requests"].append(
        {"request_kind": "page_batch", "ordered_source_refs": ["p2#1"]}
    )
    (work / "run_trace.report.json").write_text(json.dumps(trace), encoding="utf-8")
    with pytest.raises(VerificationError, match="ordinary producer"):
        verify_chain(expectations_path, source, output, work, "en", "zh")

    # Restore the passing trace before exercising independent fail-closed
    # sidecar cases.
    (work / "run_trace.report.json").write_text(
        json.dumps(trace_report), encoding="utf-8"
    )

    (work / "chain_report.json").write_text(
        json.dumps({"chains": [detector_chain, detector_chain]}), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="duplicate detector chain"):
        verify_chain(expectations_path, source, output, work, "en", "zh")
    (work / "chain_report.json").write_text(
        json.dumps(detector_report), encoding="utf-8"
    )

    ambiguous_expectations = json.loads(json.dumps(expectations))
    second_truth = json.loads(json.dumps(expectations["chains"][0]))
    second_truth["id"] = "nearby-truth"
    second_truth["ordered_members"][0]["source_box"][1] += 0.0015
    ambiguous_expectations["chains"].append(second_truth)
    expectations_path.write_text(
        json.dumps(ambiguous_expectations), encoding="utf-8"
    )
    ambiguous_detector = json.loads(json.dumps(detector_report))
    ambiguous_detector["chains"][0]["members"][0]["source_box"][1] += 0.00075
    (work / "chain_report.json").write_text(
        json.dumps(ambiguous_detector), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="ambiguous detector truth match"):
        verify_chain(expectations_path, source, output, work, "en", "zh")
    expectations_path.write_text(json.dumps(expectations), encoding="utf-8")
    (work / "chain_report.json").write_text(
        json.dumps(detector_report), encoding="utf-8"
    )

    extended_expectations = json.loads(json.dumps(expectations))
    third_truth_ref = "p5#3"
    third_ref = "p5#9"
    third_member = {
        "physical_page": 5,
        "source_text_sha256": "d" * 64,
        "source_box": [70.0, 80.0, 90.0, 100.0],
        "diagnostic_ref": f"styles_and_formulas.json:{third_truth_ref}",
    }
    extended_expectations["chains"][0]["ordered_members"].append(third_member)
    extended_expectations["negative_chain_pairs"] = [
        {
            "endpoints": [
                extended_expectations["chains"][0]["ordered_members"][1],
                extended_expectations["chains"][0]["ordered_members"][0],
            ]
        }
    ]
    expectations_path.write_text(json.dumps(extended_expectations), encoding="utf-8")
    extended_detector = json.loads(json.dumps(detector_chain))
    extended_detector["members"].append(
        {
            "source_ref": third_ref,
            "physical_page": 5,
            "source_text_sha256": third_member["source_text_sha256"],
            "source_box": third_member["source_box"],
            "role": "plain text",
            "chain_index": 2,
            "order": 2,
        }
    )
    (work / "chain_report.json").write_text(
        json.dumps({"chains": [extended_detector]}), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="negative endpoints formed"):
        verify_chain(expectations_path, source, output, work, "en", "zh")
    expectations_path.write_text(json.dumps(expectations), encoding="utf-8")
    (work / "chain_report.json").write_text(
        json.dumps(detector_report), encoding="utf-8"
    )

    duplicate_translation = json.loads(json.dumps(translation_report))
    duplicate_translation["chains"].append(translated_chain)
    (work / "chain_translation.report.json").write_text(
        json.dumps(duplicate_translation), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="duplicate translated chain"):
        verify_chain(expectations_path, source, output, work, "en", "zh")

    duplicate_outcome = json.loads(json.dumps(translation_report))
    duplicate_outcome["outcomes"].append(translated_chain)
    (work / "chain_translation.report.json").write_text(
        json.dumps(duplicate_outcome), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="duplicate translation outcome"):
        verify_chain(expectations_path, source, output, work, "en", "zh")

    fallback = json.loads(json.dumps(translation_report))
    fallback["chains"] = []
    fallback["outcomes"][0]["outcome"] = "failed_with_issue"
    fallback["outcomes"][0]["fallback_reason"] = "chain_target_overflow"
    fallback["outcomes"][0]["whole_target_sha256"] = None
    (work / "chain_translation.report.json").write_text(
        json.dumps(fallback), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="truth chain fallback.*overflow"):
        verify_chain(expectations_path, source, output, work, "en", "zh")

    wrong_outcome = json.loads(json.dumps(translation_report))
    wrong_outcome["outcomes"][0]["ordered_source_refs"] = ["p5#8", "p5#9"]
    (work / "chain_translation.report.json").write_text(
        json.dumps(wrong_outcome), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="unadjudicated translation outcome"):
        verify_chain(expectations_path, source, output, work, "en", "zh")

    invalid_hash = json.loads(json.dumps(translation_report))
    invalid_hash["chains"][0]["merged_source_sha256"] = "not-a-sha"
    (work / "chain_translation.report.json").write_text(
        json.dumps(invalid_hash), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="invalid merged_source_sha256"):
        verify_chain(expectations_path, source, output, work, "en", "zh")

    mismatched_refs = json.loads(json.dumps(translation_report))
    mismatched_refs["chains"][0]["runtime_source_refs"] = ["p2#1"]
    (work / "chain_translation.report.json").write_text(
        json.dumps(mismatched_refs), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="physical/runtime ref mismatch"):
        verify_chain(expectations_path, source, output, work, "en", "zh")

    (work / "chain_translation.report.json").write_text(
        json.dumps(translation_report), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="language direction disagrees"):
        verify_chain(expectations_path, source, output, work, "zh", "en")
