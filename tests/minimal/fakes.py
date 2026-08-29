from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import PdfParagraph
from babeldoc.format.pdf.document_il import PdfStyle
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import ArticlePolicyEvidence
from babeldoc.magazine.article_ir import ArticleRegionSlot
from babeldoc.magazine.article_ir import SourceElementRef


class FixedWidthFont:
    font_id = "target-body"
    name = "target-body"
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
        self.fontid2font = {self.base_font.font_id: self.base_font}

    def map(self, _original_font, _character: str):
        return self.base_font


class Placeholder:
    def __init__(self, token: str) -> None:
        self.placeholder = token
        self.regex_pattern = re.escape(token)


class TranslateInput:
    def __init__(self, style: PdfStyle, placeholders=()) -> None:
        self.base_style = style
        self.placeholders = list(placeholders)
        self.original_placeholder_tokens = {}

    def get_placeholders_hint(self):
        return None


class RecordingLLMTracker:
    def __init__(self) -> None:
        self.inputs = []
        self.outputs = []

    def set_input(self, value) -> None:
        self.inputs.append(value)

    def set_output(self, value) -> None:
        self.outputs.append(value)


class RecordingParagraphTracker:
    def __init__(self) -> None:
        self.output = None
        self.llm_trackers: list[RecordingLLMTracker] = []

    def new_llm_translate_tracker(self) -> RecordingLLMTracker:
        tracker = RecordingLLMTracker()
        self.llm_trackers.append(tracker)
        return tracker

    def last_llm_translate_tracker(self):
        return self.llm_trackers[-1] if self.llm_trackers else None

    def set_output(self, value) -> None:
        self.output = value

    def record_multi_paragraph_id(self, _value) -> None:
        pass

    def record_multi_paragraph_index(self, _value) -> None:
        pass


class RecordingTracker:
    def new_cross_page(self):
        return self

    def new_cross_column(self):
        return self

    def new_page(self):
        return self

    def new_paragraph(self) -> RecordingParagraphTracker:
        return RecordingParagraphTracker()


class RecordingEngine:
    def __init__(self, response: str) -> None:
        self.response = response
        self.llm_calls: list[tuple[str, dict]] = []
        self.member_calls = 0

    def llm_translate(self, prompt, **kwargs) -> str:
        self.llm_calls.append((prompt, kwargs))
        return self.response

    def translate(self, _source: str) -> str:
        self.member_calls += 1
        raise AssertionError("member-level provider translation is forbidden")


class StubILTranslator:
    def __init__(self, font_mapper: FixedWidthMapper) -> None:
        self.font_mapper = font_mapper
        self.prepared: dict[int, TranslateInput] = {}
        self.posted: list[int] = []
        self.post_attempts = 0
        self.fail_post_at: int | None = None

    def pre_translate_paragraph(
        self, paragraph, _tracker, _page_font_map, _xobj_font_map
    ):
        translate_input = self.prepared.get(
            id(paragraph), TranslateInput(paragraph.pdf_style)
        )
        return paragraph.unicode, translate_input

    def post_translate_paragraph(
        self, paragraph, tracker, _translate_input, translated_text
    ) -> None:
        self.post_attempts += 1
        if self.fail_post_at == self.post_attempts:
            raise RuntimeError("injected writeback failure")
        tracker.set_output(translated_text)
        paragraph.unicode = translated_text
        paragraph.pdf_paragraph_composition = []
        self.posted.append(id(paragraph))


class StubChainTranslator:
    def __init__(
        self,
        work: Path,
        response: str,
        font_mapper: FixedWidthMapper | None = None,
    ) -> None:
        work.mkdir(parents=True, exist_ok=True)

        def working_file(name: str):
            work.mkdir(parents=True, exist_ok=True)
            return work / name

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
            get_working_file_path=working_file,
        )
        self.translate_engine = RecordingEngine(response)
        self.il_translator = StubILTranslator(font_mapper or FixedWidthMapper())
        self.total_count = 0
        self.ok_count = 0
        self.article_briefs: list[str | None] = []

    def _build_font_maps(self, _page):
        return {"body": FixedWidthFont()}, {}

    @staticmethod
    def calc_token_count(text: str) -> int:
        return max(1, len(text) // 4)

    def _build_llm_prompt(
        self,
        *,
        json_input_str: str,
        article_brief: str | None = None,
        **_kwargs,
    ) -> str:
        self.article_briefs.append(article_brief)
        return json_input_str

    @staticmethod
    def _clean_json_output(output: str) -> str:
        return output


class RecordingExecutor:
    def __init__(self) -> None:
        self.submissions = []

    def submit(self, function, *args, **kwargs):
        self.submissions.append((function, args, kwargs))
        return SimpleNamespace()


def document_digest(document) -> str:
    payload = json.dumps(
        asdict(document), ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _paragraph(
    text: str,
    debug_id: str,
    box: tuple[float, float, float, float],
    *,
    label: str = "text",
    chain_id: str | None = None,
    chain_index: int | None = None,
) -> PdfParagraph:
    composition = il_version_1.PdfParagraphComposition(
        pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
            pdf_style=PdfStyle(font_id="body", font_size=10.0),
            unicode=text,
        )
    )
    return PdfParagraph(
        box=Box(*box),
        pdf_style=PdfStyle(font_id="body", font_size=10.0),
        pdf_paragraph_composition=[composition],
        unicode=text,
        debug_id=debug_id,
        layout_label=label,
        chain_id=chain_id,
        chain_index=chain_index,
    )


def _page(number: int, paragraphs: list[PdfParagraph]):
    box = Box(0.0, 0.0, 120.0, 100.0)
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=box),
        cropbox=il_version_1.Cropbox(box=box),
        pdf_font=[il_version_1.PdfFont(font_id="body", name="Fixed")],
        pdf_paragraph=paragraphs,
        base_operations=il_version_1.BaseOperations(value=""),
        page_number=number,
        unit="point",
    )


def make_chain_fixture(target: str, work: Path, boxes=None, sources=None):
    """One four member chain over two pages, or the shape a caller asks for.

    ``boxes`` and ``sources`` let a caller give the members boxes of different
    heights and sources of different lengths, which is what it takes to put a
    share estimate anywhere but a box edge. The defaults are the four equal
    boxes and equal sources every existing caller gets, so passing neither
    leaves the fixture exactly as it was.
    """
    boxes = (
        (
            (0.0, 0.0, 50.0, 15.0),
            (60.0, 0.0, 110.0, 15.0),
            (0.0, 0.0, 50.0, 15.0),
            (60.0, 0.0, 110.0, 15.0),
        )
        if boxes is None
        else tuple(tuple(float(value) for value in box) for box in boxes)
    )
    sources = (
        ("source member",) * len(boxes) if sources is None else tuple(sources)
    )
    if len(sources) != len(boxes):
        raise ValueError("one source per box is needed to build a chain fixture")
    paragraphs = [
        _paragraph(
            source,
            f"member-{index}",
            box,
            chain_id="raw-chain",
            chain_index=index,
        )
        for index, (box, source) in enumerate(zip(boxes, sources, strict=True))
    ]
    half = (len(boxes) + 1) // 2
    document = il_version_1.Document(
        page=[_page(0, paragraphs[:half]), _page(1, paragraphs[half:])],
        total_pages=2,
    )
    refs = tuple(
        f"p{1 if index < half else 2}#{index if index < half else index - half}"
        for index in range(len(boxes))
    )
    elements = tuple(
        SourceElementRef(
            source_ref=reference,
            page=1 if index < half else 2,
            column=index % half if half else 0,
            reading_order=index,
            role="text",
            source_box=boxes[index],
            source_text_hash=hashlib.sha256(
                sources[index].encode("utf-8")
            ).hexdigest(),
            style_hash="fixed-style",
        )
        for index, reference in enumerate(refs)
    )
    slots = tuple(
        ArticleRegionSlot(
            article_id="article-a",
            page=1 if index < half else 2,
            column=index % half if half else 0,
            slot_order=index,
            box=boxes[index],
            fixed_obstacle_refs=(),
            capacity_hint=750.0,
        )
        for index in range(len(boxes))
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
    response = json.dumps([{"id": 0, "output": target}], ensure_ascii=False)
    translator = StubChainTranslator(work, response)
    return document, article_ir, paragraphs, translator


def make_article_context_fixture():
    rows = (
        ("Feature A", "a-title", (0.0, 80.0, 50.0, 95.0), "title", None, None),
        ("Article A opening", "a-open", (0.0, 50.0, 50.0, 65.0), "text", "raw-a", 0),
        ("Article A continues", "a-next", (0.0, 70.0, 50.0, 85.0), "text", "raw-a", 1),
        ("Article A ordinary", "a-ordinary", (0.0, 40.0, 50.0, 55.0), "text", None, None),
        ("Feature B", "b-title", (0.0, 80.0, 50.0, 95.0), "title", None, None),
        ("Article B opening", "b-open", (0.0, 50.0, 50.0, 65.0), "text", None, None),
    )
    paragraphs = [
        _paragraph(text, debug_id, box, label=label, chain_id=chain, chain_index=index)
        for text, debug_id, box, label, chain, index in rows
    ]
    document = il_version_1.Document(
        page=[
            _page(0, paragraphs[:2]),
            _page(1, paragraphs[2:4]),
            _page(2, paragraphs[4:]),
        ],
        total_pages=3,
    )
    specs = (
        ("p1#0", 1, 0, 0, "title", "Feature A"),
        ("p1#1", 1, 1, 1, "text", "Article A opening"),
        ("p2#0", 2, 0, 2, "text", "Article A continues"),
        ("p2#1", 2, 1, 3, "text", "Article A ordinary"),
        ("p3#0", 3, 0, 4, "title", "Feature B"),
        ("p3#1", 3, 1, 5, "text", "Article B opening"),
    )
    elements = {
        reference: SourceElementRef(
            source_ref=reference,
            page=page,
            column=column,
            reading_order=order,
            role=role,
            source_box=None,
            source_text_hash=hashlib.sha256(text.encode()).hexdigest(),
            style_hash="fixed-style",
        )
        for reference, page, column, order, role, text in specs
    }
    article_a_refs = ("p1#0", "p1#1", "p2#0", "p2#1")
    article_b_refs = ("p3#0", "p3#1")
    article_a = ArticleIR(
        article_id="article-a",
        pages=(1, 2),
        elements=tuple(elements[ref] for ref in article_a_refs),
        slots=(),
        chain_ids=("chain-a",),
        policy_evidence=(),
    )
    article_b = ArticleIR(
        article_id="article-b",
        pages=(3,),
        elements=tuple(elements[ref] for ref in article_b_refs),
        slots=(),
        chain_ids=(),
        policy_evidence=(),
    )
    article_ir = ArticleDocumentIR(
        articles=(article_a, article_b),
        by_page={1: "article-a", 2: "article-a", 3: "article-b"},
        by_element={
            **dict.fromkeys(article_a_refs, "article-a"),
            **dict.fromkeys(article_b_refs, "article-b"),
        },
        by_chain={"chain-a": "article-a"},
        by_chain_member={"p1#1": "chain-a", "p2#0": "chain-a"},
    )
    return document, article_ir, paragraphs
