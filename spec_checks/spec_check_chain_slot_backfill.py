"""Offline contract checks for measured continuity-chain slot backfill."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spec_checks.delivery_commits import delivery_files  # noqa: E402

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
from babeldoc.format.pdf.document_il.midend.typesetting import (  # noqa: E402
    LINE_HEAD_FORBIDDEN_PUNCTUATION,
)
from babeldoc.format.pdf.document_il.midend.typesetting import (  # noqa: E402
    LINE_TAIL_FORBIDDEN_PUNCTUATION,
)
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting  # noqa: E402
from babeldoc.magazine import chain_backfill  # noqa: E402
from babeldoc.magazine import chain_translation  # noqa: E402
from babeldoc.magazine.article_context import EMPTY_CONTEXT  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticlePolicyEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ArticleRegionSlot  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.run_trace import ALLOCATION_RELEASED  # noqa: E402
from babeldoc.magazine.run_trace import ChainResultState  # noqa: E402
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
    font_id = "target-body"
    name = "target-body"
    is_bold = False
    is_italic = False
    is_monospaced = False
    is_serif = True

    @staticmethod
    def char_lengths(text: str, font_size: float):
        return tuple(font_size * 0.5 for _char in text)


class FixedWidthMapper:
    def __init__(self) -> None:
        self.base_font = FixedWidthFont()

    def map(self, _original_font, _character: str):
        return self.base_font


class TranslateInput:
    def __init__(self, style: PdfStyle) -> None:
        self.base_style = style
        self.placeholders = []
        self.original_placeholder_tokens = {}

    def get_placeholders_hint(self):
        return None


class LLMTracker:
    def set_input(self, _value) -> None:
        pass

    def set_output(self, _value) -> None:
        pass


class ParagraphTracker:
    def __init__(self) -> None:
        self.output = None

    def new_llm_translate_tracker(self) -> LLMTracker:
        return LLMTracker()

    def last_llm_translate_tracker(self):
        return None

    def set_output(self, value) -> None:
        self.output = value


class Tracker:
    def new_cross_page(self):
        return self

    def new_paragraph(self) -> ParagraphTracker:
        return ParagraphTracker()


class SpyEngine:
    def __init__(self, target: str) -> None:
        self.target = target
        self.calls = 0

    def llm_translate(self, _prompt, rate_limit_params=None) -> str:
        self.calls += 1
        return json.dumps([{"id": 0, "output": self.target}], ensure_ascii=False)


class StubILTranslator:
    def __init__(self, font_mapper) -> None:
        self.font_mapper = font_mapper

    def pre_translate_paragraph(
        self, paragraph, _tracker, _page_font_map, _xobj_font_map
    ):
        return paragraph.unicode, TranslateInput(paragraph.pdf_style)

    def post_translate_paragraph(
        self, paragraph, tracker, _translate_input, translated_text
    ) -> None:
        tracker.set_output(translated_text)
        paragraph.unicode = translated_text
        paragraph.pdf_paragraph_composition = []


class StubTranslator:
    def __init__(self, docs, work: Path, target: str, font_mapper) -> None:
        self.translation_config = SimpleNamespace(
            lang_out="zh",
            primary_font_family=None,
            magazine_chain_cut_align=False,
            magazine_short_unit=False,
            add_formula_placehold_hint=False,
            shared_context_cross_split_part=SimpleNamespace(
                first_paragraph=None,
                recent_title_paragraph=None,
            ),
            get_working_file_path=lambda name: work / name,
        )
        self.translate_engine = SpyEngine(target)
        self.il_translator = StubILTranslator(font_mapper)
        self.run_trace = RunTrace.from_document(docs[0], docs[1])
        self.total_count = 0
        self.ok_count = 0

    def _build_font_maps(self, _page):
        return {"body": FixedWidthFont()}, {}

    @staticmethod
    def calc_token_count(text: str) -> int:
        return max(1, len(text) // 4)

    @staticmethod
    def _build_llm_prompt(*, json_input_str: str, **_kwargs) -> str:
        return json_input_str

    @staticmethod
    def _trace_prompt_config(prompt: str) -> dict:
        return {"prompt": prompt}

    @staticmethod
    def _clean_json_output(output: str) -> str:
        return output


def il_digest(document) -> str:
    payload = json.dumps(
        asdict(document), ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def style_hash(style: PdfStyle) -> str:
    return hash_record(
        {
            "font_id": style.font_id,
            "font_size": style.font_size,
            "graphic_state": None,
        }
    )


def fixture(target: str):
    style = PdfStyle(font_id="body", font_size=10.0)
    boxes = (
        (0.0, 0.0, 50.0, 15.0),
        (60.0, 0.0, 110.0, 15.0),
        (0.0, 0.0, 50.0, 15.0),
        (60.0, 0.0, 110.0, 15.0),
    )
    paragraphs = [
        PdfParagraph(
            box=Box(*box),
            pdf_style=style,
            unicode="甲乙丙丁戊",
            debug_id=f"volatile-{index}",
            layout_label="text",
            chain_id="raw-chain",
            chain_index=index,
        )
        for index, box in enumerate(boxes)
    ]
    pages = [
        il_version_1.Page(
            page_number=0,
            mediabox=il_version_1.Mediabox(box=Box(0.0, 0.0, 120.0, 100.0)),
            cropbox=il_version_1.Cropbox(box=Box(0.0, 0.0, 120.0, 100.0)),
            pdf_figure=[il_version_1.PdfFigure(box=Box(116.0, 90.0, 119.0, 99.0))],
            pdf_paragraph=paragraphs[:2],
        ),
        il_version_1.Page(
            page_number=1,
            mediabox=il_version_1.Mediabox(box=Box(0.0, 0.0, 120.0, 100.0)),
            cropbox=il_version_1.Cropbox(box=Box(0.0, 0.0, 120.0, 100.0)),
            pdf_figure=[il_version_1.PdfFigure(box=Box(116.0, 90.0, 119.0, 99.0))],
            pdf_paragraph=paragraphs[2:],
        ),
    ]
    document = il_version_1.Document(page=pages)
    refs = ("p1#0", "p1#1", "p2#0", "p2#1")
    elements = tuple(
        SourceElementRef(
            source_ref=reference,
            page=1 if index < 2 else 2,
            column=index % 2,
            reading_order=index,
            role="text",
            source_box=boxes[index],
            source_text_hash=hashlib.sha256("甲乙丙丁戊".encode()).hexdigest(),
            style_hash=style_hash(style),
        )
        for index, reference in enumerate(refs)
    )
    slots = tuple(
        ArticleRegionSlot(
            article_id="article-a",
            page=1 if index < 2 else 2,
            column=index % 2,
            slot_order=index,
            box=boxes[index],
            fixed_obstacle_refs=(f"fixed-{index}",),
            capacity_hint=750.0,
        )
        for index in range(4)
    )
    article = ArticleIR(
        article_id="article-a",
        pages=(1, 2),
        elements=elements,
        slots=slots,
        chain_ids=("chain-canonical",),
        policy_evidence=(
            ArticlePolicyEvidence(1, "opens", "feature", None, True),
            ArticlePolicyEvidence(2, "member", "feature", None, True),
        ),
    )
    article_ir = ArticleDocumentIR(
        articles=(article,),
        by_page={1: "article-a", 2: "article-a"},
        by_element=dict.fromkeys(refs, "article-a"),
        by_chain={"chain-canonical": "article-a"},
        by_chain_member=dict.fromkeys(refs, "chain-canonical"),
    )
    mapper = FixedWidthMapper()
    work = Path(tempfile.mkdtemp(prefix="babeldoc-c06-"))
    translator = StubTranslator((document, article_ir), work, target, mapper)
    return document, article_ir, paragraphs, translator, mapper


def check_pure_typesetter_measurement() -> None:
    document, _article_ir, _paragraphs, _translator, mapper = fixture("甲")
    before = il_digest(document)
    config = chain_backfill.load_backfill_config()
    stage = Typesetting(
        SimpleNamespace(lang_out="zh", primary_font_family=None),
        font_mapper=mapper,
    )
    result = stage.fit_text_to_slot(
        "甲乙丙丁戊己",
        PdfStyle(font_id="body", font_size=10.0),
        "zh",
        Box(0.0, 0.0, 25.0, 15.0),
        paragraph_start=True,
        original_font=FixedWidthFont(),
        minimum_font_size=config.slot_min_font_size,
        fit_tolerance=config.slot_fit_tolerance,
        line_skip=config.capacity.line_skip_cjk,
        line_head_forbidden=config.line_head_forbidden,
        line_tail_forbidden=config.line_tail_forbidden,
    )
    after = il_digest(document)
    check(
        "dry-run measurement consumes the largest real-layout prefix",
        result.consumed_range == (0, 3)
        and result.status == "fit_prefix"
        and len(result.line_metrics) == 1
        and result.ink_bounds is not None,
        str(result),
    )
    check("dry-run leaves the Document IL digest unchanged", before == after)


def check_legal_boundaries() -> None:
    config = chain_backfill.load_backfill_config()
    mapper = FixedWidthMapper()

    def fit(text: str, language: str, width: float, protected=()):
        stage = Typesetting(
            SimpleNamespace(lang_out=language, primary_font_family=None),
            font_mapper=mapper,
        )
        return stage.fit_text_to_slot(
            text,
            PdfStyle(font_id="body", font_size=10.0),
            language,
            Box(0.0, 0.0, width, 15.0),
            paragraph_start=False,
            original_font=FixedWidthFont(),
            protected_ranges=protected,
            minimum_font_size=config.slot_min_font_size,
            fit_tolerance=config.slot_fit_tolerance,
            line_skip=(
                config.capacity.line_skip_cjk
                if config.capacity.is_cjk_target(language)
                else config.capacity.line_skip_latin
            ),
            line_head_forbidden=config.line_head_forbidden,
            line_tail_forbidden=config.line_tail_forbidden,
        )

    english = fit("alphabet soup", "en", 45.0)
    placeholder = fit("abc [[X]] def", "en", 20.0, ((4, 9),))
    closing = fit("甲乙，丙", "zh", 10.0)
    opening = fit("甲乙《丙", "zh", 15.0)
    grapheme = fit("A e\u0301 B", "en", 15.0)
    check(
        "Latin words and protected placeholders are never split",
        english.text == "alphabet " and placeholder.text == "abc ",
        f"english={english.text!r}, placeholder={placeholder.text!r}",
    )
    check(
        "CJK line-head and opening punctuation rules constrain cuts",
        closing.text == "甲乙，" and opening.text == "甲乙",
        f"closing={closing.text!r}, opening={opening.text!r}",
    )
    check(
        "grapheme clusters remain whole",
        not grapheme.text.endswith("\u0301") or grapheme.text.endswith("e\u0301"),
        repr(grapheme.text),
    )


def run_chain(target: str):
    document, article_ir, paragraphs, translator, _mapper = fixture(target)
    page_count = len(document.page)
    page_boxes = [
        (page.mediabox, page.cropbox) for page in document.page
    ]
    fixed_assets = [
        (tuple(page.pdf_figure), tuple(page.pdf_curve), tuple(page.pdf_form))
        for page in document.page
    ]
    plan = chain_translation.plan_chain_translation(
        translator,
        document,
        Tracker(),
        EMPTY_CONTEXT,
        article_ir,
    )
    plan.apply()
    return (
        plan,
        translator,
        document,
        paragraphs,
        page_count,
        page_boxes,
        fixed_assets,
    )


def check_target_ratios_and_ordered_slots() -> None:
    for ratio, length, used in ((0.6, 12, 2), (1.0, 20, 2), (1.8, 36, 4)):
        target = "译" * length
        (
            plan,
            translator,
            document,
            paragraphs,
            page_count,
            page_boxes,
            fixed_assets,
        ) = run_chain(target)
        entry = plan.entries[0]
        allocations = entry.allocation.fragments
        joined = "".join(item.text for item in allocations)
        occupied = [item for item in allocations if not item.released]
        released = [item for item in allocations if item.released]
        trace_fragments = sorted(
            translator.run_trace.fragments.values(), key=lambda item: item.order
        )
        check(
            f"{ratio:.1f}x target consumes ordered same-page and cross-page slots",
            joined == target
            and [item.slot_order for item in allocations] == [0, 1, 2, 3]
            and len(occupied) == used
            and all(item.slot_id for item in allocations),
            entry.as_record().__repr__(),
        )
        check(
            f"{ratio:.1f}x target is traced once with ranges and measurements",
            translator.translate_engine.calls == 1
            and len(trace_fragments) == 4
            and trace_fragments[0].text_start == 0
            and trace_fragments[-1].text_end == len(target)
            and all(item.slot_id for item in trace_fragments)
            and all(item.measurement_summary for item in trace_fragments),
        )
        check(
            f"{ratio:.1f}x released slots and final text conserve the target",
            len(released) == 4 - used
            and all(
                item.allocation_status == ALLOCATION_RELEASED
                for item in trace_fragments[used:]
            )
            and "".join(paragraph.unicode for paragraph in paragraphs) == target,
        )
        check(
            f"{ratio:.1f}x leaves fixed assets, page count and page boxes unchanged",
            len(document.page) == page_count
            and [(page.mediabox, page.cropbox) for page in document.page] == page_boxes
            and [
                (tuple(page.pdf_figure), tuple(page.pdf_curve), tuple(page.pdf_form))
                for page in document.page
            ]
            == fixed_assets,
        )


def check_overflow_rollback() -> None:
    document, article_ir, paragraphs, translator, _mapper = fixture("溢" * 41)
    before = il_digest(document)
    plan = chain_translation.plan_chain_translation(
        translator,
        document,
        Tracker(),
        EMPTY_CONTEXT,
        article_ir,
    )
    plan.apply()
    outcome = plan.outcomes[0]
    request = next(iter(translator.run_trace.requests.values()))
    check(
        "slot exhaustion rolls back the whole chain and reports overflow",
        not plan.entries
        and il_digest(document) == before
        and outcome["result_state"] == ChainResultState.FAILED_WITH_ISSUE.value
        and outcome["reason"] == chain_translation.ESCALATION_OVERFLOW
        and request.status == "failed"
        and request.issue == chain_translation.ESCALATION_OVERFLOW,
        str(outcome),
    )
    check(
        "overflow still makes exactly one translator call",
        translator.translate_engine.calls == 1,
    )
    check(
        "overflow leaves every source member intact",
        all(item.unicode == "甲乙丙丁戊" for item in paragraphs),
    )


def check_writeback_rollback() -> None:
    document, article_ir, _paragraphs, translator, _mapper = fixture("译" * 10)
    before = il_digest(document)
    original_post = translator.il_translator.post_translate_paragraph
    calls = 0

    def fail_second(paragraph, tracker, translate_input, translated_text):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected writeback failure")
        original_post(paragraph, tracker, translate_input, translated_text)

    translator.il_translator.post_translate_paragraph = fail_second
    plan = chain_translation.plan_chain_translation(
        translator,
        document,
        Tracker(),
        EMPTY_CONTEXT,
        article_ir,
    )
    request = next(iter(translator.run_trace.requests.values()))
    plan.apply()
    outcome = plan.outcomes[0]
    check(
        "writeback failure restores the complete touched set and trace allocation",
        not plan.entries
        and il_digest(document) == before
        and request.status == "failed"
        and outcome["result_state"] == ChainResultState.FAILED_WITH_ISSUE.value
        and all(not fragment.active for fragment in translator.run_trace.fragments.values()),
        str(outcome),
    )


def changed_files() -> set[str]:
    return delivery_files("C06", ROOT)


def check_scope_and_source_contract() -> None:
    allowed = {
        "UPSTREAM_DIFF.md",
        "babeldoc/format/pdf/document_il/midend/typesetting.py",
        "babeldoc/magazine/chain_backfill.py",
        "babeldoc/magazine/chain_translation.py",
        "babeldoc/magazine/run_trace.py",
        "configs/chain_translation.json",
        "spec_checks/spec_check_chain_slot_backfill.py",
    }
    changed = changed_files()
    source = (ROOT / "babeldoc/magazine/chain_translation.py").read_text(
        encoding="utf-8"
    )
    config = chain_backfill.load_backfill_config()
    check(
        "C06 changes only its declared implementation surface",
        changed <= allowed,
        str(sorted(changed - allowed)),
    )
    check(
        "chain allocation calls the real typesetter fit interface",
        "fit_text_to_slot(" in source and "backfill.redistribute(" not in source,
    )
    check(
        "configured punctuation classes match the real typesetter",
        config.line_head_forbidden == LINE_HEAD_FORBIDDEN_PUNCTUATION
        and config.line_tail_forbidden == LINE_TAIL_FORBIDDEN_PUNCTUATION,
    )
    check(
        "legacy translator and frozen IL schema remain untouched",
        not any(
            path.endswith("il_translator.py")
            or path.endswith((".xsd", ".rng", ".rnc"))
            for path in changed
        ),
        str(sorted(changed)),
    )


def main() -> int:
    check_pure_typesetter_measurement()
    check_legal_boundaries()
    check_target_ratios_and_ordered_slots()
    check_overflow_rollback()
    check_writeback_rollback()
    check_scope_and_source_contract()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} chain slot checks")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(f"PASS: {CHECKS} chain slot checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
