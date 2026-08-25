"""Offline contract checks for fixed asset guards and source prerequisites."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

hitl_stub = types.ModuleType("babeldoc.magazine.hitl")
hitl_stub.labeled_pages = lambda docs: enumerate(docs.page, 1)
hitl_stub.after_repair = lambda *_args: None
sys.modules.setdefault("babeldoc.magazine.hitl", hitl_stub)

escalation_stub = types.ModuleType("babeldoc.magazine.detectors.escalation")
escalation_stub.NAME = "escalation_surfacing"
escalation_stub.KIND = "chain_escalation"
escalation_stub.REQUIRES_TRANSLATION = True
escalation_stub.REQUIRES_SOURCE_GEOMETRY = False
escalation_stub.detect = lambda _context: []
sys.modules.setdefault("babeldoc.magazine.detectors.escalation", escalation_stub)

cache_stub = types.ModuleType("babeldoc.translator.cache")
cache_stub.TranslationCache = type("TranslationCache", (), {})
sys.modules.setdefault("babeldoc.translator.cache", cache_stub)

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import column_reflow  # noqa: E402
from babeldoc.magazine import fixed_assets  # noqa: E402
from babeldoc.magazine import run_trace  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import UnsupportedArticlePage  # noqa: E402
from babeldoc.magazine.detectors import overlap  # noqa: E402
from babeldoc.magazine.detectors import source_geometry  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(f"{name}: {detail or 'condition was false'}")


def box(x: float, y: float, x2: float, y2: float) -> il_version_1.Box:
    return il_version_1.Box(x=x, y=y, x2=x2, y2=y2)


def character(geometry, text: str = "x") -> il_version_1.PdfCharacter:
    return il_version_1.PdfCharacter(
        box=box(*geometry),
        char_unicode=text,
        xobj_id=0,
        pdf_style=il_version_1.PdfStyle(font_id="F0", font_size=10.0),
    )


def paragraph(geometry, text: str = "text") -> il_version_1.PdfParagraph:
    return il_version_1.PdfParagraph(
        box=box(*geometry),
        unicode=text,
        xobj_id=0,
        layout_label="plain text",
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_character=character(geometry, text[0])
            )
        ],
    )


def formula_paragraph(geometry) -> il_version_1.PdfParagraph:
    formula = il_version_1.PdfFormula(
        box=box(*geometry),
        pdf_character=[character(geometry, "f")],
        pdf_curve=[il_version_1.PdfCurve(box=box(*geometry))],
        pdf_form=[il_version_1.PdfForm(box=box(*geometry))],
    )
    return il_version_1.PdfParagraph(
        box=box(*geometry),
        unicode="formula",
        xobj_id=0,
        layout_label="formula",
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(pdf_formula=formula)
        ],
    )


def flow_kind() -> str:
    from babeldoc.magazine.taxonomy import load_taxonomy

    config = column_reflow.load_reflow_config()
    for page_type in load_taxonomy().page_types:
        if page_type.policy.get("repair_profile") in config.profiles:
            return page_type.name
    raise AssertionError("no flow repair profile is declared")


def page(paragraphs) -> il_version_1.Page:
    result = il_version_1.Page(
        page_number=0,
        pdf_paragraph=list(paragraphs),
        cropbox=il_version_1.Cropbox(box=box(0.0, 0.0, 400.0, 800.0)),
        mediabox=il_version_1.Mediabox(box=box(0.0, 0.0, 400.0, 800.0)),
    )
    result.page_kind = flow_kind()
    return result


def document(page_value) -> il_version_1.Document:
    return il_version_1.Document(page=[page_value], total_pages=1)


def source_for(boxes) -> source_geometry.SourceGeometry:
    return source_geometry.SourceGeometry(
        stage="stub",
        path="stub.xml",
        boxes={f"p1#{index}": value for index, value in enumerate(boxes)},
    )


class StubConfig:
    def __init__(self, working: Path, *, enabled: bool = True):
        self.working = working
        self.lang_out = "zh"
        self.skip_translation = False
        self.magazine_column_reflow = enabled
        self.translator = None
        self.ignore_cache = False

    def get_working_file_path(self, name: str) -> Path:
        return self.working / name


def moving_fixture():
    paragraphs = [
        paragraph((50.0, 700.0, 350.0, 760.0), "upper"),
        paragraph((50.0, 480.0, 350.0, 560.0), "lower"),
    ]
    source = source_for(
        ((50.0, 700.0, 350.0, 760.0), (50.0, 600.0, 350.0, 680.0)),
    )
    return page(paragraphs), source


def check_shared_classification_and_obstacles() -> None:
    config = column_reflow.load_reflow_config()
    check(
        "all fixed page collections are reflow obstacles",
        set(fixed_assets.PAGE_ASSET_COLLECTIONS).issubset(config.obstacle_collections),
    )
    check(
        "overlap detector shares artwork classification",
        overlap.ARTWORK_SOURCES == fixed_assets.ARTWORK_COLLECTIONS,
    )
    for collection, factory in (
        ("pdf_figure", il_version_1.PdfFigure),
        ("pdf_xobject", il_version_1.PdfXobject),
        ("pdf_form", il_version_1.PdfForm),
        ("pdf_curve", il_version_1.PdfCurve),
        ("pdf_rectangle", il_version_1.PdfRectangle),
    ):
        test_page, source = moving_fixture()
        setattr(test_page, collection, [factory(box=box(50.0, 580.0, 350.0, 690.0))])
        inventory = fixed_assets.build_inventory(document(test_page))
        planned = column_reflow.plan_page(
            test_page,
            1,
            source,
            config,
            inventory,
        )
        reason = planned["columns"][0][0]["rows"][1]["reason"]
        check(
            f"{collection} blocks crossing movement",
            reason == column_reflow.REASON_OBSTACLE,
            reason,
        )


def check_default_switch_compatibility(root: Path) -> None:
    test_page, _source = moving_fixture()
    docs = document(test_page)
    before = fixed_assets.content_digest(docs)
    result = column_reflow.apply(StubConfig(root, enabled=False), docs)
    check(
        "disabled reflow remains a no-op",
        result is None
        and before == fixed_assets.content_digest(docs)
        and not (root / column_reflow.REPORT_NAME).exists(),
    )


def check_formula_inventory_and_blank_movement() -> None:
    upper = paragraph((50.0, 700.0, 350.0, 760.0), "upper")
    lower = formula_paragraph((50.0, 480.0, 350.0, 560.0))
    formula_page = page([upper, lower])
    source = source_for(
        ((50.0, 700.0, 350.0, 760.0), (50.0, 600.0, 350.0, 680.0)),
    )
    inventory = fixed_assets.build_inventory(document(formula_page))
    types = {asset.asset_type for asset in inventory.assets}
    check(
        "formula and its form and curve are inventoried",
        {"pdf_formula", "pdf_form", "pdf_curve"}.issubset(types),
        str(sorted(types)),
    )
    planned = column_reflow.plan_page(
        formula_page,
        1,
        source,
        column_reflow.load_reflow_config(),
        inventory,
    )
    check(
        "formula paragraph remains anchored",
        planned["columns"][0][0]["rows"][1]["reason"] == column_reflow.REASON_FORMULA,
    )

    blank_page, blank_source = moving_fixture()
    blank_docs = document(blank_page)
    blank_inventory = fixed_assets.build_inventory(blank_docs)
    before = blank_page.pdf_paragraph[1].box.y
    result = column_reflow.apply_page(
        blank_page,
        1,
        StubConfig(Path()),
        blank_source,
        column_reflow.load_reflow_config(),
        issues_of=lambda *_args: set(),
        fixed_inventory=blank_inventory,
        inventory_after=lambda: fixed_assets.build_inventory(blank_docs),
    )
    check(
        "legal blank region movement passes",
        result["applied"] and blank_page.pdf_paragraph[1].box.y > before,
        json.dumps(result, sort_keys=True),
    )


def check_header_footer_inventory() -> None:
    header = paragraph((20.0, 770.0, 180.0, 790.0), "running head")
    header.layout_label = "page_header"
    body = paragraph((50.0, 500.0, 350.0, 700.0), "body")
    docs = document(page([header, body]))
    article_ir = types.SimpleNamespace(
        by_element={"p1#0": "article", "p1#1": "article"},
        unsupported_pages=(),
    )
    config = column_reflow.load_reflow_config()
    inventory = fixed_assets.build_inventory(
        docs,
        article_document_ir=article_ir,
        protected_paragraph_labels=config.protected_paragraph_labels,
    )
    check(
        "article-page header remains fixed furniture",
        inventory.protected_paragraph_refs == {"p1#0"},
        str(sorted(inventory.protected_paragraph_refs)),
    )


def check_source_checkpoint_states(root: Path) -> None:
    missing = source_geometry.load(root / "missing", "styles_and_formulas")
    check(
        "missing checkpoint is explicit",
        missing.status is source_geometry.SourceGeometryStatus.MISSING
        and missing.issue()["blocked"],
    )
    invalid_path = root / "invalid.xml"
    invalid_path.write_text("not xml", encoding="utf-8")
    original_path = source_geometry.checkpoint_path
    try:
        source_geometry.checkpoint_path = lambda *_args: invalid_path
        invalid = source_geometry.load(root, "styles_and_formulas")
    finally:
        source_geometry.checkpoint_path = original_path
    check(
        "invalid checkpoint is explicit",
        invalid.status is source_geometry.SourceGeometryStatus.INVALID
        and invalid.issue()["code"] == "source_checkpoint_invalid",
        invalid.reason or "",
    )

    for name, result in (("missing", missing), ("invalid", invalid)):
        test_page, _source = moving_fixture()
        docs = document(test_page)
        before = fixed_assets.content_digest(docs)
        working = root / name
        report = column_reflow.apply(StubConfig(working), docs, source_geometry=result)
        check(
            f"{name} checkpoint blocks without IL mutation",
            before == fixed_assets.content_digest(docs)
            and report["pages"][0]["skipped"] == f"source_checkpoint_{name}"
            and report["prerequisite_issues"][0]["blocked"],
            json.dumps(report, sort_keys=True),
        )
        manifest = json.loads(
            (working / "magazine_run_manifest.json").read_text(encoding="utf-8")
        )
        check(
            f"{name} blocked reason reaches manifest",
            manifest["blocked_reasons"][0]["code"] == f"source_checkpoint_{name}",
        )

    trace = run_trace.RunTrace()
    trace.record_blocked_reason(invalid.issue())
    check(
        "blocked reason reaches RunTrace",
        trace.to_record()["blocked_reasons"][0]["code"] == "source_checkpoint_invalid",
    )


def check_inventory_drift_and_rollback(root: Path) -> None:
    test_page, source = moving_fixture()
    test_page.pdf_xobject = [
        il_version_1.PdfXobject(
            box=box(365.0, 100.0, 390.0, 140.0), xobj_id=7, xref_id=9
        )
    ]
    docs = document(test_page)
    baseline = fixed_assets.build_inventory(docs)

    bbox_docs = copy.deepcopy(docs)
    bbox_docs.page[0].pdf_xobject[0].box.x += 1.0
    bbox_change = fixed_assets.compare(
        baseline,
        fixed_assets.build_inventory(bbox_docs),
        column_reflow.load_reflow_config().asset_bbox_tolerance_pt,
    )
    check("bbox drift is detected", not bbox_change.holds and bbox_change.bbox_changed)

    digest_docs = copy.deepcopy(docs)
    digest_docs.page[0].pdf_xobject[0].xref_id += 1
    digest_change = fixed_assets.compare(
        baseline,
        fixed_assets.build_inventory(digest_docs),
        column_reflow.load_reflow_config().asset_bbox_tolerance_pt,
    )
    check(
        "digest drift is detected",
        not digest_change.holds and digest_change.digest_changed,
    )

    count_docs = copy.deepcopy(docs)
    count_docs.page[0].pdf_rectangle.append(
        il_version_1.PdfRectangle(box=box(1.0, 1.0, 2.0, 2.0))
    )
    count_change = fixed_assets.compare(
        baseline,
        fixed_assets.build_inventory(count_docs),
        column_reflow.load_reflow_config().asset_bbox_tolerance_pt,
    )
    check(
        "count drift is detected",
        not count_change.holds
        and count_change.count_after == count_change.count_before + 1,
    )

    size_docs = copy.deepcopy(docs)
    size_docs.page[0].cropbox.box.x2 -= 1.0
    size_change = fixed_assets.compare(
        baseline,
        fixed_assets.build_inventory(size_docs),
        column_reflow.load_reflow_config().asset_bbox_tolerance_pt,
    )
    check(
        "page size drift is detected",
        not size_change.holds and size_change.page_size_changed == (1,),
    )

    original_builder = column_reflow.fixed_assets.build_inventory
    calls = 0

    def drifting_builder(value, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            value.page[0].pdf_xobject[0].box.x += 3.0
        return original_builder(value, **kwargs)

    original_x = docs.page[0].pdf_xobject[0].box.x
    try:
        column_reflow.fixed_assets.build_inventory = drifting_builder
        report = column_reflow.apply(
            StubConfig(root / "rollback"),
            docs,
            source_geometry=source,
            fixed_inventory=baseline,
        )
    finally:
        column_reflow.fixed_assets.build_inventory = original_builder
    check(
        "asset drift triggers complete rollback",
        docs.page[0].pdf_xobject[0].box.x == original_x
        and not report["fixed_asset_comparison"]["holds"]
        and report["pages"][0]["guard"] == column_reflow.GUARD_FIXED_ASSET,
        json.dumps(report, sort_keys=True),
    )


def check_unsupported_article_page(root: Path) -> None:
    test_page, source = moving_fixture()
    docs = document(test_page)
    article_ir = ArticleDocumentIR(
        articles=(),
        by_page={},
        by_element={},
        by_chain={},
        unsupported_pages=(
            UnsupportedArticlePage(
                page=1,
                reason="unsupported_same_page_multi_article",
                evidence_refs=("p1#0", "p1#1"),
            ),
        ),
    )
    before = fixed_assets.content_digest(docs)
    report = column_reflow.apply(
        StubConfig(root / "unsupported"),
        docs,
        source_geometry=source,
        article_document_ir=article_ir,
    )
    check(
        "unsupported ArticleIR page never reflows",
        before == fixed_assets.content_digest(docs)
        and report["pages"][0]["skipped"] == column_reflow.SKIP_UNSUPPORTED,
        json.dumps(report, sort_keys=True),
    )
    inventory = fixed_assets.build_inventory(docs, article_document_ir=article_ir)
    check(
        "unsupported page paragraphs are protected furniture",
        inventory.protected_paragraph_refs == {"p1#0", "p1#1"},
        str(sorted(inventory.protected_paragraph_refs)),
    )


def check_repair_transaction_rollback(root: Path) -> None:
    test_page, source = moving_fixture()
    test_page.pdf_xobject = [
        il_version_1.PdfXobject(
            box=box(365.0, 100.0, 390.0, 140.0), xobj_id=7, xref_id=9
        )
    ]
    docs = document(test_page)
    baseline = fixed_assets.build_inventory(docs)
    (root / "repair").mkdir(parents=True)
    loop = controller.RepairLoop(
        StubConfig(root / "repair"),
        docs,
        source_geometry=source,
        fixed_inventory=baseline,
    )
    original_detect = controller.detect
    original_x = docs.page[0].pdf_xobject[0].box.x
    calls = 0

    def drifting_detect(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            docs.page[0].pdf_xobject[0].box.x += 2.0
        return original_detect(*args, **kwargs)

    try:
        controller.detect = drifting_detect
        loop.run()
    finally:
        controller.detect = original_detect
    report = json.loads(
        (root / "repair" / controller.REPORT_NAME).read_text(encoding="utf-8")
    )
    check(
        "repair transaction restores fixed asset drift",
        docs.page[0].pdf_xobject[0].box.x == original_x
        and report["conservation"]["verdict"] == controller.VIOLATED
        and not report["conservation"]["fixed_assets"]["holds"],
        json.dumps(report["conservation"], sort_keys=True),
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="babeldoc-c04-") as directory:
        root = Path(directory)
        check_shared_classification_and_obstacles()
        check_default_switch_compatibility(root / "disabled")
        check_formula_inventory_and_blank_movement()
        check_header_footer_inventory()
        check_source_checkpoint_states(root)
        check_inventory_drift_and_rollback(root)
        check_unsupported_article_page(root)
        check_repair_transaction_rollback(root)
    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}")
        print(f"FAIL: {len(FAILURES)} of {CHECKS} fixed asset checks")
        return 1
    print(f"PASS: {CHECKS} fixed asset checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
