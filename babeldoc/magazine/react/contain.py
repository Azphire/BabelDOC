"""Putting a paragraph the page does not contain back inside the page.

The defect this answers is a heading drawn off the top of its own page. The
typesetting stage anchors a paragraph's line spacing on the modal size of the
units it holds, so a display line whose paragraph also carries a small credit line
is spaced for the credit and it is drawn above the box it was measured
into. Where that box already stood against the head of the sheet, the display line
is drawn past the trim and the reader receives it with its top cut away.

The anchoring is upstream and is a layout algorithm this project does not
change. What it produces can be corrected here, after the stage has finished and
before anything is written, which is the window the detection pass already runs
in.

The channel: the characters, not the composition
------------------------------------------------

A laid out paragraph is a list of characters, and the writer draws each one at
its own box origin in its own style's size -- ``pdf_creater`` emits
``Tf <font_size>`` and ``Tm 1 0 0 1 <box.x> <box.y>`` per character, and reads
neither ``paragraph.scale`` nor ``paragraph.optimal_scale``. So a paragraph's
rendering is an affine function of the character boxes and sizes, and moving or
shrinking one is that same affine map applied to them.

That is why this action does not lay the paragraph out again. Re-typesetting is
the mechanism the orphan action needs, because it is putting *new text* into a
paragraph and the text has to be measured and broken. Here the text is already
measured, already broken and already placed relative to itself, and all of that
is correct -- what is wrong is only where the result sits and how big it is. A
map that scales the characters about a point and then slides them preserves
every line break and every relative position exactly, and cannot reflow anything
or touch any other paragraph. Re-typesetting would risk all three to achieve
less.

What this reuses from the write-back path is the discipline rather than the
code: a snapshot per paragraph taken before it is touched, a geometric test on
the result, and the paragraph put back where the test fails.

Three outcomes, and they are ordered
------------------------------------

Sliding first, because a paragraph that fits inside the page and merely sits in
the wrong place should be moved and not shrunk: shrinking changes the typography
and sliding does not.

Shrinking second, and only as far as it has to: the scale is the largest one at
which the ink fits inside the frame, so a heading is never made smaller than the
page requires. The frame it is fitted to is the page's own, drawn in by this
action's declared margin -- the detector says whether ink is outside the trim,
and this says how comfortably inside to land it, which has to clear the trim
tolerance rather than sit on it. The scale is taken about the centre of the
paragraph's own extent, which keeps the heading where the designer put it as far
as the frame allows, and the slide that follows is then always the one that
lands it inside.

Escalating third. A scale under the declared floor means the paragraph would
have to be shrunk past the point where what is left is the heading the designer
set. Then nothing is applied and the finding is reported with the figure it
would have needed, which is a fact a human can act on and a fact this action
cannot.
"""

from __future__ import annotations

from dataclasses import dataclass

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.detectors import base as detector_base
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.react.actions import ACCEPTED
from babeldoc.magazine.react.actions import Application
from babeldoc.magazine.react.config import CONTAIN_LABELS_KEY
from babeldoc.magazine.react.config import MIN_OVERFLOW_KEY
from babeldoc.magazine.react.config import Action

NAME = "contain_in_page"

# The two numbers this mechanism is bounded by, declared at the action's own
# level because neither is a decision's to set and neither selects a finding.
# The floor on how far the ink may be shrunk, and how far inside the page frame
# a contained paragraph is landed: the detector answers whether ink is outside
# the trim, and this answers how comfortably inside to put it, which has to
# clear the trim tolerance rather than sit on it.
MIN_SCALE_KEY = "contain_min_scale"
MARGIN_KEY = "contain_margin_ratio"

# One finding, one paragraph: a box leaves the page on its own.
PARAGRAPHS_PER_FINDING = 1

# Why a finding was not acted on.
REASON_LABEL = "layout_label_outside_the_containment_classes"
REASON_OVERFLOW = "overflow_ratio_below_bound"
REASON_NO_FRAME = "page_carries_no_frame_to_be_contained_by"
REASON_NO_INK = "paragraph_carries_no_laid_out_character_to_move"
REASON_CONTAINED = "the_paragraph_is_already_inside_the_page"
REASON_FLOOR = "containing_it_would_shrink_it_past_the_declared_floor"
REASON_NOT_CONTAINED = "the_transform_did_not_bring_the_ink_inside_the_page"

# How it was contained: the two states an accepted application reports.
STATE_TRANSLATED = "translated"
STATE_SCALED = "scaled_and_translated"


def applicability(action: Action) -> tuple[tuple[str, ...], float]:
    rule = action.applicability
    return tuple(rule[CONTAIN_LABELS_KEY]), float(rule[MIN_OVERFLOW_KEY])


def min_scale(action: Action) -> float:
    return float(action.bound(MIN_SCALE_KEY))


def margin_ratio(action: Action) -> float:
    return float(action.bound(MARGIN_KEY))


def arithmetic_slack(bounds) -> float:
    """How much residual overflow is rounding rather than ink outside the page.

    The transform is computed in double precision from the same coordinates the
    test then reads back, so what survives it is representation error and
    nothing else. The allowance is that error scaled to the magnitude of the
    coordinates involved, which is arithmetic and not a bound anybody chose.
    """
    return max(abs(value) for value in bounds) * 1e-9 + 1e-9


def ink_box(paragraph) -> tuple[float, float, float, float] | None:
    """The extent of the characters a paragraph is laid out as, or None.

    None where the paragraph carries no laid out character: its box would then
    be all this could move, and moving a box the writer draws nothing from
    repairs nothing.
    """
    box, source = detector_base.rendered_box(paragraph)
    if source != detector_base.BOX_FROM_CHARACTERS:
        return None
    return box


@dataclass(frozen=True)
class Containment:
    """The map that would put one paragraph inside its page."""

    scale: float
    shift: tuple[float, float]
    anchor: tuple[float, float]
    box: tuple[float, float, float, float]
    box_source: str
    safe: tuple[float, float, float, float]
    frame_source: str
    floor: float

    @property
    def state(self) -> str:
        return STATE_TRANSLATED if self.scale >= 1.0 else STATE_SCALED

    @property
    def inert(self) -> bool:
        return self.scale >= 1.0 and self.shift == (0.0, 0.0)

    def as_record(self) -> dict:
        return {
            "box_before": [round(value, 4) for value in self.box],
            "box_source": self.box_source,
            "frame_source": self.frame_source,
            "safe_box": [round(value, 4) for value in self.safe],
            "scale": round(self.scale, 6),
            "shift": [round(value, 4) for value in self.shift],
            "min_scale": self.floor,
            "overflow_before": {
                side: round(value, 4)
                for side, value in detector_base.overflow(self.box, self.safe).items()
            },
        }


def fit(box, bounds) -> tuple[float, tuple[float, float]]:
    """The scale and slide that put ``box`` inside ``bounds``.

    The scale is the largest one at or below unity at which the box fits along
    both axes; the slide is what the box scaled about its own centre then needs
    in order to be inside. A box that already fits is scaled by one, and a box
    already inside is slid by nothing.
    """
    left, bottom, right, top = box
    width = right - left
    height = top - bottom
    available_width = bounds[2] - bounds[0]
    available_height = bounds[3] - bounds[1]
    scale = 1.0
    if width > available_width and width > 0:
        scale = min(scale, available_width / width)
    if height > available_height and height > 0:
        scale = min(scale, available_height / height)

    centre_x = (left + right) / 2
    centre_y = (bottom + top) / 2
    scaled = (
        centre_x + (left - centre_x) * scale,
        centre_y + (bottom - centre_y) * scale,
        centre_x + (right - centre_x) * scale,
        centre_y + (top - centre_y) * scale,
    )
    amounts = detector_base.overflow(scaled, bounds)
    shift = (
        amounts["left"] - amounts["right"],
        amounts["bottom"] - amounts["top"],
    )
    return scale, shift


def transform_box(box, scale: float, anchor, shift) -> il_version_1.Box:
    """One box under the map, as a new box: the old one is somebody's snapshot."""
    return il_version_1.Box(
        x=anchor[0] + (float(box.x) - anchor[0]) * scale + shift[0],
        y=anchor[1] + (float(box.y) - anchor[1]) * scale + shift[1],
        x2=anchor[0] + (float(box.x2) - anchor[0]) * scale + shift[0],
        y2=anchor[1] + (float(box.y2) - anchor[1]) * scale + shift[1],
    )


def _scaled_style(style, scale: float):
    """One style at a new size, as a new style.

    Replaced rather than edited, because one style object is shared by every
    character of a run and editing it would resize text this action never looked
    at.
    """
    if scale == 1.0 or style is None or style.font_size is None:
        return style
    return il_version_1.PdfStyle(
        font_id=style.font_id,
        font_size=float(style.font_size) * scale,
        graphic_state=style.graphic_state,
    )


def transform(paragraph, plan: Containment) -> None:
    """Scale a paragraph's ink about the plan's anchor and slide it, in place.

    Every character's box and, where the scale is not unity, the size it is set
    in: the writer emits both per character, so the two have to move together or
    the glyphs are drawn at the old size in the new places. The visual bounding
    box beside each character goes with it, and so does the paragraph's own
    style, so that nothing downstream is left describing where the paragraph
    used to be or how large it used to be set.
    """
    for character in paragraph_characters(paragraph):
        if character.box is not None:
            character.box = transform_box(
                character.box, plan.scale, plan.anchor, plan.shift
            )
        visual = character.visual_bbox
        if visual is not None and visual.box is not None:
            visual.box = transform_box(
                visual.box, plan.scale, plan.anchor, plan.shift
            )
        character.pdf_style = _scaled_style(character.pdf_style, plan.scale)
    paragraph.pdf_style = _scaled_style(paragraph.pdf_style, plan.scale)
    if paragraph.box is not None:
        paragraph.box = transform_box(
            paragraph.box, plan.scale, plan.anchor, plan.shift
        )


def admits(issue, candidate, action: Action) -> str:
    """Why this finding is not one to act on, or ``ACCEPTED``.

    Stricter than the detector on both terms it shares with it. The label has to
    be one of the declared containment classes, because a paragraph of running
    text reaching past the frame is a column that grew, and moving the column
    would move the reading order with it; what this action is for is a display
    block drawn outside the sheet it was set on. And the reach has to be past
    the action's own bound, which is at or above the detector's, because a
    finding reported at the edge of the detector's noise floor is not one to
    move a heading over.
    """
    labels, min_overflow = applicability(action)
    if (candidate.paragraph.layout_label or "") not in labels:
        return REASON_LABEL
    ratio = issue.evidence.get("overflow_ratio")
    if not isinstance(ratio, int | float) or float(ratio) < min_overflow:
        return REASON_OVERFLOW
    if detector_base.page_frame(candidate.page) is None:
        return REASON_NO_FRAME
    if ink_box(candidate.paragraph) is None:
        return REASON_NO_INK
    return ACCEPTED


def plan(candidate, margin_ratio: float, floor: float) -> tuple[str, Containment | None]:
    """What containing this paragraph would take, and whether it may be done."""
    frame = detector_base.page_frame(candidate.page)
    box = ink_box(candidate.paragraph)
    if frame is None:
        return REASON_NO_FRAME, None
    if box is None:
        return REASON_NO_INK, None
    bounds, frame_source = frame
    safe = detector_base.inset(bounds, margin_ratio)
    scale, shift = fit(box, safe)
    found = Containment(
        scale=scale,
        shift=shift,
        anchor=((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
        box=box,
        box_source=detector_base.BOX_FROM_CHARACTERS,
        safe=safe,
        frame_source=frame_source,
        floor=floor,
    )
    if found.inert:
        return REASON_CONTAINED, found
    if scale < floor:
        return REASON_FLOOR, found
    return ACCEPTED, found


def worst_overlap(candidate) -> float:
    """The worst overlap the contained paragraph now has with its neighbours.

    Recorded and not acted on. Moving a heading inside the page can put it over
    something that was standing where it landed, and a repair that says nothing
    about that is one nobody can review. What to do about it is the collision
    finding's business, and this batch does not act on those.
    """
    box = ink_box(candidate.paragraph)
    if box is None:
        return 0.0
    worst = 0.0
    for index, other in enumerate(candidate.page.pdf_paragraph or ()):
        if index == candidate.paragraph_index:
            continue
        if not detector_base.rendered_text(other).strip():
            continue
        other_box, _source = detector_base.rendered_box(other)
        if other_box is None:
            continue
        worst = max(worst, detector_base.intersection_over_union(box, other_box))
    return worst


def apply_one(candidate, action: Action) -> Application:
    """Contain one paragraph, or say why it was not contained.

    The paragraph is transformed and then measured again, and a transform whose
    result is still outside the page is not a repair: the caller puts the
    paragraph back. The test is on the document rather than on the arithmetic,
    for the same reason the write-back path measures its own result.
    """
    floor = min_scale(action)
    verdict, found = plan(candidate, margin_ratio(action), floor)
    outcome = Application(
        issue_id=candidate.issue_id,
        reference=candidate.reference,
        accepted=False,
        reason=verdict,
        source_text=candidate.source_text,
        geometry={} if found is None else found.as_record(),
    )
    if verdict != ACCEPTED or found is None:
        return outcome
    transform(candidate.paragraph, found)
    after = ink_box(candidate.paragraph)
    record = outcome.geometry
    record["state"] = found.state
    record["box_after"] = None if after is None else [round(v, 4) for v in after]
    if after is None:
        outcome.reason = REASON_NO_INK
        return outcome
    amounts = detector_base.overflow(after, found.safe)
    record["overflow_after"] = {
        side: round(value, 4) for side, value in amounts.items()
    }
    if max(amounts.values()) > arithmetic_slack(found.safe):
        outcome.reason = REASON_NOT_CONTAINED
        return outcome
    record["worst_overlap_after"] = round(worst_overlap(candidate), 4)
    outcome.accepted = True
    outcome.changed = True
    outcome.reason = ACCEPTED
    return outcome
