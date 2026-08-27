"""Verify one manifested semantic targeted PDF run, offline and fail closed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.manual_constraint_validator import ValidationScope  # noqa: E402
from babeldoc.magazine.targeted_pdf_acceptance import (  # noqa: E402
    TargetedAcceptanceError,
)
from babeldoc.magazine.targeted_pdf_acceptance import verify_targeted_run  # noqa: E402


def _selected_pages(value: str) -> tuple[int, ...]:
    try:
        pages = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("selected pages must be comma-separated integers") from exc
    if not pages or any(page < 1 for page in pages):
        raise argparse.ArgumentTypeError("selected pages must be positive")
    if pages != tuple(sorted(set(pages))):
        raise argparse.ArgumentTypeError("selected pages must be unique canonical ascending")
    return pages


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--manifest", default="run_manifest.json")
    parser.add_argument("--expectations", required=True)
    parser.add_argument("--selected-pages", required=True, type=_selected_pages)
    parser.add_argument("--report", required=True)
    parser.add_argument("--debug-copy")
    parser.add_argument(
        "--scope",
        choices=[item.value for item in ValidationScope],
        default=ValidationScope.FULL_TRANSLATION.value,
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    run_dir = Path(args.run_dir).resolve()
    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = run_dir / manifest
    try:
        report = verify_targeted_run(
            source_pdf=args.source,
            run_dir=run_dir,
            manifest_path=manifest,
            expectations_path=args.expectations,
            selected_pages=args.selected_pages,
            report_path=args.report,
            debug_copy=args.debug_copy,
            scope=args.scope,
        )
    except (OSError, ValueError, TargetedAcceptanceError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "targeted-pdf-acceptance.v1",
                    "status": "fail",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "schema_version": report["schema_version"],
                "status": report["status"],
                "overall": report["overall"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] in {"pass", "parse_gate_pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
