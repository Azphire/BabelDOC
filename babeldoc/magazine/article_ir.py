"""Canonical runtime state for cross-page articles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from types import MappingProxyType

BoxTuple = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class SourceElementRef:
    """One source paragraph in canonical document reading order."""

    source_ref: str
    page: int
    column: int
    reading_order: int
    role: str
    source_box: BoxTuple | None
    source_text_hash: str
    style_hash: str

    def to_record(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "page": self.page,
            "column": self.column,
            "reading_order": self.reading_order,
            "role": self.role,
            "source_box": None if self.source_box is None else list(self.source_box),
            "source_text_hash": self.source_text_hash,
            "style_hash": self.style_hash,
        }


@dataclass(frozen=True, slots=True)
class ArticleRegionSlot:
    """One geometry region an article may reflow within."""

    article_id: str
    page: int
    column: int
    slot_order: int
    box: BoxTuple
    fixed_obstacle_refs: tuple[str, ...]
    capacity_hint: float

    def to_record(self) -> dict:
        return {
            "article_id": self.article_id,
            "page": self.page,
            "column": self.column,
            "slot_order": self.slot_order,
            "box": list(self.box),
            "fixed_obstacle_refs": list(self.fixed_obstacle_refs),
            "capacity_hint": self.capacity_hint,
        }


@dataclass(frozen=True, slots=True)
class ArticlePolicyEvidence:
    """The page-policy decision retained with an article."""

    page: int
    role: str
    page_kind: str | None
    reason: str | None
    article_reflow_allowed: bool

    def to_record(self) -> dict:
        return {
            "page": self.page,
            "role": self.role,
            "page_kind": self.page_kind,
            "reason": self.reason,
            "article_reflow_allowed": self.article_reflow_allowed,
        }


@dataclass(frozen=True, slots=True)
class ArticleIR:
    """One deterministic article and everything assigned to its flow."""

    article_id: str
    pages: tuple[int, ...]
    elements: tuple[SourceElementRef, ...]
    slots: tuple[ArticleRegionSlot, ...]
    chain_ids: tuple[str, ...]
    policy_evidence: tuple[ArticlePolicyEvidence, ...]

    def to_record(self) -> dict:
        return {
            "article_id": self.article_id,
            "pages": list(self.pages),
            "elements": [element.to_record() for element in self.elements],
            "slots": [slot.to_record() for slot in self.slots],
            "chain_ids": list(self.chain_ids),
            "policy_evidence": [item.to_record() for item in self.policy_evidence],
        }


@dataclass(frozen=True, slots=True)
class UnsupportedArticlePage:
    """A page whose article identity cannot be safely split in this model."""

    page: int
    reason: str
    evidence_refs: tuple[str, ...]

    def to_record(self) -> dict:
        return {
            "page": self.page,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class ArticleIssue:
    """A structured conflict found while canonical article state is built."""

    code: str
    chain_id: str | None
    article_ids: tuple[str, ...]
    element_refs: tuple[str, ...]

    def to_record(self) -> dict:
        return {
            "code": self.code,
            "chain_id": self.chain_id,
            "article_ids": list(self.article_ids),
            "element_refs": list(self.element_refs),
        }


@dataclass(frozen=True, slots=True)
class ArticleDocumentIR:
    """The single authoritative article state for one pipeline run."""

    articles: tuple[ArticleIR, ...]
    by_page: Mapping[int, str]
    by_element: Mapping[str, str]
    by_chain: Mapping[str, str]
    by_chain_member: Mapping[str, str] = field(default_factory=dict)
    unsupported_pages: tuple[UnsupportedArticlePage, ...] = ()
    issues: tuple[ArticleIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "by_page", MappingProxyType(dict(sorted(self.by_page.items())))
        )
        object.__setattr__(
            self,
            "by_element",
            MappingProxyType(dict(sorted(self.by_element.items()))),
        )
        object.__setattr__(
            self, "by_chain", MappingProxyType(dict(sorted(self.by_chain.items())))
        )
        object.__setattr__(
            self,
            "by_chain_member",
            MappingProxyType(dict(sorted(self.by_chain_member.items()))),
        )
        self._validate()

    def _validate(self) -> None:
        article_ids = [article.article_id for article in self.articles]
        if len(article_ids) != len(set(article_ids)):
            raise ValueError("article ids must be unique")
        unsupported = {item.page for item in self.unsupported_pages}
        seen_elements: set[str] = set()
        seen_orders: set[int] = set()
        expected_by_page: dict[int, str] = {}
        expected_by_element: dict[str, str] = {}
        expected_by_chain: dict[str, str] = {}
        for article in self.articles:
            if tuple(sorted(set(article.pages))) != article.pages:
                raise ValueError("article pages must be strictly increasing")
            ordered = tuple(
                sorted(
                    article.elements,
                    key=lambda item: (item.page, item.column, item.reading_order),
                )
            )
            if ordered != article.elements:
                raise ValueError("article elements must be in canonical reading order")
            orders = [element.reading_order for element in article.elements]
            if orders != sorted(orders):
                raise ValueError("article reading orders must be monotonic")
            for page in article.pages:
                if page in expected_by_page:
                    raise ValueError(f"page {page} has two articles")
                expected_by_page[page] = article.article_id
            for element in article.elements:
                if element.source_ref in seen_elements:
                    raise ValueError(
                        f"source element {element.source_ref} has two articles"
                    )
                if element.reading_order in seen_orders:
                    raise ValueError("document reading orders must be unique")
                seen_elements.add(element.source_ref)
                seen_orders.add(element.reading_order)
                expected_by_element[element.source_ref] = article.article_id
            for chain_id in article.chain_ids:
                if chain_id in expected_by_chain:
                    raise ValueError(f"chain {chain_id} has two articles")
                expected_by_chain[chain_id] = article.article_id
            if any(slot.article_id != article.article_id for slot in article.slots):
                raise ValueError("article slot points to another article")
            if any(slot.page in unsupported for slot in article.slots):
                raise ValueError("unsupported pages cannot carry reflow slots")
        expected = (expected_by_page, expected_by_element, expected_by_chain)
        actual = (self.by_page, self.by_element, self.by_chain)
        if any(dict(index) != wanted for index, wanted in zip(actual, expected, strict=False)):
            raise ValueError("article indexes must exactly describe canonical articles")
        for source_ref, chain_id in self.by_chain_member.items():
            if source_ref not in expected_by_element:
                raise ValueError("chain member must be a canonical source element")
            if chain_id not in expected_by_chain:
                raise ValueError("chain member points to an unknown canonical chain")

    def article(self, article_id: str) -> ArticleIR | None:
        return next(
            (article for article in self.articles if article.article_id == article_id),
            None,
        )

    def article_for_page(self, page: int) -> ArticleIR | None:
        article_id = self.by_page.get(page)
        return None if article_id is None else self.article(article_id)

    def to_record(self) -> dict:
        return {
            "articles": [article.to_record() for article in self.articles],
            "by_page": {str(page): value for page, value in self.by_page.items()},
            "by_element": dict(self.by_element),
            "by_chain": dict(self.by_chain),
            "by_chain_member": dict(self.by_chain_member),
            "unsupported_pages": [item.to_record() for item in self.unsupported_pages],
            "issues": [issue.to_record() for issue in self.issues],
        }

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_record(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            )
            + "\n"
        ).encode("utf-8")
