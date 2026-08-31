"""B18 T4 -- the human-ruled term ladder, levels 2 through 5.

One fixture per level: a ruling already adopted costs nothing; a known
variant is substituted deterministically; an unknown rendering earns one
pinned retranslation; a retranslation that still declines the ruling is
escalated.  The conservation equation names every ruled occurrence exactly
once.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import term_enforce
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph


class Config:
    def __init__(self, work: Path, engine=None) -> None:
        self.work = work
        self.lang_out = "en"
        self.translator = engine

    def get_working_file_path(self, name: str):
        self.work.mkdir(parents=True, exist_ok=True)
        return self.work / name


def _set_translation(paragraph, translated: str) -> None:
    style = paragraph.pdf_style
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=style, unicode=translated
                )
            )
        )
    ]
    paragraph.unicode = translated


def _hitl_state(terms: dict, dropped=None):
    return SimpleNamespace(
        decisions=SimpleNamespace(terms=dict(terms)),
        report={
            "applied": {"terms": {"dropped_from_auto": list(dropped or ())}}
        },
    )


def _pinning_engine(good_sources: dict[str, str]):
    """Replies honour the ruling only for units named in good_sources."""

    def llm_translate(prompt: str, rate_limit_params=None):
        for source, target in good_sources.items():
            if source in prompt:
                return json.dumps(
                    {"output": f"a retranslation carrying {target}"}
                )
        return json.dumps({"output": "a retranslation still declining"})

    return SimpleNamespace(llm_translate=llm_translate)


def test_the_ladder_files_every_ruled_occurrence_once(tmp_path):
    terms = {
        "罗曼·杜瓦尔": "Romain Duval",
        "鲁德·德穆伊": "Ruud de Mooij",
        "杨沙": "Yang Sha",
        "杜俊志": "Du Junzhi",
    }
    dropped = [
        {
            "source": "鲁德·德穆伊",
            "auto_target": "Rud Demuy",
            "human_target": "Ruud de Mooij",
        }
    ]
    rows = [
        # A: 本就采纳 -- 零动作
        ("adopted", "经济学家罗曼·杜瓦尔认为", "Economist Romain Duval argues"),
        # B: 已知变体 -- 确定性替换
        ("variant", "鲁德·德穆伊指出", "Rud Demuy points out"),
        # C: 无变体 -- 钉裁重译成功
        ("retry-ok", "杨沙写道", "someone wrote"),
        # D: 重译仍违 -- 升级
        ("retry-bad", "杜俊志表示", "somebody said"),
    ]
    paragraphs = []
    for debug_id, source, _target in rows:
        paragraph = _paragraph(source, debug_id, (0.0, 0.0, 90.0, 12.0))
        paragraphs.append(paragraph)
    docs = il_version_1.Document(page=[_page(0, paragraphs)], total_pages=1)

    engine = _pinning_engine({"杨沙": "Yang Sha"})
    config = Config(tmp_path, engine)
    state = _hitl_state(terms, dropped)

    term_enforce.freeze_sources(config, docs, state)
    for paragraph, (_debug, _source, target) in zip(
        paragraphs, rows, strict=True
    ):
        _set_translation(paragraph, target)

    record = term_enforce.apply(config, docs, state)

    assert record is not None
    by_id = {case["debug_id"]: case for case in record["cases"]}
    assert by_id["adopted"]["outcome"] == "applied"
    assert by_id["variant"]["outcome"] == "variant_substituted"
    assert by_id["variant"]["variant"] == "Rud Demuy"
    assert by_id["retry-ok"]["outcome"] == "retried_ok"
    assert by_id["retry-bad"]["outcome"] == "escalated"
    assert by_id["retry-bad"]["detail"] == "retry_still_violates"
    # 守恒等式
    counts = record["counts"]
    assert counts["ruled"] == 4
    assert (
        counts["ruled"]
        == counts["applied"]
        + counts["variant_substituted"]
        + counts["retried_ok"]
        + counts["escalated"]
    )
    assert record["conservation_ok"] is True
    # 替换只动术语串:变体段落其余字节不动
    assert paragraphs[1].unicode == "Ruud de Mooij points out"
    # 重译成功者的译文确实钉住了裁定
    assert "Du Junzhi" not in paragraphs[3].unicode
    assert (
        term_enforce._normalize("Yang Sha")
        in term_enforce._normalize(paragraphs[2].unicode)
        
    )
    # 报告落盘
    report = json.loads(
        (tmp_path / term_enforce.REPORT_NAME).read_text("utf-8")
    )
    assert report["conservation_ok"] is True
    assert report["budget"]["term_enforce_retry_budget"] >= 0


def test_untranslated_source_term_is_itself_a_known_variant(tmp_path):
    # 目标文本仍原样站着源术语(pasteback/echo 形态)-- 源串即变体,
    # 确定性替换,零模型参与。
    terms = {"CourierT H E UNESCO": "联合国教科文组织《信使》"}
    paragraph = _paragraph(
        "CourierT H E UNESCO", "masthead", (0.0, 0.0, 90.0, 12.0)
    )
    docs = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    config = Config(tmp_path, None)  # no engine: level 4 would fail loudly
    state = _hitl_state(terms)

    term_enforce.freeze_sources(config, docs, state)
    _set_translation(paragraph, "CourierT H E UNESCO")

    record = term_enforce.apply(config, docs, state)

    assert record["cases"][0]["outcome"] == "variant_substituted"
    assert paragraph.unicode == "联合国教科文组织《信使》"


def test_budget_exhaustion_escalates_with_its_own_reason(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        term_enforce,
        "load_term_enforce_config",
        lambda: {"term_enforce_retry_budget": 0},
    )
    terms = {"杨沙": "Yang Sha"}
    paragraph = _paragraph("杨沙写道", "over-budget", (0.0, 0.0, 90.0, 12.0))
    docs = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    config = Config(tmp_path, _pinning_engine({"杨沙": "Yang Sha"}))
    state = _hitl_state(terms)

    term_enforce.freeze_sources(config, docs, state)
    _set_translation(paragraph, "someone wrote")

    record = term_enforce.apply(config, docs, state)

    assert record["cases"][0]["outcome"] == "escalated"
    assert record["cases"][0]["detail"] == "retry_budget_exhausted"


def test_config_budget_is_bounded():
    parameters = term_enforce.load_term_enforce_config()
    assert 0 <= int(parameters["term_enforce_retry_budget"]) <= 60
