"""Terminal-state and final-geometry coverage for every traced source."""

from __future__ import annotations

from babeldoc.magazine.detectors import base
from babeldoc.magazine.run_trace import RENDER_RENDERED
from babeldoc.magazine.run_trace import SourceTerminalState

NAME = "render_coverage"
KIND = "render_coverage"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False
REQUIRES_ARTICLE_IR = False
REQUIRES_RUN_TRACE = True
FINAL_ONLY = True


def _finding(context, source, reason, fragment=None, geometry=None):
    box = None if geometry is None else geometry.final_box or geometry.pre_repair_box
    return base.Issue(
        kind=KIND,
        page=(
            source.page
            if geometry is None or geometry.final_page is None
            else geometry.final_page
        ),
        paragraph_refs=(source.source_ref,),
        geometry=None if box is None else base.union_box([box]),
        severity=context.severity_of(KIND),
        evidence={
            "reason": reason,
            "source_terminal_state": None
            if source.terminal_state is None
            else source.terminal_state.value,
            "fragment_terminal_state": None
            if fragment is None or fragment.terminal_state is None
            else fragment.terminal_state.value,
            "render_status": None if geometry is None else geometry.render_status,
            "violation_count": 1,
            "identity_ref": (
                f"source:{reason}"
                if fragment is None
                else f"fragment:{fragment.fragment_id}:{reason}"
            ),
        },
        detector=NAME,
        detected_at_iteration=context.iteration,
        article_refs=()
        if source.article_id is None
        else (source.article_id,),
        source_refs=(source.source_ref,),
        fragment_refs=()
        if fragment is None
        else (fragment.fragment_id,),
    )


def detect(context: base.DetectionContext) -> list[base.Issue]:
    trace = context.run_trace
    found = []
    legal = set(SourceTerminalState)
    for _source_ref, source in sorted(trace.sources.items()):
        if source.terminal_state not in legal:
            found.append(_finding(context, source, "source_terminal_state_missing"))
    for _fragment_id, fragment in sorted(trace.fragments.items()):
        if not fragment.active:
            continue
        source = trace.sources.get(fragment.source_ref)
        if source is None:
            continue
        if fragment.terminal_state not in legal:
            found.append(
                _finding(context, source, "fragment_terminal_state_missing", fragment)
            )
            continue
        if fragment.terminal_state != SourceTerminalState.RENDERED:
            continue
        active = [
            trace.geometries[geometry_id]
            for geometry_id in fragment.geometry_ids
            if geometry_id in trace.geometries
            and trace.geometries[geometry_id].active
        ]
        if len(active) != 1:
            found.append(
                _finding(context, source, "active_geometry_count_invalid", fragment)
            )
            continue
        geometry = active[0]
        if (
            geometry.render_status != RENDER_RENDERED
            or geometry.final_page is None
            or geometry.final_box is None
            or geometry.binding_id is None
        ):
            found.append(
                _finding(context, source, "final_geometry_missing", fragment, geometry)
            )
    return found
