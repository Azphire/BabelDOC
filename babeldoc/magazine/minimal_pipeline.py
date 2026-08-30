"""Fixed orchestration for the minimal magazine structure pipeline."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from babeldoc.magazine import article_flow
from babeldoc.magazine import demo_coverage
from babeldoc.magazine import drop_cap_render
from babeldoc.magazine import fragment_stitch
from babeldoc.magazine import furniture
from babeldoc.magazine import hitl
from babeldoc.magazine import indent_policy
from babeldoc.magazine import layout_report
from babeldoc.magazine import line_split
from babeldoc.magazine import minimal_detection
from babeldoc.magazine import llm_decide
from babeldoc.magazine import minimal_repair
from babeldoc.magazine import repair_evidence
from babeldoc.magazine import repair_loop as repair_loop_module
from babeldoc.magazine import paren_dedup
from babeldoc.magazine import resource_paths
from babeldoc.magazine import span_merge
from babeldoc.magazine import tail_fill
from babeldoc.magazine import title_typeset
from babeldoc.magazine.article_builder import ArticleBuilder
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.chain_builder import ChainBuilder
from babeldoc.magazine.element_classifier import ElementClassifier
from babeldoc.magazine.page_classifier import PageClassifier


class MinimalPipelineStateError(RuntimeError):
    """Raised when the fixed pipeline state is missing or reused."""


RUN_REPORT_NAME = "minimal_run.report.json"
RUN_SCHEMA_VERSION = "minimal-run.v1"


@contextmanager
def _without_debug_overlay_text(docs):
    """Keep diagnostic-only paragraphs outside the product quality gate.

    Debug rendering appends Unicode-only paragraphs far outside the source page
    so the backend can draw its labels.  They retain real paragraph slots (and
    therefore must not be removed or renumbered), but they are not source or
    translated content.  The detector and its fixed-asset baseline must see the
    same text-free projection; the original objects are restored for the final
    debug PDF without copying the surrounding page graph.
    """
    hidden = []
    for page in docs.page or ():
        for paragraph in page.pdf_paragraph or ():
            if not line_split.is_debug_overlay(paragraph):
                continue
            hidden.append(
                (
                    paragraph,
                    paragraph.pdf_paragraph_composition,
                    paragraph.unicode,
                )
            )
            paragraph.pdf_paragraph_composition = []
            paragraph.unicode = None
    try:
        yield
    finally:
        for paragraph, compositions, unicode_text in hidden:
            paragraph.pdf_paragraph_composition = compositions
            paragraph.unicode = unicode_text


@dataclass(slots=True)
class MagazineState:
    """The one in-memory state object owned by a translation run."""

    _article_document_ir: ArticleDocumentIR | None = None
    _coverage_snapshot: demo_coverage.CoverageSnapshot | None = None
    _coverage_report: dict | None = None
    _structure_started: bool = False
    _structure_document_identity: int | None = None
    _hitl_state: hitl.HitlRunState | None = None
    _translation_prep_started: bool = False
    _translation_prep_completed: bool = False
    _flow_started: bool = False
    _flow_completed: bool = False
    _flow_document_identity: int | None = None
    _flow_report: dict | None = None
    _typesetter_identity: int | None = None
    _render_started: bool = False
    _render_completed: bool = False
    _render_document_identity: int | None = None
    _render_report: dict | None = None
    _detection_baseline: minimal_detection.DetectionBaseline | None = None
    _fixed_baseline_refresh_started: bool = False
    _fixed_baseline_refresh_completed: bool = False
    _fixed_baseline_refresh_document_identity: int | None = None
    _detection_started: bool = False
    _detection_completed: bool = False
    _detection_document_identity: int | None = None
    _detection_before: minimal_detection.DetectionResult | None = None
    _repair_result: minimal_repair.RepairResult | None = None
    _loop_result: object | None = None
    _evidence_pages: tuple[int, ...] = ()
    _evidence_before_pdf: object | None = None
    _minimal_report: dict | None = None
    _minimal_report_path: Path | None = None
    _result_started: bool = False
    _result_completed: bool = False
    _result_identity: int | None = None

    @property
    def article_document_ir(self) -> ArticleDocumentIR | None:
        return self._article_document_ir

    @property
    def coverage_report(self) -> dict | None:
        return self._coverage_report

    @property
    def structure_started(self) -> bool:
        return self._structure_started

    @property
    def structure_document_identity(self) -> int | None:
        return self._structure_document_identity

    @property
    def hitl_state(self) -> hitl.HitlRunState | None:
        return self._hitl_state

    @property
    def hitl_report(self) -> dict | None:
        return None if self._hitl_state is None else self._hitl_state.report

    @property
    def glossary_freeze(self) -> hitl.GlossaryFreezeEvidence | None:
        return None if self._hitl_state is None else self._hitl_state.glossary_freeze

    @property
    def translation_prep_started(self) -> bool:
        return self._translation_prep_started

    @property
    def translation_prep_completed(self) -> bool:
        return self._translation_prep_completed

    @property
    def flow_started(self) -> bool:
        return self._flow_started

    @property
    def flow_completed(self) -> bool:
        return self._flow_completed

    @property
    def flow_document_identity(self) -> int | None:
        return self._flow_document_identity

    @property
    def flow_report(self) -> dict | None:
        return self._flow_report

    @property
    def typesetter_identity(self) -> int | None:
        return self._typesetter_identity

    @property
    def render_started(self) -> bool:
        return self._render_started

    @property
    def render_completed(self) -> bool:
        return self._render_completed

    @property
    def render_document_identity(self) -> int | None:
        return self._render_document_identity

    @property
    def render_report(self) -> dict | None:
        return self._render_report

    @property
    def detection_baseline(self) -> minimal_detection.DetectionBaseline | None:
        return self._detection_baseline

    @property
    def fixed_baseline_refresh_started(self) -> bool:
        return self._fixed_baseline_refresh_started

    @property
    def fixed_baseline_refresh_completed(self) -> bool:
        return self._fixed_baseline_refresh_completed

    @property
    def fixed_baseline_refresh_document_identity(self) -> int | None:
        return self._fixed_baseline_refresh_document_identity

    @property
    def detection_started(self) -> bool:
        return self._detection_started

    @property
    def detection_completed(self) -> bool:
        return self._detection_completed

    @property
    def detection_document_identity(self) -> int | None:
        return self._detection_document_identity

    @property
    def detection_before(self) -> minimal_detection.DetectionResult | None:
        return self._detection_before

    @property
    def repair_result(self) -> minimal_repair.RepairResult | None:
        return self._repair_result

    @property
    def loop_result(self):
        return self._loop_result

    @property
    def evidence_pages(self) -> tuple[int, ...]:
        return self._evidence_pages

    @property
    def evidence_before_pdf(self):
        return self._evidence_before_pdf

    @property
    def minimal_report(self) -> dict | None:
        return self._minimal_report

    @property
    def minimal_report_path(self) -> Path | None:
        return self._minimal_report_path

    @property
    def result_started(self) -> bool:
        return self._result_started

    @property
    def result_completed(self) -> bool:
        return self._result_completed

    @property
    def result_identity(self) -> int | None:
        return self._result_identity


_FIXED_TRUE_ATTRIBUTES = (
    "magazine_page_classify",
    "magazine_chain_detect",
    "magazine_chain_translate",
    "magazine_article_group",
    "magazine_article_context",
    "magazine_hitl_apply",
    "magazine_hitl_export",
    "magazine_detect",
    "magazine_drop_cap_apply",
    "magazine_drop_cap_mark",
    "magazine_drop_cap_render",
    "magazine_echo_retry",
    "magazine_formula_reclass",
    "magazine_fragment_stitch",
    "magazine_furniture",
    "magazine_indent_policy",
    "magazine_line_structure",
    "magazine_paren_dedup",
    "magazine_repair",
    "magazine_short_unit",
    "magazine_span_merge",
    "magazine_tail_fill",
    "magazine_title_typeset",
)

_FIXED_FALSE_ATTRIBUTES = (
    "magazine_checkpoint",
    "magazine_column_reflow",
    "magazine_name_harvest",
    "magazine_pdf_compliance",
    "magazine_rotated_lane",
    "magazine_profile",
    "magazine_mode",
    "magazine_runtime_profile",
    # The declared-page (record page) half of the fragment stitch rides its
    # own attribute; the fixed path decides it off so the source audit never
    # gates a stitch on the pages line_split owns.
    "magazine_stitch_declared",
)

_MISSING = object()


def declared_switches() -> dict[str, str]:
    """Every run attribute the shipped configuration says a pass is read from.

    A pass names its own switch in its own configuration and reads the run
    attribute of that name, defaulting to off when the attribute is absent.
    The fixed path decides that attribute for every pass it runs.  So a switch
    the fixed path never names is a pass whose configuration advertises a way
    to turn it on and whose runs will always find it off -- the shape a
    finished module takes when nobody wired it up, and a shape that is
    invisible until someone reads a report and wonders why a pass left no
    trace.
    """
    found: dict[str, str] = {}
    for path in sorted(resource_paths.resource_dir("configs").glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise MinimalPipelineStateError(
                f"unreadable magazine configuration {path.name}"
            ) from error
        if not isinstance(raw, dict):
            continue
        switch = raw.get("switch")
        if isinstance(switch, str) and switch:
            found[switch] = path.name
    return found


def _assert_every_switch_is_decided() -> None:
    """Fail the run at startup rather than leave a pass silently unreachable."""
    decided = set(_FIXED_TRUE_ATTRIBUTES) | set(_FIXED_FALSE_ATTRIBUTES)
    dangling = {
        name: source
        for name, source in declared_switches().items()
        if name not in decided
    }
    if dangling:
        listed = ", ".join(
            f"{name} ({source})" for name, source in sorted(dangling.items())
        )
        raise MinimalPipelineStateError(
            f"the fixed path decides no value for declared switch: {listed}"
        )


def configure(config) -> None:
    """Configure one run for the fixed path and create its unique state."""
    if getattr(config, "magazine_state", _MISSING) is not _MISSING:
        raise MinimalPipelineStateError("magazine pipeline state is already configured")
    _assert_every_switch_is_decided()

    fixed = {
        **dict.fromkeys(_FIXED_TRUE_ATTRIBUTES, True),
        **dict.fromkeys(_FIXED_FALSE_ATTRIBUTES, False),
    }
    for name, expected in fixed.items():
        current = getattr(config, name, _MISSING)
        if current is not _MISSING and current is not expected:
            raise MinimalPipelineStateError(
                f"conflicting fixed pipeline attribute {name}"
            )

    for name, value in fixed.items():
        setattr(config, name, value)
    config.magazine_state = MagazineState()


def _state(config) -> MagazineState:
    state = getattr(config, "magazine_state", None)
    if not isinstance(state, MagazineState):
        raise MinimalPipelineStateError("magazine pipeline is not configured")
    return state


def _normalize_selected_document_total_pages(config, docs) -> None:
    """Restore the source PDF page count for an explicitly selected IL."""
    page_ranges = getattr(config, "page_ranges", None)
    if page_ranges is None:
        return
    if not isinstance(page_ranges, list) or not page_ranges:
        raise MinimalPipelineStateError(
            "explicit page ranges must be a non-empty list"
        )
    normalized_ranges = []
    for position, item in enumerate(page_ranges):
        if (
            not isinstance(item, tuple | list)
            or len(item) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) for value in item)
        ):
            raise MinimalPipelineStateError(
                f"explicit page range {position} is malformed"
            )
        start, end = item
        if start < 1 or (end != -1 and end < start):
            raise MinimalPipelineStateError(
                f"explicit page range {position} is invalid"
            )
        normalized_ranges.append((start, end))

    input_file = getattr(config, "input_file", None)
    if not isinstance(input_file, str | Path) or not str(input_file):
        raise MinimalPipelineStateError(
            "explicit page selection requires a source PDF path"
        )
    source_pdf = Path(input_file)
    if not source_pdf.is_file():
        raise MinimalPipelineStateError(
            f"selected source PDF is missing: {source_pdf}"
        )
    with pymupdf.open(source_pdf) as source_document:
        source_total_pages = int(source_document.page_count)
    if source_total_pages <= 0:
        raise MinimalPipelineStateError("selected source PDF has no pages")

    labels = []
    for position, page in enumerate(docs.page or ()):
        page_number = getattr(page, "page_number", None)
        if (
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or not 0 <= page_number < source_total_pages
        ):
            raise MinimalPipelineStateError(
                f"selected page {position} has an invalid physical page number"
            )
        label = page_number + 1
        if not any(
            start <= label and (end == -1 or label <= end)
            for start, end in normalized_ranges
        ):
            raise MinimalPipelineStateError(
                f"selected physical page {label} is outside explicit page ranges"
            )
        labels.append(label)
    if len(labels) != len(set(labels)):
        raise MinimalPipelineStateError(
            "explicitly selected pages have duplicate physical labels"
        )
    docs.total_pages = source_total_pages


def after_styles(config, docs) -> ArticleDocumentIR:
    """Build page, chain, and canonical article structure exactly once."""
    state = _state(config)
    if state._structure_started or state._article_document_ir is not None:
        raise MinimalPipelineStateError(
            "canonical ArticleDocumentIR construction was already attempted"
        )

    state._structure_started = True
    state._structure_document_identity = id(docs)

    _normalize_selected_document_total_pages(config, docs)
    classifier = PageClassifier(config)
    classifier.process(docs)
    hitl_state = hitl.begin_run(config, docs)
    state._hitl_state = hitl_state
    hitl.page_kind_pass(config, docs, hitl_state)
    ElementClassifier(config).process(docs)
    # Before the fragment stitch, so a stitch can refuse to reach into a
    # withheld production mark; before translation, which consults the marks.
    config.magazine_furniture_plan = furniture.plan(config, docs)
    # After the classifiers, so page policy and operational labels are settled;
    # before line_split and the chain builder, so a stitched paragraph is what
    # gets split into records or linked into a chain, never the fragments.
    fragment_stitch.apply(config, hitl.labeled_pages(docs))
    line_split.apply(config, hitl.labeled_pages(docs))
    # After the stitch and the split, so a rejoined word lives in the
    # paragraph shape the rest of the run will see; before the chain builder,
    # so a chain never links a paragraph this pass is about to reshape.
    span_merge.apply(config, docs)
    ChainBuilder(config).process(docs)

    article_document_ir = ArticleBuilder(config).process(docs)
    if not isinstance(article_document_ir, ArticleDocumentIR):
        raise MinimalPipelineStateError(
            "ArticleBuilder did not return an ArticleDocumentIR"
    )
    state._article_document_ir = article_document_ir
    state._coverage_snapshot = demo_coverage.freeze(
        docs,
        article_document_ir,
        hitl.labeled_pages(docs),
    )
    # The translator only receives the frozen identity resolver.  It does not
    # read expectations and the resolver cannot affect translation decisions.
    config.magazine_coverage_snapshot = state._coverage_snapshot
    if docs.page:
        with _without_debug_overlay_text(docs):
            state._detection_baseline = minimal_detection.capture_baseline(
                docs,
                article_document_ir,
                labeled_pages=hitl.labeled_pages(docs),
            )
    return article_document_ir


def before_translation(config, docs) -> dict:
    """Freeze HITL terms and drop-cap intent exactly once before translation."""
    state = _state(config)
    if state._translation_prep_started:
        raise MinimalPipelineStateError("translation preparation was already attempted")
    state._translation_prep_started = True
    article_document_ir = get_article_document_ir(config)
    if state.structure_document_identity != id(docs):
        raise MinimalPipelineStateError(
            "canonical ArticleDocumentIR belongs to a different document"
        )
    hitl_state = state.hitl_state
    if hitl_state is None:
        raise MinimalPipelineStateError("HITL state is not available")

    report = hitl.before_translation(
        config,
        docs,
        article_document_ir,
        hitl_state,
    )
    if state.article_document_ir is not article_document_ir:
        raise MinimalPipelineStateError("canonical ArticleDocumentIR identity changed")
    state._translation_prep_completed = True
    return report


def get_article_document_ir(config) -> ArticleDocumentIR:
    """Return the exact canonical object stored for this run."""
    article_document_ir = _state(config).article_document_ir
    if article_document_ir is None:
        raise MinimalPipelineStateError("canonical ArticleDocumentIR is not available")
    return article_document_ir


def after_translation(config, docs, typesetter) -> dict:
    """Run the fixed target-normalization and article-flow path exactly once."""
    state = _state(config)
    article_document_ir = get_article_document_ir(config)
    if state.structure_document_identity != id(docs):
        raise MinimalPipelineStateError(
            "canonical ArticleDocumentIR belongs to a different document"
        )
    if state._flow_started:
        raise MinimalPipelineStateError("article flow was already attempted")
    if getattr(typesetter, "translation_config", None) is not config:
        raise MinimalPipelineStateError(
            "article flow typesetter belongs to a different translation config"
        )

    state._flow_started = True
    state._flow_document_identity = id(docs)
    state._typesetter_identity = id(typesetter)
    if state._coverage_snapshot is not None:
        state._coverage_report = demo_coverage.finalize(
            config,
            state._coverage_snapshot,
        )
    # Before paren_dedup and typesetting: a member's reused text is what the
    # later passes should read and what the page should be set from.
    furniture.unify(config, docs, getattr(config, "magazine_furniture_plan", None))
    paren_dedup.apply(config, docs)
    indent_policy.apply(config, docs, article_document_ir)
    report = article_flow.apply(
        config,
        docs,
        article_document_ir,
        typesetter=typesetter,
    )
    if not isinstance(report, dict):
        raise MinimalPipelineStateError("fixed article flow did not return a report")
    if "article_flow_applied" in report:
        layout_report.prepare(
            config,
            docs,
            article_document_ir,
            article_flow_report=report,
            eligible_roles=article_flow.load_flow_config().eligible_roles,
        )
    else:
        # An opaque orchestration marker carries no geometry contract.  The
        # built-in flow pass always declares the required decision explicitly.
        layout_report.discard()
    title_typeset.prepare(config, docs, article_document_ir, typesetter)
    if state.article_document_ir is not article_document_ir:
        raise MinimalPipelineStateError("canonical ArticleDocumentIR identity changed")
    state._flow_report = report
    state._flow_completed = True
    return report


def _mapping(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise MinimalPipelineStateError(f"{where} must be an object")
    return value


def _sequence(value, where: str) -> list:
    if not isinstance(value, list):
        raise MinimalPipelineStateError(f"{where} must be a list")
    return value


def _count(value, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MinimalPipelineStateError(f"{where} must be a non-negative integer")
    return value


def _read_json(path: Path, where: str) -> dict:
    if not path.is_file():
        raise MinimalPipelineStateError(f"{where} is missing: {path}")
    return _mapping(json.loads(path.read_text(encoding="utf-8")), where)


def _working_path(config, name: str) -> Path:
    path = Path(config.get_working_file_path(name))
    working_dir = Path(config.working_dir)
    if path.resolve().parent != working_dir.resolve():
        raise MinimalPipelineStateError(f"{name} escaped the per-file working dir")
    return path


def _sidecar_summary(
    result: minimal_detection.DetectionResult,
    config,
    expected_name: str,
) -> dict:
    path = _working_path(config, expected_name)
    if result.report_path.resolve() != path.resolve():
        raise MinimalPipelineStateError(f"{expected_name} path disagrees with state")
    payload = _read_json(path, expected_name)
    canonical_record = json.loads(
        json.dumps(result.record, ensure_ascii=False, sort_keys=True)
    )
    if payload != canonical_record:
        raise MinimalPipelineStateError(f"{expected_name} differs from memory")
    counts = _mapping(payload.get("counts"), f"{expected_name}.counts")
    by_kind = _mapping(counts.get("by_kind"), f"{expected_name}.counts.by_kind")
    if set(by_kind) != set(minimal_detection.ISSUE_KINDS):
        raise MinimalPipelineStateError(f"{expected_name} has unknown issue kinds")
    normalized = {
        kind: _count(by_kind[kind], f"{expected_name}.{kind}")
        for kind in minimal_detection.ISSUE_KINDS
    }
    total = _count(counts.get("issues"), f"{expected_name}.counts.issues")
    if total != sum(normalized.values()) or total != len(result.issues):
        raise MinimalPipelineStateError(f"{expected_name} issue counts disagree")
    pass_index = _count(payload.get("pass_index"), f"{expected_name}.pass_index")
    return {
        "total": total,
        "by_kind": normalized,
        "pass_index": pass_index,
        "path": str(path.resolve()),
        "mirrored": "mirrored_after" in payload,
    }


def _chain_and_backfill_summary(config, before, translation_performed: bool):
    evidence = _mapping(
        before.record.get("chain_conservation"),
        "issues.before.chain_conservation",
    )
    path = _working_path(config, minimal_detection.CHAIN_REPORT_NAME)
    if not translation_performed:
        if path.exists():
            raise MinimalPipelineStateError(
                "offline run contains a stale chain translation report"
            )
        if (
            evidence.get("status") != "skipped_translation_not_performed"
            or evidence.get("typed_skip") is not True
            or _count(evidence.get("violations"), "offline chain violations") != 0
        ):
            raise MinimalPipelineStateError("offline chain evidence is not typed")
        chain = {
            "status": "skipped_translation_not_performed",
            "report_path": None,
            "requests": 0,
            "merged": 0,
            "members": 0,
            "claimed_members": 0,
            "single_request_holds": True,
            "claim_exclusion_holds": True,
            "conservation_holds": True,
            "typed_offline": True,
        }
        backfill = {
            "members": 0,
            "released_members": 0,
            "allocation_verified": True,
            "target_conservation_holds": True,
            "only_trailing_released": True,
        }
        return chain, backfill, 0

    report = _read_json(path, minimal_detection.CHAIN_REPORT_NAME)
    if evidence.get("status") != "available":
        raise MinimalPipelineStateError("translated chain evidence is unavailable")
    evidence_path = evidence.get("path")
    if not isinstance(evidence_path, str) or Path(evidence_path).resolve() != path.resolve():
        raise MinimalPipelineStateError("chain evidence path disagrees")
    counts = _mapping(report.get("counts"), "chain counts")
    requests = _count(counts.get("translator_calls"), "chain requests")
    merged = _count(counts.get("merged"), "merged chains")
    members = _count(counts.get("merged_members"), "merged members")
    outcomes = _sequence(report.get("outcomes"), "chain outcomes")
    entries = _sequence(report.get("chains"), "chain entries")
    skips = _sequence(report.get("skips"), "chain skips")
    outcome_refs = []
    single_request = requests == len(outcomes)
    for position, raw in enumerate(outcomes):
        outcome = _mapping(raw, f"chain outcome {position}")
        calls = _count(
            outcome.get("translator_call_count"),
            f"chain outcome {position}.translator_call_count",
        )
        refs = _sequence(
            outcome.get("ordered_source_refs"),
            f"chain outcome {position}.ordered_source_refs",
        )
        if not all(isinstance(reference, str) and reference for reference in refs):
            raise MinimalPipelineStateError("chain outcome refs must be text")
        outcome_refs.extend(refs)
        single_request = single_request and calls == 1
    chain_skips = [
        _mapping(item, f"chain skip {position}")
        for position, item in enumerate(skips)
        if isinstance(item, dict) and item.get("taken_by") == "chain"
    ]
    if any(not isinstance(item, dict) for item in skips):
        raise MinimalPipelineStateError("chain skips must be objects")
    claimed_members = len(chain_skips)
    claim_exclusion = (
        claimed_members == len(outcome_refs)
        and len(outcome_refs) == len(set(outcome_refs))
        and all(
            isinstance(item.get("declined_by"), list)
            and len(item["declined_by"]) == len(set(item["declined_by"]))
            for item in chain_skips
        )
    )
    violations = _count(evidence.get("violations"), "chain violations")
    conservation = report.get("applied") is True and violations == 0
    if merged != len(entries):
        raise MinimalPipelineStateError("merged chain count disagrees")

    released_members = 0
    allocation_verified = True
    only_trailing_released = True
    allocated_members = 0
    for position, raw in enumerate(entries):
        entry = _mapping(raw, f"chain entry {position}")
        allocation = _mapping(entry.get("allocation"), f"chain entry {position}.allocation")
        fragments = _sequence(
            allocation.get("fragments"),
            f"chain entry {position}.allocation.fragments",
        )
        allocation_verified = allocation_verified and allocation.get("verified") is True
        released_seen = False
        for fragment_position, raw_fragment in enumerate(fragments):
            fragment = _mapping(
                raw_fragment,
                f"chain entry {position}.fragment {fragment_position}",
            )
            status = fragment.get("status")
            if status == "released":
                released_seen = True
                released_members += 1
            elif status == "allocated":
                allocated_members += 1
                if released_seen:
                    only_trailing_released = False
            else:
                raise MinimalPipelineStateError("chain fragment status is invalid")
    if allocated_members + released_members != members:
        raise MinimalPipelineStateError("backfill member count disagrees")
    target_conservation = conservation and allocation_verified and only_trailing_released
    short_units = report.get("short_units")
    short_unit_requests = 0
    if short_units is not None:
        short_unit_requests = _count(
            _mapping(short_units, "short units").get("requests"),
            "short-unit requests",
        )
    chain = {
        "status": "available",
        "report_path": str(path.resolve()),
        "requests": requests,
        "merged": merged,
        "members": members,
        "claimed_members": claimed_members,
        "single_request_holds": single_request,
        "claim_exclusion_holds": claim_exclusion,
        "conservation_holds": conservation,
        "typed_offline": False,
    }
    backfill = {
        "members": members,
        "released_members": released_members,
        "allocation_verified": allocation_verified,
        "target_conservation_holds": target_conservation,
        "only_trailing_released": only_trailing_released,
    }
    return chain, backfill, short_unit_requests


def _article_context_requests(config, translation_performed: bool) -> int:
    path = _working_path(config, "article_context.report.json")
    if not translation_performed:
        if path.exists():
            raise MinimalPipelineStateError(
                "offline run contains a stale article-context report"
            )
        return 0
    report = _read_json(path, "article_context.report.json")
    return _count(
        _mapping(report.get("counts"), "article-context counts").get("requests"),
        "article-context requests",
    )


def _translator_counter(translator, name: str) -> int:
    value = getattr(translator, name, None)
    return _count(value, f"translator.{name}")


def _flow_summary(docs, article_document_ir, report: dict) -> dict:
    report = _mapping(report, "article flow report")
    totals = _mapping(report.get("totals"), "article flow totals")
    segments = _sequence(report.get("cross_page_segments"), "article flow segments")
    segment_count = _count(totals.get("segments_applied"), "flow segments applied")
    placements = _count(totals.get("placements"), "flow placements")
    movements = _count(
        totals.get("cross_page_movements"),
        "flow cross-page movements",
    )
    rolled_back = _count(
        totals.get("segments_rolled_back"),
        "flow rolled-back segments",
    )
    if segment_count != sum(item.get("status") == "applied" for item in segments):
        raise MinimalPipelineStateError("article flow applied count disagrees")
    owner_holds = True
    adjacency_holds = True
    target_holds = True
    for position, raw in enumerate(segments):
        segment = _mapping(raw, f"article flow segment {position}")
        if segment.get("status") != "applied":
            continue
        if segment.get("action_status") != "committed":
            raise MinimalPipelineStateError("applied article flow was not committed")
        article_id = segment.get("article_id")
        pages = _sequence(
            segment.get("contiguous_pages"),
            f"article flow segment {position}.contiguous_pages",
        )
        if (
            not isinstance(article_id, str)
            or not article_id
            or not pages
            or any(
                not isinstance(page, int)
                or isinstance(page, bool)
                or page < 1
                or page > len(docs.page)
                for page in pages
            )
        ):
            raise MinimalPipelineStateError("article flow segment identity is invalid")
        owner_holds = owner_holds and all(
            article_document_ir.by_page.get(page) == article_id for page in pages
        )
        adjacency_holds = adjacency_holds and pages == list(
            range(pages[0], pages[0] + len(pages))
        )
        physical = []
        for page in pages:
            value = getattr(docs.page[page - 1], "page_number", None)
            if value is None:
                physical.append(page)
            elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                physical.append(value + 1)
            else:
                adjacency_holds = False
        adjacency_holds = adjacency_holds and physical == list(
            range(physical[0], physical[0] + len(physical))
        )
        fixed = _mapping(
            segment.get("fixed_asset_comparison"),
            f"article flow segment {position}.fixed comparison",
        )
        snapshot = _mapping(
            segment.get("snapshot"),
            f"article flow segment {position}.snapshot",
        )
        source_ledger = _sequence(
            segment.get("source_ledger"),
            f"article flow segment {position}.source ledger",
        )
        target_ledger = _sequence(
            segment.get("target_ledger"),
            f"article flow segment {position}.target ledger",
        )
        candidate_placements = _sequence(
            segment.get("placements"),
            f"article flow segment {position}.placements",
        )
        target_holds = target_holds and bool(source_ledger) and bool(target_ledger)
        target_holds = (
            target_holds
            and fixed.get("holds") is True
            and snapshot.get("status") == "committed"
        )
        for target_position, raw_target in enumerate(target_ledger):
            target = _mapping(
                raw_target,
                f"article flow segment {position}.target {target_position}",
            )
            reference = target.get("source_ref")
            target_range = target.get("target_range")
            if (
                not isinstance(reference, str)
                or not isinstance(target_range, list)
                or len(target_range) != 2
                or any(
                    not isinstance(value, int) or isinstance(value, bool)
                    for value in target_range
                )
            ):
                raise MinimalPipelineStateError("article flow target ledger is invalid")
            pieces = sorted(
                (
                    _mapping(item, "article flow placement")
                    for item in candidate_placements
                    if isinstance(item, dict) and item.get("source_ref") == reference
                ),
                key=lambda item: item.get("target_range", [-1])[0],
            )
            cursor = target_range[0]
            chars = 0
            for piece in pieces:
                piece_range = piece.get("target_range")
                if (
                    not isinstance(piece_range, list)
                    or len(piece_range) != 2
                    or piece_range[0] != cursor
                    or piece_range[1] <= piece_range[0]
                ):
                    target_holds = False
                    break
                piece_chars = _count(piece.get("chars"), "article flow piece chars")
                if piece_chars != piece_range[1] - piece_range[0]:
                    target_holds = False
                chars += piece_chars
                cursor = piece_range[1]
            target_holds = (
                target_holds
                and cursor == target_range[1]
                and chars == _count(target.get("chars"), "article flow target chars")
            )
    if not owner_holds or not adjacency_holds or not target_holds:
        raise MinimalPipelineStateError("article flow conservation evidence failed")
    return {
        "segments": segment_count,
        "placements": placements,
        "cross_page_movements": movements,
        "rolled_back": rolled_back,
        "owner_boundary_holds": owner_holds,
        "physical_adjacency_holds": adjacency_holds,
        "target_conservation_holds": target_holds,
    }


def _dropcap_summary(report: dict) -> dict:
    totals = _mapping(_mapping(report, "drop-cap report").get("totals"), "drop-cap totals")
    decided = _count(totals.get("decided"), "drop-cap decided")
    rendered = _count(totals.get("set"), "drop-cap set")
    reverted = _count(totals.get("reverted"), "drop-cap reverted")
    by_state = _mapping(totals.get("by_state"), "drop-cap states")
    expected_states = {"committed", "invalid_intent", "render_rollback"}
    if set(by_state) != expected_states:
        raise MinimalPipelineStateError("drop-cap states are not the closed schema")
    committed = _count(by_state["committed"], "drop-cap committed")
    invalid_intent = _count(
        by_state["invalid_intent"],
        "drop-cap invalid intent",
    )
    render_rollback = _count(
        by_state["render_rollback"],
        "drop-cap render rollback",
    )
    if decided != committed + invalid_intent + render_rollback:
        raise MinimalPipelineStateError("drop-cap totals do not conserve candidates")
    if rendered != committed or reverted != render_rollback:
        raise MinimalPipelineStateError("drop-cap totals disagree with render states")
    typed_no_candidate = decided == 0 or (
        rendered == 0 and invalid_intent + reverted == decided
    )
    return {
        "decided": decided,
        "set": rendered,
        "reverted": reverted,
        "invalid_intent": invalid_intent,
        "typed_no_candidate": typed_no_candidate,
    }


def _repair_summary(result: minimal_repair.RepairResult) -> dict:
    record = _mapping(result.record, "repair record")
    action_count = _count(record.get("action_count"), "repair action count")
    applied_count = _count(record.get("applied_count"), "repair applied count")
    requests = _count(record.get("translator_requests"), "repair translator requests")
    passes = _count(
        record.get("detection_passes_added"),
        "repair detection passes added",
    )
    if action_count > 1 or applied_count > action_count or passes not in (0, 1):
        raise MinimalPipelineStateError("bounded repair count invariant failed")
    selected = record.get("selected")
    if selected is not None and selected not in minimal_repair.ACTIONS:
        raise MinimalPipelineStateError("repair selected an unknown action")
    if record.get("accepted") is not result.accepted:
        raise MinimalPipelineStateError("repair acceptance state disagrees")
    if record.get("rolled_back") is not result.rolled_back:
        raise MinimalPipelineStateError("repair rollback state disagrees")
    reason = record.get("reason")
    if not isinstance(reason, str) or not reason:
        raise MinimalPipelineStateError("repair requires a typed reason")
    filtered = record.get("filtered_candidates")
    if not isinstance(filtered, list):
        raise MinimalPipelineStateError("repair requires a filtered candidate list")
    rows = []
    for row in filtered:
        entry = _mapping(row, "repair filtered candidate")
        if set(entry) != {"id", "kind", "action", "reason"}:
            raise MinimalPipelineStateError(
                "repair filtered candidate is not the closed schema"
            )
        if entry["action"] not in minimal_repair.ACTIONS:
            raise MinimalPipelineStateError(
                "repair filtered candidate names an unknown action"
            )
        for name in ("id", "kind", "reason"):
            if not isinstance(entry[name], str) or not entry[name]:
                raise MinimalPipelineStateError(
                    f"repair filtered candidate {name} must be a non-empty string"
                )
        rows.append(dict(entry))
    # A refused candidate is why the run's one action went unspent, so the
    # reason it went unspent and the refusals have to agree with each other.
    if selected is None and reason == "all_candidates_refused" and not rows:
        raise MinimalPipelineStateError("refused repair run names no refusal")
    return {
        "selected": selected,
        "reason": reason,
        "action_count": action_count,
        "applied_count": applied_count,
        "translator_requests": requests,
        "detection_passes_added": passes,
        "accepted": result.accepted,
        "rolled_back": result.rolled_back,
        "filtered_candidates": rows,
    }


def _fixed_summary(final_detection: minimal_detection.DetectionResult) -> dict:
    comparison = _mapping(
        final_detection.record.get("fixed_comparison"),
        "final fixed comparison",
    )
    changed = 0
    for name in (
        "added",
        "removed",
        "bbox_changed",
        "digest_changed",
        "page_size_changed",
    ):
        changed += len(_sequence(comparison.get(name), f"fixed comparison.{name}"))
    holds = comparison.get("holds")
    if not isinstance(holds, bool) or holds != (changed == 0):
        raise MinimalPipelineStateError("fixed comparison count disagrees")
    return {"holds": holds, "drift_count": changed}


def _path_value(value) -> str | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_file():
        raise MinimalPipelineStateError(f"result PDF is missing: {path}")
    return str(path.resolve())


def _write_run_report(config, state: MagazineState, report: dict) -> Path:
    path = _working_path(config, RUN_REPORT_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    state._minimal_report = report
    state._minimal_report_path = path
    return path


def _loop_summary(result) -> dict:
    """The loop's own account of a run, held to its closed vocabulary."""
    record = _mapping(result.as_record(), "repair loop record")
    if record.get("termination") not in repair_loop_module.TERMINATIONS:
        raise MinimalPipelineStateError("the repair loop stopped for an unnamed reason")
    for row in record.get("accepted_actions") or ():
        if _mapping(row, "accepted action").get("action") not in minimal_repair.ACTIONS:
            raise MinimalPipelineStateError("the repair loop applied an unknown action")
    if record.get("rolled_back") and record.get("accepted_actions"):
        raise MinimalPipelineStateError("a rolled back loop kept actions")
    return record


def _build_run_report(config, docs, state: MagazineState) -> dict:
    before = state.detection_before
    repair_result = state.repair_result
    loop_result = state.loop_result
    article_document_ir = state.article_document_ir
    if before is None or article_document_ir is None:
        raise MinimalPipelineStateError("detection and repair evidence is incomplete")
    if (repair_result is None) == (loop_result is None):
        raise MinimalPipelineStateError(
            "exactly one of the one-shot pass and the repair loop must have run"
        )
    translation_performed = not bool(getattr(config, "skip_translation", False))
    before_summary = _sidecar_summary(before, config, "issues.before.json")
    final_detection = (
        repair_result.final_detection
        if loop_result is None
        else loop_result.final_detection
    )
    accepted = (
        repair_result.accepted if loop_result is None else loop_result.accepted
    )
    after_summary = _sidecar_summary(final_detection, config, "issues.after.json")
    if loop_result is None:
        repair = _repair_summary(repair_result)
        passes = 1 + _count(
            repair_result.record.get("detection_passes_added"),
            "repair detection passes added",
        )
        if passes not in (1, 2):
            raise MinimalPipelineStateError("detector pass count must be one or two")
    else:
        repair = _loop_summary(loop_result)
        # The loop measures once per iteration it applied something in, so the
        # pass count is bounded by the iteration ceiling rather than by one.
        passes = 1 + _count(
            repair.get("detection_passes_added"),
            "repair loop detection passes added",
        )
    if before_summary["pass_index"] != 0:
        raise MinimalPipelineStateError("before sidecar must be detector pass zero")
    expected_after_index = 1 if accepted else 0
    if after_summary["pass_index"] != expected_after_index:
        raise MinimalPipelineStateError("after sidecar pass index disagrees")
    if after_summary["mirrored"] != (not accepted):
        raise MinimalPipelineStateError("after sidecar mirror evidence disagrees")

    chain, backfill, short_unit_requests = _chain_and_backfill_summary(
        config,
        before,
        translation_performed,
    )
    article_context_requests = _article_context_requests(
        config,
        translation_performed,
    )
    translator = getattr(config, "translator", None)
    translator_total = _translator_counter(translator, "translate_call_count")
    translator_cache = _translator_counter(
        translator,
        "translate_cache_call_count",
    )
    if translator_cache > translator_total:
        raise MinimalPipelineStateError("translator cache count exceeds total")
    excluded = (
        chain["requests"]
        + article_context_requests
        + short_unit_requests
        + repair["translator_requests"]
    )
    ordinary_requests = translator_total - excluded
    if ordinary_requests < 0:
        raise MinimalPipelineStateError("ordinary translator count became negative")
    if not translation_performed and (
        translator_total
        or translator_cache
        or excluded
        or ordinary_requests
    ):
        raise MinimalPipelineStateError("offline execution recorded translator requests")
    ordinary = {
        "translator_total": translator_total,
        "translator_cache": translator_cache,
        "chain_requests": chain["requests"],
        "article_context_requests": article_context_requests,
        "short_unit_requests": short_unit_requests,
        "repair_requests": repair["translator_requests"],
        "requests": ordinary_requests,
        "claimed_members_excluded": chain["claim_exclusion_holds"],
    }
    flow = _flow_summary(docs, article_document_ir, state.flow_report)
    dropcap = _dropcap_summary(state.render_report)
    fixed = _fixed_summary(final_detection)
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": "pending_output",
        "translation_performed": translation_performed,
        "completed": False,
        "chain": chain,
        "ordinary": ordinary,
        "backfill": backfill,
        "flow": flow,
        "dropcap": dropcap,
        "issues": {
            "before": {
                "total": before_summary["total"],
                "by_kind": before_summary["by_kind"],
            },
            "after": {
                "total": after_summary["total"],
                "by_kind": after_summary["by_kind"],
            },
        },
        "detector": {
            "passes": passes,
            "before_path": before_summary["path"],
            "after_path": after_summary["path"],
            "before_pass_index": before_summary["pass_index"],
            "after_pass_index": after_summary["pass_index"],
            "after_mirrored": after_summary["mirrored"],
        },
        "repair": repair,
        "fixed": fixed,
        "output": {
            "status": "pending",
            "mono": None,
            "dual": None,
            "no_watermark_mono": None,
            "no_watermark_dual": None,
        },
    }


def _translates_over_the_network(config) -> bool:
    """Whether this run reaches a model at all.

    A run given the offline translator has no provider to put a question to,
    and a run given none has nothing at all. Either way there is no decision to
    take and the deterministic pass answers instead.
    """
    from babeldoc.translator.no_network import NoNetworkTranslator

    translator = getattr(config, "translator", None)
    return translator is not None and not isinstance(translator, NoNetworkTranslator)


def _decision_client(config, translation_performed: bool):
    """The model the repair loop decides with, or None when there is none.

    A run with no credential, or one that translated nothing, has nothing to
    decide about and nothing to decide with. Returning None rather than raising
    is what lets an offline run finish: the deterministic one-shot pass answers
    for it instead, and the run report says which of the two ran.
    """
    if not translation_performed:
        return None
    if bool(getattr(config, "only_parse_generate_pdf", False)):
        return None
    # The decision goes to the same provider the run translates with, and the
    # run says which that is by the translator it was given. Asking instead
    # whether a credential happens to be in the environment would make a run's
    # behaviour depend on the shell it was started from.
    if not _translates_over_the_network(config):
        return None
    try:
        return llm_decide.OpenAIDecisionClient(llm_decide.load_decide_config())
    except llm_decide.DecisionError:
        return None
    except Exception:  # pragma: no cover - a client this run cannot build
        logger.warning("repair decisions unavailable; the one-shot pass will run")
        return None


def _record_repair_evidence(
    config,
    state: MagazineState,
    loop_result,
    snapshot,
    temp_pdf_path,
    mediabox_data,
) -> None:
    """Render the pre-repair pages a kept action wrote to, and nothing else.

    A run that kept nothing renders nothing: two identical pictures would look
    like evidence of a repair while being evidence of none. Failure to render
    is reported and does not fail the run -- the translated document is the
    deliverable and the pictures are an account of it.
    """
    pages = sorted(
        {page for action in loop_result.accepted_actions for page in action.pages}
    )
    if not pages or snapshot is None or temp_pdf_path is None:
        return
    try:
        before_pdf = repair_evidence.write_before_pdf(
            config, snapshot, temp_pdf_path, mediabox_data
        )
        repair_evidence.render_pages(
            before_pdf,
            pages,
            repair_evidence.evidence_dir(config),
            repair_evidence.BEFORE_SUFFIX,
        )
    except Exception:
        logger.warning("pre-repair evidence could not be rendered", exc_info=True)
        return
    state._evidence_pages = tuple(pages)
    state._evidence_before_pdf = before_pdf


def _detect_and_repair(
    config,
    docs,
    typesetter,
    state: MagazineState,
    *,
    temp_pdf_path=None,
    mediabox_data=None,
) -> None:
    if state._detection_started:
        raise MinimalPipelineStateError("minimal detection was already attempted")
    if not state.render_completed:
        raise MinimalPipelineStateError("drop-cap render did not complete")
    if state.render_document_identity != id(docs):
        raise MinimalPipelineStateError("drop-cap render belongs to another document")
    article_document_ir = get_article_document_ir(config)
    baseline = state.detection_baseline
    if baseline is None:
        raise MinimalPipelineStateError("detection baseline is not available")
    if baseline.document_identity != id(docs):
        raise MinimalPipelineStateError("detection baseline belongs to another document")
    if baseline.article_document_identity != id(article_document_ir):
        raise MinimalPipelineStateError("detection baseline belongs to another ArticleIR")

    state._detection_started = True
    state._detection_document_identity = id(docs)
    translation_performed = not bool(getattr(config, "skip_translation", False))
    working_dir = Path(config.working_dir)
    with _without_debug_overlay_text(docs):
        before = minimal_detection.detect(
            docs,
            article_document_ir,
            baseline,
            language=getattr(config, "lang_out", None),
            translation_performed=translation_performed,
            working_dir=working_dir,
            sidecar_name="issues.before.json",
            pass_index=0,
            flow_report=state.flow_report,
            hitl_state=state.hitl_state,
        )
        state._detection_before = before

        def detect_after(repair_owned_local_ref):
            binding = None
            if repair_owned_local_ref is not None:
                binding = (
                    baseline.physical_ref(repair_owned_local_ref),
                    repair_owned_local_ref,
                )
            return minimal_detection.detect(
                docs,
                article_document_ir,
                baseline,
                language=getattr(config, "lang_out", None),
                translation_performed=translation_performed,
                working_dir=working_dir,
                sidecar_name="issues.after.json",
                pass_index=1,
                flow_report=state.flow_report,
                repair_owned_binding=binding,
                hitl_state=state.hitl_state,
            )

        client = _decision_client(config, translation_performed)
        if client is None:
            # No model to decide with -- an offline run, or one with no
            # credential. The one-shot deterministic pass is what the loop
            # degenerates to, and it is kept rather than simulated.
            repair_result = minimal_repair.repair_once(
                before,
                docs,
                article_document_ir,
                baseline,
                typesetter,
                config,
                state.flow_report,
                detect_after,
            )
            if not isinstance(repair_result, minimal_repair.RepairResult):
                raise MinimalPipelineStateError(
                    "minimal repair did not return a RepairResult"
                )
            state._repair_result = repair_result
        else:
            # The pre-repair document has to be kept before the loop touches
            # it, and only where there is something to render it with. A
            # snapshot that cannot be taken costs the run its pictures and
            # nothing else: the translated document is the deliverable.
            snapshot = None
            if temp_pdf_path is not None:
                try:
                    snapshot = repair_evidence.capture(docs)
                except Exception:
                    logger.warning(
                        "the pre-repair document could not be snapshotted; "
                        "this run will produce no repair pictures",
                        exc_info=True,
                    )
            loop_result = repair_loop_module.repair_loop(
                before,
                docs,
                article_document_ir,
                baseline,
                typesetter,
                config,
                state.flow_report,
                detect_after,
                client=client,
                working_dir=working_dir,
            )
            if not isinstance(loop_result, repair_loop_module.LoopResult):
                raise MinimalPipelineStateError(
                    "the repair loop did not return a LoopResult"
                )
            state._loop_result = loop_result
            _record_repair_evidence(
                config,
                state,
                loop_result,
                snapshot,
                temp_pdf_path,
                mediabox_data,
            )
    report = _build_run_report(config, docs, state)
    _write_run_report(config, state, report)
    state._detection_completed = True


def _refresh_detection_fixed_baseline(
    docs,
    article_document_ir,
    state: MagazineState,
) -> minimal_detection.DetectionBaseline:
    if state._fixed_baseline_refresh_started:
        raise MinimalPipelineStateError(
            "post-typesetting fixed baseline refresh was already attempted"
        )
    state._fixed_baseline_refresh_started = True
    state._fixed_baseline_refresh_document_identity = id(docs)
    if not state._render_started:
        raise MinimalPipelineStateError(
            "fixed baseline refresh must run inside the render phase"
        )
    if state.structure_document_identity != id(docs):
        raise MinimalPipelineStateError(
            "fixed baseline refresh belongs to a different document"
        )
    if state.flow_document_identity != id(docs):
        raise MinimalPipelineStateError(
            "fixed baseline refresh article flow belongs to another document"
        )
    baseline = state.detection_baseline
    if baseline is None:
        raise MinimalPipelineStateError("source detection baseline is not available")
    source_geometry = baseline.source_geometry
    with _without_debug_overlay_text(docs):
        refreshed = minimal_detection.refresh_fixed_inventory(
            baseline,
            docs,
            article_document_ir,
            flow_report=state.flow_report,
        )
    if refreshed.source_geometry is not source_geometry:
        raise MinimalPipelineStateError(
            "fixed baseline refresh replaced frozen source geometry"
        )
    state._detection_baseline = refreshed
    state._fixed_baseline_refresh_completed = True
    return refreshed


def after_typesetting(
    config, docs, typesetter, temp_pdf_path=None, mediabox_data=None
) -> dict:
    """Render frozen titles then drop-cap intents after formal typesetting."""
    state = _state(config)
    if state._render_started:
        raise MinimalPipelineStateError("drop-cap render was already attempted")
    state._render_started = True
    state._render_document_identity = id(docs)
    article_document_ir = get_article_document_ir(config)
    if not state.translation_prep_completed:
        raise MinimalPipelineStateError("translation preparation did not complete")
    if not state.flow_completed:
        raise MinimalPipelineStateError("article flow did not complete")
    if state.structure_document_identity != id(docs):
        raise MinimalPipelineStateError(
            "canonical ArticleDocumentIR belongs to a different document"
        )
    if state.flow_document_identity != id(docs):
        raise MinimalPipelineStateError("article flow belongs to a different document")
    if state.typesetter_identity != id(typesetter):
        raise MinimalPipelineStateError("formal typesetter identity changed")
    if getattr(typesetter, "translation_config", None) is not config:
        raise MinimalPipelineStateError(
            "drop-cap renderer typesetter belongs to a different config"
        )

    if (
        isinstance(state.flow_report, dict)
        and state.flow_report.get("article_flow_applied") is False
    ):
        layout_report.finalize()
    title_report = title_typeset.apply(config, docs, typesetter)
    if not isinstance(title_report, dict):
        raise MinimalPipelineStateError("title typesetter did not return a report")
    _refresh_detection_fixed_baseline(
        docs,
        article_document_ir,
        state,
    )
    report = drop_cap_render.apply(
        config,
        docs,
        article_document_ir=article_document_ir,
        typesetting_stage=typesetter,
    )
    if not isinstance(report, dict):
        raise MinimalPipelineStateError("drop-cap renderer did not return a report")
    if state.article_document_ir is not article_document_ir:
        raise MinimalPipelineStateError("canonical ArticleDocumentIR identity changed")
    state._render_report = report
    state._render_completed = True
    _detect_and_repair(
        config,
        docs,
        typesetter,
        state,
        temp_pdf_path=temp_pdf_path,
        mediabox_data=mediabox_data,
    )
    # Measured after repair so the sidecar describes the pages the run ships,
    # not an intermediate state a later pass may still have moved.
    tail_fill.apply(
        config,
        docs,
        article_document_ir=article_document_ir,
        typesetter=typesetter,
    )
    return report


def finalize_result(config, result) -> dict:
    """Bind final output paths and complete the unique minimal run report."""
    state = _state(config)
    if state._result_started:
        raise MinimalPipelineStateError("minimal result finalization was already attempted")
    state._result_started = True
    state._result_identity = id(result)
    if bool(getattr(config, "only_parse_generate_pdf", False)):
        if state.structure_started or state.detection_started:
            raise MinimalPipelineStateError(
                "parse-only finalization found partial magazine pipeline state"
            )
        state._result_completed = True
        return {
            "schema_version": RUN_SCHEMA_VERSION,
            "status": "not_applicable_parse_only",
            "completed": True,
        }
    if not state.detection_completed:
        raise MinimalPipelineStateError("minimal detection did not complete")
    if state.minimal_report is None or state.minimal_report_path is None:
        raise MinimalPipelineStateError("minimal run report is not available")
    current = _read_json(state.minimal_report_path, RUN_REPORT_NAME)
    if current != state.minimal_report:
        raise MinimalPipelineStateError("minimal run report changed before finalization")
    report = json.loads(json.dumps(state.minimal_report, ensure_ascii=False))
    output = {
        "status": "complete",
        "mono": _path_value(getattr(result, "mono_pdf_path", None)),
        "dual": _path_value(getattr(result, "dual_pdf_path", None)),
        "no_watermark_mono": _path_value(
            getattr(result, "no_watermark_mono_pdf_path", None)
        ),
        "no_watermark_dual": _path_value(
            getattr(result, "no_watermark_dual_pdf_path", None)
        ),
    }
    if output["mono"] is None:
        raise MinimalPipelineStateError("minimal run has no monolingual PDF result")
    report["output"] = output
    report["status"] = "complete"
    report["completed"] = True
    report["repair_evidence"] = _finish_repair_evidence(config, state, output)
    _write_run_report(config, state, report)
    state._result_completed = True
    return report


def _finish_repair_evidence(config, state: MagazineState, output: dict) -> dict:
    """Rasterise the finished pages beside the pre-repair ones already rendered.

    The "after" picture is the delivered document rather than a second render
    of the same intermediate state, so what a reader compares is the page that
    was actually produced.
    """
    pages = state.evidence_pages
    record = {"pages": list(pages), "pairs": [], "before_pdf": None}
    if not pages or state.evidence_before_pdf is None:
        return record
    record["before_pdf"] = _path_value(state.evidence_before_pdf)
    finished = output.get("no_watermark_mono") or output.get("mono")
    if finished is None:
        return record
    directory = repair_evidence.evidence_dir(config)
    try:
        repair_evidence.render_pages(
            finished, pages, directory, repair_evidence.AFTER_SUFFIX
        )
    except Exception:
        logger.warning("finished repair evidence could not be rendered", exc_info=True)
        return record
    record["pairs"] = [
        {
            "page": page,
            "before": _path_value(before),
            "after": _path_value(after),
        }
        for page, (before, after) in sorted(
            repair_evidence.pairs(directory, pages).items()
        )
    ]
    return record
