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
paragraph back into its source lines and gives each line a paragraph of its own.
Downstream, that is all it takes: the translator's unit is the paragraph, so one
line is one request, and the typesetting stage lays each line out inside the
band and measure that line occupied.

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
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "line_split.json"

REPORT_NAME = "line_split.report.json"

# The switch, by the name the caller sets on the translation config.
SWITCH = "magazine_line_structure"

# The switch this pass rides: the window it has to run in is inside the hook
# that stage calls, so a run without the classifier has no settled kind to read.
WINDOW_SWITCH = "magazine_page_classify"

POLICY_FLAGS_KEY = "policy_flags"
SIDECAR_FIELDS_KEY = "sidecar_fields"

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
    policy_flags: tuple[str, ...]
    sidecar_fields: tuple[str, ...]

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

    for key in (POLICY_FLAGS_KEY, SIDECAR_FIELDS_KEY):
        _require(key in parameters, f"{source}: missing {key}")
    flags = tuple(parameters[POLICY_FLAGS_KEY])

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
        policy_flags=flags,
        sidecar_fields=tuple(parameters[SIDECAR_FIELDS_KEY]),
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


def _union(characters):
    """The box covering every character, measured as the stages measure it."""
    boxes = [character_box(item) for item in characters]
    boxes = [
        box
        for box in boxes
        if box is not None
        and None not in (box.x, box.y, box.x2, box.y2)
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
# characters whose grouping this pass is allowed to regroup.
_SPLITTABLE = ("pdf_line", "pdf_same_style_characters")
_ATOMIC = ("pdf_formula", "pdf_character", "pdf_same_style_unicode_characters")


def composition_kind(composition) -> str | None:
    for name in (*_SPLITTABLE, *_ATOMIC):
        if getattr(composition, name, None) is not None:
            return name
    return None


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
        text = "".join(
            (characters[index].char_unicode or "") for index in bucket
        )
        if merged and len(text.strip()) < config.min_line_characters:
            merged[-1].extend(bucket)
            continue
        merged.append(list(bucket))
    return merged


# --- cutting one paragraph into one paragraph per line ------------------------


def _rebuilt(composition, kind: str, characters: list):
    """One composition holding only the characters given, of the same kind."""
    if kind == "pdf_line":
        return il_version_1.PdfParagraphComposition(
            pdf_line=il_version_1.PdfLine(
                box=_union(characters),
                pdf_character=characters,
                render_order=composition.pdf_line.render_order,
            )
        )
    return il_version_1.PdfParagraphComposition(
        pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
            box=_union(characters),
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
        if kind in _ATOMIC:
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


def _line_paragraph(paragraph, characters, compositions, ordinal: int):
    """One line of a paragraph, as a paragraph of its own.

    Copied from the paragraph rather than assembled field by field, and that is
    a property rather than a shorthand: every attribute a later stage reads off
    a paragraph -- its label, the chain it belongs to, the sentence range, a
    verdict some other pass wrote on it -- reaches the line without this module
    naming any of them, so a field added to the intermediate language later
    carries by itself and this pass consumes none of them.

    Five are then set, and each is the paragraph's own rather than its parent's.
    The measure is the parent's: a record was set across the column it stood in,
    and a box drawn tight around the source characters would leave the
    translation of a short byline nowhere to grow. The band is the line's own,
    which is what puts each record back where it was.
    """
    band = _union(characters)
    parent = paragraph.box
    if band is None:
        box = None
    elif parent is None or parent.x is None or parent.x2 is None:
        box = band
    else:
        box = il_version_1.Box(x=parent.x, y=band.y, x2=parent.x2, y2=band.y2)

    line = copy.copy(paragraph)
    line.box = box
    line.pdf_paragraph_composition = compositions
    line.unicode = get_char_unicode_string(characters) if characters else ""
    if paragraph.debug_id is not None:
        line.debug_id = f"{paragraph.debug_id}{LINE_ID_SEPARATOR}{ordinal}"
    # Only the first line can have carried the paragraph's opening indent; a
    # record line below it never had one, and re-indenting it would move the
    # record off the measure it was set on.
    if ordinal:
        line.first_line_indent = False
    return line


def split_paragraph(paragraph, config: LineSplitConfig) -> list | None:
    """One paragraph as one paragraph per source line, or None where it is one.

    None rather than a single element list, so a caller can tell a paragraph
    this pass left alone from one it rebuilt into the same shape: a paragraph
    of one line is returned untouched and its object identity is the record of
    that.
    """
    characters = paragraph_characters(paragraph)
    if len(characters) < 2:
        return None
    lines = recover_lines(characters, config)
    if len(lines) < 2:
        return None
    built = []
    for ordinal, line in enumerate(lines):
        members = set(line)
        compositions = _compositions_of_line(paragraph, members)
        if not compositions:
            continue
        built.append(
            _line_paragraph(
                paragraph,
                [characters[index] for index in line],
                compositions,
                ordinal,
            )
        )
    return built if len(built) > 1 else None


# --- one page, one document ----------------------------------------------------


def paragraph_reference(page_label: int, index: int) -> str:
    """How one paragraph of the pre-split page is named in the report."""
    return f"p{page_label}#{index}"


def process_page(page, label: int, config: LineSplitConfig) -> list[dict]:
    """Split every paragraph of one declared page. One record per split."""
    records: list[dict] = []
    rebuilt: list = []
    for index, paragraph in enumerate(page.pdf_paragraph or ()):
        lines = split_paragraph(paragraph, config)
        if lines is None:
            rebuilt.append(paragraph)
            continue
        rebuilt.extend(lines)
        records.append(
            {
                "page": label,
                "paragraph": paragraph_reference(label, index),
                "debug_id": paragraph.debug_id,
                "characters": len(paragraph_characters(paragraph)),
                "lines": len(lines),
                "line_paragraphs": [line.debug_id for line in lines],
            }
        )
    if records:
        page.pdf_paragraph = rebuilt
    return records


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
    pages: list[dict],
    untranslated: list[dict],
    minimum: int,
) -> dict:
    return {
        "switch": SWITCH,
        "window_switch": WINDOW_SWITCH,
        "policy_flags": list(config.policy_flags),
        "min_line_characters": config.min_line_characters,
        "min_text_length": minimum,
        "totals": {
            "declared_pages": sum(1 for page in pages if page["declared"]),
            "pages": len(pages),
            "split_paragraphs": len(splits),
            "line_paragraphs": sum(item["lines"] for item in splits),
            "short_lines": len(untranslated),
        },
        "pages": pages,
        "splits": splits,
        "short_lines": untranslated,
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
    resolve = policy_of if policy_of is not None else load_taxonomy().policy_of
    minimum = int(getattr(translation_config, "min_text_length", 0) or 0)

    splits: list[dict] = []
    pages: list[dict] = []
    untranslated: list[dict] = []
    for label, page in labeled_pages:
        declared = config.declared(resolve(page.page_kind))
        before = page_lines(page, config)
        records = process_page(page, label, config) if declared else []
        after = page_lines(page, config)
        splits.extend(records)
        untranslated.extend(short_lines(page, label, minimum) if declared else [])
        pages.append(
            {
                "page": label,
                "declared": declared,
                "paragraphs": len(page.pdf_paragraph or ()),
                "lines_before": before,
                "lines_after": after,
                "split_paragraphs": len(records),
            }
        )

    expected = set(config.sidecar_fields)
    for item in splits:
        if set(item) != expected:
            raise LineSplitError(
                f"{REPORT_NAME}: a split record carries {sorted(item)}, "
                f"and {CONFIG_PATH.name} declares {sorted(expected)}"
            )

    record = as_record(config, splits, pages, untranslated, minimum)
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    write_report(working_dir, record)
    logger.debug(
        "line split: %d declared page(s), %d paragraph(s) cut into %d line(s)",
        record["totals"]["declared_pages"],
        record["totals"]["split_paragraphs"],
        record["totals"]["line_paragraphs"],
    )
    return record
