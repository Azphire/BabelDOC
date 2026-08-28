from __future__ import annotations

from types import SimpleNamespace

import pytest
from babeldoc.magazine import fixed_assets
from babeldoc.magazine import minimal_repair
from tests.minimal.test_one_repair import DetectorCallback
from tests.minimal.test_one_repair import FakeTranslator
from tests.minimal.test_one_repair import FakeTypesetter
from tests.minimal.test_one_repair import before_result
from tests.minimal.test_one_repair import make_issue
from tests.minimal.test_one_repair import repair_fixture
from tests.minimal.test_one_repair import run_repair


def _digest(docs):
    return fixed_assets.content_digest(docs.page[0])


@pytest.mark.parametrize(
    ("name", "response", "reason"),
    [
        ("empty", "", "orphan_translation_empty"),
        (
            "same",
            "This source line was never translated",
            "orphan_translation_unchanged",
        ),
    ],
)
def test_typed_refusal_restores_page_and_records_request(
    tmp_path, name, response, reason
):
    issue = make_issue(
        "untranslated_residue", ("p7#2",), minimal_repair.TRANSLATE_ORPHAN
    )
    result, docs, translator, _typesetter, callback, _before = run_repair(
        tmp_path,
        name,
        [issue],
        translator=FakeTranslator(response),
    )
    assert result.record["reason"] == reason
    assert result.record["translator_requests"] == len(translator.calls) == 1
    assert result.record["applied_count"] == 0
    assert result.record["restored_digest"]["holds"] is True
    assert callback.calls == []
    assert docs.page[0].pdf_paragraph[2].unicode == (
        "This source line was never translated"
    )


def test_render_contract_and_fixed_drift_restore_complete_page(tmp_path):
    orphan = make_issue(
        "untranslated_residue", ("p7#2",), minimal_repair.TRANSLATE_ORPHAN
    )
    erased, docs, translator, _typesetter, callback, _before = run_repair(
        tmp_path,
        "erased",
        [orphan],
        typesetter=FakeTypesetter(erase=True),
    )
    assert erased.record["reason"] == "orphan_render_contract_failed"
    assert erased.record["translator_requests"] == len(translator.calls) == 1
    assert erased.record["restored_digest"]["holds"] is True
    assert docs.page[0].pdf_paragraph[2].pdf_paragraph_composition
    assert callback.calls == []

    refit = make_issue("out_of_page", ("p7#6",), minimal_repair.REFIT_OWNED)
    drift, docs, translator, _typesetter, callback, _before = run_repair(
        tmp_path,
        "fixed-drift",
        [refit],
        typesetter=FakeTypesetter(mutate_fixed=True),
    )
    assert drift.record["reason"] == "fixed_asset_drift"
    assert drift.record["restored_digest"]["holds"] is True
    assert docs.page[0].cropbox.box.x == 0.0
    assert translator.calls == callback.calls == []


def test_strict_reject_and_candidate_mutation_restore(tmp_path):
    issue = make_issue("out_of_page", ("p7#0",), minimal_repair.REFIT_OWNED)
    before = before_result(tmp_path / "reject", [issue])
    docs, article_ir, baseline, flow = repair_fixture()
    original = _digest(docs)
    unchanged = DetectorCallback(before, remove_ids=())
    rejected = minimal_repair.repair_once(
        before,
        docs,
        article_ir,
        baseline,
        FakeTypesetter(),
        SimpleNamespace(lang_out="zh", translator=FakeTranslator("unused")),
        flow,
        unchanged,
    )
    assert rejected.rolled_back and rejected.record["reason"] == (
        "strict_acceptance_rejected"
    )
    assert _digest(docs) == original

    before = before_result(tmp_path / "candidate-mutation", [issue])
    docs, article_ir, baseline, flow = repair_fixture()
    original = _digest(docs)

    def mutate_after(_repair_owned):
        docs.page[0].cropbox.box.x += 1.0
        return DetectorCallback(before, remove_ids=(issue.id,))(None)

    rejected = minimal_repair.repair_once(
        before,
        docs,
        article_ir,
        baseline,
        FakeTypesetter(),
        SimpleNamespace(lang_out="zh", translator=FakeTranslator("unused")),
        flow,
        mutate_after,
    )
    assert rejected.rolled_back
    assert rejected.record["reason"] == "detect_after_mutated_document"
    assert rejected.record["action_count"] == 1
    assert _digest(docs) == original


@pytest.mark.parametrize("stage", ["translator", "typesetter", "detect_after"])
def test_unexpected_exception_identity_and_page_rollback(tmp_path, stage):
    orphan = make_issue(
        "untranslated_residue", ("p7#2",), minimal_repair.TRANSLATE_ORPHAN
    )
    refit = make_issue("out_of_page", ("p7#0",), minimal_repair.REFIT_OWNED)
    selected = orphan if stage == "translator" else refit
    docs, article_ir, baseline, flow = repair_fixture()
    before = before_result(tmp_path / stage, [selected])
    marker = RuntimeError(stage)
    translator = FakeTranslator(error=marker if stage == "translator" else None)
    typesetter = FakeTypesetter(error=marker if stage == "typesetter" else None)
    callback = DetectorCallback(
        before,
        remove_ids=(selected.id,),
        error=marker if stage == "detect_after" else None,
    )
    original = _digest(docs)
    with pytest.raises(RuntimeError) as caught:
        minimal_repair.repair_once(
            before,
            docs,
            article_ir,
            baseline,
            typesetter,
            SimpleNamespace(lang_out="zh", translator=translator),
            flow,
            callback,
        )
    assert caught.value is marker
    assert _digest(docs) == original
    assert len(translator.calls) <= 1
    assert len(typesetter.calls) <= 1
    assert len(callback.calls) <= 1
