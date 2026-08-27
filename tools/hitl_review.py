"""Regenerate the human readable page of a review draft.

Usage:
    python tools/hitl_review.py Courier-en
    python tools/hitl_review.py reviews/Courier-en.review.json
    python tools/hitl_review.py bind --source SOURCE.pdf --config babeldoc.toml \
        --review SAMPLE.review.json --decisions SAMPLE.decisions.json \
        --output-dir EMPTY_DIRECTORY

The pipeline already writes this page beside the draft on every export, so this
tool is for the case where the draft was edited by hand, or where a draft
carried over from an earlier run has to be read again without rerunning the
pipeline. It renders with the same function the pipeline renders with, so the
two cannot drift apart.

What a page looks like is not answered here; tools/page_classify_report.py
answers that, with thumbnails and the full feature vector. This page answers
what was decided and what a ruling would have to say to change it.

Exit codes: 0 page written, 1 the draft could not be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.hitl import REVIEW_SUFFIX  # noqa: E402
from babeldoc.magazine.hitl import render_review_html  # noqa: E402
from babeldoc.magazine.hitl import review_html_path  # noqa: E402
from babeldoc.magazine.hitl import review_path  # noqa: E402
from babeldoc.magazine.hitl_binding import HitlBindingError  # noqa: E402
from babeldoc.magazine.hitl_binding import bind_legacy_files  # noqa: E402


def resolve(target: str) -> Path:
    """Accept either a sample name or a path to the draft itself."""
    candidate = Path(target)
    if candidate.suffix == ".json" and candidate.exists():
        return candidate
    return review_path(candidate.name.removesuffix(REVIEW_SUFFIX))


def _bind(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="hitl_review.py bind",
        description="Bind legacy explicit decisions to a current source PDF.",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = bind_legacy_files(
            source=args.source,
            config_path=args.config,
            review_path=args.review,
            decisions_path=args.decisions,
            output_dir=args.output_dir,
        )
    except HitlBindingError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"bound {report['sample']} as {report['binding_mode']} in {args.output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "bind":
        return _bind(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="sample name, or path to a review draft")
    parser.add_argument(
        "--out", type=Path, default=None, help="where to write the page"
    )
    args = parser.parse_args(argv)

    draft_path = resolve(args.target)
    if not draft_path.exists():
        print(f"no review draft at {draft_path}", file=sys.stderr)
        return 1
    with draft_path.open(encoding="utf-8") as f:
        draft = json.load(f)

    out = args.out or review_html_path(draft.get("sample", draft_path.stem))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(render_review_html(draft))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
