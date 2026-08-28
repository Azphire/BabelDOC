"""Article and page ownership checks over the canonical runtime lineage."""

from __future__ import annotations

from babeldoc.magazine.detectors import base

NAME = "article_ownership"
KIND = "article_ownership"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False
REQUIRES_ARTICLE_IR = True
REQUIRES_RUN_TRACE = True
FINAL_ONLY = True


def _issue(context, source, fragment=None, geometry=None, reasons=()):
    trace = context.run_trace
    article_ir = context.article_document_ir
    expected = article_ir.by_element.get(source.source_ref)
    articles = tuple(
        sorted(
            {
                value
                for value in (
                    expected,
                    source.article_id,
                    None
                    if geometry is None
                    else getattr(
                        trace.flow_slots.get(geometry.slot_id), "article_id", None
                    ),
                )
                if value
            }
        )
    )
    final_page = (
        source.page
        if fragment is None
        else geometry.final_page
        if geometry is not None and geometry.final_page is not None
        else fragment.render_page or source.page
    )
    box = (
        None
        if geometry is None
        else geometry.final_box or geometry.pre_repair_box
    )
    return base.Issue(
        kind=KIND,
        page=final_page,
        paragraph_refs=(source.source_ref,),
        geometry=None if box is None else base.union_box([box]),
        severity=context.severity_of(KIND),
        evidence={
            "expected_article_id": expected,
            "trace_article_id": source.article_id,
            "final_page": final_page,
            "reasons": sorted(set(reasons)),
            "violation_count": len(set(reasons)),
            "identity_ref": (
                f"fragment:{fragment.fragment_id}"
                if fragment is not None
                else "source"
            ),
        },
        detector=NAME,
        detected_at_iteration=context.iteration,
        article_refs=articles,
        source_refs=(source.source_ref,),
        fragment_refs=()
        if fragment is None
        else (fragment.fragment_id,),
    )


def detect(context: base.DetectionContext) -> list[base.Issue]:
    trace = context.run_trace
    article_ir = context.article_document_ir
    found = []
    for source_ref, source in sorted(trace.sources.items()):
        expected = article_ir.by_element.get(source_ref)
        reasons = []
        if expected is None and source.article_id is not None:
            reasons.append("source_is_outside_canonical_article_ir")
        elif expected is not None and source.article_id != expected:
            reasons.append("source_article_differs_from_canonical_owner")
        if reasons:
            found.append(_issue(context, source, reasons=reasons))

    for _fragment_id, fragment in sorted(trace.fragments.items()):
        if not fragment.active:
            continue
        source = trace.sources.get(fragment.source_ref)
        if source is None:
            continue
        expected = article_ir.by_element.get(source.source_ref)
        article = None if expected is None else article_ir.article(expected)
        for geometry_id in sorted(fragment.geometry_ids):
            geometry = trace.geometries.get(geometry_id)
            if geometry is None or not geometry.active:
                continue
            slot = trace.flow_slots.get(geometry.slot_id)
            if expected is None and source.article_id is None and slot is None:
                continue
            final_page = geometry.final_page or fragment.render_page or source.page
            reasons = []
            if article is None or final_page not in article.pages:
                reasons.append("geometry_page_is_outside_article")
            if slot is not None and expected is not None:
                if slot.article_id != expected:
                    reasons.append("geometry_slot_belongs_to_another_article")
                if slot.page != final_page:
                    reasons.append("geometry_page_differs_from_slot_page")
            if reasons:
                found.append(
                    _issue(context, source, fragment, geometry, reasons)
                )
    return found
