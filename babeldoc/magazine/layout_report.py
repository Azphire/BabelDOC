"""Audit immutable source-container typesetting for the minimal pipeline."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from babeldoc.magazine import line_split
from babeldoc.magazine.run_trace import parse_source_ref

REPORT_NAME = "layout_report.json"
ROLE_BODY = "body"
ROLE_CHAIN = "chain"
EMPTY_TEXT_SHA256 = hashlib.sha256(b"").hexdigest()


class ConservativeLayoutError(ValueError):
    """A paragraph cannot be proved to remain in its frozen source box."""


BoxTuple = tuple[float, float, float, float]


def _box_tuple(value) -> BoxTuple | None:
    if value is None:
        return None
    try:
        result = tuple(float(getattr(value, name)) for name in ("x", "y", "x2", "y2"))
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        len(result) != 4
        or not all(math.isfinite(item) for item in result)
        or result[0] >= result[2]
        or result[1] >= result[3]
    ):
        return None
    return result


def _contains(outer: BoxTuple, inner: BoxTuple, tolerance: float = 0.001) -> bool:
    return (
        outer[0] - tolerance <= inner[0]
        and outer[1] - tolerance <= inner[1]
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


@dataclass(frozen=True, slots=True)
class SourceContainer:
    """One paragraph's immutable formal-typesetting boundary."""

    source_ref: str
    role: str
    source_box: BoxTuple
    allocation_box: BoxTuple

    @property
    def record_kind(self) -> str:
        """Present the SourceUnit interface consumed by bounded typesetting."""
        return self.role


@dataclass(slots=True)
class _LayoutEntry:
    container: SourceContainer
    status: str = "pending"
    final_holder_box: BoxTuple | None = None
    final_text_box: BoxTuple | None = None
    overflow_reason: str | None = None

    def to_record(self) -> dict:
        held = self.container
        return {
            "source_ref": held.source_ref,
            "role": held.role,
            "source_box": list(held.source_box),
            "allocation_box": list(held.allocation_box),
            "final_holder_box": (
                None if self.final_holder_box is None else list(self.final_holder_box)
            ),
            "final_text_box": (
                None if self.final_text_box is None else list(self.final_text_box)
            ),
            "status": self.status,
            "overflow_reason": self.overflow_reason,
            "article_flow_applied": False,
        }


@dataclass(slots=True)
class _Run:
    report_path: Path
    entries: dict[int, _LayoutEntry]
    paragraphs: dict[int, object]
    debug_entries: dict[tuple[int, str], _LayoutEntry]


_RUN: _Run | None = None


def discard() -> None:
    """Clear a prior run when a test double supplies no layout contract."""
    global _RUN
    _RUN = None


def _write() -> dict:
    if _RUN is None:
        raise ConservativeLayoutError("conservative layout is not prepared")
    records = sorted(
        (entry.to_record() for entry in _RUN.entries.values()),
        key=lambda item: (
            parse_source_ref(item["source_ref"]),
            item["role"],
        ),
    )
    record = {
        "article_flow_applied": False,
        "elements": records,
        "totals": {
            "elements": len(records),
            "success": sum(item["status"] == "success" for item in records),
            "overflow": sum(item["status"] == "overflow" for item in records),
            "pending": sum(item["status"] == "pending" for item in records),
        },
    }
    _RUN.report_path.parent.mkdir(parents=True, exist_ok=True)
    _RUN.report_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def _physical_page(page, fallback: int) -> int:
    page_number = getattr(page, "page_number", None)
    return fallback if page_number is None else int(page_number) + 1


def prepare(
    translation_config,
    docs,
    article_document_ir,
    *,
    article_flow_report: dict,
    eligible_roles: tuple[str, ...],
) -> dict:
    """Freeze body, chain, and line-structure holders before formal typesetting."""
    global _RUN

    if article_flow_report.get("article_flow_applied") is not False:
        raise ConservativeLayoutError("ordinary article flow must remain disabled")
    report_path = Path(translation_config.get_working_file_path(REPORT_NAME))
    run = _Run(report_path, {}, {}, {})
    _RUN = run

    elements = {
        element.source_ref: element
        for article in article_document_ir.articles
        for element in article.elements
    }
    chain_refs = set(article_document_ir.by_chain_member)
    eligible = frozenset(eligible_roles)
    seen_refs: set[str] = set()

    for local_page, page in enumerate(docs.page or (), start=1):
        physical_page = _physical_page(page, local_page)
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph or ()):
            if line_split.is_debug_overlay(paragraph):
                continue
            target_nonempty = bool(
                (getattr(paragraph, "unicode", None) or "").strip()
            )
            local_ref = f"p{local_page}#{paragraph_index}"
            physical_ref = f"p{physical_page}#{paragraph_index}"
            unit = line_split.source_unit(paragraph, physical_page)
            element = elements.get(local_ref)
            if unit is not None:
                if getattr(unit, "fixed_companion", False):
                    # Fixed folios are untranslated source furniture.  They
                    # retain their original glyph geometry and are not target
                    # holders subject to translated-text containment.
                    continue
                source_ref = unit.source_ref
                role = unit.record_kind
                source_box = unit.source_box
            elif getattr(paragraph, "chain_id", None) or local_ref in chain_refs:
                source_ref = physical_ref
                role = ROLE_CHAIN
                source_box = None if element is None else element.source_box
            else:
                element_role = (
                    getattr(paragraph, "layout_label", None)
                    if element is None
                    else element.role
                )
                if element_role not in eligible:
                    continue
                if (
                    not target_nonempty
                    and (
                        element is None
                        or element.source_text_hash == EMPTY_TEXT_SHA256
                    )
                ):
                    continue
                source_ref = physical_ref
                role = ROLE_BODY
                source_box = None if element is None else element.source_box

            source = (
                tuple(float(item) for item in source_box)
                if source_box is not None
                else _box_tuple(getattr(paragraph, "box", None))
            )
            allocation = _box_tuple(getattr(paragraph, "box", None))
            if source is None or allocation is None:
                raise ConservativeLayoutError(
                    f"{source_ref}: source/allocation container is not measurable"
                )
            if source_ref in seen_refs:
                raise ConservativeLayoutError(
                    f"duplicate conservative layout source ref: {source_ref}"
                )
            seen_refs.add(source_ref)
            container = SourceContainer(source_ref, role, source, allocation)
            entry = _LayoutEntry(container)
            run.entries[id(paragraph)] = entry
            run.paragraphs[id(paragraph)] = paragraph
            debug_id = getattr(paragraph, "debug_id", None)
            if debug_id:
                key = (physical_page, debug_id)
                if key in run.debug_entries:
                    raise ConservativeLayoutError(
                        f"ambiguous conservative layout debug id: {key}"
                    )
                run.debug_entries[key] = entry
            if not _contains(source, allocation):
                entry.status = "overflow"
                entry.overflow_reason = "allocation_outside_source_box"
                _write()
                _RUN = None
                raise ConservativeLayoutError(
                    f"{source_ref}: allocation is outside the frozen source box"
                )
    return {
        "article_flow_applied": False,
        "elements": len(run.entries),
    }


def source_container(paragraph, physical_page: int | None = None) -> SourceContainer | None:
    if _RUN is None:
        return None
    held = _RUN.entries.get(id(paragraph))
    if held is not None and _RUN.paragraphs.get(id(paragraph)) is paragraph:
        return held.container
    debug_id = getattr(paragraph, "debug_id", None)
    if physical_page is not None and debug_id:
        entry = _RUN.debug_entries.get((physical_page, debug_id))
        return None if entry is None else entry.container
    return None


def _entry(paragraph, physical_page: int | None = None) -> _LayoutEntry | None:
    if _RUN is None:
        return None
    held = _RUN.entries.get(id(paragraph))
    if held is not None and _RUN.paragraphs.get(id(paragraph)) is paragraph:
        return held
    debug_id = getattr(paragraph, "debug_id", None)
    if physical_page is not None and debug_id:
        return _RUN.debug_entries.get((physical_page, debug_id))
    return None


def record_success(
    paragraph,
    physical_page: int | None,
    *,
    final_text_box: BoxTuple | None,
) -> None:
    """Record and enforce the final holder/text containment contract."""
    global _RUN
    entry = _entry(paragraph, physical_page)
    if entry is None:
        return
    holder = _box_tuple(getattr(paragraph, "box", None))
    source = entry.container.source_box
    reason = None
    if holder is None or not _contains(source, holder):
        reason = "final_holder_outside_source_box"
    elif final_text_box is None:
        reason = "final_text_box_missing"
    elif not _contains(source, final_text_box):
        reason = "final_text_outside_source_box"
    if reason is not None:
        entry.status = "overflow"
        entry.final_holder_box = holder
        entry.final_text_box = final_text_box
        entry.overflow_reason = reason
        _write()
        _RUN = None
        raise ConservativeLayoutError(
            f"{entry.container.source_ref}: {reason.replace('_', ' ')}"
        )
    entry.status = "success"
    entry.final_holder_box = holder
    entry.final_text_box = final_text_box
    entry.overflow_reason = None


def record_overflow(
    paragraph,
    physical_page: int | None,
    reason: str,
) -> None:
    global _RUN
    entry = _entry(paragraph, physical_page)
    if entry is None:
        return
    entry.status = "overflow"
    entry.final_holder_box = _box_tuple(getattr(paragraph, "box", None))
    entry.final_text_box = None
    entry.overflow_reason = reason
    _write()
    _RUN = None


def finalize() -> dict:
    """Write the completed formal-typesetting audit, rejecting missing renders."""
    global _RUN
    if _RUN is None:
        raise ConservativeLayoutError("conservative layout is not prepared")
    pending = [
        entry.container.source_ref
        for entry in _RUN.entries.values()
        if entry.status == "pending"
    ]
    record = _write()
    if pending:
        _RUN = None
        raise ConservativeLayoutError(
            f"formal typesetting did not render frozen holders: {sorted(pending)}"
        )
    _RUN = None
    return record
