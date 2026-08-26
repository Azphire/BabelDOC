"""Offline contract checks for bounded article flow across adjacent pages."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spec_checks.spec_check_article_cross_column import FixedWidthMapper  # noqa: E402
from spec_checks.spec_check_article_cross_column import StubTranslator  # noqa: E402
from spec_checks.spec_check_article_cross_column import paragraph  # noqa: E402
from spec_checks.spec_check_article_cross_column import style_hash  # noqa: E402

from babeldoc.format.pdf.document_il import Box  # noqa: E402
from babeldoc.format.pdf.document_il import PdfStyle  # noqa: E402
from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting  # noqa: E402
from babeldoc.magazine import article_flow  # noqa: E402
from babeldoc.magazine import cross_page_reflow  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticlePolicyEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ArticleRegionSlot  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.article_ir import UnsupportedArticlePage  # noqa: E402
from babeldoc.magazine.fixed_assets import content_digest  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402

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


def document_digest(document) -> str:
    payload = json.dumps(
        asdict(document), ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def geometry_record(document) -> tuple:
    return (
        len(document.page),
        document.total_pages,
        tuple(
            (
                page.page_number,
                tuple(asdict(page.mediabox.box).values()),
                tuple(asdict(page.cropbox.box).values()),
            )
            for page in document.page
        ),
    )


def _article(
    owner: str,
    pages: tuple[int, ...],
    elements,
    unsupported,
    hard_boundaries,
    xobject_page,
) -> ArticleIR:
    slots = []
    for page in pages:
        if page in unsupported:
            continue
        obstacle_refs = (
            (f"p{page}:pdf_xobject#0",) if page == xobject_page else ()
        )
        slots.append(
            ArticleRegionSlot(
                owner,
                page,
                0,
                len(slots),
                (0.0, 20.0, 40.0, 90.0),
                obstacle_refs,
                2800.0,
            )
        )
    return ArticleIR(
        article_id=owner,
        pages=pages,
        elements=tuple(item for item in elements if item.page in pages),
        slots=tuple(slots),
        chain_ids=(),
        policy_evidence=tuple(
            ArticlePolicyEvidence(
                page,
                "member",
                "feature",
                "fixture_hard_boundary" if page in hard_boundaries else None,
                page not in unsupported and page not in hard_boundaries,
            )
            for page in pages
        ),
    )


def fixture(
    targets: tuple[str, ...],
    *,
    owners: tuple[str, ...],
    unsupported=None,
    hard_boundaries=None,
    xobject_page: int | None = None,
):
    unsupported = frozenset() if unsupported is None else frozenset(unsupported)
    hard_boundaries = (
        frozenset() if hard_boundaries is None else frozenset(hard_boundaries)
    )
    style = PdfStyle(font_id="body", font_size=10.0)
    source = "源文"
    pages = []
    elements = []
    for index, target in enumerate(targets):
        page_number = index + 1
        body = paragraph(source, "text", (0.0, 20.0, 40.0, 90.0), style)
        xobjects = []
        if page_number == xobject_page:
            xobjects.append(
                il_version_1.PdfXobject(
                    box=Box(0.0, 48.0, 40.0, 62.0),
                    xobj_id=page_number,
                    xref_id=page_number,
                )
            )
        pages.append(
            il_version_1.Page(
                mediabox=il_version_1.Mediabox(
                    box=Box(0.0, 0.0, 100.0, 120.0)
                ),
                cropbox=il_version_1.Cropbox(box=Box(0.0, 0.0, 100.0, 120.0)),
                pdf_font=[il_version_1.PdfFont(font_id="body", name="body")],
                pdf_xobject=xobjects,
                pdf_paragraph=[body],
                page_number=index,
            )
        )
        elements.append(
            SourceElementRef(
                source_ref=f"p{page_number}#0",
                page=page_number,
                column=0,
                reading_order=index,
                role="text",
                source_box=(0.0, 20.0, 40.0, 90.0),
                source_text_hash=hashlib.sha256(source.encode()).hexdigest(),
                style_hash=style_hash(style),
            )
        )
    document = il_version_1.Document(page=pages, total_pages=len(pages))
    articles = tuple(
        _article(
            owner,
            tuple(index + 1 for index, value in enumerate(owners) if value == owner),
            elements,
            unsupported,
            hard_boundaries,
            xobject_page,
        )
        for owner in dict.fromkeys(owners)
    )
    unsupported_rows = tuple(
        UnsupportedArticlePage(page, "multiple_article_identity", (f"p{page}#0",))
        for page in sorted(unsupported)
    )
    article_ir = ArticleDocumentIR(
        articles=articles,
        by_page={index + 1: owner for index, owner in enumerate(owners)},
        by_element={
            element.source_ref: owners[element.page - 1] for element in elements
        },
        by_chain={},
        unsupported_pages=unsupported_rows,
    )
    trace = RunTrace.from_document(document, article_ir)
    for index, target in enumerate(targets):
        reference = f"p{index + 1}#0"
        request = trace.open_request(
            "paragraph_batch", (reference,), source, {"fixture": reference}
        )
        trace.record_translator_call(request)
        trace.complete_request_with_fragments(request, ((reference, target),))
        body = document.page[index].pdf_paragraph[0]
        body.unicode = target
        body.pdf_paragraph_composition = [
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        unicode=target,
                        pdf_style=style,
                    )
                )
            )
        ]
    working = Path(tempfile.mkdtemp(prefix="babeldoc-c08-"))
    mapper = FixedWidthMapper()
    translator = StubTranslator(working, mapper)
    typesetter = Typesetting(translator.translation_config, font_mapper=mapper)
    return document, article_ir, trace, translator, typesetter, working


def apply_fixture(targets, **kwargs):
    document, article_ir, trace, translator, typesetter, working = fixture(
        targets, **kwargs
    )
    report = article_flow.apply(
        translator,
        document,
        article_ir,
        trace,
        typesetter=typesetter,
    )
    return document, article_ir, trace, report, working


def check_long_target_crosses_adjacent_page() -> None:
    document, _article_ir, trace, report, _working = apply_fixture(
        ("长" * 52, "次", "新"), owners=("article-a", "article-a", "article-b")
    )
    segment = next(
        item
        for item in report["cross_page_segments"]
        if item["article_id"] == "article-a"
    )
    moved = [
        item
        for item in segment["placements"]
        if item["source_ref"] == "p1#0" and item["page"] == 2
    ]
    check(
        "a long target continues into the next canonical same-article page",
        segment["status"] == "applied"
        and segment["contiguous_pages"] == [1, 2]
        and moved
        and sum(
            item["chars"]
            for item in segment["placements"]
            if item["source_ref"] == "p1#0"
        )
        == 52,
        repr(segment),
    )
    check(
        "the next article never receives the preceding article target",
        not any(
            item["source_ref"] == "p1#0" and item["page"] == 3
            for segment in report["cross_page_segments"]
            for item in segment.get("placements", ())
        )
        and any(
            item["code"] == cross_page_reflow.ISSUE_PAGE_OWNERSHIP_CONFLICT
            and item["pages"] == [2, 3]
            for item in report["issues"]
        ),
        repr(report["issues"]),
    )
    movement = [
        item.to_record()["movement"]
        for item in trace.flow_slots.values()
        if item.active and item.source_ref == "p1#0" and item.page == 2
    ]
    check(
        "report and RunTrace retain before and after page-slot movement",
        moved[0]["movement"]["before"]["page"] == 1
        and moved[0]["movement"]["before"]["slot_id"]
        and moved[0]["movement"]["after"]["page"] == 2
        and movement
        and movement[0]["before"]["page"] == 1
        and movement[0]["after"]["page"] == 2,
        repr(movement),
    )
    check(
        "shorter remaining targets release later page capacity",
        any(
            item.active
            and item.status == article_flow.STATUS_RELEASED
            and item.page == 2
            for item in trace.flow_slots.values()
        ),
    )
    trace.validate()
    check("the cross-page trace remains internally valid", True)


def check_middle_page_xobject_and_geometry_conservation() -> None:
    before, article_ir, trace, translator, typesetter, _working = fixture(
        ("流" * 92, "二", "三"),
        owners=("article-a", "article-a", "article-a"),
        xobject_page=2,
    )
    geometry = geometry_record(before)
    xobject = content_digest(before.page[1].pdf_xobject[0])
    report = article_flow.apply(
        translator, before, article_ir, trace, typesetter=typesetter
    )
    segment = report["cross_page_segments"][0]
    obstacle = (0.0, 48.0, 40.0, 62.0)
    page_two = [item for item in segment["placements"] if item["page"] == 2]

    def overlap(box) -> bool:
        return min(box[2], obstacle[2]) > max(box[0], obstacle[0]) and min(
            box[3], obstacle[3]
        ) > max(box[1], obstacle[1])

    check(
        "middle-page target slots route around the fixed XObject",
        segment["status"] == "applied"
        and page_two
        and not any(overlap(item["box"]) for item in page_two)
        and content_digest(before.page[1].pdf_xobject[0]) == xobject,
        repr(page_two),
    )
    check(
        "page geometry, identity, and fixed furniture are conserved",
        geometry_record(before) == geometry
        and segment["fixed_asset_comparison"]["holds"],
        repr(segment.get("fixed_asset_comparison")),
    )


def check_hard_and_unsupported_boundaries() -> None:
    document, article_ir, trace, translator, typesetter, _working = fixture(
        ("长" * 52, "二"),
        owners=("article-a", "article-a"),
        hard_boundaries=frozenset({2}),
    )
    inventory = cross_page_reflow.fixed_assets.build_inventory(
        document, protected_paragraph_labels=()
    )
    issue = cross_page_reflow.page_connection_issue(
        article_ir, article_ir.articles[0], 1, 2, inventory
    )
    report = article_flow.apply(
        translator, document, article_ir, trace, typesetter=typesetter
    )
    check(
        "a declared hard boundary prevents cross-page candidate construction",
        issue is not None
        and issue.code == cross_page_reflow.ISSUE_HARD_BOUNDARY
        and issue.detail == cross_page_reflow.BOUNDARY_POLICY
        and not any(
            item["source_ref"] == "p1#0" and item["page"] == 2
            for segment in report["cross_page_segments"]
            for item in segment.get("placements", ())
        ),
        repr(report["issues"]),
    )
    document, _ir, _trace, report, _working = apply_fixture(
        ("长" * 52, "二"),
        owners=("article-a", "article-a"),
        unsupported=frozenset({2}),
    )
    check(
        "an unsupported page neither receives nor outputs article-flow text",
        report["pages"][1]["status"] == "skipped"
        and report["pages"][1]["reason"] == article_flow.SKIP_UNSUPPORTED
        and not any(
            item["page"] == 2
            for segment in report["cross_page_segments"]
            for item in segment.get("placements", ())
        )
        and document.page[1].pdf_paragraph[0].unicode == "二",
        repr(report["pages"][1]),
    )


def check_connection_predicate_negative_cases() -> None:
    document, article_ir, _trace, _translator, _typesetter, _working = fixture(
        ("一", "二"), owners=("article-a", "article-a")
    )
    inventory = cross_page_reflow.fixed_assets.build_inventory(
        document, protected_paragraph_labels=()
    )
    article = article_ir.articles[0]
    non_adjacent = cross_page_reflow.page_connection_issue(
        article_ir, article, 1, 3, inventory
    )
    discontinuous = replace(
        article,
        elements=(article.elements[0], replace(article.elements[1], reading_order=2)),
    )
    reading = cross_page_reflow.page_connection_issue(
        article_ir, discontinuous, 1, 2, inventory
    )
    missing_geometry = replace(
        article,
        elements=(replace(article.elements[0], source_box=None), article.elements[1]),
    )
    geometry = cross_page_reflow.page_connection_issue(
        article_ir, missing_geometry, 1, 2, inventory
    )
    missing_asset = replace(
        article,
        slots=(
            replace(article.slots[0], fixed_obstacle_refs=("missing-asset",)),
            article.slots[1],
        ),
    )
    assets = cross_page_reflow.page_connection_issue(
        article_ir, missing_asset, 1, 2, inventory
    )
    check(
        "the connection predicate rejects non-adjacency and reading-order gaps",
        non_adjacent is not None
        and non_adjacent.detail == cross_page_reflow.BOUNDARY_NON_ADJACENT
        and reading is not None
        and reading.detail == cross_page_reflow.BOUNDARY_READING_ORDER,
        repr((non_adjacent, reading)),
    )
    check(
        "the connection predicate rejects missing source geometry and asset inventory",
        geometry is not None
        and geometry.detail == cross_page_reflow.BOUNDARY_SOURCE_GEOMETRY
        and assets is not None
        and assets.detail == cross_page_reflow.BOUNDARY_ASSET_INVENTORY,
        repr((geometry, assets)),
    )


def check_second_page_failure_rolls_back_segment() -> None:
    document, article_ir, trace, translator, typesetter, _working = fixture(
        ("长" * 52, "二"), owners=("article-a", "article-a")
    )
    before_document = document_digest(document)
    before_trace = trace.to_json_bytes()
    report = article_flow.apply(
        translator,
        document,
        article_ir,
        trace,
        typesetter=typesetter,
        validator=lambda page, _record: (
            ("injected_second_page_failure",) if page.page_number == 1 else ()
        ),
    )
    check(
        "a second-page detector failure restores both pages and the trace",
        all(item["status"] == "rolled_back" for item in report["pages"])
        and document_digest(document) == before_document
        and trace.to_json_bytes() == before_trace,
        repr(report["pages"]),
    )


def check_capacity_exhaustion_is_typed_and_atomic() -> None:
    document, article_ir, trace, translator, typesetter, _working = fixture(
        ("溢" * 500, "二"), owners=("article-a", "article-a")
    )
    before = document_digest(document)
    report = article_flow.apply(
        translator, document, article_ir, trace, typesetter=typesetter
    )
    check(
        "capacity exhaustion is typed and leaves the full segment untouched",
        report["cross_page_segments"][0]["status"] == "rolled_back"
        and any(
            item["code"] == cross_page_reflow.ISSUE_CAPACITY_EXHAUSTION
            for item in report["issues"]
        )
        and any(
            item["code"] == cross_page_reflow.ISSUE_CAPACITY_EXHAUSTION
            for item in trace.to_record()["blocked_reasons"]
        )
        and document_digest(document) == before,
        repr(report["issues"]),
    )


def changed_files() -> set[str]:
    tagged = (
        subprocess.run(  # noqa: S603, S607
            ["git", "rev-parse", "--verify", "--quiet", "refs/tags/batch-C08"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    command = (
        ["git", "diff", "--name-only", "batch-C08^", "batch-C08"]
        if tagged
        else ["git", "diff", "--name-only", "HEAD"]
    )
    output = subprocess.check_output(command, cwd=ROOT, text=True)  # noqa: S603
    if not tagged:
        output += subprocess.check_output(  # noqa: S603
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT,
            text=True,
        )
    return {line.replace("\\", "/") for line in output.splitlines() if line}


def check_scope_and_contract() -> None:
    allowed = {
        "babeldoc/magazine/article_flow.py",
        "babeldoc/magazine/cross_page_reflow.py",
        "babeldoc/magazine/run_trace.py",
        "configs/article_flow.json",
        "spec_checks/spec_check_article_cross_page.py",
    }
    changed = changed_files()
    source = (ROOT / "babeldoc/magazine/cross_page_reflow.py").read_text(
        encoding="utf-8"
    )
    check(
        "C08 changes only its bounded runtime, trace, and focused gate",
        changed <= allowed,
        str(sorted(changed - allowed)),
    )
    check(
        "connection and allocation are canonical, deterministic, and LLM-free",
        "page_connection_issue(" in source
        and "article_document_ir.by_page" in source
        and "article_flow.allocate_segment(" in source
        and "llm" not in source.lower(),
    )
    check(
        "legacy translator and frozen IL schema remain untouched",
        not any(
            path.endswith("il_translator.py") or path.endswith((".xsd", ".rng", ".rnc"))
            for path in changed
        ),
        str(sorted(changed)),
    )


def main() -> int:
    check_long_target_crosses_adjacent_page()
    check_middle_page_xobject_and_geometry_conservation()
    check_hard_and_unsupported_boundaries()
    check_connection_predicate_negative_cases()
    check_second_page_failure_rolls_back_segment()
    check_capacity_exhaustion_is_typed_and_atomic()
    check_scope_and_contract()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} cross-page article-flow checks")
        for failure in FAILURES:
            print(f" - {failure}")
        return 1
    print(f"PASS: {CHECKS} cross-page article-flow checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
