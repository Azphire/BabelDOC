"""Load, validate, and record the effective magazine runtime profile."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from babeldoc.magazine.resource_paths import SOURCE_ROOT
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.resource_paths import logical_resource_name

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = config_path("magazine_runtime_profile.v1.json")
RUN_MANIFEST_NAME = "magazine_run_manifest.json"
MANIFEST_VERSION = 2
FINGERPRINT_SCHEMA_VERSION = "semantic-fingerprint.v1"
PROFILE_FORMAT_VERSION = 1
REVIEWS_ENV = "BABELDOC_REVIEWS_DIR"

MODE_PROFILE_FILES = MappingProxyType(
    {
        "conservative": "magazine_runtime_profile.v1.json",
        "automatic": "magazine_runtime_profile.automatic.v1.json",
        "hitl-export": "magazine_runtime_profile.hitl_export.v1.json",
        "hitl-apply": "magazine_runtime_profile.hitl_apply.v1.json",
    }
)
MODE_NAMES = tuple(MODE_PROFILE_FILES)

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
    "magazine_pdf_compliance": False,
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
    return logical_resource_name(path)


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


def load_magazine_mode(mode: str) -> MagazineRuntimeProfile:
    try:
        filename = MODE_PROFILE_FILES[mode]
    except KeyError as exc:
        raise MagazineProfileError(
            f"unknown magazine mode {mode!r}; expected one of {list(MODE_NAMES)}"
        ) from exc
    return load_magazine_profile(config_path(filename))


def resolve_magazine_profile(
    mode: str | None = None, profile: str | Path | None = None
) -> MagazineRuntimeProfile | None:
    if mode is not None and profile is not None:
        raise MagazineProfileError("magazine mode and profile are mutually exclusive")
    if mode is not None:
        return load_magazine_mode(mode)
    if profile is not None:
        return load_magazine_profile(profile)
    return None


def default_reviews_dir() -> Path:
    source_default = SOURCE_ROOT / "reviews"
    if (SOURCE_ROOT / "configs").is_dir():
        return source_default
    return Path.cwd() / "reviews"


def resolve_reviews_dir(path: str | Path | None = None) -> Path:
    selected = path or os.environ.get(REVIEWS_ENV) or default_reviews_dir()
    return Path(selected).expanduser().resolve()


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
    require(
        "magazine_chain_translate",
        "magazine_chain_detect",
        "magazine_article_group",
    )
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
        "magazine_chain_detect",
    )
    require("magazine_title_typeset", "magazine_detect")
    require("magazine_repair", "magazine_detect")
    require("magazine_rotated_lane", "magazine_repair")
    require("magazine_pdf_compliance", "magazine_article_group")
    return tuple(issues)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_summary(input_file: str | Path) -> dict:
    path = Path(input_file)
    if not path.is_file():
        return {"path": str(path), "exists": False, "size": None, "sha256": None}
    return {
        "path": str(path),
        "exists": True,
        "size": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _canonical_float(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("semantic fingerprint coordinates must be finite")
    rounded = Decimal(str(number)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        rounded = Decimal("0")
    return format(rounded, "f")


def _canonical_box(value) -> list[str] | None:
    if value is None:
        return None
    coordinates = [getattr(value, name, None) for name in ("x", "y", "x2", "y2")]
    if any(item is None for item in coordinates):
        return None
    return [_canonical_float(item) for item in coordinates]


def _canonical_value(value):
    if isinstance(value, float):
        return _canonical_float(value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def semantic_projection(stage: str, docs, article_document_ir=None) -> dict:
    """Canonical semantic state; diagnostic IDs and overlay items cannot enter it."""
    pages = []
    for page in docs.page or ():
        physical_page = int(page.page_number) + 1
        paragraphs = []
        for reading_order, paragraph in enumerate(page.pdf_paragraph or ()):
            paragraphs.append(
                {
                    "stable_ref": f"p{physical_page}#{reading_order}",
                    "reading_order": reading_order,
                    "role": getattr(paragraph, "layout_label", None)
                    or "unclassified",
                    "text": (getattr(paragraph, "unicode", None) or "")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n"),
                    "box": _canonical_box(getattr(paragraph, "box", None)),
                }
            )
        pages.append(
            {
                "physical_page_number": physical_page,
                "mediabox": _canonical_box(
                    getattr(getattr(page, "mediabox", None), "box", None)
                ),
                "cropbox": _canonical_box(
                    getattr(getattr(page, "cropbox", None), "box", None)
                ),
                "paragraphs": paragraphs,
            }
        )
    article_record = None
    if article_document_ir is not None:
        article_record = _canonical_value(article_document_ir.to_record())
    return {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "stage": stage,
        "pages": pages,
        "article_ir": article_record,
    }


def semantic_fingerprint(stage: str, docs, article_document_ir=None) -> str:
    payload = json.dumps(
        semantic_projection(stage, docs, article_document_ir),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def record_runtime_stage(
    translation_config,
    stage: str,
    *,
    docs=None,
    article_document_ir=None,
    overlay_ledger=None,
) -> str:
    """Append one deterministic stage digest to an existing run manifest."""
    if overlay_ledger is not None:
        digest = overlay_ledger.digest()
        schema_version = overlay_ledger.schema_version
    else:
        if docs is None:
            raise ValueError("semantic runtime stage requires a document")
        digest = semantic_fingerprint(stage, docs, article_document_ir)
        schema_version = FINGERPRINT_SCHEMA_VERSION
    digests = dict(getattr(translation_config, "semantic_stage_digests", {}))
    digests[stage] = digest
    translation_config.semantic_stage_digests = digests
    path = Path(translation_config.get_working_file_path(RUN_MANIFEST_NAME))
    if not path.exists():
        return digest
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records = dict(manifest.get("stage_records") or {})
    records[stage] = {
        "stage": stage,
        "schema_version": schema_version,
        "sha256": digest,
    }
    manifest["stage_records"] = records
    _atomic_write_json(path, manifest)
    return digest


def _code_head() -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed Git argv reads local metadata
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],  # noqa: S607
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
        source = _profile_source(profile.source)
        profile_record = {
            "name": profile.name,
            "version": profile.version,
            "sha256": profile.sha256,
            "source": source,
        }
        config_files[source] = profile.sha256
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "mode": getattr(translation_config, "magazine_mode", None),
        "profile": profile_record,
        "effective_switches": switches,
        "config_files": config_files,
        "code_head": _code_head(),
        "input": input_summary(translation_config.input_file),
        "reviews_dir": str(
            resolve_reviews_dir(
                getattr(translation_config, "magazine_reviews_dir", None)
            )
        ),
        "validation": validation,
    }
    preflight_material = {
        "schema_version": "runtime-preflight.v2",
        "input_sha256": manifest["input"]["sha256"],
        "profile_sha256": None if profile_record is None else profile_record["sha256"],
        "config_files": config_files,
        "effective_switches": switches,
        "code_head": manifest["code_head"],
    }
    manifest["stage_records"] = {
        "preflight": {
            "stage": "preflight",
            "schema_version": preflight_material["schema_version"],
            "sha256": hashlib.sha256(
                json.dumps(
                    preflight_material,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
    }
    path = Path(translation_config.get_working_file_path(RUN_MANIFEST_NAME))
    _atomic_write_json(path, manifest)
    if issues:
        raise MagazineDependencyError(issues)
    return path


def record_runtime_blocked_reason(translation_config, issue: dict) -> Path:
    """Append one deterministic prerequisite failure to the run manifest."""
    path = Path(translation_config.get_working_file_path(RUN_MANIFEST_NAME))
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = {"manifest_version": MANIFEST_VERSION}
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
    return _atomic_write_json(path, manifest)
