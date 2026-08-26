"""Column level reflow: the white space a shorter translation leaves behind.

The typesetting stage lays every paragraph out inside the box the source drew
for it and moves no box, so the vertical rhythm of a finished page is the source
page's rhythm. That is what keeps a translated page recognisable, and it is also
where this defect comes from: a translation that sets shorter than its source
fills less of its box, and the difference stands as white space between it and
the paragraph below. Measured over the corpus the difference is not small -- on
a running text page it is routinely tens of points, unevenly spread -- so a
column comes out alternating tight bands with holes the source never had.

What is closed, and what is not
-------------------------------

The excess, and only the excess. For each adjacent pair of paragraphs in a
column the pass takes the gap on the finished page, subtracts the gap the same
pair had on the source page, and raises the lower paragraph by the difference
where the difference is over the declared floor. A gap the source itself set
wide -- a section break, the air under a crosshead -- has no excess and is left
exactly as it is, so the pass has no opinion about layout: it only removes what
the translation added.

Because every gap ends at or above its source value and never below it, and
because the top member of a column never moves, a reflowed column cannot
collide with itself and cannot rise out of its own top. That is a property of
the arithmetic rather than a check, but it is checked as well; see the guards.

Where this sits and why
-----------------------

After the typesetting stage, which is the point at which the geometry a
paragraph renders at is final, and after the heading policy, which is the last
pass that moves any of it. Nothing upstream is changed to reach that point: the
pass is called from ``detectors.detect_issues``, the one piece of extension
owned code the pipeline runs in that window, on the same footing as the heading
policy beside it. Its own switch is ``magazine_column_reflow`` and it is down by
default; with it down this module returns having read nothing.

The narrowing is triple, and each part of it is declared rather than written
here: the repair profiles whose pages are reflowed, the target languages the
pass runs for, and the axis, which is vertical only -- no box changes width, and
no box changes its horizontal position.

What is never moved
-------------------

Anything that is not a paragraph this pass can account for. Figures, rules,
curves, forms and the characters a page carries outside any paragraph stay where
they are, and a gap with any of them standing in it is not empty space: it is
never closed, and nothing below it rises through it. A paragraph holding a
formula is the same case seen from the other side -- the stage hands a formula's
curves to the *page* rather than to the paragraph, so moving such a paragraph
would leave its own artwork behind -- and it anchors the column instead.

A paragraph drawn inside a form rather than onto the page is anchored for a
third reason of the same shape: a form is one drawing placed on however many
pages ask for it, so its coordinates are shared, and raising it on one page
raises it on all of them.

A paragraph the source checkpoint does not carry has no source gap to converge
to, so it takes no part as a member; it takes part as an obstacle, because it is
ink that does not move.

Why a column cannot collide with what it did not move
----------------------------------------------------

Every gap ends at or above the value the source set for it, and anything
standing in a gap holds that gap open, so a raised paragraph reaches no ink it
was not already reaching. What is left for the page level check to catch is a
detector that reads more than one band at a time -- a cluster rule measuring
proximity across a page rather than an overlap inside a column -- and that is
what the page is detected before and after for.

Fail open
---------

By column: a guard that trips leaves that column exactly as the stage left it,
and the sidecar records which guard. By page: the pass detects the page before
and after, and a page that gained a finding is put back in full. Nothing here is
worth a defect, and every revert restores the stored coordinates rather than
adding the shift back, so a reverted page is the page the stage produced down to
the last bit.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import is_dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il.il_version_1 import Box
from babeldoc.magazine import acceptance
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import fixed_assets
from babeldoc.magazine import hitl
from babeldoc.magazine.detectors import base
from babeldoc.magazine.detectors import source_geometry as source_geometry_module
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.line_split import holds_formula
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.runtime_profile import record_runtime_blocked_reason
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest
from babeldoc.magazine.transaction import TransactionSnapshot

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "column_reflow.json"

REPORT_NAME = "column_reflow.report.json"

# The switch, by the name the caller sets on the translation config.
SWITCH = "magazine_column_reflow"

# The switch this pass rides, because the window it has to run in holds no other
# extension owned call. Named here so the report says what it depended on.
WINDOW_SWITCH = "magazine_detect"

# Structural sections of the configuration: vocabularies validated against what
# they name rather than against a numeric range.
PROFILES_KEY = "profiles"
TARGETS_KEY = "target_languages"
OBSTACLES_KEY = "obstacle_collections"
PROTECTED_LABELS_KEY = "protected_paragraph_labels"

# The policy flag a page selects this pass with. The same flag detection selects
# its detectors by; no page type is named here.
REPAIR_PROFILE_POLICY_FLAG = base.REPAIR_PROFILE_POLICY_FLAG

# How a language tag is separated into subtags, and what is read as a separator
# before it is matched. The rule the rest of the extension resolves a target
# language under: a tag claims a prefix when it is that prefix or a subtag of it.
_SUBTAG_SEPARATOR = "-"
_SUBTAG_ALIASES = ("_",)

# Slack allowed when a measurement is compared with itself after arithmetic, in
# points. Not a tuning parameter: it is the width of a float, and a threshold
# anyone would tune is declared in the configuration instead.
_EPSILON = 1e-6

# Why one member of a column did or did not move.
REASON_TOP = "column_top"
REASON_CONVERGED = "converged"
REASON_BELOW_FLOOR = "excess_below_floor"
REASON_FORMULA = "formula_anchor"
REASON_XOBJECT = "xobject_anchor"
REASON_OBSTACLE = "obstacle_in_gap"

# The guards, each the name of a column that was planned and then left alone.
GUARD_SOURCE_ORDER = "source_order_disagrees"
GUARD_SHIFT_CAP = "shift_over_cap"
GUARD_MONOTONIC = "order_not_preserved"
GUARD_GAP = "gap_below_source"
GUARD_FRAME = "outside_page_frame"
GUARD_COLUMN_TOP = "above_column_top"

# The page level guard, which is not about one column's arithmetic but about
# what the whole page detects as afterwards.
GUARD_NEW_FINDING = "new_finding_after_shift"
GUARD_FIXED_ASSET = "fixed_asset_changed"
GUARD_DROP_CAP_ANCHOR = "drop_cap_anchor_changed"

GAP_ISSUE_KIND = "abnormal_blank_area"
GAP_ISSUE_DETECTOR = "column_gap"

# Why a page carrying the profile was not reflowed at all.
SKIP_NO_SOURCE = "no_source_geometry"
SKIP_NO_COLUMN = "no_reflowable_column"
SKIP_UNSUPPORTED = "unsupported_article_page"


class ColumnReflowError(ConfigError):
    """Raised when the column reflow configuration is malformed."""


@dataclass(frozen=True)
class ReflowConfig:
    """Everything bounded about closing one column's excess."""

    profiles: tuple[str, ...]
    target_languages: tuple[str, ...]
    obstacle_collections: tuple[str, ...]
    min_excess_pt: float
    max_shift_ratio: float
    column_min_x_overlap_ratio: float
    order_tolerance_pt: float
    asset_bbox_tolerance_pt: float
    protected_paragraph_labels: tuple[str, ...]

    def claims(self, target_lang: str | None) -> bool:
        """Whether this pass runs for one target language tag."""
        if not target_lang:
            return False
        tag = target_lang.strip().lower()
        for alias in _SUBTAG_ALIASES:
            tag = tag.replace(alias, _SUBTAG_SEPARATOR)
        return any(
            tag == prefix or tag.startswith(prefix + _SUBTAG_SEPARATOR)
            for prefix in (name.strip().lower() for name in self.target_languages)
        )

    def selects(self, policy: Mapping[str, object] | None) -> bool:
        """Whether a page carrying this policy is reflowed."""
        if policy is None:
            return False
        return policy.get(REPAIR_PROFILE_POLICY_FLAG) in self.profiles


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ColumnReflowError(message)


def _declared_profiles() -> set[str]:
    """Every repair profile the page type vocabulary declares."""
    taxonomy = load_taxonomy()
    return {
        str(page_type.policy.get(REPAIR_PROFILE_POLICY_FLAG))
        for page_type in taxonomy.page_types
        if page_type.policy.get(REPAIR_PROFILE_POLICY_FLAG) is not None
    }


def _declared_collections() -> set[str]:
    """Every page level collection an obstacle may be read from."""
    from babeldoc.format.pdf.document_il.il_version_1 import Page

    return {field.name for field in Page.__dataclass_fields__.values()}


def parse_reflow_config(raw: dict, source: str) -> ReflowConfig:
    """Validate one configuration mapping into the policy it declares."""
    try:
        parameters = dict(validate_bounded_config(raw, CONFIG_PATH))
    except ConfigError as exc:
        raise ColumnReflowError(str(exc)) from exc

    for key in (PROFILES_KEY, TARGETS_KEY, OBSTACLES_KEY, PROTECTED_LABELS_KEY):
        _require(key in parameters, f"{source}: missing {key}")

    profiles = tuple(parameters[PROFILES_KEY])
    declared = _declared_profiles()
    unknown = sorted(set(profiles) - declared)
    _require(
        not unknown,
        f"{source}: {PROFILES_KEY} names repair profiles {unknown} that no page "
        f"type declares; declared are {sorted(declared)}",
    )

    collections = tuple(parameters[OBSTACLES_KEY])
    fields = _declared_collections()
    absent = sorted(set(collections) - fields)
    _require(
        not absent,
        f"{source}: {OBSTACLES_KEY} names {absent}, which a page does not carry",
    )
    missing_fixed = sorted(set(fixed_assets.PAGE_ASSET_COLLECTIONS) - set(collections))
    _require(
        not missing_fixed,
        f"{source}: {OBSTACLES_KEY} omits fixed collections {missing_fixed}",
    )

    return ReflowConfig(
        profiles=profiles,
        target_languages=tuple(parameters[TARGETS_KEY]),
        obstacle_collections=collections,
        min_excess_pt=float(parameters["min_excess_pt"]),
        max_shift_ratio=float(parameters["max_shift_ratio"]),
        column_min_x_overlap_ratio=float(parameters["column_min_x_overlap_ratio"]),
        order_tolerance_pt=float(parameters["order_tolerance_pt"]),
        asset_bbox_tolerance_pt=float(parameters["asset_bbox_tolerance_pt"]),
        protected_paragraph_labels=tuple(parameters[PROTECTED_LABELS_KEY]),
    )


@lru_cache(maxsize=2)
def load_reflow_config(path: str | None = None) -> ReflowConfig:
    """Load and validate ``configs/column_reflow.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_reflow_config(raw, config_path.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def ink_box(paragraph) -> tuple[float, float, float, float] | None:
    """The extent of the ink one paragraph puts on the page.

    The same measurement detection reads a finished paragraph by, so a gap this
    pass closes and a collision a detector reports are measured off one number.
    """
    box, _source = base.rendered_box(paragraph)
    return box


PAGE_XOBJECT_IDS = (None, 0)


def inside_xobject(paragraph) -> bool:
    """Whether a paragraph is drawn inside a form rather than onto the page.

    A form is one drawing placed wherever a page asks for it, and several pages
    routinely ask for the same one: the running folio of this corpus is drawn
    once and placed on every page of its section. Its coordinates are the form's
    own, so moving them moves the folio on every page that places it, including
    pages this pass never looked at. Such a paragraph is left where it is and
    stands as an obstacle like any other ink the pass does not move.

    A character carrying no form id at all was inserted by the pipeline rather
    than read off a content stream, and belongs to whatever the paragraph around
    it belongs to; it is the non zero ids that are decisive.
    """
    if getattr(paragraph, "xobj_id", None) not in PAGE_XOBJECT_IDS:
        return True
    return any(
        getattr(character, "xobj_id", None) not in PAGE_XOBJECT_IDS
        for character in paragraph_characters(paragraph)
    )


def _boxes_of(node, seen: set[int] | None = None) -> list[Box]:
    """Every coordinate box reachable from one intermediate language node.

    Walked rather than listed, because a paragraph carries its coordinates in
    several places -- its own box, the box of each composition holder, each
    character's box and the visual box beside it -- and a shift that reached
    some of them and not others would leave the document disagreeing with
    itself about where the paragraph is.
    """
    seen = set() if seen is None else seen
    if id(node) in seen:
        return []
    seen.add(id(node))
    if isinstance(node, Box):
        return [node]
    found: list[Box] = []
    if is_dataclass(node):
        for field in type(node).__dataclass_fields__:
            found.extend(_boxes_of(getattr(node, field, None), seen))
    elif isinstance(node, list | tuple):
        for item in node:
            found.extend(_boxes_of(item, seen))
    return found


def snapshot(paragraph) -> list[tuple[Box, float | None, float | None]]:
    """Where every box of one paragraph stands, so it can be put back exactly."""
    return [(box, box.y, box.y2) for box in _boxes_of(paragraph)]


def raise_by(
    paragraph, distance: float
) -> list[tuple[Box, float | None, float | None]]:
    """Move one paragraph up the page, returning what it stood at before."""
    stored = snapshot(paragraph)
    for box, y, y2 in stored:
        if y is not None:
            box.y = y + distance
        if y2 is not None:
            box.y2 = y2 + distance
    return stored


def restore(stored) -> None:
    """Put every box back at the coordinate it was read at."""
    for box, y, y2 in stored:
        box.y = y
        box.y2 = y2


def shared_width(left, right) -> float:
    """How much of one horizontal band two boxes have in common."""
    return min(left[2], right[2]) - max(left[0], right[0])


def same_measure(left, right, ratio: float) -> bool:
    """Whether two boxes are set to the same measure, and so stand in one column.

    Measured against the wider of the two rather than the narrower, which is
    what keeps a paragraph set across the page -- a crosshead over two columns,
    a pull quote spanning the measure -- from joining a column it merely covers
    and, through it, joining that column to its neighbour.
    """
    width = shared_width(left, right)
    if width <= 0:
        return False
    wider = max(left[2] - left[0], right[2] - right[0])
    return wider > 0 and width / wider >= ratio


def intrudes(box, left, right, ratio: float) -> bool:
    """Whether one box reaches into the horizontal band two boxes occupy.

    Against the narrower of the band and the box, because a small object
    standing wholly inside the band is as much in the way as a wide one lying
    across it.
    """
    band = (min(left[0], right[0]), 0.0, max(left[2], right[2]), 0.0)
    width = shared_width(band, box)
    if width <= 0:
        return False
    narrower = min(band[2] - band[0], box[2] - box[0])
    return narrower > 0 and width / narrower >= ratio


def columns(members, ratio: float) -> list[list]:
    """One page's paragraphs grouped into columns by the measure they are set to.

    Grouped by the band each paragraph occupies rather than by a declared column
    count, because the column a paragraph is in is a fact about the paragraph
    and the count is an estimate about the page.
    """
    groups: list[list] = []
    spans: list[tuple[float, float]] = []
    for member in sorted(members, key=lambda item: item.box[0]):
        placed = False
        for position, span in enumerate(spans):
            if same_measure((span[0], 0.0, span[1], 0.0), member.box, ratio):
                groups[position].append(member)
                spans[position] = (
                    min(span[0], member.box[0]),
                    max(span[1], member.box[2]),
                )
                placed = True
                break
        if not placed:
            groups.append([member])
            spans.append((member.box[0], member.box[2]))
    return groups


@dataclass
class Member:
    """One paragraph of a column, as this pass reads and moves it."""

    index: int
    reference: str
    paragraph: object
    box: tuple[float, float, float, float]
    source: tuple[float, float, float, float]
    movable: bool
    # How far up the page this member is to be raised. Written by the plan and
    # read by the guards and by the application, so one number answers for a
    # member from the moment it is decided.
    shift: float = 0.0


def obstacle_boxes(
    page,
    config: ReflowConfig,
    members: set[int],
    inventory: fixed_assets.FixedAssetInventory | None = None,
    label: int | None = None,
) -> list[tuple]:
    """Every box on one page holding ink one column does not move.

    The declared page level collections, plus every paragraph outside this
    column: one set aside for having no source counterpart, one belonging to
    another column, one the pass never reads as a member at all. Each of them is
    ink that stays where it is, which is the whole of what makes it an obstacle.
    """
    boxes = []
    if inventory is not None and label is not None:
        boxes.extend(
            asset.bbox
            for asset in inventory.page_assets(label)
            if asset.protected and asset.bbox is not None
        )
    else:
        for name in config.obstacle_collections:
            for item in getattr(page, name, None) or ():
                box = base.box_tuple(getattr(item, "box", None))
                if box is not None:
                    boxes.append(box)
    for index, paragraph in enumerate(page.pdf_paragraph or ()):
        if index in members:
            continue
        box = ink_box(paragraph)
        if box is not None:
            boxes.append(box)
    return boxes


def blocked(upper, lower, obstacles, ratio: float) -> bool:
    """Whether anything stands in the band between two paragraphs of a column.

    An object covering the pair from above the upper to below the lower is not
    standing between them: it is what they are printed on -- a tint panel, the
    rule box of a sidebar, the artwork a caption is set over -- and both of them
    keep their place on it however the space between them changes. Everything
    else whose extent reaches into the band is in the way, and the gap it stands
    in is not the translation's to close.
    """
    top = upper.box[1]
    bottom = lower.box[3]
    if top <= bottom:
        return False
    for box in obstacles:
        if box[1] >= top or box[3] <= bottom:
            continue
        if box[3] >= upper.box[3] and box[1] <= lower.box[1]:
            continue
        if intrudes(box, upper.box, lower.box, ratio):
            return True
    return False


def source_order_holds(members, tolerance: float) -> bool:
    """Whether the source drew these paragraphs in the order the page shows them."""
    tops = [member.source[3] for member in members]
    return all(
        later <= earlier + tolerance
        for earlier, later in zip(tops, tops[1:], strict=False)
    )


def plan_column(members, obstacles, config: ReflowConfig) -> dict:
    """What one column would move, and what it would look like afterwards.

    Returns the record of the column whether or not it is applied: a column left
    alone is as much of an answer as a column closed, and the sidecar carries
    both.
    """
    height = members[0].box[3] - members[-1].box[1]
    cap = config.max_shift_ratio * height
    rows = []
    accumulated = 0.0
    for position, member in enumerate(members):
        own = 0.0
        if position == 0:
            reason = REASON_TOP
            accumulated = 0.0
            gap = None
            source_gap = None
            excess = None
        else:
            upper = members[position - 1]
            gap = upper.box[1] - member.box[3]
            source_gap = upper.source[1] - member.source[3]
            excess = gap - source_gap
            if not member.movable:
                reason = (
                    REASON_FORMULA
                    if holds_formula(member.paragraph)
                    else REASON_XOBJECT
                )
                accumulated = 0.0
            elif blocked(upper, member, obstacles, config.column_min_x_overlap_ratio):
                reason = REASON_OBSTACLE
                accumulated = 0.0
            elif excess > config.min_excess_pt:
                own = min(excess, cap)
                reason = REASON_CONVERGED
            else:
                reason = REASON_BELOW_FLOOR
        accumulated += own
        rows.append(
            {
                "reference": member.reference,
                "reason": reason,
                "own_shift": round(own, 4),
                "shift": round(accumulated, 4),
                "gap": None if gap is None else round(gap, 4),
                "source_gap": None if source_gap is None else round(source_gap, 4),
                "excess": None if excess is None else round(excess, 4),
                "excess_after": None if excess is None else round(excess - own, 4),
            }
        )
        member.shift = accumulated
    excesses = [row["excess"] for row in rows if row["excess"] is not None]
    after = [row["excess_after"] for row in rows if row["excess_after"] is not None]
    return {
        "x": round(min(member.box[0] for member in members), 4),
        "x2": round(max(member.box[2] for member in members), 4),
        "height": round(height, 4),
        "cap": round(cap, 4),
        "members": [row["reference"] for row in rows],
        "rows": rows,
        "moved": sum(1 for row in rows if row["shift"] > 0),
        "shift_total": round(sum(row["own_shift"] for row in rows), 4),
        "bottom_slack_gain": rows[-1]["shift"],
        "excess_sum_before": round(sum(abs(value) for value in excesses), 4),
        "excess_sum_after": round(sum(abs(value) for value in after), 4),
        "excess_median_before": (
            None if not excesses else round(statistics.median(excesses), 4)
        ),
        "excess_median_after": (
            None if not after else round(statistics.median(after), 4)
        ),
        "guard": None,
        "applied": False,
    }


def guard_column(members, cap: float, frame) -> str | None:
    """Which guard, if any, refuses the planned column. None where none does.

    Read off the members' own coordinates rather than off the record beside
    them, because the record rounds what it reports for a reader and a guard
    that compared a rounded number with an exact one would refuse arithmetic
    that is correct. Every check is about what the shift does: a paragraph the
    stage already placed outside the page is not this pass's finding, and is
    refused a shift rather than reported as one.
    """
    top = members[0].box[3]
    previous = None
    for member in members:
        moved_top = member.box[3] + member.shift
        if member.shift < -_EPSILON:
            return GUARD_SHIFT_CAP
        if member.shift > _EPSILON:
            if moved_top > top + _EPSILON:
                return GUARD_COLUMN_TOP
            if frame is not None and moved_top > frame[3] + _EPSILON:
                return GUARD_FRAME
        if previous is not None:
            if member.shift > previous.shift + cap + _EPSILON:
                return GUARD_SHIFT_CAP
            if moved_top > previous.box[3] + previous.shift + _EPSILON:
                return GUARD_MONOTONIC
            gap = previous.box[1] - member.box[3]
            source_gap = previous.source[1] - member.source[3]
            gap_after = (previous.box[1] + previous.shift) - moved_top
            if gap_after < min(gap, source_gap) - _EPSILON:
                return GUARD_GAP
        previous = member
    return None


def page_members(page, label: int, source_geometry, protected_refs=frozenset()):
    """Every paragraph of one page this pass may move, and its source box."""
    members = []
    for index, paragraph in enumerate(page.pdf_paragraph or ()):
        box = ink_box(paragraph)
        reference = paragraph_reference(label, index)
        source = (
            source_geometry.box_for(reference)
            if hasattr(source_geometry, "box_for")
            else source_geometry.box_of(paragraph)
        )
        if reference in protected_refs:
            continue
        if box is None or source is None:
            continue
        members.append(
            Member(
                index=index,
                reference=reference,
                paragraph=paragraph,
                box=box,
                source=source,
                movable=not holds_formula(paragraph) and not inside_xobject(paragraph),
            )
        )
    return members


def plan_page(
    page,
    label: int,
    source_geometry,
    config: ReflowConfig,
    fixed_inventory: fixed_assets.FixedAssetInventory | None = None,
) -> dict:
    """Every column of one page, planned and guarded but not yet applied."""
    protected_refs = (
        frozenset()
        if fixed_inventory is None
        else fixed_inventory.protected_paragraph_refs
    )
    members = page_members(page, label, source_geometry, protected_refs)
    frame = base.page_frame(page)
    frame_box = None if frame is None else frame[0]
    records = []
    for group in columns(members, config.column_min_x_overlap_ratio):
        if len(group) < 2:
            continue
        group.sort(key=lambda member: -member.box[3])
        obstacles = obstacle_boxes(
            page,
            config,
            {member.index for member in group},
            fixed_inventory,
            label,
        )
        record = plan_column(group, obstacles, config)
        if not source_order_holds(group, config.order_tolerance_pt):
            record["guard"] = GUARD_SOURCE_ORDER
        else:
            record["guard"] = guard_column(group, record["cap"], frame_box)
        record["applied"] = record["guard"] is None and record["moved"] > 0
        record["page"] = label
        records.append((record, group))
    return {"members": members, "columns": records}


def _page_issues(page, label: int, translation_config, source_geometry) -> list:
    """Every page level finding of one page.

    Detection is what says whether a change made a page worse, so the pass asks
    it rather than deciding for itself. Document level detectors are left out:
    what they read is a sidecar about the whole document, and one page's
    geometry is not what they answer for.
    """
    from babeldoc.magazine import detectors

    config = detectors.detector_config()
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    view = base.PageView(
        label=label,
        page=page,
        policy=load_taxonomy().policy_of(getattr(page, "page_kind", None)),
    )
    context = base.DetectionContext(
        pages=[view],
        config=config,
        language=getattr(translation_config, "lang_out", None),
        translation_performed=not getattr(
            translation_config, "skip_translation", False
        ),
        working_dir=working_dir,
        source_geometry=source_geometry,
    )
    issues = detectors.run_detectors(context)
    return [
        issue for issue in issues if issue.detector not in config.document_detectors
    ]


def _coerce_issues(values, policy) -> list:
    return [
        acceptance.measured_issue(
            str(value),
            "injected_finding",
            policy.reject_new_at_or_above,
            {},
            (),
            schema_version=policy.schema_version,
        )
        if isinstance(value, str)
        else value
        for value in values
    ]


def _gap_issue(label: int, columns_of, key: str, policy) -> base.Issue:
    columns = [record for record, _group in columns_of if record["applied"]]
    references = tuple(
        sorted(
            {
                row["reference"]
                for column in columns
                for row in column["rows"]
                if row["shift"] > 0
            }
        )
    )
    evidence = {"excess_sum": round(sum(item[key] for item in columns), 4)}
    return base.Issue(
        kind=GAP_ISSUE_KIND,
        page=label,
        paragraph_refs=references,
        geometry=None,
        severity=policy.severity_order[0],
        evidence=evidence,
        detector=GAP_ISSUE_DETECTOR,
        severity_vector=base.SeverityVector.from_evidence(
            policy.severity_order[0], evidence, ("excess_sum",)
        ),
    )


def apply_page(
    page,
    label: int,
    translation_config,
    source_geometry,
    config,
    issues_of=None,
    fixed_inventory=None,
    inventory_after=None,
) -> dict:
    """Reflow one page's columns, and put the page back if it detected worse.

    What counts as a finding is read through ``issues_of``, which defaults to
    running detection over the page. It is a parameter so that the revert can be
    shown working against a reader that answers on demand: the arithmetic makes
    a collision inside one column band impossible, and what remains for this
    guard to catch is a detector reading more than one band at a time, which is
    not a shape a stub can be sure of building.
    """
    reader = _page_issues if issues_of is None else issues_of
    planned = plan_page(page, label, source_geometry, config, fixed_inventory)
    applicable = [
        (record, group) for record, group in planned["columns"] if record["applied"]
    ]
    record = {
        "page": label,
        "kind": getattr(page, "page_kind", None),
        "columns": [item[0] for item in planned["columns"]],
        "members": len(planned["members"]),
        "applied": False,
        "guard": None,
    }
    if not applicable:
        record["skipped"] = SKIP_NO_COLUMN
        record["action_status"] = "not_executed"
        return record

    policy = acceptance.load_acceptance_policy()
    before = _coerce_issues(
        reader(page, label, translation_config, source_geometry), policy
    )
    before_with_gap = [
        *before,
        _gap_issue(label, applicable, "excess_sum_before", policy),
    ]
    stored = []
    active_drop_caps = drop_cap_intent.active_protected_refs(
        translation_config,
        rendered_only=True,
    )
    anchors_before = {}
    for _column, group in applicable:
        for member in group:
            if member.shift > 0:
                if member.reference in active_drop_caps:
                    intent = drop_cap_intent.intent_for(
                        translation_config, member.reference
                    )
                    anchors_before[member.reference] = (
                        None
                        if intent is None
                        else drop_cap_intent.decorative_anchor_signature(
                            member.paragraph, intent
                        )
                    )
                stored.extend(raise_by(member.paragraph, member.shift))
    changed_anchors = []
    for _column, group in applicable:
        for member in group:
            if member.reference not in anchors_before:
                continue
            intent = drop_cap_intent.intent_for(
                translation_config, member.reference
            )
            after = (
                None
                if intent is None
                else drop_cap_intent.decorative_anchor_signature(
                    member.paragraph, intent
                )
            )
            if anchors_before[member.reference] is None or (
                after != anchors_before[member.reference]
            ):
                changed_anchors.append(member.reference)
    record["drop_cap_anchor_comparison"] = {
        "checked": sorted(anchors_before),
        "changed": sorted(set(changed_anchors)),
        "holds": not changed_anchors,
    }
    if changed_anchors:
        restore(stored)
        for column, _group in applicable:
            column["applied"] = False
            column["guard"] = GUARD_DROP_CAP_ANCHOR
        record["guard"] = GUARD_DROP_CAP_ANCHOR
        record["action_status"] = "rolled_back"
        return record
    if fixed_inventory is not None and inventory_after is not None:
        asset_comparison = fixed_assets.compare(
            fixed_inventory,
            inventory_after(),
            config.asset_bbox_tolerance_pt,
        )
        record["asset_guard"] = asset_comparison.to_record()
        if not asset_comparison.holds:
            restore(stored)
            for column, _group in applicable:
                column["applied"] = False
                column["guard"] = GUARD_FIXED_ASSET
            record["guard"] = GUARD_FIXED_ASSET
            record["action_status"] = "rolled_back"
            return record
    after = _coerce_issues(
        reader(page, label, translation_config, source_geometry), policy
    )
    after_with_gap = [
        *after,
        _gap_issue(label, applicable, "excess_sum_after", policy),
    ]
    comparison = acceptance.compare_issues(
        before_with_gap, after_with_gap, policy
    )
    record["acceptance"] = comparison.as_record()
    if not comparison.accepted:
        restore(stored)
        for column, _group in applicable:
            column["applied"] = False
            column["guard"] = GUARD_NEW_FINDING
        record["guard"] = GUARD_NEW_FINDING
        record["introduced_findings"] = list(comparison.new_ids)
        record["action_status"] = "rolled_back"
        return record
    record["applied"] = True
    record["action_status"] = "committed"
    record["findings_before"] = len(before)
    record["findings_after"] = len(after)
    return record


def as_record(
    config: ReflowConfig,
    pages: list[dict],
    target_lang: str,
    notes: list[str],
    *,
    source_geometry=None,
    prerequisite_issues=(),
) -> dict:
    """One run of this pass, as the sidecar carries it."""
    columns_of = [column for page in pages for column in page["columns"]]
    applied = [column for column in columns_of if column["applied"]]
    guards: dict[str, int] = {}
    for column in columns_of:
        if column["guard"] is not None:
            guards[column["guard"]] = guards.get(column["guard"], 0) + 1
    return {
        "switch": SWITCH,
        "window_switch": WINDOW_SWITCH,
        "target_lang": target_lang,
        "profiles": list(config.profiles),
        "target_languages": list(config.target_languages),
        "min_excess_pt": config.min_excess_pt,
        "max_shift_ratio": config.max_shift_ratio,
        "asset_bbox_tolerance_pt": config.asset_bbox_tolerance_pt,
        "source_geometry": (
            None if source_geometry is None else source_geometry.to_record()
        ),
        "prerequisite_issues": list(prerequisite_issues),
        "totals": {
            "pages_considered": len(pages),
            "pages_applied": sum(1 for page in pages if page["applied"]),
            "pages_reverted": sum(
                1
                for page in pages
                if page["guard"] in (GUARD_NEW_FINDING, GUARD_FIXED_ASSET)
            ),
            "columns": len(columns_of),
            "columns_applied": len(applied),
            "columns_left": len(columns_of) - len(applied),
            "paragraphs_moved": sum(column["moved"] for column in applied),
            "shift_total_pt": round(
                sum(column["shift_total"] for column in applied), 4
            ),
            "excess_sum_before": round(
                sum(column["excess_sum_before"] for column in applied), 4
            ),
            "excess_sum_after": round(
                sum(column["excess_sum_after"] for column in applied), 4
            ),
        },
        "guards": guards,
        "pages": pages,
        "notes": notes,
    }


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH, acceptance.CONFIG_PATH])
    return path


def apply(
    translation_config,
    docs,
    source_geometry=None,
    *,
    run_trace=None,
    fixed_inventory=None,
    article_document_ir=None,
) -> dict | None:
    """Close the excess of every reflowable column. None where the switch is down.

    Returns the record it wrote, so a caller that already holds the document can
    assert about the pass without reading the sidecar back. The source layout is
    read from the run's own working directory where none is supplied; a caller
    that already holds one supplies it instead.
    """
    if not enabled(translation_config):
        return None
    from babeldoc.magazine import detectors

    config = load_reflow_config()
    target_lang = getattr(translation_config, "lang_out", "") or ""
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    notes: list[str] = []
    pages: list[dict] = []
    if not config.claims(target_lang):
        notes.append(
            f"the target language {target_lang!r} is outside "
            f"{list(config.target_languages)}; no page was reflowed"
        )
        record = as_record(config, pages, target_lang, notes)
        record["transaction"] = {
            "status": "not_executed",
            "pages": [],
            "reason": "target_language_not_selected",
        }
        write_report(working_dir, record)
        return record

    taxonomy = load_taxonomy()
    if source_geometry is None:
        source_result = detectors.source_geometry_of(
            working_dir, detectors.detector_config(), run_trace=run_trace
        )
    elif isinstance(source_geometry, source_geometry_module.SourceGeometryResult):
        source_result = source_geometry
    else:
        source_result = source_geometry_module.SourceGeometryResult(
            status=source_geometry_module.SourceGeometryStatus.AVAILABLE,
            stage=source_geometry.stage,
            checkpoint=source_geometry.path,
            geometry=source_geometry,
        )
    source = source_result.geometry
    prerequisite_issue = source_result.issue()
    if prerequisite_issue is not None:
        record_runtime_blocked_reason(translation_config, prerequisite_issue)
        if run_trace is not None:
            run_trace.record_blocked_reason(prerequisite_issue)
    if fixed_inventory is None:
        fixed_inventory = fixed_assets.build_inventory(
            docs,
            article_document_ir=article_document_ir,
            run_trace=run_trace,
            protected_paragraph_labels=config.protected_paragraph_labels,
        )
    unsupported_pages = (
        {item.page for item in article_document_ir.unsupported_pages}
        if article_document_ir is not None
        else set(getattr(run_trace, "unsupported_pages", ()))
    )
    inventory_builder = lambda: fixed_assets.build_inventory(
        docs,
        article_document_ir=article_document_ir,
        run_trace=run_trace,
        protected_paragraph_labels=config.protected_paragraph_labels,
    )
    transaction = TransactionSnapshot.capture(
        docs,
        run_trace=run_trace,
        fixed_inventory=fixed_inventory,
        fixed_inventory_builder=inventory_builder,
    )
    if source is not None:
        transaction.begin_generation("column_reflow")
    failure = None
    for label, page in hitl.labeled_pages(docs):
        if not config.selects(taxonomy.policy_of(getattr(page, "page_kind", None))):
            continue
        if label in unsupported_pages:
            pages.append(
                {
                    "page": label,
                    "kind": getattr(page, "page_kind", None),
                    "columns": [],
                    "members": 0,
                    "applied": False,
                    "guard": None,
                    "skipped": SKIP_UNSUPPORTED,
                    "action_status": "not_executed",
                }
            )
            continue
        if source is None:
            pages.append(
                {
                    "page": label,
                    "kind": getattr(page, "page_kind", None),
                    "columns": [],
                    "members": 0,
                    "applied": False,
                    "guard": None,
                    "skipped": prerequisite_issue["code"],
                    "action_status": "not_executed",
                }
            )
            continue
        try:
            page_record = apply_page(
                page,
                label,
                translation_config,
                source,
                config,
                fixed_inventory=fixed_inventory,
                inventory_after=inventory_builder,
            )
        except Exception as error:  # noqa: BLE001 - the transaction must close
            failure = f"{type(error).__name__}: {error}"
            transaction_record = transaction.rollback()
            for previous in pages:
                if previous.get("applied"):
                    previous["applied"] = False
                    previous["guard"] = GUARD_NEW_FINDING
                    previous["action_status"] = "rolled_back"
            pages.append(
                {
                    "page": label,
                    "kind": getattr(page, "page_kind", None),
                    "columns": [],
                    "members": 0,
                    "applied": False,
                    "guard": GUARD_NEW_FINDING,
                    "action_status": "rolled_back",
                    "failure": failure,
                }
            )
            notes.append(
                "column reflow failed during mutation or detection; the complete "
                "touched set was restored"
            )
            break
        pages.append(page_record)
    if source is None and pages:
        notes.append(
            f"the source checkpoint is {source_result.status.value}, so there is "
            "no source gap to converge to and nothing was moved"
        )
    final_comparison = None
    if failure is None:
        try:
            final_comparison = fixed_assets.compare(
                fixed_inventory,
                inventory_builder(),
                config.asset_bbox_tolerance_pt,
            )
        except Exception as error:  # noqa: BLE001 - detection closes the transaction
            failure = f"{type(error).__name__}: {error}"
            transaction_record = transaction.rollback()
            for page_record in pages:
                if page_record["applied"]:
                    page_record["applied"] = False
                    page_record["guard"] = GUARD_FIXED_ASSET
                    page_record["action_status"] = "rolled_back"
                for column in page_record["columns"]:
                    if column["applied"]:
                        column["applied"] = False
                        column["guard"] = GUARD_FIXED_ASSET
            notes.append(
                "fixed asset detection failed; the complete document was restored"
            )
    if final_comparison is not None and not final_comparison.holds:
        transaction_record = transaction.rollback()
        for page_record in pages:
            if page_record["applied"]:
                page_record["applied"] = False
                page_record["guard"] = GUARD_FIXED_ASSET
                page_record["action_status"] = "rolled_back"
            for column in page_record["columns"]:
                if column["applied"]:
                    column["applied"] = False
                    column["guard"] = GUARD_FIXED_ASSET
        notes.append(
            "fixed asset conservation failed; the complete document was restored"
        )
    elif failure is None:
        touched = {
            row["reference"]
            for page_record in pages
            if page_record["applied"]
            for column in page_record["columns"]
            if column["applied"]
            for row in column["rows"]
            if row["shift"] > 0
        }
        if touched:
            transaction_record = transaction.commit(touched)
        elif any(
            item.get("action_status") == "rolled_back" for item in pages
        ):
            transaction_record = transaction.rollback()
        else:
            transaction_record = transaction.not_executed()
    record = as_record(
        config,
        pages,
        target_lang,
        notes,
        source_geometry=source_result,
        prerequisite_issues=(
            () if prerequisite_issue is None else (prerequisite_issue,)
        ),
    )
    record["fixed_asset_comparison"] = (
        None if final_comparison is None else final_comparison.to_record()
    )
    record["transaction"] = transaction_record
    if failure is not None:
        record["failure"] = failure
    write_report(working_dir, record)
    logger.debug(
        "column reflow: %d page(s), %d column(s) closed, %.1fpt recovered",
        record["totals"]["pages_considered"],
        record["totals"]["columns_applied"],
        record["totals"]["shift_total_pt"],
    )
    return record
