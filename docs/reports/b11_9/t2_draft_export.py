"""Export the review draft of every new Chinese sample without spending a request.

The drafts a ruling is written from cannot come from the baseline run: that run
returns at ``only_parse_generate_pdf`` before the classifier and before the drop
cap pass, so it never produces the paragraph references a ``drop_caps`` section
is keyed on. This driver runs the pipeline far enough to produce them and no
further.

Zero API is arranged three ways, not one. ``skip_translation`` removes the
translator stage; ``auto_extract_glossary`` down removes the extractor stage,
which is the one stage of the reduced pipeline that would otherwise ask; and the
name harvest, whose ``render_names`` sends one batched request per document, is
declared down. The run also carries no engine at all, so a fourth path to a
request does not exist either. The database row counts taken around each run are
what the report states, rather than a switch inventory: a switch says what was
asked for and a row says what was spent.

Usage:
    python docs/reports/b11_9/t2_draft_export.py [--sample fd-zh ...]
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from babeldoc.docvision.doclayout import DocLayoutModel  # noqa: E402
from babeldoc.format.pdf import high_level  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.format.pdf.translation_config import WatermarkOutputMode  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine.cache_setup import PROJECT_CACHE_RELPATH  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402

logger = logging.getLogger(__name__)

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b11_9"

SAMPLES = ("HuaweiTech-zh", "ABB-zh", "bull-zh", "fd-zh", "ITU-zh", "WIPO-zh")

# Everything the draft needs and nothing that asks. The classifier fills the
# page_kinds section, the grouping stage supplies the article map the drop cap
# pass decides a candidate against, and the export switch is what writes the
# draft out.
STACK = {
    "magazine_page_classify": True,
    "magazine_chain_detect": True,
    "magazine_article_group": True,
    "magazine_hitl_export": True,
    "magazine_hitl_apply": False,
    "magazine_checkpoint": False,
}

# Switches that are not constructor parameters (W-B7-02, W-B8-01). The harvest
# is named here rather than left to its default so that the run states its own
# zero-request posture instead of inheriting it.
ATTRIBUTES = {
    "magazine_drop_cap_mark": True,
    "magazine_name_harvest": False,
    "magazine_repair": False,
}


def cache_rows(db_path: Path) -> int:
    if not db_path.is_file():
        return 0
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return connection.execute("SELECT COUNT(*) FROM _translationcache").fetchone()[
            0
        ]
    finally:
        connection.close()


def run_one(name: str, layout_model) -> dict:
    destination = OUT_DIR / name
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    source_lang, target_lang = corpus.direction_of(name)
    config = TranslationConfig(
        translator=None,
        input_file=INPUT_DIR / f"{name}.pdf",
        lang_in=source_lang,
        lang_out=target_lang,
        doc_layout_model=layout_model,
        output_dir=destination / "out",
        working_dir=destination / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=False,
        skip_translation=True,
        **STACK,
    )
    for attribute, value in ATTRIBUTES.items():
        setattr(config, attribute, value)

    db_path = ROOT / PROJECT_CACHE_RELPATH
    before = cache_rows(db_path)
    started = time.monotonic()
    high_level.translate(config)
    seconds = time.monotonic() - started
    after = cache_rows(db_path)

    draft_path = ROOT / "reviews" / f"{name}.review.json"
    with draft_path.open(encoding="utf-8") as f:
        draft = json.load(f)
    record = {
        "sample": name,
        "direction": f"{source_lang}->{target_lang}",
        "seconds": round(seconds, 1),
        "api_calls": after - before,
        "cache_rows_before": before,
        "cache_rows_after": after,
        "translator": None,
        "skip_translation": True,
        "auto_extract_glossary": False,
        "magazine_name_harvest": False,
        "page_kinds_rows": len(draft.get("page_kinds") or []),
        "terms_rows": len(draft.get("terms") or []),
        "drop_caps_rows": len(draft.get("drop_caps") or []),
        "draft": draft_path.relative_to(ROOT).as_posix(),
    }
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", default=None, choices=SAMPLES)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    use_project_cache(ROOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    layout_model = DocLayoutModel.load_onnx()
    wanted = [name for name in SAMPLES if args.sample is None or name in args.sample]
    ledger = [run_one(name, layout_model) for name in wanted]

    path = OUT_DIR / "t2_runs.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"ledger -> {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
