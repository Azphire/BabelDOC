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

From the page, not from the configuration. An initial standing two lines deep is
two line advances tall, and the advance is measured off the paragraph's own
baselines, so a column set at any body size gets an initial in proportion to it
and no line spacing is declared twice.

Where the initial is put
------------------------

Its em box top is aligned with the first line's em box top. That is the one
placement the box allows: the typesetting stage sets a paragraph so that the
first line's em box top touches ``box.y2`` exactly, so an initial hung any
higher stands outside the paragraph's own box. Aligning the tops has a second
property that is arithmetic rather than luck -- an initial ``lines * advance``
tall whose top sits at ``baseline + em`` has its bottom at
``baseline + em - lines * advance``, which is exactly where line ``lines + 1``
puts its own em box top. So the first ``lines`` lines are set beside the
initial, the line after them runs the full measure, and neither the box above
nor the line below is reached into.

What a refusal leaves
---------------------

The paragraph exactly as the typesetting stage left it, which is the shape
``flatten`` produces. Every character's box, size and advance is taken before
anything moves and put back on any refusal, so no refusal can leave a hole where
a line should be or a fragment of a first word stranded beside one.
"""

from __future__ import annotations

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
from babeldoc.magazine.chain_signals import group_lines
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "drop_cap_render.json"

REPORT_NAME = "drop_cap_render.report.json"

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
    ):
        _require(
            name in reasons,
            f"{source}: revert_reasons omits {name!r}, which a record may name",
        )
    for key in ("min_line_capacity_em", "edge_slack_pt"):
        _require(key in parameters, f"{source}: missing {key}")
    return RenderConfig(
        regimes=regimes,
        by_target=by_target,
        min_line_capacity_em=float(parameters["min_line_capacity_em"]),
        edge_slack_pt=float(parameters["edge_slack_pt"]),
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


def set_one(
    paragraph,
    regime: Regime,
    config: RenderConfig,
    base: dict,
    intent: drop_cap_intent.DropCapIntent | None = None,
) -> dict:
    """Set one paragraph's opening character enlarged, or say why it was not.

    The paragraph is put back exactly as it stood on every refusal, and the
    refusal names itself. Nothing outside the paragraph is read or written.
    """
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
        "initial": None,
        "set": False,
        "reverted": False,
        "revert_reason": None,
        "body_size": None,
        "line_advance": None,
        "initial_size": None,
        "reserve": None,
        "lines_before": None,
        "lines_after": None,
        "first_line_shifts": None,
        "resume_shift": None,
        "box": None,
        "reach": None,
    }


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


def apply(translation_config, docs, run_trace=None) -> dict | None:
    """Set every kept opening of one document. None where the switch is down.

    Returns the record it wrote, so a caller holding the document can assert
    about the pass without reading the sidecar back.
    """
    if not enabled(translation_config):
        return None
    from babeldoc.magazine import hitl

    config = load_render_config()
    target = getattr(translation_config, "lang_out", "") or ""
    regime = config.regime_for(target)
    default = drop_cap.load_drop_cap_config().default_for(target)
    keep = kept_verdict()

    records: list[dict] = []
    for label, page in hitl.labeled_pages(docs):
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            decision, _source = drop_cap.resolve_decision(paragraph, default)
            if decision != keep:
                continue
            reference = drop_cap.paragraph_reference(label, index)
            intent = drop_cap_intent.intent_for(translation_config, reference)
            if intent is None:
                raise DropCapRenderError(
                    f"{reference}: kept decision has no frozen drop-cap intent"
                )
            if intent.flatten_status == drop_cap_intent.FLATTEN_FAILED:
                intent.render_status = drop_cap_intent.RENDER_SKIPPED
                if run_trace is not None:
                    run_trace.record_drop_cap_event(
                        {
                            "event": "render_blocked",
                            "source_ref": reference,
                            "flatten_status": intent.flatten_status,
                        }
                    )
                continue
            blank = _blank(
                reference,
                label,
                decision,
                target,
                None if regime is None else regime.name,
            )
            outcome = (
                blank
                if regime is None
                else set_one(paragraph, regime, config, blank, intent=intent)
            )
            target_index = outcome.pop("_target_index", None)
            if outcome["set"] and target_index is not None:
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
            elif regime is None:
                intent.render_status = drop_cap_intent.RENDER_SKIPPED
            else:
                intent.render_status = drop_cap_intent.RENDER_FAILED
            if run_trace is not None:
                run_trace.record_drop_cap_event(
                    {
                        "event": "target_initial_style",
                        "source_ref": reference,
                        "render_status": intent.render_status,
                        "target_char": intent.target_char,
                        "target_index": intent.target_index,
                        "target_style_hash": intent.target_style_hash,
                    }
                )
            records.append(outcome)

    expected = set(config.report_fields)
    for item in records:
        if set(item) != expected:
            raise DropCapRenderError(
                f"{REPORT_NAME}: a record carries {sorted(item)}, and "
                f"{CONFIG_PATH.name} declares {sorted(expected)}"
            )
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


def as_record(
    config: RenderConfig,
    target_lang: str,
    regime: Regime | None,
    records: list[dict],
) -> dict:
    return {
        "switch": SWITCH,
        "target_lang": target_lang,
        "regime": None if regime is None else regime.name,
        "regime_lines": None if regime is None else regime.lines,
        "regime_gutter_em": None if regime is None else regime.gutter_em,
        "break_rule": None if regime is None else regime.break_rule,
        "grid": None if regime is None else regime.grid,
        "edge_slack_pt": config.edge_slack_pt,
        "min_line_capacity_em": config.min_line_capacity_em,
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
            "decided": len(records),
            "set": sum(1 for item in records if item["set"]),
            "reverted": sum(1 for item in records if item["reverted"]),
            "by_reason": {
                name: sum(1 for item in records if item["revert_reason"] == name)
                for name in config.revert_reasons
            },
        },
        "paragraphs": records,
    }


def _write_report(translation_config, record: dict) -> Path:
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path
