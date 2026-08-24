"""T1 step 2a: how often a body paragraph sits inside a filled panel.

The indent policy is about to gain a second gate. The first is the page level
one, read from the page type vocabulary. The second would be a box level one: a
body paragraph set inside a tint panel is a sidebar or an information box, which
is furniture with its own setting rather than the article's running text, and a
paragraph convention written for the article is wrong for it.

Whether that second gate ships is a determination, not a decision taken in
advance. This script is the measurement it turns on. It reads the b10.5 on arm
checkpoints -- offline, no pipeline run, no network -- lists every instance the
rule would catch, and writes the list. If the list is sidebars and information
boxes, the gate ships; if it holds the article's own running text, it does not.

Two facts about the corpus shape the reading and are recorded rather than worked
around. A filled panel reaches the intermediate language as a pdfCurve with
fillBackground set, not as a pdfRectangle: the rectangle collection is empty on
all six samples, which is why the reflow pass declares five collections rather
than one. And a great many of those filled curves are the page's own ground,
covering the whole sheet; a paragraph is not inside a panel by being printed on
the paper.

Usage:
    python t1_boxed_measure.py [--min-area-ratio R] [--containment C] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import indent_policy  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402

BASELINE = "b10_5"
ARM = "on"
# The last checkpoint before the page classifier, which carries the geometry the
# indent pass will meet: no later stage moves a paragraph box.
SOURCE_STAGE = "checkpoint.06_styles_and_formulas.xml"
# Every page level collection a filled panel may reach the intermediate language
# through, the same set the reflow pass declares as obstacles.
PANEL_COLLECTIONS = ("pdf_rectangle", "pdf_curve", "pdf_form", "pdf_figure")

# Share of the page a panel covers before it is read as the page's own ground
# rather than as a box on it. Reported, not applied: the rule under measurement
# declares a floor and no ceiling, and this column exists so that the reading
# can say how much of the catch the floor alone lets through.
GROUND_RATIO = 0.9


def page_frame(page):
    if page.cropbox is not None and page.cropbox.box is not None:
        return page.cropbox.box
    if page.mediabox is not None and page.mediabox.box is not None:
        return page.mediabox.box
    return None


def box_tuple(box):
    if box is None:
        return None
    return (
        min(box.x, box.x2),
        min(box.y, box.y2),
        max(box.x, box.x2),
        max(box.y, box.y2),
    )


def area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def overlap(first, second) -> float:
    return area(
        (
            max(first[0], second[0]),
            max(first[1], second[1]),
            min(first[2], second[2]),
            min(first[3], second[3]),
        )
    )


def panels(page, page_area: float, min_ratio: float) -> list[dict]:
    """Every filled panel of one page that reaches the declared area floor."""
    found = []
    for name in PANEL_COLLECTIONS:
        for item in getattr(page, name, None) or ():
            if not getattr(item, "fill_background", False):
                continue
            box = box_tuple(getattr(item, "box", None))
            if box is None:
                continue
            ratio = area(box) / page_area if page_area > 0 else 0.0
            if ratio < min_ratio:
                continue
            found.append(
                {
                    "collection": name,
                    "box": [round(value, 2) for value in box],
                    "page_area_ratio": round(ratio, 4),
                }
            )
    return found


# Where the page kinds come from. The classifier writes them onto the pages at
# stage 07 and every later checkpoint carries them, so the checkpoint after the
# translator is what the chain builder actually saw. The classifier's own sidecar
# is deliberately not read: the copies archived beside two of the six baselines
# disagree with their run's checkpoints, so the sidecar answers for some
# classification and the checkpoint answers for this one.
KIND_STAGE = "checkpoint.09_il_translated.xml"


def page_kinds(sample: str) -> dict[int, tuple[str | None, float | None]]:
    """Each page's kind and confidence, as the run recorded them."""
    from babeldoc.format.pdf.document_il.xml_converter import XMLConverter

    path = (
        ROOT / "examples" / "output" / BASELINE / sample / ARM / "work" / sample
        / KIND_STAGE
    )
    if not path.is_file():
        return {}
    document = XMLConverter().from_xml(path.read_text(encoding="utf-8"))
    return {
        index: (page.page_kind, page.page_kind_conf)
        for index, page in enumerate(document.page)
    }


def measure(min_ratio: float, containment: float) -> dict:
    config = indent_policy.load_indent_config()
    taxonomy = load_taxonomy()
    body_labels = set(config.body_labels)
    samples = {}
    for entry in corpus.load_manifest()["samples"]:
        sample = entry["file"].removesuffix(".pdf")
        path = (
            ROOT
            / "examples"
            / "output"
            / BASELINE
            / sample
            / ARM
            / "work"
            / sample
            / SOURCE_STAGE
        )
        if not path.is_file():
            samples[sample] = {"error": f"no checkpoint at {path}"}
            continue
        document = XMLConverter().from_xml(path.read_text(encoding="utf-8"))
        kinds = {index: kind for index, (kind, _) in page_kinds(sample).items()}

        rows = []
        counts = {
            "body_paragraphs": 0,
            "panels": 0,
            "inside": 0,
            "inside_on_eligible_pages": 0,
            "inside_a_full_page_panel": 0,
        }
        for index, page in enumerate(document.page):
            frame = box_tuple(page_frame(page))
            if frame is None:
                continue
            page_area = area(frame)
            kind = kinds.get(index)
            policy = taxonomy.policy_of(kind)
            eligible = bool(policy and policy.get("indent_eligible", False))
            found = panels(page, page_area, min_ratio)
            counts["panels"] += len(found)
            for position, paragraph in enumerate(page.pdf_paragraph or ()):
                if paragraph.layout_label not in body_labels:
                    continue
                counts["body_paragraphs"] += 1
                box = box_tuple(paragraph.box)
                if box is None or area(box) <= 0:
                    continue
                for panel in found:
                    share = overlap(box, panel["box"]) / area(box)
                    if share < containment:
                        continue
                    counts["inside"] += 1
                    if eligible:
                        counts["inside_on_eligible_pages"] += 1
                    if panel["page_area_ratio"] >= GROUND_RATIO:
                        counts["inside_a_full_page_panel"] += 1
                    rows.append(
                        {
                            "page": index + 1,
                            "reference": f"p{index + 1}#{position}",
                            "page_kind": kind,
                            "indent_eligible_page": eligible,
                            "layout_label": paragraph.layout_label,
                            "paragraph_box": [round(value, 2) for value in box],
                            "panel": panel,
                            "containment": round(share, 4),
                            "excerpt": (paragraph.unicode or "")[:80],
                        }
                    )
                    break
        samples[sample] = {
            "source": str(path.relative_to(ROOT)).replace("\\", "/"),
            "counts": counts,
            "instances": rows,
        }
    return {
        "batch": "b11_6",
        "task": "T1 step 2a: body paragraphs inside a filled panel",
        "baseline": BASELINE,
        "arm": ARM,
        "stage": SOURCE_STAGE,
        "panel_collections": list(PANEL_COLLECTIONS),
        "ground_ratio": GROUND_RATIO,
        "boxed_min_area_ratio": min_ratio,
        "boxed_containment_ratio": containment,
        "samples": samples,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-area-ratio", type=float, default=0.02)
    parser.add_argument("--containment", type=float, default=0.9)
    parser.add_argument(
        "--out",
        default=str(ROOT / "examples" / "output" / "b11_6" / "t1_boxed_measure.json"),
    )
    args = parser.parse_args(argv)
    record = measure(args.min_area_ratio, args.containment)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for sample, result in record["samples"].items():
        if "error" in result:
            print(f"{sample:20s} {result['error']}")
            continue
        counts = result["counts"]
        print(
            f"{sample:20s} body={counts['body_paragraphs']:4d} "
            f"panels={counts['panels']:3d} inside={counts['inside']:4d} "
            f"on_eligible={counts['inside_on_eligible_pages']:4d} "
            f"full_page={counts['inside_a_full_page_panel']:4d}"
        )
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
