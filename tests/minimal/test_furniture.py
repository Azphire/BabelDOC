"""The furniture pass: one voice for repeat furniture, hands off production marks.

CERN Courier's evidence, generalized: the folio line repeats letter for letter
on every page and came back in four voices; the printing slugs are drawn twice
at one text matrix (stroke-only, then under a clip) and came back half
translated and interleaved.  These tests pin the two shape rules -- repetition
in the edge band, glyph-on-glyph duplication -- and the handoffs: a member
takes its leader's translation, a production mark is refused by the stitch
and left byte for byte as the source drew it.
"""

from __future__ import annotations

import json
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.magazine import fragment_stitch
from babeldoc.magazine import furniture

from tests.minimal.test_drop_cap_keep_flatten import pdf_style

ROOT = Path(__file__).resolve().parents[2]

PAGE_W, PAGE_H = 600.0, 800.0
BODY = 10.0


class StubConfig:
    magazine_furniture = True

    def __init__(self, working_dir: Path):
        self.working_dir = working_dir

    def get_working_file_path(self, name: str) -> str:
        return str(self.working_dir / name)


def characters(text: str, x: float, y: float, style, doubled: bool = False):
    chars = []
    copies = 2 if doubled else 1
    for _copy in range(copies):
        cursor = x
        for glyph in text:
            width = BODY * 0.5
            chars.append(
                il.PdfCharacter(
                    char_unicode=glyph,
                    box=il.Box(cursor, y, cursor + width, y + BODY),
                    pdf_style=style,
                    advance=width,
                    xobj_id=0,
                )
            )
            cursor += width
    return chars


def paragraph(text: str, x: float, y: float, *, debug_id: str, doubled=False):
    style = pdf_style(font_size=BODY)
    chars = characters(text, x, y, style, doubled=doubled)
    line = il.PdfLine(box=il.Box(x, y, x + len(text) * BODY, y + BODY), pdf_character=chars)
    return il.PdfParagraph(
        unicode=text * (2 if doubled else 1),
        box=il.Box(x, y, x + len(text) * BODY * 0.5, y + BODY),
        pdf_style=style,
        pdf_paragraph_composition=[il.PdfParagraphComposition(pdf_line=line)],
        debug_id=debug_id,
        layout_label="plain text",
    )


def page_of(number: int, paragraphs):
    return il.Page(
        page_number=number,
        pdf_paragraph=list(paragraphs),
        mediabox=il.Mediabox(box=il.Box(0, 0, PAGE_W, PAGE_H)),
        cropbox=il.Cropbox(box=il.Box(0, 0, PAGE_W, PAGE_H)),
    )


def docs_of(*pages):
    return il.Document(page=list(pages))


def test_repeat_furniture_translates_once_and_reuses(tmp_path):
    """One folio string on three pages: one leader, two members, one voice."""
    config = StubConfig(tmp_path)
    pages = [
        page_of(n, [paragraph("The Folio Line", 200.0, 20.0, debug_id=f"folio-{n}")])
        for n in range(3)
    ]
    docs = docs_of(*pages)
    built = furniture.plan(config, docs)
    assert built is not None
    assert len(built.leaders) == 1
    assert len(built.reuse_members) == 2
    leader = docs.page[0].pdf_paragraph[0]
    members = [docs.page[1].pdf_paragraph[0], docs.page[2].pdf_paragraph[0]]
    assert not built.withholds(leader.debug_id)
    assert all(built.withholds(member.debug_id) for member in members)

    # The leader translates; unify copies its text onto both members.
    run = il.PdfSameStyleUnicodeCharacters()
    run.unicode = "页脚行"
    run.pdf_style = leader.pdf_style
    leader.unicode = "页脚行"
    leader.pdf_paragraph_composition = [
        il.PdfParagraphComposition(pdf_same_style_unicode_characters=run)
    ]
    furniture.unify(config, docs, built)
    for member in members:
        assert member.unicode == "页脚行"
        holder = member.pdf_paragraph_composition[0].pdf_same_style_unicode_characters
        assert holder.unicode == "页脚行"
        assert holder.pdf_style is member.pdf_style
    report = json.loads((tmp_path / furniture.REPORT_NAME).read_text("utf-8"))
    assert [row["outcome"] for row in report["unified"]] == ["reused", "reused"]


def test_an_occurrence_off_the_band_disqualifies_the_string(tmp_path):
    """A string that also lives mid-page may be prose; nothing groups."""
    config = StubConfig(tmp_path)
    docs = docs_of(
        page_of(0, [paragraph("Repeated words", 200.0, 20.0, debug_id="a")]),
        page_of(1, [paragraph("Repeated words", 200.0, 400.0, debug_id="b")]),
        page_of(2, [paragraph("Repeated words", 200.0, 20.0, debug_id="c")]),
    )
    built = furniture.plan(config, docs)
    assert built.leaders == {} and built.reuse_members == {}


def test_untranslated_leader_leaves_every_copy_as_source(tmp_path):
    config = StubConfig(tmp_path)
    pages = [
        page_of(n, [paragraph("cerncourier.com", 200.0, 20.0, debug_id=f"dom-{n}")])
        for n in range(2)
    ]
    docs = docs_of(*pages)
    built = furniture.plan(config, docs)
    before = docs.page[1].pdf_paragraph[0].unicode
    furniture.unify(config, docs, built)
    assert docs.page[1].pdf_paragraph[0].unicode == before
    report = json.loads((tmp_path / furniture.REPORT_NAME).read_text("utf-8"))
    assert [row["outcome"] for row in report["unified"]] == ["leader_kept_source"]


def test_doubled_slug_is_a_production_mark_and_kept_byte_for_byte(tmp_path):
    """The CERN shape: slug and date drawn twice at one position, in the band."""
    config = StubConfig(tmp_path)
    slug = paragraph("SLUG_v2 03/07 11:48", 10.0, 8.0, debug_id="slug", doubled=True)
    prose = paragraph("Ordinary sentence.", 350.0, 8.0, debug_id="prose")
    docs = docs_of(page_of(0, [slug, prose]))
    before = json.dumps(
        [c.char_unicode for c in slug.pdf_paragraph_composition[0].pdf_line.pdf_character]
    )
    built = furniture.plan(config, docs)
    assert built.withholds("slug")
    assert not built.withholds("prose")
    # Byte-for-byte: the plan marks, it never rewrites.
    after = json.dumps(
        [c.char_unicode for c in slug.pdf_paragraph_composition[0].pdf_line.pdf_character]
    )
    assert after == before


def test_twin_paragraphs_and_cluster_contagion(tmp_path):
    """A doubled draw split into two paragraphs, plus a fragment lying on it.

    CERN's escaped shapes: the styles pass shredded the two coincident slug
    copies into separate paragraphs and interleaved fragments.  Identical
    twins lying on each other seed the cluster; a differing fragment on top
    of a seed catches by contagion; prose elsewhere in the band stays free.
    """
    config = StubConfig(tmp_path)
    twin_a = paragraph("SLUG_v2.indd 1", 10.0, 8.0, debug_id="twin-a")
    twin_b = paragraph("SLUG_v2.indd 1", 10.2, 8.1, debug_id="twin-b")
    fragment = paragraph("SLG_v .indd", 12.0, 8.0, debug_id="frag")
    aloof = paragraph("An ordinary caption.", 400.0, 8.0, debug_id="aloof")
    docs = docs_of(page_of(0, [twin_a, twin_b, fragment, aloof]))
    built = furniture.plan(config, docs)
    assert built.withholds("twin-a") and built.withholds("twin-b")
    assert built.withholds("frag")
    assert not built.withholds("aloof")
    report = json.loads((tmp_path / furniture.REPORT_NAME).read_text("utf-8"))
    rules = {row["debug_id"]: row["rule"] for row in report["production_marks"]}
    assert rules["twin-a"] == rules["twin-b"] == "twin_paragraphs"
    assert rules["frag"] == "cluster_contagion"


def test_stitch_refuses_a_production_mark():
    """Regression for the slug+date interleave: nothing may stitch into it."""
    slug = paragraph("SLUG_v2 03/07", 10.0, 8.0, debug_id="slug", doubled=True)
    date = paragraph("03/07/2026 11:48", 90.0, 8.0, debug_id="date")
    page = page_of(0, [slug, date])
    stitch_config = fragment_stitch.load_stitch_config()
    records, _found = fragment_stitch.process_page(
        page, 1, stitch_config, withheld=frozenset({"slug"})
    )
    assert records == []
    assert page.pdf_paragraph[0].unicode.startswith("SLUG_v2")
