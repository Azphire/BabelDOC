"""Canonical knowledge-state and decision protocol for bounded repair actions."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from babeldoc.magazine.element_roles import PROTECTED_ROLES
from babeldoc.magazine.element_roles import ElementRole

REPAIR_KNOWLEDGE_STATE_SCHEMA_VERSION = "repair-knowledge-state.v1"
REPAIR_DECISION_SCHEMA_VERSION = "repair-decision.v1"
ACTION_DETECTOR_CLOSURE_VERSION = "repair-detector-closure.v1"
METRIC_VECTOR_SCHEMA_VERSION = "1"


class RepairContractError(ValueError):
    """A repair state or decision failed its closed protocol."""


class StaleRepairStateError(RepairContractError):
    code = "STALE_REPAIR_STATE"


class RepairIssueKind(StrEnum):
    UNTRANSLATED_RESIDUE = "untranslated_residue"
    FRAGMENT_CLUSTER = "fragment_cluster"
    TEXT_FIGURE_OVERLAP = "text_figure_overlap"
    CHAIN_ESCALATION = "chain_escalation"
    OUT_OF_PAGE = "out_of_page"
    TEXT_TEXT_COLLISION = "text_text_collision"
    ARTICLE_OWNERSHIP = "article_ownership"
    CHAIN_CONSERVATION = "chain_conservation"
    RENDER_COVERAGE = "render_coverage"
    ABNORMAL_BLANK = "abnormal_blank"
    FIXED_ASSET_DRIFT = "fixed_asset_drift"
    INSTRUCTION_COMPLIANCE = "instruction_compliance"
    DETECTOR_PREREQUISITE_MISSING = "detector_prerequisite_missing"


class RepairAction(StrEnum):
    REPROCESS_OMITTED_TEXT = "reprocess_omitted_text"
    REALLOCATE_CONTINUITY_CHAIN = "reallocate_continuity_chain"
    RETYPESET_ARTICLE_REGION = "retypeset_article_region"
    CONTAIN_OVERFLOWING_HEADING = "contain_overflowing_heading"
    RESOLVE_TEXT_COLLISION = "resolve_text_collision"
    NO_ACTION = "no_action"


@dataclass(frozen=True, slots=True)
class RepairIssueEvidence:
    """Stable identity and bounded evidence for one detector finding."""

    issue_id: str
    kind: RepairIssueKind
    physical_page: int
    article_refs: tuple[str, ...]
    element_refs: tuple[str, ...]
    text_excerpt: str
    metric_vector: tuple[tuple[str, float], ...]
    metric_schema_version: str = METRIC_VECTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.issue_id, str) or not self.issue_id:
            raise RepairContractError("issue_id must be non-empty")
        object.__setattr__(self, "kind", _enum(RepairIssueKind, self.kind))
        if isinstance(self.physical_page, bool) or self.physical_page < 1:
            raise RepairContractError("physical_page must be positive")
        for name in ("article_refs", "element_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        if not isinstance(self.text_excerpt, str) or len(self.text_excerpt) > 160:
            raise RepairContractError("text_excerpt must be a bounded string")
        names = [name for name, _value in self.metric_vector]
        if not names or len(names) != len(set(names)):
            raise RepairContractError("metric_vector must name unique metrics")
        for name, value in self.metric_vector:
            if not isinstance(name, str) or not name:
                raise RepairContractError("metric name must be non-empty")
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise RepairContractError("metric values must be numeric")
            if not math.isfinite(float(value)):
                raise RepairContractError("metric values must be finite")
        if self.metric_schema_version != METRIC_VECTOR_SCHEMA_VERSION:
            raise RepairContractError("unsupported metric schema")

    def to_record(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "kind": self.kind.value,
            "physical_page": self.physical_page,
            "article_refs": list(self.article_refs),
            "element_refs": list(self.element_refs),
            "text_excerpt": self.text_excerpt,
            "metric_schema_version": self.metric_schema_version,
            "metric_vector": dict(self.metric_vector),
        }


@dataclass(frozen=True, slots=True)
class RepairTarget:
    """Typed references only; a decision cannot provide coordinates or text."""

    physical_pages: tuple[int, ...] = ()
    article_refs: tuple[str, ...] = ()
    element_refs: tuple[str, ...] = ()
    chain_refs: tuple[str, ...] = ()
    legal_slot_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        pages = tuple(self.physical_pages)
        if any(isinstance(page, bool) or page < 1 for page in pages):
            raise RepairContractError("target physical pages must be positive")
        if len(pages) != len(set(pages)):
            raise RepairContractError("target physical pages must be unique")
        object.__setattr__(self, "physical_pages", tuple(sorted(pages)))
        for name in (
            "article_refs",
            "element_refs",
            "chain_refs",
            "legal_slot_refs",
        ):
            object.__setattr__(self, name, _refs(getattr(self, name), name))

    def to_record(self) -> dict:
        return {
            "physical_pages": list(self.physical_pages),
            "article_refs": list(self.article_refs),
            "element_refs": list(self.element_refs),
            "chain_refs": list(self.chain_refs),
            "legal_slot_refs": list(self.legal_slot_refs),
        }


@dataclass(frozen=True, slots=True)
class RepairDecision:
    """One action selected against one exact RepairKnowledgeState digest."""

    action: RepairAction
    issue_ids: tuple[str, ...]
    target: RepairTarget
    parameters: tuple[tuple[str, int | float | str | bool], ...]
    state_sha256: str
    schema_version: str = REPAIR_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPAIR_DECISION_SCHEMA_VERSION:
            raise RepairContractError("unsupported repair decision schema")
        object.__setattr__(self, "action", _enum(RepairAction, self.action))
        issue_ids = _refs(self.issue_ids, "issue_ids")
        if self.action is RepairAction.NO_ACTION:
            if issue_ids or self.parameters or self.target != RepairTarget():
                raise RepairContractError("no_action cannot carry targets or parameters")
        elif not issue_ids:
            raise RepairContractError("a mutating action must target issue_ids")
        keys = [name for name, _value in self.parameters]
        if len(keys) != len(set(keys)) or keys != sorted(keys):
            raise RepairContractError("decision parameters must be unique and sorted")
        if not _sha256(self.state_sha256):
            raise RepairContractError("state_sha256 must be a lowercase SHA-256")
        object.__setattr__(self, "issue_ids", issue_ids)

    def to_record(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "action": self.action.value,
            "issue_ids": list(self.issue_ids),
            "target": self.target.to_record(),
            "parameters": dict(self.parameters),
            "state_sha256": self.state_sha256,
        }


@dataclass(frozen=True, slots=True)
class RepairKnowledgeState:
    """Immutable manager input assembled exclusively from canonical state."""

    document_semantic_sha256: str
    physical_page_selection_sha256: str
    article_knowledge_state_sha256: str
    run_trace_generation: int
    issues: tuple[RepairIssueEvidence, ...]
    page_policies: tuple[tuple[int, str], ...]
    article_regions: tuple[tuple[str, tuple[str, ...]], ...]
    element_roles: tuple[tuple[str, ElementRole], ...]
    chain_states: tuple[tuple[str, tuple[str, ...]], ...]
    legal_slot_digests: tuple[tuple[str, str], ...]
    fixed_asset_inventory_sha256: str
    manual_constraint_refs: tuple[str, ...]
    protected_refs: tuple[str, ...]
    allowed_actions: tuple[RepairAction, ...]
    action_detector_closure_version: str
    limits: tuple[tuple[str, int | float], ...]
    schema_version: str = REPAIR_KNOWLEDGE_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPAIR_KNOWLEDGE_STATE_SCHEMA_VERSION:
            raise RepairContractError("unsupported repair knowledge-state schema")
        for name in (
            "document_semantic_sha256",
            "physical_page_selection_sha256",
            "article_knowledge_state_sha256",
            "fixed_asset_inventory_sha256",
        ):
            if not _sha256(getattr(self, name)):
                raise RepairContractError(f"{name} must be a lowercase SHA-256")
        if self.run_trace_generation < 0:
            raise RepairContractError("run_trace_generation must be non-negative")
        issue_ids = [issue.issue_id for issue in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise RepairContractError("repair issue IDs must be unique")
        if tuple(sorted(issue_ids)) != tuple(issue_ids):
            raise RepairContractError("repair issues must be in stable ID order")
        if self.action_detector_closure_version != ACTION_DETECTOR_CLOSURE_VERSION:
            raise RepairContractError("repair detector closure version mismatch")
        roles = tuple(
            (reference, _enum(ElementRole, role))
            for reference, role in self.element_roles
        )
        if len({reference for reference, _role in roles}) != len(roles):
            raise RepairContractError("element_roles must have unique refs")
        object.__setattr__(self, "element_roles", tuple(sorted(roles)))
        for name in (
            "page_policies",
            "article_regions",
            "chain_states",
            "legal_slot_digests",
            "limits",
        ):
            values = tuple(getattr(self, name))
            keys = [key for key, _value in values]
            if len(keys) != len(set(keys)) or keys != sorted(keys):
                raise RepairContractError(f"{name} must have unique sorted keys")
        if any(
            isinstance(page, bool) or not isinstance(page, int) or page < 1
            for page, _digest in self.page_policies
        ):
            raise RepairContractError("page_policies must use physical pages")
        for name in ("page_policies", "legal_slot_digests"):
            if any(not _sha256(value) for _key, value in getattr(self, name)):
                raise RepairContractError(f"{name} must contain SHA-256 values")
        for name in ("article_regions", "chain_states"):
            for _key, refs in getattr(self, name):
                _refs(refs, name)
        for name, value in self.limits:
            if not isinstance(name, str) or not name:
                raise RepairContractError("limit names must be non-empty")
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
                or value < 0
            ):
                raise RepairContractError("limits must be finite non-negative numbers")
        actions = tuple(_enum(RepairAction, action) for action in self.allowed_actions)
        if len(actions) != len(set(actions)) or tuple(sorted(actions)) != actions:
            raise RepairContractError("allowed_actions must be unique and sorted")
        object.__setattr__(
            self,
            "allowed_actions",
            actions,
        )
        for name in ("manual_constraint_refs", "protected_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))

    def to_record(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "document_semantic_sha256": self.document_semantic_sha256,
            "physical_page_selection_sha256": self.physical_page_selection_sha256,
            "article_knowledge_state_sha256": self.article_knowledge_state_sha256,
            "run_trace_generation": self.run_trace_generation,
            "issues": [issue.to_record() for issue in self.issues],
            "page_policies": {str(page): digest for page, digest in self.page_policies},
            "article_regions": {
                article: list(refs) for article, refs in self.article_regions
            },
            "element_roles": {
                reference: role.value for reference, role in self.element_roles
            },
            "chain_states": {chain: list(refs) for chain, refs in self.chain_states},
            "legal_slot_digests": dict(self.legal_slot_digests),
            "fixed_asset_inventory_sha256": self.fixed_asset_inventory_sha256,
            "manual_constraint_refs": list(self.manual_constraint_refs),
            "protected_refs": list(self.protected_refs),
            "allowed_actions": [action.value for action in self.allowed_actions],
            "action_detector_closure_version": self.action_detector_closure_version,
            "limits": dict(self.limits),
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_record(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def preflight(self, decision: RepairDecision, detector_closure=None) -> None:
        if decision.state_sha256 != self.sha256():
            raise StaleRepairStateError(StaleRepairStateError.code)
        if decision.action not in self.allowed_actions:
            raise RepairContractError("decision action is not allowed by state")
        # C19 owns the domain parameter contract.  The provider wire schema is
        # generated from this same config, but cached/tampered typed decisions
        # still have to pass the deterministic executor boundary independently.
        from babeldoc.magazine.react.config import load_repair_config

        repair_config = load_repair_config()
        try:
            canonical_parameters = repair_config.decision_parameters(
                decision.action, dict(decision.parameters)
            )
        except ValueError as exc:
            raise RepairContractError(str(exc)) from exc
        if decision.parameters != canonical_parameters:
            raise RepairContractError("decision parameters are not canonical")
        known = {issue.issue_id for issue in self.issues}
        if any(issue_id not in known for issue_id in decision.issue_ids):
            raise RepairContractError("decision targets an unknown issue")
        by_issue_id = {issue.issue_id: issue for issue in self.issues}
        selected = tuple(by_issue_id[issue_id] for issue_id in decision.issue_ids)
        if decision.action is not RepairAction.NO_ACTION:
            selected_pages = {issue.physical_page for issue in selected}
            if not decision.target.physical_pages:
                raise RepairContractError("mutating action must target physical pages")
            if not selected_pages.issubset(decision.target.physical_pages):
                raise RepairContractError("decision physical pages omit selected issues")
            selected_articles = {
                article for issue in selected for article in issue.article_refs
            }
            if not selected_articles.issubset(decision.target.article_refs):
                raise RepairContractError("decision article refs omit selected issues")
            selected_elements = {
                element for issue in selected for element in issue.element_refs
            }
            if not set(decision.target.element_refs).issubset(selected_elements):
                raise RepairContractError("decision targets unrelated element refs")
        known_pages = {page for page, _digest in self.page_policies}
        if any(page not in known_pages for page in decision.target.physical_pages):
            raise RepairContractError("decision targets unsupported or unassigned page")
        if set(decision.target.element_refs) & set(self.protected_refs):
            raise RepairContractError("decision targets a protected ref")
        roles = dict(self.element_roles)
        known_elements = set(roles)
        if any(ref not in known_elements for ref in decision.target.element_refs):
            raise RepairContractError("decision targets an unknown element ref")
        if any(
            roles[ref] is ElementRole.UNCLASSIFIED
            for ref in decision.target.element_refs
        ):
            raise RepairContractError("decision targets an unknown element role")
        known_articles = {article for article, _refs_value in self.article_regions}
        if any(ref not in known_articles for ref in decision.target.article_refs):
            raise RepairContractError("decision targets an unknown article ref")
        known_chains = {chain for chain, _refs_value in self.chain_states}
        if any(ref not in known_chains for ref in decision.target.chain_refs):
            raise RepairContractError("decision targets an unknown chain ref")
        known_slots = {slot for slot, _digest in self.legal_slot_digests}
        if any(ref not in known_slots for ref in decision.target.legal_slot_refs):
            raise RepairContractError("decision targets an unknown legal slot ref")
        if detector_closure is not None:
            closure = detector_closure.action(decision.action)
            selected_kinds = {issue.kind.value for issue in selected}
            if not selected_kinds.issubset(closure.trigger_issue_kinds):
                raise RepairContractError("action does not answer for selected issue kind")


def build_repair_knowledge_state(
    docs,
    issues,
    *,
    article_document_ir,
    article_state,
    legal_slot_plan,
    fixed_asset_inventory,
    run_trace,
    allowed_actions,
    limits,
    protected_refs=(),
) -> RepairKnowledgeState:
    """Project the canonical C17/C18 runtime into the manager's only input."""
    from babeldoc.magazine.runtime_profile import semantic_projection

    if article_document_ir is None or article_state is None or legal_slot_plan is None:
        raise RepairContractError("canonical article state and legal slots are required")
    if fixed_asset_inventory is None or run_trace is None:
        raise RepairContractError("fixed assets and RunTrace are required")
    unsupported = {item.page for item in article_document_ir.unsupported_pages}
    if set(legal_slot_plan.unsupported_pages) != unsupported:
        raise RepairContractError("ArticleIR and legal-slot unsupported pages differ")
    article_state_pages = getattr(article_state, "page_selection_map_sha256", None)
    article_state_sha = getattr(article_state, "state_sha256", None)
    if not _sha256(article_state_pages) or not _sha256(article_state_sha):
        raise RepairContractError("latest ArticleKnowledgeState is unavailable")
    if int(article_state.run_trace_generation) != int(run_trace.current_generation):
        raise RepairContractError("ArticleKnowledgeState RunTrace generation is stale")

    page_policies = []
    article_regions = []
    element_roles = []
    for article in article_document_ir.articles:
        evidence_by_page = {item.page: item for item in article.policy_evidence}
        for page in article.pages:
            if page in unsupported or page not in evidence_by_page:
                raise RepairContractError("supported article page lacks page policy")
            page_policies.append(
                (page, digest_record(evidence_by_page[page].to_record()))
            )
        article_regions.append(
            (
                article.article_id,
                tuple(
                    slot.slot_id
                    for slot in legal_slot_plan.article_slots(article.article_id)
                ),
            )
        )
        element_roles.extend(
            (element.source_ref, element.role) for element in article.elements
        )
    chain_states = tuple(
        sorted(
            (chain.chain_id, tuple(chain.ordered_member_refs))
            for chain in article_document_ir.chains
        )
    )
    legal_slot_digests = tuple(
        sorted(
            (slot.slot_id, digest_record(slot.to_record()))
            for slot in legal_slot_plan.slots
        )
    )
    issue_evidence = []
    for issue in issues:
        vector = getattr(issue, "severity_vector", None)
        dimensions = () if vector is None else tuple(vector.dimensions)
        element_refs = tuple(
            sorted(
                set(issue.source_refs)
                | set(issue.paragraph_refs)
                | set(issue.fragment_refs)
            )
        )
        issue_evidence.append(
            RepairIssueEvidence(
                issue_id=issue.id,
                kind=RepairIssueKind(issue.kind),
                physical_page=int(issue.page),
                article_refs=tuple(sorted(issue.article_refs)),
                element_refs=element_refs,
                text_excerpt=str(issue.evidence.get("excerpt", ""))[:160],
                metric_vector=tuple(dimensions),
                metric_schema_version=getattr(
                    vector, "schema_version", METRIC_VECTOR_SCHEMA_VERSION
                ),
            )
        )
    fixed_digest = digest_record(fixed_asset_inventory.to_record())
    if fixed_digest != article_state.fixed_asset_inventory_sha256:
        raise RepairContractError("fixed-asset snapshot differs from article state")
    protected_role_refs = {
        reference
        for reference, role in element_roles
        if role in PROTECTED_ROLES and role is not ElementRole.HEADING
    }
    protected_assets = set(fixed_asset_inventory.protected_paragraph_refs)
    projection = semantic_projection("repair_state", docs, article_document_ir)
    return RepairKnowledgeState(
        document_semantic_sha256=digest_record(projection),
        physical_page_selection_sha256=article_state_pages,
        article_knowledge_state_sha256=article_state_sha,
        run_trace_generation=int(run_trace.current_generation),
        issues=tuple(sorted(issue_evidence, key=lambda item: item.issue_id)),
        page_policies=tuple(sorted(page_policies)),
        article_regions=tuple(sorted(article_regions)),
        element_roles=tuple(sorted(element_roles)),
        chain_states=chain_states,
        legal_slot_digests=legal_slot_digests,
        fixed_asset_inventory_sha256=fixed_digest,
        manual_constraint_refs=tuple(sorted(article_state.manual_constraint_refs)),
        protected_refs=tuple(
            sorted(set(protected_refs) | protected_role_refs | protected_assets)
        ),
        allowed_actions=tuple(sorted(RepairAction(action) for action in allowed_actions)),
        action_detector_closure_version=ACTION_DETECTOR_CLOSURE_VERSION,
        limits=tuple(sorted(limits)),
    )


def require_one_decision(decisions) -> RepairDecision:
    """Reject a batch: one iteration is exactly one typed decision."""
    held = tuple(decisions)
    if len(held) != 1 or not isinstance(held[0], RepairDecision):
        raise RepairContractError("one iteration requires exactly one RepairDecision")
    return held[0]


def _enum(enum_type, value):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise RepairContractError(f"unknown {enum_type.__name__}: {value!r}") from exc


def _refs(values, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise RepairContractError(f"{name} must be a tuple")
    if any(not isinstance(value, str) or not value for value in values):
        raise RepairContractError(f"{name} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise RepairContractError(f"{name} must contain unique refs")
    return tuple(values)


def _sha256(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def digest_record(value: Mapping | list | tuple | str) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
