"""Human review page for the deterministic page classifier.

Usage:
    python tools/page_classify_report.py examples/input/sample.pdf
    python tools/page_classify_report.py sample.pdf --checkpoint work/checkpoint.07_page_classifier.xml

Writes a single self-contained HTML file to ``examples/output/b2/`` holding, for
every page, a thumbnail, the full feature vector, the ranked page type scores
and the verdict. This is the interface for tuning ``configs/page_types.json``:
edit the thresholds, rerun this tool, compare. No code change is involved in a
retune.

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
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.page_features import FEATURE_NAMES  # noqa: E402
from babeldoc.magazine.page_features import extract_page_features  # noqa: E402
from babeldoc.magazine.taxonomy import classify  # noqa: E402
from babeldoc.magazine.taxonomy import load_configs  # noqa: E402

CONFIG_PATH = ROOT / "configs" / "page_classify_report.json"
DEFAULT_OUT_DIR = ROOT / "examples" / "output" / "b2"

_STYLE = """
body { font: 13px/1.5 sans-serif; margin: 24px; color: #1a1a1a; }
h1 { font-size: 20px; }
.meta { color: #555; margin-bottom: 20px; }
.page { display: flex; gap: 18px; border-top: 1px solid #ddd; padding: 16px 0; }
.thumb img { border: 1px solid #bbb; display: block; }
.detail { flex: 1; min-width: 0; }
.verdict { font-size: 15px; font-weight: 600; margin-bottom: 8px; }
.ambiguous { background: #ffe9a8; padding: 1px 6px; border-radius: 3px;
             font-weight: 400; font-size: 12px; }
table { border-collapse: collapse; margin-right: 24px; }
td, th { padding: 1px 10px 1px 0; text-align: left; vertical-align: top; }
th { color: #555; font-weight: 500; }
.cols { display: flex; flex-wrap: wrap; }
.bar { display: inline-block; height: 8px; background: #4a7fb5; vertical-align: middle; }
"""


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def run_pipeline(pdf: Path) -> Path:
    """Dry run the pipeline with the classifier on and return its checkpoint."""
    from babeldoc.assets.assets import warmup
    from babeldoc.docvision.doclayout import DocLayoutModel
    from babeldoc.format.pdf import high_level
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.format.pdf.translation_config import WatermarkOutputMode
    from babeldoc.magazine.cache_setup import use_project_cache
    from babeldoc.magazine.checkpoint import checkpoint_stem

    use_project_cache(ROOT)
    warmup()
    work_root = Path(tempfile.mkdtemp(prefix="page_classify_"))
    config = TranslationConfig(
        translator=None,
        input_file=pdf,
        lang_in="en",
        lang_out="zh",
        doc_layout_model=DocLayoutModel.load_onnx(),
        output_dir=work_root / "out",
        working_dir=work_root / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=False,
        skip_translation=True,
        magazine_checkpoint=True,
        magazine_page_classify=True,
    )
    high_level.translate(config)
    return Path(config.working_dir) / f"{checkpoint_stem('page_classifier')}.xml"


def thumbnail_uri(doc: pymupdf.Document, index: int, dpi: int) -> str:
    pixmap = doc[index].get_pixmap(dpi=dpi, alpha=False)
    encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def feature_table(features: dict[str, float]) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(name)}</th><td>{features[name]:.4f}</td></tr>"
        for name in FEATURE_NAMES
    )
    return f"<table>{rows}</table>"


def score_table(scores: dict[str, float], limit: int) -> str:
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
    rows = "".join(
        f"<tr><th>{html.escape(name)}</th><td>{score:.3f}</td>"
        f'<td><span class="bar" style="width:{score * 80:.0f}px"></span></td></tr>'
        for name, score in ranked
    )
    return f"<table>{rows}</table>"


def build_html(pdf: Path, checkpoint: Path, config: dict) -> tuple[str, int]:
    feature_config, taxonomy = load_configs()
    docs = load_checkpoint(checkpoint)
    dpi = int(config["thumbnail_dpi"])
    limit = int(config["score_rows"])

    sections = []
    with pymupdf.open(pdf) as rendered:
        for position, page in enumerate(docs.page):
            features = extract_page_features(page, docs, feature_config)
            verdict = classify(features, taxonomy)
            index = page.page_number if page.page_number is not None else position
            thumb = (
                f'<img src="{thumbnail_uri(rendered, index, dpi)}" alt="">'
                if 0 <= index < rendered.page_count
                else "no thumbnail"
            )
            badge = (
                ' <span class="ambiguous">ambiguous</span>' if verdict.ambiguous else ""
            )
            sections.append(
                f'<div class="page"><div class="thumb">{thumb}</div>'
                f'<div class="detail"><div class="verdict">'
                f"page {index} &rarr; {html.escape(verdict.kind)} "
                f"(conf {verdict.confidence:.3f}){badge}</div>"
                f'<div class="cols">{feature_table(features)}'
                f"{score_table(verdict.scores, limit)}</div></div></div>"
            )

    body = "".join(sections)
    document = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>page classification: {html.escape(pdf.name)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<h1>Page classification: {html.escape(pdf.name)}</h1>"
        f'<div class="meta">taxonomy {html.escape(taxonomy.version)}, '
        f"ambiguity margin {taxonomy.ambiguity_margin}, "
        f"{len(docs.page)} pages, checkpoint {html.escape(checkpoint.name)}</div>"
        f"{body}</body></html>"
    )
    return document, len(docs.page)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="source PDF, used for thumbnails")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="page classifier checkpoint XML; the pipeline is run when omitted",
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

    document, pages = build_html(args.pdf, checkpoint, load_config())
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.pdf.stem}.classify.html"
    target.write_text(document, encoding="utf-8")
    print(f"page_classify_report: {pages} page(s) -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
