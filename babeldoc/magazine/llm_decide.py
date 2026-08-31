"""The decision step: which action, on which findings, with what parameters.

One request per round, a round being one detector kind, taken in the order
``configs/decision_rounds.json`` declares. The reply is a single JSON object and
is held to the shape and the vocabulary the request stated: anything but the
four declared fields, an action outside the set that round offered, a finding id
that was not shown, or a parameter the action does not declare or whose value
falls outside its range are all violations. A violated reply is asked for once
more with the violation stated back to it, and a second violation abandons the
round rather than guessing.

What is checked here is deliberately narrow: shape and vocabulary, nothing else.
Whether a named finding is one the action may actually act on is a separate,
deterministic question, and it is asked afterwards by the admission rules. That
separation is the point. A validator that also enforced admission would be
holding the model to a rule it can only partly see, and would turn "the model
named something the rule refuses" -- an ordinary, expected outcome -- into a
violation that costs the round its retry. So a decision that passes here is a
*nomination* and nothing more; the admission rules keep an unconditional veto
over it, and a nomination they refuse is not an error anywhere.

Nothing here writes to the document, and nothing here decides anything the
caller cannot discard.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path

from babeldoc.magazine.prompt_loader import load_prompt
from babeldoc.magazine.resource_paths import config_path

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("repair_actions.json")
ROUNDS_PATH = config_path("decision_rounds.json")

DECIDE_PROMPT = "react_repair_decide"
RETRY_PROMPT = "vlm_retry_notice"

# The audit trail. Every attempt of every round is appended, request and reply
# in full, so a decision in a report can be read back to the words that
# produced it.
DECISION_LOG_NAME = "repair_decisions.jsonl"

NO_OP = "no_op"

# Fields a reply must carry, and the only ones it may. An extra field is a
# reply to a different request than the one that was sent.
REQUIRED_FIELDS = ("action", "issue_ids", "parameters", "reason")

# How a round ended, closed.
DECIDED = "decided"
ABANDONED_AFTER_RETRY = "abandoned_after_retry"
NO_CANDIDATES = "no_candidates"
OUTCOMES = (DECIDED, ABANDONED_AFTER_RETRY, NO_CANDIDATES)

_RANGE = re.compile(
    r"(-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))\.\."
    r"(-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))\Z"
)

# One sentence per action, stating the deterministic rule that action applies to
# every finding a decision names for it. The sentences live here and the numbers
# they state live in the configuration, so the rule the model is shown and the
# rule the admission code applies cannot state different figures. An action with
# no entry is offered without conditions, which is what "no_op" is.
_CONSTRAINT_SENTENCES = {
    "translate_orphan_text": (
        "the finding's paragraph carries one of the layout labels {labels}, is "
        "claimed by no article, and reports a residue ratio of at least "
        "{min_residue_ratio} over at least {min_source_chars} source characters"
    ),
    "refit_or_reflow_owned_paragraph": (
        "the finding's paragraph is claimed by an article, carries one of the "
        "roles {roles}, and -- where the finding is a collision -- covers no "
        "more than {collision_max_area_ratio} of the area it shares; where "
        "the finding is a text_figure_overlap it must report an "
        "ornament-grade path (asset_class ornament_path) standing in the "
        "first line's own band, and the repair re-sets the paragraph in its "
        "own box with the first line advanced past the ornament's right edge "
        "plus clearance_pt -- the ornament itself never moves, and a "
        "paragraph the advance cannot fit is refused"
    ),
}


class DecisionError(ValueError):
    """Raised when the decision configuration or its inputs are malformed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DecisionError(message)


def _range(raw: object, where: str) -> tuple[float, float]:
    match = _RANGE.fullmatch(raw) if isinstance(raw, str) else None
    _require(match is not None, f"{where}: malformed allowed range {raw!r}")
    low, high = float(match.group(1)), float(match.group(2))
    _require(low <= high, f"{where}: inverted allowed range {raw!r}")
    return low, high


def _bounded(raw: Mapping, key: str, where: str, *, integer: bool = False):
    value = raw.get(key)
    low, high = _range(raw.get(f"{key}_allowed_range"), f"{where}.{key}")
    _require(
        isinstance(value, int | float) and not isinstance(value, bool),
        f"{where}.{key} must be a number",
    )
    if integer:
        _require(float(value).is_integer(), f"{where}.{key} must be a whole number")
        value = int(value)
    _require(low <= value <= high, f"{where}.{key} is outside {low}..{high}")
    return value


@dataclass(frozen=True)
class Parameter:
    """One bounded number a decision is allowed to set."""

    name: str
    default: float
    low: float
    high: float

    def coerce(self, value) -> tuple[float | None, str]:
        """The value if it is a number inside the range, or the violation."""
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None, f"parameter {self.name!r} is not a number"
        if not self.low <= float(value) <= self.high:
            return (
                None,
                f"parameter {self.name!r} is {value}, outside "
                f"{self.low}..{self.high}",
            )
        return float(value), ""


@dataclass(frozen=True)
class DecideConfig:
    """Everything the decision step is bounded by, from one file."""

    model: str
    temperature: float
    max_attempts: int
    max_issues_per_round: int
    issue_excerpt_chars: int
    parameters: Mapping[str, Mapping[str, Parameter]]
    issue_actions: Mapping[str, tuple[str, ...]]
    constraints: Mapping[str, str]

    def offered_actions(self, kind: str) -> tuple[str, ...]:
        """The closed set of actions one round may choose from.

        ``no_op`` is in every round: a round that could only act would have no
        way to say that nothing here is worth acting on.
        """
        declared = self.issue_actions.get(kind, ())
        return tuple(dict.fromkeys((*declared, NO_OP)))

    def parameters_for(self, action: str) -> Mapping[str, Parameter]:
        return self.parameters.get(action, {})


@dataclass(frozen=True)
class Decision:
    """One round's nomination, as the caller is free to accept or discard."""

    kind: str
    outcome: str
    action: str = NO_OP
    issue_ids: tuple[str, ...] = ()
    parameters: Mapping[str, float] = field(default_factory=dict)
    reason: str = ""
    attempts: int = 0
    violations: tuple[str, ...] = ()

    @property
    def acts(self) -> bool:
        return self.action != NO_OP and bool(self.issue_ids)

    def as_record(self) -> dict:
        return {
            "kind": self.kind,
            "outcome": self.outcome,
            "action": self.action,
            "issue_ids": list(self.issue_ids),
            "parameters": dict(self.parameters),
            "reason": self.reason,
            "attempts": self.attempts,
            "violations": list(self.violations),
        }


def _parameter(name: str, raw: object, where: str) -> Parameter:
    _require(isinstance(raw, dict), f"{where}.{name} must be an object")
    _require(
        set(raw) == {"default", "allowed_range"},
        f"{where}.{name} must declare exactly a default and an allowed range",
    )
    low, high = _range(raw.get("allowed_range"), f"{where}.{name}")
    default = raw.get("default")
    _require(
        isinstance(default, int | float) and not isinstance(default, bool),
        f"{where}.{name}.default must be a number",
    )
    _require(
        low <= float(default) <= high,
        f"{where}.{name}.default is outside its own range",
    )
    return Parameter(name=name, default=float(default), low=low, high=high)


def _constraints(raw: Mapping) -> dict[str, str]:
    """The stated rule per action, its own numbers substituted from the file."""
    orphan = raw.get("translate_orphan_text") or {}
    refit = raw.get("refit_or_reflow_owned_paragraph") or {}
    values = {
        "translate_orphan_text": {
            "labels": ", ".join(orphan.get("layout_labels") or ()),
            "min_residue_ratio": orphan.get("min_residue_ratio"),
            "min_source_chars": orphan.get("min_source_chars"),
        },
        "refit_or_reflow_owned_paragraph": {
            "roles": ", ".join(refit.get("eligible_roles") or ()),
            "collision_max_area_ratio": refit.get("collision_max_area_ratio"),
        },
    }
    stated = {}
    for action, sentence in _CONSTRAINT_SENTENCES.items():
        supplied = values.get(action)
        if supplied is None or any(item is None for item in supplied.values()):
            continue
        stated[action] = sentence.format(**supplied)
    return stated


def parse_decide_config(raw: object, source: str) -> DecideConfig:
    _require(isinstance(raw, dict), f"{source}: root must be an object")
    model = raw.get("decide_model")
    vocabulary = raw.get("decide_model_vocabulary")
    _require(
        isinstance(vocabulary, list)
        and bool(vocabulary)
        and all(isinstance(item, str) and item for item in vocabulary),
        f"{source}: decide_model_vocabulary must list model names",
    )
    _require(
        model in vocabulary,
        f"{source}: decide_model is {model!r}, outside {sorted(vocabulary)}",
    )
    declared = raw.get("decide_parameters")
    _require(
        isinstance(declared, dict),
        f"{source}: decide_parameters must be an object",
    )
    actions = tuple(raw.get("actions") or ())
    unknown = sorted(set(declared) - set(actions))
    _require(
        not unknown,
        f"{source}: decide_parameters names actions {unknown}, which the "
        f"vocabulary does not declare",
    )
    issue_actions = raw.get("issue_actions")
    _require(
        isinstance(issue_actions, dict) and issue_actions,
        f"{source}: issue_actions must be a non-empty object",
    )
    offered: dict[str, tuple[str, ...]] = {}
    for kind, value in issue_actions.items():
        names = (value,) if isinstance(value, str) else tuple(value or ())
        # An empty set is a kind that may only be escalated: the round is still
        # taken and no_op is still offered, so the model can say so explicitly
        # rather than the round being silently skipped.
        _require(
            all(isinstance(item, str) and item for item in names),
            f"{source}: issue_actions.{kind} must name actions",
        )
        outside = sorted(set(names) - set(actions))
        _require(
            not outside,
            f"{source}: issue_actions.{kind} names {outside}, outside the "
            f"action vocabulary",
        )
        offered[kind] = names
    return DecideConfig(
        model=str(model),
        temperature=float(
            _bounded(raw, "decide_temperature", f"{source}")
        ),
        max_attempts=_bounded(
            raw, "decide_max_attempts", f"{source}", integer=True
        ),
        max_issues_per_round=_bounded(
            raw, "decide_max_issues_per_round", f"{source}", integer=True
        ),
        issue_excerpt_chars=_bounded(
            raw, "decide_issue_excerpt_chars", f"{source}", integer=True
        ),
        parameters={
            action: {
                name: _parameter(name, value, f"{source}.decide_parameters.{action}")
                for name, value in (params or {}).items()
            }
            for action, params in declared.items()
        },
        issue_actions=offered,
        constraints=_constraints(raw),
    )


def load_decide_config(path: str | None = None) -> DecideConfig:
    selected = CONFIG_PATH if path is None else Path(path)
    return parse_decide_config(
        json.loads(selected.read_text(encoding="utf-8")), selected.name
    )


def kind_order(path: str | None = None) -> tuple[str, ...]:
    """The order the rounds are taken in, exactly as declared."""
    selected = ROUNDS_PATH if path is None else Path(path)
    raw = json.loads(selected.read_text(encoding="utf-8"))
    order = raw.get("kind_order")
    _require(
        isinstance(order, list)
        and bool(order)
        and len(set(order)) == len(order),
        f"{selected.name}: kind_order must list each kind once",
    )
    return tuple(order)


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


def issues_block(issues: Sequence, excerpt_chars: int, limit: int) -> str:
    """The findings as the request states them, one block each."""
    lines: list[str] = []
    for issue in list(issues)[:limit]:
        evidence = dict(issue.evidence)
        excerpt = str(evidence.pop("excerpt", "") or "")[:excerpt_chars]
        detail = ", ".join(
            f"{key}={value!r}" for key, value in sorted(evidence.items())
        )[:excerpt_chars]
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


def actions_block(config: DecideConfig, offered: Sequence[str]) -> str:
    """The vocabulary this round offers, one block per action."""
    lines: list[str] = []
    for name in offered:
        if name == NO_OP:
            continue
        declared = config.parameters_for(name)
        parameters = (
            "; ".join(
                f"{parameter.name} (number in {parameter.low:g}..{parameter.high:g}, "
                f"default {parameter.default:g})"
                for _key, parameter in sorted(declared.items())
            )
            or "none"
        )
        lines.append(f'- name: "{name}"\n  parameters: {parameters}')
    lines.append(
        f'- name: "{NO_OP}"\n'
        f"  what it does: apply nothing in this round.\n"
        f"  parameters: none"
    )
    return "\n".join(lines)


def constraints_block(config: DecideConfig, offered: Sequence[str]) -> str:
    """The admission rule as the request states it, one block per action.

    Stated so the round is not spent nominating findings the rule will refuse.
    Stating it weakens nothing: the rule is applied from the measurements after
    this step, whatever the reply says.
    """
    lines = [
        f'- "{name}" acts on a finding only when: {config.constraints[name]}'
        for name in offered
        if name in config.constraints
    ]
    return "\n".join(lines) if lines else "- none"


def interpret(
    reply: str,
    *,
    offered_actions: Sequence[str],
    offered_ids: set[str],
    config: DecideConfig,
    kind: str,
):
    """One reply as a nomination, or the violation that refuses it.

    Shape and vocabulary only. Whether the named findings are ones the action
    may act on is not asked here and is not this function's to answer.
    """
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
    if name not in offered_actions:
        return (
            None,
            f"action {name!r} is outside the vocabulary this round offered; "
            f"offered were {sorted(offered_actions)}",
        )

    ids = parsed["issue_ids"]
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
        return None, "issue_ids is not an array of strings"
    unknown = sorted(set(ids) - offered_ids)
    if unknown:
        return None, f"issue_ids names findings that were not offered: {unknown}"

    reason = parsed["reason"]
    if not isinstance(reason, str):
        return None, "reason is not a string"

    supplied = parsed["parameters"]
    if not isinstance(supplied, dict):
        return None, "parameters is not an object"

    if name == NO_OP:
        if ids:
            return None, f"action is {NO_OP!r} but issue_ids is not empty"
        if supplied:
            return None, f"action is {NO_OP!r} but parameters is not empty"
        return (
            Decision(kind=kind, outcome=DECIDED, action=NO_OP, reason=reason),
            "",
        )

    declared = config.parameters_for(name)
    undeclared = sorted(set(supplied) - set(declared))
    if undeclared:
        return (
            None,
            f"parameters names {undeclared}, which {name!r} does not declare",
        )
    resolved: dict[str, float] = {
        key: parameter.default for key, parameter in declared.items()
    }
    for key, value in supplied.items():
        coerced, violation = declared[key].coerce(value)
        if violation:
            return None, violation
        resolved[key] = coerced

    if not ids:
        return None, f"action {name!r} was chosen with no findings to apply it to"
    return (
        Decision(
            kind=kind,
            outcome=DECIDED,
            action=name,
            issue_ids=tuple(ids),
            parameters=resolved,
            reason=reason,
        ),
        "",
    )


class OpenAIDecisionClient:
    """The model, asked one question, with no cache and no retry of its own.

    Retries that belong to the protocol -- a reply the validator refused -- are
    the caller's and are visible in the audit log. Nothing is retried silently
    here.
    """

    def __init__(self, config: DecideConfig, api_key: str | None = None):
        from openai import OpenAI

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise DecisionError(
                "a repair decision needs OPENAI_API_KEY in the environment"
            )
        self._client = OpenAI(api_key=key)
        self._config = config

    def ask(self, prompt: str) -> str:
        completion = self._client.chat.completions.create(
            model=self._config.model,
            temperature=self._config.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return completion.choices[0].message.content or ""


def _log(working_dir: Path | str | None, row: dict) -> None:
    if working_dir is None:
        return
    path = Path(working_dir) / DECISION_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def decide_round(
    kind: str,
    issues: Sequence,
    client,
    config: DecideConfig,
    *,
    working_dir: Path | str | None = None,
    iteration: int = 0,
) -> Decision:
    """Ask for one round's nomination, once, and once more if it was refused."""
    if not issues:
        return Decision(kind=kind, outcome=NO_CANDIDATES)
    if working_dir is not None:
        # The prompt loader files its manifest beside the audit log, and both
        # are written before anything else has had reason to make the directory.
        Path(working_dir).mkdir(parents=True, exist_ok=True)
    offered_actions = config.offered_actions(kind)
    shown = list(issues)[: config.max_issues_per_round]
    offered_ids = {issue.id for issue in shown}
    prompt = load_prompt(
        DECIDE_PROMPT,
        {
            "issues_block": issues_block(
                shown, config.issue_excerpt_chars, config.max_issues_per_round
            ),
            "actions_block": actions_block(config, offered_actions),
            "action_constraints": constraints_block(config, offered_actions),
        },
        working_dir=working_dir,
    )
    text = prompt.text
    violations: list[str] = []
    for attempt in range(1, config.max_attempts + 1):
        reply = client.ask(text)
        decision, violation = interpret(
            reply,
            offered_actions=offered_actions,
            offered_ids=offered_ids,
            config=config,
            kind=kind,
        )
        _log(
            working_dir,
            {
                "at": datetime.now(UTC).isoformat(),
                "iteration": iteration,
                "kind": kind,
                "attempt": attempt,
                "offered_actions": list(offered_actions),
                "offered_ids": sorted(offered_ids),
                "request": text,
                "reply": reply,
                "violation": violation,
            },
        )
        if decision is not None:
            return Decision(
                kind=decision.kind,
                outcome=DECIDED,
                action=decision.action,
                issue_ids=decision.issue_ids,
                parameters=decision.parameters,
                reason=decision.reason,
                attempts=attempt,
                violations=tuple(violations),
            )
        violations.append(violation)
        if attempt == config.max_attempts:
            break
        retry = load_prompt(RETRY_PROMPT, {"violation": violation})
        text = f"{prompt.text}\n\n{retry.text}"
    logger.warning("repair decision for %s abandoned: %s", kind, violations)
    return Decision(
        kind=kind,
        outcome=ABANDONED_AFTER_RETRY,
        action=NO_OP,
        attempts=config.max_attempts,
        violations=tuple(violations),
    )
