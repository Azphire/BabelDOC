"""Two blocks of text standing in the same place, where the source had one.

A translated paragraph is laid out into the box its source occupied, and if the
translation needs more room than the source took, the stage widens or deepens
that box into whatever is beside it. The paragraph beside it was laid out from
its own box and did not move. What the reader receives is two texts printed over
each other.

The measurement is the intersection of the two rendered extents over their
union, the same quantity the artwork overlap detector uses and the same one the
layout parser assigns characters with.

Why the source is consulted
---------------------------

Because the measurement alone cannot tell a defect from a design. A magazine
prints text over text on purpose and often: a display headline painted twice,
once solid and once in a texture layer, is two paragraphs at the same place; a
strap band set across the foot of a montage sits inside the block above it; a
folio is printed inside the entry it numbers. Every one of those is an overlap
the source already had, and a detector reporting it is reporting the designer's
decision as a fault.

So a pair is a finding only where the same two paragraphs did not overlap in the
document as it stood before anything was translated. That document is the source
layout checkpoint, and the pair's members are found in it by the id they have
carried since the paragraph finder minted it. A pair either of whose members has
no counterpart there is not reported at all: without both source boxes there is
nothing to compare, and an unsupported claim that the translation caused an
overlap is worse than no claim.

Report only, and this one stays report only for longer than the others. The
causes are not one cause -- a layer painted twice, a band over a montage, a
folio inside an entry, a caption grown into the column beside it -- and they
want different answers. What moves a grown caption back would destroy a painted
layer. So this batch counts them and sorts them, and the batch that acts on them
is the one that can say which is which.
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
                if iou < config.collision_min_iou:
                    continue
                left = source.box_of(paragraph)
                right = source.box_of(other)
                if left is None or right is None:
                    skipped[SKIPPED_NO_SOURCE] = (
                        skipped.get(SKIPPED_NO_SOURCE, 0) + 1
                    )
                    continue
                source_iou = base.intersection_over_union(left, right)
                if source_iou >= config.collision_source_min_iou:
                    skipped[SKIPPED_SOURCE_OVERLAP] = (
                        skipped.get(SKIPPED_SOURCE_OVERLAP, 0) + 1
                    )
                    continue
                found.append(
                    base.Issue(
                        kind=KIND,
                        page=view.label,
                        paragraph_refs=(
                            view.reference(index),
                            view.reference(other_index),
                        ),
                        geometry=base.union_box([box, other_box]),
                        severity=context.severity_of(KIND),
                        evidence={
                            "iou": round(iou, 4),
                            "min_iou": config.collision_min_iou,
                            "source_iou": round(source_iou, 4),
                            "source_min_iou": config.collision_source_min_iou,
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
