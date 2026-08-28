from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.format.pdf.translation_config import SharedContextCrossSplitPart
from babeldoc.magazine import drop_cap
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import drop_cap_render
from babeldoc.magazine import minimal_detection
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import ArticlePolicyEvidence
from babeldoc.magazine.article_ir import ArticleRegionSlot
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.line_split import paragraph_characters


class RecordingTranslator:
    def __init__(self) -> None:
        self.requests = 0

    def translate(self, *_args, **_kwargs):
        self.requests += 1
        raise AssertionError("a test translator must never make a request")

    def llm_translate(self, *_args, **_kwargs):
        self.requests += 1
        raise AssertionError("a test translator must never make a request")


class RuntimeConfig:
    def __init__(
        self,
        working_dir: Path,
        *,
        sample: str = "Synthetic",
        language: str = "en",
    ) -> None:
        self.working_dir = working_dir
        self.input_file = str(working_dir / f"{sample}.pdf")
        self.lang_out = language
        self.magazine_article_group = True
        self.magazine_drop_cap_mark = True
        self.magazine_drop_cap_apply = True
        self.magazine_drop_cap_render = True
        self.auto_extract_glossary = False
        self.translator = RecordingTranslator()
        self.term_translator = RecordingTranslator()
        self.shared_context_cross_split_part = SharedContextCrossSplitPart()
        self.shared_context_cross_split_part.initialize_glossaries([])

    def get_term_extraction_translator(self):
        return self.term_translator

    def get_working_file_path(self, name: str) -> str:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return str(self.working_dir / name)


@dataclass(frozen=True, slots=True)
class ControlledMetric:
    ink_box_em: tuple[float, float, float, float]
    advance_em: float
    font_id: str
    glyph_id: int
    source: str = "controlled-font"


def metric_for(character) -> ControlledMetric:
    text = character.char_unicode or " "
    font_id = character.pdf_style.font_id
    if text in "gjpqy":
        box = (0.04, -0.22, 0.48, 0.54)
        advance = 0.56
    elif ord(text[0]) > 0x2FFF:
        box = (0.05, -0.10, 0.95, 0.90)
        advance = 1.0
    else:
        box = (0.02, 0.0, 0.65, 0.72)
        advance = 0.67
    return ControlledMetric(box, advance, font_id, ord(text[0]))


def pdf_style(
    font_id: str = "target-body",
    font_size: float = 10.0,
    instruction: str | None = None,
) -> il.PdfStyle:
    return il.PdfStyle(
        font_id=font_id,
        font_size=font_size,
        graphic_state=il.GraphicState(
            passthrough_per_char_instruction=instruction
        ),
    )


def pdf_character(
    text: str,
    x: float,
    baseline: float,
    *,
    font_id: str = "target-body",
    font_size: float = 10.0,
    width: float = 6.0,
    xobj_id: int | None = 0,
) -> il.PdfCharacter:
    return il.PdfCharacter(
        char_unicode=text,
        box=il.Box(x=x, y=baseline, x2=x + width, y2=baseline + font_size),
        pdf_style=pdf_style(font_id, font_size),
        advance=width,
        xobj_id=xobj_id,
    )


def source_drop_cap_paragraph(initial: str = "A") -> il.PdfParagraph:
    large = pdf_style("source-initial", 30.0, "0.2 0.4 0.6 rg")
    body = pdf_style("source-body", 10.0, "0 g")
    head = [
        il.PdfCharacter(
            char_unicode=initial,
            box=il.Box(10.0, 65.0, 28.0, 95.0),
            pdf_style=large,
            advance=18.0,
            xobj_id=0,
        ),
        il.PdfCharacter(
            char_unicode=" ",
            box=il.Box(28.0, 65.0, 34.0, 95.0),
            pdf_style=large,
            advance=6.0,
            xobj_id=None,
        ),
    ]
    text = "body text continues on the next measured line"
    tail = []
    x = 34.0
    for index, glyph in enumerate(text):
        baseline = 80.0 if index < 20 else 65.0
        if index == 20:
            x = 10.0
        tail.append(
            il.PdfCharacter(
                char_unicode=glyph,
                box=il.Box(x, baseline, x + 6.0, baseline + 10.0),
                pdf_style=body,
                advance=6.0,
                xobj_id=0,
            )
        )
        x += 6.0
    return il.PdfParagraph(
        box=il.Box(10.0, 50.0, 155.0, 95.0),
        pdf_style=body,
        unicode=f"{initial} {text}",
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_characters=il.PdfSameStyleCharacters(
                    pdf_style=large,
                    pdf_character=head,
                )
            ),
            il.PdfParagraphComposition(
                pdf_same_style_characters=il.PdfSameStyleCharacters(
                    pdf_style=body,
                    pdf_character=tail,
                )
            ),
        ],
        layout_label="plain text",
        debug_id="source-drop-cap",
    )


def ordinary_paragraph(text: str = "ordinary paragraph") -> il.PdfParagraph:
    style = pdf_style()
    characters = [
        pdf_character(glyph, 10.0 + index * 6.0, 65.0)
        for index, glyph in enumerate(text)
    ]
    return il.PdfParagraph(
        box=il.Box(10.0, 60.0, 160.0, 78.0),
        pdf_style=style,
        unicode=text,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_characters=il.PdfSameStyleCharacters(
                    pdf_style=style,
                    pdf_character=characters,
                )
            )
        ],
        layout_label="plain text",
    )


def english_render_paragraph(
    text: str = '"[Again and again across the measured second line',
) -> il.PdfParagraph:
    characters = []
    x = 10.0
    for index, glyph in enumerate(text):
        baseline = 80.0 if index < 20 else 65.0
        if index == 20:
            x = 10.0
        characters.append(pdf_character(glyph, x, baseline))
        x += 6.0
    return il.PdfParagraph(
        box=il.Box(10.0, 50.0, 150.0, 90.0),
        pdf_style=characters[0].pdf_style,
        unicode=text,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=character)
            for character in characters
        ],
        drop_cap_candidate=True,
        drop_cap_decision="keep",
        layout_label="plain text",
    )


def chinese_render_paragraph(
    text: str = "“（中文排版需要依据真实字形度量完成两行嵌入并在第三行恢复栏宽",
) -> il.PdfParagraph:
    per_line = (len(text) + 2) // 3
    characters = []
    for index, glyph in enumerate(text):
        line = min(index // per_line, 2)
        column = index - line * per_line
        characters.append(
            pdf_character(
                glyph,
                10.0 + column * 10.0,
                80.0 - line * 15.0,
                width=10.0,
            )
        )
    return il.PdfParagraph(
        box=il.Box(10.0, 20.0, 140.0, 92.0),
        pdf_style=characters[0].pdf_style,
        unicode=text,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=character)
            for character in characters
        ],
        drop_cap_candidate=True,
        drop_cap_decision="keep",
        layout_label="plain text",
    )


def make_document(
    paragraphs: list[il.PdfParagraph],
    *,
    physical_page: int = 7,
    total_pages: int = 8,
) -> il.Document:
    page_box = il.Box(0.0, 0.0, 180.0, 120.0)
    return il.Document(
        page=[
            il.Page(
                page_number=physical_page - 1,
                unit="pt",
                mediabox=il.Mediabox(box=page_box),
                cropbox=il.Cropbox(box=copy.deepcopy(page_box)),
                pdf_paragraph=paragraphs,
            )
        ],
        total_pages=total_pages,
    )


def make_article_ir(
    paragraphs: list[il.PdfParagraph],
    *,
    canonical_count: int | None = None,
) -> ArticleDocumentIR:
    canonical = paragraphs if canonical_count is None else paragraphs[:canonical_count]
    article_id = "article-fixture"
    elements = tuple(
        SourceElementRef(
            source_ref=f"p1#{index}",
            page=1,
            column=0,
            reading_order=index,
            role="body",
            source_box=(
                float(paragraph.box.x),
                float(paragraph.box.y),
                float(paragraph.box.x2),
                float(paragraph.box.y2),
            ),
            source_text_hash=hashlib.sha256(
                (paragraph.unicode or "").encode("utf-8")
            ).hexdigest(),
            style_hash=drop_cap_intent.style_hash(paragraph.pdf_style),
        )
        for index, paragraph in enumerate(canonical)
    )
    article = ArticleIR(
        article_id=article_id,
        pages=(1,),
        elements=elements,
        slots=(
            ArticleRegionSlot(
                article_id=article_id,
                page=1,
                column=0,
                slot_order=0,
                box=(0.0, 0.0, 180.0, 120.0),
                fixed_obstacle_refs=(),
                capacity_hint=21600.0,
            ),
        ),
        chain_ids=(),
        policy_evidence=(ArticlePolicyEvidence(1, "body", None, None, True),),
    )
    return ArticleDocumentIR(
        articles=(article,),
        by_page={1: article_id},
        by_element={element.source_ref: article_id for element in elements},
        by_chain={},
    )


def document_digest(document: il.Document) -> str:
    payload = json.dumps(asdict(document), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def frozen_color() -> drop_cap_intent.FrozenColorState:
    return drop_cap_intent.FrozenColorState(
        fill=drop_cap_intent.NormalizedColor(
            rgb=(0.2, 0.4, 0.6),
            source_space="DeviceRGB",
            source_components=(0.2, 0.4, 0.6),
            operator="rg",
        ),
        stroke=drop_cap_intent.NormalizedColor(
            rgb=(0.6, 0.4, 0.2),
            source_space="DeviceRGB",
            source_components=(0.6, 0.4, 0.2),
            operator="RG",
        ),
        alpha=None,
        ext_gstate="/GSfixture gs",
        evidence=("controlled",),
    )


def direct_intent(policy: str):
    return SimpleNamespace(
        target_policy=policy,
        source_color=frozen_color(),
        source_style_hash="frozen-source-style",
        source_char="A",
        article_id="article-fixture",
    )


def geometry_guard(
    *,
    width: float = 180.0,
    obstacles=(),
) -> drop_cap_render.DecorativeGeometryGuard:
    return drop_cap_render.DecorativeGeometryGuard(
        page_box=(0.0, 0.0, width, 120.0),
        article_boxes=((0.0, 0.0, width, 120.0),),
        obstacles=tuple(obstacles),
    )


def register_render_intents(
    config: RuntimeConfig,
    paragraphs: list[il.PdfParagraph],
    *,
    decision: str = "keep",
) -> list[drop_cap_intent.DropCapIntent]:
    policy = (
        drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL
        if config.lang_out.startswith("zh")
        else drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL
    )
    intents = []
    for index, paragraph in enumerate(paragraphs):
        eligible = drop_cap_intent.eligible_initial(
            paragraph_characters(paragraph), policy
        )
        if eligible is None:
            raise AssertionError("fixture has no eligible target initial")
        item = drop_cap_intent.build_intent(
            source_ref=f"p7#{index}",
            article_id="article-fixture",
            paragraph=paragraph,
            source_character=eligible[1],
            target_policy=policy,
            config_version=1,
            decision_version=1,
        )
        item.source_color = frozen_color()
        item.decision = decision
        item.flatten_status = drop_cap_intent.FLATTEN_APPLIED
        if decision == "flatten":
            item.render_status = drop_cap_intent.RENDER_SKIPPED
        paragraph.drop_cap_candidate = True
        paragraph.drop_cap_decision = decision
        intents.append(item)
    drop_cap_intent.replace_intents(config, intents)
    return intents


@pytest.mark.parametrize("decision", ["keep", "flatten"])
def test_keep_and_flatten_offer_exactly_one_source_initial(
    tmp_path: Path,
    decision: str,
) -> None:
    paragraph = source_drop_cap_paragraph()
    docs = make_document([paragraph])
    article_ir = make_article_ir([paragraph])
    config = RuntimeConfig(tmp_path / decision)
    candidates = drop_cap.mark(
        config,
        [(7, docs.page[0])],
        article_document_ir=article_ir,
    )
    assert [candidate.reference for candidate in candidates] == ["p7#0"]
    manual = drop_cap.validate_manual_decisions(config, {"p7#0": decision})
    drop_cap.apply_decisions(config, [(7, docs.page[0])], manual)
    record = drop_cap.apply(config, [(7, docs.page[0])])
    assert record is not None and record["totals"]["decided"] == 1
    characters = paragraph_characters(paragraph)
    assert "".join(character.char_unicode or "" for character in characters) == (
        paragraph.unicode
    )
    assert paragraph.unicode.startswith("Abody")
    assert paragraph.unicode.count("A") == 1
    assert sum(character.char_unicode == "A" for character in characters) == 1
    intent = drop_cap_intent.intent_for(config, "p7#0")
    assert intent is not None
    assert intent.flatten_status == drop_cap_intent.FLATTEN_APPLIED
    if decision == "flatten":
        before = document_digest(docs)
        render = drop_cap_render.apply(
            config,
            docs,
            article_document_ir=article_ir,
            typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
        )
        assert render is not None and render["totals"]["set"] == 0
        assert render["paragraphs"] == []
        assert document_digest(docs) == before
        assert intent.render_status == drop_cap_intent.RENDER_SKIPPED


def test_render_uses_physical_report_and_local_canonical_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paragraph = english_render_paragraph()
    docs = make_document([paragraph])
    article_ir = make_article_ir([paragraph])
    config = RuntimeConfig(tmp_path / "coordinates")
    register_render_intents(config, [paragraph])
    seen = []
    original_guard = drop_cap_render._decorative_guard

    def recording_guard(page, local_page, index, local_ref, *args):
        seen.append((local_page, local_ref))
        return original_guard(page, local_page, index, local_ref, *args)

    def typed_refusal(_paragraph, _regime, _config, blank, **_kwargs):
        return drop_cap_render._refusal(blank, drop_cap_render.REVERT_COLLISION)

    monkeypatch.setattr(drop_cap_render, "_decorative_guard", recording_guard)
    monkeypatch.setattr(drop_cap_render, "set_one", typed_refusal)
    report = drop_cap_render.apply(
        config,
        docs,
        article_document_ir=article_ir,
        typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
    )
    assert seen == [(1, "p1#0")]
    assert report is not None
    assert report["paragraphs"][0]["paragraph"] == "p7#0"
    assert report["paragraphs"][0]["revert_reason"] == (
        drop_cap_render.REVERT_COLLISION
    )


def test_typed_candidate_refusal_rolls_back_only_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paragraph = english_render_paragraph()
    docs = make_document([paragraph])
    article_ir = make_article_ir([paragraph])
    config = RuntimeConfig(tmp_path / "typed")
    intent = register_render_intents(config, [paragraph])[0]
    before = document_digest(docs)

    def mutating_refusal(value, _regime, _config, blank, **_kwargs):
        paragraph_characters(value)[0].box.x += 25.0
        return drop_cap_render._refusal(blank, drop_cap_render.REVERT_COLLISION)

    monkeypatch.setattr(drop_cap_render, "set_one", mutating_refusal)
    report = drop_cap_render.apply(
        config,
        docs,
        article_document_ir=article_ir,
        typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
    )
    assert report is not None
    assert report["paragraphs"][0]["revert_reason"] == (
        drop_cap_render.REVERT_COLLISION
    )
    assert document_digest(docs) == before
    assert intent.render_status == drop_cap_intent.RENDER_FAILED


def test_unexpected_second_candidate_restores_entire_render_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paragraphs = [english_render_paragraph(), english_render_paragraph()]
    docs = make_document(paragraphs)
    article_ir = make_article_ir(paragraphs)
    config = RuntimeConfig(tmp_path / "unexpected")
    register_render_intents(config, paragraphs)
    before_document = document_digest(docs)
    before_intents = [
        intent.as_record()
        for intent in drop_cap_intent.intents_for(config).values()
    ]
    calls = 0

    class SentinelError(Exception):
        pass

    marker = SentinelError("second candidate failed")

    def injected_set(paragraph, _regime, _config, blank, **_kwargs):
        nonlocal calls
        calls += 1
        paragraph_characters(paragraph)[0].box.x += calls
        if calls == 2:
            raise marker
        outcome = dict(blank)
        outcome.update(
            {
                "set": True,
                "reverted": False,
                "revert_reason": None,
                "initial": paragraph_characters(paragraph)[0].char_unicode,
                "initial_char_count": 1,
                "reach": [10.0, 50.0, 20.0, 90.0],
                "collision_evidence": [],
                "detector_contract": {"missing_fields": [], "collision": []},
                "color_evidence": {},
                "style_evidence": {},
                "_target_index": 0,
            }
        )
        return outcome

    monkeypatch.setattr(drop_cap_render, "set_one", injected_set)
    monkeypatch.setattr(
        drop_cap_render,
        "_post_render_validation",
        lambda *_args: (None, {"checks": {}, "valid": True}),
    )
    with pytest.raises(SentinelError) as raised:
        drop_cap_render.apply(
            config,
            docs,
            article_document_ir=article_ir,
            typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
        )
    assert raised.value is marker
    assert calls == 2
    assert document_digest(docs) == before_document
    assert [
        intent.as_record()
        for intent in drop_cap_intent.intents_for(config).values()
    ] == before_intents


def _prepared_pipeline_state(config, docs, article_ir, typesetter):
    minimal_pipeline.configure(config)
    state = config.magazine_state
    state._structure_started = True
    state._structure_document_identity = id(docs)
    state._article_document_ir = article_ir
    state._translation_prep_started = True
    state._translation_prep_completed = True
    state._flow_started = True
    state._flow_completed = True
    state._flow_document_identity = id(docs)
    state._typesetter_identity = id(typesetter)
    state._detection_baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=tuple(
            (
                (page.page_number if page.page_number is not None else position) + 1,
                page,
            )
            for position, page in enumerate(docs.page)
        ),
    )
    return state


def test_after_typesetting_is_one_shot_after_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        minimal_pipeline,
        "_detect_and_repair",
        lambda _config, _docs, _typesetter, _state: None,
    )
    paragraph = english_render_paragraph()
    docs = make_document([paragraph])
    article_ir = make_article_ir([paragraph])
    success_config = RuntimeConfig(tmp_path / "pipeline-success")
    success_typesetter = SimpleNamespace(translation_config=success_config)
    success_state = _prepared_pipeline_state(
        success_config,
        docs,
        article_ir,
        success_typesetter,
    )
    expected = {"totals": {"set": 0}}
    monkeypatch.setattr(drop_cap_render, "apply", lambda *_args, **_kwargs: expected)
    assert (
        minimal_pipeline.after_typesetting(success_config, docs, success_typesetter)
        is expected
    )
    assert success_state.render_completed
    assert success_state.render_document_identity == id(docs)
    with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
        minimal_pipeline.after_typesetting(success_config, docs, success_typesetter)

    failed_config = RuntimeConfig(tmp_path / "pipeline-failure")
    failed_typesetter = SimpleNamespace(translation_config=failed_config)
    failed_state = _prepared_pipeline_state(
        failed_config,
        docs,
        article_ir,
        failed_typesetter,
    )

    class SentinelError(Exception):
        pass

    marker = SentinelError("report failure")

    def fail(*_args, **_kwargs):
        raise marker

    monkeypatch.setattr(drop_cap_render, "apply", fail)
    with pytest.raises(SentinelError) as raised:
        minimal_pipeline.after_typesetting(failed_config, docs, failed_typesetter)
    assert raised.value is marker
    assert failed_state.render_started and not failed_state.render_completed
    assert failed_state.render_report is None
    with pytest.raises(minimal_pipeline.MinimalPipelineStateError):
        minimal_pipeline.after_typesetting(failed_config, docs, failed_typesetter)


def test_recording_translators_remain_unused(tmp_path: Path) -> None:
    config = RuntimeConfig(tmp_path / "offline")
    assert config.translator.requests == 0
    assert config.term_translator.requests == 0
