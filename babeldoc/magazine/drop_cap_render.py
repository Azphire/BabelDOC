"""Setting a translated paragraph's opening character the way its target sets one.

The second half of the ``keep`` verdict. The first half is the merge: ``keep``
and ``flatten`` hand the engine byte identical text, because an initial the
engine meets as a style run of its own is an initial it can carry across
untranslated, and that is true whichever way the finished page is set. What the
two verdicts differ over is only what is done once the translation is back, and
that is what this pass does. Nothing here reaches a prompt, a cache key or a
request.

Why it is not the general packer's job
--------------------------------------

The packer lays a paragraph out inside one rectangle. A drop cap is two
rectangles -- a narrow one beside the initial and a full width one under it --
and teaching the packer about the second is a rewrite of a stage this project
does not own. So this is its own lane, and the lane is kept as narrow as the
rotated one beside it: it re-packs the characters the stage already placed,
using the advances the stage already measured, and it re-packs nothing else.

Where the size comes from
-------------------------

The desired ink height follows the paragraph's measured line advance. The
mapped font's glyph box turns that height into a font size, and declared minimum
and maximum scales bound fonts with unusually short or tall capitals.

Where the initial is put
------------------------

Its real ink bottom is aligned with the first body line's real ink bottom. The
ink may stand above the paragraph body box, while the page and canonical article
envelopes still contain it and fixed assets remain obstacles. Only the first
line starts after its right edge and gutter; the next line resumes at the body
column edge.

What a refusal leaves
---------------------

The paragraph exactly as the typesetting stage left it, which is the shape
``flatten`` produces. Every character's box, size and advance is taken before
anything moves and put back on any refusal, so no refusal can leave a hole where
a line should be or a fragment of a first word stranded beside one.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import statistics
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import drop_cap
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.chain_signals import group_lines
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.detectors.drop_cap_geometry import BoxEvidence
from babeldoc.magazine.detectors.drop_cap_geometry import ColorEvidence
from babeldoc.magazine.detectors.drop_cap_geometry import DropCapGeometryContract
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("drop_cap_render.json")

REPORT_NAME = "drop_cap_render.report.json"
SCHEMA_VERSION = "drop-cap-render.v1"
CHAIN_REPORT_NAME = "chain_translation.report.json"

PERSISTED_FIELDS = (
    "source_ref",
    "decision",
    "target_char",
    "target_index",
    "direction_policy",
    "metric_source",
    "initial_box",
    "before_target_sha256",
    "after_target_sha256",
    "status",
    "failure_reason",
)
STATUS_COMMITTED = "committed"
STATUS_FAILURE = "failure"

SWITCH = "magazine_drop_cap_render"

# Structural keys: a table of regimes and a table of target languages are
# neither a number nor a vocabulary, so the bounded reader does not see them and
# they are validated by hand.
BY_TARGET_KEY = "by_target"
REGIMES_KEY = "regimes"
ENTRIES_KEY = "entries"
_STRUCTURAL_KEYS = (BY_TARGET_KEY, REGIMES_KEY)

# The two shapes an enlarged opening takes, and the two ways a re-set line may
# break. Named here because the code reads a regime's behaviour off these words;
# the words themselves are declared in the configuration and checked against it.
REGIME_SINK = "sink"
REGIME_INITIAL = "initial"
BREAK_ANYWHERE = "anywhere"
BREAK_WORD = "word"
GRID_EM = "em"
GRID_ADVANCE = "advance"

# Why one attempt was refused. Each is declared in the configuration and each is
# answered for by putting the paragraph back exactly as it stood.
REVERT_NOT_A_LETTER = "initial_is_not_a_letter"
REVERT_TOO_NARROW = "box_too_narrow"
REVERT_TOO_FEW_LINES = "not_enough_lines"
REVERT_NO_ADVANCE = "no_line_advance"
REVERT_WILL_NOT_FIT = "reached_past_its_own_box"
REVERT_NO_METRICS = "glyph_metrics_unavailable"
REVERT_POLICY = "target_policy_mismatch"
REVERT_PAGE_BOUNDS = "outside_page_envelope"
REVERT_ARTICLE_BOUNDS = "outside_article_envelope"
REVERT_COLLISION = "decorative_collision"
REVERT_RENDER_EXCEPTION = "render_exception"
REVERT_FIXED_ASSET = "fixed_asset_changed"
REVERT_INVALID_INTENT = "invalid_drop_cap_intent"
REVERT_POST_GEOMETRY = "post_render_geometry_failed"
REVERT_POST_COLOR = "post_render_color_failed"
REVERT_POST_COVERAGE = "post_render_coverage_failed"
REVERT_POST_COLLISION = "post_render_collision_failed"

STATE_INVALID_INTENT = "invalid_intent"
STATE_RENDER_ROLLBACK = "render_rollback"
STATE_COMMITTED = "committed"

RAISED_RESERVE_LINES = 1
CHINESE_RESERVE_LINES = 2

# Where the line grouping tolerance is declared, once for the whole project.
LINE_OVERLAP_KEY = "line_overlap_min"


class DropCapRenderError(ConfigError):
    """Raised when the render configuration or its dependencies are wrong."""


@dataclass(frozen=True)
class Regime:
    """One shape an enlarged opening takes, with the numbers it is set by."""

    name: str
    lines: int
    gutter_em: float
    break_rule: str
    grid: str


@dataclass(frozen=True)
class RenderConfig:
    """Everything declared about setting one enlarged opening."""

    regimes: Mapping[str, Regime]
    by_target: Mapping[str, str]
    min_line_capacity_em: float
    edge_slack_pt: float
    raised_initial_cap_height_lines: float
    raised_initial_min_font_scale: float
    raised_initial_max_font_scale: float
    ink_bottom_tolerance_pt: float
    ink_anchor_tolerance_pt: float
    revert_reasons: tuple[str, ...]
    report_fields: tuple[str, ...]

    def regime_for(self, target_lang: str) -> Regime | None:
        """The regime one target language asks for, by longest declared prefix.

        Matched as the drop cap default table is matched, because a target
        language reaches this project as a tag and a tag carries a region. None
        where no entry claims the language, which leaves every paragraph as the
        typesetting stage left it: a shape stated for the wrong language would
        set a page nobody asked a question about.
        """
        tag = (target_lang or "").strip().lower()
        claimed = [key for key in self.by_target if tag.startswith(key.lower())]
        if not claimed:
            return None
        return self.regimes[self.by_target[max(claimed, key=len)]]


BoxTuple = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class DecorativeGeometryGuard:
    """The envelopes and obstacles governing decorative initial ink."""

    page_box: BoxTuple | None
    article_boxes: tuple[BoxTuple, ...]
    obstacles: tuple[tuple[str, BoxTuple], ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DropCapRenderError(message)


def _read_regimes(raw: object, source: str, parameters: dict) -> Mapping[str, Regime]:
    """The regime table, with each regime's numbers read off the top level.

    A regime names only what is not a number -- where a line may break and what
    grid it is packed on. Its two numbers live at the top level under the
    regime's own name, so that every threshold carries the allowed range the
    bounded reader checks it against rather than hiding inside a nested object.
    """
    vocabulary = tuple(parameters.get("regime_vocabulary", ()))
    breaks = tuple(parameters.get("break_rule_vocabulary", ()))
    grids = tuple(parameters.get("grid_vocabulary", ()))
    _require(bool(vocabulary), f"{source}: missing regime_vocabulary")
    _require(bool(breaks), f"{source}: missing break_rule_vocabulary")
    _require(bool(grids), f"{source}: missing grid_vocabulary")
    _require(isinstance(raw, dict), f"{source}: {REGIMES_KEY} must be an object")
    entries = raw.get(ENTRIES_KEY)
    _require(
        isinstance(entries, dict) and bool(entries),
        f"{source}: {REGIMES_KEY}.{ENTRIES_KEY} must be a non-empty object",
    )
    _require(
        set(entries) == set(vocabulary),
        f"{source}: {REGIMES_KEY}.{ENTRIES_KEY} declares {sorted(entries)} and "
        f"regime_vocabulary declares {sorted(vocabulary)}",
    )
    built: dict[str, Regime] = {}
    for name, body in entries.items():
        _require(
            isinstance(body, dict),
            f"{source}: {REGIMES_KEY}.{ENTRIES_KEY}[{name!r}] must be an object",
        )
        rule = body.get("break_rule")
        grid = body.get("grid")
        _require(
            rule in breaks,
            f"{source}: {name}.break_rule={rule!r} is outside {sorted(breaks)}",
        )
        _require(
            grid in grids,
            f"{source}: {name}.grid={grid!r} is outside {sorted(grids)}",
        )
        lines_key = f"{name}_lines"
        gutter_key = f"{name}_gutter_em"
        for key in (lines_key, gutter_key):
            _require(key in parameters, f"{source}: regime {name!r} has no {key}")
        built[name] = Regime(
            name=name,
            lines=int(parameters[lines_key]),
            gutter_em=float(parameters[gutter_key]),
            break_rule=str(rule),
            grid=str(grid),
        )
    return MappingProxyType(built)


def _read_by_target(raw: object, source: str, regimes: Mapping[str, Regime]):
    _require(isinstance(raw, dict), f"{source}: {BY_TARGET_KEY} must be an object")
    entries = raw.get(ENTRIES_KEY)
    _require(
        isinstance(entries, dict) and bool(entries),
        f"{source}: {BY_TARGET_KEY}.{ENTRIES_KEY} must be a non-empty object",
    )
    for key, value in entries.items():
        _require(
            isinstance(key, str) and bool(key.strip()),
            f"{source}: {BY_TARGET_KEY}.{ENTRIES_KEY} has a key that is not a "
            f"language tag: {key!r}",
        )
        _require(
            value in regimes,
            f"{source}: {BY_TARGET_KEY}.{ENTRIES_KEY}[{key!r}]={value!r} is "
            f"outside the declared regimes {sorted(regimes)}",
        )
    return MappingProxyType({key.strip(): value for key, value in entries.items()})


def parse_render_config(raw: dict, source: str) -> RenderConfig:
    """Validate one configuration mapping into the policy it declares."""
    flat = {key: value for key, value in raw.items() if key not in _STRUCTURAL_KEYS}
    try:
        parameters = dict(validate_bounded_config(flat, CONFIG_PATH))
    except ConfigError as exc:
        raise DropCapRenderError(str(exc)) from exc

    regimes = _read_regimes(raw.get(REGIMES_KEY), source, parameters)
    by_target = _read_by_target(raw.get(BY_TARGET_KEY), source, regimes)
    reasons = tuple(parameters.get("revert_reasons", ()))
    fields = tuple(parameters.get("report_fields", ()))
    _require(bool(reasons), f"{source}: missing revert_reasons")
    _require(bool(fields), f"{source}: missing report_fields")
    for name in (
        REVERT_NOT_A_LETTER,
        REVERT_TOO_NARROW,
        REVERT_TOO_FEW_LINES,
        REVERT_NO_ADVANCE,
        REVERT_WILL_NOT_FIT,
        REVERT_NO_METRICS,
        REVERT_POLICY,
        REVERT_PAGE_BOUNDS,
        REVERT_ARTICLE_BOUNDS,
        REVERT_COLLISION,
        REVERT_RENDER_EXCEPTION,
        REVERT_FIXED_ASSET,
        REVERT_INVALID_INTENT,
        REVERT_POST_GEOMETRY,
        REVERT_POST_COLOR,
        REVERT_POST_COVERAGE,
        REVERT_POST_COLLISION,
    ):
        _require(
            name in reasons,
            f"{source}: revert_reasons omits {name!r}, which a record may name",
        )
    for key in (
        "min_line_capacity_em",
        "edge_slack_pt",
        "raised_initial_cap_height_lines",
        "raised_initial_min_font_scale",
        "raised_initial_max_font_scale",
        "ink_bottom_tolerance_pt",
        "ink_anchor_tolerance_pt",
    ):
        _require(key in parameters, f"{source}: missing {key}")
    _require(
        parameters["raised_initial_min_font_scale"]
        <= parameters["raised_initial_max_font_scale"],
        f"{source}: raised initial minimum font scale exceeds its maximum",
    )
    initial_regime = regimes.get(REGIME_INITIAL)
    _require(
        initial_regime is not None and initial_regime.lines == RAISED_RESERVE_LINES,
        f"{source}: the raised initial must reserve exactly one line",
    )
    sink_regime = regimes.get(REGIME_SINK)
    _require(
        sink_regime is not None and sink_regime.lines == CHINESE_RESERVE_LINES,
        f"{source}: the Chinese embedded initial must reserve exactly two lines",
    )
    return RenderConfig(
        regimes=regimes,
        by_target=by_target,
        min_line_capacity_em=float(parameters["min_line_capacity_em"]),
        edge_slack_pt=float(parameters["edge_slack_pt"]),
        raised_initial_cap_height_lines=float(
            parameters["raised_initial_cap_height_lines"]
        ),
        raised_initial_min_font_scale=float(
            parameters["raised_initial_min_font_scale"]
        ),
        raised_initial_max_font_scale=float(
            parameters["raised_initial_max_font_scale"]
        ),
        ink_bottom_tolerance_pt=float(parameters["ink_bottom_tolerance_pt"]),
        ink_anchor_tolerance_pt=float(parameters["ink_anchor_tolerance_pt"]),
        revert_reasons=reasons,
        report_fields=fields,
    )


@lru_cache(maxsize=1)
def load_render_config(path: str | None = None) -> RenderConfig:
    """Load and validate ``configs/drop_cap_render.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise DropCapRenderError(f"{config_path.name}: root must be an object")
    return parse_render_config(raw, config_path.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def _line_overlap_min() -> float:
    """The tolerance two characters are read as sharing a line under.

    Read from the file that declares it for the whole project rather than
    declared a second time here.
    """
    return float(load_chain_config()[LINE_OVERLAP_KEY])


def _is_whitespace(character) -> bool:
    return not (character.char_unicode or "").strip()


def _width(character) -> float:
    return abs(float(character.box.x2) - float(character.box.x))


@dataclass
class _Stored:
    """One character's geometry before anything moved, so it can be put back."""

    character: object
    x: float
    y: float
    x2: float
    y2: float
    style: object
    advance: float | None


def _take(characters) -> list[_Stored]:
    return [
        _Stored(
            character=c,
            x=float(c.box.x),
            y=float(c.box.y),
            x2=float(c.box.x2),
            y2=float(c.box.y2),
            style=c.pdf_style,
            advance=c.advance,
        )
        for c in characters
    ]


def _put_back(stored: list[_Stored]) -> None:
    for item in stored:
        item.character.box.x = item.x
        item.character.box.y = item.y
        item.character.box.x2 = item.x2
        item.character.box.y2 = item.y2
        item.character.pdf_style = item.style
        item.character.advance = item.advance


def _word_extent(characters, start: int) -> tuple[int, float]:
    """How far the word beginning at ``start`` runs, and how wide it is.

    A word is the run of non space characters, which is the unit a Latin line
    may not be broken inside. Consulted only under the word break rule.
    """
    end = start
    width = 0.0
    while end < len(characters) and not _is_whitespace(characters[end]):
        width += _width(characters[end])
        end += 1
    return end, width


def _place(character, x: float, baseline: float) -> None:
    height = float(character.box.y2) - float(character.box.y)
    width = float(character.box.x2) - float(character.box.x)
    character.box.x = x
    character.box.x2 = x + width
    character.box.y = baseline
    character.box.y2 = baseline + height


def _pack(characters, regime: Regime, geometry: dict) -> list[int]:
    """Place every character and report which line each landed on.

    The pen runs along a line until the next unit will not fit, and a new line
    starts at that line's own left edge: the first ``regime.lines`` lines begin
    past the reserve and every line after them begins at the paragraph's own
    left edge. A space never forces a break and is placed where the pen stands,
    because a space draws no ink and a line that ends in one has reached nowhere.
    """
    left = geometry["left"]
    right = geometry["right"]
    reserve = geometry["reserve"]
    advance = geometry["advance"]
    first_baseline = geometry["first_baseline"]

    def edge(line_index: int) -> float:
        return left + reserve if line_index < regime.lines else left

    line_index = 0
    pen = edge(0)
    assigned: list[int] = []
    index = 0
    while index < len(characters):
        character = characters[index]
        if _is_whitespace(character):
            _place(character, pen, first_baseline - line_index * advance)
            assigned.append(line_index)
            pen += _width(character)
            index += 1
            continue
        if regime.break_rule == BREAK_WORD:
            end, span = _word_extent(characters, index)
        else:
            end, span = index + 1, _width(character)
        if pen > edge(line_index) and pen + span > right:
            line_index += 1
            pen = edge(line_index)
        for position in range(index, end):
            member = characters[position]
            _place(member, pen, first_baseline - line_index * advance)
            assigned.append(line_index)
            pen += _width(member)
        index = end
    return assigned


def _ink_reach(characters) -> tuple[float, float, float, float] | None:
    boxes = [c.box for c in characters if not _is_whitespace(c)]
    if not boxes:
        return None
    return (
        min(float(b.x) for b in boxes),
        min(float(b.y) for b in boxes),
        max(float(b.x2) for b in boxes),
        max(float(b.y2) for b in boxes),
    )


def _quad(box) -> list[float] | None:
    if box is None:
        return None
    return [round(float(v), 4) for v in (box.x, box.y, box.x2, box.y2)]


def _refusal(base: dict, reason: str) -> dict:
    return {**base, "set": False, "reverted": True, "revert_reason": reason}


def _metric_for(character, resolver):
    if not callable(resolver):
        return None
    metric = resolver(character)
    if metric is None:
        return None
    try:
        box = tuple(float(value) for value in metric.ink_box_em)
        advance = float(metric.advance_em)
        glyph_id = int(metric.glyph_id)
        metric_font_id = str(metric.font_id)
    except (AttributeError, TypeError, ValueError):
        return None
    style = getattr(character, "pdf_style", None)
    paragraph_font_id = None if style is None else getattr(style, "font_id", None)
    if (
        len(box) != 4
        or not all(math.isfinite(value) for value in (*box, advance))
        or box[2] <= box[0]
        or box[3] <= box[1]
        or advance <= 0
        or glyph_id <= 0
        or not paragraph_font_id
        or metric_font_id != str(paragraph_font_id)
    ):
        return None
    return metric


def _glyph_ink_box(character, metric) -> BoxTuple | None:
    style = getattr(character, "pdf_style", None)
    size = None if style is None else getattr(style, "font_size", None)
    box = getattr(character, "box", None)
    if not size or box is None:
        return None
    try:
        x, y, x2, y2 = (float(value) for value in metric.ink_box_em)
        origin_x = float(box.x)
        baseline = float(box.y)
        size = float(size)
    except (TypeError, ValueError):
        return None
    return (
        origin_x + x * size,
        baseline + y * size,
        origin_x + x2 * size,
        baseline + y2 * size,
    )


def _union(boxes: list[BoxTuple]) -> BoxTuple | None:
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _line_ink_box(characters, assigned, line_index: int, resolver) -> BoxTuple | None:
    boxes = []
    for character, assigned_line in zip(characters, assigned, strict=True):
        if assigned_line != line_index or _is_whitespace(character):
            continue
        metric = _metric_for(character, resolver)
        if metric is None:
            return None
        box = _glyph_ink_box(character, metric)
        if box is None:
            return None
        boxes.append(box)
    return _union(boxes)


def _character_ink_boxes(characters, resolver) -> list[BoxTuple] | None:
    boxes = []
    for character in characters:
        if _is_whitespace(character):
            continue
        metric = _metric_for(character, resolver)
        if metric is None:
            return None
        box = _glyph_ink_box(character, metric)
        if box is None:
            return None
        boxes.append(box)
    return boxes


def _contains(outer: BoxTuple, inner: BoxTuple, slack: float) -> bool:
    return (
        inner[0] >= outer[0] - slack
        and inner[1] >= outer[1] - slack
        and inner[2] <= outer[2] + slack
        and inner[3] <= outer[3] + slack
    )


def _contains_raised_anchor(outer: BoxTuple, inner: BoxTuple, slack: float) -> bool:
    """Keep a raised initial anchored in its article while allowing its rise."""
    return (
        inner[0] >= outer[0] - slack
        and inner[2] <= outer[2] + slack
        and inner[1] >= outer[1] - slack
        and inner[1] <= outer[3] + slack
    )


def _overlaps(left: BoxTuple, right: BoxTuple, tolerance: float) -> bool:
    return (
        min(left[2], right[2]) - max(left[0], right[0]) > tolerance
        and min(left[3], right[3]) - max(left[1], right[1]) > tolerance
    )


def _rgb_hex(color) -> str | None:
    if color is None:
        return None
    rgb = getattr(color, "rgb", None)
    if rgb is None or len(rgb) != 3:
        return None
    channels = [max(0, min(255, round(float(value) * 255))) for value in rgb]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def _raised_initial_size(
    body_size: float,
    line_advance: float,
    metric,
    config: RenderConfig,
) -> float:
    ink_height_em = float(metric.ink_box_em[3]) - float(metric.ink_box_em[1])
    desired = config.raised_initial_cap_height_lines * line_advance / ink_height_em
    return min(
        body_size * config.raised_initial_max_font_scale,
        max(body_size * config.raised_initial_min_font_scale, desired),
    )


def _set_english_raised_initial(
    paragraph,
    regime: Regime,
    config: RenderConfig,
    base: dict,
    intent,
    glyph_metric_resolver,
    geometry_guard: DecorativeGeometryGuard | None,
) -> dict:
    if intent.target_policy != drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL:
        return _refusal(base, REVERT_POLICY)
    characters = [c for c in paragraph_characters(paragraph) if c.box is not None]
    if not characters or paragraph.box is None:
        return _refusal(base, REVERT_TOO_FEW_LINES)
    lines = group_lines(list(characters), _line_overlap_min())
    if len(lines) <= RAISED_RESERVE_LINES:
        return _refusal(base, REVERT_TOO_FEW_LINES)
    baselines = [float(line[0].box.y) for line in lines]
    steps = [
        baselines[position] - baselines[position + 1]
        for position in range(len(baselines) - 1)
    ]
    steps = [step for step in steps if step > 0]
    if not steps:
        return _refusal(base, REVERT_NO_ADVANCE)
    advance = statistics.median(steps)
    sizes = [
        float(c.pdf_style.font_size)
        for c in characters
        if c.pdf_style is not None and c.pdf_style.font_size
    ]
    if not sizes:
        return _refusal(base, REVERT_NO_ADVANCE)
    body_size = statistics.median(sizes)
    eligible = drop_cap_intent.eligible_initial(
        characters, drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL
    )
    if eligible is None:
        return _refusal(base, REVERT_NOT_A_LETTER)
    target_index, initial = eligible
    glyph = initial.char_unicode or ""
    if len(glyph) != 1 or not glyph.isalpha():
        return _refusal({**base, "initial": glyph}, REVERT_NOT_A_LETTER)
    initial_metric = _metric_for(initial, glyph_metric_resolver)
    if initial_metric is None:
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)

    initial_size = _raised_initial_size(body_size, advance, initial_metric, config)
    ink_left, _ink_bottom, ink_right, _ink_top = (
        float(value) for value in initial_metric.ink_box_em
    )
    initial_ink_width = (ink_right - ink_left) * initial_size
    left = float(paragraph.box.x)
    right = float(paragraph.box.x2)

    stored = _take(characters)
    prefix = characters[:target_index]
    suffix = characters[target_index + 1 :]
    prefix_pen = left
    for character in prefix:
        _place(character, prefix_pen, baselines[0])
        prefix_pen += _width(character)
    prefix_ink = (
        None
        if not prefix
        else _line_ink_box(
            prefix,
            [0] * len(prefix),
            0,
            glyph_metric_resolver,
        )
    )
    if prefix and any(not _is_whitespace(character) for character in prefix) and prefix_ink is None:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)
    initial_ink_left = max(
        prefix_pen,
        prefix_pen if prefix_ink is None else prefix_ink[2],
    )
    reserve = (
        initial_ink_left
        + initial_ink_width
        + regime.gutter_em * body_size
        - left
    )
    if (right - left) - reserve < config.min_line_capacity_em * body_size:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_TOO_NARROW)
    initial_style = il_version_1.PdfStyle(
        font_id=None if initial.pdf_style is None else initial.pdf_style.font_id,
        font_size=initial_size,
        graphic_state=(
            None if initial.pdf_style is None else initial.pdf_style.graphic_state
        ),
    )
    initial.pdf_style = drop_cap_intent.apply_color(
        initial_style, intent.source_color
    )
    initial.box.x = initial_ink_left - ink_left * initial_size
    initial.box.x2 = initial.box.x + float(initial_metric.advance_em) * initial_size
    initial.advance = float(initial_metric.advance_em) * initial_size
    assigned = _pack(
        suffix,
        regime,
        {
            "left": left,
            "right": right,
            "reserve": reserve,
            "advance": advance,
            "first_baseline": baselines[0],
        },
    )
    suffix_first_line_ink = _line_ink_box(
        suffix, assigned, 0, glyph_metric_resolver
    )
    first_line_ink = _union(
        [box for box in (prefix_ink, suffix_first_line_ink) if box is not None]
    )
    if first_line_ink is None or suffix_first_line_ink is None:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)
    initial.box.y = first_line_ink[1] - float(initial_metric.ink_box_em[1]) * initial_size
    initial.box.y2 = initial.box.y + initial_size
    initial_ink = _glyph_ink_box(initial, initial_metric)
    body_reaches = [
        reach
        for reach in (_ink_reach(prefix), _ink_reach(suffix))
        if reach is not None
    ]
    body_reach = _union(body_reaches)
    if initial_ink is None or body_reach is None:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)

    bottom_delta = initial_ink[1] - first_line_ink[1]
    slack = config.edge_slack_pt
    body_fits = (
        body_reach[0] >= left - slack
        and body_reach[1] >= float(paragraph.box.y) - slack
        and body_reach[2] <= right + slack
        and body_reach[3] <= float(paragraph.box.y2) + slack
    )

    def line_start(index: int) -> float | None:
        members = [
            character
            for character, line in zip(suffix, assigned, strict=True)
            if line == index and not _is_whitespace(character)
        ]
        return None if not members else min(float(character.box.x) for character in members)

    first_line_start = line_start(0)
    second_line_start = line_start(RAISED_RESERVE_LINES)
    geometry = {
        **base,
        "initial": glyph,
        "target_policy": intent.target_policy,
        "body_size": round(body_size, 4),
        "line_advance": round(advance, 4),
        "initial_size": round(initial_size, 4),
        "initial_char_count": len(glyph),
        "reserve": round(reserve, 4),
        "reserve_lines": RAISED_RESERVE_LINES,
        "lines_before": len(lines),
        "lines_after": (max(assigned) + 1) if assigned else 1,
        "first_line_shifts": [
            None if first_line_start is None else round(first_line_start - left, 4)
        ],
        "resume_shift": (
            None if second_line_start is None else round(second_line_start - left, 4)
        ),
        "second_line_start_x": (
            None if second_line_start is None else round(second_line_start, 4)
        ),
        "box": _quad(paragraph.box),
        "body_box": _quad(paragraph.box),
        "reach": [round(value, 4) for value in _union([body_reach, initial_ink])],
        "initial_ink_box": [round(value, 4) for value in initial_ink],
        "first_line_ink_box": [round(value, 4) for value in first_line_ink],
        "first_line_ink_bottom": round(first_line_ink[1], 4),
        "ink_bottom_delta": round(bottom_delta, 6),
        "page_box": (
            None
            if geometry_guard is None or geometry_guard.page_box is None
            else [round(value, 4) for value in geometry_guard.page_box]
        ),
        "article_boxes": (
            []
            if geometry_guard is None
            else [
                [round(value, 4) for value in box]
                for box in geometry_guard.article_boxes
            ]
        ),
        "collision_evidence": [],
        "color_evidence": intent.source_color.as_record(),
        "style_evidence": {
            "font_id": getattr(initial.pdf_style, "font_id", None),
            "font_size": round(initial_size, 4),
            "glyph_id": getattr(initial_metric, "glyph_id", None),
            "metric_source": getattr(initial_metric, "source", None),
            "source_style_hash": getattr(intent, "source_style_hash", None),
            "target_style_hash": drop_cap_intent.style_hash(initial.pdf_style),
        },
        "detector_contract": None,
    }
    failure = None
    if abs(bottom_delta) > config.ink_bottom_tolerance_pt or not body_fits:
        failure = REVERT_WILL_NOT_FIT
    elif (
        second_line_start is not None
        and abs(second_line_start - left) > config.ink_bottom_tolerance_pt
    ):
        failure = REVERT_WILL_NOT_FIT
    elif geometry_guard is None or geometry_guard.page_box is None:
        failure = REVERT_PAGE_BOUNDS
    elif not _contains(geometry_guard.page_box, initial_ink, slack):
        failure = REVERT_PAGE_BOUNDS
    elif not geometry_guard.article_boxes or not any(
        _contains_raised_anchor(box, initial_ink, slack)
        for box in geometry_guard.article_boxes
    ):
        failure = REVERT_ARTICLE_BOUNDS
    else:
        collisions = [
            (reference, box)
            for reference, box in geometry_guard.obstacles
            if _overlaps(initial_ink, box, config.ink_bottom_tolerance_pt)
        ]
        if collisions:
            geometry["collision_evidence"] = [
                {"reference": reference, "box": [round(value, 4) for value in box]}
                for reference, box in collisions
            ]
            failure = REVERT_COLLISION
    if failure is not None:
        _put_back(stored)
        return _refusal(geometry, failure)

    reserve_box = (
        left,
        first_line_ink[1],
        left + reserve,
        first_line_ink[3],
    )
    contract = DropCapGeometryContract(
        source_ref=str(base["paragraph"]),
        page=int(base["page"]),
        article_id=getattr(intent, "article_id", None),
        character_count=len(glyph),
        policy=intent.target_policy,
        ink=BoxEvidence(initial_ink, "font_glyph_metrics"),
        reserve=BoxEvidence(reserve_box, "first_line_only"),
        collision=(),
        color=ColorEvidence(
            _rgb_hex(intent.source_color.fill),
            _rgb_hex(intent.source_color.stroke),
            None,
        ),
    )
    geometry["detector_contract"] = contract.to_record()
    return {
        **geometry,
        "set": True,
        "reverted": False,
        "revert_reason": None,
        "_target_index": target_index,
    }


def _set_chinese_two_line_initial(
    paragraph,
    regime: Regime,
    config: RenderConfig,
    base: dict,
    intent,
    glyph_metric_resolver,
    geometry_guard: DecorativeGeometryGuard | None,
) -> dict:
    if (
        intent.target_policy != drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL
        or regime.name != REGIME_SINK
        or regime.lines != CHINESE_RESERVE_LINES
    ):
        return _refusal(base, REVERT_POLICY)
    characters = [c for c in paragraph_characters(paragraph) if c.box is not None]
    if not characters or paragraph.box is None:
        return _refusal(base, REVERT_TOO_FEW_LINES)
    lines = group_lines(list(characters), _line_overlap_min())
    if len(lines) < CHINESE_RESERVE_LINES:
        return _refusal(base, REVERT_TOO_FEW_LINES)

    baselines = [float(line[0].box.y) for line in lines]
    steps = [
        baselines[position] - baselines[position + 1]
        for position in range(len(baselines) - 1)
    ]
    steps = [step for step in steps if step > 0]
    if not steps:
        return _refusal(base, REVERT_NO_ADVANCE)
    advance = statistics.median(steps)
    sizes = [
        float(c.pdf_style.font_size)
        for c in characters
        if c.pdf_style is not None and c.pdf_style.font_size
    ]
    if not sizes:
        return _refusal(base, REVERT_NO_ADVANCE)
    body_size = statistics.median(sizes)

    eligible = drop_cap_intent.eligible_initial(
        characters, drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL
    )
    if eligible is None:
        return _refusal(base, REVERT_NOT_A_LETTER)
    target_index, initial = eligible
    glyph = initial.char_unicode or ""
    if len(glyph) != 1:
        return _refusal({**base, "initial": glyph}, REVERT_NOT_A_LETTER)
    initial_metric = _metric_for(initial, glyph_metric_resolver)
    if initial_metric is None:
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)

    dry_first = [character for character in lines[0] if character is not initial]
    dry_second = list(lines[1])
    dry_first_boxes = _character_ink_boxes(dry_first, glyph_metric_resolver)
    dry_second_boxes = _character_ink_boxes(dry_second, glyph_metric_resolver)
    dry_first_ink = None if dry_first_boxes is None else _union(dry_first_boxes)
    dry_second_ink = None if dry_second_boxes is None else _union(dry_second_boxes)
    if dry_first_ink is None or dry_second_ink is None:
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)
    target_top = dry_first_ink[3]
    target_bottom = dry_second_ink[1]
    ink_left, ink_bottom, ink_right, ink_top = (
        float(value) for value in initial_metric.ink_box_em
    )
    ink_height_em = ink_top - ink_bottom
    desired_ink_height = target_top - target_bottom
    if ink_height_em <= 0 or desired_ink_height <= 0:
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)
    initial_size = desired_ink_height / ink_height_em

    left = float(paragraph.box.x)
    right = float(paragraph.box.x2)
    stored = _take(characters)
    prefix = characters[:target_index]
    suffix = characters[target_index + 1 :]
    prefix_pen = left
    for character in prefix:
        _place(character, prefix_pen, baselines[0])
        prefix_pen += _width(character)
    prefix_boxes = _character_ink_boxes(prefix, glyph_metric_resolver)
    if prefix_boxes is None:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)
    prefix_ink = _union(prefix_boxes)
    initial_ink_left = max(
        prefix_pen,
        prefix_pen if prefix_ink is None else prefix_ink[2],
    )

    initial_style = il_version_1.PdfStyle(
        font_id=None if initial.pdf_style is None else initial.pdf_style.font_id,
        font_size=initial_size,
        graphic_state=(
            None if initial.pdf_style is None else initial.pdf_style.graphic_state
        ),
    )
    initial.pdf_style = drop_cap_intent.apply_color(initial_style, intent.source_color)
    initial.box.x = initial_ink_left - ink_left * initial_size
    initial.box.x2 = initial.box.x + float(initial_metric.advance_em) * initial_size
    initial.box.y = target_bottom - ink_bottom * initial_size
    initial.box.y2 = initial.box.y + initial_size
    initial.advance = float(initial_metric.advance_em) * initial_size
    initial_ink = _glyph_ink_box(initial, initial_metric)
    if initial_ink is None:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)

    gutter = regime.gutter_em * body_size
    reserve_edge = initial_ink[2] + gutter
    reserve = reserve_edge - left
    if (right - left) - reserve < config.min_line_capacity_em * body_size:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_TOO_NARROW)
    assigned = _pack(
        suffix,
        regime,
        {
            "left": left,
            "right": right,
            "reserve": reserve,
            "advance": advance,
            "first_baseline": baselines[0],
        },
    )
    if not assigned or max(assigned) < CHINESE_RESERVE_LINES - 1:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_TOO_FEW_LINES)

    def line_members(index: int) -> list:
        members = [
            character
            for character, assigned_line in zip(suffix, assigned, strict=True)
            if assigned_line == index and not _is_whitespace(character)
        ]
        if index == 0:
            members = [
                character for character in prefix if not _is_whitespace(character)
            ] + members
        return members

    first_members = line_members(0)
    second_members = line_members(1)
    first_boxes = _character_ink_boxes(first_members, glyph_metric_resolver)
    second_boxes = _character_ink_boxes(second_members, glyph_metric_resolver)
    body_boxes = _character_ink_boxes(prefix + suffix, glyph_metric_resolver)
    first_line_ink = None if first_boxes is None else _union(first_boxes)
    second_line_ink = None if second_boxes is None else _union(second_boxes)
    body_ink = None if body_boxes is None else _union(body_boxes)
    if first_line_ink is None or second_line_ink is None or body_ink is None:
        _put_back(stored)
        return _refusal({**base, "initial": glyph}, REVERT_NO_METRICS)

    def line_start(index: int) -> float | None:
        members = [
            character
            for character, assigned_line in zip(suffix, assigned, strict=True)
            if assigned_line == index and not _is_whitespace(character)
        ]
        return None if not members else min(float(character.box.x) for character in members)

    body_starts = [line_start(index) for index in range(CHINESE_RESERVE_LINES)]
    third_line_start = line_start(CHINESE_RESERVE_LINES)
    top_delta = initial_ink[3] - first_line_ink[3]
    bottom_delta = initial_ink[1] - second_line_ink[1]
    slack = config.edge_slack_pt
    anchor_tolerance = config.ink_anchor_tolerance_pt
    body_fits = _contains(
        (left, float(paragraph.box.y), right, float(paragraph.box.y2)),
        body_ink,
        slack,
    )
    combined_reach = _union([body_ink, initial_ink])
    assert combined_reach is not None

    geometry = {
        **base,
        "initial": glyph,
        "target_policy": intent.target_policy,
        "body_size": round(body_size, 4),
        "line_advance": round(advance, 4),
        "initial_size": round(initial_size, 4),
        "initial_char_count": len(glyph),
        "reserve": round(reserve, 4),
        "gutter": round(gutter, 4),
        "reserve_lines": CHINESE_RESERVE_LINES,
        "lines_before": len(lines),
        "lines_after": max(assigned) + 1,
        "line_baselines": [round(value, 4) for value in baselines],
        "body_start_x": [
            None if value is None else round(value, 4) for value in body_starts
        ],
        "first_line_shifts": [
            None if value is None else round(value - left, 4) for value in body_starts
        ],
        "resume_shift": (
            None
            if third_line_start is None
            else round(third_line_start - left, 4)
        ),
        "second_line_start_x": (
            None if body_starts[1] is None else round(body_starts[1], 4)
        ),
        "third_line_start_x": (
            None if third_line_start is None else round(third_line_start, 4)
        ),
        "box": _quad(paragraph.box),
        "body_box": _quad(paragraph.box),
        "reach": [round(value, 4) for value in combined_reach],
        "initial_ink_box": [round(value, 4) for value in initial_ink],
        "body_ink_box": [round(value, 4) for value in body_ink],
        "first_line_ink_box": [round(value, 4) for value in first_line_ink],
        "first_line_ink_top": round(first_line_ink[3], 4),
        "second_line_ink_box": [round(value, 4) for value in second_line_ink],
        "second_line_ink_bottom": round(second_line_ink[1], 4),
        "ink_top_delta": round(top_delta, 6),
        "first_line_ink_bottom": round(first_line_ink[1], 4),
        "ink_bottom_delta": round(bottom_delta, 6),
        "page_box": (
            None
            if geometry_guard is None or geometry_guard.page_box is None
            else [round(value, 4) for value in geometry_guard.page_box]
        ),
        "article_boxes": (
            []
            if geometry_guard is None
            else [
                [round(value, 4) for value in box]
                for box in geometry_guard.article_boxes
            ]
        ),
        "collision_evidence": [],
        "color_evidence": intent.source_color.as_record(),
        "style_evidence": {
            "font_id": getattr(initial.pdf_style, "font_id", None),
            "font_size": round(initial_size, 4),
            "glyph_id": getattr(initial_metric, "glyph_id", None),
            "metric_source": getattr(initial_metric, "source", None),
            "metric_font_id": getattr(initial_metric, "font_id", None),
            "source_style_hash": getattr(intent, "source_style_hash", None),
            "target_style_hash": drop_cap_intent.style_hash(initial.pdf_style),
        },
        "detector_contract": None,
    }

    failure = None
    if (
        abs(top_delta) > anchor_tolerance
        or abs(bottom_delta) > anchor_tolerance
        or not body_fits
    ):
        failure = REVERT_WILL_NOT_FIT
    elif any(value is None or value < reserve_edge - anchor_tolerance for value in body_starts):
        failure = REVERT_WILL_NOT_FIT
    elif (
        third_line_start is not None
        and abs(third_line_start - left) > anchor_tolerance
    ):
        failure = REVERT_WILL_NOT_FIT
    elif body_boxes is None or any(
        _overlaps(initial_ink, box, 0.0) for box in body_boxes
    ):
        failure = REVERT_COLLISION
    elif geometry_guard is None or geometry_guard.page_box is None:
        failure = REVERT_PAGE_BOUNDS
    elif not _contains(geometry_guard.page_box, combined_reach, slack):
        failure = REVERT_PAGE_BOUNDS
    elif not geometry_guard.article_boxes or not any(
        _contains(box, combined_reach, slack) for box in geometry_guard.article_boxes
    ):
        failure = REVERT_ARTICLE_BOUNDS
    else:
        collisions = [
            (reference, box)
            for reference, box in geometry_guard.obstacles
            if any(
                _overlaps(candidate, box, 0.0)
                for candidate in [initial_ink, *(body_boxes or [])]
            )
        ]
        if collisions:
            geometry["collision_evidence"] = [
                {"reference": reference, "box": [round(value, 4) for value in box]}
                for reference, box in collisions
            ]
            failure = REVERT_COLLISION
    if failure is not None:
        _put_back(stored)
        return _refusal(geometry, failure)

    reserve_box = (left, second_line_ink[1], reserve_edge, first_line_ink[3])
    contract = DropCapGeometryContract(
        source_ref=str(base["paragraph"]),
        page=int(base["page"]),
        article_id=getattr(intent, "article_id", None),
        character_count=len(glyph),
        policy=intent.target_policy,
        ink=BoxEvidence(initial_ink, "font_glyph_metrics"),
        reserve=BoxEvidence(reserve_box, "first_two_body_ink_lines"),
        collision=(),
        color=ColorEvidence(
            _rgb_hex(intent.source_color.fill),
            _rgb_hex(intent.source_color.stroke),
            None,
        ),
    )
    geometry["detector_contract"] = contract.to_record()
    return {
        **geometry,
        "set": True,
        "reverted": False,
        "revert_reason": None,
        "_target_index": target_index,
    }


def set_one(
    paragraph,
    regime: Regime,
    config: RenderConfig,
    base: dict,
    intent: drop_cap_intent.DropCapIntent | None = None,
    glyph_metric_resolver=None,
    geometry_guard: DecorativeGeometryGuard | None = None,
) -> dict:
    """Set one paragraph's opening character enlarged, or say why it was not.

    The paragraph is put back exactly as it stood on every refusal, and the
    refusal names itself. Geometry outside the paragraph is read but never
    mutated.
    """
    if (
        intent is not None
        and intent.target_policy
        == drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL
    ):
        return _set_english_raised_initial(
            paragraph,
            regime,
            config,
            base,
            intent,
            glyph_metric_resolver,
            geometry_guard,
        )
    if (
        intent is not None
        and intent.target_policy
        == drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL
    ):
        return _set_chinese_two_line_initial(
            paragraph,
            regime,
            config,
            base,
            intent,
            glyph_metric_resolver,
            geometry_guard,
        )
    characters = [c for c in paragraph_characters(paragraph) if c.box is not None]
    if not characters or paragraph.box is None:
        return _refusal(base, REVERT_TOO_FEW_LINES)
    lines = group_lines(list(characters), _line_overlap_min())
    if len(lines) <= regime.lines:
        return _refusal(base, REVERT_TOO_FEW_LINES)

    baselines = [float(line[0].box.y) for line in lines]
    steps = [
        baselines[position] - baselines[position + 1]
        for position in range(len(baselines) - 1)
    ]
    steps = [step for step in steps if step > 0]
    if not steps:
        return _refusal(base, REVERT_NO_ADVANCE)
    advance = statistics.median(steps)

    sizes = [
        float(c.pdf_style.font_size)
        for c in characters
        if c.pdf_style is not None and c.pdf_style.font_size
    ]
    if not sizes:
        return _refusal(base, REVERT_NO_ADVANCE)
    body_size = statistics.median(sizes)

    eligible = drop_cap_intent.eligible_initial(
        characters,
        (
            drop_cap_intent.POLICY_ALPHABETIC
            if intent is None
            else intent.target_policy
        ),
    )
    if eligible is None:
        return _refusal(base, REVERT_NOT_A_LETTER)
    target_index, initial = eligible
    glyph = initial.char_unicode or ""
    if not any(unicodedata.category(char).startswith("L") for char in glyph):
        return _refusal({**base, "initial": glyph}, REVERT_NOT_A_LETTER)

    base = {**base, "initial": glyph}
    initial_size = regime.lines * advance
    old_size = (
        float(initial.pdf_style.font_size)
        if initial.pdf_style is not None and initial.pdf_style.font_size
        else body_size
    )
    initial_width = _width(initial) * (initial_size / old_size) if old_size else 0.0
    reserve = initial_width + regime.gutter_em * body_size
    if regime.grid == GRID_EM and body_size > 0:
        reserve = math.ceil(reserve / body_size) * body_size

    left = float(paragraph.box.x)
    right = float(paragraph.box.x2)
    if (right - left) - reserve < config.min_line_capacity_em * body_size:
        return _refusal(base, REVERT_TOO_NARROW)

    first_baseline = baselines[0]
    stored = _take(characters)
    rest = [c for c in characters if c is not initial]

    initial_style = il_version_1.PdfStyle(
        font_id=None if initial.pdf_style is None else initial.pdf_style.font_id,
        font_size=initial_size,
        graphic_state=(
            None if initial.pdf_style is None else initial.pdf_style.graphic_state
        ),
    )
    initial.pdf_style = (
        initial_style
        if intent is None
        else drop_cap_intent.apply_color(initial_style, intent.source_color)
    )
    top = first_baseline + body_size
    initial.box.x = left
    initial.box.x2 = left + initial_width
    initial.box.y2 = top
    initial.box.y = top - initial_size
    initial.advance = initial_width

    assigned = _pack(
        rest,
        regime,
        {
            "left": left,
            "right": right,
            "reserve": reserve,
            "advance": advance,
            "first_baseline": first_baseline,
        },
    )
    reach = _ink_reach(characters)
    slack = config.edge_slack_pt
    fits = reach is not None and (
        reach[0] >= left - slack
        and reach[1] >= float(paragraph.box.y) - slack
        and reach[2] <= right + slack
        and reach[3] <= float(paragraph.box.y2) + slack
    )
    if not fits:
        _put_back(stored)
        return _refusal(
            {**base, "reach": None if reach is None else [round(v, 4) for v in reach]},
            REVERT_WILL_NOT_FIT,
        )

    def offset_of(index: int) -> float | None:
        members = [
            character
            for character, line in zip(rest, assigned, strict=True)
            if line == index and not _is_whitespace(character)
        ]
        if not members:
            return None
        return round(min(float(c.box.x) for c in members) - left, 4)

    shifts = [offset_of(index) for index in range(regime.lines)]
    return {
        **base,
        "set": True,
        "reverted": False,
        "revert_reason": None,
        "body_size": round(body_size, 4),
        "line_advance": round(advance, 4),
        "initial_size": round(initial_size, 4),
        "reserve": round(reserve, 4),
        "lines_before": len(lines),
        "lines_after": (max(assigned) + 1) if assigned else 1,
        "first_line_shifts": shifts,
        "resume_shift": offset_of(regime.lines),
        "box": _quad(paragraph.box),
        "reach": [round(v, 4) for v in reach],
        "_target_index": target_index,
    }


def _blank(reference: str, label: int, decision: str, target: str, regime) -> dict:
    return {
        "paragraph": reference,
        "page": label,
        "decision": decision,
        "target_lang": target,
        "regime": regime,
        "target_policy": None,
        "initial": None,
        "initial_char_count": None,
        "set": False,
        "reverted": False,
        "revert_reason": None,
        "issue": None,
        "body_size": None,
        "line_advance": None,
        "initial_size": None,
        "reserve": None,
        "gutter": None,
        "reserve_lines": None,
        "lines_before": None,
        "lines_after": None,
        "line_baselines": None,
        "body_start_x": None,
        "first_line_shifts": None,
        "resume_shift": None,
        "second_line_start_x": None,
        "third_line_start_x": None,
        "box": None,
        "body_box": None,
        "reach": None,
        "initial_ink_box": None,
        "body_ink_box": None,
        "first_line_ink_box": None,
        "first_line_ink_top": None,
        "second_line_ink_box": None,
        "second_line_ink_bottom": None,
        "ink_top_delta": None,
        "first_line_ink_bottom": None,
        "ink_bottom_delta": None,
        "page_box": None,
        "article_boxes": None,
        "collision_evidence": None,
        "color_evidence": None,
        "style_evidence": None,
        "detector_contract": None,
        "transaction": None,
        "render_state": None,
        "validation": None,
    }


def _box_tuple(value) -> BoxTuple | None:
    if value is None:
        return None
    coordinates = tuple(getattr(value, name, None) for name in ("x", "y", "x2", "y2"))
    if any(coordinate is None for coordinate in coordinates):
        return None
    box = tuple(float(coordinate) for coordinate in coordinates)
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def _page_envelope(page) -> BoxTuple | None:
    for name in ("cropbox", "mediabox"):
        holder = getattr(page, name, None)
        box = _box_tuple(getattr(holder, "box", None))
        if box is not None:
            return box
    return None


def _article_envelopes(article, label: int) -> tuple[BoxTuple, ...]:
    slots = tuple(
        tuple(float(value) for value in slot.box)
        for slot in article.slots
        if slot.page == label
    )
    if slots:
        return slots
    source_boxes = []
    for element in article.elements:
        if element.page != label or element.source_box is None:
            continue
        box = tuple(float(value) for value in element.source_box)
        if box[2] > box[0] and box[3] > box[1]:
            source_boxes.append(box)
    envelope = _union(source_boxes)
    return () if envelope is None else (envelope,)


def _without_mutable_paragraph(inventory, reference: str):
    return fixed_assets.FixedAssetInventory(
        assets=tuple(
            asset
            for asset in inventory.assets
            if not (
                asset.reference == reference
                and asset.asset_type == fixed_assets.FURNITURE_TYPE
            )
        ),
        page_sizes=inventory.page_sizes,
    )


def _decorative_guard(
    page,
    local_page: int,
    index: int,
    local_reference: str,
    intent,
    article_document_ir,
    inventory,
) -> DecorativeGeometryGuard:
    paragraph = page.pdf_paragraph[index]
    body_box = _box_tuple(paragraph.box)
    article_boxes: tuple[BoxTuple, ...] = ()
    if article_document_ir is not None:
        owner = article_document_ir.by_element.get(local_reference)
        article = article_document_ir.article(owner) if owner == intent.article_id else None
        if article is not None:
            article_boxes = _article_envelopes(article, local_page)
    obstacles: dict[str, BoxTuple] = {}
    for asset in inventory.page_assets(local_page):
        if (
            not asset.protected
            or asset.bbox is None
            or asset.reference == local_reference
        ):
            continue
        box = tuple(float(value) for value in asset.bbox)
        if body_box is not None and _contains(box, body_box, 0.0):
            continue
        obstacles[asset.reference] = box
    for other_index, other in enumerate(page.pdf_paragraph or ()):
        if other_index == index:
            continue
        other_characters = [
            character
            for character in paragraph_characters(other)
            if character.box is not None
        ]
        box = _ink_reach(other_characters) or _box_tuple(other.box)
        if box is None:
            continue
        obstacles[drop_cap.paragraph_reference(local_page, other_index)] = box
    return DecorativeGeometryGuard(
        page_box=_page_envelope(page),
        article_boxes=article_boxes,
        obstacles=tuple(sorted(obstacles.items())),
    )


def _record_render_issue(
    intent,
    reference: str,
    detail: str,
    kind: str = drop_cap_intent.ISSUE_RENDER_FAILED,
) -> None:
    issue = drop_cap_intent.DropCapIssue(
        kind=kind,
        source_ref=reference,
        detail=detail,
    )
    if issue not in intent.issues:
        intent.issues.append(issue)


def kept_verdict() -> str:
    """The verdict this pass answers for: the one that is not the merge's name.

    The vocabulary is two words and the other one names the pass that merges, so
    naming this one here would be naming it twice. Refused where the vocabulary
    is not two words, because a third verdict is a decision nobody has taken.
    """
    verdicts = drop_cap.decision_vocabulary()
    other = tuple(name for name in verdicts if name != drop_cap.DECISION_FLATTEN)
    if len(other) != 1:
        raise DropCapRenderError(
            f"the verdict vocabulary is {sorted(verdicts)}; this pass answers "
            f"for the one verdict that is not {drop_cap.DECISION_FLATTEN!r}"
        )
    return other[0]


def _chain_joint_success(
    translation_config,
    paragraph,
    physical_reference: str,
    local_reference: str,
) -> bool:
    """Prove a chain member was jointly translated before decorating it."""
    chain_id = getattr(paragraph, "chain_id", None)
    if not chain_id:
        return True
    chain_index = getattr(paragraph, "chain_index", None)
    if (
        not isinstance(chain_index, int)
        or isinstance(chain_index, bool)
        or chain_index < 0
    ):
        return False
    path = Path(translation_config.get_working_file_path(CHAIN_REPORT_NAME))
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    outcomes = payload.get("chains") if isinstance(payload, dict) else None
    if not isinstance(outcomes, list):
        return False
    matches = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        runtime_refs = outcome.get("runtime_source_refs")
        physical_refs = outcome.get("ordered_source_refs")
        identities = {outcome.get("chain_id"), outcome.get("canonical_chain_id")}
        if (
            chain_id not in identities
            or not isinstance(runtime_refs, list)
            or not isinstance(physical_refs, list)
            or len(runtime_refs) != len(physical_refs)
            or chain_index >= len(runtime_refs)
            or runtime_refs[chain_index] != local_reference
            or physical_refs[chain_index] != physical_reference
        ):
            continue
        members = outcome.get("members")
        member_order_holds = bool(
            isinstance(members, list)
            and (
                chain_index < len(members)
                and isinstance(members[chain_index], dict)
                and members[chain_index].get("chain_index") == chain_index
                and members[chain_index].get("runtime_source_ref")
                == local_reference
                and members[chain_index].get("source_ref") == physical_reference
            )
        )
        if (
            outcome.get("outcome") == "joint_success"
            and outcome.get("fallback_reason") is None
            and outcome.get("joint_call_count") == 1
            and member_order_holds
        ):
            matches.append(outcome)
    return len(matches) == 1


def _render_validation(
    translation_config,
    paragraph,
    physical_reference: str,
    local_reference: str,
    decision: str,
    intent,
    regime,
    article_document_ir,
) -> dict:
    page, separator, index = physical_reference.partition("#")
    physical_valid = bool(
        separator == "#"
        and page.startswith("p")
        and page[1:].isdigit()
        and int(page[1:]) > 0
        and index.isdigit()
    )
    characters = [
        character
        for character in paragraph_characters(paragraph)
        if character.box is not None
    ]
    policy = None if intent is None else intent.target_policy
    known_policies = {
        drop_cap_intent.POLICY_ALPHABETIC,
        drop_cap_intent.POLICY_CJK_IDEOGRAPH,
        drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL,
        drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL,
    }
    canonical_owner = (
        None
        if article_document_ir is None
        else article_document_ir.by_element.get(local_reference)
    )
    checks = {
        "candidate_valid": bool(getattr(paragraph, "drop_cap_candidate", False)),
        "decision_current": bool(
            intent is not None and intent.decision == decision
        ),
        "flatten_success": bool(
            intent is not None
            and intent.flatten_status == drop_cap_intent.FLATTEN_APPLIED
        ),
        "target_initial_available": bool(
            intent is not None
            and drop_cap_intent.eligible_initial(characters, policy) is not None
        ),
        "geometry_policy_known": bool(regime is not None and policy in known_policies),
        "current_intent_generation": bool(
            intent is not None
            and intent.generation
            == drop_cap_intent.current_generation(translation_config)
        ),
        "canonical_source_ref": bool(
            physical_valid
            and intent is not None
            and canonical_owner == intent.article_id
        ),
        "chain_joint_success": _chain_joint_success(
            translation_config,
            paragraph,
            physical_reference,
            local_reference,
        ),
    }
    return {
        "checks": checks,
        "valid": all(checks.values()),
        "failed": [name for name, holds in checks.items() if not holds],
        "intent_generation": None if intent is None else intent.generation,
        "registry_generation": drop_cap_intent.current_generation(
            translation_config
        ),
        "physical_source_ref": physical_reference,
        "local_source_ref": local_reference,
        "base_transaction_generation": None,
        "transaction_generation": None,
        "post_render": None,
    }


def _post_render_validation(
    paragraph,
    intent,
    outcome: dict,
    before_text: str,
) -> tuple[str | None, dict]:
    characters = [
        character
        for character in paragraph_characters(paragraph)
        if character.box is not None
    ]
    target_index = outcome.get("_target_index")
    contract = outcome.get("detector_contract")
    geometry = bool(
        outcome.get("set")
        and isinstance(target_index, int)
        and 0 <= target_index < len(characters)
        and isinstance(outcome.get("reach"), list)
        and len(outcome["reach"]) == 4
        and (
            contract is None
            or not contract.get("missing_fields", ["contract_invalid"])
        )
    )
    color = False
    if geometry:
        actual = drop_cap_intent.freeze_color(
            characters[target_index].pdf_style
        ).fill.rgb
        color = drop_cap_intent.colors_close(
            actual,
            intent.source_color.fill.rgb,
            drop_cap.load_drop_cap_config().color_tolerance,
        )
    rendered_text = "".join(character.char_unicode or "" for character in characters)
    coverage = rendered_text == before_text == (paragraph.unicode or "")
    collision = not outcome.get("collision_evidence") and (
        contract is None or not contract.get("collision")
    )
    checks = {
        "drop_cap_geometry": geometry,
        "color": color,
        "coverage": coverage,
        "collision": collision,
    }
    reason = None
    if not geometry:
        reason = REVERT_POST_GEOMETRY
    elif not color:
        reason = REVERT_POST_COLOR
    elif not coverage:
        reason = REVERT_POST_COVERAGE
    elif not collision:
        reason = REVERT_POST_COLLISION
    return reason, {"checks": checks, "valid": reason is None}


def _restore_dataclass(target, snapshot) -> None:
    for name in target.__dataclass_fields__:
        setattr(target, name, copy.deepcopy(getattr(snapshot, name)))


class _RenderPassTransaction:
    """Restore all selected pages and active intents unless the pass commits."""

    def __init__(self, translation_config, docs):
        self._translation_config = translation_config
        self._pages = [(page, copy.deepcopy(page)) for page in docs.page]
        self._intent_generation = drop_cap_intent.current_generation(
            translation_config
        )
        self._intents = copy.deepcopy(
            list(drop_cap_intent.intents_for(translation_config).values())
        )
        self._committed = False

    def __enter__(self):
        return self

    def commit(self) -> None:
        self._committed = True

    def _restore_intents(self) -> None:
        drop_cap_intent.clear(self._translation_config)
        for generation in range(1, self._intent_generation + 1):
            intents = (
                copy.deepcopy(self._intents)
                if generation == self._intent_generation
                else []
            )
            drop_cap_intent.replace_intents(self._translation_config, intents)

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is not None or not self._committed:
            for page, snapshot in self._pages:
                _restore_dataclass(page, snapshot)
            self._restore_intents()
        return False


class _ParagraphAttempt:
    """Restore one paragraph after a typed render refusal."""

    def __init__(self, paragraph):
        self._paragraph = paragraph
        self._snapshot = copy.deepcopy(paragraph)
        self._committed = False

    def __enter__(self):
        return self

    def commit(self) -> None:
        self._committed = True

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is not None or not self._committed:
            _restore_dataclass(self._paragraph, self._snapshot)
        return False


def _apply_render_pass(
    translation_config,
    docs,
    article_document_ir=None,
    typesetting_stage=None,
) -> dict:
    if article_document_ir is None:
        raise DropCapRenderError("drop-cap render requires canonical ArticleDocumentIR")
    from babeldoc.magazine import hitl

    config = load_render_config()
    target = getattr(translation_config, "lang_out", "") or ""
    regime = config.regime_for(target)
    default = drop_cap.load_drop_cap_config().default_for(target)
    keep = kept_verdict()
    glyph_metric_resolver = getattr(typesetting_stage, "glyph_ink_metrics", None)
    inventory = fixed_assets.build_inventory(
        docs,
        article_document_ir=article_document_ir,
    )

    def inventory_builder():
        return fixed_assets.build_inventory(
            docs,
            article_document_ir=article_document_ir,
        )

    records: list[dict] = []
    labeled_positions = [
        (label, position + 1, position)
        for position, (label, _page) in enumerate(hitl.labeled_pages(docs))
    ]
    for physical_label, local_page, position in labeled_positions:
        paragraph_count = len(docs.page[position].pdf_paragraph or ())
        for index in range(paragraph_count):
            page = docs.page[position]
            paragraph = page.pdf_paragraph[index]
            decision, _source = drop_cap.resolve_decision(paragraph, default)
            if decision != keep:
                continue
            physical_reference = drop_cap.paragraph_reference(physical_label, index)
            local_reference = drop_cap.paragraph_reference(local_page, index)
            intent = drop_cap_intent.intent_for(
                translation_config, physical_reference
            )
            blank = _blank(
                physical_reference,
                physical_label,
                decision,
                target,
                None if regime is None else regime.name,
            )
            blank["target_policy"] = None if intent is None else intent.target_policy
            before_text = "".join(
                character.char_unicode or ""
                for character in paragraph_characters(paragraph)
                if character.box is not None
            )
            validation = _render_validation(
                translation_config,
                paragraph,
                physical_reference,
                local_reference,
                decision,
                intent,
                regime,
                article_document_ir,
            )
            blank["validation"] = validation
            with _ParagraphAttempt(paragraph) as attempt:
                if not validation["valid"]:
                    outcome = {
                        **blank,
                        "revert_reason": REVERT_INVALID_INTENT,
                        "issue": ", ".join(validation["failed"]),
                        "render_state": STATE_INVALID_INTENT,
                    }
                elif (
                    regime.name == REGIME_INITIAL
                    and intent.target_policy
                    != drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL
                ):
                    outcome = _refusal(blank, REVERT_POLICY)
                else:
                    guard = _decorative_guard(
                        page,
                        local_page,
                        index,
                        local_reference,
                        intent,
                        article_document_ir,
                        inventory,
                    )
                    attempt_inventory = _without_mutable_paragraph(
                        inventory, local_reference
                    )
                    outcome = set_one(
                        paragraph,
                        regime,
                        config,
                        blank,
                        intent=intent,
                        glyph_metric_resolver=glyph_metric_resolver,
                        geometry_guard=guard,
                    )
                    if outcome["set"]:
                        post_reason, post = _post_render_validation(
                            paragraph,
                            intent,
                            outcome,
                            before_text,
                        )
                        validation["post_render"] = post
                        if post_reason is not None:
                            outcome = _refusal(outcome, post_reason)
                    if outcome["set"]:
                        after_inventory = inventory_builder()
                        comparison = fixed_assets.compare(
                            attempt_inventory,
                            _without_mutable_paragraph(
                                after_inventory, local_reference
                            ),
                            config.edge_slack_pt,
                        )
                        if not comparison.holds:
                            outcome = _refusal(outcome, REVERT_FIXED_ASSET)
                        else:
                            inventory = after_inventory
                if outcome["render_state"] is None:
                    outcome["render_state"] = (
                        STATE_COMMITTED
                        if outcome["set"]
                        else STATE_RENDER_ROLLBACK
                    )
                if outcome["set"]:
                    attempt.commit()
            target_index = outcome.pop("_target_index", None)
            if outcome["set"] and target_index is not None:
                paragraph = docs.page[position].pdf_paragraph[index]
                characters = [
                    character
                    for character in paragraph_characters(paragraph)
                    if character.box is not None
                ]
                target_character = characters[target_index]
                intent.render_status = drop_cap_intent.RENDER_APPLIED
                intent.target_char = target_character.char_unicode or ""
                intent.target_index = target_index
                intent.target_style_hash = drop_cap_intent.style_hash(
                    target_character.pdf_style
                )
            elif intent is not None and outcome["render_state"] == STATE_INVALID_INTENT:
                intent.render_status = drop_cap_intent.RENDER_SKIPPED
                detail = outcome["issue"] or str(outcome["revert_reason"])
                _record_render_issue(
                    intent,
                    physical_reference,
                    detail,
                    drop_cap_intent.ISSUE_INVALID_INTENT,
                )
            elif intent is not None:
                intent.render_status = drop_cap_intent.RENDER_FAILED
                detail = outcome["issue"] or str(outcome["revert_reason"])
                outcome["issue"] = detail
                _record_render_issue(intent, physical_reference, detail)
            after_text = "".join(
                character.char_unicode or ""
                for character in paragraph_characters(
                    docs.page[position].pdf_paragraph[index]
                )
                if character.box is not None
            )
            outcome["_report_target_index"] = target_index
            outcome["_before_target_sha256"] = hashlib.sha256(
                before_text.encode("utf-8")
            ).hexdigest()
            outcome["_after_target_sha256"] = hashlib.sha256(
                after_text.encode("utf-8")
            ).hexdigest()
            records.append(outcome)

    for item in records:
        reason = item["revert_reason"]
        if reason is not None and reason not in config.revert_reasons:
            raise DropCapRenderError(
                f"{REPORT_NAME}: a record names reason {reason!r}, and "
                f"{CONFIG_PATH.name} declares {sorted(config.revert_reasons)}"
            )

    record = as_record(config, target, regime, records)
    _write_report(translation_config, record)
    drop_cap_intent.write_report(translation_config)
    logger.debug(
        "drop cap render: %d kept opening(s), %d set",
        record["totals"]["decided"],
        record["totals"]["set"],
    )
    return record


def apply(
    translation_config,
    docs,
    article_document_ir=None,
    typesetting_stage=None,
) -> dict | None:
    if not enabled(translation_config):
        return None
    if article_document_ir is None:
        raise DropCapRenderError("drop-cap render requires canonical ArticleDocumentIR")

    intents = drop_cap_intent.intents_for(translation_config)
    if not intents:
        # Validate both declarations before taking the empty fast path.  A
        # dangling keep verdict/default with no intent must still reach the
        # ordinary validator rather than being silently accepted.
        config = load_render_config()
        target = getattr(translation_config, "lang_out", "") or ""
        regime = config.regime_for(target)
        default = drop_cap.load_drop_cap_config().default_for(target)
        keep = kept_verdict()
        has_keep_without_intent = any(
            drop_cap.resolve_decision(paragraph, default)[0] == keep
            for page in docs.page
            for paragraph in page.pdf_paragraph or ()
        )
        if not has_keep_without_intent:
            record = as_record(config, target, regime, [])
            _write_report(translation_config, record)
            drop_cap_intent.write_report(translation_config)
            logger.debug("drop cap render: 0 kept opening(s), 0 set")
            return record

    with _RenderPassTransaction(translation_config, docs) as transaction:
        record = _apply_render_pass(
            translation_config,
            docs,
            article_document_ir=article_document_ir,
            typesetting_stage=typesetting_stage,
        )
        transaction.commit()
    return record


def as_record(
    config: RenderConfig,
    target_lang: str,
    regime: Regime | None,
    records: list[dict],
) -> dict:
    committed = sum(1 for item in records if item["set"])
    failures = len(records) - committed
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success" if failures == 0 else "failure",
        "switch": SWITCH,
        "target_lang": target_lang,
        "regime": None if regime is None else regime.name,
        "regime_lines": None if regime is None else regime.lines,
        "regime_gutter_em": None if regime is None else regime.gutter_em,
        "break_rule": None if regime is None else regime.break_rule,
        "grid": None if regime is None else regime.grid,
        "edge_slack_pt": config.edge_slack_pt,
        "min_line_capacity_em": config.min_line_capacity_em,
        "raised_initial_cap_height_lines": config.raised_initial_cap_height_lines,
        "raised_initial_min_font_scale": config.raised_initial_min_font_scale,
        "raised_initial_max_font_scale": config.raised_initial_max_font_scale,
        "ink_bottom_tolerance_pt": config.ink_bottom_tolerance_pt,
        "ink_anchor_tolerance_pt": config.ink_anchor_tolerance_pt,
        "revert_reasons": list(config.revert_reasons),
        # Named here so that a gate reads the relation off the pass that owns it
        # rather than off a list kept somewhere else. The hanging punctuation
        # ledger is written while the general packer lays a paragraph out, and a
        # paragraph this lane re-packs is packed strictly inside its own box, so
        # no ledger entry of that paragraph's survives it. The column reflow is
        # the other way round: it runs after this one and measures the ink this
        # one leaves, so what it closes is measured off the finished shape.
        "excluded_from": ["typeset_hang"],
        "compatible_with": ["column_reflow"],
        "totals": {
            "active": len(records),
            "committed": committed,
            "failure": failures,
            "decided": len(records),
            "set": committed,
            "reverted": sum(1 for item in records if item["reverted"]),
            "by_state": {
                state: sum(1 for item in records if item["render_state"] == state)
                for state in (
                    STATE_INVALID_INTENT,
                    STATE_RENDER_ROLLBACK,
                    STATE_COMMITTED,
                )
            },
            "by_reason": {
                name: sum(1 for item in records if item["revert_reason"] == name)
                for name in config.revert_reasons
            },
        },
        "paragraphs": records,
    }


def _persisted_paragraph(item: dict) -> dict:
    style_evidence = item.get("style_evidence")
    metric_source = (
        style_evidence.get("metric_source")
        if isinstance(style_evidence, dict)
        else None
    )
    committed = bool(item.get("set"))
    record = {
        "source_ref": item.get("paragraph"),
        "decision": item.get("decision"),
        "target_char": item.get("initial"),
        "target_index": item.get("_report_target_index"),
        "direction_policy": item.get("target_policy"),
        "metric_source": metric_source,
        "initial_box": item.get("initial_ink_box"),
        "before_target_sha256": item.get("_before_target_sha256"),
        "after_target_sha256": item.get("_after_target_sha256"),
        "status": STATUS_COMMITTED if committed else STATUS_FAILURE,
        "failure_reason": None if committed else item.get("revert_reason"),
    }
    expected = set(PERSISTED_FIELDS)
    if set(record) != expected or set(record) != set(load_render_config().report_fields):
        raise DropCapRenderError(
            f"{REPORT_NAME}: persisted fields disagree with the declared schema"
        )
    return record


def _persisted_record(record: dict) -> dict:
    persisted = copy.deepcopy(record)
    persisted["paragraphs"] = [
        _persisted_paragraph(item) for item in record.get("paragraphs", ())
    ]
    return persisted


def _write_report(translation_config, record: dict) -> Path:
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            _persisted_record(record),
            f,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path
