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


def test_coverage_names_the_source_side_of_a_twin(tmp_path) -> None:
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    double = _paragraph(
        "EDITOR", 455.0, 746.0, font_size=22.0, debug_id="double", width=73.0
    )
    page = il.Page(page_number=3, pdf_paragraph=[label, double])
    docs = il.Document(page=[page], total_pages=3)
    from babeldoc.magazine.article_ir import ArticleDocumentIR

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
    assert by_ref["p3#0"]["skip_reason"] == "bilingual_companion"
    assert by_ref["p3#1"]["skip_reason"] == "no_source_script"
    assert report["unowned_sources"] == []


def test_plan_refuses_a_twin_with_a_recorded_reason(tmp_path) -> None:
    label = _paragraph("编者的话", 451.0, 745.0, font_size=18.0, debug_id="label")
    double = _paragraph(
        "EDITOR", 455.0, 746.0, font_size=22.0, debug_id="double", width=73.0
    )
    docs = _docs([label, double])

    class Translator:
        class translation_config:  # noqa: N801 - attribute bag, not a type
            min_text_length = 5
            input_file = str(tmp_path / "absent.pdf")

    plan = short_unit.plan(Translator(), docs, tracker=None)
    assert plan.units == []
    assert [item["reason"] for item in plan.refused] == ["bilingual_companion"]
    assert plan.refused[0]["source"] == "编者的话"
