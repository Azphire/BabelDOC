"""Offline checks for the public magazine runtime profile."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import sys
import tempfile
import types
from pathlib import Path

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

glossary_stub = types.ModuleType("babeldoc.glossary")
glossary_stub.Glossary = type("Glossary", (), {})
glossary_stub.GlossaryEntry = type("GlossaryEntry", (), {})
sys.modules["babeldoc.glossary"] = glossary_stub

translator_stub = types.ModuleType("babeldoc.translator.translator")
translator_stub.BaseTranslator = type("BaseTranslator", (), {})
sys.modules["babeldoc.translator.translator"] = translator_stub

from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.magazine import resource_paths  # noqa: E402
from babeldoc.magazine.runtime_profile import DEFAULT_PROFILE_PATH  # noqa: E402
from babeldoc.magazine.runtime_profile import NETWORK_CAPABLE_SWITCHES  # noqa: E402
from babeldoc.magazine.runtime_profile import RUN_MANIFEST_NAME  # noqa: E402
from babeldoc.magazine.runtime_profile import SWITCH_DEFAULTS  # noqa: E402
from babeldoc.magazine.runtime_profile import MagazineDependencyError  # noqa: E402
from babeldoc.magazine.runtime_profile import effective_switches  # noqa: E402
from babeldoc.magazine.runtime_profile import load_magazine_profile  # noqa: E402
from babeldoc.magazine.runtime_profile import parse_magazine_profile  # noqa: E402
from babeldoc.magazine.runtime_profile import preflight_magazine_runtime  # noqa: E402
from babeldoc.magazine.runtime_profile import validate_magazine_switches  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail else ''}")


def make_config(root: Path, **kwargs) -> TranslationConfig:
    root.mkdir(parents=True, exist_ok=True)
    input_file = root / "sample.pdf"
    input_file.write_bytes(b"profile-only fixture\n")
    return TranslationConfig(
        translator=object(),
        input_file=input_file,
        lang_in="en",
        lang_out="zh",
        doc_layout_model=object(),
        working_dir=root / "work",
        output_dir=root / "out",
        **kwargs,
    )


def switch_assignments() -> set[str]:
    pattern = re.compile(
        r'(?:^|\s)(?:[A-Z_]*SWITCH)\s*=\s*["\'](magazine_[a-z0-9_]+)["\']',
        re.MULTILINE,
    )
    found: set[str] = set()
    for path in (ROOT / "babeldoc" / "magazine").rglob("*.py"):
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


def check_public_inventory() -> None:
    signature = inspect.signature(TranslationConfig)
    missing = sorted(set(SWITCH_DEFAULTS) - set(signature.parameters))
    wrong_defaults = {
        name: signature.parameters[name].default
        for name, expected in SWITCH_DEFAULTS.items()
        if name in signature.parameters
        and signature.parameters[name].default is not expected
    }
    dynamic = switch_assignments()
    unknown = sorted(dynamic - set(SWITCH_DEFAULTS))
    check("01a all authoritative switches are public", not missing, str(missing))
    check(
        "01b public defaults preserve legacy behavior",
        not wrong_defaults,
        str(wrong_defaults),
    )
    check("01c every dynamic switch has one authority", not unknown, str(unknown))


def check_construct_and_round_trip(root: Path) -> None:
    default_config = make_config(root / "defaults")
    check(
        "02a default effective values are unchanged",
        effective_switches(default_config) == SWITCH_DEFAULTS,
    )

    values = {name: not default for name, default in SWITCH_DEFAULTS.items()}
    constructed = make_config(root / "constructed", **values)
    check(
        "02b every public switch is constructible",
        effective_switches(constructed) == values,
    )

    profile = load_magazine_profile(DEFAULT_PROFILE_PATH)
    encoded = json.dumps(profile.to_dict(), sort_keys=True).encode("utf-8")
    decoded = parse_magazine_profile(
        json.loads(encoded),
        "round-trip",
        DEFAULT_PROFILE_PATH,
        hashlib.sha256(encoded).hexdigest(),
    )
    check(
        "02c profile values and types round-trip",
        decoded.name == profile.name
        and decoded.version == profile.version
        and decoded.switches == profile.switches
        and all(type(value) is bool for value in decoded.switches.values()),
    )


def check_resource_resolution(root: Path) -> None:
    source_root = root / "source"
    packaged_root = root / "package" / "_resources"
    source_file = source_root / "configs" / "example.json"
    packaged_file = packaged_root / "configs" / "example.json"
    source_file.parent.mkdir(parents=True)
    packaged_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    packaged_file.write_text("wheel", encoding="utf-8")
    original_source = resource_paths.SOURCE_ROOT
    original_packaged = resource_paths.PACKAGED_ROOT
    try:
        resource_paths.SOURCE_ROOT = source_root
        resource_paths.PACKAGED_ROOT = packaged_root
        check(
            "02d source resource wins when present",
            resource_paths.config_path("example.json") == source_file,
        )
        source_file.unlink()
        resolved = resource_paths.config_path("example.json")
        check(
            "02e wheel resource fallback keeps a logical manifest name",
            resolved == packaged_file
            and resource_paths.logical_resource_name(resolved)
            == "configs/example.json",
        )
    finally:
        resource_paths.SOURCE_ROOT = original_source
        resource_paths.PACKAGED_ROOT = original_packaged


def check_formal_entry(root: Path) -> None:
    main_source = (ROOT / "babeldoc" / "main.py").read_text(encoding="utf-8")
    config = make_config(root / "entry", magazine_profile=DEFAULT_PROFILE_PATH)
    profile = load_magazine_profile(DEFAULT_PROFILE_PATH)
    check(
        "03 formal CLI entry loads the selected profile",
        '"--magazine-profile"' in main_source
        and "magazine_profile=args.magazine_profile" in main_source
        and effective_switches(config) == profile.switches
        and config.magazine_runtime_profile is not None,
    )


def issue_for(overrides: dict[str, bool], switch: str, dependency: str) -> bool:
    values = dict(SWITCH_DEFAULTS)
    values.update(overrides)
    return any(
        issue.switch == switch and dependency in issue.requires
        for issue in validate_magazine_switches(values)
    )


def check_dependencies() -> None:
    check(
        "04a render without apply is rejected",
        issue_for(
            {"magazine_drop_cap_render": True},
            "magazine_drop_cap_render",
            "magazine_drop_cap_apply",
        ),
    )
    check(
        "04b apply without mark is rejected",
        issue_for(
            {"magazine_drop_cap_apply": True},
            "magazine_drop_cap_apply",
            "magazine_drop_cap_mark",
        ),
    )
    check(
        "04c repair without detect is rejected",
        issue_for(
            {"magazine_repair": True},
            "magazine_repair",
            "magazine_detect",
        ),
    )
    check(
        "04d reflow without checkpoint is rejected",
        issue_for(
            {"magazine_column_reflow": True},
            "magazine_column_reflow",
            "magazine_checkpoint",
        ),
    )
    check(
        "04e source-geometry detection without checkpoint is rejected",
        issue_for(
            {"magazine_detect": True},
            "magazine_detect",
            "magazine_checkpoint",
        ),
    )
    profile = load_magazine_profile(DEFAULT_PROFILE_PATH)
    check(
        "04f shipped profile is a legal minimum",
        not validate_magazine_switches(profile.switches),
    )
    check(
        "04g shipped profile enables no network-capable feature",
        not any(profile.switches[name] for name in NETWORK_CAPABLE_SWITCHES),
    )
    check(
        "04h chain translation requires detection and article ownership",
        issue_for(
            {"magazine_chain_translate": True},
            "magazine_chain_translate",
            "magazine_chain_detect",
        )
        and issue_for(
            {"magazine_chain_translate": True},
            "magazine_chain_translate",
            "magazine_article_group",
        ),
    )
    check(
        "04i column reflow requires owner-scoped chain inputs",
        issue_for(
            {"magazine_column_reflow": True},
            "magazine_column_reflow",
            "magazine_article_group",
        )
        and issue_for(
            {"magazine_column_reflow": True},
            "magazine_column_reflow",
            "magazine_chain_detect",
        ),
    )


def check_manifest(root: Path) -> None:
    default_config = make_config(root / "inactive")
    inactive_path = Path(default_config.get_working_file_path(RUN_MANIFEST_NAME))
    check(
        "05a unselected default writes no new sidecar",
        preflight_magazine_runtime(default_config) is None
        and not inactive_path.exists(),
    )

    config = make_config(root / "active", magazine_profile=DEFAULT_PROFILE_PATH)
    first_path = preflight_magazine_runtime(config)
    first = first_path.read_bytes()
    second_path = preflight_magazine_runtime(config)
    second = second_path.read_bytes()
    manifest = json.loads(first)
    expected_hash = hashlib.sha256(DEFAULT_PROFILE_PATH.read_bytes()).hexdigest()
    check("05b manifest bytes are stable", first == second)
    check(
        "05c manifest records effective values",
        manifest["effective_switches"] == effective_switches(config),
    )
    check(
        "05d manifest records profile and config hash",
        manifest["profile"]["name"] == "magazine-runtime"
        and manifest["profile"]["version"] == 1
        and manifest["profile"]["sha256"] == expected_hash
        and manifest["profile"]["source"]
        == "configs/magazine_runtime_profile.v1.json"
        and set(manifest["config_files"])
        == {"configs/magazine_runtime_profile.v1.json"}
        and list(manifest["config_files"].values()) == [expected_hash],
    )
    check(
        "05e manifest records code, input, and validation",
        bool(manifest["code_head"])
        and manifest["input"]["exists"] is True
        and manifest["input"]["sha256"]
        and manifest["validation"] == {"ok": True, "errors": []},
    )

    invalid = make_config(root / "invalid", magazine_drop_cap_render=True)
    invalid_path = Path(invalid.get_working_file_path(RUN_MANIFEST_NAME))
    rejected = False
    try:
        preflight_magazine_runtime(invalid)
    except MagazineDependencyError:
        rejected = True
    failed_manifest = json.loads(invalid_path.read_text(encoding="utf-8"))
    check(
        "05f invalid profile fails with a structured manifest before IL",
        rejected
        and failed_manifest["validation"]["ok"] is False
        and bool(failed_manifest["validation"]["errors"]),
    )


def check_tool_entry() -> None:
    source = (ROOT / "tools" / "run_drift_trio.py").read_text(encoding="utf-8")
    check(
        "06 production tool no longer mutates config with setattr",
        "setattr(config," not in source and '"magazine_drop_cap_mark": True' in source,
    )


def main() -> int:
    check_public_inventory()
    with tempfile.TemporaryDirectory(prefix="babeldoc-c01-") as temp:
        root = Path(temp)
        check_construct_and_round_trip(root)
        check_resource_resolution(root)
        check_formal_entry(root)
        check_dependencies()
        check_manifest(root)
    check_tool_entry()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(
        "spec_check_magazine_runtime_profile: "
        f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
