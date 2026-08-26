"""Article grouping stage: which pages make up one article.

Runs after the chain builder and before translation. A page opens an article
when the vocabulary declares that it does; the pages after it join that article
in order until the next opener; a page the vocabulary keeps out of chains and
does not declare an opener belongs to no article, and takes no page with it. A
chain crossing a boundary this walk drew joins the two articles it touches,
because a chain is paragraph level evidence that two pages carry one text while
the page level declaration is only a prior -- the two layer rule again, decided
the same way it is decided everywhere else.

The stage is off by default, and even with ``magazine_article_group`` on it
writes nothing into the intermediate language. It returns the canonical runtime
``ArticleDocumentIR`` and writes ``article_ir.json`` for audit. The older
``article_map.json`` projection remains for offline tools. The schema is frozen,
and an article is a property of the document rather than of any one paragraph,
so neither sidecar is read back to recover runtime identity.

Two policy flags steer it and it reads nothing else about a page.
``opens_article`` says an article begins on this page. ``chain_eligible``, with
``translate``, says the page carries text that belongs to whatever article is
running. ``starts_article`` is deliberately not read here: that flag is the
chain detector's prior, meaning running text does not continue *into* a page,
which is a different question from whether an article *begins* on it. The two
coincide on the flowing page types and diverge on every piece of furniture, so
they are declared and consumed separately.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import ArticleIssue
from babeldoc.magazine.article_ir import ArticlePolicyEvidence
from babeldoc.magazine.article_ir import ArticleRegionSlot
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.article_ir import UnsupportedArticlePage
from babeldoc.magazine.chain_signals import CLASS_LABELS_KEY
from babeldoc.magazine.chain_signals import CONFIG_PATH as CHAIN_CONFIG_PATH
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.taxonomy import DEFAULT_CONFIG_PATHS
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "article_grouping.json"

REPORT_NAME = "article_map.json"
IR_REPORT_NAME = "article_ir.json"

UNSUPPORTED_SAME_PAGE_MULTI_ARTICLE = "unsupported_same_page_multi_article"
ISSUE_CHAIN_SPANS_ARTICLES = "continuity_chain_spans_articles"

# The endpoint classes whose layout labels count as a heading, by name.
TITLE_CLASSES_KEY = "title_pair_classes"

# The policy flags this stage consumes. Page types are never named; a page is
# read only through what its declared policy says about these three.
OPENER_POLICY_FLAG = "opens_article"
ELIGIBILITY_POLICY_FLAG = "chain_eligible"
TRANSLATE_POLICY_FLAG = "translate"

# What one page turned out to be.
ROLE_OPENS = "opens"
ROLE_MEMBER = "member"
ROLE_UNASSIGNED = "unassigned"

# Why a page belongs to no article.
REASON_NO_PAGE_KIND = "no_page_kind"
REASON_NOT_CHAIN_ELIGIBLE = "not_chain_eligible"
REASON_NOT_TRANSLATED = "not_translated"


class ArticleGroupingError(ConfigError):
    """Raised when the article grouping configuration is malformed."""


@lru_cache(maxsize=1)
def load_grouping_config(path: str | None = None) -> dict:
    """Load and validate ``configs/article_grouping.json``.

    The named heading classes have to be classes the chain detection
    configuration declares, so one declaration of what a heading looks like
    serves both the detector and this stage.
    """
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = dict(validate_bounded_config(raw, config_path))
    if TITLE_CLASSES_KEY not in parameters:
        raise ArticleGroupingError(f"{config_path.name}: missing {TITLE_CLASSES_KEY}")
    declared = load_chain_config()[CLASS_LABELS_KEY]
    unknown = sorted(set(parameters[TITLE_CLASSES_KEY]) - set(declared))
    if unknown:
        raise ArticleGroupingError(
            f"{config_path.name}: {TITLE_CLASSES_KEY} names {unknown}, which "
            f"{CHAIN_CONFIG_PATH.name} does not declare as endpoint classes; "
            f"declared classes are {sorted(declared)}"
        )
    return parameters


def title_labels(config: dict) -> tuple[str, ...]:
    """Layout labels a heading may carry, in declaration order."""
    declared = load_chain_config()[CLASS_LABELS_KEY]
    labels: list[str] = []
    for name in config[TITLE_CLASSES_KEY]:
        for label in declared[name]:
            if label not in labels:
                labels.append(label)
    return tuple(labels)


@dataclass(frozen=True)
class PageRole:
    """What one page is, and why, before any chain has been consulted."""

    index: int
    role: str
    reason: str | None
    kind: str | None
    confidence: float | None


@dataclass
class Article:
    """One article: the pages it runs over, in page order."""

    pages: list[int]
    article_id: str | None = None
    merged_by_chain: bool = False


@dataclass(frozen=True)
class Grouping:
    """The whole document, grouped."""

    roles: tuple[PageRole, ...]
    articles: tuple[Article, ...]

    def article_of(self, page_index: int) -> Article | None:
        for article in self.articles:
            if page_index in article.pages:
                return article
        return None

    @property
    def unassigned(self) -> tuple[PageRole, ...]:
        return tuple(role for role in self.roles if role.role == ROLE_UNASSIGNED)


def page_role(page: il_version_1.Page, index: int, policy_of) -> PageRole:
    """What one page is, read from its declared policy and nothing else.

    A page whose kind the vocabulary does not know has no policy to consume, so
    it belongs to no article rather than being given a default that would look
    declared. That is also what a document classified by nothing looks like,
    which is the honest answer for it.
    """
    kind = page.page_kind
    confidence = page.page_kind_conf
    policy = policy_of(kind)
    if policy is None:
        return PageRole(index, ROLE_UNASSIGNED, REASON_NO_PAGE_KIND, kind, confidence)
    if policy.get(OPENER_POLICY_FLAG, False):
        return PageRole(index, ROLE_OPENS, None, kind, confidence)
    if not policy.get(TRANSLATE_POLICY_FLAG, True):
        return PageRole(
            index, ROLE_UNASSIGNED, REASON_NOT_TRANSLATED, kind, confidence
        )
    if not policy.get(ELIGIBILITY_POLICY_FLAG, False):
        return PageRole(
            index, ROLE_UNASSIGNED, REASON_NOT_CHAIN_ELIGIBLE, kind, confidence
        )
    return PageRole(index, ROLE_MEMBER, None, kind, confidence)


def walk_roles(roles: list[PageRole]) -> list[Article]:
    """Group the pages by the walk the roles imply.

    An unassigned page is passed over rather than closing the article above it:
    a bought page between two pages of one feature does not end the feature. It
    takes no page with it either, because it never becomes the article a later
    page could join.

    A member page reached with no article open opens one. That is the document
    whose vocabulary declares no opener anywhere -- it is one article, not none.
    """
    articles: list[Article] = []
    current: Article | None = None
    for role in roles:
        if role.role == ROLE_OPENS:
            current = Article(pages=[role.index])
            articles.append(current)
        elif role.role == ROLE_MEMBER:
            if current is None:
                current = Article(pages=[role.index])
                articles.append(current)
            else:
                current.pages.append(role.index)
    return articles


def chain_pages(docs: il_version_1.Document) -> dict[str, list[int]]:
    """The pages each chain runs over, in page order."""
    pages: dict[str, list[int]] = {}
    for index, page in enumerate(docs.page):
        for paragraph in page.pdf_paragraph:
            chain_id = paragraph.chain_id
            if not chain_id:
                continue
            seen = pages.setdefault(chain_id, [])
            if index not in seen:
                seen.append(index)
    return pages


def merge_across_chains(
    articles: list[Article], chains: dict[str, list[int]]
) -> list[Article]:
    """Join the articles any one chain runs across.

    The walk above draws its boundaries from a page level declaration. A chain
    is paragraph level evidence about the same question, and paragraph level
    evidence is authoritative, so wherever the two disagree the boundary goes.
    """
    owner: dict[int, int] = {}
    for position, article in enumerate(articles):
        for page in article.pages:
            owner[page] = position
    parent = list(range(len(articles)))

    def find(position: int) -> int:
        while parent[position] != position:
            parent[position] = parent[parent[position]]
            position = parent[position]
        return position

    joined: set[int] = set()
    for pages in chains.values():
        touched = []
        for page in pages:
            position = owner.get(page)
            if position is not None and position not in touched:
                touched.append(position)
        for other in touched[1:]:
            left, right = find(touched[0]), find(other)
            if left != right:
                parent[right] = left
                joined.add(left)
                joined.add(right)

    grouped: dict[int, Article] = {}
    for position, article in enumerate(articles):
        root = find(position)
        held = grouped.get(root)
        if held is None:
            grouped[root] = Article(
                pages=list(article.pages), merged_by_chain=root in joined
            )
        else:
            held.pages.extend(article.pages)
    merged = list(grouped.values())
    for article in merged:
        article.pages = sorted(set(article.pages))
    merged.sort(key=lambda item: item.pages[0])
    return merged


def title_paragraph(
    page: il_version_1.Page, labels: tuple[str, ...]
) -> il_version_1.PdfParagraph | None:
    """The first heading on a page, or None where it carries none."""
    for paragraph in page.pdf_paragraph:
        if paragraph.layout_label in labels and (paragraph.unicode or "").strip():
            return paragraph
    return None


def _hash_record(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_ref(page_index: int, paragraph_index: int) -> str:
    return f"p{page_index + 1}#{paragraph_index}"


def _box_tuple(box) -> tuple[float, float, float, float] | None:
    if box is None or None in (box.x, box.y, box.x2, box.y2):
        return None
    return (float(box.x), float(box.y), float(box.x2), float(box.y2))


def _style_hash(paragraph) -> str:
    style = paragraph.pdf_style
    graphic_state = None if style is None else style.graphic_state
    return _hash_record(
        {
            "font_id": None if style is None else style.font_id,
            "font_size": None if style is None else style.font_size,
            "graphic_state": None
            if graphic_state is None
            else graphic_state.passthrough_per_char_instruction,
        }
    )


def _page_frame(page) -> tuple[float, float, float, float] | None:
    for holder in (page.cropbox, page.mediabox):
        if holder is not None:
            frame = _box_tuple(holder.box)
            if frame is not None:
                return frame
    return None


def _column_bands(page, boxes, gap_ratio: float) -> list[float]:
    lefts = sorted(box[0] for box in boxes if box is not None)
    if not lefts:
        return []
    frame = _page_frame(page)
    width = 0.0 if frame is None else frame[2] - frame[0]
    gap = width * gap_ratio
    bands = [lefts[0]]
    for left in lefts[1:]:
        if left - bands[-1] > gap:
            bands.append(left)
    return bands


def _column_of(bands: list[float], box) -> int:
    if box is None or not bands:
        return 0
    column = 0
    for position, band in enumerate(bands):
        if box[0] >= band:
            column = position
    return column


def _page_elements(
    page, page_index: int, reading_order: int, gap_ratio: float
) -> tuple[list[SourceElementRef], int]:
    entries = []
    for paragraph_index, paragraph in enumerate(page.pdf_paragraph):
        box = _box_tuple(paragraph.box)
        entries.append((paragraph_index, paragraph, box))
    bands = _column_bands(page, [item[2] for item in entries], gap_ratio)
    entries.sort(
        key=lambda item: (
            _column_of(bands, item[2]),
            -(item[2][3] if item[2] is not None else 0.0),
            item[2][0] if item[2] is not None else 0.0,
            item[0],
        )
    )
    elements = []
    for paragraph_index, paragraph, box in entries:
        elements.append(
            SourceElementRef(
                source_ref=_source_ref(page_index, paragraph_index),
                page=page_index + 1,
                column=_column_of(bands, box),
                reading_order=reading_order,
                role=paragraph.layout_label or "unclassified",
                source_box=box,
                source_text_hash=hashlib.sha256(
                    (paragraph.unicode or "").encode("utf-8")
                ).hexdigest(),
                style_hash=_style_hash(paragraph),
            )
        )
        reading_order += 1
    return elements, reading_order


def _document_elements(docs) -> dict[int, tuple[SourceElementRef, ...]]:
    gap_ratio = float(load_chain_config()["column_split_gap_ratio"])
    by_page = {}
    reading_order = 0
    for page_index, page in enumerate(docs.page):
        elements, reading_order = _page_elements(
            page, page_index, reading_order, gap_ratio
        )
        by_page[page_index] = tuple(elements)
    return by_page


def _canonical_chains(docs) -> dict[str, tuple[str, tuple[str, ...], tuple[int, ...]]]:
    members: dict[str, list[tuple[int | None, int, int, str]]] = {}
    for page_index, page in enumerate(docs.page):
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph):
            if not paragraph.chain_id:
                continue
            members.setdefault(paragraph.chain_id, []).append(
                (
                    paragraph.chain_index,
                    page_index,
                    paragraph_index,
                    _source_ref(page_index, paragraph_index),
                )
            )
    canonical = {}
    for raw_id, held in members.items():
        held.sort(
            key=lambda item: (
                item[0] is None,
                0 if item[0] is None else item[0],
                item[1],
                item[2],
            )
        )
        refs = tuple(item[3] for item in held)
        pages = tuple(sorted({item[1] for item in held}))
        canonical[raw_id] = (f"chain-{_hash_record(refs)}", refs, pages)
    return canonical


def _article_id(
    article: Article,
    elements_by_page: dict[int, tuple[SourceElementRef, ...]],
    chains: dict[str, tuple[str, tuple[str, ...], tuple[int, ...]]],
) -> str:
    held = set(article.pages)
    elements = [
        element
        for page_index in article.pages
        for element in elements_by_page.get(page_index, ())
    ]
    chain_signature = sorted(
        canonical_id
        for canonical_id, _refs, pages in chains.values()
        if held.issuperset(pages)
    )
    material = {
        "pages": [page + 1 for page in article.pages],
        "first_source_ref": elements[0].source_ref if elements else None,
        "chain_signature": chain_signature,
    }
    return f"article-{_hash_record(material)}"


def _assign_article_ids(
    articles: list[Article], elements_by_page, chains
) -> None:
    for article in articles:
        article.article_id = _article_id(article, elements_by_page, chains)


def _build_grouping(docs, policy_of):
    roles = [page_role(page, index, policy_of) for index, page in enumerate(docs.page)]
    elements_by_page = _document_elements(docs)
    chains = _canonical_chains(docs)
    provisional = walk_roles(roles)
    _assign_article_ids(provisional, elements_by_page, chains)
    merged = merge_across_chains(provisional, chain_pages(docs))
    _assign_article_ids(merged, elements_by_page, chains)
    return (
        Grouping(roles=tuple(roles), articles=tuple(merged)),
        provisional,
        elements_by_page,
        chains,
    )


def build_articles(docs: il_version_1.Document, policy_of, _labels) -> Grouping:
    """Group one document with deterministic identities."""
    grouping, _provisional, _elements, _chains = _build_grouping(docs, policy_of)
    return grouping


def _fixed_obstacle_refs(page, page_number: int) -> tuple[str, ...]:
    refs = []
    for collection in (
        "pdf_xobject",
        "pdf_rectangle",
        "pdf_figure",
        "pdf_curve",
        "pdf_form",
    ):
        for index, item in enumerate(getattr(page, collection, ()) or ()):
            if _box_tuple(getattr(item, "box", None)) is not None:
                refs.append(f"p{page_number}:{collection}#{index}")
    return tuple(refs)


def _unsupported_pages(docs, elements_by_page, title_labels):
    unsupported = []
    for page_index, page in enumerate(docs.page):
        by_ref = {
            element.source_ref: element
            for element in elements_by_page.get(page_index, ())
        }
        candidates = [
            (
                _source_ref(page_index, paragraph_index),
                paragraph.chain_id,
            )
            for paragraph_index, paragraph in enumerate(page.pdf_paragraph)
            if paragraph.layout_label in title_labels
            and (paragraph.unicode or "").strip()
        ]
        evidence = set()
        for position, (left_ref, left_chain) in enumerate(candidates):
            for right_ref, right_chain in candidates[position + 1 :]:
                if by_ref[left_ref].column == by_ref[right_ref].column:
                    continue
                if left_chain and left_chain == right_chain:
                    continue
                evidence.update((left_ref, right_ref))
        if evidence:
            unsupported.append(
                UnsupportedArticlePage(
                    page=page_index + 1,
                    reason=UNSUPPORTED_SAME_PAGE_MULTI_ARTICLE,
                    evidence_refs=tuple(sorted(evidence)),
                )
            )
    return tuple(unsupported)


def _chain_issues(provisional, chains) -> tuple[ArticleIssue, ...]:
    owner = {
        page: article.article_id for article in provisional for page in article.pages
    }
    issues = []
    for canonical_id, refs, pages in sorted(chains.values()):
        article_ids = tuple(sorted({owner[page] for page in pages if page in owner}))
        if len(article_ids) > 1:
            issues.append(
                ArticleIssue(
                    code=ISSUE_CHAIN_SPANS_ARTICLES,
                    chain_id=canonical_id,
                    article_ids=article_ids,
                    element_refs=refs,
                )
            )
    return tuple(issues)


def _slot_box(elements) -> tuple[float, float, float, float] | None:
    boxes = [
        element.source_box
        for element in elements
        if element.source_box is not None
    ]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _article_ir(
    docs,
    article,
    roles,
    elements_by_page,
    chains,
    unsupported_pages,
) -> ArticleIR:
    held = set(article.pages)
    unsupported = {item.page for item in unsupported_pages}
    elements = tuple(
        element
        for page_index in article.pages
        for element in elements_by_page.get(page_index, ())
    )
    chain_ids = tuple(
        sorted(
            canonical_id
            for canonical_id, _refs, pages in chains.values()
            if held.issuperset(pages)
        )
    )
    slots = []
    for page_index in article.pages:
        page_number = page_index + 1
        if page_number in unsupported:
            continue
        page_elements = elements_by_page.get(page_index, ())
        columns = sorted({element.column for element in page_elements})
        for column in columns:
            members = [element for element in page_elements if element.column == column]
            box = _slot_box(members)
            if box is None:
                continue
            capacity = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
            slots.append(
                ArticleRegionSlot(
                    article_id=article.article_id,
                    page=page_number,
                    column=column,
                    slot_order=len(slots),
                    box=box,
                    fixed_obstacle_refs=_fixed_obstacle_refs(
                        docs.page[page_index], page_number
                    ),
                    capacity_hint=capacity,
                )
            )
    policy_evidence = tuple(
        ArticlePolicyEvidence(
            page=page_index + 1,
            role=roles[page_index].role,
            page_kind=roles[page_index].kind,
            reason=roles[page_index].reason,
            article_reflow_allowed=page_index + 1 not in unsupported,
        )
        for page_index in article.pages
    )
    return ArticleIR(
        article_id=article.article_id,
        pages=tuple(page + 1 for page in article.pages),
        elements=elements,
        slots=tuple(slots),
        chain_ids=chain_ids,
        policy_evidence=policy_evidence,
    )


def _document_ir(docs, grouping, provisional, elements_by_page, chains, labels):
    unsupported = _unsupported_pages(docs, elements_by_page, labels)
    articles = tuple(
        _article_ir(
            docs,
            article,
            grouping.roles,
            elements_by_page,
            chains,
            unsupported,
        )
        for article in grouping.articles
    )
    by_page = {
        page: article.article_id for article in articles for page in article.pages
    }
    by_element = {
        element.source_ref: article.article_id
        for article in articles
        for element in article.elements
    }
    by_chain = {
        chain_id: article.article_id
        for article in articles
        for chain_id in article.chain_ids
    }
    by_chain_member = {
        source_ref: canonical_id
        for canonical_id, source_refs, _pages in chains.values()
        if canonical_id in by_chain
        for source_ref in source_refs
        if source_ref in by_element
    }
    return ArticleDocumentIR(
        articles=articles,
        by_page=by_page,
        by_element=by_element,
        by_chain=by_chain,
        by_chain_member=by_chain_member,
        unsupported_pages=unsupported,
        issues=_chain_issues(provisional, chains),
    )


class ArticleBuilder:
    """Build and write the canonical article state for one document."""

    stage_name = "ArticleBuilder"

    def __init__(self, translation_config, policy_of=None):
        self.translation_config = translation_config
        self.config = load_grouping_config()
        self.labels = title_labels(self.config)
        self.taxonomy = load_taxonomy()
        self.policy_of = policy_of if policy_of is not None else self.taxonomy.policy_of

    def process(self, docs: il_version_1.Document) -> ArticleDocumentIR:
        grouping, provisional, elements, chains = _build_grouping(
            docs, self.policy_of
        )
        document_ir = _document_ir(
            docs, grouping, provisional, elements, chains, self.labels
        )
        self._write_ir(document_ir)
        self._write_report(docs, grouping, document_ir)
        return document_ir

    def _article_record(
        self,
        docs: il_version_1.Document,
        article: ArticleIR,
        merged_by_chain: bool,
    ) -> dict:
        start = docs.page[article.pages[0] - 1]
        title = title_paragraph(start, self.labels)
        title_ref = None
        if title is not None:
            title_ref = next(
                (
                    _source_ref(article.pages[0] - 1, index)
                    for index, paragraph in enumerate(start.pdf_paragraph)
                    if paragraph is title
                ),
                None,
            )
        return {
            "article_id": article.article_id,
            "pages": list(article.pages),
            "start_page": article.pages[0],
            "merged_by_chain": merged_by_chain,
            "title": None
            if title is None
            else {
                "source_ref": title_ref,
                "layout_label": title.layout_label,
                "text": title.unicode,
            },
            "chains": list(article.chain_ids),
            "paragraphs": [
                {"source_ref": element.source_ref, "page": element.page}
                for element in article.elements
            ],
        }

    def _write_ir(self, document_ir: ArticleDocumentIR) -> Path:
        path = Path(self.translation_config.get_working_file_path(IR_REPORT_NAME))
        path.write_bytes(document_ir.to_json_bytes())
        return path

    def _write_report(
        self,
        docs: il_version_1.Document,
        grouping: Grouping,
        document_ir: ArticleDocumentIR,
    ) -> Path:
        merged_by_id = {
            article.article_id: article.merged_by_chain
            for article in grouping.articles
        }
        report = {
            "counts": {
                "pages": len(docs.page),
                "articles": len(document_ir.articles),
                "unassigned": len(grouping.unassigned),
                "merged_by_chain": sum(
                    1 for article in grouping.articles if article.merged_by_chain
                ),
                "chains": len(document_ir.by_chain),
            },
            "title_labels": list(self.labels),
            "articles": [
                self._article_record(
                    docs, article, merged_by_id.get(article.article_id, False)
                )
                for article in document_ir.articles
            ],
            "unassigned": [
                {
                    "page": role.index + 1,
                    "page_kind": role.kind,
                    "reason": role.reason,
                }
                for role in grouping.unassigned
            ],
            "pages": [
                {
                    "page": role.index + 1,
                    "page_kind": role.kind,
                    "page_kind_conf": role.confidence,
                    "role": role.role,
                    "reason": role.reason,
                    "article_id": document_ir.by_page.get(role.index + 1),
                }
                for role in grouping.roles
            ],
            "unsupported_pages": [
                item.to_record() for item in document_ir.unsupported_pages
            ],
            "issues": [issue.to_record() for issue in document_ir.issues],
        }
        path = Path(self.translation_config.get_working_file_path(REPORT_NAME))
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        record_config_manifest(path.parent, [*DEFAULT_CONFIG_PATHS, CONFIG_PATH])
        logger.debug(
            "grouped %d pages into %d article(s), %d unassigned, map at %s",
            len(docs.page),
            len(grouping.articles),
            len(grouping.unassigned),
            path,
        )
        return path
