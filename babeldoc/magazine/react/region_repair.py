"""Applicability binding for bounded existing-target article-region retypeset."""

from __future__ import annotations

from babeldoc.magazine import article_flow
from babeldoc.magazine.element_roles import ElementRole
from babeldoc.magazine.react import actions

NAME = "retypeset_article_region"
PARAGRAPHS_PER_FINDING = None

REASON_ARTICLE = "canonical_article_owner_unavailable"
REASON_UNSUPPORTED = "unsupported_article_page"
REASON_SLOT = "canonical_legal_slot_unavailable"
REASON_TARGET = "existing_article_target_unavailable"
REASON_ROLE = "article_region_has_no_mutable_body_target"


def owner_for_issue(issue, article_document_ir) -> str | None:
    owners = set(issue.article_refs)
    if not owners and issue.page in article_document_ir.by_page:
        owners.add(article_document_ir.by_page[issue.page])
    return next(iter(owners)) if len(owners) == 1 else None


def resolve_candidate(issue, pages_by_label: dict, context):
    article_document_ir = context.article_document_ir
    if article_document_ir is None:
        return None
    owner = owner_for_issue(issue, article_document_ir)
    article = None if owner is None else article_document_ir.article(owner)
    if article is None:
        return None
    candidates = list(issue.paragraph_refs) or [
        element.source_ref
        for element in article.elements
        if element.page == issue.page and element.role is ElementRole.BODY
    ]
    for reference in candidates:
        try:
            page_number, paragraph_index = reference[1:].split("#", 1)
            view = pages_by_label[int(page_number)]
            paragraph = view.page.pdf_paragraph[int(paragraph_index)]
        except (KeyError, ValueError, IndexError):
            continue
        return actions.Candidate(
            issue_id=issue.id,
            reference=reference,
            page_index=view.label,
            paragraph_index=int(paragraph_index),
            paragraph=paragraph,
            page=view.page,
            source_text=article_flow.canonical_text(
                getattr(paragraph, "unicode", "") or ""
            ),
            issue=issue,
        )
    return None


def admits(issue, _candidate, _action, context) -> str:
    article_document_ir = context.article_document_ir
    if article_document_ir is None:
        return REASON_ARTICLE
    owner = owner_for_issue(issue, article_document_ir)
    if owner is None or article_document_ir.by_page.get(issue.page) != owner:
        return REASON_ARTICLE
    if issue.page in {item.page for item in article_document_ir.unsupported_pages}:
        return REASON_UNSUPPORTED
    if context.legal_slot_plan is None or not context.legal_slot_plan.region_slots(
        owner,
        issue.page,
        _candidate.issue.evidence.get("column", 0),
    ):
        if not (
            context.legal_slot_plan
            and any(
                slot.page == issue.page
                for slot in context.legal_slot_plan.article_slots(owner)
            )
        ):
            return REASON_SLOT
    article = article_document_ir.article(owner)
    mutable = [
        element
        for element in article.elements
        if element.page == issue.page and element.role is ElementRole.BODY
    ]
    if not mutable:
        return REASON_ROLE
    if context.run_trace is None or not any(
        context.run_trace.target_fragments_for_source(element.source_ref)
        for element in mutable
    ):
        return REASON_TARGET
    return actions.ACCEPTED
