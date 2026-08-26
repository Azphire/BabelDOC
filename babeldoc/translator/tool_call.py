"""Fail-closed primitives for forced, structured translator tool calls.

This module deliberately knows nothing about the repair controller.  It owns
the provider wire contract: bounded requests, canonical cache keys, strict JSON
decoding and the small JSON-Schema subset accepted by the transport.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

TOOL_CALL_PROTOCOL_VERSION = "forced-tool-call.v1"
TOOL_CALL_CACHE_VERSION = 1
TOOL_CALL_CAPABILITY_VERSION = "strict-tool-capabilities.v1"
OFFICIAL_OPENAI_ENDPOINT = "https://api.openai.com/v1"
_OPENAI_STRICT_TOOL_MODEL_PREFIXES = ("gpt-4o", "gpt-4.1", "gpt-5")


class ToolCallError(RuntimeError):
    """Base class for typed tool-call failures."""


class ToolCallsUnsupported(ToolCallError):  # noqa: N818 - frozen public API name
    """The selected transport has no explicitly declared strict-tool support."""


class ToolCallProtocolError(ToolCallError):
    """The provider response did not satisfy the forced-call protocol."""


class ToolCallSchemaError(ToolCallError):
    """Arguments were not strict JSON or did not satisfy the supplied schema."""


class ToolCallTransportError(ToolCallError):
    """A bounded provider request failed before a response was available."""


class ToolCallTransientError(ToolCallTransportError):
    """Test/protocol adapter signal for a retryable transport failure."""


@dataclass(frozen=True)
class ToolCallResult:
    tool_name: str
    arguments: Mapping[str, object]
    provider_call_id: str | None
    finish_reason: str | None


@dataclass(frozen=True)
class ToolCallLimits:
    attempt_timeout_seconds: float = 60.0
    max_attempts: int = 1
    max_argument_bytes: int = 16_384
    max_depth: int = 12
    max_array_items: int = 256
    max_string_chars: int = 4_096

    @classmethod
    def from_mapping(cls, supplied: Mapping[str, object] | None) -> ToolCallLimits:
        values = {} if supplied is None else dict(supplied)
        unknown = sorted(set(values) - set(cls.__dataclass_fields__))
        if unknown:
            raise ToolCallProtocolError(f"unknown request limits: {unknown}")
        try:
            limits = cls(**values)
        except (TypeError, ValueError) as exc:
            raise ToolCallProtocolError("invalid request limit types") from exc
        numeric = (
            limits.attempt_timeout_seconds,
            limits.max_attempts,
            limits.max_argument_bytes,
            limits.max_depth,
            limits.max_array_items,
            limits.max_string_chars,
        )
        if any(isinstance(value, bool) for value in numeric):
            raise ToolCallProtocolError("request limits must be numeric, not boolean")
        if not isinstance(limits.attempt_timeout_seconds, int | float) or any(
            not isinstance(value, int)
            for value in (
                limits.max_attempts,
                limits.max_argument_bytes,
                limits.max_depth,
                limits.max_array_items,
                limits.max_string_chars,
            )
        ):
            raise ToolCallProtocolError("request limits have invalid numeric types")
        if not 0 < limits.attempt_timeout_seconds <= 600:
            raise ToolCallProtocolError("attempt_timeout_seconds is outside 0..600")
        if not 1 <= limits.max_attempts <= 3:
            raise ToolCallProtocolError("max_attempts is outside 1..3")
        if not 1 <= limits.max_argument_bytes <= 1_048_576:
            raise ToolCallProtocolError("max_argument_bytes is outside 1..1048576")
        if not 1 <= limits.max_depth <= 64:
            raise ToolCallProtocolError("max_depth is outside 1..64")
        if not 1 <= limits.max_array_items <= 10_000:
            raise ToolCallProtocolError("max_array_items is outside 1..10000")
        if not 1 <= limits.max_string_chars <= 1_000_000:
            raise ToolCallProtocolError("max_string_chars is outside 1..1000000")
        return limits

    def as_record(self) -> dict[str, int | float]:
        return {
            "attempt_timeout_seconds": self.attempt_timeout_seconds,
            "max_attempts": self.max_attempts,
            "max_argument_bytes": self.max_argument_bytes,
            "max_depth": self.max_depth,
            "max_array_items": self.max_array_items,
            "max_string_chars": self.max_string_chars,
        }


@dataclass(frozen=True)
class ToolCallCapability:
    endpoint_identity: str
    models: tuple[str, ...]
    strict: bool
    declaration: str = "explicit"
    version: str = TOOL_CALL_CAPABILITY_VERSION

    @classmethod
    def from_mapping(
        cls, supplied: Mapping[str, object] | ToolCallCapability | None
    ) -> ToolCallCapability | None:
        if supplied is None or isinstance(supplied, cls):
            return supplied
        if set(supplied) != {"endpoint_identity", "models", "strict"}:
            raise ToolCallProtocolError(
                "tool-call capability requires endpoint_identity, models and strict"
            )
        models = supplied["models"]
        if not isinstance(models, list | tuple) or not all(
            isinstance(model, str) and model for model in models
        ):
            raise ToolCallProtocolError("tool-call capability models are invalid")
        strict = supplied["strict"]
        if not isinstance(strict, bool):
            raise ToolCallProtocolError("tool-call capability strict must be boolean")
        return cls(
            endpoint_identity=endpoint_identity(str(supplied["endpoint_identity"])),
            models=tuple(models),
            strict=strict,
            declaration="explicit",
        )

    def supports(self, endpoint: str, model: str) -> bool:
        return (
            self.strict
            and self.endpoint_identity == endpoint_identity(endpoint)
            and model in self.models
        )

    def as_record(self, endpoint: str, model: str) -> dict[str, object]:
        return {
            "version": self.version,
            "supported": self.supports(endpoint, model),
            "strict": self.strict,
            "declaration": self.declaration,
            "endpoint_identity": endpoint_identity(endpoint),
            "model": model,
        }


def endpoint_identity(value: str | None) -> str:
    """Return a stable endpoint identity without query, fragment or userinfo."""
    raw = value or "https://api.openai.com/v1"
    parsed = urlsplit(raw)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), netloc.lower(), path, "", ""))


def resolve_tool_call_capability(
    endpoint: str | None,
    model: str,
    supplied: Mapping[str, object] | ToolCallCapability | None = None,
) -> ToolCallCapability | None:
    """Resolve a versioned declaration for one exact endpoint/model pair.

    The official OpenAI endpoint has a narrow built-in declaration for model
    families whose Chat Completions contract supports strict function tools.
    Compatible/custom endpoints never inherit that declaration: they remain
    unsupported unless the operator explicitly opts in for their exact URL and
    model.
    """
    explicit = ToolCallCapability.from_mapping(supplied)
    if explicit is not None:
        return explicit
    identity = endpoint_identity(endpoint)
    if identity != endpoint_identity(OFFICIAL_OPENAI_ENDPOINT):
        return None
    if not any(
        model == prefix or model.startswith(f"{prefix}-")
        for prefix in _OPENAI_STRICT_TOOL_MODEL_PREFIXES
    ):
        return None
    return ToolCallCapability(
        endpoint_identity=identity,
        models=(model,),
        strict=True,
        declaration="builtin_openai",
    )


def tool_call_capability_record(
    endpoint: str | None,
    model: str,
    supplied: Mapping[str, object] | ToolCallCapability | None = None,
) -> dict[str, object]:
    capability = resolve_tool_call_capability(endpoint, model, supplied)
    if capability is None:
        return {
            "version": TOOL_CALL_CAPABILITY_VERSION,
            "supported": False,
            "strict": False,
            "declaration": "none",
            "endpoint_identity": endpoint_identity(endpoint),
            "model": model,
        }
    return capability.as_record(endpoint or OFFICIAL_OPENAI_ENDPOINT, model)


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ToolCallProtocolError("value is not canonical JSON") from exc


def digest_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def tool_call_cache_key(
    *,
    endpoint: str,
    model: str,
    output_parameters: Mapping[str, object],
    messages: object,
    tool_name: str,
    parameters_schema: Mapping[str, object],
    state_sha256: str,
    cache_context: Mapping[str, object],
    limits: ToolCallLimits,
) -> str:
    material = {
        "protocol_version": TOOL_CALL_PROTOCOL_VERSION,
        "cache_version": TOOL_CALL_CACHE_VERSION,
        "endpoint_identity": endpoint_identity(endpoint),
        "model": model,
        "output_parameters": dict(output_parameters),
        "messages_sha256": digest_json(messages),
        "tool_name": tool_name,
        "schema_sha256": digest_json(parameters_schema),
        "state_sha256": state_sha256,
        "cache_context": dict(cache_context),
        "request_limits": limits.as_record(),
    }
    return digest_json(material)


def _reject_duplicate(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ToolCallSchemaError(f"duplicate JSON key at {key!r}")
        result[key] = value
    return result


def decode_arguments(raw: object, limits: ToolCallLimits) -> dict[str, object]:
    if not isinstance(raw, str):
        raise ToolCallSchemaError("tool arguments must be a JSON string")
    if len(raw.encode("utf-8")) > limits.max_argument_bytes:
        raise ToolCallSchemaError("tool arguments exceed max_argument_bytes")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ToolCallSchemaError(f"non-finite JSON constant {constant}")
            ),
        )
    except ToolCallSchemaError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ToolCallSchemaError("tool arguments are malformed JSON") from exc
    if not isinstance(value, dict):
        raise ToolCallSchemaError("tool arguments must decode to an object")
    validate_resource_limits(value, limits)
    return value


def validate_resource_limits(
    value: object, limits: ToolCallLimits, *, depth: int = 1
) -> None:
    if depth > limits.max_depth:
        raise ToolCallSchemaError("tool arguments exceed max_depth")
    if isinstance(value, str):
        if len(value) > limits.max_string_chars:
            raise ToolCallSchemaError("tool argument string exceeds max_string_chars")
    elif isinstance(value, list):
        if len(value) > limits.max_array_items:
            raise ToolCallSchemaError("tool argument array exceeds max_array_items")
        for item in value:
            validate_resource_limits(item, limits, depth=depth + 1)
    elif isinstance(value, dict):
        if len(value) > limits.max_array_items:
            raise ToolCallSchemaError("tool argument object exceeds member limit")
        for key, item in value.items():
            if len(key) > limits.max_string_chars:
                raise ToolCallSchemaError("tool argument key exceeds max_string_chars")
            validate_resource_limits(item, limits, depth=depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ToolCallSchemaError("tool arguments contain a non-finite number")
    elif value is not None and not isinstance(value, bool | int | float):
        raise ToolCallSchemaError("tool arguments contain a non-JSON value")


def _matches_type(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ToolCallSchemaError(f"unsupported schema type {expected!r}")


def validate_schema(
    value: object, schema: Mapping[str, object], path: str = "$"
) -> None:
    """Validate the strict provider schema subset used by repair tool calls."""
    if not isinstance(schema, Mapping):
        raise ToolCallSchemaError(f"{path}: schema must be an object")
    if "anyOf" in schema:
        choices = schema["anyOf"]
        if not isinstance(choices, list) or not choices:
            raise ToolCallSchemaError(f"{path}: anyOf must be a non-empty array")
        matches = 0
        for choice in choices:
            try:
                validate_schema(value, choice, path)
            except ToolCallSchemaError:
                continue
            matches += 1
        if matches != 1:
            raise ToolCallSchemaError(f"{path}: value matches {matches} anyOf branches")
        return

    declared = schema.get("type")
    expected = declared if isinstance(declared, list) else [declared]
    if not expected or any(not isinstance(item, str) for item in expected):
        raise ToolCallSchemaError(f"{path}: schema type is missing or invalid")
    if not any(_matches_type(value, item) for item in expected):
        raise ToolCallSchemaError(f"{path}: value has the wrong type")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolCallSchemaError(f"{path}: value is outside the closed enum")

    if isinstance(value, dict):
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            raise ToolCallSchemaError(f"{path}: object schema is not strict")
        if schema.get("additionalProperties") is not False:
            raise ToolCallSchemaError(f"{path}: additionalProperties must be false")
        missing = sorted(set(required) - set(value))
        extra = sorted(set(value) - set(properties))
        if missing:
            raise ToolCallSchemaError(f"{path}: missing required properties {missing}")
        if extra:
            raise ToolCallSchemaError(f"{path}: unknown properties {extra}")
        for key, child in value.items():
            validate_schema(child, properties[key], f"{path}.{key}")
    elif isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and len(value) < minimum:
            raise ToolCallSchemaError(f"{path}: array has too few items")
        if maximum is not None and len(value) > maximum:
            raise ToolCallSchemaError(f"{path}: array has too many items")
        if schema.get("uniqueItems") and len(
            {canonical_json(item) for item in value}
        ) != len(value):
            raise ToolCallSchemaError(f"{path}: array items are not unique")
        item_schema = schema.get("items")
        if item_schema is None:
            raise ToolCallSchemaError(f"{path}: array schema omits items")
        for index, item in enumerate(value):
            validate_schema(item, item_schema, f"{path}[{index}]")
    elif isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if minimum is not None and len(value) < minimum:
            raise ToolCallSchemaError(f"{path}: string is too short")
        if maximum is not None and len(value) > maximum:
            raise ToolCallSchemaError(f"{path}: string is too long")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise ToolCallSchemaError(f"{path}: string does not match pattern")
    elif isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolCallSchemaError(f"{path}: number is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolCallSchemaError(f"{path}: number is above maximum")


def validate_state_binding(arguments: Mapping[str, object], state_sha256: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", state_sha256):
        raise ToolCallProtocolError("state_sha256 must be 64 lowercase hex")
    if arguments.get("state_sha256") != state_sha256:
        raise ToolCallSchemaError("tool arguments are not bound to the current state")
