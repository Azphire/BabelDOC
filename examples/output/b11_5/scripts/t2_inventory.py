"""T2.3: the consumer inventory this batch owes before a reclassification.

CLAUDE.md section 4.18 makes a fresh inventory the precondition for any change
that moves an IL element between types, and forbids reusing an earlier batch's
list: the mechanism holds still while the code moves, so a reused list is a list
nobody checked. This one is written against the tree as it stands and is proved
against it -- every site it names is located by reading the file, so a site that
has moved or gone fails the build of this record rather than being carried
forward as a line of prose.

The absolute item of section 4.18 is answered here as well: a composition
carrying pdf_form or pdf_curve is never reclassified. That claim is not asserted
by inspection, it is counted -- the count comes out of t2_measurement.json,
which drove the real stage twice, and the count being a count is what makes
"zero" an assertion rather than an inheritance.

Writes examples/output/b11_5/t2_consumer_inventory.json.

Usage:
    python t2_inventory.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

MEASUREMENT = ROOT / "examples" / "output" / "b11_5" / "t2_measurement.json"
OUT = ROOT / "examples" / "output" / "b11_5" / "t2_consumer_inventory.json"

# One entry per site that reads the formula annotation, each with the anchor
# text the site is located by. The anchor is matched rather than the line number
# recorded, because a line number is stale the moment anything above it moves.
SITES = [
    {
        "file": "babeldoc/format/pdf/document_il/backend/pdf_creater.py",
        "anchor": "formula_forms.extend(composition.pdf_formula.pdf_form)",
        "reads": "the pdf_form list held inside a formula composition",
        "effect": (
            "This and the curve site below are the only render entry for graphics "
            "carried inside a formula; a reclassified composition would drop them "
            "silently, because PdfLine has neither member. Measured: no "
            "reclassified composition carries a form or a curve, and the page "
            "level form and curve counts are identical in both arms on every "
            "page of every sample, so nothing is dropped and nothing is orphaned."
        ),
        "verdict": "no change",
        "absolute": True,
    },
    {
        "file": "babeldoc/format/pdf/document_il/backend/pdf_creater.py",
        "anchor": "formula_curves.extend(composition.pdf_formula.pdf_curve)",
        "reads": "the pdf_curve list held inside a formula composition",
        "effect": "As above; the two sites are one question and are counted together.",
        "verdict": "no change",
        "absolute": True,
    },
    {
        "file": "babeldoc/format/pdf/document_il/backend/pdf_creater.py",
        "anchor": "chars.extend(composition.pdf_formula.pdf_character)",
        "reads": "a formula's characters, when flattening a paragraph for render",
        "effect": (
            "The characters are the same objects either way; the sibling branch "
            "for a line reaches them by the same extend. Nothing renders "
            "differently on this account."
        ),
        "verdict": "no change",
    },
    {
        "file": "babeldoc/format/pdf/document_il/midend/styles_and_formulas.py",
        "anchor": "and not composition.pdf_formula.is_corner_mark",
        "reads": "the corner mark flag, to decide whether a formula is translatable",
        "effect": (
            "This is the one place downstream of the predicate that reads the "
            "flag itself. It converts a non corner mark formula of digits back "
            "into a line. A composition the exemption keeps out of formula never "
            "reaches it, which is the same outcome by a shorter road."
        ),
        "verdict": "unreachable for the exempted span, by construction",
    },
    {
        "file": "babeldoc/format/pdf/document_il/midend/styles_and_formulas.py",
        "anchor": "all_formulas.append((composition.pdf_formula, paragraph.xobj_id))",
        "reads": "every formula of a page, to assign page curves and forms to them",
        "effect": (
            "A formula that no longer exists is not offered as a home for a "
            "curve, so the curve stays on the page and is drawn from there. "
            "Measured over the full stage rather than the formula pass alone: "
            "page level counts move on no page."
        ),
        "verdict": "no change",
        "absolute": True,
    },
    {
        "file": "babeldoc/format/pdf/document_il/midend/typesetting.py",
        "anchor": "result.extend([TypesettingUnit(formular=composition.pdf_formula)])",
        "reads": "a formula composition, to make one typesetting unit of it",
        "effect": (
            "A formula becomes a unit the typesetter carries whole and does not "
            "scale with the text. Reclassified, its characters join the text unit "
            "beside them and are set with it. That is the repair: the letters of "
            "an opening word are set as the word they belong to."
        ),
        "verdict": "intended change",
    },
    {
        "file": "babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py",
        "anchor": "is_placeholder_only_paragraph(paragraph)",
        "reads": (
            "whether a paragraph is nothing but formulas and whitespace, to skip "
            "translating it"
        ),
        "effect": (
            "A paragraph that was formula only could become text only and so be "
            "translated where it was not. Neither reclassified instance is in "
            "such a paragraph: both sit among text compositions of the same "
            "paragraph, so the paragraph was translated before and is translated "
            "now."
        ),
        "verdict": "no change on the measured instances",
    },
    {
        "file": "babeldoc/format/pdf/document_il/utils/paragraph_helper.py",
        "anchor": "if composition.pdf_formula:",
        "reads": "a formula composition, as an allowed member of a placeholder paragraph",
        "effect": "The reading half of the site above; same answer.",
        "verdict": "no change on the measured instances",
    },
    {
        "file": "babeldoc/format/pdf/document_il/midend/il_translator.py",
        "anchor": "elif composition.pdf_formula:",
        "reads": "a formula, to build its placeholder in the translate input",
        "effect": (
            "The non LLM translator, which CLAUDE.md section 2 forbids this "
            "project from using or altering. Recorded so the inventory is "
            "complete; the run path is ILTranslatorLLMOnly."
        ),
        "verdict": "off the run path",
    },
    {
        "file": "babeldoc/format/pdf/document_il/midend/add_debug_information.py",
        "anchor": "if composition.pdf_formula:",
        "reads": "a formula's box, to draw it in the debug overlay",
        "effect": (
            "One fewer box is drawn in the debug document where a composition is "
            "reclassified. The debug overlay is not a product and no assertion "
            "reads it."
        ),
        "verdict": "cosmetic, debug only",
    },
    {
        "file": "babeldoc/format/pdf/document_il/midend/paragraph_finder.py",
        "anchor": "chars.extend(composition.pdf_formula.pdf_character)",
        "reads": "a formula's characters when composing a paragraph",
        "effect": (
            "Runs before the styling stage, so it never sees a composition this "
            "predicate touched. Listed because it reads the annotation."
        ),
        "verdict": "upstream of the change",
    },
    {
        "file": "babeldoc/format/pdf/document_il/midend/remove_descent.py",
        "anchor": "elif comp.pdf_formula:",
        "reads": "a formula's characters, to adjust descent",
        "effect": "Reaches the same characters through the line branch instead.",
        "verdict": "no change",
    },
    {
        "file": "babeldoc/format/pdf/document_il/utils/layout_helper.py",
        "anchor": "chars.extend(composition.pdf_formula.pdf_character)",
        "reads": "a formula's characters and box, for width, height and order",
        "effect": (
            "Every one of this file's formula branches has a line branch beside "
            "it reaching the same characters and the same box. The measured "
            "instances hold no graphics, so the box is the characters' own union "
            "either way."
        ),
        "verdict": "no change",
    },
    {
        "file": "babeldoc/magazine/line_split.py",
        "anchor": 'ATOMIC = ("pdf_formula", "pdf_character", "pdf_same_style_unicode_characters")',
        "reads": "the composition kind, to decide what may be regrouped by line",
        "effect": (
            "A formula is atomic and a line is splittable, so a reclassified "
            "composition becomes eligible for line regrouping. That is what lets "
            "the drop cap merge act at all, since its mergeable set is this "
            "splittable set."
        ),
        "verdict": "intended change",
    },
    {
        "file": "babeldoc/magazine/drop_cap.py",
        "anchor": "tail_kind not in _MERGEABLE",
        "reads": "the kind of the composition after the initial",
        "effect": (
            "The guard that refused to fold the initial into a formula. With the "
            "tail reclassified as a line the guard passes and the initial is "
            "merged, which is the whole chain this task is for. The guard itself "
            "is untouched: a formula tail still refuses."
        ),
        "verdict": "intended change",
    },
    {
        "file": "babeldoc/magazine/column_reflow.py",
        "anchor": "movable=not holds_formula(paragraph) and not inside_xobject(paragraph),",
        "reads": "whether a paragraph holds a formula, to decide if reflow may move it",
        "effect": (
            "A paragraph pinned because it held a formula may become movable. "
            "This is the one site where the reclassification could change a "
            "decision about a paragraph rather than about a composition, so the "
            "run's column_reflow report is compared against the baseline rather "
            "than reasoned about."
        ),
        "verdict": "watch at run time",
    },
    {
        "file": "babeldoc/magazine/fragment_stitch.py",
        "anchor": "if composition_kind(composition) not in SPLITTABLE:",
        "reads": "the composition kinds of a paragraph, to decide if it may be stitched",
        "effect": (
            "A paragraph holding a formula is disqualified from stitching. "
            "Reclassified, it may qualify. Both measured instances are single "
            "paragraphs that were already whole, so nothing is joined to them; "
            "the run's fragment_stitch report is compared against the baseline."
        ),
        "verdict": "watch at run time",
    },
    {
        "file": "babeldoc/magazine/paren_dedup.py",
        "anchor": "kind in SPLITTABLE",
        "reads": "the composition kind, to mark a segment as one it may cut",
        "effect": (
            "A reclassified composition becomes cuttable by the bracket dedup "
            "pass. It only cuts where it finds a duplicated bracketed run, and "
            "neither measured instance holds a bracket."
        ),
        "verdict": "no change on the measured instances",
    },
    {
        "file": "babeldoc/magazine/source_audit.py",
        "anchor": "_COMPOSITION_KINDS = (*SPLITTABLE, *ATOMIC)",
        "reads": "every composition kind, to audit what the source held",
        "effect": (
            "Counts both kinds, so a composition moving between them changes "
            "which tally it lands in and not whether it is seen."
        ),
        "verdict": "no change in totals",
    },
    {
        "file": "babeldoc/magazine/chain_signals.py",
        "anchor": "characters.extend(composition.pdf_formula.pdf_character)",
        "reads": "a formula's characters, when reading a paragraph's text for chaining",
        "effect": "Reaches the same characters through the line branch instead.",
        "verdict": "no change",
    },
    {
        "file": "babeldoc/magazine/react/writeback.py",
        "anchor": '_CHARACTER_HOLDERS = ("pdf_same_style_characters", "pdf_line", "pdf_formula")',
        "reads": "all three character holders, when writing a repair back",
        "effect": "Both kinds are in the tuple, so the holder is found either way.",
        "verdict": "no change",
    },
    {
        "file": "babeldoc/magazine/reading_order.py",
        "anchor": '_CHARACTER_HOLDERS = ("pdf_same_style_characters", "pdf_line", "pdf_formula")',
        "reads": "all three character holders, when reading document order",
        "effect": "As above.",
        "verdict": "no change",
    },
]


def main() -> int:
    if not MEASUREMENT.is_file():
        raise SystemExit(f"no measurement at {MEASUREMENT}")
    measurement = json.loads(MEASUREMENT.read_text(encoding="utf-8"))

    faults = []
    for site in SITES:
        path = ROOT / site["file"]
        if not path.is_file():
            faults.append(f"{site['file']}: gone")
            continue
        text = path.read_text(encoding="utf-8")
        occurrences = text.count(site["anchor"])
        if occurrences == 0:
            faults.append(f"{site['file']}: anchor not found: {site['anchor'][:60]}")
        site["occurrences"] = occurrences
    if faults:
        for fault in faults:
            print("FAULT", fault, flush=True)
        raise SystemExit("the inventory does not match the tree it was written for")

    reclassified = measurement["reclassified"]
    carriers = [r for r in reclassified if r["pdf_form"] or r["pdf_curve"]]
    record = {
        "rule": "CLAUDE.md 4.18",
        "written_for": "b11.5 T2, the corner mark exemption beside an enlarged initial",
        "reuse": (
            "None. Every site below was located in the current tree by matching "
            "its anchor text, and this record fails to build if one has moved."
        ),
        "absolute_item": {
            "statement": (
                "A composition carrying pdf_form or pdf_curve is never "
                "reclassified. Absolute, and not softened by any finding."
            ),
            "reclassified_total": len(reclassified),
            "carrying_pdf_form_or_curve": len(carriers),
            "carriers": carriers,
            "page_level_graphics_moved": measurement["totals"][
                "pages_with_graphics_moved"
            ],
            "structural_note": (
                "create_composition builds a formula from characters alone, so a "
                "composition made by this predicate holds no graphic at the "
                "moment it is made; graphics are assigned to formulas afterwards "
                "by collect_contained_elements. The count above is taken after "
                "the whole stage has run, so it covers that assignment too."
            ),
        },
        "sites": SITES,
        "sites_total": len(SITES),
        "verdict_counts": {
            verdict: sum(1 for s in SITES if s["verdict"] == verdict)
            for verdict in sorted({s["verdict"] for s in SITES})
        },
        "watch_at_run_time": [
            s["file"] for s in SITES if s["verdict"] == "watch at run time"
        ],
    }
    OUT.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"sites={len(SITES)} carriers={len(carriers)} "
        f"graphics_moved={record['absolute_item']['page_level_graphics_moved']}",
        flush=True,
    )
    print(json.dumps(record["verdict_counts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
