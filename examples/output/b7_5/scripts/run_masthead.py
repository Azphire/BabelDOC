"""B7.5.2 real-API smoke driver: the two passes that close the masthead ruling.

The shape is the one batch-b7.3 established, and for the same reason: pass one
runs the whole magazine stack with the review export up and no ruling applied,
pass two runs the identical stack with the ruling applied, and what differs
between their outputs is what the ruling did.

What this run adds over b7.3 is the publication name. The b6.2 gap was that the
masthead rendered two different ways across the document with nothing able to
settle it; the ruling settles it, and this run is the evidence that it reached
every site the translator can see and the record of the one site it cannot.

The project cache is frozen in the sense that matters: a paragraph whose prompt
text the ruling did not change is the same request it was on pass one and is
replayed from the cache. Requests and cache hits are recorded per pass so that
the size of the ruling's blast radius is readable from the ledger.

Not part of the gate: this is the only thing in the batch that spends a
credential.

Usage:
    python run_masthead.py --pass pass1
    python run_masthead.py --pass pass2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.docvision.doclayout import DocLayoutModel  # noqa: E402
from babeldoc.format.pdf import high_level  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.format.pdf.translation_config import WatermarkOutputMode  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b7_5"

SAMPLE = "Courier-en.pdf"
MODEL = "gpt-4o"
QPS = 4

# Every magazine switch the stack has, up, in both passes. The one that differs
# is the one under test.
STACK = {
    "magazine_checkpoint": True,
    "magazine_page_classify": True,
    "magazine_chain_detect": True,
    "magazine_chain_translate": True,
    "magazine_article_group": True,
    "magazine_article_context": True,
    "magazine_hitl_export": True,
}

# Drop cap marking is not a constructor parameter; it is set on the object
# afterwards (W-B7-02).
ATTRIBUTES = {"magazine_drop_cap_mark": True}

PASSES = {
    "pass1": {"magazine_hitl_apply": False},
    "pass2": {"magazine_hitl_apply": True},
}


def load_dotenv() -> None:
    """Read the repository .env for a credential the shell does not carry."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("'\""))


def build_engine() -> OpenAITranslator:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    return OpenAITranslator(
        lang_in="en",
        lang_out="zh",
        model=MODEL,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=key,
        ignore_cache=False,
        enable_json_mode_if_requested=False,
        send_dashscope_header=False,
        send_temperature=True,
    )


def snapshot_reviews(name: str, destination: Path) -> list[str]:
    """Freeze the draft this pass wrote, which the next pass overwrites."""
    kept = []
    for path in (hitl.review_path(name), hitl.review_html_path(name)):
        if path.exists():
            shutil.copyfile(path, destination / path.name)
            kept.append(path.name)
    decisions = hitl.decisions_path(name)
    if decisions.exists():
        shutil.copyfile(decisions, destination / decisions.name)
        kept.append(decisions.name)
    return kept


def run_one(which: str, layout_model) -> dict:
    pdf = INPUT_DIR / SAMPLE
    name = Path(SAMPLE).stem
    destination = OUT_DIR / which
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    engine = build_engine()
    config = TranslationConfig(
        translator=engine,
        input_file=pdf,
        lang_in="en",
        lang_out="zh",
        doc_layout_model=layout_model,
        output_dir=destination / "out",
        working_dir=destination / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=True,
        qps=QPS,
        **STACK,
        **PASSES[which],
    )
    for attribute, value in ATTRIBUTES.items():
        setattr(config, attribute, value)

    started = time.monotonic()
    result = high_level.translate(config)
    seconds = time.monotonic() - started

    mono = getattr(result, "mono_pdf_path", None)
    if mono:
        shutil.copyfile(mono, OUT_DIR / f"{name}.{which}.pdf")

    record = {
        "sample": SAMPLE,
        "pass": which,
        "model": MODEL,
        "seconds": round(seconds, 1),
        "requests": engine.translate_call_count,
        "cache_hits": engine.translate_cache_call_count,
        "api_calls": engine.translate_call_count - engine.translate_cache_call_count,
        "prompt_tokens": engine.prompt_token_count.value,
        "completion_tokens": engine.completion_token_count.value,
        "working_dir": str(Path(config.working_dir).relative_to(ROOT)),
        "mono_pdf": f"{name}.{which}.pdf" if mono else None,
        "reviews": snapshot_reviews(name, destination),
    }
    with (destination / "run.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(json.dumps(record, indent=2, ensure_ascii=False), flush=True)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pass", dest="which", required=True, choices=list(PASSES))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    record = run_one(args.which, DocLayoutModel.load_onnx())

    ledger = OUT_DIR / "runs.json"
    existing = []
    if ledger.exists():
        with ledger.open(encoding="utf-8") as f:
            existing = json.load(f)
    keyed = {entry["pass"]: entry for entry in [*existing, record]}
    with ledger.open("w", encoding="utf-8") as f:
        json.dump([keyed[key] for key in sorted(keyed)], f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
