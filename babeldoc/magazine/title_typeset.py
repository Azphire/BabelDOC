"""Heading typesetting policy, applied to a document the stage has laid out.

A heading is a display unit rather than a paragraph of running text, and the
three things that follow from that are the whole of this pass. It is set on one
line, because a headline broken mid word is a headline nobody set. It carries
no first line indent, because the indent is a running text convention the
paragraph finder infers from where the first line starts. And it is shown once,
because a display headline is routinely drawn twice -- once per paint, a solid
layer under a gradient or texture layer -- and the two layers survive the
translation as two copies of the text rather than as one headline.

Where this sits and why
-----------------------

After the typesetting stage, which is the point at which the geometry a
paragraph will render at is final, and before detection reads it. Nothing
upstream is changed to reach that point: the pass is called from
``detectors.detect_issues``, which is the only extension owned code the pipeline
runs in that window, so this pass runs when ``magazine_detect`` runs. Its own
switch is ``magazine_title_typeset`` and it is down by default; with it down
this module returns having read nothing and the document is byte for byte the
one the stage produced.

What one heading is laid out again from
---------------------------------------

The characters it was laid out as, grouped back into style runs -- consecutive
characters agreeing on font id, size and paint -- and rebuilt as unicode runs.
Rebuilt rather than reused because a character unit passes straight through the
stage: ``TypesettingUnit.calc_can_passthrough`` is ``self.unicode is None``, so
a paragraph handed back its own laid out characters is copied, not laid out.
Only a unicode run makes the stage measure and place text again.

There is no flag anywhere upstream that forbids a line break, so single line is
not asked for, it is obtained: the layout wraps when a unit would cross the
right edge of the box, and a scale at which the whole run fits inside the box
never reaches that edge. The scale is estimated from the font metrics the stage
itself measures with and then verified against the result -- the characters that
came back have to sit in one band -- and shrunk and retried while they do not.
The measurement is the authority, the estimate only picks where to start.

Erasure
-------

Nothing here erases anything, because nothing upstream erases anything either.
``PDFCreater.update_page_content_stream`` builds each page's content stream from
this document -- the page's own base operations are not carried over -- so the
source text of every paragraph is gone from the output by construction, and a
layer dropped here is dropped from the output whether it was source or
translation. That is what makes deduplicating a layer safe: suppressing it needs
no counterpart erasure, and a duplicate paragraph left with an empty composition
renders nothing at all.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import hitl
from babeldoc.magazine.article_builder import TITLE_CLASSES_KEY
from babeldoc.magazine.article_builder import title_labels
from babeldoc.magazine.chain_signals import CLASS_LABELS_KEY
from babeldoc.magazine.chain_signals import CONFIG_PATH as CHAIN_CONFIG_PATH
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.react.writeback import page_font_map
from babeldoc.magazine.reading_order import paragraph_reading_text
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "title_typeset.json"

REPORT_NAME = "title_typeset.report.json"

# The switch, by the name the caller sets on the translation config.
SWITCH = "magazine_title_typeset"

# The switch this pass rides, because the window it has to run in holds no other
# extension owned call. Named here so the report says what it depended on.
WINDOW_SWITCH = "magazine_detect"

# Structural sections of the configuration: what is validated against a declared
# vocabulary rather than against a numeric range.
FLOOR_KEY = "on_floor"
FLOOR_VOCABULARY_KEY = "on_floor_vocabulary"

_STRUCTURAL_KEYS = (FLOOR_KEY,)

# The floor policy that raises what it could not set, by the name the
# configuration's own vocabulary declares it under. The other member of that
# vocabulary accepts the same rendering without raising anything.
FLOOR_ESCALATE = "escalate"

# What was done with one heading.
DISPOSITION_UNCHANGED = "unchanged"
DISPOSITION_SINGLE_LINE = "single_line"
DISPOSITION_FLOOR = "floor_reached"

# What a deduplicated layer was recovered as.
LAYER_PARAGRAPH = "paragraph"
LAYER_RUN = "run"


class TitleTypesetError(ConfigError):
    """Raised when the title typesetting configuration is malformed."""


@dataclass(frozen=True)
class TitleConfig:
    """Everything bounded about setting one heading."""

    labels: tuple[str, ...]
    title_min_scale: float
    on_floor: str
    duplicate_min_iou: float
    duplicate_min_text_similarity: float
    duplicate_min_chars: int
    duplicate_font_size_tolerance: float
    single_line_width_ratio: float
    scale_shrink_step: float
    max_scale_attempts: int
    line_band_tolerance: float

    def is_title(self, paragraph) -> bool:
        return getattr(paragraph, "layout_label", None) in self.labels


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TitleTypesetError(message)


def parse_title_config(raw: dict, source: str) -> TitleConfig:
    """Validate one configuration mapping into the policy it declares."""
    flat = {key: value for key, value in raw.items() if key not in _STRUCTURAL_KEYS}
    try:
        parameters = dict(validate_bounded_config(flat, CONFIG_PATH))
    except ConfigError as exc:
        raise TitleTypesetError(str(exc)) from exc

    _require(TITLE_CLASSES_KEY in parameters, f"{source}: missing {TITLE_CLASSES_KEY}")
    vocabulary = tuple(parameters.get(FLOOR_VOCABULARY_KEY, ()))
    _require(bool(vocabulary), f"{source}: missing {FLOOR_VOCABULARY_KEY}")
    floor = raw.get(FLOOR_KEY)
    _require(
        floor in vocabulary,
        f"{source}: {FLOOR_KEY} is {floor!r}, outside {sorted(vocabulary)}",
    )
    _require(
        FLOOR_ESCALATE in vocabulary,
        f"{source}: {FLOOR_VOCABULARY_KEY} omits {FLOOR_ESCALATE!r}, which is "
        f"the policy the report raises a heading under",
    )
    # The heading labels come from the chain detector's own class declaration,
    # which is what keeps one description of a heading serving both.
    declared = load_chain_config()[CLASS_LABELS_KEY]
    unknown = sorted(set(parameters[TITLE_CLASSES_KEY]) - set(declared))
    _require(
        not unknown,
        f"{source}: {TITLE_CLASSES_KEY} names {unknown}, which "
        f"{CHAIN_CONFIG_PATH.name} does not declare as endpoint classes; "
        f"declared classes are {sorted(declared)}",
    )
    labels = title_labels(parameters)
    _require(bool(labels), f"{source}: {TITLE_CLASSES_KEY} names no layout label")

    return TitleConfig(
        labels=labels,
        title_min_scale=float(parameters["title_min_scale"]),
        on_floor=str(floor),
        duplicate_min_iou=float(parameters["duplicate_min_iou"]),
        duplicate_min_text_similarity=float(
            parameters["duplicate_min_text_similarity"]
        ),
        duplicate_min_chars=int(parameters["duplicate_min_chars"]),
        duplicate_font_size_tolerance=float(
            parameters["duplicate_font_size_tolerance"]
        ),
        single_line_width_ratio=float(parameters["single_line_width_ratio"]),
        scale_shrink_step=float(parameters["scale_shrink_step"]),
        max_scale_attempts=int(parameters["max_scale_attempts"]),
        line_band_tolerance=float(parameters["line_band_tolerance"]),
    )


@lru_cache(maxsize=2)
def load_title_config(path: str | None = None) -> TitleConfig:
    """Load and validate ``configs/title_typeset.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_title_config(raw, config_path.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


# --- reading a laid out paragraph ---------------------------------------------


def laid_out_characters(paragraph) -> list:
    """The characters a laid out paragraph is composed of, in stored order.

    After the stage, a paragraph that was typeset carries one character per
    composition. A composition holding anything else belongs to a paragraph the
    stage passed through rather than laid out, and this pass leaves those alone
    rather than guessing at their structure.
    """
    characters = []
    for composition in paragraph.pdf_paragraph_composition or ():
        if composition is None or composition.pdf_character is None:
            return []
        characters.append(composition.pdf_character)
    return characters


def _style_key(character) -> tuple:
    """What makes two characters part of one style run: font, size and paint."""
    style = character.pdf_style
    if style is None:
        return (None, None, None)
    state = style.graphic_state
    return (
        style.font_id,
        style.font_size,
        None if state is None else state.passthrough_per_char_instruction,
    )


@dataclass
class Run:
    """One style run of a laid out heading."""

    style: object
    characters: list
    position: int

    @property
    def text(self) -> str:
        return "".join(item.char_unicode or "" for item in self.characters)


def style_runs(characters) -> list[Run]:
    """Consecutive characters agreeing on font, size and paint, as runs."""
    runs: list[Run] = []
    previous = object()
    for character in characters:
        key = _style_key(character)
        if not runs or key != previous:
            runs.append(Run(character.pdf_style, [character], len(runs)))
        else:
            runs[-1].characters.append(character)
        previous = key
    return runs


def line_bands(characters, tolerance: float) -> list[float]:
    """The distinct vertical bands the characters were laid out on.

    The layout places every character of one line at one vertical position, so
    the bands are the distinct positions; the tolerance is a fraction of the
    line height and absorbs nothing more than arithmetic noise.
    """
    positions = [
        float(item.box.y)
        for item in characters
        if item.box is not None and item.box.y is not None
    ]
    if not positions:
        return []
    heights = [
        float(item.box.y2) - float(item.box.y)
        for item in characters
        if item.box is not None and item.box.y is not None and item.box.y2 is not None
    ]
    span = max(heights) if heights else 0.0
    window = max(span * tolerance, 1e-6)
    bands: list[float] = []
    for position in sorted(positions):
        if not bands or abs(position - bands[-1]) > window:
            bands.append(position)
    return bands


def normalised(text: str) -> str:
    """One heading's text as agreement between two layers is measured on."""
    return "".join(text.split()).casefold()


def similarity(left: str, right: str) -> float:
    left_key, right_key = normalised(left), normalised(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    return SequenceMatcher(None, left_key, right_key).ratio()


def box_tuple(box) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    values = (box.x, box.y, box.x2, box.y2)
    if any(value is None for value in values):
        return None
    return tuple(float(value) for value in values)


def intersection_over_union(left, right) -> float:
    """Area shared by two boxes over the area they cover together."""
    width = min(left[2], right[2]) - max(left[0], right[0])
    height = min(left[3], right[3]) - max(left[1], right[1])
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - shared
    return shared / union if union > 0 else 0.0


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


# --- deduplicating the layers of one display unit -----------------------------


def duplicate_paragraphs(titles, config: TitleConfig) -> dict[int, dict]:
    """Which heading paragraphs of one page are a second layer of another.

    ``titles`` are the page's headings as (index, paragraph) pairs. Two of them
    standing on each other and saying the same thing are one display unit drawn
    twice; the one covering more of the page keeps it, and equal area is settled
    by which came first, so the choice does not depend on iteration order.
    """
    suppressed: dict[int, dict] = {}
    for position, (index, paragraph) in enumerate(titles):
        if index in suppressed:
            continue
        left_box = box_tuple(paragraph.box)
        left_text = paragraph_reading_text(paragraph)
        if left_box is None or len(normalised(left_text)) < config.duplicate_min_chars:
            continue
        for other_index, other in titles[position + 1 :]:
            if other_index in suppressed:
                continue
            right_box = box_tuple(other.box)
            if right_box is None:
                continue
            overlap = intersection_over_union(left_box, right_box)
            if overlap < config.duplicate_min_iou:
                continue
            agreement = similarity(left_text, paragraph_reading_text(other))
            if agreement < config.duplicate_min_text_similarity:
                continue
            if _area(right_box) > _area(left_box):
                keeper, dropped = other_index, index
            else:
                keeper, dropped = index, other_index
            suppressed[dropped] = {
                "layer": LAYER_PARAGRAPH,
                "duplicate_of_index": keeper,
                "iou": round(overlap, 4),
                "similarity": round(agreement, 4),
            }
            if dropped == index:
                break
    return suppressed


def duplicate_runs(runs: list[Run], config: TitleConfig) -> tuple[list[Run], list[dict]]:
    """The runs of one heading with its repeated layers dropped.

    Two runs set in one font at one size and saying the same thing are the two
    paints of one display unit: the paragraph finder recovered them as one
    paragraph because they were drawn at one place, and the layout has since put
    them side by side. The earlier run keeps the heading.
    """
    kept: list[Run] = []
    dropped: list[dict] = []
    for run in runs:
        text = run.text
        if len(normalised(text)) < config.duplicate_min_chars:
            kept.append(run)
            continue
        match = None
        for earlier in kept:
            if earlier.style is None or run.style is None:
                continue
            if earlier.style.font_id != run.style.font_id:
                continue
            sizes = (earlier.style.font_size, run.style.font_size)
            if any(size is None for size in sizes):
                continue
            if abs(float(sizes[0]) - float(sizes[1])) > (
                config.duplicate_font_size_tolerance
            ):
                continue
            agreement = similarity(earlier.text, text)
            if agreement >= config.duplicate_min_text_similarity:
                match = (earlier, agreement)
                break
        if match is None:
            kept.append(run)
            continue
        earlier, agreement = match
        dropped.append(
            {
                "layer": LAYER_RUN,
                "run": run.position,
                "duplicate_of_run": earlier.position,
                "similarity": round(agreement, 4),
                "characters": len(run.characters),
            }
        )
    return kept, dropped


# --- laying one heading out again ---------------------------------------------


def _set_runs(paragraph, runs: list[Run]) -> None:
    """Compose the paragraph from unicode runs, which the stage lays out again."""
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    unicode=run.text, pdf_style=run.style
                )
            )
        )
        for run in runs
    ]
    paragraph.unicode = "".join(run.text for run in runs)


def _font_of(fonts, font_id, xobj_id):
    """The font a style resolves to, looked up as the stage looks it up."""
    scoped = fonts.get(xobj_id)
    if isinstance(scoped, dict) and font_id in scoped:
        return scoped[font_id]
    return fonts.get(font_id)


def natural_width(runs: list[Run], typesetting, fonts, xobj_id) -> float | None:
    """How wide the heading is on one line at the size it is set in.

    Measured with the font the stage would map each character to, which is the
    same measurement ``TypesettingUnit`` makes. None where any character cannot
    be measured, in which case the search starts at full size and shrinks.
    """
    total = 0.0
    for run in runs:
        style = run.style
        if style is None or style.font_id is None or style.font_size is None:
            return None
        original = _font_of(fonts, style.font_id, xobj_id)
        if original is None:
            return None
        for character in run.text:
            try:
                mapped = typesetting.font_mapper.map(original, character)
                if mapped is None:
                    return None
                total += mapped.char_lengths(character, float(style.font_size))[0]
            except Exception:  # noqa: BLE001 - an unmeasurable heading is searched for
                return None
    return total


def _render(typesetting, paragraph, page, fonts) -> bool:
    """Lay one paragraph out again in place. False where nothing came out."""
    try:
        typesetting.render_paragraph(paragraph, page, fonts)
    except Exception:  # noqa: BLE001 - a heading that cannot be laid out stands
        logger.warning(
            "title typeset: laying out %s again failed; it is left as it was",
            paragraph.debug_id,
            exc_info=True,
        )
        return False
    return bool(paragraph.pdf_paragraph_composition)


def _fit_single_line(
    typesetting, paragraph, page, fonts, runs, start_scale, config
) -> tuple[bool, float, float]:
    """Shrink until the heading lands on one line. The scale it landed at.

    Returns whether it landed, the scale it landed at or the last one tried, and
    the scale the first estimate asked for, which is what an escalation reports.
    """
    scale = start_scale
    for _attempt in range(config.max_scale_attempts):
        if scale < config.title_min_scale:
            break
        _set_runs(paragraph, runs)
        paragraph.optimal_scale = scale
        if not _render(typesetting, paragraph, page, fonts):
            return False, scale, start_scale
        bands = line_bands(laid_out_characters(paragraph), config.line_band_tolerance)
        if len(bands) <= 1:
            return True, scale, start_scale
        scale *= config.scale_shrink_step
    return False, scale, start_scale


def _restore(page, index: int, snapshot) -> None:
    page.pdf_paragraph[index] = snapshot


def _suppress(paragraph) -> None:
    """Leave a paragraph that renders nothing, without removing the paragraph.

    The composition is what the page is drawn from, so emptying it is the whole
    of not being drawn. ``unicode`` goes with it because a paragraph that shows
    nothing says nothing: the writer logs an unformatted paragraph when a
    composition is empty beside a text, and a detector reading the fallback
    would otherwise measure a line the reader cannot see.
    """
    paragraph.pdf_paragraph_composition = []
    paragraph.unicode = ""


def process_page(page, label: int, typesetting, config: TitleConfig) -> list[dict]:
    """Apply the policy to every heading of one page. One record per heading."""
    titles = [
        (index, paragraph)
        for index, paragraph in enumerate(page.pdf_paragraph or ())
        if config.is_title(paragraph)
    ]
    if not titles:
        return []
    fonts = page_font_map(page, typesetting.font_mapper)
    suppressed = duplicate_paragraphs(titles, config)
    records = []
    for index, paragraph in titles:
        reference = paragraph_reference(label, index)
        if index in suppressed:
            finding = suppressed[index]
            _suppress(paragraph)
            records.append(
                {
                    "page": label,
                    "reference": reference,
                    "disposition": DISPOSITION_UNCHANGED,
                    "suppressed": True,
                    "duplicates": [
                        {
                            "layer": finding["layer"],
                            "duplicate_of": paragraph_reference(
                                label, finding["duplicate_of_index"]
                            ),
                            "iou": finding["iou"],
                            "similarity": finding["similarity"],
                        }
                    ],
                }
            )
            continue
        records.append(
            _process_title(page, label, index, paragraph, typesetting, fonts, config)
        )
    return records


def _process_title(
    page, label: int, index: int, paragraph, typesetting, fonts, config
) -> dict:
    """One heading: its layers deduplicated, its indent closed, its line found."""
    reference = paragraph_reference(label, index)
    characters = laid_out_characters(paragraph)
    record = {
        "page": label,
        "reference": reference,
        "disposition": DISPOSITION_UNCHANGED,
        "suppressed": False,
        "duplicates": [],
    }
    if not characters:
        return record

    runs = style_runs(characters)
    kept, dropped = duplicate_runs(runs, config)
    record["duplicates"] = [
        {
            "layer": item["layer"],
            "duplicate_of": f"{reference}~{item['duplicate_of_run']}",
            "run": f"{reference}~{item['run']}",
            "similarity": item["similarity"],
            "characters": item["characters"],
        }
        for item in dropped
    ]
    bands_before = line_bands(characters, config.line_band_tolerance)
    indent = bool(paragraph.first_line_indent)
    record["lines_before"] = len(bands_before)
    record["indent_closed"] = indent
    if not dropped and len(bands_before) <= 1 and not indent:
        # Nothing to answer for: one line, no indent, one layer. A heading the
        # policy has no work on is not laid out again, so its rendering is the
        # one the stage produced rather than one this pass reproduced.
        return record

    snapshot = copy.deepcopy(paragraph)
    paragraph.first_line_indent = False
    box = box_tuple(paragraph.box)
    usable = 0.0 if box is None else (box[2] - box[0]) * config.single_line_width_ratio
    measured = natural_width(kept, typesetting, fonts, paragraph.xobj_id)
    if measured and usable > 0:
        start = min(1.0, usable / measured)
    else:
        start = 1.0
    record["required_scale"] = round(start, 4)

    landed, scale, _asked = _fit_single_line(
        typesetting, paragraph, page, fonts, kept, start, config
    )
    if landed:
        record["disposition"] = DISPOSITION_SINGLE_LINE
        record["scale"] = round(scale, 4)
        record["lines_after"] = 1
        return record

    record["disposition"] = DISPOSITION_FLOOR
    record["floor"] = config.title_min_scale
    record["on_floor"] = config.on_floor
    if dropped:
        # The deduplication stands on its own: a heading shown once and wrapped
        # is better than one shown twice, and the wrapping is what the stage
        # would have produced for the text that is left.
        _set_runs(paragraph, kept)
        paragraph.optimal_scale = snapshot.optimal_scale or 1.0
        if not _render(typesetting, paragraph, page, fonts):
            _restore(page, index, snapshot)
            record["duplicates"] = []
            record["restored"] = True
    else:
        _restore(page, index, snapshot)
        record["restored"] = True
    after = line_bands(
        laid_out_characters(page.pdf_paragraph[index]), config.line_band_tolerance
    )
    record["lines_after"] = len(after)
    return record


def as_record(config: TitleConfig, records: list[dict], pages: int) -> dict:
    escalations = [
        {
            "page": item["page"],
            "reference": item["reference"],
            "required_scale": item.get("required_scale"),
            "floor": item.get("floor"),
            "lines_after": item.get("lines_after"),
        }
        for item in records
        if item["disposition"] == DISPOSITION_FLOOR
        and config.on_floor == FLOOR_ESCALATE
    ]
    duplicates = [
        {"page": item["page"], "reference": item["reference"], **finding}
        for item in records
        for finding in item["duplicates"]
    ]
    return {
        "switch": SWITCH,
        "window_switch": WINDOW_SWITCH,
        "labels": list(config.labels),
        "on_floor": config.on_floor,
        "title_min_scale": config.title_min_scale,
        "pages": pages,
        "totals": {
            "titles": len(records),
            "single_line": sum(
                1
                for item in records
                if item["disposition"] == DISPOSITION_SINGLE_LINE
            ),
            "unchanged": sum(
                1 for item in records if item["disposition"] == DISPOSITION_UNCHANGED
            ),
            "floor_reached": sum(
                1 for item in records if item["disposition"] == DISPOSITION_FLOOR
            ),
            "suppressed_paragraphs": sum(
                1 for item in records if item.get("suppressed")
            ),
            "duplicate_layers": len(duplicates),
            "escalations": len(escalations),
        },
        "titles": records,
        "duplicates": duplicates,
        "escalations": escalations,
    }


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def apply(translation_config, docs) -> dict | None:
    """Set every heading of one laid out document. None where the switch is down.

    Returns the record it wrote, so a caller that already holds the document can
    assert about the pass without reading the sidecar back.
    """
    if not enabled(translation_config):
        return None
    config = load_title_config()
    typesetting = Typesetting(translation_config)
    records: list[dict] = []
    pages = hitl.labeled_pages(docs)
    for label, page in pages:
        records.extend(process_page(page, label, typesetting, config))
    record = as_record(config, records, len(pages))
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    write_report(working_dir, record)
    logger.debug(
        "title typeset: %d heading(s), %d set on one line, %d layer(s) dropped",
        record["totals"]["titles"],
        record["totals"]["single_line"],
        record["totals"]["duplicate_layers"],
    )
    return record
