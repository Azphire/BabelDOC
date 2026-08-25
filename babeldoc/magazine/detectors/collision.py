"""Two blocks of text standing in the same place, where the source had one.

A translated paragraph is laid out into the box its source occupied, and if the
translation needs more room than the source took, the stage widens or deepens
that box into whatever is beside it. The paragraph beside it was laid out from
its own box and did not move. What the reader receives is two texts printed over
each other.

Two measures, and a pair needs only one
---------------------------------------

The first is the intersection of the two rendered extents over their union, the
same quantity the artwork overlap detector uses and the same one the layout
parser assigns characters with. It answers well for two blocks of comparable
size drifting into each other and badly for everything else, because it divides
by an area neither box occupies alone. A folio printed inside the entry it
numbers, a dropped initial standing in the column beside it, a strap set across
a headline: each is a small box wholly inside a large one, sharing the whole of
its own area and a few percent of the area the two cover together. Over this
corpus that is the common shape, and the ratio over the union reports it as
nothing.

The second measure divides the shared area by the area of the smaller box, so a
box standing wholly inside another reports one however small it is. A pair is a
candidate at or above either bound rather than at or above both: they answer for
different shapes of overlap, and requiring both would find only the overlaps
that are obvious either way.

Why the source is consulted
---------------------------

Because neither measure alone can tell a defect from a design. A magazine prints
text over text on purpose and often: a display headline painted twice, once
solid and once in a texture layer, is two paragraphs at the same place; a strap
band set across the foot of a montage sits inside the block above it; a folio is
printed inside the entry it numbers. Every one of those is an overlap the source
already had, and a detector reporting it is reporting the designer's decision as
a fault.

So a pair is a finding only where the same two paragraphs did not already
overlap in the document as it stood before anything was translated. That
document is the source layout checkpoint, and the pair's members are found in it
by the id they have carried since the paragraph finder minted it. A pair either
of whose members has no counterpart there is not reported at all: without both
source boxes there is nothing to compare, and an unsupported claim that the
translation caused an overlap is worse than no claim.

The exemption reads both measures for the same reason the candidacy does, and
which of them exempted a pair is filed rather than folded into a count. Widening
the candidate bound moves pairs between routes as well as into and out of the
finding set: a pair that used to fall short of candidacy and is now a candidate
the source exempts reaches the verdict it always reached along a path it did not
use before. A census that records only the verdict cannot show that, and showing
it is how a change to a bound is argued to have preserved what it should.
"""

from __future__ import annotations

from babeldoc.magazine.detectors import base

NAME = "text_text_collision"
KIND = "text_text_collision"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = True

# Why a pair on the page produced no finding. Counted rather than dropped, so
# the sidecar says how much of the page the comparison could answer for.
SKIPPED_NO_SOURCE = "member_has_no_source_counterpart"
SKIPPED_SOURCE_OVERLAP = "the_source_layout_already_overlapped"

# Which of the two measures made a pair a candidate, and which exempted it.
# Filed per pair: the routes are what a change to either bound moves pairs
# between, and a record holding only the verdict cannot show that the verdict
# survived the change.
ROUTE_IOU = "iou"
ROUTE_COVERAGE = "coverage"
ROUTE_BOTH = "iou_and_coverage"
SOURCE_ROUTE_IOU = "source_iou"
SOURCE_ROUTE_COVERAGE = "source_coverage"
SOURCE_ROUTE_BOTH = "source_iou_and_source_coverage"

CANDIDATE_ROUTES = (ROUTE_IOU, ROUTE_COVERAGE, ROUTE_BOTH)
EXEMPT_ROUTES = (SOURCE_ROUTE_IOU, SOURCE_ROUTE_COVERAGE, SOURCE_ROUTE_BOTH)


def measurable(view) -> list[tuple[int, object, str, tuple[float, float, float, float]]]:
    """Every paragraph of a page that carries text and an extent to compare."""
    rows = []
    for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
        text = base.rendered_text(paragraph).strip()
        box, _source = base.rendered_box(paragraph)
        if not text or box is None:
            continue
        rows.append((index, paragraph, text, box))
    return rows


def route(by_iou: bool, by_coverage: bool, names: tuple[str, str, str]) -> str:
    """Which of the two measures answered, named for the record."""
    if by_iou and by_coverage:
        return names[2]
    return names[0] if by_iou else names[1]


def detect(context: base.DetectionContext) -> list[base.Issue]:
    config = context.config
    source = context.source_geometry
    if source is None:
        return []
    found: list[base.Issue] = []
    skipped: dict[str, int] = {}
    for view in context.pages:
        rows = measurable(view)
        for position, (index, paragraph, text, box) in enumerate(rows):
            for other_index, other, other_text, other_box in rows[position + 1 :]:
                iou = base.intersection_over_union(box, other_box)
                covered = base.coverage(box, other_box)
                by_iou = iou >= config.collision_min_iou
                by_coverage = covered >= config.collision_min_coverage
                if not (by_iou or by_coverage):
                    continue
                if hasattr(source, "box_for"):
                    left = source.box_for(view.reference(index))
                    right = source.box_for(view.reference(other_index))
                else:
                    left = source.box_of(paragraph)
                    right = source.box_of(other)
                if left is None or right is None:
                    skipped[SKIPPED_NO_SOURCE] = skipped.get(SKIPPED_NO_SOURCE, 0) + 1
                    continue
                source_iou = base.intersection_over_union(left, right)
                source_covered = base.coverage(left, right)
                source_by_iou = source_iou >= config.collision_source_min_iou
                source_by_coverage = (
                    source_covered >= config.collision_source_min_coverage
                )
                pair = (view.reference(index), view.reference(other_index))
                candidate_route = route(by_iou, by_coverage, CANDIDATE_ROUTES)
                if source_by_iou or source_by_coverage:
                    skipped[SKIPPED_SOURCE_OVERLAP] = (
                        skipped.get(SKIPPED_SOURCE_OVERLAP, 0) + 1
                    )
                    context.file(
                        NAME,
                        {
                            "page": view.label,
                            "paragraphs": list(pair),
                            "verdict": SKIPPED_SOURCE_OVERLAP,
                            "candidate_route": candidate_route,
                            "exempt_route": route(
                                source_by_iou, source_by_coverage, EXEMPT_ROUTES
                            ),
                            "iou": round(iou, 4),
                            "coverage": round(covered, 4),
                            "source_iou": round(source_iou, 4),
                            "source_coverage": round(source_covered, 4),
                        },
                    )
                    continue
                found.append(
                    base.Issue(
                        kind=KIND,
                        page=view.label,
                        paragraph_refs=pair,
                        geometry=base.union_box([box, other_box]),
                        severity=context.severity_of(KIND),
                        evidence={
                            "iou": round(iou, 4),
                            "min_iou": config.collision_min_iou,
                            "coverage": round(covered, 4),
                            "min_coverage": config.collision_min_coverage,
                            "candidate_route": candidate_route,
                            "source_iou": round(source_iou, 4),
                            "source_min_iou": config.collision_source_min_iou,
                            "source_coverage": round(source_covered, 4),
                            "source_min_coverage": config.collision_source_min_coverage,
                            "source_stage": source.stage,
                            "source_checkpoint": source.path,
                            "debug_ids": [paragraph.debug_id, other.debug_id],
                            "layout_labels": [
                                paragraph.layout_label,
                                other.layout_label,
                            ],
                            "excerpt": text[: config.excerpt_chars],
                            "other_excerpt": other_text[: config.excerpt_chars],
                        },
                        detector=NAME,
                        detected_at_iteration=context.iteration,
                    )
                )
    for reason, count in sorted(skipped.items()):
        context.notes.append(f"{NAME}: {count} overlapping pair(s) not raised: {reason}")
    return found
