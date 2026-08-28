from __future__ import annotations

from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import article_flow
from babeldoc.magazine import cross_page_reflow
from babeldoc.magazine import fixed_assets
from babeldoc.magazine import minimal_pipeline
from tests.minimal.fakes import FixedWidthMapper
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


def pipeline_fixture():
    paragraph = _paragraph("body", "body", (0.0, 0.0, 25.0, 15.0))
    document = il_version_1.Document(page=[_page(0, [paragraph])], total_pages=1)
    article_document_ir = canonical_ir(
        (source_element("p1#0", page=1, column=0, reading_order=0),),
        (region_slot(page=1, column=0, slot_order=0, box=(0.0, 0.0, 25.0, 15.0)),),
    )
    state = minimal_pipeline.MagazineState(
        _article_document_ir=article_document_ir,
        _structure_started=True,
        _structure_document_identity=id(document),
    )
    config = SimpleNamespace(magazine_state=state)
    typesetter = SimpleNamespace(translation_config=config)
    return document, article_document_ir, state, config, typesetter


def test_after_translation_order_identity_typesetter_and_success_one_shot(monkeypatch):
    document, article_document_ir, state, config, typesetter = pipeline_fixture()
    events = []
    marker = {"status": "applied"}

    monkeypatch.setattr(
        minimal_pipeline.paren_dedup,
        "apply",
        lambda held_config, held_docs: events.append(
            ("paren", held_config, held_docs)
        ),
    )
    monkeypatch.setattr(
        minimal_pipeline.indent_policy,
        "apply",
        lambda held_config, held_docs, held_ir: events.append(
            ("indent", held_config, held_docs, held_ir)
        ),
    )

    def record_flow(held_config, held_docs, held_ir, *, typesetter):
        events.append(("flow", held_config, held_docs, held_ir, typesetter))
        return marker

    monkeypatch.setattr(minimal_pipeline.article_flow, "apply", record_flow)

    report = minimal_pipeline.after_translation(config, document, typesetter)

    assert report is marker
    assert [event[0] for event in events] == ["paren", "indent", "flow"]
    assert events[1][3] is article_document_ir
    assert events[2][3] is article_document_ir
    assert events[2][4] is typesetter
    assert state.flow_started and state.flow_completed
    assert state.flow_document_identity == id(document)
    assert state.flow_report is marker
    with pytest.raises(
        minimal_pipeline.MinimalPipelineStateError,
        match="article flow was already attempted",
    ):
        minimal_pipeline.after_translation(config, document, typesetter)
    assert [event[0] for event in events] == ["paren", "indent", "flow"]


def test_failed_after_translation_propagates_and_cannot_reenter(monkeypatch):
    document, _article_document_ir, state, config, typesetter = pipeline_fixture()
    failure = RuntimeError("injected flow failure")
    monkeypatch.setattr(minimal_pipeline.paren_dedup, "apply", lambda *_args: None)
    monkeypatch.setattr(minimal_pipeline.indent_policy, "apply", lambda *_args: None)

    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(minimal_pipeline.article_flow, "apply", fail)

    with pytest.raises(RuntimeError) as raised:
        minimal_pipeline.after_translation(config, document, typesetter)

    assert raised.value is failure
    assert state.flow_started
    assert not state.flow_completed
    assert state.flow_report is None
    with pytest.raises(
        minimal_pipeline.MinimalPipelineStateError,
        match="article flow was already attempted",
    ):
        minimal_pipeline.after_translation(config, document, typesetter)


def conservation_fixture():
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
    local = local_segment(
        page=1,
        source_refs=("p1#0",),
        slots=(
            flow_slot(page=1, column=0, order=0, suffix="ledger-left"),
            flow_slot(
                page=1,
                column=1,
                order=1,
                suffix="ledger-right",
                box=(60.0, 0.0, 85.0, 15.0),
            ),
        ),
        boundaries=(boundary(paragraph, suffix="ledger"),),
        suffix="ledger",
    )
    return document, article_document_ir, cross_segment(
        (local,), document, article_document_ir
    )


def test_source_and_target_ledgers_are_separately_conserved(monkeypatch, tmp_path):
    document, article_document_ir, unified = conservation_fixture()
    monkeypatch.setattr(
        cross_page_reflow,
        "build_cross_page_segments",
        lambda *_args, **_kwargs: ((unified,), ()),
    )
    config, typesetter = flow_runtime(tmp_path)
    initial_inventory = fixed_assets.build_inventory(
        document, article_document_ir=article_document_ir
    )
    page_count = len(document.page)
    page_shell = cross_page_reflow._document_invariants(document)

    report = cross_page_reflow.apply(
        config,
        document,
        article_document_ir,
        typesetter=typesetter,
        config=FLOW_CONFIG,
    )

    result = report["cross_page_segments"][0]
    element = article_document_ir.articles[0].elements[0]
    assert result["source_ledger"] == [
        {
            "source_ref": element.source_ref,
            "owner": "article-1",
            "source_text_hash": element.source_text_hash,
            "style_hash": element.style_hash,
        }
    ]
    assert result["target_ledger"][0]["target_range"] == [0, len(FLOW_TARGET)]
    ranges = [placement["target_range"] for placement in result["placements"]]
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(FLOW_TARGET)
    assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:], strict=False))
    assert "".join(paragraph.unicode for paragraph in document.page[0].pdf_paragraph) == FLOW_TARGET
    assert len(document.page) == page_count
    assert cross_page_reflow._document_invariants(document) == page_shell
    final_inventory = fixed_assets.build_inventory(
        document,
        article_document_ir=article_document_ir,
        flow_owned_paragraph_refs=result["committed_flow_owned_refs"],
    )
    assert fixed_assets.compare(initial_inventory, final_inventory, 0.000001).holds


def test_second_writeback_failure_restores_touched_page_and_propagates(
    monkeypatch, tmp_path
):
    document, article_document_ir, unified = conservation_fixture()
    monkeypatch.setattr(
        cross_page_reflow,
        "build_cross_page_segments",
        lambda *_args, **_kwargs: ((unified,), ()),
    )
    original_composition = article_flow._composition
    attempts = 0
    failure = RuntimeError("injected second writeback failure")

    def fail_second(text, style):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise failure
        return original_composition(text, style)

    monkeypatch.setattr(article_flow, "_composition", fail_second)
    config, typesetter = flow_runtime(tmp_path)
    before = document_digest(document)

    with pytest.raises(RuntimeError) as raised:
        cross_page_reflow.apply(
            config,
            document,
            article_document_ir,
            typesetter=typesetter,
            config=FLOW_CONFIG,
        )

    assert raised.value is failure
    assert attempts == 2
    assert document_digest(document) == before


@pytest.mark.parametrize("failure_site", ("mapper", "line_packer"))
def test_unexpected_capacity_errors_restore_and_propagate(
    monkeypatch, tmp_path, failure_site
):
    document, article_document_ir, unified = conservation_fixture()
    monkeypatch.setattr(
        cross_page_reflow,
        "build_cross_page_segments",
        lambda *_args, **_kwargs: ((unified,), ()),
    )
    config, typesetter = flow_runtime(tmp_path)
    failure = RuntimeError(f"injected {failure_site} failure")
    if failure_site == "mapper":

        def explode_map(*_args, **_kwargs):
            raise failure

        monkeypatch.setattr(typesetter.font_mapper, "map", explode_map)
    else:

        def explode_layout(*_args, **_kwargs):
            raise failure

        monkeypatch.setattr(typesetter, "_layout_typesetting_units", explode_layout)
    before = document_digest(document)

    with pytest.raises(RuntimeError) as raised:
        cross_page_reflow.apply(
            config,
            document,
            article_document_ir,
            typesetter=typesetter,
            config=FLOW_CONFIG,
        )

    assert raised.value is failure
    assert document_digest(document) == before


def test_wrong_document_or_typesetter_identity_fails_before_flow():
    document, _article_document_ir, state, config, typesetter = pipeline_fixture()
    other_document = il_version_1.Document(page=list(document.page), total_pages=1)

    with pytest.raises(
        minimal_pipeline.MinimalPipelineStateError,
        match="different document",
    ):
        minimal_pipeline.after_translation(config, other_document, typesetter)
    assert not state.flow_started

    wrong_typesetter = Typesetting(
        SimpleNamespace(lang_out="zh"), font_mapper=FixedWidthMapper()
    )
    with pytest.raises(
        minimal_pipeline.MinimalPipelineStateError,
        match="different translation config",
    ):
        minimal_pipeline.after_translation(config, document, wrong_typesetter)
    assert not state.flow_started
