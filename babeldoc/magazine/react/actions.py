"""The one repair action of v1: translate the lines nobody translated.

An orphan line is a paragraph the layout parser recovered outside every
detected block. It reaches typesetting carrying its source text because it was
never offered to the translator at all, and it is the defect this batch exists
for. The action sends its text through the run's engine and writes the answer
back.

Two things decide whether a finding is one this action may act on, and both are
deterministic and are not the deciding model's to overrule. The share of the
wrong script has to be at or above the declared bound, because a paragraph that
is almost entirely the wrong script was not translated, whereas a mixed one is a
translation that kept a name in its source form. And the layout label has to be
one of the declared orphan labels, because a paragraph carrying any other label
*was* offered to the translator, and what it renders as is that translator's
decision -- a byline correctly left in its source script is exactly that case,
and rewriting it would be undoing a decision rather than repairing an omission.

The request carries the glossary. The ruled and extracted pairs whose source
occurs in the line are matched by the same matcher the translation prompt
matches with and stated in the same table shape, so a term a human ruled on
binds this path exactly as it binds the batch path. What was offered here is
recorded, so that the report on what a ruling reached counts this path too.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from babeldoc.magazine.detectors import base as detector_base
from babeldoc.magazine.prompt_loader import Prompt
from babeldoc.magazine.prompt_loader import load_prompt
from babeldoc.magazine.react import cache_key as cache_key_fields
from babeldoc.magazine.react import writeback
from babeldoc.magazine.react.cache_key import GROUP_ORPHAN
from babeldoc.magazine.react.cache_key import SERVED_BYPASSED
from babeldoc.magazine.react.cache_key import SERVED_MISS
from babeldoc.magazine.react.cache_key import SERVED_RETRY
from babeldoc.magazine.react.cache_key import SERVED_STALE
from babeldoc.magazine.react.cache_key import attribution
from babeldoc.magazine.react.config import MAX_PARAGRAPHS as MAX_PARAGRAPHS_KEY
from babeldoc.magazine.react.config import MIN_CHARS_KEY
from babeldoc.magazine.react.config import MIN_RATIO_KEY
from babeldoc.magazine.react.config import ORPHAN_LABELS_KEY
from babeldoc.magazine.react.config import Action
from babeldoc.magazine.react.config import RepairConfig
from babeldoc.translator.cache import TranslationCache

logger = logging.getLogger(__name__)

NAME = "translate_orphan_lines"

# The parameter the decision may set: how many paragraphs one iteration takes.
# Declared beside the vocabulary rather than here, because the loop reads it to
# bound an iteration whichever action that iteration is carrying out.
MAX_PARAGRAPHS = MAX_PARAGRAPHS_KEY

# One finding, one paragraph: an orphan line is untranslated on its own.
PARAGRAPHS_PER_FINDING = 1

TRANSLATE_PROMPT = "react_translate_orphan"
GLOSSARY_PROMPT = "react_orphan_glossary"

# Engine name the orphan translations are filed under. The column is 20 wide.
ENGINE_NAME = "magazine_orphan"

# The same composition the decision cache is keyed by, taken from the one place
# it is defined so the two request points cannot drift apart. This prompt
# renders no evidence block, so the projection has no field to drop here; what
# it shares is the composition and the version that retires stored replies.
CACHE_KEY_VERSION = cache_key_fields.CACHE_KEY_VERSION

TRANSLATION_FIELD = "translation"

# Why a finding was not acted on. Recorded rather than dropped: a filter whose
# rejections are invisible is a filter nobody can argue with.
REASON_KIND = "kind_outside_action"
REASON_RATIO = "residue_ratio_below_bound"
REASON_LABEL = "layout_label_not_orphan"
REASON_SHORT = "source_text_too_short"
REASON_NO_PARAGRAPH = "paragraph_reference_not_resolvable"
REASON_MANY = "finding_is_about_more_than_one_paragraph"
REASON_NO_STYLE = "paragraph_carries_no_style_to_write_into"
REASON_CEILING = "action_application_ceiling_reached"
REASON_LIMIT = "iteration_paragraph_limit_reached"
REASON_REFUSED = "translation_refused"
REASON_UNCHANGED = "translation_equals_source"
REASON_LAYOUT = "retypesetting_produced_nothing"
REASON_GEOMETRY = "retypesetting_needed_more_room_than_the_paragraph_had"

ACCEPTED = "accepted"


@dataclass(frozen=True)
class Candidate:
    """One finding, resolved to the paragraph it is about."""

    issue_id: str
    reference: str
    page_index: int
    paragraph_index: int
    paragraph: object
    page: object
    source_text: str
    # The finding this candidate was resolved from. An action about a single
    # paragraph has everything it needs without it; one about a pair reads the
    # second member's reference from here, because the pair is what the finding
    # is and the resolution is only ever to one of them.
    issue: object = None


@dataclass
class Application:
    """What happened to one candidate."""

    issue_id: str
    reference: str
    accepted: bool
    reason: str
    source_text: str = ""
    translated_text: str = ""
    offered_text: str = ""
    glossary_entries: list[list[str]] = field(default_factory=list)
    attempts: int = 0
    from_cache: bool = False
    changed: bool = False
    # What a geometric action measured before and after it acted. Empty for an
    # action whose evidence is text, and the whole of the evidence for one whose
    # evidence is where the ink landed.
    geometry: dict = field(default_factory=dict)
    # One row per call this application made that reached the transport, which
    # is one row per call it was billed for. Empty for an action that sends
    # nothing and for a request the cache answered.
    calls: list[dict] = field(default_factory=list)

    def as_record(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "paragraph_ref": self.reference,
            "accepted": self.accepted,
            "reason": self.reason,
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "offered_text": self.offered_text,
            "glossary_entries": [list(pair) for pair in self.glossary_entries],
            "attempts": self.attempts,
            "from_cache": self.from_cache,
            "changed": self.changed,
            "geometry": dict(self.geometry),
            "calls": [dict(row) for row in self.calls],
        }


def applicability(action: Action) -> tuple[float, int, tuple[str, ...]]:
    rule = action.applicability
    return (
        float(rule[MIN_RATIO_KEY]),
        int(rule[MIN_CHARS_KEY]),
        tuple(rule[ORPHAN_LABELS_KEY]),
    )


def admits(issue, paragraph, action: Action, source_text: str) -> str:
    """Why this finding is not one to act on, or ``ACCEPTED``."""
    min_ratio, min_chars, orphan_labels = applicability(action)
    if (paragraph.layout_label or "") not in orphan_labels:
        return REASON_LABEL
    ratio = issue.evidence.get("residue_ratio")
    if not isinstance(ratio, int | float) or float(ratio) < min_ratio:
        return REASON_RATIO
    if len(source_text.strip()) < min_chars:
        return REASON_SHORT
    if not writeback.can_write_back(paragraph):
        return REASON_NO_STYLE
    return ACCEPTED


def admits_candidate(issue, candidate, action: Action, context) -> str:  # noqa: ARG001 - the pass is part of the question every action is asked
    """This action's admission question, in the shape the loop asks every action."""
    return admits(issue, candidate.paragraph, action, candidate.source_text)


def resolve(issue, pages_by_label: dict) -> Candidate | None:
    """The single paragraph one finding is about, where there is exactly one."""
    view = pages_by_label.get(issue.page)
    if view is None:
        return None
    reference = issue.paragraph_refs[0]
    paragraphs = view.page.pdf_paragraph or []
    for index in range(len(paragraphs)):
        if view.reference(index) != reference:
            continue
        return Candidate(
            issue_id=issue.id,
            reference=reference,
            page_index=view.label,
            paragraph_index=index,
            paragraph=paragraphs[index],
            page=view.page,
            source_text=detector_base.rendered_text(paragraphs[index]).strip(),
            issue=issue,
        )
    return None


def page_context(view, skip_index: int, limit: int) -> str:
    """What else the page says, as the request shows it.

    Bounded, and drawn from the page the line stands on rather than from the
    document: what a credit line needs is how the names beside it are being
    rendered, and that is on the page.
    """
    if limit <= 0:
        return "(not shown)"
    parts: list[str] = []
    total = 0
    for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
        if index == skip_index:
            continue
        text = detector_base.rendered_text(paragraph).strip()
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= limit:
            break
    joined = "\n".join(parts)[:limit]
    return joined or "(the page carries no other text)"


def glossary_entries(glossaries, text: str, limit: int) -> list[tuple[str, str]]:
    """The declared pairs whose source occurs in ``text``, by the shared matcher."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for glossary in glossaries or ():
        try:
            active = glossary.get_active_entries_for_text(text)
        except Exception as exc:  # noqa: BLE001 - a glossary is never a hard failure
            logger.debug("glossary matching failed, ignoring it: %s", exc)
            continue
        for source, target in sorted(active):
            if source in seen:
                continue
            seen.add(source)
            found.append((source, target))
            if len(found) >= limit:
                return found
    return found


def glossary_block(entries, working_dir) -> str:
    if not entries:
        return ""
    rows = "\n".join(f"| {source} | {target} |" for source, target in entries)
    return load_prompt(
        GLOSSARY_PROMPT, {"glossary_rows": rows}, working_dir=working_dir
    ).text


def cache_key(prompt: Prompt, identity: str) -> str:
    """Digest of everything that could change the translation of one line."""
    return cache_key_fields.digest(identity, prompt.digest, prompt.text)


def interpret(reply: str) -> tuple[str | None, str]:
    """One reply as a translated line, or the violation that refuses it."""
    from babeldoc.magazine.react.decide import strip_fence

    try:
        parsed = json.loads(strip_fence(reply))
    except (ValueError, TypeError) as exc:
        return None, f"reply is not JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, f"reply is a {type(parsed).__name__}, not one JSON object"
    if TRANSLATION_FIELD not in parsed:
        return None, f"reply omits {TRANSLATION_FIELD!r}"
    extra = sorted(set(parsed) - {TRANSLATION_FIELD})
    if extra:
        return None, f"reply carries fields nothing asked for: {extra}"
    value = parsed[TRANSLATION_FIELD]
    if not isinstance(value, str) or not value.strip():
        return None, f"{TRANSLATION_FIELD} is not a non-empty string"
    return value.strip(), ""


class CachedOrphanTranslator:
    """One translation point for orphan lines: cache, bounded attempts, strict reply."""

    def __init__(
        self,
        config: RepairConfig,
        transport=None,
        cache: TranslationCache | None = None,
        identity: str = "",
        language: str = "",
        glossaries=(),
        working_dir: Path | str | None = None,
        ignore_cache: bool = False,
    ) -> None:
        self.config = config
        self.transport = transport
        self.cache = (
            TranslationCache(ENGINE_NAME, {"cache_key_version": CACHE_KEY_VERSION})
            if cache is None
            else cache
        )
        self.identity = identity
        self.language = language
        self.glossaries = glossaries
        self.working_dir = working_dir
        self.ignore_cache = ignore_cache

    def prompt(self, source_text: str, context: str, entries) -> Prompt:
        return load_prompt(
            TRANSLATE_PROMPT,
            {
                "target_language": self.language,
                "source_text": source_text,
                "page_context": context,
                "glossary_block": glossary_block(entries, self.working_dir),
            },
            working_dir=self.working_dir,
        )

    def _retry_text(self, prompt: Prompt, violation: str) -> str:
        from babeldoc.magazine.react.decide import RETRY_PROMPT

        notice = load_prompt(
            RETRY_PROMPT, {"violation": violation}, working_dir=self.working_dir
        )
        return f"{prompt.text}\n\n{notice.text}"

    def translate(self, source_text: str, context: str) -> Application:
        """Render one orphan line, from cache where the request is not new."""
        entries = glossary_entries(
            self.glossaries, source_text, self.config.max_glossary_entries
        )
        prompt = self.prompt(source_text, context, entries)
        result = Application(
            issue_id="",
            reference="",
            accepted=False,
            reason=REASON_REFUSED,
            source_text=source_text,
            offered_text=source_text,
            glossary_entries=[list(pair) for pair in entries],
        )
        key = cache_key(prompt, self.identity)
        verdict = SERVED_BYPASSED if self.ignore_cache else SERVED_MISS
        if not self.ignore_cache:
            try:
                stored = self.cache.get(key)
            except Exception as exc:  # noqa: BLE001 - a cache is never a hard failure
                logger.debug("orphan cache lookup failed, ignoring it: %s", exc)
                stored = None
            if stored is not None:
                text, violation = interpret(stored)
                if text is not None:
                    result.accepted = True
                    result.reason = ACCEPTED
                    result.translated_text = text
                    result.from_cache = True
                    return result
                logger.debug("cached orphan reply rejected, re-requesting: %s", violation)
                verdict = SERVED_STALE

        violations: list[str] = []
        attempts = 0
        text_to_send = prompt.text
        while attempts < self.config.decide_max_attempts:
            attempts += 1
            result.calls.append(
                attribution(
                    GROUP_ORPHAN,
                    SERVED_RETRY if attempts > 1 else verdict,
                    key,
                    prompt.digest,
                    text_to_send,
                    attempts,
                    identity=self.identity,
                )
            )
            try:
                reply = self.transport.complete(text_to_send)
            except Exception as exc:  # noqa: BLE001 - any failure is a violation
                violations.append(f"request failed: {type(exc).__name__}: {exc}")
                continue
            text, violation = interpret(reply)
            if text is not None:
                if not self.ignore_cache:
                    try:
                        self.cache.set(key, reply)
                    except Exception as exc:  # noqa: BLE001 - see above
                        logger.debug("orphan cache write failed, ignoring: %s", exc)
                result.accepted = True
                result.reason = ACCEPTED
                result.translated_text = text
                result.attempts = attempts
                return result
            violations.append(violation)
            text_to_send = self._retry_text(prompt, violation)
        result.attempts = attempts
        result.reason = f"{REASON_REFUSED}: {'; '.join(violations)}"
        return result
