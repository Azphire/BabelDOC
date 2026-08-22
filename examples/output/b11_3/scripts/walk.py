"""Walk a StylesAndFormulas checkpoint and judge every formula composition.

Shared by the T1 self-check and the T2 measurement so that both ask the
criterion the same question in the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402

import formula_criterion as fc  # noqa: E402


def font_table(page) -> dict:
    """Resolve font ids to face names, page level and per xobject."""
    table = {}
    for font in page.pdf_font or []:
        table[(None, font.font_id)] = font.name
    for xobj in page.pdf_xobject or []:
        for font in xobj.pdf_font or []:
            table[(xobj.xobj_id, font.font_id)] = font.name
    return table


def resolve(table: dict, xobj_id, font_id) -> str | None:
    return table.get((xobj_id, font_id)) or table.get((None, font_id))


def walk(checkpoint: Path, config: dict):
    """Yield one record per pdf_formula composition in the document."""
    # load_checkpoint rather than the bare converter: a checkpoint escapes the
    # codepoints XML 1.0 will not carry, and only this reader reverses that. The
    # raw converter hands back the escape as six literal characters, which the
    # annotation stage then reads as six ASCII letters rather than one control.
    doc = load_checkpoint(checkpoint)
    for page in doc.page:
        table = font_table(page)
        for index, para in enumerate(page.pdf_paragraph or []):
            for slot, comp in enumerate(para.pdf_paragraph_composition or []):
                if not comp.pdf_formula:
                    continue
                chars = comp.pdf_formula.pdf_character or []
                fonts = {
                    resolve(table, para.xobj_id, c.pdf_style.font_id)
                    for c in chars
                    if c.pdf_style
                }
                fonts.discard(None)
                verdict = fc.evaluate(comp.pdf_formula, fonts, config)
                yield {
                    # page_number is zero based in the IL; the reports number
                    # pages from one, so both are carried and never conflated.
                    "page_index": page.page_number,
                    "page": page.page_number + 1,
                    "paragraph_slot": index,
                    "anchor": f"p{page.page_number + 1}#{index}",
                    "composition_slot": slot,
                    "paragraph_text": para.unicode,
                    "paragraph_label": para.layout_label,
                    "paragraph_vertical": bool(para.vertical),
                    "fonts": sorted(fonts),
                    "n_chars": len(chars),
                    "all_chars_vertical": bool(chars) and all(c.vertical for c in chars),
                    "is_corner_mark": bool(comp.pdf_formula.is_corner_mark),
                    "text": verdict.text,
                    "is_mislabel": verdict.is_mislabel,
                    "reason": verdict.reason,
                    "exemption": verdict.exemption,
                    "longest_letter_run": verdict.longest_letter_run,
                    "letter_ratio": verdict.letter_ratio,
                    "math_ratio": verdict.math_ratio,
                }
