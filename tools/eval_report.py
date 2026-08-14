"""Every metric a produced run can answer for, over one sample, in one report.

The four metric modules under ``babeldoc/magazine/metrics/`` each take the
artefacts they need and return a mapping. This tool is what knows where those
artefacts live in a working directory, which of them a given run happens to have
left, and how to lay the answers out so two configurations of one sample can be
read side by side.

It computes what it can and says what it could not. A run without a chain
sidecar has no chain level of the conservation invariant, a run whose source and
produced checkpoints are not both present has no layout geometry, and in both
cases the report carries the reason under ``absent`` rather than a zero. A
number missing for a stated reason is evidence; a zero standing in for one is
not.

Nothing here makes a model request or reads a credential. Every metric is
deterministic, so running this twice over one working directory produces the
same bytes, which is what makes a frozen artefact re-measurable years later.

Usage:

    python tools/eval_report.py \\
        --run chain_on=examples/output/b8/smoke/Courier-en/work/Courier-en \\
        --run chain_off=examples/output/b5_smoke/Courier-en.chain_off/work/Courier-en \\
        --sample Courier-en.pdf \\
        --out examples/output/e1

A working directory is one produced with ``magazine_checkpoint`` up. The source
side of the geometry comparison is the checkpoint before translation and the
produced side the one after typesetting, so the two sides are the same document
measured before and after this project touched it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.metrics import conservation  # noqa: E402
from babeldoc.magazine.metrics import layout_geometry  # noqa: E402
from babeldoc.magazine.metrics import load_metrics_config  # noqa: E402
from babeldoc.magazine.metrics import ltcr  # noqa: E402
from babeldoc.magazine.metrics import mid_break_rate  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402

logger = logging.getLogger(__name__)

# Which checkpoint answers which question. The source side of every before/after
# comparison is the last checkpoint written before translation: it is the
# document as the parser finished with it, so its paragraphs and their boxes are
# the layout of the original page. An earlier checkpoint would be no use here --
# before the paragraph finder there are characters and no paragraphs, and a
# geometry measured over an empty element set is not a measurement of anything.
# The produced side is the typeset checkpoint, which is also the only place the
# rendered lines the mid-unit rate reads exist.
SOURCE_STAGE = "chain_builder"
TRANSLATED_STAGE = "il_translated"
TYPESET_STAGE = "typesetting"

# The sidecars the conservation invariant reads, by the names
# configs/checkpoint_stages.json declares for them.
CHAIN_SIDECAR = "chain_translation.report.json"
REPAIR_SIDECAR = "react_repair.report.json"

# The corpus adjudication of which page boundaries cut a semantic unit. Read for
# annotation only: no metric's verdict depends on it.
CHAIN_LABELS = ROOT / "corpus" / "chain_labels.user.json"


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _checkpoint(working_dir: Path, stage: str):
    path = working_dir / f"{checkpoint_stem(stage)}.xml"
    if not path.is_file():
        return None
    with warnings.catch_warnings():
        # Reading a checkpoint written by an earlier batch may warn about a
        # converter default; an error is still an error and still raises.
        warnings.simplefilter("ignore")
        return load_checkpoint(path)


def _truth_for(sample: str | None) -> dict[str, bool] | None:
    """The adjudicated boundaries of one sample, keyed as the ground truth keys them."""
    if sample is None:
        return None
    labels = _read_json(CHAIN_LABELS)
    if not labels:
        return None
    entry = labels.get(sample)
    if not isinstance(entry, dict):
        return None
    return {
        key: bool(value.get("link"))
        for key, value in entry.items()
        if isinstance(value, dict)
    }


def _regions_for_ltcr(source, translated) -> list[tuple[str, dict, dict]]:
    """One region per article, so a term recurring is a term recurring in an article.

    The grouping is the article builder's, which is the same grouping the brief
    pass translated under. Measuring over a whole magazine instead would count a
    name shared by two unrelated articles as one term with two renderings.
    """
    body_labels = tuple(load_chain_config()["body_labels"])
    titles = article_builder.title_labels(article_builder.load_grouping_config())
    grouping = article_builder.build_articles(source, load_taxonomy().policy_of, titles)
    target_text = {
        paragraph.debug_id: ltcr.strip_markup(paragraph.unicode or "")
        for page in translated.page
        for paragraph in page.pdf_paragraph
        if paragraph.debug_id is not None
    }
    regions = []
    for position, article in enumerate(grouping.articles, start=1):
        sources = {
            paragraph.debug_id: paragraph.unicode or ""
            for index in article.pages
            for paragraph in source.page[index].pdf_paragraph
            if paragraph.debug_id is not None
            and paragraph.layout_label in body_labels
            and (paragraph.unicode or "").strip()
        }
        targets = {
            debug_id: target_text.get(debug_id, "") for debug_id in sources
        }
        regions.append((f"A{position}", sources, targets))
    return regions


def measure_run(label: str, working_dir: Path, sample: str | None) -> dict:
    """Every metric this working directory carries the artefacts for."""
    config = load_metrics_config()
    chain_config = load_chain_config()
    absent: list[str] = []

    source = _checkpoint(working_dir, SOURCE_STAGE)
    translated = _checkpoint(working_dir, TRANSLATED_STAGE)
    typeset = _checkpoint(working_dir, TYPESET_STAGE)
    chain_report = _read_json(working_dir / CHAIN_SIDECAR)
    repair_report = _read_json(working_dir / REPAIR_SIDECAR)

    report: dict = {"label": label, "working_dir": str(working_dir), "sample": sample}

    if typeset is None:
        absent.append(f"{TYPESET_STAGE} checkpoint: no mid-unit page-break rate")
    else:
        report["mid_break_rate"] = mid_break_rate.measure(
            typeset, chain_config, _truth_for(sample), config
        )

    report["conservation"] = conservation.measure(
        chain_report=chain_report,
        repair_report=repair_report,
        source_pages=None if source is None else len(source.page),
        produced_pages=None if typeset is None else len(typeset.page),
    )
    if chain_report is None:
        absent.append(f"{CHAIN_SIDECAR}: no chain level of the conservation invariant")
    if repair_report is None:
        absent.append(f"{REPAIR_SIDECAR}: no repair level of the conservation invariant")

    if source is None or translated is None:
        absent.append(f"{SOURCE_STAGE} or {TRANSLATED_STAGE} checkpoint: no LTCR")
    else:
        report["ltcr"] = ltcr.measure(
            _regions_for_ltcr(source, translated),
            tuple(chain_config["terminal_punctuation"]),
            metrics=config,
        )

    if source is None or typeset is None:
        absent.append(
            f"{SOURCE_STAGE} or {TYPESET_STAGE} checkpoint: no layout geometry"
        )
    else:
        report["layout_geometry"] = layout_geometry.measure(
            list(source.page), list(typeset.page), config
        )

    report["absent"] = absent
    return report


def _cell(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def markdown(report: dict) -> str:
    """One row per run, one column per headline number."""
    runs = report["runs"]
    lines = ["# Evaluation metrics", "", f"Sample: `{report['sample']}`", ""]
    header = (
        "| run | MBR | MBR strict | conserved | LTCR | legacy share | "
        "Overlap delta | Alignment delta | image IoU | page delta |"
    )
    lines.append(header)
    lines.append("| --- " * 10 + "|")
    for run in runs:
        breaks = run.get("mid_break_rate") or {}
        terms = (run.get("ltcr") or {}).get("summary") or {}
        geometry = (run.get("layout_geometry") or {}).get("summary") or {}
        pages = (run.get("layout_geometry") or {}).get("page_count_delta") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    run["label"],
                    _cell(breaks.get("rate")),
                    _cell(breaks.get("strict_rate")),
                    _cell(run["conservation"]["holds"]),
                    _cell(terms.get("ltcr")),
                    _cell(terms.get("legacy_mean_share")),
                    _cell(geometry.get("overlap_delta")),
                    _cell(geometry.get("alignment_delta")),
                    _cell(geometry.get("image_placement_iou")),
                    _cell(pages.get("value")),
                ]
            )
            + " |"
        )
    lines.append("")
    for run in runs:
        if run["absent"]:
            lines.append(f"- `{run['label']}` could not measure:")
            lines.extend(f"  - {reason}" for reason in run["absent"])
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=WORKING_DIR",
        help="a produced working directory to measure, named by its configuration",
    )
    parser.add_argument(
        "--sample",
        default=None,
        help="the corpus filename, which is how the ground truth is keyed",
    )
    parser.add_argument("--out", default=None, help="directory to write the report to")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    runs = []
    for spec in args.run:
        if "=" not in spec:
            raise SystemExit(f"--run wants LABEL=WORKING_DIR, got {spec!r}")
        label, path = spec.split("=", 1)
        runs.append(measure_run(label, Path(path), args.sample))

    report = {
        "sample": args.sample or runs[0]["working_dir"],
        "runs": runs,
    }
    text = markdown(report)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        stem = f"eval_report.{Path(report['sample']).stem}"
        (out / f"{stem}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out / f"{stem}.md").write_text(text, encoding="utf-8")
        print(f"wrote {out / (stem + '.json')}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
