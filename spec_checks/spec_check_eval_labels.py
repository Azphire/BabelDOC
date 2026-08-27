"""Offline checks that proxy metrics cannot masquerade as formal metrics."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.metrics import ltcr  # noqa: E402
from babeldoc.magazine.metrics import readiness  # noqa: E402

from tools import lopo  # noqa: E402

STATUS = ROOT / "docs" / "eval" / "methodology_status.v2.json"
DOCS = (
    ROOT / "docs" / "eval" / "metric_contract.md",
    ROOT / "docs" / "eval" / "gap_register.md",
    ROOT / "docs" / "eval" / "splice_protocol.md",
)
SPLICE_TOOL = ROOT / "tools" / "splice_judge.py"
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail else ''}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_current_ids() -> None:
    publication = lopo.build_report()
    substring = ltcr.measure([], terminals=())
    tree = ast.parse(SPLICE_TOOL.read_text(encoding="utf-8"))
    report_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "report_of"
    )
    returned = next(
        node.value
        for node in ast.walk(report_function)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    )
    endpoint = {
        ast.literal_eval(key): ast.literal_eval(value)
        for key, value in zip(returned.keys, returned.values, strict=True)
        if key is not None
        and isinstance(key, ast.Constant)
        and isinstance(value, ast.Constant)
    }
    outputs = (publication, substring, endpoint)
    expected = {
        "descriptive_publication_matrix": ("descriptive", "generalisation_claim"),
        "substring_consistency_proxy": ("proxy", "formal_ltcr_claim"),
        "exploratory_endpoint_window_annotations": (
            "exploratory",
            "formal_seam_mqm_claim",
        ),
    }
    faults = []
    for output in outputs:
        metric_id = output.get("metric_id")
        if metric_id not in expected:
            faults.append(f"unknown current id {metric_id!r}")
            continue
        metric_class, claim = expected[metric_id]
        if output.get("metric_class") != metric_class or output.get(claim) is not False:
            faults.append(f"{metric_id}: class/claim mismatch")
    encoded = json.dumps(outputs, sort_keys=True)
    for forbidden in ('"metric": "ltcr"', '"metric": "M10"'):
        if forbidden in encoded:
            faults.append(f"current output exposes formal alias {forbidden}")
    record(
        "01 current public IDs are descriptive/proxy/exploratory only",
        not faults,
        "; ".join(faults),
    )


def check_formal_certificate_and_aggregation() -> None:
    not_ready = [
        readiness.current_formal_report(metric)
        for metric in ("lopo", "ltcr", "seam-mqm")
    ]
    forged = copy.deepcopy(not_ready[0])
    forged.update(
        {
            "readiness_status": "ready",
            "computation_status": "computed",
            "missing_reason_codes": [],
            "value": 0.9,
        }
    )
    forged_closed = False
    try:
        readiness.validate_readiness_report(forged)
    except readiness.ReadinessError:
        forged_closed = True
    values = readiness.aggregate_formal(not_ready)
    rendered = [readiness.render_value(report) for report in not_ready]
    record(
        "02 formal values require certificates; not-computed is text and never aggregates",
        forged_closed and values == [] and rendered == ["not_computed"] * 3,
    )


def check_legacy_reader() -> None:
    records = [
        readiness.legacy_metric_record("lopo_v2", 0.9),
        readiness.legacy_metric_record("ltcr", 0.5),
        readiness.legacy_metric_record("M10", {"rows": 14}),
    ]
    record(
        "03 legacy values remain readable but formal values are null/non-comparable",
        all(
            item["compatibility"] == "legacy_noncomparable"
            and item["formal_value"] is None
            and item["current_metric_id"] in readiness.CURRENT_METRICS
            for item in records
        ),
    )


def check_methodology_sidecar() -> None:
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    faults = []
    if status.get("schema_version") != "methodology-status.v2":
        faults.append("unknown sidecar schema")
    if status.get("tex_sha256") != (
        "a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08"
    ):
        faults.append("TeX hash mismatch")
    expected = {
        "lopo_v2": ("descriptive_publication_matrix", "lopo"),
        "ltcr": ("substring_consistency_proxy", "ltcr"),
        "M10": ("exploratory_endpoint_window_annotations", "seam-mqm"),
    }
    for group in status.get("artifact_groups", []):
        old = group.get("old_label")
        if old not in expected:
            faults.append(f"unknown legacy group {old!r}")
            continue
        new_label, formal_cli_name = expected[old]
        if (
            group.get("new_label") != new_label
            or group.get("compatibility") != "legacy_noncomparable"
        ):
            faults.append(f"{old}: label/compatibility mismatch")
        current = readiness.current_formal_report(formal_cli_name)
        formal = group.get("formal_status") or {}
        if (
            formal.get("readiness_status") != "not_ready"
            or formal.get("computation_status") != "not_computed"
            or formal.get("value") is not None
            or set(formal.get("missing_reason_codes") or [])
            != set(current["missing_reason_codes"])
        ):
            faults.append(f"{old}: formal status differs from validator")
        for artifact in group.get("artifacts", []):
            path = ROOT / artifact.get("path", "")
            if not path.is_file() or sha256(path) != artifact.get("sha256"):
                faults.append(f"{artifact.get('path')}: frozen hash mismatch")
    if {group.get("old_label") for group in status.get("artifact_groups", [])} != set(
        expected
    ):
        faults.append("sidecar does not cover exactly the three legacy labels")
    record(
        "04 sidecar labels/reasons match code and every recorded frozen hash",
        not faults,
        "; ".join(faults[:5]),
    )


def check_docs() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)
    required = (
        "descriptive_publication_matrix",
        "substring_consistency_proxy",
        "exploratory_endpoint_window_annotations",
        "not_computed",
        "methodology_status.v2.json",
        "14/14 human review",
    )
    record(
        "05 contract/gap/protocol publish the correction without claiming incomplete review",
        all(item in text for item in required)
        and "MQM_HUMAN_REVIEW_INCOMPLETE" not in text,
    )


def main() -> int:
    check_current_ids()
    check_formal_certificate_and_aggregation()
    check_legacy_reader()
    check_methodology_sidecar()
    check_docs()
    failed = [name for name, ok, _detail in RESULTS if not ok]
    print(f"spec_check_eval_labels: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
