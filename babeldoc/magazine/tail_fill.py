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


def _write_report(translation_config, record: dict) -> Path:
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def apply(translation_config, docs, article_document_ir=None) -> dict | None:
    """Measure every continuation tail of the finished document and say so."""
    if not enabled(translation_config):
        return None
    parameters = load_tail_fill_config()
    rows = measure_boundaries(translation_config, docs, article_document_ir)
    record = {
        "schema_version": SCHEMA_VERSION,
        "switch": SWITCH,
        "status": "success" if rows else "no_boundaries",
        "boundaries": rows,
        "summary": summarize(rows, parameters),
    }
    _write_report(translation_config, record)
    logger.debug("tail fill: %d boundary(ies) measured", len(rows))
    return record
