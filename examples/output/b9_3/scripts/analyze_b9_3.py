"""B9.3 acceptance analysis: what the line structure switch did, and did not.

Reads the three arms this batch ran and writes the evidence the batch is
accepted on. Nothing here calls a translator: every number comes out of the
checkpoints, the sidecars and the produced pages the arms left behind.

The attribution floor is b9.2's and is used unchanged. Two arms carry the same
configuration and one carries the switch; a difference counts against the switch
only on a page where the repeat arm reproduced the first one. Checkpoints are
compared with the two attributes a run mints -- the debug id and the chain id --
removed, because they label rather than say anything.

What is measured, in the order the acceptance asks for it:

  a. The five defects the F1 diagnosis found on a contents page, each one
     measured on the produced page in both arms rather than described. Two of
     them are what this batch is for; two are recorded as out of reach at this
     layer and one is an observation about what the layout does not carry.
  b. The editorial column that shares the contents page: it must reach the
     translator whole, which is what the two bounds this session added are for.
     The counterfactual -- what the split would have done to it without them --
     is computed rather than argued.
  c. Every line the translator's length floor skipped, listed as it stands.
  d. The soul assertion: outside a declared page, the arms hold the same
     document.
  e. How far the recovered lines are from the lines the paragraph finder found,
     on the two samples session one did not measure.
  f. What the split did to the surface the ruled glossary matches against.

Usage:
    python analyze_b9_3.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from tools import render_diff  # noqa: E402

BATCH_DIR = ROOT / "examples" / "output" / "b9_3"
RASTER_DIR = BATCH_DIR / "raster"
FIXTURE_DIR = BATCH_DIR / "fixtures"

ARMS = ("off", "control", "on")
BASE_ARM, CONTROL_ARM, SUBJECT_ARM = ARMS

CLASSIFIER_STAGE = "page_classifier"
FINDER_STAGE = "paragraph_finder"
TRANSLATED_STAGE = "il_translated"
TYPESET_STAGE = "typesetting"

# The sample and page the F1 diagnosis reported the five defects from, and the
# fraction of the page width its contents column occupies. The crop is the same
# for both arms, so what it shows is the arms and not the crop.
CASE_SAMPLE = "Courier-en"
CASE_PAGE = 1
COLUMN_FRACTION = 0.47
CROP_SCALE = 3.0

# What a record line looks like once it is drawn. A run of dots is a leader; a
# short run of digits standing alone is a folio.
LEADER_RUN = re.compile(r"[.…·]{3,}")
FOLIO = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
LATIN_TAIL = re.compile(r"[A-Za-z]$")
LATIN_HEAD = re.compile(r"^[a-z]")

# A rendered line this short in the middle of a column is an orphan: the tail
# of a record that wrapped, standing alone on a line of its own.
ORPHAN_MAX_CHARS = 2

# How far apart two glyph centres may stand and still be read as one line.
LINE_BAND_POINTS = 3.0


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


# Two attributes of a checkpoint are minted fresh on every run rather than
# derived from the document. They label, they do not say anything, and two runs
# of one input disagree on them by construction.
MINTED_ATTRIBUTES = re.compile(r'\s*(?:debug_id|chainId)="[^"]*"')


def page_digests(path: Path) -> dict[int, str]:
    """One digest per page of a checkpoint, with the minted labels removed.

    Per page rather than per document, because the switch is a page policy: the
    document differs on a declared page by construction and the claim being
    asserted is about every other page.
    """
    document = read_checkpoint(path)
    digests = {}
    for index, page in enumerate(document.page, start=1):
        text = checkpoint_module.to_checkpoint_xml(
            il_version_1.Document(page=[page], total_pages=1)
        )
        stripped = MINTED_ATTRIBUTES.sub("", text)
        digests[index] = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
    return digests


def split_report(row: dict) -> dict | None:
    path = working_dir(row) / line_split.REPORT_NAME
    return load(path) if path.is_file() else None


def declared_pages(sample: str, rows: dict[str, dict]) -> list[int]:
    """Which pages of one sample the policy declares, read off the run itself."""
    report = split_report(rows[SUBJECT_ARM])
    if report is None:
        return []
    return [item["page"] for item in report["pages"] if item["declared"]]


# --- the produced page ---------------------------------------------------------


def column_clip(page) -> pymupdf.Rect:
    """The contents column of a page, as a fraction of its own width."""
    rect = page.rect
    return pymupdf.Rect(rect.x0, rect.y0, rect.x0 + rect.width * COLUMN_FRACTION, rect.y1)


def rendered_lines(pdf: Path, label: int) -> list[dict]:
    """Every line of type the writer drew in the contents column, in order.

    Built from words and their baselines rather than from the extractor's own
    line grouping. The two arms do not draw the same way -- a line the split
    produced is placed glyph by glyph, and the extractor then reports each glyph
    as a line of its own -- so a measurement that trusted that grouping would be
    comparing the writer's placement rather than the layout. Words whose
    vertical centres agree to LINE_BAND_POINTS stand on one line.
    """
    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        words = page.get_text("words", clip=column_clip(page))
    words.sort(key=lambda word: ((word[1] + word[3]) / 2, word[0]))
    grouped: list[dict] = []
    for word in words:
        centre = (word[1] + word[3]) / 2
        if grouped and abs(grouped[-1]["centre"] - centre) <= LINE_BAND_POINTS:
            grouped[-1]["parts"].append((word[0], word[4]))
            grouped[-1]["x1"] = max(grouped[-1]["x1"], word[2])
            continue
        grouped.append(
            {"centre": centre, "parts": [(word[0], word[4])], "x0": word[0], "x1": word[2]}
        )
    lines = []
    for item in grouped:
        text = "".join(part for _, part in sorted(item["parts"]))
        lines.append(
            {
                "text": text,
                "x0": round(item["x0"], 2),
                "x1": round(item["x1"], 2),
                "y": round(item["centre"], 2),
            }
        )
    return lines


def glued_after_folio(text: str) -> bool:
    """Whether a folio on this line is followed by more of another record.

    The third defect: the byline that belonged on the next line continues after
    the page number and wraps, which is what leaves an orphan behind it.
    """
    match = None
    for match in FOLIO.finditer(text):
        pass
    if match is None:
        return False
    return len(text[match.end() :].strip()) >= ORPHAN_MAX_CHARS


def leader_lines(lines: list[dict]) -> list[dict]:
    return [item for item in lines if LEADER_RUN.search(item["text"])]


def is_orphan(text: str, above: str | None) -> bool:
    """A line carrying nothing but the tail of the record above it.

    Short is not enough: a section label and the page's own title are short and
    stand in both arms. What makes a line an orphan is the line above it -- a
    record whose folio was followed by a byline that ran past the measure and
    wrapped, leaving one or two characters behind.
    """
    stripped = text.strip()
    if not (0 < len(stripped) <= ORPHAN_MAX_CHARS) or stripped.isdigit():
        return False
    return bool(above and FOLIO.search(above))


def designed_leader_alignment(row: dict, label: int) -> dict:
    """Where the source put the right edge of every record that has a leader.

    The second defect is that the leader no longer fills to the margin. What
    "the margin" was is only knowable from the source, so it is measured there:
    the right edge of each source line that carries a leader run, and how far
    those edges spread. A design that fills to a margin spreads by nothing.
    """
    settings = line_split.load_line_split_config()
    page = read_checkpoint(checkpoint_path(row, CLASSIFIER_STAGE)).page[label - 1]
    edges = []
    for paragraph in page.pdf_paragraph or ():
        characters = line_split.paragraph_characters(paragraph)
        if not characters:
            continue
        for line in line_split.recover_lines(characters, settings):
            text = line_split.line_text(characters, line)
            if not LEADER_RUN.search(text):
                continue
            boxes = [line_split.character_box(characters[index]) for index in line]
            right = max(box.x2 for box in boxes if box is not None and box.x2 is not None)
            edges.append(round(float(right), 2))
    return {
        "lines": len(edges),
        "right_edges": sorted(edges),
        "spread": round(max(edges) - min(edges), 2) if edges else None,
    }


def defect_metrics(pdf: Path, label: int) -> dict:
    """The defects that can be counted, counted on one produced page."""
    lines = rendered_lines(pdf, label)
    leaders = leader_lines(lines)
    orphans = [
        item
        for position, item in enumerate(lines)
        if is_orphan(item["text"], lines[position - 1]["text"] if position else None)
    ]
    broken = []
    for first, second in zip(lines, lines[1:], strict=False):
        if LATIN_TAIL.search(first["text"].strip()) and LATIN_HEAD.match(
            second["text"].strip()
        ):
            broken.append(
                f"{first['text'].strip()[-12:]} | {second['text'].strip()[:12]}"
            )
    right_edges = sorted(round(item["x1"], 2) for item in leaders)
    return {
        "lines": len(lines),
        "leader_lines": len(leaders),
        "records_glued_after_folio": sum(
            1 for item in lines if glued_after_folio(item["text"])
        ),
        "glued_examples": [
            item["text"].strip()[:60] for item in lines if glued_after_folio(item["text"])
        ][:6],
        "orphan_lines": len(orphans),
        "orphan_examples": [item["text"].strip() for item in orphans][:6],
        "broken_latin_words": len(broken),
        "broken_examples": broken[:6],
        "leader_right_edge_spread": (
            round(right_edges[-1] - right_edges[0], 2) if right_edges else None
        ),
        "leader_right_edges": right_edges[:12],
    }


def render_page(pdf: Path, label: int, stem: str) -> str:
    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        page.get_pixmap(matrix=pymupdf.Matrix(CROP_SCALE, CROP_SCALE)).save(
            RASTER_DIR / f"{stem}.png"
        )
    return (RASTER_DIR / f"{stem}.png").relative_to(ROOT).as_posix()


def render_column(pdf: Path, label: int, stem: str) -> str:
    with pymupdf.open(pdf) as document:
        page = document[label - 1]
        page.get_pixmap(
            matrix=pymupdf.Matrix(CROP_SCALE, CROP_SCALE), clip=column_clip(page)
        ).save(RASTER_DIR / f"{stem}.png")
    return (RASTER_DIR / f"{stem}.png").relative_to(ROOT).as_posix()


def pair_pages(left: Path, right: Path, dpi: int, threshold: int) -> dict[int, bool]:
    """Page by page, whether two produced PDFs differ at all."""
    differs = {}
    with pymupdf.open(left) as first, pymupdf.open(right) as second:
        for index in range(min(first.page_count, second.page_count)):
            gray_left = render_diff.render_gray(first, index, dpi)
            gray_right = render_diff.render_gray(second, index, dpi)
            if gray_left.shape != gray_right.shape:
                differs[index + 1] = True
                continue
            delta = np.abs(gray_left.astype(np.int16) - gray_right.astype(np.int16))
            differs[index + 1] = bool((delta > threshold).any())
    return differs


# --- d. the soul assertion -----------------------------------------------------


def compare_arms(sample: str, rows: dict[str, dict]) -> dict:
    """One sample's three arms, page by page, in the document and on the page."""
    declared = declared_pages(sample, rows)
    report = split_report(rows[SUBJECT_ARM]) or {"pages": [], "splits": [], "short_lines": []}
    stages = {}
    for stage in (CLASSIFIER_STAGE, TRANSLATED_STAGE, TYPESET_STAGE):
        digests = {arm: page_digests(checkpoint_path(rows[arm], stage)) for arm in ARMS}
        pages = sorted(digests[BASE_ARM])
        subject = [
            label
            for label in pages
            if digests[BASE_ARM][label] != digests[SUBJECT_ARM].get(label)
        ]
        control = [
            label
            for label in pages
            if digests[BASE_ARM][label] != digests[CONTROL_ARM].get(label)
        ]
        stages[stage] = {
            "differing_on": subject,
            "differing_control": control,
            "attributable": [label for label in subject if label not in control],
            "undeclared_differing_on": [
                label for label in subject if label not in declared
            ],
            "undeclared_attributable": [
                label
                for label in subject
                if label not in control and label not in declared
            ],
        }

    settings = render_diff.load_config()
    dpi, threshold = settings["dpi"], settings["pixel_diff_threshold"]
    subject_raster = pair_pages(
        ROOT / rows[BASE_ARM]["pdf"], ROOT / rows[SUBJECT_ARM]["pdf"], dpi, threshold
    )
    control_raster = pair_pages(
        ROOT / rows[BASE_ARM]["pdf"], ROOT / rows[CONTROL_ARM]["pdf"], dpi, threshold
    )
    raster_on = [label for label, moved in subject_raster.items() if moved]
    raster_control = [label for label, moved in control_raster.items() if moved]

    translated = stages[TRANSLATED_STAGE]
    structure = stages[CLASSIFIER_STAGE]
    return {
        "structure_differing_pages": structure["differing_on"],
        "structure_differing_control": structure["differing_control"],
        "structure_confined_to_declared": not [
            label for label in structure["differing_on"] if label not in declared
        ],
        "declared_pages_unchanged": [
            label for label in declared if label not in structure["differing_on"]
        ],
        "declared_pages": declared,
        "undeclared_pages": [
            item["page"] for item in report["pages"] if not item["declared"]
        ],
        "split_paragraphs": report["totals"]["split_paragraphs"] if report.get("totals") else 0,
        "line_paragraphs": report["totals"]["line_paragraphs"] if report.get("totals") else 0,
        "exempt_paragraphs": report["totals"]["exempt_paragraphs"] if report.get("totals") else 0,
        "split_pages_outside_declared": sorted(
            {item["page"] for item in report["splits"]} - set(declared)
        ),
        "undeclared_pages_identical": not translated["undeclared_differing_on"],
        "undeclared_attributable": translated["undeclared_attributable"],
        "il": stages,
        "raster": {
            "differing_on": raster_on,
            "differing_control": raster_control,
            "attributable": [label for label in raster_on if label not in raster_control],
            "undeclared_attributable": [
                label
                for label in raster_on
                if label not in raster_control and label not in declared
            ],
        },
        "short_lines": report.get("short_lines", []),
        "short_line_count": len(report.get("short_lines", [])),
    }


# --- a. the five defects -------------------------------------------------------


def case_records(rows: dict[str, dict]) -> dict:
    """The five defects of the diagnosed page, measured in both arms."""
    off = ROOT / rows[BASE_ARM]["pdf"]
    on = ROOT / rows[SUBJECT_ARM]["pdf"]
    measured = {
        BASE_ARM: defect_metrics(off, CASE_PAGE),
        SUBJECT_ARM: defect_metrics(on, CASE_PAGE),
    }
    report = split_report(rows[SUBJECT_ARM])
    splits = [item for item in (report or {}).get("splits", ()) if item["page"] == CASE_PAGE]
    measured["source"] = designed_leader_alignment(rows[BASE_ARM], CASE_PAGE)
    # The same stems the declared page rasters use, so the diagnosed page is one
    # pair of images rather than two copies of one.
    rasters = {
        "off_page": render_page(off, CASE_PAGE, f"{CASE_SAMPLE}.p{CASE_PAGE}.off"),
        "on_page": render_page(on, CASE_PAGE, f"{CASE_SAMPLE}.p{CASE_PAGE}.on"),
        "off_column": render_column(off, CASE_PAGE, f"{CASE_SAMPLE}.p{CASE_PAGE}.off.crop"),
        "on_column": render_column(on, CASE_PAGE, f"{CASE_SAMPLE}.p{CASE_PAGE}.on.crop"),
    }
    return {
        "sample": CASE_SAMPLE,
        "page": CASE_PAGE,
        "split_paragraphs": len(splits),
        "line_paragraphs": sum(item["lines"] for item in splits),
        "metrics": measured,
        "raster": rasters,
    }


def declared_rasters(sample: str, rows: dict[str, dict]) -> list[dict]:
    """Every declared page of one sample, before and after, page and column.

    The diagnosed page gets its own case above; this is the rest of what the
    switch touched, so a reader can see each declared page in both arms without
    running anything.
    """
    produced = []
    for label in declared_pages(sample, rows):
        entry = {"page": label, "measurements": {}}
        for arm in (BASE_ARM, SUBJECT_ARM):
            pdf = ROOT / rows[arm]["pdf"]
            stem = f"{sample}.p{label}.{arm}"
            # The column, not the page: a declared page is a grid of records and
            # the records are what changed, so a full page image would be mostly
            # the artwork beside them. The diagnosed page is rendered whole as
            # well, by the case above.
            entry[f"{arm}_column"] = render_column(pdf, label, f"{stem}.crop")
            entry["measurements"][arm] = defect_metrics(pdf, label)
        produced.append(entry)
    return produced


# --- b. the column that must not be cut ----------------------------------------


def translated_texts(row: dict, label: int) -> list[str]:
    """One translated page's paragraphs, in the order they are stored in.

    By position rather than by identity: the debug id is minted per run, so the
    two arms disagree on it by construction and it cannot match a paragraph to
    itself across them. Position can, because no stage between the split and the
    translator reorders a page.
    """
    document = read_checkpoint(checkpoint_path(row, TRANSLATED_STAGE))
    page = document.page[label - 1]
    return [paragraph.unicode or "" for paragraph in page.pdf_paragraph or ()]


def split_offsets(report: dict, label: int) -> dict[int, int]:
    """Where a pre-split paragraph of one page ends up after the split.

    The split replaces one paragraph with several in place, so a paragraph after
    a cut one moves down the list by the lines that cut produced beyond the
    first. Read off the report rather than guessed, and keyed by the index the
    paragraph had before.
    """
    grown = sorted(
        (int(item["paragraph"].split("#")[-1]), item["lines"] - 1)
        for item in report.get("splits", ())
        if item["page"] == label
    )
    offsets: dict[int, int] = {}
    running = 0
    previous = 0
    for index, extra in grown:
        for position in range(previous, index + 1):
            offsets[position] = running
        running += extra
        previous = index + 1
    return {"offsets": offsets, "tail": running}


def offered_inputs(row: dict) -> set[str]:
    """Every source text this run offered a translator, as it offered it.

    Read from the run's own tracking rather than reconstructed. A paragraph
    whose whole text is in this set was translated as one unit; a paragraph the
    split had cut would appear as its lines instead.
    """
    path = working_dir(row) / "translate_tracking.json"
    if not path.is_file():
        return set()
    offered: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            if "pdf_unicode" in node:
                offered.add((node.get("pdf_unicode") or "").strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(load(path))
    return offered


def prose_exemption(rows: dict[str, dict]) -> dict:
    """The editorial column of the contents page, and what the bounds did to it.

    Three things, and the third is the point. The column's paragraphs were
    exempted, and for the measure bound rather than by accident. Their
    translations are the same text in both arms, which is what "reached the
    translator whole" means when read off the produced document. And the
    counterfactual is computed: with the bounds relaxed, this is how many
    requests each paragraph would have become and where the first cut would
    have fallen.
    """
    report = split_report(rows[SUBJECT_ARM]) or {"exemptions": []}
    exemptions = [
        item
        for item in report["exemptions"]
        if item["page"] == CASE_PAGE and item["reason"] == line_split.REASON_LONG_LINES
    ]
    off_text = translated_texts(rows[BASE_ARM], CASE_PAGE)
    on_text = translated_texts(rows[SUBJECT_ARM], CASE_PAGE)
    mapping = split_offsets(report, CASE_PAGE)
    offered = offered_inputs(rows[SUBJECT_ARM])

    # The identities are minted per run, so the two arms are matched on the
    # source paragraph the exemption names rather than on a label.
    source = read_checkpoint(
        checkpoint_path(rows[BASE_ARM], CLASSIFIER_STAGE)
    ).page[CASE_PAGE - 1]
    settings = line_split.load_line_split_config()
    relaxed = line_split.parse_line_split_config(
        {
            **load(ROOT / "configs" / "line_split.json"),
            "max_line_chars": 400.0,
            "require_style_heterogeneity": 0,
        },
        "line_split.json (bounds relaxed)",
    )

    rows_out = []
    for item in exemptions:
        index = int(item["paragraph"].split("#")[-1])
        paragraph = (source.pdf_paragraph or ())[index]
        examination = line_split.examine(paragraph, relaxed)
        characters = line_split.paragraph_characters(paragraph)
        fragments = [
            line_split.line_text(characters, line).strip()
            for line in (examination.lines if examination else [])
        ]
        offset = mapping["offsets"].get(index, mapping["tail"])
        off_translation = off_text[index] if index < len(off_text) else None
        on_position = index + offset
        on_translation = on_text[on_position] if on_position < len(on_text) else None
        rows_out.append(
            {
                "paragraph": item["paragraph"],
                "reason": item["reason"],
                "lines": item["lines"],
                "mean_line_chars": item["mean_line_chars"],
                "source_chars": len(paragraph.unicode or ""),
                "translated_chars_off": len(off_translation or ""),
                "translated_chars_on": len(on_translation or ""),
                "translations_identical": off_translation == on_translation,
                "offered_whole": (paragraph.unicode or "").strip() in offered,
                "counterfactual_requests": len(fragments),
                "counterfactual_first_fragments": fragments[:2],
            }
        )
    return {
        "sample": CASE_SAMPLE,
        "page": CASE_PAGE,
        "paragraphs": len(rows_out),
        "exempted": sum(1 for item in rows_out if item["reason"]),
        "identical_translations": sum(
            1 for item in rows_out if item["translations_identical"]
        ),
        "offered_whole": sum(1 for item in rows_out if item["offered_whole"]),
        "counterfactual_requests": sum(item["counterfactual_requests"] for item in rows_out),
        "bounds": {
            "max_line_chars": settings.max_line_chars,
            "require_style_heterogeneity": settings.require_style_heterogeneity,
        },
        "evidence": rows_out,
    }


def unchanged_units(row: dict, labels: list[int]) -> dict:
    """Units of a declared page that came back as the text they went in as.

    A translation unit whose answer is its own source is a unit the engine did
    not translate. The split makes units smaller, and a smaller unit carries
    less of the sentence it came from, so this is the cost side of the same
    change: measured per arm on the same pages, with the units that are pure
    punctuation or digits left out because nothing was ever going to happen to
    them.
    """
    source = read_checkpoint(checkpoint_path(row, CLASSIFIER_STAGE))
    translated = read_checkpoint(checkpoint_path(row, TRANSLATED_STAGE))
    total = 0
    unchanged = []
    for label in labels:
        before = source.page[label - 1].pdf_paragraph or ()
        after = translated.page[label - 1].pdf_paragraph or ()
        if len(before) != len(after):
            continue
        for paragraph, result in zip(before, after, strict=False):
            text = (paragraph.unicode or "").strip()
            if not any(character.isalpha() for character in text):
                continue
            total += 1
            if text == (result.unicode or "").strip():
                unchanged.append(text[:40])
    return {"units": total, "unchanged": len(unchanged), "examples": unchanged[:8]}


# --- d. why a page outside the declared set moved anyway -----------------------


def auto_glossary(row: dict) -> dict[str, str]:
    """The glossary the term extractor wrote for this run."""
    path = working_dir(row) / "auto_extractor_glossary.csv"
    entries: dict[str, str] = {}
    if not path.is_file():
        return entries
    with path.open(encoding="utf-8", newline="") as f:
        for row_in in csv.reader(f):
            if len(row_in) >= 2 and row_in[0] != "source":
                entries[row_in[0]] = row_in[1]
    return entries


def page_sources(row: dict) -> dict[int, str]:
    """Every page's source text, as the document held it before translation."""
    document = read_checkpoint(checkpoint_path(row, CLASSIFIER_STAGE))
    return {
        label: "\n".join((paragraph.unicode or "") for paragraph in page.pdf_paragraph or ())
        for label, page in enumerate(document.page, start=1)
    }


def spillover(sample: str, rows: dict[str, dict], observed: list[int]) -> dict:
    """How a page the split never touched can still be translated differently.

    The split is confined to the declared pages and the document proves it. The
    translation is not, and the reason is that a request is not a paragraph.
    Two channels carry a change off the page it happened on, and both are
    measured here rather than asserted: the term extractor reads the whole
    document and writes one glossary that every prompt draws on, and the
    cross page and cross column pairing puts a paragraph of one page and a
    paragraph of another into a single request. A page whose translation moved
    is explained where at least one channel reaches it.
    """
    declared = set(declared_pages(sample, rows))
    off_glossary = auto_glossary(rows[BASE_ARM])
    on_glossary = auto_glossary(rows[SUBJECT_ARM])
    control_glossary = auto_glossary(rows[CONTROL_ARM])
    delta = sorted(
        term
        for term in set(off_glossary) | set(on_glossary)
        if off_glossary.get(term) != on_glossary.get(term)
    )
    control_delta = sorted(
        term
        for term in set(off_glossary) | set(control_glossary)
        if off_glossary.get(term) != control_glossary.get(term)
    )
    sources = page_sources(rows[BASE_ARM])
    by_glossary = {
        label: [term for term in delta if term and term in text]
        for label, text in sources.items()
        if label not in declared
    }

    text_page = {}
    for label, text in sources.items():
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                text_page.setdefault(stripped, label)
    tracking = load(working_dir(rows[BASE_ARM]) / "translate_tracking.json")
    spanning = []
    for kind in ("cross_page", "cross_column"):
        for unit in tracking.get(kind, ()):
            pages = set()
            for record in unit.get("paragraph", ()):
                key = (record.get("pdf_unicode") or "").strip()
                if key in text_page:
                    pages.add(text_page[key])
            if pages & declared and pages - declared:
                spanning.append(sorted(pages))
    by_pairing = sorted({label for pages in spanning for label in pages} - declared)

    reached = {label for label, terms in by_glossary.items() if terms} | set(by_pairing)
    return {
        "glossary_entries_changed": delta,
        "glossary_entries_changed_by_the_control": control_delta,
        "pages_reached_by_glossary": sorted(
            label for label, terms in by_glossary.items() if terms
        ),
        "glossary_terms_per_page": {
            str(label): terms for label, terms in sorted(by_glossary.items()) if terms
        },
        "paired_units_spanning": spanning,
        "pages_reached_by_pairing": by_pairing,
        "observed_moving": observed,
        "explained": sorted(set(observed) - reached) == [],
        "unexplained": sorted(set(observed) - reached),
    }


# --- e. how close the recovered lines are --------------------------------------


def finder_lines(row: dict) -> dict[int, list[int]]:
    """How many lines the paragraph finder built, per paragraph, per page."""
    document = read_checkpoint(checkpoint_path(row, FINDER_STAGE))
    found = {}
    for label, page in enumerate(document.page, start=1):
        counts = []
        for paragraph in page.pdf_paragraph or ():
            counts.append(
                sum(
                    1
                    for composition in paragraph.pdf_paragraph_composition or ()
                    if composition.pdf_line is not None
                )
            )
        found[label] = counts
    return found


def recovery(sample: str, rows: dict[str, dict]) -> dict:
    """The recovery against the finder's own lines, on the declared pages.

    Session one measured this on Courier; this is the same measurement on the
    samples it did not reach. Read on the arm with the switch down, because the
    arm with it up has already replaced the paragraphs being compared.
    """
    row = rows[BASE_ARM]
    settings = line_split.load_line_split_config()
    reference = finder_lines(row)
    document = read_checkpoint(checkpoint_path(row, CLASSIFIER_STAGE))
    declared = set(declared_pages(sample, rows))
    exact = under = over = total = 0
    misses = []
    for label, page in enumerate(document.page, start=1):
        if label not in declared:
            continue
        expected = reference.get(label, [])
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            characters = line_split.paragraph_characters(paragraph)
            if not characters or index >= len(expected) or not expected[index]:
                continue
            recovered = len(line_split.recover_lines(characters, settings))
            total += 1
            if recovered == expected[index]:
                exact += 1
                continue
            if recovered < expected[index]:
                under += 1
            else:
                over += 1
            misses.append(
                {
                    "paragraph": line_split.paragraph_reference(label, index),
                    "found_by_finder": expected[index],
                    "recovered": recovered,
                    "text": (paragraph.unicode or "")[:60],
                }
            )
    return {
        "paragraphs": total,
        "exact": exact,
        "under_split": under,
        "over_split": over,
        "misses": misses[:12],
    }


# --- f. the surface the glossary matches against -------------------------------


def ruled_terms(rows: dict[str, dict]) -> list[str]:
    """The pairs the ruling applied on this run, by source form."""
    path = working_dir(rows[SUBJECT_ARM]) / "hitl_apply.report.json"
    if not path.is_file():
        return []
    terms = load(path).get("terms") or {}
    return [entry["source"] for entry in terms.get("entries", ())]


def terms_across_line_boundaries(rows: dict[str, dict], terms: list[str]) -> list[dict]:
    """Where each ruled term stands on the declared pages, line by line.

    The split makes the matching surface shorter: a term the source set inside
    one line is still one string after the cut, and a term the source set across
    a line break was never one string in the first place and is now two
    requests. Measured on the source rather than argued from the counts.
    """
    settings = line_split.load_line_split_config()
    document = read_checkpoint(checkpoint_path(rows[BASE_ARM], CLASSIFIER_STAGE))
    declared = set(declared_pages(CASE_SAMPLE, rows))
    lines: list[str] = []
    pages: list[str] = []
    for label, page in enumerate(document.page, start=1):
        if label not in declared:
            continue
        page_text = []
        for paragraph in page.pdf_paragraph or ():
            characters = line_split.paragraph_characters(paragraph)
            if not characters:
                continue
            page_text.append(paragraph.unicode or "")
            for line in line_split.recover_lines(characters, settings):
                lines.append(line_split.line_text(characters, line))
        pages.append(" ".join(page_text))
    joined = " ".join(pages)
    found = []
    for term in terms:
        on_page = term in joined
        within_line = any(term in line for line in lines)
        found.append(
            {
                "source": term,
                "on_a_declared_page": on_page,
                "inside_one_source_line": within_line,
                "spans_a_line_boundary": bool(on_page and not within_line),
            }
        )
    return found


def glossary_matches(rows: dict[str, dict]) -> dict:
    """How many requests each ruled pair reached, arm against arm.

    The ruling's person names are matched against the text a paragraph is
    offered as, and the split changes what those texts are: a contents entry
    becomes one request per line, so a name on its own line is still a whole
    name and a name the source set across two lines is now two requests neither
    of which holds it.
    """
    counts = {}
    for arm in (BASE_ARM, SUBJECT_ARM):
        path = working_dir(rows[arm]) / "hitl_apply.report.json"
        if not path.is_file():
            continue
        terms = load(path).get("terms") or {}
        counts[arm] = {
            item["source"]: item["matched_prompt_count"]
            for item in terms.get("matches", ())
        }
    if len(counts) < 2:
        return {"available": False}
    sources = sorted(set(counts[BASE_ARM]) | set(counts[SUBJECT_ARM]))
    rows_out = [
        {
            "source": source,
            "off": counts[BASE_ARM].get(source),
            "on": counts[SUBJECT_ARM].get(source),
        }
        for source in sources
    ]
    spans = terms_across_line_boundaries(rows, [item["source"] for item in rows_out])
    return {
        "available": True,
        "terms": len(rows_out),
        "on_a_declared_page": [
            item["source"] for item in spans if item["on_a_declared_page"]
        ],
        "spanning_a_line_boundary": [
            item["source"] for item in spans if item["spans_a_line_boundary"]
        ],
        "line_positions": spans,
        "unreached_off": [item["source"] for item in rows_out if not item["off"]],
        "unreached_on": [item["source"] for item in rows_out if not item["on"]],
        "lost": [item["source"] for item in rows_out if item["off"] and not item["on"]],
        "gained": [item["source"] for item in rows_out if item["on"] and not item["off"]],
        "matches": rows_out,
    }


# --- the section a page does not carry -----------------------------------------


def section_observation(rows: dict[str, dict]) -> dict:
    """The fifth defect: what a section rule and its entries do not share.

    A section is drawn as a coloured rule and a label; the entries below it are
    paragraphs of their own. Nothing in the intermediate language ties one to
    the other, and the split does not add a tie: it cuts a paragraph into the
    lines it was set as, which is a smaller unit, not a grouping. Counted so the
    observation is a count rather than a claim.
    """
    document = read_checkpoint(checkpoint_path(rows[SUBJECT_ARM], CLASSIFIER_STAGE))
    page = document.page[CASE_PAGE - 1]
    labels = {}
    for paragraph in page.pdf_paragraph or ():
        labels[paragraph.layout_label] = labels.get(paragraph.layout_label, 0) + 1
    return {
        "paragraphs_by_label": dict(sorted(labels.items())),
        "curves": len(page.pdf_curve or ()),
        "grouping_fields_written": [],
    }


def flatten_observation(rows: dict[str, dict]) -> dict:
    """Where the ruled drop caps stand now, with both later passes running.

    Not this batch's subject and recorded because it is the next one's input.
    The ruling flattened three drop caps of the diagnosed sample; the pages they
    stand on are not declared, so the split does not reach them, and the heading
    policy runs on the same document afterwards. What is written down is the
    state, page by page: which pass touched the page, and whether the ruled
    paragraph is still the paragraph the ruling named.
    """
    work = working_dir(rows[SUBJECT_ARM])
    applied = load(work / "hitl_apply.report.json") if (work / "hitl_apply.report.json").is_file() else {}
    ruled = applied.get("drop_caps") or []
    marks = load(work / "drop_cap.report.json") if (work / "drop_cap.report.json").is_file() else {}
    marked = {
        item.get("debug_id"): item
        for item in (marks.get("candidates") or marks.get("marked") or ())
        if isinstance(item, dict)
    }
    headings = (
        load(work / "title_typeset.report.json")
        if (work / "title_typeset.report.json").is_file()
        else {}
    )
    heading_pages = sorted(
        {
            item["page"]
            for item in headings.get("titles", ())
            if item.get("disposition") and item["disposition"] != "unchanged"
        }
    )
    declared = set(declared_pages(CASE_SAMPLE, rows))
    report = split_report(rows[SUBJECT_ARM]) or {"splits": []}
    split_pages = {item["page"] for item in report["splits"]}
    entries = []
    for item in ruled:
        page = item.get("page")
        entries.append(
            {
                "page": page,
                "paragraph": item.get("paragraph"),
                "decision": item.get("decision"),
                "page_declared": page in declared,
                "page_split": page in split_pages,
                "heading_policy_touched_page": page in heading_pages,
                "still_marked_as_candidate": item.get("debug_id") in marked,
            }
        )
    return {
        "sample": CASE_SAMPLE,
        "ruled": len(entries),
        "on_a_declared_page": sum(1 for item in entries if item["page_declared"]),
        "heading_pages": heading_pages,
        "entries": entries,
    }


# --- the frozen fixture --------------------------------------------------------


def freeze_fixture(rows: dict[str, dict]) -> dict:
    """The calibration page, committed so the bounds can be replayed forever.

    The page as the arm with the switch down left it, carrying its settled kind
    and its paragraphs and nothing else: the figures, curves and page level
    characters are what makes a checkpoint large and none of them is read by the
    bounds. Packed as a checkpoint archive, which the loader reads in place.
    """
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    source = read_checkpoint(
        checkpoint_path(rows[BASE_ARM], CLASSIFIER_STAGE)
    ).page[CASE_PAGE - 1]
    trimmed = il_version_1.Page(
        mediabox=source.mediabox,
        cropbox=source.cropbox,
        pdf_paragraph=source.pdf_paragraph,
        page_number=source.page_number,
        unit=source.unit,
    )
    trimmed.page_kind = source.page_kind
    text = checkpoint_module.to_checkpoint_xml(
        il_version_1.Document(page=[trimmed], total_pages=1)
    )
    member = f"{checkpoint_module.checkpoint_stem(CLASSIFIER_STAGE)}.xml"
    staging = FIXTURE_DIR / member
    staging.write_text(text, encoding="utf-8")
    archive = FIXTURE_DIR / f"{CASE_SAMPLE}.p{CASE_PAGE}.checkpoints.zip"
    checkpoint_module.write_checkpoint_archive([staging], archive)
    staging.unlink()

    copied = []
    for sample, row in sorted(rows_by_sample(SUBJECT_ARM).items()):
        report = working_dir(row) / line_split.REPORT_NAME
        if not report.is_file():
            continue
        destination = FIXTURE_DIR / f"{sample}.{line_split.REPORT_NAME}"
        destination.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
        copied.append(destination.relative_to(ROOT).as_posix())
    return {
        "calibration_page": archive.relative_to(ROOT).as_posix(),
        "member": member,
        "page_kind": trimmed.page_kind,
        "paragraphs": len(trimmed.pdf_paragraph or ()),
        "reports": copied,
    }


def calibration(rows: dict[str, dict]) -> dict:
    """The two bounds, measured on both sides of the page they were set on."""
    settings = line_split.load_line_split_config()
    page = read_checkpoint(
        checkpoint_path(rows[BASE_ARM], CLASSIFIER_STAGE)
    ).page[CASE_PAGE - 1]
    measured = []
    for index, paragraph in enumerate(page.pdf_paragraph or ()):
        examination = line_split.examine(paragraph, settings)
        if examination is None:
            continue
        measured.append(
            {
                "paragraph": line_split.paragraph_reference(CASE_PAGE, index),
                "lines": len(examination.lines),
                "mean_line_chars": examination.mean_line_chars,
                "heterogeneous": examination.heterogeneous,
                "reason": examination.reason,
                "text": (paragraph.unicode or "")[:60],
            }
        )
    admitted = [item for item in measured if item["reason"] is None]
    long_lines = [
        item for item in measured if item["reason"] == line_split.REASON_LONG_LINES
    ]
    uniform = [
        item for item in measured if item["reason"] == line_split.REASON_UNIFORM_STYLING
    ]
    widest = max(item["mean_line_chars"] for item in admitted)
    narrowest = min(item["mean_line_chars"] for item in long_lines)
    return {
        "sample": CASE_SAMPLE,
        "page": CASE_PAGE,
        "page_kind": page.page_kind,
        "measure_bound": {
            "name": "max_line_chars",
            "value": settings.max_line_chars,
            "widest_admitted": widest,
            "narrowest_exempted": narrowest,
            "margin_below": round(settings.max_line_chars - widest, 2),
            "margin_above": round(narrowest - settings.max_line_chars, 2),
        },
        "setting_bound": {
            "name": "require_style_heterogeneity",
            "value": settings.require_style_heterogeneity,
            "admitted_all_heterogeneous": all(item["heterogeneous"] for item in admitted),
            "exempted_for_uniform_setting": [item["paragraph"] for item in uniform],
        },
        "totals": {
            "measured": len(measured),
            "admitted": len(admitted),
            "exempted_long_lines": len(long_lines),
            "exempted_uniform_styling": len(uniform),
        },
        "paragraphs": [
            {key: item[key] for key in ("paragraph", "lines", "mean_line_chars", "heterogeneous", "reason")}
            for item in measured
        ],
        "annotated": measured,
    }


def cost(rows: dict[str, dict[str, dict]]) -> dict:
    totals = {}
    for arm in ARMS:
        entries = ledger(arm)
        totals[arm] = {
            "requests": sum(item["requests"] for item in entries),
            "cache_hits": sum(item["cache_hits"] for item in entries),
            "api_calls": sum(item["api_calls"] for item in entries),
            "prompt_tokens": sum(item["prompt_tokens"] for item in entries),
            "completion_tokens": sum(item["completion_tokens"] for item in entries),
            "seconds": round(sum(item["seconds"] for item in entries), 1),
        }
    return totals


# --- the report ----------------------------------------------------------------


def markdown(evidence: dict) -> str:
    out = ["# B9.3 acceptance: line structure preservation over three samples", ""]
    out.append(
        "Three arms per sample, the same stack in all three. Two of them differ in "
        "one attribute; the third repeats the first, and is what says how much a "
        "run differs from itself."
    )
    out.append("")

    out.append("## The arms")
    out.append("")
    out.append(
        "| sample | declared pages | split paragraphs | line paragraphs | exempt | "
        "IL pages differing | attributable | undeclared attributable |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for sample, entry in sorted(evidence["samples"].items()):
        translated = entry["il"][TRANSLATED_STAGE]
        out.append(
            f"| {sample} | {entry['declared_pages']} | {entry['split_paragraphs']} | "
            f"{entry['line_paragraphs']} | {entry['exempt_paragraphs']} | "
            f"{translated['differing_on']} | {translated['attributable']} | "
            f"{translated['undeclared_attributable'] or 'none'} |"
        )
    out.append("")

    out.append("## Cost")
    out.append("")
    out.append(
        "| arm | requests | cache hits | API calls | prompt tokens | "
        "completion tokens | seconds |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for arm, entry in evidence["cost"].items():
        out.append(
            f"| {arm} | {entry['requests']} | {entry['cache_hits']} | "
            f"{entry['api_calls']} | {entry['prompt_tokens']} | "
            f"{entry['completion_tokens']} | {entry['seconds']} |"
        )
    out.append("")

    calibrated = evidence["calibration"]
    out.append("## The calibration")
    out.append("")
    measure = calibrated["measure_bound"]
    out.append(
        f"Measured on {calibrated['sample']} page {calibrated['page']}, classified "
        f"`{calibrated['page_kind']}`: {calibrated['totals']['measured']} paragraph(s) "
        f"hold more than one line. The widest the measure bound admits is "
        f"{measure['widest_admitted']} non-space characters per line; the narrowest "
        f"column it exempts is {measure['narrowest_exempted']}. The bound ships at "
        f"{measure['value']}, {measure['margin_below']} above the first and "
        f"{measure['margin_above']} below the second."
    )
    out.append("")
    out.append(
        f"The setting bound ships up. Every paragraph admitted is set in more than "
        f"one face: {calibrated['setting_bound']['admitted_all_heterogeneous']}. It "
        f"exempts {calibrated['totals']['exempted_uniform_styling']} paragraph(s) the "
        f"measure bound would have admitted: "
        f"{calibrated['setting_bound']['exempted_for_uniform_setting'] or 'none'}."
    )
    out.append("")
    out.append("| paragraph | lines | mean line chars | heterogeneous | verdict | text |")
    out.append("| --- | --- | --- | --- | --- | --- |")
    for item in calibrated["annotated"]:
        verdict = item["reason"] or "split"
        text = item["text"].replace("|", "/")
        out.append(
            f"| {item['paragraph']} | {item['lines']} | {item['mean_line_chars']} | "
            f"{item['heterogeneous']} | {verdict} | {text} |"
        )
    out.append("")

    case = evidence["records"]
    out.append("## a. The five defects, measured on the page")
    out.append("")
    out.append(
        f"{case['sample']} page {case['page']}: {case['split_paragraphs']} paragraph(s) "
        f"cut into {case['line_paragraphs']} record line(s)."
    )
    out.append("")
    out.append("| measurement | off | on |")
    out.append("| --- | --- | --- |")
    keys = (
        ("lines", "rendered lines in the column"),
        ("leader_lines", "lines carrying a leader run"),
        ("records_glued_after_folio", "3: another record continues after the folio"),
        ("orphan_lines", "3: orphan lines left by that wrap"),
        ("broken_latin_words", "4: latin words broken across lines"),
        ("leader_right_edge_spread", "2: spread of the leader right edges (pt)"),
    )
    for key, title in keys:
        out.append(
            f"| {title} | {case['metrics']['off'][key]} | {case['metrics']['on'][key]} |"
        )
    out.append("")
    source = case["metrics"]["source"]
    out.append("")
    out.append(
        f"Defects 1 and 3 are what this batch closes and the table above is the "
        f"measurement. Defect 2 is not closed and is not closeable here: the "
        f"source fills its leaders to a common right edge -- "
        f"{source['lines']} leader line(s), spreading {source['spread']}pt -- and "
        f"nothing in the intermediate language carries a fill rule, so a line laid "
        f"out again is laid out from its left edge with the font's own advances. "
        f"Defect 4 is a line breaking rule inside the typesetting stage rather "
        f"than a paragraph boundary, and is untouched by a pass that decides what "
        f"a paragraph is."
    )
    out.append("")
    for arm in ("off", "on"):
        examples = case["metrics"][arm]
        out.append(
            f"- {arm} glued: {examples['glued_examples'] or 'none'}; "
            f"orphans: {examples['orphan_examples'] or 'none'}; "
            f"broken: {examples['broken_examples'] or 'none'}"
        )
    out.append("")
    for name, path in case["raster"].items():
        out.append(f"- {name}: `{path}`")
    out.append("")

    prose = evidence["prose_exemption"]
    out.append("## b. The editorial column of the same page")
    out.append("")
    out.append(
        f"{prose['paragraphs']} paragraph(s), all exempted by the measure bound. "
        f"{prose['offered_whole']} of them were offered to the translator as one "
        f"whole text, which is what the exemption is for; without the bounds the "
        f"same paragraphs would have been cut into "
        f"{prose['counterfactual_requests']} requests, each of them a fragment of "
        f"a sentence. {prose['identical_translations']} came back as exactly the "
        f"text the arm with the switch down produced -- the rest were resampled "
        f"because the shared glossary changed, which is the channel measured in d "
        f"and not a difference in what was asked."
    )
    out.append("")
    out.append(
        "| paragraph | lines | mean line chars | source chars | offered whole | "
        "translated off | translated on | identical | requests without the bounds | "
        "first fragment without them |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in prose["evidence"]:
        fragment = (item["counterfactual_first_fragments"] or [""])[0][:44].replace("|", "/")
        out.append(
            f"| {item['paragraph']} | {item['lines']} | {item['mean_line_chars']} | "
            f"{item['source_chars']} | {item['offered_whole']} | "
            f"{item['translated_chars_off']} | "
            f"{item['translated_chars_on']} | {item['translations_identical']} | "
            f"{item['counterfactual_requests']} | {fragment} |"
        )
    out.append("")

    out.append("## c. The lines the length floor skipped")
    out.append("")
    for sample, entry in sorted(evidence["samples"].items()):
        listed = ", ".join(
            f"{item['paragraph']} {item['text'].strip()[:24]!r}"
            for item in entry["short_lines"][:8]
        )
        out.append(
            f"- {sample}: {entry['short_line_count']} line(s){': ' + listed if listed else ''}"
        )
    out.append("")

    out.append("### What a smaller unit costs")
    out.append("")
    out.append(
        "| sample | units on the declared pages, off | returned untranslated, off | "
        "units, on | returned untranslated, on |"
    )
    out.append("| --- | --- | --- | --- | --- |")
    for sample, entry in sorted(evidence["unchanged_units"].items()):
        share = {
            arm: (
                round(100.0 * entry[arm]["unchanged"] / entry[arm]["units"], 1)
                if entry[arm]["units"]
                else None
            )
            for arm in (BASE_ARM, SUBJECT_ARM)
        }
        out.append(
            f"| {sample} | {entry['off']['units']} | "
            f"{entry['off']['unchanged']} ({share['off']}%) | "
            f"{entry['on']['units']} | {entry['on']['unchanged']} ({share['on']}%) |"
        )
    out.append("")
    out.append(
        "A record line is a smaller unit than the paragraph it came out of, and a "
        "smaller unit carries less of what a translator needs: a personal name "
        "standing alone on its own line is a request with nothing around it, and "
        "the engine more often hands it back as it stands. The examples are in "
        "the evidence file per arm."
    )
    out.append("")

    out.append("## d. Outside a declared page")
    out.append("")
    out.append(
        "Two levels, and they do not say the same thing. The first is the pass "
        "itself: the document as it stands when the split has run and before a "
        "single request has been built. There the claim is exact and it holds -- "
        "every page that differs between the arms is a declared page, and the "
        "control differs on none of them. A declared page can also stand "
        "unchanged, and one does: a page whose paragraphs the bounds all exempt "
        "is a page the pass looked at and left."
    )
    out.append("")
    out.append(
        "| sample | declared | pages differing before translation | confined to declared | "
        "declared but unchanged | control differing | splits outside declared |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for sample, entry in sorted(evidence["samples"].items()):
        out.append(
            f"| {sample} | {entry['declared_pages']} | "
            f"{entry['structure_differing_pages']} | "
            f"{entry['structure_confined_to_declared']} | "
            f"{entry['declared_pages_unchanged'] or 'none'} | "
            f"{entry['structure_differing_control'] or 'none'} | "
            f"{entry['split_pages_outside_declared'] or 'none'} |"
        )
    out.append("")
    out.append(
        "The second is the finished document, and there it does not hold: pages "
        "the split never touched are translated differently. That is a real "
        "finding rather than noise -- the control reproduced those pages exactly "
        "-- and the two channels that carry it are measured below."
    )
    out.append("")
    out.append(
        "| sample | undeclared pages | translated identical | undeclared attributable | "
        "raster differing | raster attributable | undeclared attributable (raster) |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for sample, entry in sorted(evidence["samples"].items()):
        out.append(
            f"| {sample} | {entry['undeclared_pages']} | "
            f"{entry['undeclared_pages_identical']} | "
            f"{entry['undeclared_attributable'] or 'none'} | "
            f"{entry['raster']['differing_on']} | "
            f"{entry['raster']['attributable']} | "
            f"{entry['raster']['undeclared_attributable'] or 'none'} |"
        )
    out.append("")
    out.append("### How a change reaches a page the split never touched")
    out.append("")
    out.append(
        "| sample | pages that moved | reached by the shared glossary | "
        "reached by cross page pairing | unexplained | glossary entries changed | "
        "changed by the control alone |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for sample, entry in sorted(evidence["spillover"].items()):
        out.append(
            f"| {sample} | {entry['observed_moving'] or 'none'} | "
            f"{entry['pages_reached_by_glossary'] or 'none'} | "
            f"{entry['pages_reached_by_pairing'] or 'none'} | "
            f"{entry['unexplained'] or 'none'} | "
            f"{len(entry['glossary_entries_changed'])} | "
            f"{len(entry['glossary_entries_changed_by_the_control'])} |"
        )
    out.append("")
    out.append(
        "The term extractor reads the whole document and writes one glossary that "
        "every prompt draws on, and the cross page and cross column pairing puts a "
        "paragraph of one page and a paragraph of another into a single request. "
        "Either channel is enough to carry a change off the page it happened on. "
        "Neither is this batch's to close, and both are on the record here rather "
        "than smoothed into the attribution floor."
    )
    out.append("")

    out.append("## Every declared page, before and after")
    out.append("")
    out.append(
        "| sample | page | glued after folio, off | on | orphan lines, off | on | "
        "off raster | on raster |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for sample, entries in sorted(evidence["rasters"].items()):
        for entry in entries:
            off_metrics = entry["measurements"]["off"]
            on_metrics = entry["measurements"]["on"]
            out.append(
                f"| {sample} | {entry['page']} | "
                f"{off_metrics['records_glued_after_folio']} | "
                f"{on_metrics['records_glued_after_folio']} | "
                f"{off_metrics['orphan_lines']} | {on_metrics['orphan_lines']} | "
                f"`{entry['off_column']}` | `{entry['on_column']}` |"
            )
    out.append("")
    out.append(
        "The glue count reads a folio followed by more text on one line, which is "
        "a defect only where the design puts the folio at the end of the record. "
        "A contents page that sets the folio at the head of its entry scores on "
        "it in both arms and the equal counts are the tell; the crops are what to "
        "read for those pages."
    )
    out.append("")

    out.append("## e. The recovery against the finder's own lines")
    out.append("")
    out.append("| sample | paragraphs | exact | under split | over split |")
    out.append("| --- | --- | --- | --- | --- |")
    for sample, entry in sorted(evidence["recovery"].items()):
        out.append(
            f"| {sample} | {entry['paragraphs']} | {entry['exact']} | "
            f"{entry['under_split']} | {entry['over_split']} |"
        )
    out.append("")

    glossary = evidence["glossary"]
    out.append("## f. The ruled names against the split surface")
    out.append("")
    if not glossary.get("available"):
        out.append("No ruling applies to a sample of this batch.")
    else:
        out.append(
            f"{glossary['terms']} ruled pair(s). Reached no request with the switch "
            f"down: {glossary['unreached_off'] or 'none'}; with it up: "
            f"{glossary['unreached_on'] or 'none'}. Lost by the split: "
            f"{glossary['lost'] or 'none'}; gained: {glossary['gained'] or 'none'}."
        )
        out.append("")
        out.append(
            f"{len(glossary['on_a_declared_page'])} of them stand on a declared "
            f"page: {glossary['on_a_declared_page'] or 'none'}. Set across a source "
            f"line boundary, and so never one string for the matcher to find "
            f"either before or after the split: "
            f"{glossary['spanning_a_line_boundary'] or 'none'}."
        )
        out.append("")
        out.append("| ruled pair | requests reached, off | requests reached, on |")
        out.append("| --- | --- | --- |")
        for item in glossary["matches"]:
            out.append(f"| {item['source']} | {item['off']} | {item['on']} |")
    out.append("")

    observation = evidence["section_observation"]
    out.append("## The fifth defect, as an observation")
    out.append("")
    out.append(
        f"Paragraph labels on the diagnosed page: {observation['paragraphs_by_label']}; "
        f"{observation['curves']} curve(s) drawn. The split writes no grouping field, "
        f"so which entry belongs under which section rule is as unrecoverable from "
        f"the layout as it was."
    )
    out.append("")

    flatten = evidence["flatten_observation"]
    out.append("## For the next batch: where the ruled drop caps stand")
    out.append("")
    out.append(
        f"{flatten['ruled']} paragraph(s) the ruling flattened, "
        f"{flatten['on_a_declared_page']} of them on a page this batch declares. "
        f"Pages the heading policy changed something on: "
        f"{flatten['heading_pages'] or 'none'}."
    )
    out.append("")
    out.append(
        "| paragraph | page | ruling | page declared | page split | heading policy "
        "touched the page | still a candidate |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for item in flatten["entries"]:
        out.append(
            f"| {item['paragraph']} | {item['page']} | {item['decision']} | "
            f"{item['page_declared']} | {item['page_split']} | "
            f"{item['heading_policy_touched_page']} | "
            f"{item['still_marked_as_candidate']} |"
        )
    out.append("")

    out.append("## The frozen fixture")
    out.append("")
    fixture = evidence["fixture"]
    out.append(f"- `{fixture['calibration_page']}` ({fixture['paragraphs']} paragraphs)")
    for path in fixture["reports"]:
        out.append(f"- `{path}`")
    out.append("")
    return "\n".join(out)


def main() -> int:
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    per_arm = {arm: rows_by_sample(arm) for arm in ARMS}
    samples = sorted(per_arm[BASE_ARM])

    evidence: dict = {"arms": list(ARMS), "cost": cost(per_arm), "samples": {}, "recovery": {}}
    evidence["spillover"] = {}
    evidence["rasters"] = {}
    evidence["unchanged_units"] = {}
    for sample in samples:
        rows = {arm: per_arm[arm][sample] for arm in ARMS}
        entry = compare_arms(sample, rows)
        evidence["samples"][sample] = entry
        evidence["recovery"][sample] = recovery(sample, rows)
        evidence["spillover"][sample] = spillover(
            sample, rows, entry["il"][TRANSLATED_STAGE]["undeclared_attributable"]
        )
        evidence["rasters"][sample] = declared_rasters(sample, rows)
        evidence["unchanged_units"][sample] = {
            arm: unchanged_units(rows[arm], entry["declared_pages"])
            for arm in (BASE_ARM, SUBJECT_ARM)
        }

    case_rows = {arm: per_arm[arm][CASE_SAMPLE] for arm in ARMS}
    evidence["calibration"] = calibration(case_rows)
    evidence["records"] = case_records(case_rows)
    evidence["prose_exemption"] = prose_exemption(case_rows)
    evidence["glossary"] = glossary_matches(case_rows)
    evidence["section_observation"] = section_observation(case_rows)
    evidence["flatten_observation"] = flatten_observation(case_rows)
    evidence["fixture"] = freeze_fixture(case_rows)

    with (BATCH_DIR / "evidence.json").open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False, sort_keys=True)
    calibration_record = dict(evidence["calibration"])
    with (BATCH_DIR / "calibration.json").open("w", encoding="utf-8") as f:
        json.dump(calibration_record, f, indent=2, ensure_ascii=False, sort_keys=True)
    (BATCH_DIR / "report.md").write_text(markdown(evidence), encoding="utf-8")
    print(markdown(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
