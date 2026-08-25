"""Load, validate, and record the effective magazine runtime profile."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = ROOT / "configs" / "magazine_runtime_profile.v1.json"
RUN_MANIFEST_NAME = "magazine_run_manifest.json"
PROFILE_FORMAT_VERSION = 1

SWITCH_DEFAULTS: dict[str, bool] = {
    "magazine_checkpoint": False,
    "magazine_page_classify": False,
    "magazine_chain_detect": False,
    "magazine_chain_translate": False,
    "magazine_article_group": False,
    "magazine_article_context": False,
    "magazine_hitl_export": False,
    "magazine_hitl_apply": False,
    "magazine_detect": False,
    "magazine_column_reflow": False,
    "magazine_drop_cap_apply": False,
    "magazine_drop_cap_mark": False,
    "magazine_drop_cap_render": False,
    "magazine_formula_reclass": False,
    "magazine_fragment_stitch": False,
    "magazine_indent_policy": False,
    "magazine_line_structure": False,
    "magazine_paren_dedup": True,
    "magazine_repair": False,
    "magazine_rotated_lane": False,
    "magazine_title_typeset": False,
}

NETWORK_CAPABLE_SWITCHES = frozenset(
    {
        "magazine_article_context",
        "magazine_chain_translate",
        "magazine_repair",
    }
)


class MagazineProfileError(ValueError):
    """Raised when a magazine profile does not satisfy its data contract."""


@dataclass(frozen=True, slots=True)
class MagazineRuntimeProfile:
    name: str
    version: int
    switches: dict[str, bool]
    source: Path
    sha256: str

    def to_dict(self) -> dict:
        return {
            "format_version": PROFILE_FORMAT_VERSION,
            "profile": self.name,
            "version": self.version,
            "switches": dict(self.switches),
        }


@dataclass(frozen=True, slots=True)
class DependencyIssue:
    code: str
    switch: str
    requires: tuple[str, ...]
    message: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "switch": self.switch,
            "requires": list(self.requires),
            "message": self.message,
        }


class MagazineDependencyError(ValueError):
    """Raised before IL creation when enabled switches have missing inputs."""

    def __init__(self, issues: tuple[DependencyIssue, ...]):
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MagazineProfileError(message)


def _profile_source(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def parse_magazine_profile(
    raw: object, source: str, path: Path, sha256: str
) -> MagazineRuntimeProfile:
    _require(isinstance(raw, dict), f"{source}: root must be an object")
    expected = {"format_version", "profile", "version", "switches"}
    _require(set(raw) == expected, f"{source}: keys must be {sorted(expected)}")
    _require(
        raw["format_version"] == PROFILE_FORMAT_VERSION,
        f"{source}: unsupported format_version {raw['format_version']!r}",
    )
    _require(
        isinstance(raw["profile"], str) and bool(raw["profile"]),
        f"{source}: profile must be a non-empty string",
    )
    _require(
        isinstance(raw["version"], int) and not isinstance(raw["version"], bool),
        f"{source}: version must be an integer",
    )
    switches = raw["switches"]
    _require(isinstance(switches, dict), f"{source}: switches must be an object")
    missing = sorted(set(SWITCH_DEFAULTS) - set(switches))
    unknown = sorted(set(switches) - set(SWITCH_DEFAULTS))
    _require(not missing, f"{source}: missing switches {missing}")
    _require(not unknown, f"{source}: unknown switches {unknown}")
    invalid = sorted(
        name for name, value in switches.items() if type(value) is not bool
    )
    _require(not invalid, f"{source}: switches must be booleans: {invalid}")
    return MagazineRuntimeProfile(
        name=raw["profile"],
        version=raw["version"],
        switches={name: switches[name] for name in SWITCH_DEFAULTS},
        source=path.resolve(),
        sha256=sha256,
    )


def load_magazine_profile(path: str | Path | None = None) -> MagazineRuntimeProfile:
    profile_path = DEFAULT_PROFILE_PATH if path is None else Path(path)
    content = profile_path.read_bytes()
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise MagazineProfileError(f"{profile_path.name}: invalid JSON: {exc}") from exc
    return parse_magazine_profile(
        raw,
        profile_path.name,
        profile_path,
        hashlib.sha256(content).hexdigest(),
    )


def effective_switches(translation_config) -> dict[str, bool]:
    return {
        name: bool(getattr(translation_config, name, default))
        for name, default in SWITCH_DEFAULTS.items()
    }


def validate_magazine_switches(
    switches: dict[str, bool],
) -> tuple[DependencyIssue, ...]:
    issues: list[DependencyIssue] = []

    def require(switch: str, *dependencies: str) -> None:
        if not switches[switch]:
            return
        missing = tuple(name for name in dependencies if not switches[name])
        if not missing:
            return
        issues.append(
            DependencyIssue(
                code="missing_dependency",
                switch=switch,
                requires=missing,
                message=f"{switch} requires {', '.join(missing)}",
            )
        )

    require("magazine_chain_detect", "magazine_page_classify")
    require("magazine_chain_translate", "magazine_chain_detect")
    require("magazine_article_group", "magazine_page_classify")
    require("magazine_article_context", "magazine_article_group")
    require("magazine_fragment_stitch", "magazine_page_classify")
    require("magazine_line_structure", "magazine_page_classify")
    require(
        "magazine_indent_policy",
        "magazine_page_classify",
        "magazine_article_group",
    )
    require("magazine_drop_cap_mark", "magazine_article_group")
    require("magazine_drop_cap_apply", "magazine_drop_cap_mark")
    require("magazine_drop_cap_render", "magazine_drop_cap_apply")
    require("magazine_detect", "magazine_checkpoint")
    require(
        "magazine_column_reflow",
        "magazine_detect",
        "magazine_checkpoint",
        "magazine_article_group",
    )
    require("magazine_title_typeset", "magazine_detect")
    require("magazine_repair", "magazine_detect")
    require("magazine_rotated_lane", "magazine_repair")
    return tuple(issues)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _input_summary(input_file: str | Path) -> dict:
    path = Path(input_file)
    if not path.is_file():
        return {"path": str(path), "exists": False, "size": None, "sha256": None}
    return {
        "path": str(path),
        "exists": True,
        "size": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _code_head() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _profile_of(translation_config) -> MagazineRuntimeProfile | None:
    profile = getattr(translation_config, "magazine_runtime_profile", None)
    return profile if isinstance(profile, MagazineRuntimeProfile) else None


def _runtime_active(
    switches: dict[str, bool], profile: MagazineRuntimeProfile | None
) -> bool:
    return profile is not None or switches != SWITCH_DEFAULTS


def preflight_magazine_runtime(translation_config) -> Path | None:
    switches = effective_switches(translation_config)
    profile = _profile_of(translation_config)
    if not _runtime_active(switches, profile):
        return None
    issues = validate_magazine_switches(switches)
    validation = {
        "ok": not issues,
        "errors": [issue.to_dict() for issue in issues],
    }
    profile_record = None
    config_files: dict[str, str] = {}
    if profile is not None:
        profile_record = {"name": profile.name, "version": profile.version}
        config_files[_profile_source(profile.source)] = profile.sha256
    manifest = {
        "manifest_version": 1,
        "profile": profile_record,
        "effective_switches": switches,
        "config_files": config_files,
        "code_head": _code_head(),
        "input": _input_summary(translation_config.input_file),
        "validation": validation,
    }
    path = Path(translation_config.get_working_file_path(RUN_MANIFEST_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if issues:
        raise MagazineDependencyError(issues)
    return path


def record_runtime_blocked_reason(translation_config, issue: dict) -> Path:
    """Append one deterministic prerequisite failure to the run manifest."""
    path = Path(translation_config.get_working_file_path(RUN_MANIFEST_NAME))
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = {"manifest_version": 1}
    reasons = list(manifest.get("blocked_reasons") or ())
    row = dict(issue)
    if row not in reasons:
        reasons.append(row)
    manifest["blocked_reasons"] = sorted(
        reasons,
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
