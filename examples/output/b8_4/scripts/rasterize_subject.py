"""B8.4 rendering evidence: two paragraphs, as the produced PDFs draw them.

Pixels, which is what a reader gets, against the intermediate language, which
is what the pipeline believes it produced. Two regions are cropped out of this
batch's PDF and out of the previous batch's, at the same box in both so the
pair compares:

The subject of the whole B8 line, the rotated credit strip. Its repair was
requested with the line in its reading order for the first time and refused at
the write-back, because the rendering would not have fitted the strip. So the
two crops have to be identical, and that identity is the evidence that a
refusal is a refusal.

The paragraph a repair did land on, which is where the pair has to differ. The
box is the same in both crops because a landed repair does not move one; what
changed inside it is the text.

The region for each is the paragraph's box before the loop ran, taken from the
driver's snapshot: a repair that resolved its finding leaves no finding to read
a geometry from, and the box before is the region worth looking at either way.
The intermediate language measures from the bottom left of the page and the
raster from the top left, so the box is flipped once here; the margin around it
is a viewing convenience and is stated rather than hidden.

Usage:
    python rasterize_subject.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402

BATCH_DIR = ROOT / "examples" / "output" / "b8_4"
SMOKE_DIR = BATCH_DIR / "smoke"
RASTER_DIR = SMOKE_DIR / "raster"
PREVIOUS_DIR = ROOT / "examples" / "output" / "b8" / "smoke"

PARAGRAPHS_NAME = "paragraphs.json"

# The rotated credit strip two batches have been about.
SUBJECT_SAMPLE = "Courier-en"
SUBJECT = "p6#15"

# Points added on each side of the box, so a strip is readable against what
# stands beside it rather than cropped to its own edges.
MARGIN_POINTS = 18.0

# Four device pixels per point, which is legible for a line set at caption size
# without producing a file nobody can open.
SCALE = 4.0


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def landed() -> list[tuple[str, str]]:
    """Every paragraph a repair landed on in this batch, sample and reference."""
    found: list[tuple[str, str]] = []
    for row in load(SMOKE_DIR / "runs.json"):
        sample = Path(row["sample"]).stem
        repair = load(ROOT / row["working_dir"] / controller.REPORT_NAME)
        for reference in repair["conservation"]["touched_refs"]:
            found.append((sample, reference))
    return found


def box_before(sample: str, reference: str) -> tuple[int, dict]:
    snapshot = load(SMOKE_DIR / sample / PARAGRAPHS_NAME)
    box = (snapshot["before"].get(reference) or {}).get("box")
    if box is None:
        raise SystemExit(f"{sample} {reference}: no box in the snapshot")
    page_label = int(reference.split("#")[0][1:])
    return page_label, {"x": box[0], "y": box[1], "x2": box[2], "y2": box[3]}


def render(pdf_path: Path, page_label: int, geometry: dict, stem: str) -> list[Path]:
    written = []
    with pymupdf.open(pdf_path) as document:
        page = document[page_label - 1]
        height = page.rect.height
        full = page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE))
        full_path = RASTER_DIR / f"{stem}.page{page_label}.png"
        full.save(full_path)
        written.append(full_path)

        clip = pymupdf.Rect(
            geometry["x"] - MARGIN_POINTS,
            height - geometry["y2"] - MARGIN_POINTS,
            geometry["x2"] + MARGIN_POINTS,
            height - geometry["y"] + MARGIN_POINTS,
        ) & page.rect
        crop = page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), clip=clip)
        crop_path = RASTER_DIR / f"{stem}.png"
        crop.save(crop_path)
        written.append(crop_path)
    return written


def pair(sample: str, reference: str) -> list[Path]:
    page_label, geometry = box_before(sample, reference)
    tail = reference.replace("#", "_")
    written = render(
        SMOKE_DIR / f"{sample}.b8_4.pdf",
        page_label,
        geometry,
        f"b8_4.{tail}",
    )
    written += render(
        PREVIOUS_DIR / f"{sample}.b8_3.pdf",
        page_label,
        geometry,
        f"b8_3.{tail}",
    )
    return written


def main() -> int:
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    subjects = [(SUBJECT_SAMPLE, SUBJECT), *landed()]
    written: list[Path] = []
    for sample, reference in subjects:
        written += pair(sample, reference)
    print(
        json.dumps(
            {
                "subjects": [
                    {"sample": sample, "reference": reference}
                    for sample, reference in subjects
                ],
                "margin_points": MARGIN_POINTS,
                "scale": SCALE,
                "files": [str(path.relative_to(ROOT)) for path in written],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
