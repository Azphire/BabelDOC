"""C20C fast gate for canonical non-contiguous output page compliance."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pymupdf

# The gate must also run directly from its own directory.
# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.high_level import _project_targeted_toc
from babeldoc.format.pdf.high_level import _projected_page_label_rules
from babeldoc.format.pdf.translation_config import TranslationConfig
from babeldoc.magazine.final_pdf_validator import ComplianceExpectations
from babeldoc.magazine.final_pdf_validator import FinalPdfValidator
from babeldoc.magazine.page_identity import OutputPageIndex
from babeldoc.magazine.page_identity import PageSelectionMap
from babeldoc.magazine.page_identity import PhysicalPageNumber
from babeldoc.magazine.page_identity import UnsupportedOutputCardinalityChange

GATE_SET = "fast"
SELECTED = (2, 3, 8, 9)


def _source(path: Path) -> None:
    document = pymupdf.open()
    for physical in range(1, 10):
        page = document.new_page(
            width=300 + physical * 3,
            height=400 + physical * 5,
        )
        page.insert_text(
            (35, 55),
            f"physical source page {physical} searchable untouched content",
        )
        page.draw_rect(pymupdf.Rect(20, 80, 45 + physical, 105))
        if physical in {3, 8}:
            page.set_rotation(90 if physical == 8 else 180)
    document.set_page_labels(
        [
            {
                "startpage": physical - 1,
                "prefix": f"P-{physical}",
                "style": "",
                "firstpagenum": 1,
            }
            for physical in range(1, 10)
        ]
    )
    document.set_toc(
        [
            [1, "selected two", 2],
            [2, "selected three", 3],
            [1, "unselected five", 5],
            [1, "selected eight", 8],
            [2, "selected nine", 9],
        ]
    )
    document.save(path)
    document.close()


def _subset(
    source_path: Path,
    output_path: Path,
    pages: tuple[int, ...],
    mapping: PageSelectionMap,
    *,
    project_metadata: bool = True,
) -> None:
    source = pymupdf.open(source_path)
    output = pymupdf.open()
    for physical in pages:
        output.insert_pdf(source, from_page=physical - 1, to_page=physical - 1)
    if project_metadata:
        output.set_page_labels(_projected_page_label_rules(source, mapping))
        output.set_toc(_project_targeted_toc(source.get_toc(simple=False), mapping))
    output.save(output_path)
    output.close()
    source.close()


def _expectations(mapping: PageSelectionMap) -> ComplianceExpectations:
    refs = {page: (f"article:p{page}",) for page in SELECTED}
    return ComplianceExpectations(
        expected_page_count=4,
        touched_pages=SELECTED,
        page_selection_map=mapping,
        expected_page_labels_by_physical_page={
            page: f"P-{page}" for page in SELECTED
        },
        fixed_assets_by_physical_page={
            page: ({"reference": f"asset:p{page}"},) for page in SELECTED
        },
        article_refs_by_physical_page=refs,
        chain_refs_by_physical_page={2: ("chain:2-3",), 3: ("chain:2-3",)},
        runtrace_refs_by_physical_page={
            page: (f"trace:p{page}",) for page in SELECTED
        },
    )


def _validate(
    source: Path,
    output: Path,
    report: Path,
    expectations: ComplianceExpectations,
):
    return FinalPdfValidator().validate(
        source,
        output,
        report,
        expectations=expectations,
    )


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool) -> None:
        print(f"{'PASS' if condition else 'FAIL'} {name}")
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="c20c-targeted-") as temp:
        root = Path(temp)
        source = root / "source.pdf"
        output = root / "targeted.pdf"
        _source(source)
        mapping = PageSelectionMap.from_source_pdf(
            source,
            selected_physical_pages=SELECTED,
            targeted_output=True,
        )
        expectations = _expectations(mapping)
        _subset(source, output, SELECTED, mapping)
        positive = _validate(source, output, root / "positive.json", expectations)
        check(
            "2,3,8,9 map to output 0,1,2,3 with boxes rotation and labels",
            positive.fully_compliant
            and tuple(mapping.output_index_to_physical_page.values()) == SELECTED
            and mapping.physical_page_to_output_index[8] == 2,
        )
        check(
            "physical refs for 8/9 use the canonical resolver",
            any(
                item["physical_page"] == 9 and item["output_index"] == 3
                for item in positive.record["evidence"]["references"]
            ),
        )

        toc = pymupdf.open(output).get_toc()
        check(
            "targeted outline drops unselected destinations and remaps selected ones",
            [item[1] for item in toc]
            == ["selected two", "selected three", "selected eight", "selected nine"]
            and [item[2] for item in toc] == [1, 2, 3, 4],
        )

        negative_cases = {
            "wrong_page": (2, 3, 7, 9),
            "repeated_page": (2, 3, 8, 8),
            "missing_page": (2, 3, 8),
        }
        for name, pages in negative_cases.items():
            candidate = root / f"{name}.pdf"
            _subset(source, candidate, pages, mapping, project_metadata=False)
            result = _validate(
                source,
                candidate,
                root / f"{name}.json",
                expectations,
            )
            check(f"{name} fails closed", not result.fully_compliant)

        changed = pymupdf.open(output)
        changed[0].set_cropbox(pymupdf.Rect(0, 0, 250, 300))
        changed.save(root / "dimension.pdf")
        changed.close()
        check(
            "dimension mismatch fails",
            not _validate(
                source,
                root / "dimension.pdf",
                root / "dimension.json",
                expectations,
            ).fully_compliant,
        )

        changed = pymupdf.open(output)
        changed[2].set_rotation(0)
        changed.save(root / "rotation.pdf")
        changed.close()
        check(
            "rotation mismatch fails",
            not _validate(
                source,
                root / "rotation.pdf",
                root / "rotation.json",
                expectations,
            ).fully_compliant,
        )

        changed = pymupdf.open(output)
        changed.set_page_labels(
            [{"startpage": 0, "prefix": "WRONG", "style": "", "firstpagenum": 1}]
        )
        changed.save(root / "labels.pdf")
        changed.close()
        check(
            "label mismatch fails",
            not _validate(
                source,
                root / "labels.pdf",
                root / "labels.json",
                expectations,
            ).fully_compliant,
        )

        identity = PageSelectionMap.from_source_pdf(source)
        identity_result = _validate(
            source,
            source,
            root / "identity.json",
            ComplianceExpectations(page_selection_map=identity),
        )
        check("full identity map regression passes", identity_result.fully_compliant)

        try:
            PageSelectionMap(
                source_pdf_sha256=mapping.source_pdf_sha256,
                source_page_count=9,
                selected_physical_pages=(PhysicalPageNumber(2), PhysicalPageNumber(3)),
                physical_page_to_structural_position={
                    PhysicalPageNumber(page): page - 1 for page in range(1, 10)
                },
                output_index_to_physical_page={
                    OutputPageIndex(0): PhysicalPageNumber(2),
                    OutputPageIndex(1): PhysicalPageNumber(2),
                },
            )
        except UnsupportedOutputCardinalityChange as error:
            cardinality_failed = error.code == "UNSUPPORTED_OUTPUT_CARDINALITY_CHANGE"
        else:
            cardinality_failed = False
        check("page split or merge is typed unsupported", cardinality_failed)

        rejected = []
        for value in ("3-2", "2,2", "2-4,4-5", "0", "1--2"):
            try:
                TranslationConfig.parse_pages(None, value)
            except (TypeError, ValueError):
                rejected.append(value)
        check("CLI rejects reversed duplicate and invalid ranges", len(rejected) == 5)

    if failures:
        print(f"spec_check_targeted_page_compliance: FAIL {failures}")
        return 1
    print("spec_check_targeted_page_compliance: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
