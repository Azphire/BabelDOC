"""One acceptance test for every single-unit retry the pipeline makes.

What is broken here
-------------------

The upstream translator refuses a reply that is far longer or far shorter than
what it asked about: ``il_translator_llm_only`` counts tokens on both sides and
falls back to the source when the ratio leaves ``0.3 .. 3``. Every paragraph of
every page passes that test.

The passes this project added do not. Each of them asks the engine one more
question about one unit -- an echoed label, a unit whose ruled term the page
did not honour, a unit the length floor never offered a request -- and each of
them wrote its own acceptance: does the reply parse, does it differ from the
source, does the ruled rendering appear in it. None of them asked how big the
answer was.

Two replies in the B18 corpus show what that costs. Asked to render the
masthead fragment ``ERNCOURIER`` again with its ruling pinned, the engine
answered with four sentences of invented marketing copy about a courier
company, and every one of them was set into CERN Courier page 3's footer,
because the ruled string ``ERNCOURIER`` did appear in it. Asked the same about
``CourierT H E UNESCO``, it answered ``《信使》是由联合国教科文组织《信使》出版
的杂志，旨在传播文化和教育的价值。`` -- a sentence about the magazine rather than
the magazine's name -- and that reached the cover. Both replies were then
cached, so a warm re-run reproduced them without asking anything.

What this is
------------

The single acceptance point those channels were missing, stated once here and
called from each of them, because three passes with three opinions about what
an over-long answer is would be the same defect in triplicate.

How big is measured
-------------------

Not in characters. This corpus runs in two directions and one Han character
carries about as much as one English word, so a character ratio makes every
honest zh->en translation look like an inflation: measured that way the widest
honest expansion in the B18 corpus runs 6.79 characters out per character in
while the CERN reply that must be refused runs 15.5, and two thresholds that
close cannot both be safe. So a Han character counts as one and a run of
letters or digits in any other script counts as one -- what the upstream
guard's token count achieves with a tokenizer this has no reach to. Measured
this way all 1456 translated units of the corpus sit at or under 9.0, and the
two refused replies sit at 7.75 and 118.

The three tests, and why each is shaped the way it is
-----------------------------------------------------

*Invented sentences.* A unit carrying no sentence-terminal punctuation is a
name, a label or a fragment, and an answer to it is one too. An answer that
comes back as a sentence several times the size of what it was asked about is
prose about the unit rather than the unit. Both refused replies are caught
here, one of them (Courier) by a single closing 。 that no length rule would
have reached. The bound clears every honest fragment translation in the
corpus, the widest of which runs 3.69, with room; a caption whose translation
legitimately closes with a full stop is shorter than its source and passes.

Which stops count is itself measured. The CJK marks are unambiguous; a Latin
full stop is not, and reading every one of them as a sentence called six
honest renderings of company names and job titles multi-sentence prose, so a
Latin stop counts only where it closes the string or opens another sentence.

*Gross length.* Both conditions have to fail together: past the declared ratio
**and** past the declared absolute cap. Either alone is unsafe, for opposite
reasons -- a ratio alone refuses an honest expansion, a cap alone refuses the
long paragraph a term retry may legitimately be handed.

*Content anchor.* A name-shaped unit's answer either keeps something of the
name or rewrites it wholly into the target script, which is what a
transliteration is. An answer sharing nothing with its input and running past
the length ratio is about something else. This one has never fired on the
corpus, which the report says rather than hides.

What a refusal does
-------------------

Nothing. The caller keeps what it had -- the source text, byte for byte -- and
records the typed reason. The unit is not asked again: a channel that re-asks
after a refusal is a channel that can oscillate, and a run that must finish is
better served by an honest untranslated unit than by an argument with an
engine.

One more thing happens, and it is the reason a warm re-run of B18 reproduced
both hallucinations without spending a request: the reply was in the
translation cache. A refused reply is discarded from the cache it was written
to, so the next run asks the question again rather than being handed the answer
this run refused.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("retry_guard.json")

# Why one reply was refused. A closed set: the caller records the name, never
# a sentence written at the site, so the three channels answer the question
# "why is this unit still in its source language" with one vocabulary.
REJECTED_SENTENCES = "retry_hallucination_rejected_sentences"
REJECTED_LENGTH = "retry_hallucination_rejected_length"
REJECTED_UNANCHORED = "retry_hallucination_rejected_unanchored"
REJECTION_REASONS = (
    REJECTED_SENTENCES,
    REJECTED_LENGTH,
    REJECTED_UNANCHORED,
)

# The family name the three reasons share, for a ledger that records the kind
# of refusal rather than which test caught it.
REJECTED = "retry_hallucination_rejected"

# What ends a sentence, by script. The CJK marks are unambiguous: nothing but
# a sentence ends with 。！？. The Latin full stop is not -- ``Co., Ltd.`` and
# ``indd 1 30/06`` carry stops that end nothing -- so a Latin terminal counts
# only where it closes the string or is followed by white space and something
# that opens a sentence. Measured against the B18 corpus: the naive reading
# called six honest zh->en renderings of company names and job titles
# multi-sentence prose, and this one calls none of them that while still
# reading both hallucinated replies as the prose they are.
_CJK_TERMINALS = "。！？；"
_SENTENCE_END = re.compile(
    rf"[{re.escape(_CJK_TERMINALS)}]+"
    r"|[.!?]+(?=\s+[\"'“‘(\[A-Z一-鿿]|\s*$)"
)

# A token, for the anchor test: a run of letters or digits in any script.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class RetryGuardError(ConfigError):
    """Raised when the retry acceptance configuration is malformed."""


@dataclass(frozen=True)
class RetryGuardConfig:
    """Everything bounded about accepting one single-unit retry."""

    retry_output_max_ratio: float
    retry_output_max_chars: int
    retry_sentence_max_ratio: float


def parse_retry_guard_config(raw: dict, source: str) -> RetryGuardConfig:
    """Validate one configuration mapping into the policy it declares."""
    try:
        parameters = dict(validate_bounded_config(raw, CONFIG_PATH))
    except ConfigError as exc:
        raise RetryGuardError(str(exc)) from exc
    names = (
        "retry_output_max_ratio",
        "retry_output_max_chars",
        "retry_sentence_max_ratio",
    )
    missing = sorted(set(names) - set(parameters))
    if missing:
        raise RetryGuardError(f"{source}: missing parameters {missing}")
    return RetryGuardConfig(
        retry_output_max_ratio=float(parameters["retry_output_max_ratio"]),
        retry_output_max_chars=int(parameters["retry_output_max_chars"]),
        retry_sentence_max_ratio=float(parameters["retry_sentence_max_ratio"]),
    )


@lru_cache(maxsize=1)
def load_retry_guard_config(path: str | None = None) -> RetryGuardConfig:
    """Load and validate ``configs/retry_guard.json``."""
    resolved = CONFIG_PATH if path is None else Path(path)
    with resolved.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise RetryGuardError(f"{resolved.name}: root must be an object")
    return parse_retry_guard_config(raw, resolved.name)


def effective_chars(text: str) -> int:
    """How long one string is, in the characters a reader sees.

    NFKC first, so a full-width Latin run and a half-width one are the same
    length, and whitespace out, so a source the paragraph finder spaced glyph
    by glyph is not measured as several times its own size -- which is the
    shape every CJK unit of this corpus arrives in.
    """
    return sum(
        1 for char in unicodedata.normalize("NFKC", text or "") if not char.isspace()
    )


def effective_size(text: str) -> int:
    """How much one string says, in units comparable across scripts.

    Characters cannot be compared across this corpus's two directions. One Han
    character carries about as much as one English word, so measuring both in
    characters makes every honest zh->en translation look like an inflation:
    the widest in the B18 corpus runs 6.79 characters out per character in and
    is correct, while a reply this pass must refuse runs 15.5. Two thresholds
    that close cannot both be safe.

    So a Han character counts as one and a run of letters or digits in any
    other script counts as one, which is what the upstream guard's token count
    achieves with a tokenizer this has no reach to. Under it the same honest
    translation measures near parity and the refused reply still measures two
    orders away.
    """
    normalized = unicodedata.normalize("NFKC", text or "")
    han = sum(1 for char in normalized if _is_han(char))
    words = len(_TOKEN.findall("".join(
        " " if _is_han(char) else char for char in normalized
    )))
    return han + words


def _is_han(char: str) -> bool:
    """Whether one character is a CJK ideograph, in any of its blocks."""
    return (
        "一" <= char <= "鿿"
        or "㐀" <= char <= "䶿"
        or "豈" <= char <= "﫿"
    )


def sentence_count(text: str) -> int:
    """How many sentences one string closes.

    Runs of terminals count once: an ellipsis is not three sentences.
    """
    return len(_SENTENCE_END.findall(text or ""))


def tokens(text: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _TOKEN.finditer(unicodedata.normalize("NFKC", text or ""))
    }


def accept(
    source_text: str,
    output: str,
    config: RetryGuardConfig | None = None,
) -> tuple[bool, str | None, dict]:
    """Whether one retry's reply may be written back.

    Returns ``(accepted, reason, evidence)``. ``reason`` is one of the closed
    rejection names, or ``None`` where the reply is accepted; ``evidence`` is
    what was measured either way, so an accepted reply is as inspectable as a
    refused one.
    """
    config = load_retry_guard_config() if config is None else config
    source_size = effective_size(source_text)
    output_size = effective_size(output)
    ratio = output_size / source_size if source_size else float("inf")
    source_sentences = sentence_count(source_text)
    output_sentences = sentence_count(output)
    shared = tokens(source_text) & tokens(output)
    evidence = {
        "source_size": source_size,
        "output_size": output_size,
        "output_chars": effective_chars(output),
        "ratio": round(ratio, 4) if source_size else None,
        "source_sentences": source_sentences,
        "output_sentences": output_sentences,
        "shared_tokens": sorted(shared)[:8],
        "max_ratio": config.retry_output_max_ratio,
        "max_chars": config.retry_output_max_chars,
        "sentence_max_ratio": config.retry_sentence_max_ratio,
    }
    name_shaped = source_sentences == 0
    if (
        name_shaped
        and output_sentences
        and ratio > config.retry_sentence_max_ratio
    ):
        return False, REJECTED_SENTENCES, evidence
    over_ratio = ratio > config.retry_output_max_ratio
    if over_ratio and evidence["output_chars"] > config.retry_output_max_chars:
        return False, REJECTED_LENGTH, evidence
    if name_shaped and over_ratio and not shared and _script_mixed(source_text, output):
        return False, REJECTED_UNANCHORED, evidence
    return True, None, evidence


def _script_mixed(source_text: str, output: str) -> bool:
    """Whether the answer is something other than a wholesale rewrite.

    A name carried into another script shares no token with its source and is
    exactly right, so the anchor test has to let a transliteration through. It
    does so by asking whether the output still carries characters of the
    source's own kind: an answer wholly in the target's script is a rewrite,
    and one mixing the two while sharing nothing is about something else.
    """
    source_has_han = any("一" <= char <= "鿿" for char in source_text or "")
    output_has_han = any("一" <= char <= "鿿" for char in output or "")
    return source_has_han == output_has_han


def discard_from_cache(engine, prompt_text: str) -> bool:
    """Forget one refused reply, so the next run asks rather than repeats.

    ``False`` where there was no cache to forget it from, which is the case in
    every fixture and in any run whose engine keeps none. Never raises: a cache
    that cannot be cleaned is a warm run that repeats a question, not a run
    that fails.
    """
    cache = getattr(engine, "cache", None)
    discard = getattr(cache, "discard", None)
    if not callable(discard):
        return False
    try:
        return bool(discard(prompt_text))
    except Exception:  # noqa: BLE001 - a cache is never a reason to stop
        logger.debug("retry guard: a refused reply could not be uncached")
        return False
