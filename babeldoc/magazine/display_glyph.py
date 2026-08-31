"""Display glyphs: a short oversized run inside running text is pinned, not set.

What is broken here
-------------------

A magazine draws a feature number into the reading order of its contents
blurb: AramcoWorld p3 holds a 65pt ``8`` inside the same paragraph as a 14pt
title and an 8pt standfirst. The translator receives the whole unit, the
typesetter re-sets it, and the number comes back shrunk and moved -- 52pt at
another x, standing on the byline. Nothing about the number wanted any of
that: it is not prose, it translates to itself, and its position *is* its
meaning.

So a run like that is taken out of the flow before anything downstream sees
it: split into a paragraph of its own, pinned at its source coordinates and
size, labelled ``display_glyph``, and registered as a fixed asset class so
the clearance capture and the overlap detector cover it exactly as they cover
an ornament path (``fixed_assets.display_glyph_paragraphs`` is the one
enumerator both read).

What a display glyph is
-----------------------

A maximal contiguous run of non-space characters inside one paragraph, no
longer than ``display_glyph_max_chars``, set at or above
``min_first_run_size_ratio`` (read from configs/drop_cap.json -- the single
source of that number, as span_merge already reads it) times the paragraph's
own median character size. The ratio against the paragraph's *own* median is
what keeps every all-large paragraph -- a title, a headline -- out: its
median is its own size and the ratio is one.

The jurisdiction boundary with the drop cap lane is positional and decided
here, first and deterministically: a qualifying run that begins at the
paragraph's first visible character is an opening initial's shape and is left
untouched for the drop cap lane to judge, whether or not that lane later
takes it. Everything after the first character is this pass's territory.
This pass runs before the drop cap candidate signal, so the order is fixed
by the pipeline rather than by racing, and every refusal is recorded.

And a pinned run must be translation-invariant: digits and marks only, no
letter of any script. Pinning trades re-setting for fidelity, and that trade
is only free where the run would translate to itself -- a ``8`` is an ``8``
in any language, while a two-character topic word pinned over a section
label (the first cold sample this pass walked) is a translation silently
not made. Lettered runs go back to the flow, recorded as refused.
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.paragraph_finder import generate_base58_id
from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.drop_cap import load_drop_cap_config
from babeldoc.magazine.line_split import character_union
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("display_glyph.json")
REPORT_NAME = "display_glyph.report.json"
SWITCH = "magazine_display_glyph"

# Why a qualifying run was not pinned. Closed, and every refusal is recorded.
REFUSED_OPENING_POSITION = "opening_position_drop_cap_lane"
REFUSED_LETTERED_RUN = "lettered_run_translates"


def load_display_glyph_config() -> dict:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    flat = {key: value for key, value in raw.items() if key != "switch"}
    return dict(validate_bounded_config(flat, CONFIG_PATH))


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def _char_size(character) -> float | None:
    style = getattr(character, "pdf_style", None)
    size = getattr(style, "font_size", None) if style else None
    return float(size) if size else None


def _median_size(characters) -> float | None:
    sizes = [
        size
        for character in characters
        if (character.char_unicode or "").strip()
        and (size := _char_size(character)) is not None
    ]
    return statistics.median(sizes) if sizes else None


def _runs(characters, ratio: float, median: float):
    """Maximal contiguous oversized non-space runs, as (start, end) index pairs."""
    found: list[tuple[int, int]] = []
    start = None
    for index, character in enumerate(characters):
        glyph = character.char_unicode or ""
        size = _char_size(character)
        oversized = (
            bool(glyph.strip()) and size is not None and size >= ratio * median
        )
        if oversized and start is None:
            start = index
        elif not oversized and start is not None:
            found.append((start, index))
            start = None
    if start is not None:
        found.append((start, len(characters)))
    return found


def _rebuild_without(paragraph, removed_ids: set[int]) -> None:
    """Take the pinned characters out of the host, composition by composition.

    The host's composition structure is kept -- only the pinned characters
    leave it -- so the style runs the translator reads are the ones the
    styling stage built, minus the glyph.
    """
    kept_compositions = []
    for composition in paragraph.pdf_paragraph_composition or ():
        holder = None
        for name in (
            "pdf_line",
            "pdf_same_style_characters",
            "pdf_formula",
        ):
            candidate = getattr(composition, name, None)
            if candidate is not None:
                holder = candidate
                break
        if holder is None:
            single = getattr(composition, "pdf_character", None)
            if single is not None and id(single) in removed_ids:
                continue
            kept_compositions.append(composition)
            continue
        holder.pdf_character = [
            character
            for character in holder.pdf_character or ()
            if id(character) not in removed_ids
        ]
        if holder.pdf_character:
            box = character_union(holder.pdf_character)
            if box is not None:
                holder.box = box
            kept_compositions.append(composition)
    paragraph.pdf_paragraph_composition = kept_compositions
    remaining = paragraph_characters(paragraph)
    paragraph.unicode = get_char_unicode_string(remaining)
    box = character_union(remaining)
    if box is not None:
        paragraph.box = box


def _pinned_paragraph(characters, host) -> il_version_1.PdfParagraph:
    box = character_union(characters)
    style = characters[0].pdf_style
    return il_version_1.PdfParagraph(
        unicode=get_char_unicode_string(characters),
        box=box,
        pdf_style=style,
        layout_label=fixed_assets.DISPLAY_GLYPH_LABEL,
        debug_id=generate_base58_id(),
        vertical=False,
        xobj_id=getattr(host, "xobj_id", None),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    box=box,
                    pdf_style=style,
                    pdf_character=list(characters),
                )
            )
        ],
    )


def apply(translation_config, docs) -> dict | None:
    """Pin every display glyph of one document. None where the switch is down."""
    if not enabled(translation_config):
        return None
    parameters = load_display_glyph_config()
    max_chars = int(parameters["display_glyph_max_chars"])
    ratio = load_drop_cap_config().min_first_run_size_ratio

    pinned: list[dict] = []
    refused: list[dict] = []
    for position, page in enumerate(docs.page or ()):
        page_number = position + 1
        additions: list[tuple[int, il_version_1.PdfParagraph]] = []
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            characters = paragraph_characters(paragraph)
            if not characters:
                continue
            median = _median_size(characters)
            if not median:
                continue
            first_visible = next(
                (
                    idx
                    for idx, character in enumerate(characters)
                    if (character.char_unicode or "").strip()
                ),
                None,
            )
            for start, end in _runs(characters, ratio, median):
                run = characters[start:end]
                text = get_char_unicode_string(run)
                run_size = _char_size(run[0])
                record = {
                    "page": page_number,
                    "host_debug_id": getattr(paragraph, "debug_id", None),
                    "text": text,
                    "characters": end - start,
                    "font_size": run_size,
                    "median_size": median,
                    "size_ratio": (
                        round(run_size / median, 4) if run_size else None
                    ),
                }
                if end - start > max_chars:
                    continue
                if start == first_visible:
                    refused.append(
                        {**record, "reason": REFUSED_OPENING_POSITION}
                    )
                    continue
                # Pinning is only harmless where the run translates to
                # itself. A numeral or a mark does; a word does not -- the
                # first cold walk of this pass pinned a 30pt two-character
                # topic word over a section label, which silently exempted a
                # real translation from happening. Letters of any script
                # send the run back to the flow.
                if any(
                    glyph.isalpha()
                    for character in run
                    for glyph in (character.char_unicode or "").strip()
                ):
                    refused.append({**record, "reason": REFUSED_LETTERED_RUN})
                    continue
                glyph = _pinned_paragraph(run, paragraph)
                _rebuild_without(paragraph, {id(c) for c in run})
                additions.append((index, glyph))
                box = glyph.box
                record["debug_id"] = glyph.debug_id
                record["box"] = (
                    None
                    if box is None
                    else [
                        float(box.x),
                        float(box.y),
                        float(box.x2),
                        float(box.y2),
                    ]
                )
                pinned.append(record)
        # Inserted after their hosts, back to front, so earlier indices hold.
        for index, glyph in reversed(additions):
            page.pdf_paragraph.insert(index + 1, glyph)

    record = {
        "switch": SWITCH,
        "max_chars": max_chars,
        "size_ratio_source": "drop_cap.json:min_first_run_size_ratio",
        "size_ratio": ratio,
        "jurisdiction": (
            "display glyph runs first by pipeline order; a qualifying run at "
            "the paragraph's first visible character is left to the drop cap "
            "lane"
        ),
        "counts": {"pinned": len(pinned), "refused": len(refused)},
        "pinned": pinned,
        "refused": refused,
    }
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.debug("display glyph: %d pinned, %d refused", len(pinned), len(refused))
    return record
