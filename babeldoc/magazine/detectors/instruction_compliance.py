"""Trace-backed compliance with joint-call, protection, and rollback rules."""

from __future__ import annotations

from babeldoc.magazine.detectors import base
from babeldoc.magazine.run_trace import GENERATION_OPEN
from babeldoc.magazine.run_trace import GENERATION_ROLLED_BACK
from babeldoc.magazine.run_trace import RENDER_RENDERED
from babeldoc.magazine.run_trace import ChainResultState
from babeldoc.magazine.run_trace import SourceTerminalState

NAME = "instruction_compliance"
KIND = "instruction_compliance"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False
REQUIRES_RUN_TRACE = True
FINAL_ONLY = True


def _geometry(trace, source_refs):
    boxes = []
    for source_ref in source_refs:
        source = trace.sources.get(source_ref)
        if source is None:
            continue
        for fragment_id in source.fragment_ids:
            fragment = trace.fragments.get(fragment_id)
            if fragment is None:
                continue
            for geometry_id in fragment.geometry_ids:
                geometry = trace.geometries.get(geometry_id)
                if geometry is not None and geometry.active:
                    boxes.append(geometry.final_box or geometry.pre_repair_box)
    return base.union_box(boxes)


def _issue(context, rule, identity, source_refs=(), detail=None):
    trace = context.run_trace
    sources = [trace.sources[ref] for ref in source_refs if ref in trace.sources]
    return base.Issue(
        kind=KIND,
        page=min(
            (source.page for source in sources),
            default=context.pages[0].label if context.pages else 0,
        ),
        paragraph_refs=tuple(source_refs),
        geometry=_geometry(trace, source_refs),
        severity=context.severity_of(KIND),
        evidence={
            "instruction": rule,
            "instruction_ref": identity,
            "detail": detail,
            "violation_count": 1,
            "identity_ref": f"{rule}:{identity}",
        },
        detector=NAME,
        detected_at_iteration=context.iteration,
        article_refs=tuple(
            sorted({source.article_id for source in sources if source.article_id})
        ),
        source_refs=tuple(source_refs),
    )


def detect(context: base.DetectionContext) -> list[base.Issue]:
    trace = context.run_trace
    found = []
    for chain_id, outcome in sorted(trace.chain_outcomes.items()):
        expected_calls = (
            1 if outcome.result_state == ChainResultState.JOINT_SUCCESS else 0
        )
        if outcome.result_state in {
            ChainResultState.JOINT_SUCCESS,
            ChainResultState.PROTECTED_UNTRANSLATED,
        } and outcome.translator_call_count != expected_calls:
            found.append(
                _issue(
                    context,
                    "joint_call_count",
                    chain_id,
                    outcome.ordered_source_refs,
                    {
                        "expected": expected_calls,
                        "actual": outcome.translator_call_count,
                    },
                )
            )
        if outcome.result_state == ChainResultState.PROTECTED_UNTRANSLATED:
            states = [
                trace.sources[ref].terminal_state
                for ref in outcome.ordered_source_refs
                if ref in trace.sources
            ]
            if outcome.request_id is not None or any(
                state != SourceTerminalState.PROTECTED for state in states
            ):
                found.append(
                    _issue(
                        context,
                        "protected_state",
                        chain_id,
                        outcome.ordered_source_refs,
                        {"request_id": outcome.request_id},
                    )
                )
    for source_ref, source in sorted(trace.sources.items()):
        if source.terminal_state != SourceTerminalState.PROTECTED:
            continue
        rendered = any(
            geometry.active and geometry.render_status == RENDER_RENDERED
            for fragment_id in source.fragment_ids
            if fragment_id in trace.fragments
            for geometry_id in trace.fragments[fragment_id].geometry_ids
            if geometry_id in trace.geometries
            for geometry in (trace.geometries[geometry_id],)
        )
        if rendered:
            found.append(
                _issue(context, "protected_state", source_ref, (source_ref,))
            )
    for generation, record in sorted(trace.generations.items()):
        if record.status == GENERATION_OPEN:
            found.append(
                _issue(context, "rollback_state", f"generation-{generation}", detail={"status": record.status})
            )
            continue
        if record.status != GENERATION_ROLLED_BACK:
            continue
        active = {
            "fragments": sorted(
                item for item in record.fragment_ids if trace.fragments[item].active
            ),
            "geometry": sorted(
                item for item in record.geometry_ids if trace.geometries[item].active
            ),
            "flow_slots": sorted(
                item for item in record.flow_slot_ids if trace.flow_slots[item].active
            ),
        }
        if any(active.values()):
            found.append(
                _issue(
                    context,
                    "rollback_state",
                    f"generation-{generation}",
                    detail=active,
                )
            )
    return found
