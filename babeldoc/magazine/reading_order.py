"""What a paragraph says, in the order a reader reads it.

A paragraph's composition is a list, and the list is the order the parser
recovered the style runs in rather than the order they are read in. For text
set along the page's horizontal axis the two agree. For text set along the
vertical axis they need not: a strip set rotated is stored top of page first
and read bottom of page first, so concatenating the list gives a permutation of
the line rather than the line.

The permutation is invisible to a measurement that counts characters and fatal
to one that reads them. A script share is unaffected by it; a request that
sends the text to a model is not, and what comes back is an answer to a
scrambled question.

So the order is derived from the geometry rather than assumed. The characters
inside one run advance in some direction, which is the direction the paragraph
is written in, and it is read off the boxes those characters already carry. A
paragraph whose runs advance along the vertical axis is sorted by where each
run sits on that axis, in the direction its own characters advance. Anything
else -- a paragraph written along the horizontal axis, one whose runs carry no
geometry to compare, one with a single run -- is left in the order it is stored
in, so this changes nothing for the paragraphs whose stored order was already
the reading order.
"""

from __future__ import annotations

# The composition members that carry a list of characters. ``pdf_character`` is
# one character on its own, and the unicode holder carries a string instead of
# characters, so neither is in this list.
_CHARACTER_HOLDERS = ("pdf_same_style_characters", "pdf_line", "pdf_formula")
_UNICODE_HOLDER = "pdf_same_style_unicode_characters"


def _characters(composition) -> list:
    """The laid out characters of one composition member, in stored order."""
    if composition.pdf_character is not None:
        return [composition.pdf_character]
    for name in _CHARACTER_HOLDERS:
        group = getattr(composition, name, None)
        if group is not None:
            return list(group.pdf_character or ())
    return []


def _unit(composition) -> tuple[str, list]:
    """One composition as the text it shows and the characters it shows it with.

    The unicode holder is read before the character holders and after the single
    character, which is the order the members are declared in and the order a
    composition carries at most one of.
    """
    if composition.pdf_character is not None:
        return composition.pdf_character.char_unicode or "", [
            composition.pdf_character
        ]
    holder = getattr(composition, _UNICODE_HOLDER, None)
    if holder is not None:
        return holder.unicode or "", []
    characters = _characters(composition)
    return "".join(item.char_unicode or "" for item in characters), characters


def _centre(box) -> tuple[float, float] | None:
    if box is None:
        return None
    values = (box.x, box.y, box.x2, box.y2)
    if any(value is None for value in values):
        return None
    return ((float(box.x) + float(box.x2)) / 2, (float(box.y) + float(box.y2)) / 2)


def _advance(units) -> tuple[float, float]:
    """How far the characters of these units travel, summed over each step.

    Summed rather than counted so that a run advancing steadily in one direction
    outweighs the odd step that does not, which is what a superscript or a
    kerned pair looks like from here.

    The steps are the ones inside a unit wherever there are any. A paragraph
    whose units hold one character each has none, so its two sums are zero,
    neither axis dominates, and the paragraph is left in stored order -- and
    that is exactly the shape a strip of rotated type arrives in, one character
    per formula, which is the paragraph this module exists for. For that shape
    alone the steps between consecutive units are counted instead.

    The two cases are kept apart rather than merged because the step between
    two units of a paragraph set in lines is not an advance: at a line end it
    runs the width of the column backwards and one line down, and summing those
    with the steps along the lines makes a page of running text look as though
    it were written downwards. Where a unit carries its own characters the
    direction is legible without leaving the unit, and that is the reading
    taken.
    """
    horizontal = 0.0
    vertical = 0.0
    for _text, characters in units:
        centres = [
            centre
            for centre in (_centre(item.box) for item in characters)
            if centre is not None
        ]
        for first, second in zip(centres, centres[1:], strict=False):
            horizontal += second[0] - first[0]
            vertical += second[1] - first[1]
    if horizontal or vertical:
        return horizontal, vertical
    return _strip_advance(units)


def _strip_advance(units) -> tuple[float, float]:
    """The advance of a paragraph whose units carry one character each.

    Two conditions, and neither of them is the stored order. The characters have
    to stand in a single column of type -- every one within the width of one
    character of every other, compared against their own measured width so that
    no threshold is introduced -- and they have to be marked as set along the
    vertical axis. A paragraph set in lines fails the first by the width of its
    column and is given no direction rather than the wrong one.

    The direction itself comes from that mark and not from the geometry, because
    the geometry here cannot supply it. The stored order of a one character unit
    is the only order there is, so a direction measured from it would be the
    direction of the stored order, and sorting by that would reproduce the
    stored order and call it the reading order -- which is the answer this
    module exists to avoid. The mark is where the answer is: the writer turns it
    into the one rotation it stands for, ``0 1 -1 0``, and under that matrix the
    pen travels up the page. So the reading order of a marked column is
    ascending, whichever way the characters were stored.
    """
    boxes = [
        item.box
        for _text, characters in units
        for item in characters
        if _centre(item.box) is not None
    ]
    if len(boxes) < 2:
        return 0.0, 0.0
    marked = all(
        bool(getattr(item, "vertical", False))
        for _text, characters in units
        for item in characters
    )
    if not marked:
        return 0.0, 0.0
    horizontals = [_centre(box)[0] for box in boxes]
    verticals = [_centre(box)[1] for box in boxes]
    widths = sorted(float(box.x2) - float(box.x) for box in boxes)
    if max(horizontals) - min(horizontals) > widths[len(widths) // 2]:
        return 0.0, 0.0
    return 0.0, max(verticals) - min(verticals)


def _band(characters) -> float | None:
    """Where one unit sits on the vertical axis, as the middle of its extent."""
    centres = [
        centre
        for centre in (_centre(item.box) for item in characters)
        if centre is not None
    ]
    if not centres:
        return None
    verticals = [centre[1] for centre in centres]
    return (min(verticals) + max(verticals)) / 2


def reading_order(units) -> list[int]:
    """The positions of ``units`` in the order they are read, stored order first.

    Stored order is returned unless the geometry positively says otherwise: the
    characters have to advance further along the vertical axis than along the
    horizontal one, and every unit has to carry a band to be placed by. A sort
    that cannot be justified from the geometry is not performed.
    """
    positions = list(range(len(units)))
    if len(units) < 2:
        return positions
    horizontal, vertical = _advance(units)
    if abs(vertical) <= abs(horizontal):
        return positions
    bands = [_band(characters) for _text, characters in units]
    if any(band is None for band in bands):
        return positions
    direction = 1.0 if vertical > 0 else -1.0
    return sorted(positions, key=lambda position: direction * bands[position])


def paragraph_characters(paragraph) -> list:
    """Every laid out character of a paragraph, in the order it is read.

    The shared walk. A pass needing a paragraph's characters asks here rather
    than naming the composition members itself, so there is one place that knows
    which members hold characters and one order they come back in -- which is
    what keeps a finding and the repair answering for it looking at one string.
    """
    compositions = paragraph.pdf_paragraph_composition or []
    units = [_unit(composition) for composition in compositions]
    order = reading_order(units)
    return [character for position in order for character in units[position][1]]


def paragraph_reading_text(paragraph) -> str:
    """What the page shows for this paragraph, as a reader reads it.

    ``unicode`` is the string the translation round trip was carried out in and
    it still carries the placeholder markup the paragraph's style runs and
    formulae were represented by; measuring a script share over it would count
    the markup as text. The composition after typesetting is the laid out
    characters themselves, which is what the reader sees. A paragraph with no
    composition -- which a hand built one may be -- falls back to ``unicode``.
    """
    compositions = paragraph.pdf_paragraph_composition or []
    if not compositions:
        return paragraph.unicode or ""
    units = [_unit(composition) for composition in compositions]
    return "".join(units[position][0] for position in reading_order(units))
