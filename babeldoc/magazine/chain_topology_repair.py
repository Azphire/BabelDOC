"""One closed adjudication round for a chain's reading-order inversion.

The model answers only the semantic continuity question.  Structural
authority stays here: a confirmation is admitted only when the members still
match the immutable preflight snapshot in every respect that makes the
existing joint translation and allocation safe.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from dataclasses import replace

KIND = "chain_topology_conflict"
SUBTYPE_READING_ORDER_INVERSION = "reading_order_inversion"

ACTION_CONFIRM = "confirm_joint_chain"
ACTION_NO_OP = "no_op"

STATUS_CONFIRMED = "confirmed"
STATUS_MODEL_NO_OP = "model_no_op"
STATUS_DECISION_UNAVAILABLE = "decision_unavailable"
STATUS_INVALID_DECISION_REPLY = "invalid_decision_reply"
STATUS_ADMISSION_REFUSED = "admission_refused"

CHAIN_BOUNDARY = "<CHAIN_BOUNDARY>"

BoxTuple = tuple[float, float, float, float]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TopologyConflict:
    """The sole topology defect eligible for semantic adjudication."""

    runtime_chain_id: str
    canonical_chain_id: str
    article_id: str
    ordered_runtime_source_refs: tuple[str, ...]
    ordered_physical_source_refs: tuple[str, ...]
    chain_indices: tuple[int, ...]
    reading_orders: tuple[int, ...]
    member_pages: tuple[int, ...]
    source_boxes: tuple[BoxTuple, ...]
    source_fragments: tuple[str, ...]
    merged_source: str
    detail: str
    builder_accepted: bool = True
    kind: str = KIND
    subtype: str = SUBTYPE_READING_ORDER_INVERSION

    @property
    def merged_source_sha256(self) -> str:
        return _sha256(self.merged_source)

    def with_sources(
        self, source_fragments: tuple[str, ...], merged_source: str
    ) -> TopologyConflict:
        return replace(
            self,
            source_fragments=source_fragments,
            merged_source=merged_source,
        )

    def to_record(self) -> dict:
        return {
            "kind": self.kind,
            "subtype": self.subtype,
            "runtime_chain_id": self.runtime_chain_id,
            "canonical_chain_id": self.canonical_chain_id,
            "article_id": self.article_id,
            "ordered_runtime_source_refs": list(self.ordered_runtime_source_refs),
            "ordered_physical_source_refs": list(self.ordered_physical_source_refs),
            "chain_indices": list(self.chain_indices),
            "reading_orders": list(self.reading_orders),
            "member_pages": list(self.member_pages),
            "source_boxes": [list(box) for box in self.source_boxes],
            "source_fragments": list(self.source_fragments),
            "fragment_boundary": CHAIN_BOUNDARY,
            "merged_source": self.merged_source,
            "merged_source_sha256": self.merged_source_sha256,
            "builder_accepted": self.builder_accepted,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class TopologyDecision:
    action: str
    reason: str
    status: str
    raw_reply_sha256: str | None
    call_count: int
    merged_source_sha256: str

    def to_record(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "status": self.status,
            "raw_reply_sha256": self.raw_reply_sha256,
            "call_count": self.call_count,
            "merged_source_sha256": self.merged_source_sha256,
        }


@dataclass(frozen=True, slots=True)
class TopologyAdmissionSnapshot:
    subtype: str
    ordered_runtime_source_refs: tuple[str, ...]
    ordered_physical_source_refs: tuple[str, ...]
    chain_indices: tuple[int | None, ...]
    member_object_ids: tuple[int, ...]
    member_pages: tuple[int, ...]
    article_ids: tuple[str | None, ...]
    canonical_chain_ids: tuple[str | None, ...]
    canonical_chain_owner_article_id: str | None
    source_boxes: tuple[BoxTuple | None, ...]
    source_fragments: tuple[str, ...]
    merged_source: str


@dataclass(frozen=True, slots=True)
class TopologyAdmission:
    accepted: bool
    reason: str
    status: str

    def to_record(self) -> dict:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class TopologyAdjudicationRecord:
    issue: TopologyConflict
    decision: TopologyDecision
    admission: TopologyAdmission
    repair_action_applied: bool
    final_chain_result_state: str | None = None
    joint_translator_call_count: int = 0

    def finalized(
        self, result_state: str, joint_translator_call_count: int
    ) -> TopologyAdjudicationRecord:
        return replace(
            self,
            final_chain_result_state=result_state,
            joint_translator_call_count=joint_translator_call_count,
        )

    def to_record(self) -> dict:
        return {
            "detected": True,
            "confirmed": self.decision.status == STATUS_CONFIRMED,
            "admitted": self.admission.accepted,
            "applied": self.repair_action_applied,
            "issue": self.issue.to_record(),
            "decision": self.decision.to_record(),
            "admission": self.admission.to_record(),
            "repair_action": {
                "action": (ACTION_CONFIRM if self.repair_action_applied else None),
                "applied": self.repair_action_applied,
            },
            "final_chain_result_state": self.final_chain_result_state,
            "joint_translator_call_count": self.joint_translator_call_count,
        }


def build_decision_prompt(issue: TopologyConflict) -> str:
    fragments = f"\n{CHAIN_BOUNDARY}\n".join(
        f"[{index}] {fragment}" for index, fragment in enumerate(issue.source_fragments)
    )
    return (
        "Decide one question only: does each later source fragment directly "
        "continue the preceding fragment in grammar and meaning, so the "
        "ordered fragments should be translated jointly as one continuous "
        "unit? Do not translate or rewrite any text. Do not evaluate layout "
        "or visual appearance. Return exactly one JSON object with only "
        '"action" and "reason". "action" must be "confirm_joint_chain" '
        'or "no_op".\n\nORDERED SOURCE FRAGMENTS (chain-index order):\n'
        f"{fragments}\n\nMERGED SOURCE:\n{issue.merged_source}"
    )


def parse_decision_reply(raw_reply: str, merged_source: str) -> TopologyDecision:
    raw_hash = _sha256(raw_reply)
    try:
        payload = json.loads(raw_reply.strip())
    except (AttributeError, TypeError, ValueError):
        return TopologyDecision(
            ACTION_NO_OP,
            "response_is_not_a_json_object",
            STATUS_INVALID_DECISION_REPLY,
            raw_hash,
            1,
            _sha256(merged_source),
        )
    if not isinstance(payload, dict) or set(payload) != {"action", "reason"}:
        return TopologyDecision(
            ACTION_NO_OP,
            "decision_fields_are_not_exactly_action_and_reason",
            STATUS_INVALID_DECISION_REPLY,
            raw_hash,
            1,
            _sha256(merged_source),
        )
    action = payload["action"]
    reason = payload["reason"]
    if not isinstance(action, str) or not isinstance(reason, str):
        return TopologyDecision(
            ACTION_NO_OP,
            "decision_fields_must_be_strings",
            STATUS_INVALID_DECISION_REPLY,
            raw_hash,
            1,
            _sha256(merged_source),
        )
    if action not in {ACTION_CONFIRM, ACTION_NO_OP}:
        return TopologyDecision(
            ACTION_NO_OP,
            "decision_action_is_outside_the_closed_vocabulary",
            STATUS_INVALID_DECISION_REPLY,
            raw_hash,
            1,
            _sha256(merged_source),
        )
    return TopologyDecision(
        action,
        reason.strip(),
        STATUS_CONFIRMED if action == ACTION_CONFIRM else STATUS_MODEL_NO_OP,
        raw_hash,
        1,
        _sha256(merged_source),
    )


def request_decision(issue: TopologyConflict, translator) -> TopologyDecision:
    """Make exactly one transport call; every failure closes to ``no_op``."""

    prompt = build_decision_prompt(issue)
    try:
        raw_reply = translator.translate_engine.llm_translate(
            prompt,
            rate_limit_params={
                "paragraph_token_count": translator.calc_token_count(prompt),
                "request_json_mode": True,
            },
        )
    except Exception as error:
        return TopologyDecision(
            ACTION_NO_OP,
            f"decision_transport_unavailable:{type(error).__name__}",
            STATUS_DECISION_UNAVAILABLE,
            None,
            1,
            issue.merged_source_sha256,
        )
    if not isinstance(raw_reply, str) or not raw_reply.strip():
        return TopologyDecision(
            ACTION_NO_OP,
            "decision_reply_is_empty",
            STATUS_INVALID_DECISION_REPLY,
            None if not isinstance(raw_reply, str) else _sha256(raw_reply),
            1,
            issue.merged_source_sha256,
        )
    return parse_decision_reply(raw_reply, issue.merged_source)


def decision_not_requested(issue: TopologyConflict, reason: str) -> TopologyDecision:
    return TopologyDecision(
        ACTION_NO_OP,
        reason,
        STATUS_ADMISSION_REFUSED,
        None,
        0,
        issue.merged_source_sha256,
    )


def _refused(reason: str) -> TopologyAdmission:
    return TopologyAdmission(False, reason, STATUS_ADMISSION_REFUSED)


def admit_decision(
    issue: TopologyConflict,
    decision: TopologyDecision,
    snapshot: TopologyAdmissionSnapshot,
) -> TopologyAdmission:
    """Recheck every structural fact after the semantic decision returns."""

    if decision.action != ACTION_CONFIRM or decision.status != STATUS_CONFIRMED:
        return _refused(decision.status)
    if not issue.builder_accepted:
        return _refused("builder_did_not_accept_chain")
    if (
        issue.subtype != SUBTYPE_READING_ORDER_INVERSION
        or snapshot.subtype != SUBTYPE_READING_ORDER_INVERSION
    ):
        return _refused("conflict_subtype_is_not_reading_order_inversion")
    if (
        snapshot.ordered_runtime_source_refs != issue.ordered_runtime_source_refs
        or snapshot.ordered_physical_source_refs != issue.ordered_physical_source_refs
    ):
        return _refused("member_refs_changed_after_preflight")
    expected_indices = tuple(range(len(issue.ordered_runtime_source_refs)))
    if snapshot.chain_indices != expected_indices:
        return _refused("chain_indices_are_not_contiguous_from_zero")
    if len(set(snapshot.member_object_ids)) != len(snapshot.member_object_ids) or len(
        set(snapshot.ordered_runtime_source_refs)
    ) != len(snapshot.ordered_runtime_source_refs):
        return _refused("members_are_not_unique")
    page_pairs = zip(snapshot.member_pages, snapshot.member_pages[1:], strict=False)
    if any(right < left or right - left > 1 for left, right in page_pairs):
        return _refused("member_pages_are_not_continuous")
    if not snapshot.article_ids or any(
        article_id != issue.article_id for article_id in snapshot.article_ids
    ):
        return _refused("canonical_article_owner_changed")
    if not snapshot.canonical_chain_ids or any(
        chain_id != issue.canonical_chain_id
        for chain_id in snapshot.canonical_chain_ids
    ):
        return _refused("canonical_chain_owner_changed")
    if snapshot.canonical_chain_owner_article_id != issue.article_id:
        return _refused("canonical_chain_owner_changed")
    if len(snapshot.source_boxes) != len(issue.source_boxes):
        return _refused("source_boxes_are_incomplete")
    for box in snapshot.source_boxes:
        if box is None or len(box) != 4 or not all(math.isfinite(v) for v in box):
            return _refused("source_boxes_are_incomplete")
    if snapshot.source_boxes != issue.source_boxes:
        return _refused("source_boxes_changed_after_preflight")
    if snapshot.source_fragments != issue.source_fragments:
        return _refused("source_fragments_changed_after_preflight")
    merged_hash = _sha256(snapshot.merged_source)
    if (
        merged_hash != issue.merged_source_sha256
        or merged_hash != decision.merged_source_sha256
    ):
        return _refused("merged_source_changed_after_decision")
    return TopologyAdmission(True, "all_structural_guards_passed", STATUS_CONFIRMED)


def refused_admission(reason: str) -> TopologyAdmission:
    return _refused(reason)
