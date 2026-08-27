"""Behavior checks for atomic semantic geometry commits."""

from __future__ import annotations

import math
import sys
from pathlib import Path

GATE_SET = "fast"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il.il_version_1 import Box  # noqa: E402
from babeldoc.magazine.geometry_write import GeometryRole  # noqa: E402
from babeldoc.magazine.geometry_write import propose_box_update  # noqa: E402
from babeldoc.magazine.geometry_write import propose_box_updates  # noqa: E402


def coords(value):
    return value.x, value.y, value.x2, value.y2


def main() -> int:
    checks = {}
    target = Box(1, 1, 4, 4)
    checks["valid candidate commits"] = propose_box_update(
        target, (2, 2, 5, 5), page_bounds=(0, 0, 10, 10), stage="gate",
        source_page=1, stable_ref="p1#0"
    ).committed and coords(target) == (2, 2, 5, 5)

    cases = {
        "zero-area text": (2, 2, 2, 5),
        "NaN": (2, 2, math.nan, 5),
        "Inf": (2, 2, math.inf, 5),
        "reversed": (5, 2, 2, 5),
        "outside page": (-1, 2, 2, 5),
    }
    for name, candidate in cases.items():
        value = Box(1, 1, 4, 4)
        result = propose_box_update(
            value, candidate, page_bounds=(0, 0, 10, 10), stage="gate",
            source_page=7, stable_ref="p7#3"
        )
        checks[f"{name} refuses without mutation"] = (
            not result.committed
            and coords(value) == (1, 1, 4, 4)
            and "stage=gate" in str(result.refusal)
            and "source_page=7" in str(result.refusal)
            and "stable_ref=p7#3" in str(result.refusal)
        )

    marker = Box(1, 1, 4, 4)
    checks["zero-area marker is allowed"] = propose_box_update(
        marker, (2, 2, 2, 5), page_bounds=(0, 0, 10, 10), stage="gate",
        source_page=1, stable_ref="marker", role=GeometryRole.MARKER
    ).committed

    first, second = Box(1, 1, 2, 2), Box(3, 3, 4, 4)
    transaction = propose_box_updates(
        ((first, (2, 2, 3, 3), "first", GeometryRole.PROCESSABLE_TEXT),
         (second, (8, 8, 7, 9), "second", GeometryRole.PROCESSABLE_TEXT)),
        page_bounds=(0, 0, 10, 10), stage="overlap", source_page=1,
    )
    checks["multi-box refusal cannot half-commit"] = (
        not transaction.committed
        and coords(first) == (1, 1, 2, 2)
        and coords(second) == (3, 3, 4, 4)
    )
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"spec_check_geometry_write_guard: {sum(checks.values())}/{len(checks)} passed")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
