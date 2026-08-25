"""Same form parentheticals, folded out of a translated document.

A translation engine asked to carry a proper name across a language boundary
answers, often enough to be a defect of its own, by writing the name and then
glossing it with itself: ``Khakimov (Khakimov)``. The gloss is not a translation
decision a reader benefits from and it is not one the wording of a request
reaches -- two rounds of prompt work over the same corpus left it in place -- so
it is closed here instead, mechanically, on a rule narrow enough to state in one
sentence: a parenthetical whose content is exactly how the text immediately
before it ends is removed, brackets and all.

What the rule deliberately does not reach is the parenthetical that carries a
different string: a name transliterated into the target script and then glossed
with its source spelling is the shape the standing style instruction asks for on
first mention, and a rule that folded it would be deleting the only place the
source spelling appears. So agreement is
literal, after NFKC and outer whitespace only. Case is not folded either, which
keeps an initialism standing beside the words it abbreviates.

Where this sits
---------------

Between the translation being written back and the typesetting stage laying it
out, which is the one window where the text is final and the geometry it will be
set at is not: a paragraph shortened here is laid out at its shortened length
rather than laid out twice. Both halves of a paragraph's text are rewritten --
the compositions, which is what the stage sets, and ``unicode``, which is what a
reader and a detector consult -- and each is folded by the same rule read over
itself rather than by mapping offsets from one to the other, because the two are
not always the same string at this point in the pipeline.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine import hitl
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.line_split import SPLITTABLE
from babeldoc.magazine.line_split import character_union
from babeldoc.magazine.line_split import composition_characters
from babeldoc.magazine.line_split import composition_kind
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "paren_dedup.json"

REPORT_NAME = "paren_dedup.report.json"

# The switch, by the name the caller sets on the translation config. Up unless
# something puts it down: folding a repetition out of a translation is not a
# judgement call a run has to opt into, and the rule refuses everything it is
# not certain about rather than asking to be turned off.
SWITCH = "magazine_paren_dedup"

OPENERS_KEY = "bracket_openers"
CLOSERS_KEY = "bracket_closers"


class ParenDedupError(ConfigError):
    """Raised when the parenthetical folding configuration is malformed."""


@dataclass(frozen=True)
class ParenConfig:
    """Everything bounded about folding one parenthetical."""

    openers: tuple[str, ...]
    closers: tuple[str, ...]
    max_span_chars: int
    excerpt_chars: int


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ParenDedupError(message)


def parse_paren_config(raw: dict, source: str) -> ParenConfig:
    """Validate one configuration mapping into the policy it declares."""
    try:
        parameters = dict(validate_bounded_config(raw, CONFIG_PATH))
    except ConfigError as exc:
        raise ParenDedupError(str(exc)) from exc
    for key in (OPENERS_KEY, CLOSERS_KEY):
        _require(key in parameters, f"{source}: missing {key}")
        for form in parameters[key]:
            _require(
                len(form) == 1,
                f"{source}: {key} names {form!r}, which is not one character",
            )
    shared = set(parameters[OPENERS_KEY]) & set(parameters[CLOSERS_KEY])
    _require(
        not shared,
        f"{source}: {sorted(shared)} is declared as both an opener and a closer, "
        f"which leaves no bracket the scan can tell apart",
    )
    for key in ("max_span_chars", "excerpt_chars"):
        _require(key in parameters, f"{source}: missing {key}")
    return ParenConfig(
        openers=tuple(parameters[OPENERS_KEY]),
        closers=tuple(parameters[CLOSERS_KEY]),
        max_span_chars=int(parameters["max_span_chars"]),
        excerpt_chars=int(parameters["excerpt_chars"]),
    )


@lru_cache(maxsize=1)
def load_paren_config(path: str | None = None) -> ParenConfig:
    """Load and validate ``configs/paren_dedup.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ParenDedupError(f"{config_path.name}: root must be an object")
    return parse_paren_config(raw, config_path.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, True))


# --- the rule -----------------------------------------------------------------


def normalize(text: str) -> str:
    """One string as the rule compares it: NFKC, outer whitespace off.

    Case is left alone on purpose: an initialism standing beside the words it
    abbreviates is a parenthetical that says something, and folding case is what
    would read it as one that does not.
    """
    return unicodedata.normalize("NFKC", text).strip()


def _closing(text: str, opener: int, config: ParenConfig) -> int | None:
    """Where the parenthetical opened at ``opener`` closes, or None.

    None where it does not close, and None where another opener stands inside
    it: a nested parenthetical is not a shape this rule reads, and reading it as
    one would take the wrong span out.
    """
    for index in range(opener + 1, len(text)):
        char = text[index]
        if char in config.closers:
            return index
        if char in config.openers:
            return None
    return None


def same_form_spans(text: str, config: ParenConfig) -> list[tuple[int, int, str]]:
    """Every span of ``text`` this rule removes, left to right, disjoint.

    A span runs from the whitespace standing before the opening bracket -- which
    goes with the parenthetical, so folding one out of a line does not leave the
    line double spaced -- through the closing bracket. The third member is the
    content that agreed, which is what the record quotes.
    """
    spans: list[tuple[int, int, str]] = []
    index = 0
    while index < len(text):
        if text[index] not in config.openers:
            index += 1
            continue
        close = _closing(text, index, config)
        if close is None:
            index += 1
            continue
        inner = text[index + 1 : close]
        start = index
        while start > 0 and text[start - 1].isspace():
            start -= 1
        if _agrees(text[:start], inner, config):
            spans.append((start, close + 1, inner))
        index = close + 1
    return spans


def reverse_annotation(text: str, config: ParenConfig, is_residue) -> tuple[str, list[str]]:
    """Fold a name away and keep the original it is annotated with.

    The mirror of the rule above, and the same shape read the other way. That
    one folds out a parenthetical saying what the text before it already said;
    this one folds out the text *before* a parenthetical, where that text is
    written in the script the target document should not be holding and the
    parenthetical is not. A transliterated name followed by that same name in
    brackets, in a document finished into English, is a name the page already
    carries in the language it is being finished into, with a transliteration
    of it standing in front -- so the annotation is the answer
    and the run before it is the residue.

    Deterministic and free: no model is asked, because there is nothing to ask.
    What comes out is characters the page already had.

    Applies only where the parenthetical holds none of the residue script, so a
    parenthetical that is itself residue is left alone rather than promoted.
    """
    folded: list[str] = []
    out = text
    position = 0
    while position < len(out):
        character = out[position]
        if character not in config.openers:
            position += 1
            continue
        close = _closing(out, position, config)
        if close is None:
            position += 1
            continue
        inner = out[position + 1 : close]
        if not inner.strip() or any(is_residue(item) for item in inner):
            position = close + 1
            continue
        start = position
        while start > 0 and (
            is_residue(out[start - 1]) or out[start - 1] in _ANNOTATION_JOINERS
        ):
            start -= 1
        if start == position or not any(is_residue(item) for item in out[start:position]):
            position = close + 1
            continue
        folded.append(out[start:position])
        out = out[:start] + inner + out[close + 1 :]
        position = start + len(inner)
    return out, folded


# The marks that may stand inside a name written in the residue script without
# ending it. A middle dot separates the parts of a transliterated name, and a
# name broken by one is still one name.
_ANNOTATION_JOINERS = "\u00b7\u2027\u30fb\uff65"


def _agrees(before: str, inner: str, config: ParenConfig) -> bool:
    """Whether a parenthetical's content is how the text before it ends."""
    content = normalize(inner)
    if not content or len(content) > config.max_span_chars:
        return False
    return normalize(before).endswith(content)


def fold_text(text: str, config: ParenConfig) -> tuple[str, list[str]]:
    """One string with its same form parentheticals out, and what came out."""
    spans = same_form_spans(text, config)
    if not spans:
        return text, []
    # Rebuilt in one pass rather than cut span by span, because every span is
    # an offset into the string as it was read.
    kept = []
    cursor = 0
    for start, end, _inner in spans:
        kept.append(text[cursor:start])
        cursor = end
    kept.append(text[cursor:])
    return "".join(kept), [inner for _s, _e, inner in spans]


# --- folding one paragraph ----------------------------------------------------


class _Segment:
    """One composition's text, and how much of it may be taken away.

    A segment carries either a unicode run's string or a character sequence's
    members, never both, and says whether the pass may shorten it. Everything a
    span crosses has to be shortenable for the span to be taken, so a
    parenthetical reaching into a formula is left where it is.
    """

    __slots__ = ("characters", "composition", "editable", "member", "text")

    def __init__(self, composition, member, text, characters, editable):
        self.composition = composition
        self.member = member
        self.text = text
        self.characters = characters
        self.editable = editable


def _segment(composition) -> _Segment | None:
    """What one composition contributes to its paragraph's text.

    The member kinds and how a character is read out of each are the line
    split's declaration, read through it rather than spelled again here, so the
    package keeps one place that names a composition member. Shortenable are
    the kinds that declaration already calls regroupable: a run of characters is
    a sequence members may be taken out of, while a lone character and a formula
    are units of their own.
    """
    if composition is None:
        return None
    unicode_run = composition.pdf_same_style_unicode_characters
    if unicode_run is not None:
        return _Segment(
            composition, unicode_run, unicode_run.unicode or "", None, True
        )
    kind = composition_kind(composition)
    if kind is None:
        return None
    characters = list(composition_characters(composition, kind))
    text = "".join(item.char_unicode or "" for item in characters)
    member = getattr(composition, kind)
    return _Segment(composition, member, text, characters, kind in SPLITTABLE)


def _cut(segment: _Segment, start: int, end: int) -> None:
    """Take ``[start, end)`` of one segment's text out of the segment."""
    if segment.characters is None:
        text = segment.member.unicode or ""
        segment.member.unicode = text[:start] + text[end:]
        segment.text = segment.member.unicode
        return
    kept = segment.characters[:start] + segment.characters[end:]
    segment.characters = kept
    segment.member.pdf_character = kept
    segment.member.box = character_union(kept)
    segment.text = "".join(item.char_unicode or "" for item in kept)


def _apply_spans(segments: list[_Segment], spans) -> list[str]:
    """Take every span the segments as a whole allow. What was taken.

    A span crossing a segment the pass may not shorten is left where it is
    rather than half taken, which is what keeps a parenthetical reaching into a
    formula whole.
    """
    bounds = []
    cursor = 0
    for segment in segments:
        bounds.append((cursor, cursor + len(segment.text)))
        cursor += len(segment.text)
    taken = []
    # Backwards, so a cut never moves the offsets of a span not yet taken. The
    # bounds are the ones the concatenation was read at and are not recomputed
    # for the same reason.
    for start, end, inner in reversed(spans):
        cuts = []
        blocked = False
        for segment, (begin, finish) in zip(segments, bounds, strict=True):
            low, high = max(start, begin), min(end, finish)
            if low >= high:
                continue
            if not segment.editable:
                blocked = True
                break
            cuts.append((segment, low - begin, high - begin))
        if blocked or not cuts:
            continue
        for segment, low, high in cuts:
            _cut(segment, low, high)
        taken.append(inner)
    taken.reverse()
    return taken


def fold_paragraph(paragraph, config: ParenConfig) -> dict | None:
    """Fold one paragraph's same form parentheticals. None where none were.

    The compositions and ``unicode`` are folded separately under one rule, and
    the record reports each count, because a paragraph whose two halves disagree
    at this point in the pipeline is one this pass has no offset map for and one
    a reader of the record should be able to see.
    """
    compositions = list(paragraph.pdf_paragraph_composition or ())
    segments = [
        segment
        for segment in (_segment(item) for item in compositions)
        if segment is not None
    ]
    composed = "".join(segment.text for segment in segments)
    spans = same_form_spans(composed, config)
    text_before = paragraph.unicode or ""
    folded, removed = fold_text(text_before, config)
    taken = _apply_spans(segments, spans) if spans else []
    if not taken and not removed:
        return None
    if taken:
        # Rebuilt from the compositions rather than from the segments, so a
        # member kind this pass does not read is carried through untouched
        # instead of dropped; what goes is the one a cut emptied.
        emptied = {id(segment.composition) for segment in segments if not segment.text}
        paragraph.pdf_paragraph_composition = [
            composition
            for composition in compositions
            if id(composition) not in emptied
        ]
    paragraph.unicode = folded
    return {
        "removed_compositions": len(taken),
        "removed_unicode": len(removed),
        "spans": taken,
        "before": text_before[: config.excerpt_chars],
        "after": folded[: config.excerpt_chars],
    }


def as_record(config: ParenConfig, records: list[dict], pages: int) -> dict:
    return {
        "switch": SWITCH,
        "openers": list(config.openers),
        "closers": list(config.closers),
        "max_span_chars": config.max_span_chars,
        "pages": pages,
        "totals": {
            "paragraphs_folded": len(records),
            "spans_removed": sum(item["removed_compositions"] for item in records),
            "unicode_spans_removed": sum(item["removed_unicode"] for item in records),
        },
        "paragraphs": records,
    }


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def apply(translation_config, docs) -> dict | None:
    """Fold every paragraph of one document. None where the switch is down.

    Returns the record it wrote, so a caller holding the document can assert
    about the pass without reading the sidecar back.
    """
    if not enabled(translation_config):
        return None
    config = load_paren_config()
    pages = hitl.labeled_pages(docs)
    records: list[dict] = []
    for label, page in pages:
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            outcome = fold_paragraph(paragraph, config)
            if outcome is None:
                continue
            records.append(
                {
                    "page": label,
                    "reference": paragraph_reference(label, index),
                    "debug_id": paragraph.debug_id,
                    **outcome,
                }
            )
    record = as_record(config, records, len(pages))
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    write_report(working_dir, record)
    logger.debug(
        "paren dedup: %d paragraph(s) folded, %d span(s) removed",
        record["totals"]["paragraphs_folded"],
        record["totals"]["spans_removed"],
    )
    return record
