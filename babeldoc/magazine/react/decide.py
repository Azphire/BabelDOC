"""The decision step: which action, on which findings, with what parameters.

One request per iteration, through the run's own engine, filed in the project
cache under a key naming the prompt file it came from. The reply is a JSON
object and is held to the vocabulary the request stated: an action name outside
it, a finding id that was not offered, a parameter the action does not declare
or a value outside its range are all violations. A violated reply is asked for
again once with the violation stated back, and a second violation abandons the
iteration rather than guessing -- not repairing is the safe failure of a repair
loop, and the loop's own guard would have to undo a wrong guess anyway.

Nothing here writes to the document. What it returns is a decision the caller
is free to reject: the applicability rule below it decides whether the findings
the decision named are ones the action may act on, and that rule is
deterministic and is not the model's to overrule.
"""

from __future__ import annotations

import json
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
from babeldoc.magazine.react.cache_key import SERVED_STALE
from babeldoc.magazine.react.cache_key import attribution
from babeldoc.magazine.react.config import NO_ACTION
from babeldoc.magazine.react.config import RepairConfig
from babeldoc.magazine.react.config import RepairConfigError
from babeldoc.translator.cache import TranslationCache

logger = logging.getLogger(__name__)

DECIDE_PROMPT = "react_repair_decide"

# The generic notice a rejected reply is asked again with, shared with the
# vision client: what it says is true of any strict-shape request.
RETRY_PROMPT = "vlm_retry_notice"

# Engine name the decisions are filed under, keeping them out of the translated
# segments sharing the database. The column is 20 characters wide.
ENGINE_NAME = "magazine_repair"

# The composition a key is built by, shared with the orphan action's cache so
# the two cannot drift apart. Named here as well because the engine parameters
# the stored replies are filed under carry it, and those have to move when the
# composition does.
CACHE_KEY_VERSION = cache_key_fields.CACHE_KEY_VERSION

# Fields a reply must carry. Anything else in the object is a violation: an
# extra field is a reply to a different request than the one that was sent.
REQUIRED_FIELDS = ("action", "issue_ids", "parameters", "reason")


@dataclass(frozen=True)
class Decision:
    """One iteration's choice, as the loop is allowed to act on it."""

    action: str
    issue_ids: tuple[str, ...]
    parameters: dict[str, float]
    reason: str
    attempts: int = 0
    from_cache: bool = False
    raw: str = ""
    violations: tuple[str, ...] = ()

    @property
    def acts(self) -> bool:
        return self.action != NO_ACTION and bool(self.issue_ids)

    @property
    def refused(self) -> bool:
        return self.action == ""

    def as_record(self) -> dict:
        return {
            "action": self.action,
            "issue_ids": list(self.issue_ids),
            "parameters": dict(self.parameters),
            "reason": self.reason,
            "attempts": self.attempts,
            "from_cache": self.from_cache,
            "raw": self.raw,
            "violations": list(self.violations),
        }


REFUSED = Decision(action="", issue_ids=(), parameters={}, reason="")


@dataclass
class RequestLog:
    """What one decision point sent, for the sidecar."""

    prompt_digest: str = ""
    prompt_text: str = ""
    key: str = ""
    replies: list[str] = field(default_factory=list)
    # One row per call that reached the transport, which is one row per call
    # the run is billed for. A request the cache answered adds none.
    calls: list[dict] = field(default_factory=list)


class EngineTransport:
    """The run's translation engine, asked a question that is not a translation.

    A repair decision is a text request to the model already configured for the
    run, so it travels that engine's transport: its credential, its endpoint and
    its rate limiter, none of which is configured a second time here. The
    engine's own cache is bypassed, because the cache that serves a decision is
    the one below, whose key names the prompt file the request came from.
    """

    def __init__(self, engine):
        self.engine = engine

    def complete(self, prompt_text: str) -> str:
        return self.engine.llm_translate(
            prompt_text,
            ignore_cache=True,
            rate_limit_params={"request_json_mode": True},
        )


def engine_identity(engine, lang_out: str) -> str:
    """What about the engine could change a decision, as a cache key fragment."""
    return f"{type(engine).__name__}/{getattr(engine, 'name', '')}/{lang_out}"


def cache_key(prompt: Prompt, identity: str, version: int | None = None) -> str:
    """Digest of everything that could change the answer to one request.

    Given the key rendering of a request rather than the sent one, so two runs
    whose findings differ only in the ids the paragraph finder minted afresh
    reach one key and the second is served what the first paid for.

    ``version`` is for replaying a key an earlier batch filed under an earlier
    composition; a run leaves it alone.
    """
    return cache_key_fields.digest(identity, prompt.digest, prompt.text, version)


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
            f"  paragraphs: {', '.join(issue.paragraph_refs)}\n"
            f"  evidence: {detail}\n"
            f"  text as the page renders it: {excerpt}"
        )
    if len(issues) > limit:
        lines.append(
            f"- and {len(issues) - limit} further finding(s), not shown; the "
            f"loop will see them again next iteration"
        )
    return "\n".join(lines) if lines else "- none"


def actions_block(config: RepairConfig, language: str | None = None) -> str:
    """The vocabulary as the request states it, one block per action."""
    lines: list[str] = []
    for name, action in sorted(config.actions.items()):
        parameters = (
            "; ".join(
                f"{parameter.name} (number in {parameter.low}..{parameter.high}, "
                f"default {parameter.default:g})"
                for _key, parameter in sorted(action.parameters.items())
            )
            or "none"
        )
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


def interpret(reply: str, config: RepairConfig, offered: set[str]):
    """One reply as a decision, or the violation that refuses it."""
    try:
        parsed = json.loads(strip_fence(reply))
    except (ValueError, TypeError) as exc:
        return None, f"reply is not JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, f"reply is a {type(parsed).__name__}, not one JSON object"
    missing = [name for name in REQUIRED_FIELDS if name not in parsed]
    if missing:
        return None, f"reply omits {missing}"
    extra = sorted(set(parsed) - set(REQUIRED_FIELDS))
    if extra:
        return None, f"reply carries fields nothing asked for: {extra}"

    name = parsed["action"]
    if not isinstance(name, str):
        return None, "action is not a string"
    action = config.action(name)
    if action is None and name != NO_ACTION:
        return (
            None,
            f"action {name!r} is outside the vocabulary; declared are "
            f"{sorted(config.actions) + [NO_ACTION]}",
        )

    ids = parsed["issue_ids"]
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
        return None, "issue_ids is not an array of strings"
    unknown = sorted(set(ids) - offered)
    if unknown:
        return None, f"issue_ids names findings that were not offered: {unknown}"

    reason = parsed["reason"]
    if not isinstance(reason, str):
        return None, "reason is not a string"

    if action is None:
        if ids:
            return None, f"action is {NO_ACTION!r} but issue_ids is not empty"
        return (
            Decision(
                action=NO_ACTION, issue_ids=(), parameters={}, reason=reason, raw=reply
            ),
            "",
        )

    try:
        parameters = action.resolve(parsed["parameters"])
    except RepairConfigError as exc:
        return None, str(exc)
    if not ids:
        return None, f"action {name!r} was chosen with no findings to apply it to"
    return (
        Decision(
            action=name,
            issue_ids=tuple(ids),
            parameters=parameters,
            reason=reason,
            raw=reply,
        ),
        "",
    )


class CachedDecisionClient:
    """One decision point: cache lookup, bounded attempts, closed vocabulary."""

    def __init__(
        self,
        config: RepairConfig,
        transport=None,
        cache: TranslationCache | None = None,
        identity: str = "",
        working_dir: Path | str | None = None,
        ignore_cache: bool = False,
        language: str | None = None,
    ) -> None:
        self.config = config
        # The run's target language, because an applicability term declared for
        # one language governs this decision and the sentence the model reads
        # has to carry the value that governs.
        self.language = language
        self.transport = transport
        self.cache = (
            TranslationCache(ENGINE_NAME, {"cache_key_version": CACHE_KEY_VERSION})
            if cache is None
            else cache
        )
        self.identity = identity
        self.working_dir = working_dir
        self.ignore_cache = ignore_cache

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

    def _retry_text(self, prompt: Prompt, violation: str) -> str:
        notice = load_prompt(
            RETRY_PROMPT, {"violation": violation}, working_dir=self.working_dir
        )
        return f"{prompt.text}\n\n{notice.text}"

    def decide(self, issues) -> tuple[Decision, RequestLog]:
        """Choose one action for one iteration, from cache where it is not new."""
        prompt = self.prompt(issues)
        offered = {issue.id for issue in issues[: self.config.max_issues_offered]}
        key = cache_key(self.key_prompt(issues), self.identity)
        log = RequestLog(prompt_digest=prompt.digest, prompt_text=prompt.text, key=key)
        verdict = SERVED_BYPASSED if self.ignore_cache else SERVED_MISS

        if not self.ignore_cache:
            try:
                stored = self.cache.get(key)
            except Exception as exc:  # noqa: BLE001 - a cache is never a hard failure
                logger.debug("decision cache lookup failed, ignoring it: %s", exc)
                stored = None
            if stored is not None:
                log.replies.append(stored)
                decision, violation = interpret(stored, self.config, offered)
                if decision is not None:
                    return (
                        Decision(
                            action=decision.action,
                            issue_ids=decision.issue_ids,
                            parameters=decision.parameters,
                            reason=decision.reason,
                            attempts=0,
                            from_cache=True,
                            raw=stored,
                        ),
                        log,
                    )
                # A stored reply that no longer validates means the vocabulary
                # moved under it. Ask again rather than serve what cannot be used.
                logger.debug("cached decision rejected, re-requesting: %s", violation)
                verdict = SERVED_STALE

        text = prompt.text
        violations: list[str] = []
        attempts = 0
        while attempts < self.config.decide_max_attempts:
            attempts += 1
            log.calls.append(
                attribution(
                    GROUP_DECISION,
                    SERVED_RETRY if attempts > 1 else verdict,
                    key,
                    prompt.digest,
                    text,
                    attempts,
                    identity=self.identity,
                )
            )
            try:
                reply = self.transport.complete(text)
            except Exception as exc:  # noqa: BLE001 - any failure is a violation
                violations.append(f"request failed: {type(exc).__name__}: {exc}")
                text = self._retry_text(prompt, violations[-1])
                continue
            log.replies.append(reply)
            decision, violation = interpret(reply, self.config, offered)
            if decision is not None:
                if not self.ignore_cache:
                    try:
                        self.cache.set(key, reply)
                    except Exception as exc:  # noqa: BLE001 - see above
                        logger.debug("decision cache write failed, ignoring: %s", exc)
                return (
                    Decision(
                        action=decision.action,
                        issue_ids=decision.issue_ids,
                        parameters=decision.parameters,
                        reason=decision.reason,
                        attempts=attempts,
                        raw=reply,
                        violations=tuple(violations),
                    ),
                    log,
                )
            violations.append(violation)
            text = self._retry_text(prompt, violation)

        logger.warning(
            "react: no usable decision after %d attempt(s); this iteration "
            "applies nothing. %s",
            attempts,
            "; ".join(violations),
        )
        return (
            Decision(
                action="",
                issue_ids=(),
                parameters={},
                reason="",
                attempts=attempts,
                raw=log.replies[-1] if log.replies else "",
                violations=tuple(violations),
            ),
            log,
        )
