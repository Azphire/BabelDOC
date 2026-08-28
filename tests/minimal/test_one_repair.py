from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import minimal_detection
from babeldoc.magazine import minimal_repair
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.article_ir import ArticleIR
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.detectors.base import Issue
from tests.minimal.fakes import FixedWidthMapper
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph


class FakeTranslator:
    def __init__(self, response="这是修复后的正文", error=None):
        self.response = response
        self.error = error
        self.calls = []

    def translate(self, source):
        self.calls.append(source)
        if self.error is not None:
            raise self.error
        return self.response


class FakeTypesetter:
    def __init__(self, *, error=None, mutate_fixed=False, erase=False):
        self.font_mapper = FixedWidthMapper()
        self.error = error
        self.mutate_fixed = mutate_fixed
        self.erase = erase
        self.calls = []

    def render_paragraph(self, paragraph, page, fonts):
        self.calls.append((paragraph, page, fonts))
        if self.mutate_fixed:
            page.cropbox.box.x += 1.0
        if self.error is not None:
            paragraph.unicode = "mutated-before-error"
            raise self.error
        if self.erase:
            paragraph.pdf_paragraph_composition = []
            return
        style = paragraph.pdf_style
        if style is None:
            for composition in paragraph.pdf_paragraph_composition or ():
                holder = composition.pdf_same_style_unicode_characters
                if holder is not None:
                    style = holder.pdf_style
                    break
                group = composition.pdf_same_style_characters
                if group is not None and group.pdf_character:
                    style = group.pdf_character[0].pdf_style
                    break
        assert style is not None
        rendered_style = copy.deepcopy(style)
        rendered_style.font_id = self.font_mapper.base_font.font_id
        characters = [
            il_version_1.PdfCharacter(
                pdf_style=copy.deepcopy(rendered_style),
                box=il_version_1.Box(float(index), 0.0, float(index + 1), 10.0),
                char_unicode=character,
            )
            for index, character in enumerate(paragraph.unicode or "")
        ]
        paragraph.pdf_paragraph_composition = [
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    box=copy.deepcopy(paragraph.box),
                    pdf_style=copy.deepcopy(rendered_style),
                    pdf_character=characters,
                )
            )
        ]


class DetectorCallback:
    def __init__(self, before, *, remove_ids=(), error=None, fixed_holds=True):
        self.before = before
        self.remove_ids = set(remove_ids)
        self.error = error
        self.fixed_holds = fixed_holds
        self.calls = []

    def __call__(self, repair_owned_local_ref):
        self.calls.append(repair_owned_local_ref)
        if self.error is not None:
            raise self.error
        issues = tuple(
            issue for issue in self.before.issues if issue.id not in self.remove_ids
        )
        binding = None
        if repair_owned_local_ref is not None:
            physical_ref = next(
                issue.paragraph_refs[0]
                for issue in self.before.issues
                if issue.suggested_action_type == minimal_repair.TRANSLATE_ORPHAN
            )
            binding = {
                "physical_ref": physical_ref,
                "local_ref": repair_owned_local_ref,
                "symmetric_fixed_exclusion": True,
            }
        return minimal_detection.DetectionResult(
            issues,
            {
                "repair_owned_paragraph": binding,
                "fixed_comparison": {"holds": self.fixed_holds},
                "issues": [issue.as_record() for issue in issues],
            },
            self.before.report_path.parent / "issues.after.json",
        )


def _element(ref, page, order, *, role="body", box=(10.0, 10.0, 60.0, 25.0)):
    return SourceElementRef(
        source_ref=ref,
        page=page,
        column=0,
        reading_order=order,
        role=role,
        source_box=box,
        source_text_hash=f"source-{ref}",
        style_hash="style",
    )


def repair_fixture():
    paragraphs = [
        _paragraph("目标正文", "owned-out", (122.0, 10.0, 150.0, 25.0)),
        _paragraph("目标较大正文", "owned-large", (10.0, 30.0, 110.0, 65.0)),
        _paragraph(
            "This source line was never translated",
            "orphan",
            (10.0, 70.0, 110.0, 85.0),
            label="fallback_line",
        ),
        _paragraph(
            "chain member source",
            "chain",
            (10.0, 5.0, 60.0, 18.0),
            chain_id="chain-a",
            chain_index=0,
        ),
        _paragraph("流式正文", "flow", (65.0, 5.0, 110.0, 18.0)),
        _paragraph("首字下沉正文", "dropcap", (10.0, 88.0, 100.0, 98.0)),
        _paragraph("固定资产测试", "fixed", (65.0, 20.0, 115.0, 29.0)),
    ]
    paragraphs[5].drop_cap_candidate = True
    orphan_style = copy.deepcopy(paragraphs[2].pdf_style)
    paragraphs[2].pdf_style = None
    docs = il_version_1.Document(
        page=[
            _page(6, paragraphs),
            _page(7, [_paragraph("其他文章", "owner-b", (10.0, 10.0, 50.0, 25.0))]),
        ],
        total_pages=2,
    )
    refs = (
        ("p1#0", 0, (10.0, 10.0, 60.0, 25.0)),
        ("p1#1", 1, (10.0, 30.0, 110.0, 65.0)),
        ("p1#3", 2, (10.0, 5.0, 60.0, 18.0)),
        ("p1#4", 3, (65.0, 5.0, 110.0, 18.0)),
        ("p1#5", 4, (10.0, 88.0, 100.0, 98.0)),
        ("p1#6", 5, (65.0, 20.0, 115.0, 29.0)),
    )
    elements_a = tuple(_element(ref, 1, order, box=box) for ref, order, box in refs)
    element_b = _element("p2#0", 2, 6)
    article_ir = ArticleDocumentIR(
        articles=(
            ArticleIR("article-a", (1,), elements_a, (), ("chain-a",), ()),
            ArticleIR("article-b", (2,), (element_b,), (), (), ()),
        ),
        by_page={1: "article-a", 2: "article-b"},
        by_element={
            **dict.fromkeys((item.source_ref for item in elements_a), "article-a"),
            "p2#0": "article-b",
        },
        by_chain={"chain-a": "article-a"},
        by_chain_member={"p1#3": "chain-a"},
    )
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )
    # Prove the orphan style resolver uses existing holder style, not paragraph.pdf_style.
    paragraphs[2].pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                box=copy.deepcopy(paragraphs[2].box),
                pdf_style=copy.deepcopy(orphan_style),
                pdf_character=[
                    il_version_1.PdfCharacter(
                        pdf_style=copy.deepcopy(orphan_style),
                        box=il_version_1.Box(
                            float(index), 0.0, float(index + 1), 10.0
                        ),
                        char_unicode=character,
                    )
                    for index, character in enumerate(paragraphs[2].unicode)
                ],
            )
        )
    ]
    flow = {
        "cross_page_segments": [
            {
                "status": "applied",
                "action_status": "committed",
                "touched_sources": ["p1#4"],
                "placements": [{"source_ref": "p1#4", "render_ref": "p1#4"}],
                "released_holders": [],
                "committed_flow_owned_refs": [],
            }
        ]
    }
    return docs, article_ir, baseline, flow


def make_issue(kind, refs, action, *, severity=None):
    evidence = {
        "untranslated_residue": {"residue_ratio": 1.0},
        "out_of_page": {"overflow_ratio": 0.2},
        "text_text_collision": {"coverage": 0.8, "iou": 0.4},
        "fragment_cluster": {"member_count": 3},
    }.get(kind, {})
    return Issue(
        kind=kind,
        page=int(refs[0].split("#")[0][1:]) if refs else 7,
        paragraph_refs=tuple(refs),
        geometry=None,
        severity=severity or ("low" if kind == "fragment_cluster" else "high"),
        evidence=evidence,
        detector=kind,
        suggested_action_type=action,
    ).with_severity_fields(tuple(evidence))


def before_result(directory, issues):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "issues.before.json"
    path.write_text("{}\n", encoding="utf-8")
    return minimal_detection.DetectionResult(
        tuple(issues),
        {"issues": [issue.as_record() for issue in issues]},
        path,
    )


def run_repair(
    tmp_path,
    name,
    issues,
    *,
    translator=None,
    typesetter=None,
    callback=None,
    mutate=None,
):
    docs, article_ir, baseline, flow = repair_fixture()
    if mutate is not None:
        mutate(docs)
    before = before_result(tmp_path / name, issues)
    translator = translator or FakeTranslator()
    typesetter = typesetter or FakeTypesetter()
    if callback is None:
        selected, _action = minimal_repair._select_issue(
            before, minimal_repair.load_repair_config()
        )
        callback = DetectorCallback(
            before, remove_ids=() if selected is None else (selected.id,)
        )
    result = minimal_repair.repair_once(
        before,
        docs,
        article_ir,
        baseline,
        typesetter,
        SimpleNamespace(lang_out="zh", translator=translator),
        flow,
        callback,
    )
    return result, docs, translator, typesetter, callback, before


def test_closed_actions_and_deterministic_selection(tmp_path):
    config = minimal_repair.load_repair_config()
    assert config.actions == minimal_repair.ACTIONS == (
        "translate_orphan_text",
        "refit_or_reflow_owned_paragraph",
        "no_op",
    )
    orphan = make_issue(
        "untranslated_residue", ("p7#2",), minimal_repair.TRANSLATE_ORPHAN
    )
    refit = make_issue("out_of_page", ("p7#0",), minimal_repair.REFIT_OWNED)
    fragment = make_issue("fragment_cluster", ("p7#0",), minimal_repair.NO_OP)
    critical = make_issue(
        "fixed_asset_drift", ("p7#6",), minimal_repair.NO_OP, severity="critical"
    )
    result, _docs, translator, _typesetter, callback, _before = run_repair(
        tmp_path, "critical", [orphan, critical]
    )
    assert result.selected_action == minimal_repair.NO_OP
    assert translator.calls == callback.calls == []
    same = make_issue(
        "chain_conservation", ("p7#3",), minimal_repair.NO_OP, severity="high"
    )
    result, _docs, translator, _typesetter, callback, _before = run_repair(
        tmp_path, "same", [refit, same]
    )
    assert result.selected_action == minimal_repair.NO_OP
    assert translator.calls == callback.calls == []
    result, _docs, _translator, _typesetter, callback, _before = run_repair(
        tmp_path, "higher", [fragment, refit]
    )
    assert result.accepted and result.selected_action == minimal_repair.REFIT_OWNED
    assert callback.calls == [None]


def test_no_issues_and_no_op_add_no_action_or_pass(tmp_path):
    for name, issues, selected in (
        ("empty", [], None),
        (
            "noop",
            [make_issue("fragment_cluster", ("p7#0",), minimal_repair.NO_OP)],
            minimal_repair.NO_OP,
        ),
    ):
        result, _docs, translator, _typesetter, callback, _before = run_repair(
            tmp_path, name, issues
        )
        assert result.selected_action == selected
        assert result.record["action_count"] == 0
        assert result.record["detection_passes_added"] == 0
        assert translator.calls == callback.calls == []


def test_orphan_uses_one_fake_request_and_preserves_style(tmp_path):
    orphan = make_issue(
        "untranslated_residue", ("p7#2",), minimal_repair.TRANSLATE_ORPHAN
    )
    result, docs, translator, typesetter, callback, _before = run_repair(
        tmp_path, "orphan", [orphan]
    )
    assert result.accepted and result.record["action_count"] == 1
    assert result.record["translator_requests"] == len(translator.calls) == 1
    assert len(typesetter.calls) == 1 and callback.calls == ["p1#2"]
    paragraph = docs.page[0].pdf_paragraph[2]
    assert paragraph.pdf_style is None
    characters = paragraph.pdf_paragraph_composition[0].pdf_same_style_characters
    assert characters is not None
    assert "".join(char.char_unicode for char in characters.pdf_character) == (
        "这是修复后的正文"
    )
    assert all(
        char.pdf_style.font_id == "target-body" for char in characters.pdf_character
    )


def test_refit_uses_no_translator_and_only_one_candidate_pass(tmp_path):
    refit = make_issue("out_of_page", ("p7#0",), minimal_repair.REFIT_OWNED)
    result, docs, translator, typesetter, callback, _before = run_repair(
        tmp_path, "refit", [refit]
    )
    assert result.accepted and result.record["detection_passes_added"] == 1
    assert translator.calls == [] and callback.calls == [None]
    assert len(typesetter.calls) == 1
    assert docs.page[0].pdf_paragraph[0].box.x == 10.0


@pytest.mark.parametrize(
    ("name", "item", "reason"),
    [
        (
            "cross-owner",
            make_issue(
                "text_text_collision",
                ("p7#0", "p8#0"),
                minimal_repair.REFIT_OWNED,
            ),
            "collision_crosses_page",
        ),
        (
            "chain",
            make_issue("out_of_page", ("p7#3",), minimal_repair.REFIT_OWNED),
            "chain_member",
        ),
        (
            "flow",
            make_issue("out_of_page", ("p7#4",), minimal_repair.REFIT_OWNED),
            "article_flow_owned",
        ),
        (
            "dropcap",
            make_issue("out_of_page", ("p7#5",), minimal_repair.REFIT_OWNED),
            "drop_cap_candidate",
        ),
    ],
)
def test_protected_targets_are_refused(tmp_path, name, item, reason):
    result, _docs, translator, _typesetter, callback, _before = run_repair(
        tmp_path, name, [item]
    )
    assert result.record["reason"] == reason
    assert result.record["applied_count"] == 0
    assert result.record["restored_digest"]["holds"] is True
    assert translator.calls == callback.calls == []


def test_strict_improvement_and_single_action(tmp_path):
    first = make_issue(
        "untranslated_residue", ("p7#2",), minimal_repair.TRANSLATE_ORPHAN
    )
    second = make_issue(
        "out_of_page", ("p7#6",), minimal_repair.REFIT_OWNED, severity="medium"
    )
    result, docs, translator, _typesetter, callback, _before = run_repair(
        tmp_path, "single", [first, second]
    )
    assert result.record["action_count"] == result.record["applied_count"] == 1
    assert len(translator.calls) == len(callback.calls) == 1
    assert docs.page[0].pdf_paragraph[6].box.x == 65.0

    before = before_result(tmp_path / "reject", [second])
    docs, article_ir, baseline, flow = repair_fixture()
    callback = DetectorCallback(before, remove_ids=())
    rejected = minimal_repair.repair_once(
        before,
        docs,
        article_ir,
        baseline,
        FakeTypesetter(),
        SimpleNamespace(lang_out="zh", translator=FakeTranslator("unused")),
        flow,
        callback,
    )
    assert rejected.rolled_back and not rejected.accepted
    assert rejected.record["detection_passes_added"] == 1
    assert rejected.final_detection.record["restored_from_before"] is True


def test_malformed_action_vocabulary_fails_closed():
    raw = json.loads(minimal_repair.CONFIG_PATH.read_text(encoding="utf-8"))
    raw["actions"].append("repair_loop")
    with pytest.raises(minimal_repair.MinimalRepairError):
        minimal_repair.parse_repair_config(raw, "bad-config")
