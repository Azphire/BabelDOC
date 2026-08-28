"""A written unit short enough that the length floor never offered it a request.

What is broken here
-------------------

``TranslationConfig.min_text_length`` is five, and a paragraph shorter than that
has no request built for it anywhere in the pipeline. That is the right default.
Most of what is that short is a folio, a rule number, or a piece of a word the
paragraph finder broke off, and sending any of those to a translation engine
produces a translation of half a word.

Some of it is not. On the contents page of a magazine translated out of its own
language, the seven section labels -- two characters each -- come out in the
source script in the middle of an otherwise translated page, and the F2 review
found them one by one. They are whole written units. Nothing about them wants
the floor except their length.

So the floor gains a shape exception, and the exception is what this module is.

Why it is not the floor that changed
------------------------------------

The floor is upstream, and it is read once per paragraph in the middle of a loop
this project does not own. Lowering it would admit every short paragraph on
every page, which is exactly the outcome the floor exists to prevent, and there
is no upstream hook between the floor and the batch to put a shape test in.

So the admitted paragraphs are translated here instead, before the per paragraph
machinery runs, through the same prompt builder a page batch uses -- so a unit
carries the run's standing instruction, the run's glossaries and its article's
brief exactly as every other request does -- and are then claimed, so the
paragraph path leaves them alone. This is the same shape the chain pass has
taken since B5 and it reuses that pass's two ends of the pipeline,
``pre_translate_paragraph`` and ``post_translate_paragraph``, rather than
writing a second way in and out.

What a shape is
---------------

Two, both declared in ``configs/short_unit.json``, and a paragraph has to hold
one of them and be solitary.

*Solitary* is the whole of the distinction, and it is the same signal the
fragment stitch's horizontal rule reads. A section label sits alone on its line
band with a column's width between it and the next thing printed. A piece of a
broken word sits hard against the piece that follows it: the gap between ``Wh``
and ``e`` is the gap between two letters. So a paragraph with anything within a
declared multiple of its own font size, horizontally, on its band, is not
admitted -- and a paragraph in the next column of the same band, two hundred
points away, is not within it.

Beyond that, a paragraph the source audit placed as a broken word is never
admitted however solitary its box looks. The audit reads the page through an
extractor that shares no code with the pipeline, and a paragraph whose
characters are part of a word that reading holds whole is a fragment whatever
its geometry says. Those belong to the fragment stitch, which is the repair they
want.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il.utils.paragraph_helper import is_cid_paragraph
from babeldoc.format.pdf.document_il.utils.paragraph_helper import (
    is_placeholder_only_paragraph,
)
from babeldoc.format.pdf.document_il.utils.paragraph_helper import (
    is_pure_numeric_paragraph,
)
from babeldoc.magazine import source_audit
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("short_unit.json")
REPORT_NAME = "short_unit.report.json"

SWITCH_KEY = "switch"
SHAPES_KEY = "shapes"

SHAPE_LABEL = "label_shaped"
SHAPE_NAME = "name_shaped"

# One request holds several units, and the reply names them by these ids, which
# is the envelope every other request of this pipeline is wrapped in.
_ID_KEY = "id"
_INPUT_KEY = "input"
_OUTPUT_KEY = "output"

# What a personal name is written like in a Latin script: capitalised words,
# each of which may carry an internal apostrophe or hyphen, with the lowercase
# particles a European surname is built with allowed between them. The pattern
# is over the shape of the writing and names no person, place or publication.
_NAME_WORD = r"(?:[A-Z][A-Za-z]*(?:['’\-][A-Za-z]+)*)"
_NAME_PARTICLE = r"(?:de|del|della|der|van|von|da|di|du|la|le|bin|ibn|al)"
_NAME_PATTERN = re.compile(
    rf"^{_NAME_WORD}(?:\s+(?:{_NAME_PARTICLE}\s+)?{_NAME_WORD})*$"
)


class ShortUnitError(ConfigError):
    """Raised when the short unit configuration is unusable."""


@dataclass(frozen=True)
class ShortUnitConfig:
    shape_exception_floor: int
    short_label_max_chars: int
    min_letters: int
    adjacent_gap_ratio: float
    name_min_words: int
    name_max_words: int
    batch_max_units: int
    switch: str
    shapes: tuple[str, ...]


@lru_cache(maxsize=2)
def load_short_unit_config(path: str | None = None) -> ShortUnitConfig:
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    switch = raw.get(SWITCH_KEY)
    if not isinstance(switch, str) or not switch or switch.strip() != switch:
        raise ShortUnitError(
            f"{config_path.name}: {SWITCH_KEY} must name the run attribute the "
            f"pass is read from"
        )
    try:
        parameters = dict(
            validate_bounded_config(
                {key: value for key, value in raw.items() if key != SWITCH_KEY},
                config_path,
            )
        )
    except ConfigError as exc:
        raise ShortUnitError(str(exc)) from exc
    shapes = tuple(parameters.get(SHAPES_KEY, ()))
    if set(shapes) != {SHAPE_LABEL, SHAPE_NAME}:
        raise ShortUnitError(
            f"{config_path.name}: {SHAPES_KEY} is {sorted(shapes)}, and this "
            f"module admits {sorted((SHAPE_LABEL, SHAPE_NAME))}"
        )
    if int(parameters["name_min_words"]) > int(parameters["name_max_words"]):
        raise ShortUnitError(
            f"{config_path.name}: name_min_words is above name_max_words, so no "
            f"word count could satisfy both"
        )
    return ShortUnitConfig(
        shape_exception_floor=int(parameters["shape_exception_floor"]),
        short_label_max_chars=int(parameters["short_label_max_chars"]),
        min_letters=int(parameters["min_letters"]),
        adjacent_gap_ratio=float(parameters["adjacent_gap_ratio"]),
        name_min_words=int(parameters["name_min_words"]),
        name_max_words=int(parameters["name_max_words"]),
        batch_max_units=int(parameters["batch_max_units"]),
        switch=switch,
        shapes=shapes,
    )


def enabled(translation_config, config: ShortUnitConfig | None = None) -> bool:
    config = load_short_unit_config() if config is None else config
    return bool(getattr(translation_config, config.switch, False))


# --- the shape tests --------------------------------------------------------


def font_size_of(paragraph) -> float | None:
    """The size the paragraph's first character is set at.

    Read through the shared character walk rather than off one kind of
    composition: a paragraph is recomposed as it moves down the pipeline, and
    this pass runs at the far end of it, where a paragraph holds runs of one
    style rather than the lines the finder left. The paragraph's own base style
    answers where no character does.
    """
    for character in paragraph_characters(paragraph):
        style = getattr(character, "pdf_style", None)
        size = getattr(style, "font_size", None) if style else None
        if size:
            return float(size)
    style = getattr(paragraph, "pdf_style", None)
    size = getattr(style, "font_size", None) if style else None
    return float(size) if size else None


def _box(item):
    box = getattr(item, "box", None)
    if box is None:
        return None
    try:
        return (float(box.x), float(box.y), float(box.x2), float(box.y2))
    except (AttributeError, TypeError, ValueError):
        return None


def is_solitary(index: int, paragraphs: list, config: ShortUnitConfig) -> bool:
    """Whether nothing else is printed beside this paragraph on its line.

    Measured as a multiple of the paragraph's own font size, so the same
    judgement is made at any size, and against the horizontal gap alone: two
    boxes are beside each other when they share a band and nearly touch.
    """
    own = _box(paragraphs[index])
    if own is None:
        return False
    size = font_size_of(paragraphs[index])
    if not size:
        return False
    reach = size * config.adjacent_gap_ratio
    for other, paragraph in enumerate(paragraphs):
        if other == index:
            continue
        box = _box(paragraph)
        if box is None or not (paragraph.unicode or "").strip():
            continue
        if min(own[3], box[3]) - max(own[1], box[1]) <= 0:
            continue
        gap = max(own[0], box[0]) - min(own[2], box[2])
        if gap <= reach:
            return False
    return True


def shape_of(text: str, config: ShortUnitConfig) -> str | None:
    """Which declared shape a text holds, or None for neither."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    if sum(1 for char in stripped if char.isalpha()) < config.min_letters:
        return None
    words = stripped.split()
    if config.name_min_words <= len(
        words
    ) <= config.name_max_words and _NAME_PATTERN.match(stripped):
        return SHAPE_NAME
    if len(stripped) <= config.short_label_max_chars:
        return SHAPE_LABEL
    return None


@dataclass
class Unit:
    """One admitted paragraph, and why it was admitted."""

    page_index: int
    page_label: int
    index: int
    paragraph: object
    shape: str
    source: str = ""
    translated: str = ""
    translate_input: object = None
    tracker: object = None
    identity_skipped: bool | None = None

    def as_record(self) -> dict:
        return {
            "page": self.page_label,
            "paragraph": f"p{self.page_label}#{self.index}",
            "debug_id": getattr(self.paragraph, "debug_id", None),
            "shape": self.shape,
            "chars": len(self.source or ""),
            "source": self.source,
            "identity_skipped": self.identity_skipped,
        }


def candidates(
    docs,
    minimum: int,
    config: ShortUnitConfig,
    fractured: dict[int, set[int]] | None = None,
) -> list[Unit]:
    """Every paragraph the exception admits, in document order.

    ``minimum`` is the run's own floor: a paragraph at or above it needs no
    exception and is left to the path that already reaches it.
    """
    found: list[Unit] = []
    for page_index, page in enumerate(docs.page or ()):
        paragraphs = list(page.pdf_paragraph or ())
        label = page_index + 1
        broken = (fractured or {}).get(label, set())
        for index, paragraph in enumerate(paragraphs):
            text = paragraph.unicode
            if text is None or getattr(paragraph, "debug_id", None) is None:
                continue
            length = len(text)
            if not config.shape_exception_floor <= length < minimum:
                continue
            # The other three tests the page batch applies below the floor. A
            # folio, a paragraph drawn in an unmapped encoding and a paragraph
            # holding only a formula placeholder are all things no request is
            # built for at any length, and the exception is to the floor alone.
            if (
                is_cid_paragraph(paragraph)
                or is_pure_numeric_paragraph(paragraph)
                or is_placeholder_only_paragraph(paragraph)
            ):
                continue
            if index in broken:
                continue
            shape = shape_of(text, config)
            if shape is None or shape not in config.shapes:
                continue
            if not is_solitary(index, paragraphs, config):
                continue
            found.append(
                Unit(
                    page_index=page_index,
                    page_label=label,
                    index=index,
                    paragraph=paragraph,
                    shape=shape,
                )
            )
    return found


def fractured_paragraphs(translation_config, docs) -> dict[int, set[int]]:
    """Which paragraphs the source audit placed as pieces of a broken word.

    Empty where the audit cannot be run, and an empty answer admits nothing it
    would otherwise have refused only because there is nothing to refuse with:
    the caller treats a page with no audit as a page with no fragments, which is
    the same page the stitch treats that way.
    """
    pdf = getattr(translation_config, "input_file", None)
    if not pdf or not Path(pdf).exists():
        return {}
    config = source_audit.load_audit_config()
    broken: dict[int, set[int]] = {}
    for page_index, page in enumerate(docs.page or ()):
        label = page_index + 1
        words = source_audit.independent_words(Path(pdf), page_index)
        for item in source_audit.audit_page(page, words, label, config):
            if item["class"] == source_audit.CLASS_TRUE_FRACTURE:
                broken.setdefault(label, set()).add(
                    int(item["paragraph"].split("#")[1])
                )
    return broken


# --- the pass ---------------------------------------------------------------


def prepare(translator, paragraph, tracker, page_font_map, xobj_font_map):
    """The pipeline's own translate input for one paragraph, floor not applied.

    ``ILTranslator.pre_translate_paragraph`` is the method every other path uses
    and it would be used here too, but it applies the length floor itself and
    returns nothing for a paragraph below it -- which is every paragraph this
    pass exists for. So the two steps it takes before that test are taken here:
    the same ``get_translate_input`` builds the same input, and the same tracker
    fields are set from it, so a unit is recorded exactly as a batch member is.
    Nothing else about it differs, and the floor is the one thing not repeated.

    Returns ``(None, None)`` for the cases that method also refuses, which are
    refusals about what a paragraph is rather than about how long it is.
    """
    if paragraph.vertical:
        return None, None
    tracker.set_pdf_unicode(paragraph.unicode)
    if paragraph.xobj_id in xobj_font_map:
        page_font_map = xobj_font_map[paragraph.xobj_id]
    il_translator = translator.il_translator
    disable_rich_text = il_translator.translation_config.disable_rich_text_translate
    if not il_translator.support_llm_translate:
        disable_rich_text = True
    translate_input = il_translator.get_translate_input(
        paragraph, page_font_map, disable_rich_text
    )
    if not translate_input:
        return None, None
    tracker.set_input(translate_input.unicode)
    tracker.set_placeholders(translate_input.placeholders)
    tracker.set_original_placeholders(
        getattr(translate_input, "original_placeholder_tokens", None),
    )
    return translate_input.unicode, translate_input


@dataclass
class ShortUnitPlan:
    """Every admitted unit of one document, translated and waiting to be written."""

    units: list[Unit] = field(default_factory=list)
    refused: list[dict] = field(default_factory=list)
    requests: int = 0
    enabled: bool = False

    def claimed(self) -> set[int]:
        return {id(unit.paragraph) for unit in self.units}


def _batches(units: list[Unit], config: ShortUnitConfig) -> list[list[Unit]]:
    """One request per page, split where a page holds more than a request should.

    Batched by page because a request carries its page's article brief, and a
    brief belongs to the page it describes.
    """
    batches: list[list[Unit]] = []
    for page_index in sorted({unit.page_index for unit in units}):
        of_page = [unit for unit in units if unit.page_index == page_index]
        for start in range(0, len(of_page), config.batch_max_units):
            batches.append(of_page[start : start + config.batch_max_units])
    return batches


def plan(
    translator,
    docs,
    tracker,
    article_context=None,
    config=None,
    excluded_paragraph_ids: frozenset[int] = frozenset(),
) -> ShortUnitPlan:
    """Translate every admitted unit, writing nothing into the document yet."""
    config = load_short_unit_config() if config is None else config
    result = ShortUnitPlan(enabled=True)
    translation_config = translator.translation_config
    minimum = int(getattr(translation_config, "min_text_length", 0) or 0)
    units = candidates(
        docs, minimum, config, fractured_paragraphs(translation_config, docs)
    )
    units = [unit for unit in units if id(unit.paragraph) not in excluded_paragraph_ids]
    if not units:
        return result

    pages = list(docs.page or ())
    prepared: list[Unit] = []
    # One tracking level per page, opened once and reused, so a unit is filed
    # under the page it stands on exactly as a batch of that page is.
    page_trackers: dict[int, object] = {}
    for unit in units:
        page = pages[unit.page_index]
        page_font_map, xobj_font_map = translator._build_font_maps(page)
        page_tracker = page_trackers.get(unit.page_index)
        if page_tracker is None:
            page_tracker = tracker.new_page()
            page_trackers[unit.page_index] = page_tracker
        unit_tracker = page_tracker.new_paragraph()
        text, translate_input = prepare(
            translator, unit.paragraph, unit_tracker, page_font_map, xobj_font_map
        )
        if text is None or translate_input is None:
            result.refused.append({**unit.as_record(), "reason": "no_text"})
            continue
        if translate_input.placeholders:
            result.refused.append({**unit.as_record(), "reason": "placeholder_bearing"})
            continue
        unit.source = text
        unit.translate_input = translate_input
        unit.tracker = unit_tracker
        prepared.append(unit)

    shared = translation_config.shared_context_cross_split_part
    for batch in _batches(prepared, config):
        json_input = [
            {
                _ID_KEY: position,
                _INPUT_KEY: unit.source,
                "layout_label": getattr(unit.paragraph, "layout_label", None),
            }
            for position, unit in enumerate(batch)
        ]
        brief = (
            article_context.brief_for_page_index(batch[0].page_index)
            if article_context is not None
            else None
        )
        extra = {"article_brief": brief} if brief else {}
        prompt = translator._build_llm_prompt(
            json_input_str=json.dumps(json_input, ensure_ascii=False, indent=2),
            title_paragraph=shared.first_paragraph,
            local_title_paragraph=shared.recent_title_paragraph,
            batch_text_for_glossary_matching="\n".join(unit.source for unit in batch),
            **extra,
        )
        trace = getattr(translator, "run_trace", None)
        trace_request_id = None
        if trace is not None:
            references = [trace.source_ref_for(unit.paragraph) for unit in batch]
            if any(reference is None for reference in references):
                raise ValueError("short unit batch contains an unfrozen source")
            trace_request_id = trace.open_request(
                "short_unit_batch",
                references,
                "\n".join(unit.source for unit in batch),
                translator._trace_prompt_config(prompt),
            )
        llm_trackers = [unit.tracker.new_llm_translate_tracker() for unit in batch]
        for llm_tracker in llm_trackers:
            llm_tracker.set_input(prompt)
        try:
            if trace_request_id is not None:
                trace.record_translator_call(trace_request_id)
            raw = translator.translate_engine.llm_translate(
                prompt,
                rate_limit_params={
                    "paragraph_token_count": translator.calc_token_count(
                        "\n".join(unit.source for unit in batch)
                    ),
                    "request_json_mode": True,
                },
            )
        except Exception as error:  # the engine and its output are both foreign
            if trace_request_id is not None:
                trace.fail_request(trace_request_id, str(error))
            logger.warning("short unit: a batch could not be translated: %s", error)
            for unit in batch:
                result.refused.append(
                    {**unit.as_record(), "reason": "translation_unavailable"}
                )
            continue
        result.requests += 1
        for llm_tracker in llm_trackers:
            llm_tracker.set_output(raw)
        try:
            parsed = json.loads(translator._clean_json_output(raw.strip()))
        except ValueError as error:
            if trace_request_id is not None:
                trace.fail_request(trace_request_id, str(error))
            logger.warning("short unit: a reply could not be read: %s", error)
            for unit in batch:
                result.refused.append(
                    {**unit.as_record(), "reason": "reply_unreadable"}
                )
            continue
        if isinstance(parsed, dict):
            parsed = [parsed]
        answers = {
            int(item[_ID_KEY]): item.get(_OUTPUT_KEY, item.get(_INPUT_KEY))
            for item in parsed
            if isinstance(item, dict) and _ID_KEY in item
        }
        trace_fragments = []
        for position, unit in enumerate(batch):
            answer = answers.get(position)
            if not isinstance(answer, str) or not answer.strip():
                result.refused.append({**unit.as_record(), "reason": "no_answer"})
                continue
            unit.translated = answer
            result.units.append(unit)
            if trace_request_id is not None:
                trace_fragments.append(
                    (trace.source_ref_for(unit.paragraph), answer)
                )
        if trace_request_id is not None:
            if trace_fragments:
                trace.complete_request_with_fragments(
                    trace_request_id, trace_fragments
                )
            else:
                trace.fail_request(trace_request_id, "batch_returned_no_answers")
    return result


def apply(translator, plan_result: ShortUnitPlan, pbar=None) -> None:
    """Write every translated unit back through the pipeline's own writer.

    The writer reports whether it rewrote the paragraph. A unit whose reply says
    what its source said -- a label that reads the same in both languages -- is
    left standing rather than recomposed, and which of the two happened is
    recorded, because the difference is invisible in the text and visible on the
    page.
    """
    for unit in plan_result.units:
        rewritten = translator.il_translator.post_translate_paragraph(
            unit.paragraph, unit.tracker, unit.translate_input, unit.translated
        )
        unit.identity_skipped = rewritten is False
        translator.total_count += 1
        translator.ok_count += 1
        if pbar:
            pbar.advance(1)


def write_report(translation_config, plan_result: ShortUnitPlan, config=None) -> Path:
    config = load_short_unit_config() if config is None else config
    record = {
        "switch": config.switch,
        "enabled": plan_result.enabled,
        "shape_exception_floor": config.shape_exception_floor,
        "short_label_max_chars": config.short_label_max_chars,
        "adjacent_gap_ratio": config.adjacent_gap_ratio,
        "min_text_length": int(getattr(translation_config, "min_text_length", 0) or 0),
        "counts": {
            "admitted": len(plan_result.units),
            "refused": len(plan_result.refused),
            "requests": plan_result.requests,
            "by_shape": {
                shape: sum(1 for unit in plan_result.units if unit.shape == shape)
                for shape in config.shapes
            },
        },
        "units": [
            {**unit.as_record(), "translated": unit.translated}
            for unit in plan_result.units
        ],
        "refused_units": plan_result.refused,
    }
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    return path
