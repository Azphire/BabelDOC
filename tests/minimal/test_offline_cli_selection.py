from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc import main as main_module
from babeldoc.translator.no_network import NoNetworkTranslator

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TEMP = ROOT / ".runtime" / "temp"


class EnvironmentMustNotBeRead(dict[str, str]):
    def get(self, key: str, default=None):
        raise AssertionError(f"credential environment was queried: {key}")


class FakeTranslator:
    def __init__(self, kwargs: dict[str, object]):
        self.kwargs = kwargs
        counter = SimpleNamespace(value=0)
        self.token_count = counter
        self.prompt_token_count = counter
        self.completion_token_count = counter
        self.cache_hit_prompt_token_count = counter


def parser_args(*arguments: str):
    return main_module.create_parser().parse_args(list(arguments))


def install_fake_translator(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeTranslator(kwargs)

    monkeypatch.setattr(main_module, "OpenAITranslator", factory)
    return calls


@pytest.mark.parametrize(
    "offline_flag",
    ["--only-parse-generate-pdf", "--skip-translation"],
)
def test_offline_flags_bypass_credentials_and_openai(
    monkeypatch: pytest.MonkeyPatch,
    offline_flag: str,
) -> None:
    def forbidden_factory(**_kwargs):
        raise AssertionError("OpenAITranslator was instantiated")

    monkeypatch.setattr(main_module, "OpenAITranslator", forbidden_factory)
    args = parser_args(offline_flag)
    main_key, term_key = main_module.resolve_cli_credentials(
        args,
        EnvironmentMustNotBeRead(),
    )
    translator, term_translator = main_module.build_translators(
        args,
        main_key,
        term_key,
    )

    assert main_key is None
    assert term_key is None
    assert isinstance(translator, NoNetworkTranslator)
    assert term_translator is translator


def test_no_network_translator_fails_closed_without_counting() -> None:
    translator = NoNetworkTranslator("en", "zh")

    for method_name in (
        "translate",
        "llm_translate",
        "do_translate",
        "do_llm_translate",
    ):
        with pytest.raises(
            RuntimeError,
            match="translation is disabled for this execution path",
        ):
            getattr(translator, method_name)("synthetic text")

    assert translator.translate_call_count == 0
    assert translator.translate_cache_call_count == 0
    assert translator.token_count.value == 0
    assert translator.prompt_token_count.value == 0
    assert translator.completion_token_count.value == 0
    assert translator.cache_hit_prompt_token_count.value == 0


def test_cli_and_toml_keys_take_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_translator(monkeypatch)
    cli_args = parser_args(
        "--openai",
        "--openai-api-key",
        "synthetic-cli-main",
        "--openai-term-extraction-model",
        "synthetic-term-model",
        "--openai-term-extraction-api-key",
        "synthetic-cli-term",
    )
    main_key, term_key = main_module.resolve_cli_credentials(
        cli_args,
        EnvironmentMustNotBeRead(),
    )
    main_module.build_translators(cli_args, main_key, term_key)

    assert [call["api_key"] for call in calls] == [
        "synthetic-cli-main",
        "synthetic-cli-term",
    ]

    calls.clear()
    with tempfile.TemporaryDirectory(
        prefix="m0-cli-config-",
        dir=RUNTIME_TEMP,
    ) as temp_dir:
        config_file = Path(temp_dir) / "babeldoc.toml"
        config_file.write_text(
            "[babeldoc]\n"
            "openai = true\n"
            'openai-api-key = "synthetic-toml-main"\n'
            'openai-term-extraction-model = "synthetic-term-model"\n',
            encoding="utf-8",
        )
        toml_args = parser_args("-c", str(config_file))
        main_key, term_key = main_module.resolve_cli_credentials(
            toml_args,
            EnvironmentMustNotBeRead(),
        )
        main_module.build_translators(toml_args, main_key, term_key)

    assert [call["api_key"] for call in calls] == [
        "synthetic-toml-main",
        "synthetic-toml-main",
    ]


def test_environment_fallback_is_inherited_by_term_translator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_translator(monkeypatch)
    args = parser_args(
        "--openai",
        "--openai-term-extraction-model",
        "synthetic-term-model",
    )
    main_key, term_key = main_module.resolve_cli_credentials(
        args,
        {"OPENAI_API_KEY": "synthetic-environment-main"},
    )
    main_module.build_translators(args, main_key, term_key)

    assert [call["api_key"] for call in calls] == [
        "synthetic-environment-main",
        "synthetic-environment-main",
    ]


def test_openai_constructor_kwargs_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_translator(monkeypatch)
    args = parser_args(
        "--openai",
        "--openai-api-key",
        "synthetic-main",
        "--openai-model",
        "synthetic-main-model",
        "--openai-base-url",
        "https://main.invalid/v1",
        "--ignore-cache",
        "--enable-json-mode-if-requested",
        "--send-dashscope-header",
        "--no-send-temperature",
        "--openai-reasoning",
        "high",
        "--openai-thinking",
        "enabled",
        "--openai-term-extraction-model",
        "synthetic-term-model",
        "--openai-term-extraction-base-url",
        "https://term.invalid/v1",
        "--openai-term-extraction-api-key",
        "synthetic-term",
        "--openai-term-extraction-reasoning",
        "medium",
    )
    main_key, term_key = main_module.resolve_cli_credentials(
        args,
        EnvironmentMustNotBeRead(),
    )
    main_module.build_translators(args, main_key, term_key)

    assert len(calls) == 2
    main_call, term_call = calls
    assert main_call == {
        "lang_in": args.lang_in,
        "lang_out": args.lang_out,
        "model": "synthetic-main-model",
        "base_url": "https://main.invalid/v1",
        "api_key": "synthetic-main",
        "ignore_cache": True,
        "enable_json_mode_if_requested": True,
        "send_dashscope_header": True,
        "send_temperature": False,
        "reasoning": "high",
        "thinking": "enabled",
    }
    assert term_call == {
        "lang_in": args.lang_in,
        "lang_out": args.lang_out,
        "model": "synthetic-term-model",
        "base_url": "https://term.invalid/v1",
        "api_key": "synthetic-term",
        "ignore_cache": True,
        "enable_json_mode_if_requested": True,
        "send_dashscope_header": True,
        "send_temperature": False,
        "reasoning": "medium",
    }


def test_normal_missing_service_and_key_fail_without_output(capsys) -> None:
    missing_service = parser_args()
    with pytest.raises(ValueError) as service_error:
        main_module.build_translators(missing_service, None, None)
    assert str(service_error.value) == "必须选择一个翻译服务：--openai"

    missing_key = parser_args("--openai")
    with pytest.raises(ValueError) as key_error:
        main_module.build_translators(missing_key, None, None)
    assert str(key_error.value) == (
        "使用 OpenAI 服务时必须提供 API key 或 OPENAI_API_KEY"
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
