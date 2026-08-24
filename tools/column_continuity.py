"""Measure whether a sentence runs on across a column break inside one page.

The chain detector once walked adjacent *pages* only: it scored the last
endpoint of page N against the first of page N+1. A magazine sets three columns
to a page, and a noun phrase broken across the second and third column of one
page is a handover of exactly the same kind, which that walk could not reach by
construction. This tool was the measurement that had to come before any decision
about it, and it is what b11.6 decided from.

It takes the same column bands the chain detector derives -- literally the same
function, ``chain_signals.page_columns``, rather than a copy of it -- pairs each
column's last paragraph with the next column's first, computes the signals the
page level walk already has, and scores the pair with the weights and threshold
in force. It writes a report and nothing else: no paragraph is touched, no chain
is built, no file inside a run's working directory is written.

What it deliberately does not apply is the qualification the detector applies. A
page kind is not read here and the head clearance gate is not run, because this
is the measurement of what the *scoring* says, and separating what the score
says from what the gates then withdraw is the whole reason the measurement
exists. The detector's own report is where the gated answer is read.

Two of the six signals cannot mean here what they mean across a page break, and
both are handled by saying so rather than by pretending: ``column_position`` is
one by construction, because the pairing is chosen to be exactly the position it
asks about, and ``opener_prior`` is zero, because a column declares no kind.
Both constants are declared in ``chain_signals`` and read from there. A seventh
signal, whether the tail ends on a hyphen, is computed and not scored, because
its weight has never been calibrated.

Usage:
    python tools/column_continuity.py [--batch b10_5] [--arm on] [--stage NAME]
                                      [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import chain_signals  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402

# The stage whose checkpoint this reads by default. The chain builder consumes
# the intermediate language before the translator rewrites it, so the text
# scored here is the text the detector would have scored.
SOURCE_STAGE = "checkpoint.08_chain_builder.xml"

# The stage before the page classifier, which carries the same paragraphs and
# the same geometry and is what remains on disk once a batch's own checkpoints
# have been through the retention window. Offered so that this measurement stays
# replayable against a baseline whose stage 08 has gone.
EARLIER_STAGE = "checkpoint.06_styles_and_formulas.xml"


def first_line_text(item) -> str:
    return chain_signals.line_text(item[2][0])


def page_column_pairs(page, page_index, config):
    """Every (column n last, column n+1 first) pair of one page, scored."""
    columns = chain_signals.page_columns(page, config)
    if columns is None or len(columns.order) < 2:
        return []
    rows = []
    for pairing, tail_band, head_band in chain_signals.column_pairings(columns.order):
        rows.extend(
            _pair_rows(pairing, page, page_index, columns, tail_band, head_band, config)
        )
    return rows


def _pair_rows(kind, page, page_index, columns, index, following, config):
    """One pairing of two columns, scored, or nothing where no rule takes it."""
    tail_item = columns.columns[index][-1]
    head_item = columns.columns[following][0]
    tail = chain_signals.build_endpoint(
        tail_item, page_index, columns.bands, columns.families
    )
    head = chain_signals.build_endpoint(
        head_item, page_index, columns.bands, columns.families
    )
    values = {
        "tail_no_terminal_punct": chain_signals.tail_no_terminal_punct(tail, config),
        "tail_line_fill": chain_signals.tail_line_fill(tail, config),
        "style_continuity": chain_signals.style_continuity(tail, head, config),
        "body_label_pair": chain_signals.body_label_pair(tail, head, config),
        "column_position": chain_signals.IN_PAGE_COLUMN_POSITION,
        "opener_prior": chain_signals.IN_PAGE_OPENER_PRIOR,
    }
    labels = config[chain_signals.CLASS_LABELS_KEY]
    best = None
    for rule in config[chain_signals.PAIR_RULES_KEY]:
        if tail.label not in labels.get(rule.tail_class, ()):
            continue
        if head.label not in labels.get(rule.head_class, ()):
            continue
        score = chain_signals.combine(values, rule.weights)
        if best is None or score > best[1]:
            best = (rule, score, rule.weights)
    if best is None:
        return [
            {
                "pairing": kind,
                "page": page.page_number + 1,
                "tail_column": index,
                "head_column": following,
                "column_count": len(columns.bands),
                "pair": None,
                "tail_label": tail.label,
                "head_label": head.label,
                "not_scored": (
                    "no declared pairing takes these two endpoint classes, so the "
                    "weights never see this pair"
                ),
                "tail_last_line": tail.last_line_text or "",
                "head_first_line": first_line_text(head_item),
                "tail_text": (tail.paragraph.unicode or "")[-220:],
                "head_text": (head.paragraph.unicode or "")[:220],
            }
        ]
    rule, score, weights = best
    constant_share = (
        weights.get("column_position", 0.0) * chain_signals.IN_PAGE_COLUMN_POSITION
    )
    return [
        {
            "pairing": kind,
            "page": page.page_number + 1,
            "tail_column": index,
            "head_column": following,
            "column_count": len(columns.bands),
            "pair": rule.name,
            "tail_label": tail.label,
            "head_label": head.label,
            "signals": values,
            "weights": dict(sorted(weights.items())),
            "score": score,
            "link_min_score": config["link_min_score"],
            "would_link": score >= config["link_min_score"],
            "constant_share_of_score": constant_share,
            "score_without_the_constant": score - constant_share,
            chain_signals.HYPHEN_SIGNAL: chain_signals.tail_ends_on_hyphen(tail),
            "tail_last_line": tail.last_line_text or "",
            "tail_text": (tail.paragraph.unicode or "")[-220:],
            "head_first_line": first_line_text(head_item),
            "head_text": (head.paragraph.unicode or "")[:220],
        }
    ]


def sample_report(sample, batch, arm, config, stage=SOURCE_STAGE):
    from babeldoc.format.pdf.document_il.xml_converter import XMLConverter

    path = ROOT / "examples" / "output" / batch / sample / arm / "work" / sample
    checkpoint = path / stage
    if not checkpoint.is_file():
        return {"sample": sample, "error": f"no checkpoint at {checkpoint}"}
    document = XMLConverter().from_xml(checkpoint.read_text(encoding="utf-8"))
    rows = []
    for index, page in enumerate(document.page):
        rows.extend(page_column_pairs(page, index, config))
    return {
        "sample": sample,
        "source": str(checkpoint.relative_to(ROOT)).replace("\\", "/"),
        "pairs": len(rows),
        "would_link": sum(1 for r in rows if r.get("would_link")),
        "tail_ends_on_hyphen": sum(
            1 for r in rows if r.get(chain_signals.HYPHEN_SIGNAL)
        ),
        "not_scored": sum(1 for r in rows if "not_scored" in r),
        "rows": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", default="b10_5")
    parser.add_argument("--arm", default="on")
    parser.add_argument("--stage", default=SOURCE_STAGE)
    parser.add_argument(
        "--out",
        default=str(
            ROOT / "examples" / "output" / "b11_2" / "column_continuity.report.json"
        ),
    )
    args = parser.parse_args(argv)

    config = chain_signals.load_chain_config()
    samples = [
        entry["file"].removesuffix(".pdf")
        for entry in corpus.load_manifest()["samples"]
    ]
    report = {
        "batch": args.batch,
        "arm": args.arm,
        "stage": args.stage,
        "link_min_score": config["link_min_score"],
        "constants": {
            "column_position": chain_signals.IN_PAGE_COLUMN_POSITION,
            "opener_prior": chain_signals.IN_PAGE_OPENER_PRIOR,
        },
        "unweighed_signal": chain_signals.HYPHEN_SIGNAL,
        "samples": {},
    }
    for sample in samples:
        result = sample_report(sample, args.batch, args.arm, config, args.stage)
        report["samples"][sample] = result
        if "error" in result:
            print(f"{sample:20s} {result['error']}")
        else:
            print(
                f"{sample:20s} pairs={result['pairs']:4d} "
                f"would_link={result['would_link']:3d} "
                f"hyphen_tails={result['tail_ends_on_hyphen']:3d}"
            )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(
        (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
