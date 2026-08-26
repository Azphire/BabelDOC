"""Post typesetting detection: what a finished document got wrong.

This runs after typesetting and before the PDF is written, which is the one
point at which both halves of a defect are on the table -- the translation has
been written back into every paragraph, and the geometry those paragraphs will
be rendered at is final. It reads the document and writes a sidecar. It changes
nothing, in this batch or in principle: what a finding is worth acting on, and
what acting on it may touch, belongs to the repair controller beside it.

The switch is ``magazine_detect``, down by default. With it down nothing here
is reached and no sidecar is written.

Which detectors answer for a page comes from the repair profile that page's
kind declares in ``configs/page_types.json`` and is resolved through
``configs/detectors.json``. No page type is named in this package, and neither
is a profile: both are strings read from configuration and used as keys.

A detector that needs a translated document says so, and is skipped with its
reason recorded on a run that translated nothing, rather than reporting every
paragraph of an untranslated document as untranslated. A detector that needs the
layout as the source drew it says so the same way, and is skipped on a run that
kept no checkpoint to read it from: its finding is a claim about what the
translation changed, and without the before there is no such claim to make.

Two passes that do change the document are called from here, before any of this
runs: the heading policy in ``magazine/title_typeset.py`` and the column reflow
in ``magazine/column_reflow.py``. Both belong in the same window -- after the
geometry is final, before anything reads it -- and this call is the only
extension owned code the pipeline runs in that window, so reaching the window
through it is what keeps the pipeline itself unchanged. Each carries its own
switch and answers for its own sidecar; with those switches down they return
having read nothing, and detection then sees exactly the document it saw before.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from babeldoc.magazine import fixed_assets
from babeldoc.magazine.detectors import abnormal_blank
from babeldoc.magazine.detectors import article_ownership
from babeldoc.magazine.detectors import chain_conservation
from babeldoc.magazine.detectors import collision
from babeldoc.magazine.detectors import escalation
from babeldoc.magazine.detectors import fixed_asset_drift
from babeldoc.magazine.detectors import fragment
from babeldoc.magazine.detectors import instruction_compliance
from babeldoc.magazine.detectors import overlap
from babeldoc.magazine.detectors import page_bounds
from babeldoc.magazine.detectors import render_coverage
from babeldoc.magazine.detectors import residue
from babeldoc.magazine.detectors import source_geometry as source_geometry_module
from babeldoc.magazine.detectors.base import CONFIG_PATH
from babeldoc.magazine.detectors.base import REPAIR_PROFILE_POLICY_FLAG
from babeldoc.magazine.detectors.base import DetectionContext
from babeldoc.magazine.detectors.base import DetectorConfig
from babeldoc.magazine.detectors.base import DetectorError
from babeldoc.magazine.detectors.base import Issue
from babeldoc.magazine.detectors.base import PageView
from babeldoc.magazine.detectors.base import load_detector_config
from babeldoc.magazine.hitl import labeled_pages
from babeldoc.magazine.runtime_profile import record_runtime_blocked_reason
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

__all__ = [
    "CONFIG_PATH",
    "DETECTORS",
    "REPORT_NAME",
    "SWITCH",
    "DetectionContext",
    "DetectorConfig",
    "DetectorError",
    "Issue",
    "PageView",
    "build_context",
    "detect_issues",
    "detector_config",
    "detector_kinds",
    "run_detectors",
    "source_geometry_of",
]

REPORT_NAME = "issues.json"
PREREQUISITE_KIND = "detector_prerequisite_missing"

# The switch, by the name the caller sets on the translation config.
SWITCH = "magazine_detect"

# Every detector, by the name the configuration steers it with. A module is a
# detector by carrying NAME, KIND, REQUIRES_TRANSLATION,
# REQUIRES_SOURCE_GEOMETRY and detect().
DETECTORS = {
    module.NAME: module
    for module in (
        residue,
        fragment,
        overlap,
        page_bounds,
        collision,
        escalation,
        article_ownership,
        chain_conservation,
        render_coverage,
        abnormal_blank,
        fixed_asset_drift,
        instruction_compliance,
    )
}


def detector_kinds() -> tuple[str, ...]:
    return tuple(
        sorted({PREREQUISITE_KIND, *(module.KIND for module in DETECTORS.values())})
    )


def detector_config() -> DetectorConfig:
    """The bounds, validated against the detectors that exist."""
    return load_detector_config(
        None,
        tuple(sorted(DETECTORS)),
        detector_kinds(),
    )


def build_context(
    docs,
    config: DetectorConfig,
    language: str | None,
    working_dir: Path | None,
    translation_performed: bool = True,
    iteration: int = 0,
    source_geometry: object | None = None,
    article_document_ir=None,
    run_trace=None,
    fixed_inventory=None,
    current_inventory=None,
    finalized: bool = False,
) -> DetectionContext:
    """One document as the detectors read it, each page carrying its policy.

    The source layout is loaded from the working directory where none is
    supplied. A caller that detects the same document several times supplies it
    instead, so the checkpoint behind it is read once rather than once per pass.
    """
    taxonomy = load_taxonomy()
    pages = [
        PageView(label=label, page=page, policy=taxonomy.policy_of(page.page_kind))
        for label, page in labeled_pages(docs)
    ]
    result = None
    if source_geometry is None and working_dir is not None:
        source_geometry = source_geometry_of(working_dir, config)
    if isinstance(source_geometry, source_geometry_module.SourceGeometryResult):
        result = source_geometry
        source_geometry = result.geometry
    return DetectionContext(
        pages=pages,
        config=config,
        language=language,
        iteration=iteration,
        translation_performed=translation_performed,
        working_dir=working_dir,
        source_geometry=source_geometry,
        source_geometry_result=result,
        article_document_ir=article_document_ir,
        run_trace=run_trace,
        fixed_inventory=fixed_inventory,
        current_inventory=current_inventory,
        finalized=finalized,
    )


def source_geometry_of(working_dir, config: DetectorConfig, run_trace=None):
    """The layout as the source drew it, from the stage the bounds declare."""
    return source_geometry_module.load(
        working_dir, config.source_geometry_stage, run_trace=run_trace
    )


def _selected(context: DetectionContext) -> dict[str, list[PageView]]:
    """Which pages each page level detector answers for."""
    selection: dict[str, list[PageView]] = {}
    for view in context.pages:
        profile = view.flag(REPAIR_PROFILE_POLICY_FLAG)
        for name in context.config.detectors_for_profile(profile):
            selection.setdefault(name, []).append(view)
    return selection


def run_detectors(context: DetectionContext) -> list[Issue]:
    """Every issue of one document, in detector then page then paragraph order.

    A page level detector sees only the pages whose profile selected it; a
    document level one sees the whole document, because what it reads is a
    sidecar about the document rather than anything on a page.
    """
    selection = _selected(context)
    found: list[Issue] = []
    for name in sorted(DETECTORS):
        module = DETECTORS[name]
        if getattr(module, "FINAL_ONLY", False) and not context.finalized:
            continue
        document_level = name in context.config.document_detectors
        pages = context.pages if document_level else selection.get(name, [])
        if not pages:
            continue
        if module.REQUIRES_TRANSLATION and not context.translation_performed:
            context.notes.append(
                f"{name}: this run performed no translation, so the document "
                f"carries no translated text to answer for; not run"
            )
            continue
        missing = []
        if module.REQUIRES_SOURCE_GEOMETRY and context.source_geometry is None:
            missing.append("source_geometry")
        for attribute, label in (
            ("REQUIRES_ARTICLE_IR", "article_ir"),
            ("REQUIRES_RUN_TRACE", "run_trace"),
            ("REQUIRES_FIXED_INVENTORY", "fixed_asset_inventory"),
            ("REQUIRES_CURRENT_INVENTORY", "current_fixed_asset_inventory"),
        ):
            if not getattr(module, attribute, False):
                continue
            context_name = {
                "REQUIRES_ARTICLE_IR": "article_document_ir",
                "REQUIRES_RUN_TRACE": "run_trace",
                "REQUIRES_FIXED_INVENTORY": "fixed_inventory",
                "REQUIRES_CURRENT_INVENTORY": "current_inventory",
            }[attribute]
            if getattr(context, context_name) is None:
                missing.append(label)
        if missing:
            page = context.pages[0].label if context.pages else 0
            found.extend(
                Issue(
                    kind=PREREQUISITE_KIND,
                    page=page,
                    paragraph_refs=(),
                    geometry=None,
                    severity=context.severity_of(PREREQUISITE_KIND),
                    evidence={
                        "prerequisite": prerequisite,
                        "required_by": name,
                        "detector_kind": module.KIND,
                        "violation_count": 1,
                    },
                    detector=name,
                    detected_at_iteration=context.iteration,
                ).with_severity_fields(
                    context.config.progress_fields(PREREQUISITE_KIND)
                )
                for prerequisite in missing
            )
            continue
        scoped = DetectionContext(
            pages=pages,
            config=context.config,
            language=context.language,
            iteration=context.iteration,
            translation_performed=context.translation_performed,
            working_dir=context.working_dir,
            source_geometry=context.source_geometry,
            source_geometry_result=context.source_geometry_result,
            article_document_ir=context.article_document_ir,
            run_trace=context.run_trace,
            fixed_inventory=context.fixed_inventory,
            current_inventory=context.current_inventory,
            finalized=context.finalized,
            notes=context.notes,
            records=context.records,
        )
        for issue in module.detect(scoped):
            source_refs = tuple(
                reference
                for reference in issue.paragraph_refs
                if context.run_trace is not None
                and reference in context.run_trace.sources
            )
            source_refs = issue.source_refs or source_refs
            articles = set(issue.article_refs)
            fragments = set(issue.fragment_refs)
            if context.run_trace is not None:
                for reference in source_refs:
                    source = context.run_trace.sources[reference]
                    if source.article_id:
                        articles.add(source.article_id)
                    fragments.update(
                        fragment_id
                        for fragment_id in source.fragment_ids
                        if fragment_id in context.run_trace.fragments
                        and context.run_trace.fragments[fragment_id].active
                    )
            found.append(
                issue.with_severity_fields(
                    context.config.progress_fields(issue.kind)
                ).with_contract(
                    suggested_action_type=context.config.suggested_action(issue.kind),
                    article_refs=articles,
                    source_refs=source_refs,
                    fragment_refs=fragments,
                )
            )
    contracted = [
        issue
        if issue.suggested_action_type is not None
        else issue.with_contract(
            suggested_action_type=context.config.suggested_action(issue.kind)
        )
        for issue in found
    ]
    return sorted(contracted, key=Issue.sort_key)


def as_record(context: DetectionContext, issues: list[Issue]) -> dict:
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.kind] = counts.get(issue.kind, 0) + 1
    selection = _selected(context)
    return {
        "language": context.language,
        "iteration": context.iteration,
        "translation_performed": context.translation_performed,
        "counts": {"issues": len(issues), "by_kind": counts},
        "pages_by_detector": {
            name: sorted(view.label for view in views)
            for name, views in sorted(selection.items())
        },
        "document_detectors": list(context.config.document_detectors),
        "source_geometry": (
            context.source_geometry_result.to_record()
            if context.source_geometry_result is not None
            else None
            if context.source_geometry is None
            else {
                "status": source_geometry_module.AVAILABLE,
                "stage": context.source_geometry.stage,
                "checkpoint": context.source_geometry.path,
                "paragraphs": len(context.source_geometry.boxes),
                "reason": None,
            }
        ),
        "prerequisite_issues": (
            []
            if context.source_geometry_result is None
            or context.source_geometry_result.issue() is None
            else [context.source_geometry_result.issue()]
        ),
        "notes": list(context.notes),
        "detector_records": {
            name: list(rows) for name, rows in sorted(context.records.items())
        },
        "issues": [issue.as_record() for issue in issues],
    }


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def _write_fixed_asset_report(
    working_dir,
    source_result,
    prerequisite_issue,
    before,
    after,
    tolerance: float,
) -> None:
    fixed_assets.write_report(
        working_dir,
        {
            "source_geometry": source_result.to_record(),
            "prerequisite_issues": (
                [] if prerequisite_issue is None else [prerequisite_issue]
            ),
            "inventory": before.to_record(),
            "final_comparison": fixed_assets.compare(
                before, after, tolerance
            ).to_record(),
        },
    )


def detect_issues(
    translation_config,
    docs,
    run_trace=None,
    article_document_ir=None,
) -> list[Issue]:
    """Find every issue of one finished document and write the sidecar.

    Returns them in report order, empty where the switch is down, in which case
    nothing is written either.

    Where the repair switch is up as well, the loop beside this package owns the
    pass instead: it detects, acts and detects again, and the sidecar it leaves
    describes the document the PDF is written from rather than the one detection
    first saw. The import is local because that package reads this one.

    The heading policy runs first, and before the switch is consulted, so that
    what is detected is the document as it will be written. The column reflow
    runs after it and on the same terms, because what it measures is the gap
    between one paragraph and the next and the heading policy is the last pass
    that moves either of them. Both imports are local for the same reason the
    controller's is.
    """
    from babeldoc.magazine import column_reflow
    from babeldoc.magazine import title_typeset

    title_typeset.apply(translation_config, docs)
    config = detector_config()
    reflow_config = column_reflow.load_reflow_config()
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    source_result = source_geometry_of(working_dir, config, run_trace=run_trace)
    prerequisite_issue = source_result.issue()
    if prerequisite_issue is not None:
        record_runtime_blocked_reason(translation_config, prerequisite_issue)
        if run_trace is not None:
            run_trace.record_blocked_reason(prerequisite_issue)
    inventory_before = fixed_assets.build_inventory(
        docs,
        run_trace=run_trace,
        protected_paragraph_labels=reflow_config.protected_paragraph_labels,
    )
    if run_trace is None:
        column_reflow.apply(
            translation_config,
            docs,
            source_geometry=source_result,
            fixed_inventory=inventory_before,
        )
    else:
        column_reflow.apply(
            translation_config,
            docs,
            source_geometry=source_result,
            fixed_inventory=inventory_before,
            run_trace=run_trace,
        )
    if not enabled(translation_config):
        return []
    from babeldoc.magazine.react import controller

    if controller.enabled(translation_config):
        if run_trace is None:
            controller.repair_document(
                translation_config,
                docs,
                source_geometry=source_result,
                fixed_inventory=inventory_before,
            )
        else:
            controller.repair_document(
                translation_config,
                docs,
                run_trace=run_trace,
                source_geometry=source_result,
                fixed_inventory=inventory_before,
            )
    if run_trace is not None:
        run_trace.capture_final_document(docs)
        run_trace.finalize_sources()
    inventory_after = fixed_assets.build_inventory(
        docs,
        run_trace=run_trace,
        protected_paragraph_labels=reflow_config.protected_paragraph_labels,
    )
    context = build_context(
        docs,
        config,
        getattr(translation_config, "lang_out", None),
        working_dir,
        translation_performed=not getattr(
            translation_config, "skip_translation", False
        ),
        source_geometry=source_result,
        article_document_ir=article_document_ir,
        run_trace=run_trace,
        fixed_inventory=inventory_before,
        current_inventory=inventory_after,
        finalized=True,
    )
    issues = run_detectors(context)
    write_report(working_dir, as_record(context, issues))
    _write_fixed_asset_report(
        working_dir,
        source_result,
        prerequisite_issue,
        inventory_before,
        inventory_after,
        reflow_config.asset_bbox_tolerance_pt,
    )
    logger.debug(
        "detection: %d issue(s) over %d page(s)", len(issues), len(context.pages)
    )
    return issues
