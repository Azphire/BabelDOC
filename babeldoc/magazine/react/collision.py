"""The action for two texts standing in one place: move the smaller one clear.

Why this writes, where it used to write nothing
-----------------------------------------------

It used to refuse everything, and the refusal was right for the state it was
written in. The reasoning was that the causes of an overlap are not one cause
and their answers are opposite -- a display headline painted twice in the source
wants one layer suppressed, a caption grown into the column beside it wants
moving or setting smaller, a folio printed inside the entry it numbers wants
nothing at all because it was always there and the entry moved. Moving a
paragraph blindly costs more than leaving the overlap, because an overlap is
legible under inspection and a paragraph moved to the wrong place is not
recoverable from the finished page at all.

That reasoning is not overturned here. What has gone is the two conditions it
rested on.

The first was that nothing separated the causes. The detector measured overlap
by the ratio over the union alone, which reported almost nothing on this corpus,
and what it did report it reported without saying whether the source had drawn
it. Both are now false: the coverage measure finds the overlaps the union ratio
could not see, and the source exemption takes out the largest and most
dangerous class -- the overlaps the designer drew -- before this action is shown
anything. What reaches here is an overlap the translation made.

The second was that there was nowhere to judge a finding one at a time. There is
now: the decision rounds ask about one detector kind at a time, so a
heterogeneous cause is answered where heterogeneous causes belong, in a decision
about a particular finding, rather than by an action refusing its whole kind in
advance.

So the action writes. What it does not do is claim the causes have become one
cause: the heterogeneity is still real and is now handled by narrowing what this
will accept, rather than by accepting nothing.

What it will and will not act on
--------------------------------

It moves the smaller of the two paragraphs, and the rule is built so that "the
smaller" always names something. The smaller box's area over the larger's has to
be at or below the declared ratio, so a pair of comparable blocks -- where
moving either is exactly as wrong as moving the other, and where the right
answer is usually to reset one rather than to shift it -- is escalated and left
alone. That is the case the acceptance of the batch that refused everything was
measured on, and it is still refused; what has changed is that it is now refused
by a rule that says which case it is, rather than by a rule that refused every
case.

And the movement has a ceiling. Clearing the overlap has to take no more than
the declared share of the page along the axis it moves on. A pair needing more
than that is not a paragraph that drifted into its neighbour, it is a layout
that went wrong further back, and sliding it a third of the way across the page
would produce a page that is wrong in a new way instead of the old one.

One measure in the rule, where the detector has two
---------------------------------------------------

The detector admits a pair at or above either bound. The rule here reads
coverage alone, and the asymmetry is deliberate rather than an oversight.

The union ratio can select nothing this rule would not already have. Coverage is
never below it -- both divide the same shared area, and the smaller box's area is
never above the union -- so a pair the union ratio admits at its bound while
coverage refuses it at the higher one is squeezed into a narrow region, and in
that region the two boxes are forced to within about 0.71 of each other's area.
The asymmetry bound refuses everything above 0.5. So the second bound would
select nothing, on any page, ever.

Which would be harmless if the rule were only ever executed. It is also stated:
the deciding model is shown these sentences as the whole of the filter it is
feeding, under the heading that all of them must hold. A disjunction written as
two conjoined sentences is a thing to be misread, and it was misread the first
time it was put in front of a model -- the reply refused a pair reporting
coverage 0.5234 on the ground that 0.5234 was below the bound of 0.4. A bound
that selects nothing and misleads the reader is worse than no bound.

Which way, and how far
----------------------

There are four ways out of an overlap -- two axes, two directions on each -- and
the one taken is the cheapest. The smallest movement that ends the overlap is
the one least likely to walk into anything else and the least visible where it
is wrong, so the four distances are computed and the smallest wins.

Cheapest is not the same as least overlapping, which is why all four are
measured rather than read off the overlap. Two boxes meeting edge to edge part
by exactly the distance they are moved, so for them the two are the same. A
small box standing wholly inside a large one is the case this action mostly
sees, and it overlaps the large one by its own whole width and its own whole
height however far it moves, right up until its trailing edge passes the large
box's edge. What separates them is not how much they overlap but how near the
small one is to an edge, and that is a different number on each of the four
ways out.

What it reuses, and the one thing it does not
---------------------------------------------

The mechanism layer is the containment action's: the same affine map over the
characters, the same snapshot taken before a paragraph is touched, the same
measurement of the result on the document rather than on the arithmetic, and the
same restoration where the measurement fails.

The guard is its own, and deliberately. The containment action asks whether its
repair would stand a paragraph on something by the ratio over the union, because
that was the whole of what an overlap meant when it was written. Here that would
be a hole: this action exists because the union ratio does not see a small box
standing inside a large one, so a guard reading the union ratio alone would let
this slide a folio out of one entry and straight into the next without noticing.
The guard therefore asks the same either-measure question the detector asks, so
what it refuses to create is exactly what the detector would go on to report.
"""

from __future__ import annotations

from dataclasses import dataclass

from babeldoc.magazine.detectors import base as detector_base
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.react.actions import ACCEPTED
from babeldoc.magazine.react.actions import Application
from babeldoc.magazine.react.config import MIN_COLLISION_COVERAGE_KEY
from babeldoc.magazine.react.config import Action
from babeldoc.magazine.react.contain import arithmetic_slack
from babeldoc.magazine.react.contain import ink_box
from babeldoc.magazine.react.contain import transform

NAME = "resolve_collision"

# One finding, two paragraphs: an overlap is a statement about a pair.
PARAGRAPHS_PER_FINDING = 2

# The numbers the mechanism is bounded by, declared at the action's own level:
# none is a decision's to set and none selects a finding. The largest the
# smaller box may be as a share of the larger before "the smaller" stops
# naming anything; the furthest the ink may travel, as a share of the page
# along the axis it travels on; and how far below the coverage bound the result
# has to land, so a repair clears the threshold rather than stopping on it.
MAX_AREA_RATIO_KEY = "resolve_max_area_ratio"
MAX_SHIFT_RATIO_KEY = "resolve_max_shift_ratio"
MARGIN_KEY = "resolve_margin"

# Why a finding was not acted on.
REASON_MEASURE = "neither_overlap_measure_reaches_the_declared_bound"
REASON_NO_BOUND = "the_rule_declares_no_coverage_bound_for_this_action"
REASON_PAIR = "the_pair_could_not_be_resolved_to_two_paragraphs"
REASON_NO_INK = "a_member_carries_no_laid_out_character_to_move"
REASON_NO_FRAME = "page_carries_no_frame_to_measure_the_shift_against"
REASON_AREA = "the_two_are_of_comparable_size_so_neither_is_the_one_to_move"
REASON_SHIFT = "clearing_the_overlap_would_take_more_than_the_declared_shift"
REASON_SEPARATE = "the_two_do_not_overlap_on_both_axes"
REASON_ALREADY = "the_overlap_is_already_below_the_bound_the_slide_aims_at"
REASON_INDUCED = "moving_it_clear_would_stand_it_on_text_it_was_not_standing_on"
REASON_LEAVES_PAGE = "moving_it_clear_would_take_its_ink_outside_the_page"
REASON_NOT_RESOLVED = "the_move_did_not_bring_the_overlap_below_the_bound"

# What the guard refused, as the record states it.
GUARD_INDUCED = "it_would_stand_on_text_it_was_not_standing_on"
GUARD_OFF_PAGE = "it_would_leave_the_page"

AXIS_X = "x"
AXIS_Y = "y"


def applicability(action: Action) -> float | None:
    """The coverage bound this rule declares, or None where it declares none.

    None for a configuration frozen before that bound existed, which names the
    union ratio's instead. Such a file still parses, because reproducing what an
    earlier batch sent needs the configuration that batch shipped; what it does
    not do is drive this action, which refuses rather than reading a bound that
    measures a different thing.
    """
    found = action.applicability.get(MIN_COLLISION_COVERAGE_KEY)
    return None if found is None else float(found)


def max_area_ratio(action: Action) -> float:
    return float(action.bound(MAX_AREA_RATIO_KEY))


def max_shift_ratio(action: Action) -> float:
    return float(action.bound(MAX_SHIFT_RATIO_KEY))


def margin(action: Action) -> float:
    return float(action.bound(MARGIN_KEY))


def area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def overlaps(left, right) -> tuple[float, float]:
    """How far two boxes overlap along each axis, never below zero."""
    return (
        max(0.0, min(left[2], right[2]) - max(left[0], right[0])),
        max(0.0, min(left[3], right[3]) - max(left[1], right[1])),
    )


def stands_on(left, right, min_iou: float, min_coverage: float) -> bool:
    """Whether two boxes overlap by either of the two measures.

    The detector's question, asked here so the guard refuses to create exactly
    what the detector would go on to report.
    """
    return (
        detector_base.intersection_over_union(left, right) >= min_iou
        or detector_base.coverage(left, right) >= min_coverage
    )


@dataclass(frozen=True)
class Separation:
    """The slide that would take one paragraph of a pair clear of the other."""

    mover_index: int
    mover_reference: str
    other_reference: str
    axis: str
    shift: tuple[float, float]
    box: tuple[float, float, float, float]
    other_box: tuple[float, float, float, float]
    area_ratio: float
    limit: float
    coverage_before: float
    iou_before: float
    target: float

    @property
    def distance(self) -> float:
        return abs(self.shift[0]) + abs(self.shift[1])

    @property
    def projected(self) -> tuple[float, float, float, float]:
        """Where the mover's ink would be under this slide, without applying it."""
        shift_x, shift_y = self.shift
        left, bottom, right, top = self.box
        return (left + shift_x, bottom + shift_y, right + shift_x, top + shift_y)

    def as_record(self) -> dict:
        return {
            "mover": self.mover_reference,
            "other": self.other_reference,
            "axis": self.axis,
            "shift": [round(value, 4) for value in self.shift],
            "distance": round(self.distance, 4),
            "shift_limit": round(self.limit, 4),
            "area_ratio": round(self.area_ratio, 4),
            "box_before": [round(value, 4) for value in self.box],
            "coverage_before": round(self.coverage_before, 4),
            "iou_before": round(self.iou_before, 4),
            "coverage_target": round(self.target, 4),
        }


def members(candidate) -> list[tuple[int, object, str]]:
    """The two paragraphs the finding names, in the order it names them."""
    issue = getattr(candidate, "issue", None)
    references = tuple(getattr(issue, "paragraph_refs", ()) or ())
    if len(references) != PARAGRAPHS_PER_FINDING:
        return []
    by_reference: dict[str, tuple[int, object]] = {}
    for index, paragraph in enumerate(candidate.page.pdf_paragraph or ()):
        by_reference[paragraph_reference(candidate.page_index, index)] = (
            index,
            paragraph,
        )
    found = []
    for reference in references:
        entry = by_reference.get(reference)
        if entry is None:
            return []
        found.append((entry[0], entry[1], reference))
    return found


def escape_distances(
    box, other_box, axis_index: int, target: float, min_area: float
) -> tuple[float, float]:
    """How far along one axis the boxes must part for coverage to reach ``target``.

    Returned as the two directions, low side first.

    Coverage is the shared area over the smaller area, and a slide changes
    neither area: it shortens the overlap along the axis it moves on and leaves
    the other one alone. So what has to be found is the overlap along that axis
    which brings the shared area under the target, and then the distance that
    produces it.

    That distance is not the amount the two currently overlap. Two boxes meeting
    edge to edge part by exactly the distance they are moved, but a small box
    standing wholly inside a large one overlaps by its own whole width however
    far it moves, until its trailing edge passes the large box's edge. Reading
    the current overlap as the distance would report a folio inside a contents
    entry as needing a few points to clear when what it needs is the distance to
    the edge of the entry, and the slide would move it and resolve nothing.

    So each direction is solved from the edges. Leaving towards the low side,
    the shared span becomes the mover's trailing edge less the other's leading
    one; towards the high side, the other's trailing edge less the mover's
    leading one. Both are returned, and the caller takes the cheaper.
    """
    across = overlaps(box, other_box)[1 - axis_index]
    if across <= 0:
        return 0.0, 0.0
    allowed = target * min_area / across
    low, high = box[axis_index], box[axis_index + 2]
    other_low, other_high = other_box[axis_index], other_box[axis_index + 2]
    return (
        max(0.0, (high - other_low) - allowed),
        max(0.0, (other_high - low) - allowed),
    )


def plan(candidate, action: Action, config) -> tuple[str, Separation | None, dict]:
    """What separating this pair would take, whether it may be done, and why."""
    pair = members(candidate)
    if not pair:
        return REASON_PAIR, None, {}
    boxes = [ink_box(paragraph) for _index, paragraph, _reference in pair]
    if any(box is None for box in boxes):
        return REASON_NO_INK, None, {}
    frame = detector_base.page_frame(candidate.page)
    if frame is None:
        return REASON_NO_FRAME, None, {}

    areas = [area(box) for box in boxes]
    if min(areas) <= 0:
        return REASON_NO_INK, None, {}
    smaller = 0 if areas[0] <= areas[1] else 1
    mover_index, mover, mover_reference = pair[smaller]
    _other_index, _other, other_reference = pair[1 - smaller]
    box = boxes[smaller]
    other_box = boxes[1 - smaller]
    ratio = areas[smaller] / areas[1 - smaller]

    along = overlaps(box, other_box)
    if along[0] <= 0 or along[1] <= 0:
        return REASON_SEPARATE, None, {}
    bounds, _frame_source = frame
    target = max(0.0, config.collision_min_coverage - margin(action))

    # Both axes and both directions, and the cheapest of the four wins. The
    # smallest movement that ends the overlap is the one least likely to walk
    # into anything else and least visible where it is wrong, and which axis
    # that is cannot be read off the overlap alone: a box standing inside
    # another overlaps it by its own whole width and its own whole height, and
    # what separates them is how near it is to an edge.
    options = []
    for axis in (0, 1):
        low_way, high_way = escape_distances(box, other_box, axis, target, min(areas))
        options.append((low_way, axis, -1.0))
        options.append((high_way, axis, 1.0))
    distance, axis_index, sign = min(options, key=lambda option: option[0])
    # Solved exactly, the distance lands the overlap on the target rather than
    # under it, and which side of the target the result then falls on is decided
    # by the last bit of the arithmetic. The slide is overshot by the
    # representation error of the coordinates it is computed from, which is the
    # same allowance the containment action measures its own result by and is
    # arithmetic rather than a bound anybody chose.
    if distance > 0:
        distance += arithmetic_slack(box)

    if distance <= 0:
        # Nothing to travel: the pair the detector reported has since fallen
        # below what a slide would aim at, which happens when an earlier repair
        # of the same iteration moved one of them. Accepting it would count an
        # application that wrote nothing and add a paragraph to the touched set
        # that no digest will show as changed.
        return REASON_ALREADY, None, {}

    page_extent = (bounds[2] - bounds[0], bounds[3] - bounds[1])[axis_index]
    limit = max_shift_ratio(action) * page_extent
    shift = (sign * distance, 0.0) if axis_index == 0 else (0.0, sign * distance)

    found = Separation(
        mover_index=mover_index,
        mover_reference=mover_reference,
        other_reference=other_reference,
        axis=AXIS_X if axis_index == 0 else AXIS_Y,
        shift=shift,
        box=box,
        other_box=other_box,
        area_ratio=ratio,
        limit=limit,
        coverage_before=detector_base.coverage(box, other_box),
        iou_before=detector_base.intersection_over_union(box, other_box),
        target=target,
    )
    if ratio > max_area_ratio(action):
        return REASON_AREA, found, {}
    if distance > limit:
        return REASON_SHIFT, found, {}

    landing = found.projected
    safe = detector_base.inset(bounds, config.page_safety_margin_ratio)
    amounts = detector_base.overflow(landing, safe)
    before = standing_on(candidate, mover_index, box, config)
    trace: dict = {
        "collision_min_iou": config.collision_min_iou,
        "collision_min_coverage": config.collision_min_coverage,
        "standing_on_before": references(candidate, before),
    }
    if max(amounts.values()) > 0:
        trace["refused"] = GUARD_OFF_PAGE
        trace["overflow_projected"] = {
            side: round(value, 4) for side, value in amounts.items()
        }
        return REASON_LEAVES_PAGE, found, trace

    after = standing_on(candidate, mover_index, landing, config)
    new = sorted(set(after) - set(before))
    trace["standing_on_projected"] = references(candidate, after)
    trace["induced_projected"] = references(candidate, new)
    if new:
        trace["refused"] = GUARD_INDUCED
        return REASON_INDUCED, found, trace
    return ACCEPTED, found, trace


def standing_on(candidate, mover_index: int, box, config) -> list[int]:
    """Which other paragraphs of the page a box at these coordinates stands on.

    By either measure, which is the detector's question rather than the
    containment guard's: the overlap this action exists to repair is the one the
    ratio over the union does not report, so a guard reading that ratio alone
    would be blind to the overlap it is most likely to create.
    """
    found: list[int] = []
    for index, other in enumerate(candidate.page.pdf_paragraph or ()):
        if index == mover_index:
            continue
        if not detector_base.rendered_text(other).strip():
            continue
        other_box, _source = detector_base.rendered_box(other)
        if other_box is None:
            continue
        if stands_on(
            box, other_box, config.collision_min_iou, config.collision_min_coverage
        ):
            found.append(index)
    return found


def references(candidate, indices) -> list[str]:
    """Paragraph indices as the references every report names paragraphs by."""
    return [
        paragraph_reference(candidate.page_index, index) for index in sorted(indices)
    ]


def admits(issue, candidate, action: Action, context) -> str:
    """Why this finding is not one to act on, or ``ACCEPTED``.

    Stricter than the detector, and stricter in the direction the detector
    cannot be. The detector reports an overlap wherever either measure sees one,
    because a defect left unreported is a defect nobody can act on. This refuses
    every overlap it cannot name one member of as the one to move, and every
    overlap that clearing would take further than a paragraph that merely
    drifted could have travelled, because a paragraph moved wrongly is worse
    than an overlap left standing.

    It reads coverage alone, and does not restate the detector's other bound.
    See the module docstring: a pair the union ratio admits and coverage does
    not is forced to be two boxes of nearly one size, which the asymmetry bound
    below refuses anyway, so stating it would state a filter that selects
    nothing.
    """
    bound = applicability(action)
    if bound is None:
        return REASON_NO_BOUND
    covered = issue.evidence.get("coverage")
    if not isinstance(covered, int | float) or float(covered) < bound:
        return REASON_MEASURE
    return plan(candidate, action, context.config)[0]


def separate(candidate, action: Action, config):
    """Plan one separation. What to record, the plan, and what it would move."""
    verdict, found, trace = plan(candidate, action, config)
    outcome = Application(
        issue_id=candidate.issue_id,
        reference=candidate.reference if found is None else found.mover_reference,
        accepted=False,
        reason=verdict,
        source_text=candidate.source_text,
        geometry={} if found is None else found.as_record(),
    )
    if trace:
        outcome.geometry["guard"] = trace
    if verdict != ACCEPTED or found is None:
        return outcome, None
    return outcome, found


@dataclass(frozen=True)
class _Slide:
    """A pure translation in the shape the shared transform expects.

    The containment action's map scales about an anchor and then slides; this
    one only slides, which is that map with a unit scale, so both go through one
    implementation rather than two that could drift apart.
    """

    shift: tuple[float, float]
    scale: float = 1.0
    anchor: tuple[float, float] = (0.0, 0.0)


def move(paragraph, found: Separation) -> None:
    """Slide one paragraph's ink by the plan, through the shared affine map."""
    transform(paragraph, _Slide(found.shift))


def finish(candidate, outcome: Application, found: Separation, config) -> Application:
    """Measure the moved paragraph on the document and accept or refuse it.

    On the document rather than on the arithmetic the plan was chosen by, for
    the same reason the containment action measures its own result: what has to
    be true is that the finished page no longer carries the overlap, and that is
    a fact about the page.
    """
    record = outcome.geometry
    after = ink_box(candidate.page.pdf_paragraph[found.mover_index])
    record["box_after"] = None if after is None else [round(v, 4) for v in after]
    if after is None:
        outcome.reason = REASON_NO_INK
        return outcome
    covered = detector_base.coverage(after, found.other_box)
    record["coverage_after"] = round(covered, 4)
    record["iou_after"] = round(
        detector_base.intersection_over_union(after, found.other_box), 4
    )
    if covered >= found.target:
        outcome.reason = REASON_NOT_RESOLVED
        return outcome
    guard = record.setdefault("guard", {})
    before = guard.get("standing_on_before", [])
    landed = references(
        candidate, standing_on(candidate, found.mover_index, after, config)
    )
    guard["standing_on_after"] = landed
    induced = sorted(set(landed) - set(before))
    guard["induced"] = induced
    if induced:
        outcome.reason = REASON_INDUCED
        return outcome
    outcome.accepted = True
    outcome.changed = True
    outcome.reason = ACCEPTED
    return outcome
