"""T2.2: what the frozen exemption changes, measured over the whole corpus.

The predicate was frozen and hashed before this ran. What it does is measured
rather than argued: for every sample of the b10.5 on arm, the real styling stage
is driven twice over the same stage-05 document -- once with the exemption as
declared, once with it suppressed -- and the two runs are compared composition
by composition. Nothing here reimplements the rule, so the measurement cannot
drift from the code that ships.

The comparison is deliberately two-directional. It counts what turned from
formula into text, which is the repair, and it counts what turned the other way
and what else moved, which would be damage; and it lists every reclassified run
in full, with page, paragraph, font, size and text, so a human can answer the
question the plan makes a stopping condition -- is any of this a real
superscript or a real formula.

Reads checkpoints under examples/output/b10_5/, writes
examples/output/b11_5/t2_measurement.json. No API call, no network.

Usage:
    python t2_measure.py
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il.midend import (  # noqa: E402
    styles_and_formulas as sf,
)
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402

BASELINE = ROOT / "examples" / "output" / "b10_5"
STAGE_05 = "checkpoint.05_paragraph_finder.xml"
OUT = ROOT / "examples" / "output" / "b11_5" / "t2_measurement.json"
CONFIG = ROOT / "configs" / "initial_adjacent.json"


def samples() -> list[str]:
    found = []
    for directory in sorted(BASELINE.iterdir()):
        if not directory.is_dir():
            continue
        if (directory / "on" / "work" / directory.name / STAGE_05).is_file():
            found.append(directory.name)
    return found


def build_stage(sample: str, lang_out: str) -> sf.StylesAndFormulas:
    config = TranslationConfig(
        translator=None,
        input_file=str(ROOT / "examples" / "input" / f"{sample}.pdf"),
        lang_in="en",
        lang_out=lang_out,
        doc_layout_model=None,
    )
    return sf.StylesAndFormulas(config)


def composition_characters(composition) -> list:
    holder = (
        composition.pdf_formula
        or composition.pdf_line
        or composition.pdf_same_style_characters
    )
    return list(holder.pdf_character or ()) if holder is not None else []


def shape_of(paragraph) -> list[tuple[str, str]]:
    """Every composition of a paragraph as (kind, text), in document order."""
    out = []
    for composition in paragraph.pdf_paragraph_composition or ():
        characters = composition_characters(composition)
        kind = "formula" if composition.pdf_formula is not None else "text"
        out.append((kind, "".join(c.char_unicode or "" for c in characters)))
    return out


def describe(composition, page_label: int, index: int) -> dict:
    """One composition as the few facts a human needs to judge it."""
    characters = composition_characters(composition)
    sizes = [
        float(c.pdf_style.font_size)
        for c in characters
        if c.pdf_style is not None and c.pdf_style.font_size
    ]
    fonts = sorted(
        {
            c.pdf_style.font_id
            for c in characters
            if c.pdf_style is not None and c.pdf_style.font_id
        }
    )
    formula = composition.pdf_formula
    return {
        "is_corner_mark": bool(getattr(formula, "is_corner_mark", False)),
        "page": page_label,
        "paragraph_index": index,
        "text": "".join(c.char_unicode or "" for c in characters),
        "characters": len(characters),
        "font_ids": fonts,
        "font_size": round(statistics.median(sizes), 3) if sizes else None,
        "pdf_curve": len(getattr(formula, "pdf_curve", None) or ()),
        "pdf_form": len(getattr(formula, "pdf_form", None) or ()),
    }


def font_names(page) -> dict[str, str]:
    names = {}
    for font in page.pdf_font or ():
        names[font.font_id] = font.name
    for xobject in page.pdf_xobject or ():
        for font in xobject.pdf_font or ():
            names.setdefault(font.font_id, font.name)
    return names


def measure_sample(sample: str) -> dict:
    path = BASELINE / sample / "on" / "work" / sample / STAGE_05
    lang_out = "en" if sample.endswith("-zh") else "zh"

    stage = build_stage(sample, lang_out)
    exempted = load_checkpoint(path)
    plain = load_checkpoint(path)

    spans: list[dict] = []
    for page in plain.page:
        label = (page.page_number or 0) + 1
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            start, end = sf.initial_adjacent_exemption(paragraph)
            if end <= start:
                continue
            sizes = sf.paragraph_character_sizes(paragraph)
            median = statistics.median(sizes)
            spans.append(
                {
                    "sample": sample,
                    "page": label,
                    "paragraph": f"p{label}#{index}",
                    "opening_size": round(sizes[0], 3),
                    "median_size": round(median, 3),
                    "ratio": round(sizes[0] / median, 3),
                    "run_length": start,
                    "span": [start, end],
                    "opening_text": (paragraph.unicode or "")[:60],
                }
            )

    # The whole stage, not the formula pass alone: curves and forms are assigned
    # to formulas after the classification, and whether that assignment moves is
    # the question CLAUDE.md section 4.18 makes absolute.
    for page in exempted.page:
        stage.process_page(page)

    original = sf.initial_adjacent_exemption
    sf.initial_adjacent_exemption = lambda paragraph: (0, 0)
    try:
        for page in plain.page:
            stage.process_page(page)
    finally:
        sf.initial_adjacent_exemption = original

    reclassified: list[dict] = []
    reverse: list[dict] = []
    pages_unchanged = 0
    graphics_moved: list[dict] = []

    for before_page, after_page in zip(plain.page, exempted.page, strict=True):
        label = (before_page.page_number or 0) + 1
        names = font_names(before_page)
        before_paragraphs = list(before_page.pdf_paragraph or ())
        after_paragraphs = list(after_page.pdf_paragraph or ())
        if len(before_paragraphs) != len(after_paragraphs):
            raise SystemExit(f"{sample} p{label}: paragraph count moved")
        page_moved = False
        before_graphics = (len(before_page.pdf_curve or ()), len(before_page.pdf_form or ()))
        after_graphics = (len(after_page.pdf_curve or ()), len(after_page.pdf_form or ()))
        if before_graphics != after_graphics:
            graphics_moved.append(
                {
                    "sample": sample,
                    "page": label,
                    "page_level_before": list(before_graphics),
                    "page_level_after": list(after_graphics),
                }
            )
        for index, (was, now) in enumerate(
            zip(before_paragraphs, after_paragraphs, strict=True)
        ):
            was_shape = shape_of(was)
            now_shape = shape_of(now)
            if "".join(t for _, t in was_shape) != "".join(t for _, t in now_shape):
                raise SystemExit(f"{sample} p{label}#{index}: text moved")
            if was_shape == now_shape:
                continue
            page_moved = True
            was_formulas = [
                describe(c, label, index)
                for c in was.pdf_paragraph_composition or ()
                if c.pdf_formula is not None
            ]
            now_formulas = [
                describe(c, label, index)
                for c in now.pdf_paragraph_composition or ()
                if c.pdf_formula is not None
            ]
            was_keys = [(f["text"], f["font_size"]) for f in was_formulas]
            now_keys = [(f["text"], f["font_size"]) for f in now_formulas]
            for entry in was_formulas:
                if (entry["text"], entry["font_size"]) not in now_keys:
                    entry["sample"] = sample
                    entry["font_names"] = [
                        names.get(fid, fid) for fid in entry["font_ids"]
                    ]
                    reclassified.append(entry)
            for entry in now_formulas:
                if (entry["text"], entry["font_size"]) not in was_keys:
                    entry["sample"] = sample
                    entry["font_names"] = [
                        names.get(fid, fid) for fid in entry["font_ids"]
                    ]
                    reverse.append(entry)
        if not page_moved:
            pages_unchanged += 1

    return {
        "sample": sample,
        "pages": len(exempted.page),
        "pages_unchanged": pages_unchanged,
        "paragraphs_with_span": len(spans),
        "spans": spans,
        "reclassified": reclassified,
        "reverse": reverse,
        "graphics_moved": graphics_moved,
    }


def main() -> int:
    found = samples()
    print(f"samples: {found}", flush=True)
    per_sample = []
    for sample in found:
        result = measure_sample(sample)
        per_sample.append(result)
        print(
            f"{sample}: spans={result['paragraphs_with_span']} "
            f"reclassified={len(result['reclassified'])} "
            f"reverse={len(result['reverse'])} "
            f"graphics_moved={len(result['graphics_moved'])}",
            flush=True,
        )
    reclassified = [r for s in per_sample for r in s["reclassified"]]
    reverse = [r for s in per_sample for r in s["reverse"]]
    graphics = [r for s in per_sample for r in s["graphics_moved"]]
    record = {
        "predicate_config": "configs/initial_adjacent.json",
        "predicate_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
        "method": (
            "The real StylesAndFormulas.process_page_formulas is driven twice "
            "over the same stage-05 checkpoint, once with the exemption as "
            "declared and once with it suppressed, and the two documents are "
            "compared. Nothing reimplements the rule."
        ),
        "baseline": f"examples/output/b10_5/<sample>/on/work/<sample>/{STAGE_05}",
        "totals": {
            "samples": len(per_sample),
            "paragraphs_with_span": sum(s["paragraphs_with_span"] for s in per_sample),
            "reclassified": len(reclassified),
            "reverse": len(reverse),
            "carrying_pdf_form_or_curve": sum(
                1 for r in reclassified if r["pdf_form"] or r["pdf_curve"]
            ),
            "corner_mark_among_reclassified": sum(
                1 for r in reclassified if r["is_corner_mark"]
            ),
            "pages_with_graphics_moved": len(graphics),
        },
        "reclassified": reclassified,
        "reverse": reverse,
        "graphics_moved": graphics,
        "per_sample": [
            {
                k: v
                for k, v in s.items()
                if k not in ("reclassified", "reverse", "graphics_moved")
            }
            for s in per_sample
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(record["totals"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
