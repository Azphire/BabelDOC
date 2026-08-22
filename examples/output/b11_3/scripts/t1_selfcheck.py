"""T1: the annotation-path table, the criterion, and its self-check.

Zero API, zero pipeline changes. Reads the frozen b10.5 on-arm stage-06
checkpoints and writes t1_formula_criterion.json.

The reference sets below are anchored by sample, one-based page and the
composition's own text. No debug_id appears here: those are minted per run
(CLAUDE.md 5.13).
"""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import formula_criterion as fc  # noqa: E402
import paths as pp  # noqa: E402
import walk  # noqa: E402

ROOT = Path("d:/Codes/BabelDOC")
BASELINE = ROOT / "examples" / "output" / "b10_5"
SAMPLES = ["AramcoWorld-en-v2", "CERNCourier-en", "Courier-en",
           "Courier-zh", "FD-en-v2", "Vogue-en"]

# Hand-picked by reading the text, not by what the criterion says about it.
# These are genuine formula annotations: the criterion must leave them alone.
GENUINE = [
    ("CERNCourier-en", 3, "6 \u00d7 1012 ", "six times ten to the twelfth"),
    ("CERNCourier-en", 3, "4 \u00d7 108", "four times ten to the eighth"),
    ("CERNCourier-en", 3, "7 \u00d7 106 ", "seven times ten to the sixth"),
    ("CERNCourier-en", 4, "3 + 3 ", "arithmetic expression"),
    ("CERNCourier-en", 1, "\uf06c   ", "private-use dingbat glyph"),
    ("CERNCourier-en", 4, "\uf06c", "private-use dingbat glyph"),
    ("CERNCourier-en", 2, "\u2022 ", "bullet"),
    ("Courier-en", 2, "\u2022 ", "bullet"),
    ("Vogue-en", 3, "+", "bare mathematical operator"),
    ("AramcoWorld-en-v2", 3, "(cid:23)(cid:19) ", "undecodable CID glyph run"),
    ("AramcoWorld-en-v2", 5, "(cid:20)(cid:20)", "undecodable CID glyph run"),
]

# Genuine mislabels, likewise hand-picked: ordinary running text. Drawn from
# every sample, so that the criterion is not demonstrated on one publication.
MISLABELS = [
    ("FD-en-v2", 5, "MANAGING EDITOR", "masthead heading, formula font"),
    ("FD-en-v2", 5, "EDITOR-IN-CHIEF", "masthead heading, formula font"),
    ("FD-en-v2", 9, "buttercup", "caption word, formula font"),
    ("FD-en-v2", 2, "STAU", "rotated photo credit"),
    ("CERNCourier-en", 2, "olume 66 ", "small-caps volume line, corner-mark path"),
    ("CERNCourier-en", 2, "P Dinault/CERN", "rotated photo credit"),
    ("AramcoWorld-en-v2", 3, "cCARRON", "rotated photo credit"),
    ("Courier-en", 3, "brano", "rotated photo credit"),
    ("Courier-zh", 5, "Adriano Gam", "rotated photo credit"),
    ("Vogue-en", 1, "I BOUTIQ", "rotated boutique credit"),
]


# The eleven units b11.2 traced to the formula annotation, anchored by sample,
# one-based page and the paragraph's own source text. The vertical eleventh of
# that batch's class C is not here: it is refused at the vertical guard in
# pre_translate_paragraph, not by the annotation, and is out of this batch.
IN_SCOPE = [
    ("FD-en-v2", 5, "EDITOR-IN-CHIEF Gita Bhatt", "C"),
    ("FD-en-v2", 5, "MANAGING EDITOR Nicholas Owen", "C"),
    ("FD-en-v2", 5, "SENIOR EDITORS Andreas Adriano Jeff Kearns Peter Walker", "C"),
    ("FD-en-v2", 5, "ASSISTANT EDITOR Andrew Stanley", "C"),
    ("FD-en-v2", 2, "FFER STAU N BRIA", "C"),
    ("FD-en-v2", 3, "FFER STAU N BRIA", "C"),
    ("FD-en-v2", 8, "L H RU KIM RTESY U O C", "C"),
    ("FD-en-v2", 9, "K N BA L A N ATIO N ISS SW RTESY U O C", "C"),
    ("FD-en-v2", 9,
     "A glacier buttercup appears on the front of the draft 1,000 franc note.", "D"),
]
# Two masthead headings whose stage-06 paragraph text begins with the heading but
# is matched on the heading alone, because the trailing names differ in spacing.
IN_SCOPE_PREFIX = [
    ("FD-en-v2", 5, "CREATIVE AND MARKETING", "C"),
    ("FD-en-v2", 5, "ART DIRECTION AND DESIGN", "C"),
]


def collect() -> dict:
    config = fc.load_config()
    rows = {}
    for sample in SAMPLES:
        cp = (BASELINE / sample / "on" / "work" / sample
              / "checkpoint.06_styles_and_formulas.xml")
        rows[sample] = list(walk.walk(cp, config))
    return rows


def lookup(rows, sample, page, text):
    return [r for r in rows[sample] if r["page"] == page and r["text"] == text]


def main() -> int:
    config = fc.load_config()
    rows = collect()

    genuine, genuine_faults = [], []
    for sample, page, text, why in GENUINE:
        hits = lookup(rows, sample, page, text)
        if not hits:
            genuine_faults.append(f"reference not found: {sample} p{page} {text!r}")
            continue
        hit = hits[0]
        genuine.append({"sample": sample, "page": page, "text": text,
                        "why_genuine": why, "is_mislabel": hit["is_mislabel"],
                        "reason": hit["reason"],
                        "longest_letter_run": hit["longest_letter_run"],
                        "math_ratio": hit["math_ratio"]})
        if hit["is_mislabel"]:
            genuine_faults.append(f"a genuine formula was called a mislabel: "
                                  f"{sample} p{page} {text!r}")

    mislabels, mislabel_faults = [], []
    for sample, page, text, why in MISLABELS:
        hits = lookup(rows, sample, page, text)
        if not hits:
            mislabel_faults.append(f"reference not found: {sample} p{page} {text!r}")
            continue
        hit = hits[0]
        mislabels.append({"sample": sample, "page": page, "text": text,
                          "why_mislabel": why, "is_mislabel": hit["is_mislabel"],
                          "reason": hit["reason"],
                          "longest_letter_run": hit["longest_letter_run"],
                          "letter_ratio": hit["letter_ratio"]})
        if not hit["is_mislabel"]:
            mislabel_faults.append(f"a mislabel was missed: {sample} p{page} {text!r}")

    # Which branch of the annotation disjunction produced each mislabel.
    import collections
    from babeldoc.magazine.checkpoint import load_checkpoint
    attribution = collections.Counter()
    per_sample = collections.defaultdict(collections.Counter)
    in_scope_rows = []
    for sample in SAMPLES:
        cp = (BASELINE / sample / "on" / "work" / sample
              / "checkpoint.06_styles_and_formulas.xml")
        doc = load_checkpoint(cp)
        for page in doc.page:
            table = walk.font_table(page)
            for para in page.pdf_paragraph or []:
                text = para.unicode or ""
                wanted = [(s2, p2, t2, k) for (s2, p2, t2, k) in IN_SCOPE
                          if s2 == sample and p2 == page.page_number + 1 and t2 == text]
                wanted += [(s2, p2, t2, k) for (s2, p2, t2, k) in IN_SCOPE_PREFIX
                           if s2 == sample and p2 == page.page_number + 1
                           and text.startswith(t2)]
                para_tally = collections.Counter()
                para_mislabels = 0
                for comp in para.pdf_paragraph_composition or []:
                    if not comp.pdf_formula:
                        continue

                    def font_of(char, _t=table, _x=para.xobj_id):
                        return (walk.resolve(_t, _x, char.pdf_style.font_id)
                                if char.pdf_style else None)

                    fonts = {font_of(c) for c in (comp.pdf_formula.pdf_character or [])}
                    fonts.discard(None)
                    if not fc.evaluate(comp.pdf_formula, fonts, config).is_mislabel:
                        continue
                    tally = pp.attribute(comp.pdf_formula, font_of)
                    branch = pp.dominant(tally)
                    attribution[branch] += 1
                    per_sample[sample][branch] += 1
                    para_tally[branch] += 1
                    para_mislabels += 1
                for s2, p2, t2, kind in wanted:
                    in_scope_rows.append({
                        "sample": s2, "page": p2, "anchor_text": t2,
                        "b11_2_class": kind,
                        "compositions_all_formula": all(
                            c.pdf_formula for c in (para.pdf_paragraph_composition or [])),
                        "mislabelled_compositions": para_mislabels,
                        "dominant_path": (para_tally.most_common(1)[0][0]
                                          if para_tally else None),
                        "paths": dict(para_tally)})

    totals = {s: {"compositions": len(r),
                  "mislabels": sum(1 for x in r if x["is_mislabel"])}
              for s, r in rows.items()}

    out = {
        "criterion": config,
        "criterion_sha256": hashlib.sha256(
            (HERE / "formula_criterion.py").read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(
            (HERE.parent / "criterion_config.json").read_bytes()).hexdigest(),
        "read_from": "examples/output/b10_5/<sample>/on/work/<sample>"
                     "/checkpoint.06_styles_and_formulas.xml",
        "self_check": {
            "genuine_formulas": genuine,
            "genuine_faults": genuine_faults,
            "mislabel_examples": mislabels,
            "mislabel_faults": mislabel_faults,
            "passed": not genuine_faults and not mislabel_faults,
        },
        "corpus_totals": totals,
        "path_attribution": {
            "over_all_mislabels": dict(attribution),
            "per_sample": {s: dict(c) for s, c in per_sample.items()},
            "note": "the branch explaining the most characters of the composition; "
                    "see annotation_paths.json for what each branch is",
        },
        "in_scope_attribution": in_scope_rows,
        "known_boundary_misses": {
            "statement": "cases the criterion does not flag although the text is "
                         "ordinary. Recorded here rather than repaired, because the "
                         "thresholds were fixed before any measurement was taken and "
                         "moving them afterwards is what this batch's plan forbids.",
            "short_fragments": "the rotated credits are cut into compositions of two "
                               "and three letters, which fall under min_word_len and "
                               "so are not each flagged, although the longer fragments "
                               "of the same credit are",
            "one_symbol_is_enough": "a composition of ordinary words carrying a single "
                                    "character in a mathematical category is exempted "
                                    "by max_math_ratio",
        },
    }
    path = HERE.parent / "t1_formula_criterion.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"self-check passed: {out['self_check']['passed']}")
    for f in genuine_faults + mislabel_faults:
        print(f"  FAULT: {f}")
    print(f"wrote {path.relative_to(ROOT)}")
    return 0 if out["self_check"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
