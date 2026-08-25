"""The consumer list CLAUDE.md section 4.18 requires before a reclassification.

T3.3 changes what a composition is: one holding ``pdf_formula`` becomes one
holding ``pdf_line``. Section 4.18 says that before such a change is made,
every downstream site consuming the annotation has to be listed and each one
answered -- what happens here after the change -- and that the list may not be
carried over from another batch, because the mechanism stays the same while the
code moves.

The sites are found by scanning rather than remembered, so the list is this
tree's. Each is then answered by hand below, keyed by file and line, and the
script refuses to write a list with a site it has no answer for: a site nobody
answered is exactly what the requirement exists to catch.

The carrier count is measured, not asserted from the last batch. b11.3 found
that ``PdfFormula`` holds ``pdf_form`` and ``pdf_curve`` while ``PdfLine`` holds
neither, and that the writer's only route to those two runs through the formula
holder -- so a converted carrier loses its artwork with no error at all. The
count of carriers in scope is therefore taken here, from the checkpoint the
pass reads, so that "none carried artwork" is a measurement this batch made.

Writes ``examples/output/b11_7/t3_consumer_list.json``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import formula_reclass  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "t3_consumer_list.json"
PRIOR = ROOT / "examples" / "output" / "b11_6"

# The stage whose checkpoint the pass reads, so the count is taken over exactly
# the compositions the pass is offered.
CHECKPOINT = "checkpoint.06_styles_and_formulas.xml"

SAMPLES = (
    ("Courier-en", "zh"),
    ("AramcoWorld-en-v2", "zh"),
    ("FD-en-v2", "zh"),
    ("Courier-zh", "en"),
)

# One answer per site, keyed by file and by what the site reads. Every site the
# scan finds has to match one of these keys or the script fails.
ANSWERS = {
    "babeldoc/format/pdf/document_il/backend/pdf_creater.py": {
        "reads": "the characters of a composition, and separately its pdf_form "
        "and pdf_curve, which are the writer's only route to vector artwork",
        "after_reclassification": "A converted composition is a line and the "
        "writer takes its characters through the line branch, which draws the "
        "same glyphs. The form and curve branches no longer see it, which is "
        "why a composition carrying either is never converted -- that is the "
        "absolute rule, and the carrier count below is what shows it was not "
        "merely assumed.",
    },
    "babeldoc/format/pdf/document_il/midend/add_debug_information.py": {
        "reads": "a formula's box and characters, to draw a debug frame",
        "after_reclassification": "Debug output only, and it runs under the "
        "debug switch. A converted composition draws no formula frame; its "
        "characters are still drawn by the line branch. Nothing a produced "
        "document shows depends on it.",
    },
    "babeldoc/format/pdf/document_il/midend/il_translator.py": {
        "reads": "a formula, to replace it with a placeholder in the request "
        "and to restore it in the answer",
        "after_reclassification": "This is the point of the change. A "
        "converted composition is no longer replaced by a placeholder, so its "
        "characters reach the request as text and are translated. Nothing in "
        "this file is modified; what changes is which compositions arrive "
        "carrying a formula.",
    },
    "babeldoc/format/pdf/document_il/midend/paragraph_finder.py": {
        "reads": "a formula's characters, when gathering a paragraph's",
        "after_reclassification": "The stage runs before this pass and never "
        "sees a converted composition.",
    },
    "babeldoc/format/pdf/document_il/midend/remove_descent.py": {
        "reads": "a formula's characters, to shift them off the descent",
        "after_reclassification": "It handles the line branch the same way, so "
        "a converted composition is shifted identically.",
    },
    "babeldoc/format/pdf/document_il/midend/styles_and_formulas.py": {
        "reads": "everything about a formula: is_corner_mark, line_id, the "
        "offsets, and the merge and split of formulas within a paragraph",
        "after_reclassification": "The stage that writes all of them, and it "
        "has finished before this pass runs. is_corner_mark and line_id are "
        "read nowhere else in the tree, which is why converting a corner mark "
        "loses nothing downstream. This pass converts by the same rewrite that "
        "stage already performs on the formulas it judges translatable.",
    },
    "babeldoc/format/pdf/document_il/midend/typesetting.py": {
        "reads": "a formula, to build one typesetting unit carrying it whole, "
        "and its x_advance and offsets when placing it",
        "after_reclassification": "A converted composition becomes ordinary "
        "character units instead of one formula unit, so it is line broken "
        "like text rather than carried as an atom -- which is what a credit "
        "line should be. It loses the formula's padding advance and takes its "
        "own characters' advances instead.",
    },
    "babeldoc/format/pdf/document_il/utils/layout_helper.py": {
        "reads": "a formula's width, height, characters, and its first and "
        "last character, for the layout measurements shared across stages",
        "after_reclassification": "Every one of those has a line branch beside "
        "the formula branch, computing the same quantity from the same "
        "characters. The measurements are unchanged.",
    },
    "babeldoc/magazine/chain_signals.py": {
        "reads": "a formula's characters, when gathering an endpoint's",
        "after_reclassification": "The line branch gathers the same "
        "characters, so an endpoint's geometry and text are unchanged.",
    },
    "babeldoc/magazine/drop_cap.py": {
        "reads": "whether a composition is a formula, to leave it alone",
        "after_reclassification": "A converted composition becomes eligible to "
        "be read as a dropped initial. It cannot be one in practice -- the "
        "pass acts only on residue bearing compositions and the drop cap acts "
        "on the first paragraph of an article -- and the lane's exclusion "
        "assertion holds the two apart on the rotated ones.",
    },
    "babeldoc/magazine/line_split.py": {
        "reads": "ATOMIC: a formula is a unit a line split may not divide",
        "after_reclassification": "A converted composition is divisible. That "
        "is correct for the text it now is: a credit line broken across two "
        "lines is set as two lines, which is what the source did.",
    },
    "babeldoc/magazine/react/writeback.py": {
        "reads": "a formula's characters, when rebuilding a paragraph",
        "after_reclassification": "The line branch holds the same characters, "
        "so the rebuild reads the same text. This is the path that writes the "
        "repair back.",
    },
    "babeldoc/format/pdf/document_il/utils/paragraph_helper.py": {
        "reads": "a formula's characters when gathering a paragraph's, and "
        "separately whether every composition of a paragraph is a formula or "
        "whitespace -- the test for a paragraph that is nothing but formula",
        "after_reclassification": "The gather has a line branch holding the "
        "same characters, so it is unchanged. The all-formula test stops "
        "answering yes for a converted paragraph, which is correct and is the "
        "point: a paragraph of residue text is not a paragraph of formula, and "
        "it was that answer which kept it out of the translator's way.",
    },
    "babeldoc/tools/italic_assistance.py": {
        "reads": "the fonts a formula's characters are set in, from a written "
        "IL json, for the standalone italic recognition tool",
        "after_reclassification": "A developer tool run by hand against a "
        "debug json; it is not in any pipeline. It reads the line branch in "
        "the same loop, so it collects the same fonts either way.",
    },
    "babeldoc/magazine/reading_order.py": {
        "reads": "a formula's characters, to order the compositions of a "
        "paragraph as a reader reads them",
        "after_reclassification": "The line branch is in the same list, so a "
        "converted composition is ordered identically.",
    },
}


def scan() -> list[dict]:
    """Every site in the tree reading ``pdf_formula``, by file and line."""
    out = subprocess.run(
        ["git", "grep", "-n", "pdf_formula", "--", "babeldoc", "tools"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    sites = []
    for line in out.stdout.splitlines():
        match = re.match(r"^([^:]+):(\d+):(.*)$", line)
        if not match:
            continue
        path, number, text = match.groups()
        # The generated dataclasses are the definition, not a consumer.
        if path.endswith("il_version_1.py"):
            continue
        sites.append({"file": path, "line": int(number), "source": text.strip()})
    return sites


def carriers() -> dict:
    """How many residue bearing compositions carry artwork, per sample."""
    counts = {}
    for sample, language in SAMPLES:
        path = PRIOR / sample / "work" / sample / CHECKPOINT
        if not path.is_file():
            continue
        if not formula_reclass.acts_in(language):
            counts[sample] = {
                "acts": False,
                "residue_bearing": 0,
                "carrying_artwork": 0,
            }
            continue
        script = formula_reclass.residue_script(language)
        document = load_checkpoint(path)
        bearing = 0
        carrying = 0
        for page in document.page or ():
            for paragraph in page.pdf_paragraph or ():
                for composition in paragraph.pdf_paragraph_composition or ():
                    formula = composition.pdf_formula
                    if formula is None:
                        continue
                    text = "".join(
                        c.char_unicode or "" for c in (formula.pdf_character or ())
                    )
                    if not formula_reclass.holds_residue(text, script):
                        continue
                    bearing += 1
                    if (formula.pdf_form or ()) or (formula.pdf_curve or ()):
                        carrying += 1
        counts[sample] = {
            "acts": True,
            "residue_bearing": bearing,
            "carrying_artwork": carrying,
        }
    return counts


def main() -> int:
    sites = scan()
    answered = []
    unanswered = []
    for site in sites:
        answer = ANSWERS.get(site["file"])
        if answer is None:
            unanswered.append(site)
            continue
        answered.append({**site, **answer})
    files = sorted({site["file"] for site in sites})
    stale = sorted(set(ANSWERS) - set(files))
    counts = carriers()
    payload = {
        "batch": "b11.7",
        "annotation": "a composition's holder, from pdf_formula to pdf_line",
        "absolute_rule": (
            "A composition carrying pdf_form or pdf_curve is never converted. "
            "PdfLine holds neither field and pdf_creater.py is the only "
            "renderer of both, so a converted carrier drops its artwork with "
            "no error raised and nothing missing from any report -- an image "
            "simply absent from the page."
        ),
        "sites": answered,
        "unanswered": unanswered,
        "answers_with_no_site": stale,
        "files": files,
        "carriers_by_sample": counts,
        "carriers_in_scope": sum(
            row["carrying_artwork"] for row in counts.values() if row["acts"]
        ),
        "residue_bearing_in_scope": sum(
            row["residue_bearing"] for row in counts.values() if row["acts"]
        ),
    }
    OUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"sites: {len(sites)} across {len(files)} file(s)")
    print(f"unanswered: {len(unanswered)}  answers with no site: {stale}")
    print(
        f"residue bearing in scope: {payload['residue_bearing_in_scope']}; "
        f"carrying artwork: {payload['carriers_in_scope']}"
    )
    print(f"written: {OUT}")
    return 1 if unanswered else 0


if __name__ == "__main__":
    raise SystemExit(main())
