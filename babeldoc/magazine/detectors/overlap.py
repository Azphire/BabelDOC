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

Ornament-grade curves are the B16 extension. A triangle before a caption or an
oversized quotation mark opening a pull quote is a filled vector path, not a
figure or an xobject, so the artwork walk above never saw one -- and the union
ratio never would have: a 30 pt^2 triangle shares a vanishing fraction of its
union with any paragraph, however squarely the text is set over it. So the
small paths the shared classifier admits (``configs/ornament_assets.json``)
are tested by shared ink instead -- the intersection area in page points --
against ``ornament_overlap_min_pt2``. One finding per paragraph either way:
the issue id is built from the paragraph reference, and a paragraph over a
figure and a triangle at once is one defect with the figure as its worst
witness, not two findings sharing a name.
"""

from __future__ import annotations

from babeldoc.magazine import fixed_assets
from babeldoc.magazine.detectors import base
from babeldoc.magazine.fixed_assets import ARTWORK_COLLECTIONS

NAME = "text_figure_overlap"
KIND = "text_figure_overlap"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False

# What counts as artwork: the figures the parser recorded and the embedded
# forms it recorded beside them, each named by the attribute holding its box.
ARTWORK_SOURCES = ARTWORK_COLLECTIONS


def artwork_boxes(page) -> list[tuple[str, int, tuple[float, float, float, float]]]:
    """Every artwork box of one page, named by where it came from."""
    boxes = []
    for source in ARTWORK_SOURCES:
        for index, item in enumerate(getattr(page, source, None) or ()):
            box = base.box_tuple(item.box)
            if box is not None:
                boxes.append((source, index, box))
    return boxes


def _intersection(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[tuple[float, float, float, float], float] | None:
    """The shared rectangle and its area, or None where the boxes only touch."""
    x = max(left[0], right[0])
    y = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    if x2 - x <= 0 or y2 - y <= 0:
        return None
    return (x, y, x2, y2), (x2 - x) * (y2 - y)


def _artwork_issue(context, view, index, paragraph, text, box, artwork):
    config = context.config
    worst = max(
        (
            (base.intersection_over_union(box, other), source, position, other)
            for source, position, other in artwork
        ),
        default=None,
    )
    if worst is None or worst[0] < config.overlap_min_iou:
        return None
    iou, source, position, other = worst
    return base.Issue(
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


def _ink_boxes(paragraph, box):
    """The boxes the paragraph's ink actually stands in.

    The character boxes where the paragraph is laid out as characters; its own
    box where nothing has laid it out yet. The distinction is the whole
    measurement for an ornament: a paragraph whose first line was indented
    past a triangle still owns a box that covers the triangle, and reporting
    the box would report the avoidance as the defect it just repaired.
    """
    characters = [
        base.box_tuple(item)
        for item in (
            getattr(character, "box", None)
            for character in base.paragraph_characters(paragraph)
        )
        if item is not None
    ]
    characters = [item for item in characters if item is not None]
    return characters or [box]


def _ornament_issue(context, view, index, paragraph, text, box, ornaments):
    config = context.config
    ink = _ink_boxes(paragraph, box)
    worst = None
    for position, bbox in ornaments:
        area = 0.0
        rectangles = []
        for item in ink:
            shared = _intersection(item, bbox)
            if shared is None:
                continue
            rectangles.append(shared[0])
            area += shared[1]
        if not rectangles:
            continue
        rectangle = (
            min(item[0] for item in rectangles),
            min(item[1] for item in rectangles),
            max(item[2] for item in rectangles),
            max(item[3] for item in rectangles),
        )
        if worst is None or area > worst[0]:
            worst = (area, rectangle, position, bbox)
    if worst is None or worst[0] < config.ornament_overlap_min_pt2:
        return None
    area, rectangle, position, bbox = worst
    return base.Issue(
        kind=KIND,
        page=view.label,
        paragraph_refs=(view.reference(index),),
        geometry=base.union_box([box, bbox]),
        severity=context.severity_of(KIND),
        evidence={
            "iou": round(base.intersection_over_union(box, bbox), 4),
            "artwork_source": "pdf_curve",
            "artwork_index": position,
            "asset_class": fixed_assets.ORNAMENT_ASSET_CLASS,
            "ornament_bbox": [round(value, 4) for value in bbox],
            "intersection_box": [round(value, 4) for value in rectangle],
            "intersection_area_pt2": round(area, 4),
            "min_intersection_area_pt2": config.ornament_overlap_min_pt2,
            "debug_id": paragraph.debug_id,
            "layout_label": paragraph.layout_label,
            "excerpt": text[: config.excerpt_chars],
        },
        detector=NAME,
        detected_at_iteration=context.iteration,
    )


def detect(context: base.DetectionContext) -> list[base.Issue]:
    found: list[base.Issue] = []
    thresholds = fixed_assets.load_ornament_thresholds()
    for view in context.pages:
        artwork = artwork_boxes(view.page)
        ornaments = fixed_assets.ornament_curves(view.page, thresholds)
        if not artwork and not ornaments:
            continue
        for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
            text = base.rendered_text(paragraph, physical_page=view.label).strip()
            box = base.box_tuple(paragraph.box)
            if not text or box is None:
                continue
            issue = _artwork_issue(
                context, view, index, paragraph, text, box, artwork
            )
            if issue is None:
                issue = _ornament_issue(
                    context, view, index, paragraph, text, box, ornaments
                )
            if issue is not None:
                found.append(issue)
    return found
