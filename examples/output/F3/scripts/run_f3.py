"""F3 driver: the whole stack over every corpus sample, with the stages timed.

Same shape as the F2 driver a cycle ago -- one run per sample, every magazine
switch up, the rulings under ``reviews/`` governing the samples that have one --
plus the two things this cycle's closing run owes.

The first is the pass batch b10.5 added, ``magazine_column_reflow``, which is off
by default and is turned up here: the standard run configuration is where a pass
whose default is off becomes part of the stack.

The second is a stage timing sidecar. It is pure observation and changes nothing
about what is produced: a progress callback records the wall clock of every
pipeline stage, which is the measurement b11 needs to aim at a stage rather than
at a guess. Getting it needs no upstream edit -- ``high_level.translate`` is a
two line wrapper that builds a ``ProgressMonitor`` and calls ``do_translate``, so
the driver builds the monitor itself, with a callback, and calls the same
function.

Cache temperature is a property of a run, not of the stack, so it is recorded.
``--arm warm`` is the arm whose timings are citable; ``--arm cold`` is the
warm-up that fills the cache with whatever this stack asks for the first time,
and is kept separately and labelled, because a stage that waited on the network
is not a stage that is slow.

Usage:
    python run_f3.py --all --arm cold
    python run_f3.py --all --arm warm
    python run_f3.py --sample Courier-en --arm warm
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
from babeldoc.progress_monitor import ProgressMonitor  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "F3"

MODEL = "gpt-4o"
QPS = 4
RUN = "f3"

# The two arms, and what each is for. Only the warm one's timings are citable.
ARMS = ("cold", "warm")

# Constructor switches. Export is down for the reason F2 gave: export writes its
# drafts into the user's directory, and a run whose purpose is to consume a
# ruling has no business rewriting the drafts beside it.
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

# Switches that are not constructor parameters (W-B7-02, W-B8-01).
ATTRIBUTES = {
    "magazine_drop_cap_mark": True,
    "magazine_drop_cap_apply": True,
    title_typeset.SWITCH: True,
    line_split.SWITCH: True,
    fragment_stitch.SWITCH: True,
    react.SWITCH: True,
    paren_dedup.SWITCH: True,
    column_reflow.SWITCH: True,
    backfill.load_backfill_config().align_switch: True,
    fragment_stitch.load_stitch_config().declared_page_switch: True,
    short_unit.load_short_unit_config().switch: True,
    name_harvest.load_harvest_config().switch: True,
}

# The sidecars kept beside each sample's products. A run's own working directory
# is pruned; these are the files the report reads back.
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


class StageClock:
    """Wall clock per pipeline stage, taken off the progress callback.

    The monitor emits ``progress_start`` when a stage opens and ``progress_end``
    when it closes, both carrying the stage's name. A stage that runs more than
    once -- which the display name marks -- accumulates, and the number of runs
    is kept beside the total so a large figure cannot be read as one slow pass
    when it is many quick ones.
    """

    def __init__(self) -> None:
        self.open: dict[str, float] = {}
        self.totals: dict[str, float] = {}
        self.runs: dict[str, int] = {}
        self.order: list[str] = []

    def __call__(self, **event) -> None:
        kind = event.get("type")
        stage = event.get("stage")
        if not stage or kind not in {"progress_start", "progress_end"}:
            return
        if kind == "progress_start":
            self.open[stage] = time.monotonic()
            if stage not in self.order:
                self.order.append(stage)
            return
        started = self.open.pop(stage, None)
        if started is None:
            return
        self.totals[stage] = self.totals.get(stage, 0.0) + (time.monotonic() - started)
        self.runs[stage] = self.runs.get(stage, 0) + 1

    def record(self) -> list[dict]:
        return [
            {
                "stage": stage,
                "seconds": round(self.totals.get(stage, 0.0), 3),
                "runs": self.runs.get(stage, 0),
            }
            for stage in self.order
        ]


def raster(pdf: Path, sample: str, destination: Path) -> list[str]:
    """Every page of one produced PDF as an image, for reading by eye."""
    import pymupdf

    destination.mkdir(parents=True, exist_ok=True)
    written = []
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document):
            path = destination / f"{sample}.p{index + 1}.png"
            page.get_pixmap(dpi=110).save(path)
            written.append(str(path.relative_to(ROOT)))
    return written


def run_one(sample: str, arm: str, layout_model) -> dict:
    pdf = INPUT_DIR / f"{sample}.pdf"
    destination = OUT_DIR / arm / sample
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    # The direction is the corpus owner's declaration for this sample, read here
    # rather than carried by the driver: the corpus holds both a Chinese and an
    # English edition of one magazine.
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
    style_prompt = translation_style.apply(config, target_lang)

    clock = StageClock()
    started = time.monotonic()
    try:
        with ProgressMonitor(
            high_level.get_translation_stage(config),
            progress_change_callback=clock,
        ) as monitor:
            result = high_level.do_translate(monitor, config)
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

    stages = clock.record()
    record = {
        "sample": f"{sample}.pdf",
        "arm": arm,
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
        "ruling": ruling(sample),
        "switches": {**STACK, **dict.fromkeys(ATTRIBUTES, True)},
        "stages": stages,
        "stage_seconds_total": round(sum(row["seconds"] for row in stages), 3),
        "raster": raster(final_pdf, sample, destination / "raster")
        if final_pdf
        else [],
        "sidecars": sorted(str(path.relative_to(ROOT)) for path in kept.glob("*.json")),
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


def samples() -> list[str]:
    return [
        Path(entry["file"]).stem for entry in corpus.load_manifest().get("samples", ())
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--arm", choices=ARMS, default="warm")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    (OUT_DIR / args.arm).mkdir(parents=True, exist_ok=True)

    wanted = samples() if args.all else (args.sample or ["Courier-en"])
    layout_model = DocLayoutModel.load_onnx()
    ledger = []
    for sample in wanted:
        ledger.append(run_one(sample, args.arm, layout_model))

    path = OUT_DIR / args.arm / "runs.json"
    existing = []
    if path.exists() and not args.all:
        with path.open(encoding="utf-8") as f:
            existing = [
                row
                for row in json.load(f)
                if row["sample"] not in {item["sample"] for item in ledger}
            ]
    with path.open("w", encoding="utf-8") as f:
        json.dump(existing + ledger, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
