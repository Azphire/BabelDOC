"""T3 verification: re-run the annotation stage and judge what it now writes.

The frozen stage-06 checkpoints were written by the code as it stood before the
repair, so re-reading them cannot say anything about the repair. This runs
StylesAndFormulas itself over the frozen stage-05 checkpoints -- the last state
before any formula exists -- and does it twice: once with the broad font pattern
as it stood before the repair, once with the tree as it now stands.

Both arms are the same code over the same input, differing in one pattern. The
before arm is checked against the frozen stage-06 annotation, so the harness has
to reproduce the original before its answer about the repair counts for
anything.

Offline: the stage makes no request and reaches no engine.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import formula_criterion as fc  # noqa: E402
import paths as pp  # noqa: E402
import walk  # noqa: E402

from babeldoc.format.pdf.document_il.midend.styles_and_formulas import (  # noqa: E402
    StylesAndFormulas,
)
from babeldoc.format.pdf.document_il.utils.fontmap import FontMapper  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402

ROOT = Path("d:/Codes/BabelDOC")
BASELINE = ROOT / "examples" / "output" / "b10_5"
SAMPLES = ["AramcoWorld-en-v2", "CERNCourier-en", "Courier-en",
           "Courier-zh", "FD-en-v2", "Vogue-en"]

# The broad formula-font pattern as it stood before the repair. Supplying it as
# formular_font_pattern reinstates exactly the old font branch, because a
# supplied pattern replaces the broad one rather than adding to it. That is what
# lets the two arms differ in one thing and still be produced by one code path.
PATTERN_BEFORE = (
    r"(CM[^RB]|(MS|XY|MT|BL|RM|EU|LA|RS)[A-Z]|LINE|LCIRCLE|TeX-|rsfs|txsy"
    r"|wasy|stmary|.*Mono|.*Code|.*Sym|.*Math|AdvP4C4E74|AdvPSSym|AdvP4C4E59)"
)


class _Config:
    """The little of TranslationConfig this stage reads.

    Written out rather than built, because constructing the real one wants an
    engine, an output directory and a document, none of which an offline
    re-annotation has or needs. Every field here is one the stage actually
    consults; the values are the run's recorded ones (premise 7).
    """

    formular_char_pattern = None
    ocr_workaround = False
    remove_non_formula_lines = False
    non_formula_line_iou_threshold = 0.9
    skip_formula_offset_calculation = False
    primary_font_family = None

    def __init__(self, lang_out: str, font_pattern: str | None):
        # The character-class branch asks the font mapper whether the target
        # language's faces can draw a character, so the direction has to be the
        # sample's own. It is read from the corpus registry, which is where a
        # sample's direction is declared.
        self.lang_out = lang_out
        self.formular_font_pattern = font_pattern

    def raise_if_cancelled(self):
        return None


def reannotate(sample: str, font_pattern: str | None):
    checkpoint = (BASELINE / sample / "on" / "work" / sample
                  / "checkpoint.05_paragraph_finder.xml")
    doc = load_checkpoint(checkpoint)
    _, lang_out = corpus.direction_of(sample)
    config = _Config(lang_out, font_pattern)
    stage = StylesAndFormulas.__new__(StylesAndFormulas)
    stage.translation_config = config
    stage.font_mapper = FontMapper(config)
    for page in doc.page:
        stage.process_page(page)
    return doc


def judge(doc, config, font_pattern: str | None):
    """Every formula composition, judged, and attributed to the branch behind it.

    The attribution is given the arm's own font pattern: asking the current code
    which branch produced a composition the old pattern produced would answer
    about the wrong tree.
    """
    rows, clean = [], []
    for page in doc.page:
        table = walk.font_table(page)
        for slot, para in enumerate(page.pdf_paragraph or []):
            for cslot, comp in enumerate(para.pdf_paragraph_composition or []):
                if not comp.pdf_formula:
                    continue

                def font_of(char, _t=table, _x=para.xobj_id):
                    return (walk.resolve(_t, _x, char.pdf_style.font_id)
                            if char.pdf_style else None)

                fonts = {font_of(c) for c in (comp.pdf_formula.pdf_character or [])}
                fonts.discard(None)
                verdict = fc.evaluate(comp.pdf_formula, fonts, config)
                record = {"page": page.page_number + 1,
                          "anchor": f"p{page.page_number + 1}#{slot}",
                          "composition_slot": cslot, "text": verdict.text,
                          "reason": verdict.reason,
                          "longest_letter_run": verdict.longest_letter_run,
                          "annotation_path": pp.dominant(pp.attribute(
                              comp.pdf_formula, font_of, font_pattern))}
                (rows if verdict.is_mislabel else clean).append(record)
    return rows, clean


def arm(font_pattern: str | None, config: dict) -> dict:
    per_sample, per_path = {}, collections.Counter()
    rows, annotated = [], collections.defaultdict(set)
    for sample in SAMPLES:
        doc = reannotate(sample, font_pattern)
        flagged, clean = judge(doc, config, font_pattern)
        for record in flagged + clean:
            annotated[sample].add((record["page"], record["text"]))
        for record in flagged:
            per_path[record["annotation_path"]] += 1
            rows.append({"sample": sample, **record})
        per_sample[sample] = {"mislabels": len(flagged),
                              "formula_compositions": len(flagged) + len(clean)}
    return {"by_sample": per_sample, "by_annotation_path": dict(per_path),
            "mislabels": len(rows), "rows": rows, "_annotated": annotated}


def frozen_control() -> dict:
    """What the stage-06 checkpoints on disk hold, for the before arm to match."""
    config = fc.load_config()
    out = {}
    for sample in SAMPLES:
        cp = (BASELINE / sample / "on" / "work" / sample
              / "checkpoint.06_styles_and_formulas.xml")
        rows = list(walk.walk(cp, config))
        out[sample] = {"mislabels": sum(1 for r in rows if r["is_mislabel"]),
                       "formula_compositions": len(rows)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    config = fc.load_config()
    reference = json.loads(
        (HERE.parent / "t3_reference_set.json").read_text(encoding="utf-8"))

    control = frozen_control()
    before = arm(PATTERN_BEFORE, config)
    after = arm(None, config)

    # The harness has to reproduce the frozen annotation before its answer about
    # the repair means anything.
    mismatches = [
        {"sample": s, "frozen": control[s], "reannotated": before["by_sample"][s]}
        for s in SAMPLES if control[s] != before["by_sample"][s]]

    survived, lost = [], []
    for item in reference["items"]:
        entry = {k: item[k] for k in ("sample", "page", "text", "why_genuine")}
        (survived
         if (item["page"], item["text"]) in after["_annotated"][item["sample"]]
         else lost).append(entry)
    wrongly_flagged = [
        r for r in after["rows"]
        if any(r["sample"] == i["sample"] and r["page"] == i["page"]
               and r["text"] == i["text"] for i in reference["items"])]

    before_keys = {(r["sample"], r["page"], r["text"]) for r in before["rows"]}
    after_keys = {(r["sample"], r["page"], r["text"]) for r in after["rows"]}
    fixed = [r for r in before["rows"]
             if (r["sample"], r["page"], r["text"]) not in after_keys]
    introduced = [r for r in after["rows"]
                  if (r["sample"], r["page"], r["text"]) not in before_keys]

    for a in (before, after):
        a.pop("_annotated")

    result = {
        "what_this_is": "the annotation stage run twice over the frozen stage-05 "
                        "checkpoints, differing only in the broad font pattern",
        "landing_site": "babeldoc/format/pdf/document_il/utils/formular_helper.py, "
                        "is_formulas_font, the broad formula-font pattern",
        "criterion_sha256": hashlib.sha256(
            (HERE / "formula_criterion.py").read_bytes()).hexdigest(),
        "reference_items_sha256": reference["items_sha256"],
        "harness_control": {
            "question": "does the before arm reproduce the frozen stage-06 annotation",
            "mismatches": mismatches,
            "passed": not mismatches,
        },
        "before": before,
        "after": after,
        "delta": {
            "mislabels_before": before["mislabels"],
            "mislabels_after": after["mislabels"],
            "removed": len(fixed),
            "introduced": len(introduced),
            "introduced_rows": introduced,
            "fixed_rows": fixed,
        },
        "reference_regression": {
            "pinned": len(reference["items"]),
            "still_annotated_as_formula": len(survived),
            "lost": lost,
            "wrongly_flagged_as_mislabel": wrongly_flagged,
            "passed": not lost and not wrongly_flagged,
        },
    }
    Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print(f"harness control passed : {result['harness_control']['passed']}")
    print(f"mislabels              : {before['mislabels']} -> {after['mislabels']}"
          f"  (removed {len(fixed)}, introduced {len(introduced)})")
    print(f"paths before           : {before['by_annotation_path']}")
    print(f"paths after            : {after['by_annotation_path']}")
    print(f"reference regression   : {result['reference_regression']['passed']} "
          f"({len(survived)}/{len(reference['items'])})")
    print(f"wrote {args.out}")
    ok = (result["harness_control"]["passed"]
          and result["reference_regression"]["passed"]
          and not introduced)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
