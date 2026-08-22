"""B11.2 driver: the samples the exposure probe selected, on arm only.

Which samples run is not declared here. ``exposure.report.json`` counts, over
the b10.5 on arm, how many paragraphs b11.1's identity change reaches and how
many lines its hang bound reaches; a sample both counts are zero for cannot be
changed by either and is not run. This driver reads that list rather than
carrying one, so the range of the batch is auditable against the evidence that
set it.

One arm, per CLAUDE.md section 4.14: the assertions this batch makes are about
the end state of a run, not about the difference between two runs, so the off
arm would double the cost and the disk to answer nothing.

The switch set is read out of the f3 run record of the same sample rather than
retyped, which is how every driver since b7 has raised them.

Usage:
    python run_b11_2.py [--only SAMPLE ...]
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
OUT_DIR = ROOT / "examples" / "output" / "b11_2"
EXPOSURE = OUT_DIR / "exposure.report.json"
BASELINE_BATCH = ROOT / "examples" / "output" / "b10_5"
F3 = ROOT / "examples" / "output" / "F3" / "cold"

MODEL = "gpt-4o"
QPS = 4
RUN = "b11_2"
DPI = 110
CHECKPOINT = "checkpoint.11_typesetting.json"

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
PLAIN_ATTRIBUTES = ("magazine_drop_cap_mark", "magazine_drop_cap_apply")
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
    "identity_criterion.report.json",
    title_typeset.REPORT_NAME,
    column_reflow.REPORT_NAME,
    "issues.json",
    "react_repair.report.json",
)


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def selected_samples() -> list[str]:
    """The samples the exposure probe found a surface on."""
    with EXPOSURE.open(encoding="utf-8") as f:
        return list(json.load(f)["must_run"])


def baseline_switches(sample: str) -> dict:
    with (F3 / sample / "run.json").open(encoding="utf-8") as f:
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
    path = hitl.decisions_path(sample)
    if not path.exists():
        return {"path": None, "sha256": None, "present": False}
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
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
    import pymupdf

    destination.mkdir(parents=True, exist_ok=True)
    written = []
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document):
            path = destination / f"{sample}.p{index + 1}.png"
            page.get_pixmap(dpi=DPI).save(path)
            written.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    return written


def paragraph_texts(document: dict, label: int) -> list[str]:
    for page in document.get("page", ()):
        if page.get("page_number", -1) + 1 == label:
            return [
                paragraph.get("unicode") or ""
                for paragraph in page.get("pdf_paragraph") or ()
            ]
    return []


def conservation(sample: str, working: Path, destination: Path) -> str | None:
    """This run's typesetting document beside the b10.5 on arm it answers to."""
    path = working / CHECKPOINT
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        document = json.load(f)
    baseline_path = (
        BASELINE_BATCH / sample / "on" / "work" / sample / CHECKPOINT
    )
    baseline = None
    if baseline_path.is_file():
        with baseline_path.open(encoding="utf-8") as f:
            baseline = json.load(f)

    pages = {}
    for label in range(1, len(document.get("page") or ()) + 1):
        texts = paragraph_texts(document, label)
        row = {
            "paragraphs": len(texts),
            "text": {f"p{label}#{index}": text for index, text in enumerate(texts)},
        }
        if baseline is not None:
            before = paragraph_texts(baseline, label)
            row["baseline_paragraphs"] = len(before)
            row["baseline_text"] = {
                f"p{label}#{index}": text for index, text in enumerate(before)
            }
        pages[str(label)] = row
    record = {
        "sample": sample,
        "baseline": str(baseline_path.relative_to(ROOT)).replace("\\", "/"),
        "baseline_pages": len(baseline.get("page") or ()) if baseline else None,
        "pages": len(document.get("page") or ()),
        "per_page": pages,
    }
    out = destination / "conservation.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return str(out.relative_to(ROOT)).replace("\\", "/")


def run_one(sample: str, layout_model) -> dict:
    pdf = INPUT_DIR / f"{sample}.pdf"
    destination = OUT_DIR / sample
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    source_lang, target_lang = corpus.direction_of(sample)
    switches = baseline_switches(sample)
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
        "arm": "on",
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
        "pdf": str(final_pdf.relative_to(ROOT)).replace("\\", "/") if final_pdf else None,
        "pdf_sha256": digest(final_pdf) if final_pdf else None,
        "working_dir": str(working.relative_to(ROOT)).replace("\\", "/"),
        "ruling": ruling(sample),
        "switches": switches,
        "raster": raster(final_pdf, sample, destination / "raster") if final_pdf else [],
        "sidecars": sorted(
            str(path.relative_to(ROOT)).replace("\\", "/") for path in kept.glob("*.json")
        ),
        "conservation": conservation(sample, working, destination),
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
        f"{sample}: {record['seconds']}s requests={record['requests']} "
        f"hits={record['cache_hits']} api={record['api_calls']} "
        f"pages={record['output_pages']}",
        flush=True,
    )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    samples = args.only or selected_samples()
    print(f"samples selected by the exposure probe: {samples}", flush=True)
    model = DocLayoutModel.load_onnx()
    ledger = []
    for sample in samples:
        ledger.append(run_one(sample, model))
    with (OUT_DIR / "runs.json").open("w", encoding="utf-8") as f:
        json.dump({"runs": ledger}, f, indent=2, ensure_ascii=False)
    total = sum(r["api_calls"] for r in ledger)
    print(f"done: {len(ledger)} runs, {total} api calls", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
