"""B8.3 real-API smoke driver: the whole magazine stack with the repair loop up.

One configuration, every sample. The stack is the one batch-b7.5.2 ran, with
detection and the repair loop added and nothing else moved: the ruling is
applied exactly as it was, so every body paragraph is the request it already
was and is replayed from the project cache. What costs a call is what is new --
the loop's decision points and the orphan lines it sends -- and that is the
point of holding the rest still, because then a difference between this run's
output and batch-b7.5.2's is the loop's doing or it is a defect.

The loop's own requests are recorded as they are made. The sidecar the loop
writes carries what was decided and what came back; what it does not carry is
the exact text that was sent, and a claim about a glossary entry reaching a
prompt is not worth much without the prompt. So the two prompt builders and the
transport are wrapped here, in the driver, and every rendered prompt and every
reply is appended to `prompt_trace.jsonl` beside the run. Wrapping is observation
only: each wrapper calls through and returns what it got.

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
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b8" / "smoke"

MODEL = "gpt-4o"
QPS = 4

TRACE_NAME = "prompt_trace.jsonl"

# The main evidence sample. The other five are the regression face.
PRIMARY = "Courier-en"

# Every magazine switch the stack has, up. Identical to the batch-b7.5.2 second
# pass except for the last two, which are what this batch adds.
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


class Trace:
    """Append-only record of every prompt the loop rendered and every reply.

    Installed by wrapping, and uninstalled afterwards, so a second sample in the
    same process is traced into its own file rather than the previous one's.
    """

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


def isolate_reviews(name: str, destination: Path) -> Path:
    """Point the review layer at this run's own directory, with the ruling in it.

    The export switch writes a draft every run, and the repository's `reviews/`
    is a reviewed, committed directory: a smoke run that rewrote the drafts
    there would put the working tree in a state no gate can distinguish from an
    edit. So the layer is redirected here and the ruling is copied in, which is
    a read of the committed file and the only contact this run has with it.
    """
    reviews = destination / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    source = hitl.DEFAULT_REVIEWS_DIR / f"{name}{hitl.DECISIONS_SUFFIX}"
    if source.exists():
        shutil.copyfile(source, reviews / source.name)
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    return reviews


def snapshot_reviews(name: str, destination: Path) -> list[str]:
    """Freeze the draft and the ruling this run read, beside the run."""
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
    started = time.monotonic()
    try:
        result = high_level.translate(config)
    finally:
        seconds = time.monotonic() - started
        trace.remove()

    mono = getattr(result, "mono_pdf_path", None)
    if mono:
        shutil.copyfile(mono, OUT_DIR / f"{sample}.b8_3.pdf")

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
        "mono_pdf": f"{sample}.b8_3.pdf" if mono else None,
        "reviews": snapshot_reviews(sample, destination),
    }
    with (destination / "run.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(json.dumps(record, indent=2, ensure_ascii=False), flush=True)
    return record


def samples() -> list[str]:
    """Every registered sample, the main evidence one first."""
    names = [
        Path(entry["file"]).stem for entry in corpus.load_manifest().get("samples", ())
    ]
    return [PRIMARY, *sorted(name for name in names if name != PRIMARY)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    wanted = samples() if args.all else args.sample
    if not wanted:
        parser.error("name at least one --sample, or pass --all")

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    layout_model = DocLayoutModel.load_onnx()
    ledger_path = OUT_DIR / "runs.json"
    for sample in wanted:
        record = run_one(sample, layout_model)
        existing = []
        if ledger_path.exists():
            with ledger_path.open(encoding="utf-8") as f:
                existing = json.load(f)
        keyed = {entry["sample"]: entry for entry in [*existing, record]}
        with ledger_path.open("w", encoding="utf-8") as f:
            json.dump(
                [keyed[key] for key in sorted(keyed)], f, indent=2, ensure_ascii=False
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
