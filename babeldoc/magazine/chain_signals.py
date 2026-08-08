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
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import Parameter
from babeldoc.magazine.page_features import validate_bounded_config

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "chain_detection.json"

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

    parameters[CLASS_LABELS_KEY] = classes
    parameters[PAIR_RULES_KEY] = rules
    return parameters


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

    def build(item) -> Endpoint:
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

    first: dict[str, Endpoint] = {}
    last: dict[str, Endpoint] = {}
    for name, labels in config[CLASS_LABELS_KEY].items():
        members = [item for item in candidates if item[1] in labels]
        if not members:
            continue
        first[name] = build(members[0])
        last[name] = build(members[-1])

    boxes = [item[0].box for item in candidates]
    region = (min(box.y for box in boxes), max(box.y2 for box in boxes))
    return PageEndpoints(first=first, last=last, region=region)


# --- signals ----------------------------------------------------------------


def tail_no_terminal_punct(
    tail: Endpoint, config: dict[str, ChainParameter]
) -> float | None:
    """Whether the tail's last line stops without ending a sentence.

    Trailing closing marks are stripped first, so a paragraph that ends on a
    closed quotation reads as ended rather than as running on.
    """
    text = tail.last_line_text.rstrip()
    closers = config["terminal_closers"]
    while text and text[-1] in closers:
        text = text[:-1].rstrip()
    # Combining marks and format characters carry no punctuation of their own
    # and would otherwise hide the ender they sit on.
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
    """One boundary, scored or explained."""

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

    def as_record(self) -> dict:
        """The report row for this boundary, one page pair per row."""
        return {
            # 1-based file page numbers, the form the truth file is keyed in.
            "boundary": f"{self.tail_page + 1}->{self.head_page + 1}",
            "tail_page": self.tail_page + 1,
            "head_page": self.head_page + 1,
            "eligible": self.eligible,
            "reason": self.reason,
            "pair": self.pair,
            "signals": dict(self.values),
            "tail_fill_ratio": self.tail_fill_ratio,
            "score": self.score,
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
    kind is not in the vocabulary. Eligibility is read per endpoint: the tail
    endpoint answers to the page it sits on and the head endpoint to the page it
    begins, so a page the vocabulary keeps out of chains takes only its own end
    of the boundary with it. It is a qualification rather than a term, so no
    accumulation of continuity evidence can link through an endpoint the
    vocabulary excludes.

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
    excluded = [
        endpoint
        for endpoint, policy in (
            (TAIL_ENDPOINT, tail_policy),
            (HEAD_ENDPOINT, head_policy),
        )
        if not policy.get(ELIGIBILITY_POLICY_FLAG, False)
    ]
    if excluded:
        return rejected(f"{REASON_NOT_CHAIN_ELIGIBLE}:{','.join(excluded)}")

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
    )
