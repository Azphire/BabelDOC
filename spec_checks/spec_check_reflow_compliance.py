"""Offline checks for trace-backed reflow compliance findings."""

from __future__ import annotations

import sys
from pathlib import Path

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import fixed_assets  # noqa: E402
from babeldoc.magazine import run_trace  # noqa: E402
from babeldoc.magazine.article_ir import ArticleChain  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticlePolicyEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ArticleRegionSlot  # noqa: E402
from babeldoc.magazine.article_ir import ChainHeadStartEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ChainSourceRange  # noqa: E402
from babeldoc.magazine.article_ir import ChainTailEndEvidence  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.detectors import abnormal_blank  # noqa: E402
from babeldoc.magazine.detectors import article_ownership  # noqa: E402
from babeldoc.magazine.detectors import base  # noqa: E402
from babeldoc.magazine.detectors import chain_conservation  # noqa: E402
from babeldoc.magazine.detectors import drop_cap_geometry  # noqa: E402
from babeldoc.magazine.detectors import fixed_asset_drift  # noqa: E402
from babeldoc.magazine.detectors import instruction_compliance  # noqa: E402
from babeldoc.magazine.detectors import render_coverage  # noqa: E402
from spec_checks.delivery_commits import delivery_files  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0
CONFIG = detectors.detector_config()


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"PASS: {name}")
    else:
        FAILURES.append(f"{name}: {detail or 'condition was false'}")
        print(f"FAIL: {name} :: {detail or 'condition was false'}")


def box(x: float, y: float, x2: float, y2: float) -> il_version_1.Box:
    return il_version_1.Box(x=x, y=y, x2=x2, y2=y2)


def document() -> il_version_1.Document:
    return il_version_1.Document(
        page=[
            il_version_1.Page(
                page_number=0,
                pdf_paragraph=[],
                pdf_figure=[],
                cropbox=il_version_1.Cropbox(box=box(0.0, 0.0, 100.0, 100.0)),
                mediabox=il_version_1.Mediabox(box=box(0.0, 0.0, 100.0, 100.0)),
            )
        ],
        total_pages=1,
    )


class SourceGeometry:
    stage = "styles_and_formulas"
    path = "fixture.xml"

    @staticmethod
    def box_for(_reference):
        return None


def element(reference: str, order: int) -> SourceElementRef:
    page, _index = run_trace.parse_source_ref(reference)
    return SourceElementRef(
        source_ref=reference,
        page=page,
        column=0,
        reading_order=order,
        role="text",
        source_box=(0.0, 0.0, 100.0, 100.0),
        source_text_hash=run_trace.hash_text(reference),
        style_hash=run_trace.hash_record({"style": "body"}),
    )


def article_state(
    references=("p1#0", "p1#1"),
    *,
    allowed: bool = True,
) -> ArticleDocumentIR:
    elements = tuple(element(reference, index) for index, reference in enumerate(references))
    has_chain = len(references) >= 2
    article = ArticleIR(
        article_id="article-a",
        pages=(1,),
        elements=elements,
        slots=(
            ArticleRegionSlot(
                article_id="article-a",
                page=1,
                column=0,
                slot_order=0,
                box=(0.0, 0.0, 100.0, 100.0),
                fixed_obstacle_refs=(),
                capacity_hint=100.0,
            ),
        ),
        chain_ids=(("chain-a",) if has_chain else ()),
        policy_evidence=(
            ArticlePolicyEvidence(
                page=1,
                role="member",
                page_kind="fixture",
                reason=None,
                article_reflow_allowed=allowed,
            ),
        ),
    )
    return ArticleDocumentIR(
        articles=(article,),
        by_page={1: "article-a"},
        by_element=dict.fromkeys(references, "article-a"),
        by_chain=({"chain-a": "article-a"} if has_chain else {}),
        by_chain_member=(
            dict.fromkeys(references, "chain-a") if has_chain else {}
        ),
        chains=((
            ArticleChain(
                chain_id="chain-a",
                article_id="article-a",
                ordered_member_refs=tuple(references),
                source_ranges=tuple(
                    ChainSourceRange(
                        source_ref=reference,
                        start=0,
                        end=len(reference),
                        source_sha256=run_trace.hash_text(reference),
                    )
                    for reference in references
                ),
                member_physical_pages=tuple(1 for _reference in references),
                head_start_evidence=(
                    ChainHeadStartEvidence.NOT_APPLICABLE_SAME_PAGE_COLUMN
                ),
                tail_end_evidence=(
                    ChainTailEndEvidence.NOT_APPLICABLE_SAME_PAGE_COLUMN
                ),
                decision_reason="synthetic_fixture",
            ),
        ) if has_chain else ()),
    )


def add_source(trace: run_trace.RunTrace, reference: str) -> None:
    page, index = run_trace.parse_source_ref(reference)
    trace.register_source(
        reference,
        page=page,
        index=index,
        source_box=(0.0, 0.0, 100.0, 100.0),
        text_hash=run_trace.hash_text(reference),
        style_hash=run_trace.hash_record({"style": "body"}),
        article_id="article-a",
        chain_id="chain-a",
    )


def complete_chain() -> tuple[run_trace.RunTrace, str, tuple[str, str]]:
    trace = run_trace.RunTrace()
    add_source(trace, "p1#0")
    add_source(trace, "p1#1")
    request_id = trace.open_request(
        "continuity_chain",
        ("p1#0", "p1#1"),
        "source",
        {"prompt": "fixture"},
    )
    trace.record_translator_call(request_id)
    fragments = tuple(
        trace.complete_request_with_fragments(
            request_id,
            (("p1#0", "甲"), ("p1#1", "乙")),
        )
    )
    trace.record_chain_outcome(
        "chain-a",
        ("p1#0", "p1#1"),
        run_trace.ChainResultState.JOINT_SUCCESS,
        request_id=request_id,
        translator_call_count=1,
    )
    for index, fragment_id in enumerate(fragments):
        trace.register_typeset_geometry(
            fragment_id,
            slot_id=f"slot-{index}",
            pre_repair_box=(0.0, index * 40.0, 100.0, index * 40.0 + 35.0),
        )
        trace.bind_final_geometry(
            fragment_id,
            final_page=1,
            final_box=(0.0, index * 40.0, 100.0, index * 40.0 + 35.0),
            binding_id=f"binding-{index}",
        )
    trace.finalize_sources()
    return trace, request_id, fragments


def inventory(*assets: fixed_assets.AssetRecord) -> fixed_assets.FixedAssetInventory:
    return fixed_assets.FixedAssetInventory(
        assets=tuple(sorted(assets, key=lambda item: item.reference)),
        page_sizes=((1, (0.0, 0.0, 100.0, 100.0), (0.0, 0.0, 100.0, 100.0)),),
    )


def asset(
    reference="p1:pdf_figure#0",
    *,
    bbox=(0.0, 0.0, 50.0, 100.0),
    digest="digest-a",
) -> fixed_assets.AssetRecord:
    return fixed_assets.AssetRecord(
        reference=reference,
        asset_type="pdf_figure",
        page=1,
        bbox=bbox,
        digest=digest,
        movable=False,
        protected=True,
    )


def context(
    trace=None,
    article_ir=None,
    before=None,
    after=None,
    *,
    docs=None,
) -> base.DetectionContext:
    docs = document() if docs is None else docs
    return base.DetectionContext(
        pages=[
            base.PageView(
                label=1,
                page=docs.page[0],
                policy={"repair_profile": "flow", "translate": True},
            )
        ],
        config=CONFIG,
        language="zh",
        source_geometry=SourceGeometry(),
        article_document_ir=article_ir,
        run_trace=trace,
        fixed_inventory=before,
        current_inventory=after,
        finalized=True,
    )


def check_article_ownership() -> None:
    trace, _request_id, fragments = complete_chain()
    trace.sources["p1#0"].article_id = "article-b"
    geometry = next(
        trace.geometries[item]
        for item in trace.fragments[fragments[1]].geometry_ids
        if trace.geometries[item].active
    )
    geometry.final_page = 2
    issues = article_ownership.detect(context(trace, article_state()))
    reasons = {reason for issue in issues for reason in issue.evidence["reasons"]}
    check(
        "article ownership reports wrong article and page",
        {
            "source_article_differs_from_canonical_owner",
            "geometry_page_is_outside_article",
        }.issubset(reasons),
        str(sorted(reasons)),
    )


def conservation_reasons(mutator) -> dict:
    trace, request_id, fragments = complete_chain()
    mutator(trace, request_id, fragments)
    issues = chain_conservation.detect(context(trace, article_state()))
    return {} if not issues else issues[0].evidence


def check_chain_conservation() -> None:
    complete, _request_id, _fragments = complete_chain()
    check(
        "complete ordered chain target passes",
        not chain_conservation.detect(context(complete, article_state())),
    )
    missing = conservation_reasons(
        lambda trace, request_id, fragments: trace.requests[
            request_id
        ].fragment_ids.remove(fragments[1])
    )
    duplicate = conservation_reasons(
        lambda trace, _request_id, fragments: setattr(
            trace.fragments[fragments[1]], "order", 0
        )
    )

    def reverse_sources(trace, _request_id, fragments):
        trace.fragments[fragments[0]].source_ref = "p1#1"
        trace.fragments[fragments[1]].source_ref = "p1#0"

    unordered = conservation_reasons(reverse_sources)
    check("missing chain fragment is reported", missing.get("gap_chars", 0) > 0)
    check(
        "duplicate chain fragment order is reported",
        duplicate.get("duplicate_order_count", 0) > 0,
    )
    check(
        "out-of-order chain fragments are reported",
        unordered.get("out_of_order_count", 0) > 0,
    )


def check_render_coverage() -> None:
    trace = run_trace.RunTrace()
    add_source(trace, "p1#0")
    request_id = trace.open_request(
        "paragraph_batch", ("p1#0",), "source", {"prompt": "fixture"}
    )
    trace.record_translator_call(request_id)
    fragment_id = trace.complete_request_with_fragments(
        request_id, (("p1#0", "target"),)
    )[0]
    trace.register_typeset_geometry(
        fragment_id,
        slot_id="slot-a",
        pre_repair_box=(0.0, 0.0, 50.0, 20.0),
    )
    issues = render_coverage.detect(context(trace, article_state(("p1#0",))))
    reasons = {issue.evidence["reason"] for issue in issues}
    check(
        "source and fragment missing final states are explicit",
        {"source_terminal_state_missing", "fragment_terminal_state_missing"}
        == reasons,
        str(sorted(reasons)),
    )
    trace.sources["p1#0"].terminal_state = run_trace.SourceTerminalState.RENDERED
    trace.fragments[fragment_id].terminal_state = run_trace.SourceTerminalState.RENDERED
    issues = render_coverage.detect(context(trace, article_state(("p1#0",))))
    check(
        "rendered fragment without final geometry is explicit",
        any(issue.evidence["reason"] == "final_geometry_missing" for issue in issues),
    )


def flow_blank_trace() -> run_trace.RunTrace:
    trace = run_trace.RunTrace()
    generation = trace.begin_repair_generation("fixture")
    trace.record_flow_slot(
        generation,
        slot_id="slot-a:released",
        article_id="article-a",
        page=1,
        status="released",
        box=(0.0, 0.0, 50.0, 100.0),
        reason="unused_page_local_capacity",
    )
    trace.commit_generation(generation)
    return trace


def check_abnormal_blank() -> None:
    empty = inventory()
    blank = abnormal_blank.detect(
        context(flow_blank_trace(), article_state(), empty, empty)
    )
    covered = inventory(asset())
    image = abnormal_blank.detect(
        context(flow_blank_trace(), article_state(), covered, covered)
    )
    designed = abnormal_blank.detect(
        context(run_trace.RunTrace(), article_state(), empty, empty)
    )
    boundary = abnormal_blank.detect(
        context(flow_blank_trace(), article_state(allowed=False), empty, empty)
    )
    check(
        "flow-created blank is normalized and reported",
        len(blank) == 1
        and blank[0].evidence["blank_area_ratio"] == 0.5
        and blank[0].evidence["blank_capacity_ratio"] == 0.5,
        str([issue.evidence for issue in blank]),
    )
    check(
        "fixed image, design whitespace, and hard boundary are excluded",
        not image and not designed and not boundary,
        f"image={len(image)} design={len(designed)} boundary={len(boundary)}",
    )


def check_fixed_asset_drift() -> None:
    before = inventory(asset())
    changed = inventory(asset(bbox=(1.0, 0.0, 51.0, 100.0), digest="digest-b"))
    issues = fixed_asset_drift.detect(context(before=before, after=changed))
    reasons = {issue.evidence["reason"] for issue in issues}
    ids = {issue.id for issue in issues}
    removed = fixed_asset_drift.detect(context(before=before, after=inventory()))
    check(
        "fixed asset bbox and digest drift are separate stable findings",
        reasons == {"bbox_changed", "digest_changed"}
        and len(ids) == len(issues),
        str([issue.evidence for issue in issues]),
    )
    check(
        "fixed asset count drift is reported",
        len(removed) == 1
        and removed[0].evidence["count_before"] == 1
        and removed[0].evidence["count_after"] == 0,
    )


def check_instruction_compliance() -> None:
    trace, request_id, _fragments = complete_chain()
    trace.requests[request_id].translator_call_count = 2
    trace.chain_outcomes["chain-a"].translator_call_count = 2
    issues = instruction_compliance.detect(context(trace, article_state()))
    check(
        "joint call count noncompliance is reported",
        any(issue.evidence["instruction"] == "joint_call_count" for issue in issues),
    )
    generation = trace.begin_repair_generation("rollback-fixture")
    trace.rollback_generation(generation)
    trace.generations[generation].status = run_trace.GENERATION_OPEN
    issues = instruction_compliance.detect(context(trace, article_state()))
    check(
        "unfinished rollback state is reported",
        any(issue.evidence["instruction"] == "rollback_state" for issue in issues),
    )


def check_prerequisite_and_contract() -> None:
    missing = detectors.run_detectors(context())
    prerequisite = [
        issue for issue in missing if issue.kind == detectors.PREREQUISITE_KIND
    ]
    check(
        "missing required detector inputs produce findings",
        prerequisite
        and {issue.evidence["prerequisite"] for issue in prerequisite}
        >= {"article_ir", "run_trace", "fixed_asset_inventory"},
        str([issue.as_record() for issue in prerequisite]),
    )
    contract = drop_cap_geometry.DropCapGeometryContract(
        source_ref="p1#0",
        page=1,
        article_id="article-a",
        character_count=1,
        policy="keep",
        ink=drop_cap_geometry.BoxEvidence((0.0, 0.0, 10.0, 20.0), "glyphs"),
        reserve=drop_cap_geometry.BoxEvidence((0.0, 0.0, 12.0, 20.0), "policy"),
        collision=(),
        color=drop_cap_geometry.ColorEvidence("#000000", None, 21.0),
    )
    record = contract.to_record()
    check(
        "drop-cap contract exposes character policy ink reserve collision and color",
        not record["missing_fields"]
        and {"character_count", "policy", "ink", "reserve", "collision", "color"}
        <= set(record),
    )


def check_read_only_and_deterministic() -> None:
    docs = document()
    trace, _request_id, fragments = complete_chain()
    geometry = next(
        trace.geometries[item]
        for item in trace.fragments[fragments[1]].geometry_ids
        if trace.geometries[item].active
    )
    geometry.final_page = 2
    article_ir = article_state()
    assets = fixed_assets.build_inventory(docs, run_trace=trace)
    detector_context = context(trace, article_ir, assets, assets, docs=docs)
    il_before = fixed_assets.content_digest(docs)
    trace_before = trace.transaction_digest()
    first = detectors.run_detectors(detector_context)
    second = detectors.run_detectors(detector_context)
    check(
        "detectors leave IL and RunTrace digests unchanged",
        il_before == fixed_assets.content_digest(docs)
        and trace_before == trace.transaction_digest(),
    )
    check(
        "issue ordering and IDs are deterministic",
        [issue.id for issue in first] == [issue.id for issue in second]
        and [issue.id for issue in first] == sorted(
            [issue.id for issue in first],
            key=lambda issue_id: next(
                issue.sort_key() for issue in first if issue.id == issue_id
            ),
        )
        and len({issue.id for issue in first}) == len(first),
        str([issue.id for issue in first]),
    )
    records = [issue.as_record() for issue in first]
    check(
        "every issue carries stable refs evidence severity geometry and action",
        all(
            {
                "detector",
                "page",
                "article_refs",
                "source_refs",
                "fragment_refs",
                "geometry_evidence",
                "severity_vector",
                "suggested_action_type",
            }
            <= set(record)
            and record["suggested_action_type"]
            for record in records
        ),
    )


def check_scope_and_integration() -> None:
    changed = delivery_files("C10", ROOT)
    forbidden = {
        "babeldoc/format/pdf/document_il/midend/il_translator.py",
        "babeldoc/format/pdf/document_il/il_version_1.py",
        "babeldoc/format/pdf/document_il/il_version_1.xsd",
        "babeldoc/format/pdf/document_il/il_version_1.rng",
        "babeldoc/format/pdf/document_il/il_version_1.rnc",
    }
    high_level = (ROOT / "babeldoc/format/pdf/high_level.py").read_text(
        encoding="utf-8"
    )
    check(
        "legacy translator and frozen IL schema stay untouched",
        not changed.intersection(forbidden),
        str(sorted(changed.intersection(forbidden))),
    )
    check(
        "high level passes the canonical ArticleIR into detection",
        "article_document_ir=article_document_ir" in high_level,
    )


CHECKS_TO_RUN = (
    check_article_ownership,
    check_chain_conservation,
    check_render_coverage,
    check_abnormal_blank,
    check_fixed_asset_drift,
    check_instruction_compliance,
    check_prerequisite_and_contract,
    check_read_only_and_deterministic,
    check_scope_and_integration,
)


def main() -> int:
    for operation in CHECKS_TO_RUN:
        operation()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} reflow compliance checks")
        for failure in FAILURES:
            print(f"- {failure}")
        return 1
    print(f"PASS: {CHECKS} reflow compliance checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
