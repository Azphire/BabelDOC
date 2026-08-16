"""Human review page for article chain detection.

Usage:
    python tools/chain_report.py examples/input/sample.pdf
    python tools/chain_report.py sample.pdf --checkpoint work/checkpoint.07_page_classifier.xml

Writes a single self-contained HTML file to ``examples/output/b4/`` holding one
row per adjacent page boundary: the two page thumbnails, the page kinds and what
their policy says, every endpoint pairing that was scored with its signal
vector, the winning score against the link threshold, and the text at each end.
Where ``corpus/chain_labels.user.json`` adjudicates the boundary, the
adjudication and the note behind it are shown beside the verdict and a
disagreement is called out.

This is the interface for two jobs. It is the sheet a corpus owner adjudicates
boundaries from, since it puts the tail and head text side by side without
opening the PDF. It is also the tuning interface for
``configs/chain_detection.json``: edit the weights or thresholds, rerun this
tool, compare. No code change is involved in a retune, and this tool never
writes the ground truth it reads.

Without ``--checkpoint`` the tool runs the pipeline itself with translation
skipped, so it needs no API key.

Exit codes: 0 report written, 1 the input could not be processed.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine.chain_signals import PAIR_RULES_KEY  # noqa: E402
from babeldoc.magazine.chain_signals import SIGNAL_NAMES  # noqa: E402
from babeldoc.magazine.chain_signals import BoundaryVerdict  # noqa: E402
from babeldoc.magazine.chain_signals import evaluate_boundary  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.page_features import validate_bounded_config  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402

CONFIG_PATH = ROOT / "configs" / "chain_report.json"
DEFAULT_OUT_DIR = ROOT / "examples" / "output" / "b4"

_STYLE = """
body { font: 13px/1.5 sans-serif; margin: 24px; color: #1a1a1a; }
h1 { font-size: 20px; }
.meta { color: #555; margin-bottom: 20px; }
.boundary { border-top: 1px solid #ddd; padding: 16px 0; display: flex; gap: 18px; }
.thumbs { display: flex; gap: 6px; }
.thumbs img { border: 1px solid #bbb; display: block; }
.detail { flex: 1; min-width: 0; }
.verdict { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
.linked { background: #cfe8cf; padding: 1px 6px; border-radius: 3px; }
.unlinked { background: #eee; padding: 1px 6px; border-radius: 3px; }
.masked { background: #f0e0d0; padding: 1px 6px; border-radius: 3px; }
.truth { padding: 1px 6px; border-radius: 3px; background: #dde6f5; }
.disagree { background: #f5c6c6; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
.note { color: #555; margin: 4px 0 8px 0; }
table { border-collapse: collapse; margin: 6px 24px 6px 0; }
td, th { padding: 1px 10px 1px 0; text-align: left; vertical-align: top; }
th { color: #555; font-weight: 500; }
.win td { font-weight: 600; }
.text { margin-top: 6px; }
.text div { margin: 2px 0; }
.tag { color: #777; }
.frag { font-family: ui-monospace, monospace; white-space: pre-wrap; }
"""


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return validate_bounded_config(raw, path)


def run_pipeline(pdf: Path) -> Path:
    """Dry run the pipeline with chain detection on and return its checkpoint."""
    from babeldoc.assets.assets import warmup
    from babeldoc.docvision.doclayout import DocLayoutModel
    from babeldoc.format.pdf import high_level
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.format.pdf.translation_config import WatermarkOutputMode
    from babeldoc.magazine.cache_setup import use_project_cache
    from babeldoc.magazine.checkpoint import checkpoint_stem

    use_project_cache(ROOT)
    warmup()
    work_root = Path(tempfile.mkdtemp(prefix="chain_report_"))
    source_lang, target_lang = corpus.direction_of(pdf.stem)
    config = TranslationConfig(
        translator=None,
        input_file=pdf,
        lang_in=source_lang,
        lang_out=target_lang,
        doc_layout_model=DocLayoutModel.load_onnx(),
        output_dir=work_root / "out",
        working_dir=work_root / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=False,
        skip_translation=True,
        magazine_checkpoint=True,
        magazine_page_classify=True,
        magazine_chain_detect=True,
    )
    high_level.translate(config)
    return Path(config.working_dir) / f"{checkpoint_stem('chain_builder')}.xml"


def thumbnail_uri(doc: pymupdf.Document, index: int, dpi: int) -> str:
    pixmap = doc[index].get_pixmap(dpi=dpi, alpha=False)
    encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def truth_for(pdf: Path) -> dict[str, dict]:
    """The adjudicated boundaries of this sample, or nothing when unlabelled."""
    if not corpus.CHAIN_LABELS_PATH.exists():
        return {}
    labels = corpus.chain_label_samples(corpus.load_chain_labels())
    return labels.get(pdf.name, {})


def signal_table(verdict: BoundaryVerdict) -> str:
    """Every scored pairing, one row each, the winner in bold."""
    if not verdict.pairs:
        return ""
    header = "".join(f"<th>{html.escape(name)}</th>" for name in SIGNAL_NAMES)
    rows = []
    for pair in verdict.pairs:
        cells = "".join(
            "<td>&mdash;</td>"
            if pair.values[name] is None
            else f"<td>{pair.values[name]:.2f}</td>"
            for name in SIGNAL_NAMES
        )
        klass = ' class="win"' if pair.pair == verdict.pair else ""
        rows.append(
            f"<tr{klass}><th>{html.escape(pair.pair)}</th>"
            f"<td>{pair.score:.3f}</td>{cells}"
            f"<td>{'link' if pair.linked else 'no'}</td></tr>"
        )
    return (
        f"<table><tr><th>pairing</th><th>score</th>{header}<th></th></tr>"
        f"{''.join(rows)}</table>"
    )


def text_block(verdict: BoundaryVerdict, limit: int) -> str:
    if verdict.tail is None or verdict.head is None:
        return ""
    tail_full = (verdict.tail.paragraph.unicode or "")[-limit:]
    head_full = (verdict.head.paragraph.unicode or "")[:limit]
    return (
        f'<div class="text">'
        f'<div><span class="tag">tail [{html.escape(verdict.tail.label)}] '
        f'&hellip;</span><span class="frag">{html.escape(tail_full)}</span></div>'
        f'<div><span class="tag">head [{html.escape(verdict.head.label)}] '
        f'</span><span class="frag">{html.escape(head_full)}</span>'
        f'<span class="tag">&hellip;</span></div></div>'
    )


def verdict_line(verdict: BoundaryVerdict, key: str, kinds: str, truth: dict) -> str:
    if not verdict.eligible:
        badge = f'<span class="masked">not scored: {html.escape(verdict.reason)}</span>'
    else:
        state = "linked" if verdict.linked else "unlinked"
        badge = (
            f'<span class="{state}">{state} at {verdict.score:.3f} '
            f"by {html.escape(verdict.pair)}</span>"
        )
    adjudication = ""
    note = ""
    if truth:
        want = bool(truth.get("link"))
        agrees = want == verdict.linked
        klass = "truth" if agrees else "disagree"
        adjudication = (
            f' <span class="{klass}">adjudicated {str(want).lower()}'
            f"{'' if agrees else ' -- DISAGREES'}</span>"
        )
        if truth.get("note"):
            note = f'<div class="note">{html.escape(truth["note"])}</div>'
    return (
        f'<div class="verdict">{html.escape(key)} '
        f"[{html.escape(kinds)}] {badge}{adjudication}</div>{note}"
    )


def build_html(pdf: Path, checkpoint: Path, config: dict) -> tuple[str, int, int]:
    chain_config = load_chain_config()
    taxonomy = load_taxonomy()
    docs = load_checkpoint(checkpoint)
    dpi = int(config["thumbnail_dpi"])
    limit = int(config["excerpt_chars"])
    truth = truth_for(pdf)

    sections = []
    linked = 0
    with pymupdf.open(pdf) as rendered:
        for index in range(len(docs.page) - 1):
            tail_page, head_page = docs.page[index], docs.page[index + 1]
            verdict = evaluate_boundary(
                tail_page,
                head_page,
                index,
                index + 1,
                taxonomy.policy_of,
                chain_config,
            )
            linked += 1 if verdict.linked else 0
            key = f"{index + 1}->{index + 2}"
            kinds = f"{tail_page.page_kind} -> {head_page.page_kind}"
            thumbs = "".join(
                f'<img src="{thumbnail_uri(rendered, page, dpi)}" alt="">'
                for page in (index, index + 1)
                if 0 <= page < rendered.page_count
            )
            sections.append(
                f'<div class="boundary"><div class="thumbs">{thumbs}</div>'
                f'<div class="detail">'
                f"{verdict_line(verdict, key, kinds, truth.get(key, {}))}"
                f"{signal_table(verdict)}{text_block(verdict, limit)}"
                f"</div></div>"
            )

    pairings = ", ".join(rule.name for rule in chain_config[PAIR_RULES_KEY])
    document = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>article chains: {html.escape(pdf.name)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<h1>Article chains: {html.escape(pdf.name)}</h1>"
        f'<div class="meta">link_min_score {chain_config["link_min_score"]}, '
        f"pairings {html.escape(pairings)}, "
        f"{len(docs.page) - 1} boundaries, {linked} linked, "
        f"checkpoint {html.escape(checkpoint.name)}</div>"
        f"{''.join(sections)}</body></html>"
    )
    return document, len(docs.page) - 1, linked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="source PDF, used for thumbnails")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="a checkpoint XML carrying page kinds; the pipeline is run when omitted",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"ERROR: input not found: {args.pdf}")
        return 1

    checkpoint = args.checkpoint or run_pipeline(args.pdf)
    if not checkpoint.exists():
        print(f"ERROR: checkpoint not found: {checkpoint}")
        return 1

    document, boundaries, linked = build_html(args.pdf, checkpoint, load_config())
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.pdf.stem}.chains.html"
    target.write_text(document, encoding="utf-8")
    print(f"chain_report: {boundaries} boundaries, {linked} linked -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
