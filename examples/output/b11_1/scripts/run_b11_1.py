"""B11.1 driver: one sample, the whole stack, the working directory kept.

The batch's evidence is a single document. Its three changes -- an identity
write back that no longer reflows, a bound on hung punctuation, and the person
name policy moved to ``translate`` -- all show themselves on FD-en-v2, and the
ruling for this batch is that nothing else is run. So this driver takes one
sample rather than a corpus, and the switches it raises are read out of the f3
run record for that sample rather than restated, because a switch set that is
retyped is a switch set that can drift.

The working directory is kept rather than pruned. The determination this batch
owes for hung punctuation is read out of the typesetting checkpoint, and a
checkpoint that has been deleted is a determination that cannot be made twice.

Usage:
    python run_b11_1.py                 # produces into examples/output/b11_1
    python run_b11_1.py --tag probe     # a named side run, kept apart
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
from babeldoc.magazine import chain_backfill as backfill  # noqa: E402
from babeldoc.magazine import column_reflow  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import fragment_stitch  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from babeldoc.magazine import name_harvest  # noqa: E402
from babeldoc.magazine import paren_dedup  # noqa: E402
from babeldoc.magazine import short_unit  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from babeldoc.magazine import translation_style  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.react import controller as react  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b11_1"
BASELINE = ROOT / "examples" / "output" / "F3" / "cold" / "FD-en-v2" / "run.json"

SAMPLE = "FD-en-v2"
MODEL = "gpt-4o"
QPS = 4
RUN = "b11_1"
DPI = 110
CHECKPOINT = "checkpoint.11_typesetting.json"

# Switch names that are constructor parameters; the rest are set afterwards
# (W-B7-02, W-B8-01). Which name belongs to which group is a property of the
# code, so it is stated here; whether a name is up is read from the baseline.
CONSTRUCTOR_SWITCHES = (
    "magazine_checkpoint",
    "magazine_page_classify",
    "magazine_chain_detect",
    "magazine_chain_translate",
    "magazine_article_group",
    "magazine_article_context",
    "magazine_hitl_export",
    "magazine_hitl_apply",
    "magazine_detect",
)

# Plain attribute switches, named the way the run record names them.
PLAIN_ATTRIBUTES = ("magazine_drop_cap_mark", "magazine_drop_cap_apply")

# Attribute switches whose name is computed from a config rather than spelled.
COMPUTED_ATTRIBUTES = {
    title_typeset.SWITCH: "magazine_title_typeset",
    line_split.SWITCH: "magazine_line_structure",
    fragment_stitch.SWITCH: "magazine_fragment_stitch",
    react.SWITCH: "magazine_repair",
    paren_dedup.SWITCH: "magazine_paren_dedup",
    column_reflow.SWITCH: "magazine_column_reflow",
    backfill.load_backfill_config().align_switch: "magazine_chain_cut_align",
    fragment_stitch.load_stitch_config().declared_page_switch: (
        "magazine_stitch_declared"
    ),
    short_unit.load_short_unit_config().switch: "magazine_short_unit",
    name_harvest.load_harvest_config().switch: "magazine_name_harvest",
}

SIDECARS = (
    "page_classify.report.json",
    "chain_report.json",
    "chain_translation.report.json",
    "article_map.json",
    "article_context.report.json",
    "hitl_apply.report.json",
    "drop_cap.report.json",
    "drop_cap_apply.report.json",
    "line_split.report.json",
    "fragment_stitch.report.json",
    "short_unit.report.json",
    "name_harvest.report.json",
    "paren_dedup.report.json",
    "source_audit.report.json",
    "typeset_hang.report.json",
    title_typeset.REPORT_NAME,
    column_reflow.REPORT_NAME,
    "issues.json",
    "react_repair.report.json",
)


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


def baseline_switches() -> dict:
    """The switch set of the f3 run of this sample, read rather than retyped."""
    with BASELINE.open(encoding="utf-8") as f:
        return json.load(f)["switches"]


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


def raster(pdf: Path, sample: str, destination: Path) -> list[str]:
    """Every page of the produced PDF as an image, for reading by eye."""
    import pymupdf

    destination.mkdir(parents=True, exist_ok=True)
    written = []
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document):
            path = destination / f"{sample}.p{index + 1}.png"
            page.get_pixmap(dpi=DPI).save(path)
            written.append(str(path.relative_to(ROOT)))
    return written


def page_of(document: dict, label: int) -> dict | None:
    for page in document.get("page", ()):
        if page.get("page_number", -1) + 1 == label:
            return page
    return None


def paragraph_texts(document: dict, label: int) -> list[str] | None:
    """The text of every paragraph of one page, in stored order, or None."""
    page = page_of(document, label)
    if page is None:
        return None
    return [
        paragraph.get("unicode") or "" for paragraph in page.get("pdf_paragraph") or ()
    ]


def conservation(working: Path, destination: Path) -> str | None:
    """This run's typesetting document, page and paragraph by paragraph.

    The batch baseline is the f3 run of the same sample, whose working directory
    was pruned; what survives of it is the produced PDF. So the page and
    paragraph counts come from this run's checkpoint and the baseline's page
    count from its PDF, and each paragraph's text is recorded under its page
    ordinal reference, which is the anchor the gate compares on.
    """
    path = working / CHECKPOINT
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        document = json.load(f)
    baseline_pdf = BASELINE.parent / f"{SAMPLE}.f3.pdf"
    pages = {}
    for label in range(1, len(document.get("page") or ()) + 1):
        texts = paragraph_texts(document, label) or []
        pages[str(label)] = {
            "paragraphs": len(texts),
            "text": {f"p{label}#{index}": text for index, text in enumerate(texts)},
        }
    record = {
        "sample": SAMPLE,
        "baseline": str(baseline_pdf.relative_to(ROOT)),
        "baseline_pages": page_count(baseline_pdf),
        "pages": len(document.get("page") or ()),
        "per_page": pages,
    }
    out = destination / "conservation.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return str(out.relative_to(ROOT))


def run_one(layout_model, tag: str | None) -> dict:
    pdf = INPUT_DIR / f"{SAMPLE}.pdf"
    destination = OUT_DIR / (SAMPLE if tag is None else f"{SAMPLE}.{tag}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    source_lang, target_lang = corpus.direction_of(SAMPLE)
    switches = baseline_switches()
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
        **{name: switches[name] for name in CONSTRUCTOR_SWITCHES},
    )
    for name in PLAIN_ATTRIBUTES:
        setattr(config, name, switches[name])
    for attribute, declared in COMPUTED_ATTRIBUTES.items():
        setattr(config, attribute, switches[declared])
    style_prompt = translation_style.apply(config, target_lang)

    started = time.monotonic()
    try:
        result = high_level.translate(config)
    finally:
        seconds = time.monotonic() - started

    mono = getattr(result, "mono_pdf_path", None)
    final_pdf = None
    if mono:
        final_pdf = destination / f"{SAMPLE}.{RUN}.pdf"
        shutil.copyfile(mono, final_pdf)

    working = Path(config.working_dir)
    kept = destination / "sidecars"
    kept.mkdir(parents=True, exist_ok=True)
    for name in SIDECARS:
        source = working / name
        if source.exists():
            shutil.copyfile(source, kept / name)

    record = {
        "sample": f"{SAMPLE}.pdf",
        "tag": tag,
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
        "working_dir": str(working.relative_to(ROOT)),
        "ruling": ruling(SAMPLE),
        "switches": switches,
        "raster": raster(final_pdf, SAMPLE, destination / "raster")
        if final_pdf
        else [],
        "sidecars": sorted(str(path.relative_to(ROOT)) for path in kept.glob("*.json")),
        "conservation": conservation(working, destination),
        "translation_style": {
            "person_names": translation_style.load_style_config().person_names,
            "system_prompt_sha256": None
            if style_prompt is None
            else hashlib.sha256(style_prompt.encode("utf-8")).hexdigest(),
        },
    }
    with (destination / "run.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(
        json.dumps(
            {key: value for key, value in record.items() if key != "raster"},
            indent=2,
            ensure_ascii=False,
        ),
        flush=True,
    )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_one(DocLayoutModel.load_onnx(), args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
