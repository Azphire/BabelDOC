"""Typed source, selection, and output page identities for magazine runs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import NewType

PhysicalPageNumber = NewType("PhysicalPageNumber", int)
SelectedPagePosition = NewType("SelectedPagePosition", int)
OutputPageIndex = NewType("OutputPageIndex", int)

PAGE_SELECTION_MAP_SCHEMA_VERSION = "page-selection-map.v2"
UNBOUND_SOURCE_PDF_SHA256 = "0" * 64

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PageIdentityError(ValueError):
    """The source document cannot supply an unambiguous physical identity."""

    code = "PAGE_IDENTITY_INVALID"


class PhysicalPageAbsentError(LookupError):
    """A requested physical page is absent from the structural document."""

    code = "PHYSICAL_PAGE_ABSENT"

    def __init__(self, page: int):
        self.page = int(page)
        super().__init__(f"{self.code}: physical page {self.page} is absent")


class MagazineFullStructureSplitUnsupported(RuntimeError):  # noqa: N818
    """A multi-part split would destroy source-bound ArticleIR identity."""

    code = "MAGAZINE_FULL_STRUCTURE_SPLIT_UNSUPPORTED"

    def __init__(self):
        super().__init__(self.code)


class PartialArticleStructureError(RuntimeError):
    """ArticleIR was asked to recover ownership from a filtered IL."""

    code = "PARTIAL_ARTICLE_STRUCTURE_UNSUPPORTED"

    def __init__(self):
        super().__init__(self.code)


class UnsupportedOutputCardinalityChange(RuntimeError):  # noqa: N818
    """The v2 one-to-one map cannot describe a split or merged PDF page."""

    code = "UNSUPPORTED_OUTPUT_CARDINALITY_CHANGE"

    def __init__(self, detail: str = ""):
        suffix = f": {detail}" if detail else ""
        super().__init__(f"{self.code}{suffix}")


def _sha256_file(path) -> str | None:
    if path is None:
        return None
    from pathlib import Path

    source = Path(path)
    if not source.is_file():
        return None
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def physical_page_number(page) -> PhysicalPageNumber:
    """Return the parser-preserved 1-based source PDF page number.

    The IL stores the parser page number as a zero-based attribute.  Missing
    metadata is refused: list position is never an identity fallback.
    """
    value = getattr(page, "page_number", None)
    if value is None:
        raise PageIdentityError("page.page_number source metadata is required")
    value = int(value)
    if value < 0:
        raise PageIdentityError("page.page_number must be zero based and non-negative")
    return PhysicalPageNumber(value + 1)


def requires_full_document_structure(translation_config) -> bool:
    """Whether page selection must be deferred until translation/output."""
    return any(
        bool(getattr(translation_config, name, False))
        for name in (
            "magazine_article_group",
            "magazine_hitl_export",
            "magazine_hitl_apply",
        )
    )


def ensure_magazine_split_supported(translation_config, split_points) -> None:
    """Fail before any part PDF or partial ArticleIR can be created."""
    if requires_full_document_structure(translation_config) and len(split_points) > 1:
        raise MagazineFullStructureSplitUnsupported


def ensure_full_structural_document(translation_config, docs) -> None:
    """Refuse a partial IL where a full-source ArticleIR is required."""
    if not requires_full_document_structure(translation_config):
        return
    total = getattr(docs, "total_pages", None)
    if total is None:
        total = len(docs.page or ())
    physical = tuple(int(physical_page_number(page)) for page in docs.page or ())
    if physical != tuple(range(1, int(total) + 1)):
        raise PartialArticleStructureError


def structural_page_selected(translation_config, page_number: int) -> bool:
    """Select every source page when full magazine structure is required."""
    if requires_full_document_structure(translation_config):
        return True
    return bool(translation_config.should_translate_page(int(page_number)))


def translation_pages(docs, translation_config) -> tuple:
    """Pages target mutation may touch, preserving the structural document."""
    selector = getattr(translation_config, "should_translate_page", None)
    if selector is None:
        return tuple(docs.page or ())
    return tuple(
        page
        for page in docs.page or ()
        if selector(int(physical_page_number(page)))
    )


@dataclass(frozen=True, slots=True)
class PageSelectionMap:
    """Canonical v2 mapping between physical, structural, and output pages.

    The output mapping is deliberately one-to-one.  A future page split/merge
    needs a multimap schema and is rejected instead of being guessed here.
    """

    source_pdf_sha256: str
    source_page_count: int
    selected_physical_pages: tuple[PhysicalPageNumber, ...]
    physical_page_to_structural_position: Mapping[PhysicalPageNumber, int]
    output_index_to_physical_page: Mapping[OutputPageIndex, PhysicalPageNumber]
    mapping_sha256: str | None = None
    schema_version: str = PAGE_SELECTION_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PAGE_SELECTION_MAP_SCHEMA_VERSION:
            raise PageIdentityError("unsupported page selection map schema")
        if not isinstance(self.source_page_count, int) or self.source_page_count < 1:
            raise PageIdentityError("source_page_count must be a positive integer")
        if not isinstance(self.source_pdf_sha256, str) or not _SHA256_RE.fullmatch(
            self.source_pdf_sha256
        ):
            raise PageIdentityError(
                "source_pdf_sha256 must be 64 lowercase hexadecimal characters"
            )
        selected = tuple(
            PhysicalPageNumber(int(page)) for page in self.selected_physical_pages
        )
        if len(selected) != len(set(selected)):
            raise PageIdentityError("selected physical pages must be unique")
        if selected != tuple(sorted(selected)):
            raise PageIdentityError("selected physical pages must be canonical ascending")
        if any(not 1 <= int(page) <= self.source_page_count for page in selected):
            raise PageIdentityError("selected physical page is outside the source PDF")
        structural = {
            PhysicalPageNumber(int(page)): int(position)
            for page, position in self.physical_page_to_structural_position.items()
        }
        if sorted(structural.values()) != list(range(len(structural))):
            raise PageIdentityError("structural positions must be dense and zero based")
        if any(not 1 <= int(page) <= self.source_page_count for page in structural):
            raise PageIdentityError("structural page is outside the source PDF")
        if any(page not in structural for page in selected):
            raise PageIdentityError("selected physical page is absent from structure")
        output = {
            OutputPageIndex(int(index)): PhysicalPageNumber(int(page))
            for index, page in self.output_index_to_physical_page.items()
        }
        if sorted(int(index) for index in output) != list(range(len(output))):
            raise PageIdentityError("output indexes must be dense and zero based")
        if any(page not in structural for page in output.values()):
            raise PageIdentityError("output page is absent from structure")
        if len(output.values()) != len(set(output.values())):
            raise UnsupportedOutputCardinalityChange(
                "a physical source page may appear in output exactly once"
            )
        output_pages = tuple(output[index] for index in sorted(output))
        identity_pages = tuple(
            PhysicalPageNumber(page)
            for page in range(1, self.source_page_count + 1)
        )
        if output_pages not in (selected, identity_pages):
            raise UnsupportedOutputCardinalityChange(
                "output must be the selected projection or the full identity map"
            )
        object.__setattr__(self, "selected_physical_pages", selected)
        object.__setattr__(
            self,
            "physical_page_to_structural_position",
            MappingProxyType(dict(sorted(structural.items()))),
        )
        object.__setattr__(
            self,
            "output_index_to_physical_page",
            MappingProxyType(dict(sorted(output.items()))),
        )
        computed = self._compute_mapping_sha256(
            self.source_pdf_sha256,
            self.source_page_count,
            selected,
            structural,
            output,
        )
        if self.mapping_sha256 is not None and self.mapping_sha256 != computed:
            raise PageIdentityError("mapping_sha256 does not match canonical map")
        object.__setattr__(self, "mapping_sha256", computed)

    @classmethod
    def from_document(
        cls,
        docs,
        *,
        translation_config=None,
        selected_physical_pages: Iterable[int] | None = None,
        targeted_output: bool | None = None,
        source_pdf=None,
        source_pdf_sha256: str | None = None,
    ) -> PageSelectionMap:
        physical_pages = tuple(physical_page_number(page) for page in docs.page or ())
        if len(physical_pages) != len(set(physical_pages)):
            raise PageIdentityError("physical page numbers must be unique")
        if selected_physical_pages is None:
            selector = getattr(translation_config, "should_translate_page", None)
            selected = tuple(
                page
                for page in physical_pages
                if translation_config is None
                or selector is None
                or selector(int(page))
            )
        else:
            selected = tuple(
                PhysicalPageNumber(int(page)) for page in selected_physical_pages
            )
        if len(selected) != len(set(selected)):
            raise PageIdentityError("selected physical pages must be unique")
        selected = tuple(sorted(selected))
        if targeted_output is None:
            targeted_output = bool(
                translation_config is not None
                and getattr(translation_config, "only_include_translated_page", False)
            )
        output_pages = selected if targeted_output else physical_pages
        source_page_count = int(
            getattr(docs, "total_pages", None) or len(physical_pages)
        )
        source_pdf = source_pdf or getattr(translation_config, "input_file", None)
        source_digest = source_pdf_sha256 or _sha256_file(source_pdf)
        if source_digest is None:
            # Synthetic IL/checkpoint tests have no PDF bytes.  Production
            # ArticleBuilder supplies translation_config.input_file; validators
            # fail closed if this sentinel reaches a source-bound acceptance run.
            source_digest = UNBOUND_SOURCE_PDF_SHA256
        return cls(
            source_pdf_sha256=source_digest,
            source_page_count=source_page_count,
            selected_physical_pages=selected,
            physical_page_to_structural_position={
                page: position for position, page in enumerate(physical_pages)
            },
            output_index_to_physical_page={
                OutputPageIndex(index): page for index, page in enumerate(output_pages)
            },
        )

    @classmethod
    def from_source_pdf(
        cls,
        source_pdf,
        *,
        selected_physical_pages: Iterable[int] | None = None,
        targeted_output: bool = False,
    ) -> PageSelectionMap:
        """Build the same canonical map directly from an opened source PDF."""

        import pymupdf

        source_digest = _sha256_file(source_pdf)
        if source_digest is None:
            raise PageIdentityError("source PDF is required for a bound page map")
        with pymupdf.open(source_pdf) as document:
            count = len(document)
        physical_pages = tuple(
            PhysicalPageNumber(page) for page in range(1, count + 1)
        )
        selected = (
            physical_pages
            if selected_physical_pages is None
            else tuple(
                PhysicalPageNumber(int(page)) for page in selected_physical_pages
            )
        )
        if len(selected) != len(set(selected)):
            raise PageIdentityError("selected physical pages must be unique")
        selected = tuple(sorted(selected))
        output_pages = selected if targeted_output else physical_pages
        return cls(
            source_pdf_sha256=source_digest,
            source_page_count=count,
            selected_physical_pages=selected,
            physical_page_to_structural_position={
                page: index for index, page in enumerate(physical_pages)
            },
            output_index_to_physical_page={
                OutputPageIndex(index): page for index, page in enumerate(output_pages)
            },
        )

    @staticmethod
    def _compute_mapping_sha256(
        source_pdf_sha256,
        source_page_count,
        selected,
        structural,
        output,
    ) -> str:
        payload = {
            "schema_version": PAGE_SELECTION_MAP_SCHEMA_VERSION,
            "source_pdf_sha256": source_pdf_sha256,
            "source_page_count": source_page_count,
            "selected_physical_pages": [int(page) for page in selected],
            "physical_page_to_structural_position": {
                str(int(page)): position for page, position in sorted(structural.items())
            },
            "output_index_to_physical_page": {
                str(int(index)): int(page) for index, page in sorted(output.items())
            },
            "physical_page_to_output_index": {
                str(int(page)): int(index) for index, page in sorted(output.items())
            },
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @property
    def translation_selected_physical_pages(self):
        """Compatibility spelling retained for C18 consumers."""

        return self.selected_physical_pages

    @property
    def physical_to_structural(self):
        """Compatibility spelling retained for C18 consumers."""

        return self.physical_page_to_structural_position

    @property
    def output_to_physical(self):
        """Compatibility spelling retained for C18 consumers."""

        return self.output_index_to_physical_page

    @property
    def physical_to_output(self) -> Mapping[PhysicalPageNumber, OutputPageIndex]:
        return MappingProxyType(
            {
                page: index
                for index, page in self.output_index_to_physical_page.items()
            }
        )

    @property
    def physical_page_to_output_index(self):
        return self.physical_to_output

    @property
    def is_targeted(self) -> bool:
        return (
            tuple(self.output_index_to_physical_page.values())
            == self.selected_physical_pages
        )

    def selected_position_of(self, page: int) -> SelectedPagePosition:
        physical = PhysicalPageNumber(int(page))
        try:
            return SelectedPagePosition(
                self.translation_selected_physical_pages.index(physical)
            )
        except ValueError as exc:
            raise PhysicalPageAbsentError(int(physical)) from exc

    def output_index_of(self, page: int) -> OutputPageIndex | None:
        return self.physical_to_output.get(PhysicalPageNumber(int(page)))

    def require_output_index(self, page: int) -> OutputPageIndex:
        index = self.output_index_of(page)
        if index is None:
            raise PhysicalPageAbsentError(page)
        return index

    def to_record(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_pdf_sha256": self.source_pdf_sha256,
            "source_page_count": self.source_page_count,
            "selected_physical_pages": [
                int(page) for page in self.selected_physical_pages
            ],
            "physical_page_to_structural_position": {
                str(int(page)): position
                for page, position in self.physical_page_to_structural_position.items()
            },
            "output_index_to_physical_page": {
                str(int(index)): int(page)
                for index, page in self.output_index_to_physical_page.items()
            },
            "physical_page_to_output_index": {
                str(int(page)): int(index)
                for page, index in self.physical_to_output.items()
            },
            "mapping_sha256": self.mapping_sha256,
        }

    @classmethod
    def from_record(cls, record: Mapping) -> PageSelectionMap:
        expected = {
            "schema_version",
            "source_pdf_sha256",
            "source_page_count",
            "selected_physical_pages",
            "physical_page_to_structural_position",
            "output_index_to_physical_page",
            "physical_page_to_output_index",
            "mapping_sha256",
        }
        if set(record) != expected:
            raise PageIdentityError(
                "page selection map fields must exactly match the v2 schema"
            )
        instance = cls(
            schema_version=str(record["schema_version"]),
            source_pdf_sha256=str(record["source_pdf_sha256"]),
            source_page_count=int(record["source_page_count"]),
            selected_physical_pages=tuple(
                PhysicalPageNumber(int(page))
                for page in record["selected_physical_pages"]
            ),
            physical_page_to_structural_position={
                PhysicalPageNumber(int(page)): int(position)
                for page, position in record[
                    "physical_page_to_structural_position"
                ].items()
            },
            output_index_to_physical_page={
                OutputPageIndex(int(index)): PhysicalPageNumber(int(page))
                for index, page in record["output_index_to_physical_page"].items()
            },
            mapping_sha256=str(record["mapping_sha256"]),
        )
        declared_reverse = {
            PhysicalPageNumber(int(page)): OutputPageIndex(int(index))
            for page, index in record["physical_page_to_output_index"].items()
        }
        if declared_reverse != dict(instance.physical_page_to_output_index):
            raise PageIdentityError(
                "physical_page_to_output_index does not match the forward map"
            )
        return instance

    def sha256(self) -> str:
        return str(self.mapping_sha256)


class DocumentPageIndex:
    """Resolver for physical source pages without dense-index assumptions."""

    def __init__(self, docs, selection_map: PageSelectionMap | None = None):
        self.docs = docs
        pages = tuple(docs.page or ())
        physical = tuple(physical_page_number(page) for page in pages)
        if len(physical) != len(set(physical)):
            raise PageIdentityError("physical page numbers must be unique")
        self._page_by_source = dict(zip(physical, pages, strict=True))
        self._position_by_source = {
            page: position for position, page in enumerate(physical)
        }
        self.selection_map = selection_map or PageSelectionMap.from_document(docs)

    @property
    def physical_pages(self) -> tuple[PhysicalPageNumber, ...]:
        return tuple(self._position_by_source)

    def page_by_source_number(self, page: int):
        physical = PhysicalPageNumber(int(page))
        try:
            return self._page_by_source[physical]
        except KeyError as exc:
            raise PhysicalPageAbsentError(int(physical)) from exc

    def structural_position_of(self, page: int) -> int:
        physical = PhysicalPageNumber(int(page))
        try:
            return self._position_by_source[physical]
        except KeyError as exc:
            raise PhysicalPageAbsentError(int(physical)) from exc

    def selected_position_of(self, page: int) -> SelectedPagePosition:
        return self.selection_map.selected_position_of(page)

    def output_index_of(self, page: int) -> OutputPageIndex | None:
        return self.selection_map.output_index_of(page)

    def are_source_adjacent(self, left: int, right: int) -> bool:
        left_page = PhysicalPageNumber(int(left))
        right_page = PhysicalPageNumber(int(right))
        return (
            left_page in self._page_by_source
            and right_page in self._page_by_source
            and abs(int(left_page) - int(right_page)) == 1
        )
