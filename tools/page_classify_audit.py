"""Offline replay of the page classifier's two sources, one row per page.

Reads finished ``page_classify.report.json`` files -- each already carries the
deterministic layer's verdict (``kind``/``conf``/``ambiguous``) and the model's
(``vlm``) side by side -- and prints the per-page comparison the B15 T2b audit
calls for.  No page is re-rendered and no model is asked: the replay is a read
of what both layers already said.

Usage:
    python tools/page_classify_audit.py <name=work_dir> [<name=work_dir>...]

Each argument names one sample and the working directory holding its report.
Exit code 0 always; the table is the product.  Adjudication of disagreements
is a human step recorded elsewhere (docs/reports/B15/), not something this
tool invents.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPORT_NAME = "page_classify.report.json"


def rows_of(name: str, work_dir: Path) -> list[dict]:
    report = json.loads((work_dir / REPORT_NAME).read_text(encoding="utf-8"))
    rows = []
    for page in report.get("pages", ()):
        vlm = page.get("vlm") or {}
        vlm_kind = vlm.get("kind") if vlm.get("accepted") else None
        deterministic = page.get("kind")
        rows.append(
            {
                "sample": name,
                "page": int(page.get("page_number", 0)) + 1,
                "deterministic_kind": deterministic,
                "deterministic_conf": page.get("conf"),
                "ambiguous": page.get("ambiguous"),
                "vlm_kind": vlm_kind,
                "vlm_conf": vlm.get("confidence") if vlm_kind else None,
                "final_kind": page.get("final_kind"),
                "agree": (vlm_kind is None) or (vlm_kind == deterministic),
            }
        )
    return rows


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: page_classify_audit.py <name=work_dir> [...]", file=sys.stderr)
        return 2
    rows: list[dict] = []
    for argument in argv:
        name, _, path = argument.partition("=")
        if not path:
            print(f"argument {argument!r} is not name=work_dir", file=sys.stderr)
            return 2
        rows.extend(rows_of(name, Path(path)))
    disagreements = [row for row in rows if not row["agree"]]
    print(json.dumps({"rows": rows, "disagreements": len(disagreements)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
