"""Bounded reallocation of one already translated canonical continuity chain."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from babeldoc.format.pdf.document_il.il_version_1 import Box
from babeldoc.magazine import article_flow
from babeldoc.magazine import chain_backfill
from babeldoc.magazine.detectors import base as detector_base
from babeldoc.magazine.element_roles import ElementRole
from babeldoc.magazine.legal_slots import slot_for_source_box
from babeldoc.magazine.page_identity import DocumentPageIndex
from babeldoc.magazine.react import actions
from babeldoc.magazine.react import writeback
from babeldoc.magazine.run_trace import REQUEST_COMPLETED
from babeldoc.magazine.run_trace import canonical_text

NAME = "reallocate_continuity_chain"
PARAGRAPHS_PER_FINDING = None

REASON_NO_CHAIN = "canonical_chain_unavailable"
REASON_UNSUPPORTED = "unsupported_article_page"
REASON_ROLE = "chain_member_role_not_body"
REASON_TARGET = "complete_chain_target_unavailable"
REASON_SLOT = "canonical_legal_slot_unavailable"
REASON_FIT = "existing_chain_fragment_does_not_fit"
REASON_OWNER = "chain_owner_mismatch"


@dataclass(frozen=True, slots=True)
class ChainPlacement:
    source_ref: str
    page: int
    paragraph_index: int
    slot_id: str
    box: tuple[float, float, float, float]
    text_start: int
    text_end: int
    text: str
    style: object
    measurement: dict


@dataclass(frozen=True, slots=True)
class ChainReallocationPlan:
    chain_id: str
    article_id: str
    request_id: str
    whole_target: str
    placements: tuple[ChainPlacement, ...]

    @property
    def touched_refs(self) -> tuple[str, ...]:
        return tuple(item.source_ref for item in self.placements)


def _chain_id(issue, article_document_ir) -> str | None:
    value = issue.evidence.get("chain_id")
    if isinstance(value, str) and value in article_document_ir.by_chain:
        return value
    candidates = {
        article_document_ir.by_chain_member.get(reference)
        for reference in (*issue.source_refs, *issue.paragraph_refs)
    }
    candidates.discard(None)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _chain(issue, context):
    article_document_ir = context.article_document_ir
    if article_document_ir is None:
        return None
    chain_id = _chain_id(issue, article_document_ir)
    if chain_id is None:
        return None
    return next(
        (item for item in article_document_ir.chains if item.chain_id == chain_id),
        None,
    )


def resolve_candidate(issue, pages_by_label: dict, context):
    chain = _chain(issue, context)
    if chain is None:
        return None
    first = chain.ordered_member_refs[0]
    page_number, paragraph_index = first[1:].split("#", 1)
    view = pages_by_label.get(int(page_number))
    if view is None or int(paragraph_index) >= len(view.page.pdf_paragraph or ()):
        return None
    paragraph = view.page.pdf_paragraph[int(paragraph_index)]
    return actions.Candidate(
        issue_id=issue.id,
        reference=first,
        page_index=view.label,
        paragraph_index=int(paragraph_index),
        paragraph=paragraph,
        page=view.page,
        source_text=article_flow.canonical_text(
            getattr(paragraph, "unicode", "") or ""
        ),
        issue=issue,
    )


def _preflight(issue, context):
    chain = _chain(issue, context)
    if chain is None:
        return REASON_NO_CHAIN, None
    article_document_ir = context.article_document_ir
    unsupported = {item.page for item in article_document_ir.unsupported_pages}
    if set(chain.member_physical_pages) & unsupported:
        return REASON_UNSUPPORTED, None
    if article_document_ir.by_chain.get(chain.chain_id) != chain.article_id:
        return REASON_OWNER, None
    article = article_document_ir.article(chain.article_id)
    if article is None:
        return REASON_OWNER, None
    elements = {item.source_ref: item for item in article.elements}
    if any(
        reference not in elements
        or elements[reference].role is not ElementRole.BODY
        for reference in chain.ordered_member_refs
    ):
        return REASON_ROLE, None
    if context.run_trace is None:
        return REASON_TARGET, None
    requests = [
        request
        for request in context.run_trace.requests.values()
        if tuple(request.ordered_source_refs) == chain.ordered_member_refs
        and request.status == REQUEST_COMPLETED
    ]
    if len(requests) != 1:
        return REASON_TARGET, None
    request = requests[0]
    try:
        target = context.run_trace.whole_target_text(request.request_id)
    except KeyError:
        return REASON_TARGET, None
    fragments = sorted(
        (
            context.run_trace.fragments[fragment_id]
            for fragment_id in request.fragment_ids
            if context.run_trace.fragments[fragment_id].active
        ),
        key=lambda item: (item.text_start, item.order),
    )
    reconstructed = "".join(
        context.run_trace.target_fragment_text(item.fragment_id)
        for item in fragments
    )
    if (
        target is None
        or canonical_text(reconstructed) != canonical_text(target)
        or tuple(item.source_ref for item in fragments)
        != chain.ordered_member_refs
    ):
        return REASON_TARGET, None
    if context.legal_slot_plan is None:
        return REASON_SLOT, None
    slots = []
    for reference in chain.ordered_member_refs:
        element = elements[reference]
        slot = slot_for_source_box(
            context.legal_slot_plan,
            article_id=chain.article_id,
            page=element.page,
            column=element.column,
            source_box=element.source_box,
        )
        if slot is None:
            return REASON_SLOT, None
        slots.append(slot)
    return actions.ACCEPTED, (chain, article, request, target, fragments, tuple(slots))


def admits(issue, _candidate, _action, context) -> str:
    return _preflight(issue, context)[0]


def plan(candidate, context, typesetter) -> ChainReallocationPlan:
    verdict, held = _preflight(candidate.issue, context)
    if verdict != actions.ACCEPTED or held is None:
        raise ValueError(verdict)
    chain, article, request, target, fragments, slots = held
    elements = {item.source_ref: item for item in article.elements}
    document_index = DocumentPageIndex(context.docs)
    fit_config = chain_backfill.load_backfill_config()
    placements = []
    for fragment, slot in zip(fragments, slots, strict=True):
        text = context.run_trace.target_fragment_text(fragment.fragment_id)
        element = elements[fragment.source_ref]
        page = document_index.page_by_source_number(element.page)
        paragraph_index = int(fragment.source_ref.rsplit("#", 1)[1])
        paragraph = page.pdf_paragraph[paragraph_index]
        style = writeback.paragraph_style(paragraph)
        if style is None or canonical_text(
            detector_base.rendered_text(paragraph)
        ) != canonical_text(text):
            raise ValueError(REASON_FIT)
        source_font = article_flow._source_font(page, paragraph, style, typesetter)
        result = typesetter.fit_text_to_slot(
            text,
            style,
            typesetter.translation_config.lang_out,
            Box(*slot.box),
            paragraph_start=bool(getattr(paragraph, "first_line_indent", False)),
            original_font=source_font,
            minimum_font_size=fit_config.slot_min_font_size,
            fit_tolerance=fit_config.slot_fit_tolerance,
            line_skip=(
                fit_config.capacity.line_skip_cjk
                if fit_config.capacity.is_cjk_target(
                    typesetter.translation_config.lang_out
                )
                else fit_config.capacity.line_skip_latin
            ),
            line_head_forbidden=fit_config.line_head_forbidden,
            line_tail_forbidden=fit_config.line_tail_forbidden,
        )
        if result.status in {"invalid", "none"} or result.consumed_range[1] != len(text):
            raise ValueError(REASON_FIT)
        measurement = result.to_record()
        measurement["request_target_range"] = [
            fragment.text_start,
            fragment.text_end,
        ]
        placements.append(
            ChainPlacement(
                source_ref=fragment.source_ref,
                page=slot.page,
                paragraph_index=paragraph_index,
                slot_id=slot.slot_id,
                box=tuple(float(value) for value in slot.box),
                text_start=fragment.text_start,
                text_end=fragment.text_end,
                text=text,
                style=style,
                measurement=measurement,
            )
        )
    if canonical_text("".join(item.text for item in placements)) != canonical_text(target):
        raise ValueError(REASON_TARGET)
    return ChainReallocationPlan(
        chain.chain_id,
        chain.article_id,
        request.request_id,
        target,
        tuple(placements),
    )


def apply_plan(docs, run_trace, generation: int, plan: ChainReallocationPlan) -> None:
    document_index = DocumentPageIndex(docs)
    allocations = []
    for placement in plan.placements:
        page = document_index.page_by_source_number(placement.page)
        paragraph = copy.deepcopy(page.pdf_paragraph[placement.paragraph_index])
        paragraph.box = Box(*placement.box)
        paragraph.unicode = placement.text
        paragraph.pdf_style = placement.style
        paragraph.pdf_paragraph_composition = article_flow._composition(
            placement.text, placement.style
        )
        paragraph.optimal_scale = None
        paragraph.scale = None
        page.pdf_paragraph[placement.paragraph_index] = paragraph
        allocations.append(
            {
                "source_ref": placement.source_ref,
                "text_start": placement.text_start,
                "text_end": placement.text_end,
                "text": placement.text,
                "slot_id": placement.slot_id,
                "render_ref": placement.source_ref,
                "render_page": placement.page,
                "measurement_summary": placement.measurement,
            }
        )
    run_trace.replace_request_fragments(generation, plan.request_id, allocations)
    run_trace.validate()
