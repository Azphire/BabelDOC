"""B10.2 driver: the three samples the collision criterion and action are read on.

Two arms per sample, and they answer different questions.

The **model arm** is the loop as it ships: the decision rounds ask the model
which findings to act on, and what it chooses is recorded and is not an
assertion. It is sampled once, for the record of what a model does when it is
shown this kind for the first time, and the gate does not read it. That
separation is the GAP-25 lesson: an assertion whose truth depends on a sampled
reply is an assertion that fails on a day the sampling goes the other way.

The **detect arm** runs the same stack with the repair loop switched off, so it
produces the findings without acting on them and the unrepaired pages the
repaired ones are compared against. It spends nothing.

The gate's assertions about the action itself are neither of these: they drive
the applicability rule and the mechanism directly from stubs the gate builds, so
no assertion in it depends on a sampled reply. That separation is the GAP-25
lesson.

Whole documents, and why not ``--pages``
----------------------------------------

The batch plan asked for page ranged runs over the target pages. That is not
what this does, and the reason is the plan's own cost bound.

B10.1 established that the requests a run builds depend on how its pages group
into articles and chains, so a page range builds requests no earlier run built,
and a request no earlier run built is a request the project cache cannot answer.
A page ranged run over these three samples would therefore spend real money on
*translation* -- the thing every replay since F2 has been careful not to do --
in order to look at pages a whole document run reaches anyway. The plan bounds
this batch's spend to the decision rounds it adds, in the single digits, and the
two instructions cannot both be followed.

So the documents are translated whole, out of the warm cache, exactly as B10.1
and B9.5 translated them, and the target pages are what is *written out*: the
PDF extract, the rasters, and the sidecars. The deliverable is the target pages
either way; only the spend differs.

Usage:
    python run_b10_2.py --all
    python run_b10_2.py --sample Vogue-en
    python run_b10_2.py --all --detect-only
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
from babeldoc.magazine import paren_dedup  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from babeldoc.magazine import translation_style  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.react import controller as react  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b10_2"

MODEL = "gpt-4o"
QPS = 4
RUN = "b10_2"
DPI = 110

# The pages each sample is read on: the census pairs this batch's criterion is
# anchored to, plus the CERN page whose printing slugs must stay exempt.
TARGETS = {
    "AramcoWorld-en-v2": (3,),
    "Vogue-en": (3,),
    "CERNCourier-en": (3, 4),
}

# The sidecars this batch's assertions are read from, copied out of the working
# directory so the evidence stands without it. The title pass record is here
# because one census pair stopped being a candidate when that pass shrank it,
# and a gate that asserts the cause has to be able to read the cause.
SIDECARS = (
    "issues.json",
    "react_repair.report.json",
    "title_typeset.report.json",
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

ATTRIBUTES = {
    "magazine_drop_cap_mark": True,
    "magazine_drop_cap_apply": True,
    title_typeset.SWITCH: True,
    line_split.SWITCH: True,
    react.SWITCH: True,
    paren_dedup.SWITCH: True,
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


def render(pdf: Path, sample: str, destination: Path, tag: str) -> list[str]:
    """One PNG per target page of one sample, at the batch's resolution."""
    import pymupdf

    written = []
    destination.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as document:
        for page in TARGETS[sample]:
            if page - 1 >= document.page_count:
                continue
            image = document[page - 1].get_pixmap(dpi=DPI)
            path = destination / f"{sample}.p{page}.{tag}.png"
            image.save(path)
            written.append(str(path.relative_to(ROOT)))
    return written


def extract(pdf: Path, sample: str, destination: Path) -> str:
    """The target pages of one produced PDF, as a PDF of their own."""
    import pymupdf

    path = destination / f"{sample}.{RUN}.pages.pdf"
    with pymupdf.open(pdf) as document, pymupdf.open() as pages:
        for page in TARGETS[sample]:
            if page - 1 >= document.page_count:
                continue
            pages.insert_pdf(document, from_page=page - 1, to_page=page - 1)
        pages.save(path, garbage=4, deflate=True)
    return str(path.relative_to(ROOT))


def run_one(sample: str, layout_model, detect_only: bool) -> dict:
    pdf = INPUT_DIR / f"{sample}.pdf"
    # The two arms are kept side by side rather than one overwriting the other:
    # the detect arm's pages are the "before" the repaired pages are compared
    # against, and a comparison whose two sides cannot both exist is not one.
    destination = OUT_DIR / (f"{sample}.detect" if detect_only else sample)
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
    if detect_only:
        # The loop still detects; what it does not do is ask anybody anything.
        setattr(config, react.SWITCH, False)
    style_prompt = translation_style.apply(config, target_lang)

    started = time.monotonic()
    try:
        result = high_level.translate(config)
    finally:
        seconds = time.monotonic() - started

    mono = getattr(result, "mono_pdf_path", None)
    final_pdf = None
    if mono:
        final_pdf = destination / f"{sample}.{RUN}.pdf"
        shutil.copyfile(mono, final_pdf)

    working = Path(config.working_dir)
    kept = destination / "sidecars"
    kept.mkdir(parents=True, exist_ok=True)
    for name in SIDECARS:
        source = working / name
        if source.exists():
            shutil.copyfile(source, kept / name)

    record = {
        "sample": f"{sample}.pdf",
        "model": MODEL,
        "arm": "detect" if detect_only else "model",
        "lang_in": source_lang,
        "lang_out": target_lang,
        "seconds": round(seconds, 1),
        "target_pages": list(TARGETS[sample]),
        "requests": engine.translate_call_count,
        "cache_hits": engine.translate_cache_call_count,
        "api_calls": engine.translate_call_count - engine.translate_cache_call_count,
        "prompt_tokens": engine.prompt_token_count.value,
        "completion_tokens": engine.completion_token_count.value,
        "pdf": str(final_pdf.relative_to(ROOT)) if final_pdf else None,
        "pdf_sha256": digest(final_pdf) if final_pdf else None,
        "pages_pdf": extract(final_pdf, sample, destination) if final_pdf else None,
        "raster": render(
            final_pdf,
            sample,
            destination / "raster",
            "before" if detect_only else "after",
        )
        if final_pdf
        else [],
        "sidecars": sorted(str(p.relative_to(ROOT)) for p in kept.glob("*.json")),
        "working_dir": str(working.relative_to(ROOT)),
        "switches": {**STACK, **dict.fromkeys(ATTRIBUTES, True)},
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--sample", action="append")
    parser.add_argument("--detect-only", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = list(TARGETS) if args.all else (args.sample or ["AramcoWorld-en-v2"])
    layout_model = DocLayoutModel.load_available()
    rows = [run_one(sample, layout_model, args.detect_only) for sample in wanted]
    name = "runs.detect.json" if args.detect_only else "runs.json"
    with (OUT_DIR / name).open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
