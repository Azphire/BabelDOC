"""Offline checks for monotonic acceptance and atomic repair transactions."""

from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

cache_stub = types.ModuleType("babeldoc.translator.cache")
cache_stub.TranslationCache = type("TranslationCache", (), {})
sys.modules.setdefault("babeldoc.translator.cache", cache_stub)

react_package = types.ModuleType("babeldoc.magazine.react")
react_package.__path__ = [str(ROOT / "babeldoc" / "magazine" / "react")]
sys.modules.setdefault("babeldoc.magazine.react", react_package)

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import acceptance  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import fixed_assets  # noqa: E402
from babeldoc.magazine import run_trace  # noqa: E402
from babeldoc.magazine.react import config as repair_config  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.magazine.transaction import TransactionSnapshot  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0
POLICY = acceptance.load_acceptance_policy()


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"PASS: {name}")
    else:
        FAILURES.append(f"{name}: {detail or 'condition was false'}")
        print(f"FAIL: {name} :: {detail or 'condition was false'}")


def issue(
    issue_id: str,
    kind: str,
    severity: str,
    **dimensions: int | float,
):
    return acceptance.measured_issue(
        issue_id,
        kind,
        severity,
        dimensions,
        tuple(dimensions),
    )


def box(x: float, y: float, x2: float, y2: float) -> il_version_1.Box:
    return il_version_1.Box(x=x, y=y, x2=x2, y2=y2)


def paragraph(text: str, y: float) -> il_version_1.PdfParagraph:
    return il_version_1.PdfParagraph(
        box=box(10.0, y, 90.0, y + 12.0),
        unicode=text,
        layout_label="plain text",
        drop_cap_candidate=True,
        drop_cap_decision="preserve",
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        unicode=text,
                        pdf_style=il_version_1.PdfStyle(
                            font_id="F0", font_size=10.0
                        ),
                    )
                )
            )
        ],
    )


def page(number: int, text: str) -> il_version_1.Page:
    return il_version_1.Page(
        page_number=number - 1,
        pdf_paragraph=[paragraph(text, 60.0)],
        pdf_figure=[il_version_1.PdfFigure(box=box(5.0, 5.0, 20.0, 20.0))],
        cropbox=il_version_1.Cropbox(box=box(0.0, 0.0, 100.0, 100.0)),
        mediabox=il_version_1.Mediabox(box=box(0.0, 0.0, 100.0, 100.0)),
    )


def document(pages: int = 2) -> il_version_1.Document:
    values = [page(index, f"page {index}") for index in range(1, pages + 1)]
    return il_version_1.Document(page=values, total_pages=pages)


def inventory_builder(docs, trace):
    return lambda: fixed_assets.build_inventory(docs, run_trace=trace)


def check_same_issue_worsening_rolls_back() -> None:
    docs = document(1)
    trace = run_trace.RunTrace()
    inventory = fixed_assets.build_inventory(docs, run_trace=trace)
    transaction = TransactionSnapshot.capture(
        docs,
        run_trace=trace,
        fixed_inventory=inventory,
        fixed_inventory_builder=inventory_builder(docs, trace),
    )
    transaction.begin_generation("same_issue_worsened")
    docs.page[0].pdf_paragraph[0].box.x += 4.0
    before = [issue("overlap:p1:p1#0", "text_figure_overlap", "low", area=12.0)]
    after = [issue("overlap:p1:p1#0", "text_figure_overlap", "low", area=18.0)]
    comparison = acceptance.compare_issues(before, after, POLICY)
    record = transaction.rollback() if not comparison.accepted else transaction.commit()
    check(
        "same issue ID with larger overlap area rolls back",
        not comparison.accepted
        and comparison.worsened_ids == ("overlap:p1:p1#0",)
        and record["status"] == "rolled_back"
        and record["rollback_verification"]["verified"],
        json.dumps(comparison.as_record(), sort_keys=True),
    )


def check_new_critical_rejects_resolved_old_issue() -> None:
    docs = document(1)
    trace = run_trace.RunTrace()
    inventory = fixed_assets.build_inventory(docs, run_trace=trace)
    transaction = TransactionSnapshot.capture(
        docs,
        run_trace=trace,
        fixed_inventory=inventory,
        fixed_inventory_builder=inventory_builder(docs, trace),
    )
    transaction.begin_generation("critical_swap")
    docs.page[0].pdf_paragraph[0].box.y2 = 104.0
    before = [issue("collision:p1:p1#0+p1#1", "text_text_collision", "medium", area=8.0)]
    after = [issue("bounds:p1:p1#0", "out_of_page", "critical", distance=4.0)]
    comparison = acceptance.compare_issues(before, after, POLICY)
    record = transaction.rollback() if not comparison.accepted else transaction.commit()
    check(
        "resolved old issue cannot hide a new critical bounds issue",
        not comparison.accepted
        and comparison.new_high_severity_ids == ("bounds:p1:p1#0",)
        and record["rollback_verification"]["verified"],
        json.dumps(comparison.as_record(), sort_keys=True),
    )


def check_metric_improvement_commits() -> None:
    docs = document(1)
    trace = run_trace.RunTrace()
    inventory = fixed_assets.build_inventory(docs, run_trace=trace)
    transaction = TransactionSnapshot.capture(
        docs,
        run_trace=trace,
        fixed_inventory=inventory,
        fixed_inventory_builder=inventory_builder(docs, trace),
    )
    transaction.begin_generation("metric_improved")
    docs.page[0].pdf_paragraph[0].box.x += 1.0
    before = [issue("overlap:p1:p1#0", "text_figure_overlap", "low", area=18.0)]
    after = [issue("overlap:p1:p1#0", "text_figure_overlap", "low", area=9.0)]
    comparison = acceptance.compare_issues(before, after, POLICY)
    record = (
        transaction.commit(capture_geometry=False)
        if comparison.accepted
        else transaction.rollback()
    )
    check(
        "strict metric improvement with no new issue commits",
        comparison.accepted
        and comparison.improved_ids == ("overlap:p1:p1#0",)
        and record["status"] == "committed"
        and docs.page[0].pdf_paragraph[0].box.x == 11.0,
        json.dumps(comparison.as_record(), sort_keys=True),
    )


def mutate_page(docs, position: int, suffix: str) -> None:
    page_value = docs.page[position]
    paragraph_value = page_value.pdf_paragraph[0]
    paragraph_value.unicode += suffix
    paragraph_value.pdf_paragraph_composition[0].pdf_same_style_unicode_characters.unicode += suffix
    paragraph_value.box.y += 3.0
    paragraph_value.drop_cap_decision = "flatten"
    page_value.pdf_figure[0].box.x += 2.0


def check_action_exception_restores_touched_state() -> None:
    docs = document(2)
    trace = run_trace.RunTrace()
    allocator = {"cursor": 1, "open_slots": ["p1#0", "p2#0"]}
    inventory = fixed_assets.build_inventory(docs, run_trace=trace)
    transaction = TransactionSnapshot.capture(
        docs,
        (0, 1),
        run_trace=trace,
        fixed_inventory=inventory,
        fixed_inventory_builder=inventory_builder(docs, trace),
        allocator=allocator,
    )
    transaction.begin_generation("action_exception")
    try:
        mutate_page(docs, 0, " changed")
        allocator["cursor"] = 2
        allocator["open_slots"].pop()
        trace.record_blocked_reason({"code": "partial_action"})
        raise RuntimeError("injected action failure")
    except RuntimeError:
        record = transaction.rollback()
    digests = record["rollback_verification"]
    check(
        "mid-action exception restores XML geometry trace assets and intent",
        record["status"] == "rolled_back"
        and digests["verified"]
        and digests["expected"] == digests["restored"]
        and allocator == {"cursor": 1, "open_slots": ["p1#0", "p2#0"]},
        json.dumps(record, sort_keys=True),
    )


def check_second_page_failure_restores_both_pages() -> None:
    docs = document(2)
    trace = run_trace.RunTrace()
    inventory = fixed_assets.build_inventory(docs, run_trace=trace)
    transaction = TransactionSnapshot.capture(
        docs,
        (0, 1),
        run_trace=trace,
        fixed_inventory=inventory,
        fixed_inventory_builder=inventory_builder(docs, trace),
    )
    transaction.begin_generation("second_page_failure")
    before_text = [item.pdf_paragraph[0].unicode for item in docs.page]
    try:
        mutate_page(docs, 0, " first")
        mutate_page(docs, 1, " second")
        raise ValueError("page two detector failed")
    except ValueError:
        record = transaction.rollback()
    check(
        "second-page failure restores both pages atomically",
        [item.pdf_paragraph[0].unicode for item in docs.page] == before_text
        and record["pages"] == [1, 2]
        and record["rollback_verification"]["verified"],
        json.dumps(record, sort_keys=True),
    )


class BrokenTransport:
    def __init__(self) -> None:
        self.calls = 0

    def counters(self):
        return self.calls, 0

    def select(self, **_request):
        self.calls += 1
        raise ConnectionError("transport unavailable")


def check_cache_transport_failure_is_not_executed() -> None:
    config = repair_config.load_repair_config(None, detectors.detector_kinds())
    transport = BrokenTransport()
    with tempfile.TemporaryDirectory(prefix="repair_transaction_") as directory:
        client = decide.CachedDecisionClient(
            config,
            transport=transport,
            identity="offline",
            working_dir=Path(directory),
            language="zh",
        )
        finding = types.SimpleNamespace(
            id="untranslated_residue:p1:p1#0",
            kind="untranslated_residue",
            severity="high",
            page=1,
            paragraph_refs=("p1#0",),
            evidence={
                "residue_chars": 20,
                "residue_ratio": 1.0,
                "excerpt": "untranslated line",
            },
        )
        state = types.SimpleNamespace(sha256=lambda: "1" * 64)
        decision, request = client.decide([finding], repair_state=state)
    check(
        "forced transport failure is reported as not_executed without fallback",
        transport.calls == 1
        and decision is None
        and request.logical_calls == 1
        and request.provider_attempts == 1
        and request.violations == ["ConnectionError"],
        json.dumps(request.__dict__, sort_keys=True),
    )


def check_integration_and_limits() -> None:
    sources = {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in (
            "babeldoc/magazine/column_reflow.py",
            "babeldoc/magazine/article_flow.py",
            "babeldoc/magazine/cross_page_reflow.py",
            "babeldoc/magazine/react/controller.py",
        )
    }
    repair_raw = json.loads(
        (ROOT / "configs" / "repair_actions.json").read_text(encoding="utf-8")
    )
    integration = all(
        "TransactionSnapshot" in source for source in sources.values()
    ) and all(
        needle in "\n".join(sources.values())
        for needle in ("acceptance.compare_issues", "compare_flow")
    )
    limits = repair_raw["max_iterations"] == 3 and {
        name: value["max_applications"]
        for name, value in repair_raw["actions"].items()
    } == {
        "reprocess_omitted_text": 12,
        "reallocate_continuity_chain": 2,
        "retypeset_article_region": 3,
        "contain_overflowing_heading": 8,
        "resolve_text_collision": 8,
    }
    check("all flow and repair paths share the transaction boundary", integration)
    check("canonical round and five-action limits remain bounded", limits)


def main() -> int:
    check_same_issue_worsening_rolls_back()
    check_new_critical_rejects_resolved_old_issue()
    check_metric_improvement_commits()
    check_action_exception_restores_touched_state()
    check_second_page_failure_restores_both_pages()
    check_cache_transport_failure_is_not_executed()
    check_integration_and_limits()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} repair transaction checks")
        for failure in FAILURES:
            print(f" - {failure}")
        return 1
    print(f"PASS: {CHECKS} repair transaction checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
