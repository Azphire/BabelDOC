"""Offline verifier for frozen magazine chain and TOC truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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


def _require_box(value, where: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise VerificationError(f"invalid source box: {where}")
    try:
        box = tuple(float(item) for item in value)
    except (TypeError, ValueError) as error:
        raise VerificationError(f"invalid source box: {where}") from error
    if not all(math.isfinite(item) for item in box) or not (
        box[0] < box[2] and box[1] < box[3]
    ):
        raise VerificationError(f"invalid source box: {where}")
    return box


def _union_box(boxes) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _box_contains(outer, inner, tolerance: float = 0.001) -> bool:
    return (
        outer[0] - tolerance <= inner[0]
        and outer[1] - tolerance <= inner[1]
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
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


def _verify_inputs(
    expectations_path: Path,
    source: Path,
    output: Path,
    source_lang: str,
    target_lang: str,
) -> dict:
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
    if hashlib.sha256(source.read_bytes()).hexdigest() != expectations.get(
        "source_sha256"
    ):
        raise VerificationError("source PDF hash disagrees with expectations")
    return expectations


def _toc_anchor_inventory(expectations: dict) -> dict | None:
    """Load compact frozen nodes when this is one of the demo fixtures."""
    sample_id = expectations.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id:
        raise VerificationError("expectations sample id is missing")
    corpus_path = Path(__file__).resolve().parents[1] / "corpus" / f"{sample_id}.json"
    if not corpus_path.is_file():
        # Small synthetic verifier tests intentionally have no repository
        # corpus. Their aliases are already the physical parent aliases.
        return None
    corpus = _read(corpus_path)
    if (
        corpus.get("sample_id") != sample_id
        or corpus.get("source_sha256") != expectations.get("source_sha256")
    ):
        raise VerificationError(f"TOC corpus identity disagrees: {corpus_path}")
    nodes = corpus.get("nodes")
    if not isinstance(nodes, list):
        raise VerificationError(f"TOC corpus nodes are missing: {corpus_path}")
    by_ref = {}
    for node in nodes:
        reference = node.get("source_ref") if isinstance(node, dict) else None
        if (
            not isinstance(reference, str)
            or REF_PATTERN.fullmatch(reference) is None
            or reference in by_ref
        ):
            raise VerificationError(f"TOC corpus refs are invalid: {corpus_path}")
        _member_signature(node, f"TOC corpus node {reference}")
        by_ref[reference] = node
    return by_ref


def verify_toc(
    expectations_path: Path,
    source: Path,
    output: Path,
    working_dir: Path,
    source_lang: str,
    target_lang: str,
):
    """Verify frozen TOC records against the line-structure sidecar."""
    expectations = _verify_inputs(
        expectations_path,
        source,
        output,
        source_lang,
        target_lang,
    )
    report = _read(working_dir / "line_split.report.json")
    if report.get("switch") != "magazine_line_structure":
        raise VerificationError("line structure pass was not enabled")
    for page in report.get("pages", []):
        if page.get("lines_before") != page.get("lines_after"):
            raise VerificationError(f"source lines changed on p{page.get('page')}")
        if page.get("characters_before") != page.get("characters_after"):
            raise VerificationError(
                f"source character count changed on p{page.get('page')}"
            )
        if page.get("source_characters_sha256") != page.get(
            "result_characters_sha256"
        ):
            raise VerificationError(
                f"source character order changed on p{page.get('page')}"
            )

    units = report.get("source_units")
    if not isinstance(units, list):
        raise VerificationError("line split source unit inventory is missing")
    refs = [unit.get("source_ref") for unit in units]
    if any(
        not isinstance(reference, str)
        or REF_PATTERN.fullmatch(reference) is None
        for reference in refs
    ) or len(refs) != len(set(refs)):
        raise VerificationError("line split source refs are invalid or duplicated")
    allowed_kinds = {"single_visual_line", "block", "prose_exempt"}
    parent_groups = {}
    source_parents = {}
    children_by_ref = {}
    for unit in units:
        if unit.get("record_kind") not in allowed_kinds:
            raise VerificationError(f"invalid record kind: {unit.get('source_ref')}")
        parent_ref = unit.get("parent_ref")
        if not isinstance(parent_ref, str) or REF_PATTERN.fullmatch(parent_ref) is None:
            raise VerificationError(f"source alias is missing: {unit.get('source_ref')}")
        parent_refs = unit.get("parent_refs")
        if (
            not isinstance(parent_refs, list)
            or not parent_refs
            or parent_refs[0] != parent_ref
            or len(parent_refs) != len(set(parent_refs))
            or any(
                not isinstance(reference, str)
                or REF_PATTERN.fullmatch(reference) is None
                for reference in parent_refs
            )
        ):
            raise VerificationError(f"source aliases are invalid: {unit.get('source_ref')}")
        group_key = tuple(parent_refs)
        runtime_parent_ref = unit.get("runtime_parent_ref")
        if (
            not isinstance(runtime_parent_ref, str)
            or REF_PATTERN.fullmatch(runtime_parent_ref) is None
        ):
            raise VerificationError(
                f"runtime parent alias is missing: {unit.get('source_ref')}"
            )
        runtime_parent_refs = unit.get("runtime_parent_refs")
        if (
            not isinstance(runtime_parent_refs, list)
            or len(runtime_parent_refs) != len(parent_refs)
            or runtime_parent_refs[0] != runtime_parent_ref
            or len(runtime_parent_refs) != len(set(runtime_parent_refs))
            or any(
                not isinstance(reference, str)
                or REF_PATTERN.fullmatch(reference) is None
                for reference in runtime_parent_refs
            )
        ):
            raise VerificationError(
                f"runtime parent aliases are invalid: {unit.get('source_ref')}"
            )
        if unit.get("runtime_source_ref") != unit.get("source_ref"):
            raise VerificationError(
                f"runtime child alias disagrees: {unit.get('source_ref')}"
            )
        _require_box(unit.get("source_band"), unit.get("source_ref", "unit"))
        _require_sha256(unit, "source_text_sha256", unit.get("source_ref", "unit"))

        parent = unit.get("parent")
        if not isinstance(parent, dict) or parent.get("source_ref") != parent_ref:
            raise VerificationError(f"source parent is invalid: {unit.get('source_ref')}")
        if (
            parent.get("source_refs") != parent_refs
            or parent.get("runtime_source_ref") != runtime_parent_ref
            or parent.get("runtime_source_refs") != runtime_parent_refs
        ):
            raise VerificationError(
                f"runtime parent alias disagrees: {unit.get('source_ref')}"
            )
        _require_box(parent.get("source_box"), f"parent {parent_ref}")
        _require_sha256(parent, "source_text_sha256", f"parent {parent_ref}")
        _require_sha256(parent, "source_characters_sha256", f"parent {parent_ref}")
        _require_sha256(
            parent,
            "ordered_children_characters_sha256",
            f"parent {parent_ref}",
        )
        if (
            parent["source_characters_sha256"]
            != parent["ordered_children_characters_sha256"]
        ):
            raise VerificationError(f"parent/children characters changed: {parent_ref}")
        held_parent = parent_groups.setdefault(group_key, parent)
        if held_parent != parent:
            raise VerificationError(f"inconsistent source parent group: {parent_refs}")

        raw_source_parents = unit.get("source_parents")
        if (
            not isinstance(raw_source_parents, list)
            or [item.get("source_ref") for item in raw_source_parents] != parent_refs
            or [item.get("runtime_source_ref") for item in raw_source_parents]
            != runtime_parent_refs
        ):
            raise VerificationError(f"source parent audit is invalid: {parent_refs}")
        for source_parent in raw_source_parents:
            reference = source_parent["source_ref"]
            _require_box(source_parent.get("source_box"), f"source parent {reference}")
            _require_sha256(
                source_parent,
                "source_text_sha256",
                f"source parent {reference}",
            )
            _require_sha256(
                source_parent,
                "source_characters_sha256",
                f"source parent {reference}",
            )
            held_source_parent = source_parents.setdefault(
                reference,
                (source_parent, group_key),
            )
            if held_source_parent != (source_parent, group_key):
                raise VerificationError(f"inconsistent source parent: {reference}")

        ordered = unit.get("ordered_children")
        if not isinstance(ordered, list) or not ordered:
            raise VerificationError(f"ordered children are missing: {parent_ref}")
        if [child.get("child_order") for child in ordered] != list(
            range(len(ordered))
        ):
            raise VerificationError(f"child order is invalid: {parent_ref}")
        child_refs = [child.get("source_ref") for child in ordered]
        if len(child_refs) != len(set(child_refs)):
            raise VerificationError(f"duplicate child ref: {parent_ref}")
        parent_box = _require_box(parent["source_box"], f"parent {parent_ref}")
        child_boxes = []
        child_characters = 0
        for child in ordered:
            reference = child.get("source_ref")
            if child.get("runtime_source_ref") != reference:
                raise VerificationError(f"runtime child alias disagrees: {reference}")
            if child.get("record_kind") not in allowed_kinds:
                raise VerificationError(f"invalid child kind: {reference}")
            if not isinstance(child.get("fixed_companion"), bool):
                raise VerificationError(f"invalid child translation role: {reference}")
            box = _require_box(child.get("source_band"), f"child {reference}")
            if not _box_contains(parent_box, box):
                raise VerificationError(f"child left parent container: {reference}")
            child_boxes.append(box)
            count = child.get("source_characters")
            if not isinstance(count, int) or count < 0:
                raise VerificationError(f"invalid child character count: {reference}")
            child_characters += count
            _require_sha256(child, "source_text_sha256", f"child {reference}")
            _require_sha256(
                child,
                "source_characters_sha256",
                f"child {reference}",
            )
            held_child = children_by_ref.setdefault(reference, child)
            if held_child != child:
                raise VerificationError(f"inconsistent child record: {reference}")
        if not _box_equal(_union_box(child_boxes), parent_box):
            raise VerificationError(f"children do not conserve parent box: {parent_ref}")
        if parent.get("source_characters") != child_characters:
            raise VerificationError(f"children do not conserve parent text: {parent_ref}")
        matching = next(
            (child for child in ordered if child.get("source_ref") == unit.get("source_ref")),
            None,
        )
        if matching is None or any(
            unit.get(field) != matching.get(field)
            for field in (
                "child_order",
                "record_kind",
                "fixed_companion",
                "runtime_source_ref",
                "source_band",
                "source_text_sha256",
                "source_characters",
                "source_characters_sha256",
            )
        ):
            raise VerificationError(f"flat child audit disagrees: {unit.get('source_ref')}")
    if set(children_by_ref) != set(refs):
        raise VerificationError("flat source units disagree with ordered children")

    frozen_nodes = _toc_anchor_inventory(expectations)
    verified = []
    matched_parent_refs = set()
    for truth in expectations.get("toc_records", []):
        anchors = truth.get("anchor")
        anchors = [anchors] if isinstance(anchors, str) else anchors
        if not isinstance(anchors, list) or not anchors:
            raise VerificationError("TOC truth has no anchors")
        if len(anchors) != len(set(anchors)):
            raise VerificationError(f"TOC truth aliases are duplicated: {anchors}")
        matches = []
        for anchor in anchors:
            if frozen_nodes is None:
                candidates = [source_parents[anchor]] if anchor in source_parents else []
            else:
                frozen = frozen_nodes.get(anchor)
                if frozen is None:
                    raise VerificationError(f"TOC corpus alias is missing: {anchor}")
                candidates = [
                    (parent, group_key)
                    for reference, (parent, group_key) in source_parents.items()
                    if reference.startswith(f"p{frozen['physical_page']}#")
                    and parent.get("source_text_sha256")
                    == frozen.get("source_text_sha256")
                    and _box_equal(parent.get("source_box"), frozen.get("source_box"))
                ]
            if len(candidates) != 1:
                raise VerificationError(
                    f"TOC truth anchor match is not unique: {anchor}"
                )
            parent, group_key = candidates[0]
            if parent["source_ref"] in matched_parent_refs:
                raise VerificationError(f"TOC truth reuses a parent: {anchor}")
            matched_parent_refs.add(parent["source_ref"])
            matches.append((parent, group_key))
        parent_boxes = [
            _require_box(parent["source_box"], f"truth parent {parent['source_ref']}")
            for parent, _group_key in matches
        ]
        if not _box_equal(_union_box(parent_boxes), truth.get("source_box")):
            raise VerificationError(f"TOC parent container mismatch: {anchors}")
        group_keys = list(dict.fromkeys(group_key for _parent, group_key in matches))
        truth_children = [
            child
            for group_key in group_keys
            for child in next(
                unit["ordered_children"] for unit in units
                if tuple(unit["parent_refs"]) == group_key
            )
        ]
        translation_children = [
            child for child in truth_children if not child["fixed_companion"]
        ]
        kinds = [child["record_kind"] for child in translation_children]
        expected_kind = truth.get("kind")
        kind_valid = (
            expected_kind == "single_visual_line"
            and kinds
            and set(kinds) == {"single_visual_line"}
        ) or (
            expected_kind == "block"
            and len(kinds) == 1
            and kinds[0] == "block"
        ) or (
            expected_kind == "prose_exempt"
            and len(kinds) == 1
            and kinds[0] == "prose_exempt"
        )
        if not kind_valid:
            raise VerificationError(f"TOC record kind mismatch: {anchors}")
        child_refs = [child["source_ref"] for child in translation_children]
        if len(child_refs) != len(set(child_refs)):
            raise VerificationError(f"TOC children are not independent: {anchors}")
        verified.append(tuple(child_refs))
    all_verified_children = [reference for record in verified for reference in record]
    if len(all_verified_children) != len(set(all_verified_children)):
        raise VerificationError("two TOC truth records reuse one child item")
    return {
        "check": "toc",
        "sample_id": expectations.get("sample_id"),
        "records": len(verified),
        "status": "pass",
    }


def _parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", required=True, choices=("chain", "toc"))
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
        verifier = verify_chain if args.check == "chain" else verify_toc
        result = verifier(
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
