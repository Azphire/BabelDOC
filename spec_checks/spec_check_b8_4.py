"""Gate script for batch B8.4 (reading order, treated semantics, landed repair).

Run from the repository root:

    python spec_checks/spec_check_b8_4.py

Exit code 0 when every assertion T8.4 answers for passes, 1 otherwise. Needs no
API key and makes no network request: every engine in this file is a stub, and
the one run that spent a credential left its evidence under
examples/output/b8_4/, which is what this gate reads.

01 is the reading order (T8.4a). The strip the previous batch sent to a model
in the reverse of its reading order has to come back as the line it is, and the
paragraphs whose stored order was already their reading order have to render
byte for byte what they rendered before. The rule is geometric, so it is
asserted geometrically: a paragraph written the other way down the page sorts
the other way, and a paragraph with nothing to sort by is left alone.

02 is the treated semantics (T8.4b). Two synthetic scenarios and one bound
check. A repair that leaves a finding standing with less of the defect in it
converges rather than rolls back; a repair that leaves the same defect standing
rolls back exactly as it did before, because that is the guard this batch is
not allowed to weaken. And the two thresholds the batch was forbidden to move
are compared against the values the previous batch's commit carries.

03 is the decision request (T8.4c). The applicability rule is declared once and
is stated to the model from that declaration, so the request cannot describe a
filter other than the one it feeds. The nineteen finding fixture is where the
selection is measured: it carries eligible and ineligible findings and strong
and weak evidence, its eligible set is derived from the rule rather than
written down, and a decision naming exactly that set is refused nothing.

04 is the storage (T8.4d and T8.4f). A staging directory belonging to a running
build is exempt from the sweep and one left by an interrupted build is not. The
retention policy keeps what git tracks, what the manifest names and the recent
batches, and removes the rest. The baselines are archives and the checkpoint
round trip is asserted through them.

05 is what the real run did (T8.4e), read from the frozen smoke evidence. The
strip was sent as the line it is and answered in the target language, and the
write-back then refused it: a rendering of that line needs more room than a
strip one character wide has, and the rule that reads the box either side of
laying a paragraph out again is what keeps a refusal from becoming a credit
reprinted across the artwork. What did land, landed with its box held, and both
are asserted in pixels as well as in the document.

06 is the scope, and 07 the sweep.

Every assertion is static. There is no pipeline tier.
"""

from __future__ import annotations

import ast
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import reading_order  # noqa: E402
from babeldoc.magazine.detectors import base as detector_base  # noqa: E402
from babeldoc.magazine.prompt_loader import file_digest  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b8.4"

# The batch this one is measured against: the thresholds it froze and the
# fixture it left behind are both read from it.
PREVIOUS_TAG = "batch-b8.3"

PYTHON = sys.executable

OUTPUT_DIR = ROOT / "examples" / "output" / "b8_4"
SMOKE_DIR = OUTPUT_DIR / "smoke"
EVIDENCE = SMOKE_DIR / "evidence.json"
LEDGER = SMOKE_DIR / "runs.json"
REPORT = OUTPUT_DIR / "smoke.report.md"
ROUNDS_DIR = SMOKE_DIR / "prompt_rounds"
RASTER_DIR = SMOKE_DIR / "raster"
SELECTION_EVIDENCE = OUTPUT_DIR / "selection_fixture.json"
SCRIPT_DIR = OUTPUT_DIR / "scripts"
DRIVER = SCRIPT_DIR / "run_repair_smoke.py"
ANALYZER = SCRIPT_DIR / "analyze_repair_smoke.py"
RASTERIZER = SCRIPT_DIR / "rasterize_subject.py"

# The frozen paragraphs of a real translated run, from the previous batch.
FIXTURE = ROOT / "examples" / "output" / "b8" / "Courier-en.orphans.fixture.xml"

DECIDE_PROMPT = ROOT / "prompts" / "react_repair_decide.md"
BASELINE_DIR = ROOT / "examples" / "output" / "baseline"

SAMPLE = "Courier-en"
SUBJECT = "p6#15"
SUBJECT_PAGE = 6
SUBJECT_INDEX = 15

LANGUAGE = "zh"

# The credit line the subject paragraph reads as, which is the whole of T8.4a's
# positive assertion: three style runs stored top of page first and read bottom
# of page first. Written as escapes, like the target language text below, so
# that no source file of this project carries text outside ASCII.
# (c) Boris Semeniako for The UNESCO Courier, with its accents
SUBJECT_LINE = "\u00a9 Boris S\u00e9m\u00e9niako for The UNESCO Courier"

# Target language text the stubs render; what each one reads is stated beside it.
# for the UNESCO Courier
TARGET_CREDIT = "\u4e3a\u8054\u5408\u56fd\u6559\u79d1\u6587\u7ec4\u7ec7\u300a\u4fe1\u4f7f\u300b"
# one character of the target script, for building a measured share
TARGET_FILL = "\u6587"

# T3.4's ceiling on how many times one prompt may be reworked in a session.
MAX_PROMPT_ROUNDS = 3

# How many findings the selection fixture carries.
FIXTURE_FINDINGS = 19

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Paths this batch may change.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "prompts/",
    "tools/",
    "spec_checks/",
    "plans/",
    "examples/output/",
    "corpus/manifest.json",
    # Written evidence for the dissertation, which is a document rather than a
    # pipeline input and cannot reach a run.
    "docs/",
)
ALLOWED_FILES = {"UPSTREAM_DIFF.md", "WAIVERS.md"}

# Files a run may never write to.
READ_ONLY = ("corpus/registry.user.json", "corpus/page_labels.json")

# The code this batch adds or reworks, which the scope assertions hold to the
# conventions.
SESSION_CODE = (
    "babeldoc/magazine/reading_order.py",
    "babeldoc/magazine/react/controller.py",
    "babeldoc/magazine/react/decide.py",
    "babeldoc/magazine/react/config.py",
    "babeldoc/magazine/detectors/base.py",
    "babeldoc/magazine/checkpoint.py",
    "tools/prune_outputs.py",
    "spec_checks/artifacts.py",
    "spec_checks/run_all.py",
    "examples/output/b8_4/scripts/run_repair_smoke.py",
    "examples/output/b8_4/scripts/analyze_repair_smoke.py",
    "examples/output/b8_4/scripts/rasterize_subject.py",
    f"spec_checks/{Path(__file__).name}",
)

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b8_4_"))

# The gate never writes a review draft into the working tree it asserts about.
os.environ[hitl.REVIEWS_ENV] = str(_tmp_root / "reviews")

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b8_4")


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


def evidence() -> dict:
    return load_json(EVIDENCE)


def source_of(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def issue_kinds() -> tuple[str, ...]:
    return tuple(sorted(module.KIND for module in detectors.DETECTORS.values()))


def repair_config():
    return react_config.load_repair_config(None, issue_kinds())


def orphan_action():
    return repair_config().actions[actions.NAME]


def fixture_document():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return checkpoint_module.load_checkpoint(FIXTURE)


def stored_order_text(paragraph) -> str:
    """What the paragraph rendered as before the ordering rule existed.

    The composition walked in list order, which is what every reader of a
    paragraph did until this batch; it is here so the no-spill assertion
    compares against the previous behaviour rather than against itself.
    """
    compositions = paragraph.pdf_paragraph_composition or []
    if not compositions:
        return paragraph.unicode or ""
    return "".join(
        reading_order._unit(composition)[0]  # noqa: SLF001
        for composition in compositions
    )


# --- documents and engines built here -----------------------------------------


BUILT_FONT = "base"


def style(size: float = 10.0):
    return il_version_1.PdfStyle(
        font_id=BUILT_FONT, font_size=size, graphic_state=il_version_1.GraphicState()
    )


def character(text: str, box: tuple[float, float, float, float]):
    return il_version_1.PdfCharacter(
        char_unicode=text,
        box=il_version_1.Box(*box),
        visual_bbox=il_version_1.VisualBbox(box=il_version_1.Box(*box)),
        pdf_style=style(),
        vertical=False,
    )


def run_composition(text: str, boxes):
    """One style run holding ``text``, its characters at the boxes given."""
    return il_version_1.PdfParagraphComposition(
        pdf_formula=il_version_1.PdfFormula(
            pdf_character=[
                character(item, box) for item, box in zip(text, boxes, strict=True)
            ]
        )
    )


def vertical_paragraph(runs, downward: bool = False):
    """A paragraph of style runs stacked along the vertical axis.

    ``runs`` are given in reading order and stored in the reverse of it, which
    is the shape the layout parser recovers a rotated strip in. ``downward``
    writes the characters advancing towards the foot of the page instead, which
    is the other vertical direction and has to sort the other way.
    """
    # Laid out from the foot of the strip upwards, taking the runs in whichever
    # order puts the first-read one where the writing direction says it goes.
    upwards = list(reversed(runs)) if downward else list(runs)
    placed: dict[str, object] = {}
    low = 100.0
    for text in upwards:
        boxes = [
            (10.0, low + 2.0 * index, 16.0, low + 2.0 * (index + 1))
            for index in range(len(text))
        ]
        placed[text] = run_composition(text, list(reversed(boxes)) if downward else boxes)
        low += 2.0 * len(text)
    # Stored in the reverse of the reading order, which is the shape the layout
    # parser recovers a rotated strip in and the thing the rule has to undo.
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(10.0, 100.0, 16.0, low),
        pdf_paragraph_composition=[placed[text] for text in reversed(runs)],
        unicode="".join(runs),
        layout_label=orphan_label(),
        debug_id="vertical",
        vertical=True,
        xobj_id=-1,
    )


def orphan_label() -> str:
    """The layout label an orphan carries, read from the action's own rule."""
    return orphan_action().applicability[react_config.ORPHAN_LABELS_KEY][0]


def horizontal_paragraph(text: str, label: str | None = None):
    boxes = [
        (10.0 + 6.0 * index, 100.0, 16.0 + 6.0 * index, 110.0)
        for index in range(len(text))
    ]
    # A generous box: what is being built is a line of text, and a repair that
    # writes a longer line into it must have room to be laid out rather than
    # failing for a reason this fixture never meant to test.
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(0.0, 95.0, 590.0, 115.0),
        pdf_paragraph_composition=[run_composition(text, boxes)],
        unicode=text,
        layout_label=orphan_label() if label is None else label,
        debug_id=f"h{abs(hash(text)) % 100000}",
        vertical=False,
        xobj_id=-1,
    )


def page(paragraphs, number: int = 0):
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=il_version_1.Box(0.0, 0.0, 600.0, 800.0)),
        cropbox=il_version_1.Cropbox(box=il_version_1.Box(0.0, 0.0, 600.0, 800.0)),
        pdf_paragraph=list(paragraphs),
        page_number=number,
        unit="point",
    )


def document(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


class LayoutModel:
    stage_name = "stub"

    def predict(self, *args, **kwargs):
        return []


def Config(directory: Path, translator=None, **attributes):  # noqa: N802
    from babeldoc.format.pdf.translation_config import TranslationConfig

    directory.mkdir(parents=True, exist_ok=True)
    config = TranslationConfig(
        translator=translator,
        input_file=str(ROOT / "examples" / "input" / f"{SAMPLE}.pdf"),
        lang_in="en",
        lang_out=LANGUAGE,
        doc_layout_model=LayoutModel(),
        working_dir=directory,
        output_dir=directory / "out",
        progress_monitor=None,
        auto_extract_glossary=False,
        skip_translation=False,
        magazine_detect=True,
    )
    config.magazine_repair = True
    for name, value in attributes.items():
        setattr(config, name, value)
    return config


class Engine:
    """A stub model: replies from a rule written here, and a record of requests."""

    name = "stub"

    def __init__(self, decide_with, translate_with):
        self.decide_with = decide_with
        self.translate_with = translate_with
        self.requests: list[str] = []

    def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
        self.requests.append(text)
        if "Actions available" in text:
            return self.decide_with(text)
        return self.translate_with(text)


class NoCache:
    def get(self, key):
        return None

    def set(self, key, value):
        return None


def offered_ids(text: str) -> list[str]:
    """The finding ids one rendered decision request carries, in its order."""
    return [
        line.split('"')[1]
        for line in text.splitlines()
        if line.strip().startswith("- id:")
    ]


def decision_reply(ids, parameters=None, reason="because"):
    return json.dumps(
        {
            "action": actions.NAME,
            "issue_ids": list(ids),
            "parameters": parameters if parameters is not None else {},
            "reason": reason,
        }
    )


def translation_reply(text: str) -> str:
    return json.dumps({actions.TRANSLATION_FIELD: text})


def build_loop(directory: Path, docs, engine):
    config = Config(directory, translator=engine)
    loop = controller.RepairLoop(config, docs)
    loop.decision_client = decide.CachedDecisionClient(
        loop.repair_config,
        transport=decide.EngineTransport(engine),
        cache=NoCache(),
        working_dir=loop.working_dir,
    )
    loop.translator = actions.CachedOrphanTranslator(
        loop.repair_config,
        transport=decide.EngineTransport(engine),
        cache=NoCache(),
        language=LANGUAGE,
        glossaries=[],
        working_dir=loop.working_dir,
    )
    return loop


def report_of(loop) -> dict:
    with (loop.working_dir / controller.REPORT_NAME).open(encoding="utf-8") as f:
        return json.load(f)


# --- 01 the reading order -----------------------------------------------------


def check_01a_the_subject_reads_as_its_line() -> None:
    """Positive 1a: the strip reads as the credit line it is.

    Against the frozen paragraphs of the run that measured it, so the assertion
    is about a real rotated strip rather than about one built to pass. What is
    also asserted is that the stored order is *not* the reading order, since
    otherwise the rule is being credited with a paragraph it never had to sort.
    """
    faults = []
    target = None
    for label, page_ in hitl.labeled_pages(fixture_document()):
        if label == SUBJECT_PAGE:
            target = page_.pdf_paragraph[SUBJECT_INDEX]
    if target is None:
        record("check_01a_the_subject_reads_as_its_line", False, f"{SUBJECT} absent")
        return
    read = detector_base.rendered_text(target)
    if read != SUBJECT_LINE:
        faults.append(f"reads as {read!r}")
    if stored_order_text(target) == read:
        faults.append("the stored order was already the reading order")
    runs = len(target.pdf_paragraph_composition or ())
    if runs < 2:
        faults.append(f"the subject carries {runs} run(s), so nothing was ordered")
    if not target.vertical:
        faults.append("the subject is not the rotated paragraph it was")
    record("check_01a_the_subject_reads_as_its_line", not faults, "; ".join(faults))


def check_01b_horizontal_paragraphs_are_byte_identical() -> None:
    """Negative 1b: nothing that was already in reading order moved.

    Every paragraph of the frozen document is compared against what the previous
    rule rendered it as. The ones that moved have to be vertical, and the count
    has to be small enough to name: a rule that reorders a page of body text is
    not the rule this batch describes.
    """
    docs = fixture_document()
    faults = []
    moved: list[str] = []
    total = 0
    for label, page_ in hitl.labeled_pages(docs):
        for index, paragraph in enumerate(page_.pdf_paragraph or ()):
            total += 1
            before = stored_order_text(paragraph)
            after = detector_base.rendered_text(paragraph)
            if before == after:
                continue
            moved.append(f"p{label}#{index}")
            if not paragraph.vertical:
                faults.append(f"p{label}#{index} is horizontal and was reordered")
    if total < 1:
        faults.append("the fixture holds no paragraph")
    if SUBJECT not in moved:
        faults.append(f"{SUBJECT} did not move")
    record(
        "check_01b_horizontal_paragraphs_are_byte_identical",
        not faults,
        f"moved={moved} of {total}: " + "; ".join(faults),
    )


def check_01c_the_order_is_read_from_the_geometry() -> None:
    """Positive/negative 1c: the direction comes from the characters themselves.

    Four built cases. A strip whose characters advance up the page reads bottom
    to top; the same strip written down the page reads top to bottom; a
    horizontal paragraph is untouched however its runs are stored; and a
    paragraph whose characters carry no boxes is left in the order it is stored
    in rather than guessed at.
    """
    faults = []
    runs = ("aaa", "bbb", "ccc")
    for what, downward in (("an upward", False), ("a downward", True)):
        strip = vertical_paragraph(runs, downward=downward)
        if stored_order_text(strip) != "".join(reversed(runs)):
            faults.append(f"{what} strip was not built stored in reverse")
        if detector_base.rendered_text(strip) != "".join(runs):
            faults.append(
                f"{what} strip read as {detector_base.rendered_text(strip)!r}"
            )
    flat = horizontal_paragraph("credit line for the magazine")
    if detector_base.rendered_text(flat) != stored_order_text(flat):
        faults.append("a horizontal paragraph was reordered")

    # No geometry anywhere: nothing to sort by, so nothing is sorted.
    blind = vertical_paragraph(runs)
    for composition in blind.pdf_paragraph_composition:
        for item in composition.pdf_formula.pdf_character:
            item.box = None
    if detector_base.rendered_text(blind) != stored_order_text(blind):
        faults.append("a paragraph with no geometry was reordered anyway")
    record("check_01c_the_order_is_read_from_the_geometry", not faults, "; ".join(faults))


def check_01d_one_reader_for_the_whole_package() -> None:
    """Negative 1d: nothing else in the package walks a composition for text.

    The detectors and the repair action have to be reading one string, or a
    finding is about one thing and the repair of it is about another. The check
    is that the composition member names appear in the shared module alone.
    """
    holders = set(reading_order._CHARACTER_HOLDERS)  # noqa: SLF001
    holders.add(reading_order._UNICODE_HOLDER)  # noqa: SLF001
    allowed = {
        "babeldoc/magazine/reading_order.py",
        # The write-back builds a composition rather than reading one, and takes
        # a style off the characters it finds; it names the holders to do it.
        "babeldoc/magazine/react/writeback.py",
        # The line split partitions a paragraph's compositions across the source
        # lines it recovered and rebuilds one per line, keeping each member's
        # kind and style. That is building, as above, and not a second reading:
        # nothing here derives a string a finding could be made about.
        "babeldoc/magazine/line_split.py",
    }
    faults = []
    for path in sorted((ROOT / "babeldoc" / "magazine").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in holders
            ):
                faults.append(f"{relative}:{node.lineno} names {node.value!r}")
    record("check_01d_one_reader_for_the_whole_package", not faults, "; ".join(faults))


# --- 02 the treated semantics -------------------------------------------------


def residue_text(latin: int, han: int, fill: str = "c") -> str:
    """Text holding a measured share of the residue script.

    ``latin`` cased characters against ``han`` of the target script, so the
    share the detector measures is exactly ``latin / (latin + han)`` and a case
    can be built at any point either side of a bound. ``fill`` changes the
    letters without changing anything measured, which is how a rewrite that is
    a different string and the same defect is built.
    """
    return (fill * latin) + (TARGET_FILL * han)


def orphan_document(count: int, latin: int = 30, han: int = 0):
    return document(
        [page([horizontal_paragraph(residue_text(latin, han)) for _ in range(count)])]
    )


def check_02a_converged_with_residuals() -> None:
    """Positive 2a: a repair that improves without clearing converges.

    The stub renders each line into text that is still over the detector's
    bound and well under it: the findings survive, with strictly less of the
    defect in each. That is progress by the rule this batch adds, so the
    iteration stands, the document keeps the repair, and the loop stops saying
    what it did rather than rolling back or running to its ceiling.
    """
    docs = orphan_document(3)
    before = XMLConverter().to_xml(docs)
    # Half the residue of what it replaces, and still a finding.
    partial = residue_text(15, 9)

    engine = Engine(
        lambda text: decision_reply(
            offered_ids(text), parameters={actions.MAX_PARAGRAPHS: 5}
        ),
        lambda _text: translation_reply(partial),
    )
    loop = build_loop(_tmp_root / "residuals", docs, engine)
    remaining = loop.run()
    report = report_of(loop)
    faults = []
    if report["stopped_because"] != controller.STOP_CONVERGED_WITH_RESIDUALS:
        faults.append(f"stopped because {report['stopped_because']}")
    if report["iterations_run"] != 1:
        faults.append(f"{report['iterations_run']} iteration(s), expected 1")
    if report["applications"] != 3:
        faults.append(f"{report['applications']} application(s), expected 3")
    outcomes = [item.get("outcome") for item in report["iterations"]]
    if controller.OUTCOME_ROLLED_BACK in outcomes:
        faults.append("an improving iteration was rolled back")
    if len(remaining) != 3:
        faults.append(f"{len(remaining)} finding(s) left, expected 3")
    if XMLConverter().to_xml(docs) == before:
        faults.append("the document is unchanged, so nothing was repaired")
    treated = report.get("treated") or []
    if len(treated) != 3:
        faults.append(f"{len(treated)} treated row(s), expected 3")
    for row in treated:
        if not row.get("still_reported"):
            faults.append(f"{row['issue_id']} is treated and no longer reported")
        if not row.get("measured"):
            faults.append(f"{row['issue_id']} names no measure")
        for name in row.get("measured", ()):
            if row["residual"].get(name) is None:
                faults.append(f"{row['issue_id']} reports no residual {name}")
            elif row["residual"][name] >= row["before"][name]:
                faults.append(f"{row['issue_id']} was treated without improving")
    if report["final_untreated"]["total"] != 0:
        faults.append("findings remain untreated after a converged run")
    if report["conservation"]["verdict"] != controller.CONSERVED:
        faults.append("conservation was not reported as held")
    record("check_02a_converged_with_residuals", not faults, "; ".join(faults))


def check_02b_untreated_set_not_shrinking_rolls_back() -> None:
    """Negative 2b: the guard is exactly as strong as it was.

    Two ways a repair fails to be progress, and both have to be undone. The
    first rewrites each line into the same defect in different words, which is
    the case the previous batch's guard was written against and the one the
    treated semantics must not swallow. The second writes back a line carrying
    more of the defect than the line it replaced, which is a repair that made
    the page worse. Neither may be mistaken for convergence.
    """
    faults = []

    # a. the same defect, in different words: as many characters of the wrong
    # script as before, so nothing the detector measures has moved.
    docs = orphan_document(2)
    before = XMLConverter().to_xml(docs)
    engine = Engine(
        lambda text: decision_reply(
            offered_ids(text), parameters={actions.MAX_PARAGRAPHS: 5}
        ),
        lambda _text: translation_reply(residue_text(30, 0, fill="d")),
    )
    loop = build_loop(_tmp_root / "stubborn", docs, engine)
    logs: list[str] = []

    class Capture(logging.Handler):
        def emit(self, item):
            logs.append(item.getMessage())

    logger = logging.getLogger("babeldoc.magazine.react.controller")
    handler = Capture(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        loop.run()
    finally:
        logger.removeHandler(handler)
    report = report_of(loop)
    if report["stopped_because"] != controller.STOP_NOT_CONVERGING:
        faults.append(f"a: stopped because {report['stopped_because']}")
    if report["applications"]:
        faults.append("a: a rolled back iteration was counted as an application")
    if report["treated"]:
        faults.append("a: a rewritten defect was recorded as treated")
    if XMLConverter().to_xml(docs) != before:
        faults.append("a: the document was left changed")
    if not any("rolled back and stopped" in message for message in logs):
        faults.append("a: the rollback was not reported in the run log")

    # b. more of the defect than there was: a repair that made the page worse
    docs = orphan_document(2)
    before = XMLConverter().to_xml(docs)
    engine = Engine(
        lambda text: decision_reply(
            offered_ids(text), parameters={actions.MAX_PARAGRAPHS: 5}
        ),
        lambda _text: translation_reply(residue_text(45, 0)),
    )
    loop = build_loop(_tmp_root / "worse", docs, engine)
    loop.run()
    report = report_of(loop)
    if report["stopped_because"] != controller.STOP_NOT_CONVERGING:
        faults.append(f"b: stopped because {report['stopped_because']}")
    if report["applications"]:
        faults.append("b: a rolled back iteration was counted as an application")
    if report["treated"]:
        faults.append("b: a worsened line was recorded as treated")
    if XMLConverter().to_xml(docs) != before:
        faults.append("b: the document was left changed")
    record(
        "check_02b_untreated_set_not_shrinking_rolls_back", not faults, "; ".join(faults)
    )


def check_02c_the_two_bounds_did_not_move() -> None:
    """Negative 2c: neither threshold was touched, mechanically.

    The design claim of this batch is that treated semantics make tuning either
    bound unnecessary. The claim is only worth something if the bounds were
    left alone, so both are compared against the values the previous batch's
    commit carries rather than against numbers written here.
    """
    faults = []
    code, previous_detectors = git_output(
        ["show", f"{PREVIOUS_TAG}:configs/detectors.json"]
    )
    if code != 0:
        record(
            "check_02c_the_two_bounds_did_not_move",
            False,
            f"{PREVIOUS_TAG} is not in the repository",
        )
        return
    _code, previous_actions = git_output(
        ["show", f"{PREVIOUS_TAG}:configs/repair_actions.json"]
    )
    was_detector = json.loads(previous_detectors)
    was_action = json.loads(previous_actions)
    now_detector = load_json(ROOT / "configs" / "detectors.json")
    now_action = load_json(ROOT / "configs" / "repair_actions.json")

    share_key = detector_base.RATIO_KEY_FORMAT.format(language=LANGUAGE)
    if was_detector[share_key] != now_detector[share_key]:
        faults.append(
            f"{share_key}: {was_detector[share_key]} -> {now_detector[share_key]}"
        )
    was_rule = was_action[react_config.ACTIONS_KEY][actions.NAME][
        react_config.APPLICABILITY_KEY
    ]
    now_rule = now_action[react_config.ACTIONS_KEY][actions.NAME][
        react_config.APPLICABILITY_KEY
    ]
    for key in (
        react_config.MIN_RATIO_KEY,
        react_config.MIN_CHARS_KEY,
        react_config.ORPHAN_LABELS_KEY,
    ):
        if was_rule[key] != now_rule[key]:
            faults.append(f"{key}: {was_rule[key]} -> {now_rule[key]}")
    # And the loop still reads them as the numbers they are.
    detector = detectors.detector_config().residue_rule(LANGUAGE)
    if detector is None or detector[1] != now_detector[share_key]:
        faults.append("the detector does not apply the declared share")
    if float(orphan_action().applicability[react_config.MIN_RATIO_KEY]) != float(
        now_rule[react_config.MIN_RATIO_KEY]
    ):
        faults.append("the action does not apply the declared share")
    record("check_02c_the_two_bounds_did_not_move", not faults, "; ".join(faults))


def check_02d_progress_is_declared_not_assumed() -> None:
    """Positive/negative 2d: what counts as less of a defect is configuration.

    Declared per issue kind, so a kind with nothing monotone to measure can be
    resolved and never improved, and the comparison refuses anything it cannot
    read as a number.
    """
    config = detectors.detector_config()
    faults = []
    kinds = set(issue_kinds())
    declared = set(config.progress_evidence)
    if not declared:
        faults.append("no kind declares what quantifies its defect")
    if declared - kinds:
        faults.append(f"declared for kinds nothing raises: {sorted(declared - kinds)}")
    for kind in orphan_action().issue_kinds:
        if not config.progress_fields(kind):
            faults.append(f"{kind} is acted on and declares no measure")

    fields = config.progress_fields(orphan_action().issue_kinds[0])
    cases = (
        ("strictly smaller", dict.fromkeys(fields, 10), dict.fromkeys(fields, 5), True),
        ("unchanged", dict.fromkeys(fields, 10), dict.fromkeys(fields, 10), False),
        ("larger", dict.fromkeys(fields, 10), dict.fromkeys(fields, 11), False),
        (
            "mixed",
            dict.fromkeys(fields, 10),
            {name: (5 if index else 11) for index, name in enumerate(fields)},
            False,
        ),
        ("missing", {}, dict.fromkeys(fields, 5), False),
        ("not a number", dict.fromkeys(fields, "10"), dict.fromkeys(fields, 5), False),
    )
    for what, was, now, expected in cases:
        if controller.improved(was, now, fields) != expected:
            faults.append(f"{what}: read as {not expected}")
    if controller.improved({"x": 1}, {"x": 0}, ()):
        faults.append("a kind declaring no measure was called improved")
    record("check_02d_progress_is_declared_not_assumed", not faults, "; ".join(faults))


# --- 03 the decision request --------------------------------------------------


def selection_fixture():
    """A page of nineteen findings, mixing what qualifies with what does not.

    Built from the rule rather than around it: the shares either side of the
    action's bound are computed from the bound, and the label that disqualifies
    a paragraph is any label the rule does not list. What comes back is the
    document and the set of references the rule ought to admit.
    """
    action = orphan_action()
    bound = float(action.applicability[react_config.MIN_RATIO_KEY])
    minimum = int(action.applicability[react_config.MIN_CHARS_KEY])
    orphan = orphan_label()
    other = next(
        label
        for label in ("plain text", "title", "abandon")
        if label not in action.applicability[react_config.ORPHAN_LABELS_KEY]
    )
    floor = detectors.detector_config().residue_min_script_chars

    def share(ratio: float, total: int = 60) -> tuple[int, int]:
        latin = max(floor, round(ratio * total))
        return latin, total - latin

    paragraphs = []
    expected: list[int] = []

    # Eligible, strongest evidence first by the share they carry.
    for latin in (60, 50, 40, 30):
        paragraphs.append(horizontal_paragraph(residue_text(latin, 0), orphan))
        expected.append(len(paragraphs) - 1)
    # Eligible, exactly at the bound.
    for _ in range(2):
        latin, han = share(bound)
        paragraphs.append(horizontal_paragraph(residue_text(latin, han), orphan))
        expected.append(len(paragraphs) - 1)
    # Reported by the detector, refused by the action: under the share bound.
    # Seven of them, the weakest evidence in the set.
    for step in (0.05, 0.1, 0.15, 0.2, 0.22, 0.25, 0.28):
        latin, han = share(bound - step)
        paragraphs.append(horizontal_paragraph(residue_text(latin, han), orphan))
    # Refused on the label: the translator was given these and did render them.
    for latin in (60, 50, 40, 30, 20, minimum):
        paragraphs.append(horizontal_paragraph(residue_text(latin, 0), other))

    docs = document([page(paragraphs)])
    references = [f"p1#{index}" for index in expected]
    return docs, references


def detected(docs):
    context = detectors.build_context(
        docs, detectors.detector_config(), LANGUAGE, None, translation_performed=True
    )
    return detectors.run_detectors(context), context


def ids_for(issues, references) -> list[str]:
    """The ids of the findings about ``references``, matched exactly.

    By set membership on the references a finding names rather than by looking
    for one inside an id, which would make p1#1 a match for p1#10.
    """
    wanted = set(references)
    return [issue.id for issue in issues if set(issue.paragraph_refs) & wanted]


def check_03a_the_request_states_the_rule() -> None:
    """Positive 3a: the filter the decision feeds is in the request it answers.

    Every term of the rule, with its own figure in it, from the one declaration
    that the rule is applied from. A statement written into the prompt file
    instead would pass a weaker version of this and drift the first time a bound
    moved, which is why the sentences are configuration.
    """
    config = repair_config()
    client = decide.CachedDecisionClient(config, cache=NoCache(), working_dir=_tmp_root)
    docs, _references = selection_fixture()
    issues, _context = detected(docs)
    text = client.prompt(issues).text
    faults = []
    for action in config.actions.values():
        for sentence in action.conditions():
            if sentence not in text:
                faults.append(f"the request does not state {sentence!r}")
        if not action.conditions():
            faults.append(f"{action.name} states no condition at all")
    # The figures themselves, so a statement that dropped its value fails here.
    rule = orphan_action().applicability
    for key in (react_config.MIN_RATIO_KEY, react_config.MIN_CHARS_KEY):
        if str(rule[key]) not in text:
            faults.append(f"the request does not carry {key}={rule[key]}")
    for label in rule[react_config.ORPHAN_LABELS_KEY]:
        if label not in text:
            faults.append(f"the request does not carry the label {label!r}")
    # And the evidence the rule is read against is in the findings it shows.
    for field in ("residue_ratio", "layout_label"):
        if field not in text:
            faults.append(f"the request states a rule about {field} and never shows it")
    record("check_03a_the_request_states_the_rule", not faults, "; ".join(faults))


def check_03b_the_known_correct_selection_is_refused_nothing() -> None:
    """Positive 3b: naming exactly what qualifies costs nothing and repairs all.

    The fixture's eligible set is derived from the rule; a decision naming it is
    admitted in full. The set is a proper subset of what the detectors report,
    or the fixture would be asserting nothing about selection.
    """
    docs, references = selection_fixture()
    issues, _context = detected(docs)
    faults = []
    if len(issues) != FIXTURE_FINDINGS:
        faults.append(f"{len(issues)} finding(s) detected, expected {FIXTURE_FINDINGS}")
    eligible = ids_for(issues, references)
    if len(eligible) != len(references):
        faults.append(
            f"{len(eligible)} of the {len(references)} eligible references were reported"
        )
    if len(eligible) >= len(issues):
        faults.append("every finding qualifies, so the fixture mixes nothing")

    engine = Engine(
        lambda text: decision_reply(
            [issue_id for issue_id in offered_ids(text) if issue_id in set(eligible)],
            parameters={actions.MAX_PARAGRAPHS: len(references)},
        ),
        lambda _text: translation_reply(TARGET_CREDIT),
    )
    loop = build_loop(_tmp_root / "selection", docs, engine)
    loop.run()
    report = report_of(loop)
    first = report["iterations"][0]
    refused = [row for row in first.get("applicability") or () if not row["accepted"]]
    if refused:
        faults.append(
            f"the known correct selection was refused {[row['reason'] for row in refused]}"
        )
    written = {row["paragraph_ref"] for row in first["executed"] if row["changed"]}
    if written != set(references):
        faults.append(f"repaired {sorted(written)}, expected {sorted(references)}")
    with SELECTION_EVIDENCE.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "findings": len(issues),
                "eligible": sorted(references),
                "eligible_share": round(len(references) / max(1, len(issues)), 4),
                "refused_reasons": sorted(
                    {row["reason"] for row in first.get("applicability") or ()}
                ),
            },
            f,
            indent=2,
            sort_keys=True,
        )
    record(
        "check_03b_the_known_correct_selection_is_refused_nothing",
        not faults,
        "; ".join(faults),
    )


def check_03c_naming_what_the_rule_refuses_costs_the_quota() -> None:
    """Negative 3c: over-naming is refused and under-naming leaves work undone.

    Two decisions over the same findings. One names every finding on the list:
    the rule admits exactly the eligible ones and records a declared reason for
    each of the rest, so the cost of over-naming is a quota spent rather than a
    paragraph damaged. One names the ineligible findings alone: nothing is
    written at all, which is the iteration that a decision unable to see the
    filter throws away.
    """
    docs, references = selection_fixture()
    issues, _context = detected(docs)
    faults = []

    engine = Engine(
        lambda text: decision_reply(
            offered_ids(text), parameters={actions.MAX_PARAGRAPHS: len(references)}
        ),
        lambda _text: translation_reply(TARGET_CREDIT),
    )
    loop = build_loop(_tmp_root / "over_named", docs, engine)
    loop.run()
    report = report_of(loop)
    first = report["iterations"][0]
    declared = {
        value
        for name, value in vars(actions).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    accepted = {row["paragraph_ref"] for row in first["executed"] if row["changed"]}
    if accepted != set(references):
        faults.append(f"over-naming repaired {sorted(accepted)}")
    for row in first.get("applicability") or ():
        if row["reason"] not in declared:
            faults.append(f"undeclared refusal reason {row['reason']!r}")
        if row["paragraph_ref"] in references:
            faults.append(f"{row['paragraph_ref']} qualifies and was refused")

    docs, references = selection_fixture()
    eligible = set(ids_for(detected(docs)[0], references))
    ineligible = [
        issue.id for issue in detected(docs)[0] if issue.id not in eligible
    ]
    engine = Engine(
        lambda _text: decision_reply(
            ineligible[:3], parameters={actions.MAX_PARAGRAPHS: 3}
        ),
        lambda _text: translation_reply(TARGET_CREDIT),
    )
    loop = build_loop(_tmp_root / "under_named", docs, engine)
    loop.run()
    report = report_of(loop)
    if report["applications"]:
        faults.append("a decision naming only refused findings repaired something")
    if report["stopped_because"] != controller.STOP_NOTHING_APPLICABLE:
        faults.append(f"stopped because {report['stopped_because']}")
    record(
        "check_03c_naming_what_the_rule_refuses_costs_the_quota",
        not faults,
        "; ".join(faults),
    )


def check_03d_statements_are_declared_for_every_term() -> None:
    """Negative 3d: a term with nothing to say about itself is refused.

    Both directions, since either one drifting is how a request comes to
    describe a filter that is not there.
    """
    faults = []
    raw = load_json(ROOT / "configs" / "repair_actions.json")
    rule = raw[react_config.ACTIONS_KEY][actions.NAME][react_config.APPLICABILITY_KEY]
    statements = rule.get(react_config.STATEMENTS_KEY) or {}
    terms = {
        key
        for key in rule
        if key != react_config.STATEMENTS_KEY
        and not key.endswith(react_config.RANGE_SUFFIX)
    }
    if set(statements) != terms:
        faults.append(f"terms {sorted(terms)} against statements {sorted(statements)}")

    def refuses(mutate, what: str) -> None:
        probe = load_json(ROOT / "configs" / "repair_actions.json")
        mutate(probe[react_config.ACTIONS_KEY][actions.NAME][
            react_config.APPLICABILITY_KEY
        ])
        try:
            react_config.parse_repair_config(probe, "probe.json", set(issue_kinds()))
        except react_config.RepairConfigError:
            return
        faults.append(f"accepted {what}")

    refuses(
        lambda block: block[react_config.STATEMENTS_KEY].pop(react_config.MIN_RATIO_KEY),
        "a term with no statement",
    )
    refuses(
        lambda block: block[react_config.STATEMENTS_KEY].__setitem__("invented", "x {value}"),
        "a statement about a term that does not exist",
    )
    refuses(
        lambda block: block[react_config.STATEMENTS_KEY].__setitem__(
            react_config.MIN_RATIO_KEY, "a sentence carrying no figure"
        ),
        "a statement that drops the value it states",
    )
    refuses(
        lambda block: block.pop(react_config.STATEMENTS_KEY),
        "an applicability block declaring no statements",
    )
    record(
        "check_03d_statements_are_declared_for_every_term", not faults, "; ".join(faults)
    )


def check_03e_prompt_rounds_are_recorded() -> None:
    """Positive 3e: this batch's reworking of the prompt is on record.

    The discipline is the one T3.4 declares: every round frozen with what it
    produced, inside the ceiling, no two rounds running the same text, and the
    file in the tree being the last round -- which is the live half of the
    assertion and belongs to whichever batch reworked the prompt last.
    """
    faults = []
    if not ROUNDS_DIR.is_dir():
        record("check_03e_prompt_rounds_are_recorded", False, "no rounds recorded")
        return
    rounds = sorted(path for path in ROUNDS_DIR.iterdir() if path.is_dir())
    if not rounds:
        faults.append("no prompt round was recorded")
    if len(rounds) > MAX_PROMPT_ROUNDS + 1:
        faults.append(f"{len(rounds)} rounds against a ceiling of {MAX_PROMPT_ROUNDS}")
    digests: dict[str, str] = {}
    for path in rounds:
        for name in ("prompt_trace.jsonl", controller.REPORT_NAME, detectors.REPORT_NAME):
            if not (path / name).exists():
                faults.append(f"{path.name}: no {name}")
        trace_path = path / "prompt_trace.jsonl"
        if not trace_path.exists():
            continue
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("kind") == "decide_prompt":
                digests[path.name] = entry["prompt_sha256"]
                break
    if len(set(digests.values())) != len(digests):
        faults.append(f"two rounds ran the same prompt: {digests}")
    current = file_digest(DECIDE_PROMPT)
    if digests and digests[rounds[-1].name] != current:
        faults.append(
            f"the last round ran {digests[rounds[-1].name][:12]} and the tree "
            f"carries {current[:12]}"
        )
    code, previous = git_output(
        ["show", f"{PREVIOUS_TAG}:prompts/react_repair_decide.md"]
    )
    if code == 0 and previous == DECIDE_PROMPT.read_text(encoding="utf-8"):
        faults.append("the prompt was not reworked at all")
    record("check_03e_prompt_rounds_are_recorded", not faults, "; ".join(faults))


# --- 04 the storage -----------------------------------------------------------


class _Sandbox:
    """A disposable cache root with a budget of this gate's choosing."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="spec_b8_4_cache_"))
        self._saved: dict[str, object] = {}

    def budget(self, max_bytes: int) -> None:
        with self.config.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "description": "disposable budget for one gate assertion",
                    "gate_cache_max_gb": max_bytes / artifacts.BYTES_PER_GB,
                    "gate_cache_max_gb_allowed_range": "0.0000001..256",
                    "staging_stale_after_seconds": 86400,
                    "staging_stale_after_seconds_allowed_range": "60..2592000",
                },
                f,
            )

    def __enter__(self) -> _Sandbox:
        self.config = self.root / "gate_cache.json"
        self.budget(artifacts.BYTES_PER_GB)
        self._saved = {
            "CACHE_ROOT": artifacts.CACHE_ROOT,
            "STATS_DIR": artifacts.STATS_DIR,
            "CACHE_CONFIG_PATH": artifacts.CACHE_CONFIG_PATH,
        }
        artifacts.CACHE_ROOT = self.root / "cache"
        artifacts.STATS_DIR = artifacts.CACHE_ROOT / "stats"
        artifacts.CACHE_CONFIG_PATH = self.config
        artifacts.CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *_exc) -> None:
        for name, value in self._saved.items():
            setattr(artifacts, name, value)
        shutil.rmtree(self.root, ignore_errors=True)

    def slot(self, generation: str, name: str, payload_bytes: int) -> Path:
        path = artifacts.CACHE_ROOT / generation / name
        path.mkdir(parents=True, exist_ok=True)
        with (path / "meta.json").open("w", encoding="utf-8") as f:
            json.dump({"mode": "fabricated", "working_subdir": "work"}, f)
        (path / "payload.bin").write_bytes(b"\0" * payload_bytes)
        return path

    def staging(self, generation: str, name: str, payload_bytes: int, live: bool):
        path = artifacts.CACHE_ROOT / generation / (name + artifacts.STAGING_SUFFIX)
        path.mkdir(parents=True, exist_ok=True)
        (path / "payload.bin").write_bytes(b"\0" * payload_bytes)
        if live:
            artifacts._take_lock(path)  # noqa: SLF001
        return path


_PAYLOAD = 64 << 10


def check_04a_a_live_build_is_exempt_and_an_abandoned_one_is_not() -> None:
    """Positive/negative 4a: what a staging directory costs and when.

    A directory a build is working in is not counted and is not swept, or a
    sweep could delete the thing it is making room for. One left by an
    interrupted build is counted and is swept first, and is swept whether or not
    the cache is over its ceiling, because it can never be served as a hit.
    """
    faults = []
    with _Sandbox() as box:
        live = box.staging("gen", "current", _PAYLOAD, live=True)
        abandoned = box.staging("gen", "orphan", _PAYLOAD, live=False)
        slot = box.slot("gen", "published", _PAYLOAD)
        box.budget(10 * artifacts.BYTES_PER_GB)

        listed = {path.name for path in artifacts.abandoned_staging()}
        if abandoned.name not in listed:
            faults.append("an abandoned staging directory was not seen")
        if live.name in listed:
            faults.append("a live build was read as abandoned")
        with_orphan = artifacts.cache_size_bytes()

        dropped, freed = artifacts.trim_cache(10 * artifacts.BYTES_PER_GB)
        if not dropped:
            faults.append("a cache inside its ceiling kept an abandoned build")
        if abandoned.exists():
            faults.append("the abandoned directory survived the sweep")
        if not live.exists():
            faults.append("the sweep removed a build in progress")
        if not slot.exists():
            faults.append("a sweep with room to spare dropped a published slot")
        after = artifacts.cache_size_bytes()
        if after >= with_orphan:
            faults.append("the abandoned build was never in the size accounting")
        if freed <= 0:
            faults.append("the sweep reported nothing reclaimed")
        # A live build is not in the accounting at all, so what is left is the
        # published slot alone.
        if after != artifacts._slot_bytes(slot):  # noqa: SLF001
            faults.append(f"{after} bytes accounted against one published slot")
    record(
        "check_04a_a_live_build_is_exempt_and_an_abandoned_one_is_not",
        not faults,
        "; ".join(faults),
    )


def check_04b_the_build_takes_and_drops_its_lock() -> None:
    """Positive 4b: the lock is taken before the work and dropped before publish.

    A build that published its lock would exempt the finished slot from every
    later sweep, and one that never took a lock would be swept by the sweep it
    triggers itself.
    """
    tree = ast.parse(source_of("spec_checks/artifacts.py"))
    build = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_build"
    )
    calls = [
        (node.lineno, ast.unparse(node.func))
        for node in ast.walk(build)
        if isinstance(node, ast.Call)
    ]
    body = ast.unparse(build)
    faults = []
    taken = [line for line, name in calls if name.endswith("_take_lock")]
    publish = [line for line, name in calls if name.endswith("staging.replace")]
    room = [line for line, name in calls if name.endswith("make_room")]
    if len(taken) != 1:
        faults.append(f"_build takes a lock {len(taken)} time(s)")
    if not publish:
        faults.append("_build no longer publishes with an atomic replace")
    if taken and publish and min(taken) > min(publish):
        faults.append("the lock is taken after the publish")
    if "STAGING_LOCK" not in body or "unlink" not in body:
        faults.append("_build does not drop its lock")
    if room and publish and min(room) > min(publish):
        faults.append("the sweep happens after the publish")
    record("check_04b_the_build_takes_and_drops_its_lock", not faults, "; ".join(faults))


def check_04c_retention_keeps_what_it_declares() -> None:
    """Positive/negative 4c: the policy over a fabricated output tree.

    Three batches of products, one report and one log in each, and one file
    standing for something git tracks. The two newest batches keep everything,
    the oldest keeps its report and its log, and nothing outside a batch
    directory is touched at all.

    Batch b9.2r added the archive pass and the registered-path guard, and both
    belong to the same question this assertion has always asked -- what the
    policy keeps -- so they are checked here rather than somewhere a reader of
    the policy would not look. The evicted batch's small text has to be selected
    for its archive, including the report the keep patterns leave in place: a
    file that stays on the disk untracked is one clone away from gone, which is
    the whole reason the archive exists. And nothing on the configured
    protection list may be selected for removal anywhere in the real tree.
    """
    from tools import prune_outputs

    faults = []
    root = Path(tempfile.mkdtemp(prefix="spec_b8_4_outputs_"))
    try:
        for name in ("b1", "b7_5", "b8"):
            directory = root / name
            (directory / "work").mkdir(parents=True)
            (directory / f"{name}.report.md").write_text("report", encoding="utf-8")
            (directory / f"{name}.log").write_text("log", encoding="utf-8")
            (directory / "work" / "checkpoint.01.xml").write_text("x", encoding="utf-8")
            (directory / "work" / f"{name}.sidecar.json").write_text(
                "{}", encoding="utf-8"
            )
            (directory / "bulk.pdf").write_bytes(b"0" * 1024)
        (root / "gate_cache").mkdir()
        (root / "gate_cache" / "payload.bin").write_bytes(b"0" * 1024)

        config = prune_outputs.load_config()
        doomed, recent = prune_outputs.prunable(root, config)
        names = {path.relative_to(root).as_posix() for path in doomed}
        if names != {
            "b1/work/checkpoint.01.xml",
            "b1/work/b1.sidecar.json",
            "b1/bulk.pdf",
        }:
            faults.append(f"would remove {sorted(names)}")
        if len(recent) != int(config[prune_outputs.KEEP_RECENT_KEY]):
            faults.append(f"kept {len(recent)} batch(es) whole")
        for path in doomed:
            if path.match("*.report.md") or path.match("*.log"):
                faults.append(f"a kept pattern was listed: {path.name}")

        # The archive pass, over the same fabricated tree. Only the evicted
        # batch contributes, and its report and log go in beside the sidecar
        # even though the keep patterns leave those two on the disk.
        selected = prune_outputs.archivable(root, config)
        if sorted(selected) != ["b1"]:
            faults.append(f"batches selected for archiving: {sorted(selected)}")
        archived = {
            path.relative_to(root).as_posix() for path in selected.get("b1", ())
        }
        if archived != {"b1/b1.report.md", "b1/b1.log", "b1/work/b1.sidecar.json"}:
            faults.append(f"would archive {sorted(archived)}")
        if any("bulk.pdf" in member for member in archived):
            faults.append("the bulk product was selected for the archive")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # Nothing the repository records and nothing the manifest names is prunable.
    protected = prune_outputs.tracked_paths(ROOT / "examples" / "output")
    if not protected:
        faults.append("no tracked output file was found, so the guard proves nothing")
    named = prune_outputs.manifest_paths()
    if not named:
        faults.append("the manifest names no baseline")
    registered_files, registered_dirs = prune_outputs.registered_paths(config)
    if not registered_files:
        faults.append("the policy registers no protected path, so that guard is idle")
    real, _recent = prune_outputs.prunable(ROOT / "examples" / "output", config)
    trespass = sorted(
        path.as_posix() for path in real if path.resolve() in protected | named
    )
    trespass += sorted(
        path.as_posix()
        for path in real
        if prune_outputs.is_registered(path, registered_files, registered_dirs)
    )
    if trespass:
        faults.append(f"the policy would remove protected files: {trespass[:3]}")
    record("check_04c_retention_keeps_what_it_declares", not faults, "; ".join(faults))


def check_04d_baselines_are_archives_that_round_trip() -> None:
    """Positive 4d: every baseline is an archive and reads as it did.

    The checkpoint round trip is the assertion the earlier batches make about
    these files, re-run here through the archive path: a member is loaded, its
    canonical form is taken twice, and the two have to agree. What is also
    checked is that the manifest still resolves -- it names a directory, and a
    reader that could not turn that into the archive would report a corpus with
    no baselines.
    """
    faults = []
    containers = sorted(
        BASELINE_DIR.glob(f"*.checkpoints{checkpoint_module.CHECKPOINT_ARCHIVE_SUFFIX}")
    )
    if not containers:
        record(
            "check_04d_baselines_are_archives_that_round_trip",
            False,
            "no baseline archive is in the tree",
        )
        return
    leftovers = sorted(path.name for path in BASELINE_DIR.glob("*.checkpoints"))
    if leftovers:
        faults.append(f"unpacked baseline directories remain: {leftovers}")
    checked = 0
    for archive in containers:
        if not zipfile.is_zipfile(archive):
            faults.append(f"{archive.name} is not an archive")
            continue
        members = checkpoint_module.checkpoint_paths(archive, "*.xml")
        if not members:
            faults.append(f"{archive.name} holds no checkpoint")
        for member in members:
            checked += 1
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                docs = checkpoint_module.load_checkpoint(member)
            once = checkpoint_module.to_checkpoint_xml(docs)
            twice = checkpoint_module.to_checkpoint_xml(
                checkpoint_module.from_checkpoint_xml(once)
            )
            if once != twice:
                faults.append(f"{archive.name}/{member.name}: canonical form moves")
    if not checked:
        faults.append("no archived checkpoint was read")

    for entry in corpus.load_manifest()["samples"]:
        named = ROOT / entry["baseline"]["checkpoints"]
        if not checkpoint_module.checkpoint_paths(named, "*.xml"):
            faults.append(f"{entry['file']}: the manifest baseline resolves to nothing")
    record(
        "check_04d_baselines_are_archives_that_round_trip", not faults, "; ".join(faults)
    )


def check_04e_the_sweep_applies_the_policy() -> None:
    """Positive 4e: the runner ends by applying the retention policy.

    After the gates rather than before them, because a sweep reads what earlier
    sweeps left, and with --apply rather than as a report nobody acts on.

    The function inspected is whichever one drives the gates, found by looking
    for the ``run_gate`` calls rather than by name: batch b9.2r moved the sweep
    body out of ``main`` so the cache lock could be released on every exit path,
    and an assertion pinned to a function name would have read that refactor as
    a runner that had stopped applying the policy.
    """
    tree = ast.parse(source_of("spec_checks/run_all.py"))
    def calls_run_gate(node: ast.AST) -> bool:
        return any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "run_gate"
            for inner in ast.walk(node)
        )

    drivers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and calls_run_gate(node)
    ]
    faults = []
    if not drivers:
        record(
            "check_04e_the_sweep_applies_the_policy",
            False,
            "no function in the runner calls run_gate",
        )
        return
    # The innermost one: an outer wrapper contains the driver's source too.
    driver = min(drivers, key=lambda node: len(ast.unparse(node)))
    body = ast.unparse(driver)
    if "prune_outputs()" not in body:
        faults.append("the runner does not apply the retention policy")
    prune = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "prune_outputs"
        ),
        None,
    )
    if prune is None:
        faults.append("the runner declares no retention step")
    elif "--apply" not in ast.unparse(prune):
        faults.append("the retention step is a dry run")
    lines = body.splitlines()
    applied = [index for index, line in enumerate(lines) if "prune_outputs()" in line]
    ran = [index for index, line in enumerate(lines) if "run_gate(" in line]
    if applied and ran and min(applied) < max(ran):
        faults.append("the policy is applied before the gates have run")
    record("check_04e_the_sweep_applies_the_policy", not faults, "; ".join(faults))


# --- 05 the landed repair -----------------------------------------------------


def check_05a_artefacts_present() -> None:
    """Positive 5a: the run left the files the report is written from."""
    wanted = [
        EVIDENCE,
        LEDGER,
        REPORT,
        DRIVER,
        ANALYZER,
        RASTERIZER,
        SELECTION_EVIDENCE,
        SMOKE_DIR / SAMPLE / "run.json",
        SMOKE_DIR / SAMPLE / "prompt_trace.jsonl",
        *(
            RASTER_DIR / f"{stem}.{SUBJECT.replace('#', '_')}.png"
            for stem in ("b8_3", "b8_4")
        ),
    ]
    missing = [str(path.relative_to(ROOT)) for path in wanted if not path.exists()]
    record("check_05a_artefacts_present", not missing, f"missing {missing}")


def check_05b_the_subject_was_asked_the_right_question() -> None:
    """Positive 5b: the strip was sent as the line it is, and answered as one.

    This is T8.4a's live proof and it is separate from whether the answer could
    be written back. Two batches sent this paragraph in the reverse of its
    reading order; this one sent the credit line, and what came back carries the
    target script -- so the request and the reply are both right whatever the
    write-back then did with them.
    """
    data = evidence()
    faults = []
    subject = data["subject"]
    if not subject.get("detected"):
        faults.append(f"{SUBJECT} was not detected")
    if subject.get("source_offered") != SUBJECT_LINE:
        faults.append(
            f"the line sent for repair was {subject.get('source_offered')!r}"
        )
    written = subject.get("translation_written", "")
    if detector_base.script_counts(written).get("han", 0) < 1:
        faults.append(f"the reply carries no target script: {written!r}")
    for iteration in data["loop"]["iterations"]:
        if iteration.get("outcome") == controller.OUTCOME_ROLLED_BACK:
            faults.append("an iteration of the recorded run was rolled back")
    record(
        "check_05b_the_subject_was_asked_the_right_question",
        not faults,
        "; ".join(faults),
    )


def check_05g_a_repair_landed_and_held_its_box() -> None:
    """Positive 5g: at least one repair reached the produced PDF intact.

    Landing is the batch's claim and holding the box is the condition on it. A
    repair that needed more room than the paragraph had is refused at the
    write-back, so every paragraph that did land has to report the box it
    started with and text in the target script.
    """
    data = evidence()
    rows = data.get("landed") or []
    faults = []
    if not rows:
        faults.append("no repair landed anywhere in the corpus")
    for row in rows:
        if not row["box_held"]:
            faults.append(
                f"{row['sample']} {row['paragraph_ref']}: box "
                f"{row['box_before']} -> {row['box_after']}"
            )
        if detector_base.script_counts(row["text_after"]).get("han", 0) < 1:
            faults.append(
                f"{row['sample']} {row['paragraph_ref']}: no target script after"
            )
        if row["text_after"] == row["text_before"]:
            faults.append(f"{row['sample']} {row['paragraph_ref']}: text unchanged")
    record(
        "check_05g_a_repair_landed_and_held_its_box", not faults, "; ".join(faults)
    )


def check_05h_the_strip_was_refused_rather_than_rearranged() -> None:
    """Negative 5h: the one repair that would have moved a paragraph was refused.

    The write-back reads the box either side of laying the paragraph out again
    and refuses a composition that needs more room than the paragraph had. On
    this document that rule fires once, on the subject, and what it prevents is
    a credit set down the edge of the artwork being reprinted across the top of
    it. The reason is recorded in the loop's own vocabulary.
    """
    from babeldoc.magazine.react import actions as action_module

    data = evidence()
    faults = []
    refused = [
        row
        for row in data.get("refusals") or []
        if row.get("reason") == action_module.REASON_GEOMETRY
    ]
    if not refused:
        faults.append("no repair was refused for needing more room")
    subject = [row for row in refused if row["paragraph_ref"] == SUBJECT]
    if not subject:
        faults.append(f"{SUBJECT} was not the paragraph refused")
    if SUBJECT in data["loop"]["conservation"]["touched_refs"]:
        faults.append(f"{SUBJECT} was written after all")
    if SUBJECT in data["loop"]["conservation"]["changed_refs"]:
        faults.append(f"{SUBJECT} changed in a run that refused to write it")
    record(
        "check_05h_the_strip_was_refused_rather_than_rearranged",
        not faults,
        "; ".join(faults),
    )


def check_05c_the_pixels_agree_with_the_document() -> None:
    """Positive/negative 5c: the two regions draw exactly as the loop says.

    The strongest form the claim takes, because an image cannot be satisfied by
    a document that merely says it is unchanged. The strip was refused, so its
    crop out of this batch's PDF has to be identical to the previous batch's. A
    paragraph that was repaired has to differ. And the pages whose text moved
    have to be pages a repair landed on, in the document the PDF was written
    from.
    """
    faults = []
    crops = {
        stem: RASTER_DIR / f"{stem}.{SUBJECT.replace('#', '_')}.png"
        for stem in ("b8_3", "b8_4")
    }
    missing = [path.name for path in crops.values() if not path.exists()]
    if missing:
        faults.append(f"missing {missing}")
    else:
        digests = {stem: file_digest(path) for stem, path in crops.items()}
        if len(set(digests.values())) != 1:
            faults.append("a refused repair changed what the page draws")

    for row in evidence().get("landed") or []:
        tail = row["paragraph_ref"].replace("#", "_")
        pair = {
            stem: RASTER_DIR / f"{stem}.{tail}.png" for stem in ("b8_3", "b8_4")
        }
        absent = [path.name for path in pair.values() if not path.exists()]
        if absent:
            faults.append(f"missing {absent}")
            continue
        if len({file_digest(path) for path in pair.values()}) == 1:
            faults.append(f"{row['paragraph_ref']} was repaired and draws the same")

    radius = evidence()["blast_radius"]
    changed = set(radius["pdf_pages_changed"])
    allowed = set(radius["pdf_pages_of_touched"])
    if not changed <= allowed:
        faults.append(
            f"pages changed with nothing repaired on them: {sorted(changed - allowed)}"
        )
    if radius["changed_outside_touched"]:
        faults.append(f"the document changed at {radius['changed_outside_touched']}")
    record("check_05c_the_pixels_agree_with_the_document", not faults, "; ".join(faults))


def check_05d_the_strip_is_still_a_strip() -> None:
    """Negative 5d: the run left the strip exactly as it found it.

    Its box, its orientation flag and the text it renders are what make it the
    strip it is. A run that refused to write into it has to have left all three,
    and a rendered text that still reads as the credit line is also T8.4a
    holding on the document the PDF was written from.
    """
    subject = evidence()["subject"]
    faults = []
    if subject["box_before"] != subject["box_after"]:
        faults.append(
            f"the box moved: {subject['box_before']} -> {subject['box_after']}"
        )
    if subject["vertical_before"] is not True or subject["vertical_after"] is not True:
        faults.append(
            f"the orientation flag is {subject['vertical_before']} -> "
            f"{subject['vertical_after']}"
        )
    if subject["rendered_before"] != SUBJECT_LINE:
        faults.append(f"the strip reads as {subject['rendered_before']!r}")
    if subject["rendered_after"] != subject["rendered_before"]:
        faults.append("the strip's text moved in a run that refused to write it")
    record("check_05d_the_strip_is_still_a_strip", not faults, "; ".join(faults))


def check_05e_every_run_conserved_its_document() -> None:
    """Positive 5e: across the corpus, no run violated conservation."""
    faults = []
    for entry in load_json(LEDGER):
        repair = load_json(ROOT / entry["working_dir"] / controller.REPORT_NAME)
        conservation = repair["conservation"]
        if conservation["verdict"] != controller.CONSERVED:
            faults.append(f"{entry['sample']}: {conservation['verdict']}")
        if conservation["pages_before"] != conservation["pages_after"]:
            faults.append(f"{entry['sample']}: page count moved")
        if conservation["paragraphs_before"] != conservation["paragraphs_after"]:
            faults.append(f"{entry['sample']}: paragraph count moved")
        if conservation["changed_outside_touched"]:
            faults.append(f"{entry['sample']}: changed outside the repaired set")
        if repair["iterations_run"] > repair_config().max_iterations:
            faults.append(f"{entry['sample']}: iterations above the ceiling")
        if not set(conservation["changed_refs"]) <= set(conservation["touched_refs"]):
            faults.append(f"{entry['sample']}: changed is not a subset of touched")
    record("check_05e_every_run_conserved_its_document", not faults, "; ".join(faults))


def check_05f_the_decision_quality_is_measured() -> None:
    """Positive 5f: what the constraint injection did is recorded per sample.

    Not asserted as a target. A model's selection is not a property this gate
    can require, and a batch that asserted an improvement would be a batch that
    had to produce one. What is required is that the measurement exists for
    every sample, is derived from the run rather than written down, and is
    stated beside the same measurement from the previous batch.
    """
    data = evidence()
    faults = []
    quality = data.get("decision_quality") or {}
    ledger = {entry["sample"] for entry in load_json(LEDGER)}
    for sample in sorted(ledger):
        row = quality.get(sample)
        if row is None:
            faults.append(f"{sample}: no selection measured")
            continue
        for key in ("named", "eligible_named", "eligible_available", "previous_named"):
            if key not in row:
                faults.append(f"{sample}: the measurement omits {key}")
        if row.get("named") and row.get("eligible_named", 0) > row["named"]:
            faults.append(f"{sample}: more eligible named than named")
    record("check_05f_the_decision_quality_is_measured", not faults, "; ".join(faults))


# --- 06 the scope -------------------------------------------------------------


def check_06a_no_upstream_change() -> None:
    """Negative 6a: this batch changes no upstream file and no ground truth."""
    changed = changed_paths()
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    faults = []
    if upstream:
        faults.append(f"upstream changed: {upstream}")
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    for path in READ_ONLY:
        if path in changed:
            faults.append(f"{path} is ground truth and was changed")
    if any(path.startswith("reviews/") for path in changed):
        faults.append("a ruling was edited")
    record("check_06a_no_upstream_change", not faults, "; ".join(faults))


def check_06b_no_vocabulary_literals() -> None:
    """Negative 6b: no page type and no layout label is written into the code."""
    declared = set(load_taxonomy().names())
    for action in repair_config().actions.values():
        declared |= set(action.applicability.get(react_config.ORPHAN_LABELS_KEY, ()))
    faults = []
    for relative in SESSION_CODE:
        if relative.startswith("spec_checks/"):
            # A gate builds documents and names the labels it builds them with;
            # what may not name one is the package the pipeline runs.
            continue
        tree = ast.parse(source_of(relative))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ) and ast.get_docstring(node) is not None:
                docstrings.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and node.value in declared
            ):
                faults.append(f"{relative}:{node.lineno} names {node.value!r}")
    record("check_06b_no_vocabulary_literals", not faults, "; ".join(faults))


def check_06c_ascii_prose() -> None:
    """Negative 6c: the code and configuration this batch touches are English."""
    faults = []
    files = [
        *SESSION_CODE,
        "configs/detectors.json",
        "configs/repair_actions.json",
        "configs/gate_cache.json",
        "configs/output_retention.json",
        "prompts/react_repair_decide.md",
    ]
    for relative in files:
        for number, line in enumerate(source_of(relative).splitlines(), start=1):
            if not line.isascii():
                offenders = [
                    unicodedata.name(char, hex(ord(char)))
                    for char in line
                    if not char.isascii()
                ]
                faults.append(f"{relative}:{number} {offenders[:3]}")
    record("check_06c_ascii_prose", not faults, "; ".join(faults[:5]))


def check_06d_the_gate_spends_no_credential() -> None:
    """Negative 6d: this gate imports no driver and reads no credential."""
    tree = ast.parse(source_of(f"spec_checks/{Path(__file__).name}"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    faults = [
        f"imports {name}"
        for name in sorted(imported)
        if "translator" in name or "openai" in name or name.endswith("run_repair_smoke")
    ]
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith(suffix)
        ):
            faults.append(f"line {node.lineno} names a credential variable")
    record("check_06d_the_gate_spends_no_credential", not faults, "; ".join(faults))


def check_06e_report_quotes_the_evidence() -> None:
    """Positive 6e: the report's headline numbers are in the evidence file."""
    data = evidence()
    text = REPORT.read_text(encoding="utf-8")
    wanted = [
        data["loop"]["stopped_because"],
        SUBJECT,
        SUBJECT_LINE,
        str(data["blast_radius"]["paragraphs_compared"]),
        controller.STOP_CONVERGED_WITH_RESIDUALS,
    ]
    missing = [token for token in wanted if token not in text]
    record("check_06e_report_quotes_the_evidence", not missing, f"absent {missing}")


def check_06f_registered() -> None:
    """Positive 6f: the plan and the registries say what this batch did."""
    faults = []
    if not (ROOT / "plans" / "PLAN_B8_4.md").is_file():
        faults.append("the plan is not in the tree")
    upstream = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    if "reading_order" not in upstream:
        faults.append("the coupling registry does not name the shared reader")
    record("check_06f_registered", not faults, "; ".join(faults))


# --- 07 the sweep -------------------------------------------------------------


def check_07_sweep() -> None:
    """Positive 7: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_07_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_07_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks = [
        check_01a_the_subject_reads_as_its_line,
        check_01b_horizontal_paragraphs_are_byte_identical,
        check_01c_the_order_is_read_from_the_geometry,
        check_01d_one_reader_for_the_whole_package,
        check_02a_converged_with_residuals,
        check_02b_untreated_set_not_shrinking_rolls_back,
        check_02c_the_two_bounds_did_not_move,
        check_02d_progress_is_declared_not_assumed,
        check_03a_the_request_states_the_rule,
        check_03b_the_known_correct_selection_is_refused_nothing,
        check_03c_naming_what_the_rule_refuses_costs_the_quota,
        check_03d_statements_are_declared_for_every_term,
        check_03e_prompt_rounds_are_recorded,
        check_04a_a_live_build_is_exempt_and_an_abandoned_one_is_not,
        check_04b_the_build_takes_and_drops_its_lock,
        check_04c_retention_keeps_what_it_declares,
        check_04d_baselines_are_archives_that_round_trip,
        check_04e_the_sweep_applies_the_policy,
        check_05a_artefacts_present,
        check_05b_the_subject_was_asked_the_right_question,
        check_05c_the_pixels_agree_with_the_document,
        check_05d_the_strip_is_still_a_strip,
        check_05e_every_run_conserved_its_document,
        check_05f_the_decision_quality_is_measured,
        check_05g_a_repair_landed_and_held_its_box,
        check_05h_the_strip_was_refused_rather_than_rearranged,
        check_06a_no_upstream_change,
        check_06b_no_vocabulary_literals,
        check_06c_ascii_prose,
        check_06d_the_gate_spends_no_credential,
        check_06e_report_quotes_the_evidence,
        check_06f_registered,
        check_07_sweep,
    ]
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(check.__name__, False, f"raised {exc!r}")
    print(f"\nspec_check_b8_4: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.write_stats("spec_check_b8_4")
        artifacts.print_stats("spec_check_b8_4")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
