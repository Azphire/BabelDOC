"""Run the source audit on a working directory that already exists.

The audit itself is ``babeldoc.magazine.source_audit``, which the pipeline calls
at the point the fragment stitch runs. This is the way to ask the same question
of a run that has already been made: what are the short paragraphs on these
pages, and is each of them a written unit the paragraph finder broke or a layer
of text the page holds twice.

Nothing here calls a model and nothing here writes to a document.

Usage:
    python tools/source_audit.py --pages 3 \\
        --checkpoint <working dir>/checkpoint.05_paragraph_finder.json \\
        --pdf examples/input/Vogue-en.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import source_audit  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--pages", type=str, default=None)
    args = parser.parse_args(argv)

    pages = (
        None
        if not args.pages
        else [int(item) for item in args.pages.replace(",", " ").split()]
    )
    config = source_audit.load_audit_config()
    record = source_audit.audit_document(args.checkpoint, args.pdf, pages, config)
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"{args.out}: {record['counts']}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
