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
is what makes the policy a switch rather than a third behaviour: an empty slot
is the run that existed before this module, byte for byte, while a slot holding
a politely worded instruction to change nothing is a different run that happens
to be aiming at the same output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from babeldoc.magazine.page_features import ConfigError

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "translation_style.json"

# The policy selector and the closed vocabulary it is checked against.
POLICY_KEY = "person_names"
VOCABULARY_KEY = "person_names_vocabulary"

# Where the role texts live, and the key holding the texts themselves.
NOTES_KEY = "style_note_by_target"
ENTRIES_KEY = "entries"

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
    """The declared policy, and the role text each target language states it in."""

    person_names: str
    notes: Mapping[str, str]
    languages: frozenset[str]

    @property
    def states_an_instruction(self) -> bool:
        return self.person_names != POLICY_KEEP_SOURCE

    def note_for(self, target_lang: str) -> str:
        """The role text for one target language, by longest declared prefix.

        Matched by prefix rather than by equality because a target language
        reaches this project as a tag and a tag carries a region: the rule for
        a language is the rule for every variety of it. A tag no entry claims
        raises, since a naming rule stated for the wrong language is worse than
        no naming rule at all.
        """
        tag = (target_lang or "").strip().lower()
        claimed = [key for key in self.notes if tag.startswith(key.lower())]
        if not claimed:
            raise TranslationStyleError(
                f"{CONFIG_PATH.name}: {NOTES_KEY} declares no entry for target "
                f"language {target_lang!r}; declared are {sorted(self.notes)}"
            )
        return self.notes[max(claimed, key=len)]


def _read_notes(raw: object, source: str) -> Mapping[str, str]:
    if not isinstance(raw, dict):
        raise TranslationStyleError(f"{source}: {NOTES_KEY} must be an object")
    entries = raw.get(ENTRIES_KEY)
    if not isinstance(entries, dict) or not entries:
        raise TranslationStyleError(
            f"{source}: {NOTES_KEY}.{ENTRIES_KEY} must be a non-empty object"
        )
    for key, value in entries.items():
        if not isinstance(key, str) or not key.strip():
            raise TranslationStyleError(
                f"{source}: {NOTES_KEY}.{ENTRIES_KEY} has a key that is not a "
                f"language tag: {key!r}"
            )
        if not isinstance(value, str) or not value.strip():
            raise TranslationStyleError(
                f"{source}: {NOTES_KEY}.{ENTRIES_KEY}[{key!r}] must be a "
                f"non-empty string"
            )
    return MappingProxyType({key: value.strip() for key, value in entries.items()})


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


def _read_policy(raw: dict, source: str) -> str:
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
        - {POLICY_KEY, VOCABULARY_KEY, NOTES_KEY, LANGUAGES_KEY, DESCRIPTION_KEY}
    )
    if unknown:
        raise TranslationStyleError(f"{config_path.name}: unknown key(s) {unknown}")
    return StylePolicy(
        person_names=_read_policy(raw, config_path.name),
        notes=_read_notes(raw.get(NOTES_KEY), config_path.name),
        languages=_read_languages(raw.get(LANGUAGES_KEY), config_path.name),
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
