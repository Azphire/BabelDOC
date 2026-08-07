"""Rasterised page-by-page comparison of two PDF files.

Usage:
    python tools/render_diff.py A.pdf B.pdf --out report_dir/

Writes ``report.json`` with per-page and summary metrics plus a red hotspot
overlay PNG for every page that differs. Exit codes:

    0  every page identical within tolerance
    1  at least one page differs
    2  structural difference (page counts differ, or a file cannot be opened)

A raster size mismatch on a page present in both files is reported as a
page-level difference (exit 1), not as a structural difference (exit 2).

Two files with the same bytes cannot render differently, so that case is
answered from the content hashes and no page is rasterised at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pymupdf

EXIT_IDENTICAL = 0
EXIT_DIFFERENT = 1
EXIT_STRUCTURAL = 2

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "render_diff.json"

# Read size for incremental hashing; a pure I/O buffer, not a tuning knob.
_HASH_CHUNK_BYTES = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path = _CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def render_gray(doc: pymupdf.Document, page_index: int, dpi: int) -> np.ndarray:
    """Render one page to a 2D uint8 grayscale array."""
    pix = doc[page_index].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def count_regions(mask: np.ndarray, block_px: int) -> int:
    """Count 8-connected difference regions after grouping pixels into blocks.

    Working on blocks rather than raw pixels keeps the count stable against
    anti-aliasing noise and keeps the labelling cheap on large rasters.
    """
    if not mask.any():
        return 0
    height, width = mask.shape
    rows = -(-height // block_px)
    cols = -(-width // block_px)
    padded = np.zeros((rows * block_px, cols * block_px), dtype=bool)
    padded[:height, :width] = mask
    grid = padded.reshape(rows, block_px, cols, block_px).any(axis=(1, 3))

    seen = np.zeros_like(grid)
    regions = 0
    for start_r, start_c in zip(*np.nonzero(grid), strict=True):
        if seen[start_r, start_c]:
            continue
        regions += 1
        queue = deque([(start_r, start_c)])
        seen[start_r, start_c] = True
        while queue:
            r, c = queue.popleft()
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        if grid[nr, nc] and not seen[nr, nc]:
                            seen[nr, nc] = True
                            queue.append((nr, nc))
    return regions


def write_overlay(base: np.ndarray, mask: np.ndarray, path: Path) -> None:
    """Save ``base`` as RGB with differing pixels tinted red."""
    rgb = np.repeat(base[:, :, None], 3, axis=2).copy()
    rgb[mask] = (255, 0, 0)
    pix = pymupdf.Pixmap(
        pymupdf.csRGB,
        rgb.shape[1],
        rgb.shape[0],
        rgb.tobytes(),
        False,
    )
    pix.save(str(path))


def compare(
    pdf_a: Path,
    pdf_b: Path,
    out_dir: Path,
    dpi: int,
    threshold: int,
    tolerance: float,
    block_px: int,
) -> tuple[int, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "a": str(pdf_a),
        "b": str(pdf_b),
        "dpi": dpi,
        "pixel_diff_threshold": threshold,
        "diff_ratio_tolerance": tolerance,
        "region_block_px": block_px,
        "structural_difference": False,
        "structural_reason": None,
        "identical_bytes": False,
        "pages": [],
    }

    if pdf_a.exists() and pdf_b.exists():
        digest_a = sha256_file(pdf_a)
        if digest_a == sha256_file(pdf_b):
            report["identical_bytes"] = True
            report["sha256"] = digest_a
            report["summary"] = {
                "compared_pages": 0,
                "differing_pages": 0,
                "mean_diff_ratio": 0.0,
                "max_diff_ratio": 0.0,
            }
            return EXIT_IDENTICAL, report

    try:
        doc_a = pymupdf.open(pdf_a)
    except Exception as exc:  # any open failure is a structural difference
        report["structural_difference"] = True
        report["structural_reason"] = f"cannot open {pdf_a}: {exc}"
        return EXIT_STRUCTURAL, report
    try:
        doc_b = pymupdf.open(pdf_b)
    except Exception as exc:  # any open failure is a structural difference
        doc_a.close()
        report["structural_difference"] = True
        report["structural_reason"] = f"cannot open {pdf_b}: {exc}"
        return EXIT_STRUCTURAL, report

    report["pages_a"] = doc_a.page_count
    report["pages_b"] = doc_b.page_count
    if doc_a.page_count != doc_b.page_count:
        report["structural_difference"] = True
        report["structural_reason"] = (
            f"page count differs: {doc_a.page_count} vs {doc_b.page_count}"
        )

    differing_pages = 0
    total_ratio = 0.0
    common = min(doc_a.page_count, doc_b.page_count)
    for index in range(common):
        gray_a = render_gray(doc_a, index, dpi)
        gray_b = render_gray(doc_b, index, dpi)
        entry: dict = {"page": index, "size_mismatch": False}
        if gray_a.shape != gray_b.shape:
            entry["size_mismatch"] = True
            entry["shape_a"] = list(gray_a.shape)
            entry["shape_b"] = list(gray_b.shape)
            entry["diff_ratio"] = 1.0
            entry["diff_regions"] = 1
            entry["differs"] = True
            differing_pages += 1
            total_ratio += 1.0
            report["pages"].append(entry)
            continue

        delta = np.abs(gray_a.astype(np.int16) - gray_b.astype(np.int16))
        mask = delta > threshold
        ratio = float(mask.sum()) / float(mask.size)
        entry["diff_ratio"] = ratio
        entry["diff_regions"] = count_regions(mask, block_px)
        entry["differs"] = ratio > tolerance
        total_ratio += ratio
        if entry["differs"]:
            differing_pages += 1
            overlay = out_dir / f"page_{index:04d}.diff.png"
            write_overlay(gray_b, mask, overlay)
            entry["overlay"] = overlay.name
        report["pages"].append(entry)

    doc_a.close()
    doc_b.close()

    report["summary"] = {
        "compared_pages": common,
        "differing_pages": differing_pages,
        "mean_diff_ratio": (total_ratio / common) if common else 0.0,
        "max_diff_ratio": max(
            (p["diff_ratio"] for p in report["pages"]),
            default=0.0,
        ),
    }

    if report["structural_difference"]:
        return EXIT_STRUCTURAL, report
    if differing_pages:
        return EXIT_DIFFERENT, report
    return EXIT_IDENTICAL, report


def build_parser(config: dict) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_a", type=Path)
    parser.add_argument("pdf_b", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=config["dpi"])
    parser.add_argument("--threshold", type=int, default=config["pixel_diff_threshold"])
    parser.add_argument(
        "--tolerance", type=float, default=config["diff_ratio_tolerance"]
    )
    parser.add_argument("--block-px", type=int, default=config["region_block_px"])
    return parser


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    args = build_parser(config).parse_args(argv)
    code, report = compare(
        args.pdf_a,
        args.pdf_b,
        args.out,
        args.dpi,
        args.threshold,
        args.tolerance,
        args.block_px,
    )
    report_path = args.out
    report_path.mkdir(parents=True, exist_ok=True)
    with (report_path / "report.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    summary = report.get("summary", {})
    print(
        f"exit={code} structural={report['structural_difference']} "
        f"differing_pages={summary.get('differing_pages', 'n/a')} "
        f"max_diff_ratio={summary.get('max_diff_ratio', 'n/a')}"
    )
    if report["structural_reason"]:
        print(report["structural_reason"])
    return code


if __name__ == "__main__":
    sys.exit(main())
