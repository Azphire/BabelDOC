"""A box an article owns that its translated text no longer comes near filling.

Translating a paragraph changes how much room its text needs, and the box the
layout stage measured for the source does not move with it. Where the
translation runs short the box stays the size the source asked for and the
difference is printed as blank paper in the middle of an article.

What counts as the text's own size is the ink, not the box: the union extent of
the characters the paragraph was actually laid out as. A paragraph whose ink
fills less than its declared share of its own box, and whose unfilled remainder
is a large enough part of the page to be seen as a hole rather than as leading,
is reported here.

Two exclusions keep the measurement about the defect rather than about the
design. A paragraph no article owns is furniture and is not measured -- neither
is one the fixed inventory holds as protected, which is the same question the
rest of the pipeline already asks about what may be touched. And the last
member an article has on a page is never measured: an article stops where it
stops, and the short paragraph it stops on is the layout working correctly. The
exclusion is taken per page rather than per article because a member ending at
a page or column break is the one place a run of body text is legitimately
allowed to stop short of its box.

Report only. Nothing here writes to the document.
"""

from __future__ import annotations

from babeldoc.magazine.detectors import base

NAME = "abnormal_blank"
KIND = "abnormal_blank"

REQUIRES_TRANSLATION = True
REQUIRES_SOURCE_GEOMETRY = True
REQUIRES_ARTICLE_IR = True

# Why a run measured nothing, where that is a fact about the run rather than a
# verdict about the document.
SKIP_NOT_TRANSLATED = "translation_not_performed"
SKIP_NO_ARTICLE_IR = "article_ir_absent"
SKIP_NO_SOURCE_GEOMETRY = "source_geometry_absent"


def _area(box) -> float:
    if box is None:
        return 0.0
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _elements_by_ref(article_document_ir) -> dict[str, object]:
    """Every article member, under the local reference it is named by."""
    return {
        element.source_ref: element
        for article in article_document_ir.articles
        for element in article.elements
    }


def _last_member_on_page(article_document_ir) -> dict[tuple[str, int], str]:
    """The last member each article has on each page, in reading order."""
    last: dict[tuple[str, int], tuple[int, str]] = {}
    for article in article_document_ir.articles:
        for element in article.elements:
            key = (article.article_id, element.page)
            current = last.get(key)
            if current is None or element.reading_order > current[0]:
                last[key] = (element.reading_order, element.source_ref)
    return {key: reference for key, (_order, reference) in last.items()}


def _skip(context, reason: str) -> list:
    context.file(NAME, {"status": "skipped", "reason": reason, "typed": True})
    return []


def detect(context: base.DetectionContext) -> list[base.Issue]:
    if not context.translation_performed:
        return _skip(context, SKIP_NOT_TRANSLATED)
    article_document_ir = context.article_document_ir
    if article_document_ir is None:
        return _skip(context, SKIP_NO_ARTICLE_IR)
    source_geometry = context.source_geometry
    if source_geometry is None:
        return _skip(context, SKIP_NO_SOURCE_GEOMETRY)

    config = context.config
    elements = _elements_by_ref(article_document_ir)
    last_on_page = _last_member_on_page(article_document_ir)
    protected = (
        frozenset()
        if context.fixed_inventory is None
        else context.fixed_inventory.protected_paragraph_refs
    )

    found: list[base.Issue] = []
    for view in context.pages:
        frame = base.page_frame(view.page)
        if frame is None:
            continue
        page_area = _area(frame[0])
        if page_area <= 0:
            continue
        for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
            reference = view.reference(index)
            local_ref = source_geometry.local_ref(reference)
            if local_ref is None or local_ref in protected:
                continue
            article_id = article_document_ir.by_element.get(local_ref)
            element = elements.get(local_ref)
            if article_id is None or element is None:
                continue
            if last_on_page.get((article_id, element.page)) == local_ref:
                continue
            box = base.box_tuple(paragraph.box)
            box_area = _area(box)
            if box_area <= 0:
                continue
            ink, route = base.rendered_box(paragraph)
            # A paragraph with no laid out character falls back to its own box,
            # which would measure as perfectly filled and say nothing. There is
            # no ink to compare, so there is no finding to make.
            if ink is None or route != base.BOX_FROM_CHARACTERS:
                continue
            ink_area = _area(ink)
            fill_ratio = ink_area / box_area
            if fill_ratio >= config.abnormal_blank_min_capacity_ratio:
                continue
            blank_area_ratio = (box_area - ink_area) / page_area
            if blank_area_ratio < config.abnormal_blank_min_area_ratio:
                continue
            found.append(
                base.Issue(
                    kind=KIND,
                    page=view.label,
                    paragraph_refs=(reference,),
                    geometry=base.union_box([box]),
                    severity=context.severity_of(KIND),
                    evidence={
                        # Both declared dimensions count blank, not fill, so
                        # that a smaller number is always the better document.
                        "blank_area_ratio": round(blank_area_ratio, 6),
                        "blank_capacity_ratio": round(1.0 - fill_ratio, 6),
                        "fill_ratio": round(fill_ratio, 6),
                        "min_area_ratio": config.abnormal_blank_min_area_ratio,
                        "min_capacity_ratio": (
                            config.abnormal_blank_min_capacity_ratio
                        ),
                        "box": list(box),
                        "ink_box": list(ink),
                        "box_area": round(box_area, 4),
                        "ink_area": round(ink_area, 4),
                        "page_area": round(page_area, 4),
                        "article_id": article_id,
                        "reading_order": element.reading_order,
                        "role": element.role,
                        "debug_id": paragraph.debug_id,
                        "layout_label": paragraph.layout_label,
                        "violation_count": 1,
                        "identity_ref": local_ref,
                    },
                    detector=NAME,
                    detected_at_iteration=context.iteration,
                    article_refs=(article_id,),
                    source_refs=(local_ref,),
                )
            )
    return found
