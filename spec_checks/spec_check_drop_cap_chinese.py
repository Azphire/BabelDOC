from __future__ import annotations

import math
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import drop_cap_intent  # noqa: E402
from babeldoc.magazine import drop_cap_render as lane  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticlePolicyEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ArticleRegionSlot  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.line_split import paragraph_characters  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402


@dataclass(frozen=True, slots=True)
class Metric:
    ink_box_em: tuple[float, float, float, float]
    advance_em: float
    font_id: str
    source: str = "fixture-cjk-font"
    glyph_id: int = 1


class FakeCJKFont:
    def has_glyph(self, codepoint: int) -> int:
        return codepoint

    def glyph_bbox(self, _codepoint: int):
        return (0.06, -0.12, 0.94, 0.86)

    def glyph_advance(self, _codepoint: int) -> float:
        return 1.0


def metric_for(character) -> Metric | None:
    style = getattr(character, "pdf_style", None)
    font_id = "" if style is None else str(style.font_id or "")
    if font_id == "font-missing-metrics":
        return None
    boxes = {
        "font-cjk-short": (0.04, -0.08, 0.92, 0.78),
        "font-cjk-tall": (-0.02, -0.18, 0.98, 0.92),
        "font-cjk-fallback": (0.06, -0.12, 0.94, 0.86),
    }
    box = boxes.get(font_id, (0.05, -0.10, 0.95, 0.90))
    return Metric(box, 1.0, font_id, glyph_id=ord(character.char_unicode or " "))


def character(
    text: str,
    x: float,
    baseline: float,
    *,
    font_id: str = "font-cjk-default",
    color_instruction: str | None = None,
) -> il.PdfCharacter:
    return il.PdfCharacter(
        char_unicode=text,
        box=il.Box(x=x, y=baseline, x2=x + 10.0, y2=baseline + 10.0),
        pdf_style=il.PdfStyle(
            font_id=font_id,
            font_size=10.0,
            graphic_state=il.GraphicState(
                passthrough_per_char_instruction=color_instruction
            ),
        ),
        advance=10.0,
    )


def paragraph(
    text: str = "“（中文排版需要依据真实字形度量完成两行嵌入并在第三行恢复栏宽",
    *,
    line_count: int = 3,
    width: float = 130.0,
    font_id: str = "font-cjk-default",
) -> il.PdfParagraph:
    per_line = math.ceil(len(text) / line_count)
    characters = []
    for index, text_char in enumerate(text):
        line = min(index // per_line, line_count - 1)
        position = index - line * per_line
        characters.append(
            character(
                text_char,
                10.0 + position * 10.0,
                80.0 - line * 15.0,
                font_id=font_id,
            )
        )
    return il.PdfParagraph(
        box=il.Box(x=10.0, y=20.0, x2=10.0 + width, y2=92.0),
        pdf_style=characters[0].pdf_style,
        unicode=text,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=item) for item in characters
        ],
        drop_cap_candidate=True,
        drop_cap_decision="keep",
        layout_label="plain text",
    )


def frozen_intent(*, color=None, article_id: str = "article-fixture"):
    return SimpleNamespace(
        target_policy=drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL,
        source_color=color or drop_cap_intent.freeze_color(None),
        source_style_hash="source-style-fixture",
        source_char="A",
        article_id=article_id,
    )


def guard(*, obstacles=()) -> lane.DecorativeGeometryGuard:
    return lane.DecorativeGeometryGuard(
        page_box=(0.0, 0.0, 180.0, 120.0),
        article_boxes=((0.0, 0.0, 180.0, 120.0),),
        obstacles=tuple(obstacles),
    )


def set_fixture(value, *, intent=None, geometry_guard=None):
    config = lane.load_render_config()
    regime = config.regime_for("zh-CN")
    assert regime is not None
    return lane.set_one(
        value,
        regime,
        config,
        lane._blank("p1#0", 1, "keep", "zh-CN", regime.name),
        intent=intent or frozen_intent(),
        glyph_metric_resolver=metric_for,
        geometry_guard=geometry_guard or guard(),
    )


def snapshot(value) -> tuple:
    return (
        value.unicode,
        tuple(
            (
                item.char_unicode,
                item.pdf_style.font_id,
                item.pdf_style.font_size,
                getattr(
                    item.pdf_style.graphic_state,
                    "passthrough_per_char_instruction",
                    None,
                ),
                tuple(getattr(item.box, name) for name in ("x", "y", "x2", "y2")),
                item.advance,
            )
            for item in paragraph_characters(value)
        ),
    )


def check_two_line_ink_anchors_and_reserve() -> None:
    value = paragraph()
    before_sizes = [item.pdf_style.font_size for item in paragraph_characters(value)]
    outcome = set_fixture(value)
    assert outcome["set"], outcome
    assert outcome["target_policy"] == "chinese_two_line_initial"
    assert outcome["initial"] == "中"
    assert outcome["initial_char_count"] == 1
    assert outcome["reserve_lines"] == 2
    tolerance = lane.load_render_config().ink_anchor_tolerance_pt
    assert abs(outcome["ink_top_delta"]) <= tolerance
    assert abs(outcome["ink_bottom_delta"]) <= tolerance
    reserve_edge = outcome["initial_ink_box"][2] + outcome["gutter"]
    assert all(value >= reserve_edge - tolerance for value in outcome["body_start_x"])
    assert abs(outcome["third_line_start_x"] - outcome["body_box"][0]) <= tolerance
    after_sizes = [item.pdf_style.font_size for item in paragraph_characters(value)]
    assert sum(after > before for before, after in zip(before_sizes, after_sizes, strict=True)) == 1
    assert after_sizes[:2] == before_sizes[:2]
    assert not outcome["detector_contract"]["missing_fields"]
    assert outcome["detector_contract"]["reserve"]["source"] == "first_two_body_ink_lines"


def check_two_line_body_and_font_variants() -> None:
    two_lines = set_fixture(
        paragraph("中文排版需要真实度量并保持正文完整", line_count=2)
    )
    assert two_lines["set"], two_lines
    assert two_lines["lines_before"] == 2
    assert two_lines["third_line_start_x"] is None
    for font_id in ("font-cjk-short", "font-cjk-tall", "font-cjk-fallback"):
        outcome = set_fixture(paragraph(font_id=font_id))
        assert outcome["set"], (font_id, outcome)
        assert outcome["style_evidence"]["font_id"] == font_id
        assert outcome["style_evidence"]["metric_font_id"] == font_id
    typesetter = object.__new__(Typesetting)
    typesetter.font_mapper = SimpleNamespace(
        fontid2font={"font-cjk-fallback": FakeCJKFont()}
    )
    measured = typesetter.glyph_ink_metrics(
        character("中", 0.0, 0.0, font_id="font-cjk-fallback")
    )
    assert measured is not None
    assert measured.font_id == "font-cjk-fallback"
    assert measured.glyph_id == ord("中")


def check_source_color_and_searchable_order() -> None:
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
    source_text = value.unicode
    outcome = set_fixture(value, intent=frozen_intent(color=color))
    assert outcome["set"], outcome
    characters = paragraph_characters(value)
    target = characters[outcome["_target_index"]]
    instruction = target.pdf_style.graphic_state.passthrough_per_char_instruction
    assert "0.2 0.4 0.6 rg" in instruction
    assert outcome["detector_contract"]["color"]["fill"] == "#336699"
    assert "".join(item.char_unicode for item in characters) == source_text
    assert value.unicode == source_text


def check_zero_body_ink_overlap() -> None:
    value = paragraph()
    outcome = set_fixture(value)
    assert outcome["set"], outcome
    characters = paragraph_characters(value)
    target_index = outcome["_target_index"]
    initial = tuple(outcome["initial_ink_box"])
    body_boxes = lane._character_ink_boxes(
        [item for index, item in enumerate(characters) if index != target_index],
        metric_for,
    )
    assert body_boxes is not None
    assert not any(lane._overlaps(initial, box, 0.0) for box in body_boxes)
    assert outcome["collision_evidence"] == []


def check_failure_paths_restore_plain_text() -> None:
    fixtures = (
        (paragraph("中文正文不足一行", line_count=1), guard(), lane.REVERT_TOO_FEW_LINES),
        (paragraph(width=80.0), guard(), lane.REVERT_TOO_NARROW),
        (
            paragraph(font_id="font-missing-metrics"),
            guard(),
            lane.REVERT_NO_METRICS,
        ),
        (
            paragraph(),
            guard(obstacles=(("fixed:title", (20.0, 55.0, 55.0, 90.0)),)),
            lane.REVERT_COLLISION,
        ),
    )
    for value, geometry_guard, reason in fixtures:
        before = snapshot(value)
        outcome = set_fixture(value, geometry_guard=geometry_guard)
        assert not outcome["set"] and outcome["revert_reason"] == reason, outcome
        assert snapshot(value) == before


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
                source_box=(10.0, 20.0, 140.0, 92.0),
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
        by_element={"p1#0": article_id},
        by_chain={},
    )


class Config:
    def __init__(self, working_dir: Path):
        self.lang_out = "zh-CN"
        self.magazine_drop_cap_render = True
        self.working_dir = working_dir

    def get_working_file_path(self, name: str) -> str:
        return str(self.working_dir / name)


def check_apply_transaction_trace_and_typed_issue() -> None:
    success_body = paragraph()
    success_docs = il.Document(
        page=[
            il.Page(
                page_number=0,
                unit="pt",
                mediabox=il.Mediabox(box=il.Box(0.0, 0.0, 180.0, 120.0)),
                cropbox=il.Cropbox(box=il.Box(0.0, 0.0, 180.0, 120.0)),
                pdf_paragraph=[success_body],
            )
        ],
        total_pages=1,
    )
    article_ir = article_state()
    success_trace = RunTrace.from_document(success_docs)
    with tempfile.TemporaryDirectory(prefix="babeldoc-c13-success-") as directory:
        success_config = Config(Path(directory))
        success_intent = drop_cap_intent.build_intent(
            source_ref="p1#0",
            article_id="article-fixture",
            paragraph=success_body,
            source_character=paragraph_characters(success_body)[2],
            target_policy=drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL,
            config_version=1,
            decision_version=1,
        )
        success_intent.decision = "keep"
        success_intent.flatten_status = drop_cap_intent.FLATTEN_APPLIED
        drop_cap_intent.replace_intents(success_config, [success_intent])
        success_report = lane.apply(
            success_config,
            success_docs,
            run_trace=success_trace,
            article_document_ir=article_ir,
            typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
        )
    assert success_report is not None
    success_row = success_report["paragraphs"][0]
    assert success_row["set"]
    assert success_row["transaction"]["status"] == "committed"
    success_event = success_trace.drop_cap_events[-1]
    assert success_event["event"] == "chinese_two_line_initial_geometry"
    assert success_event["reserve_lines"] == 2
    assert success_event["first_line_metrics"]["ink_top"] is not None
    assert success_event["second_line_metrics"]["ink_bottom"] is not None
    assert success_event["gutter"] == success_row["gutter"]
    assert success_event["style_evidence"] == success_row["style_evidence"]

    body = paragraph()
    obstacle = paragraph("固定标题", line_count=1, width=40.0)
    obstacle.drop_cap_candidate = None
    obstacle.drop_cap_decision = None
    for item in paragraph_characters(obstacle):
        item.box.x += 10.0
        item.box.x2 += 10.0
    obstacle.box = il.Box(x=20.0, y=55.0, x2=60.0, y2=92.0)
    docs = il.Document(
        page=[
            il.Page(
                page_number=0,
                unit="pt",
                mediabox=il.Mediabox(box=il.Box(0.0, 0.0, 180.0, 120.0)),
                cropbox=il.Cropbox(box=il.Box(0.0, 0.0, 180.0, 120.0)),
                pdf_paragraph=[body, obstacle],
            )
        ],
        total_pages=1,
    )
    trace = RunTrace.from_document(docs)
    before = snapshot(body)
    obstacle_before = snapshot(obstacle)
    with tempfile.TemporaryDirectory(prefix="babeldoc-c13-") as directory:
        config = Config(Path(directory))
        frozen = drop_cap_intent.build_intent(
            source_ref="p1#0",
            article_id="article-fixture",
            paragraph=body,
            source_character=paragraph_characters(body)[2],
            target_policy=drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL,
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
    assert snapshot(body) == before
    assert snapshot(obstacle) == obstacle_before
    assert docs.total_pages == 1 and len(docs.page) == 1
    assert len(docs.page[0].pdf_paragraph) == 2
    assert frozen.issues[-1].kind == drop_cap_intent.ISSUE_RENDER_FAILED
    event = trace.drop_cap_events[-1]
    assert event["event"] == "chinese_two_line_initial_geometry"
    assert event["reserve_lines"] == 2
    assert event["revert_reason"] == lane.REVERT_COLLISION


def check_declared_policy_and_negative_scope() -> None:
    config = drop_cap.load_drop_cap_config()
    assert (
        config.target_policy_for("zh-CN")
        == drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL
    )
    source = Path(lane.__file__).read_text(encoding="utf-8")
    assert "debug_id" not in source
    for publication in ("HuaweiTech", "UNESCO", "WIPO"):
        assert publication not in source


def main() -> None:
    checks = (
        check_two_line_ink_anchors_and_reserve,
        check_two_line_body_and_font_variants,
        check_source_color_and_searchable_order,
        check_zero_body_ink_overlap,
        check_failure_paths_restore_plain_text,
        check_apply_transaction_trace_and_typed_issue,
        check_declared_policy_and_negative_scope,
    )
    for check in checks:
        check()
    print(f"PASS: {len(checks)} Chinese two-line initial checks")


if __name__ == "__main__":
    main()
