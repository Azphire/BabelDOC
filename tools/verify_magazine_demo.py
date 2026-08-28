"""Minimal Stage 01 verifier for frozen magazine chain truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REF_PATTERN = re.compile(r"p\d+#\d+")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class VerificationError(ValueError):
    pass


def _read(path: Path) -> dict:
    if not path.is_file():
        raise VerificationError(f"required sidecar is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationError(f"sidecar must be an object: {path}")
    return value


def _truth_ref(member: dict) -> str:
    diagnostic = member.get("diagnostic_ref")
    match = REF_PATTERN.search(diagnostic or "")
    if match is None:
        raise VerificationError(f"truth member has no source ref: {member}")
    return match.group(0)


def _box_equal(left, right, tolerance: float = 0.001) -> bool:
    return (
        isinstance(left, list)
        and isinstance(right, list)
        and len(left) == len(right) == 4
        and all(
            abs(float(a) - float(b)) <= tolerance
            for a, b in zip(left, right, strict=True)
        )
    )


def _expected_chains(expectations: dict):
    expected = {}
    members = {}
    for chain in expectations.get("chains", []):
        refs = tuple(_truth_ref(item) for item in chain["ordered_members"])
        if refs in expected:
            raise VerificationError(f"duplicate truth chain: {refs}")
        expected[refs] = chain
        for reference, member in zip(refs, chain["ordered_members"], strict=True):
            members[reference] = member
    return expected, members


def _report_refs(record: dict, where: str) -> tuple[str, ...]:
    physical = record.get("ordered_source_refs")
    runtime = record.get("runtime_source_refs")
    if (
        not isinstance(physical, list)
        or not isinstance(runtime, list)
        or len(physical) != len(runtime)
        or any(not isinstance(item, str) for item in physical + runtime)
    ):
        raise VerificationError(f"physical/runtime ref mismatch: {where}")
    return tuple(physical)


def _require_sha256(record: dict, field: str, where: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise VerificationError(f"invalid {field}: {where}")
    return value


def verify_chain(
    expectations_path: Path,
    source: Path,
    output: Path,
    working_dir: Path,
    source_lang: str,
    target_lang: str,
):
    expectations = _read(expectations_path)
    actual_direction = f"{source_lang}-{target_lang}"
    if expectations.get("direction") != actual_direction:
        raise VerificationError(
            "language direction disagrees with expectations: "
            f"expected={expectations.get('direction')}, actual={actual_direction}"
        )
    if not source.is_file():
        raise VerificationError(f"source PDF is missing: {source}")
    if not output.is_file():
        raise VerificationError(f"translated PDF is missing: {output}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != expectations.get("source_sha256"):
        raise VerificationError("source PDF hash disagrees with expectations")

    expected, truth_members = _expected_chains(expectations)
    detector = _read(working_dir / "chain_report.json")
    detected = {}
    for chain in detector.get("chains", []):
        rows = chain.get("members")
        if not isinstance(rows, list) or len(rows) < 2:
            raise VerificationError("detector chain has fewer than two members")
        refs = tuple(row.get("source_ref") for row in rows)
        if refs in detected:
            raise VerificationError(f"duplicate detector chain: {refs}")
        detected[refs] = rows
    if set(detected) != set(expected):
        missing = sorted(set(expected) - set(detected))
        extra = sorted(set(detected) - set(expected))
        raise VerificationError(
            f"detector truth mismatch; missing={missing}, extra={extra}"
        )
    for refs, rows in detected.items():
        for order, (reference, row) in enumerate(zip(refs, rows, strict=True)):
            truth = truth_members[reference]
            if row.get("order", row.get("chain_index")) != order:
                raise VerificationError(f"detector order mismatch: {reference}")
            if row.get("physical_page") != truth.get("physical_page"):
                raise VerificationError(f"detector page mismatch: {reference}")
            if row.get("source_text_sha256") != truth.get("source_text_sha256"):
                raise VerificationError(f"detector text hash mismatch: {reference}")
            if not _box_equal(row.get("source_box"), truth.get("source_box")):
                raise VerificationError(f"detector source box mismatch: {reference}")
            if row.get("role") not in {"plain text", "text", "body"}:
                raise VerificationError(f"detector role is not body: {reference}")

    for negative in expectations.get("negative_chain_pairs", []):
        refs = tuple(_truth_ref(item) for item in negative["endpoints"])
        for chain_refs in detected:
            adjacent_pairs = set(zip(chain_refs, chain_refs[1:], strict=False))
            if refs in adjacent_pairs or refs[::-1] in adjacent_pairs:
                raise VerificationError(f"negative endpoints formed a chain: {refs}")

    translation = _read(working_dir / "chain_translation.report.json")
    if translation.get("applied") is not True:
        raise VerificationError("chain translation plan was not applied")
    translated = {}
    for chain in translation.get("chains", []):
        refs = _report_refs(chain, "translated chain")
        if refs in translated:
            raise VerificationError(f"duplicate translated chain: {refs}")
        translated[refs] = chain
    if set(translated) != set(expected):
        raise VerificationError("translated chain set disagrees with truth")
    for refs, chain in translated.items():
        fragments = chain.get("ordered_fragments")
        source_boxes = chain.get("source_boxes")
        fragment_boxes = chain.get("fragment_boxes")
        if chain.get("joint_call_count") != 1:
            raise VerificationError(f"chain was not translated exactly once: {refs}")
        if chain.get("outcome") != "joint_success" or chain.get("fallback_reason"):
            raise VerificationError(f"chain did not finish jointly: {refs}")
        _require_sha256(chain, "merged_source_sha256", str(refs))
        whole_target_sha256 = _require_sha256(chain, "whole_target_sha256", str(refs))
        if not isinstance(fragments, list) or len(fragments) != len(refs):
            raise VerificationError(f"fragment count mismatch: {refs}")
        if any(not isinstance(fragment, str) or not fragment for fragment in fragments):
            raise VerificationError(f"empty body fragment: {refs}")
        whole = "".join(fragments)
        if hashlib.sha256(whole.encode("utf-8")).hexdigest() != whole_target_sha256:
            raise VerificationError(f"whole target conservation failed: {refs}")
        if len(source_boxes or []) != len(refs) or len(fragment_boxes or []) != len(
            refs
        ):
            raise VerificationError(f"fragment box count mismatch: {refs}")
        for reference, source_box, fragment_box in zip(
            refs, source_boxes, fragment_boxes, strict=True
        ):
            truth_box = truth_members[reference]["source_box"]
            if not _box_equal(source_box, truth_box) or not _box_equal(
                fragment_box, truth_box
            ):
                raise VerificationError(f"fragment left its source box: {reference}")

    outcomes = {}
    for item in translation.get("outcomes", []):
        refs = _report_refs(item, "translation outcome")
        if refs in outcomes:
            raise VerificationError(f"duplicate translation outcome: {refs}")
        if item.get("outcome") != "joint_success" or item.get("fallback_reason"):
            raise VerificationError("chain report contains a fallback outcome")
        _require_sha256(item, "merged_source_sha256", str(refs))
        _require_sha256(item, "whole_target_sha256", str(refs))
        outcomes[refs] = item
    if set(outcomes) != set(expected):
        raise VerificationError("translation outcome set disagrees with truth")

    trace = _read(working_dir / "run_trace.report.json")
    runtime_by_physical = {
        physical: runtime
        for chain in translation.get("chains", [])
        for physical, runtime in zip(
            chain.get("ordered_source_refs", []),
            chain.get("runtime_source_refs", chain.get("ordered_source_refs", [])),
            strict=True,
        )
    }
    chain_runtime_refs = set(runtime_by_physical.values())
    for request in trace.get("requests", []):
        overlap = chain_runtime_refs.intersection(
            request.get("ordered_source_refs", [])
        )
        if overlap and request.get("request_kind") != "continuity_chain":
            raise VerificationError(
                f"joint member reached ordinary producer: {sorted(overlap)}"
            )

    return {
        "check": "chain",
        "sample_id": expectations.get("sample_id"),
        "chains": len(expected),
        "members": sum(len(refs) for refs in expected),
        "status": "pass",
    }


def _parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", required=True, choices=("chain",))
    parser.add_argument("--expectations", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--working-dir", "--run-dir", dest="working_dir", required=True, type=Path
    )
    parser.add_argument("--source-lang", required=True)
    parser.add_argument("--target-lang", required=True)
    parser.add_argument("--pages")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_chain(
            args.expectations,
            args.source,
            args.output,
            args.working_dir,
            args.source_lang,
            args.target_lang,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"check": args.check, "status": "fail", "error": str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
