"""Validate and bind the redacted effective config to v4 HITL evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc import main as babeldoc_main  # noqa: E402

SCHEMA_VERSION = "bounded-run-intent.v2"
BINDING_EVIDENCE_VERSION = "hitl-binding-evidence.v1"


class RunIntentError(ValueError):
    pass


def _exact(value: object, keys: set[str], path: str) -> dict:
    if not isinstance(value, dict):
        raise RunIntentError(f"{path} must be an object")
    missing = sorted(keys - set(value))
    unknown = sorted(set(value) - keys)
    if missing or unknown:
        raise RunIntentError(f"{path} missing={missing} unknown={unknown}")
    return value


def _digest(value: object) -> str:
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RunIntentError("run-intent evidence is not canonical JSON") from exc
    return hashlib.sha256(canonical.encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: object, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RunIntentError(f"{path} must be 64 lowercase hex")
    return value


def validate_report(report: object, require_credentials: bool = False) -> dict:
    """Validate only the single-source effective report.

    This remains useful for local config diagnostics. A paid run must also use
    :func:`validate_bound_run_intent` so the human decisions and detached
    binding evidence participate in the digest.
    """
    report = _exact(
        report,
        {
            "schema_version",
            "diagnostics",
            "inputs",
            "languages",
            "mode",
            "selection",
            "profile",
            "resources",
            "paths",
            "service",
            "limits",
            "cache",
            "switches",
            "validation",
        },
        "$",
    )
    if report["schema_version"] != "effective-run-config.v1":
        raise RunIntentError("unknown effective report schema")
    diagnostics = _exact(
        report["diagnostics"], {"debug", "show_char_box"}, "diagnostics"
    )
    if not all(isinstance(value, bool) for value in diagnostics.values()):
        raise RunIntentError("diagnostic switches must be boolean")
    inputs = report["inputs"]
    if not isinstance(inputs, list) or not inputs:
        raise RunIntentError("at least one --files input is required")
    for index, item in enumerate(inputs):
        item = _exact(
            item, {"basename", "exists", "size", "sha256"}, f"inputs[{index}]"
        )
        if not isinstance(item["basename"], str) or not item["basename"]:
            raise RunIntentError(f"inputs[{index}].basename is invalid")
        if Path(item["basename"]).name != item["basename"]:
            raise RunIntentError(f"inputs[{index}].basename contains a path")
        if item["exists"] is not True:
            raise RunIntentError(f"inputs[{index}] does not exist")
        if not isinstance(item["size"], int) or item["size"] < 1:
            raise RunIntentError(f"inputs[{index}].size is invalid")
        _sha(item["sha256"], f"inputs[{index}].sha256")

    languages = _exact(report["languages"], {"in", "out"}, "languages")
    if not all(isinstance(languages[key], str) and languages[key] for key in languages):
        raise RunIntentError("language codes are invalid")
    selection = _exact(
        report["selection"], {"physical_pages", "output_mode"}, "selection"
    )
    output_mode = _exact(
        selection["output_mode"],
        {"bilingual", "monolingual", "watermark"},
        "selection.output_mode",
    )
    if not isinstance(output_mode["bilingual"], bool) or not isinstance(
        output_mode["monolingual"], bool
    ):
        raise RunIntentError("output mode booleans are invalid")
    if not output_mode["bilingual"] and not output_mode["monolingual"]:
        raise RunIntentError("all output modes are disabled")

    paths = _exact(report["paths"], {"working", "output", "reviews"}, "paths")
    allowed_paths = {
        "working": {"explicit", "temporary"},
        "output": {"explicit", "input_adjacent"},
        "reviews": {"explicit", "default"},
    }
    for key, allowed in allowed_paths.items():
        if paths[key] not in allowed:
            raise RunIntentError(f"paths.{key} has an unknown category")

    service = _exact(
        report["service"], {"openai", "term_extraction", "repair"}, "service"
    )
    openai = _exact(
        service["openai"],
        {
            "api_key",
            "base_url",
            "credential_configured",
            "enabled",
            "model",
            "tool_call_capability",
        },
        "service.openai",
    )
    term = _exact(
        service["term_extraction"],
        {"api_key", "base_url", "credential_configured", "model"},
        "service.term_extraction",
    )
    repair = _exact(service["repair"], {"model", "endpoint"}, "service.repair")
    for name, value in (("openai", openai["api_key"]), ("term", term["api_key"])):
        if value not in {None, "<redacted>"}:
            raise RunIntentError(f"effective report contains a {name} credential")
    if (
        require_credentials
        and openai["enabled"]
        and not openai["credential_configured"]
    ):
        raise PermissionError("BLOCKED_PENDING_CREDENTIAL")
    capability = _exact(
        openai["tool_call_capability"],
        {
            "version",
            "supported",
            "strict",
            "declaration",
            "endpoint_identity",
            "model",
        },
        "service.openai.tool_call_capability",
    )
    if capability["version"] != "strict-tool-capabilities.v1":
        raise RunIntentError("unknown tool-call capability version")
    if capability["supported"] is not True or capability["strict"] is not True:
        raise RunIntentError("strict tool calls are unsupported for the endpoint/model")
    if capability["model"] != openai["model"]:
        raise RunIntentError("tool-call capability is bound to a different model")
    effective_endpoint = openai["base_url"] or "https://api.openai.com/v1"
    if capability["endpoint_identity"] != effective_endpoint:
        raise RunIntentError("tool-call capability is bound to a different endpoint")
    if repair["model"] != openai["model"]:
        raise RunIntentError("repair model differs from the translator model")

    limits = _exact(
        report["limits"],
        {
            "qps",
            "pool_max_workers",
            "term_pool_max_workers",
            "translation_request_timeout_seconds",
            "tool_call_timeout_seconds",
            "repair_max_iterations",
            "repair_decide_max_attempts",
            "repair_max_issues_offered",
            "max_tool_call_attempts",
        },
        "limits",
    )
    bounds = {
        "qps": (1, 1000),
        "pool_max_workers": (1, 1000),
        "term_pool_max_workers": (1, 1000),
        "translation_request_timeout_seconds": (1, 600),
        "tool_call_timeout_seconds": (0, 600),
        "repair_max_iterations": (1, 10),
        "repair_decide_max_attempts": (1, 5),
        "repair_max_issues_offered": (1, 500),
        "max_tool_call_attempts": (1, 3),
    }
    for key, (low, high) in bounds.items():
        value = limits[key]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RunIntentError(f"limits.{key} is not numeric")
        if key == "tool_call_timeout_seconds":
            valid = low < value <= high
        else:
            valid = low <= value <= high
        if not valid:
            raise RunIntentError(f"limits.{key} is out of bounds")

    cache = _exact(report["cache"], {"ordinary_translation", "tool_calls"}, "cache")
    if any(value not in {"read_write", "bypass"} for value in cache.values()):
        raise RunIntentError("cache policy is unknown")
    validation = _exact(report["validation"], {"errors", "ok"}, "validation")
    if validation["ok"] is not True or validation["errors"] != []:
        raise RunIntentError("effective configuration did not validate")

    return {
        "effective_config_sha256": _digest(report),
        "input_sha256": [item["sha256"] for item in inputs],
        "model": openai["model"],
        "term_model": term["model"],
        "repair_model": repair["model"],
        "endpoint_identity": capability["endpoint_identity"],
        "capability_version": capability["version"],
        "capability_declaration": capability["declaration"],
        "physical_pages": selection["physical_pages"],
    }


def _legacy_record(value: object, path: str) -> dict | None:
    if value is None:
        return None
    record = _exact(value, {"format_version", "sha256"}, path)
    if not isinstance(record["format_version"], int):
        raise RunIntentError(f"{path}.format_version is invalid")
    _sha(record["sha256"], f"{path}.sha256")
    return record


def validate_bound_artifacts(
    decisions: object,
    binding_report: object,
    *,
    decisions_sha256: str,
    effective_input_sha256: list[str],
) -> dict:
    decisions = _exact(
        decisions,
        {
            "format_version",
            "sample",
            "source_binding",
            "review_manifest_sha256",
            "lineage",
            "page_kinds",
            "terms",
            "drop_caps",
            "decision_refs",
        },
        "decisions",
    )
    if decisions["format_version"] != 4:
        raise RunIntentError("decisions must be a source-bound v4 envelope")
    if not isinstance(decisions["sample"], str) or not decisions["sample"]:
        raise RunIntentError("decisions.sample is invalid")
    source_binding = _exact(
        decisions["source_binding"],
        {
            "source_pdf_sha256",
            "source_page_count",
            "page_box_rotation_manifest_sha256",
            "semantic_digest_schema_version",
            "per_physical_page_semantic_sha256",
            "parser_layout_model_identity",
            "parser_layout_model_digest",
            "semantic_config_digest",
            "code_contract_version",
        },
        "decisions.source_binding",
    )
    source_sha = _sha(source_binding["source_pdf_sha256"], "source_pdf_sha256")
    if source_sha not in effective_input_sha256:
        raise RunIntentError("v4 decisions are bound to a different source PDF")
    if (
        not isinstance(source_binding["source_page_count"], int)
        or source_binding["source_page_count"] < 1
    ):
        raise RunIntentError("source page count is invalid")
    _sha(source_binding["page_box_rotation_manifest_sha256"], "page manifest")
    _sha(source_binding["parser_layout_model_digest"], "parser/layout digest")
    _sha(source_binding["semantic_config_digest"], "semantic config digest")
    pages = source_binding["per_physical_page_semantic_sha256"]
    if not isinstance(pages, dict) or len(pages) != source_binding["source_page_count"]:
        raise RunIntentError("per-page semantic digest manifest is incomplete")
    for page, digest in pages.items():
        if not isinstance(page, str) or not page.isdigit():
            raise RunIntentError("per-page semantic digest key is invalid")
        _sha(digest, f"per-page semantic digest {page}")
    review_sha = _sha(decisions["review_manifest_sha256"], "review manifest")
    lineage = _exact(
        decisions["lineage"],
        {
            "binding_mode",
            "legacy_review",
            "legacy_decisions",
            "legacy_review_cycle_unverified",
            "rebuilt_review_manifest_sha256",
            "binding_evidence_schema_version",
            "binding_evidence_sha256",
        },
        "decisions.lineage",
    )
    if lineage["binding_mode"] not in {"native_v4", "legacy_explicit_rebind"}:
        raise RunIntentError("unknown binding mode")
    legacy_review = _legacy_record(lineage["legacy_review"], "legacy_review")
    legacy_decisions = _legacy_record(lineage["legacy_decisions"], "legacy_decisions")
    if lineage["binding_mode"] == "legacy_explicit_rebind":
        if (
            legacy_review is None
            or legacy_decisions is None
            or lineage["legacy_review_cycle_unverified"] is not True
        ):
            raise RunIntentError("legacy rebind lineage is incomplete or washed")
    elif lineage["legacy_review_cycle_unverified"] is not False:
        raise RunIntentError("native v4 lineage has an invalid legacy status")
    if lineage["rebuilt_review_manifest_sha256"] != review_sha:
        raise RunIntentError("rebuilt review manifest does not match decisions")
    if lineage["binding_evidence_schema_version"] != BINDING_EVIDENCE_VERSION:
        raise RunIntentError("unknown binding evidence schema")
    evidence_sha = _sha(lineage["binding_evidence_sha256"], "binding evidence")
    for key in ("page_kinds", "terms", "drop_caps", "decision_refs"):
        if not isinstance(decisions[key], dict | list):
            raise RunIntentError(f"decisions.{key} has an invalid type")

    binding_report = _exact(
        binding_report,
        {
            "format_version",
            "sample",
            "status",
            "binding_mode",
            "binding_evidence_schema_version",
            "binding_evidence_sha256",
            "binding_evidence",
            "source_pdf_sha256",
            "review_manifest_sha256",
            "decisions_sha256",
        },
        "binding_report",
    )
    if binding_report["format_version"] != 4 or binding_report["status"] != "bound":
        raise RunIntentError("binding report is not a successful v4 binding")
    evidence = _exact(
        binding_report["binding_evidence"],
        {
            "source_binding_sha256",
            "review_manifest_sha256",
            "binding_mode",
            "legacy_review_sha256",
            "legacy_decisions_sha256",
            "decision_refs_sha256",
            "tool_schema_version",
            "code_contract_version",
        },
        "binding_report.binding_evidence",
    )
    expected_legacy_review = None if legacy_review is None else legacy_review["sha256"]
    expected_legacy_decisions = (
        None if legacy_decisions is None else legacy_decisions["sha256"]
    )
    cross_checks = (
        binding_report["sample"] == decisions["sample"],
        binding_report["binding_mode"] == lineage["binding_mode"],
        binding_report["binding_evidence_schema_version"] == BINDING_EVIDENCE_VERSION,
        binding_report["binding_evidence_sha256"] == evidence_sha,
        binding_report["source_pdf_sha256"] == source_sha,
        binding_report["review_manifest_sha256"] == review_sha,
        binding_report["decisions_sha256"] == decisions_sha256,
        evidence["source_binding_sha256"] == _digest(source_binding),
        evidence["review_manifest_sha256"] == review_sha,
        evidence["binding_mode"] == lineage["binding_mode"],
        evidence["legacy_review_sha256"] == expected_legacy_review,
        evidence["legacy_decisions_sha256"] == expected_legacy_decisions,
        evidence["decision_refs_sha256"] == _digest(decisions["decision_refs"]),
        evidence["code_contract_version"] == source_binding["code_contract_version"],
        _digest(evidence) == evidence_sha,
    )
    if not all(cross_checks):
        raise RunIntentError("decisions and binding report do not match")
    if (
        not isinstance(evidence["tool_schema_version"], str)
        or not evidence["tool_schema_version"]
    ):
        raise RunIntentError("binding tool schema version is invalid")
    return {
        "sample": decisions["sample"],
        "source_pdf_sha256": source_sha,
        "source_binding_sha256": _digest(source_binding),
        "review_manifest_sha256": review_sha,
        "binding_evidence_sha256": evidence_sha,
        "binding_evidence_schema_version": BINDING_EVIDENCE_VERSION,
        "binding_mode": lineage["binding_mode"],
    }


def validate_bound_run_intent(
    effective_report: object,
    decisions: object,
    binding_report: object,
    *,
    decisions_sha256: str,
    binding_report_sha256: str,
    require_credentials: bool = False,
) -> dict:
    effective = validate_report(effective_report, require_credentials)
    binding = validate_bound_artifacts(
        decisions,
        binding_report,
        decisions_sha256=decisions_sha256,
        effective_input_sha256=effective["input_sha256"],
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY",
        **effective,
        **binding,
        "decisions_sha256": _sha(decisions_sha256, "decisions file"),
        "binding_report_sha256": _sha(binding_report_sha256, "binding report file"),
    }
    return {**payload, "run_intent_sha256": _digest(payload)}


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    control = argparse.ArgumentParser(description=__doc__)
    control.add_argument(
        "--effective-config",
        "--effective-config-json",
        dest="effective_config",
        type=Path,
    )
    control.add_argument("--decisions", type=Path)
    control.add_argument("--binding-report", type=Path)
    control.add_argument("--require-external-credentials", action="store_true")
    control.add_argument("--report", type=Path)
    controls, remaining = control.parse_known_args(argv)
    bound_values = (
        controls.effective_config,
        controls.decisions,
        controls.binding_report,
        controls.report,
    )
    try:
        if any(value is not None for value in bound_values):
            if not all(value is not None for value in bound_values) or remaining:
                raise RunIntentError(
                    "bound mode requires exactly --effective-config, --decisions, "
                    "--binding-report and --report"
                )
            effective_report = _load_json(controls.effective_config)
            decisions = _load_json(controls.decisions)
            binding_report = _load_json(controls.binding_report)
            intent = validate_bound_run_intent(
                effective_report,
                decisions,
                binding_report,
                decisions_sha256=_file_sha256(controls.decisions),
                binding_report_sha256=_file_sha256(controls.binding_report),
                require_credentials=controls.require_external_credentials,
            )
            controls.report.parent.mkdir(parents=True, exist_ok=True)
            with controls.report.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(intent, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
        else:
            args = babeldoc_main.create_parser().parse_args(remaining)
            effective_report, errors = babeldoc_main.effective_config_report(args)
            if errors:
                raise RunIntentError("; ".join(errors))
            effective = validate_report(
                effective_report, controls.require_external_credentials
            )
            payload = {
                "schema_version": SCHEMA_VERSION,
                "status": "EFFECTIVE_CONFIG_VALID",
                **effective,
            }
            intent = {**payload, "run_intent_sha256": _digest(payload)}
    except PermissionError as exc:
        print(str(exc))
        return 3
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID_RUN_INTENT: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(intent, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
