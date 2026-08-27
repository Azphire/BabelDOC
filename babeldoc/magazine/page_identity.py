"""Typed source, selection, and output page identities for magazine runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import NewType

PhysicalPageNumber = NewType("PhysicalPageNumber", int)
SelectedPagePosition = NewType("SelectedPagePosition", int)
OutputPageIndex = NewType("OutputPageIndex", int)

PAGE_SELECTION_MAP_SCHEMA_VERSION = "page-selection-map.v1"


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
    """Canonical mapping between physical, structural, and output pages."""

    translation_selected_physical_pages: tuple[PhysicalPageNumber, ...]
    physical_to_structural: Mapping[PhysicalPageNumber, int]
    output_to_physical: Mapping[OutputPageIndex, PhysicalPageNumber]
    schema_version: str = PAGE_SELECTION_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        selected = tuple(
            PhysicalPageNumber(int(page))
            for page in self.translation_selected_physical_pages
        )
        if len(selected) != len(set(selected)):
            raise PageIdentityError("selected physical pages must be unique")
        structural = {
            PhysicalPageNumber(int(page)): int(position)
            for page, position in self.physical_to_structural.items()
        }
        if sorted(structural.values()) != list(range(len(structural))):
            raise PageIdentityError("structural positions must be dense and zero based")
        if any(page not in structural for page in selected):
            raise PageIdentityError("selected physical page is absent from structure")
        output = {
            OutputPageIndex(int(index)): PhysicalPageNumber(int(page))
            for index, page in self.output_to_physical.items()
        }
        if sorted(int(index) for index in output) != list(range(len(output))):
            raise PageIdentityError("output indexes must be dense and zero based")
        if any(page not in structural for page in output.values()):
            raise PageIdentityError("output page is absent from structure")
        if self.schema_version != PAGE_SELECTION_MAP_SCHEMA_VERSION:
            raise PageIdentityError("unsupported page selection map schema")
        object.__setattr__(self, "translation_selected_physical_pages", selected)
        object.__setattr__(
            self,
            "physical_to_structural",
            MappingProxyType(dict(sorted(structural.items()))),
        )
        object.__setattr__(
            self,
            "output_to_physical",
            MappingProxyType(dict(sorted(output.items()))),
        )

    @classmethod
    def from_document(
        cls,
        docs,
        *,
        translation_config=None,
        selected_physical_pages: Iterable[int] | None = None,
        targeted_output: bool | None = None,
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
            selected = tuple(PhysicalPageNumber(int(page)) for page in selected_physical_pages)
        if targeted_output is None:
            targeted_output = bool(
                translation_config is not None
                and getattr(translation_config, "only_include_translated_page", False)
            )
        output_pages = selected if targeted_output else physical_pages
        return cls(
            translation_selected_physical_pages=selected,
            physical_to_structural={
                page: position for position, page in enumerate(physical_pages)
            },
            output_to_physical={
                OutputPageIndex(index): page for index, page in enumerate(output_pages)
            },
        )

    @property
    def physical_to_output(self) -> Mapping[PhysicalPageNumber, OutputPageIndex]:
        return MappingProxyType(
            {page: index for index, page in self.output_to_physical.items()}
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
            "translation_selected_physical_pages": [
                int(page) for page in self.translation_selected_physical_pages
            ],
            "physical_to_structural": {
                str(int(page)): position
                for page, position in self.physical_to_structural.items()
            },
            "output_to_physical": {
                str(int(index)): int(page)
                for index, page in self.output_to_physical.items()
            },
            "physical_to_output": {
                str(int(page)): int(index)
                for page, index in self.physical_to_output.items()
            },
        }

    @classmethod
    def from_record(cls, record: Mapping) -> PageSelectionMap:
        return cls(
            schema_version=str(record["schema_version"]),
            translation_selected_physical_pages=tuple(
                PhysicalPageNumber(int(page))
                for page in record["translation_selected_physical_pages"]
            ),
            physical_to_structural={
                PhysicalPageNumber(int(page)): int(position)
                for page, position in record["physical_to_structural"].items()
            },
            output_to_physical={
                OutputPageIndex(int(index)): PhysicalPageNumber(int(page))
                for index, page in record["output_to_physical"].items()
            },
        )

    def sha256(self) -> str:
        payload = json.dumps(
            self.to_record(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


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
