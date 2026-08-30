"""Runtime drop-cap intent frozen before translation changes source styling."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
import weakref
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.new_parser.tokenizer import ContentStreamTokenizer
from babeldoc.format.pdf.new_parser.tokenizer import PdfName
from babeldoc.pdfminer.casting import safe_cmyk
from babeldoc.pdfminer.casting import safe_float
from babeldoc.pdfminer.casting import safe_rgb

REPORT_NAME = "drop_cap_intent.report.json"

POLICY_ALPHABETIC = "alphabetic"
POLICY_CJK_IDEOGRAPH = "cjk_ideograph"
POLICY_ENGLISH_RAISED_INITIAL = "english_raised_initial"
POLICY_CHINESE_TWO_LINE_INITIAL = "chinese_two_line_initial"

FLATTEN_PENDING = "pending"
FLATTEN_APPLIED = "applied"
FLATTEN_FAILED = "failed"

RENDER_PENDING = "pending"
RENDER_APPLIED = "applied"
RENDER_SKIPPED = "skipped"
RENDER_FAILED = "failed"

ISSUE_FLATTEN_FAILED = "drop_cap_flatten_failed"
ISSUE_RENDER_FAILED = "drop_cap_render_failed"
ISSUE_INVALID_INTENT = "invalid_drop_cap_intent"
ISSUE_PROTECTED_CONFLICT = "protected_drop_cap_conflict"


def _digest(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def style_record(style) -> dict:
    state = None if style is None else getattr(style, "graphic_state", None)
    return {
        "font_id": None if style is None else getattr(style, "font_id", None),
        "font_size": None if style is None else getattr(style, "font_size", None),
        "graphic_state": (
            None
            if state is None
            else getattr(state, "passthrough_per_char_instruction", None)
        ),
    }


def style_hash(style) -> str:
    return _digest(style_record(style))


@dataclass(frozen=True)
class NormalizedColor:
    rgb: tuple[float, float, float]
    source_space: str
    source_components: tuple[float, ...]
    operator: str

    def as_record(self) -> dict:
        return {
            "rgb": list(self.rgb),
            "source_space": self.source_space,
            "source_components": list(self.source_components),
            "operator": self.operator,
        }


@dataclass(frozen=True)
class FrozenColorState:
    fill: NormalizedColor
    stroke: NormalizedColor | None
    alpha: float | None
    ext_gstate: str | None
    evidence: tuple[str, ...]

    def as_record(self) -> dict:
        return {
            "fill": self.fill.as_record(),
            "stroke": None if self.stroke is None else self.stroke.as_record(),
            "alpha": self.alpha,
            "ext_gstate": self.ext_gstate,
            "evidence": list(self.evidence),
        }


"""Where the source initial's ink metric came from, or why it could not."""
ANCHOR_METRIC_GLYPH_BBOX = "source_font_char_bounding_box"
ANCHOR_METRIC_FALLBACK = "anchor_fallback_metric_box"


@dataclass(frozen=True)
class SourceAnchor:
    """How far the source initial's ink top sits below its own metric box top.

    Captured while the source character still exists, in the source font at
    the source size, off the same per-glyph ink table the frontend read out of
    the embedded font program. The render subtracts this from the paragraph's
    metric-box gap so the target initial's ink top lands where the source
    initial's ink actually started, not where its ascent whitespace did.
    ``ink_top_offset_pt`` is None exactly when the source metric could not be
    read, and then ``metric_source`` says so and the render changes nothing.
    """

    ink_top_offset_pt: float | None
    ink_top_em: float | None
    source_font_size: float | None
    metric_source: str
    evidence: tuple[str, ...]

    def as_record(self) -> dict:
        return {
            "ink_top_offset_pt": self.ink_top_offset_pt,
            "ink_top_em": self.ink_top_em,
            "source_font_size": self.source_font_size,
            "metric_source": self.metric_source,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class DropCapIssue:
    kind: str
    source_ref: str
    detail: str

    def as_record(self) -> dict:
        return {
            "kind": self.kind,
            "source_ref": self.source_ref,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ManualDecision:
    decision: str
    candidate_id: str
    source_ref: str
    source_text_fingerprint: str
    source_style_hash: str
    config_version: int
    decision_version: int

    def as_record(self) -> dict:
        return {
            "decision": self.decision,
            "candidate_id": self.candidate_id,
            "source_ref": self.source_ref,
            "source_text_fingerprint": self.source_text_fingerprint,
            "source_style_hash": self.source_style_hash,
            "config_version": self.config_version,
            "decision_version": self.decision_version,
        }


@dataclass
class DropCapIntent:
    candidate_id: str
    source_ref: str
    article_id: str | None
    source_char: str
    source_codepoint: str
    source_text_fingerprint: str
    source_style_hash: str
    source_color: FrozenColorState
    target_policy: str
    candidate_fingerprint: str
    config_version: int
    decision_version: int
    visual_initial_ref: str | None = None
    binding_proof: dict = field(default_factory=dict)
    generation: int = 0
    decision: str | None = None
    flatten_status: str = FLATTEN_PENDING
    render_status: str = RENDER_PENDING
    target_char: str | None = None
    target_index: int | None = None
    target_style_hash: str | None = None
    source_anchor: SourceAnchor | None = None
    issues: list[DropCapIssue] = field(default_factory=list)

    def manual_template(self, decision: str) -> dict:
        return ManualDecision(
            decision=decision,
            candidate_id=self.candidate_id,
            source_ref=self.source_ref,
            source_text_fingerprint=self.source_text_fingerprint,
            source_style_hash=self.source_style_hash,
            config_version=self.config_version,
            decision_version=self.decision_version,
        ).as_record()

    def as_record(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "source_ref": self.source_ref,
            "article_id": self.article_id,
            "source_char": self.source_char,
            "source_codepoint": self.source_codepoint,
            "source_text_fingerprint": self.source_text_fingerprint,
            "source_style_hash": self.source_style_hash,
            "source_color": self.source_color.as_record(),
            "target_policy": self.target_policy,
            "candidate_fingerprint": self.candidate_fingerprint,
            "config_version": self.config_version,
            "decision_version": self.decision_version,
            "visual_initial_ref": self.visual_initial_ref,
            "binding_proof": self.binding_proof,
            "generation": self.generation,
            "decision": self.decision,
            "flatten_status": self.flatten_status,
            "render_status": self.render_status,
            "target_char": self.target_char,
            "target_index": self.target_index,
            "target_style_hash": self.target_style_hash,
            "source_anchor": (
                None if self.source_anchor is None else self.source_anchor.as_record()
            ),
            "issues": [issue.as_record() for issue in self.issues],
        }


_registry: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_generations: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def replace_intents(translation_config, intents: list[DropCapIntent]) -> None:
    references = [intent.source_ref for intent in intents]
    if len(references) != len(set(references)):
        raise ValueError("a drop-cap source ref cannot own more than one active intent")
    generation = int(_generations.get(translation_config, 0)) + 1
    for intent in intents:
        intent.generation = generation
    _generations[translation_config] = generation
    _registry[translation_config] = {intent.source_ref: intent for intent in intents}


def intents_for(translation_config) -> dict[str, DropCapIntent]:
    return _registry.get(translation_config, {})


def intent_for(translation_config, reference: str) -> DropCapIntent | None:
    return intents_for(translation_config).get(reference)


def clear(translation_config) -> None:
    _registry.pop(translation_config, None)
    _generations.pop(translation_config, None)


def current_generation(translation_config) -> int:
    return int(_generations.get(translation_config, 0))


def active_protected_refs(
    translation_config,
    *,
    rendered_only: bool = False,
) -> frozenset[str]:
    """Canonical refs whose current intent still owns decorative composition."""
    generation = current_generation(translation_config)
    active = set()
    for reference, intent in intents_for(translation_config).items():
        try:
            from babeldoc.magazine.run_trace import parse_source_ref

            parse_source_ref(reference)
        except (TypeError, ValueError):
            continue
        if intent.generation != generation:
            continue
        if intent.flatten_status != FLATTEN_APPLIED:
            continue
        if rendered_only:
            if intent.render_status != RENDER_APPLIED:
                continue
        elif intent.render_status not in (RENDER_PENDING, RENDER_APPLIED):
            continue
        active.add(reference)
    return frozenset(active)


def decorative_anchor_signature(paragraph, intent: DropCapIntent):
    """Relative initial geometry used to prove whole-paragraph moves are safe."""
    if intent.render_status != RENDER_APPLIED or intent.target_index is None:
        return None
    paragraph_box = getattr(paragraph, "box", None)
    if paragraph_box is None:
        return None
    from babeldoc.magazine.line_split import paragraph_characters

    characters = [
        character
        for character in paragraph_characters(paragraph)
        if character.box is not None
    ]
    if not 0 <= intent.target_index < len(characters):
        return None
    initial = characters[intent.target_index]
    box = initial.box
    body = tuple(
        (
            character.char_unicode or "",
            round(float(character.box.x) - float(paragraph_box.x), 6),
            round(float(character.box.y) - float(paragraph_box.y), 6),
            round(float(character.box.x2) - float(paragraph_box.x), 6),
            round(float(character.box.y2) - float(paragraph_box.y), 6),
        )
        for index, character in enumerate(characters)
        if index != intent.target_index
    )
    return (
        initial.char_unicode or "",
        round(float(box.x) - float(paragraph_box.x), 6),
        round(float(box.y) - float(paragraph_box.y), 6),
        round(float(box.x2) - float(paragraph_box.x), 6),
        round(float(box.y2) - float(paragraph_box.y), 6),
        None
        if initial.pdf_style is None or initial.pdf_style.font_size is None
        else round(float(initial.pdf_style.font_size), 6),
        body,
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalized(
    operator: str,
    components: tuple[float, ...],
    color_space: str,
) -> NormalizedColor | None:
    if color_space == "DeviceGray" and len(components) == 1:
        gray = _clamp(components[0])
        rgb = (gray, gray, gray)
    elif color_space == "DeviceRGB" and len(components) == 3:
        parsed = safe_rgb(*components)
        if parsed is None:
            return None
        rgb = tuple(_clamp(item) for item in parsed)
    elif color_space == "DeviceCMYK" and len(components) == 4:
        parsed = safe_cmyk(*components)
        if parsed is None:
            return None
        cyan, magenta, yellow, black = (_clamp(item) for item in parsed)
        rgb = (
            1.0 - min(1.0, cyan + black),
            1.0 - min(1.0, magenta + black),
            1.0 - min(1.0, yellow + black),
        )
    else:
        return None
    return NormalizedColor(
        rgb=tuple(round(item, 6) for item in rgb),
        source_space=color_space,
        source_components=tuple(round(item, 6) for item in components),
        operator=operator,
    )


def _numbers(operands, count: int) -> tuple[float, ...] | None:
    if len(operands) != count:
        return None
    values = tuple(safe_float(value) for value in operands)
    if any(value is None or not math.isfinite(value) for value in values):
        return None
    return tuple(float(value) for value in values)


# The three spaces sc/scn components can be normalized in, and how many
# components each takes. A named space resolves into one of these or stays a
# name, in which case the components that follow it are recorded unsupported.
_DEVICE_COMPONENTS = {"DeviceGray": 1, "DeviceRGB": 3, "DeviceCMYK": 4}


def freeze_color(style, resolve_color_space=None) -> FrozenColorState:
    fill = _normalized("default", (0.0,), "DeviceGray")
    assert fill is not None
    stroke: NormalizedColor | None = None
    fill_space = "DeviceGray"
    stroke_space = "DeviceGray"
    evidence: list[str] = ["default-fill:DeviceGray"]
    ext_gstate = None
    state = None if style is None else getattr(style, "graphic_state", None)
    instruction = (
        None
        if state is None
        else getattr(state, "passthrough_per_char_instruction", None)
    )
    if instruction:
        try:
            operations = ContentStreamTokenizer(
                str(instruction).encode("latin-1", errors="replace")
            ).iter_operation_stream()
            for operation in operations:
                operator = operation.operator
                operands = operation.operands
                if operator in ("cs", "CS") and len(operands) == 1:
                    name = operands[0]
                    if isinstance(name, PdfName):
                        evidence.append(f"{operator}:/{name.value}")
                        space = name.value
                        if (
                            space not in _DEVICE_COMPONENTS
                            and resolve_color_space is not None
                        ):
                            resolved = resolve_color_space(space)
                            if resolved in _DEVICE_COMPONENTS:
                                evidence.append(f"resolve:/{space}->{resolved}")
                                space = resolved
                            else:
                                evidence.append(f"resolve:/{space}:unsupported")
                        if operator == "cs":
                            fill_space = space
                        else:
                            stroke_space = space
                    continue
                direct = {
                    "g": ("fill", "DeviceGray", 1),
                    "rg": ("fill", "DeviceRGB", 3),
                    "k": ("fill", "DeviceCMYK", 4),
                    "G": ("stroke", "DeviceGray", 1),
                    "RG": ("stroke", "DeviceRGB", 3),
                    "K": ("stroke", "DeviceCMYK", 4),
                }.get(operator)
                if direct is not None:
                    role, space, count = direct
                elif operator in ("sc", "scn"):
                    role, space = "fill", fill_space
                    count = _DEVICE_COMPONENTS.get(space, 0)
                elif operator in ("SC", "SCN"):
                    role, space = "stroke", stroke_space
                    count = _DEVICE_COMPONENTS.get(space, 0)
                else:
                    if operator == "gs" and len(operands) == 1:
                        name = operands[0]
                        if isinstance(name, PdfName):
                            ext_gstate = f"/{name.value} gs"
                            evidence.append(f"gs:/{name.value}:alpha-unresolved")
                    continue
                values = _numbers(operands, count)
                color = None if values is None else _normalized(operator, values, space)
                if color is None:
                    evidence.append(f"{operator}:{space}:unsupported")
                    continue
                if role == "fill":
                    fill = color
                else:
                    stroke = color
                evidence.append(f"{role}:{space}->{color.rgb}")
        except (TypeError, ValueError):
            evidence.append("instruction:unparseable")
    return FrozenColorState(
        fill=fill,
        stroke=stroke,
        alpha=1.0 if ext_gstate is None else None,
        ext_gstate=ext_gstate,
        evidence=tuple(evidence),
    )


def _anchor_fallback(reason: str) -> SourceAnchor:
    return SourceAnchor(
        ink_top_offset_pt=None,
        ink_top_em=None,
        source_font_size=None,
        metric_source=ANCHOR_METRIC_FALLBACK,
        evidence=(reason,),
    )


def freeze_source_anchor(il_page, character) -> SourceAnchor:
    """The source initial's ink-top offset below its own metric box top.

    Reads the per-glyph ink box the frontend parsed out of the embedded source
    font (``PdfFont.pdf_font_char_bounding_box``, font units over 1000, keyed
    by the character's cid), so the offset is measured in the source font at
    the source size. Every way the metric can be missing falls back to a
    recorded refusal rather than a guess, and the render then leaves the
    paragraph grid where today's behavior puts it.
    """
    style = getattr(character, "pdf_style", None)
    font_id = None if style is None else getattr(style, "font_id", None)
    size = None if style is None else getattr(style, "font_size", None)
    box = getattr(character, "box", None)
    char_id = getattr(character, "pdf_character_id", None)
    if not font_id or not size or box is None or char_id is None:
        return _anchor_fallback("source-style-or-box-incomplete")
    fonts = list(getattr(il_page, "pdf_font", None) or ())
    xobj_id = getattr(character, "xobj_id", None)
    if xobj_id is not None:
        for xobject in getattr(il_page, "pdf_xobject", None) or ():
            if getattr(xobject, "xobj_id", None) == xobj_id:
                fonts = list(getattr(xobject, "pdf_font", None) or ()) + fonts
                break
    font = next(
        (item for item in fonts if getattr(item, "font_id", None) == font_id),
        None,
    )
    if font is None:
        return _anchor_fallback(f"font:/{font_id}:not-in-page")
    entry = next(
        (
            candidate
            for candidate in getattr(font, "pdf_font_char_bounding_box", None) or ()
            if getattr(candidate, "char_id", None) == char_id
        ),
        None,
    )
    if entry is None:
        return _anchor_fallback(f"font:/{font_id}:cid:{char_id}:no-glyph-ink-box")
    try:
        ink_top_em = float(entry.y2) / 1000.0
        size = float(size)
        baseline = float(box.y)
        top = float(box.y2)
    except (TypeError, ValueError):
        return _anchor_fallback(f"font:/{font_id}:cid:{char_id}:unreadable-metric")
    if not all(math.isfinite(value) for value in (ink_top_em, size, baseline, top)):
        return _anchor_fallback(f"font:/{font_id}:cid:{char_id}:non-finite-metric")
    if size <= 0 or ink_top_em <= 0 or top <= baseline:
        return _anchor_fallback(f"font:/{font_id}:cid:{char_id}:degenerate-metric")
    offset = top - (baseline + ink_top_em * size)
    return SourceAnchor(
        ink_top_offset_pt=round(offset, 4),
        ink_top_em=round(ink_top_em, 6),
        source_font_size=round(size, 4),
        metric_source=ANCHOR_METRIC_GLYPH_BBOX,
        evidence=(
            f"font:/{font_id}",
            f"cid:{char_id}",
            f"glyph-ink-top-em:{round(ink_top_em, 6)}",
        ),
    )


def build_intent(
    *,
    source_ref: str,
    article_id: str | None,
    paragraph,
    source_character,
    target_policy: str,
    config_version: int,
    decision_version: int,
    visual_initial_ref: str | None = None,
    binding_proof: dict | None = None,
    resolve_color_space=None,
    source_anchor: SourceAnchor | None = None,
) -> DropCapIntent:
    source_char = source_character.char_unicode or ""
    source_style_hash = style_hash(source_character.pdf_style)
    text_fingerprint = _digest(paragraph.unicode or "")
    candidate_payload = {
        "source_ref": source_ref,
        "article_id": article_id,
        "source_char": source_char,
        "source_text_fingerprint": text_fingerprint,
        "source_style_hash": source_style_hash,
        "visual_initial_ref": visual_initial_ref or source_ref,
        "binding_proof": binding_proof or {},
        "config_version": config_version,
    }
    candidate_fingerprint = _digest(candidate_payload)
    return DropCapIntent(
        candidate_id=f"dropcap-{candidate_fingerprint}",
        source_ref=source_ref,
        article_id=article_id,
        source_char=source_char,
        source_codepoint=" ".join(f"U+{ord(char):04X}" for char in source_char),
        source_text_fingerprint=text_fingerprint,
        source_style_hash=source_style_hash,
        source_color=freeze_color(
            source_character.pdf_style, resolve_color_space
        ),
        target_policy=target_policy,
        candidate_fingerprint=candidate_fingerprint,
        config_version=config_version,
        decision_version=decision_version,
        visual_initial_ref=visual_initial_ref or source_ref,
        binding_proof=dict(binding_proof or {}),
        source_anchor=source_anchor,
    )


def decision_matches(intent: DropCapIntent, decision: ManualDecision) -> bool:
    return (
        decision.candidate_id == intent.candidate_id
        and decision.source_ref == intent.source_ref
        and decision.source_text_fingerprint == intent.source_text_fingerprint
        and decision.source_style_hash == intent.source_style_hash
        and decision.config_version == intent.config_version
        and decision.decision_version == intent.decision_version
    )


def _is_cjk_ideograph(char: str) -> bool:
    name = unicodedata.name(char, "")
    return name.startswith("CJK UNIFIED IDEOGRAPH-") or name.startswith(
        "CJK COMPATIBILITY IDEOGRAPH-"
    )


def eligible_initial(characters, policy: str) -> tuple[int, object] | None:
    for index, character in enumerate(characters):
        text = character.char_unicode or ""
        if (
            policy == POLICY_ENGLISH_RAISED_INITIAL
            and len(text) == 1
            and text.isalpha()
            and not _is_cjk_ideograph(text)
        ):
            return index, character
        if policy == POLICY_ALPHABETIC and any(
            char.isalpha() and not _is_cjk_ideograph(char) for char in text
        ):
            return index, character
        if policy == POLICY_CJK_IDEOGRAPH and any(_is_cjk_ideograph(char) for char in text):
            return index, character
        if (
            policy == POLICY_CHINESE_TWO_LINE_INITIAL
            and len(text) == 1
            and _is_cjk_ideograph(text)
        ):
            return index, character
    return None


def _rgb_instruction(color: NormalizedColor, stroke: bool = False) -> str:
    operator = "RG" if stroke else "rg"
    return f"{' '.join(format(value, '.6g') for value in color.rgb)} {operator}"


def apply_color(style, color: FrozenColorState) -> il_version_1.PdfStyle:
    base_instruction = None
    if style is not None and style.graphic_state is not None:
        base_instruction = style.graphic_state.passthrough_per_char_instruction
    parts = [str(base_instruction).strip()] if base_instruction else []
    if color.ext_gstate is not None:
        parts.append(color.ext_gstate)
    parts.append(_rgb_instruction(color.fill))
    if color.stroke is not None:
        parts.append(_rgb_instruction(color.stroke, stroke=True))
    return il_version_1.PdfStyle(
        font_id=None if style is None else style.font_id,
        font_size=None if style is None else style.font_size,
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction=" ".join(parts)
        ),
    )


def colors_close(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
    tolerance: float,
) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(left, right, strict=True))


def write_report(translation_config) -> Path:
    intents = intents_for(translation_config)
    record = {
        "generation": current_generation(translation_config),
        "intents": [intent.as_record() for _ref, intent in sorted(intents.items())],
        "totals": {
            "active": len(intents),
            "flatten_failed": sum(
                intent.flatten_status == FLATTEN_FAILED for intent in intents.values()
            ),
            "rendered": sum(
                intent.render_status == RENDER_APPLIED for intent in intents.values()
            ),
        },
    }
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
