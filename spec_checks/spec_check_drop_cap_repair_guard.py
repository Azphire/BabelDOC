"""Offline C14 gate for drop-cap render and repair interaction guards."""

from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

cache_stub = types.ModuleType("babeldoc.translator.cache")
cache_stub.TranslationCache = type("TranslationCache", (), {})
sys.modules.setdefault("babeldoc.translator.cache", cache_stub)

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

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.magazine import article_flow  # noqa: E402
from babeldoc.magazine import column_reflow  # noqa: E402
from babeldoc.magazine import drop_cap_intent  # noqa: E402
from babeldoc.magazine import drop_cap_render  # noqa: E402
from babeldoc.magazine import fixed_assets  # noqa: E402
from babeldoc.magazine.detectors import base  # noqa: E402
from babeldoc.magazine.line_split import paragraph_characters  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import collision  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402


class Config:
    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.lang_out = "en"
        self.magazine_drop_cap_render = True
        self.translator = None
        self.ignore_cache = False

    def get_working_file_path(self, name: str) -> str:
        return str(self.working_dir / name)


def style(size: float = 10.0, instruction: str = "0 g") -> il.PdfStyle:
    return il.PdfStyle(
        font_id="fixture-font",
        font_size=size,
        graphic_state=il.GraphicState(
            passthrough_per_char_instruction=instruction
        ),
    )


def paragraph(
    text: str,
    *,
    left: float = 20.0,
    bottom: float = 40.0,
    label: str = "plain text",
) -> il.PdfParagraph:
    characters = []
    x = left
    for index, glyph in enumerate(text):
        line, column = divmod(index, 18)
        x = left + column * 5.0
        baseline = bottom + 35.0 - line * 12.0
        characters.append(
            il.PdfCharacter(
                char_unicode=glyph,
                box=il.Box(x=x, y=baseline, x2=x + 5.0, y2=baseline + 10.0),
                pdf_style=style(),
                advance=5.0,
            )
        )
    return il.PdfParagraph(
        box=il.Box(x=left, y=bottom, x2=left + 95.0, y2=bottom + 48.0),
        unicode=text,
        layout_label=label,
        drop_cap_candidate=True,
        drop_cap_decision="keep",
        pdf_style=style(),
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(pdf_character=character)
            for character in characters
        ],
    )


def document(*paragraphs: il.PdfParagraph) -> il.Document:
    return il.Document(
        page=[
            il.Page(
                page_number=0,
                unit="pt",
                mediabox=il.Mediabox(box=il.Box(0.0, 0.0, 160.0, 120.0)),
                cropbox=il.Cropbox(box=il.Box(0.0, 0.0, 160.0, 120.0)),
                pdf_paragraph=list(paragraphs),
            )
        ],
        total_pages=1,
    )


def intent_for(reference: str):
    source = paragraph("A source opening")
    source_character = paragraph_characters(source)[0]
    source_character.pdf_style = style(30.0, "1 0 0 rg")
    intent = drop_cap_intent.build_intent(
        source_ref=reference,
        article_id="article-fixture",
        paragraph=source,
        source_character=source_character,
        target_policy=drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL,
        config_version=1,
        decision_version=1,
    )
    intent.decision = "keep"
    intent.flatten_status = drop_cap_intent.FLATTEN_APPLIED
    return intent


def digest(value) -> str:
    return fixed_assets.content_digest(value)


def fake_render(mode: str):
    def render(paragraph_value, _regime, _config, base_record, *, intent, **_kwargs):
        initial = paragraph_characters(paragraph_value)[0]
        initial.pdf_style = il.PdfStyle(
            font_id=initial.pdf_style.font_id,
            font_size=30.0,
            graphic_state=initial.pdf_style.graphic_state,
        )
        if mode != "color":
            initial.pdf_style = drop_cap_intent.apply_color(
                initial.pdf_style, intent.source_color
            )
        if mode == "coverage":
            paragraph_value.unicode = (paragraph_value.unicode or "") + "!"
        return {
            **base_record,
            "initial": initial.char_unicode,
            "initial_char_count": 1,
            "set": True,
            "reverted": False,
            "revert_reason": None,
            "reach": None if mode == "geometry" else [20.0, 40.0, 115.0, 88.0],
            "collision_evidence": (
                [{"reference": "p1#1"}] if mode == "collision" else []
            ),
            "_target_index": 0,
        }

    return render


def check_invalid_intents_do_not_render(directory: Path) -> None:
    values = [
        paragraph("Alpha body text across several measured lines"),
        paragraph("Beta body text across several measured lines"),
        paragraph("Gamma body text across several measured lines"),
    ]
    values[2].drop_cap_candidate = None
    docs = document(*values)
    config = Config(directory / "invalid")
    intents = [intent_for(f"p1#{index}") for index, _value in enumerate(values)]
    intents[0].flatten_status = drop_cap_intent.FLATTEN_FAILED
    intents[1].decision = "flatten"
    drop_cap_intent.replace_intents(config, intents)
    before = digest(docs.page[0])
    original = drop_cap_render.set_one
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("invalid intent reached the render implementation")

    drop_cap_render.set_one = forbidden
    try:
        report = drop_cap_render.apply(
            config,
            docs,
            run_trace=RunTrace.from_document(docs),
        )
    finally:
        drop_cap_render.set_one = original
    assert report is not None
    assert calls == 0
    assert report["totals"]["by_state"]["invalid_intent"] == 3
    assert {
        tuple(row["validation"]["failed"])
        for row in report["paragraphs"]
    } >= {
        ("flatten_success",),
        ("decision_current",),
        ("candidate_valid",),
    }
    assert digest(docs.page[0]) == before
    assert all(
        character.pdf_style.font_size == 10.0
        for value in values
        for character in paragraph_characters(value)
    )


def check_post_render_failures_rollback(directory: Path) -> None:
    original = drop_cap_render.set_one
    try:
        for mode, reason in (
            ("color", drop_cap_render.REVERT_POST_COLOR),
            ("geometry", drop_cap_render.REVERT_POST_GEOMETRY),
            ("coverage", drop_cap_render.REVERT_POST_COVERAGE),
            ("collision", drop_cap_render.REVERT_POST_COLLISION),
        ):
            value = paragraph("Alpha body text across several measured lines")
            docs = document(value)
            config = Config(directory / mode)
            intent = intent_for("p1#0")
            drop_cap_intent.replace_intents(config, [intent])
            trace = RunTrace.from_document(docs)
            before = digest(docs.page[0])
            drop_cap_render.set_one = fake_render(mode)
            report = drop_cap_render.apply(config, docs, run_trace=trace)
            row = report["paragraphs"][0]
            assert row["render_state"] == "render_rollback"
            assert row["revert_reason"] == reason
            assert row["transaction"]["status"] == "rolled_back"
            assert row["transaction"]["rollback_verification"]["verified"]
            assert digest(docs.page[0]) == before
            assert trace.drop_cap_events[-1]["render_state"] == "render_rollback"
    finally:
        drop_cap_render.set_one = original


def check_committed_render_state(directory: Path) -> None:
    value = paragraph("Alpha body text across several measured lines")
    docs = document(value)
    config = Config(directory / "committed")
    intent = intent_for("p1#0")
    drop_cap_intent.replace_intents(config, [intent])
    trace = RunTrace.from_document(docs)
    original = drop_cap_render.set_one
    drop_cap_render.set_one = fake_render("valid")
    try:
        report = drop_cap_render.apply(config, docs, run_trace=trace)
    finally:
        drop_cap_render.set_one = original
    row = report["paragraphs"][0]
    assert row["render_state"] == "committed"
    assert row["validation"]["valid"]
    assert row["validation"]["post_render"]["valid"]
    assert row["transaction"]["status"] == "committed"
    assert (
        row["validation"]["transaction_generation"]
        == row["transaction"]["generation"]
    )
    assert report["totals"]["by_state"]["committed"] == 1
    assert trace.drop_cap_events[-1]["render_state"] == "committed"


def repair_issue(kind: str, refs: tuple[str, ...], **evidence) -> base.Issue:
    return base.Issue(
        kind=kind,
        page=1,
        paragraph_refs=refs,
        geometry=None,
        severity="medium",
        evidence=evidence,
        detector=kind,
    )


def check_repair_preflight_and_unrelated_action(directory: Path) -> None:
    protected = paragraph("Alpha protected decorative paragraph")
    unrelated = paragraph(
        "TITLE",
        left=-12.0,
        bottom=92.0,
        label="title",
    )
    unrelated.box = il.Box(-12.0, 92.0, 35.0, 115.0)
    docs = document(protected, unrelated)
    config = Config(directory / "repair")
    intent = intent_for("p1#0")
    intent.render_status = drop_cap_intent.RENDER_APPLIED
    intent.target_index = 0
    drop_cap_intent.replace_intents(config, [intent])
    trace = RunTrace.from_document(docs)
    loop = controller.RepairLoop(
        config,
        docs,
        run_trace=trace,
        source_geometry=SimpleNamespace(),
    )
    context = SimpleNamespace(
        pages=[base.PageView(1, docs.page[0], None)],
        language="en",
        config=loop.detector_config,
    )

    def decision(issue):
        return SimpleNamespace(
            issue_ids=[issue.id], parameters={"max_paragraphs": 3}
        )
    cases = (
        (
            actions.NAME,
            repair_issue("untranslated_residue", ("p1#0",), residue_ratio=1.0),
            1,
        ),
        (
            contain.NAME,
            repair_issue("out_of_page", ("p1#0",), overflow_ratio=1.0),
            1,
        ),
        (
            collision.NAME,
            repair_issue(
                "text_text_collision", ("p1#1", "p1#0"), coverage=1.0
            ),
            2,
        ),
    )
    before_page = digest(docs.page[0])
    before_trace = trace.transaction_digest()
    for name, issue, count in cases:
        action = loop.repair_config.action(name)
        handler = controller.Handler(count, lambda *_args: actions.ACCEPTED, None)
        accepted, rejected = loop._candidates(
            [issue], decision(issue), action, context, handler
        )
        assert not accepted and len(rejected) == 1
        assert rejected[0].reason == actions.REASON_PROTECTED_DROP_CAP
        assert rejected[0].geometry["issue"] == {
            "kind": drop_cap_intent.ISSUE_PROTECTED_CONFLICT,
            "source_refs": ["p1#0"],
        }
    assert digest(docs.page[0]) == before_page
    assert trace.transaction_digest() == before_trace

    candidate = actions.Candidate(
        issue_id="out_of_page:p1:p1#1",
        reference="p1#1",
        page_index=1,
        paragraph_index=1,
        paragraph=unrelated,
        page=docs.page[0],
        source_text=unrelated.unicode,
    )
    snapshot = controller.Snapshot()
    outcomes = loop._contain(
        [candidate],
        context,
        snapshot,
        loop.repair_config.action(contain.NAME),
    )
    assert outcomes[0].changed
    assert "p1#1" in loop.touched and "p1#0" not in loop.touched


def check_reflow_anchor_and_article_holder_guard(directory: Path) -> None:
    value = paragraph("Alpha protected decorative paragraph")
    docs = document(value)
    config = Config(directory / "reflow")
    intent = intent_for("p1#0")
    intent.render_status = drop_cap_intent.RENDER_APPLIED
    intent.target_index = 0
    drop_cap_intent.replace_intents(config, [intent])
    before_page = digest(docs.page[0])
    before = drop_cap_intent.decorative_anchor_signature(value, intent)
    stored = column_reflow.raise_by(value, 7.0)
    assert drop_cap_intent.decorative_anchor_signature(value, intent) == before
    column_reflow.restore(stored)
    assert drop_cap_intent.decorative_anchor_signature(value, intent) == before

    element = SimpleNamespace(
        source_ref="p1#0",
        page=1,
        column=0,
        reading_order=0,
        role="body",
        source_box=(20.0, 40.0, 115.0, 88.0),
    )
    article = SimpleNamespace(article_id="article-fixture", elements=(element,))
    inventory = fixed_assets.build_inventory(docs)
    segments = article_flow.build_page_segments(
        docs,
        article,
        1,
        SimpleNamespace(),
        inventory,
        article_flow.load_flow_config(),
        SimpleNamespace(),
        drop_cap_intent.active_protected_refs(config),
    )
    assert segments == ()
    assert digest(docs.page[0]) == before_page


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="babeldoc-c14-") as raw:
        directory = Path(raw)
        check_invalid_intents_do_not_render(directory)
        check_post_render_failures_rollback(directory)
        check_committed_render_state(directory)
        check_repair_preflight_and_unrelated_action(directory)
        check_reflow_anchor_and_article_holder_guard(directory)
    print("PASS: C14 drop-cap render, repair, transaction, and reflow guards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
