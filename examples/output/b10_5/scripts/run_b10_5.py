"""B10.5 driver: the same stack the batch before it ran, twice per sample.

This batch adds one pass and changes nothing else, so the evidence it owes is a
comparison rather than a run: the same document, produced once with the column
reflow switch down and once with it up, and every difference between the two
attributed to that switch. Each sample is therefore run twice into two working
directories, and both runs are rasterised page by page so that "this page did
not move" is a statement about pixels rather than about intent.

No request text changes, so the second run of a sample answers every request out
of the project cache the first one filled, and the first out of the cache the
batch before filled. The ledger records the API call count of each run, which is
what that claim is checked against.

Usage:
    python run_b10_5.py --all
    python run_b10_5.py --sample Courier-en
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
OUT_DIR = ROOT / "examples" / "output" / "b10_5"

MODEL = "gpt-4o"
QPS = 4
RUN = "b10_5"
DPI = 110

# The pages this batch reads each sample on: the flowing text pages of the
# corpus, which are the only pages the pass can reach, and for the samples that
# have none, the pages the batch before read. Nothing outside them is kept as an
# image; every page of every sample is still hashed.
TARGETS = {
    "Courier-en": (4, 6, 8),
    "AramcoWorld-en-v2": (4, 6, 7),
    "CERNCourier-en": (1, 4),
    "Vogue-en": (3,),
    "FD-en-v2": (3, 5),
    "Courier-zh": (4, 6, 8),
}

# The two runs of every sample, and the value of this batch's switch in each.
ARMS = {"off": False, "on": True}

SIDECARS = (
    column_reflow.REPORT_NAME,
    "issues.json",
    "react_repair.report.json",
    title_typeset.REPORT_NAME,
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
    fragment_stitch.SWITCH: True,
    react.SWITCH: True,
    paren_dedup.SWITCH: True,
    backfill.load_backfill_config().align_switch: True,
    fragment_stitch.load_stitch_config().declared_page_switch: True,
    short_unit.load_short_unit_config().switch: True,
    name_harvest.load_harvest_config().switch: True,
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
        os.environ.setdefault(name.strip(), value.strip().strip("'\""))


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


def raster(pdf: Path, sample: str, destination: Path, keep: tuple[int, ...]) -> dict:
    """Every page of one produced PDF as an image, hashed; the named ones kept.

    The hash is what says whether a page moved, and it is taken for every page
    rather than for the ones this batch reads, because "the pass touched nothing
    else" is a claim about the whole document.
    """
    import pymupdf

    destination.mkdir(parents=True, exist_ok=True)
    hashes = {}
    kept = []
    with pymupdf.open(pdf) as document:
        for index in range(document.page_count):
            image = document[index].get_pixmap(dpi=DPI)
            path = destination / f"{sample}.p{index + 1}.png"
            image.save(path)
            hashes[str(index + 1)] = digest(path)
            if index + 1 in keep:
                kept.append(str(path.relative_to(ROOT)))
            else:
                path.unlink()
    return {"hashes": hashes, "kept": kept}


CHECKPOINT = "checkpoint.11_typesetting.json"


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


def words_of(pdf, label: int) -> list:
    """Every word one produced page shows, with the box it is drawn in.

    Read back out of the finished PDF rather than off the document the pass
    edited, so that what is compared is what a reader is shown. The vertical
    axis here is the reader's: a paragraph raised on the page carries a smaller
    y than it did.
    """
    import pymupdf

    with pymupdf.open(pdf) as document:
        return [
            (
                word[4],
                round(word[0], 2),
                round(word[1], 2),
                round(word[2], 2),
                round(word[3], 2),
            )
            for word in document[label - 1].get_text("words")
        ]


def graphics_of(pdf, label: int) -> tuple[str, str]:
    """What one produced page draws that is not text, as two comparable strings.

    The vector paths and the placed images. The pass moves paragraphs and
    nothing else, so these are what has to come out of both arms identical: a
    rule, a tint panel or a photograph that moved would be a defect this batch
    caused and no word count would show it.
    """
    import pymupdf

    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        drawings = json.dumps(page.get_drawings(), sort_keys=True, default=str)
        images = json.dumps(sorted(str(item) for item in page.get_images(full=True)))
    return drawings, images


def displacements(off_pdf: Path, on_pdf: Path, label: int) -> dict:
    """Where the two arms draw one page's words differently.

    Words are paired by their text and their horizontal position, so a pair that
    matches has not moved sideways and a word that finds no partner is reported
    as unmatched rather than silently dropped. Each distinct vertical
    displacement is then one entry, carrying how many words took it and the
    extent those words occupy in each arm, which is the region an image
    comparison crops.
    """
    before, after = words_of(off_pdf, label), words_of(on_pdf, label)
    buckets: dict[tuple, list] = {}
    for word in before:
        buckets.setdefault((word[0], word[1]), [[], []])[0].append(word)
    for word in after:
        buckets.setdefault((word[0], word[1]), [[], []])[1].append(word)
    moved: dict[float, list] = {}
    unmatched = {"off": 0, "on": 0}
    for left, right in buckets.values():
        if len(left) != len(right):
            unmatched["off"] += len(left)
            unmatched["on"] += len(right)
            continue
        left.sort(key=lambda word: word[2])
        right.sort(key=lambda word: word[2])
        for was, now in zip(left, right, strict=True):
            delta = round(now[2] - was[2], 2)
            if delta == 0.0 and round(now[4] - was[4], 2) == 0.0:
                continue
            moved.setdefault(delta, []).append((was, now))
    entries = []
    for delta, pairs in sorted(moved.items()):
        entries.append(
            {
                "dy": delta,
                "words": len(pairs),
                "off": [
                    min(was[1] for was, _ in pairs),
                    min(was[2] for was, _ in pairs),
                    max(was[3] for was, _ in pairs),
                    max(was[4] for was, _ in pairs),
                ],
                "on": [
                    min(now[1] for _, now in pairs),
                    min(now[2] for _, now in pairs),
                    max(now[3] for _, now in pairs),
                    max(now[4] for _, now in pairs),
                ],
            }
        )
    off_graphics = graphics_of(off_pdf, label)
    on_graphics = graphics_of(on_pdf, label)
    return {
        "displaced": entries,
        "unmatched": unmatched,
        "graphics": {
            "drawings_equal": off_graphics[0] == on_graphics[0],
            "images_equal": off_graphics[1] == on_graphics[1],
            "drawings_sha256": hashlib.sha256(off_graphics[0].encode()).hexdigest(),
            "images_sha256": hashlib.sha256(off_graphics[1].encode()).hexdigest(),
        },
    }


def conservation(sample: str, arms: dict, pdfs: dict, destination: Path) -> str | None:
    """The two arms' documents against each other, paragraph by paragraph.

    The pass moves boxes and writes no text, so the two arms have to agree on
    every page's paragraph count and on every paragraph's text. What they may
    disagree about is where a paragraph stands, and that disagreement is what
    the rasters measure.
    """
    paths = {arm: working / CHECKPOINT for arm, working in arms.items()}
    if not all(path.exists() for path in paths.values()):
        return None
    loaded = {}
    for arm, path in paths.items():
        with path.open(encoding="utf-8") as f:
            loaded[arm] = json.load(f)
    pages = {}
    for label in range(1, len(loaded["off"].get("page") or ()) + 1):
        before = paragraph_texts(loaded["off"], label)
        after = paragraph_texts(loaded["on"], label)
        comparable = (
            before is not None and after is not None and len(before) == len(after)
        )
        pages[str(label)] = {
            "paragraphs_off": None if before is None else len(before),
            "paragraphs_on": None if after is None else len(after),
            "differing": []
            if not comparable
            else [
                {"reference": f"p{label}#{index}", "off": was, "on": now}
                for index, (was, now) in enumerate(zip(before, after, strict=True))
                if was != now
            ],
            **displacements(pdfs["off"], pdfs["on"], label),
        }
    record = {
        "sample": sample,
        "pages_off": len(loaded["off"].get("page") or ()),
        "pages_on": len(loaded["on"].get("page") or ()),
        "pages": pages,
    }
    path = destination / "conservation.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return str(path.relative_to(ROOT))


def run_arm(sample: str, arm: str, layout_model) -> dict:
    pdf = INPUT_DIR / f"{sample}.pdf"
    destination = OUT_DIR / sample / arm
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
    setattr(config, column_reflow.SWITCH, ARMS[arm])
    translation_style.apply(config, target_lang)

    started = time.monotonic()
    try:
        result = high_level.translate(config)
    finally:
        seconds = time.monotonic() - started

    mono = getattr(result, "mono_pdf_path", None)
    final_pdf = None
    if mono:
        final_pdf = destination / f"{sample}.{RUN}.{arm}.pdf"
        shutil.copyfile(mono, final_pdf)

    working = Path(config.working_dir)
    kept = destination / "sidecars"
    kept.mkdir(parents=True, exist_ok=True)
    for name in SIDECARS:
        source = working / name
        if source.exists():
            shutil.copyfile(source, kept / name)

    images = (
        raster(final_pdf, sample, destination / "raster", TARGETS[sample])
        if final_pdf
        else {"hashes": {}, "kept": []}
    )
    return {
        "arm": arm,
        "switch": ARMS[arm],
        "seconds": round(seconds, 1),
        "requests": engine.translate_call_count,
        "cache_hits": engine.translate_cache_call_count,
        "api_calls": engine.translate_call_count - engine.translate_cache_call_count,
        "pdf": str(final_pdf.relative_to(ROOT)) if final_pdf else None,
        "pdf_sha256": digest(final_pdf) if final_pdf else None,
        "page_hashes": images["hashes"],
        "raster": images["kept"],
        "sidecars": sorted(str(path.relative_to(ROOT)) for path in kept.glob("*.json")),
        "working_dir": str(working.relative_to(ROOT)),
    }


def run_one(sample: str, layout_model) -> dict:
    arms = {arm: run_arm(sample, arm, layout_model) for arm in ARMS}
    destination = OUT_DIR / sample
    changed = sorted(
        int(label)
        for label, value in arms["on"]["page_hashes"].items()
        if arms["off"]["page_hashes"].get(label) != value
    )
    report = None
    path = ROOT / arms["on"]["working_dir"] / column_reflow.REPORT_NAME
    if path.exists():
        with path.open(encoding="utf-8") as f:
            report = json.load(f)
    source_lang, target_lang = corpus.direction_of(sample)
    record = {
        "sample": f"{sample}.pdf",
        "model": MODEL,
        "lang_in": source_lang,
        "lang_out": target_lang,
        "target_pages": list(TARGETS[sample]),
        "arms": arms,
        "pages_changed": changed,
        "reflow_totals": None if report is None else report["totals"],
        "reflow_guards": None if report is None else report["guards"],
        "reflow_notes": None if report is None else report["notes"],
        "conservation": conservation(
            sample,
            {arm: ROOT / arms[arm]["working_dir"] for arm in ARMS},
            {arm: ROOT / arms[arm]["pdf"] for arm in ARMS},
            destination,
        ),
    }
    with (destination / "run.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(
        json.dumps(
            {key: value for key, value in record.items() if key != "arms"},
            indent=2,
            ensure_ascii=False,
        ),
        flush=True,
    )
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

    if args.sample:
        wanted = args.sample
    elif args.all:
        wanted = list(TARGETS)
    else:
        wanted = ["Courier-en"]
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
