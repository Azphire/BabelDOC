"""Forced structured selection for one bounded repair action.

The production path makes one logical ``select_repair_action`` tool request
through the run's translator.  Provider arguments are decoded against the
versioned wire schema and converted to C19's canonical :class:`RepairDecision`;
the exact C19 knowledge state then preflights that decision before the caller
can resolve or invoke a handler.  There is deliberately no text-response JSON
path here.

Generic fence stripping remains for the separate orphan-translation reader;
there is no historical decision reader on the executable controller surface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from babeldoc.magazine.prompt_loader import Prompt
from babeldoc.magazine.prompt_loader import load_prompt
from babeldoc.magazine.react import cache_key as cache_key_fields
from babeldoc.magazine.react.cache_key import GROUP_DECISION
from babeldoc.magazine.react.cache_key import SERVED_BYPASSED
from babeldoc.magazine.react.cache_key import SERVED_MISS
from babeldoc.magazine.react.cache_key import SERVED_RETRY
from babeldoc.magazine.react.cache_key import attribution
from babeldoc.magazine.react.config import NO_ACTION
from babeldoc.magazine.react.config import RepairConfig
from babeldoc.magazine.repair_contract import RepairAction
from babeldoc.magazine.repair_contract import RepairContractError
from babeldoc.magazine.repair_contract import RepairDecision
from babeldoc.magazine.repair_contract import RepairKnowledgeState
from babeldoc.magazine.repair_contract import RepairTarget
from babeldoc.translator.repair_tool_schema import RepairToolContext
from babeldoc.translator.repair_tool_schema import decode_repair_tool_arguments
from babeldoc.translator.repair_tool_schema import load_repair_tool_config
from babeldoc.translator.repair_tool_schema import repair_tool_parameters_schema
from babeldoc.translator.tool_call import ToolCallError
from babeldoc.translator.tool_call import ToolCallLimits
from babeldoc.translator.tool_call import ToolCallSchemaError
from babeldoc.translator.tool_call import ToolCallsUnsupported

logger = logging.getLogger(__name__)

DECIDE_PROMPT = "react_repair_decide"

# The composition a key is built by, shared with the orphan action's cache so
# the two cannot drift apart. Named here as well because the engine parameters
# the stored replies are filed under carry it, and those have to move when the
# composition does.
CACHE_KEY_VERSION = cache_key_fields.CACHE_KEY_VERSION

ACTION_NOT_EXECUTED = "not_executed"
STRUCTURED_TOOL_CALLS_UNSUPPORTED = "STRUCTURED_TOOL_CALLS_UNSUPPORTED"
STRUCTURED_TOOL_CACHE_HIT = "structured_tool_cache_hit"


@dataclass
class RequestLog:
    """Digest-only accounting for one logical structured selection."""

    prompt_digest: str = ""
    key: str = ""
    calls: list[dict] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    logical_calls: int = 0
    provider_attempts: int = 0
    cache_hits: int = 0


class EngineTransport:
    """The run's translator, exposing only its forced-tool interface."""

    def __init__(self, engine):
        self.engine = engine

    def counters(self) -> tuple[int, int]:
        return (
            int(getattr(self.engine, "tool_call_attempt_count", 0)),
            int(getattr(self.engine, "tool_call_cache_hit_count", 0)),
        )

    def select(
        self,
        *,
        messages,
        state_sha256: str,
        cache_context: dict[str, object],
        request_limits: dict[str, int | float],
    ):
        if not self.engine.supports_tool_calls():
            raise ToolCallsUnsupported("strict structured tool calls unavailable")
        tool = load_repair_tool_config()
        return self.engine.llm_tool_call(
            messages=messages,
            tool_name=tool.tool_name,
            parameters_schema=repair_tool_parameters_schema(tool),
            state_sha256=state_sha256,
            cache_context=cache_context,
            request_limits=request_limits,
        )


def engine_identity(engine, lang_out: str) -> str:
    """What about the engine could change a decision, as a cache key fragment."""
    return f"{type(engine).__name__}/{getattr(engine, 'name', '')}/{lang_out}"


def cache_key(
    prompt: Prompt,
    identity: str,
    version: int | None = None,
    *,
    state_sha256: str | None = None,
) -> str:
    """Digest of everything that could change the answer to one request.

    Given the key rendering of a request rather than the sent one, so two runs
    whose findings differ only in the ids the paragraph finder minted afresh
    reach one key and the second is served what the first paid for.

    ``version`` is for replaying a key an earlier batch filed under an earlier
    composition; a run leaves it alone.
    """
    bound_identity = (
        identity
        if state_sha256 is None
        else f"{identity}/repair-state-sha256:{state_sha256}"
    )
    return cache_key_fields.digest(
        bound_identity, prompt.digest, prompt.text, version
    )


def strip_fence(reply: str) -> str:
    """Strip a code fence a chat model wrapped its object in."""
    text = (reply or "").strip()
    for opener in ("```json", "```"):
        if text.startswith(opener):
            text = text[len(opener) :]
            break
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def issues_block(issues, excerpt_chars: int, limit: int, drop=()) -> str:
    """The findings as the request states them, one block each.

    ``drop`` names evidence fields to leave out. It is empty for the rendering
    that is sent and holds the volatile fields for the rendering the cache key
    is taken over, so what the model reads and what the key is computed from
    differ in exactly those fields and in nothing else.
    """
    lines: list[str] = []
    for issue in issues[:limit]:
        evidence = cache_key_fields.project(issue.evidence, drop)
        excerpt = str(evidence.pop("excerpt", "") or "")[:excerpt_chars]
        detail = ", ".join(
            f"{key}={value!r}" for key, value in sorted(evidence.items())
        )
        lines.append(
            f'- id: "{issue.id}"\n'
            f"  kind: {issue.kind}\n"
            f"  severity: {issue.severity}\n"
            f"  page: {issue.page}\n"
            f"  article refs: {', '.join(getattr(issue, 'article_refs', ()))}\n"
            f"  target element refs: {', '.join(issue.paragraph_refs)}\n"
            f"  evidence: {detail}\n"
            f"  text as the page renders it: {excerpt}"
        )
    if len(issues) > limit:
        lines.append(
            f"- and {len(issues) - limit} further finding(s), not shown; the "
            f"loop will see them again next iteration"
        )
    return "\n".join(lines) if lines else "- none"


def actions_block(config: RepairConfig, _language: str | None = None) -> str:
    """The vocabulary as the request states it, one block per action."""
    tool = load_repair_tool_config()
    lines: list[str] = []
    for name, action in sorted(config.actions.items()):
        descriptions = []
        for slot_name in tool.actions[name]:
            slot = tool.parameter_slots[slot_name]
            if "enum" in slot:
                bound = f"one of {', '.join(map(str, slot['enum']))}"
            else:
                bound = f"integer in {slot['minimum']}..{slot['maximum']}"
            descriptions.append(f"{slot_name} ({bound})")
        parameters = "; ".join(descriptions) or "none"
        lines.append(
            f'- name: "{name}"\n'
            f"  what it does: {action.description}\n"
            f"  answers for findings of kind: {', '.join(action.issue_kinds)}\n"
            f"  parameters: {parameters}"
        )
    lines.append(
        f'- name: "{NO_ACTION}"\n'
        f"  what it does: apply nothing in this iteration.\n"
        f"  answers for findings of kind: any\n"
        f"  parameters: none"
    )
    return "\n".join(lines)


def constraints_block(config: RepairConfig, language: str | None = None) -> str:
    """The applicability rule as the request states it, one block per action.

    The rule is what decides whether a named finding is acted on, and it is
    deterministic and is not the model's to overrule. Stating it is not a
    weakening of that: a decision step that cannot see the filter it feeds
    spends its list on findings the filter throws away, which costs the
    iteration the findings it did not name instead.
    """
    lines: list[str] = []
    for name, action in sorted(config.actions.items()):
        conditions = action.conditions(language)
        if not conditions:
            continue
        stated = "\n".join(f"    - {sentence}" for sentence in conditions)
        lines.append(
            f'- "{name}" acts on a finding only when all of these hold:\n{stated}'
        )
    return "\n".join(lines) if lines else "- none"


def _tool_context(
    issues, repair_state: RepairKnowledgeState, config: RepairConfig
) -> RepairToolContext:
    """Project only offered, canonically-owned refs into the wire decoder."""
    roles = dict(repair_state.element_roles)
    contract_issues = {item.issue_id: item for item in repair_state.issues}
    issue_actions: dict[str, tuple[str, ...]] = {}
    element_owners: dict[str, tuple[int, str]] = {}
    supported_pages = {page for page, _digest in repair_state.page_policies}
    unsupported_pages: set[int] = set()
    for issue in issues[: config.max_issues_offered]:
        issue_actions[issue.id] = tuple(
            sorted(
                name
                for name, action in config.actions.items()
                if action.answers_for(issue.kind)
            )
        )
        contract = contract_issues.get(issue.id)
        articles = (
            tuple(contract.article_refs)
            if contract is not None
            else tuple(getattr(issue, "article_refs", ()))
        )
        if issue.page not in supported_pages:
            unsupported_pages.add(issue.page)
        if len(articles) != 1:
            continue
        owner = (int(issue.page), articles[0])
        for reference in issue.paragraph_refs:
            if reference not in roles:
                continue
            previous = element_owners.get(reference)
            if previous is None:
                element_owners[reference] = owner
            elif previous != owner:
                element_owners.pop(reference, None)
    return RepairToolContext(
        state_sha256=repair_state.sha256(),
        issue_actions=issue_actions,
        element_owners=element_owners,
        unsupported_pages=tuple(sorted(unsupported_pages)),
    )


def _canonical_decision(
    domain: dict[str, object],
    issues,
    repair_state: RepairKnowledgeState,
    config: RepairConfig,
) -> RepairDecision:
    """Bind decoded wire targets to the exact offered C19 issue objects."""
    action = RepairAction(domain["action"])
    parameters = config.decision_parameters(action, dict(domain["parameters"]))
    if action is RepairAction.NO_ACTION:
        return RepairDecision(
            action=action,
            issue_ids=(),
            target=RepairTarget(),
            parameters=parameters,
            state_sha256=repair_state.sha256(),
        )

    offered = {
        issue.id: issue for issue in issues[: config.max_issues_offered]
    }
    selected = [offered[issue_id] for issue_id in domain["issue_ids"]]
    contract = {item.issue_id: item for item in repair_state.issues}
    expected_pages = {int(issue.page) for issue in selected}
    expected_articles = {
        article
        for issue in selected
        for article in contract[issue.id].article_refs
    }
    expected_elements = {
        reference for issue in selected for reference in issue.paragraph_refs
    }
    wire_target = domain["target"]
    if expected_pages != {wire_target["physical_page_number"]}:
        raise ToolCallSchemaError("tool target must name the selected physical page")
    if expected_articles != {wire_target["article_id"]}:
        raise ToolCallSchemaError("tool target must name one selected article owner")
    if expected_elements != set(wire_target["element_refs"]):
        raise ToolCallSchemaError("tool target must name every selected element ref")
    return RepairDecision(
        action=action,
        issue_ids=tuple(domain["issue_ids"]),
        target=RepairTarget(
            physical_pages=(wire_target["physical_page_number"],),
            article_refs=(wire_target["article_id"],),
            element_refs=tuple(sorted(wire_target["element_refs"])),
        ),
        parameters=parameters,
        state_sha256=repair_state.sha256(),
    )


class CachedDecisionClient:
    """One logical forced call, transport cache, strict decode and preflight."""

    def __init__(
        self,
        config: RepairConfig,
        transport=None,
        identity: str = "",
        working_dir: Path | str | None = None,
        ignore_cache: bool = False,
        language: str | None = None,
        request_limits: dict[str, object] | None = None,
    ) -> None:
        self.config = config
        # The run's target language, because an applicability term declared for
        # one language governs this decision and the sentence the model reads
        # has to carry the value that governs.
        self.language = language
        self.transport = transport
        self.identity = identity
        self.working_dir = working_dir
        self.ignore_cache = ignore_cache
        self.request_limits = ToolCallLimits.from_mapping(request_limits).as_record()

    def _render(self, issues, drop, working_dir) -> Prompt:
        return load_prompt(
            DECIDE_PROMPT,
            {
                "issues_block": issues_block(
                    issues,
                    self.config.issue_excerpt_chars,
                    self.config.max_issues_offered,
                    drop=drop,
                ),
                "actions_block": actions_block(self.config, self.language),
                "action_constraints": constraints_block(self.config, self.language),
            },
            working_dir=working_dir,
        )

    def prompt(self, issues) -> Prompt:
        """The request as it is sent: every field the finding carries."""
        return self._render(issues, (), self.working_dir)

    def key_prompt(self, issues) -> Prompt:
        """The same request without the fields that change on every run.

        Never sent, so it is not recorded in the run's prompt manifest: what
        that manifest answers for is what the model was asked, and this was
        asked of nobody.
        """
        return self._render(issues, self.config.volatile_evidence_keys, None)

    def decide(
        self, issues, *, repair_state: RepairKnowledgeState
    ) -> tuple[RepairDecision | None, RequestLog]:
        """Return one preflighted C19 decision, or a typed fail-closed refusal."""
        prompt = self.prompt(issues)
        state_sha256 = repair_state.sha256()
        key = cache_key(
            self.key_prompt(issues),
            self.identity,
            state_sha256=state_sha256,
        )
        log = RequestLog(prompt_digest=prompt.digest, key=key, logical_calls=1)
        before_attempts, before_hits = self.transport.counters()
        tool = load_repair_tool_config()
        try:
            result = self.transport.select(
                messages=[
                    {"role": "system", "content": prompt.text},
                    {
                        "role": "user",
                        "content": f"repair_state_sha256={state_sha256}",
                    },
                ],
                state_sha256=state_sha256,
                cache_context={
                    "decision_schema_version": tool.repair_config.decision_schema_version,
                    "decision_prompt_sha256": prompt.digest,
                    "decision_projection_sha256": key,
                    "engine_identity": self.identity,
                },
                request_limits=self.request_limits,
            )
        except Exception as exc:  # noqa: BLE001 - every transport fault fails closed
            after_attempts, after_hits = self.transport.counters()
            self._account(
                log,
                prompt,
                before_attempts,
                before_hits,
                after_attempts,
                after_hits,
            )
            violation = (
                STRUCTURED_TOOL_CALLS_UNSUPPORTED
                if isinstance(exc, ToolCallsUnsupported)
                else type(exc).__name__
            )
            log.violations.append(violation)
            logger.warning(
                "repair structured decision refused %s",
                {"state_sha256": state_sha256, "reason": violation},
            )
            return None, log

        after_attempts, after_hits = self.transport.counters()
        self._account(
            log,
            prompt,
            before_attempts,
            before_hits,
            after_attempts,
            after_hits,
        )
        try:
            domain = decode_repair_tool_arguments(
                result.arguments,
                _tool_context(issues, repair_state, self.config),
                tool,
            )
            decision = _canonical_decision(
                domain, issues, repair_state, self.config
            )
            repair_state.preflight(decision)
        except (
            ToolCallError,
            RepairContractError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            violation = type(exc).__name__
            log.violations.append(violation)
            logger.warning(
                "repair structured decision rejected %s",
                {"state_sha256": state_sha256, "reason": violation},
            )
            return None, log
        return decision, log

    def _account(
        self,
        log: RequestLog,
        prompt: Prompt,
        before_attempts: int,
        before_hits: int,
        after_attempts: int,
        after_hits: int,
    ) -> None:
        log.provider_attempts = max(0, after_attempts - before_attempts)
        log.cache_hits = max(0, after_hits - before_hits)
        verdict = (
            SERVED_BYPASSED
            if self.ignore_cache
            else STRUCTURED_TOOL_CACHE_HIT
            if log.cache_hits
            else SERVED_MISS
        )
        for attempt in range(1, log.provider_attempts + 1):
            log.calls.append(
                attribution(
                    GROUP_DECISION,
                    SERVED_RETRY if attempt > 1 else verdict,
                    log.key,
                    prompt.digest,
                    prompt.text,
                    attempt,
                    identity=self.identity,
                )
            )
