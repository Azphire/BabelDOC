"""Gate script for batch B9.5 session one: collision detectors and containment.

Run from the repository root:

    python spec_checks/spec_check_b9_5.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: every document is built in this file and the one loop it
drives is wired to a stub engine declared here, which is what lets the mechanics
be asserted one property at a time.

What this session adds. Two detectors and two repair actions. ``out_of_page``
reports a paragraph whose laid out characters reach past the page frame, which
is the shape of the CERN report head defect: the typesetting stage anchors line
spacing on the modal size of a paragraph's units, so a display line sharing a
paragraph with a credit line is spaced for the credit and drawn off the top of
the sheet. ``text_text_collision`` reports two texts standing in one place, and
only where the layout as the source drew it did not already have them there,
because a magazine prints text over text on purpose and often. ``contain_in_page``
puts an out of page paragraph back inside its page by an affine map of the
characters it is laid out as -- slide first, shrink only where sliding cannot
fit it, escalate rather than shrink past the declared floor. ``resolve_collision``
writes nothing and exists to make the escalation list.

01 is the two configurations. Every number bounded, every new kind weighted and
answered by an action, every profile widened, the source stage validated against
the declared stage order, and the containment labels a subset of the display
vocabulary the heading pass already declares. The negative probes are what prove
the validators refuse rather than repair.

02 is out of page, one property at a time: the side, the noise floor, the safety
margin that is zero by default and reports ink approaching the trim when it is
not, the ink measured instead of the box, and a page with no frame noted rather
than reported.

03 is the collision detector, and the assertion this batch turns on is the
exemption: the same two boxes are a finding where the source had them apart and
are not where the source had them together. Beside it, the pair whose member has
no source counterpart is never a finding, a line split child finds its parent's
source box, and a run that kept no checkpoint does not run the detector at all.

04 is containment, three states and their refusals: slid, scaled, escalated,
and the paragraph left byte for byte identical wherever it was not contained.
Then the loop carrying it, with conservation and with the pixel evidence the
b8.4 rule requires of a repair.

05 is the default and the conservation: with the switch down nothing happens,
and with it up detection leaves the document byte for byte what it was.

06 is determinism. 07 is scope, registration and spend.

08 is the authorised maintenance this session carried out ahead of the batch:
the second ruling's digest pin, the three statements that batch b9.4 made stale,
the runner's output encoding declared on every hop, the replay boundary written
into the evaluation contract, and the corpus census that no longer writes over
evidence git carries.

Tiers: every assertion here is static. The documents are built in this file and
the loop is driven by a stub, so nothing in this gate needs a pipeline run.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import json
import math
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
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import title_typeset  # noqa: E402
from babeldoc.magazine.detectors import base as detector_base  # noqa: E402
from babeldoc.magazine.detectors import collision as collision_detector  # noqa: E402
from babeldoc.magazine.detectors import page_bounds  # noqa: E402
from babeldoc.magazine.detectors import source_geometry  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import collision as collision_action  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build:
# every document it asserts on is a stub it builds itself or evidence a
# batch froze, so it answers in seconds to a couple of minutes and runs on
# every batch.
GATE_SET = "fast"

# The batch runs over two sessions and each tags its own commit, so the delta
# this gate holds to scope is the union of both. A tag that does not exist yet
# is the session in progress, and that session's delta is the working tree.
BATCH_TAGS = ("batch-b9.5.1", "batch-b9.5")

PYTHON = sys.executable
RUNNER = ROOT / "spec_checks" / "run_all.py"

DETECTOR_CONFIG = ROOT / "configs" / "detectors.json"
REPAIR_CONFIG = ROOT / "configs" / "repair_actions.json"

SESSION_MODULES = (
    "babeldoc/magazine/detectors/base.py",
    "babeldoc/magazine/detectors/page_bounds.py",
    "babeldoc/magazine/detectors/collision.py",
    "babeldoc/magazine/detectors/source_geometry.py",
    "babeldoc/magazine/react/contain.py",
    "babeldoc/magazine/react/collision.py",
)

ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "spec_checks/",
    "examples/output/b9_5/",
    # The sweep ends by applying the output retention policy, which archives a
    # batch falling out of the keep window into this tree.
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "plans/PLAN_B9_5.md",
    "UPSTREAM_DIFF.md",
    # The three documents T9.5.0 authorises this session to touch, and nothing
    # else under their trees.
    "docs/eval/metric_contract.md",
    "docs/eval/gap_register.md",
    "reviews/README.md",
    "examples/output/run_all.b9_5_1.log",
    "examples/output/run_all.b9_5.log",
}

# Prefixes no session of this batch may touch. The review tree is the user's;
# the one file in it this session may correct is the prose that describes the
# format, which T9.5.0 names, and no ruling.
FORBIDDEN_PREFIXES = ("corpus/", "prompts/")
REVIEWS_ALLOWED = {"reviews/README.md"}

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

LANGUAGE = "zh"

# The ruling the corpus owner filed after b9.4, and the digest T9.5.0 pins it at.
FD_RULING = "reviews/FD-en-v2.decisions.json"
FD_RULING_DIGEST = (
    "8850413eca6e0f3fecd1e901841a447caff41e251053565432176015d94ac470"
)

# Every sample of the corpus, read from the register rather than listed here.
CORPUS_SAMPLES = {
    entry["file"].removesuffix(".pdf")
    for entry in json.loads(
        (ROOT / "corpus" / "manifest.json").read_text(encoding="utf-8")
    )["samples"]
}

# The acceptance session's own tree: the arms, the report every figure is in,
# and the fixture the geometry can be replayed from without a run.
ACCEPTANCE_DIR = ROOT / "examples" / "output" / "b9_5"
ACCEPTANCE_ARMS = ("off", "control", "on", "contain")
ACCEPTANCE_REPORT = ACCEPTANCE_DIR / "report.md"
ACCEPTANCE_EVIDENCE = ACCEPTANCE_DIR / "evidence.json"
FIXTURE_SAMPLE = "CERNCourier-en"
FIXTURE_DIR = ACCEPTANCE_DIR / "fixtures"
FIXTURE_ARCHIVE = FIXTURE_DIR / f"{FIXTURE_SAMPLE}.checkpoints.zip"
FIXTURE_CONTAINMENT = FIXTURE_DIR / f"{FIXTURE_SAMPLE}.containment.json"
FIXTURE_ISSUES = FIXTURE_DIR / f"{FIXTURE_SAMPLE}.issues.json"

PAGE_WIDTH = 600.0
PAGE_HEIGHT = 800.0

BODY_FONT = "body"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b9_5")
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b9_5_"))


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


def load_json(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, proc.stdout


def changed_paths() -> set[str]:
    """The batch's delta: each session's tag where it exists, the tree otherwise."""
    paths: set[str] = set()
    pending = False
    for tag in BATCH_TAGS:
        code, _ = git_output(["rev-parse", "--verify", f"{tag}^{{commit}}"])
        if code != 0:
            pending = True
            continue
        _, listing = git_output(["diff", "--name-only", f"{tag}^..{tag}"])
        paths |= {line.strip() for line in listing.splitlines() if line.strip()}
    if not pending:
        return paths
    _, listing = git_output(["diff", "--name-only", "HEAD"])
    paths |= {line.strip() for line in listing.splitlines() if line.strip()}
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


def style(font: str = BODY_FONT, size: float = 10.0):
    return il_version_1.PdfStyle(
        font_id=font, font_size=size, graphic_state=il_version_1.GraphicState()
    )


def character(text: str, x: float, y: float, width: float, size: float):
    box = il_version_1.Box(x=x, y=y, x2=x + width, y2=y + size)
    return il_version_1.PdfCharacter(
        char_unicode=text,
        box=box,
        visual_bbox=il_version_1.VisualBbox(box=copy.deepcopy(box)),
        pdf_style=style(BODY_FONT, size),
        advance=width / size,
        vertical=False,
        xobj_id=0,
    )


def laid_out(
    text: str,
    x: float,
    y: float,
    size: float = 10.0,
    width: float | None = None,
    label: str = "plain text",
    debug_id: str | None = None,
    box: tuple[float, float, float, float] | None = None,
):
    """One paragraph as the typesetting stage leaves it: one character each.

    The composition after the stage is one ``pdfCharacter`` per member, which is
    what the writer draws from and what the extension measures, so a fixture
    built any other way would be asserting about a document the pipeline does
    not produce.
    """
    step = size * 0.6 if width is None else width
    characters = [
        character(letter, x + index * step, y, step, size)
        for index, letter in enumerate(text)
    ]
    ink = (
        min(item.box.x for item in characters),
        min(item.box.y for item in characters),
        max(item.box.x2 for item in characters),
        max(item.box.y2 for item in characters),
    )
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*(ink if box is None else box)),
        pdf_style=style(BODY_FONT, size),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(pdf_character=item)
            for item in characters
        ],
        unicode=text,
        layout_label=label,
        debug_id=debug_id,
        vertical=False,
        xobj_id=-1,
    )


def boxed(text: str, box, label: str = "plain text", debug_id: str | None = None):
    """One paragraph carrying a box and text but no laid out character.

    What a hand built paragraph looks like, and the one shape whose extent has
    to fall back to the box.
    """
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*box),
        pdf_style=style(),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(unicode=text)
                )
            )
        ],
        unicode=text,
        layout_label=label,
        debug_id=debug_id,
        vertical=False,
        xobj_id=-1,
    )


def page(paragraphs, number: int = 0, framed: bool = True):
    frame = (
        il_version_1.Box(0.0, 0.0, PAGE_WIDTH, PAGE_HEIGHT) if framed else None
    )
    return il_version_1.Page(
        mediabox=None if frame is None else il_version_1.Mediabox(box=frame),
        cropbox=None if frame is None else il_version_1.Cropbox(box=copy.deepcopy(frame)),
        pdf_paragraph=list(paragraphs),
        page_number=number,
        unit="point",
    )


def document(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


def write_source(directory: Path, docs) -> Path:
    """One source layout checkpoint where the detectors look for it."""
    directory.mkdir(parents=True, exist_ok=True)
    stage = detectors.detector_config().source_geometry_stage
    path = directory / f"{checkpoint_module.checkpoint_stem(stage)}.xml"
    path.write_text(checkpoint_module.to_checkpoint_xml(docs), encoding="utf-8")
    return path


def detect(docs, working_dir: Path | None = None, config=None, **kwargs):
    config = config or detectors.detector_config()
    context = detectors.build_context(docs, config, LANGUAGE, working_dir, **kwargs)
    return detectors.run_detectors(context), context


def of_kind(issues, kind: str) -> list:
    return [issue for issue in issues if issue.kind == kind]


def raw_detectors() -> dict:
    return load_json(DETECTOR_CONFIG)


def raw_repairs() -> dict:
    return load_json(REPAIR_CONFIG)


def parse_detectors(raw: dict):
    return detector_base.parse_detector_config(
        raw,
        "probe.json",
        set(detectors.DETECTORS),
        {module.KIND for module in detectors.DETECTORS.values()},
    )


def parse_repairs(raw: dict):
    return react_config.parse_repair_config(
        raw, "probe.json", {module.KIND for module in detectors.DETECTORS.values()}
    )


def repair_config():
    return react_config.load_repair_config(
        None, tuple(sorted(module.KIND for module in detectors.DETECTORS.values()))
    )


def collision_bound() -> float:
    """The overlap the guard shares with the collision detector."""
    return detectors.detector_config().collision_min_iou


def contain_action():
    return repair_config().actions[contain.NAME]


# --- 01 the two configurations -------------------------------------------------


def check_01a_detector_bounds_are_declared() -> None:
    """Positive 1a: the new detector bounds are declared, weighted and selected."""
    raw = raw_detectors()
    config = parse_detectors(raw)
    faults = []
    for key, value in raw.items():
        if key.endswith("_allowed_range") or key == "description":
            continue
        if isinstance(value, int | float) and not isinstance(value, bool):
            if f"{key}_allowed_range" not in raw:
                faults.append(f"{key} declares no allowed range")
    for kind in (page_bounds.KIND, collision_detector.KIND):
        if kind not in config.severity:
            faults.append(f"{kind} carries no declared weight")
        if not config.progress_fields(kind):
            faults.append(f"{kind} declares no measure of how much of it is left")
    for profile, names in config.profile_detectors.items():
        for name in (page_bounds.NAME, collision_detector.NAME):
            if name not in names:
                faults.append(f"profile {profile} does not select {name}")
    if config.source_geometry_stage not in checkpoint_module.stage_names():
        faults.append("the source stage is not a declared pipeline stage")
    # The margin is zero by default: the crop box is the trim, and what stands
    # inside it however close to the edge is what the designer put there.
    if config.page_safety_margin_ratio != 0.0:
        faults.append(
            f"the declared safety margin is {config.page_safety_margin_ratio}, "
            f"not the page frame itself"
        )
    record("check_01a_detector_bounds_are_declared", not faults, "; ".join(faults))


def check_01b_detector_negative_probes() -> None:
    """Negative 1b: a malformed detector configuration is refused, not repaired."""
    faults = []

    def refuses(mutate, what: str) -> None:
        raw = raw_detectors()
        mutate(raw)
        try:
            parse_detectors(raw)
        except detector_base.DetectorError:
            return
        faults.append(f"accepted {what}")

    refuses(
        lambda raw: raw.__setitem__(
            detector_base.SOURCE_STAGE_KEY, "a_stage_nobody_checkpoints"
        ),
        "a source stage the pipeline does not checkpoint",
    )
    refuses(
        lambda raw: raw.pop(detector_base.SOURCE_STAGE_KEY),
        "a configuration naming no source stage at all",
    )
    refuses(
        lambda raw: raw.__setitem__("page_safety_margin_ratio", 5.0),
        "a safety margin outside its own range",
    )
    refuses(
        lambda raw: raw.pop("collision_source_min_iou_allowed_range"),
        "a source overlap bound with no range beside it",
    )
    refuses(
        lambda raw: raw["severity"].pop(page_bounds.KIND),
        "a kind a detector raises carrying no weight",
    )
    refuses(
        lambda raw: raw["profile_detectors"].__setitem__(
            "flow", ["a_detector_nobody_wrote"]
        ),
        "a profile selecting a detector that does not exist",
    )
    record("check_01b_detector_negative_probes", not faults, "; ".join(faults))


def check_01c_the_vocabulary_gained_two_actions() -> None:
    """Positive 1c: both actions are declared, answered for, and carried out."""
    config = repair_config()
    faults = []
    kinds = {module.KIND for module in detectors.DETECTORS.values()}
    for name in (contain.NAME, collision_action.NAME):
        action = config.actions.get(name)
        if action is None:
            faults.append(f"the vocabulary omits {name}")
            continue
        if not action.issue_kinds:
            faults.append(f"{name} answers for no issue kind")
        for kind in action.issue_kinds:
            if kind not in kinds:
                faults.append(f"{name} answers for {kind}, which no detector raises")
        if not action.conditions():
            faults.append(f"{name} states no condition at all")
        if name not in react_config.REQUIRED_APPLICABILITY:
            faults.append(f"{name} declares no rule the code can be held to")
    # Every declared action has a mechanism, and no mechanism answers for an
    # action nobody declared: the loop's table is the whole of the binding.
    loop = controller.RepairLoop.__new__(controller.RepairLoop)
    handlers = controller.RepairLoop._handlers(loop)  # noqa: SLF001 - the table itself
    missing = sorted(set(config.actions) - set(handlers))
    stray = sorted(set(handlers) - set(config.actions))
    if missing:
        faults.append(f"declared with no mechanism: {missing}")
    if stray:
        faults.append(f"mechanism for an action nobody declares: {stray}")
    # A kind is answered by at most one action, so a decision naming a finding
    # never has two mechanisms that could take it; the report only kinds are
    # answered by none, which is what report only means.
    for kind in sorted(kinds):
        answering = [
            name for name, action in config.actions.items() if action.answers_for(kind)
        ]
        if len(answering) > 1:
            faults.append(f"{kind} is answered by {answering}")
    for kind in (page_bounds.KIND, collision_detector.KIND):
        if not any(action.answers_for(kind) for action in config.actions.values()):
            faults.append(f"{kind} is answered by no action at all")
    record("check_01c_the_vocabulary_gained_two_actions", not faults, "; ".join(faults))


def check_01d_repair_negative_probes() -> None:
    """Negative 1d: a rule missing its own terms is refused for its own action."""
    faults = []

    def refuses(mutate, what: str) -> None:
        raw = raw_repairs()
        mutate(raw)
        try:
            parse_repairs(raw)
        except react_config.RepairConfigError:
            return
        faults.append(f"accepted {what}")

    key = react_config.ACTIONS_KEY
    refuses(
        lambda raw: raw[key][contain.NAME][react_config.APPLICABILITY_KEY].pop(
            react_config.CONTAIN_LABELS_KEY
        ),
        "a containment rule with no layout class set",
    )
    refuses(
        lambda raw: raw[key][contain.NAME].pop(contain.MIN_SCALE_KEY),
        "a containment action with no floor on how far it may shrink",
    )
    refuses(
        lambda raw: raw[key][contain.NAME].pop(f"{contain.MARGIN_KEY}_allowed_range"),
        "a containment margin with no range beside it",
    )
    refuses(
        lambda raw: raw[key][collision_action.NAME][
            react_config.APPLICABILITY_KEY
        ].pop(react_config.MIN_COLLISION_COVERAGE_KEY),
        "a collision rule with no overlap bound",
    )
    refuses(
        lambda raw: raw[key].__setitem__(
            "an_action_nobody_implemented", raw[key][contain.NAME]
        ),
        "an action no code declares a rule for",
    )
    refuses(
        lambda raw: raw[key][contain.NAME][react_config.APPLICABILITY_KEY][
            react_config.STATEMENTS_KEY
        ].pop(react_config.MIN_OVERFLOW_KEY),
        "a rule term the request cannot state",
    )
    record("check_01d_repair_negative_probes", not faults, "; ".join(faults))


def check_01e_the_action_is_stricter_than_the_detector() -> None:
    """Positive 1e: containment acts on less than detection reports.

    Two directions. The layout classes it will move are a subset of the display
    vocabulary the heading pass already declares, so this action introduces no
    second opinion about what a heading is. And the reach it acts at is at or
    above the reach the detector reports at, so a finding made at the edge of
    the detector's own noise floor never moves a heading.
    """
    action = contain_action()
    detector = detectors.detector_config()
    faults = []
    labels = set(action.applicability[react_config.CONTAIN_LABELS_KEY])
    display = set(title_typeset.load_title_config().labels)
    if not labels:
        faults.append("the containment rule names no layout class")
    if labels - display:
        faults.append(f"classes outside the display vocabulary: {sorted(labels - display)}")
    bound = float(action.applicability[react_config.MIN_OVERFLOW_KEY])
    if bound < detector.out_of_page_min_overflow_ratio:
        faults.append(
            f"the action acts at {bound}, below the "
            f"{detector.out_of_page_min_overflow_ratio} the detector reports at"
        )
    if not 0.0 < contain.min_scale(action) <= 1.0:
        faults.append(f"the shrink floor is {contain.min_scale(action)}")
    if not 0.0 <= contain.margin_ratio(action) < 0.5:
        faults.append(f"the landing margin is {contain.margin_ratio(action)}")
    # The collision action's own bound is not below the detector's: an action
    # acting at less overlap than the detector reports at would move a paragraph
    # on a finding made at the edge of the detector's own noise floor. B10.2
    # gave this action a mechanism, and what is asserted here is the strictness
    # this check is named for -- a claim about the rule, not about the
    # mechanism, which is why it survived the action gaining one.
    collision_rule = repair_config().actions[collision_action.NAME]
    action_coverage = collision_action.applicability(collision_rule)
    if action_coverage < detector.collision_min_coverage:
        faults.append(
            f"the collision action acts at coverage {action_coverage}, below the "
            f"{detector.collision_min_coverage} the detector reports at"
        )
    record(
        "check_01e_the_action_is_stricter_than_the_detector", not faults, "; ".join(faults)
    )


# --- 02 out of page ------------------------------------------------------------


def check_02a_ink_past_the_frame_is_reported() -> None:
    """Positive 2a: a paragraph drawn off the top is reported, and one inside is not."""
    docs = document(
        [
            page(
                [
                    laid_out("inside the page", 100.0, 700.0, debug_id="in"),
                    laid_out("over the top", 100.0, 780.0, size=50.0, debug_id="out"),
                ]
            )
        ]
    )
    issues = of_kind(detect(docs)[0], page_bounds.KIND)
    faults = []
    if len(issues) != 1:
        faults.append(f"{len(issues)} finding(s), expected exactly one")
    else:
        evidence = issues[0].evidence
        if evidence["overflow_side"] != "top":
            faults.append(f"reported the {evidence['overflow_side']} side")
        # The characters reach 780 + 50 = 830 on a page 800 high.
        if abs(evidence["overflow_max"] - 30.0) > 1e-6:
            faults.append(f"overflow_max is {evidence['overflow_max']}, expected 30")
        if abs(evidence["overflow_ratio"] - 30.0 / PAGE_HEIGHT) > 1e-6:
            faults.append(f"overflow_ratio is {evidence['overflow_ratio']}")
        if evidence["frame_source"] != "cropbox":
            faults.append(f"the frame came from {evidence['frame_source']}")
        if issues[0].paragraph_refs != ("p1#1",):
            faults.append(f"named {issues[0].paragraph_refs}")
    record("check_02a_ink_past_the_frame_is_reported", not faults, "; ".join(faults))


def check_02b_the_noise_floor_holds() -> None:
    """Boundary 2b: a rounding past the frame is not a finding and a reach is."""
    floor = detectors.detector_config().out_of_page_min_overflow_ratio
    faults = []
    for overflow, expected in (
        (floor * PAGE_HEIGHT * 0.5, False),
        (floor * PAGE_HEIGHT * 2.0, True),
    ):
        # A ten point line whose top lands ``overflow`` past the page.
        y = PAGE_HEIGHT + overflow - 10.0
        docs = document([page([laid_out("edge", 100.0, y, debug_id="edge")])])
        found = of_kind(detect(docs)[0], page_bounds.KIND)
        if bool(found) != expected:
            faults.append(
                f"{overflow:.3f} points past the frame reported={bool(found)}, "
                f"expected {expected}"
            )
    record("check_02b_the_noise_floor_holds", not faults, "; ".join(faults))


def check_02c_the_safety_margin_reports_ink_at_the_trim() -> None:
    """Positive 2c: ink inside the frame is a finding only under a raised margin.

    The margin is what makes "close to the trim" reportable at all, and it is
    zero by default. Both halves are asserted on one document, so the difference
    is the margin and nothing else.
    """
    raw = raw_detectors()
    default = parse_detectors(raw)
    raised = dict(raw)
    raised["page_safety_margin_ratio"] = 0.05
    raised = parse_detectors(raised)
    # A line ending five points inside the top of the page.
    docs = document([page([laid_out("at the trim", 100.0, 785.0, debug_id="trim")])])
    faults = []
    if of_kind(detect(docs, config=default)[0], page_bounds.KIND):
        faults.append("ink inside the frame was reported at the declared margin")
    found = of_kind(detect(docs, config=raised)[0], page_bounds.KIND)
    if len(found) != 1:
        faults.append(f"a raised margin reported {len(found)} finding(s)")
    else:
        evidence = found[0].evidence
        safe = evidence["safe_box"]
        if abs(safe[3] - (PAGE_HEIGHT * 0.95)) > 1e-6:
            faults.append(f"the safe box top is {safe[3]}")
        if evidence["margin_ratio"] != 0.05:
            faults.append("the finding does not carry the margin it was made under")
    record(
        "check_02c_the_safety_margin_reports_ink_at_the_trim", not faults, "; ".join(faults)
    )


def check_02d_the_ink_is_measured_not_the_box() -> None:
    """Positive 2d: a paragraph whose box is inside and whose ink is not is reported.

    This is the defect's own shape. The stage put the box where the paragraph
    belonged and drew the display line outside it, so a detector reading the box
    would report nothing about the page that lost its heading.
    """
    inside_box = (100.0, 700.0, 400.0, 730.0)
    docs = document(
        [
            page(
                [
                    laid_out(
                        "heading",
                        100.0,
                        780.0,
                        size=50.0,
                        box=inside_box,
                        debug_id="mast",
                    )
                ]
            )
        ]
    )
    issues = of_kind(detect(docs)[0], page_bounds.KIND)
    faults = []
    if len(issues) != 1:
        faults.append(f"{len(issues)} finding(s) for ink outside a box that is inside")
    else:
        evidence = issues[0].evidence
        if evidence["box_source"] != detector_base.BOX_FROM_CHARACTERS:
            faults.append(f"measured the {evidence['box_source']}")
    # And the fallback is asserted too: a paragraph with no laid out character
    # is measured by its box, and says so.
    plain = document([page([boxed("hand built", (100.0, 780.0, 400.0, 830.0))])])
    fallback = of_kind(detect(plain)[0], page_bounds.KIND)
    if len(fallback) != 1:
        faults.append(f"{len(fallback)} finding(s) for a paragraph with no characters")
    elif fallback[0].evidence["box_source"] != detector_base.BOX_FROM_PARAGRAPH:
        faults.append("a paragraph with no characters was not measured by its box")
    record("check_02d_the_ink_is_measured_not_the_box", not faults, "; ".join(faults))


def check_02e_a_page_with_no_frame_is_noted() -> None:
    """Negative 2e: a page carrying no frame is recorded, not reported against."""
    docs = document(
        [page([laid_out("nowhere", 100.0, 780.0, size=50.0)], framed=False)]
    )
    issues, context = detect(docs)
    faults = []
    if of_kind(issues, page_bounds.KIND):
        faults.append("a page with no frame produced a containment finding")
    if not any(note.startswith(page_bounds.NAME) for note in context.notes):
        faults.append(f"nothing was noted; notes are {context.notes}")
    record("check_02e_a_page_with_no_frame_is_noted", not faults, "; ".join(faults))


# --- 03 the collision detector and its exemption -------------------------------


def collision_pair(first_x: float, second_x: float, ids=("a", "b")):
    """Two paragraphs of one page, the second placed against the first."""
    return page(
        [
            laid_out("first block of text", first_x, 400.0, size=20.0, debug_id=ids[0]),
            laid_out("second block of text", second_x, 400.0, size=20.0, debug_id=ids[1]),
        ]
    )


def check_03a_an_induced_collision_is_reported() -> None:
    """Positive 3a: two texts the source had apart and the page has together."""
    directory = _tmp_root / "collision_induced"
    write_source(directory, document([collision_pair(100.0, 400.0)]))
    docs = document([collision_pair(100.0, 100.0)])
    issues = of_kind(detect(docs, directory)[0], collision_detector.KIND)
    faults = []
    if len(issues) != 1:
        faults.append(f"{len(issues)} finding(s), expected exactly one")
    else:
        issue = issues[0]
        if len(issue.paragraph_refs) != 2:
            faults.append(f"the finding names {issue.paragraph_refs}")
        if issue.evidence["iou"] < issue.evidence["min_iou"]:
            faults.append("the finding was made below its own bound")
        if issue.evidence["source_iou"] != 0.0:
            faults.append(
                f"the source overlap is {issue.evidence['source_iou']}, expected none"
            )
        if issue.evidence["source_stage"] != (
            detectors.detector_config().source_geometry_stage
        ):
            faults.append("the finding does not name the stage it compared against")
    record("check_03a_an_induced_collision_is_reported", not faults, "; ".join(faults))


def check_03b_a_source_design_overlay_is_exempt() -> None:
    """Negative 3b: the same finished page, with the source already overlapping.

    The one assertion this detector exists for. Nothing about the finished page
    separates a defect from a design; the source layout does, and the same two
    boxes have to come out a finding under one source and no finding under the
    other.
    """
    directory = _tmp_root / "collision_design"
    write_source(directory, document([collision_pair(100.0, 100.0)]))
    docs = document([collision_pair(100.0, 100.0)])
    issues, context = detect(docs, directory)
    faults = []
    if of_kind(issues, collision_detector.KIND):
        faults.append("an overlap the source already had was reported")
    note = collision_detector.SKIPPED_SOURCE_OVERLAP
    if not any(note in item for item in context.notes):
        faults.append(f"the exemption was not counted; notes are {context.notes}")
    record("check_03b_a_source_design_overlay_is_exempt", not faults, "; ".join(faults))


def check_03c_an_overlap_below_the_bound_is_not_a_finding() -> None:
    """Boundary 3c: the pair has to share the declared share of its own area."""
    config = detectors.detector_config()
    directory = _tmp_root / "collision_bound"
    write_source(directory, document([collision_pair(100.0, 400.0)]))
    faults = []
    # Two 20 point lines of the same width, offset so the shared area is a
    # known share of the union, either side of the bound.
    for offset, expected in ((10.0, True), (200.0, False)):
        docs = document([collision_pair(100.0, 100.0 + offset)])
        found = of_kind(detect(docs, directory)[0], collision_detector.KIND)
        measured = detector_base.intersection_over_union(
            detector_base.rendered_box(docs.page[0].pdf_paragraph[0])[0],
            detector_base.rendered_box(docs.page[0].pdf_paragraph[1])[0],
        )
        if (measured >= config.collision_min_iou) != expected:
            faults.append(f"the fixture at offset {offset} measures {measured:.3f}")
        if bool(found) != expected:
            faults.append(f"offset {offset}: reported={bool(found)}")
    record(
        "check_03c_an_overlap_below_the_bound_is_not_a_finding", not faults, "; ".join(faults)
    )


def check_03d_a_member_with_no_source_is_never_a_finding() -> None:
    """Negative 3d: a paragraph the source never drew is left out and counted.

    The watermark the typesetting stage appends is exactly this: it carries no
    identity, it spans most of the page, and treating "the source did not draw
    this" as "the source had no overlap here" would report it against every
    paragraph it covers.
    """
    directory = _tmp_root / "collision_orphan"
    write_source(directory, document([collision_pair(100.0, 400.0)]))
    finished = collision_pair(100.0, 400.0)
    finished.pdf_paragraph.append(
        laid_out("appended by a later stage", 100.0, 400.0, size=20.0, debug_id=None)
    )
    issues, context = detect(document([finished]), directory)
    faults = []
    if of_kind(issues, collision_detector.KIND):
        faults.append("a pair with no source counterpart was reported")
    if not any(
        collision_detector.SKIPPED_NO_SOURCE in item for item in context.notes
    ):
        faults.append(f"the skip was not counted; notes are {context.notes}")
    record(
        "check_03d_a_member_with_no_source_is_never_a_finding", not faults, "; ".join(faults)
    )


def check_03e_a_split_line_finds_its_parent() -> None:
    """Positive 3e: a line split child is compared against the paragraph it came from."""
    directory = _tmp_root / "collision_split"
    write_source(directory, document([collision_pair(100.0, 400.0)]))
    separator = source_geometry.LINE_ID_SEPARATOR
    docs = document(
        [collision_pair(100.0, 100.0, ids=(f"a{separator}0", f"b{separator}2"))]
    )
    issues = of_kind(detect(docs, directory)[0], collision_detector.KIND)
    faults = []
    if len(issues) != 1:
        faults.append(f"{len(issues)} finding(s) for two split lines")
    elif issues[0].evidence["source_iou"] != 0.0:
        faults.append("the children did not resolve to their parents' boxes")
    if source_geometry.root_id(f"a{separator}7") != "a":
        faults.append("the identity of a split line does not cut back to its parent")
    record("check_03e_a_split_line_finds_its_parent", not faults, "; ".join(faults))


def check_03f_without_the_source_the_detector_does_not_run() -> None:
    """Negative 3f: no checkpoint, no claim, and the sidecar says which."""
    docs = document([collision_pair(100.0, 100.0)])
    issues, context = detect(docs, _tmp_root / "collision_absent")
    faults = []
    if of_kind(issues, collision_detector.KIND):
        faults.append("a collision was claimed with nothing to compare against")
    if not any(note.startswith(collision_detector.NAME) for note in context.notes):
        faults.append(f"the skip was not recorded; notes are {context.notes}")
    if context.source_geometry is not None:
        faults.append("a source layout was loaded from a directory holding none")
    # And the sidecar carries what it did compare against where there is one.
    directory = _tmp_root / "collision_recorded"
    write_source(directory, document([collision_pair(100.0, 400.0)]))
    issues, context = detect(docs, directory)
    record_ = detectors.as_record(context, issues)
    if not record_.get("source_geometry"):
        faults.append("the sidecar does not say what the comparison read")
    elif record_["source_geometry"]["paragraphs"] != 2:
        faults.append(f"the sidecar reports {record_['source_geometry']}")
    record(
        "check_03f_without_the_source_the_detector_does_not_run", not faults, "; ".join(faults)
    )


# --- 04 containment ------------------------------------------------------------


# The fixture 4b is measured on: a heading whose height is what will not fit,
# set on a narrow measure so that the width never becomes the binding axis.
TALL_TEXT = "TALL"
TALL_X = 60.0
TALL_Y = 100.0
TALL_SIZE = 900.0
TALL_WIDTH = 100.0


def contain_fixture(
    text: str,
    x: float,
    y: float,
    size: float,
    label: str = "title",
    width: float | None = None,
):
    """One display paragraph on one page, and the finding made about it."""
    paragraph = laid_out(
        text, x, y, size=size, width=width, label=label, debug_id="head"
    )
    docs = document([page([paragraph])])
    issues = of_kind(detect(docs)[0], page_bounds.KIND)
    return docs, paragraph, (issues[0] if issues else None)


def candidate_for(docs, issue):
    _found, context = detect(docs)
    return actions.resolve(issue, {view.label: view for view in context.pages})


def offsets(paragraph) -> list[tuple[float, float]]:
    """Where each character sits relative to the first, which a slide preserves."""
    boxes = [item.box for item in contain_characters(paragraph)]
    first = boxes[0]
    return [(box.x - first.x, box.y - first.y) for box in boxes]


def contain_characters(paragraph):
    from babeldoc.magazine.line_split import paragraph_characters

    return paragraph_characters(paragraph)


def check_04a_a_heading_that_fits_is_slid() -> None:
    """Positive 4a: sliding is preferred, and it changes nothing but position."""
    docs, paragraph, issue = contain_fixture("HEADLINE", 100.0, 780.0, 30.0)
    action = contain_action()
    faults = []
    if issue is None:
        record("check_04a_a_heading_that_fits_is_slid", False, "nothing was detected")
        return
    before = offsets(paragraph)
    sizes = [item.pdf_style.font_size for item in contain_characters(paragraph)]
    candidate = candidate_for(docs, issue)
    outcome = contain.apply_one(candidate, action, collision_bound())
    if not outcome.accepted:
        faults.append(f"refused with {outcome.reason}")
    geometry = outcome.geometry
    if geometry.get("state") != contain.STATE_TRANSLATED:
        faults.append(f"the state is {geometry.get('state')}")
    if geometry.get("scale") != 1.0:
        faults.append(f"a heading that fits was scaled by {geometry.get('scale')}")
    if offsets(paragraph) != before:
        faults.append("sliding moved the characters relative to each other")
    if [item.pdf_style.font_size for item in contain_characters(paragraph)] != sizes:
        faults.append("sliding changed the size the characters are set in")
    after = contain.ink_box(paragraph)
    safe = geometry["safe_box"]
    if not (after[1] >= safe[1] and after[3] <= safe[3]):
        faults.append(f"the ink landed at {after}, outside {safe}")
    if geometry["shift"][0] != 0.0:
        faults.append("a heading overflowing the top was moved sideways")
    record("check_04a_a_heading_that_fits_is_slid", not faults, "; ".join(faults))


def check_04b_a_heading_too_large_is_scaled() -> None:
    """Positive 4b: what sliding cannot fit is shrunk, and only as far as it must."""
    docs, paragraph, issue = contain_fixture(
        TALL_TEXT, TALL_X, TALL_Y, TALL_SIZE, width=TALL_WIDTH
    )
    action = contain_action()
    faults = []
    if issue is None:
        record("check_04b_a_heading_too_large_is_scaled", False, "nothing was detected")
        return
    before = contain.ink_box(paragraph)
    sizes = [item.pdf_style.font_size for item in contain_characters(paragraph)]
    candidate = candidate_for(docs, issue)
    outcome = contain.apply_one(candidate, action, collision_bound())
    geometry = outcome.geometry
    if not outcome.accepted:
        faults.append(f"refused with {outcome.reason}")
    if geometry.get("state") != contain.STATE_SCALED:
        faults.append(f"the state is {geometry.get('state')}")
    scale = geometry.get("scale", 0.0)
    safe = geometry["safe_box"]
    expected = min(
        1.0,
        (safe[2] - safe[0]) / (before[2] - before[0]),
        (safe[3] - safe[1]) / (before[3] - before[1]),
    )
    if abs(scale - expected) > 1e-6:
        faults.append(f"scaled by {scale}, the largest that fits is {expected}")
    # Against the scale derived here rather than the one the record rounds for a
    # reader, so what is compared is the map the mechanism actually applied.
    after_sizes = [item.pdf_style.font_size for item in contain_characters(paragraph)]
    if any(
        not math.isclose(new, old * expected, rel_tol=1e-9, abs_tol=1e-9)
        for new, old in zip(after_sizes, sizes, strict=True)
    ):
        faults.append("the characters were moved without being resized with the map")
    after = contain.ink_box(paragraph)
    if max(detector_base.overflow(after, tuple(safe)).values()) > 1e-6:
        faults.append(f"the ink landed at {after}, outside {safe}")
    # Nothing is left describing where the paragraph used to be or how large it
    # used to be set: the visual box beside each character moved with it, and so
    # did the paragraph's own style.
    for item in contain_characters(paragraph):
        visual = item.visual_bbox.box
        if (visual.x, visual.y, visual.x2, visual.y2) != (
            item.box.x,
            item.box.y,
            item.box.x2,
            item.box.y2,
        ):
            faults.append("a visual bounding box was left where the character was")
            break
    if not math.isclose(
        paragraph.pdf_style.font_size, TALL_SIZE * expected, rel_tol=1e-9
    ):
        faults.append("the paragraph still declares the size it was set at")
    # The line structure survives: every offset scaled by the same factor.
    if any(
        not math.isclose(new[0], old[0] * expected, rel_tol=1e-9, abs_tol=1e-9)
        or not math.isclose(new[1], old[1] * expected, rel_tol=1e-9, abs_tol=1e-9)
        for new, old in zip(offsets(paragraph), offsets_of(docs), strict=True)
    ):
        faults.append("the relative geometry of the characters did not survive")
    record("check_04b_a_heading_too_large_is_scaled", not faults, "; ".join(faults))


def offsets_of(_docs) -> list[tuple[float, float]]:
    """The offsets of the fixture as it was built, rebuilt rather than kept.

    Rebuilding it is what makes the comparison in 4b a comparison against the
    document the fixture describes rather than against a list the same code
    already transformed.
    """
    return offsets(
        laid_out(TALL_TEXT, TALL_X, TALL_Y, size=TALL_SIZE, width=TALL_WIDTH)
    )


def check_04c_a_heading_past_the_floor_is_escalated() -> None:
    """Negative 4c: past the floor nothing is applied and the figure is reported."""
    action = contain_action()
    floor = contain.min_scale(action)
    docs, paragraph, issue = contain_fixture(
        "HUGE", 60.0, 100.0, 4000.0, width=100.0
    )
    faults = []
    if issue is None:
        record(
            "check_04c_a_heading_past_the_floor_is_escalated", False, "nothing detected"
        )
        return
    before = copy.deepcopy(paragraph)
    candidate = candidate_for(docs, issue)
    outcome = contain.apply_one(candidate, action, collision_bound())
    if outcome.accepted or outcome.changed:
        faults.append("a heading past the floor was contained anyway")
    if outcome.reason != contain.REASON_FLOOR:
        faults.append(f"refused with {outcome.reason}")
    scale = outcome.geometry.get("scale")
    if scale is None or scale >= floor:
        faults.append(f"the escalation reports a scale of {scale}, floor {floor}")
    if checkpoint_module.to_checkpoint_xml(
        document([page([before])])
    ) != checkpoint_module.to_checkpoint_xml(document([page([paragraph])])):
        faults.append("the escalated paragraph was not left exactly as it was")
    record(
        "check_04c_a_heading_past_the_floor_is_escalated", not faults, "; ".join(faults)
    )


def check_04d_containment_refuses_what_it_may_not_move() -> None:
    """Negative 4d: the rule refuses by class, by reach, and by having no ink."""
    action = contain_action()
    faults = []

    docs, _paragraph, issue = contain_fixture(
        "running text off the page", 100.0, 780.0, 30.0, label="plain text"
    )
    if issue is None:
        faults.append("the running text fixture produced no finding to refuse")
    else:
        verdict = contain.admits(
            issue, candidate_for(docs, issue), action, detect(docs)[1]
        )
        if verdict != contain.REASON_LABEL:
            faults.append(f"a paragraph of running text was admitted with {verdict}")

    # A reach the detector reports and the action's own bound does not.
    bound = float(action.applicability[react_config.MIN_OVERFLOW_KEY])
    overflow = bound * PAGE_HEIGHT * 0.5
    docs, _paragraph, issue = contain_fixture(
        "just over", 100.0, PAGE_HEIGHT + overflow - 30.0, 30.0
    )
    if issue is None:
        faults.append("the shallow fixture produced no finding at all")
    else:
        verdict = contain.admits(
            issue, candidate_for(docs, issue), action, detect(docs)[1]
        )
        if verdict != contain.REASON_OVERFLOW:
            faults.append(f"a shallow reach was admitted with {verdict}")

    # And a paragraph with nothing laid out has nothing this action can move.
    plain = document(
        [page([boxed("hand built", (100.0, 780.0, 400.0, 900.0), label="title")])]
    )
    found = of_kind(detect(plain)[0], page_bounds.KIND)
    if not found:
        faults.append("the box-only fixture produced no finding")
    else:
        verdict = contain.admits(
            found[0], candidate_for(plain, found[0]), action, detect(plain)[1]
        )
        if verdict != contain.REASON_NO_INK:
            faults.append(f"a paragraph with no ink was admitted with {verdict}")
    record(
        "check_04d_containment_refuses_what_it_may_not_move", not faults, "; ".join(faults)
    )


class LayoutModel:
    stage_name = "stub"

    def predict(self, *args, **kwargs):
        return []


class Engine:
    """A stub model: one reply per request, and a record of what was asked."""

    name = "stub"

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.requests: list[str] = []

    def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
        self.requests.append(text)
        return self.decisions.pop(0) if self.decisions else "{}"


class NoCache:
    def get(self, key):
        return None

    def set(self, key, value):
        return None


def decision_reply(ids, action: str, parameters=None, reason="because"):
    return json.dumps(
        {
            "action": action,
            "issue_ids": list(ids),
            "parameters": parameters if parameters is not None else {},
            "reason": reason,
        }
    )


def build_loop(directory: Path, docs, engine, source=None):
    """One loop wired to a stub engine, with the source layout it should read.

    The configuration puts its working directory under the input file's own
    stem, so where the loop looks for the source checkpoint is not the directory
    named here; the source is written after the configuration has decided.
    """
    directory.mkdir(parents=True, exist_ok=True)
    config = TranslationConfig(
        translator=engine,
        input_file=str(ROOT / "examples" / "input" / "Courier-en.pdf"),
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
    if source is not None:
        write_source(Path(config.working_dir), source)
    loop = controller.RepairLoop(config, docs)
    loop.decision_client = decide.CachedDecisionClient(
        loop.repair_config,
        transport=decide.EngineTransport(engine),
        cache=NoCache(),
        working_dir=loop.working_dir,
    )
    return loop


def offered_ids(text: str) -> list[str]:
    return [
        line.split('"')[1]
        for line in text.splitlines()
        if line.strip().startswith("- id:")
    ]


def check_04e_the_loop_carries_containment() -> None:
    """Positive 4e: the loop applies it, conserves the document and shows the pixels."""
    docs = document(
        [
            page(
                [
                    laid_out("HEADLINE", 100.0, 780.0, size=30.0, label="title",
                             debug_id="head"),
                    laid_out("a paragraph nobody touched", 100.0, 200.0,
                             debug_id="body"),
                ]
            )
        ]
    )

    class Decider(Engine):
        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            self.requests.append(text)
            return decision_reply(offered_ids(text), contain.NAME)

    loop = build_loop(_tmp_root / "loop_contain", docs, Decider([]))
    loop.run()
    report = load_json(loop.working_dir / controller.REPORT_NAME)
    faults = []
    if report["applications"] != 1:
        faults.append(f"{report['applications']} paragraph(s) contained, expected 1")
    if report["conservation"]["verdict"] != controller.CONSERVED:
        faults.append(f"conservation: {report['conservation']['verdict']}")
    if report["conservation"]["changed_outside_touched"]:
        faults.append(
            f"changed outside the repaired set: "
            f"{report['conservation']['changed_outside_touched']}"
        )
    executed = [
        row
        for iteration in report["iterations"]
        for row in iteration.get("executed", ())
    ]
    accepted = [row for row in executed if row["accepted"]]
    if len(accepted) != 1:
        faults.append(f"{len(accepted)} accepted application(s)")
    else:
        geometry = accepted[0]["geometry"]
        for key in ("box_before", "box_after", "safe_box", "scale", "shift", "state"):
            if key not in geometry:
                faults.append(f"the application record omits {key}")
        if geometry.get("box_before") == geometry.get("box_after"):
            faults.append("the record shows a repair that moved nothing")
        if "worst_overlap_after" not in geometry:
            faults.append("the record does not say what it now stands on")
    record("check_04e_the_loop_carries_containment", not faults, "; ".join(faults))


def check_04f_the_collision_action_refuses_a_pair_of_equals() -> None:
    """Negative 4f: a decision naming a collision escalates and touches nothing.

    The fixture is two blocks of one size standing in one place. When this was
    written the action refused every collision, and the check read as an
    assertion that it did. B10.2 gave it a mechanism, and this fixture is the
    case that mechanism still refuses: moving either of two paragraphs of
    comparable size is exactly as wrong as moving the other, so there is no
    smaller one to move and the finding is escalated. What the check asserts is
    therefore unchanged -- nothing is written, nothing is touched, and the
    refusal reaches the escalation record -- and only the reason it carries has
    moved, from "this action writes nothing" to "these two are equals".
    """
    directory = _tmp_root / "loop_collision"
    docs = document([collision_pair(100.0, 100.0)])
    before = checkpoint_module.to_checkpoint_xml(docs)

    class Decider(Engine):
        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            self.requests.append(text)
            return decision_reply(offered_ids(text), collision_action.NAME)

    loop = build_loop(
        directory, docs, Decider([]), source=document([collision_pair(100.0, 400.0)])
    )
    loop.run()
    report = load_json(loop.working_dir / controller.REPORT_NAME)
    faults = []
    if loop.source_layout is None:
        faults.append("the loop did not load the source layout it was given")
    if report["applications"] != 0:
        faults.append(f"{report['applications']} application(s) on a pair of equals")
    if checkpoint_module.to_checkpoint_xml(docs) != before:
        faults.append("the document changed under a refused finding")
    reasons = {
        row["reason"]
        for iteration in report["iterations"]
        for row in iteration.get("applicability", ())
    }
    if collision_action.REASON_AREA not in reasons:
        faults.append(f"no finding was escalated; reasons were {sorted(reasons)}")
    if report["stopped_because"] != controller.STOP_NOTHING_APPLICABLE:
        faults.append(f"stopped because {report['stopped_because']}")
    record(
        "check_04f_the_collision_action_refuses_a_pair_of_equals",
        not faults,
        "; ".join(faults),
    )


# The fixture the guard is measured on: a display line hanging off the head of
# the page, and the two neighbours it would meet on the way back in. The first
# stands where the slide would land the ink and nowhere near where the ink is
# now, so sliding induces an overlap and shrinking in place does not. The second
# stands inside what shrinking in place would leave, and is too small a share of
# the ink where it is now to be an overlap with it, so it induces on the
# fallback alone. A fixture carrying the first is contained by the fallback; one
# carrying both is contained by neither and is escalated.
GUARD_TEXT = "HEAD"
GUARD_X = 100.0
GUARD_Y = 700.0
GUARD_SIZE = 120.0
GUARD_WIDTH = 50.0
GUARD_UNDER_THE_SLIDE = (100.0, 660.0, 300.0, 705.0)
GUARD_INSIDE_THE_SHRINK = (160.0, 740.0, 240.0, 780.0)


def guard_fixture(neighbours):
    """The overflowing heading, its neighbours, and the finding made about it."""
    heading = laid_out(
        GUARD_TEXT,
        GUARD_X,
        GUARD_Y,
        size=GUARD_SIZE,
        width=GUARD_WIDTH,
        label="title",
        debug_id="head",
    )
    others = [
        boxed(f"neighbour {index}", box, debug_id=f"near{index}")
        for index, box in enumerate(neighbours)
    ]
    docs = document([page([heading, *others])])
    issues = of_kind(detect(docs)[0], page_bounds.KIND)
    # The heading's own finding, by the identity it carries, because a fixture
    # whose neighbours also left the page would otherwise be measured by one of
    # theirs.
    found = [issue for issue in issues if issue.evidence.get("debug_id") == "head"]
    return docs, heading, (found[0] if found else None)


def check_04g_a_slide_onto_a_neighbour_falls_back_to_shrinking() -> None:
    """Positive 4g: the slide is refused for what it would land on.

    And what it falls back to is the heading shrunk where it stands, which is
    inside the page and standing on nothing it was not standing on before.
    """
    docs, heading, issue = guard_fixture([GUARD_UNDER_THE_SLIDE])
    faults = []
    if issue is None:
        record(
            "check_04g_a_slide_onto_a_neighbour_falls_back_to_shrinking",
            False,
            "nothing was detected",
        )
        return
    min_iou = collision_bound()
    candidate = candidate_for(docs, issue)
    before = contain.standing_on(candidate, contain.ink_box(heading), min_iou)
    if before:
        faults.append(f"the fixture already stands on {sorted(before)}")
    outcome = contain.apply_one(candidate, contain_action(), min_iou)
    geometry = outcome.geometry
    guard = geometry.get("guard", {})
    if not outcome.accepted:
        faults.append(f"refused with {outcome.reason}")
    if geometry.get("state") != contain.STATE_SCALED_IN_PLACE:
        faults.append(f"the state is {geometry.get('state')}")
    if guard.get("slide_refused") != contain.GUARD_INDUCED:
        faults.append(f"the slide was refused for {guard.get('slide_refused')}")
    if not guard.get(contain.STATE_TRANSLATED, {}).get("induced"):
        faults.append("the record does not say what the slide would have stood on")
    if guard.get(contain.STATE_SCALED_IN_PLACE, {}).get("induced"):
        faults.append("the fallback was applied while standing on something new")
    if geometry.get("shift") != [0.0, 0.0]:
        faults.append(f"the fallback moved the heading by {geometry.get('shift')}")
    scale = geometry.get("scale", 0.0)
    if not 0.0 < scale < 1.0:
        faults.append(f"the fallback scaled by {scale}")
    # The guard's promise is about the document and not about the plan: what the
    # heading stands on now is what it stood on before, and nothing else.
    after = contain.standing_on(candidate, contain.ink_box(heading), min_iou)
    if set(after) - set(before):
        faults.append(f"the heading now stands on {sorted(set(after) - set(before))}")
    landed = detector_base.overflow(
        contain.ink_box(heading), tuple(geometry["safe_box"])
    )
    if max(landed.values()) > 1e-6:
        faults.append(f"the fallback left the ink outside the page by {landed}")
    record(
        "check_04g_a_slide_onto_a_neighbour_falls_back_to_shrinking",
        not faults,
        "; ".join(faults),
    )


def check_04h_a_heading_with_nowhere_to_go_is_escalated() -> None:
    """Negative 4h: neither the slide nor the fallback is clear, so nothing moves."""
    docs, heading, issue = guard_fixture(
        [GUARD_UNDER_THE_SLIDE, GUARD_INSIDE_THE_SHRINK]
    )
    faults = []
    if issue is None:
        record(
            "check_04h_a_heading_with_nowhere_to_go_is_escalated",
            False,
            "nothing was detected",
        )
        return
    min_iou = collision_bound()
    before = copy.deepcopy(docs)
    candidate = candidate_for(docs, issue)
    if contain.standing_on(candidate, contain.ink_box(heading), min_iou):
        faults.append("the fixture already stands on something")
    outcome = contain.apply_one(candidate, contain_action(), min_iou)
    guard = outcome.geometry.get("guard", {})
    if outcome.accepted or outcome.changed:
        faults.append("a heading with nowhere to go was moved anyway")
    if outcome.reason != contain.REASON_INDUCED:
        faults.append(f"refused with {outcome.reason}")
    if guard.get("fallback_refused") != contain.GUARD_INDUCED:
        faults.append(f"the fallback was refused for {guard.get('fallback_refused')}")
    for state in (contain.STATE_TRANSLATED, contain.STATE_SCALED_IN_PLACE):
        if not guard.get(state, {}).get("induced"):
            faults.append(f"the record does not say what {state} would have stood on")
    if checkpoint_module.to_checkpoint_xml(docs) != checkpoint_module.to_checkpoint_xml(
        before
    ):
        faults.append("the escalated document was not left exactly as it was")
    record(
        "check_04h_a_heading_with_nowhere_to_go_is_escalated",
        not faults,
        "; ".join(faults),
    )


def check_04i_the_guard_reads_the_detectors_bound() -> None:
    """Negative 4i: the guard is not a number of its own.

    It refuses at the overlap the collision detector reports at, so the same
    fixture driven at a bound nothing on the page reaches is slid after all.
    Asserted by driving the mechanism rather than by reading the source, so what
    is checked is the behaviour and not the spelling.
    """
    docs, _heading, issue = guard_fixture([GUARD_UNDER_THE_SLIDE])
    faults = []
    if issue is None:
        record(
            "check_04i_the_guard_reads_the_detectors_bound", False, "nothing detected"
        )
        return
    candidate = candidate_for(docs, issue)
    outcome = contain.apply_one(candidate, contain_action(), 1.0)
    if not outcome.accepted:
        faults.append(f"refused with {outcome.reason}")
    if outcome.geometry.get("state") != contain.STATE_TRANSLATED:
        faults.append(
            f"at a bound nothing reaches, the state is "
            f"{outcome.geometry.get('state')} rather than a slide"
        )
    if outcome.geometry.get("guard", {}).get("slide_refused") is not None:
        faults.append("the slide was refused at a bound nothing reaches")
    record(
        "check_04i_the_guard_reads_the_detectors_bound", not faults, "; ".join(faults)
    )


# --- 05 the default and the conservation ---------------------------------------


def check_05a_the_switch_is_down_by_default() -> None:
    """Negative 5a: with detection down the new detectors are never reached."""
    docs = document([page([laid_out("over the top", 100.0, 780.0, size=50.0)])])
    directory = _tmp_root / "switch_down"
    directory.mkdir(parents=True, exist_ok=True)

    class Down:
        magazine_detect = False

        def get_working_file_path(self, name: str) -> str:
            return str(directory / name)

    before = checkpoint_module.to_checkpoint_xml(docs)
    issues = detectors.detect_issues(Down(), docs)
    faults = []
    if issues:
        faults.append(f"{len(issues)} finding(s) with the switch down")
    written = sorted(path.name for path in directory.iterdir())
    if written:
        faults.append(f"files written with the switch down: {written}")
    if checkpoint_module.to_checkpoint_xml(docs) != before:
        faults.append("the document changed with the switch down")
    record("check_05a_the_switch_is_down_by_default", not faults, "; ".join(faults))


def check_05b_detection_changes_nothing() -> None:
    """Negative 5b: with the switch up the document is byte for byte what it was."""
    directory = _tmp_root / "detect_only"
    write_source(directory, document([collision_pair(100.0, 400.0)]))
    docs = document(
        [
            collision_pair(100.0, 100.0),
            page([laid_out("over the top", 100.0, 780.0, size=50.0, debug_id="c")]),
        ]
    )
    before = checkpoint_module.to_checkpoint_xml(docs)
    issues, _context = detect(docs, directory)
    faults = []
    if not issues:
        faults.append("the fixture produced no finding, so nothing was asserted")
    if checkpoint_module.to_checkpoint_xml(docs) != before:
        faults.append("detection changed the document")
    record("check_05b_detection_changes_nothing", not faults, "; ".join(faults))


def check_06_detection_is_deterministic() -> None:
    """Positive 6: the same document detected twice gives the same record."""
    directory = _tmp_root / "determinism"
    write_source(directory, document([collision_pair(100.0, 400.0)]))
    docs = document(
        [
            collision_pair(100.0, 100.0),
            page([laid_out("over the top", 100.0, 780.0, size=50.0, debug_id="c")]),
        ]
    )
    first = json.dumps(detectors.as_record(*reversed(detect(docs, directory))), sort_keys=True)
    second = json.dumps(
        detectors.as_record(*reversed(detect(docs, directory))), sort_keys=True
    )
    record("check_06_detection_is_deterministic", first == second, "the records differ")


# --- 07 scope, registration and spend ------------------------------------------


def check_07a_this_session_changed_only_what_it_may() -> None:
    """Negative 7a: extension code, configuration, gates and the named documents."""
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
    rulings = sorted(
        path
        for path in changed
        if path.startswith("reviews/") and path not in REVIEWS_ALLOWED
    )
    if rulings:
        faults.append(f"a ruling was edited: {rulings}")
    record("check_07a_this_session_changed_only_what_it_may", not faults, "; ".join(faults))


def check_07b_no_vocabulary_literal_in_the_new_code() -> None:
    """Negative 7b: no page type and no layout label is written into the modules.

    Page types because policy is what code may consume; layout labels because a
    repair that names one has stopped reading the configuration that declares
    which classes it may move.
    """
    declared = set(load_taxonomy().names())
    for action in repair_config().actions.values():
        for key in (
            react_config.ORPHAN_LABELS_KEY,
            react_config.CONTAIN_LABELS_KEY,
        ):
            declared |= set(action.applicability.get(key, ()))
    faults = []
    for relative in SESSION_MODULES:
        source = text_of(ROOT / relative)
        tree = ast.parse(source)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            if node.value in declared:
                faults.append(f"{relative}: names {node.value!r}")
    record(
        "check_07b_no_vocabulary_literal_in_the_new_code", not faults, "; ".join(faults)
    )


def check_07c_the_gate_spends_nothing() -> None:
    """Negative 7c: no credential, no network engine, ASCII prose."""
    source = text_of(Path(__file__))
    faults = []
    for forbidden in ("openai", "high_level", "doclayout", "requests", "httpx"):
        if re.search(rf"^\s*(import|from)\s+.*{forbidden}", source, re.MULTILINE):
            faults.append(f"imports {forbidden}")
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    if suffix in source.replace('"_API" + "_KEY"', ""):
        faults.append("names a credential variable")
    if "Engine(" not in source:
        faults.append("the loop is not driven by the stub declared here")
    for number, line in enumerate(source.splitlines(), start=1):
        if not line.isascii():
            offenders = [
                unicodedata.name(char, hex(ord(char)))
                for char in line
                if not char.isascii()
            ]
            faults.append(f"line {number}: {offenders[:3]}")
    for relative in SESSION_MODULES:
        for number, line in enumerate(text_of(ROOT / relative).splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{relative} line {number} is not ASCII")
    for path in (DETECTOR_CONFIG, REPAIR_CONFIG):
        for number, line in enumerate(text_of(path).splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{path.name} line {number} is not ASCII")
    record("check_07c_the_gate_spends_nothing", not faults, "; ".join(faults[:5]))


def check_07d_the_runner_registers_this_gate() -> None:
    """Positive 7d: the sweep runs this gate, after the batch it follows."""
    source = text_of(RUNNER)
    name = Path(__file__).name
    faults = []
    listed = re.findall(r'"(spec_check_[a-z0-9_]+\.py)"', source)
    if name not in listed:
        faults.append("run_all.py does not list this gate")
    elif "spec_check_b9_4.py" in listed and listed.index(
        "spec_check_b9_4.py"
    ) > listed.index(name):
        faults.append("this gate runs before the batch it follows")
    record("check_07d_the_runner_registers_this_gate", not faults, "; ".join(faults))


# --- 08 the authorised maintenance ---------------------------------------------


def check_08a_the_second_ruling_is_pinned() -> None:
    """Positive 8a: the ruling filed after b9.4 is pinned at what it was filed as."""
    from spec_checks import spec_check_b7_5

    faults = []
    pinned = spec_check_b7_5.TRUTH_DIGESTS.get(FD_RULING)
    if pinned is None:
        faults.append("the ruling carries no digest pin")
    elif pinned != FD_RULING_DIGEST:
        faults.append(f"pinned at {pinned}")
    else:
        actual = spec_check_b7_5.sha256_file(ROOT / FD_RULING)
        if actual != FD_RULING_DIGEST:
            faults.append(f"the file digests to {actual}")
    record("check_08a_the_second_ruling_is_pinned", not faults, "; ".join(faults))


def check_08b_the_stale_statements_are_corrected() -> None:
    """Positive 8b: three documents no longer say the verdict has no reader.

    Batch b9.4 gave the drop cap verdict a reader. Three places said otherwise
    and are the standing risk of a document that describes the system: a reader
    of the review format, the gap register's axis B, and the upstream registry
    row for the pass that finds a candidate.
    """
    faults = []
    reviews = text_of(ROOT / "reviews" / "README.md")
    if "no stage reads it yet" in reviews:
        faults.append("the review format still says no stage reads the verdict")
    if "magazine_drop_cap_apply" not in reviews:
        faults.append("the review format does not name the reader")
    register = text_of(ROOT / "docs" / "eval" / "gap_register.md")
    if "Nothing consumes the ruling" in register:
        faults.append("the gap register still quotes the retired sentence")
    if "batch-b9.4" not in register:
        faults.append("the gap register does not name the batch that closed axis B")
    registry = text_of(ROOT / "UPSTREAM_DIFF.md")
    if "first_style_run" in registry:
        faults.append("the registry still names a function that was renamed")
    if "`leading_run`" not in registry:
        faults.append("the registry does not name the function that replaced it")
    if "B9.4 |" not in registry:
        faults.append("the registry has no row for the pass that rewrites a composition")
    # And the renamed function is the one that exists.
    from babeldoc.magazine import drop_cap

    if not hasattr(drop_cap, "leading_run") or hasattr(drop_cap, "first_style_run"):
        faults.append("the module does not carry the name the registry now gives it")
    record("check_08b_the_stale_statements_are_corrected", not faults, "; ".join(faults))


def check_08c_the_runner_declares_its_encoding() -> None:
    """Positive 8c: the sweep's output is UTF-8 on every hop, declared not assumed.

    A redirect into a file takes its encoding from the locale, which on a
    Windows workstation is a legacy codepage. The failure is a raise rather than
    a mangled line, so a sweep that ran for hours ends with no summary at all.
    """
    source = text_of(RUNNER)
    faults = []
    if "reconfigure(encoding=IO_ENCODING" not in source:
        faults.append("the runner's own streams are left at the platform default")
    if 'env["PYTHONIOENCODING"]' not in source:
        faults.append("a gate writing into a pipe is not told what to encode with")
    if source.count("encoding=IO_ENCODING") < 3:
        faults.append("not every hop declares the encoding it uses")
    if 'IO_ERRORS = "replace"' not in source:
        faults.append("an unencodable character still raises rather than being marked")
    # The runner still imports and parses, which is the cheapest proof that the
    # stream reconfiguration at module scope does not raise on this platform.
    proc = subprocess.run(  # noqa: S603
        [PYTHON, "-c", "import sys; sys.path.insert(0, '.'); import spec_checks.run_all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        faults.append(f"the runner does not import: {(proc.stderr or '')[-200:]}")
    record("check_08c_the_runner_declares_its_encoding", not faults, "; ".join(faults))


def check_08d_the_contract_carries_the_replay_boundary() -> None:
    """Positive 8d: the one pass that cannot be replayed is written down once."""
    contract = text_of(ROOT / "docs" / "eval" / "metric_contract.md")
    faults = []
    for token in ("babeldoc/magazine/react/decide.py", "GAP-20", "b9.4", "E2.1"):
        if token not in contract:
            faults.append(f"the clause does not cite {token}")
    if "ignore_cache=True" not in contract:
        faults.append("the clause does not say what makes the pass unreplayable")
    # What it describes is what the code does.
    source = text_of(ROOT / "babeldoc" / "magazine" / "react" / "decide.py")
    if "ignore_cache=True" not in source:
        faults.append("the decision transport no longer bypasses the engine cache")
    record(
        "check_08d_the_contract_carries_the_replay_boundary", not faults, "; ".join(faults)
    )


def check_08e_the_census_no_longer_writes_frozen_evidence() -> None:
    """Negative 8e: the b8 census writes beside the tracked table, not over it.

    A gate may read produced evidence git carries and may not write it. The
    census table is cited by the evidence ledger, and it was being rewritten on
    every sweep; adding a detector would have rewritten it with a wider header
    and failed the sweep's own frozen-evidence guard.
    """
    from spec_checks import spec_check_b8

    faults = []
    if spec_check_b8.CENSUS_TABLE == spec_check_b8.FROZEN_CENSUS_TABLE:
        faults.append("the census still writes the tracked table")
    tracked = f"examples/output/b8/{spec_check_b8.FROZEN_CENSUS_TABLE}"
    code, listing = git_output(["ls-files", tracked])
    if code != 0 or not listing.strip():
        faults.append(f"{tracked} is not tracked, so this assertion is about nothing")
    code, listing = git_output(
        ["ls-files", f"examples/output/b8/{spec_check_b8.CENSUS_TABLE}"]
    )
    if listing.strip():
        faults.append("the current census is tracked, which makes it frozen too")
    if tracked not in text_of(ROOT / "docs" / "eval" / "evidence_ledger.md"):
        faults.append("the ledger no longer cites the table this protects")
    record(
        "check_08e_the_census_no_longer_writes_frozen_evidence", not faults, "; ".join(faults)
    )


# --- 10 the acceptance session ------------------------------------------------


def acceptance_evidence() -> dict | None:
    return load_json(ACCEPTANCE_EVIDENCE) if ACCEPTANCE_EVIDENCE.exists() else None


def check_10a_the_acceptance_left_its_evidence() -> None:
    """Positive 10a: the arms, the report and the fixture are all on disk."""
    faults = []
    for arm in ACCEPTANCE_ARMS:
        path = ACCEPTANCE_DIR / f"runs.{arm}.json"
        if not path.exists():
            faults.append(f"no ledger for the {arm} arm")
            continue
        rows = load_json(path)
        if len(rows) != len(CORPUS_SAMPLES):
            faults.append(f"the {arm} arm ran {len(rows)} of {len(CORPUS_SAMPLES)}")
        missing = sorted(
            CORPUS_SAMPLES - {row["sample"].removesuffix(".pdf") for row in rows}
        )
        if missing:
            faults.append(f"the {arm} arm did not run {missing}")
    for path in (
        ACCEPTANCE_REPORT,
        ACCEPTANCE_EVIDENCE,
        FIXTURE_ARCHIVE,
        FIXTURE_CONTAINMENT,
        FIXTURE_ISSUES,
    ):
        if not path.exists():
            faults.append(f"{path.relative_to(ROOT).as_posix()} was not written")
    record("check_10a_the_acceptance_left_its_evidence", not faults, "; ".join(faults))


def unpack_fixture(destination: Path) -> Path:
    """The frozen checkpoints, read out of the archive into a scratch directory.

    Read only, in both directions: the archive is never written and the copy is
    never put back. What the replay measures is what git carries.
    """
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(FIXTURE_ARCHIVE) as bundle:
        bundle.extractall(destination)
    return destination


def replay_containment(directory: Path) -> dict:
    """Drive the shipped detectors and the shipped action over the fixture.

    The same three steps the loop takes -- resolve the finding to its paragraph,
    hold it against the action's own rule, apply -- so what is compared against
    the frozen record is the mechanism and not a description of it.
    """
    config = detectors.detector_config()
    stem = checkpoint_module.checkpoint_stem("typesetting")
    document = checkpoint_module.load_checkpoint(directory / f"{stem}.xml")
    source = detectors.source_geometry_of(directory, config)
    context = detectors.build_context(
        document, config, LANGUAGE, directory, source_geometry=source
    )
    issues = detectors.run_detectors(context)
    action = repair_config().actions[contain.NAME]
    pages_by_label = {view.label: view for view in context.pages}
    applied, escalated, refused = [], [], []
    for issue in issues:
        if issue.kind != page_bounds.KIND:
            continue
        candidate = actions.resolve(issue, pages_by_label)
        verdict = contain.admits(issue, candidate, action, context)
        if verdict != actions.ACCEPTED:
            refused.append({"ref": candidate.reference, "reason": verdict})
            continue
        outcome = contain.apply_one(candidate, action, config.collision_min_iou)
        row = {
            "ref": candidate.reference,
            "reason": outcome.reason,
            "geometry": outcome.geometry,
        }
        (applied if outcome.accepted else escalated).append(row)
    return {
        "counts": counts_by_kind(issues),
        "applied": applied,
        "escalated": escalated,
        "refused": refused,
    }


def counts_by_kind(issues) -> dict:
    found: dict[str, int] = {}
    for issue in issues:
        found[issue.kind] = found.get(issue.kind, 0) + 1
    return dict(sorted(found.items()))


# What of a containment record has to come back identical on a replay. The
# geometry is compared field by field rather than as a whole object, so a record
# that gains a field a later batch adds does not fail a replay of the arithmetic
# this one froze.
REPLAYED_GEOMETRY = ("state", "scale", "shift", "box_before", "box_after", "safe_box")


def check_10b_the_frozen_fixture_replays() -> None:
    """Positive 10b: the frozen documents still produce the frozen geometry."""
    faults = []
    if not (FIXTURE_ARCHIVE.exists() and FIXTURE_CONTAINMENT.exists()):
        record(
            "check_10b_the_frozen_fixture_replays", False, "the fixture is not on disk"
        )
        return
    frozen = load_json(FIXTURE_CONTAINMENT)
    replayed = replay_containment(unpack_fixture(_tmp_root / "fixture"))
    if replayed["counts"] != frozen["counts"]:
        faults.append(
            f"the fixture now reports {replayed['counts']}, frozen "
            f"{frozen['counts']}"
        )
    for name in ("applied", "escalated", "refused"):
        here = replayed[name]
        there = frozen["containment"][name]
        if len(here) != len(there):
            faults.append(f"{name}: {len(here)} now, {len(there)} frozen")
            continue
        for now, then in zip(here, there, strict=True):
            if now["ref"] != then["ref"] or now["reason"] != then["reason"]:
                faults.append(
                    f"{name}: {now['ref']} {now['reason']} now, "
                    f"{then['ref']} {then['reason']} frozen"
                )
                continue
            for field in REPLAYED_GEOMETRY:
                if now.get("geometry", {}).get(field) != then.get("geometry", {}).get(
                    field
                ):
                    faults.append(
                        f"{name}: {now['ref']}.{field} is "
                        f"{now.get('geometry', {}).get(field)}, frozen "
                        f"{then.get('geometry', {}).get(field)}"
                    )
    record("check_10b_the_frozen_fixture_replays", not faults, "; ".join(faults))


def check_10c_the_census_says_what_the_detector_raised() -> None:
    """Positive 10c: the census and the findings are one set of numbers.

    Every pair the census classified as induced is a pair the detector raised,
    and every pair it exempted is one the detector did not, on every sample.
    """
    evidence = acceptance_evidence()
    if evidence is None:
        record("check_10c_the_census_says_what_the_detector_raised", False, "no evidence")
        return
    faults = []
    for item in evidence["samples"]:
        raised = [pair for pair in item["pairs"] if pair["raised"]]
        induced = [pair for pair in item["pairs"] if pair["class"] == "induced"]
        if raised != induced:
            faults.append(f"{item['sample']}: {len(raised)} raised, {len(induced)} induced")
        found = item["counts"].get(collision_detector.KIND, 0)
        if found != len(induced):
            faults.append(
                f"{item['sample']}: the detector raised {found} and the census "
                f"counted {len(induced)}"
            )
        for pair in item["pairs"]:
            if pair["class"] == "source design" and pair["raised"]:
                faults.append(f"{item['sample']}: an exempt pair was raised")
    record(
        "check_10c_the_census_says_what_the_detector_raised", not faults, "; ".join(faults)
    )


def check_10d_nothing_moved_outside_the_contained_set() -> None:
    """Positive 10d: the soul assertion, on every sample and on three channels.

    In the run: each arm's loop reports its own document conserved and names no
    paragraph changed outside the ones it touched. On the intermediate language:
    every paragraph the action did not name carries the digest it carried
    before. On the page: what the scripted arm renders differently is a page it
    contained on, unless the control arm moved that page too -- which is the
    attribution floor -- or that arm had to resample a translation, which is the
    one channel the evaluation protocol records as unreplayable. A sample where
    neither arm resampled anything has no such excuse and is held to the page.
    """
    evidence = acceptance_evidence()
    if evidence is None:
        record("check_10d_nothing_moved_outside_the_contained_set", False, "no evidence")
        return
    faults = []
    for item in evidence["samples"]:
        for arm, summary in (item.get("loop") or {}).items():
            if not summary.get("ran"):
                continue
            conservation = summary.get("conservation") or {}
            if conservation.get("verdict") != "conserved":
                faults.append(
                    f"{item['sample']}/{arm}: the loop reported "
                    f"{conservation.get('verdict')}"
                )
            if conservation.get("changed_outside_touched"):
                faults.append(
                    f"{item['sample']}/{arm}: "
                    f"{conservation['changed_outside_touched']} changed outside "
                    f"the touched set"
                )
        conservation = item["conservation"]
        if conservation["moved_outside_touched"]:
            faults.append(
                f"{item['sample']}: {conservation['moved_outside_touched']} changed "
                f"outside the contained set"
            )
        if not conservation["shape_held"]:
            faults.append(f"{item['sample']}: the paragraph set changed")
        raster = item.get("raster") or {}
        contained = set(item.get("contain_pages") or ())
        floor = set(raster.get("control_moved") or ())
        outside = sorted(set(raster.get("contain_moved") or ()) - contained - floor)
        calls = item.get("api_calls") or {}
        resampled = (calls.get("off") or 0) + (calls.get("contain") or 0)
        if outside and not resampled:
            faults.append(
                f"{item['sample']}: pages {outside} render differently, were "
                f"neither contained on nor moved by the control arm, and neither "
                f"arm resampled anything"
            )
    record(
        "check_10d_nothing_moved_outside_the_contained_set", not faults, "; ".join(faults)
    )


def check_10e_the_scripted_arm_is_scripted_and_says_so() -> None:
    """Negative 10e: the fourth arm chose nothing, and nothing hid that.

    Its decisions are written down, every one of them is either containment or
    nothing, and the report names it as scripted rather than presenting it as
    what a model chose.
    """
    path = ACCEPTANCE_DIR / "runs.contain.json"
    if not path.exists():
        record("check_10e_the_scripted_arm_is_scripted_and_says_so", False, "no ledger")
        return
    faults = []
    allowed = {contain.NAME, "none"}
    for row in load_json(path):
        answers = row.get("scripted_decisions")
        if not answers:
            faults.append(f"{row['sample']} recorded no scripted decision")
            continue
        outside = sorted({answer["action"] for answer in answers} - allowed)
        if outside:
            faults.append(f"{row['sample']} scripted {outside}")
    if ACCEPTANCE_REPORT.exists():
        text = text_of(ACCEPTANCE_REPORT)
        if "scripted rather than sampled" not in text:
            faults.append("the report does not say the fourth arm is scripted")
    else:
        faults.append("the report was not written")
    record(
        "check_10e_the_scripted_arm_is_scripted_and_says_so", not faults, "; ".join(faults)
    )


# The gaps this session files, and the figures each of them quotes. The figures
# are recomputed from the evidence and matched in the text, so a register entry
# cannot drift away from the run it describes.
GAP_REGISTER = ROOT / "docs" / "eval" / "gap_register.md"
FILED_GAPS = ("GAP-22", "GAP-23", "GAP-24", "GAP-25", "GAP-26")
NEAR_MISS_COVERAGE = 0.5


def census_totals(evidence: dict) -> dict:
    """What the corpus census adds up to, recomputed from the evidence."""
    classes: dict[str, int] = {}
    near = raised = pairs = 0
    origins: dict[str, int] = {}
    applied = refused = findings = 0
    contained_by_model = 0
    for item in evidence["samples"]:
        for pair in item["pairs"]:
            pairs += 1
            classes[pair["class"]] = classes.get(pair["class"], 0) + 1
            raised += bool(pair["raised"])
            if not pair["raised"] and pair["covered"] >= NEAR_MISS_COVERAGE:
                near += 1
        for row in item["out_of_page"]:
            findings += 1
            origins[row["origin"]] = origins.get(row["origin"], 0) + 1
        applied += len(item["containment"]["applied"])
        refused += len(item["containment"]["refused"])
        summary = (item.get("loop") or {}).get("on") or {}
        contained_by_model += sum(
            1
            for row in summary.get("executed", ())
            if "safe_box" in (row.get("geometry") or {})
        )
    return {
        "pairs": pairs,
        "classes": classes,
        "raised": raised,
        "near": near,
        "out_of_page": findings,
        "origins": origins,
        "applied": applied,
        "refused": refused,
        "contained_by_model": contained_by_model,
    }


def check_10f_the_register_carries_this_batchs_gaps() -> None:
    """Positive 10f: the F2 readiness list is filed and quotes the run's figures.

    Every gap this session files is in the register, and the figures the entries
    argue from are the figures the evidence holds. A register that quotes a
    number the run does not produce is worse than one that quotes none.
    """
    evidence = acceptance_evidence()
    if evidence is None:
        record("check_10f_the_register_carries_this_batchs_gaps", False, "no evidence")
        return
    faults = []
    text = text_of(GAP_REGISTER)
    for gap in FILED_GAPS:
        if f"### {gap} " not in text:
            faults.append(f"{gap} is not filed")
    totals = census_totals(evidence)
    quoted = {
        "overlapping pairs": totals["pairs"],
        "raised collisions": totals["raised"],
        "source design pairs": totals["classes"].get("source design", 0),
        "pairs below the bound": totals["classes"].get("below the bound", 0),
        "covered near misses": totals["near"],
        "out of page findings": totals["out_of_page"],
        "containments applied": totals["applied"],
        "containments refused": totals["refused"],
    }
    for what, value in quoted.items():
        if f"**{value}**" not in text and f" {value} " not in text:
            faults.append(f"the register does not quote {what} as {value}")
    if totals["contained_by_model"] != 0:
        faults.append(
            f"GAP-25 says the model chose containment never; it chose it "
            f"{totals['contained_by_model']} time(s)"
        )
    if f"0/{totals['applied']}" not in text:
        faults.append(
            f"GAP-25 does not state the rate as 0/{totals['applied']}"
        )
    record(
        "check_10f_the_register_carries_this_batchs_gaps", not faults, "; ".join(faults)
    )


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
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_09_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01a_detector_bounds_are_declared,
        check_01b_detector_negative_probes,
        check_01c_the_vocabulary_gained_two_actions,
        check_01d_repair_negative_probes,
        check_01e_the_action_is_stricter_than_the_detector,
        check_02a_ink_past_the_frame_is_reported,
        check_02b_the_noise_floor_holds,
        check_02c_the_safety_margin_reports_ink_at_the_trim,
        check_02d_the_ink_is_measured_not_the_box,
        check_02e_a_page_with_no_frame_is_noted,
        check_03a_an_induced_collision_is_reported,
        check_03b_a_source_design_overlay_is_exempt,
        check_03c_an_overlap_below_the_bound_is_not_a_finding,
        check_03d_a_member_with_no_source_is_never_a_finding,
        check_03e_a_split_line_finds_its_parent,
        check_03f_without_the_source_the_detector_does_not_run,
        check_04a_a_heading_that_fits_is_slid,
        check_04b_a_heading_too_large_is_scaled,
        check_04c_a_heading_past_the_floor_is_escalated,
        check_04d_containment_refuses_what_it_may_not_move,
        check_04e_the_loop_carries_containment,
        check_04f_the_collision_action_refuses_a_pair_of_equals,
        check_04g_a_slide_onto_a_neighbour_falls_back_to_shrinking,
        check_04h_a_heading_with_nowhere_to_go_is_escalated,
        check_04i_the_guard_reads_the_detectors_bound,
        check_05a_the_switch_is_down_by_default,
        check_05b_detection_changes_nothing,
        check_06_detection_is_deterministic,
        check_07a_this_session_changed_only_what_it_may,
        check_07b_no_vocabulary_literal_in_the_new_code,
        check_07c_the_gate_spends_nothing,
        check_07d_the_runner_registers_this_gate,
        check_08a_the_second_ruling_is_pinned,
        check_08b_the_stale_statements_are_corrected,
        check_08c_the_runner_declares_its_encoding,
        check_08d_the_contract_carries_the_replay_boundary,
        check_08e_the_census_no_longer_writes_frozen_evidence,
        check_10a_the_acceptance_left_its_evidence,
        check_10b_the_frozen_fixture_replays,
        check_10c_the_census_says_what_the_detector_raised,
        check_10d_nothing_moved_outside_the_contained_set,
        check_10e_the_scripted_arm_is_scripted_and_says_so,
        check_10f_the_register_carries_this_batchs_gaps,
        check_09_sweep,
    ]
    for check in checks:
        name = check.__name__
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(name, False, f"raised {exc!r}")
    print(f"\nspec_check_b9_5: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_b9_5")
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
