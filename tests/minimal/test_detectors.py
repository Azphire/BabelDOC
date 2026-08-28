from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pymupdf
import pytest
from babeldoc.magazine import minimal_detection
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine.detectors import CONFIG_PATH
from babeldoc.magazine.detectors import DETECTOR_KINDS
from babeldoc.magazine.detectors.base import DetectorError
from babeldoc.magazine.detectors.base import load_detector_config
from tests.minimal.fakes import _paragraph
from tests.minimal.fakes import document_digest
from tests.minimal.fakes import make_chain_fixture


def _chain_report(*, calls=1, state="joint_success", applied=True):
    refs = ["p1#0", "p1#1", "p2#0", "p2#1"]
    members = [
        {
            "source_ref": ref,
            "debug_id": f"member-{index}",
            "chain_index": index,
            "page_index": index // 2,
            "layout_label": "text",
        }
        for index, ref in enumerate(refs)
    ]
    outcome = {
        "chain_id": "raw-chain",
        "canonical_chain_id": "chain-canonical",
        "article_id": "article-a",
        "ordered_source_refs": refs,
        "request_id": "request-1" if calls else None,
        "translator_call_count": calls,
        "result_state": state,
        "reason": "" if state == "joint_success" else "translation_unavailable",
        "detail": "" if state == "joint_success" else "failed",
        "members": members,
    }
    entry = {
        **outcome,
        "result_state": "joint_success",
        "request_id": "request-1",
        "pair_class": "page",
        "strategy": "slot_capacity",
        "boundary_kinds": ["column", "page", "column"],
        "capacity": [{}, {}, {}, {}],
        "cut_displacement": [],
        "merged_source_chars": 52,
        "merged_translation_chars": 4,
        "translation": "目标文本",
        "merge": {},
        "allocation": {
            "verified": True,
            "whole_target_chars": 4,
            "fragments": [
                {
                    "slot_id": f"slot-{index}",
                    "page": 1 if index < 2 else 2,
                    "column": index % 2,
                    "slot_order": index,
                    "source_ref": ref,
                    "target_range": [index, index + 1],
                    "chars": 1,
                    "status": "allocated",
                    "box": None,
                    "measurement": {},
                }
                for index, ref in enumerate(refs)
            ],
            "released_slot_ids": [],
        },
        "redistribution": {},
        "members": [
            {
                "debug_id": f"member-{index}",
                "chain_index": index,
                "page_index": index // 2,
                "layout_label": "text",
                "source_chars": 13,
                "segment": {},
            }
            for index in range(4)
        ],
    }
    successful = state == "joint_success"
    skips = [
        {
            "chain_id": "raw-chain",
            "chain_index": index,
            "debug_id": f"member-{index}",
            "page_index": index // 2,
            "reason": "chain_member",
            "taken_by": "chain",
            "result_state": state,
            "declined_by": ["page_batch"],
        }
        for index in range(4)
    ]
    skips.append(
        {
            "chain_id": "",
            "chain_index": None,
            "debug_id": "short-unit-0",
            "page_index": 0,
            "reason": "chain_member",
            "taken_by": "short_unit",
            "result_state": None,
            "declined_by": ["page_batch"],
        }
    )
    return {
        "language": "zh",
        "counts": {
            "chains": 1,
            "merged": int(successful),
            "escalated": int(not successful),
            "merged_members": 4 if successful else 0,
            "skips": len(skips),
            "translator_calls": calls,
            "alignment_requests": 0,
            "aligned_cuts": 0,
        },
        "align_enabled": False,
        "short_units": {"admitted": 1, "refused": 0, "requests": 1},
        "applied": applied,
        "chains": [entry] if successful else [],
        "escalated": [] if successful else [outcome],
        "outcomes": [outcome],
        "skips": skips,
    }


def _write_chain(directory, report):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / minimal_detection.CHAIN_REPORT_NAME).write_text(
        json.dumps(report, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path):
    docs, article_ir, paragraphs, _translator = make_chain_fixture(
        "目标文本", tmp_path / "translator"
    )
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )
    return docs, article_ir, paragraphs, baseline


def test_six_detectors_and_document_are_read_only(tmp_path):
    docs, article_ir, paragraphs, baseline = _fixture(tmp_path)
    paragraphs[0].box.x = -8.0
    paragraphs[0].box.x2 = 42.0
    paragraphs[1].box.x = 12.0
    paragraphs[1].box.x2 = 62.0
    docs.page[0].pdf_paragraph.extend(
        [
            _paragraph("a", "fragment-a", (75.0, 30.0, 85.0, 38.0)),
            _paragraph("b", "fragment-b", (75.0, 40.0, 85.0, 48.0)),
            _paragraph("c", "fragment-c", (75.0, 50.0, 85.0, 58.0)),
        ]
    )
    flow_refs = ["p1#2", "p1#3", "p1#4"]
    flow = {
        "cross_page_segments": [
            {
                "status": "applied",
                "action_status": "committed",
                "committed_flow_owned_refs": flow_refs,
            }
        ]
    }
    _write_chain(tmp_path, _chain_report(calls=2))
    before = document_digest(docs)
    result = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=True,
        working_dir=tmp_path,
        sidecar_name="issues.before.json",
        pass_index=0,
        flow_report=flow,
    )
    assert document_digest(docs) == before
    assert {
        "untranslated_residue",
        "out_of_page",
        "text_text_collision",
        "fragment_cluster",
        "chain_conservation",
    }.issubset({issue.kind for issue in result.issues})
    assert result.record["fixed_comparison"]["holds"] is True
    tuple_record = json.loads(json.dumps(result.record))
    tuple_record["issues"][0]["evidence"]["tuple_box"] = (0.0, 1.0, 2.0, 3.0)
    tuple_path = minimal_detection._write_sidecar(
        tmp_path, "issues.before.json", tuple_record
    )
    tuple_result = minimal_detection.DetectionResult(
        result.issues, tuple_record, tuple_path
    )
    assert isinstance(tuple_record["issues"][0]["evidence"]["tuple_box"], tuple)
    summary_config = SimpleNamespace(
        working_dir=tmp_path,
        get_working_file_path=lambda name: str(tmp_path / name),
    )
    assert minimal_pipeline._sidecar_summary(
        tuple_result, summary_config, "issues.before.json"
    )["total"] == len(result.issues)

    docs.page[0].cropbox.box.x += 1.0
    drift_before = document_digest(docs)
    drift = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=False,
        working_dir=tmp_path / "drift",
        sidecar_name="issues.after.json",
        pass_index=1,
    )
    assert document_digest(docs) == drift_before
    assert "fixed_asset_drift" in {issue.kind for issue in drift.issues}
    assert set(DETECTOR_KINDS) == {
        "untranslated_residue",
        "out_of_page",
        "text_text_collision",
        "fragment_cluster",
        "chain_conservation",
        "fixed_asset_drift",
    }


def test_offline_skip_and_chain_report_fail_closed(tmp_path):
    docs, article_ir, _paragraphs, baseline = _fixture(tmp_path)
    skipped = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=False,
        working_dir=tmp_path / "offline",
        sidecar_name="issues.before.json",
        pass_index=0,
    )
    assert skipped.record["skips"] == [
        {
            "detector": "untranslated_residue",
            "reason": "translation_not_performed",
            "typed": True,
        }
    ]
    assert skipped.record["chain_conservation"]["typed_skip"] is True

    translated = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=True,
        working_dir=tmp_path / "missing",
        sidecar_name="issues.after.json",
        pass_index=1,
    )
    assert translated.record["chain_conservation"]["status"] == (
        "missing_after_translation"
    )
    assert any(issue.kind == "chain_conservation" for issue in translated.issues)

    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / minimal_detection.CHAIN_REPORT_NAME).write_text(
        "{not-json}\n", encoding="utf-8"
    )
    with pytest.raises(json.JSONDecodeError):
        minimal_detection.detect(
            docs,
            article_ir,
            baseline,
            language="zh",
            translation_performed=True,
            working_dir=malformed,
            sidecar_name="issues.after.json",
            pass_index=1,
        )


def test_chain_root_and_backfill_contract(tmp_path):
    docs, article_ir, _paragraphs, baseline = _fixture(tmp_path)
    good_dir = tmp_path / "good"
    _write_chain(good_dir, _chain_report())
    good = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=True,
        working_dir=good_dir,
        sidecar_name="issues.before.json",
        pass_index=0,
    )
    assert good.record["chain_conservation"]["violations"] == 0

    cases = (
        ("escalated", _chain_report(state="failed_with_issue"), "non_joint_success"),
        ("unapplied", _chain_report(applied=False), "chain_plan_not_applied"),
    )
    mismatch = _chain_report()
    mismatch["counts"]["merged"] = 0
    cases += (("mismatch", mismatch, "count_merged_mismatch"),)
    dangling = _chain_report()
    dangling["skips"][0]["debug_id"] = "not-a-member"
    cases += (("dangling", dangling, "dangling_chain_skip"),)
    for name, report, evidence in cases:
        directory = tmp_path / name
        _write_chain(directory, report)
        result = minimal_detection.detect(
            docs,
            article_ir,
            baseline,
            language="zh",
            translation_performed=True,
            working_dir=directory,
            sidecar_name="issues.after.json",
            pass_index=1,
        )
        record = result.record["chain_conservation"]
        recorded = {
            violation
            for row in record["records"]
            for violation in row["violations"]
        }.union(record["root_violations"])
        assert evidence in recorded


def test_repair_owned_exclusion_is_pass_one_and_exact(tmp_path):
    docs, article_ir, _paragraphs, _baseline = _fixture(tmp_path)
    docs.page[0].pdf_paragraph.append(
        _paragraph("orphan source", "orphan", (20.0, 75.0, 90.0, 90.0))
    )
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )
    docs.page[0].pdf_paragraph[2].unicode = "orphan translated"
    with pytest.raises(minimal_detection.MinimalDetectionError):
        minimal_detection.detect(
            docs,
            article_ir,
            baseline,
            language="zh",
            translation_performed=False,
            working_dir=tmp_path / "wrong-pass",
            sidecar_name="issues.before.json",
            pass_index=0,
            repair_owned_binding=("p7#2", "p1#2"),
        )
    excluded = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=False,
        working_dir=tmp_path / "excluded",
        sidecar_name="issues.after.json",
        pass_index=1,
        repair_owned_binding=("p7#2", "p1#2"),
    )
    assert excluded.record["fixed_comparison"]["holds"] is True
    unexcluded = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=False,
        working_dir=tmp_path / "control",
        sidecar_name="issues.after.json",
        pass_index=1,
    )
    assert unexcluded.record["fixed_comparison"]["holds"] is False


def test_detector_config_and_baseline_invariants_fail_closed(tmp_path):
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["suggested_actions"]["fixed_asset_drift"] = "repair_loop"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(DetectorError):
        load_detector_config(bad.as_posix(), DETECTOR_KINDS, DETECTOR_KINDS)

    docs, article_ir, _paragraphs, baseline = _fixture(tmp_path)
    with pytest.raises(minimal_detection.MinimalDetectionError):
        replace(baseline, physical_to_local={7: 2, 8: 1})
    assert baseline.physical_to_local == {7: 1, 8: 2}


def _source_pdf(path, pages=8):
    document = pymupdf.open()
    for _index in range(pages):
        document.new_page()
    document.save(path)
    document.close()


def test_explicit_selection_restores_source_total_before_structure(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.pdf"
    _source_pdf(source)
    docs, article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", tmp_path / "translator"
    )
    docs.total_pages = 2
    docs.page[0].page_number = 6
    docs.page[1].page_number = 7
    observed = []

    class Classifier:
        def __init__(self, _config):
            self.vlm_enabled = False

        def process(self, document):
            observed.append(document.total_pages)
            return document

    class Processor:
        def __init__(self, _config, result=None):
            self.result = result

        def process(self, document):
            return document if self.result is None else self.result

    monkeypatch.setattr(minimal_pipeline, "PageClassifier", Classifier)
    monkeypatch.setattr(minimal_pipeline, "ChainBuilder", Processor)
    monkeypatch.setattr(
        minimal_pipeline,
        "ArticleBuilder",
        lambda config: Processor(config, article_ir),
    )
    monkeypatch.setattr(
        minimal_pipeline.hitl,
        "page_kind_pass",
        lambda _config, _docs, _state: None,
    )
    config = SimpleNamespace(input_file=source, page_ranges=[(7, 8)])
    minimal_pipeline.configure(config)
    assert minimal_pipeline.after_styles(config, docs) is article_ir
    assert observed == [8]
    assert docs.total_pages == 8
    assert config.magazine_state.hitl_state.total_pages == 8
    assert config.magazine_state.hitl_state.physical_to_local == {7: 1, 8: 2}
    assert config.magazine_state.detection_baseline.physical_labels == (7, 8)


def test_explicit_selection_source_and_labels_fail_closed(tmp_path):
    docs, _article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", tmp_path / "translator"
    )
    docs.page[0].page_number = 6
    docs.page[1].page_number = 7
    with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
        minimal_pipeline._normalize_selected_document_total_pages(
            SimpleNamespace(
                input_file=tmp_path / "missing.pdf", page_ranges=[(7, 8)]
            ),
            docs,
        )

    invalid = tmp_path / "invalid.pdf"
    invalid.write_text("not a PDF", encoding="utf-8")
    with pytest.raises(pymupdf.FileDataError):
        minimal_pipeline._normalize_selected_document_total_pages(
            SimpleNamespace(input_file=invalid, page_ranges=[(7, 8)]), docs
        )

    source = tmp_path / "source.pdf"
    _source_pdf(source)
    docs.page[1].page_number = None
    with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
        minimal_pipeline._normalize_selected_document_total_pages(
            SimpleNamespace(input_file=source, page_ranges=[(7, 8)]), docs
        )


def test_no_explicit_selection_preserves_fixture_total(tmp_path):
    docs, _article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", tmp_path / "translator"
    )
    docs.total_pages = 2
    minimal_pipeline._normalize_selected_document_total_pages(
        SimpleNamespace(input_file=tmp_path / "missing.pdf", page_ranges=None), docs
    )
    assert docs.total_pages == 2

    empty = type(docs)(page=[], total_pages=0)
    minimal_pipeline._normalize_selected_document_total_pages(
        SimpleNamespace(input_file=tmp_path / "missing.pdf", page_ranges=None), empty
    )
    assert empty.total_pages == 0


def test_post_typesetting_fixed_refresh_preserves_source_and_flow_exclusions(
    tmp_path,
):
    docs, article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", tmp_path / "translator"
    )
    docs.page[0].pdf_paragraph.append(
        _paragraph("fixed furniture", "furniture", (10.0, 70.0, 80.0, 82.0))
    )
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )
    source_geometry = baseline.source_geometry
    docs.page[0].pdf_paragraph[2].unicode = "formal representation"
    docs.page[0].pdf_paragraph.append(
        _paragraph("flow holder", "flow", (85.0, 70.0, 110.0, 82.0))
    )
    flow = {
        "cross_page_segments": [
            {
                "status": "applied",
                "action_status": "committed",
                "committed_flow_owned_refs": ["p1#3"],
            }
        ]
    }
    before_refresh = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=False,
        working_dir=tmp_path / "before-refresh",
        sidecar_name="issues.before.json",
        pass_index=0,
        flow_report=flow,
    )
    assert before_refresh.record["fixed_comparison"]["holds"] is False

    refreshed = minimal_detection.refresh_fixed_inventory(
        baseline,
        docs,
        article_ir,
        flow_report=flow,
    )
    assert refreshed.source_geometry is source_geometry
    assert refreshed.physical_to_local == baseline.physical_to_local
    assert all(
        asset.reference != "p1#3" for asset in refreshed.fixed_inventory.assets
    )
    clean = minimal_detection.detect(
        docs,
        article_ir,
        refreshed,
        language="zh",
        translation_performed=False,
        working_dir=tmp_path / "after-refresh",
        sidecar_name="issues.before.json",
        pass_index=0,
        flow_report=flow,
    )
    assert clean.record["fixed_comparison"]["holds"] is True
    docs.page[0].cropbox.box.x += 1.0
    drift = minimal_detection.detect(
        docs,
        article_ir,
        refreshed,
        language="zh",
        translation_performed=False,
        working_dir=tmp_path / "after-drift",
        sidecar_name="issues.after.json",
        pass_index=1,
        flow_report=flow,
    )
    assert drift.record["fixed_comparison"]["holds"] is False
    assert any(issue.kind == "fixed_asset_drift" for issue in drift.issues)


def test_pipeline_fixed_refresh_is_one_shot_and_identity_bound(tmp_path):
    docs, article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", tmp_path / "translator"
    )
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )

    def prepared_state(document):
        config = SimpleNamespace()
        minimal_pipeline.configure(config)
        state = config.magazine_state
        state._structure_started = True
        state._structure_document_identity = id(document)
        state._article_document_ir = article_ir
        state._flow_started = True
        state._flow_completed = True
        state._flow_document_identity = id(document)
        state._flow_report = None
        state._render_started = True
        state._detection_baseline = baseline
        return state

    state = prepared_state(docs)
    refreshed = minimal_pipeline._refresh_detection_fixed_baseline(
        docs, article_ir, state
    )
    assert refreshed.source_geometry is baseline.source_geometry
    assert state.fixed_baseline_refresh_started
    assert state.fixed_baseline_refresh_completed
    assert state.fixed_baseline_refresh_document_identity == id(docs)
    with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
        minimal_pipeline._refresh_detection_fixed_baseline(docs, article_ir, state)

    wrong_docs, _wrong_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", tmp_path / "wrong-translator"
    )
    wrong_state = prepared_state(docs)
    with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
        minimal_pipeline._refresh_detection_fixed_baseline(
            wrong_docs, article_ir, wrong_state
        )
    assert wrong_state.fixed_baseline_refresh_started
    assert not wrong_state.fixed_baseline_refresh_completed


def test_after_typesetting_refreshes_fixed_before_dropcap(tmp_path, monkeypatch):
    docs, article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", tmp_path / "translator"
    )
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )
    config = SimpleNamespace()
    minimal_pipeline.configure(config)
    typesetter = SimpleNamespace(translation_config=config)
    state = config.magazine_state
    state._structure_started = True
    state._structure_document_identity = id(docs)
    state._article_document_ir = article_ir
    state._translation_prep_started = True
    state._translation_prep_completed = True
    state._flow_started = True
    state._flow_completed = True
    state._flow_document_identity = id(docs)
    state._flow_report = None
    state._typesetter_identity = id(typesetter)
    state._detection_baseline = baseline
    events = []

    def refresh(current, document, current_ir, *, flow_report):
        assert current is baseline
        assert document is docs
        assert current_ir is article_ir
        assert flow_report is None
        events.append("fixed_refresh")
        return current

    marker = RuntimeError("dropcap marker")

    def dropcap(*_args, **_kwargs):
        events.append("dropcap")
        raise marker

    monkeypatch.setattr(minimal_detection, "refresh_fixed_inventory", refresh)
    monkeypatch.setattr(minimal_pipeline.drop_cap_render, "apply", dropcap)
    with pytest.raises(RuntimeError) as raised:
        minimal_pipeline.after_typesetting(config, docs, typesetter)
    assert raised.value is marker
    assert events == ["fixed_refresh", "dropcap"]
    assert state.fixed_baseline_refresh_completed
    assert state.render_started and not state.render_completed


def test_dropcap_summary_closes_all_render_states():
    actual_invalid_intent = {
        "totals": {
            "decided": 1,
            "set": 0,
            "reverted": 0,
            "by_state": {
                "committed": 0,
                "invalid_intent": 1,
                "render_rollback": 0,
            },
        }
    }
    assert minimal_pipeline._dropcap_summary(actual_invalid_intent) == {
        "decided": 1,
        "set": 0,
        "reverted": 0,
        "invalid_intent": 1,
        "typed_no_candidate": True,
    }

    invalid_reports = []
    for states in (
        {"committed": 0, "render_rollback": 0},
        {
            "committed": 0,
            "invalid_intent": 1,
            "render_rollback": 0,
            "unknown": 0,
        },
        {"committed": False, "invalid_intent": 1, "render_rollback": 0},
        {"committed": 0, "invalid_intent": -1, "render_rollback": 0},
    ):
        invalid_reports.append(
            {
                "totals": {
                    "decided": 1,
                    "set": 0,
                    "reverted": 0,
                    "by_state": states,
                }
            }
        )
    invalid_reports.extend(
        [
            {
                "totals": {
                    "decided": 2,
                    "set": 0,
                    "reverted": 0,
                    "by_state": {
                        "committed": 0,
                        "invalid_intent": 1,
                        "render_rollback": 0,
                    },
                }
            },
            {
                "totals": {
                    "decided": 1,
                    "set": 0,
                    "reverted": 1,
                    "by_state": {
                        "committed": 0,
                        "invalid_intent": 1,
                        "render_rollback": 0,
                    },
                }
            },
            {
                "totals": {
                    "decided": 1,
                    "set": 0,
                    "reverted": 0,
                    "by_state": {
                        "committed": 1,
                        "invalid_intent": 0,
                        "render_rollback": 0,
                    },
                }
            },
        ]
    )
    for report in invalid_reports:
        with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
            minimal_pipeline._dropcap_summary(report)
