"""B17 short-label admission: the ideographic floor and the script-aware tests.

Three judgments ride one script measurement. A wholly-Han label of one
character reaches down to its own floor, because one ideograph is one word.
A neighbour written wholly in another script does not defeat solitarity,
because a word does not break across scripts. And a label standing on its
own other-script double is a bilingual pair the page printed on purpose,
refused with a recorded reason rather than translated into a duplicate.
"""

from __future__ import annotations

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.magazine import demo_coverage
from babeldoc.magazine import short_unit


def _paragraph(
    text: str,
    x: float,
    y: float,
    *,
    width: float | None = None,
    font_size: float = 9.0,
    label: str = "fallback_line",
    debug_id: str = "unit",
) -> il.PdfParagraph:
    width = len(text) * font_size if width is None else width
    style = il.PdfStyle(font_id="body", font_size=font_size)
    advance = width / max(len(text), 1)
    characters = [
        il.PdfCharacter(
            char_unicode=glyph,
            box=il.Box(
                x + index * advance, y, x + (index + 1) * advance, y + font_size
            ),
            pdf_style=style,
            advance=advance,
            xobj_id=0,
        )
        for index, glyph in enumerate(text)
    ]
    box = il.Box(x, y, x + width, y + font_size)
    return il.PdfParagraph(
        unicode=text,
        box=box,
        pdf_style=style,
        layout_label=label,
        debug_id=debug_id,
        vertical=False,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_characters=il.PdfSameStyleCharacters(
                    box=box, pdf_style=style, pdf_character=characters
                )
            )
        ],
    )


def _docs(paragraphs) -> il.Document:
    page = il.Page(page_number=5, pdf_paragraph=list(paragraphs))
    return il.Document(page=[page], total_pages=5)


def _candidates(paragraphs):
    config = short_unit.load_short_unit_config()
    return short_unit.candidates(_docs(paragraphs), 5, config, fractured={})


# --- the ideographic floor ----------------------------------------------------


def test_a_single_han_axis_label_clears_its_own_floor() -> None:
    label = _paragraph("年", 152.0, 323.0, debug_id="axis")
    found = _candidates([label])
    assert [unit.paragraph for unit in found] == [label]
    assert found[0].shape == short_unit.SHAPE_LABEL


def test_a_single_latin_letter_keeps_the_general_floor() -> None:
    stray = _paragraph("T", 152.0, 323.0, debug_id="stray")
    assert _candidates([stray]) == []


def test_a_two_character_han_label_is_admitted_as_before() -> None:
    label = _paragraph("主编", 60.0, 500.0, debug_id="role")
    assert len(_candidates([label])) == 1


# --- script-blind solitarity --------------------------------------------------


def test_an_other_script_neighbour_does_not_defeat_solitarity() -> None:
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    header = _paragraph(
        "FROM THE", 340.0, 746.0, font_size=22.0, debug_id="header", width=107.0
    )
    found = _candidates([header, label])
    assert [unit.paragraph for unit in found] == [label]


def test_a_same_script_neighbour_still_defeats_solitarity() -> None:
    piece = _paragraph("的后", 380.0, 745.0, debug_id="piece")
    rest = _paragraph("遗症从头说起继续下去", 300.0, 745.0, width=79.0, debug_id="rest")
    assert _candidates([rest, piece]) == []


# --- the bilingual companion --------------------------------------------------


def test_a_label_on_its_other_script_double_is_a_twin() -> None:
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    double = _paragraph(
        "EDITOR", 455.0, 746.0, font_size=22.0, debug_id="double", width=73.0
    )
    assert demo_coverage.cross_script_twin(label, [label, double]) is True
    assert demo_coverage.cross_script_twin(double, [label, double]) is True


def test_labels_merely_beside_each_other_are_not_twins() -> None:
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    beside = _paragraph(
        "FROM THE", 340.0, 746.0, font_size=22.0, debug_id="beside", width=107.0
    )
    assert demo_coverage.cross_script_twin(label, [label, beside]) is False


def test_coverage_names_the_source_side_of_a_visible_twin(
    tmp_path, monkeypatch
) -> None:
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    double = _paragraph(
        "EDITOR", 455.0, 746.0, font_size=22.0, debug_id="double", width=73.0
    )
    page = il.Page(page_number=3, pdf_paragraph=[label, double])
    docs = il.Document(page=[page], total_pages=3)
    from babeldoc.magazine.article_ir import ArticleDocumentIR

    monkeypatch.setattr(
        demo_coverage,
        "companion_visibility",
        lambda companion, held_page, config: (
            demo_coverage.COMPANION_VISIBLE,
            {"ink_fraction": 0.1},
        ),
    )
    snapshot = demo_coverage.freeze(
        docs, ArticleDocumentIR((), {}, {}, {}, {}), [(3, page)]
    )

    class Config:
        lang_in = "zh"
        lang_out = "en"
        min_text_length = 5
        page_ranges = None

        def get_working_file_path(self, name: str) -> str:
            return str(tmp_path / name)

    report = demo_coverage.finalize(Config(), snapshot)
    by_ref = {row["source_ref"]: row for row in report["items"]}
    # The Han half is the companion; the Latin half, untranslated in a zh-en
    # run, is not a hole either -- but it is not a companion, it is the page's
    # own English and stays visible under its own reason.
    assert by_ref["p3#0"]["skip_reason"] == "bilingual_companion_visible"
    assert by_ref["p3#1"]["skip_reason"] == "no_source_script"
    assert report["unowned_sources"] == []


def test_coverage_gives_no_exemption_without_visibility_proof(
    tmp_path, monkeypatch
) -> None:
    # The same twin geometry, but the companion cannot be proven visible:
    # the trait is withheld, so the Han half earns no skip reason and shows
    # up as the hole it would otherwise silently be.
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    double = _paragraph(
        "EDITOR", 455.0, 746.0, font_size=22.0, debug_id="double", width=73.0
    )
    page = il.Page(page_number=3, pdf_paragraph=[label, double])
    docs = il.Document(page=[page], total_pages=3)
    from babeldoc.magazine.article_ir import ArticleDocumentIR

    monkeypatch.setattr(
        demo_coverage,
        "companion_visibility",
        lambda companion, held_page, config: (
            demo_coverage.COMPANION_NO_INK,
            {"ink_fraction": 0.0},
        ),
    )
    snapshot = demo_coverage.freeze(
        docs, ArticleDocumentIR((), {}, {}, {}, {}), [(3, page)]
    )

    class Config:
        lang_in = "zh"
        lang_out = "en"
        min_text_length = 5
        page_ranges = None

        def get_working_file_path(self, name: str) -> str:
            return str(tmp_path / name)

    config = Config()
    config.min_text_length = 3  # below the label's four characters
    report = demo_coverage.finalize(config, snapshot)
    by_ref = {row["source_ref"]: row for row in report["items"]}
    assert by_ref["p3#0"]["skip_reason"] is None
    assert "p3#0" in [
        row["source_ref"] for row in report["unowned_sources"]
    ]


def test_plan_refuses_a_visible_twin_with_a_recorded_reason(
    tmp_path, monkeypatch
) -> None:
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    double = _paragraph(
        "EDITOR", 455.0, 746.0, font_size=22.0, debug_id="double", width=73.0
    )
    docs = _docs([label, double])
    monkeypatch.setattr(
        demo_coverage,
        "companion_visibility",
        lambda companion, page, config: (
            demo_coverage.COMPANION_VISIBLE,
            {"ink_fraction": 0.1},
        ),
    )

    class Translator:
        class translation_config:  # noqa: N801 - attribute bag, not a type
            min_text_length = 5
            input_file = str(tmp_path / "absent.pdf")

    plan = short_unit.plan(Translator(), docs, tracker=None)
    assert plan.units == []
    assert [item["reason"] for item in plan.refused] == [
        "bilingual_companion_visible"
    ]
    assert plan.refused[0]["source"] == "编者的话"
    assert plan.refused[0]["companion"]["visibility"] == "visible"


def test_plan_enqueues_a_twin_whose_companion_is_not_provably_visible(
    tmp_path, monkeypatch
) -> None:
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    double = _paragraph(
        "EDITOR", 455.0, 746.0, font_size=22.0, debug_id="double", width=73.0
    )
    docs = _docs([label, double])
    monkeypatch.setattr(
        demo_coverage,
        "companion_visibility",
        lambda companion, page, config: (
            demo_coverage.COMPANION_NO_INK,
            {"ink_fraction": 0.0},
        ),
    )
    # The unit must reach the enqueue path; a stubbed prepare marks the
    # attempt without needing the whole translator machinery.
    monkeypatch.setattr(
        short_unit, "prepare", lambda *args, **kwargs: (None, None)
    )

    class Tracker:
        def new_page(self):
            return self

        def new_paragraph(self):
            return self

    class Translator:
        class translation_config:  # noqa: N801 - attribute bag, not a type
            min_text_length = 5
            input_file = str(tmp_path / "absent.pdf")
            shared_context_cross_split_part = None

        @staticmethod
        def _build_font_maps(_page):
            return {}, {}

    plan = short_unit.plan(Translator(), docs, tracker=Tracker())
    # Not exempted: the refusal reason is the stub's no_text, never the
    # bilingual companion.
    assert [item["reason"] for item in plan.refused] == ["no_text"]


# --- companion visibility, measured off real pixels ---------------------------


def _render_fixture(tmp_path, *, cover: bool):
    import pymupdf

    pdf_path = tmp_path / ("covered.pdf" if cover else "visible.pdf")
    doc = pymupdf.open()
    pdf_page = doc.new_page(width=595.0, height=842.0)
    # Top-down insertion point y=100 -> ink around IL y 742..762.
    pdf_page.insert_text((60.0, 100.0), "EDITOR", fontsize=22)
    if cover:
        shape = pdf_page.new_shape()
        shape.draw_rect(pymupdf.Rect(50.0, 70.0, 200.0, 110.0))
        shape.finish(fill=(1, 1, 1), color=None)
        shape.commit()
        # A later text operation in the same crop contributes final-page ink,
        # but cannot prove that the earlier EDITOR operation survived.
        pdf_page.insert_text((60.0, 100.0), "VISIBLE", fontsize=22)
    doc.save(str(pdf_path))
    doc.close()
    companion = _paragraph(
        "EDITOR", 58.0, 738.0, font_size=22.0, debug_id="companion", width=100.0
    )
    page = il.Page(
        page_number=0,
        pdf_paragraph=[companion],
        cropbox=il.Cropbox(box=il.Box(0.0, 0.0, 595.0, 842.0)),
    )

    class Config:
        input_file = str(pdf_path)
        page_ranges = None

    return companion, page, Config()


def test_a_companion_with_real_ink_is_visible(tmp_path) -> None:
    companion, page, config = _render_fixture(tmp_path, cover=False)
    verdict, evidence = demo_coverage.companion_visibility(
        companion, page, config
    )
    assert verdict == demo_coverage.COMPANION_VISIBLE
    assert evidence["ink_fraction"] > 0.0


def test_a_companion_hidden_under_opaque_fill_is_not_visible(tmp_path) -> None:
    companion, page, config = _render_fixture(tmp_path, cover=True)
    verdict, evidence = demo_coverage.companion_visibility(
        companion, page, config
    )
    assert verdict == demo_coverage.COMPANION_NO_INK
    assert evidence["trace_seqno"] == 0
    assert evidence["occluder_seqno"] == 1
    assert evidence["occlusion_coverage"] == 1.0


def test_a_companion_outside_the_page_body_is_not_visible(tmp_path) -> None:
    companion, page, config = _render_fixture(tmp_path, cover=False)
    page.cropbox = il.Cropbox(box=il.Box(0.0, 0.0, 595.0, 700.0))
    verdict, _evidence = demo_coverage.companion_visibility(
        companion, page, config
    )
    assert verdict == demo_coverage.COMPANION_OUTSIDE_PAGE_BODY


def test_an_unrenderable_companion_is_not_visible(tmp_path) -> None:
    companion, page, _config = _render_fixture(tmp_path, cover=False)

    class Absent:
        input_file = str(tmp_path / "absent.pdf")
        page_ranges = None

    verdict, _evidence = demo_coverage.companion_visibility(
        companion, page, Absent()
    )
    assert verdict == demo_coverage.COMPANION_UNRENDERABLE
