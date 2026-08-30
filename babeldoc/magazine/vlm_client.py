"""Cached client for the vision model that adjudicates ambiguous pages.

This is the project's first model call outside the translation path, and it is
built to the same three rules the translation path already follows.

Cached. A reply is stored in the project-local database the translator cache
already uses, under an engine name of its own, keyed by everything that could
change the answer: the model, the request parameters that shape a reply, the
identity of the prompt template, the rendered prompt and the page image. Two
runs over one unchanged page therefore cost one request, and a gate can prove
it by counting calls into the transport.

Bounded. Every setting comes from ``configs/vlm.json`` with a declared range,
including the switch that decides whether any request is made at all. The
credential is not a setting: the configuration names an environment variable
and the value is read from the process environment when a request is built.
Which parameters a model will accept is a setting too: the name the token limit
travels under, and whether a temperature is sent at all, are declared rather
than assumed, so a model with a different capability profile is a configuration
to write and never a branch to add. A request the endpoint rejects is a
configuration to correct: nothing here retries under a different parameter,
because a client that quietly changed the contract would file replies produced
under one profile behind a key that claims another.

Constrained. A reply is a JSON object naming a kind from the vocabulary it was
given, and a reply that is anything else is a violation, not a result. A
violation is retried once with the previous violation stated, and a second
violation refuses the reply outright so the caller keeps its deterministic
verdict. The vocabulary is never widened by what a model returns.

Nothing here names a page type or renders a page. The vocabulary arrives from
the caller and the page image arrives as bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.prompt_loader import Prompt
from babeldoc.magazine.prompt_loader import load_prompt
from babeldoc.magazine.resource_paths import config_path
from babeldoc.translator.cache import TranslationCache

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("vlm.json")

# Engine name the cached replies are filed under, keeping them apart from the
# translated segments sharing the database.
ENGINE_NAME = "magazine_vlm"

# Bumped when the composition of the cache key changes, which retires every
# entry written under the old composition in one step.
CACHE_KEY_VERSION = 1

# Template that states a rejected reply back to the model on the retry.
RETRY_PROMPT_NAME = "vlm_retry_notice"

# Configuration keys that are not bounded numbers, and so are validated here
# rather than by the shared bounded-parameter validator.
FLAG_KEYS: tuple[str, ...] = ("enabled",)
TEXT_KEYS: tuple[str, ...] = ("model", "base_url", "api_key_env")

NUMERIC_KEYS: tuple[str, ...] = (
    "temperature",
    "max_output_tokens",
    "max_retries",
    "render_dpi",
    "timeout_seconds",
    "verdict_rows",
)

# Settings whose value is one of a closed set of names rather than a number in
# a range. The token limit reaches an OpenAI-compatible endpoint under one of
# two names, and which one a model accepts is a property of that model.
ENUM_KEYS: dict[str, tuple[str, ...]] = {
    "token_parameter": ("max_tokens", "max_completion_tokens"),
    "image_detail": ("auto", "low", "high"),
}

# Numeric settings a request may leave out entirely. ``null`` means the field
# is absent from the body and the service default applies, which for some
# models is the only value they will serve. The declared range stays required:
# it bounds whatever value replaces the null.
NULLABLE_NUMERIC_KEYS: tuple[str, ...] = ("temperature",)

# Request parameters that shape a reply, and therefore belong in the cache key.
# The endpoint, the credential's variable name, the wall clock limit and the
# retry budget are how a request is delivered, not what it asks for. Settings
# that reach the model through the words of the prompt -- ``verdict_rows`` among
# them -- are already in the key through the rendered text and are not repeated
# here, and ``render_dpi`` is in it through the bytes of the image.
KEY_PARAMETERS: tuple[str, ...] = (
    "temperature",
    "max_output_tokens",
    "token_parameter",
    "image_detail",
)

# What a stored reply was already produced under, for parameters the key did
# not name at the time it was written. A setting sitting at its implied value
# carries no information the stored keys do not already encode, so it is left
# out of the key and the replies written under it stay valid; any other value
# is written in, and retires only the requests that departed. This is how a
# capability can be declared without discarding replies already paid for.
IMPLIED_PARAMETERS: dict[str, object] = {"token_parameter": "max_tokens"}

# Fields a reply must carry. Anything else in the object is ignored; anything
# missing from this set makes the reply unusable.
REQUIRED_REPLY_FIELDS = ("kind", "confidence")

# Documentation key every configuration file in this project carries.
DESCRIPTION_KEY = "description"

_RANGE_SUFFIX = "_allowed_range"

# One code fence wrapping the whole reply, opened bare or tagged as JSON and
# closed at the very end. Chat models emit this shape even when told not to, and
# it changes nothing about the answer inside it, so it is peeled off rather than
# refused. The match is anchored at both ends and the tag set is closed: a reply
# with prose around the fence, a second fence, or any other tag is a reply that
# did not do as it was asked, and stays a violation.
_FENCED = re.compile(r"\A```(?:json)?[ \t]*\r?\n(?P<body>.*)\r?\n?```\Z", re.DOTALL)


class VlmError(ConfigError):
    """Raised when the vision model configuration or transport is unusable."""


@dataclass(frozen=True)
class VlmConfig:
    enabled: bool
    model: str
    base_url: str
    api_key_env: str
    temperature: float | None
    max_output_tokens: int
    max_retries: int
    render_dpi: int
    timeout_seconds: float
    verdict_rows: int
    token_parameter: str
    image_detail: str

    def key_parameters(self) -> dict[str, object]:
        """The request parameters the cache key is composed from."""
        return {
            name: getattr(self, name)
            for name in KEY_PARAMETERS
            if name not in IMPLIED_PARAMETERS
            or getattr(self, name) != IMPLIED_PARAMETERS[name]
        }


@dataclass(frozen=True)
class VlmVerdict:
    """Outcome of one adjudication, accepted or refused.

    A refusal is a result like any other: it carries why it was refused so the
    caller can record the reason beside the deterministic verdict it keeps.
    """

    accepted: bool
    kind: str | None = None
    confidence: float | None = None
    secondary_kind: str | None = None
    secondary_reason: str | None = None
    reason: str = ""
    attempts: int = 0
    from_cache: bool = False


class Transport(Protocol):
    """How a rendered prompt and a page image reach a model."""

    def complete(self, config: VlmConfig, prompt: str, image_png: bytes) -> str:
        """Return the model's reply text, or raise if the request fails."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VlmError(message)


def parse_vlm_config(raw: dict, source: str) -> VlmConfig:
    """Validate a decoded ``vlm.json`` and build its object model."""
    _require(isinstance(raw, dict), f"{source}: root must be an object")
    # The key set is closed rather than merely validated. An undeclared key is
    # the shape a planted credential would take, and a closed set refuses it
    # without having to guess at what a credential is named.
    declared = {
        DESCRIPTION_KEY,
        *FLAG_KEYS,
        *TEXT_KEYS,
        *ENUM_KEYS,
        *NUMERIC_KEYS,
        *(f"{key}{_RANGE_SUFFIX}" for key in NUMERIC_KEYS),
    }
    unknown = sorted(set(raw) - declared)
    _require(
        not unknown,
        f"{source}: undeclared keys {unknown}; this file holds the declared "
        f"settings only and never a credential, which is read from the "
        f"environment variable it names",
    )

    for key in (*FLAG_KEYS, *TEXT_KEYS, *ENUM_KEYS, *NUMERIC_KEYS):
        _require(key in raw, f"{source}: missing key {key!r}")
    for key in FLAG_KEYS:
        _require(isinstance(raw[key], bool), f"{source}: {key} must be a boolean")
    for key in TEXT_KEYS:
        _require(
            isinstance(raw[key], str) and raw[key],
            f"{source}: {key} must be a non-empty string",
        )
    for key, choices in ENUM_KEYS.items():
        _require(
            raw[key] in choices,
            f"{source}: {key} must be one of {list(choices)}, not {raw[key]!r}",
        )

    bounded = {
        key: value
        for key, value in raw.items()
        if key not in FLAG_KEYS and key not in TEXT_KEYS and key not in ENUM_KEYS
    }
    # A nullable setting at ``null`` is not sent, so there is no value for the
    # shared validator to bound; its range declaration is still required, and
    # is parsed by that validator as soon as a value takes the null's place.
    omitted = tuple(key for key in NULLABLE_NUMERIC_KEYS if bounded.get(key) is None)
    for key in omitted:
        _require(
            f"{key}{_RANGE_SUFFIX}" in raw, f"{source}: {key} has no {_RANGE_SUFFIX}"
        )
        bounded.pop(key)
        bounded.pop(f"{key}{_RANGE_SUFFIX}")

    parameters = validate_bounded_config(bounded, Path(source))
    missing = sorted(set(NUMERIC_KEYS) - set(parameters) - set(omitted))
    _require(not missing, f"{source}: missing bounded parameters {missing}")

    temperature = parameters.get("temperature")
    return VlmConfig(
        enabled=raw["enabled"],
        model=raw["model"],
        base_url=raw["base_url"],
        api_key_env=raw["api_key_env"],
        temperature=None if temperature is None else float(temperature),
        max_output_tokens=int(parameters["max_output_tokens"]),
        max_retries=int(parameters["max_retries"]),
        render_dpi=int(parameters["render_dpi"]),
        timeout_seconds=float(parameters["timeout_seconds"]),
        verdict_rows=int(parameters["verdict_rows"]),
        token_parameter=raw["token_parameter"],
        image_detail=raw["image_detail"],
    )


@lru_cache(maxsize=1)
def load_vlm_config(path: str | None = None) -> VlmConfig:
    """Load and validate ``configs/vlm.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_vlm_config(raw, config_path.name)


def cache_key(config: VlmConfig, prompt: Prompt, image_png: bytes) -> str:
    """Digest of everything that could change the reply to one request.

    ``render_dpi`` enters through the image bytes rather than by name: two
    resolutions of one page are two different images and cannot collide.
    """
    fields = (
        f"cache_key_version={CACHE_KEY_VERSION}",
        f"model={config.model}",
        "params="
        + json.dumps(config.key_parameters(), sort_keys=True, separators=(",", ":")),
        f"prompt_file_sha256={prompt.digest}",
        f"prompt_text_sha256={hashlib.sha256(prompt.text.encode()).hexdigest()}",
        f"image_sha256={hashlib.sha256(image_png).hexdigest()}",
    )
    return hashlib.sha256("\n".join(fields).encode()).hexdigest()


def unfence(reply: str) -> str:
    """Strip one balanced code fence enclosing the whole reply, if there is one."""
    if not isinstance(reply, str):
        return reply
    match = _FENCED.match(reply.strip())
    return match.group("body").strip() if match else reply


def interpret_reply(reply: str, vocabulary: Sequence[str]) -> VlmVerdict:
    """Turn a reply into a verdict, refusing anything outside the contract.

    The vocabulary is closed. A name the caller did not declare is a violation
    and never a new page type, whatever the model believes it saw.
    """
    try:
        payload = json.loads(unfence(reply))
    except (json.JSONDecodeError, TypeError) as exc:
        return VlmVerdict(accepted=False, reason=f"reply is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        return VlmVerdict(
            accepted=False,
            reason=f"reply is a {type(payload).__name__}, expected a JSON object",
        )

    missing = sorted(set(REQUIRED_REPLY_FIELDS) - set(payload))
    if missing:
        return VlmVerdict(accepted=False, reason=f"reply is missing fields {missing}")

    known = tuple(vocabulary)
    kind = payload["kind"]
    if kind not in known:
        return VlmVerdict(
            accepted=False,
            reason=f"kind {kind!r} is not one of the {len(known)} declared names",
        )

    confidence = payload["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return VlmVerdict(
            accepted=False, reason=f"confidence {confidence!r} is not a number"
        )
    if not 0.0 <= float(confidence) <= 1.0:
        return VlmVerdict(
            accepted=False, reason=f"confidence {confidence} lies outside 0..1"
        )

    secondary = payload.get("secondary_kind")
    if secondary is not None and secondary not in known:
        return VlmVerdict(
            accepted=False,
            reason=f"secondary_kind {secondary!r} is not one of the declared names",
        )
    reason = payload.get("secondary_reason")
    if reason is not None and not isinstance(reason, str):
        return VlmVerdict(accepted=False, reason="secondary_reason is not a string")

    return VlmVerdict(
        accepted=True,
        kind=kind,
        confidence=float(confidence),
        secondary_kind=secondary,
        secondary_reason=reason,
    )


def build_request(config: VlmConfig, prompt: str, image_png: bytes) -> dict:
    """The chat completion body one configuration asks for.

    The token limit travels under the name the configuration declares, and a
    temperature of ``null`` is absent from the body rather than sent as a
    value: asking a model for its own default and asking it for a setting it
    refuses are different requests, and only one of them is answerable.
    """
    encoded = base64.b64encode(image_png).decode("ascii")
    body = {
        "model": config.model,
        config.token_parameter: config.max_output_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{encoded}",
                            "detail": config.image_detail,
                        },
                    },
                ],
            }
        ],
    }
    if config.temperature is not None:
        body["temperature"] = config.temperature
    return body


def read_api_key(config: VlmConfig) -> str:
    key = os.environ.get(config.api_key_env, "")
    _require(
        bool(key),
        f"environment variable {config.api_key_env} is unset; the vision "
        f"model credential is read from the environment only",
    )
    return key


def build_openai_client(config: VlmConfig):
    """The endpoint this project talks to, built from the configuration."""
    import openai

    return openai.OpenAI(
        api_key=read_api_key(config),
        base_url=config.base_url,
        timeout=config.timeout_seconds,
    )


class OpenAICompatibleTransport:
    """Chat completions over an OpenAI-compatible endpoint, image inline.

    The client is built on first use so that importing this module, or running
    with the switch off, neither reads a credential nor opens a connection.
    Which client is built is a constructor argument, so a caller can watch a
    request take the shape the configuration asks for without a credential and
    without reaching a network.
    """

    def __init__(self, client_factory: Callable[[VlmConfig], object] | None = None):
        self._client_factory = (
            build_openai_client if client_factory is None else client_factory
        )
        self._client = None
        self._built_for: str | None = None

    def _openai_client(self, config: VlmConfig):
        signature = f"{config.base_url}|{config.api_key_env}|{config.timeout_seconds}"
        if self._client is None or self._built_for != signature:
            self._client = self._client_factory(config)
            self._built_for = signature
        return self._client

    def complete(self, config: VlmConfig, prompt: str, image_png: bytes) -> str:
        response = self._openai_client(config).chat.completions.create(
            **build_request(config, prompt, image_png)
        )
        return response.choices[0].message.content or ""


class CachedVlmClient:
    """One adjudication point: cache lookup, bounded retry, closed vocabulary."""

    def __init__(
        self,
        config: VlmConfig | None = None,
        transport: Transport | None = None,
        cache: TranslationCache | None = None,
        working_dir: Path | str | None = None,
    ) -> None:
        self.config = load_vlm_config() if config is None else config
        self.transport = OpenAICompatibleTransport() if transport is None else transport
        self.cache = (
            TranslationCache(ENGINE_NAME, {"cache_key_version": CACHE_KEY_VERSION})
            if cache is None
            else cache
        )
        self.working_dir = working_dir

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def cache_key(self, prompt: Prompt, image_png: bytes) -> str:
        return cache_key(self.config, prompt, image_png)

    def _retry_prompt(self, prompt: Prompt, violation: str) -> str:
        notice = load_prompt(
            RETRY_PROMPT_NAME,
            {"violation": violation},
            working_dir=self.working_dir,
        )
        return f"{prompt.text}\n\n{notice.text}"

    def classify(
        self, prompt: Prompt, image_png: bytes, vocabulary: Sequence[str]
    ) -> VlmVerdict:
        """Adjudicate one page, from cache when the request is not new."""
        key = self.cache_key(prompt, image_png)
        stored = self.cache.get(key)
        if stored is not None:
            verdict = interpret_reply(stored, vocabulary)
            if verdict.accepted:
                return replace(verdict, attempts=0, from_cache=True)
            # A stored reply that no longer validates means the vocabulary moved
            # under it. Ask again rather than serve a reply the caller cannot use.
            logger.debug("cached reply rejected, re-requesting: %s", verdict.reason)

        text = prompt.text
        violations: list[str] = []
        attempts = 0
        while attempts <= self.config.max_retries:
            attempts += 1
            try:
                reply = self.transport.complete(self.config, text, image_png)
            except Exception as exc:  # noqa: BLE001 - any failure is a violation
                violations.append(f"request failed: {type(exc).__name__}: {exc}")
            else:
                verdict = interpret_reply(reply, vocabulary)
                if verdict.accepted:
                    self.cache.set(key, reply)
                    return replace(verdict, attempts=attempts, from_cache=False)
                violations.append(verdict.reason)
            if attempts <= self.config.max_retries:
                text = self._retry_prompt(prompt, violations[-1])

        return VlmVerdict(
            accepted=False,
            reason="; ".join(violations),
            attempts=attempts,
            from_cache=False,
        )
