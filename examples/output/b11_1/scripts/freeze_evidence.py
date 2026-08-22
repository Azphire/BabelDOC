"""Distil this batch's three claims into evidence a clone can read.

The measurements the gate makes are taken off two things that do not survive a
clone: a typesetting checkpoint, which is tens of megabytes, and a produced PDF,
which by this repository's intake is workspace evidence rather than tracked
evidence. So each measurement is taken once, here, and written to a small JSON
file beside the run. The gate recomputes every one of them where the workspace
still holds the source and compares; where it does not, it reads what is frozen
and says which path it could not check against.

Nothing here decides anything. It reads two runs and writes down what they say.

Usage:
    python freeze_evidence.py
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

BATCH = ROOT / "examples" / "output" / "b11_1"
RUN = BATCH / "FD-en-v2"
# The replay of the f3 stack on this tree before any of the three changes: the
# batch baseline, reproduced here because the f3 working directory was pruned.
BASELINE = BATCH / "FD-en-v2.probe"
# The same run with T1 and T2 in and the person name policy still the old one,
# which is what separates a layout change from a translation change.
ISOLATION = BATCH / "FD-en-v2.t12"
BASELINE_PDF = ROOT / "examples" / "output" / "F3" / "cold" / "FD-en-v2" / "FD-en-v2.f3.pdf"

EVIDENCE = RUN / "evidence"

PRE_CHECKPOINT = "checkpoint.08_chain_builder.json"
POST_CHECKPOINT = "checkpoint.09_il_translated.json"
TYPESET_CHECKPOINT = "checkpoint.11_typesetting.json"

# The pages whose running head is the label this batch stopped reflowing, and
# the band a running head stands in.
HEAD_PAGES = (5, 6, 8)
HEAD_BAND = 60.0

# The page carrying the pull quote whose closing mark reached the column rule.
QUOTE_PAGE = 3

# A Chinese name followed by a Latin form in brackets. Narrowed from the plan's
# pattern, which also matched a domain inside brackets after a Chinese noun --
# a publisher's address line, not a name annotation. The narrowing requires the
# bracketed form to be written the way a personal name is written: capitalised
# words, no dot, which no domain satisfies.
NAME_ANNOTATION = re.compile(
    r"[一-鿿·]{2,}\s*[(（][A-Z][a-z]+"
    r"(?:[ '\-][A-Za-z]+)*[)）]"
)
# The plan's own pattern, kept so the gate can state what it matched and why the
# narrowing was needed rather than only that a narrower one matched nothing.
NAME_ANNOTATION_BROAD = re.compile(r"[一-鿿·]{2,}\s*[(（][A-Za-z]")


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def composition_digest(paragraph: dict) -> str:
    return digest_text(
        json.dumps(
            paragraph.get("pdf_paragraph_composition"),
            sort_keys=True,
            ensure_ascii=False,
        )
    )


def paragraphs_by_ref(document: dict) -> dict[str, dict]:
    found = {}
    for page in document.get("page") or ():
        label = (page.get("page_number") or 0) + 1
        for index, paragraph in enumerate(page.get("pdf_paragraph") or ()):
            found[f"p{label}#{index}"] = paragraph
    return found


def work_dir(run: Path) -> Path:
    return run / "work" / "FD-en-v2"


def identity_table() -> dict:
    """Every paragraph the revived identity short circuit now leaves standing.

    A paragraph qualifies where the reply said what the source said, which shows
    as a document whose text and composition after translation are the ones it
    carried before. What is recorded beside it is what the baseline run wrote
    into the same paragraph, which is the whole of the difference this change
    makes to a page.
    """
    rows = []
    for run, key in ((RUN, "run"), (ISOLATION, "isolation")):
        pre = paragraphs_by_ref(load(work_dir(run) / PRE_CHECKPOINT))
        post = paragraphs_by_ref(load(work_dir(run) / POST_CHECKPOINT))
        base_pre = paragraphs_by_ref(load(work_dir(BASELINE) / PRE_CHECKPOINT))
        base_post = paragraphs_by_ref(load(work_dir(BASELINE) / POST_CHECKPOINT))
        for ref, paragraph in post.items():
            source = pre[ref].get("unicode") or ""
            written = paragraph.get("unicode") or ""
            before, after = composition_digest(pre[ref]), composition_digest(paragraph)
            if not (written == source and before == after):
                continue
            baseline_written = (base_post.get(ref) or {}).get("unicode") or ""
            baseline_rebuilt = composition_digest(
                base_pre.get(ref, {})
            ) != composition_digest(base_post.get(ref, {}))
            if baseline_written == written and not baseline_rebuilt:
                continue
            rows.append(
                {
                    "arm": key,
                    "ref": ref,
                    "source": source,
                    "composition_sha256_before": before,
                    "composition_sha256_after": after,
                    "baseline_written": baseline_written,
                    "baseline_composition_rebuilt": baseline_rebuilt,
                    "text_differs_from_baseline": baseline_written != written,
                }
            )
    return {
        "baseline": str(BASELINE.relative_to(ROOT)),
        "run": str(RUN.relative_to(ROOT)),
        "isolation": str(ISOLATION.relative_to(ROOT)),
        "pre_checkpoint": PRE_CHECKPOINT,
        "post_checkpoint": POST_CHECKPOINT,
        "paragraphs": rows,
    }


def quote_paragraph(run: Path) -> tuple[str, dict] | tuple[None, None]:
    """The paragraph of the pull quote, found by the closing mark it ends with."""
    document = load(work_dir(run) / TYPESET_CHECKPOINT)
    for page in document.get("page") or ():
        if (page.get("page_number") or 0) + 1 != QUOTE_PAGE:
            continue
        for index, paragraph in enumerate(page.get("pdf_paragraph") or ()):
            text = paragraph.get("unicode") or ""
            if text.startswith("“") and text.endswith("”"):
                return f"p{QUOTE_PAGE}#{index}", paragraph
    return None, None


def spans(pdf: Path, page_index: int, keep) -> list[dict]:
    import pymupdf

    found = []
    with pymupdf.open(pdf) as document:
        for block in document[page_index].get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if not keep(span):
                        continue
                    found.append(
                        {
                            "text": span["text"],
                            "font": span["font"],
                            "size": round(span["size"], 2),
                            "bbox": [round(value, 2) for value in span["bbox"]],
                        }
                    )
    return found


def vertical_rules(pdf: Path, page_index: int) -> list[dict]:
    """Every vertical stroke of one page, which is what a column rule is drawn as."""
    import pymupdf

    found = []
    with pymupdf.open(pdf) as document:
        for drawing in document[page_index].get_drawings():
            rect = drawing["rect"]
            if abs(rect.x1 - rect.x0) > 1.0 or (rect.y1 - rect.y0) < 100.0:
                continue
            found.append(
                {
                    "x": round(rect.x0, 2),
                    "y": [round(rect.y0, 2), round(rect.y1, 2)],
                }
            )
    return sorted(found, key=lambda entry: entry["x"])


def hang_determination() -> dict:
    """The four numbers the bound was decided on, and where the mark ends now."""
    ref, paragraph = quote_paragraph(BASELINE)
    box = paragraph["box"]
    style = paragraph.get("pdf_style") or {}
    font_size = float(style.get("font_size") or 0.0)
    scale = float(paragraph.get("scale") or 1.0)
    after_ref, after_paragraph = quote_paragraph(RUN)

    def quote_spans(pdf: Path) -> list[dict]:
        return spans(
            pdf,
            QUOTE_PAGE - 1,
            lambda span: span["size"] > 18 and span["bbox"][0] > 200,
        )

    rules = vertical_rules(BASELINE_PDF, QUOTE_PAGE - 1)
    before = quote_spans(BASELINE_PDF)
    after = quote_spans(RUN / "FD-en-v2.b11_1.pdf")
    rule_x = min(
        (entry["x"] for entry in rules if entry["x"] > box["x2"]),
        default=None,
    )
    return {
        "baseline_pdf": str(BASELINE_PDF.relative_to(ROOT)),
        "run_pdf": str((RUN / "FD-en-v2.b11_1.pdf").relative_to(ROOT)),
        "checkpoint": TYPESET_CHECKPOINT,
        "before": {
            "ref": ref,
            "box_x2": round(float(box["x2"]), 4),
            "font_size": font_size,
            "scale": scale,
            "em": round(font_size * scale, 4),
            "column_rule_x": rule_x,
            "column_rules": rules,
            "spans": before,
            "rightmost_ink_x": max(span["bbox"][2] for span in before),
            "overflow_by_span": [
                {
                    "text": span["text"],
                    "x1": span["bbox"][2],
                    "overflow": round(span["bbox"][2] - float(box["x2"]), 3),
                    "crosses_rule": rule_x is not None and span["bbox"][2] > rule_x,
                }
                for span in before
            ],
        },
        "after": {
            "ref": after_ref,
            "box_x2": round(float(after_paragraph["box"]["x2"]), 4),
            "scale": float(after_paragraph.get("scale") or 1.0),
            "spans": after,
            "rightmost_ink_x": max(span["bbox"][2] for span in after),
        },
    }


def head_band(pdf: Path) -> dict:
    """What each running head page draws in its top band, in both runs."""
    return {
        str(label): spans(
            pdf,
            label - 1,
            lambda span: span["bbox"][1] < HEAD_BAND,
        )
        for label in HEAD_PAGES
    }


def name_annotations(pdf: Path) -> dict:
    import pymupdf

    narrow, broad = [], []
    with pymupdf.open(pdf) as document:
        for index in range(document.page_count):
            text = document[index].get_text().replace("\n", "")
            for match in NAME_ANNOTATION.finditer(text):
                narrow.append({"page": index + 1, "match": match.group(0)})
            for match in NAME_ANNOTATION_BROAD.finditer(text):
                broad.append(
                    {
                        "page": index + 1,
                        "context": text[match.start() : match.start() + 40],
                    }
                )
    return {"name_shaped": narrow, "broad_pattern": broad}


def pixel_evidence() -> dict:
    run_pdf = RUN / "FD-en-v2.b11_1.pdf"
    return {
        "baseline_pdf": str(BASELINE_PDF.relative_to(ROOT)),
        "run_pdf": str(run_pdf.relative_to(ROOT)),
        "head_band_points": HEAD_BAND,
        "head_pages": list(HEAD_PAGES),
        "baseline_head_band": head_band(BASELINE_PDF),
        "run_head_band": head_band(run_pdf),
        "baseline_name_annotations": name_annotations(BASELINE_PDF),
        "run_name_annotations": name_annotations(run_pdf),
    }


def main() -> int:
    missing = [
        path
        for path in (
            work_dir(RUN) / PRE_CHECKPOINT,
            work_dir(BASELINE) / PRE_CHECKPOINT,
            work_dir(ISOLATION) / PRE_CHECKPOINT,
            BASELINE_PDF,
            RUN / "FD-en-v2.b11_1.pdf",
        )
        if not path.exists()
    ]
    if missing:
        for path in missing:
            print(f"missing: {path}")
        return 1
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for name, record in (
        ("identity_writeback.json", identity_table()),
        ("hang_determination.json", hang_determination()),
        ("pixel_evidence.json", pixel_evidence()),
    ):
        path = EVIDENCE / name
        with path.open("w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
