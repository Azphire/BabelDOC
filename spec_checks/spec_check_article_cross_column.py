"""Offline contract checks for page-local article flow across columns."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if importlib.util.find_spec("pymupdf") is None:
    pymupdf_stub = types.ModuleType("pymupdf")
    pymupdf_stub.Font = object
    pymupdf_stub.Document = object
    sys.modules["pymupdf"] = pymupdf_stub
if importlib.util.find_spec("rtree") is None:
    rtree_stub = types.ModuleType("rtree")
    rtree_stub.index = SimpleNamespace()
    sys.modules["rtree"] = rtree_stub
if "babeldoc.translator.cache" not in sys.modules:
    cache_stub = types.ModuleType("babeldoc.translator.cache")
    cache_stub.TranslationCache = object
    sys.modules["babeldoc.translator.cache"] = cache_stub
if "babeldoc.format.pdf.translation_config" not in sys.modules:
    config_stub = types.ModuleType("babeldoc.format.pdf.translation_config")
    config_stub.TranslationConfig = object
    config_stub.WatermarkOutputMode = SimpleNamespace(
        NoWatermark="no_watermark",
        Both="both",
    )
    sys.modules["babeldoc.format.pdf.translation_config"] = config_stub

from babeldoc.format.pdf.document_il import Box  # noqa: E402
from babeldoc.format.pdf.document_il import PdfParagraph  # noqa: E402
from babeldoc.format.pdf.document_il import PdfStyle  # noqa: E402
from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting  # noqa: E402
from babeldoc.magazine import article_flow  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticlePolicyEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ArticleRegionSlot  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.article_ir import UnsupportedArticlePage  # noqa: E402
from babeldoc.magazine.fixed_assets import content_digest  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402
from babeldoc.magazine.run_trace import hash_record  # noqa: E402

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


class FixedWidthFont:
    font_id = "body"
    name = "body"
    is_bold = False
    is_italic = False
    is_monospaced = False
    is_serif = True

    @staticmethod
    def char_lengths(text: str, font_size: float):
        return tuple(font_size * 0.5 for _character in text)


class FixedWidthMapper:
    def __init__(self) -> None:
        self.base_font = FixedWidthFont()

    def map(self, _original_font, _character: str):
        return self.base_font


class StubConfig:
    def __init__(self, working: Path, enabled: bool = True) -> None:
        self.magazine_column_reflow = enabled
        self.lang_out = "zh"
        self.primary_font_family = None
        self.working = working

    def get_working_file_path(self, name: str) -> Path:
        return self.working / name


class StubTranslator:
    def __init__(self, working: Path, mapper) -> None:
        self.translation_config = StubConfig(working)
        self.font_mapper = mapper


def paragraph(text: str, role: str, box, style, *, formula: bool = False):
    if formula:
        composition = [
            il_version_1.PdfParagraphComposition(
                pdf_formula=il_version_1.PdfFormula(box=Box(*box))
            )
        ]
    else:
        composition = [
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
                    unicode=text,
                    pdf_style=style,
                )
            )
        ]
    return PdfParagraph(
        box=Box(*box),
        pdf_style=style,
        unicode=text,
        layout_label=role,
        first_line_indent=role == "text",
        pdf_paragraph_composition=composition,
    )


def style_hash(style) -> str:
    return hash_record(
        {"font_id": style.font_id, "font_size": style.font_size, "graphic_state": None}
    )


def document_digest(document) -> str:
    payload = json.dumps(
        asdict(document), ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fixture(targets: tuple[str, ...], *, unsupported: bool = False):
    style = PdfStyle(font_id="body", font_size=10.0)
    source = "源文"
    specs = (
        ("title", (0.0, 105.0, 100.0, 116.0)),
        ("text", (0.0, 58.0, 40.0, 90.0)),
        ("plain text", (0.0, 20.0, 40.0, 52.0)),
        ("continuation", (60.0, 58.0, 100.0, 90.0)),
        ("body", (60.0, 20.0, 100.0, 52.0)),
        ("caption", (0.0, 5.0, 35.0, 14.0)),
        ("formula", (40.0, 5.0, 60.0, 14.0)),
        ("footer", (65.0, 5.0, 100.0, 14.0)),
        ("mystery", (0.0, 0.0, 20.0, 4.0)),
    )
    paragraphs = [
        paragraph(
            source,
            role,
            box,
            style,
            formula=role == "formula",
        )
        for role, box in specs
    ]
    paragraphs[3].chain_id = "raw-chain"
    paragraphs[3].chain_index = 0
    paragraphs[4].chain_id = "raw-chain"
    paragraphs[4].chain_index = 1
    page = il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=Box(0.0, 0.0, 100.0, 120.0)),
        cropbox=il_version_1.Cropbox(box=Box(0.0, 0.0, 100.0, 120.0)),
        pdf_font=[il_version_1.PdfFont(font_id="body", name="body")],
        pdf_figure=[il_version_1.PdfFigure(box=Box(45.0, 18.0, 55.0, 94.0))],
        pdf_paragraph=paragraphs,
    )
    document = il_version_1.Document(page=[page])
    elements = []
    reading_order = 0
    for column, indices in (
        (-1, (0,)),
        (0, (1, 2)),
        (1, (3, 4)),
        (2, (5, 6, 7, 8)),
    ):
        for index in indices:
            role, box = specs[index]
            elements.append(
                SourceElementRef(
                    source_ref=f"p1#{index}",
                    page=1,
                    column=column,
                    reading_order=reading_order,
                    role=role,
                    source_box=box,
                    source_text_hash=hashlib.sha256(source.encode()).hexdigest(),
                    style_hash=style_hash(style),
                )
            )
            reading_order += 1
    article = ArticleIR(
        article_id="article-a",
        pages=(1,),
        elements=tuple(elements),
        slots=(
            ()
            if unsupported
            else (
                ArticleRegionSlot(
                    "article-a", 1, 0, 0, (0.0, 20.0, 40.0, 90.0), ("figure",), 2800.0
                ),
                ArticleRegionSlot(
                    "article-a", 1, 1, 1, (60.0, 20.0, 100.0, 90.0), ("figure",), 2800.0
                ),
            )
        ),
        chain_ids=("chain-a",),
        policy_evidence=(
            ArticlePolicyEvidence(1, "member", "feature", None, not unsupported),
        ),
    )
    article_ir = ArticleDocumentIR(
        articles=(article,),
        by_page={1: "article-a"},
        by_element={item.source_ref: "article-a" for item in elements},
        by_chain={"chain-a": "article-a"},
        by_chain_member={"p1#3": "chain-a", "p1#4": "chain-a"},
        unsupported_pages=(
            (UnsupportedArticlePage(1, "multiple_article_identity", ("p1#0", "p1#8")),)
            if unsupported
            else ()
        ),
    )
    trace = RunTrace.from_document(document, article_ir)
    body_refs = ("p1#1", "p1#2", "p1#3", "p1#4")
    for reference, target in zip(body_refs[:2], targets[:2], strict=True):
        request = trace.open_request(
            "paragraph_batch", (reference,), source, {"fixture": reference}
        )
        trace.record_translator_call(request)
        trace.complete_request_with_fragments(request, ((reference, target),))
        item = paragraphs[int(reference.partition("#")[2])]
        item.unicode = target
        item.pdf_paragraph_composition = [
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
                    unicode=target, pdf_style=style
                )
            )
        ]
    chain_request = trace.open_request(
        "continuity_chain",
        body_refs[2:],
        source * 2,
        {"fixture": "chain-a"},
    )
    trace.record_translator_call(chain_request)
    trace.complete_request_with_fragments(
        chain_request,
        tuple(zip(body_refs[2:], targets[2:], strict=True)),
    )
    for reference, target in zip(body_refs[2:], targets[2:], strict=True):
        item = paragraphs[int(reference.partition("#")[2])]
        item.unicode = target
        item.pdf_paragraph_composition = [
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
                    unicode=target, pdf_style=style
                )
            )
        ]
    working = Path(tempfile.mkdtemp(prefix="babeldoc-c07-"))
    mapper = FixedWidthMapper()
    translator = StubTranslator(working, mapper)
    typesetter = Typesetting(translator.translation_config, font_mapper=mapper)
    return document, article_ir, trace, translator, typesetter, working, paragraphs


def apply_fixture(targets: tuple[str, ...]):
    document, article_ir, trace, translator, typesetter, working, paragraphs = fixture(
        targets
    )
    protected = {index: content_digest(paragraphs[index]) for index in (0, 5, 6, 7, 8)}
    figure = content_digest(document.page[0].pdf_figure[0])
    report = article_flow.apply(
        translator,
        document,
        article_ir,
        trace,
        typesetter=typesetter,
    )
    return document, trace, report, protected, figure, working


def check_long_target_crosses_column() -> None:
    document, trace, report, protected, figure, _working = apply_fixture(
        ("长" * 44, "短短", "续续", "末末")
    )
    page = report["pages"][0]
    long_pieces = [item for item in page["placements"] if item["source_ref"] == "p1#1"]
    check(
        "long body target overflows from the first column into the second",
        page["status"] == "applied"
        and {item["column"] for item in long_pieces} == {0, 1}
        and sum(item["chars"] for item in long_pieces) == 44,
        repr(long_pieces),
    )
    trace_fragments = [
        item
        for item in trace.fragments.values()
        if item.active and item.source_ref == "p1#1"
    ]
    check(
        "cross-column fragments retain target ranges and render slots",
        len(trace_fragments) == 2
        and trace_fragments[0].text_start == 0
        and trace_fragments[-1].text_end == 44
        and all(item.slot_id and item.render_ref for item in trace_fragments),
        repr(trace_fragments),
    )
    check(
        "RunTrace advertises the article-flow record contract",
        trace.to_record()["schema_version"] == "run-trace.v2"
        and "flow_slots" in trace.to_record(),
    )
    trace.capture_typeset_document(document)
    geometry = next(
        item
        for item in trace.geometries.values()
        if trace.fragments[item.fragment_id].source_ref == "p1#1"
    )
    reverse = trace.trace_from_geometry(geometry.geometry_id)
    check(
        "fragment to slot to geometry is reverse traceable",
        reverse["fragment"]["source_ref"] == "p1#1"
        and reverse["geometry"]["slot_id"] == reverse["fragment"]["slot_id"],
        repr(reverse),
    )
    check(
        "fixed figure and protected role paragraphs are byte-stable",
        content_digest(document.page[0].pdf_figure[0]) == figure
        and all(
            content_digest(document.page[0].pdf_paragraph[index]) == digest
            for index, digest in protected.items()
        ),
    )


def check_short_targets_release_capacity() -> None:
    _document, trace, report, _protected, _figure, _working = apply_fixture(
        ("甲乙", "丙丁", "戊己", "庚辛")
    )
    page = report["pages"][0]
    placements = page["placements"]
    released = [
        slot
        for slot in trace.flow_slots.values()
        if slot.active and slot.status == article_flow.STATUS_RELEASED
    ]
    check(
        "short targets compact in reading order and release column-tail capacity",
        [item["source_ref"] for item in placements] == ["p1#1", "p1#2", "p1#3", "p1#4"]
        and [item["column"] for item in placements] == [0, 0, 0, 0]
        and any(slot.box and slot.box[0] >= 60.0 for slot in released),
        repr(placements),
    )
    check(
        "ordinary paragraphs and continuity fragments share one page-local slot order",
        trace.sources["p1#1"].chain_id is None
        and trace.sources["p1#3"].chain_id == "chain-a"
        and [item["slot_order"] for item in placements] == list(range(4)),
    )
    check(
        "paragraph boundary tokens retain identity, indentation, spacing, and order",
        all(
            {
                "source_ref",
                "paragraph_order",
                "target_range",
                "first_line_indent",
                "spacing_before",
            }
            <= set(item)
            for segment in page["segments"]
            for item in segment["boundaries"]
        ),
    )


def check_detector_failure_rolls_back() -> None:
    document, article_ir, trace, translator, typesetter, _working, _paragraphs = (
        fixture(("长" * 30, "二", "三", "四"))
    )
    before_document = document_digest(document)
    before_trace = trace.to_json_bytes()
    report = article_flow.apply(
        translator,
        document,
        article_ir,
        trace,
        typesetter=typesetter,
        validator=lambda _page, _record: ("injected_detector_failure",),
    )
    check(
        "detector failure restores the complete page/article segment",
        report["pages"][0]["status"] == "rolled_back"
        and document_digest(document) == before_document
        and trace.to_json_bytes() == before_trace,
        repr(report["pages"][0]),
    )


def check_trace_failure_rolls_back() -> None:
    document, article_ir, trace, translator, typesetter, _working, _paragraphs = (
        fixture(("长" * 30, "二", "三", "四"))
    )
    before_document = document_digest(document)
    before_active = {
        request_id: set(request.fragment_ids)
        for request_id, request in trace.requests.items()
    }
    original_record = trace.record_flow_slot

    def fail_record(*_args, **_kwargs):
        raise RuntimeError("injected_trace_failure")

    trace.record_flow_slot = fail_record
    try:
        report = article_flow.apply(
            translator,
            document,
            article_ir,
            trace,
            typesetter=typesetter,
        )
    finally:
        trace.record_flow_slot = original_record
    check(
        "trace write failure restores document and active request allocations",
        report["pages"][0]["status"] == "rolled_back"
        and document_digest(document) == before_document
        and all(
            request.fragment_ids == before_active[request_id]
            for request_id, request in trace.requests.items()
        )
        and any(
            generation.status == "rolled_back"
            for generation in trace.generations.values()
        ),
        repr(report["pages"][0]),
    )
    trace.validate()


def check_unsupported_page_is_inert() -> None:
    document, article_ir, trace, translator, typesetter, _working, _paragraphs = (
        fixture(("一", "二", "三", "四"), unsupported=True)
    )
    before = document_digest(document)
    report = article_flow.apply(
        translator, document, article_ir, trace, typesetter=typesetter
    )
    check(
        "unsupported multi-article page never enters article flow",
        document_digest(document) == before
        and report["pages"][0]["status"] == "skipped"
        and report["pages"][0]["reason"] == article_flow.SKIP_UNSUPPORTED,
        repr(report["pages"][0]),
    )


def changed_files() -> set[str]:
    tagged = (
        subprocess.run(  # noqa: S603, S607
            [  # noqa: S607
                "git",
                "rev-parse",
                "--verify",
                "--quiet",
                "refs/tags/batch-C07",
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    command = (
        ["git", "diff", "--name-only", "batch-C07^", "batch-C07"]
        if tagged
        else ["git", "diff", "--name-only", "HEAD"]
    )
    output = subprocess.check_output(  # noqa: S603, S607
        command, cwd=ROOT, text=True
    )
    return {line.replace("\\", "/") for line in output.splitlines() if line}


def check_scope_and_pipeline_contract() -> None:
    allowed = {
        "UPSTREAM_DIFF.md",
        "babeldoc/format/pdf/high_level.py",
        "babeldoc/magazine/article_flow.py",
        "babeldoc/magazine/run_trace.py",
        "configs/article_flow.json",
        "configs/checkpoint_stages.json",
        "spec_checks/spec_check_article_cross_column.py",
    }
    changed = changed_files()
    source = (ROOT / "babeldoc/magazine/article_flow.py").read_text(encoding="utf-8")
    high_level = (ROOT / "babeldoc/format/pdf/high_level.py").read_text(
        encoding="utf-8"
    )
    check(
        "C07 changes only its declared implementation surface",
        changed <= allowed,
        str(sorted(changed - allowed)),
    )
    check(
        "ordinary and continuity targets share the C06 fit interface",
        "fit_text_to_slot(" in source and "article_flow.apply(" in high_level,
    )
    check(
        "article flow runs after final target and indent policy on the LLM-only path",
        high_level.index("paren_dedup.apply(")
        < high_level.index("indent_policy.apply(")
        < high_level.index("article_flow.apply(")
        < high_level.index("typesetting_stage = Typesetting("),
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
    check_long_target_crosses_column()
    check_short_targets_release_capacity()
    check_detector_failure_rolls_back()
    check_trace_failure_rolls_back()
    check_unsupported_page_is_inert()
    check_scope_and_pipeline_contract()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} article-flow checks")
        for failure in FAILURES:
            print(f" - {failure}")
        return 1
    print(f"PASS: {CHECKS} article-flow checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
