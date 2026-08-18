"""Gate script for batch B9.4: the drop cap ruling is consumed.

Run from the repository root:

    python spec_checks/spec_check_b9_4.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: the one translation stage this gate builds is built around a
stub engine declared in this file, and every document is built here too, which is
what lets the mechanics be asserted one property at a time.

What this batch does. B7 wrote ``dropCapDecision`` into the intermediate language
and nothing read it. This batch reads it. Behind ``magazine_drop_cap_apply``,
down by default, and after the ruling is injected and before the translator is
built, ``flatten`` merges the enlarged initial into the text it opens so the
first word reaches the engine as a word, and ``keep`` leaves the paragraph as an
unruled one is left. A candidate nobody ruled takes the default its target
language declares.

01 is the switch: down by default, refused without the pass that finds the
candidates a default answers, and with it down the document is byte for byte the
one that came in and no sidecar appears.

02 is the initial, and it is where the F1 candidate gap was. The signal is read
off the paragraph's leading characters rather than off its first composition,
because the styling stage groups the body sized letters after an enlarged initial
into a formula with it: an initial in a style run and an initial inside a formula
are both read here, and the widening is asserted to be additive on the frozen
corpus rather than merely different.

03 is the merge itself, property by property: what a style run held, what a
formula held, the synthesised separator that is dropped, the drawn space that is
never dropped, the later composition that is left alone, and the identity of a
paragraph ruled keep.

04 is the payoff, measured through the upstream reader that builds a request. A
flattened paragraph is offered as plain text with no placeholder around its
initial; the same paragraph before the merge hides its whole first word behind a
formula placeholder, which is why that word came back untranslated.

05 is the machine default: per target language, matched by prefix, reaching a
marked candidate only, and outranked by a ruling.

06 is the sidecar, whose record shape and source vocabulary are declared in the
configuration and asserted against what the pass builds, and whose name is in the
run inventory. The marking report names its consumer, which is the note a reader
of an unchanged run needs.

07 is the configuration: bounded, refused when a bound or a vocabulary is broken,
and drawing its verdict vocabulary from the one file that declares verdicts.

08 is scope: no upstream file, no ground truth, no ruling, and no page type named
in the pass.

10 is the acceptance, replayed from the evidence this batch commits: what the
merge did to every real request, the towering initial measured away on the
finished document against the same bound that found it, the pages outside a ruled
one that did not move with both document level channels asserted shut, the
candidate F1 found carried out to a draft rather than answered, and the Vogue
residues accounted for one by one.

09 is the sweep.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.midend import il_translator  # noqa: E402
from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.checkpoint import sidecar_products  # noqa: E402
from babeldoc.magazine.checkpoint import to_checkpoint_xml  # noqa: E402
from babeldoc.progress_monitor import ProgressMonitor  # noqa: E402
from babeldoc.translator.translator import BaseTranslator  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b9.4"

PYTHON = sys.executable

RUNNER = ROOT / "spec_checks" / "run_all.py"
MODULE = ROOT / "babeldoc" / "magazine" / "drop_cap.py"
HOOK = ROOT / "babeldoc" / "magazine" / "hitl.py"
CONFIG = ROOT / "configs" / "drop_cap.json"
HITL_CONFIG = ROOT / "configs" / "hitl.json"

# The frozen F1 run, which is where the corpus wide additivity of the widened
# initial signal is measured. Untracked, so its absence is a skip and not a
# failure: the archive is a workspace artefact and this gate never writes it.
FINAL_ARCHIVE = ROOT / "examples" / "output" / "final.zip"
FINAL_MEMBER = "final/{sample}/work/{sample}/{name}"
FINAL_SAMPLES = (
    "AramcoWorld-en-v2",
    "CERNCourier-en",
    "Courier-en",
    "Courier-zh",
    "FD-en-v2",
    "Vogue-en",
)
CHECKPOINT_MEMBER = "checkpoint.08_chain_builder.xml"

# This batch's own evidence tree.
EVIDENCE_DIR = ROOT / "examples" / "output" / "b9_4"
EVIDENCE = EVIDENCE_DIR / "evidence.json"

# Paths this session may change.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "spec_checks/",
    "examples/output/b9_4/",
    # The sweep ends by applying the output retention policy, which archives a
    # batch falling out of the keep window into this tree.
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "plans/PLAN_B9_4.md",
    # The two gaps this session registered, which is the one edit outside code
    # the plan authorises.
    "docs/eval/gap_register.md",
    "examples/output/run_all.b9_4.log",
}

# Prefixes no session of this batch may touch. The review tree holds the ruling
# and the corpus tree the ground truth; both are the user's.
FORBIDDEN_PREFIXES = ("corpus/", "reviews/", "prompts/")

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

BODY_FONT = "body"
INITIAL_FONT = "initial"
BODY_SIZE = 10.0
INITIAL_SIZE = 30.0

# What a built body paragraph reads like beyond its initial, long enough that the
# paragraph's median character size is the body size.
TAIL = (
    "ong before satellites orbited Earth, navigators crossed thousands of miles "
    "of open ocean by reading stars, swells and the flight of birds"
)

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b9_4")
_stage: il_translator.ILTranslator | None = None


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


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    """This session's delta: its tag where it exists, the working tree otherwise."""
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


# --- documents built here ------------------------------------------------------


def style(font: str, size: float):
    return il_version_1.PdfStyle(
        font_id=font,
        font_size=size,
        graphic_state=il_version_1.GraphicState(),
    )


def character(text: str, x: float, y: float, width: float, size: float, font: str):
    """One character as the frontend reads it off a page: drawn, so it has an id."""
    box = il_version_1.Box(x=x, y=y, x2=x + width, y2=y + size)
    return il_version_1.PdfCharacter(
        char_unicode=text,
        box=box,
        visual_bbox=il_version_1.VisualBbox(box=copy.deepcopy(box)),
        pdf_style=style(font, size),
        advance=width / size,
        vertical=False,
        xobj_id=0,
    )


def filler_space(x: float, y: float, width: float, size: float, font: str):
    """The space the paragraph finder fills a drawing gap with.

    Built exactly as ``layout_helper.add_space_dummy_chars`` builds one: the
    advance is the width of the box rather than a font advance, and no xobject id
    is set, because no content stream drew it.
    """
    box = il_version_1.Box(x=x, y=y, x2=x + width, y2=y + size)
    return il_version_1.PdfCharacter(
        char_unicode=" ",
        box=box,
        visual_bbox=il_version_1.VisualBbox(box=copy.deepcopy(box)),
        pdf_style=style(font, size),
        advance=width,
        vertical=False,
    )


def run_composition(characters):
    boxes = [item.box for item in characters]
    return il_version_1.PdfParagraphComposition(
        pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
            box=il_version_1.Box(
                x=min(item.x for item in boxes),
                y=min(item.y for item in boxes),
                x2=max(item.x2 for item in boxes),
                y2=max(item.y2 for item in boxes),
            ),
            pdf_style=characters[0].pdf_style,
            pdf_character=list(characters),
        )
    )


def formula_composition(characters):
    boxes = [item.box for item in characters]
    return il_version_1.PdfParagraphComposition(
        pdf_formula=il_version_1.PdfFormula(
            box=il_version_1.Box(
                x=min(item.x for item in boxes),
                y=min(item.y for item in boxes),
                x2=max(item.x2 for item in boxes),
                y2=max(item.y2 for item in boxes),
            ),
            pdf_character=list(characters),
        )
    )


def letters(text: str, x: float, y: float, size: float, font: str, width: float):
    characters = []
    cursor = x
    for letter in text:
        characters.append(character(letter, cursor, y, width, size, font))
        cursor += width
    return characters


def paragraph_of(compositions, label: str = "plain text", debug_id: str = "built"):
    characters = [
        item
        for composition in compositions
        for item in line_split.composition_characters(
            composition, line_split.composition_kind(composition)
        )
    ]
    boxes = [item.box for item in characters]
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(
            x=min(item.x for item in boxes),
            y=min(item.y for item in boxes),
            x2=max(item.x2 for item in boxes),
            y2=max(item.y2 for item in boxes),
        ),
        pdf_style=style(BODY_FONT, BODY_SIZE),
        pdf_paragraph_composition=list(compositions),
        xobj_id=0,
        # The text as the paragraph finder recorded it, which is every character
        # in order, filler space included. That space is what splits the first
        # word in two.
        unicode="".join(item.char_unicode or "" for item in characters),
        vertical=False,
        first_line_indent=False,
        debug_id=debug_id,
        layout_label=label,
        layout_id=1,
        render_order=1,
    )


def style_run_initial(debug_id: str = "style_run"):
    """A drop cap in a style run of its own, with the filler space after it.

    The Courier-en shape: the initial and the space stand in one style run at the
    display size, the rest of the paragraph in a second run at the body size, and
    the recorded text opens ``L ong``.
    """
    initial = [
        character("L", 80.0, 700.0, 26.0, INITIAL_SIZE, INITIAL_FONT),
        filler_space(106.0, 700.0, 3.0, INITIAL_SIZE, INITIAL_FONT),
    ]
    tail = letters(TAIL, 110.0, 720.0, BODY_SIZE, BODY_FONT, 5.0)
    return paragraph_of([run_composition(initial), run_composition(tail)], debug_id=debug_id)


def formula_initial(debug_id: str = "formula"):
    """A drop cap the styling stage grouped into a formula with its own word.

    The FD-en-v2 shape, and the F1 candidate gap: the display sized ``W`` and the
    body sized ``hen`` are one formula because the letters after an enlarged
    initial are read as corner marks, so the whole first word is inside a unit the
    request carries as a placeholder.
    """
    grouped = [
        character("W", 80.0, 700.0, 26.0, INITIAL_SIZE, INITIAL_FONT),
        *letters("hen", 106.0, 720.0, BODY_SIZE, BODY_FONT, 5.0),
        character(" ", 121.0, 720.0, 3.0, BODY_SIZE, BODY_FONT),
    ]
    tail = letters(
        "it comes to international trade, countries have always weighed openness "
        "against the risks of depending on one another for what they need",
        124.0,
        720.0,
        BODY_SIZE,
        BODY_FONT,
        5.0,
    )
    return paragraph_of(
        [formula_composition(grouped), run_composition(tail)], debug_id=debug_id
    )


def drawn_space_initial(debug_id: str = "drawn"):
    """An initial whose following space the source itself drew.

    The case the separator rule has to leave alone: a space with an xobject id is
    a space the content stream carries, so closing the break would join two words
    that were never one.
    """
    initial = [
        character("A", 80.0, 700.0, 26.0, INITIAL_SIZE, INITIAL_FONT),
        character(" ", 106.0, 700.0, 3.0, INITIAL_SIZE, INITIAL_FONT),
    ]
    tail = letters(
        "dog barks at the postman every morning and twice on a saturday, which is "
        "the whole of what this built paragraph has to say for itself",
        110.0,
        720.0,
        BODY_SIZE,
        BODY_FONT,
        5.0,
    )
    return paragraph_of([run_composition(initial), run_composition(tail)], debug_id=debug_id)


def initial_then_formula(debug_id: str = "trailing"):
    """A drop cap paragraph carrying a formula further along.

    The merge closes one boundary. Everything after the run it merges into is the
    request's business and has to arrive untouched.
    """
    initial = [
        character("L", 80.0, 700.0, 26.0, INITIAL_SIZE, INITIAL_FONT),
        filler_space(106.0, 700.0, 3.0, INITIAL_SIZE, INITIAL_FONT),
    ]
    tail = letters(TAIL, 110.0, 720.0, BODY_SIZE, BODY_FONT, 5.0)
    formula = formula_composition(letters("E=mc", 500.0, 720.0, BODY_SIZE, BODY_FONT, 5.0))
    return paragraph_of(
        [run_composition(initial), run_composition(tail), formula], debug_id=debug_id
    )


def plain_paragraph(debug_id: str = "plain"):
    """A body paragraph with no initial at all."""
    return paragraph_of(
        [run_composition(letters(TAIL, 80.0, 600.0, BODY_SIZE, BODY_FONT, 5.0))],
        debug_id=debug_id,
    )


def page_of(paragraphs, number: int = 0):
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=il_version_1.Box(0.0, 0.0, 631.5, 807.0)),
        cropbox=il_version_1.Cropbox(box=il_version_1.Box(0.0, 0.0, 631.5, 807.0)),
        pdf_paragraph=list(paragraphs),
        page_number=number,
        unit="point",
    )


def document_of(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


class Config:
    """The attributes the drop cap passes read off a translation configuration."""

    def __init__(
        self,
        directory: Path,
        *,
        apply_switch: object = True,
        mark_switch: object = True,
        group_switch: object = True,
        lang_out: str = "zh",
    ):
        self.directory = Path(directory)
        self.lang_out = lang_out
        if apply_switch is not None:
            setattr(self, drop_cap.APPLY_SWITCH, apply_switch)
        if mark_switch is not None:
            setattr(self, drop_cap.MARK_SWITCH, mark_switch)
        if group_switch is not None:
            setattr(self, drop_cap.GROUP_SWITCH, group_switch)

    def get_working_file_path(self, name: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        return str(self.directory / name)


def settings() -> drop_cap.DropCapConfig:
    return drop_cap.load_drop_cap_config()


def working_directory() -> Path:
    return Path(tempfile.mkdtemp(prefix="spec_b9_4_"))


def write_article_map(directory: Path, pages: list[int]) -> None:
    """One article covering the pages given, as the grouping stage writes it."""
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "articles": [
            {"article_id": "A1", "pages": pages, "start_page": min(pages)}
        ],
        "counts": {"articles": 1},
        "pages": pages,
    }
    with (directory / article_builder.REPORT_NAME).open("w", encoding="utf-8") as f:
        json.dump(payload, f)


def apply_to(docs, **attributes) -> tuple[dict | None, Path]:
    directory = working_directory()
    result = drop_cap.apply(Config(directory, **attributes), hitl.labeled_pages(docs))
    return result, directory


def canonical(docs) -> str:
    return to_checkpoint_xml(docs)


def compositions_of(paragraph) -> list[str]:
    return [
        line_split.composition_kind(item)
        for item in paragraph.pdf_paragraph_composition or ()
    ]


def characters_of(paragraph) -> list[str]:
    return [
        item.char_unicode or ""
        for item in line_split.paragraph_characters(paragraph)
    ]


# --- 01 the switch --------------------------------------------------------------


def check_01a_the_switch_is_down_by_default() -> None:
    """Negative 1a: nothing set, nothing read, nothing written.

    The whole default position of this batch. A caller who set no attribute gets
    a pass that returns None, a document that is byte for byte the one it was and
    a working directory with no sidecar in it.
    """
    faults = []

    class Bare:
        def __init__(self, directory: Path):
            self.directory = directory
            self.lang_out = "zh"

        def get_working_file_path(self, name: str) -> str:
            return str(self.directory / name)

    docs = document_of([page_of([style_run_initial(), plain_paragraph()], number=0)])
    docs.page[0].pdf_paragraph[0].drop_cap_candidate = True
    docs.page[0].pdf_paragraph[0].drop_cap_decision = drop_cap.DECISION_FLATTEN
    before = canonical(docs)
    directory = working_directory()
    if drop_cap.apply_enabled(Bare(directory)):
        faults.append("the switch reads as up on a configuration that sets nothing")
    result = drop_cap.apply(Bare(directory), hitl.labeled_pages(docs))
    if result is not None:
        faults.append(f"the pass returned {type(result).__name__} with the switch down")
    if canonical(docs) != before:
        faults.append("the document changed with the switch down")
    if (directory / drop_cap.APPLY_REPORT_NAME).exists():
        faults.append("a sidecar was written with the switch down")
    record("check_01a_the_switch_is_down_by_default", not faults, "; ".join(faults))


def check_01b_apply_without_marking_is_refused() -> None:
    """Negative 1b: acting on defaults without the finding they answer is refused.

    Not degraded silently: the verdict an unruled candidate takes is decided from
    the candidate mark, so a run that raised this switch alone would report
    deciding nothing while the reason was that nothing had been found.
    """
    faults = []
    docs = document_of([page_of([style_run_initial()], number=0)])
    directory = working_directory()
    lonely = Config(directory, mark_switch=False)
    try:
        drop_cap.apply(lonely, hitl.labeled_pages(docs))
    except drop_cap.DropCapError:
        pass
    else:
        faults.append("the pass degraded silently instead of refusing")
    # And the refusal is on the dependency alone: with both up it runs.
    result, _ = apply_to(document_of([page_of([style_run_initial()], number=0)]))
    if result is None:
        faults.append("the pass returned nothing with both switches up")
    record("check_01b_apply_without_marking_is_refused", not faults, "; ".join(faults))


# --- 02 the initial, and the candidate gap it closes ----------------------------


def marked(docs, pages: list[int]) -> list[str]:
    """The candidate references of one built document, through the marking pass."""
    directory = working_directory()
    write_article_map(directory, pages)
    config = Config(directory)
    return [
        candidate.reference
        for candidate in drop_cap.mark(config, hitl.labeled_pages(docs))
    ]


def check_02a_an_initial_in_a_style_run_is_read() -> None:
    """Positive 2a: the shape the signal was written for is still read."""
    faults = []
    config = settings()
    paragraph = style_run_initial()
    run = drop_cap.leading_run(paragraph, config.initial_size_tolerance)
    if run is None:
        faults.append("no leading run was read")
    else:
        if run.text != "L ":
            faults.append(f"the run text is {run.text!r}")
        if run.span != 2:
            faults.append(f"the run spans {run.span} characters")
        median = drop_cap.median_font_size(paragraph)
        if not median or run.size / median < config.min_first_run_size_ratio:
            faults.append(f"the ratio is {run.size}/{median}")
    docs = document_of([page_of([paragraph], number=0)])
    if marked(docs, [1]) != ["p1#0"]:
        faults.append(f"the marking pass found {marked(docs, [1])}")
    record("check_02a_an_initial_in_a_style_run_is_read", not faults, "; ".join(faults))


def check_02b_an_initial_inside_a_formula_is_read() -> None:
    """Positive 2b: the F1 candidate gap, closed.

    ``FD-en-v2`` page 8 opens with a drop cap the styling stage grouped into a
    formula together with the rest of its word, and the signal that consulted the
    first style run found nothing there. Read off the characters, the same initial
    is an initial.
    """
    faults = []
    config = settings()
    paragraph = formula_initial()
    if compositions_of(paragraph)[0] != "pdf_formula":
        faults.append("the built shape does not open with a formula")
    run = drop_cap.leading_run(paragraph, config.initial_size_tolerance)
    if run is None or run.text != "W":
        faults.append(f"the leading run is {run}")
    docs = document_of([page_of([paragraph], number=0)])
    if marked(docs, [1]) != ["p1#0"]:
        faults.append(f"the marking pass found {marked(docs, [1])}")
    record("check_02b_an_initial_inside_a_formula_is_read", not faults, "; ".join(faults))


def frozen_work(sample: str, name: str, into: Path) -> Path | None:
    member = FINAL_MEMBER.format(sample=sample, name=name)
    with zipfile.ZipFile(FINAL_ARCHIVE) as archive:
        if member not in archive.namelist():
            return None
        archive.extract(member, into)
    return into / member


def former_candidates(labeled, article_of_page, openers, config, labels) -> list[str]:
    """The candidate set as the signal read it before this batch widened it.

    The reference implementation lives here rather than in the package, because
    what it is for is to say that the widening added and removed nothing: a
    superset claim needs both sets, and only one of them is code that ships.
    """
    found = []
    rank_of_article: dict[str, int] = {}
    for label, page in labeled:
        article_id = article_of_page.get(label)
        for index, paragraph in enumerate(page.pdf_paragraph):
            text = (paragraph.unicode or "").strip()
            if paragraph.layout_label not in labels or not text:
                continue
            if article_id is None:
                continue
            rank = rank_of_article.get(article_id, 0) + 1
            rank_of_article[article_id] = rank
            opens = label in openers
            if rank > config.max_body_rank_in_article and not opens:
                continue
            compositions = paragraph.pdf_paragraph_composition or []
            run = compositions[0].pdf_same_style_characters if compositions else None
            if run is None or run.pdf_style is None:
                continue
            size = run.pdf_style.font_size
            median = drop_cap.median_font_size(paragraph)
            if not size or not median:
                continue
            initial = "".join(
                item.char_unicode or "" for item in run.pdf_character
            ).strip()
            if not initial or len(initial) > config.max_first_run_chars:
                continue
            if size / median < config.min_first_run_size_ratio:
                continue
            found.append(drop_cap.paragraph_reference(label, index))
    return found


def check_02c_the_widening_is_additive_on_the_corpus() -> None:
    """Positive 2c: over the frozen corpus the new signal loses nothing.

    Read only, out of the frozen archive into a temporary directory. Skipped
    rather than failed where the archive is not in the workspace, because it is
    untracked and this gate never writes it.
    """
    if not FINAL_ARCHIVE.is_file():
        print(
            f"SKIPPED: check_02c_the_widening_is_additive_on_the_corpus "
            f"({FINAL_ARCHIVE.relative_to(ROOT)} is not in the workspace)"
        )
        return
    config = settings()
    labels = drop_cap.body_labels()
    faults = []
    tally = {"old": 0, "new": 0, "gained": 0}
    into = working_directory()
    for sample in FINAL_SAMPLES:
        checkpoint = frozen_work(sample, CHECKPOINT_MEMBER, into)
        article_map = frozen_work(sample, article_builder.REPORT_NAME, into)
        report = frozen_work(sample, drop_cap.REPORT_NAME, into)
        if checkpoint is None or article_map is None or report is None:
            faults.append(f"{sample}: the archive carries no frozen work directory")
            continue
        docs = load_checkpoint(str(checkpoint))
        labeled = hitl.labeled_pages(docs)
        article_of_page, openers = drop_cap.read_article_map(article_map)
        before = former_candidates(labeled, article_of_page, openers, config, labels)
        after = [
            candidate.reference
            for candidate in drop_cap.find_candidates(
                labeled, article_of_page, openers, config, labels
            )
        ]
        frozen_refs = [
            item["paragraph"]
            for item in json.loads(report.read_text(encoding="utf-8"))["candidates"]
        ]
        # The reference implementation has to reproduce the frozen report, or it
        # is not the signal that ran.
        if before != frozen_refs:
            faults.append(f"{sample}: recomputed {before}, the run recorded {frozen_refs}")
        lost = sorted(set(before) - set(after))
        if lost:
            faults.append(f"{sample}: the widening lost {lost}")
        tally["old"] += len(before)
        tally["new"] += len(after)
        tally["gained"] += len(set(after) - set(before))
    if tally["gained"] < 1:
        faults.append("the widening gained nothing, so it closes no gap")
    record(
        "check_02c_the_widening_is_additive_on_the_corpus",
        not faults,
        "; ".join(faults[:4]) or f"tally={tally}",
    )


# --- 03 the merge ---------------------------------------------------------------


def check_03a_a_style_run_initial_is_merged_and_the_word_closed() -> None:
    """Positive 3a: two runs become one, and ``L ong`` becomes ``Long``."""
    faults = []
    config = settings()
    paragraph = style_run_initial()
    before_characters = characters_of(paragraph)
    outcome = drop_cap.flatten(paragraph, config)
    if not outcome["merged"]:
        faults.append("nothing was merged")
    if outcome["separator_dropped"] != 1:
        faults.append(f"{outcome['separator_dropped']} separator(s) dropped")
    if compositions_of(paragraph) != ["pdf_same_style_characters"]:
        faults.append(f"the compositions are {compositions_of(paragraph)}")
    run = paragraph.pdf_paragraph_composition[0].pdf_same_style_characters
    if run.pdf_style is not paragraph.pdf_style:
        faults.append("the merged run does not declare the paragraph's own style")
    if not (paragraph.unicode or "").startswith("Long before"):
        faults.append(f"the text opens {paragraph.unicode[:14]!r}")
    after_characters = characters_of(paragraph)
    if after_characters != [before_characters[0], *before_characters[2:]]:
        faults.append("the characters are not the source characters less the filler")
    if outcome["characters_merged"] != len(after_characters):
        faults.append(
            f"the record counts {outcome['characters_merged']} of {len(after_characters)}"
        )
    record(
        "check_03a_a_style_run_initial_is_merged_and_the_word_closed",
        not faults,
        "; ".join(faults),
    )


def check_03b_a_formula_initial_is_merged_and_the_text_untouched() -> None:
    """Positive 3b: the formula stops being a formula, and no character moves.

    Nothing is dropped here: the space after ``When`` was drawn by the source, so
    the recorded text is already the text it should be and the merge only changes
    what carries the characters.
    """
    faults = []
    config = settings()
    paragraph = formula_initial()
    before_text = paragraph.unicode
    before_characters = characters_of(paragraph)
    outcome = drop_cap.flatten(paragraph, config)
    if not outcome["merged"]:
        faults.append("nothing was merged")
    if outcome["separator_dropped"] != 0:
        faults.append("a drawn space was dropped")
    if compositions_of(paragraph) != ["pdf_same_style_characters"]:
        faults.append(f"the compositions are {compositions_of(paragraph)}")
    if paragraph.unicode != before_text:
        faults.append("the recorded text changed")
    if characters_of(paragraph) != before_characters:
        faults.append("a character was lost or added")
    record(
        "check_03b_a_formula_initial_is_merged_and_the_text_untouched",
        not faults,
        "; ".join(faults),
    )


def check_03c_a_drawn_space_is_never_dropped() -> None:
    """Negative 3c: an initial that is a word of its own keeps its space.

    The one thing the separator rule must not do. A space carrying an xobject id
    was drawn by the source, and joining across it would make two words one.
    """
    faults = []
    config = settings()
    paragraph = drawn_space_initial()
    before_text = paragraph.unicode
    outcome = drop_cap.flatten(paragraph, config)
    if not outcome["merged"]:
        faults.append("nothing was merged")
    if outcome["separator_dropped"] != 0:
        faults.append(f"{outcome['separator_dropped']} drawn space(s) dropped")
    if paragraph.unicode != before_text:
        faults.append(f"the text became {paragraph.unicode[:12]!r}")
    if not (paragraph.unicode or "").startswith("A dog"):
        faults.append("the two words were joined")
    record("check_03c_a_drawn_space_is_never_dropped", not faults, "; ".join(faults))


def check_03d_a_later_composition_is_left_alone() -> None:
    """Negative 3d: the merge closes one boundary and no other."""
    faults = []
    config = settings()
    paragraph = initial_then_formula()
    formula_before = paragraph.pdf_paragraph_composition[2].pdf_formula
    outcome = drop_cap.flatten(paragraph, config)
    if not outcome["merged"]:
        faults.append("nothing was merged")
    kinds = compositions_of(paragraph)
    if kinds != ["pdf_same_style_characters", "pdf_formula"]:
        faults.append(f"the compositions are {kinds}")
    elif paragraph.pdf_paragraph_composition[1].pdf_formula is not formula_before:
        faults.append("the trailing formula was rebuilt")
    record("check_03d_a_later_composition_is_left_alone", not faults, "; ".join(faults))


def check_03e_keep_is_the_document_that_came_in() -> None:
    """Positive 3e: a paragraph ruled keep is byte for byte an unruled one.

    Asserted against the document a run with no verdict at all leaves, which is
    the only definition of unchanged that means anything here.
    """
    faults = []
    verdicts = drop_cap.decision_vocabulary()
    keep = next(item for item in verdicts if item != drop_cap.DECISION_FLATTEN)

    def built(decision: str | None):
        docs = document_of([page_of([style_run_initial(), plain_paragraph()], number=0)])
        paragraph = docs.page[0].pdf_paragraph[0]
        paragraph.drop_cap_candidate = True
        paragraph.drop_cap_decision = decision
        return docs

    ruled = built(keep)
    result, directory = apply_to(ruled)
    reference = built(keep)
    # The reference is the same document with the pass never run over it, minus
    # the attribute the ruling wrote, which is on both.
    if canonical(ruled) != canonical(reference):
        faults.append("a paragraph ruled keep was changed")
    if result is None or result["totals"]["merged"] != 0:
        faults.append(f"the record reports {result and result['totals']}")
    if result is not None and result["totals"]["decided"] != 1:
        faults.append("the verdict was not recorded")
    if not (directory / drop_cap.APPLY_REPORT_NAME).exists():
        faults.append("no sidecar was written")
    record("check_03e_keep_is_the_document_that_came_in", not faults, "; ".join(faults))


# --- 04 what the request carries ------------------------------------------------


class Stub(BaseTranslator):
    """An engine that answers nothing over the wire and is never asked to."""

    name = "b9-4-stub"

    def do_translate(self, text, rate_limit_params: dict = None):
        return text

    def do_llm_translate(self, text, rate_limit_params: dict = None):
        return json.dumps([{"id": 0, "output": text}])


def translator_stage() -> il_translator.ILTranslator:
    """The upstream reader that turns a paragraph into a request, built once."""
    global _stage
    if _stage is not None:
        return _stage
    work = working_directory()
    monitor = ProgressMonitor([(il_translator.ILTranslator.stage_name, 1.0)])
    monitor.disable = True
    config = TranslationConfig(
        translator=Stub("en", "zh", ignore_cache=True),
        input_file="Sample.pdf",
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        working_dir=work,
        output_dir=work / "out",
        progress_monitor=monitor,
        auto_extract_glossary=False,
        qps=1,
    )
    _stage = il_translator.ILTranslator(config.translator, config)
    return _stage


def offered(paragraph):
    """What the request would carry for one paragraph, and its placeholders."""
    prepared = translator_stage().get_translate_input(
        paragraph, {}, disable_rich_text_translate=True
    )
    return prepared.unicode, list(prepared.placeholders or ())


def check_04a_the_flattened_paragraph_is_offered_whole() -> None:
    """Positive 4a: after the merge the request carries the text and no placeholder.

    Measured through the upstream reader that builds every request, so the claim
    is about what the engine is asked rather than about what this pass believes.
    """
    faults = []
    config = settings()
    for name, paragraph in (
        ("style run", style_run_initial()),
        ("formula", formula_initial()),
    ):
        drop_cap.flatten(paragraph, config)
        text, placeholders = offered(paragraph)
        if placeholders:
            faults.append(f"{name}: {len(placeholders)} placeholder(s) remain")
        if text != paragraph.unicode:
            faults.append(f"{name}: the request carries {text[:20]!r}")
    record(
        "check_04a_the_flattened_paragraph_is_offered_whole", not faults, "; ".join(faults)
    )


def check_04b_before_the_merge_the_first_word_is_hidden() -> None:
    """Positive 4b: the defect, measured on the shapes as they arrive.

    A formula held initial takes the whole first word out of the request and puts
    a placeholder in its place, which is why that word comes back in the source
    script. An initial in a style run leaves the word split at the filler space.
    """
    faults = []
    text, placeholders = offered(formula_initial())
    if not placeholders:
        faults.append("the formula shape carried no placeholder before the merge")
    if "When" in text:
        faults.append("the first word reached the request after all")
    split, _ = offered(style_run_initial())
    if not split.startswith("L "):
        faults.append(f"the style run shape opens {split[:6]!r}")
    record(
        "check_04b_before_the_merge_the_first_word_is_hidden", not faults, "; ".join(faults)
    )


# --- 05 the machine default -----------------------------------------------------


def check_05a_the_default_is_per_target_language() -> None:
    """Positive 5a: the declared table decides, matched by longest prefix."""
    faults = []
    config = settings()
    flattening = [
        tag for tag in config.defaults if config.defaults[tag] == drop_cap.DECISION_FLATTEN
    ]
    if not flattening:
        faults.append("no target language declares the verdict this pass acts on")
    for tag in flattening:
        docs = document_of([page_of([style_run_initial()], number=0)])
        docs.page[0].pdf_paragraph[0].drop_cap_candidate = True
        result, _ = apply_to(docs, lang_out=f"{tag}-Hant")
        if result is None or result["totals"]["merged"] != 1:
            faults.append(f"{tag}: nothing was merged under the declared default")
        if result is not None and result["decisions"][0]["source"] != drop_cap.SOURCE_DEFAULT:
            faults.append(f"{tag}: the source is {result['decisions'][0]['source']}")
    keeping = [
        tag for tag in config.defaults if config.defaults[tag] != drop_cap.DECISION_FLATTEN
    ]
    for tag in keeping:
        docs = document_of([page_of([style_run_initial()], number=0)])
        docs.page[0].pdf_paragraph[0].drop_cap_candidate = True
        before = canonical(docs)
        result, _ = apply_to(docs, lang_out=tag)
        if canonical(docs) != before:
            faults.append(f"{tag}: the document changed under a keeping default")
        if result is None or result["totals"]["merged"] != 0:
            faults.append(f"{tag}: something was merged")
    record("check_05a_the_default_is_per_target_language", not faults, "; ".join(faults))


def check_05b_an_unclaimed_language_decides_nothing() -> None:
    """Negative 5b: a target language no entry claims leaves candidates alone."""
    faults = []
    config = settings()
    unclaimed = "qqq"
    if config.default_for(unclaimed) is not None:
        faults.append(f"{unclaimed} resolves to {config.default_for(unclaimed)}")
    docs = document_of([page_of([style_run_initial()], number=0)])
    docs.page[0].pdf_paragraph[0].drop_cap_candidate = True
    before = canonical(docs)
    result, _ = apply_to(docs, lang_out=unclaimed)
    if canonical(docs) != before:
        faults.append("the document changed under an unclaimed language")
    if result is None or result["totals"]["decided"] != 0:
        faults.append(f"the record decided {result and result['totals']['decided']}")
    record("check_05b_an_unclaimed_language_decides_nothing", not faults, "; ".join(faults))


def check_05c_a_ruling_outranks_the_default() -> None:
    """Positive 5c: the human answer wins, and reaches a non candidate too."""
    faults = []
    verdicts = drop_cap.decision_vocabulary()
    keep = next(item for item in verdicts if item != drop_cap.DECISION_FLATTEN)
    docs = document_of([page_of([style_run_initial()], number=0)])
    paragraph = docs.page[0].pdf_paragraph[0]
    paragraph.drop_cap_candidate = True
    paragraph.drop_cap_decision = keep
    result, _ = apply_to(docs, lang_out="zh")
    if result is None or result["totals"]["merged"] != 0:
        faults.append("the default overrode the ruling")
    if result is not None and result["decisions"][0]["source"] != drop_cap.SOURCE_RULED:
        faults.append(f"the source is {result['decisions'][0]['source']}")

    # A ruling on a paragraph the marking pass never flagged is the human's to
    # make, exactly as a ruling on terms may name a source nobody proposed.
    docs = document_of([page_of([style_run_initial()], number=0)])
    docs.page[0].pdf_paragraph[0].drop_cap_decision = drop_cap.DECISION_FLATTEN
    result, _ = apply_to(docs, lang_out="en")
    if result is None or result["totals"]["merged"] != 1:
        faults.append("a ruling on a non candidate was not acted on")
    if result is not None and result["decisions"][0]["was_candidate"]:
        faults.append("the record claims the paragraph was a candidate")
    record("check_05c_a_ruling_outranks_the_default", not faults, "; ".join(faults))


def check_05d_a_paragraph_nobody_found_is_not_swept() -> None:
    """Negative 5d: the default answers a finding, and never a whole page."""
    faults = []
    docs = document_of(
        [page_of([style_run_initial(), plain_paragraph(), formula_initial()], number=0)]
    )
    docs.page[0].pdf_paragraph[0].drop_cap_candidate = True
    before = [canonical(document_of([page_of([item])])) for item in docs.page[0].pdf_paragraph[1:]]
    result, _ = apply_to(docs, lang_out="zh")
    after = [canonical(document_of([page_of([item])])) for item in docs.page[0].pdf_paragraph[1:]]
    if before != after:
        faults.append("a paragraph carrying no candidate mark was changed")
    if result is None or result["totals"]["decided"] != 1:
        faults.append(f"the record decided {result and result['totals']['decided']}")
    record("check_05d_a_paragraph_nobody_found_is_not_swept", not faults, "; ".join(faults))


# --- 06 the sidecar -------------------------------------------------------------


def check_06a_the_report_has_the_declared_shape() -> None:
    """Positive 6a: every record is the shape the configuration declares."""
    faults = []
    config = settings()
    docs = document_of([page_of([style_run_initial(), formula_initial()], number=0)])
    for paragraph in docs.page[0].pdf_paragraph:
        paragraph.drop_cap_candidate = True
    result, directory = apply_to(docs, lang_out="zh")
    if result is None:
        record("check_06a_the_report_has_the_declared_shape", False, "no record")
        return
    for item in result["decisions"]:
        if set(item) != set(config.apply_fields):
            faults.append(f"a record carries {sorted(item)}")
        if item["source"] not in config.decision_sources:
            faults.append(f"a record names source {item['source']!r}")
    totals = result["totals"]
    if totals["decided"] != len(result["decisions"]):
        faults.append("the totals do not count the records")
    if totals["merged"] != sum(1 for item in result["decisions"] if item["merged"]):
        faults.append("the merged total is not the records")
    if totals["separators_dropped"] != sum(
        item["separator_dropped"] for item in result["decisions"]
    ):
        faults.append("the separator total is not the records")
    path = directory / drop_cap.APPLY_REPORT_NAME
    if not path.exists():
        faults.append("no sidecar on disk")
    else:
        written = json.loads(path.read_text(encoding="utf-8"))
        if written != result:
            faults.append("the sidecar is not the record the pass returned")
    record("check_06a_the_report_has_the_declared_shape", not faults, "; ".join(faults))


def check_06b_a_record_of_the_wrong_shape_is_refused() -> None:
    """Negative 6b: a field the configuration does not declare stops the run."""
    faults = []
    config = settings()
    narrowed = drop_cap.DropCapConfig(
        min_first_run_size_ratio=config.min_first_run_size_ratio,
        max_first_run_chars=config.max_first_run_chars,
        max_body_rank_in_article=config.max_body_rank_in_article,
        excerpt_chars=config.excerpt_chars,
        initial_size_tolerance=config.initial_size_tolerance,
        separator_policy=config.separator_policy,
        decision_sources=config.decision_sources,
        apply_fields=config.apply_fields[:-1],
        defaults=config.defaults,
    )
    docs = document_of([page_of([style_run_initial()], number=0)])
    docs.page[0].pdf_paragraph[0].drop_cap_candidate = True
    original = drop_cap.load_drop_cap_config
    drop_cap.load_drop_cap_config = lambda *_: narrowed  # type: ignore[assignment]
    try:
        apply_to(docs, lang_out="zh")
    except drop_cap.DropCapError:
        pass
    else:
        faults.append("a record outside the declared shape was accepted")
    finally:
        drop_cap.load_drop_cap_config = original  # type: ignore[assignment]
    record("check_06b_a_record_of_the_wrong_shape_is_refused", not faults, "; ".join(faults))


def check_06c_the_sidecar_is_in_the_inventory() -> None:
    """Positive 6c: the run's products stay enumerable without running one."""
    faults = []
    declared = {entry["name"]: entry for entry in sidecar_products()}
    entry = declared.get(drop_cap.APPLY_REPORT_NAME)
    if entry is None:
        faults.append(f"{drop_cap.APPLY_REPORT_NAME} is not declared")
    else:
        if entry.get("switch") != drop_cap.APPLY_SWITCH:
            faults.append(f"the declaration names switch {entry.get('switch')!r}")
        if not entry.get("stage"):
            faults.append("the declaration names no stage")
    record("check_06c_the_sidecar_is_in_the_inventory", not faults, "; ".join(faults))


def check_06d_the_marking_report_names_its_consumer() -> None:
    """Positive 6d: a run whose ruling changed nothing says why in its inventory."""
    faults = []
    docs = document_of([page_of([style_run_initial()], number=0)])
    directory = working_directory()
    write_article_map(directory, [1])
    drop_cap.mark(Config(directory), hitl.labeled_pages(docs))
    path = directory / drop_cap.REPORT_NAME
    if not path.exists():
        record("check_06d_the_marking_report_names_its_consumer", False, "no report")
        return
    consumers = json.loads(path.read_text(encoding="utf-8"))["decision_consumers"]
    if not consumers:
        faults.append("the report still says nothing consumes the verdict")
    flattened = json.dumps(consumers)
    for token in (drop_cap.APPLY_SWITCH, drop_cap.APPLY_REPORT_NAME):
        if token not in flattened:
            faults.append(f"the consumer entry does not name {token}")
    record(
        "check_06d_the_marking_report_names_its_consumer", not faults, "; ".join(faults)
    )


# --- 07 the configuration -------------------------------------------------------


def check_07a_the_configuration_is_bounded() -> None:
    """Positive 7a: every number declares a range and sits inside it."""
    faults = []
    raw = json.loads(text_of(CONFIG))
    for key, value in raw.items():
        if key in ("description", *drop_cap._STRUCTURAL_KEYS) or key.endswith(
            "_allowed_range"
        ):
            continue
        if isinstance(value, list):
            if not value:
                faults.append(f"{key} is an empty vocabulary")
            continue
        low, high = (float(part) for part in raw[f"{key}_allowed_range"].split(".."))
        if not low <= float(value) <= high:
            faults.append(f"{key}={value} outside {low}..{high}")
    record("check_07a_the_configuration_is_bounded", not faults, "; ".join(faults))


def check_07b_a_broken_declaration_is_refused() -> None:
    """Negative 7b: one fault each, across every rule the reader holds."""
    raw = json.loads(text_of(CONFIG))
    probes = {}
    probes["separator outside its vocabulary"] = {
        **raw,
        drop_cap.SEPARATOR_KEY: "invent",
    }
    probes["vocabulary without the closing policy"] = {
        **raw,
        drop_cap.SEPARATOR_VOCABULARY_KEY: ["keep"],
        drop_cap.SEPARATOR_KEY: "keep",
    }
    probes["default outside the verdicts"] = {
        **raw,
        drop_cap.DEFAULTS_KEY: {
            **raw[drop_cap.DEFAULTS_KEY],
            drop_cap.ENTRIES_KEY: {"zh": "invent"},
        },
    }
    probes["defaults with no entries"] = {
        **raw,
        drop_cap.DEFAULTS_KEY: {drop_cap.DESCRIPTION_KEY: "empty"},
    }
    probes["a number outside its range"] = {**raw, "initial_size_tolerance": 99.0}
    probes["a source the records may name is gone"] = {
        **raw,
        "decision_sources": [drop_cap.SOURCE_RULED],
    }
    faults = []
    for name, payload in probes.items():
        try:
            drop_cap.parse_drop_cap_config(payload, "probe")
        except drop_cap.DropCapError:
            continue
        faults.append(f"accepted: {name}")
    # And the shipped file itself still parses, so the probes are probes.
    try:
        drop_cap.parse_drop_cap_config(raw, CONFIG.name)
    except drop_cap.DropCapError as exc:
        faults.append(f"the shipped configuration is refused: {exc}")
    record("check_07b_a_broken_declaration_is_refused", not faults, "; ".join(faults))


def check_07c_the_verdicts_come_from_one_file() -> None:
    """Positive 7c: no second list of verdicts, and no page type in the pass."""
    faults = []
    declared = json.loads(text_of(HITL_CONFIG))[drop_cap.HITL_DECISIONS_KEY]
    if list(drop_cap.decision_vocabulary()) != list(declared):
        faults.append("the pass reads a vocabulary the review layer does not declare")
    raw = json.loads(text_of(CONFIG))
    for key, value in raw.items():
        if not isinstance(value, list) or key.endswith("_allowed_range"):
            continue
        if set(value) == set(declared) and key != drop_cap.SEPARATOR_VOCABULARY_KEY:
            faults.append(f"{key} repeats the verdict vocabulary")
    # No page type name reaches the pass, which is the standing rule for every
    # policy consumer in this package.
    source = text_of(MODULE)
    from babeldoc.magazine.taxonomy import load_taxonomy

    for page_type in load_taxonomy().page_types:
        if re.search(rf'"{re.escape(page_type.name)}"', source):
            faults.append(f"the module names page type {page_type.name}")
    record("check_07c_the_verdicts_come_from_one_file", not faults, "; ".join(faults))


def check_07d_the_pass_runs_before_the_translator() -> None:
    """Positive 7d: the window the merge has to happen in is the one it runs in.

    The hook this runs from is the last point at which a paragraph can be changed
    before the translation stage is constructed, and the merge has to be last
    inside it so a ruling injected earlier in the same hook is what it acts on.
    """
    faults = []
    hook = text_of(HOOK)
    body = hook.split("def after_term_extract", 1)
    if len(body) != 2:
        record("check_07d_the_pass_runs_before_the_translator", False, "no hook")
        return
    body = body[1].split("\ndef ", 1)[0]
    if "drop_cap.apply(" not in body:
        faults.append("the hook does not run the pass")
    else:
        if body.index("drop_cap.apply_decisions(") > body.index("drop_cap.apply("):
            faults.append("the pass runs before the ruling is injected")
        tail = body[body.index("drop_cap.apply(") :]
        if "hitl_apply" in tail:
            faults.append("the pass is inside the ruling branch")
    high_level = text_of(
        ROOT / "babeldoc" / "format" / "pdf" / "high_level.py"
    )
    if "hitl.after_term_extract" not in high_level:
        faults.append("the pipeline does not call the hook")
    else:
        hook_at = high_level.index("hitl.after_term_extract")
        built_at = high_level.index("ILTranslatorLLMOnly(translate_engine")
        if hook_at > built_at:
            faults.append("the hook runs after the translator is built")
    record("check_07d_the_pass_runs_before_the_translator", not faults, "; ".join(faults))


# --- 10 the acceptance, replayed from frozen evidence ---------------------------


def acceptance() -> dict | None:
    if not EVIDENCE.is_file():
        return None
    with EVIDENCE.open(encoding="utf-8") as f:
        return json.load(f)


def check_10a_every_ruled_site_reached_the_request() -> None:
    """Positive 10a: what the merge did to the request, on the real samples.

    The deterministic half of the acceptance. For every site a verdict reached
    and the merge acted on, the request the arm with the switch up built has to
    differ from the one the arm with it down built, and it has to carry no
    placeholder: a placeholder is the shape the whole first word was hidden in.
    """
    evidence = acceptance()
    if evidence is None:
        record(
            "check_10a_every_ruled_site_reached_the_request",
            False,
            f"{EVIDENCE.relative_to(ROOT)} is not in the workspace",
        )
        return
    faults = []
    merged = [site for site in evidence["sites"] if site["merged"]]
    if not merged:
        faults.append("no site was merged, so the acceptance measured nothing")
    for site in merged:
        where = f"{site['sample']}:{site['paragraph']}"
        if site["decision"] != drop_cap.DECISION_FLATTEN:
            faults.append(f"{where}: merged under verdict {site['decision']!r}")
        if site["placeholders_on"] != 0:
            faults.append(f"{where}: {site['placeholders_on']} placeholder(s) remain")
        if site["offered_on"] == site["offered_off"]:
            faults.append(f"{where}: the request did not change")
        if site["offered_on"] is None or site["offered_off"] is None:
            faults.append(f"{where}: no request was recorded in one arm")
    for site in evidence["sites"]:
        if site["decision"] == drop_cap.DECISION_FLATTEN and not site["merged"]:
            faults.append(f"{site['sample']}:{site['paragraph']}: flatten merged nothing")
    record(
        "check_10a_every_ruled_site_reached_the_request", not faults, "; ".join(faults[:4])
    )


def check_10b_the_towering_initial_is_gone() -> None:
    """Positive 10b: the typographic claim, measured on the finished document.

    Read off the paragraph as the typesetting stage left it, and against the
    shipped bound rather than against a number written here: an initial that
    survived is at least ``min_first_run_size_ratio`` times the paragraph's own
    median character size, which is the same test that found it a candidate.
    """
    evidence = acceptance()
    if evidence is None:
        record(
            "check_10b_the_towering_initial_is_gone",
            False,
            f"{EVIDENCE.relative_to(ROOT)} is not in the workspace",
        )
        return
    ratio = settings().min_first_run_size_ratio
    faults = []
    for site in evidence["sites"]:
        if not site["merged"]:
            continue
        where = f"{site['sample']}:{site['paragraph']}"
        median = site["median_glyph_on"]
        before = site["opening_glyph_off"]
        after = site["opening_glyph_on"]
        if None in (median, before, after):
            faults.append(f"{where}: a glyph size is missing")
            continue
        if before < median * ratio:
            faults.append(
                f"{where}: the arm with the switch down opens at {before} against "
                f"a median of {median}, so there was no drop cap to remove"
            )
        if after >= median * ratio:
            faults.append(f"{where}: the opening is still {after} against {median}")
    record("check_10b_the_towering_initial_is_gone", not faults, "; ".join(faults[:4]))


def check_10c_nothing_reached_an_unruled_paragraph() -> None:
    """Negative 10c: the soul assertion, with the two channels measured.

    A page that moved and that the control reproduced is a page this switch is
    answerable for, and every one of them has to be a page a verdict stands on.
    The two document level channels b9.3 found are asserted shut rather than
    argued shut: the automatic glossary is the same table in both arms, because
    the merge runs after the extractor has read the document, and the requests are
    composed of the same paragraphs, because the merge changes no paragraph count.

    A page that rendered differently outside a ruled one is reported rather than
    asserted away, which is this project's attribution floor: what is held here is
    that every such page carries a stated mechanism and that the translated
    document did not move on it. One does, and the mechanism is the repair loop's
    own uncached decision.
    """
    evidence = acceptance()
    if evidence is None:
        record(
            "check_10c_nothing_reached_an_unruled_paragraph",
            False,
            f"{EVIDENCE.relative_to(ROOT)} is not in the workspace",
        )
        return
    faults = []
    for item in evidence["spill"]:
        sample = item["sample"]
        attributable = [
            label
            for label in item["text_moved"]
            if label not in item["control_text_moved"]
        ]
        outside = [label for label in attributable if label not in item["ruled_pages"]]
        if outside:
            faults.append(f"{sample}: pages {outside} moved outside a ruled page")
        if not item["glossary_identical"]:
            faults.append(
                f"{sample}: the glossary channel is open, "
                f"{item['glossary_changed_entries']} entry(ies) differ"
            )
        if not item["batch_composition_identical"]:
            faults.append(f"{sample}: the request composition channel is open")
        # A page that rendered differently outside a ruled one is not asserted
        # away: the attribution floor of this project reports it with the
        # mechanism that produced it, and what is asserted is that every such
        # page carries one and that the translated document did not move there.
        for row in item["raster_exceptions"]:
            if not row["attribution"]:
                faults.append(
                    f"{sample}: page {row['page']} rendered differently with nothing "
                    f"stated about why"
                )
            if row["text_moved"]:
                faults.append(
                    f"{sample}: page {row['page']} is outside every ruled page and "
                    f"its translated text moved"
                )
    record(
        "check_10c_nothing_reached_an_unruled_paragraph", not faults, "; ".join(faults[:4])
    )


def check_10d_the_found_candidate_and_the_draft() -> None:
    """Positive 10d: the F1 candidate is found, defaulted on, and left to a human.

    Found by the widened signal, acted on under the declared default because
    nobody has ruled it, and carried out to a draft that is not in the review
    directory: the answer to it is the user's.
    """
    evidence = acceptance()
    if evidence is None:
        record(
            "check_10d_the_found_candidate_and_the_draft",
            False,
            f"{EVIDENCE.relative_to(ROOT)} is not in the workspace",
        )
        return
    faults = []
    defaulted = [
        site for site in evidence["sites"] if site["source"] == drop_cap.SOURCE_DEFAULT
    ]
    if not defaulted:
        faults.append("no site was decided by the declared default")
    for site in defaulted:
        if site["was_candidate"] is not True:
            faults.append(f"{site['sample']}:{site['paragraph']} was not a candidate")
    ruled = [
        site for site in evidence["sites"] if site["source"] == drop_cap.SOURCE_RULED
    ]
    if not ruled:
        faults.append("no site was decided by a ruling")
    draft = evidence.get("draft")
    if not draft:
        faults.append("no candidate draft was written")
    elif not (ROOT / draft).is_file():
        faults.append(f"{draft} is not in the workspace")
    elif draft.startswith("reviews/"):
        faults.append("the draft was written into the review directory")
    else:
        payload = json.loads((ROOT / draft).read_text(encoding="utf-8"))
        rows = payload.get("drop_caps") or []
        if not rows:
            faults.append("the draft carries no candidate row")
        for row in rows:
            if "decision" in row or "verdict" in row:
                faults.append("the draft states an answer as well as a question")
    record("check_10d_the_found_candidate_and_the_draft", not faults, "; ".join(faults[:4]))


def check_10e_the_residues_are_outside_the_signal() -> None:
    """Positive 10e: the Vogue observation is recorded, with a reason per residue.

    Not a repair and not a claim: the two Latin residues F1 recorded on that page
    are fragments rather than paragraphs opening with an initial, and what this
    holds is that the evidence says so for each of them rather than leaving them
    unaccounted for.
    """
    evidence = acceptance()
    if evidence is None:
        record(
            "check_10e_the_residues_are_outside_the_signal",
            False,
            f"{EVIDENCE.relative_to(ROOT)} is not in the workspace",
        )
        return
    vogue = evidence["vogue"]
    faults = []
    if not vogue.get("available"):
        record(
            "check_10e_the_residues_are_outside_the_signal",
            False,
            f"the observation was not measured: {vogue.get('reason')}",
        )
        return
    if not vogue["residues"]:
        faults.append("the page carries no residue, so the observation found nothing")
    for item in vogue["residues"]:
        if item["is_candidate"]:
            faults.append(f"{item['paragraph']} is a candidate and is not answered for")
        elif not item["reasons"]:
            faults.append(f"{item['paragraph']} is outside the signal for no stated reason")
    record(
        "check_10e_the_residues_are_outside_the_signal", not faults, "; ".join(faults[:4])
    )


def check_10f_the_evidence_is_committed() -> None:
    """Positive 10f: the acceptance rests on files this batch commits.

    A number quoted from a workspace file nobody tracked is a number that stops
    being checkable at the next sweep, which is the loss b9.2r registered.
    """
    faults = []
    evidence = acceptance()
    wanted = [EVIDENCE, EVIDENCE_DIR / "report.md"]
    if evidence is not None:
        wanted.extend(ROOT / name for name in evidence["fixtures"])
        if evidence.get("draft"):
            wanted.append(ROOT / evidence["draft"])
    for path in wanted:
        if not path.is_file():
            faults.append(f"{path.relative_to(ROOT).as_posix()} is missing")
            continue
        code, listing = git_output(
            ["ls-files", "--error-unmatch", path.relative_to(ROOT).as_posix()]
        )
        if code != 0 or not listing.strip():
            faults.append(f"{path.relative_to(ROOT).as_posix()} is not tracked")
    record("check_10f_the_evidence_is_committed", not faults, "; ".join(faults[:5]))


# --- 08 scope, registration and spend ------------------------------------------


def check_08a_no_upstream_no_ground_truth_no_ruling() -> None:
    """Negative 8a: this session changes extension code, configuration and gates."""
    changed = changed_paths()
    faults = []
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    if stray:
        faults.append(f"outside the declared paths: {stray[:5]}")
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    if upstream:
        faults.append(f"upstream changed: {upstream}")
    for prefix in FORBIDDEN_PREFIXES:
        touched = sorted(path for path in changed if path.startswith(prefix))
        if touched:
            faults.append(f"{prefix} changed: {touched[:3]}")
    # The one file under docs/eval this session may touch is the gap register,
    # and only for the two gaps the plan authorises.
    evaluation = sorted(
        path
        for path in changed
        if path.startswith("docs/eval/") and path not in ALLOWED_FILES
    )
    if evaluation:
        faults.append(f"docs/eval changed beyond the register: {evaluation}")
    record("check_08a_no_upstream_no_ground_truth_no_ruling", not faults, "; ".join(faults))


def check_08b_the_runner_registers_this_gate() -> None:
    """Positive 8b: the sweep runs this gate, after the batch it follows."""
    source = text_of(RUNNER)
    name = Path(__file__).name
    faults = []
    listed = re.findall(r'"(spec_check_[a-z0-9_]+\.py)"', source)
    if name not in listed:
        faults.append("run_all.py does not list this gate")
    elif "spec_check_b9_3.py" in listed and listed.index(
        "spec_check_b9_3.py"
    ) > listed.index(name):
        faults.append("this gate runs before the batch it follows")
    record("check_08b_the_runner_registers_this_gate", not faults, "; ".join(faults))


def check_08c_the_gate_spends_nothing() -> None:
    """Negative 8c: no credential, no network engine, ASCII prose.

    This gate does build a translation stage, because what a request carries is
    the property the batch is about and asserting it against a copy of the
    upstream reader would assert nothing. The engine it is built around is the
    stub in this file, which answers out of its own arguments.
    """
    source = text_of(Path(__file__))
    faults = []
    for forbidden in ("openai", "high_level", "doclayout", "requests", "httpx"):
        if re.search(rf"^\s*(import|from)\s+.*{forbidden}", source, re.MULTILINE):
            faults.append(f"imports {forbidden}")
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    if suffix in source.replace('"_API" + "_KEY"', ""):
        faults.append("names a credential variable")
    if "Stub(" not in source or "BaseTranslator" not in source:
        faults.append("the stage is not built around the stub declared here")
    for number, line in enumerate(source.splitlines(), start=1):
        if not line.isascii():
            offenders = [
                unicodedata.name(char, hex(ord(char)))
                for char in line
                if not char.isascii()
            ]
            faults.append(f"line {number}: {offenders[:3]}")
    for path in (MODULE, CONFIG):
        for number, line in enumerate(text_of(path).splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{path.name} line {number} is not ASCII")
    record("check_08c_the_gate_spends_nothing", not faults, "; ".join(faults[:5]))


def check_09_sweep() -> None:
    """Positive 9: every gate passes, this one included."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_09_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(RUNNER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_09_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01a_the_switch_is_down_by_default,
        check_01b_apply_without_marking_is_refused,
        check_02a_an_initial_in_a_style_run_is_read,
        check_02b_an_initial_inside_a_formula_is_read,
        check_02c_the_widening_is_additive_on_the_corpus,
        check_03a_a_style_run_initial_is_merged_and_the_word_closed,
        check_03b_a_formula_initial_is_merged_and_the_text_untouched,
        check_03c_a_drawn_space_is_never_dropped,
        check_03d_a_later_composition_is_left_alone,
        check_03e_keep_is_the_document_that_came_in,
        check_04a_the_flattened_paragraph_is_offered_whole,
        check_04b_before_the_merge_the_first_word_is_hidden,
        check_05a_the_default_is_per_target_language,
        check_05b_an_unclaimed_language_decides_nothing,
        check_05c_a_ruling_outranks_the_default,
        check_05d_a_paragraph_nobody_found_is_not_swept,
        check_06a_the_report_has_the_declared_shape,
        check_06b_a_record_of_the_wrong_shape_is_refused,
        check_06c_the_sidecar_is_in_the_inventory,
        check_06d_the_marking_report_names_its_consumer,
        check_07a_the_configuration_is_bounded,
        check_07b_a_broken_declaration_is_refused,
        check_07c_the_verdicts_come_from_one_file,
        check_07d_the_pass_runs_before_the_translator,
        check_10a_every_ruled_site_reached_the_request,
        check_10b_the_towering_initial_is_gone,
        check_10c_nothing_reached_an_unruled_paragraph,
        check_10d_the_found_candidate_and_the_draft,
        check_10e_the_residues_are_outside_the_signal,
        check_10f_the_evidence_is_committed,
        check_08a_no_upstream_no_ground_truth_no_ruling,
        check_08b_the_runner_registers_this_gate,
        check_08c_the_gate_spends_nothing,
        check_09_sweep,
    ]
    for check in checks:
        name = check.__name__
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(name, False, f"raised {exc!r}")
    print(f"\nspec_check_b9_4: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_b9_4")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
