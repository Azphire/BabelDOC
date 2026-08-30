"""Does every frozen truth record sit on a page its own fixture declares?

``stage_pages`` is a fixture's statement about which pages it can adjudicate,
and ``verify_magazine_demo`` now takes it at its word: a detector chain outside
that scope is skipped rather than judged. That only holds together if the truth
itself stays inside the scope it declares. Nothing checked that, and task A
found it is not true everywhere -- bull-zh freezes a cross-page chain on pages
six and seven while declaring pages three, four, five, eight and nine.

The consequence is narrow but real. That chain is adjudicated today only
because the scope filter keeps any chain the truth reaches out to claim; it is
verified by an accident of the rule rather than by the fixture's own account of
itself, and a reader of the fixture cannot tell which pages it stands behind.

This script is deliberately not part of any acceptance gate. It reports a
standing fixture defect, and it is expected to fail on bull-zh until that
fixture is either narrowed to its declared scope or the scope is widened to
match its truth. Deciding which is a fixture change, not a verifier change.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "tests/fixtures/demo/sample_matrix.json"
REF_PAGE = re.compile(r"p(\d+)#\d+")

# Where each kind of truth record keeps the page it speaks about. A record
# names its page outright, or names a source ref that carries it.
DIRECT = "physical_page"
ANCHOR = "anchor"


def _pages_of(record: dict, where: str) -> tuple[list[int], list[str]]:
    """Every page one truth record touches, and what could not be read."""
    pages: list[int] = []
    unreadable: list[str] = []
    if isinstance(record.get(DIRECT), int):
        pages.append(record[DIRECT])
    # A block record anchors on every ref it spans, so an anchor is a ref or
    # a list of them.
    anchor = record.get(ANCHOR)
    anchors = anchor if isinstance(anchor, list) else [anchor]
    for item in anchors:
        if item is None:
            continue
        match = REF_PAGE.fullmatch(item) if isinstance(item, str) else None
        if match is None:
            unreadable.append(f"{where}: unreadable anchor {item!r}")
        else:
            pages.append(int(match.group(1)))
    for key in ("ordered_members", "endpoints"):
        for index, member in enumerate(record.get(key) or ()):
            member_pages, member_unreadable = _pages_of(member, f"{where}.{key}[{index}]")
            pages.extend(member_pages)
            unreadable.extend(member_unreadable)
    if not pages and not unreadable:
        unreadable.append(f"{where}: no page on record")
    return pages, unreadable


KINDS = (
    "chains",
    "negative_chain_pairs",
    "titles",
    "dropcaps",
    "toc_records",
    "layout_regions",
    "coverage_exemptions",
)


def _identify(kind: str, index: int, record: dict) -> str:
    return f"{kind}[{record.get('id') or record.get('anchor') or index}]"


def check(sample: dict) -> tuple[bool, list[str]]:
    expectations = json.loads(
        (ROOT / sample["expectations_path"]).read_text(encoding="utf-8")
    )
    lines = []
    declared = expectations.get("stage_pages")
    if not isinstance(declared, list) or not declared:
        return False, ["  no stage_pages declared"]
    if any(not isinstance(page, int) or isinstance(page, bool) or page <= 0
           for page in declared):
        return False, [f"  invalid stage_pages: {declared}"]
    scope = set(declared)

    outside = []
    unreadable = []
    counted = 0
    for kind in KINDS:
        for index, record in enumerate(expectations.get(kind) or ()):
            where = _identify(kind, index, record)
            pages, problems = _pages_of(record, where)
            unreadable.extend(problems)
            counted += 1
            stray = sorted({page for page in pages if page not in scope})
            if stray:
                outside.append((where, sorted(set(pages)), stray))

    lines.append(f"  stage_pages={declared}  truth records={counted}")
    for where, pages, stray in outside:
        lines.append(f"  OUTSIDE {where}: pages={pages}, outside scope={stray}")
    for problem in unreadable:
        lines.append(f"  UNREADABLE {problem}")
    return not outside and not unreadable, lines


def main() -> int:
    samples = json.loads(MATRIX.read_text(encoding="utf-8"))
    passed = 0
    for sample in samples:
        ok, lines = check(sample)
        print(f"{'pass' if ok else 'FAIL'} {sample['sample_id']}")
        for line in lines:
            print(line)
        passed += ok
    print(f"\n{passed}/{len(samples)} fixtures keep their truth inside the scope they declare")
    return 0 if passed == len(samples) else 1


if __name__ == "__main__":
    sys.exit(main())
