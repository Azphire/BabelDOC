"""The coverage ledger's conservation vocabulary and the enqueue drift guard.

Every frozen source ends a run owned, preserved, skipped for a closed-table
reason, or listed in ``unowned_sources`` -- and an enqueue site that binds a
paragraph whose text drifted since the freeze fails closed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.il_translator import (
    DocumentTranslateTracker,
)
from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator
from babeldoc.magazine import demo_coverage
from babeldoc.magazine.article_ir import ArticleDocumentIR


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Config:
    def __init__(self, working_dir: Path, *, lang_in="zh", lang_out="en", floor=5):
        self.working_dir = working_dir
        self.lang_in = lang_in
        self.lang_out = lang_out
        self.min_text_length = floor
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


def _empty_ir() -> ArticleDocumentIR:
    return ArticleDocumentIR((), {}, {}, {}, {})


def _freeze(paragraphs, furniture_plan=None):
    page = il_version_1.Page(page_number=7, pdf_paragraph=list(paragraphs))
    docs = il_version_1.Document(page=[page], total_pages=7)
    return demo_coverage.freeze(
        docs, _empty_ir(), [(7, page)], furniture_plan=furniture_plan
    )


# --- what the freeze measures -------------------------------------------------


def test_freeze_measures_scripts_length_and_traits() -> None:
    mixed = _paragraph("危机 crisis 42")
    upright = _paragraph("2011")
    sideways = _paragraph("竖排咒文", vertical=True)
    withheld = _paragraph("folio mark")
    withheld.debug_id = "mark1"

    class Plan:
        def withholds(self, debug_id):
            return debug_id == "mark1"

    snapshot = _freeze([mixed, upright, sideways, withheld], furniture_plan=Plan())
    by_ref = {item.source_ref: item for item in snapshot.items}

    assert by_ref["p7#0"].han_chars == 2
    assert by_ref["p7#0"].latin_chars == 6
    assert by_ref["p7#0"].text_length == len("危机 crisis 42")
    assert by_ref["p7#0"].skip_traits == ()
    assert by_ref["p7#1"].han_chars == 0
    assert by_ref["p7#1"].latin_chars == 0
    assert by_ref["p7#2"].skip_traits == ("vertical",)
    assert by_ref["p7#3"].skip_traits == ("furniture_withheld",)


# --- the closed skip vocabulary and the unowned list --------------------------


def test_finalize_names_every_skip_and_lists_the_unowned(tmp_path: Path) -> None:
    digits = _paragraph("2011")
    short_han = _paragraph("编者的话")
    long_han = _paragraph("这一段够长却谁也没有认领")
    sideways = _paragraph("竖排的字", vertical=True)
    snapshot = _freeze([digits, short_han, long_han, sideways])

    report = demo_coverage.finalize(Config(tmp_path), snapshot)

    by_ref = {row["source_ref"]: row for row in report["items"]}
    assert report["source_script"] == "han"
    assert by_ref["p7#0"]["skip_reason"] == "no_source_script"
    assert by_ref["p7#1"]["skip_reason"] == "below_length_floor"
    assert by_ref["p7#2"]["skip_reason"] is None
    assert by_ref["p7#3"]["skip_reason"] == "vertical"
    assert report["skip_reason_totals"]["no_source_script"] == 1
    assert report["skip_reason_totals"]["below_length_floor"] == 1
    assert report["skip_reason_totals"]["vertical"] == 1

    assert [entry["source_ref"] for entry in report["unowned_sources"]] == ["p7#2"]
    listed = report["unowned_sources"][0]
    assert listed["source_script_chars"] == len("这一段够长却谁也没有认领")
    assert listed["text_length"] == len("这一段够长却谁也没有认领")
    assert listed["physical_page"] == 7

    written = json.loads(
        (tmp_path / demo_coverage.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert written == report


def test_latin_is_the_source_script_of_an_english_run(tmp_path: Path) -> None:
    label = _paragraph("Contents")
    snapshot = _freeze([label])

    report = demo_coverage.finalize(
        Config(tmp_path, lang_in="en", lang_out="zh"), snapshot
    )

    assert report["source_script"] == "latin"
    assert report["items"][0]["skip_reason"] is None
    assert [e["source_ref"] for e in report["unowned_sources"]] == ["p7#0"]


def test_fully_owned_page_has_no_unowned_and_no_reasons(tmp_path: Path) -> None:
    body = _paragraph("这一段将由普通翻译路径认领下来")
    snapshot = _freeze([body])
    (tmp_path / "translate_tracking.json").write_text(
        json.dumps(
            {
                "page": [
                    {
                        "paragraph": [
                            {
                                "source_ref": "p7#0",
                                "runtime_source_ref": "p1#0",
                                "input": "source",
                                "output": "the target text",
                                "pdf_unicode": "source",
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

    report = demo_coverage.finalize(Config(tmp_path), snapshot)

    assert report["items"][0]["final_status"] == "translated"
    assert report["items"][0]["skip_reason"] is None
    assert report["unowned_sources"] == []
    assert all(count == 0 for count in report["skip_reason_totals"].values())


# --- the drift guard ----------------------------------------------------------


def test_guard_passes_an_unchanged_paragraph_and_fails_a_drifted_one() -> None:
    paragraph = _paragraph("要复兴全球生产力，就要从头说起")
    snapshot = _freeze([paragraph])

    snapshot.assert_source_unchanged(paragraph)

    paragraph.unicode = "要复兴全球生产力"
    with pytest.raises(ValueError, match="drifted.*p7#0"):
        snapshot.assert_source_unchanged(paragraph)


def test_guard_ignores_a_paragraph_the_freeze_never_saw() -> None:
    # The frozen paragraph is kept alive: the snapshot's identity map is keyed
    # by id(), and a collected paragraph would let a newcomer reuse its id.
    frozen_paragraph = _paragraph("已冻结的段落")
    snapshot = _freeze([frozen_paragraph])
    snapshot.assert_source_unchanged(_paragraph("外来的段落"))
    snapshot.assert_source_unchanged(frozen_paragraph)


def test_pre_translate_fails_closed_before_building_any_request() -> None:
    paragraph = _paragraph("这段文本在冻结之后被截断了")
    snapshot = _freeze([paragraph])
    translator = object.__new__(ILTranslator)
    translator.coverage_snapshot = None
    # Nothing beyond the snapshot is supplied: the guard must raise before
    # the method needs fonts, engines, or any other translator state.
    translator.translation_config = SimpleNamespace(
        magazine_coverage_snapshot=snapshot
    )
    tracker = DocumentTranslateTracker().new_page().new_paragraph()

    paragraph.unicode = "这段文本"
    with pytest.raises(ValueError, match="drifted"):
        translator.pre_translate_paragraph(paragraph, tracker, {}, {})
    # The refs were still bound first, so the failure names a source.
    assert tracker.source_ref == "p7#0"
