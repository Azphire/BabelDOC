from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import article_flow
from babeldoc.magazine import cross_page_reflow
from babeldoc.magazine import fixed_assets
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph
from tests.minimal.fakes import document_digest
from tests.minimal.test_article_flow_column import FLOW_CONFIG
from tests.minimal.test_article_flow_column import FLOW_TARGET
from tests.minimal.test_article_flow_column import boundary
from tests.minimal.test_article_flow_column import canonical_ir
from tests.minimal.test_article_flow_column import cross_segment
from tests.minimal.test_article_flow_column import flow_runtime
from tests.minimal.test_article_flow_column import flow_slot
from tests.minimal.test_article_flow_column import local_segment
from tests.minimal.test_article_flow_column import region_slot
from tests.minimal.test_article_flow_column import source_element


def connection_fixture():
    left = _paragraph("left", "left", (0.0, 0.0, 25.0, 15.0))
    right = _paragraph("right", "right", (0.0, 0.0, 25.0, 15.0))
    document = il_version_1.Document(
        page=[_page(0, [left]), _page(1, [right])], total_pages=2
    )
    elements = (
        source_element("p1#0", page=1, column=0, reading_order=0),
        source_element("p2#0", page=2, column=0, reading_order=1),
    )
    slots = (
        region_slot(page=1, column=0, slot_order=0, box=(0.0, 0.0, 25.0, 15.0)),
        region_slot(page=2, column=0, slot_order=1, box=(0.0, 0.0, 25.0, 15.0)),
    )
    article_document_ir = canonical_ir(elements, slots)
    inventory = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    return document, article_document_ir, article_document_ir.articles[0], inventory


def two_page_manual_segment(document, article_document_ir, target=FLOW_TARGET):
    left_boundary = boundary(
        document.page[0].pdf_paragraph[0], target=target, suffix="cross-page"
    )
    left = local_segment(
        page=1,
        source_refs=("p1#0",),
        slots=(flow_slot(page=1, column=0, order=0, suffix="page-1"),),
        boundaries=(left_boundary,),
        suffix="page-1",
    )
    right = local_segment(
        page=2,
        source_refs=("p2#0",),
        slots=(flow_slot(page=2, column=0, order=1, suffix="page-2"),),
        boundaries=(),
        suffix="page-2",
    )
    return cross_segment((left, right), document, article_document_ir)


def test_zero_based_physical_adjacent_pages_connect_and_conserve_target(
    monkeypatch, tmp_path
):
    document, article_document_ir, article, inventory = connection_fixture()
    assert (
        cross_page_reflow.page_connection_issue(
            document, article_document_ir, article, 1, 2, inventory
        )
        is None
    )
    unified = two_page_manual_segment(document, article_document_ir)
    monkeypatch.setattr(
        cross_page_reflow,
        "build_cross_page_segments",
        lambda *_args, **_kwargs: ((unified,), ()),
    )
    config, typesetter = flow_runtime(tmp_path)

    report = cross_page_reflow.apply(
        config,
        document,
        article_document_ir,
        typesetter=typesetter,
        config=FLOW_CONFIG,
    )

    result = report["cross_page_segments"][0]
    assert result["status"] == "applied"
    assert [item["page"] for item in result["placements"]] == [1, 2]
    assert report["totals"]["cross_page_movements"] == 1
    assert "".join(page.pdf_paragraph[0].unicode for page in document.page) == FLOW_TARGET


def test_page_connection_rejections_are_typed(tmp_path):
    document, article_document_ir, article, inventory = connection_fixture()

    document.page[1].page_number = 2
    issue = cross_page_reflow.page_connection_issue(
        document, article_document_ir, article, 1, 2, inventory
    )
    assert issue.detail == cross_page_reflow.BOUNDARY_NON_ADJACENT
    document.page[1].page_number = 1

    issue = cross_page_reflow.page_connection_issue(
        document, article_document_ir, article, 1, 3, inventory
    )
    assert issue.detail == cross_page_reflow.BOUNDARY_NON_ADJACENT

    wrong_owner = SimpleNamespace(
        by_page={1: "article-1", 2: "article-2"}, unsupported_pages=()
    )
    issue = cross_page_reflow.page_connection_issue(
        document, wrong_owner, article, 1, 2, inventory
    )
    assert issue.code == cross_page_reflow.ISSUE_PAGE_OWNERSHIP_CONFLICT

    discontinuous = replace(
        article,
        elements=(article.elements[0], replace(article.elements[1], reading_order=3)),
    )
    issue = cross_page_reflow.page_connection_issue(
        document, article_document_ir, discontinuous, 1, 2, inventory
    )
    assert issue.detail == cross_page_reflow.BOUNDARY_READING_ORDER

    denied = replace(
        article,
        policy_evidence=(
            article.policy_evidence[0],
            replace(article.policy_evidence[1], article_reflow_allowed=False),
        ),
    )
    issue = cross_page_reflow.page_connection_issue(
        document, article_document_ir, denied, 1, 2, inventory
    )
    assert issue.detail == cross_page_reflow.BOUNDARY_POLICY

    unsupported = SimpleNamespace(
        by_page=article_document_ir.by_page,
        unsupported_pages=(SimpleNamespace(page=2),),
    )
    issue = cross_page_reflow.page_connection_issue(
        document, unsupported, article, 1, 2, inventory
    )
    assert issue.detail == cross_page_reflow.BOUNDARY_UNSUPPORTED

    issue = cross_page_reflow.page_connection_issue(
        document, article_document_ir, replace(article, slots=()), 1, 2, inventory
    )
    assert issue.detail == cross_page_reflow.BOUNDARY_SOURCE_GEOMETRY

    document.page[0].pdf_paragraph[0].vertical = True
    protected_inventory = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    _config, typesetter = flow_runtime(tmp_path)
    _segments, issues = cross_page_reflow.build_cross_page_segments(
        document,
        article_document_ir,
        protected_inventory,
        FLOW_CONFIG,
        typesetter,
    )
    assert any(
        issue.detail == cross_page_reflow.BOUNDARY_NO_SLOT for issue in issues
    )


def test_capacity_exhaustion_restores_all_touched_pages(monkeypatch, tmp_path):
    document, article_document_ir, _article, _inventory = connection_fixture()
    target = "甲" * 40
    unified = two_page_manual_segment(document, article_document_ir, target)
    monkeypatch.setattr(
        cross_page_reflow,
        "build_cross_page_segments",
        lambda *_args, **_kwargs: ((unified,), ()),
    )
    config, typesetter = flow_runtime(tmp_path)
    before = document_digest(document)

    report = cross_page_reflow.apply(
        config,
        document,
        article_document_ir,
        typesetter=typesetter,
        config=FLOW_CONFIG,
    )

    assert document_digest(document) == before
    result = report["cross_page_segments"][0]
    assert result["status"] == "rolled_back"
    assert result["reason"] == cross_page_reflow.ISSUE_CAPACITY_EXHAUSTION
    assert result["snapshot"]["status"] == "rolled_back"


def test_flow_owned_refs_commit_incrementally_and_rollback_does_not_leak(
    monkeypatch, tmp_path
):
    paragraph = _paragraph(FLOW_TARGET, "body", (0.0, 0.0, 25.0, 15.0))
    document = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    article_document_ir = canonical_ir(
        (source_element("p1#0", page=1, column=0, reading_order=0),),
        (
            region_slot(
                page=1, column=0, slot_order=0, box=(0.0, 0.0, 25.0, 15.0)
            ),
            region_slot(
                page=1, column=1, slot_order=1, box=(60.0, 0.0, 85.0, 15.0)
            ),
        ),
    )
    segments = []
    for index in range(3):
        local = local_segment(
            page=1,
            source_refs=("p1#0",),
            slots=(
                flow_slot(
                    page=1, column=0, order=0, suffix=f"{index}-left"
                ),
                flow_slot(
                    page=1,
                    column=1,
                    order=1,
                    suffix=f"{index}-right",
                    box=(60.0, 0.0, 85.0, 15.0),
                ),
            ),
            boundaries=(boundary(paragraph, suffix=str(index)),),
            suffix=str(index),
        )
        segments.append(cross_segment((local,), document, article_document_ir))
    monkeypatch.setattr(
        cross_page_reflow,
        "build_cross_page_segments",
        lambda *_args, **_kwargs: (tuple(segments), ()),
    )
    original_validate = cross_page_reflow._validate_written_targets
    calls = 0

    def reject_third(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            return [article_flow.GUARD_TARGET_CONSERVATION]
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(cross_page_reflow, "_validate_written_targets", reject_third)
    config, typesetter = flow_runtime(tmp_path)

    report = cross_page_reflow.apply(
        config,
        document,
        article_document_ir,
        typesetter=typesetter,
        config=FLOW_CONFIG,
    )

    first, second, rolled_back = report["cross_page_segments"]
    assert first["status"] == second["status"] == "applied"
    assert first["committed_flow_owned_refs"] == ["p1#1"]
    assert second["committed_flow_owned_refs"] == ["p1#1", "p1#2"]
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["committed_flow_owned_refs"] == ["p1#1", "p1#2"]
    assert len(document.page[0].pdf_paragraph) == 3
    final_inventory = fixed_assets.build_inventory(
        document,
        article_document_ir=article_document_ir,
        flow_owned_paragraph_refs=("p1#1", "p1#2"),
    )
    assert not final_inventory.protected_paragraph_refs
