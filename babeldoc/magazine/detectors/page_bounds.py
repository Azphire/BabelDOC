"""Text the page does not contain.

A translated paragraph is laid out into the box the source paragraph occupied,
and the characters it is laid out as are not obliged to stay inside it. The
stage anchors a paragraph's line height on the modal size of the units it holds,
so a paragraph mixing a display sized line with body sized ones is spaced for
the body size and the display line is drawn outside the box it was measured
into. Where that box already stood against the head of the page, the display
line is drawn off the page, and what the reader receives is a heading with its
top cut away.

So what is measured is the ink and not the box: the union of the boxes of the
characters the paragraph was laid out as, against the page's own frame drawn in
by a declared safety margin. The margin is a share of each axis of the page
rather than a distance, because the corpus is not one page size.

Two bounds and they do different work. The margin says how close to the trim a
paragraph may stand before it is worth reporting. The minimum overflow says how
far past that a paragraph has to reach before the reach is a finding rather than
arithmetic: a box a thousandth of a page outside its bound is a rounding, and
reporting it would bury the page that lost its heading.

Report only, like every detector. Putting the paragraph back inside the page is
the repair action's business, and it is stricter about which paragraphs it will
touch than this is about which it will report.
"""

from __future__ import annotations

from babeldoc.magazine.detectors import base

NAME = "out_of_page"
KIND = "out_of_page"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False

# The sides of the frame, in the order an issue reports them.
SIDES = ("left", "bottom", "right", "top")

# Which page dimension bounds the overflow of each side, so that a share is
# taken against the axis the paragraph actually left the page along.
_SIDE_AXIS = {"left": 0, "right": 0, "bottom": 1, "top": 1}


def worst_overflow(amounts: dict[str, float], frame) -> tuple[str, float, float]:
    """The side reached furthest past, in points and as a share of that axis.

    The share is taken against the page dimension of the side's own axis, so a
    paragraph hanging off the foot of a tall page and one hanging off the side
    of a wide one are measured on comparable scales. Ties go to the earlier side
    in the declared order, which makes the answer independent of dict ordering.
    """
    extent = (frame[2] - frame[0], frame[3] - frame[1])
    worst_side = SIDES[0]
    worst_points = 0.0
    worst_ratio = 0.0
    for side in SIDES:
        points = amounts[side]
        axis = extent[_SIDE_AXIS[side]]
        ratio = points / axis if axis > 0 else 0.0
        if points > worst_points:
            worst_side, worst_points, worst_ratio = side, points, ratio
    return worst_side, worst_points, worst_ratio


def detect(context: base.DetectionContext) -> list[base.Issue]:
    config = context.config
    found: list[base.Issue] = []
    for view in context.pages:
        frame = base.page_frame(view.page)
        if frame is None:
            context.notes.append(
                f"{NAME}: page {view.label} carries neither a crop box nor a "
                f"media box, so it has no frame to be contained by; not measured"
            )
            continue
        bounds, frame_source = frame
        safe = base.inset(bounds, config.page_safety_margin_ratio)
        for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
            text = base.rendered_text(paragraph, physical_page=view.label).strip()
            box, box_source = base.rendered_box(paragraph)
            if not text or box is None:
                continue
            amounts = base.overflow(box, safe)
            side, points, ratio = worst_overflow(amounts, bounds)
            if ratio < config.out_of_page_min_overflow_ratio or points <= 0:
                continue
            found.append(
                base.Issue(
                    kind=KIND,
                    page=view.label,
                    paragraph_refs=(view.reference(index),),
                    geometry=base.union_box([box]),
                    severity=context.severity_of(KIND),
                    evidence={
                        "overflow_max": round(points, 4),
                        "overflow_ratio": round(ratio, 6),
                        "overflow_side": side,
                        **{
                            f"overflow_{name}": round(amounts[name], 4)
                            for name in SIDES
                        },
                        "safe_box": [round(value, 4) for value in safe],
                        "frame_box": [round(value, 4) for value in bounds],
                        "frame_source": frame_source,
                        "box_source": box_source,
                        "margin_ratio": config.page_safety_margin_ratio,
                        "min_overflow_ratio": config.out_of_page_min_overflow_ratio,
                        "debug_id": paragraph.debug_id,
                        "layout_label": paragraph.layout_label,
                        "excerpt": text[: config.excerpt_chars],
                    },
                    detector=NAME,
                    detected_at_iteration=context.iteration,
                )
            )
    return found
