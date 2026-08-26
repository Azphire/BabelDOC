"""Offline contract checks for the forced structured tool-call transport."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import logging
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from openai.types.chat import ChatCompletion

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc import main as main_module  # noqa: E402
from babeldoc.tools.executor.translator import ExecutorTranslator  # noqa: E402
from babeldoc.translator.cache import TranslationCache  # noqa: E402
from babeldoc.translator.tool_call import ToolCallLimits  # noqa: E402
from babeldoc.translator.tool_call import ToolCallProtocolError  # noqa: E402
from babeldoc.translator.tool_call import ToolCallSchemaError  # noqa: E402
from babeldoc.translator.tool_call import ToolCallsUnsupported  # noqa: E402
from babeldoc.translator.tool_call import ToolCallTransientError  # noqa: E402
from babeldoc.translator.tool_call import ToolCallTransportError  # noqa: E402
from babeldoc.translator.tool_call import tool_call_cache_key  # noqa: E402
from babeldoc.translator.translator import BaseTranslator  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from tools.validate_bounded_run_intent import RunIntentError  # noqa: E402
from tools.validate_bounded_run_intent import main as run_intent_main  # noqa: E402
from tools.validate_bounded_run_intent import validate_bound_run_intent  # noqa: E402
from tools.validate_bounded_run_intent import validate_report  # noqa: E402

STATE = "a" * 64
TOOL = "select_repair_action"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "state_sha256"],
    "properties": {
        "action": {"type": "string", "enum": ["no_action"]},
        "state_sha256": {
            "type": "string",
            "minLength": 64,
            "maxLength": 64,
            "pattern": "[0-9a-f]{64}",
        },
    },
}
VALID = {"action": "no_action", "state_sha256": STATE}
MESSAGES = [{"role": "user", "content": "bounded digest-only test request"}]
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail else ''}")


def completion(
    arguments: str | None = None,
    *,
    content: str | None = None,
    calls: int = 1,
    tool_name: str = TOOL,
    call_type: str = "function",
    finish_reason: str = "tool_calls",
    refusal: str | None = None,
) -> ChatCompletion:
    tool_calls = []
    if arguments is not None:
        tool_calls = [
            {
                "id": f"call_{index}",
                "type": call_type,
                "function": {"name": tool_name, "arguments": arguments},
            }
            for index in range(calls)
        ]
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl_offline_fixture",
            "created": 0,
            "model": "offline-model",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {
                        "role": "assistant",
                        "content": content,
                        "refusal": refusal,
                        "tool_calls": tool_calls or None,
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }
    )


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **request):
        self.calls.append(request)
        if not self.outcomes:
            raise AssertionError("fake provider received an unexpected request")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeCache:
    def __init__(self, stored=None, fail_set: Exception | None = None):
        self.stored = stored
        self.fail_set = fail_set
        self.get_keys: list[str] = []
        self.set_rows: list[tuple[str, dict]] = []

    def get(self, key):
        self.get_keys.append(key)
        return copy.deepcopy(self.stored)

    def set(self, key, **value):
        if self.fail_set:
            raise self.fail_set
        self.set_rows.append((key, copy.deepcopy(value)))
        self.stored = {
            "schema_version": 1,
            "tool_name": value["tool_name"],
            "arguments": value["arguments"],
            "finish_reason": value["finish_reason"],
            "attempts": value["attempts"],
        }


def translator(outcomes=(), *, ignore_cache=True, capability_endpoint=None):
    endpoint = "https://offline.invalid/v1"
    capability_endpoint = capability_endpoint or endpoint
    instance = OpenAITranslator(
        "en",
        "zh",
        "offline-model",
        base_url=endpoint,
        api_key="offline-placeholder-key",
        ignore_cache=ignore_cache,
        tool_call_capability={
            "endpoint_identity": capability_endpoint,
            "models": ["offline-model"],
            "strict": True,
        },
    )
    completions = FakeCompletions(outcomes)
    instance.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return instance, completions


def call(instance, **overrides):
    values = {
        "messages": MESSAGES,
        "tool_name": TOOL,
        "parameters_schema": SCHEMA,
        "state_sha256": STATE,
        "cache_context": {"prompt_template_sha256": "b" * 64},
        "request_limits": {"max_attempts": 1},
    }
    values.update(overrides)
    return instance.llm_tool_call(**values)


def refused(response, expected=ToolCallProtocolError, **overrides):
    instance, completions = translator([response])
    try:
        call(instance, **overrides)
    except expected:
        return True, len(completions.calls)
    return False, len(completions.calls)


def check_success_and_forcing() -> None:
    instance, completions = translator([completion(json.dumps(VALID))])
    result = call(instance)
    request = completions.calls[0]
    check(
        "01 exactly one named forced call succeeds",
        result.arguments == VALID
        and result.provider_call_id == "call_0"
        and request["tools"]
        == [
            {
                "type": "function",
                "function": {
                    "name": TOOL,
                    "parameters": SCHEMA,
                    "strict": True,
                },
            }
        ]
        and request["tool_choice"] == {"type": "function", "function": {"name": TOOL}}
        and request["timeout"] == 60.0,
    )


def check_closed_response_shapes() -> None:
    content_only = completion(
        None, content=json.dumps(VALID), calls=0, finish_reason="stop"
    )
    markdown_only = completion(
        None,
        content=f"```json\n{json.dumps(VALID)}\n```",
        calls=0,
        finish_reason="stop",
    )
    wrong_type = completion(json.dumps(VALID))
    wrong_type.choices[0].message.tool_calls[0].type = "custom"
    cases = [
        content_only,
        markdown_only,
        completion(None, calls=0),
        completion(json.dumps(VALID), calls=2),
        wrong_type,
        completion(json.dumps(VALID), tool_name="other_tool"),
        completion(json.dumps(VALID), refusal="declined"),
        completion(json.dumps(VALID), finish_reason="length"),
    ]
    outcomes = [refused(item)[0] for item in cases]
    check(
        "02 content/markdown/zero/multi/wrong/refusal/truncation fail closed",
        all(outcomes),
    )


def check_argument_limits() -> None:
    raw_cases = [
        "{",
        '{"action":"no_action","state_sha256":"' + STATE + '","action":"no_action"}',
        '{"action":"no_action","state_sha256":NaN}',
    ]
    rejected = [
        refused(completion(raw), expected=ToolCallSchemaError)[0] for raw in raw_cases
    ]
    oversized = refused(
        completion(json.dumps(VALID)),
        expected=ToolCallSchemaError,
        request_limits={"max_argument_bytes": 32},
    )[0]
    deep_value = {"state_sha256": STATE, "action": "no_action", "x": []}
    cursor = deep_value["x"]
    for _ in range(6):
        child = []
        cursor.append(child)
        cursor = child
    deep = refused(
        completion(json.dumps(deep_value)),
        expected=ToolCallSchemaError,
        request_limits={"max_depth": 4},
    )[0]
    check(
        "03 malformed/duplicate/non-finite/oversized/deep arguments reject",
        all(rejected) and oversized and deep,
    )


def check_retries_and_capability() -> None:
    instance, completions = translator(
        [
            ToolCallTransientError("sensitive retry payload"),
            completion(json.dumps(VALID)),
        ]
    )
    result = call(instance, request_limits={"max_attempts": 2})
    bounded = result.arguments == VALID and len(completions.calls) == 2
    logic, attempts = refused(completion("{"), expected=ToolCallSchemaError)
    unsupported, unsupported_calls = translator(
        [completion(json.dumps(VALID))],
        capability_endpoint="https://different.invalid/v1",
    )
    capability_closed = False
    try:
        call(unsupported)
    except ToolCallsUnsupported:
        capability_closed = len(unsupported_calls.calls) == 0

    executor = ExecutorTranslator.__new__(ExecutorTranslator)
    executor.name = "executor"
    no_fallback = False
    try:
        call(executor)
    except ToolCallsUnsupported:
        no_fallback = True
    official = OpenAITranslator(
        "zh",
        "en",
        "gpt-4o-mini",
        api_key="offline-placeholder-key",
        ignore_cache=True,
    )
    custom = OpenAITranslator(
        "zh",
        "en",
        "gpt-4o-mini",
        base_url="https://custom.invalid/v1",
        api_key="offline-placeholder-key",
        ignore_cache=True,
    )
    check(
        "04 transient retry is bounded and logic/unsupported/executor never retry/fallback",
        bounded
        and logic
        and attempts == 1
        and capability_closed
        and no_fallback
        and official.supports_tool_calls()
        and not custom.supports_tool_calls(),
    )


def check_cache_separation_and_revalidation() -> None:
    limits = ToolCallLimits()
    base = {
        "endpoint": "https://user:secret@offline.invalid/v1?token=x",
        "model": "offline-model",
        "output_parameters": {"temperature": 0},
        "messages": MESSAGES,
        "tool_name": TOOL,
        "parameters_schema": SCHEMA,
        "state_sha256": STATE,
        "cache_context": {"prompt": "c" * 64},
        "limits": limits,
    }
    keys = [tool_call_cache_key(**base)]
    for name, value in (
        ("model", "other-model"),
        ("state_sha256", "d" * 64),
        ("output_parameters", {"temperature": 1}),
        ("parameters_schema", {**SCHEMA, "description": "version two"}),
    ):
        changed = dict(base)
        changed[name] = value
        keys.append(tool_call_cache_key(**changed))
    distinct = len(set(keys)) == len(keys) and all(
        secret not in "".join(keys) for secret in ("secret", "token", "bounded")
    )

    instance, completions = translator([], ignore_cache=False)
    instance.tool_call_cache = FakeCache(
        {
            "schema_version": 1,
            "tool_name": TOOL,
            "arguments": {**VALID, "extra": "raw provider payload"},
            "finish_reason": "tool_calls",
            "attempts": 1,
        }
    )
    revalidated = False
    try:
        call(instance)
    except ToolCallSchemaError:
        revalidated = len(completions.calls) == 0

    good, good_calls = translator([], ignore_cache=False)
    good.tool_call_cache = FakeCache(
        {
            "schema_version": 1,
            "tool_name": TOOL,
            "arguments": VALID,
            "finish_reason": "tool_calls",
            "attempts": 1,
        }
    )
    hit = call(good)
    check(
        "05 cache key separates schema/model/state/params and hits revalidate",
        distinct
        and revalidated
        and hit.arguments == VALID
        and hit.provider_call_id is None
        and not good_calls.calls,
    )


class PlainTranslator(BaseTranslator):
    name = "plain-test"
    model = "offline"

    def do_translate(self, text, rate_limit_params=None):
        return "ordinary target payload"

    def do_llm_translate(self, text, rate_limit_params=None):
        return "ordinary target payload"


class FailingOrdinaryCache:
    def get(self, _key):
        return None

    def set(self, _key, _value):
        raise RuntimeError("ordinary target payload secret")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record))


def check_ordinary_contract_and_logs() -> None:
    signature = str(inspect.signature(BaseTranslator.llm_translate))
    fixture = TranslationCache(
        "openai", {"lang_in": "en", "lang_out": "zh"}
    ).translate_engine_params
    ordinary_unchanged = (
        signature == "(self, text, ignore_cache=False, rate_limit_params: dict = None)"
        and fixture == '{"lang_in": "en", "lang_out": "zh"}'
    )
    capture = Capture()
    target_logger = logging.getLogger("babeldoc.translator.translator")
    old_level = target_logger.level
    target_logger.setLevel(logging.DEBUG)
    target_logger.addHandler(capture)
    try:
        plain = PlainTranslator("en", "zh", False)
        plain.cache = FailingOrdinaryCache()
        plain.llm_translate("ordinary source payload secret")

        provider, _ = translator([RuntimeError("provider raw secret")])
        try:
            call(provider)
        except ToolCallTransportError:
            pass
        retry, _ = translator([ToolCallTransientError("retry raw secret")])
        try:
            call(retry)
        except ToolCallTransportError:
            pass
        refusal, _ = translator(
            [completion(json.dumps(VALID), refusal="raw refusal secret")]
        )
        try:
            call(refusal)
        except ToolCallProtocolError:
            pass
        schema, _ = translator([completion('{"prompt":"raw schema secret"}')])
        try:
            call(schema)
        except ToolCallSchemaError:
            pass
    finally:
        target_logger.removeHandler(capture)
        target_logger.setLevel(old_level)
    logs = "\n".join(capture.lines)
    no_payload = all(
        value not in logs
        for value in (
            "ordinary source payload secret",
            "ordinary target payload secret",
            "provider raw secret",
            "retry raw secret",
            "raw refusal secret",
            "raw schema secret",
        )
    )
    check(
        "06 ordinary llm/cache bytes stay stable and all error logs are digest-only",
        ordinary_unchanged and no_payload,
        signature,
    )


def canonical_digest(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def bound_v4(source_sha: str, directory: Path) -> tuple[Path, Path, dict, dict]:
    review_sha = "2" * 64
    source_binding = {
        "source_pdf_sha256": source_sha,
        "source_page_count": 1,
        "page_box_rotation_manifest_sha256": "3" * 64,
        "semantic_digest_schema_version": "semantic-pages.v1",
        "per_physical_page_semantic_sha256": {"1": "4" * 64},
        "parser_layout_model_identity": "offline-fixture",
        "parser_layout_model_digest": "5" * 64,
        "semantic_config_digest": "6" * 64,
        "code_contract_version": "hitl-source-binding.v1",
    }
    decision_refs = {"page:1": "page-ref-1"}
    evidence = {
        "source_binding_sha256": canonical_digest(source_binding),
        "review_manifest_sha256": review_sha,
        "binding_mode": "native_v4",
        "legacy_review_sha256": None,
        "legacy_decisions_sha256": None,
        "decision_refs_sha256": canonical_digest(decision_refs),
        "tool_schema_version": "hitl-bind-tool.v1",
        "code_contract_version": source_binding["code_contract_version"],
    }
    evidence_sha = canonical_digest(evidence)
    decisions = {
        "format_version": 4,
        "sample": "ABB-zh",
        "source_binding": source_binding,
        "review_manifest_sha256": review_sha,
        "lineage": {
            "binding_mode": "native_v4",
            "legacy_review": None,
            "legacy_decisions": None,
            "legacy_review_cycle_unverified": False,
            "rebuilt_review_manifest_sha256": review_sha,
            "binding_evidence_schema_version": "hitl-binding-evidence.v1",
            "binding_evidence_sha256": evidence_sha,
        },
        "page_kinds": {"1": "toc"},
        "terms": {},
        "drop_caps": {},
        "decision_refs": decision_refs,
    }
    decisions_path = directory / "ABB-zh.decisions.json"
    write_json(decisions_path, decisions)
    decisions_sha = hashlib.sha256(decisions_path.read_bytes()).hexdigest()
    binding = {
        "format_version": 4,
        "sample": "ABB-zh",
        "status": "bound",
        "binding_mode": "native_v4",
        "binding_evidence_schema_version": "hitl-binding-evidence.v1",
        "binding_evidence_sha256": evidence_sha,
        "binding_evidence": evidence,
        "source_pdf_sha256": source_sha,
        "review_manifest_sha256": review_sha,
        "decisions_sha256": decisions_sha,
    }
    binding_path = directory / "ABB-zh.binding-report.json"
    write_json(binding_path, binding)
    return decisions_path, binding_path, decisions, binding


def check_effective_run_intent() -> None:
    previous = main_module.os.environ.pop("OPENAI_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory(prefix="babeldoc-c20a-") as temp:
            root = Path(temp)
            source = root / "ABB-zh.pdf"
            source.write_bytes(b"%PDF-1.7\nforced-tool-fixture\n")
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            config = root / "babeldoc.zh-en.toml"
            config.write_text(
                "[babeldoc]\n"
                'lang-in = "zh"\n'
                'lang-out = "en"\n'
                "openai = true\n"
                'openai-model = "gpt-4o-mini"\n'
                "qps = 4\n"
                "pool-max-workers = 4\n"
                "term-pool-max-workers = 2\n",
                encoding="ascii",
            )
            reviews = root / "reviews-v4"
            reviews.mkdir()
            decisions_path, binding_path, decisions, binding = bound_v4(
                source_sha, reviews
            )
            # The exact C22-like argv deliberately carries no capability flag.
            main_module.os.environ["OPENAI_API_KEY"] = "configured-placeholder"
            args = main_module.create_parser().parse_args(
                [
                    "--config",
                    str(config),
                    "--magazine-mode",
                    "hitl-apply",
                    "--magazine-reviews-dir",
                    str(reviews),
                    "--files",
                    str(source),
                    "--pages",
                    "2-3,8-9",
                    "--only-include-translated-page",
                    "--debug",
                    "--working-dir",
                    str(root / "paid-run" / "work"),
                    "--output",
                    str(root / "paid-run" / "output"),
                    "--print-effective-config",
                ]
            )
            report, errors = main_module.effective_config_report(args)
            effective = validate_report(report, require_credentials=True)
            encoded = json.dumps(report, sort_keys=True)
            effective_path = root / "effective-config.redacted.json"
            output_path = root / "run-intent-validation.json"
            write_json(effective_path, report)
            exit_code = run_intent_main(
                [
                    "--effective-config",
                    str(effective_path),
                    "--decisions",
                    str(decisions_path),
                    "--binding-report",
                    str(binding_path),
                    "--require-external-credentials",
                    "--report",
                    str(output_path),
                ]
            )
            output = json.loads(output_path.read_text(encoding="utf-8"))
            digest_payload = dict(output)
            digest = digest_payload.pop("run_intent_sha256")
            exact_output = (
                exit_code == 0
                and output["schema_version"] == "bounded-run-intent.v2"
                and output["status"] == "READY"
                and digest == canonical_digest(digest_payload)
                and output_path.read_bytes().endswith(b"\n")
            )

            missing = copy.deepcopy(decisions)
            del missing["lineage"]
            missing_path = reviews / "missing.decisions.json"
            write_json(missing_path, missing)
            missing_report = root / "missing-report.json"
            missing_closed = (
                run_intent_main(
                    [
                        "--effective-config",
                        str(effective_path),
                        "--decisions",
                        str(missing_path),
                        "--binding-report",
                        str(binding_path),
                        "--report",
                        str(missing_report),
                    ]
                )
                == 1
                and not missing_report.exists()
            )
            absent_decisions_report = root / "absent-decisions-report.json"
            absent_decisions_closed = (
                run_intent_main(
                    [
                        "--effective-config",
                        str(effective_path),
                        "--decisions",
                        str(reviews / "absent.decisions.json"),
                        "--binding-report",
                        str(binding_path),
                        "--report",
                        str(absent_decisions_report),
                    ]
                )
                == 1
                and not absent_decisions_report.exists()
            )
            absent_binding_report = root / "absent-binding-report.json"
            absent_binding_closed = (
                run_intent_main(
                    [
                        "--effective-config",
                        str(effective_path),
                        "--decisions",
                        str(decisions_path),
                        "--binding-report",
                        str(reviews / "absent.binding-report.json"),
                        "--report",
                        str(absent_binding_report),
                    ]
                )
                == 1
                and not absent_binding_report.exists()
            )
            mismatched = copy.deepcopy(binding)
            mismatched["sample"] = "other-sample"
            mismatched_path = reviews / "mismatched.binding-report.json"
            write_json(mismatched_path, mismatched)
            mismatch_closed = False
            try:
                validate_bound_run_intent(
                    report,
                    decisions,
                    mismatched,
                    decisions_sha256=hashlib.sha256(
                        decisions_path.read_bytes()
                    ).hexdigest(),
                    binding_report_sha256=hashlib.sha256(
                        mismatched_path.read_bytes()
                    ).hexdigest(),
                    require_credentials=True,
                )
            except RunIntentError:
                mismatch_closed = True

            attempts = copy.deepcopy(report)
            attempts["limits"]["max_tool_call_attempts"] = 4
            attempts_closed = False
            try:
                validate_report(attempts)
            except RunIntentError:
                attempts_closed = True

            custom_args = main_module.create_parser().parse_args(
                [
                    "--openai",
                    "--openai-base-url",
                    "https://custom.invalid/v1",
                    "--files",
                    str(source),
                ]
            )
            custom_report, _custom_errors = main_module.effective_config_report(
                custom_args
            )
            custom_closed = False
            try:
                validate_report(custom_report)
            except RunIntentError:
                custom_closed = True
            check(
                "07 exact C22 argv and v4 binding produce a canonical report; missing/mismatch/custom/bounds close",
                not errors
                and effective["capability_declaration"] == "builtin_openai"
                and report["inputs"][0]["basename"] == "ABB-zh.pdf"
                and str(root) not in encoded
                and "configured-placeholder" not in encoded
                and exact_output
                and missing_closed
                and absent_decisions_closed
                and absent_binding_closed
                and mismatch_closed
                and attempts_closed
                and custom_closed,
            )
    finally:
        main_module.os.environ.pop("OPENAI_API_KEY", None)
        if previous is not None:
            main_module.os.environ["OPENAI_API_KEY"] = previous


def main() -> int:
    check_success_and_forcing()
    check_closed_response_shapes()
    check_argument_limits()
    check_retries_and_capability()
    check_cache_separation_and_revalidation()
    check_ordinary_contract_and_logs()
    check_effective_run_intent()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(
        f"spec_check_tool_call_transport: "
        f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
