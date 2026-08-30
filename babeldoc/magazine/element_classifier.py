"""Project-level magazine paragraph role classification.

The upstream layout model supplies useful text classes, but it does not expose
magazine-specific bylines or pull quotes.  This stage keeps the frozen IL
schema intact: it derives a closed role vocabulary, records the derivation in
one sidecar, and writes only the operational label back to ``layout_label``.
All decisions use page policy, relative geometry, typography, and shared CJK /
Latin punctuation evidence.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import line_split
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("element_classification.json")
REPORT_NAME = "element_classification.report.json"

ROLE_TITLE = "title"
ROLE_BODY = "body"
ROLE_CAPTION = "caption"
ROLE_PULL_QUOTE = "pull_quote"
ROLE_BYLINE = "byline"
ROLE_OTHER_DISPLAY = "other_display"
ROLES = frozenset(
    {
        ROLE_TITLE,
        ROLE_BODY,
        ROLE_CAPTION,
        ROLE_PULL_QUOTE,
        ROLE_BYLINE,
        ROLE_OTHER_DISPLAY,
    }
)

_REQUIRED_PARAMETERS = frozenset(
    {
        "title_labels",
        "body_labels",
        "caption_labels",
        "excluded_labels",
        "article_opener_kinds",
        "quote_openers",
        "quote_closers",
        "sentence_enders",
        "opener_title_band_ratio",
        "top_title_band_ratio",
        "body_region_top_ratio",
        "body_region_bottom_ratio",
        "main_title_min_font_ratio",
        "main_cohort_font_tolerance_ratio",
        "main_cohort_top_tolerance_ratio",
        "continuation_font_tolerance_ratio",
        "continuation_line_delta_max",
        "byline_max_title_gap_ratio",
        "byline_max_line_count",
        "byline_max_width_ratio",
        "byline_max_area_ratio",
        "byline_max_title_font_ratio",
        "pull_quote_min_font_ratio",
        "pull_quote_max_line_count",
        "pull_quote_max_width_ratio",
        "pull_quote_max_area_ratio",
        "sentence_min_characters",
        "line_height_factor",
    }
)


class ElementClassificationError(RuntimeError):
    """Raised when element classification is reused or cannot be reported."""


@lru_cache(maxsize=8)
def load_element_config(path: str | None = None) -> dict:
    """Load and validate the language-neutral element thresholds."""
    source = CONFIG_PATH if path is None else Path(path)
    with source.open(encoding="utf-8") as stream:
        raw = json.load(stream)
    parameters = validate_bounded_config(raw, source)
    missing = sorted(_REQUIRED_PARAMETERS - set(parameters))
    if missing:
        raise ConfigError(f"{source.name}: missing parameters {missing}")
    unknown = sorted(set(parameters) - _REQUIRED_PARAMETERS)
    if unknown:
        raise ConfigError(f"{source.name}: unknown parameters {unknown}")
    if parameters["body_region_top_ratio"] >= parameters["body_region_bottom_ratio"]:
        raise ConfigError(f"{source.name}: body region is empty or inverted")
    return parameters


@dataclass(slots=True)
class _Element:
    paragraph: il_version_1.PdfParagraph
    source_ref: str
    source_label: str
    bbox: tuple[float, float, float, float] | None
    text: str
    font_size: float | None
    font_id: str | None
    line_count: int
    width_ratio: float | None
    area_ratio: float | None
    top_ratio: float | None
    bottom_ratio: float | None
    font_ratio: float | None = None
    quote_shape: bool = False
    terminal_punctuation: bool = False
    sentence_shape: bool = False


def _box_record(box) -> tuple[float, float, float, float] | None:
    if box is None or None in (box.x, box.y, box.x2, box.y2):
        return None
    low_x, high_x = sorted((float(box.x), float(box.x2)))
    low_y, high_y = sorted((float(box.y), float(box.y2)))
    if low_x == high_x or low_y == high_y:
        return None
    return low_x, low_y, high_x, high_y


def _page_frame(page) -> tuple[float, float, float, float] | None:
    for holder in (getattr(page, "cropbox", None), getattr(page, "mediabox", None)):
        frame = _box_record(None if holder is None else holder.box)
        if frame is not None:
            return frame
    return None


def _paragraph_text(paragraph, characters) -> str:
    if paragraph.unicode is not None:
        return str(paragraph.unicode)
    return line_split.characters_text(characters)


def _style_candidates(paragraph, characters):
    for character in characters:
        style = getattr(character, "pdf_style", None)
        if style is not None:
            yield style
    for composition in paragraph.pdf_paragraph_composition or ():
        kind = line_split.composition_kind(composition)
        if kind is None:
            continue
        holder = getattr(composition, kind)
        style = getattr(holder, "pdf_style", None)
        if style is not None:
            yield style
    if paragraph.pdf_style is not None:
        yield paragraph.pdf_style


def _paragraph_typography(paragraph, characters) -> tuple[float | None, str | None]:
    sizes = []
    font_ids = []
    for style in _style_candidates(paragraph, characters):
        size = getattr(style, "font_size", None)
        if size is not None and float(size) > 0:
            sizes.append(float(size))
        font_id = getattr(style, "font_id", None)
        if font_id:
            font_ids.append(str(font_id))
    size = statistics.median(sizes) if sizes else None
    font_id = statistics.mode(font_ids) if font_ids else None
    return size, font_id


def _line_count(paragraph, characters, font_size, bbox, parameters) -> int:
    if characters:
        recovered = line_split.recover_lines(
            characters,
            line_split.load_line_split_config(),
        )
        if recovered:
            return len(recovered)
    text = (paragraph.unicode or "").strip()
    explicit = len(text.splitlines()) if text else 0
    if explicit > 1:
        return explicit
    if bbox is not None and font_size is not None and font_size > 0:
        height = bbox[3] - bbox[1]
        estimate = round(height / (font_size * parameters["line_height_factor"]))
        return max(1, estimate)
    return 1 if text else 0


def _relative_geometry(bbox, frame):
    if bbox is None or frame is None:
        return None, None, None, None
    width = frame[2] - frame[0]
    height = frame[3] - frame[1]
    if width <= 0 or height <= 0:
        return None, None, None, None
    width_ratio = (bbox[2] - bbox[0]) / width
    area_ratio = width_ratio * ((bbox[3] - bbox[1]) / height)
    top_ratio = (frame[3] - bbox[3]) / height
    bottom_ratio = (frame[3] - bbox[1]) / height

    def clamp(value):
        return max(0.0, min(1.0, value))

    return (
        clamp(width_ratio),
        clamp(area_ratio),
        clamp(top_ratio),
        clamp(bottom_ratio),
    )


def _text_shapes(text: str, line_count: int, parameters) -> tuple[bool, bool, bool]:
    stripped = text.strip()
    if not stripped:
        return False, False, False
    quote_shape = (
        stripped[0] in parameters["quote_openers"]
        or stripped[-1] in parameters["quote_closers"]
    )
    terminal_text = stripped.rstrip("".join(parameters["quote_closers"]))
    terminal = (
        bool(terminal_text) and terminal_text[-1] in parameters["sentence_enders"]
    )
    character_count = sum(not character.isspace() for character in stripped)
    sentence_shape = (
        quote_shape
        or terminal
        or (
            line_count >= 2 and character_count >= parameters["sentence_min_characters"]
        )
    )
    return quote_shape, terminal, sentence_shape


def _element(
    page_position, paragraph_position, paragraph, frame, parameters
) -> _Element:
    characters = line_split.paragraph_characters(paragraph)
    bbox = _box_record(paragraph.box)
    text = _paragraph_text(paragraph, characters)
    font_size, font_id = _paragraph_typography(paragraph, characters)
    line_count = _line_count(paragraph, characters, font_size, bbox, parameters)
    width_ratio, area_ratio, top_ratio, bottom_ratio = _relative_geometry(bbox, frame)
    quote_shape, terminal, sentence_shape = _text_shapes(text, line_count, parameters)
    return _Element(
        paragraph=paragraph,
        source_ref=f"p{page_position + 1}#{paragraph_position}",
        source_label=str(paragraph.layout_label or "").strip(),
        bbox=bbox,
        text=text,
        font_size=font_size,
        font_id=font_id,
        line_count=line_count,
        width_ratio=width_ratio,
        area_ratio=area_ratio,
        top_ratio=top_ratio,
        bottom_ratio=bottom_ratio,
        quote_shape=quote_shape,
        terminal_punctuation=terminal,
        sentence_shape=sentence_shape,
    )


def _body_median(elements, parameters) -> float | None:
    # Weight a body style by the number of source lines it paints.  A single
    # display quote may arrive under a body label, but it must not redefine the
    # page's running-text baseline merely because the page has only one other
    # paragraph object.
    sizes = [
        item.font_size
        for item in elements
        if item.source_label in parameters["body_labels"]
        and item.text.strip()
        and item.font_size is not None
        for _line in range(max(1, item.line_count))
    ]
    return statistics.median(sizes) if sizes else None


def _style_continuity(current: _Element, previous: _Element, parameters) -> bool:
    if current.font_size is None or previous.font_size is None:
        return False
    denominator = max(current.font_size, previous.font_size)
    size_delta = abs(current.font_size - previous.font_size) / denominator
    line_delta = abs(current.line_count - previous.line_count)
    return (
        size_delta <= parameters["continuation_font_tolerance_ratio"]
        and line_delta <= parameters["continuation_line_delta_max"]
    )


def _main_title_cohort(
    elements: list[_Element],
    page_kind: str | None,
    previous_main: _Element | None,
    parameters,
) -> list[_Element]:
    candidates = []
    for item in elements:
        if item.source_label not in parameters["title_labels"]:
            continue
        if item.top_ratio is None:
            continue
        in_opener_zone = (
            page_kind in parameters["article_opener_kinds"]
            and item.top_ratio <= parameters["opener_title_band_ratio"]
        )
        continues_previous = (
            previous_main is not None
            and item.top_ratio <= parameters["top_title_band_ratio"]
            and _style_continuity(item, previous_main, parameters)
        )
        has_hierarchy = (
            item.font_ratio is None
            or item.font_ratio >= parameters["main_title_min_font_ratio"]
        )
        if (in_opener_zone or continues_previous) and has_hierarchy:
            candidates.append(item)
    if not candidates:
        return []

    strongest = max(
        candidates,
        key=lambda item: (
            item.font_size or 0.0,
            item.area_ratio or 0.0,
            -(item.top_ratio or 0.0),
            item.width_ratio or 0.0,
            item.source_ref,
        ),
    )
    cohort = []
    for item in candidates:
        if item.font_size is None or strongest.font_size is None:
            same_level = item is strongest
        else:
            same_level = (
                abs(item.font_size - strongest.font_size) / strongest.font_size
                <= parameters["main_cohort_font_tolerance_ratio"]
            )
        same_band = (
            item.top_ratio is not None
            and strongest.top_ratio is not None
            and abs(item.top_ratio - strongest.top_ratio)
            <= parameters["main_cohort_top_tolerance_ratio"]
        )
        if same_level and same_band:
            cohort.append(item)
    return cohort


def _distance_below_title(item: _Element, title: _Element, frame) -> float | None:
    if item.bbox is None or title.bbox is None or frame is None:
        return None
    height = frame[3] - frame[1]
    if height <= 0:
        return None
    item_centre = (item.bbox[1] + item.bbox[3]) / 2.0
    title_centre = (title.bbox[1] + title.bbox[3]) / 2.0
    if item_centre >= title_centre:
        return None
    return max(0.0, title.bbox[1] - item.bbox[3]) / height


def _nearest_title_gap(
    item, main_titles, frame
) -> tuple[float | None, _Element | None]:
    measured = [
        (gap, title)
        for title in main_titles
        if (gap := _distance_below_title(item, title, frame)) is not None
    ]
    return min(measured, key=lambda pair: pair[0]) if measured else (None, None)


def _in_body_region(item: _Element, parameters) -> bool:
    return (
        item.top_ratio is not None
        and item.bottom_ratio is not None
        and item.top_ratio >= parameters["body_region_top_ratio"]
        and item.bottom_ratio <= parameters["body_region_bottom_ratio"]
    )


def _short_display_block(item: _Element, parameters) -> bool:
    return (
        0 < item.line_count <= parameters["pull_quote_max_line_count"]
        and item.width_ratio is not None
        and item.width_ratio <= parameters["pull_quote_max_width_ratio"]
        and item.area_ratio is not None
        and item.area_ratio <= parameters["pull_quote_max_area_ratio"]
    )


def _pull_quote_visuals(item: _Element, parameters) -> bool:
    return (
        item.font_ratio is not None
        and item.font_ratio >= parameters["pull_quote_min_font_ratio"]
        and _short_display_block(item, parameters)
        and _in_body_region(item, parameters)
    )


def _byline_evidence(item, main_titles, frame, parameters):
    gap, title = _nearest_title_gap(item, main_titles, frame)
    title_font_ratio = None
    if (
        title is not None
        and item.font_size is not None
        and title.font_size is not None
        and title.font_size > 0
    ):
        title_font_ratio = item.font_size / title.font_size
    short = (
        0 < item.line_count <= parameters["byline_max_line_count"]
        and item.area_ratio is not None
        and item.area_ratio <= parameters["byline_max_area_ratio"]
    )
    smaller_or_narrower = (
        title_font_ratio is not None
        and title_font_ratio <= parameters["byline_max_title_font_ratio"]
    ) or (
        item.width_ratio is not None
        and item.width_ratio <= parameters["byline_max_width_ratio"]
    )
    accepted = (
        gap is not None
        and gap <= parameters["byline_max_title_gap_ratio"]
        and short
        and smaller_or_narrower
    )
    return accepted, gap, title_font_ratio


def _evidence(
    item: _Element,
    *,
    page_kind,
    body_median,
    main_title_refs,
    decision_reason,
    title_gap=None,
    title_font_ratio=None,
) -> dict:
    return {
        "page_kind": page_kind,
        "body_font_median": body_median,
        "font_size": item.font_size,
        "font_size_ratio": item.font_ratio,
        "line_count": item.line_count,
        "width_ratio": item.width_ratio,
        "area_ratio": item.area_ratio,
        "top_ratio": item.top_ratio,
        "bottom_ratio": item.bottom_ratio,
        "quote_shape": item.quote_shape,
        "terminal_punctuation": item.terminal_punctuation,
        "sentence_shape": item.sentence_shape,
        "main_title_refs": main_title_refs,
        "main_title_gap_ratio": title_gap,
        "main_title_font_ratio": title_font_ratio,
        "decision_reason": decision_reason,
    }


def _record(
    item,
    *,
    page_kind,
    body_median,
    main_title_refs,
    final_role,
    operation_label,
    decision_reason,
    title_gap=None,
    title_font_ratio=None,
) -> dict:
    if final_role is not None and final_role not in ROLES:
        raise ElementClassificationError(f"unknown final role {final_role!r}")
    if final_role is None:
        action = "excluded"
    elif operation_label == item.source_label:
        action = "preserve"
    else:
        action = "relabel"
    return {
        "source_ref": item.source_ref,
        "bbox": None if item.bbox is None else list(item.bbox),
        "source_label": item.source_label or None,
        "final_role": final_role,
        "operation_label": operation_label or None,
        "action": action,
        "evidence": _evidence(
            item,
            page_kind=page_kind,
            body_median=body_median,
            main_title_refs=main_title_refs,
            decision_reason=decision_reason,
            title_gap=title_gap,
            title_font_ratio=title_font_ratio,
        ),
    }


class ElementClassifier:
    """Assign final roles and operational labels to one document exactly once."""

    stage_name = "ElementClassifier"

    def __init__(self, translation_config):
        self.translation_config = translation_config
        self.config = load_element_config()
        self._processed = False

    def process(self, docs: il_version_1.Document) -> il_version_1.Document:
        if self._processed:
            raise ElementClassificationError(
                "element classification was already attempted by this stage"
            )
        self._processed = True
        records = []
        previous_main = None

        for page_position, page in enumerate(docs.page or ()):
            frame = _page_frame(page)
            elements = [
                _element(
                    page_position,
                    paragraph_position,
                    paragraph,
                    frame,
                    self.config,
                )
                for paragraph_position, paragraph in enumerate(page.pdf_paragraph or ())
            ]
            body_median = _body_median(elements, self.config)
            for item in elements:
                if (
                    item.font_size is not None
                    and body_median is not None
                    and body_median > 0
                ):
                    item.font_ratio = item.font_size / body_median

            page_kind = getattr(page, "page_kind", None)
            main_titles = _main_title_cohort(
                elements,
                page_kind,
                previous_main,
                self.config,
            )
            main_title_refs = [item.source_ref for item in main_titles]
            main_title_ids = {id(item) for item in main_titles}

            for item in elements:
                source_label = item.source_label
                if (
                    source_label in self.config["excluded_labels"]
                    or not item.text.strip()
                ):
                    records.append(
                        _record(
                            item,
                            page_kind=page_kind,
                            body_median=body_median,
                            main_title_refs=main_title_refs,
                            final_role=None,
                            operation_label=source_label,
                            decision_reason=(
                                "excluded_source_label"
                                if source_label in self.config["excluded_labels"]
                                else "non_text_paragraph"
                            ),
                        )
                    )
                    continue

                title_gap = title_font_ratio = None
                if source_label in self.config["caption_labels"]:
                    final_role = ROLE_CAPTION
                    operation_label = source_label
                    reason = "inherited_caption"
                elif source_label in self.config["body_labels"]:
                    if _pull_quote_visuals(item, self.config):
                        final_role = ROLE_PULL_QUOTE
                        operation_label = ROLE_PULL_QUOTE
                        reason = "body_visual_pull_quote"
                    else:
                        final_role = ROLE_BODY
                        operation_label = source_label
                        reason = "inherited_body"
                elif source_label in self.config["title_labels"]:
                    if id(item) in main_title_ids:
                        final_role = ROLE_TITLE
                        operation_label = ROLE_TITLE
                        reason = "main_title"
                    else:
                        is_byline, title_gap, title_font_ratio = _byline_evidence(
                            item, main_titles, frame, self.config
                        )
                        if is_byline:
                            final_role = ROLE_BYLINE
                            operation_label = ROLE_BYLINE
                            reason = "adjacent_short_byline"
                        elif (
                            _pull_quote_visuals(item, self.config)
                            and item.sentence_shape
                        ):
                            final_role = ROLE_PULL_QUOTE
                            operation_label = ROLE_PULL_QUOTE
                            reason = "title_candidate_visual_pull_quote"
                        else:
                            final_role = ROLE_OTHER_DISPLAY
                            operation_label = ROLE_OTHER_DISPLAY
                            reason = "insufficient_title_evidence"
                else:
                    final_role = ROLE_OTHER_DISPLAY
                    operation_label = ROLE_OTHER_DISPLAY
                    reason = "unrecognized_text_label"

                item.paragraph.layout_label = operation_label
                records.append(
                    _record(
                        item,
                        page_kind=page_kind,
                        body_median=body_median,
                        main_title_refs=main_title_refs,
                        final_role=final_role,
                        operation_label=operation_label,
                        decision_reason=reason,
                        title_gap=title_gap,
                        title_font_ratio=title_font_ratio,
                    )
                )

            previous_main = main_titles[0] if main_titles else None

        self._write_report(docs, records)
        return docs

    def _write_report(self, docs, records) -> Path | None:
        getter = getattr(self.translation_config, "get_working_file_path", None)
        if not callable(getter):
            # A few orchestration unit stubs intentionally have no filesystem.
            # Production translation configurations always supply this method.
            logger.debug("element report omitted for a filesystem-free test config")
            return None
        path = Path(getter(REPORT_NAME))
        path.parent.mkdir(parents=True, exist_ok=True)
        classified = sum(record["final_role"] is not None for record in records)
        report = {
            "roles": sorted(ROLES),
            "counts": {
                "pages": len(docs.page or ()),
                "paragraphs": len(records),
                "classified": classified,
                "excluded": len(records) - classified,
                "relabelled": sum(record["action"] == "relabel" for record in records),
            },
            "elements": records,
        }
        with path.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
        record_config_manifest(path.parent, [CONFIG_PATH])
        logger.debug("classified %d elements, report at %s", classified, path)
        return path
