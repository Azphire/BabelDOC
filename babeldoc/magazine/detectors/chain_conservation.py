"""Hash-and-range conservation of joint targets and their ordered fragments."""

from __future__ import annotations

from babeldoc.magazine.detectors import base
from babeldoc.magazine.run_trace import REQUEST_COMPLETED

NAME = "chain_conservation"
KIND = "chain_conservation"

REQUIRES_TRANSLATION = True
REQUIRES_SOURCE_GEOMETRY = False
REQUIRES_ARTICLE_IR = False
REQUIRES_RUN_TRACE = True
FINAL_ONLY = True


def _geometry(trace, fragment_ids):
    boxes = []
    for fragment_id in fragment_ids:
        fragment = trace.fragments.get(fragment_id)
        if fragment is None:
            continue
        for geometry_id in fragment.geometry_ids:
            record = trace.geometries.get(geometry_id)
            if record is not None and record.active:
                boxes.append(record.final_box or record.pre_repair_box)
    return base.union_box(boxes)


def detect(context: base.DetectionContext) -> list[base.Issue]:
    trace = context.run_trace
    found = []
    request_ids = {
        request_id
        for request_id, request in trace.requests.items()
        if request.request_kind == "continuity_chain"
        and request.status == REQUEST_COMPLETED
    }
    request_ids.update(
        outcome.request_id
        for outcome in trace.chain_outcomes.values()
        if outcome.request_id is not None
        and trace.requests.get(outcome.request_id) is not None
        and trace.requests[outcome.request_id].status == REQUEST_COMPLETED
    )
    for request_id in sorted(request_ids):
        evidence = trace.target_conservation_evidence(request_id)
        fragments = evidence["fragments"]
        orders = [item["order"] for item in fragments]
        duplicate_orders = len(orders) - len(set(orders))
        missing_orders = len(set(range(len(fragments))) - set(orders))
        cursor = 0
        gap_chars = 0
        overlap_chars = 0
        hash_mismatches = 0
        source_positions = {
            reference: index
            for index, reference in enumerate(evidence["ordered_source_refs"])
        }
        seen_positions = []
        for fragment in fragments:
            start = fragment["text_start"]
            end = fragment["text_end"]
            if start > cursor:
                gap_chars += start - cursor
            elif start < cursor:
                overlap_chars += cursor - start
            cursor = max(cursor, end)
            hash_mismatches += int(
                fragment["text_hash"] != fragment["stored_text_hash"]
            )
            seen_positions.append(source_positions.get(fragment["source_ref"], -1))
        whole_chars = evidence["whole_target_chars"]
        if isinstance(whole_chars, int) and cursor < whole_chars:
            gap_chars += whole_chars - cursor
        out_of_order = sum(
            int(right < left)
            for left, right in zip(
                seen_positions, seen_positions[1:], strict=False
            )
        )
        target_mismatch = (
            evidence["whole_target_hash"]
            != evidence["reconstructed_target_hash"]
            or evidence["whole_target_chars"]
            != evidence["reconstructed_target_chars"]
        )
        violation_count = (
            duplicate_orders
            + missing_orders
            + int(gap_chars > 0)
            + int(overlap_chars > 0)
            + hash_mismatches
            + out_of_order
            + int(target_mismatch)
        )
        if not violation_count:
            continue
        source_refs = tuple(evidence["ordered_source_refs"])
        fragment_refs = tuple(item["fragment_id"] for item in fragments)
        sources = [trace.sources[ref] for ref in source_refs if ref in trace.sources]
        articles = tuple(sorted({item.article_id for item in sources if item.article_id}))
        page = min((item.page for item in sources), default=0)
        found.append(
            base.Issue(
                kind=KIND,
                page=page,
                paragraph_refs=source_refs,
                geometry=_geometry(trace, fragment_refs),
                severity=context.severity_of(KIND),
                evidence={
                    **{key: value for key, value in evidence.items() if key != "fragments"},
                    "fragment_ranges": [
                        {
                            key: item[key]
                            for key in (
                                "fragment_id",
                                "source_ref",
                                "order",
                                "text_start",
                                "text_end",
                                "text_hash",
                            )
                        }
                        for item in fragments
                    ],
                    "duplicate_order_count": duplicate_orders,
                    "missing_order_count": missing_orders,
                    "gap_chars": gap_chars,
                    "overlap_chars": overlap_chars,
                    "hash_mismatch_count": hash_mismatches,
                    "out_of_order_count": out_of_order,
                    "target_hash_mismatch": target_mismatch,
                    "violation_count": violation_count,
                    "identity_ref": request_id,
                },
                detector=NAME,
                detected_at_iteration=context.iteration,
                article_refs=articles,
                source_refs=source_refs,
                fragment_refs=fragment_refs,
            )
        )
    return found
