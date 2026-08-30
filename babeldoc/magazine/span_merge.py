"""A word split across a style boundary, put back into one container.

Magazine typesetting hands the first letter of a word to a different style
than the rest of it -- a small-caps initial, a colored lead-in -- and the
paragraph reaches the translator as ``<style>V </style><style>o l u m e</style>``
or as a bare ``J`` beside a span holding ``uly``.  The model then translates
the two halves separately, and the page prints ``J七月``: half a word in each
language.  This pass finds the boundary that splits one word between two
adjacent containers and moves the short half into the long half's container
before translation, so the translator meets the word whole.

The rule is a shape rule, not a content rule.  A boundary qualifies when the
letters on its two sides belong to one word -- judged geometrically, because
letterspaced text carries real and synthesized spaces between letters that a
string test cannot tell from word gaps -- when the continuation side starts
lowercase, and when the short side carries at most ``span_merge_max_chars``
letters.  Either side may be the span and either side may be short; the short
run moves, keeping the paragraph's visible character sequence byte for byte.

One exclusion, deliberately shared with the drop cap lane: a short run whose
letters reach ``min_first_run_size_ratio`` (read from ``configs/drop_cap.json``,
the single source of that number) against the paragraph's own median size is
the shape of an oversized initial, and the initial belongs to the drop cap
machinery.  Merging it here would hand one letter to two passes.

What a merged letter gives up is its special style: the moved characters take
the target container's style, so the translated word renders in one voice.
A paragraph that is never translated (identity pasteback) renders with that
style change too -- a demo-grade trade recorded in UPSTREAM_DIFF.md.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine import hitl
from babeldoc.magazine.drop_cap import load_drop_cap_config
from babeldoc.magazine.drop_cap import median_font_size
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.line_split import character_union
from babeldoc.magazine.line_split import composition_kind
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("span_merge.json")

REPORT_NAME = "span_merge.report.json"

# The switch, by the name the caller sets on the translation config. Up unless
# something puts it down: handing the translator whole words is not a
# judgement call a run opts into.
SWITCH = "magazine_span_merge"

# Why a boundary that geometry reads as one word was still left split. A
# closed set, one name per unmet condition, so the sidecar answers "why is
# J七月 still here" precisely.  Boundaries that fail the geometry itself --
# every ordinary styled word -- are passed over without a record.
SKIP_SIZE_RATIO = "size_ratio_gate"
SKIP_NOT_CONTINUATION = "not_lowercase_continuation"
SKIP_SHORT_TOO_LONG = "short_side_over_max_chars"

# The container kinds a run may be moved between. A formula or a lone
# character composition is atomic and never a party to a merge.
_MERGEABLE = ("pdf_line", "pdf_same_style_characters")


class SpanMergeError(ConfigError):
    """Raised when the span merge configuration is malformed."""


@dataclass(frozen=True)
class SpanMergeConfig:
    """Everything bounded about rejoining one split word."""

    max_chars: int
    gap_tolerance: float
    abs_gap_em: float
    excerpt_chars: int


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SpanMergeError(message)


def parse_span_merge_config(raw: dict, source: str) -> SpanMergeConfig:
    flat = {key: value for key, value in raw.items() if key != "switch"}
    try:
        parameters = dict(validate_bounded_config(flat, CONFIG_PATH))
    except ConfigError as exc:
        raise SpanMergeError(str(exc)) from exc
    for key in (
        "span_merge_max_chars",
        "span_merge_gap_tolerance",
        "span_merge_abs_gap_em",
        "excerpt_chars",
    ):
        _require(key in parameters, f"{source}: missing {key}")
    return SpanMergeConfig(
        max_chars=int(parameters["span_merge_max_chars"]),
        gap_tolerance=float(parameters["span_merge_gap_tolerance"]),
        abs_gap_em=float(parameters["span_merge_abs_gap_em"]),
        excerpt_chars=int(parameters["excerpt_chars"]),
    )


@lru_cache(maxsize=1)
def load_span_merge_config(path: str | None = None) -> SpanMergeConfig:
    """Load and validate ``configs/span_merge.json``."""
    source = CONFIG_PATH if path is None else Path(path)
    with source.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise SpanMergeError(f"{source.name}: root must be an object")
    return parse_span_merge_config(raw, source.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, True))


# --- reading one boundary -----------------------------------------------------


def _is_letter(character) -> bool:
    text = character.char_unicode or ""
    return len(text) == 1 and text.isascii() and text.isalpha()


def _is_space(character) -> bool:
    text = character.char_unicode or ""
    return len(text) == 1 and text.isspace()


def _holder(composition):
    kind = composition_kind(composition)
    if kind not in _MERGEABLE:
        return None, None
    return getattr(composition, kind), kind


def _trailing_run(characters: list) -> tuple[int, list] | None:
    """The word tail at the end of one container: (slice start, letters).

    A run is a *pure* letter sequence: the sources in evidence letterspace a
    word with geometry alone and write a real space character only at a word
    break (CERN's footer IL: no space inside ``V olume``, spaces between
    every word).  So a space character standing between the container's end
    and its last letters is a word break, and the boundary reads as one --
    None here, no merge.  What letterspacing leaves is gaps, and gaps are the
    ``_same_word`` test's to judge.
    """
    if not characters:
        return None
    if _is_space(characters[-1]):
        return None
    index = len(characters) - 1
    while index >= 0 and _is_letter(characters[index]):
        index -= 1
    if index == len(characters) - 1:
        return None
    return index + 1, characters[index + 1 :]


def _leading_run(characters: list) -> tuple[int, list] | None:
    """The word head at the start of one container: (slice end, letters).

    The mirror of ``_trailing_run``: pure letters from the container's start,
    and a leading space character means the word broke at the boundary."""
    if not characters or _is_space(characters[0]):
        return None
    index = 0
    while index < len(characters) and _is_letter(characters[index]):
        index += 1
    if index == 0:
        return None
    return index, characters[:index]


def _gap(left, right) -> float | None:
    if left.box is None or right.box is None:
        return None
    if None in (left.box.x2, right.box.x) or None in (
        left.box.y,
        left.box.y2,
        right.box.y,
        right.box.y2,
    ):
        return None
    return right.box.x - left.box.x2


def _same_baseline(left, right) -> bool:
    """Whether two letters stand on one line, by vertical overlap."""
    overlap = min(left.box.y2, right.box.y2) - max(left.box.y, right.box.y)
    height = min(left.box.y2 - left.box.y, right.box.y2 - right.box.y)
    return height > 0 and overlap >= 0.5 * height


def _internal_gaps(letters: list) -> list[float]:
    gaps = []
    for prev, item in zip(letters, letters[1:], strict=False):
        gap = _gap(prev, item)
        if gap is not None:
            gaps.append(gap)
    return gaps


def _letter_size(character) -> float | None:
    style = getattr(character, "pdf_style", None)
    size = getattr(style, "font_size", None)
    return float(size) if size else None


def _same_word(left_letters, right_letters, config: SpanMergeConfig) -> bool:
    """Whether the boundary gap reads as a letter gap, not a word gap.

    Letterspaced text separates the letters of one word as far as it separates
    that word from digits and neighbours -- in characters.  What still tells
    them apart is geometry: the gap across the boundary is no wider than the
    gaps inside the runs.  Where neither run has an inside (two lone letters),
    only a gap small against the letter size -- far under a space width --
    counts as contiguous.
    """
    boundary = _gap(left_letters[-1], right_letters[0])
    if boundary is None:
        return False
    sizes = [
        size
        for size in (_letter_size(left_letters[-1]), _letter_size(right_letters[0]))
        if size
    ]
    floor = config.abs_gap_em * min(sizes) if sizes else 0.0
    internal = _internal_gaps(left_letters) + _internal_gaps(right_letters)
    allowed = max(config.gap_tolerance * max(internal), floor) if internal else floor
    return boundary <= allowed


# --- moving one run -----------------------------------------------------------


def _target_style(holder, kind: str, paragraph):
    if kind == "pdf_same_style_characters":
        return holder.pdf_style
    return paragraph.pdf_style


def _restyle(characters: list, style) -> None:
    if style is None:
        return
    for character in characters:
        character.pdf_style = style


def merge_boundary(paragraph, left_comp, right_comp, config, size_ratio_gate):
    """Try one boundary; the record of what happened, or None for no shape.

    ``size_ratio_gate`` is the drop cap threshold and the paragraph median
    curried together: it answers whether a run of letters is an oversized
    initial this pass must not touch.
    """
    left_holder, left_kind = _holder(left_comp)
    right_holder, right_kind = _holder(right_comp)
    if left_holder is None or right_holder is None:
        return None
    if left_kind != "pdf_same_style_characters" and (
        right_kind != "pdf_same_style_characters"
    ):
        # Two flow containers share the paragraph's style already; the only
        # boundary that splits a word's *style* has a span on at least one side.
        return None
    left_chars = left_holder.pdf_character or []
    right_chars = right_holder.pdf_character or []
    trailing = _trailing_run(left_chars)
    leading = _leading_run(right_chars)
    if trailing is None or leading is None:
        return None
    slice_start, left_letters = trailing
    slice_end, right_letters = leading

    # A boundary that fails the geometry is not a split word at all -- it is
    # every ordinary styled word in the document -- and is passed over
    # silently rather than logged as a refusal.  A refusal record is reserved
    # for a boundary that *is* one word and was still left split.
    if not _same_baseline(left_letters[-1], right_letters[0]):
        return None
    if not _same_word(left_letters, right_letters, config):
        return None

    def refused(reason: str) -> dict:
        return {"merged": False, "skip": reason, "word": None}

    if not (right_letters[0].char_unicode or "").islower():
        return refused(SKIP_NOT_CONTINUATION)
    short_is_left = len(left_letters) <= len(right_letters)
    short_letters = left_letters if short_is_left else right_letters
    if len(short_letters) > config.max_chars:
        return refused(SKIP_SHORT_TOO_LONG)
    if size_ratio_gate(short_letters):
        return refused(SKIP_SIZE_RATIO)

    word = "".join(
        item.char_unicode for item in (*left_letters, *right_letters)
    )
    if short_is_left:
        moved = left_chars[slice_start:]
        del left_chars[slice_start:]
        _restyle(moved, _target_style(right_holder, right_kind, paragraph))
        right_holder.pdf_character[:0] = moved
    else:
        moved = right_chars[:slice_end]
        del right_chars[:slice_end]
        _restyle(moved, _target_style(left_holder, left_kind, paragraph))
        left_holder.pdf_character.extend(moved)
    for holder in (left_holder, right_holder):
        if holder.pdf_character:
            holder.box = character_union(holder.pdf_character) or holder.box
    return {
        "merged": True,
        "skip": None,
        "word": word,
        "moved_letters": len(short_letters),
        "direction": "left_into_right" if short_is_left else "right_into_left",
        "target_kind": right_kind if short_is_left else left_kind,
    }


def _paragraph_text(paragraph) -> str:
    parts = []
    for composition in paragraph.pdf_paragraph_composition or ():
        kind = composition_kind(composition)
        if kind is None:
            continue
        if kind == "pdf_character":
            parts.append(composition.pdf_character.char_unicode or "")
        elif kind == "pdf_same_style_unicode_characters":
            parts.append(composition.pdf_same_style_unicode_characters.unicode or "")
        elif kind == "pdf_formula":
            parts.extend(
                item.char_unicode or ""
                for item in composition.pdf_formula.pdf_character or ()
            )
        else:
            holder = getattr(composition, kind)
            parts.extend(item.char_unicode or "" for item in holder.pdf_character or ())
    return "".join(parts)


def merge_paragraph(paragraph, config: SpanMergeConfig, ratio_threshold: float):
    """Rejoin every split word of one paragraph. (merge records, skip records)."""
    compositions = paragraph.pdf_paragraph_composition or []
    if len(compositions) < 2:
        return [], []
    median = median_font_size(paragraph)

    def size_ratio_gate(letters) -> bool:
        if not median:
            return False
        sizes = [size for size in (_letter_size(item) for item in letters) if size]
        return bool(sizes) and max(sizes) / median >= ratio_threshold

    before = _paragraph_text(paragraph)
    merges: list[dict] = []
    skips: list[dict] = []
    for index in range(len(compositions) - 1):
        outcome = merge_boundary(
            paragraph,
            compositions[index],
            compositions[index + 1],
            config,
            size_ratio_gate,
        )
        if outcome is None:
            continue
        record = {"boundary": index, **outcome}
        (merges if outcome["merged"] else skips).append(record)
    if merges:
        paragraph.pdf_paragraph_composition = [
            composition
            for composition in compositions
            if not _emptied(composition)
        ]
        after = _paragraph_text(paragraph)
        if after != before:
            raise SpanMergeError(
                "span merge changed the paragraph's visible characters: "
                f"{before[:80]!r} became {after[:80]!r}"
            )
    return merges, skips


def _emptied(composition) -> bool:
    holder, kind = _holder(composition)
    return holder is not None and not holder.pdf_character


# --- the pass -----------------------------------------------------------------


def as_record(config: SpanMergeConfig, ratio: float, records, skips, pages) -> dict:
    return {
        "switch": SWITCH,
        "span_merge_max_chars": config.max_chars,
        "span_merge_gap_tolerance": config.gap_tolerance,
        "span_merge_abs_gap_em": config.abs_gap_em,
        "min_first_run_size_ratio": ratio,
        "min_first_run_size_ratio_source": "drop_cap.json",
        "pages": pages,
        "totals": {
            "paragraphs_merged": len({item["reference"] for item in records}),
            "words_rejoined": len(records),
            "boundaries_refused": len(skips),
        },
        "merges": records,
        "refusals": skips,
    }


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def apply(translation_config, docs) -> dict | None:
    """Rejoin split words across one document. None where the switch is down.

    Returns the record it wrote, so a caller holding the document can assert
    about the pass without reading the sidecar back.
    """
    if not enabled(translation_config):
        return None
    config = load_span_merge_config()
    ratio = float(load_drop_cap_config().min_first_run_size_ratio)
    pages = hitl.labeled_pages(docs)
    records: list[dict] = []
    refusals: list[dict] = []
    for label, page in pages:
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            merges, skips = merge_paragraph(paragraph, config, ratio)
            reference = paragraph_reference(label, index)
            excerpt = (paragraph.unicode or "")[: config.excerpt_chars]
            for item in merges:
                records.append(
                    {
                        "page": label,
                        "reference": reference,
                        "debug_id": paragraph.debug_id,
                        "excerpt": excerpt,
                        **item,
                    }
                )
            for item in skips:
                refusals.append(
                    {
                        "page": label,
                        "reference": reference,
                        "debug_id": paragraph.debug_id,
                        **item,
                    }
                )
    record = as_record(config, ratio, records, refusals, len(pages))
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    write_report(working_dir, record)
    logger.debug(
        "span merge: %d word(s) rejoined, %d boundary(ies) refused",
        record["totals"]["words_rejoined"],
        record["totals"]["boundaries_refused"],
    )
    return record
