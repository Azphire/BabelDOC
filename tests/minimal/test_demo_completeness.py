from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.il_translator import (
    DocumentTranslateTracker,
)
from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator
from babeldoc.magazine import demo_coverage
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine.article_ir import ArticleDocumentIR

from tools import verify_magazine_demo


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Config:
    def __init__(self, working_dir: Path):
        self.working_dir = working_dir
        self.lang_in = "en"
        self.lang_out = "zh"
        self.page_ranges = None

    def get_working_file_path(self, name: str) -> str:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return str(self.working_dir / name)


def _paragraph(text: str, *, label: str = "plain text", vertical=False):
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(x=10, y=20, x2=210, y2=80),
        unicode=text,
        layout_label=label,
        vertical=vertical,
        pdf_paragraph_composition=[],
    )


def _snapshot() -> demo_coverage.CoverageSnapshot:
    specs = (
        ("p1#0", "p7#0", "chain", False, True),
        ("p1#1", "p7#1", "body", False, False),
        ("p1#2", "p7#2", "folio", True, False),
        ("p1#3", "p7#3", "body", False, False),
    )
    return demo_coverage.CoverageSnapshot(
        tuple(
            demo_coverage.FrozenCoverageItem(
                runtime_source_ref=runtime_ref,
                source_ref=source_ref,
                physical_page=7,
                role=role,
                source_text_sha256=_sha(source_ref),
                source_box=(10.0, 20.0, 210.0, 80.0),
                preserve_candidate=preserve,
                chain_member=chain,
            )
            for runtime_ref, source_ref, role, preserve, chain in specs
        ),
        {},
    )


def _write_outcomes(tmp_path: Path, *, duplicate_chain_ordinary=False) -> None:
    cross_column = [
        {
            "source_ref": "p7#1",
            "runtime_source_ref": "p1#1",
            "input": "source",
            "output": "目标",
            "pdf_unicode": "source",
        }
    ]
    ordinary = []
    if duplicate_chain_ordinary:
        ordinary.append(
            {
                "source_ref": "p7#0",
                "runtime_source_ref": "p1#0",
                "input": "chain source",
                "output": "错误的普通翻译",
                "pdf_unicode": "chain source",
            }
        )
    (tmp_path / "translate_tracking.json").write_text(
        json.dumps(
            {
                "page": [{"paragraph": ordinary}],
                # Chain members use the shared historical cross-page tracker;
                # this row must not be counted as ordinary ownership.
                "cross_page": [
                    {
                        "paragraph": [
                            {
                                "source_ref": "p7#0",
                                "runtime_source_ref": "p1#0",
                                "input": "chain source",
                                "output": "联合目标",
                                "pdf_unicode": "chain source",
                            }
                        ]
                    }
                ],
                "cross_column": [{"paragraph": cross_column}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "chain_translation.report.json").write_text(
        json.dumps(
            {
                "chains": [
                    {
                        "runtime_source_refs": ["p1#0"],
                        "ordered_source_refs": ["p7#0"],
                        "ordered_fragments": ["联合目标"],
                        "outcome": "joint_success",
                        "joint_call_count": 1,
                        "fallback_reason": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_coverage_report_joins_mutually_exclusive_owners(tmp_path: Path) -> None:
    _write_outcomes(tmp_path)
    report = demo_coverage.finalize(Config(tmp_path), _snapshot())

    assert report["schema_version"] == "demo-coverage.v1"
    assert report["status"] == "complete"
    assert report["direction"] == "en-zh"
    assert report["totals"] == {
        "sources": 4,
        "owners": {"joint": 1, "ordinary": 1, "preserve": 1, "none": 1},
    }
    by_ref = {row["source_ref"]: row for row in report["items"]}
    assert by_ref["p7#0"]["runtime_source_ref"] == "p1#0"
    assert by_ref["p7#0"]["translation_owner"] == "joint"
    assert by_ref["p7#0"]["final_status"] == "joint_success"
    assert by_ref["p7#0"]["target_text_sha256"] == _sha("联合目标")
    assert by_ref["p7#1"]["translation_owner"] == "ordinary"
    assert by_ref["p7#1"]["final_status"] == "translated"
    assert by_ref["p7#2"]["translation_owner"] == "preserve"
    assert by_ref["p7#2"]["target_text_sha256"] is None
    assert by_ref["p7#3"]["translation_owner"] == "none"
    assert by_ref["p7#3"]["final_status"] == "untranslated"
    required = {
        "source_ref",
        "physical_page",
        "role",
        "source_text_sha256",
        "source_box",
        "translation_owner",
        "target_text_sha256",
        "final_status",
    }
    assert all(required <= set(row) for row in report["items"])
    assert json.loads((tmp_path / demo_coverage.REPORT_NAME).read_text()) == report


def test_chain_claim_cannot_also_be_owned_by_ordinary_translation(tmp_path: Path) -> None:
    _write_outcomes(tmp_path, duplicate_chain_ordinary=True)
    report = demo_coverage.finalize(Config(tmp_path), _snapshot())
    chain = report["items"][0]
    assert chain["translation_owner"] == "joint"
    assert chain["final_status"] == "duplicate_ownership"


def test_freeze_separates_sparse_physical_and_runtime_refs() -> None:
    first = _paragraph("first body")
    second = _paragraph("second body")
    pages = [
        il_version_1.Page(page_number=4, pdf_paragraph=[first]),
        il_version_1.Page(page_number=8, pdf_paragraph=[second]),
    ]
    docs = il_version_1.Document(page=pages, total_pages=12)
    article_ir = ArticleDocumentIR(
        articles=(),
        by_page={},
        by_element={},
        by_chain={},
        by_chain_member={},
    )

    snapshot = demo_coverage.freeze(docs, article_ir, [(5, pages[0]), (9, pages[1])])

    assert [item.runtime_source_ref for item in snapshot.items] == ["p1#0", "p2#0"]
    assert [item.source_ref for item in snapshot.items] == ["p5#0", "p9#0"]
    assert snapshot.source_refs_for(second) == ("p9#0", "p2#0")


def test_common_pretranslate_path_binds_both_refs_before_skip() -> None:
    paragraph = _paragraph("vertical furniture", vertical=True)
    snapshot = demo_coverage.CoverageSnapshot((), {id(paragraph): ("p9#4", "p2#4")})
    translator = object.__new__(ILTranslator)
    translator.coverage_snapshot = None
    # The driver may be constructed before the structural stage installs the
    # snapshot.  Binding must resolve it at call time, not constructor time.
    translator.translation_config = SimpleNamespace(
        magazine_coverage_snapshot=snapshot
    )
    document_tracker = DocumentTranslateTracker()

    for page_tracker in (
        document_tracker.new_page(),
        document_tracker.new_cross_page(),
        document_tracker.new_cross_column(),
    ):
        tracker = page_tracker.new_paragraph()
        assert translator.pre_translate_paragraph(paragraph, tracker, {}, {}) == (
            None,
            None,
        )
        assert tracker.source_ref == "p9#4"
        assert tracker.runtime_source_ref == "p2#4"


def test_tracker_serializes_physical_and_runtime_refs() -> None:
    document_tracker = DocumentTranslateTracker()
    paragraph_tracker = document_tracker.new_page().new_paragraph()
    paragraph_tracker.set_source_refs("p9#4", "p2#4")
    paragraph_tracker.set_pdf_unicode("source")
    paragraph_tracker.set_input("source")
    paragraph_tracker.set_output("target")

    row = json.loads(document_tracker.to_json())["page"][0]["paragraph"][0]
    assert row["source_ref"] == "p9#4"
    assert row["runtime_source_ref"] == "p2#4"


def test_pipeline_freezes_after_article_builder(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    article_ir = ArticleDocumentIR((), {}, {}, {}, {})
    snapshot = demo_coverage.CoverageSnapshot((), {})

    class Classifier:
        vlm_enabled = False

        def __init__(self, _config):
            pass

        def process(self, _docs):
            events.append("classifier")

    class Builder:
        def __init__(self, _config):
            pass

        def process(self, _docs):
            events.append("article")
            return article_ir

    class Chain:
        def __init__(self, _config):
            pass

        def process(self, _docs):
            events.append("chain")

    monkeypatch.setattr(minimal_pipeline, "PageClassifier", Classifier)
    monkeypatch.setattr(minimal_pipeline, "ChainBuilder", Chain)
    monkeypatch.setattr(minimal_pipeline, "ArticleBuilder", Builder)
    monkeypatch.setattr(minimal_pipeline.hitl, "begin_run", lambda *_: object())
    monkeypatch.setattr(
        minimal_pipeline.hitl,
        "page_kind_pass",
        lambda *_: events.append("page_kind"),
    )
    monkeypatch.setattr(minimal_pipeline.hitl, "labeled_pages", lambda _docs: [])
    monkeypatch.setattr(
        minimal_pipeline.line_split,
        "apply",
        lambda *_: events.append("line_split"),
    )
    monkeypatch.setattr(
        minimal_pipeline.demo_coverage,
        "freeze",
        lambda *_: events.append("coverage_freeze") or snapshot,
    )
    config = Config(tmp_path)
    minimal_pipeline.configure(config)

    minimal_pipeline.after_styles(config, il_version_1.Document(page=[], total_pages=0))

    assert events == [
        "classifier",
        "page_kind",
        "line_split",
        "chain",
        "article",
        "coverage_freeze",
    ]
    assert config.magazine_coverage_snapshot is snapshot


def _pdf(path: Path, *, pages: int, physical_page: int, text: str, cjk: bool) -> None:
    document = pymupdf.open()
    for page_number in range(1, pages + 1):
        page = document.new_page(width=300, height=300)
        held = text if page_number == physical_page else "fixture"
        page.insert_text(
            (20, 40),
            held,
            fontsize=10,
            fontname="china-s" if cjk else "helv",
        )
    document.save(path)
    document.close()


def _verification_fixture(
    tmp_path: Path,
    *,
    sample_id: str,
    source_lang: str,
    target_lang: str,
    physical_page: int,
) -> tuple[Path, Path, Path, Path]:
    source = tmp_path / f"{sample_id}.source.pdf"
    output = tmp_path / f"{sample_id}.target.pdf"
    source_text = (
        "这是用于验证整段源文覆盖关系的中文正文。" * 5
        if source_lang == "zh"
        else "A complete source paragraph must enter the translation coverage. " * 3
    )
    target_text = (
        "这是完整的目标译文。" * 8
        if target_lang == "zh"
        else "This is the complete translated target paragraph. " * 4
    )
    _pdf(
        source,
        pages=physical_page,
        physical_page=physical_page,
        text=source_text,
        cjk=source_lang == "zh",
    )
    _pdf(
        output,
        pages=physical_page,
        physical_page=physical_page,
        text=target_text,
        cjk=target_lang == "zh",
    )
    expectations = tmp_path / f"{sample_id}.expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": sample_id,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "direction": f"{source_lang}-{target_lang}",
                "chains": [],
                "negative_chain_pairs": [],
                "toc_records": [],
                "layout_regions": [],
                "titles": [],
                "dropcaps": [],
                "coverage_exemptions": [],
                "coverage_thresholds": {
                    "source_block_min_characters": 20,
                    "max_source_script_characters": 19,
                },
                "stage_pages": [physical_page],
            }
        ),
        encoding="utf-8",
    )
    source_ref = f"p{physical_page}#0"
    target_hash = _sha(target_text)
    report = {
        "schema_version": "demo-coverage.v1",
        "status": "complete",
        "direction": f"{source_lang}-{target_lang}",
        "source_lang": source_lang,
        "target_lang": target_lang,
        "items": [
            {
                "source_ref": source_ref,
                "runtime_source_ref": "p1#0",
                "physical_page": physical_page,
                "role": "body",
                "source_text_sha256": _sha(source_text),
                "source_box": [0.0, 0.0, 300.0, 300.0],
                "translation_owner": "ordinary",
                "target_text_sha256": target_hash,
                "final_status": "translated",
            }
        ],
        "totals": {
            "sources": 1,
            "owners": {"joint": 0, "ordinary": 1, "preserve": 0, "none": 0},
        },
    }
    (tmp_path / verify_magazine_demo.COVERAGE_REPORT_NAME).write_text(
        json.dumps(report), encoding="utf-8"
    )
    (tmp_path / "translate_tracking.json").write_text(
        json.dumps(
            {
                "page": [
                    {
                        "paragraph": [
                            {
                                "source_ref": source_ref,
                                "runtime_source_ref": "p1#0",
                                "output": target_text,
                            }
                        ]
                    }
                ],
                "cross_page": [],
                "cross_column": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "chain_translation.report.json").write_text(
        json.dumps({"chains": []}), encoding="utf-8"
    )
    return expectations, source, output, tmp_path


@pytest.mark.parametrize(
    ("sample_id", "source_lang", "target_lang", "physical_page"),
    (("amber-journal", "en", "zh", 2), ("jade-review", "zh", "en", 4)),
)
def test_two_directions_pass_coverage_and_independent_pdf_gate(
    tmp_path: Path,
    sample_id: str,
    source_lang: str,
    target_lang: str,
    physical_page: int,
) -> None:
    fixture = _verification_fixture(
        tmp_path,
        sample_id=sample_id,
        source_lang=source_lang,
        target_lang=target_lang,
        physical_page=physical_page,
    )
    assert verify_magazine_demo.verify_coverage(
        *fixture, source_lang, target_lang
    )["status"] == "pass"
    assert verify_magazine_demo.verify_long_blocks_and_pdf(
        *fixture, source_lang, target_lang, (physical_page,)
    )["status"] == "pass"


def test_ordinary_body_without_target_fails_closed(tmp_path: Path) -> None:
    fixture = _verification_fixture(
        tmp_path,
        sample_id="empty-target",
        source_lang="en",
        target_lang="zh",
        physical_page=3,
    )
    path = tmp_path / verify_magazine_demo.COVERAGE_REPORT_NAME
    report = json.loads(path.read_text(encoding="utf-8"))
    report["items"][0]["final_status"] = "empty_target"
    report["items"][0]["target_text_sha256"] = _sha("")
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(verify_magazine_demo.VerificationError, match="finish cleanly"):
        verify_magazine_demo.verify_coverage(*fixture, "en", "zh")


@pytest.mark.parametrize("status", ("joint_failed", "empty_target"))
def test_body_chain_fallback_or_empty_fragment_fails_closed(
    tmp_path: Path, status: str
) -> None:
    fixture = _verification_fixture(
        tmp_path,
        sample_id=f"chain-{status}",
        source_lang="en",
        target_lang="zh",
        physical_page=3,
    )
    path = tmp_path / verify_magazine_demo.COVERAGE_REPORT_NAME
    report = json.loads(path.read_text(encoding="utf-8"))
    row = report["items"][0]
    row["role"] = "chain"
    row["translation_owner"] = "joint"
    row["final_status"] = status
    report["totals"]["owners"] = {
        "joint": 1,
        "ordinary": 0,
        "preserve": 0,
        "none": 0,
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(verify_magazine_demo.VerificationError, match="finish cleanly"):
        verify_magazine_demo.verify_coverage(*fixture, "en", "zh")


def test_joint_member_with_second_tracker_is_duplicate_ordinary_ownership(
    tmp_path: Path,
) -> None:
    fixture = _verification_fixture(
        tmp_path,
        sample_id="duplicate-owner",
        source_lang="en",
        target_lang="zh",
        physical_page=3,
    )
    coverage_path = tmp_path / verify_magazine_demo.COVERAGE_REPORT_NAME
    report = json.loads(coverage_path.read_text(encoding="utf-8"))
    row = report["items"][0]
    row["role"] = "chain"
    row["translation_owner"] = "joint"
    row["final_status"] = "joint_success"
    report["totals"]["owners"] = {
        "joint": 1,
        "ordinary": 0,
        "preserve": 0,
        "none": 0,
    }
    coverage_path.write_text(json.dumps(report), encoding="utf-8")
    target_text = "这是完整的目标译文。" * 8
    (tmp_path / "chain_translation.report.json").write_text(
        json.dumps(
            {
                "chains": [
                    {
                        "outcome": "joint_success",
                        "ordered_source_refs": ["p3#0"],
                        "ordered_fragments": [target_text],
                        "members": [{}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    tracking_path = tmp_path / "translate_tracking.json"
    tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
    tracking["cross_column"] = [
        {"paragraph": [dict(tracking["page"][0]["paragraph"][0])]}
    ]
    tracking_path.write_text(json.dumps(tracking), encoding="utf-8")
    with pytest.raises(verify_magazine_demo.VerificationError, match="ordinary ownership"):
        verify_magazine_demo.verify_coverage(*fixture, "en", "zh")


def _stub_core_verifiers(monkeypatch) -> None:
    for name in ("chain", "toc", "layout", "title", "dropcap", "coverage"):
        monkeypatch.setattr(
            verify_magazine_demo,
            f"verify_{name}",
            lambda *_args, held=name: {"check": held, "status": "pass"},
        )


@pytest.mark.parametrize("failed", ("chain", "toc", "layout", "title", "dropcap"))
def test_full_propagates_every_core_gate_failure(
    monkeypatch, tmp_path: Path, failed: str
) -> None:
    fixture = _verification_fixture(
        tmp_path,
        sample_id=f"core-{failed}",
        source_lang="zh",
        target_lang="en",
        physical_page=2,
    )
    _stub_core_verifiers(monkeypatch)

    def reject(*_args):
        raise verify_magazine_demo.VerificationError(f"{failed} core failed")

    monkeypatch.setattr(verify_magazine_demo, f"verify_{failed}", reject)
    with pytest.raises(verify_magazine_demo.VerificationError, match="core failed"):
        verify_magazine_demo.verify_full(*fixture, "zh", "en", (2,))


def test_full_passes_for_both_directions_and_distinct_pages(monkeypatch, tmp_path: Path) -> None:
    _stub_core_verifiers(monkeypatch)
    for sample_id, source_lang, target_lang, physical_page in (
        ("north-window", "en", "zh", 2),
        ("south-window", "zh", "en", 5),
    ):
        sample_dir = tmp_path / sample_id
        sample_dir.mkdir()
        fixture = _verification_fixture(
            sample_dir,
            sample_id=sample_id,
            source_lang=source_lang,
            target_lang=target_lang,
            physical_page=physical_page,
        )
        result = verify_magazine_demo.verify_full(
            *fixture,
            source_lang,
            target_lang,
            (physical_page,),
        )
        assert result["status"] == "pass"
        assert result["checks"]["pdf_completeness"]["status"] == "pass"


def test_full_rejects_long_source_block_absent_from_coverage(
    monkeypatch, tmp_path: Path
) -> None:
    fixture = _verification_fixture(
        tmp_path,
        sample_id="missing-long-block",
        source_lang="en",
        target_lang="zh",
        physical_page=3,
    )
    _stub_core_verifiers(monkeypatch)
    coverage_path = tmp_path / verify_magazine_demo.COVERAGE_REPORT_NAME
    report = json.loads(coverage_path.read_text(encoding="utf-8"))
    report["items"] = []
    report["totals"] = {
        "sources": 0,
        "owners": {"joint": 0, "ordinary": 0, "preserve": 0, "none": 0},
    }
    coverage_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(verify_magazine_demo.VerificationError, match="absent from coverage"):
        verify_magazine_demo.verify_full(*fixture, "en", "zh", (3,))


def test_cli_rejects_target_language_that_disagrees_with_expectations(
    tmp_path: Path, capsys
) -> None:
    expectations, source, output, working_dir = _verification_fixture(
        tmp_path,
        sample_id="direction-check",
        source_lang="en",
        target_lang="zh",
        physical_page=2,
    )
    result = verify_magazine_demo.main(
        [
            "--check",
            "full",
            "--expectations",
            str(expectations),
            "--source",
            str(source),
            "--output",
            str(output),
            "--run-dir",
            str(working_dir),
            "--pages",
            "2",
            "--target-lang",
            "en",
        ]
    )
    assert result == 1
    assert "target language disagrees" in capsys.readouterr().out


def test_verifier_has_no_sample_name_or_frozen_page_special_case() -> None:
    source = Path(verify_magazine_demo.__file__).read_text(encoding="utf-8")
    assert "Courier" not in source
    assert "p7#" not in source
    assert "candidate_count" not in source
