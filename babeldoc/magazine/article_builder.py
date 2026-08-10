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
writes nothing into the intermediate language. What it finds goes to
``article_map.json`` beside the other sidecars: the schema is frozen, and an
article is a property of the document's structure rather than of any one
paragraph, so the map is a document of its own. Nothing downstream of this stage
is affected by it in this batch, which is why the stage leaves no checkpoint of
its own: the intermediate language after it is the one the chain builder's
checkpoint already holds.

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

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.paragraph_finder import generate_base58_id
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


def build_articles(docs: il_version_1.Document, policy_of, labels) -> Grouping:
    """Group one document: roles, the walk they imply, then the chain merge."""
    roles = [page_role(page, index, policy_of) for index, page in enumerate(docs.page)]
    articles = merge_across_chains(walk_roles(roles), chain_pages(docs))
    for article in articles:
        article.article_id = generate_base58_id()
    return Grouping(roles=tuple(roles), articles=tuple(articles))


class ArticleBuilder:
    """Group the pages of a document into articles and write the map."""

    stage_name = "ArticleBuilder"

    def __init__(self, translation_config, policy_of=None):
        self.translation_config = translation_config
        self.config = load_grouping_config()
        self.labels = title_labels(self.config)
        self.taxonomy = load_taxonomy()
        self.policy_of = policy_of if policy_of is not None else self.taxonomy.policy_of

    def process(self, docs: il_version_1.Document) -> il_version_1.Document:
        grouping = build_articles(docs, self.policy_of, self.labels)
        self._write_report(docs, grouping)
        return docs

    def _article_record(
        self, docs: il_version_1.Document, article: Article, chains: dict[str, list[int]]
    ) -> dict:
        start = docs.page[article.pages[0]]
        title = title_paragraph(start, self.labels)
        held = set(article.pages)
        return {
            "article_id": article.article_id,
            # 1-based file page order, the form every other sidecar reports in.
            "pages": [index + 1 for index in article.pages],
            "start_page": article.pages[0] + 1,
            "merged_by_chain": article.merged_by_chain,
            "title": None
            if title is None
            else {
                "debug_id": title.debug_id,
                "layout_label": title.layout_label,
                "text": title.unicode,
            },
            "chains": sorted(
                chain_id
                for chain_id, pages in chains.items()
                if held.issuperset(pages)
            ),
            "paragraphs": [
                {"debug_id": paragraph.debug_id, "page": index + 1}
                for index in article.pages
                for paragraph in docs.page[index].pdf_paragraph
            ],
        }

    def _write_report(self, docs: il_version_1.Document, grouping: Grouping) -> Path:
        chains = chain_pages(docs)
        by_page = {
            index: article.article_id
            for article in grouping.articles
            for index in article.pages
        }
        report = {
            "counts": {
                "pages": len(docs.page),
                "articles": len(grouping.articles),
                "unassigned": len(grouping.unassigned),
                "merged_by_chain": sum(
                    1 for article in grouping.articles if article.merged_by_chain
                ),
                "chains": len(chains),
            },
            "title_labels": list(self.labels),
            "articles": [
                self._article_record(docs, article, chains)
                for article in grouping.articles
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
                    "article_id": by_page.get(role.index),
                }
                for role in grouping.roles
            ],
        }
        path = Path(self.translation_config.get_working_file_path(REPORT_NAME))
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
        record_config_manifest(path.parent, [*DEFAULT_CONFIG_PATHS, CONFIG_PATH])
        logger.debug(
            "grouped %d pages into %d article(s), %d unassigned, map at %s",
            len(docs.page),
            len(grouping.articles),
            len(grouping.unassigned),
            path,
        )
        return path
