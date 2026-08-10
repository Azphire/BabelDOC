"""Declarative page type vocabulary: loading, validation and scoring.

The classification logic lives entirely in ``configs/page_types.json``. This
module only knows how to read that file, reject a malformed one, and turn a
feature vector into per-type scores. It never names a page type, so retuning
thresholds or adding a type is a JSON edit with no code change.

Loading a configuration records its SHA-256 in a run manifest under the working
directory, the same provenance mechanism prompts use.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.page_features import CONFIG_PATH as FEATURE_CONFIG_PATH
from babeldoc.magazine.page_features import PERCENTILE_SUFFIX
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import Parameter
from babeldoc.magazine.page_features import known_feature_names
from babeldoc.magazine.page_features import load_feature_config

logger = logging.getLogger(__name__)

TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "configs" / "page_types.json"

RUN_MANIFEST_NAME = "magazine_config_manifest.json"

# Comparison operators a rule may use, as name -> predicate.
OPERATORS = {
    "ge": lambda value, threshold: value >= threshold,
    "le": lambda value, threshold: value <= threshold,
    "gt": lambda value, threshold: value > threshold,
    "lt": lambda value, threshold: value < threshold,
}

# Operators that assert a page reaches a quantity rather than staying under
# one. Only a rule of this shape carrying positive weight is evidence a page
# really is of a type: an ``le``/``lt`` rule is satisfied by the absence of a
# quantity, so a page with nothing on it satisfies every one of them at once.
EVIDENCE_OPERATORS = frozenset({"ge", "gt"})

# Midrank a percentile companion lands on when its raw feature is constant
# across a document: every page ties with every other, so the rank is
# ``(0 + 0.5 * n) / n``. A feature that is zero on every page of an issue is the
# common case, and it lands here too. Positive evidence on a percentile must sit
# strictly above this value, or such a document satisfies the rule on every one
# of its pages and the positive evidence guard admits exactly what it exists to
# keep out. Definitional, not a tuning parameter: it follows from how
# ``page_features._midranks`` breaks ties and moves only if that does.
CONSTANT_COLUMN_MIDRANK = 0.5

POLICY_KEYS = frozenset({"chain_eligible", "translate", "repair_profile"})

# Policy flags a type may declare but need not. A vocabulary written before the
# flag existed still loads, and every consumer sees the declared default rather
# than a missing key, so a downstream stage never has to ask whether a policy
# carries a flag at all.
#
# The two article flags answer different questions and are declared separately.
# ``starts_article`` is the chain detector's prior: running text does not
# continue into this page. ``opens_article`` is where an article begins. They
# agree on the flowing page types and diverge on every piece of furniture, a
# contents page being somewhere text begins without being somewhere an article
# does, so one flag cannot carry both readings.
OPTIONAL_POLICY_DEFAULTS: dict[str, object] = {
    "starts_article": False,
    "opens_article": False,
}

# Optional flags whose value is a boolean, validated as such when declared.
OPTIONAL_BOOLEAN_POLICY_KEYS = frozenset({"starts_article", "opens_article"})


class TaxonomyError(ConfigError):
    """Raised when the page type vocabulary is malformed."""


@dataclass(frozen=True)
class Rule:
    feature: str
    op: str
    threshold: float
    weight: float

    def holds(self, features: dict[str, float]) -> bool:
        return OPERATORS[self.op](features[self.feature], self.threshold)


@dataclass(frozen=True)
class PageType:
    name: str
    description: str
    rules: tuple[Rule, ...]
    policy: dict[str, object]

    @property
    def total_weight(self) -> float:
        """Evidence available for this type, which is its positive weight.

        A negative rule is a penalty: it withdraws evidence a page has already
        earned rather than adding any of its own, so it stays out of the
        denominator and a type that trips none of its penalties can still
        reach 1.0.
        """
        return sum(rule.weight for rule in self.rules if rule.weight > 0)

    @property
    def evidence_rules(self) -> tuple[Rule, ...]:
        """Rules whose satisfaction is positive evidence for this type."""
        return tuple(
            rule
            for rule in self.rules
            if rule.op in EVIDENCE_OPERATORS and rule.weight > 0
        )

    def has_evidence(self, features: dict[str, float]) -> bool:
        return any(rule.holds(features) for rule in self.evidence_rules)


@dataclass(frozen=True)
class Taxonomy:
    version: str
    ambiguity_margin: float
    default_type: str
    require_positive_evidence: bool
    page_types: tuple[PageType, ...]

    def names(self) -> tuple[str, ...]:
        return tuple(page_type.name for page_type in self.page_types)

    def policy_of(self, kind: str | None) -> dict[str, object] | None:
        """Declared policy of a page kind, or None when the kind is unknown.

        A page carrying no kind, or one whose kind is not in this vocabulary,
        has no policy to consume; the caller decides what an absent policy
        means rather than getting a silent default that looks declared.
        """
        for page_type in self.page_types:
            if page_type.name == kind:
                return page_type.policy
        return None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TaxonomyError(message)


def _parse_rule(raw: object, owner: str, index: int) -> Rule:
    where = f"{owner}.rules[{index}]"
    _require(isinstance(raw, dict), f"{where}: rule must be an object")
    missing = sorted({"feature", "op", "threshold", "weight"} - set(raw))
    _require(not missing, f"{where}: missing keys {missing}")
    feature = raw["feature"]
    # Percentile companions are referenced by name like any other feature, but
    # only for the raw features the configuration selects for one.
    known = known_feature_names()
    _require(
        feature in known,
        f"{where}: unknown feature {feature!r}; known features are {list(known)}",
    )
    op = raw["op"]
    _require(
        op in OPERATORS,
        f"{where}: illegal op {op!r}; expected one of {sorted(OPERATORS)}",
    )
    threshold = raw["threshold"]
    _require(
        isinstance(threshold, int | float) and not isinstance(threshold, bool),
        f"{where}: threshold must be a number",
    )
    weight = raw["weight"]
    _require(
        isinstance(weight, int | float) and not isinstance(weight, bool),
        f"{where}: weight must be a number",
    )
    _require(weight != 0, f"{where}: weight must be non-zero")
    if (
        feature.endswith(PERCENTILE_SUFFIX)
        and op in EVIDENCE_OPERATORS
        and weight > 0
        and threshold <= CONSTANT_COLUMN_MIDRANK
    ):
        raise TaxonomyError(
            f"{where}: positive evidence on the percentile feature {feature!r} "
            f"needs a threshold above {CONSTANT_COLUMN_MIDRANK}, got {threshold}. "
            f"A raw feature that is constant across a document -- an all zero "
            f"column among them -- puts every page on the midrank "
            f"{CONSTANT_COLUMN_MIDRANK}, so a rule at or below it is satisfied by "
            f"a blank page and the positive evidence guard stops guarding."
        )
    return Rule(
        feature=feature, op=op, threshold=float(threshold), weight=float(weight)
    )


def parse_taxonomy(raw: dict, source: str) -> Taxonomy:
    """Validate a decoded page type vocabulary and build its object model."""
    _require(isinstance(raw, dict), f"{source}: root must be an object")
    for key in (
        "taxonomy_version",
        "ambiguity_margin",
        "default_type",
        "require_positive_evidence",
        "page_types",
    ):
        _require(key in raw, f"{source}: missing key {key!r}")

    require_evidence = raw["require_positive_evidence"]
    _require(
        isinstance(require_evidence, bool),
        f"{source}: require_positive_evidence must be a boolean",
    )

    margin = raw["ambiguity_margin"]
    _require(
        isinstance(margin, int | float) and not isinstance(margin, bool),
        f"{source}: ambiguity_margin must be a number",
    )
    _require(0.0 <= margin <= 1.0, f"{source}: ambiguity_margin must lie in 0..1")

    entries = raw["page_types"]
    _require(
        isinstance(entries, list) and entries,
        f"{source}: page_types must be a non-empty list",
    )

    page_types: list[PageType] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries):
        where = f"{source}.page_types[{position}]"
        _require(isinstance(entry, dict), f"{where}: entry must be an object")
        name = entry.get("name")
        _require(
            isinstance(name, str) and name, f"{where}: name must be a non-empty string"
        )
        _require(name not in seen, f"{where}: duplicate type name {name!r}")
        seen.add(name)

        description = entry.get("description")
        _require(
            isinstance(description, str) and description,
            f"{where}: description must be a non-empty string",
        )

        rules_raw = entry.get("rules")
        _require(
            isinstance(rules_raw, list) and rules_raw,
            f"{where}: rules must be a non-empty list",
        )
        rules = tuple(
            _parse_rule(rule, f"{source}.{name}", index)
            for index, rule in enumerate(rules_raw)
        )
        _require(
            sum(rule.weight for rule in rules if rule.weight > 0) > 0,
            f"{where}: needs positive weight to score against, "
            f"a type made only of penalties can never be reached",
        )
        _require(
            any(rule.op in EVIDENCE_OPERATORS and rule.weight > 0 for rule in rules),
            f"{where}: needs at least one positive weight rule using one of "
            f"{sorted(EVIDENCE_OPERATORS)}, otherwise the type is reachable only "
            f"by what a page lacks and an empty page would score against it",
        )

        policy = entry.get("policy")
        _require(isinstance(policy, dict), f"{where}: policy must be an object")
        missing = sorted(POLICY_KEYS - set(policy))
        _require(not missing, f"{where}: policy missing keys {missing}")
        unknown = sorted(set(policy) - POLICY_KEYS - set(OPTIONAL_POLICY_DEFAULTS))
        _require(not unknown, f"{where}: policy has unknown keys {unknown}")
        for flag in ("chain_eligible", "translate"):
            _require(
                isinstance(policy[flag], bool),
                f"{where}: policy.{flag} must be a boolean",
            )
        for flag in sorted(OPTIONAL_BOOLEAN_POLICY_KEYS & set(policy)):
            _require(
                isinstance(policy[flag], bool),
                f"{where}: policy.{flag} must be a boolean",
            )
        _require(
            isinstance(policy["repair_profile"], str) and policy["repair_profile"],
            f"{where}: policy.repair_profile must be a non-empty string",
        )

        page_types.append(
            PageType(
                name=name,
                description=description,
                rules=rules,
                policy=OPTIONAL_POLICY_DEFAULTS | dict(policy),
            )
        )

    default_type = raw["default_type"]
    _require(
        default_type in seen,
        f"{source}: default_type {default_type!r} is not a declared page type",
    )
    return Taxonomy(
        version=str(raw["taxonomy_version"]),
        ambiguity_margin=float(margin),
        default_type=default_type,
        require_positive_evidence=require_evidence,
        page_types=tuple(page_types),
    )


@lru_cache(maxsize=1)
def load_taxonomy(path: str | None = None) -> Taxonomy:
    """Load and validate ``configs/page_types.json``."""
    taxonomy_path = TAXONOMY_PATH if path is None else Path(path)
    with taxonomy_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_taxonomy(raw, taxonomy_path.name)


def load_configs() -> tuple[dict[str, Parameter], Taxonomy]:
    """Load both magazine classification configurations, validating each."""
    return load_feature_config(), load_taxonomy()


def score_page_types(
    features: dict[str, float], taxonomy: Taxonomy
) -> dict[str, float]:
    """Score every page type as satisfied weight over available weight.

    Satisfied weight is the algebraic sum, so a tripped penalty subtracts. The
    result is clamped to 0..1: a page that trips enough penalties is simply not
    of that type, and there is nothing to gain from ranking how badly.

    With ``require_positive_evidence`` set, a type scores 0 on a page that
    satisfies none of its evidence rules. Without that guard a page carrying
    nothing at all sweeps every ``le``/``lt`` rule in the vocabulary and can
    reach a high score on types it shows no sign of being.
    """
    scores: dict[str, float] = {}
    for page_type in taxonomy.page_types:
        total = page_type.total_weight
        if total <= 0:
            scores[page_type.name] = 0.0
            continue
        if taxonomy.require_positive_evidence and not page_type.has_evidence(features):
            scores[page_type.name] = 0.0
            continue
        satisfied = sum(rule.weight for rule in page_type.rules if rule.holds(features))
        scores[page_type.name] = min(1.0, max(0.0, satisfied / total))
    return scores


@dataclass(frozen=True)
class Verdict:
    kind: str
    confidence: float
    ambiguous: bool
    scores: dict[str, float]


def classify(features: dict[str, float], taxonomy: Taxonomy) -> Verdict:
    """Pick the highest scoring page type.

    Ties and near ties keep the top candidate but mark the page ambiguous, so a
    later batch can route those pages to a stronger judge. When nothing scores
    at all the declared default type is used.
    """
    scores = score_page_types(features, taxonomy)
    declared_order = {name: index for index, name in enumerate(taxonomy.names())}
    ranked = sorted(
        declared_order,
        key=lambda name: (-scores[name], declared_order[name]),
    )
    top = ranked[0]
    top_score = scores[top]
    runner_up = scores[ranked[1]] if len(ranked) > 1 else 0.0
    ambiguous = (top_score - runner_up) < taxonomy.ambiguity_margin
    kind = taxonomy.default_type if top_score <= 0.0 else top
    return Verdict(kind=kind, confidence=top_score, ambiguous=ambiguous, scores=scores)


def vocabulary_block(taxonomy: Taxonomy) -> str:
    """The vocabulary as one name and description per line, for prompt injection.

    Rules, thresholds and policy stay out. A judge told which downstream flags a
    name carries is being invited to answer with the consequence it prefers
    rather than with what the page in front of it is, and the numbers are the
    deterministic layer's own workings, not evidence about the page.
    """
    return "\n".join(
        f"- {page_type.name}: {page_type.description}"
        for page_type in taxonomy.page_types
    )


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_config_manifest(working_dir: Path | str, paths: list[Path]) -> Path:
    """Write the SHA-256 of every loaded configuration into the working dir.

    Minimal provenance record; a later batch merges it with the prompt manifest.
    """
    manifest_path = Path(working_dir) / RUN_MANIFEST_NAME
    existing: dict[str, str] = {}
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as f:
            existing = json.load(f)
    for path in paths:
        existing[path.name] = file_digest(path)
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, sort_keys=True)
    return manifest_path


DEFAULT_CONFIG_PATHS = (FEATURE_CONFIG_PATH, TAXONOMY_PATH)
