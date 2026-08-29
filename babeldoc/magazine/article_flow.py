"""Measured, page-local target flow across the columns of one article."""

from __future__ import annotations

import json
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il.il_version_1 import Box
from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
from babeldoc.format.pdf.document_il.il_version_1 import PdfSameStyleUnicodeCharacters
from babeldoc.format.pdf.document_il.midend.typesetting import FIT_INVALID
from babeldoc.format.pdf.document_il.midend.typesetting import FIT_NONE
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.chain_backfill import load_backfill_config
from babeldoc.magazine.line_split import holds_formula
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.run_trace import canonical_text
from babeldoc.magazine.run_trace import hash_record
from babeldoc.magazine.run_trace import parse_source_ref
from babeldoc.magazine.taxonomy import record_config_manifest

CONFIG_PATH = config_path("article_flow.json")
CHAIN_CONFIG_PATH = config_path("chain_translation.json")
REPORT_NAME = "article_flow.report.json"
SWITCH = "magazine_column_reflow"

STATUS_ALLOCATED = "allocated"
STATUS_RELEASED = "released"
STATUS_PROTECTED = "protected"

SKIP_DISABLED = "switch_disabled"
SKIP_UNSUPPORTED = "unsupported_multi_article_page"
SKIP_NO_SEGMENT = "no_eligible_article_flow_segment"
SKIP_NO_TARGET = "target_text_unavailable"

GUARD_BOUNDS = "bounds"
GUARD_OVERLAP = "overlap"
GUARD_OWNERSHIP = "ownership"
GUARD_SOURCE_CONSERVATION = "source_text_conservation"
GUARD_TARGET_CONSERVATION = "target_text_conservation"
GUARD_CONSERVATION = GUARD_TARGET_CONSERVATION
GUARD_FIXED_ASSET = "fixed_asset_conservation"
GUARD_PROTECTED = "protected_element_conservation"
GUARD_ACTION = "action"


class ArticleFlowError(ConfigError):
    """Raised when article flow cannot be planned without breaking a contract."""


@dataclass(frozen=True, slots=True)
class ArticleFlowConfig:
    eligible_roles: tuple[str, ...]
    asset_bbox_tolerance_pt: float
    minimum_slot_height_pt: float

    def eligible(self, role: str | None) -> bool:
        return role in self.eligible_roles


@dataclass(frozen=True, slots=True)
class ParagraphBoundaryToken:
    """A zero-width boundary retaining one target paragraph's identity and policy."""

    source_ref: str
    source_page: int
    source_slot_id: str | None
    paragraph_order: int
    request_id: str
    fragment_id: str
    target_start: int
    target_end: int
    text: str
    first_line_indent: bool
    spacing_before: float
    style: object
    original_font: object
    paragraph: object

    def to_record(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "source_page": self.source_page,
            "source_slot_id": self.source_slot_id,
            "paragraph_order": self.paragraph_order,
            "request_id": self.request_id,
            "fragment_id": self.fragment_id,
            "target_range": [self.target_start, self.target_end],
            "chars": len(self.text),
            "first_line_indent": self.first_line_indent,
            "spacing_before": round(self.spacing_before, 3),
        }


@dataclass(frozen=True, slots=True)
class ArticleFlowSlot:
    slot_id: str
    article_id: str
    page: int
    column: int
    slot_order: int
    box: tuple[float, float, float, float]
    obstacle_refs: tuple[str, ...]

    def to_record(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "article_id": self.article_id,
            "page": self.page,
            "column": self.column,
            "slot_order": self.slot_order,
            "box": list(self.box),
            "obstacle_refs": list(self.obstacle_refs),
        }


@dataclass(frozen=True, slots=True)
class ProtectedElement:
    reference: str
    role: str
    box: tuple[float, float, float, float] | None
    reason: str

    def to_record(self) -> dict:
        return {
            "reference": self.reference,
            "role": self.role,
            "box": None if self.box is None else list(self.box),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ArticleFlowSegment:
    """One page/article flow bounded by protected elements."""

    segment_id: str
    article_id: str
    page: int
    ordered_source_refs: tuple[str, ...]
    ordered_slots: tuple[ArticleFlowSlot, ...]
    boundaries: tuple[ParagraphBoundaryToken, ...]
    protected_elements: tuple[ProtectedElement, ...]

    def to_record(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "article_id": self.article_id,
            "page": self.page,
            "ordered_source_refs": list(self.ordered_source_refs),
            "ordered_slots": [slot.to_record() for slot in self.ordered_slots],
            "boundaries": [boundary.to_record() for boundary in self.boundaries],
            "protected_elements": [
                item.to_record() for item in self.protected_elements
            ],
        }


@dataclass(frozen=True, slots=True)
class FlowPlacement:
    slot_id: str
    legal_slot_id: str
    source_ref: str
    request_id: str
    old_fragment_id: str
    previous_page: int
    previous_slot_id: str | None
    target_start: int
    target_end: int
    text: str
    page: int
    column: int
    slot_order: int
    box: tuple[float, float, float, float]
    first_line_indent: bool
    style: object
    source_paragraph: object
    measurement: dict
    render_ref: str | None = None

    def with_render_ref(self, reference: str) -> FlowPlacement:
        return FlowPlacement(
            self.slot_id,
            self.legal_slot_id,
            self.source_ref,
            self.request_id,
            self.old_fragment_id,
            self.previous_page,
            self.previous_slot_id,
            self.target_start,
            self.target_end,
            self.text,
            self.page,
            self.column,
            self.slot_order,
            self.box,
            self.first_line_indent,
            self.style,
            self.source_paragraph,
            self.measurement,
            reference,
        )

    def to_record(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "legal_slot_id": self.legal_slot_id,
            "source_ref": self.source_ref,
            "render_ref": self.render_ref,
            "request_id": self.request_id,
            "movement": {
                "before": {
                    "page": self.previous_page,
                    "slot_id": self.previous_slot_id,
                },
                "after": {"page": self.page, "slot_id": self.slot_id},
            },
            "target_range": [self.target_start, self.target_end],
            "chars": len(self.text),
            "page": self.page,
            "column": self.column,
            "slot_order": self.slot_order,
            "box": list(self.box),
            "first_line_indent": self.first_line_indent,
            "measurement": dict(self.measurement),
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArticleFlowError(message)


def parse_flow_config(raw: dict, source: str) -> ArticleFlowConfig:
    try:
        values = validate_bounded_config(raw, CONFIG_PATH)
    except ConfigError as exc:
        raise ArticleFlowError(str(exc)) from exc
    _require("eligible_roles" in values, f"{source}: missing eligible_roles")
    roles = tuple(values["eligible_roles"])
    _require(
        len(roles) == len(set(roles)), f"{source}: eligible_roles contains duplicates"
    )
    return ArticleFlowConfig(
        eligible_roles=roles,
        asset_bbox_tolerance_pt=float(values["asset_bbox_tolerance_pt"]),
        minimum_slot_height_pt=float(values["minimum_slot_height_pt"]),
    )


@lru_cache(maxsize=2)
def load_flow_config(path: str | None = None) -> ArticleFlowConfig:
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as stream:
        return parse_flow_config(json.load(stream), config_path.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def _box_tuple(value) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    coordinates = tuple(getattr(value, name, None) for name in ("x", "y", "x2", "y2"))
    if any(item is None for item in coordinates):
        return None
    result = tuple(float(item) for item in coordinates)
    if result[2] <= result[0] or result[3] <= result[1]:
        return None
    return result


def _paragraph(docs, reference: str):
    page, index = parse_source_ref(reference)
    return docs.page[page - 1].pdf_paragraph[index]


def _source_font(page, paragraph, style, typesetter):
    font_id = getattr(style, "font_id", None)
    xobj_id = getattr(paragraph, "xobj_id", None)
    if xobj_id is not None:
        for xobject in page.pdf_xobject or ():
            if xobject.xobj_id != xobj_id:
                continue
            for font in xobject.pdf_font or ():
                if font.font_id == font_id:
                    return font
    for font in page.pdf_font or ():
        if font.font_id == font_id:
            return font
    return typesetter.font_mapper.base_font


def _plain_style(paragraph, text: str):
    if holds_formula(paragraph):
        return None
    compositions = paragraph.pdf_paragraph_composition or ()
    if not compositions:
        return None
    rendered = []
    styles = []
    for composition in compositions:
        same = composition.pdf_same_style_unicode_characters
        if same is None or same.pdf_style is None:
            return None
        rendered.append(same.unicode or "")
        styles.append(same.pdf_style)
    if canonical_text("".join(rendered)) != canonical_text(text):
        return None
    first = styles[0]
    if any(style != first for style in styles[1:]):
        return None
    return first


def _spacing_before(previous, current) -> float:
    if previous is None or previous.column != current.column:
        return 0.0
    if previous.source_box is None or current.source_box is None:
        return 0.0
    return max(0.0, previous.source_box[1] - current.source_box[3])


def _subtract_obstacles(
    envelope: tuple[float, float, float, float],
    obstacles: Sequence[ProtectedElement],
    minimum_height: float,
) -> tuple[tuple[tuple[float, float, float, float], tuple[str, ...]], ...]:
    x, y, x2, y2 = envelope
    intervals = []
    for obstacle in obstacles:
        box = obstacle.box
        if box is None or min(x2, box[2]) <= max(x, box[0]):
            continue
        low = max(y, box[1])
        high = min(y2, box[3])
        if high > low:
            intervals.append((low, high, obstacle.reference))
    intervals.sort(key=lambda item: (item[0], item[1], item[2]))
    merged: list[tuple[float, float, set[str]]] = []
    for low, high, reference in intervals:
        if not merged or low > merged[-1][1]:
            merged.append((low, high, {reference}))
        else:
            old_low, old_high, refs = merged[-1]
            refs.add(reference)
            merged[-1] = (old_low, max(old_high, high), refs)
    cursor = y
    regions = []
    for low, high, refs in merged:
        if low - cursor >= minimum_height:
            regions.append(((x, cursor, x2, low), tuple(sorted(refs))))
        cursor = max(cursor, high)
    if y2 - cursor >= minimum_height:
        regions.append(((x, cursor, x2, y2), ()))
    return tuple(reversed(regions))


def _legal_slots(
    article_id: str,
    page_number: int,
    elements,
    protected: Sequence[ProtectedElement],
    config: ArticleFlowConfig,
) -> tuple[ArticleFlowSlot, ...]:
    columns = []
    for column in dict.fromkeys(element.column for element in elements):
        held = [element for element in elements if element.column == column]
        boxes = [
            element.source_box for element in held if element.source_box is not None
        ]
        if not boxes:
            continue
        envelope = (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )
        columns.append((column, envelope))
    slots = []
    for column, envelope in columns:
        for box, obstacle_refs in _subtract_obstacles(
            envelope, protected, config.minimum_slot_height_pt
        ):
            material = {
                "article_id": article_id,
                "page": page_number,
                "column": column,
                "box": list(box),
            }
            slots.append(
                ArticleFlowSlot(
                    slot_id=f"article-flow-region-{hash_record(material)}",
                    article_id=article_id,
                    page=page_number,
                    column=column,
                    slot_order=len(slots),
                    box=box,
                    obstacle_refs=obstacle_refs,
                )
            )
    return tuple(slots)


def _asset_obstacles(inventory, page: int) -> list[ProtectedElement]:
    return [
        ProtectedElement(asset.reference, asset.asset_type, asset.bbox, "fixed_asset")
        for asset in inventory.page_assets(page)
        if asset.bbox is not None
    ]


def build_page_segments(
    docs,
    article,
    page_number: int,
    inventory,
    config: ArticleFlowConfig,
    typesetter: Typesetting,
) -> tuple[ArticleFlowSegment, ...]:
    """Build segments strictly from canonical ArticleIR reading order."""
    page = docs.page[page_number - 1]
    page_elements = [item for item in article.elements if item.page == page_number]
    protected_page = _asset_obstacles(inventory, page_number)
    prepared = []
    previous = None
    for element in page_elements:
        paragraph = _paragraph(docs, element.source_ref)
        role_allowed = config.eligible(element.role)
        boundaries = []
        reason = None
        target = paragraph.unicode or ""
        if bool(getattr(paragraph, "vertical", False)):
            reason = "rotated_text"
        elif holds_formula(paragraph):
            reason = "formula"
        elif not role_allowed:
            reason = "role_not_eligible"
        elif not target:
            reason = SKIP_NO_TARGET
        else:
            style = _plain_style(paragraph, target)
            if style is None:
                reason = "non_plain_target"
            else:
                identity = {
                    "source_ref": element.source_ref,
                    "target": target,
                }
                fragment_id = f"article-flow-target-{hash_record(identity)}"
                boundaries.append(
                    ParagraphBoundaryToken(
                        source_ref=element.source_ref,
                        source_page=element.page,
                        source_slot_id=f"source-holder:{element.source_ref}",
                        paragraph_order=element.reading_order,
                        request_id=f"article-flow-source:{element.source_ref}",
                        fragment_id=fragment_id,
                        target_start=0,
                        target_end=len(target),
                        text=target,
                        first_line_indent=bool(
                            getattr(paragraph, "first_line_indent", False)
                        ),
                        spacing_before=_spacing_before(previous, element),
                        style=style,
                        original_font=_source_font(
                            page, paragraph, style, typesetter
                        ),
                        paragraph=paragraph,
                    )
                )
        prepared.append((element, tuple(boundaries), reason))
        if reason is None:
            previous = element
        else:
            previous = None

    for element, _boundaries, reason in prepared:
        if reason is not None:
            protected_page.append(
                ProtectedElement(
                    element.source_ref, element.role, element.source_box, reason
                )
            )

    segments = []
    held_elements = []
    held_boundaries = []

    def flush() -> None:
        if not held_elements or not held_boundaries:
            held_elements.clear()
            held_boundaries.clear()
            return
        slots = _legal_slots(
            article.article_id,
            page_number,
            held_elements,
            protected_page,
            config,
        )
        if slots:
            identity = {
                "article_id": article.article_id,
                "page": page_number,
                "sources": [item.source_ref for item in held_elements],
            }
            segments.append(
                ArticleFlowSegment(
                    segment_id=f"article-flow-{hash_record(identity)}",
                    article_id=article.article_id,
                    page=page_number,
                    ordered_source_refs=tuple(
                        item.source_ref for item in held_elements
                    ),
                    ordered_slots=slots,
                    boundaries=tuple(held_boundaries),
                    protected_elements=tuple(protected_page),
                )
            )
        held_elements.clear()
        held_boundaries.clear()

    for element, boundaries, reason in prepared:
        if reason is not None:
            flush()
            continue
        held_elements.append(element)
        held_boundaries.extend(boundaries)
    flush()
    return tuple(segments)


def allocate_segment(
    segment: ArticleFlowSegment,
    typesetter: Typesetting,
    config: ArticleFlowConfig,
) -> tuple[FlowPlacement, ...]:
    """Pack every target boundary into legal slots through the C06 fit API."""
    chain_config = load_backfill_config()
    placements = []
    slot_index = 0
    top = segment.ordered_slots[0].box[3] if segment.ordered_slots else 0.0
    used_in_slot = False
    for boundary in segment.boundaries:
        local = 0
        first_piece = True
        while local < len(boundary.text):
            if slot_index >= len(segment.ordered_slots):
                raise ArticleFlowError("target text exceeds page-local article slots")
            slot = segment.ordered_slots[slot_index]
            spacing = boundary.spacing_before if first_piece and used_in_slot else 0.0
            available_top = top - spacing
            if available_top - slot.box[1] < config.minimum_slot_height_pt:
                slot_index += 1
                if slot_index < len(segment.ordered_slots):
                    top = segment.ordered_slots[slot_index].box[3]
                used_in_slot = False
                continue
            result = typesetter.fit_text_to_slot(
                boundary.text[local:],
                boundary.style,
                typesetter.translation_config.lang_out,
                Box(slot.box[0], slot.box[1], slot.box[2], available_top),
                paragraph_start=boundary.first_line_indent and first_piece,
                original_font=boundary.original_font,
                minimum_font_size=chain_config.slot_min_font_size,
                fit_tolerance=chain_config.slot_fit_tolerance,
                line_skip=(
                    chain_config.capacity.line_skip_cjk
                    if chain_config.capacity.is_cjk_target(
                        typesetter.translation_config.lang_out
                    )
                    else chain_config.capacity.line_skip_latin
                ),
                line_head_forbidden=chain_config.line_head_forbidden,
                line_tail_forbidden=chain_config.line_tail_forbidden,
            )
            consumed = result.consumed_range[1]
            if result.status in (FIT_INVALID, FIT_NONE) or consumed <= 0:
                slot_index += 1
                if slot_index < len(segment.ordered_slots):
                    top = segment.ordered_slots[slot_index].box[3]
                used_in_slot = False
                continue
            if result.ink_bounds is None:
                raise ArticleFlowError(
                    "typesetter returned no ink bounds for fitted text"
                )
            end = local + consumed
            target_start = boundary.target_start + local
            target_end = boundary.target_start + end
            box = (
                slot.box[0],
                max(slot.box[1], float(result.ink_bounds[1])),
                slot.box[2],
                available_top,
            )
            material = {
                "region": slot.slot_id,
                "source_ref": boundary.source_ref,
                "target_range": [target_start, target_end],
                "order": len(placements),
            }
            measurement = result.to_record()
            measurement["request_target_range"] = [target_start, target_end]
            measurement["paragraph_order"] = boundary.paragraph_order
            placements.append(
                FlowPlacement(
                    slot_id=f"article-flow-slot-{hash_record(material)}",
                    legal_slot_id=slot.slot_id,
                    source_ref=boundary.source_ref,
                    request_id=boundary.request_id,
                    old_fragment_id=boundary.fragment_id,
                    previous_page=boundary.source_page,
                    previous_slot_id=boundary.source_slot_id,
                    target_start=target_start,
                    target_end=target_end,
                    text=boundary.text[local:end],
                    page=slot.page,
                    column=slot.column,
                    slot_order=len(placements),
                    box=box,
                    first_line_indent=boundary.first_line_indent and first_piece,
                    style=boundary.style,
                    source_paragraph=boundary.paragraph,
                    measurement=measurement,
                )
            )
            top = box[1]
            used_in_slot = True
            local = end
            first_piece = False
            if local < len(boundary.text):
                slot_index += 1
                if slot_index < len(segment.ordered_slots):
                    top = segment.ordered_slots[slot_index].box[3]
                used_in_slot = False
    return tuple(placements)


def _composition(text: str, style) -> list[PdfParagraphComposition]:
    return [
        PdfParagraphComposition(
            pdf_same_style_unicode_characters=PdfSameStyleUnicodeCharacters(
                unicode=text,
                pdf_style=style,
            )
        )
    ]


def _overlap(left, right) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def _validate_page(
    docs,
    article,
    page_number: int,
    segments,
    placements,
    protected_digests: Mapping[str, str],
    *,
    validate_conservation: bool = True,
) -> list[str]:
    issues = []
    frame = _box_tuple(getattr(docs.page[page_number - 1].cropbox, "box", None))
    if frame is None:
        frame = _box_tuple(getattr(docs.page[page_number - 1].mediabox, "box", None))
    legal = {
        slot.slot_id: slot for segment in segments for slot in segment.ordered_slots
    }
    for placement in placements:
        slot = legal.get(placement.legal_slot_id)
        if slot is None or placement.page != page_number:
            issues.append(GUARD_OWNERSHIP)
            continue
        if article.article_id != slot.article_id:
            issues.append(GUARD_OWNERSHIP)
        if any(placement.box[index] < slot.box[index] for index in (0, 1)) or any(
            placement.box[index] > slot.box[index] for index in (2, 3)
        ):
            issues.append(GUARD_BOUNDS)
        if frame is not None and (
            placement.box[0] < frame[0]
            or placement.box[1] < frame[1]
            or placement.box[2] > frame[2]
            or placement.box[3] > frame[3]
        ):
            issues.append(GUARD_BOUNDS)
        if placement.source_ref not in {item.source_ref for item in article.elements}:
            issues.append(GUARD_OWNERSHIP)
    for index, left in enumerate(placements):
        if any(_overlap(left.box, right.box) for right in placements[index + 1 :]):
            issues.append(GUARD_OVERLAP)
            break
    for segment in segments:
        for protected in segment.protected_elements:
            if protected.box is None:
                continue
            if any(_overlap(protected.box, placement.box) for placement in placements):
                issues.append(GUARD_OVERLAP)
                break
    for reference, digest in protected_digests.items():
        if fixed_assets.content_digest(_paragraph(docs, reference)) != digest:
            issues.append(GUARD_PROTECTED)
    if validate_conservation:
        for segment in segments:
            for boundary in segment.boundaries:
                pieces = [
                    item.text
                    for item in placements
                    if item.old_fragment_id == boundary.fragment_id
                ]
                if "".join(pieces) != boundary.text:
                    issues.append(GUARD_CONSERVATION)
    return sorted(set(issues))


def _released_regions(segments, placements):
    by_region: dict[str, list[FlowPlacement]] = {}
    for placement in placements:
        by_region.setdefault(placement.legal_slot_id, []).append(placement)
    released = []
    for segment in segments:
        for slot in segment.ordered_slots:
            used = by_region.get(slot.slot_id, ())
            bottom = slot.box[3] if not used else min(item.box[1] for item in used)
            if bottom <= slot.box[1]:
                continue
            box = (slot.box[0], slot.box[1], slot.box[2], bottom)
            released.append((f"{slot.slot_id}:released", segment.article_id, box))
    return released


def _write_report(translation_config, record: dict) -> Path:
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    record_config_manifest(
        path.parent, [CONFIG_PATH, CHAIN_CONFIG_PATH]
    )
    return path


def apply(
    translation_config,
    docs,
    article_document_ir,
    *,
    typesetter: Typesetting,
    config: ArticleFlowConfig | None = None,
) -> dict | None:
    """Apply bounded article flow across canonical adjacent pages."""
    if typesetter.translation_config is not translation_config:
        raise ValueError("article flow typesetter belongs to another config")
    if not enabled(translation_config):
        record = {
            "switch": SWITCH,
            "status": "disabled",
            "reason": SKIP_DISABLED,
            "article_flow_applied": False,
            "cross_page_segments": [],
            "issues": [],
            "pages": [],
            "totals": {
                "segments_considered": 0,
                "segments_applied": 0,
                "segments_rolled_back": 0,
                "pages_considered": 0,
                "pages_applied": 0,
                "pages_rolled_back": 0,
                "pages_skipped": 0,
                "placements": 0,
                "cross_page_movements": 0,
            },
        }
        _write_report(translation_config, record)
        return record
    from babeldoc.magazine import cross_page_reflow

    return cross_page_reflow.apply(
        translation_config,
        docs,
        article_document_ir,
        typesetter=typesetter,
        config=config,
    )
