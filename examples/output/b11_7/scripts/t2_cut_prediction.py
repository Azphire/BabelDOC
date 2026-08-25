"""Cut every frozen b11.6 chain both ways, from the same text, and compare.

The question T2 answers is where a body chain should be cut. Comparing this
batch's pages against the previous batch's would compare two translations as
much as two cut rules, so the comparison is made here instead: the previous
batch's merged sources and joint translations are held constant and only the
rule varies. Both answers are computed by the shipped code.

The first half of the file is the determination the plan asked for -- which
packer the dry fit reuses -- recorded rather than assumed, because the answer
turned out to be "none of them".

Writes ``examples/output/b11_7/t2_cut_prediction.json``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import chain_backfill as backfill  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402

PRIOR = ROOT / "examples" / "output" / "b11_6"
OUT = Path(__file__).resolve().parents[1] / "t2_cut_prediction.json"

SAMPLES = (
    ("Courier-en", "zh"),
    ("AramcoWorld-en-v2", "zh"),
    ("FD-en-v2", "zh"),
    ("Courier-zh", "en"),
)

# Why the typesetting stage's own packer is not called to do the dry fit. Each
# of these was checked against the tree at b11.6 and is recorded so that the
# line grid reads as a decision and not as the first thing that came to hand.
WHY_NOT = [
    "_layout_typesetting_units is a method of the Typesetting stage and needs "
    "its font mapper, which is built from the run configuration at the stage "
    "and does not exist earlier.",
    "It takes TypesettingUnit objects built by create_typesetting_units from a "
    "paragraph's laid out characters. At the moment a chain is cut the "
    "translation is a string and has no characters behind it, so there is "
    "nothing for that packer to pack.",
    "chain_backfill is declared pure -- strings in, strings out, no "
    "intermediate language and no pipeline -- and importing the stage would "
    "invert that and pull the font mapper into the translation stage.",
]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    config = backfill.load_backfill_config()
    grid = config.capacity
    rows = []
    for sample, language in SAMPLES:
        work = PRIOR / sample / "work" / sample
        checkpoint = work / "checkpoint.08_chain_builder.xml"
        report_path = PRIOR / sample / "sidecars" / "chain_translation.report.json"
        evidence_path = PRIOR / sample / "chain_evidence.json"
        if not (checkpoint.is_file() and report_path.is_file()):
            continue
        document = load_checkpoint(checkpoint)
        paragraphs = {}
        for index, page in enumerate(document.page, 1):
            for paragraph in page.pdf_paragraph or ():
                if paragraph.debug_id:
                    paragraphs[paragraph.debug_id] = (index, paragraph)
        report = read_json(report_path)
        chain_evidence = read_json(evidence_path)
        sources = {
            chain["joint_translation"]: [member["source"] for member in chain["members"]]
            for chain in chain_evidence["chains"]
            if chain.get("joint_translation")
        }
        cjk = grid.is_cjk_target(language)
        advance = grid.advance_ratio_cjk if cjk else grid.advance_ratio_latin
        for entry in report.get("chains", ()):
            if entry["pair_class"] != "body":
                continue
            ids = [member["debug_id"] for member in entry["members"]]
            if any(item not in paragraphs for item in ids):
                continue
            pages = [paragraphs[item][0] for item in ids]
            kinds = [
                "column" if left == right else "page"
                for left, right in zip(pages, pages[1:], strict=False)
            ]
            translation = entry["translation"]
            texts = sources.get(translation)
            if texts is None:
                continue
            merge = backfill.merge_chain_text(texts, config)
            sentence = backfill.redistribute(
                merge, translation, language, backfill.STRATEGY_SENTENCE_GREEDY, config
            )
            capacities = []
            for item in ids:
                _page, paragraph = paragraphs[item]
                size = (
                    paragraph.pdf_style.font_size if paragraph.pdf_style else None
                )
                if paragraph.box is None or not size:
                    capacities = None
                    break
                capacities.append(
                    grid.characters_in(
                        float(paragraph.box.x2) - float(paragraph.box.x),
                        float(paragraph.box.y2) - float(paragraph.box.y),
                        float(size),
                        language,
                    )
                )
            measurable = bool(capacities) and all(item > 0 for item in capacities)
            row = {
                "sample": sample,
                "target_lang": language,
                "first_page": pages[0],
                "boundary_kinds": kinds,
                "measurable": measurable,
                "translation_chars": len(translation),
            }
            if not measurable:
                row["note"] = "a member carries no box or no font size; the cut falls back"
                rows.append(row)
                continue
            capacity = backfill.redistribute(
                merge,
                translation,
                language,
                backfill.STRATEGY_CAPACITY,
                config,
                capacities=capacities,
            )
            _page, first = paragraphs[ids[0]]
            size = float(first.pdf_style.font_size)
            width = float(first.box.x2) - float(first.box.x)
            per_line = int(width // (size * advance))
            cut_sentence = sentence.segments[0].end
            cut_capacity = capacity.segments[0].end

            def last_line_fill(cut: int) -> float:
                if per_line < 1:
                    return 1.0
                remainder = min(cut, capacities[0]) % per_line
                return 1.0 if remainder == 0 else remainder / per_line

            def quality(cut: int) -> list:
                # Two numbers, compared in order. A cut past the box's capacity
                # overflows it and the stage answers by shrinking the whole
                # paragraph, so an overfull box is worse than any well filled
                # one however full its last line reads; only among boxes that
                # fit does the last line decide. A single fill figure would
                # score the overflow as a perfect fill, which is how a cut that
                # made the page worse could pass for a cut that improved it.
                return [0 if cut > capacities[0] else 1, last_line_fill(cut)]

            row.update(
                {
                    "capacities": capacities,
                    "characters_per_line": per_line,
                    "cut_sentence": cut_sentence,
                    "cut_capacity": cut_capacity,
                    "overflowed_sentence": cut_sentence > capacities[0],
                    "overflowed_capacity": cut_capacity > capacities[0],
                    "last_line_fill_sentence": round(last_line_fill(cut_sentence), 4),
                    "last_line_fill_capacity": round(last_line_fill(cut_capacity), 4),
                    "quality_sentence": quality(cut_sentence),
                    "quality_capacity": quality(cut_capacity),
                    "cut_displacement": cut_capacity - capacity.cuts[0].estimate,
                    "moved_to": capacity.cuts[0].moved_to,
                }
            )
            rows.append(row)

    measured = [row for row in rows if row["measurable"]]
    payload = {
        "batch": "b11.7",
        "read_from": "examples/output/b11_6",
        "implementation": {
            "reused_the_general_packer": False,
            "why_not": WHY_NOT,
            "chosen": "line_grid_arithmetic",
            "grid": {
                "line_skip_cjk": grid.line_skip_cjk,
                "line_skip_latin": grid.line_skip_latin,
                "advance_ratio_cjk": grid.advance_ratio_cjk,
                "advance_ratio_latin": grid.advance_ratio_latin,
            },
        },
        "totals": {
            "chains": len(rows),
            "measurable": len(measured),
            "overflowed_sentence": sum(
                1 for row in measured if row["overflowed_sentence"]
            ),
            "overflowed_capacity": sum(
                1 for row in measured if row["overflowed_capacity"]
            ),
            "better": sum(
                1
                for row in measured
                if row["quality_capacity"] > row["quality_sentence"]
            ),
            "worse": sum(
                1
                for row in measured
                if row["quality_capacity"] < row["quality_sentence"]
            ),
            "unchanged": sum(
                1
                for row in measured
                if row["quality_capacity"] == row["quality_sentence"]
            ),
        },
        "chains": rows,
    }
    OUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload["totals"], indent=1))
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
