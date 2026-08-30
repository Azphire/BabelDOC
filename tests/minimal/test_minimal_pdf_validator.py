from __future__ import annotations

import json

import fitz
import pytest

from tools import verify_minimal_pdf

# The closed defect vocabulary has one declaration; a second copy here would
# let the validator and its fixture drift apart silently.
KINDS = verify_minimal_pdf.ISSUE_KINDS


def _pdf(path, *, text, pages=8, cjk=False):
    document = fitz.open()
    for _index in range(pages):
        page = document.new_page()
        page.insert_text(
            (72, 72),
            text,
            fontsize=11,
            fontname="china-s" if cjk else "helv",
        )
    document.save(path)
    document.close()


def _counts(total=0, **overrides):
    by_kind = dict.fromkeys(KINDS, 0)
    by_kind.update(overrides)
    return {"total": total, "by_kind": by_kind}


def _sidecar(pass_index, *, mirrored=False):
    record = {
        "schema_version": "minimal-detection.v1",
        "pass_index": pass_index,
        "translation_performed": False,
        "physical_to_local": {"7": 1, "8": 2},
        "source_geometry": {
            "stage": "styles_and_formulas",
            "path": "memory:styles_and_formulas",
            "paragraphs": 2,
            "boxes": 2,
        },
        "flow_owned_paragraph_refs": [],
        "repair_owned_paragraph": None,
        "counts": {"issues": 0, "by_kind": dict.fromkeys(KINDS, 0)},
        "notes": [],
        "skips": [],
        "detector_records": {},
        "chain_conservation": {
            "status": "skipped_translation_not_performed",
            "path": "typed-offline",
            "chains": 0,
            "violations": 0,
            "typed_skip": True,
        },
        "fixed_comparison": {
            "holds": True,
            "count_before": 0,
            "count_after": 0,
            "added": [],
            "removed": [],
            "digest_changed": [],
            "bbox_changed": [],
            "page_size_changed": [],
        },
        "issues": [],
    }
    if mirrored:
        record["mirrored_after"] = {
            "restored_from_before": False,
            "reason": "no_issues",
        }
    return record


def _report(run_dir, output, *, translated=False):
    before = run_dir / "issues.before.json"
    after = run_dir / "issues.after.json"
    chain_path = run_dir / "chain_translation.report.json"
    if translated:
        chain_path.write_text("{}\n", encoding="utf-8")
    chain_requests = int(translated)
    members = 2 if translated else 0
    return {
        "schema_version": "minimal-run.v1",
        "status": "complete",
        "translation_performed": translated,
        "completed": True,
        "chain": {
            "status": (
                "available" if translated else "skipped_translation_not_performed"
            ),
            "report_path": str(chain_path.resolve()) if translated else None,
            "requests": chain_requests,
            "merged": chain_requests,
            "members": members,
            "claimed_members": members,
            "single_request_holds": True,
            "claim_exclusion_holds": True,
            "conservation_holds": True,
            "typed_offline": not translated,
        },
        "ordinary": {
            "translator_total": chain_requests,
            "translator_cache": 0,
            "chain_requests": chain_requests,
            "article_context_requests": 0,
            "short_unit_requests": 0,
            "repair_requests": 0,
            "requests": 0,
            "claimed_members_excluded": True,
        },
        "backfill": {
            "members": members,
            "released_members": 0,
            "allocation_verified": True,
            "target_conservation_holds": True,
            "only_trailing_released": True,
        },
        "flow": {
            "segments": 0,
            "placements": 0,
            "cross_page_movements": 0,
            "rolled_back": 0,
            "owner_boundary_holds": True,
            "physical_adjacency_holds": True,
            "target_conservation_holds": True,
        },
        "dropcap": {
            "decided": 0,
            "set": 0,
            "reverted": 0,
            "invalid_intent": 0,
            "typed_no_candidate": True,
        },
        "issues": {"before": _counts(), "after": _counts()},
        "detector": {
            "passes": 1,
            "before_path": str(before.resolve()),
            "after_path": str(after.resolve()),
            "before_pass_index": 0,
            "after_pass_index": 0,
            "after_mirrored": True,
        },
        "repair": {
            "selected": None,
            "reason": "no_issues",
            "action_count": 0,
            "applied_count": 0,
            "translator_requests": 0,
            "detection_passes_added": 0,
            "accepted": False,
            "rolled_back": False,
            "filtered_candidates": [],
        },
        # A run that kept no repair has no page to show, and says so rather
        # than leaving the section out.
        "repair_evidence": {"pages": [], "pairs": [], "before_pdf": None},
        "fixed": {"holds": True, "drift_count": 0},
        "output": {
            "status": "complete",
            "mono": str(output.resolve()),
            "dual": None,
            "no_watermark_mono": None,
            "no_watermark_dual": None,
        },
    }


def validator_case(tmp_path, *, translated=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    run_dir = tmp_path / "run"
    output_dir.mkdir()
    run_dir.mkdir()
    output = output_dir / "sample.zh.mono.pdf"
    _pdf(source, text="source body")
    _pdf(output, text="中文目标" if translated else "source body", cjk=translated)
    (run_dir / "issues.before.json").write_text(
        json.dumps(_sidecar(0), sort_keys=True) + "\n", encoding="utf-8"
    )
    (run_dir / "issues.after.json").write_text(
        json.dumps(_sidecar(0, mirrored=True), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = _report(run_dir, output, translated=translated)
    report_path = run_dir / "minimal_run.report.json"
    report_path.write_text(
        json.dumps(report, sort_keys=True) + "\n", encoding="utf-8"
    )
    args = [
        "--source",
        str(source),
        "--output-dir",
        str(output_dir),
        "--run-dir",
        str(run_dir),
        "--translated-pages",
        "7,8",
    ]
    if not translated:
        args.append("--allow-untranslated")
    return args, report, report_path, output_dir, run_dir


def test_offline_and_paid_synthetic_pdf_validate(tmp_path):
    offline_args, offline_report, offline_path, _output, _run = validator_case(
        tmp_path / "offline"
    )
    assert verify_minimal_pdf.main(offline_args) == 0
    offline_report["dropcap"] = {
        "decided": 1,
        "set": 0,
        "reverted": 0,
        "invalid_intent": 1,
        "typed_no_candidate": True,
    }
    offline_path.write_text(json.dumps(offline_report) + "\n", encoding="utf-8")
    assert verify_minimal_pdf.main(offline_args) == 0

    paid_args, report, _path, _output, _run = validator_case(
        tmp_path / "paid", translated=True
    )
    assert verify_minimal_pdf.main(paid_args) == 0
    assert report["chain"]["requests"] == report["chain"]["merged"] == 1
    assert report["chain"]["members"] == report["chain"]["claimed_members"]
    assert report["backfill"]["target_conservation_holds"] is True


def test_ambiguous_mono_and_mode_mismatch_fail_closed(tmp_path):
    args, report, report_path, output_dir, _run = validator_case(tmp_path)
    _pdf(output_dir / "second.mono.pdf", text="duplicate")
    with pytest.raises(verify_minimal_pdf.MinimalPdfValidationError):
        verify_minimal_pdf.main(args)

    (output_dir / "second.mono.pdf").unlink()
    report["translation_performed"] = True
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    with pytest.raises(verify_minimal_pdf.MinimalPdfValidationError):
        verify_minimal_pdf.main(args)


@pytest.mark.parametrize(
    "mutation",
    [
        "unallowed_action",
        "fixed_drift",
        "pass_overflow",
        "sidecar_mismatch",
        "chain_claim_mismatch",
        "dropcap_missing_state",
        "dropcap_count_mismatch",
        "dropcap_typed_mismatch",
    ],
)
def test_malformed_report_evidence_fails_closed(tmp_path, mutation):
    args, report, report_path, _output, run_dir = validator_case(tmp_path)
    if mutation == "unallowed_action":
        report["repair"]["selected"] = "repair_loop"
    elif mutation == "fixed_drift":
        report["fixed"] = {"holds": False, "drift_count": 1}
    elif mutation == "pass_overflow":
        report["detector"]["passes"] = 3
    elif mutation == "sidecar_mismatch":
        sidecar = _sidecar(0)
        sidecar["counts"]["issues"] = 1
        (run_dir / "issues.before.json").write_text(
            json.dumps(sidecar) + "\n", encoding="utf-8"
        )
    elif mutation == "chain_claim_mismatch":
        report["chain"]["claimed_members"] = 1
    elif mutation == "dropcap_missing_state":
        del report["dropcap"]["invalid_intent"]
    elif mutation == "dropcap_count_mismatch":
        report["dropcap"] = {
            "decided": 1,
            "set": 0,
            "reverted": 1,
            "invalid_intent": 1,
            "typed_no_candidate": True,
        }
    else:
        report["dropcap"] = {
            "decided": 1,
            "set": 1,
            "reverted": 0,
            "invalid_intent": 0,
            "typed_no_candidate": True,
        }
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    with pytest.raises(verify_minimal_pdf.MinimalPdfValidationError):
        verify_minimal_pdf.main(args)


def test_page_count_and_selected_page_text_fail_closed(tmp_path):
    args, _report, _path, output_dir, _run = validator_case(tmp_path)
    output = next(output_dir.glob("*.mono.pdf"))
    output.unlink()
    _pdf(output, text="body", pages=7)
    with pytest.raises(verify_minimal_pdf.MinimalPdfValidationError):
        verify_minimal_pdf.main(args)

    output.unlink()
    document = fitz.open()
    for index in range(8):
        page = document.new_page()
        if index not in (6, 7):
            page.insert_text((72, 72), "body")
    document.save(output)
    document.close()
    with pytest.raises(verify_minimal_pdf.MinimalPdfValidationError):
        verify_minimal_pdf.main(args)
