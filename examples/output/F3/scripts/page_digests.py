"""Digest every rendered page of one arm into a file the gate can read.

The two arms of this run render 41 pages each. Tracking 82 images to prove they
are pairwise identical would put eighty megabytes into the repository to answer
one question; the digests answer the same question at four kilobytes, and they
are taken from the images themselves rather than from anything the run reported
about them. A handful of pages is tracked as images besides, for the reader.

Usage:
    python page_digests.py --arm warm
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "examples" / "output" / "F3"


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="warm")
    args = parser.parse_args(argv)

    arm = OUT_DIR / args.arm
    record: dict[str, dict[str, str]] = {}
    for sample_dir in sorted(p for p in arm.iterdir() if p.is_dir()):
        raster = sample_dir / "raster"
        if not raster.is_dir():
            continue
        pages = {}
        for image in sorted(raster.glob("*.png")):
            label = image.stem.rsplit(".p", 1)[-1]
            pages[label] = digest(image)
        record[sample_dir.name] = dict(
            sorted(pages.items(), key=lambda item: int(item[0]))
        )

    destination = OUT_DIR / f"page_digests.{args.arm}.json"
    with destination.open("w", encoding="utf-8") as f:
        json.dump({"arm": args.arm, "pages": record}, f, indent=2)
        f.write("\n")
    total = sum(len(pages) for pages in record.values())
    print(f"{total} pages digested into {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
