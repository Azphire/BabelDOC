"""Gate script for batch B9.2 (heading typesetting: mechanics and acceptance).

Run from the repository root:

    python spec_checks/spec_check_b9_2.py

Exit code 0 when every assertion this session answers for passes, 1 otherwise.
Needs no API key and makes no network request: no engine is constructed here and
every document this gate reasons about is either built in this file or read from
a frozen artefact.

01 is the premise. The four facts the batch was planned against are asserted as
facts about upstream rather than quoted from a plan, so that a change upstream
turns them red instead of turning the design quietly wrong.

  a. Source text is not erased, it is omitted. A page's content stream is
     rebuilt from the intermediate language -- the page's own base operations
     are not carried into it -- and base operations, page and xobject alike, are
     collected with every text operator filtered out. So a paragraph's source
     glyphs reach the output only through the paragraph, and a layer dropped
     from the document is gone from the output whether it was source or
     translation.
  b. Nothing upstream can be told not to break a line. The layout wraps when a
     unit would cross the right edge of the box and there is no parameter that
     says otherwise, so a single line is obtained by scale and verified against
     the characters that came back rather than requested.
  c. The first line indent is an intermediate language attribute the layout
     reads, so closing it is writing it False before laying the paragraph out.
  d. A chain's backfill is applied inside the translator, the translator runs
     before the typesetting stage, and this pass runs after it. The order the
     batch requires -- backfill first, scale after -- is the pipeline's own.

02 is the mechanics, on documents built here. An over-wide heading is set on one
line; one that would need a scale below the floor is not squeezed in and is
raised instead; an indent is closed; the two paints of one headline become one
headline and neither layer reaches the writer; two heading paragraphs standing
on each other become one; and a chain member is scaled without its backfilled
text being touched. The duplicate-layer case is built from the geometry and the
paint strings of a real one, named in the fixture below.

03 is conservation and the default. With the switch down the document is byte
for byte the one the stage produced. With it up the pages keep their paragraphs
and every paragraph that is not a heading is byte for byte what it was.

04 is the configuration: bounded, refused when it is not, and naming no layout
label of its own.

05 is the scope and 06 the sweep.

07 is session two: the acceptance, over the pair of runs the batch was accepted
on. Those runs spent a credential and this gate does not, so what it reads is
their frozen evidence -- the ledger, the rasters, and an excerpt of the document
the doubled headline is in, all of them committed. Every assertion of 07 either
recomputes something from that excerpt with the pipeline's own code or holds the
ledger to a claim the batch made:

  a. The arms translated one document. A third arm repeats the first one's
     configuration, which is what says how much a run of this pipeline differs
     from itself -- the model is sampled and a request the cache did not keep is
     asked again -- and the switch's pair is read against it: where the repeat
     agrees, the pair has to agree, and a page whose pixels moved has to be a
     page a heading changed on.
  b. The doubled headline is drawn once, where it was drawn twice.
  c. Both cover headings come off two lines, the ink still outside the page
     frame is less than it was, and that residue is on the record as an open
     defect: it is a different mechanism and this batch does not close it.
  d. Every heading of the ruled sample is on one line or raised, and the eight
     names that ruling gained were carried into the run's glossary.
  e. Every heading that reached the floor is listed with the scale it asked for.
  f. A doubled heading does not reach M3.
  g. The arm with the switch up asked the model nothing new: what it spent is
     what a repeat run spends, far below what the first arm paid.

Every assertion is static; there is no pipeline tier.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import functools
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.backend.pdf_creater import PDFCreater  # noqa: E402
from babeldoc.format.pdf.new_parser.base_operations import (  # noqa: E402
    collect_page_base_inner_operation,
)
from babeldoc.format.pdf.new_parser.tokenizer import PdfOperation  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from babeldoc.magazine.chain_signals import CLASS_LABELS_KEY  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build:
# every document it asserts on is a stub it builds itself or evidence a
# batch froze, so it answers in seconds to a couple of minutes and runs on
# every batch.
GATE_SET = "fast"

BATCH_TAG = "batch-b9.2.2"

PYTHON = sys.executable

# This gate writes no artefact of its own: every document it reasons about is
# built in this file or read from a frozen one. So it creates no batch directory
# under examples/output/ either -- an empty one would still count as a batch to
# the retention policy and push an older batch out of the window it protects,
# which is how a gate that produces nothing can still delete another's evidence.
# The acceptance runs of session two do create one, and everything of theirs
# this gate reads is committed for that reason: what retention deletes is what
# git does not hold, and 07 asserts that it holds all of it.

LANGUAGE = "zh"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Paths this batch may change.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "spec_checks/",
    "examples/output/b9_2/",
)
ALLOWED_FILES = {"plans/PLAN_B9_2.md"}

# The ruling this session re-pinned, in its own commit ahead of the mechanics.
# 04d is where its revision is held to being the owner's and only theirs.
RULING = "reviews/Courier-en.decisions.json"

# A document of the sample that ruling answers for, committed by B8 and read
# here so the ruling's paragraph references are checked against real paragraphs.
RULING_DOCUMENT = "examples/output/b8/Courier-en.typeset.fixture.xml"

# The gate whose pinned digest this session moved.
PINNING_GATE = "spec_checks/spec_check_b7_5.py"

# Files a run may never write to.
READ_ONLY = ("corpus/registry.user.json", "corpus/page_labels.json")

# The code this batch adds or reworks.
SESSION_CODE = (
    "babeldoc/magazine/title_typeset.py",
    "babeldoc/magazine/detectors/__init__.py",
    "spec_checks/run_all.py",
    f"spec_checks/{Path(__file__).name}",
)

# The two scripts session two drove and read its runs with. They are evidence
# rather than pipeline, so they are held to the prose and vocabulary rules but
# are not part of what 05a calls this batch's code.
ACCEPTANCE_CODE = (
    "examples/output/b9_2/scripts/run_b9_2_ab.py",
    "examples/output/b9_2/scripts/analyze_b9_2.py",
)

# What session two froze, all of it committed. The ledger is what the runs
# recorded, the excerpt is the smallest document still carrying the doubled
# headline, and the sidecar is what the pass wrote for the run it came from.
EVIDENCE = "examples/output/b9_2/evidence.json"
ACCEPTANCE_REPORT = "examples/output/b9_2/report.md"
FIXTURE = "examples/output/b9_2/fixtures/AramcoWorld-en-v2.titles.xml"
FIXTURE_SIDECAR = (
    "examples/output/b9_2/fixtures/AramcoWorld-en-v2.title_typeset.report.json"
)

# How many samples the acceptance ran, and how many person names the ruling's
# revision added. Both are claims of the batch rather than measurements, so a
# run that quietly covered less turns 07 red instead of passing thinner.
ACCEPTANCE_SAMPLES = 5
RULED_TERMS_ADDED = 8

# Upstream symbols the premise assertions read, named here so a rename is
# traceable to the assertion it breaks rather than to a line number.
WRITER_SOURCE = "babeldoc/format/pdf/document_il/backend/pdf_creater.py"
WRITER_FUNCTION = "update_page_content_stream"
LAYOUT_SOURCE = "babeldoc/format/pdf/document_il/midend/typesetting.py"
LAYOUT_FUNCTION = "_layout_typesetting_units"
PIPELINE_SOURCE = "babeldoc/format/pdf/high_level.py"
FINDER_SOURCE = "babeldoc/format/pdf/document_il/midend/paragraph_finder.py"

# The real defect case 02d is built from: batch F1's AramcoWorld-en-v2, file page
# five, whose display headline the source draws twice -- a solid layer and a
# pattern layer at identical coordinates -- which the paragraph finder recovered
# as one paragraph of two style runs and the translator answered twice over. The
# paint strings are the ones that run recorded.
GHOST_SOLID = "/GS0 gs /GS1 gs /GS0 gs /CS0 cs 1 scn /GS1 gs 0 0 0 0.755000 k /GS0 gs"
GHOST_PATTERN = (
    "/GS0 gs /GS1 gs /GS0 gs /GS1 gs 0 0 0 0.755000 k /GS0 gs /CS2 cs /P0 scn"
)
# The headline as that run translated it, per layer. Written as escapes so no
# source file of this project carries text outside ASCII. ("railway?")
GHOST_LAYER = "\u94c1\u8def\uff1f"
GHOST_SIZE = 79.1395
GHOST_BOX = (54.07, 695.46, 566.65, 753.94)

# A heading long enough that one line of it needs shrinking, and one long enough
# that no allowed scale fits it. Ten and forty CJK characters ("one" to "ten").
WIDE_TEXT = "\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341"
FLOOR_TEXT = WIDE_TEXT * 4
# What a chain backfill would have written into one member: two halves of one
# sentence, joined ("the first half and the second half make one line").
CHAIN_TEXT = (
    "\u524d\u534a\u53e5\u4e0e\u540e\u534a\u53e5\u5408\u4e3a\u4e00\u884c"
)

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b9_2_"))

# The gate never writes a review draft into the working tree it asserts about.
os.environ[hitl.REVIEWS_ENV] = str(_tmp_root / "reviews")

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b9_2")


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


def git_text(args: list[str]) -> tuple[int, str]:
    """``git_output`` for a file that is not ASCII.

    A ruling carries rendered names, which are not ASCII, and the default
    decoding here is the console's rather than the file's.
    """
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return proc.returncode, proc.stdout or ""


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


def source_of(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def function_node(relative: str, name: str):
    for node in ast.walk(ast.parse(source_of(relative))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


# --- documents built here -----------------------------------------------------


BUILT_FONT = "base"


def policy():
    return title_typeset.load_title_config()


def title_label() -> str:
    """The layout label a heading carries, read from the policy's own classes."""
    return policy().labels[0]


def body_label() -> str:
    """A label no heading class claims, so a paragraph carrying it is not one."""
    declared = load_chain_config()[CLASS_LABELS_KEY]
    headings = set(policy().labels)
    for labels in declared.values():
        for label in labels:
            if label not in headings:
                return label
    raise AssertionError("every declared endpoint label is a heading label")


def style(size: float, paint: str | None = None):
    return il_version_1.PdfStyle(
        font_id=BUILT_FONT,
        font_size=size,
        graphic_state=il_version_1.GraphicState(
            passthrough_per_char_instruction=paint
        ),
    )


def character(text: str, x: float, y: float, size: float, paint: str | None):
    return il_version_1.PdfParagraphComposition(
        pdf_character=il_version_1.PdfCharacter(
            char_unicode=text,
            box=il_version_1.Box(x, y, x + size, y + size),
            pdf_style=style(size, paint),
            vertical=False,
            xobj_id=-1,
        )
    )


def laid_out(
    text: str,
    box: tuple[float, float, float, float],
    size: float,
    label: str,
    paint_of=None,
    line_of=None,
    indent: bool = False,
    chain_id: str | None = None,
    debug_id: str = "built",
):
    """One paragraph as the typesetting stage leaves it: one character per member.

    ``line_of`` places a character on a later line, which is what a wrapped
    heading looks like coming out of the stage; ``paint_of`` gives it the paint
    of one layer, which is what two layers of one headline look like.
    """
    members = []
    x = box[0]
    top = box[3] - size
    for index, item in enumerate(text):
        line = 0 if line_of is None else line_of(index)
        if line_of is not None and index and line != line_of(index - 1):
            x = box[0]
        members.append(
            character(
                item,
                x,
                top - line * size * 1.3,
                size,
                None if paint_of is None else paint_of(index),
            )
        )
        x += size
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*box),
        pdf_paragraph_composition=members,
        unicode=text,
        layout_label=label,
        debug_id=debug_id,
        vertical=False,
        xobj_id=-1,
        first_line_indent=indent,
        scale=1.0,
        optimal_scale=1.0,
        pdf_style=style(size),
        render_order=10,
        chain_id=chain_id,
    )


def page(paragraphs, number: int = 0):
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=il_version_1.Box(0.0, 0.0, 631.5, 807.0)),
        cropbox=il_version_1.Cropbox(box=il_version_1.Box(0.0, 0.0, 631.5, 807.0)),
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


def Config(directory: Path, **attributes):  # noqa: N802
    from babeldoc.format.pdf.translation_config import TranslationConfig

    directory.mkdir(parents=True, exist_ok=True)
    config = TranslationConfig(
        translator=None,
        input_file=str(ROOT / "examples" / "input" / "Courier-en.pdf"),
        lang_in="en",
        lang_out=LANGUAGE,
        doc_layout_model=LayoutModel(),
        working_dir=directory,
        output_dir=directory / "out",
        progress_monitor=None,
        auto_extract_glossary=False,
        skip_translation=False,
    )
    for name, value in attributes.items():
        setattr(config, name, value)
    return config


_counter = [0]


def sidecar_dir(config) -> Path:
    """Where the pass writes, resolved the way the pass resolves it.

    The configuration nests a directory of its own under the one it is given, so
    the path is asked for rather than assumed.
    """
    return Path(config.get_working_file_path(title_typeset.REPORT_NAME)).parent


def run_pass(docs, **attributes):
    """Apply the pass to a document, in a working directory of its own."""
    _counter[0] += 1
    directory = _tmp_root / f"run{_counter[0]}"
    config = Config(directory, magazine_title_typeset=True, **attributes)
    return title_typeset.apply(config, docs), sidecar_dir(config)


def rendered(paragraph) -> str:
    return "".join(
        item.char_unicode or ""
        for item in title_typeset.laid_out_characters(paragraph)
    )


def lines(paragraph) -> int:
    return len(
        title_typeset.line_bands(
            title_typeset.laid_out_characters(paragraph), policy().line_band_tolerance
        )
    )


def ghost_page():
    """The real duplicate-layer case, rebuilt from what F1 recorded."""
    return page(
        [
            laid_out(
                GHOST_LAYER * 2,
                GHOST_BOX,
                GHOST_SIZE,
                title_label(),
                paint_of=lambda index: (
                    GHOST_SOLID if index < len(GHOST_LAYER) else GHOST_PATTERN
                ),
                debug_id="ghost",
            )
        ]
    )


# --- 01 the premise -----------------------------------------------------------


def check_01a_erasure_is_omission() -> None:
    """Positive 1a: source text leaves the output by not being in the document.

    Two halves. The writer rebuilds a page's stream without carrying the page's
    own base operations into it, so nothing of the original page survives except
    what the intermediate language still holds. And the base operations that
    *are* carried -- an xobject's -- are collected with every operator beginning
    with T dropped, which takes the font selection with it, and with the shown
    strings dropped as well. The markers opening and closing a text object
    survive and paint nothing, having neither a font nor a string between them.
    Together these are why dropping a layer from the document drops it from the
    page, and why the pass needs no erasure path of its own.
    """
    faults = []
    node = function_node(WRITER_SOURCE, WRITER_FUNCTION)
    if node is None:
        faults.append(f"{WRITER_SOURCE} has no {WRITER_FUNCTION}")
    else:
        carried = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and child.attr == "base_operations":
                owner = child.value
                carried.add(owner.id if isinstance(owner, ast.Name) else "?")
        if "page" in carried:
            faults.append(
                "the writer carries the page's base operations into the rebuilt "
                "stream, so the source text of the page is no longer omitted"
            )
        if "xobj" not in carried:
            faults.append(
                "the writer no longer carries an xobject's base operations; the "
                "second half of this premise is about a path that has moved"
            )
    # The collector is asked directly, with a whole text run and one path
    # operation, rather than read.
    collected = collect_page_base_inner_operation(
        [
            PdfOperation(operands=[], operator="BT"),
            PdfOperation(operands=["/F1", 12], operator="Tf"),
            PdfOperation(operands=[10, 10], operator="Td"),
            PdfOperation(operands=["(hello)"], operator="Tj"),
            PdfOperation(operands=[1, 0, 0, 1, 0, 0], operator="Tm"),
            PdfOperation(operands=["(again)"], operator="'"),
            PdfOperation(operands=[], operator="ET"),
            PdfOperation(operands=[0.5], operator="w"),
        ]
    )
    leaked = [
        token
        for token in ("Tf", "Tj", "Tm", "Td", "/F1", "hello", "again")
        if token in collected
    ]
    if leaked:
        faults.append(f"base operations carry text: {leaked} in {collected!r}")
    if "w" not in collected:
        faults.append(f"base operations lost a graphics operator: {collected!r}")
    record("check_01a_erasure_is_omission", not faults, "; ".join(faults))


def check_01b_no_upstream_flag_forbids_a_break() -> None:
    """Negative 1b: no parameter of the layout can be set to forbid a wrap.

    The wrap is unconditional on the box: the layout compares the running x
    against ``box.x2`` and starts a new line, and nothing in the signature or
    the body gates that on a caller's choice. So the mechanism this batch uses
    is the scale, and the assertion that matters is that the mechanism the batch
    did *not* use still does not exist -- otherwise this pass is reimplementing
    something upstream offers.
    """
    faults = []
    node = function_node(LAYOUT_SOURCE, LAYOUT_FUNCTION)
    if node is None:
        faults.append(f"{LAYOUT_SOURCE} has no {LAYOUT_FUNCTION}")
    else:
        names = {argument.arg for argument in node.args.args}
        offered = sorted(
            name
            for name in names
            if "wrap" in name
            or ("break" in name and name != "use_english_line_break")
        )
        if offered:
            faults.append(
                f"the layout now offers {offered}; a single line may be asked "
                f"for rather than obtained"
            )
        source = ast.get_source_segment(source_of(LAYOUT_SOURCE), node) or ""
        if "box.x2" not in source:
            faults.append("the layout no longer wraps on the box's right edge")
    for name in ("retypeset_with_precomputed_scale", "render_paragraph"):
        entry = function_node(LAYOUT_SOURCE, name)
        if entry is None:
            faults.append(f"{LAYOUT_SOURCE} has no {name}")
            continue
        if any(
            "wrap" in argument.arg or "single_line" in argument.arg
            for argument in entry.args.args
        ):
            faults.append(f"{name} now takes a wrapping parameter")
    record("check_01b_no_upstream_flag_forbids_a_break", not faults, "; ".join(faults))


def check_01c_the_indent_is_an_attribute_the_layout_reads() -> None:
    """Positive 1c: the indent is carried on the paragraph and read at layout.

    Written by the paragraph finder from where the first line starts, read by
    the layout as an offset applied before the first unit is placed. So closing
    it is writing the attribute, and it is asserted by writing it: one paragraph
    laid out with it and one without have to start at different x.
    """
    faults = []
    finder = source_of(FINDER_SOURCE)
    if "paragraph.first_line_indent = True" not in finder:
        faults.append("the paragraph finder no longer sets the indent")
    node = function_node(LAYOUT_SOURCE, LAYOUT_FUNCTION)
    source = "" if node is None else (ast.get_source_segment(source_of(LAYOUT_SOURCE), node) or "")
    if "paragraph.first_line_indent" not in source:
        faults.append("the layout no longer reads the indent")

    indented = laid_out(
        WIDE_TEXT, (50.0, 600.0, 560.0, 660.0), 20.0, title_label(), indent=True
    )
    docs = document([page([indented])])
    report, _ = run_pass(docs)
    after = docs.page[0].pdf_paragraph[0]
    entry = report["titles"][0]
    if not entry["indent_closed"]:
        faults.append("the report does not say the indent was closed")
    if after.first_line_indent:
        faults.append("the indent is still set on the paragraph")
    first = title_typeset.laid_out_characters(after)[0]
    if abs(float(first.box.x) - 50.0) > 0.5:
        faults.append(f"the first character starts at {first.box.x}, not at the box")
    record(
        "check_01c_the_indent_is_an_attribute_the_layout_reads",
        not faults,
        "; ".join(faults),
    )


def check_01d_backfill_precedes_the_layout_precedes_this_pass() -> None:
    """Positive 1d: the order the batch requires is the pipeline's own order.

    A chain's backfill is written by the translator; the typesetting stage runs
    after the translator; this pass is reached from the detection call, which
    runs after the stage. Read from the pipeline's source in that order, so a
    reordering upstream is what turns this red.
    """
    faults = []
    source = source_of(PIPELINE_SOURCE).splitlines()
    positions = {}
    for name, needle in (
        ("translate", "il_translator.translate(docs)"),
        ("typeset", "Typesetting(translation_config).typesetting_document(docs)"),
        ("detect", "detectors.detect_issues(translation_config, docs)"),
    ):
        found = [index for index, line in enumerate(source) if needle in line]
        if not found:
            faults.append(f"the pipeline no longer calls {needle}")
        else:
            positions[name] = found[0]
    if len(positions) == 3 and not (
        positions["translate"] < positions["typeset"] < positions["detect"]
    ):
        faults.append(f"the pipeline order changed: {positions}")
    # And the pass is reached from that call rather than from a call of its own.
    detect_source = source_of("babeldoc/magazine/detectors/__init__.py")
    if "title_typeset.apply(translation_config, docs)" not in detect_source:
        faults.append("the detection window no longer reaches the heading pass")
    if "title_typeset" in source_of(PIPELINE_SOURCE):
        faults.append("the pipeline names the heading pass; upstream was changed")
    record(
        "check_01d_backfill_precedes_the_layout_precedes_this_pass",
        not faults,
        "; ".join(faults),
    )


# --- 02 the mechanics ---------------------------------------------------------


def check_02a_an_over_wide_heading_is_set_on_one_line() -> None:
    """Positive 2a: a heading the stage wrapped comes back on one line."""
    faults = []
    wide = laid_out(
        WIDE_TEXT,
        (50.0, 600.0, 300.0, 660.0),
        40.0,
        title_label(),
        line_of=lambda index: 0 if index < 6 else 1,
    )
    docs = document([page([wide])])
    report, _ = run_pass(docs)
    after = docs.page[0].pdf_paragraph[0]
    entry = report["titles"][0]
    if entry["lines_before"] != 2:
        faults.append(f"the heading was not wrapped to begin with: {entry}")
    if entry["disposition"] != title_typeset.DISPOSITION_SINGLE_LINE:
        faults.append(f"disposition {entry['disposition']}")
    if lines(after) != 1:
        faults.append(f"{lines(after)} line(s) after the pass")
    if not 0 < entry["scale"] < 1:
        faults.append(f"scale {entry['scale']} is not a shrink")
    if rendered(after) != WIDE_TEXT:
        faults.append("the heading's text changed")
    characters = title_typeset.laid_out_characters(after)
    right = max(float(item.box.x2) for item in characters)
    if right > 300.0:
        faults.append(f"the line runs to {right}, past the box")
    record(
        "check_02a_an_over_wide_heading_is_set_on_one_line", not faults, "; ".join(faults)
    )


def check_02b_below_the_floor_is_raised_not_squeezed() -> None:
    """Negative 2b: a heading needing less than the floor is left, and raised.

    Left as the stage laid it out -- the pass restores what it found rather than
    setting it at a scale the policy calls illegible -- and named in the report's
    escalations with the scale it asked for, which is the list a human answers.
    """
    faults = []
    before = laid_out(
        FLOOR_TEXT,
        (50.0, 600.0, 200.0, 660.0),
        40.0,
        title_label(),
        line_of=lambda index: index // 4,
    )
    original = copy.deepcopy(before)
    docs = document([page([before])])
    report, _ = run_pass(docs)
    after = docs.page[0].pdf_paragraph[0]
    entry = report["titles"][0]
    if entry["disposition"] != title_typeset.DISPOSITION_FLOOR:
        faults.append(f"disposition {entry['disposition']}")
    if entry.get("required_scale", 1.0) >= policy().title_min_scale:
        faults.append(f"the case does not reach the floor: {entry}")
    if not entry.get("restored"):
        faults.append("the heading was not put back")
    if rendered(after) != rendered(original):
        faults.append("the restored heading is not the one the stage produced")
    boxes_before = [
        (item.box.x, item.box.y) for item in title_typeset.laid_out_characters(original)
    ]
    boxes_after = [
        (item.box.x, item.box.y) for item in title_typeset.laid_out_characters(after)
    ]
    if boxes_before != boxes_after:
        faults.append("the restored heading was moved")
    escalated = [item["reference"] for item in report["escalations"]]
    if escalated != [entry["reference"]]:
        faults.append(f"escalations {escalated}")
    if report["escalations"] and report["escalations"][0]["required_scale"] is None:
        faults.append("the escalation does not say what scale it asked for")
    record(
        "check_02b_below_the_floor_is_raised_not_squeezed", not faults, "; ".join(faults)
    )


def check_02c_two_paints_of_one_headline_become_one() -> None:
    """Positive 2c: the real duplicate-layer case, and both layers erased.

    The headline is drawn twice in the source, so the paragraph carries the
    translation twice. One copy survives the pass. Erasure is asserted where it
    actually happens: the characters the writer would draw for this page are
    read from the writer's own function, and neither the source text nor a
    second copy of the translation is among them.
    """
    faults = []
    docs = document([ghost_page()])
    report, _ = run_pass(docs)
    after = docs.page[0].pdf_paragraph[0]
    if rendered(after) != GHOST_LAYER:
        faults.append(f"the page still shows {rendered(after)!r}")
    if lines(after) != 1:
        faults.append(f"{lines(after)} line(s)")
    duplicates = report["duplicates"]
    if len(duplicates) != 1 or duplicates[0]["layer"] != title_typeset.LAYER_RUN:
        faults.append(f"duplicates {duplicates}")
    elif duplicates[0]["similarity"] < policy().duplicate_min_text_similarity:
        faults.append(f"recorded a weaker agreement than the rule needs: {duplicates}")
    # What the writer would draw. Called unbound: the function reads only the
    # paragraph it is given, and building a writer needs a PDF this gate has no
    # business opening.
    drawn = "".join(
        item.char_unicode or ""
        for paragraph in docs.page[0].pdf_paragraph
        for item in PDFCreater.render_paragraph_to_char(None, paragraph)
    )
    if drawn != GHOST_LAYER:
        faults.append(f"the writer would draw {drawn!r}")
    record(
        "check_02c_two_paints_of_one_headline_become_one", not faults, "; ".join(faults)
    )


def check_02d_overlapping_heading_paragraphs_become_one() -> None:
    """Positive 2d: two heading paragraphs standing on each other, deduplicated.

    The larger keeps the page. The smaller keeps its place in the document --
    the paragraph count is conserved -- and draws nothing at all, which is the
    same erasure the run-level case gets and for the same reason.
    """
    faults = []
    text = GHOST_LAYER
    primary = laid_out(
        text, (50.0, 700.0, 300.0, 760.0), 40.0, title_label(), debug_id="primary"
    )
    secondary = laid_out(
        text, (52.0, 702.0, 296.0, 757.0), 40.0, title_label(), debug_id="secondary"
    )
    docs = document([page([primary, secondary])])
    report, _ = run_pass(docs)
    kept, dropped = docs.page[0].pdf_paragraph
    if len(docs.page[0].pdf_paragraph) != 2:
        faults.append("a paragraph was removed")
    if rendered(kept) != text:
        faults.append(f"the surviving heading shows {rendered(kept)!r}")
    if dropped.pdf_paragraph_composition:
        faults.append("the second layer still has a composition")
    if dropped.unicode:
        faults.append("the second layer still carries text")
    drawn = PDFCreater.render_paragraph_to_char(None, dropped)
    if drawn:
        faults.append(f"the writer would draw {len(drawn)} character(s) of it")
    entries = [item for item in report["duplicates"] if item["layer"] == "paragraph"]
    if len(entries) != 1:
        faults.append(f"duplicates {report['duplicates']}")
    else:
        entry = entries[0]
        if entry["duplicate_of"] != "p1#0" or entry["reference"] != "p1#1":
            faults.append(f"the pair is recorded as {entry}")
        if entry["iou"] < policy().duplicate_min_iou:
            faults.append(f"recorded a weaker overlap than the rule needs: {entry}")
    if report["totals"]["suppressed_paragraphs"] != 1:
        faults.append(f"totals {report['totals']}")
    record(
        "check_02d_overlapping_heading_paragraphs_become_one",
        not faults,
        "; ".join(faults),
    )


def check_02e_a_chain_member_is_scaled_after_its_backfill() -> None:
    """Positive 2e: a chain member's text is what the backfill left it.

    The member arrives carrying the sentence the backfill wrote into it and
    wrapped across two lines. The pass sets it on one line and does not touch a
    character of it, which is the whole of the ordering requirement: what is
    scaled is the backfilled text, and scaling never rewrites it.
    """
    faults = []
    member = laid_out(
        CHAIN_TEXT,
        (50.0, 600.0, 330.0, 660.0),
        36.0,
        title_label(),
        line_of=lambda index: 0 if index < 5 else 1,
        chain_id="chain-1",
        debug_id="member",
    )
    docs = document([page([member])])
    report, _ = run_pass(docs)
    after = docs.page[0].pdf_paragraph[0]
    if rendered(after) != CHAIN_TEXT:
        faults.append(f"the backfilled text became {rendered(after)!r}")
    if after.chain_id != "chain-1":
        faults.append("the member lost its chain")
    if lines(after) != 1:
        faults.append(f"{lines(after)} line(s)")
    if report["titles"][0]["disposition"] != title_typeset.DISPOSITION_SINGLE_LINE:
        faults.append(f"disposition {report['titles'][0]['disposition']}")
    record(
        "check_02e_a_chain_member_is_scaled_after_its_backfill",
        not faults,
        "; ".join(faults),
    )


def check_02f_a_heading_with_nothing_to_answer_for_is_left_alone() -> None:
    """Negative 2f: a heading already on one line is not laid out again.

    A pass that reproduces a rendering it had no reason to change is a pass that
    can change it. So the no-op case is asserted at the byte level rather than
    at the level of what it looks like.
    """
    faults = []
    settled = laid_out(
        GHOST_LAYER, (50.0, 700.0, 400.0, 760.0), 40.0, title_label(), debug_id="settled"
    )
    docs = document([page([settled])])
    before = controller.paragraph_digests(docs)
    report, _ = run_pass(docs)
    after = controller.paragraph_digests(docs)
    if before != after:
        faults.append("the heading was rewritten")
    entry = report["titles"][0]
    if entry["disposition"] != title_typeset.DISPOSITION_UNCHANGED:
        faults.append(f"disposition {entry['disposition']}")
    if entry.get("scale") is not None:
        faults.append("a scale was applied to a heading that needed none")
    record(
        "check_02f_a_heading_with_nothing_to_answer_for_is_left_alone",
        not faults,
        "; ".join(faults),
    )


# --- 03 conservation and the default ------------------------------------------


def mixed_document():
    """One document carrying every case, plus paragraphs that are not headings."""
    return document(
        [
            ghost_page(),
            page(
                [
                    laid_out(
                        WIDE_TEXT,
                        (50.0, 600.0, 300.0, 660.0),
                        40.0,
                        title_label(),
                        line_of=lambda index: 0 if index < 6 else 1,
                        debug_id="wide",
                    ),
                    laid_out(
                        FLOOR_TEXT,
                        (50.0, 400.0, 200.0, 460.0),
                        40.0,
                        title_label(),
                        line_of=lambda index: index // 4,
                        debug_id="floor",
                    ),
                    laid_out(
                        WIDE_TEXT,
                        (50.0, 100.0, 560.0, 130.0),
                        10.0,
                        body_label(),
                        indent=True,
                        debug_id="body",
                    ),
                ],
                number=1,
            ),
        ]
    )


def check_03a_the_switch_down_changes_nothing() -> None:
    """Negative 3a: with the switch down the document is what it was.

    Asserted through the call the pipeline actually makes, so what is measured
    is the pipeline's behaviour rather than the pass's own early return.
    """
    faults = []
    docs = mixed_document()
    before = controller.paragraph_digests(docs)
    directory = _tmp_root / "default_off"
    config = Config(directory)
    issues = detectors.detect_issues(config, docs)
    after = controller.paragraph_digests(docs)
    if before != after:
        changed = sorted(key for key in before if before[key] != after.get(key))
        faults.append(f"changed {changed}")
    if issues:
        faults.append(f"detection ran with its own switch down: {len(issues)} issue(s)")
    if (sidecar_dir(config) / title_typeset.REPORT_NAME).exists():
        faults.append("a sidecar was written")
    if title_typeset.enabled(config):
        faults.append("the switch reads as up by default")
    record("check_03a_the_switch_down_changes_nothing", not faults, "; ".join(faults))


def check_03b_conservation() -> None:
    """Positive 3b: pages keep their paragraphs, non-headings keep their bytes."""
    faults = []
    docs = mixed_document()
    shape_before = controller.shape(docs)
    digests_before = controller.paragraph_digests(docs)
    labels = set(policy().labels)
    headings = {
        f"p{label}#{index}"
        for label, page_ in hitl.labeled_pages(docs)
        for index, paragraph in enumerate(page_.pdf_paragraph)
        if paragraph.layout_label in labels
    }
    report, _ = run_pass(docs)
    shape_after = controller.shape(docs)
    digests_after = controller.paragraph_digests(docs)
    if shape_before != shape_after:
        faults.append(f"shape {shape_before} became {shape_after}")
    if set(digests_before) != set(digests_after):
        faults.append("the set of paragraph references changed")
    strayed = sorted(
        key
        for key in digests_before
        if key not in headings and digests_before[key] != digests_after.get(key)
    )
    if strayed:
        faults.append(f"non-heading paragraphs changed: {strayed}")
    touched = sorted(
        key for key in headings if digests_before[key] != digests_after.get(key)
    )
    if not touched:
        faults.append("no heading changed, so the conservation claim is vacuous")
    if report["totals"]["titles"] != len(headings):
        faults.append(f"the report covers {report['totals']['titles']} of {len(headings)}")
    record("check_03b_conservation", not faults, "; ".join(faults))


def check_03c_the_sidecar_says_what_was_done() -> None:
    """Positive 3c: the sidecar names every heading, its disposition and its layers."""
    faults = []
    docs = mixed_document()
    report, directory = run_pass(docs)
    path = directory / title_typeset.REPORT_NAME
    if not path.exists():
        faults.append("no sidecar was written")
        record("check_03c_the_sidecar_says_what_was_done", False, "; ".join(faults))
        return
    with path.open(encoding="utf-8") as f:
        written = json.load(f)
    if written != report:
        faults.append("the sidecar and the returned record disagree")
    if written["switch"] != title_typeset.SWITCH:
        faults.append(f"the sidecar names {written['switch']}")
    if written["window_switch"] != detectors.SWITCH:
        faults.append("the sidecar does not name the window it rode")
    dispositions = {item["disposition"] for item in written["titles"]}
    wanted = {
        title_typeset.DISPOSITION_SINGLE_LINE,
        title_typeset.DISPOSITION_FLOOR,
    }
    if not wanted <= dispositions:
        faults.append(f"dispositions {sorted(dispositions)}")
    if written["totals"]["duplicate_layers"] != len(written["duplicates"]):
        faults.append("the totals and the list disagree")
    manifest = directory / "magazine_config_manifest.json"
    if not manifest.exists():
        faults.append("the configuration was not recorded in the run manifest")
    else:
        with manifest.open(encoding="utf-8") as f:
            recorded = json.load(f)
        text = json.dumps(recorded)
        if title_typeset.CONFIG_PATH.name not in text:
            faults.append("the manifest does not name this pass's configuration")
    record("check_03c_the_sidecar_says_what_was_done", not faults, "; ".join(faults))


# --- 04 the configuration -----------------------------------------------------


def check_04a_every_parameter_is_bounded() -> None:
    """Positive 4a: every number declares a range and sits inside it."""
    faults = []
    with title_typeset.CONFIG_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    for key, value in raw.items():
        if key in ("description", *title_typeset._STRUCTURAL_KEYS) or key.endswith(
            "_allowed_range"
        ):
            continue
        if isinstance(value, list):
            continue
        if f"{key}_allowed_range" not in raw:
            faults.append(f"{key} declares no range")
    # A structural key states per target language what a flat key states once,
    # so it is bounded by that flat key's own vocabulary or range rather than by
    # one of its own. Checked here so the property the loop above asserts --
    # nothing numeric is declared without a bound -- reaches the tables too.
    for name, policy_value in raw.get(title_typeset.FLOOR_BY_TARGET_KEY, {}).items():
        if policy_value not in raw.get(title_typeset.FLOOR_VOCABULARY_KEY, []):
            faults.append(f"{title_typeset.FLOOR_BY_TARGET_KEY}[{name}] is unbounded")
    low, high = (
        raw.get(f"{title_typeset.MIN_SCALE_KEY}_allowed_range", "0..0")
        .split("..")
    )
    for name, scale in raw.get(title_typeset.MIN_SCALE_BY_TARGET_KEY, {}).items():
        if not float(low) <= float(scale) <= float(high):
            faults.append(f"{title_typeset.MIN_SCALE_BY_TARGET_KEY}[{name}] {scale}")
    if raw.get(title_typeset.FLOOR_KEY) not in raw.get(
        title_typeset.FLOOR_VOCABULARY_KEY, []
    ):
        faults.append("the floor policy is outside its own vocabulary")
    if title_typeset.FLOOR_ESCALATE not in raw.get(
        title_typeset.FLOOR_VOCABULARY_KEY, []
    ):
        faults.append("the vocabulary omits the policy the report raises under")
    config = policy()
    if not 0 < config.title_min_scale <= 1:
        faults.append(f"title_min_scale {config.title_min_scale}")
    if not 0 < config.scale_shrink_step < 1:
        faults.append(f"scale_shrink_step {config.scale_shrink_step}")
    record("check_04a_every_parameter_is_bounded", not faults, "; ".join(faults))


def check_04b_a_bad_configuration_is_refused() -> None:
    """Negative 4b: out of range, unbounded and unknown policy are all refused."""
    faults = []
    with title_typeset.CONFIG_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)

    def refused(mutate, why: str) -> None:
        broken = json.loads(json.dumps(raw))
        mutate(broken)
        try:
            title_typeset.parse_title_config(broken, "test")
        except title_typeset.TitleTypesetError:
            return
        except Exception as exc:  # noqa: BLE001 - a wrong error is still a fault
            faults.append(f"{why}: raised {exc!r}")
            return
        faults.append(f"{why}: accepted")

    refused(lambda item: item.__setitem__("title_min_scale", 9.0), "out of range")
    refused(lambda item: item.pop("title_min_scale_allowed_range"), "unbounded")
    refused(lambda item: item.__setitem__(title_typeset.FLOOR_KEY, "nope"), "bad policy")
    refused(
        lambda item: item.__setitem__(title_typeset.FLOOR_VOCABULARY_KEY, ["wrap"]),
        "a vocabulary without the raising policy",
    )
    refused(
        lambda item: item.__setitem__(
            title_typeset.FLOOR_BY_TARGET_KEY, {"en": "nope"}
        ),
        "a per target policy outside the vocabulary",
    )
    refused(
        lambda item: item.__setitem__(
            title_typeset.MIN_SCALE_BY_TARGET_KEY, {"en": 9.0}
        ),
        "a per target floor outside the range",
    )
    refused(
        lambda item: item.__setitem__("title_pair_classes", ["not_a_class"]),
        "a heading class the chain detector does not declare",
    )
    record("check_04b_a_bad_configuration_is_refused", not faults, "; ".join(faults))


def pinned_digest(relative: str, gate: str) -> str | None:
    """What ``gate`` pins ``relative`` at, read from its source rather than run.

    Read rather than imported: importing a gate runs its module body, which
    makes temporary directories and moves environment variables belonging to a
    run this one is not performing.
    """
    for node in ast.walk(ast.parse(source_of(gate))):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "TRUTH_DIGESTS":
                with contextlib.suppress(ValueError):
                    return ast.literal_eval(node.value).get(relative)
    return None


def check_04d_the_ruling_revision_is_the_owners_and_only_theirs() -> None:
    """Negative 4d: the re-pinned ruling carries the owner's edit and nothing else.

    This session moved the digest ``spec_check_b7_5`` pins the Courier ruling
    at, under CLAUDE.md 4.12. A pin that moves stops asserting anything on its
    own, so the statement it was making is made here instead, at the level of
    the fields rather than of the bytes.

    Three things. The file still loads under the very validator the pipeline
    reads it with, against a real document of that sample, so the revision is
    well formed, names a declared page type and a declared drop cap verdict, and
    points at paragraphs that exist. The revision against the commit before it
    is additions to the terms and a changed drop cap verdict, with no term
    removed, no term rewritten, no page kind moved and no drop cap reference
    appearing or disappearing -- which is what says a machine did not take the
    opportunity to edit something else while the file was open. And the digest
    now pinned is the digest of what is on disk, so the re-pin describes reality.
    """
    faults = []
    path = ROOT / RULING
    with path.open(encoding="utf-8") as f:
        after = json.load(f)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs = checkpoint_module.load_checkpoint(ROOT / RULING_DOCUMENT)
    labelled = hitl.labeled_pages(docs)
    pages = {label for label, _page in labelled}
    references = {
        f"p{label}#{index}"
        for label, page_ in labelled
        for index in range(len(page_.pdf_paragraph or ()))
    }
    try:
        hitl.parse_decisions(after, path, pages, references)
    except Exception as exc:  # noqa: BLE001 - any refusal is the fault
        faults.append(f"the loader refuses the revision: {exc}")

    code, listing = git_text(["log", "--format=%H", "-n", "2", "--", RULING])
    revisions = listing.split() if code == 0 else []
    if len(revisions) < 2:
        faults.append("the ruling has no previous revision to be compared against")
    else:
        code, text = git_text(["show", f"{revisions[1]}:{RULING}"])
        if code != 0:
            faults.append(f"cannot read {RULING} at {revisions[1]}")
        else:
            before = json.loads(text)
            if set(before) != set(after):
                faults.append(f"sections moved: {sorted(set(before) ^ set(after))}")
            before_terms = before.get("terms") or {}
            after_terms = after.get("terms") or {}
            for term, rendering in before_terms.items():
                if term not in after_terms:
                    faults.append(f"term {term!r} was removed")
                elif after_terms[term] != rendering:
                    faults.append(f"term {term!r} was rewritten")
            if (before.get("page_kinds") or {}) != (after.get("page_kinds") or {}):
                faults.append("a page kind was moved")
            before_caps = before.get("drop_caps") or {}
            after_caps = after.get("drop_caps") or {}
            if set(before_caps) != set(after_caps):
                faults.append(
                    f"drop cap references moved: "
                    f"{sorted(set(before_caps) ^ set(after_caps))}"
                )

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pinned = pinned_digest(RULING, PINNING_GATE)
    if pinned != digest:
        faults.append(f"{PINNING_GATE} pins {pinned}, the file is {digest}")
    record(
        "check_04d_the_ruling_revision_is_the_owners_and_only_theirs",
        not faults,
        "; ".join(faults[:5]),
    )


def check_04c_the_heading_labels_are_declared_elsewhere() -> None:
    """Positive 4c: what a heading is comes from the chain detector's classes."""
    faults = []
    declared = load_chain_config()[CLASS_LABELS_KEY]
    with title_typeset.CONFIG_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    names = raw.get("title_pair_classes", [])
    unknown = sorted(set(names) - set(declared))
    if unknown:
        faults.append(f"{unknown} is no declared class")
    expected = tuple(
        label for name in names for label in declared[name] if name in declared
    )
    if policy().labels != expected:
        faults.append(f"labels {policy().labels} against {expected}")
    if not policy().labels:
        faults.append("no heading label at all")
    record(
        "check_04c_the_heading_labels_are_declared_elsewhere", not faults, "; ".join(faults)
    )


# --- 05 the scope -------------------------------------------------------------


def check_05a_no_upstream_change() -> None:
    """Negative 5a: this session changes no upstream file and no ground truth."""
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
    rulings = sorted(path for path in changed if path.startswith("reviews/"))
    if rulings:
        faults.append(f"a ruling was edited: {rulings}")
    # And no code of this session can reach a ruling in the first place.
    for relative in SESSION_CODE:
        if "reviews" in source_of(relative) and relative != f"spec_checks/{Path(__file__).name}":
            faults.append(f"{relative} names the review directory")
    record("check_05a_no_upstream_change", not faults, "; ".join(faults))


def check_05b_no_vocabulary_literals() -> None:
    """Negative 5b: no page type and no layout label is written into the code."""
    declared = set(load_taxonomy().names())
    for labels in load_chain_config()[CLASS_LABELS_KEY].values():
        declared |= set(labels)
    faults = []
    for relative in (*SESSION_CODE, *ACCEPTANCE_CODE):
        if relative.startswith("spec_checks/"):
            # A gate builds documents and reads the labels it builds them with
            # from the configuration; what may not name one is the package the
            # pipeline runs.
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
    record("check_05b_no_vocabulary_literals", not faults, "; ".join(faults))


def check_05c_ascii_prose() -> None:
    """Negative 5c: the code and configuration this session touches are English."""
    faults = []
    files = [*SESSION_CODE, *ACCEPTANCE_CODE, "configs/title_typeset.json"]
    for relative in files:
        for number, line in enumerate(source_of(relative).splitlines(), start=1):
            if not line.isascii():
                offenders = [
                    unicodedata.name(char, hex(ord(char)))
                    for char in line
                    if not char.isascii()
                ]
                faults.append(f"{relative}:{number} {offenders[:3]}")
    record("check_05c_ascii_prose", not faults, "; ".join(faults[:5]))


def check_05d_the_gate_spends_no_credential() -> None:
    """Negative 5d: this gate constructs no engine and reads no credential."""
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
        if "translator" in name or "openai" in name
    ]
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith(suffix)
        ):
            faults.append(f"line {node.lineno} names a credential variable")
    record("check_05d_the_gate_spends_no_credential", not faults, "; ".join(faults))


def check_05e_registered() -> None:
    """Positive 5e: the plan is in the tree and the runner runs this gate."""
    faults = []
    if not (ROOT / "plans" / "PLAN_B9_2.md").is_file():
        faults.append("the plan is not in the tree")
    runner = source_of("spec_checks/run_all.py")
    if Path(__file__).name not in runner:
        faults.append("the runner does not name this gate")
    record("check_05e_registered", not faults, "; ".join(faults))


def check_05f_the_real_case_is_frozen() -> None:
    """Positive 5f: the real headline, recomputed from a committed excerpt.

    Session one read this out of a working directory when one happened to be on
    disk, which made the strongest assertion of the batch the one most likely to
    be absent. Session two froze the page's headings as they left the layout,
    and this reads that: the case the rule was built for is the case the rule
    catches -- one heading paragraph, two style runs saying the same thing in
    one font, deduplicated to one -- and what the pass recorded on the run the
    excerpt came from says the same.
    """
    faults = []
    fixture, sidecar = ROOT / FIXTURE, ROOT / FIXTURE_SIDECAR
    for path, relative in ((fixture, FIXTURE), (sidecar, FIXTURE_SIDECAR)):
        if not path.is_file():
            faults.append(f"{relative} is not in the tree")
    if faults:
        record("check_05f_the_real_case_is_frozen", False, "; ".join(faults))
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs = checkpoint_module.load_checkpoint(fixture)
    config = policy()
    found = {}
    for label, page_ in hitl.labeled_pages(docs):
        for index, paragraph in enumerate(page_.pdf_paragraph or ()):
            if not config.is_title(paragraph):
                faults.append("the excerpt carries a paragraph that is not a heading")
                continue
            runs = title_typeset.style_runs(
                title_typeset.laid_out_characters(paragraph)
            )
            kept, dropped = title_typeset.duplicate_runs(runs, config)
            if dropped:
                found[f"p{label}#{index}"] = (kept, dropped)
    if not found:
        faults.append("the frozen excerpt no longer carries a duplicate layer")
    with sidecar.open(encoding="utf-8") as f:
        recorded = json.load(f)
    written = {
        item["reference"]
        for item in recorded["duplicates"]
        if item["layer"] == title_typeset.LAYER_RUN
    }
    # An excerpt renumbers the headings it keeps, so what the sidecar calls a
    # heading and what this file calls it are different names for one paragraph.
    # The ledger carries the mapping and it is applied rather than assumed.
    mapping = evidence()["fixture"]["references"]
    named = {
        mapping[int(reference.split("#")[1])]
        for reference in found
        if int(reference.split("#")[1]) < len(mapping)
    }
    if written != named:
        faults.append(f"the sidecar records {sorted(written)}, this finds {sorted(named)}")
    for reference, (kept, dropped) in found.items():
        # The layer that stays says the whole headline once, which is the point
        # of dropping the other one.
        if len(kept) + len(dropped) <= len(kept):
            faults.append(f"{reference}: nothing was dropped")
        if any(not run.text.strip() for run in kept):
            faults.append(f"{reference}: an empty layer was kept")
    record("check_05f_the_real_case_is_frozen", not faults, "; ".join(faults))


# --- 07 the acceptance ---------------------------------------------------------


@functools.lru_cache(maxsize=1)
def evidence() -> dict:
    with (ROOT / EVIDENCE).open(encoding="utf-8") as f:
        return json.load(f)


def tracked(paths) -> list[str]:
    """Which of these the repository does not hold, which is what gets swept."""
    absent = []
    for relative in paths:
        code, listing = git_output(["ls-files", "--", relative])
        if not listing.strip():
            absent.append(relative)
        elif code != 0:
            absent.append(relative)
    return absent


def check_07a_the_arms_translated_one_document() -> None:
    """Positive 7a: one translation, two typographies, and the difference placed.

    The strongest thing the batch can say about itself, read against the arm
    that says what a run differs from itself by. Where the identical pair agrees
    on the document handed to the layout, the switch's pair has to agree on it
    too; and a page whose pixels moved has to be a page a heading was changed
    on, unless the identical pair moved it as well, in which case nothing here
    can attribute it and it is recorded as unattributed rather than as either.
    """
    faults = []
    arms = evidence()["arms"]
    if len(arms) != ACCEPTANCE_SAMPLES:
        faults.append(f"{len(arms)} sample(s), expected {ACCEPTANCE_SAMPLES}")
    reproducible = 0
    for item in arms:
        sample = item["sample"]
        for stage in ("il_translated", "typesetting"):
            if item[stage]["control_identical"] and not item[stage]["identical"]:
                faults.append(
                    f"{sample}: the {stage} checkpoint differs between the arms "
                    f"while the control is quiet, so the switch moved it"
                )
        if item["typesetting"]["control_identical"]:
            reproducible += 1
        if item["stray"]:
            faults.append(f"{sample}: {'; '.join(item['stray'])}")
        counts = set(item["pages"].values())
        if len(counts) != 1:
            faults.append(f"{sample}: the arms produced different page counts")
        if item["repair"]["attributable"]:
            faults.append(
                f"{sample}: the repair loop touched different paragraphs while "
                f"the control reproduced the first arm"
            )
        differing = [page for page in item["page_diff"] if page.get("differs")]
        if item["changed_pages"] and not differing:
            faults.append(f"{sample}: headings changed and no page differs")
    if not reproducible:
        faults.append("no sample reproduced, so nothing is attributable at all")
    record("check_07a_the_arms_translated_one_document", not faults, "; ".join(faults))


def check_07b_the_doubled_headline_is_drawn_once() -> None:
    """Positive 7b: two renderings became one, in the record and in the pixels."""
    faults = []
    ghost = evidence()["ghost"]
    if not ghost["duplicates"]:
        faults.append("the sidecar records no duplicate layer")
    if not ghost["layers"]:
        faults.append("no heading of that page was found to carry two layers")
    for reference, layer in ghost["layers"].items():
        # What survives is exactly half of what the layout laid out, which is
        # what "drawn twice, shown once" means at the level of the text.
        if layer["kept"] * 2 != layer["as_laid_out"]:
            faults.append(f"{reference}: what is kept is not half of what was there")
        if not layer["runs_dropped"]:
            faults.append(f"{reference}: nothing was dropped")
    ratio = ghost.get("extent_ratio")
    if ratio is None:
        faults.append("the headline band could not be read from the page")
    elif ratio > 0.75:
        faults.append(f"the headline still runs {ratio} of the way it ran")
    faults += ghost["faults"]
    cited = list(ghost["raster"].values())
    if len(cited) < 4:
        faults.append(f"only {len(cited)} raster(s) cited")
    missing = [path for path in cited if not (ROOT / path).is_file()]
    if missing:
        faults.append(f"cited but absent: {missing}")
    untracked = tracked(cited)
    if untracked:
        faults.append(f"cited but not committed: {untracked}")
    record("check_07b_the_doubled_headline_is_drawn_once", not faults, "; ".join(faults))


def check_07c_the_cover_headings_are_unwrapped_and_the_residue_is_named() -> None:
    """Positive 7c: both cover headings come off two lines, and what remains is named.

    The batch delivers the unwrapping and does not deliver containment against
    the page edge, which turned out to be a different mechanism -- the layout
    anchors a first line by the modal unit height, and the paragraph carrying
    this masthead also carries the credit line beside it. So this asserts what
    was delivered, holds the residue to being smaller than it was, and requires
    it to be on the record as an open defect rather than absent from it.
    """
    faults = []
    cover = evidence()["cover"]
    if not cover["wrapped_before"]:
        faults.append("no heading on that page was wrapped before the pass")
    if cover["still_wrapped"]:
        faults.append(f"still wrapped after the pass: {cover['still_wrapped']}")
    overhang = cover["overhang_points"]
    if overhang["on"] > overhang["off"]:
        faults.append(f"the overhang grew from {overhang['off']} to {overhang['on']}")
    if cover["outside_frame"]["on"] and not cover["open_defect"]:
        faults.append("ink is outside the frame and no open defect is recorded")
    if not cover["outside_frame"]["off"]:
        faults.append(
            "nothing is outside the frame with the switch down, so the case "
            "does not carry the defect it was written for"
        )
    faults += cover["faults"]
    cited = list(cover["raster"].values())
    missing = [path for path in cited if not (ROOT / path).is_file()]
    if missing:
        faults.append(f"cited but absent: {missing}")
    untracked = tracked(cited)
    if untracked:
        faults.append(f"cited but not committed: {untracked}")
    record(
        "check_07c_the_cover_headings_are_unwrapped_and_the_residue_is_named",
        not faults,
        "; ".join(faults),
    )


def check_07d_every_heading_is_on_one_line_or_raised() -> None:
    """Positive 7d: the ruled sample, heading by heading, and the ruling's terms."""
    faults = []
    ruled = evidence()["ruled"]
    if ruled["unaccounted"]:
        faults.append(f"unaccounted for: {ruled['unaccounted']}")
    if len(ruled["accounted"]) != ruled["titles"]:
        faults.append(
            f"{len(ruled['accounted'])} of {ruled['titles']} heading(s) accounted for"
        )
    if not ruled["titles"]:
        faults.append("the sample carries no heading, so the case is vacuous")
    if len(ruled["ruling_terms_added"]) != RULED_TERMS_ADDED:
        faults.append(
            f"the revision added {len(ruled['ruling_terms_added'])} term(s), "
            f"expected {RULED_TERMS_ADDED}"
        )
    if ruled["ruling_terms_missing"]:
        faults.append(f"never reached the glossary: {ruled['ruling_terms_missing']}")
    if len(ruled["ruling_terms_hits"]) != len(ruled["ruling_terms_added"]):
        faults.append("a ruled term has no hit record")
    faults += ruled["faults"]
    record("check_07d_every_heading_is_on_one_line_or_raised", not faults, "; ".join(faults))


def check_07e_the_floor_is_listed() -> None:
    """Positive 7e: every heading that reached the floor is on the list, with its scale."""
    faults = []
    report = evidence()
    listed = report["floor"]["escalations"]
    reached = sum(item["titles"]["floor_reached"] for item in report["arms"])
    if len(listed) != reached:
        faults.append(f"{len(listed)} listed, {reached} reached the floor")
    if report["floor"]["count"] != len(listed):
        faults.append("the count and the list disagree")
    for item in listed:
        if item["disposition"] != title_typeset.FLOOR_ESCALATE:
            faults.append(f"{item['reference']}: disposition {item['disposition']}")
        if not isinstance(item["required_scale"], int | float):
            faults.append(f"{item['reference']}: no scale asked for")
        if not item["sample"] or not item["reference"]:
            faults.append("an entry names neither a sample nor a heading")
    record("check_07e_the_floor_is_listed", not faults, "; ".join(faults))


def check_07f_a_doubled_heading_does_not_reach_the_metric() -> None:
    """Negative 7f: M3 measures the same with every doubled layer collapsed.

    The measurement is taken upstream of this pass, so if a doubled heading were
    inside it the defect would have been inflating a published number all along.
    The perturbation says it is not.
    """
    faults = []
    metric = evidence()["metric"]
    if metric["contaminated"]:
        faults.append(f"contaminated: {metric['contaminated']}")
    if not metric["samples"]:
        faults.append("no sample carries a doubled heading, so nothing was perturbed")
    for item in metric["samples"]:
        if item["summary_as_run"] != item["summary_collapsed"]:
            faults.append(f"{item['sample']}: the summaries differ")
        if item["doubled_paragraphs_inside_the_measurement"]:
            faults.append(
                f"{item['sample']}: a doubled heading is inside the measurement: "
                f"{item['doubled_paragraphs_inside_the_measurement']}"
            )
    record(
        "check_07f_a_doubled_heading_does_not_reach_the_metric", not faults, "; ".join(faults)
    )


def check_07g_the_policy_asks_no_question() -> None:
    """Positive 7g: the arm with the switch up asked the model nothing new.

    The pass runs long after the last request is built, so it cannot reach a
    prompt and every translation the second arm needs is one the first arm
    already paid for. What the second arm is still charged for is the repair
    loop's decision, which is issued with the cache bypassed by its own design;
    that is accounted for per sample, and a call beyond it would mean the switch
    had reached a prompt after all.
    """
    faults = []
    report = evidence()
    cost = report["cost"]
    if not cost["off"]["api_calls"]:
        faults.append("the first arm paid for nothing, so the cache proves nothing")
    for arm in ("on", "control"):
        if cost[arm]["api_calls"] >= cost["off"]["api_calls"]:
            faults.append(
                f"the {arm} arm spent {cost[arm]['api_calls']} against the first "
                f"arm's {cost['off']['api_calls']}, so nothing was reused"
            )
    # Every arm that runs the repair loop is charged for its decision whatever
    # the cache holds, so that is the floor a repeat arm cannot go below.
    for item in report["arms"]:
        floor = item["repair"]["on_live_decisions"]
        if item["api_calls"]["on"] < floor:
            faults.append(
                f"{item['sample']}: {item['api_calls']['on']} call(s) against "
                f"{floor} uncacheable decision(s)"
            )
    if report["faults"]:
        faults.append(f"the acceptance recorded: {report['faults']}")
    for relative in (EVIDENCE, ACCEPTANCE_REPORT, FIXTURE, FIXTURE_SIDECAR):
        if not (ROOT / relative).is_file():
            faults.append(f"{relative} is not in the tree")
    untracked = tracked((EVIDENCE, ACCEPTANCE_REPORT, FIXTURE, FIXTURE_SIDECAR))
    if untracked:
        faults.append(f"not committed: {untracked}")
    record("check_07g_the_policy_asks_no_question", not faults, "; ".join(faults))


# --- 06 the sweep -------------------------------------------------------------


def check_06_sweep() -> None:
    """Positive 6: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_06_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_06_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01a_erasure_is_omission,
        check_01b_no_upstream_flag_forbids_a_break,
        check_01c_the_indent_is_an_attribute_the_layout_reads,
        check_01d_backfill_precedes_the_layout_precedes_this_pass,
        check_02a_an_over_wide_heading_is_set_on_one_line,
        check_02b_below_the_floor_is_raised_not_squeezed,
        check_02c_two_paints_of_one_headline_become_one,
        check_02d_overlapping_heading_paragraphs_become_one,
        check_02e_a_chain_member_is_scaled_after_its_backfill,
        check_02f_a_heading_with_nothing_to_answer_for_is_left_alone,
        check_03a_the_switch_down_changes_nothing,
        check_03b_conservation,
        check_03c_the_sidecar_says_what_was_done,
        check_04a_every_parameter_is_bounded,
        check_04b_a_bad_configuration_is_refused,
        check_04c_the_heading_labels_are_declared_elsewhere,
        check_04d_the_ruling_revision_is_the_owners_and_only_theirs,
        check_05a_no_upstream_change,
        check_05b_no_vocabulary_literals,
        check_05c_ascii_prose,
        check_05d_the_gate_spends_no_credential,
        check_05e_registered,
        check_05f_the_real_case_is_frozen,
        check_07a_the_arms_translated_one_document,
        check_07b_the_doubled_headline_is_drawn_once,
        check_07c_the_cover_headings_are_unwrapped_and_the_residue_is_named,
        check_07d_every_heading_is_on_one_line_or_raised,
        check_07e_the_floor_is_listed,
        check_07f_a_doubled_heading_does_not_reach_the_metric,
        check_07g_the_policy_asks_no_question,
        check_06_sweep,
    ]
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(check.__name__, False, f"raised {exc!r}")
    print(f"\nspec_check_b9_2: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.write_stats("spec_check_b9_2")
        artifacts.print_stats("spec_check_b9_2")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
