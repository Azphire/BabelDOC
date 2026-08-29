from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import drop_cap_render
from babeldoc.magazine.line_split import paragraph_characters
from tests.minimal.test_drop_cap_chinese import paragraph_snapshot
from tests.minimal.test_drop_cap_keep_flatten import ControlledMetric
from tests.minimal.test_drop_cap_keep_flatten import RuntimeConfig
from tests.minimal.test_drop_cap_keep_flatten import chinese_render_paragraph
from tests.minimal.test_drop_cap_keep_flatten import direct_intent
from tests.minimal.test_drop_cap_keep_flatten import document_digest
from tests.minimal.test_drop_cap_keep_flatten import english_render_paragraph
from tests.minimal.test_drop_cap_keep_flatten import geometry_guard
from tests.minimal.test_drop_cap_keep_flatten import make_article_ir
from tests.minimal.test_drop_cap_keep_flatten import make_document
from tests.minimal.test_drop_cap_keep_flatten import metric_for
from tests.minimal.test_drop_cap_keep_flatten import pdf_character
from tests.minimal.test_drop_cap_keep_flatten import register_render_intents
from tools.verify_magazine_demo import DROPCAP_FIELDS
from tools.verify_magazine_demo import VerificationError
from tools.verify_magazine_demo import verify_dropcap


def _allowed_metric(character) -> ControlledMetric:
    return replace(metric_for(character), source="advance_em_fallback")


def _font_path() -> Path:
    candidates = (
        Path(".runtime/demo-repair/cache/fonts/NotoSerif-Bold.ttf"),
        Path(".runtime/babeldoc-cache/fonts/NotoSerif-Bold.ttf"),
    )
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        pytest.skip("repository runtime font is not available")
    return path


def test_real_glyph_metric_enables_per_glyph_bbox_for_unicode() -> None:
    real = pymupdf.Font(fontfile=str(_font_path()))
    sample = pdf_character("A", 0.0, 0.0, font_id="mapped")
    typesetter = object.__new__(Typesetting)
    typesetter.font_mapper = SimpleNamespace(fontid2font={"mapped": real})
    full_font_bbox = tuple(
        float(getattr(real.bbox, name)) for name in ("x0", "y0", "x1", "y1")
    )
    assert real.this.m_internal.use_glyph_bbox == 0

    measured = typesetter.glyph_ink_metrics(sample)

    assert measured is not None
    assert real.this.m_internal.use_glyph_bbox == 1
    assert measured.source == "pymupdf.Font.glyph_bbox"
    assert measured.glyph_id == real.has_glyph(ord("A"))
    assert measured.ink_box_em == tuple(real.glyph_bbox(ord("A")))
    assert measured.ink_box_em != full_font_bbox
    assert measured.font_id == sample.pdf_style.font_id
    assert all(abs(value) < 10 for value in measured.ink_box_em)
    assert measured.ink_box_em[0] < measured.ink_box_em[2]
    assert measured.ink_box_em[1] < measured.ink_box_em[3]


def test_glyph_metric_falls_back_only_to_finite_advance_em_box() -> None:
    calls = []

    class AdvanceOnlyFont:
        def has_glyph(self, codepoint: int) -> int:
            calls.append(("has", codepoint))
            return 17

        def glyph_advance(self, codepoint: int) -> float:
            calls.append(("advance", codepoint))
            return 0.625

    sample = pdf_character("A", 0.0, 0.0, font_id="mapped")
    typesetter = object.__new__(Typesetting)
    typesetter.font_mapper = SimpleNamespace(
        fontid2font={"mapped": AdvanceOnlyFont()}
    )

    measured = typesetter.glyph_ink_metrics(sample)

    assert measured is not None
    assert measured.glyph_id == 17
    assert measured.ink_box_em == (0.0, 0.0, 0.625, 1.0)
    assert measured.advance_em == 0.625
    assert measured.source == "advance_em_fallback"
    assert calls == [("has", ord("A")), ("advance", ord("A"))]


@pytest.mark.parametrize(
    ("language", "paragraph_factory", "policy", "target_char", "target_index"),
    [
        (
            "zh-CN",
            chinese_render_paragraph,
            drop_cap_intent.POLICY_CHINESE_TWO_LINE_INITIAL,
            "中",
            2,
        ),
        (
            "en",
            english_render_paragraph,
            drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL,
            "A",
            2,
        ),
    ],
)
def test_direction_layout_preserves_punctuated_target_and_source_box(
    language,
    paragraph_factory,
    policy,
    target_char,
    target_index,
) -> None:
    paragraph = paragraph_factory()
    before_text = paragraph.unicode
    before_digest = hashlib.sha256(before_text.encode("utf-8")).hexdigest()
    before_box = copy.deepcopy(paragraph.box)
    config = drop_cap_render.load_render_config()
    regime = config.regime_for(language)
    assert regime is not None

    outcome = drop_cap_render.set_one(
        paragraph,
        regime,
        config,
        drop_cap_render._blank("p7#0", 7, "keep", language, regime.name),
        intent=direct_intent(policy),
        glyph_metric_resolver=metric_for,
        geometry_guard=geometry_guard(),
    )

    assert outcome["set"], outcome
    assert outcome["initial"] == target_char
    assert outcome["_target_index"] == target_index
    assert paragraph.box == before_box
    after_text = "".join(
        character.char_unicode or "" for character in paragraph_characters(paragraph)
    )
    assert after_text == before_text
    assert hashlib.sha256(after_text.encode("utf-8")).hexdigest() == before_digest
    if language.startswith("zh"):
        assert outcome["reserve_lines"] == 2
        assert outcome["third_line_start_x"] == outcome["body_box"][0]
    else:
        assert outcome["reserve_lines"] == 1
        assert outcome["second_line_start_x"] == outcome["body_box"][0]


def test_raised_initial_may_rise_above_its_anchored_article_box() -> None:
    paragraph = english_render_paragraph()
    config = drop_cap_render.load_render_config()
    regime = config.regime_for("en")
    assert regime is not None
    article_box = tuple(
        float(getattr(paragraph.box, name)) for name in ("x", "y", "x2", "y2")
    )
    guard = drop_cap_render.DecorativeGeometryGuard(
        page_box=(0.0, 0.0, 180.0, 120.0),
        article_boxes=(article_box,),
        obstacles=(),
    )

    outcome = drop_cap_render.set_one(
        paragraph,
        regime,
        config,
        drop_cap_render._blank("p7#0", 7, "keep", "en", regime.name),
        intent=direct_intent(drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL),
        glyph_metric_resolver=metric_for,
        geometry_guard=guard,
    )

    assert outcome["set"], outcome
    assert outcome["initial_ink_box"][1] <= article_box[3]
    assert outcome["initial_ink_box"][3] > article_box[3]


def _write_chain_report(config, *, outcome: str, fallback_reason=None) -> None:
    record = {
        "chain_id": "runtime-chain",
        "canonical_chain_id": "canonical-chain",
        "ordered_source_refs": ["p7#0", "p7#1"],
        "runtime_source_refs": ["p1#0", "p1#1"],
        "members": [
            {
                "source_ref": "p7#0",
                "runtime_source_ref": "p1#0",
                "chain_index": 0,
            },
            {
                "source_ref": "p7#1",
                "runtime_source_ref": "p1#1",
                "chain_index": 1,
            },
        ],
        "joint_call_count": 1,
        "outcome": outcome,
        "result_state": outcome,
        "fallback_reason": fallback_reason,
    }
    path = Path(config.get_working_file_path(drop_cap_render.CHAIN_REPORT_NAME))
    path.write_text(json.dumps({"chains": [record]}), encoding="utf-8")


def test_chain_member_reaches_renderer_only_after_joint_success(
    tmp_path, monkeypatch
) -> None:
    calls = []

    def refusal(_paragraph, _regime, _config, blank, **_kwargs):
        calls.append(blank["paragraph"])
        return drop_cap_render._refusal(blank, drop_cap_render.REVERT_COLLISION)

    monkeypatch.setattr(drop_cap_render, "set_one", refusal)
    for name, outcome, fallback, expected_calls in (
        ("fallback", "fallback", "verification_failed", []),
        ("joint", "joint_success", None, ["p7#0"]),
    ):
        paragraph = english_render_paragraph()
        paragraph.chain_id = "runtime-chain"
        paragraph.chain_index = 0
        docs = make_document([paragraph])
        article_ir = make_article_ir([paragraph])
        config = RuntimeConfig(tmp_path / name)
        register_render_intents(config, [paragraph])
        _write_chain_report(config, outcome=outcome, fallback_reason=fallback)
        calls.clear()

        report = drop_cap_render.apply(
            config,
            docs,
            article_document_ir=article_ir,
            typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
        )

        assert calls == expected_calls
        assert report is not None
        if not expected_calls:
            assert "chain_joint_success" in report["paragraphs"][0]["validation"][
                "failed"
            ]


def test_typed_refusal_restores_only_current_paragraph(
    tmp_path, monkeypatch
) -> None:
    first = english_render_paragraph()
    second = english_render_paragraph()
    docs = make_document([first, second])
    article_ir = make_article_ir([first, second])
    config = RuntimeConfig(tmp_path / "local-rollback")
    register_render_intents(config, [first, second])
    first_before = paragraph_snapshot(first)
    second_before = paragraph_snapshot(second)
    calls = 0

    def injected(paragraph, _regime, _config, blank, **_kwargs):
        nonlocal calls
        calls += 1
        paragraph_characters(paragraph)[0].box.x += 7.0
        if calls == 2:
            return drop_cap_render._refusal(
                blank, drop_cap_render.REVERT_NO_METRICS
            )
        outcome = dict(blank)
        outcome.update(
            {
                "set": True,
                "reverted": False,
                "revert_reason": None,
                "initial": "A",
                "initial_ink_box": [10.0, 50.0, 20.0, 90.0],
                "style_evidence": {"metric_source": "advance_em_fallback"},
                "reach": [10.0, 50.0, 20.0, 90.0],
                "collision_evidence": [],
                "detector_contract": {"missing_fields": [], "collision": []},
                "_target_index": 2,
            }
        )
        return outcome

    monkeypatch.setattr(drop_cap_render, "set_one", injected)
    monkeypatch.setattr(
        drop_cap_render,
        "_post_render_validation",
        lambda *_args: (None, {"checks": {}, "valid": True}),
    )

    report = drop_cap_render.apply(
        config,
        docs,
        article_document_ir=article_ir,
        typesetting_stage=SimpleNamespace(glyph_ink_metrics=metric_for),
    )

    assert report is not None and report["status"] == "failure"
    assert paragraph_snapshot(first) != first_before
    assert paragraph_snapshot(second) == second_before
    assert report["totals"]["committed"] == 1
    assert report["totals"]["failure"] == 1


def test_persisted_schema_and_offline_verifier_are_fail_closed(tmp_path) -> None:
    paragraph = english_render_paragraph()
    docs = make_document([paragraph])
    article_ir = make_article_ir([paragraph])
    work = tmp_path / "work"
    config = RuntimeConfig(work)
    register_render_intents(config, [paragraph])

    report = drop_cap_render.apply(
        config,
        docs,
        article_document_ir=article_ir,
        typesetting_stage=SimpleNamespace(glyph_ink_metrics=_allowed_metric),
    )
    assert report is not None and report["status"] == "success"
    persisted = json.loads(
        (work / drop_cap_render.REPORT_NAME).read_text(encoding="utf-8")
    )
    assert set(persisted["paragraphs"][0]) == DROPCAP_FIELDS
    row = persisted["paragraphs"][0]
    assert row["before_target_sha256"] == row["after_target_sha256"]
    assert row["target_char"] == "A" and row["target_index"] == 2

    (work / "drop_cap.report.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {"page": 7, "paragraph": "p7#0", "first_run": "A"}
                ]
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": "dropcap-demo",
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "direction": "zh-en",
                "dropcaps": [
                    {
                        "anchor": "p7#999",
                        "decision": "keep",
                        "diagnostic_ref": (
                            "paragraph_owner=p7#999;"
                            "visual_initial=A(same_paragraph_composition)"
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    verified = verify_dropcap(expectations, source, output, work, "zh", "en")
    assert verified["status"] == "pass"
    persisted["paragraphs"][0]["after_target_sha256"] = "0" * 64
    (work / drop_cap_render.REPORT_NAME).write_text(
        json.dumps(persisted), encoding="utf-8"
    )
    with pytest.raises(VerificationError, match="target digest changed"):
        verify_dropcap(expectations, source, output, work, "zh", "en")


def test_metric_font_mismatch_refuses_without_mutation() -> None:
    paragraph = english_render_paragraph()
    before = document_digest(make_document([copy.deepcopy(paragraph)]))
    config = drop_cap_render.load_render_config()
    regime = config.regime_for("en")
    assert regime is not None

    def mismatch(character):
        return replace(metric_for(character), font_id="another-mapped-font")

    outcome = drop_cap_render.set_one(
        paragraph,
        regime,
        config,
        drop_cap_render._blank("p7#0", 7, "keep", "en", regime.name),
        intent=direct_intent(drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL),
        glyph_metric_resolver=mismatch,
        geometry_guard=geometry_guard(),
    )

    assert outcome["revert_reason"] == drop_cap_render.REVERT_NO_METRICS
    assert document_digest(make_document([paragraph])) == before
