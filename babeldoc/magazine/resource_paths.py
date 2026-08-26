"""Resolve magazine data files in source checkouts and installed wheels."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PACKAGE_ROOT.parent
PACKAGED_ROOT = PACKAGE_ROOT / "_resources"
RESOURCE_KINDS = frozenset({"configs", "prompts"})


def _validate(kind: str, name: str | None = None) -> None:
    if kind not in RESOURCE_KINDS:
        raise ValueError(f"unknown magazine resource kind {kind!r}")
    if name is not None and (not name or Path(name).name != name):
        raise ValueError(f"magazine resource name must be a file name: {name!r}")


def resource_dir(kind: str) -> Path:
    """Prefer repository data and fall back to the wheel-owned copy."""
    _validate(kind)
    source = SOURCE_ROOT / kind
    return source if source.is_dir() else PACKAGED_ROOT / kind


def resource_path(kind: str, name: str) -> Path:
    """Resolve one resource while keeping a useful path when it is missing."""
    _validate(kind, name)
    source = SOURCE_ROOT / kind / name
    if source.is_file():
        return source
    return PACKAGED_ROOT / kind / name


def config_path(name: str) -> Path:
    return resource_path("configs", name)


def prompt_path(name: str) -> Path:
    return resource_path("prompts", name)


def logical_resource_name(path: str | Path) -> str:
    """Return a stable manifest name independent of installation location."""
    resolved = Path(path).resolve()
    for kind in sorted(RESOURCE_KINDS):
        for root in (SOURCE_ROOT / kind, PACKAGED_ROOT / kind):
            try:
                relative = resolved.relative_to(root.resolve())
            except ValueError:
                continue
            return (Path(kind) / relative).as_posix()
    return resolved.as_posix()
