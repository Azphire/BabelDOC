"""Characters the formula grouper swallowed, given back to the translator.

The style and formula stage groups a run of characters as a formula when the
run does not look like prose to it, and a formula is not offered to the
translator: it is carried through and set again as it stood. That is right for
a formula. It is wrong for a strip of rotated type, a folio line and a credit
line, which arrive as formulas because they carry no paragraph style and their
characters are grouped without one -- and it is wrong in a way that no amount
of care in the translator can fix, because the translator never sees them.

Whether it matters depends on the direction of the run. Into Chinese, a Latin
run standing untranslated on the page may be a brand, a URL or a name, and
handing every one of them to the translator would change text that was meant to
stand as it is. Into English there is no such case: a Chinese character in a
document finished into English is untranslated source, whatever grouping it
arrived under. So this pass is directional, and the direction it acts in is
declared rather than assumed.

What it does is the smallest thing that works. A composition whose characters
include the residue script is rewritten as a line -- the same rewrite the
upstream stage already performs on the formulas it judges translatable, into
the same type, by the same helper -- and the paragraph then reaches the
translator as ordinary text. No character is added, removed or moved.

What it must never do
---------------------

Convert a composition carrying vector artwork. ``PdfFormula`` holds
``pdf_form`` and ``pdf_curve``; ``PdfLine`` holds neither, and the writer's
only route to those two runs through the formula holder. A composition
converted with artwork on it loses the artwork silently -- no error, no warning,
an image simply missing from the page. That is refused unconditionally, and the
count of compositions refused for it is reported so that "none carried artwork"
is a measurement each run makes rather than a claim inherited from the run
before.

What the conversion drops, and why each is answerable
-----------------------------------------------------

``is_corner_mark`` is read only inside the stage that sets it, which has
finished by the time this runs. ``line_id`` is likewise read only there, by the
merge and split passes of that same stage. ``x_offset`` and ``y_offset`` shift a
formula against the baseline it sits on and are reported per composition, so a
run converting one that carries a shift can be seen to have done so.
``x_advance`` is padding the typesetter adds after a formula; a line takes the
advance of its own characters instead, which is what it is being set as.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il.il_version_1 import Box
from babeldoc.format.pdf.document_il.il_version_1 import PdfLine
from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
from babeldoc.format.pdf.document_il.il_version_1 import PdfSameStyleUnicodeCharacters
from babeldoc.format.pdf.document_il.il_version_1 import PdfStyle
from babeldoc.magazine import fragment_stitch
from babeldoc.magazine import paren_dedup
from babeldoc.magazine import reading_order
from babeldoc.magazine.detectors import base as detector_base
from babeldoc.magazine.detectors import detector_config
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.resource_paths import config_path

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("formula_reclass.json")

DIRECTIONS_KEY = "directions"

REPORT_NAME = "formula_reclass.report.json"

# The switch, by the name the caller sets on the translation config. Down unless
# something puts it up: this changes which text a run pays to translate.
SWITCH = "magazine_formula_reclass"

# Why one CJK bearing composition was left as a formula.
REFUSED_ARTWORK = "carries_vector_artwork"

# What a paragraph this pass converted looked like before it did, kept so that
# a conversion the typesetting stage cannot lay out can be undone rather than
# left to be dropped. Keyed by page and in-page position, which is what the
# stage preserves; cleared at the start of every run.
_ORIGINALS: dict[str, dict] = {}


class FormulaReclassError(ConfigError):
    """Raised when the reclassification configuration is malformed."""


@lru_cache(maxsize=1)
def load_directions(path: str | None = None) -> tuple[str, ...]:
    """The target languages this pass acts in, as declared."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise FormulaReclassError(f"{config_path.name}: root must be an object")
    declared = raw.get(DIRECTIONS_KEY)
    if not isinstance(declared, list) or not all(
        isinstance(item, str) and item.strip() for item in declared
    ):
        raise FormulaReclassError(
            f"{config_path.name}: {DIRECTIONS_KEY} must be a list of language tags"
        )
    return tuple(item.strip().lower() for item in declared)


def acts_in(language: str | None, directions: tuple[str, ...] | None = None) -> bool:
    """Whether this pass acts on a run finishing into this language.

    Matched by declared prefix, as every other per language rule in this project
    is, so a tag carrying a region is claimed by the rule for its language.
    """
    tag = (language or "").strip().lower()
    declared = load_directions() if directions is None else directions
    return any(tag.startswith(item) for item in declared)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def _composition_text(formula) -> str:
    return "".join(
        character.char_unicode or "" for character in (formula.pdf_character or ())
    )


def _artwork_counts(formula) -> tuple[int, int]:
    return len(formula.pdf_form or ()), len(formula.pdf_curve or ())


def residue_script(language: str | None):
    """The script that is residue in this direction, or None where none is."""
    rule = detector_config().residue_rule(language)
    return None if rule is None else rule[0]


def holds_residue(text: str, script: str) -> bool:
    return detector_base.script_counts(text).get(script, 0) > 0


def apply(translation_config, docs) -> dict | None:
    """Rewrite the residue bearing formulas of every page as lines.

    Returns the record it wrote, so a caller holding the document can assert
    about the pass without reading the sidecar back. None where the switch is
    down or the direction declares no residue script.
    """
    if not enabled(translation_config):
        return None
    _ORIGINALS.clear()
    _PENDING.clear()
    language = getattr(translation_config, "lang_out", "") or ""
    script = residue_script(language) if acts_in(language) else None
    rows: list[dict] = []
    refused: list[dict] = []
    converted = 0
    examined = 0
    if script is not None:
        for index, page in enumerate(docs.page or ()):
            label = (
                page.page_number if page.page_number is not None else index
            ) + 1
            for position, paragraph in enumerate(page.pdf_paragraph or ()):
                reference = f"p{label}#{position}"
                rebuilt = []
                touched = 0
                for composition in paragraph.pdf_paragraph_composition or ():
                    formula = composition.pdf_formula
                    if formula is None:
                        rebuilt.append(composition)
                        continue
                    examined += 1
                    text = _composition_text(formula)
                    if not holds_residue(text, script):
                        rebuilt.append(composition)
                        continue
                    forms, curves = _artwork_counts(formula)
                    if forms or curves:
                        refused.append(
                            {
                                "reference": reference,
                                "reason": REFUSED_ARTWORK,
                                "forms": forms,
                                "curves": curves,
                                "text": text[:40],
                            }
                        )
                        rebuilt.append(composition)
                        continue
                    line = PdfLine(pdf_character=list(formula.pdf_character or ()))
                    line.box = formula.box
                    rebuilt.append(PdfParagraphComposition(pdf_line=line))
                    converted += 1
                    touched += 1
                    rows.append(
                        {
                            "reference": reference,
                            "layout_label": paragraph.layout_label,
                            "vertical": bool(getattr(paragraph, "vertical", None)),
                            "is_corner_mark": bool(formula.is_corner_mark),
                            "x_offset": float(formula.x_offset or 0.0),
                            "y_offset": float(formula.y_offset or 0.0),
                            "characters": len(formula.pdf_character or ()),
                            "text": text[:40],
                        }
                    )
                if touched:
                    # A paragraph made entirely of formulas carries no paragraph
                    # style, because the style pass computes one from the runs
                    # that are not formulas and there were none. The typesetting
                    # stage needs one to set text with: without it the stage
                    # reports "Style is None", lays nothing out, and the writer
                    # then declines to export a paragraph with no composition --
                    # so the line does not merely stay untranslated, it leaves
                    # the page. The style is taken from the characters the
                    # paragraph already holds, by the same majority the stitch
                    # pass takes one by.
                    if paragraph.pdf_style is None:
                        majority = fragment_stitch._majority_style(
                            reading_order.paragraph_characters(paragraph)
                        )
                        if majority is not None:
                            paragraph.pdf_style = PdfStyle(
                                font_id=majority.font_id,
                                font_size=majority.font_size,
                                graphic_state=majority.graphic_state,
                            )
                    _ORIGINALS[reference] = {
                        "compositions": list(
                            paragraph.pdf_paragraph_composition or ()
                        ),
                        "unicode": paragraph.unicode,
                    }
                    # Stored in reading order, not in the order the compositions
                    # arrived in. A strip of rotated type is stored top of page
                    # first and read bottom of page first, and the paragraph is
                    # about to be sent to a model: a question asked in stored
                    # order is a question with its characters shuffled, and the
                    # answer to it is not an answer to anything. Reordering the
                    # compositions rather than only the text is what makes every
                    # later reader -- the translator, the writer, the detector --
                    # agree without each of them having to sort again.
                    rebuilt = _in_reading_order(rebuilt)
                    paragraph.pdf_paragraph_composition = rebuilt
                    paragraph.unicode = "".join(
                        reading_order._unit(item)[0] for item in rebuilt
                    )
    stitched = stitch_rotated(docs, {row["reference"] for row in rows}, _ORIGINALS)
    # PLAN_B11_7_REV2 withdrew this rule's independent standing and kept it as
    # the fallback to reach for where the gate cannot be met without it, on the
    # ground that the engine route already returns the parenthetical original.
    # The run that tested that ground found otherwise: with the fold off, the
    # stitched p3 credit is never offered to any engine at all. Its residue
    # share is 8 characters of 24, under the detector's own share floor into
    # English, so it is not reported; and the translator refuses it before
    # reading it for being set along the vertical axis. Nothing downstream ever
    # sees it, and the page keeps eight characters of the source. So the
    # fallback the revision provided for is the case that obtains, and the fold
    # runs.
    folded = fold_annotations(docs, set(_ORIGINALS), language)
    record = {
        "switch": SWITCH,
        "target_lang": language,
        "residue_script": script,
        "stitched_rotated": stitched,
        "stitched_count": len(stitched),
        "folded_annotations": folded,
        "folded_count": len(folded),
        "formula_compositions_examined": examined,
        "converted": converted,
        "refused": refused,
        "refused_for_artwork": sum(
            1 for row in refused if row["reason"] == REFUSED_ARTWORK
        ),
        "paragraphs_touched": len({row["reference"] for row in rows}),
        "compositions": rows,
    }
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    logger.debug(
        "formula reclass: %d of %d composition(s) rewritten as lines, %d refused",
        converted,
        examined,
        len(refused),
    )
    return record


def _box_of(paragraph):
    box = paragraph.box
    if box is None:
        return None
    values = (box.x, box.y, box.x2, box.y2)
    if any(value is None for value in values):
        return None
    return tuple(float(value) for value in values)


def _overlap(low_a, high_a, low_b, high_b) -> float:
    return max(0.0, min(high_a, high_b) - max(low_a, low_b))


def _gap(low_a, high_a, low_b, high_b) -> float:
    return max(low_b - high_a, low_a - high_b, 0.0)


def _font_size(paragraph) -> float | None:
    sizes = [
        float(character.pdf_style.font_size)
        for character in reading_order.paragraph_characters(paragraph)
        if character.pdf_style and character.pdf_style.font_size
    ]
    if not sizes:
        return None
    sizes.sort()
    return sizes[len(sizes) // 2]


def _joins_along_the_axis(upper, lower, size: float, config) -> bool:
    """The stitch pass's side-by-side rule, read in the transposed frame.

    That rule asks two things of two pieces standing on one line: that they
    share most of the line's own thickness, and that the space between them
    along the line is no wider than a declared share of the type size. On a
    horizontal line the thickness is measured across y and the space along x.
    On a strip of rotated type the two axes exchange, and the same rule with the
    same two declared numbers asks the same question -- which is why no
    threshold is introduced here: the numbers are the stitch pass's own.
    """
    shared = _overlap(upper[0], upper[2], lower[0], lower[2])
    narrower = min(upper[2] - upper[0], lower[2] - lower[0])
    if narrower <= 0 or shared / narrower < config.min_x_overlap_ratio:
        return False
    gap = _gap(upper[1], upper[3], lower[1], lower[3])
    return gap <= config.max_inline_gap_ratio * size


def stitch_rotated(docs, converted: set[str], originals: dict) -> list[dict]:
    """Put the pieces of one rotated strip back into one paragraph.

    A credit line printed up the side of a photograph reaches the intermediate
    language as two paragraphs about as often as one, cut in the middle of a
    name. Each piece is a request of its own, so the model is asked to translate
    half a name twice and answers twice -- and no bound on how short a piece may
    be can tell a half name from a short line. The repair is to stop making two
    requests, not to lower the bound until both halves are accepted.

    Only paragraphs this pass has just converted, and only ones set along the
    vertical axis. The order is the reading order of that axis -- up the page --
    and not the order the paragraphs are stored in, which for these two runs
    the other way.
    """
    config = fragment_stitch.load_stitch_config()
    records: list[dict] = []
    for index, page in enumerate(docs.page or ()):
        label = (page.page_number if page.page_number is not None else index) + 1
        paragraphs = list(page.pdf_paragraph or ())
        pieces = []
        for position, paragraph in enumerate(paragraphs):
            reference = f"p{label}#{position}"
            if reference not in converted:
                continue
            if not getattr(paragraph, "vertical", False):
                continue
            box = _box_of(paragraph)
            size = _font_size(paragraph)
            if box is None or size is None:
                continue
            pieces.append((box[1], position, paragraph, box, size))
        if len(pieces) < 2:
            continue
        pieces.sort(key=lambda item: item[0])
        run = [pieces[0]]
        runs = [run]
        for piece in pieces[1:]:
            previous = run[-1]
            if _joins_along_the_axis(previous[3], piece[3], previous[4], config):
                run.append(piece)
            else:
                run = [piece]
                runs.append(run)
        for members in runs:
            if len(members) < 2:
                continue
            first = members[0][2]
            characters = [
                character
                for _y, _position, paragraph, _box, _size in members
                for character in reading_order.paragraph_characters(paragraph)
            ]
            text = "".join(
                reading_order.paragraph_reading_text(paragraph)
                for _y, _position, paragraph, _box, _size in members
            )
            first.pdf_paragraph_composition = [
                PdfParagraphComposition(
                    pdf_line=PdfLine(pdf_character=characters)
                )
            ]
            # Joined without inferring a space from the gaps, which is how the
            # ordinary stitch recovers the spaces a PDF does not encode. That
            # inference reads the gap along x, and along x a rotated strip does
            # not advance at all: every character sits at the same offset and
            # the inference would put a space between every pair of them.
            first.unicode = text
            box = (
                min(item[3][0] for item in members),
                min(item[3][1] for item in members),
                max(item[3][2] for item in members),
                max(item[3][3] for item in members),
            )
            first.box = Box(x=box[0], y=box[1], x2=box[2], y2=box[3])
            # A member merged away holds nothing on purpose, so it must stop
            # being a paragraph the restore below is watching: an empty
            # composition is how the stage reports that it could not lay a
            # paragraph out, and one blanked deliberately would be read as that
            # and filled back in -- putting the text on the page twice. The
            # surviving member inherits what the whole run held, so a restore of
            # it puts back the whole strip rather than its first piece.
            merged_original = {
                "compositions": [
                    composition
                    for _y, _position, paragraph, _box, _size in members
                    for composition in (
                        originals.get(f"p{label}#{_position}", {}).get(
                            "compositions", []
                        )
                    )
                ],
                "unicode": "".join(
                    originals.get(f"p{label}#{_position}", {}).get("unicode", "")
                    for _y, _position, paragraph, _box, _size in members
                ),
            }
            for _y, position_of, paragraph, _box, _size in members[1:]:
                fragment_stitch._blank(paragraph)
                originals.pop(f"p{label}#{position_of}", None)
            if merged_original["compositions"]:
                originals[f"p{label}#{members[0][1]}"] = merged_original
            records.append(
                {
                    "page": label,
                    "reference": f"p{label}#{members[0][1]}",
                    "merged": [f"p{label}#{item[1]}" for item in members],
                    "characters": len(characters),
                    "text": text[:80],
                }
            )
    return records


# What a paragraph the deterministic fold rewrote is waiting to be set as, so
# the axis lane can set it after the stage has declined to. Keyed as _ORIGINALS
# is, and cleared with it.
_PENDING: dict[str, dict] = {}


def fold_annotations(docs, converted: set[str], language: str) -> list[dict]:
    """Keep the original a residue name is annotated with, and drop the name.

    Deterministic and free. A credit that writes a name in the residue script
    and then repeats it in a parenthetical -- a transliteration followed by
    the original in brackets -- already carries the answer on the page: the
    parenthetical is the name as its owner writes it, and the run in front of it
    is a transliteration of that name into the script this document should not
    be holding. Folding the run away is not a translation and costs no request,
    and it keeps the source's own spelling rather than a model's guess at
    reversing a transliteration.

    Runs before any engine is asked, so what is left for the engine is what the
    page does not already answer.
    """
    config = paren_dedup.load_paren_config()
    script = residue_script(language)
    if script is None:
        return []

    def is_residue(character: str) -> bool:
        return detector_base.script_of(character) == script

    records: list[dict] = []
    for index, page in enumerate(docs.page or ()):
        label = (page.page_number if page.page_number is not None else index) + 1
        for position, paragraph in enumerate(page.pdf_paragraph or ()):
            reference = f"p{label}#{position}"
            if reference not in converted:
                continue
            before = paragraph.unicode or ""
            after, folded = paren_dedup.reverse_annotation(before, config, is_residue)
            if not folded or after == before:
                continue
            # Only where the fold leaves no residue at all. A fold that removes
            # some of it makes the paragraph shorter in the residue script
            # without making it right, and the share the detector measures falls
            # with it -- so a line that was reported and would have been
            # translated whole becomes a line that is neither folded away nor
            # reported. The engine route handles the whole line better than a
            # partial fold handles half of it, so a partial fold is declined.
            if any(is_residue(character) for character in after):
                continue
            holder = PdfParagraphComposition(
                pdf_same_style_unicode_characters=PdfSameStyleUnicodeCharacters(
                    unicode=after, pdf_style=paragraph.pdf_style
                )
            )
            paragraph.pdf_paragraph_composition = [holder]
            paragraph.unicode = after
            if getattr(paragraph, "vertical", False):
                _PENDING[reference] = {"composition": holder, "unicode": after}
            records.append(
                {
                    "reference": reference,
                    "folded": folded,
                    "before": before[:80],
                    "after": after[:80],
                }
            )
    return records


def set_folded_along_axis(translation_config, docs, typesetting) -> list[dict]:
    """Set every rotated paragraph the fold rewrote along its own axis.

    The stage lays out on the horizontal axis, so whatever it produced for a
    rotated strip is wrong: either nothing at all, which the writer then
    declines to export, or a line of type running the wrong way across the page.
    Both are discarded and the strip is set by the lane -- the same lane the
    repair loop's write back uses, for the same reason and by the same route.

    Unconditionally, and that is the point. Acting only where the stage produced
    nothing would leave exactly the strips it *could* fit set along the wrong
    axis, which is the harder failure to see: a paragraph that is missing is
    noticed, and one printed sideways in the margin reads as a layout that was
    always like that.
    """
    if not enabled(translation_config) or not _PENDING:
        return []
    from babeldoc.magazine import rotated_lane

    set_out: list[dict] = []
    for index, page in enumerate(docs.page or ()):
        label = (page.page_number if page.page_number is not None else index) + 1
        for position, paragraph in enumerate(page.pdf_paragraph or ()):
            reference = f"p{label}#{position}"
            pending = _PENDING.get(reference)
            if pending is None:
                continue
            paragraph.pdf_paragraph_composition = [pending["composition"]]
            paragraph.unicode = pending["unicode"]
            laid = rotated_lane.set_along_axis(typesetting, paragraph, page)
            rotated_lane.note_reference(reference)
            if not laid:
                paragraph.pdf_paragraph_composition = []
            set_out.append({"reference": reference, "laid_out": laid})
    return set_out


RESTORE_REPORT_NAME = "formula_reclass_restore.report.json"


def restore_unformatted(translation_config, docs, typesetting=None) -> dict | None:
    """Put back any paragraph the stage could not lay out after conversion.

    Handing a paragraph's characters to the translator makes its text longer,
    and a line whose box was drawn around ten Chinese characters may have no
    room for the forty Latin ones that come back. The stage answers a paragraph
    it cannot fit by leaving its composition empty, and the writer answers an
    empty composition by refusing to export the paragraph at all -- so the line
    does not merely stay untranslated, it disappears from the page.

    Losing the line is worse than not translating it. Where the stage produced
    nothing, the composition and text this pass replaced are put back, and the
    page keeps its source line. The detector then reports it as residue, which
    is true and is the outcome a reader can act on.
    """
    if not enabled(translation_config) or not _ORIGINALS:
        return None
    restored = []
    laid_by_lane = (
        set_folded_along_axis(translation_config, docs, typesetting)
        if typesetting is not None
        else []
    )
    for index, page in enumerate(docs.page or ()):
        label = (page.page_number if page.page_number is not None else index) + 1
        for position, paragraph in enumerate(page.pdf_paragraph or ()):
            reference = f"p{label}#{position}"
            original = _ORIGINALS.get(reference)
            if original is None:
                continue
            if paragraph.pdf_paragraph_composition:
                continue
            paragraph.pdf_paragraph_composition = original["compositions"]
            paragraph.unicode = original["unicode"]
            restored.append(
                {
                    "reference": reference,
                    "layout_label": paragraph.layout_label,
                    "text": (original["unicode"] or "")[:60],
                }
            )
    record = {
        "switch": SWITCH,
        "converted_paragraphs": sorted(_ORIGINALS),
        "set_along_axis": laid_by_lane,
        "restored": restored,
        "restored_count": len(restored),
    }
    path = Path(translation_config.get_working_file_path(RESTORE_REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    if restored:
        logger.warning(
            "formula reclass: %d converted paragraph(s) could not be laid out and "
            "were put back as their source",
            len(restored),
        )
    return record


def _in_reading_order(compositions: list) -> list:
    """The compositions in the order a reader meets them."""
    units = [reading_order._unit(item) for item in compositions]
    return [compositions[position] for position in reading_order.reading_order(units)]
