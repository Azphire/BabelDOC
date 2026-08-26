"""Setting a translated line back along the axis its source was set along.

A credit line printed up the side of a photograph is one line of type rotated a
quarter turn. The intermediate language records that as a flag on each
character, and the writer turns the flag into the one rotation it stands for --
``0 1 -1 0``, which advances the pen up the page. Everything between those two
lays out on the horizontal axis and nothing else: the typesetting stage builds
every character it creates unrotated, and its packer measures the box's width
as the length of a line. Handed a rotated strip six points wide, it asks
whether a word fits in six points, finds that none does, and refuses.

That refusal is what stopped the repair loop from writing back a translation it
had already paid for. The answer is not to teach the general packer about axes
-- its every measurement, from the space width to the hanging punctuation
ledger, is written in terms of x as the line and y as the column, and an axis
parameter through all of it is a rewrite of a stage this project does not own.
The answer is that a rotated strip is a much smaller problem than the general
one: one line of type, no columns, no hanging punctuation, no drop cap. So it
gets its own lane, and the lane is kept deliberately narrow.

What the lane claims
--------------------

Only paragraphs another pass has just rewritten and which are set along the
vertical axis. A rotated paragraph nobody changed is already correct on the
page and is left exactly as it is: this sets translated text, it does not
re-set source text. The claim is passed in rather than inferred, so the set of
paragraphs the lane touched is a list some other pass can be held to.

How it lays out
---------------

The box transposed -- its height is the length of a line and its width is the
depth available for lines -- and then filled along one axis. Characters keep
the font and size the typesetting stage mapped for them, so the advances are
the real ones and not an estimate; a line breaks where the target language's
break rule allows, which is a word edge in English and nearly anywhere in
Chinese. Where the text will not fit at full size the size is reduced, by the
same repeated shrink the general stage uses and down to the same floor.

What it is kept away from
-------------------------

The column reflow, the drop cap and the hanging punctuation ledger. None of the
three has any notion of a rotated box: the reflow moves paragraphs down a
column measured in y, the drop cap sets an initial against the first lines of a
paragraph measured in x, and the ledger records how far past ``box.x2`` a mark
was allowed to stand. What they would do to a transposed box is not defined, so
the lane's paragraphs are excluded from all three and the exclusion is asserted
rather than assumed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.react import writeback
from babeldoc.magazine.reading_order import paragraph_characters

logger = logging.getLogger(__name__)

REPORT_NAME = "rotated_lane.report.json"

SWITCH = "magazine_rotated_lane"

# How far past its own box a rotated strip may reach before the layout is
# refused, in points. The same slack the ordinary path allows itself for a
# rounded advance; past it the strip has rearranged the page rather than been
# set on it, and the caller puts the paragraph back.
_EDGE_SLACK = 1.0

# What the lane set this run, in the order it set it.
_RECORDER: list[dict] = []

# Why a strip the lane took was not set after all.
SKIP_WILL_NOT_FIT = "reached_past_its_own_box"


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def _transposed(box):
    """The paragraph's box with its two axes exchanged, at the same origin.

    The packer measures a line along x. A rotated strip is six points wide and
    a hundred long, so measured that way it holds nothing; measured across its
    own axis it holds a line. Exchanging the two is the whole of the trick, and
    it is done by handing the packer a different box rather than by teaching it
    about axes.
    """
    return il_version_1.Box(
        x=float(box.x),
        y=float(box.y),
        x2=float(box.x) + (float(box.y2) - float(box.y)),
        y2=float(box.y) + (float(box.x2) - float(box.x)),
    )


def _rotate_into(characters, laid_box, box) -> None:
    """Map characters laid out in the transposed box back onto the real one.

    The writer draws a character marked vertical with the matrix ``0 1 -1 0``
    anchored at its box's right hand edge and bottom, under which the pen
    advances up the page and the ascent runs to the left. So a character that
    the packer placed at horizontal offset ``u`` along its line and at vertical
    depth ``v`` below the top of the transposed box belongs at ``u`` up from the
    real box's bottom and ``v`` in from its right hand edge.
    """
    left = float(laid_box.x)
    top = float(laid_box.y2)
    right = float(box.x2)
    bottom = float(box.y)
    for character in characters:
        if character.box is None:
            continue
        along = float(character.box.x) - left
        extent = float(character.box.x2) - float(character.box.x)
        depth = top - float(character.box.y2)
        height = float(character.box.y2) - float(character.box.y)
        character.box.y = bottom + along
        character.box.y2 = bottom + along + extent
        character.box.x2 = right - depth
        character.box.x = right - depth - height
        character.vertical = True


def _extent(characters) -> tuple[float, float, float, float] | None:
    boxes = [c.box for c in characters if c.box is not None]
    if not boxes:
        return None
    return (
        min(float(b.x) for b in boxes),
        min(float(b.y) for b in boxes),
        max(float(b.x2) for b in boxes),
        max(float(b.y2) for b in boxes),
    )


def set_along_axis(typesetting, paragraph, page) -> bool:
    """Lay one rotated paragraph out along its own axis. False where it will not.

    Called in place of the ordinary re-layout, for a paragraph the ordinary one
    cannot serve. The packer is not modified and not bypassed: it is given the
    paragraph's box with the axes exchanged, does its own line breaking with the
    real mapped font, and what comes back is rotated into place.
    """
    box = paragraph.box
    if box is None:
        return False
    original = il_version_1.Box(
        x=float(box.x), y=float(box.y), x2=float(box.x2), y2=float(box.y2)
    )
    laid = _transposed(original)
    paragraph.box = laid
    try:
        fonts = writeback.page_font_map(page, typesetting.font_mapper)
        typesetting.render_paragraph(paragraph, page, fonts)
    except Exception:  # noqa: BLE001 - any failure leaves the line as it was
        logger.warning(
            "rotated lane: laying out a strip along its axis failed", exc_info=True
        )
        paragraph.box = original
        return False
    characters = paragraph_characters(paragraph)
    if not paragraph.pdf_paragraph_composition or not characters:
        paragraph.box = original
        return False
    _rotate_into(characters, laid, original)
    paragraph.box = original
    reach = _extent(characters)
    fits = reach is not None and (
        reach[0] >= original.x - _EDGE_SLACK
        and reach[1] >= original.y - _EDGE_SLACK
        and reach[2] <= original.x2 + _EDGE_SLACK
        and reach[3] <= original.y2 + _EDGE_SLACK
    )
    _RECORDER.append(
        {
            "reference": None,
            "layout_label": paragraph.layout_label,
            "box": [round(v, 2) for v in (original.x, original.y, original.x2, original.y2)],
            "reach": None if reach is None else [round(v, 2) for v in reach],
            "characters": len(characters),
            "text": "".join(c.char_unicode or "" for c in characters)[:60],
            "skipped": None if fits else SKIP_WILL_NOT_FIT,
        }
    )
    return fits


def claims(paragraph) -> bool:
    """Whether this paragraph is the lane's rather than the ordinary layout's."""
    return bool(getattr(paragraph, "vertical", False))


def note_reference(reference: str) -> None:
    """Name the paragraph the last layout belonged to, for the record."""
    if _RECORDER and _RECORDER[-1]["reference"] is None:
        _RECORDER[-1]["reference"] = reference


def reset() -> None:
    _RECORDER.clear()


def write_report(translation_config) -> dict | None:
    """Write what the lane set, or nothing where the switch is down."""
    if not enabled(translation_config):
        return None
    laid = [row for row in _RECORDER if row["skipped"] is None]
    record = {
        "switch": SWITCH,
        "target_lang": getattr(translation_config, "lang_out", "") or "",
        "laid_out": len(laid),
        "attempted": len(_RECORDER),
        "paragraphs": list(_RECORDER),
        # Named here so that the gate reads the exclusion off the pass that
        # owns it rather than off a list kept somewhere else.
        "excluded_from": ["column_reflow", "drop_cap", "typeset_hang"],
    }
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    logger.debug("rotated lane: %d strip(s) set along their own axis", len(laid))
    return record
