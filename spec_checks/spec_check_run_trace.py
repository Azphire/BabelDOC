"""Offline contract checks for source-to-geometry RunTrace lineage."""

from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import run_trace  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from spec_checks.delivery_commits import delivery_files  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(f"{name}: {detail or 'condition was false'}")


def rejected(name: str, operation, message: str) -> None:
    try:
        operation()
    except (KeyError, ValueError) as error:
        check(name, message in str(error), str(error))
    else:
        check(name, False, "invalid operation was accepted")


def add_source(
    trace: run_trace.RunTrace,
    reference: str,
    *,
    article_id: str = "article-a",
    chain_id: str | None = None,
) -> None:
    page, index = run_trace.parse_source_ref(reference)
    trace.register_source(
        reference,
        page=page,
        index=index,
        source_box=(10.0, 20.0, 110.0, 50.0),
        text_hash=run_trace.hash_text(f"source {reference}"),
        style_hash=run_trace.hash_record({"font": "body", "size": 10.0}),
        article_id=article_id,
        chain_id=chain_id,
    )


def ordinary_trace() -> tuple[run_trace.RunTrace, str, str, str]:
    trace = run_trace.RunTrace()
    add_source(trace, "p1#0")
    request_id = trace.open_request(
        "paragraph_batch",
        ["p1#0"],
        "A source paragraph.",
        {"prompt": "private prompt material", "temperature": 0},
    )
    trace.record_translator_call(request_id)
    fragment_id = trace.complete_request_with_fragments(
        request_id, [("p1#0", "一个目标段落。")]
    )[0]
    geometry_id = trace.register_typeset_geometry(
        fragment_id,
        slot_id="slot-article-a-0",
        pre_repair_box=(10.0, 20.0, 110.0, 50.0),
        font_summary={"fonts": [{"font_id": "body", "font_size": 10.0}]},
        color_summary={"graphic_state_hashes": [run_trace.hash_text("black")]},
    )
    binding_id = "pdf-block-p1-0"
    trace.bind_final_geometry(
        fragment_id,
        final_page=1,
        final_box=(10.0, 22.0, 105.0, 48.0),
        binding_id=binding_id,
        span_ids=(f"{binding_id}:span:0",),
    )
    trace.finalize_sources()
    trace.validate(require_terminal=True)
    return trace, request_id, fragment_id, geometry_id


def check_ordinary_complete_lineage(root: Path) -> None:
    trace, request_id, fragment_id, geometry_id = ordinary_trace()
    forward = trace.trace_from_source("p1#0")
    backward = trace.trace_from_geometry("pdf-block-p1-0")
    backward_by_box = trace.trace_from_final_geometry(
        1, (10.0, 22.0, 105.0, 48.0)
    )
    check(
        "ordinary source reaches request fragment and geometry",
        forward["requests"][0]["request_id"] == request_id
        and forward["requests"][0]["fragments"][0]["fragment_id"]
        == fragment_id
        and forward["requests"][0]["fragments"][0]["geometry"][0][
            "geometry_id"
        ]
        == geometry_id,
    )
    check(
        "final geometry reverses to source",
        backward["fragment"]["fragment_id"] == fragment_id
        and backward_by_box["fragment"]["fragment_id"] == fragment_id
        and backward["request"]["request_id"] == request_id
        and [item["source_ref"] for item in backward["sources"]] == ["p1#0"],
    )
    check(
        "rendered terminal is explicit",
        forward["source"]["terminal_state"]
        == run_trace.SourceTerminalState.RENDERED.value
        and forward["requests"][0]["fragments"][0]["terminal_state"]
        == run_trace.SourceTerminalState.RENDERED.value,
    )
    payload = trace.to_json_bytes()
    path = trace.write(root / run_trace.REPORT_NAME, require_terminal=True)
    check("writer emits the stable sidecar", path.read_bytes() == payload)
    check(
        "sidecar retains hashes instead of sensitive text",
        b"private prompt material" not in payload
        and b"A source paragraph." not in payload
        and "一个目标段落。".encode() not in payload,
    )


def check_two_page_chain_fragments() -> None:
    trace = run_trace.RunTrace()
    chain_id = "chain-stable"
    add_source(trace, "p1#0", chain_id=chain_id)
    add_source(trace, "p2#0", chain_id=chain_id)
    request_id = trace.open_request(
        "continuity_chain",
        ["p1#0", "p2#0"],
        "first half second half",
        {"prompt_sha": "configuration-only"},
    )
    trace.record_translator_call(request_id)
    trace.register_whole_target(request_id, "前半后半")
    first = trace.allocate_target_fragment(
        request_id,
        "p1#0",
        order=0,
        text_start=0,
        text_end=2,
        text="前半",
    )
    second = trace.allocate_target_fragment(
        request_id,
        "p2#0",
        order=1,
        text_start=2,
        text_end=4,
        text="后半",
    )
    trace.complete_request(request_id)
    request = trace.requests[request_id]
    check(
        "two-page chain retains stable shared keys",
        request.request_kind == "continuity_chain"
        and request.ordered_source_refs == ("p1#0", "p2#0")
        and trace.sources["p1#0"].chain_id == chain_id
        and trace.sources["p2#0"].chain_id == chain_id,
    )
    check(
        "chain fragments cover the whole target in order",
        [trace.fragments[item].order for item in (first, second)] == [0, 1]
        and [
            (trace.fragments[item].text_start, trace.fragments[item].text_end)
            for item in (first, second)
        ]
        == [(0, 2), (2, 4)],
    )


def check_failure_and_protection_terminals() -> None:
    trace = run_trace.RunTrace()
    add_source(trace, "p1#0")
    add_source(trace, "p1#1")
    add_source(trace, "p1#2")
    request_id = trace.open_request(
        "paragraph_batch", ["p1#0"], "source", {"prompt": "hash me"}
    )
    trace.record_translator_call(request_id)
    trace.fail_request(request_id, "translator refused the request")
    trace.mark_source_protected("p1#1", "fixed visual asset")
    protected_request = trace.open_request(
        "paragraph_batch", ["p1#2"], "source", {"prompt": "hash me too"}
    )
    trace.record_translator_call(protected_request)
    protected_fragment = trace.complete_request_with_fragments(
        protected_request, [("p1#2", "protected target")]
    )[0]
    trace.mark_fragment_protected(protected_fragment, "protected target slot")
    trace.validate(require_terminal=True)
    check(
        "failed request has an explicit source terminal",
        trace.sources["p1#0"].terminal_state
        == run_trace.SourceTerminalState.FAILED_WITH_ISSUE
        and trace.requests[request_id].status == run_trace.REQUEST_FAILED,
    )
    check(
        "protected source has an explicit source terminal",
        trace.sources["p1#1"].terminal_state
        == run_trace.SourceTerminalState.PROTECTED
        and trace.fragments[protected_fragment].terminal_state
        == run_trace.SourceTerminalState.PROTECTED
        and trace.sources["p1#2"].terminal_state
        == run_trace.SourceTerminalState.PROTECTED,
    )


def invalid_trace() -> run_trace.RunTrace:
    trace = run_trace.RunTrace()
    add_source(trace, "p1#0")
    add_source(trace, "p1#1")
    return trace


def check_invalid_ranges_and_refs() -> None:
    trace = invalid_trace()
    rejected(
        "duplicate request source refs are rejected",
        lambda: trace.open_request(
            "paragraph_batch", ["p1#0", "p1#0"], "source", {}
        ),
        "non-empty and unique",
    )

    overlap = invalid_trace()
    overlap_request = overlap.open_request(
        "continuity_chain", ["p1#0", "p1#1"], "source", {}
    )
    overlap.register_whole_target(overlap_request, "abcd")
    overlap.allocate_target_fragment(
        overlap_request,
        "p1#0",
        order=0,
        text_start=0,
        text_end=3,
        text="abc",
    )
    rejected(
        "overlapping target ranges are rejected",
        lambda: overlap.allocate_target_fragment(
            overlap_request,
            "p1#1",
            order=1,
            text_start=2,
            text_end=4,
            text="cd",
        ),
        "must not overlap",
    )

    gap = invalid_trace()
    gap_request = gap.open_request(
        "continuity_chain", ["p1#0", "p1#1"], "source", {}
    )
    gap.record_translator_call(gap_request)
    gap.register_whole_target(gap_request, "abcd")
    gap.allocate_target_fragment(
        gap_request,
        "p1#0",
        order=0,
        text_start=0,
        text_end=1,
        text="a",
    )
    gap.allocate_target_fragment(
        gap_request,
        "p1#1",
        order=1,
        text_start=2,
        text_end=4,
        text="cd",
    )
    rejected(
        "gaps in target ranges are rejected",
        lambda: gap.complete_request(gap_request),
        "must not contain gaps",
    )


def check_generation_rollback_and_replacement() -> None:
    trace, _request_id, fragment_id, base_geometry_id = ordinary_trace()
    generation_one = trace.begin_repair_generation("repair_one")
    replacement_id = trace.register_typeset_geometry(
        fragment_id,
        slot_id="slot-article-a-0",
        pre_repair_box=(10.0, 22.0, 105.0, 48.0),
        final_page=1,
        final_box=(10.0, 24.0, 105.0, 50.0),
        generation=generation_one,
    )
    trace.commit_generation(generation_one)
    trace.rollback_generation(generation_one)
    check(
        "rollback deactivates replacement and restores old geometry",
        not trace.geometries[replacement_id].active
        and trace.geometries[base_geometry_id].active
        and trace.generations[generation_one].status
        == run_trace.GENERATION_ROLLED_BACK,
    )

    generation_two = trace.begin_repair_generation("repair_two")
    new_geometry_id = trace.register_typeset_geometry(
        fragment_id,
        slot_id="slot-article-a-0",
        pre_repair_box=(10.0, 22.0, 105.0, 48.0),
        final_page=1,
        final_box=(10.0, 26.0, 105.0, 52.0),
        generation=generation_two,
    )
    trace.commit_generation(generation_two)
    trace.bind_final_geometry(
        fragment_id,
        final_page=1,
        final_box=(10.0, 26.0, 105.0, 52.0),
        binding_id="pdf-block-p1-0-generation-two",
    )
    check(
        "a new generation can write after rollback",
        trace.geometries[new_geometry_id].active
        and not trace.geometries[base_geometry_id].active,
    )
    trace.validate(require_terminal=True)

    fragment_trace = run_trace.RunTrace()
    add_source(fragment_trace, "p1#0")
    fragment_generation = fragment_trace.begin_repair_generation(
        "replacement_translation"
    )
    fragment_request = fragment_trace.open_request(
        "repair_translation", ["p1#0"], "source", {"prompt": "repair"}
    )
    fragment_trace.record_translator_call(fragment_request)
    replacement_fragment = fragment_trace.complete_request_with_fragments(
        fragment_request,
        [("p1#0", "target")],
        generation=fragment_generation,
    )[0]
    fragment_trace.commit_generation(fragment_generation)
    fragment_trace.rollback_generation(fragment_generation)
    fragment_trace.validate()
    check(
        "rollback deactivates fragments allocated by its generation",
        not fragment_trace.fragments[replacement_fragment].active
        and fragment_trace.fragments[replacement_fragment].allocation_status
        == run_trace.ALLOCATION_INACTIVE,
    )


def deterministic_trace() -> tuple[str, bytes]:
    trace = run_trace.RunTrace()
    add_source(trace, "p1#0")
    add_source(trace, "p2#0")
    request_id = trace.open_request(
        "continuity_chain",
        ["p1#0", "p2#0"],
        "first\r\nsecond",
        {"z": 1, "a": "same"},
    )
    trace.record_translator_call(request_id)
    fragments = trace.complete_request_with_fragments(
        request_id, [("p1#0", "甲"), ("p2#0", "乙")]
    )
    for index, fragment_id in enumerate(reversed(fragments)):
        trace.register_typeset_geometry(
            fragment_id,
            slot_id=f"slot-{index}",
            pre_repair_box=(10.0, 20.0, 110.0, 50.0),
        )
    return request_id, trace.to_json_bytes()


def check_deterministic_ids_and_json() -> None:
    first_id, first_payload = deterministic_trace()
    second_id, second_payload = deterministic_trace()
    check("request ids are deterministic", first_id == second_id)
    check("JSON bytes are deterministic", first_payload == second_payload)
    check(
        "canonicalization and freeze versions are declared",
        run_trace.CANONICALIZATION_VERSION.encode() in first_payload
        and run_trace.SOURCE_REF_FREEZE_STAGE.encode() in first_payload,
    )


def check_source_ref_freeze() -> None:
    first = SimpleNamespace(
        box=SimpleNamespace(x=1.0, y=2.0, x2=3.0, y2=4.0),
        unicode="first",
        pdf_style=None,
        chain_id=None,
    )
    second = SimpleNamespace(
        box=SimpleNamespace(x=5.0, y=6.0, x2=7.0, y2=8.0),
        unicode="second",
        pdf_style=None,
        chain_id=None,
    )
    page = SimpleNamespace(pdf_paragraph=[first, second])
    trace = run_trace.RunTrace.from_document(SimpleNamespace(page=[page]))
    page.pdf_paragraph.reverse()
    check(
        "pN#k freezes immediately after structural stages",
        trace.source_ref_for(first) == "p1#0"
        and trace.source_ref_for(second) == "p1#1"
        and run_trace.SOURCE_REF_FREEZE_STAGE == "post-article-builder-v1",
    )


def check_article_and_chain_keys_are_shared() -> None:
    paragraph = SimpleNamespace(
        box=SimpleNamespace(x=1.0, y=2.0, x2=3.0, y2=4.0),
        unicode="member",
        pdf_style=None,
        chain_id="ephemeral-chain-id",
    )
    style_hash = run_trace.hash_record(
        {"font_id": None, "font_size": None, "graphic_state": None}
    )
    element = SourceElementRef(
        source_ref="p1#0",
        page=1,
        column=0,
        reading_order=0,
        role="text",
        source_box=(1.0, 2.0, 3.0, 4.0),
        source_text_hash=run_trace.hash_text("member"),
        style_hash=style_hash,
    )
    article = ArticleIR(
        article_id="article-stable",
        pages=(1,),
        elements=(element,),
        slots=(),
        chain_ids=("chain-stable",),
        policy_evidence=(),
    )
    article_document = ArticleDocumentIR(
        articles=(article,),
        by_page={1: article.article_id},
        by_element={element.source_ref: article.article_id},
        by_chain={"chain-stable": article.article_id},
        by_chain_member={element.source_ref: "chain-stable"},
    )
    trace = run_trace.RunTrace.from_document(
        SimpleNamespace(page=[SimpleNamespace(pdf_paragraph=[paragraph])]),
        article_document,
    )
    check(
        "source article and chain use canonical shared keys",
        trace.sources["p1#0"].article_id == "article-stable"
        and trace.sources["p1#0"].chain_id == "chain-stable",
    )
def changed_files() -> set[str]:
    return delivery_files("C03", ROOT)


def check_negative_and_integration_contracts() -> None:
    changed = changed_files()
    forbidden = {
        "babeldoc/format/pdf/document_il/midend/il_translator.py",
        "babeldoc/format/pdf/document_il/il_version_1.py",
        "babeldoc/format/pdf/document_il/il_version_1.xsd",
        "babeldoc/format/pdf/document_il/il_version_1.rng",
        "babeldoc/format/pdf/document_il/il_version_1.rnc",
    }
    check(
        "legacy translator and frozen IL schema are untouched",
        not changed.intersection(forbidden),
        str(sorted(changed.intersection(forbidden))),
    )
    source = inspect.getsource(run_trace)
    check("RunTrace never gates on debug_id", "debug_id" not in source)
    high_level = (ROOT / "babeldoc/format/pdf/high_level.py").read_text(
        encoding="utf-8"
    )
    llm_only = (
        ROOT
        / "babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py"
    ).read_text(encoding="utf-8")
    chain = (ROOT / "babeldoc/magazine/chain_translation.py").read_text(
        encoding="utf-8"
    )
    short_unit = (ROOT / "babeldoc/magazine/short_unit.py").read_text(
        encoding="utf-8"
    )
    check(
        "high level creates and explicitly passes one trace",
        "RunTrace.from_document(docs, article_document_ir)" in high_level
        and "run_trace=run_trace" in high_level
        and "capture_final_document(docs)" in high_level,
    )
    check(
        "all LLM-only translation routes use the unified request API",
        "open_request(" in llm_only
        and "open_request(" in chain
        and "open_request(" in short_unit
        and "write_text(" not in chain
        and "write_text(" not in short_unit,
    )
    inventory = json.loads(
        (ROOT / "configs/checkpoint_stages.json").read_text(encoding="utf-8")
    )["sidecars"]
    check(
        "the unified sidecar is declared in the run inventory",
        any(
            entry == {
                "name": run_trace.REPORT_NAME,
                "stage": "pdf_created",
                "switch": run_trace.SWITCH,
            }
            for entry in inventory
        ),
    )


CHECKS_TO_RUN = (
    check_ordinary_complete_lineage,
    check_two_page_chain_fragments,
    check_failure_and_protection_terminals,
    check_invalid_ranges_and_refs,
    check_generation_rollback_and_replacement,
    check_deterministic_ids_and_json,
    check_source_ref_freeze,
    check_article_and_chain_keys_are_shared,
    check_negative_and_integration_contracts,
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="run-trace-check-") as directory:
        root = Path(directory)
        for operation in CHECKS_TO_RUN:
            if operation is check_ordinary_complete_lineage:
                operation(root)
            else:
                operation()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} RunTrace checks")
        for failure in FAILURES:
            print(f"- {failure}")
        return 1
    print(f"PASS: {CHECKS} RunTrace checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
