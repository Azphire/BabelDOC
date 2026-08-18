"""B9.4 acceptance analysis: what consuming the drop cap ruling changed.

Reads the three arms this batch ran and writes ``evidence.json``, ``report.md``
and the rasters the report points at. Every number here is computed from the
arms' own artefacts -- the checkpoints, the sidecars, the translator's tracking
file and the produced PDFs -- and nothing is copied from a previous session.

Four questions, in order.

a. The ruled sites. For each paragraph a verdict reached: what the translator was
   offered in each arm, what came back, whether the initial is still standing in
   the source script, and how large the largest glyph of the paragraph's opening
   is after the document has been laid out. That last number is the one the
   typographic claim rests on, and it is read off the finished document rather
   than off the merge.

b. Outside the ruled paragraphs. Page by page, in the intermediate language and
   on the rendered page, with the control arm as the floor: a page the switch is
   blamed for has to be a page the control reproduced. The two document level
   channels b9.3 measured are checked rather than assumed -- the automatic
   glossary is compared entry by entry between the arms, and the batch
   composition is compared request by request.

c. The candidate the F1 review found and the marking pass used to miss, on
   FD-en-v2 page 8. Nobody has ruled it, so what acted on it is the default its
   target language declares; the draft for the ruling is written beside this by
   ``export_candidates.py``.

d. Vogue-en page 3, where F1 recorded two Latin residues. Read from the frozen
   b9.3 run rather than by running it again: the question there is whether the
   candidate signal reaches those paragraphs at all, which is a question about
   the document and not about a switch.

Usage:
    python analyze_b9_4.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import zipfile
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402

from tools import render_diff  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b9_4"
RASTER_DIR = OUT_DIR / "raster"
FIXTURE_DIR = OUT_DIR / "fixtures"
EVIDENCE = OUT_DIR / "evidence.json"
REPORT = OUT_DIR / "report.md"

# The frozen b9.3 arm the Vogue observation is read from, which is the last run
# that put the line structure switch up on that sample.
VOGUE_WORK = (
    ROOT / "examples" / "output" / "b9_3" / "on" / "Vogue-en" / "work" / "Vogue-en"
)
VOGUE_PAGE = 3

ARMS = ("off", "control", "on")
SUBJECT_ARM = "on"
BASE_ARM = "off"
CONTROL_ARM = "control"

# How a page raster is compared, at the settings the render diff tool ships.
RASTER_DPI = 110
RASTER_THRESHOLD = 12
CROP_SCALE = 2.0
# How far around a paragraph box a crop reaches, in points, so the reader sees
# the initial in the column it stands in.
CROP_MARGIN = 18.0

# How much of a paragraph's opening the report quotes.
QUOTE = 46

LATIN = re.compile(r"[A-Za-z]")


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def ledger(arm: str) -> list[dict]:
    return load(OUT_DIR / f"runs.{arm}.json")


def rows_by_sample() -> dict[str, dict[str, dict]]:
    found: dict[str, dict[str, dict]] = {}
    for arm in ARMS:
        for row in ledger(arm):
            sample = row["sample"].removesuffix(".pdf")
            found.setdefault(sample, {})[arm] = row
    return found


def working_dir(row: dict) -> Path:
    return ROOT / row["working_dir"]


def produced(row: dict) -> Path:
    return ROOT / row["pdf"]


_documents: dict[tuple[str, str], object] = {}


def checkpoint(row: dict, stage: str):
    """One arm's document at one stage, read once per run of this script."""
    key = (row["working_dir"], stage)
    if key not in _documents:
        _documents[key] = load_checkpoint(
            working_dir(row) / f"{checkpoint_stem(stage)}.xml"
        )
    return _documents[key]


def debug_id_of(row: dict, reference: str) -> str | None:
    """The identity one arm minted for the paragraph a reference names.

    A debug id is minted afresh on every run, which is why a ruling is written in
    references -- a page and a position -- rather than in identities. So the
    reference is what carries between the arms, and each arm's own identity is
    looked up from it here, at the stage the ruling was applied at.
    """
    document = checkpoint(row, "chain_builder")
    for label, page in hitl.labeled_pages(document):
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            if drop_cap.paragraph_reference(label, index) == reference:
                return paragraph.debug_id
    return None


def apply_report(row: dict) -> dict | None:
    path = working_dir(row) / drop_cap.APPLY_REPORT_NAME
    return load(path) if path.is_file() else None


def mark_report(row: dict) -> dict | None:
    path = working_dir(row) / drop_cap.REPORT_NAME
    return load(path) if path.is_file() else None


def glossary_entries(row: dict) -> list[str]:
    path = working_dir(row) / "auto_extractor_glossary.csv"
    if not path.is_file():
        return []
    return sorted(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def tracking(row: dict) -> dict:
    path = working_dir(row) / hitl.TRACKING_NAME
    return load(path) if path.is_file() else {}


def tracking_records(row: dict) -> list[dict]:
    payload = tracking(row)
    records = []
    for name in ("cross_page", "cross_column", "page"):
        for holder in payload.get(name) or ():
            for item in holder.get("paragraph") or ():
                records.append({"section": name, **item})
    return records


def batch_composition(row: dict) -> list[list[str]]:
    """Which paragraph openings each request was built from, request by request.

    The second of the two channels b9.3 measured. Two arms whose requests are
    composed of the same paragraphs in the same order cannot carry a change from
    one page to another by that route.
    """
    payload = tracking(row)
    built = []
    for name in ("cross_page", "cross_column", "page"):
        for holder in payload.get(name) or ():
            built.append(
                [
                    # Space insensitive: the only text the merge changes is the
                    # separator it drops, so a fingerprint that counted spaces
                    # would report the merge itself as a regrouping.
                    "".join((item.get("pdf_unicode") or "").split())[:32]
                    for item in holder.get("paragraph") or ()
                ]
            )
    return built


def offered_for(row: dict, openings: list[str]) -> dict | None:
    """The request record whose rendering opens with one of the texts given."""
    for record in tracking_records(row):
        rendered = record.get("pdf_unicode") or ""
        for opening in openings:
            if opening and rendered.startswith(opening[: min(len(opening), 30)]):
                return record
    return None


def paragraph_by_debug_id(document, debug_id: str):
    for label, page in hitl.labeled_pages(document):
        for paragraph in page.pdf_paragraph or ():
            if paragraph.debug_id == debug_id:
                return label, paragraph
    return None, None


def character_sizes(paragraph) -> list[float]:
    """Every character size of one paragraph, whatever composition holds them.

    The typesetting stage lays a paragraph out as one composition per character,
    which is a shape neither the candidate signal nor the merge ever sees, so the
    characters are collected through the walker that handles every kind.
    """
    return [
        float(character.pdf_style.font_size)
        for character in line_split.paragraph_characters(paragraph)
        if character.pdf_style is not None and character.pdf_style.font_size
    ]


def opening_glyph(paragraph) -> float | None:
    """The size of the paragraph's first character.

    The measure of the typographic claim, read off the finished document: a drop
    cap that survived is the first character of its paragraph set several times the
    body size, and a paragraph whose first character is body sized has none.
    """
    sizes = character_sizes(paragraph)
    return round(sizes[0], 2) if sizes else None


def paragraph_median_glyph(paragraph) -> float | None:
    sizes = character_sizes(paragraph)
    return round(statistics.median(sizes), 2) if sizes else None


def opening_text(paragraph) -> str:
    return (paragraph.unicode or "")[:QUOTE]


def leading_script(paragraph) -> str:
    """Whether the paragraph opens in the source script, in one word."""
    text = (paragraph.unicode or "").lstrip()
    if not text:
        return "empty"
    return "latin" if LATIN.match(text[0]) else "target"


# --- a. the ruled sites ---------------------------------------------------------


def site_rows(sample: str, rows: dict[str, dict]) -> list[dict]:
    """One row per paragraph a verdict reached in the arm with the switch up."""
    report = apply_report(rows[SUBJECT_ARM])
    if report is None:
        return []
    built = []
    for decision in report["decisions"]:
        debug_id = decision["debug_id"]
        site = {
            "sample": sample,
            "paragraph": decision["paragraph"],
            "page": decision["page"],
            "debug_id": debug_id,
            "decision": decision["decision"],
            "source": decision["source"],
            "was_candidate": decision["was_candidate"],
            "initial": decision["initial"],
            "size_ratio": decision["size_ratio"],
            "merged": decision["merged"],
            "separator_dropped": decision["separator_dropped"],
            "unicode_before": decision["unicode_before"][:QUOTE],
            "unicode_after": decision["unicode_after"][:QUOTE],
        }
        openings = [decision["unicode_before"], decision["unicode_after"]]
        for arm in (BASE_ARM, SUBJECT_ARM):
            identity = debug_id_of(rows[arm], decision["paragraph"]) or debug_id
            site[f"debug_id_{arm}"] = identity
            record = offered_for(rows[arm], openings)
            site[f"offered_{arm}"] = (
                None if record is None else (record.get("input") or "")[:QUOTE]
            )
            site[f"placeholders_{arm}"] = (
                None if record is None else len(record.get("placeholders") or ())
            )
            translated = checkpoint(rows[arm], "il_translated")
            _, paragraph = paragraph_by_debug_id(translated, identity)
            site[f"translated_{arm}"] = (
                None if paragraph is None else opening_text(paragraph)
            )
            site[f"opens_in_{arm}"] = (
                None if paragraph is None else leading_script(paragraph)
            )
            typeset = checkpoint(rows[arm], "typesetting")
            _, laid = paragraph_by_debug_id(typeset, identity)
            site[f"opening_glyph_{arm}"] = None if laid is None else opening_glyph(laid)
            site[f"median_glyph_{arm}"] = (
                None if laid is None else paragraph_median_glyph(laid)
            )
            site[f"box_{arm}"] = None if laid is None or laid.box is None else [
                round(laid.box.x, 2),
                round(laid.box.y, 2),
                round(laid.box.x2, 2),
                round(laid.box.y2, 2),
            ]
        built.append(site)
    return built


def crop(row: dict, label: int, box: list[float], stem: str) -> str | None:
    """One paragraph's own area of the produced page, rasterised."""
    pdf = produced(row)
    if not pdf.is_file() or box is None:
        return None
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as document:
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


# --- b. outside the ruled paragraphs -------------------------------------------


def translated_text(row: dict) -> dict[int, list[str]]:
    document = checkpoint(row, "il_translated")
    return {
        label: [paragraph.unicode or "" for paragraph in page.pdf_paragraph or ()]
        for label, page in hitl.labeled_pages(document)
    }


def pair_pages(left: Path, right: Path) -> dict[int, bool]:
    """Page by page, whether two produced PDFs differ at all."""
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


def spill(sample: str, rows: dict[str, dict], sites: list[dict]) -> dict:
    """Which pages moved, which of them a verdict stands on, and by what route."""
    ruled_pages = sorted({site["page"] for site in sites})
    texts = {arm: translated_text(rows[arm]) for arm in ARMS}
    pages = sorted(texts[BASE_ARM])
    text_moved = [
        label
        for label in pages
        if texts[BASE_ARM].get(label) != texts[SUBJECT_ARM].get(label)
    ]
    control_moved = [
        label
        for label in pages
        if texts[BASE_ARM].get(label) != texts[CONTROL_ARM].get(label)
    ]
    raster = pair_pages(produced(rows[BASE_ARM]), produced(rows[SUBJECT_ARM]))
    raster_control = pair_pages(produced(rows[BASE_ARM]), produced(rows[CONTROL_ARM]))
    raster_moved = [label for label, moved in raster.items() if moved]
    raster_control_moved = [label for label, moved in raster_control.items() if moved]

    glossary = {arm: glossary_entries(rows[arm]) for arm in ARMS}
    composition = {arm: batch_composition(rows[arm]) for arm in ARMS}
    outside = [label for label in raster_moved if label not in ruled_pages]
    resolved = {
        arm: resolved_by_page(repair_report(rows[arm])) for arm in ARMS
    }
    exceptions = []
    for label in outside:
        base_resolved = resolved[BASE_ARM].get(label, [])
        subject_resolved = resolved[SUBJECT_ARM].get(label, [])
        attribution = []
        if label not in text_moved:
            attribution.append("the translated document is identical on this page")
        if set(base_resolved) != set(subject_resolved):
            attribution.append(
                "the repair loop resolved "
                f"{sorted(set(base_resolved) - set(subject_resolved))} in the base arm "
                f"and {sorted(set(subject_resolved) - set(base_resolved))} in the "
                "subject arm, on an uncached decision"
            )
        exceptions.append(
            {
                "page": label,
                "text_moved": label in text_moved,
                "control_moved": label in control_moved,
                "control_raster_moved": label in raster_control_moved,
                "repair_resolved_base": base_resolved,
                "repair_resolved_subject": subject_resolved,
                "attribution": attribution,
            }
        )
    return {
        "sample": sample,
        "ruled_pages": ruled_pages,
        "pages": len(pages),
        "raster_exceptions": exceptions,
        "text_moved": text_moved,
        "text_moved_outside_ruled": [
            label for label in text_moved if label not in ruled_pages
        ],
        "control_text_moved": control_moved,
        "raster_moved": raster_moved,
        "raster_moved_outside_ruled": [
            label for label in raster_moved if label not in ruled_pages
        ],
        "control_raster_moved": raster_control_moved,
        "attributable": [
            label for label in text_moved if label not in control_moved
        ],
        # The two document level channels, measured rather than assumed.
        "glossary_entries": {arm: len(glossary[arm]) for arm in ARMS},
        "glossary_identical": glossary[BASE_ARM] == glossary[SUBJECT_ARM],
        "glossary_changed_entries": len(
            set(glossary[BASE_ARM]) ^ set(glossary[SUBJECT_ARM])
        ),
        "batches": {arm: len(composition[arm]) for arm in ARMS},
        "batch_composition_identical": composition[BASE_ARM] == composition[SUBJECT_ARM],
    }


def issues_of(row: dict) -> dict:
    path = working_dir(row) / "issues.json"
    return load(path) if path.is_file() else {}


def detector_inventory(sample: str, rows: dict[str, dict], sites: list[dict]) -> dict:
    """What this project's own detectors report, arm by arm.

    The F1 review recorded the drop cap defects by eye: an initial drawn on top of
    a section chip, another colliding with run-in text, a Latin initial overlapping
    the line below it. Whether the detectors see them is a separate question from
    whether they are there, and both answers belong here: the counts say what
    changed between the arms, and the last column says whether any finding names
    the paragraph a verdict acted on at all.
    """
    ruled_pages = sorted({site["page"] for site in sites})
    ruled_ids = {site["debug_id"] for site in sites}
    ruled_refs = {site["paragraph"] for site in sites}
    per_arm = {}
    for arm in ARMS:
        payload = issues_of(rows[arm])
        issues = payload.get("issues") or []
        by_kind: dict[str, int] = {}
        on_ruled: dict[str, int] = {}
        naming = []
        for issue in issues:
            kind = issue.get("detector") or "unknown"
            by_kind[kind] = by_kind.get(kind, 0) + 1
            page = issue.get("page")
            if page in ruled_pages:
                on_ruled[kind] = on_ruled.get(kind, 0) + 1
            evidence_ids = set((issue.get("evidence") or {}).get("debug_ids") or ())
            refs = set(issue.get("paragraph_refs") or ())
            if (evidence_ids & ruled_ids) or (refs & ruled_refs):
                naming.append({"detector": kind, "id": issue.get("id")})
        per_arm[arm] = {
            "issues": len(issues),
            "by_kind": by_kind,
            "on_ruled_pages": on_ruled,
            "naming_a_ruled_paragraph": naming,
            "detectors_that_ran": sorted(payload.get("pages_by_detector") or {}),
        }
    return {"sample": sample, "ruled_pages": ruled_pages, "arms": per_arm}


def repair_report(row: dict) -> dict:
    path = working_dir(row) / "react_repair.report.json"
    return load(path) if path.is_file() else {}


def resolved_by_page(report: dict) -> dict[int, list[str]]:
    """Which findings the repair loop resolved, by the page they stood on.

    A finding id carries its page, which is what lets a rendered difference on a
    page the merge never touched be attributed to the loop rather than to the
    switch.
    """
    found: dict[int, list[str]] = {}
    for item in report.get("iterations") or ():
        for identifier in item.get("resolved_ids") or ():
            parts = identifier.split(":")
            if len(parts) < 2 or not parts[1].startswith("p"):
                continue
            try:
                page = int(parts[1][1:])
            except ValueError:
                continue
            found.setdefault(page, []).append(identifier)
    return {page: sorted(items) for page, items in found.items()}


def repair_comparison(sample: str, rows: dict[str, dict]) -> dict:
    """The repair loop's own answer, arm by arm.

    Here because it is where a page outside a ruled one moved. The loop asks a
    model which findings to act on and that request is not served from the cache,
    so two runs of one configuration can choose differently -- and a finding the
    loop repaired in one arm and left in another is a rendered difference on a page
    the merge never touched. The detector finding sets are compared as well, since
    a finding that appears only in one arm is the trace the repair left rather than
    a difference the detectors found.
    """
    per_arm = {}
    for arm in ARMS:
        report = repair_report(rows[arm])
        issues = issues_of(rows[arm])
        per_arm[arm] = {
            "iterations": report.get("iterations_run"),
            "stopped_because": report.get("stopped_because"),
            "applications": report.get("applications"),
            "decisions": [
                {
                    "iteration": item.get("iteration"),
                    "action": (item.get("decision") or {}).get("action"),
                    "issue_ids": (item.get("decision") or {}).get("issue_ids"),
                    "from_cache": (item.get("decision") or {}).get("from_cache"),
                    "executed": item.get("executed"),
                    "resolved_ids": item.get("resolved_ids"),
                    "outcome": item.get("outcome"),
                }
                for item in (report.get("iterations") or [])
            ],
            "finding_ids": sorted(item["id"] for item in issues.get("issues") or []),
            "resolved_by_page": resolved_by_page(report),
        }
    base = set(per_arm[BASE_ARM]["finding_ids"])
    return {
        "sample": sample,
        "arms": {
            arm: {
                key: value
                for key, value in per_arm[arm].items()
                if key != "finding_ids"
            }
            | {
                "findings": len(per_arm[arm]["finding_ids"]),
                "findings_only_here": sorted(set(per_arm[arm]["finding_ids"]) - base),
                "findings_missing_here": sorted(base - set(per_arm[arm]["finding_ids"])),
            }
            for arm in ARMS
        },
        "decision_served_from_cache": sorted(
            {
                bool(item["from_cache"])
                for arm in ARMS
                for item in per_arm[arm]["decisions"]
            }
        ),
        "control_chose_the_same_as_off": (
            per_arm[BASE_ARM]["decisions"] == per_arm[CONTROL_ARM]["decisions"]
        ),
    }


# --- c and d. the candidates ----------------------------------------------------


def candidate_rows(sample: str, rows: dict[str, dict]) -> list[dict]:
    report = mark_report(rows[SUBJECT_ARM])
    if report is None:
        return []
    return [
        {
            "sample": sample,
            "paragraph": item["paragraph"],
            "page": item["page"],
            "article_id": item["article_id"],
            "body_rank": item["body_rank"],
            "opens_article": item["opens_article"],
            "size_ratio": item["size_ratio"],
            "first_run": item["first_run"],
            "excerpt": item["excerpt"][:QUOTE],
            "ruled": (rows[SUBJECT_ARM]["ruling"]["drop_caps"] or {}).get(
                item["paragraph"]
            ),
        }
        for item in report["candidates"]
    ]


def vogue_observation() -> dict:
    """What the candidate signal sees on the page F1 recorded two residues on.

    Read from the frozen b9.3 arm. The two residues are Latin fragments standing
    where a drop cap was, and the question is whether they are paragraphs the
    signal can reach: a fragment belonging to no article, or labelled as anything
    but running text, is outside the signal by construction and not by threshold.
    """
    checkpoint_path = VOGUE_WORK / f"{checkpoint_stem('chain_builder')}.xml"
    map_path = VOGUE_WORK / "article_map.json"
    split_path = VOGUE_WORK / line_split.REPORT_NAME
    if not checkpoint_path.is_file() or not map_path.is_file():
        return {"available": False, "reason": f"{checkpoint_path} is not in the workspace"}
    settings = drop_cap.load_drop_cap_config()
    labels = drop_cap.body_labels()
    document = load_checkpoint(checkpoint_path)
    article_of_page, openers = drop_cap.read_article_map(map_path)
    labeled = hitl.labeled_pages(document)
    candidates = {
        item.reference
        for item in drop_cap.find_candidates(
            labeled, article_of_page, openers, settings, labels
        )
    }
    residues = []
    for label, page in labeled:
        if label != VOGUE_PAGE:
            continue
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            text = (paragraph.unicode or "").strip()
            if not text or len(text) > 4 or not LATIN.match(text[0]):
                continue
            run = drop_cap.leading_run(paragraph, settings.initial_size_tolerance)
            median = drop_cap.median_font_size(paragraph)
            reference = drop_cap.paragraph_reference(label, index)
            reasons = []
            if paragraph.layout_label not in labels:
                reasons.append(f"labelled {paragraph.layout_label}")
            if article_of_page.get(label) is None:
                reasons.append("page belongs to no article")
            if run is not None and median:
                if run.size / median < settings.min_first_run_size_ratio:
                    reasons.append(
                        f"ratio {round(run.size / median, 2)} below "
                        f"{settings.min_first_run_size_ratio}"
                    )
            else:
                reasons.append("no leading run or no median size")
            residues.append(
                {
                    "paragraph": reference,
                    "text": text,
                    "label": paragraph.layout_label,
                    "characters": len(text),
                    "is_candidate": reference in candidates,
                    "reasons": reasons,
                }
            )
    split = load(split_path) if split_path.is_file() else None
    return {
        "available": True,
        "source": VOGUE_WORK.relative_to(ROOT).as_posix(),
        "page": VOGUE_PAGE,
        "candidates_on_page": sorted(
            item for item in candidates if item.startswith(f"p{VOGUE_PAGE}#")
        ),
        "residues": residues,
        "line_split_declared": (
            None
            if split is None
            else [item["page"] for item in split["pages"] if item["declared"]]
        ),
    }


# --- the fixture ----------------------------------------------------------------


def freeze(rows: dict[str, dict], sample: str) -> list[str]:
    """The arm's own answer, committed: the sidecar and the state it acted on."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    report = apply_report(rows[SUBJECT_ARM])
    if report is not None:
        path = FIXTURE_DIR / f"{sample}.{drop_cap.APPLY_REPORT_NAME}"
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
        written.append(path.relative_to(ROOT).as_posix())
    marks = mark_report(rows[SUBJECT_ARM])
    if marks is not None:
        path = FIXTURE_DIR / f"{sample}.{drop_cap.REPORT_NAME}"
        with path.open("w", encoding="utf-8") as f:
            json.dump(marks, f, indent=2, sort_keys=True, ensure_ascii=False)
        written.append(path.relative_to(ROOT).as_posix())
    # The document as the merge found it, so the mechanics can be replayed from a
    # committed file rather than from a run.
    source = working_dir(rows[SUBJECT_ARM]) / f"{checkpoint_stem('chain_builder')}.xml"
    if source.is_file():
        archive = FIXTURE_DIR / f"{sample}.checkpoints.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(source, source.name)
        written.append(archive.relative_to(ROOT).as_posix())
    return written


# --- the report -----------------------------------------------------------------


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return lines


def write_report(evidence: dict) -> Path:
    lines = [
        "# B9.4 acceptance: the drop cap ruling, consumed",
        "",
        "Three arms per sample, the same stack in all three. Two of them differ in "
        "one attribute, `magazine_drop_cap_apply`; the third repeats the first and is "
        "what says how much a run differs from itself.",
        "",
        "## Cost",
        "",
    ]
    lines += table(
        [
            "arm",
            "requests",
            "cache hits",
            "API calls",
            "prompt tokens",
            "completion tokens",
            "seconds",
        ],
        [
            [
                arm,
                sum(row["requests"] for row in evidence["arms"][arm]),
                sum(row["cache_hits"] for row in evidence["arms"][arm]),
                sum(row["api_calls"] for row in evidence["arms"][arm]),
                sum(row["prompt_tokens"] for row in evidence["arms"][arm]),
                sum(row["completion_tokens"] for row in evidence["arms"][arm]),
                round(sum(row["seconds"] for row in evidence["arms"][arm]), 1),
            ]
            for arm in ARMS
        ],
    )

    lines += [
        "",
        "## a. Every site a verdict reached",
        "",
        "What each request carried, read out of the translator's own tracking file.",
        "",
    ]
    lines += table(
        [
            "sample",
            "paragraph",
            "verdict",
            "from",
            "initial",
            "ratio",
            "merged",
            "separator dropped",
            "offered, off",
            "offered, on",
        ],
        [
            [
                site["sample"],
                f"`{site['paragraph']}`",
                site["decision"],
                site["source"],
                f"`{site['initial']}`",
                site["size_ratio"],
                site["merged"],
                site["separator_dropped"],
                f"`{site['offered_off']}`",
                f"`{site['offered_on']}`",
            ]
            for site in evidence["sites"]
        ],
    )
    lines += [
        "",
        "What came back, and how large the paragraph's opening glyph is once the "
        "document has been laid out. The last three columns are the typographic "
        "claim: an initial that survived is several times the body size, and the "
        "median column is the body size of that same paragraph.",
        "",
    ]
    lines += table(
        [
            "sample",
            "paragraph",
            "translated, off",
            "opens in",
            "translated, on",
            "opens in",
            "opening glyph, off",
            "opening glyph, on",
            "median glyph, on",
        ],
        [
            [
                site["sample"],
                f"`{site['paragraph']}`",
                f"`{site['translated_off']}`",
                site["opens_in_off"],
                f"`{site['translated_on']}`",
                site["opens_in_on"],
                site["opening_glyph_off"],
                site["opening_glyph_on"],
                site["median_glyph_on"],
            ]
            for site in evidence["sites"]
        ],
    )
    lines += ["", "The crops, one pair per site:", ""]
    for site in evidence["sites"]:
        lines.append(
            f"- `{site['sample']}` `{site['paragraph']}` page {site['page']}: "
            f"off `{site.get('crop_off')}`, on `{site.get('crop_on')}`"
        )

    lines += [
        "",
        "## b. Outside the paragraphs a verdict reached",
        "",
        "The soul assertion, and the two channels b9.3 found carrying a page level "
        "change out of the page it happened on. Both are measured here rather than "
        "assumed: the merge runs after the term extractor has read the document, so "
        "the automatic glossary is built from the same text in every arm, and the "
        "merge changes no paragraph count, so the requests are composed the same way.",
        "",
    ]
    lines += table(
        [
            "sample",
            "pages",
            "ruled pages",
            "text moved",
            "outside ruled",
            "control moved",
            "raster moved",
            "outside ruled",
            "control raster moved",
        ],
        [
            [
                item["sample"],
                item["pages"],
                item["ruled_pages"] or "none",
                item["text_moved"] or "none",
                item["text_moved_outside_ruled"] or "none",
                item["control_text_moved"] or "none",
                item["raster_moved"] or "none",
                item["raster_moved_outside_ruled"] or "none",
                item["control_raster_moved"] or "none",
            ]
            for item in evidence["spill"]
        ],
    )
    exceptions = [
        (item["sample"], row)
        for item in evidence["spill"]
        for row in item["raster_exceptions"]
    ]
    if exceptions:
        lines += [
            "",
            "One page rendered differently outside a ruled page, and it is accounted "
            "for rather than smoothed away. The repair loop asks a model which "
            "findings to act on, that request is not served from the cache, and the "
            "three arms chose differently; a finding the loop resolved in one arm and "
            "not in another is a rendered difference on a page the merge never "
            "touched. The control arm chose a third set and happened to resolve the "
            "same findings as the base arm, which is why the floor did not reveal the "
            "variance and why the mechanism is read out of the loop's own record.",
            "",
        ]
        lines += table(
            [
                "sample",
                "page",
                "translated text moved",
                "resolved, base arm",
                "resolved, subject arm",
                "attribution",
            ],
            [
                [
                    sample,
                    row["page"],
                    row["text_moved"],
                    len(row["repair_resolved_base"]),
                    len(row["repair_resolved_subject"]),
                    "; ".join(row["attribution"]) or "unexplained",
                ]
                for sample, row in exceptions
            ],
        )
    lines += ["", "And the two channels, entry by entry and request by request:", ""]
    lines += table(
        [
            "sample",
            "glossary entries, off",
            "on",
            "identical",
            "entries differing",
            "requests, off",
            "on",
            "composition identical",
        ],
        [
            [
                item["sample"],
                item["glossary_entries"]["off"],
                item["glossary_entries"]["on"],
                item["glossary_identical"],
                item["glossary_changed_entries"],
                item["batches"]["off"],
                item["batches"]["on"],
                item["batch_composition_identical"],
            ]
            for item in evidence["spill"]
        ],
    )

    lines += ["", "The repair loop's own answer, arm by arm:", ""]
    lines += table(
        ["sample", "arm", "iterations", "action and findings chosen", "resolved", "from cache"],
        [
            [
                item["sample"],
                arm,
                item["arms"][arm]["iterations"],
                "; ".join(
                    f"{dec['action']}({len(dec['issue_ids'] or ())})"
                    for dec in item["arms"][arm]["decisions"]
                ),
                sum(
                    len(dec["resolved_ids"] or ())
                    for dec in item["arms"][arm]["decisions"]
                ),
                sorted({bool(dec["from_cache"]) for dec in item["arms"][arm]["decisions"]}),
            ]
            for item in evidence["repair"]
            for arm in ARMS
        ],
    )
    lines += [
        "",
        "### What the detectors see",
        "",
        "The F1 review recorded these defects by eye. Whether this project's own "
        "detectors see them is a different question, and the answer is on the "
        "record either way: a collision between an oversized initial and the text "
        "beside it is not a kind any shipped detector reports, so the counts below "
        "are the surrounding findings rather than the defect itself.",
        "",
    ]
    lines += table(
        ["sample", "arm", "issues", "by kind", "on ruled pages", "naming a ruled paragraph"],
        [
            [
                item["sample"],
                arm,
                item["arms"][arm]["issues"],
                json.dumps(item["arms"][arm]["by_kind"], sort_keys=True),
                json.dumps(item["arms"][arm]["on_ruled_pages"], sort_keys=True),
                len(item["arms"][arm]["naming_a_ruled_paragraph"]),
            ]
            for item in evidence["detectors"]
            for arm in ARMS
        ],
    )
    lines += [
        "",
        "## c. The candidates, and the one F1 found that the signal used to miss",
        "",
    ]
    lines += table(
        ["sample", "paragraph", "page", "article", "rank", "opens article", "ratio", "initial", "ruled"],
        [
            [
                item["sample"],
                f"`{item['paragraph']}`",
                item["page"],
                item["article_id"],
                item["body_rank"],
                item["opens_article"],
                item["size_ratio"],
                f"`{item['first_run']}`",
                item["ruled"] or "unruled",
            ]
            for item in evidence["candidates"]
        ],
    )
    lines += [
        "",
        "An unruled candidate is acted on under the default its target language "
        "declares, which is what the `from` column of section a records as "
        f"`{drop_cap.SOURCE_DEFAULT}`. The ruling on such a candidate is the user's, "
        "and the draft for it is `"
        + (evidence.get("draft") or "not written by this run")
        + "`.",
        "",
        "## d. Vogue-en page 3, where F1 recorded two Latin residues",
        "",
    ]
    vogue = evidence["vogue"]
    if not vogue.get("available"):
        lines += [f"Not measured: {vogue.get('reason')}.", ""]
    else:
        lines += [
            f"Read from the frozen `{vogue['source']}`, which is the last run that "
            f"put the line structure switch up on this sample. Candidates the signal "
            f"finds on the page: {vogue['candidates_on_page'] or 'none'}. Pages that "
            f"run declared for line splitting: {vogue['line_split_declared']}.",
            "",
        ]
        lines += table(
            ["paragraph", "text", "label", "characters", "candidate", "why not"],
            [
                [
                    f"`{item['paragraph']}`",
                    f"`{item['text']}`",
                    item["label"],
                    item["characters"],
                    item["is_candidate"],
                    "; ".join(item["reasons"]) or "-",
                ]
                for item in vogue["residues"]
            ],
        )
        lines += [
            "",
            "These are fragments, not paragraphs opening with an initial: a residue "
            "of two characters standing on its own is outside the candidate signal by "
            "construction rather than by threshold, because the signal reads a "
            "paragraph's opening against that paragraph's own body text and a "
            "fragment has none. Nothing in this batch changes them, and the "
            "observation is recorded rather than answered.",
        ]

    lines += ["", "## The frozen fixture", ""]
    for path_name in evidence["fixtures"]:
        lines.append(f"- `{path_name}`")
    lines.append("")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return REPORT


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    samples = rows_by_sample()
    sites: list[dict] = []
    spills: list[dict] = []
    detectors: list[dict] = []
    repairs: list[dict] = []
    candidates: list[dict] = []
    fixtures: list[str] = []
    for sample, rows in sorted(samples.items()):
        found = site_rows(sample, rows)
        for site in found:
            for arm in (BASE_ARM, SUBJECT_ARM):
                site[f"crop_{arm}"] = crop(
                    rows[arm],
                    site["page"],
                    site[f"box_{arm}"],
                    f"{sample}.{site['paragraph'].replace('#', '_')}.{arm}",
                )
        sites.extend(found)
        spills.append(spill(sample, rows, found))
        detectors.append(detector_inventory(sample, rows, found))
        repairs.append(repair_comparison(sample, rows))
        candidates.extend(candidate_rows(sample, rows))
        fixtures.extend(freeze(rows, sample))

    evidence = {
        "batch": "b9.4",
        "switch": drop_cap.APPLY_SWITCH,
        "arms": {arm: ledger(arm) for arm in ARMS},
        "sites": sites,
        "spill": spills,
        "detectors": detectors,
        "repair": repairs,
        "candidates": candidates,
        "vogue": vogue_observation(),
        "fixtures": sorted(fixtures),
        "totals": {
            "sites": len(sites),
            "merged": sum(1 for site in sites if site["merged"]),
            "ruled": sum(1 for site in sites if site["source"] == drop_cap.SOURCE_RULED),
            "defaulted": sum(
                1 for site in sites if site["source"] == drop_cap.SOURCE_DEFAULT
            ),
            "still_latin_off": sum(
                1 for site in sites if site["opens_in_off"] == "latin"
            ),
            "still_latin_on": sum(1 for site in sites if site["opens_in_on"] == "latin"),
        },
    }
    # The draft the candidate ruling is written on, whichever sample carries an
    # unruled candidate. Written by export_candidates.py into this batch's tree.
    drafts = sorted((OUT_DIR / "reviews").glob("*.review.json"))
    if drafts:
        evidence["draft"] = drafts[0].relative_to(ROOT).as_posix()
        evidence["drafts"] = [item.relative_to(ROOT).as_posix() for item in drafts]
    with EVIDENCE.open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, sort_keys=True, ensure_ascii=False)
    write_report(evidence)
    print(json.dumps(evidence["totals"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
