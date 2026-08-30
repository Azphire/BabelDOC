"""Continuity signals for one adjacent page boundary.

An article that runs over a page break leaves traces in the geometry of the two
pages: an unfinished sentence at the foot of one, a full measure last line, the
same type set at the head of the next, and both endpoints sitting where a
column hands over to the next. This module turns each of those into one pure
function of the intermediate language, and combines them into a score.

Every function here reads only geometry, counts, character statistics and the
declared policy flags of the two pages. Nothing inspects a publication or names
a page type, and every number it compares against comes from
``configs/chain_detection.json``.

A boundary is not one pair of paragraphs but one pair per declared endpoint
class: running text hands over to running text, and a display line broken
across a spread hands over to the line that completes it. Which classes exist,
which of them may pair with which, and how each pairing weighs the signals are
all declared in the configuration; this module only reads the declaration. A
boundary is scored once per allowed pairing and takes the strongest verdict any
of them supports.

A boundary is also not only a page break. A magazine sets several columns to a
sheet, and a sentence broken between two of them is the same handover as one
broken across a break; the page walk cannot reach it by construction, because
both ends sit on one page. The two kinds are scored by the same signals and the
same weights, and differ in three declared ways: the two signals that cannot
mean inside a page what they mean across a break enter as stated constants, the
page kind qualifies a column boundary through a different flag, and one further
gate asks whether the receiving column's head has clear space above it.

The stage runs after StylesAndFormulas, which replaces the line compositions
built by ParagraphFinder with style runs. Line structure is therefore rebuilt
here from the character boxes that survive, by the same vertical banding
ParagraphFinder itself uses; the reconstruction reproduces the boxes of the
lines it replaced.
"""

from __future__ import annotations

import json
import statistics
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.line_split import excludes_chain_endpoint
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import Parameter
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("chain_detection.json")

# Signals in report order. Scoring is by name, through the weight_<signal> key.
SIGNAL_NAMES: tuple[str, ...] = (
    "tail_no_terminal_punct",
    "tail_line_fill",
    "style_continuity",
    "body_label_pair",
    "column_position",
    "opener_prior",
)

WEIGHT_PREFIX = "weight_"

# Suffix under which a bounded entry declares its range. The same convention
# validate_bounded_config applies to the flat parameters, repeated here because
# a weight declared inside a pairing is bounded by the range its flat namesake
# declares.
RANGE_SUFFIX = "_allowed_range"

# The section declaring the endpoint classes and the pairings between them.
PAIR_CLASSES_KEY = "pair_classes"
CLASSES_KEY = "classes"
PAIRS_KEY = "pairs"
TAIL_CLASS_KEY = "tail_class"
HEAD_CLASS_KEY = "head_class"
PAIR_WEIGHTS_KEY = "weights"

# Keys the parsed pairing section is published under, alongside the bounded
# parameters, so that one loaded configuration carries everything scoring needs.
PAIR_RULES_KEY = "pair_rules"
CLASS_LABELS_KEY = "pair_class_labels"

# The policy flag the page level prior is read through. The prior enters the
# score only by this name, which is what keeps page type names out of the code.
OPENER_POLICY_FLAG = "starts_article"

# The policy flag that qualifies an endpoint for chaining at all.
ELIGIBILITY_POLICY_FLAG = "chain_eligible"

# The policy flag that keeps a page of records out of column boundaries. A page
# setting one record to a line hands nothing over between its columns, so it
# offers no column boundary at all. ``chain_eligible`` is deliberately not read
# for a column boundary: it answers whether running text continues into or out
# of a page, which is a question about a page break rather than about a handover
# internal to one page, and reading it here would withdraw a real in-page
# handover on the strength of a page level answer to a different question.
LINE_STRUCTURE_POLICY_FLAG = "preserve_line_structure"

# What a boundary joins.
BOUNDARY_PAGE = "page"
BOUNDARY_COLUMN = "column"

# How two columns of one page were paired. ``column_adjacent`` is band n against
# band n+1. ``body_next`` skips one band, which is the handover hidden behind a
# band offering no endpoint the pair rules take -- a display line set in its own
# band between two text columns is such a band.
PAIRING_COLUMN_ADJACENT = "column_adjacent"
PAIRING_BODY_NEXT = "body_next"

# What ``column_position`` is worth inside a page, and why it is a constant.
# Across pages it asks whether the tail sits at the foot of its page's text
# region and the head at the head of the next. Inside a page the pairing is
# chosen to be exactly that -- the last paragraph of one column against the
# first of the next -- so the answer is one by construction. It is reported as a
# constant, and its share of the score is reported beside it, because a term
# that cannot vary is not evidence.
IN_PAGE_COLUMN_POSITION = 1.0

# A column has no page kind, so no page kind can declare that it opens an
# article. The prior is zero here, which is stated rather than borrowed.
IN_PAGE_OPENER_PRIOR = 0.0

# A signal computed and not scored: whether the tail ends on a hyphen, which in
# an English source is a word broken across the break. It is recorded because it
# is the strongest single piece of evidence available, and left out of the score
# because its weight has never been calibrated; an uncalibrated term in a scored
# total would make the total say more than the calibration behind it.
HYPHEN_SIGNAL = "tail_ends_on_hyphen"
HYPHENS = ("-", "\u2010", "\u00ad")

# Keys the in-page half of the configuration is declared under.
BOUNDARY_KINDS_KEY = "boundary_kinds"
BOUNDARY_PRIORITY_KEY = "boundary_priority"
HEAD_BLOCK_CLASSES_KEY = "column_head_block_classes"
HEAD_CLEAR_GAP_KEY = "head_clear_gap_em"

# Every name chain assembly may be asked to order, in no particular order. A
# page boundary carries the kind and a column boundary carries its pairing,
# because the two pairings are ordered against each other and against the page.
PRIORITY_NAMES = (BOUNDARY_PAGE, PAIRING_COLUMN_ADJACENT, PAIRING_BODY_NEXT)

# The two ends of a boundary, named for the reports and for the mask reasons.
TAIL_ENDPOINT = "tail"
HEAD_ENDPOINT = "head"

REQUIRED_PARAMETERS: frozenset[str] = frozenset(
    {f"{WEIGHT_PREFIX}{name}" for name in SIGNAL_NAMES}
    | {
        "link_min_score",
        "tail_line_fill_min",
        "font_size_tolerance",
        "line_overlap_min",
        "column_split_gap_ratio",
        "bottom_band_ratio",
        "top_band_ratio",
        "chain_endpoint_min_width_ratio",
        "boundary_agreement_min",
        HEAD_CLEAR_GAP_KEY,
        BOUNDARY_KINDS_KEY,
        BOUNDARY_PRIORITY_KEY,
        HEAD_BLOCK_CLASSES_KEY,
        "body_labels",
        "endpoint_labels",
        "terminal_punctuation",
        "terminal_closers",
    }
)

# Reasons a boundary is not scored, recorded in the report in place of a score.
REASON_NO_ENDPOINT = "no_endpoint"
REASON_NO_PAGE_KIND = "no_page_kind"
REASON_NOT_CHAIN_ELIGIBLE = "not_chain_eligible"
REASON_SPLIT_BOUNDARY = "split_boundary"
REASON_LINE_STRUCTURE = "preserve_line_structure"
REASON_ONE_COLUMN = "one_column"
REASON_HEAD_NOT_CLEAR = "head_not_clear"
REASON_OVERLAPPING_COLUMNS = "overlapping_column_boxes"
REASON_NONADJACENT_PHYSICAL_PAGE = "nonadjacent_physical_page"

# Why chain assembly dropped an edge it was handed. Exclusive assembly gives a
# paragraph at most one edge in each role, so an edge wanting an end another
# edge already holds is dropped and says which end it lost.
DROPPED_TAIL_TAKEN = "tail_already_handed_on"
DROPPED_HEAD_TAKEN = "head_already_resumed"

# Separator PostScript font names put between a subset tag and the name proper.
_SUBSET_SEPARATOR = "+"
# Separators a PostScript font name puts before its style suffix. The part in
# front of the first one is the family, which is what style continuity compares.
_FAMILY_SEPARATORS = ("-", ",")


class ChainConfigError(ConfigError):
    """Raised when the chain detection configuration is malformed."""


@dataclass(frozen=True)
class PairRule:
    """One allowed pairing of endpoint classes, with the weights it is read by.

    A pairing carries a complete weight profile: the flat weights are the
    default, and what the pairing declares replaces them signal by signal. Two
    kinds of handover leave different traces, so they are not comparable on one
    weight set: a broken display line has no measure to fill and is not running
    text, and weighing it as though it were would score it for evidence it
    cannot produce.
    """

    tail_class: str
    head_class: str
    weights: dict[str, float]

    @property
    def name(self) -> str:
        return f"{self.tail_class}->{self.head_class}"


# A chain configuration entry is a bounded parameter, a closed vocabulary, or
# the parsed pairing section.
ChainParameter = Parameter | tuple[PairRule, ...] | dict[str, tuple[str, ...]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ChainConfigError(message)


def _parse_classes(raw: object, source: str, labels: tuple[str, ...]) -> dict:
    """Endpoint classes: a name and the layout labels that belong to it."""
    _require(
        isinstance(raw, dict) and raw,
        f"{source}: {CLASSES_KEY} must be a non-empty object",
    )
    classes: dict[str, tuple[str, ...]] = {}
    for name, members in raw.items():
        where = f"{source}: {CLASSES_KEY}.{name}"
        _require(
            isinstance(members, list) and members,
            f"{where}: must list at least one layout label",
        )
        _require(
            all(isinstance(member, str) and member for member in members),
            f"{where}: every layout label must be a non-empty string",
        )
        unknown = sorted(set(members) - set(labels))
        _require(
            not unknown,
            f"{where}: labels {unknown} are not endpoint candidates; add them to "
            f"endpoint_labels first, or a class would name paragraphs that never "
            f"reach the scoring",
        )
        classes[name] = tuple(members)
    return classes


def _parse_pair_weights(
    raw: object, source: str, where: str, config: dict, defaults: dict[str, float]
) -> dict[str, float]:
    """A pairing's weight profile: the flat weights with its overrides applied.

    Each override is validated against the range its flat namesake declares, so
    a weight inside a pairing is bounded exactly as the default it replaces and
    the bound is still written down once.
    """
    if raw is None:
        return dict(defaults)
    _require(isinstance(raw, dict), f"{where}: {PAIR_WEIGHTS_KEY} must be an object")
    unknown = sorted(set(raw) - set(SIGNAL_NAMES))
    _require(
        not unknown,
        f"{where}: weights for unknown signals {unknown}; declared signals are "
        f"{list(SIGNAL_NAMES)}",
    )
    flat: dict[str, object] = {}
    for name, value in raw.items():
        key = f"{WEIGHT_PREFIX}{name}"
        range_key = f"{key}{RANGE_SUFFIX}"
        _require(
            range_key in config,
            f"{where}: {name} has no {range_key} to be bounded by",
        )
        flat[key] = value
        flat[range_key] = config[range_key]
    bounded = validate_bounded_config(flat, Path(source))
    return defaults | {
        key[len(WEIGHT_PREFIX) :]: float(value) for key, value in bounded.items()
    }


def _parse_pair_rules(
    raw: object, source: str, config: dict, defaults: dict[str, float], classes: dict
) -> tuple[PairRule, ...]:
    _require(
        isinstance(raw, list) and raw, f"{source}: {PAIRS_KEY} must be a non-empty list"
    )
    rules: list[PairRule] = []
    seen: set[tuple[str, str]] = set()
    for position, entry in enumerate(raw):
        where = f"{source}: {PAIRS_KEY}[{position}]"
        _require(isinstance(entry, dict), f"{where}: pairing must be an object")
        unknown = sorted(
            set(entry) - {TAIL_CLASS_KEY, HEAD_CLASS_KEY, PAIR_WEIGHTS_KEY}
        )
        _require(not unknown, f"{where}: unknown keys {unknown}")
        tail_class = entry.get(TAIL_CLASS_KEY)
        head_class = entry.get(HEAD_CLASS_KEY)
        for role, name in ((TAIL_CLASS_KEY, tail_class), (HEAD_CLASS_KEY, head_class)):
            _require(
                isinstance(name, str) and name in classes,
                f"{where}: {role} {name!r} is not a declared endpoint class; "
                f"declared classes are {sorted(classes)}",
            )
        key = (tail_class, head_class)
        _require(key not in seen, f"{where}: pairing {key} is declared twice")
        seen.add(key)
        weights = _parse_pair_weights(
            entry.get(PAIR_WEIGHTS_KEY), source, where, config, defaults
        )
        rules.append(
            PairRule(tail_class=tail_class, head_class=head_class, weights=weights)
        )
    return tuple(rules)


def _check_prior_is_soft(
    weights: dict[str, float], link_min_score: float, source: str, where: str
) -> None:
    """A weight profile in which the priors can overrule full evidence is refused.

    Paragraph level evidence is authoritative and the page level prior is soft,
    so a boundary carrying every continuity signal at full strength has to stay
    linked even with every prior firing against it. A profile where it does not
    is a misconfiguration rather than a tuning choice.
    """
    positive = positive_weight(weights)
    _require(
        positive > 0,
        f"{source}: {where} carries no positive weight, so no boundary scored "
        f"under it could ever rise above zero",
    )
    penalty = sum(value for value in weights.values() if value < 0)
    floor = (positive + penalty) / positive
    _require(
        floor >= link_min_score,
        f"{source}: under {where}, full continuity evidence scores {floor:.3f} "
        f"once every prior fires against it, below link_min_score "
        f"{link_min_score}. The page level prior is soft and may not overrule "
        f"complete paragraph level evidence; raise the positive weights, weaken "
        f"the priors, or lower link_min_score",
    )


@lru_cache(maxsize=1)
def load_chain_config(path: str | None = None) -> dict[str, ChainParameter]:
    """Load and validate ``configs/chain_detection.json``.

    The flat entries are bounded the usual way. The pairing section is checked
    against the vocabulary it refers to, and every weight profile it produces
    has to keep the page level prior soft.
    """
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    source = config_path.name
    section = raw.get(PAIR_CLASSES_KEY)
    parameters: dict[str, ChainParameter] = dict(
        validate_bounded_config(
            {key: value for key, value in raw.items() if key != PAIR_CLASSES_KEY},
            config_path,
        )
    )
    missing = sorted(REQUIRED_PARAMETERS - set(parameters))
    if missing:
        raise ChainConfigError(f"{source}: missing parameters {missing}")
    unknown = sorted(
        name
        for name in parameters
        if name.startswith(WEIGHT_PREFIX)
        and name[len(WEIGHT_PREFIX) :] not in SIGNAL_NAMES
    )
    if unknown:
        raise ChainConfigError(f"{source}: weights for unknown signals {unknown}")

    defaults = default_weights(parameters)
    link_min_score = parameters["link_min_score"]
    _check_prior_is_soft(defaults, link_min_score, source, "the default weights")

    _require(
        isinstance(section, dict),
        f"{source}: {PAIR_CLASSES_KEY} must be an object declaring "
        f"{CLASSES_KEY} and {PAIRS_KEY}",
    )
    section_unknown = sorted(set(section) - {"description", CLASSES_KEY, PAIRS_KEY})
    _require(
        not section_unknown,
        f"{source}: {PAIR_CLASSES_KEY} has unknown keys {section_unknown}",
    )
    classes = _parse_classes(
        section.get(CLASSES_KEY), source, parameters["endpoint_labels"]
    )
    rules = _parse_pair_rules(section.get(PAIRS_KEY), source, raw, defaults, classes)
    for rule in rules:
        _check_prior_is_soft(
            rule.weights, link_min_score, source, f"the {rule.name} pairing"
        )

    _check_in_page_declarations(parameters, classes, source)

    parameters[CLASS_LABELS_KEY] = classes
    parameters[PAIR_RULES_KEY] = rules
    return parameters


def _check_in_page_declarations(
    parameters: dict, classes: dict, source: str
) -> None:
    """The in-page half of the declaration, checked against what code can act on.

    Three lists, each refused where it names something no branch below reads.
    The kinds and the priority are closed vocabularies this module owns, so a
    name outside them would silently order nothing; the head blocking classes
    are the scoring vocabulary's, so naming an undeclared class there would
    silently block nothing.
    """
    kinds = tuple(parameters[BOUNDARY_KINDS_KEY])
    _require(
        set(kinds) == {BOUNDARY_PAGE, BOUNDARY_COLUMN},
        f"{source}: {BOUNDARY_KINDS_KEY} must declare exactly "
        f"{[BOUNDARY_PAGE, BOUNDARY_COLUMN]}, got {list(kinds)}",
    )
    priority = tuple(parameters[BOUNDARY_PRIORITY_KEY])
    _require(
        len(set(priority)) == len(priority),
        f"{source}: {BOUNDARY_PRIORITY_KEY} names something twice: {list(priority)}",
    )
    _require(
        set(priority) == set(PRIORITY_NAMES),
        f"{source}: {BOUNDARY_PRIORITY_KEY} must order exactly "
        f"{list(PRIORITY_NAMES)}, got {list(priority)}",
    )
    blocking = tuple(parameters[HEAD_BLOCK_CLASSES_KEY])
    unknown = sorted(set(blocking) - set(classes))
    _require(
        not unknown,
        f"{source}: {HEAD_BLOCK_CLASSES_KEY} names {unknown}, which are not "
        f"declared endpoint classes; declared classes are {sorted(classes)}",
    )


def default_weights(config: dict[str, ChainParameter]) -> dict[str, float]:
    """The flat weight profile, which every pairing starts from."""
    return {
        name: float(config[f"{WEIGHT_PREFIX}{name}"])
        for name in SIGNAL_NAMES
        if f"{WEIGHT_PREFIX}{name}" in config
    }


def positive_weight(weights: dict[str, float]) -> float:
    """Evidence available under one weight profile, its total positive weight."""
    return sum(value for value in weights.values() if value > 0)


# --- geometry rebuilt from the intermediate language ------------------------


@dataclass(frozen=True)
class Endpoint:
    """One end of a boundary: a paragraph, with what the geometry says about it."""

    paragraph: il_version_1.PdfParagraph
    page_index: int
    label: str
    column_index: int
    column_count: int
    last_line_text: str
    last_line_width: float
    width: float
    measure: float | None
    font_family: str | None
    font_size: float | None


def paragraph_characters(
    paragraph: il_version_1.PdfParagraph,
) -> list[il_version_1.PdfCharacter]:
    """Every positioned character of a paragraph, whichever composition holds it.

    Which composition that is depends on how far the pipeline has run: lines
    before StylesAndFormulas, style runs and formulas after it. Reading all of
    them keeps this module independent of where in the pipeline it is called.
    """
    characters: list[il_version_1.PdfCharacter] = []
    for composition in paragraph.pdf_paragraph_composition:
        if composition.pdf_line is not None:
            characters.extend(composition.pdf_line.pdf_character)
        elif composition.pdf_same_style_characters is not None:
            characters.extend(composition.pdf_same_style_characters.pdf_character)
        elif composition.pdf_formula is not None:
            characters.extend(composition.pdf_formula.pdf_character)
        elif composition.pdf_character is not None:
            characters.append(composition.pdf_character)
    return [character for character in characters if character.box is not None]


def group_lines(
    characters: list[il_version_1.PdfCharacter], overlap_min: float
) -> list[list[il_version_1.PdfCharacter]]:
    """Partition characters into lines by vertical band, top line first.

    Two characters share a line when their vertical spans overlap by at least
    ``overlap_min`` of the shorter one's height. Superscripts and small caps
    overlap their neighbours comfortably at any sane setting, while the gap
    between consecutive lines of a paragraph does not.
    """
    if not characters:
        return []
    ordered = sorted(
        characters, key=lambda c: (-(c.box.y + c.box.y2) / 2.0, min(c.box.x, c.box.x2))
    )
    lines: list[list[il_version_1.PdfCharacter]] = []
    current = [ordered[0]]
    for character in ordered[1:]:
        previous = current[-1]
        low = max(
            min(character.box.y, character.box.y2), min(previous.box.y, previous.box.y2)
        )
        high = min(
            max(character.box.y, character.box.y2), max(previous.box.y, previous.box.y2)
        )
        height = min(
            abs(character.box.y2 - character.box.y),
            abs(previous.box.y2 - previous.box.y),
        )
        if height > 0 and max(0.0, high - low) / height >= overlap_min:
            current.append(character)
        else:
            lines.append(current)
            current = [character]
    lines.append(current)
    for line in lines:
        line.sort(key=lambda c: min(c.box.x, c.box.x2))
    return lines


def line_width(line: list[il_version_1.PdfCharacter]) -> float:
    return max(max(c.box.x, c.box.x2) for c in line) - min(
        min(c.box.x, c.box.x2) for c in line
    )


def line_left(line: list[il_version_1.PdfCharacter]) -> float:
    return min(min(c.box.x, c.box.x2) for c in line)


def line_text(line: list[il_version_1.PdfCharacter]) -> str:
    return "".join(c.char_unicode or "" for c in line)


def paragraph_width(lines: list[list[il_version_1.PdfCharacter]]) -> float:
    """The width a paragraph is actually set across, its widest line.

    Unlike the measure this is defined for a single line paragraph too, which
    is what a display line broken across a spread consists of.
    """
    return max(line_width(line) for line in lines)


def paragraph_measure(lines: list[list[il_version_1.PdfCharacter]]) -> float | None:
    """The measure a paragraph is set to, or None when it cannot be told.

    Every line of a justified or ragged paragraph but the last one runs to the
    measure, so the widest of them is it. A one line paragraph is exactly as
    wide as its own text and says nothing about the column holding it, so it
    reports nothing rather than a width that would read as a full measure.
    """
    if len(lines) < 2:
        return None
    return max(line_width(line) for line in lines[:-1])


def _page_frame(page: il_version_1.Page) -> il_version_1.Box | None:
    if page.cropbox is not None and page.cropbox.box is not None:
        return page.cropbox.box
    if page.mediabox is not None and page.mediabox.box is not None:
        return page.mediabox.box
    return None


def _font_families(page: il_version_1.Page) -> dict[str, str]:
    """Font id to family name for one page, subset tag and style suffix removed.

    A subset tag and a style suffix are the two things a PostScript name carries
    besides the family, and neither changes when running text continues; the
    family is what a continuation shares with what it continues.
    """
    families: dict[str, str] = {}
    for font in page.pdf_font:
        if not font.font_id or not font.name:
            continue
        name = font.name.split(_SUBSET_SEPARATOR, 1)[-1]
        for separator in _FAMILY_SEPARATORS:
            name = name.split(separator, 1)[0]
        families[font.font_id] = name.strip().casefold()
    return families


def _column_bands(lefts: list[float], gap: float) -> list[float]:
    """Left edge of each column band, ascending.

    Column bands are found by splitting the sorted left edges wherever they
    jump by more than ``gap``. A column is entered at the same x by everything
    set in it, so its members cluster tightly, while the step to the next column
    is a whole measure wide.
    """
    if not lefts:
        return []
    ordered = sorted(lefts)
    bands = [ordered[0]]
    for left in ordered[1:]:
        if left - bands[-1] > gap:
            bands.append(left)
    return bands


def _band_index(bands: list[float], left: float) -> int:
    index = 0
    for position, band in enumerate(bands):
        if left >= band:
            index = position
    return index


def build_endpoint(
    item: tuple, page_index: int, bands: list[float], families: dict[str, str]
) -> Endpoint:
    """One candidate as an endpoint record, with what the geometry says of it.

    The one place an endpoint is built. A page boundary and a column boundary
    both read their ends through here, so a signal computed for one is computed
    from the same measurements as the same signal for the other.
    """
    paragraph, label, lines = item
    style = paragraph.pdf_style
    font_id = style.font_id if style is not None else None
    return Endpoint(
        paragraph=paragraph,
        page_index=page_index,
        label=label,
        column_index=_band_index(bands, line_left(lines[0])),
        column_count=len(bands),
        last_line_text=line_text(lines[-1]),
        last_line_width=line_width(lines[-1]),
        width=paragraph_width(lines),
        measure=paragraph_measure(lines),
        font_family=families.get(font_id) if font_id else None,
        font_size=float(style.font_size)
        if style is not None and style.font_size
        else None,
    )


@dataclass(frozen=True)
class PageColumns:
    """One page's candidates, banded into columns, top of each column first.

    ``order`` is the band indices ascending, which is left to right and so is
    the order a reader takes the columns in. Both the in-page boundary walk and
    the measurement tool that preceded it read a page through this object, which
    is what keeps the two banding the same page the same way.
    """

    bands: list[float]
    columns: dict[int, list]
    order: list[int]
    families: dict[str, str]
    candidates: list


def page_columns(
    page: il_version_1.Page, config: dict[str, ChainParameter]
) -> PageColumns | None:
    """One page's endpoint candidates grouped into its column bands.

    None where the page offers fewer than two candidates or no frame to measure
    against; a page with one column offers no in-page handover, and is answered
    by the caller rather than by an empty object that looks like a measurement.
    """
    candidates = page_candidates(page, config)
    if len(candidates) < 2:
        return None
    frame = _page_frame(page)
    if frame is None:
        return None
    gap = (frame.x2 - frame.x) * config["column_split_gap_ratio"]
    bands = _column_bands([line_left(item[2][0]) for item in candidates], gap)
    columns: dict[int, list] = {}
    for item in candidates:
        index = _band_index(bands, line_left(item[2][0]))
        columns.setdefault(index, []).append(item)
    for members in columns.values():
        members.sort(key=lambda item: -item[0].box.y2)
    return PageColumns(
        bands=bands,
        columns=columns,
        order=sorted(columns),
        families=_font_families(page),
        candidates=candidates,
    )


def column_pairings(order: list[int]) -> list[tuple[str, int, int]]:
    """Every pairing one page's column order offers, as (pairing, tail, head).

    Two per band where the bands allow it. ``column_adjacent`` is the pairing
    this was specified as: band n's last paragraph against band n+1's first.
    ``body_next`` skips one band, because a band offering no paragraph the pair
    rules will take hides the handover behind it rather than being one.
    """
    pairings: list[tuple[str, int, int]] = []
    for position, index in enumerate(order[:-1]):
        following = order[position + 1]
        pairings.append((PAIRING_COLUMN_ADJACENT, index, following))
        for candidate in order[position + 1 :]:
            if candidate != following:
                pairings.append((PAIRING_BODY_NEXT, index, candidate))
                break
    return pairings


def tail_ends_on_hyphen(tail: Endpoint) -> bool:
    """Whether the tail's last line stops on a hyphen. Recorded, never scored."""
    text = tail.last_line_text or ""
    return bool(text) and text[-1] in HYPHENS


@dataclass(frozen=True)
class PageEndpoints:
    """What one page offers a boundary: an endpoint per class, and its extent."""

    first: dict[str, Endpoint]
    last: dict[str, Endpoint]
    region: tuple[float, float] | None


def page_candidates(
    page: il_version_1.Page, config: dict[str, ChainParameter]
) -> list[tuple[il_version_1.PdfParagraph, str, list]]:
    """Paragraphs a page offers as endpoints, in derived reading order.

    Reading order is column major: the columns left to right, and within a
    column top to bottom. It has to be derived, because the order paragraphs sit
    in the intermediate language is the order the content stream drew them,
    which for a multi column page is not the order anybody reads them.

    Two filters apply. A paragraph whose layout label is outside
    ``endpoint_labels`` is furniture rather than text and never stands in for
    it. A paragraph set narrower than ``chain_endpoint_min_width_ratio`` of the
    page is a fragment beside the text rather than part of it: a byline, a
    credit, a boxed aside. Both are ordinary members of the page and would
    otherwise be picked as the last thing on it, which is a handover the reader
    never makes.
    """
    frame = _page_frame(page)
    if frame is None:
        return []
    labels = config["endpoint_labels"]
    overlap_min = config["line_overlap_min"]
    page_width = frame.x2 - frame.x
    minimum = page_width * config["chain_endpoint_min_width_ratio"]

    candidates = []
    for paragraph in page.pdf_paragraph:
        if excludes_chain_endpoint(paragraph):
            continue
        label = paragraph.layout_label or ""
        if label not in labels or paragraph.box is None:
            continue
        lines = group_lines(paragraph_characters(paragraph), overlap_min)
        if not lines or paragraph_width(lines) < minimum:
            continue
        candidates.append((paragraph, label, lines))
    if not candidates:
        return []

    gap = page_width * config["column_split_gap_ratio"]
    bands = _column_bands([line_left(item[2][0]) for item in candidates], gap)
    return sorted(
        candidates,
        key=lambda item: (
            _band_index(bands, line_left(item[2][0])),
            -item[0].box.y2,
            item[0].box.x,
        ),
    )


def page_endpoints(
    page: il_version_1.Page, page_index: int, config: dict[str, ChainParameter]
) -> PageEndpoints:
    """The first and last candidate of every declared class, in reading order.

    One page carries one endpoint per class rather than one endpoint outright:
    the running text of a page and the display line across it end in different
    places, and a boundary that joins the second cannot be found by looking at
    the first.
    """
    candidates = page_candidates(page, config)
    if not candidates:
        return PageEndpoints(first={}, last={}, region=None)

    frame = _page_frame(page)
    families = _font_families(page)
    gap = (frame.x2 - frame.x) * config["column_split_gap_ratio"]
    bands = _column_bands([line_left(item[2][0]) for item in candidates], gap)

    first: dict[str, Endpoint] = {}
    last: dict[str, Endpoint] = {}
    for name, labels in config[CLASS_LABELS_KEY].items():
        members = [item for item in candidates if item[1] in labels]
        if not members:
            continue
        first[name] = build_endpoint(members[0], page_index, bands, families)
        last[name] = build_endpoint(members[-1], page_index, bands, families)

    boxes = [item[0].box for item in candidates]
    region = (min(box.y for box in boxes), max(box.y2 for box in boxes))
    return PageEndpoints(first=first, last=last, region=region)


# --- signals ----------------------------------------------------------------


def tail_no_terminal_punct(
    tail: Endpoint, config: dict[str, ChainParameter]
) -> float | None:
    """Whether the tail's last line stops without ending a sentence.

    A closing bracket or parenthesis is terminal evidence in its own right.
    Quote closers are stripped first, so a paragraph ending on a closed quote
    still takes its verdict from the punctuation inside the quote.
    """
    text = tail.last_line_text.rstrip()
    closers = config["terminal_closers"]
    # Combining marks and format characters carry no punctuation of their own
    # and would otherwise hide the closer or ender they sit on.
    while text and unicodedata.category(text[-1]) in ("Mn", "Cf"):
        text = text[:-1]
    if (
        text
        and text[-1] in closers
        and unicodedata.category(text[-1]) == "Pe"
    ):
        return 0.0
    while text and text[-1] in closers:
        text = text[:-1].rstrip()
    while text and unicodedata.category(text[-1]) in ("Mn", "Cf"):
        text = text[:-1]
    if not text:
        return None
    return 0.0 if text[-1] in config["terminal_punctuation"] else 1.0


def tail_line_fill(tail: Endpoint, config: dict[str, ChainParameter]) -> float | None:
    """Whether the tail's last line runs to the measure of its column.

    A paragraph that ends mid measure ended because its text ended. One that
    fills the measure was cut off by the page, which is what a continuation
    looks like.
    """
    if tail.measure is None or tail.measure <= 0:
        return None
    return (
        1.0
        if tail.last_line_width / tail.measure >= config["tail_line_fill_min"]
        else 0.0
    )


def tail_line_fill_ratio(tail: Endpoint) -> float | None:
    """The raw fill ratio behind ``tail_line_fill``, for the report."""
    if tail.measure is None or tail.measure <= 0:
        return None
    return tail.last_line_width / tail.measure


def style_continuity(
    tail: Endpoint, head: Endpoint, config: dict[str, ChainParameter]
) -> float | None:
    """Whether both ends are set in the same family at the same size.

    Running text keeps its type set across a page break. A change of family or
    a step in size is a change of role, which is what the start of something
    new looks like.
    """
    if tail.font_size is None or head.font_size is None:
        return None
    if tail.font_family is None or head.font_family is None:
        return None
    same_size = abs(tail.font_size - head.font_size) <= config["font_size_tolerance"]
    return 1.0 if same_size and tail.font_family == head.font_family else 0.0


def body_label_pair(
    tail: Endpoint, head: Endpoint, config: dict[str, ChainParameter]
) -> float:
    """Whether both ends are running text rather than furniture around it."""
    labels = config["body_labels"]
    return 1.0 if tail.label in labels and head.label in labels else 0.0


def column_position(
    tail: Endpoint,
    head: Endpoint,
    tail_region: tuple[float, float] | None,
    head_region: tuple[float, float] | None,
    config: dict[str, ChainParameter],
) -> float | None:
    """Whether the two ends sit where one page hands over to the next.

    Text that continues leaves at the foot of the last column and resumes at
    the head of the first. Each half is scored on its own, so a boundary that
    satisfies one of them is placed between one that satisfies both and one
    that satisfies neither.
    """
    halves: list[float] = []
    if tail_region is not None and tail.paragraph.box is not None:
        bottom, top = tail_region
        height = top - bottom
        in_last_column = tail.column_index == tail.column_count - 1
        in_band = (
            height <= 0
            or tail.paragraph.box.y <= bottom + height * config["bottom_band_ratio"]
        )
        halves.append(1.0 if in_last_column and in_band else 0.0)
    if head_region is not None and head.paragraph.box is not None:
        bottom, top = head_region
        height = top - bottom
        in_first_column = head.column_index == 0
        in_band = (
            height <= 0
            or head.paragraph.box.y2 >= top - height * config["top_band_ratio"]
        )
        halves.append(1.0 if in_first_column and in_band else 0.0)
    if not halves:
        return None
    return statistics.fmean(halves)


def opener_prior(page: il_version_1.Page, policy: dict[str, object] | None) -> float:
    """How strongly the following page is declared to be where text begins.

    This is the one place the page level intermediate representation enters the
    boundary score, and it enters as a soft prior weighted against linking: the
    strength is the confidence the page carries in its own kind, so a page the
    classifier was unsure about withdraws proportionally less evidence.
    """
    if policy is None or not policy.get(OPENER_POLICY_FLAG, False):
        return 0.0
    confidence = page.page_kind_conf
    if confidence is None:
        return 1.0
    return max(0.0, min(1.0, float(confidence)))


# --- combination ------------------------------------------------------------


@dataclass(frozen=True)
class PairVerdict:
    """One allowed pairing, scored on the two endpoints it selected."""

    pair: str
    values: dict[str, float | None]
    score: float
    linked: bool
    tail_fill_ratio: float | None
    tail: Endpoint
    head: Endpoint

    def as_record(self) -> dict:
        return {
            "pair": self.pair,
            "signals": dict(self.values),
            "score": self.score,
            "linked": self.linked,
            "tail_fill_ratio": self.tail_fill_ratio,
            "tail_debug_id": self.tail.paragraph.debug_id,
            "head_debug_id": self.head.paragraph.debug_id,
            "tail_label": self.tail.label,
            "head_label": self.head.label,
            "tail_text": self.tail.last_line_text,
            "head_text": self.head.paragraph.unicode or "",
        }


@dataclass(frozen=True)
class BoundaryVerdict:
    """One boundary, scored or explained.

    ``kind`` says what it joins. A page boundary joins the two pages named by
    ``tail_page`` and ``head_page``; a column boundary names one page in both
    and joins the two bands named by ``tail_column`` and ``head_column``. The
    fields carrying only for a column boundary default to absent, so a page
    boundary is built exactly as it was before in-page boundaries existed.
    """

    tail_page: int
    head_page: int
    eligible: bool
    reason: str | None
    pair: str | None
    values: dict[str, float | None]
    score: float | None
    linked: bool
    tail_fill_ratio: float | None
    tail: Endpoint | None
    head: Endpoint | None
    pairs: tuple[PairVerdict, ...] = ()
    kind: str = BOUNDARY_PAGE
    pairing: str | None = None
    tail_column: int | None = None
    head_column: int | None = None
    column_count: int | None = None
    hyphen_tail: bool = False
    constant_share: float | None = None

    @property
    def priority_name(self) -> str:
        """The name chain assembly orders this boundary by.

        A page boundary answers with its kind and a column boundary with its
        pairing, because the two pairings are ordered against each other as well
        as against the page.
        """
        return self.pairing if self.kind == BOUNDARY_COLUMN else BOUNDARY_PAGE

    @property
    def label(self) -> str:
        """This boundary in the form a report and a gate name it by.

        1-based file page numbers, the form the truth files are keyed in, and
        for a column boundary the page followed by the two bands.
        """
        if self.kind != BOUNDARY_COLUMN:
            return f"{self.tail_page + 1}->{self.head_page + 1}"
        if self.tail_column is None:
            # One row standing for a whole page that offered no column
            # boundary, which has a reason rather than a pair of bands.
            return f"p{self.tail_page + 1}:columns"
        return f"p{self.tail_page + 1}:c{self.tail_column}->c{self.head_column}"

    def as_record(self) -> dict:
        """The report row for this boundary, one boundary per row."""
        return {
            "boundary": self.label,
            "kind": self.kind,
            "pairing": self.pairing,
            "tail_page": self.tail_page + 1,
            "head_page": self.head_page + 1,
            "tail_column": self.tail_column,
            "head_column": self.head_column,
            "column_count": self.column_count,
            "eligible": self.eligible,
            "reason": self.reason,
            "pair": self.pair,
            "signals": dict(self.values),
            "tail_fill_ratio": self.tail_fill_ratio,
            "score": self.score,
            "constant_share_of_score": self.constant_share,
            HYPHEN_SIGNAL: self.hyphen_tail,
            "linked": self.linked,
            "tail_debug_id": self.tail.paragraph.debug_id if self.tail else None,
            "head_debug_id": self.head.paragraph.debug_id if self.head else None,
            "tail_label": self.tail.label if self.tail else None,
            "head_label": self.head.label if self.head else None,
            "tail_text": self.tail.last_line_text if self.tail else None,
            "head_text": (self.head.paragraph.unicode or "") if self.head else None,
            "pairs": [pair.as_record() for pair in self.pairs],
        }


def combine(values: dict[str, float | None], weights: dict[str, float]) -> float:
    """Weighted evidence over available evidence, clamped to 0..1.

    A signal the geometry cannot supply contributes nothing rather than being
    imputed: the alternative is to guess in whichever direction the default
    points, and a boundary with less evidence should score lower, not differently
    biased.
    """
    total = positive_weight(weights)
    if total <= 0:
        return 0.0
    satisfied = sum(
        weights.get(name, 0.0) * value
        for name, value in values.items()
        if value is not None
    )
    return max(0.0, min(1.0, satisfied / total))


def _pair_verdict(
    rule: PairRule,
    tail: Endpoint,
    head: Endpoint,
    tail_region: tuple[float, float] | None,
    head_region: tuple[float, float] | None,
    prior: float,
    config: dict[str, ChainParameter],
) -> PairVerdict:
    values: dict[str, float | None] = {
        "tail_no_terminal_punct": tail_no_terminal_punct(tail, config),
        "tail_line_fill": tail_line_fill(tail, config),
        "style_continuity": style_continuity(tail, head, config),
        "body_label_pair": body_label_pair(tail, head, config),
        "column_position": column_position(
            tail, head, tail_region, head_region, config
        ),
        "opener_prior": prior,
    }
    score = combine(values, rule.weights)
    return PairVerdict(
        pair=rule.name,
        values=values,
        score=score,
        linked=score >= config["link_min_score"],
        tail_fill_ratio=tail_line_fill_ratio(tail),
        tail=tail,
        head=head,
    )


def head_is_clear(
    columns: PageColumns, head: Endpoint, config: dict[str, ChainParameter]
) -> bool:
    """Whether a column head has clear space above it.

    A column whose first paragraph is set tight under a display line is not a
    column running text arrives into: it is the opening of something the display
    line names, and whatever the column before it was saying stopped before it.
    Measured in the head's own type size, so the answer is the same for a page
    set large and one set small, and only against endpoint candidates of the
    declared blocking classes, so the gate reads the vocabulary the scoring
    reads. A head whose size cannot be told is treated as clear: the gate
    withdraws a link and an unmeasurable gate may not withdraw one.
    """
    box = head.paragraph.box
    size = head.font_size
    if box is None or not size or size <= 0:
        return True
    reach = box.y2 + config[HEAD_CLEAR_GAP_KEY] * size
    labels = config[CLASS_LABELS_KEY]
    blocking: set[str] = set()
    for name in config[HEAD_BLOCK_CLASSES_KEY]:
        blocking.update(labels.get(name, ()))
    for paragraph, label, _lines in columns.candidates:
        if paragraph is head.paragraph or label not in blocking:
            continue
        other = paragraph.box
        if other is None or other.y < box.y2 or other.y > reach:
            continue
        if min(other.x2, box.x2) - max(other.x, box.x) <= 0:
            continue
        return False
    return True


def _column_pair_verdict(
    rule: PairRule,
    tail: Endpoint,
    head: Endpoint,
    config: dict[str, ChainParameter],
) -> PairVerdict:
    """One allowed pairing scored on two ends of the same page.

    The same four measured signals as a page boundary, and the two that cannot
    vary inside a page entered as the constants declared for them.
    """
    values: dict[str, float | None] = {
        "tail_no_terminal_punct": tail_no_terminal_punct(tail, config),
        "tail_line_fill": tail_line_fill(tail, config),
        "style_continuity": style_continuity(tail, head, config),
        "body_label_pair": body_label_pair(tail, head, config),
        "column_position": IN_PAGE_COLUMN_POSITION,
        "opener_prior": IN_PAGE_OPENER_PRIOR,
    }
    score = combine(values, rule.weights)
    return PairVerdict(
        pair=rule.name,
        values=values,
        score=score,
        linked=score >= config["link_min_score"],
        tail_fill_ratio=tail_line_fill_ratio(tail),
        tail=tail,
        head=head,
    )


def _column_rejected(page_index: int, reason: str) -> BoundaryVerdict:
    """One row standing for a page that offered no column boundary, and why."""
    return BoundaryVerdict(
        tail_page=page_index,
        head_page=page_index,
        eligible=False,
        reason=reason,
        pair=None,
        values=dict.fromkeys(SIGNAL_NAMES),
        score=None,
        linked=False,
        tail_fill_ratio=None,
        tail=None,
        head=None,
        kind=BOUNDARY_COLUMN,
    )


def evaluate_column_boundaries(
    page: il_version_1.Page,
    page_index: int,
    policy_of,
    config: dict[str, ChainParameter],
) -> list[BoundaryVerdict]:
    """Every boundary between two columns of one page, scored or explained.

    Two qualifications and one gate stand in front of the score. A page whose
    kind the vocabulary does not hold is not read, because nothing is declared
    about it. A page declared to preserve its line structure sets records rather
    than prose and offers no boundary at all. And a pairing whose head has a
    display line set tight above it is scored and then refused, with the refusal
    written down, because the evidence for the handover is real and the reason
    for not taking it is a separate fact about the page.
    """
    policy = policy_of(page.page_kind)
    if policy is None:
        return [_column_rejected(page_index, REASON_NO_PAGE_KIND)]
    columns = page_columns(page, config)
    if columns is None or len(columns.order) < 2:
        return [_column_rejected(page_index, REASON_ONE_COLUMN)]

    verdicts: list[BoundaryVerdict] = []
    for pairing, tail_band, head_band in column_pairings(columns.order):
        scored: list[PairVerdict] = []
        for rule in config[PAIR_RULES_KEY]:
            tail_labels = config[CLASS_LABELS_KEY].get(rule.tail_class, ())
            head_labels = config[CLASS_LABELS_KEY].get(rule.head_class, ())
            tail_candidates = [
                item for item in columns.columns[tail_band] if item[1] in tail_labels
            ]
            head_candidates = [
                item for item in columns.columns[head_band] if item[1] in head_labels
            ]
            if not tail_candidates or not head_candidates:
                continue
            tail = build_endpoint(
                tail_candidates[-1], page_index, columns.bands, columns.families
            )
            head = build_endpoint(
                head_candidates[0], page_index, columns.bands, columns.families
            )
            scored.append(_column_pair_verdict(rule, tail, head, config))
        common = {
            "kind": BOUNDARY_COLUMN,
            "pairing": pairing,
            "tail_column": tail_band,
            "head_column": head_band,
            "column_count": len(columns.bands),
        }
        if not scored:
            tail = build_endpoint(
                columns.columns[tail_band][-1],
                page_index,
                columns.bands,
                columns.families,
            )
            head = build_endpoint(
                columns.columns[head_band][0],
                page_index,
                columns.bands,
                columns.families,
            )
            verdicts.append(
                BoundaryVerdict(
                    tail_page=page_index,
                    head_page=page_index,
                    eligible=False,
                    reason=REASON_NO_ENDPOINT,
                    pair=None,
                    values=dict.fromkeys(SIGNAL_NAMES),
                    score=None,
                    linked=False,
                    tail_fill_ratio=None,
                    tail=tail,
                    head=head,
                    hyphen_tail=tail_ends_on_hyphen(tail),
                    **common,
                )
            )
            continue
        # Declaration order breaks a tie, as it does across a page break, so the
        # same document always yields the same verdict.
        best = scored[0]
        for candidate in scored[1:]:
            if candidate.score > best.score:
                best = candidate
        tail = best.tail
        head = best.head
        clear = head_is_clear(columns, head, config)
        tail_box = tail.paragraph.box
        head_box = head.paragraph.box
        horizontal_overlap = 0.0
        if tail_box is not None and head_box is not None:
            horizontal_overlap = max(
                0.0, min(tail_box.x2, head_box.x2) - max(tail_box.x, head_box.x)
            )
        separate_columns = horizontal_overlap <= 0.0
        weights = next(
            rule.weights for rule in config[PAIR_RULES_KEY] if rule.name == best.pair
        )
        verdicts.append(
            BoundaryVerdict(
                tail_page=page_index,
                head_page=page_index,
                eligible=True,
                reason=(
                    None
                    if clear and separate_columns
                    else (
                        REASON_HEAD_NOT_CLEAR
                        if not clear
                        else REASON_OVERLAPPING_COLUMNS
                    )
                ),
                pair=best.pair,
                values=best.values,
                score=best.score,
                linked=best.linked and clear and separate_columns,
                tail_fill_ratio=best.tail_fill_ratio,
                tail=best.tail,
                head=best.head,
                pairs=tuple(scored),
                hyphen_tail=tail_ends_on_hyphen(best.tail),
                constant_share=weights.get("column_position", 0.0)
                * IN_PAGE_COLUMN_POSITION,
                **common,
            )
        )
    return verdicts


def evaluate_boundary(
    tail_page: il_version_1.Page,
    head_page: il_version_1.Page,
    tail_index: int,
    head_index: int,
    policy_of,
    config: dict[str, ChainParameter],
) -> BoundaryVerdict:
    """Score one adjacent page boundary, or explain why it was not scored.

    ``policy_of`` maps a page kind to its declared policy, or to None when the
    kind is not in the vocabulary. A known page's classification is a soft
    prior: paragraph geometry, role, style and text continuity decide the
    boundary even when the page-level classifier called the page a sidebar.

    Every allowed pairing that finds both its endpoints is scored, and the
    boundary takes the strongest of them; a pairing that finds neither leaves no
    trace beyond the report.
    """
    blank: dict[str, float | None] = dict.fromkeys(SIGNAL_NAMES)

    def rejected(reason: str) -> BoundaryVerdict:
        return BoundaryVerdict(
            tail_page=tail_index,
            head_page=head_index,
            eligible=False,
            reason=reason,
            pair=None,
            values=blank,
            score=None,
            linked=False,
            tail_fill_ratio=None,
            tail=None,
            head=None,
        )

    tail_policy = policy_of(tail_page.page_kind)
    head_policy = policy_of(head_page.page_kind)
    if tail_policy is None or head_policy is None:
        return rejected(REASON_NO_PAGE_KIND)
    # Page classification is only a prior.  A feature page misclassified as a
    # sidebar must not overrule complete paragraph-level continuity evidence.

    tail_ends = page_endpoints(tail_page, tail_index, config)
    head_ends = page_endpoints(head_page, head_index, config)
    prior = opener_prior(head_page, head_policy)

    scored: list[PairVerdict] = []
    for rule in config[PAIR_RULES_KEY]:
        tail = tail_ends.last.get(rule.tail_class)
        head = head_ends.first.get(rule.head_class)
        if tail is None or head is None:
            continue
        scored.append(
            _pair_verdict(
                rule, tail, head, tail_ends.region, head_ends.region, prior, config
            )
        )
    if not scored:
        return rejected(REASON_NO_ENDPOINT)

    # Declaration order breaks a tie, so the same document always yields the
    # same verdict.
    best = scored[0]
    for candidate in scored[1:]:
        if candidate.score > best.score:
            best = candidate
    return BoundaryVerdict(
        tail_page=tail_index,
        head_page=head_index,
        eligible=True,
        reason=None,
        pair=best.pair,
        values=best.values,
        score=best.score,
        linked=best.linked,
        tail_fill_ratio=best.tail_fill_ratio,
        tail=best.tail,
        head=best.head,
        pairs=tuple(scored),
        # Recorded here for the same reason it is recorded for a column
        # boundary, and weighed here for the same reason it is not weighed
        # there: the merge already closes a broken word up, and the score has
        # never been calibrated against this term.
        hyphen_tail=tail_ends_on_hyphen(best.tail),
        tail_column=best.tail.column_index,
        head_column=best.head.column_index,
    )
