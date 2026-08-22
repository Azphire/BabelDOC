"""The b11.3 mislabel criterion.

One module, used unchanged by the measurement before the repair and by the
measurement after it, so that a change in the counts is a change in the
pipeline and never a change in the question. The gate pins its hash.

Only general signals take part: unicode category, letter-run length, font
identity and the independent formula detectors. Nothing here names a
publication, a page, a paragraph or a string drawn from any sample.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from babeldoc.format.pdf.document_il.utils.formular_helper import is_formulas_font

# A regex that can never match. Passed as formular_font_pattern it replaces the
# broad heuristic branch inside is_formulas_font, so a True can only have come
# from the precise mathematics-typeface pattern. This reads the real decision
# code rather than restating its literal here, which is why the exemption
# cannot drift away from the annotation it defers to.
NEVER_MATCHES = "(?!)"

CONFIG_PATH = Path(__file__).resolve().parent.parent / "criterion_config.json"

# Unicode categories that carry mathematical or symbolic weight rather than
# lexical weight: modifiers, math symbols, and private-use glyphs (dingbats).
MATH_CATEGORIES = frozenset({"Sm", "Sk", "Mn", "Co"})
GREEK_BLOCK = range(0x370, 0x400)
LETTER_RUN = re.compile(r"[^\W\d_]+", re.UNICODE)


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))


def is_math_char(ch: str) -> bool:
    if not ch or ch.isspace():
        return False
    return unicodedata.category(ch) in MATH_CATEGORIES or ord(ch) in GREEK_BLOCK


def composition_text(formula) -> str:
    return "".join(c.char_unicode or "" for c in (formula.pdf_character or []))


def is_precise_math_font(font_name: str | None) -> bool:
    """Whether the face is one of the actual mathematics typefaces.

    Reuses the pattern StylesAndFormulas itself consults, so that the
    exemption cannot drift away from the annotation it defers to.
    """
    if not font_name:
        return False
    return is_formulas_font(font_name, NEVER_MATCHES)


@dataclass(frozen=True)
class Verdict:
    is_mislabel: bool
    reason: str
    text: str
    longest_letter_run: int
    letter_ratio: float
    math_ratio: float
    exemption: str | None


def evaluate(formula, font_names: set[str], config: dict) -> Verdict:
    """Judge one pdf_formula composition.

    font_names are the resolved face names of the composition's characters,
    which only the caller can resolve (they live on the page or the xobject).
    """
    cond = config["conditions"]
    text = composition_text(formula)
    non_space = [c for c in text if not c.isspace()]

    runs = [len(m.group(0)) for m in LETTER_RUN.finditer(text)]
    longest = max(runs) if runs else 0
    letters = sum(1 for c in non_space if c.isalpha())
    maths = sum(1 for c in non_space if is_math_char(c))
    letter_ratio = letters / len(non_space) if non_space else 0.0
    math_ratio = maths / len(non_space) if non_space else 0.0

    exemption = None
    if any(c.formula_layout_id for c in (formula.pdf_character or [])):
        exemption = "layout_formula"
    elif any(is_precise_math_font(n) for n in font_names):
        exemption = "precise_math_font"

    def verdict(is_mislabel: bool, reason: str) -> Verdict:
        return Verdict(is_mislabel, reason, text, longest,
                       round(letter_ratio, 4), round(math_ratio, 4), exemption)

    if exemption:
        return verdict(False, f"exempt: {exemption}")
    if longest < cond["min_word_len"]["value"]:
        return verdict(False, "no letter run long enough to be a word")
    if math_ratio > cond["max_math_ratio"]["value"]:
        return verdict(False, "carries mathematical symbols")
    if letter_ratio < cond["min_letter_ratio"]["value"]:
        return verdict(False, "not predominantly letters")
    return verdict(True, "a word-bearing run with no mathematics and no independent formula evidence")
