"""The bounds of the repair loop, and the vocabulary a decision may name.

Two things live in ``configs/repair_actions.json``: what the loop is allowed to
do to itself -- how many iterations, how many attempts at a decision, how much
one request may carry -- and the closed vocabulary of actions, each carrying the
issue kinds it answers for, the parameters it takes with a range each, and the
applicability rule that decides whether one particular finding is one it may act
on.

Applicability is separate from detection on purpose and is stricter. A detector
reports what looks wrong; an action has to be sure, because a defect left
standing costs one defect and a correct paragraph rewritten costs a correct
paragraph. Nothing here names a page type, a publication or a sample: an action
is selected by the kind of the finding, and a finding is admitted by terms its
own action declares -- the share of the wrong script and the layout label that
says whether the translator was ever given the chance to see the paragraph, for
the one that rewrites text; how far past the page frame the ink reached and what
class of block it belongs to, for the one that puts it back inside.

An action also declares the numbers its own mechanism is bounded by, at its own
level rather than among its parameters, because they are neither something a
decision may set nor something that selects a finding: a floor on how far a
heading may be shrunk before shrinking it is the wrong answer is one of these.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import _parse_range
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.repair_contract import RepairAction
from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("repair_actions.json")

ACTIONS_KEY = "actions"
PARAMETERS_KEY = "parameters"
APPLICABILITY_KEY = "applicability"
ISSUE_KINDS_KEY = "issue_kinds"
DEFAULT_KEY = "default"
RANGE_SUFFIX = "_allowed_range"

# How each applicability term reads to a reader, keyed by the term it states.
# The rule is enforced from the numbers beside it and is stated from here, so
# what a request tells a model about the filter it is feeding cannot drift from
# what the filter does: both are this one declaration.
STATEMENTS_KEY = "statements"

# Where the term's own value is substituted into its statement.
STATEMENT_VALUE = "{value}"

# The name a decision uses to apply nothing. Reserved, so no action may take it.
NO_ACTION = "no_action"
MUTATING_ACTIONS = frozenset(
    action.value for action in RepairAction if action is not RepairAction.NO_ACTION
)

# The parameter every action that touches paragraphs declares: how many of them
# one iteration may take. Named here rather than in one action's module because
# the loop reads it to bound an iteration whichever action it is carrying out.
MAX_PARAGRAPHS = "max_paragraphs"

# Applicability keys the orphan action is built from.
MIN_RATIO_KEY = "min_residue_ratio"
# The same bound, declared for one target language and overriding the general
# one there. Named by the direction it governs, as the detector's own residue
# bounds are, so the two files spell a direction the same way.
MIN_RATIO_BY_LANGUAGE_FORMAT = "min_residue_ratio_into_{language}"

# What separates a general applicability term from the language it is declared
# for. One spelling, so a term overriding another is recognised by shape rather
# than by being listed somewhere.
LANGUAGE_INFIX = "_into_"
MIN_CHARS_KEY = "min_source_chars"
ORPHAN_LABELS_KEY = "orphan_layout_labels"
# The second jurisdiction, and optional rather than required: a configuration an
# earlier batch froze declares only the first, and a parser that refuses last
# year's file makes last year's run unreplayable. Absent, it is false, which is
# what those configurations meant.
ORPHAN_VERTICAL_KEY = "orphan_accepts_vertical"
ORPHAN_VERTICAL_DEFAULT = False

# Applicability keys the containment action is built from.
CONTAIN_LABELS_KEY = "contain_layout_labels"
MIN_OVERFLOW_KEY = "min_overflow_ratio"

# The applicability key the collision action is built from. Coverage alone: the
# detector is bounded by either measure, and the action needs only this one
# because the other can select nothing the area asymmetry bound does not refuse
# first. See the action's own module for why.
MIN_COLLISION_COVERAGE_KEY = "min_collision_coverage"

# The bound that key replaced. Not read by the action any more, and named here
# because a configuration an earlier batch froze declares it and has to stay
# readable: reproducing the request that batch sent needs the configuration it
# shipped, so a parser that refuses last year's file makes last year's run
# unreplayable.
LEGACY_COLLISION_IOU_KEY = "min_collision_iou"

# The evidence fields kept out of a cache key, declared beside the loop's other
# bounds because it is the loop's requests they are keys for.
VOLATILE_EVIDENCE_KEY = "volatile_evidence_keys"

# Which applicability terms each action's rule is made of. An action whose rule
# omits one of them is a rule the code answering for that action cannot apply,
# and that is a fault in the file rather than a surprise at run time. Declared
# per action rather than as one list for all of them: the actions do not share a
# rule, and requiring the orphan action's terms of a geometric one would be
# requiring a filter that means nothing there.
REQUIRED_APPLICABILITY = {
    "reprocess_omitted_text": (MIN_RATIO_KEY, MIN_CHARS_KEY, ORPHAN_LABELS_KEY),
    "reallocate_continuity_chain": ("requires_complete_target",),
    "retypeset_article_region": ("requires_legal_slots",),
    "contain_overflowing_heading": (CONTAIN_LABELS_KEY, MIN_OVERFLOW_KEY),
    "resolve_text_collision": (),
}

# Terms an action's rule may declare in place of one another, of which it must
# declare at least one. Only the collision rule has any: it was written against
# the union ratio's bound and is written against coverage's, so a configuration
# frozen by an earlier batch names the first and one written now names the
# second. Both are rules this file can read, and a collision rule naming neither
# is a filter that selects everything, which is the fault worth refusing. The
# action itself reads only the current term and refuses every finding under a
# rule that carries the older one, rather than reading a bound that means
# something else.
ALTERNATIVE_APPLICABILITY = {
    "resolve_text_collision": (
        MIN_COLLISION_COVERAGE_KEY,
        LEGACY_COLLISION_IOU_KEY,
    ),
}


class RepairConfigError(ConfigError):
    """Raised when the repair configuration is malformed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RepairConfigError(message)


@dataclass(frozen=True)
class Parameter:
    """One bounded argument of one action."""

    name: str
    default: float
    low: float
    high: float

    def coerce(self, value) -> float:
        """The value if it is a number inside the range, or a refusal."""
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RepairConfigError(f"{self.name} is not a number: {value!r}")
        if not self.low <= float(value) <= self.high:
            raise RepairConfigError(
                f"{self.name}={value} outside allowed range {self.low}..{self.high}"
            )
        return float(value)

    def as_record(self) -> dict:
        return {
            "name": self.name,
            "default": self.default,
            "allowed_range": f"{self.low}..{self.high}",
        }


@dataclass(frozen=True)
class Action:
    """One member of the vocabulary a decision may name."""

    name: str
    description: str
    issue_kinds: tuple[str, ...]
    max_applications: int
    parameters: dict[str, Parameter]
    applicability: dict[str, object]
    statements: dict[str, str]
    # Numbers the action's mechanism is bounded by, as opposed to the parameters
    # a decision may set and the terms that decide which findings it may act on.
    # A floor on how far a heading may be shrunk is one of these: it is not the
    # model's to move and it does not select anything.
    bounds: dict[str, object] = field(default_factory=dict)

    def bound(self, name: str):
        """One declared mechanism bound, which validation guarantees is there."""
        return self.bounds[name]

    def answers_for(self, kind: str) -> bool:
        return kind in self.issue_kinds

    def overridden_by(self, language: str | None) -> dict[str, str]:
        """Which general terms this run's target language replaces, and with what.

        A term named ``<term>_into_<language>`` overrides ``<term>`` for a run
        finishing into that language, by the same longest declared prefix match
        every other per language rule in this project uses.
        """
        tag = (language or "").strip().lower()
        taken: dict[str, str] = {}
        for key in self.applicability:
            general, separator, suffix = key.partition(LANGUAGE_INFIX)
            if not separator or general not in self.applicability:
                continue
            if not tag.startswith(suffix):
                continue
            if general not in taken or len(suffix) > len(
                taken[general].partition(LANGUAGE_INFIX)[2]
            ):
                taken[general] = key
        return taken

    def conditions(self, language: str | None = None) -> list[str]:
        """Each applicability term as one sentence, its own value substituted.

        In the file's own order, so the sentences read the way the rule is
        written rather than in an order chosen here.

        A term the run's target language overrides is rendered with the value
        that actually governs, and the override's own sentence is dropped. Both
        would be worse than either: the decision this list is written for is
        taken by a model reading it, and a rule stated as "at or above 0.9,
        unless" followed by "into English it is 0.05" is read as 0.9 -- which is
        not the rule, and the finding it refuses is one the code would have
        admitted.
        """
        overrides = self.overridden_by(language)
        # Every term declared for a language is rendered through the general
        # term it overrides, never beside it. A run that takes the override sees
        # the general sentence carrying the override's value; a run that does
        # not sees the general sentence carrying the general value. Either way
        # exactly one share is stated, which is the number that governs.
        suffixed = {
            key
            for key in self.applicability
            if LANGUAGE_INFIX in key
            and key.partition(LANGUAGE_INFIX)[0] in self.applicability
        }
        rendered: list[str] = []
        for key, value in self.applicability.items():
            if key in suffixed:
                continue
            statement = self.statements.get(key)
            if statement is None:
                continue
            if key in overrides:
                value = self.applicability[overrides[key]]
            shown = (
                ", ".join(str(item) for item in value)
                if isinstance(value, list | tuple)
                else str(value)
            )
            rendered.append(statement.replace(STATEMENT_VALUE, shown))
        return rendered

    def resolve(self, supplied: object) -> dict[str, float]:
        """The parameters of one application, defaults filled, bounds enforced.

        A name the action does not declare is a violation rather than something
        to drop: a decision naming a parameter that does not exist is a decision
        about an action that does not exist either.
        """
        if supplied is None:
            supplied = {}
        if not isinstance(supplied, dict):
            raise RepairConfigError(f"{self.name}: parameters must be an object")
        unknown = sorted(set(supplied) - set(self.parameters))
        _require(
            not unknown,
            f"{self.name}: parameters names {unknown}, which the action does "
            f"not declare; declared are {sorted(self.parameters)}",
        )
        return {
            name: (
                parameter.coerce(supplied[name])
                if name in supplied
                else parameter.default
            )
            for name, parameter in self.parameters.items()
        }

    def as_record(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "issue_kinds": list(self.issue_kinds),
            "max_applications": self.max_applications,
            "parameters": [
                parameter.as_record()
                for _name, parameter in sorted(self.parameters.items())
            ],
            "applicability": {
                key: (list(value) if isinstance(value, tuple) else value)
                for key, value in sorted(self.applicability.items())
            },
            "bounds": {
                key: (list(value) if isinstance(value, tuple) else value)
                for key, value in sorted(self.bounds.items())
            },
            "conditions": self.conditions(),
        }


@dataclass(frozen=True)
class RepairConfig:
    """Everything bounded about running the loop once."""

    max_iterations: int
    decide_max_attempts: int
    max_issues_offered: int
    issue_excerpt_chars: int
    max_glossary_entries: int
    page_context_chars: int
    volatile_evidence_keys: tuple[str, ...]
    actions: dict[str, Action]

    def action(self, name: str) -> Action | None:
        return self.actions.get(name)

    def as_record(self) -> dict:
        return {
            "max_iterations": self.max_iterations,
            "decide_max_attempts": self.decide_max_attempts,
            "max_issues_offered": self.max_issues_offered,
            "issue_excerpt_chars": self.issue_excerpt_chars,
            "max_glossary_entries": self.max_glossary_entries,
            "page_context_chars": self.page_context_chars,
            "volatile_evidence_keys": list(self.volatile_evidence_keys),
            "actions": [
                action.as_record() for _name, action in sorted(self.actions.items())
            ],
        }


def _bounded(raw: dict, source: str) -> dict:
    """One flat block of the file, validated by the shared range convention."""
    try:
        return dict(validate_bounded_config(raw, CONFIG_PATH))
    except ConfigError as exc:
        raise RepairConfigError(f"{source}: {exc}") from exc


def _parse_parameter(name: str, raw: object, source: str) -> Parameter:
    _require(isinstance(raw, dict), f"{source}.{name} must be an object")
    parameters = _bounded(raw, f"{source}.{name}")
    _require(
        DEFAULT_KEY in parameters,
        f"{source}.{name} declares no {DEFAULT_KEY}",
    )
    low, high = _parse_range(
        raw.get(f"{DEFAULT_KEY}{RANGE_SUFFIX}"), f"{source}.{name}"
    )
    return Parameter(
        name=name,
        default=float(parameters[DEFAULT_KEY]),
        low=low,
        high=high,
    )


def _parse_applicability(
    raw: object, source: str, required, alternatives=()
) -> tuple[dict, dict]:
    """The rule's terms and the sentence each of them is stated with.

    Every term has to carry a statement and every statement has to name a term.
    Neither direction is optional: a term with nothing to say about itself is
    one a request cannot state, and a statement about a term that no longer
    exists is a request describing a filter that is not there.

    ``required`` is what this particular action's rule is made of, so an action
    is held to its own terms rather than to another action's.
    """
    _require(isinstance(raw, dict) and raw, f"{source}: {APPLICABILITY_KEY} is empty")
    flat = {key: value for key, value in raw.items() if key != STATEMENTS_KEY}
    # A term that switches a whole jurisdiction on or off is a boolean, and a
    # boolean is its own bound: there is no range to declare and none to check.
    # Taken out before the numeric validation rather than given a range that
    # would be a fiction, which is the same treatment the page type vocabulary
    # gives an optional boolean policy flag.
    switches = {
        key: value for key, value in flat.items() if isinstance(value, bool)
    }
    parameters = _bounded(
        {key: value for key, value in flat.items() if key not in switches},
        f"{source}.{APPLICABILITY_KEY}",
    )
    parameters.update(switches)
    for key in required:
        _require(
            key in parameters,
            f"{source}: {APPLICABILITY_KEY} omits {key}",
        )
    if alternatives:
        _require(
            any(key in parameters for key in alternatives),
            f"{source}: {APPLICABILITY_KEY} declares none of "
            f"{sorted(alternatives)}",
        )
    statements = raw.get(STATEMENTS_KEY)
    _require(
        isinstance(statements, dict) and bool(statements),
        f"{source}: {APPLICABILITY_KEY} declares no {STATEMENTS_KEY}",
    )
    unstated = sorted(set(parameters) - set(statements))
    _require(
        not unstated,
        f"{source}: {APPLICABILITY_KEY}.{STATEMENTS_KEY} omits {unstated}",
    )
    unknown = sorted(set(statements) - set(parameters))
    _require(
        not unknown,
        f"{source}: {APPLICABILITY_KEY}.{STATEMENTS_KEY} states {unknown}, which "
        f"{APPLICABILITY_KEY} does not declare",
    )
    for key, sentence in statements.items():
        _require(
            isinstance(sentence, str) and STATEMENT_VALUE in sentence,
            f"{source}: {APPLICABILITY_KEY}.{STATEMENTS_KEY}.{key} must be a "
            f"sentence carrying {STATEMENT_VALUE}",
        )
    # The declaration order of the terms, which is the order they read in.
    ordered = {key: parameters[key] for key in flat if key in parameters}
    return ordered, dict(statements)


def _parse_action(name: str, raw: object, kinds: set[str], source: str) -> Action:
    _require(isinstance(raw, dict), f"{source}: action {name} must be an object")
    _require(
        name != NO_ACTION,
        f"{source}: {NO_ACTION!r} is how a decision applies nothing and cannot "
        f"name an action",
    )
    flat = {
        key: value
        for key, value in raw.items()
        if key not in (PARAMETERS_KEY, APPLICABILITY_KEY)
    }
    parameters = _bounded(flat, f"{source}.{name}")
    declared = parameters.get(ISSUE_KINDS_KEY)
    _require(
        bool(declared), f"{source}.{name} declares no {ISSUE_KINDS_KEY}"
    )
    unknown = sorted(set(declared) - kinds)
    _require(
        not unknown or not kinds,
        f"{source}.{name}: {ISSUE_KINDS_KEY} names {unknown}, which no detector "
        f"raises; raised are {sorted(kinds)}",
    )
    _require(
        "max_applications" in parameters,
        f"{source}.{name} declares no max_applications",
    )
    raw_parameters = raw.get(PARAMETERS_KEY) or {}
    _require(
        isinstance(raw_parameters, dict),
        f"{source}.{name}: {PARAMETERS_KEY} must be an object",
    )
    required = REQUIRED_APPLICABILITY.get(name)
    _require(
        required is not None,
        f"{source}.{name}: no code declares what this action's rule is made of; "
        f"the actions with a rule are {sorted(REQUIRED_APPLICABILITY)}",
    )
    applicability, statements = _parse_applicability(
        raw.get(APPLICABILITY_KEY),
        f"{source}.{name}",
        required,
        ALTERNATIVE_APPLICABILITY.get(name, ()),
    )
    return Action(
        name=name,
        description=str(raw.get("description") or ""),
        issue_kinds=tuple(declared),
        max_applications=int(parameters["max_applications"]),
        parameters={
            key: _parse_parameter(key, value, f"{source}.{name}.{PARAMETERS_KEY}")
            for key, value in raw_parameters.items()
        },
        applicability=applicability,
        statements=statements,
        # Whatever else the action declared at its own level: validated by the
        # same range convention, and everything that is not one of the two keys
        # read by name above.
        bounds={
            key: value
            for key, value in parameters.items()
            if key not in (ISSUE_KINDS_KEY, "max_applications")
        },
    )


def parse_repair_config(raw: dict, source: str, kinds: set[str]) -> RepairConfig:
    """Validate one configuration mapping against the issue kinds that exist."""
    flat = {key: value for key, value in raw.items() if key != ACTIONS_KEY}
    parameters = _bounded(flat, source)
    actions_raw = raw.get(ACTIONS_KEY)
    _require(
        isinstance(actions_raw, dict) and actions_raw,
        f"{source}: {ACTIONS_KEY} must be a non-empty object",
    )
    _require(
        set(actions_raw) == MUTATING_ACTIONS,
        f"{source}: {ACTIONS_KEY} must be the closed mutating vocabulary "
        f"{sorted(MUTATING_ACTIONS)}",
    )
    return RepairConfig(
        max_iterations=int(parameters["max_iterations"]),
        decide_max_attempts=int(parameters["decide_max_attempts"]),
        max_issues_offered=int(parameters["max_issues_offered"]),
        issue_excerpt_chars=int(parameters["issue_excerpt_chars"]),
        max_glossary_entries=int(parameters["max_glossary_entries"]),
        page_context_chars=int(parameters["page_context_chars"]),
        # Optional, and empty where it is absent. A configuration written
        # before this key existed is one nobody has classified a field of, and
        # the conservative reading of that is that every field stays in the key:
        # the direction this declaration is built to fail in. Required would
        # instead make every frozen historical configuration unparseable, which
        # is a replay this project cannot run rather than a fault it catches.
        volatile_evidence_keys=tuple(parameters.get(VOLATILE_EVIDENCE_KEY, ())),
        actions={
            name: _parse_action(name, value, kinds, source)
            for name, value in actions_raw.items()
        },
    )


@lru_cache(maxsize=2)
def load_repair_config(
    path: str | None = None, kinds: tuple[str, ...] = ()
) -> RepairConfig:
    """Load and validate ``configs/repair_actions.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_repair_config(raw, config_path.name, set(kinds))
