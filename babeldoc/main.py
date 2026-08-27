import asyncio
import json
import logging
import multiprocessing as mp
import os
import queue
import random
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import configargparse
import tqdm
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.progress import TimeRemainingColumn

import babeldoc.assets.assets
import babeldoc.format.pdf.high_level
from babeldoc.const import enable_process_pool
from babeldoc.format.pdf.translation_config import TranslationConfig
from babeldoc.format.pdf.translation_config import WatermarkOutputMode
from babeldoc.glossary import Glossary
from babeldoc.magazine.resource_paths import logical_resource_name
from babeldoc.magazine.resource_paths import resource_availability
from babeldoc.magazine.runtime_profile import MODE_NAMES
from babeldoc.magazine.runtime_profile import SWITCH_DEFAULTS
from babeldoc.magazine.runtime_profile import input_summary
from babeldoc.magazine.runtime_profile import resolve_magazine_profile
from babeldoc.magazine.runtime_profile import resolve_reviews_dir
from babeldoc.magazine.runtime_profile import validate_magazine_switches
from babeldoc.translator.no_network import NoNetworkTranslator
from babeldoc.translator.translator import OpenAITranslator
from babeldoc.translator.translator import set_translate_rate_limiter

logger = logging.getLogger(__name__)
__version__ = "0.6.4"


class DiagnosticArgumentParser(configargparse.ArgParser):
    """Apply CLI diagnostic master overrides after TOML expansion."""

    def parse_known_args(self, args=None, namespace=None, **kwargs):
        raw_args = list(sys.argv[1:] if args is None else args)
        parsed, remaining = super().parse_known_args(args, namespace, **kwargs)
        cli_no_debug = "--no-debug" in raw_args
        cli_debug = "--debug" in raw_args
        cli_show_char_box = "--show-char-box" in raw_args
        if cli_debug and cli_no_debug:
            self.error("--debug cannot be combined with --no-debug")
        if cli_no_debug and cli_show_char_box:
            self.error("--show-char-box cannot be combined with --no-debug")
        if cli_no_debug:
            parsed.debug = False
            parsed.show_char_box = False
        parsed.debug = bool(parsed.debug)
        parsed.show_char_box = bool(parsed.show_char_box)
        return parsed, remaining


def _open_utf8_config(path):
    return open(path, encoding="utf-8")  # noqa: PTH123 - configargparse callback


def create_parser():
    parser = DiagnosticArgumentParser(
        config_file_parser_class=configargparse.TomlConfigParser(["babeldoc"]),
        config_file_open_func=_open_utf8_config,
    )
    parser.add_argument(
        "-c",
        "--config",
        is_config_file=True,
        help="config file path",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--files",
        action="append",
        help="One or more paths to PDF files.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        dest="debug",
        default=False,
        help="Use debug logging level.",
    )
    parser.add_argument(
        "--no-debug",
        action="store_false",
        dest="debug",
        help="Disable all general debug diagnostics from TOML/defaults.",
    )
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Only download and verify required assets then exit.",
    )
    parser.add_argument(
        "--rpc-doclayout",
        help="RPC service host address for document layout analysis",
    )
    parser.add_argument(
        "--rpc-doclayout2",
        help="RPC service host address for document layout analysis",
    )
    parser.add_argument(
        "--rpc-doclayout3",
        help="RPC service host address for document layout analysis",
    )
    parser.add_argument(
        "--rpc-doclayout4",
        help="RPC service host address for document layout analysis",
    )
    parser.add_argument(
        "--rpc-doclayout5",
        help="RPC service host address for document layout analysis",
    )
    parser.add_argument(
        "--rpc-doclayout6",
        help="RPC service host address for document layout analysis",
    )
    parser.add_argument(
        "--rpc-doclayout7",
        help="RPC service host address for document layout analysis",
    )
    parser.add_argument(
        "--generate-offline-assets",
        default=None,
        help="Generate offline assets package in the specified directory",
    )
    parser.add_argument(
        "--restore-offline-assets",
        default=None,
        help="Restore offline assets package from the specified file",
    )
    parser.add_argument(
        "--working-dir",
        default=None,
        help="Working directory for translation. If not set, use temp directory.",
    )
    parser.add_argument(
        "--metadata-extra-data",
        default=None,
        help="Extra data for metadata",
    )
    parser.add_argument(
        "--enable-process-pool",
        action="store_true",
        help="DEBUG ONLY",
    )
    # translation option argument group
    translation_group = parser.add_argument_group(
        "Translation",
        description="Used during translation",
    )
    translation_group.add_argument(
        "--pages",
        "-p",
        help="Pages to translate. If not set, translate all pages. like: 1,2,1-,-3,3-5",
    )
    translation_group.add_argument(
        "--min-text-length",
        type=int,
        default=5,
        help="Minimum text length to translate (default: 5)",
    )
    translation_group.add_argument(
        "--lang-in",
        "-li",
        default="en",
        help="The code of source language.",
    )
    translation_group.add_argument(
        "--lang-out",
        "-lo",
        default="zh",
        help="The code of target language.",
    )
    translation_group.add_argument(
        "--output",
        "-o",
        help="Output directory for files. if not set, use same as input.",
    )
    translation_group.add_argument(
        "--qps",
        "-q",
        type=int,
        default=4,
        help="QPS limit of translation service",
    )
    translation_group.add_argument(
        "--ignore-cache",
        action="store_true",
        help="Ignore translation cache.",
    )
    translation_group.add_argument(
        "--no-dual",
        action="store_true",
        help="Do not output bilingual PDF files",
    )
    translation_group.add_argument(
        "--no-mono",
        action="store_true",
        help="Do not output monolingual PDF files",
    )
    translation_group.add_argument(
        "--formular-font-pattern",
        help="Font pattern to identify formula text",
    )
    translation_group.add_argument(
        "--formular-char-pattern",
        help="Character pattern to identify formula text",
    )
    translation_group.add_argument(
        "--split-short-lines",
        action="store_true",
        help="Force split short lines into different paragraphs (may cause poor typesetting & bugs)",
    )
    translation_group.add_argument(
        "--short-line-split-factor",
        type=float,
        default=0.8,
        help="Split threshold factor. The actual threshold is the median length of all lines on the current page * this factor",
    )
    translation_group.add_argument(
        "--skip-clean",
        action="store_true",
        help="Skip PDF cleaning step",
    )
    translation_group.add_argument(
        "--dual-translate-first",
        action="store_true",
        help="Put translated pages first in dual PDF mode",
    )
    translation_group.add_argument(
        "--disable-rich-text-translate",
        action="store_true",
        help="Disable rich text translation (may help improve compatibility with some PDFs)",
    )
    translation_group.add_argument(
        "--enhance-compatibility",
        action="store_true",
        help="Enable all compatibility enhancement options (equivalent to --skip-clean --dual-translate-first --disable-rich-text-translate)",
    )
    translation_group.add_argument(
        "--use-alternating-pages-dual",
        action="store_true",
        help="Use alternating pages mode for dual PDF. When enabled, original and translated pages are arranged in alternate order.",
    )
    translation_group.add_argument(
        "--watermark-output-mode",
        type=str,
        choices=["watermarked", "no_watermark", "both"],
        default="watermarked",
        help="Control watermark output mode: 'watermarked' (default) adds watermark to translated PDF, 'no_watermark' doesn't add watermark, 'both' outputs both versions.",
    )
    translation_group.add_argument(
        "--max-pages-per-part",
        type=int,
        help="Maximum number of pages per part for split translation. If not set, no splitting will be performed.",
    )
    translation_group.add_argument(
        "--no-watermark",
        action="store_true",
        help="[DEPRECATED] Use --watermark-output-mode=no_watermark instead. Do not add watermark to the translated PDF.",
    )
    translation_group.add_argument(
        "--report-interval",
        type=float,
        default=0.1,
        help="Progress report interval in seconds (default: 0.1)",
    )
    translation_group.add_argument(
        "--translate-table-text",
        action="store_true",
        default=False,
        help="Translate table text (experimental)",
    )
    translation_group.add_argument(
        "--show-char-box",
        action="store_true",
        default=False,
        help="Show character box (debug only)",
    )
    translation_group.add_argument(
        "--skip-scanned-detection",
        action="store_true",
        default=False,
        help="Skip scanned document detection (speeds up processing for non-scanned documents)",
    )
    translation_group.add_argument(
        "--ocr-workaround",
        action="store_true",
        default=False,
        help="Add text fill background (experimental)",
    )
    translation_group.add_argument(
        "--custom-system-prompt",
        help="Custom system prompt for translation.",
        default=None,
    )
    translation_group.add_argument(
        "--add-formula-placehold-hint",
        action="store_true",
        default=False,
        help="Add formula placeholder hint for translation. (Currently not recommended, it may affect translation quality, default: False)",
    )
    translation_group.add_argument(
        "--disable-same-text-fallback",
        action="store_true",
        default=False,
        help="Disable fallback translation when LLM output matches input text. (default: False)",
    )
    translation_group.add_argument(
        "--glossary-files",
        type=str,
        default=None,
        help="Comma-separated paths to glossary CSV files.",
    )
    translation_group.add_argument(
        "--pool-max-workers",
        type=int,
        help="Maximum number of worker threads for internal task processing pools. If not specified, defaults to QPS value. This parameter directly sets the worker count, replacing previous QPS-based dynamic calculations.",
    )
    translation_group.add_argument(
        "--term-pool-max-workers",
        type=int,
        help="Maximum number of worker threads dedicated to automatic term extraction. If not specified, defaults to --pool-max-workers (or QPS value when unset).",
    )
    translation_group.add_argument(
        "--no-auto-extract-glossary",
        action="store_false",
        dest="auto_extract_glossary",
        default=True,
        help="Disable automatic term extraction. (Config file: set auto_extract_glossary = false)",
    )
    translation_group.add_argument(
        "--auto-enable-ocr-workaround",
        action="store_true",
        default=False,
        help="Enable automatic OCR workaround. If a document is detected as heavily scanned, this will attempt to enable OCR processing and skip further scan detection. Note: This option interacts with `--ocr-workaround` and `--skip-scanned-detection`. See documentation for details. (default: False)",
    )
    translation_group.add_argument(
        "--primary-font-family",
        type=str,
        choices=["serif", "sans-serif", "script"],
        default=None,
        help="Override primary font family for translated text. Choices: 'serif' for serif fonts, 'sans-serif' for sans-serif fonts, 'script' for script/italic fonts. If not specified, uses automatic font selection based on original text properties.",
    )
    translation_group.add_argument(
        "--only-include-translated-page",
        action="store_true",
        default=False,
        help="Only include translated pages in the output PDF. Effective only when --pages is used.",
    )
    translation_group.add_argument(
        "--save-auto-extracted-glossary",
        action="store_true",
        default=False,
        help="Save automatically extracted glossary terms to a CSV file in the output directory.",
    )
    translation_group.add_argument(
        "--disable-graphic-element-process",
        action="store_true",
        default=False,
        help="Disable graphic element process. (default: False)",
    )
    translation_group.add_argument(
        "--no-merge-alternating-line-numbers",
        action="store_false",
        dest="merge_alternating_line_numbers",
        default=True,
        help="Disable post-processing that merges alternating line-number layouts (by default this feature is enabled).",
    )
    translation_group.add_argument(
        "--skip-translation",
        action="store_true",
        default=False,
        help="Skip translation step. (default: False)",
    )
    translation_group.add_argument(
        "--skip-form-render",
        action="store_true",
        default=False,
        help="Skip form rendering. (default: False)",
    )
    translation_group.add_argument(
        "--skip-curve-render",
        action="store_true",
        default=False,
        help="Skip curve rendering. (default: False)",
    )
    translation_group.add_argument(
        "--only-parse-generate-pdf",
        action="store_true",
        default=False,
        help="Only parse PDF and generate output PDF without translation (default: False). This skips all translation-related processing including layout analysis, paragraph finding, style processing, and translation itself.",
    )
    translation_group.add_argument(
        "--remove-non-formula-lines",
        action="store_true",
        default=False,
        help="Remove non-formula lines from paragraph areas. This removes decorative lines that are not part of formulas, while protecting lines in figure/table areas. (default: False)",
    )
    translation_group.add_argument(
        "--non-formula-line-iou-threshold",
        type=float,
        default=0.9,
        help="IoU threshold for detecting paragraph overlap when removing non-formula lines. Higher values are more conservative. (default: 0.9)",
    )
    translation_group.add_argument(
        "--figure-table-protection-threshold",
        type=float,
        default=0.9,
        help="IoU threshold for protecting lines in figure/table areas when removing non-formula lines. Higher values provide more protection. (default: 0.9)",
    )
    translation_group.add_argument(
        "--skip-formula-offset-calculation",
        action="store_true",
        default=False,
        help="Skip formula offset calculation (default: False)",
    )
    magazine_group = translation_group.add_mutually_exclusive_group()
    magazine_group.add_argument(
        "--magazine-mode",
        choices=MODE_NAMES,
        default=None,
        help="Use a built-in validated magazine runtime mode.",
    )
    magazine_group.add_argument(
        "--magazine-profile",
        default=None,
        help="Path to a versioned magazine runtime profile JSON file.",
    )
    translation_group.add_argument(
        "--magazine-reviews-dir",
        default=None,
        help="Directory containing HITL review and decisions files.",
    )
    translation_group.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate the effective configuration and exit before loading models.",
    )
    translation_group.add_argument(
        "--print-effective-config",
        action="store_true",
        help="Print the validated, redacted effective configuration as JSON.",
    )
    # service option argument group
    service_group = translation_group.add_mutually_exclusive_group()
    service_group.add_argument(
        "--openai",
        action="store_true",
        help="Use OpenAI translator.",
    )
    service_group = parser.add_argument_group(
        "Translation - OpenAI Options",
        description="OpenAI specific options",
    )
    service_group.add_argument(
        "--openai-model",
        default="gpt-4o-mini",
        help="The OpenAI model to use for translation.",
    )
    service_group.add_argument(
        "--openai-base-url",
        help="The base URL for the OpenAI API.",
    )
    service_group.add_argument(
        "--openai-api-key",
        "-k",
        help="The API key for the OpenAI API.",
    )
    service_group.add_argument(
        "--openai-term-extraction-model",
        default=None,
        help="OpenAI model to use for automatic term extraction. Defaults to --openai-model when unset.",
    )
    service_group.add_argument(
        "--openai-term-extraction-base-url",
        default=None,
        help="Base URL for the OpenAI API used during automatic term extraction. Falls back to --openai-base-url when unset.",
    )
    service_group.add_argument(
        "--openai-term-extraction-api-key",
        default=None,
        help="API key for the OpenAI API used during automatic term extraction. Falls back to --openai-api-key when unset.",
    )
    service_group.add_argument(
        "--enable-json-mode-if-requested",
        action="store_true",
        default=False,
        help="Enable JSON mode for OpenAI requests.",
    )
    service_group.add_argument(
        "--send-dashscope-header",
        action="store_true",
        default=False,
        help="Send DashScope data inspection header to disable input/output inspection.",
    )
    service_group.add_argument(
        "--no-send-temperature",
        action="store_true",
        default=False,
        help="Do not send temperature parameter to OpenAI API (default: send temperature).",
    )
    service_group.add_argument(
        "--openai-reasoning",
        type=str,
        default=None,
        help="Reasoning string to send in the OpenAI request body 'reasoning' field. If not set, the field is not sent.",
    )
    service_group.add_argument(
        "--openai-thinking",
        type=str,
        choices=["enabled", "disabled"],
        default=None,
        help="DeepSeek-style thinking switch sent as request body 'thinking': {'type': ...}. If not set, the field is not sent.",
    )
    service_group.add_argument(
        "--openai-term-extraction-reasoning",
        type=str,
        default=None,
        help="Reasoning string for the OpenAI term extraction translator. If not set, no reasoning field is sent for term extraction requests.",
    )

    return parser


def _normalized_file(value: str) -> str:
    if value.startswith("--files="):
        value = value[len("--files=") :]
    return value.lstrip("-").strip("\"'")


def _redacted(value: str | None) -> str | None:
    return "<redacted>" if value else None


def _display_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def translation_disabled(args) -> bool:
    return bool(args.only_parse_generate_pdf or args.skip_translation)


def resolve_cli_credentials(
    args, environment: dict[str, str] | None = None
) -> tuple[str | None, str | None]:
    if translation_disabled(args):
        return None, None
    source = os.environ if environment is None else environment
    main_key = args.openai_api_key or source.get("OPENAI_API_KEY")
    term_key = args.openai_term_extraction_api_key or main_key
    return main_key, term_key


def build_translators(args, environment: dict[str, str] | None = None):
    if translation_disabled(args):
        translator = NoNetworkTranslator(args.lang_in, args.lang_out)
        return translator, translator
    if not args.openai:
        raise ValueError("必须选择一个翻译服务：--openai")
    main_key, term_key = resolve_cli_credentials(args, environment)
    if not main_key:
        raise ValueError("使用 OpenAI 服务时必须提供 API key 或 OPENAI_API_KEY")

    translator_kwargs: dict[str, Any] = {}
    if args.openai_reasoning is not None:
        translator_kwargs["reasoning"] = args.openai_reasoning
    if args.openai_thinking is not None:
        translator_kwargs["thinking"] = args.openai_thinking
    try:
        translator = OpenAITranslator(
            lang_in=args.lang_in,
            lang_out=args.lang_out,
            model=args.openai_model,
            base_url=args.openai_base_url,
            api_key=main_key,
            ignore_cache=args.ignore_cache,
            enable_json_mode_if_requested=args.enable_json_mode_if_requested,
            send_dashscope_header=args.send_dashscope_header,
            send_temperature=not args.no_send_temperature,
            **translator_kwargs,
        )
        term_extraction_translator = translator
        if (
            args.openai_term_extraction_model
            or args.openai_term_extraction_base_url
            or args.openai_term_extraction_api_key
        ):
            term_translator_kwargs: dict[str, Any] = {}
            if args.openai_term_extraction_reasoning is not None:
                term_translator_kwargs["reasoning"] = (
                    args.openai_term_extraction_reasoning
                )
            term_extraction_translator = OpenAITranslator(
                lang_in=args.lang_in,
                lang_out=args.lang_out,
                model=args.openai_term_extraction_model or args.openai_model,
                base_url=(args.openai_term_extraction_base_url or args.openai_base_url),
                api_key=term_key,
                ignore_cache=args.ignore_cache,
                enable_json_mode_if_requested=args.enable_json_mode_if_requested,
                send_dashscope_header=args.send_dashscope_header,
                send_temperature=not args.no_send_temperature,
                **term_translator_kwargs,
            )
    except Exception as exc:
        raise ValueError("无法初始化 OpenAI 翻译器；请检查服务配置") from exc
    return translator, term_extraction_translator


def redact_sensitive_text(text: object, args) -> str:
    redacted = str(text)
    main_key, term_key = resolve_cli_credentials(args)
    for secret in {
        main_key,
        term_key,
        args.openai_api_key,
        args.openai_term_extraction_api_key,
    }:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    for value in {args.openai_base_url, args.openai_term_extraction_base_url}:
        if value:
            redacted = redacted.replace(value, _display_url(value) or "<redacted>")
    return redacted


def effective_config_report(args) -> tuple[dict, list[str]]:
    profile = resolve_magazine_profile(args.magazine_mode, args.magazine_profile)
    switches = dict(SWITCH_DEFAULTS if profile is None else profile.switches)
    inputs = [input_summary(_normalized_file(value)) for value in (args.files or ())]
    reviews = resolve_reviews_dir(args.magazine_reviews_dir)
    resources = resource_availability()
    main_key, term_key = resolve_cli_credentials(args)
    errors = [issue.message for issue in validate_magazine_switches(switches)]
    for kind, status in resources.items():
        if not status["available"]:
            errors.append(f"runtime {kind} resources are unavailable")
    if switches["magazine_hitl_apply"]:
        from babeldoc.magazine.hitl import DECISIONS_SUFFIX

        for summary in inputs:
            decision = reviews / f"{Path(summary['path']).stem}{DECISIONS_SUFFIX}"
            if not decision.is_file():
                errors.append(f"HITL decisions file not found: {decision}")
    profile_record = None
    if profile is not None:
        profile_record = {
            "name": profile.name,
            "version": profile.version,
            "sha256": profile.sha256,
            "source": logical_resource_name(profile.source),
        }
    report = {
        "diagnostics": {
            "debug": bool(args.debug),
            "show_char_box": bool(args.show_char_box),
        },
        "inputs": inputs,
        "mode": args.magazine_mode,
        "profile": profile_record,
        "resources": resources,
        "reviews_dir": str(reviews),
        "service": {
            "openai": {
                "api_key": _redacted(main_key),
                "base_url": _display_url(args.openai_base_url),
                "enabled": bool(args.openai),
                "model": args.openai_model,
            },
            "term_extraction": {
                "api_key": _redacted(term_key),
                "base_url": _display_url(
                    args.openai_term_extraction_base_url or args.openai_base_url
                ),
                "model": args.openai_term_extraction_model or args.openai_model,
            },
        },
        "switches": switches,
        "validation": {"errors": errors, "ok": not errors},
    }
    return report, errors


async def main():
    parser = create_parser()
    args: Any = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if (
        args.validate_config
        or args.print_effective_config
        or args.magazine_mode is not None
        or args.magazine_profile is not None
    ):
        try:
            effective, config_errors = effective_config_report(args)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        if config_errors:
            parser.error("; ".join(config_errors))
        if args.print_effective_config:
            print(
                json.dumps(
                    effective,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        if args.validate_config:
            print("Configuration valid.")
            return

    if args.generate_offline_assets:
        babeldoc.assets.assets.generate_offline_assets_package(
            Path(args.generate_offline_assets)
        )
        logger.info("Offline assets package generated, exiting...")
        return

    if args.restore_offline_assets:
        babeldoc.assets.assets.restore_offline_assets_package(
            Path(args.restore_offline_assets)
        )
        logger.info("Offline assets package restored, exiting...")
        return

    if args.warmup:
        babeldoc.assets.assets.warmup()
        logger.info("Warmup completed, exiting...")
        return

    if args.enable_process_pool:
        enable_process_pool()

    try:
        translator, term_extraction_translator = build_translators(args)
    except ValueError as exc:
        parser.error(str(exc))

    # 设置翻译速率限制
    set_translate_rate_limiter(args.qps)
    # 初始化文档布局模型
    if args.rpc_doclayout:
        from babeldoc.docvision.rpc_doclayout import RpcDocLayoutModel

        doc_layout_model = RpcDocLayoutModel(host=args.rpc_doclayout)
    elif args.rpc_doclayout2:
        from babeldoc.docvision.rpc_doclayout2 import RpcDocLayoutModel

        doc_layout_model = RpcDocLayoutModel(host=args.rpc_doclayout2)
    elif args.rpc_doclayout3:
        from babeldoc.docvision.rpc_doclayout3 import RpcDocLayoutModel

        doc_layout_model = RpcDocLayoutModel(host=args.rpc_doclayout3)
    elif args.rpc_doclayout4:
        from babeldoc.docvision.rpc_doclayout4 import RpcDocLayoutModel

        doc_layout_model = RpcDocLayoutModel(host=args.rpc_doclayout4)
    elif args.rpc_doclayout5:
        from babeldoc.docvision.rpc_doclayout5 import RpcDocLayoutModel

        doc_layout_model = RpcDocLayoutModel(host=args.rpc_doclayout5)
    elif args.rpc_doclayout6:
        from babeldoc.docvision.rpc_doclayout6 import RpcDocLayoutModel

        doc_layout_model = RpcDocLayoutModel(host=args.rpc_doclayout6)
    elif args.rpc_doclayout7:
        from babeldoc.docvision.rpc_doclayout7 import RpcDocLayoutModel

        doc_layout_model = RpcDocLayoutModel(host=args.rpc_doclayout7)
    else:
        from babeldoc.docvision.doclayout import DocLayoutModel

        doc_layout_model = DocLayoutModel.load_onnx()

    if args.translate_table_text:
        from babeldoc.docvision.table_detection.rapidocr import RapidOCRModel

        table_model = RapidOCRModel()
    else:
        table_model = None

    # Load glossaries
    loaded_glossaries: list[Glossary] = []
    if args.glossary_files:
        paths_str = args.glossary_files.split(",")
        for p_str in paths_str:
            file_path = Path(p_str.strip())
            if not file_path.exists():
                logger.error(f"Glossary file not found: {file_path}")
                continue
            if not file_path.is_file():
                logger.error(f"Glossary path is not a file: {file_path}")
                continue
            try:
                glossary_obj = Glossary.from_csv(file_path, args.lang_out)
                if glossary_obj.entries:
                    loaded_glossaries.append(glossary_obj)
                    logger.info(
                        f"Loaded glossary '{glossary_obj.name}' with {len(glossary_obj.entries)} entries."
                    )
                else:
                    logger.info(
                        f"Glossary '{file_path.stem}' loaded with no applicable entries for lang_out '{args.lang_out}'."
                    )
            except Exception as e:
                logger.error(f"Failed to load glossary from {file_path}: {e}")

    pending_files = []
    for file in args.files:
        # 清理文件路径，去除两端的引号
        if file.startswith("--files="):
            file = file[len("--files=") :]
        file = file.lstrip("-").strip("\"'")
        if not Path(file).exists():
            logger.error(f"文件不存在：{file}")
            exit(1)
        if not file.lower().endswith(".pdf"):
            logger.error(f"文件不是 PDF 文件：{file}")
            exit(1)
        pending_files.append(file)

    if args.output:
        if not Path(args.output).exists():
            logger.info(f"输出目录不存在，创建：{args.output}")
            try:
                Path(args.output).mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.critical(
                    f"Failed to create output folder at {args.output}",
                    exc_info=True,
                )
                exit(1)
    else:
        args.output = None

    if args.working_dir:
        working_dir = Path(args.working_dir)
        if not working_dir.exists():
            logger.info(f"工作目录不存在，创建：{working_dir}")
            try:
                working_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.critical(
                    f"Failed to create working directory at {working_dir}",
                    exc_info=True,
                )
                exit(1)
    else:
        working_dir = None

    watermark_output_mode = WatermarkOutputMode.Watermarked
    if args.no_watermark:
        watermark_output_mode = WatermarkOutputMode.NoWatermark
    elif args.watermark_output_mode == "both":
        watermark_output_mode = WatermarkOutputMode.Both
    elif args.watermark_output_mode == "watermarked":
        watermark_output_mode = WatermarkOutputMode.Watermarked
    elif args.watermark_output_mode == "no_watermark":
        watermark_output_mode = WatermarkOutputMode.NoWatermark

    split_strategy = None
    if args.max_pages_per_part:
        split_strategy = TranslationConfig.create_max_pages_per_part_split_strategy(
            args.max_pages_per_part
        )

    total_term_extraction_total_tokens = 0
    total_term_extraction_prompt_tokens = 0
    total_term_extraction_completion_tokens = 0
    total_term_extraction_cache_hit_prompt_tokens = 0

    for file in pending_files:
        # 清理文件路径，去除两端的引号
        file = file.strip("\"'")
        # 创建配置对象
        config = TranslationConfig(
            input_file=file,
            font=None,
            pages=args.pages,
            output_dir=args.output,
            translator=translator,
            term_extraction_translator=term_extraction_translator,
            debug=args.debug,
            lang_in=args.lang_in,
            lang_out=args.lang_out,
            no_dual=args.no_dual,
            no_mono=args.no_mono,
            qps=args.qps,
            formular_font_pattern=args.formular_font_pattern,
            formular_char_pattern=args.formular_char_pattern,
            split_short_lines=args.split_short_lines,
            short_line_split_factor=args.short_line_split_factor,
            doc_layout_model=doc_layout_model,
            skip_clean=args.skip_clean,
            dual_translate_first=args.dual_translate_first,
            disable_rich_text_translate=args.disable_rich_text_translate,
            enhance_compatibility=args.enhance_compatibility,
            use_alternating_pages_dual=args.use_alternating_pages_dual,
            report_interval=args.report_interval,
            min_text_length=args.min_text_length,
            watermark_output_mode=watermark_output_mode,
            split_strategy=split_strategy,
            table_model=table_model,
            show_char_box=args.show_char_box,
            skip_scanned_detection=args.skip_scanned_detection,
            ocr_workaround=args.ocr_workaround,
            custom_system_prompt=args.custom_system_prompt,
            working_dir=working_dir,
            add_formula_placehold_hint=args.add_formula_placehold_hint,
            disable_same_text_fallback=args.disable_same_text_fallback,
            glossaries=loaded_glossaries,
            pool_max_workers=args.pool_max_workers,
            auto_extract_glossary=args.auto_extract_glossary,
            auto_enable_ocr_workaround=args.auto_enable_ocr_workaround,
            primary_font_family=args.primary_font_family,
            only_include_translated_page=args.only_include_translated_page,
            save_auto_extracted_glossary=args.save_auto_extracted_glossary,
            enable_graphic_element_process=not args.disable_graphic_element_process,
            merge_alternating_line_numbers=args.merge_alternating_line_numbers,
            skip_translation=args.skip_translation,
            skip_form_render=args.skip_form_render,
            skip_curve_render=args.skip_curve_render,
            only_parse_generate_pdf=args.only_parse_generate_pdf,
            remove_non_formula_lines=args.remove_non_formula_lines,
            non_formula_line_iou_threshold=args.non_formula_line_iou_threshold,
            figure_table_protection_threshold=args.figure_table_protection_threshold,
            skip_formula_offset_calculation=args.skip_formula_offset_calculation,
            metadata_extra_data=args.metadata_extra_data,
            term_pool_max_workers=args.term_pool_max_workers,
            magazine_profile=args.magazine_profile,
            magazine_mode=args.magazine_mode,
            magazine_reviews_dir=args.magazine_reviews_dir,
        )

        def nop(_x):
            pass

        getattr(doc_layout_model, "init_font_mapper", nop)(config)
        # Create progress handler
        progress_context, progress_handler = create_progress_handler(
            config, show_log=False
        )

        # 开始翻译
        with progress_context:
            async for event in babeldoc.format.pdf.high_level.async_translate(config):
                progress_handler(event)
                if config.debug:
                    debug_event = dict(event)
                    if event["type"] == "error":
                        debug_event["error"] = redact_sensitive_text(
                            event["error"], args
                        )
                    logger.debug(debug_event)
                if event["type"] == "error":
                    logger.error(
                        "Error: %s", redact_sensitive_text(event["error"], args)
                    )
                    break
                if event["type"] == "finish":
                    result = event["translate_result"]
                    logger.info(str(result))
                    break
        usage = config.term_extraction_token_usage
        total_term_extraction_total_tokens += usage["total_tokens"]
        total_term_extraction_prompt_tokens += usage["prompt_tokens"]
        total_term_extraction_completion_tokens += usage["completion_tokens"]
        total_term_extraction_cache_hit_prompt_tokens += usage[
            "cache_hit_prompt_tokens"
        ]
    logger.info(f"Total tokens: {translator.token_count.value}")
    logger.info(f"Prompt tokens: {translator.prompt_token_count.value}")
    logger.info(f"Completion tokens: {translator.completion_token_count.value}")
    logger.info(
        f"Cache hit prompt tokens: {translator.cache_hit_prompt_token_count.value}"
    )
    logger.info(
        "Term extraction tokens: total=%s prompt=%s completion=%s cache_hit_prompt=%s",
        total_term_extraction_total_tokens,
        total_term_extraction_prompt_tokens,
        total_term_extraction_completion_tokens,
        total_term_extraction_cache_hit_prompt_tokens,
    )
    if term_extraction_translator is not translator:
        logger.info(
            "Term extraction translator raw tokens: total=%s prompt=%s completion=%s cache_hit_prompt=%s",
            term_extraction_translator.token_count.value,
            term_extraction_translator.prompt_token_count.value,
            term_extraction_translator.completion_token_count.value,
            term_extraction_translator.cache_hit_prompt_token_count.value,
        )


def create_progress_handler(
    translation_config: TranslationConfig, show_log: bool = False
):
    """Create a progress handler function based on the configuration.

    Args:
        translation_config: The translation configuration.

    Returns:
        A tuple of (progress_context, progress_handler), where progress_context is a context
        manager that should be used to wrap the translation process, and progress_handler
        is a function that will be called with progress events.
    """
    if translation_config.use_rich_pbar:
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )
        translate_task_id = progress.add_task("translate", total=100)
        stage_tasks = {}

        def progress_handler(event):
            if show_log and random.random() <= 0.1:  # noqa: S311
                logger.info(event)
            if event["type"] == "progress_start":
                if event["stage"] not in stage_tasks:
                    stage_tasks[event["stage"]] = progress.add_task(
                        f"{event['stage']} ({event['part_index']}/{event['total_parts']})",
                        total=event.get("stage_total", 100),
                    )
            elif event["type"] == "progress_update":
                stage = event["stage"]
                if stage in stage_tasks:
                    progress.update(
                        stage_tasks[stage],
                        completed=event["stage_current"],
                        total=event["stage_total"],
                        description=f"{event['stage']} ({event['part_index']}/{event['total_parts']})",
                        refresh=True,
                    )
                progress.update(
                    translate_task_id,
                    completed=event["overall_progress"],
                    refresh=True,
                )
            elif event["type"] == "progress_end":
                stage = event["stage"]
                if stage in stage_tasks:
                    progress.update(
                        stage_tasks[stage],
                        completed=event["stage_total"],
                        total=event["stage_total"],
                        description=f"{event['stage']} ({event['part_index']}/{event['total_parts']})",
                        refresh=True,
                    )
                    progress.update(
                        translate_task_id,
                        completed=event["overall_progress"],
                        refresh=True,
                    )
                progress.refresh()

        return progress, progress_handler
    else:
        pbar = tqdm.tqdm(total=100, desc="translate")

        def progress_handler(event):
            if event["type"] == "progress_update":
                pbar.update(event["overall_progress"] - pbar.n)
                pbar.set_description(
                    f"{event['stage']} ({event['stage_current']}/{event['stage_total']})",
                )
            elif event["type"] == "progress_end":
                pbar.set_description(f"{event['stage']} (Complete)")
                pbar.refresh()

        return pbar, progress_handler


# for backward compatibility
def create_cache_folder():
    return babeldoc.format.pdf.high_level.create_cache_folder()


# for backward compatibility
def download_font_assets():
    return babeldoc.format.pdf.high_level.download_font_assets()


class EvictQueue(queue.Queue):
    def __init__(self, maxsize):
        self.discarded = 0
        super().__init__(maxsize)

    def put(self, item, block=False, timeout=None):
        while True:
            try:
                super().put(item, block=False)
                break
            except queue.Full:
                try:
                    self.get_nowait()
                    self.discarded += 1
                except queue.Empty:
                    pass


def speed_up_logs():
    import logging.handlers

    root_logger = logging.getLogger()
    log_que = EvictQueue(1000)
    queue_handler = logging.handlers.QueueHandler(log_que)
    queue_listener = logging.handlers.QueueListener(log_que, *root_logger.handlers)
    queue_listener.start()
    root_logger.handlers = [queue_handler]


def cli():
    """Command line interface entry point."""
    from rich.logging import RichHandler

    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])

    logging.getLogger("httpx").setLevel("CRITICAL")
    logging.getLogger("httpx").propagate = False
    logging.getLogger("openai").setLevel("CRITICAL")
    logging.getLogger("openai").propagate = False
    logging.getLogger("httpcore").setLevel("CRITICAL")
    logging.getLogger("httpcore").propagate = False
    logging.getLogger("http11").setLevel("CRITICAL")
    logging.getLogger("http11").propagate = False
    for v in logging.Logger.manager.loggerDict.values():
        if getattr(v, "name", None) is None:
            continue
        if (
            v.name.startswith("pdfminer")
            or v.name.startswith("peewee")
            or v.name.startswith("httpx")
            or "http11" in v.name
            or "openai" in v.name
            or "pdfminer" in v.name
        ):
            v.disabled = True
            v.propagate = False

    speed_up_logs()
    babeldoc.format.pdf.high_level.init()
    asyncio.run(main())


if __name__ == "__main__":
    if sys.platform == "darwin" or sys.platform == "win32":
        mp.set_start_method("spawn")
    else:
        mp.set_start_method("forkserver")
    cli()
