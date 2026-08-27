"""Bounded article-flow transactions across canonical adjacent pages."""

from __future__ import annotations

import copy
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import dataclass

from babeldoc.format.pdf.document_il.il_version_1 import Box
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import article_flow
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.page_identity import DocumentPageIndex
from babeldoc.magazine.run_trace import hash_record
from babeldoc.magazine.run_trace import parse_source_ref
from babeldoc.magazine.transaction import TransactionSnapshot

ISSUE_CAPACITY_EXHAUSTION = "capacity_exhaustion"
ISSUE_HARD_BOUNDARY = "hard_boundary"
ISSUE_PAGE_OWNERSHIP_CONFLICT = "page_ownership_conflict"

BOUNDARY_NON_ADJACENT = "non_adjacent_pages"
BOUNDARY_READING_ORDER = "article_reading_order_discontinuity"
BOUNDARY_POLICY = "article_reflow_not_allowed"
BOUNDARY_UNSUPPORTED = "unsupported_page"
BOUNDARY_SOURCE_GEOMETRY = "source_geometry_unavailable"
BOUNDARY_ASSET_INVENTORY = "fixed_asset_inventory_unavailable"
BOUNDARY_PROTECTED = "protected_in_page_boundary"
BOUNDARY_NO_SLOT = "no_eligible_boundary_slot"

GUARD_PAGE_GEOMETRY = "page_geometry_conservation"


@dataclass(frozen=True, slots=True)
class CrossPageFlowIssue:
    """One typed reason a candidate cross-page flow was blocked or reverted."""

    code: str
    article_id: str
    pages: tuple[int, ...]
    detail: str

    def __post_init__(self) -> None:
        if self.code not in {
            ISSUE_CAPACITY_EXHAUSTION,
            ISSUE_HARD_BOUNDARY,
            ISSUE_PAGE_OWNERSHIP_CONFLICT,
        }:
            raise ValueError(f"unknown cross-page flow issue: {self.code}")
        if not self.article_id or not self.pages or not self.detail:
            raise ValueError("cross-page flow issues require identity and evidence")
        if self.pages != tuple(sorted(self.pages)) or any(
            page <= 0 for page in self.pages
        ):
            raise ValueError("cross-page flow issue pages must be positive and ordered")

    def to_record(self) -> dict:
        return {
            "code": self.code,
            "article_id": self.article_id,
            "pages": list(self.pages),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class CrossPageArticleFlowSegment:
    """One atomic article flow spanning one or more contiguous pages."""

    segment_id: str
    article_id: str
    contiguous_pages: tuple[int, ...]
    ordered_page_column_slots: tuple[article_flow.ArticleFlowSlot, ...]
    page_segments: tuple[article_flow.ArticleFlowSegment, ...]
    hard_boundaries: tuple[CrossPageFlowIssue, ...]
    touched_source_refs: tuple[str, ...]
    touched_fragment_ids: tuple[str, ...]
    touched_asset_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.contiguous_pages:
            raise ValueError("cross-page segment requires at least one page")
        if not self.page_segments or not self.ordered_page_column_slots:
            raise ValueError("cross-page segment requires source and slot coverage")
        expected_pages = tuple(
            range(self.contiguous_pages[0], self.contiguous_pages[-1] + 1)
        )
        if self.contiguous_pages != expected_pages:
            raise ValueError("cross-page segment pages must be contiguous")
        if any(
            slot.article_id != self.article_id
            or slot.page not in self.contiguous_pages
            for slot in self.ordered_page_column_slots
        ):
            raise ValueError("cross-page slots must belong to their segment")
        if tuple(segment.page for segment in self.page_segments) != tuple(
            sorted(segment.page for segment in self.page_segments)
        ):
            raise ValueError("cross-page page segments must be monotonic")
        expected_sources = tuple(
            dict.fromkeys(
                reference
                for segment in self.page_segments
                for reference in segment.ordered_source_refs
            )
        )
        expected_fragments = tuple(
            dict.fromkeys(
                boundary.fragment_id
                for segment in self.page_segments
                for boundary in segment.boundaries
            )
        )
        if (
            self.touched_source_refs != expected_sources
            or self.touched_fragment_ids != expected_fragments
        ):
            raise ValueError("cross-page touched text must exactly match its plan")
        if self.touched_asset_refs != tuple(sorted(set(self.touched_asset_refs))):
            raise ValueError("cross-page touched assets must be unique and stable")

    @property
    def page(self) -> int:
        return self.contiguous_pages[0]

    @property
    def ordered_slots(self) -> tuple[article_flow.ArticleFlowSlot, ...]:
        return self.ordered_page_column_slots

    @property
    def boundaries(self) -> tuple[article_flow.ParagraphBoundaryToken, ...]:
        return tuple(
            boundary
            for segment in self.page_segments
            for boundary in segment.boundaries
        )

    def to_record(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "article_id": self.article_id,
            "contiguous_pages": list(self.contiguous_pages),
            "ordered_page_column_slots": [
                slot.to_record() for slot in self.ordered_page_column_slots
            ],
            "page_segments": [segment.to_record() for segment in self.page_segments],
            "hard_boundaries": [item.to_record() for item in self.hard_boundaries],
            "touched_sources": list(self.touched_source_refs),
            "touched_fragments": list(self.touched_fragment_ids),
            "touched_assets": list(self.touched_asset_refs),
        }


def _issue(code: str, article_id: str, pages, detail: str) -> CrossPageFlowIssue:
    return CrossPageFlowIssue(code, article_id, tuple(pages), detail)


def _page_policy(article, page: int):
    return next((item for item in article.policy_evidence if item.page == page), None)


def _page_inventory(inventory, page: int):
    return next((item for item in inventory.page_sizes if item[0] == page), None)


def page_connection_issue(
    article_document_ir,
    article,
    left_page: int,
    right_page: int,
    inventory,
) -> CrossPageFlowIssue | None:
    """Return the first canonical reason two page endpoints cannot connect."""
    pages = (left_page, right_page)
    if right_page != left_page + 1:
        return _issue(
            ISSUE_HARD_BOUNDARY,
            article.article_id,
            pages,
            BOUNDARY_NON_ADJACENT,
        )
    owners = (
        article_document_ir.by_page.get(left_page),
        article_document_ir.by_page.get(right_page),
    )
    if owners != (article.article_id, article.article_id):
        return _issue(
            ISSUE_PAGE_OWNERSHIP_CONFLICT,
            article.article_id,
            pages,
            f"owners={owners!r}",
        )
    unsupported = {item.page for item in article_document_ir.unsupported_pages}
    if left_page in unsupported or right_page in unsupported:
        return _issue(
            ISSUE_HARD_BOUNDARY,
            article.article_id,
            pages,
            BOUNDARY_UNSUPPORTED,
        )
    policies = (_page_policy(article, left_page), _page_policy(article, right_page))
    if any(item is None or not item.article_reflow_allowed for item in policies):
        return _issue(
            ISSUE_HARD_BOUNDARY,
            article.article_id,
            pages,
            BOUNDARY_POLICY,
        )
    ordered = tuple(article.elements)
    left_indices = [
        index for index, item in enumerate(ordered) if item.page == left_page
    ]
    right_indices = [
        index for index, item in enumerate(ordered) if item.page == right_page
    ]
    if (
        not left_indices
        or not right_indices
        or max(left_indices) + 1 != min(right_indices)
        or ordered[min(right_indices)].reading_order
        != ordered[max(left_indices)].reading_order + 1
    ):
        return _issue(
            ISSUE_HARD_BOUNDARY,
            article.article_id,
            pages,
            BOUNDARY_READING_ORDER,
        )
    page_elements = [item for item in ordered if item.page in pages]
    ordered_slots = tuple(article.slots)
    page_slots = [item for item in ordered_slots if item.page in pages]
    left_slot_indices = [
        index for index, item in enumerate(ordered_slots) if item.page == left_page
    ]
    right_slot_indices = [
        index for index, item in enumerate(ordered_slots) if item.page == right_page
    ]
    if (
        any(item.source_box is None for item in page_elements)
        or {item.page for item in page_slots} != set(pages)
        or max(left_slot_indices) + 1 != min(right_slot_indices)
        or [slot.slot_order for slot in page_slots]
        != sorted({slot.slot_order for slot in page_slots})
        or any(
            slot.box[2] <= slot.box[0] or slot.box[3] <= slot.box[1]
            for slot in page_slots
        )
    ):
        return _issue(
            ISSUE_HARD_BOUNDARY,
            article.article_id,
            pages,
            BOUNDARY_SOURCE_GEOMETRY,
        )
    inventory_rows = (
        _page_inventory(inventory, left_page),
        _page_inventory(inventory, right_page),
    )
    expected_assets = {
        reference for slot in page_slots for reference in slot.fixed_obstacle_refs
    }
    if (
        any(
            row is None or (row[1] is None and row[2] is None)
            for row in inventory_rows
        )
        or not expected_assets.issubset(inventory.by_ref)
    ):
        return _issue(
            ISSUE_HARD_BOUNDARY,
            article.article_id,
            pages,
            BOUNDARY_ASSET_INVENTORY,
        )
    return None


def _cross_segment(local_segments, hard_boundaries, inventory):
    pages = tuple(dict.fromkeys(segment.page for segment in local_segments))
    material = {
        "article_id": local_segments[0].article_id,
        "pages": list(pages),
        "segments": [segment.segment_id for segment in local_segments],
    }
    return CrossPageArticleFlowSegment(
        segment_id=f"cross-page-article-flow-{hash_record(material)}",
        article_id=local_segments[0].article_id,
        contiguous_pages=pages,
        ordered_page_column_slots=tuple(
            slot for segment in local_segments for slot in segment.ordered_slots
        ),
        page_segments=tuple(local_segments),
        hard_boundaries=tuple(hard_boundaries),
        touched_source_refs=tuple(
            dict.fromkeys(
                reference
                for segment in local_segments
                for reference in segment.ordered_source_refs
            )
        ),
        touched_fragment_ids=tuple(
            dict.fromkeys(
                boundary.fragment_id
                for segment in local_segments
                for boundary in segment.boundaries
            )
        ),
        touched_asset_refs=tuple(
            sorted(
                asset.reference
                for page in pages
                for asset in inventory.page_assets(page)
            )
        ),
    )


def build_cross_page_segments(
    docs,
    article_document_ir,
    run_trace,
    inventory,
    config: article_flow.ArticleFlowConfig,
    typesetter: Typesetting,
    protected_refs=frozenset(),
) -> tuple[tuple[CrossPageArticleFlowSegment, ...], tuple[CrossPageFlowIssue, ...]]:
    """Build a read-only cross-page plan from the canonical article state."""
    unsupported = {item.page for item in article_document_ir.unsupported_pages}
    selection = article_document_ir.page_selection_map
    selected_pages = (
        set(article_document_ir.by_page)
        if selection is None
        else {int(page) for page in selection.translation_selected_physical_pages}
    )
    all_segments = []
    issues = []
    ordered_pages = sorted(set(article_document_ir.by_page) & selected_pages)
    for left_page, right_page in zip(ordered_pages, ordered_pages[1:], strict=False):
        if right_page != left_page + 1:
            continue
        left_owner = article_document_ir.by_page[left_page]
        right_owner = article_document_ir.by_page[right_page]
        if left_owner != right_owner:
            issues.append(
                _issue(
                    ISSUE_PAGE_OWNERSHIP_CONFLICT,
                    left_owner,
                    (left_page, right_page),
                    f"owners={(left_owner, right_owner)!r}",
                )
            )
    for article in article_document_ir.articles:
        by_page = {}
        article_pages = tuple(page for page in article.pages if page in selected_pages)
        for page in article_pages:
            by_page[page] = (
                ()
                if page in unsupported
                else article_flow.build_page_segments(
                    docs,
                    article,
                    page,
                    run_trace,
                    inventory,
                    config,
                    typesetter,
                    protected_refs,
                )
            )
            for left, right in zip(by_page[page], by_page[page][1:], strict=False):
                issues.append(
                    _issue(
                        ISSUE_HARD_BOUNDARY,
                        article.article_id,
                        (page, page),
                        f"{BOUNDARY_PROTECTED}:{left.segment_id}:{right.segment_id}",
                    )
                )
        groups = [[segment] for page in article_pages for segment in by_page[page]]
        for left_page, right_page in zip(
            article_pages, article_pages[1:], strict=False
        ):
            connection = page_connection_issue(
                article_document_ir,
                article,
                left_page,
                right_page,
                inventory,
            )
            left_segments = by_page[left_page]
            right_segments = by_page[right_page]
            if connection is None and (not left_segments or not right_segments):
                connection = _issue(
                    ISSUE_HARD_BOUNDARY,
                    article.article_id,
                    (left_page, right_page),
                    BOUNDARY_NO_SLOT,
                )
            if connection is not None:
                issues.append(connection)
                continue
            left = left_segments[-1]
            right = right_segments[0]
            left_group = next(
                index for index, group in enumerate(groups) if left in group
            )
            right_group = next(
                index for index, group in enumerate(groups) if right in group
            )
            if left_group != right_group:
                groups[left_group].extend(groups.pop(right_group))
        for group in groups:
            pages = {segment.page for segment in group}
            boundaries = [
                issue for issue in issues if pages.intersection(issue.pages)
            ]
            all_segments.append(_cross_segment(group, boundaries, inventory))
    unique = {
        hash_record(issue.to_record()): issue for issue in issues
    }
    return tuple(all_segments), tuple(unique[key] for key in sorted(unique))


def _write_segment(docs, segment, placements):
    assigned = []
    released = []
    page_index = DocumentPageIndex(docs)
    for page_number in segment.contiguous_pages:
        page = page_index.page_by_source_number(page_number)
        holders = list(
            dict.fromkeys(
                reference
                for local in segment.page_segments
                if local.page == page_number
                for reference in local.ordered_source_refs
            )
        )
        page_placements = [item for item in placements if item.page == page_number]
        for index, placement in enumerate(page_placements):
            if index < len(holders):
                render_ref = holders[index]
                _page, paragraph_index = parse_source_ref(render_ref)
            else:
                paragraph_index = len(page.pdf_paragraph)
                render_ref = f"p{page_number}#{paragraph_index}"
                page.pdf_paragraph.append(copy.deepcopy(placement.source_paragraph))
            paragraph = copy.deepcopy(placement.source_paragraph)
            paragraph.box = Box(*placement.box)
            paragraph.unicode = placement.text
            paragraph.pdf_style = placement.style
            paragraph.pdf_paragraph_composition = article_flow._composition(
                placement.text, placement.style
            )
            paragraph.first_line_indent = placement.first_line_indent
            paragraph.optimal_scale = None
            paragraph.scale = None
            page.pdf_paragraph[paragraph_index] = paragraph
            assigned.append(placement.with_render_ref(render_ref))
        for render_ref in holders[len(page_placements) :]:
            _page, paragraph_index = parse_source_ref(render_ref)
            paragraph = copy.deepcopy(page.pdf_paragraph[paragraph_index])
            paragraph.unicode = ""
            paragraph.pdf_paragraph_composition = []
            page.pdf_paragraph[paragraph_index] = paragraph
            released.append(render_ref)
    return tuple(assigned), tuple(released)


def _paragraph(docs, reference: str):
    page, index = parse_source_ref(reference)
    return DocumentPageIndex(docs).page_by_source_number(page).pdf_paragraph[index]


def _page_shell_digest(page) -> str:
    shell = copy.deepcopy(page)
    shell.pdf_paragraph = []
    return fixed_assets.content_digest(shell)


def _document_invariants(docs) -> tuple:
    return (
        len(docs.page),
        getattr(docs, "total_pages", None),
        tuple(
            (
                getattr(page, "page_number", None),
                getattr(page, "rotation", None),
                getattr(page, "page_label", None),
                _page_shell_digest(page),
            )
            for page in docs.page
        ),
    )


def _validate_ranges(segment, placements) -> list[str]:
    issues = []
    for boundary in segment.boundaries:
        pieces = sorted(
            (
                item
                for item in placements
                if item.old_fragment_id == boundary.fragment_id
            ),
            key=lambda item: item.target_start,
        )
        cursor = boundary.target_start
        text = []
        for piece in pieces:
            if piece.target_start != cursor or piece.target_end <= piece.target_start:
                issues.append(article_flow.GUARD_CONSERVATION)
                break
            cursor = piece.target_end
            text.append(piece.text)
        if cursor != boundary.target_end or "".join(text) != boundary.text:
            issues.append(article_flow.GUARD_CONSERVATION)
    destinations = [
        (item.page, item.column, item.slot_order, item.target_start)
        for item in placements
    ]
    if destinations != sorted(destinations):
        issues.append(article_flow.GUARD_OWNERSHIP)
    return sorted(set(issues))


def _segment_page_records(segment, result):
    records = {}
    placements = result.get("placements", ())
    released = result.get("released_holders", ())
    for page in segment.contiguous_pages:
        records[page] = {
            "page": page,
            "article_id": segment.article_id,
            "status": result["status"],
            "action_status": result.get("action_status", "not_executed"),
            "reason": result.get("reason"),
            "detail": result.get("detail"),
            "segments": [
                local.to_record()
                for local in segment.page_segments
                if local.page == page
            ],
            "placements": [item for item in placements if item["page"] == page],
            "released_holders": [
                reference
                for reference in released
                if parse_source_ref(reference)[0] == page
            ],
            "transaction": result.get("transaction"),
        }
        if "acceptance" in result:
            records[page]["acceptance"] = result["acceptance"]
        if "fixed_asset_comparison" in result:
            records[page]["fixed_asset_comparison"] = result[
                "fixed_asset_comparison"
            ]
    return records


def _merge_page_records(target, incoming) -> None:
    for page, record in incoming.items():
        if page not in target:
            target[page] = record
            continue
        held = target[page]
        held["segments"].extend(record["segments"])
        held["placements"].extend(record["placements"])
        held["released_holders"].extend(record["released_holders"])
        if record["status"] == "rolled_back":
            held["status"] = "rolled_back"
            held["action_status"] = record.get("action_status", "rolled_back")
            held["reason"] = record.get("reason")
        details = [item for item in (held.get("detail"), record.get("detail")) if item]
        held["detail"] = "; ".join(dict.fromkeys(details)) or None
        if "fixed_asset_comparison" in record:
            held["fixed_asset_comparison"] = record["fixed_asset_comparison"]


def apply(
    translator,
    docs,
    article_document_ir,
    run_trace,
    *,
    typesetter: Typesetting | None = None,
    validator: Callable[[object, dict], Sequence[str]] | None = None,
    config: article_flow.ArticleFlowConfig | None = None,
) -> dict | None:
    """Apply each cross-page segment as one document and trace transaction."""
    if not article_flow.enabled(translator.translation_config):
        return None
    config = article_flow.load_flow_config() if config is None else config
    typesetter = typesetter or Typesetting(
        translator.translation_config,
        font_mapper=getattr(translator, "font_mapper", None),
    )
    protected_labels = {
        element.raw_layout_label
        for article in article_document_ir.articles
        for element in article.elements
        if not config.eligible(element.role)
        and element.raw_layout_label is not None
    }
    inventory = fixed_assets.build_inventory(
        docs,
        protected_paragraph_labels=tuple(sorted(protected_labels)),
    )
    protected_refs = drop_cap_intent.active_protected_refs(
        translator.translation_config
    )
    segments, boundary_issues = build_cross_page_segments(
        docs,
        article_document_ir,
        run_trace,
        inventory,
        config,
        typesetter,
        protected_refs,
    )
    issues = list(boundary_issues)
    for issue in boundary_issues:
        run_trace.record_blocked_reason(issue.to_record())
    segment_results = []
    page_results = {}
    for segment in segments:
        try:
            planned = article_flow.allocate_segment(segment, typesetter, config)
        except article_flow.ArticleFlowError as error:
            issue = _issue(
                ISSUE_CAPACITY_EXHAUSTION,
                segment.article_id,
                segment.contiguous_pages,
                str(error),
            )
            issues.append(issue)
            run_trace.record_blocked_reason(issue.to_record())
            result = {
                **segment.to_record(),
                "status": "rolled_back",
                "action_status": "not_executed",
                "reason": ISSUE_CAPACITY_EXHAUSTION,
                "detail": str(error),
                "placements": [],
                "released_holders": [],
                "transaction": {
                    "status": "not_executed",
                    "pages": list(segment.contiguous_pages),
                },
            }
            segment_results.append(result)
            _merge_page_records(page_results, _segment_page_records(segment, result))
            continue
        invariants = _document_invariants(docs)
        protected_refs = {
            item.reference
            for local in segment.page_segments
            for item in local.protected_elements
            if item.reference.startswith("p")
            and "#" in item.reference
            and ":" not in item.reference
        }
        protected_digests = {
            reference: fixed_assets.content_digest(_paragraph(docs, reference))
            for reference in protected_refs
        }

        def inventory_builder():
            return fixed_assets.build_inventory(
                docs,
                protected_paragraph_labels=tuple(sorted(protected_labels)),
            )

        page_index = DocumentPageIndex(docs)
        transaction = TransactionSnapshot.capture(
            docs,
            (
                page_index.structural_position_of(page)
                for page in segment.contiguous_pages
            ),
            run_trace=run_trace,
            fixed_inventory=inventory,
            fixed_inventory_builder=inventory_builder,
        )
        generation = transaction.begin_generation(
            f"cross_page_article_flow:{segment.article_id}:"
            f"p{segment.contiguous_pages[0]}-p{segment.contiguous_pages[-1]}"
        )
        found = []
        monotonic = None
        failure_stage = article_flow.GUARD_ACTION
        try:
            placements, released_holders = _write_segment(docs, segment, planned)
            failure_stage = article_flow.GUARD_CONSERVATION
            found = _validate_ranges(segment, placements)
            for page in segment.contiguous_pages:
                local_segments = tuple(
                    item for item in segment.page_segments if item.page == page
                )
                page_placements = tuple(
                    item for item in placements if item.page == page
                )
                found.extend(
                    article_flow._validate_page(
                        docs,
                        article_document_ir.article(segment.article_id),
                        page,
                        local_segments,
                        page_placements,
                        {
                            reference: digest
                            for reference, digest in protected_digests.items()
                            if parse_source_ref(reference)[0] == page
                        },
                        validate_conservation=False,
                    )
                )
            failure_stage = article_flow.GUARD_FIXED_ASSET
            candidate_inventory = inventory_builder()
            comparison = fixed_assets.compare(
                inventory,
                candidate_inventory,
                config.asset_bbox_tolerance_pt,
            )
            if not comparison.holds:
                found.append(article_flow.GUARD_FIXED_ASSET)
            if _document_invariants(docs) != invariants:
                found.append(GUARD_PAGE_GEOMETRY)
            provisional = {
                "segment": segment.to_record(),
                "placements": [item.to_record() for item in placements],
            }
            if validator is not None:
                for page in segment.contiguous_pages:
                    detected = [
                        str(item)
                        for item in validator(
                            page_index.page_by_source_number(page), provisional
                        )
                    ]
                    if detected:
                        found.extend(f"p{page}:{item}" for item in detected)
                        found.append(article_flow.GUARD_DETECTOR)
            failure_stage = article_flow.GUARD_ACCEPTANCE
            monotonic = article_flow.compare_flow(
                segment.article_id,
                segment.contiguous_pages,
                segment.page_segments,
                found,
            )
            provisional["acceptance"] = monotonic.as_record()
            if not monotonic.accepted:
                raise article_flow.ArticleFlowError(", ".join(sorted(set(found))))
            failure_stage = article_flow.GUARD_TRACE
            for request_id, rows in article_flow._request_replacements(
                run_trace, placements
            ).items():
                run_trace.replace_request_fragments(generation, request_id, rows)
            for placement in placements:
                run_trace.record_flow_slot(
                    generation,
                    slot_id=placement.slot_id,
                    article_id=segment.article_id,
                    page=placement.page,
                    status=article_flow.STATUS_ALLOCATED,
                    box=placement.box,
                    source_ref=placement.source_ref,
                    render_ref=placement.render_ref,
                    previous_page=placement.previous_page,
                    previous_slot_id=placement.previous_slot_id,
                )
            for slot_id, article_id, box in article_flow._released_regions(
                segment.page_segments, placements
            ):
                page = next(
                    slot.page
                    for slot in segment.ordered_slots
                    if f"{slot.slot_id}:released" == slot_id
                )
                run_trace.record_flow_slot(
                    generation,
                    slot_id=slot_id,
                    article_id=article_id,
                    page=page,
                    status=article_flow.STATUS_RELEASED,
                    box=box,
                    reason="unused_cross_page_capacity",
                )
            for render_ref in released_holders:
                page, _index = parse_source_ref(render_ref)
                holder_slot_id = "article-flow-holder-" + hash_record(
                    {"render_ref": render_ref, "generation": generation}
                )
                run_trace.record_flow_slot(
                    generation,
                    slot_id=holder_slot_id,
                    article_id=segment.article_id,
                    page=page,
                    status=article_flow.STATUS_RELEASED,
                    box=article_flow._box_tuple(_paragraph(docs, render_ref).box),
                    render_ref=render_ref,
                    reason="released_paragraph_holder",
                )
            protected = {
                item.reference: item
                for local in segment.page_segments
                for item in local.protected_elements
            }
            for item in protected.values():
                page = (
                    parse_source_ref(item.reference)[0]
                    if item.reference.startswith("p")
                    and "#" in item.reference
                    and ":" not in item.reference
                    else next(
                        asset.page
                        for asset in inventory.assets
                        if asset.reference == item.reference
                    )
                )
                protected_slot_id = "article-flow-protected-" + hash_record(
                    {
                        "reference": item.reference,
                        "page": page,
                        "generation": generation,
                    }
                )
                run_trace.record_flow_slot(
                    generation,
                    slot_id=protected_slot_id,
                    article_id=segment.article_id,
                    page=page,
                    status=article_flow.STATUS_PROTECTED,
                    box=item.box,
                    source_ref=(
                        item.reference if item.reference in run_trace.sources else None
                    ),
                    reason=item.reason,
                )
            run_trace.validate()
            transaction_record = transaction.commit(
                (item.render_ref for item in placements if item.render_ref),
                capture_geometry=False,
            )
            inventory = candidate_inventory
            result = {
                **segment.to_record(),
                "status": "applied",
                "action_status": "committed",
                "reason": None,
                "placements": [item.to_record() for item in placements],
                "released_holders": list(released_holders),
                "fixed_asset_comparison": comparison.to_record(),
                "acceptance": monotonic.as_record(),
                "transaction": transaction_record,
            }
        except Exception as error:
            transaction_record = transaction.rollback()
            result = {
                **segment.to_record(),
                "status": "rolled_back",
                "action_status": "rolled_back",
                "reason": failure_stage,
                "failure_stage": failure_stage,
                "detail": str(error),
                "placements": [],
                "released_holders": [],
                "transaction": transaction_record,
            }
            if monotonic is not None:
                result["acceptance"] = monotonic.as_record()
        segment_results.append(result)
        _merge_page_records(page_results, _segment_page_records(segment, result))
    unsupported = {item.page for item in article_document_ir.unsupported_pages}
    selection = article_document_ir.page_selection_map
    selected_pages = (
        set(article_document_ir.by_page)
        if selection is None
        else {int(page) for page in selection.translation_selected_physical_pages}
    )
    page_records = []
    for page in sorted(article_document_ir.by_page):
        if page not in selected_pages:
            continue
        if page in page_results:
            page_records.append(page_results[page])
        else:
            article_id = article_document_ir.by_page[page]
            page_records.append(
                {
                    "page": page,
                    "article_id": article_id,
                    "status": "skipped",
                    "action_status": "not_executed",
                    "reason": (
                        article_flow.SKIP_UNSUPPORTED
                        if page in unsupported
                        else article_flow.SKIP_NO_SEGMENT
                    ),
                    "segments": [],
                    "placements": [],
                }
            )
    record = {
        "switch": article_flow.SWITCH,
        "eligible_roles": [role.value for role in config.eligible_roles],
        "cross_page_segments": segment_results,
        "issues": [item.to_record() for item in issues],
        "pages": page_records,
        "totals": {
            "segments_considered": len(segment_results),
            "segments_applied": sum(
                item["status"] == "applied" for item in segment_results
            ),
            "segments_rolled_back": sum(
                item["status"] == "rolled_back" for item in segment_results
            ),
            "pages_considered": len(page_records),
            "pages_applied": sum(item["status"] == "applied" for item in page_records),
            "pages_rolled_back": sum(
                item["status"] == "rolled_back" for item in page_records
            ),
            "pages_skipped": sum(item["status"] == "skipped" for item in page_records),
            "placements": sum(
                len(item.get("placements", ())) for item in segment_results
            ),
            "cross_page_movements": sum(
                placement["movement"]["before"]["page"] != placement["page"]
                for item in segment_results
                for placement in item.get("placements", ())
            ),
        },
    }
    article_flow._write_report(translator.translation_config, record)
    return record
