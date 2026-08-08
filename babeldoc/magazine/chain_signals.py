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

# The policy flag the page level prior is read through. The prior enters the
# score only by this name, which is what keeps page type names out of the code.
OPENER_POLICY_FLAG = "starts_article"

# The policy flag that qualifies a page for chaining at all.
ELIGIBILITY_POLICY_FLAG = "chain_eligible"

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


@lru_cache(maxsize=1)
def load_chain_config(path: str | None = None) -> dict[str, Parameter]:
    """Load and validate ``configs/chain_detection.json``.

    Beyond the bounds every entry declares for itself, the weight set has to
    satisfy one structural property: a boundary on which every continuity
    signal fires at full strength must still be scored as linked even when the
    page level prior fires against it. Paragraph level evidence is authoritative
    and the prior is soft, so a weight set in which the prior alone can overrule
    complete evidence is a misconfiguration, not a tuning choice.
    """
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = validate_bounded_config(raw, config_path)
    missing = sorted(REQUIRED_PARAMETERS - set(parameters))
    if missing:
        raise ChainConfigError(f"{config_path.name}: missing parameters {missing}")
    unknown = sorted(
        name
        for name in parameters
        if name.startswith(WEIGHT_PREFIX)
        and name[len(WEIGHT_PREFIX) :] not in SIGNAL_NAMES
    )
    if unknown:
        raise ChainConfigError(
            f"{config_path.name}: weights for unknown signals {unknown}"
        )

    positive = positive_weight(parameters)
    if positive <= 0:
        raise ChainConfigError(
            f"{config_path.name}: no signal carries positive weight, so no "
            f"boundary could ever be scored above zero"
        )
    penalty = sum(
        value
        for name, value in parameters.items()
        if name.startswith(WEIGHT_PREFIX)
        and isinstance(value, float | int)
        and value < 0
    )
    floor = (positive + penalty) / positive
    if floor < parameters["link_min_score"]:
        raise ChainConfigError(
            f"{config_path.name}: full continuity evidence scores {floor:.3f} once "
            f"every prior fires against it, below link_min_score "
            f"{parameters['link_min_score']}. The page level prior is soft and may "
            f"not overrule complete paragraph level evidence; raise the positive "
            f"weights, weaken the priors, or lower link_min_score"
        )
    return parameters


def positive_weight(config: dict[str, Parameter]) -> float:
    """Evidence available to a boundary, which is the total positive weight."""
    return sum(
        value
        for name, value in config.items()
        if name.startswith(WEIGHT_PREFIX)
        and isinstance(value, float | int)
        and value > 0
    )


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


def page_endpoints(
    page: il_version_1.Page, page_index: int, config: dict[str, Parameter]
) -> tuple[Endpoint | None, Endpoint | None]:
    """The first and last paragraph of a page in derived reading order.

    Reading order is column major: the columns left to right, and within a
    column top to bottom. It has to be derived, because the order paragraphs sit
    in the intermediate language is the order the content stream drew them,
    which for a multi column page is not the order anybody reads them.

    Only paragraphs whose layout label is in ``endpoint_labels`` are candidates,
    which keeps folios, figures and tables from standing in for the text; the
    narrower body test is a scored signal rather than a filter, so a page whose
    text hands over from something that is not running text still reaches the
    scoring and is judged on the evidence.
    """
    frame = _page_frame(page)
    if frame is None:
        return None, None
    labels = config["endpoint_labels"]
    overlap_min = config["line_overlap_min"]
    families = _font_families(page)

    candidates = []
    for paragraph in page.pdf_paragraph:
        label = paragraph.layout_label or ""
        if label not in labels or paragraph.box is None:
            continue
        lines = group_lines(paragraph_characters(paragraph), overlap_min)
        if not lines:
            continue
        candidates.append((paragraph, label, lines))
    if not candidates:
        return None, None

    gap = (frame.x2 - frame.x) * config["column_split_gap_ratio"]
    bands = _column_bands([line_left(item[2][0]) for item in candidates], gap)

    ordered = sorted(
        candidates,
        key=lambda item: (
            _band_index(bands, line_left(item[2][0])),
            -item[0].box.y2,
            item[0].box.x,
        ),
    )

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
            measure=paragraph_measure(lines),
            font_family=families.get(font_id) if font_id else None,
            font_size=float(style.font_size)
            if style is not None and style.font_size
            else None,
        )

    return build(ordered[0]), build(ordered[-1])


def _text_region(
    page: il_version_1.Page, config: dict[str, Parameter]
) -> tuple[float, float] | None:
    """Vertical extent of the text on a page, as (bottom, top).

    The band tests are taken against the text a page actually carries rather
    than against its trim, so a page with generous margins and one set tight
    are measured on the same scale.
    """
    labels = config["endpoint_labels"]
    boxes = [
        paragraph.box
        for paragraph in page.pdf_paragraph
        if (paragraph.layout_label or "") in labels and paragraph.box is not None
    ]
    if not boxes:
        return None
    return min(box.y for box in boxes), max(box.y2 for box in boxes)


# --- signals ----------------------------------------------------------------


def tail_no_terminal_punct(
    tail: Endpoint, config: dict[str, Parameter]
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


def tail_line_fill(tail: Endpoint, config: dict[str, Parameter]) -> float | None:
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
    tail: Endpoint, head: Endpoint, config: dict[str, Parameter]
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
    tail: Endpoint, head: Endpoint, config: dict[str, Parameter]
) -> float:
    """Whether both ends are running text rather than furniture around it."""
    labels = config["body_labels"]
    return 1.0 if tail.label in labels and head.label in labels else 0.0


def column_position(
    tail: Endpoint,
    head: Endpoint,
    tail_region: tuple[float, float] | None,
    head_region: tuple[float, float] | None,
    config: dict[str, Parameter],
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
class BoundaryVerdict:
    """One boundary, scored or explained."""

    tail_page: int
    head_page: int
    eligible: bool
    reason: str | None
    values: dict[str, float | None]
    score: float | None
    linked: bool
    tail_fill_ratio: float | None
    tail: Endpoint | None
    head: Endpoint | None

    def as_record(self) -> dict:
        """The report row for this boundary, one page pair per row."""
        return {
            # 1-based file page numbers, the form the truth file is keyed in.
            "boundary": f"{self.tail_page + 1}->{self.head_page + 1}",
            "tail_page": self.tail_page + 1,
            "head_page": self.head_page + 1,
            "eligible": self.eligible,
            "reason": self.reason,
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
        }


def combine(values: dict[str, float | None], config: dict[str, Parameter]) -> float:
    """Weighted evidence over available evidence, clamped to 0..1.

    A signal the geometry cannot supply contributes nothing rather than being
    imputed: the alternative is to guess in whichever direction the default
    points, and a boundary with less evidence should score lower, not differently
    biased.
    """
    total = positive_weight(config)
    if total <= 0:
        return 0.0
    satisfied = sum(
        config[f"{WEIGHT_PREFIX}{name}"] * value
        for name, value in values.items()
        if value is not None
    )
    return max(0.0, min(1.0, satisfied / total))


def evaluate_boundary(
    tail_page: il_version_1.Page,
    head_page: il_version_1.Page,
    tail_index: int,
    head_index: int,
    policy_of,
    config: dict[str, Parameter],
) -> BoundaryVerdict:
    """Score one adjacent page boundary, or explain why it was not scored.

    ``policy_of`` maps a page kind to its declared policy, or to None when the
    kind is not in the vocabulary. Eligibility is a qualification rather than a
    term: a boundary between pages that are not both declared chain eligible is
    not scored at all, so no accumulation of continuity evidence can link across
    a page the vocabulary says is not part of a chain.
    """
    blank: dict[str, float | None] = dict.fromkeys(SIGNAL_NAMES)

    def rejected(reason: str) -> BoundaryVerdict:
        return BoundaryVerdict(
            tail_page=tail_index,
            head_page=head_index,
            eligible=False,
            reason=reason,
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
    if not tail_policy.get(ELIGIBILITY_POLICY_FLAG, False) or not head_policy.get(
        ELIGIBILITY_POLICY_FLAG, False
    ):
        return rejected(REASON_NOT_CHAIN_ELIGIBLE)

    _, tail = page_endpoints(tail_page, tail_index, config)
    head, _ = page_endpoints(head_page, head_index, config)
    if tail is None or head is None:
        return rejected(REASON_NO_ENDPOINT)

    values: dict[str, float | None] = {
        "tail_no_terminal_punct": tail_no_terminal_punct(tail, config),
        "tail_line_fill": tail_line_fill(tail, config),
        "style_continuity": style_continuity(tail, head, config),
        "body_label_pair": body_label_pair(tail, head, config),
        "column_position": column_position(
            tail,
            head,
            _text_region(tail_page, config),
            _text_region(head_page, config),
            config,
        ),
        "opener_prior": opener_prior(head_page, head_policy),
    }
    score = combine(values, config)
    return BoundaryVerdict(
        tail_page=tail_index,
        head_page=head_index,
        eligible=True,
        reason=None,
        values=values,
        score=score,
        linked=score >= config["link_min_score"],
        tail_fill_ratio=tail_line_fill_ratio(tail),
        tail=tail,
        head=head,
    )
