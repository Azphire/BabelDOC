"""T1 step 2b: the reading of the step 2a list, and the determination it forces.

Step 2a measured what the declared rule catches. This is the human pass over
that catch and the decision it produces, written down so the decision is
readable rather than inferred from what shipped.

The reading splits the catch in two, on the one column step 2a reports and does
not apply: whether the panel a paragraph was found inside covers the page. A
panel covering the sheet is the page's own ground, and a paragraph is not inside
a box by being printed on the paper.

Every instance whose panel is smaller than the page is listed here with a
verdict, one of two. ``furniture`` says the paragraph really is set inside a
sidebar, an information box, a pull quote panel or an advertisement, and the
box level gate would be right to leave it alone. ``running_text`` says it is the
article's own text and the gate would be wrong.

Usage:
    python t1_boxed_review.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

MEASUREMENT = ROOT / "examples" / "output" / "b11_6" / "t1_boxed_measure.json"

VERDICT_FURNITURE = "furniture"
VERDICT_RUNNING_TEXT = "running_text"

# One verdict per instance whose panel is smaller than the page, keyed by sample
# and paragraph reference. Read off the rasters of the b10.5 on arm run and the
# excerpts the measurement carries.
REVIEW = {
    ("Courier-en", "p6#12"): (
        VERDICT_FURNITURE,
        "the tinted box on the quantum year, set apart from the article",
    ),
    ("Courier-en", "p6#13"): (
        VERDICT_FURNITURE,
        "the second paragraph of the same tinted box",
    ),
    ("Courier-zh", "p6#11"): (
        VERDICT_FURNITURE,
        "the same tinted box in the Chinese edition of the same page",
    ),
    ("Courier-zh", "p6#12"): (
        VERDICT_FURNITURE,
        "the second paragraph of that box",
    ),
    ("AramcoWorld-en-v2", "p3#13"): (
        VERDICT_FURNITURE,
        "a caption panel on the contents page",
    ),
    ("AramcoWorld-en-v2", "p3#15"): (
        VERDICT_FURNITURE,
        "the continuation of that caption panel",
    ),
    ("AramcoWorld-en-v2", "p3#16"): (
        VERDICT_FURNITURE,
        "the contents strip along the foot of the page",
    ),
    ("AramcoWorld-en-v2", "p9#15"): (
        VERDICT_FURNITURE,
        "a pull quote set in its own tint panel",
    ),
    ("AramcoWorld-en-v2", "p9#16"): (
        VERDICT_FURNITURE,
        "the attribution line of that pull quote",
    ),
    ("FD-en-v2", "p4#0"): (
        VERDICT_FURNITURE,
        "the body of a subscription advertisement panel",
    ),
    ("FD-en-v2", "p4#1"): (
        VERDICT_FURNITURE,
        "the call to action of that advertisement",
    ),
    ("FD-en-v2", "p5#27"): (
        VERDICT_FURNITURE,
        "a promotion panel on the imprint page",
    ),
    ("FD-en-v2", "p5#28"): (VERDICT_FURNITURE, "a line of that promotion panel"),
    ("FD-en-v2", "p5#33"): (VERDICT_FURNITURE, "a line of that promotion panel"),
    ("FD-en-v2", "p5#34"): (VERDICT_FURNITURE, "the address line of that panel"),
    ("FD-en-v2", "p7#6"): (
        VERDICT_FURNITURE,
        "a highlighted statement set in its own panel",
    ),
    ("FD-en-v2", "p7#27"): (VERDICT_FURNITURE, "a quotation in a tint panel"),
    ("FD-en-v2", "p7#28"): (VERDICT_FURNITURE, "its attribution line"),
    ("FD-en-v2", "p7#29"): (VERDICT_FURNITURE, "a quotation in a tint panel"),
    ("FD-en-v2", "p7#30"): (VERDICT_FURNITURE, "its attribution line"),
    ("FD-en-v2", "p7#31"): (VERDICT_FURNITURE, "a quotation in a tint panel"),
    ("FD-en-v2", "p7#32"): (VERDICT_FURNITURE, "its attribution line"),
}

DETERMINATION = (
    "The box level gate does not ship. The mechanism it rests on is sound: every "
    "one of the 22 instances whose panel is smaller than the page is furniture, "
    "and not one of them is the article's running text, so a gate that fired on "
    "those and only those would be right every time. What does not hold is the "
    "predicate as declared. The rule declares a floor on the panel's area and no "
    "ceiling, and a filled curve covering the whole sheet clears that floor by "
    "the widest margin of any panel in the corpus. So the declared rule catches "
    "230 of the corpus's 428 body paragraphs, 208 of them inside a panel that is "
    "the page's own ground -- every one of CERNCourier-en's 90 body paragraphs "
    "among them. That is the catch this step exists to look at, and it is "
    "running text, so step 2b's second branch applies: stop the sub-item, ship "
    "the page gate alone, and register the box level gate as a gap. The term "
    "that separates a panel from the paper is not written into the rule this "
    "batch was given, and writing one in here to make the number come out would "
    "be tuning a knob so that a predicted result holds, which CLAUDE.md section "
    "5.14 forbids."
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(ROOT / "examples" / "output" / "b11_6" / "t1_boxed_review.json"),
    )
    args = parser.parse_args(argv)

    with MEASUREMENT.open(encoding="utf-8") as f:
        measurement = json.load(f)

    ground = measurement["ground_ratio"]
    rows = []
    totals = {
        "body_paragraphs": 0,
        "inside": 0,
        "inside_a_full_page_panel": 0,
        "reviewed": 0,
        VERDICT_FURNITURE: 0,
        VERDICT_RUNNING_TEXT: 0,
    }
    for sample, result in measurement["samples"].items():
        if "error" in result:
            continue
        for name in ("body_paragraphs", "inside", "inside_a_full_page_panel"):
            totals[name] += result["counts"][name]
        for instance in result["instances"]:
            if instance["panel"]["page_area_ratio"] >= ground:
                continue
            key = (sample, instance["reference"])
            if key not in REVIEW:
                raise SystemExit(f"{key} is in the catch and not in the review")
            verdict, note = REVIEW[key]
            totals["reviewed"] += 1
            totals[verdict] += 1
            rows.append(
                {
                    "sample": sample,
                    "reference": instance["reference"],
                    "page_kind": instance["page_kind"],
                    "indent_eligible_page": instance["indent_eligible_page"],
                    "panel_page_area_ratio": instance["panel"]["page_area_ratio"],
                    "verdict": verdict,
                    "note": note,
                    "excerpt": instance["excerpt"],
                }
            )
    unseen = sorted(set(REVIEW) - {(row["sample"], row["reference"]) for row in rows})
    if unseen:
        raise SystemExit(f"the review rules on instances the catch does not hold: {unseen}")

    record = {
        "batch": "b11_6",
        "task": "T1 step 2b: the reading of the catch, and the determination",
        "measurement": "examples/output/b11_6/t1_boxed_measure.json",
        "ground_ratio": ground,
        "totals": totals,
        "boxed_exclusion_ships": False,
        "determination": DETERMINATION,
        "reviewed": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(totals, indent=1))
    print(f"boxed_exclusion_ships: {record['boxed_exclusion_ships']}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
