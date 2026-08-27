import logging
from pathlib import Path

import cv2
import numpy as np
from pymupdf import Document

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.utils.mupdf_helper import get_no_rotation_img
from babeldoc.format.pdf.translation_config import TranslationConfig
from babeldoc.magazine.debug_overlay import OverlayCategory
from babeldoc.magazine.debug_overlay import OverlayProducer
from babeldoc.magazine.debug_overlay import OverlayStyle
from babeldoc.magazine.debug_overlay import ledger_for
from babeldoc.magazine.debug_overlay import page_bounds
from babeldoc.magazine.debug_overlay import physical_page_number

logger = logging.getLogger(__name__)


class TableParser:
    stage_name = "Parse Table"

    def __init__(self, translation_config: TranslationConfig):
        self.translation_config = translation_config
        self.model = translation_config.table_model

    def _save_debug_image(self, image: np.ndarray, layouts, page_number: int):
        """Save debug image with drawn boxes if debug mode is enabled."""
        if not self.translation_config.debug:
            return

        if not isinstance(layouts, list):
            layouts = [layouts]
        debug_dir = Path(
            self.translation_config.get_working_file_path("table-ocr-box-image")
        )
        debug_dir.mkdir(parents=True, exist_ok=True)

        # Draw boxes on the image
        debug_image = image.copy()
        for layout in layouts:
            for box in layout.boxes:
                x0, y0, x1, y1 = box.xyxy
                cv2.rectangle(
                    debug_image,
                    (int(x0), int(y0)),
                    (int(x1), int(y1)),
                    (0, 255, 0),
                    2,
                )
                # Add text label
                cv2.putText(
                    debug_image,
                    layout.names[box.cls],
                    (int(x0), int(y0) - 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                )

        # Save the image
        output_path = debug_dir / f"{page_number}.jpg"
        cv2.imwrite(str(output_path), debug_image)

    def _save_debug_box_to_page(self, page: il_version_1.Page):
        """Record table diagnostics without mutating semantic page elements."""
        if not self.translation_config.debug:
            return
        ledger = ledger_for(self.translation_config)
        bounds = page_bounds(page)
        source_page = physical_page_number(page)
        for layout in page.page_layout:
            related_ref = f"p{source_page}:layout#{layout.id}"
            ledger.add_box(
                source_page_number=source_page,
                producer=OverlayProducer.TABLE_PARSER,
                category=OverlayCategory.LAYOUT,
                page_bounds=bounds,
                box=layout.box,
                style=OverlayStyle.GREEN,
                related_semantic_ref=related_ref,
            )
            ledger.add_label(
                source_page_number=source_page,
                producer=OverlayProducer.TABLE_PARSER,
                category=OverlayCategory.LAYOUT,
                page_bounds=bounds,
                box=layout.box,
                text=layout.class_name,
                style=OverlayStyle.GREEN,
                related_semantic_ref=related_ref,
            )

    def process(self, docs: il_version_1.Document, mupdf_doc: Document):
        """Generate layouts for all pages that need to be translated."""
        # Get pages that need to be translated
        have_table_pages = {}
        for page in docs.page:
            for layout in page.page_layout:
                if layout.class_name == "table":
                    have_table_pages[page.page_number] = page
        with self.translation_config.progress_monitor.stage_start(
            self.stage_name,
            len(have_table_pages),
        ) as progress:
            # Process predictions for each page
            for page, layouts in self.model.handle_document(
                have_table_pages.values(),
                mupdf_doc,
                self.translation_config,
                self._save_debug_image,
            ):
                page_layouts = []
                for layout in layouts.boxes:
                    # Convert coordinate system from picture to il
                    # system to the il coordinate system
                    x0, y0, x1, y1 = layout.xyxy
                    # pix = mupdf_doc[page.page_number].get_pixmap()
                    pix = get_no_rotation_img(mupdf_doc[page.page_number])
                    h, w = pix.height, pix.width
                    x0, y0, x1, y1 = (
                        np.clip(int(x0 - 1), 0, w - 1),
                        np.clip(int(h - y1 - 1), 0, h - 1),
                        np.clip(int(x1 + 1), 0, w - 1),
                        np.clip(int(h - y0 + 1), 0, h - 1),
                    )
                    page_layout = il_version_1.PageLayout(
                        id=len(page_layouts) + 1,
                        box=il_version_1.Box(
                            x0.item(),
                            y0.item(),
                            x1.item(),
                            y1.item(),
                        ),
                        conf=layout.conf.item(),
                        class_name=layouts.names[layout.cls],
                    )
                    page_layouts.append(page_layout)

                page.page_layout.extend(page_layouts)
                self._save_debug_box_to_page(page)
                progress.advance(1)

        return docs
