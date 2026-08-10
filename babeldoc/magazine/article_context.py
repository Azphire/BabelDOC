"""Article level translation context: one brief per article, carried by its batches.

B5 solved the cut -- a sentence broken by a page break is translated whole. This
solves the drift: a feature running over four pages is translated in a dozen
independent requests, and nothing tells the eleventh request what the first
decided about the piece's voice, or how it rendered the name of the person the
whole article is about. The answer here is a brief rather than a rolling
summary: one small request per article, made before its paragraphs are
translated, whose answer every batch of that article then carries.

What the brief is made of is deliberately thin -- the article's heading and the
opening of its body text. That is what a copy editor would hand a translator,
it is bounded work whatever the article's length, and it is fixed for the whole
article, so the request is cacheable and two runs over one unchanged article
cost one call.

The brief is consumed and never stored. It reaches the engine as a block of
contextual hints beside the running title and it goes nowhere else: not into the
intermediate language, which is frozen, and above all not into the glossary. A
glossary is an authority over terminology that a person or the extraction stage
writes; letting a model's guess at a name flow into it would make one model's
reading of one opening paragraph binding on the rest of the document, and would
launder a guess into a decision. The names in a brief are guidance to the same
model in the same request, which is a different thing entirely.

Everything degrades to nothing. An article whose brief cannot be produced --
the request failed, the reply was not the object it was asked for, the article
carries no text to describe -- is translated exactly as it would have been with
the switch down, and the sidecar records that it was. A brief is guidance and
never a precondition, so there is no path here that can stop a translation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from babeldoc.magazine import article_builder
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.prompt_loader import Prompt
from babeldoc.magazine.prompt_loader import load_prompt
from babeldoc.magazine.taxonomy import DEFAULT_CONFIG_PATHS
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest
from babeldoc.translator.cache import TranslationCache

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "article_context.json"

REPORT_NAME = "article_context.report.json"

# The template that asks for a brief, and the template that states one back to
# the translating model. Neither text lives in this file.
BRIEF_PROMPT = "article_brief"
CONTEXT_PROMPT = "article_brief_context"

# Engine name the cached briefs are filed under, keeping them apart from the
# translated segments sharing the database. The column is 20 characters wide.
ENGINE_NAME = "magazine_brief"

# Bumped when the composition of the cache key changes, which retires every
# entry written under the old composition in one step.
CACHE_KEY_VERSION = 1

# Where the body label vocabulary is declared. The excerpt is drawn from a
# paragraph of running text, and what that means is declared once for the whole
# project rather than again here.
BODY_LABELS_KEY = "body_labels"

# Fields a reply must carry. Anything else in the object is ignored.
REQUIRED_REPLY_FIELDS = ("title_translation", "register", "names")

# Why an article carries no brief.
REASON_NO_SOURCE = "no_source_text"
REASON_REFUSED = "reply_refused"
REASON_TRANSPORT = "request_failed"


class ArticleContextError(ConfigError):
    """Raised when the article context configuration is unusable."""


@dataclass(frozen=True)
class BriefConfig:
    """Everything bounded about producing and accepting one brief."""

    first_body_excerpt_chars: int
    max_attempts: int
    max_names: int
    max_name_chars: int
    max_register_chars: int
    max_title_translation_chars: int


@lru_cache(maxsize=1)
def load_context_config(path: str | None = None) -> BriefConfig:
    """Load and validate ``configs/article_context.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = validate_bounded_config(raw, config_path)
    missing = sorted(set(BriefConfig.__dataclass_fields__) - set(parameters))
    if missing:
        raise ArticleContextError(f"{config_path.name}: missing parameters {missing}")
    return BriefConfig(
        first_body_excerpt_chars=int(parameters["first_body_excerpt_chars"]),
        max_attempts=int(parameters["max_attempts"]),
        max_names=int(parameters["max_names"]),
        max_name_chars=int(parameters["max_name_chars"]),
        max_register_chars=int(parameters["max_register_chars"]),
        max_title_translation_chars=int(parameters["max_title_translation_chars"]),
    )


@dataclass(frozen=True)
class ArticleBrief:
    """What one article was described as, in the target language."""

    title_translation: str
    register: str
    names: tuple[str, ...]

    def as_record(self) -> dict:
        return {
            "title_translation": self.title_translation,
            "register": self.register,
            "names": list(self.names),
        }


@dataclass(frozen=True)
class BriefOutcome:
    """One attempt at describing one article, accepted or refused."""

    brief: ArticleBrief | None = None
    reason: str = ""
    attempts: int = 0
    from_cache: bool = False

    @property
    def failed(self) -> bool:
        return self.brief is None


@dataclass(frozen=True)
class ArticleSource:
    """The text one brief is asked for from, and the pages it speaks for."""

    article_id: str
    pages: tuple[int, ...]
    title_text: str
    excerpt: str

    @property
    def has_text(self) -> bool:
        return bool(self.title_text.strip() or self.excerpt.strip())


class BriefTransport(Protocol):
    """How a rendered brief request reaches a model."""

    def complete(self, prompt_text: str) -> str:
        """Return the model's reply text, or raise if the request fails."""


class EngineTransport:
    """The translation engine, asked a question that is not a translation.

    A brief is a text-only request to the model already configured for this
    run, so it travels the engine's own transport: its credential, its endpoint
    and its rate limiter, none of which is configured a second time here. The
    engine's own cache is bypassed, because the cache that serves a brief is
    the one below, whose key names the prompt file a request came from.
    """

    def __init__(self, engine):
        self.engine = engine

    def complete(self, prompt_text: str) -> str:
        return self.engine.llm_translate(
            prompt_text,
            ignore_cache=True,
            rate_limit_params={"request_json_mode": True},
        )


def engine_identity(engine, lang_out: str) -> str:
    """What about the engine could change a brief, as a cache key fragment."""
    return f"{type(engine).__name__}/{getattr(engine, 'name', '')}/{lang_out}"


def cache_key(prompt: Prompt, identity: str) -> str:
    """Digest of everything that could change the answer to one request."""
    fields = (
        f"cache_key_version={CACHE_KEY_VERSION}",
        f"engine={identity}",
        f"prompt_file_sha256={prompt.digest}",
        f"prompt_text_sha256={hashlib.sha256(prompt.text.encode()).hexdigest()}",
    )
    return hashlib.sha256("\n".join(fields).encode()).hexdigest()


def _clean(reply: str) -> str:
    """Strip a code fence a chat model wrapped its object in."""
    text = reply.strip()
    for opener in ("```json", "```"):
        if text.startswith(opener):
            text = text[len(opener) :]
            break
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def interpret_reply(reply: str, config: BriefConfig) -> BriefOutcome:
    """Turn a reply into a brief, refusing anything that is not one.

    A field of the wrong type is a refusal: the reply did not do as it was
    asked and nothing here guesses at what it meant. A field that is merely
    longer than its bound is cut to it, a verbose brief still being usable
    guidance.
    """
    try:
        payload = json.loads(_clean(reply))
    except (json.JSONDecodeError, TypeError) as exc:
        return BriefOutcome(reason=f"reply is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        return BriefOutcome(
            reason=f"reply is a {type(payload).__name__}, expected a JSON object"
        )

    missing = sorted(set(REQUIRED_REPLY_FIELDS) - set(payload))
    if missing:
        return BriefOutcome(reason=f"reply is missing fields {missing}")

    for field_name in ("title_translation", "register"):
        if not isinstance(payload[field_name], str):
            return BriefOutcome(reason=f"{field_name} is not a string")
    names = payload["names"]
    if not isinstance(names, list) or any(
        not isinstance(name, str) for name in names
    ):
        return BriefOutcome(reason="names is not an array of strings")

    return BriefOutcome(
        brief=ArticleBrief(
            title_translation=payload["title_translation"].strip()[
                : config.max_title_translation_chars
            ],
            register=payload["register"].strip()[: config.max_register_chars],
            names=tuple(
                name.strip()[: config.max_name_chars]
                for name in names[: config.max_names]
                if name.strip()
            ),
        )
    )


class CachedBriefClient:
    """One brief request point: cache lookup, bounded attempts, strict reply.

    The same three rules the vision client is built to, with one difference of
    substance: the transport is the run's own translation engine rather than a
    client configured here, because a brief is a text request to the model
    already translating the document. What this class owns is the cache
    identity -- a key naming the prompt file a request came from, so a reworded
    template cannot be answered from replies to the old wording -- and the
    contract a reply has to meet.
    """

    def __init__(
        self,
        config: BriefConfig | None = None,
        transport: BriefTransport | None = None,
        cache: TranslationCache | None = None,
        identity: str = "",
        ignore_cache: bool = False,
    ) -> None:
        self.config = load_context_config() if config is None else config
        self.transport = transport
        self.cache = (
            TranslationCache(ENGINE_NAME, {"cache_key_version": CACHE_KEY_VERSION})
            if cache is None
            else cache
        )
        self.identity = identity
        # A run told to ignore the translation cache ignores it here too: an
        # engine set that way is being watched, and a brief served from a
        # previous run's reply would make the count of requests meaningless.
        self.ignore_cache = ignore_cache

    def cache_key(self, prompt: Prompt) -> str:
        return cache_key(prompt, self.identity)

    def brief(self, prompt: Prompt) -> BriefOutcome:
        """Describe one article, from cache when the request is not new."""
        key = self.cache_key(prompt)
        stored = None
        if not self.ignore_cache:
            try:
                stored = self.cache.get(key)
            except Exception as exc:  # noqa: BLE001 - a cache is never a hard failure
                logger.debug("brief cache lookup failed, ignoring it: %s", exc)
        if stored is not None:
            outcome = interpret_reply(stored, self.config)
            if not outcome.failed:
                return BriefOutcome(
                    brief=outcome.brief, attempts=0, from_cache=True
                )
            # A stored reply that no longer validates means the contract moved
            # under it. Ask again rather than serve what the caller cannot use.
            logger.debug("cached brief rejected, re-requesting: %s", outcome.reason)

        refusals: list[str] = []
        attempts = 0
        while attempts < self.config.max_attempts:
            attempts += 1
            try:
                reply = self.transport.complete(prompt.text)
            except Exception as exc:  # noqa: BLE001 - any failure is a refusal
                refusals.append(f"{REASON_TRANSPORT}: {type(exc).__name__}: {exc}")
                continue
            outcome = interpret_reply(reply, self.config)
            if not outcome.failed:
                if not self.ignore_cache:
                    try:
                        self.cache.set(key, reply)
                    except Exception as exc:  # noqa: BLE001 - see above
                        logger.debug("brief cache write failed, ignoring it: %s", exc)
                return BriefOutcome(
                    brief=outcome.brief, attempts=attempts, from_cache=False
                )
            refusals.append(f"{REASON_REFUSED}: {outcome.reason}")

        return BriefOutcome(reason="; ".join(refusals), attempts=attempts)


class ArticleContext:
    """Which article each page belongs to, and what its batches carry.

    The empty context is what a document translated with the switch down leaves
    behind: it declares no heading labels, opens no article and hands out no
    brief, so every call site reads the same with the pass absent as present.
    """

    def __init__(
        self,
        page_index: dict[int, int] | None = None,
        article_of_page: dict[int, str] | None = None,
        brief_of_article: dict[str, str] | None = None,
        opener_indices: frozenset[int] = frozenset(),
        title_labels: tuple[str, ...] = (),
    ) -> None:
        self._page_index = page_index or {}
        self._article_of_page = article_of_page or {}
        self._brief_of_article = brief_of_article or {}
        self._opener_indices = opener_indices
        self._title_labels = title_labels

    def __bool__(self) -> bool:
        return bool(self._page_index)

    @property
    def declares_titles(self) -> bool:
        """Whether this context supplies the heading labels to be read."""
        return bool(self._title_labels)

    @property
    def title_labels(self) -> tuple[str, ...]:
        return self._title_labels

    def is_running_title(self, paragraph) -> bool:
        """Whether this paragraph is a heading the running title follows."""
        return getattr(paragraph, "layout_label", None) in self._title_labels

    def index_of(self, page) -> int | None:
        return self._page_index.get(id(page))

    def opens_article(self, page) -> bool:
        """Whether an article begins on this page, so the scope starts afresh."""
        index = self.index_of(page)
        return index is not None and index in self._opener_indices

    def brief_for_page_index(self, index: int | None) -> str | None:
        if index is None:
            return None
        article_id = self._article_of_page.get(index)
        if article_id is None:
            return None
        return self._brief_of_article.get(article_id)

    def brief_for_page(self, page) -> str | None:
        """The brief a batch of this page carries, or None where there is none."""
        return self.brief_for_page_index(self.index_of(page))

    def brief_for_page_pair(self, first, second) -> str | None:
        """The brief a pair spanning two pages carries.

        A pair whose halves belong to two different articles, or to none,
        carries nothing: there is no one piece it is part of.
        """
        left, right = self.index_of(first), self.index_of(second)
        if left is None or right is None:
            return None
        article = self._article_of_page.get(left)
        if article is None or article != self._article_of_page.get(right):
            return None
        return self._brief_of_article.get(article)


# What a document translated with the switch down leaves behind.
EMPTY_CONTEXT = ArticleContext()


def first_body_excerpt(page, body_labels, limit: int) -> str:
    """The opening of the first paragraph of running text on a page."""
    for paragraph in page.pdf_paragraph:
        if getattr(paragraph, "layout_label", None) not in body_labels:
            continue
        text = (paragraph.unicode or "").strip()
        if text:
            return text[:limit]
    return ""


def article_sources(docs, grouping, title_labels, body_labels, config) -> list:
    """The heading and opening excerpt of every article, in page order."""
    sources = []
    for article in grouping.articles:
        start = docs.page[article.pages[0]]
        title = article_builder.title_paragraph(start, title_labels)
        excerpt = ""
        for index in article.pages:
            excerpt = first_body_excerpt(
                docs.page[index], body_labels, config.first_body_excerpt_chars
            )
            if excerpt:
                break
        sources.append(
            ArticleSource(
                article_id=article.article_id,
                pages=tuple(article.pages),
                title_text="" if title is None else (title.unicode or "").strip(),
                excerpt=excerpt,
            )
        )
    return sources


class ArticleContextPlan:
    """Every article of one document, described once and reported on."""

    def __init__(
        self,
        translation_config,
        client: CachedBriefClient | None = None,
        policy_of=None,
    ) -> None:
        self.translation_config = translation_config
        self.config = load_context_config()
        self.grouping_config = article_builder.load_grouping_config()
        self.title_labels = article_builder.title_labels(self.grouping_config)
        self.body_labels = tuple(load_chain_config()[BODY_LABELS_KEY])
        taxonomy = load_taxonomy()
        self.policy_of = policy_of if policy_of is not None else taxonomy.policy_of
        self.client = client
        self.records: list[dict] = []
        self.requests = 0

    @property
    def working_dir(self):
        return Path(
            self.translation_config.get_working_file_path(REPORT_NAME)
        ).parent

    def _request(self, source: ArticleSource) -> tuple[BriefOutcome, Prompt | None]:
        prompt = load_prompt(
            BRIEF_PROMPT,
            {
                "title_paragraph": source.title_text,
                "first_body_excerpt": source.excerpt,
                "target_language": self.translation_config.lang_out,
            },
            working_dir=self.working_dir,
        )
        self.requests += 1
        return self.client.brief(prompt), prompt

    def _context_text(self, brief: ArticleBrief) -> str:
        prompt = load_prompt(
            CONTEXT_PROMPT,
            {
                "title_translation": brief.title_translation,
                "register": brief.register,
                "names": "; ".join(brief.names),
            },
            working_dir=self.working_dir,
        )
        return prompt.text.strip()

    def plan(self, docs) -> ArticleContext:
        grouping = article_builder.build_articles(
            docs, self.policy_of, self.title_labels
        )
        sources = article_sources(
            docs,
            grouping,
            self.title_labels,
            self.body_labels,
            self.config,
        )

        brief_of_article: dict[str, str] = {}
        for source in sources:
            if not source.has_text:
                self._record(source, BriefOutcome(reason=REASON_NO_SOURCE), False)
                continue
            outcome, _prompt = self._request(source)
            if outcome.failed:
                logger.info(
                    "article %s carries no brief: %s", source.article_id, outcome.reason
                )
            else:
                brief_of_article[source.article_id] = self._context_text(outcome.brief)
            self._record(source, outcome, True)

        page_index = {id(page): index for index, page in enumerate(docs.page)}
        article_of_page = {
            index: article.article_id
            for article in grouping.articles
            for index in article.pages
        }
        openers = frozenset(article.pages[0] for article in grouping.articles)
        context = ArticleContext(
            page_index=page_index,
            article_of_page=article_of_page,
            brief_of_article=brief_of_article,
            opener_indices=openers,
            title_labels=self.title_labels,
        )
        self._write_report(grouping)
        return context

    def _record(
        self, source: ArticleSource, outcome: BriefOutcome, requested: bool
    ) -> None:
        self.records.append(
            {
                "article_id": source.article_id,
                "pages": [index + 1 for index in source.pages],
                "start_page": source.pages[0] + 1,
                "title_text": source.title_text,
                "excerpt_chars": len(source.excerpt),
                "requested": requested,
                "brief_failed": outcome.failed,
                "reason": outcome.reason,
                "attempts": outcome.attempts,
                "from_cache": outcome.from_cache,
                "brief": None if outcome.brief is None else outcome.brief.as_record(),
            }
        )

    def _write_report(self, grouping) -> Path:
        report = {
            "counts": {
                "articles": len(self.records),
                "requested": sum(1 for row in self.records if row["requested"]),
                "briefs": sum(1 for row in self.records if not row["brief_failed"]),
                "failed": sum(1 for row in self.records if row["brief_failed"]),
                "from_cache": sum(1 for row in self.records if row["from_cache"]),
                "requests": self.requests,
            },
            "title_labels": list(self.title_labels),
            "body_labels": list(self.body_labels),
            "articles": self.records,
            "unassigned_pages": [
                role.index + 1 for role in grouping.unassigned
            ],
        }
        path = Path(self.translation_config.get_working_file_path(REPORT_NAME))
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
        record_config_manifest(
            path.parent,
            [*DEFAULT_CONFIG_PATHS, article_builder.CONFIG_PATH, CONFIG_PATH],
        )
        logger.debug(
            "article context: %d article(s), %d brief(s), report at %s",
            len(self.records),
            report["counts"]["briefs"],
            path,
        )
        return path


def plan_article_context(
    translator,
    docs,
    transport: BriefTransport | None = None,
    client: CachedBriefClient | None = None,
):
    """Describe every article of ``docs`` before its paragraphs are translated."""
    config = translator.translation_config
    engine = translator.translate_engine
    if client is None:
        client = CachedBriefClient(
            transport=EngineTransport(engine) if transport is None else transport,
            identity=engine_identity(engine, config.lang_out),
            ignore_cache=bool(getattr(engine, "ignore_cache", False)),
        )
    return ArticleContextPlan(config, client=client).plan(docs)
