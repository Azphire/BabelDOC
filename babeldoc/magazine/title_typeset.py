"""Bounded target-title typesetting for the fixed minimal pipeline.

``prepare`` runs after translation but before formal Typesetting and freezes
title ownership, target text, source boxes, and base font sizes. ``apply`` runs
after formal Typesetting with that exact Typesetting instance and lays each
complete target back into its immutable source box.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import BoundedTypesettingError
from babeldoc.magazine import hitl
from babeldoc.magazine import line_split
from babeldoc.magazine.article_builder import TITLE_CLASSES_KEY
from babeldoc.magazine.article_builder import title_labels
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.chain_signals import CLASS_LABELS_KEY
from babeldoc.magazine.chain_signals import CONFIG_PATH as CHAIN_CONFIG_PATH
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.react.writeback import page_font_map
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import record_config_manifest

CONFIG_PATH = config_path("title_typeset.json")
REPORT_NAME = "title_typeset.report.json"
CHAIN_REPORT_NAME = "chain_translation.report.json"
SWITCH = "magazine_title_typeset"
SCHEMA_VERSION = "title-typeset.v1"

MIN_SCALE_KEY = "title_min_scale"
MAX_LINES_KEY = "title_max_lines"
MIN_SCALE_BY_TARGET_KEY = "title_min_scale_by_target"
MAX_LINES_BY_TARGET_KEY = "title_max_lines_by_target"
_STRUCTURAL_KEYS = (MIN_SCALE_BY_TARGET_KEY, MAX_LINES_BY_TARGET_KEY)
_SUBTAG_SEPARATOR = "-"
_SUBTAG_ALIASES = ("_",)
_BOX_TOLERANCE = 0.001

_EXCLUDED_LABELS = frozenset(
    {
        "caption",
        "credit",
        "figure_caption",
        "folio",
        "page number",
        "page_number",
        "table_caption",
    }
)


class TitleTypesetError(ConfigError):
    """A title cannot be safely identified, conserved, or fitted."""


@dataclass(frozen=True, slots=True)
class TitleConfig:
    labels: tuple[str, ...]
    title_min_scale: float
    title_max_lines: int
    title_min_scale_by_target: Mapping[str, float]
    title_max_lines_by_target: Mapping[str, int]

    def is_title(self, paragraph) -> bool:
        return getattr(paragraph, "layout_label", None) in self.labels

    def for_target(self, target_lang: str | None) -> TitleConfig:
        scale = _claimed(target_lang, self.title_min_scale_by_target)
        lines = _claimed(target_lang, self.title_max_lines_by_target)
        return replace(
            self,
            title_min_scale=(
                self.title_min_scale if scale is None else float(scale)
            ),
            title_max_lines=(
                self.title_max_lines if lines is None else int(lines)
            ),
        )


@dataclass(slots=True)
class FrozenTitle:
    paragraph: object
    page: object
    physical_page: int
    local_ref: str
    source_ref: str
    source_box: tuple[float, float, float, float]
    base_style: object
    base_font_size: float
    target: str
    target_sha256: str
    target_compositions: tuple[object, ...]
    target_segments: tuple[dict, ...]
    chain_id: str | None
    chain_index: int | None
    owner_ref: str | None = None
    member_refs: tuple[str, ...] = ()
    trailing: bool = False


@dataclass(slots=True)
class _Run:
    config: object
    docs: object
    typesetter: object
    policy: TitleConfig
    titles: list[FrozenTitle]
    exclusions: list[dict]


_RUN: _Run | None = None


def discard() -> None:
    global _RUN
    _RUN = None


def _claimed(target_lang: str | None, table: Mapping[str, object]):
    if not table or not target_lang:
        return None
    tag = target_lang.strip().lower()
    for alias in _SUBTAG_ALIASES:
        tag = tag.replace(alias, _SUBTAG_SEPARATOR)
    matches = [
        (len(prefix), key)
        for key in table
        for prefix in (key.strip().lower(),)
        if tag == prefix or tag.startswith(prefix + _SUBTAG_SEPARATOR)
    ]
    return None if not matches else table[max(matches)[1]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TitleTypesetError(message)


def _target_table(raw: object, key: str, source: str) -> dict:
    _require(isinstance(raw, dict) and bool(raw), f"{source}: {key} must be an object")
    for name in raw:
        _require(
            isinstance(name, str) and bool(name.strip()),
            f"{source}: {key} has an invalid language prefix",
        )
    return dict(raw)


def _validate_table_values(
    table: dict,
    *,
    key: str,
    flat_key: str,
    raw: dict,
    source: str,
    integer: bool,
) -> Mapping:
    result = {}
    range_key = f"{flat_key}_allowed_range"
    for language, value in table.items():
        try:
            validated = validate_bounded_config(
                {flat_key: value, range_key: raw.get(range_key)}, CONFIG_PATH
            )[flat_key]
        except ConfigError as error:
            raise TitleTypesetError(
                f"{source}: {key}[{language!r}]: {error}"
            ) from error
        if integer:
            _require(
                isinstance(value, int) and not isinstance(value, bool),
                f"{source}: {key}[{language!r}] must be an integer",
            )
            result[language] = int(validated)
        else:
            result[language] = float(validated)
    return MappingProxyType(result)


def parse_title_config(raw: dict, source: str) -> TitleConfig:
    flat = {key: value for key, value in raw.items() if key not in _STRUCTURAL_KEYS}
    try:
        parameters = dict(validate_bounded_config(flat, CONFIG_PATH))
    except ConfigError as error:
        raise TitleTypesetError(str(error)) from error
    for key in (TITLE_CLASSES_KEY, MIN_SCALE_KEY, MAX_LINES_KEY):
        _require(key in parameters, f"{source}: missing {key}")
    _require(
        isinstance(raw[MAX_LINES_KEY], int) and not isinstance(raw[MAX_LINES_KEY], bool),
        f"{source}: {MAX_LINES_KEY} must be an integer",
    )
    declared = load_chain_config()[CLASS_LABELS_KEY]
    unknown = sorted(set(parameters[TITLE_CLASSES_KEY]) - set(declared))
    _require(
        not unknown,
        f"{source}: {TITLE_CLASSES_KEY} names {unknown}, outside "
        f"{CHAIN_CONFIG_PATH.name}",
    )
    labels = title_labels(parameters)
    _require(bool(labels), f"{source}: no title layout labels are declared")
    scale_table = _target_table(
        raw.get(MIN_SCALE_BY_TARGET_KEY), MIN_SCALE_BY_TARGET_KEY, source
    )
    lines_table = _target_table(
        raw.get(MAX_LINES_BY_TARGET_KEY), MAX_LINES_BY_TARGET_KEY, source
    )
    _require(
        set(scale_table) == set(lines_table),
        f"{source}: target policy language prefixes disagree",
    )
    return TitleConfig(
        labels=labels,
        title_min_scale=float(parameters[MIN_SCALE_KEY]),
        title_max_lines=int(parameters[MAX_LINES_KEY]),
        title_min_scale_by_target=_validate_table_values(
            scale_table,
            key=MIN_SCALE_BY_TARGET_KEY,
            flat_key=MIN_SCALE_KEY,
            raw=raw,
            source=source,
            integer=False,
        ),
        title_max_lines_by_target=_validate_table_values(
            lines_table,
            key=MAX_LINES_BY_TARGET_KEY,
            flat_key=MAX_LINES_KEY,
            raw=raw,
            source=source,
            integer=True,
        ),
    )


@lru_cache(maxsize=2)
def load_title_config(path: str | None = None) -> TitleConfig:
    held = CONFIG_PATH if path is None else Path(path)
    raw = json.loads(held.read_text(encoding="utf-8"))
    _require(isinstance(raw, dict), f"{held.name}: root must be an object")
    return parse_title_config(raw, held.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def _box(value) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        result = tuple(
            float(getattr(value, name)) for name in ("x", "y", "x2", "y2")
        )
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        not all(math.isfinite(item) for item in result)
        or result[0] >= result[2]
        or result[1] >= result[3]
    ):
        return None
    return result


def _box_equal(left, right, tolerance: float = _BOX_TOLERANCE) -> bool:
    return (
        left is not None
        and right is not None
        and len(left) == len(right) == 4
        and all(
            abs(float(a) - float(b)) <= tolerance
            for a, b in zip(left, right, strict=True)
        )
    )


def _contains(outer, inner, tolerance: float = _BOX_TOLERANCE) -> bool:
    return (
        outer[0] - tolerance <= inner[0]
        and outer[1] - tolerance <= inner[1]
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _characters_text(characters) -> str:
    return "".join(character.char_unicode or "" for character in characters)


def _style_identity(style) -> dict | None:
    font_id = None if style is None else getattr(style, "font_id", None)
    font_size = None if style is None else getattr(style, "font_size", None)
    if not isinstance(font_id, str) or not font_id or font_size is None:
        return None
    try:
        size = float(font_size)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(size) or size <= 0:
        return None
    return {"font_id": font_id, "font_size": size}


def _composition_identity(composition) -> dict | None:
    """The exact text/type/font-size evidence one paint layer can compare."""
    holder = composition.pdf_same_style_unicode_characters
    if holder is not None:
        identity = _style_identity(holder.pdf_style)
        if identity is None or not holder.unicode:
            return None
        return {
            "kind": "unicode",
            "text": holder.unicode,
            "styles": [identity],
        }
    character = composition.pdf_character
    if character is not None:
        identity = _style_identity(character.pdf_style)
        if identity is None or not character.char_unicode:
            return None
        return {
            "kind": "character",
            "text": character.char_unicode,
            "styles": [identity],
        }
    character_holder = (
        composition.pdf_same_style_characters or composition.pdf_line
    )
    if character_holder is not None:
        characters = list(character_holder.pdf_character or ())
        text = _characters_text(characters)
        styles = []
        holder_style = getattr(character_holder, "pdf_style", None)
        for character in characters:
            identity = _style_identity(character.pdf_style or holder_style)
            if identity is None:
                return None
            if not styles or styles[-1] != identity:
                styles.append(identity)
        if not text or not styles:
            return None
        return {
            "kind": (
                "same_style_characters"
                if composition.pdf_same_style_characters is not None
                else "line"
            ),
            "text": text,
            "styles": styles,
        }
    # Formula paint correspondence is not provable from font id/size alone.
    # A formula therefore prevents duplicate-layer suppression.
    return None


def _duplicate_layer_proof(compositions: tuple) -> dict | None:
    """Prove two exact overpaint layers at one composition boundary."""
    if len(compositions) < 2 or len(compositions) % 2:
        return None
    split = len(compositions) // 2
    left = [_composition_identity(item) for item in compositions[:split]]
    right = [_composition_identity(item) for item in compositions[split:]]
    if any(item is None for item in (*left, *right)):
        return None
    layer = "".join(item["text"] for item in left)
    other = "".join(item["text"] for item in right)
    if layer != other or len("".join(layer.split())) < 2:
        return None
    pairs = []
    for position, (kept, dropped) in enumerate(zip(left, right, strict=True)):
        if (
            kept["kind"] != dropped["kind"]
            or kept["text"] != dropped["text"]
            or kept["styles"] != dropped["styles"]
        ):
            return None
        pairs.append(
            {
                "position": position,
                "kind": kept["kind"],
                "kept_text": kept["text"],
                "kept_chars": len(kept["text"]),
                "kept_text_sha256": _sha256(kept["text"]),
                "dropped_text": dropped["text"],
                "dropped_chars": len(dropped["text"]),
                "dropped_text_sha256": _sha256(dropped["text"]),
                "kept_style_sequence": kept["styles"],
                "dropped_style_sequence": dropped["styles"],
            }
        )
    return {
        "split_composition_index": split,
        "kept_composition_count": split,
        "dropped_composition_count": split,
        "dropped_layer_count": 1,
        "layer_chars": len(layer),
        "layer_sha256": _sha256(layer),
        "paint_may_differ": True,
        "style_proof": pairs,
    }


def _generated_target(paragraph, source_ref: str) -> tuple[str, tuple, dict] | None:
    """Return the pre-formal visual target and its generated compositions.

    ``paragraph.unicode`` is the translation protocol string and can still
    contain rich-style/formula markup.  The post-translation composition list
    is the parser's rendered target.  A non-debug Unicode holder is the proof
    that this list was generated by translation; without one, laid-out source
    characters must not be mistaken for a target.  Once that proof exists,
    non-debug character/formula compositions in the same replacement list are
    legitimate rich-text/formula placeholders and are conserved in order.

    ``get_paragraph_unicode`` is intentionally not used: it admits source-only
    and debug carriers and applies character-spacing normalization.
    """
    compositions = paragraph.pdf_paragraph_composition or ()
    generated = any(
        composition.pdf_same_style_unicode_characters is not None
        and not bool(
            getattr(
                composition.pdf_same_style_unicode_characters,
                "debug_info",
                False,
            )
        )
        and bool(composition.pdf_same_style_unicode_characters.unicode)
        for composition in compositions
    )
    if not generated:
        return None

    visible: list[str] = []
    retained = []
    for composition in compositions:
        holder = composition.pdf_same_style_unicode_characters
        if holder is not None:
            if bool(getattr(holder, "debug_info", False)):
                continue
            _require(
                isinstance(holder.unicode, str),
                f"{source_ref}: generated Unicode holder has no text",
            )
            if holder.unicode:
                retained.append(copy.deepcopy(composition))
                visible.append(holder.unicode)
            continue

        character = composition.pdf_character
        if character is not None:
            if not bool(getattr(character, "debug_info", False)):
                retained.append(copy.deepcopy(composition))
                visible.append(character.char_unicode or "")
            continue

        character_holder = (
            composition.pdf_same_style_characters or composition.pdf_line
        )
        if character_holder is not None:
            characters = [
                copy.deepcopy(character)
                for character in character_holder.pdf_character or ()
                if not bool(getattr(character, "debug_info", False))
            ]
            if characters:
                held = copy.deepcopy(composition)
                target_holder = held.pdf_same_style_characters or held.pdf_line
                target_holder.pdf_character = characters
                retained.append(held)
                visible.append(_characters_text(characters))
            continue

        formula = composition.pdf_formula
        if formula is not None:
            held = copy.deepcopy(composition)
            held_formula = held.pdf_formula
            held_formula.pdf_character = [
                character
                for character in held_formula.pdf_character or ()
                if not bool(getattr(character, "debug_info", False))
            ]
            held_formula.pdf_curve = [
                curve
                for curve in held_formula.pdf_curve or ()
                if not bool(getattr(curve, "debug_info", False))
            ]
            if (
                held_formula.pdf_character
                or held_formula.pdf_curve
                or held_formula.pdf_form
            ):
                retained.append(held)
                visible.append(_characters_text(held_formula.pdf_character))
            continue

        raise TitleTypesetError(
            f"{source_ref}: generated target has an unknown composition"
        )
    pre_dedup_target = "".join(visible)
    _require(
        bool(pre_dedup_target), f"{source_ref}: generated visual target is empty"
    )
    _require(bool(retained), f"{source_ref}: generated target has no visual carriers")
    retained = tuple(retained)
    proof = _duplicate_layer_proof(retained)
    if proof is None:
        target = pre_dedup_target
        target_compositions = retained
    else:
        target_compositions = retained[: proof["split_composition_index"]]
        target = "".join(
            _composition_identity(composition)["text"]
            for composition in target_compositions
        )
    segment = {
        "source_ref": source_ref,
        "pre_dedup_visual_target": pre_dedup_target,
        "pre_dedup_target_chars": len(pre_dedup_target),
        "pre_dedup_target_sha256": _sha256(pre_dedup_target),
        "visual_target": target,
        "target_chars": len(target),
        "target_sha256": _sha256(target),
        "duplicate_layer": proof,
    }
    return target, target_compositions, segment


def _union_box(boxes) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _base_style(paragraph):
    style = getattr(paragraph, "pdf_style", None)
    if style is not None and getattr(style, "font_size", None):
        return copy.deepcopy(style)
    for composition in paragraph.pdf_paragraph_composition or ():
        holder = composition.pdf_same_style_unicode_characters
        if holder is not None and holder.pdf_style is not None:
            if getattr(holder.pdf_style, "font_size", None):
                return copy.deepcopy(holder.pdf_style)
    return None


def _read_chain_report(config) -> dict:
    path = Path(config.get_working_file_path(CHAIN_REPORT_NAME))
    if not path.is_file():
        return {"chains": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), f"{CHAIN_REPORT_NAME}: root must be an object")
    return payload


def _prove_title_chains(
    config,
    article_document_ir: ArticleDocumentIR,
    titles: list[FrozenTitle],
) -> None:
    groups: dict[str, list[FrozenTitle]] = {}
    for title in titles:
        if title.chain_id:
            groups.setdefault(title.chain_id, []).append(title)
    if not groups:
        return
    report_chains = _read_chain_report(config).get("chains")
    _require(
        isinstance(report_chains, list), f"{CHAIN_REPORT_NAME}.chains must be a list"
    )
    for chain_id, members in groups.items():
        _require(
            len(members) >= 2,
            f"title chain {chain_id} has fewer than two runtime members",
        )
        members.sort(
            key=lambda item: (
                item.chain_index if item.chain_index is not None else 1 << 30,
                item.local_ref,
            )
        )
        _require(
            [item.chain_index for item in members] == list(range(len(members))),
            f"title chain {chain_id} has incomplete member order",
        )
        local_refs = tuple(item.local_ref for item in members)
        canonical = tuple(
            article_document_ir.by_chain_member.get(reference)
            for reference in local_refs
        )
        _require(
            canonical[0] is not None and len(set(canonical)) == 1,
            f"title chain {chain_id} lacks canonical ArticleIR ownership",
        )
        matches = [
            item
            for item in report_chains
            if isinstance(item, dict)
            and item.get("chain_id") == chain_id
            and item.get("outcome") == "joint_success"
            and item.get("pair_class") == "title"
            and tuple(item.get("runtime_source_refs") or ()) == local_refs
            and item.get("canonical_chain_id") == canonical[0]
        ]
        _require(
            len(matches) == 1,
            f"title chain {chain_id} has no unique joint-success ownership proof",
        )
        evidence = matches[0]
        target = evidence.get("translation")
        fragments = evidence.get("ordered_fragments")
        source_boxes = evidence.get("source_boxes")
        _require(
            isinstance(target, str)
            and bool(target)
            and isinstance(fragments, list)
            and all(isinstance(item, str) for item in fragments)
            and "".join(fragments) == target
            and _sha256(target) == evidence.get("whole_target_sha256"),
            f"title chain {chain_id} target conservation proof is invalid",
        )
        _require(
            len(fragments) == len(members)
            and all(
                getattr(item.paragraph, "unicode", None) == fragment
                for item, fragment in zip(members, fragments, strict=True)
            ),
            f"title chain {chain_id} serialized fragments disagree with holders",
        )
        _require(
            isinstance(source_boxes, list)
            and len(source_boxes) == len(members)
            and all(
                _box_equal(source_box, member.source_box)
                for source_box, member in zip(source_boxes, members, strict=True)
            ),
            f"title chain {chain_id} source boxes changed",
        )
        _require(
            len({item.physical_page for item in members}) == 1,
            f"title chain {chain_id} crosses physical pages",
        )
        refs = tuple(item.source_ref for item in members)
        # A display title can be recovered as adjacent title paragraphs.  The
        # chain report is the ownership proof and its immutable member boxes
        # define the only region the complete target may use.  It is not safe
        # to require the boxes to overlap: that would reject the common two-line
        # source shape and leave two independently translated target holders.
        members[0].source_box = _union_box(
            tuple(item.source_box for item in members)
        )
        for position, member in enumerate(members):
            member.owner_ref = refs[0]
            member.member_refs = refs
            member.trailing = position > 0
        visual_target = "".join(member.target for member in members)
        _require(
            bool(visual_target),
            f"title chain {chain_id} generated visual target is empty",
        )
        members[0].target = visual_target
        members[0].target_sha256 = _sha256(visual_target)
        members[0].target_compositions = tuple(
            composition
            for member in members
            for composition in member.target_compositions
        )
        members[0].target_segments = tuple(
            segment
            for member in members
            for segment in member.target_segments
        )


def prepare(
    translation_config,
    docs,
    article_document_ir: ArticleDocumentIR,
    typesetter,
) -> dict | None:
    """Freeze target titles before the formal Typesetting pass."""
    global _RUN
    if not enabled(translation_config):
        discard()
        return None
    _require(
        getattr(typesetter, "translation_config", None) is translation_config,
        "title prepare received a foreign Typesetting instance",
    )
    policy = load_title_config().for_target(
        getattr(translation_config, "lang_out", None)
    )
    elements = {
        element.source_ref: element
        for article in article_document_ir.articles
        for element in article.elements
    }
    titles: list[FrozenTitle] = []
    exclusions: list[dict] = []
    for local_page, (physical_page, page) in enumerate(
        hitl.labeled_pages(docs), start=1
    ):
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph or ()):
            local_ref = f"p{local_page}#{paragraph_index}"
            source_ref = f"p{physical_page}#{paragraph_index}"
            label = (getattr(paragraph, "layout_label", None) or "").strip().lower()
            unit = line_split.source_unit(paragraph, physical_page)
            element = elements.get(local_ref)
            is_title = policy.is_title(paragraph) or (
                element is not None and element.role == "title"
            )
            generated_target = None
            reason = None
            if unit is not None:
                reason = f"toc:{unit.record_kind}"
            elif label in _EXCLUDED_LABELS:
                reason = label
            elif not is_title:
                continue
            else:
                generated_target = _generated_target(paragraph, source_ref)
                if generated_target is None:
                    reason = "no_generated_target"
            if reason is not None:
                exclusions.append(
                    {
                        "source_ref": source_ref,
                        "layout_label": label or None,
                        "reason": reason,
                    }
                )
                continue
            source_box = (
                tuple(float(value) for value in element.source_box)
                if element is not None and element.source_box is not None
                else _box(getattr(paragraph, "box", None))
            )
            style = _base_style(paragraph)
            _require(
                generated_target is not None,
                f"{source_ref}: generated target disappeared during prepare",
            )
            target, target_compositions, target_segment = generated_target
            _require(source_box is not None, f"{source_ref}: title source box is missing")
            _require(
                style is not None and float(style.font_size) > 0,
                f"{source_ref}: title base font size is missing",
            )
            _require(isinstance(target, str) and bool(target), f"{source_ref}: title target is empty")
            _require(
                "\n" not in target and "\r" not in target,
                f"{source_ref}: title target contains an unrendered line break",
            )
            titles.append(
                FrozenTitle(
                    paragraph=paragraph,
                    page=page,
                    physical_page=physical_page,
                    local_ref=local_ref,
                    source_ref=source_ref,
                    source_box=source_box,
                    base_style=style,
                    base_font_size=float(style.font_size),
                    target=target,
                    target_sha256=_sha256(target),
                    target_compositions=target_compositions,
                    target_segments=(target_segment,),
                    chain_id=getattr(paragraph, "chain_id", None),
                    chain_index=getattr(paragraph, "chain_index", None),
                )
            )
    _prove_title_chains(translation_config, article_document_ir, titles)
    _RUN = _Run(translation_config, docs, typesetter, policy, titles, exclusions)
    return {
        "prepared": len(titles),
        "excluded": len(exclusions),
        "typesetter_identity_frozen": True,
    }


def _unit_bounds(units) -> tuple[float, float, float, float] | None:
    boxes = [unit.box for unit in units if unit.box is not None]
    if not boxes:
        return None
    return (
        min(float(box.x) for box in boxes),
        min(float(box.y) for box in boxes),
        max(float(box.x2) for box in boxes),
        max(float(box.y2) for box in boxes),
    )


def _line_count(units) -> int:
    indices = [getattr(unit, "layout_line_index", None) for unit in units]
    _require(
        bool(indices) and all(index is not None for index in indices),
        "title line metrics are missing",
    )
    return len(set(indices))


def _snapshot(paragraph) -> tuple:
    return (
        paragraph.pdf_paragraph_composition,
        paragraph.unicode,
        copy.deepcopy(paragraph.box),
        paragraph.scale,
        paragraph.optimal_scale,
        paragraph.first_line_indent,
        paragraph.pdf_style,
    )


def _restore(paragraph, snapshot) -> None:
    (
        paragraph.pdf_paragraph_composition,
        paragraph.unicode,
        paragraph.box,
        paragraph.scale,
        paragraph.optimal_scale,
        paragraph.first_line_indent,
        paragraph.pdf_style,
    ) = snapshot


def _units_text(units) -> str:
    parts = []
    for unit in units:
        if unit.formular is not None:
            parts.append(_characters_text(unit.formular.pdf_character or ()))
        else:
            parts.append(unit.try_get_unicode() or "")
    return "".join(parts)


def _render_owner(typesetter, title: FrozenTitle, policy: TitleConfig) -> dict:
    paragraph = title.paragraph
    style = copy.deepcopy(title.base_style)
    style.font_size = title.base_font_size
    paragraph.box = il_version_1.Box(*title.source_box)
    paragraph.pdf_style = style
    paragraph.pdf_paragraph_composition = copy.deepcopy(
        list(title.target_compositions)
    )
    paragraph.unicode = title.target
    paragraph.first_line_indent = False
    fonts = page_font_map(title.page, typesetter.font_mapper)
    units = typesetter.create_typesetting_units(paragraph, fonts)
    sequence = _units_text(units)
    _require(sequence == title.target, f"{title.source_ref}: target unit sequence changed")
    try:
        laid_out = typesetter.retypeset_bounded_text(
            paragraph,
            title.page,
            units,
            source_ref=title.source_ref,
            source_box=title.source_box,
            minimum_scale=policy.title_min_scale,
            maximum_lines=policy.title_max_lines,
            # The ordinary English look-ahead deliberately drops a space that
            # becomes a line-leading layout separator.  A title pass has the
            # stricter audit contract that its target character sequence is
            # preserved exactly, so let the bounded packer wrap at the actual
            # unit boundary instead.
            use_english_line_break=False,
        )
    except BoundedTypesettingError as error:
        raise TitleTypesetError(str(error)) from error
    rendered = _units_text(laid_out)
    bounds = _unit_bounds(laid_out)
    lines = _line_count(laid_out)
    holder = _box(paragraph.box)
    _require(rendered == title.target, f"{title.source_ref}: rendered target changed")
    _require(
        _sha256(rendered) == title.target_sha256,
        f"{title.source_ref}: target digest changed",
    )
    _require(
        holder is not None and _box_equal(holder, title.source_box),
        f"{title.source_ref}: title holder changed",
    )
    _require(
        bounds is not None and _contains(title.source_box, bounds),
        f"{title.source_ref}: title ink escaped source box",
    )
    _require(
        1 <= lines <= policy.title_max_lines,
        f"{title.source_ref}: title line limit changed",
    )
    _require(
        paragraph.scale is not None
        and float(paragraph.scale) + 1e-9 >= policy.title_min_scale,
        f"{title.source_ref}: title fell below minimum scale",
    )
    return {
        "scale": float(paragraph.scale),
        "lines": lines,
        "final_text_box": list(bounds),
        "final_holder_box": list(holder),
    }


def _report(run: _Run, records: list[dict], status: str, error: str | None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "error": error,
        "same_formal_typesetter": True,
        "target_lang": getattr(run.config, "lang_out", "") or "",
        "policy": {
            "minimum_scale": run.policy.title_min_scale,
            "maximum_lines": run.policy.title_max_lines,
        },
        "titles": records,
        "exclusions": run.exclusions,
        "totals": {
            "owners": len(records),
            "success": sum(item.get("status") == "success" for item in records),
            "failure": sum(item.get("status") == "failure" for item in records),
            "rolled_back": sum(
                item.get("status") == "rolled_back" for item in records
            ),
            "suppressed_trailing_holders": sum(
                len(item.get("suppressed_refs", ())) for item in records
            ),
            "duplicate_layers_dropped": sum(
                item.get("duplicate_layers_dropped", 0)
                for item in records
                if item.get("status") == "success"
            ),
            "excluded": len(run.exclusions),
        },
    }


def _write(run: _Run, report: dict) -> None:
    path = Path(run.config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    record_config_manifest(path.parent, [CONFIG_PATH])


def apply(translation_config, docs, typesetter) -> dict | None:
    """Retypeset every frozen title with the exact formal Typesetting instance."""
    global _RUN
    if not enabled(translation_config):
        discard()
        return None
    run = _RUN
    if run is None:
        raise TitleTypesetError("title typesetting was not prepared")
    _require(run.config is translation_config, "title config identity changed")
    _require(run.docs is docs, "title document identity changed")
    _require(run.typesetter is typesetter, "formal Typesetting identity changed")
    _require(
        getattr(typesetter, "translation_config", None) is translation_config,
        "formal Typesetting config identity changed",
    )
    by_ref = {item.source_ref: item for item in run.titles}
    owners = [item for item in run.titles if not item.trailing]
    # The pass is one document-title transaction, not one transaction per
    # owner.  A late overflow must undo earlier owner rendering and any proven
    # trailing-holder suppression as well as the owner that failed.
    snapshots = {
        id(item.paragraph): _snapshot(item.paragraph) for item in run.titles
    }
    page_snapshots = {
        id(item.page): (
            item.page,
            list(item.page.pdf_curve or ()),
            list(item.page.pdf_form or ()),
        )
        for item in run.titles
    }
    records: list[dict] = []
    for title in sorted(owners, key=lambda item: (item.physical_page, item.source_ref)):
        member_refs = title.member_refs or (title.source_ref,)
        members = [by_ref[reference] for reference in member_refs]
        target_segments = copy.deepcopy(list(title.target_segments))
        pre_dedup_target = "".join(
            segment["pre_dedup_visual_target"] for segment in target_segments
        )
        duplicate_layers_dropped = sum(
            0
            if segment["duplicate_layer"] is None
            else segment["duplicate_layer"]["dropped_layer_count"]
            for segment in target_segments
        )
        record = {
            "source_ref": title.source_ref,
            "physical_page": title.physical_page,
            "source_box": list(title.source_box),
            "base_font_size": title.base_font_size,
            "target_chars": len(title.target),
            "target_sha256": title.target_sha256,
            "visual_target": title.target,
            "pre_dedup_visual_target": pre_dedup_target,
            "pre_dedup_target_chars": len(pre_dedup_target),
            "pre_dedup_target_sha256": _sha256(pre_dedup_target),
            "target_segments": target_segments,
            "duplicate_layers_dropped": duplicate_layers_dropped,
            "rendered_target_sha256": None,
            "maximum_lines": run.policy.title_max_lines,
            "minimum_scale": run.policy.title_min_scale,
            "chain_id": title.chain_id,
            "owner_ref": title.owner_ref or title.source_ref,
            "member_refs": list(member_refs),
            "suppressed_refs": [],
            "suppressed_holders": [],
            "status": "pending",
            "failure_reason": None,
        }
        try:
            outcome = _render_owner(typesetter, title, run.policy)
            suppressed = []
            suppressed_holders = []
            for member in members[1:]:
                member.paragraph.pdf_paragraph_composition = []
                member.paragraph.unicode = ""
                suppressed.append(member.source_ref)
                suppressed_holders.append(
                    {
                        "source_ref": member.source_ref,
                        "final_chars": len(member.paragraph.unicode),
                        "composition_count": len(
                            member.paragraph.pdf_paragraph_composition
                        ),
                    }
                )
            record.update(outcome)
            record["suppressed_refs"] = suppressed
            record["suppressed_holders"] = suppressed_holders
            record["rendered_target_sha256"] = _sha256(title.target)
            record["status"] = "success"
            records.append(record)
        except Exception as error:
            for frozen in run.titles:
                _restore(
                    frozen.paragraph,
                    snapshots[id(frozen.paragraph)],
                )
            for page, curves, forms in page_snapshots.values():
                page.pdf_curve[:] = curves
                page.pdf_form[:] = forms
            rollback_reason = f"title pass rolled back after {title.source_ref} failed"
            for previous in records:
                previous["status"] = "rolled_back"
                previous["failure_reason"] = rollback_reason
                previous["rendered_target_sha256"] = None
                previous["suppressed_refs"] = []
                previous["suppressed_holders"] = []
                for field in (
                    "scale",
                    "lines",
                    "final_text_box",
                    "final_holder_box",
                ):
                    previous.pop(field, None)
            record["status"] = "failure"
            record["failure_reason"] = f"{type(error).__name__}: {error}"
            records.append(record)
            report = _report(run, records, "failure", record["failure_reason"])
            _write(run, report)
            _RUN = None
            if isinstance(error, TitleTypesetError):
                raise
            raise TitleTypesetError(str(error)) from error
    report = _report(run, records, "success", None)
    _write(run, report)
    _RUN = None
    return report
