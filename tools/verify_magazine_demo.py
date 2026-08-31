"""Offline verifier for frozen magazine chain, TOC, layout, and title truth."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import pymupdf
from babeldoc.magazine.line_split import load_line_split_config

REF_PATTERN = re.compile(r"p\d+#\d+")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COVERAGE_REPORT_NAME = "demo_coverage.report.json"
COVERAGE_SCHEMA_VERSION = "demo-coverage.v1"
COVERAGE_FIELDS = {
    "source_ref",
    "physical_page",
    "role",
    "source_text_sha256",
    "source_box",
    "translation_owner",
    "target_text_sha256",
    "final_status",
}
COVERAGE_OPTIONAL_FIELDS = {"runtime_source_ref"}
COVERAGE_OWNERS = {"joint", "ordinary", "preserve", "none"}
BODY_ROLES = {"body", "text", "plain text", "paragraph_hybrid"}
DROPCAP_COMPANION_ROLE = "drop_cap_companion"
HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_PATTERN = re.compile(r"[A-Za-z]")
DROPCAP_FIELDS = {
    "source_ref",
    "decision",
    "target_char",
    "target_index",
    "direction_policy",
    "metric_source",
    "initial_box",
    "anchor",
    "before_target_sha256",
    "after_target_sha256",
    "status",
    "failure_reason",
}
DROPCAP_METRIC_SOURCES = {
    "pymupdf.Font.glyph_bbox",
    "advance_em_fallback",
}
STYLE_TAG_PATTERN = re.compile(
    r"</?style(?:\s+id=(?:'[^']+'|\"[^\"]+\"))?\s*>",
    re.IGNORECASE,
)
FROZEN_BOX_TOLERANCE = 0.5
SOURCE_PAGE_BOUNDARY_TOLERANCE = 0.01


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


def _frozen_box_equal(left, right) -> bool:
    """Allow sub-point PDF normalization drift only at the frozen-truth boundary."""
    return _box_equal(left, right, tolerance=FROZEN_BOX_TOLERANCE)


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


def _boxes_overlap(left, right, tolerance: float) -> bool:
    return (
        min(left[2], right[2]) - max(left[0], right[0]) > tolerance
        and min(left[3], right[3]) - max(left[1], right[1]) > tolerance
    )


def _source_pdf_page_boundaries(
    source: Path,
    physical_pages: set[int],
) -> dict[int, tuple[float, float, float, float]]:
    """Read page bounds in the normalized coordinates used by the IL.

    ``fix_media_box`` rewrites the original MediaBox as ``[0 0 x1 y1]`` and
    removes CropBox before IL parsing. Mirror that exact preprocessing here:
    an original CropBox, even when smaller, cannot shrink the product frame.
    """
    if any(page <= 0 for page in physical_pages):
        raise VerificationError("allocation obstacle page is invalid")
    try:
        document = pymupdf.open(source)
    except (RuntimeError, ValueError) as error:
        raise VerificationError(f"source PDF cannot be opened: {source}") from error
    try:
        boundaries = {}
        for physical_page in sorted(physical_pages):
            if physical_page > document.page_count:
                raise VerificationError(
                    f"source PDF has no physical page: p{physical_page}"
                )
            pdf_page = document[physical_page - 1]
            media = getattr(pdf_page, "mediabox", None)
            coordinates = (
                () if media is None else tuple(float(value) for value in media)
            )
            if (
                len(coordinates) != 4
                or not all(math.isfinite(value) for value in coordinates)
                or not (
                    coordinates[0] < coordinates[2]
                    and coordinates[1] < coordinates[3]
                    and coordinates[2] > 0
                    and coordinates[3] > 0
                )
            ):
                raise VerificationError(
                    f"source PDF page boundary is invalid: p{physical_page}"
                )
            boundaries[physical_page] = (
                0.0,
                0.0,
                coordinates[2],
                coordinates[3],
            )
        return boundaries
    finally:
        document.close()


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


def _stage_pages(expectations: dict) -> frozenset[int]:
    """The physical pages the frozen truth was authored over.

    Read from the expectations and never from ``--pages``: the caller chooses
    which pages to run, the truth file decides which pages it can adjudicate.
    """
    pages = expectations.get("stage_pages")
    if not isinstance(pages, list) or not pages:
        raise VerificationError("expectations declare no stage pages")
    for page in pages:
        if not isinstance(page, int) or isinstance(page, bool) or page <= 0:
            raise VerificationError(f"invalid stage page: {page!r}")
    return frozenset(pages)


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

    # The detector walks the whole document; the truth is authored over the
    # staged pages. A chain wholly outside that scope has no truth to be
    # judged against unless the truth reaches out and declares it anyway, and
    # one that straddles the boundary has truth for only part of itself, which
    # is not something this verifier is willing to call verified.
    stage_pages = _stage_pages(expectations)
    truth_signatures = [signatures for signatures, _chain in expected]
    adjudicated = []
    out_of_scope_refs = set()
    for signatures, rows, refs in detected:
        pages = {signature[0] for signature in signatures}
        inside = pages & stage_pages
        outside = pages - stage_pages
        if inside and outside:
            raise VerificationError(f"chain straddles the declared scope: {refs}")
        if not inside and not any(
            _chain_signature_equal(signatures, held) for held in truth_signatures
        ):
            out_of_scope_refs.add(refs)
            continue
        adjudicated.append((signatures, rows, refs))

    truth_by_actual_ref = {}
    expected_actual_chains = {}
    matched_truth = set()
    for signatures, rows, refs in adjudicated:
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
    seen_outcome_refs = set()
    for item in translation.get("outcomes", []):
        refs = _report_refs(item, "translation outcome")
        if refs in seen_outcome_refs:
            raise VerificationError(f"duplicate translation outcome: {refs}")
        seen_outcome_refs.add(refs)
        if refs in out_of_scope_refs:
            continue
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
    seen_translated_refs = set()
    out_of_scope_chain_ids = set()
    for chain in translation.get("chains", []):
        refs = _report_refs(chain, "translated chain")
        if refs in seen_translated_refs:
            raise VerificationError(f"duplicate translated chain: {refs}")
        seen_translated_refs.add(refs)
        if refs in out_of_scope_refs:
            out_of_scope_chain_ids.add(chain.get("chain_id"))
            continue
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

    # Two passes take paragraphs out of the page batch and each leaves its own
    # kind of record, so each is adjudicated against its own evidence. A chain
    # member is proved excluded by the page batch having asked for it and been
    # refused; a short unit sits below the page batch's length floor, which
    # returns before it ever asks, so its proof is that nobody asked at all.
    skips = {}
    short_unit_skips = {}
    for item in translation.get("skips", []):
        owner = item.get("taken_by")
        declined = set(item.get("declined_by", []))
        if owner == "chain":
            key = (item.get("chain_id"), item.get("chain_index"))
            if item.get("chain_id") in out_of_scope_chain_ids:
                continue
            if key in skips:
                raise VerificationError(f"duplicate chain skip: {key}")
            if key not in expected_skip_keys:
                raise VerificationError(f"unadjudicated chain skip: {key}")
            if "page_batch" not in declined:
                raise VerificationError(f"chain skip does not prove exclusion: {key}")
            skips[key] = item
        elif owner == "short_unit":
            key = (item.get("page_index"), item.get("debug_id"))
            if key in short_unit_skips:
                raise VerificationError(f"duplicate short unit skip: {key}")
            if item.get("chain_id") != "" or item.get("chain_index") is not None:
                raise VerificationError(f"short unit skip carries chain identity: {key}")
            if declined:
                raise VerificationError(
                    f"short unit skip was refused a producer it never reached: {key}"
                )
            short_unit_skips[key] = item
        else:
            raise VerificationError(f"unknown skip owner: {owner}")
    if set(skips) != expected_skip_keys:
        raise VerificationError("chain skips do not cover every joint member")

    short_units = translation.get("short_units")
    if short_units is None:
        if short_unit_skips:
            raise VerificationError("short unit skips without a short unit report")
    else:
        admitted = short_units.get("admitted")
        if not isinstance(admitted, int) or isinstance(admitted, bool):
            raise VerificationError(f"invalid short unit admitted count: {admitted!r}")
        if admitted != len(short_unit_skips):
            raise VerificationError(
                "short unit skips do not cover every admitted unit: "
                f"admitted={admitted}, skips={len(short_unit_skips)}"
            )

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
        "out_of_scope_chains": len(out_of_scope_refs),
        "short_unit_skips": len(short_unit_skips),
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
    raw_obstacles = report.get("allocation_obstacles")
    if not isinstance(raw_obstacles, list):
        raise VerificationError("line split allocation obstacle inventory is missing")
    obstacles_by_page: dict[
        int,
        list[tuple[str, str, tuple[float, float, float, float]]],
    ] = {}
    obstacle_refs = set()
    for obstacle in raw_obstacles:
        if not isinstance(obstacle, dict) or set(obstacle) != {
            "page",
            "kind",
            "source_ref",
            "box",
        }:
            raise VerificationError("allocation obstacle record is malformed")
        page = obstacle["page"]
        kind = obstacle["kind"]
        reference = obstacle["source_ref"]
        if (
            not isinstance(page, int)
            or kind
            not in {
                "paragraph",
                "pdf_figure",
                "layout_figure",
                "page_boundary",
            }
            or not isinstance(reference, str)
            or reference in obstacle_refs
            or (
                kind == "paragraph"
                and (
                    REF_PATTERN.fullmatch(reference) is None
                    or not reference.startswith(f"p{page}#")
                )
            )
            or (
                kind != "paragraph"
                and not reference.startswith(f"p{page}:{kind}#")
            )
        ):
            raise VerificationError(f"allocation obstacle identity is invalid: {reference}")
        obstacle_refs.add(reference)
        obstacles_by_page.setdefault(page, []).append(
            (
                kind,
                reference,
                _require_box(obstacle["box"], f"obstacle {reference}"),
            )
        )
    source_page_boundaries = _source_pdf_page_boundaries(
        source,
        set(obstacles_by_page),
    )
    for page, obstacles in obstacles_by_page.items():
        page_boundaries = [
            box for kind, _reference, box in obstacles if kind == "page_boundary"
        ]
        if len(page_boundaries) != 1 or not _box_equal(
            page_boundaries[0],
            source_page_boundaries[page],
            tolerance=SOURCE_PAGE_BOUNDARY_TOLERANCE,
        ):
            raise VerificationError(
                f"allocation page boundary disagrees with source PDF: p{page}"
            )
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
            if not isinstance(child.get("allocation_allows_wrap"), bool):
                raise VerificationError(f"invalid child wrap evidence: {reference}")
            box = _require_box(child.get("source_band"), f"child {reference}")
            allocation = _require_box(
                child.get("allocation_band"), f"allocation child {reference}"
            )
            basis = child.get("allocation_basis")
            if (
                not _box_contains(allocation, box)
                or not isinstance(basis, list)
                or not basis
                or len(basis) != len(set(basis))
                or reference not in basis
            ):
                raise VerificationError(
                    f"child allocation evidence is invalid: {reference}"
                )
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
                "allocation_band",
                "allocation_basis",
                "allocation_allows_wrap",
                "source_text_sha256",
                "source_characters",
                "source_characters_sha256",
            )
        ):
            raise VerificationError(f"flat child audit disagrees: {unit.get('source_ref')}")
    if set(children_by_ref) != set(refs):
        raise VerificationError("flat source units disagree with ordered children")
    split_config = load_line_split_config()
    record_gap_ratio = split_config.record_gap_ratio
    scan_step = split_config.scan_step
    for reference, child in children_by_ref.items():
        source = _require_box(child["source_band"], reference)
        allocation = _require_box(child["allocation_band"], reference)
        basis = child["allocation_basis"]
        allows_wrap = child["allocation_allows_wrap"]
        page = int(reference.split("#", 1)[0][1:])
        matching_obstacles = [
            box
            for kind, obstacle_ref, box in obstacles_by_page.get(page, [])
            if kind == "paragraph" and obstacle_ref == reference
        ]
        if len(matching_obstacles) != 1 or not _box_equal(
            matching_obstacles[0], source
        ):
            raise VerificationError(
                f"source unit is absent from obstacle inventory: {reference}"
            )
        page_boundaries = [
            box
            for kind, _obstacle_ref, box in obstacles_by_page.get(page, [])
            if kind == "page_boundary"
        ]
        if (
            len(page_boundaries) != 1
            or not _box_contains(page_boundaries[0], source)
            or not _box_contains(page_boundaries[0], allocation)
        ):
            raise VerificationError(
                f"allocation page boundary is invalid: {reference}"
            )
        if _box_equal(source, allocation):
            if basis != [reference] or allows_wrap:
                raise VerificationError(
                    f"unexpanded child has foreign allocation basis: {reference}"
                )
            continue
        if (
            child["record_kind"] != "single_visual_line"
            or len(basis) < 3
            or abs(allocation[0] - source[0]) > 0.001
            or abs(allocation[3] - source[3]) > 0.001
            or allocation[1] > source[1] + 0.001
            or allocation[2] < source[2] - 0.001
        ):
            raise VerificationError(f"expanded child allocation is invalid: {reference}")
        peers = [children_by_ref.get(peer_ref) for peer_ref in basis]
        if any(peer is None or peer.get("fixed_companion") for peer in peers):
            raise VerificationError(f"allocation basis is unresolved: {reference}")
        page_prefix = reference.split("#", 1)[0]
        if any(peer_ref.split("#", 1)[0] != page_prefix for peer_ref in basis):
            raise VerificationError(f"allocation basis crosses pages: {reference}")
        for peer_ref, peer in zip(basis, peers, strict=True):
            peer_box = _require_box(peer["source_band"], peer_ref)
            source_height = source[3] - source[1]
            peer_height = peer_box[3] - peer_box[1]
            tolerance = min(source_height, peer_height) / record_gap_ratio
            if max(source_height, peer_height) / min(
                source_height, peer_height
            ) > record_gap_ratio:
                raise VerificationError(
                    f"allocation basis mixes record scales: {reference}"
                )
            if abs(peer_box[0] - source[0]) > tolerance:
                raise VerificationError(f"allocation basis left the lane: {reference}")
            if peer_ref != reference and not (
                peer_box[3] <= source[1] + scan_step
                or peer_box[1] >= source[3] - scan_step
            ):
                raise VerificationError(
                    f"allocation basis is not vertically independent: {reference}"
                )
        expected_x2 = max(
            _require_box(peer["source_band"], peer_ref)[2]
            for peer_ref, peer in zip(basis, peers, strict=True)
        )
        page_obstacles = [
            (kind, obstacle_ref, box)
            for kind, obstacle_ref, box in obstacles_by_page.get(page, [])
            if kind != "page_boundary" and obstacle_ref != reference
        ]

        def intersections(region, obstacles=page_obstacles):
            return [
                obstacle_ref
                for _kind, obstacle_ref, box in obstacles
                if _boxes_overlap(region, box, scan_step)
            ]

        horizontal_candidate = [source[2], source[1], expected_x2, source[3]]
        horizontal_obstacles = (
            intersections(horizontal_candidate)
            if expected_x2 > source[2] + scan_step
            else []
        )
        if abs(allocation[2] - expected_x2) <= 0.001:
            if horizontal_obstacles:
                raise VerificationError(
                    f"allocation region intersects obstacle: {reference}"
                )
        elif abs(allocation[2] - source[2]) <= 0.001:
            if expected_x2 > source[2] + scan_step and not horizontal_obstacles:
                raise VerificationError(
                    f"allocation lane edge is not proved: {reference}"
                )
        else:
            raise VerificationError(f"allocation lane edge is not proved: {reference}")

        below_boxes = [
            (peer_ref, _require_box(peer["source_band"], peer_ref))
            for peer_ref, peer in zip(basis, peers, strict=True)
            if peer_ref != reference
            and _require_box(peer["source_band"], peer_ref)[3]
            <= source[1] + scan_step
        ]
        candidate_y = source[1]
        if below_boxes:
            _boundary_ref, boundary_box = max(
                below_boxes,
                key=lambda held: held[1][3],
            )
            held_y = boundary_box[3] + scan_step
            if held_y < source[1] - scan_step:
                candidate_y = held_y
        else:
            terminal_obstacles = [
                (obstacle_ref, box)
                for _kind, obstacle_ref, box in page_obstacles
                if box[3] <= source[1] + scan_step
                and min(allocation[2], box[2]) - max(source[0], box[0])
                > scan_step
            ]
            if terminal_obstacles:
                _boundary_ref, boundary_box = max(
                    terminal_obstacles,
                    key=lambda held: held[1][3],
                )
                candidate_y = boundary_box[3] + scan_step
            else:
                candidate_y = page_boundaries[0][1] + scan_step
        vertical_candidate = [
            source[0],
            candidate_y,
            allocation[2],
            source[1],
        ]
        vertical_obstacles = (
            intersections(vertical_candidate)
            if candidate_y < source[1] - scan_step
            else []
        )
        has_cell_candidate = candidate_y < source[1] - scan_step
        if has_cell_candidate and abs(allocation[1] - candidate_y) <= 0.001:
            if vertical_obstacles:
                raise VerificationError(
                    f"allocation record cell is not proved: {reference}"
                )
            if not allows_wrap:
                raise VerificationError(
                    f"allocation record cell lacks wrap evidence: {reference}"
                )
        elif abs(allocation[1] - source[1]) <= 0.001:
            if has_cell_candidate and not vertical_obstacles:
                raise VerificationError(
                    f"allocation record cell is not proved: {reference}"
                )
            if allows_wrap:
                raise VerificationError(
                    f"unexpanded record cell allows wrapping: {reference}"
                )
        else:
            raise VerificationError(f"allocation record cell is not proved: {reference}")

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
                    and _frozen_box_equal(
                        parent.get("source_box"), frozen.get("source_box")
                    )
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
        if not _frozen_box_equal(_union_box(parent_boxes), truth.get("source_box")):
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


def verify_layout(
    expectations_path: Path,
    source: Path,
    output: Path,
    working_dir: Path,
    source_lang: str,
    target_lang: str,
):
    """Verify that formal text stayed inside every frozen source holder."""
    expectations = _verify_inputs(
        expectations_path,
        source,
        output,
        source_lang,
        target_lang,
    )
    flow = _read(working_dir / "article_flow.report.json")
    if (
        flow.get("article_flow_applied") is not False
        or flow.get("status") != "disabled"
        or flow.get("totals", {}).get("placements") != 0
    ):
        raise VerificationError("ordinary article flow was applied")

    report = _read(working_dir / "layout_report.json")
    if report.get("article_flow_applied") is not False:
        raise VerificationError("layout report does not prove disabled article flow")
    elements = report.get("elements")
    if not isinstance(elements, list) or not elements:
        raise VerificationError("layout element inventory is missing")
    allowed_roles = {
        "body",
        "chain",
        "single_visual_line",
        "block",
        "prose_exempt",
    }
    by_ref = {}
    for element in elements:
        reference = element.get("source_ref") if isinstance(element, dict) else None
        if (
            not isinstance(reference, str)
            or REF_PATTERN.fullmatch(reference) is None
            or reference in by_ref
        ):
            raise VerificationError("layout source refs are invalid or duplicated")
        if element.get("role") not in allowed_roles:
            raise VerificationError(f"invalid layout role: {reference}")
        if element.get("article_flow_applied") is not False:
            raise VerificationError(f"layout element used article flow: {reference}")
        source_box = _require_box(element.get("source_box"), reference)
        allocation_box = _require_box(
            element.get("allocation_box"), f"allocation {reference}"
        )
        holder_box = _require_box(
            element.get("final_holder_box"), f"holder {reference}"
        )
        text_box = _require_box(element.get("final_text_box"), f"text {reference}")
        if not _box_equal(source_box, allocation_box):
            raise VerificationError(f"allocation changed source holder: {reference}")
        if not _box_equal(source_box, holder_box):
            raise VerificationError(f"formal holder changed source box: {reference}")
        if not _box_contains(source_box, text_box):
            raise VerificationError(f"final text left source box: {reference}")
        if element.get("status") != "success" or element.get("overflow_reason") is not None:
            raise VerificationError(f"layout overflow/failure: {reference}")
        by_ref[reference] = element

    totals = report.get("totals")
    if not isinstance(totals, dict) or totals != {
        "elements": len(elements),
        "overflow": 0,
        "pending": 0,
        "success": len(elements),
    }:
        raise VerificationError("layout totals disagree with element inventory")

    units_path = working_dir / "line_split.report.json"
    if units_path.is_file():
        units = _read(units_path).get("source_units", [])
        unit_boxes = {
            item.get("source_ref"): item.get(
                "allocation_band", item.get("source_band")
            )
            for item in units
            if isinstance(item, dict)
        }
        for reference, element in by_ref.items():
            if element["role"] not in {
                "single_visual_line",
                "block",
                "prose_exempt",
            }:
                continue
            if reference not in unit_boxes or not _box_equal(
                element["source_box"], unit_boxes[reference]
            ):
                raise VerificationError(
                    f"layout source unit disagrees with line split: {reference}"
                )

    chain_path = working_dir / "chain_translation.report.json"
    if chain_path.is_file():
        chain_members = {}
        for chain in _read(chain_path).get("chains", []):
            if chain.get("outcome") != "joint_success":
                continue
            refs = chain.get("ordered_source_refs")
            source_boxes = chain.get("source_boxes")
            fragment_boxes = chain.get("fragment_boxes")
            if (
                not isinstance(refs, list)
                or not isinstance(source_boxes, list)
                or not isinstance(fragment_boxes, list)
                or not len(refs) == len(source_boxes) == len(fragment_boxes)
            ):
                raise VerificationError("chain layout boxes are incomplete")
            for reference, source_box, fragment_box in zip(
                refs, source_boxes, fragment_boxes, strict=True
            ):
                if reference in chain_members:
                    raise VerificationError(
                        f"duplicate chain layout member: {reference}"
                    )
                chain_members[reference] = (source_box, fragment_box)
        for reference, (source_box, fragment_box) in chain_members.items():
            element = by_ref.get(reference)
            if element is None:
                raise VerificationError(f"chain member has no layout holder: {reference}")
            if element["role"] not in {"chain", "prose_exempt"}:
                raise VerificationError(f"chain member has wrong layout role: {reference}")
            if not _box_equal(element["source_box"], source_box):
                raise VerificationError(f"chain source box changed: {reference}")
            if not _box_equal(element["allocation_box"], fragment_box):
                raise VerificationError(f"chain allocation box changed: {reference}")
        unproved_chain = {
            reference
            for reference, element in by_ref.items()
            if element["role"] == "chain" and reference not in chain_members
        }
        if unproved_chain:
            raise VerificationError(
                f"layout chain holders lack joint allocation evidence: {sorted(unproved_chain)}"
            )

    verified_regions = 0
    seen_region_pages = set()
    for region in expectations.get("layout_regions", []):
        page = region.get("physical_page")
        if (
            region.get("role") != "multi_column_page"
            or not isinstance(page, int)
            or page <= 0
            or page in seen_region_pages
        ):
            raise VerificationError("layout region identity is invalid or duplicated")
        seen_region_pages.add(page)
        box = _require_box(region.get("source_box"), f"layout region p{page}")
        page_elements = [
            element
            for reference, element in by_ref.items()
            if int(reference[1 : reference.index("#")]) == page
        ]
        if not page_elements:
            raise VerificationError(f"layout region has no frozen holders: p{page}")
        if any(
            not _box_contains(box, _require_box(element["source_box"], element["source_ref"]))
            for element in page_elements
        ):
            raise VerificationError(f"layout holder left frozen page region: p{page}")
        verified_regions += 1
    return {
        "check": "layout",
        "sample_id": expectations.get("sample_id"),
        "elements": len(elements),
        "regions": verified_regions,
        "status": "pass",
    }


def verify_title(
    expectations_path: Path,
    source: Path,
    output: Path,
    working_dir: Path,
    source_lang: str,
    target_lang: str,
):
    """Verify complete target titles inside their frozen source regions."""
    expectations = _verify_inputs(
        expectations_path,
        source,
        output,
        source_lang,
        target_lang,
    )
    report = _read(working_dir / "title_typeset.report.json")
    if (
        report.get("schema_version") != "title-typeset.v1"
        or report.get("status") != "success"
        or report.get("error") is not None
        or report.get("same_formal_typesetter") is not True
        or report.get("target_lang") != target_lang
    ):
        raise VerificationError("title pass did not complete with the formal typesetter")
    policy = report.get("policy")
    if not isinstance(policy, dict):
        raise VerificationError("title policy evidence is missing")
    minimum_scale = policy.get("minimum_scale")
    maximum_lines = policy.get("maximum_lines")
    if (
        not isinstance(minimum_scale, int | float)
        or isinstance(minimum_scale, bool)
        or not 0 < float(minimum_scale) <= 1
        or not isinstance(maximum_lines, int)
        or isinstance(maximum_lines, bool)
        or maximum_lines < 1
    ):
        raise VerificationError("title policy bounds are invalid")
    if target_lang.lower().replace("_", "-").split("-", 1)[0] == "zh":
        if maximum_lines != 1:
            raise VerificationError("Chinese target title policy is not single-line")

    rows = report.get("titles")
    if not isinstance(rows, list):
        raise VerificationError("title inventory is missing")
    by_ref = {}
    all_members = set()
    duplicate_layers_dropped = 0
    for row in rows:
        reference = row.get("source_ref") if isinstance(row, dict) else None
        if (
            not isinstance(reference, str)
            or REF_PATTERN.fullmatch(reference) is None
            or reference in by_ref
        ):
            raise VerificationError("title owner refs are invalid or duplicated")
        physical_page = row.get("physical_page")
        if (
            not isinstance(physical_page, int)
            or isinstance(physical_page, bool)
            or physical_page < 1
        ):
            raise VerificationError(f"title physical page is invalid: {reference}")
        source_box = _require_box(row.get("source_box"), reference)
        holder_box = _require_box(row.get("final_holder_box"), f"holder {reference}")
        text_box = _require_box(row.get("final_text_box"), f"text {reference}")
        if not _box_equal(source_box, holder_box) or not _box_contains(
            source_box, text_box
        ):
            raise VerificationError(f"title left frozen source region: {reference}")
        if (
            row.get("status") != "success"
            or row.get("failure_reason") is not None
            or not isinstance(row.get("target_chars"), int)
            or row["target_chars"] <= 0
            or _require_sha256(row, "target_sha256", reference)
            != _require_sha256(row, "rendered_target_sha256", reference)
        ):
            raise VerificationError(f"title target conservation failed: {reference}")
        visual_target = row.get("visual_target")
        pre_dedup_target = row.get("pre_dedup_visual_target")
        if (
            not isinstance(visual_target, str)
            or not visual_target
            or len(visual_target) != row["target_chars"]
            or hashlib.sha256(visual_target.encode("utf-8")).hexdigest()
            != row["target_sha256"]
            or not isinstance(pre_dedup_target, str)
            or not pre_dedup_target
            or len(pre_dedup_target) != row.get("pre_dedup_target_chars")
            or hashlib.sha256(pre_dedup_target.encode("utf-8")).hexdigest()
            != _require_sha256(row, "pre_dedup_target_sha256", reference)
        ):
            raise VerificationError(f"title visual target evidence failed: {reference}")
        segments = row.get("target_segments")
        if not isinstance(segments, list) or not segments:
            raise VerificationError(f"title target segments are missing: {reference}")
        segment_refs = []
        segment_pre = []
        segment_targets = []
        row_dropped = 0
        for segment in segments:
            segment_ref = segment.get("source_ref") if isinstance(segment, dict) else None
            segment_before = (
                segment.get("pre_dedup_visual_target")
                if isinstance(segment, dict)
                else None
            )
            segment_target = (
                segment.get("visual_target") if isinstance(segment, dict) else None
            )
            if (
                not isinstance(segment_ref, str)
                or REF_PATTERN.fullmatch(segment_ref) is None
                or not isinstance(segment_before, str)
                or not segment_before
                or not isinstance(segment_target, str)
                or not segment_target
                or len(segment_before) != segment.get("pre_dedup_target_chars")
                or hashlib.sha256(segment_before.encode("utf-8")).hexdigest()
                != _require_sha256(
                    segment, "pre_dedup_target_sha256", segment_ref
                )
                or len(segment_target) != segment.get("target_chars")
                or hashlib.sha256(segment_target.encode("utf-8")).hexdigest()
                != _require_sha256(segment, "target_sha256", segment_ref)
            ):
                raise VerificationError(
                    f"title target segment evidence failed: {reference}"
                )
            proof = segment.get("duplicate_layer")
            if proof is None:
                if segment_before != segment_target:
                    raise VerificationError(
                        f"title changed without duplicate proof: {segment_ref}"
                    )
            else:
                if not isinstance(proof, dict):
                    raise VerificationError(
                        f"title duplicate-layer proof failed: {segment_ref}"
                    )
                style_proof = proof.get("style_proof")
                kept_count = proof.get("kept_composition_count")
                if (
                    segment_before != segment_target + segment_target
                    or proof.get("dropped_layer_count") != 1
                    or not isinstance(kept_count, int)
                    or isinstance(kept_count, bool)
                    or kept_count < 1
                    or proof.get("dropped_composition_count") != kept_count
                    or proof.get("split_composition_index") != kept_count
                    or proof.get("layer_chars") != len(segment_target)
                    or _require_sha256(proof, "layer_sha256", segment_ref)
                    != segment["target_sha256"]
                    or proof.get("paint_may_differ") is not True
                    or not isinstance(style_proof, list)
                    or len(style_proof) != kept_count
                ):
                    raise VerificationError(
                        f"title duplicate-layer proof failed: {segment_ref}"
                    )
                proved_kept = []
                proved_dropped = []
                for position, pair in enumerate(style_proof):
                    kept_styles = (
                        pair.get("kept_style_sequence")
                        if isinstance(pair, dict)
                        else None
                    )
                    dropped_styles = (
                        pair.get("dropped_style_sequence")
                        if isinstance(pair, dict)
                        else None
                    )
                    valid_styles = (
                        isinstance(kept_styles, list)
                        and bool(kept_styles)
                        and kept_styles == dropped_styles
                        and all(
                            isinstance(style, dict)
                            and isinstance(style.get("font_id"), str)
                            and bool(style["font_id"])
                            and isinstance(style.get("font_size"), int | float)
                            and not isinstance(style.get("font_size"), bool)
                            and math.isfinite(float(style["font_size"]))
                            and float(style["font_size"]) > 0
                            for style in kept_styles
                        )
                    )
                    kept_text = pair.get("kept_text") if isinstance(pair, dict) else None
                    dropped_text = (
                        pair.get("dropped_text") if isinstance(pair, dict) else None
                    )
                    if (
                        not isinstance(pair, dict)
                        or pair.get("position") != position
                        or pair.get("kind")
                        not in {
                            "unicode",
                            "character",
                            "same_style_characters",
                            "line",
                        }
                        or not isinstance(kept_text, str)
                        or not kept_text
                        or not isinstance(dropped_text, str)
                        or dropped_text != kept_text
                        or pair.get("kept_chars") != len(kept_text)
                        or pair.get("dropped_chars") != len(dropped_text)
                        or hashlib.sha256(kept_text.encode("utf-8")).hexdigest()
                        != pair.get("kept_text_sha256")
                        or hashlib.sha256(dropped_text.encode("utf-8")).hexdigest()
                        != pair.get("dropped_text_sha256")
                        or _require_sha256(
                            pair, "kept_text_sha256", f"{segment_ref}:{position}"
                        )
                        != _require_sha256(
                            pair,
                            "dropped_text_sha256",
                            f"{segment_ref}:{position}",
                        )
                        or not valid_styles
                    ):
                        raise VerificationError(
                            f"title duplicate style proof failed: {segment_ref}"
                        )
                    proved_kept.append(kept_text)
                    proved_dropped.append(dropped_text)
                if (
                    "".join(proved_kept) != segment_target
                    or "".join(proved_dropped) != segment_target
                ):
                    raise VerificationError(
                        f"title duplicate text proof failed: {segment_ref}"
                    )
                row_dropped += 1
            segment_refs.append(segment_ref)
            segment_pre.append(segment_before)
            segment_targets.append(segment_target)
        if (
            "".join(segment_pre) != pre_dedup_target
            or "".join(segment_targets) != visual_target
            or row.get("duplicate_layers_dropped") != row_dropped
        ):
            raise VerificationError(f"title segment aggregate failed: {reference}")
        duplicate_layers_dropped += row_dropped
        scale = row.get("scale")
        lines = row.get("lines")
        if (
            not isinstance(scale, int | float)
            or isinstance(scale, bool)
            or float(scale) + 1e-9 < float(minimum_scale)
            or not isinstance(lines, int)
            or isinstance(lines, bool)
            or not 1 <= lines <= maximum_lines
            or row.get("minimum_scale") != minimum_scale
            or row.get("maximum_lines") != maximum_lines
        ):
            raise VerificationError(f"title scale/line policy failed: {reference}")
        members = row.get("member_refs")
        suppressed = row.get("suppressed_refs")
        suppressed_holders = row.get("suppressed_holders")
        if (
            not isinstance(members, list)
            or not members
            or members[0] != reference
            or len(members) != len(set(members))
            or any(
                not isinstance(item, str) or REF_PATTERN.fullmatch(item) is None
                for item in members
            )
            or not isinstance(suppressed, list)
            or suppressed != members[1:]
            or not isinstance(suppressed_holders, list)
            or [
                item.get("source_ref") if isinstance(item, dict) else None
                for item in suppressed_holders
            ]
            != suppressed
            or any(
                item.get("final_chars") != 0
                or item.get("composition_count") != 0
                for item in suppressed_holders
            )
            or row.get("owner_ref") != reference
            or segment_refs != members
            or all_members.intersection(members)
        ):
            raise VerificationError(f"title owner/member evidence failed: {reference}")
        all_members.update(members)
        if len(members) > 1 and not row.get("chain_id"):
            raise VerificationError(f"title trailing holder lacks chain proof: {reference}")
        by_ref[reference] = row

    totals = report.get("totals")
    exclusions = report.get("exclusions")
    if not isinstance(exclusions, list) or not isinstance(totals, dict):
        raise VerificationError("title totals/exclusions are missing")
    if totals != {
        "owners": len(rows),
        "success": len(rows),
        "failure": 0,
        "rolled_back": 0,
        "duplicate_layers_dropped": duplicate_layers_dropped,
        "suppressed_trailing_holders": sum(
            len(row["suppressed_refs"]) for row in rows
        ),
        "joint_fit_members": sum(1 for row in rows if row.get("joint_fit")),
        "excluded": len(exclusions),
    }:
        raise VerificationError("title totals disagree with inventory")
    active_refs = set(by_ref)
    for exclusion in exclusions:
        reference = exclusion.get("source_ref") if isinstance(exclusion, dict) else None
        if (
            not isinstance(reference, str)
            or REF_PATTERN.fullmatch(reference) is None
            or not isinstance(exclusion.get("reason"), str)
            or not exclusion["reason"]
        ):
            raise VerificationError("title exclusion evidence is invalid")
        if reference in all_members or reference in active_refs:
            raise VerificationError(f"excluded item entered title pass: {reference}")

    line_split_path = working_dir / "line_split.report.json"
    if line_split_path.is_file():
        toc_refs = {
            item.get("source_ref")
            for item in _read(line_split_path).get("source_units", [])
            if isinstance(item, dict)
        }
        if toc_refs.intersection(all_members):
            raise VerificationError("typed TOC record entered title pass")

    verified = 0
    for truth in expectations.get("titles", []):
        anchor = truth.get("anchor")
        if not isinstance(anchor, str) or REF_PATTERN.fullmatch(anchor) is None:
            raise VerificationError("title truth anchor is invalid")
        expected_box = _require_box(truth.get("source_box"), anchor)
        physical_page = int(anchor[1 : anchor.index("#")])
        matches = [
            row
            for row in rows
            if row["physical_page"] == physical_page
            and _box_equal(row["source_box"], expected_box)
        ]
        if len(matches) != 1:
            raise VerificationError(f"title truth match is not unique: {anchor}")
        verified += 1
    return {
        "check": "title",
        "sample_id": expectations.get("sample_id"),
        "titles": verified,
        "owners": len(rows),
        "status": "pass",
    }


def _dropcap_truth_binding(truth: dict) -> tuple[str, str | None, str]:
    diagnostic = truth.get("diagnostic_ref")
    anchor = truth.get("anchor")
    if (
        not isinstance(diagnostic, str)
        or not isinstance(anchor, str)
        or "paragraph_owner=" not in diagnostic
        or "visual_initial=" not in diagnostic
    ):
        raise VerificationError("drop-cap truth has no owner/visual binding")
    owner_value = diagnostic.split("paragraph_owner=", 1)[1].split(";", 1)[0]
    if owner_value != anchor or REF_PATTERN.fullmatch(owner_value) is None:
        raise VerificationError("drop-cap truth owner disagrees with its anchor")
    value = diagnostic.split("visual_initial=", 1)[1]
    held = re.fullmatch(r"(p\d+#\d+)\((.)\)", value)
    if held is not None:
        return owner_value, held.group(1), held.group(2)
    same = re.fullmatch(r"(.)\(same_paragraph_composition\)", value)
    if same is not None:
        return owner_value, None, same.group(1)
    if not value:
        raise VerificationError("drop-cap truth visual initial is empty")
    raise VerificationError("drop-cap truth visual initial syntax is invalid")


def _verify_dropcap_binding_proof(candidate: dict, intent: dict) -> None:
    owner_ref = candidate.get("paragraph")
    visual_ref = candidate.get("visual_initial_ref")
    proof = candidate.get("binding_proof")
    if (
        not isinstance(owner_ref, str)
        or REF_PATTERN.fullmatch(owner_ref) is None
        or not isinstance(visual_ref, str)
        or REF_PATTERN.fullmatch(visual_ref) is None
        or not isinstance(proof, dict)
        or proof.get("owner_ref") != owner_ref
        or proof.get("visual_initial_ref") != visual_ref
        or proof.get("source_character_count") != 1
        or proof.get("unique_owner_count") != 1
        or proof.get("unique_visual_count") != 1
        or intent.get("visual_initial_ref") != visual_ref
        or intent.get("binding_proof") != proof
    ):
        raise VerificationError(f"drop-cap binding proof is invalid: {owner_ref}")
    ratio = proof.get("size_ratio")
    minimum = proof.get("minimum_size_ratio")
    if (
        not isinstance(ratio, int | float)
        or isinstance(ratio, bool)
        or not isinstance(minimum, int | float)
        or isinstance(minimum, bool)
        or float(ratio) < float(minimum)
    ):
        raise VerificationError(f"drop-cap size proof is invalid: {owner_ref}")
    if proof.get("kind") == "same_paragraph_composition":
        if visual_ref != owner_ref:
            raise VerificationError(f"drop-cap same-paragraph proof split: {owner_ref}")
        return
    try:
        owner_box = _require_box(candidate.get("source_box"), f"drop-cap owner {owner_ref}")
        glyph_box = _require_box(
            proof.get("visual_initial_glyph_box"),
            f"drop-cap visual glyph {owner_ref}",
        )
        first_line_box = _require_box(
            proof.get("owner_first_line_box"),
            f"drop-cap owner first line {owner_ref}",
        )
    except VerificationError as exc:
        raise VerificationError(
            f"drop-cap standalone proof is invalid: {owner_ref}"
        ) from exc
    recomputed_geometry = {
        "logical_start_delta": abs(glyph_box[0] - owner_box[0]),
        "first_line_gap": abs(first_line_box[0] - glyph_box[2]),
        "vertical_gap": max(
            0.0,
            max(glyph_box[1], first_line_box[1])
            - min(glyph_box[3], first_line_box[3]),
        ),
    }
    body_size = proof.get("body_size")
    visual_size = proof.get("visual_font_size")
    if (
        proof.get("kind") != "standalone_visual_initial"
        or visual_ref == owner_ref
        or not isinstance(proof.get("article_id"), str)
        or not proof["article_id"]
        or not isinstance(proof.get("owner_reading_order"), int)
        or not isinstance(proof.get("visual_reading_order"), int)
        or proof["visual_reading_order"] >= proof["owner_reading_order"]
        or not isinstance(proof.get("column"), int)
        or not isinstance(proof.get("body_rank"), int)
        or proof["body_rank"] <= 0
        or not isinstance(proof.get("opens_article"), bool)
        or not isinstance(body_size, int | float)
        or isinstance(body_size, bool)
        or float(body_size) <= 0
        or not isinstance(visual_size, int | float)
        or isinstance(visual_size, bool)
        or float(visual_size) <= 0
        # Product evidence is rounded to six decimals before JSON emission.
        or abs(float(visual_size) / float(body_size) - float(ratio)) > 1e-4
        or not isinstance(proof.get("visual_font_id"), str)
        or not proof["visual_font_id"]
        or not isinstance(proof.get("body_font_id"), str)
        or not proof["body_font_id"]
        or any(
            not isinstance(proof.get(name), int | float)
            or isinstance(proof.get(name), bool)
            or not 0 <= float(proof[name]) <= float(body_size)
            or abs(float(proof[name]) - recomputed_geometry[name]) > 1e-4
            for name in ("logical_start_delta", "first_line_gap", "vertical_gap")
        )
    ):
        raise VerificationError(f"drop-cap standalone proof is invalid: {owner_ref}")


def _verify_dropcap_chain(rows: list[dict], working_dir: Path) -> None:
    path = working_dir / "chain_translation.report.json"
    if not path.is_file():
        return
    chains = _read(path).get("chains")
    if not isinstance(chains, list):
        raise VerificationError("chain translation inventory is invalid")
    for row in rows:
        reference = row["source_ref"]
        matches = [
            chain
            for chain in chains
            if isinstance(chain, dict)
            and reference in (chain.get("ordered_source_refs") or ())
        ]
        if not matches:
            continue
        if len(matches) != 1:
            raise VerificationError(f"drop-cap chain membership is ambiguous: {reference}")
        chain = matches[0]
        refs = chain.get("ordered_source_refs")
        members = chain.get("members")
        index = refs.index(reference)
        if (
            chain.get("outcome") != "joint_success"
            or chain.get("fallback_reason") is not None
            or chain.get("joint_call_count") != 1
            or not isinstance(members, list)
            or index >= len(members)
            or not isinstance(members[index], dict)
            or members[index].get("chain_index") != index
            or members[index].get("source_ref") != reference
        ):
            raise VerificationError(f"drop-cap chain lacks joint-success proof: {reference}")


def _dropcap_owner_target(reference: str, working_dir: Path) -> str:
    """Read one owner's target from an independent translation sidecar."""
    chain_path = working_dir / "chain_translation.report.json"
    chain_matches = []
    if chain_path.is_file():
        chains = _read(chain_path).get("chains")
        if not isinstance(chains, list):
            raise VerificationError("chain translation inventory is invalid")
        for chain in chains:
            refs = chain.get("ordered_source_refs") if isinstance(chain, dict) else None
            if not isinstance(refs, list) or reference not in refs:
                continue
            fragments = chain.get("ordered_fragments")
            index = refs.index(reference)
            if (
                refs.count(reference) != 1
                or not isinstance(fragments, list)
                or len(fragments) != len(refs)
                or not isinstance(fragments[index], str)
                or not fragments[index]
            ):
                raise VerificationError(
                    f"drop-cap chain target evidence is invalid: {reference}"
                )
            chain_matches.append(fragments[index])
    if len(chain_matches) > 1:
        raise VerificationError(f"drop-cap chain target is ambiguous: {reference}")
    if chain_matches:
        target = chain_matches[0]
    else:
        targets = [
            row.get("output")
            for row in _tracking_rows(working_dir)
            if row.get("source_ref") == reference
            and isinstance(row.get("output"), str)
        ]
        if len(targets) != 1:
            raise VerificationError(
                f"drop-cap ordinary target evidence is not unique: {reference}"
            )
        target = targets[0]
    visible = STYLE_TAG_PATTERN.sub("", target)
    if "<style" in visible.lower() or "</style" in visible.lower():
        raise VerificationError(f"drop-cap target has malformed style markup: {reference}")
    return visible


def _verify_dropcap_target_initial(
    row: dict,
    working_dir: Path,
    target_lang: str,
) -> None:
    reference = row["source_ref"]
    target = _dropcap_owner_target(reference, working_dir)
    pattern = LATIN_PATTERN if target_lang.lower().startswith("en") else HAN_PATTERN
    match = pattern.search(target)
    if (
        match is None
        or match.group(0) != row["target_char"]
        or match.start() != row["target_index"]
    ):
        raise VerificationError(
            f"drop-cap initial disagrees with owner target: {reference}"
        )


def verify_dropcap(
    expectations_path: Path,
    source: Path,
    output: Path,
    working_dir: Path,
    source_lang: str,
    target_lang: str,
):
    expectations = _verify_inputs(
        expectations_path,
        source,
        output,
        source_lang,
        target_lang,
    )
    report = _read(working_dir / "drop_cap_render.report.json")
    rows = report.get("paragraphs")
    totals = report.get("totals")
    if (
        report.get("schema_version") != "drop-cap-render.v1"
        or report.get("status") != "success"
        or report.get("target_lang") != target_lang
        or not isinstance(rows, list)
        or not isinstance(totals, dict)
    ):
        raise VerificationError("drop-cap report did not commit cleanly")
    expected_policy = (
        "chinese_two_line_initial"
        if target_lang.lower().startswith("zh")
        else "english_raised_initial"
        if target_lang.lower().startswith("en")
        else None
    )
    if expected_policy is None:
        raise VerificationError("drop-cap verifier has no target direction policy")
    by_ref = {}
    for row in rows:
        # The anchor field arrived in B14; a run made before it carries the
        # same schema without it, and frozen control artifacts stay readable.
        if not isinstance(row, dict) or set(row) not in (
            DROPCAP_FIELDS,
            DROPCAP_FIELDS - {"anchor"},
        ):
            raise VerificationError("drop-cap paragraph schema is not exact")
        reference = row.get("source_ref")
        target_char = row.get("target_char")
        target_index = row.get("target_index")
        initial_box = _require_box(row.get("initial_box"), str(reference))
        if (
            not isinstance(reference, str)
            or REF_PATTERN.fullmatch(reference) is None
            or reference in by_ref
            or row.get("decision") != "keep"
            or row.get("status") != "committed"
            or row.get("failure_reason") is not None
            or not isinstance(target_char, str)
            or len(target_char) != 1
            or not isinstance(target_index, int)
            or isinstance(target_index, bool)
            or target_index < 0
            or row.get("direction_policy") != expected_policy
            or row.get("metric_source") not in DROPCAP_METRIC_SOURCES
            or initial_box[2] <= initial_box[0]
            or initial_box[3] <= initial_box[1]
        ):
            raise VerificationError(f"drop-cap committed record is invalid: {reference}")
        before = _require_sha256(row, "before_target_sha256", reference)
        after = _require_sha256(row, "after_target_sha256", reference)
        if before != after:
            raise VerificationError(f"drop-cap target digest changed: {reference}")
        by_ref[reference] = row
    if (
        totals.get("active") != len(rows)
        or totals.get("committed") != len(rows)
        or totals.get("failure") != 0
    ):
        raise VerificationError("drop-cap totals disagree with committed inventory")

    intent_report = _read(working_dir / "drop_cap_intent.report.json")
    active_intents = [
        item
        for item in intent_report.get("intents", ())
        if isinstance(item, dict)
        and item.get("decision") == "keep"
        and item.get("flatten_status") == "applied"
    ]
    if len(active_intents) != len(rows):
        raise VerificationError("active keep intents disagree with rendered inventory")
    intents_by_ref = {}
    for intent in active_intents:
        reference = intent.get("source_ref")
        row = by_ref.get(reference)
        if (
            row is None
            or intent.get("render_status") != "applied"
            or intent.get("target_char") != row["target_char"]
            or intent.get("target_index") != row["target_index"]
            or intent.get("target_policy") != row["direction_policy"]
        ):
            raise VerificationError(f"drop-cap intent was not committed: {reference}")
        if reference in intents_by_ref:
            raise VerificationError(f"duplicate drop-cap intent: {reference}")
        intents_by_ref[reference] = intent

    source_report = _read(working_dir / "drop_cap.report.json")
    candidates = source_report.get("candidates")
    if not isinstance(candidates, list):
        raise VerificationError("drop-cap source candidate inventory is invalid")
    corpus = _toc_anchor_inventory(expectations)
    verified = 0
    for truth in expectations.get("dropcaps", []):
        anchor = truth.get("anchor")
        if (
            not isinstance(anchor, str)
            or REF_PATTERN.fullmatch(anchor) is None
            or truth.get("decision") != "keep"
        ):
            raise VerificationError("drop-cap truth is invalid")
        page = int(anchor[1 : anchor.index("#")])
        owner_anchor, visual_anchor, source_initial = _dropcap_truth_binding(truth)
        if corpus is None:
            matches = [
                item
                for item in candidates
                if isinstance(item, dict)
                and item.get("page") == page
                and isinstance(item.get("first_run"), str)
                and item["first_run"].startswith(source_initial)
            ]
        else:
            owner_node = corpus.get(owner_anchor)
            visual_node = None if visual_anchor is None else corpus.get(visual_anchor)
            if owner_node is None or (visual_anchor is not None and visual_node is None):
                raise VerificationError(
                    f"drop-cap frozen owner/visual node is missing: {anchor}"
                )
            matches = [
                item
                for item in candidates
                if isinstance(item, dict)
                and item.get("page") == page
                and item.get("source_text_sha256")
                == owner_node.get("source_text_sha256")
                and _frozen_box_equal(
                    item.get("source_box"), owner_node.get("source_box")
                )
                and (
                    visual_node is None
                    or (
                        item.get("visual_initial_text_sha256")
                        == visual_node.get("source_text_sha256")
                        and _frozen_box_equal(
                            item.get("visual_initial_box"),
                            visual_node.get("source_box"),
                        )
                    )
                )
                and isinstance(item.get("first_run"), str)
                and item["first_run"] == source_initial
            ]
        if len(matches) != 1:
            raise VerificationError(f"drop-cap truth match is not unique: {anchor}")
        candidate = matches[0]
        runtime_ref = candidate.get("paragraph")
        if runtime_ref not in by_ref:
            raise VerificationError(f"drop-cap truth was not rendered: {anchor}")
        intent = intents_by_ref.get(runtime_ref)
        if intent is None:
            raise VerificationError(f"drop-cap truth has no active intent: {anchor}")
        _verify_dropcap_binding_proof(candidate, intent)
        if visual_anchor is None:
            if candidate.get("visual_initial_ref") != runtime_ref:
                raise VerificationError(
                    f"drop-cap same-paragraph truth used a companion: {anchor}"
                )
        elif candidate.get("visual_initial_ref") == runtime_ref:
            raise VerificationError(
                f"drop-cap standalone truth lost its companion: {anchor}"
            )
        target_char = by_ref[runtime_ref]["target_char"]
        if (
            target_lang.lower().startswith("en")
            and LATIN_PATTERN.fullmatch(target_char) is None
        ) or (
            target_lang.lower().startswith("zh")
            and HAN_PATTERN.fullmatch(target_char) is None
        ):
            raise VerificationError(
                f"drop-cap committed target initial is invalid: {anchor}"
            )
        _verify_dropcap_target_initial(
            by_ref[runtime_ref],
            working_dir,
            target_lang,
        )
        verified += 1
    _verify_dropcap_chain(rows, working_dir)
    return {
        "check": "dropcap",
        "sample_id": expectations.get("sample_id"),
        "dropcaps": verified,
        "committed": len(rows),
        "status": "pass",
    }


def _parse_physical_pages(value: str) -> tuple[int, ...]:
    pages: list[int] = []
    for raw_piece in value.split(","):
        piece = raw_piece.strip()
        if not piece:
            raise argparse.ArgumentTypeError("pages must not contain empty entries")
        if "-" in piece:
            raw_start, raw_end = piece.split("-", 1)
            if not raw_start.isdigit() or not raw_end.isdigit():
                raise argparse.ArgumentTypeError("pages must be comma-separated integers or ranges")
            start, end = int(raw_start), int(raw_end)
            if start < 1 or end < start:
                raise argparse.ArgumentTypeError("page ranges must be positive and ordered")
            pages.extend(range(start, end + 1))
        else:
            if not piece.isdigit() or int(piece) < 1:
                raise argparse.ArgumentTypeError("pages must be positive integers")
            pages.append(int(piece))
    if not pages or len(pages) != len(set(pages)):
        raise argparse.ArgumentTypeError("pages must be non-empty and unique")
    return tuple(pages)


def _intersection_area(left, right) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    return width * height


def _box_area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _pdf_box_to_source_box(box, page) -> tuple[float, float, float, float]:
    """Convert crop-local PDF coordinates to the pipeline's normalized IL space."""
    held = _require_box(list(box), "PDF text block")
    crop = page.cropbox
    media = page.mediabox
    return (
        held[0] + crop.x0,
        media.y1 - (held[3] + crop.y0),
        held[2] + crop.x0,
        media.y1 - (held[1] + crop.y0),
    )


def _coverage_exemptions(expectations: dict) -> tuple[dict, ...]:
    raw_exemptions = expectations.get("coverage_exemptions", [])
    if not isinstance(raw_exemptions, list):
        raise VerificationError("coverage exemptions must be a list")
    corpus = _toc_anchor_inventory(expectations)
    exemptions = []
    seen = set()
    for position, raw in enumerate(raw_exemptions):
        if not isinstance(raw, dict):
            raise VerificationError(f"coverage exemption {position} is not an object")
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason:
            raise VerificationError(f"coverage exemption {position} has no reason")
        anchors = raw.get("anchor")
        if isinstance(anchors, str):
            anchors = [anchors]
        if not isinstance(anchors, list) or not anchors:
            page = raw.get("physical_page")
            box = raw.get("source_box")
            if not isinstance(page, int) or page < 1 or box is None:
                raise VerificationError(f"coverage exemption {position} has no anchor")
            signature = (page, _require_box(box, f"coverage exemption {position}"))
            if signature in seen:
                raise VerificationError("coverage exemptions are duplicated")
            seen.add(signature)
            exemptions.append({"refs": (), "page": page, "box": signature[1]})
            continue
        for anchor in anchors:
            if not isinstance(anchor, str) or REF_PATTERN.fullmatch(anchor) is None:
                raise VerificationError(f"coverage exemption {position} has an invalid anchor")
            page = int(anchor[1 : anchor.index("#")])
            box = raw.get("source_box")
            if corpus is not None and anchor in corpus:
                node = corpus[anchor]
                page = node["physical_page"]
                box = node["source_box"]
            stable_box = None if box is None else _require_box(box, anchor)
            signature = (anchor, page, stable_box)
            if signature in seen:
                raise VerificationError("coverage exemptions are duplicated")
            seen.add(signature)
            exemptions.append({"refs": (anchor,), "page": page, "box": stable_box})
    return tuple(exemptions)


def _item_is_exempt(item: dict, exemptions: tuple[dict, ...]) -> bool:
    item_box = tuple(item["source_box"])
    for exemption in exemptions:
        if item["source_ref"] in exemption["refs"]:
            return True
        if exemption["page"] != item["physical_page"] or exemption["box"] is None:
            continue
        if _box_equal(item_box, exemption["box"]):
            return True
    return False


def _block_is_exempt(page: int, box, exemptions: tuple[dict, ...]) -> bool:
    area = _box_area(box)
    return any(
        exemption["page"] == page
        and exemption["box"] is not None
        and _intersection_area(box, exemption["box"]) >= min(area, _box_area(exemption["box"])) * 0.5
        for exemption in exemptions
    )


def _tracking_rows(working_dir: Path) -> tuple[dict, ...]:
    path = working_dir / "translate_tracking.json"
    tracking = _read(path)
    rows = []
    for section in ("page", "cross_page", "cross_column"):
        groups = tracking.get(section)
        if not isinstance(groups, list):
            raise VerificationError(f"translation tracking section is invalid: {section}")
        for group in groups:
            paragraphs = group.get("paragraph") if isinstance(group, dict) else None
            if not isinstance(paragraphs, list):
                raise VerificationError(f"translation tracking group is invalid: {section}")
            for row in paragraphs:
                if not isinstance(row, dict):
                    raise VerificationError("translation tracking row is not an object")
                rows.append(row)
    return tuple(rows)


def verify_coverage(
    expectations_path: Path,
    source: Path,
    output: Path,
    working_dir: Path,
    source_lang: str,
    target_lang: str,
) -> dict:
    expectations = _verify_inputs(
        expectations_path,
        source,
        output,
        source_lang,
        target_lang,
    )
    report = _read(working_dir / COVERAGE_REPORT_NAME)
    items = report.get("items")
    if (
        report.get("schema_version") != COVERAGE_SCHEMA_VERSION
        or report.get("status") != "complete"
        or report.get("direction") != f"{source_lang}-{target_lang}"
        or not isinstance(items, list)
    ):
        raise VerificationError("coverage report did not complete with the requested direction")
    exemptions = _coverage_exemptions(expectations)
    dropcap_intent_path = working_dir / "drop_cap_intent.report.json"
    dropcap_intents = (
        _read(dropcap_intent_path).get("intents", [])
        if dropcap_intent_path.is_file()
        else []
    )
    if not isinstance(dropcap_intents, list):
        raise VerificationError("drop-cap intent inventory is invalid")
    companion_refs = {
        item.get("visual_initial_ref")
        for item in dropcap_intents
        if isinstance(item, dict)
        and item.get("visual_initial_ref") != item.get("source_ref")
        and isinstance(item.get("binding_proof"), dict)
        and item["binding_proof"].get("kind") == "standalone_visual_initial"
    }
    by_ref = {}
    signatures = []
    owner_counts = dict.fromkeys(sorted(COVERAGE_OWNERS), 0)
    for position, item in enumerate(items):
        if not isinstance(item, dict) or not (
            COVERAGE_FIELDS <= set(item)
            and set(item) <= COVERAGE_FIELDS | COVERAGE_OPTIONAL_FIELDS
        ):
            raise VerificationError(f"coverage item schema is invalid: {position}")
        reference = item.get("source_ref")
        page = item.get("physical_page")
        role = item.get("role")
        owner = item.get("translation_owner")
        target_hash = item.get("target_text_sha256")
        status = item.get("final_status")
        source_hash = item.get("source_text_sha256")
        source_box = _require_box(item.get("source_box"), str(reference))
        if (
            not isinstance(reference, str)
            or REF_PATTERN.fullmatch(reference) is None
            or reference in by_ref
            or not isinstance(page, int)
            or isinstance(page, bool)
            or page < 1
            or int(reference[1 : reference.index("#")]) != page
            or not isinstance(role, str)
            or not role
            or owner not in COVERAGE_OWNERS
            or not isinstance(source_hash, str)
            or SHA256_PATTERN.fullmatch(source_hash) is None
            or not isinstance(status, str)
            or not status
        ):
            raise VerificationError(f"coverage item identity is invalid: {reference}")
        runtime_ref = item.get("runtime_source_ref")
        if runtime_ref is not None and (
            not isinstance(runtime_ref, str) or REF_PATTERN.fullmatch(runtime_ref) is None
        ):
            raise VerificationError(f"coverage runtime ref is invalid: {reference}")
        if owner in {"joint", "ordinary"}:
            if not isinstance(target_hash, str) or SHA256_PATTERN.fullmatch(target_hash) is None:
                raise VerificationError(f"translated coverage item has no target: {reference}")
            expected_status = "joint_success" if owner == "joint" else "translated"
            if status != expected_status:
                raise VerificationError(
                    f"translated coverage item did not finish cleanly: {reference} ({status})"
                )
        elif target_hash is not None:
            raise VerificationError(f"untranslated coverage item has a target digest: {reference}")
        held = {**item, "source_box": source_box}
        exempt = _item_is_exempt(held, exemptions)
        if owner == "preserve" and not exempt:
            raise VerificationError(f"preserved coverage item lacks an expectation exemption: {reference}")
        if role == "chain" and owner != "joint":
            raise VerificationError(f"body chain coverage item is not joint-owned: {reference}")
        if role == DROPCAP_COMPANION_ROLE and (
            reference not in companion_refs
            or owner != "none"
            or target_hash is not None
            or status != "merged_into_drop_cap_owner"
        ):
            raise VerificationError(
                f"drop-cap companion coverage evidence is invalid: {reference}"
            )
        if role in BODY_ROLES and (owner == "none" or target_hash is None):
            raise VerificationError(f"body coverage item has no target: {reference}")
        by_ref[reference] = held
        signatures.append((page, source_hash, source_box, held))
        owner_counts[owner] += 1
    if not items:
        raise VerificationError("coverage item inventory is empty")
    covered_companions = {
        reference
        for reference, item in by_ref.items()
        if item["role"] == DROPCAP_COMPANION_ROLE
    }
    if covered_companions != companion_refs:
        raise VerificationError("drop-cap companion coverage inventory disagrees")

    totals = report.get("totals")
    if not isinstance(totals, dict) or set(totals) != {"sources", "owners"}:
        raise VerificationError("coverage totals are missing")
    if totals["sources"] != len(items):
        raise VerificationError("coverage source total disagrees")
    if totals["owners"] != owner_counts:
        raise VerificationError("coverage owner totals disagree")

    joint_refs = set()
    chain_report = _read(working_dir / "chain_translation.report.json")
    for chain in chain_report.get("chains", []):
        if not isinstance(chain, dict) or chain.get("outcome") != "joint_success":
            continue
        physical_refs = chain.get("ordered_source_refs")
        members = chain.get("members")
        if not isinstance(physical_refs, list) or not isinstance(members, list):
            raise VerificationError("joint chain coverage evidence is malformed")
        joint_refs.update(physical_refs)
    tracking_by_ref = {}
    for row in _tracking_rows(working_dir):
        reference = row.get("source_ref")
        if isinstance(reference, str) and row.get("output") not in (None, ""):
            tracking_by_ref.setdefault(reference, []).append(row)
    for reference in joint_refs:
        tracked = tracking_by_ref.get(reference, [])
        item = by_ref.get(reference)
        if item is None:
            raise VerificationError(f"joint chain member is absent from coverage: {reference}")
        if any(not isinstance(row.get("output"), str) for row in tracked) or len(
            tracked
        ) > 1 or (
            len(tracked) == 1
            and hashlib.sha256(tracked[0]["output"].encode("utf-8")).hexdigest()
            != item["target_text_sha256"]
        ):
            raise VerificationError(f"joint chain member also has ordinary ownership: {reference}")

    verified_chain_members = 0
    for truth_chain in expectations.get("chains", []):
        if truth_chain.get("role") != "body":
            continue
        for truth in truth_chain.get("ordered_members", []):
            signature = _member_signature(truth, f"coverage truth {truth_chain.get('id')}")
            matches = [
                item
                for page, source_hash, source_box, item in signatures
                if page == signature[0]
                and source_hash == signature[1]
                and _box_equal(source_box, signature[2])
            ]
            if len(matches) != 1 or matches[0]["translation_owner"] != "joint":
                raise VerificationError(
                    f"body chain member lacks unique joint coverage: {_truth_ref(truth)}"
                )
            verified_chain_members += 1
    return {
        "check": "coverage",
        "sample_id": expectations.get("sample_id"),
        "items": len(items),
        "chain_members": verified_chain_members,
        "owners": owner_counts,
        "status": "pass",
    }


def _script_count(text: str, language: str) -> int:
    pattern = HAN_PATTERN if language.lower().startswith("zh") else LATIN_PATTERN
    return len(pattern.findall(text))


def _coverage_thresholds(expectations: dict, source_lang: str) -> tuple[int, int]:
    policy = expectations.get("coverage_thresholds", {})
    if not isinstance(policy, dict):
        raise VerificationError("coverage thresholds must be an object")
    default = 30 if source_lang.lower().startswith("zh") else 80
    source_min = policy.get("source_block_min_characters", default)
    residue_max = policy.get("max_source_script_characters", default - 1)
    if (
        not isinstance(source_min, int)
        or isinstance(source_min, bool)
        or source_min < 1
        or not isinstance(residue_max, int)
        or isinstance(residue_max, bool)
        or residue_max < 0
    ):
        raise VerificationError("coverage thresholds must be non-negative integers")
    return source_min, residue_max


def _output_page_map(source_document, output_document, pages: tuple[int, ...]) -> dict[int, int]:
    if any(page > source_document.page_count for page in pages):
        raise VerificationError("selected physical page is outside the source PDF")
    if output_document.page_count == source_document.page_count:
        page_map = {page: page - 1 for page in pages}
        compared = range(1, source_document.page_count + 1)
        for page in compared:
            source_page = source_document[page - 1]
            output_page = output_document[page - 1]
            if not (
                math.isclose(source_page.rect.width, output_page.rect.width, abs_tol=0.01)
                and math.isclose(source_page.rect.height, output_page.rect.height, abs_tol=0.01)
            ):
                raise VerificationError(f"page size changed: p{page}")
        return page_map
    if output_document.page_count != len(pages):
        raise VerificationError("output page count matches neither source nor selected window")
    page_map = {page: index for index, page in enumerate(pages)}
    for page, output_index in page_map.items():
        source_page = source_document[page - 1]
        output_page = output_document[output_index]
        if not (
            math.isclose(source_page.rect.width, output_page.rect.width, abs_tol=0.01)
            and math.isclose(source_page.rect.height, output_page.rect.height, abs_tol=0.01)
        ):
            raise VerificationError(f"page size changed: p{page}")
    return page_map


def verify_long_blocks_and_pdf(
    expectations_path: Path,
    source: Path,
    output: Path,
    working_dir: Path,
    source_lang: str,
    target_lang: str,
    pages: tuple[int, ...],
) -> dict:
    expectations = _verify_inputs(
        expectations_path,
        source,
        output,
        source_lang,
        target_lang,
    )
    coverage = _read(working_dir / COVERAGE_REPORT_NAME)
    raw_items = coverage.get("items")
    if not isinstance(raw_items, list):
        raise VerificationError("coverage item inventory is missing")
    items = [
        {
            **item,
            "source_box": _require_box(item.get("source_box"), str(item.get("source_ref"))),
        }
        for item in raw_items
        if isinstance(item, dict)
    ]
    if len(items) != len(raw_items):
        raise VerificationError("coverage item inventory contains a non-object")
    exemptions = _coverage_exemptions(expectations)
    source_min, residue_max = _coverage_thresholds(expectations, source_lang)
    long_blocks = 0
    with pymupdf.open(source) as source_document, pymupdf.open(output) as output_document:
        if source_document.page_count < 1 or output_document.page_count < 1:
            raise VerificationError("source/output PDF must contain pages")
        page_map = _output_page_map(source_document, output_document, pages)
        for physical_page in pages:
            source_page = source_document[physical_page - 1]
            page_items = [
                item
                for item in items
                if item.get("physical_page") == physical_page
                and item.get("translation_owner") != "none"
            ]
            for block in source_page.get_text("blocks"):
                if len(block) < 5 or not isinstance(block[4], str):
                    continue
                text = block[4]
                if _script_count(text, source_lang) < source_min:
                    continue
                source_box = _pdf_box_to_source_box(block[:4], source_page)
                if _block_is_exempt(physical_page, source_box, exemptions):
                    continue
                block_area = _box_area(source_box)
                covered_area = min(
                    block_area,
                    sum(
                        _intersection_area(source_box, item["source_box"])
                        for item in page_items
                    ),
                )
                if block_area <= 0 or covered_area / block_area < 0.25:
                    raise VerificationError(
                        f"long source block is absent from coverage: p{physical_page} "
                        f"box={[round(value, 3) for value in source_box]}"
                    )
                long_blocks += 1

            output_page = output_document[page_map[physical_page]]
            for block in output_page.get_text("blocks"):
                if len(block) < 5 or not isinstance(block[4], str):
                    continue
                residue = _script_count(block[4], source_lang)
                if residue <= residue_max:
                    continue
                output_box = _pdf_box_to_source_box(block[:4], output_page)
                if _block_is_exempt(physical_page, output_box, exemptions):
                    continue
                raise VerificationError(
                    f"long source-script residue remains: p{physical_page} "
                    f"characters={residue} box={[round(value, 3) for value in output_box]}"
                )
    return {
        "check": "pdf_completeness",
        "sample_id": expectations.get("sample_id"),
        "physical_pages": list(pages),
        "long_source_blocks": long_blocks,
        "status": "pass",
    }


def verify_full(
    expectations_path: Path,
    source: Path,
    output: Path,
    working_dir: Path,
    source_lang: str,
    target_lang: str,
    pages: tuple[int, ...],
) -> dict:
    if not pages:
        raise VerificationError("full verification requires physical pages")
    checks = {}
    for name, verifier in (
        ("chain", verify_chain),
        ("toc", verify_toc),
        ("layout", verify_layout),
        ("title", verify_title),
        ("dropcap", verify_dropcap),
        ("coverage", verify_coverage),
    ):
        checks[name] = verifier(
            expectations_path,
            source,
            output,
            working_dir,
            source_lang,
            target_lang,
        )
    checks["pdf_completeness"] = verify_long_blocks_and_pdf(
        expectations_path,
        source,
        output,
        working_dir,
        source_lang,
        target_lang,
        pages,
    )
    expectations = _read(expectations_path)
    return {
        "check": "full",
        "sample_id": expectations.get("sample_id"),
        "checks": checks,
        "status": "pass",
    }


def _parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        required=True,
        choices=("chain", "toc", "layout", "title", "dropcap", "full"),
    )
    parser.add_argument("--expectations", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--working-dir", "--run-dir", dest="working_dir", required=True, type=Path
    )
    parser.add_argument("--source-lang")
    parser.add_argument("--target-lang", required=True)
    parser.add_argument("--pages", type=_parse_physical_pages)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        expectations = _read(args.expectations)
        direction = expectations.get("direction")
        if not isinstance(direction, str) or direction.count("-") != 1:
            raise VerificationError("expectations direction is invalid")
        inferred_source, expected_target = direction.split("-", 1)
        source_lang = args.source_lang or inferred_source
        if expected_target != args.target_lang:
            raise VerificationError(
                "target language disagrees with expectations: "
                f"expected={expected_target}, actual={args.target_lang}"
            )
        verifier = {
            "chain": verify_chain,
            "toc": verify_toc,
            "layout": verify_layout,
            "title": verify_title,
            "dropcap": verify_dropcap,
            "full": verify_full,
        }[args.check]
        positional = (
            args.expectations,
            args.source,
            args.output,
            args.working_dir,
            source_lang,
            args.target_lang,
        )
        result = (
            verifier(*positional, args.pages)
            if args.check == "full"
            else verifier(*positional)
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"check": args.check, "status": "fail", "error": str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
