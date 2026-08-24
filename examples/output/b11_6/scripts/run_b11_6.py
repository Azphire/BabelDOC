"""B11.6 driver: four samples, one arm, with this batch's two changes in force.

The batch adds a page level gate to the indent policy and in-page column
boundaries to the chain detector. The second changes which requests are sent --
a column chain is translated as one unit -- so every sample the adjudication
rules a column pair on has to be run again: Courier-en, AramcoWorld-en-v2,
FD-en-v2 and Courier-zh. CERNCourier-en and Vogue-en carry no ruled pair and are
not run, per CLAUDE.md section 4.14.

The switch set is read out of the f3 run record of each sample rather than
retyped, as every driver since b7 has raised it, with the switches raised by
batches after f3 added on top and recorded as added rather than folded in
silently.

What this writes beyond the usual ledger is the batch's gate evidence, per
CLAUDE.md section 4.16: small derived files carrying exactly the quantities the
gate asserts about, so the gate never opens a checkpoint or a PDF.

    chain_evidence.json    every boundary the detector scored, every edge
                           assembly took, every chain it closed, and for each
                           chain member its source text, its translated text and
                           the box each was set in -- keyed by page and by text,
                           never by a debug id, per CLAUDE.md section 5.13.
    render_evidence.json   every line of the produced document as position, size
                           and text.
    indent_evidence.json   the first line offset of every paragraph as the
                           typesetting stage left it.
    conservation.json      this run's paragraph texts per page beside the b10.5
                           on arm they answer to.

Usage:
    python run_b11_6.py [--only SAMPLE ...]
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
from babeldoc.magazine import indent_policy  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from babeldoc.magazine import name_harvest  # noqa: E402
from babeldoc.magazine import paren_dedup  # noqa: E402
from babeldoc.magazine import short_unit  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from babeldoc.magazine import translation_style  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.react import controller as react  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

INPUT_DIR = ROOT / "examples" / "input"
OUT_DIR = ROOT / "examples" / "output" / "b11_6"
BASELINE_BATCH = ROOT / "examples" / "output" / "b10_5"
F3 = ROOT / "examples" / "output" / "F3" / "cold"

MODEL = "gpt-4o"
QPS = 4
RUN = "b11_6"
DPI = 110
CHECKPOINT = "checkpoint.11_typesetting.json"
TYPESET_XML = "checkpoint.11_typesetting.xml"
CHAIN_XML = "checkpoint.08_chain_builder.xml"

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
    indent_policy.SWITCH: "magazine_indent_policy",
}

# Raised since the f3 record was written and therefore absent from it. This
# batch raises no switch of its own: both of its changes are new behaviour
# inside passes the switch set already turns on.
SWITCHES_SINCE_F3 = {"magazine_indent_policy": True}

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
    indent_policy.REPORT_NAME,
    title_typeset.REPORT_NAME,
    column_reflow.REPORT_NAME,
    "issues.json",
    "react_repair.report.json",
    "magazine_config_manifest.json",
    "prompts.manifest.json",
)

# The samples the adjudication rules a column pair on.
REGRESSION_SAMPLES = (
    "Courier-en",
    "AramcoWorld-en-v2",
    "FD-en-v2",
    "Courier-zh",
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
    return list(REGRESSION_SAMPLES)


def baseline_switches(sample: str) -> dict:
    with (F3 / sample / "run.json").open(encoding="utf-8") as f:
        switches = json.load(f)["switches"]
    switches.update(SWITCHES_SINCE_F3)
    return switches


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
        return {"path": None, "sha256": None, "present": False, "terms": {}}
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": digest(path),
        "present": True,
        "terms": raw.get("terms") or {},
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


def render_evidence(pdf: Path, sample: str, destination: Path) -> str:
    """Every line of the produced document, as the gate will read it."""
    import pymupdf

    pages = []
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document):
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [
                        {
                            "text": span["text"],
                            "size": round(span["size"], 3),
                            "bbox": [round(v, 3) for v in span["bbox"]],
                            "font": span.get("font"),
                        }
                        for span in line["spans"]
                    ]
                    lines.append(
                        {
                            "bbox": [round(v, 3) for v in line["bbox"]],
                            "text": "".join(s["text"] for s in spans),
                            "max_size": round(max(s["size"] for s in spans), 3),
                            "spans": spans,
                        }
                    )
            lines.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
            pages.append(
                {
                    "page": index + 1,
                    "size": [round(page.rect.width, 3), round(page.rect.height, 3)],
                    "lines": lines,
                    "text": page.get_text(),
                }
            )
    record = {
        "sample": sample,
        "pdf": str(pdf.relative_to(ROOT)).replace("\\", "/"),
        "pdf_sha256": digest(pdf),
        "pages": len(pages),
        "per_page": pages,
    }
    out = destination / "render_evidence.json"
    out.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return str(out.relative_to(ROOT)).replace("\\", "/")


def paragraph_characters(paragraph):
    """Every positioned character of a paragraph, whichever composition holds it."""
    characters = []
    for composition in paragraph.pdf_paragraph_composition or ():
        if composition.pdf_character is not None:
            characters.append(composition.pdf_character)
        for name in ("pdf_same_style_characters", "pdf_line", "pdf_formula"):
            holder = getattr(composition, name, None)
            if holder is not None:
                characters.extend(holder.pdf_character or ())
    return [c for c in characters if c.box is not None]


def indent_evidence(working: Path, sample: str, destination: Path) -> str | None:
    """Where every paragraph's first line starts, as the stage left it."""
    path = working / TYPESET_XML
    if not path.is_file():
        return None
    document = load_checkpoint(path)
    rows = []
    for position, page in enumerate(document.page):
        label = (page.page_number if page.page_number is not None else position) + 1
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            boxed = paragraph_characters(paragraph)
            if not boxed or paragraph.box is None:
                continue
            top = max(c.box.y for c in boxed)
            first_line = [c for c in boxed if abs(c.box.y - top) < 1.0]
            start = min(c.box.x for c in first_line)
            rows.append(
                {
                    "page": label,
                    "reference": f"p{label}#{index}",
                    "layout_label": paragraph.layout_label,
                    "page_kind": page.page_kind,
                    "first_line_indent": bool(paragraph.first_line_indent),
                    "box_x": round(float(paragraph.box.x), 3),
                    "first_line_x": round(float(start), 3),
                    "offset": round(float(start) - float(paragraph.box.x), 3),
                    "lines": len({round(c.box.y, 1) for c in boxed}),
                    "excerpt": (paragraph.unicode or "")[:60],
                }
            )
    record = {"sample": sample, "read_from": TYPESET_XML, "paragraphs": rows}
    out = destination / "indent_evidence.json"
    out.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return str(out.relative_to(ROOT)).replace("\\", "/")


def _box_of(paragraph):
    box = paragraph.box
    if box is None:
        return None
    return [round(float(v), 2) for v in (box.x, box.y, box.x2, box.y2)]


def chain_evidence(working: Path, sample: str, destination: Path) -> str | None:
    """Every boundary, edge and chain of this run, keyed by page and by text.

    The detector's own sidecar names a paragraph by its debug id, which is
    reassigned every run and so cannot anchor an assertion (CLAUDE.md section
    5.13). This translates the sidecar into references and texts: each row
    carries the page and the in-page position of its ends at the stage the chain
    was built, the text each end carries, and for a chain member the box it was
    laid out in, so a gate can ask where a chain's two halves were set without
    opening a checkpoint.
    """
    source = working / CHAIN_XML
    report_path = working / "chain_report.json"
    if not source.is_file() or not report_path.is_file():
        return None
    document = load_checkpoint(source)
    with report_path.open(encoding="utf-8") as f:
        report = json.load(f)

    reference: dict[str, str] = {}
    text_of: dict[str, str] = {}
    box_at_build: dict[str, list | None] = {}
    page_of: dict[str, int] = {}
    for index, page in enumerate(document.page):
        for position, paragraph in enumerate(page.pdf_paragraph or ()):
            if not paragraph.debug_id:
                continue
            reference[paragraph.debug_id] = f"p{index + 1}#{position}"
            text_of[paragraph.debug_id] = paragraph.unicode or ""
            box_at_build[paragraph.debug_id] = _box_of(paragraph)
            page_of[paragraph.debug_id] = index + 1

    laid_out: dict[str, dict] = {}
    typeset = working / TYPESET_XML
    if typeset.is_file():
        final = load_checkpoint(typeset)
        for index, page in enumerate(final.page):
            for position, paragraph in enumerate(page.pdf_paragraph or ()):
                if not paragraph.debug_id:
                    continue
                laid_out[paragraph.debug_id] = {
                    "reference": f"p{index + 1}#{position}",
                    "box": _box_of(paragraph),
                    "text": paragraph.unicode or "",
                }

    def side(debug_id):
        if debug_id is None:
            return None
        return {
            "reference": reference.get(debug_id),
            "page": page_of.get(debug_id),
            "text": text_of.get(debug_id, "")[:240],
        }

    boundaries = []
    for row in report["boundaries"]:
        boundaries.append(
            {
                "boundary": row["boundary"],
                "kind": row.get("kind"),
                "pairing": row.get("pairing"),
                "tail_page": row.get("tail_page"),
                "head_page": row.get("head_page"),
                "tail_column": row.get("tail_column"),
                "head_column": row.get("head_column"),
                "column_count": row.get("column_count"),
                "eligible": row.get("eligible"),
                "reason": row.get("reason"),
                "pair": row.get("pair"),
                "score": row.get("score"),
                "linked": row.get("linked"),
                "tail_ends_on_hyphen": row.get("tail_ends_on_hyphen"),
                "tail_last_line": row.get("tail_text"),
                "head_first_line": (row.get("head_text") or "")[:160],
                "tail": side(row.get("tail_debug_id")),
                "head": side(row.get("head_debug_id")),
            }
        )

    translation = {}
    translation_path = working / "chain_translation.report.json"
    if translation_path.is_file():
        with translation_path.open(encoding="utf-8") as f:
            translation = json.load(f)
    merged_by_chain = {
        entry["chain_id"]: entry for entry in translation.get("chains", ()) or ()
    }

    chains = []
    for chain in report["chains"]:
        members = []
        for member in chain["members"]:
            debug_id = member["debug_id"]
            members.append(
                {
                    "chain_index": member["chain_index"],
                    "reference_at_build": reference.get(debug_id),
                    "page": page_of.get(debug_id),
                    "source": text_of.get(debug_id, ""),
                    "box_at_build": box_at_build.get(debug_id),
                    "laid_out": laid_out.get(debug_id),
                }
            )
        joint = merged_by_chain.get(chain["chain_id"])
        chains.append(
            {
                "length": chain["length"],
                "pages": sorted({m["page"] for m in members if m["page"]}),
                "members": members,
                "joint_translation": None if joint is None else joint.get("translation"),
                "joint_segments": None
                if joint is None
                else [m["segment"] for m in joint.get("members", ())],
            }
        )

    record = {
        "sample": sample,
        "read_from": CHAIN_XML,
        "link_min_score": report["link_min_score"],
        "boundary_priority": report.get("boundary_priority"),
        "boundaries": boundaries,
        "edges": report.get("edges", []),
        "dropped_edges": report.get("dropped_edges", []),
        "chains": chains,
        "escalated": translation.get("escalated", []),
        "totals": {
            "boundaries": len(boundaries),
            "linked": sum(1 for row in boundaries if row["linked"]),
            "column_linked": sum(
                1 for row in boundaries if row["linked"] and row["kind"] == "column"
            ),
            "edges": len(report.get("edges", [])),
            "dropped_edges": len(report.get("dropped_edges", [])),
            "chains": len(chains),
        },
    }
    out = destination / "chain_evidence.json"
    out.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return str(out.relative_to(ROOT)).replace("\\", "/")


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
    baseline_path = BASELINE_BATCH / sample / "on" / "work" / sample / CHECKPOINT
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
        "pdf": str(final_pdf.relative_to(ROOT)).replace("\\", "/")
        if final_pdf
        else None,
        "pdf_sha256": digest(final_pdf) if final_pdf else None,
        "working_dir": str(working.relative_to(ROOT)).replace("\\", "/"),
        "ruling": ruling(sample),
        "switches": switches,
        "switches_raised_since_f3": SWITCHES_SINCE_F3,
        "switches_added_this_batch": {},
        "chain_detection_sha256": digest(ROOT / "configs" / "chain_detection.json"),
        "indent_policy_sha256": digest(ROOT / "configs" / "indent_policy.json"),
        "page_types_sha256": digest(ROOT / "configs" / "page_types.json"),
        "adjudication_sha256": digest(
            ROOT / "reviews" / "column_pairs.adjudication.json"
        ),
        "raster": raster(final_pdf, sample, destination / "raster")
        if final_pdf
        else [],
        "sidecars": sorted(
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in kept.glob("*.json")
        ),
        "conservation": conservation(sample, working, destination),
        "render_evidence": render_evidence(final_pdf, sample, destination)
        if final_pdf
        else None,
        "indent_evidence": indent_evidence(working, sample, destination),
        "chain_evidence": chain_evidence(working, sample, destination),
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
    parser.add_argument(
        "--ledger-only",
        action="store_true",
        help="rebuild runs.json from the run records on disk and run nothing",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not args.ledger_only:
        samples = args.only or selected_samples()
        print(f"regression samples: {samples}", flush=True)
        model = DocLayoutModel.load_onnx()
        for sample in samples:
            run_one(sample, model)

    # Rebuilt from what is on disk rather than from this invocation's own list,
    # so a ledger written after a subset run still holds every sample the batch
    # ran. A run record is the run's, and collecting them is not a second run.
    ledger = []
    for sample in selected_samples():
        path = OUT_DIR / sample / "run.json"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as f:
            ledger.append(json.load(f))
    with (OUT_DIR / "runs.json").open("w", encoding="utf-8") as f:
        json.dump({"runs": ledger}, f, indent=2, ensure_ascii=False)
    total = sum(r["api_calls"] for r in ledger)
    print(f"done: {len(ledger)} runs in the ledger, {total} api calls", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
