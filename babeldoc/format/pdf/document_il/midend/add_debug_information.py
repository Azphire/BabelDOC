"""Build final diagnostics from semantic geometry without mutating the IL."""

from __future__ import annotations

import math

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.translation_config import TranslationConfig
from babeldoc.magazine.debug_overlay import OverlayCategory
from babeldoc.magazine.debug_overlay import OverlayProducer
from babeldoc.magazine.debug_overlay import OverlayStyle
from babeldoc.magazine.debug_overlay import ledger_for
from babeldoc.magazine.debug_overlay import page_bounds
from babeldoc.magazine.debug_overlay import physical_page_number


class AddDebugInformation:
    stage_name = "Build Debug Overlay Ledger"

    def __init__(self, translation_config: TranslationConfig):
        self.translation_config = translation_config

    def process(self, docs: il_version_1.Document):
        ledger = ledger_for(self.translation_config)
        if self.translation_config.debug:
            for page in docs.page:
                self.process_page(page)
        return ledger

    def _box(
        self,
        page,
        box,
        *,
        category: OverlayCategory,
        style: OverlayStyle,
        related_ref: str | None,
        width: float = 0.4,
    ) -> None:
        box = self._renderable_box(page, box)
        if box is None:
            return
        ledger_for(self.translation_config).add_box(
            source_page_number=physical_page_number(page),
            producer=OverlayProducer.ADD_DEBUG_INFORMATION,
            category=category,
            page_bounds=page_bounds(page),
            box=box,
            text=str(width),
            style=style,
            related_semantic_ref=related_ref,
        )

    def _label(
        self,
        page,
        box,
        text: str,
        *,
        category: OverlayCategory,
        style: OverlayStyle,
        related_ref: str | None,
    ) -> None:
        box = self._renderable_box(page, box)
        if box is None:
            return
        ledger_for(self.translation_config).add_label(
            source_page_number=physical_page_number(page),
            producer=OverlayProducer.ADD_DEBUG_INFORMATION,
            category=category,
            page_bounds=page_bounds(page),
            box=box,
            text=text,
            style=style,
            related_semantic_ref=related_ref,
        )

    @staticmethod
    def _renderable_box(page, value):
        raw = tuple(float(getattr(value, name)) for name in ("x", "y", "x2", "y2"))
        if not all(math.isfinite(item) for item in raw):
            return None
        if raw[0] > raw[2] or raw[1] > raw[3]:
            return None
        bounds = tuple(
            float(getattr(page_bounds(page), name)) for name in ("x", "y", "x2", "y2")
        )
        return (
            max(bounds[0], min(raw[0], bounds[2])),
            max(bounds[1], min(raw[1], bounds[3])),
            max(bounds[0], min(raw[2], bounds[2])),
            max(bounds[1], min(raw[3], bounds[3])),
        )

    def process_page(self, page: il_version_1.Page):
        source_page = physical_page_number(page)
        bounds = page_bounds(page)
        self._label(
            page,
            bounds,
            f"pagenumber: {source_page}",
            category=OverlayCategory.PAGE,
            style=OverlayStyle.BLUE,
            related_ref=None,
        )
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph):
            if paragraph.box is None:
                continue
            reference = f"p{source_page}#{paragraph_index}"
            self._box(
                page,
                paragraph.box,
                category=OverlayCategory.PARAGRAPH,
                style=OverlayStyle.BLUE,
                related_ref=reference,
            )
            self._label(
                page,
                paragraph.box,
                f"paragraph[{reference}]-[{paragraph.layout_label}]",
                category=OverlayCategory.PARAGRAPH,
                style=OverlayStyle.BLUE,
                related_ref=reference,
            )
            for composition in paragraph.pdf_paragraph_composition:
                formula = composition.pdf_formula
                if formula is None or formula.box is None:
                    continue
                self._box(
                    page,
                    formula.box,
                    category=OverlayCategory.FORMULA,
                    style=OverlayStyle.ORANGE,
                    related_ref=reference,
                )
                self._label(
                    page,
                    formula.box,
                    "formula",
                    category=OverlayCategory.FORMULA,
                    style=OverlayStyle.ORANGE,
                    related_ref=reference,
                )
                for char in formula.pdf_character:
                    visual = getattr(getattr(char, "visual_bbox", None), "box", None)
                    if visual is not None:
                        self._box(
                            page,
                            visual,
                            category=OverlayCategory.CHARACTER_BOX,
                            style=OverlayStyle.TEAL,
                            related_ref=reference,
                            width=0.2,
                        )
        for index, xobj in enumerate(page.pdf_xobject):
            if xobj.box is not None:
                self._box(
                    page,
                    xobj.box,
                    category=OverlayCategory.XOBJECT,
                    style=OverlayStyle.YELLOW,
                    related_ref=f"p{source_page}:pdf_xobject#{index}",
                )
        for index, form in enumerate(page.pdf_form):
            if form.box is None:
                continue
            reference = f"p{source_page}:pdf_form#{index}"
            self._box(
                page,
                form.box,
                category=OverlayCategory.FORM,
                style=OverlayStyle.PINK,
                related_ref=reference,
            )
            subtype = form.pdf_form_subtype
            text = "Form"
            if subtype is not None and subtype.pdf_xobj_form:
                text += f"[{subtype.pdf_xobj_form.do_args}]"
            elif subtype is not None and subtype.pdf_inline_form:
                text += "[inline]"
            self._label(
                page,
                form.box,
                text,
                category=OverlayCategory.FORM,
                style=OverlayStyle.PINK,
                related_ref=reference,
            )
