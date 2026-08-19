"""B9.5 acceptance: the repair loop against the whole corpus, three arms.

Six samples, because the census this batch owes is a census of the corpus and
not of the two samples a defect was first seen in. Every page of every sample is
measured by the two detectors this batch added, and what they report is sorted
into what the translation induced and what the source already drew.

The arm attribute is ``magazine_repair``. It is the switch that decides whether
anything is done about a finding, and it is the only one that separates a run
that measures the geometry from a run that also corrects it. Holding it down is
what the corpus stood at through b9.4, so the off arm is the corpus as the last
batch left it and the on arm is the corpus with the loop allowed to act.

Three arms, and the third repeats the first exactly. This pipeline is not bit
reproducible: a request the cache did not keep is sampled again, and the loop's
own decision is by design not served from the cache at all. So a difference
between the off and on arms counts against the switch only where the control
reproduced its arm, which is the attribution floor every batch since e2.1 has
been read against.

``magazine_hitl_export`` is down for the reason it has been down since F1:
export writes drafts into the user's directory, and an acceptance run has no
business rewriting the rulings beside it.

Usage:
    python run_b9_5_ab.py --arm off --all
    python run_b9_5_ab.py --arm control --all
    python run_b9_5_ab.py --arm on --all
"""

from __future__ import annotations

import argparse
import hashlib
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
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from babeldoc.magazine import translation_style  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.react import controller as react  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b9_5"

MODEL = "gpt-4o"
QPS = 4
BATCH = "b9_5"

ARMS = {"off": False, "control": False, "on": True}

# The whole corpus: the census is a census.
SAMPLES = (
    "Courier-en",
    "Vogue-en",
    "CERNCourier-en",
    "AramcoWorld-en-v2",
    "FD-en-v2",
    "Courier-zh",
)

STACK = {
    "magazine_checkpoint": True,
    "magazine_page_classify": True,
    "magazine_chain_detect": True,
    "magazine_chain_translate": True,
    "magazine_article_group": True,
    "magazine_article_context": True,
    "magazine_hitl_export": False,
    "magazine_hitl_apply": True,
    "magazine_detect": True,
}

# Switches that are not constructor parameters (W-B7-02, W-B8-01). Everything
# that shipped is up; the one this batch varies is set per arm below.
ATTRIBUTES = {
    "magazine_drop_cap_mark": True,
    "magazine_drop_cap_apply": True,
    title_typeset.SWITCH: True,
    line_split.SWITCH: True,
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
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def build_engine(source_lang: str, target_lang: str) -> OpenAITranslator:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("no credential in the environment")
    return OpenAITranslator(
        lang_in=source_lang,
        lang_out=target_lang,
        model=MODEL,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=key,
        ignore_cache=False,
        enable_json_mode_if_requested=False,
        send_dashscope_header=False,
        send_temperature=True,
    )


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def page_count(path: Path) -> int | None:
    try:
        import pymupdf

        with pymupdf.open(path) as document:
            return document.page_count
    except Exception:  # noqa: BLE001 - a page count is never worth failing a run
        return None


def run_one(sample: str, arm: str, layout_model) -> dict:
    pdf = INPUT_DIR / f"{sample}.pdf"
    destination = OUT_DIR / arm / sample
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    source_lang, target_lang = corpus.direction_of(sample)
    engine = build_engine(source_lang, target_lang)
    config = TranslationConfig(
        translator=engine,
        input_file=pdf,
        lang_in=source_lang,
        lang_out=target_lang,
        doc_layout_model=layout_model,
        output_dir=destination / "out",
        working_dir=destination / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=True,
        qps=QPS,
        **STACK,
    )
    for attribute, value in ATTRIBUTES.items():
        setattr(config, attribute, value)
    setattr(config, react.SWITCH, ARMS[arm])
    style_prompt = translation_style.apply(config, target_lang)

    started = time.monotonic()
    try:
        result = high_level.translate(config)
    finally:
        seconds = time.monotonic() - started

    mono = getattr(result, "mono_pdf_path", None)
    final_pdf = None
    if mono:
        final_pdf = destination / f"{sample}.{BATCH}.{arm}.pdf"
        shutil.copyfile(mono, final_pdf)

    record = {
        "sample": f"{sample}.pdf",
        "arm": arm,
        react.SWITCH: ARMS[arm],
        "model": MODEL,
        "lang_in": source_lang,
        "lang_out": target_lang,
        "seconds": round(seconds, 1),
        "requests": engine.translate_call_count,
        "cache_hits": engine.translate_cache_call_count,
        "api_calls": engine.translate_call_count - engine.translate_cache_call_count,
        "prompt_tokens": engine.prompt_token_count.value,
        "completion_tokens": engine.completion_token_count.value,
        "input_pages": page_count(pdf),
        "output_pages": page_count(final_pdf) if final_pdf else None,
        "pdf": str(final_pdf.relative_to(ROOT)) if final_pdf else None,
        "pdf_sha256": digest(final_pdf) if final_pdf else None,
        "working_dir": str(Path(config.working_dir).relative_to(ROOT)),
        "translation_style": {
            "person_names": translation_style.load_style_config().person_names,
            "system_prompt_sha256": None
            if style_prompt is None
            else hashlib.sha256(style_prompt.encode("utf-8")).hexdigest(),
        },
    }
    with (destination / "run.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(json.dumps(record, indent=2, ensure_ascii=False), flush=True)
    return record


def ledger_path(arm: str) -> Path:
    return OUT_DIR / f"runs.{arm}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    parser.add_argument("--sample", action="append", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = list(SAMPLES) if args.all else (args.sample or [SAMPLES[0]])
    layout_model = DocLayoutModel.load_onnx()
    written = []
    for sample in wanted:
        written.append(run_one(sample, args.arm, layout_model))

    path = ledger_path(args.arm)
    existing = []
    if path.exists() and not args.all:
        with path.open(encoding="utf-8") as f:
            existing = [
                row
                for row in json.load(f)
                if row["sample"] not in {item["sample"] for item in written}
            ]
    with path.open("w", encoding="utf-8") as f:
        json.dump(existing + written, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
