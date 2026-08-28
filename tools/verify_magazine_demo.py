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
        isinstance(left, (list, tuple))
        and isinstance(right, (list, tuple))
        and len(left) == len(right) == 4
        and all(
            abs(float(a) - float(b)) <= tolerance
            for a, b in zip(left, right, strict=True)
        )
    )


def _member_signature(member: dict, where: str) -> tuple:
    page = member.get("physical_page")
    text_hash = member.get("source_text_sha256")
    box = member.get("source_box")
    if not isinstance(page, int) or page <= 0:
        raise VerificationError(f"invalid physical page: {where}")
    if not isinstance(text_hash, str) or SHA256_PATTERN.fullmatch(text_hash) is None:
        raise VerificationError(f"invalid source text hash: {where}")
    if not isinstance(box, list) or len(box) != 4:
        raise VerificationError(f"invalid source box: {where}")
    try:
        stable_box = tuple(float(value) for value in box)
    except (TypeError, ValueError) as error:
        raise VerificationError(f"invalid source box: {where}") from error
    return page, text_hash, stable_box


def _signature_equal(left: tuple, right: tuple) -> bool:
    return left[:2] == right[:2] and _box_equal(left[2], right[2])


def _chain_signature_equal(left: tuple, right: tuple) -> bool:
    return len(left) == len(right) and all(
        _signature_equal(left_member, right_member)
        for left_member, right_member in zip(left, right, strict=True)
    )


def _expected_chains(expectations: dict):
    expected = []
    for chain in expectations.get("chains", []):
        members = chain.get("ordered_members")
        if not isinstance(members, list) or len(members) < 2:
            raise VerificationError("truth chain has fewer than two members")
        signatures = tuple(
            _member_signature(item, f"truth chain {chain.get('id')}")
            for item in members
        )
        if any(
            _chain_signature_equal(signatures, held_signatures)
            for held_signatures, _held_chain in expected
        ):
            refs = tuple(_truth_ref(item) for item in members)
            raise VerificationError(f"duplicate truth chain: {refs}")
        expected.append((signatures, chain))
    return expected


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

    expected = _expected_chains(expectations)
    detector = _read(working_dir / "chain_report.json")
    detected = []
    for chain in detector.get("chains", []):
        rows = chain.get("members")
        if not isinstance(rows, list) or len(rows) < 2:
            raise VerificationError("detector chain has fewer than two members")
        refs = tuple(row.get("source_ref") for row in rows)
        if any(
            not isinstance(reference, str)
            or REF_PATTERN.fullmatch(reference) is None
            for reference in refs
        ):
            raise VerificationError(f"detector has invalid source refs: {refs}")
        signatures = tuple(
            _member_signature(row, f"detector member {reference}")
            for reference, row in zip(refs, rows, strict=True)
        )
        detected.append((signatures, rows, refs))

    truth_by_actual_ref = {}
    expected_actual_chains = {}
    matched_truth = set()
    for signatures, rows, refs in detected:
        candidates = [
            index
            for index, (truth_signatures, _truth_chain) in enumerate(expected)
            if _chain_signature_equal(signatures, truth_signatures)
        ]
        if not candidates:
            raise VerificationError(f"unadjudicated detector chain: {refs}")
        if len(candidates) != 1:
            raise VerificationError(f"ambiguous detector truth match: {refs}")
        truth_index = candidates[0]
        if truth_index in matched_truth:
            raise VerificationError(f"duplicate detector chain: {refs}")
        matched_truth.add(truth_index)
        truth_chain = expected[truth_index][1]
        truth_members = truth_chain["ordered_members"]
        if refs in expected_actual_chains:
            raise VerificationError(f"duplicate detector refs: {refs}")
        expected_actual_chains[refs] = truth_index
        for order, (reference, row, truth) in enumerate(
            zip(refs, rows, truth_members, strict=True)
        ):
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
            if reference in truth_by_actual_ref:
                raise VerificationError(f"detector member repeated: {reference}")
            truth_by_actual_ref[reference] = truth
    if matched_truth != set(range(len(expected))):
        missing = [
            expected[index][1].get("id")
            for index in sorted(set(range(len(expected))) - matched_truth)
        ]
        raise VerificationError(f"detector truth mismatch; missing={missing}")

    for negative in expectations.get("negative_chain_pairs", []):
        endpoints = negative.get("endpoints")
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            raise VerificationError("negative truth must have two endpoints")
        signatures = tuple(
            _member_signature(item, f"negative pair {negative.get('id')}")
            for item in endpoints
        )
        for chain_signatures, _rows, _refs in detected:
            for left, right in zip(
                chain_signatures, chain_signatures[1:], strict=False
            ):
                direct = _signature_equal(signatures[0], left) and _signature_equal(
                    signatures[1], right
                )
                reverse = _signature_equal(signatures[1], left) and _signature_equal(
                    signatures[0], right
                )
                if direct or reverse:
                    refs = tuple(_truth_ref(item) for item in endpoints)
                    raise VerificationError(
                        f"negative endpoints formed a chain: {refs}"
                    )

    translation = _read(working_dir / "chain_translation.report.json")
    if translation.get("applied") is not True:
        raise VerificationError("chain translation plan was not applied")

    outcomes = {}
    for item in translation.get("outcomes", []):
        refs = _report_refs(item, "translation outcome")
        if refs in outcomes:
            raise VerificationError(f"duplicate translation outcome: {refs}")
        if refs not in expected_actual_chains:
            raise VerificationError(f"unadjudicated translation outcome: {refs}")
        outcomes[refs] = item
    if set(outcomes) != set(expected_actual_chains):
        raise VerificationError("translation outcome set disagrees with truth")
    for refs, item in outcomes.items():
        if item.get("outcome") != "joint_success" or item.get("fallback_reason"):
            raise VerificationError(
                "truth chain fallback: "
                f"refs={refs}, reason={item.get('fallback_reason') or item.get('outcome')}"
            )
        _require_sha256(item, "merged_source_sha256", str(refs))
        _require_sha256(item, "whole_target_sha256", str(refs))

    translated = {}
    for chain in translation.get("chains", []):
        refs = _report_refs(chain, "translated chain")
        if refs in translated:
            raise VerificationError(f"duplicate translated chain: {refs}")
        translated[refs] = chain
    if set(translated) != set(expected_actual_chains):
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
            truth_box = truth_by_actual_ref[reference]["source_box"]
            if not _box_equal(source_box, truth_box) or not _box_equal(
                fragment_box, truth_box
            ):
                raise VerificationError(f"fragment left its source box: {reference}")

    expected_skip_keys = set()
    for refs, chain in translated.items():
        members = chain.get("members")
        if not isinstance(members, list) or len(members) != len(refs):
            raise VerificationError(f"translated member audit mismatch: {refs}")
        chain_id = chain.get("chain_id")
        for order, member in enumerate(members):
            if member.get("source_ref") != refs[order]:
                raise VerificationError(f"translated member ref mismatch: {refs[order]}")
            if member.get("chain_index") != order:
                raise VerificationError(f"translated member order mismatch: {refs[order]}")
            key = (chain_id, order)
            expected_skip_keys.add(key)

    skips = {}
    for item in translation.get("skips", []):
        key = (item.get("chain_id"), item.get("chain_index"))
        if key in skips:
            raise VerificationError(f"duplicate chain skip: {key}")
        if key not in expected_skip_keys:
            raise VerificationError(f"unadjudicated chain skip: {key}")
        declined = set(item.get("declined_by", []))
        if (
            item.get("taken_by") != "chain"
            or "page_batch" not in declined
        ):
            raise VerificationError(f"chain skip does not prove exclusion: {key}")
        skips[key] = item
    if set(skips) != expected_skip_keys:
        raise VerificationError("chain skips do not cover every joint member")

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
    trace_path = working_dir / "run_trace.report.json"
    if trace_path.is_file():
        trace = _read(trace_path)
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
        "members": sum(len(signatures) for signatures, _chain in expected),
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
