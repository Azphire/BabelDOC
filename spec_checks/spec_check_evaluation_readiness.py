"""Offline synthetic checks for formal evaluation readiness certificates."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.metrics import readiness  # noqa: E402

PYTHON = sys.executable
TOOL = ROOT / "tools" / "evaluation_readiness.py"
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail else ''}")


def digest_record(data: object) -> dict:
    return {"data": data, "sha256": readiness.canonical_digest(data)}


def lopo_manifest() -> dict:
    publications = ["alpha", "beta", "gamma"]
    folds = []
    for index, heldout in enumerate(publications):
        others = [item for item in publications if item != heldout]
        training = [others[0]]
        tuning = [others[1]]
        artifact = {"policy": f"policy-{heldout}", "threshold": index + 1}
        trace = {
            "events": ["fit", "select", "freeze"],
            "selected_artifact_sha256": readiness.canonical_digest(artifact),
        }
        folds.append(
            {
                "held_out_publication": heldout,
                "training_publications": training,
                "tuning_publications": tuning,
                "training_rows": digest_record(
                    [{"publication": training[0], "rows": 3}]
                ),
                "tuning_rows": digest_record([{"publication": tuning[0], "rows": 2}]),
                "fitting_code_sha256": f"{index + 1:064x}",
                "selection_code_sha256": f"{index + 11:064x}",
                "search_space": digest_record({"thresholds": [1, 2, 3]}),
                "selection_trace": digest_record(trace),
                "fold_artifact": digest_record(artifact),
                "cache_access": digest_record(
                    {
                        "namespace": f"fold-{heldout}",
                        "accessed_publications": others,
                        "accessed_keys": [f"{heldout}-train", f"{heldout}-tune"],
                    }
                ),
                "heldout": {
                    "input_sha256": f"{index + 21:064x}",
                    "prediction_sha256": f"{index + 31:064x}",
                    "score_numerator": index + 1,
                    "score_denominator": 3,
                },
            }
        )
    return {
        "schema_version": "formal-lopo-evidence.v1",
        "metric_id": "formal_lopo",
        "publications": publications,
        "folds": folds,
        "data_provenance": [{"source": "synthetic-fold-fixture"}],
    }


def ltcr_manifest() -> dict:
    terms = [
        {
            "term_id": "t1",
            "normalized_term": "alpha term",
            "scope": "article:a",
            "expected_occurrences": [
                {"ref": "o1", "source_span": [0, 5]},
                {"ref": "o2", "source_span": [10, 15]},
                {"ref": "o3", "source_span": [20, 25]},
            ],
            "adjudication_provenance": "pre-output-adjudication-a",
        },
        {
            "term_id": "t2",
            "normalized_term": "beta term",
            "scope": "article:a",
            "expected_occurrences": [
                {"ref": "o4", "source_span": [30, 34]},
                {"ref": "o5", "source_span": [40, 44]},
            ],
            "adjudication_provenance": "pre-output-adjudication-b",
        },
    ]
    term_sha = readiness.canonical_digest(terms)
    output_sha = "a" * 64
    ordering = {
        "sequence": ["term_manifest", "system_output"],
        "term_manifest_sha256": term_sha,
        "system_output_sha256": output_sha,
    }
    renderings = {
        "o1": ("t1", [0, 5], "X", "aligned"),
        "o2": ("t1", [10, 15], "X", "aligned"),
        "o3": ("t1", [20, 25], "Y", "aligned"),
        "o4": ("t2", [30, 34], "Z", "aligned"),
        "o5": ("t2", [40, 44], None, "unaligned"),
    }
    occurrences = []
    for ref, (term_id, source_span, rendering, status) in renderings.items():
        aligned = status == "aligned"
        occurrences.append(
            {
                "term_id": term_id,
                "occurrence_ref": ref,
                "source_span": source_span,
                "target_ref": f"target-{ref}" if aligned else None,
                "target_span": [0, 1] if aligned else None,
                "rendering": rendering,
                "method": "offline-aligner",
                "model": "aligner-v1",
                "config_sha256": "b" * 64,
                "version": "alignment.v1",
                "confidence": 0.99 if aligned else 0.2,
                "status": status,
            }
        )
    return {
        "schema_version": "formal-ltcr-evidence.v1",
        "metric_id": "formal_ltcr",
        "term_manifest": digest_record(terms),
        "time_ordering": digest_record(ordering),
        "alignment_artifact": digest_record(
            {"term_manifest_sha256": term_sha, "occurrences": occurrences}
        ),
        "system_output_sha256": output_sha,
        "data_provenance": [{"source": "synthetic-alignment-fixture"}],
    }


def seam_manifest() -> dict:
    points = [
        {
            "point_id": "point-1",
            "publication": "alpha",
            "document": "alpha.pdf",
            "boundary_type": "page_break",
            "physical_source_boundary": [1, 2],
            "chain_member_refs": ["member-1", "member-2"],
            "source_sentence_refs": ["sentence-1"],
            "source_sentence_sha256": "c" * 64,
            "expected_arms": ["system-a", "system-b"],
            "adjudicator": "fixture-owner",
            "status": "adjudicated",
            "phase": "pre_output",
        }
    ]
    mappings = [
        {
            "point_id": "point-1",
            "arm": arm,
            "artifact_sha256": character * 64,
            "source_member_refs": ["member-1", "member-2"],
            "target_segment_refs": [f"target-{arm}"],
            "mapping_status": "mapped",
            "posthoc_invalid": False,
        }
        for arm, character in (("system-a", "d"), ("system-b", "e"))
    ]
    annotations = [
        {
            "point_id": "point-1",
            "arm": "system-a",
            "annotator": "one",
            "errors": [
                {"category": "fluency", "subtype": "punctuation", "severity": "Minor"}
            ],
        },
        {
            "point_id": "point-1",
            "arm": "system-a",
            "annotator": "two",
            "errors": [
                {
                    "category": "accuracy",
                    "subtype": "mistranslation",
                    "severity": "Major",
                }
            ],
        },
        {
            "point_id": "point-1",
            "arm": "system-b",
            "annotator": "one",
            "errors": [],
        },
    ]
    return {
        "schema_version": "formal-seam-mqm-evidence.v1",
        "metric_id": "formal_seam_mqm",
        "point_manifest": digest_record(points),
        "arm_artifacts": mappings,
        "mqm_contract": copy.deepcopy(readiness.MQM_CONTRACT),
        "prompt_protocol": {
            "protocol_version": "GEMBA-MQM-three-shot.v1",
            "shots": 3,
            "prompt_sha256": "f" * 64,
            "model_version": "offline-judge-v1",
            "parameters_sha256": "1" * 64,
            "cache_namespace": "seam-mqm-fixture-v1",
            "reply_sha256": "2" * 64,
        },
        "annotations": annotations,
        "human_review": {
            "records": [
                {"point_id": "point-1", "arm": "system-a", "complete": True},
                {"point_id": "point-1", "arm": "system-b", "complete": True},
            ],
            "context_bound": True,
            "paired_comparison": True,
            "completed": True,
        },
        "aggregation": {
            "denominator": "all_expected_point_arms",
            "multi_annotator": "mean",
            "phase": "pre_output",
        },
        "data_provenance": [{"source": "synthetic-seam-fixture"}],
    }


def check_lopo() -> None:
    valid = lopo_manifest()
    ready = readiness.evaluate_lopo(valid)
    conditions = [
        ready["readiness_status"] == "ready",
        ready["computation_status"] == "computed",
        ready["coverage"] == {"publications": 3, "folds": 3},
    ]
    no_refit = copy.deepcopy(valid)
    del no_refit["folds"][0]["fold_artifact"]
    no_refit_report = readiness.evaluate_lopo(no_refit)
    heldout = copy.deepcopy(valid)
    heldout["folds"][0]["tuning_publications"] = ["alpha"]
    heldout_report = readiness.evaluate_lopo(heldout)
    shared = copy.deepcopy(valid)
    cache_data = shared["folds"][1]["cache_access"]["data"]
    cache_data["namespace"] = shared["folds"][0]["cache_access"]["data"]["namespace"]
    shared["folds"][1]["cache_access"] = digest_record(cache_data)
    shared_report = readiness.evaluate_lopo(shared)
    missing_hash = copy.deepcopy(valid)
    missing_hash["folds"][0]["fitting_code_sha256"] = "missing"
    missing_hash_report = readiness.evaluate_lopo(missing_hash)
    conditions += [
        "LOPO_NO_FOLD_REFIT" in no_refit_report["missing_reason_codes"],
        "LOPO_HELDOUT_TUNING_CONTACT" in heldout_report["missing_reason_codes"],
        "LOPO_CACHE_NOT_ISOLATED" in shared_report["missing_reason_codes"],
        "LOPO_PROVENANCE_MISSING" in missing_hash_report["missing_reason_codes"],
        all(
            report["computation_status"] == "not_computed" and report["value"] is None
            for report in (
                no_refit_report,
                heldout_report,
                shared_report,
                missing_hash_report,
            )
        ),
    ]
    proof = copy.deepcopy(valid)
    proof["proof"] = True
    proof_closed = False
    try:
        readiness.evaluate_lopo(proof)
    except readiness.ReadinessError:
        proof_closed = True
    conditions.append(proof_closed)
    record(
        "01 LOPO recomputes fold/cache/provenance evidence and fails closed",
        all(conditions),
    )


def check_ltcr() -> None:
    valid = ltcr_manifest()
    report = readiness.evaluate_ltcr(valid)
    terms = report["value"]["terms"]
    t2 = next(term for term in terms if term["term_id"] == "t2")
    missing = copy.deepcopy(valid)
    alignment = missing["alignment_artifact"]["data"]
    alignment["occurrences"] = alignment["occurrences"][:-1]
    missing["alignment_artifact"] = digest_record(alignment)
    missing_report = readiness.evaluate_ltcr(missing)
    proxy = copy.deepcopy(valid)
    proxy["metric_id"] = "substring_consistency_proxy"
    proxy_closed = False
    try:
        readiness.evaluate_ltcr(proxy)
    except readiness.ReadinessError:
        proxy_closed = True
    record(
        "02 LTCR uses aligned pairs and reports ambiguous/unaligned/uncomputable separately",
        report["computation_status"] == "computed"
        and report["value"]["pairs_agreeing"] == 1
        and report["value"]["pairs_total"] == 3
        and t2["value"] is None
        and report["coverage"]["unaligned"] == 1
        and report["coverage"]["unaligned_refs"] == ["o5"]
        and missing_report["value"] is None
        and "LTCR_WORD_ALIGNMENT_MISSING" in missing_report["missing_reason_codes"]
        and proxy_closed,
    )


def check_seam() -> None:
    valid = seam_manifest()
    ready = readiness.evaluate_seam_mqm(valid)
    variants: list[tuple[dict, str]] = []
    taxonomy = copy.deepcopy(valid)
    taxonomy["mqm_contract"]["categories"] = ["accuracy", "style"]
    variants.append((taxonomy, "MQM_TAXONOMY_OR_WEIGHTS_MISMATCH"))
    severity = copy.deepcopy(valid)
    severity["annotations"][0]["errors"][0]["severity"] = "critical"
    variants.append((severity, "MQM_TAXONOMY_OR_WEIGHTS_MISMATCH"))
    weights = copy.deepcopy(valid)
    weights["mqm_contract"]["weights"]["Major"] = 4
    variants.append((weights, "MQM_TAXONOMY_OR_WEIGHTS_MISMATCH"))
    prompt = copy.deepcopy(valid)
    prompt["prompt_protocol"]["shots"] = 2
    variants.append((prompt, "MQM_PROMPT_PROTOCOL_MISMATCH"))
    posthoc = copy.deepcopy(valid)
    posthoc["arm_artifacts"][0]["posthoc_invalid"] = True
    variants.append((posthoc, "SEAM_INVALID_POSTHOC_WINDOWS"))
    missing_arm = copy.deepcopy(valid)
    missing_arm["arm_artifacts"] = missing_arm["arm_artifacts"][:-1]
    variants.append((missing_arm, "SEAM_ARM_MAPPING_INCOMPLETE"))
    reports = [readiness.evaluate_seam_mqm(item) for item, _reason in variants]
    record(
        "03 seam requires pre-run mappings, exact MQM weights/taxonomy, three-shot, and review",
        ready["computation_status"] == "computed"
        and abs(ready["value"]["mqm_error_score"] - 1.275) < 1e-9
        and all(
            report["computation_status"] == "not_computed"
            and report["value"] is None
            and reason in report["missing_reason_codes"]
            for report, (_item, reason) in zip(reports, variants, strict=True)
        ),
    )


def check_cli_exit_contract() -> None:
    faults = []
    with tempfile.TemporaryDirectory(prefix="babeldoc-c21-readiness-") as temp:
        root = Path(temp)
        for metric in ("lopo", "ltcr", "seam-mqm"):
            output = root / f"{metric}.json"
            proc = subprocess.run(  # noqa: S603
                [
                    PYTHON,
                    str(TOOL),
                    "check",
                    "--metric",
                    metric,
                    "--mode",
                    "formal",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            payload = (
                json.loads(output.read_text(encoding="utf-8"))
                if output.is_file()
                else {}
            )
            if not (
                proc.returncode == 3
                and payload.get("computation_status") == "not_computed"
                and payload.get("value") is None
                and payload.get("missing_reason_codes")
            ):
                faults.append(f"{metric}: exit={proc.returncode} payload={payload}")
        invalid = root / "invalid.json"
        invalid.write_text("{}", encoding="utf-8")
        implementation = subprocess.run(  # noqa: S603
            [
                PYTHON,
                str(TOOL),
                "check",
                "--metric",
                "lopo",
                "--mode",
                "formal",
                "--evidence-manifest",
                str(invalid),
                "--output",
                str(root / "invalid-output.json"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if implementation.returncode != 1:
            faults.append(f"invalid schema exit={implementation.returncode}")
        usage = subprocess.run(  # noqa: S603
            [PYTHON, str(TOOL), "check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if usage.returncode != 2:
            faults.append(f"usage exit={usage.returncode}")
        timeout_closed = False
        try:
            subprocess.run(  # noqa: S603
                [PYTHON, "-c", "import time; time.sleep(2)"],
                timeout=0.05,
                check=False,
            )
        except subprocess.TimeoutExpired:
            timeout_closed = True
        if not timeout_closed:
            faults.append("timeout was not distinct from methodology exit 3")
    record(
        "04 CLI distinguishes computed=0, schema=1, usage=2, not-ready=3, timeout",
        not faults,
        "; ".join(faults),
    )


def main() -> int:
    check_lopo()
    check_ltcr()
    check_seam()
    check_cli_exit_contract()
    failed = [name for name, ok, _detail in RESULTS if not ok]
    print(
        f"spec_check_evaluation_readiness: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
