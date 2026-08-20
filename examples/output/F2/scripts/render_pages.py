"""Render every page of every produced PDF to a PNG, for reading by eye.

The anomaly section of the report is a reader's section: it is what turning the
pages finds that no detector reports. This writes those pages out one image per
page so they can be looked at, and it writes nothing else.

Usage:
    python render_pages.py [--dpi 110]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "examples" / "output" / "F2"
RASTER_DIR = OUT_DIR / "raster"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=110)
    args = parser.parse_args(argv)

    import pymupdf

    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "runs.json").open(encoding="utf-8") as f:
        records = json.load(f)

    written = []
    for record in records:
        sample = Path(record["sample"]).stem
        pdf = ROOT / Path(record["pdf"])
        with pymupdf.open(pdf) as document:
            for index, page in enumerate(document):
                image = page.get_pixmap(dpi=args.dpi)
                path = RASTER_DIR / f"{sample}.p{index + 1}.png"
                image.save(path)
                written.append(str(path.relative_to(ROOT)))
    print("\n".join(written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
