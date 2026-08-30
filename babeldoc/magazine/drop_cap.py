"""Drop cap candidates, and the verdict a human returns on them.

A drop cap is the oversized initial a magazine opens a piece of running text
with. It is a typographic decision rather than a linguistic one, and it is not
one a translation can take on its own: the source may paint the initial either
as the paragraph's leading run or as a separate visual paragraph. In both
forms, translating the body alone leaves an untranslated source initial beside
the target word. This module therefore freezes one unambiguous visual-initial
owner binding, exposes it to review, and merges the source character into that
owner before translation.

The evidence is general, bounded by ``configs/drop_cap.json``, and never names a
publication or page type. A separate visual initial additionally has to be a
single oversized letter in the same article, page and column, immediately
before the body owner in reading order, geometrically attached to its first
line, and in a one-to-one binding. Ambiguous bindings are not candidates.

The paragraph is body text, by the label vocabulary every other stage reads. It
belongs to an article, and stands within the first few body paragraphs of it or
on the page that article opens on -- which is where an opening initial goes, and
which is why this needs the article map: a paragraph in no article is never a
candidate, and a run without the grouping stage has no map to read. Its opening
run of characters is large against the paragraph's own median character size and
short enough to be an initial rather than a heading the paragraph finder swept in.

The size ratio is measured against the paragraph's median rather than the
document's: a magazine sets its body text at several sizes, and what makes an
initial an initial is that it towers over the text it opens, not over the
average of the issue.

The switch is ``magazine_drop_cap_mark``, down by default, and it is an
attribute of the translation configuration rather than a constructor parameter
of it: this batch adds nothing upstream, so the flag is read from whatever the
caller set on the object and is off wherever nobody set it (see W-B7-02). It
requires ``magazine_article_group``, and a run that raises one without the other
is refused rather than quietly marking nothing, because a run that was asked for
candidates and produced none has to be a run that found none.

Where the initial is read from
------------------------------

From rendered characters, not merely from the first composition. For an inline
initial those characters may be grouped as a style run or formula. For a
standalone initial the visual paragraph must contain exactly one regroupable
letter, while ArticleIR reading order and source geometry prove the body owner;
the frozen companion ref remains audit evidence after its paint is cleared.

What consumes the ruling
------------------------

``apply``, behind ``magazine_drop_cap_apply`` and down by default, run after the
ruling is injected and before the translator is built. It is the reader of the
``dropCapDecision`` attribute B1 added to the schema, and it merges under either
verdict: the enlarged initial goes into the text it opens, so the first word
reaches the engine as a word. Both verdicts, because an initial the engine meets
as a style run of its own is an initial it can carry across untranslated, and
that is true whichever way the finished page is set. What a verdict decides is
therefore only what is done once the translation is back -- ``flatten`` leaves
the paragraph set as one run of body text, ``keep`` has the render lane beside
this one set the opening character the way the target language sets one -- and
the two hand the engine byte identical text. A candidate nobody ruled takes the
default its target language declares in ``configs/drop_cap.json``, which is how a
run with no human in it still decides, and only a marked candidate is decided
that way.

The merge is the whole of the mechanism, and the typographic downgrade follows
from it rather than from a rewrite of the characters. One composition carrying
the paragraph's own base style is what the translator's fast path reads as plain
text -- no style span around the initial, so no span for the engine to carry the
initial across untranslated -- and a translated paragraph is written back as one
run at that style, so the towering glyph is gone because the paragraph is one run
again. Each character keeps the style it was drawn with, so a paragraph that ends
up untranslated renders as its source did.

One character has to be decided about. The paragraph finder fills the gap between
the initial's drawing position and the first word's with a space of its own, and
that space is what splits ``Long`` into ``L`` and ``ong``. It is recognisable
because no content stream drew it: every character the frontend reads off a page
carries an xobject id and a synthesised one does not. Under the declared
separator policy such a space is dropped when the runs are merged and a space the
source itself drew is kept, and every join is recorded with the text before and
after it, because a source that draws no space after a one letter word leaves the
two cases indistinguishable at this layer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import pymupdf

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.chain_signals import group_lines
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.line_split import SPLITTABLE
from babeldoc.magazine.line_split import character_box
from babeldoc.magazine.line_split import character_union
from babeldoc.magazine.line_split import composition_characters
from babeldoc.magazine.line_split import composition_kind
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.run_trace import parse_source_ref
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("drop_cap.json")

REPORT_NAME = "drop_cap.report.json"

# What the pass acting on a verdict leaves behind. Separate from the marking
# report because the two run at different points of the same hook and each has to
# be readable on its own.
APPLY_REPORT_NAME = "drop_cap_apply.report.json"

# Where the body label vocabulary is declared, once for the whole project.
BODY_LABELS_KEY = "body_labels"

# The switches, by the names the caller sets on the translation config.
MARK_SWITCH = "magazine_drop_cap_mark"
APPLY_SWITCH = "magazine_drop_cap_apply"
GROUP_SWITCH = "magazine_article_group"

# Keys of the declarative surface. The structural ones are read by hand: the
# bounded configuration reader takes numbers and vocabularies, and a policy word
# and a table of defaults are neither.
SEPARATOR_KEY = "separator_policy"
SEPARATOR_VOCABULARY_KEY = "separator_policy_vocabulary"
DEFAULTS_KEY = "default_decision_by_target"
TARGET_POLICY_KEY = "target_initial_policy"
ENTRIES_KEY = "entries"
DESCRIPTION_KEY = "description"
_STRUCTURAL_KEYS = (SEPARATOR_KEY, DEFAULTS_KEY, TARGET_POLICY_KEY)

# The separator policy that closes the break the paragraph finder opened.
SEPARATOR_DROP_SYNTHESIZED = "drop_synthesized"

# The verdict this pass acts on, and where the verdicts are declared. A verdict
# is named in one file for the whole project, and that file belongs to the review
# layer, so it is read through the module that owns it.
DECISION_FLATTEN = "flatten"
HITL_DECISIONS_KEY = "drop_cap_decisions"

# Where the verdict a paragraph was acted on under came from.
SOURCE_RULED = "ruled"
SOURCE_DEFAULT = "default"

# Composition kinds the initial may be merged into: the ones the line split
# already declares regroupable, read from there rather than spelled again, so the
# package keeps one place that names a composition member. A formula is not among
# them, so an initial standing before one is left alone rather than folded into a
# unit the engine is required to carry across whole.
_MERGEABLE = SPLITTABLE

# How a decisions file names one paragraph: its one-based file page and its
# position among that page's paragraphs. Neither half is generated per run, so a
# reference a human writes after the first pass still names the same paragraph on
# the second, which a debug id -- minted afresh on every run -- would not.
REFERENCE_FORMAT = "p{page}#{index}"


class DropCapError(ConfigError):
    """Raised when the drop cap configuration or its dependencies are wrong."""


@dataclass(frozen=True)
class DropCapConfig:
    """Everything declared about finding one candidate and acting on a verdict."""

    min_first_run_size_ratio: float
    max_first_run_chars: int
    max_body_rank_in_article: int
    excerpt_chars: int
    initial_size_tolerance: float
    color_tolerance: float
    intent_config_version: int
    decision_version: int
    separator_policy: str
    decision_sources: tuple[str, ...]
    apply_fields: tuple[str, ...]
    defaults: Mapping[str, str]
    target_policies: Mapping[str, str]

    def default_for(self, target_lang: str) -> str | None:
        """The verdict an unruled candidate takes under one target language.

        Matched by longest declared prefix, because a target language reaches
        this project as a tag and a tag carries a region. None where no entry
        claims the language, which leaves every unruled candidate as it was: a
        default stated for the wrong language would change a rendering nobody
        asked a question about.
        """
        tag = (target_lang or "").strip().lower()
        claimed = [key for key in self.defaults if tag.startswith(key.lower())]
        if not claimed:
            return None
        return self.defaults[max(claimed, key=len)]

    def target_policy_for(self, target_lang: str) -> str | None:
        """Return the eligible-initial policy selected by a target language tag."""
        tag = (target_lang or "").strip().lower()
        claimed = [key for key in self.target_policies if tag.startswith(key.lower())]
        if not claimed:
            return None
        return self.target_policies[max(claimed, key=len)]


def decision_vocabulary() -> tuple[str, ...]:
    """The verdicts a ruling may carry, read from the file that declares them.

    Imported inside the call because the review layer imports this module. The
    vocabulary is declared once, in the review layer's configuration, and read
    through the module that owns that file rather than copied into a second one.
    """
    from babeldoc.magazine.hitl import load_hitl_config

    return tuple(load_hitl_config()[HITL_DECISIONS_KEY])


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DropCapError(message)


def _read_defaults(raw: object, source: str, verdicts: tuple[str, ...]):
    """The table of per target language defaults, checked against the verdicts."""
    _require(isinstance(raw, dict), f"{source}: {DEFAULTS_KEY} must be an object")
    entries = raw.get(ENTRIES_KEY)
    _require(
        isinstance(entries, dict) and bool(entries),
        f"{source}: {DEFAULTS_KEY}.{ENTRIES_KEY} must be a non-empty object",
    )
    for key, value in entries.items():
        _require(
            isinstance(key, str) and bool(key.strip()),
            f"{source}: {DEFAULTS_KEY}.{ENTRIES_KEY} has a key that is not a "
            f"language tag: {key!r}",
        )
        _require(
            value in verdicts,
            f"{source}: {DEFAULTS_KEY}.{ENTRIES_KEY}[{key!r}]={value!r} is "
            f"outside the declared verdicts {sorted(verdicts)}",
        )
    return MappingProxyType({key.strip(): value for key, value in entries.items()})


def _read_target_policies(raw: object, source: str):
    _require(isinstance(raw, dict), f"{source}: {TARGET_POLICY_KEY} must be an object")
    entries = raw.get(ENTRIES_KEY)
    vocabulary = raw.get("vocabulary")
    _require(
        isinstance(vocabulary, list) and bool(vocabulary),
        f"{source}: {TARGET_POLICY_KEY}.vocabulary must be a non-empty list",
    )
    _require(
        isinstance(entries, dict) and bool(entries),
        f"{source}: {TARGET_POLICY_KEY}.{ENTRIES_KEY} must be a non-empty object",
    )
    for key, value in entries.items():
        _require(
            isinstance(key, str) and bool(key.strip()) and value in vocabulary,
            f"{source}: {TARGET_POLICY_KEY}.{ENTRIES_KEY}[{key!r}]={value!r} "
            f"is not a declared target policy",
        )
    required = {
        drop_cap_intent.POLICY_ALPHABETIC,
        drop_cap_intent.POLICY_CJK_IDEOGRAPH,
        drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL,
        drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL,
    }
    _require(
        required.issubset(vocabulary),
        f"{source}: {TARGET_POLICY_KEY}.vocabulary omits {sorted(required - set(vocabulary))}",
    )
    return MappingProxyType({key.strip(): value for key, value in entries.items()})


def parse_drop_cap_config(raw: dict, source: str) -> DropCapConfig:
    """Validate one configuration mapping into the policy it declares."""
    flat = {key: value for key, value in raw.items() if key not in _STRUCTURAL_KEYS}
    try:
        parameters = dict(validate_bounded_config(flat, CONFIG_PATH))
    except ConfigError as exc:
        raise DropCapError(str(exc)) from exc

    verdicts = decision_vocabulary()
    _require(
        DECISION_FLATTEN in verdicts,
        f"{source}: the verdict vocabulary omits {DECISION_FLATTEN!r}, which is "
        f"the verdict this pass acts on",
    )
    vocabulary = tuple(parameters.get(SEPARATOR_VOCABULARY_KEY, ()))
    _require(bool(vocabulary), f"{source}: missing {SEPARATOR_VOCABULARY_KEY}")
    separator = raw.get(SEPARATOR_KEY)
    _require(
        separator in vocabulary,
        f"{source}: {SEPARATOR_KEY}={separator!r} is outside {sorted(vocabulary)}",
    )
    _require(
        SEPARATOR_DROP_SYNTHESIZED in vocabulary,
        f"{source}: {SEPARATOR_VOCABULARY_KEY} omits "
        f"{SEPARATOR_DROP_SYNTHESIZED!r}, which is the policy that closes the "
        f"break the paragraph finder opened",
    )
    sources = tuple(parameters.get("decision_sources", ()))
    for name in (SOURCE_RULED, SOURCE_DEFAULT):
        _require(
            name in sources,
            f"{source}: decision_sources omits {name!r}, which a record may name",
        )
    fields = tuple(parameters.get("apply_fields", ()))
    _require(bool(fields), f"{source}: missing apply_fields")

    numbers = (
        "min_first_run_size_ratio",
        "max_first_run_chars",
        "max_body_rank_in_article",
        "excerpt_chars",
        "initial_size_tolerance",
        "color_tolerance",
        "intent_config_version",
        "decision_version",
    )
    missing = sorted(set(numbers) - set(parameters))
    _require(not missing, f"{source}: missing parameters {missing}")
    return DropCapConfig(
        min_first_run_size_ratio=float(parameters["min_first_run_size_ratio"]),
        max_first_run_chars=int(parameters["max_first_run_chars"]),
        max_body_rank_in_article=int(parameters["max_body_rank_in_article"]),
        excerpt_chars=int(parameters["excerpt_chars"]),
        initial_size_tolerance=float(parameters["initial_size_tolerance"]),
        color_tolerance=float(parameters["color_tolerance"]),
        intent_config_version=int(parameters["intent_config_version"]),
        decision_version=int(parameters["decision_version"]),
        separator_policy=str(separator),
        decision_sources=sources,
        apply_fields=fields,
        defaults=_read_defaults(raw.get(DEFAULTS_KEY), source, verdicts),
        target_policies=_read_target_policies(raw.get(TARGET_POLICY_KEY), source),
    )


@lru_cache(maxsize=1)
def load_drop_cap_config(path: str | None = None) -> DropCapConfig:
    """Load and validate ``configs/drop_cap.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise DropCapError(f"{config_path.name}: root must be an object")
    return parse_drop_cap_config(raw, config_path.name)


def body_labels() -> tuple[str, ...]:
    """Layout labels that count as running text, in declaration order."""
    return tuple(load_chain_config()[BODY_LABELS_KEY])


def mark_enabled(translation_config) -> bool:
    return bool(getattr(translation_config, MARK_SWITCH, False))


def require_dependencies(translation_config) -> None:
    """Refuse a run that asks for marking without the stage marking needs."""
    if not mark_enabled(translation_config):
        return
    if not getattr(translation_config, GROUP_SWITCH, False):
        raise DropCapError(
            f"{MARK_SWITCH} requires {GROUP_SWITCH}: a candidate is decided "
            f"against the article it belongs to, and without the grouping stage "
            f"there is no article map to decide it against"
        )


def paragraph_reference(page_label: int, index: int) -> str:
    """How one paragraph is named in the review draft and in a decisions file."""
    return REFERENCE_FORMAT.format(page=page_label, index=index)


def document_references(labeled_pages) -> set[str]:
    """Every reference the paragraphs of one document answer to."""
    return {
        paragraph_reference(label, index)
        for label, page in labeled_pages
        for index in range(len(page.pdf_paragraph))
    }


@dataclass(frozen=True)
class LeadingRun:
    """The run of characters one paragraph opens with, at one size."""

    size: float
    text: str
    span: int


def character_size(character) -> float | None:
    style = getattr(character, "pdf_style", None)
    size = getattr(style, "font_size", None)
    return float(size) if size else None


def leading_run(paragraph, tolerance: float) -> LeadingRun | None:
    """The paragraph's opening run of characters set at one size, or None.

    Read off the characters in the order they are stored, so the composition
    holding them does not matter: an initial grouped into a formula with the
    letters after it is the same initial as one standing in a style run of its
    own. The run ends where a character's size leaves the first character's by
    more than the tolerance the styling stage merges two styles under.
    """
    characters = paragraph_characters(paragraph)
    if not characters:
        return None
    size = character_size(characters[0])
    if size is None:
        return None
    span = 1
    for character in characters[1:]:
        other = character_size(character)
        if other is None or abs(other - size) > tolerance:
            break
        span += 1
    text = "".join(character.char_unicode or "" for character in characters[:span])
    return LeadingRun(size=size, text=text, span=span)


def median_font_size(paragraph) -> float | None:
    """The median size over every character of the paragraph."""
    sizes: list[float] = []
    for composition in paragraph.pdf_paragraph_composition or []:
        for holder in (
            composition.pdf_same_style_characters,
            composition.pdf_line,
            composition.pdf_formula,
        ):
            if holder is None:
                continue
            sizes.extend(
                character.pdf_style.font_size
                for character in holder.pdf_character
                if character.pdf_style is not None and character.pdf_style.font_size
            )
    return statistics.median(sizes) if sizes else None


@dataclass(frozen=True)
class Candidate:
    """One paragraph that opens with what looks like a drop cap."""

    reference: str
    page: int
    index: int
    debug_id: str | None
    article_id: str | None
    body_rank: int
    opens_article: bool
    size_ratio: float
    first_run: str
    excerpt: str
    source_text_sha256: str
    source_box: tuple[float, float, float, float]
    visual_initial_reference: str
    visual_initial_debug_id: str | None
    visual_initial_text_sha256: str
    visual_initial_box: tuple[float, float, float, float]
    binding_proof: Mapping[str, object]

    def as_record(self) -> dict:
        return {
            "paragraph": self.reference,
            "page": self.page,
            "debug_id": self.debug_id,
            "article_id": self.article_id,
            "body_rank": self.body_rank,
            "opens_article": self.opens_article,
            "size_ratio": round(self.size_ratio, 4),
            "first_run": self.first_run,
            "excerpt": self.excerpt,
            "source_text_sha256": self.source_text_sha256,
            "source_box": list(self.source_box),
            "visual_initial_ref": self.visual_initial_reference,
            "visual_initial_debug_id": self.visual_initial_debug_id,
            "visual_initial_text_sha256": self.visual_initial_text_sha256,
            "visual_initial_box": list(self.visual_initial_box),
            "binding_proof": dict(self.binding_proof),
        }


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strict_box(value) -> tuple[float, float, float, float] | None:
    if value is None or any(
        getattr(value, name, None) is None for name in ("x", "y", "x2", "y2")
    ):
        return None
    box = tuple(float(getattr(value, name)) for name in ("x", "y", "x2", "y2"))
    return box if box[0] < box[2] and box[1] < box[3] else None


def _visible_characters(paragraph) -> list:
    return [
        character
        for character in paragraph_characters(paragraph)
        if (character.char_unicode or "").strip() and _strict_box(character.box)
    ]


def _letter(text: str) -> bool:
    return len(text) == 1 and unicodedata.category(text).startswith("L")


def _same_paragraph_candidate(
    *,
    reference: str,
    page: int,
    index: int,
    paragraph,
    article_id: str,
    rank: int,
    opens: bool,
    run: LeadingRun,
    median: float,
    config: DropCapConfig,
) -> Candidate | None:
    source_box = _strict_box(paragraph.box)
    source_character = next(iter(_visible_characters(paragraph)), None)
    initial_box = (
        None if source_character is None else _strict_box(source_character.box)
    )
    if source_box is None or source_character is None or initial_box is None:
        return None
    initial = run.text.strip()
    ratio = run.size / median
    return Candidate(
        reference=reference,
        page=page,
        index=index,
        debug_id=paragraph.debug_id,
        article_id=article_id,
        body_rank=rank,
        opens_article=opens,
        size_ratio=ratio,
        first_run=initial,
        excerpt=(paragraph.unicode or "").strip()[: config.excerpt_chars],
        source_text_sha256=_text_sha256(paragraph.unicode or ""),
        source_box=source_box,
        visual_initial_reference=reference,
        visual_initial_debug_id=paragraph.debug_id,
        visual_initial_text_sha256=_text_sha256(initial),
        visual_initial_box=initial_box,
        binding_proof=MappingProxyType(
            {
                "kind": "same_paragraph_composition",
                "owner_ref": reference,
                "visual_initial_ref": reference,
                "source_character_count": 1,
                "size_ratio": round(ratio, 6),
                "minimum_size_ratio": config.min_first_run_size_ratio,
                "unique_owner_count": 1,
                "unique_visual_count": 1,
            }
        ),
    )


def read_article_map(path: Path) -> tuple[dict[int, str], set[int]]:
    """Which article each page belongs to, and the pages articles open on."""
    with path.open(encoding="utf-8") as f:
        report = json.load(f)
    article_of_page: dict[int, str] = {}
    openers: set[int] = set()
    for article in report.get("articles", ()):
        openers.add(int(article["start_page"]))
        for page in article.get("pages", ()):
            article_of_page[int(page)] = article.get("article_id")
    return article_of_page, openers


def find_candidates(
    page_coordinates,
    article_of_page: dict[int, str],
    openers: set[int],
    config: DropCapConfig,
    labels: tuple[str, ...],
) -> list[Candidate]:
    """Every candidate of one document, in page then paragraph order."""
    found: list[Candidate] = []
    rank_of_article: dict[str, int] = {}
    for physical_label, canonical_page, page in page_coordinates:
        article_id = article_of_page.get(canonical_page)
        for index, paragraph in enumerate(page.pdf_paragraph):
            text = (paragraph.unicode or "").strip()
            if paragraph.layout_label not in labels or not text:
                continue
            if article_id is None:
                # A paragraph outside every article is measured against no
                # article, so the position signal cannot be satisfied at all.
                continue
            rank = rank_of_article.get(article_id, 0) + 1
            rank_of_article[article_id] = rank
            opens = canonical_page in openers
            if rank > config.max_body_rank_in_article and not opens:
                continue
            run = leading_run(paragraph, config.initial_size_tolerance)
            median = median_font_size(paragraph)
            if run is None or not median:
                continue
            initial = run.text.strip()
            # An initial is a character. An opening run holding only the space
            # after one is not the initial itself, whatever it is set at.
            if not initial or len(initial) > config.max_first_run_chars:
                continue
            ratio = run.size / median
            if ratio < config.min_first_run_size_ratio:
                continue
            candidate = _same_paragraph_candidate(
                reference=paragraph_reference(physical_label, index),
                page=physical_label,
                index=index,
                paragraph=paragraph,
                article_id=article_id,
                rank=rank,
                opens=opens,
                run=run,
                median=median,
                config=config,
            )
            if candidate is not None:
                found.append(candidate)
    return found


def _band_gap(left, right) -> float:
    return max(0.0, max(left[0], right[0]) - min(left[1], right[1]))


def _standalone_geometry(companion, owner, config: DropCapConfig) -> dict | None:
    companion_compositions = list(companion.pdf_paragraph_composition or ())
    if not companion_compositions or any(
        composition_kind(composition) not in _MERGEABLE
        for composition in companion_compositions
    ):
        return None
    companion_characters = _visible_characters(companion)
    owner_characters = _visible_characters(owner)
    if len(companion_characters) != 1 or len(owner_characters) < 2:
        return None
    source_char = companion_characters[0].char_unicode or ""
    if not _letter(source_char) or (companion.unicode or "").strip() != source_char:
        return None
    initial_size = character_size(companion_characters[0])
    body_size = median_font_size(owner)
    initial_box = _strict_box(companion_characters[0].box)
    companion_box = _strict_box(companion.box)
    owner_box = _strict_box(owner.box)
    if (
        not initial_size
        or not body_size
        or initial_box is None
        or companion_box is None
        or owner_box is None
    ):
        return None
    ratio = initial_size / body_size
    if ratio < config.min_first_run_size_ratio:
        return None
    lines = group_lines(
        owner_characters,
        float(load_chain_config()["line_overlap_min"]),
    )
    if not lines:
        return None
    first_line_box = character_union(lines[0])
    first_box = _strict_box(first_line_box)
    if first_box is None:
        return None
    logical_start_delta = abs(initial_box[0] - owner_box[0])
    first_line_gap = abs(first_box[0] - initial_box[2])
    vertical_gap = _band_gap(
        (initial_box[1], initial_box[3]),
        (first_box[1], first_box[3]),
    )
    # The paragraph's own body em is the only geometric tolerance: the initial
    # starts on the body edge, meets its first line, and is no farther than one
    # body glyph from that line vertically.  No publication-specific distance
    # or page coordinate enters the proof.
    if (
        initial_box[0] > first_box[0]
        or logical_start_delta > body_size
        or first_line_gap > body_size
        or vertical_gap > body_size
    ):
        return None
    return {
        "source_char": source_char,
        "source_character": companion_characters[0],
        "size_ratio": ratio,
        "body_size": body_size,
        "visual_font_id": getattr(companion_characters[0].pdf_style, "font_id", None),
        "body_font_id": getattr(owner_characters[0].pdf_style, "font_id", None),
        "visual_font_size": initial_size,
        "initial_box": initial_box,
        "companion_box": companion_box,
        "owner_box": owner_box,
        "first_line_box": first_box,
        "logical_start_delta": logical_start_delta,
        "first_line_gap": first_line_gap,
        "vertical_gap": vertical_gap,
    }


def find_standalone_candidates(
    page_coordinates,
    article_document_ir: ArticleDocumentIR,
    config: DropCapConfig,
    labels: tuple[str, ...],
) -> list[Candidate]:
    """Bind an independently painted initial to exactly one body owner."""
    pages_by_local = {
        canonical_page: (physical_label, page)
        for physical_label, canonical_page, page in page_coordinates
    }
    possibilities = []
    for article in article_document_ir.articles:
        ordered = sorted(
            article.elements,
            key=lambda item: (item.reading_order, item.page, item.column, item.source_ref),
        )
        for visual in ordered:
            visual_page, visual_index = parse_source_ref(visual.source_ref)
            held = pages_by_local.get(visual_page)
            if held is None or visual.role not in labels:
                continue
            physical_label, page = held
            if visual_index >= len(page.pdf_paragraph):
                continue
            companion = page.pdf_paragraph[visual_index]
            if companion.layout_label not in labels:
                continue
            for owner in ordered:
                owner_page, owner_index = parse_source_ref(owner.source_ref)
                if (
                    owner.role not in labels
                    or owner_page != visual_page
                    or owner.column != visual.column
                    or visual.reading_order >= owner.reading_order
                    or owner_index >= len(page.pdf_paragraph)
                ):
                    continue
                # Once this pair is geometrically admissible, the standalone
                # initial is not an independent body paragraph and therefore
                # must not consume the owner's semantic opening rank.
                rank = sum(
                    1
                    for item in ordered
                    if item.role in labels
                    and item.source_ref != visual.source_ref
                    and item.reading_order <= owner.reading_order
                )
                opens = owner_page == article.pages[0]
                if rank > config.max_body_rank_in_article and not opens:
                    continue
                paragraph = page.pdf_paragraph[owner_index]
                if paragraph.layout_label not in labels:
                    continue
                geometry = _standalone_geometry(companion, paragraph, config)
                if geometry is None:
                    continue
                possibilities.append(
                    (
                        article.article_id,
                        physical_label,
                        owner_index,
                        visual_index,
                        owner,
                        visual,
                        paragraph,
                        companion,
                        rank,
                        opens,
                        geometry,
                    )
                )

    owner_counts = Counter((item[1], item[2]) for item in possibilities)
    visual_counts = Counter((item[1], item[3]) for item in possibilities)
    found = []
    for (
        article_id,
        physical_label,
        owner_index,
        visual_index,
        owner,
        visual,
        paragraph,
        companion,
        rank,
        opens,
        geometry,
    ) in possibilities:
        if owner_counts[(physical_label, owner_index)] != 1 or visual_counts[
            (physical_label, visual_index)
        ] != 1:
            continue
        owner_ref = paragraph_reference(physical_label, owner_index)
        visual_ref = paragraph_reference(physical_label, visual_index)
        source_char = geometry["source_char"]
        proof = MappingProxyType(
            {
                "kind": "standalone_visual_initial",
                "owner_ref": owner_ref,
                "visual_initial_ref": visual_ref,
                "article_id": article_id,
                "owner_reading_order": owner.reading_order,
                "visual_reading_order": visual.reading_order,
                "column": owner.column,
                "body_rank": rank,
                "opens_article": opens,
                "source_character_count": 1,
                "size_ratio": round(geometry["size_ratio"], 6),
                "minimum_size_ratio": config.min_first_run_size_ratio,
                "body_size": round(geometry["body_size"], 6),
                "visual_font_id": geometry["visual_font_id"],
                "body_font_id": geometry["body_font_id"],
                "visual_font_size": round(geometry["visual_font_size"], 6),
                "visual_initial_glyph_box": list(geometry["initial_box"]),
                "owner_first_line_box": list(geometry["first_line_box"]),
                "logical_start_delta": round(geometry["logical_start_delta"], 6),
                "first_line_gap": round(geometry["first_line_gap"], 6),
                "vertical_gap": round(geometry["vertical_gap"], 6),
                "unique_owner_count": 1,
                "unique_visual_count": 1,
            }
        )
        found.append(
            Candidate(
                reference=owner_ref,
                page=physical_label,
                index=owner_index,
                debug_id=paragraph.debug_id,
                article_id=article_id,
                body_rank=rank,
                opens_article=opens,
                size_ratio=geometry["size_ratio"],
                first_run=source_char,
                excerpt=(source_char + (paragraph.unicode or ""))[: config.excerpt_chars],
                source_text_sha256=_text_sha256(paragraph.unicode or ""),
                source_box=geometry["owner_box"],
                visual_initial_reference=visual_ref,
                visual_initial_debug_id=companion.debug_id,
                visual_initial_text_sha256=_text_sha256(companion.unicode or ""),
                # Stable matching is paragraph-to-paragraph. The glyph ink box
                # remains separate in binding_proof because it can legitimately
                # extend beyond the paragraph's frozen semantic source box.
                visual_initial_box=geometry["companion_box"],
                binding_proof=proof,
            )
        )
    return found


# What an ICCBased stream's /N component count means as a device space -- the
# only family resolved past its name, because it is the only one whose
# components normalize the way the capture's device branches already do.
_ICC_COMPONENT_SPACES = {1: "DeviceGray", 3: "DeviceRGB", 4: "DeviceCMYK"}

_DEVICE_SPACE_NAMES = frozenset(_ICC_COMPONENT_SPACES.values())

_ICC_BASED_RE = re.compile(r"/ICCBased\s+(\d+)\s+\d+\s+R")
_DIRECT_DEVICE_RE = re.compile(r"^\s*/(DeviceGray|DeviceRGB|DeviceCMYK)\s*$")
_INDIRECT_REFERENCE_RE = re.compile(r"^\s*(\d+)\s+\d+\s+R\s*$")


class _ColorSpaceResolver:
    """Resolve named fill/stroke color spaces against the source PDF.

    The intermediate language carries a character's content-stream operators
    but not the resource dictionaries they name into, so ``/CS0 cs`` cannot be
    read past the name from the instruction alone. The name is resolved in the
    character's own drawing context -- the form xobject it came from where it
    came from one, the page otherwise -- and only into the three device spaces
    the color capture normalizes: a direct device name stands for itself and an
    ICCBased stream maps by its /N component count. Every other family
    (Separation, DeviceN, Pattern, Indexed, ...) resolves to None on purpose,
    and the capture keeps its recorded unsupported fallback, so nothing this
    class fails at can change a color the capture reads today.
    """

    def __init__(self, translation_config):
        self._input_file = getattr(translation_config, "input_file", None)
        self._document = None
        self._open_failed = False
        self._cache: dict[tuple[int, int | None, str], str | None] = {}

    def close(self) -> None:
        if self._document is not None:
            self._document.close()
            self._document = None

    def _open(self):
        if self._open_failed or self._document is not None:
            return self._document
        try:
            self._document = pymupdf.open(str(self._input_file))
        except (RuntimeError, ValueError, TypeError, OSError):
            logger.warning(
                "drop cap color spaces stay unresolved: cannot open %s",
                self._input_file,
            )
            self._open_failed = True
        return self._document

    def for_character(self, physical_page: int, il_page, character):
        """The resolver closure for one character's drawing context."""
        form_xref = None
        xobj_id = getattr(character, "xobj_id", None)
        if xobj_id is not None:
            form_xref = next(
                (
                    getattr(xobject, "xref_id", None)
                    for xobject in il_page.pdf_xobject or ()
                    if getattr(xobject, "xobj_id", None) == xobj_id
                ),
                None,
            )

        def resolve(name: str) -> str | None:
            key = (physical_page, form_xref, name)
            if key not in self._cache:
                self._cache[key] = self._resolve(physical_page, form_xref, name)
            return self._cache[key]

        return resolve

    def _resolve(
        self, physical_page: int, form_xref: int | None, name: str
    ) -> str | None:
        document = self._open()
        if document is None:
            return None
        owners: list[int] = []
        if form_xref:
            owners.append(int(form_xref))
        try:
            if 1 <= physical_page <= document.page_count:
                owners.append(document[physical_page - 1].xref)
            for owner in owners:
                space = self._resolve_in(document, owner, name)
                if space is not None:
                    return space
        except (RuntimeError, ValueError, TypeError, IndexError):
            logger.warning(
                "color space /%s stays unresolved on page %d",
                name,
                physical_page,
            )
        return None

    @staticmethod
    def _resolve_in(document, owner_xref: int, name: str) -> str | None:
        kind, value = document.xref_get_key(
            owner_xref, f"Resources/ColorSpace/{name}"
        )
        if kind == "xref":
            reference = _INDIRECT_REFERENCE_RE.match(value or "")
            if reference is None:
                return None
            value = document.xref_object(int(reference.group(1)), compressed=True)
        elif kind not in ("name", "array"):
            return None
        direct = _DIRECT_DEVICE_RE.match(value or "")
        if direct is not None:
            return direct.group(1)
        icc = _ICC_BASED_RE.search(value or "")
        if icc is None:
            return None
        count_kind, count = document.xref_get_key(int(icc.group(1)), "N")
        if count_kind != "int":
            return None
        return _ICC_COMPONENT_SPACES.get(int(count))


def mark(
    translation_config,
    labeled_pages,
    article_document_ir: ArticleDocumentIR | None = None,
) -> list[Candidate]:
    """Find the candidates of one document and say so in the document.

    Each candidate's frozen color resolves named color spaces against the
    source document's own resources, so an initial painted through ``scn``
    freezes the color it was set in rather than the capture's black default.

    Returns them in page order, empty where the switch is down. Only a candidate
    is written: a paragraph that is not one carries no attribute at all, so a run
    with the switch down and a run that found nothing leave the same document.
    """
    require_dependencies(translation_config)
    if not mark_enabled(translation_config):
        drop_cap_intent.clear(translation_config)
        return []
    if article_document_ir is None:
        raise DropCapError("drop cap marking requires the canonical ArticleDocumentIR")
    config = load_drop_cap_config()
    article_of_page = dict(article_document_ir.by_page)
    openers = {article.pages[0] for article in article_document_ir.articles}
    pages = dict(labeled_pages)
    page_coordinates = [
        (physical_label, position + 1, page)
        for position, (physical_label, page) in enumerate(labeled_pages)
    ]
    candidates = find_candidates(
        page_coordinates, article_of_page, openers, config, body_labels()
    )
    candidates.extend(
        find_standalone_candidates(
            page_coordinates,
            article_document_ir,
            config,
            body_labels(),
        )
    )
    candidate_counts = Counter(candidate.reference for candidate in candidates)
    candidates = sorted(
        (
            candidate
            for candidate in candidates
            if candidate_counts[candidate.reference] == 1
        ),
        key=lambda candidate: (candidate.page, candidate.index),
    )
    policy = config.target_policy_for(getattr(translation_config, "lang_out", ""))
    if candidates and policy is None:
        raise DropCapError(
            "drop cap candidates have no target initial policy for "
            f"{getattr(translation_config, 'lang_out', '')!r}"
        )
    intents: list[drop_cap_intent.DropCapIntent] = []
    resolver = _ColorSpaceResolver(translation_config)
    try:
        for candidate in candidates:
            paragraph = pages[candidate.page].pdf_paragraph[candidate.index]
            visual_page, visual_index = parse_source_ref(
                candidate.visual_initial_reference
            )
            visual_page_position = next(
                (
                    index
                    for index, (physical_label, _page) in enumerate(labeled_pages)
                    if physical_label == visual_page
                ),
                None,
            )
            if visual_page_position is None:
                raise DropCapError(
                    f"{candidate.reference}: visual initial page is not selected"
                )
            visual_paragraph = labeled_pages[visual_page_position][1].pdf_paragraph[
                visual_index
            ]
            source_character = next(
                (
                    character
                    for character in paragraph_characters(visual_paragraph)
                    if (character.char_unicode or "").strip()
                ),
                None,
            )
            if source_character is None:
                raise DropCapError(
                    f"{candidate.reference} has no source initial character"
                )
            intent = drop_cap_intent.build_intent(
                source_ref=candidate.reference,
                article_id=candidate.article_id,
                paragraph=paragraph,
                source_character=source_character,
                target_policy=str(policy),
                config_version=config.intent_config_version,
                decision_version=config.decision_version,
                visual_initial_ref=candidate.visual_initial_reference,
                binding_proof=dict(candidate.binding_proof),
                resolve_color_space=resolver.for_character(
                    visual_page,
                    labeled_pages[visual_page_position][1],
                    source_character,
                ),
                source_anchor=drop_cap_intent.freeze_source_anchor(
                    labeled_pages[visual_page_position][1],
                    source_character,
                ),
            )
            intents.append(intent)
    finally:
        resolver.close()
    for candidate in candidates:
        pages[candidate.page].pdf_paragraph[candidate.index].drop_cap_candidate = True
    drop_cap_intent.replace_intents(translation_config, intents)
    drop_cap_intent.write_report(translation_config)
    _write_report(translation_config, config, candidates)
    logger.debug("drop cap: %d candidate(s)", len(candidates))
    return candidates


def _write_report(
    translation_config, config: DropCapConfig, candidates: list[Candidate]
) -> Path:
    report = {
        "counts": {
            "candidates": len(candidates),
            "articles": len({c.article_id for c in candidates}),
            "pages": len({c.page for c in candidates}),
        },
        "parameters": {
            "min_first_run_size_ratio": config.min_first_run_size_ratio,
            "max_first_run_chars": config.max_first_run_chars,
            "max_body_rank_in_article": config.max_body_rank_in_article,
            "excerpt_chars": config.excerpt_chars,
        },
        "body_labels": list(body_labels()),
        "reference_format": REFERENCE_FORMAT,
        "candidates": [candidate.as_record() for candidate in candidates],
        # What reads the verdict a human returns, so a run whose ruling appears
        # to have changed nothing is explained by its own inventory rather than
        # by reading the code.
        "decision_consumers": [
            {
                "pass": "drop_cap.apply",
                "switch": APPLY_SWITCH,
                "report": APPLY_REPORT_NAME,
            }
        ],
    }
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def review_rows(candidates: list[Candidate], translation_config=None) -> list[dict]:
    """The candidates as the review draft states them, one row each."""
    intents = (
        {} if translation_config is None else drop_cap_intent.intents_for(translation_config)
    )
    rows = []
    for candidate in candidates:
        row = {
            "paragraph": candidate.reference,
            "page": candidate.page,
            "article_id": candidate.article_id,
            "size_ratio": round(candidate.size_ratio, 3),
            "first_run": candidate.first_run,
            "excerpt": candidate.excerpt,
        }
        intent = intents.get(candidate.reference)
        if intent is not None:
            row.update(intent.manual_template("keep"))
            row["decision"] = None
        rows.append(row)
    return rows


def parse_manual_decision(
    reference: str, raw: object, verdicts: tuple[str, ...]
) -> drop_cap_intent.ManualDecision:
    fields = {
        "decision",
        "candidate_id",
        "source_ref",
        "source_text_fingerprint",
        "source_style_hash",
        "config_version",
        "decision_version",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise DropCapError(
            f"drop_caps[{reference!r}] must carry exactly {sorted(fields)}"
        )
    if raw["decision"] not in verdicts:
        raise DropCapError(
            f"drop_caps[{reference!r}].decision={raw['decision']!r} is outside "
            f"{sorted(verdicts)}"
        )
    if raw["source_ref"] != reference:
        raise DropCapError(
            f"drop_caps[{reference!r}].source_ref must equal its mapping key"
        )
    for name in (
        "candidate_id",
        "source_ref",
        "source_text_fingerprint",
        "source_style_hash",
    ):
        if not isinstance(raw[name], str) or not raw[name]:
            raise DropCapError(f"drop_caps[{reference!r}].{name} must be non-empty")
    if not isinstance(raw["config_version"], int) or not isinstance(
        raw["decision_version"], int
    ):
        raise DropCapError(
            f"drop_caps[{reference!r}] versions must be decimal integers"
        )
    return drop_cap_intent.ManualDecision(**raw)


def validate_manual_decisions(
    translation_config, verdicts: Mapping[str, object]
) -> dict[str, drop_cap_intent.ManualDecision]:
    intents = drop_cap_intent.intents_for(translation_config)
    faults: list[str] = []
    parsed = {}
    vocabulary = decision_vocabulary()
    for reference, raw in verdicts.items():
        intent = intents.get(reference)
        if isinstance(raw, str):
            if raw not in vocabulary:
                faults.append(
                    f"{reference}: decision {raw!r} is outside {sorted(vocabulary)}"
                )
                continue
            if intent is None:
                faults.append(f"{reference}: not a current drop-cap candidate")
                continue
            raw = intent.manual_template(raw)
        try:
            decision = (
                raw
                if isinstance(raw, drop_cap_intent.ManualDecision)
                else parse_manual_decision(reference, raw, vocabulary)
            )
        except DropCapError as exc:
            faults.append(str(exc))
            continue
        parsed[reference] = decision
        if intent is None:
            faults.append(f"{reference}: not a current drop-cap candidate")
        elif not drop_cap_intent.decision_matches(intent, decision):
            faults.append(f"{reference}: candidate or source/config fingerprint is stale")
    if faults:
        raise DropCapError("drop-cap decisions rejected: " + "; ".join(faults))
    return parsed


def _restore_dataclass(target, snapshot) -> None:
    for name in target.__dataclass_fields__:
        setattr(target, name, copy.deepcopy(getattr(snapshot, name)))


class _AtomicParagraphUpdate:
    """Restore all touched paragraphs and intents unless explicitly committed."""

    def __init__(self, paragraphs, intents=()):
        self._paragraphs = [
            (paragraph, copy.deepcopy(paragraph)) for paragraph in paragraphs
        ]
        self._intents = [(intent, copy.deepcopy(intent)) for intent in intents]
        self._committed = False

    def __enter__(self):
        return self

    def commit(self) -> None:
        self._committed = True

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is not None or not self._committed:
            for paragraph, snapshot in self._paragraphs:
                _restore_dataclass(paragraph, snapshot)
            for intent, snapshot in self._intents:
                _restore_dataclass(intent, snapshot)
        return False


def apply_decisions(
    translation_config,
    labeled_pages,
    verdicts: Mapping[str, drop_cap_intent.ManualDecision],
) -> list[dict]:
    """Write the ruled verdicts into the document, one paragraph at a time.

    Every ruling must name and fingerprint one current candidate. Validation is
    completed before this function writes the first IL attribute.
    """
    records: list[dict] = []
    if not verdicts:
        return records
    intents = drop_cap_intent.intents_for(translation_config)
    invalid = [
        reference
        for reference, manual in verdicts.items()
        if reference not in intents
        or not drop_cap_intent.decision_matches(intents[reference], manual)
    ]
    if invalid:
        raise DropCapError(
            f"stale or noncandidate decisions cannot change IL: {sorted(invalid)}"
        )
    targets = []
    for label, page in labeled_pages:
        for index, paragraph in enumerate(page.pdf_paragraph):
            reference = paragraph_reference(label, index)
            manual = verdicts.get(reference)
            if manual is None:
                continue
            intent = drop_cap_intent.intent_for(translation_config, reference)
            if intent is None or not drop_cap_intent.decision_matches(intent, manual):
                raise DropCapError(f"{reference}: stale or noncandidate decision")
            targets.append((label, index, paragraph, intent, manual))
    if len(targets) != len(verdicts):
        raise DropCapError("a validated drop-cap decision has no selected paragraph")
    with _AtomicParagraphUpdate(
        [target[2] for target in targets],
        [target[3] for target in targets],
    ) as transaction:
        for label, index, paragraph, intent, manual in targets:
            records.append(
                {
                    "paragraph": paragraph_reference(label, index),
                    "page": label,
                    "debug_id": paragraph.debug_id,
                    "was_candidate": bool(paragraph.drop_cap_candidate),
                    "decision": manual.decision,
                }
            )
            paragraph.drop_cap_decision = manual.decision
            intent.decision = manual.decision
        transaction.commit()
    return records


# --- acting on the ruling ------------------------------------------------------


def apply_enabled(translation_config) -> bool:
    return bool(getattr(translation_config, APPLY_SWITCH, False))


def require_apply_dependencies(translation_config) -> None:
    """Refuse a run that asks for a verdict to be acted on without the finding."""
    if not apply_enabled(translation_config):
        return
    if not mark_enabled(translation_config):
        raise DropCapError(
            f"{APPLY_SWITCH} requires {MARK_SWITCH}: the verdict an unruled "
            f"candidate is acted on under is decided from the candidate mark, so "
            f"a run acting on defaults without the marking pass would act on none"
        )


def synthesized(character) -> bool:
    """Whether one character was inserted by the pipeline rather than drawn.

    Every character the frontend reads off a content stream carries an xobject
    id -- zero for the page itself -- and the space the paragraph finder fills a
    drawing gap with is built without one.
    """
    return getattr(character, "xobj_id", None) is None


def closed_text(text: str, initial: str) -> str | None:
    """The paragraph text with the break after its initial closed, or None.

    None where the break cannot be located: a text that does not open with the
    initial, or one carrying no space after it, is left exactly as it is rather
    than repaired by a rule written for a shape it does not have.
    """
    if not initial or not text.startswith(initial):
        return None
    rest = text[len(initial) :]
    closed = rest.lstrip()
    if closed == rest:
        return None
    return initial + closed


def merged_style(paragraph, compositions):
    """The style the merged run declares.

    The paragraph's own, which is what a paragraph with no drop cap declares and
    what makes the run indistinguishable from ordinary text to the reader that
    decides whether a style span is needed. Where the paragraph carries none, the
    style of the run being merged into stands in, so the merged run is never left
    declaring nothing.
    """
    if paragraph.pdf_style is not None:
        return paragraph.pdf_style
    run = compositions[1].pdf_same_style_characters
    return run.pdf_style if run is not None else None


def _start_edge(characters) -> str | None:
    """The vertical box edge a paragraph of these characters starts from.

    Read off the characters rather than assumed: the first of them sits on the
    side the reading runs from, so comparing it with the last says which edge
    that is without this module deciding which way the coordinates grow. None
    where they do not say -- a text of one line has no second line to start away
    from -- and nothing is moved then, because a rule that guessed the side
    would as readily move the edge the paragraph ends at.
    """
    boxes = [
        box
        for box in (character_box(item) for item in characters)
        if box is not None and None not in (box.y, box.y2)
    ]
    if not boxes:
        return None
    first, last = boxes[0], boxes[-1]
    if first.y > last.y and first.y2 > last.y2:
        return "y2"
    if first.y < last.y and first.y2 < last.y2:
        return "y"
    return None


def merged_box(head, tail):
    """The box the merged run and the paragraph holding it declare.

    Across the line the box covers the initial and the text it opens both, which
    is the width the merged run is drawn on. Along the reading it covers the text
    alone on the side the paragraph starts from: an enlarged initial stands proud
    of the first line it sits beside, so a box whose start edge is the initial's
    hands the stage a paragraph that begins that far off the line its neighbours
    on the page begin on. The initial's characters stay in the run and are set at
    the text's size once translated, so nothing of it is lost by not measuring
    the box from it.
    """
    whole = character_union([*head, *tail])
    text = character_union(tail)
    if whole is None or text is None:
        return whole
    box = il_version_1.Box(x=whole.x, y=whole.y, x2=whole.x2, y2=whole.y2)
    edge = _start_edge(tail)
    if edge is not None:
        setattr(box, edge, getattr(text, edge))
    return box


def box_quad(box) -> list[float] | None:
    """One box as four numbers, for a record a human reads beside a page."""
    if box is None or None in (box.x, box.y, box.x2, box.y2):
        return None
    return [float(box.x), float(box.y), float(box.x2), float(box.y2)]


def _unchanged(paragraph, config: DropCapConfig) -> dict:
    """What a paragraph nothing was merged in reports."""
    text = (paragraph.unicode or "")[: config.excerpt_chars]
    return {
        "merged": False,
        "characters_merged": 0,
        "separator_dropped": 0,
        "unicode_before": text,
        "unicode_after": text,
        "box_before": box_quad(paragraph.box),
        "box_after": box_quad(paragraph.box),
    }


def flatten(paragraph, config: DropCapConfig) -> dict:
    """Merge the paragraph's enlarged initial into the text it opens.

    Reports what it did, and reports doing nothing where there was nothing to
    do: a paragraph whose opening already stands in one composition is one the
    translator already sees whole, and a paragraph whose opening run reaches past
    the first composition is not standing at the boundary this would close.
    """
    outcome = _unchanged(paragraph, config)
    compositions = list(paragraph.pdf_paragraph_composition or ())
    if len(compositions) < 2:
        return outcome
    head_kind = composition_kind(compositions[0])
    tail_kind = composition_kind(compositions[1])
    if head_kind is None or tail_kind not in _MERGEABLE:
        return outcome
    head = composition_characters(compositions[0], head_kind)
    tail = composition_characters(compositions[1], tail_kind)
    if not head or not tail:
        return outcome
    run = leading_run(paragraph, config.initial_size_tolerance)
    if run is None or run.span > len(head):
        return outcome

    dropped = 0
    if config.separator_policy == SEPARATOR_DROP_SYNTHESIZED:
        while len(head) - dropped > 1:
            character = head[-1 - dropped]
            if not (character.char_unicode or "").isspace():
                break
            if not synthesized(character):
                break
            dropped += 1
    before = paragraph.unicode or ""
    after = before
    if dropped:
        closed = closed_text(before, run.text.strip())
        if closed is None:
            # The break is not locatable in the recorded text, so the characters
            # stay whole: a paragraph whose text and characters say different
            # things is not something this pass leaves behind.
            dropped = 0
        else:
            after = closed
    kept = head[: len(head) - dropped] if dropped else head
    merged = [*kept, *tail]
    box = merged_box(kept, tail)
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                box=box,
                pdf_style=merged_style(paragraph, compositions),
                pdf_character=merged,
            )
        ),
        *compositions[2:],
    ]
    paragraph.unicode = after
    edge = _start_edge(tail)
    if box is not None and paragraph.box is not None and edge is not None:
        setattr(paragraph.box, edge, getattr(box, edge))
    outcome.update(
        {
            "merged": True,
            "characters_merged": len(merged),
            "separator_dropped": dropped,
            "unicode_after": after[: config.excerpt_chars],
            "box_after": box_quad(paragraph.box),
        }
    )
    return outcome


def flatten_standalone(
    paragraph,
    companion,
    intent: drop_cap_intent.DropCapIntent,
    config: DropCapConfig,
) -> dict:
    """Move one proven standalone source initial into its semantic owner.

    The owner remains the sole translation paragraph and keeps its immutable
    source container.  The independently painted source glyph is removed only
    after the exact character has been prepended to the owner's first regroupable
    run; any stale or unsupported shape raises so the surrounding document
    transaction restores both paragraphs.
    """
    owner_text = paragraph.unicode or ""
    visual_text = companion.unicode or ""
    visual_characters = _visible_characters(companion)
    if (
        len(visual_characters) != 1
        or visual_text.strip() != intent.source_char
        or (visual_characters[0].char_unicode or "") != intent.source_char
        or not _letter(intent.source_char)
    ):
        raise DropCapError(f"{intent.source_ref}: standalone visual initial is stale")
    if owner_text.startswith(intent.source_char):
        raise DropCapError(f"{intent.source_ref}: standalone visual initial is duplicated")
    compositions = list(paragraph.pdf_paragraph_composition or ())
    if not compositions:
        raise DropCapError(f"{intent.source_ref}: standalone owner has no composition")
    tail_kind = composition_kind(compositions[0])
    if tail_kind not in _MERGEABLE:
        raise DropCapError(
            f"{intent.source_ref}: standalone owner does not open in regroupable text"
        )
    tail = composition_characters(compositions[0], tail_kind)
    if not tail:
        raise DropCapError(f"{intent.source_ref}: standalone owner has no leading text")
    combined = [visual_characters[0], *tail]
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                box=copy.deepcopy(paragraph.box),
                pdf_style=paragraph.pdf_style,
                pdf_character=combined,
            )
        ),
        *compositions[1:],
    ]
    paragraph.unicode = intent.source_char + owner_text
    companion.pdf_paragraph_composition = []
    companion.unicode = ""
    return {
        "merged": True,
        "characters_merged": len(combined),
        "separator_dropped": 0,
        "unicode_before": (intent.source_char + owner_text)[: config.excerpt_chars],
        "unicode_after": (paragraph.unicode or "")[: config.excerpt_chars],
        "box_before": box_quad(paragraph.box),
        "box_after": box_quad(paragraph.box),
    }


def resolve_decision(paragraph, default: str | None) -> tuple[str | None, str | None]:
    """The verdict one paragraph is acted on under, and where it came from.

    A ruling outranks the default, and the default reaches a marked candidate
    only: the machine answer is an answer to a finding, so a paragraph the
    marking pass did not find is left alone whatever the default says.
    """
    if paragraph.drop_cap_decision:
        return paragraph.drop_cap_decision, SOURCE_RULED
    if paragraph.drop_cap_candidate and default is not None:
        return default, SOURCE_DEFAULT
    return None, None


def apply(translation_config, labeled_pages) -> dict | None:
    """Act on every verdict of one document. None where the switch is down.

    Returns the record it wrote, so a caller holding the document can assert
    about the pass without reading the sidecar back.
    """
    require_apply_dependencies(translation_config)
    if not apply_enabled(translation_config):
        return None
    config = load_drop_cap_config()
    verdicts = decision_vocabulary()
    target = getattr(translation_config, "lang_out", "") or ""
    default = config.default_for(target)

    targets = []
    pages_by_label = dict(labeled_pages)
    for label, page in labeled_pages:
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            decision, source = resolve_decision(paragraph, default)
            if decision is None:
                continue
            reference = paragraph_reference(label, index)
            intent = drop_cap_intent.intent_for(translation_config, reference)
            if intent is None:
                raise DropCapError(f"{reference}: active decision has no frozen intent")
            if decision not in verdicts:
                raise DropCapError(
                    f"{paragraph_reference(label, index)} carries verdict "
                    f"{decision!r}, which is outside {sorted(verdicts)}"
                )
            run = leading_run(paragraph, config.initial_size_tolerance)
            median = median_font_size(paragraph)
            visual_ref = intent.visual_initial_ref or reference
            visual_page, visual_index = parse_source_ref(visual_ref)
            visual_holder = pages_by_label.get(visual_page)
            if visual_holder is None or visual_index >= len(
                visual_holder.pdf_paragraph
            ):
                raise DropCapError(
                    f"{reference}: frozen visual initial has no selected paragraph"
                )
            companion = visual_holder.pdf_paragraph[visual_index]
            targets.append(
                (
                    label,
                    index,
                    paragraph,
                    companion,
                    decision,
                    source,
                    intent,
                    run,
                    median,
                )
            )

    records: list[dict] = []
    touched = []
    for target_item in targets:
        for paragraph in (target_item[2], target_item[3]):
            if all(paragraph is not held for held in touched):
                touched.append(paragraph)
    with _AtomicParagraphUpdate(
        touched,
        [target_item[6] for target_item in targets],
    ) as transaction:
        for (
            label,
            index,
            paragraph,
            companion,
            decision,
            source,
            intent,
            run,
            median,
        ) in targets:
            # Under either verdict. What the engine is offered is independent
            # of whether the later render keeps or flattens the visual initial.
            if companion is paragraph:
                outcome = flatten(paragraph, config)
            else:
                outcome = flatten_standalone(
                    paragraph,
                    companion,
                    intent,
                    config,
                )
            intent.flatten_status = drop_cap_intent.FLATTEN_APPLIED
            intent.decision = decision
            if decision == DECISION_FLATTEN:
                intent.render_status = drop_cap_intent.RENDER_SKIPPED
            records.append(
                {
                    "paragraph": paragraph_reference(label, index),
                    "page": label,
                    "debug_id": paragraph.debug_id,
                    "decision": decision,
                    "source": source,
                    "was_candidate": bool(paragraph.drop_cap_candidate),
                    "initial": intent.source_char,
                    "size_ratio": (
                        round(float(intent.binding_proof.get("size_ratio")), 4)
                        if intent.binding_proof.get("size_ratio") is not None
                        else (
                            None
                            if run is None or not median
                            else round(run.size / median, 4)
                        )
                    ),
                    "flatten_status": intent.flatten_status,
                    "issue": None,
                    **outcome,
                }
            )

        expected = set(config.apply_fields)
        for item in records:
            if set(item) != expected:
                raise DropCapError(
                    f"{APPLY_REPORT_NAME}: a record carries {sorted(item)}, and "
                    f"{CONFIG_PATH.name} declares {sorted(expected)}"
                )
            if item["source"] not in config.decision_sources:
                raise DropCapError(
                    f"{APPLY_REPORT_NAME}: a record names source "
                    f"{item['source']!r}, and {CONFIG_PATH.name} declares "
                    f"{sorted(config.decision_sources)}"
                )

        record = as_apply_record(config, verdicts, target, default, records)
        _write_apply_report(translation_config, record)
        drop_cap_intent.write_report(translation_config)
        transaction.commit()

    logger.debug(
        "drop cap apply: %d verdict(s), %d merged",
        record["totals"]["decided"],
        record["totals"]["merged"],
    )
    return record


def as_apply_record(
    config: DropCapConfig,
    verdicts: tuple[str, ...],
    target_lang: str,
    default: str | None,
    records: list[dict],
) -> dict:
    return {
        "switch": APPLY_SWITCH,
        "target_lang": target_lang,
        "default_decision": default,
        "separator_policy": config.separator_policy,
        "verdicts": list(verdicts),
        "decision_sources": list(config.decision_sources),
        "totals": {
            "decided": len(records),
            "merged": sum(1 for item in records if item["merged"]),
            "separators_dropped": sum(item["separator_dropped"] for item in records),
            "by_source": {
                name: sum(1 for item in records if item["source"] == name)
                for name in config.decision_sources
            },
            "by_decision": {
                name: sum(1 for item in records if item["decision"] == name)
                for name in verdicts
            },
        },
        "decisions": records,
    }


def _write_apply_report(translation_config, record: dict) -> Path:
    path = Path(translation_config.get_working_file_path(APPLY_REPORT_NAME))
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path
