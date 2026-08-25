"""The three write back sites T3.4 asked about, each answered from the tree.

The plan asked whether a rotated paragraph's translation can be written back
with its source rotation, and required the question be settled site by site
before anything was built: the character matrix, the packer's handling of a
rotated box, and the renderer's consumption of the matrix. What follows is what
each of the three was found to do, with the evidence read out of the source
rather than remembered, and what the lane does about it.

Writes ``examples/output/b11_7/t3_lane_feasibility.json``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parents[1] / "t3_lane_feasibility.json"

TYPESETTING = ROOT / "babeldoc" / "format" / "pdf" / "document_il" / "midend" / "typesetting.py"
RENDERER = ROOT / "babeldoc" / "format" / "pdf" / "document_il" / "backend" / "pdf_creater.py"
IL = ROOT / "babeldoc" / "format" / "pdf" / "document_il" / "il_version_1.py"

# The matrix the writer emits for a character marked vertical: a quarter turn
# anticlockwise, anchored at the character box's right hand edge and bottom.
ROTATION = "0 1 -1 0"


def lines_matching(path: Path, pattern: str) -> list[dict]:
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(pattern, line):
            out.append(
                {
                    "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "line": number,
                    "source": line.strip(),
                }
            )
    return out


def main() -> int:
    source = TYPESETTING.read_text(encoding="utf-8")
    packer = source.split("def _layout_typesetting_units", 1)[1].split("\n    def ", 1)[0]

    sites = {
        "character_matrix": {
            "question": "Can a character the stage creates from translated text "
            "carry the source rotation?",
            "carries": False,
            "evidence": lines_matching(TYPESETTING, r"vertical=False,"),
            "detail": (
                "The stage constructs every character it creates from a "
                "translated string with vertical hardcoded false. The two "
                "branches that carry a source character or a formula's "
                "characters through do copy the flag, so the flag itself is "
                "live in the intermediate language; it is only the newly set "
                "text that loses it."
            ),
            "what_the_lane_does": (
                "Sets the flag itself, on exactly the characters it has just "
                "placed. The upstream line is deliberately left alone: making "
                "the stage inherit the paragraph's flag would mark every "
                "character of every rotated paragraph, including the ones the "
                "lane never claimed and the stage laid out horizontally, and "
                "those would then be drawn rotated at horizontal positions. "
                "The narrower change is the correct one, and it needs no "
                "upstream edit at all."
            ),
        },
        "packer": {
            "question": "Can the packer lay text out along the vertical axis?",
            "carries": False,
            "evidence": [
                {
                    "file": "babeldoc/format/pdf/document_il/midend/typesetting.py",
                    "line": None,
                    "source": "_layout_typesetting_units names no axis: "
                    f"'axis' in the function = {'axis' in packer}; "
                    "the line end test is "
                    f"{'current_x + unit_width > box.x2' in packer}",
                }
            ],
            "detail": (
                "Every geometric decision in the packer is written with x as "
                "the line and y as the column: the cursor, the space width, "
                "the hanging punctuation overflow measured past box.x2, the "
                "retreat that undoes a hung run, and the first line indent "
                "added to the cursor. Threading an axis through all of it is a "
                "rewrite of a stage this project does not own."
            ),
            "what_the_lane_does": (
                "Hands it the paragraph's box with the two axes exchanged and "
                "rotates the result. The packer is neither modified nor "
                "bypassed: it does its own line breaking with the real mapped "
                "font, in a box whose width is the strip's length, and what "
                "comes back is mapped onto the strip. This is the plan's "
                "transposed box, and it buys the real font advances that a "
                "hand rolled fitter would have had to estimate."
            ),
        },
        "renderer": {
            "question": "Does the writer draw a character marked vertical "
            "rotated, and with which matrix?",
            "carries": True,
            "evidence": lines_matching(RENDERER, re.escape(ROTATION)),
            "detail": (
                f"Both of the writer's character paths emit {ROTATION!r} for a "
                "character marked vertical, anchored at the character box's "
                "x2 and y. Under that matrix the pen advances up the page and "
                "the ascent runs to the left, which is what the lane maps its "
                "characters into."
            ),
            "what_the_lane_does": (
                "Nothing. The renderer is untouched and carries the rotation "
                "as it always has."
            ),
        },
    }

    # What the intermediate language can express about rotation, which is what
    # decides whether "take the source rotation" means anything.
    il_source = IL.read_text(encoding="utf-8")
    rotation_fields = sorted(
        {
            match
            for match in re.findall(r"^\s+(vertical|rotation|matrix)\s*:", il_source, re.M)
        }
    )

    payload = {
        "batch": "b11.7",
        "sites": sites,
        "verdict": "feasible",
        "verdict_detail": (
            "Two of the three sites do not carry it and one does. Neither of "
            "the two needs an upstream change: the character flag is set by "
            "the lane on the characters it placed, and the packer is given a "
            "transposed box rather than an axis. So the lane is built, and it "
            "is built narrow -- it claims only a paragraph set along the "
            "vertical axis whose text a repair has just replaced."
        ),
        "rotation_expressible_in_il": rotation_fields,
        "per_char_source_matrix": {
            "asked_for_by": "the initial plan, as 'per-char matrix takes the "
            "source rotation'",
            "available": False,
            "detail": (
                "The intermediate language carries a boolean and no matrix, "
                "and the schema is frozen. The writer expands that boolean "
                f"into the single matrix {ROTATION!r}. So 'the source "
                "rotation' has exactly one value it can take, and a paragraph "
                "rotated any other way cannot enter the lane -- which is "
                "registered rather than silently mishandled."
            ),
        },
    }
    OUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for name, site in sites.items():
        print(f"{name}: carries={site['carries']} evidence={len(site['evidence'])}")
    print(f"verdict: {payload['verdict']}")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
