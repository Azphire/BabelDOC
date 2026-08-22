"""Measure whether a sentence runs on across a column break inside one page.

The chain detector walks adjacent *pages*: it scores the last endpoint of page N
against the first of page N+1. A magazine sets three columns to a page, and a
noun phrase broken across the second and third column of one page is a handover
of exactly the same kind, which that walk cannot reach by construction.

This tool is the measurement that has to come before any decision about that. It
takes the same column bands the chain detector derives, pairs each column's last
paragraph with the next column's first, computes the signals the page level
walk already has, and scores the pair with the weights and threshold in force.
It writes a report and nothing else: no paragraph is touched, no chain is built,
no file inside a run's working directory is written.

Two of the six signals cannot mean here what they mean across a page break, and
both are handled by saying so rather than by pretending:

``column_position``
    across pages this asks whether the tail sits at the bottom of its page's
    text region and the head at the top of the next. Inside a page the pairing
    is chosen to be exactly that -- the last paragraph of one column and the
    first of the next -- so the answer is one by construction. It is reported as
    a constant and its contribution is reported separately, because a term that
    cannot vary is not evidence.

``opener_prior``
    across pages this is the prior that a page whose kind declares it starts an
    article does start one. A column has no kind and declares nothing, so the
    prior is zero here, which is stated rather than borrowed.

A seventh signal is computed and *not* scored: whether the tail ends on a hyphen,
which in an English source is a word broken across the break. It is recorded
because it is the strongest single piece of evidence available and it is left
out of the score because its weight has never been calibrated; putting an
uncalibrated term into a scored total would make the total say more than the
calibration behind it.

Usage:
    python tools/column_continuity.py [--batch b10_5] [--arm on] [--out PATH]
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

# The stage whose checkpoint this reads. The chain builder consumes the
# intermediate language before the translator rewrites it, so the text scored
# here is the text the detector would have scored.
SOURCE_STAGE = "checkpoint.08_chain_builder.xml"

# The signal this tool records and does not weigh, and the mark it looks for.
HYPHEN_SIGNAL = "tail_ends_on_hyphen"
HYPHENS = ("-", "‐", "­")

# What ``column_position`` is worth inside a page, and why it is a constant.
IN_PAGE_COLUMN_POSITION = 1.0

# A column has no page kind, so no page kind can declare it opens an article.
IN_PAGE_OPENER_PRIOR = 0.0


def endpoint_of(item, page_index, bands, families):
    """One candidate as the chain detector's own endpoint record.

    Built from the same measurements ``chain_signals.page_endpoints`` builds
    from, so the signals below are reading what they read across a page break.
    """
    paragraph, label, lines = item
    style = paragraph.pdf_style
    font_id = style.font_id if style is not None else None
    return chain_signals.Endpoint(
        paragraph=paragraph,
        page_index=page_index,
        label=label,
        column_index=chain_signals._band_index(bands, chain_signals.line_left(lines[0])),
        column_count=len(bands),
        last_line_text=chain_signals.line_text(lines[-1]),
        last_line_width=chain_signals.line_width(lines[-1]),
        width=chain_signals.paragraph_width(lines),
        measure=chain_signals.paragraph_measure(lines),
        font_family=families.get(font_id) if font_id else None,
        font_size=float(style.font_size)
        if style is not None and style.font_size
        else None,
    )


def first_line_text(item):
    return chain_signals.line_text(item[2][0])


def page_column_pairs(page, page_index, config):
    """Every (column n last, column n+1 first) pair of one page, scored."""
    candidates = chain_signals.page_candidates(page, config)
    if len(candidates) < 2:
        return []
    frame = chain_signals._page_frame(page)
    families = chain_signals._font_families(page)
    gap = (frame.x2 - frame.x) * config["column_split_gap_ratio"]
    bands = chain_signals._column_bands(
        [chain_signals.line_left(item[2][0]) for item in candidates], gap
    )
    if len(bands) < 2:
        return []

    columns: dict[int, list] = {}
    for item in candidates:
        index = chain_signals._band_index(bands, chain_signals.line_left(item[2][0]))
        columns.setdefault(index, []).append(item)
    for members in columns.values():
        members.sort(key=lambda item: -item[0].box.y2)

    # Two pairings, reported side by side. ``column_adjacent`` is the one the
    # measurement was specified as: band n's last paragraph against band n+1's
    # first. ``body_next`` skips a band that offers no paragraph the pair rules
    # will take -- a display line set in its own band between two text columns
    # is such a band, and under strict adjacency it hides the handover behind
    # it rather than being one.
    order = sorted(columns)
    rows = []
    for position, index in enumerate(order[:-1]):
        pairings = [("column_adjacent", order[position + 1])]
        for candidate in order[position + 1:]:
            if candidate != order[position + 1]:
                pairings.append(("body_next", candidate))
                break
        for kind, following in pairings:
            rows.extend(_pair_rows(
                kind, page, page_index, bands, families, columns, index, following,
                config))
    return rows


def _pair_rows(kind, page, page_index, bands, families, columns, index, following,
               config):
    """One pairing of two columns, scored, or nothing where no rule takes it."""
    tail_item = columns[index][-1]
    head_item = columns[following][0]
    tail = endpoint_of(tail_item, page_index, bands, families)
    head = endpoint_of(head_item, page_index, bands, families)
    values = {
        "tail_no_terminal_punct": chain_signals.tail_no_terminal_punct(tail, config),
        "tail_line_fill": chain_signals.tail_line_fill(tail, config),
        "style_continuity": chain_signals.style_continuity(tail, head, config),
        "body_label_pair": chain_signals.body_label_pair(tail, head, config),
        "column_position": IN_PAGE_COLUMN_POSITION,
        "opener_prior": IN_PAGE_OPENER_PRIOR,
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
        return [{
            "pairing": kind,
            "page": page.page_number + 1,
            "tail_column": index,
            "head_column": following,
            "column_count": len(bands),
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
        }]
    rule, score, weights = best
    constant_share = weights.get("column_position", 0.0) * IN_PAGE_COLUMN_POSITION
    tail_text = tail.last_line_text or ""
    return [{
        "pairing": kind,
        "page": page.page_number + 1,
        "tail_column": index,
        "head_column": following,
        "column_count": len(bands),
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
        HYPHEN_SIGNAL: bool(tail_text) and tail_text[-1] in HYPHENS,
        "tail_last_line": tail_text,
        "tail_text": (tail.paragraph.unicode or "")[-220:],
        "head_first_line": first_line_text(head_item),
        "head_text": (head.paragraph.unicode or "")[:220],
    }]


def sample_report(sample, batch, arm, config):
    from babeldoc.format.pdf.document_il.xml_converter import XMLConverter

    path = ROOT / "examples" / "output" / batch / sample / arm / "work" / sample
    checkpoint = path / SOURCE_STAGE
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
        "tail_ends_on_hyphen": sum(1 for r in rows if r.get(HYPHEN_SIGNAL)),
        "not_scored": sum(1 for r in rows if "not_scored" in r),
        "rows": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", default="b10_5")
    parser.add_argument("--arm", default="on")
    parser.add_argument(
        "--out",
        default=str(ROOT / "examples" / "output" / "b11_2" / "column_continuity.report.json"),
    )
    args = parser.parse_args(argv)

    config = chain_signals.load_chain_config()
    samples = [entry["file"].removesuffix(".pdf")
               for entry in corpus.load_manifest()["samples"]]
    report = {
        "batch": args.batch,
        "arm": args.arm,
        "stage": SOURCE_STAGE,
        "link_min_score": config["link_min_score"],
        "constants": {
            "column_position": IN_PAGE_COLUMN_POSITION,
            "opener_prior": IN_PAGE_OPENER_PRIOR,
        },
        "unweighed_signal": HYPHEN_SIGNAL,
        "samples": {},
    }
    for sample in samples:
        result = sample_report(sample, args.batch, args.arm, config)
        report["samples"][sample] = result
        if "error" in result:
            print(f"{sample:20s} {result['error']}")
        else:
            print(f"{sample:20s} pairs={result['pairs']:4d} "
                  f"would_link={result['would_link']:3d} "
                  f"hyphen_tails={result['tail_ends_on_hyphen']:3d}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
