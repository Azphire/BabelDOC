"""Text standing where artwork stands.

A translated paragraph grows or shrinks against its source, and the box it was
typeset into does not move with it, so text can end up sharing space with a
figure or an embedded form. The measurement is the intersection of the two
boxes over their union, which is the same quantity the layout parser assigns
characters to layouts with.

Report only, and knowingly conservative: a caption printed inside a full page
photograph shares almost none of that photograph's area and is not reported at
this bound, while a paragraph and a figure of comparable size sitting on top of
one another is. Which of the two the census should be tuned for is a question
for the batch that acts on the finding, not for the batch that first counts it.
"""

from __future__ import annotations

from babeldoc.magazine.detectors import base

NAME = "text_figure_overlap"
KIND = "text_figure_overlap"

REQUIRES_TRANSLATION = False

# What counts as artwork: the figures the parser recorded and the embedded
# forms it recorded beside them, each named by the attribute holding its box.
ARTWORK_SOURCES = ("pdf_figure", "pdf_xobject")


def artwork_boxes(page) -> list[tuple[str, int, tuple[float, float, float, float]]]:
    """Every artwork box of one page, named by where it came from."""
    boxes = []
    for source in ARTWORK_SOURCES:
        for index, item in enumerate(getattr(page, source, None) or ()):
            box = base.box_tuple(item.box)
            if box is not None:
                boxes.append((source, index, box))
    return boxes


def detect(context: base.DetectionContext) -> list[base.Issue]:
    config = context.config
    found: list[base.Issue] = []
    for view in context.pages:
        artwork = artwork_boxes(view.page)
        if not artwork:
            continue
        for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
            text = base.rendered_text(paragraph).strip()
            box = base.box_tuple(paragraph.box)
            if not text or box is None:
                continue
            worst = max(
                (
                    (base.intersection_over_union(box, other), source, position, other)
                    for source, position, other in artwork
                ),
                default=None,
            )
            if worst is None or worst[0] < config.overlap_min_iou:
                continue
            iou, source, position, other = worst
            found.append(
                base.Issue(
                    kind=KIND,
                    page=view.label,
                    paragraph_refs=(view.reference(index),),
                    geometry=base.union_box([box, other]),
                    severity=context.severity_of(KIND),
                    evidence={
                        "iou": round(iou, 4),
                        "min_iou": config.overlap_min_iou,
                        "artwork_source": source,
                        "artwork_index": position,
                        "debug_id": paragraph.debug_id,
                        "layout_label": paragraph.layout_label,
                        "excerpt": text[: config.excerpt_chars],
                    },
                    detector=NAME,
                    detected_at_iteration=context.iteration,
                )
            )
    return found
