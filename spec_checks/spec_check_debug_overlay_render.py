"""Render diagnostics only on a post-validation PDF copy."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pymupdf

GATE_SET = "fast"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf import high_level  # noqa: E402
from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater  # noqa: E402
from babeldoc.magazine.debug_overlay import DebugArtifactError  # noqa: E402
from babeldoc.magazine.debug_overlay import DebugOverlayLedger  # noqa: E402
from babeldoc.magazine.debug_overlay import OverlayCategory  # noqa: E402
from babeldoc.magazine.debug_overlay import OverlayProducer  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    checks = {}
    with tempfile.TemporaryDirectory(prefix="babeldoc-c17-overlay-") as raw:
        root = Path(raw)
        semantic = root / "semantic.pdf"
        debug = root / "semantic.debug.pdf"
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=300, height=400)
            page.insert_text((40, 80), "semantic body")
            pdf.save(semantic)
        before_hash = sha(semantic)
        with pymupdf.open(semantic) as pdf:
            before = (pdf.page_count, tuple(pdf[0].mediabox), tuple(pdf[0].cropbox), pdf[0].rotation)
            before_drawings = len(pdf[0].get_drawings())

        ledger = DebugOverlayLedger()
        ledger.add_box(
            source_page_number=1, producer=OverlayProducer.ADD_DEBUG_INFORMATION,
            category=OverlayCategory.PARAGRAPH, page_bounds=(0, 0, 300, 400),
            box=(35, 60, 150, 90),
        )
        ledger.add_label(
            source_page_number=1, producer=OverlayProducer.ADD_DEBUG_INFORMATION,
            category=OverlayCategory.PARAGRAPH, page_bounds=(0, 0, 300, 400),
            box=(35, 60, 150, 90), text="paragraph[p1#0]",
        )
        config = SimpleNamespace(
            debug_overlay_ledger=ledger, raise_if_cancelled=lambda: None
        )
        writer = object.__new__(PDFCreater)
        writer.write_debug_artifact(semantic, debug, config, ledger)
        with pymupdf.open(debug) as pdf:
            after = (pdf.page_count, tuple(pdf[0].mediabox), tuple(pdf[0].cropbox), pdf[0].rotation)
            checks["debug copy preserves page geometry and semantic text"] = (
                after == before and "semantic body" in pdf[0].get_text()
            )
            checks["debug copy contains additional drawing operations"] = (
                len(pdf[0].get_drawings()) > before_drawings
            )
        checks["semantic PDF bytes are never modified"] = sha(semantic) == before_hash

        bad = DebugOverlayLedger()
        bad.add_box(
            source_page_number=2, producer=OverlayProducer.ADD_DEBUG_INFORMATION,
            category=OverlayCategory.PAGE, page_bounds=(0, 0, 300, 400),
            box=(1, 1, 2, 2),
        )
        typed = False
        try:
            writer.write_debug_artifact(semantic, root / "bad.pdf", config, bad)
        except DebugArtifactError:
            typed = True
        checks["overlay failure is typed and preserves semantic success"] = (
            typed and sha(semantic) == before_hash and not (root / "bad.pdf").exists()
        )

        events = []
        old_validate = high_level._run_final_pdf_compliance
        old_overlay = high_level._write_debug_artifact_after_validation
        high_level._run_final_pdf_compliance = lambda *_args: events.append("validate")
        high_level._write_debug_artifact_after_validation = lambda *_args: events.append("overlay")
        try:
            high_level._validate_then_write_debug_artifact(
                object(), object(), semantic, object(), ()
            )
        finally:
            high_level._run_final_pdf_compliance = old_validate
            high_level._write_debug_artifact_after_validation = old_overlay
        checks["overlay writer runs only after semantic validator"] = events == ["validate", "overlay"]

    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"spec_check_debug_overlay_render: {sum(checks.values())}/{len(checks)} passed")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
