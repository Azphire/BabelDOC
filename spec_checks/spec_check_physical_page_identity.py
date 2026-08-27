"""C18 fast gate for physical source page identity and targeted output mapping."""

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

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.article_builder import ArticleBuilder
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.final_pdf_validator import ComplianceExpectations
from babeldoc.magazine.final_pdf_validator import FinalPdfValidator
from babeldoc.magazine.page_identity import DocumentPageIndex
from babeldoc.magazine.page_identity import MagazineFullStructureSplitUnsupported
from babeldoc.magazine.page_identity import PageSelectionMap
from babeldoc.magazine.page_identity import PartialArticleStructureError
from babeldoc.magazine.page_identity import PhysicalPageAbsentError
from babeldoc.magazine.page_identity import ensure_magazine_split_supported

GATE_SET = "fast"


class Config:
    def __init__(self, root: Path, selected=(), *, magazine=True, targeted=True):
        self.root = root
        self.selected = frozenset(selected)
        self.magazine_article_group = magazine
        self.magazine_hitl_export = False
        self.magazine_hitl_apply = False
        self.only_include_translated_page = targeted

    def should_translate_page(self, page: int) -> bool:
        return not self.selected or page in self.selected

    def get_working_file_path(self, name: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        return str(self.root / name)


POLICIES = {
    "excluded": {
        "opens_article": False,
        "chain_eligible": False,
        "translate": False,
    },
    "opener": {
        "opens_article": True,
        "chain_eligible": True,
        "translate": True,
    },
    "member": {
        "opens_article": False,
        "chain_eligible": True,
        "translate": True,
    },
}


def policy_of(kind):
    return POLICIES.get(kind)


def paragraph(text: str, y: float = 700.0):
    return il_version_1.PdfParagraph(
        debug_id="volatile",
        layout_label="text",
        unicode=text,
        box=il_version_1.Box(x=50.0, y=y, x2=250.0, y2=y + 20.0),
        pdf_style=il_version_1.PdfStyle(font_id="f", font_size=10.0),
    )


def page(physical: int, kind: str):
    frame = il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
    return il_version_1.Page(
        page_number=physical - 1,
        page_kind=kind,
        page_kind_conf=1.0,
        mediabox=il_version_1.Mediabox(box=frame),
        cropbox=il_version_1.Cropbox(box=frame),
        pdf_paragraph=[paragraph(f"physical {physical}")],
    )


def document(physical_pages=range(1, 10)):
    held = []
    for number in physical_pages:
        kind = "excluded" if number < 6 else "opener" if number == 6 else "member"
        held.append(page(number, kind))
    return il_version_1.Document(page=held, total_pages=9)


def write_pdf(path: Path, count: int) -> None:
    doc = pymupdf.open()
    for number in range(1, count + 1):
        page_obj = doc.new_page(width=300, height=400)
        page_obj.insert_text((50, 50), f"physical {number}")
    doc.save(path)
    doc.close()


def write_subset(source: Path, output: Path, pages: tuple[int, ...]) -> None:
    original = pymupdf.open(source)
    selected = pymupdf.open()
    for physical in pages:
        selected.insert_pdf(original, from_page=physical - 1, to_page=physical - 1)
    selected.save(output)
    selected.close()
    original.close()


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool) -> None:
        print(f"{'PASS' if condition else 'FAIL'} {name}")
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="c18-page-identity-") as temp:
        root = Path(temp)
        full_docs = document()
        full = ArticleBuilder(
            Config(root / "full", selected=range(1, 10)), policy_of=policy_of
        ).process(full_docs)
        subset = ArticleBuilder(
            Config(root / "subset", selected=(7, 8, 9)), policy_of=policy_of
        ).process(document())
        full_article = full.article_for_page(7)
        subset_article = subset.article_for_page(7)
        check(
            "full and subset retain source refs and ArticleIR identity",
            full_article is not None
            and subset_article is not None
            and full_article.article_id == subset_article.article_id
            and [item.source_ref for item in full_article.elements]
            == [item.source_ref for item in subset_article.elements]
            and subset.page_selection_map.translation_selected_physical_pages
            == (7, 8, 9),
        )

        try:
            ArticleBuilder(
                Config(root / "partial", selected=(7, 8, 9)), policy_of=policy_of
            ).process(document((7, 8, 9)))
        except PartialArticleStructureError as error:
            partial_failed = error.code == "PARTIAL_ARTICLE_STRUCTURE_UNSUPPORTED"
        else:
            partial_failed = False
        check("partial ArticleIR fails closed", partial_failed)

        resolver = DocumentPageIndex(
            full_docs,
            PageSelectionMap.from_document(
                full_docs,
                selected_physical_pages=(2, 3, 8, 9),
                targeted_output=True,
            ),
        )
        check(
            "non-contiguous selection never creates false adjacency",
            resolver.are_source_adjacent(2, 3)
            and resolver.are_source_adjacent(8, 9)
            and not resolver.are_source_adjacent(1, 3)
            and not resolver.are_source_adjacent(3, 8),
        )
        check(
            "selection and output positions are typed dense mappings",
            resolver.selected_position_of(8) == 2
            and resolver.output_index_of(9) == 3,
        )
        try:
            resolver.page_by_source_number(10)
        except PhysicalPageAbsentError as error:
            absent_failed = error.code == "PHYSICAL_PAGE_ABSENT"
        else:
            absent_failed = False
        check("absent physical page is typed", absent_failed)

        roundtrip = ArticleDocumentIR.from_record(subset.to_record())
        check(
            "ArticleIR serializer round-trip preserves physical identity",
            roundtrip.to_record() == subset.to_record(),
        )

        source_pdf = root / "source.pdf"
        output_pdf = root / "output.pdf"
        report = root / "compliance.json"
        write_pdf(source_pdf, 9)
        write_subset(source_pdf, output_pdf, (7, 8, 9))
        mapping = PageSelectionMap.from_document(
            full_docs,
            selected_physical_pages=(7, 8, 9),
            targeted_output=True,
        )
        result = FinalPdfValidator().validate(
            source_pdf,
            output_pdf,
            report,
            expectations=ComplianceExpectations(
                expected_page_count=3,
                touched_pages=(7, 8, 9),
                page_selection_map=mapping,
            ),
        )
        issue_codes = {item["code"] for item in result.record["issues"]}
        check(
            "physical 7/8/9 map to targeted output 0/1/2",
            mapping.output_index_of(7) == 0
            and mapping.output_index_of(8) == 1
            and mapping.output_index_of(9) == 2
            and "touched_page_missing" not in issue_codes,
        )

        magazine = Config(root / "split", selected=(7, 8, 9))
        try:
            ensure_magazine_split_supported(magazine, (object(), object()))
        except MagazineFullStructureSplitUnsupported as error:
            split_failed = (
                error.code == "MAGAZINE_FULL_STRUCTURE_SPLIT_UNSUPPORTED"
            )
        else:
            split_failed = False
        ordinary = Config(root / "ordinary", magazine=False)
        ensure_magazine_split_supported(ordinary, (object(), object()))
        check("magazine multipart split alone fails closed", split_failed)

    if failures:
        print(f"spec_check_physical_page_identity: FAIL {failures}")
        return 1
    print("spec_check_physical_page_identity: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
