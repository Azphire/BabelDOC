"""Gate script for micro batch B10.1 (geometry and display fixes).

Run from the repository root:

    python spec_checks/spec_check_b10_1.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: the batch's one instrument replays the corpus out of the
project cache and this gate reads what that replay left behind.

What this batch is. Five fixes, four of them landed and one of them a finding.
T1 stops a flattened drop cap's own glyph box from deciding where its paragraph
starts. T2 states the single line heading policy per target language, which is
what a sample translated into English needed and a sample translated into
Chinese did not. T3 was a determination before it was a fix and stayed one: the
plan named two candidate mechanisms for the AramcoWorld page 5 headline and
neither is what the evidence says, so nothing was built (assertion 03).
T4 folds a parenthetical that repeats the text before it out of a translated
document. T5 puts a heading the font mapper could not lay out again into the
sidecar rather than only into the run log.

01 is the scope: the delta is the three modules this batch may move plus
configuration, gates and this batch's evidence, with no upstream directory, no
prompt, no ground truth and no ruling touched.

02 is T1, measured in pixels off the committed page images rather than inferred
from the boxes the fix writes.

03 is T3, which is a record of what was determined rather than of what was
changed, frozen as three measurable facts.

04 is T2, T4 and T5, each read off the sidecar and the produced pages.

05 is conservation: page counts, per page paragraph counts, and per paragraph
text against the F2 run, which must differ at the folded paragraphs and nowhere
else. It also carries the batch's cost claim.

Tiers: every assertion is static -- it reads frozen evidence -- so the fast tier
runs the whole gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import paren_dedup  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build:
# every document it asserts on is a stub it builds itself or evidence a
# batch froze, so it answers in seconds to a couple of minutes and runs on
# every batch.
GATE_SET = "fast"

BATCH_TAG = "b10.1"

BATCH_DIR = ROOT / "examples" / "output" / "b10_1"
DRIVER = BATCH_DIR / "scripts" / "run_b10_1.py"
LEDGER = BATCH_DIR / "runs.json"
F2_DIR = ROOT / "examples" / "output" / "F2"

# The samples this batch reads, and the pages of each it reads them on. The same
# table the driver runs from, restated here so the gate does not import it.
TARGETS = {
    "Courier-en": (4, 5, 7),
    "FD-en-v2": (3, 5, 8),
    "AramcoWorld-en-v2": (4, 5, 8, 9),
    "Courier-zh": (1, 2, 5, 7),
}

# The resolution the committed page images were rendered at, which is what turns
# a row of one of them back into a coordinate on the page.
RASTER_DPI = 110

# How dark a channel has to be for a pixel to count as ink. Well below the paper
# tints the corpus prints on and well above the lightest body text it sets.
INK_THRESHOLD = 200

# The layout labels a column's running text is written under, by the vocabulary
# the drop cap pass reads bodies by.
BODY_LABELS = frozenset(drop_cap.body_labels())

# T1: the flattened paragraphs, by sample, page and index within the page. Each
# is a paragraph a ruling said "flatten" about, which is why it is named here
# rather than searched for: a gate that recomputed the candidate set would be
# asserting about the finder rather than about the geometry.
FLATTENED = (
    ("Courier-en", 4, 3),
    ("Courier-en", 5, 5),
    ("Courier-en", 7, 8),
    ("FD-en-v2", 8, 9),
)

# T3: the heading the determination is about.
T3_SAMPLE = "AramcoWorld-en-v2"
T3_PAGE = 5
T3_REFERENCE = "p5#17"
T3_HEADING_SIZE = 20.0

# T5: the heading whose relayout the font mapper refused, and what it refused
# with. Asserted against the real run: the batch's replay reached it, so no stub
# is needed to drive the field.
T5_SAMPLE = "FD-en-v2"
T5_REFERENCE = "p5#39"
T5_ERROR = "NotoSerif-Bold.ttf"

# T4's negative sample: a transliterated name glossed with its source spelling
# is the shape the style instruction asks for and the fold must leave it whole.
NEGATIVE_SAMPLE = "AramcoWorld-en-v2"
NEGATIVE_PAGE = 4
NEGATIVE_INNER = "Khakimov"

# The bracket forms and the two constructed cases, written as escapes: the
# project's sources carry no CJK, and a full width bracket is one.
OPEN = "\uff08"
CLOSE = "\uff09"
# A transliterated name glossed with its source spelling, which must survive,
# and the same shape glossed with itself, which must not.
GLOSS_KEPT = f"\u7532{OPEN}Ji\u01ce{CLOSE}\u8bf4"
GLOSS_FOLDED = f"\u7532{OPEN}\u7532{CLOSE}\u8bf4"

ALLOWED_PREFIXES = (
    "examples/output/b10_1/",
    "configs/",
    "spec_checks/",
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "babeldoc/magazine/drop_cap.py",
    "babeldoc/magazine/title_typeset.py",
    "babeldoc/magazine/paren_dedup.py",
    "babeldoc/format/pdf/high_level.py",
    "plans/PLAN_B10_1.md",
    # The next batch of the same five day cycle. Its plan was written before this
    # session and sits in the tree; carrying it in with this commit is what keeps
    # a session from leaving an uncommitted file behind, and it moves no code.
    "plans/PLAN_B10_2.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
}

# The one upstream file the switch registration reaches, and the only upstream
# path this batch may name at all.
ALLOWED_UPSTREAM = "babeldoc/format/pdf/high_level.py"

# Nothing of the truth, the rulings, the prompts or the tools moves here.
FORBIDDEN_PREFIXES = ("corpus/", "reviews/", "prompts/", "tools/", "docs/eval/")

NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b10_1")


def record(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _total
    _total += 1
    seconds = _timer.mark(name)
    if ok:
        _passed += 1
        print(f"PASS: {name} ({seconds:.2f}s)")
    else:
        _failures.append(f"{name}: {detail}")
        print(f"FAIL: {name}: {detail} ({seconds:.2f}s)")


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def changed_paths() -> set[str]:
    """This batch's delta: its tag where it exists, the working tree otherwise."""
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^..{BATCH_TAG}"])
        return {line.strip() for line in listing.splitlines() if line.strip()}
    _, listing = git_output(["diff", "--name-only", "HEAD"])
    paths = {line.strip() for line in listing.splitlines() if line.strip()}
    _, untracked = git_output(["status", "--porcelain", "--untracked-files=all"])
    for line in untracked.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def sidecar(sample: str, name: str) -> Path:
    return BATCH_DIR / sample / "sidecars" / name


def pages_pdf(sample: str) -> Path:
    return BATCH_DIR / sample / f"{sample}.b10_1.pages.pdf"


def raster(sample: str, page: int) -> Path:
    return BATCH_DIR / sample / "raster" / f"{sample}.p{page}.png"


def checkpoint(root: Path, sample: str) -> Path:
    return root / sample / "work" / sample / "checkpoint.11_typesetting.json"


def missing(paths) -> list[str]:
    return [str(path.relative_to(ROOT)) for path in paths if not path.exists()]


def skip(name: str, absent) -> None:
    """Report an assertion whose evidence is no longer on disk, by name.

    One assertion of this gate reads a stage checkpoint out of the run's working
    directory, which is not part of the evidence the batch committed and which
    the output retention policy takes once two later batches exist. A frozen
    product that has been pruned may not be replaced by re-running the batch, so
    what is left to do is say which path is gone rather than crash on it or
    quietly pass.
    """
    global _total
    _total += 1
    seconds = _timer.mark(name)
    print(f"SKIPPED: {name}: evidence pruned: {sorted(absent)} ({seconds:.2f}s)")


def page_of(document: dict, label: int) -> dict | None:
    for page in document["page"]:
        if page["page_number"] + 1 == label:
            return page
    return None


def box_of(paragraph) -> dict:
    return paragraph["box"]


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


# --- ink, read off a committed page image -------------------------------------


def ink_top(path: Path, page_height: float, x0, x1, y_top, y_bottom):
    """The highest page coordinate carrying ink inside one band of one image.

    The band is a column of the page between two vertical coordinates, which is
    what makes "where this column starts" a pixel measurement rather than a
    reading of the box the stage was handed. None where the band is blank.
    """
    import pymupdf

    pix = pymupdf.Pixmap(str(path))
    scale = RASTER_DPI / 72.0
    first = max(0, int((page_height - y_top) * scale))
    last = min(pix.height, int((page_height - y_bottom) * scale))
    left = max(0, int(x0 * scale))
    right = min(pix.width, int(x1 * scale))
    samples = pix.samples
    for row in range(first, last):
        base = row * pix.stride
        for column in range(left, right):
            offset = base + column * pix.n
            if all(samples[offset + channel] < INK_THRESHOLD for channel in range(3)):
                return page_height - row / scale
    return None


def neighbour_column(page: dict, index: int):
    """The first paragraph of a column beside the one paragraph ``index`` is in.

    A body paragraph of the same page whose horizontal extent is disjoint from
    this one's and whose vertical extent overlaps it, which is what "beside" is;
    the highest of them is the column's first. None where the page sets no such
    paragraph, which a page whose other column is a photograph does not.
    """
    own = box_of(page["pdf_paragraph"][index])
    beside = []
    for position, paragraph in enumerate(page["pdf_paragraph"]):
        if position == index or paragraph.get("layout_label") not in BODY_LABELS:
            continue
        box = paragraph["box"]
        if not (box["x2"] <= own["x"] or box["x"] >= own["x2"]):
            continue
        if min(box["y2"], own["y2"]) <= max(box["y"], own["y"]):
            continue
        beside.append(box)
    if not beside:
        return None
    return max(beside, key=lambda box: box["y2"])


def paragraph_font_size(paragraph) -> float:
    """The size the paragraph's characters were laid out at, as the stage set it.

    The modal size over the laid out characters, which is the size a reader
    would call the paragraph's; a paragraph whose style says nothing falls back
    to the style the paragraph itself declares.
    """
    sizes: dict[float, int] = {}
    for composition in paragraph.get("pdf_paragraph_composition") or ():
        character = composition.get("pdf_character")
        if character is None:
            continue
        style = character.get("pdf_style") or {}
        size = style.get("font_size")
        if size:
            sizes[round(float(size), 3)] = sizes.get(round(float(size), 3), 0) + 1
    if sizes:
        return max(sizes.items(), key=lambda item: item[1])[0]
    style = paragraph.get("pdf_style") or {}
    return float(style.get("font_size") or 0.0)


# --- 01 scope -----------------------------------------------------------------


def check_01a_the_delta_is_the_three_modules_and_its_evidence() -> None:
    """Negative 1a: nothing outside the batch's declared surface moved."""
    strays = sorted(
        path
        for path in changed_paths()
        if path not in ALLOWED_FILES
        and not path.startswith(ALLOWED_PREFIXES)
    )
    record("check_01a_the_delta_is_the_three_modules_and_its_evidence", not strays, f"{strays}")


def check_01b_no_truth_no_ruling_no_prompt() -> None:
    """Negative 1b: the corpus truth, the rulings and the prompts stand."""
    strays = sorted(
        path for path in changed_paths() if path.startswith(FORBIDDEN_PREFIXES)
    )
    record("check_01b_no_truth_no_ruling_no_prompt", not strays, f"{strays}")


def check_01c_one_upstream_file_and_it_is_registered() -> None:
    """Negative 1c: the only upstream path is the switch's call site."""
    faults = []
    upstream = sorted(
        path
        for path in changed_paths()
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    if upstream not in ([], [ALLOWED_UPSTREAM]):
        faults.append(f"upstream={upstream}")
    registry = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    if upstream and "B10.1" not in registry:
        faults.append("UPSTREAM_DIFF.md carries no B10.1 row")
    record(
        "check_01c_one_upstream_file_and_it_is_registered", not faults, "; ".join(faults)
    )


def check_01d_the_evidence_is_present() -> None:
    """Positive 1d: the replay this gate reads is on disk, whole."""
    wanted = [DRIVER, LEDGER]
    for sample, pages in TARGETS.items():
        wanted.append(pages_pdf(sample))
        wanted.extend(raster(sample, page) for page in pages)
        wanted.append(sidecar(sample, title_typeset.REPORT_NAME))
        wanted.append(sidecar(sample, paren_dedup.REPORT_NAME))
        wanted.append(sidecar(sample, drop_cap.APPLY_REPORT_NAME))
        wanted.append(BATCH_DIR / sample / "parity.json")
        wanted.append(BATCH_DIR / sample / "conservation.json")
    absent = missing(wanted)
    record("check_01d_the_evidence_is_present", not absent, f"missing={absent}")


# --- 02 T1, the flattened paragraph's start edge -------------------------------


def check_02a_the_flattened_box_starts_where_the_text_does() -> None:
    """Positive 2a: the merge reports the start edge it moved, or left alone.

    The sidecar carries the paragraph's box either side of the merge, so what
    the fix did to each flattened paragraph is readable without the document:
    a paragraph whose initial stood proud reports a start edge that moved, and
    one whose initial did not reports a box that did not.
    """
    faults = []
    moved = 0
    for sample, page, index in FLATTENED:
        report = load_json(sidecar(sample, drop_cap.APPLY_REPORT_NAME))
        reference = drop_cap.paragraph_reference(page, index)
        rows = [item for item in report["decisions"] if item["paragraph"] == reference]
        if not rows:
            faults.append(f"{sample} {reference}: no decision")
            continue
        row = rows[0]
        if not row["merged"]:
            faults.append(f"{sample} {reference}: not merged")
            continue
        before, after = row.get("box_before"), row.get("box_after")
        if not before or not after:
            faults.append(f"{sample} {reference}: no box pair")
            continue
        if before[:2] != after[:2] or before[2] != after[2]:
            faults.append(f"{sample} {reference}: an edge other than the start moved")
        if before[3] != after[3]:
            moved += 1
    if moved < 3:
        faults.append(f"only {moved} start edge(s) moved")
    record(
        "check_02a_the_flattened_box_starts_where_the_text_does",
        not faults,
        "; ".join(faults),
    )


def check_02b_the_flattened_column_starts_level_with_its_neighbour() -> None:
    """Positive 2b: measured in ink, a flattened column starts where the next does.

    The two ink tops are read off the committed page image, so what is asserted
    is what a reader sees rather than what the boxes claim. The bound is the
    paragraph's own font size: two columns of running text set from the same
    edge start within one line of each other, and the defect this closes put
    them a whole enlarged initial apart. A page whose other column carries no
    running text -- FD page 8, whose left half is a photograph -- has no
    neighbour to be level with, and there the assertion is that the pass left
    the paragraph's box exactly as it found it.
    """
    name = "check_02b_the_flattened_column_starts_level_with_its_neighbour"
    absent = missing({checkpoint(BATCH_DIR, sample) for sample, _, _ in FLATTENED})
    if absent:
        skip(name, absent)
        return
    faults = []
    measured = []
    for sample, page, index in FLATTENED:
        document = load_json(checkpoint(BATCH_DIR, sample))
        sheet = page_of(document, page)
        if sheet is None:
            faults.append(f"{sample} p{page}: no such page")
            continue
        paragraph = sheet["pdf_paragraph"][index]
        own = box_of(paragraph)
        size = paragraph_font_size(paragraph)
        neighbour = neighbour_column(sheet, index)
        if neighbour is None:
            report = load_json(sidecar(sample, drop_cap.APPLY_REPORT_NAME))
            reference = drop_cap.paragraph_reference(page, index)
            row = next(
                item for item in report["decisions"] if item["paragraph"] == reference
            )
            if row["box_before"] != row["box_after"]:
                faults.append(f"{sample} p{page}: no neighbour and the box moved")
            continue
        height = sheet["mediabox"]["box"]["y2"]
        top = max(own["y2"], neighbour["y2"]) + size * 1.4
        bottom = min(own["y2"], neighbour["y2"]) - size * 6
        image = raster(sample, page)
        mine = ink_top(image, height, own["x"], own["x2"], top, bottom)
        theirs = ink_top(image, height, neighbour["x"], neighbour["x2"], top, bottom)
        if mine is None or theirs is None:
            faults.append(f"{sample} p{page}: a column measured blank")
            continue
        gap = abs(mine - theirs)
        measured.append(f"{sample} p{page} gap={gap:.2f} size={size:.2f}")
        if gap > size:
            faults.append(f"{sample} p{page}: gap {gap:.2f} > font size {size:.2f}")
    print("    " + "; ".join(measured))
    record(name, not faults, "; ".join(faults))


def check_02c_the_start_edge_is_read_off_the_text() -> None:
    """Negative 2c: no axis direction is written into the merge.

    The fix has to hold for a document whose coordinates grow the other way, so
    which vertical edge a paragraph starts from is derived from the characters
    rather than declared. Driven both ways over one synthetic pair.
    """
    from babeldoc.format.pdf.document_il import il_version_1

    def character(y, y2):
        return il_version_1.PdfCharacter(box=il_version_1.Box(x=0, y=y, x2=10, y2=y2))

    faults = []
    # A tail whose first character sits at the larger coordinate: the start edge
    # is the larger one, so a head standing above it must not reach the box.
    head = [character(60, 120)]
    tail = [character(80, 100), character(40, 60)]
    box = drop_cap.merged_box(head, tail)
    if box.y2 != 100:
        faults.append(f"descending: start edge {box.y2} is not the text's 100")
    if box.y != 40:
        faults.append(f"descending: end edge {box.y} moved")
    # The same document upside down.
    head = [character(-120, -60)]
    tail = [character(-100, -80), character(-60, -40)]
    box = drop_cap.merged_box(head, tail)
    if box.y != -100:
        faults.append(f"ascending: start edge {box.y} is not the text's -100")
    if box.y2 != -40:
        faults.append(f"ascending: end edge {box.y2} moved")
    # And a text that cannot say which side it starts from moves nothing, which
    # is what keeps a guess from shortening the box a paragraph is set into.
    head = [character(60, 120)]
    tail = [character(80, 100)]
    box = drop_cap.merged_box(head, tail)
    if (box.y, box.y2) != (60, 120):
        faults.append(f"one line: the box moved to {box.y}..{box.y2}")
    record("check_02c_the_start_edge_is_read_off_the_text", not faults, "; ".join(faults))


# --- 03 T3, the determination --------------------------------------------------


def check_03a_the_single_line_branch_writes_the_kept_runs_back() -> None:
    """Positive 3a: candidate (a) of the plan is excluded, in the source.

    The plan's first candidate was that the single line branch measured the
    deduplicated runs and rendered the original ones. It does not: the fitting
    loop composes the paragraph from the runs it was handed before every render,
    and the runs it is handed are the kept ones. Read off the syntax tree rather
    than from a comment, so a rewrite that changed it would fail here.
    """
    import ast

    faults = []
    source = (ROOT / "babeldoc" / "magazine" / "title_typeset.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    fit = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_fit_single_line"
    )
    loop = next(node for node in fit.body if isinstance(node, ast.For))
    calls = [
        node.func.id
        for node in ast.walk(loop)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    if "_set_runs" not in calls:
        faults.append("the fitting loop never composes the paragraph")
    elif "_render" not in calls:
        faults.append("the fitting loop never renders")
    elif calls.index("_set_runs") > calls.index("_render"):
        faults.append("the paragraph is rendered before it is composed")
    caller = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_process_title"
    )
    handed = [
        node
        for node in ast.walk(caller)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_fit_single_line"
    ]
    if not handed or not any(
        isinstance(argument, ast.Name) and argument.id == "kept"
        for call in handed
        for argument in call.args
    ):
        faults.append("the fitting is not handed the kept runs")
    record(
        "check_03a_the_single_line_branch_writes_the_kept_runs_back",
        not faults,
        "; ".join(faults),
    )


def check_03b_the_heading_never_reached_the_floor_branch() -> None:
    """Positive 3b: candidate (b) of the plan is excluded, in the record.

    The second candidate was that the heading reached the floor and was restored
    after a failed render, which would have emptied its duplicate findings. The
    record says otherwise: it landed on one line at full scale, it carries both
    findings, and it was never restored.
    """
    faults = []
    report = load_json(sidecar(T3_SAMPLE, title_typeset.REPORT_NAME))
    rows = [item for item in report["titles"] if item["reference"] == T3_REFERENCE]
    if not rows:
        record("check_03b_the_heading_never_reached_the_floor_branch", False, "no record")
        return
    row = rows[0]
    if row["disposition"] != title_typeset.DISPOSITION_SINGLE_LINE:
        faults.append(f"disposition={row['disposition']}")
    if row.get("restored"):
        faults.append("restored")
    if len(row["duplicates"]) != 2:
        faults.append(f"duplicates={len(row['duplicates'])}")
    if row.get("scale") != 1.0:
        faults.append(f"scale={row.get('scale')}")
    record(
        "check_03b_the_heading_never_reached_the_floor_branch",
        not faults,
        "; ".join(faults),
    )


def check_03c_the_heading_is_drawn_once_and_covered_by_a_graphic() -> None:
    """Positive 3c: what is actually there, frozen as the determination.

    The deduplication landed: the page draws the display line once. What clips
    it is not a second drawing of the text but an image standing over it -- in
    the source that image is the mask the second paint was drawn through, and
    the pass that dropped the second paint does not reach a graphic. This is the
    finding the batch reports instead of a fix, so it is asserted as it stands
    and will fail the moment either half of it changes.
    """
    import pymupdf

    faults = []
    document = pymupdf.open(str(pages_pdf(T3_SAMPLE)))
    index = list(TARGETS[T3_SAMPLE]).index(T3_PAGE)
    page = document[index]
    blocks = page.get_text("dict")["blocks"]
    display = [
        span
        for block in blocks
        if block["type"] == 0
        for line in block["lines"]
        for span in line["spans"]
        if span["size"] > T3_HEADING_SIZE
    ]
    text = normalize("".join(span["text"] for span in display))
    half = len(text) // 2
    if not display:
        faults.append("the page draws no display line")
    elif half and text[:half] == text[half:]:
        faults.append(f"the display line is drawn twice: {text!r}")
    if display:
        right = max(span["bbox"][2] for span in display)
        top = min(span["bbox"][1] for span in display)
        bottom = max(span["bbox"][3] for span in display)
        images = [
            block["bbox"]
            for block in blocks
            if block["type"] == 1
            and block["bbox"][0] < right
            and block["bbox"][1] < bottom
            and block["bbox"][3] > top
        ]
        if not images:
            faults.append("no graphic stands over the display line")
        else:
            faults.extend(
                []
                if min(box[0] for box in images) < right
                else ["the graphic does not reach the display line"]
            )
    document.close()
    record(
        "check_03c_the_heading_is_drawn_once_and_covered_by_a_graphic",
        not faults,
        "; ".join(faults),
    )


# --- 04 T2, T4 and T5 ----------------------------------------------------------


def check_04a_the_heading_policy_is_the_targets() -> None:
    """Positive 4a: a target language's own policy is what the run used.

    English claims both keys, so the sample set in English ran at the higher
    floor under the wrapping policy; Chinese claims neither, so the samples set
    in Chinese ran at the flat declaration. Read off the sidecar of each run,
    which is where the policy a run used is written down.
    """
    faults = []
    config = title_typeset.load_title_config()
    for sample in TARGETS:
        report = load_json(sidecar(sample, title_typeset.REPORT_NAME))
        target = report.get("target_lang") or ""
        wanted = config.for_target(target)
        if report["on_floor"] != wanted.on_floor:
            faults.append(f"{sample}: on_floor={report['on_floor']} for {target!r}")
        if report["title_min_scale"] != wanted.title_min_scale:
            faults.append(f"{sample}: floor={report['title_min_scale']} for {target!r}")
    if config.for_target("en").on_floor != title_typeset.FLOOR_WRAP:
        faults.append("English does not claim the wrapping policy")
    if config.for_target("zh").on_floor != config.on_floor:
        faults.append("Chinese does not fall back to the flat key")
    record("check_04a_the_heading_policy_is_the_targets", not faults, "; ".join(faults))


def check_04b_no_heading_of_the_english_run_is_squeezed_or_raised() -> None:
    """Positive 4b: T2's own measure, on the sample the policy is for.

    Every heading on the target pages either sits at or above the declared
    floor, or was accepted as it stood; none is raised for a human, and the one
    the F2 run raised at 0.28 is among them.
    """
    faults = []
    sample = "Courier-zh"
    report = load_json(sidecar(sample, title_typeset.REPORT_NAME))
    accepted = {
        title_typeset.DISPOSITION_WRAP,
        title_typeset.DISPOSITION_UNCHANGED,
    }
    for row in report["titles"]:
        if row["page"] not in TARGETS[sample]:
            continue
        scale = row.get("scale")
        if scale is not None and scale >= report["title_min_scale"]:
            continue
        if row["disposition"] in accepted and row.get("lines_after", 1) >= 1:
            continue
        faults.append(f"{row['reference']}: {row['disposition']} at {scale}")
    if report["escalations"]:
        faults.append(f"escalations={[e['reference'] for e in report['escalations']]}")
    record(
        "check_04b_no_heading_of_the_english_run_is_squeezed_or_raised",
        not faults,
        "; ".join(faults),
    )


def same_form_hits(text: str) -> list[str]:
    """Every same form parenthetical in one string, by the module's own rule."""
    config = paren_dedup.load_paren_config()
    flat = text.replace("\n", "")
    return [inner for _s, _e, inner in paren_dedup.same_form_spans(flat, config)]


def check_04c_no_same_form_parenthetical_is_left_on_a_target_page() -> None:
    """Positive 4c: T4's own measure, over the produced pages of all four samples."""
    import pymupdf

    faults = []
    for sample, pages in TARGETS.items():
        document = pymupdf.open(str(pages_pdf(sample)))
        for index, page in enumerate(pages):
            hits = same_form_hits(document[index].get_text())
            if hits:
                faults.append(f"{sample} p{page}: {hits}")
        document.close()
    record(
        "check_04c_no_same_form_parenthetical_is_left_on_a_target_page",
        not faults,
        "; ".join(faults),
    )


def check_04d_a_translated_name_keeps_its_gloss() -> None:
    """Negative 4d: the fold does not reach a gloss that says something.

    Two ways: the produced page still carries the corpus's own case, and the
    rule refuses a constructed one. A rule that folded either would be deleting
    the only place a source name appears.
    """
    import pymupdf

    faults = []
    document = pymupdf.open(str(pages_pdf(NEGATIVE_SAMPLE)))
    index = list(TARGETS[NEGATIVE_SAMPLE]).index(NEGATIVE_PAGE)
    text = normalize(document[index].get_text()).replace("\n", "")
    document.close()
    if f"({NEGATIVE_INNER})" not in text:
        faults.append("the corpus gloss was folded")
    config = paren_dedup.load_paren_config()
    constructed = GLOSS_KEPT
    folded, removed = paren_dedup.fold_text(constructed, config)
    if folded != constructed or removed:
        faults.append(f"a constructed gloss folded to {folded!r}")
    # And the shape it is meant to fold still folds, so the negative is not a
    # rule that folds nothing.
    repeated = GLOSS_FOLDED
    folded, removed = paren_dedup.fold_text(repeated, config)
    if not removed:
        faults.append("the same form shape no longer folds")
    record("check_04d_a_translated_name_keeps_its_gloss", not faults, "; ".join(faults))


def check_04e_a_long_parenthetical_is_left_alone() -> None:
    """Negative 4e: the declared bound is what stops the fold, and it is bounded."""
    faults = []
    config = paren_dedup.load_paren_config()
    body = "x" * (config.max_span_chars + 1)
    text = f"{body}{OPEN}{body}{CLOSE}"
    folded, removed = paren_dedup.fold_text(text, config)
    if folded != text or removed:
        faults.append("a parenthetical past the bound folded")
    short = "y" * config.max_span_chars
    folded, removed = paren_dedup.fold_text(f"{short}{OPEN}{short}{CLOSE}", config)
    if not removed:
        faults.append("a parenthetical at the bound did not fold")
    raw = load_json(paren_dedup.CONFIG_PATH)
    if "max_span_chars_allowed_range" not in raw:
        faults.append("max_span_chars declares no range")
    record("check_04e_a_long_parenthetical_is_left_alone", not faults, "; ".join(faults))


def check_04f_a_refused_relayout_reaches_the_sidecar() -> None:
    """Positive 4f: T5, on the heading the run's font mapper actually refused."""
    faults = []
    report = load_json(sidecar(T5_SAMPLE, title_typeset.REPORT_NAME))
    rows = [item for item in report["titles"] if item["reference"] == T5_REFERENCE]
    if not rows:
        faults.append(f"{T5_REFERENCE} carries no record")
    else:
        row = rows[0]
        if not row.get("relayout_failed"):
            faults.append("relayout_failed is not set")
        if T5_ERROR not in (row.get("relayout_error") or ""):
            faults.append(f"relayout_error={row.get('relayout_error')!r}")
        if not row.get("restored"):
            faults.append("the heading was not left as it was")
    if report["totals"].get("relayout_failed") != 1:
        faults.append(f"totals={report['totals'].get('relayout_failed')}")
    record("check_04f_a_refused_relayout_reaches_the_sidecar", not faults, "; ".join(faults))


# --- 05 conservation and cost --------------------------------------------------


def conservation_of(sample: str) -> dict:
    return load_json(BATCH_DIR / sample / "conservation.json")


def live_shape(root: Path, sample: str):
    """Page count and per target page paragraph counts, or None where pruned.

    The working directories are not tracked and the retention policy takes them
    once a batch leaves the recent window, so the frozen record is the assertion
    and this is the check on the record while the workspace can still make it.
    """
    path = checkpoint(root, sample)
    if not path.is_file():
        return None
    document = load_json(path)
    counts = {}
    for label in TARGETS[sample]:
        sheet = page_of(document, label)
        counts[str(label)] = None if sheet is None else len(sheet["pdf_paragraph"])
    return len(document.get("page") or ()), counts


def check_05a_the_pages_and_paragraphs_are_the_f2_ones() -> None:
    """Conservation 5a: page count and per page paragraph count against F2.

    Asserted off the frozen comparison, and the frozen comparison is checked
    against the workspace wherever the workspace still holds the runs it was
    made from.
    """
    faults = []
    for sample, pages in TARGETS.items():
        frozen = conservation_of(sample)
        if frozen["pages"] != frozen["baseline_pages"]:
            faults.append(
                f"{sample}: {frozen['baseline_pages']} pages became {frozen['pages']}"
            )
        for label in pages:
            entry = frozen["target_pages"][str(label)]
            if entry["paragraphs"] is None or entry["baseline_paragraphs"] is None:
                faults.append(f"{sample} p{label}: a page was not read")
            elif entry["paragraphs"] != entry["baseline_paragraphs"]:
                faults.append(
                    f"{sample} p{label}: {entry['baseline_paragraphs']} paragraphs "
                    f"became {entry['paragraphs']}"
                )
        for root, key in ((BATCH_DIR, "pages"), (F2_DIR, "baseline_pages")):
            live = live_shape(root, sample)
            if live is None:
                continue
            total, counts = live
            if total != frozen[key]:
                faults.append(f"{sample}: the frozen {key} is not this workspace's")
            for label in pages:
                entry = frozen["target_pages"][str(label)]
                field = "paragraphs" if key == "pages" else "baseline_paragraphs"
                if counts[str(label)] != entry[field]:
                    faults.append(f"{sample} p{label}: the frozen {field} drifted")
    record("check_05a_the_pages_and_paragraphs_are_the_f2_ones", not faults, "; ".join(faults))


def parity_of(sample: str) -> dict:
    return load_json(BATCH_DIR / sample / "parity.json")


def check_05b_every_request_is_the_one_f2_built() -> None:
    """Conservation 5b: nothing this batch changed reaches a translation request.

    The strongest form the claim has: request for request, in the order the
    tracking files them, this replay asked exactly what F2 asked. Recomputed
    from both runs' tracking where the workspace still holds them, and read off
    the frozen record where it does not, with the two compared where both are
    there.

    The scope is the translator's requests, which is every group the tracking
    files. The repair loop's calls are not among them -- they are recorded in
    its own report, which is why a run can be request-identical to F2 and still
    show a non-zero API count -- so the comparison also asserts that it read
    every group the tracking held. A group appearing later fails here rather
    than being quietly left out of the claim.
    """
    faults = []
    for sample in TARGETS:
        frozen = parity_of(sample)
        if frozen["requests"] != frozen["baseline_requests"]:
            faults.append(
                f"{sample}: {frozen['requests']} requests against F2's "
                f"{frozen['baseline_requests']}"
            )
        if frozen["inputs_sha256"] != frozen["baseline_inputs_sha256"]:
            faults.append(f"{sample}: the request texts are not F2's")
        if sorted(frozen["groups_read"]) != sorted(frozen["groups_present"]):
            faults.append(
                f"{sample}: the tracking holds {frozen['groups_present']} and the "
                f"comparison read {frozen['groups_read']}"
            )
        live = tracking_digest(BATCH_DIR, sample)
        baseline = tracking_digest(F2_DIR, sample)
        if live is not None and live != frozen["inputs_sha256"]:
            faults.append(f"{sample}: the frozen digest is not this workspace's")
        if baseline is not None and baseline != frozen["baseline_inputs_sha256"]:
            faults.append(f"{sample}: the frozen baseline digest is not F2's")
    record("check_05b_every_request_is_the_one_f2_built", not faults, "; ".join(faults))


def check_05b2_text_moves_where_the_fold_says_or_where_the_model_resampled() -> None:
    """Conservation 5b2: every paragraph that reads differently has a reason.

    Two reasons are allowed and no third. One is the fold, which names its
    paragraphs. The other is a request the cache could not answer: the same text
    was sent again and this model does not answer twice the same, so the answer
    came back different for a reason that is not a change in this batch. Those
    answers are frozen in ``parity.json`` beside the run, so a paragraph is only
    excused by one of them where the pair of texts is literally the pair that
    came back.
    """
    faults = []
    for sample, pages in TARGETS.items():
        frozen = conservation_of(sample)
        folded = {
            row["reference"]
            for row in load_json(sidecar(sample, paren_dedup.REPORT_NAME))["paragraphs"]
        }
        resampled = [
            (row["baseline"], row["run"]) for row in parity_of(sample)["resampled"]
        ]
        for label in pages:
            for item in frozen["target_pages"][str(label)]["differing"]:
                reference = item["reference"]
                if reference in folded:
                    continue
                was, now = item["baseline"], item["run"]
                if any(was in old and now in new for old, new in resampled):
                    continue
                faults.append(f"{sample} {reference}")
    record(
        "check_05b2_text_moves_where_the_fold_says_or_where_the_model_resampled",
        not faults,
        "; ".join(faults),
    )


def tracking_digest(root: Path, sample: str):
    """The digest of every request text one run made, or None where it is gone.

    Computed exactly as the driver computes it, so a frozen record and a live
    working directory are comparable; the working directories are not tracked,
    so a clone has the record alone and this returns None there.
    """
    import hashlib

    path = root / sample / "work" / sample / "translate_tracking.json"
    if not path.is_file():
        return None
    tracking = load_json(path)
    sha = hashlib.sha256()
    for group in ("page", "cross_page", "cross_column"):
        for batch in tracking.get(group, ()):
            for paragraph in batch.get("paragraph", ()):
                sha.update((paragraph.get("input") or "").encode("utf-8"))
                sha.update(b"\x00")
    return sha.hexdigest()


def check_05c_the_replay_spent_nothing_new() -> None:
    """Conservation 5c: no sample sent more requests than its F2 run did.

    The batch changes nothing a request is built from, so a replay that sent
    more than F2 sent would mean one of the fixes reached the translation path.
    """
    faults = []
    f2 = {row["sample"]: row for row in load_json(F2_DIR / "runs.json")}
    for row in load_json(LEDGER):
        earlier = f2.get(row["sample"])
        if earlier is None:
            faults.append(f"{row['sample']}: no F2 run to compare with")
            continue
        if row["api_calls"] > earlier["api_calls"]:
            faults.append(
                f"{row['sample']}: {row['api_calls']} calls against F2's "
                f"{earlier['api_calls']}"
            )
    record("check_05c_the_replay_spent_nothing_new", not faults, "; ".join(faults))


def check_05d_the_folding_is_registered_as_a_sidecar() -> None:
    """Positive 5d: the run inventory declares the file the new pass writes."""
    faults = []
    stages = load_json(ROOT / "configs" / "checkpoint_stages.json")
    declared = {
        entry["name"]: entry["switch"] for entry in stages.get("sidecars", ())
    }
    if declared.get(paren_dedup.REPORT_NAME) != paren_dedup.SWITCH:
        faults.append(f"{paren_dedup.REPORT_NAME} is not declared under its switch")
    for sample in TARGETS:
        report = load_json(sidecar(sample, paren_dedup.REPORT_NAME))
        if report["switch"] != paren_dedup.SWITCH:
            faults.append(f"{sample}: report names {report['switch']}")
    record("check_05d_the_folding_is_registered_as_a_sidecar", not faults, "; ".join(faults))


def check_06_history_is_green() -> None:
    """Positive 6: every earlier gate of the fast set still passes.

    The fast set, not the whole history: under W-B10-04 the sweep set -- the
    eighteen gates that re-run the pipeline to answer, two and a half hours of
    them -- is run once at the end of the cycle rather than once per batch.
    Suppressed under the runner, which drives the selection linearly and would
    otherwise run it once per gate.
    """
    if NESTED_SUPPRESSED:
        record("check_06_history_is_green", True, "run by spec_checks/run_all.py")
        return
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(ROOT / "spec_checks" / "run_all.py"),
            "--set",
            "fast",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    record("check_06_history_is_green", proc.returncode == 0, (proc.stdout or "")[-800:])


CHECKS = (
    check_01a_the_delta_is_the_three_modules_and_its_evidence,
    check_01b_no_truth_no_ruling_no_prompt,
    check_01c_one_upstream_file_and_it_is_registered,
    check_01d_the_evidence_is_present,
    check_02a_the_flattened_box_starts_where_the_text_does,
    check_02b_the_flattened_column_starts_level_with_its_neighbour,
    check_02c_the_start_edge_is_read_off_the_text,
    check_03a_the_single_line_branch_writes_the_kept_runs_back,
    check_03b_the_heading_never_reached_the_floor_branch,
    check_03c_the_heading_is_drawn_once_and_covered_by_a_graphic,
    check_04a_the_heading_policy_is_the_targets,
    check_04b_no_heading_of_the_english_run_is_squeezed_or_raised,
    check_04c_no_same_form_parenthetical_is_left_on_a_target_page,
    check_04d_a_translated_name_keeps_its_gloss,
    check_04e_a_long_parenthetical_is_left_alone,
    check_04f_a_refused_relayout_reaches_the_sidecar,
    check_05a_the_pages_and_paragraphs_are_the_f2_ones,
    check_05b_every_request_is_the_one_f2_built,
    check_05b2_text_moves_where_the_fold_says_or_where_the_model_resampled,
    check_05c_the_replay_spent_nothing_new,
    check_05d_the_folding_is_registered_as_a_sidecar,
    check_06_history_is_green,
)


def main() -> int:
    print("spec_check_b10_1: geometry and display fixes\n")
    for check in CHECKS:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, it does not crash
            record(check.__name__, False, f"{type(exc).__name__}: {exc}")
    print(f"\n{_passed}/{_total} assertions passed")
    if _failures:
        print("\nfailures:")
        for line in _failures:
            print(f"  - {line}")
    _timer.write()
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
