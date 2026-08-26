"""Offline checks for built-in magazine modes and early CLI validation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.runtime_profile import MODE_NAMES  # noqa: E402
from babeldoc.magazine.runtime_profile import MODE_PROFILE_FILES  # noqa: E402
from babeldoc.magazine.runtime_profile import SWITCH_DEFAULTS  # noqa: E402
from babeldoc.magazine.runtime_profile import load_magazine_mode  # noqa: E402
from babeldoc.magazine.runtime_profile import preflight_magazine_runtime  # noqa: E402
from babeldoc.magazine.runtime_profile import resolve_reviews_dir  # noqa: E402
from babeldoc.main import create_parser  # noqa: E402
from babeldoc.main import effective_config_report  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail else ''}")


def run_cli(*arguments: str, env: dict[str, str] | None = None):
    clean_env = os.environ.copy()
    clean_env.pop("OPENAI_API_KEY", None)
    if env:
        clean_env.update(env)
    return subprocess.run(  # noqa: S603 - fixed Python argv runs the local CLI
        [sys.executable, "-m", "babeldoc.main", *arguments],
        cwd=ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def check_mode_profiles() -> None:
    expected = ("conservative", "automatic", "hitl-export", "hitl-apply")
    check("01a mode registry is closed and ordered", MODE_NAMES == expected)
    immutable = False
    try:
        MODE_PROFILE_FILES["extra"] = "extra.json"
    except TypeError:
        immutable = True
    check("01b mode registry is immutable", immutable)

    profiles = {name: load_magazine_mode(name) for name in MODE_NAMES}
    complete = all(
        set(profile.switches) == set(SWITCH_DEFAULTS)
        and all(type(value) is bool for value in profile.switches.values())
        for profile in profiles.values()
    )
    check("01c every built-in profile declares 22 booleans", complete)
    automatic = profiles["automatic"].switches
    check(
        "01d automatic disables only HITL",
        {name for name, value in automatic.items() if not value}
        == {"magazine_hitl_export", "magazine_hitl_apply"},
    )
    exported = profiles["hitl-export"].switches
    check(
        "01e hitl-export adds export only",
        exported["magazine_hitl_export"]
        and not exported["magazine_hitl_apply"]
        and all(
            value == exported[name]
            for name, value in automatic.items()
            if name != "magazine_hitl_export"
        ),
    )
    check(
        "01f hitl-apply enables every switch",
        all(profiles["hitl-apply"].switches.values()),
    )


def check_cli_validation(root: Path) -> None:
    conservative = run_cli("--magazine-mode", "conservative", "--validate-config")
    check(
        "02a conservative validates without service or key",
        conservative.returncode == 0 and "Configuration valid." in conservative.stdout,
        conservative.stderr[-300:],
    )

    custom = run_cli(
        "--magazine-profile",
        str(ROOT / "configs" / "magazine_runtime_profile.v1.json"),
        "--validate-config",
    )
    check(
        "02b custom profile validates without service or key",
        custom.returncode == 0,
        custom.stderr[-300:],
    )

    exclusive = run_cli(
        "--magazine-mode",
        "automatic",
        "--magazine-profile",
        str(ROOT / "configs" / "magazine_runtime_profile.v1.json"),
        "--validate-config",
    )
    check(
        "02c mode and profile are rejected by argparse",
        exclusive.returncode == 2 and "not allowed with argument" in exclusive.stderr,
        exclusive.stderr[-300:],
    )

    effective = run_cli(
        "--magazine-mode",
        "automatic",
        "--print-effective-config",
    )
    payload = json.loads(effective.stdout) if effective.returncode == 0 else {}
    check(
        "02d effective config is complete, stable, and redacted",
        effective.returncode == 0
        and payload.get("mode") == "automatic"
        and len(payload.get("switches") or {}) == 22
        and payload.get("service", {}).get("openai", {}).get("api_key") is None
        and payload.get("resources", {}).get("configs", {}).get("available") is True
        and payload.get("resources", {}).get("prompts", {}).get("available") is True
        and payload.get("validation") == {"errors": [], "ok": True},
        effective.stderr[-300:],
    )

    secret_args = create_parser().parse_args(
        [
            "--magazine-mode",
            "automatic",
            "--openai-api-key",
            "main-test-secret",
            "--openai-term-extraction-api-key",
            "term-test-secret",
            "--openai-base-url",
            "https://example.test/v1?token=url-test-secret",
            "--print-effective-config",
        ]
    )
    secret_report, secret_errors = effective_config_report(secret_args)
    encoded = json.dumps(secret_report, sort_keys=True)
    check(
        "02e effective config redacts keys and URL queries",
        not secret_errors
        and secret_report["service"]["openai"]["api_key"] == "<redacted>"
        and secret_report["service"]["term_extraction"]["api_key"]
        == "<redacted>"
        and "test-secret" not in encoded,
    )

    input_file = root / "sample.pdf"
    input_file.write_bytes(b"%PDF-1.7\n")
    reviews = root / "reviews"
    missing = run_cli(
        "--magazine-mode",
        "hitl-apply",
        "--magazine-reviews-dir",
        str(reviews),
        "--files",
        str(input_file),
        "--validate-config",
    )
    check(
        "02f hitl-apply rejects a missing decisions file before IL",
        missing.returncode == 2
        and "HITL decisions file not found" in missing.stderr,
        missing.stderr[-300:],
    )
    reviews.mkdir()
    (reviews / "sample.decisions.json").write_text("{}\n", encoding="utf-8")
    present = run_cli(
        "--magazine-mode",
        "hitl-apply",
        "--magazine-reviews-dir",
        str(reviews),
        "--files",
        str(input_file),
        "--validate-config",
    )
    check(
        "02g hitl-apply accepts the corresponding decisions file",
        present.returncode == 0,
        present.stderr[-300:],
    )


def check_reviews_and_manifest(root: Path) -> None:
    environment_reviews = root / "environment"
    explicit_reviews = root / "explicit"
    previous = os.environ.get(hitl.REVIEWS_ENV)
    os.environ[hitl.REVIEWS_ENV] = str(environment_reviews)
    try:
        toml_reviews = root / "toml"
        config_file = root / "babeldoc.toml"
        config_file.write_text(
            "[babeldoc]\n"
            'magazine-mode = "automatic"\n'
            f'magazine-reviews-dir = "{toml_reviews.as_posix()}"\n'
            "validate-config = true\n",
            encoding="utf-8",
        )
        parsed = create_parser().parse_args(["-c", str(config_file)])
        overridden = create_parser().parse_args(
            [
                "-c",
                str(config_file),
                "--magazine-reviews-dir",
                str(explicit_reviews),
            ]
        )
        check(
            "03a TOML and CLI review paths override the environment",
            parsed.magazine_mode == "automatic"
            and resolve_reviews_dir(parsed.magazine_reviews_dir)
            == toml_reviews.resolve()
            and resolve_reviews_dir(overridden.magazine_reviews_dir)
            == explicit_reviews.resolve(),
        )
        config = TranslationConfig(
            translator=object(),
            input_file=root / "manifest.pdf",
            lang_in="en",
            lang_out="zh",
            doc_layout_model=object(),
            working_dir=root / "work",
            output_dir=root / "out",
            magazine_mode="conservative",
            magazine_reviews_dir=explicit_reviews,
        )
        Path(config.input_file).write_bytes(b"%PDF-1.7\n")
        check(
            "03b explicit review directory wins over the environment",
            hitl.reviews_dir(config) == explicit_reviews.resolve(),
        )
        manifest_path = preflight_magazine_runtime(config)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        check(
            "03c manifest records mode and profile identity",
            manifest["mode"] == "conservative"
            and manifest["profile"]["name"] == "magazine-runtime"
            and manifest["profile"]["version"] == 1
            and len(manifest["profile"]["sha256"]) == 64
            and manifest["profile"]["source"]
            == "configs/magazine_runtime_profile.v1.json",
        )
    finally:
        if previous is None:
            os.environ.pop(hitl.REVIEWS_ENV, None)
        else:
            os.environ[hitl.REVIEWS_ENV] = previous


def main() -> int:
    check_mode_profiles()
    with tempfile.TemporaryDirectory(prefix="babeldoc-c16-modes-") as temp:
        root = Path(temp)
        check_cli_validation(root)
        check_reviews_and_manifest(root)
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(
        f"spec_check_startup_modes: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
