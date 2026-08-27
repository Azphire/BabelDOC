"""Versioned closed ArticleIR element-role vocabulary and raw-label evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("element_roles.json")
ELEMENT_ROLE_SCHEMA_VERSION = "element-roles.v1"


class ElementRole(StrEnum):
    BODY = "BODY"
    HEADING = "HEADING"
    CAPTION = "CAPTION"
    TOC_RECORD = "TOC_RECORD"
    RECORD = "RECORD"
    DROP_CAP = "DROP_CAP"
    FORMULA = "FORMULA"
    FURNITURE = "FURNITURE"
    PASSTHROUGH = "PASSTHROUGH"
    UNCLASSIFIED = "UNCLASSIFIED"


PROTECTED_ROLES = frozenset(set(ElementRole) - {ElementRole.BODY})


class ElementRoleConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RoleMapping:
    role: ElementRole
    raw_layout_label: str | None
    reason: str
    allowed_consumers: tuple[str, ...]

    @property
    def protected(self) -> bool:
        return self.role in PROTECTED_ROLES


@dataclass(frozen=True, slots=True)
class ElementRoleConfig:
    schema_version: str
    mappings: dict[str, RoleMapping]
    unknown: RoleMapping


@lru_cache(maxsize=2)
def load_element_role_config(path: str | None = None) -> ElementRoleConfig:
    source = CONFIG_PATH if path is None else Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if raw.get("schema_version") != ELEMENT_ROLE_SCHEMA_VERSION:
        raise ElementRoleConfigError("unsupported element role schema")
    declared = set(ElementRole)
    mappings: dict[str, RoleMapping] = {}
    for label, record in raw.get("mappings", {}).items():
        if not isinstance(label, str) or not label:
            raise ElementRoleConfigError("raw layout labels must be non-empty strings")
        try:
            role = ElementRole(record["role"])
        except (KeyError, ValueError) as exc:
            raise ElementRoleConfigError(f"unknown role for raw label {label!r}") from exc
        consumers = tuple(record.get("allowed_consumers", ()))
        if not consumers or any(not isinstance(item, str) for item in consumers):
            raise ElementRoleConfigError(f"{label!r} must declare allowed_consumers")
        mappings[label] = RoleMapping(role, label, "declared_raw_label", consumers)
    unknown = raw.get("unknown_fallback") or {}
    if set(ElementRole) != declared or unknown.get("role") != ElementRole.UNCLASSIFIED:
        raise ElementRoleConfigError("unknown raw labels must map to UNCLASSIFIED")
    unknown_consumers = tuple(unknown.get("allowed_consumers", ()))
    if any(item in unknown_consumers for item in ("article_flow", "chain")):
        raise ElementRoleConfigError("UNCLASSIFIED cannot enter flow or chain")
    return ElementRoleConfig(
        schema_version=ELEMENT_ROLE_SCHEMA_VERSION,
        mappings=mappings,
        unknown=RoleMapping(
            ElementRole.UNCLASSIFIED,
            None,
            str(unknown.get("reason") or "unknown_raw_layout_label"),
            unknown_consumers,
        ),
    )


def map_layout_label(label: str | None) -> RoleMapping:
    config = load_element_role_config()
    if label is None:
        return config.unknown
    return config.mappings.get(label, config.unknown)


def coerce_element_role(value: ElementRole | str | None) -> ElementRole:
    if isinstance(value, ElementRole):
        return value
    if value is None:
        return ElementRole.UNCLASSIFIED
    text = str(value)
    try:
        return ElementRole(text.upper())
    except ValueError:
        return map_layout_label(text).role
