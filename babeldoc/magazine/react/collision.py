"""The action for two texts standing in one place, which in v1 moves nothing.

An action that does nothing is still worth declaring, and this one is declared
for two reasons.

It closes the vocabulary honestly. The deciding model is shown every finding the
detectors made, and a kind of finding no action answers for is a kind the model
is invited to answer with an action meant for something else. Declaring the
action that owns this kind is what makes "there is nothing to do about it yet" a
statement the vocabulary can carry.

And it produces the escalation list. A finding named in a decision is recorded
with why it was not acted on, which is the same channel every other refusal
travels by, so the run's sidecar carries the collisions a human should look at
rather than losing them between a detector that reported them and an action that
declined them.

Why it moves nothing
--------------------

Because the causes are not one cause, and the answers are opposite. A display
headline painted twice in the source and grown apart by the translation wants
one layer suppressed. A caption that grew into the column beside it wants
setting smaller or its column widened. A folio printed inside a contents entry
wants neither, because it was always there and the entry moved. Moving a
paragraph blindly costs more than leaving the overlap: the overlap is legible
under inspection and a paragraph moved to the wrong place is not recoverable
from the finished page at all.

The finding carries which of those it is only after the census that sorts them,
and that census is the acceptance work of this batch's second session. So the
applicability rule here admits nothing to be moved, and admits a finding to the
escalation list at or above the overlap the rule declares.
"""

from __future__ import annotations

from babeldoc.magazine.react.config import MIN_COLLISION_IOU_KEY
from babeldoc.magazine.react.config import Action

NAME = "resolve_collision"

# One finding, two paragraphs: an overlap is a statement about a pair.
PARAGRAPHS_PER_FINDING = 2

# Why a finding was not acted on. The first is the whole of this action in v1;
# the second is a finding whose overlap is under the bound the rule declares,
# which is not one worth a human's attention either.
REASON_REPORT_ONLY = "reported_for_review_no_automatic_action_in_this_version"
REASON_IOU = "collision_iou_below_bound"


def applicability(action: Action) -> float:
    return float(action.applicability[MIN_COLLISION_IOU_KEY])


def admits(issue, candidate, action: Action) -> str:  # noqa: ARG001 - the paragraph is part of the question every action is asked
    """Always a refusal, and which refusal says whether a human should look.

    Never ``ACCEPTED``: this action writes nothing, so admitting a finding would
    be admitting it to a mechanism that does not exist. What the two reasons
    separate is the finding worth escalating from the finding under the bound.
    """
    iou = issue.evidence.get("iou")
    if not isinstance(iou, int | float) or float(iou) < applicability(action):
        return REASON_IOU
    return REASON_REPORT_ONLY
