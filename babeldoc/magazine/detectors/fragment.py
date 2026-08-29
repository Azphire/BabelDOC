"""Runs of short paragraphs that one paragraph was cut into.

A paragraph finder that loses a column boundary, a rule or a change of leading
leaves running text as a stack of one-line paragraphs. Each is translated on
its own, so the sentence they share is translated in pieces, and the defect is
visible in the geometry rather than in the text: several short paragraphs, set
in one font at one size, standing in one column, separated by no more than an
ordinary line's leading.

Report only. Merging them is a change to the document's paragraph structure and
so to every downstream count, which is a batch of its own; what this produces
is the census that batch would be argued from.
"""

from __future__ import annotations

import statistics

from babeldoc.magazine.detectors import base

NAME = "fragment_cluster"
KIND = "fragment_cluster"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False


def style_key(paragraph, tolerance: float) -> tuple[str, int] | None:
    """Font and quantised size of a paragraph, or None where it has no style.

    The size is quantised by the declared tolerance so that two members set at
    sizes a rounding apart share a key, and two set a step apart do not.
    """
    style = paragraph.pdf_style
    if style is None or not style.font_id or not style.font_size:
        return None
    if tolerance <= 0:
        return style.font_id, round(float(style.font_size) * 1000)
    return style.font_id, int(round(float(style.font_size) / tolerance))


def x_overlap_ratio(left, right) -> float:
    """Shared width of two boxes over the width of the narrower one."""
    shared = min(left[2], right[2]) - max(left[0], right[0])
    if shared <= 0:
        return 0.0
    narrower = min(left[2] - left[0], right[2] - right[0])
    return shared / narrower if narrower > 0 else 0.0


def _height(box) -> float:
    return max(0.0, box[3] - box[1])


def _gap(upper, lower) -> float:
    """Vertical distance between two boxes, zero where they overlap."""
    return max(0.0, max(upper[1], lower[1]) - min(upper[3], lower[3]))


def _continues(previous, current, config: base.DetectorConfig) -> bool:
    previous_box, previous_key = previous
    current_box, current_key = current
    if previous_key != current_key:
        return False
    if x_overlap_ratio(previous_box, current_box) < config.fragment_min_x_overlap_ratio:
        return False
    heights = [_height(previous_box), _height(current_box)]
    reference = statistics.median([height for height in heights if height > 0] or [0.0])
    if reference <= 0:
        return False
    return _gap(previous_box, current_box) <= (
        config.fragment_max_line_gap_ratio * reference
    )


def _members(view, config: base.DetectorConfig):
    """Candidate members of the page, in the order the page holds them."""
    for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
        text = base.rendered_text(paragraph, physical_page=view.label).strip()
        box = base.box_tuple(paragraph.box)
        key = style_key(paragraph, config.fragment_font_size_tolerance)
        eligible = bool(text) and len(text) <= config.fragment_max_chars
        yield index, paragraph, text, box, key, (eligible and box is not None and key is not None)


def _issue(view, run, context: base.DetectionContext) -> base.Issue:
    config = context.config
    return base.Issue(
        kind=KIND,
        page=view.label,
        paragraph_refs=tuple(view.reference(index) for index, _, _, _ in run),
        geometry=base.union_box([box for _, _, box, _ in run]),
        severity=context.severity_of(KIND),
        evidence={
            "member_count": len(run),
            "max_chars": config.fragment_max_chars,
            "min_cluster": config.fragment_min_cluster,
            "debug_ids": [paragraph.debug_id for _, paragraph, _, _ in run],
            "layout_labels": sorted({paragraph.layout_label for _, paragraph, _, _ in run}),
            "excerpt": " / ".join(text for _, _, _, text in run)[: config.excerpt_chars],
        },
        detector=NAME,
        detected_at_iteration=context.iteration,
    )


def detect(context: base.DetectionContext) -> list[base.Issue]:
    config = context.config
    found: list[base.Issue] = []
    for view in context.pages:
        run: list = []
        previous = None
        for index, paragraph, text, box, key, eligible in _members(view, config):
            if not eligible:
                if len(run) >= config.fragment_min_cluster:
                    found.append(_issue(view, run, context))
                run, previous = [], None
                continue
            if previous is not None and not _continues(previous, (box, key), config):
                if len(run) >= config.fragment_min_cluster:
                    found.append(_issue(view, run, context))
                run = []
            run.append((index, paragraph, box, text))
            previous = (box, key)
        if len(run) >= config.fragment_min_cluster:
            found.append(_issue(view, run, context))
    return found
