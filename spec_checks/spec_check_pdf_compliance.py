"""Offline generated-PDF checks for final searchable PDF compliance."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pymupdf

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.final_pdf_validator import ComplianceExpectations  # noqa: E402
from babeldoc.magazine.final_pdf_validator import DropCapExpectation  # noqa: E402
from babeldoc.magazine.final_pdf_validator import FinalPdfValidator  # noqa: E402
from babeldoc.magazine.final_pdf_validator import TargetExpectation  # noqa: E402
from babeldoc.magazine.final_pdf_validator import load_config  # noqa: E402
from babeldoc.magazine.final_pdf_validator import normalize_text  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf(
    path: Path,
    pages: tuple[str, ...],
    *,
    sizes: tuple[tuple[float, float], ...] | None = None,
    text_origins: tuple[tuple[float, float], ...] | None = None,
    image_rect: tuple[float, float, float, float] | None = None,
) -> None:
    document = pymupdf.open()
    sizes = sizes or tuple((200.0, 200.0) for _item in pages)
    text_origins = text_origins or tuple((20.0, 40.0) for _item in pages)
    for index, text in enumerate(pages):
        width, height = sizes[index]
        page = document.new_page(width=width, height=height)
        page.insert_text(text_origins[index], text, fontsize=12)
        if image_rect is not None and index == 0:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False)
            pixmap.clear_with(0x336699)
            page.insert_image(pymupdf.Rect(image_rect), pixmap=pixmap)
    document.save(path)
    document.close()


def drop_cap_pdf(
    path: Path,
    *,
    initial: str = "A",
    color: tuple[float, float, float] = (1.0, 0.0, 0.0),
    origin: tuple[float, float] = (20.0, 50.0),
) -> None:
    document = pymupdf.open()
    page = document.new_page(width=200, height=200)
    page.insert_text(origin, initial, fontsize=24, color=color)
    page.insert_text((50, 50), "body remains searchable", fontsize=10)
    document.save(path)
    document.close()


def result(root: Path, source: Path, output: Path, expectations, *, warnings=()):
    return FinalPdfValidator().validate(
        source,
        output,
        root / "report.json",
        expectations=expectations,
        writer_warnings=warnings,
    )


def codes(value) -> set[str]:
    return {item["code"] for item in value.record["issues"]}


def target_expectations(
    text: str = "Target fragment",
    *,
    box=(0.0, 0.0, 200.0, 200.0),
    article_bounds=((0.0, 0.0, 200.0, 200.0),),
) -> ComplianceExpectations:
    return ComplianceExpectations(
        expected_page_count=2,
        touched_pages=(1,),
        targets=(
            TargetExpectation(
                fragment_id="fragment-fixture",
                source_ref="p1#0",
                page=1,
                text=text,
                box=box,
                article_bounds=article_bounds,
            ),
        ),
    )


def check_searchable_pdf_passes_and_stays_unchanged(root: Path) -> None:
    source = root / "source.pdf"
    output = root / "output.pdf"
    pdf(source, ("Target fragment", "Untouched page"))
    shutil.copy2(source, output)
    before_source = digest(source)
    before_output = digest(output)
    value = result(root, source, output, target_expectations())
    assert value.status == "pass", value.record
    assert value.fully_compliant
    assert digest(source) == before_source
    assert digest(output) == before_output
    report = json.loads(value.report_path.read_text(encoding="utf-8"))
    assert report["normalization"]["version"] == "nfkc-whitespace-v1"
    assert report["fully_compliant"]
    assert report["trace_reconciliation"][0]["located"]


def check_broken_file_fails_with_report(root: Path) -> None:
    source = root / "broken-source.pdf"
    output = root / "broken-output.pdf"
    pdf(source, ("Searchable",))
    output.write_bytes(b"not a PDF")
    value = result(
        root,
        source,
        output,
        ComplianceExpectations(expected_page_count=1),
    )
    assert value.status == "fail"
    assert "output_unreadable" in codes(value)
    assert output.read_bytes() == b"not a PDF"
    assert value.report_path.is_file()


def check_page_count_and_geometry_fail(root: Path) -> None:
    source = root / "geometry-source.pdf"
    page_count_output = root / "page-count.pdf"
    geometry_output = root / "geometry-output.pdf"
    pdf(source, ("One", "Two"))
    pdf(page_count_output, ("One",))
    count_result = result(
        root,
        source,
        page_count_output,
        ComplianceExpectations(expected_page_count=2),
    )
    assert "page_count_mismatch" in codes(count_result)
    pdf(geometry_output, ("One", "Two"), sizes=((210, 200), (200, 200)))
    geometry_result = result(
        root,
        source,
        geometry_output,
        ComplianceExpectations(expected_page_count=2),
    )
    assert "page_geometry_mismatch" in codes(geometry_result)


def check_target_missing_and_duplicate_fail(root: Path) -> None:
    source = root / "target-source.pdf"
    missing = root / "target-missing.pdf"
    duplicate = root / "target-duplicate.pdf"
    pdf(source, ("Target fragment", "Untouched page"))
    pdf(missing, ("Different searchable text", "Untouched page"))
    missing_result = result(root, source, missing, target_expectations())
    assert "target_fragment_missing" in codes(missing_result)
    pdf(duplicate, ("Target fragment Target fragment", "Untouched page"))
    duplicate_result = result(root, source, duplicate, target_expectations())
    assert "target_fragment_duplicate" in codes(duplicate_result)


def check_text_bounds_fail(root: Path) -> None:
    source = root / "bounds-source.pdf"
    output = root / "bounds-output.pdf"
    pdf(source, ("Target fragment", "Untouched page"))
    pdf(
        output,
        ("Target fragment", "Untouched page"),
        text_origins=((195, 40), (20, 40)),
    )
    value = result(
        root,
        source,
        output,
        target_expectations(article_bounds=((0.0, 0.0, 100.0, 100.0),)),
    )
    assert {"text_span_outside_page", "target_fragment_out_of_bounds"} & codes(value)


def check_fixed_asset_bbox_drift_fails(root: Path) -> None:
    source = root / "asset-source.pdf"
    output = root / "asset-output.pdf"
    pdf(
        source,
        ("Target fragment", "Untouched page"),
        image_rect=(20, 80, 50, 110),
    )
    pdf(
        output,
        ("Target fragment", "Untouched page"),
        image_rect=(80, 80, 110, 110),
    )
    value = result(root, source, output, target_expectations())
    assert "fixed_asset_drift" in codes(value), value.record["evidence"]["assets"]


def initial_span(path: Path) -> dict:
    with pymupdf.open(path) as document:
        raw = document[0].get_text("rawdict")
        return next(
            span
            for block in raw["blocks"]
            if block.get("type") == 0
            for line in block["lines"]
            for span in line["spans"]
            if "".join(char["c"] for char in span["chars"]) == "A"
        )


def drop_cap_expectation(path: Path, **overrides) -> ComplianceExpectations:
    span = initial_span(path)
    values = {
        "source_ref": "p1#0",
        "page": 1,
        "character": "A",
        "policy": "english_raised_initial",
        "box": tuple(span["bbox"]),
        "font_size": 24.0,
        "rgb": (1.0, 0.0, 0.0),
        "body_text": "A body remains searchable",
    }
    values.update(overrides)
    return ComplianceExpectations(
        expected_page_count=1,
        touched_pages=(1,),
        drop_caps=(DropCapExpectation(**values),),
    )


def check_drop_cap_character_color_and_bbox_fail(root: Path) -> None:
    source = root / "drop-source.pdf"
    valid = root / "drop-valid.pdf"
    invalid_character = root / "drop-character.pdf"
    invalid_color = root / "drop-color.pdf"
    drop_cap_pdf(source)
    shutil.copy2(source, valid)
    good = result(root, source, valid, drop_cap_expectation(valid))
    assert good.status == "pass", good.record

    drop_cap_pdf(invalid_character, initial="AB")
    character_result = result(
        root,
        source,
        invalid_character,
        drop_cap_expectation(valid),
    )
    assert "drop_cap_noncompliant" in codes(character_result)

    drop_cap_pdf(invalid_color, color=(0.0, 0.0, 1.0))
    color_result = result(
        root,
        source,
        invalid_color,
        drop_cap_expectation(valid),
    )
    assert "drop_cap_noncompliant" in codes(color_result)

    bbox_result = result(
        root,
        source,
        valid,
        drop_cap_expectation(valid, box=(100.0, 100.0, 120.0, 130.0)),
    )
    assert "drop_cap_noncompliant" in codes(bbox_result)


def check_writer_warning_is_degraded_and_failure_dominates(root: Path) -> None:
    source = root / "warning-source.pdf"
    output = root / "warning-output.pdf"
    pdf(source, ("Searchable",))
    shutil.copy2(source, output)
    warning = ({"code": "xobject_stream_restoration_error", "xref": 7},)
    degraded = result(
        root,
        source,
        output,
        ComplianceExpectations(expected_page_count=1),
        warnings=warning,
    )
    assert degraded.status == "degraded"
    assert not degraded.fully_compliant
    broken = root / "warning-broken.pdf"
    broken.write_bytes(b"broken")
    failed = result(
        root,
        source,
        broken,
        ComplianceExpectations(expected_page_count=1),
        warnings=warning,
    )
    assert failed.status == "fail"


def check_pipeline_status_and_trace_binding(root: Path) -> None:
    from babeldoc.format.pdf.high_level import _run_final_pdf_compliance

    source = root / "pipeline-source.pdf"
    output = root / "pipeline-output.pdf"
    pdf(source, ("Searchable final",))
    shutil.copy2(source, output)
    trace = RunTrace()

    class Config:
        magazine_pdf_compliance = True

        def get_working_file_path(self, name: str) -> Path:
            return root / name

    pipeline_result = SimpleNamespace(
        mono_pdf_path=output,
        writer_warnings=(),
        _pdf_compliance_run_trace=trace,
        _pdf_compliance_trace_path=root / "run_trace.report.json",
    )
    _run_final_pdf_compliance(
        Config(),
        pipeline_result,
        source,
        ComplianceExpectations(expected_page_count=1),
        (),
    )
    assert pipeline_result.final_pdf_compliance_status == "pass"
    assert pipeline_result.fully_compliant
    manifest = json.loads(
        (root / "magazine_run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["final_pdf_compliance"]["status"] == "pass"
    trace_report = json.loads(
        (root / "run_trace.report.json").read_text(encoding="utf-8")
    )
    assert trace_report["final_pdf_compliance"]["status"] == "pass"


def check_contract_and_run_trace_binding() -> None:
    config = load_config()
    assert config.allowed_extra_target_occurrences == 0
    assert normalize_text("Ａ\r\n  B") == "A B"
    trace = RunTrace()
    trace.bind_final_pdf_compliance(
        {
            "schema_version": "final-pdf-compliance.v1",
            "status": "pass",
            "fully_compliant": True,
        }
    )
    assert trace.to_record()["final_pdf_compliance"]["status"] == "pass"
    source = (ROOT / "babeldoc" / "magazine" / "final_pdf_validator.py").read_text(
        encoding="utf-8"
    )
    assert "debug_id" not in source
    for publication in ("UNESCO", "HuaweiTech", "WIPO"):
        assert publication not in source
    high_level = (ROOT / "babeldoc" / "format" / "pdf" / "high_level.py").read_text(
        encoding="utf-8"
    )
    assert high_level.index(
        "migrate_toc(translation_config, result)"
    ) < high_level.index(
        "_run_final_pdf_compliance(",
        high_level.index("migrate_toc(translation_config, result)"),
    )
    writer = (
        ROOT
        / "babeldoc"
        / "format"
        / "pdf"
        / "document_il"
        / "backend"
        / "pdf_creater.py"
    ).read_text(encoding="utf-8")
    for warning in (
        "xobject_font_restoration_error",
        "xobject_stream_restoration_error",
        "mediabox_restoration_error",
    ):
        assert warning in writer


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="babeldoc-c15-") as directory:
        root = Path(directory)
        checks = (
            check_searchable_pdf_passes_and_stays_unchanged,
            check_broken_file_fails_with_report,
            check_page_count_and_geometry_fail,
            check_target_missing_and_duplicate_fail,
            check_text_bounds_fail,
            check_fixed_asset_bbox_drift_fails,
            check_drop_cap_character_color_and_bbox_fail,
            check_writer_warning_is_degraded_and_failure_dominates,
            check_pipeline_status_and_trace_binding,
        )
        for index, check in enumerate(checks):
            case_root = root / str(index)
            case_root.mkdir()
            check(case_root)
    check_contract_and_run_trace_binding()
    print("PASS: 10 final PDF compliance checks")


if __name__ == "__main__":
    main()
