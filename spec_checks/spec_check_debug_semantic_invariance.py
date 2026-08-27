"""Behavior checks for diagnostics that must not enter semantic IL."""

from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

GATE_SET = "fast"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.add_debug_information import (  # noqa: E402
    AddDebugInformation,
)
from babeldoc.magazine.debug_overlay import DebugOverlayLedger  # noqa: E402
from babeldoc.magazine.debug_overlay import OverlayCategory  # noqa: E402
from babeldoc.magazine.debug_overlay import OverlayProducer  # noqa: E402
from babeldoc.magazine.fixed_assets import content_digest  # noqa: E402
from babeldoc.magazine.runtime_profile import semantic_fingerprint  # noqa: E402


def box(x, y, x2, y2):
    return il.Box(x=x, y=y, x2=x2, y2=y2)


def document():
    paragraph = il.PdfParagraph(
        box=box(40, 100, 260, 150),
        unicode="semantic body",
        layout_label="text",
        chain_id="chain-1",
    )
    page = il.Page(
        page_number=0,
        cropbox=il.Cropbox(box=box(0, 0, 300, 400)),
        mediabox=il.Mediabox(box=box(0, 0, 300, 400)),
        pdf_paragraph=[paragraph],
        pdf_curve=[il.PdfCurve(box=box(5, 5, 20, 20), debug_info=True)],
    )
    return il.Document(page=[page], total_pages=1)


def config(*, debug=False, show=False):
    return SimpleNamespace(
        debug=debug,
        show_char_box=show,
        debug_overlay_ledger=DebugOverlayLedger(),
    )


def main() -> int:
    baseline = document()
    off, on, show = (copy.deepcopy(baseline) for _ in range(3))
    off_config, on_config, show_config = (
        config(),
        config(debug=True),
        config(show=True),
    )
    AddDebugInformation(off_config).process(off)
    AddDebugInformation(on_config).process(on)
    show_config.debug_overlay_ledger.add_box(
        source_page_number=1,
        producer=OverlayProducer.ACTIVE_FRONTEND_CHAR_BOX,
        category=OverlayCategory.CHARACTER_BOX,
        page_bounds=(0, 0, 300, 400),
        box=(40, 100, 50, 112),
    )

    fingerprints = {
        stage: {
            semantic_fingerprint(stage, value)
            for value in (baseline, off, on, show)
        }
        for stage in ("post_article_ir", "post_typesetting", "post_repair")
    }
    checks = {
        "root TOML has the cross-platform byte contract": hashlib.sha256(
            (ROOT / "babeldoc.zh-en.toml").read_bytes()
        ).hexdigest() == "0e704cddbf26e1a0da76e55c1a0cbdebbca3b19825f2246a9434e8ec98dd7ea9",
        "all staged semantic fingerprints are invariant": all(
            len(values) == 1 for values in fingerprints.values()
        ),
        "fixed-asset and classifier inputs are invariant": len(
            {content_digest(value) for value in (baseline, off, on, show)}
        ) == 1,
        "semantic document values are untouched": baseline == off == on == show,
        "source debug-tagged artwork remains semantic": all(
            value.page[0].pdf_curve[0].debug_info for value in (off, on, show)
        ),
        "debug-off ledger is empty": len(off_config.debug_overlay_ledger) == 0,
        "debug-on ledger is non-empty": len(on_config.debug_overlay_ledger) > 0,
        "show-char-only contains character overlays only": {
            item.category for item in show_config.debug_overlay_ledger.items
        } == {OverlayCategory.CHARACTER_BOX},
        "no diagnostic semantic rectangles or paragraphs were added": all(
            len(value.page[0].pdf_rectangle) == 0
            and len(value.page[0].pdf_paragraph) == 1
            for value in (off, on, show)
        ),
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"spec_check_debug_semantic_invariance: {sum(checks.values())}/{len(checks)} passed")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
