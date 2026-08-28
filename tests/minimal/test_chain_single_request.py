from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
    ILTranslatorLLMOnly,
)
from babeldoc.magazine.article_context import EMPTY_CONTEXT
from babeldoc.magazine.article_context import ArticleContext
from babeldoc.magazine.chain_translation import ESCALATION_PLACEHOLDER
from babeldoc.magazine.chain_translation import MECHANISM_CROSS_COLUMN
from babeldoc.magazine.chain_translation import MECHANISM_CROSS_PAGE
from babeldoc.magazine.chain_translation import MECHANISM_PAGE_BATCH
from babeldoc.magazine.chain_translation import ChainClaim
from babeldoc.magazine.chain_translation import SkipRecord
from babeldoc.magazine.chain_translation import plan_chain_translation
from tests.minimal.fakes import Placeholder
from tests.minimal.fakes import RecordingExecutor
from tests.minimal.fakes import RecordingTracker
from tests.minimal.fakes import TranslateInput
from tests.minimal.fakes import make_article_context_fixture
from tests.minimal.fakes import make_chain_fixture


def _claim_record(index: int) -> SkipRecord:
    return SkipRecord("chain", index, f"p-{index}", 0)


def test_chain_is_one_semantic_request_and_never_member_translation(tmp_path):
    target = "译文连续内容"
    document, article_ir, paragraphs, translator = make_chain_fixture(
        target, tmp_path
    )

    context = ArticleContext(
        article_document_ir=article_ir,
        page_index={id(page): index for index, page in enumerate(document.page)},
        article_of_page={0: "article-a", 1: "article-a"},
        brief_of_article={"article-a": "shared article brief"},
    )
    plan = plan_chain_translation(
        translator, document, RecordingTracker(), context, article_ir
    )

    assert plan.claim.membership_frozen
    assert len(translator.translate_engine.llm_calls) == 1
    assert translator.translate_engine.member_calls == 0
    assert translator.article_briefs == ["shared article brief"]
    assert len(plan.entries) == 1
    assert plan.outcomes[0]["translator_call_count"] == 1
    assert plan.entries[0].translated == target

    plan.apply()
    assert len(translator.il_translator.posted) == len(paragraphs)
    assert "".join(paragraph.unicode for paragraph in paragraphs) == target
    assert len(plan.claim) == 0


def test_claim_membership_is_atomic_frozen_and_released_once():
    first, second, third = object(), object(), object()
    claim = ChainClaim()
    claim.take_many([(first, _claim_record(0)), (second, _claim_record(1))])

    with pytest.raises(ValueError, match="only one active claim"):
        claim.take_many([(second, _claim_record(1)), (third, _claim_record(2))])
    assert len(claim) == 2

    claim.freeze()
    with pytest.raises(ValueError, match="frozen"):
        claim.take(third, _claim_record(2))
    with pytest.raises(ValueError, match="already frozen"):
        claim.freeze()
    claim.release_all()
    with pytest.raises(ValueError, match="already released"):
        claim.release_all()


def test_claimed_candidates_are_excluded_without_neighbor_promotion():
    document, _article_ir, paragraphs = make_article_context_fixture()
    document.page = document.page[:2]
    document.total_pages = 2
    chain_members = [paragraphs[1], paragraphs[2]]
    paragraphs[3].box.y2 = 120.0
    claim = ChainClaim()
    claim.take_many(
        [
            (paragraph, _claim_record(index))
            for index, paragraph in enumerate(chain_members)
        ]
    )
    claim.freeze()
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
    driver.calc_token_count = len
    driver.mid = 0

    cross_page = RecordingExecutor()
    translated_ids: set[int] = set()
    driver.process_cross_page_paragraph(
        document,
        cross_page,
        tracker=RecordingTracker(),
        translated_ids=translated_ids,
        chain_claim=claim,
    )
    assert not cross_page.submissions

    cross_column = RecordingExecutor()
    driver.process_cross_column_paragraph(
        document.page[1],
        cross_column,
        tracker=RecordingTracker(),
        translated_ids=translated_ids,
        chain_claim=claim,
    )
    assert not cross_column.submissions

    ordinary = RecordingExecutor()
    driver.process_page(
        document.page[1],
        ordinary,
        tracker=RecordingTracker(),
        translated_ids=translated_ids,
        chain_claim=claim,
    )
    assert len(ordinary.submissions) == 1
    scheduled = ordinary.submissions[0][1][0].paragraphs
    assert scheduled == [paragraphs[3]]
    assert not {id(paragraph) for paragraph in scheduled} & {
        id(paragraph) for paragraph in chain_members
    }
    declined = {item for record in claim.records() for item in record.declined_by}
    assert declined == {
        MECHANISM_CROSS_PAGE,
        MECHANISM_CROSS_COLUMN,
        MECHANISM_PAGE_BATCH,
    }


@pytest.mark.parametrize(
    "response",
    [
        "not-json",
        json.dumps([{"id": 9, "output": "wrong id"}]),
        json.dumps(
            [{"id": 0, "output": "one"}, {"id": 1, "output": "two"}]
        ),
        json.dumps([{"id": 0, "output": ""}]),
    ],
)
def test_malformed_chain_reply_is_protected_without_fallback(tmp_path, response):
    document, article_ir, paragraphs, translator = make_chain_fixture(
        "unused", tmp_path
    )
    translator.translate_engine.response = response

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    assert len(translator.translate_engine.llm_calls) == 1
    assert not plan.entries
    assert plan.claim.membership_frozen
    assert len(plan.claim) == len(paragraphs)
    assert plan.outcomes[0]["translator_call_count"] == 1

    page_driver = object.__new__(ILTranslatorLLMOnly)
    page_driver.translation_config = SimpleNamespace(
        raise_if_cancelled=lambda: None,
        min_text_length=1,
        shared_context_cross_split_part=SimpleNamespace(
            first_paragraph=None,
            recent_title_paragraph=None,
        ),
    )
    page_driver.shared_context_cross_split_part = SimpleNamespace(
        recent_title_paragraph=None,
        snapshot_title_paragraph=lambda paragraph: paragraph,
    )
    page_driver.mid = 0
    page_driver.calc_token_count = lambda text: len(text)
    executor = RecordingExecutor()
    page_driver.process_page(
        document.page[0],
        executor,
        tracker=RecordingTracker(),
        translated_ids=set(),
        chain_claim=plan.claim,
    )
    assert not executor.submissions


def test_placeholder_damage_fails_closed(tmp_path):
    document, article_ir, paragraphs, translator = make_chain_fixture(
        "unused", tmp_path
    )
    paragraphs[0].unicode = "source [[0]]"
    translator.il_translator.prepared[id(paragraphs[0])] = TranslateInput(
        paragraphs[0].pdf_style,
        placeholders=[Placeholder("[[0]]")],
    )
    translator.translate_engine.response = json.dumps(
        [{"id": 0, "output": "damaged"}]
    )

    plan = plan_chain_translation(
        translator, document, RecordingTracker(), EMPTY_CONTEXT, article_ir
    )

    assert len(translator.translate_engine.llm_calls) == 1
    assert not plan.entries
    assert len(plan.claim) == len(paragraphs)
    assert plan.outcomes[0]["reason"] == ESCALATION_PLACEHOLDER
