"""One bounded deterministic repair action for the minimal pipeline."""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import acceptance
from babeldoc.magazine import chain_backfill
from babeldoc.magazine import fixed_assets
from babeldoc.magazine import minimal_detection
from babeldoc.magazine.detectors import detector_config
from babeldoc.magazine.detectors import residue
from babeldoc.magazine.reading_order import paragraph_characters
from babeldoc.magazine.reading_order import paragraph_reading_text
from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("repair_actions.json")
SCHEMA_VERSION = "mapek-demo.v1"

TRANSLATE_ORPHAN = "translate_orphan_text"
REALLOCATE_CHAIN = "reallocate_chain_cut"
RETYPESET_REGION = "retypeset_article_region"
CONTAIN_HEADING = "contain_heading"
REFIT_OWNED = "refit_or_reflow_owned_paragraph"
NO_OP = "no_op"
ACTIONS = (
    TRANSLATE_ORPHAN,
    REALLOCATE_CHAIN,
    RETYPESET_REGION,
    CONTAIN_HEADING,
    REFIT_OWNED,
    NO_OP,
)

# What a decision round may choose from for one kind. no_op is always available
# and is not listed; a kind mapped to nothing offers no_op alone, which is how
# a kind that may only be escalated is written.
ISSUE_ACTIONS = {
    "untranslated_residue": (TRANSLATE_ORPHAN,),
    "chain_conservation": (REALLOCATE_CHAIN,),
    "out_of_page": (CONTAIN_HEADING, REFIT_OWNED),
    "text_text_collision": (REFIT_OWNED,),
    "fragment_cluster": (RETYPESET_REGION,),
    "abnormal_blank": (RETYPESET_REGION,),
    # B16: an ornament overlap is one paragraph's first line standing on one
    # small fixed path, and the paragraph-scoped refit clears it in place.
    # B12 hung this kind on the region action and watched every nomination
    # die of region_target_has_no_canonical_owner; the region action keeps
    # fragment_cluster and abnormal_blank, whose defects really are regional.
    "text_figure_overlap": (REFIT_OWNED,),
    "instruction_compliance": (),
    "fixed_asset_drift": (),
}

# The one-shot pass predates the loop and chose an action from the kind alone.
# Frozen here so widening the vocabulary above does not change what it does.
DETERMINISTIC_ISSUE_ACTIONS = {
    "untranslated_residue": TRANSLATE_ORPHAN,
    "out_of_page": REFIT_OWNED,
    "text_text_collision": REFIT_OWNED,
    "fragment_cluster": NO_OP,
    "chain_conservation": NO_OP,
    "fixed_asset_drift": NO_OP,
    "abnormal_blank": NO_OP,
    "text_figure_overlap": NO_OP,
    "instruction_compliance": NO_OP,
}

_SOURCE_REF = re.compile(r"p([1-9][0-9]*)#(0|[1-9][0-9]*)\Z")
_RANGE = re.compile(
    r"(-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))\.\."
    r"(-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))\Z"
)
_ACTION_PRIORITY = {
    NO_OP: 0,
    TRANSLATE_ORPHAN: 1,
    REFIT_OWNED: 1,
    CONTAIN_HEADING: 1,
    RETYPESET_REGION: 1,
    REALLOCATE_CHAIN: 1,
}
_STYLE_CHARACTER_HOLDERS = (
    "pdf_same_style_characters",
    "pdf_line",
    "pdf_formula",
)
_DECIDE_KEYS = frozenset(
    {
        "decide_model",
        "decide_model_vocabulary",
        "decide_temperature",
        "decide_temperature_allowed_range",
        "decide_max_attempts",
        "decide_max_attempts_allowed_range",
        "decide_max_issues_per_round",
        "decide_max_issues_per_round_allowed_range",
        "decide_issue_excerpt_chars",
        "decide_issue_excerpt_chars_allowed_range",
        "decide_parameters",
        "max_iterations",
        "max_iterations_allowed_range",
        "max_actions_per_iteration",
        "max_actions_per_iteration_allowed_range",
        "max_affected_elements_per_run",
        "max_affected_elements_per_run_allowed_range",
    }
)
_ROOT_KEYS = frozenset(
    {
        "description",
        "schema_version",
        "max_actions_per_run",
        "max_actions_per_run_allowed_range",
        "actions",
        "issue_actions",
        "deterministic_issue_actions",
        TRANSLATE_ORPHAN,
        REALLOCATE_CHAIN,
        RETYPESET_REGION,
        CONTAIN_HEADING,
        REFIT_OWNED,
        "asset_bbox_tolerance_pt",
        "asset_bbox_tolerance_pt_allowed_range",
    }
    # Bounds belonging to the model decision that nominates an action rather
    # than to the actions themselves. They share one file so that the offered
    # vocabulary and the bounds on choosing from it cannot drift apart, and
    # this pass reads none of them; llm_decide.py owns their meaning.
    | _DECIDE_KEYS
)


class MinimalRepairError(ValueError):
    """Raised when bounded repair input or configuration is malformed."""


@dataclass(frozen=True, slots=True)
class RepairConfig:
    max_actions_per_run: int
    actions: tuple[str, ...]
    issue_actions: tuple[tuple[str, tuple[str, ...]], ...]
    deterministic_issue_actions: tuple[tuple[str, str], ...]
    orphan_layout_labels: tuple[str, ...]
    orphan_min_residue_ratio: float
    orphan_min_source_chars: int
    eligible_roles: tuple[str, ...]
    collision_max_area_ratio: float
    heading_eligible_roles: tuple[str, ...]
    heading_min_scale: float
    heading_max_lines: int
    region_eligible_roles: tuple[str, ...]
    region_min_scale: float
    region_max_members: int
    chain_max_members: int
    asset_bbox_tolerance_pt: float

    def action_for(self, kind: str) -> str:
        """The one-shot pass's single answer for a kind, which is frozen."""
        mapping = dict(self.deterministic_issue_actions)
        if kind not in mapping:
            raise MinimalRepairError(f"unsupported repair issue kind: {kind}")
        return mapping[kind]

    def permitted_actions(self, kind: str) -> tuple[str, ...]:
        """What a decision round may choose from for a kind, no_op included."""
        mapping = dict(self.issue_actions)
        if kind not in mapping:
            raise MinimalRepairError(f"unsupported repair issue kind: {kind}")
        return (*mapping[kind], NO_OP)


@dataclass(frozen=True, slots=True)
class RepairResult:
    selected_action: str | None
    accepted: bool
    rolled_back: bool
    final_detection: minimal_detection.DetectionResult
    record: dict


@dataclass(frozen=True, slots=True)
class _Target:
    physical_ref: str
    local_ref: str
    local_page: int
    paragraph_index: int
    page: object
    paragraph: object
    owner: str | None
    element: object | None


class _RepairRefusalError(Exception):
    def __init__(self, reason: str, *, translator_requests: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.translator_requests = translator_requests


class _RepairRejectedError(Exception):
    def __init__(self, candidate, comparison, fixed_comparison, reason: str):
        super().__init__(reason)
        self.candidate = candidate
        self.comparison = comparison
        self.fixed_comparison = fixed_comparison
        self.reason = reason


class _PageTransaction:
    """Restore one complete page unless the single action is committed."""

    def __init__(self, docs, local_page: int):
        self.docs = docs
        self.local_page = local_page
        self.snapshot = copy.deepcopy(docs.page[local_page - 1])
        self.before_digest = fixed_assets.content_digest(self.snapshot)
        self.committed = False
        self.restored = False

    def __enter__(self):
        return self

    def commit(self) -> None:
        if self.committed or self.restored:
            raise RuntimeError("repair transaction is already closed")
        self.committed = True

    def restore(self) -> None:
        if self.restored:
            return
        self.docs.page[self.local_page - 1] = copy.deepcopy(self.snapshot)
        self.restored = True

    @property
    def current_digest(self) -> str:
        return fixed_assets.content_digest(self.docs.page[self.local_page - 1])

    @property
    def restore_holds(self) -> bool:
        return self.restored and self.current_digest == self.before_digest

    def __exit__(self, exc_type, exc, traceback):
        if not self.committed:
            self.restore()
        return False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MinimalRepairError(message)


def _bounded_number(raw: dict, name: str, *, integer: bool = False):
    value = raw.get(name)
    allowed = raw.get(f"{name}_allowed_range")
    match = _RANGE.fullmatch(allowed) if isinstance(allowed, str) else None
    _require(match is not None, f"{name} requires a numeric allowed range")
    if integer:
        _require(
            isinstance(value, int) and not isinstance(value, bool),
            f"{name} must be an integer",
        )
    else:
        _require(
            isinstance(value, int | float) and not isinstance(value, bool),
            f"{name} must be numeric",
        )
    number = float(value)
    low, high = (float(item) for item in match.groups())
    _require(
        math.isfinite(number) and low <= number <= high,
        f"{name} is outside its allowed range",
    )
    return int(value) if integer else number


def _closed_strings(value, where: str) -> tuple[str, ...]:
    _require(
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item for item in value)
        and len(value) == len(set(value)),
        f"{where} must contain unique non-empty strings",
    )
    return tuple(value)


def parse_repair_config(raw: object, source: str) -> RepairConfig:
    _require(isinstance(raw, dict), f"{source}: root must be an object")
    unknown = set(raw).difference(_ROOT_KEYS)
    _require(not unknown, f"{source}: unknown keys {sorted(unknown)}")
    _require(raw.get("schema_version") == SCHEMA_VERSION, f"{source}: bad schema")
    max_actions = _bounded_number(raw, "max_actions_per_run", integer=True)
    _require(max_actions == 1, f"{source}: max_actions_per_run must be one")
    actions = _closed_strings(raw.get("actions"), f"{source}.actions")
    _require(actions == ACTIONS, f"{source}: action vocabulary must be {ACTIONS}")
    issue_actions = raw.get("issue_actions")
    _require(
        isinstance(issue_actions, dict), f"{source}: issue_actions must be an object"
    )
    _require(
        {kind: tuple(value) for kind, value in issue_actions.items()} == ISSUE_ACTIONS,
        f"{source}: issue action mapping changed",
    )
    deterministic = raw.get("deterministic_issue_actions")
    _require(
        isinstance(deterministic, dict),
        f"{source}: deterministic_issue_actions must be an object",
    )
    _require(
        deterministic == DETERMINISTIC_ISSUE_ACTIONS,
        f"{source}: the frozen one-shot issue action mapping changed",
    )

    orphan = raw.get(TRANSLATE_ORPHAN)
    _require(isinstance(orphan, dict), f"{source}: orphan action must be an object")
    orphan_keys = {
        "layout_labels",
        "min_residue_ratio",
        "min_residue_ratio_allowed_range",
        "min_source_chars",
        "min_source_chars_allowed_range",
    }
    _require(set(orphan) == orphan_keys, f"{source}: malformed orphan action")
    labels = _closed_strings(orphan["layout_labels"], "orphan layout labels")
    _require(labels == ("fallback_line",), "only fallback_line is repairable")
    min_ratio = _bounded_number(orphan, "min_residue_ratio")
    min_chars = _bounded_number(orphan, "min_source_chars", integer=True)

    refit = raw.get(REFIT_OWNED)
    _require(isinstance(refit, dict), f"{source}: refit action must be an object")
    refit_keys = {
        "eligible_roles",
        "collision_max_area_ratio",
        "collision_max_area_ratio_allowed_range",
    }
    _require(set(refit) == refit_keys, f"{source}: malformed refit action")
    roles = _closed_strings(refit["eligible_roles"], "eligible roles")
    ratio = _bounded_number(refit, "collision_max_area_ratio")
    heading = raw.get(CONTAIN_HEADING)
    _require(
        isinstance(heading, dict), f"{source}: heading action must be an object"
    )
    _require(
        set(heading)
        == {
            "eligible_roles",
            "heading_min_scale",
            "heading_min_scale_allowed_range",
            "heading_max_lines",
            "heading_max_lines_allowed_range",
        },
        f"{source}: malformed heading action",
    )
    heading_roles = _closed_strings(heading["eligible_roles"], "heading roles")
    heading_min_scale = _bounded_number(heading, "heading_min_scale")
    heading_max_lines = _bounded_number(heading, "heading_max_lines", integer=True)

    region = raw.get(RETYPESET_REGION)
    _require(isinstance(region, dict), f"{source}: region action must be an object")
    _require(
        set(region)
        == {
            "eligible_roles",
            "region_min_scale",
            "region_min_scale_allowed_range",
            "region_max_members",
            "region_max_members_allowed_range",
        },
        f"{source}: malformed region action",
    )
    region_roles = _closed_strings(region["eligible_roles"], "region roles")
    region_min_scale = _bounded_number(region, "region_min_scale")
    region_max_members = _bounded_number(region, "region_max_members", integer=True)

    chain = raw.get(REALLOCATE_CHAIN)
    _require(isinstance(chain, dict), f"{source}: chain action must be an object")
    _require(
        set(chain) == {"chain_max_members", "chain_max_members_allowed_range"},
        f"{source}: malformed chain action",
    )
    chain_max_members = _bounded_number(chain, "chain_max_members", integer=True)

    tolerance = _bounded_number(raw, "asset_bbox_tolerance_pt")
    return RepairConfig(
        max_actions_per_run=max_actions,
        actions=actions,
        issue_actions=tuple(
            (kind, tuple(value)) for kind, value in sorted(issue_actions.items())
        ),
        deterministic_issue_actions=tuple(sorted(deterministic.items())),
        orphan_layout_labels=labels,
        orphan_min_residue_ratio=min_ratio,
        orphan_min_source_chars=min_chars,
        eligible_roles=roles,
        collision_max_area_ratio=ratio,
        heading_eligible_roles=heading_roles,
        heading_min_scale=heading_min_scale,
        heading_max_lines=heading_max_lines,
        region_eligible_roles=region_roles,
        region_min_scale=region_min_scale,
        region_max_members=region_max_members,
        chain_max_members=chain_max_members,
        asset_bbox_tolerance_pt=tolerance,
    )


def load_repair_config(path: str | None = None) -> RepairConfig:
    selected = CONFIG_PATH if path is None else Path(path)
    return parse_repair_config(
        json.loads(selected.read_text(encoding="utf-8")),
        selected.name,
    )


def _parse_ref(reference: object) -> tuple[int, int]:
    match = _SOURCE_REF.fullmatch(reference) if isinstance(reference, str) else None
    if match is None:
        raise _RepairRefusalError("invalid_physical_ref")
    return int(match.group(1)), int(match.group(2))


def _elements(article_document_ir) -> dict[str, object]:
    elements = {
        element.source_ref: element
        for article in article_document_ir.articles
        for element in article.elements
    }
    if set(elements) != set(article_document_ir.by_element):
        raise MinimalRepairError("canonical ArticleIR indexes disagree")
    return elements


def _target(docs, baseline, article_document_ir, physical_ref: str) -> _Target:
    physical_page, index = _parse_ref(physical_ref)
    local_page = baseline.physical_to_local.get(physical_page)
    if local_page is None:
        raise _RepairRefusalError("physical_ref_outside_selected_pages")
    paragraphs = docs.page[local_page - 1].pdf_paragraph or ()
    if index >= len(paragraphs):
        raise _RepairRefusalError("physical_ref_missing_paragraph")
    local_ref = f"p{local_page}#{index}"
    owner = article_document_ir.by_element.get(local_ref)
    element = _elements(article_document_ir).get(local_ref)
    return _Target(
        physical_ref,
        local_ref,
        local_page,
        index,
        docs.page[local_page - 1],
        paragraphs[index],
        owner,
        element,
    )


def _select_issue(
    before,
    docs,
    baseline,
    article_document_ir,
    translation_config,
    flow_report,
    config: RepairConfig,
):
    """Choose the one finding this run will act on, from those it may act on.

    A run gets one action.  Ranking every finding and testing admissibility
    only afterwards spends that action on whichever candidate sorts first, and
    a candidate that sorts first but can never be acted on takes the run down
    with it while an actionable candidate waits behind it.  So admissibility is
    asked of every candidate first, on reads alone, and the ranking runs over
    what is left.  ``no_op`` findings are not asked: the action does not touch
    the document, so there is nothing for an admission to protect.

    The refused candidates are returned rather than dropped.  "Nothing was
    actionable" and "the detector reported nothing" are different states of the
    run and the report has to be able to tell them apart.
    """
    policy = acceptance.load_acceptance_policy()
    flow_refs = None
    candidates = []
    filtered: list[dict] = []
    for issue in before.issues:
        action = config.action_for(issue.kind)
        if issue.suggested_action_type != action:
            raise MinimalRepairError(
                f"issue {issue.id} recommendation disagrees with repair config"
            )
        if action != NO_OP:
            if flow_refs is None:
                flow_refs = _flow_refs(flow_report, article_document_ir)
            if action == TRANSLATE_ORPHAN:
                refused = admits_orphan(
                    issue,
                    docs,
                    baseline,
                    article_document_ir,
                    translation_config,
                    flow_refs,
                    config,
                )
            else:
                refused = admits_refit(
                    issue,
                    docs,
                    baseline,
                    article_document_ir,
                    flow_refs,
                    config,
                )
            if refused is not None:
                filtered.append(
                    {
                        "id": issue.id,
                        "kind": issue.kind,
                        "action": action,
                        "reason": refused,
                    }
                )
                continue
        candidates.append(
            (
                -policy.rank(issue.severity),
                _ACTION_PRIORITY[action],
                issue.sort_key(),
                issue,
                action,
            )
        )
    if not candidates:
        return None, None, tuple(filtered)
    _severity, _priority, _sort_key, issue, action = min(candidates)
    return issue, action, tuple(filtered)


def _box_tuple(box) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    values = tuple(float(getattr(box, name)) for name in ("x", "y", "x2", "y2"))
    if (
        not all(math.isfinite(item) for item in values)
        or values[0] >= values[2]
        or values[1] >= values[3]
    ):
        return None
    return values


def _area(target: _Target) -> float:
    box = _box_tuple(target.paragraph.box)
    if box is None:
        raise _RepairRefusalError("paragraph_box_invalid")
    return (box[2] - box[0]) * (box[3] - box[1])


def _has_formula(paragraph) -> bool:
    return any(
        getattr(composition, "pdf_formula", None) is not None
        for composition in paragraph.pdf_paragraph_composition or ()
    )


def _protected(target: _Target, article_document_ir, flow_refs) -> str | None:
    paragraph = target.paragraph
    if bool(getattr(paragraph, "vertical", False)):
        return "vertical_paragraph"
    if _has_formula(paragraph):
        return "formula_paragraph"
    if bool(getattr(paragraph, "drop_cap_candidate", False)):
        return "drop_cap_candidate"
    if (
        target.local_ref in article_document_ir.by_chain_member
        or getattr(paragraph, "chain_id", None)
    ):
        return "chain_member"
    if target.local_ref in flow_refs:
        return "article_flow_owned"
    return None


def _flow_refs(flow_report, article_document_ir) -> frozenset[str]:
    if flow_report is None:
        return frozenset()
    if not isinstance(flow_report, dict):
        raise MinimalRepairError("article flow report must be an object")
    segments = flow_report.get("cross_page_segments", ())
    if not isinstance(segments, list):
        raise MinimalRepairError("article flow segments must be a list")
    refs = set()
    for position, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise MinimalRepairError(f"article flow segment {position} is malformed")
        if segment.get("status") != "applied":
            continue
        if segment.get("action_status") != "committed":
            raise MinimalRepairError("applied article flow segment is not committed")
        rows = []
        rows.extend(segment.get("touched_sources", ()))
        rows.extend(segment.get("released_holders", ()))
        rows.extend(segment.get("committed_flow_owned_refs", ()))
        placements = segment.get("placements", ())
        if not isinstance(placements, list):
            raise MinimalRepairError("article flow placements must be a list")
        for placement in placements:
            if not isinstance(placement, dict):
                raise MinimalRepairError("article flow placement must be an object")
            rows.extend((placement.get("source_ref"), placement.get("render_ref")))
        for reference in rows:
            if reference is None:
                continue
            match = (
                _SOURCE_REF.fullmatch(reference)
                if isinstance(reference, str)
                else None
            )
            if match is None:
                raise MinimalRepairError(
                    f"invalid article flow paragraph ref: {reference!r}"
                )
            page, index = (int(item) for item in match.groups())
            local_ref = f"p{page}#{index}"
            if local_ref != reference:
                raise MinimalRepairError("article flow refs must be canonical local refs")
            refs.add(local_ref)
    committed = minimal_detection.committed_flow_refs(
        flow_report,
        article_document_ir,
    )
    if not committed.issubset(refs):
        raise MinimalRepairError("flow-owned ref evidence is incomplete")
    return frozenset(refs)


def _fonts(typesetter, page) -> dict:
    fonts = {font.font_id: font for font in page.pdf_font or () if font.font_id}
    page_fonts = dict(fonts)
    mapped = getattr(typesetter.font_mapper, "fontid2font", None)
    if not isinstance(mapped, dict):
        raise _RepairRefusalError("font_mapper_unavailable")
    fonts.update(mapped)
    for xobject in page.pdf_xobject or ():
        if xobject.xobj_id is None:
            continue
        fonts[xobject.xobj_id] = dict(page_fonts)
        for font in xobject.pdf_font or ():
            if font.font_id:
                fonts[xobject.xobj_id][font.font_id] = font
    return fonts


def _render_target(typesetter, target: _Target) -> None:
    from babeldoc.format.pdf.document_il.midend.typesetting import (
        BoundedTypesettingError,
    )

    try:
        typesetter.render_paragraph(
            target.paragraph,
            target.page,
            _fonts(typesetter, target.page),
        )
    except BoundedTypesettingError as error:
        # A repair that cannot be laid out is a repair to decline, not a reason
        # to abandon the document. Refusal is this stage's own way of saying
        # "leave this one alone"; it is recorded and the run continues.
        raise _RepairRefusalError("render_bounded_typesetting_failed") from error


def _paragraph_style(paragraph):
    """Resolve the source style without changing paragraph-level semantics."""
    if paragraph.pdf_style is not None:
        return paragraph.pdf_style
    for composition in paragraph.pdf_paragraph_composition or ():
        direct = getattr(composition, "pdf_character", None)
        if direct is not None and direct.pdf_style is not None:
            return direct.pdf_style
        for name in _STYLE_CHARACTER_HOLDERS:
            holder = getattr(composition, name, None)
            characters = () if holder is None else holder.pdf_character or ()
            if characters and characters[0].pdf_style is not None:
                return characters[0].pdf_style
    return None


def _style_is_renderable(style) -> bool:
    return bool(
        style is not None
        and style.font_id
        and isinstance(style.font_size, int | float)
        and not isinstance(style.font_size, bool)
        and math.isfinite(style.font_size)
        and style.font_size > 0
    )


def _visible_character_contract(
    paragraph,
    expected_text: str,
    *,
    source_style=None,
) -> bool:
    """Prove that rendering produced the expected visible character sequence."""
    if not paragraph.pdf_paragraph_composition:
        return False
    characters = paragraph_characters(paragraph)
    if not characters:
        return False
    if "".join(character.char_unicode or "" for character in characters) != expected_text:
        return False
    source_graphic_state = (
        None
        if source_style is None
        else fixed_assets.content_digest(source_style.graphic_state)
    )
    for character in characters:
        style = character.pdf_style
        if not _style_is_renderable(style):
            return False
        if (
            source_graphic_state is not None
            and fixed_assets.content_digest(style.graphic_state)
            != source_graphic_state
        ):
            return False
    return True


def _orphan_admission(
    issue,
    docs,
    baseline,
    article_document_ir,
    translation_config,
    flow_refs,
    config: RepairConfig,
) -> tuple[_Target | None, str | None]:
    """The target this finding would be translated on, or why it would not be.

    Every condition below is a read.  Nothing here writes to the document,
    resolves a translator or spends a request, which is what lets the selection
    ask the question of every candidate before it commits to one.  The action
    asks the same question first and refuses on the same string, so a caller
    reaching ``_translate_orphan`` directly still sees what it saw before.
    """
    try:
        if len(issue.paragraph_refs) != 1:
            return None, "orphan_requires_one_physical_ref"
        target = _target(
            docs,
            baseline,
            article_document_ir,
            issue.paragraph_refs[0],
        )
        if target.owner is not None or target.element is not None:
            return None, "orphan_is_canonical_article_text"
        paragraph = target.paragraph
        if paragraph.layout_label not in config.orphan_layout_labels:
            return None, "orphan_layout_label_not_allowed"
        blocked = _protected(target, article_document_ir, flow_refs)
        if blocked is not None:
            return None, blocked
        source = paragraph_reading_text(paragraph)
        if not isinstance(source, str) or not source.strip():
            return None, "orphan_source_text_unavailable"
        detector_rule = detector_config().residue_rule(
            getattr(translation_config, "lang_out", None)
        )
        if detector_rule is None:
            return None, "residue_direction_unavailable"
        script, detector_ratio = detector_rule
        residue_chars, _script_chars, ratio = residue.measure(source, script)
        min_chars = max(
            config.orphan_min_source_chars,
            detector_config().residue_min_chars(
                getattr(translation_config, "lang_out", None)
            ),
        )
        if (
            len(source.strip()) < config.orphan_min_source_chars
            or residue_chars < min_chars
            or ratio < max(config.orphan_min_residue_ratio, detector_ratio)
        ):
            return None, "orphan_residue_threshold_not_met"
        style = _paragraph_style(paragraph)
        if (
            not _style_is_renderable(style)
            or _box_tuple(paragraph.box) is None
        ):
            return None, "orphan_style_font_or_box_unavailable"
    except _RepairRefusalError as refusal:
        return None, refusal.reason
    return target, None


def admits_orphan(
    issue,
    docs,
    baseline,
    article_document_ir,
    translation_config,
    flow_refs,
    config: RepairConfig,
) -> str | None:
    """Why this finding is not one to translate, or ``None`` when it is."""
    return _orphan_admission(
        issue,
        docs,
        baseline,
        article_document_ir,
        translation_config,
        flow_refs,
        config,
    )[1]


def _translate_orphan(
    issue,
    docs,
    baseline,
    article_document_ir,
    typesetter,
    translation_config,
    flow_refs,
    config: RepairConfig,
) -> tuple[_Target, int]:
    target, refused = _orphan_admission(
        issue,
        docs,
        baseline,
        article_document_ir,
        translation_config,
        flow_refs,
        config,
    )
    if refused is not None:
        raise _RepairRefusalError(refused)
    paragraph = target.paragraph
    source = paragraph_reading_text(paragraph)
    style = _paragraph_style(paragraph)
    original_box = _box_tuple(paragraph.box)
    source_style_digest = fixed_assets.content_digest(style)
    translator = getattr(translation_config, "translator", None)
    if translator is None or not callable(getattr(translator, "translate", None)):
        raise _RepairRefusalError("translator_unavailable")
    translated = translator.translate(source)
    if not isinstance(translated, str):
        raise _RepairRefusalError("orphan_translation_not_text", translator_requests=1)
    if not translated.strip():
        raise _RepairRefusalError("orphan_translation_empty", translator_requests=1)
    if translated == source:
        raise _RepairRefusalError("orphan_translation_unchanged", translator_requests=1)
    paragraph.unicode = translated
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    unicode=translated,
                    pdf_style=copy.deepcopy(style),
                )
            )
        )
    ]
    _render_target(typesetter, target)
    if (
        paragraph.unicode != translated
        or _box_tuple(paragraph.box) != original_box
        or fixed_assets.content_digest(style) != source_style_digest
        or not _visible_character_contract(
            paragraph,
            translated,
            source_style=style,
        )
    ):
        raise _RepairRefusalError("orphan_render_contract_failed", translator_requests=1)
    return target, 1


def _finite_bbox(raw) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, list | tuple) or len(raw) != 4:
        return None
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    if values[0] >= values[2] or values[1] >= values[3]:
        return None
    return values


def _first_line_band(paragraph) -> tuple[float, float] | None:
    """The vertical ink span of the first line, read off the characters."""
    characters = paragraph_characters(paragraph)
    if not characters:
        return None
    first = characters[0].box
    if first is None or first.y is None or first.y2 is None:
        return None
    band_y, band_y2 = float(first.y), float(first.y2)
    if band_y2 <= band_y:
        return None
    for character in characters[1:]:
        box = character.box
        if box is None or box.y is None or box.y2 is None:
            continue
        shared = min(float(box.y2), band_y2) - max(float(box.y), band_y)
        height = min(float(box.y2) - float(box.y), band_y2 - band_y)
        if height <= 0 or shared < height * 0.5:
            break
        band_y = min(band_y, float(box.y))
        band_y2 = max(band_y2, float(box.y2))
    return band_y, band_y2


def _ink_ornament_area(paragraph, bbox: tuple[float, float, float, float]) -> float:
    """How much of the paragraph's ink stands on the ornament, in points."""
    area = 0.0
    for character in paragraph_characters(paragraph):
        box = character.box
        if box is None:
            continue
        width = min(float(box.x2), bbox[2]) - max(float(box.x), bbox[0])
        height = min(float(box.y2), bbox[3]) - max(float(box.y), bbox[1])
        if width > 0 and height > 0:
            area += width * height
    return area


def _ornament_clearance_admission(
    issue,
    target: _Target,
    baseline,
    config: RepairConfig,
) -> str | None:
    """Why this overlap is not one the head clearance can act on, or None.

    Three refusals, each its own fact. The finding must name an
    ornament-grade path -- an artwork overlap measured by union ratio is a
    different defect and the region this action does not own. The ornament
    must be in the frozen fixed-asset inventory at the position the evidence
    states, because the ornament is the anchor and the text is what moves.
    And the ornament must stand in the first line's own band: the only
    exclusion the typesetting stage supports is advancing the first line's
    pen (the B16 clearance channel), so an ornament under a later line is a
    shape this batch declines rather than half-repairs.
    """
    evidence = issue.evidence or {}
    if evidence.get("asset_class") != fixed_assets.ORNAMENT_ASSET_CLASS:
        return "overlap_not_ornament"
    bbox = _finite_bbox(evidence.get("ornament_bbox"))
    index = evidence.get("artwork_index")
    if bbox is None or not isinstance(index, int) or isinstance(index, bool):
        return "ornament_evidence_invalid"
    reference = f"p{target.local_page}:pdf_curve#{index}"
    record = baseline.fixed_inventory.by_ref.get(reference)
    if record is None or record.bbox is None:
        return "ornament_not_fixed_asset"
    tolerance = config.asset_bbox_tolerance_pt
    if any(
        abs(float(held) - float(stated)) > tolerance
        for held, stated in zip(record.bbox, bbox, strict=True)
    ):
        return "ornament_not_fixed_asset"
    band = _first_line_band(target.paragraph)
    if band is None or min(bbox[3], band[1]) - max(bbox[1], band[0]) <= 0:
        return "clearance_not_head_form"
    return None


def _refit_admission(
    issue,
    docs,
    baseline,
    article_document_ir,
    flow_refs,
    config: RepairConfig,
) -> tuple[_Target | None, str | None]:
    """The target this finding would be refitted on, or why it would not be.

    A collision names two paragraphs and only the smaller of them is refitted,
    so choosing which one is part of the same question as whether either may be
    touched at all.  The choice is made here, on reads alone, and handed to the
    action; the selection throws the target away and keeps the reason.
    """
    try:
        refs = tuple(issue.paragraph_refs)
        if issue.kind == "out_of_page":
            if len(refs) != 1:
                return None, "out_of_page_requires_one_ref"
            target = _target(docs, baseline, article_document_ir, refs[0])
        elif issue.kind == "text_figure_overlap":
            if len(refs) != 1:
                return None, "overlap_requires_one_ref"
            target = _target(docs, baseline, article_document_ir, refs[0])
            refused = _ornament_clearance_admission(issue, target, baseline, config)
            if refused is not None:
                return None, refused
        elif issue.kind == "text_text_collision":
            if len(refs) != 2 or refs[0] == refs[1]:
                return None, "collision_requires_two_unique_refs"
            targets = tuple(
                _target(docs, baseline, article_document_ir, reference)
                for reference in refs
            )
            if targets[0].local_page != targets[1].local_page:
                return None, "collision_crosses_page"
            owners = {item.owner for item in targets}
            if None in owners or len(owners) != 1:
                return None, "collision_crosses_article_owner"
            areas = tuple(_area(item) for item in targets)
            if areas[0] == areas[1]:
                return None, "collision_has_no_unique_smaller_member"
            smaller = 0 if areas[0] < areas[1] else 1
            larger = 1 - smaller
            if areas[smaller] / areas[larger] > config.collision_max_area_ratio:
                return None, "collision_members_are_comparable"
            target = targets[smaller]
        else:
            return None, "issue_is_not_refittable"
        if target.owner is None or target.element is None:
            return None, "refit_target_has_no_canonical_owner"
        if target.element.role not in config.eligible_roles:
            return None, "refit_role_not_allowed"
        blocked = _protected(target, article_document_ir, flow_refs)
        if blocked is not None:
            return None, blocked
        if target.local_ref in baseline.fixed_inventory.protected_paragraph_refs:
            return None, "refit_target_is_fixed_furniture"
        source_box = target.element.source_box
        if source_box is None or len(source_box) != 4:
            return None, "canonical_source_box_unavailable"
        source_box = tuple(float(value) for value in source_box)
        if (
            not all(math.isfinite(value) for value in source_box)
            or source_box[0] >= source_box[2]
            or source_box[1] >= source_box[3]
        ):
            return None, "canonical_source_box_invalid"
        target_text = paragraph_reading_text(target.paragraph)
        if not isinstance(target_text, str) or not target_text:
            return None, "refit_target_text_unavailable"
        style = _paragraph_style(target.paragraph)
        if not _style_is_renderable(style):
            return None, "refit_target_style_unavailable"
    except _RepairRefusalError as refusal:
        return None, refusal.reason
    return target, None


def admits_refit(
    issue,
    docs,
    baseline,
    article_document_ir,
    flow_refs,
    config: RepairConfig,
) -> str | None:
    """Why this finding is not one to refit, or ``None`` when it is."""
    return _refit_admission(
        issue,
        docs,
        baseline,
        article_document_ir,
        flow_refs,
        config,
    )[1]


def _refit_target(
    issue,
    docs,
    baseline,
    article_document_ir,
    typesetter,
    flow_refs,
    config: RepairConfig,
    *,
    translation_config=None,
    clearance_pt: float | None = None,
) -> _Target:
    target, refused = _refit_admission(
        issue,
        docs,
        baseline,
        article_document_ir,
        flow_refs,
        config,
    )
    if refused is not None:
        raise _RepairRefusalError(refused)
    source_box = tuple(float(value) for value in target.element.source_box)
    if issue.kind == "text_figure_overlap":
        return _refit_with_clearance(
            issue,
            target,
            source_box,
            typesetter,
            translation_config,
            clearance_pt,
        )
    target_text = paragraph_reading_text(target.paragraph)
    target_unicode = target.paragraph.unicode
    style = _paragraph_style(target.paragraph)
    source_style_digest = fixed_assets.content_digest(style)
    target.paragraph.box = il_version_1.Box(*source_box)
    _render_target(typesetter, target)
    if (
        target.paragraph.unicode != target_unicode
        or _box_tuple(target.paragraph.box) != source_box
        or fixed_assets.content_digest(style) != source_style_digest
        or not _visible_character_contract(target.paragraph, target_text)
    ):
        raise _RepairRefusalError("refit_render_contract_failed")
    return target


# What the decision schema declares for ``clearance_pt`` and the loop hands
# through; stated once here for the caller that has no parameters to give.
DEFAULT_CLEARANCE_PT = 2.0


def _refit_with_clearance(
    issue,
    target: _Target,
    source_box: tuple[float, float, float, float],
    typesetter,
    translation_config,
    clearance_pt: float | None,
) -> _Target:
    """Re-set the paragraph in its own box, first line advanced past the ornament.

    The ornament never moves -- it is a fixed asset and the admission proved
    it. What moves is the pen: a repair-owned clearance width (the B16
    channel the typesetting stage reads) advances the first line past the
    ornament's right edge plus the margin. Every failure restores the
    paragraph and the width store to what they were, so a refused repair
    leaves no fingerprints for the next round to trip on.
    """
    from babeldoc.magazine import indent_policy

    if translation_config is None:
        raise _RepairRefusalError("clearance_requires_translation_config")
    paragraph = target.paragraph
    debug_id = getattr(paragraph, "debug_id", None)
    if not debug_id:
        raise _RepairRefusalError("clearance_requires_debug_id")
    margin = DEFAULT_CLEARANCE_PT if clearance_pt is None else float(clearance_pt)
    bbox = _finite_bbox((issue.evidence or {}).get("ornament_bbox"))
    if bbox is None:
        raise _RepairRefusalError("ornament_evidence_invalid")
    width = bbox[2] - source_box[0] + margin
    if width <= 0 or width >= source_box[2] - source_box[0]:
        raise _RepairRefusalError("clearance_no_fit")

    store = getattr(translation_config, indent_policy.REPAIR_CLEARANCE_ATTR, None)
    if store is None:
        store = {}
        setattr(translation_config, indent_policy.REPAIR_CLEARANCE_ATTR, store)
    previous_width = store.get(debug_id)
    saved_box = paragraph.box
    saved_compositions = copy.deepcopy(paragraph.pdf_paragraph_composition)
    saved_scale = getattr(paragraph, "scale", None)
    saved_optimal = getattr(paragraph, "optimal_scale", None)
    target_text = paragraph_reading_text(paragraph)
    target_unicode = paragraph.unicode
    style = _paragraph_style(paragraph)
    source_style_digest = fixed_assets.content_digest(style)

    def _restore() -> None:
        paragraph.box = saved_box
        paragraph.pdf_paragraph_composition = saved_compositions
        paragraph.scale = saved_scale
        paragraph.optimal_scale = saved_optimal
        if previous_width is None:
            store.pop(debug_id, None)
        else:
            store[debug_id] = previous_width

    store[debug_id] = width
    try:
        paragraph.box = il_version_1.Box(*source_box)
        _render_target(typesetter, target)
    except _RepairRefusalError:
        _restore()
        raise
    if (
        paragraph.unicode != target_unicode
        or _box_tuple(paragraph.box) != source_box
        or fixed_assets.content_digest(style) != source_style_digest
        or not _visible_character_contract(paragraph, target_text)
    ):
        _restore()
        raise _RepairRefusalError("refit_render_contract_failed")
    if _ink_ornament_area(paragraph, bbox) > 1e-6:
        _restore()
        raise _RepairRefusalError("clearance_no_fit")
    return target


def _inventory(docs, article_document_ir, flow_refs, repair_owned_ref=None):
    movable = set(flow_refs)
    if repair_owned_ref is not None:
        movable.add(repair_owned_ref)
    return fixed_assets.build_inventory(
        docs,
        article_document_ir=article_document_ir,
        flow_owned_paragraph_refs=movable,
    )


def _target_only_page_change(transaction: _PageTransaction, target: _Target) -> bool:
    current = transaction.docs.page[transaction.local_page - 1]
    before_paragraphs = transaction.snapshot.pdf_paragraph or ()
    current_paragraphs = current.pdf_paragraph or ()
    if (
        len(before_paragraphs) != len(current_paragraphs)
        or target.paragraph_index >= len(current_paragraphs)
    ):
        return False
    expected = copy.deepcopy(transaction.snapshot)
    expected.pdf_paragraph[target.paragraph_index] = copy.deepcopy(
        current_paragraphs[target.paragraph_index]
    )
    return fixed_assets.content_digest(expected) == fixed_assets.content_digest(current)


def _result(
    *,
    action,
    issue,
    reason,
    action_count,
    applied_count,
    translator_requests,
    detection_passes_added,
    target,
    fixed_comparison,
    candidate,
    acceptance_candidate,
    final_detection,
    accepted,
    rolled_back,
    transaction,
    filtered_candidates,
) -> RepairResult:
    record = {
        "schema_version": SCHEMA_VERSION,
        "selected": action,
        "reason": reason,
        "filtered_candidates": [dict(row) for row in filtered_candidates],
        "offered_issue": (
            None if issue is None else {"id": issue.id, "kind": issue.kind}
        ),
        "action_count": action_count,
        "applied_count": applied_count,
        "translator_requests": translator_requests,
        "detection_passes_added": detection_passes_added,
        "target": (
            None
            if target is None
            else {
                "physical_ref": target.physical_ref,
                "local_ref": target.local_ref,
                "owner": target.owner,
            }
        ),
        "fixed_comparison": (
            None if fixed_comparison is None else fixed_comparison.to_record()
        ),
        "acceptance": {
            "candidate": (
                None
                if acceptance_candidate is None
                else acceptance_candidate.as_record()
            ),
            "final": {
                "accepted_candidate": accepted,
                "restored_from_before": rolled_back,
                "final_issue_ids": [issue.id for issue in final_detection.issues],
            },
        },
        "candidate_after": None if candidate is None else copy.deepcopy(candidate.record),
        "accepted": accepted,
        "rolled_back": rolled_back,
        "restored_digest": (
            None
            if transaction is None
            else {
                "before": transaction.before_digest,
                "current": transaction.current_digest,
                "restored": rolled_back,
                "holds": transaction.restore_holds if rolled_back else None,
            }
        ),
    }
    _require(action_count <= 1 and applied_count <= 1, "repair count overflow")
    return RepairResult(action, accepted, rolled_back, final_detection, record)


def repair_once(
    before: minimal_detection.DetectionResult,
    docs,
    article_document_ir,
    baseline: minimal_detection.DetectionBaseline,
    typesetter,
    translation_config,
    flow_report,
    detect_after: Callable[[str | None], minimal_detection.DetectionResult],
    *,
    config: RepairConfig | None = None,
) -> RepairResult:
    """Select, transact, and accept at most one locally provable action."""
    if not isinstance(before, minimal_detection.DetectionResult):
        raise MinimalRepairError("repair requires the before DetectionResult")
    if baseline.document_identity != id(docs):
        raise MinimalRepairError("repair baseline belongs to another document")
    if baseline.article_document_identity != id(article_document_ir):
        raise MinimalRepairError("repair baseline belongs to another ArticleIR")
    if not callable(detect_after):
        raise MinimalRepairError("detect_after must be callable")
    config = load_repair_config() if config is None else config
    issue, action, filtered = _select_issue(
        before,
        docs,
        baseline,
        article_document_ir,
        translation_config,
        flow_report,
        config,
    )
    working_dir = before.report_path.parent
    if issue is None:
        # "Every candidate was refused" is not "the detector found nothing".
        # The first says the action budget had nowhere to go and names where
        # it could not go; the second says there was nothing to spend it on.
        reason = "all_candidates_refused" if filtered else "no_issues"
        final = minimal_detection.mirror_after(
            before,
            working_dir,
            restored_from_before=False,
            reason=reason,
        )
        return _result(
            action=None,
            issue=None,
            reason=reason,
            action_count=0,
            applied_count=0,
            translator_requests=0,
            detection_passes_added=0,
            target=None,
            fixed_comparison=None,
            candidate=None,
            acceptance_candidate=None,
            final_detection=final,
            accepted=False,
            rolled_back=False,
            transaction=None,
            filtered_candidates=filtered,
        )
    if action == NO_OP:
        final = minimal_detection.mirror_after(
            before,
            working_dir,
            restored_from_before=False,
            reason="selected_no_op",
        )
        return _result(
            action=action,
            issue=issue,
            reason="selected_no_op",
            action_count=0,
            applied_count=0,
            translator_requests=0,
            detection_passes_added=0,
            target=None,
            fixed_comparison=None,
            candidate=None,
            acceptance_candidate=None,
            final_detection=final,
            accepted=False,
            rolled_back=False,
            transaction=None,
            filtered_candidates=filtered,
        )

    flow_refs = _flow_refs(flow_report, article_document_ir)
    target = None
    translator_requests = 0
    transaction = None
    fixed_comparison = None
    candidate = None
    comparison = None
    try:
        if action == TRANSLATE_ORPHAN:
            if len(issue.paragraph_refs) != 1:
                raise _RepairRefusalError("orphan_requires_one_physical_ref")
            initial_target = _target(
                docs,
                baseline,
                article_document_ir,
                issue.paragraph_refs[0],
            )
        else:
            refs = tuple(issue.paragraph_refs)
            if not refs:
                raise _RepairRefusalError("refit_requires_paragraph_refs")
            initial_target = _target(
                docs,
                baseline,
                article_document_ir,
                refs[0],
            )
        target = initial_target
        transaction = _PageTransaction(docs, initial_target.local_page)
        initial_repair_owned_ref = (
            initial_target.local_ref if action == TRANSLATE_ORPHAN else None
        )
        before_inventory = _inventory(
            docs,
            article_document_ir,
            flow_refs,
            initial_repair_owned_ref,
        )
        with transaction:
            if action == TRANSLATE_ORPHAN:
                target, translator_requests = _translate_orphan(
                    issue,
                    docs,
                    baseline,
                    article_document_ir,
                    typesetter,
                    translation_config,
                    flow_refs,
                    config,
                )
                repair_owned_ref = target.local_ref
            else:
                target = _refit_target(
                    issue,
                    docs,
                    baseline,
                    article_document_ir,
                    typesetter,
                    flow_refs,
                    config,
                )
                if target.local_page != initial_target.local_page:
                    raise _RepairRefusalError("collision_target_page_changed")
                repair_owned_ref = None
            after_inventory = _inventory(
                docs,
                article_document_ir,
                flow_refs,
                repair_owned_ref,
            )
            fixed_comparison = fixed_assets.compare(
                before_inventory,
                after_inventory,
                config.asset_bbox_tolerance_pt,
            )
            if not fixed_comparison.holds:
                raise _RepairRefusalError("fixed_asset_drift")
            if not _target_only_page_change(transaction, target):
                raise _RepairRefusalError("repair_touched_non_target_page_state")
            candidate = detect_after(repair_owned_ref)
            if not isinstance(candidate, minimal_detection.DetectionResult):
                raise MinimalRepairError("detect_after returned no DetectionResult")
            fixed_comparison = fixed_assets.compare(
                before_inventory,
                _inventory(
                    docs,
                    article_document_ir,
                    flow_refs,
                    repair_owned_ref,
                ),
                config.asset_bbox_tolerance_pt,
            )
            if (
                not fixed_comparison.holds
                or not _target_only_page_change(transaction, target)
            ):
                comparison = acceptance.compare_issues(
                    before.issues,
                    candidate.issues,
                    acceptance.load_acceptance_policy(),
                )
                raise _RepairRejectedError(
                    candidate,
                    comparison,
                    fixed_comparison,
                    "detect_after_mutated_document",
                )
            expected_binding = None
            if repair_owned_ref is not None:
                expected_binding = {
                    "physical_ref": target.physical_ref,
                    "local_ref": repair_owned_ref,
                    "symmetric_fixed_exclusion": True,
                }
            if candidate.record.get("repair_owned_paragraph") != expected_binding:
                raise MinimalRepairError("candidate repair-owned evidence disagrees")
            if candidate.record.get("fixed_comparison", {}).get("holds") is not True:
                comparison = acceptance.compare_issues(
                    before.issues,
                    candidate.issues,
                    acceptance.load_acceptance_policy(),
                )
                raise _RepairRejectedError(
                    candidate,
                    comparison,
                    fixed_comparison,
                    "candidate_fixed_asset_drift",
                )
            comparison = acceptance.compare_issues(
                before.issues,
                candidate.issues,
                acceptance.load_acceptance_policy(),
            )
            if not comparison.accepted:
                raise _RepairRejectedError(
                    candidate,
                    comparison,
                    fixed_comparison,
                    "strict_acceptance_rejected",
                )
            transaction.commit()
    except _RepairRefusalError as refusal:
        translator_requests = max(translator_requests, refusal.translator_requests)
        if transaction is not None and not transaction.restore_holds:
            raise RuntimeError(
                "typed repair refusal did not restore its page"
            ) from refusal
        final = minimal_detection.mirror_after(
            before,
            working_dir,
            restored_from_before=True,
            reason=refusal.reason,
        )
        return _result(
            action=action,
            issue=issue,
            reason=refusal.reason,
            action_count=1,
            applied_count=0,
            translator_requests=translator_requests,
            detection_passes_added=0,
            target=target,
            fixed_comparison=fixed_comparison,
            candidate=None,
            acceptance_candidate=None,
            final_detection=final,
            accepted=False,
            rolled_back=True,
            transaction=transaction,
            filtered_candidates=filtered,
        )
    except _RepairRejectedError as rejected:
        if transaction is None or not transaction.restore_holds:
            raise RuntimeError("rejected repair did not restore its page") from rejected
        final = minimal_detection.mirror_after(
            before,
            working_dir,
            restored_from_before=True,
            reason=rejected.reason,
        )
        return _result(
            action=action,
            issue=issue,
            reason=rejected.reason,
            action_count=1,
            applied_count=0,
            translator_requests=translator_requests,
            detection_passes_added=1,
            target=target,
            fixed_comparison=rejected.fixed_comparison,
            candidate=rejected.candidate,
            acceptance_candidate=rejected.comparison,
            final_detection=final,
            accepted=False,
            rolled_back=True,
            transaction=transaction,
            filtered_candidates=filtered,
        )
    return _result(
        action=action,
        issue=issue,
        reason="strict_improvement_accepted",
        action_count=1,
        applied_count=1,
        translator_requests=translator_requests,
        detection_passes_added=1,
        target=target,
        fixed_comparison=fixed_comparison,
        candidate=candidate,
        acceptance_candidate=comparison,
        final_detection=candidate,
        accepted=True,
        rolled_back=False,
        transaction=transaction,
        filtered_candidates=filtered,
    )


# --- contain a heading inside the box its source occupied ---------------------


def _bounded_units(typesetter, target: _Target):
    """The typesetting units of one paragraph, or the refusal to build them."""
    from babeldoc.format.pdf.document_il.midend.typesetting import (
        BoundedTypesettingError,
    )

    try:
        return typesetter.create_typesetting_units(
            target.paragraph, _fonts(typesetter, target.page)
        )
    except BoundedTypesettingError as error:
        raise _RepairRefusalError("bounded_units_unavailable") from error


def _source_box(target: _Target) -> tuple[float, float, float, float] | None:
    box = None if target.element is None else target.element.source_box
    if box is None or len(box) != 4:
        return None
    box = tuple(float(value) for value in box)
    if (
        not all(math.isfinite(value) for value in box)
        or box[0] >= box[2]
        or box[1] >= box[3]
    ):
        return None
    return box


def _geometry_admission(
    target: _Target,
    baseline,
    article_document_ir,
    flow_refs,
    roles: tuple[str, ...],
    prefix: str,
) -> str | None:
    """The questions every in-place relayout asks before it moves any ink."""
    if target.owner is None or target.element is None:
        return f"{prefix}_target_has_no_canonical_owner"
    if target.element.role not in roles:
        return f"{prefix}_role_not_allowed"
    blocked = _protected(target, article_document_ir, flow_refs)
    if blocked is not None:
        return blocked
    if target.local_ref in baseline.fixed_inventory.protected_paragraph_refs:
        return f"{prefix}_target_is_fixed_furniture"
    if _source_box(target) is None:
        return "canonical_source_box_invalid"
    if not paragraph_reading_text(target.paragraph):
        return f"{prefix}_target_text_unavailable"
    if not _style_is_renderable(_paragraph_style(target.paragraph)):
        return f"{prefix}_target_style_unavailable"
    return None


def _heading_admission(
    issue,
    docs,
    baseline,
    article_document_ir,
    flow_refs,
    config: RepairConfig,
) -> tuple[_Target | None, str | None]:
    """The heading this finding would be pulled back into, or why it would not."""
    try:
        if issue.kind != "out_of_page":
            return None, "issue_is_not_a_heading_overflow"
        refs = tuple(issue.paragraph_refs)
        if len(refs) != 1:
            return None, "out_of_page_requires_one_ref"
        target = _target(docs, baseline, article_document_ir, refs[0])
        refused = _geometry_admission(
            target,
            baseline,
            article_document_ir,
            flow_refs,
            config.heading_eligible_roles,
            "heading",
        )
        if refused is not None:
            return None, refused
    except _RepairRefusalError as refusal:
        return None, refusal.reason
    return target, None


def admits_heading(
    issue,
    docs,
    baseline,
    article_document_ir,
    flow_refs,
    config: RepairConfig,
) -> str | None:
    """Why this finding is not a heading to contain, or ``None`` when it is."""
    return _heading_admission(
        issue, docs, baseline, article_document_ir, flow_refs, config
    )[1]


def _contain_heading(
    issue,
    docs,
    baseline,
    article_document_ir,
    typesetter,
    flow_refs,
    config: RepairConfig,
    *,
    minimum_scale: float | None = None,
    maximum_lines: int | None = None,
) -> _Target:
    """Lay a heading out again inside the box its source occupied.

    The box does not move. A heading overflows its page because the translated
    title needs more room than the source title did, and the repair is to make
    the title fit the room rather than the room fit the title -- moving a
    heading's box is a layout decision this pass has no standing to take. A
    title that cannot be made to fit at the declared floor is refused and left
    overflowing, which is visible, rather than shrunk past legibility, which is
    not.
    """
    from babeldoc.format.pdf.document_il.midend.typesetting import (
        BoundedTypesettingError,
    )

    target, refused = _heading_admission(
        issue, docs, baseline, article_document_ir, flow_refs, config
    )
    if refused is not None:
        raise _RepairRefusalError(refused)
    source_box = _source_box(target)
    target_text = paragraph_reading_text(target.paragraph)
    target_unicode = target.paragraph.unicode
    style = _paragraph_style(target.paragraph)
    source_style_digest = fixed_assets.content_digest(style)
    units = _bounded_units(typesetter, target)
    try:
        typesetter.retypeset_bounded_text(
            target.paragraph,
            target.page,
            units,
            source_ref=target.physical_ref,
            source_box=source_box,
            minimum_scale=(
                config.heading_min_scale if minimum_scale is None else minimum_scale
            ),
            maximum_lines=(
                config.heading_max_lines if maximum_lines is None else maximum_lines
            ),
            use_english_line_break=True,
            preserve_wrapped_spaces=True,
        )
    except BoundedTypesettingError as error:
        raise _RepairRefusalError("heading_does_not_fit_source_box") from error
    if (
        target.paragraph.unicode != target_unicode
        or _box_tuple(target.paragraph.box) != source_box
        or fixed_assets.content_digest(style) != source_style_digest
        or not _visible_character_contract(target.paragraph, target_text)
    ):
        raise _RepairRefusalError("heading_render_contract_failed")
    return target


# --- lay one article region's own paragraphs out again ------------------------


def _region_members(
    issue,
    docs,
    baseline,
    article_document_ir,
    flow_refs,
    config: RepairConfig,
) -> tuple[tuple[_Target, ...], str | None]:
    """Every paragraph of the finding's article region this run may relayout.

    The region is the finding's article on the finding's page, which is the
    unit the canonical ArticleIR already names. Members outside it are not
    touched: an action reaching into a second article would be answering for a
    defect nobody measured there.
    """
    try:
        refs = tuple(issue.paragraph_refs)
        if not refs:
            return (), "region_finding_names_no_paragraph"
        anchor = _target(docs, baseline, article_document_ir, refs[0])
        if anchor.owner is None or anchor.element is None:
            return (), "region_target_has_no_canonical_owner"
        page = anchor.element.page
        owner = anchor.owner
        members: list[_Target] = []
        for index, _paragraph in enumerate(anchor.page.pdf_paragraph or ()):
            reference = fixed_assets.paragraph_reference(anchor.local_page, index)
            if article_document_ir.by_element.get(reference) != owner:
                continue
            candidate = _target(
                docs,
                baseline,
                article_document_ir,
                baseline.physical_ref(reference),
            )
            if candidate.element is None or candidate.element.page != page:
                continue
            if (
                _geometry_admission(
                    candidate,
                    baseline,
                    article_document_ir,
                    flow_refs,
                    config.region_eligible_roles,
                    "region",
                )
                is not None
            ):
                continue
            members.append(candidate)
        if not members:
            return (), "region_has_no_relayoutable_member"
        if len(members) > config.region_max_members:
            return (), "region_exceeds_member_ceiling"
    except _RepairRefusalError as refusal:
        return (), refusal.reason
    return tuple(members), None


def admits_region(
    issue,
    docs,
    baseline,
    article_document_ir,
    flow_refs,
    config: RepairConfig,
) -> str | None:
    """Why this finding's region may not be laid out again, or ``None``."""
    return _region_members(
        issue, docs, baseline, article_document_ir, flow_refs, config
    )[1]


def _retypeset_region(
    issue,
    docs,
    baseline,
    article_document_ir,
    typesetter,
    flow_refs,
    config: RepairConfig,
    *,
    minimum_scale: float | None = None,
) -> tuple[_Target, ...]:
    """Lay every owned member of one article region out again in its own box.

    No box moves and no member crosses into another region. Every member has to
    survive: a region half laid out is a worse page than the one the finding
    complained about, so the first refusal takes the whole action down and the
    caller's transaction puts the region back.
    """
    from babeldoc.format.pdf.document_il.midend.typesetting import (
        BoundedTypesettingError,
    )

    members, refused = _region_members(
        issue, docs, baseline, article_document_ir, flow_refs, config
    )
    if refused is not None:
        raise _RepairRefusalError(refused)
    scale = config.region_min_scale if minimum_scale is None else minimum_scale
    for target in members:
        source_box = _source_box(target)
        target_text = paragraph_reading_text(target.paragraph)
        target_unicode = target.paragraph.unicode
        style = _paragraph_style(target.paragraph)
        source_style_digest = fixed_assets.content_digest(style)
        units = _bounded_units(typesetter, target)
        try:
            typesetter.retypeset_bounded_text(
                target.paragraph,
                target.page,
                units,
                source_ref=target.physical_ref,
                source_box=source_box,
                minimum_scale=scale,
                maximum_lines=None,
                use_english_line_break=True,
                preserve_wrapped_spaces=True,
            )
        except BoundedTypesettingError as error:
            raise _RepairRefusalError("region_member_does_not_fit") from error
        if (
            target.paragraph.unicode != target_unicode
            or _box_tuple(target.paragraph.box) != source_box
            or fixed_assets.content_digest(style) != source_style_digest
            or not _visible_character_contract(target.paragraph, target_text)
        ):
            raise _RepairRefusalError("region_render_contract_failed")
    return members


# --- cut one chain's translation again, one cascade level down ----------------

# What the chain pass reports a slot-cascade level as, against the strategy name
# the cascade itself declares. The pass reports the level it settled on with a
# "slot_" prefix; the cascade in chain_translation.json names the strategies
# without one, so the two have to be read through each other to find out which
# level a chain is currently at and which one is below it.
_SLOT_PREFIX = "slot_"

# What a rebuilt merge member is made of. Never read: only its length is.
_MERGE_FILLER = " "


def _cascade_level(reported: object) -> str | None:
    """The cascade strategy a reported chain strategy stands for."""
    if not isinstance(reported, str) or not reported:
        return None
    return reported[len(_SLOT_PREFIX) :] if reported.startswith(_SLOT_PREFIX) else reported


def _next_strategy(reported: object, cascade: tuple[str, ...]) -> str | None:
    """The level below the one a chain was cut at, or None at the bottom."""
    current = _cascade_level(reported)
    if current is None or current not in cascade:
        return None
    position = cascade.index(current)
    if position + 1 >= len(cascade):
        return None
    return cascade[position + 1]


def _chain_row(issue, docs) -> tuple[dict | None, str | None]:
    """The chain report row this finding is about, or why there is none."""
    evidence = issue.evidence or {}
    chain_id = evidence.get("chain_id")
    report_path = evidence.get("report_path")
    if not isinstance(chain_id, str) or not chain_id:
        return None, "chain_finding_names_no_chain"
    if not isinstance(report_path, str) or not report_path:
        return None, "chain_report_path_unavailable"
    path = Path(report_path)
    if not path.is_file():
        return None, "chain_report_missing"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None, "chain_report_unreadable"
    rows = report.get("chains")
    if not isinstance(rows, list):
        return None, "chain_report_has_no_chains"
    for row in rows:
        if not isinstance(row, dict):
            continue
        if chain_id in (row.get("chain_id"), row.get("canonical_chain_id")):
            return row, None
    return None, "chain_not_in_report"


def _rebuilt_merge(row: dict) -> tuple[object | None, str | None]:
    """The chain's merge, rebuilt from what the report kept of it.

    Only two things are ever read back out of a merge by ``redistribute`` and
    ``verify_redistribution``: how many members there were, and each member's
    share of the merged source, which is a ratio of lengths. The source texts
    themselves are gone by the time a repair runs -- the paragraphs carry the
    translation now -- and the report keeps their lengths rather than their
    text. So the merge is rebuilt at the right lengths and its member texts are
    filler, and the assertion below is what keeps that sound: if a later version
    of the cut planner starts reading the text, the filler stops matching the
    recorded source size and the action refuses instead of cutting on nothing.
    """
    merge_record = row.get("merge")
    if not isinstance(merge_record, dict):
        return None, "chain_merge_record_missing"
    member_chars = merge_record.get("member_chars")
    separators = merge_record.get("separators")
    if (
        not isinstance(member_chars, list)
        or not member_chars
        or not all(isinstance(item, int) and item > 0 for item in member_chars)
    ):
        return None, "chain_member_lengths_unusable"
    if not isinstance(separators, list) or len(separators) != len(member_chars):
        return None, "chain_separators_unusable"
    members = tuple(_MERGE_FILLER * count for count in member_chars)
    text = "".join(
        f"{separator}{member}"
        for separator, member in zip(separators, members, strict=True)
    )
    spans: list[tuple[int, int]] = []
    cursor = 0
    for separator, member in zip(separators, members, strict=True):
        cursor += len(separator)
        spans.append((cursor, cursor + len(member)))
        cursor += len(member)
    if len(text) != merge_record.get("chars"):
        return None, "chain_merge_length_disagrees_with_report"
    return (
        chain_backfill.ChainMerge(
            text=text,
            members=members,
            separators=tuple(str(item) for item in separators),
            spans=tuple(spans),
            dropped_hyphens=tuple(merge_record.get("dropped_hyphens") or ()),
        ),
        None,
    )


def _chain_admission(
    issue,
    docs,
    baseline,
    article_document_ir,
    flow_refs,
    config: RepairConfig,
) -> tuple[tuple[dict, object, str, tuple[_Target, ...]] | None, str | None]:
    """The chain this finding would be cut again, or why it would not be."""
    try:
        if issue.kind != "chain_conservation":
            return None, "issue_is_not_a_chain_conservation_finding"
        row, refused = _chain_row(issue, docs)
        if refused is not None:
            return None, refused
        translated = row.get("translation")
        if not isinstance(translated, str) or not translated.strip():
            return None, "chain_translation_unavailable"
        backfill_config = chain_backfill.load_backfill_config()
        strategy = _next_strategy(row.get("strategy"), backfill_config.slot_cascade)
        if strategy is None:
            return None, "chain_realloc_no_further_strategy"
        merge, refused = _rebuilt_merge(row)
        if refused is not None:
            return None, refused
        members = row.get("members")
        if not isinstance(members, list) or len(members) != len(merge.members):
            return None, "chain_member_records_disagree_with_merge"
        if len(members) > config.chain_max_members:
            return None, "chain_exceeds_member_ceiling"
        targets: list[_Target] = []
        for member in members:
            local_ref = None if not isinstance(member, dict) else member.get(
                "runtime_source_ref"
            )
            if not isinstance(local_ref, str) or not local_ref:
                return None, "chain_member_has_no_runtime_ref"
            physical_ref = baseline.physical_ref(local_ref)
            if physical_ref is None:
                return None, "chain_member_outside_selected_pages"
            target = _target(docs, baseline, article_document_ir, physical_ref)
            if _source_box(target) is None:
                return None, "canonical_source_box_invalid"
            if target.local_ref in baseline.fixed_inventory.protected_paragraph_refs:
                return None, "chain_member_is_fixed_furniture"
            if not _style_is_renderable(_paragraph_style(target.paragraph)):
                return None, "chain_member_style_unavailable"
            targets.append(target)
    except _RepairRefusalError as refusal:
        return None, refusal.reason
    return (row, merge, strategy, tuple(targets)), None


def admits_chain_reallocation(
    issue,
    docs,
    baseline,
    article_document_ir,
    flow_refs,
    config: RepairConfig,
) -> str | None:
    """Why this chain may not be cut again, or ``None`` when it may."""
    return _chain_admission(
        issue, docs, baseline, article_document_ir, flow_refs, config
    )[1]


def _reallocate_chain_cut(
    issue,
    docs,
    baseline,
    article_document_ir,
    typesetter,
    flow_refs,
    config: RepairConfig,
    *,
    language: str | None = None,
) -> tuple[_Target, ...]:
    """Cut the chain's translation again one cascade level down, or refuse.

    The translation itself is not touched and not asked for again: the same
    characters are handed to the members in different proportions, which is why
    the conservation law below is checkable at all. Every member must then hold
    the piece it was given inside its own box; the first that cannot takes the
    whole reallocation down, because a chain with one member overflowing and the
    rest moved is worse than the chain the finding complained about.
    """
    from babeldoc.format.pdf.document_il.midend.typesetting import (
        BoundedTypesettingError,
    )

    admitted, refused = _chain_admission(
        issue, docs, baseline, article_document_ir, flow_refs, config
    )
    if refused is not None:
        raise _RepairRefusalError(refused)
    row, merge, strategy, targets = admitted
    translated = row["translation"]
    try:
        result = chain_backfill.redistribute(
            merge,
            translated,
            language,
            strategy,
        )
    except chain_backfill.ChainBackfillError as error:
        raise _RepairRefusalError("chain_redistribution_failed") from error
    conservation = chain_backfill.verify_redistribution(merge, translated, result)
    if not conservation.ok:
        raise _RepairRefusalError("chain_redistribution_not_conserved")
    if len(result.segments) != len(targets):
        raise _RepairRefusalError("chain_segment_count_disagrees_with_members")

    for target, segment in zip(targets, result.segments, strict=True):
        piece = segment.text
        if not piece:
            raise _RepairRefusalError("chain_member_received_no_text")
        source_box = _source_box(target)
        style = _paragraph_style(target.paragraph)
        source_style_digest = fixed_assets.content_digest(style)
        target.paragraph.unicode = piece
        target.paragraph.pdf_paragraph_composition = [
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        pdf_style=style,
                        unicode=piece,
                    )
                )
            )
        ]
        units = _bounded_units(typesetter, target)
        try:
            typesetter.retypeset_bounded_text(
                target.paragraph,
                target.page,
                units,
                source_ref=target.physical_ref,
                source_box=source_box,
                minimum_scale=config.region_min_scale,
                maximum_lines=None,
                use_english_line_break=True,
                preserve_wrapped_spaces=True,
            )
        except BoundedTypesettingError as error:
            raise _RepairRefusalError("chain_realloc_member_overflow") from error
        if (
            target.paragraph.unicode != piece
            or _box_tuple(target.paragraph.box) != source_box
            or fixed_assets.content_digest(style) != source_style_digest
            or not _visible_character_contract(target.paragraph, piece)
        ):
            raise _RepairRefusalError("chain_realloc_render_contract_failed")
    return targets
