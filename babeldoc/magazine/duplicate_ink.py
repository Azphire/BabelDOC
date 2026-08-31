"""The same words painted twice in one place, printed once.

What this is about
------------------

A magazine page is a production artifact, and a production artifact carries the
marks of how it was made. On page 3 of the IAEA Bulletin the photo credit
``（图/国际原子能机构）`` is painted twice at the same left margin, thirteen and a
half points apart, the two copies overlapping. A reader of the source sees one
of them: the upper copy sits under the photograph it credits, and the
photograph is opaque.

Nothing in the pipeline asked whether the source had ever shown a unit before
reproducing it, so both copies were translated and both were set. The target's
metrics are not the source's -- a Latin line sits differently inside the same
box than the Chinese line it replaced -- and the copy the photograph used to
hide now reaches below its bottom edge. A hidden duplicate became a visible
one, and the page gained a defect the source did not have.

The rule
--------

One sentence: where a page paints the same text twice with intersecting boxes,
it is painting it once, and exactly one copy survives.

Identity is the normalised source text, NFKC and outer whitespace only, read
through the same normaliser the parenthetical folding rule compares by, so the
two passes cannot come to mean different things by "the same string".
Intersection is positive shared area, as a fraction of the smaller box, against
a declared floor: two copies of ``Fig. 1`` at opposite ends of a page are two
labels, and only copies fighting for one piece of paper are one label.

Which copy survives is decided by what the source showed, and the evidence is
geometric rather than rendered: the fraction of a copy's box that no piece of
page artwork covers. The copy showing the most of itself is the one the source
meant a reader to read. Where two copies are equally uncovered the earlier in
reading order survives, because a tie has to break somewhere and the page's own
order is the only thing left that is not arbitrary.

Note what the rule does not rest on. It does not ask which object the content
stream painted last, because the intermediate language does not carry that
order and a rule that guessed at it would be guessing at the answer. Coverage
by artwork decides only *which* of two copies survives, never *whether* a lone
paragraph is dropped -- a body paragraph set over a full-bleed photograph is
covered by artwork and is not a duplicate of anything, so this pass never
reaches it.

What survives and what is withheld
----------------------------------

A withheld copy is emptied rather than deleted: its compositions and its text
go, its paragraph stays. This is the shape the drop cap merge already uses on
the companion glyph it absorbs, so nothing new happens to the document
structure, and an emptied paragraph is not text the coverage ledger is owed.

Where this sits
---------------

After the stitch, the split and the span merge, so the page has settled into
the paragraphs the rest of the run will see and a copy is compared at the shape
it will be set at; before the chain builder and the article builder, so no
chain is ever linked through a paragraph this pass is about to empty and no
article claims text that will not be printed. That also puts it before the
coverage snapshot is frozen, which is why a withheld copy leaves the ledger
balanced rather than owed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine import fixed_assets
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.paren_dedup import normalize
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import TAXONOMY_PATH
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("duplicate_ink.json")

REPORT_NAME = "duplicate_ink.report.json"

# The switch, by the name the caller sets on the translation config. Up unless
# something puts it down: printing one line of text twice is not a rendering a
# run has to opt out of, and the rule reaches nothing it is not certain about.
SWITCH = "magazine_duplicate_ink"

# The key the configuration names the switch under. Read out of the file and
# checked against the constant, so the name a run is read from and the name the
# switch inventory scans for cannot drift apart.
SWITCH_KEY = "switch"

# Why a copy was withheld. One entry, because the pass makes one kind of
# finding; declared as a closed set anyway so a reader of the sidecar meets the
# vocabulary rather than a string written at the site.
WITHHELD_DUPLICATE = "duplicate_source_ink"
WITHHOLD_REASONS = (WITHHELD_DUPLICATE,)

# Why one copy of a group was the one kept. Also closed: "it showed more of
# itself" and "it came first" are different findings about the same page and a
# sidecar that could not tell them apart would answer neither.
KEPT_MOST_UNCOVERED = "most_uncovered"
KEPT_READING_ORDER = "earliest_in_reading_order"
KEEP_REASONS = (KEPT_MOST_UNCOVERED, KEPT_READING_ORDER)


class DuplicateInkError(ConfigError):
    """Raised when the duplicate ink configuration is malformed."""


@dataclass(frozen=True)
class DuplicateInkConfig:
    """Everything bounded about deciding that one page painted one line twice."""

    min_overlap_fraction: float
    max_line_gap_ratio: float
    min_text_chars: int
    uncovered_tolerance: float
    excerpt_chars: int


def parse_duplicate_ink_config(raw: dict, source: str) -> DuplicateInkConfig:
    """Validate one configuration mapping into the policy it declares."""
    switch = raw.get(SWITCH_KEY)
    if switch != SWITCH:
        raise DuplicateInkError(
            f"{source}: {SWITCH_KEY}={switch!r} is not the attribute this pass "
            f"is read from ({SWITCH!r})"
        )
    try:
        parameters = dict(
            validate_bounded_config(
                {key: value for key, value in raw.items() if key != SWITCH_KEY},
                CONFIG_PATH,
            )
        )
    except ConfigError as exc:
        raise DuplicateInkError(str(exc)) from exc
    numbers = (
        "min_overlap_fraction",
        "max_line_gap_ratio",
        "min_text_chars",
        "uncovered_tolerance",
        "excerpt_chars",
    )
    missing = sorted(set(numbers) - set(parameters))
    if missing:
        raise DuplicateInkError(f"{source}: missing parameters {missing}")
    return DuplicateInkConfig(
        min_overlap_fraction=float(parameters["min_overlap_fraction"]),
        max_line_gap_ratio=float(parameters["max_line_gap_ratio"]),
        min_text_chars=int(parameters["min_text_chars"]),
        uncovered_tolerance=float(parameters["uncovered_tolerance"]),
        excerpt_chars=int(parameters["excerpt_chars"]),
    )


@lru_cache(maxsize=1)
def load_duplicate_ink_config(path: str | None = None) -> DuplicateInkConfig:
    """Load and validate ``configs/duplicate_ink.json``."""
    resolved = CONFIG_PATH if path is None else Path(path)
    with resolved.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise DuplicateInkError(f"{resolved.name}: root must be an object")
    return parse_duplicate_ink_config(raw, resolved.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def _box(value) -> tuple[float, float, float, float] | None:
    if value is None or any(
        getattr(value, name, None) is None for name in ("x", "y", "x2", "y2")
    ):
        return None
    box = tuple(float(getattr(value, name)) for name in ("x", "y", "x2", "y2"))
    return box if box[0] < box[2] and box[1] < box[3] else None


def _area(box) -> float:
    return (box[2] - box[0]) * (box[3] - box[1])


def _intersection(left, right):
    box = (
        max(left[0], right[0]),
        max(left[1], right[1]),
        min(left[2], right[2]),
        min(left[3], right[3]),
    )
    return box if box[0] < box[2] and box[1] < box[3] else None


def _covered_area(box, blockers) -> float:
    """The area of ``box`` under the union of ``blockers``.

    A union rather than a sum: two overlapping figures cover a point once, and
    adding their overlaps would report a box as more than wholly covered. The
    union is exact -- the coordinates are compressed into a grid and each cell
    is tested -- because the blockers on one page are few and an approximation
    here would be an approximation in the evidence a decision is recorded with.
    """
    pieces = [
        piece for piece in (_intersection(box, blocker) for blocker in blockers)
        if piece is not None
    ]
    if not pieces:
        return 0.0
    xs = sorted({value for piece in pieces for value in (piece[0], piece[2])})
    ys = sorted({value for piece in pieces for value in (piece[1], piece[3])})
    total = 0.0
    for left, right in zip(xs, xs[1:], strict=False):
        for bottom, top in zip(ys, ys[1:], strict=False):
            centre = ((left + right) / 2.0, (bottom + top) / 2.0)
            for piece in pieces:
                if (
                    piece[0] <= centre[0] <= piece[2]
                    and piece[1] <= centre[1] <= piece[3]
                ):
                    total += (right - left) * (top - bottom)
                    break
    return total


def artwork_boxes(translation_config, page, physical_label: int) -> list:
    """Every piece of artwork on one page that can hide text behind it.

    Read from the source file rather than from the intermediate language,
    because the two do not hold the same inventory: the IL's artwork
    collections carry what the structural passes made of a page, and on the
    page this rule was written for they hold a rule line and not the
    photograph that hides the credit. The source file is asked with the
    physical page label -- the number the page carries in the file the run
    opened -- so a run over a page range asks about the page it is actually
    looking at.

    An unreadable file, or a label the file does not hold, yields nothing:
    with no blockers every copy measures equally uncovered and the choice
    falls to reading order, which is a worse answer than the evidence would
    have given and a better one than a guess.
    """
    found = []
    for collection in fixed_assets.ARTWORK_COLLECTIONS:
        for item in getattr(page, collection, None) or ():
            box = _box(getattr(item, "box", None))
            if box is not None:
                found.append(box)
    input_file = getattr(translation_config, "input_file", None)
    if not input_file:
        return found
    try:
        import pymupdf

        with pymupdf.open(str(input_file)) as source:
            source_page = source[int(physical_label) - 1]
            height = float(source_page.mediabox.y1)
            for info in source_page.get_images(full=True):
                for rect in source_page.get_image_rects(info[0]):
                    found.append(
                        (
                            float(rect.x0),
                            height - float(rect.y1),
                            float(rect.x1),
                            height - float(rect.y0),
                        )
                    )
    except Exception:  # noqa: BLE001 - no evidence is a stated outcome here
        logger.debug(
            "duplicate ink: no artwork evidence for physical page %s", physical_label
        )
    return found


def uncovered_fraction(box, blockers) -> float:
    """How much of one box no artwork covers, as a fraction of its own area."""
    area = _area(box)
    if area <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - _covered_area(box, blockers) / area))


def _one_line_apart(left, right, config: DuplicateInkConfig) -> bool:
    """Whether two boxes are the same line of a page, painted twice.

    Two conditions, both scaled by the boxes themselves so no page coordinate
    or publication measurement enters. Horizontally they have to share a
    declared fraction of the narrower box, which is what makes them the same
    line rather than two lines of a column. Vertically they have to be no
    farther apart than a declared multiple of their own height: touching
    boxes are one case of that and the case this rule was written for --
    consecutive lines, a duplicate the source stacked directly under its
    original -- is the other. A copy two lines away is a page that says
    something twice, which is a page, not a defect.
    """
    shared = min(left[2], right[2]) - max(left[0], right[0])
    narrower = min(left[2] - left[0], right[2] - right[0])
    if narrower <= 0 or shared / narrower < config.min_overlap_fraction:
        return False
    gap = max(left[1], right[1]) - min(left[3], right[3])
    tallest = max(left[3] - left[1], right[3] - right[1])
    return gap <= tallest * config.max_line_gap_ratio


def groups_on_page(page, config: DuplicateInkConfig) -> list[list[int]]:
    """Every set of paragraph indexes on one page painting the same text.

    A group is built by identity of the normalised text first and by sharing
    one line of the page second, so a label printed twice at opposite ends of
    a page stays two labels. Membership is transitive over that relation,
    which is what makes three stacked copies one group rather than two pairs.
    """
    by_text: dict[str, list[int]] = {}
    boxes: dict[int, tuple[float, float, float, float]] = {}
    for index, paragraph in enumerate(page.pdf_paragraph or ()):
        text = normalize(getattr(paragraph, "unicode", "") or "")
        if len(text) < config.min_text_chars:
            continue
        box = _box(getattr(paragraph, "box", None))
        if box is None:
            continue
        by_text.setdefault(text, []).append(index)
        boxes[index] = box
    found: list[list[int]] = []
    for indexes in by_text.values():
        if len(indexes) < 2:
            continue
        remaining = list(indexes)
        while remaining:
            group = [remaining.pop(0)]
            changed = True
            while changed:
                changed = False
                for candidate in list(remaining):
                    for member in group:
                        if _one_line_apart(boxes[candidate], boxes[member], config):
                            group.append(candidate)
                            remaining.remove(candidate)
                            changed = True
                            break
                    if changed:
                        break
            if len(group) > 1:
                found.append(sorted(group))
    return sorted(found)


def _withhold(paragraph) -> None:
    """Empty one copy, keeping the paragraph the document was built with.

    The same two statements the drop cap merge uses on the companion glyph it
    absorbs. Nothing is removed from the page's paragraph list, so every index
    a report or a decision already names still names what it named.
    """
    paragraph.pdf_paragraph_composition = []
    paragraph.unicode = ""


def as_record(config: DuplicateInkConfig, rows: list[dict], pages: int) -> dict:
    return {
        "switch": SWITCH,
        "min_overlap_fraction": config.min_overlap_fraction,
        "min_text_chars": config.min_text_chars,
        "uncovered_tolerance": config.uncovered_tolerance,
        "withhold_reasons": list(WITHHOLD_REASONS),
        "keep_reasons": list(KEEP_REASONS),
        "pages": pages,
        "totals": {
            "groups": len(rows),
            "copies": sum(len(row["copies"]) for row in rows),
            "withheld": sum(
                1 for row in rows for copy in row["copies"] if copy["withheld"]
            ),
            "kept": len(rows),
        },
        "groups": rows,
    }


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH, TAXONOMY_PATH])
    return path


def apply(translation_config, labeled_pages) -> dict | None:
    """Print each repeated line once. None where the switch is down.

    Returns the record it wrote, so a caller holding the document can assert
    about the pass without reading the sidecar back.
    """
    if not enabled(translation_config):
        return None
    config = load_duplicate_ink_config()
    rows: list[dict] = []
    pages = 0
    for physical_label, page in labeled_pages:
        pages += 1
        blockers = None
        for group in groups_on_page(page, config):
            if blockers is None:
                # Asked once per page, and only for a page that has a group:
                # opening the source file is the expensive half of this pass
                # and a page painting nothing twice has no question to answer.
                blockers = artwork_boxes(translation_config, page, physical_label)
            measured = []
            for index in group:
                paragraph = page.pdf_paragraph[index]
                box = _box(paragraph.box)
                measured.append(
                    {
                        "index": index,
                        "reference": paragraph_reference(physical_label, index),
                        "debug_id": getattr(paragraph, "debug_id", None),
                        "box": [round(value, 4) for value in box],
                        "uncovered_fraction": round(
                            uncovered_fraction(box, blockers), 6
                        ),
                    }
                )
            best = max(item["uncovered_fraction"] for item in measured)
            contenders = [
                item
                for item in measured
                if best - item["uncovered_fraction"] <= config.uncovered_tolerance
            ]
            kept = contenders[0]
            keep_reason = (
                KEPT_READING_ORDER if len(contenders) > 1 else KEPT_MOST_UNCOVERED
            )
            paragraph = page.pdf_paragraph[group[0]]
            excerpt = normalize(getattr(paragraph, "unicode", "") or "")
            for item in measured:
                item["withheld"] = item["index"] != kept["index"]
                item["reason"] = (
                    WITHHELD_DUPLICATE if item["withheld"] else None
                )
                if item["withheld"]:
                    _withhold(page.pdf_paragraph[item["index"]])
            rows.append(
                {
                    "page": physical_label,
                    "text": excerpt[: config.excerpt_chars],
                    "kept": kept["reference"],
                    "keep_reason": keep_reason,
                    "blockers": len(blockers),
                    "copies": measured,
                }
            )
    record = as_record(config, rows, pages)
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    write_report(working_dir, record)
    if rows:
        logger.debug(
            "duplicate ink: %d group(s), %d copy/copies withheld",
            record["totals"]["groups"],
            record["totals"]["withheld"],
        )
    return record
