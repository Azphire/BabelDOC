"""R1: the three runs that make neighbour drift attributable.

Batch b5.3 measured fifteen paragraphs of Courier-en changing between a run
with chain level joint translation down and one with it up, and could not say
why. Four of the fifteen are the chain members themselves; the other eleven are
their batch neighbours, and their changes are single word substitutions of the
same size this engine produces when the same prompt is sent twice. The design
that measured them could not separate the two causes, because a paragraph whose
prompt did not change was served from the cache and was therefore identical by
construction rather than by measurement.

Three runs settle it. Two ``chain_off`` arms sample the engine independently on
identical prompts, which is the repeat noise; one ``chain_on`` arm replays the
frozen configuration, which is the observed effect. A paragraph the two off
arms already disagree about is noise; a paragraph they agree about and the on
arm differs from is the recomposition.

Independence, and why it is a cache namespace rather than ``ignore_cache``
-------------------------------------------------------------------------

The second off arm must not be able to read the first arm's answers. Setting
``ignore_cache`` on the engine would achieve that, but it also stops the
answers being written, and an arm that was never filed cannot be replayed --
the evaluation protocol of this project is frozen replay, and an unrepeatable
paid run is the one thing it does not allow. So each off arm instead declares a
cache impact parameter of its own. That changes the key the answer is filed
under and nothing about the request on the wire: the two arms send byte
identical prompts, neither can serve the other, and both are on disk afterwards
to be replayed for nothing. The gate asserts the two keys differ, which is what
makes "independent sample" checkable rather than asserted.

The on arm declares no such parameter, so it lands in the shared namespace the
frozen full stack run of batch b8.4 filled and replays it at no cost.

What is traced
--------------

Every request the translator built, with the paragraphs that were in the batch
it was built from. That is the discriminator b5.3 lacked: a paragraph whose
prompt is byte identical across two arms and whose translation is not can only
have been resampled, and a paragraph whose prompt moved was asked a different
question. The wrapping is observation only -- both wrappers call through and
return what they were given.

Usage:
    python tools/run_drift_trio.py                 # all three arms
    python tools/run_drift_trio.py --arm chain_on  # one arm
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.docvision.doclayout import DocLayoutModel  # noqa: E402
from babeldoc.format.pdf import high_level  # noqa: E402
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (  # noqa: E402
    ILTranslatorLLMOnly,
)
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.format.pdf.translation_config import WatermarkOutputMode  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.cache_setup import PROJECT_CACHE_RELPATH  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "e2" / "r1"

SAMPLE = "Courier-en"
MODEL = "gpt-4o"
QPS = 4

# The cache impact parameter an off arm declares so that it cannot be served by
# the other one. Its value is the arm name; the on arm declares nothing and so
# stays in the shared namespace the frozen run filled.
ARM_CACHE_KEY = "e2_r1_arm"

TRACE_NAME = "prompt_trace.json"

# The configuration of the frozen full stack run (batch b8.4), unchanged. The
# three arms differ in exactly one switch, so a difference between them is that
# switch's doing and nothing else's.
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

# The three arms, in the order they are run. The on arm goes first because it
# spends nothing: if it does not replay from cache, the setup is wrong and the
# two paid arms have not been launched yet.
ARMS = (
    {"name": "chain_on", "chain_translate": True, "namespace": None},
    {"name": "chain_off_1", "chain_translate": False, "namespace": "off1"},
    {"name": "chain_off_2", "chain_translate": False, "namespace": "off2"},
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


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_engine(namespace: str | None) -> OpenAITranslator:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    engine = OpenAITranslator(
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
    if namespace is not None:
        engine.add_cache_impact_parameters(ARM_CACHE_KEY, namespace)
    return engine


def cache_rows_by_engine(db_path: Path) -> dict[str, int]:
    """How many answers each caching client has filed, by engine name.

    The translator writes one row per request it did not have, so the delta
    across a run is that run's spend measured at the database rather than taken
    from a counter the run kept about itself.
    """
    if not db_path.is_file():
        return {}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT translate_engine, COUNT(*) FROM _translationcache GROUP BY 1"
        ).fetchall()
    finally:
        connection.close()
    return {name: count for name, count in rows}


class PromptTrace:
    """Every request the translator built, with the batch it was built from.

    Taken around the batch entry point and the prompt builder together: the
    builder is called once per batch from the thread the batch is being
    translated on, so a thread local is enough to say which batch a prompt
    belongs to. A prompt built with no batch open is the chain pass building
    its merged request through the same template, and is recorded as such.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: list[dict] = []
        self._local = threading.local()
        self._lock = threading.Lock()
        self._restore: list[tuple[object, str, object]] = []

    def install(self) -> None:
        original_batch = ILTranslatorLLMOnly.translate_paragraph

        def traced_batch(inner_self, batch_paragraph, *args, **kwargs):
            row = {
                "kind": "batch",
                "paragraphs": [
                    paragraph.debug_id for paragraph in batch_paragraph.paragraphs
                ],
                "pages": sorted(
                    {
                        page.page_number
                        for page in batch_paragraph.pages
                        if page is not None
                    }
                ),
            }
            self._local.current = row
            try:
                return original_batch(inner_self, batch_paragraph, *args, **kwargs)
            finally:
                self._local.current = None
                with self._lock:
                    self.rows.append(row)

        ILTranslatorLLMOnly.translate_paragraph = traced_batch
        self._restore.append(
            (ILTranslatorLLMOnly, "translate_paragraph", original_batch)
        )

        original_prompt = ILTranslatorLLMOnly._build_llm_prompt

        def traced_prompt(inner_self, *args, **kwargs):
            text = original_prompt(inner_self, *args, **kwargs)
            row = getattr(self._local, "current", None)
            if row is None:
                with self._lock:
                    self.rows.append(
                        {
                            "kind": "chain",
                            "paragraphs": [],
                            "pages": [],
                            "prompt_sha256": digest(text),
                            "prompt_text": text,
                        }
                    )
            else:
                row["prompt_sha256"] = digest(text)
                row["prompt_text"] = text
            return text

        ILTranslatorLLMOnly._build_llm_prompt = traced_prompt
        self._restore.append(
            (ILTranslatorLLMOnly, "_build_llm_prompt", original_prompt)
        )

    def remove(self) -> None:
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore.clear()

    def write(self) -> None:
        payload = sorted(
            self.rows,
            key=lambda row: (row["kind"], row.get("prompt_sha256") or ""),
        )
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)


def isolate_reviews(name: str, destination: Path) -> Path:
    """Point the review layer at this run's own directory, with the ruling in it.

    The corpus ruling is an input to every arm and is never written by one: the
    run reads its copy and writes its draft beside that copy.
    """
    reviews = destination / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    source = hitl.DEFAULT_REVIEWS_DIR / f"{name}{hitl.DECISIONS_SUFFIX}"
    if source.exists():
        shutil.copyfile(source, reviews / source.name)
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    return reviews


def run_one(arm: dict, layout_model) -> dict:
    pdf = INPUT_DIR / f"{SAMPLE}.pdf"
    destination = OUT_DIR / arm["name"]
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    isolate_reviews(SAMPLE, destination)
    trace = PromptTrace(destination / TRACE_NAME)
    engine = build_engine(arm["namespace"])
    switches = dict(STACK)
    switches["magazine_chain_translate"] = arm["chain_translate"]
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
        **switches,
    )
    for attribute, value in ATTRIBUTES.items():
        setattr(config, attribute, value)

    db_path = ROOT / PROJECT_CACHE_RELPATH
    before = cache_rows_by_engine(db_path)

    trace.install()
    started = time.monotonic()
    try:
        result = high_level.translate(config)
    finally:
        seconds = time.monotonic() - started
        trace.remove()
    trace.write()

    after = cache_rows_by_engine(db_path)
    filed = {
        name: after[name] - before.get(name, 0)
        for name in sorted(after)
        if after[name] - before.get(name, 0) != 0
    }

    mono = getattr(result, "mono_pdf_path", None)
    produced = None
    if mono:
        produced = OUT_DIR / f"{SAMPLE}.{arm['name']}.pdf"
        shutil.copyfile(mono, produced)

    record = {
        "arm": arm["name"],
        "sample": f"{SAMPLE}.pdf",
        "model": MODEL,
        "magazine_chain_translate": arm["chain_translate"],
        "cache_namespace": arm["namespace"],
        "cache_engine": engine.cache.translate_engine,
        "cache_key_params": engine.cache.translate_engine_params,
        "cache_key_sha256": digest(
            engine.cache.translate_engine + engine.cache.translate_engine_params
        ),
        "seconds": round(seconds, 1),
        "requests": engine.translate_call_count,
        "cache_hits": engine.translate_cache_call_count,
        "api_calls": engine.translate_call_count - engine.translate_cache_call_count,
        "prompt_tokens": engine.prompt_token_count.value,
        "completion_tokens": engine.completion_token_count.value,
        "cache_rows_filed": filed,
        "working_dir": str(Path(config.working_dir).relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "mono_pdf": None if produced is None else produced.name,
        "mono_pdf_sha256": None if produced is None else file_digest(produced),
        "prompt_trace": TRACE_NAME,
        "prompt_batches": sum(1 for row in trace.rows if row["kind"] == "batch"),
        "chain_prompts": sum(1 for row in trace.rows if row["kind"] == "chain"),
    }
    with (destination / "run.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(json.dumps(record, indent=2, ensure_ascii=False), flush=True)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arm",
        action="append",
        default=None,
        choices=[arm["name"] for arm in ARMS],
        help="run one arm rather than all three",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = [arm for arm in ARMS if args.arm is None or arm["name"] in args.arm]
    layout_model = DocLayoutModel.load_onnx()
    ledger = [run_one(arm, layout_model) for arm in wanted]

    path = OUT_DIR / "runs.json"
    existing = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            done = {row["arm"] for row in ledger}
            existing = [row for row in json.load(f) if row["arm"] not in done]
    order = {arm["name"]: index for index, arm in enumerate(ARMS)}
    rows = sorted(existing + ledger, key=lambda row: order[row["arm"]])
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
