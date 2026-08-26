"""The standing instruction a run's translation requests carry.

An article brief describes one article and travels with the batches of that
article. This is the other half of the same problem and needs the opposite
shape: a rule about how the whole document is rendered, which has to reach a
request whether or not that request belongs to an article at all.

The batches an article brief cannot reach are not an edge case. A page the
grouping walk leaves unassigned -- a contents page above all -- carries no
brief, a cross page pair whose halves belong to two articles carries none, an
article whose brief request was refused carries none, and a paragraph retried
alone after its batch failed is built by ``ILTranslator`` rather than by
``ILTranslatorLLMOnly`` and has no brief parameter to be given one through.
Those are exactly the places the F1 review found personal names surviving in
their source script.

So the instruction travels by the one slot all three prompt builders read:
``TranslationConfig.custom_system_prompt``, which
``ILTranslatorLLMOnly._build_llm_prompt`` reads for the page and chain paths
and ``ILTranslator._build_role_block`` reads for the fallback path. Nothing
upstream changes, and there is no request left for the rule to miss.

Two properties of that slot shape what is done with it. It replaces the role
block rather than adding to it, which is why the configuration declares whole
role texts rather than one appended sentence; and it may already hold a
caller's own system prompt, which is stated first and kept rather than
overruled.

Under ``keep_source`` the slot is not written at all. That is deliberate and it
is what makes the policy a switch rather than a further behaviour: an empty slot
is the run that existed before this module, byte for byte, while a slot holding
a politely worded instruction to change nothing is a different run that happens
to be aiming at the same output.

What a policy is
----------------

There is more than one defensible answer to what a magazine should do with a
personal name, and which one is right is a house style decision rather than a
technical one. So the configuration declares a matrix -- one whole role text per
policy per target language -- and the run selects a row of it. ``translate``
renders the name and says nothing further; ``keep`` leaves it in its source
form; ``annotate`` renders it and puts the source form after it once, between a
bracket pair the configuration declares. ``transliterate`` is the selected
default and its two texts are frozen, so that a run made now is comparable with
every run made since the policy existed.

Every text ends by stating that a glossary table outranks it, ``keep`` included.
A ruled name is a decision a person took about one name, and a policy is a
default about all of them; a default that could overrule a ruling would make the
ruling loop pointless, and the model is the only thing in a position to honour
that ordering, so it is written where the model reads it.

Each text is pinned by the digest of its bytes and the loader refuses a text
whose digest has moved. Freezing a text is otherwise only a claim.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("translation_style.json")

# The policy selector and the closed vocabulary it is checked against.
POLICY_KEY = "person_names"
VOCABULARY_KEY = "person_names_vocabulary"

# The matrix of role texts, policy by target language, and the digest of every
# one of them. The two are separate keys rather than one nested structure so
# that a text and its pin cannot be edited in one motion without noticing.
POLICIES_KEY = "person_names_policies"
PINS_KEY = "person_names_policy_sha256"

# The bracket pair the annotate texts name, per target language. Read here so
# that a check on the annotation's shape reads the same declaration the model
# is instructed from rather than a second copy of it.
BRACKETS_KEY = "annotation_brackets"

# The closed vocabulary of language tags a corpus entry may name a direction
# with. Declared beside the role texts rather than in the corpus module: a
# language tag is a declaration, and the rule against writing one into code
# holds for the module that validates the registry as much as for any other.
LANGUAGES_KEY = "languages"

# Prose keys a reader is meant to see and a loader is meant to skip.
DESCRIPTION_KEY = "description"

# The one policy value that states nothing. Named here because the absence of
# an instruction is a behaviour this module implements, not an omission.
POLICY_KEEP_SOURCE = "keep_source"

# What separates a caller's own system prompt from the declared role text.
SECTION_SEPARATOR = "\n\n"


class TranslationStyleError(ConfigError):
    """Raised when the translation style configuration is unusable."""


@dataclass(frozen=True)
class StylePolicy:
    """The declared policy, and the role text every policy states in each language.

    The whole matrix is carried rather than the selected row alone, so that a
    caller comparing what two policies would send -- the gate above all -- reads
    the same loaded, validated and pinned object a run reads, instead of a
    second parse of the same file.
    """

    person_names: str
    policies: Mapping[str, Mapping[str, str]]
    languages: frozenset[str]
    annotation_brackets: Mapping[str, tuple[str, str]]

    @property
    def states_an_instruction(self) -> bool:
        return self.person_names != POLICY_KEEP_SOURCE

    @property
    def notes(self) -> Mapping[str, str]:
        """The selected policy's texts, by target language tag."""
        return self.policies.get(self.person_names, MappingProxyType({}))

    def _match(self, texts: Mapping[str, str], target_lang: str, where: str) -> str:
        """One text out of a language keyed table, by longest declared prefix.

        Matched by prefix rather than by equality because a target language
        reaches this project as a tag and a tag carries a region: the rule for
        a language is the rule for every variety of it. A tag no entry claims
        raises, since a naming rule stated for the wrong language is worse than
        no naming rule at all.
        """
        tag = (target_lang or "").strip().lower()
        claimed = [key for key in texts if tag.startswith(key.lower())]
        if not claimed:
            raise TranslationStyleError(
                f"{CONFIG_PATH.name}: {where} declares no entry for target "
                f"language {target_lang!r}; declared are {sorted(texts)}"
            )
        return texts[max(claimed, key=len)]

    def note_for(self, target_lang: str) -> str:
        """The role text the selected policy states for one target language."""
        return self._match(
            self.notes, target_lang, f"{POLICIES_KEY}.{self.person_names}"
        )

    def note_for_policy(self, policy: str, target_lang: str) -> str:
        """The role text one named policy states for one target language.

        Raises for ``keep_source``, which states nothing: asking what text it
        would send is asking a question with no answer, and answering it with
        the empty string would let a caller send one.
        """
        texts = self.policies.get(policy)
        if texts is None:
            raise TranslationStyleError(
                f"{CONFIG_PATH.name}: {POLICIES_KEY} declares no policy "
                f"{policy!r}; declared are {sorted(self.policies)}"
            )
        return self._match(texts, target_lang, f"{POLICIES_KEY}.{policy}")

    def brackets_for(self, target_lang: str) -> tuple[str, str]:
        """The opener and closer an annotation is written between."""
        tag = (target_lang or "").strip().lower()
        claimed = [
            key for key in self.annotation_brackets if tag.startswith(key.lower())
        ]
        if not claimed:
            raise TranslationStyleError(
                f"{CONFIG_PATH.name}: {BRACKETS_KEY} declares no pair for target "
                f"language {target_lang!r}; declared are "
                f"{sorted(self.annotation_brackets)}"
            )
        return self.annotation_brackets[max(claimed, key=len)]


def _read_texts(raw: object, source: str, where: str) -> Mapping[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise TranslationStyleError(f"{source}: {where} must be a non-empty object")
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise TranslationStyleError(
                f"{source}: {where} has a key that is not a language tag: {key!r}"
            )
        if not isinstance(value, str) or not value.strip():
            raise TranslationStyleError(
                f"{source}: {where}[{key!r}] must be a non-empty string"
            )
    return MappingProxyType({key: value.strip() for key, value in raw.items()})


def _read_policies(
    raw: object,
    pins: object,
    vocabulary: list[str],
    languages: frozenset[str],
    source: str,
) -> Mapping[str, Mapping[str, str]]:
    """The matrix, checked against its vocabulary, its languages and its pins.

    Three things are checked and each of them is a way the matrix could be
    wrong without the run that reads it noticing. A policy the vocabulary offers
    and the matrix does not hold is a switch position with nothing behind it. A
    policy that claims fewer languages than the corpus may be written in is a
    direction that cannot be run under it. And a text whose digest is not the
    one declared beside it is an edit nobody wrote down, which is the case the
    pins exist for: a frozen text is only frozen if something refuses to load it
    changed.
    """
    if not isinstance(raw, dict) or not raw:
        raise TranslationStyleError(
            f"{source}: {POLICIES_KEY} must be a non-empty object"
        )
    if not isinstance(pins, dict) or not pins:
        raise TranslationStyleError(f"{source}: {PINS_KEY} must be a non-empty object")

    stated = [name for name in vocabulary if name != POLICY_KEEP_SOURCE]
    missing = sorted(set(stated) - set(raw))
    if missing:
        raise TranslationStyleError(
            f"{source}: {VOCABULARY_KEY} offers {missing} and {POLICIES_KEY} "
            f"holds no text for them"
        )
    extra = sorted(set(raw) - set(stated))
    if extra:
        raise TranslationStyleError(
            f"{source}: {POLICIES_KEY} holds {extra}, which {VOCABULARY_KEY} "
            f"does not offer"
        )
    if sorted(pins) != sorted(raw):
        raise TranslationStyleError(
            f"{source}: {PINS_KEY} pins {sorted(pins)} and {POLICIES_KEY} "
            f"declares {sorted(raw)}"
        )

    matrix = {}
    for name in sorted(raw):
        texts = _read_texts(raw[name], source, f"{POLICIES_KEY}.{name}")
        unclaimed = sorted(languages - set(texts))
        if unclaimed:
            raise TranslationStyleError(
                f"{source}: {POLICIES_KEY}.{name} states nothing for "
                f"{unclaimed}, which {LANGUAGES_KEY} declares"
            )
        declared = pins[name]
        if not isinstance(declared, dict) or sorted(declared) != sorted(texts):
            raise TranslationStyleError(
                f"{source}: {PINS_KEY}.{name} pins "
                f"{sorted(declared) if isinstance(declared, dict) else declared} "
                f"and {POLICIES_KEY}.{name} declares {sorted(texts)}"
            )
        for tag, text in texts.items():
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if declared[tag] != digest:
                raise TranslationStyleError(
                    f"{source}: {POLICIES_KEY}.{name}.{tag} hashes to {digest} "
                    f"and {PINS_KEY} declares {declared[tag]!r}"
                )
        matrix[name] = texts
    return MappingProxyType(matrix)


def _read_brackets(raw: object, source: str) -> Mapping[str, tuple[str, str]]:
    if not isinstance(raw, dict) or not raw:
        raise TranslationStyleError(
            f"{source}: {BRACKETS_KEY} must be a non-empty object"
        )
    pairs = {}
    for key, value in raw.items():
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(not isinstance(item, str) or not item for item in value)
        ):
            raise TranslationStyleError(
                f"{source}: {BRACKETS_KEY}[{key!r}] must be an opener and a closer"
            )
        pairs[key] = (value[0], value[1])
    return MappingProxyType(pairs)


def _read_languages(raw: object, source: str) -> frozenset[str]:
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(item, str) or not item.strip() for item in raw)
    ):
        raise TranslationStyleError(
            f"{source}: {LANGUAGES_KEY} must list at least one non-empty language tag"
        )
    return frozenset(tag.strip() for tag in raw)


def _read_vocabulary(raw: dict, source: str) -> list[str]:
    vocabulary = raw.get(VOCABULARY_KEY)
    if (
        not isinstance(vocabulary, list)
        or not vocabulary
        or any(not isinstance(item, str) or not item for item in vocabulary)
    ):
        raise TranslationStyleError(
            f"{source}: {VOCABULARY_KEY} must list at least one non-empty string"
        )
    if POLICY_KEEP_SOURCE not in vocabulary:
        raise TranslationStyleError(
            f"{source}: {VOCABULARY_KEY} must declare {POLICY_KEEP_SOURCE!r}, "
            f"which is the value that leaves the prompts as they were"
        )
    return list(vocabulary)


def _read_policy(raw: dict, vocabulary: list[str], source: str) -> str:
    selected = raw.get(POLICY_KEY)
    if selected not in vocabulary:
        raise TranslationStyleError(
            f"{source}: {POLICY_KEY}={selected!r} is outside {sorted(vocabulary)}"
        )
    return selected


@lru_cache(maxsize=1)
def load_style_config(path: str | None = None) -> StylePolicy:
    """Load and validate ``configs/translation_style.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise TranslationStyleError(f"{config_path.name}: root must be an object")
    unknown = sorted(
        set(raw)
        - {
            POLICY_KEY,
            VOCABULARY_KEY,
            POLICIES_KEY,
            PINS_KEY,
            BRACKETS_KEY,
            LANGUAGES_KEY,
            DESCRIPTION_KEY,
        }
    )
    if unknown:
        raise TranslationStyleError(f"{config_path.name}: unknown key(s) {unknown}")
    vocabulary = _read_vocabulary(raw, config_path.name)
    languages = _read_languages(raw.get(LANGUAGES_KEY), config_path.name)
    return StylePolicy(
        person_names=_read_policy(raw, vocabulary, config_path.name),
        policies=_read_policies(
            raw.get(POLICIES_KEY),
            raw.get(PINS_KEY),
            vocabulary,
            languages,
            config_path.name,
        ),
        languages=languages,
        annotation_brackets=_read_brackets(raw.get(BRACKETS_KEY), config_path.name),
    )


def system_prompt(
    target_lang: str,
    existing: str | None = None,
    policy: StylePolicy | None = None,
) -> str | None:
    """The system prompt a run is to carry, or None to leave the slot alone.

    None is not an error and not an empty string: it says this run states no
    standing instruction, so whatever the slot held stays exactly as it was.
    """
    policy = load_style_config() if policy is None else policy
    if not policy.states_an_instruction:
        return None
    note = policy.note_for(target_lang)
    carried = (existing or "").strip()
    # A caller's own system prompt is kept and stated first: a run that already
    # had a voice gains the naming rule rather than trading one for the other.
    return note if not carried else carried + SECTION_SEPARATOR + note


def apply(
    translation_config,
    target_lang: str,
    policy: StylePolicy | None = None,
) -> str | None:
    """Put the standing instruction where every prompt builder reads it.

    Returns what was written, or None where nothing was: a caller recording
    what its run carried records the same value either way.
    """
    composed = system_prompt(
        target_lang,
        getattr(translation_config, "custom_system_prompt", None),
        policy,
    )
    if composed is not None:
        translation_config.custom_system_prompt = composed
    return composed
