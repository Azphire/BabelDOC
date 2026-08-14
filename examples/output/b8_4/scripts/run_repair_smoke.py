"""B8.4 real-API smoke driver: the same stack again, with the repair landing.

The configuration is the one batch b8.3 ran, unchanged, so that a difference
between its output and this one is this batch's doing. What changed is
underneath: a rotated paragraph is read in the order it is read in, a repair
that improves a finding without clearing it counts as progress rather than as
nothing, and the request that chooses what to repair states the rule it is
feeding. Whether that lands the repair in the produced PDF is what this run
answers.

Three things are observed as the run makes them, all by wrapping and all
observation only -- each wrapper calls through and returns what it got. The two
prompt builders and the transport are traced into `prompt_trace.jsonl`, so a
claim about what a request carried can be read rather than inferred. And the
repair loop itself is wrapped, so the paragraphs it writes are snapshotted
before and after it writes them: the box, the orientation flag and the text.
Nothing else records what a repaired paragraph looked like on either side of
the repair, and that pair is the whole of the landing evidence.

Not part of the gate: this is the only thing in the batch that spends a
credential.

Usage:
    python run_repair_smoke.py --sample Courier-en
    python run_repair_smoke.py --all
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
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.detectors import base as detector_base  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b8_4" / "smoke"

MODEL = "gpt-4o"
QPS = 4

BATCH = "b8_4"
TRACE_NAME = "prompt_trace.jsonl"
PARAGRAPHS_NAME = "paragraphs.json"

# The main evidence sample. The other five are the regression face.
PRIMARY = "Courier-en"

# Every magazine switch the stack has, up. Identical to what b8.3 ran.
STACK = {
    "magazine_checkpoint": True,
    "magazine_page_classify": True,
    "magazine_chain_detect": True,
    "magazine_chain_translate": True,
    "magazine_article_group": True,
    "magazine_article_context": True,
    "magazine_hitl_export": True,
    "magazine_hitl_apply": True,
    "magazine_detect": True,
}

# Switches that are not constructor parameters (W-B7-02, W-B8-01).
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
        os.environ.setdefault(name.strip(), value.strip().strip('"\''))


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


def paragraph_state(docs) -> dict:
    """Every paragraph of a document as box, orientation and rendered text."""
    state: dict[str, dict] = {}
    for label, page in hitl.labeled_pages(docs):
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            state[f"p{label}#{index}"] = {
                "box": detector_base.box_tuple(paragraph.box),
                "vertical": paragraph.vertical,
                "layout_label": paragraph.layout_label,
                "text": detector_base.rendered_text(paragraph),
            }
    return state


class Trace:
    """Append-only record of every prompt the loop rendered and every reply."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._restore: list[tuple[object, str, object]] = []

    def write(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _wrap_prompt(self, owner, kind: str) -> None:
        original = owner.prompt

        def traced(inner_self, *args, **kwargs):
            prompt = original(inner_self, *args, **kwargs)
            self.write(
                {
                    "kind": kind,
                    "prompt_file": prompt.path.name,
                    "prompt_sha256": prompt.digest,
                    "prompt_text": prompt.text,
                }
            )
            return prompt

        owner.prompt = traced
        self._restore.append((owner, "prompt", original))

    def install(self) -> None:
        self._wrap_prompt(decide.CachedDecisionClient, "decide_prompt")
        self._wrap_prompt(actions.CachedOrphanTranslator, "orphan_prompt")

        original = decide.EngineTransport.complete

        def traced(inner_self, prompt_text: str) -> str:
            reply = original(inner_self, prompt_text)
            self.write({"kind": "transport", "sent": prompt_text, "reply": reply})
            return reply

        decide.EngineTransport.complete = traced
        self._restore.append((decide.EngineTransport, "complete", original))

    def remove(self) -> None:
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore.clear()


class Paragraphs:
    """The document either side of the loop, for the paragraphs the loop wrote.

    Taken around ``RepairLoop.run`` because that is the only moment both states
    exist: the typesetting checkpoint is the document before the loop and the
    produced PDF is a rendering of the document after it, and neither is the
    other's units. What is written is one entry per paragraph the run touched,
    plus one for the subject of the batch whether or not it was touched.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._restore: list[tuple[object, str, object]] = []
        self.rows: dict[str, dict] = {}

    def install(self) -> None:
        original = controller.RepairLoop.run

        def traced(loop_self):
            before = paragraph_state(loop_self.docs)
            issues = original(loop_self)
            after = paragraph_state(loop_self.docs)
            self.rows = {
                "before": before,
                "after": after,
                "changed": sorted(
                    reference
                    for reference in set(before) | set(after)
                    if before.get(reference) != after.get(reference)
                ),
            }
            self.write()
            return issues

        controller.RepairLoop.run = traced
        self._restore.append((controller.RepairLoop, "run", original))

    def write(self) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.rows, f, indent=2, ensure_ascii=False, sort_keys=True)

    def remove(self) -> None:
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore.clear()


def isolate_reviews(name: str, destination: Path) -> Path:
    """Point the review layer at this run's own directory, with the ruling in it."""
    reviews = destination / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    source = hitl.DEFAULT_REVIEWS_DIR / f"{name}{hitl.DECISIONS_SUFFIX}"
    if source.exists():
        shutil.copyfile(source, reviews / source.name)
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    return reviews


def snapshot_reviews(name: str, destination: Path) -> list[str]:
    kept = []
    for path in (
        hitl.review_path(name),
        hitl.review_html_path(name),
        hitl.decisions_path(name),
    ):
        if path.exists():
            shutil.copyfile(path, destination / path.name)
            kept.append(path.name)
    return kept


def run_one(sample: str, layout_model) -> dict:
    pdf = INPUT_DIR / f"{sample}.pdf"
    destination = OUT_DIR / sample
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    isolate_reviews(sample, destination)
    trace = Trace(destination / TRACE_NAME)
    paragraphs = Paragraphs(destination / PARAGRAPHS_NAME)
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
    )
    for attribute, value in ATTRIBUTES.items():
        setattr(config, attribute, value)

    trace.install()
    paragraphs.install()
    started = time.monotonic()
    try:
        result = high_level.translate(config)
    finally:
        seconds = time.monotonic() - started
        paragraphs.remove()
        trace.remove()

    mono = getattr(result, "mono_pdf_path", None)
    if mono:
        shutil.copyfile(mono, OUT_DIR / f"{sample}.{BATCH}.pdf")

    record = {
        "sample": f"{sample}.pdf",
        "model": MODEL,
        "seconds": round(seconds, 1),
        "requests": engine.translate_call_count,
        "cache_hits": engine.translate_cache_call_count,
        "api_calls": engine.translate_call_count - engine.translate_cache_call_count,
        "prompt_tokens": engine.prompt_token_count.value,
        "completion_tokens": engine.completion_token_count.value,
        "working_dir": str(Path(config.working_dir).relative_to(ROOT)),
        "mono_pdf": f"{sample}.{BATCH}.pdf" if mono else None,
        "reviews": snapshot_reviews(sample, destination),
    }
    with (destination / "run.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(json.dumps(record, indent=2, ensure_ascii=False), flush=True)
    return record


def samples() -> list[str]:
    names = [
        Path(entry["file"]).stem for entry in corpus.load_manifest().get("samples", ())
    ]
    return [PRIMARY, *sorted(name for name in names if name != PRIMARY)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = samples() if args.all else (args.sample or [PRIMARY])
    layout_model = DocLayoutModel.load_onnx()
    ledger = []
    for sample in wanted:
        ledger.append(run_one(sample, layout_model))
    path = OUT_DIR / "runs.json"
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
