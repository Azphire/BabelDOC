"""One bounded retry for a unit whose translation echoed in the wrong script.

The identity pasteback keeps an unchanged translation as source furniture,
which is right for a brand, an acronym or a URL and wrong for a personal name
or a role title the model simply declined to render (FD's masthead names came
back as themselves). This module decides whether one echoed unit earns a
second, explicit ask -- transliterate a name, translate a title, keep what
genuinely stands -- and runs it within a per-document budget. A retry that
still echoes changes nothing and is recorded, so the floor stays at today's
behavior.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import weakref
from pathlib import Path

from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.prompt_loader import PromptError
from babeldoc.magazine.prompt_loader import load_prompt
from babeldoc.magazine.resource_paths import config_path

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("echo_retry.json")

SWITCH = "magazine_echo_retry"
PROMPT_NAME = "echo_retry"

# Outcomes, one per way an attempt can end. "accepted" is the only one that
# changes the page; every other name explains a kept pasteback.
ACCEPTED = "accepted"
EXHAUSTED = "echo_retry_exhausted"
SKIP_SWITCH = "switch_off"
SKIP_SCRIPT = "not_wrong_script"
SKIP_LENGTH = "over_max_chars"
SKIP_BUDGET = "budget_exhausted"
SKIP_ENGINE = "engine_unsupported"
UNUSABLE = "reply_unusable"

_spent: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def load_echo_retry_config() -> dict:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    flat = {key: value for key, value in raw.items() if key != "switch"}
    return dict(validate_bounded_config(flat, CONFIG_PATH))


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def normalized(text: str) -> str:
    """The same normal form the identity pasteback compares under."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def _script_counts(text: str) -> tuple[int, int]:
    han = sum(1 for char in text if "㐀" <= char <= "鿿")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    return han, latin


def wrong_script(text: str, lang_out: str) -> bool:
    """Whether the unit's body is the script the target should have replaced.

    Into a CJK target, a Latin-dominant unit went untranslated; into a Latin
    target, a Han-dominant one did. Anything else -- mixed, digits, symbols,
    or already in the target script -- is not this defect and earns no retry.
    """
    han, latin = _script_counts(text)
    tag = (lang_out or "").strip().lower()
    if tag.startswith("zh"):
        return latin > han and latin >= 2
    if tag.startswith("en"):
        return han > latin and han >= 2
    return False


def _parse_reply(reply: str) -> str | None:
    match = _JSON_OBJECT.search(reply or "")
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return None
    output = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(output, str) or not output.strip():
        return None
    return output.strip()


def _within_length(source_text: str, line_lengths, max_chars: int) -> bool:
    """Whether the unit is short enough to earn a retry.

    A unit fits either as a whole or line by line: a masthead column that
    stacks a dozen short names is one unit whose total passes the cap while
    every visual line sits far under it, and the length cap exists to keep a
    retry from re-asking an essay, not to protect a list from being fixed.
    A single visual line is judged as the whole it is.
    """
    if len(source_text) <= max_chars:
        return True
    lengths = [int(item) for item in (line_lengths or ()) if int(item) > 0]
    return len(lengths) >= 2 and all(item <= max_chars for item in lengths)


def attempt(
    translation_config,
    engine,
    source_text: str,
    line_lengths=None,
) -> tuple[str | None, str]:
    """One retry for one echoed unit: (accepted text or None, outcome name).

    ``line_lengths`` are the character counts of the unit's visual lines as
    the source page sets them, which is what lets a multi-line list qualify
    by its lines while a single long line stays refused.
    """
    if not enabled(translation_config):
        return None, SKIP_SWITCH
    parameters = load_echo_retry_config()
    if not _within_length(
        source_text, line_lengths, int(parameters["echo_retry_max_chars"])
    ):
        return None, SKIP_LENGTH
    lang_out = getattr(translation_config, "lang_out", "") or ""
    if not wrong_script(source_text, lang_out):
        return None, SKIP_SCRIPT
    llm_translate = getattr(engine, "llm_translate", None)
    if not callable(llm_translate):
        return None, SKIP_ENGINE
    spent = int(_spent.get(translation_config, 0))
    if spent >= int(parameters["echo_retry_budget"]):
        return None, SKIP_BUDGET
    _spent[translation_config] = spent + 1
    try:
        prompt = load_prompt(
            PROMPT_NAME,
            {"target_language": lang_out, "unit": source_text},
            working_dir=_working_dir(translation_config),
        )
    except PromptError as error:
        logger.warning("echo retry prompt unavailable: %s", error)
        return None, UNUSABLE
    try:
        reply = llm_translate(prompt.text, rate_limit_params={})
    except Exception:
        logger.warning("echo retry request failed", exc_info=True)
        return None, UNUSABLE
    output = _parse_reply(reply)
    if output is None:
        return None, UNUSABLE
    if normalized(output) == normalized(source_text):
        return None, EXHAUSTED
    return output, ACCEPTED


def _working_dir(translation_config) -> Path | None:
    getter = getattr(translation_config, "get_working_file_path", None)
    if not callable(getter):
        return None
    try:
        return Path(getter("prompts.manifest.json")).parent
    except Exception:
        return None
