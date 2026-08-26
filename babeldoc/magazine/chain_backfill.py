"""Chain level joint translation: merge a chain, cut the translation back up.

A chain is a semantic unit the page break happens to have split. Translating
its members one by one is what puts a broken sentence in front of the engine
twice, so the members are merged into one source text, translated whole, and
the translation is cut back into one piece per member. This module is the pure
half of that: strings in, strings out, no intermediate language and no pipeline.

Three functions carry it. :func:`merge_chain_text` puts the members together
and records how, :func:`split_sentences` finds the sentence ends of a target
language text, and :func:`redistribute` decides where the translation is cut.
:func:`verify_redistribution` states the conservation law the whole thing is
answerable to: the pieces join back to exactly the translation that came in,
their spans tile it once with no overlap and no gap, and every member gets a
non-empty piece.

Three redistributions exist because the kinds of chain differ in what a cut
should respect. Running text is one paragraph the layout broke, so its
continuation should resume where the first box ran out of room: the cut is
placed at that box's capacity, made legal by the target language's break rule
and pulled back off any mark a line may not open with. A broken display line
has no such structure -- it is one line of type the layout snapped -- so it is
cut by share throughout and claims no sentence indices. The sentence greedy cut
that running text used to take remains, and is what a capacity cut falls back
to where the caller could measure no box. Which one a chain takes is read from
the endpoint pair class it was built under, through the declaration in
``configs/chain_translation.json``; nothing here names a page type or a
publication, and every character class, threshold and separator it compares
against comes from that file.

Which kind of boundary broke the chain does not enter into it. A body paragraph
interrupted by a column edge and one interrupted by a page edge are the same
paragraph interrupted, and a cut that answered to the edge rather than to the
text would be answering the wrong question.

Sentence splitting is a model, not a parser, and its failure modes are known
and bounded. Three guards narrow them. A terminator that carries no whitespace
after it does not end a sentence, which is what keeps decimals, version
numbers and in-word full stops whole. A boundary that closes on an abbreviation
the profile declares is dropped however the whitespace falls, which is what
keeps the abbreviations a magazine actually writes from ending a sentence in
the middle of one. A boundary that would close a sentence shorter than the
profile's minimum is dropped as well, which absorbs an initial standing at the
head of a sentence. What none of them catches is an abbreviation nobody
declared. Over-splitting only offers a cut position that need not be taken, and
under-splitting only withholds one; neither can violate the conservation law,
because every cut is a position in the translated string and no branch here
adds or removes a character from it.
"""

from __future__ import annotations

import bisect
import json
import math
import unicodedata
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "chain_translation.json"

# Sections of the configuration that are not flat bounded parameters and are
# parsed here rather than by validate_bounded_config.
JOIN_KEY = "join"
PROFILES_KEY = "profiles"
STRATEGIES_KEY = "strategies"
CAPACITY_KEY = "capacity"
LINE_HEAD_KEY = "line_head_forbidden_punctuation"
LINE_TAIL_KEY = "line_tail_forbidden_punctuation"

# The run attribute the alignment level is read from. A name rather than a
# value: the switch itself lives on the run, and this says which one it is.
ALIGN_SWITCH_KEY = "cut_align_switch"
NESTED_KEYS = (
    JOIN_KEY,
    PROFILES_KEY,
    STRATEGIES_KEY,
    CAPACITY_KEY,
    LINE_HEAD_KEY,
    f"{LINE_HEAD_KEY}_description",
    LINE_TAIL_KEY,
    f"{LINE_TAIL_KEY}_description",
    ALIGN_SWITCH_KEY,
)

ENTRIES_KEY = "entries"
DEFAULT_KEY = "default"
BY_PAIR_CLASS_KEY = "by_pair_class"
DESCRIPTION_KEY = "description"

# The per-profile override and the flat range that bounds it, by the same
# convention chain_signals uses for a weight declared inside a pairing: the
# bound is written down once, beside the default the override replaces.
SENTENCE_MIN_CHARS_KEY = "sentence_min_chars"
RANGE_SUFFIX = "_allowed_range"

REQUIRED_PARAMETERS: frozenset[str] = frozenset(
    {
        SENTENCE_MIN_CHARS_KEY,
        "snap_search_ratio",
        "snap_search_min_chars",
        "cut_snap_radius",
        "output_token_budget",
        "output_token_ratio",
        "slot_min_font_size",
        "slot_fit_tolerance",
    }
)

# The redistributions this module implements. A strategy named by the
# configuration has to be one of them.
STRATEGY_SENTENCE_GREEDY = "sentence_greedy"
STRATEGY_PROPORTIONAL = "proportional"
STRATEGY_CAPACITY = "capacity"
STRATEGIES = (STRATEGY_SENTENCE_GREEDY, STRATEGY_PROPORTIONAL, STRATEGY_CAPACITY)

# Where a proportional cut may land. A break rule named by a profile has to be
# one of them.
BREAK_WORD_BOUNDARY = "word_boundary"
BREAK_ANY_CHAR = "any_char"
BREAK_RULES = (BREAK_WORD_BOUNDARY, BREAK_ANY_CHAR)

# How one cut was placed, recorded per cut.
CUT_SENTENCE = "sentence"
CUT_PROPORTIONAL = "proportional"
CUT_CAPACITY = "capacity"

# Recorded on a capacity cut that was pulled back off a mark no line may open
# with. The move is towards the start of the text, by the least it takes.
MOVED_OFF_LINE_HEAD = "line_head_punctuation"

# How far back a capacity cut may be pulled to keep the continuation from
# opening on a forbidden mark. One position is the whole of the intended move;
# the rest of the allowance covers a run of such marks, which a closing bracket
# after a full stop is. Past it the cut stands where it was and the sidecar
# says so, because walking backwards without limit would trade a punctuation
# defect for an arbitrary one.
_LINE_HEAD_RETREAT_LIMIT = 4

# Reported by a sentence redistribution that had to place at least one cut by
# share because no sentence boundary was left for it.
FALLBACK_PROPORTIONAL = "proportional"

# Reported by a capacity redistribution the caller could measure no box for. The
# cut is then placed by the share cascade, which is the answer the strategy
# before this one gave, and saying so is what keeps a capacity cut that was
# never measured from reading like one that was.
FALLBACK_NO_CAPACITY = "no_capacity"

# Recorded in place of a sentence index by a redistribution that claims no
# sentence structure.
NO_SENTENCE_INDEX = -1

# A cut immediately after a joiner would break the sequence it joins.
_ZERO_WIDTH_JOINER = "\u200d"

# The abbreviations a profile exempts from ending a sentence. Optional, because
# a script that writes no abbreviation with a terminator in it declares none.
NON_TERMINAL_PREFIXES_KEY = "non_terminal_prefixes"

# The closed class words a cut may be moved to stand after. Declared per
# profile, beside the break rule it refines, so one language resolution
# serves both. A profile declaring none takes no such move.
CUT_BOUNDARY_MARKERS_KEY = "cut_boundary_markers"

# Keys a profile declares. sentence_min_chars and the abbreviation table are the
# optional entries.
_PROFILE_REQUIRED = (
    "language_prefixes",
    "terminators",
    "space_gated_terminators",
    "closers",
    "break_rule",
)
_PROFILE_OPTIONAL = (
    SENTENCE_MIN_CHARS_KEY,
    NON_TERMINAL_PREFIXES_KEY,
    CUT_BOUNDARY_MARKERS_KEY,
)

# Separator a language tag puts before its region or script subtag.
_SUBTAG_SEPARATOR = "-"
_SUBTAG_ALIASES = ("_",)

# Separator a code point range is written with in the configuration.
_RANGE_SEPARATOR = ".."


class BackfillConfigError(ConfigError):
    """Raised when the chain translation configuration is malformed."""


class ChainBackfillError(ValueError):
    """Raised when a chain cannot be merged or a translation cannot be cut."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackfillConfigError(message)


@dataclass(frozen=True)
class LanguageProfile:
    """What a sentence end looks like in one target language, and where to cut.

    ``terminators`` end a sentence wherever they stand and
    ``space_gated_terminators`` only when whitespace or the end of the text
    follows. ``all_terminators`` is the union, held separately because the scan
    reads it once per character.
    """

    name: str
    language_prefixes: tuple[str, ...]
    terminators: frozenset[str]
    space_gated_terminators: frozenset[str]
    all_terminators: frozenset[str]
    closers: frozenset[str]
    non_terminal_prefixes: tuple[str, ...]
    break_rule: str
    sentence_min_chars: int
    cut_boundary_markers: tuple[str, ...]


@dataclass(frozen=True)
class JoinRules:
    """How two consecutive members are put back together."""

    default_separator: str
    spaceless_separator: str
    hyphen_separator: str
    drop_trailing_hyphen: bool
    trailing_hyphens: frozenset[str]
    spaceless_ranges: tuple[tuple[int, int], ...]

    def is_spaceless(self, char: str) -> bool:
        return any(low <= ord(char) <= high for low, high in self.spaceless_ranges)


@dataclass(frozen=True)
class CapacityGrid:
    """How many characters of a target language one box is estimated to hold.

    Two numbers per script rather than one per language: the advance of a
    character and the advance between baselines are both multiples of the font
    size, and which pair a language takes is the one question a tag has to
    answer.
    """

    line_skip_cjk: float
    line_skip_latin: float
    advance_ratio_cjk: float
    advance_ratio_latin: float
    cjk_target_prefixes: tuple[str, ...]

    def is_cjk_target(self, language: str | None) -> bool:
        tag = (language or "").strip().lower()
        return any(tag.startswith(prefix) for prefix in self.cjk_target_prefixes)

    def characters_in(
        self, width: float, height: float, font_size: float, language: str | None
    ) -> int:
        """The capacity of one box, as a whole number of characters.

        Zero where the box holds no whole line or the font size is not a
        positive number, which a caller reads as "not measurable" rather than
        as "empty": a capacity of zero is not a cut position.
        """
        if not (font_size and font_size > 0 and width > 0 and height > 0):
            return 0
        cjk = self.is_cjk_target(language)
        skip = self.line_skip_cjk if cjk else self.line_skip_latin
        advance = self.advance_ratio_cjk if cjk else self.advance_ratio_latin
        lines = int(height // (font_size * skip))
        per_line = int(width // (font_size * advance))
        if lines < 1 or per_line < 1:
            return 0
        return lines * per_line

    def lines_in(self, height: float, font_size: float, language: str | None) -> int:
        """How many lines the box was estimated to hold, for the record."""
        if not (font_size and font_size > 0 and height > 0):
            return 0
        skip = self.line_skip_cjk if self.is_cjk_target(language) else (
            self.line_skip_latin
        )
        return int(height // (font_size * skip))


@dataclass(frozen=True)
class BackfillConfig:
    """The whole of ``configs/chain_translation.json``, parsed and checked."""

    sentence_min_chars: int
    snap_search_ratio: float
    snap_search_min_chars: int
    cut_snap_radius: int
    output_token_budget: int
    output_token_ratio: float
    align_switch: str
    join: JoinRules
    profiles: Mapping[str, LanguageProfile]
    default_profile: str
    strategy_by_pair_class: Mapping[str, str]
    default_strategy: str
    capacity: CapacityGrid
    line_head_forbidden: frozenset
    line_tail_forbidden: frozenset
    slot_min_font_size: float
    slot_fit_tolerance: float


@dataclass(frozen=True)
class ChainMerge:
    """One chain merged into a single source text.

    ``members`` are the member texts as they entered ``text``, which differs
    from what was handed in only by the one page break hyphen a merge may drop.
    ``separators`` holds what was put in front of each member, empty for the
    first, so the merge can be read back from the record alone.
    """

    text: str
    members: tuple[str, ...]
    separators: tuple[str, ...]
    spans: tuple[tuple[int, int], ...]
    dropped_hyphens: tuple[int, ...]

    @property
    def shares(self) -> tuple[float, ...]:
        """Each member's share of the merged source, which sizes its piece."""
        total = sum(len(member) for member in self.members)
        return tuple(len(member) / total for member in self.members)

    def as_record(self) -> dict:
        return {
            "member_count": len(self.members),
            "chars": len(self.text),
            "member_chars": [len(member) for member in self.members],
            "separators": list(self.separators),
            "dropped_hyphens": list(self.dropped_hyphens),
        }


@dataclass(frozen=True)
class Cut:
    """One cut between member ``index`` and member ``index + 1``."""

    index: int
    position: int
    mode: str
    snapped: bool
    estimate: int | None = None
    moved_to: str | None = None

    def as_record(self) -> dict:
        return {
            "index": self.index,
            "position": self.position,
            "mode": self.mode,
            "snapped": self.snapped,
            "estimate": self.estimate,
            "moved_to": self.moved_to,
        }


@dataclass(frozen=True)
class MemberSegment:
    """The piece of the translation one member receives.

    ``sentence_start`` and ``sentence_end`` are a half-open range over the
    sentences of the translation, or the no-index marker when the
    redistribution claims no sentence structure. The range is empty where a
    member both starts and ends inside one sentence, which is what a
    proportional cut inside a body chain produces: the sentence is attributed
    to whichever member finishes it.
    """

    index: int
    text: str
    start: int
    end: int
    sentence_start: int
    sentence_end: int

    def as_record(self) -> dict:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "chars": len(self.text),
            "sentence_start": self.sentence_start,
            "sentence_end": self.sentence_end,
        }


@dataclass(frozen=True)
class Alignment:
    """What the alignment level measured, and whether the cut was placed by it.

    ``member_lengths`` are the lengths of each member's own translation. The
    texts those lengths were taken from are deliberately absent: a chain's
    output comes from the joint translation and from nothing else, and a record
    that carried the auxiliary text would be an invitation to build output from
    it. ``source_shares`` is what the third level would have used, kept so that
    the two placements can be compared without translating anything again.
    """

    used: bool
    reason: str | None
    member_lengths: tuple[int, ...]
    source_shares: tuple[float, ...]

    def as_record(self) -> dict:
        return {
            "used": self.used,
            "reason": self.reason,
            "member_lengths": list(self.member_lengths),
            "source_shares": [round(share, 6) for share in self.source_shares],
        }


# What an alignment records when it was not used, one reason per way of not
# being used. Declared rather than written at each site so that a reader of a
# sidecar meets a closed set.
ALIGN_SWITCH_DOWN = "switch_down"
ALIGN_NOT_OFFERED = "not_offered"
ALIGN_UNUSABLE = "unusable_lengths"
ALIGN_REASONS = (ALIGN_SWITCH_DOWN, ALIGN_NOT_OFFERED, ALIGN_UNUSABLE)

# How a cut came to stand where it does, beyond the share that proposed it.
MOVED_TO_PUNCTUATION = "punctuation"
MOVED_TO_MARKER = "marker"


@dataclass(frozen=True)
class Redistribution:
    """A translation cut back into one piece per chain member."""

    strategy: str
    profile: str
    segments: tuple[MemberSegment, ...]
    sentences: tuple[str, ...]
    cuts: tuple[Cut, ...]
    fallback: str | None
    alignment: Alignment | None = None
    capacities: tuple[int, ...] = ()

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(segment.text for segment in self.segments)

    def as_record(self) -> dict:
        return {
            "strategy": self.strategy,
            "profile": self.profile,
            "fallback": self.fallback,
            "sentence_count": len(self.sentences),
            "members": [segment.as_record() for segment in self.segments],
            "cuts": [cut.as_record() for cut in self.cuts],
            "alignment": None if self.alignment is None else self.alignment.as_record(),
            "capacities": list(self.capacities),
        }


@dataclass(frozen=True)
class ConservationReport:
    """The conservation law's verdict on one redistribution."""

    ok: bool
    violations: tuple[str, ...]

    def as_record(self) -> dict:
        return {"ok": self.ok, "violations": list(self.violations)}


# --- configuration ----------------------------------------------------------


def _parse_char_set(
    raw: object, where: str, allow_empty: bool = False
) -> frozenset[str]:
    """A set of single characters the scan compares against."""
    _require(isinstance(raw, list), f"{where}: must be a list of characters")
    _require(allow_empty or raw, f"{where}: must not be empty")
    for item in raw:
        _require(
            isinstance(item, str) and len(item) == 1,
            f"{where}: {item!r} is not a single character",
        )
    return frozenset(raw)


def _parse_ranges(raw: object, where: str) -> tuple[tuple[int, int], ...]:
    """Code point ranges, written low..high in hexadecimal."""
    _require(isinstance(raw, list) and raw, f"{where}: must be a non-empty list")
    ranges: list[tuple[int, int]] = []
    for item in raw:
        _require(
            isinstance(item, str) and _RANGE_SEPARATOR in item,
            f"{where}: {item!r} is not a 'low..high' range",
        )
        low_text, _, high_text = item.partition(_RANGE_SEPARATOR)
        try:
            low, high = int(low_text, 16), int(high_text, 16)
        except ValueError:
            raise BackfillConfigError(
                f"{where}: {item!r} bounds must be hexadecimal code points"
            ) from None
        _require(low <= high, f"{where}: {item!r} is inverted")
        ranges.append((low, high))
    return tuple(ranges)


def _parse_prefixes(
    raw: object, where: str, terminators: frozenset[str]
) -> tuple[str, ...]:
    """Abbreviations that carry a terminator and still do not end a sentence.

    Each entry has to end in a terminator the same profile declares: an entry
    that does not is a word the scan never looks at, so it would sit in the file
    claiming an effect it cannot have.
    """
    if raw is None:
        return ()
    _require(isinstance(raw, list), f"{where}: must be a list of abbreviations")
    for item in raw:
        _require(
            isinstance(item, str) and len(item) > 1,
            f"{where}: {item!r} is not an abbreviation of at least two characters",
        )
        _require(
            item[-1] in terminators,
            f"{where}: {item!r} does not end in a terminator this profile "
            f"declares, so no boundary could ever be read at it",
        )
    return tuple(raw)


def _parse_join(raw: object, source: str) -> JoinRules:
    where = f"{source}: {JOIN_KEY}"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    known = {
        DESCRIPTION_KEY,
        "default_separator",
        "spaceless_separator",
        "hyphen_separator",
        "drop_trailing_hyphen",
        "trailing_hyphens",
        "spaceless_script_ranges",
    }
    unknown = sorted(set(raw) - known)
    _require(not unknown, f"{where}: unknown keys {unknown}")
    missing = sorted(known - {DESCRIPTION_KEY} - set(raw))
    _require(not missing, f"{where}: missing keys {missing}")
    for key in ("default_separator", "spaceless_separator", "hyphen_separator"):
        _require(isinstance(raw[key], str), f"{where}.{key}: must be a string")
    _require(
        isinstance(raw["drop_trailing_hyphen"], bool),
        f"{where}.drop_trailing_hyphen: must be a boolean",
    )
    return JoinRules(
        default_separator=raw["default_separator"],
        spaceless_separator=raw["spaceless_separator"],
        hyphen_separator=raw["hyphen_separator"],
        drop_trailing_hyphen=raw["drop_trailing_hyphen"],
        trailing_hyphens=_parse_char_set(
            raw["trailing_hyphens"], f"{where}.trailing_hyphens"
        ),
        spaceless_ranges=_parse_ranges(
            raw["spaceless_script_ranges"], f"{where}.spaceless_script_ranges"
        ),
    )


def _parse_min_chars(raw: object, where: str, config: dict, default: int) -> int:
    """A profile's sentence floor, bounded by the range its flat namesake declares."""
    if raw is None:
        return default
    range_key = f"{SENTENCE_MIN_CHARS_KEY}{RANGE_SUFFIX}"
    _require(range_key in config, f"{where}: no {range_key} to be bounded by")
    bounded = validate_bounded_config(
        {SENTENCE_MIN_CHARS_KEY: raw, range_key: config[range_key]}, CONFIG_PATH
    )
    return int(bounded[SENTENCE_MIN_CHARS_KEY])


def _parse_markers(raw: object, where: str) -> tuple[str, ...]:
    """The closed class words a cut may be moved to stand after.

    An empty list is a declaration and not an omission: it says this language
    takes no marker move, which is what a profile whose break rule already
    snaps to word boundaries wants.
    """
    if raw is None:
        return ()
    _require(isinstance(raw, list), f"{where}: must be a list of words")
    markers = []
    for item in raw:
        _require(
            isinstance(item, str) and item and not item.strip() != item,
            f"{where}: {item!r} is not a word without surrounding space",
        )
        markers.append(item)
    duplicated = sorted({item for item in markers if markers.count(item) > 1})
    _require(not duplicated, f"{where}: {duplicated} declared more than once")
    # Longest first, so a marker that ends with a shorter one is tested whole.
    return tuple(sorted(markers, key=len, reverse=True))


def _parse_align_switch(raw: object, source: str) -> str:
    where = f"{source}: {ALIGN_SWITCH_KEY}"
    _require(
        isinstance(raw, str) and raw.strip() and raw.strip() == raw,
        f"{where}: must name the run attribute the alignment level is read from",
    )
    return raw


def _parse_profile(name: str, raw: object, source: str, config: dict, default: int):
    where = f"{source}: {PROFILES_KEY}.{ENTRIES_KEY}.{name}"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    unknown = sorted(
        set(raw) - {DESCRIPTION_KEY, *_PROFILE_REQUIRED, *_PROFILE_OPTIONAL}
    )
    _require(not unknown, f"{where}: unknown keys {unknown}")
    missing = sorted(set(_PROFILE_REQUIRED) - set(raw))
    _require(not missing, f"{where}: missing keys {missing}")

    prefixes = raw["language_prefixes"]
    _require(
        isinstance(prefixes, list)
        and prefixes
        and all(isinstance(item, str) and item for item in prefixes),
        f"{where}.language_prefixes: must list at least one non-empty tag",
    )
    terminators = _parse_char_set(raw["terminators"], f"{where}.terminators", True)
    gated = _parse_char_set(
        raw["space_gated_terminators"], f"{where}.space_gated_terminators", True
    )
    _require(
        terminators or gated,
        f"{where}: declares no terminator of either kind, so no text scored under "
        f"it could ever hold a sentence end",
    )
    overlap = sorted(terminators & gated)
    _require(
        not overlap,
        f"{where}: {overlap} are declared both gated and ungated, which leaves it "
        f"undecided whether they need whitespace after them",
    )
    _require(
        raw["break_rule"] in BREAK_RULES,
        f"{where}.break_rule: {raw['break_rule']!r} is not implemented; "
        f"the rules are {list(BREAK_RULES)}",
    )
    return LanguageProfile(
        name=name,
        language_prefixes=tuple(item.strip().lower() for item in prefixes),
        terminators=terminators,
        space_gated_terminators=gated,
        all_terminators=terminators | gated,
        closers=_parse_char_set(raw["closers"], f"{where}.closers", True),
        non_terminal_prefixes=_parse_prefixes(
            raw.get(NON_TERMINAL_PREFIXES_KEY),
            f"{where}.{NON_TERMINAL_PREFIXES_KEY}",
            terminators | gated,
        ),
        break_rule=raw["break_rule"],
        sentence_min_chars=_parse_min_chars(
            raw.get(SENTENCE_MIN_CHARS_KEY), where, config, default
        ),
        cut_boundary_markers=_parse_markers(
            raw.get(CUT_BOUNDARY_MARKERS_KEY), f"{where}.{CUT_BOUNDARY_MARKERS_KEY}"
        ),
    )


def _parse_profiles(
    raw: object, source: str, config: dict, default: int
) -> tuple[dict[str, LanguageProfile], str]:
    where = f"{source}: {PROFILES_KEY}"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    unknown = sorted(set(raw) - {DESCRIPTION_KEY, DEFAULT_KEY, ENTRIES_KEY})
    _require(not unknown, f"{where}: unknown keys {unknown}")
    entries = raw.get(ENTRIES_KEY)
    _require(
        isinstance(entries, dict) and entries,
        f"{where}.{ENTRIES_KEY}: must declare at least one profile",
    )
    profiles = {
        name: _parse_profile(name, entry, source, config, default)
        for name, entry in entries.items()
    }
    fallback = raw.get(DEFAULT_KEY)
    _require(
        fallback in profiles,
        f"{where}.{DEFAULT_KEY}: {fallback!r} is not a declared profile; "
        f"declared profiles are {sorted(profiles)}",
    )
    claimed: dict[str, str] = {}
    for name, profile in profiles.items():
        for prefix in profile.language_prefixes:
            _require(
                prefix not in claimed,
                f"{where}: language prefix {prefix!r} is claimed by both "
                f"{claimed.get(prefix)!r} and {name!r}",
            )
            claimed[prefix] = name
    return profiles, fallback


def _parse_strategies(raw: object, source: str) -> tuple[dict[str, str], str]:
    where = f"{source}: {STRATEGIES_KEY}"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    unknown = sorted(set(raw) - {DESCRIPTION_KEY, DEFAULT_KEY, BY_PAIR_CLASS_KEY})
    _require(not unknown, f"{where}: unknown keys {unknown}")
    fallback = raw.get(DEFAULT_KEY)
    _require(
        fallback in STRATEGIES,
        f"{where}.{DEFAULT_KEY}: {fallback!r} is not implemented; the strategies "
        f"are {list(STRATEGIES)}",
    )
    by_class = raw.get(BY_PAIR_CLASS_KEY)
    _require(
        isinstance(by_class, dict) and by_class,
        f"{where}.{BY_PAIR_CLASS_KEY}: must map at least one pair class",
    )
    for pair_class, strategy in by_class.items():
        _require(
            isinstance(pair_class, str) and pair_class,
            f"{where}.{BY_PAIR_CLASS_KEY}: pair class names must be non-empty",
        )
        _require(
            strategy in STRATEGIES,
            f"{where}.{BY_PAIR_CLASS_KEY}.{pair_class}: {strategy!r} is not "
            f"implemented; the strategies are {list(STRATEGIES)}",
        )
    return dict(by_class), fallback


def _parse_capacity(raw: object, source: str) -> CapacityGrid:
    """The line grid, bounded by the ranges declared beside each of its numbers."""
    where = f"{source}.{CAPACITY_KEY}"
    _require(isinstance(raw, dict), f"{where} must be an object")
    prefixes = raw.get("cjk_target_prefixes")
    _require(
        isinstance(prefixes, list)
        and bool(prefixes)
        and all(isinstance(item, str) and item.strip() for item in prefixes),
        f"{where}.cjk_target_prefixes must be a non-empty list of language tags",
    )
    flat = {
        key: value
        for key, value in raw.items()
        if key not in (DESCRIPTION_KEY, "cjk_target_prefixes")
    }
    try:
        numbers = dict(validate_bounded_config(flat, Path(where)))
    except ConfigError as exc:
        raise BackfillConfigError(str(exc)) from exc
    needed = (
        "line_skip_cjk",
        "line_skip_latin",
        "advance_ratio_cjk",
        "advance_ratio_latin",
    )
    missing = sorted(set(needed) - set(numbers))
    _require(not missing, f"{where}: missing parameters {missing}")
    return CapacityGrid(
        line_skip_cjk=float(numbers["line_skip_cjk"]),
        line_skip_latin=float(numbers["line_skip_latin"]),
        advance_ratio_cjk=float(numbers["advance_ratio_cjk"]),
        advance_ratio_latin=float(numbers["advance_ratio_latin"]),
        cjk_target_prefixes=tuple(item.strip().lower() for item in prefixes),
    )


def _parse_punctuation(raw: object, source: str, key: str) -> frozenset:
    """A declared class of one-character punctuation marks."""
    where = f"{source}.{key}"
    _require(
        isinstance(raw, list) and bool(raw),
        f"{where} must be a non-empty list of marks",
    )
    for item in raw:
        _require(
            isinstance(item, str) and len(item) == 1,
            f"{where} holds {item!r}, which is not a single character",
        )
    return frozenset(raw)


@lru_cache(maxsize=4)
def load_backfill_config(path: str | None = None) -> BackfillConfig:
    """Load and validate ``configs/chain_translation.json``.

    The flat entries are bounded the usual way; the nested sections are checked
    against the vocabularies this module implements, so a strategy or a break
    rule that has no code behind it is refused at load rather than reached at
    run time.
    """
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    source = config_path.name
    flat = {key: value for key, value in raw.items() if key not in NESTED_KEYS}
    parameters = validate_bounded_config(flat, config_path)
    missing = sorted(REQUIRED_PARAMETERS - set(parameters))
    _require(not missing, f"{source}: missing parameters {missing}")

    default_min_chars = int(parameters[SENTENCE_MIN_CHARS_KEY])
    profiles, default_profile = _parse_profiles(
        raw.get(PROFILES_KEY), source, raw, default_min_chars
    )
    strategy_by_pair_class, default_strategy = _parse_strategies(
        raw.get(STRATEGIES_KEY), source
    )
    return BackfillConfig(
        sentence_min_chars=default_min_chars,
        snap_search_ratio=float(parameters["snap_search_ratio"]),
        snap_search_min_chars=int(parameters["snap_search_min_chars"]),
        cut_snap_radius=int(parameters["cut_snap_radius"]),
        output_token_budget=int(parameters["output_token_budget"]),
        output_token_ratio=float(parameters["output_token_ratio"]),
        align_switch=_parse_align_switch(raw.get(ALIGN_SWITCH_KEY), source),
        join=_parse_join(raw.get(JOIN_KEY), source),
        profiles=profiles,
        default_profile=default_profile,
        strategy_by_pair_class=strategy_by_pair_class,
        default_strategy=default_strategy,
        capacity=_parse_capacity(raw.get(CAPACITY_KEY), source),
        line_head_forbidden=_parse_punctuation(
            raw.get(LINE_HEAD_KEY), source, LINE_HEAD_KEY
        ),
        line_tail_forbidden=_parse_punctuation(
            raw.get(LINE_TAIL_KEY), source, LINE_TAIL_KEY
        ),
        slot_min_font_size=float(parameters["slot_min_font_size"]),
        slot_fit_tolerance=float(parameters["slot_fit_tolerance"]),
    )


def select_profile(language: str | None, config: BackfillConfig) -> LanguageProfile:
    """The profile a target language tag resolves to, longest prefix first.

    A tag matches a prefix when it is that prefix or a subtag of it, so ``zh``
    and ``zh-CN`` resolve alike while ``zho`` does not match ``zh``.
    """
    if not language:
        return config.profiles[config.default_profile]
    tag = language.strip().lower()
    for alias in _SUBTAG_ALIASES:
        tag = tag.replace(alias, _SUBTAG_SEPARATOR)
    best: tuple[int, str] | None = None
    for name, profile in config.profiles.items():
        for prefix in profile.language_prefixes:
            if tag == prefix or tag.startswith(prefix + _SUBTAG_SEPARATOR):
                if best is None or len(prefix) > best[0]:
                    best = (len(prefix), name)
    if best is None:
        return config.profiles[config.default_profile]
    return config.profiles[best[1]]


def strategy_for_pair_class(pair_class: str | None, config: BackfillConfig) -> str:
    """The redistribution declared for one endpoint pair class."""
    if pair_class is None:
        return config.default_strategy
    return config.strategy_by_pair_class.get(pair_class, config.default_strategy)


def estimated_output_tokens(source_tokens: int, config: BackfillConfig) -> int:
    """How large an answer a merged chain of this size is expected to draw.

    The estimate rounds up, so a chain sitting exactly on the budget is treated
    as reaching it rather than as fitting.
    """
    return math.ceil(max(0, source_tokens) * config.output_token_ratio)


def over_output_token_budget(source_tokens: int, config: BackfillConfig) -> bool:
    """Whether a chain this size is too large to be sent as one unit.

    The engine answers with a fixed output ceiling and truncates rather than
    refusing when a request reaches it, and a truncated answer is still a
    string the redistribution would cut up and write back. The size is
    therefore judged before the request, from the merged source alone.
    """
    return estimated_output_tokens(source_tokens, config) > config.output_token_budget


# --- merge ------------------------------------------------------------------


def _separator_for(left: str, right: str, join: JoinRules) -> tuple[str, str]:
    """The separator between two members, and the left member as it is kept.

    A trailing hyphen with a word in front of it is a word the page break cut
    in half, so it goes and the halves close up. A hyphen standing on its own
    is a word and stays.
    """
    if (
        join.drop_trailing_hyphen
        and len(left) > 1
        and left[-1] in join.trailing_hyphens
        and not left[-2].isspace()
    ):
        return join.hyphen_separator, left[:-1]
    if join.is_spaceless(left[-1]) and join.is_spaceless(right[0]):
        return join.spaceless_separator, left
    return join.default_separator, left


def merge_chain_text(
    members: Sequence[str], config: BackfillConfig | None = None
) -> ChainMerge:
    """Merge the members of one chain, in chain order, into one source text.

    A member that carries no text is refused rather than merged away: a chain
    whose member has nothing to say cannot be given a share of the translation
    afterwards, and silently dropping it would break the count the whole
    conservation law rests on.
    """
    config = load_backfill_config() if config is None else config
    if not members:
        raise ChainBackfillError("a chain must have at least one member to merge")
    for index, member in enumerate(members):
        if not isinstance(member, str):
            raise ChainBackfillError(f"member {index} is not a string")
        if not member.strip():
            raise ChainBackfillError(f"member {index} carries no text")

    kept = list(members)
    separators = [""]
    dropped: list[int] = []
    for index in range(1, len(kept)):
        separator, left = _separator_for(kept[index - 1], kept[index], config.join)
        if left != kept[index - 1]:
            dropped.append(index - 1)
        kept[index - 1] = left
        separators.append(separator)

    pieces: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    for index, member in enumerate(kept):
        cursor += len(separators[index])
        pieces.append(separators[index])
        pieces.append(member)
        spans.append((cursor, cursor + len(member)))
        cursor += len(member)
    return ChainMerge(
        text="".join(pieces),
        members=tuple(kept),
        separators=tuple(separators),
        spans=tuple(spans),
        dropped_hyphens=tuple(dropped),
    )


# --- sentences --------------------------------------------------------------


def _visible_length(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def _ends_with_abbreviation(text: str, end: int, profile: LanguageProfile) -> bool:
    """Whether the text ending at ``end`` closes on a declared abbreviation.

    The character in front of the abbreviation has to be one that cannot
    continue a word, so a longer word ending in the same letters is not read as
    the abbreviation itself.
    """
    for prefix in profile.non_terminal_prefixes:
        start = end - len(prefix)
        if start < 0 or text[start:end] != prefix:
            continue
        if start == 0 or not text[start - 1].isalnum():
            return True
    return False


def split_sentences(text: str, profile: LanguageProfile) -> tuple[str, ...]:
    """Cut ``text`` into sentences that join back to it exactly.

    A boundary is a run of terminators, the closers behind it and the
    whitespace behind those, so every character of the text belongs to exactly
    one sentence and the trailing space of a sentence travels with it. The last
    terminator of the run decides whether the boundary needs whitespace after
    it to count, and a run that closes a declared abbreviation is no boundary
    whatever follows it.
    """
    if not text:
        return ()
    sentences: list[str] = []
    start = 0
    index = 0
    length = len(text)
    while index < length:
        if text[index] not in profile.all_terminators:
            index += 1
            continue
        run_end = index
        while run_end < length and text[run_end] in profile.all_terminators:
            run_end += 1
        if _ends_with_abbreviation(text, run_end, profile):
            index = run_end
            continue
        closer_end = run_end
        while closer_end < length and text[closer_end] in profile.closers:
            closer_end += 1
        gated = text[run_end - 1] not in profile.terminators
        if gated and closer_end < length and not text[closer_end].isspace():
            index = run_end
            continue
        end = closer_end
        while end < length and text[end].isspace():
            end += 1
        candidate = text[start:end]
        if _visible_length(candidate) >= profile.sentence_min_chars:
            sentences.append(candidate)
            start = end
        index = end
    if start < length:
        sentences.append(text[start:])
    return tuple(sentences)


def sentence_end_offsets(sentences: Sequence[str]) -> tuple[int, ...]:
    """The exclusive end offset of each sentence within the joined text."""
    offsets: list[int] = []
    cursor = 0
    for sentence in sentences:
        cursor += len(sentence)
        offsets.append(cursor)
    return tuple(offsets)


# --- redistribution ---------------------------------------------------------


def _is_legal_break(text: str, position: int, profile: LanguageProfile) -> bool:
    """Whether a cut may land in front of ``text[position]``."""
    if position <= 0 or position >= len(text):
        return False
    if unicodedata.combining(text[position]) != 0:
        return False
    if text[position - 1] == _ZERO_WIDTH_JOINER:
        return False
    if profile.break_rule == BREAK_WORD_BOUNDARY:
        return text[position - 1].isspace() and not text[position].isspace()
    return True


def _snap(
    text: str,
    ideal: int,
    low: int,
    high: int,
    target_length: int,
    profile: LanguageProfile,
    config: BackfillConfig,
) -> int | None:
    """The legal break nearest the ideal position, earlier one winning a tie."""
    radius = max(
        config.snap_search_min_chars,
        round(target_length * config.snap_search_ratio),
    )
    for offset in range(radius + 1):
        candidates = (ideal,) if offset == 0 else (ideal - offset, ideal + offset)
        for candidate in candidates:
            if low <= candidate <= high and _is_legal_break(text, candidate, profile):
                return candidate
    return None


def _follows_marker(text: str, position: int, profile: LanguageProfile) -> str | None:
    """What, if anything, the character in front of ``position`` finishes.

    A punctuation mark finishes a clause in every language this runs in, and a
    declared marker finishes one in the language that declared it. Punctuation
    is asked first: it is the stronger evidence and it is language independent.
    """
    if position <= 0 or position > len(text):
        return None
    if unicodedata.category(text[position - 1]).startswith("P"):
        return MOVED_TO_PUNCTUATION
    for marker in profile.cut_boundary_markers:
        if text.endswith(marker, 0, position):
            return MOVED_TO_MARKER
    return None


def _snap_to_boundary(
    text: str,
    ideal: int,
    low: int,
    high: int,
    profile: LanguageProfile,
    config: BackfillConfig,
) -> tuple[int, str] | None:
    """Move an estimate onto a nearby clause end, nearest first, earlier on a tie.

    The radius is small and fixed rather than proportional to the piece: this
    corrects an estimate that is nearly right, and an estimate that is wrong by
    more than a couple of characters is wrong for a reason no local move
    repairs.
    """
    for offset in range(config.cut_snap_radius + 1):
        candidates = (ideal,) if offset == 0 else (ideal - offset, ideal + offset)
        for candidate in candidates:
            if not low <= candidate <= high:
                continue
            if not _is_legal_break(text, candidate, profile):
                continue
            moved = _follows_marker(text, candidate, profile)
            if moved is not None:
                return candidate, moved
    return None


def _nearest_boundary(
    boundaries: Sequence[int], ideal: int, low: int, high: int, reserve: int
) -> int | None:
    """The sentence boundary nearest the ideal position that leaves enough behind.

    ``reserve`` is how many of the cuts that still follow this one a boundary
    has to be kept for. A boundary that does not leave that many behind it is
    not taken, so an early cut cannot spend the boundary a later one needs.
    Where there are fewer boundaries than cuts the reserve shrinks to what is
    actually there, which is what lets the boundaries that do exist land at the
    positions that want them and leaves only the remainder to be cut by share.
    """
    eligible = [
        position
        for order, position in enumerate(boundaries)
        if low <= position <= high and len(boundaries) - 1 - order >= reserve
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda position: (abs(position - ideal), position))


def _plan_cuts(
    translated: str,
    shares: Sequence[float],
    boundaries: Sequence[int],
    profile: LanguageProfile,
    config: BackfillConfig,
    allow_sentence_cuts: bool,
) -> tuple[Cut, ...]:
    """Place the interior cuts, in order, one per member handover."""
    length = len(translated)
    count = len(shares)
    cuts: list[Cut] = []
    previous = 0
    cumulative = 0.0
    for index in range(count - 1):
        cumulative += shares[index]
        # Every member left, this one included, still needs a character.
        low = previous + 1
        high = length - (count - 1 - index)
        if low > high:
            raise ChainBackfillError(
                f"the translation has {length} characters, too few to give each "
                f"of {count} members a piece"
            )
        ideal = min(max(round(length * cumulative), low), high)
        position = None
        if allow_sentence_cuts:
            available = sum(1 for offset in boundaries if low <= offset <= high)
            reserve = max(0, min(count - 2 - index, available - 1))
            position = _nearest_boundary(boundaries, ideal, low, high, reserve)
        if position is not None:
            cuts.append(Cut(index, position, CUT_SENTENCE, True, estimate=ideal))
        else:
            # The second level of the cascade, offered the estimate the first
            # level produced when there was one and the share when there was
            # not. It moves the cut onto a clause end within a couple of
            # characters or leaves it where it stands.
            moved = _snap_to_boundary(translated, ideal, low, high, profile, config)
            if moved is not None:
                cuts.append(
                    Cut(index, moved[0], CUT_PROPORTIONAL, True, ideal, moved[1])
                )
            else:
                target = max(1, round(length * shares[index]))
                snapped = _snap(translated, ideal, low, high, target, profile, config)
                cuts.append(
                    Cut(
                        index,
                        ideal if snapped is None else snapped,
                        CUT_PROPORTIONAL,
                        snapped is not None,
                        estimate=ideal,
                    )
                )
        previous = cuts[-1].position
    return tuple(cuts)


def _retreat_off_line_head(
    text: str, position: int, low: int, profile: LanguageProfile, forbidden
) -> tuple[int, str | None]:
    """Pull a cut back off a mark the continuation may not open with.

    The class consulted is the typesetting stage's own, so a cut is judged by
    the rule that will set the line rather than by a second list meaning nearly
    the same thing. The retreat is bounded and it is refused rather than
    forced: a position it cannot reach legally leaves the cut where it stood,
    which the record then says.
    """
    if position >= len(text) or text[position] not in forbidden:
        return position, None
    for step in range(1, _LINE_HEAD_RETREAT_LIMIT + 1):
        candidate = position - step
        if candidate < low:
            break
        if text[candidate] in forbidden:
            continue
        if _is_legal_break(text, candidate, profile):
            return candidate, MOVED_OFF_LINE_HEAD
    return position, None


def _plan_capacity_cuts(
    translated: str,
    capacities: Sequence[int],
    profile: LanguageProfile,
    config: BackfillConfig,
) -> tuple[Cut, ...]:
    """Place each cut where the member's box runs out of room.

    A body chain is one paragraph the layout broke, so its continuation should
    resume where the first box stopped holding text and not where the nearest
    sentence happened to end. The estimate is therefore the box's own capacity
    in characters, accumulated across the members, rather than a share of the
    text: a cut at a share leaves the first box's last line part empty whenever
    the two boxes are of different sizes, and that gap is the join showing.

    The estimate is then made a position a line may actually break at -- the
    profile's break rule decides that, which is nearly any character between
    two Chinese ones and a word edge in English -- and pulled back off a mark
    no line may open with.
    """
    length = len(translated)
    count = len(capacities)
    cuts: list[Cut] = []
    previous = 0
    running = 0
    for index in range(count - 1):
        running += capacities[index]
        low = previous + 1
        high = length - (count - 1 - index)
        if low > high:
            raise ChainBackfillError(
                f"the translation has {length} characters, too few to give each "
                f"of {count} members a piece"
            )
        ideal = min(max(running, low), high)
        target = max(1, capacities[index])
        snapped = _snap(translated, ideal, low, high, target, profile, config)
        position = ideal if snapped is None else snapped
        position, moved = _retreat_off_line_head(
            translated, position, low, profile, config.line_head_forbidden
        )
        cuts.append(
            Cut(
                index,
                position,
                CUT_CAPACITY,
                snapped is not None,
                estimate=ideal,
                moved_to=moved,
            )
        )
        previous = position
    return tuple(cuts)


def _sentence_intervals(
    positions: Sequence[int], ends: Sequence[int], count: int
) -> tuple[tuple[int, int], ...]:
    """Attribute the sentences to the members, as one partition of their range.

    A member's range runs from the first sentence not already finished before
    it starts to the last one it finishes, so a sentence a proportional cut
    left straddling two members belongs to the one that finishes it and the
    ranges still tile the sentences once.
    """
    starts = [bisect.bisect_right(ends, position) for position in (0, *positions)]
    return tuple(
        (starts[index], starts[index + 1] if index + 1 < count else len(ends))
        for index in range(count)
    )


def align_shares(lengths: Sequence[int] | None, count: int) -> tuple[float, ...] | None:
    """The shares a set of auxiliary translation lengths gives, or None.

    None where the lengths cannot size anything: one per member is needed, each
    positive, and a caller that could not obtain them says so by passing none
    rather than by passing zeros.
    """
    if lengths is None or len(lengths) != count:
        return None
    if any(not isinstance(item, int) or item <= 0 for item in lengths):
        return None
    total = sum(lengths)
    return tuple(item / total for item in lengths)


def redistribute(
    merge: ChainMerge,
    translated: str,
    language: str | None,
    strategy: str,
    config: BackfillConfig | None = None,
    aligned_lengths: Sequence[int] | None = None,
    align_enabled: bool = True,
    capacities: Sequence[int] | None = None,
) -> Redistribution:
    """Cut one chain's translation back into one piece per member.

    A cut is placed by a cascade of three. Where ``aligned_lengths`` carries a
    usable length per member -- each member's own translation measured, never
    read -- the pieces are sized by those lengths, so a cut lands where the
    first member's translation would have ended. Where it does not, they are
    sized by each member's share of the merged source, which is what every run
    before the cascade did. Either estimate is then offered to a clause end
    within the declared radius.

    Under ``sentence_greedy`` a cut lands on a sentence end wherever one is
    still available and is placed by the estimate where none is, which is
    reported as a proportional fallback. Under ``proportional`` no sentence
    indices are claimed. Under ``capacity`` the cut is placed where the
    member's own box stops holding text, which needs ``capacities`` and falls
    back to the share cascade where the caller could not measure them -- a
    caller with no boxes to measure says so by passing none, and the fallback
    is reported rather than assumed.
    """
    config = load_backfill_config() if config is None else config
    if strategy not in STRATEGIES:
        raise ChainBackfillError(
            f"{strategy!r} is not implemented; the strategies are {list(STRATEGIES)}"
        )
    if not translated or not translated.strip():
        raise ChainBackfillError("the translation carries no text")
    count = len(merge.members)
    if len(translated) < count:
        raise ChainBackfillError(
            f"the translation has {len(translated)} characters, too few to give "
            f"each of {count} members a piece"
        )

    profile = select_profile(language, config)
    sentences = split_sentences(translated, profile)
    ends = sentence_end_offsets(sentences)
    interior = [offset for offset in ends if offset < len(translated)]
    sentence_mode = strategy == STRATEGY_SENTENCE_GREEDY
    # Usable capacities are one positive integer per member. Anything else is
    # not a measurement, and a cut placed on it would be a guess wearing a
    # measurement's name.
    usable_capacities = (
        capacities is not None
        and len(capacities) == count
        and all(isinstance(item, int) and item > 0 for item in capacities)
    )
    capacity_mode = strategy == STRATEGY_CAPACITY and usable_capacities
    # The sentences are attributed whenever the text has sentence structure to
    # attribute, which a body chain has however its cuts were placed. Only the
    # display strategy claims none.
    claims_sentences = strategy != STRATEGY_PROPORTIONAL

    source_shares = merge.shares
    aligned = align_shares(aligned_lengths, count) if align_enabled else None
    if not align_enabled:
        reason = ALIGN_SWITCH_DOWN
    elif aligned_lengths is None:
        reason = ALIGN_NOT_OFFERED
    elif aligned is None:
        reason = ALIGN_UNUSABLE
    else:
        reason = None
    alignment = Alignment(
        used=aligned is not None,
        reason=reason,
        member_lengths=tuple(aligned_lengths or ()),
        source_shares=source_shares,
    )

    if capacity_mode:
        cuts = _plan_capacity_cuts(translated, list(capacities), profile, config)
    else:
        cuts = _plan_cuts(
            translated,
            source_shares if aligned is None else aligned,
            interior,
            profile,
            config,
            sentence_mode,
        )
    positions = [cut.position for cut in cuts]
    edges = [0, *positions, len(translated)]
    intervals = (
        _sentence_intervals(positions, ends, count)
        if claims_sentences
        else ((NO_SENTENCE_INDEX, NO_SENTENCE_INDEX),) * count
    )
    segments = tuple(
        MemberSegment(
            index=index,
            text=translated[edges[index] : edges[index + 1]],
            start=edges[index],
            end=edges[index + 1],
            sentence_start=intervals[index][0],
            sentence_end=intervals[index][1],
        )
        for index in range(count)
    )
    if strategy == STRATEGY_CAPACITY and not capacity_mode:
        fallback = FALLBACK_NO_CAPACITY
    elif sentence_mode and any(cut.mode == CUT_PROPORTIONAL for cut in cuts):
        fallback = FALLBACK_PROPORTIONAL
    else:
        fallback = None
    result = Redistribution(
        strategy=strategy,
        profile=profile.name,
        segments=segments,
        sentences=sentences,
        cuts=cuts,
        fallback=fallback,
        alignment=alignment,
        capacities=tuple(capacities or ()),
    )
    report = verify_redistribution(merge, translated, result)
    if not report.ok:
        raise ChainBackfillError(
            f"redistribution violates conservation: {list(report.violations)}"
        )
    return result


# --- conservation -----------------------------------------------------------


def verify_redistribution(
    merge: ChainMerge, translated: str, result: Redistribution
) -> ConservationReport:
    """State the conservation law over one redistribution.

    The pieces join back to the translation exactly, their spans tile it once
    from end to end, every member gets one non-empty piece, and the sentence
    ranges partition the sentences of the translation. Everything here is
    checkable from the arguments alone, which is what lets a caller verify a
    result it did not produce.
    """
    violations: list[str] = []
    segments = result.segments
    if len(segments) != len(merge.members):
        violations.append(
            f"member count changed: {len(merge.members)} in, {len(segments)} out"
        )
    joined = "".join(segment.text for segment in segments)
    if joined != translated:
        violations.append(
            f"the pieces do not join back to the translation: "
            f"{len(joined)} characters against {len(translated)}"
        )

    cursor = 0
    for position, segment in enumerate(segments):
        if segment.index != position:
            violations.append(f"segment {position} carries index {segment.index}")
        if segment.start != cursor:
            violations.append(
                f"segment {position} starts at {segment.start}, leaving a gap or an "
                f"overlap at {cursor}"
            )
        if segment.end <= segment.start:
            violations.append(
                f"segment {position} spans {segment.start}..{segment.end} and is empty"
            )
        if segment.text != translated[segment.start : segment.end]:
            violations.append(f"segment {position} is not the text at its own span")
        cursor = segment.end
    if segments and cursor != len(translated):
        violations.append(f"the spans stop at {cursor} of {len(translated)} characters")

    violations.extend(_sentence_violations(result, translated))
    return ConservationReport(ok=not violations, violations=tuple(violations))


def _sentence_violations(result: Redistribution, translated: str) -> list[str]:
    """The sentence side of the law: the ranges tile the sentences once."""
    violations: list[str] = []
    if "".join(result.sentences) != translated:
        violations.append("the sentences do not join back to the translation")
    marked = [
        segment
        for segment in result.segments
        if segment.sentence_start == NO_SENTENCE_INDEX
        or segment.sentence_end == NO_SENTENCE_INDEX
    ]
    if marked and len(marked) != len(result.segments):
        violations.append(
            f"{len(marked)} of {len(result.segments)} members claim no sentence "
            f"range, which leaves the range of the rest unreadable"
        )
    if marked:
        return violations

    cursor = 0
    for segment in result.segments:
        if segment.sentence_start != cursor:
            violations.append(
                f"member {segment.index} starts at sentence {segment.sentence_start}, "
                f"leaving a gap or an overlap at {cursor}"
            )
        if segment.sentence_end < segment.sentence_start:
            violations.append(
                f"member {segment.index} spans sentences "
                f"{segment.sentence_start}..{segment.sentence_end} backwards"
            )
        cursor = max(cursor, segment.sentence_end)
    if result.segments and cursor != len(result.sentences):
        violations.append(
            f"the sentence ranges stop at {cursor} of {len(result.sentences)}"
        )
    return violations
