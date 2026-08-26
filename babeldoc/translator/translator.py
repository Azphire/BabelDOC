import contextlib
import hashlib
import logging
import threading
import time
import unicodedata
from abc import ABC
from abc import abstractmethod
from collections.abc import Mapping

import httpx
import openai
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from babeldoc.babeldoc_exception.BabelDOCException import ContentFilterError
from babeldoc.translator.cache import TranslationCache
from babeldoc.translator.tool_call import ToolCallCapability
from babeldoc.translator.tool_call import ToolCallLimits
from babeldoc.translator.tool_call import ToolCallProtocolError
from babeldoc.translator.tool_call import ToolCallResult
from babeldoc.translator.tool_call import ToolCallSchemaError
from babeldoc.translator.tool_call import ToolCallsUnsupported
from babeldoc.translator.tool_call import ToolCallTransientError
from babeldoc.translator.tool_call import ToolCallTransportError
from babeldoc.translator.tool_call import decode_arguments
from babeldoc.translator.tool_call import digest_json
from babeldoc.translator.tool_call import endpoint_identity
from babeldoc.translator.tool_call import resolve_tool_call_capability
from babeldoc.translator.tool_call import tool_call_cache_key
from babeldoc.translator.tool_call import validate_resource_limits
from babeldoc.translator.tool_call import validate_schema
from babeldoc.translator.tool_call import validate_state_binding
from babeldoc.utils.atomic_integer import AtomicInteger

logger = logging.getLogger(__name__)


def _safe_cache_log(event: str, text: object, exc: Exception, result=None) -> None:
    encoded = "" if text is None else str(text)
    fields = {
        "event": event,
        "request_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "request_chars": len(encoded),
        "exception": type(exc).__name__,
    }
    if result is not None:
        fields["result_chars"] = len(str(result))
    logger.debug("translator cache event %s", fields)


def remove_control_characters(s):
    return "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")


class RateLimiter:
    """
    A rate limiter using the leaky bucket algorithm to ensure a smooth, constant rate of requests.
    This implementation is thread-safe and robust against system clock changes.
    """

    def __init__(self, max_qps: int):
        if max_qps <= 0:
            raise ValueError("max_qps must be a positive number")
        self.max_qps = max_qps
        self.min_interval = 1.0 / max_qps
        self.lock = threading.Lock()
        # Use monotonic time to prevent issues with system time changes
        self.next_request_time = time.monotonic()

    def wait(self, _rate_limit_params: dict = None):
        """
        Blocks until the next request can be processed, ensuring the rate limit is not exceeded.
        """
        with self.lock:
            now = time.monotonic()

            wait_duration = self.next_request_time - now
            if wait_duration > 0:
                time.sleep(wait_duration)

            # Update the next allowed request time.
            # If the limiter has been idle, the next request should start from 'now'.
            now = time.monotonic()
            self.next_request_time = (
                max(self.next_request_time, now) + self.min_interval
            )

    def set_max_qps(self, max_qps: int):
        """
        Updates the maximum queries per second. This operation is thread-safe.
        """
        if max_qps <= 0:
            raise ValueError("max_qps must be a positive number")
        with self.lock:
            self.max_qps = max_qps
            self.min_interval = 1.0 / max_qps


_translate_rate_limiter = RateLimiter(5)


def set_translate_rate_limiter(max_qps):
    _translate_rate_limiter.set_max_qps(max_qps)


class BaseTranslator(ABC):
    # Due to cache limitations, name should be within 20 characters.
    # cache.py: translate_engine = CharField(max_length=20)
    name = "base"
    lang_map = {}

    def __init__(self, lang_in, lang_out, ignore_cache):
        self.ignore_cache = ignore_cache
        lang_in = self.lang_map.get(lang_in.lower(), lang_in)
        lang_out = self.lang_map.get(lang_out.lower(), lang_out)
        self.lang_in = lang_in
        self.lang_out = lang_out

        self.cache = TranslationCache(
            self.name,
            {
                "lang_in": lang_in,
                "lang_out": lang_out,
            },
        )

        self.translate_call_count = 0
        self.translate_cache_call_count = 0

    def __del__(self):
        with contextlib.suppress(Exception):
            logger.info(
                f"{self.name} translate call count: {self.translate_call_count}"
            )
            logger.info(
                f"{self.name} translate cache call count: {self.translate_cache_call_count}",
            )

    def add_cache_impact_parameters(self, k: str, v):
        """
        Add parameters that affect the translation quality to distinguish the translation effects under different parameters.
        :param k: key
        :param v: value
        """
        self.cache.add_params(k, v)

    def translate(self, text, ignore_cache=False, rate_limit_params: dict = None):
        """
        Translate the text, and the other part should call this method.
        :param text: text to translate
        :return: translated text
        """
        self.translate_call_count += 1
        if not (self.ignore_cache or ignore_cache):
            try:
                cache = self.cache.get(text)
                if cache is not None:
                    self.translate_cache_call_count += 1
                    return cache
            except Exception as e:
                _safe_cache_log("get_failed", text, e)
        _translate_rate_limiter.wait()
        translation = self.do_translate(text, rate_limit_params)
        if not (self.ignore_cache or ignore_cache):
            self.cache.set(text, translation)
        return translation

    def llm_translate(self, text, ignore_cache=False, rate_limit_params: dict = None):
        """
        Translate the text, and the other part should call this method.
        :param text: text to translate
        :return: translated text
        """
        self.translate_call_count += 1
        if not (self.ignore_cache or ignore_cache):
            try:
                cache = self.cache.get(text)
                if cache is not None:
                    self.translate_cache_call_count += 1
                    return cache
            except Exception as e:
                _safe_cache_log("get_failed", text, e)
        _translate_rate_limiter.wait()
        translation = self.do_llm_translate(text, rate_limit_params)
        if not (self.ignore_cache or ignore_cache):
            try:
                self.cache.set(text, translation)
            except Exception as e:
                _safe_cache_log("set_failed", text, e, translation)
        return translation

    def supports_tool_calls(self) -> bool:
        """Whether this exact endpoint/model has declared strict-tool support."""
        return False

    def llm_tool_call(
        self,
        *,
        messages,
        tool_name: str,
        parameters_schema: Mapping[str, object],
        state_sha256: str,
        cache_context: Mapping[str, object],
        request_limits: Mapping[str, object] | None,
    ) -> ToolCallResult:
        del messages, tool_name, parameters_schema, state_sha256
        del cache_context, request_limits
        raise ToolCallsUnsupported(
            f"{self.name} does not support forced structured tool calls"
        )

    @abstractmethod
    def do_llm_translate(self, text, rate_limit_params: dict = None):
        """
        Actual translate text, override this method
        :param text: text to translate
        :return: translated text
        """
        raise NotImplementedError

    @abstractmethod
    def do_translate(self, text, rate_limit_params: dict = None):
        """
        Actual translate text, override this method
        :param text: text to translate
        :return: translated text
        """
        logger.critical(
            f"Do not call BaseTranslator.do_translate. "
            f"Translator: {self}. "
            f"Text: {text}. ",
        )
        raise NotImplementedError

    def __str__(self):
        return f"{self.name} {self.lang_in} {self.lang_out} {self.model}"

    def get_rich_text_left_placeholder(self, placeholder_id: int | str):
        return f"<b{placeholder_id}>"

    def get_rich_text_right_placeholder(self, placeholder_id: int | str):
        return f"</b{placeholder_id}>"

    def get_formular_placeholder(self, placeholder_id: int | str):
        return self.get_rich_text_left_placeholder(placeholder_id)


class OpenAITranslator(BaseTranslator):
    # https://github.com/openai/openai-python
    name = "openai"

    def __init__(
        self,
        lang_in,
        lang_out,
        model,
        base_url=None,
        api_key=None,
        ignore_cache=False,
        enable_json_mode_if_requested=False,
        send_dashscope_header=False,
        send_temperature=True,
        reasoning=None,
        thinking=None,
        tool_call_capability: Mapping[str, object] | ToolCallCapability | None = None,
    ):
        super().__init__(lang_in, lang_out, ignore_cache)
        self.options = {"temperature": 0}  # 随机采样可能会打断公式标记
        self.extra_body = {}
        # if 'gpt-5' in model and 'gpt-5-chat' not in model:
        #     self.extra_body['reasoning'] = {
        #         "effort": "minimal"
        #     }
        #     self.add_cache_impact_parameters("reasoning-effort", 'minimal')
        self.reasoning = reasoning
        self.base_url_identity = endpoint_identity(base_url)
        self.tool_call_capability = resolve_tool_call_capability(
            base_url,
            model,
            tool_call_capability,
        )
        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            http_client=httpx.Client(
                limits=httpx.Limits(
                    max_connections=None, max_keepalive_connections=None
                ),
                timeout=600,
            ),
        )
        if send_temperature:
            self.add_cache_impact_parameters("temperature", self.options["temperature"])
        self.model = model
        self.enable_json_mode_if_requested = enable_json_mode_if_requested
        self.send_dashscope_header = send_dashscope_header
        self.send_temperature = send_temperature
        self.add_cache_impact_parameters("model", self.model)
        self.add_cache_impact_parameters("prompt", self.prompt(""))
        if self.reasoning:
            self.extra_body["reasoning"] = {"effort": self.reasoning}
            self.add_cache_impact_parameters("reasoning", self.reasoning)
        self.thinking = thinking
        if self.thinking:
            # DeepSeek-style thinking switch: {"type": "enabled"|"disabled"}
            self.extra_body["thinking"] = {"type": self.thinking}
            self.add_cache_impact_parameters("thinking", self.thinking)
        if self.enable_json_mode_if_requested:
            self.add_cache_impact_parameters(
                "enable_json_mode_if_requested", self.enable_json_mode_if_requested
            )
        self.token_count = AtomicInteger()
        self.prompt_token_count = AtomicInteger()
        self.completion_token_count = AtomicInteger()
        self.cache_hit_prompt_token_count = AtomicInteger()
        self.tool_call_count = 0
        self.tool_call_cache_hit_count = 0
        self.tool_call_attempt_count = 0
        # Imported only where an OpenAI transport is actually built.  Several
        # offline layout gates install a minimal TranslationCache protocol
        # module while importing BaseTranslator, and must not need tool-cache
        # production dependencies merely to exercise non-transport code.
        from babeldoc.translator.cache import ToolCallCache

        self.tool_call_cache = ToolCallCache(
            self.name, self.base_url_identity, self.model
        )

    def supports_tool_calls(self) -> bool:
        return bool(
            self.tool_call_capability
            and self.tool_call_capability.supports(
                self.base_url_identity,
                self.model,
            )
        )

    @staticmethod
    def _member(value, name: str, default=None):
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    @staticmethod
    def _is_transient_tool_error(exc: Exception) -> bool:
        provider_types = tuple(
            candidate
            for candidate in (
                getattr(openai, "RateLimitError", None),
                getattr(openai, "APIConnectionError", None),
                getattr(openai, "APITimeoutError", None),
                getattr(openai, "InternalServerError", None),
            )
            if isinstance(candidate, type)
        )
        return isinstance(exc, (ToolCallTransientError, *provider_types))

    def _parse_tool_response(
        self,
        response,
        *,
        tool_name: str,
        parameters_schema: Mapping[str, object],
        state_sha256: str,
        limits: ToolCallLimits,
    ) -> ToolCallResult:
        choices = self._member(response, "choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ToolCallProtocolError("provider must return exactly one choice")
        choice = choices[0]
        finish_reason = self._member(choice, "finish_reason")
        if finish_reason != "tool_calls":
            raise ToolCallProtocolError("provider did not finish with tool_calls")
        message = self._member(choice, "message")
        if message is None:
            raise ToolCallProtocolError("provider choice has no message")
        refusal = self._member(message, "refusal")
        if refusal:
            raise ToolCallProtocolError("provider refused the forced tool call")
        calls = self._member(message, "tool_calls")
        if not isinstance(calls, list) or len(calls) != 1:
            raise ToolCallProtocolError("provider must return exactly one tool call")
        call = calls[0]
        if self._member(call, "type") != "function":
            raise ToolCallProtocolError("provider returned the wrong tool-call type")
        function = self._member(call, "function")
        if function is None or self._member(function, "name") != tool_name:
            raise ToolCallProtocolError("provider returned the wrong tool name")
        arguments = decode_arguments(self._member(function, "arguments"), limits)
        validate_schema(arguments, parameters_schema)
        validate_state_binding(arguments, state_sha256)
        call_id = self._member(call, "id")
        if call_id is not None and not isinstance(call_id, str):
            raise ToolCallProtocolError("provider call id has the wrong type")
        return ToolCallResult(
            tool_name=tool_name,
            arguments=arguments,
            provider_call_id=call_id,
            finish_reason=finish_reason,
        )

    def llm_tool_call(
        self,
        *,
        messages,
        tool_name: str,
        parameters_schema: Mapping[str, object],
        state_sha256: str,
        cache_context: Mapping[str, object],
        request_limits: Mapping[str, object] | None,
    ) -> ToolCallResult:
        if not self.supports_tool_calls():
            raise ToolCallsUnsupported(
                "strict tool calls were not declared for this endpoint and model"
            )
        if not isinstance(tool_name, str) or not tool_name:
            raise ToolCallProtocolError("tool_name must be a non-empty string")
        if not isinstance(parameters_schema, Mapping):
            raise ToolCallProtocolError("parameters_schema must be an object")
        if not isinstance(cache_context, Mapping):
            raise ToolCallProtocolError("cache_context must be an object")
        # Canonicalisation validates these inputs before a cache or provider is
        # touched, and prevents provider identifiers from entering semantics.
        digest_json(messages)
        digest_json(parameters_schema)
        digest_json(cache_context)
        limits = ToolCallLimits.from_mapping(request_limits)
        output_parameters = {
            "temperature": self.options.get("temperature")
            if self.send_temperature
            else None,
            "reasoning": self.reasoning,
            "thinking": self.thinking,
            "max_tokens": 2048,
        }
        key = tool_call_cache_key(
            endpoint=self.base_url_identity,
            model=self.model,
            output_parameters=output_parameters,
            messages=messages,
            tool_name=tool_name,
            parameters_schema=parameters_schema,
            state_sha256=state_sha256,
            cache_context=cache_context,
            limits=limits,
        )
        self.tool_call_count += 1
        if not self.ignore_cache:
            try:
                cached = self.tool_call_cache.get(key)
            except Exception as exc:  # cache failure is a miss, never a bypass
                logger.debug(
                    "tool-call cache get failed %s",
                    {"cache_key": key, "exception": type(exc).__name__},
                )
            else:
                if cached is not None:
                    if cached["tool_name"] != tool_name:
                        raise ToolCallSchemaError(
                            "cached tool name does not match the forced tool"
                        )
                    arguments = dict(cached["arguments"])
                    validate_resource_limits(arguments, limits)
                    validate_schema(arguments, parameters_schema)
                    validate_state_binding(arguments, state_sha256)
                    self.tool_call_cache_hit_count += 1
                    return ToolCallResult(
                        tool_name=tool_name,
                        arguments=arguments,
                        provider_call_id=None,
                        finish_reason=cached["finish_reason"],
                    )

        request_digest = digest_json(
            {
                "cache_key": key,
                "tool_name": tool_name,
                "schema_sha256": digest_json(parameters_schema),
                "state_sha256": state_sha256,
            }
        )
        request = {
            "model": self.model,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "parameters": dict(parameters_schema),
                        "strict": True,
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": tool_name},
            },
            "max_tokens": 2048,
            "extra_body": self.extra_body,
            "timeout": limits.attempt_timeout_seconds,
        }
        if self.send_temperature:
            request.update(self.options)

        last_exc: Exception | None = None
        for attempt in range(1, limits.max_attempts + 1):
            self.tool_call_attempt_count += 1
            try:
                response = self.client.chat.completions.create(**request)
            except Exception as exc:  # provider libraries expose several subclasses
                last_exc = exc
                if not self._is_transient_tool_error(exc):
                    logger.warning(
                        "tool-call provider error %s",
                        {
                            "request_sha256": request_digest,
                            "attempt": attempt,
                            "exception": type(exc).__name__,
                        },
                    )
                    raise ToolCallTransportError(
                        f"non-transient tool-call transport error: {type(exc).__name__}"
                    ) from exc
                logger.warning(
                    "tool-call transient retry %s",
                    {
                        "request_sha256": request_digest,
                        "attempt": attempt,
                        "exception": type(exc).__name__,
                    },
                )
                if attempt == limits.max_attempts:
                    break
                continue
            try:
                result = self._parse_tool_response(
                    response,
                    tool_name=tool_name,
                    parameters_schema=parameters_schema,
                    state_sha256=state_sha256,
                    limits=limits,
                )
            except (ToolCallProtocolError, ToolCallSchemaError) as exc:
                logger.warning(
                    "tool-call response rejected %s",
                    {
                        "request_sha256": request_digest,
                        "attempt": attempt,
                        "reason": type(exc).__name__,
                    },
                )
                raise
            self.update_token_count(response)
            if not self.ignore_cache:
                try:
                    self.tool_call_cache.set(
                        key,
                        tool_name=result.tool_name,
                        arguments=dict(result.arguments),
                        finish_reason=result.finish_reason,
                        attempts=attempt,
                    )
                except Exception as exc:
                    logger.debug(
                        "tool-call cache set failed %s",
                        {"cache_key": key, "exception": type(exc).__name__},
                    )
            return result
        assert last_exc is not None
        raise ToolCallTransportError(
            f"tool-call transport exhausted {limits.max_attempts} attempts: "
            f"{type(last_exc).__name__}"
        ) from last_exc

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(100),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None) -> str:
        options = {}
        if self.send_temperature:
            options.update(self.options)

        response = self.client.chat.completions.create(
            model=self.model,
            **options,
            messages=self.prompt(text),
            extra_body=self.extra_body,
        )
        self.update_token_count(response)
        return response.choices[0].message.content.strip()

    def prompt(self, text):
        return [
            {
                "role": "system",
                "content": "You are a professional,authentic machine translation engine.",
            },
            {
                "role": "user",
                "content": f";; Treat next line as plain text input and translate it into {self.lang_out}, output translation ONLY. If translation is unnecessary (e.g. proper nouns, codes, {'{{1}}, etc. '}), return the original text. NO explanations. NO notes. Input:\n\n{text}",
            },
        ]

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(100),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_llm_translate(self, text, rate_limit_params: dict = None):
        if text is None:
            return None

        options = {}
        if self.send_temperature:
            options.update(self.options)
        if self.enable_json_mode_if_requested and (rate_limit_params or {}).get(
            "request_json_mode", False
        ):
            options["response_format"] = {"type": "json_object"}

        extra_headers = {}
        if self.send_dashscope_header:
            extra_headers["X-DashScope-DataInspection"] = (
                '{"input": "disable", "output": "disable"}'
            )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                **options,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": text,
                    },
                ],
                extra_headers=extra_headers,
                extra_body=self.extra_body,
            )
            self.update_token_count(response)
            return response.choices[0].message.content.strip()
        except openai.BadRequestError as e:
            if (
                "系统检测到输入或生成内容可能包含不安全或敏感内容，请您避免输入易产生敏感内容的提示语，感谢您的配合。"
                in e.message
            ):
                raise ContentFilterError(e.message) from e
            else:
                raise

    def update_token_count(self, response):
        try:
            if response.usage and response.usage.total_tokens:
                self.token_count.inc(response.usage.total_tokens)
            if response.usage and response.usage.prompt_tokens:
                self.prompt_token_count.inc(response.usage.prompt_tokens)
            if response.usage and response.usage.completion_tokens:
                self.completion_token_count.inc(response.usage.completion_tokens)
            # Support both response.usage.prompt_cache_hit_tokens and response.prompt_tokens_details.cached_tokens
            hit_count = 0
            if response.usage and hasattr(response.usage, "prompt_cache_hit_tokens"):
                hit_count = getattr(response.usage, "prompt_cache_hit_tokens", 0)
            if hasattr(response, "prompt_tokens_details") and getattr(
                response.prompt_tokens_details, "cached_tokens", 0
            ):
                hit_count += getattr(response.prompt_tokens_details, "cached_tokens", 0)
            if hit_count:
                self.cache_hit_prompt_token_count.inc(hit_count)
        except Exception as e:
            logger.exception("Error updating token count")

    def get_formular_placeholder(self, placeholder_id: int | str):
        return "{v" + str(placeholder_id) + "}", f"{{\\s*v\\s*{placeholder_id}\\s*}}"
        return "{{" + str(placeholder_id) + "}}"

    def get_rich_text_left_placeholder(self, placeholder_id: int | str):
        return (
            f"<style id='{placeholder_id}'>",
            f"<\\s*style\\s*id\\s*=\\s*'\\s*{placeholder_id}\\s*'\\s*>",
        )

    def get_rich_text_right_placeholder(self, placeholder_id: int | str):
        return "</style>", r"<\s*\/\s*style\s*>"
