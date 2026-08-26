"""Offline C11 gate for frozen drop-cap intent and source color transfer."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import pymupdf  # noqa: F401
except ModuleNotFoundError:
    pymupdf_stub = types.ModuleType("pymupdf")
    pymupdf_stub.Font = type("Font", (), {})
    sys.modules["pymupdf"] = pymupdf_stub

try:
    import hyperscan  # noqa: F401
except ModuleNotFoundError:
    sys.modules["hyperscan"] = types.ModuleType("hyperscan")

hitl_stub = types.ModuleType("babeldoc.magazine.hitl")
hitl_stub.load_hitl_config = lambda: {"drop_cap_decisions": ["keep", "flatten"]}
hitl_stub.labeled_pages = lambda docs: [
    (
        int(page.page_number) + 1 if page.page_number is not None else position + 1,
        page,
    )
    for position, page in enumerate(docs.page)
]
sys.modules["babeldoc.magazine.hitl"] = hitl_stub

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import drop_cap_intent as intent_lane  # noqa: E402
from babeldoc.magazine import drop_cap_render as render_lane  # noqa: E402
from babeldoc.magazine.line_split import paragraph_characters  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402


class Config:
    def __init__(self, directory: Path, target: str) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lang_out = target
        self.magazine_article_group = True
        self.magazine_drop_cap_mark = True
        self.magazine_drop_cap_apply = True
        self.magazine_drop_cap_render = True

    def get_working_file_path(self, name: str) -> str:
        return str(self.directory / name)


class Trace:
    def __init__(self) -> None:
        self.events = []
        self.blocked = []

    def record_drop_cap_event(self, event) -> None:
        self.events.append(dict(event))

    def record_blocked_reason(self, issue) -> None:
        self.blocked.append(dict(issue))


def style(font: str, size: float, instruction: str) -> il.PdfStyle:
    return il.PdfStyle(
        font_id=font,
        font_size=size,
        graphic_state=il.GraphicState(
            passthrough_per_char_instruction=instruction
        ),
    )


def paragraph(
    prefix: str,
    *,
    font: str,
    instruction: str = "0 g",
    lines: int = 7,
    width: float = 260.0,
) -> il.PdfParagraph:
    body = prefix + (" body text continues across the column. " * 20)
    size = 10.0
    advance = 15.0
    per_line = int(width // size)
    count = per_line * lines
    text = (body * ((count // len(body)) + 1))[:count]
    shared_style = style(font, size, instruction)
    characters = []
    baseline = 700.0
    for index, glyph in enumerate(text):
        line, column = divmod(index, per_line)
        x = 100.0 + column * size
        y = baseline - line * advance
        characters.append(
            il.PdfCharacter(
                char_unicode=glyph,
                advance=size,
                box=il.Box(x=x, y=y, x2=x + size, y2=y + size),
                pdf_style=shared_style,
            )
        )
    return il.PdfParagraph(
        box=il.Box(
            x=100.0,
            y=baseline - (lines + 2) * advance,
            x2=100.0 + width,
            y2=baseline + size,
        ),
        pdf_style=shared_style,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_characters=il.PdfSameStyleCharacters(
                    pdf_style=shared_style,
                    pdf_character=characters,
                )
            )
        ],
        unicode=text,
        layout_label="text",
        drop_cap_candidate=True,
    )


def source_intent(
    reference: str,
    source_char: str,
    source_font: str,
    color_instruction: str,
    policy: str,
) -> intent_lane.DropCapIntent:
    source = paragraph(source_char, font=source_font, instruction="0 g", lines=3)
    first = paragraph_characters(source)[0]
    first.pdf_style = style(source_font, 30.0, color_instruction)
    config = drop_cap.load_drop_cap_config()
    return intent_lane.build_intent(
        source_ref=reference,
        article_id="article-1",
        paragraph=source,
        source_character=first,
        target_policy=policy,
        config_version=config.intent_config_version,
        decision_version=config.decision_version,
    )


def rendered_color(character) -> tuple[float, float, float]:
    return intent_lane.freeze_color(character.pdf_style).fill.rgb


def render_case(
    directory: Path,
    *,
    target: str,
    prefix: str,
    source_char: str,
    source_font: str,
    source_color: str,
    target_font: str,
    policy: str,
    expected: tuple[float, float, float],
) -> tuple[il.PdfParagraph, intent_lane.DropCapIntent, Trace]:
    config = Config(directory, target)
    target_paragraph = paragraph(prefix, font=target_font)
    frozen = source_intent(
        "p1#0", source_char, source_font, source_color, policy
    )
    frozen.flatten_status = intent_lane.FLATTEN_APPLIED
    intent_lane.replace_intents(config, [frozen])
    page = SimpleNamespace(page_number=0, pdf_paragraph=[target_paragraph])
    trace = Trace()
    report = render_lane.apply(config, SimpleNamespace(page=[page]), run_trace=trace)
    assert report is not None and report["totals"]["set"] == 1
    characters = paragraph_characters(target_paragraph)
    assert frozen.target_index is not None
    selected = characters[frozen.target_index]
    tolerance = drop_cap.load_drop_cap_config().color_tolerance
    assert intent_lane.colors_close(rendered_color(selected), expected, tolerance)
    assert selected.pdf_style.font_id == target_font
    assert selected.pdf_style.font_id != source_font
    assert sum(
        intent_lane.colors_close(rendered_color(character), expected, tolerance)
        for character in characters
    ) == 1
    assert trace.events[-1]["event"] == "target_initial_style"
    assert trace.events[-1]["target_style_hash"] == frozen.target_style_hash
    return target_paragraph, frozen, trace


def il_digest(paragraphs) -> str:
    record = [
        {
            "unicode": paragraph.unicode,
            "candidate": paragraph.drop_cap_candidate,
            "decision": paragraph.drop_cap_decision,
            "styles": [
                intent_lane.style_record(character.pdf_style)
                for character in paragraph_characters(paragraph)
            ],
        }
        for paragraph in paragraphs
    ]
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def check_bidirectional_color_and_eligible_initial(directory: Path) -> None:
    chinese, zh_intent, _trace = render_case(
        directory / "en_to_zh",
        target="zh-CN",
        prefix="“（中文段落",
        source_char="R",
        source_font="SourceLatin",
        source_color="1 0 0 rg",
        target_font="TargetCJK",
        policy=intent_lane.POLICY_CJK_IDEOGRAPH,
        expected=(1.0, 0.0, 0.0),
    )
    zh_characters = paragraph_characters(chinese)
    assert zh_intent.target_char == "中"
    assert [character.char_unicode for character in zh_characters[:3]] == ["“", "（", "中"]
    assert zh_characters[0].pdf_style.font_size == 10.0
    assert zh_characters[1].pdf_style.font_size == 10.0
    assert rendered_color(zh_characters[0]) == (0.0, 0.0, 0.0)
    assert rendered_color(zh_characters[1]) == (0.0, 0.0, 0.0)

    english, en_intent, _trace = render_case(
        directory / "zh_to_en",
        target="en-GB",
        prefix="(“Alpha opening",
        source_char="蓝",
        source_font="SourceCJK",
        source_color="0 0 1 rg",
        target_font="TargetLatin",
        policy=intent_lane.POLICY_ALPHABETIC,
        expected=(0.0, 0.0, 1.0),
    )
    en_characters = paragraph_characters(english)
    assert en_intent.target_char == "A"
    assert rendered_color(en_characters[2]) == (0.0, 0.0, 1.0)
    assert rendered_color(en_characters[3]) == (0.0, 0.0, 0.0)
    assert en_characters[3].char_unicode == "l"


def check_flatten_failure_blocks_render(directory: Path) -> None:
    config = Config(directory / "flatten_failure", "zh")
    candidate = paragraph("中文", font="TargetCJK")
    frozen = source_intent(
        "p1#0",
        "R",
        "SourceLatin",
        "1 0 0 rg",
        intent_lane.POLICY_CJK_IDEOGRAPH,
    )
    intent_lane.replace_intents(config, [frozen])
    page = SimpleNamespace(page_number=0, pdf_paragraph=[candidate])
    docs = SimpleNamespace(page=[page])
    trace = Trace()
    before = il_digest([candidate])
    original = drop_cap.flatten

    def fail(_paragraph, _config):
        raise RuntimeError("synthetic flatten failure")

    drop_cap.flatten = fail
    try:
        report = drop_cap.apply(config, [(1, page)], run_trace=trace)
    finally:
        drop_cap.flatten = original
    assert report is not None
    assert frozen.flatten_status == intent_lane.FLATTEN_FAILED
    assert frozen.render_status == intent_lane.RENDER_SKIPPED
    assert frozen.issues[0].kind == intent_lane.ISSUE_FLATTEN_FAILED
    assert trace.blocked[0]["kind"] == intent_lane.ISSUE_FLATTEN_FAILED
    assert il_digest([candidate]) == before
    render_report = render_lane.apply(config, docs, run_trace=trace)
    assert render_report is not None and render_report["totals"]["decided"] == 0
    assert not any(event["event"] == "target_initial_style" for event in trace.events)


def check_stale_and_noncandidate_decisions_are_atomic(directory: Path) -> None:
    config = Config(directory / "decisions", "en")
    candidate = paragraph("Alpha", font="TargetLatin")
    other = paragraph("Body", font="TargetLatin")
    other.drop_cap_candidate = None
    frozen = source_intent(
        "p1#0",
        "蓝",
        "SourceCJK",
        "0 0 1 rg",
        intent_lane.POLICY_ALPHABETIC,
    )
    intent_lane.replace_intents(config, [frozen])
    before = il_digest([candidate, other])
    stale = frozen.manual_template("keep")
    stale["source_style_hash"] = "0" * 64
    try:
        drop_cap.validate_manual_decisions(config, {"p1#0": stale})
    except drop_cap.DropCapError:
        pass
    else:
        raise AssertionError("stale drop-cap decision was accepted")
    assert il_digest([candidate, other]) == before

    noncandidate = frozen.manual_template("keep")
    noncandidate["source_ref"] = "p1#1"
    try:
        drop_cap.validate_manual_decisions(config, {"p1#1": noncandidate})
    except drop_cap.DropCapError:
        pass
    else:
        raise AssertionError("noncandidate drop-cap decision was accepted")
    assert il_digest([candidate, other]) == before

    valid_manual = drop_cap.parse_manual_decision(
        "p1#0", frozen.manual_template("keep"), ("keep", "flatten")
    )
    invalid_manual = intent_lane.ManualDecision(
        **{**valid_manual.as_record(), "source_ref": "p1#1"}
    )
    page = SimpleNamespace(pdf_paragraph=[candidate, other])
    try:
        drop_cap.apply_decisions(
            config,
            [(1, page)],
            {"p1#0": valid_manual, "p1#1": invalid_manual},
        )
    except drop_cap.DropCapError:
        pass
    else:
        raise AssertionError("mixed valid/noncandidate decisions were partly applied")
    assert il_digest([candidate, other]) == before


def check_color_normalization() -> None:
    cmyk = style("Source", 30.0, "/GS1 gs 0 1 1 0 k")
    frozen = intent_lane.freeze_color(cmyk)
    assert frozen.fill.source_space == "DeviceCMYK"
    assert frozen.fill.rgb == (1.0, 0.0, 0.0)
    assert frozen.ext_gstate == "/GS1 gs"
    assert "DeviceCMYK" in " ".join(frozen.evidence)


def check_run_trace_contract() -> None:
    trace = RunTrace()
    trace.register_source(
        "p1#0",
        page=1,
        index=0,
        source_box=(0.0, 0.0, 10.0, 10.0),
        text_hash="text",
        style_hash="style",
    )
    trace.record_drop_cap_event(
        {
            "event": "target_initial_style",
            "source_ref": "p1#0",
            "source_style_hash": "source-style",
            "target_style_hash": "target-style",
        }
    )
    assert trace.to_record()["drop_cap_events"] == [
        {
            "event": "target_initial_style",
            "source_ref": "p1#0",
            "source_style_hash": "source-style",
            "target_style_hash": "target-style",
        }
    ]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="babeldoc-c11-") as raw:
        directory = Path(raw)
        check_bidirectional_color_and_eligible_initial(directory)
        check_flatten_failure_blocks_render(directory)
        check_stale_and_noncandidate_decisions_are_atomic(directory)
        check_color_normalization()
        check_run_trace_contract()
    print("PASS: drop-cap intent, color transfer, decision validation, and failure gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
