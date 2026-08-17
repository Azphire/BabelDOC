"""B9.2 acceptance: what the arms say, in pixels and in the record.

Reads the runs the driver beside this file produced and answers the questions
the batch was accepted on, each of them from what the pipeline recorded and
from what the reader is shown.

How a difference is attributed
------------------------------

Two arms differing is not evidence by itself, because this pipeline is not bit
reproducible: a request the cache did not keep is asked again and the model
answers it differently, and everything downstream of that answer moves. So
three arms were run, two of them identically configured. The identical pair is
the floor -- whatever it differs by is what a run differs from itself by -- and
the contrast is read against it. A page that differs between the switch's two
arms and does not differ between the identical pair is a page the switch
changed. A page that differs in both is a page nothing here can attribute, and
it is listed as that rather than counted either way.

The document handed to the layout is compared first, on the bytes of the
translated checkpoint and of the typeset checkpoint, the second of which is
written before the heading pass runs. Two attributes are taken out of that
comparison and named where it is made: the debug id and the chain id are minted
per run rather than derived from the document.

The cases
---------

a. The doubled headline. One rendering rather than two: the deduplication in
   the sidecar, and the ink the page carries in the headline's own band, which
   halves. The page is rastered from both arms and from the F1 run the defect
   was reported from.
b. The cover headings. Both were wrapped and neither is now. One of them also
   draws past the top edge of the page, which is a different mechanism and is
   not closed here; it is measured and recorded as an open defect.
c. Every heading of the ruled sample on one line, or raised, with nothing
   unaccounted for. The ruling's revision added eight person names and they are
   held to having been carried into the run's glossary, with the requests each
   one fired on.
d. Every heading of the whole corpus that reached the floor, with the scale it
   asked for and what was done with it.
e. Whether a doubled heading reaches M3. LTCR is measured over the translated
   checkpoint, which is upstream of this pass, so if a doubled heading were
   inside the measurement the defect this batch fixes would have been inflating
   a published number. The check is a perturbation: the metric is measured as
   the run leaves it and again with every doubled heading collapsed.

Usage:
    python analyze_b9_2.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
import render_diff  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.metrics import ltcr  # noqa: E402

BATCH_DIR = ROOT / "examples" / "output" / "b9_2"
RASTER_DIR = BATCH_DIR / "raster"
FIXTURE_DIR = BATCH_DIR / "fixtures"

# The run the defect was reported from, for the third raster of case a.
F1_DIR = ROOT / "examples" / "output" / "final"

# The arm the switch is up in, the arm it is down in, and the second run of the
# second one, which is what says how much a run differs from itself.
SUBJECT_ARM = "on"
BASE_ARM = "off"
CONTROL_ARM = "control"
ARMS = (BASE_ARM, CONTROL_ARM, SUBJECT_ARM)

TRANSLATED_STAGE = "il_translated"
TYPESET_STAGE = "typesetting"

# The subjects of the first three cases, each named by the sample and the file
# page it is on. They are the defects F1 was reviewed to and are quoted here as
# the evidence they are, not as anything the pipeline branches on.
GHOST_SAMPLE = "AramcoWorld-en-v2"
GHOST_PAGE = 5
COVER_SAMPLE = "CERNCourier-en"
COVER_PAGE = 1
RULED_SAMPLE = "Courier-en"

# The revision the ruling's eight person names were added by, read rather than
# copied: what case c checks is the difference this commit made.
RULING_REVISION = "ce57280"

# Device pixels per point: enough for a whole page to be read at a glance, and
# enough for a crop of one heading to be read closely. The whole page figure is
# the lower of the two because these are committed and a magazine page is mostly
# photograph; the detail any assertion turns on is in the crops.
PAGE_SCALE = 1.5
CROP_SCALE = 4.0
# Points around a band, so it is read against what stands beside it.
MARGIN_POINTS = 12.0

# A grey below this is ink. Page furniture is far lighter and display type far
# darker, so nothing here turns on the exact value.
INK_LEVEL = 160

# What counts as display type on a page: a span within this much of the largest
# span on it. A headline is set several times the size of its body text, so the
# band this picks out is the headline's.
DISPLAY_SIZE_RATIO = 0.9

# How far past the page frame a glyph box may reach before it is called out.
# The box a text extractor reports spans the font's ascent and descent rather
# than the ink, so this figure overstates what a reader loses and is quoted as
# a bound rather than as the visible overhang.
FRAME_TOLERANCE_POINTS = 1.0


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def ledger(arm: str) -> list[dict]:
    return load(BATCH_DIR / f"runs.{arm}.json")


def rows_by_sample(arm: str) -> dict[str, dict]:
    return {Path(row["sample"]).stem: row for row in ledger(arm)}


def working_dir(row: dict) -> Path:
    return ROOT / row["working_dir"]


def checkpoint_path(row: dict, stage: str) -> Path:
    return working_dir(row) / f"{checkpoint_module.checkpoint_stem(stage)}.xml"


def read_checkpoint(path: Path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return checkpoint_module.load_checkpoint(path)


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return render_diff.sha256_file(path)


# Two attributes of a checkpoint are minted fresh on every run rather than
# derived from the document: the debug id a paragraph is logged under and the id
# a chain is assembled under. They label, they do not say anything, and two runs
# of one input disagree on them by construction. Everything else is content, and
# it is the content the arms have to agree on byte for byte.
MINTED_ATTRIBUTES = re.compile(r'\s*(?:debug_id|chainId)="[^"]*"')


def content_digest(path: Path) -> str | None:
    """One checkpoint's bytes with the run's minted labels taken out."""
    if not path.is_file():
        return None
    text = MINTED_ATTRIBUTES.sub("", path.read_text(encoding="utf-8"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- what the heading pass did -------------------------------------------------


def title_report(row: dict) -> dict:
    return load(working_dir(row) / title_typeset.REPORT_NAME)


def changed_pages(report: dict) -> set[int]:
    """Every page the pass changed a heading on."""
    pages = set()
    for item in report.get("titles", ()):
        touched = (
            item.get("suppressed")
            or item.get("duplicates")
            or item["disposition"] != title_typeset.DISPOSITION_UNCHANGED
        )
        if touched:
            pages.add(item["page"])
    return pages


# --- reading a produced page ---------------------------------------------------


def page_gray(document, index: int, dpi: int):
    return render_diff.render_gray(document, index, dpi)


def display_band(pdf: Path, label: int) -> tuple | None:
    """The box the largest type on one page occupies, in the writer's own axes.

    Taken from the produced PDF rather than from the document, because the two
    do not share a coordinate system: a paragraph inside a form xobject is laid
    out in that object's space and the writer places it through a transform. The
    band a headline occupies is what the crops need, and the page itself is the
    only place it can be read without reproducing that transform.
    """
    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        spans = [
            span
            for block in page.get_text("dict").get("blocks", ())
            for line in block.get("lines", ())
            for span in line.get("spans", ())
        ]
        sizes = [span["size"] for span in spans]
        if not sizes:
            return None
        floor = max(sizes) * DISPLAY_SIZE_RATIO
        boxes = [span["bbox"] for span in spans if span["size"] >= floor]
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )


def band_ink(pdf: Path, label: int, band: tuple) -> dict:
    """How much ink one band of one page carries, and how far it reaches.

    A headline drawn twice covers twice the width and roughly twice the ink of
    the same headline drawn once, whatever either layer is painted in, so this
    is the pixel side of the deduplication.
    """
    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        clip = pymupdf.Rect(*band) & page.rect
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(CROP_SCALE, CROP_SCALE), clip=clip, colorspace="gray"
        )
        gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width
        )
    mask = gray < INK_LEVEL
    columns = np.nonzero(mask.any(axis=0))[0]
    return {
        "ink_pixels": int(mask.sum()),
        "ink_fraction": round(float(mask.mean()), 6),
        "ink_width_points": 0.0
        if not len(columns)
        else round(float(columns[-1] - columns[0] + 1) / CROP_SCALE, 2),
        "band": [round(value, 2) for value in band],
    }


def glyph_boxes(pdf: Path, label: int) -> tuple[list, tuple]:
    """Every character the page draws, with the frame it is drawn on."""
    boxes = []
    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        frame = tuple(page.rect)
        for block in page.get_text("rawdict").get("blocks", ()):
            for line in block.get("lines", ()):
                for span in line.get("spans", ()):
                    for character in span.get("chars", ()):
                        boxes.append((character["c"], tuple(character["bbox"])))
    return boxes, frame


def render_page(pdf: Path, label: int, stem: str) -> str:
    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        page.get_pixmap(matrix=pymupdf.Matrix(PAGE_SCALE, PAGE_SCALE)).save(
            RASTER_DIR / f"{stem}.png"
        )
    return (RASTER_DIR / f"{stem}.png").relative_to(ROOT).as_posix()


def render_crop(pdf: Path, label: int, band: tuple, stem: str) -> str:
    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        clip = (
            pymupdf.Rect(
                band[0] - MARGIN_POINTS,
                band[1] - MARGIN_POINTS,
                band[2] + MARGIN_POINTS,
                band[3] + MARGIN_POINTS,
            )
            & page.rect
        )
        page.get_pixmap(matrix=pymupdf.Matrix(CROP_SCALE, CROP_SCALE), clip=clip).save(
            RASTER_DIR / f"{stem}.png"
        )
    return (RASTER_DIR / f"{stem}.png").relative_to(ROOT).as_posix()


# --- the arms ------------------------------------------------------------------


def pair_pages(left: Path, right: Path, dpi: int, threshold: int) -> list[dict]:
    """Page by page, whether two produced PDFs differ and by how much."""
    pages = []
    with pymupdf.open(left) as first, pymupdf.open(right) as second:
        for index in range(min(first.page_count, second.page_count)):
            entry: dict = {"page": index + 1}
            gray_left = page_gray(first, index, dpi)
            gray_right = page_gray(second, index, dpi)
            if gray_left.shape != gray_right.shape:
                entry.update({"differs": True, "size_mismatch": True})
                pages.append(entry)
                continue
            delta = np.abs(gray_left.astype(np.int16) - gray_right.astype(np.int16))
            mask = delta > threshold
            entry["diff_ratio"] = round(float(mask.sum()) / float(mask.size), 8)
            entry["differs"] = bool(mask.any())
            pages.append(entry)
    return pages


def compare_arms(sample: str, rows: dict[str, dict]) -> dict:
    """One sample's three arms: what the switch changed, over what a run varies by."""
    base, control, subject = (rows[arm] for arm in ARMS)
    result: dict = {"sample": sample}
    for stage in (TRANSLATED_STAGE, TYPESET_STAGE):
        digests = {arm: content_digest(checkpoint_path(rows[arm], stage)) for arm in ARMS}
        result[stage] = {
            "sha256": digests,
            "identical": digests[BASE_ARM] is not None
            and digests[BASE_ARM] == digests[SUBJECT_ARM],
            "control_identical": digests[BASE_ARM] is not None
            and digests[BASE_ARM] == digests[CONTROL_ARM],
            "verbatim_sha256": {
                arm: digest(checkpoint_path(rows[arm], stage)) for arm in ARMS
            },
        }

    report = title_report(subject)
    result["titles"] = report["totals"]
    touched = changed_pages(report)
    result["changed_pages"] = sorted(touched)

    settings = render_diff.load_config()
    dpi, threshold = settings["dpi"], settings["pixel_diff_threshold"]
    contrast = pair_pages(ROOT / base["pdf"], ROOT / subject["pdf"], dpi, threshold)
    floor = pair_pages(ROOT / base["pdf"], ROOT / control["pdf"], dpi, threshold)
    floor_differs = {item["page"] for item in floor if item.get("differs")}

    pages = []
    stray = []
    unattributable = []
    for item in contrast:
        label = item["page"]
        entry = dict(item)
        entry["control_differs"] = label in floor_differs
        entry["heading_changed"] = label in touched
        if item.get("differs"):
            if entry["control_differs"]:
                unattributable.append(label)
            elif not entry["heading_changed"]:
                stray.append(f"p{label}: differs with no heading changed and a quiet control")
        pages.append(entry)
    result["page_diff"] = pages
    result["stray"] = stray
    result["unattributable_pages"] = unattributable
    result["pages"] = {arm: _page_count(ROOT / rows[arm]["pdf"]) for arm in ARMS}

    repair = "react_repair.report.json"
    result["repair"] = {
        f"{arm}_touched": _touched(working_dir(rows[arm]) / repair) for arm in ARMS
    }
    # The repair loop's decision is a request issued with the cache bypassed, so
    # it is sampled afresh on every run and two runs of one configuration can
    # act differently. It is held to the same rule as everything else here: it
    # counts against the switch only where the repeat arm reproduced the first
    # one and the subject did not.
    result["repair"]["control_identical"] = (
        result["repair"][f"{BASE_ARM}_touched"]
        == result["repair"][f"{CONTROL_ARM}_touched"]
    )
    result["repair"]["identical"] = (
        result["repair"][f"{BASE_ARM}_touched"]
        == result["repair"][f"{SUBJECT_ARM}_touched"]
    )
    result["repair"]["attributable"] = (
        result["repair"]["control_identical"] and not result["repair"]["identical"]
    )
    result["repair"][f"{SUBJECT_ARM}_live_decisions"] = _live_decisions(
        working_dir(subject) / repair
    )
    result["api_calls"] = {arm: rows[arm]["api_calls"] for arm in ARMS}
    result["requests"] = {arm: rows[arm]["requests"] for arm in ARMS}
    return result


def _page_count(pdf: Path) -> int:
    with pymupdf.open(pdf) as document:
        return document.page_count


def _touched(path: Path) -> list[str] | None:
    if not path.is_file():
        return None
    return sorted((load(path).get("conservation") or {}).get("touched_refs") or ())


def _live_decisions(path: Path) -> int:
    """How many questions the repair loop asked that no cache could answer.

    Its decision request is issued with the cache bypassed, by its own design,
    so it is charged on every run whatever came before it. That is the whole of
    what the arm with the switch up spends.
    """
    if not path.is_file():
        return 0
    return sum(
        1
        for iteration in load(path).get("iterations", ())
        if not (iteration.get("decision") or {}).get("from_cache")
    )


# --- case a: the doubled headline ----------------------------------------------


def case_ghost(rows_off: dict, rows_on: dict, config) -> dict:
    off, on = rows_off[GHOST_SAMPLE], rows_on[GHOST_SAMPLE]
    report = title_report(on)
    duplicates = [item for item in report["duplicates"] if item["page"] == GHOST_PAGE]
    references = sorted({item["reference"] for item in duplicates})

    document = read_checkpoint(checkpoint_path(on, TYPESET_STAGE))
    # The band's ink is compared across the arms, so the heading itself has to
    # be the same heading in both. It is read from each arm's own document
    # rather than assumed from the pair being one translation, because this
    # sample is the one whose arms did not reproduce each other everywhere.
    other = read_checkpoint(checkpoint_path(off, TYPESET_STAGE))
    layers = {}
    for reference in references:
        index = int(reference.split("#")[1])
        paragraph = document.page[GHOST_PAGE - 1].pdf_paragraph[index]
        runs = title_typeset.style_runs(title_typeset.laid_out_characters(paragraph))
        kept, dropped = title_typeset.duplicate_runs(runs, config)
        mirror = other.page[GHOST_PAGE - 1].pdf_paragraph[index]
        mirror_text = "".join(
            item.char_unicode or ""
            for item in title_typeset.laid_out_characters(mirror)
        )
        laid_out = "".join(run.text for run in runs)
        layers[reference] = {
            "as_laid_out": laid_out,
            "kept": "".join(run.text for run in kept),
            "runs": len(runs),
            "runs_dropped": len(dropped),
            "same_heading_in_both_arms": mirror_text == laid_out,
        }

    record = {
        "sample": GHOST_SAMPLE,
        "page": GHOST_PAGE,
        "duplicates": duplicates,
        "references": references,
        "layers": layers,
        "record": [
            item
            for item in report["titles"]
            if item["reference"] in set(references)
        ],
    }

    # The band the display type occupies, per arm, taken from the produced page.
    # This is the measure the deduplication moves: a headline drawn twice runs
    # twice as far across the page as the same headline drawn once, whatever
    # either layer is painted in. Ink is measured too, in one band for both arms
    # so the two are comparable, and it is the second measure rather than the
    # first because the layer that goes is painted with a gradient pattern --
    # on this page it lands white on white and a reader loses nothing visible
    # by it, which is the difference between this run and the F1 one below.
    bands = {
        arm: display_band(ROOT / row["pdf"], GHOST_PAGE)
        for arm, row in (("off", off), ("on", on))
    }
    band = bands["off"]
    extent = {
        arm: None if value is None else round(value[2] - value[0], 2)
        for arm, value in bands.items()
    }
    ink = {}
    rasters = {}
    if band is not None:
        for arm, row in (("off", off), ("on", on)):
            ink[arm] = band_ink(ROOT / row["pdf"], GHOST_PAGE, band)
            rasters[f"{arm}_page"] = render_page(
                ROOT / row["pdf"], GHOST_PAGE, f"ghost.p{GHOST_PAGE}.{arm}"
            )
            rasters[f"{arm}_crop"] = render_crop(
                ROOT / row["pdf"], GHOST_PAGE, band, f"ghost.p{GHOST_PAGE}.{arm}.crop"
            )
        f1_pdf = F1_DIR / GHOST_SAMPLE / f"{GHOST_SAMPLE}.final.pdf"
        if f1_pdf.is_file():
            f1_band = display_band(f1_pdf, GHOST_PAGE)
            if f1_band is not None:
                ink["f1"] = band_ink(f1_pdf, GHOST_PAGE, f1_band)
                extent["f1"] = round(f1_band[2] - f1_band[0], 2)
                rasters["f1_page"] = render_page(
                    f1_pdf, GHOST_PAGE, f"ghost.p{GHOST_PAGE}.f1"
                )
                rasters["f1_crop"] = render_crop(
                    f1_pdf, GHOST_PAGE, f1_band, f"ghost.p{GHOST_PAGE}.f1.crop"
                )
    record["ink"] = ink
    record["display_extent_points"] = extent
    record["raster"] = rasters
    record["extent_ratio"] = (
        None
        if not extent.get("off")
        else round(extent["on"] / extent["off"], 4)
    )
    # Whether the layer that was dropped was drawing anything a reader could
    # see. It is stated rather than assumed, because it is what says how much
    # of this case is a rendering defect and how much is a text defect.
    record["dropped_layer_was_visible"] = (
        None
        if band is None or extent["on"] is None
        else bool(
            band_ink(
                ROOT / off["pdf"],
                GHOST_PAGE,
                (bands["on"][2], band[1], band[2], band[3]),
            )["ink_pixels"]
        )
    )

    faults = []
    if not duplicates:
        faults.append("the deduplication is not in the sidecar")
    for reference, layer in layers.items():
        if layer["kept"] == layer["as_laid_out"]:
            faults.append(f"{reference}: nothing was dropped")
        if layer["kept"] * 2 != layer["as_laid_out"]:
            faults.append(
                f"{reference}: what is kept is not half of what was laid out"
            )
        if not layer["same_heading_in_both_arms"]:
            faults.append(
                f"{reference}: the arms carry different headings, so the ink "
                f"either side of the comparison is not the same headline"
            )
    if record["extent_ratio"] is None:
        faults.append("the headline band could not be read from the page")
    elif record["extent_ratio"] > 0.75:
        faults.append(
            f"the headline still runs {record['extent_ratio']} of the way it ran "
            f"when it was drawn twice"
        )
    record["faults"] = faults
    # What the two layers were for, and what dropping one of them costs. The
    # source sets this headline twice on purpose -- a solid layer under a
    # gradient layer, which together read as one headline fading to the right --
    # and the paragraph finder recovered the pair as one paragraph, so the
    # translator was shown the text twice and answered it twice. Rendering one
    # layer is what fixes the doubled text; it also gives up the overlay the
    # design was made of. The fix that keeps both is deduplication before the
    # translation, which changes the text a heading is translated as and is why
    # this batch does not do it.
    record["what_the_layers_were"] = {
        "design": "a solid layer under a gradient layer, read as one headline",
        "kept": "the solid layer",
        "given_up": "the gradient overlay",
        "the_fix_that_keeps_both": (
            "deduplicating before the translation, which this batch does not do "
            "because it would change the text a heading is translated as"
        ),
    }
    return record


# --- case b: the cover headings ------------------------------------------------


def case_cover(rows_off: dict, rows_on: dict) -> dict:
    """The cover headings: what the policy fixed, and what it did not.

    Two things are wrong with this page and only one of them is this batch's.
    Both cover headings were wrapped, and the policy is what unwraps them. One
    of them also draws past the top edge of the page, and that is a different
    mechanism: the layout anchors a paragraph's first line at the top of its box
    less the modal height of its units, and this paragraph merges a display
    masthead with the credit line beside it, so the anchor follows the credit
    and the masthead stands above it. Setting the heading on one line shrinks
    that overhang and cannot close it, so the residue is measured and named
    rather than counted as fixed.
    """
    off, on = rows_off[COVER_SAMPLE], rows_on[COVER_SAMPLE]
    report = title_report(on)
    headings = [item for item in report["titles"] if item["page"] == COVER_PAGE]
    wrapped = [item for item in headings if item.get("lines_before", 0) > 1]

    record = {
        "sample": COVER_SAMPLE,
        "page": COVER_PAGE,
        "headings": headings,
        "wrapped_before": [item["reference"] for item in wrapped],
        "still_wrapped": [
            item["reference"]
            for item in wrapped
            if item.get("lines_after", item.get("lines_before")) != 1
        ],
    }

    outside = {}
    overhang = {}
    for arm, row in (("off", off), ("on", on)):
        boxes, frame = glyph_boxes(ROOT / row["pdf"], COVER_PAGE)
        escaped = []
        worst = 0.0
        for character, box in boxes:
            beyond = max(
                frame[0] - box[0],
                frame[1] - box[1],
                box[2] - frame[2],
                box[3] - frame[3],
            )
            if beyond > FRAME_TOLERANCE_POINTS:
                escaped.append(
                    {
                        "char": character,
                        "bbox": [round(value, 2) for value in box],
                        "beyond_frame": round(beyond, 2),
                    }
                )
                worst = max(worst, beyond)
        outside[arm] = escaped
        overhang[arm] = round(worst, 2)
        record[f"{arm}_glyphs"] = len(boxes)
    record["frame"] = [round(value, 2) for value in frame]
    record["outside_frame"] = {arm: len(items) for arm, items in outside.items()}
    record["outside_frame_detail"] = {
        arm: items[:12] for arm, items in outside.items() if items
    }
    record["outside_frame_text"] = {
        arm: "".join(item["char"] for item in items) for arm, items in outside.items()
    }
    # How far the worst glyph box reaches past the edge. The count is not the
    # measure the residue moves on -- it rises when a wrapped line becomes one
    # line -- and this is.
    record["overhang_points"] = overhang

    band = display_band(ROOT / off["pdf"], COVER_PAGE)
    rasters = {}
    for arm, row in (("off", off), ("on", on)):
        rasters[f"{arm}_page"] = render_page(
            ROOT / row["pdf"], COVER_PAGE, f"cover.p{COVER_PAGE}.{arm}"
        )
        if band is not None:
            rasters[f"{arm}_crop"] = render_crop(
                ROOT / row["pdf"], COVER_PAGE, band, f"cover.p{COVER_PAGE}.{arm}.crop"
            )
    record["raster"] = rasters

    faults = []
    if record["still_wrapped"]:
        faults.append(f"still wrapped: {record['still_wrapped']}")
    if not wrapped:
        faults.append("no heading on this page was wrapped, so the case is vacuous")
    if overhang["on"] > overhang["off"]:
        faults.append(
            f"the overhang grew from {overhang['off']} to {overhang['on']} points"
        )
    record["faults"] = faults
    record["open_defect"] = (
        None
        if not outside["on"]
        else {
            "what": "a display heading draws past the top edge of the page",
            "sample": COVER_SAMPLE,
            "page": COVER_PAGE,
            "overhang_points": overhang,
            "why": (
                "the layout anchors a paragraph's first line at the top of its "
                "box less the modal height of its units, and this paragraph "
                "carries a masthead and the credit line beside it, so the "
                "anchor follows the credit and the masthead stands above it"
            ),
            "why_this_batch_does_not_close_it": (
                "the scale that would bring the glyph box under the edge is far "
                "below the floor, and shrinking a masthead to a quarter of its "
                "size to fit a frame is not setting a heading; containment "
                "against the page edge is a collision question"
            ),
        }
    )
    return record


# --- case c: the ruled sample --------------------------------------------------


def case_ruled(rows_on: dict) -> dict:
    on = rows_on[RULED_SAMPLE]
    report = title_report(on)
    raised = {item["reference"] for item in report["escalations"]}
    accounted, unaccounted = [], []
    for item in report["titles"]:
        lines = item.get("lines_after", item.get("lines_before"))
        if item.get("suppressed"):
            accounted.append({"reference": item["reference"], "as": "suppressed"})
        elif lines == 1:
            accounted.append({"reference": item["reference"], "as": "one line"})
        elif item["reference"] in raised:
            accounted.append({"reference": item["reference"], "as": "raised"})
        else:
            unaccounted.append({"reference": item["reference"], "lines": lines})

    terms = _added_terms()
    carried, matched = _applied_terms(working_dir(on))
    missing = sorted(term for term in terms if term not in carried)
    hits = [
        {"term": term, "prompts_matched": matched.get(term, 0)} for term in sorted(terms)
    ]
    return {
        "sample": RULED_SAMPLE,
        "titles": len(report["titles"]),
        "accounted": accounted,
        "unaccounted": unaccounted,
        "ruling_terms_added": sorted(terms),
        "ruling_terms_carried": sorted(term for term in terms if term in carried),
        "ruling_terms_hits": hits,
        "ruling_terms_unmatched": [
            item["term"] for item in hits if not item["prompts_matched"]
        ],
        "ruling_terms_missing": missing,
        "faults": (
            [f"{len(unaccounted)} heading(s) neither on one line nor raised"]
            if unaccounted
            else []
        )
        + (
            [f"{len(missing)} ruled term(s) never reached the glossary"]
            if missing
            else []
        ),
    }


def _added_terms() -> set[str]:
    """The terms the ruling's revision added, read from the revision itself."""
    path = hitl.decisions_path(RULED_SAMPLE)
    relative = path.relative_to(ROOT).as_posix()
    proc = subprocess.run(  # noqa: S603
        ["git", "show", f"{RULING_REVISION}:{relative}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    before = json.loads(proc.stdout).get("terms", {}) if proc.returncode == 0 else {}
    after = load(path).get("terms", {})
    return {term for term in after if term not in before}


def _applied_terms(work: Path) -> tuple[set[str], dict[str, int]]:
    """What the run's own apply pass carried, and how often each was activated.

    Two different things, which the report keeps apart and so does this: an
    entry is a term the ruling put into the glossary the requests were built
    with, and a match is a request whose text that entry fired on. A ruled name
    the sample never mentions is carried and never matched, which is the ruling
    being wider than one sample rather than the run losing a term.
    """
    path = work / "hitl_apply.report.json"
    if not path.is_file():
        return set(), {}
    terms = load(path).get("terms") or {}
    carried = {
        entry["source"] for entry in terms.get("entries", ()) if entry.get("source")
    }
    matched = {
        entry["source"]: int(entry.get("matched_prompt_count") or 0)
        for entry in terms.get("matches", ())
        if entry.get("source")
    }
    return carried, matched


# --- case d: every heading that reached the floor ------------------------------


def case_floor(rows_on: dict) -> dict:
    listed = []
    for sample, row in sorted(rows_on.items()):
        report = title_report(row)
        for item in report["escalations"]:
            listed.append(
                {
                    "sample": sample,
                    "page": item["page"],
                    "reference": item["reference"],
                    "required_scale": item["required_scale"],
                    "floor": item["floor"],
                    "lines": item["lines_after"],
                    "disposition": report["on_floor"],
                }
            )
    return {"escalations": listed, "count": len(listed)}


# --- case e: does a doubled heading reach M3 -----------------------------------


def case_metric(rows_on: dict) -> dict:
    """Whether the doubled text a heading carries is inside the LTCR measurement.

    The metric counts a term inside a region built from body paragraphs, so a
    heading should be outside it by construction. That is asserted rather than
    assumed: the regions are built as the reporter builds them, the paragraphs
    the pass found a doubled layer in are looked for inside them, and the metric
    is measured twice -- once as the run left it, once with every doubled layer
    collapsed -- and the two summaries compared.
    """
    import eval_report

    findings = []
    for sample, row in sorted(rows_on.items()):
        report = title_report(row)
        doubled = {item["reference"] for item in report["duplicates"]}
        if not doubled:
            continue
        source = read_checkpoint(checkpoint_path(row, eval_report.SOURCE_STAGE))
        translated = read_checkpoint(checkpoint_path(row, TRANSLATED_STAGE))
        regions = eval_report._regions_for_ltcr(source, translated)
        measured = {
            debug_id for _name, sources, _targets in regions for debug_id in sources
        }
        doubled_ids = _debug_ids_of(translated, doubled)
        terminals = tuple(load_chain_config()["terminal_punctuation"])
        before = ltcr.measure(regions, terminals)["summary"]
        after = ltcr.measure(_collapse(regions, doubled_ids), terminals)["summary"]
        findings.append(
            {
                "sample": sample,
                "doubled_headings": sorted(doubled),
                "doubled_paragraphs_inside_the_measurement": sorted(
                    doubled_ids & measured
                ),
                "summary_as_run": before,
                "summary_collapsed": after,
                "identical": before == after,
            }
        )
    return {
        "samples": findings,
        "contaminated": [item["sample"] for item in findings if not item["identical"]],
        "faults": [],
    }


def _debug_ids_of(document, references: set[str]) -> set[str]:
    found = set()
    for label, page in hitl.labeled_pages(document):
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            if f"p{label}#{index}" in references:
                found.add(paragraph.debug_id or f"p{label}#{index}")
    return found


def _collapse(regions, doubled_ids: set[str]):
    """The same regions with each doubled paragraph's text halved.

    Halving is what collapsing a layer does to a paragraph the finder merged two
    identical layers into: the text is one sentence written twice, and the first
    half is the sentence.
    """
    collapsed = []
    for name, sources, targets in regions:
        new_sources, new_targets = dict(sources), dict(targets)
        for debug_id in doubled_ids & set(sources):
            for mapping in (new_sources, new_targets):
                text = mapping.get(debug_id) or ""
                half = len(text) // 2
                if half and text[:half] == text[half:]:
                    mapping[debug_id] = text[:half]
        collapsed.append((name, new_sources, new_targets))
    return collapsed


# --- the frozen fixture --------------------------------------------------------


def freeze_fixture(rows_on: dict, config) -> dict:
    """The doubled headline as a committed document, so the gate stops guessing.

    A working directory is swept; a fixture is not. What is frozen is the
    smallest document that still carries the case -- the headings of the page
    the defect is on, as the layout left them -- beside the sidecar the pass
    wrote for that run.
    """
    from babeldoc.format.pdf.document_il import il_version_1

    row = rows_on[GHOST_SAMPLE]
    document = read_checkpoint(checkpoint_path(row, TYPESET_STAGE))
    page = copy.deepcopy(document.page[GHOST_PAGE - 1])
    # An excerpt renumbers what it keeps, so the reference a heading answers to
    # in the run's sidecar is not the reference it answers to here. The mapping
    # is written down rather than reconstructed, because reconstructing it needs
    # the page this excerpt exists to avoid keeping.
    kept = [
        (index, paragraph)
        for index, paragraph in enumerate(page.pdf_paragraph or ())
        if config.is_title(paragraph)
    ]
    references = [f"p{GHOST_PAGE}#{index}" for index, _paragraph in kept]
    page.pdf_paragraph = [paragraph for _index, paragraph in kept]
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    fixture = FIXTURE_DIR / f"{GHOST_SAMPLE}.titles.xml"
    # The page count is declared, because a checkpoint that does not declare one
    # matching its pages is refused when it is read back -- which is the point
    # of freezing it in the form the loader accepts rather than in some other.
    excerpt = il_version_1.Document(page=[page], total_pages=1)
    fixture.write_text(
        checkpoint_module.to_checkpoint_xml(excerpt), encoding="utf-8"
    )
    sidecar = FIXTURE_DIR / f"{GHOST_SAMPLE}.{title_typeset.REPORT_NAME}"
    sidecar.write_text(
        (working_dir(row) / title_typeset.REPORT_NAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return {
        "document": fixture.relative_to(ROOT).as_posix(),
        "document_sha256": digest(fixture),
        "sidecar": sidecar.relative_to(ROOT).as_posix(),
        "sidecar_sha256": digest(sidecar),
        "sample": GHOST_SAMPLE,
        "page": GHOST_PAGE,
        "headings": len(page.pdf_paragraph),
        "references": references,
    }


# --- the report ----------------------------------------------------------------


def cost(rows: dict) -> dict:
    return {
        "requests": sum(row["requests"] for row in rows.values()),
        "cache_hits": sum(row["cache_hits"] for row in rows.values()),
        "api_calls": sum(row["api_calls"] for row in rows.values()),
        "prompt_tokens": sum(row["prompt_tokens"] for row in rows.values()),
        "completion_tokens": sum(row["completion_tokens"] for row in rows.values()),
        "seconds": round(sum(row["seconds"] for row in rows.values()), 1),
    }


def markdown(evidence: dict) -> str:
    lines = [
        "# B9.2 acceptance: the heading policy over five samples",
        "",
        "Three arms per sample, the same stack in all three. Two of them differ "
        "in one attribute; the third repeats the first, and is what says how "
        "much a run differs from itself.",
        "",
        "## The arms",
        "",
        "| sample | translated | typeset | control quiet | pages differing | "
        "unattributable | stray |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in evidence["arms"]:
        differing = sum(1 for page in item["page_diff"] if page.get("differs"))
        lines.append(
            f"| {item['sample']} "
            f"| {'same' if item['il_translated']['identical'] else 'DIFFERS'} "
            f"| {'same' if item['typesetting']['identical'] else 'DIFFERS'} "
            f"| {'yes' if item['typesetting']['control_identical'] else 'no'} "
            f"| {differing} of {item['pages']['on']} "
            f"| {item['unattributable_pages'] or 'none'} "
            f"| {'; '.join(item['stray']) or 'none'} |"
        )
    lines += [
        "",
        "## Cost",
        "",
        "| arm | requests | cache hits | API calls | prompt tokens | "
        "completion tokens | seconds |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm in ARMS:
        row = evidence["cost"][arm]
        lines.append(
            f"| {arm} | {row['requests']} | {row['cache_hits']} | {row['api_calls']} "
            f"| {row['prompt_tokens']} | {row['completion_tokens']} | {row['seconds']} |"
        )
    accounted = sum(
        item["repair"][f"{SUBJECT_ARM}_live_decisions"] for item in evidence["arms"]
    )
    lines += [
        "",
        f"The repair loop's decision bypasses the cache by design and is what "
        f"the arm with the switch up is charged for: {accounted} call(s) of "
        f"{evidence['cost'][SUBJECT_ARM]['api_calls']}.",
    ]

    ghost = evidence["ghost"]
    lines += [
        "",
        "## a. The doubled headline",
        "",
        f"{ghost['sample']} page {ghost['page']}, heading(s) {ghost['references']}.",
    ]
    for reference, layer in ghost["layers"].items():
        lines.append(
            f"- {reference}: laid out as {layer['runs']} run(s), "
            f"{layer['runs_dropped']} dropped."
        )
    if ghost["ink"]:
        lines += [
            "",
            "| arm | display band width (pt) | ink pixels in the off arm's band |",
            "| --- | --- | --- |",
            *(
                f"| {arm} | {ghost['display_extent_points'].get(arm)} "
                f"| {row['ink_pixels']} |"
                for arm, row in ghost["ink"].items()
            ),
            "",
            f"Band with the switch up over band with it down: "
            f"{ghost['extent_ratio']}. The layer that was dropped was drawing "
            f"something a reader could see: {ghost['dropped_layer_was_visible']}. "
            f"On this page it is painted with a gradient pattern that lands "
            f"white on white, so the defect it leaves here is doubled text "
            f"rather than a visible ghost; the F1 raster beside these is the "
            f"page the visible one was reported from.",
            "",
            f"What the two layers were: {ghost['what_the_layers_were']['design']}. "
            f"Kept: {ghost['what_the_layers_were']['kept']}. "
            f"Given up: {ghost['what_the_layers_were']['given_up']}. "
            f"The fix that keeps both is "
            f"{ghost['what_the_layers_were']['the_fix_that_keeps_both']}.",
        ]
    lines += ["", *(f"- {name}: `{path}`" for name, path in ghost["raster"].items())]

    cover = evidence["cover"]
    lines += [
        "",
        "## b. The cover headings",
        "",
        f"{cover['sample']} page {cover['page']}, frame {cover['frame']}.",
        f"Wrapped before: {cover['wrapped_before']}. "
        f"Still wrapped: {cover['still_wrapped'] or 'none'}.",
        f"Glyph boxes past the frame: off {cover['outside_frame']['off']}, "
        f"on {cover['outside_frame']['on']}; worst overhang off "
        f"{cover['overhang_points']['off']}pt, on {cover['overhang_points']['on']}pt.",
        "",
    ]
    if cover["open_defect"]:
        lines += [
            f"**Open, not closed by this batch**: {cover['open_defect']['what']}. "
            f"{cover['open_defect']['why']}. "
            f"{cover['open_defect']['why_this_batch_does_not_close_it']}.",
            "",
        ]
    lines += [f"- {name}: `{path}`" for name, path in cover["raster"].items()]

    ruled = evidence["ruled"]
    lines += [
        "",
        "## c. Every heading of the ruled sample",
        "",
        f"{ruled['titles']} heading(s), {len(ruled['accounted'])} accounted for, "
        f"{len(ruled['unaccounted'])} not.",
        f"Ruled terms added by the revision: {len(ruled['ruling_terms_added'])}, "
        f"carried into the glossary: {len(ruled['ruling_terms_carried'])}, "
        f"never matched by a request: {ruled['ruling_terms_unmatched'] or 'none'}.",
        "",
        "| ruled term | prompts matched |",
        "| --- | --- |",
        *(
            f"| {item['term']} | {item['prompts_matched']} |"
            for item in ruled["ruling_terms_hits"]
        ),
        "",
        "## d. Every heading that reached the floor",
        "",
        "| sample | page | heading | scale asked for | floor | lines | disposition |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *(
            f"| {item['sample']} | {item['page']} | {item['reference']} "
            f"| {item['required_scale']} | {item['floor']} | {item['lines']} "
            f"| {item['disposition']} |"
            for item in evidence["floor"]["escalations"]
        ),
    ]

    metric = evidence["metric"]
    lines += [
        "",
        "## e. Does a doubled heading reach M3",
        "",
        f"Samples carrying a doubled heading: {len(metric['samples'])}. "
        f"Contaminated: {metric['contaminated'] or 'none'}.",
        "",
        "## The frozen fixture",
        "",
        f"- `{evidence['fixture']['document']}`",
        f"- `{evidence['fixture']['sidecar']}`",
        "",
        "## Faults",
        "",
        *(f"- {fault}" for fault in evidence["faults"] or ["none"]),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    config = title_typeset.load_title_config()
    by_arm = {arm: rows_by_sample(arm) for arm in ARMS}
    samples = sorted(
        set(by_arm[BASE_ARM]) & set(by_arm[CONTROL_ARM]) & set(by_arm[SUBJECT_ARM])
    )

    arms = [
        compare_arms(sample, {arm: by_arm[arm][sample] for arm in ARMS})
        for sample in samples
    ]
    rows_off, rows_on = by_arm[BASE_ARM], by_arm[SUBJECT_ARM]
    evidence = {
        "batch": "b9_2",
        "switch": title_typeset.SWITCH,
        "samples": samples,
        "arms": arms,
        "cost": {arm: cost(by_arm[arm]) for arm in ARMS},
        "ghost": case_ghost(rows_off, rows_on, config),
        "cover": case_cover(rows_off, rows_on),
        "ruled": case_ruled(rows_on),
        "floor": case_floor(rows_on),
        "metric": case_metric(rows_on),
        "fixture": freeze_fixture(rows_on, config),
    }

    faults = []
    for item in arms:
        for stage in (TRANSLATED_STAGE, TYPESET_STAGE):
            if not item[stage]["identical"] and item[stage]["control_identical"]:
                faults.append(
                    f"{item['sample']}: the {stage} checkpoint differs between the "
                    f"arms and the control is quiet, so the switch moved it"
                )
        faults += [f"{item['sample']}: {reason}" for reason in item["stray"]]
        if item["repair"]["attributable"]:
            faults.append(
                f"{item['sample']}: the repair touched different paragraphs while "
                f"the control reproduced, so the switch moved it"
            )
        if item["api_calls"][SUBJECT_ARM] < item["repair"][f"{SUBJECT_ARM}_live_decisions"]:
            faults.append(f"{item['sample']}: fewer calls than decisions")
    for case in ("ghost", "cover", "ruled", "metric"):
        faults += [f"{case}: {reason}" for reason in evidence[case]["faults"]]
    if evidence["metric"]["contaminated"]:
        faults.append(f"M3 is contaminated in {evidence['metric']['contaminated']}")
    evidence["faults"] = faults

    with (BATCH_DIR / "evidence.json").open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False, sort_keys=True)
    (BATCH_DIR / "report.md").write_text(markdown(evidence), encoding="utf-8")
    print(markdown(evidence))
    return 0 if not faults else 1


if __name__ == "__main__":
    raise SystemExit(main())
