"""Chains the joint translation pass handed back, raised to issues.

The chain pass already decides, and already records, every chain it refused to
translate as one unit and why: a chain over the output token budget, one whose
members carry placeholders, one whose redistribution failed conservation. Each
of those is a page break left inside a sentence, which is exactly the class of
defect this package exists to surface.

So this detector carries, and decides nothing. It reads the sidecar that pass
writes and restates each escalation in the issue vocabulary. A finding here
that disagrees with that sidecar is a bug in this file, because there is no
second judgement for it to disagree with.
"""

from __future__ import annotations

import json
from pathlib import Path

from babeldoc.magazine.chain_translation import REPORT_NAME
from babeldoc.magazine.detectors import base

NAME = "escalation_surfacing"
KIND = "chain_escalation"

REQUIRES_TRANSLATION = True
REQUIRES_SOURCE_GEOMETRY = False

# The section of the chain pass report this reads, and the key inside it.
ESCALATED_KEY = "escalated"
MEMBERS_KEY = "members"


def read_escalations(working_dir: Path | None) -> list[dict]:
    """What the chain pass refused, or nothing where it did not run."""
    if working_dir is None:
        return []
    path = Path(working_dir) / REPORT_NAME
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        report = json.load(f)
    return list(report.get(ESCALATED_KEY) or ())


def _page_of(members: list[dict], pages: dict[int, base.PageView]) -> int | None:
    """The first page the chain touches, by the label the pages carry."""
    indices = [
        member.get("page_index")
        for member in members
        if member.get("page_index") is not None
    ]
    if not indices:
        return None
    position = min(int(index) for index in indices)
    view = pages.get(position)
    return view.label if view is not None else position + 1


def _references(
    members: list[dict], pages: dict[int, base.PageView]
) -> tuple[tuple[str, ...], list]:
    """The chain's members as paragraph references, by their debug ids."""
    wanted = {
        member.get("debug_id") for member in members if member.get("debug_id")
    }
    references: list[str] = []
    boxes = []
    for view in pages.values():
        for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
            if paragraph.debug_id in wanted:
                references.append(view.reference(index))
                boxes.append(base.box_tuple(paragraph.box))
    return tuple(references), boxes


def detect(context: base.DetectionContext) -> list[base.Issue]:
    escalations = read_escalations(context.working_dir)
    if not escalations:
        return []
    # Keyed by the position the chain pass recorded, which is the index of the
    # page in the document rather than its label.
    pages = dict(enumerate(context.pages))
    found: list[base.Issue] = []
    for record in escalations:
        members = list(record.get(MEMBERS_KEY) or ())
        page = _page_of(members, pages)
        if page is None:
            context.notes.append(
                f"{NAME}: chain {record.get('chain_id')!r} names no page and "
                f"was not raised"
            )
            continue
        references, boxes = _references(members, pages)
        found.append(
            base.Issue(
                kind=KIND,
                page=page,
                paragraph_refs=references,
                geometry=base.union_box(boxes),
                severity=context.severity_of(KIND),
                evidence={
                    "chain_id": record.get("chain_id"),
                    "reason": record.get("reason"),
                    "detail": record.get("detail"),
                    "member_count": len(members),
                    "source_report": REPORT_NAME,
                },
                detector=NAME,
                detected_at_iteration=context.iteration,
            )
        )
    return found
