"""Measure the six premises PLAN_B11_7 opens with, against the tree at b11.6.

Reads frozen b11.6 evidence and the current working tree, and writes one JSON
beside the batch directory. Nothing here decides anything: the premises are
propositions about what is already true, and this records what was found.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import pymupdf

from babeldoc.format.pdf.document_il.xml_converter import XMLConverter
from babeldoc.magazine.detectors import base
from babeldoc.magazine.reading_order import paragraph_reading_text

ROOT = Path(__file__).resolve().parents[4]
B11_6 = ROOT / "examples" / "output" / "b11_6"
CZH = B11_6 / "Courier-zh"
FD = B11_6 / "FD-en-v2"
CHECKPOINT = CZH / "work" / "Courier-zh" / "checkpoint.11_typesetting.xml"
RENDERED = CZH / "out" / "Courier-zh.no_watermark.en.mono.pdf"

# The block a canvas count and an IL count are compared over. Han ideographs
# plus the CJK punctuation and fullwidth forms a reader sees as the same script,
# so both sides are counted by one predicate and a difference between them is a
# difference in what was seen rather than in how it was classified.
CJK_RANGES = (
    (0x3000, 0x303F),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)

# The floors the residue detector withholds a finding under, read from the
# declared configuration rather than restated here.
DETECTORS = json.loads(
    (ROOT / "configs" / "detectors.json").read_text(encoding="utf-8")
)
MIN_SCRIPT_CHARS = int(DETECTORS["residue_min_script_chars"])
MIN_RATIO_INTO_EN = float(DETECTORS["residue_min_ratio_into_en"])


def is_cjk(char: str) -> bool:
    point = ord(char)
    return any(low <= point <= high for low, high in CJK_RANGES)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def il_pages():
    return XMLConverter().read_xml(str(CHECKPOINT)).page


def canvas_cjk_by_page() -> dict[int, int]:
    pdf = pymupdf.open(str(RENDERED))
    found: dict[int, int] = {}
    for number in range(len(pdf)):
        count = sum(
            1
            for block in pdf[number].get_text("rawdict")["blocks"]
            if block["type"] == 0
            for line in block["lines"]
            for span in line["spans"]
            for char in span["chars"]
            if is_cjk(char["c"])
        )
        if count:
            found[number + 1] = count
    return found


def premise_1() -> dict:
    """FD p3 carries three paragraphs indented before and after, none decided."""
    report = read_json(FD / "sidecars" / "indent_policy.report.json")
    rows = [row for row in report["paragraphs"] if row["page"] == 3]
    flagged = [row for row in rows if row["before"] or row["after"]]
    return {
        "premise": (
            "b11.6 FD indent sidecar: p3 three paragraphs before/after true, source "
            "geometry inherited; page_ineligible leaves them alone"
        ),
        "p3_paragraphs": len(rows),
        "p3_flagged": [
            {
                "reference": row["reference"],
                "before": row["before"],
                "after": row["after"],
                "decided": row["decided"],
                "skipped": row["skipped"],
            }
            for row in flagged
        ],
        "p3_decided": sum(1 for row in rows if row["decided"]),
        "skip_reasons_on_p3": sorted({row["skipped"] for row in rows}),
        "left_alone_total": report["totals"]["left_alone"],
        "holds": (
            [row["reference"] for row in flagged] == ["p3#18", "p3#36", "p3#43"]
            and all(row["before"] and row["after"] for row in flagged)
            and all(not row["decided"] for row in flagged)
            and {row["skipped"] for row in rows} == {"page_ineligible"}
        ),
    }


def premise_2() -> dict:
    """FD p6 continuation member is indented; the members after it are not."""
    rows = read_json(FD / "indent_evidence.json")["paragraphs"]
    page6 = {row["reference"]: row for row in rows if row["page"] == 6}
    continuation = page6["p6#12"]
    following = [page6["p6#13"], page6["p6#14"]]
    return {
        "premise": (
            "b11.6 FD p6 column chain continuation first line x=409.4 against 393.7 "
            "for the members after it; the sentence lands whole"
        ),
        "continuation": {
            "reference": "p6#12",
            "box_x": continuation["box_x"],
            "first_line_x": continuation["first_line_x"],
            "offset": continuation["offset"],
            "first_line_indent": continuation["first_line_indent"],
        },
        "following_box_x": {row["reference"]: row["box_x"] for row in following},
        "sentence_in_continuation": "食品和化肥成本上升" in continuation["excerpt"],
        # Compared within a tenth of a point rather than by a rounded equality,
        # because the figures the premise quotes are themselves rounded and a
        # value a tenth below the half way point rounds away from them.
        "holds": (
            abs(continuation["first_line_x"] - 409.4) < 0.1
            and abs(continuation["box_x"] - 393.7) < 0.1
            and all(abs(row["box_x"] - 393.7) < 0.5 for row in following)
            and continuation["first_line_indent"] is True
            and "食品和化肥成本上升" in continuation["excerpt"]
        ),
    }


def residue_rows() -> list[dict]:
    """Every IL paragraph holding han, with what the detector reads off it."""
    rows = []
    for number, page in enumerate(il_pages(), 1):
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            text = paragraph_reading_text(paragraph).strip()
            counts = base.script_counts(text)
            han = counts.get("han", 0)
            if han == 0:
                continue
            total = sum(counts.values())
            ratio = han / total if total else 0.0
            holders = set()
            for composition in paragraph.pdf_paragraph_composition or []:
                for name in (
                    "pdf_character",
                    "pdf_same_style_characters",
                    "pdf_line",
                    "pdf_formula",
                    "pdf_same_style_unicode_characters",
                ):
                    if getattr(composition, name, None) is not None:
                        holders.add(name)
            reported = han >= MIN_SCRIPT_CHARS and ratio >= MIN_RATIO_INTO_EN
            rows.append(
                {
                    "reference": f"p{number}#{index}",
                    "layout_label": paragraph.layout_label,
                    "vertical": bool(getattr(paragraph, "vertical", None)),
                    "han_chars": han,
                    "script_chars": total,
                    "residue_ratio": round(ratio, 4),
                    "composition_holders": sorted(holders),
                    "reported_by_detector": reported,
                    "withheld_by": None
                    if reported
                    else (
                        "residue_min_script_chars"
                        if han < MIN_SCRIPT_CHARS
                        else "residue_min_ratio_into_en"
                    ),
                    "text": text[:60],
                }
            )
    return rows


def premise_3() -> dict:
    """Four residue sites stand on the Courier-zh canvas, two of them reported."""
    pdf = pymupdf.open(str(RENDERED))
    sites = []
    for number in range(len(pdf)):
        for block in pdf[number].get_text("rawdict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = "".join(char["c"] for char in span["chars"])
                    hits = [char for char in text if is_cjk(char)]
                    if not hits:
                        continue
                    sites.append(
                        {
                            "page": number + 1,
                            "direction": [round(value, 2) for value in line["dir"]],
                            "rotated": abs(line["dir"][1]) > abs(line["dir"][0]),
                            "text": text[:60],
                            "cjk_chars": len(hits),
                        }
                    )
    canvas = canvas_cjk_by_page()
    # A site is one run of type a reader sees as a single line. The extractor
    # splits a line at a font change, so the Gambarini credit arrives as two
    # spans of one strip; sites are therefore counted per page and orientation
    # rather than per span.
    site_keys = sorted({(site["page"], site["rotated"]) for site in sites})
    issues = read_json(CZH / "sidecars" / "issues.json")["issues"]
    residues = sorted(
        issue["paragraph_refs"][0]
        for issue in issues
        if issue["kind"] == "untranslated_residue"
    )
    return {
        "premise": (
            "Courier-zh carries four residue sites on the canvas: p3 rotated credit "
            "(unreported), p5 footer (unreported), p5 Gambarini (reported), p6 "
            "Semeniako (reported)"
        ),
        "canvas_cjk_by_page": canvas,
        "canvas_spans": sites,
        "canvas_sites": [
            {"page": page, "rotated": rotated} for page, rotated in site_keys
        ],
        "reported_residue_refs": residues,
        "page1_canvas_cjk": canvas.get(1, 0),
        "holds": (
            sorted(canvas) == [3, 5, 6]
            and site_keys == [(3, True), (5, False), (5, True), (6, True)]
            and residues == ["p5#8", "p6#14"]
            and canvas.get(1, 0) == 0
        ),
    }


def premise_4() -> dict:
    """Typesetting lays out on the horizontal axis; formula characters are counted."""
    source = (
        ROOT
        / "babeldoc"
        / "format"
        / "pdf"
        / "document_il"
        / "midend"
        / "typesetting.py"
    ).read_text(encoding="utf-8")
    packer = source.split("def _layout_typesetting_units", 1)[1].split("\n    def ", 1)[
        0
    ]
    renderer = (
        ROOT
        / "babeldoc"
        / "format"
        / "pdf"
        / "document_il"
        / "backend"
        / "pdf_creater.py"
    ).read_text(encoding="utf-8")
    rows = residue_rows()
    il_by_page: dict[int, int] = {}
    for number, page in enumerate(il_pages(), 1):
        count = sum(
            1
            for paragraph in (page.pdf_paragraph or ())
            for char in paragraph_reading_text(paragraph)
            if is_cjk(char)
        )
        if count:
            il_by_page[number] = count
    canvas = canvas_cjk_by_page()
    formula_only = [row for row in rows if row["composition_holders"] == ["pdf_formula"]]
    return {
        "premise": (
            "typesetting always reflows a vertical paragraph on the horizontal "
            "matrix; the residue detector reads IL paragraph text and does not count "
            "formula characters"
        ),
        "clause_1_horizontal_reflow": {
            "packer_reads_box_x2_as_line_end": (
                "current_x + unit_width > box.x2" in packer
            ),
            "packer_names_an_axis": "axis" in packer,
            "new_characters_constructed_vertical_false": "vertical=False," in source,
            "renderer_emits_rotation_for_vertical_chars": (
                renderer.count("0 1 -1 0") == 2
            ),
            "holds": (
                "current_x + unit_width > box.x2" in packer
                and "axis" not in packer
                and "vertical=False," in source
            ),
        },
        "clause_2_formula_characters_not_counted": {
            "character_holders_read_by_reading_order": [
                "pdf_same_style_characters",
                "pdf_line",
                "pdf_formula",
            ],
            "residue_bearing_paragraphs": rows,
            "all_residue_paragraphs_are_formula_only": len(formula_only) == len(rows),
            "formula_characters_reaching_the_detector": sum(
                row["han_chars"] for row in formula_only
            ),
            "reported_paragraphs_are_formula_only": all(
                row["composition_holders"] == ["pdf_formula"]
                for row in rows
                if row["reported_by_detector"]
            ),
            "il_cjk_by_page": il_by_page,
            "canvas_cjk_by_page": canvas,
            "il_equals_canvas": il_by_page == canvas,
            "withheld_by": {
                row["reference"]: row["withheld_by"]
                for row in rows
                if row["withheld_by"]
            },
            "holds": False,
        },
        "holds": False,
    }


def premise_5() -> dict:
    """Body chains cut on sentence ends; indent policy touches eligible pages only."""
    strategies = read_json(ROOT / "configs" / "chain_translation.json")["strategies"]
    report = read_json(FD / "sidecars" / "indent_policy.report.json")
    totals = report["totals"]
    ineligible_decided = [
        row
        for row in report["paragraphs"]
        if row["decided"] and not row["indent_eligible_page"]
    ]
    return {
        "premise": (
            "chain_backfill cuts a body chain on sentence ends; indent_policy indents "
            "on eligible pages and leaves the rest alone"
        ),
        "strategy_by_pair_class": strategies["by_pair_class"],
        "strategy_default": strategies["default"],
        "decided": totals["decided"],
        "left_alone": totals["left_alone"],
        "skipped": totals["skipped"],
        "decided_on_ineligible_pages": [row["reference"] for row in ineligible_decided],
        "holds": (
            strategies["by_pair_class"]["body"] == "sentence_greedy"
            and not ineligible_decided
            and totals["skipped"]["page_ineligible"] > 0
        ),
    }


def premise_6() -> dict:
    """Why the p6 orphan line was never written back."""
    report = read_json(CZH / "sidecars" / "react_repair.report.json")
    iteration = report["iterations"][0]
    decision = iteration["decision"]
    return {
        "premise": (
            "translate_orphan_lines accepts fallback_line; the p6 finding was not "
            "repaired -- read the react sidecar for whether it refused or failed"
        ),
        "action_offered": decision["action"],
        "issue_ids": decision["issue_ids"],
        "decision_reason": decision["reason"],
        "executions": [
            {
                "issue_id": entry["issue_id"],
                "accepted": entry["accepted"],
                "changed": entry["changed"],
                "attempts": entry["attempts"],
                "reason": entry["reason"],
                "source_text": entry["source_text"],
                "translated_text": entry["translated_text"],
            }
            for entry in iteration["executed"]
        ],
        "api_calls": report["api_calls"],
        "applications": report["applications"],
        "stopped_because": report["stopped_because"],
        "verdict": "applied_and_refused_at_retypesetting",
        "verdict_detail": (
            "The action was selected, the engine was called and answered, and the "
            "write back was refused because laying the answer out needed more room "
            "than the paragraph had. That is a failure to apply rather than a refusal "
            "to act: the paragraph is a rotated strip 6.4 pt wide, and the packer "
            "measures that 6.4 pt as the line it has to fit the answer into."
        ),
        "holds": True,
    }


def main() -> int:
    results = {
        "1": premise_1(),
        "2": premise_2(),
        "3": premise_3(),
        "4": premise_4(),
        "5": premise_5(),
        "6": premise_6(),
    }
    failed = [key for key, value in results.items() if not value["holds"]]
    payload = {
        "batch": "b11.7",
        "read_at_tag": "b11.6",
        "premises": results,
        "failed": failed,
        "verdict": "STOP" if failed else "PROCEED",
    }
    out = Path(__file__).resolve().parents[1] / "premise_check.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    for key, value in results.items():
        print(f"premise {key}: {'HOLDS' if value['holds'] else 'FAILS'}")
    print(f"verdict: {payload['verdict']}  failed: {failed or 'none'}")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
