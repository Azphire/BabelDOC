"""T2: drive the shipped detector over the frozen baseline and read the answer.

The adjudication in ``reviews/column_pairs.adjudication.json`` rules on the 24
column pairs the b11.2 measurement scored above the link threshold. This script
puts the shipped code in front of the same six documents and writes what it
does with them, pair by pair, beside the ruling: which pairs the four gates
leave linked, which edges exclusive assembly then takes, and which chains the
edges close into.

It is offline and reads no network. The geometry and the text come from the
b10.5 on arm checkpoint before the page classifier; the page kinds come from
that same run's checkpoint after the translator, which is where the classifier
left them, and are written onto the parsed pages so that the policy gates read
what the run read. Nothing under a run's working directory is written.

This is a prediction and not the batch's own evidence: the connection set the
gate answers to is the one the b11.6 run itself produces. It exists so that the
gates can be checked before a single request is spent, and so that the report
can say which of the two agrees with which.

Usage:
    python t2_predict.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import chain_signals as cs  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine.chain_builder import _accepted_edges  # noqa: E402
from babeldoc.magazine.chain_builder import _chains_from  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402

BASELINE = "b10_5"
ARM = "on"
SOURCE_STAGE = "checkpoint.06_styles_and_formulas.xml"
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
ADJUDICATION = ROOT / "reviews" / "column_pairs.adjudication.json"


def load_document(sample: str):
    path = (
        ROOT / "examples" / "output" / BASELINE / sample / ARM / "work" / sample
        / SOURCE_STAGE
    )
    if not path.is_file():
        return None, f"no checkpoint at {path}"
    document = XMLConverter().from_xml(path.read_text(encoding="utf-8"))
    kinds = page_kinds(sample)
    if not kinds:
        return None, f"no page kinds beside {path}"
    for index, page in enumerate(document.page):
        kind, confidence = kinds.get(index, (None, None))
        page.page_kind = kind
        page.page_kind_conf = confidence
    return document, str(path.relative_to(ROOT)).replace("\\", "/")


def run(sample: str, config, taxonomy) -> dict:
    document, source = load_document(sample)
    if document is None:
        return {"sample": sample, "error": source}
    pages = document.page
    verdicts = []
    for index, page in enumerate(pages):
        verdicts.extend(
            cs.evaluate_column_boundaries(page, index, taxonomy.policy_of, config)
        )
        if index + 1 < len(pages):
            verdicts.append(
                cs.evaluate_boundary(
                    page, pages[index + 1], index, index + 1, taxonomy.policy_of, config
                )
            )
    taken, dropped = _accepted_edges(verdicts, config[cs.BOUNDARY_PRIORITY_KEY])
    chains = _chains_from(taken)
    reference = {}
    for index, page in enumerate(pages):
        for position, paragraph in enumerate(page.pdf_paragraph or ()):
            reference[id(paragraph)] = f"p{index + 1}#{position}"
    return {
        "sample": sample,
        "source": source,
        "column_boundaries": [
            verdict.as_record()
            for verdict in verdicts
            if verdict.kind == cs.BOUNDARY_COLUMN
        ],
        "linked": [
            verdict.label for verdict in verdicts if verdict.linked
        ],
        "edges": [
            {
                "boundary": verdict.label,
                "kind": verdict.kind,
                "pairing": verdict.pairing,
                "score": verdict.score,
            }
            for verdict in taken
        ],
        "dropped_edges": [
            {
                "boundary": verdict.label,
                "kind": verdict.kind,
                "pairing": verdict.pairing,
                "score": verdict.score,
                "dropped_reason": reason,
            }
            for verdict, reason in dropped
        ],
        "chains": [
            {
                "length": len(chain),
                "members": [reference[id(paragraph)] for paragraph in chain],
                "pages": sorted({reference[id(p)].split("#")[0] for p in chain}),
            }
            for chain in chains
        ],
    }


def against_the_ruling(results: dict) -> dict:
    """Every ruled pair beside what the detector did with it."""
    if not ADJUDICATION.is_file():
        return {"error": f"no adjudication at {ADJUDICATION}"}
    with ADJUDICATION.open(encoding="utf-8") as f:
        ruling = json.load(f)
    rows = []
    for pair in ruling["pairs"]:
        sample = pair["sample"]
        result = results.get(sample) or {}
        boundary = f"p{pair['page']}:c{pair['tail_column']}->c{pair['head_column']}"
        record = next(
            (
                row
                for row in result.get("column_boundaries", ())
                if row["boundary"] == boundary
            ),
            None,
        )
        # A page refused whole leaves one row for the page rather than one per
        # pair, so the reason for this pair is that page's reason.
        page_refusal = next(
            (
                row
                for row in result.get("column_boundaries", ())
                if row["boundary"] == f"p{pair['page']}:columns"
            ),
            None,
        )
        edge = any(
            item["boundary"] == boundary for item in result.get("edges", ())
        )
        dropped = next(
            (
                item
                for item in result.get("dropped_edges", ())
                if item["boundary"] == boundary
            ),
            None,
        )
        rows.append(
            {
                "sample": sample,
                "boundary": boundary,
                "pairing": pair["pairing"],
                "ruled": pair["continues"],
                "scored": None if record is None else record["score"],
                "reason": record["reason"]
                if record is not None
                else (None if page_refusal is None else page_refusal["reason"]),
                "linked": bool(record and record["linked"]),
                "is_edge": edge,
                "dropped_reason": None if dropped is None else dropped["dropped_reason"],
                "agrees": bool(edge) == bool(pair["continues"]),
            }
        )
    return {
        "ruled_pairs": len(rows),
        "true_pairs": sum(1 for row in rows if row["ruled"]),
        "false_pairs": sum(1 for row in rows if not row["ruled"]),
        "true_taken": sum(1 for row in rows if row["ruled"] and row["is_edge"]),
        "false_taken": sum(1 for row in rows if not row["ruled"] and row["is_edge"]),
        "disagreements": [row["boundary"] for row in rows if not row["agrees"]],
        "rows": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(ROOT / "examples" / "output" / "b11_6" / "t2_prediction.json"),
    )
    args = parser.parse_args(argv)

    config = cs.load_chain_config()
    taxonomy = load_taxonomy()
    results = {}
    for entry in corpus.load_manifest()["samples"]:
        sample = entry["file"].removesuffix(".pdf")
        results[sample] = run(sample, config, taxonomy)
    record = {
        "batch": "b11_6",
        "task": "T2: the shipped detector over the frozen baseline",
        "baseline": BASELINE,
        "arm": ARM,
        "stage": SOURCE_STAGE,
        "link_min_score": config["link_min_score"],
        "head_clear_gap_em": config[cs.HEAD_CLEAR_GAP_KEY],
        "boundary_priority": list(config[cs.BOUNDARY_PRIORITY_KEY]),
        "column_head_block_classes": list(config[cs.HEAD_BLOCK_CLASSES_KEY]),
        "against_the_ruling": against_the_ruling(results),
        "samples": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for sample, result in results.items():
        if "error" in result:
            print(f"{sample:20s} {result['error']}")
            continue
        columns = [row for row in result["column_boundaries"] if row["linked"]]
        edges = [item for item in result["edges"] if item["kind"] == "column"]
        print(
            f"{sample:20s} column_linked={len(columns):3d} column_edges={len(edges):3d} "
            f"chains={len(result['chains']):3d}"
        )
    summary = record["against_the_ruling"]
    if "error" not in summary:
        print(
            f"ruling: {summary['true_taken']}/{summary['true_pairs']} true taken, "
            f"{summary['false_taken']}/{summary['false_pairs']} false taken, "
            f"disagreements={summary['disagreements']}"
        )
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
