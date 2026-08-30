"""Running furniture and production marks, found by shape and held steady.

A magazine repeats its furniture: the folio line and the publication domain
stand at the page edge of every page, letter for letter the same.  Translated
page by page they come back in as many voices as pages -- B14's CERN Courier
carried four spellings of one masthead.  And under the furniture, printers'
slugs travel with the file: drawn twice at the same coordinates, stroke-only
or clipped away in the source, invisible to a reader and yet parsed into the
IL, where translation mangles them into half-translated interleave.

Two shape rules, no content test:

*Repeat furniture* -- a paragraph whose normalized text appears on at least
``furniture_repeat_min_pages`` physical pages, every occurrence within
``furniture_edge_band_pt`` of its page's nearest edge, is one string the
publication repeats.  The first occurrence in document order is the leader
and is translated once; every other member skips translation and takes the
leader's translated text afterwards, set in its own paragraph style.

*Production marks* -- a paragraph in the same edge band in which at least
``production_dupe_min_fraction`` of the characters lie glyph-on-glyph over a
twin (same character, boxes within ``production_dupe_tolerance_em`` of the
letter size) is text drawn twice at one position: the shape of a printing
slug, never of prose.  It is withheld whole -- not translated, not stitched,
not re-set -- so the page keeps it exactly as the source drew it.

The pass runs before the fragment stitch, so a stitch can refuse to reach
into a withheld paragraph, and before translation, which consults the marks
through ``withholds``.  After translation ``unify`` copies each leader's text
onto its members.  What a member gives up is its internal style variation:
the reused text renders in the member's own paragraph style, the same trade
T1a's span merge makes, recorded in UPSTREAM_DIFF.md.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import hitl
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("furniture.json")

REPORT_NAME = "furniture.report.json"

# The switch, by the name the caller sets on the translation config. Up unless
# something puts it down: a publication's furniture speaking with one voice is
# not behavior a run opts into.
SWITCH = "magazine_furniture"

# The plan travels on the translation config as ``magazine_furniture_plan``
# and is consulted by debug_id: the IL dataclasses are slotted and the schema
# stays frozen, so nothing is ever written onto a paragraph object.
PLAN_ATTR = "magazine_furniture_plan"

# The markup the translated text may carry; stripped when a leader's text is
# copied onto a member, whose single-run composition holds no spans.
_PLACEHOLDER_MARKUP = re.compile(
    r"<\s*style\s+id\s*=\s*'\s*\d+\s*'\s*>|<\s*/\s*style\s*>|\{\s*v\s*\d+\s*\}"
)


class FurnitureError(ConfigError):
    """Raised when the furniture configuration is malformed."""


@dataclass(frozen=True)
class FurnitureConfig:
    repeat_min_pages: int
    edge_band_pt: float
    dupe_min_fraction: float
    dupe_tolerance_em: float
    excerpt_chars: int


def parse_furniture_config(raw: dict, source: str) -> FurnitureConfig:
    flat = {key: value for key, value in raw.items() if key != "switch"}
    try:
        parameters = dict(validate_bounded_config(flat, CONFIG_PATH))
    except ConfigError as exc:
        raise FurnitureError(str(exc)) from exc
    for key in (
        "furniture_repeat_min_pages",
        "furniture_edge_band_pt",
        "production_dupe_min_fraction",
        "production_dupe_tolerance_em",
        "excerpt_chars",
    ):
        if key not in parameters:
            raise FurnitureError(f"{source}: missing {key}")
    return FurnitureConfig(
        repeat_min_pages=int(parameters["furniture_repeat_min_pages"]),
        edge_band_pt=float(parameters["furniture_edge_band_pt"]),
        dupe_min_fraction=float(parameters["production_dupe_min_fraction"]),
        dupe_tolerance_em=float(parameters["production_dupe_tolerance_em"]),
        excerpt_chars=int(parameters["excerpt_chars"]),
    )


@lru_cache(maxsize=1)
def load_furniture_config(path: str | None = None) -> FurnitureConfig:
    """Load and validate ``configs/furniture.json``."""
    source = CONFIG_PATH if path is None else Path(path)
    with source.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise FurnitureError(f"{source.name}: root must be an object")
    return parse_furniture_config(raw, source.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, True))


def normalized(text: str) -> str:
    """The identity two occurrences of one furniture string share."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


# --- geometry -----------------------------------------------------------------


def edge_distance(paragraph, page) -> float | None:
    """How far one paragraph stands from its page's nearest edge."""
    box = paragraph.box
    if box is None or None in (box.x, box.y, box.x2, box.y2):
        return None
    width, height = _page_extent(page)
    if not width or not height:
        return None
    return min(box.x, box.y, width - box.x2, height - box.y2)


def _page_extent(page) -> tuple[float | None, float | None]:
    for name in ("cropbox", "mediabox"):
        holder = getattr(page, name, None)
        box = getattr(holder, "box", None)
        if box is not None and None not in (box.x, box.y, box.x2, box.y2):
            return box.x2 - box.x, box.y2 - box.y
    return None, None


def duplicate_fraction(paragraph, tolerance_em: float) -> float:
    """The share of characters lying glyph-on-glyph over a twin.

    Two draws of one slug at one text matrix put every character exactly on
    top of its twin; ordinary text never does.  Pairing is greedy over
    identical characters whose origins agree within ``tolerance_em`` of the
    letter size, and each character pairs at most once, so a tripled draw
    counts as well as a doubled one.
    """
    characters = []
    for composition in paragraph.pdf_paragraph_composition or ():
        for name in ("pdf_line", "pdf_same_style_characters"):
            holder = getattr(composition, name, None)
            if holder is not None:
                characters.extend(holder.pdf_character or ())
        if composition.pdf_character is not None:
            characters.append(composition.pdf_character)
    measurable = [
        item
        for item in characters
        if (item.char_unicode or "").strip()
        and item.box is not None
        and None not in (item.box.x, item.box.y)
    ]
    if len(measurable) < 4:
        return 0.0
    paired: set[int] = set()
    for i, one in enumerate(measurable):
        if i in paired:
            continue
        size = _char_size(one)
        tolerance = tolerance_em * size if size else 1.0
        for j in range(i + 1, len(measurable)):
            if j in paired:
                continue
            other = measurable[j]
            if one.char_unicode != other.char_unicode:
                continue
            if (
                abs(one.box.x - other.box.x) <= tolerance
                and abs(one.box.y - other.box.y) <= tolerance
            ):
                paired.add(i)
                paired.add(j)
                break
    return len(paired) / len(measurable)


def _char_size(character) -> float | None:
    style = getattr(character, "pdf_style", None)
    size = getattr(style, "font_size", None)
    return float(size) if size else None


# --- the plan -----------------------------------------------------------------


@dataclass
class FurniturePlan:
    """What the pass decided, addressed by ``debug_id``."""

    leaders: dict[str, list[str]] = field(default_factory=dict)
    reuse_members: dict[str, str] = field(default_factory=dict)
    production_marks: set[str] = field(default_factory=set)
    record: dict = field(default_factory=dict)

    def withholds(self, debug_id: str | None) -> bool:
        """Whether translation must leave this paragraph alone."""
        return debug_id in self.reuse_members or debug_id in self.production_marks


def _paragraph_index(docs) -> list[tuple[int, int, object, object]]:
    rows = []
    for label, page in hitl.labeled_pages(docs):
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            rows.append((label, index, page, paragraph))
    return rows


def plan(translation_config, docs) -> FurniturePlan | None:
    """Mark repeat furniture and production marks. None with the switch down."""
    if not enabled(translation_config):
        return None
    config = load_furniture_config()
    built = FurniturePlan()
    rows = _paragraph_index(docs)

    marks = []
    for label, index, page, paragraph in rows:
        distance = edge_distance(paragraph, page)
        if distance is None or distance > config.edge_band_pt:
            continue
        fraction = duplicate_fraction(paragraph, config.dupe_tolerance_em)
        if fraction >= config.dupe_min_fraction:
            built.production_marks.add(paragraph.debug_id)
            marks.append(
                {
                    "page": label,
                    "reference": paragraph_reference(label, index),
                    "debug_id": paragraph.debug_id,
                    "duplicate_fraction": round(fraction, 3),
                    "edge_distance_pt": round(distance, 1),
                    "excerpt": (paragraph.unicode or "")[: config.excerpt_chars],
                }
            )

    by_text: dict[str, list] = {}
    off_band: dict[str, bool] = {}
    for label, index, page, paragraph in rows:
        if paragraph.debug_id in built.production_marks:
            continue
        key = normalized(paragraph.unicode or "")
        if not key:
            continue
        distance = edge_distance(paragraph, page)
        in_band = distance is not None and distance <= config.edge_band_pt
        off_band[key] = off_band.get(key, False) or not in_band
        by_text.setdefault(key, []).append((label, index, paragraph, distance))

    groups = []
    for key, members in by_text.items():
        if off_band[key]:
            # One occurrence away from the edge is one occurrence that may be
            # prose; the whole string stays out rather than half in.
            continue
        pages_seen = {label for label, _i, _p, _d in members}
        if len(pages_seen) < config.repeat_min_pages:
            continue
        leader_label, leader_index, leader, _d = members[0]
        member_ids = []
        for label, index, paragraph, _distance in members[1:]:
            built.reuse_members[paragraph.debug_id] = leader.debug_id
            member_ids.append(paragraph_reference(label, index))
        built.leaders[leader.debug_id] = [
            paragraph.debug_id for _l, _i, paragraph, _d in members[1:]
        ]
        groups.append(
            {
                "text": key[: config.excerpt_chars],
                "pages": sorted(pages_seen),
                "occurrences": len(members),
                "leader": paragraph_reference(leader_label, leader_index),
                "members": member_ids,
            }
        )

    built.record = {
        "switch": SWITCH,
        "furniture_repeat_min_pages": config.repeat_min_pages,
        "furniture_edge_band_pt": config.edge_band_pt,
        "production_dupe_min_fraction": config.dupe_min_fraction,
        "production_dupe_tolerance_em": config.dupe_tolerance_em,
        "totals": {
            "groups": len(groups),
            "reuse_members": len(built.reuse_members),
            "production_marks": len(built.production_marks),
        },
        "groups": groups,
        "production_marks": marks,
        "unified": [],
    }
    _write_report(translation_config, built.record)
    logger.debug(
        "furniture: %d group(s), %d member(s) to reuse, %d production mark(s)",
        len(groups),
        len(built.reuse_members),
        len(built.production_marks),
    )
    return built


def unify(translation_config, docs, built: FurniturePlan | None) -> None:
    """Copy each translated leader's text onto its members, after translation.

    A leader that kept its source (an identity pasteback, or a unit never
    offered) leaves its members exactly as they are -- every copy stays
    source, which is the same one voice.  The outcome of every member is a
    row in the report either way.
    """
    if built is None or not enabled(translation_config):
        return
    by_id = {}
    for label, index, _page, paragraph in _paragraph_index(docs):
        by_id[paragraph.debug_id] = (label, index, paragraph)
    unified = []
    for leader_id, member_ids in built.leaders.items():
        leader_row = by_id.get(leader_id)
        if leader_row is None:
            continue
        _l, _i, leader = leader_row
        translated = any(
            composition.pdf_same_style_unicode_characters is not None
            for composition in leader.pdf_paragraph_composition or ()
        )
        text = _PLACEHOLDER_MARKUP.sub("", leader.unicode or "") if translated else None
        for member_id in member_ids:
            member_row = by_id.get(member_id)
            if member_row is None:
                unified.append({"member": member_id, "outcome": "member_missing"})
                continue
            label, index, member = member_row
            if not translated:
                unified.append(
                    {
                        "member": paragraph_reference(label, index),
                        "outcome": "leader_kept_source",
                    }
                )
                continue
            run = il_version_1.PdfSameStyleUnicodeCharacters()
            run.unicode = text
            run.pdf_style = member.pdf_style
            composition = il_version_1.PdfParagraphComposition()
            composition.pdf_same_style_unicode_characters = run
            member.unicode = text
            member.pdf_paragraph_composition = [composition]
            unified.append(
                {
                    "member": paragraph_reference(label, index),
                    "outcome": "reused",
                    "text": (text or "")[:80],
                }
            )
    built.record["unified"] = unified
    _write_report(translation_config, built.record)


def _write_report(translation_config, record: dict) -> Path:
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path
