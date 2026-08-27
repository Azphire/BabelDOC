"""Offline production-path checks for the closed C19 repair handlers."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import types
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importing the repair package must not open the user's process-wide cache.
# This gate supplies both decision and translation replies deterministically.
cache_stub = types.ModuleType("babeldoc.translator.cache")


class OfflineCache:
    def __init__(self, *_args, **_kwargs) -> None:
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value) -> None:
        self.values[key] = value


cache_stub.TranslationCache = OfflineCache
sys.modules["babeldoc.translator.cache"] = cache_stub

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import acceptance  # noqa: E402
from babeldoc.magazine import fixed_assets  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticlePolicyEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ArticleRegionSlot  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.article_ir import UnsupportedArticlePage  # noqa: E402
from babeldoc.magazine.article_state import ArticleStateJournal  # noqa: E402
from babeldoc.magazine.article_state import ArticleStateStage  # noqa: E402
from babeldoc.magazine.detectors import build_context  # noqa: E402
from babeldoc.magazine.detectors import detector_config  # noqa: E402
from babeldoc.magazine.detectors.base import Issue  # noqa: E402
from babeldoc.magazine.element_roles import ElementRole  # noqa: E402
from babeldoc.magazine.legal_slots import digest_record  # noqa: E402
from babeldoc.magazine.legal_slots import plan_legal_slots  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import chain_repair  # noqa: E402
from babeldoc.magazine.react import collision  # noqa: E402
from babeldoc.magazine.react import config as repair_config_module  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.magazine.react import region_repair  # noqa: E402
from babeldoc.magazine.repair_contract import RepairAction  # noqa: E402
from babeldoc.magazine.repair_contract import RepairDecision  # noqa: E402
from babeldoc.magazine.repair_contract import RepairIssueEvidence  # noqa: E402
from babeldoc.magazine.repair_contract import RepairIssueKind  # noqa: E402
from babeldoc.magazine.repair_contract import RepairKnowledgeState  # noqa: E402
from babeldoc.magazine.repair_contract import RepairTarget  # noqa: E402
from babeldoc.magazine.repair_contract import StaleRepairStateError  # noqa: E402
from babeldoc.magazine.repair_detector_closure import DetectorClosureRun  # noqa: E402
from babeldoc.magazine.repair_detector_closure import (  # noqa: E402
    load_repair_detector_closure,
)
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402
from babeldoc.magazine.run_trace import hash_record  # noqa: E402
from babeldoc.magazine.transaction import TransactionSnapshot  # noqa: E402

# This existing deterministic fixture already exercises the real C18 chain
# translation, Typesetting.fit_text_to_slot, and RunTrace target allocation.
from spec_checks import spec_check_chain_slot_backfill as chain_fixture  # noqa: E402

CHECKS = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"PASS: {name}")
        return
    FAILURES.append(f"{name}: {detail}")
    print(f"FAIL: {name} :: {detail}")


def style(size: float = 10.0) -> il.PdfStyle:
    return il.PdfStyle(
        font_id="body", font_size=size, graphic_state=il.GraphicState()
    )


def character(text: str, x: float, y: float, width: float, size: float):
    box = il.Box(x, y, x + width, y + size)
    return il.PdfCharacter(
        char_unicode=text,
        box=box,
        visual_bbox=il.VisualBbox(box=copy.deepcopy(box)),
        pdf_style=style(size),
        advance=width / size,
        vertical=False,
        xobj_id=0,
    )


def laid_out(
    text: str,
    x: float,
    y: float,
    *,
    size: float = 10.0,
    width: float | None = None,
    label: str = "plain text",
    debug_id: str | None = None,
    paragraph_box: tuple[float, float, float, float] | None = None,
):
    step = size * 0.6 if width is None else width
    characters = [
        character(letter, x + index * step, y, step, size)
        for index, letter in enumerate(text)
    ]
    ink = (
        min(item.box.x for item in characters),
        min(item.box.y for item in characters),
        max(item.box.x2 for item in characters),
        max(item.box.y2 for item in characters),
    )
    return il.PdfParagraph(
        box=il.Box(*(ink if paragraph_box is None else paragraph_box)),
        pdf_style=style(size),
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=item) for item in characters
        ],
        unicode=text,
        layout_label=label,
        debug_id=debug_id,
        vertical=False,
        xobj_id=-1,
    )


def page(paragraphs, number: int):
    frame = il.Box(0.0, 0.0, 600.0, 800.0)
    return il.Page(
        page_number=number,
        mediabox=il.Mediabox(box=frame),
        cropbox=il.Cropbox(box=copy.deepcopy(frame)),
        pdf_paragraph=list(paragraphs),
        pdf_figure=[il.PdfFigure(box=il.Box(500.0, 20.0, 570.0, 90.0))],
        unit="point",
    )


def article_fixture():
    pages = [
        page(
            [
                laid_out("HEADING", 80.0, 796.0, size=20.0, label="title"),
                laid_out("ordinary body", 80.0, 600.0),
                laid_out("LARGER", 180.0, 400.0, width=12.0),
                laid_out("x", 195.0, 402.0, width=5.0),
            ],
            0,
        ),
        page(
            [
                laid_out(
                    "未翻译的正文内容确实足够长",
                    80.0,
                    500.0,
                    label="fallback_line",
                    paragraph_box=(80.0, 500.0, 300.0, 520.0),
                ),
                laid_out("neighbour", 80.0, 450.0),
            ],
            1,
        ),
    ]
    document = il.Document(page=pages)
    roles = (
        ElementRole.HEADING,
        ElementRole.BODY,
        ElementRole.BODY,
        ElementRole.BODY,
        ElementRole.BODY,
        ElementRole.BODY,
    )
    elements = []
    order = 0
    for page_number, current_page in enumerate(pages, start=1):
        for index, paragraph in enumerate(current_page.pdf_paragraph):
            reference = f"p{page_number}#{index}"
            box = paragraph.box
            elements.append(
                SourceElementRef(
                    source_ref=reference,
                    page=page_number,
                    column=0,
                    reading_order=order,
                    role=roles[order],
                    source_box=(box.x, box.y, box.x2, box.y2),
                    source_text_hash=hashlib.sha256(
                        paragraph.unicode.encode("utf-8")
                    ).hexdigest(),
                    style_hash=hash_record(
                        {
                            "font_id": "body",
                            "font_size": paragraph.pdf_style.font_size,
                            "graphic_state": None,
                        }
                    ),
                )
            )
            order += 1
    slots = (
        ArticleRegionSlot(
            "article-a", 1, 0, 0, (40.0, 100.0, 480.0, 760.0), (), 290400.0
        ),
        ArticleRegionSlot(
            "article-a", 2, 0, 1, (40.0, 100.0, 480.0, 760.0), (), 290400.0
        ),
    )
    article = ArticleIR(
        article_id="article-a",
        pages=(1, 2),
        elements=tuple(elements),
        slots=slots,
        chain_ids=(),
        policy_evidence=(
            ArticlePolicyEvidence(1, "opens", "feature", None, True),
            ArticlePolicyEvidence(2, "member", "feature", None, True),
        ),
    )
    article_ir = ArticleDocumentIR(
        articles=(article,),
        by_page={1: "article-a", 2: "article-a"},
        by_element=dict.fromkeys((item.source_ref for item in elements), "article-a"),
        by_chain={},
    )
    slots_plan = plan_legal_slots(article_ir)
    trace = RunTrace.from_document(document, article_ir)
    return document, article_ir, slots_plan, trace


def finding(kind: str, page_number: int, refs, evidence, detector: str):
    config = detector_config()
    return Issue(
        kind=kind,
        page=page_number,
        paragraph_refs=tuple(refs),
        geometry=None,
        severity=config.severity[kind],
        evidence=dict(evidence),
        detector=detector,
        article_refs=("article-a",),
        source_refs=tuple(refs),
        suggested_action_type=config.suggested_action(kind),
    ).with_severity_fields(config.progress_fields(kind))


def context_for(document, article_ir, slots_plan, trace):
    return build_context(
        document,
        detector_config(),
        "en",
        None,
        source_geometry=SimpleNamespace(
            boxes={}, stage="fixture", path="fixture.xml"
        ),
        article_document_ir=article_ir,
        run_trace=trace,
        fixed_inventory=fixed_assets.build_inventory(
            document, article_document_ir=article_ir, run_trace=trace
        ),
        current_inventory=fixed_assets.build_inventory(
            document, article_document_ir=article_ir, run_trace=trace
        ),
        legal_slot_plan=slots_plan,
    )


def strict_commit(transaction, before, action: RepairAction, touched) -> bool:
    registry = load_repair_detector_closure()
    closure = DetectorClosureRun(
        action=action,
        registry_version=registry.schema_version,
        ran_detectors=registry.complete_detector_suite,
        conservation_invariants_passed=True,
    )
    closure.require_complete(registry)
    result = acceptance.compare_repair_action(
        [before],
        [],
        acceptance.load_acceptance_policy(),
        action=action,
        target_issue_ids=(before.id,),
        closure_complete=True,
        conservation_holds=True,
        touched_scope_valid=True,
    )
    if result.accepted:
        transaction.commit(touched)
    else:
        transaction.rollback()
    return result.accepted


class OneReplyTransport:
    def __init__(self, translation: str) -> None:
        self.translation = translation
        self.calls = 0

    def complete(self, _prompt: str) -> str:
        self.calls += 1
        return json.dumps({"translation": self.translation}, ensure_ascii=False)


class SafeTypesetter:
    font_mapper = SimpleNamespace(fontid2font={})

    @staticmethod
    def render_paragraph(_paragraph, _page, _fonts) -> None:
        return None


def check_vocabulary() -> None:
    config = repair_config_module.load_repair_config(
        None, controller.detector_kinds()
    )
    expected = {item.value for item in RepairAction} - {"no_action"}
    check(
        "repair config exposes exactly five mutating actions plus no_action",
        set(config.actions) == expected
        and repair_config_module.NO_ACTION == RepairAction.NO_ACTION.value,
        str(sorted(config.actions)),
    )
    check(
        "controller binds every mutating action to one production handler",
        set(
            controller.RepairLoop._handlers(
                SimpleNamespace(
                    _translate_orphans=None,
                    _reallocate_chain=None,
                    _retypeset_article_region=None,
                    _contain=None,
                    _resolve_collisions=None,
                )
            ).keys()
        )
        == expected,
    )


def check_omitted_handler() -> None:
    document, article_ir, slots_plan, trace = article_fixture()
    issue = finding(
        "untranslated_residue",
        2,
        ("p2#0",),
        {"residue_ratio": 1.0, "layout_label": "fallback_line", "residue_chars": 12},
        "residue",
    )
    context = context_for(document, article_ir, slots_plan, trace)
    action = repair_config_module.load_repair_config(
        None, controller.detector_kinds()
    ).actions[actions.NAME]
    candidate = actions.resolve(issue, {view.label: view for view in context.pages})
    check(
        "reprocess omitted text preflight admits canonical BODY with legal slot",
        candidate is not None
        and actions.admits_candidate(issue, candidate, action, context)
        == actions.ACCEPTED,
    )
    transport = OneReplyTransport("translated body copy")
    translator = actions.CachedOrphanTranslator(
        repair_config_module.load_repair_config(None, controller.detector_kinds()),
        transport=transport,
        cache=OfflineCache(),
        identity="offline",
        language="en",
        working_dir=ROOT,
    )
    owner = SimpleNamespace(
        translator=translator,
        typesetting=SafeTypesetter(),
        repair_config=translator.config,
        language="en",
        article_document_ir=article_ir,
        legal_slot_plan=slots_plan,
        run_trace=trace,
        touched=set(),
        applications=0,
        attributions=[],
        offered_texts=[],
        _translator=lambda: translator,
        _typesetting=lambda: SafeTypesetter(),
    )
    transaction = TransactionSnapshot.capture(document, run_trace=trace)
    before_generation = trace.current_generation
    transaction.begin_generation("handler_omitted")
    written = controller.RepairLoop._translate_orphans(
        owner, [candidate], context, controller.Snapshot(), action
    )
    committed = strict_commit(
        transaction, issue, RepairAction.REPROCESS_OMITTED_TEXT, ("p2#0",)
    )
    request = next(iter(trace.requests.values()))
    fragments = trace.target_fragments_for_source("p2#0")
    check(
        "reprocess omitted text mutates through CachedOrphanTranslator and commits",
        committed
        and written[0].changed
        and document.page[1].pdf_paragraph[0].unicode == "translated body copy"
        and transport.calls == 1
        and trace.current_generation == before_generation + 1,
    )
    check(
        "omitted target and canonical slot are recorded in the same generation",
        request.status == "completed"
        and len(fragments) == 1
        and fragments[0]["slot_id"]
        and trace.fragments[fragments[0]["fragment_id"]].generation
        == trace.current_generation,
    )
    other_owner = copy.copy(issue)
    object.__setattr__(other_owner, "article_refs", ("article-other",))
    check(
        "reprocess omitted text refuses a foreign owner",
        actions.admits_candidate(other_owner, candidate, action, context)
        == actions.REASON_OWNER,
    )


def check_heading_handler() -> None:
    document, article_ir, slots_plan, trace = article_fixture()
    issue = finding(
        "out_of_page",
        1,
        ("p1#0",),
        {
            "overflow_max": 16.0,
            "overflow_ratio": 0.1,
            "layout_label": "title",
        },
        "page_bounds",
    )
    context = context_for(document, article_ir, slots_plan, trace)
    action = repair_config_module.load_repair_config(
        None, controller.detector_kinds()
    ).actions[contain.NAME]
    candidate = actions.resolve(issue, {view.label: view for view in context.pages})
    transaction = TransactionSnapshot.capture(document, run_trace=trace)
    before_generation = trace.current_generation
    transaction.begin_generation("handler_heading")
    verdict = contain.admits(issue, candidate, action, context)
    result = contain.apply_one(candidate, action, context.config.collision_min_iou)
    committed = strict_commit(
        transaction, issue, RepairAction.CONTAIN_OVERFLOWING_HEADING, ("p1#0",)
    )
    ink = contain.ink_box(document.page[0].pdf_paragraph[0])
    check(
        "contain heading preflight, mutation, closure and strict commit succeed",
        verdict == actions.ACCEPTED
        and result.changed
        and ink is not None
        and ink[3] <= 800.0
        and committed
        and trace.current_generation == before_generation + 1,
    )
    body_issue = finding(
        "out_of_page",
        1,
        ("p1#1",),
        {
            "overflow_max": 10.0,
            "overflow_ratio": 0.1,
            "layout_label": "title",
        },
        "page_bounds",
    )
    body = actions.resolve(body_issue, {view.label: view for view in context.pages})
    check(
        "contain heading refuses a BODY target even when labels claim title",
        contain.admits(body_issue, body, action, context) == contain.REASON_ROLE,
    )


def check_collision_handler() -> None:
    document, article_ir, slots_plan, trace = article_fixture()
    issue = finding(
        "text_text_collision",
        1,
        ("p1#2", "p1#3"),
        {
            "coverage": 1.0,
            "iou": 0.06,
            "source_coverage": 0.0,
            "source_iou": 0.0,
            "overlap_area": 50.0,
        },
        "collision",
    )
    context = context_for(document, article_ir, slots_plan, trace)
    action = repair_config_module.load_repair_config(
        None, controller.detector_kinds()
    ).actions[collision.NAME]
    candidate = actions.resolve(issue, {view.label: view for view in context.pages})
    verdict = collision.admits(issue, candidate, action, context)
    transaction = TransactionSnapshot.capture(document, run_trace=trace)
    before_generation = trace.current_generation
    transaction.begin_generation("handler_collision")
    outcome, plan = collision.separate(candidate, action, context.config)
    if plan is not None:
        collision.move(document.page[0].pdf_paragraph[plan.mover_index], plan)
        outcome = collision.finish(candidate, outcome, plan, context.config)
    committed = strict_commit(
        transaction, issue, RepairAction.RESOLVE_TEXT_COLLISION, (outcome.reference,)
    )
    check(
        "resolve collision preflight, mutation, closure and strict commit succeed",
        verdict == actions.ACCEPTED
        and plan is not None
        and outcome.changed
        and committed
        and trace.current_generation == before_generation + 1,
        outcome.reason,
    )
    source_existing = copy.copy(issue)
    object.__setattr__(
        source_existing,
        "evidence",
        {**issue.evidence, "source_coverage": 1.0},
    )
    check(
        "resolve collision refuses a source-existing overlap",
        collision.admits(source_existing, candidate, action, context)
        == collision.REASON_SOURCE,
    )


def chain_case():
    target = "译" * 36
    plan, translator, document, paragraphs, *_rest = chain_fixture.run_chain(target)
    article_ir = plan.article_document_ir
    slots_plan = plan_legal_slots(article_ir)
    trace = translator.run_trace
    return document, article_ir, slots_plan, trace, paragraphs, translator


def check_chain_handler() -> None:
    document, article_ir, slots_plan, trace, paragraphs, translator = chain_case()
    issue = finding(
        "chain_conservation",
        1,
        ("p1#0", "p1#1", "p2#0", "p2#1"),
        {"chain_id": "chain-canonical", "violation_count": 1},
        "chain_conservation",
    )
    context = context_for(document, article_ir, slots_plan, trace)
    candidate = chain_repair.resolve_candidate(
        issue, {view.label: view for view in context.pages}, context
    )
    action = repair_config_module.load_repair_config(
        None, controller.detector_kinds()
    ).actions[chain_repair.NAME]
    verdict = chain_repair.admits(issue, candidate, action, context)
    before_box = copy.deepcopy(paragraphs[0].box)
    paragraphs[0].box = il.Box(2.0, 2.0, 20.0, 8.0)
    transaction = TransactionSnapshot.capture(document, run_trace=trace)
    before_generation = trace.current_generation
    transaction.begin_generation("handler_chain")
    typesetter = Typesetting(
        translator.translation_config,
        font_mapper=translator.il_translator.font_mapper,
    )
    allocation = chain_repair.plan(candidate, context, typesetter)
    chain_repair.apply_plan(document, trace, trace.current_generation, allocation)
    committed = strict_commit(
        transaction,
        issue,
        RepairAction.REALLOCATE_CONTINUITY_CHAIN,
        allocation.touched_refs,
    )
    check(
        "reallocate chain uses complete existing target and commits one generation",
        verdict == actions.ACCEPTED
        and committed
        and trace.current_generation == before_generation + 1
        and paragraphs[0].box != before_box
        and trace.whole_target_text(allocation.request_id) == "译" * 36,
    )
    unavailable = copy.copy(context)
    unavailable.run_trace = None
    check(
        "reallocate chain refuses when the complete RunTrace target is unavailable",
        chain_repair.admits(issue, candidate, action, unavailable)
        == chain_repair.REASON_TARGET,
    )


def check_region_handler() -> None:
    document, article_ir, slots_plan, trace, _paragraphs, translator = chain_case()
    issue = finding(
        "abnormal_blank",
        1,
        ("p1#0",),
        {"blank_area_ratio": 0.5, "column": 0},
        "abnormal_blank",
    )
    context = context_for(document, article_ir, slots_plan, trace)
    candidate = region_repair.resolve_candidate(
        issue, {view.label: view for view in context.pages}, context
    )
    action = repair_config_module.load_repair_config(
        None, controller.detector_kinds()
    ).actions[region_repair.NAME]
    verdict = region_repair.admits(issue, candidate, action, context)
    inventory = fixed_assets.build_inventory(
        document, article_document_ir=article_ir, run_trace=trace
    )
    transaction = TransactionSnapshot.capture(
        document, run_trace=trace, fixed_inventory=inventory
    )
    before_generation = trace.current_generation
    transaction.begin_generation("handler_region")
    typesetter = Typesetting(
        translator.translation_config,
        font_mapper=translator.il_translator.font_mapper,
    )
    result = controller.article_flow.retypeset_existing_article_region(
        document,
        article_ir,
        trace,
        inventory,
        slots_plan,
        article_id="article-a",
        page_number=1,
        generation=trace.current_generation,
        typesetter=typesetter,
    )
    committed = strict_commit(
        transaction,
        issue,
        RepairAction.RETYPESET_ARTICLE_REGION,
        result.touched_refs,
    )
    check(
        "retypeset region uses existing targets/legal slots and strictly commits",
        verdict == actions.ACCEPTED
        and result.touched_refs
        and committed
        and trace.current_generation == before_generation + 1,
    )
    no_slots = copy.copy(context)
    no_slots.legal_slot_plan = None
    check(
        "retypeset region refuses a target without canonical legal slots",
        region_repair.admits(issue, candidate, action, no_slots)
        == region_repair.REASON_SLOT,
    )


def minimal_state() -> RepairKnowledgeState:
    digest = "0" * 64
    issue = RepairIssueEvidence(
        issue_id="residue:p1:p1#0",
        kind=RepairIssueKind.UNTRANSLATED_RESIDUE,
        physical_page=1,
        article_refs=("article-a",),
        element_refs=("p1#0",),
        text_excerpt="source",
        metric_vector=(("residue_chars", 12),),
    )
    return RepairKnowledgeState(
        document_semantic_sha256=digest,
        physical_page_selection_sha256=digest,
        article_knowledge_state_sha256=digest,
        run_trace_generation=0,
        issues=(issue,),
        page_policies=((1, digest),),
        article_regions=(("article-a", ("slot-a",)),),
        element_roles=(("p1#0", ElementRole.BODY),),
        chain_states=(),
        legal_slot_digests=(("slot-a", digest),),
        fixed_asset_inventory_sha256=digest,
        manual_constraint_refs=(),
        protected_refs=(),
        allowed_actions=(RepairAction.NO_ACTION, RepairAction.REPROCESS_OMITTED_TEXT),
        action_detector_closure_version="repair-detector-closure.v1",
        limits=(("max_actions", 1),),
    )


def check_closed_boundaries() -> None:
    state = minimal_state()
    stale = RepairDecision(
        action=RepairAction.REPROCESS_OMITTED_TEXT,
        issue_ids=("residue:p1:p1#0",),
        target=RepairTarget(
            physical_pages=(1,),
            article_refs=("article-a",),
            element_refs=("p1#0",),
            legal_slot_refs=("slot-a",),
        ),
        parameters=(("max_paragraphs", 1),),
        state_sha256="1" * 64,
    )
    try:
        state.preflight(stale)
    except StaleRepairStateError:
        stale_refused = True
    else:
        stale_refused = False
    no_action = RepairDecision(
        action=RepairAction.NO_ACTION,
        issue_ids=(),
        target=RepairTarget(),
        parameters=(),
        state_sha256=state.sha256(),
    )
    state.preflight(no_action)
    check("stale repair state is refused before a handler runs", stale_refused)
    check(
        "no_action is targetless, parameterless, and produces no mutation",
        no_action.action is RepairAction.NO_ACTION and not no_action.issue_ids,
    )

    document, article_ir, slots_plan, trace = article_fixture()
    unsupported_article = ArticleIR(
        article_id="article-a",
        pages=article_ir.articles[0].pages,
        elements=article_ir.articles[0].elements,
        slots=tuple(slot for slot in article_ir.articles[0].slots if slot.page != 2),
        chain_ids=(),
        policy_evidence=article_ir.articles[0].policy_evidence,
    )
    unsupported_ir = ArticleDocumentIR(
        articles=(unsupported_article,),
        by_page={1: "article-a", 2: "article-a"},
        by_element=dict(article_ir.by_element),
        by_chain={},
        unsupported_pages=(UnsupportedArticlePage(2, "multiple_articles", ("p2#0",)),),
    )
    unsupported_context = context_for(
        document, unsupported_ir, plan_legal_slots(unsupported_ir), trace
    )
    issue = finding(
        "untranslated_residue",
        2,
        ("p2#0",),
        {"residue_ratio": 1.0, "layout_label": "fallback_line", "residue_chars": 12},
        "residue",
    )
    action = repair_config_module.load_repair_config(
        None, controller.detector_kinds()
    ).actions[actions.NAME]
    candidate = actions.resolve(
        issue, {view.label: view for view in unsupported_context.pages}
    )
    check(
        "unsupported same-page multi-article scope remains unavailable",
        actions.admits_candidate(issue, candidate, action, unsupported_context)
        == actions.REASON_UNSUPPORTED,
    )

    decision = SimpleNamespace(
        issue_ids=(issue.id,), parameters={"max_paragraphs": 1}
    )
    handler = controller.Handler(
        paragraphs_per_finding=1,
        resolve=lambda selected, pages, _context: actions.resolve(
            selected, pages
        ),
        admits=actions.admits_candidate,
        apply=None,
    )

    def candidates(*, drop_caps=(), fixed=(), applications=0):
        probe = SimpleNamespace(
            protected_drop_cap_refs=frozenset(drop_caps),
            fixed_inventory=SimpleNamespace(
                protected_paragraph_refs=frozenset(fixed)
            ),
            applications=applications,
        )
        return controller.RepairLoop._candidates(
            probe,
            [issue],
            decision,
            action,
            context_for(document, article_ir, slots_plan, trace),
            handler,
        )

    _accepted, protected = candidates(drop_caps=("p2#0",))
    _accepted, fixed = candidates(fixed=("p2#0",))
    _accepted, limited = candidates(applications=action.max_applications)
    check(
        "protected roles and fixed assets are refused before handler execution",
        protected[0].reason == actions.REASON_PROTECTED_DROP_CAP
        and fixed[0].reason == actions.REASON_FIXED_ASSET,
    )
    check(
        "per-action application ceiling refuses partial work",
        limited[0].reason == actions.REASON_CEILING,
    )


class CollisionTypesetter(SafeTypesetter):
    @staticmethod
    def render_paragraph(paragraph, page_value, _fonts) -> None:
        neighbour = page_value.pdf_paragraph[1]
        other_box = neighbour.pdf_paragraph_composition[0].pdf_character.box
        paragraph.pdf_paragraph_composition = [
            il.PdfParagraphComposition(
                pdf_character=character(
                    "X", other_box.x, other_box.y, 5.0, 10.0
                )
            )
        ]


class QueuedRound:
    def __init__(self, action_name: str) -> None:
        self.action_name = action_name

    def decide(self, offered, state_sha256=None):
        action = repair_config_module.load_repair_config(
            None, controller.detector_kinds()
        ).actions[self.action_name]
        return (
            decide.Decision(
                action=self.action_name,
                issue_ids=(offered[0].id,),
                parameters=action.resolve({"max_paragraphs": 1}),
                reason="deterministic fixture",
            ),
            decide.RequestLog(),
        )


class OrchestrationLoop(controller.RepairLoop):
    def __init__(self, *args, issue_passes, action_queue, **kwargs):
        self._issue_passes = list(issue_passes)
        self._action_queue = list(action_queue)
        super().__init__(*args, **kwargs)

    def _detect(self, iteration: int):
        issues = self._issue_passes.pop(0)
        return issues, context_for(
            self.docs,
            self.article_document_ir,
            self.legal_slot_plan,
            self.run_trace,
        )

    def _round_client(self, _kind: str):
        return QueuedRound(self._action_queue.pop(0))


class FixtureTranslationConfig:
    def __init__(self, work: Path) -> None:
        self.translator = object()
        self.lang_in = "zh"
        self.lang_out = "en"
        self.shared_context_cross_split_part = SimpleNamespace(
            user_glossaries=[]
        )
        self.magazine_article_context = False
        self.magazine_hitl_apply = False
        self.ignore_cache = True
        self.work = work

    def get_working_file_path(self, name: str) -> Path:
        return self.work / name


class FixtureArticleStateJournal:
    """Copy-safe journal adapter retaining the canonical immutable states."""

    def __init__(self, initial) -> None:
        self.states = (initial,)
        self.context_records = ()

    def capture_repair_checkpoint(self):
        previous = self.states[-1]
        state = replace(
            previous,
            generation=previous.generation + 1,
            previous_generation=previous.generation,
            stage=ArticleStateStage.TYPESET,
            reason="REPAIR_ACTION_COMMITTED",
            run_trace_generation=previous.run_trace_generation + 1,
            state_sha256="",
        )
        state = replace(state, state_sha256=digest_record(state.material()))
        self.states = (*self.states, state)
        return state


def check_orchestration() -> None:
    document, article_ir, slots_plan, trace = article_fixture()
    heading = finding(
        "out_of_page",
        1,
        ("p1#0",),
        {
            "overflow_max": 16.0,
            "overflow_ratio": 0.1,
            "layout_label": "title",
        },
        "page_bounds",
    )
    omitted = finding(
        "untranslated_residue",
        2,
        ("p2#0",),
        {"residue_ratio": 1.0, "layout_label": "fallback_line", "residue_chars": 12},
        "residue",
    )
    induced = finding(
        "text_text_collision",
        2,
        ("p2#0", "p2#1"),
        {
            "coverage": 1.0,
            "iou": 0.1,
            "source_coverage": 0.0,
            "source_iou": 0.0,
            "overlap_area": 50.0,
        },
        "collision",
    )
    work = Path(tempfile.mkdtemp(prefix="babeldoc-c19-handlers-"))
    config = FixtureTranslationConfig(work)
    inventory = fixed_assets.build_inventory(
        document, article_document_ir=article_ir, run_trace=trace
    )
    journal = ArticleStateJournal(
        config, document, article_ir, trace, inventory, slots_plan
    )
    initial_state = journal.capture(ArticleStateStage.TYPESET)
    fixture_journal = FixtureArticleStateJournal(initial_state)
    transport = OneReplyTransport("translated body copy")
    translator = actions.CachedOrphanTranslator(
        repair_config_module.load_repair_config(None, controller.detector_kinds()),
        transport=transport,
        cache=OfflineCache(),
        identity="offline-orchestration",
        language="en",
        working_dir=ROOT,
        ignore_cache=True,
    )
    loop = OrchestrationLoop(
        config,
        document,
        translator=translator,
        run_trace=trace,
        source_geometry=SimpleNamespace(
            boxes={}, stage="fixture", path="fixture.xml"
        ),
        fixed_inventory=inventory,
        article_document_ir=article_ir,
        article_state_journal=fixture_journal,
        legal_slot_plan=slots_plan,
        issue_passes=([heading, omitted], [omitted], [induced]),
        action_queue=(contain.NAME, actions.NAME),
    )
    loop.typesetting = CollisionTypesetter()
    before_omitted = copy.deepcopy(document.page[1].pdf_paragraph[0])
    residual = loop.run()
    report = json.loads((work / controller.REPORT_NAME).read_text(encoding="utf-8"))
    statuses = [item["action_status"] for item in report["iterations"]]
    xml = XMLConverter().to_xml(document)
    check(
        "two-page high-level fixture commits one action per iteration",
        statuses == [controller.ACTION_COMMITTED, controller.ACTION_ROLLED_BACK]
        and report["iterations"][0]["transaction"]["generation"] == 1
        and trace.current_generation == 1
        and len(fixture_journal.states) == 2,
        str(statuses),
    )
    check(
        "new collision rolls back the complete second action and stops",
        report["stopped_because"] == controller.STOP_NOT_CONVERGING
        and document.page[1].pdf_paragraph[0] == before_omitted
        and residual[0].id == omitted.id
        and report["iterations"][1]["new_ids"] == [induced.id],
    )
    check(
        "orchestration output remains serializable with fixed image and residual",
        bool(xml)
        and len(document.page) == 2
        and all(page_value.pdf_figure for page_value in document.page)
        and report["final_untreated"],
    )


def main() -> int:
    check_vocabulary()
    check_omitted_handler()
    check_heading_handler()
    check_collision_handler()
    check_chain_handler()
    check_region_handler()
    check_closed_boundaries()
    check_orchestration()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} repair handler checks")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(f"PASS: {CHECKS} repair handler checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
