"""Which annotation path made a composition a formula.

The disjunction in StylesAndFormulas._classify_characters_in_composition is
exhaustive, so a character that none of the directly observable branches
explains must have been taken by the character-class branch. That residual is
reported as such rather than guessed at.
"""

from __future__ import annotations

from babeldoc.format.pdf.document_il.utils.formular_helper import is_formulas_font

# Branch names follow the source order of the disjunction, so that a reader can
# put each back against the line that produced it.
PATHS = ("layout_formula", "formula_font", "vertical", "visual_bbox_disjoint",
         "corner_mark", "character_class")


def _bbox_disjoint(char) -> bool:
    box, vis = char.box, char.visual_bbox.box
    return box.x > vis.x2 or box.x2 < vis.x or box.y > vis.y2 or box.y2 < vis.y


def attribute(formula, font_of_char, formular_font_pattern=None) -> dict:
    """Count, per branch, how many of the composition's characters it explains."""
    chars = formula.pdf_character or []
    tally = dict.fromkeys(PATHS, 0)
    for char in chars:
        explained = False
        if char.formula_layout_id:
            tally["layout_formula"] += 1
            explained = True
        name = font_of_char(char)
        if name and is_formulas_font(name, formular_font_pattern):
            tally["formula_font"] += 1
            explained = True
        if char.vertical:
            tally["vertical"] += 1
            explained = True
        if _bbox_disjoint(char):
            tally["visual_bbox_disjoint"] += 1
            explained = True
        if not explained and not (char.char_unicode or "").isspace():
            # The corner-mark branch is a size ratio against the neighbour, which
            # this view cannot recompute; the flag on the formula records it.
            if formula.is_corner_mark:
                tally["corner_mark"] += 1
            else:
                tally["character_class"] += 1
    return tally


def dominant(tally: dict) -> str | None:
    """The branch explaining the most characters, or None when nothing does."""
    best = max(tally, key=lambda k: tally[k])
    return best if tally[best] else None
