"""Putting a translation into a paragraph the translator never handled.

The round trip the translator writes a paragraph back through is not available
here, and not because of where the hook sits. An orphan line fails it three
times over -- ``pre_translate_paragraph`` returns nothing for a paragraph marked
vertical, ``get_translate_input`` returns nothing for one whose whole
composition is placeholders, and the writer sets the rebuilt run's style from
``paragraph.pdf_style``, which an orphan does not have. The third is the one
that would be silent: a run whose style is None is dropped by
``create_typesetting_units``, so the paragraph would come back empty rather than
untranslated.

So the write-back is done here, and it is the smallest thing that can work. The
source text is the characters the page already renders. The translated text
replaces the composition with a single same-style run, set in a style taken
from the paragraph's own characters where the paragraph itself carries none.
The box, the orientation flag and every other field are left as they are.
Laying the result out is then the existing typesetting stage's job, called one
paragraph at a time.

One paragraph at a time rather than one page: ``render_page`` opens by nudging
the boxes of paragraphs that overlap each other, which would move paragraphs
this repair is not allowed to touch. ``render_paragraph`` touches the paragraph
it is given and the page's curve and form lists, and a rebuilt run contributes
no curves and no forms, so nothing else on the page moves.

Vertical orphans go through the same path. Typesetting has no vertical mode --
a unicode unit is always emitted horizontal -- and the strip an orphan credit
stands in is about one character wide, so the laid out result is one character
per line down the strip. For a target language set in Han script that is the
conventional vertical setting; for one that is not, the action's applicability
is what decides whether the paragraph is offered here at all.
"""

from __future__ import annotations

import logging

from babeldoc.format.pdf.document_il import il_version_1

logger = logging.getLogger(__name__)

# Composition members that carry a list of characters, in the order a
# paragraph's style is most reliably read from.
_CHARACTER_HOLDERS = ("pdf_same_style_characters", "pdf_line", "pdf_formula")


def paragraph_style(paragraph) -> il_version_1.PdfStyle | None:
    """The style the rebuilt run is set in.

    The paragraph's own style where it has one. An orphan does not, so the
    style is taken from the first character the paragraph is laid out as, which
    is the size and font the line was actually printed in.
    """
    if paragraph.pdf_style is not None:
        return paragraph.pdf_style
    for composition in paragraph.pdf_paragraph_composition or ():
        if composition.pdf_character is not None:
            return composition.pdf_character.pdf_style
        for name in _CHARACTER_HOLDERS:
            group = getattr(composition, name, None)
            if group is not None and group.pdf_character:
                return group.pdf_character[0].pdf_style
    return None


def can_write_back(paragraph) -> bool:
    """Whether a translation could be written into this paragraph at all."""
    style = paragraph_style(paragraph)
    return (
        paragraph.box is not None
        and style is not None
        and style.font_id is not None
        and style.font_size is not None
    )


def rebuild(paragraph, text: str) -> None:
    """Replace the paragraph's composition with one run carrying ``text``."""
    style = paragraph_style(paragraph)
    if style is None:
        raise ValueError("paragraph carries no style to set a translation in")
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    unicode=text, pdf_style=style
                )
            )
        )
    ]
    paragraph.unicode = text


def page_font_map(page, font_mapper) -> dict:
    """The font lookup ``render_paragraph`` expects, built as the stage builds it.

    Page fonts, then the mapped fonts the target language is set in, then one
    sub-map per xobject so that a paragraph inside a form resolves its font ids
    against that form's resources. This mirrors the opening of ``render_page``,
    which is the part of it that reads the page rather than moving it.
    """
    fonts: dict = {font.font_id: font for font in page.pdf_font or () if font.font_id}
    page_fonts = dict(fonts)
    for font_id, font in font_mapper.fontid2font.items():
        fonts[font_id] = font
    for xobject in page.pdf_xobject or ():
        if xobject.xobj_id is None:
            continue
        scoped = page_fonts.copy()
        for font in xobject.pdf_font or ():
            if font.font_id:
                scoped[font.font_id] = font
        fonts[xobject.xobj_id] = scoped
    return fonts


def retypeset(typesetting, paragraph, page) -> bool:
    """Lay one paragraph out again in place. False where nothing came out.

    A rebuilt run that cannot be fitted into the paragraph's box at any scale
    leaves the composition empty, which would erase the line rather than repair
    it, and a font id that resolves against nothing raises. Both are answered
    the same way: this paragraph is not repairable and the caller puts it back.
    A repair loop that cannot repair a line is working correctly; one that
    stops a translation from being written is not.
    """
    fonts = page_font_map(page, typesetting.font_mapper)
    try:
        typesetting.render_paragraph(paragraph, page, fonts)
    except Exception:  # noqa: BLE001 - any failure means this line stands as it was
        logger.warning(
            "react: laying out %s again failed; it is left as it was",
            paragraph.debug_id,
            exc_info=True,
        )
        return False
    return bool(paragraph.pdf_paragraph_composition)
