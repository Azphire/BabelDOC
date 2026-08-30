"""Measure the finished last line at every continuation boundary.

The chain simulation chooses its cuts on scaled measurements before formal
typesetting; nothing afterwards ever looked at what the cut became on the
finished page. This pass runs after typesetting, rendering, and repair, walks
every chain cut and every cross-column or cross-page pair of adjacent body
elements in an article's reading order -- chained or not -- and measures the
final last line of the paragraph handing over: ink characters, fill against
the paragraph's set width, and whether it stops on sentence-ending
punctuation. From B14 on, a claim about column tails cites this sidecar; the
simulation's own cut accounting is process information.

The pass moves nothing. It writes ``tail_fill.report.json`` and returns the
record.
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path

from babeldoc.magazine.chain_signals import group_lines
from babeldoc.magazine.chain_signals import line_text
from babeldoc.magazine.chain_signals import line_width
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.chain_signals import paragraph_characters
from babeldoc.magazine.chain_signals import paragraph_measure
from babeldoc.magazine.chain_signals import text_ends_terminal
from babeldoc.magazine.drop_cap import body_labels
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.run_trace import parse_source_ref
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("tail_fill.json")

REPORT_NAME = "tail_fill.report.json"
CHAIN_REPORT_NAME = "chain_translation.report.json"
SCHEMA_VERSION = "tail-fill.v1"
SWITCH = "magazine_tail_fill"

BOUNDARY_PAGE = "page"
BOUNDARY_COLUMN = "column"

# How many characters of a measured last line the report quotes. Enough to
# recognize the line in the page, small enough to keep the sidecar readable.
EXCERPT_CHARS = 24


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def load_tail_fill_config() -> dict:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    flat = {key: value for key, value in raw.items() if key != "switch"}
    return dict(validate_bounded_config(flat, CONFIG_PATH))


def _labeled_paragraphs(docs) -> dict[tuple[int, int], object]:
    by_ref: dict[tuple[int, int], object] = {}
    for position, page in enumerate(docs.page):
        label = int(
            page.page_number if page.page_number is not None else position
        ) + 1
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            by_ref[(label, index)] = paragraph
    return by_ref


def _chain_boundaries(translation_config) -> list[dict]:
    """Every cut before a non-final chain member, off the chain sidecar.

    The chain pass has already written its own report by the time this pass
    runs; reading it back keeps the two accounts of one cut in one place.
    A run without chains measures the unchained boundaries alone.
    """
    try:
        path = Path(translation_config.get_working_file_path(CHAIN_REPORT_NAME))
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    found = []
    for chain in raw.get("chains") or ():
        allocation = chain.get("allocation") or {}
        fragments = sorted(
            allocation.get("fragments") or (),
            key=lambda fragment: fragment.get("slot_order", 0),
        )
        kinds = chain.get("boundary_kinds") or ()
        for position in range(len(fragments) - 1):
            prev = fragments[position]
            nxt = fragments[position + 1]
            found.append(
                {
                    "prev_ref": prev.get("runtime_source_ref")
                    or prev.get("source_ref"),
                    "next_ref": nxt.get("runtime_source_ref")
                    or nxt.get("source_ref"),
                    "boundary": (
                        kinds[position] if position < len(kinds) else None
                    ),
                    "chain_id": chain.get("chain_id"),
                }
            )
    return found


def _article_boundaries(article_document_ir) -> list[dict]:
    """Every cross-column or cross-page pair of adjacent body elements.

    Read off the canonical article order, whether or not a chain covered the
    pair -- the uncovered ones are exactly the tails nobody redistributed.
    """
    if article_document_ir is None:
        return []
    body = set(body_labels())
    found = []
    for article in article_document_ir.articles:
        elements = sorted(article.elements, key=lambda item: item.reading_order)
        for prev, nxt in zip(elements, elements[1:], strict=False):
            if prev.role not in body or nxt.role not in body:
                continue
            if prev.page != nxt.page:
                boundary = BOUNDARY_PAGE
            elif prev.column != nxt.column:
                boundary = BOUNDARY_COLUMN
            else:
                continue
            found.append(
                {
                    "prev_ref": prev.source_ref,
                    "next_ref": nxt.source_ref,
                    "boundary": boundary,
                    "chain_id": None,
                }
            )
    return found


def measure_last_line(paragraph, chain_config) -> dict | None:
    """The finished last line of one paragraph, as the page will show it."""
    characters = [
        character
        for character in paragraph_characters(paragraph)
        if character.box is not None
    ]
    if not characters:
        return None
    lines = group_lines(characters, float(chain_config["line_overlap_min"]))
    if not lines:
        return None
    last = lines[-1]
    text = line_text(last).strip()
    ink_characters = sum(
        1 for character in last if (character.char_unicode or "").strip()
    )
    width = line_width(last)
    box = getattr(paragraph, "box", None)
    measure = None
    if box is not None and box.x is not None and box.x2 is not None:
        measure = abs(float(box.x2) - float(box.x))
    if not measure:
        measure = paragraph_measure(lines)
    fill_ratio = None if not measure else width / measure
    return {
        "chars": ink_characters,
        "ink_width_pt": round(width, 4),
        "measure_pt": None if measure is None else round(measure, 4),
        "fill_ratio": None if fill_ratio is None else round(fill_ratio, 4),
        "terminal_punct": text_ends_terminal(
            text,
            chain_config["terminal_punctuation"],
            chain_config["terminal_closers"],
        ),
        "lines": len(lines),
        "text": text[:EXCERPT_CHARS],
    }


def measure_boundaries(translation_config, docs, article_document_ir) -> list[dict]:
    """Every continuation boundary of the run, measured on the finished page."""
    chain_config = load_chain_config()
    by_ref = _labeled_paragraphs(docs)
    merged: dict[tuple[str, str], dict] = {}
    for source in (
        _chain_boundaries(translation_config),
        _article_boundaries(article_document_ir),
    ):
        for entry in source:
            key = (entry["prev_ref"], entry["next_ref"])
            known = merged.get(key)
            if known is None:
                merged[key] = dict(entry)
            elif known.get("chain_id") is None and entry.get("chain_id"):
                known["chain_id"] = entry["chain_id"]
                known["boundary"] = entry["boundary"] or known["boundary"]
    rows = []
    for (prev_ref, next_ref), entry in sorted(merged.items()):
        try:
            page_label, index = parse_source_ref(prev_ref)
        except (TypeError, ValueError):
            continue
        paragraph = by_ref.get((page_label, index))
        measured = (
            None
            if paragraph is None
            else measure_last_line(paragraph, chain_config)
        )
        rows.append(
            {
                "prev_ref": prev_ref,
                "next_ref": next_ref,
                "boundary": entry.get("boundary"),
                "chain_id": entry.get("chain_id"),
                "chained": entry.get("chain_id") is not None,
                "last_line": measured,
            }
        )
    return rows


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    cuts = statistics.quantiles(ordered, n=100, method="inclusive")
    return cuts[max(0, min(98, round(fraction * 100) - 1))]


def summarize(rows: list[dict], parameters: dict) -> dict:
    measured = [row for row in rows if row["last_line"] is not None]
    fills = [
        row["last_line"]["fill_ratio"]
        for row in measured
        if row["last_line"]["fill_ratio"] is not None
    ]
    full_min = float(parameters["full_line_fill_min"])
    short_max = int(parameters["short_tail_max_chars"])
    short_tails = [
        {
            "prev_ref": row["prev_ref"],
            "next_ref": row["next_ref"],
            "boundary": row["boundary"],
            "chained": row["chained"],
            "chars": row["last_line"]["chars"],
            "terminal_punct": row["last_line"]["terminal_punct"],
            "text": row["last_line"]["text"],
        }
        for row in measured
        if 0 < row["last_line"]["chars"] <= short_max
    ]
    return {
        "boundaries": len(rows),
        "measured": len(measured),
        "chained": sum(1 for row in rows if row["chained"]),
        "unchained": sum(1 for row in rows if not row["chained"]),
        "by_boundary": {
            kind: sum(1 for row in rows if row["boundary"] == kind)
            for kind in sorted({row["boundary"] for row in rows if row["boundary"]})
        },
        "fill_ratio": {
            "min": None if not fills else round(min(fills), 4),
            "p25": (
                None
                if not fills
                else round(_quantile(fills, 0.25), 4)
            ),
            "median": None if not fills else round(statistics.median(fills), 4),
        },
        "full_line_share": (
            None
            if not fills
            else round(
                sum(1 for value in fills if value >= full_min) / len(fills), 4
            )
        ),
        "full_line_fill_min": full_min,
        "short_tail_max_chars": short_max,
        "short_tails": short_tails,
    }


def _paragraph_characters_ordered(paragraph) -> list:
    return [
        character
        for character in paragraph_characters(paragraph)
        if character.box is not None
    ]


def _snapshot(paragraph) -> dict:
    return {
        "composition": list(paragraph.pdf_paragraph_composition),
        "unicode": paragraph.unicode,
        "characters": [
            (
                character,
                float(character.box.x),
                float(character.box.y),
                float(character.box.x2),
                float(character.box.y2),
                character.pdf_style,
                character.advance,
            )
            for character in _paragraph_characters_ordered(paragraph)
        ],
    }


def _restore(paragraph, snapshot: dict) -> None:
    paragraph.pdf_paragraph_composition = snapshot["composition"]
    paragraph.unicode = snapshot["unicode"]
    for character, x, y, x2, y2, style, advance in snapshot["characters"]:
        character.box.x = x
        character.box.y = y
        character.box.x2 = x2
        character.box.y2 = y2
        character.pdf_style = style
        character.advance = advance


def _fonts_for(typesetter, page) -> dict | None:
    fonts = {font.font_id: font for font in page.pdf_font or () if font.font_id}
    page_fonts = dict(fonts)
    mapped = getattr(typesetter.font_mapper, "fontid2font", None)
    if not isinstance(mapped, dict):
        return None
    fonts.update(mapped)
    for xobject in page.pdf_xobject or ():
        if xobject.xobj_id is None:
            continue
        fonts[xobject.xobj_id] = dict(page_fonts)
        for font in xobject.pdf_font or ():
            if font.font_id:
                fonts[xobject.xobj_id][font.font_id] = font
    return fonts


def _flat_composition(characters: list) -> list:
    # One same-style run holding the characters in reading order. The unit
    # builder walks a run character by character with each character's own
    # style, so the wrapper's style is a label, not a override -- and the
    # bare-character composition shape is avoided because the unit builder
    # reads a field off the paragraph that shape alone requires.
    from babeldoc.format.pdf.document_il import il_version_1

    if not characters:
        return []
    return [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                pdf_character=list(characters),
                pdf_style=characters[0].pdf_style,
            )
        )
    ]


def _verified_conservation(
    prev_text: str, next_text: str, new_prev: str, new_next: str
) -> bool:
    """The chain conservation law over the move, stated by the chain's checker."""
    from babeldoc.magazine import chain_backfill

    translated = prev_text + next_text
    merge = chain_backfill.ChainMerge(
        text=translated,
        members=(prev_text, next_text),
        separators=("", ""),
        spans=((0, len(prev_text)), (len(prev_text), len(translated))),
        dropped_hyphens=(),
    )
    result = chain_backfill.Redistribution(
        strategy="tail_rebalance",
        profile="tail_rebalance",
        segments=(
            chain_backfill.MemberSegment(
                index=0,
                text=new_prev,
                start=0,
                end=len(new_prev),
                sentence_start=chain_backfill.NO_SENTENCE_INDEX,
                sentence_end=chain_backfill.NO_SENTENCE_INDEX,
            ),
            chain_backfill.MemberSegment(
                index=1,
                text=new_next,
                start=len(new_prev),
                end=len(translated),
                sentence_start=chain_backfill.NO_SENTENCE_INDEX,
                sentence_end=chain_backfill.NO_SENTENCE_INDEX,
            ),
        ),
        sentences=(translated,),
        cuts=(),
        fallback=None,
    )
    return chain_backfill.verify_redistribution(merge, translated, result).ok


def _retypeset(typesetter, paragraph, page) -> str | None:
    """Set one member again inside its own box; the refusal reason, or None."""
    from babeldoc.format.pdf.document_il.midend.typesetting import (
        BoundedTypesettingError,
    )
    from babeldoc.magazine import line_split

    box = getattr(paragraph, "box", None)
    if box is None or box.x is None or box.y is None:
        return "member_box_unavailable"
    fonts = _fonts_for(typesetter, page)
    if fonts is None:
        return "font_mapper_unavailable"
    try:
        units = typesetter.create_typesetting_units(paragraph, fonts)
        typesetter.retypeset_bounded_text(
            paragraph,
            page,
            units,
            source_ref="tail-rebalance",
            source_box=(
                float(box.x),
                float(box.y),
                float(box.x2),
                float(box.y2),
            ),
            minimum_scale=line_split.load_line_split_config().minimum_readable_scale,
            maximum_lines=None,
        )
    except BoundedTypesettingError as error:
        return str(error) or "member_does_not_fit"
    return None


def _rebalance_one(
    typesetter,
    prev_paragraph,
    prev_page,
    next_paragraph,
    next_page,
    chain_config,
) -> tuple[bool, str, int]:
    """Move one dangling last line into the next member, or say why not.

    Returns (applied, reason, chars_moved). Every refusal leaves both
    paragraphs exactly as they stood.
    """
    for member in (prev_paragraph, next_paragraph):
        if bool(getattr(member, "drop_cap_candidate", False)):
            return False, "member_is_a_drop_cap", 0
    prev_chars = _paragraph_characters_ordered(prev_paragraph)
    next_chars = _paragraph_characters_ordered(next_paragraph)
    if not prev_chars or not next_chars:
        return False, "member_has_no_characters", 0
    lines = group_lines(prev_chars, float(chain_config["line_overlap_min"]))
    if len(lines) < 2:
        return False, "tail_is_the_whole_member", 0
    moved = lines[-1]
    moved_text = "".join(
        character.char_unicode or "" for character in moved
    )
    prev_text = prev_paragraph.unicode or ""
    next_text = next_paragraph.unicode or ""
    if not moved_text.strip():
        return False, "tail_is_whitespace", 0
    if not prev_text.endswith(moved_text):
        return False, "tail_text_disagrees_with_member_text", 0
    new_prev = prev_text[: len(prev_text) - len(moved_text)]
    new_next = moved_text + next_text
    if not new_prev.strip():
        return False, "move_would_empty_the_member", 0
    if not _verified_conservation(prev_text, next_text, new_prev, new_next):
        return False, "conservation_refused", 0

    prev_before = _snapshot(prev_paragraph)
    next_before = _snapshot(next_paragraph)
    moved_set = {id(character) for character in moved}
    prev_paragraph.pdf_paragraph_composition = _flat_composition(
        [
            character
            for character in prev_chars
            if id(character) not in moved_set
        ]
    )
    prev_paragraph.unicode = new_prev
    next_paragraph.pdf_paragraph_composition = _flat_composition(
        list(moved) + next_chars
    )
    next_paragraph.unicode = new_next
    for member, page in ((prev_paragraph, prev_page), (next_paragraph, next_page)):
        refused = _retypeset(typesetter, member, page)
        if refused is not None:
            _restore(prev_paragraph, prev_before)
            _restore(next_paragraph, next_before)
            return False, f"retypeset_refused:{refused}", 0
    return True, "applied", len(moved_text)


def rebalance(
    translation_config, docs, rows: list[dict], typesetter, parameters: dict
) -> dict:
    """Merge every qualifying dangling chained tail forward, within budget."""
    budget = int(parameters["tail_rebalance_max"])
    minimum = int(parameters["tail_min_chars"])
    record = {
        "budget": budget,
        "tail_min_chars": minimum,
        "attempts": [],
        "applied": 0,
    }
    if budget <= 0 or typesetter is None:
        record["enabled"] = False
        return record
    record["enabled"] = True
    chain_config = load_chain_config()
    pages_by_label = {}
    for position, page in enumerate(docs.page):
        label = int(
            page.page_number if page.page_number is not None else position
        ) + 1
        pages_by_label[label] = page
    by_ref = _labeled_paragraphs(docs)
    for row in rows:
        if record["applied"] >= budget:
            break
        line = row.get("last_line")
        if (
            not row.get("chained")
            or line is None
            or not 0 < line["chars"] <= minimum
            or line["terminal_punct"] is not False
        ):
            continue
        try:
            prev_key = parse_source_ref(row["prev_ref"])
            next_key = parse_source_ref(row["next_ref"])
        except (TypeError, ValueError):
            continue
        prev_paragraph = by_ref.get(prev_key)
        next_paragraph = by_ref.get(next_key)
        prev_page = pages_by_label.get(prev_key[0])
        next_page = pages_by_label.get(next_key[0])
        if None in (prev_paragraph, next_paragraph, prev_page, next_page):
            continue
        applied, reason, chars_moved = _rebalance_one(
            typesetter,
            prev_paragraph,
            prev_page,
            next_paragraph,
            next_page,
            chain_config,
        )
        record["attempts"].append(
            {
                "prev_ref": row["prev_ref"],
                "next_ref": row["next_ref"],
                "tail_chars": line["chars"],
                "tail_text": line["text"],
                "outcome": reason,
                "chars_moved": chars_moved,
            }
        )
        if applied:
            record["applied"] += 1
    return record


def _write_report(translation_config, record: dict) -> Path:
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def apply(
    translation_config, docs, article_document_ir=None, typesetter=None
) -> dict | None:
    """Measure every continuation tail, merge the dangling ones, measure again.

    The report always describes the finished pages: where the rebalance moved
    a tail, the boundaries are measured a second time and the rows and the
    summary carry the post-move state, with the moves themselves on record.
    """
    if not enabled(translation_config):
        return None
    parameters = load_tail_fill_config()
    rows = measure_boundaries(translation_config, docs, article_document_ir)
    rebalanced = rebalance(translation_config, docs, rows, typesetter, parameters)
    if rebalanced["applied"]:
        rows = measure_boundaries(translation_config, docs, article_document_ir)
    record = {
        "schema_version": SCHEMA_VERSION,
        "switch": SWITCH,
        "status": "success" if rows else "no_boundaries",
        "boundaries": rows,
        "rebalance": rebalanced,
        "summary": summarize(rows, parameters),
    }
    _write_report(translation_config, record)
    logger.debug(
        "tail fill: %d boundary(ies) measured, %d rebalanced",
        len(rows),
        rebalanced["applied"],
    )
    return record
