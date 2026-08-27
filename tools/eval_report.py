"""Every metric a produced run can answer for, over one sample, in one report.

The five metric modules under ``babeldoc/magazine/metrics/`` each take the
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

Two paths to the same metrics
-----------------------------

A run of this fork leaves checkpoints, so its geometry is read from the
intermediate language: the paragraphs and boxes the pipeline itself worked with.
The upstream baseline leaves a PDF and nothing else, so its geometry is read
back out of the file by ``metrics/pdf_geometry.py``. The two are not the same
measurement and this tool never pretends they are: a fork run is measured down
**both** paths, and the corpus sweep reports how far apart the two answers are
on the one artefact both can read. That deviation is what says whether
an upstream column may be read beside a fork column at all, and it is recorded
in ``docs/eval/metric_contract.md``.

Usage:

    python tools/eval_report.py \\
        --run chain_on=examples/output/b8_4/smoke/Courier-en/work/Courier-en \\
        --sample Courier-en.pdf \\
        --out examples/output/e1

    python tools/eval_report.py --corpus --out docs/eval/results_e1

The first form measures named working directories. The second walks
``corpus/manifest.json`` and measures every sample in every frozen
configuration this repository holds, which is what fills the results directory.

A working directory is one produced with ``magazine_checkpoint`` up. The source
side of the geometry comparison is the checkpoint before translation and the
produced side the one after typesetting, so the two sides are the same document
measured before and after this project touched it. On the PDF path the source
side is the input PDF and the produced side the translated one, so both sides
are read by the same extractor and the extraction cancels out of the delta.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.metrics import conservation  # noqa: E402
from babeldoc.magazine.metrics import layout_geometry  # noqa: E402
from babeldoc.magazine.metrics import load_metrics_config  # noqa: E402
from babeldoc.magazine.metrics import ltcr  # noqa: E402
from babeldoc.magazine.metrics import mid_break_rate  # noqa: E402
from babeldoc.magazine.metrics import pdf_geometry  # noqa: E402
from babeldoc.magazine.metrics import rounded  # noqa: E402
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

# The corpus adjudication of which page boundaries cut a semantic unit, and
# which of the rest are traps the excerpt itself cut. Read for stratification
# only: no metric's verdict depends on it.
CHAIN_LABELS = ROOT / "corpus" / "chain_labels.user.json"

# Where the frozen artefacts of this corpus sit, by configuration. The upstream
# side is a translation by unmodified upstream BabelDOC and carries no working
# directory at all; the fork side is the last full-stack run of every sample.
# Named here rather than discovered, because a report that measured whatever
# happened to be lying in the output tree would change meaning between sweeps.
INPUT_DIR = ROOT / "examples" / "input"
UPSTREAM_PDF_DIR = ROOT / "examples" / "baseline" / "pdf"
FORK_RUN_DIR = ROOT / "examples" / "output" / "b8_4" / "smoke"
MONO_PDF_GLOB = "*.mono.pdf"

# The configuration labels the corpus sweep produces, in the order a table
# reads them. The two fork labels are one run measured down the two paths.
UPSTREAM = "upstream"
FORK_IL = "fork_full_il"
FORK_PDF = "fork_full_pdf"


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def digest_of(path: Path) -> str:
    """The artefact a number came from, named so a later reader can check it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def named(path: Path) -> str:
    """An artefact path as a report should carry it: relative, forward slashes.

    A report is read on another machine years later, and an absolute path from
    the machine that produced it is neither checkable there nor meaningful.
    """
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _checkpoint(working_dir: Path, stage: str):
    path = working_dir / f"{checkpoint_stem(stage)}.xml"
    if not path.is_file():
        return None
    with warnings.catch_warnings():
        # Reading a checkpoint written by an earlier batch may warn about a
        # converter default; an error is still an error and still raises.
        warnings.simplefilter("ignore")
        return load_checkpoint(path)


def _truth_for(sample: str | None, config) -> dict | None:
    """The adjudicated boundaries of one sample, keyed as the ground truth keys them."""
    if sample is None:
        return None
    labels = _read_json(CHAIN_LABELS)
    if not labels:
        return None
    entry = labels.get(sample)
    if not isinstance(entry, dict):
        return None
    return mid_break_rate.adjudications_of(entry, config.truth_trap_markers)


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

    report: dict = {
        "label": label,
        "path": "intermediate_language",
        "working_dir": named(working_dir),
        "sample": sample,
    }

    if typeset is None:
        absent.append(f"{TYPESET_STAGE} checkpoint: no mid-unit page-break rate")
    else:
        report["mid_break_rate"] = mid_break_rate.measure(
            typeset, chain_config, _truth_for(sample, config), config
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
        absent.append(
            f"{SOURCE_STAGE} or {TRANSLATED_STAGE} checkpoint: "
            "no substring consistency proxy"
        )
    else:
        report["substring_consistency_proxy"] = ltcr.measure(
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


def measure_pdf(
    label: str, source_pdf: Path, produced_pdf: Path, sample: str | None
) -> dict:
    """The metrics a pair of PDFs can answer for, with no checkpoint anywhere.

    Both sides are read by the same extractor, so the delta metrics are a
    statement about the two documents rather than about the two readers. What
    cannot be had this way is stated: neither term consistency nor the chain and
    repair levels of the conservation invariant survive in a PDF, and reporting
    them as zero would be inventing them.
    """
    config = load_metrics_config()
    chain_config = load_chain_config()

    source = pdf_geometry.document_from_pdf(source_pdf, config)
    produced = pdf_geometry.document_from_pdf(produced_pdf, config)

    report: dict = {
        "label": label,
        "path": "pdf_extraction",
        "source_pdf": named(source_pdf),
        "source_pdf_sha256": digest_of(source_pdf),
        "produced_pdf": named(produced_pdf),
        "produced_pdf_sha256": digest_of(produced_pdf),
        "sample": sample,
        "mid_break_rate": mid_break_rate.measure(
            produced, chain_config, _truth_for(sample, config), config
        ),
        "conservation": conservation.measure(
            source_pages=len(source.page), produced_pages=len(produced.page)
        ),
        "layout_geometry": layout_geometry.measure(
            list(source.page), list(produced.page), config
        ),
        "absent": [
            "no working directory: no chain or repair level of the conservation "
            "invariant",
            "no source and translated checkpoint pair: no substring consistency proxy",
        ],
    }
    return report


def _relative_delta(left, right) -> float | None:
    """How far apart two readings of one quantity are, against the larger of them.

    Absolute difference alone would call a large metric incomparable and a small
    one agreed for the same proportional gap, and a ratio alone divides by zero
    the moment a page has none of whatever is being counted.
    """
    if left is None or right is None:
        return None
    scale = max(abs(float(left)), abs(float(right)))
    if scale == 0.0:
        return 0.0
    return abs(float(left) - float(right)) / scale


def compare_paths(il_report: dict, pdf_report: dict) -> dict:
    """How far the two geometry paths land apart on one produced artefact.

    Reported per metric, with the element counts that drive most of it, and with
    a verdict per metric rather than one for the pair: the paths can agree about
    where the images went and disagree about how the text was blocked, and a
    single verdict would lose whichever half is the useful one.
    """
    config = load_metrics_config()
    digits = config.report_float_digits
    bound = config.method_comparable_max_relative_delta

    il_geometry = (il_report.get("layout_geometry") or {}).get("summary") or {}
    pdf_geometry_summary = (pdf_report.get("layout_geometry") or {}).get("summary") or {}
    metrics: dict[str, dict] = {}
    for key in sorted(set(il_geometry) | set(pdf_geometry_summary)):
        left = il_geometry.get(key)
        right = pdf_geometry_summary.get(key)
        delta = _relative_delta(left, right)
        metrics[key] = {
            "intermediate_language": left,
            "pdf_extraction": right,
            "relative_delta": rounded(delta, digits),
            "comparable": None if delta is None else delta <= bound,
        }

    il_breaks = il_report.get("mid_break_rate") or {}
    pdf_breaks = pdf_report.get("mid_break_rate") or {}
    il_boundaries = {
        item["label"]: item["verdict"]
        for item in (il_breaks.get("series") or {})
        .get(mid_break_rate.PAGE_SERIES, {})
        .get("boundaries", [])
    }
    pdf_boundaries = {
        item["label"]: item["verdict"]
        for item in (pdf_breaks.get("series") or {})
        .get(mid_break_rate.PAGE_SERIES, {})
        .get("boundaries", [])
    }
    shared = sorted(set(il_boundaries) & set(pdf_boundaries))
    agreeing = [
        label for label in shared if il_boundaries[label] == pdf_boundaries[label]
    ]
    agreement = len(agreeing) / len(shared) if shared else None
    # The one metric whose verdict is not taken from its own deviation. A rate
    # over seven boundaries moves by a seventh whenever a single tail is read
    # differently, so the rate's deviation says more about the denominator than
    # about the two methods; what the two paths either do or do not agree about
    # is the verdict at each boundary, and that is what decides this row.
    metrics["mid_break_rate.rate"] = {
        "intermediate_language": il_breaks.get("rate"),
        "pdf_extraction": pdf_breaks.get("rate"),
        "relative_delta": rounded(
            _relative_delta(il_breaks.get("rate"), pdf_breaks.get("rate")), digits
        ),
        "comparable": None if agreement is None else agreement >= 1.0 - bound,
        "comparable_basis": "boundary verdict agreement",
    }

    # Element counts, which is where most of the disagreement above comes from:
    # a viewer's text block and a paragraph finder's paragraph are different
    # partitions of the same ink, and both Overlap and Alignment normalise by N.
    def _elements(report: dict, side: str) -> int:
        pages = (report.get("layout_geometry") or {}).get("pages") or []
        return sum(page[side]["elements"] for page in pages)

    return {
        "sample": il_report.get("sample"),
        "bound": bound,
        "metrics": metrics,
        "boundary_verdicts": {
            "shared": len(shared),
            "agreeing": len(agreeing),
            "agreement": rounded(agreement, digits),
            "disagreeing": [
                {
                    "label": label,
                    "intermediate_language": il_boundaries[label],
                    "pdf_extraction": pdf_boundaries[label],
                }
                for label in shared
                if il_boundaries[label] != pdf_boundaries[label]
            ],
        },
        "elements": {
            "intermediate_language_source": _elements(il_report, "source"),
            "intermediate_language_produced": _elements(il_report, "produced"),
            "pdf_extraction_source": _elements(pdf_report, "source"),
            "pdf_extraction_produced": _elements(pdf_report, "produced"),
        },
    }


def _cell(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _stratified(run: dict) -> dict:
    return ((run.get("mid_break_rate") or {}).get("stratified")) or {}


def markdown(report: dict) -> str:
    """One row per run, one column per headline number."""
    runs = report["runs"]
    lines = ["# Evaluation metrics", "", f"Sample: `{report['sample']}`", ""]
    lines.append(
        "| run | path | MBR linkable | MBR all | inherited open | conserved | "
        "substring consistency proxy | legacy share | Overlap delta | Alignment delta | image IoU | "
        "page delta |"
    )
    lines.append("| --- " * 12 + "|")
    for run in runs:
        breaks = _stratified(run)
        terms = (run.get("substring_consistency_proxy") or {}).get("summary") or {}
        geometry = (run.get("layout_geometry") or {}).get("summary") or {}
        pages = (run.get("layout_geometry") or {}).get("page_count_delta") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    run["label"],
                    run["path"],
                    _cell(breaks.get("mbr_linkable")),
                    _cell(breaks.get("mbr_all")),
                    _cell(breaks.get("source_inherited_open")),
                    _cell(run["conservation"]["holds"]),
                    _cell(terms.get("substring_consistency_proxy")),
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


def _boundary_rows(run: dict) -> dict[str, dict]:
    series = (
        (run.get("mid_break_rate") or {}).get("series") or {}
    ).get(mid_break_rate.PAGE_SERIES) or {}
    return {item["label"]: item for item in series.get("boundaries", [])}


def corpus_markdown(report: dict) -> str:
    """The whole corpus, every sample in every configuration, as one document."""
    lines = [
        "# batch-e1.2 evaluation results",
        "",
        "Computed by `tools/eval_report.py --corpus` over frozen artefacts. No "
        "translation was run and no model request was made.",
        "",
        "## 1. Headline table",
        "",
        "| sample | run | path | MBR linkable | MBR all | inherited open | "
        "conserved | substring consistency proxy | Overlap delta | Alignment delta | image IoU | "
        "page delta |",
        "| --- " * 12 + "|",
    ]
    for sample in report["samples"]:
        for run in sample["runs"]:
            breaks = _stratified(run)
            terms = (run.get("substring_consistency_proxy") or {}).get("summary") or {}
            geometry = (run.get("layout_geometry") or {}).get("summary") or {}
            pages = (run.get("layout_geometry") or {}).get("page_count_delta") or {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        sample["sample"],
                        run["label"],
                        run["path"],
                        _cell(breaks.get("mbr_linkable")),
                        _cell(breaks.get("mbr_all")),
                        _cell(breaks.get("source_inherited_open")),
                        _cell(run["conservation"]["holds"]),
                        _cell(terms.get("substring_consistency_proxy")),
                        _cell(geometry.get("overlap_delta")),
                        _cell(geometry.get("alignment_delta")),
                        _cell(geometry.get("image_placement_iou")),
                        _cell(pages.get("value")),
                    ]
                )
                + " |"
            )

    lines += [
        "",
        "## 2. Mid-unit page-break rate, stratum by stratum",
        "",
        "`linked` is a boundary the corpus adjudicated as cutting a semantic "
        "unit, `trap` one whose continuation is outside the excerpt and which "
        "therefore no producer can close, `clean` the rest.",
        "",
        "| sample | run | linked open/answerable | trap open/answerable | "
        "clean open/answerable | axis unsupported | vertical paragraphs | "
        "no tail |",
        "| --- " * 8 + "|",
    ]
    def stratum_cell(strata: dict, name: str) -> str:
        row = strata.get(name) or {}
        return f"{row.get('open_count', 0)}/{row.get('answerable', 0)}"

    for sample in report["samples"]:
        for run in sample["runs"]:
            breaks = _stratified(run)
            strata = breaks.get("strata") or {}
            series = (
                (run.get("mid_break_rate") or {}).get("series") or {}
            ).get(mid_break_rate.PAGE_SERIES) or {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        sample["sample"],
                        run["label"],
                        stratum_cell(strata, mid_break_rate.LINKED),
                        stratum_cell(strata, mid_break_rate.TRAP),
                        stratum_cell(strata, mid_break_rate.CLEAN),
                        str(series.get("axis_unsupported_count", 0)),
                        str((run.get("mid_break_rate") or {}).get(
                            "vertical_paragraphs", 0
                        )),
                        str(series.get("no_tail_count", 0)),
                    ]
                )
                + " |"
            )

    lines += [
        "",
        "## 3. Every adjudicated boundary, verdict by verdict",
        "",
        "| sample | boundary | truth | " + " | ".join(report["labels"]) + " |",
        "| --- " * (3 + len(report["labels"])) + "|",
    ]
    for sample in report["samples"]:
        rows = {run["label"]: _boundary_rows(run) for run in sample["runs"]}
        labels = sorted(
            {label for table in rows.values() for label in table},
            key=lambda item: [int(part) for part in item.split("->")],
        )
        for label in labels:
            any_row = next(
                (table[label] for table in rows.values() if label in table), None
            )
            if any_row is None:
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        sample["sample"],
                        label,
                        str(any_row.get("truth_category")),
                        *[
                            (rows.get(name, {}).get(label) or {}).get("verdict", "-")
                            for name in report["labels"]
                        ],
                    ]
                )
                + " |"
            )

    lines += [
        "",
        "## 4. Geometry method difference, on the fork product",
        "",
        "The same produced PDF measured down both paths. `comparable` is the "
        "relative deviation against the declared bound; a metric that fails it "
        "may not be read across the two paths.",
        "",
        "| sample | metric | IL path | PDF path | relative delta | comparable |",
        "| --- " * 6 + "|",
    ]
    for sample in report["samples"]:
        comparison = sample.get("method_comparison")
        if not comparison:
            continue
        for name, row in comparison["metrics"].items():
            lines.append(
                "| "
                + " | ".join(
                    [
                        sample["sample"],
                        name,
                        _cell(row["intermediate_language"]),
                        _cell(row["pdf_extraction"]),
                        _cell(row["relative_delta"]),
                        _cell(row["comparable"]),
                    ]
                )
                + " |"
            )
    lines.append("")
    lines.append("| sample | boundary verdict agreement | IL elements | PDF elements |")
    lines.append("| --- " * 4 + "|")
    for sample in report["samples"]:
        comparison = sample.get("method_comparison")
        if not comparison:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    sample["sample"],
                    f"{comparison['boundary_verdicts']['agreeing']}"
                    f"/{comparison['boundary_verdicts']['shared']}",
                    str(comparison["elements"]["intermediate_language_produced"]),
                    str(comparison["elements"]["pdf_extraction_produced"]),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _one_pdf(directory: Path) -> Path | None:
    matches = sorted(directory.glob(MONO_PDF_GLOB)) if directory.is_dir() else []
    return matches[0] if matches else None


def corpus_runs(sample: dict) -> tuple[list[dict], list[str]]:
    """Every frozen configuration of one sample, and what was not there."""
    file_name = sample["file"]
    stem = Path(file_name).stem
    runs: list[dict] = []
    missing: list[str] = []

    source_pdf = INPUT_DIR / file_name
    upstream_pdf = _one_pdf(UPSTREAM_PDF_DIR / stem)
    fork_dir = FORK_RUN_DIR / stem
    fork_pdf = _one_pdf(fork_dir / "out")
    fork_working = fork_dir / "work" / stem

    if not source_pdf.is_file():
        missing.append(f"{UPSTREAM}: {source_pdf} is absent")
    elif upstream_pdf is None:
        missing.append(f"{UPSTREAM}: no baseline PDF under {UPSTREAM_PDF_DIR / stem}")
    else:
        runs.append(measure_pdf(UPSTREAM, source_pdf, upstream_pdf, file_name))

    if not (fork_working / f"{checkpoint_stem(TYPESET_STAGE)}.xml").is_file():
        missing.append(f"{FORK_IL}: no typeset checkpoint under {fork_working}")
    else:
        runs.append(measure_run(FORK_IL, fork_working, file_name))

    if fork_pdf is None or not source_pdf.is_file():
        missing.append(f"{FORK_PDF}: no produced PDF under {fork_dir / 'out'}")
    else:
        runs.append(measure_pdf(FORK_PDF, source_pdf, fork_pdf, file_name))

    return runs, missing


def measure_corpus() -> dict:
    """Every sample of the registered corpus in every configuration held here."""
    manifest = corpus_module.load_manifest()
    samples = []
    for entry in manifest["samples"]:
        runs, missing = corpus_runs(entry)
        by_label = {run["label"]: run for run in runs}
        comparison = None
        if FORK_IL in by_label and FORK_PDF in by_label:
            comparison = compare_paths(by_label[FORK_IL], by_label[FORK_PDF])
        samples.append(
            {
                "sample": entry["file"],
                "publication": entry.get("publication", ""),
                "pages": entry.get("pages"),
                "runs": runs,
                "missing": missing,
                "method_comparison": comparison,
            }
        )
    return {
        "generated_by": "tools/eval_report.py --corpus",
        "labels": [UPSTREAM, FORK_IL, FORK_PDF],
        "samples": samples,
    }


def _run_summary(run: dict) -> dict:
    """One run reduced to its headline numbers and the artefacts behind them.

    The per sample files hold every boundary, page and element; repeating all of
    that in the corpus file would make the one document meant to be read a
    megabyte of duplicate. What stays is what a table needs, plus the digest of
    each artefact measured, so a reader can tell which copy of an untracked PDF
    a number came from.
    """
    breaks = run.get("mid_break_rate") or {}
    series = (breaks.get("series") or {}).get(mid_break_rate.PAGE_SERIES) or {}
    summary = {
        "label": run["label"],
        "path": run["path"],
        "absent": run["absent"],
        "conservation": run["conservation"],
        "mid_break_rate": {
            key: value
            for key, value in breaks.items()
            if key not in ("series", "stratified")
        },
        "stratified": breaks.get("stratified"),
        "page_series": {
            key: value for key, value in series.items() if key != "boundaries"
        },
        "boundaries": [
            {
                "label": item["label"],
                "verdict": item["verdict"],
                "truth_category": item["truth_category"],
                "layout_label": (item["tail"] or {}).get("layout_label"),
                "last_character": (item["tail"] or {}).get("last_character"),
            }
            for item in series.get("boundaries", [])
        ],
        "substring_consistency_proxy": (
            run.get("substring_consistency_proxy") or {}
        ).get("summary"),
        "layout_geometry": (run.get("layout_geometry") or {}).get("summary"),
        "page_count_delta": (run.get("layout_geometry") or {}).get("page_count_delta"),
    }
    for key in (
        "working_dir",
        "source_pdf",
        "source_pdf_sha256",
        "produced_pdf",
        "produced_pdf_sha256",
    ):
        if key in run:
            summary[key] = run[key]
    return summary


def corpus_summary(report: dict) -> dict:
    """The corpus report as it is written to disk: headlines, not every box."""
    return {
        "generated_by": report["generated_by"],
        "labels": report["labels"],
        "detail": "eval_report.<sample>.json beside this file",
        "samples": [
            {
                "sample": sample["sample"],
                "publication": sample["publication"],
                "pages": sample["pages"],
                "missing": sample["missing"],
                "method_comparison": sample["method_comparison"],
                "runs": [_run_summary(run) for run in sample["runs"]],
            }
            for sample in report["samples"]
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="append",
        default=None,
        metavar="LABEL=WORKING_DIR",
        help="a produced working directory to measure, named by its configuration",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        default=None,
        metavar="LABEL=SOURCE_PDF:PRODUCED_PDF",
        help="a pair of PDFs to measure down the extraction path",
    )
    parser.add_argument(
        "--corpus",
        action="store_true",
        help="measure every registered sample in every frozen configuration",
    )
    parser.add_argument(
        "--sample",
        default=None,
        help="the corpus filename, which is how the ground truth is keyed",
    )
    parser.add_argument("--out", default=None, help="directory to write the report to")
    return parser


def _write(out: Path, stem: str, report: dict, text: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    (out / f"{stem}.md").write_text(text, encoding="utf-8")
    print(f"wrote {out / (stem + '.json')}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    if args.corpus:
        report = measure_corpus()
        text = corpus_markdown(report)
        out = Path(args.out) if args.out else ROOT / "docs" / "eval" / "results_e1"
        for sample in report["samples"]:
            stem = Path(sample["sample"]).stem
            _write(
                out,
                f"eval_report.{stem}",
                {"sample": sample["sample"], "runs": sample["runs"]},
                markdown({"sample": sample["sample"], "runs": sample["runs"]}),
            )
        _write(out, "eval_corpus", corpus_summary(report), text)
        print(text)
        return 0

    if not args.run and not args.pdf:
        raise SystemExit("nothing to measure: pass --run, --pdf or --corpus")

    runs = []
    for spec in args.run or ():
        if "=" not in spec:
            raise SystemExit(f"--run wants LABEL=WORKING_DIR, got {spec!r}")
        label, path = spec.split("=", 1)
        runs.append(measure_run(label, Path(path), args.sample))
    for spec in args.pdf or ():
        if "=" not in spec or ":" not in spec.split("=", 1)[1]:
            raise SystemExit(
                f"--pdf wants LABEL=SOURCE_PDF:PRODUCED_PDF, got {spec!r}"
            )
        label, pair = spec.split("=", 1)
        source, produced = pair.rsplit(":", 1)
        runs.append(measure_pdf(label, Path(source), Path(produced), args.sample))

    report = {
        "sample": args.sample or runs[0].get("working_dir") or runs[0]["produced_pdf"],
        "runs": runs,
    }
    text = markdown(report)
    if args.out:
        _write(
            Path(args.out),
            f"eval_report.{Path(report['sample']).stem}",
            report,
            text,
        )
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
