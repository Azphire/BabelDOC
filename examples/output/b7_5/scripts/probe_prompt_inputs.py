"""What text the translator is actually offered for each masthead site.

The review draft shows a human the paragraph's joined ``unicode``. The glossary
matches against the text the batch is built from, which carries the rich text
markup the paragraph's style runs imply. Where a display masthead is set in
several styles the two strings differ, and a ruling keyed on the one the human
was shown cannot match the one the machine matches on.

This probe records both, so that claim in the report rests on captured prompts
rather than on reasoning about them. It uses a stub translator and spends no
credential: what is wanted is the prompt the pipeline builds, not an answer.

Usage:
    python probe_prompt_inputs.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf import high_level  # noqa: E402
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (  # noqa: E402
    ILTranslatorLLMOnly,
)
from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.progress_monitor import ProgressMonitor  # noqa: E402
from babeldoc.translator.translator import BaseTranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b7_5"
WORK = OUT_DIR / "pass2" / "work" / "Courier-en"
SOURCE_STAGE = "checkpoint.08_chain_builder.xml"

# The header the batch input follows in the prompt, and the rate the stub runs
# at: neither is a tuning knob, both are how the prompt is taken apart.
INPUT_HEADER = "## Here is the input:"
STUB_QPS = 16

# The word that identifies a masthead site.
NEEDLE = "Courier"


class StubTranslator(BaseTranslator):
    name = "b7-5-probe"

    def __init__(self):
        super().__init__("en", "zh", ignore_cache=True)
        self.prompts: list[str] = []
        self.lock = threading.Lock()

    def do_translate(self, text, rate_limit_params: dict = None):
        return text

    def do_llm_translate(self, text, rate_limit_params: dict = None):
        if text is None:
            return None
        with self.lock:
            self.prompts.append(text)
        if INPUT_HEADER not in text:
            return "stub"
        return json.dumps(
            [
                {"id": item["id"], "output": item["input"]}
                for item in json.loads(text.split(INPUT_HEADER, 1)[1].strip())
            ]
        )


def main() -> int:
    os.environ[hitl.REVIEWS_ENV] = str(ROOT / "reviews")
    set_translate_rate_limiter(STUB_QPS)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs = checkpoint_module.load_checkpoint(WORK / SOURCE_STAGE)

    joined = [
        paragraph.unicode
        for page in docs.page
        for paragraph in page.pdf_paragraph or []
        if NEEDLE in (paragraph.unicode or "")
    ]

    work = OUT_DIR / "probe" / "work"
    work.mkdir(parents=True, exist_ok=True)
    monitor = ProgressMonitor([(ILTranslatorLLMOnly.stage_name, 1.0)])
    monitor.disable = True
    config = TranslationConfig(
        translator=StubTranslator(),
        input_file=str(ROOT / "examples" / "input" / "Courier-en.pdf"),
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        working_dir=work,
        output_dir=work / "out",
        progress_monitor=monitor,
        auto_extract_glossary=False,
        qps=STUB_QPS,
        magazine_hitl_apply=True,
        magazine_article_context=True,
    )
    high_level.hitl.after_term_extract(config, docs)
    ILTranslatorLLMOnly(config.translator, config).translate(docs)

    offered = []
    for prompt in config.translator.prompts:
        if INPUT_HEADER not in prompt:
            continue
        for item in json.loads(prompt.split(INPUT_HEADER, 1)[1].strip()):
            if NEEDLE in item.get("input", ""):
                offered.append(item["input"])

    ruling = json.loads(
        (ROOT / "reviews" / f"Courier-en{hitl.DECISIONS_SUFFIX}").read_text(
            encoding="utf-8"
        )
    )
    ruled = [source for source in ruling["terms"] if NEEDLE in source]

    evidence = {
        "joined_unicode_the_draft_shows": sorted(set(joined)),
        "text_the_translator_is_offered": sorted(set(offered)),
        "ruled_sources": ruled,
        "ruled_source_matches_offered_text": {
            source: sorted({text for text in set(offered) if source in text})
            for source in ruled
        },
        "prompts_captured": len(config.translator.prompts),
    }
    with (OUT_DIR / "prompt_inputs.evidence.json").open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)

    print("joined unicode the review draft shows:")
    for text in evidence["joined_unicode_the_draft_shows"]:
        print(f"  {text!r}")
    print("\ntext the translator is offered:")
    for text in evidence["text_the_translator_is_offered"]:
        print(f"  {text!r}")
    print("\nruled source -> offered texts it matches:")
    for source, matches in evidence["ruled_source_matches_offered_text"].items():
        print(f"  {source!r}: {matches}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
