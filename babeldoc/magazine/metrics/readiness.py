"""Machine-verifiable readiness for the three formal evaluation methods.

The historical publication matrix, substring grouping, and endpoint-window
annotations remain useful evidence, but none implements the methodology named
by formal LOPO, word-aligned LTCR, or seam MQM.  This module is the only place
that may issue a formal readiness certificate.  It validates evidence rather
than accepting author-written ``proof`` flags, and it represents missing
methodology as ``not_computed`` with a null value.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from math import comb

SCHEMA_VERSION = "evaluation-readiness.v1"

FORMAL_METRICS = {
    "lopo": "formal_lopo",
    "ltcr": "formal_ltcr",
    "seam-mqm": "formal_seam_mqm",
}
CURRENT_METRICS = {
    "descriptive_publication_matrix": "descriptive",
    "substring_consistency_proxy": "proxy",
    "exploratory_endpoint_window_annotations": "exploratory",
}

REASON_CODES = frozenset(
    {
        "LOPO_NO_FOLD_REFIT",
        "LOPO_HELDOUT_TUNING_CONTACT",
        "LOPO_PROVENANCE_MISSING",
        "LOPO_CACHE_NOT_ISOLATED",
        "LOPO_FOLD_ARTIFACT_MISSING",
        "LTCR_TERM_MANIFEST_NOT_FROZEN",
        "LTCR_WORD_ALIGNMENT_MISSING",
        "LTCR_ALIGNMENT_PROVENANCE_MISSING",
        "SEAM_POINTS_NOT_FROZEN",
        "SEAM_POINTS_NOT_BOUND_TO_ADJUDICATED_MEMBERS",
        "SEAM_INVALID_POSTHOC_WINDOWS",
        "SEAM_SOURCE_SENTENCE_INCOMPLETE",
        "SEAM_ARM_MAPPING_INCOMPLETE",
        "MQM_TAXONOMY_OR_WEIGHTS_MISMATCH",
        "MQM_PROMPT_PROTOCOL_MISMATCH",
        "MQM_HUMAN_REVIEW_INCOMPLETE",
    }
)

REQUIRED_EVIDENCE = {
    "formal_lopo": [
        "fold_partition",
        "training_row_manifest",
        "tuning_row_manifest",
        "fitting_and_selection_code_hashes",
        "search_space_and_selection_trace",
        "fold_specific_artifact",
        "isolated_cache_access_manifest",
        "heldout_input_and_prediction_hashes",
    ],
    "formal_ltcr": [
        "preidentified_term_manifest",
        "pre_output_freeze_order",
        "word_alignment_artifact",
        "alignment_provenance",
        "complete_occurrence_statuses",
    ],
    "formal_seam_mqm": [
        "pre_run_point_arm_manifest",
        "adjudicated_chain_members",
        "complete_source_sentences",
        "all_arm_mappings",
        "tex_mqm_taxonomy_and_weights",
        "gemba_mqm_three_shot_protocol",
        "completed_human_review",
        "frozen_aggregation",
    ],
}

CURRENT_NOT_READY = {
    "formal_lopo": ["LOPO_NO_FOLD_REFIT", "LOPO_HELDOUT_TUNING_CONTACT"],
    "formal_ltcr": [
        "LTCR_TERM_MANIFEST_NOT_FROZEN",
        "LTCR_WORD_ALIGNMENT_MISSING",
    ],
    "formal_seam_mqm": [
        "SEAM_POINTS_NOT_FROZEN",
        "SEAM_POINTS_NOT_BOUND_TO_ADJUDICATED_MEMBERS",
        "SEAM_INVALID_POSTHOC_WINDOWS",
        "SEAM_ARM_MAPPING_INCOMPLETE",
        "MQM_TAXONOMY_OR_WEIGHTS_MISMATCH",
        "MQM_PROMPT_PROTOCOL_MISMATCH",
    ],
}

LEGACY_LABELS = {
    "lopo_v2": (
        "descriptive_publication_matrix",
        "formal_lopo",
    ),
    "ltcr": (
        "substring_consistency_proxy",
        "formal_ltcr",
    ),
    "M10": (
        "exploratory_endpoint_window_annotations",
        "formal_seam_mqm",
    ),
}

MQM_CONTRACT = {
    "contract_version": "seam-mqm-tex.v1",
    "categories": ["accuracy", "fluency", "non_translation"],
    "severities": ["Major", "Minor", "Neutral"],
    "weights": {
        "non_translation": 25,
        "Major": 5,
        "Minor_punctuation": 0.1,
        "Minor_other": 1,
        "Neutral": 0,
    },
}


class ReadinessError(ValueError):
    """Evidence or report input has an unknown/invalid schema."""


def canonical_digest(value: object) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReadinessError("evidence is not canonical JSON") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _exact(value: object, keys: set[str], path: str) -> dict:
    if not isinstance(value, dict):
        raise ReadinessError(f"{path} must be an object")
    missing = sorted(keys - set(value))
    unknown = sorted(set(value) - keys)
    if missing or unknown:
        raise ReadinessError(f"{path} missing={missing} unknown={unknown}")
    return value


def _sha(value: object, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ReadinessError(f"{path} must be 64 lowercase hex")
    return value


def _strings(value: object, path: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ReadinessError(f"{path} must be an array of non-empty strings")
    if nonempty and not value:
        raise ReadinessError(f"{path} must not be empty")
    if len(value) != len(set(value)):
        raise ReadinessError(f"{path} must not contain duplicates")
    return value


def _digest_record(value: object, path: str) -> object:
    record = _exact(value, {"data", "sha256"}, path)
    if _sha(record["sha256"], f"{path}.sha256") != canonical_digest(record["data"]):
        raise ReadinessError(f"{path} digest mismatch")
    return record["data"]


def _report(
    metric_id: str,
    *,
    reasons: list[str] | set[str] = (),
    manifest_sha256: str | None = None,
    present: list[str] | None = None,
    provenance: list[dict] | None = None,
    value: object = None,
    coverage: dict | None = None,
) -> dict:
    ordered_reasons = sorted(set(reasons))
    computed = not ordered_reasons
    report = {
        "schema_version": SCHEMA_VERSION,
        "metric_id": metric_id,
        "metric_class": "formal",
        "readiness_status": "ready" if computed else "not_ready",
        "computation_status": "computed" if computed else "not_computed",
        "compatibility": "current",
        "evidence_manifest_sha256": manifest_sha256,
        "required_evidence": list(REQUIRED_EVIDENCE[metric_id]),
        "present_evidence": sorted(set(present or [])),
        "missing_reason_codes": ordered_reasons,
        "data_provenance": provenance or [],
        "value": value if computed else None,
        "coverage": coverage or {},
    }
    validate_readiness_report(report)
    return report


def current_formal_report(metric: str) -> dict:
    metric_id = FORMAL_METRICS.get(metric)
    if metric_id is None:
        raise ReadinessError(f"unknown formal metric {metric!r}")
    provenance = {
        "formal_lopo": [
            {
                "artifact": "docs/eval/results_e1/lopo_v2.json",
                "role": "legacy descriptive input",
            }
        ],
        "formal_ltcr": [
            {
                "artifact": "babeldoc/magazine/metrics/ltcr.py",
                "role": "substring proxy implementation",
            }
        ],
        "formal_seam_mqm": [
            {
                "artifact": "docs/eval/results_e2/splice_judgements.json",
                "role": "legacy exploratory annotations",
            },
            {
                "artifact": "docs/eval/results_e2/splice_manual_review.json",
                "role": "completed legacy human review",
            },
        ],
    }[metric_id]
    return _report(
        metric_id,
        reasons=CURRENT_NOT_READY[metric_id],
        provenance=provenance,
    )


def legacy_metric_record(label: str, value: object) -> dict:
    """Read a historical label without promoting its value to a formal one."""
    mapped = LEGACY_LABELS.get(label)
    if mapped is None:
        raise ReadinessError(f"unknown legacy metric label {label!r}")
    current_id, formal_id = mapped
    return {
        "legacy_label": label,
        "legacy_value": value,
        "current_metric_id": current_id,
        "compatibility": "legacy_noncomparable",
        "formal_metric_id": formal_id,
        "formal_value": None,
    }


def validate_readiness_report(report: object) -> dict:
    report = _exact(
        report,
        {
            "schema_version",
            "metric_id",
            "metric_class",
            "readiness_status",
            "computation_status",
            "compatibility",
            "evidence_manifest_sha256",
            "required_evidence",
            "present_evidence",
            "missing_reason_codes",
            "data_provenance",
            "value",
            "coverage",
        },
        "report",
    )
    if report["schema_version"] != SCHEMA_VERSION:
        raise ReadinessError("unknown readiness schema")
    metric_id = report["metric_id"]
    metric_class = report["metric_class"]
    formal_ids = set(FORMAL_METRICS.values())
    if metric_class == "formal":
        if metric_id not in formal_ids:
            raise ReadinessError("unknown formal metric id")
        if report["required_evidence"] != REQUIRED_EVIDENCE[metric_id]:
            raise ReadinessError("formal required-evidence list changed")
    elif metric_class in {"descriptive", "proxy", "exploratory"}:
        if CURRENT_METRICS.get(metric_id) != metric_class:
            raise ReadinessError("non-formal metric uses an unknown/formal alias")
        if report["evidence_manifest_sha256"] is not None:
            raise ReadinessError("non-formal output cannot carry a formal certificate")
    else:
        raise ReadinessError("unknown metric class")
    if report["compatibility"] not in {"current", "legacy_noncomparable"}:
        raise ReadinessError("unknown compatibility state")
    if not isinstance(report["data_provenance"], list) or not isinstance(
        report["coverage"], dict
    ):
        raise ReadinessError("provenance/coverage have invalid types")
    reasons = report["missing_reason_codes"]
    if not isinstance(reasons, list) or len(reasons) != len(set(reasons)):
        raise ReadinessError("reason codes must be a unique array")
    if set(reasons) - REASON_CODES:
        raise ReadinessError("unknown readiness reason code")
    ready = report["readiness_status"] == "ready"
    not_ready = report["readiness_status"] == "not_ready"
    computed = report["computation_status"] == "computed"
    not_computed = report["computation_status"] == "not_computed"
    if not ((ready and computed) or (not_ready and not_computed)):
        raise ReadinessError("readiness/computation state is inconsistent")
    if computed and reasons:
        raise ReadinessError("computed report carries missing reasons")
    if not_computed and (report["value"] is not None or not reasons):
        raise ReadinessError("not-computed report must carry null and reasons")
    if metric_class == "formal" and computed:
        _sha(report["evidence_manifest_sha256"], "evidence manifest")
        if report["value"] is None:
            raise ReadinessError("computed formal value cannot be null")
    return report


def _row_manifest(record: object, expected: set[str], path: str) -> None:
    rows = _digest_record(record, path)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ReadinessError(f"{path}.data must be an array of rows")
    observed = {row.get("publication") for row in rows}
    if observed != expected:
        raise ReadinessError(f"{path} publications do not match its fold set")


def evaluate_lopo(manifest: object) -> dict:
    manifest = _exact(
        manifest,
        {"schema_version", "metric_id", "publications", "folds", "data_provenance"},
        "lopo",
    )
    if (
        manifest["schema_version"] != "formal-lopo-evidence.v1"
        or manifest["metric_id"] != "formal_lopo"
    ):
        raise ReadinessError("unknown LOPO evidence schema")
    publications = _strings(manifest["publications"], "lopo.publications")
    folds = manifest["folds"]
    if not isinstance(folds, list):
        raise ReadinessError("lopo.folds must be an array")
    manifest_sha = canonical_digest(manifest)
    reasons: set[str] = set()
    present: set[str] = {"fold_partition"}
    seen_heldout: list[str] = []
    namespaces: list[str] = []
    fold_scores: list[dict] = []
    required = {
        "held_out_publication",
        "training_publications",
        "tuning_publications",
        "training_rows",
        "tuning_rows",
        "fitting_code_sha256",
        "selection_code_sha256",
        "search_space",
        "selection_trace",
        "fold_artifact",
        "cache_access",
        "heldout",
    }
    for index, raw_fold in enumerate(folds):
        if not isinstance(raw_fold, dict):
            raise ReadinessError(f"lopo.folds[{index}] must be an object")
        unknown = set(raw_fold) - required
        if unknown:
            raise ReadinessError(f"lopo.folds[{index}] unknown={sorted(unknown)}")
        missing = required - set(raw_fold)
        if missing:
            if {"fold_artifact", "selection_trace", "search_space"} & missing:
                reasons |= {"LOPO_NO_FOLD_REFIT", "LOPO_FOLD_ARTIFACT_MISSING"}
            else:
                reasons.add("LOPO_PROVENANCE_MISSING")
            continue
        heldout = raw_fold["held_out_publication"]
        if not isinstance(heldout, str) or heldout not in publications:
            raise ReadinessError(f"lopo.folds[{index}] held-out publication is invalid")
        seen_heldout.append(heldout)
        training = set(_strings(raw_fold["training_publications"], "training"))
        tuning = set(
            _strings(raw_fold["tuning_publications"], "tuning", nonempty=False)
        )
        if (
            heldout in training
            or heldout in tuning
            or training & tuning
            or training | tuning | {heldout} != set(publications)
        ):
            reasons.add("LOPO_HELDOUT_TUNING_CONTACT")
        try:
            _row_manifest(raw_fold["training_rows"], training, "training_rows")
            _row_manifest(raw_fold["tuning_rows"], tuning, "tuning_rows")
            present |= {"training_row_manifest", "tuning_row_manifest"}
            _sha(raw_fold["fitting_code_sha256"], "fitting code")
            _sha(raw_fold["selection_code_sha256"], "selection code")
            present.add("fitting_and_selection_code_hashes")
            _digest_record(raw_fold["search_space"], "search_space")
            trace = _digest_record(raw_fold["selection_trace"], "selection_trace")
            artifact = _digest_record(raw_fold["fold_artifact"], "fold_artifact")
            if not isinstance(trace, dict) or not isinstance(artifact, dict):
                raise ReadinessError("selection trace/artifact data must be objects")
            artifact_sha = canonical_digest(artifact)
            if trace.get("selected_artifact_sha256") != artifact_sha:
                reasons |= {"LOPO_NO_FOLD_REFIT", "LOPO_FOLD_ARTIFACT_MISSING"}
            else:
                present |= {
                    "search_space_and_selection_trace",
                    "fold_specific_artifact",
                }
            cache = _digest_record(raw_fold["cache_access"], "cache_access")
            cache = _exact(
                cache,
                {"namespace", "accessed_publications", "accessed_keys"},
                "cache_access.data",
            )
            namespace = cache["namespace"]
            if not isinstance(namespace, str) or not namespace:
                raise ReadinessError("cache namespace is invalid")
            namespaces.append(namespace)
            accessed = set(
                _strings(
                    cache["accessed_publications"],
                    "cache accessed publications",
                    nonempty=False,
                )
            )
            _strings(cache["accessed_keys"], "cache accessed keys", nonempty=False)
            if heldout in accessed or not accessed <= training | tuning:
                reasons.add("LOPO_HELDOUT_TUNING_CONTACT")
            heldout_record = _exact(
                raw_fold["heldout"],
                {
                    "input_sha256",
                    "prediction_sha256",
                    "score_numerator",
                    "score_denominator",
                },
                "heldout",
            )
            _sha(heldout_record["input_sha256"], "heldout input")
            _sha(heldout_record["prediction_sha256"], "heldout prediction")
            numerator = heldout_record["score_numerator"]
            denominator = heldout_record["score_denominator"]
            if (
                isinstance(numerator, bool)
                or isinstance(denominator, bool)
                or not isinstance(numerator, int)
                or not isinstance(denominator, int)
                or not 0 <= numerator <= denominator
                or denominator < 1
            ):
                raise ReadinessError("heldout score counts are invalid")
            fold_scores.append(
                {
                    "held_out_publication": heldout,
                    "score_numerator": numerator,
                    "score_denominator": denominator,
                    "value": numerator / denominator,
                }
            )
            present |= {
                "isolated_cache_access_manifest",
                "heldout_input_and_prediction_hashes",
            }
        except ReadinessError:
            reasons.add("LOPO_PROVENANCE_MISSING")
    if Counter(seen_heldout) != Counter(publications):
        reasons.add("LOPO_HELDOUT_TUNING_CONTACT")
    if len(namespaces) != len(set(namespaces)) or len(namespaces) != len(folds):
        reasons.add("LOPO_CACHE_NOT_ISOLATED")
    if not folds:
        reasons |= {"LOPO_NO_FOLD_REFIT", "LOPO_FOLD_ARTIFACT_MISSING"}
    numerator = sum(item["score_numerator"] for item in fold_scores)
    denominator = sum(item["score_denominator"] for item in fold_scores)
    value = {
        "ratio": numerator / denominator if denominator else None,
        "score_numerator": numerator,
        "score_denominator": denominator,
        "folds": fold_scores,
    }
    return _report(
        "formal_lopo",
        reasons=reasons,
        manifest_sha256=manifest_sha,
        present=list(present),
        provenance=manifest["data_provenance"],
        value=value,
        coverage={"publications": len(publications), "folds": len(folds)},
    )


def evaluate_ltcr(manifest: object) -> dict:
    manifest = _exact(
        manifest,
        {
            "schema_version",
            "metric_id",
            "term_manifest",
            "time_ordering",
            "alignment_artifact",
            "system_output_sha256",
            "data_provenance",
        },
        "ltcr",
    )
    if (
        manifest["schema_version"] != "formal-ltcr-evidence.v1"
        or manifest["metric_id"] != "formal_ltcr"
    ):
        raise ReadinessError("unknown LTCR evidence schema")
    manifest_sha = canonical_digest(manifest)
    reasons: set[str] = set()
    present: set[str] = set()
    term_data = _digest_record(manifest["term_manifest"], "term_manifest")
    if not isinstance(term_data, list) or not term_data:
        raise ReadinessError("term manifest must contain terms")
    term_sha = canonical_digest(term_data)
    output_sha = _sha(manifest["system_output_sha256"], "system output")
    ordering = _digest_record(manifest["time_ordering"], "time_ordering")
    if not isinstance(ordering, dict) or ordering != {
        "sequence": ["term_manifest", "system_output"],
        "term_manifest_sha256": term_sha,
        "system_output_sha256": output_sha,
    }:
        reasons.add("LTCR_TERM_MANIFEST_NOT_FROZEN")
    else:
        present |= {"preidentified_term_manifest", "pre_output_freeze_order"}
    expected: dict[tuple[str, str], dict] = {}
    for term in term_data:
        term = _exact(
            term,
            {
                "term_id",
                "normalized_term",
                "scope",
                "expected_occurrences",
                "adjudication_provenance",
            },
            "term",
        )
        term_id = term["term_id"]
        if not isinstance(term_id, str) or not term_id:
            raise ReadinessError("term id is invalid")
        occurrences = term["expected_occurrences"]
        if not isinstance(occurrences, list) or not occurrences:
            raise ReadinessError("term expected occurrences are empty")
        for occurrence in occurrences:
            occurrence = _exact(occurrence, {"ref", "source_span"}, "occurrence")
            ref = occurrence["ref"]
            span = occurrence["source_span"]
            if (
                not isinstance(ref, str)
                or not ref
                or not isinstance(span, list)
                or len(span) != 2
                or not all(isinstance(item, int) and item >= 0 for item in span)
                or span[0] >= span[1]
            ):
                raise ReadinessError("source occurrence ref/span is invalid")
            key = (term_id, ref)
            if key in expected:
                raise ReadinessError("duplicate expected occurrence")
            expected[key] = occurrence
    alignment_data = _digest_record(
        manifest["alignment_artifact"], "alignment_artifact"
    )
    alignment_data = _exact(
        alignment_data,
        {"term_manifest_sha256", "occurrences"},
        "alignment_artifact.data",
    )
    if alignment_data["term_manifest_sha256"] != term_sha:
        reasons.add("LTCR_WORD_ALIGNMENT_MISSING")
    rows = alignment_data["occurrences"]
    if not isinstance(rows, list):
        raise ReadinessError("alignment occurrences must be an array")
    observed: dict[tuple[str, str], dict] = {}
    statuses = Counter()
    by_term: dict[str, list[str]] = {}
    ambiguous_refs: list[str] = []
    unaligned_refs: list[str] = []
    for row in rows:
        row = _exact(
            row,
            {
                "term_id",
                "occurrence_ref",
                "source_span",
                "target_ref",
                "target_span",
                "rendering",
                "method",
                "model",
                "config_sha256",
                "version",
                "confidence",
                "status",
            },
            "alignment occurrence",
        )
        key = (row["term_id"], row["occurrence_ref"])
        if key in observed or key not in expected:
            raise ReadinessError("alignment occurrence is duplicate or unexpected")
        observed[key] = row
        if row["source_span"] != expected[key]["source_span"]:
            raise ReadinessError("alignment source span differs from frozen term")
        for name in ("method", "model", "version"):
            if not isinstance(row[name], str) or not row[name]:
                reasons.add("LTCR_ALIGNMENT_PROVENANCE_MISSING")
        try:
            _sha(row["config_sha256"], "alignment config")
        except ReadinessError:
            reasons.add("LTCR_ALIGNMENT_PROVENANCE_MISSING")
        status = row["status"]
        if status not in {"aligned", "ambiguous", "unaligned"}:
            raise ReadinessError("unknown alignment status")
        statuses[status] += 1
        if status == "aligned":
            if (
                not isinstance(row["target_ref"], str)
                or not row["target_ref"]
                or not isinstance(row["target_span"], list)
                or len(row["target_span"]) != 2
                or not isinstance(row["rendering"], str)
                or not row["rendering"]
                or isinstance(row["confidence"], bool)
                or not isinstance(row["confidence"], int | float)
            ):
                raise ReadinessError("aligned occurrence is incomplete")
            by_term.setdefault(row["term_id"], []).append(row["rendering"])
        elif status == "ambiguous":
            ambiguous_refs.append(row["occurrence_ref"])
        else:
            unaligned_refs.append(row["occurrence_ref"])
    if set(observed) != set(expected):
        reasons.add("LTCR_WORD_ALIGNMENT_MISSING")
    else:
        present |= {"word_alignment_artifact", "complete_occurrence_statuses"}
    if "LTCR_ALIGNMENT_PROVENANCE_MISSING" not in reasons:
        present.add("alignment_provenance")
    agreeing = 0
    total = 0
    uncomputable: list[str] = []
    term_values: list[dict] = []
    for term in term_data:
        term_id = term["term_id"]
        renderings = by_term.get(term_id, [])
        if len(renderings) < 2:
            uncomputable.append(term_id)
            term_values.append(
                {"term_id": term_id, "aligned": len(renderings), "value": None}
            )
            continue
        counts = Counter(renderings)
        term_agreeing = sum(comb(count, 2) for count in counts.values())
        term_total = comb(len(renderings), 2)
        agreeing += term_agreeing
        total += term_total
        term_values.append(
            {
                "term_id": term_id,
                "aligned": len(renderings),
                "pairs_agreeing": term_agreeing,
                "pairs_total": term_total,
                "value": term_agreeing / term_total,
            }
        )
    value = {
        "ratio": agreeing / total if total else None,
        "pairs_agreeing": agreeing,
        "pairs_total": total,
        "terms": term_values,
    }
    coverage = {
        "expected": len(expected),
        "aligned": statuses["aligned"],
        "ambiguous": statuses["ambiguous"],
        "unaligned": statuses["unaligned"],
        "ambiguous_refs": sorted(ambiguous_refs),
        "unaligned_refs": sorted(unaligned_refs),
        "uncomputable_terms": sorted(uncomputable),
    }
    return _report(
        "formal_ltcr",
        reasons=reasons,
        manifest_sha256=manifest_sha,
        present=list(present),
        provenance=manifest["data_provenance"],
        value=value,
        coverage=coverage,
    )


def _mqm_weight(error: dict) -> float:
    category = error["category"]
    severity = error["severity"]
    subtype = error["subtype"]
    if category == "non_translation":
        return 25.0
    if severity == "Major":
        return 5.0
    if severity == "Neutral":
        return 0.0
    if severity == "Minor" and category == "fluency" and subtype == "punctuation":
        return 0.1
    return 1.0


def evaluate_seam_mqm(manifest: object) -> dict:
    manifest = _exact(
        manifest,
        {
            "schema_version",
            "metric_id",
            "point_manifest",
            "arm_artifacts",
            "mqm_contract",
            "prompt_protocol",
            "annotations",
            "human_review",
            "aggregation",
            "data_provenance",
        },
        "seam",
    )
    if (
        manifest["schema_version"] != "formal-seam-mqm-evidence.v1"
        or manifest["metric_id"] != "formal_seam_mqm"
    ):
        raise ReadinessError("unknown seam MQM evidence schema")
    manifest_sha = canonical_digest(manifest)
    reasons: set[str] = set()
    present: set[str] = set()
    points = _digest_record(manifest["point_manifest"], "point_manifest")
    if not isinstance(points, list) or not points:
        raise ReadinessError("point manifest must contain points")
    expected: set[tuple[str, str]] = set()
    for point in points:
        point = _exact(
            point,
            {
                "point_id",
                "publication",
                "document",
                "boundary_type",
                "physical_source_boundary",
                "chain_member_refs",
                "source_sentence_refs",
                "source_sentence_sha256",
                "expected_arms",
                "adjudicator",
                "status",
                "phase",
            },
            "seam point",
        )
        if point["phase"] != "pre_output" or point["status"] != "adjudicated":
            reasons.add("SEAM_POINTS_NOT_FROZEN")
        members = _strings(point["chain_member_refs"], "chain members")
        if len(members) < 2:
            reasons.add("SEAM_POINTS_NOT_BOUND_TO_ADJUDICATED_MEMBERS")
        sentence_refs = _strings(point["source_sentence_refs"], "sentence refs")
        if not sentence_refs:
            reasons.add("SEAM_SOURCE_SENTENCE_INCOMPLETE")
        try:
            _sha(point["source_sentence_sha256"], "source sentence")
        except ReadinessError:
            reasons.add("SEAM_SOURCE_SENTENCE_INCOMPLETE")
        arms = _strings(point["expected_arms"], "expected arms")
        expected |= {(point["point_id"], arm) for arm in arms}
    if "SEAM_POINTS_NOT_FROZEN" not in reasons:
        present.add("pre_run_point_arm_manifest")
    if "SEAM_POINTS_NOT_BOUND_TO_ADJUDICATED_MEMBERS" not in reasons:
        present.add("adjudicated_chain_members")
    if "SEAM_SOURCE_SENTENCE_INCOMPLETE" not in reasons:
        present.add("complete_source_sentences")

    mappings = manifest["arm_artifacts"]
    if not isinstance(mappings, list):
        raise ReadinessError("arm artifacts must be an array")
    observed: set[tuple[str, str]] = set()
    for mapping in mappings:
        mapping = _exact(
            mapping,
            {
                "point_id",
                "arm",
                "artifact_sha256",
                "source_member_refs",
                "target_segment_refs",
                "mapping_status",
                "posthoc_invalid",
            },
            "arm artifact",
        )
        key = (mapping["point_id"], mapping["arm"])
        if key in observed or key not in expected:
            raise ReadinessError("arm mapping is duplicate or unexpected")
        observed.add(key)
        _sha(mapping["artifact_sha256"], "arm artifact")
        if mapping["posthoc_invalid"] is not False:
            reasons.add("SEAM_INVALID_POSTHOC_WINDOWS")
        if (
            mapping["mapping_status"] != "mapped"
            or not _strings(mapping["source_member_refs"], "mapped source refs")
            or not _strings(mapping["target_segment_refs"], "mapped target refs")
        ):
            reasons.add("SEAM_ARM_MAPPING_INCOMPLETE")
    if observed != expected:
        reasons.add("SEAM_ARM_MAPPING_INCOMPLETE")
    elif "SEAM_ARM_MAPPING_INCOMPLETE" not in reasons:
        present.add("all_arm_mappings")

    if manifest["mqm_contract"] != MQM_CONTRACT:
        reasons.add("MQM_TAXONOMY_OR_WEIGHTS_MISMATCH")
    else:
        present.add("tex_mqm_taxonomy_and_weights")
    prompt = _exact(
        manifest["prompt_protocol"],
        {
            "protocol_version",
            "shots",
            "prompt_sha256",
            "model_version",
            "parameters_sha256",
            "cache_namespace",
            "reply_sha256",
        },
        "prompt protocol",
    )
    prompt_valid = (
        prompt["protocol_version"] == "GEMBA-MQM-three-shot.v1"
        and prompt["shots"] == 3
        and isinstance(prompt["model_version"], str)
        and bool(prompt["model_version"])
        and isinstance(prompt["cache_namespace"], str)
        and bool(prompt["cache_namespace"])
    )
    try:
        for key in ("prompt_sha256", "parameters_sha256", "reply_sha256"):
            _sha(prompt[key], key)
    except ReadinessError:
        prompt_valid = False
    if not prompt_valid:
        reasons.add("MQM_PROMPT_PROTOCOL_MISMATCH")
    else:
        present.add("gemba_mqm_three_shot_protocol")

    annotations = manifest["annotations"]
    if not isinstance(annotations, list):
        raise ReadinessError("annotations must be an array")
    scores: dict[tuple[str, str], list[float]] = {}
    for annotation in annotations:
        annotation = _exact(
            annotation,
            {"point_id", "arm", "annotator", "errors"},
            "annotation",
        )
        key = (annotation["point_id"], annotation["arm"])
        if key not in expected:
            raise ReadinessError("annotation names an unexpected point/arm")
        if not isinstance(annotation["annotator"], str) or not annotation["annotator"]:
            raise ReadinessError("annotation has no annotator")
        errors = annotation["errors"]
        if not isinstance(errors, list):
            raise ReadinessError("annotation errors must be an array")
        score = 0.0
        for error in errors:
            error = _exact(error, {"category", "subtype", "severity"}, "error")
            if (
                error["category"] not in MQM_CONTRACT["categories"]
                or error["severity"] not in MQM_CONTRACT["severities"]
                or not isinstance(error["subtype"], str)
            ):
                reasons.add("MQM_TAXONOMY_OR_WEIGHTS_MISMATCH")
                continue
            score += _mqm_weight(error)
        scores.setdefault(key, []).append(score)

    review = _exact(
        manifest["human_review"],
        {"records", "context_bound", "paired_comparison", "completed"},
        "human review",
    )
    review_records = review["records"]
    reviewed = (
        {
            (row.get("point_id"), row.get("arm"))
            for row in review_records
            if isinstance(row, dict) and row.get("complete") is True
        }
        if isinstance(review_records, list)
        else set()
    )
    if (
        review["context_bound"] is not True
        or review["paired_comparison"] is not True
        or review["completed"] is not True
        or reviewed != expected
    ):
        reasons.add("MQM_HUMAN_REVIEW_INCOMPLETE")
    else:
        present.add("completed_human_review")
    aggregation = _exact(
        manifest["aggregation"],
        {"denominator", "multi_annotator", "phase"},
        "aggregation",
    )
    if aggregation != {
        "denominator": "all_expected_point_arms",
        "multi_annotator": "mean",
        "phase": "pre_output",
    }:
        reasons.add("SEAM_POINTS_NOT_FROZEN")
    else:
        present.add("frozen_aggregation")
    if set(scores) != expected or any(not values for values in scores.values()):
        reasons.add("SEAM_ARM_MAPPING_INCOMPLETE")
    arm_scores = {
        f"{point_id}:{arm}": sum(values) / len(values)
        for (point_id, arm), values in sorted(scores.items())
        if values
    }
    value = {
        "mqm_error_score": sum(arm_scores.values()) / len(arm_scores)
        if arm_scores
        else None,
        "arm_scores": arm_scores,
    }
    return _report(
        "formal_seam_mqm",
        reasons=reasons,
        manifest_sha256=manifest_sha,
        present=list(present),
        provenance=manifest["data_provenance"],
        value=value,
        coverage={
            "points": len(points),
            "expected_point_arms": len(expected),
            "mapped_point_arms": len(observed & expected),
            "annotated_point_arms": len(set(scores) & expected),
            "human_reviewed_point_arms": len(reviewed & expected),
        },
    )


def evaluate_formal(metric: str, manifest: object) -> dict:
    if metric == "lopo":
        return evaluate_lopo(manifest)
    if metric == "ltcr":
        return evaluate_ltcr(manifest)
    if metric == "seam-mqm":
        return evaluate_seam_mqm(manifest)
    raise ReadinessError(f"unknown formal metric {metric!r}")


def aggregate_formal(reports: list[object]) -> list[object]:
    """Return computed formal values; not-computed entries never become zero."""
    values = []
    for report in reports:
        validated = validate_readiness_report(report)
        if (
            validated["metric_class"] == "formal"
            and validated["computation_status"] == "computed"
        ):
            values.append(validated["value"])
    return values


def render_value(report: object) -> object:
    """Render absent methodology as text, never as zero/NaN/empty output."""
    validated = validate_readiness_report(report)
    if validated["computation_status"] == "not_computed":
        return "not_computed"
    return validated["value"]
