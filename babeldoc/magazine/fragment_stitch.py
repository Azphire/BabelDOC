"""Fragment stitching: one written unit reaches the translator as one request.

What is broken here
-------------------

The paragraph finder groups characters into paragraphs by layout region, and on
a magazine page it sometimes leaves one written unit as several of them. Three
shapes of that recur on this corpus, and the third is a special case of the
first:

* a line cut in the middle of a word into two boxes standing side by side --
  ``There are many more examples of how t`` and ``raditional knowledge``;
* a run of such boxes down a column, so the sentence they hold together is
  spread over four paragraphs before the paragraph that finishes it;
* the first letters of a paragraph drawn as their own small box before the rest
  of it -- ``T``, ``h``, then ``e European Strategy reiterates...``.

Every piece is a translation request of its own. Half a word goes to the model
and a translation of half a word comes back, and the page prints it. So this
pass runs before the translator and puts the pieces back.

Why it runs where it runs
-------------------------

Before the line structure pass and before the chain builder, and after the
classifier, which is the same window ``line_split`` runs in and for a related
reason: a page whose declared policy says its lines are records is a page whose
paragraphs are *meant* to be assembled from lines, and joining two of them would
undo the thing that pass exists to do. The flag is read by name from the
configuration, so no page type is named here.

The three guards, and why the geometry alone is not enough
----------------------------------------------------------

Geometry says two boxes are near each other. Every column of running text is
made of boxes near each other, so geometry alone would join a column into one
request. Two further guards narrow it, and both have to hold.

The **style guard** is that the two pieces are set in one face at one size. The
face is read by the *name* the font carries, not by the resource id it is
reachable under: the same typeface is registered under a different id inside
every form a page draws, so on the page this was written against the two halves
of one word carry ids ``TT3`` and ``C2_0`` and one name.

The **unit guard** is that the join falls inside a written unit rather than
between two. A piece that ends its sentence is not waiting for what follows it,
so the left piece's last character, with any closing quotation stripped, may not
be sentence-terminal; and one of the two pieces has to be short enough to be a
piece rather than a paragraph. Two full paragraphs, one ending where the next
begins, is what running text looks like everywhere.

What a stitch does to the paragraphs
------------------------------------

The members are merged into the first of them and the rest are left in place
holding nothing: the page keeps its paragraph count and every index that named a
paragraph still names it, which is what makes the account of a run checkable
against the account of the run before it. The merged paragraph's text is written
from the same characters its composition is rebuilt from, so the two halves of a
paragraph's text cannot drift apart here.

A member holding anything but characters -- a formula above all -- disqualifies
its group. A formula is a unit this pass has no way to carry into a rebuilt
composition without changing what the paragraph's text says, and a fragment is
never a formula.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
from babeldoc.magazine import source_audit
from babeldoc.magazine.line_split import SPLITTABLE
from babeldoc.magazine.line_split import character_union
from babeldoc.magazine.line_split import composition_kind
from babeldoc.magazine.line_split import load_line_split_config
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.line_split import recover_lines
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("fragment_stitch.json")

REPORT_NAME = "fragment_stitch.report.json"

SWITCH = "magazine_fragment_stitch"

# The switch this pass rides: it runs inside the hook the classifier stage calls,
# because the page policy it has to respect is not settled before that.
WINDOW_SWITCH = "magazine_page_classify"

RULE_INLINE = "inline"
RULE_VERTICAL = "vertical"
RULE_INITIAL = "initial"

POLICY_FLAGS_KEY = "policy_flags"
LAYOUT_LABELS_KEY = "stitch_layout_labels"
TERMINATORS_KEY = "sentence_terminators"
CLOSING_MARKS_KEY = "closing_marks"
DESCRIPTION_KEY = "description"
RULES_KEY = "rules"
SIDECAR_FIELDS_KEY = "sidecar_fields"

# What may still run on a page whose lines are records, what lets it, and which
# audit classes it may act on. The inline rule works inside one line band and
# cannot reach across a record boundary; the vertical rule can, which is why the
# narrowing is by rule rather than by page.
DECLARED_RULES_KEY = "declared_page_rules"
DECLARED_SWITCH_KEY = "declared_page_switch"
DECLARED_CLASSES_KEY = "declared_page_classes"
BLANK_CLASSES_KEY = "duplicate_blank_classes"

# Keys of this configuration that are neither a bounded number nor a closed
# vocabulary. Declared here rather than listed in whatever scans the file, so a
# structural key added later is one every reader already knows about.
_STRUCTURAL_KEYS = (DESCRIPTION_KEY, DECLARED_SWITCH_KEY)

# How a merged paragraph is named after the paragraph it was merged into: it is
# that paragraph, so it keeps its identity and nothing is minted.
_VOCABULARIES = (
    POLICY_FLAGS_KEY,
    LAYOUT_LABELS_KEY,
    TERMINATORS_KEY,
    CLOSING_MARKS_KEY,
    RULES_KEY,
    DECLARED_RULES_KEY,
    DECLARED_CLASSES_KEY,
    BLANK_CLASSES_KEY,
    SIDECAR_FIELDS_KEY,
)


class FragmentStitchError(ConfigError):
    """Raised when the fragment stitch configuration is malformed."""


@dataclass(frozen=True)
class StitchConfig:
    """Everything bounded about putting a broken unit back together."""

    font_size_tolerance: float
    min_y_overlap_ratio: float
    max_inline_gap_ratio: float
    min_x_overlap_ratio: float
    max_line_gap_ratio: float
    max_fragment_chars: int
    initial_min_font_ratio: float
    initial_max_chars: int
    initial_max_offset_ratio: float
    policy_flags: tuple[str, ...]
    layout_labels: tuple[str, ...]
    terminators: tuple[str, ...]
    closing_marks: tuple[str, ...]
    rules: tuple[str, ...]
    declared_page_rules: tuple[str, ...]
    declared_page_switch: str
    declared_page_classes: frozenset[str]
    blank_classes: frozenset[str]
    sidecar_fields: tuple[str, ...]

    def declared(self, policy: dict | None) -> bool:
        """Whether a page carrying this policy is left alone by this pass."""
        if not policy:
            return False
        return any(bool(policy.get(flag, False)) for flag in self.policy_flags)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FragmentStitchError(message)


def parse_stitch_config(raw: dict, source: str) -> StitchConfig:
    """Validate one configuration mapping into the policy it declares."""
    # The switch is a name rather than a bound, so it is read here rather than
    # by the bounded validator, which admits numbers and vocabularies only.
    switch = raw.get(DECLARED_SWITCH_KEY)
    _require(
        isinstance(switch, str) and switch and switch.strip() == switch,
        f"{source}: {DECLARED_SWITCH_KEY} must name the run attribute that lets "
        f"a declared page be stitched",
    )
    try:
        parameters = dict(
            validate_bounded_config(
                {
                    key: value
                    for key, value in raw.items()
                    if key != DECLARED_SWITCH_KEY
                },
                CONFIG_PATH,
            )
        )
    except ConfigError as exc:
        raise FragmentStitchError(str(exc)) from exc

    for key in _VOCABULARIES:
        _require(key in parameters, f"{source}: missing {key}")

    rules = tuple(parameters[RULES_KEY])
    implemented = {RULE_INLINE, RULE_VERTICAL, RULE_INITIAL}
    _require(
        bool(rules)
        and set(rules) <= implemented
        and len(set(rules)) == len(rules),
        f"{source}: {RULES_KEY} is {sorted(rules)}, and the pass admits a pair "
        f"under a non-empty subset of {sorted(implemented)}",
    )

    declared_rules = tuple(parameters[DECLARED_RULES_KEY])
    outside = sorted(set(declared_rules) - set(rules))
    _require(
        not outside,
        f"{source}: {DECLARED_RULES_KEY} names {outside}, which {RULES_KEY} "
        f"does not admit",
    )
    both = sorted(
        set(parameters[DECLARED_CLASSES_KEY]) & set(parameters[BLANK_CLASSES_KEY])
    )
    _require(
        not both,
        f"{source}: {both} are named by both {DECLARED_CLASSES_KEY} and "
        f"{BLANK_CLASSES_KEY}, which leaves it undecided which repair they take",
    )
    unimplemented = sorted(
        (set(parameters[DECLARED_CLASSES_KEY]) | set(parameters[BLANK_CLASSES_KEY]))
        - set(source_audit.load_audit_config().classes)
    )
    _require(
        not unimplemented,
        f"{source}: {unimplemented} are not classes the source audit places a "
        f"fragment in",
    )
    # The flags have to be flags some page type could actually raise, or the
    # exemption is declared by a key nothing declares and would never apply.
    declared = set()
    for page_type in load_taxonomy().page_types:
        declared.update(page_type.policy)
    unknown = sorted(set(parameters[POLICY_FLAGS_KEY]) - declared)
    _require(
        not unknown,
        f"{source}: {POLICY_FLAGS_KEY} names {unknown}, which no page type "
        f"declares; declared policy keys are {sorted(declared)}",
    )

    return StitchConfig(
        font_size_tolerance=float(parameters["stitch_font_size_tolerance"]),
        min_y_overlap_ratio=float(parameters["stitch_min_y_overlap_ratio"]),
        max_inline_gap_ratio=float(parameters["stitch_max_inline_gap_ratio"]),
        min_x_overlap_ratio=float(parameters["stitch_min_x_overlap_ratio"]),
        max_line_gap_ratio=float(parameters["stitch_max_line_gap_ratio"]),
        max_fragment_chars=int(parameters["stitch_max_fragment_chars"]),
        initial_min_font_ratio=float(parameters["initial_min_font_ratio"]),
        initial_max_chars=int(parameters["initial_max_chars"]),
        initial_max_offset_ratio=float(parameters["initial_max_offset_ratio"]),
        policy_flags=tuple(parameters[POLICY_FLAGS_KEY]),
        layout_labels=tuple(parameters[LAYOUT_LABELS_KEY]),
        terminators=tuple(parameters[TERMINATORS_KEY]),
        closing_marks=tuple(parameters[CLOSING_MARKS_KEY]),
        rules=rules,
        declared_page_rules=declared_rules,
        declared_page_switch=switch,
        declared_page_classes=frozenset(parameters[DECLARED_CLASSES_KEY]),
        blank_classes=frozenset(parameters[BLANK_CLASSES_KEY]),
        sidecar_fields=tuple(parameters[SIDECAR_FIELDS_KEY]),
    )


@lru_cache(maxsize=2)
def load_stitch_config(path: str | None = None) -> StitchConfig:
    """Load and validate ``configs/fragment_stitch.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_stitch_config(raw, config_path.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


# --- reading the face a piece is set in ---------------------------------------


def face_names(page) -> dict[tuple[int | None, str], str]:
    """Every font of one page by the scope and id it is reachable under.

    A font id is scoped: the page has its own resources and every form the page
    draws has its own, so one id names one typeface inside one scope and another
    typeface inside the next. The name is what is comparable across scopes, and
    comparing faces is the whole of asking whether two pieces are set alike.
    """
    names: dict[tuple[int | None, str], str] = {}
    for font in page.pdf_font or ():
        if font.font_id:
            names[(None, font.font_id)] = font.name or font.font_id
    for xobject in page.pdf_xobject or ():
        for font in xobject.pdf_font or ():
            if font.font_id:
                names[(xobject.xobj_id, font.font_id)] = font.name or font.font_id
    return names


def _face_of(names, xobj_id, font_id: str) -> str:
    scoped = names.get((xobj_id, font_id))
    if scoped is not None:
        return scoped
    return names.get((None, font_id), font_id)


def style_key(names, paragraph, config: StitchConfig) -> tuple[str, int] | None:
    """Face and quantised size of one paragraph, or None where it has neither.

    The same shape as the fragment census detector's key, and quantised the same
    way, so a piece the census would call one member of a cluster and a piece
    this pass would join to it are judged alike.
    """
    style = paragraph.pdf_style
    if style is None or not style.font_id or not style.font_size:
        return None
    face = _face_of(names, paragraph.xobj_id, style.font_id)
    if config.font_size_tolerance <= 0:
        return face, round(float(style.font_size) * 1000)
    return face, int(round(float(style.font_size) / config.font_size_tolerance))


def font_size_of(paragraph) -> float | None:
    style = paragraph.pdf_style
    if style is None or not style.font_size:
        return None
    return float(style.font_size)


# --- geometry -----------------------------------------------------------------


def box_tuple(box) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    values = (box.x, box.y, box.x2, box.y2)
    if any(value is None for value in values):
        return None
    return tuple(float(value) for value in values)


def union(left, right):
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def line_bands(paragraph) -> list[tuple[float, float, float, float]]:
    """One box per source line of a paragraph, top first.

    The line recovery is the line structure pass's, run over the same
    characters, so a band this pass measures against is the band that pass would
    have cut at.
    """
    characters = paragraph_characters(paragraph)
    if not characters:
        return []
    bands = []
    for line in recover_lines(characters, load_line_split_config()):
        box = character_union([characters[index] for index in line])
        measured = box_tuple(box)
        if measured is not None:
            bands.append(measured)
    return bands


def _overlap(low_a, high_a, low_b, high_b) -> float:
    return max(0.0, min(high_a, high_b) - max(low_a, low_b))


def _gap(low_a, high_a, low_b, high_b) -> float:
    return max(0.0, max(low_a, low_b) - min(high_a, high_b))


# --- what a group of pieces is ------------------------------------------------


@dataclass
class Group:
    """One run of paragraphs this pass is treating as one unit so far."""

    members: list[int]
    box: tuple[float, float, float, float]
    text: str
    short: bool
    key: tuple[str, int] | None
    size: float | None
    first_band: tuple[float, float, float, float] | None
    last_band: tuple[float, float, float, float] | None
    characters: int
    rules: list[str] = field(default_factory=list)


def _eligible(paragraph, config: StitchConfig) -> bool:
    """Whether one paragraph may take part in a stitch at all.

    Page furniture is fragmented as readily as running text -- a printing slug
    split at a hyphen, a wordmark drawn letter by letter -- and putting it back
    together repairs nothing, because nothing translates it. A composition this
    pass cannot rebuild without changing what the paragraph says disqualifies it
    as well.
    """
    if (paragraph.layout_label or "") not in config.layout_labels:
        return False
    compositions = paragraph.pdf_paragraph_composition or ()
    if not compositions:
        return False
    for composition in compositions:
        if composition_kind(composition) not in SPLITTABLE:
            return False
    return bool(paragraph_characters(paragraph))


def _group_of(index: int, paragraph, names, config: StitchConfig) -> Group | None:
    box = box_tuple(paragraph.box)
    if box is None:
        return None
    bands = line_bands(paragraph)
    text = paragraph.unicode or ""
    characters = paragraph_characters(paragraph)
    return Group(
        members=[index],
        box=box,
        text=text,
        short=len(text.strip()) <= config.max_fragment_chars,
        key=style_key(names, paragraph, config),
        size=font_size_of(paragraph),
        first_band=bands[0] if bands else None,
        last_band=bands[-1] if bands else None,
        characters=len(characters),
    )


def _merged(left: Group, right: Group, rule: str) -> Group:
    return Group(
        members=[*left.members, *right.members],
        box=union(left.box, right.box),
        text=left.text + right.text,
        short=left.short or right.short,
        key=left.key,
        size=left.size,
        first_band=left.first_band,
        last_band=right.last_band or left.last_band,
        characters=left.characters + right.characters,
        rules=[*left.rules, *right.rules, rule],
    )


# --- the unit guard -----------------------------------------------------------


def ends_sentence(text: str, config: StitchConfig) -> bool:
    """Whether a piece of text finishes what it was saying.

    Closing quotation and brackets are stripped first, so a sentence that ends
    inside a quotation is read as ending. A piece ending in nothing at all --
    whitespace, or empty -- is read as not ending one, which is the reading that
    lets the guard fall to the other two conditions rather than deciding on its
    own.
    """
    stripped = text.rstrip()
    while stripped and stripped[-1] in config.closing_marks:
        stripped = stripped[:-1].rstrip()
    if not stripped:
        return False
    return stripped[-1] in config.terminators


def joins_within_unit(left: Group, right: Group, config: StitchConfig) -> bool:
    """Whether a pair is one unit broken in two rather than two units."""
    if ends_sentence(left.text, config):
        return False
    return left.short or right.short


# --- the three rules ----------------------------------------------------------


def accepts_inline(left: Group, right: Group, config: StitchConfig) -> bool:
    """Two pieces standing side by side on one line."""
    upper, lower = left.last_band, right.first_band
    if upper is None or lower is None or left.size is None:
        return False
    shared = _overlap(upper[1], upper[3], lower[1], lower[3])
    shorter = min(upper[3] - upper[1], lower[3] - lower[1])
    if shorter <= 0 or shared / shorter < config.min_y_overlap_ratio:
        return False
    gap = _gap(upper[0], upper[2], lower[0], lower[2])
    return gap <= config.max_inline_gap_ratio * left.size


def accepts_vertical(left: Group, right: Group, config: StitchConfig) -> bool:
    """One piece standing above another in one column."""
    upper, lower = left.box, right.box
    shared = _overlap(upper[0], upper[2], lower[0], lower[2])
    narrower = min(upper[2] - upper[0], lower[2] - lower[0])
    if narrower <= 0 or shared / narrower < config.min_x_overlap_ratio:
        return False
    gap = _gap(upper[1], upper[3], lower[1], lower[3])
    median = statistics.median([upper[3] - upper[1], lower[3] - lower[1]])
    return gap <= config.max_line_gap_ratio * median


def initial_measures(left: Group, right: Group) -> dict | None:
    """What the dropped initial rule reads off a pair, or None where it cannot.

    Reported for every pair whose shape is an initial's -- a cluster of a few
    characters at the upper left of the paragraph beside it -- whether or not
    the size that decides it is reached, so the rule's refusals are as readable
    as its acceptances.
    """
    if right.first_band is None or left.box is None or right.size in (None, 0):
        return None
    body = right.first_band
    return {
        "characters": left.characters,
        "font_ratio": round((left.size or 0.0) / right.size, 4),
        "left_offset": round(left.box[0] - body[0], 2),
        "top_offset": round(body[3] - left.box[3], 2),
        "body_size": round(right.size, 3),
    }


def accepts_initial(left: Group, right: Group, config: StitchConfig) -> bool:
    """A dropped initial that arrived as its own fragment.

    No style guard: an initial is set in another face by design, which is what
    makes it an initial. The unit guard still holds, because letters that are
    not the opening of the words beside them are not an initial either.
    """
    measures = initial_measures(left, right)
    if measures is None:
        return False
    if left.characters > config.initial_max_chars:
        return False
    if measures["font_ratio"] < config.initial_min_font_ratio:
        return False
    reach = config.initial_max_offset_ratio * (right.size or 0.0)
    return (
        -reach <= measures["left_offset"] <= reach
        and -reach <= measures["top_offset"] <= reach
    )


# --- one page ------------------------------------------------------------------


def _fold(groups: list[Group], accept, config: StitchConfig, rule: str) -> list[Group]:
    """One pass of one rule over a page's groups, left to right."""
    folded: list[Group] = []
    for group in groups:
        if folded:
            previous = folded[-1]
            joinable = previous.key is not None and previous.key == group.key
            if rule == RULE_INITIAL:
                joinable = True
            if (
                joinable
                and joins_within_unit(previous, group, config)
                and accept(previous, group, config)
            ):
                folded[-1] = _merged(previous, group, rule)
                continue
        folded.append(group)
    return folded


def paragraph_reference(page_label: int, index: int) -> str:
    """How one paragraph of the pre-stitch page is named in the report."""
    return f"p{page_label}#{index}"


def _blank(paragraph) -> None:
    """Leave a member that has been merged away, without removing it.

    The composition is what the page is drawn from, so emptying it is the whole
    of not being drawn twice, and ``unicode`` goes with it because a paragraph
    that shows nothing says nothing. The paragraph itself stays where it was, so
    the page keeps its count and every index that named a paragraph still does.

    The box goes too, and that is not tidiness. The typesetting stage trims a
    paragraph's lower edge back to clear whatever paragraph stands below it, and
    a member whose box says it still occupies the band it used to occupy is
    exactly such a paragraph -- standing *inside* the box of the unit it was
    merged into. Left in place it squeezes that unit into the band above it and
    the stage shrinks the text to fit: on the page this was written against, a
    five piece stitch came out set at half size. A paragraph with no box is one
    every stage already skips, which is what a paragraph drawing nothing should
    be.
    """
    paragraph.pdf_paragraph_composition = []
    paragraph.unicode = ""
    paragraph.box = None


def _majority_style(characters):
    """The style most of a group's visible characters are set in."""
    counts: dict[tuple, int] = {}
    holder: dict[tuple, object] = {}
    for character in characters:
        style = character.pdf_style
        if style is None or not style.font_id or not style.font_size:
            continue
        if not (character.char_unicode or "").strip():
            continue
        key = (style.font_id, round(float(style.font_size), 4))
        counts[key] = counts.get(key, 0) + 1
        holder.setdefault(key, style)
    if not counts:
        return None
    best = max(counts.items(), key=lambda item: item[1])[0]
    return holder[best]


def _same_style(left, right) -> bool:
    if left is None or right is None:
        return left is right
    return (
        left.font_id == right.font_id
        and left.font_size == right.font_size
        and left.graphic_state == right.graphic_state
    )


def _restyle(characters, style) -> int:
    """Take the minority of a merged unit to the style the majority is set in.

    A merged unit set in two styles reaches the translator as a rich text
    request, with a placeholder around each run, and comes back as a
    reassembled one. What the pieces of a broken word want is to be one run, so
    the minority is taken to the majority and the unit is one style throughout.
    Reported rather than silent: the count is in the record.
    """
    changed = 0
    for character in characters:
        if _same_style(character.pdf_style, style):
            continue
        character.pdf_style = il_version_1.PdfStyle(
            font_id=style.font_id,
            font_size=style.font_size,
            graphic_state=style.graphic_state,
        )
        changed += 1
    return changed


def _stitch(page, group: Group, label: int) -> dict:
    """Merge one group into its first member and leave the rest holding nothing."""
    paragraphs = page.pdf_paragraph
    members = [paragraphs[index] for index in group.members]
    characters = [
        character for member in members for character in paragraph_characters(member)
    ]
    style = _majority_style(characters)
    restyled = _restyle(characters, style) if style is not None else 0

    first = members[0]
    box = character_union(characters)
    if box is not None:
        first.box = box
    if style is not None:
        first.pdf_style = il_version_1.PdfStyle(
            font_id=style.font_id,
            font_size=style.font_size,
            graphic_state=style.graphic_state,
        )
    first.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                box=box,
                pdf_style=first.pdf_style,
                pdf_character=characters,
            )
        )
    ]
    first.unicode = get_char_unicode_string(characters)
    for member in members[1:]:
        _blank(member)

    rule = group.rules[-1] if group.rules else RULE_INLINE
    if RULE_INITIAL in group.rules:
        rule = RULE_INITIAL
    elif RULE_VERTICAL in group.rules:
        rule = RULE_VERTICAL
    return {
        "page": label,
        "paragraph": paragraph_reference(label, group.members[0]),
        "debug_id": first.debug_id,
        "rule": rule,
        "members": len(group.members),
        "member_debug_ids": [member.debug_id for member in members],
        "characters": len(characters),
        "style_normalized": bool(restyled),
        "restyled_characters": restyled,
        "text": first.unicode,
    }


def process_page(
    page,
    label: int,
    config: StitchConfig,
    allowed_rules: tuple[str, ...] | None = None,
    placed: dict[int, str] | None = None,
    admits: frozenset[str] | None = None,
    forbids: frozenset[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Stitch every broken unit of one page. One record per stitch.

    ``allowed_rules`` narrows which rules run. ``placed`` narrows which groups
    may be taken on a page whose lines are records: a group is stitched there
    only where the source audit put at least one of its members in a class that
    admits a stitch, and put none of them in a class that does not.

    At least one rather than all of them, because that is the shape of what is
    being repaired. A broken word is a run of pieces and then the paragraph that
    finishes it, and the finishing paragraph is not a fragment -- it is the rest
    of the sentence. Requiring every member to be placed as a fracture would
    refuse exactly the join the rule exists to make.

    Both are None on a page nothing narrows, which is every page whose lines are
    not records, and there the pass is what it was.
    """
    paragraphs = list(page.pdf_paragraph or ())
    if not paragraphs:
        return [], []
    names = face_names(page)
    rules = config.rules if allowed_rules is None else allowed_rules

    groups: list[Group] = []
    for index, paragraph in enumerate(paragraphs):
        group = (
            _group_of(index, paragraph, names, config)
            if _eligible(paragraph, config)
            else None
        )
        # An ineligible paragraph still occupies its place in reading order, and
        # a stitch may not reach across it: two pieces with something else drawn
        # between them are not one piece.
        groups.append(group if group is not None else _BARRIER)

    # Read before anything is folded. The dropped initial rule is the last one
    # tried, so by the time it runs the inline rule may already have taken the
    # same pair, and a census taken then would report that the shape was never
    # seen rather than what the rule read on it.
    candidates = _initial_candidates(groups, config)
    for rule, accept in (
        (RULE_INLINE, accepts_inline),
        (RULE_VERTICAL, accepts_vertical),
        (RULE_INITIAL, accepts_initial),
    ):
        if rule in rules:
            groups = _fold_barriers(groups, accept, config, rule)

    records = [
        _stitch(page, group, label)
        for group in groups
        if group is not _BARRIER
        and len(group.members) > 1
        and _audit_admits(group.members, placed, admits, forbids)
    ]
    for candidate in candidates:
        candidate["page"] = label
    return records, candidates


def _audit_admits(members, placed, admits, forbids) -> bool:
    """Whether the audit's placement of a group's members admits a stitch."""
    if placed is None:
        return True
    classes = [placed.get(index) for index in members]
    if any(name in (forbids or frozenset()) for name in classes if name):
        return False
    return any(name in (admits or frozenset()) for name in classes if name)


_BARRIER = Group(
    members=[],
    box=(0.0, 0.0, 0.0, 0.0),
    text="",
    short=False,
    key=None,
    size=None,
    first_band=None,
    last_band=None,
    characters=0,
)


def _fold_barriers(groups, accept, config: StitchConfig, rule: str) -> list[Group]:
    """Run one rule over each run of eligible groups, barriers kept in place."""
    folded: list[Group] = []
    run: list[Group] = []
    for group in groups:
        if group is _BARRIER:
            folded.extend(_fold(run, accept, config, rule))
            folded.append(group)
            run = []
            continue
        run.append(group)
    folded.extend(_fold(run, accept, config, rule))
    return folded


def _initial_candidates(groups, config: StitchConfig) -> list[dict]:
    """Every pair shaped like a dropped initial, with what the rule read on it.

    A census rather than a decision: a pair is listed whenever the piece before
    a paragraph is small enough to be an initial, whatever the size that decides
    it turns out to be, so a refusal carries the figure that refused it.
    """
    found = []
    for previous, group in zip(groups, groups[1:], strict=False):
        if previous is _BARRIER or group is _BARRIER:
            continue
        if previous.characters > config.initial_max_chars:
            continue
        if len((group.text or "").strip()) <= config.initial_max_chars:
            continue
        measures = initial_measures(previous, group)
        if measures is None:
            continue
        found.append(
            {
                "fragment": previous.text,
                "body": group.text[:40],
                "accepted": bool(
                    joins_within_unit(previous, group, config)
                    and accepts_initial(previous, group, config)
                ),
                "within_unit": joins_within_unit(previous, group, config),
                **measures,
            }
        )
    return found


# --- one document --------------------------------------------------------------


def as_record(
    config: StitchConfig,
    stitches: list[dict],
    pages: list[dict],
    candidates: list[dict],
) -> dict:
    return {
        "switch": SWITCH,
        "window_switch": WINDOW_SWITCH,
        "policy_flags": list(config.policy_flags),
        "rules": list(config.rules),
        "max_fragment_chars": config.max_fragment_chars,
        "initial_min_font_ratio": config.initial_min_font_ratio,
        "initial_max_chars": config.initial_max_chars,
        "totals": {
            "pages": len(pages),
            "exempt_pages": sum(1 for page in pages if page["exempt"]),
            "stitches": len(stitches),
            "merged_paragraphs": sum(item["members"] for item in stitches),
            "blanked_paragraphs": sum(item["members"] - 1 for item in stitches),
            "style_normalized": sum(1 for item in stitches if item["style_normalized"]),
            "initial_candidates": len(candidates),
            "initial_accepted": sum(1 for item in candidates if item["accepted"]),
        },
        "by_rule": {
            rule: sum(1 for item in stitches if item["rule"] == rule)
            for rule in config.rules
        },
        "pages": pages,
        "stitches": stitches,
        "initial_candidates": candidates,
    }


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def _audit_declared(translation_config, labeled_pages, resolve, config):
    """Place the fragments of every declared page, keyed page then paragraph.

    Read from the document in hand and the file it came from, so the audit is
    of the run being made rather than of a sidecar left by another one. A page
    the audit cannot be run over -- no input file beside the run -- places
    nothing, and a page that places nothing is stitched nowhere, which is the
    behaviour the switch turns off.
    """
    declared = [
        (label, page)
        for label, page in labeled_pages
        if config.declared(resolve(page.page_kind))
    ]
    if not declared:
        return {}
    pdf = getattr(translation_config, "input_file", None)
    if not pdf or not Path(pdf).exists():
        logger.warning(
            "fragment stitch: no input file beside the run, so no declared page "
            "is audited and none is stitched"
        )
        return {}
    audit_config = source_audit.load_audit_config()
    placed: dict[int, dict[int, str]] = {}
    records = []
    for label, page in declared:
        words = source_audit.independent_words(Path(pdf), label - 1)
        found = source_audit.audit_page(page, words, label, audit_config)
        records.extend(found)
        for item in found:
            index = int(item["paragraph"].split("#")[1])
            # A paragraph appearing in more than one band is placed by the band
            # that placed it at all: a class is evidence and undetermined is
            # the absence of it.
            current = placed.setdefault(label, {}).get(index)
            if current is None or current == source_audit.CLASS_UNDETERMINED:
                placed[label][index] = item["class"]
    source_audit.write_report(
        Path(translation_config.get_working_file_path(source_audit.REPORT_NAME)).parent,
        {
            "pages": [label for label, _page in declared],
            "band_overlap_ratio": audit_config.band_overlap_ratio,
            "max_fragment_chars": audit_config.max_fragment_chars,
            "min_evidence_chars": audit_config.min_evidence_chars,
            "counts": {
                name: sum(1 for item in records if item["class"] == name)
                for name in audit_config.classes
            },
            "fragments": records,
        },
    )
    return placed


def _blank_duplicates(page, label: int, placed: dict, config: StitchConfig):
    """Empty the members of a layer the page holds twice.

    Stitching is the wrong repair for these and blanking is the right one, by
    the same reasoning that makes stitching right for a broken word: what the
    page needs is for the text to appear once. The blanking is the one the
    stitch already does to a merged away member, so a blanked paragraph keeps
    its place and gives up its box.
    """
    paragraphs = list(page.pdf_paragraph or ())
    records = []
    for index, name in sorted(placed.items()):
        if name not in config.blank_classes or index >= len(paragraphs):
            continue
        paragraph = paragraphs[index]
        text = paragraph.unicode
        if not text:
            continue
        records.append(
            {
                "page": label,
                "paragraph": paragraph_reference(label, index),
                "text": text,
                "audit_class": name,
            }
        )
        _blank(paragraph)
    return records


def apply(translation_config, labeled_pages, policy_of=None) -> dict | None:
    """Stitch every page of one document. None where the switch is down."""
    if not enabled(translation_config):
        return None
    config = load_stitch_config()
    resolve = policy_of if policy_of is not None else load_taxonomy().policy_of

    unblocked = bool(getattr(translation_config, config.declared_page_switch, False))
    audit = (
        _audit_declared(translation_config, labeled_pages, resolve, config)
        if unblocked
        else {}
    )

    stitches: list[dict] = []
    pages: list[dict] = []
    candidates: list[dict] = []
    blanked_records: list[dict] = []
    for label, page in labeled_pages:
        exempt = config.declared(resolve(page.page_kind))
        if not exempt:
            records, found = process_page(page, label, config)
        elif unblocked:
            placed = audit.get(label, {})
            records, found = process_page(
                page,
                label,
                config,
                allowed_rules=config.declared_page_rules,
                placed=placed,
                admits=config.declared_page_classes,
                forbids=config.blank_classes,
            )
            blanked_records.extend(_blank_duplicates(page, label, placed, config))
        else:
            records, found = [], []
        stitches.extend(records)
        candidates.extend(found)
        pages.append(
            {
                "page": label,
                "exempt": exempt,
                "unblocked": bool(exempt and unblocked),
                "paragraphs": len(page.pdf_paragraph or ()),
                "stitches": len(records),
                "blanked": sum(item["members"] - 1 for item in records),
            }
        )

    expected = set(config.sidecar_fields)
    for item in stitches:
        if set(item) != expected:
            raise FragmentStitchError(
                f"{REPORT_NAME}: a stitch record carries {sorted(item)}, "
                f"and {CONFIG_PATH.name} declares {sorted(expected)}"
            )
        if item["rule"] not in config.rules:
            raise FragmentStitchError(
                f"{REPORT_NAME}: a stitch names rule {item['rule']!r}, "
                f"and {CONFIG_PATH.name} declares {sorted(config.rules)}"
            )

    record = as_record(config, stitches, pages, candidates)
    record["declared_page_switch"] = config.declared_page_switch
    record["declared_pages_unblocked"] = unblocked
    record["declared_page_rules"] = list(config.declared_page_rules)
    record["duplicate_blanked"] = blanked_records
    record["totals"]["duplicate_blanked"] = len(blanked_records)
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    write_report(working_dir, record)
    logger.debug(
        "fragment stitch: %d stitch(es) over %d page(s), %d paragraph(s) blanked",
        record["totals"]["stitches"],
        record["totals"]["pages"],
        record["totals"]["blanked_paragraphs"],
    )
    return record
