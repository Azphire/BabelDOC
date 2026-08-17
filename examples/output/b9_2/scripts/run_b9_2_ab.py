"""B9.2 acceptance: the heading policy against the stack, one sample twice.

Three arms over every English sample of the corpus. All three run the finished
stack with detection up; two of them differ in one attribute,
``magazine_title_typeset``, which is what the batch is for. The arms are not
evaluations to be scored against each other -- there is nothing to score, the
policy either sets a heading on one line or raises it -- they are a controlled
comparison, and what it is for is the assertion that the switch is typography
and nothing else: the translated document an arm hands to the layout has to be
the document the other arm handed over, and the difference between the finished
PDFs has to be heading geometry and the layers a heading was shown by.

The third arm is the control, and it repeats the first arm's configuration
exactly. It is there because this pipeline is not bit reproducible: a request
the cache did not keep is asked again, the model is sampled rather than looked
up, and two runs of one configuration can disagree. The control is what says how
much. A difference between the first two arms means something only where the
control shows none.

Why the requests are the same requests
--------------------------------------

The heading policy runs after the typesetting stage, which is long after the
last translation request is built, so it cannot reach a prompt. The off arm is
therefore the one that pays: the standing instruction changed with the person
name policy and the ruling gained terms since the last full run, so most of
what it asks is new to the cache. The on arm asks the same questions again and
the cache answers them. Both arms record what they spent, which is the ledger
this batch reports.

``magazine_hitl_export`` is down for the reason it was down in F1: export
writes drafts into the user's directory and a run that consumes a ruling has no
business rewriting the drafts beside it. Nothing in a prompt depends on it.

Usage:
    python run_b9_2_ab.py --arm off --all
    python run_b9_2_ab.py --arm on --all
    python run_b9_2_ab.py --arm control --all
    python run_b9_2_ab.py --arm on --sample CERNCourier-en
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
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from babeldoc.magazine import translation_style  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b9_2"

MODEL = "gpt-4o"
QPS = 4
BATCH = "b9_2"

# The arms, by the value each gives the switch under test. Two of them give it
# the same value: "control" repeats "off" unchanged, and what it measures is how
# much two runs of one configuration differ from each other. Without that figure
# a difference between "off" and "on" cannot be read, because this pipeline is
# not bit reproducible -- the model is sampled, and a request the cache did not
# keep is asked again and answered differently.
ARMS = {"off": False, "control": False, "on": True}

# The direction this batch accepts in. The corpus declares a direction per
# sample; the samples this batch runs are the ones declaring this source.
SOURCE_LANGUAGE = "en"

# Constructor switches, the same stack F1 ran.
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

# Switches that are not constructor parameters (W-B7-02, W-B8-01), and the one
# this batch adds, which the arm decides.
ATTRIBUTES = {"magazine_drop_cap_mark": True, "magazine_repair": True}


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


def ruling(sample: str) -> dict:
    """The ruling that governs this sample, identified rather than copied."""
    path = hitl.decisions_path(sample)
    if not path.exists():
        return {"path": None, "sha256": None, "present": False}
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": digest(path),
        "present": True,
    }


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
    setattr(config, title_typeset.SWITCH, ARMS[arm])
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
        title_typeset.SWITCH: ARMS[arm],
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
        "ruling": ruling(sample),
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


def samples() -> list[str]:
    """Every sample the corpus declares this batch's source language for."""
    wanted = []
    for entry in corpus.load_manifest().get("samples", ()):
        stem = Path(entry["file"]).stem
        if corpus.direction_of(stem)[0] == SOURCE_LANGUAGE:
            wanted.append(stem)
    return wanted


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

    wanted = samples() if args.all else (args.sample or samples()[:1])
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
