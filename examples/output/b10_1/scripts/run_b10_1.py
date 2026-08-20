"""B10.1 driver: the four samples the batch's fixes are visible on.

The stack is F2's stack plus the parenthetical folding pass this batch adds, so
what comes out is comparable with F2 page for page. Every sample is translated
whole rather than page ranged: the requests a run builds depend on how its pages
group into articles and chains, so a page range would build requests F2 never
built, and a request F2 never built is a request the cache cannot answer. Whole
documents keep every request byte identical to F2's, which is what makes this a
replay at no cost -- the ledger records the API call count per sample and the
gate asserts it is no higher than the same sample's F2 run recorded, which is
the only reading of "spent nothing new" the corpus can answer for: one sample
already sent one uncached request in F2 and sends the same one here.

What is written out is bounded instead: the pages of the evidence table below,
as PNG and as a PDF holding those pages alone, plus the sidecars the batch's
fixes are recorded in. The whole document stays in the working directory, which
is not what a reader of the batch is handed.

Beside those go two frozen comparisons against F2, both written here rather than
left to be recomputed from the working directories: those are not tracked and the
retention policy eventually takes them, and an assertion that cannot be made a
year from now is not an assertion.

``conservation.json`` is the shape comparison: page count, per target page
paragraph count, and every paragraph of a target page whose text is not the one
F2 produced.

``parity.json`` is this run's requests set against F2's, request
for request. It carries the digest of every request text of each run and the
outputs that came back different from the same text. Both are needed to read the
result honestly. The first is the batch's real conservation claim -- none of
these fixes reaches a request, so every request has to be F2's byte for byte.
The second is the limit of that claim: a request the cache cannot answer is sent
again, and this model does not answer twice the same, so a handful of paragraphs
carry a different translation for a reason that is not a change in this batch.
Naming them here is what keeps them from being read as one.

What parity covers, exactly: the translator's own requests, which is what
``translate_tracking.json`` files under ``page``, ``cross_page`` and
``cross_column``. It does **not** cover the repair loop, whose decision requests
and whose LLM backed actions are recorded in ``react_repair.report.json`` under
a scheme of their own -- there is no ``repair`` group in the tracking to read.
That is why a run can report every tracked request identical to F2's and still
show a non-zero API count: the calls the cache did not answer are the repair
loop's, not the translator's. The record names both the groups it read and the
groups the tracking held, so a group appearing later cannot be left out in
silence.

Usage:
    python run_b10_1.py --all
    python run_b10_1.py --sample Courier-zh
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
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b10_1"

MODEL = "gpt-4o"
QPS = 4
RUN = "b10_1"
DPI = 110

# The pages each sample is read on, and what is being read there. One entry per
# row of the batch's evidence table; nothing outside these pages is written out.
TARGETS = {
    "Courier-en": (4, 5, 7),
    "FD-en-v2": (3, 5, 8),
    "AramcoWorld-en-v2": (4, 5, 8, 9),
    "Courier-zh": (1, 2, 5, 7),
}

# The sidecars this batch's fixes are recorded in, copied out of the working
# directory so the evidence stands without it.
SIDECARS = (
    "drop_cap_apply.report.json",
    "title_typeset.report.json",
    paren_dedup.REPORT_NAME,
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


def render(pdf: Path, sample: str, destination: Path) -> list[str]:
    """One PNG per target page of one sample, at the batch's resolution."""
    import pymupdf

    written = []
    destination.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as document:
        for page in TARGETS[sample]:
            image = document[page - 1].get_pixmap(dpi=DPI)
            path = destination / f"{sample}.p{page}.png"
            image.save(path)
            written.append(str(path.relative_to(ROOT)))
    return written


def extract(pdf: Path, sample: str, destination: Path) -> str:
    """The target pages of one produced PDF, as a PDF of their own."""
    import pymupdf

    path = destination / f"{sample}.{RUN}.pages.pdf"
    with pymupdf.open(pdf) as document, pymupdf.open() as pages:
        for page in TARGETS[sample]:
            pages.insert_pdf(document, from_page=page - 1, to_page=page - 1)
        pages.save(path, garbage=4, deflate=True)
    return str(path.relative_to(ROOT))


TRACKING = "translate_tracking.json"

# The groups a run files its requests under, in the order the tracking writes
# them. Named so the comparison walks both runs the same way rather than
# whatever order a mapping happens to iterate in.
REQUEST_GROUPS = ("page", "cross_page", "cross_column")

BASELINE_DIR = ROOT / "examples" / "output" / "F2"


def requests_of(tracking: dict) -> list[tuple[str, str]]:
    """Every request of one run as (what was asked, what came back), in order."""
    rows = []
    for group in REQUEST_GROUPS:
        for batch in tracking.get(group, ()):
            for paragraph in batch.get("paragraph", ()):
                rows.append((paragraph.get("input") or "", paragraph.get("output") or ""))
    return rows


def digest_of(texts) -> str:
    sha = hashlib.sha256()
    for text in texts:
        sha.update(text.encode("utf-8"))
        sha.update(b"\x00")
    return sha.hexdigest()


def parity(sample: str, working: Path, destination: Path) -> str | None:
    """This run's requests against F2's, frozen beside the run that made them.

    None where the baseline run is not in the workspace, which is a workspace
    that cannot answer the question rather than an answer to it.
    """
    baseline_path = BASELINE_DIR / sample / "work" / sample / TRACKING
    mine_path = working / TRACKING
    if not baseline_path.exists() or not mine_path.exists():
        return None
    with baseline_path.open(encoding="utf-8") as f:
        baseline = requests_of(json.load(f))
    with mine_path.open(encoding="utf-8") as f:
        mine = requests_of(json.load(f))
    resampled = [
        {"baseline": before[1], "run": after[1]}
        for before, after in zip(baseline, mine, strict=False)
        if before[0] == after[0] and before[1] != after[1]
    ]
    with mine_path.open(encoding="utf-8") as f:
        present = sorted(json.load(f))
    record = {
        "sample": sample,
        "baseline": str(baseline_path.relative_to(ROOT)),
        "groups_read": list(REQUEST_GROUPS),
        "groups_present": present,
        "requests": len(mine),
        "baseline_requests": len(baseline),
        "inputs_sha256": digest_of(text for text, _ in mine),
        "baseline_inputs_sha256": digest_of(text for text, _ in baseline),
        "resampled": resampled,
    }
    path = destination / "parity.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return str(path.relative_to(ROOT))


CHECKPOINT = "checkpoint.11_typesetting.json"


def typeset_checkpoint(working: Path) -> Path:
    return working / CHECKPOINT


def baseline_working(sample: str) -> Path:
    return BASELINE_DIR / sample / "work" / sample


def paragraph_texts(document: dict, label: int) -> list[str] | None:
    """The text of every paragraph of one page, in stored order, or None."""
    for page in document.get("page", ()):
        if page.get("page_number", -1) + 1 == label:
            return [
                paragraph.get("unicode") or ""
                for paragraph in page.get("pdf_paragraph") or ()
            ]
    return None


def conservation(sample: str, working: Path, destination: Path) -> str | None:
    """This run's shape against F2's, frozen beside the run that made it.

    None where the baseline run is not in the workspace, which is a workspace
    that cannot answer the question rather than an answer to it.
    """
    baseline_path = typeset_checkpoint(baseline_working(sample))
    mine_path = typeset_checkpoint(working)
    if not baseline_path.exists() or not mine_path.exists():
        return None
    with baseline_path.open(encoding="utf-8") as f:
        baseline = json.load(f)
    with mine_path.open(encoding="utf-8") as f:
        mine = json.load(f)
    pages = {}
    for label in TARGETS[sample]:
        before = paragraph_texts(baseline, label)
        after = paragraph_texts(mine, label)
        entry = {
            "baseline_paragraphs": None if before is None else len(before),
            "paragraphs": None if after is None else len(after),
            "differing": [],
        }
        if before is not None and after is not None and len(before) == len(after):
            entry["differing"] = [
                {
                    "reference": f"p{label}#{index}",
                    "baseline": was,
                    "run": now,
                }
                for index, (was, now) in enumerate(zip(before, after, strict=True))
                if was != now
            ]
        pages[str(label)] = entry
    record = {
        "sample": sample,
        "baseline": str(baseline_path.relative_to(ROOT)),
        "baseline_pages": len(baseline.get("page") or ()),
        "pages": len(mine.get("page") or ()),
        "target_pages": pages,
    }
    path = destination / "conservation.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return str(path.relative_to(ROOT))


def run_one(sample: str, layout_model) -> dict:
    pdf = INPUT_DIR / f"{sample}.pdf"
    destination = OUT_DIR / sample
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
        "parity": parity(sample, working, destination),
        "conservation": conservation(sample, working, destination),
        "raster": render(final_pdf, sample, destination / "raster")
        if final_pdf
        else [],
        "sidecars": sorted(
            str(path.relative_to(ROOT)) for path in kept.glob("*.json")
        ),
        "working_dir": str(Path(config.working_dir).relative_to(ROOT)),
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
    parser.add_argument("--sample", action="append", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = list(TARGETS) if args.all else (args.sample or ["Courier-zh"])
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
