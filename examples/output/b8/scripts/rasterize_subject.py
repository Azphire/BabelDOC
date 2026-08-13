"""B8.3 rendering evidence: the disputed strip as the produced PDF draws it.

Every other measurement in this batch is taken on the intermediate language or
on extracted text, both of which are what the pipeline believes it produced.
This one is taken on pixels, which is what a reader gets. It crops the region a
finding's geometry names out of the finished page and writes it as a PNG, plus
the whole page for context.

The geometry is the finding's own, read from the detection sidecar, so the crop
is the region the detector was talking about and not one chosen by eye. The
intermediate language measures from the bottom left of the page and the raster
from the top left, so the box is flipped once here; the margin around it is a
viewing convenience and is stated rather than hidden.

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
from babeldoc.magazine import detectors  # noqa: E402

B8_DIR = ROOT / "examples" / "output" / "b8"
SMOKE_DIR = B8_DIR / "smoke"
RASTER_DIR = SMOKE_DIR / "raster"

SAMPLE = "Courier-en"
SUBJECT = "p6#15"

# Points added on each side of the finding's box, so the strip is readable
# against what stands beside it rather than cropped to its own edges.
MARGIN_POINTS = 18.0

# Raster scale. Four device pixels per point, which is legible for a strip set
# at caption size without producing a file nobody can open.
SCALE = 4.0


def subject_geometry(working: Path) -> tuple[int, dict]:
    with (working / detectors.REPORT_NAME).open(encoding="utf-8") as f:
        report = json.load(f)
    for issue in report.get("issues", ()):
        if SUBJECT in issue.get("paragraph_refs", ()):
            return int(issue["page"]), issue["geometry"]
    raise SystemExit(f"{SUBJECT} carries no finding in {detectors.REPORT_NAME}")


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
        crop_path = RASTER_DIR / f"{stem}.{SUBJECT.replace('#', '_')}.png"
        crop.save(crop_path)
        written.append(crop_path)
    return written


def main() -> int:
    working = SMOKE_DIR / SAMPLE / "work" / SAMPLE
    page_label, geometry = subject_geometry(working)
    RASTER_DIR.mkdir(parents=True, exist_ok=True)

    produced = SMOKE_DIR / f"{SAMPLE}.b8_3.pdf"
    previous = ROOT / "examples" / "output" / "b7_5" / f"{SAMPLE}.pass2.pdf"
    written = render(produced, page_label, geometry, "b8_3")
    written += render(previous, page_label, geometry, "b7_5_2")

    print(json.dumps({
        "page": page_label,
        "geometry": geometry,
        "margin_points": MARGIN_POINTS,
        "scale": SCALE,
        "files": [str(path.relative_to(ROOT)) for path in written],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
