"""Offline diagnostic replay for legacy debug geometry in ABB checkpoints."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.debug_overlay import DebugOverlayLedger  # noqa: E402
from babeldoc.magazine.debug_overlay import OverlayCategory  # noqa: E402
from babeldoc.magazine.debug_overlay import OverlayProducer  # noqa: E402
from babeldoc.magazine.debug_overlay import OverlayStyle  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402

EXPECTED = {
    "checkpoint.03_layout_generator.xml": "ba5c433f2091c911600ac8f08ad36e4c67bb99f5aee0a74aba0d11bac4ace21f",
    "layout_generator.json": "eecf3e3ee792fb8fa6351d553f5232006937a105e3bf27eaf562973be404f14e",
    "checkpoint.05_paragraph_finder.xml": "30ec4744ded147c1201cd6d60008528d25c96d231769725cc3d558ef35467c1f",
    "checkpoint.08_chain_builder.xml": "1c3f88ef69950e8a8bac3c24e8347b1b69da2996b1f07f673d01499cf0e1800f",
    "article_ir.json": "f522279e66d4bcd003c4cd05ca01a69f3a9ac0367c7d3a4ccd7fa1c437d9e440",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coords(value) -> tuple[float, float, float, float]:
    if isinstance(value, dict):
        return tuple(float(value[name]) for name in ("x", "y", "x2", "y2"))
    return tuple(float(getattr(value, name)) for name in ("x", "y", "x2", "y2"))


def clean_stage(document, layout_record, ledger: DebugOverlayLedger, *, emit: bool):
    cleaned = copy.deepcopy(document)
    removed = 0
    for page_index, (page, layout_page) in enumerate(
        zip(cleaned.page, layout_record["page"], strict=True)
    ):
        layouts = layout_page["page_layout"]
        if len(page.page_layout) != len(layouts):
            raise ValueError(f"page {page_index + 1}: layout count mismatch")
        keys = []
        for index, (runtime_layout, raw_layout) in enumerate(
            zip(page.page_layout, layouts, strict=True)
        ):
            layout_box = coords(raw_layout["box"])
            key = (page_index + 1, raw_layout["class_name"], layout_box)
            if coords(runtime_layout.box) != layout_box or runtime_layout.class_name != key[1]:
                raise ValueError(f"page {page_index + 1} layout {index}: archive mismatch")
            keys.append(key)
        if len(keys) != len(set(keys)):
            raise ValueError(f"page {page_index + 1}: ambiguous legacy layout key")
        if len(page.pdf_paragraph) < len(keys) or len(page.pdf_rectangle) < len(keys):
            raise ValueError(f"page {page_index + 1}: unmatched legacy diagnostics")
        bounds = coords(page.cropbox.box)
        for index, key in enumerate(keys):
            paragraph = page.pdf_paragraph[index]
            rectangle = page.pdf_rectangle[index]
            layout_box = key[2]
            expected_label = (layout_box[0], layout_box[3], layout_box[2], layout_box[3] + 5.0)
            label_box = coords(paragraph.box)
            if paragraph.unicode != key[1] or label_box[0] != expected_label[0] or label_box[2] != expected_label[2]:
                raise ValueError(f"page {page_index + 1} layout {index}: unmatched legacy label")
            if coords(rectangle.box) != layout_box:
                raise ValueError(f"page {page_index + 1} layout {index}: unmatched legacy box")
            if emit:
                reference = f"legacy:p{page_index + 1}:layout#{index}"
                label_y = max(bounds[1], min(layout_box[3], bounds[3] - 5.0))
                rendered_label = (
                    layout_box[0],
                    label_y,
                    layout_box[2],
                    label_y + 5.0,
                )
                rendered_box = (
                    max(bounds[0], min(layout_box[0], bounds[2])),
                    max(bounds[1], min(layout_box[1], bounds[3])),
                    max(bounds[0], min(layout_box[2], bounds[2])),
                    max(bounds[1], min(layout_box[3], bounds[3])),
                )
                ledger.add_box(
                    source_page_number=page_index + 1,
                    producer=OverlayProducer.LEGACY_CHECKPOINT_ADAPTER,
                    category=OverlayCategory.LEGACY_CONTAMINATION,
                    page_bounds=bounds,
                    box=rendered_box,
                    style=OverlayStyle.INDIGO,
                    related_semantic_ref=reference,
                )
                # Use the original valid label geometry; the later inverted box is evidence,
                # never renderable overlay geometry.
                ledger.add_label(
                    source_page_number=page_index + 1,
                    producer=OverlayProducer.LEGACY_CHECKPOINT_ADAPTER,
                    category=OverlayCategory.LEGACY_CONTAMINATION,
                    page_bounds=bounds,
                    box=rendered_label,
                    text=key[1],
                    style=OverlayStyle.INDIGO,
                    related_semantic_ref=reference,
                )
        del page.pdf_paragraph[: len(keys)]
        del page.pdf_rectangle[: len(keys)]
        removed += len(keys)
    return cleaned, removed


def invalid_boxes(document):
    invalid = []
    for page_index, page in enumerate(document.page):
        for index, paragraph in enumerate(page.pdf_paragraph):
            if paragraph.box is None:
                continue
            value = coords(paragraph.box)
            if value[0] > value[2] or value[1] > value[3]:
                invalid.append({"source_page": page_index + 1, "index": index, "box": list(value)})
    return invalid


def write_atomic(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-page", required=True, type=int)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    hashes = {name: digest(args.root / name) for name in EXPECTED}
    mismatches = {name: value for name, value in hashes.items() if value != EXPECTED[name]}
    if mismatches:
        raise ValueError(f"checkpoint hash mismatch: {mismatches}")

    layout = json.loads((args.root / "layout_generator.json").read_text(encoding="utf-8"))
    ledger = DebugOverlayLedger()
    stages = {}
    documents = {}
    for filename in (
        "checkpoint.03_layout_generator.xml",
        "checkpoint.05_paragraph_finder.xml",
        "checkpoint.08_chain_builder.xml",
    ):
        archived = load_checkpoint(args.root / filename)
        documents[filename] = archived
        cleaned, removed = clean_stage(archived, layout, ledger, emit=filename.endswith("03_layout_generator.xml"))
        invalid = invalid_boxes(cleaned)
        trace = RunTrace.from_document(cleaned)
        stages[filename] = {
            "legacy_debug_labels_removed": removed,
            "semantic_paragraphs": sum(len(page.pdf_paragraph) for page in cleaned.page),
            "invalid_semantic_boxes": invalid,
            "run_trace_sources": len(trace.sources),
        }
        if invalid:
            raise ValueError(f"{filename}: invalid semantic geometry after replay")

    archived_target = documents["checkpoint.05_paragraph_finder.xml"].page[args.source_page - 1].pdf_paragraph[11]
    target_box = coords(archived_target.box)
    expected_target = (54.0, 117.70305, 82.0, 117.41005)
    if any(abs(actual - expected) > 1e-9 for actual, expected in zip(target_box, expected_target, strict=True)):
        raise ValueError(f"ABB archived target changed: {target_box}")
    article_record = json.loads((args.root / "article_ir.json").read_text(encoding="utf-8"))
    report = {
        "schema_version": "debug-geometry-replay.v1",
        "archive_hashes": hashes,
        "source_page": args.source_page,
        "archived_failure": {
            "paragraph_index": 11,
            "box": list(target_box),
            "classification": "legacy_debug_contamination",
            "layout_key": [args.source_page, "title", [54.0, 104.0, 82.0, 116.0]],
        },
        "stages": stages,
        "article_ir": {
            "articles": len(article_record["articles"]),
            "elements": len(article_record["by_element"]),
            "archived_failure_ref_is_semantic": f"p{args.source_page}#11" in article_record["by_element"],
        },
        "semantic_legacy_debug_labels": 0,
        "overlay": {"count": len(ledger), "sha256": ledger.digest()},
        "run_trace_strict": True,
    }
    if report["article_ir"]["archived_failure_ref_is_semantic"]:
        raise ValueError("legacy label entered archived ArticleIR")
    write_atomic(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
