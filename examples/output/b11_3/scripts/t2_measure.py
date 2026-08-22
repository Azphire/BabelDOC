"""T2: what the criterion finds over the whole corpus, and what it costs.

Offline, zero API. Reads the frozen chain-builder checkpoints -- the stage the
translator consumes -- judges every formula composition with the T1 criterion,
and then works out, for each affected paragraph, what actually became of it by
executing the pipeline's own refusal predicates in the pipeline's own order.

Run before the repair and again after it. The criterion module is unchanged
between the two runs and the gate pins its hash, so a change in the counts is a
change in the pipeline and never a change in the question.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import inspect
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import formula_criterion as fc  # noqa: E402
import paths as pp  # noqa: E402
import walk  # noqa: E402

from babeldoc.format.pdf.document_il.utils.paragraph_helper import (  # noqa: E402
    is_cid_paragraph,
    is_placeholder_only_paragraph,
    is_pure_numeric_paragraph,
)
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402

ROOT = Path("d:/Codes/BabelDOC")
SAMPLES = ["AramcoWorld-en-v2", "CERNCourier-en", "Courier-en",
           "Courier-zh", "FD-en-v2", "Vogue-en"]

# The request-side marker a formula composition leaves behind.
FORMULA_PLACEHOLDER = re.compile(r"\{v\d+\}")

# Read from the constructor rather than restated, so the measurement cannot
# disagree with the pipeline about where the threshold is.
MIN_TEXT_LENGTH = inspect.signature(
    TranslationConfig.__init__).parameters["min_text_length"].default

REVERSE_SAMPLE_N = 30
REVERSE_SAMPLE_SEED = 20260822

SITE_I = ("il_translator_llm_only.py:641-645 -> paragraph_helper.py:69-71")
SITE_II = ("il_translator_llm_only.py:736 -> il_translator.pre_translate_paragraph")
SITE_IV = ("the paragraph was sent and its request carries no formula placeholder")

EXPOSURE = {
    "i_paragraph_refused_as_placeholder_only": SITE_I,
    "ii_sent_with_placeholders_in_the_request": SITE_II,
    "iii_not_sent_for_another_reason":
        "filled by measurement; the site is recorded on each row",
    "iv_no_observable_consequence": SITE_IV,
}


def tracking_index(sample: str) -> dict:
    """Source text to the records of what was asked and what came back.

    The tracking file has three roots and a paragraph may sit under any of
    them; the caption paragraph this batch follows sits under cross_column.
    """
    path = (ROOT / "examples" / "output" / "b10_5" / sample / "on" / "work"
            / sample / "translate_tracking.json")
    index = collections.defaultdict(list)
    if not path.exists():
        return index
    data = json.loads(path.read_text(encoding="utf-8"))
    for root in ("page", "cross_page", "cross_column"):
        for group in data.get(root) or []:
            for para in group.get("paragraph") or []:
                index[para.get("pdf_unicode") or ""].append(
                    {"root": root, "input": para.get("input") or "",
                     "output": para.get("output") or ""})
    return index


def fate(paragraph, index):
    """Which of the four exposure classes the paragraph fell into, and where."""
    if is_cid_paragraph(paragraph):
        return ("iii_not_sent_for_another_reason",
                "il_translator_llm_only.py:626-630 is_cid_paragraph", {})
    if len(paragraph.unicode or "") < MIN_TEXT_LENGTH:
        return ("iii_not_sent_for_another_reason",
                "il_translator_llm_only.py:631-635 min_text_length="
                f"{MIN_TEXT_LENGTH}", {})
    if is_pure_numeric_paragraph(paragraph):
        return ("iii_not_sent_for_another_reason",
                "il_translator_llm_only.py:636-640 is_pure_numeric_paragraph", {})
    if is_placeholder_only_paragraph(paragraph):
        return ("i_paragraph_refused_as_placeholder_only", SITE_I, {})
    if paragraph.vertical:
        return ("iii_not_sent_for_another_reason",
                "il_translator.py:1043-1044 pre_translate_paragraph returns on "
                "paragraph.vertical", {})
    records = index.get(paragraph.unicode or "")
    if not records:
        return ("iii_not_sent_for_another_reason",
                "no request was recorded for this paragraph, and no predicate "
                "this measurement executes refused it", {})
    with_ph = [r for r in records if FORMULA_PLACEHOLDER.search(r["input"])]
    if with_ph:
        return ("ii_sent_with_placeholders_in_the_request", SITE_II,
                {"request": with_ph[0]["input"][:200],
                 "reply": with_ph[0]["output"][:200],
                 "ambiguous_join": len(records) > 1})
    return ("iv_no_observable_consequence", SITE_IV,
            {"request": records[0]["input"][:200],
             "ambiguous_join": len(records) > 1})


def measure(arm_dir):
    config = fc.load_config()
    rows, clean = [], []
    per_sample = collections.Counter()
    per_label = collections.Counter()
    per_class = collections.Counter()
    per_path = collections.Counter()

    for sample in SAMPLES:
        base = (arm_dir / sample if arm_dir else
                ROOT / "examples" / "output" / "b10_5" / sample / "on" / "work"
                / sample)
        checkpoint = base / "checkpoint.08_chain_builder.xml"
        index = tracking_index(sample)
        doc = load_checkpoint(checkpoint)
        for page in doc.page:
            table = walk.font_table(page)
            for slot, para in enumerate(page.pdf_paragraph or []):
                flagged = []
                for cslot, comp in enumerate(para.pdf_paragraph_composition or []):
                    if not comp.pdf_formula:
                        continue

                    def font_of(char, _t=table, _x=para.xobj_id):
                        return (walk.resolve(_t, _x, char.pdf_style.font_id)
                                if char.pdf_style else None)

                    chars = comp.pdf_formula.pdf_character or []
                    fonts = {font_of(c) for c in chars}
                    fonts.discard(None)
                    verdict = fc.evaluate(comp.pdf_formula, fonts, config)
                    if verdict.is_mislabel:
                        flagged.append((cslot, verdict, comp.pdf_formula, font_of))
                    else:
                        clean.append({
                            "sample": sample, "page": page.page_number + 1,
                            "anchor": f"p{page.page_number + 1}#{slot}",
                            "composition_slot": cslot, "text": verdict.text,
                            "reason": verdict.reason,
                            "exemption": verdict.exemption,
                            "longest_letter_run": verdict.longest_letter_run,
                            "math_ratio": verdict.math_ratio})
                if not flagged:
                    continue
                klass, site, extra = fate(para, index)
                per_class[klass] += len(flagged)
                per_sample[sample] += len(flagged)
                per_label[para.layout_label or "(none)"] += len(flagged)
                for cslot, verdict, formula, font_of in flagged:
                    tally = pp.attribute(formula, font_of)
                    branch = pp.dominant(tally)
                    per_path[branch] += 1
                    row = {
                        "sample": sample, "page": page.page_number + 1,
                        "anchor": f"p{page.page_number + 1}#{slot}",
                        # minted per run; carried for tracing, never asserted on
                        "debug_id_this_run": para.debug_id,
                        "composition_slot": cslot,
                        "composition_type": "pdf_formula",
                        "paragraph_label": para.layout_label,
                        "paragraph_vertical": bool(para.vertical),
                        "text": verdict.text,
                        "paragraph_excerpt": (para.unicode or "")[:120],
                        "conditions_met": {
                            "longest_letter_run": verdict.longest_letter_run,
                            "letter_ratio": verdict.letter_ratio,
                            "math_ratio": verdict.math_ratio,
                            "exemption": verdict.exemption},
                        "annotation_path": branch,
                        "annotation_path_tally": tally,
                        "exposure_class": klass,
                        "exposure_site": site,
                    }
                    row.update(extra)
                    rows.append(row)

    # The same exposure counted by paragraph rather than by composition. A
    # paragraph is the unit the translator accepts or refuses, so this is the
    # number that says how much text the annotation costs.
    by_para = collections.defaultdict(set)
    for row in rows:
        by_para[row["exposure_class"]].add((row["sample"], row["anchor"]))
    affected = set().union(*by_para.values()) if by_para else set()
    paragraphs = {
        "distinct_affected": len(affected),
        "by_class": {k: len(v) for k, v in sorted(by_para.items())},
        "by_sample": dict(collections.Counter(s for s, _ in affected)),
    }

    rng = random.Random(REVERSE_SAMPLE_SEED)
    drawn = rng.sample(clean, min(REVERSE_SAMPLE_N, len(clean)))

    return {
        "criterion_sha256": hashlib.sha256(
            (HERE / "formula_criterion.py").read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(
            (HERE.parent / "criterion_config.json").read_bytes()).hexdigest(),
        "read_from": (str(arm_dir) if arm_dir else
                      "examples/output/b10_5/<sample>/on/work/<sample>"),
        "stage": "checkpoint.08_chain_builder.xml",
        "min_text_length_in_force": MIN_TEXT_LENGTH,
        "totals": {"mislabels": len(rows),
                   "formula_compositions_not_flagged": len(clean)},
        "by_sample": dict(per_sample),
        "by_paragraph_label": dict(per_label),
        "by_annotation_path": dict(per_path),
        "exposure": {"counts": dict(per_class), "sites": EXPOSURE,
                     "paragraphs": paragraphs},
        "reverse_sample": {"n": len(drawn), "seed": REVERSE_SAMPLE_SEED,
                           "drawn_from": len(clean), "rows": drawn},
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm-dir", default=None,
                    help="working directory of a run to measure; the default is "
                         "the frozen b10.5 on arm")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = measure(Path(args.arm_dir) if args.arm_dir else None)
    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"mislabels: {result['totals']['mislabels']}")
    print(f"exposure : {result['exposure']['counts']}")
    print(f"paths    : {result['by_annotation_path']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
