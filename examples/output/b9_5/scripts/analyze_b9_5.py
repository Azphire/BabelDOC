"""B9.5 acceptance: the census, the containment, and the evidence behind both.

Every number in the report this writes is computed here from what the three arms
produced, and nothing is copied in by hand.

Two instruments, and they answer different questions.

The three arms answer what the repair loop does to the corpus end to end. The
arm attribute is ``magazine_repair``, the control repeats the off arm, and the
difference between off and on counts against the switch only where the control
reproduced its arm.

The census and the containment inventory are computed here instead, by reading
each run's own checkpoints and driving the shipped detectors and the shipped
action over them. That is deliberate. The loop asks a model which findings to
act on, that request is by design not served from the cache, and a mechanism
measured through a sampled decision is measured through the sampling as well.
Driving the action directly removes the sampling from the measurement of the
action, and what it costs is that the resulting geometry is not written to a
PDF: the pixels in this report come from the arms, and the geometry from here.

Which document is measured. The finished geometry is the typesetting checkpoint,
which is the document as the typesetting stage left it. The pass between that
checkpoint and detection is the heading policy, so this cross checks its own
findings against the ``issues.json`` the run wrote and reports the difference
per sample rather than assuming there is none.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.detectors import base as detector_base  # noqa: E402
from babeldoc.magazine.detectors import collision as collision_detector  # noqa: E402
from babeldoc.magazine.detectors import page_bounds  # noqa: E402
from babeldoc.magazine.detectors import source_geometry  # noqa: E402
from babeldoc.magazine.drop_cap import paragraph_reference  # noqa: E402
from babeldoc.magazine.react import actions as react_actions  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import controller as react  # noqa: E402

from tools import render_diff  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b9_5"
RASTER_DIR = OUT_DIR / "raster"
FIXTURE_DIR = OUT_DIR / "fixtures"
EVIDENCE = OUT_DIR / "evidence.json"
REPORT = OUT_DIR / "report.md"
CENSUS = OUT_DIR / "collision_census.md"

ARMS = ("off", "control", "on", "contain")
BASE_ARM = "off"
CONTROL_ARM = "control"
SUBJECT_ARM = "on"
# The arm whose decision is scripted rather than sampled, and the only one that
# renders a contained heading to a page. What it is for, and what it is not, is
# stated where it is reported.
CONTAIN_ARM = "contain"

# How a page raster is compared, at the settings the render diff tool ships.
RASTER_DPI = 110
RASTER_THRESHOLD = 12
CROP_SCALE = 2.0
CROP_MARGIN = 18.0
# A whole page is context around a crop rather than the evidence itself, and one
# device pixel per point is what a reader needs to see where on the sheet the
# crop came from without the file being larger than everything else this batch
# commits.
PAGE_SCALE = 1.0

QUOTE = 40


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def ledger(arm: str) -> list[dict]:
    path = OUT_DIR / f"runs.{arm}.json"
    return load(path) if path.exists() else []


def rows_by_sample() -> dict[str, dict[str, dict]]:
    found: dict[str, dict[str, dict]] = {}
    for arm in ARMS:
        for row in ledger(arm):
            found.setdefault(row["sample"].removesuffix(".pdf"), {})[arm] = row
    return found


def working_dir(row: dict) -> Path:
    return ROOT / row["working_dir"]


def produced(row: dict) -> Path:
    return ROOT / row["pdf"]


_documents: dict[tuple[str, str], object] = {}


def checkpoint(row: dict, stage: str):
    key = (row["working_dir"], stage)
    if key not in _documents:
        _documents[key] = load_checkpoint(
            working_dir(row) / f"{checkpoint_stem(stage)}.xml"
        )
    return _documents[key]


def detector_config():
    return detectors.detector_config()


def repair_config():
    return react_config.load_repair_config(
        None, tuple(sorted(module.KIND for module in detectors.DETECTORS.values()))
    )


def contain_action():
    return repair_config().actions[contain.NAME]


# --- the document the geometry is measured on ----------------------------------


def measured(row: dict):
    """One run's finished document, its source layout, and the findings on it.

    The findings are made here by the shipped detectors rather than read from
    the sidecar, because the containment inventory needs the finding objects and
    the paragraphs they name. The sidecar is then compared against these.
    """
    config = detector_config()
    document = checkpoint(row, "typesetting")
    source = source_geometry.load(working_dir(row), config.source_geometry_stage)
    context = detectors.build_context(
        document,
        config,
        row["lang_out"],
        working_dir(row),
        source_geometry=source,
    )
    issues = detectors.run_detectors(context)
    return document, source, context, issues


def sidecar_agreement(row: dict, issues) -> dict:
    """Whether the findings made here are the findings the run itself recorded.

    The run detected after the heading policy had run and this detects before
    it, so the two can differ; where they do, the report says so rather than
    presenting one as the other.
    """
    path = working_dir(row) / detectors.REPORT_NAME
    if not path.exists():
        return {"sidecar": None, "agrees": None}
    recorded = load(path)
    here = {issue.id for issue in issues}
    there = {item["id"] for item in recorded["issues"]}
    return {
        "sidecar": str(path.relative_to(ROOT)),
        "counts_here": counts_of(issues),
        "counts_there": recorded["counts"]["by_kind"],
        "only_here": sorted(here - there),
        "only_there": sorted(there - here),
        "agrees": here == there,
    }


def counts_of(issues) -> dict:
    found: dict[str, int] = {}
    for issue in issues:
        found[issue.kind] = found.get(issue.kind, 0) + 1
    return dict(sorted(found.items()))


# --- b. the collision census ---------------------------------------------------


def text_rows(page):
    """Every paragraph of a page that carries text and an extent, as the

    detector reads them: index, the paragraph, its text and its rendered box.
    """
    rows = []
    for index, paragraph in enumerate(page.pdf_paragraph or ()):
        text = detector_base.rendered_text(paragraph).strip()
        box, _source = detector_base.rendered_box(paragraph)
        if not text or box is None:
            continue
        rows.append((index, paragraph, text, box))
    return rows


# How a pair is classified. The first three are the detector's own three
# outcomes; the fourth is the pair it never looks at, kept because a defect
# under the bound is still a defect somebody may want to see.
CLASS_INDUCED = "induced"
CLASS_DESIGN = "source design"
CLASS_UNMATCHED = "no source counterpart"
CLASS_BELOW = "below the bound"


def covered(left, right) -> float:
    """The shared area over the area of the smaller box.

    Measured beside the intersection over union the detector reports at, and
    reported rather than acted on. The two answer different questions and part
    company exactly where a magazine puts a folio inside a contents entry: a
    small box wholly inside a large one is an overlap of one by the first
    measure and of very little by the second, because the union it is divided by
    is the large box. Which of the two a detector should be bounded by is a
    question this census exists to inform and does not answer.
    """
    width = min(left[2], right[2]) - max(left[0], right[0])
    height = min(left[3], right[3]) - max(left[1], right[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min(
        max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1]),
        max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1]),
    )
    return width * height / smaller if smaller > 0 else 0.0


def classify_pairs(document, source, config) -> list[dict]:
    """Every overlapping pair of texts in one finished document, classified.

    Wider than the detector on purpose: the detector reports the pairs it is for
    and this counts every pair that overlaps at all, so a census can say what was
    exempted and what was under the bound as well as what was raised.
    """
    found: list[dict] = []
    for label, page in hitl.labeled_pages(document):
        rows = text_rows(page)
        for position, (index, paragraph, text, box) in enumerate(rows):
            for other_index, other, other_text, other_box in rows[position + 1 :]:
                iou = detector_base.intersection_over_union(box, other_box)
                if iou <= 0:
                    continue
                left = None if source is None else source.box_of(paragraph)
                right = None if source is None else source.box_of(other)
                if left is None or right is None:
                    verdict, source_iou = CLASS_UNMATCHED, None
                else:
                    source_iou = detector_base.intersection_over_union(left, right)
                    if source_iou >= config.collision_source_min_iou:
                        verdict = CLASS_DESIGN
                    elif iou >= config.collision_min_iou:
                        verdict = CLASS_INDUCED
                    else:
                        verdict = CLASS_BELOW
                found.append(
                    {
                        "page": label,
                        "refs": [
                            paragraph_reference(label, index),
                            paragraph_reference(label, other_index),
                        ],
                        "labels": [paragraph.layout_label, other.layout_label],
                        "iou": round(iou, 4),
                        "covered": round(covered(box, other_box), 4),
                        "source_covered": (
                            None
                            if left is None or right is None
                            else round(covered(left, right), 4)
                        ),
                        "source_iou": None if source_iou is None else round(source_iou, 4),
                        "class": verdict,
                        "raised": verdict == CLASS_INDUCED,
                        "text": [text[:QUOTE], other_text[:QUOTE]],
                    }
                )
    return found


# --- the out of page inventory, and where the ink came from --------------------

# How an overflow is accounted for, against what the same paragraph's source
# counterpart did. Induced is ink the source kept inside the frame and the
# translation put out; a bleed the translation deepened is a paragraph the
# source already ran past the trim and the translation ran further; and a bleed
# is one the translation did not worsen. The comparison is between the same two
# quantities on both sides -- the extent of the boxes the characters are laid
# out in -- which for a display line is the em box rather than the visible ink,
# so the figures are wider than what the reader sees being cut. They are
# comparable to each other, which is what a classification needs.
OVERFLOW_BLEED = "bleed"
OVERFLOW_WORSENED = "bleed the translation deepened"
OVERFLOW_INDUCED = "induced"
OVERFLOW_UNMATCHED = "no source counterpart"


def overflow_origin(paragraph, source, frame, finished: float) -> dict:
    """How far the source counterpart of this paragraph stood past the frame."""
    box = None if source is None else source.box_of(paragraph)
    if box is None or frame is None:
        return {"origin": OVERFLOW_UNMATCHED, "source_overflow": None, "added": None}
    worst = max(detector_base.overflow(box, frame).values())
    if worst <= 0:
        origin = OVERFLOW_INDUCED
    elif finished > worst:
        origin = OVERFLOW_WORSENED
    else:
        origin = OVERFLOW_BLEED
    return {
        "origin": origin,
        "source_box": [round(value, 2) for value in box],
        "source_overflow": round(worst, 4),
        "added": round(finished - worst, 4),
    }


def out_of_page_rows(document, source, issues) -> list[dict]:
    by_label = {label: page for label, page in hitl.labeled_pages(document)}
    rows = []
    for issue in issues:
        if issue.kind != page_bounds.KIND:
            continue
        page = by_label[issue.page]
        index = int(issue.paragraph_refs[0].split("#")[1])
        paragraph = page.pdf_paragraph[index]
        frame = detector_base.page_frame(page)
        rows.append(
            {
                "page": issue.page,
                "ref": issue.paragraph_refs[0],
                "layout_label": issue.evidence.get("layout_label"),
                "side": issue.evidence.get("overflow_side"),
                "overflow_points": issue.evidence.get("overflow_max"),
                "overflow_ratio": issue.evidence.get("overflow_ratio"),
                "frame_box": issue.evidence.get("frame_box"),
                "box": [
                    round(value, 2)
                    for value in detector_base.rendered_box(paragraph)[0]
                ],
                "text": detector_base.rendered_text(paragraph).strip()[:QUOTE],
                **overflow_origin(
                    paragraph,
                    source,
                    None if frame is None else frame[0],
                    float(issue.evidence.get("overflow_max") or 0.0),
                ),
            }
        )
    return rows


# --- c. the containment inventory ----------------------------------------------


def contain_inventory(document, context, issues, min_iou) -> dict:
    """Drive the shipped action over every out of page finding of one document.

    In the order the loop would, holding each finding against the action's own
    rule first, so what this records is the action's answer and not this
    script's opinion of it.
    """
    action = contain_action()
    pages_by_label = {view.label: view for view in context.pages}
    applied: list[dict] = []
    escalated: list[dict] = []
    refused: list[dict] = []
    for issue in issues:
        if issue.kind != page_bounds.KIND:
            continue
        candidate = react_actions.resolve(issue, pages_by_label)
        if candidate is None:
            refused.append({"ref": issue.paragraph_refs[0], "reason": "unresolved"})
            continue
        verdict = contain.admits(issue, candidate, action)
        if verdict != react_actions.ACCEPTED:
            refused.append(
                {
                    "page": issue.page,
                    "ref": candidate.reference,
                    "layout_label": issue.evidence.get("layout_label"),
                    "overflow_ratio": issue.evidence.get("overflow_ratio"),
                    "reason": verdict,
                }
            )
            continue
        outcome = contain.apply_one(candidate, action, min_iou)
        record = {
            "page": issue.page,
            "ref": candidate.reference,
            "layout_label": issue.evidence.get("layout_label"),
            "accepted": outcome.accepted,
            "reason": outcome.reason,
            "geometry": outcome.geometry,
            "text": detector_base.rendered_text(candidate.paragraph).strip()[:QUOTE],
        }
        (applied if outcome.accepted else escalated).append(record)
    return {
        "applied": applied,
        "escalated": escalated,
        "refused": refused,
        "min_scale": contain.min_scale(action),
        "margin_ratio": contain.margin_ratio(action),
        "collision_min_iou": min_iou,
    }


def containment_conservation(before, after, touched) -> dict:
    """What the containment changed outside the paragraphs it contained.

    The soul assertion, measured on the intermediate language rather than on the
    page: one digest per paragraph, and every paragraph the action did not name
    has to carry the digest it carried before.
    """
    moved = sorted(
        reference
        for reference, digest in after.items()
        if before.get(reference) != digest
    )
    return {
        "paragraphs": len(after),
        "touched": sorted(touched),
        "moved": moved,
        "moved_outside_touched": sorted(set(moved) - set(touched)),
        "shape_held": sorted(before) == sorted(after),
    }


# --- the arms ------------------------------------------------------------------


def pair_pages(left: Path, right: Path) -> dict[int, bool]:
    differs = {}
    with pymupdf.open(left) as first, pymupdf.open(right) as second:
        for index in range(min(first.page_count, second.page_count)):
            gray_left = render_diff.render_gray(first, index, RASTER_DPI)
            gray_right = render_diff.render_gray(second, index, RASTER_DPI)
            if gray_left.shape != gray_right.shape:
                differs[index + 1] = True
                continue
            delta = np.abs(gray_left.astype(np.int16) - gray_right.astype(np.int16))
            differs[index + 1] = bool((delta > RASTER_THRESHOLD).any())
    return differs


def repair_report(row: dict) -> dict | None:
    path = working_dir(row) / react.REPORT_NAME
    return load(path) if path.exists() else None


def loop_summary(row: dict) -> dict:
    report = repair_report(row)
    if report is None:
        return {"ran": False}
    chosen = []
    applications = []
    for iteration in report.get("iterations", ()):
        decision = iteration.get("decision") or {}
        chosen.append(f"{decision.get('action', 'none')}({len(decision.get('issue_ids', ()))})")
        for item in iteration.get("executed", ()):
            applications.append(
                {
                    "iteration": iteration["iteration"],
                    "ref": item["paragraph_ref"],
                    "accepted": item["accepted"],
                    "reason": item["reason"],
                    "geometry": item.get("geometry") or {},
                }
            )
    return {
        "ran": True,
        "iterations": len(report.get("iterations", ())),
        "chosen": chosen,
        "applications": report.get("applications"),
        "stopped_because": report.get("stopped_because"),
        "conservation": report.get("conservation"),
        "executed": applications,
        "escalated": [
            {
                "ref": item["paragraph_ref"],
                "reason": item["reason"],
                "issue_id": item["issue_id"],
            }
            for iteration in report.get("iterations", ())
            for item in iteration.get("applicability", ())
        ],
    }


def contained_by_loop(row: dict) -> list[dict]:
    """Every containment one run's own loop carried out, from its own sidecar.

    The geometry here was measured on the document the PDF was written from,
    which is what makes the crops beside it evidence about this action rather
    than about a document that resembles it.
    """
    report = repair_report(row)
    if report is None:
        return []
    found = []
    for iteration in report.get("iterations", ()):
        for item in iteration.get("executed", ()):
            geometry = item.get("geometry") or {}
            if "safe_box" not in geometry:
                continue
            found.append(
                {
                    "iteration": iteration["iteration"],
                    "issue_id": item["issue_id"],
                    "ref": item["paragraph_ref"],
                    "accepted": item["accepted"],
                    "reason": item["reason"],
                    "geometry": geometry,
                }
            )
    return found


def loop_refusals(row: dict) -> list[dict]:
    """Every finding one run's loop named and its rule then refused."""
    report = repair_report(row)
    if report is None:
        return []
    return [
        {
            "iteration": iteration["iteration"],
            "issue_id": item["issue_id"],
            "ref": item["paragraph_ref"],
            "reason": item["reason"],
        }
        for iteration in report.get("iterations", ())
        for item in iteration.get("applicability", ())
    ]


def site_crops(sample: str, rows: dict[str, dict], sites: list[dict]) -> list[dict]:
    """One before and one after crop per site the loop contained.

    The crop window is the union of where the paragraph was and where it landed,
    so the same region of the page is shown in both and the reader is comparing
    the page rather than two different windows onto it.
    """
    built = []
    if CONTAIN_ARM not in rows:
        return built
    for site in sites:
        geometry = site["geometry"]
        before = geometry.get("box_before")
        after = geometry.get("box_after") or before
        if before is None:
            continue
        window = [
            min(before[0], after[0]),
            min(before[1], after[1]),
            max(before[2], after[2]),
            max(before[3], after[3]),
        ]
        label = int(site["ref"].split("#")[0].removeprefix("p"))
        stem = f"{sample}.{site['ref'].replace('#', '_')}"
        built.append(
            {
                **site,
                "page": label,
                "window": [round(value, 2) for value in window],
                "before": crop(produced(rows[BASE_ARM]), label, window, f"{stem}.before"),
                "after": crop(
                    produced(rows[CONTAIN_ARM]), label, window, f"{stem}.after"
                ),
                "page_before": whole_page(
                    produced(rows[BASE_ARM]), label, f"{sample}.p{label}.before"
                ),
                "page_after": whole_page(
                    produced(rows[CONTAIN_ARM]), label, f"{sample}.p{label}.after"
                ),
            }
        )
    return built


def crop(pdf: Path, label: int, box, stem: str) -> str | None:
    """One paragraph's own area of a produced page, rasterised."""
    if not pdf.is_file() or box is None:
        return None
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as document:
        if label - 1 >= document.page_count:
            return None
        page = document[label - 1]
        height = page.rect.height
        clip = pymupdf.Rect(
            max(page.rect.x0, box[0] - CROP_MARGIN),
            max(page.rect.y0, height - box[3] - CROP_MARGIN),
            min(page.rect.x1, box[2] + CROP_MARGIN),
            min(page.rect.y1, height - box[1] + CROP_MARGIN),
        )
        page.get_pixmap(matrix=pymupdf.Matrix(CROP_SCALE, CROP_SCALE), clip=clip).save(
            RASTER_DIR / f"{stem}.png"
        )
    return (RASTER_DIR / f"{stem}.png").relative_to(ROOT).as_posix()


def whole_page(pdf: Path, label: int, stem: str) -> str | None:
    if not pdf.is_file():
        return None
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as document:
        if label - 1 >= document.page_count:
            return None
        document[label - 1].get_pixmap(
            matrix=pymupdf.Matrix(PAGE_SCALE, PAGE_SCALE)
        ).save(
            RASTER_DIR / f"{stem}.png"
        )
    return (RASTER_DIR / f"{stem}.png").relative_to(ROOT).as_posix()


# The pages the census section points a reader at, and the paragraph whose
# source form the masthead section compares against. Named here so every raster
# the report cites is one this script produced.
CENSUS_PAGES = {
    "CERNCourier-en": (3,),
    "Courier-zh": (8,),
    "Vogue-en": (3,),
}
SOURCE_CROP = {
    "CERNCourier-en": (1, "p1#2"),
}


def census_rasters(sample: str, rows: dict[str, dict], item: dict) -> dict:
    """The pages the census cites, and the source form of the headline paragraph."""
    built: dict[str, str] = {}
    for label in CENSUS_PAGES.get(sample, ()):
        path = whole_page(
            produced(rows[BASE_ARM]), label, f"{sample}.p{label}.census"
        )
        if path is not None:
            built[f"page {label}"] = path
    if sample in SOURCE_CROP:
        label, reference = SOURCE_CROP[sample]
        row = next(
            (entry for entry in item["out_of_page"] if entry["ref"] == reference), None
        )
        if row is not None and row.get("source_box"):
            path = crop(
                ROOT / "examples" / "input" / f"{sample}.pdf",
                label,
                row["source_box"],
                f"{sample}.{reference.replace('#', '_')}.source",
            )
            if path is not None:
                built[f"{reference} as the source drew it"] = path
    return built


def evidence_of(sample: str, rows: dict[str, dict]) -> dict:
    config = detector_config()
    base = rows[BASE_ARM]
    document, source, context, issues = measured(base)
    before = react.paragraph_digests(document)
    inventory = contain_inventory(document, context, issues, config.collision_min_iou)
    after = react.paragraph_digests(document)
    touched = [item["ref"] for item in inventory["applied"]]
    record = {
        "sample": sample,
        "arms": {arm: rows[arm]["pdf_sha256"] for arm in ARMS if arm in rows},
        "pages": rows[BASE_ARM]["input_pages"],
        "agreement": sidecar_agreement(base, issues),
        "counts": counts_of(issues),
        "pairs": classify_pairs(
            checkpoint(base, "typesetting"), source, config
        ),
        "out_of_page": out_of_page_rows(document, source, issues),
        "containment": inventory,
        "conservation": containment_conservation(before, after, touched),
        "loop": {arm: loop_summary(rows[arm]) for arm in ARMS if arm in rows},
        # What each arm had to ask the model for that the cache could not
        # answer. Any of it is a page that can render differently for a reason
        # that is not the switch, which is what the attribution floor is for and
        # what the evaluation protocol calls the pipeline's one unreplayable
        # channel.
        "api_calls": {arm: rows[arm]["api_calls"] for arm in ARMS if arm in rows},
        "requests": {arm: rows[arm]["requests"] for arm in ARMS if arm in rows},
    }
    if SUBJECT_ARM in rows and CONTROL_ARM in rows:
        subject = pair_pages(produced(base), produced(rows[SUBJECT_ARM]))
        control = pair_pages(produced(base), produced(rows[CONTROL_ARM]))
        record["raster"] = {
            "moved": [label for label, moved in subject.items() if moved],
            "control_moved": [label for label, moved in control.items() if moved],
        }
    record["census_rasters"] = census_rasters(sample, rows, record)
    if CONTAIN_ARM in rows:
        sites = contained_by_loop(rows[CONTAIN_ARM])
        record["loop_contained"] = site_crops(sample, rows, sites)
        record["loop_refused"] = loop_refusals(rows[CONTAIN_ARM])
        contained = pair_pages(produced(base), produced(rows[CONTAIN_ARM]))
        record.setdefault("raster", {})["contain_moved"] = [
            label for label, moved in contained.items() if moved
        ]
        record["contain_pages"] = sorted(
            {site["page"] for site in record["loop_contained"]}
        )
    return record


# The sample and the paragraph this batch was planned around, so the report can
# lead with it rather than leave a reader to find it in a corpus table.
HEADLINE_SAMPLE = "CERNCourier-en"
HEADLINE_REF = "p1#2"


# What the frozen fixture carries, and for which sample. The two checkpoints are
# what the census and the containment arithmetic are computed from -- the
# finished layout and the layout the source drew -- so a gate holding them can
# replay both without a run and without a credential.
FIXTURE_SAMPLE = HEADLINE_SAMPLE
FIXTURE_STAGES = ("styles_and_formulas", "typesetting")


def freeze(rows: dict[str, dict], sample: str, item: dict) -> list[str]:
    """The documents this batch's numbers were computed from, committed."""
    import zipfile

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    base = rows[BASE_ARM]
    archive = FIXTURE_DIR / f"{sample}.checkpoints.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for stage in FIXTURE_STAGES:
            path = working_dir(base) / f"{checkpoint_stem(stage)}.xml"
            if path.is_file():
                bundle.write(path, path.name)
    written.append(archive.relative_to(ROOT).as_posix())

    sidecar = working_dir(base) / detectors.REPORT_NAME
    if sidecar.is_file():
        path = FIXTURE_DIR / f"{sample}.{detectors.REPORT_NAME}"
        path.write_text(sidecar.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(path.relative_to(ROOT).as_posix())

    # What the shipped action answered on that document, so a gate can replay it
    # and compare rather than recompute an expectation of its own.
    path = FIXTURE_DIR / f"{sample}.containment.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "sample": sample,
                "arm": BASE_ARM,
                "checkpoints": [
                    f"{checkpoint_stem(stage)}.xml" for stage in FIXTURE_STAGES
                ],
                "counts": item["counts"],
                "out_of_page": item["out_of_page"],
                "containment": item["containment"],
                "pairs": item["pairs"],
                "conservation": item["conservation"],
            },
            f,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    written.append(path.relative_to(ROOT).as_posix())
    return written


# --- the report ----------------------------------------------------------------


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def fence(value) -> str:
    return f"`{value}`" if value not in (None, "") else "none"



def sample_of(evidence: dict, name: str) -> dict | None:
    for item in evidence["samples"]:
        if item["sample"] == name:
            return item
    return None


def contained_site(item: dict, reference: str) -> dict | None:
    for row in item["containment"]["applied"] + item["containment"]["escalated"]:
        if row["ref"] == reference:
            return row
    return None


def loop_containments(item: dict) -> list[dict]:
    """Every containment the loop itself carried out, arm by arm."""
    found = []
    for arm, summary in item["loop"].items():
        for application in summary.get("executed", ()):
            geometry = application.get("geometry") or {}
            if "safe_box" not in geometry:
                continue
            found.append({"arm": arm, **application})
    return found


def cost_rows(evidence: dict) -> list[list[str]]:
    rows = []
    for arm in ARMS:
        entries = evidence["arms"].get(arm) or []
        if not entries:
            continue
        rows.append(
            [
                arm,
                sum(row["requests"] for row in entries),
                sum(row["cache_hits"] for row in entries),
                sum(row["api_calls"] for row in entries),
                sum(row["prompt_tokens"] for row in entries),
                sum(row["completion_tokens"] for row in entries),
                round(sum(row["seconds"] for row in entries), 1),
            ]
        )
    return rows


def census_rows(evidence: dict) -> list[list[str]]:
    rows = []
    for item in evidence["samples"]:
        counts = {name: 0 for name in (CLASS_INDUCED, CLASS_DESIGN, CLASS_BELOW, CLASS_UNMATCHED)}
        for pair in item["pairs"]:
            counts[pair["class"]] += 1
        raised = sum(1 for pair in item["pairs"] if pair["raised"])
        rows.append(
            [
                item["sample"],
                item["pages"],
                len(item["pairs"]),
                counts[CLASS_INDUCED],
                counts[CLASS_DESIGN],
                counts[CLASS_BELOW],
                counts[CLASS_UNMATCHED],
                raised,
            ]
        )
    return rows


def design_rows(evidence: dict, floor: float) -> list[list[str]]:
    rows = []
    for item in evidence["samples"]:
        for pair in sorted(item["pairs"], key=lambda pair: -pair["iou"]):
            if pair["class"] == CLASS_INDUCED or pair["iou"] < floor:
                continue
            rows.append(
                [
                    item["sample"],
                    pair["page"],
                    ", ".join(f"`{ref}`" for ref in pair["refs"]),
                    "/".join(str(label) for label in pair["labels"]),
                    pair["iou"],
                    pair["source_iou"],
                    pair["covered"],
                    pair["source_covered"],
                    pair["class"],
                    " / ".join(f"`{text}`" for text in pair["text"]),
                ]
            )
    return rows


# How much of the smaller box has to be covered for a pair under the detector's
# bound to be worth listing in the report. A display floor for a table a human
# reads, not a threshold anything is judged by.
NEAR_MISS_COVERAGE = 0.5


def near_miss_rows(evidence: dict) -> list[list[str]]:
    """Pairs the detector does not raise where one text is largely under another."""
    rows = []
    for item in evidence["samples"]:
        for pair in sorted(item["pairs"], key=lambda pair: -pair["covered"]):
            if pair["raised"] or pair["covered"] < NEAR_MISS_COVERAGE:
                continue
            rows.append(
                [
                    item["sample"],
                    pair["page"],
                    ", ".join(f"`{ref}`" for ref in pair["refs"]),
                    "/".join(str(label) for label in pair["labels"]),
                    pair["iou"],
                    pair["covered"],
                    pair["source_covered"],
                    pair["class"],
                    " / ".join(f"`{text}`" for text in pair["text"]),
                ]
            )
    return rows


def out_of_page_table(evidence: dict) -> list[list[str]]:
    rows = []
    for item in evidence["samples"]:
        for row in item["out_of_page"]:
            rows.append(
                [
                    item["sample"],
                    row["page"],
                    f"`{row['ref']}`",
                    row["layout_label"],
                    row["side"],
                    row["overflow_points"],
                    row["overflow_ratio"],
                    row["source_overflow"],
                    row["added"],
                    row["origin"],
                    f"`{row['text']}`",
                ]
            )
    return rows


def containment_table(evidence: dict) -> tuple[list[list[str]], list[list[str]], list[list[str]]]:
    applied, escalated, refused = [], [], []
    for item in evidence["samples"]:
        for row in item["containment"]["applied"]:
            geometry = row["geometry"]
            applied.append(
                [
                    item["sample"],
                    row["page"],
                    f"`{row['ref']}`",
                    row["layout_label"],
                    geometry["state"],
                    geometry["scale"],
                    geometry["shift"],
                    geometry["box_before"],
                    geometry["box_after"],
                    max(geometry["overflow_after"].values()),
                    geometry.get("worst_overlap_after"),
                ]
            )
        for row in item["containment"]["escalated"]:
            geometry = row["geometry"]
            escalated.append(
                [
                    item["sample"],
                    row["page"],
                    f"`{row['ref']}`",
                    row["layout_label"],
                    row["reason"],
                    geometry.get("scale"),
                    geometry.get("min_scale"),
                ]
            )
        for row in item["containment"]["refused"]:
            refused.append(
                [
                    item["sample"],
                    row.get("page"),
                    f"`{row['ref']}`",
                    row.get("layout_label"),
                    row.get("overflow_ratio"),
                    row["reason"],
                ]
            )
    return applied, escalated, refused


def guard_table(evidence: dict) -> list[list[str]]:
    rows = []
    for item in evidence["samples"]:
        for row in item["containment"]["applied"] + item["containment"]["escalated"]:
            guard = (row["geometry"] or {}).get("guard") or {}
            if not guard:
                continue
            slide = guard.get(contain.STATE_TRANSLATED) or guard.get(contain.STATE_SCALED) or {}
            fallback = guard.get(contain.STATE_SCALED_IN_PLACE) or {}
            rows.append(
                [
                    item["sample"],
                    f"`{row['ref']}`",
                    guard.get("collision_min_iou"),
                    len(guard.get("standing_on_before") or ()),
                    len(slide.get("induced") or ()),
                    slide.get("worst_induced_iou"),
                    len(fallback.get("induced") or ()) if fallback else "n/a",
                    guard.get("slide_refused") or guard.get("fallback_refused") or "none",
                    len((guard.get("applied") or {}).get("induced") or ()),
                ]
            )
    return rows


def conservation_rows(evidence: dict) -> list[list[str]]:
    rows = []
    for item in evidence["samples"]:
        conservation = item["conservation"]
        rows.append(
            [
                item["sample"],
                conservation["paragraphs"],
                len(conservation["touched"]),
                ", ".join(f"`{ref}`" for ref in conservation["touched"]) or "none",
                len(conservation["moved"]),
                ", ".join(f"`{ref}`" for ref in conservation["moved_outside_touched"])
                or "none",
            ]
        )
    return rows


def loop_conservation_rows(evidence: dict) -> list[list[str]]:
    """Each arm's own conservation check, from the sidecar that arm wrote.

    The in run answer, and the only one of the three channels that is unaffected
    by what a request came back with: it compares the document the loop received
    against the document it produced, inside one run.
    """
    rows = []
    for item in evidence["samples"]:
        for arm in ARMS:
            summary = item["loop"].get(arm)
            if summary is None or not summary["ran"]:
                continue
            conservation = summary.get("conservation") or {}
            rows.append(
                [
                    item["sample"],
                    arm,
                    conservation.get("verdict"),
                    ", ".join(f"`{ref}`" for ref in conservation.get("touched_refs") or ())
                    or "none",
                    ", ".join(
                        f"`{ref}`"
                        for ref in conservation.get("changed_outside_touched") or ()
                    )
                    or "none",
                    conservation.get("paragraphs_before"),
                    conservation.get("paragraphs_after"),
                ]
            )
    return rows


def attribution_rows(evidence: dict) -> list[list[str]]:
    """The raster channel, with what could have moved a page other than the switch."""
    rows = []
    for item in evidence["samples"]:
        raster = item.get("raster") or {}
        contained = set(item.get("contain_pages") or ())
        floor = set(raster.get("control_moved") or ())
        unexplained = sorted(
            set(raster.get("contain_moved") or ()) - contained - floor
        )
        calls = item.get("api_calls") or {}
        rows.append(
            [
                item["sample"],
                sorted(contained) or "none",
                raster.get("control_moved") or "none",
                raster.get("contain_moved") or "none",
                unexplained or "none",
                calls.get(BASE_ARM),
                calls.get(CONTROL_ARM),
                calls.get(CONTAIN_ARM),
            ]
        )
    return rows


def loop_rows(evidence: dict) -> list[list[str]]:
    rows = []
    for item in evidence["samples"]:
        for arm in ARMS:
            summary = item["loop"].get(arm)
            if summary is None:
                continue
            if not summary["ran"]:
                rows.append([item["sample"], arm, "loop down", "-", "-", "-"])
                continue
            rows.append(
                [
                    item["sample"],
                    arm,
                    summary["iterations"],
                    "; ".join(summary["chosen"]) or "none",
                    summary["applications"],
                    summary["stopped_because"],
                ]
            )
    return rows


def write_report(evidence: dict) -> Path:
    config = evidence["detector_bounds"]
    headline = sample_of(evidence, HEADLINE_SAMPLE)
    lines: list[str] = []
    add = lines.append
    add("# B9.5 acceptance: the collision census and page containment")
    add("")
    add(
        "Three arms per sample over the whole corpus, the same stack in all three. "
        "The arm attribute is `magazine_repair`; the control repeats the off arm "
        "and is what says how much a run differs from itself."
    )
    add("")
    add(
        "Two instruments, and the report says which produced each number. The arms "
        "produce the pages and the pixels. The census and the containment "
        "inventory are computed by `analyze_b9_5.py`, which drives the shipped "
        "detectors and the shipped action over each run's own checkpoints: the "
        "loop's decision is by design not served from the cache, and a mechanism "
        "measured through a sampled decision is measured through the sampling too."
    )
    add("")
    add(
        f"Bounds in force: `collision_min_iou` {config['collision_min_iou']}, "
        f"`collision_source_min_iou` {config['collision_source_min_iou']}, "
        f"`page_safety_margin_ratio` {config['page_safety_margin_ratio']}, "
        f"`out_of_page_min_overflow_ratio` "
        f"{config['out_of_page_min_overflow_ratio']}, source layout read from the "
        f"`{config['source_geometry_stage']}` checkpoint."
    )
    add("")
    add("## Cost")
    add("")
    lines.extend(
        table(
            [
                "arm",
                "requests",
                "cache hits",
                "API calls",
                "prompt tokens",
                "completion tokens",
                "seconds",
            ],
            cost_rows(evidence),
        )
    )
    add("")

    add("## Which document the geometry is measured on")
    add("")
    add(
        "The finished geometry here is the `typesetting` checkpoint. The one pass "
        "between that checkpoint and the run's own detection is the heading "
        "policy, so the findings made here are compared against the `issues.json` "
        "each run wrote, and where they differ the difference is the heading "
        "policy and is stated rather than smoothed away."
    )
    add("")
    lines.extend(
        table(
            ["sample", "agrees", "counts here", "counts in the run's sidecar", "only here", "only there"],
            [
                [
                    item["sample"],
                    item["agreement"]["agrees"],
                    json.dumps(item["agreement"].get("counts_here"), sort_keys=True),
                    json.dumps(item["agreement"].get("counts_there"), sort_keys=True),
                    ", ".join(f"`{name}`" for name in item["agreement"].get("only_here") or ()) or "none",
                    ", ".join(f"`{name}`" for name in item["agreement"].get("only_there") or ()) or "none",
                ]
                for item in evidence["samples"]
            ],
        )
    )
    add("")

    add("## a. CERN Courier page 1, the masthead")
    add("")
    if headline is None:
        add("The sample was not run.")
    else:
        row = next(
            (item for item in headline["out_of_page"] if item["ref"] == HEADLINE_REF),
            None,
        )
        site = contained_site(headline, HEADLINE_REF)
        add(
            "F1 recorded this heading as drawn off the top of its own page and "
            "b9.2.2 found the cause: the typesetting stage anchors a paragraph's "
            "line spacing on the modal size of the units it holds, and this "
            "paragraph holds the masthead together with the issue date, the URL "
            "and the strapline. The heading path changed in b9.2, so the F1 "
            "measurement is void and the state is measured again here before "
            "anything is done about it."
        )
        add("")
        if row is not None:
            lines.extend(
                table(
                    [
                        "what",
                        "box",
                        "frame",
                        "past the frame",
                        "as a share of the axis",
                        "the source, past the same frame",
                        "added by the translation",
                    ],
                    [
                        [
                            f"`{row['ref']}` ({row['layout_label']}), side {row['side']}",
                            row["box"],
                            row["frame_box"],
                            row["overflow_points"],
                            row["overflow_ratio"],
                            row["source_overflow"],
                            row["added"],
                        ]
                    ],
                )
            )
            add("")
            add(
                f"Classification: **{row['origin']}**. The comparison is between "
                "the same quantity on both sides -- the extent of the boxes the "
                "characters are laid out in, which for a display line is the em "
                "box and not the visible ink -- so both figures are wider than "
                "what a reader sees being cut, and they are comparable to each "
                "other."
            )
            add("")
        rendered = next(
            (
                entry
                for entry in headline.get("loop_contained") or []
                if entry["ref"] == HEADLINE_REF
            ),
            None,
        )
        add("What containment does to it, and what a reader gets:")
        add("")
        rows_here = []
        if rendered is not None:
            geometry = rendered["geometry"]
            rows_here.append(
                [
                    "the scripted arm, on the document the PDF was written from",
                    rendered["reason"],
                    geometry.get("state", "-"),
                    geometry.get("scale"),
                    geometry.get("shift"),
                    geometry.get("box_before"),
                    geometry.get("box_after"),
                    max((geometry.get("overflow_after") or {"n": 0}).values()),
                ]
            )
        if site is not None:
            geometry = site["geometry"]
            rows_here.append(
                [
                    "this script, on the typesetting checkpoint",
                    site["reason"],
                    geometry.get("state", "-"),
                    geometry.get("scale"),
                    geometry.get("shift"),
                    geometry.get("box_before"),
                    geometry.get("box_after"),
                    max((geometry.get("overflow_after") or {"n": 0}).values()),
                ]
            )
        lines.extend(
            table(
                [
                    "measured on",
                    "outcome",
                    "state",
                    "scale",
                    "shift",
                    "box before",
                    "box after",
                    "worst overflow after",
                ],
                rows_here,
            )
        )
        add("")
        add(
            "The two rows differ by the heading policy, which runs between the "
            "checkpoint this script reads and the document the run detects and "
            "writes: the policy has already pulled the masthead part of the way "
            "back, and what containment then has to move is the remainder. Both "
            "land the ink inside the frame; the first is the one the pixels come "
            "from."
        )
        add("")
        add("Rasters, and every one of them is written by this script:")
        add("")
        for caption, path in sorted((headline.get("census_rasters") or {}).items()):
            if caption.startswith("page "):
                continue
            add(f"- {caption}: `{path}`")
        if rendered is not None:
            add(f"- the masthead as translated, before containment: `{rendered['before']}`")
            add(f"- the same, contained: `{rendered['after']}`")
            add(f"- the whole page before: `{rendered['page_before']}`")
            add(f"- the whole page contained: `{rendered['page_after']}`")
        add("")
    add("")

    add("## b. The corpus collision census")
    add("")
    add(
        "Every pair of texts that overlaps at all on a finished page, classified "
        "against the layout the source drew. A pair the source already overlapped "
        "at or above `collision_source_min_iou` is the designer's decision and is "
        "exempt; a pair the source did not, overlapping now at or above "
        "`collision_min_iou`, is raised; the rest are under the bound and are "
        "counted here so that the census can be read for near misses as well."
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "pages",
                "overlapping pairs",
                "induced",
                "source design",
                "below the bound",
                "no source counterpart",
                "raised as findings",
            ],
            census_rows(evidence),
        )
    )
    add("")
    add("### The overlaps the source already had, pair by pair")
    add("")
    add(
        "Everything at or above the bound the detector measures at, so what is "
        "listed is what the source exemption is carrying. Nothing here is a "
        "finding."
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "page",
                "paragraphs",
                "labels",
                "iou",
                "source iou",
                "covered",
                "source covered",
                "class",
                "text",
            ],
            design_rows(evidence, config["collision_min_iou"]),
        )
    )
    add("")

    add("### Where one text stands under another and no finding is made")
    add("")
    add(
        "The same pairs read by the other measure: the shared area over the area "
        "of the smaller box. A folio printed inside a contents entry covers "
        "almost all of itself and almost none of their union, so the "
        "intersection over union the detector is bounded by reports it as "
        "nothing. Listed at coverage "
        f"{NEAR_MISS_COVERAGE} and above, which is a floor for this table and "
        "not a threshold anything is judged by."
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "page",
                "paragraphs",
                "labels",
                "iou",
                "covered",
                "source covered",
                "class",
                "text",
            ],
            near_miss_rows(evidence),
        )
        or ["No pair covers that much of its smaller member."]
    )
    add("")

    add("### The pages behind the three cases this batch was asked to sort")
    add("")
    add(
        "Read against the tables above. The imposition slugs a printer's file "
        "carries are painted twice and are exempt by the source comparison; a "
        "contents page prints its folio inside the entry it numbers, and the "
        "measure the detector is bounded by does not see it; and a page the "
        "earlier review recorded as carrying three layers of text carries no "
        "overlapping pair at all in this build."
    )
    add("")
    for item in evidence["samples"]:
        for caption, path in sorted((item.get("census_rasters") or {}).items()):
            if not caption.startswith("page "):
                continue
            add(f"- `{item['sample']}` {caption}: `{path}`")
    add("")

    add("## The out of page inventory")
    add("")
    add(
        "Every out of page finding on the corpus, with what the same paragraph's "
        "source counterpart did against the same frame. `induced` is ink the "
        "source kept inside and the translation put out; `bleed the translation "
        "deepened` is a paragraph the source already ran past the trim and the "
        "translation ran further; `bleed` is one the translation did not worsen."
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "page",
                "paragraph",
                "label",
                "side",
                "past the frame",
                "share",
                "the source",
                "added",
                "class",
                "text",
            ],
            out_of_page_table(evidence),
        )
    )
    add("")

    add("## c. What containment did, site by site")
    add("")
    add(
        "The first instrument is the fourth arm. Its decision is scripted rather "
        "than sampled -- it names every out of page finding and lets the "
        "action's own rule decide which of them may be touched -- and everything "
        "downstream of the decision is the shipped path: the rule, the guard, "
        "the transform and the writer. It is the arm the pixels below come from, "
        "and it is not evidence about what the model chooses."
    )
    add("")
    for item in evidence["samples"]:
        sites = item.get("loop_contained") or []
        if not sites:
            continue
        add(f"### {item['sample']}")
        add("")
        lines.extend(
            table(
                [
                    "paragraph",
                    "iteration",
                    "accepted",
                    "reason",
                    "state",
                    "scale",
                    "shift",
                    "box before",
                    "box after",
                    "worst overflow after",
                ],
                [
                    [
                        f"`{site['ref']}`",
                        site["iteration"],
                        site["accepted"],
                        site["reason"],
                        site["geometry"].get("state", "-"),
                        site["geometry"].get("scale"),
                        site["geometry"].get("shift"),
                        site["geometry"].get("box_before"),
                        site["geometry"].get("box_after"),
                        max(
                            (site["geometry"].get("overflow_after") or {"n": 0}).values()
                        ),
                    ]
                    for site in sites
                ],
            )
        )
        add("")
        for site in sites:
            add(
                f"- `{site['ref']}` page {site['page']}: before `{site['before']}`, "
                f"after `{site['after']}`; the whole page before "
                f"`{site['page_before']}`, after `{site['page_after']}`"
            )
        add("")
    add("### The same action driven over every finding of the corpus")
    add("")
    applied, escalated, refused = containment_table(evidence)
    add(
        "The second instrument, which reaches the findings the arm's own run did "
        "not: the action driven from `analyze_b9_5.py` over every out of page "
        "finding, each held against its own rule first. What it applied:"
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "page",
                "paragraph",
                "label",
                "state",
                "scale",
                "shift",
                "box before",
                "box after",
                "worst overflow after",
                "worst overlap after",
            ],
            applied,
        )
        if applied
        else ["Nothing was applied."]
    )
    add("")
    add("What it escalated:")
    add("")
    lines.extend(
        table(
            ["sample", "page", "paragraph", "label", "reason", "scale it would have needed", "floor"],
            escalated,
        )
        if escalated
        else ["Nothing was escalated."]
    )
    add("")
    add("What its rule refused before it looked at the geometry:")
    add("")
    lines.extend(
        table(
            ["sample", "page", "paragraph", "label", "overflow ratio", "reason"],
            refused,
        )
        if refused
        else ["Nothing was refused."]
    )
    add("")
    add("### What the arm's own loop refused, which is the escalation list")
    add("")
    lines.extend(
        table(
            ["sample", "paragraph", "finding", "reason"],
            [
                [
                    item["sample"],
                    f"`{row['ref']}`",
                    f"`{row['issue_id']}`",
                    row["reason"],
                ]
                for item in evidence["samples"]
                for row in item.get("loop_refused") or []
            ],
        )
        or ["The arm was not run."]
    )
    add("")

    add("### The guard")
    add("")
    add(
        "Every plan measured against the page it would be applied to, before it "
        "was applied: what the paragraph stands on now, what each plan would "
        "newly stand on, and what the applied transform actually landed on."
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "paragraph",
                "bound",
                "standing on before",
                "the slide would induce",
                "worst iou it would induce",
                "the fallback would induce",
                "refused",
                "induced after applying",
            ],
            guard_table(evidence),
        )
    )
    add("")
    fired = [
        row
        for item in evidence["samples"]
        for row in item["containment"]["applied"] + item["containment"]["escalated"]
        if ((row["geometry"] or {}).get("guard") or {}).get("slide_refused")
        or ((row["geometry"] or {}).get("guard") or {}).get("fallback_refused")
    ]
    add(
        f"The guard refused nothing on this corpus: {len(fired)} of the "
        f"containments planned here had a plan turned down, because neither "
        f"heading had anything standing where it was going. That is the corpus "
        f"answering rather than the mechanism being untested -- the fallback "
        f"chain is driven end to end by the synthetic cases in "
        f"`spec_checks/spec_check_b9_5.py`, which build a page where the slide "
        f"lands on a neighbour and the shrink in place does not, and one where "
        f"neither is clear and the finding is escalated with the paragraph left "
        f"exactly as it was."
    )
    add("")

    add("### What the loop itself did")
    add("")
    add(
        "The arms, for comparison: the loop asks a model which findings to act "
        "on and that request is not served from the cache, so this is what was "
        "sampled on these runs rather than what the loop will do on the next one."
    )
    add("")
    lines.extend(
        table(
            ["sample", "arm", "iterations", "action and findings chosen", "applications", "stopped because"],
            loop_rows(evidence),
        )
    )
    add("")
    carried = loop_containments(sample_of(evidence, HEADLINE_SAMPLE) or {"loop": {}})
    if carried:
        add("Containments the loop carried out end to end:")
        add("")
        lines.extend(
            table(
                ["arm", "iteration", "paragraph", "accepted", "reason"],
                [
                    [
                        row["arm"],
                        row["iteration"],
                        f"`{row['ref']}`",
                        row["accepted"],
                        row["reason"],
                    ]
                    for row in carried
                ],
            )
        )
        add("")

    add("## d. Outside the contained paragraphs")
    add("")
    add(
        "The soul assertion, on three channels, because they fail differently "
        "and only one of them is clean of the sampling."
    )
    add("")
    add(
        "**In the run.** Each arm's loop compares the document it received "
        "against the document it produced and writes the verdict into its own "
        "sidecar. Nothing about a request's answer can move this: it is one "
        "document measured against itself inside one process."
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "arm",
                "verdict",
                "touched",
                "changed outside the touched set",
                "paragraphs before",
                "paragraphs after",
            ],
            loop_conservation_rows(evidence),
        )
    )
    add("")
    add(
        "**On the intermediate language, outside the loop.** One digest per "
        "paragraph before and after the action was driven over the base arm's "
        "document by `analyze_b9_5.py`, so the claim covers the findings the "
        "arm's own run did not reach."
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "paragraphs",
                "contained",
                "which",
                "paragraphs changed",
                "changed outside the contained set",
            ],
            conservation_rows(evidence),
        )
    )
    add("")
    add(
        "**On the page, with the attribution floor.** What the scripted arm "
        "renders differently from the base arm, against what the control arm -- "
        "which repeats the base arm exactly -- renders differently from it. The "
        "last three columns are why a floor is needed at all: a request the "
        "cache could not answer is sampled again, and a resampled translation "
        "is a page that renders differently for a reason that is not this "
        "batch's. The unexplained column is the one that would be a finding, and "
        "the report says plainly where a sample's floor is too wide for this "
        "channel to attribute anything."
    )
    add("")
    lines.extend(
        table(
            [
                "sample",
                "pages contained on",
                "moved, control vs off",
                "moved, contain vs off",
                "moved and neither contained nor within the floor",
                "API calls, off",
                "control",
                "contain",
            ],
            attribution_rows(evidence),
        )
    )
    add("")
    for item in evidence["samples"]:
        raster = item.get("raster") or {}
        contained = set(item.get("contain_pages") or ())
        floor = set(raster.get("control_moved") or ())
        unexplained = sorted(set(raster.get("contain_moved") or ()) - contained - floor)
        if not unexplained:
            continue
        calls = (item.get("api_calls") or {}).get(CONTAIN_ARM)
        conservation = (item["loop"].get(CONTAIN_ARM) or {}).get("conservation") or {}
        add(
            f"- `{item['sample']}` pages {unexplained}: the scripted arm "
            f"contained nothing on this sample -- its loop's own record names "
            f"{conservation.get('touched_refs') or 'no paragraph'} as touched -- "
            f"and it made {calls} request(s) the cache could not answer. A "
            f"resampled translation is what these pages differ by, and it is the "
            f"channel the evaluation protocol already records as unreplayable."
        )
    add("")

    add("## e. The frozen fixture")
    add("")
    add(
        "The documents every geometric number above was computed from, so the "
        "census and the containment can be replayed from committed files rather "
        "than from a run."
    )
    add("")
    for path in evidence.get("fixture") or []:
        add(f"- `{path}`")
    add("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return REPORT


def main() -> int:
    rows = rows_by_sample()
    if not rows:
        print("no arm has been run yet")
        return 1
    config = detector_config()
    evidence = {
        "arms": {arm: ledger(arm) for arm in ARMS},
        "detector_bounds": {
            "collision_min_iou": config.collision_min_iou,
            "collision_source_min_iou": config.collision_source_min_iou,
            "page_safety_margin_ratio": config.page_safety_margin_ratio,
            "out_of_page_min_overflow_ratio": config.out_of_page_min_overflow_ratio,
            "source_geometry_stage": config.source_geometry_stage,
        },
        "samples": [evidence_of(sample, arms) for sample, arms in sorted(rows.items())],
    }
    frozen = sample_of(evidence, FIXTURE_SAMPLE)
    if frozen is not None:
        evidence["fixture"] = freeze(rows[FIXTURE_SAMPLE], FIXTURE_SAMPLE, frozen)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with EVIDENCE.open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)
    print(f"wrote {EVIDENCE.relative_to(ROOT)}")
    print(f"wrote {write_report(evidence).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
