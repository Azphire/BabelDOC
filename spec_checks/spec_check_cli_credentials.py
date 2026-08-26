"""Offline checks for CLI credential precedence and translation-free startup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc import main as main_module  # noqa: E402
from babeldoc.translator.no_network import NoNetworkTranslator  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail else ''}")


class FakeTranslator:
    def __init__(self, kwargs: dict):
        self.kwargs = kwargs
        counter = SimpleNamespace(value=0)
        self.token_count = counter
        self.prompt_token_count = counter
        self.completion_token_count = counter
        self.cache_hit_prompt_token_count = counter


def parser_args(*arguments: str):
    return main_module.create_parser().parse_args(list(arguments))


def check_precedence(root: Path) -> None:
    calls: list[dict] = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeTranslator(kwargs)

    original = main_module.OpenAITranslator
    main_module.OpenAITranslator = factory
    try:
        explicit = parser_args(
            "--openai",
            "--openai-api-key",
            "cli-main-key",
            "--openai-term-extraction-api-key",
            "cli-term-key",
            "--openai-term-extraction-model",
            "term-model",
        )
        main_module.build_translators(explicit, {"OPENAI_API_KEY": "environment-key"})
        check(
            "01a explicit CLI keys win over the environment",
            [call["api_key"] for call in calls] == ["cli-main-key", "cli-term-key"],
        )

        calls.clear()
        config_file = root / "babeldoc.toml"
        config_file.write_text(
            "[babeldoc]\n"
            "openai = true\n"
            'openai-api-key = "toml-main-key"\n'
            'openai-term-extraction-model = "term-model"\n',
            encoding="utf-8",
        )
        configured = parser_args("-c", str(config_file))
        main_module.build_translators(configured, {"OPENAI_API_KEY": "environment-key"})
        check(
            "01b TOML key wins and the term translator uses the final main key",
            [call["api_key"] for call in calls] == ["toml-main-key", "toml-main-key"],
        )

        calls.clear()
        environment_only = parser_args("--openai")
        main_key, term_key = main_module.resolve_cli_credentials(
            environment_only, {"OPENAI_API_KEY": "environment-key"}
        )
        main_module.build_translators(
            environment_only, {"OPENAI_API_KEY": "environment-key"}
        )
        check(
            "01c environment key fills an empty main key",
            (main_key, term_key) == ("environment-key", "environment-key")
            and [call["api_key"] for call in calls] == ["environment-key"],
        )
    finally:
        main_module.OpenAITranslator = original


def check_missing_and_redaction() -> None:
    missing_service = None
    try:
        main_module.build_translators(parser_args(), {})
    except ValueError as exc:
        missing_service = str(exc)
    missing_key = None
    try:
        main_module.build_translators(parser_args("--openai"), {})
    except ValueError as exc:
        missing_key = str(exc)
    check(
        "02a normal translation requires a service and final key",
        missing_service == "必须选择一个翻译服务：--openai"
        and missing_key == "使用 OpenAI 服务时必须提供 API key 或 OPENAI_API_KEY",
    )

    args = parser_args(
        "--openai",
        "--openai-api-key",
        "message-key",
        "--openai-base-url",
        "https://example.test/v1?token=query-key",
    )
    message = main_module.redact_sensitive_text(
        "message-key https://example.test/v1?token=query-key", args
    )
    check(
        "02b error redaction removes keys and URL queries",
        "message-key" not in message
        and "query-key" not in message
        and "https://example.test/v1" in message,
    )

    original = main_module.OpenAITranslator

    def failing_factory(**kwargs):
        raise RuntimeError(f"{kwargs['api_key']} {kwargs['base_url']}")

    main_module.OpenAITranslator = failing_factory
    try:
        failure = None
        try:
            main_module.build_translators(args, {})
        except ValueError as exc:
            failure = str(exc)
        check(
            "02c constructor failures expose no service configuration",
            failure == "无法初始化 OpenAI 翻译器；请检查服务配置"
            and "message-key" not in failure
            and "query-key" not in failure,
        )
    finally:
        main_module.OpenAITranslator = original


def check_translation_free_paths() -> None:
    class EnvironmentMustNotBeRead(dict):
        def get(self, key, default=None):
            raise AssertionError(f"environment key was read: {key}")

    original = main_module.OpenAITranslator

    def forbidden_factory(**_kwargs):
        raise AssertionError("OpenAITranslator was instantiated")

    main_module.OpenAITranslator = forbidden_factory
    try:
        parse_args = parser_args("--only-parse-generate-pdf")
        parse_credentials = main_module.resolve_cli_credentials(
            parse_args, EnvironmentMustNotBeRead()
        )
        parse_translator, parse_term = main_module.build_translators(
            parse_args, EnvironmentMustNotBeRead()
        )
        skip_args = parser_args("--skip-translation")
        skip_translator, skip_term = main_module.build_translators(
            skip_args, EnvironmentMustNotBeRead()
        )
        check(
            "03a translation-free paths do not read credentials or build OpenAI",
            parse_credentials == (None, None)
            and isinstance(parse_translator, NoNetworkTranslator)
            and parse_term is parse_translator
            and isinstance(skip_translator, NoNetworkTranslator)
            and skip_term is skip_translator,
        )
        refused = False
        try:
            parse_translator.translate("must not be sent")
        except RuntimeError:
            refused = True
        check("03b no-network translator refuses accidental translation", refused)
    finally:
        main_module.OpenAITranslator = original


def check_cli_missing_key(root: Path) -> None:
    input_file = root / "input.pdf"
    input_file.write_bytes(b"%PDF-1.7\n")
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    result = subprocess.run(  # noqa: S603 - fixed Python argv runs the local CLI
        [
            sys.executable,
            "-m",
            "babeldoc.main",
            "--openai",
            "--files",
            str(input_file),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    combined = result.stdout + result.stderr
    check(
        "04 missing key fails before model loading",
        result.returncode == 2
        and "OPENAI_API_KEY" in combined
        and "DocLayout" not in combined,
        combined[-300:],
    )


def check_effective_environment_redaction() -> None:
    previous = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "effective-environment-key"
    try:
        args = parser_args("--magazine-mode", "automatic", "--openai")
        report, errors = main_module.effective_config_report(args)
        encoded = json.dumps(report, sort_keys=True)
        check(
            "05 effective config reports but never reveals the environment key",
            not errors
            and report["service"]["openai"]["api_key"] == "<redacted>"
            and report["service"]["term_extraction"]["api_key"] == "<redacted>"
            and "effective-environment-key" not in encoded,
        )
    finally:
        if previous is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="babeldoc-c16-credentials-") as temp:
        root = Path(temp)
        check_precedence(root)
        check_missing_and_redaction()
        check_translation_free_paths()
        check_cli_missing_key(root)
        check_effective_environment_redaction()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(
        f"spec_check_cli_credentials: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
