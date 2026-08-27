"""C20C fast gate for generic targeted acceptance and contact sheets."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pymupdf

# The gate must also run directly from its own directory.
# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.hitl_expectation import ManualConstraintEvidence
from babeldoc.magazine.hitl_expectation import ManualConstraintExpectation
from babeldoc.magazine.hitl_expectation import ManualConstraintKind
from babeldoc.magazine.hitl_expectation import ManualConstraintStage
from babeldoc.magazine.hitl_expectation import ManualConstraintStatus
from babeldoc.magazine.manual_constraint_validator import ManualOccurrenceObservation
from babeldoc.magazine.manual_constraint_validator import TranslationEligibility
from babeldoc.magazine.manual_constraint_validator import ValidationScope
from babeldoc.magazine.page_identity import PageIdentityError
from babeldoc.magazine.page_identity import PageSelectionMap
from babeldoc.magazine.page_identity import UnsupportedOutputCardinalityChange
from babeldoc.magazine.targeted_pdf_acceptance import EXPECTATION_INVENTORY_VERSION
from babeldoc.magazine.targeted_pdf_acceptance import OBSERVATION_INVENTORY_VERSION
from babeldoc.magazine.targeted_pdf_acceptance import TargetedAcceptanceError
from babeldoc.magazine.targeted_pdf_acceptance import scan_sensitive_artifacts
from babeldoc.magazine.targeted_pdf_acceptance import verify_targeted_run
from tools.render_targeted_contact_sheet import render_contact_sheet
from tools.verify_targeted_pdf_run import main as verify_main

GATE_SET = "fast"
SELECTED = (1, 3)
PAGE_BOX = (0.0, 0.0, 300.0, 400.0)
TERM_REGION = (35.0, 25.0, 130.0, 60.0)
TERM_BOX = (40.0, 32.0, 110.0, 50.0)


def _source(path: Path) -> None:
    document = pymupdf.open()
    for physical in range(1, 4):
        page = document.new_page(width=300, height=400)
        text = (
            "ABB Review appears on this wrong article page"
            if physical == 1
            else "middle unselected page"
            if physical == 2
            else "ABB Review"
        )
        page.insert_text((40, 45), text)
        page.draw_rect(pymupdf.Rect(20, 80, 60, 110))
    document.set_page_labels(
        [
            {
                "startpage": page,
                "prefix": f"SRC-{page + 1}",
                "style": "",
                "firstpagenum": 1,
            }
            for page in range(3)
        ]
    )
    document.save(path)
    document.close()


def _semantic(source_path: Path, output_path: Path) -> None:
    source = pymupdf.open(source_path)
    output = pymupdf.open()
    for physical in SELECTED:
        output.insert_pdf(source, from_page=physical - 1, to_page=physical - 1)
    output.set_page_labels(
        [
            {
                "startpage": output_index,
                "prefix": source[physical - 1].get_label(),
                "style": "",
                "firstpagenum": 1,
            }
            for output_index, physical in enumerate(SELECTED)
        ]
    )
    output.save(output_path)
    output.close()
    source.close()


def _debug_copy(semantic: Path, debug: Path, *, add_text=False) -> None:
    document = pymupdf.open(semantic)
    document[0].draw_rect(pymupdf.Rect(5, 5, 15, 15), color=(1, 0, 0))
    if add_text:
        document[1].insert_text((40, 45), "ABB Review")
    document.save(debug)
    document.close()


def _expectation() -> ManualConstraintExpectation:
    return ManualConstraintExpectation(
        expectation_id="term:generic",
        kind=ManualConstraintKind.TERM,
        human_value="ABB Review",
        source_occurrence_refs=("p3:a2#term",),
        selected_occurrence_refs=("p3:a2#term",),
        source_binding_sha256="a" * 64,
        stage_evidence=tuple(
            ManualConstraintEvidence(
                stage=stage,
                status=(
                    ManualConstraintStatus.PASS
                    if stage
                    in {ManualConstraintStage.DELIVERY, ManualConstraintStage.TARGET}
                    else ManualConstraintStatus.PENDING
                ),
                evidence_refs=(
                    (f"seed:{stage.value}",)
                    if stage
                    in {ManualConstraintStage.DELIVERY, ManualConstraintStage.TARGET}
                    else ()
                ),
            )
            for stage in ManualConstraintStage
        ),
    )


def _observation() -> ManualOccurrenceObservation:
    return ManualOccurrenceObservation(
        occurrence_ref="p3:a2#term",
        physical_page=3,
        output_index=1,
        article_id="a2",
        source_article_id="a2",
        eligibility=TranslationEligibility.ELIGIBLE,
        policy_rule_id="term-eligibility.v1:body",
        typeset_text_fragments=("ABB Review",),
        typeset_fragment_refs=("fragment:p3",),
        typeset_boxes=(TERM_BOX,),
        final_text="CLAIM_MUST_BE_IGNORED",
        final_glyph_boxes=(TERM_BOX,),
        target_region=TERM_REGION,
        page_box=PAGE_BOX,
    )


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _manifest(mapping: PageSelectionMap, semantic_name="semantic.pdf") -> dict:
    return {
        "manifest_version": 1,
        "semantic_output_pdf": semantic_name,
        "semantic_output_candidates": [semantic_name],
        "page_selection_map": mapping.to_record(),
        "manual_observations": "manual-observations.json",
        "repair_transactions": {
            "schema_version": "repair-summary.v1",
            "status": "pass",
            "count": 1,
            "accepted": 1,
            "rejected": 0,
        },
        "formal_metric_status": {
            "schema_version": "formal-metrics.v1",
            "status": "pass",
            "count": 3,
        },
    }


def _verify(
    root: Path,
    source: Path,
    debug: Path | None = None,
    scope: ValidationScope = ValidationScope.FULL_TRANSLATION,
):
    return verify_targeted_run(
        source_pdf=source,
        run_dir=root,
        manifest_path=root / "run_manifest.json",
        expectations_path=root / "expectations.json",
        selected_pages=SELECTED,
        report_path=root / "acceptance.json",
        debug_copy=debug,
        scope=scope,
    )


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool) -> None:
        print(f"{'PASS' if condition else 'FAIL'} {name}")
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="c20c-acceptance-") as temp:
        root = Path(temp)
        source = root / "source.pdf"
        semantic = root / "semantic.pdf"
        debug = root / "debug.pdf"
        _source(source)
        mapping = PageSelectionMap.from_source_pdf(
            source,
            selected_physical_pages=SELECTED,
            targeted_output=True,
        )
        _semantic(source, semantic)
        _debug_copy(semantic, debug)
        _write_json(root / "run_manifest.json", _manifest(mapping))
        _write_json(
            root / "expectations.json",
            {
                "schema_version": EXPECTATION_INVENTORY_VERSION,
                "expectations": [_expectation().to_record()],
            },
        )
        _write_json(
            root / "manual-observations.json",
            {
                "schema_version": OBSERVATION_INVENTORY_VERSION,
                "observations": [_observation().to_record()],
            },
        )

        report = _verify(root, source, debug)
        check(
            "generic validator accepts manifested two-page semantic PDF",
            report["overall"]
            and report["inputs"]["mapping_sha256"] == mapping.mapping_sha256
            and len(report["inputs"]["config_contract_sha256"]) == 64
            and report["formal_metric_status"]["status"] == "pass",
        )
        parse_report = _verify(
            root,
            source,
            debug,
            scope=ValidationScope.PARSE_ONLY,
        )
        check(
            "parse_only acceptance is a gate pass but never full compliance",
            parse_report["status"] == "parse_gate_pass"
            and not parse_report["overall"],
        )
        cli_report = root / "cli-acceptance.json"
        check(
            "verify_targeted_pdf_run CLI calls the production validator",
            verify_main(
                [
                    "--source",
                    str(source),
                    "--run-dir",
                    str(root),
                    "--expectations",
                    str(root / "expectations.json"),
                    "--selected-pages",
                    "1,3",
                    "--report",
                    str(cli_report),
                    "--debug-copy",
                    str(debug),
                ]
            )
            == 0
            and cli_report.is_file(),
        )

        contact = root / "contact-sheet.pdf"
        contact_report = render_contact_sheet(semantic, mapping, contact)
        contact_doc = pymupdf.open(contact)
        contact_text = "\n".join(page.get_text("text") for page in contact_doc)
        contact_doc.close()
        check(
            "contact sheet preserves mapped order and labels outside page images",
            contact_report["dpi"] == 144
            and contact_report["labels"][0].startswith(
                "physical source page 1 | output index 0"
            )
            and contact_report["labels"][1].startswith(
                "physical source page 3 | output index 1"
            )
            and "physical source page 3" in contact_text,
        )

        changed = pymupdf.open(semantic)
        changed[0].set_cropbox(pymupdf.Rect(0, 0, 220, 300))
        changed.save(root / "illegal-geometry.pdf")
        changed.close()
        _write_json(
            root / "run_manifest.json",
            _manifest(mapping, "illegal-geometry.pdf"),
        )
        check("illegal semantic geometry fails", not _verify(root, source)["overall"])

        changed = pymupdf.open(semantic)
        changed[0].draw_rect(pymupdf.Rect(100, 100, 150, 150))
        changed.save(root / "fixed-asset-change.pdf")
        changed.close()
        _write_json(
            root / "run_manifest.json",
            _manifest(mapping, "fixed-asset-change.pdf"),
        )
        check("fixed asset change fails", not _verify(root, source)["overall"])

        missing = pymupdf.open()
        source_doc = pymupdf.open(source)
        missing.insert_pdf(source_doc, from_page=0, to_page=0)
        page = missing.new_page(width=300, height=400)
        page.insert_text((40, 45), "terminal absent here")
        page.draw_rect(pymupdf.Rect(20, 80, 60, 110))
        missing.set_page_labels(
            [
                {"startpage": 0, "prefix": "SRC-1", "style": "", "firstpagenum": 1},
                {"startpage": 1, "prefix": "SRC-3", "style": "", "firstpagenum": 1},
            ]
        )
        missing.save(root / "missing-terminal.pdf")
        missing.close()
        source_doc.close()
        _write_json(
            root / "run_manifest.json",
            _manifest(mapping, "missing-terminal.pdf"),
        )
        missing_report = _verify(root, source)
        check(
            "missing terminal and wrong-page string cannot satisfy manual term",
            not missing_report["overall"]
            and missing_report["manual_expectations"]["status"] == "fail",
        )

        overlay = root / "missing-debug.pdf"
        _debug_copy(root / "missing-terminal.pdf", overlay, add_text=True)
        check(
            "debug overlay text never counts as final manual evidence",
            not _verify(root, source, overlay)["overall"],
        )

        ambiguous = _manifest(mapping)
        ambiguous["semantic_output_candidates"] = ["semantic.pdf", "debug.pdf"]
        _write_json(root / "run_manifest.json", ambiguous)
        try:
            _verify(root, source)
        except TargetedAcceptanceError:
            ambiguity_failed = True
        else:
            ambiguity_failed = False
        check("ambiguous or debug-only semantic output fails closed", ambiguity_failed)

        tampered = mapping.to_record()
        tampered["output_index_to_physical_page"] = {"0": 3, "1": 1}
        mismatch = _manifest(mapping)
        mismatch["page_selection_map"] = tampered
        _write_json(root / "run_manifest.json", mismatch)
        try:
            _verify(root, source)
        except (
            PageIdentityError,
            TargetedAcceptanceError,
            UnsupportedOutputCardinalityChange,
        ):
            mapping_failed = True
        else:
            mapping_failed = False
        check("report mapping mismatch fails closed", mapping_failed)

        _write_json(root / "run_manifest.json", _manifest(mapping))
        sensitive_values = {
            "translator-cache-error.json": {"api_key": "SIMULATED_SECRET"},
            "provider-retry.json": {"provider_response": "FULL_PRIVATE_RESPONSE"},
            "repair-request.json": {"raw_prompt": "PRIVATE_RAW_PROMPT"},
            "translation-report.json": {
                "source_payload": "PRIVATE_SOURCE",
                "target_payload": "PRIVATE_TARGET",
            },
        }
        for name, value in sensitive_values.items():
            _write_json(root / name, value)
        violations = scan_sensitive_artifacts(root)
        serialized_violations = json.dumps(violations, sort_keys=True)
        sensitive_report = _verify(root, source)
        check(
            "whole run-tree scanner detects credential prompt response and payloads",
            len(violations) >= 5 and not sensitive_report["overall"],
        )
        check(
            "sensitive scanner never echoes detected content",
            all(
                secret not in serialized_violations
                for secret in (
                    "SIMULATED_SECRET",
                    "FULL_PRIVATE_RESPONSE",
                    "PRIVATE_RAW_PROMPT",
                    "PRIVATE_SOURCE",
                    "PRIVATE_TARGET",
                )
            ),
        )

    if failures:
        print(f"spec_check_targeted_pdf_acceptance: FAIL {failures}")
        return 1
    print("spec_check_targeted_pdf_acceptance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
