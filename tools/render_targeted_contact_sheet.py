"""Render a mapped targeted PDF as labelled 2x2 contact-sheet pages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.page_identity import PageSelectionMap  # noqa: E402


def _load_mapping(path: str | Path) -> PageSelectionMap:
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if "page_selection_map" in record:
        record = record["page_selection_map"]
    return PageSelectionMap.from_record(record)


def render_contact_sheet(
    pdf_path: str | Path,
    page_selection_map: PageSelectionMap,
    output_path: str | Path,
    *,
    dpi: int = 144,
) -> dict:
    """Render at 144dpi by default, adding labels only in an outer margin."""

    if not isinstance(dpi, int) or not 72 <= dpi <= 600:
        raise ValueError("dpi must be an integer in 72..600")
    source = pymupdf.open(pdf_path)
    if len(source) != len(page_selection_map.output_index_to_physical_page):
        source.close()
        raise ValueError("PDF page count does not match PageSelectionMap")
    scale = dpi / 72.0
    rendered = [page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False) for page in source]
    max_width = max((pix.width for pix in rendered), default=1)
    max_height = max((pix.height for pix in rendered), default=1)
    gutter = 24.0
    label_height = 32.0
    cell_width = max_width + gutter
    cell_height = max_height + label_height + gutter
    sheet_width = gutter + 2 * cell_width
    sheet_height = gutter + 2 * cell_height
    contact = pymupdf.open()
    labels = []
    for group_start in range(0, len(rendered), 4):
        sheet = contact.new_page(width=sheet_width, height=sheet_height)
        for offset, pixmap in enumerate(rendered[group_start : group_start + 4]):
            output_index = group_start + offset
            physical_page = int(
                page_selection_map.output_index_to_physical_page[output_index]
            )
            row, column = divmod(offset, 2)
            x0 = gutter + column * cell_width
            y0 = gutter + row * cell_height
            label = (
                f"physical source page {physical_page} | output index {output_index} "
                f"| source label {source[output_index].get_label()}"
            )
            labels.append(label)
            sheet.insert_textbox(
                pymupdf.Rect(x0, y0, x0 + max_width, y0 + label_height),
                label,
                fontsize=10,
                color=(0, 0, 0),
            )
            image_rect = pymupdf.Rect(
                x0,
                y0 + label_height,
                x0 + pixmap.width,
                y0 + label_height + pixmap.height,
            )
            sheet.insert_image(image_rect, stream=pixmap.tobytes("png"))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    contact.save(destination)
    contact.close()
    source.close()
    return {
        "schema_version": "targeted-contact-sheet.v1",
        "dpi": dpi,
        "columns": 2,
        "rows_per_sheet": 2,
        "source_page_count": len(rendered),
        "sheet_page_count": (len(rendered) + 3) // 4,
        "mapping_sha256": page_selection_map.mapping_sha256,
        "labels": labels,
        "output": str(destination),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--page-selection-map", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dpi", type=int, default=144)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    mapping = _load_mapping(args.page_selection_map)
    report = render_contact_sheet(args.pdf, mapping, args.output, dpi=args.dpi)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
