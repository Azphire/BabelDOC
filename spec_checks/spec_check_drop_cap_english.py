from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import drop_cap_render as lane
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import ArticlePolicyEvidence
from babeldoc.magazine.article_ir import ArticleRegionSlot
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.article_ir import UnsupportedArticlePage
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.run_trace import RunTrace

GATE_SET = "fast"


@dataclass(frozen=True, slots=True)
class Metric:
    ink_box_em: tuple[float, float, float, float]
    advance_em: float
    source: str = "fixture-font"
    glyph_id: int = 1


METRICS = {
    "normal": Metric((0.02, 0.0, 0.65, 0.72), 0.67),
    "descender": Metric((0.04, -0.22, 0.48, 0.54), 0.56),
    "short": Metric((0.01, 0.02, 0.62, 0.50), 0.65),
    "tall": Metric((-0.03, -0.08, 0.72, 0.92), 0.70),
}


def metric_for(character) -> Metric:
    font_id = getattr(getattr(character, "pdf_style", None), "font_id", "")
    if font_id == "font-short":
        return METRICS["short"]
    if font_id == "font-tall":
        return METRICS["tall"]
    if (character.char_unicode or "") in "gjpqy":
        return METRICS["descender"]
    return METRICS["normal"]


def character(
    text: str,
    x: float,
    baseline: float,
    *,
    font_id: str = "fixture-font",
) -> il.PdfCharacter:
    style = il.PdfStyle(
        font_id=font_id,
        font_size=10.0,
        graphic_state=il.GraphicState(),
    )
    return il.PdfCharacter(
        char_unicode=text,
        box=il.Box(x=x, y=baseline, x2=x + 6.0, y2=baseline + 10.0),
        pdf_style=style,
        advance=6.0,
    )


def paragraph(
    text: str = "Again and again across the measured second line",
    *,
    font_id: str = "fixture-font",
    top: float = 90.0,
) -> il.PdfParagraph:
    chars = []
    x = 10.0
    for index, text_char in enumerate(text):
        baseline = 80.0 if index < 20 else 65.0
        if index == 20:
            x = 10.0
        chars.append(character(text_char, x, baseline, font_id=font_id))
        x += 6.0
    return il.PdfParagraph(
        box=il.Box(x=10.0, y=50.0, x2=150.0, y2=top),
        pdf_style=chars[0].pdf_style,
        unicode=text,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=item) for item in chars
        ],
        drop_cap_candidate=True,
        drop_cap_decision="keep",
        layout_label="plain text",
    )


def intent(*, color=None) -> SimpleNamespace:
    return SimpleNamespace(
        target_policy=drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL,
        source_color=color or drop_cap_intent.freeze_color(None),
        source_style_hash="source-style-fixture",
        source_char="目",
        article_id="article-fixture",
    )


def guard(*, obstacles=(), article_top: float = 120.0):
    return lane.DecorativeGeometryGuard(
        page_box=(0.0, 0.0, 160.0, 120.0),
        article_boxes=((0.0, 0.0, 160.0, article_top),),
        obstacles=tuple(obstacles),
    )


def set_fixture(value, *, frozen=None, geometry_guard=None):
    config = lane.load_render_config()
    regime = config.regime_for("en")
    assert regime is not None
    return lane.set_one(
        value,
        regime,
        config,
        lane._blank("p1#0", 1, "keep", "en", regime.name),
        intent=frozen or intent(),
        glyph_metric_resolver=metric_for,
        geometry_guard=geometry_guard or guard(),
    )


def snapshot(value) -> tuple:
    return (
        value.unicode,
        tuple(
            (
                item.char_unicode,
                item.pdf_style.font_size,
                tuple(getattr(item.box, name) for name in ("x", "y", "x2", "y2")),
            )
            for item in paragraph_characters(value)
        ),
    )


def check_legacy_sink_and_metric_alignment() -> None:
    value = paragraph()
    config = lane.load_render_config()
    old_initial_size = 2.0 * 15.0
    old_initial_bottom = 80.0 + 10.0 - old_initial_size
    assert abs(old_initial_bottom - 80.0) > config.ink_bottom_tolerance_pt

    outcome = set_fixture(value)
    assert outcome["set"], outcome
    assert outcome["initial_char_count"] == 1
    assert outcome["reserve_lines"] == 1
    assert abs(outcome["ink_bottom_delta"]) <= config.ink_bottom_tolerance_pt
    assert outcome["initial_ink_box"][3] > outcome["body_box"][3]
    assert abs(outcome["second_line_start_x"] - outcome["body_box"][0]) <= 0.001
    assert not outcome["detector_contract"]["missing_fields"]


def check_one_letter_and_opening_punctuation() -> None:
    value = paragraph('"[Again and again across the measured second line')
    before = [item.pdf_style.font_size for item in paragraph_characters(value)]
    outcome = set_fixture(value)
    after = [item.pdf_style.font_size for item in paragraph_characters(value)]
    assert outcome["initial"] == "A"
    assert sum(right > left for left, right in zip(before, after, strict=True)) == 1
    assert after[:2] == before[:2]
    characters = paragraph_characters(value)
    assert characters[0].box.x < outcome["initial_ink_box"][0] < characters[3].box.x
    assert "".join(item.char_unicode for item in paragraph_characters(value)) == value.unicode
    assert outcome["target_policy"] == "english_raised_initial"


def check_font_cap_height_and_descent_variants() -> None:
    config = lane.load_render_config()
    for font_id in ("font-short", "font-tall"):
        outcome = set_fixture(paragraph(font_id=font_id))
        assert outcome["set"], (font_id, outcome)
        assert abs(outcome["ink_bottom_delta"]) <= config.ink_bottom_tolerance_pt
        assert outcome["initial_ink_box"][3] > outcome["body_box"][3]
        assert (
            config.raised_initial_min_font_scale * outcome["body_size"]
            <= outcome["initial_size"]
            <= config.raised_initial_max_font_scale * outcome["body_size"]
        )


def check_source_color_and_style_evidence() -> None:
    fill = drop_cap_intent.NormalizedColor(
        rgb=(0.2, 0.4, 0.6),
        source_space="DeviceRGB",
        source_components=(0.2, 0.4, 0.6),
        operator="rg",
    )
    color = drop_cap_intent.FrozenColorState(
        fill=fill,
        stroke=None,
        alpha=1.0,
        ext_gstate=None,
        evidence=("fixture-rgb",),
    )
    value = paragraph()
    outcome = set_fixture(value, frozen=intent(color=color))
    target = paragraph_characters(value)[0]
    instruction = target.pdf_style.graphic_state.passthrough_per_char_instruction
    assert "0.2 0.4 0.6 rg" in instruction
    assert outcome["detector_contract"]["color"]["fill"] == "#336699"
    assert outcome["color_evidence"]["evidence"] == ["fixture-rgb"]
    assert outcome["style_evidence"]["metric_source"] == "fixture-font"


def check_bounds_and_collision_restore_plain_text() -> None:
    for geometry_guard, reason in (
        (guard(article_top=95.0), lane.REVERT_ARTICLE_BOUNDS),
        (
            guard(obstacles=(("p1#1", (8.0, 96.0, 80.0, 116.0)),)),
            lane.REVERT_COLLISION,
        ),
    ):
        value = paragraph()
        before = snapshot(value)
        outcome = set_fixture(value, geometry_guard=geometry_guard)
        assert not outcome["set"] and outcome["revert_reason"] == reason
        assert snapshot(value) == before


class FakeFont:
    def has_glyph(self, codepoint: int) -> int:
        return codepoint

    def glyph_bbox(self, codepoint: int):
        return (0.02, -0.1, 0.66, 0.75)

    def glyph_advance(self, codepoint: int) -> float:
        return 0.68


def check_typesetter_metric_interface() -> None:
    typesetter = object.__new__(Typesetting)
    typesetter.font_mapper = SimpleNamespace(fontid2font={"fixture-font": FakeFont()})
    measured = typesetter.glyph_ink_metrics(character("A", 0.0, 0.0))
    assert measured is not None
    assert measured.ink_box_em == (0.02, -0.1, 0.66, 0.75)
    assert measured.advance_em == 0.68
    assert measured.glyph_id == ord("A")

    real_metrics = []
    for font_id, font_name in (("helvetica", "helv"), ("times", "tiro")):
        typesetter.font_mapper = SimpleNamespace(
            fontid2font={font_id: pymupdf.Font(font_name)}
        )
        measured = typesetter.glyph_ink_metrics(
            character("A", 0.0, 0.0, font_id=font_id)
        )
        assert measured is not None
        assert measured.source == "pymupdf.Font.glyph_bbox"
        real_metrics.append(measured.ink_box_em)
    assert real_metrics[0] != real_metrics[1]


def check_slotless_article_envelope_fallback() -> None:
    article = SimpleNamespace(
        slots=(),
        elements=(
            SimpleNamespace(page=4, source_box=(20.0, 40.0, 80.0, 90.0)),
            SimpleNamespace(page=4, source_box=(10.0, 60.0, 120.0, 110.0)),
            SimpleNamespace(page=6, source_box=(0.0, 0.0, 10.0, 10.0)),
        ),
    )
    assert lane._article_envelopes(article, 4) == ((10.0, 40.0, 120.0, 110.0),)


def slotless_article_state() -> ArticleDocumentIR:
    article_id = "article-slotless"
    article = ArticleIR(
        article_id=article_id,
        pages=(1,),
        elements=(
            SourceElementRef(
                "p1#0", 1, 0, 0, "body", (10.0, 50.0, 150.0, 90.0), "a", "a"
            ),
            SourceElementRef(
                "p1#1", 1, 0, 1, "title", (0.0, 0.0, 160.0, 120.0), "b", "b"
            ),
        ),
        slots=(),
        chain_ids=(),
        policy_evidence=(ArticlePolicyEvidence(1, "body", None, None, False),),
    )
    return ArticleDocumentIR(
        articles=(article,),
        by_page={1: article_id},
        by_element={"p1#0": article_id, "p1#1": article_id},
        by_chain={},
        unsupported_pages=(UnsupportedArticlePage(1, "fixture", ("p1#0",)),),
    )


def check_slotless_unsupported_page_commit() -> None:
    body = paragraph()
    docs = il.Document(
        page=[
            il.Page(
                page_number=0,
                unit="pt",
                mediabox=il.Mediabox(box=il.Box(0.0, 0.0, 160.0, 120.0)),
                cropbox=il.Cropbox(box=il.Box(0.0, 0.0, 160.0, 120.0)),
                pdf_paragraph=[body],
            )
        ],
        total_pages=1,
    )
    with tempfile.TemporaryDirectory(prefix="babeldoc-c12-slotless-") as directory:
        config = Config(Path(directory))
        frozen = drop_cap_intent.build_intent(
            source_ref="p1#0",
            article_id="article-slotless",
            paragraph=body,
            source_character=paragraph_characters(body)[0],
            target_policy=drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL,
            config_version=1,
            decision_version=1,
        )
        frozen.decision = "keep"
        frozen.flatten_status = drop_cap_intent.FLATTEN_APPLIED
        drop_cap_intent.replace_intents(config, [frozen])
        report = lane.apply(
            config,
            docs,
            run_trace=RunTrace.from_document(docs),
            article_document_ir=slotless_article_state(),
            typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
        )
    row = report["paragraphs"][0]
    assert row["set"] and row["transaction"]["status"] == "committed"
    assert row["article_boxes"] == [[0.0, 0.0, 160.0, 120.0]]


def article_state() -> ArticleDocumentIR:
    article_id = "article-fixture"
    article = ArticleIR(
        article_id=article_id,
        pages=(1,),
        elements=(
            SourceElementRef(
                source_ref="p1#0",
                page=1,
                column=0,
                reading_order=0,
                role="body",
                source_box=(10.0, 50.0, 150.0, 90.0),
                source_text_hash="fixture",
                style_hash="fixture",
            ),
        ),
        slots=(
            ArticleRegionSlot(
                article_id=article_id,
                page=1,
                column=0,
                slot_order=0,
                box=(0.0, 0.0, 160.0, 120.0),
                fixed_obstacle_refs=(),
                capacity_hint=19200.0,
            ),
        ),
        chain_ids=(),
        policy_evidence=(
            ArticlePolicyEvidence(1, "body", None, None, True),
        ),
    )
    return ArticleDocumentIR(
        articles=(article,),
        by_page={1: article_id},
        by_element={"p1#0": article_id},
        by_chain={},
    )


def title_paragraph() -> il.PdfParagraph:
    chars = [
        character(text, 10.0 + index * 6.0, 101.0)
        for index, text in enumerate("TITLE")
    ]
    return il.PdfParagraph(
        box=il.Box(x=8.0, y=99.0, x2=80.0, y2=116.0),
        pdf_style=chars[0].pdf_style,
        unicode="TITLE",
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=item) for item in chars
        ],
        layout_label="title",
    )


class Config:
    def __init__(self, working_dir: Path):
        self.lang_out = "en"
        self.magazine_drop_cap_render = True
        self.working_dir = working_dir

    def get_working_file_path(self, name: str) -> str:
        return str(self.working_dir / name)


def check_transaction_trace_and_fixed_title_rollback() -> None:
    body = paragraph()
    docs = il.Document(
        page=[
            il.Page(
                page_number=0,
                unit="pt",
                mediabox=il.Mediabox(box=il.Box(0.0, 0.0, 160.0, 120.0)),
                cropbox=il.Cropbox(box=il.Box(0.0, 0.0, 160.0, 120.0)),
                pdf_paragraph=[body, title_paragraph()],
            )
        ],
        total_pages=1,
    )
    article_ir = article_state()
    trace = RunTrace.from_document(docs)
    before = snapshot(body)
    with tempfile.TemporaryDirectory(prefix="babeldoc-c12-") as directory:
        config = Config(Path(directory))
        frozen = drop_cap_intent.build_intent(
            source_ref="p1#0",
            article_id="article-fixture",
            paragraph=body,
            source_character=paragraph_characters(body)[0],
            target_policy=drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL,
            config_version=1,
            decision_version=1,
        )
        frozen.decision = "keep"
        frozen.flatten_status = drop_cap_intent.FLATTEN_APPLIED
        drop_cap_intent.replace_intents(config, [frozen])
        report = lane.apply(
            config,
            docs,
            run_trace=trace,
            article_document_ir=article_ir,
            typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
        )
    assert report is not None
    row = report["paragraphs"][0]
    assert row["revert_reason"] == lane.REVERT_COLLISION
    assert row["transaction"]["status"] == "rolled_back"
    assert row["transaction"]["rollback_verification"]["verified"]
    assert snapshot(docs.page[0].pdf_paragraph[0]) == before
    assert frozen.issues[-1].kind == drop_cap_intent.ISSUE_RENDER_FAILED
    event = trace.drop_cap_events[-1]
    assert event["event"] == "english_raised_initial_geometry"
    assert event["reserve_lines"] == 1
    assert event["revert_reason"] == lane.REVERT_COLLISION


def check_no_document_specific_branch() -> None:
    source = Path(lane.__file__).read_text(encoding="utf-8")
    assert "HuaweiTech" not in source
    assert "debug_id" not in source


def main() -> None:
    checks = (
        check_legacy_sink_and_metric_alignment,
        check_one_letter_and_opening_punctuation,
        check_font_cap_height_and_descent_variants,
        check_source_color_and_style_evidence,
        check_bounds_and_collision_restore_plain_text,
        check_typesetter_metric_interface,
        check_slotless_article_envelope_fallback,
        check_slotless_unsupported_page_commit,
        check_transaction_trace_and_fixed_title_rollback,
        check_no_document_specific_branch,
    )
    for check in checks:
        check()
    print(f"PASS: {len(checks)} English raised-initial checks")


if __name__ == "__main__":
    main()
