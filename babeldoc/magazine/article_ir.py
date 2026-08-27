"""Canonical runtime state for cross-page articles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from types import MappingProxyType

from babeldoc.magazine.element_roles import ElementRole
from babeldoc.magazine.element_roles import coerce_element_role
from babeldoc.magazine.page_identity import PageSelectionMap

BoxTuple = tuple[float, float, float, float]
ARTICLE_IR_SCHEMA_VERSION = "article-ir.v3"
CHAIN_DECISION_VERSION = "owner-scoped-continuity.v1"


class ChainHeadStartEvidence(StrEnum):
    SENTENCE_CONTINUATION = "sentence_continuation"
    LOWERCASE_OR_PUNCTUATION_CONTINUATION = (
        "lowercase_or_punctuation_continuation"
    )
    MANUAL_ADJUDICATION = "manual_adjudication"
    NOT_APPLICABLE_SAME_PAGE_COLUMN = "not_applicable_same_page_column"


class ChainTailEndEvidence(StrEnum):
    NO_TERMINAL_PUNCTUATION = "no_terminal_punctuation"
    HYPHENATED_CONTINUATION = "hyphenated_continuation"
    MANUAL_ADJUDICATION = "manual_adjudication"
    NOT_APPLICABLE_SAME_PAGE_COLUMN = "not_applicable_same_page_column"


@dataclass(frozen=True, slots=True)
class SourceElementRef:
    """One source paragraph in canonical document reading order."""

    source_ref: str
    page: int
    column: int
    reading_order: int
    role: ElementRole
    source_box: BoxTuple | None
    source_text_hash: str
    style_hash: str
    raw_layout_label: str | None = None
    role_mapping_reason: str = "closed_role"

    def __post_init__(self) -> None:
        role = coerce_element_role(self.role)
        object.__setattr__(self, "role", role)
        if role is ElementRole.UNCLASSIFIED and not self.role_mapping_reason:
            raise ValueError("UNCLASSIFIED requires a mapping reason")

    def to_record(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "page": self.page,
            "column": self.column,
            "reading_order": self.reading_order,
            "role": self.role.value,
            "raw_layout_label": self.raw_layout_label,
            "role_mapping_reason": self.role_mapping_reason,
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
class ChainSourceRange:
    """The exact source range contributed by one ordered chain member."""

    source_ref: str
    start: int
    end: int
    source_sha256: str

    def to_record(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "start": self.start,
            "end": self.end,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class ArticleChain:
    """One canonical continuity chain already proven to stay within its owner."""

    chain_id: str
    article_id: str
    ordered_member_refs: tuple[str, ...]
    source_ranges: tuple[ChainSourceRange, ...]
    member_physical_pages: tuple[int, ...]
    head_start_evidence: ChainHeadStartEvidence
    tail_end_evidence: ChainTailEndEvidence
    decision_reason: str
    decision_version: str = CHAIN_DECISION_VERSION

    def __post_init__(self) -> None:
        if self.decision_version != CHAIN_DECISION_VERSION:
            raise ValueError("unsupported chain decision version")
        if len(self.ordered_member_refs) < 2:
            raise ValueError("a continuity chain requires at least two members")
        if len(self.source_ranges) != len(self.ordered_member_refs):
            raise ValueError("chain source ranges must cover every member")
        if len(self.member_physical_pages) != len(self.ordered_member_refs):
            raise ValueError("chain pages must cover every member")
        if tuple(item.source_ref for item in self.source_ranges) != (
            self.ordered_member_refs
        ):
            raise ValueError("chain source ranges must follow member order")
        if any(item.start != 0 or item.end < item.start for item in self.source_ranges):
            raise ValueError("chain source ranges must be complete source ranges")

    def to_record(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "article_id": self.article_id,
            "ordered_member_refs": list(self.ordered_member_refs),
            "source_ranges": [item.to_record() for item in self.source_ranges],
            "member_physical_pages": list(self.member_physical_pages),
            "head_start_evidence": self.head_start_evidence.value,
            "tail_end_evidence": self.tail_end_evidence.value,
            "decision_reason": self.decision_reason,
            "decision_version": self.decision_version,
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
    chains: tuple[ArticleChain, ...] = ()
    unsupported_pages: tuple[UnsupportedArticlePage, ...] = ()
    issues: tuple[ArticleIssue, ...] = ()
    page_selection_map: PageSelectionMap | None = None
    schema_version: str = ARTICLE_IR_SCHEMA_VERSION

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
        if self.schema_version != ARTICLE_IR_SCHEMA_VERSION:
            raise ValueError("unsupported ArticleIR schema")
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
        chain_ids = [chain.chain_id for chain in self.chains]
        if len(chain_ids) != len(set(chain_ids)):
            raise ValueError("canonical chain ids must be unique")
        if set(chain_ids) != set(expected_by_chain):
            raise ValueError("chain evidence must exactly describe chain indexes")
        element_by_ref = {
            element.source_ref: element
            for article in self.articles
            for element in article.elements
        }
        for chain in self.chains:
            if expected_by_chain.get(chain.chain_id) != chain.article_id:
                raise ValueError("chain evidence points to another article")
            if tuple(
                sorted(
                    chain.ordered_member_refs,
                    key=lambda reference: element_by_ref[reference].reading_order,
                )
            ) != chain.ordered_member_refs:
                raise ValueError("chain members must follow canonical reading order")
            for reference, page in zip(
                chain.ordered_member_refs,
                chain.member_physical_pages,
                strict=True,
            ):
                element = element_by_ref.get(reference)
                if element is None or element.page != page:
                    raise ValueError("chain member evidence must resolve to its page")
                if element.role is not ElementRole.BODY:
                    raise ValueError("only BODY elements may enter continuity chains")
                if self.by_element.get(reference) != chain.article_id:
                    raise ValueError("chain member must belong to its chain owner")
            for source_range in chain.source_ranges:
                if (
                    element_by_ref[source_range.source_ref].source_text_hash
                    != source_range.source_sha256
                ):
                    raise ValueError("chain source range hash must conserve source")

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
            "schema_version": self.schema_version,
            "page_selection_map": (
                None
                if self.page_selection_map is None
                else self.page_selection_map.to_record()
            ),
            "articles": [article.to_record() for article in self.articles],
            "by_page": {str(page): value for page, value in self.by_page.items()},
            "by_element": dict(self.by_element),
            "by_chain": dict(self.by_chain),
            "by_chain_member": dict(self.by_chain_member),
            "chains": [chain.to_record() for chain in self.chains],
            "unsupported_pages": [item.to_record() for item in self.unsupported_pages],
            "issues": [issue.to_record() for issue in self.issues],
        }
    @classmethod
    def from_record(cls, record: Mapping) -> ArticleDocumentIR:
        """Rehydrate the canonical sidecar without guessing legacy identities."""

        def element(item) -> SourceElementRef:
            box = item.get("source_box")
            return SourceElementRef(
                source_ref=str(item["source_ref"]),
                page=int(item["page"]),
                column=int(item["column"]),
                reading_order=int(item["reading_order"]),
                role=ElementRole(str(item["role"])),
                source_box=None if box is None else tuple(float(x) for x in box),
                source_text_hash=str(item["source_text_hash"]),
                style_hash=str(item["style_hash"]),
                raw_layout_label=item.get("raw_layout_label"),
                role_mapping_reason=str(item.get("role_mapping_reason") or "closed_role"),
            )

        def slot(item) -> ArticleRegionSlot:
            return ArticleRegionSlot(
                article_id=str(item["article_id"]),
                page=int(item["page"]),
                column=int(item["column"]),
                slot_order=int(item["slot_order"]),
                box=tuple(float(x) for x in item["box"]),
                fixed_obstacle_refs=tuple(item.get("fixed_obstacle_refs", ())),
                capacity_hint=float(item["capacity_hint"]),
            )

        def policy(item) -> ArticlePolicyEvidence:
            return ArticlePolicyEvidence(
                page=int(item["page"]),
                role=str(item["role"]),
                page_kind=item.get("page_kind"),
                reason=item.get("reason"),
                article_reflow_allowed=bool(item["article_reflow_allowed"]),
            )

        def chain(item) -> ArticleChain:
            return ArticleChain(
                chain_id=str(item["chain_id"]),
                article_id=str(item["article_id"]),
                ordered_member_refs=tuple(item["ordered_member_refs"]),
                source_ranges=tuple(
                    ChainSourceRange(
                        source_ref=str(value["source_ref"]),
                        start=int(value["start"]),
                        end=int(value["end"]),
                        source_sha256=str(value["source_sha256"]),
                    )
                    for value in item["source_ranges"]
                ),
                member_physical_pages=tuple(
                    int(page) for page in item["member_physical_pages"]
                ),
                head_start_evidence=ChainHeadStartEvidence(
                    str(item["head_start_evidence"])
                ),
                tail_end_evidence=ChainTailEndEvidence(
                    str(item["tail_end_evidence"])
                ),
                decision_reason=str(item["decision_reason"]),
                decision_version=str(item["decision_version"]),
            )

        articles = tuple(
            ArticleIR(
                article_id=str(item["article_id"]),
                pages=tuple(int(page) for page in item["pages"]),
                elements=tuple(element(value) for value in item["elements"]),
                slots=tuple(slot(value) for value in item["slots"]),
                chain_ids=tuple(item["chain_ids"]),
                policy_evidence=tuple(
                    policy(value) for value in item["policy_evidence"]
                ),
            )
            for item in record["articles"]
        )
        selection = record.get("page_selection_map")
        return cls(
            schema_version=str(record.get("schema_version") or ""),
            page_selection_map=(
                None if selection is None else PageSelectionMap.from_record(selection)
            ),
            articles=articles,
            by_page={int(page): value for page, value in record["by_page"].items()},
            by_element=dict(record["by_element"]),
            by_chain=dict(record["by_chain"]),
            by_chain_member=dict(record.get("by_chain_member", {})),
            chains=tuple(chain(item) for item in record.get("chains", ())),
            unsupported_pages=tuple(
                UnsupportedArticlePage(
                    page=int(item["page"]),
                    reason=str(item["reason"]),
                    evidence_refs=tuple(item.get("evidence_refs", ())),
                )
                for item in record.get("unsupported_pages", ())
            ),
            issues=tuple(
                ArticleIssue(
                    code=str(item["code"]),
                    chain_id=item.get("chain_id"),
                    article_ids=tuple(item.get("article_ids", ())),
                    element_refs=tuple(item.get("element_refs", ())),
                )
                for item in record.get("issues", ())
            ),
        )

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
