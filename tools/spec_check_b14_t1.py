"""Gate: a rendered initial's ink starts where the source initial's ink did.

B13's outputs anchored the target initial at the source metric box top, so the
glyph floated the whole ascent whitespace above the source ink (18.5 pt on
Courier p4, 17.75 pt on p5). B14 captures the source ink offset at mark time
and moves the grid down by it; this gate measures the finished pages rather
than trusting the report that claims they moved.

Claims:

S1  No color component literal lives in the magazine code. The drop cap's
    color is resolved per document from the source stream, and stays that
    way: no three-float tuple and no literal fill/stroke instruction string
    appears anywhere under babeldoc/magazine.
S2  Every drop cap intent in a run's report carries a fill with an evidence
    chain, and every named color space in that chain resolved to a device
    space rather than falling back silently.
S3  On the finished pages, each committed initial's ink top sits within
    ANCHOR_INK_TOP_TOLERANCE_PT of the source initial's ink top, measured in
    pixels at 288 dpi in the initial's own column of the page.

Usage:
    python tools/spec_check_b14_t1.py [<work_dir> <output_pdf>]...

S1 always runs. S2 and S3 run once per (work_dir, output_pdf) pair; the
source is <work_dir>/input.pdf.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The pixel gate's threshold, named once. The plan's T1 gate: rendered ink top
# within 1 pt of the source ink top on every committed initial.
ANCHOR_INK_TOP_TOLERANCE_PT = 1.0
MEASURE_DPI = 288
# The probe window opens just above the reported initial box and runs to its
# bottom. A floated output tops the window while the source ink sits lower
# inside it; an overshot output leaves the source ink above the window, whose
# clipped measurement still lands past the tolerance. Either defect fails.
PROBE_ABOVE_PT = 2.0
# A flat fill renders its exact color, so the probe accepts only a near-exact
# match: wide enough for rounding through the report's three decimals, narrow
# enough that a nearby element in a merely similar color cannot stand in for
# the initial (Courier p4 has a band 9/7/21 channels away from its own cap).
COLOR_CHANNEL_TOLERANCE = 6

FLOAT_TRIPLE = re.compile(
    r"\(\s*[01]?\.[0-9]+\s*,\s*[01]?\.[0-9]+\s*,\s*[01]?\.[0-9]+\s*\)"
)
LITERAL_INSTRUCTION = re.compile(
    r"\"[0-9]*\.?[0-9]+ [0-9]*\.?[0-9]+( [0-9]*\.?[0-9]+)+ (rg|RG|k|K|g|G)\b"
)
DEVICE_SPACES = {"DeviceGray", "DeviceRGB", "DeviceCMYK"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def s1_no_color_literals() -> str:
    offenders = []
    for path in sorted((ROOT / "babeldoc" / "magazine").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in (FLOAT_TRIPLE, LITERAL_INSTRUCTION):
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(ROOT)}:{line}:{match.group(0)}")
    _require(not offenders, "color-like literals in code: " + "; ".join(offenders))
    return "no color component literal under babeldoc/magazine"


def s2_color_evidence_chains(work: Path) -> str:
    report = json.loads(
        (work / "drop_cap_intent.report.json").read_text(encoding="utf-8")
    )
    intents = report.get("intents", [])
    _require(bool(intents), f"{work}: no drop cap intents to check")
    for intent in intents:
        ref = intent.get("source_ref")
        color = intent.get("source_color") or {}
        fill = color.get("fill") or {}
        evidence = color.get("evidence") or []
        _require(
            isinstance(fill.get("rgb"), list) and len(fill["rgb"]) == 3,
            f"{ref}: fill carries no rgb",
        )
        _require(
            any(str(item).startswith("fill:") for item in evidence),
            f"{ref}: evidence chain has no fill entry",
        )
        for item in evidence:
            named = re.match(r"cs:/(.+)$", str(item))
            if named is None or named.group(1) in DEVICE_SPACES:
                continue
            _require(
                any(
                    str(entry).startswith(f"resolve:/{named.group(1)}->")
                    for entry in evidence
                ),
                f"{ref}: named space /{named.group(1)} never resolved",
            )
    return f"{len(intents)} intent(s) carry resolved fill evidence chains"


def _ink_top(page, x0: float, x1: float, y_top: float, y_bottom: float, rgb):
    import pymupdf

    scale = MEASURE_DPI / 72.0
    clip = pymupdf.Rect(x0, y_top, x1, y_bottom)
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), clip=clip, colorspace=pymupdf.csRGB
    )
    want = [round(value * 255) for value in rgb]
    buf, n = pix.samples, pix.n
    for row in range(pix.height):
        base = row * pix.stride
        for col in range(pix.width):
            offset = base + col * n
            if all(
                abs(buf[offset + channel] - want[channel]) <= COLOR_CHANNEL_TOLERANCE
                for channel in range(3)
            ):
                return y_top + row / scale
    return None


def s3_ink_tops_align(work: Path, output_pdf: Path) -> str:
    import pymupdf

    render = json.loads(
        (work / "drop_cap_render.report.json").read_text(encoding="utf-8")
    )
    intents = {
        intent["source_ref"]: intent
        for intent in json.loads(
            (work / "drop_cap_intent.report.json").read_text(encoding="utf-8")
        ).get("intents", [])
    }
    committed = [
        row
        for row in render.get("paragraphs", [])
        if row.get("status") == "committed" and row.get("initial_box")
    ]
    _require(bool(committed), f"{work}: no committed initial to measure")
    source_doc = pymupdf.open(str(work / "input.pdf"))
    output_doc = pymupdf.open(str(output_pdf))
    checked = []
    for row in committed:
        ref = row["source_ref"]
        page_number = int(ref.split("#")[0][1:])
        intent = intents.get(ref)
        _require(intent is not None, f"{ref}: committed row without an intent")
        rgb = intent["source_color"]["fill"]["rgb"]
        box = row["initial_box"]
        page_height = float(source_doc[page_number - 1].rect.height)
        x0, x1 = float(box[0]), float(box[2])
        top_td = page_height - float(box[3])
        bottom_td = page_height - float(box[1])
        window = (x0, x1, top_td - PROBE_ABOVE_PT, bottom_td)
        source_top = _ink_top(source_doc[page_number - 1], *window[:2], *window[2:], rgb)
        output_top = _ink_top(output_doc[page_number - 1], *window[:2], *window[2:], rgb)
        _require(source_top is not None, f"{ref}: no source ink in the probe window")
        _require(output_top is not None, f"{ref}: no output ink in the probe window")
        difference = output_top - source_top
        _require(
            abs(difference) <= ANCHOR_INK_TOP_TOLERANCE_PT,
            f"{ref}: output ink top differs from source by {difference:+.2f} pt "
            f"(source {source_top:.2f}, output {output_top:.2f})",
        )
        checked.append(f"{ref}:{difference:+.2f}pt")
    return "ink tops align: " + ", ".join(checked)


def main(argv: list[str]) -> int:
    pairs = [
        (Path(argv[index]), Path(argv[index + 1]))
        for index in range(0, len(argv), 2)
    ]
    claims = [("S1", s1_no_color_literals)]
    for work, output_pdf in pairs:
        claims.append(("S2", lambda w=work: s2_color_evidence_chains(w)))
        claims.append(
            ("S3", lambda w=work, o=output_pdf: s3_ink_tops_align(w, o))
        )
    failures = 0
    for name, claim in claims:
        try:
            print(f"{name}  OK  {claim()}")
        except AssertionError as error:
            print(f"{name}  FAIL  {error}")
            failures += 1
    if failures:
        return 1
    print("spec_check_b14_t1: all claims hold")
    return 0


if __name__ == "__main__":
    if len(sys.argv[1:]) % 2 != 0:
        print("usage: spec_check_b14_t1.py [<work_dir> <output_pdf>]...")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
