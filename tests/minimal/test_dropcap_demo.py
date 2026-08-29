from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import drop_cap
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import drop_cap_render
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import ArticlePolicyEvidence
from babeldoc.magazine.article_ir import ArticleRegionSlot
from babeldoc.magazine.article_ir import SourceElementRef
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

from tools import verify_magazine_demo as demo_verifier


def _standalone_initial_fixture(*, duplicate_visual=False, duplicate_owner=False):
    body_text = "内加尔加强了应对核安保威胁并继续到第二行"
    body_characters = []
    for index, glyph in enumerate(body_text):
        line = index // 10
        column = index % 10
        body_characters.append(
            pdf_character(
                glyph,
                40.0 + column * 10.0,
                80.0 - line * 15.0,
                font_size=10.0,
                width=10.0,
            )
        )
    owner = il_version_1.PdfParagraph(
        box=il_version_1.Box(10.0, 40.0, 150.0, 90.0),
        pdf_style=body_characters[0].pdf_style,
        unicode=body_text,
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    pdf_style=body_characters[0].pdf_style,
                    pdf_character=body_characters,
                )
            )
        ],
        layout_label="plain text",
        debug_id="owner-debug",
    )

    def companion(debug_id="visual-debug"):
        character = pdf_character(
            "塞",
            10.0,
            82.0,
            font_size=30.0,
            width=25.0,
        )
        return il_version_1.PdfParagraph(
            # The semantic paragraph box is deliberately distinct from glyph
            # ink: real display initials commonly overpaint beyond this box.
            box=il_version_1.Box(
                character.box.x + 1.0,
                character.box.y + 1.0,
                character.box.x2 - 1.0,
                character.box.y2 - 1.0,
            ),
            pdf_style=character.pdf_style,
            unicode="塞",
            pdf_paragraph_composition=[
                il_version_1.PdfParagraphComposition(
                    pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                        pdf_style=character.pdf_style,
                        pdf_character=[character],
                    )
                )
            ],
            layout_label="plain text",
            debug_id=debug_id,
        )

    paragraphs = [owner, companion()]
    if duplicate_visual:
        paragraphs.append(companion("visual-debug-2"))
    if duplicate_owner:
        paragraphs.append(copy.deepcopy(owner))
        paragraphs[-1].debug_id = "owner-debug-2"
    docs = make_document(paragraphs)
    article_id = "standalone-article"
    elements = []
    visual_indices = [
        index
        for index, paragraph in enumerate(paragraphs)
        if (paragraph.unicode or "") == "塞"
    ]
    owner_indices = [index for index in range(len(paragraphs)) if index not in visual_indices]
    reading_orders = {
        index: order
        for order, index in enumerate([*visual_indices, *owner_indices], start=1)
    }
    for index, paragraph in enumerate(paragraphs):
        elements.append(
            SourceElementRef(
                source_ref=f"p1#{index}",
                page=1,
                column=0,
                reading_order=reading_orders[index],
                role="plain text",
                source_box=tuple(
                    float(getattr(paragraph.box, name))
                    for name in ("x", "y", "x2", "y2")
                ),
                source_text_hash=hashlib.sha256(
                    (paragraph.unicode or "").encode("utf-8")
                ).hexdigest(),
                style_hash=drop_cap_intent.style_hash(paragraph.pdf_style),
            )
        )
    elements.sort(key=lambda item: item.reading_order)
    article = ArticleIR(
        article_id=article_id,
        pages=(1,),
        elements=tuple(elements),
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
    article_ir = ArticleDocumentIR(
        articles=(article,),
        by_page={1: article_id},
        by_element={element.source_ref: article_id for element in elements},
        by_chain={},
    )
    return docs, article_ir


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


def _write_tracking_target(work: Path, reference: str, target: str) -> None:
    (work / "translate_tracking.json").write_text(
        json.dumps(
            {
                "page": [
                    {
                        "paragraph": [
                            {
                                "source_ref": reference,
                                "runtime_source_ref": reference,
                                "output": target,
                            }
                        ]
                    }
                ],
                "cross_page": [],
                "cross_column": [],
            }
        ),
        encoding="utf-8",
    )


def _write_chain_target(work: Path, chains: list[dict]) -> None:
    (work / "chain_translation.report.json").write_text(
        json.dumps({"chains": chains}),
        encoding="utf-8",
    )


def test_dropcap_owner_target_reads_real_chain_fragment_shape(tmp_path) -> None:
    _write_chain_target(
        tmp_path,
        [
            {
                "ordered_source_refs": ["p8#0", "p8#1"],
                "ordered_fragments": ["Senegal opens", "and continues"],
                "members": [
                    {"segment": {"chars": 13, "start": 0, "end": 13, "index": 0}},
                    {"segment": {"chars": 13, "start": 13, "end": 26, "index": 1}},
                ],
            }
        ],
    )

    assert demo_verifier._dropcap_owner_target("p8#0", tmp_path) == "Senegal opens"


@pytest.mark.parametrize("damage", ["length", "empty", "ambiguous"])
def test_dropcap_owner_target_rejects_malformed_chain_evidence(
    tmp_path,
    damage,
) -> None:
    chain = {
        "ordered_source_refs": ["p8#0", "p8#1"],
        "ordered_fragments": ["Senegal opens", "and continues"],
        "members": [
            {"segment": {"chars": 13, "start": 0, "end": 13, "index": 0}},
            {"segment": {"chars": 13, "start": 13, "end": 26, "index": 1}},
        ],
    }
    if damage == "length":
        chain["ordered_fragments"] = ["Senegal opens"]
        chains = [chain]
        expected = "target evidence is invalid"
    elif damage == "empty":
        chain["ordered_fragments"][0] = ""
        chains = [chain]
        expected = "target evidence is invalid"
    else:
        chains = [chain, copy.deepcopy(chain)]
        expected = "target is ambiguous"
    _write_chain_target(tmp_path, chains)

    with pytest.raises(VerificationError, match=expected):
        demo_verifier._dropcap_owner_target("p8#0", tmp_path)


def test_standalone_visual_initial_is_bound_merged_and_rendered_as_target(
    tmp_path,
    monkeypatch,
) -> None:
    docs, article_ir = _standalone_initial_fixture()
    owner, companion = docs.page[0].pdf_paragraph[:2]
    before_source = (companion.unicode or "") + (owner.unicode or "")
    config = RuntimeConfig(tmp_path / "standalone-binding", language="en")

    candidates = drop_cap.mark(
        config,
        [(7, docs.page[0])],
        article_document_ir=article_ir,
    )

    assert [candidate.reference for candidate in candidates] == ["p7#0"]
    candidate = candidates[0]
    assert candidate.visual_initial_reference == "p7#1"
    assert candidate.first_run == "塞"
    visual_character_box = tuple(
        float(getattr(paragraph_characters(companion)[0].box, name))
        for name in ("x", "y", "x2", "y2")
    )
    assert candidate.visual_initial_box == tuple(
        float(getattr(companion.box, name)) for name in ("x", "y", "x2", "y2")
    )
    assert candidate.visual_initial_box != visual_character_box
    assert candidate.binding_proof["visual_initial_glyph_box"] == list(
        visual_character_box
    )
    assert candidate.binding_proof["kind"] == "standalone_visual_initial"
    assert candidate.binding_proof["unique_owner_count"] == 1
    assert candidate.binding_proof["unique_visual_count"] == 1

    applied = drop_cap.apply(config, [(7, docs.page[0])])
    assert applied is not None and applied["totals"]["merged"] == 1
    assert owner.unicode == before_source
    assert companion.unicode == ""
    assert companion.pdf_paragraph_composition == []
    assert "".join(
        character.char_unicode or "" for character in paragraph_characters(owner)
    ) == before_source
    intent = drop_cap_intent.intent_for(config, "p7#0")
    assert intent is not None
    assert intent.visual_initial_ref == "p7#1"
    assert intent.binding_proof == dict(candidate.binding_proof)

    translated = english_render_paragraph(
        "Senegal continues across the measured second body line"
    )
    translated.debug_id = owner.debug_id
    docs.page[0].pdf_paragraph[0] = translated
    rendered = drop_cap_render.apply(
        config,
        docs,
        article_document_ir=article_ir,
        typesetting_stage=SimpleNamespace(glyph_ink_metrics=_allowed_metric),
    )
    assert rendered is not None and rendered["status"] == "success"
    assert rendered["paragraphs"][0]["initial"] == "S"
    assert intent.target_char == "S"
    assert "".join(
        character.char_unicode or ""
        for character in paragraph_characters(docs.page[0].pdf_paragraph[0])
    ) == translated.unicode
    assert companion.unicode == "" and companion.pdf_paragraph_composition == []

    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"standalone-source")
    output.write_bytes(b"standalone-output")
    _write_tracking_target(config.working_dir, "p7#0", translated.unicode)
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "sample_id": "standalone-dropcap",
                "source_sha256": hashlib.sha256(b"standalone-source").hexdigest(),
                "direction": "zh-en",
                "dropcaps": [
                    {
                        "anchor": "p7#69",
                        "decision": "keep",
                        "diagnostic_ref": (
                            "paragraph_owner=p7#69;visual_initial=p7#83(塞)"
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        demo_verifier,
        "_toc_anchor_inventory",
        lambda _expectations: {
            "p7#69": {
                "source_text_sha256": candidate.source_text_sha256,
                "source_box": list(candidate.source_box),
            },
            "p7#83": {
                "source_text_sha256": candidate.visual_initial_text_sha256,
                "source_box": list(candidate.visual_initial_box),
            },
        },
    )
    assert verify_dropcap(
        expectations,
        source,
        output,
        config.working_dir,
        "zh",
        "en",
    )["status"] == "pass"

    intent_report_path = config.working_dir / drop_cap_intent.REPORT_NAME
    intent_report = json.loads(intent_report_path.read_text(encoding="utf-8"))
    intent_report["intents"][0]["visual_initial_ref"] = "p7#9"
    intent_report_path.write_text(json.dumps(intent_report), encoding="utf-8")
    with pytest.raises(VerificationError, match="binding proof is invalid"):
        verify_dropcap(
            expectations,
            source,
            output,
            config.working_dir,
            "zh",
            "en",
        )


@pytest.mark.parametrize(
    "failure",
    ["title", "folio", "formula", "far", "after_owner", "cross_article"],
)
def test_standalone_visual_initial_rejects_unproved_relationship(failure) -> None:
    docs, article_ir = _standalone_initial_fixture()
    owner, companion = docs.page[0].pdf_paragraph[:2]
    if failure in {"title", "folio"}:
        companion.layout_label = failure
    elif failure == "formula":
        character = paragraph_characters(companion)[0]
        companion.pdf_paragraph_composition = [
            il_version_1.PdfParagraphComposition(
                pdf_formula=il_version_1.PdfFormula(
                    box=copy.deepcopy(companion.box),
                    pdf_character=[character],
                    pdf_curve=[
                        il_version_1.PdfCurve(
                            box=il_version_1.Box(12.0, 82.0, 14.0, 84.0)
                        )
                    ],
                )
            )
        ]
    elif failure == "far":
        companion.box.x += 100.0
        companion.box.x2 += 100.0
        character = paragraph_characters(companion)[0]
        character.box.x += 100.0
        character.box.x2 += 100.0
    elif failure == "after_owner":
        # A nearby independent display letter painted after the body is not an
        # opening initial, even if its geometry and font ratio look decorative.
        visual = next(
            item
            for item in article_ir.articles[0].elements
            if item.source_ref == "p1#1"
        )
        owner_element = next(
            item
            for item in article_ir.articles[0].elements
            if item.source_ref == "p1#0"
        )
        article_ir = replace(
            article_ir,
            articles=(
                replace(
                    article_ir.articles[0],
                    elements=(
                        replace(owner_element, reading_order=1),
                        replace(visual, reading_order=2),
                    ),
                ),
            ),
        )
    else:
        owner_element = next(
            item for item in article_ir.articles[0].elements if item.source_ref == "p1#0"
        )
        companion_element = next(
            item for item in article_ir.articles[0].elements if item.source_ref == "p1#1"
        )
        visual_article = replace(
            article_ir.articles[0],
            article_id="visual-article",
            elements=(companion_element,),
        )
        owner_article = replace(
            article_ir.articles[0],
            article_id="owner-article",
            elements=(owner_element,),
        )
        article_ir = SimpleNamespace(
            articles=(visual_article, owner_article),
            by_page={1: "owner-article"},
            by_element={"p1#1": "visual-article", "p1#0": "owner-article"},
            by_chain={},
        )
    config = RuntimeConfig(Path(".runtime") / f"negative-{failure}")
    assert drop_cap.mark(
        config,
        [(7, docs.page[0])],
        article_document_ir=article_ir,
    ) == []
    assert not owner.drop_cap_candidate


@pytest.mark.parametrize("duplicate", ["visual", "owner"])
def test_standalone_visual_initial_rejects_ambiguous_binding(duplicate) -> None:
    docs, article_ir = _standalone_initial_fixture(
        duplicate_visual=duplicate == "visual",
        duplicate_owner=duplicate == "owner",
    )
    config = RuntimeConfig(Path(".runtime") / f"ambiguous-{duplicate}")
    assert drop_cap.mark(
        config,
        [(7, docs.page[0])],
        article_document_ir=article_ir,
    ) == []
    assert not any(
        paragraph.drop_cap_candidate for paragraph in docs.page[0].pdf_paragraph
    )


def test_standalone_visual_initial_does_not_consume_owner_body_rank() -> None:
    docs, article_ir = _standalone_initial_fixture()
    article = replace(article_ir.articles[0], pages=(0, 1))
    config = replace(drop_cap.load_drop_cap_config(), max_body_rank_in_article=1)

    candidates = drop_cap.find_standalone_candidates(
        [(7, 1, docs.page[0])],
        SimpleNamespace(articles=(article,)),
        config,
        drop_cap.body_labels(),
    )

    assert len(candidates) == 1
    assert candidates[0].reference == "p7#0"
    assert candidates[0].binding_proof["body_rank"] == 1


def test_standalone_visual_initial_apply_rolls_back_owner_and_companion(
    tmp_path,
    monkeypatch,
) -> None:
    docs, article_ir = _standalone_initial_fixture()
    config = RuntimeConfig(tmp_path / "standalone-rollback")
    candidates = drop_cap.mark(
        config,
        [(7, docs.page[0])],
        article_document_ir=article_ir,
    )
    assert len(candidates) == 1
    before_document = document_digest(docs)
    before_intent = drop_cap_intent.intent_for(config, "p7#0").as_record()

    class SentinelError(Exception):
        pass

    marker = SentinelError("late sidecar failure")

    def fail(*_args, **_kwargs):
        raise marker

    monkeypatch.setattr(drop_cap, "_write_apply_report", fail)
    with pytest.raises(SentinelError) as raised:
        drop_cap.apply(config, [(7, docs.page[0])])
    assert raised.value is marker
    assert document_digest(docs) == before_document
    assert drop_cap_intent.intent_for(config, "p7#0").as_record() == before_intent


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


def test_decorative_guard_ignores_existing_paragraph_background() -> None:
    paragraph = english_render_paragraph()
    page = make_document([paragraph]).page[0]
    background = fixed_assets.AssetRecord(
        reference="background",
        asset_type="pdf_figure",
        page=7,
        bbox=(0.0, 40.0, 20.0, 100.0),
        digest="background-digest",
        movable=False,
        protected=True,
    )
    foreground = fixed_assets.AssetRecord(
        reference="foreground",
        asset_type="pdf_figure",
        page=7,
        bbox=(155.0, 40.0, 175.0, 100.0),
        digest="foreground-digest",
        movable=False,
        protected=True,
    )
    inventory = fixed_assets.FixedAssetInventory(
        assets=(background, foreground),
        page_sizes=(),
    )

    guard = drop_cap_render._decorative_guard(
        page,
        7,
        0,
        "p7#0",
        direct_intent(drop_cap_intent.POLICY_ENGLISH_RAISED_INITIAL),
        None,
        inventory,
    )

    assert [reference for reference, _box in guard.obstacles] == ["foreground"]


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
    intent = register_render_intents(config, [paragraph])[0]
    proof = {
        "kind": "same_paragraph_composition",
        "owner_ref": "p7#0",
        "visual_initial_ref": "p7#0",
        "source_character_count": 1,
        "size_ratio": 3.0,
        "minimum_size_ratio": 2.0,
        "unique_owner_count": 1,
        "unique_visual_count": 1,
    }
    intent.visual_initial_ref = "p7#0"
    intent.binding_proof = proof

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
                    {
                        "page": 7,
                        "paragraph": "p7#0",
                        "first_run": "A",
                        "visual_initial_ref": "p7#0",
                        "binding_proof": proof,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    _write_tracking_target(work, "p7#0", paragraph.unicode)
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


def test_bull_standalone_truth_requires_both_corpus_nodes_and_target_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    expectations_path = (
        root / "tests" / "fixtures" / "demo" / "expectations" / "bull-zh.json"
    )
    expectations = json.loads(expectations_path.read_text(encoding="utf-8"))
    inventory = demo_verifier._toc_anchor_inventory(expectations)
    assert inventory is not None
    owner_node = inventory["p8#69"]
    visual_node = inventory["p8#83"]
    assert visual_node == {
        "source_ref": "p8#83",
        "physical_page": 8,
        "source_text_sha256": (
            "3d776eaca02874cbe18689e373e084cc150f208ddc4c5458c49aad7a06d56546"
        ),
        "source_box": [171.426356, 461.816104, 198.789637, 474.770556],
        "debug_id": "T1C1E",
    }

    work = tmp_path / "work"
    work.mkdir()
    owner_ref = "p8#0"
    visual_ref = "p8#14"
    proof = {
        "kind": "standalone_visual_initial",
        "owner_ref": owner_ref,
        "visual_initial_ref": visual_ref,
        "article_id": "article-bull-opener",
        "owner_reading_order": 108,
        "visual_reading_order": 107,
        "column": 1,
        "body_rank": 1,
        "opens_article": True,
        "source_character_count": 1,
        "size_ratio": 2.727273,
        "minimum_size_ratio": 2.0,
        "body_size": 11.0,
        "visual_font_id": "visual-font",
        "body_font_id": "body-font",
        "visual_font_size": 30.0,
        "visual_initial_glyph_box": [170.0, 451.0, 200.0, 481.0],
        "owner_first_line_box": [203.0, 451.0, 350.0, 460.0],
        "logical_start_delta": 0.470819,
        "first_line_gap": 3.0,
        "vertical_gap": 0.0,
        "unique_owner_count": 1,
        "unique_visual_count": 1,
    }
    candidate = {
        "page": 8,
        "paragraph": owner_ref,
        "first_run": "塞",
        "source_text_sha256": owner_node["source_text_sha256"],
        "source_box": owner_node["source_box"],
        "visual_initial_ref": visual_ref,
        "visual_initial_text_sha256": visual_node["source_text_sha256"],
        "visual_initial_box": visual_node["source_box"],
        "binding_proof": proof,
    }
    (work / "drop_cap.report.json").write_text(
        json.dumps({"candidates": [candidate]}),
        encoding="utf-8",
    )
    intent = {
        "source_ref": owner_ref,
        "visual_initial_ref": visual_ref,
        "binding_proof": proof,
        "decision": "keep",
        "flatten_status": "applied",
        "render_status": "applied",
        "target_char": "S",
        "target_index": 0,
        "target_policy": "english_raised_initial",
    }
    intent_report = {"intents": [intent]}
    (work / "drop_cap_intent.report.json").write_text(
        json.dumps(intent_report),
        encoding="utf-8",
    )
    target = "Senegal has strengthened its preparedness"
    digest = hashlib.sha256(target.encode("utf-8")).hexdigest()
    render_row = {
        "source_ref": owner_ref,
        "decision": "keep",
        "target_char": "S",
        "target_index": 0,
        "direction_policy": "english_raised_initial",
        "metric_source": "advance_em_fallback",
        "initial_box": [170.0, 430.0, 200.0, 475.0],
        "before_target_sha256": digest,
        "after_target_sha256": digest,
        "status": "committed",
        "failure_reason": None,
    }
    render_report = {
        "schema_version": "drop-cap-render.v1",
        "status": "success",
        "target_lang": "en",
        "paragraphs": [render_row],
        "totals": {"active": 1, "committed": 1, "failure": 0},
    }
    (work / drop_cap_render.REPORT_NAME).write_text(
        json.dumps(render_report),
        encoding="utf-8",
    )
    _write_tracking_target(work, owner_ref, target)
    source = root / "examples" / "input" / "bull-zh.pdf"
    output = tmp_path / "output.pdf"
    output.write_bytes(b"offline-verifier-output")

    assert verify_dropcap(
        expectations_path,
        source,
        output,
        work,
        "zh",
        "en",
    )["status"] == "pass"

    stable_visual_box = list(candidate["visual_initial_box"])
    candidate["visual_initial_box"] = [
        stable_visual_box[0] + 1.0,
        *stable_visual_box[1:],
    ]
    (work / "drop_cap.report.json").write_text(
        json.dumps({"candidates": [candidate]}),
        encoding="utf-8",
    )
    with pytest.raises(VerificationError, match="truth match is not unique"):
        verify_dropcap(expectations_path, source, output, work, "zh", "en")
    candidate["visual_initial_box"] = stable_visual_box
    (work / "drop_cap.report.json").write_text(
        json.dumps({"candidates": [candidate]}),
        encoding="utf-8",
    )

    render_report["paragraphs"][0]["target_char"] = "N"
    intent_report["intents"][0]["target_char"] = "N"
    (work / drop_cap_render.REPORT_NAME).write_text(
        json.dumps(render_report), encoding="utf-8"
    )
    (work / "drop_cap_intent.report.json").write_text(
        json.dumps(intent_report), encoding="utf-8"
    )
    with pytest.raises(
        VerificationError,
        match="initial disagrees with owner target",
    ):
        verify_dropcap(expectations_path, source, output, work, "zh", "en")

    render_report["paragraphs"][0]["target_char"] = "S"
    intent_report["intents"][0]["target_char"] = "S"
    (work / drop_cap_render.REPORT_NAME).write_text(
        json.dumps(render_report), encoding="utf-8"
    )
    (work / "drop_cap_intent.report.json").write_text(
        json.dumps(intent_report), encoding="utf-8"
    )
    monkeypatch.setattr(
        demo_verifier,
        "_toc_anchor_inventory",
        lambda _expectations: {
            reference: node
            for reference, node in inventory.items()
            if reference != "p8#83"
        },
    )
    with pytest.raises(
        VerificationError,
        match="frozen owner/visual node is missing",
    ):
        verify_dropcap(expectations_path, source, output, work, "zh", "en")


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
