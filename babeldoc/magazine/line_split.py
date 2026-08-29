"""Line structure preservation: one source line becomes one translation unit.

Why a page needs this
---------------------

Some magazine layouts do not set running text at all. A contents page sets
records: one entry is a title, a run of leader dots, a folio and a byline, and
what holds those four together as one entry is the line they stand on. The
paragraph finder groups characters by layout region and then assembles the lines
it found into one paragraph, which is the right thing to do for prose and the
wrong thing to do for a record: the entry, its folio and the next entry's byline
arrive at the translator as one stream, come back as one stream, and are laid
out again as a wrapped block in which no line is the record it was.

So on a page whose declared policy raises the flag, this pass cuts every
paragraph back into the records it was assembled from and gives each record a
paragraph of its own. Downstream, that is all it takes: the translator's unit is
the paragraph, so one record is one request, and the typesetting stage lays each
record out inside the band and measure it occupied.

Which lines make one record is read off the paragraph rather than assumed. An
entry is often one line, and on a grid where every entry is a line the line is
the record. But an entry set over three tight lines with the next entry a full
line's space below is one entry, and cutting it at its line breaks hands the
translator a third of a sentence at a time. The distances between consecutive
lines decide it: the lines inside one record are set close and the records are
set apart, so a distance far above the paragraph's own median is a record
boundary and a paragraph whose distances are all alike has none. See
``record_groups``.

What a line is here, and why it is recovered rather than read
-------------------------------------------------------------

The intermediate language has a line carrier -- ``PdfLine``, built by
``ParagraphFinder.create_line`` -- and by the time this pass runs there is not
one left in the document. ``StylesAndFormulas.process_page_styles`` rebuilds
every paragraph's compositions as style runs and drops the line grouping; on the
corpus sample this pass was written against, 582 lines after the paragraph
finder are 0 after the styling stage. A style run also crosses line boundaries,
so the boundary cannot be read off the composition list either.

What does survive is the geometry of every character. So the line is recovered
the way the paragraph finder found it in the first place: the paragraph's
vertical range is scanned, positions crossed by no character are gaps, and the
characters are bucketed by which gap they fall between. Running the same scan
over characters instead of one-character compositions is what makes the recovery
the finder's own answer rather than a second opinion. Where it disagrees it
under-splits -- a paragraph of tightly leaded prose whose ascenders and
descenders interlock has no gap to find -- and under-splitting is the safe
direction: the paragraph stays whole, which is what it would have been anyway.

Where this sits and why
-----------------------

Between the classifier and the chain builder: the flag is a page policy, so the
kinds have to be settled, and splitting after the chains were built would leave
the chain indices pointing at paragraphs that no longer exist. The only
extension owned call in that window is ``hitl.after_page_classify``, which is
also where a human ruling on a page kind is applied, so this runs at the end of
that hook and sees the kind the run went on to use. Its own switch is
``magazine_line_structure`` and it is down by default; with it down this module
returns having read nothing.

What may be cut, and what may not
---------------------------------

A declared page is not records all the way down. A contents page can carry a
column of running prose beside the entries -- an editor's letter set in the same
measure -- and cutting running prose into lines would hand the translator half a
sentence at a time and give back a translation of half a sentence. So the split is narrowed to the paragraphs
that look like records, by two bounds that both have to hold. A record line is
short because the record is short, so a paragraph whose mean line is longer than
``max_line_chars`` is prose and is left whole. And a record says at its own line
boundary that it is one -- the leader is set in another face, the byline in a
third -- so where ``require_style_heterogeneity`` is up a paragraph whose lines
are all set in the same faces is left whole as well. A paragraph the bounds
exempt is recorded in the sidecar with the reason, so what was not cut is as
readable as what was.

What is not reachable from here
-------------------------------

The leader dots are ordinary characters and so is the folio. Nothing in the
intermediate language says "fill to the right margin" or "set this token flush
right"; the alignment of a source leader is an emergent property of the x
coordinate each dot was drawn at. A line laid out again is laid out from the
left edge of its box with the font's own advance widths, so the dots keep their
place in the record and lose their alignment with the margin. Splitting restores
the record boundary; restoring the alignment would need a fill rule that does
not exist at this layer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("line_split.json")

REPORT_NAME = "line_split.report.json"

# The switch, by the name the caller sets on the translation config.
SWITCH = "magazine_line_structure"

# The switch this pass rides: the window it has to run in is inside the hook
# that stage calls, so a run without the classifier has no settled kind to read.
WINDOW_SWITCH = "magazine_page_classify"

POLICY_FLAGS_KEY = "policy_flags"
SIDECAR_FIELDS_KEY = "sidecar_fields"
EXEMPTION_FIELDS_KEY = "exemption_fields"
EXEMPTION_REASONS_KEY = "exemption_reasons"

RECORD_SINGLE = "single_visual_line"
RECORD_BLOCK = "block"
RECORD_PROSE = "prose_exempt"
RECORD_KINDS = frozenset((RECORD_SINGLE, RECORD_BLOCK, RECORD_PROSE))
CHAIN_EXCLUDED_RECORD_KINDS = frozenset((RECORD_SINGLE, RECORD_BLOCK))

# Why a paragraph of a declared page was left whole. Both are the narrowing the
# bounds perform, and the vocabulary is declared in the configuration so a
# reason the report may carry cannot be invented in code.
REASON_LONG_LINES = "long_lines"
REASON_UNIFORM_STYLING = "uniform_styling"

# How a line paragraph is named after the paragraph it came out of.
LINE_ID_SEPARATOR = "#L"


class LineSplitError(ConfigError):
    """Raised when the line split configuration is malformed."""


@dataclass(frozen=True)
class LineSplitConfig:
    """Everything bounded about cutting a paragraph back into its lines."""

    scan_step: float
    flat_paragraph_height: float
    min_gap_collisions: int
    min_line_characters: int
    max_line_chars: float
    require_style_heterogeneity: bool
    record_gap_ratio: float
    minimum_readable_scale: float
    policy_flags: tuple[str, ...]
    sidecar_fields: tuple[str, ...]
    exemption_fields: tuple[str, ...]
    exemption_reasons: tuple[str, ...]

    def declared(self, policy: dict | None) -> bool:
        """Whether a page carrying this policy asks for its lines kept.

        A page with no policy -- no kind, or a kind outside the vocabulary --
        asks for nothing, which is the same answer as a policy that raises no
        flag. Every flag is read by name from the configuration, so no page type
        is named here.
        """
        if not policy:
            return False
        return any(bool(policy.get(flag, False)) for flag in self.policy_flags)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LineSplitError(message)


def parse_line_split_config(raw: dict, source: str) -> LineSplitConfig:
    """Validate one configuration mapping into the policy it declares."""
    try:
        parameters = dict(validate_bounded_config(raw, CONFIG_PATH))
    except ConfigError as exc:
        raise LineSplitError(str(exc)) from exc

    for key in (
        POLICY_FLAGS_KEY,
        SIDECAR_FIELDS_KEY,
        EXEMPTION_FIELDS_KEY,
        EXEMPTION_REASONS_KEY,
    ):
        _require(key in parameters, f"{source}: missing {key}")
    flags = tuple(parameters[POLICY_FLAGS_KEY])

    # The reasons an exemption may name are declared, and the pass has exactly
    # one rule per declared reason: a vocabulary and a code path that disagree
    # would let a narrowing happen under a name no reader could look up.
    reasons = tuple(parameters[EXEMPTION_REASONS_KEY])
    _require(
        set(reasons) == {REASON_LONG_LINES, REASON_UNIFORM_STYLING},
        f"{source}: {EXEMPTION_REASONS_KEY} is {sorted(reasons)}, and the pass "
        f"exempts for {sorted((REASON_LONG_LINES, REASON_UNIFORM_STYLING))}",
    )

    # The flags have to be flags some page type could actually raise, or the
    # pass is declared by a key nothing declares and would never run.
    declared = set()
    for page_type in load_taxonomy().page_types:
        declared.update(page_type.policy)
    unknown = sorted(set(flags) - declared)
    _require(
        not unknown,
        f"{source}: {POLICY_FLAGS_KEY} names {unknown}, which no page type "
        f"declares; declared policy keys are {sorted(declared)}",
    )

    return LineSplitConfig(
        scan_step=float(parameters["scan_step"]),
        flat_paragraph_height=float(parameters["flat_paragraph_height"]),
        min_gap_collisions=int(parameters["min_gap_collisions"]),
        min_line_characters=int(parameters["min_line_characters"]),
        max_line_chars=float(parameters["max_line_chars"]),
        require_style_heterogeneity=bool(
            int(parameters["require_style_heterogeneity"])
        ),
        record_gap_ratio=float(parameters["record_gap_ratio"]),
        minimum_readable_scale=float(parameters["minimum_readable_scale"]),
        policy_flags=flags,
        sidecar_fields=tuple(parameters[SIDECAR_FIELDS_KEY]),
        exemption_fields=tuple(parameters[EXEMPTION_FIELDS_KEY]),
        exemption_reasons=reasons,
    )


@lru_cache(maxsize=2)
def load_line_split_config(path: str | None = None) -> LineSplitConfig:
    """Load and validate ``configs/line_split.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_line_split_config(raw, config_path.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


@dataclass(frozen=True)
class SourceUnit:
    """Runtime source-container identity for one post-split paragraph.

    Document IL has no extension field for a structure pass.  The registry is
    keyed by object identity for one ``apply`` lifetime, but retains only this
    immutable payload rather than the paragraph/page graph.  A
    physical-page/debug-id fallback lets an otherwise identical transaction
    copy retain the same bounded source container without changing the IL
    schema.
    """

    # ``parent_ref`` is the stable physical alias used by frozen truth.  Its
    # paragraph ordinal excludes debug-only overlay paragraphs.  The runtime
    # refs retain the actual IL indexes before and after splitting.
    parent_ref: str
    runtime_parent_ref: str
    parent_refs: tuple[str, ...]
    runtime_parent_refs: tuple[str, ...]
    source_ref: str
    record_kind: str
    child_order: int
    source_box: tuple[float, float, float, float] | None
    source_text_sha256: str
    source_text: str
    source_characters_sha256: str
    source_characters_text: str
    fixed_companion: bool


_SOURCE_UNITS_BY_ID: dict[int, SourceUnit] = {}
_SOURCE_UNITS_BY_DEBUG: dict[tuple[int, str], SourceUnit] = {}
_RULING_OWNERS_BY_ID: dict[int, tuple[object, tuple[str, ...]]] = {}
_RULING_OWNERS_BY_DEBUG: dict[tuple[int, str], tuple[str, ...]] = {}


def _box_record(box) -> list[float] | None:
    if box is None or any(getattr(box, name, None) is None for name in ("x", "y", "x2", "y2")):
        return None
    return [float(getattr(box, name)) for name in ("x", "y", "x2", "y2")]


def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _register_source_unit(paragraph, physical_page: int, unit: SourceUnit) -> None:
    _SOURCE_UNITS_BY_ID[id(paragraph)] = unit
    if paragraph.debug_id:
        _SOURCE_UNITS_BY_DEBUG[(physical_page, paragraph.debug_id)] = unit


def _register_ruling_owner(
    paragraph,
    physical_page: int,
    parent_refs: tuple[str, ...],
) -> None:
    """Record which pre-split paragraph(s) own one post-split paragraph."""
    # Keep the object itself so a later object reusing the same CPython id
    # cannot inherit stale ownership before the next apply clears the table.
    _RULING_OWNERS_BY_ID[id(paragraph)] = (paragraph, parent_refs)
    if not paragraph.debug_id:
        return
    key = (physical_page, paragraph.debug_id)
    previous = _RULING_OWNERS_BY_DEBUG.get(key)
    if previous is None or previous == parent_refs:
        _RULING_OWNERS_BY_DEBUG[key] = parent_refs
    else:
        # A copied paragraph with a colliding debug id cannot prove ownership.
        _RULING_OWNERS_BY_DEBUG[key] = ()


def _ruling_owner_refs(
    paragraph,
    physical_page: int,
) -> tuple[str, ...] | None:
    held = _RULING_OWNERS_BY_ID.get(id(paragraph))
    if held is not None and held[0] is paragraph:
        return held[1]
    if paragraph.debug_id:
        return _RULING_OWNERS_BY_DEBUG.get(
            (physical_page, paragraph.debug_id)
        )
    return None


def source_unit(paragraph, physical_page: int | None = None) -> SourceUnit | None:
    """Return the structure unit belonging to ``paragraph``, if it has one."""
    held = _SOURCE_UNITS_BY_ID.get(id(paragraph))
    if held is not None:
        return held
    if physical_page is not None and paragraph.debug_id:
        return _SOURCE_UNITS_BY_DEBUG.get((physical_page, paragraph.debug_id))
    return None


def record_kind(paragraph, physical_page: int | None = None) -> str | None:
    unit = source_unit(paragraph, physical_page)
    return None if unit is None else unit.record_kind


def excludes_chain_endpoint(paragraph, physical_page: int | None = None) -> bool:
    return record_kind(paragraph, physical_page) in CHAIN_EXCLUDED_RECORD_KINDS


def resolve_parent_index(page, physical_page: int, parent_ref: str) -> int | None:
    """Resolve one pre-split parent ref to its unique post-split paragraph.

    A split parent has more than one child and is intentionally ambiguous: a
    paragraph ruling must name an owner, never be guessed onto one of several
    records.  Ownership aliases cover both bounded source units and untouched
    paragraphs on a page where only other paragraphs became source units.
    """
    registered = [
        _ruling_owner_refs(paragraph, physical_page)
        for paragraph in page.pdf_paragraph or ()
    ]
    if not any(owner is not None for owner in registered):
        prefix = f"p{physical_page}#"
        if parent_ref.startswith(prefix):
            try:
                index = int(parent_ref[len(prefix) :])
            except ValueError:
                return None
            physical_paragraphs = [
                runtime_index
                for runtime_index, paragraph in enumerate(page.pdf_paragraph or ())
                if paragraph_characters(paragraph) or not is_debug_overlay(paragraph)
            ]
            if 0 <= index < len(physical_paragraphs):
                return physical_paragraphs[index]
        return None
    matches = [
        index
        for index, owner_refs in enumerate(registered)
        if owner_refs is not None and parent_ref in owner_refs
    ]
    return matches[0] if len(matches) == 1 else None


# --- reading the geometry the characters still carry --------------------------


def character_box(character):
    """The box a character's vertical extent is measured on.

    The visual box where there is one, which is what both the paragraph finder
    and the styling stage measure a line and a style run with; the drawing box
    otherwise, so a character that never got a visual box still has a position.
    """
    visual = getattr(character, "visual_bbox", None)
    if visual is not None and visual.box is not None:
        return visual.box
    return character.box


def _bounds(character) -> tuple[float, float] | None:
    box = character_box(character)
    if box is None or box.y is None or box.y2 is None:
        return None
    return float(box.y), float(box.y2)


def character_union(characters):
    """The box covering every character, measured as the stages measure it."""
    boxes = [character_box(item) for item in characters]
    boxes = [
        box
        for box in boxes
        if box is not None and None not in (box.x, box.y, box.x2, box.y2)
    ]
    if not boxes:
        return None
    return il_version_1.Box(
        x=min(box.x for box in boxes),
        y=min(box.y for box in boxes),
        x2=max(box.x2 for box in boxes),
        y2=max(box.y2 for box in boxes),
    )


# The composition kinds this pass understands, and whether one may be cut. A
# formula is a unit of its own and is never cut; everything else is a run of
# characters whose grouping this pass is allowed to regroup. Public because the
# regroupable kinds are the same question wherever a pass rebuilds a paragraph's
# compositions, and naming them once is what keeps the package to one place that
# spells a composition member out.
SPLITTABLE = ("pdf_line", "pdf_same_style_characters")
ATOMIC = ("pdf_formula", "pdf_character", "pdf_same_style_unicode_characters")

# The one atomic kind that carries drawing of its own.
FORMULA_KIND = ATOMIC[0]


def composition_kind(composition) -> str | None:
    for name in (*SPLITTABLE, *ATOMIC):
        if getattr(composition, name, None) is not None:
            return name
    return None


def holds_formula(paragraph) -> bool:
    """Whether one paragraph carries a formula among its compositions.

    Here rather than beside its caller because the composition member names
    belong to the modules that classify a composition, and asking this question
    anywhere else would be a second place naming them. What the answer is for is
    layout: the typesetting stage hands a formula's curves and forms to the
    *page* rather than to the paragraph, so a paragraph holding one cannot be
    moved without leaving its own artwork behind.
    """
    return any(
        composition_kind(composition) == FORMULA_KIND
        for composition in paragraph.pdf_paragraph_composition or ()
    )


def composition_characters(composition, kind: str) -> list:
    if kind == "pdf_character":
        return [composition.pdf_character]
    if kind == "pdf_same_style_unicode_characters":
        return []
    holder = getattr(composition, kind)
    return list(holder.pdf_character or ())


def paragraph_characters(paragraph) -> list:
    """Every character of one paragraph, in the order it is stored in."""
    characters = []
    for composition in paragraph.pdf_paragraph_composition or ():
        kind = composition_kind(composition)
        if kind is None:
            continue
        characters.extend(composition_characters(composition, kind))
    return characters


def _box_contains(outer, inner) -> bool:
    outer_record = _box_record(outer)
    inner_record = _box_record(inner)
    if outer_record is None or inner_record is None:
        return False
    return (
        outer_record[0] <= inner_record[0]
        and outer_record[1] <= inner_record[1]
        and outer_record[2] >= inner_record[2]
        and outer_record[3] >= inner_record[3]
    )


def embedded_figure_artwork(page, paragraph) -> dict | None:
    """Prove that one source paragraph is paint inside embedded artwork.

    A paragraph merely being small, or merely carrying an ``xobj_id``, is not
    enough: both occur in ordinary page text.  The conservative proof used here
    requires an actual nested page XObject, original passthrough-only non-space
    characters owned by that XObject, and geometry nesting both paragraph and
    XObject in exactly one detected figure. ParagraphFinder may synthesize
    whitespace without an XObject owner, and a Form's declared box may omit
    glyph ink; neither weakens the non-space ownership plus figure proof. A
    generated, mixed, root-page, or geometrically independent paragraph remains
    in the translation path.
    """
    xobj_id = getattr(paragraph, "xobj_id", None)
    compositions = list(paragraph.pdf_paragraph_composition or ())
    if xobj_id is None or not compositions:
        return None

    characters = []
    owned_characters = 0
    synthetic_whitespace_characters = 0
    for composition in compositions:
        if composition_kind(composition) != "pdf_same_style_characters":
            return None
        held = list(composition.pdf_same_style_characters.pdf_character or ())
        if not held:
            return None
        for character in held:
            if bool(character.debug_info):
                return None
            text = character.char_unicode or ""
            if character.xobj_id == xobj_id:
                if not text.isspace():
                    owned_characters += 1
                continue
            if character.xobj_id is None and text.isspace():
                # ParagraphFinder may synthesize inter-run whitespace.  It has
                # no PDF owner, but it cannot prove content outside the Form.
                synthetic_whitespace_characters += 1
                continue
            return None
        characters.extend(held)
    if not characters or not owned_characters:
        return None

    xobjects = [
        xobject
        for xobject in page.pdf_xobject or ()
        if xobject.xobj_id == xobj_id
    ]
    if len(xobjects) != 1:
        return None
    xobject = xobjects[0]
    figures = [
        layout
        for layout in page.page_layout or ()
        if (layout.class_name or "").casefold() == "figure"
        and _box_contains(layout.box, xobject.box)
        and _box_contains(layout.box, paragraph.box)
    ]
    if len(figures) != 1:
        return None
    figure = figures[0]
    return {
        "reason": "embedded_figure_xobject",
        "xobj_id": xobj_id,
        "xobject_box": _box_record(xobject.box),
        "figure_box": _box_record(figure.box),
        "owned_characters": owned_characters,
        "synthetic_whitespace_characters": synthetic_whitespace_characters,
        "paragraph_inside_xobject": _box_contains(xobject.box, paragraph.box),
    }


def is_debug_overlay(paragraph) -> bool:
    """Whether every actual text carrier is explicitly diagnostic-only.

    Before formal Typesetting a debug label is a Unicode holder.  Afterwards it
    is a run of laid-out ``PdfCharacter`` objects which inherit that holder's
    flag.  Requiring every carrier to opt in keeps a paragraph containing even
    one real character in the product path.  Formula drawing is conservative:
    an unmarked curve or any form prevents whole-paragraph exclusion.
    """
    saw_text = False
    for composition in paragraph.pdf_paragraph_composition or ():
        unicode_holder = composition.pdf_same_style_unicode_characters
        if unicode_holder is not None:
            saw_text = True
            if not bool(unicode_holder.debug_info):
                return False
            continue

        kind = composition_kind(composition)
        if kind is None:
            continue
        characters = composition_characters(composition, kind)
        if characters:
            saw_text = True
            if any(not bool(character.debug_info) for character in characters):
                return False
        if kind == FORMULA_KIND:
            formula = composition.pdf_formula
            if formula.pdf_form or any(
                not bool(curve.debug_info) for curve in formula.pdf_curve or ()
            ):
                return False
    return saw_text


def characters_text(characters) -> str:
    """Exact stored source characters, with no punctuation normalization."""
    return "".join(character.char_unicode or "" for character in characters)


def has_multiple_source_rows(characters) -> bool:
    """Whether drawing baselines prove multiple rows despite a spanning glyph.

    A large folio or decorative initial can cross every whitespace gap and make
    the collision scan conservatively return one bucket.  Its drawing baseline
    does not erase the distinct baselines of the ordinary text around it.  This
    fallback only classifies the untouched paragraph as a block; it never cuts
    on this weaker signal.
    """
    positions = []
    sizes = []
    for character in characters:
        if not (character.char_unicode or "").strip():
            continue
        box = character.box
        if box is None or box.y is None:
            continue
        positions.append(float(box.y))
        style = character.pdf_style
        if style is not None and style.font_size is not None:
            size = float(style.font_size)
            if size > 0:
                sizes.append(size)
    if len(positions) < 2 or not sizes:
        return False
    tolerance = max(1.0, statistics.median(sizes) * 0.55)
    rows = 1
    previous = min(positions)
    for position in sorted(positions):
        if position - previous > tolerance:
            rows += 1
        previous = position
    return rows > 1


def recover_lines(characters, config: LineSplitConfig) -> list[list[int]]:
    """The source lines of one character sequence, as index buckets.

    The paragraph finder's threading scan, run over characters. A paragraph
    whose characters span less than one line's height cannot hold two lines and
    comes back as one; so does one the scan finds no gap in, which is the safe
    answer where two lines interlock.
    """
    pairs = [_bounds(character) for character in characters]
    measured = [pair for pair in pairs if pair is not None]
    if not measured:
        return [list(range(len(characters)))] if characters else []

    low = min(pair[0] for pair in measured)
    high = max(pair[1] for pair in measured)
    if high - low < config.flat_paragraph_height:
        return [list(range(len(characters)))]

    steps = int((high - low) / config.scan_step) + 1
    crossings = [0] * (steps + 1)
    for start, end in measured:
        first = int((high - end) / config.scan_step)
        last = int((high - start) / config.scan_step) + 1
        first = max(0, min(first, steps))
        last = max(0, min(last, steps))
        crossings[first] += 1
        crossings[last] -= 1

    running = 0
    counts = []
    for index in range(steps):
        running += crossings[index]
        counts.append(running)

    separators: list[float] = []
    in_gap = False
    for index, count in enumerate(counts):
        if count < config.min_gap_collisions and not in_gap:
            in_gap = True
            separators.append(high - index * config.scan_step)
        elif count >= config.min_gap_collisions:
            in_gap = False
    if not separators:
        return [list(range(len(characters)))]
    separators.sort(reverse=True)

    buckets: list[list[int]] = [[] for _ in range(len(separators) + 1)]
    for index, pair in enumerate(pairs):
        if pair is None:
            # A character with no measurable box belongs to whatever line the
            # characters around it are on, which is the one being filled.
            target = next(
                (bucket for bucket in reversed(buckets) if bucket), buckets[0]
            )
            target.append(index)
            continue
        centre = (pair[0] + pair[1]) / 2
        position = 0
        for separator in separators:
            if centre > separator:
                break
            position += 1
        buckets[position].append(index)
    filled = [sorted(bucket) for bucket in buckets if bucket]
    return _merge_short_lines(filled, characters, config)


def _merge_short_lines(lines, characters, config: LineSplitConfig) -> list[list[int]]:
    """Fold a line too small to be a record into the line above it.

    A stray mark, a rule drawn as a character, an orphaned accent: below the
    configured floor a recovered line is not an entry of its own, and giving it
    a paragraph would give it a translation request.
    """
    merged: list[list[int]] = []
    for bucket in lines:
        text = "".join((characters[index].char_unicode or "") for index in bucket)
        if merged and len(text.strip()) < config.min_line_characters:
            merged[-1].extend(bucket)
            continue
        merged.append(list(bucket))
    return merged


# --- which paragraphs are records, and which are prose -------------------------


def line_text(characters, line) -> str:
    return "".join((characters[index].char_unicode or "") for index in line)


def mean_line_chars(characters, lines) -> float:
    """Non-space characters per recovered line, over the whole paragraph.

    The measure a record is short by. Counted over the characters rather than
    the paragraph's own text so that it is the same characters the lines were
    recovered from, and averaged rather than taken at the longest line so that
    one full measure line inside a block of records does not decide the answer.
    """
    if not lines:
        return 0.0
    total = sum(
        1
        for line in lines
        for character in (characters[index] for index in line)
        if (character.char_unicode or "").strip()
    )
    return total / len(lines)


def line_faces(characters, line) -> frozenset[str]:
    """The faces one line is set in, by font id.

    Whitespace carries a style of its own and no shape, so it says nothing
    about how the line is set and is left out. Size is left out as well: a
    record announces itself by changing face -- the leader, the byline -- and
    reading a size difference inside one face as a boundary would widen the
    split on a signal a wrapped prose line can also carry.
    """
    faces = set()
    for index in line:
        character = characters[index]
        if not (character.char_unicode or "").strip():
            continue
        style = character.pdf_style
        if style is not None and style.font_id is not None:
            faces.add(style.font_id)
    return frozenset(faces)


def style_heterogeneous(characters, lines) -> bool:
    """Whether the paragraph's lines are not all set in the same faces."""
    return len({line_faces(characters, line) for line in lines}) > 1


def line_band(characters, line) -> tuple[float, float] | None:
    """The vertical extent of one recovered line."""
    bounds = [_bounds(characters[index]) for index in line]
    bounds = [pair for pair in bounds if pair is not None]
    if not bounds:
        return None
    return min(pair[0] for pair in bounds), max(pair[1] for pair in bounds)


def line_gaps(characters, lines) -> list[float] | None:
    """The vertical distance between each pair of consecutive lines.

    None where a line cannot be measured, which is the answer that leaves the
    record question undecided rather than deciding it on a partial reading.
    Distances are never negative: two lines whose ascenders and descenders
    interlock are as close as two lines get.
    """
    bands = [line_band(characters, line) for line in lines]
    if any(band is None for band in bands):
        return None
    return [
        max(0.0, bands[index][0] - bands[index + 1][1])
        for index in range(len(bands) - 1)
    ]


def record_groups(characters, lines, config: LineSplitConfig) -> list[list[list[int]]]:
    """The lines of one paragraph grouped into the records they set.

    What separates two records is space, and what holds one together is the
    absence of it: an entry set over three tight lines is one entry, and the
    next entry begins after a distance the tight lines do not have. So the
    distances between consecutive lines are measured, their median taken, and a
    distance of at least ``record_gap_ratio`` of the median is where one record
    ends and the next begins. The median is the paragraph's own leading, so the
    bound is read against the way this paragraph is set rather than against a
    figure carried in from another page.

    A paragraph in which no distance reaches the bound has one peak and no
    boundary in it. There the line is the record, which is the answer this pass
    has always given, and the grouping returns the lines unchanged. Reading that
    case as one record instead would be the other extreme and a worse one: a
    grid of entries set one to a line would come back as one entry.
    """
    one_each = [[list(line)] for line in lines]
    if len(lines) < 2:
        return one_each
    gaps = line_gaps(characters, lines)
    if not gaps:
        return one_each
    median = statistics.median(gaps)
    if median <= 0:
        return one_each
    bound = config.record_gap_ratio * median
    if not any(gap >= bound for gap in gaps):
        return one_each
    groups: list[list[list[int]]] = [[list(lines[0])]]
    for position, gap in enumerate(gaps):
        if gap >= bound:
            groups.append([list(lines[position + 1])])
        else:
            groups[-1].append(list(lines[position + 1]))
    return groups


@dataclass(frozen=True)
class Examination:
    """What the bounds saw in one paragraph, and what they decided."""

    lines: list[list[int]]
    mean_line_chars: float
    heterogeneous: bool
    reason: str | None

    @property
    def admitted(self) -> bool:
        return self.reason is None


def examine(paragraph, config: LineSplitConfig) -> Examination | None:
    """Recover one paragraph's lines and read the bounds over them.

    None where there is nothing to decide: a paragraph of one line, or of too
    few characters to hold two. Otherwise an examination whose reason is the
    bound that exempted the paragraph, or None where both bounds held and it
    may be cut.
    """
    characters = paragraph_characters(paragraph)
    if len(characters) < 2:
        return None
    lines = recover_lines(characters, config)
    if len(lines) < 2:
        return None
    mean = mean_line_chars(characters, lines)
    heterogeneous = style_heterogeneous(characters, lines)
    reason = None
    if mean > config.max_line_chars:
        reason = REASON_LONG_LINES
    elif config.require_style_heterogeneity and not heterogeneous:
        reason = REASON_UNIFORM_STYLING
    return Examination(
        lines=lines,
        mean_line_chars=round(mean, 1),
        heterogeneous=heterogeneous,
        reason=reason,
    )


def _is_prose_exempt(
    paragraph,
    examination: Examination | None,
    config: LineSplitConfig,
) -> bool:
    """Distinguish long prose from a short uniform multiline record.

    Mean line length already identifies prose set in long lines.  Uniform
    styling is deliberately also an exemption from splitting, but is not by
    itself prose: a short multiline TOC block is commonly uniform.  Within
    that exempt class, reuse the configured line-length bound as a conservative
    total-content bound, require more than the minimum two-line block shape,
    and require the recovered glyph rows to have horizontal rather than
    vertical flow.  This admits long CJK prose whose many short visual lines
    keep its mean below the line bound, without folding either a dense two-line
    TOC subtitle or narrow vertical furniture into prose.
    """
    if examination is None:
        return False
    if examination.reason == REASON_LONG_LINES:
        return True
    if examination.reason != REASON_UNIFORM_STYLING:
        return False
    visible_characters = sum(
        1
        for character in characters_text(paragraph_characters(paragraph))
        if not character.isspace()
    )
    characters = paragraph_characters(paragraph)
    horizontal_extent = 0.0
    vertical_extent = 0.0
    for line in examination.lines:
        box = _box_record(
            character_union([characters[index] for index in line])
        )
        if box is None:
            continue
        horizontal_extent += box[2] - box[0]
        vertical_extent += box[3] - box[1]
    return (
        len(examination.lines) > 2
        and visible_characters > config.max_line_chars
        and horizontal_extent > vertical_extent
    )


# --- cutting one paragraph into one paragraph per line ------------------------


def _rebuilt(composition, kind: str, characters: list):
    """One composition holding only the characters given, of the same kind."""
    if kind == "pdf_line":
        return il_version_1.PdfParagraphComposition(
            pdf_line=il_version_1.PdfLine(
                box=character_union(characters),
                pdf_character=characters,
                render_order=composition.pdf_line.render_order,
            )
        )
    return il_version_1.PdfParagraphComposition(
        pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
            box=character_union(characters),
            pdf_style=composition.pdf_same_style_characters.pdf_style,
            pdf_character=characters,
        )
    )


def _compositions_of_line(paragraph, line: set[int]):
    """The compositions of one paragraph, restricted to one line's characters.

    A splittable composition is cut down to the characters of this line and
    keeps its kind and its style. An atomic one -- a formula above all -- is
    never cut: it goes whole to the line its first character sits on.
    """
    compositions = []
    position = 0
    for composition in paragraph.pdf_paragraph_composition or ():
        kind = composition_kind(composition)
        if kind is None:
            continue
        characters = composition_characters(composition, kind)
        indices = range(position, position + len(characters))
        position += len(characters)
        if kind in ATOMIC:
            if characters and indices[0] in line:
                compositions.append(composition)
            continue
        kept = [
            character
            for offset, character in enumerate(characters)
            if indices[offset] in line
        ]
        if kept:
            compositions.append(_rebuilt(composition, kind, kept))
    return compositions


def record_style(characters):
    """The style most of a record's visible characters are set in.

    A paragraph's base style is what its translation is laid out in, so a
    record given the style of the paragraph it came out of is set in the style
    of whatever that paragraph mostly was. On a contents page mostly bylines,
    that prints every entry title at byline size. Whitespace carries a style and
    no shape and is left out, so a record's setting is decided by what a reader
    can see of it.
    """
    counts: dict[tuple, int] = {}
    holder: dict[tuple, object] = {}
    for character in characters:
        style = character.pdf_style
        if style is None or style.font_id is None or style.font_size is None:
            continue
        if not (character.char_unicode or "").strip():
            continue
        key = (style.font_id, round(float(style.font_size), 4))
        counts[key] = counts.get(key, 0) + 1
        holder.setdefault(key, style)
    if not counts:
        return None
    return holder[max(counts.items(), key=lambda item: item[1])[0]]


def _line_paragraph(paragraph, characters, compositions, ordinal: int):
    """One record of a paragraph, as a paragraph of its own.

    Copied from the paragraph rather than assembled field by field, and that is
    a property rather than a shorthand: every attribute a later stage reads off
    a paragraph -- its label, the chain it belongs to, the sentence range, a
    verdict some other pass wrote on it -- reaches the record without this
    module naming any of them, so a field added to the intermediate language
    later carries by itself and this pass consumes none of them.

    Six are then set, and each is the record's own rather than its parent's.
    The measure is the parent's: a record was set across the column it stood in,
    and a box drawn tight around the source characters would leave the
    translation of a short byline nowhere to grow. The band is the record's own,
    which is what puts each record back where it was. So is the style, because
    inheriting the parent's sets a title at the size of the byline under it.
    """
    band = character_union(characters)
    parent = paragraph.box
    if band is None:
        box = None
    elif parent is None or parent.x is None or parent.x2 is None:
        box = band
    else:
        box = il_version_1.Box(x=parent.x, y=band.y, x2=parent.x2, y2=band.y2)

    line = copy.copy(paragraph)
    line.box = box
    style = record_style(characters)
    if style is not None:
        line.pdf_style = il_version_1.PdfStyle(
            font_id=style.font_id,
            font_size=style.font_size,
            graphic_state=style.graphic_state,
        )
    line.pdf_paragraph_composition = compositions
    line.unicode = characters_text(characters)
    if paragraph.debug_id is not None:
        line.debug_id = f"{paragraph.debug_id}{LINE_ID_SEPARATOR}{ordinal}"
    # Only the first line can have carried the paragraph's opening indent; a
    # record line below it never had one, and re-indenting it would move the
    # record off the measure it was set on.
    if ordinal:
        line.first_line_indent = False
    return line


def split_paragraph(paragraph, config: LineSplitConfig) -> list | None:
    """One paragraph as one paragraph per record, or None where it stays.

    None rather than a single element list, so a caller can tell a paragraph
    this pass left alone from one it rebuilt into the same shape: a paragraph
    of one line, one whose records come back as one record, or one the bounds
    exempt, is returned untouched and its object identity is the record of that.
    """
    examination = examine(paragraph, config)
    if examination is None or not examination.admitted:
        return None
    characters = paragraph_characters(paragraph)
    built = []
    for ordinal, group in enumerate(
        record_groups(characters, examination.lines, config)
    ):
        indices = sorted(index for line in group for index in line)
        members = set(indices)
        compositions = _compositions_of_line(paragraph, members)
        if not compositions:
            continue
        built.append(
            _line_paragraph(
                paragraph,
                [characters[index] for index in indices],
                compositions,
                ordinal,
            )
        )
    return built if len(built) > 1 else None


# --- one page, one document ----------------------------------------------------


def same_style(left, right) -> bool:
    """Whether two styles set text the same way, either being absent."""
    if left is None or right is None:
        return left is right
    return (
        left.font_id == right.font_id
        and left.font_size == right.font_size
        and left.graphic_state == right.graphic_state
    )


def paragraph_reference(page_label: int, index: int) -> str:
    """How one paragraph of the pre-split page is named in the report."""
    return f"p{page_label}#{index}"


@dataclass(frozen=True)
class _PendingUnit:
    paragraph: object
    parent_refs: tuple[str, ...]
    kind: str
    child_order: int
    mergeable: bool
    fixed_companion: bool


_FOLIO_TEXT = re.compile(r"[\d\s.·|/\-–—]+\Z")
_FOLIO_EDGE = re.compile(r"(?:^\d+|\d+$)")


def _is_fixed_folio(paragraph) -> bool:
    text = (
        paragraph.unicode or characters_text(paragraph_characters(paragraph))
    ).strip()
    return bool(text) and _FOLIO_TEXT.fullmatch(text) is not None


def _has_folio_edge(paragraph) -> bool:
    """Whether a record advertises its own folio at either text edge."""
    text = (
        paragraph.unicode or characters_text(paragraph_characters(paragraph))
    ).strip()
    return bool(text) and _FOLIO_EDGE.search(text) is not None


def _tight_uniform_neighbors(upper, lower, config: LineSplitConfig) -> bool:
    """Whether two source paragraphs are one tightly set visual block."""
    if _has_folio_edge(lower):
        # A lower record carrying its own folio is a new TOC item even where
        # the printer uses the same leading as a title/subtitle pair.
        return False
    if not (
        _has_folio_edge(upper)
        or has_multiple_source_rows(paragraph_characters(upper))
        or has_multiple_source_rows(paragraph_characters(lower))
    ):
        # Geometry alone cannot distinguish two tightly led independent
        # singles.  Merge only with positive record-continuation evidence.
        return False
    upper_box = _box_record(upper.box)
    lower_box = _box_record(lower.box)
    if upper_box is None or lower_box is None:
        return False
    upper_height = upper_box[3] - upper_box[1]
    lower_height = lower_box[3] - lower_box[1]
    narrower = min(upper_box[2] - upper_box[0], lower_box[2] - lower_box[0])
    overlap = min(upper_box[2], lower_box[2]) - max(upper_box[0], lower_box[0])
    if min(upper_height, lower_height, narrower) <= 0:
        return False
    gap = upper_box[1] - lower_box[3]
    tolerance = config.scan_step
    return (
        gap >= -tolerance
        and gap <= min(upper_height, lower_height) / config.record_gap_ratio
        and overlap / narrower >= 1.0 / config.record_gap_ratio
    )


def _tight_short_label_value_neighbors(
    upper,
    lower,
    config: LineSplitConfig,
    minimum_text_length: int,
) -> bool:
    """Whether two single rows prove one short-label/value block.

    Mastheads and other record pages commonly set a short field label above a
    longer value.  Keeping those rows as unrelated single-line targets both
    strands the label below the translator's length floor and denies the value
    the vertical source area that visually belongs to the field.  Geometry
    alone is not proof: require the upper row to be below that existing floor,
    distinct typography, close left alignment, and both semantic and visual
    width growth into the lower row.  This leaves ordinary adjacent records
    separate while preserving the complete field as one bounded block.
    """
    if minimum_text_length <= 1 or _has_folio_edge(upper) or _has_folio_edge(lower):
        return False
    if has_multiple_source_rows(
        paragraph_characters(upper)
    ) or has_multiple_source_rows(paragraph_characters(lower)):
        return False
    if same_style(upper.pdf_style, lower.pdf_style):
        return False
    upper_text = characters_text(paragraph_characters(upper)).strip()
    lower_text = characters_text(paragraph_characters(lower)).strip()
    if not (
        0 < len(upper_text) < minimum_text_length <= len(lower_text)
        and len(upper_text) * config.record_gap_ratio <= len(lower_text)
    ):
        return False
    upper_box = _box_record(upper.box)
    lower_box = _box_record(lower.box)
    if upper_box is None or lower_box is None:
        return False
    upper_width = upper_box[2] - upper_box[0]
    lower_width = lower_box[2] - lower_box[0]
    upper_height = upper_box[3] - upper_box[1]
    lower_height = lower_box[3] - lower_box[1]
    if min(upper_width, lower_width, upper_height, lower_height) <= 0:
        return False
    gap = upper_box[1] - lower_box[3]
    return (
        abs(upper_box[0] - lower_box[0]) <= config.scan_step
        and gap >= -config.scan_step
        and gap <= min(upper_height, lower_height)
        and upper_width * config.record_gap_ratio <= lower_width
    )


def _merged_block(paragraphs: list):
    """Build one translation paragraph from a tight source paragraph block."""
    merged = copy.copy(paragraphs[0])
    boxes = [_box_record(paragraph.box) for paragraph in paragraphs]
    if any(box is None for box in boxes):
        raise LineSplitError("a merged visual block has no source box")
    merged.box = il_version_1.Box(
        x=min(box[0] for box in boxes),
        y=min(box[1] for box in boxes),
        x2=max(box[2] for box in boxes),
        y2=max(box[3] for box in boxes),
    )
    merged.pdf_paragraph_composition = [
        composition
        for paragraph in paragraphs
        for composition in paragraph.pdf_paragraph_composition or ()
    ]
    characters = paragraph_characters(merged)
    merged.unicode = "\n".join(
        paragraph.unicode or characters_text(paragraph_characters(paragraph))
        for paragraph in paragraphs
    )
    style = record_style(characters)
    if style is not None:
        merged.pdf_style = il_version_1.PdfStyle(
            font_id=style.font_id,
            font_size=style.font_size,
            graphic_state=style.graphic_state,
        )
    return merged


def _merge_tight_blocks(
    rebuilt,
    pending,
    config: LineSplitConfig,
    minimum_text_length: int,
):
    """Coalesce adjacent untouched single lines into physical block items."""
    by_id = {id(item.paragraph): item for item in pending}

    def split_sibling_group(start: int):
        """Return one already-split parent's complete adjacent child group."""
        first_paragraph = rebuilt[start]
        first = by_id.get(id(first_paragraph))
        if (
            first is None
            or first.mergeable
            or first.fixed_companion
            or first.child_order != 0
        ):
            return None
        paragraphs = []
        held_items = []
        cursor = start
        expected_order = 0
        while cursor < len(rebuilt):
            paragraph = rebuilt[cursor]
            held = by_id.get(id(paragraph))
            if (
                held is None
                or held.mergeable
                or held.fixed_companion
                or held.parent_refs != first.parent_refs
                or held.child_order != expected_order
            ):
                break
            paragraphs.append(paragraph)
            held_items.append(held)
            expected_order += 1
            cursor += 1
        return (
            (paragraphs, held_items, cursor)
            if len(paragraphs) > 1
            else None
        )

    result = []
    result_pending = []
    position = 0
    while position < len(rebuilt):
        paragraph = rebuilt[position]
        held = by_id.get(id(paragraph))
        if held is None or not held.mergeable:
            result.append(paragraph)
            if held is not None:
                result_pending.append(held)
            position += 1
            continue
        members = [paragraph]
        held_members = [held]
        cursor = position + 1
        while cursor < len(rebuilt):
            next_paragraph = rebuilt[cursor]
            next_held = by_id.get(id(next_paragraph))
            if next_held is None:
                break
            if next_held.mergeable:
                candidates = [next_paragraph]
                candidate_items = [next_held]
                next_cursor = cursor + 1
            else:
                split_group = split_sibling_group(cursor)
                if split_group is None:
                    break
                candidates, candidate_items, next_cursor = split_group
            neighbor = (
                candidates[0]
                if len(candidates) == 1
                else _merged_block(candidates)
            )
            if not (
                _tight_uniform_neighbors(members[-1], neighbor, config)
                or _tight_short_label_value_neighbors(
                    members[-1],
                    neighbor,
                    config,
                    minimum_text_length,
                )
            ):
                break
            members.extend(candidates)
            held_members.extend(candidate_items)
            cursor = next_cursor
        if len(members) == 1:
            result.append(paragraph)
            result_pending.append(held)
            position += 1
            continue
        merged = _merged_block(members)
        result.append(merged)
        result_pending.append(
            _PendingUnit(
                paragraph=merged,
                parent_refs=tuple(
                    dict.fromkeys(
                        reference
                        for item in held_members
                        for reference in item.parent_refs
                    )
                ),
                kind=RECORD_BLOCK,
                child_order=0,
                mergeable=False,
                fixed_companion=False,
            )
        )
        position = cursor
    return result, result_pending


def process_page(
    page,
    label: int,
    config: LineSplitConfig,
    *,
    prose_only: bool = False,
    minimum_text_length: int = 0,
    fixed_artwork: list[dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split a record page, or inventory only its long prose paragraphs.

    One record per split, and one per paragraph the bounds exempted, so the
    page's answer is readable in both directions: what was cut, and what was
    left whole because it was prose rather than records.  ``prose_only`` is
    used outside declared record pages: it leaves the page untouched and
    registers only paragraphs already identified by the same long-line bound
    as prose.  Ordinary body paragraphs therefore do not become TOC units.
    """
    records: list[dict] = []
    exemptions: list[dict] = []
    units: list[dict] = []
    rebuilt: list = []
    pending: list[_PendingUnit] = []
    parents: dict[str, dict] = {}
    parent_texts: dict[str, str] = {}
    parent_character_texts: dict[str, str] = {}
    pre_owner_refs: dict[int, tuple[str, ...]] = {}
    physical_index = 0
    for runtime_index, paragraph in enumerate(page.pdf_paragraph or ()):
        source_characters = paragraph_characters(paragraph)
        if not source_characters and is_debug_overlay(paragraph):
            # Debug overlays are explicitly marked on their Unicode-only
            # composition and have no source glyph container to preserve.
            rebuilt.append(paragraph)
            continue
        parent_ref = paragraph_reference(label, physical_index)
        runtime_parent_ref = paragraph_reference(label, runtime_index)
        physical_index += 1
        pre_owner_refs[id(paragraph)] = (parent_ref,)
        if not source_characters:
            # Other generated furniture can likewise have no source glyph
            # geometry. It is not a bounded TOC source unit either.
            rebuilt.append(paragraph)
            continue
        artwork = embedded_figure_artwork(page, paragraph)
        if artwork is not None:
            source_character_text = characters_text(source_characters)
            if fixed_artwork is not None:
                fixed_artwork.append(
                    {
                        "source_ref": parent_ref,
                        "runtime_source_ref": runtime_parent_ref,
                        "debug_id": paragraph.debug_id,
                        "source_box": _box_record(paragraph.box),
                        "source_text_sha256": _source_hash(
                            paragraph.unicode or source_character_text
                        ),
                        **artwork,
                    }
                )
            # The original character objects remain the rendering authority.
            # Removing only semantic input makes all translation producers
            # decline this fixed artwork without changing its paint geometry.
            paragraph.unicode = None
            rebuilt.append(paragraph)
            continue
        source_character_text = characters_text(source_characters)
        parent_text = paragraph.unicode or source_character_text
        examination = examine(paragraph, config)
        prose_exempt = _is_prose_exempt(paragraph, examination, config)
        if prose_only and not prose_exempt:
            rebuilt.append(paragraph)
            continue
        parent_record = {
            "source_ref": parent_ref,
            "runtime_source_ref": runtime_parent_ref,
            "debug_id": paragraph.debug_id,
            "source_box": _box_record(paragraph.box),
            "source_text_sha256": _source_hash(parent_text),
            "source_characters": len(source_character_text),
            "source_characters_sha256": _source_hash(source_character_text),
        }
        parents[parent_ref] = parent_record
        parent_texts[parent_ref] = parent_text
        parent_character_texts[parent_ref] = source_character_text
        lines = None if prose_only else split_paragraph(paragraph, config)
        if lines is None:
            rebuilt.append(paragraph)
            kind = (
                RECORD_PROSE
                if prose_exempt
                else (
                    RECORD_BLOCK
                    if (
                        examination is not None
                        and len(examination.lines) > 1
                    )
                    or (
                        examination is None
                        and has_multiple_source_rows(source_characters)
                    )
                    else RECORD_SINGLE
                )
            )
            pending.append(
                _PendingUnit(
                    paragraph=paragraph,
                    parent_refs=(parent_ref,),
                    kind=kind,
                    child_order=0,
                    mergeable=(
                        kind in {RECORD_SINGLE, RECORD_BLOCK}
                        and not _is_fixed_folio(paragraph)
                    ),
                    fixed_companion=_is_fixed_folio(paragraph),
                )
            )
            if examination is not None and not examination.admitted:
                exemptions.append(
                    {
                        "page": label,
                        "paragraph": parent_ref,
                        "debug_id": paragraph.debug_id,
                        "lines": len(examination.lines),
                        "mean_line_chars": examination.mean_line_chars,
                        "heterogeneous": examination.heterogeneous,
                        "reason": examination.reason,
                    }
                )
            continue
        rebuilt.extend(lines)
        characters = paragraph_characters(paragraph)
        groups = record_groups(characters, examination.lines, config)
        if characters_text(characters) != "".join(
            characters_text(paragraph_characters(child)) for child in lines
        ):
            raise LineSplitError(
                f"{parent_ref}: split changed source character order or count"
            )
        for ordinal, (child, group) in enumerate(zip(lines, groups, strict=True)):
            kind = RECORD_SINGLE if len(group) == 1 else RECORD_BLOCK
            pending.append(
                _PendingUnit(
                    paragraph=child,
                    parent_refs=(parent_ref,),
                    kind=kind,
                    child_order=ordinal,
                    mergeable=False,
                    fixed_companion=False,
                )
            )
        parent = paragraph.pdf_style
        records.append(
            {
                "page": label,
                "paragraph": parent_ref,
                "debug_id": paragraph.debug_id,
                "characters": len(characters),
                "lines": len(examination.lines),
                "mean_line_chars": examination.mean_line_chars,
                "records": len(groups),
                "record_lines": [len(group) for group in groups],
                "restyled_records": sum(
                    1 for line in lines if not same_style(line.pdf_style, parent)
                ),
                "line_paragraphs": [line.debug_id for line in lines],
            }
        )
    rebuilt, pending = _merge_tight_blocks(
        rebuilt,
        pending,
        config,
        minimum_text_length,
    )
    page.pdf_paragraph = rebuilt

    pending_by_id = {
        id(item.paragraph): item
        for item in pending
    }
    children_by_parent: dict[tuple[str, ...], list[dict]] = {}
    group_parents: dict[tuple[str, ...], dict] = {}
    for post_index, paragraph in enumerate(page.pdf_paragraph or ()):
        held = pending_by_id.get(id(paragraph))
        if held is None:
            owner_refs = pre_owner_refs.get(id(paragraph))
            if owner_refs is not None:
                _register_ruling_owner(paragraph, label, owner_refs)
            continue
        parent_refs = held.parent_refs
        _register_ruling_owner(paragraph, label, parent_refs)
        parent_ref = parent_refs[0]
        kind = held.kind
        order = held.child_order
        source_ref = paragraph_reference(label, post_index)
        runtime_parent_refs = tuple(
            parents[reference]["runtime_source_ref"] for reference in parent_refs
        )
        runtime_parent_ref = runtime_parent_refs[0]
        text = paragraph.unicode or characters_text(paragraph_characters(paragraph))
        source_character_text = characters_text(paragraph_characters(paragraph))
        box = _box_record(paragraph.box)
        parent_boxes = [parents[reference]["source_box"] for reference in parent_refs]
        if any(parent_box is None for parent_box in parent_boxes):
            group_box = None
        else:
            group_box = [
                min(parent_box[0] for parent_box in parent_boxes),
                min(parent_box[1] for parent_box in parent_boxes),
                max(parent_box[2] for parent_box in parent_boxes),
                max(parent_box[3] for parent_box in parent_boxes),
            ]
        group_character_text = "".join(
            parent_character_texts[reference] for reference in parent_refs
        )
        group_text = "\n".join(
            parent_texts[reference] for reference in parent_refs
        )
        group_parents.setdefault(
            parent_refs,
            {
                "source_ref": parent_ref,
                "source_refs": list(parent_refs),
                "runtime_source_ref": runtime_parent_ref,
                "runtime_source_refs": list(runtime_parent_refs),
                "debug_id": parents[parent_ref]["debug_id"],
                "source_box": group_box,
                "source_text_sha256": _source_hash(group_text),
                "source_characters": len(group_character_text),
                "source_characters_sha256": _source_hash(group_character_text),
            },
        )
        unit = SourceUnit(
            parent_ref=parent_ref,
            runtime_parent_ref=runtime_parent_ref,
            parent_refs=parent_refs,
            runtime_parent_refs=runtime_parent_refs,
            source_ref=source_ref,
            record_kind=kind,
            child_order=order,
            source_box=None if box is None else tuple(box),
            source_text_sha256=_source_hash(text),
            source_text=text,
            source_characters_sha256=_source_hash(source_character_text),
            source_characters_text=source_character_text,
            fixed_companion=held.fixed_companion,
        )
        _register_source_unit(paragraph, label, unit)
        child = {
            "source_ref": source_ref,
            "runtime_source_ref": source_ref,
            "debug_id": paragraph.debug_id,
            "record_kind": kind,
            "fixed_companion": held.fixed_companion,
            "child_order": order,
            "source_band": box,
            "source_text_sha256": unit.source_text_sha256,
            "source_characters": len(source_character_text),
            "source_characters_sha256": unit.source_characters_sha256,
        }
        children_by_parent.setdefault(parent_refs, []).append(child)
        units.append(
            {
                "parent_ref": parent_ref,
                "parent_refs": list(parent_refs),
                "runtime_parent_ref": runtime_parent_ref,
                "runtime_parent_refs": list(runtime_parent_refs),
                **child,
            }
        )
        if held.fixed_companion:
            # Keep the original glyph compositions as fixed page furniture,
            # while making every translation producer's shared semantic-input
            # precondition reject this standalone folio.
            paragraph.unicode = None

    for unit in units:
        parent_refs = tuple(unit["parent_refs"])
        ordered = sorted(
            children_by_parent[parent_refs],
            key=lambda child: child["child_order"],
        )
        ordered_character_text = "".join(
            source_unit(paragraph, label).source_characters_text
            for paragraph in page.pdf_paragraph or ()
            if source_unit(paragraph, label) is not None
            and source_unit(paragraph, label).parent_refs == parent_refs
        )
        group_parents[parent_refs]["ordered_children_characters_sha256"] = (
            _source_hash(ordered_character_text)
        )
        unit["parent"] = group_parents[parent_refs]
        unit["source_parents"] = [parents[reference] for reference in parent_refs]
        unit["ordered_children"] = ordered
    return records, exemptions, units


def page_lines(page, config: LineSplitConfig) -> int:
    """How many source lines one page's paragraphs hold between them.

    The conserved quantity of this pass: cutting a paragraph into its lines
    does not change how many lines the page has, so this is the same number
    before and after.
    """
    return sum(
        max(1, len(recover_lines(paragraph_characters(paragraph), config)))
        for paragraph in page.pdf_paragraph or ()
        if paragraph_characters(paragraph)
    )


def short_lines(page, label: int, minimum: int) -> list[dict]:
    """The line paragraphs the translator's length floor will not translate.

    Reported rather than worked around. The floor is a translation
    configuration and this pass does not move it; what a page owes the reader is
    an inventory of the lines that will come out in the source language.
    """
    found = []
    for index, paragraph in enumerate(page.pdf_paragraph or ()):
        text = paragraph.unicode or ""
        if LINE_ID_SEPARATOR not in (paragraph.debug_id or ""):
            continue
        if len(text) >= minimum:
            continue
        found.append(
            {
                "page": label,
                "paragraph": paragraph_reference(label, index),
                "debug_id": paragraph.debug_id,
                "text": text,
            }
        )
    return found


def as_record(
    config: LineSplitConfig,
    splits: list[dict],
    exemptions: list[dict],
    source_units: list[dict],
    pages: list[dict],
    untranslated: list[dict],
    fixed_artwork: list[dict],
    minimum: int,
) -> dict:
    return {
        "switch": SWITCH,
        "window_switch": WINDOW_SWITCH,
        "policy_flags": list(config.policy_flags),
        "min_line_characters": config.min_line_characters,
        "max_line_chars": config.max_line_chars,
        "require_style_heterogeneity": config.require_style_heterogeneity,
        "minimum_readable_scale": config.minimum_readable_scale,
        "min_text_length": minimum,
        "totals": {
            "declared_pages": sum(1 for page in pages if page["declared"]),
            "pages": len(pages),
            "split_paragraphs": len(splits),
            "line_paragraphs": sum(item["lines"] for item in splits),
            "exempt_paragraphs": len(exemptions),
            "short_lines": len(untranslated),
            "fixed_artwork": len(fixed_artwork),
        },
        "pages": pages,
        "splits": splits,
        "exemptions": exemptions,
        "source_units": source_units,
        "short_lines": untranslated,
        "fixed_artwork": fixed_artwork,
    }


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def apply(translation_config, labeled_pages, policy_of=None) -> dict | None:
    """Split every declared page of one document. None where the switch is down.

    Returns the record it wrote, so a caller holding the document can assert
    about the pass without reading the sidecar back.
    """
    if not enabled(translation_config):
        return None
    config = load_line_split_config()
    _SOURCE_UNITS_BY_ID.clear()
    _SOURCE_UNITS_BY_DEBUG.clear()
    _RULING_OWNERS_BY_ID.clear()
    _RULING_OWNERS_BY_DEBUG.clear()
    resolve = policy_of if policy_of is not None else load_taxonomy().policy_of
    minimum = int(getattr(translation_config, "min_text_length", 0) or 0)

    splits: list[dict] = []
    exempt: list[dict] = []
    source_units: list[dict] = []
    pages: list[dict] = []
    untranslated: list[dict] = []
    fixed_artwork: list[dict] = []
    for label, page in labeled_pages:
        declared = config.declared(resolve(page.page_kind))
        source_characters = "".join(
            characters_text(paragraph_characters(paragraph))
            for paragraph in page.pdf_paragraph or ()
        )
        before = page_lines(page, config)
        records, exemptions, units = process_page(
            page,
            label,
            config,
            prose_only=not declared,
            minimum_text_length=minimum,
            fixed_artwork=fixed_artwork,
        )
        after = page_lines(page, config)
        result_characters = "".join(
            characters_text(paragraph_characters(paragraph))
            for paragraph in page.pdf_paragraph or ()
        )
        if source_characters != result_characters:
            raise LineSplitError(
                f"p{label}: line split changed source character order or count"
            )
        splits.extend(records)
        exempt.extend(exemptions)
        source_units.extend(units)
        untranslated.extend(short_lines(page, label, minimum) if declared else [])
        pages.append(
            {
                "page": label,
                "declared": declared,
                "paragraphs": len(page.pdf_paragraph or ()),
                "lines_before": before,
                "lines_after": after,
                "characters_before": len(source_characters),
                "characters_after": len(result_characters),
                "source_characters_sha256": _source_hash(source_characters),
                "result_characters_sha256": _source_hash(result_characters),
                "split_paragraphs": len(records),
                "exempt_paragraphs": len(exemptions),
            }
        )

    for items, declared_shape, what in (
        (splits, config.sidecar_fields, "split"),
        (exempt, config.exemption_fields, "exemption"),
    ):
        expected = set(declared_shape)
        for item in items:
            if set(item) != expected:
                raise LineSplitError(
                    f"{REPORT_NAME}: a {what} record carries {sorted(item)}, "
                    f"and {CONFIG_PATH.name} declares {sorted(expected)}"
                )
    for item in exempt:
        if item["reason"] not in config.exemption_reasons:
            raise LineSplitError(
                f"{REPORT_NAME}: an exemption names {item['reason']!r}, "
                f"and {CONFIG_PATH.name} declares {sorted(config.exemption_reasons)}"
            )

    refs = [item["source_ref"] for item in source_units]
    if len(refs) != len(set(refs)):
        raise LineSplitError(f"{REPORT_NAME}: post-split source refs are not unique")
    record = as_record(
        config,
        splits,
        exempt,
        source_units,
        pages,
        untranslated,
        fixed_artwork,
        minimum,
    )
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    write_report(working_dir, record)
    logger.debug(
        "line split: %d declared page(s), %d paragraph(s) cut into %d line(s), "
        "%d left whole",
        record["totals"]["declared_pages"],
        record["totals"]["split_paragraphs"],
        record["totals"]["line_paragraphs"],
        record["totals"]["exempt_paragraphs"],
    )
    return record
