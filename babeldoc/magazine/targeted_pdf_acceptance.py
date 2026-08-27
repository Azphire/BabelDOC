"""Fail-closed, offline acceptance for a manifested targeted PDF run."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pymupdf

from babeldoc.magazine.final_pdf_validator import ComplianceExpectations
from babeldoc.magazine.final_pdf_validator import FinalPdfValidator
from babeldoc.magazine.final_pdf_validator import normalize_text
from babeldoc.magazine.hitl_expectation import ManualConstraintExpectation
from babeldoc.magazine.manual_constraint_validator import PAGE_POLICY_CONFIG
from babeldoc.magazine.manual_constraint_validator import PAGE_TAXONOMY_CONFIG
from babeldoc.magazine.manual_constraint_validator import ManualOccurrenceObservation
from babeldoc.magazine.manual_constraint_validator import ValidationScope
from babeldoc.magazine.page_identity import PageSelectionMap

SCHEMA_VERSION = "targeted-pdf-acceptance.v1"
EXPECTATION_INVENTORY_VERSION = "manual-expectation-inventory.v1"
OBSERVATION_INVENTORY_VERSION = "manual-observation-inventory.v1"
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "access_token",
        "authorization",
        "credential",
        "raw_prompt",
        "prompt_text",
        "full_prompt",
        "raw_response",
        "full_response",
        "provider_response",
        "source_payload",
        "target_payload",
        "original_payload",
        "translated_payload",
    }
)
_SENSITIVE_MARKERS = {
    "authorization_bearer": b"authorization: bearer ",
    "raw_prompt_marker": b"begin raw prompt",
    "full_response_marker": b"provider full response",
    "credential_marker": b"simulated_credential=",
    "source_payload_marker": b"original_payload=",
    "target_payload_marker": b"translated_payload=",
}


class TargetedAcceptanceError(ValueError):
    """The run tree cannot identify one safe semantic output."""


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_within(root: Path, value: str, label: str) -> Path:
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TargetedAcceptanceError(f"{label} must stay within run_dir") from exc
    return candidate


def _walk_sensitive_json(value: Any, path: str = "$") -> list[tuple[str, str]]:
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in _SENSITIVE_KEYS:
                found.append((f"sensitive_json_key:{normalized}", f"{path}.{key}"))
            found.extend(_walk_sensitive_json(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_walk_sensitive_json(item, f"{path}[{index}]"))
    return found


def scan_sensitive_artifacts(run_dir: str | Path) -> tuple[dict[str, Any], ...]:
    """Scan every small text artifact and return hashes/locations, never payloads."""

    root = Path(run_dir).resolve()
    violations = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix.casefold() in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            continue
        if path.stat().st_size > 8 * 1024 * 1024:
            continue
        payload = path.read_bytes()
        matches: list[tuple[str, str | None]] = []
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            lowered = payload.lower()
            matches.extend(
                (rule_id, None)
                for rule_id, marker in _SENSITIVE_MARKERS.items()
                if marker in lowered
            )
        else:
            matches.extend(_walk_sensitive_json(decoded))
            lowered = payload.lower()
            matches.extend(
                (rule_id, None)
                for rule_id, marker in _SENSITIVE_MARKERS.items()
                if marker in lowered
            )
        for rule_id, json_path in sorted(set(matches)):
            violations.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "rule_id": rule_id,
                    "json_path": json_path,
                }
            )
    return tuple(violations)


def _box(page) -> tuple[float, float, float, float]:
    return tuple(float(value) for value in page.cropbox)


def _fixed_asset_signature(page) -> tuple:
    images = []
    for item in page.get_image_info(xrefs=True):
        digest = item.get("digest")
        images.append(
            (
                "image",
                (
                    None
                    if digest is None
                    else digest.hex()
                    if isinstance(digest, bytes)
                    else str(digest)
                ),
                tuple(float(value) for value in item.get("bbox", ())),
            )
        )
    xobjects = [
        (
            "xobject",
            int(item[0]),
            tuple(float(value) for value in item[3]) if len(item) > 3 else (),
        )
        for item in page.get_xobjects()
    ]
    return tuple(sorted(images + xobjects))


def validate_debug_invariance(
    semantic_pdf: str | Path,
    debug_pdf: str | Path,
) -> dict[str, Any]:
    """Require identical semantic text/boxes/fixed assets; drawings may be added."""

    semantic = pymupdf.open(semantic_pdf)
    debug = pymupdf.open(debug_pdf)
    page_rows = []
    holds = len(semantic) == len(debug)
    for index in range(min(len(semantic), len(debug))):
        left = semantic[index]
        right = debug[index]
        geometry_holds = _box(left) == _box(right) and left.rotation == right.rotation
        text_holds = normalize_text(left.get_text("text")) == normalize_text(
            right.get_text("text")
        )
        assets_hold = _fixed_asset_signature(left) == _fixed_asset_signature(right)
        drawings_before = len(left.get_drawings())
        drawings_after = len(right.get_drawings())
        row_holds = geometry_holds and text_holds and assets_hold
        holds = holds and row_holds
        page_rows.append(
            {
                "output_index": index,
                "geometry_holds": geometry_holds,
                "text_holds": text_holds,
                "fixed_assets_hold": assets_hold,
                "diagnostic_drawings_added": max(0, drawings_after - drawings_before),
                "holds": row_holds,
            }
        )
    semantic.close()
    debug.close()
    return {
        "status": "pass" if holds else "fail",
        "holds": holds,
        "pages": page_rows,
    }


def _inventory(path: Path, version: str, key: str, parser) -> tuple:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != version or not isinstance(raw.get(key), list):
        raise TargetedAcceptanceError(f"{path.name} has an unsupported inventory schema")
    return tuple(parser(item) for item in raw[key])


def _safe_status_projection(value: Any) -> Any:
    """Pass through bounded status/count/digest material, never arbitrary payloads."""

    if isinstance(value, dict):
        allowed = {
            "status",
            "count",
            "accepted",
            "rejected",
            "rolled_back",
            "sha256",
            "schema_version",
        }
        projected = {}
        for key, item in value.items():
            key = str(key)
            if key not in allowed:
                continue
            if key in {"status", "schema_version"}:
                projected[key] = (
                    item
                    if isinstance(item, str) and _SAFE_TOKEN_RE.fullmatch(item)
                    else None
                )
            elif key == "sha256":
                projected[key] = (
                    item
                    if isinstance(item, str) and _SHA256_RE.fullmatch(item)
                    else None
                )
            elif key in {"count", "accepted", "rejected", "rolled_back"}:
                projected[key] = (
                    item
                    if isinstance(item, int) and not isinstance(item, bool) and item >= 0
                    else None
                )
        return projected
    if isinstance(value, list):
        return [_safe_status_projection(item) for item in value]
    return None


def _config_contract_sha256() -> str:
    root = Path(__file__).resolve().parents[2]
    paths = (
        root / "configs/final_pdf_compliance.json",
        PAGE_POLICY_CONFIG,
        PAGE_TAXONOMY_CONFIG,
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _code_contract_sha256() -> str:
    root = Path(__file__).resolve().parents[2]
    paths = (
        root / "babeldoc/magazine/page_identity.py",
        root / "babeldoc/magazine/final_pdf_validator.py",
        root / "babeldoc/magazine/manual_constraint_validator.py",
        root / "babeldoc/magazine/targeted_pdf_acceptance.py",
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def verify_targeted_run(
    *,
    source_pdf: str | Path,
    run_dir: str | Path,
    manifest_path: str | Path,
    expectations_path: str | Path,
    selected_pages: tuple[int, ...],
    report_path: str | Path,
    debug_copy: str | Path | None = None,
    scope: ValidationScope | str = ValidationScope.FULL_TRANSLATION,
) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    manifest_file = Path(manifest_path).resolve()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    semantic_value = manifest.get("semantic_output_pdf")
    candidates = manifest.get("semantic_output_candidates")
    if not isinstance(semantic_value, str) or not semantic_value:
        raise TargetedAcceptanceError("manifest must uniquely name semantic_output_pdf")
    if candidates is not None and candidates != [semantic_value]:
        raise TargetedAcceptanceError("manifest semantic output candidates are ambiguous")
    semantic_pdf = _resolve_within(root, semantic_value, "semantic_output_pdf")
    if not semantic_pdf.is_file():
        raise TargetedAcceptanceError("manifested semantic output PDF is missing")
    if debug_copy is not None and semantic_pdf == Path(debug_copy).resolve():
        raise TargetedAcceptanceError("debug copy cannot be the semantic output")

    mapping_record = manifest.get("page_selection_map")
    if isinstance(mapping_record, str):
        mapping_record = json.loads(
            _resolve_within(root, mapping_record, "page_selection_map").read_text(
                encoding="utf-8"
            )
        )
    if not isinstance(mapping_record, dict):
        raise TargetedAcceptanceError("manifest must contain one PageSelectionMap")
    mapping = PageSelectionMap.from_record(mapping_record)
    if tuple(int(page) for page in mapping.selected_physical_pages) != selected_pages:
        raise TargetedAcceptanceError("selected pages do not match manifested mapping")

    expectations = _inventory(
        Path(expectations_path),
        EXPECTATION_INVENTORY_VERSION,
        "expectations",
        ManualConstraintExpectation.from_record,
    )
    observation_value = manifest.get("manual_observations")
    observations = ()
    if observation_value is not None:
        if not isinstance(observation_value, str):
            raise TargetedAcceptanceError("manual_observations must be one path")
        observations = _inventory(
            _resolve_within(root, observation_value, "manual_observations"),
            OBSERVATION_INVENTORY_VERSION,
            "observations",
            ManualOccurrenceObservation.from_record,
        )

    validator_report = Path(report_path).with_suffix(".validator.json")
    validation = FinalPdfValidator().validate(
        source_pdf,
        semantic_pdf,
        validator_report,
        expectations=ComplianceExpectations(
            expected_page_count=len(mapping.output_index_to_physical_page),
            touched_pages=selected_pages,
            page_selection_map=mapping,
            manual_constraint_expectations=expectations,
            manual_constraint_observations=observations,
            validation_scope=ValidationScope(scope),
        ),
    )
    sensitive = scan_sensitive_artifacts(root)
    debug_result = None
    if debug_copy is not None:
        debug_path = Path(debug_copy).resolve()
        if not debug_path.is_file():
            raise TargetedAcceptanceError("debug copy is missing")
        debug_result = validate_debug_invariance(semantic_pdf, debug_path)
    residuals = list(validation.record.get("issues", ()))
    residuals.extend(
        {
            "code": "sensitive_artifact",
            "path": item["path"],
            "rule_id": item["rule_id"],
            "sha256": item["sha256"],
        }
        for item in sensitive
    )
    if debug_result is not None and not debug_result["holds"]:
        residuals.append({"code": "debug_semantic_invariance_failed"})
    parse_gate_pass = validation.status == "parse_gate_pass"
    debug_holds = debug_result is None or debug_result["holds"]
    overall = validation.fully_compliant and not sensitive and debug_holds
    accepted = (
        validation.fully_compliant or parse_gate_pass
    ) and not sensitive and debug_holds
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "parse_gate_pass" if accepted and parse_gate_pass else "pass" if overall else "fail"
        ),
        "overall": overall,
        "inputs": {
            "source_pdf_sha256": _sha256(source_pdf),
            "semantic_output_sha256": _sha256(semantic_pdf),
            "manifest_sha256": _sha256(manifest_file),
            "expectations_sha256": _sha256(expectations_path),
            "mapping_sha256": mapping.mapping_sha256,
            "config_contract_sha256": _config_contract_sha256(),
            "code_contract_sha256": _code_contract_sha256(),
        },
        "page_geometry_and_labels": validation.record.get("evidence", {}).get(
            "pages", ()
        ),
        "semantic_geometry_legality": [
            item
            for item in validation.record.get("checks", ())
            if item.get("name") in {"text_spans_within_page", "page_geometry"}
        ],
        "article_chain_runtrace_fixed_assets": {
            "references": validation.record.get("evidence", {}).get("references", ()),
            "fixed_assets": validation.record.get("evidence", {}).get("assets", ()),
        },
        "repair_transactions": _safe_status_projection(
            manifest.get("repair_transactions", {})
        ),
        "manual_expectations": validation.record.get("manual_constraints"),
        "debug_invariance": debug_result,
        "sensitive_artifacts": list(sensitive),
        "residuals": residuals,
        "formal_metric_status": _safe_status_projection(
            manifest.get("formal_metric_status", {})
        ),
        "validator": {
            "status": validation.status,
            "report_sha256": _sha256(validator_report),
        },
    }
    destination = Path(report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "EXPECTATION_INVENTORY_VERSION",
    "OBSERVATION_INVENTORY_VERSION",
    "SCHEMA_VERSION",
    "TargetedAcceptanceError",
    "scan_sensitive_artifacts",
    "validate_debug_invariance",
    "verify_targeted_run",
]
