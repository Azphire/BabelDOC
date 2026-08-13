"""Gate script for batch B8 session two (the repair controller and its action).

Run from the repository root:

    python spec_checks/spec_check_b8_2.py

Exit code 0 when every assertion T8.2 answers for passes, 1 otherwise. Needs no
API key and makes no network request: every engine in this file is a stub that
answers from a rule written here, and the one really translated document it
reads was frozen from a run an earlier batch paid for.

01 is the configuration. Every bound declared and respected, every action
answering for issue kinds that a detector actually raises, and the negative
probes that prove the parser refuses rather than repairs: an action named after
the reserved word for applying nothing, an issue kind nothing raises, a default
outside its own range, an applicability block missing a term the rule needs.

02 is the decision point over the whole spectrum a model can answer with: a
legal reply, an action outside the vocabulary, a finding that was not offered,
a parameter out of range, malformed JSON, and a reply that declines. The rule
being asserted is the same in every case except the first -- one retry, then
the iteration applies nothing -- because not repairing is the safe failure of a
repair loop. The cache is asserted separately: a second decision over the same
findings spends no request.

03 is the applicability filter, which is where precision lives. The two
findings the b8.1 report called arguably-not-defects -- a translated line
keeping a personal name, and a byline correctly left in its source script --
are built here in their measured shape and have to be refused, by the rule that
a paragraph the translator was given is not one this action overrules. Beside
them: an orphan below the share bound, an orphan too short, and the boundary
itself.

04 is the write-back. A repaired paragraph survives the intermediate language's
own round trip unchanged, keeps its box and its orientation flag, and is laid
out in a font the font mapper will register at PDF creation -- which is what
makes the repaired characters printable without rerunning anything.

05 is the loop and its guards. A stub that never converges has to be rolled
back and the loop stopped, with the document byte for byte what it was; the
iteration ceiling has to hold; the log has to carry, per iteration, what was
found, what was decided, what was executed and what the recheck saw.

06 is the live evidence: the loop driven over orphan paragraphs a real
translated run produced, where p6#15 -- the fallback line two b7.5 passes
measured as untranslated -- has to be the one repaired.

07 is the default and the conservation over a real pipeline run: with the
repair switch down nothing about detection changes, and with it up on a run
with nothing to repair the intermediate language and the PDF are identical.

08 is the scope. No page type, no repair profile and no publication is a
literal in the package; no prompt text is; no upstream file is in this batch's
delta; the ruling and corpus files are not written.

Tiers: 07 needs pipeline artefacts and belongs to the pipeline tier; the rest
are static, 06 included -- the fixture is frozen and reading it spends nothing.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.detectors import base as detector_base  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.magazine.react import writeback  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b8.2"

PYTHON = sys.executable

PACKAGE = ROOT / "babeldoc" / "magazine" / "react"
CONFIG = "configs/repair_actions.json"
OUTPUT_DIR = ROOT / "examples" / "output" / "b8"
FIXTURE = OUTPUT_DIR / "Courier-en.orphans.fixture.xml"
FIXTURE_PROVENANCE = OUTPUT_DIR / "Courier-en.orphans.fixture.json"
REPAIR_EVIDENCE = OUTPUT_DIR / "fixture_repair.json"

PROMPT_DIR = ROOT / "prompts"
DECIDE_PROMPT = PROMPT_DIR / "react_repair_decide.md"
TRANSLATE_PROMPT = PROMPT_DIR / "react_translate_orphan.md"
GLOSSARY_PROMPT = PROMPT_DIR / "react_orphan_glossary.md"

# The finding this batch, like the one before it, exists for.
LIVE_REFERENCE = "p6#15"

# The two findings the b8.1 report named as names rather than defects.
NAME_REFERENCES = ("p1#20", "p1#25")

LANGUAGE = "zh"

# Target language text the stubs render, and the source shape of the finding
# that keeps a personal name. Written as escapes rather than as characters
# because no source file of this project carries text in the target language;
# what each one reads is stated beside it.
# photographed for the UNESCO Courier
TARGET_CREDIT = "\u4e3a\u8054\u5408\u56fd\u6559\u79d1\u6587\u7ec4\u7ec7\u300a\u4fe1\u4f7f\u300b\u62cd\u6444"
# translated caption
TARGET_CAPTION = "\u8bd1\u540e\u7684\u56fe\u7247\u8bf4\u660e"
# an already translated body paragraph
TARGET_BODY = "\u5df2\u7ecf\u7ffb\u8bd1\u597d\u7684\u6b63\u6587\u6bb5\u843d"
# interview with Ora Marek-Martinez: the live finding that keeps a name
TARGET_INTERVIEW = "\u4e0eOra Marek-Martinez\u7684\u8bbf\u8c08"
# the UNESCO Courier, as a ruled glossary target
TARGET_TITLE = "\u8054\u5408\u56fd\u6559\u79d1\u6587\u7ec4\u7ec7\u300a\u4fe1\u4f7f\u300b"
TARGET_TITLE_PLAIN = "\u8054\u5408\u56fd\u6559\u79d1\u6587\u7ec4\u7ec7\u4fe1\u4f7f"
# a translation, of nothing in particular
TARGET_ANY = "\u8bd1\u6587"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = ("check_07_switch_down_run",)

# Paths this session may change. No upstream file is in it: the batch is
# delivered under a zero-upstream-change constraint and the hook it uses is the
# one the previous session already registered.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "prompts/",
    "tools/",
    "spec_checks/",
    "plans/",
    "examples/output/",
)
ALLOWED_FILES = {"UPSTREAM_DIFF.md", "WAIVERS.md"}

# Files a repair run may never write to.
READ_ONLY = ("corpus/registry.user.json", "corpus/page_labels.json")

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b8_2_"))

# The gate never writes a review draft into the working tree it asserts about.
os.environ[hitl.REVIEWS_ENV] = str(_tmp_root / "reviews")

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b8_2")


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


def skip(name: str) -> None:
    global _total
    _total += 1
    _timer.mark(name)
    harness.fast_skip(name)


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


def issue_kinds() -> tuple[str, ...]:
    return tuple(sorted(module.KIND for module in detectors.DETECTORS.values()))


def repair_config():
    return react_config.load_repair_config(None, issue_kinds())


def raw_config() -> dict:
    with (ROOT / CONFIG).open(encoding="utf-8") as f:
        return json.load(f)


def parse(raw: dict):
    return react_config.parse_repair_config(raw, "probe.json", set(issue_kinds()))


# --- documents and engines built here -----------------------------------------


# The font id every built paragraph is set in. The mapper always carries it, so
# a built paragraph can be laid out again without a page font list.
BUILT_FONT = "base"


def style(font: str = BUILT_FONT, size: float = 10.0):
    return il_version_1.PdfStyle(
        font_id=font, font_size=size, graphic_state=il_version_1.GraphicState()
    )


def character(text: str, font: str = BUILT_FONT, size: float = 10.0):
    return il_version_1.PdfCharacter(
        char_unicode=text,
        box=il_version_1.Box(0.0, 0.0, 5.0, size),
        visual_bbox=il_version_1.VisualBbox(box=il_version_1.Box(0.0, 0.0, 5.0, size)),
        pdf_style=style(font, size),
        vertical=False,
    )


def paragraph(
    text: str,
    label: str = "fallback_line",
    box: tuple[float, float, float, float] = (0.0, 0.0, 400.0, 12.0),
    carry_style: bool = False,
    as_characters: bool = True,
):
    """One paragraph in the shape a finished page carries it.

    ``carry_style`` is the difference between a paragraph the styling stage gave
    a style and an orphan, which has none of its own and whose style has to come
    from its characters.
    """
    if as_characters:
        composition = [
            il_version_1.PdfParagraphComposition(pdf_character=character(item))
            for item in text
        ]
    else:
        composition = [
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        unicode=text, pdf_style=style()
                    )
                )
            )
        ]
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*box),
        pdf_style=style() if carry_style else None,
        pdf_paragraph_composition=composition,
        unicode=text,
        layout_label=label,
        debug_id=f"d{abs(hash(text)) % 100000}",
        vertical=False,
        xobj_id=-1,
    )


def page(paragraphs, number: int = 0, kind: str | None = None):
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=il_version_1.Box(0.0, 0.0, 600.0, 800.0)),
        cropbox=il_version_1.Cropbox(box=il_version_1.Box(0.0, 0.0, 600.0, 800.0)),
        pdf_paragraph=list(paragraphs),
        page_number=number,
        unit="point",
        page_kind=kind,
    )


def document(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


class LayoutModel:
    stage_name = "stub"

    def predict(self, *args, **kwargs):
        return []


def Config(directory: Path, translator=None, **attributes):  # noqa: N802
    """A real translation config in a directory of its own.

    Real rather than a stand-in: the loop hands it to the typesetting stage and
    to the font mapper, both of which read more of it than a stand-in would be
    honest about carrying.
    """
    directory.mkdir(parents=True, exist_ok=True)
    config = TranslationConfig(
        translator=translator,
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
    for name, value in attributes.items():
        setattr(config, name, value)
    return config


class Engine:
    """A stub model: a queue of replies, and a count of what was asked."""

    name = "stub"

    def __init__(self, decisions, translations=None):
        self.decisions = list(decisions)
        self.translations = list(translations or [])
        self.requests: list[str] = []

    def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
        self.requests.append(text)
        if "Actions available" in text:
            return self.decisions.pop(0) if self.decisions else "{}"
        return self.translations.pop(0) if self.translations else "{}"


class NoCache:
    def get(self, key):
        return None

    def set(self, key, value):
        return None


class Memory:
    def __init__(self):
        self.rows: dict[str, str] = {}

    def get(self, key):
        return self.rows.get(key)

    def set(self, key, value):
        self.rows[key] = value


def decision_reply(ids, action: str = actions.NAME, parameters=None, reason="because"):
    return json.dumps(
        {
            "action": action,
            "issue_ids": list(ids),
            "parameters": parameters if parameters is not None else {},
            "reason": reason,
        }
    )


def translation_reply(text: str) -> str:
    return json.dumps({actions.TRANSLATION_FIELD: text})


def build_loop(directory: Path, docs, engine, cache=None, translations_cache=None):
    """One loop wired to a stub engine, with the caches the caller chose."""
    config = Config(directory, translator=engine)
    loop = controller.RepairLoop(config, docs)
    loop.decision_client = decide.CachedDecisionClient(
        loop.repair_config,
        transport=decide.EngineTransport(engine),
        cache=NoCache() if cache is None else cache,
        working_dir=loop.working_dir,
    )
    loop.translator = actions.CachedOrphanTranslator(
        loop.repair_config,
        transport=decide.EngineTransport(engine),
        cache=NoCache() if translations_cache is None else translations_cache,
        language=LANGUAGE,
        glossaries=[],
        working_dir=loop.working_dir,
    )
    return loop


def report_of(loop) -> dict:
    with (loop.working_dir / controller.REPORT_NAME).open(encoding="utf-8") as f:
        return json.load(f)


# --- 01 the configuration -----------------------------------------------------


def check_01a_config_bounds() -> None:
    """Positive 1a: every declared bound exists, is respected, and is reachable."""
    faults = []
    raw = raw_config()
    try:
        config = parse(raw)
    except react_config.RepairConfigError as exc:
        record("check_01a_config_bounds", False, f"the declared file is refused: {exc}")
        return
    if config.max_iterations < 1:
        faults.append("the iteration ceiling admits no iteration")
    if config.decide_max_attempts < 1:
        faults.append("the attempt ceiling admits no attempt")
    if actions.NAME not in config.actions:
        faults.append(f"the vocabulary omits {actions.NAME}")
    else:
        action = config.actions[actions.NAME]
        if actions.MAX_PARAGRAPHS not in action.parameters:
            faults.append(f"{actions.NAME} declares no {actions.MAX_PARAGRAPHS}")
        if not action.issue_kinds:
            faults.append(f"{actions.NAME} answers for no issue kind")
        for key in (
            react_config.MIN_RATIO_KEY,
            react_config.MIN_CHARS_KEY,
            react_config.ORPHAN_LABELS_KEY,
        ):
            if key not in action.applicability:
                faults.append(f"applicability omits {key}")
        # The action's share bound has to be at least the detector's, or the
        # action would act on findings the detector was not sure enough to make.
        detector = detectors.detector_config().residue_rule(LANGUAGE)
        if detector is not None:
            if float(action.applicability[react_config.MIN_RATIO_KEY]) < detector[1]:
                faults.append(
                    "the action acts below the share the detector reports at"
                )
    # Every number in the file, at every depth, carries a range.
    def numbers_without_range(node, path: str) -> list[str]:
        missing = []
        if not isinstance(node, dict):
            return missing
        for key, value in node.items():
            if key.endswith(react_config.RANGE_SUFFIX) or key == "description":
                continue
            if isinstance(value, dict):
                missing.extend(numbers_without_range(value, f"{path}.{key}"))
            elif isinstance(value, int | float) and not isinstance(value, bool):
                if f"{key}{react_config.RANGE_SUFFIX}" not in node:
                    missing.append(f"{path}.{key}")
        return missing

    faults.extend(
        f"{name} declares no allowed range" for name in numbers_without_range(raw, CONFIG)
    )
    record("check_01a_config_bounds", not faults, "; ".join(faults))


def check_01b_config_negative_probes() -> None:
    """Negative 1b: a malformed configuration is refused rather than repaired."""
    faults = []

    def refuses(mutate, what: str) -> None:
        raw = raw_config()
        mutate(raw)
        try:
            parse(raw)
        except react_config.RepairConfigError:
            return
        faults.append(f"accepted {what}")

    def rename_to_none(raw):
        raw[react_config.ACTIONS_KEY][react_config.NO_ACTION] = raw[
            react_config.ACTIONS_KEY
        ].pop(actions.NAME)

    refuses(rename_to_none, "an action named after the word for applying nothing")
    refuses(
        lambda raw: raw[react_config.ACTIONS_KEY][actions.NAME].__setitem__(
            react_config.ISSUE_KINDS_KEY, ["no_detector_raises_this"]
        ),
        "an action answering for an issue kind nothing raises",
    )
    refuses(
        lambda raw: raw[react_config.ACTIONS_KEY][actions.NAME][
            react_config.PARAMETERS_KEY
        ][actions.MAX_PARAGRAPHS].__setitem__("default", 9999),
        "a parameter default outside its own range",
    )
    refuses(
        lambda raw: raw[react_config.ACTIONS_KEY][actions.NAME][
            react_config.APPLICABILITY_KEY
        ].pop(react_config.ORPHAN_LABELS_KEY),
        "an applicability block missing the orphan label set",
    )
    refuses(
        lambda raw: raw[react_config.ACTIONS_KEY][actions.NAME][
            react_config.APPLICABILITY_KEY
        ].pop(f"{react_config.MIN_RATIO_KEY}{react_config.RANGE_SUFFIX}"),
        "a share bound with no range beside it",
    )
    refuses(
        lambda raw: raw.__setitem__("max_iterations", 0),
        "an iteration ceiling outside its own range",
    )
    refuses(
        lambda raw: raw.pop(react_config.ACTIONS_KEY),
        "a file declaring no action vocabulary",
    )
    record("check_01b_config_negative_probes", not faults, "; ".join(faults))


def check_01c_parameters_bounded() -> None:
    """Positive 1c: an action refuses a parameter it does not declare or cannot hold."""
    action = repair_config().actions[actions.NAME]
    faults = []
    resolved = action.resolve({})
    if resolved.get(actions.MAX_PARAGRAPHS) != action.parameters[
        actions.MAX_PARAGRAPHS
    ].default:
        faults.append("an empty parameter object did not fall to the declared default")
    for supplied, what in (
        ({actions.MAX_PARAGRAPHS: 10**6}, "a value above the range"),
        ({actions.MAX_PARAGRAPHS: -1}, "a value below the range"),
        ({actions.MAX_PARAGRAPHS: "3"}, "a value that is not a number"),
        ({"invented": 1}, "a parameter the action does not declare"),
    ):
        try:
            action.resolve(supplied)
        except react_config.RepairConfigError:
            continue
        faults.append(f"accepted {what}")
    record("check_01c_parameters_bounded", not faults, "; ".join(faults))


# --- 02 the decision point ----------------------------------------------------


def one_issue(reference: str = "p1#0", kind: str = "untranslated_residue"):
    return detector_base.Issue(
        kind=kind,
        page=1,
        paragraph_refs=(reference,),
        geometry=None,
        severity="high",
        evidence={"residue_ratio": 1.0, "excerpt": "The UNESCO Courier"},
        detector="untranslated_residue",
    )


def check_02a_decision_spectrum() -> None:
    """Positive/negative 2a: every shape a model can answer with, and one rule."""
    config = repair_config()
    issues = [one_issue()]
    offered = issues[0].id
    faults = []

    cases = (
        ("a legal reply", [decision_reply([offered])], True, 1),
        (
            "an action outside the vocabulary",
            [decision_reply([offered], action="delete_the_page")] * 2,
            False,
            2,
        ),
        (
            "a finding that was not offered",
            [decision_reply(["untranslated_residue:p9:p9#9"])] * 2,
            False,
            2,
        ),
        (
            "a parameter outside its range",
            [decision_reply([offered], parameters={actions.MAX_PARAGRAPHS: 10**6})] * 2,
            False,
            2,
        ),
        ("malformed JSON", ["not json at all", "still not json"], False, 2),
        (
            "a field nothing asked for",
            [json.dumps({"action": actions.NAME, "issue_ids": [offered],
                         "parameters": {}, "reason": "r", "extra": 1})] * 2,
            False,
            2,
        ),
    )
    for what, replies, should_act, expected_attempts in cases:
        engine = Engine(replies)
        client = decide.CachedDecisionClient(
            config,
            transport=decide.EngineTransport(engine),
            cache=NoCache(),
            working_dir=_tmp_root,
        )
        decision, _log = client.decide(issues)
        if decision.acts != should_act:
            faults.append(f"{what}: acts={decision.acts}, expected {should_act}")
        if decision.attempts != expected_attempts:
            faults.append(
                f"{what}: {decision.attempts} attempt(s), expected {expected_attempts}"
            )
        if not should_act and not decision.violations:
            faults.append(f"{what}: refused without recording why")
        if not should_act and len(engine.requests) > config.decide_max_attempts:
            faults.append(f"{what}: asked more than the declared attempt ceiling")

    # A reply that declines is a decision, not a violation: it costs one request
    # and applies nothing.
    engine = Engine([decision_reply([], action=react_config.NO_ACTION)])
    client = decide.CachedDecisionClient(
        config,
        transport=decide.EngineTransport(engine),
        cache=NoCache(),
        working_dir=_tmp_root,
    )
    declined, _log = client.decide(issues)
    if declined.acts or declined.refused:
        faults.append("a declining reply was not read as a decision to do nothing")
    if len(engine.requests) != 1:
        faults.append("a declining reply was asked for more than once")

    # A retry states the violation back rather than repeating the request.
    engine = Engine(["not json", decision_reply([offered])])
    client = decide.CachedDecisionClient(
        config,
        transport=decide.EngineTransport(engine),
        cache=NoCache(),
        working_dir=_tmp_root,
    )
    retried, _log = client.decide(issues)
    if not retried.acts:
        faults.append("a legal reply after a violation was not accepted")
    if len(engine.requests) != 2 or engine.requests[0] == engine.requests[1]:
        faults.append("the retry did not carry the violation back to the model")
    record("check_02a_decision_spectrum", not faults, "; ".join(faults))


def check_02b_decision_cached() -> None:
    """Positive 2b: the same findings twice cost one request."""
    config = repair_config()
    issues = [one_issue()]
    memory = Memory()
    faults = []
    engine = Engine([decision_reply([issues[0].id])])
    for _round in range(2):
        client = decide.CachedDecisionClient(
            config,
            transport=decide.EngineTransport(engine),
            cache=memory,
            working_dir=_tmp_root,
        )
        decision, _log = client.decide(issues)
        if not decision.acts:
            faults.append("a cached decision did not survive the round trip")
    if len(engine.requests) != 1:
        faults.append(f"{len(engine.requests)} request(s) for two identical decisions")

    # The key names the prompt file, so a reworded prompt is a different request.
    first = decide.cache_key(
        decide.load_prompt(decide.DECIDE_PROMPT, {"issues_block": "a", "actions_block": "b"}),
        "engine",
    )
    second = decide.cache_key(
        decide.load_prompt(decide.DECIDE_PROMPT, {"issues_block": "a", "actions_block": "c"}),
        "engine",
    )
    if first == second:
        faults.append("two different requests share one cache key")
    record("check_02b_decision_cached", not faults, "; ".join(faults))


def check_02c_prompts_are_files() -> None:
    """Negative 2c: no prompt text is written in the package."""
    faults = []
    for path in (DECIDE_PROMPT, TRANSLATE_PROMPT, GLOSSARY_PROMPT):
        if not path.is_file():
            faults.append(f"{path.name} is not beside the others in prompts/")
    # Every string literal in the package that is not a docstring is short: a
    # prompt is a file, and a paragraph of instruction to a model cannot hide in
    # a constant.
    for source in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        documented = set()
        for node in ast.walk(tree):
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ) and ast.get_docstring(node) is not None:
                documented.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in documented:
                continue
            if len(node.value) > 200:
                faults.append(
                    f"{source.name}:{node.lineno} carries a long string constant"
                )
    record("check_02c_prompts_are_files", not faults, "; ".join(faults))


# --- 03 the applicability filter ----------------------------------------------


def admits(text: str, label: str, ratio: float, carry_style: bool = False) -> str:
    action = repair_config().actions[actions.NAME]
    item = paragraph(text, label=label, carry_style=carry_style)
    issue = detector_base.Issue(
        kind="untranslated_residue",
        page=1,
        paragraph_refs=("p1#0",),
        geometry=None,
        severity="high",
        evidence={"residue_ratio": ratio},
        detector="untranslated_residue",
    )
    return actions.admits(issue, item, action, detector_base.rendered_text(item))


def check_03a_applicability_filter() -> None:
    """Positive/negative 3a: what the action may act on, at the boundary."""
    action = repair_config().actions[actions.NAME]
    bound = float(action.applicability[react_config.MIN_RATIO_KEY])
    orphan = action.applicability[react_config.ORPHAN_LABELS_KEY][0]
    minimum = int(action.applicability[react_config.MIN_CHARS_KEY])
    faults = []

    cases = (
        ("an orphan wholly in the source script", "The UNESCO Courier photo", orphan,
         1.0, actions.ACCEPTED),
        ("an orphan exactly at the share bound", "The UNESCO Courier photo", orphan,
         bound, actions.ACCEPTED),
        ("an orphan just below the share bound", "The UNESCO Courier photo", orphan,
         bound - 0.01, actions.REASON_RATIO),
        ("an orphan shorter than the floor", "a" * (minimum - 1), orphan, 1.0,
         actions.REASON_SHORT),
        ("a paragraph the translator was given", "Jim Al-Khalili and others",
         "plain text", 1.0, actions.REASON_LABEL),
    )
    for what, text, label, ratio, expected in cases:
        got = admits(text, label, ratio)
        if got != expected:
            faults.append(f"{what}: {got}, expected {expected}")

    # The two shapes the b8.1 report measured on the live document and called
    # names rather than defects. Both are plain text, so both are refused.
    for what, text, ratio in (
        ("an interview line keeping a personal name", TARGET_INTERVIEW, 0.8),
        ("a byline correctly left in its source script", "Jim Al-Khalili", 1.0),
    ):
        got = admits(text, "plain text", ratio)
        if got != actions.REASON_LABEL:
            faults.append(f"{what} was not refused: {got}")

    # A finding of a kind this action does not answer for is refused by the
    # controller before the paragraph is even resolved.
    if action.answers_for("fragment_cluster"):
        faults.append("the action claims to answer for a report-only kind")
    record("check_03a_applicability_filter", not faults, "; ".join(faults))


def check_03b_orphan_labels_are_general() -> None:
    """Negative 3b: the orphan label set names a parser class, not a publication."""
    action = repair_config().actions[actions.NAME]
    labels = action.applicability[react_config.ORPHAN_LABELS_KEY]
    faults = []
    if not labels:
        faults.append("the orphan label set is empty")
    helper = (
        ROOT
        / "babeldoc"
        / "format"
        / "pdf"
        / "document_il"
        / "utils"
        / "layout_helper.py"
    ).read_text(encoding="utf-8")
    for label in labels:
        if f'"{label}"' not in helper:
            faults.append(f"{label!r} is not a label the layout helper knows")
    record("check_03b_orphan_labels_are_general", not faults, "; ".join(faults))


# --- 04 the write-back --------------------------------------------------------


def check_04a_write_back_round_trip() -> None:
    """Positive 4a: a repaired paragraph survives the language's own round trip."""
    faults = []
    item = paragraph("credit line in the source script")
    if item.pdf_style is not None:
        faults.append("the built orphan carries a style of its own")
    if not writeback.can_write_back(item):
        faults.append("an orphan with styled characters was called unwritable")
    box_before = detector_base.box_tuple(item.box)
    vertical_before = item.vertical
    writeback.rebuild(item, TARGET_CAPTION)
    if detector_base.rendered_text(item) != TARGET_CAPTION:
        faults.append("the rebuilt paragraph does not render what was written")
    if detector_base.box_tuple(item.box) != box_before:
        faults.append("the write-back moved the paragraph's box")
    if item.vertical != vertical_before:
        faults.append("the write-back changed the orientation flag")

    docs = document([page([item])])
    converter = XMLConverter()
    once = converter.to_xml(docs)
    twice = converter.to_xml(converter.from_xml(once))
    if once != twice:
        faults.append("a repaired document does not survive its own serialisation")

    # A paragraph with nothing to take a style from is refused rather than
    # written into with None, which typesetting would drop in silence.
    styleless = il_version_1.PdfParagraph(
        box=il_version_1.Box(0.0, 0.0, 10.0, 10.0),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(unicode="x")
                )
            )
        ],
    )
    if writeback.can_write_back(styleless):
        faults.append("a paragraph with no style anywhere was called writable")
    record("check_04a_write_back_round_trip", not faults, "; ".join(faults))


def check_04b_font_is_registered() -> None:
    """Positive 4b: repaired characters carry a font the mapper will register.

    This is the whole of the font question. The mapper is constructed inside
    PDFCreater and its `add_font` runs when the PDF is written, which is after
    the hook this loop runs at, and what it registers is read off the characters
    the paragraphs are laid out as. So a repaired paragraph needs no rerun of
    anything -- it needs its characters to name a font the mapper has.
    """
    faults = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs = checkpoint_module.load_checkpoint(FIXTURE)
    directory = _tmp_root / "fonts"
    engine = Engine([], [])
    loop = build_loop(directory, docs, engine)
    mapper = loop._typesetting().font_mapper  # noqa: SLF001

    target = None
    for label, page_ in hitl.labeled_pages(docs):
        for index, item in enumerate(page_.pdf_paragraph or ()):
            if f"p{label}#{index}" == LIVE_REFERENCE:
                target = (page_, index, item)
    if target is None:
        record("check_04b_font_is_registered", False, f"{LIVE_REFERENCE} not in fixture")
        return
    page_, index, item = target
    writeback.rebuild(item, TARGET_CREDIT)
    laid_out = writeback.retypeset(loop._typesetting(), item, page_)  # noqa: SLF001
    if not laid_out:
        faults.append("the repaired paragraph laid out to nothing")
    else:
        used = mapper.get_used_font_ids(docs)
        registered = {name for name in used if name in mapper.fontid2fontpath}
        characters = [
            composition.pdf_character
            for composition in item.pdf_paragraph_composition
            if composition.pdf_character is not None
        ]
        if not characters:
            faults.append("the repaired paragraph carries no characters")
        for character_ in characters:
            font_id = character_.pdf_style.font_id
            if font_id not in registered:
                faults.append(f"{font_id} is not a font the mapper would register")
                break
        if item.vertical is not True:
            faults.append("laying out again cleared the orientation flag")
    record("check_04b_font_is_registered", not faults, "; ".join(faults))


# --- 05 the loop and its guards -----------------------------------------------


def residue_document(count: int = 3):
    """A page of orphans, each wholly in the source script."""
    return document(
        [
            page(
                [
                    paragraph(f"photo credit number {index} for the magazine")
                    for index in range(count)
                ]
            )
        ]
    )


def check_05a_loop_converges() -> None:
    """Positive 5a: a loop that repairs stops when there is nothing left."""
    docs = residue_document()

    class Decider(Engine):
        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            self.requests.append(text)
            if "Actions available" in text:
                ids = [
                    line.split('"')[1]
                    for line in text.splitlines()
                    if line.strip().startswith("- id:")
                ]
                return decision_reply(ids, parameters={actions.MAX_PARAGRAPHS: 5})
            return translation_reply(TARGET_CAPTION)

    engine = Decider([], [])
    loop = build_loop(_tmp_root / "converge", docs, engine)
    remaining = loop.run()
    report = report_of(loop)
    faults = []
    if remaining:
        faults.append(f"{len(remaining)} finding(s) left standing")
    if report["stopped_because"] != controller.STOP_NO_ISSUES:
        faults.append(f"stopped because {report['stopped_because']}")
    if report["conservation"]["verdict"] != controller.CONSERVED:
        faults.append("conservation was not reported as held")
    if report["applications"] != 3:
        faults.append(f"{report['applications']} paragraph(s) written, expected 3")
    first = report["iterations"][0]
    for key in ("detected", "decision", "executed", "recheck"):
        if key not in first:
            faults.append(f"the log omits {key}")
    if first.get("outcome") != controller.OUTCOME_ADVANCED:
        faults.append("a repairing iteration was not recorded as advancing")
    record("check_05a_loop_converges", not faults, "; ".join(faults))


def check_05b_rollback_on_no_progress() -> None:
    """Negative 5b: an iteration that does not reduce the count is undone."""
    docs = residue_document(2)
    before = XMLConverter().to_xml(docs)

    class Stubborn(Engine):
        """Renders every line into text that is still residue, so nothing improves."""

        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            self.requests.append(text)
            if "Actions available" in text:
                ids = [
                    line.split('"')[1]
                    for line in text.splitlines()
                    if line.strip().startswith("- id:")
                ]
                return decision_reply(ids, parameters={actions.MAX_PARAGRAPHS: 5})
            return translation_reply("another credit line in the source script")

    engine = Stubborn([], [])
    loop = build_loop(_tmp_root / "stubborn", docs, engine)
    logs: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record_):
            logs.append(record_.getMessage())

    logger = logging.getLogger("babeldoc.magazine.react.controller")
    handler = Capture(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        loop.run()
    finally:
        logger.removeHandler(handler)

    report = report_of(loop)
    faults = []
    if report["stopped_because"] != controller.STOP_NOT_CONVERGING:
        faults.append(f"stopped because {report['stopped_because']}")
    if report["iterations_run"] != 1:
        faults.append(f"{report['iterations_run']} iteration(s), expected 1")
    if report["applications"] != 0:
        faults.append("a rolled back iteration was counted as an application")
    outcomes = [item.get("outcome") for item in report["iterations"]]
    if controller.OUTCOME_ROLLED_BACK not in outcomes:
        faults.append(f"no iteration recorded a rollback: {outcomes}")
    rolled = report["iterations"][-1].get("rolled_back_refs")
    if not rolled:
        faults.append("the rollback did not name what it put back")
    if XMLConverter().to_xml(docs) != before:
        faults.append("the document is not what it was before the iteration")
    if report["conservation"]["changed_refs"]:
        faults.append("a rolled back run reports a changed paragraph")
    if not any("rolled back and stopped" in message for message in logs):
        faults.append("the rollback was not reported in the run log")
    record("check_05b_rollback_on_no_progress", not faults, "; ".join(faults))


def check_05c_ceiling_holds() -> None:
    """Negative 5c: the loop never runs past its declared iteration ceiling."""
    config = repair_config()
    # Enough orphans that one paragraph per iteration cannot finish them within
    # the ceiling, so what stops the loop is the ceiling and nothing else.
    docs = residue_document(config.max_iterations + 3)

    class OneAtATime(Engine):
        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            self.requests.append(text)
            if "Actions available" in text:
                ids = [
                    line.split('"')[1]
                    for line in text.splitlines()
                    if line.strip().startswith("- id:")
                ]
                return decision_reply(ids[:1], parameters={actions.MAX_PARAGRAPHS: 1})
            return translation_reply(TARGET_CAPTION)

    engine = OneAtATime([], [])
    loop = build_loop(_tmp_root / "ceiling", docs, engine)
    remaining = loop.run()
    report = report_of(loop)
    faults = []
    if report["iterations_run"] != config.max_iterations:
        faults.append(
            f"{report['iterations_run']} iteration(s) against a ceiling of "
            f"{config.max_iterations}"
        )
    if report["stopped_because"] != controller.STOP_CEILING:
        faults.append(f"stopped because {report['stopped_because']}")
    if not remaining:
        faults.append("the ceiling case finished the document, so it proves nothing")
    if report["applications"] != config.max_iterations:
        faults.append("the per-iteration parameter did not bound what was written")
    record("check_05c_ceiling_holds", not faults, "; ".join(faults))


def check_05d_untouched_paragraphs_are_byte_identical() -> None:
    """Negative 5d: nothing outside the repaired set changes, byte for byte."""
    docs = document(
        [
            page(
                [
                    paragraph("photo credit for the magazine cover"),
                    paragraph(TARGET_BODY, label="plain text",
                              carry_style=True),
                    paragraph("Jim Al-Khalili", label="plain text", carry_style=True),
                ]
            )
        ]
    )
    before = controller.paragraph_digests(docs)

    class Decider(Engine):
        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            self.requests.append(text)
            if "Actions available" in text:
                ids = [
                    line.split('"')[1]
                    for line in text.splitlines()
                    if line.strip().startswith("- id:")
                ]
                return decision_reply(ids, parameters={actions.MAX_PARAGRAPHS: 5})
            return translation_reply(TARGET_CAPTION)

    engine = Decider([], [])
    loop = build_loop(_tmp_root / "untouched", docs, engine)
    loop.run()
    after = controller.paragraph_digests(docs)
    report = report_of(loop)
    faults = []
    changed = {name for name in after if before.get(name) != after[name]}
    if changed != {"p1#0"}:
        faults.append(f"changed paragraphs were {sorted(changed)}, expected p1#0 alone")
    if report["conservation"]["changed_outside_touched"]:
        faults.append("the run reports a change outside what it repaired")
    if report["conservation"]["verdict"] != controller.CONSERVED:
        faults.append("conservation was not reported as held")
    if (
        report["conservation"]["paragraphs_before"]
        != report["conservation"]["paragraphs_after"]
    ):
        faults.append("the paragraph count moved")
    if report["conservation"]["pages_before"] != report["conservation"]["pages_after"]:
        faults.append("the page count moved")
    record("check_05d_untouched_paragraphs_are_byte_identical", not faults,
           "; ".join(faults))


def check_05e_no_engine_applies_nothing() -> None:
    """Negative 5e: with no engine configured the loop reports and changes nothing."""
    docs = residue_document(2)
    before = XMLConverter().to_xml(docs)
    config = Config(_tmp_root / "engineless", translator=None)
    loop = controller.RepairLoop(config, docs)
    remaining = loop.run()
    report = report_of(loop)
    faults = []
    if report["stopped_because"] != controller.STOP_NO_ENGINE:
        faults.append(f"stopped because {report['stopped_because']}")
    if XMLConverter().to_xml(docs) != before:
        faults.append("a run with no engine changed the document")
    if not remaining:
        faults.append("a run with no engine reported nothing left to repair")
    if (loop.working_dir / detectors.REPORT_NAME).exists() is False:
        faults.append("the detection sidecar was not written")
    record("check_05e_no_engine_applies_nothing", not faults, "; ".join(faults))


def check_05h_illegal_code_points() -> None:
    """Negative 5h: a document carrying text XML 1.0 refuses is still measurable.

    A real intermediate language holds control characters the parser will not
    accept, which is why the checkpoint serialisation escapes them. The
    conservation check reads that serialisation, so a document carrying such a
    character is compared rather than crashed on -- and the loop over it
    behaves as it does over any other.
    """
    faults = []
    docs = residue_document(2)
    # One control character, in a paragraph the action will not touch, which is
    # where one really occurs: text no stage rewrote.
    docs.page[0].pdf_paragraph.append(
        paragraph("a caption carrying \x01 a control character", label="plain text",
                  carry_style=True)
    )
    try:
        digests = controller.paragraph_digests(docs)
    except Exception as exc:  # noqa: BLE001 - the point of the assertion
        record("check_05h_illegal_code_points", False, f"digesting raised {exc!r}")
        return
    if len(digests) != 3:
        faults.append(f"{len(digests)} paragraph(s) digested, expected 3")

    class Decider(Engine):
        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            self.requests.append(text)
            if "Actions available" in text:
                ids = [
                    line.split('"')[1]
                    for line in text.splitlines()
                    if line.strip().startswith("- id:")
                ]
                return decision_reply(ids, parameters={actions.MAX_PARAGRAPHS: 5})
            return translation_reply(TARGET_CAPTION)

    loop = build_loop(_tmp_root / "illegal", docs, Decider([], []))
    loop.run()
    report = report_of(loop)
    if report["conservation"]["verdict"] != controller.CONSERVED:
        faults.append("conservation was not held over a document with such a character")
    if report["applications"] != 2:
        faults.append(f"{report['applications']} paragraph(s) written, expected 2")
    record("check_05h_illegal_code_points", not faults, "; ".join(faults))


def check_05i_failure_is_never_fatal() -> None:
    """Negative 5i: a loop that raises leaves the document and reports detection.

    The loop improves a finished translation; it is never a precondition for
    one. A run that cannot repair has to produce the document it would have
    produced with the switch down, rather than no document at all.
    """
    docs = residue_document(2)
    before = XMLConverter().to_xml(docs)

    class Broken(Engine):
        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            raise MemoryError("the transport is not the failure being simulated")

    config = Config(_tmp_root / "broken", translator=Broken([], []))
    directory = Path(config.get_working_file_path(detectors.REPORT_NAME)).parent
    faults = []

    # The decision point already tolerates a transport that raises, so the
    # failure is injected where nothing tolerates it: the digest of the document.
    original = controller.paragraph_digests
    controller.paragraph_digests = lambda _docs: (_ for _ in ()).throw(
        RuntimeError("digesting failed")
    )
    try:
        issues = controller.repair_document(config, docs)
    except Exception as exc:  # noqa: BLE001 - the point of the assertion
        controller.paragraph_digests = original
        record("check_05i_failure_is_never_fatal", False, f"the loop raised {exc!r}")
        return
    finally:
        controller.paragraph_digests = original

    if not issues:
        faults.append("the fallback reported no findings, so detection did not run")
    if XMLConverter().to_xml(docs) != before:
        faults.append("a failed loop left the document changed")
    if not (directory / detectors.REPORT_NAME).exists():
        faults.append("the detection sidecar was not written after the failure")
    if (directory / controller.REPORT_NAME).exists():
        faults.append("a failed loop wrote an account of a run it did not finish")
    record("check_05i_failure_is_never_fatal", not faults, "; ".join(faults))


def check_05f_ruling_reach_covers_the_action() -> None:
    """Positive 5f: a ruling whose only occurrence is on an orphan is counted."""
    config = Config(_tmp_root / "reach", magazine_hitl_apply=True)
    directory = Path(config.get_working_file_path(hitl.TRACKING_NAME)).parent
    with (directory / hitl.TRACKING_NAME).open("w", encoding="utf-8") as f:
        json.dump(
            {"page": [{"paragraph": [{"input": "a body paragraph",
                                      "pdf_unicode": "a body paragraph"}]}],
             "cross_page": [], "cross_column": []},
            f,
        )
    report = hitl._report(config)  # noqa: SLF001
    report[hitl.TERMS_SECTION] = {
        "glossary": hitl.DECISIONS_GLOSSARY,
        "entries": [{"source": "The UNESCO Courier", "target": TARGET_TITLE_PLAIN}],
    }
    faults = []
    hitl.after_translate(config)
    with (directory / hitl.REPORT_NAME).open(encoding="utf-8") as f:
        after_translate = json.load(f)
    if after_translate[hitl.TERMS_SECTION]["matches"][0]["matched_prompt_count"] != 0:
        faults.append("the term was counted before the repair path ran")

    hitl.after_repair(config, ["photo for The UNESCO Courier"])
    with (directory / hitl.REPORT_NAME).open(encoding="utf-8") as f:
        after_repair = json.load(f)
    entry = after_repair[hitl.TERMS_SECTION]["matches"][0]
    if entry["matched_prompt_count"] != 1:
        faults.append(
            f"a ruling reached by the repair path counted {entry['matched_prompt_count']}"
        )
    if after_repair[hitl.TERMS_SECTION].get(hitl.REPAIR_INPUTS_KEY) != 1:
        faults.append("the report does not say how many inputs the loop contributed")
    if hitl.MATCH_DEFINITION not in json.dumps(after_repair):
        faults.append("the report does not say what it counted")

    # With the ruling switch down the hook writes nothing.
    down = Config(_tmp_root / "reach_down", magazine_hitl_apply=False)
    quiet = Path(down.get_working_file_path(hitl.REPORT_NAME)).parent
    hitl.after_repair(down, ["anything"])
    if (quiet / hitl.REPORT_NAME).exists():
        faults.append("the hook wrote a report with the ruling switch down")
    record("check_05f_ruling_reach_covers_the_action", not faults, "; ".join(faults))


def check_05g_glossary_reaches_the_request() -> None:
    """Positive 5g: a ruled pair matching the line is in the request that renders it."""
    from babeldoc.glossary import Glossary
    from babeldoc.glossary import GlossaryEntry

    glossary = Glossary(
        name=hitl.DECISIONS_GLOSSARY,
        entries=[GlossaryEntry("The UNESCO Courier", TARGET_TITLE)],
    )
    engine = Engine([], [translation_reply(TARGET_CREDIT)])
    translator = actions.CachedOrphanTranslator(
        repair_config(),
        transport=decide.EngineTransport(engine),
        cache=NoCache(),
        language=LANGUAGE,
        glossaries=[glossary],
        working_dir=_tmp_root,
    )
    outcome = translator.translate("photo for The UNESCO Courier", "the page")
    faults = []
    if not outcome.accepted:
        faults.append(f"the line was not rendered: {outcome.reason}")
    if not engine.requests or TARGET_TITLE not in engine.requests[0]:
        faults.append("the ruled target is not in the request")
    if [["The UNESCO Courier", TARGET_TITLE]] != outcome.glossary_entries:
        faults.append(f"the run does not record what it carried: {outcome.glossary_entries}")

    # A pair whose source is not in the line is not carried.
    engine = Engine([], [translation_reply(TARGET_ANY)])
    translator = actions.CachedOrphanTranslator(
        repair_config(),
        transport=decide.EngineTransport(engine),
        cache=NoCache(),
        language=LANGUAGE,
        glossaries=[glossary],
        working_dir=_tmp_root,
    )
    other = translator.translate("an unrelated credit line here", "the page")
    if other.glossary_entries:
        faults.append("a pair that does not occur in the line was carried anyway")
    record("check_05g_glossary_reaches_the_request", not faults, "; ".join(faults))


# --- 06 the live evidence -----------------------------------------------------


def check_06a_live_repair() -> None:
    """Positive 6a: the loop repairs p6#15 on paragraphs a real run produced."""
    faults = []
    if not FIXTURE.is_file():
        record("check_06a_live_repair", False, f"{FIXTURE.name} is not in the tree")
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs = checkpoint_module.load_checkpoint(FIXTURE)
    before = controller.paragraph_digests(docs)

    class Decider(Engine):
        def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
            self.requests.append(text)
            if "Actions available" in text:
                ids = [
                    line.split('"')[1]
                    for line in text.splitlines()
                    if line.strip().startswith("- id:")
                ]
                return decision_reply(ids, parameters={actions.MAX_PARAGRAPHS: 8})
            return translation_reply(TARGET_CREDIT)

    engine = Decider([], [])
    loop = build_loop(_tmp_root / "live", docs, engine)
    loop.run()
    report = report_of(loop)
    touched = set(report["conservation"]["touched_refs"])
    if LIVE_REFERENCE not in touched:
        faults.append(f"{LIVE_REFERENCE} was not repaired; repaired {sorted(touched)}")
    for reference in NAME_REFERENCES:
        if reference in touched:
            faults.append(f"{reference} is a name and was rewritten anyway")
    rejections = {
        item["paragraph_ref"]: item["reason"]
        for iteration in report["iterations"]
        for item in iteration.get("applicability") or ()
    }
    for reference in NAME_REFERENCES:
        if rejections.get(reference) != actions.REASON_LABEL:
            faults.append(
                f"{reference} was refused for {rejections.get(reference)!r} rather "
                f"than for the label"
            )
    if report["conservation"]["verdict"] != controller.CONSERVED:
        faults.append("conservation was not reported as held on the live document")
    if report["conservation"]["changed_outside_touched"]:
        faults.append("a paragraph outside the repaired set changed")
    after = controller.paragraph_digests(docs)
    changed = {name for name in after if before.get(name) != after[name]}
    if changed != touched:
        faults.append(f"the document changed at {sorted(changed - touched)} as well")
    # The recheck has to show the repair, not merely that it happened.
    first = report["iterations"][0]
    if LIVE_REFERENCE not in json.dumps(first.get("resolved_ids") or []):
        faults.append("the recheck does not record the finding as resolved")
    record("check_06a_live_repair", not faults, "; ".join(faults))


def check_06b_evidence_is_current() -> None:
    """Positive 6b: the recorded evidence beside the gate says what the loop says."""
    faults = []
    for path in (FIXTURE_PROVENANCE, REPAIR_EVIDENCE):
        if not path.is_file():
            faults.append(f"{path.name} is not beside the gate")
    if faults:
        record("check_06b_evidence_is_current", False, "; ".join(faults))
        return
    with REPAIR_EVIDENCE.open(encoding="utf-8") as f:
        evidence = json.load(f)
    if evidence["conservation"]["verdict"] != controller.CONSERVED:
        faults.append("the recorded run did not conserve the document")
    if LIVE_REFERENCE not in evidence["conservation"]["touched_refs"]:
        faults.append(f"the recorded run did not repair {LIVE_REFERENCE}")
    rendered = evidence.get("rendered_after", {}).get(LIVE_REFERENCE, "")
    if detector_base.script_counts(rendered).get("han", 0) < 1:
        faults.append("the recorded repair did not leave target language text")
    with FIXTURE_PROVENANCE.open(encoding="utf-8") as f:
        provenance = json.load(f)
    labels = repair_config().actions[actions.NAME].applicability[
        react_config.ORPHAN_LABELS_KEY
    ]
    if sorted(provenance["orphan_labels"]) != sorted(labels):
        faults.append("the fixture was frozen against a different orphan label set")
    record("check_06b_evidence_is_current", not faults, "; ".join(faults))


# --- 07 the default -----------------------------------------------------------


def check_07_switch_down_run() -> None:
    """Positive/negative 7: the repair switch changes nothing it should not.

    Two real pipeline runs over every sample: one with detection on and one with
    detection and repair on. These runs translate nothing, so there is nothing
    for the loop to repair, and the property asserted is that turning the loop
    on costs the document nothing -- the same intermediate language and the same
    PDF -- while still leaving its own account of the run behind.
    """
    faults = []
    stem = checkpoint_module.checkpoint_stem("typesetting")
    for sample in sample_pdfs():
        detected = artifacts.get_artifacts(sample, "detected")
        repaired = artifacts.get_artifacts(sample, "repaired")
        left = detected.working_dir / f"{stem}.xml"
        right = repaired.working_dir / f"{stem}.xml"
        if not left.exists() or not right.exists():
            faults.append(f"{sample.stem}: a typesetting checkpoint is missing")
        # Debug ids are minted per run, so two runs of one pipeline over one
        # document never agree on them; everything else has to agree exactly.
        elif anonymous(left) != anonymous(right):
            faults.append(f"{sample.stem}: the intermediate language moved")
        if detected.mono_pdf and repaired.mono_pdf:
            proc = subprocess.run(  # noqa: S603
                [
                    PYTHON,
                    str(ROOT / "tools" / "render_diff.py"),
                    str(detected.mono_pdf),
                    str(repaired.mono_pdf),
                    "--out",
                    str(_tmp_root / f"render_{sample.stem}"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                faults.append(f"{sample.stem}: the render differs, exit={proc.returncode}")
        report = repaired.working_dir / controller.REPORT_NAME
        if not report.exists():
            faults.append(f"{sample.stem}: the loop left no account of itself")
            continue
        with report.open(encoding="utf-8") as f:
            written = json.load(f)
        if written["conservation"]["verdict"] != controller.CONSERVED:
            faults.append(f"{sample.stem}: conservation was not held")
        if written["applications"]:
            faults.append(f"{sample.stem}: a run that translated nothing repaired something")
        if (detected.working_dir / controller.REPORT_NAME).exists():
            faults.append(f"{sample.stem}: the loop wrote a report with its switch down")
    record("check_07_switch_down_run", not faults, "; ".join(faults[:4]))


# Identities the pipeline mints afresh on every run, renumbered by first sight
# rather than blanked so that two runs that group paragraphs differently still
# compare unequal.
_MINTED_ID = re.compile(r'(debug_id|chainId)="([^"]*)"')


def anonymous(path: Path) -> str:
    seen: dict[tuple[str, str], int] = {}

    def rename(match: re.Match) -> str:
        key = (match.group(1), match.group(2))
        number = seen.setdefault(key, len(seen))
        return f'{match.group(1)}="#{number}"'

    return _MINTED_ID.sub(rename, path.read_text(encoding="utf-8"))


def sample_pdfs() -> list[Path]:
    from babeldoc.magazine import corpus

    manifest = corpus.load_manifest()
    return [ROOT / "examples" / "input" / entry["file"] for entry in manifest["samples"]]


# --- 08 the scope -------------------------------------------------------------


def check_08a_no_vocabulary_literals() -> None:
    """Negative 8a: no page type, profile or publication is named in the package."""
    from babeldoc.magazine.taxonomy import load_taxonomy

    taxonomy = load_taxonomy()
    names = set(taxonomy.names())
    profiles = {
        str(page_type.policy.get(detector_base.REPAIR_PROFILE_POLICY_FLAG))
        for page_type in taxonomy.page_types
        if page_type.policy.get(detector_base.REPAIR_PROFILE_POLICY_FLAG)
    }
    publications = {"unesco", "courier", "vogue", "aramco", "cern"}
    faults = []
    for source in sorted(PACKAGE.glob("*.py")):
        text = source.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if node.value in names:
                faults.append(f"{source.name}:{node.lineno} names page type {node.value!r}")
            if node.value in profiles:
                faults.append(f"{source.name}:{node.lineno} names profile {node.value!r}")
        for word in publications:
            if word in text.lower():
                faults.append(f"{source.name} names {word!r}")
    record("check_08a_no_vocabulary_literals", not faults, "; ".join(faults))


def check_08b_upstream_scope() -> None:
    """Negative 8b: this batch touches no upstream file at all."""
    faults = []
    for path in sorted(changed_paths()):
        if path in ALLOWED_FILES or path.startswith(ALLOWED_PREFIXES):
            continue
        faults.append(f"{path} is outside what this batch may change")
    for path in READ_ONLY:
        if path in changed_paths():
            faults.append(f"{path} is ground truth and was changed")
    record("check_08b_upstream_scope", not faults, "; ".join(faults))


def check_08c_ascii_prose() -> None:
    """Negative 8c: the package and its configuration are written in English."""
    faults = []
    for path in [*sorted(PACKAGE.glob("*.py")), ROOT / CONFIG, DECIDE_PROMPT,
                 TRANSLATE_PROMPT, GLOSSARY_PROMPT]:
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{path.name}:{number} is not ASCII")
                break
    record("check_08c_ascii_prose", not faults, "; ".join(faults))


def check_08d_no_request_path() -> None:
    """Negative 8d: the package reaches a model through the run's engine alone."""
    faults = []
    banned = ("requests", "httpx", "urllib", "openai", "socket", "aiohttp")
    for source in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in banned:
                    faults.append(f"{source.name}:{node.lineno} imports {name}")
    record("check_08d_no_request_path", not faults, "; ".join(faults))


def check_08e_default_is_down() -> None:
    """Negative 8e: with the repair switch absent the detection pass is unchanged."""
    docs = residue_document(2)
    before = XMLConverter().to_xml(docs)
    config = Config(
        _tmp_root / "default_down", translator=Engine([], []), magazine_repair=False
    )
    directory = Path(config.get_working_file_path(detectors.REPORT_NAME)).parent
    issues = detectors.detect_issues(config, docs)
    faults = []
    if not issues:
        faults.append("the detection pass found nothing, so it proves nothing")
    if (directory / controller.REPORT_NAME).exists():
        faults.append("the loop wrote a report with its switch down")
    if not (directory / detectors.REPORT_NAME).exists():
        faults.append("the detection sidecar was not written")
    if XMLConverter().to_xml(docs) != before:
        faults.append("the detection pass changed the document")
    record("check_08e_default_is_down", not faults, "; ".join(faults))


def check_08f_registered() -> None:
    """Positive 8f: the waiver and the registry say what this batch did."""
    faults = []
    waivers = (ROOT / "WAIVERS.md").read_text(encoding="utf-8")
    if controller.SWITCH not in waivers:
        faults.append(f"{controller.SWITCH} is not registered as a waiver")
    upstream = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    if "react" not in upstream:
        faults.append("the coupling registry does not name this package")
    plan = ROOT / "plans" / "PLAN_B8.md"
    if not plan.is_file():
        faults.append("the plan is not in the tree")
    record("check_08f_registered", not faults, "; ".join(faults))


# --- 09 the sweep -------------------------------------------------------------


def check_09_sweep() -> None:
    """Positive 9: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_09_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_09_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks = [
        check_01a_config_bounds,
        check_01b_config_negative_probes,
        check_01c_parameters_bounded,
        check_02a_decision_spectrum,
        check_02b_decision_cached,
        check_02c_prompts_are_files,
        check_03a_applicability_filter,
        check_03b_orphan_labels_are_general,
        check_04a_write_back_round_trip,
        check_04b_font_is_registered,
        check_05a_loop_converges,
        check_05b_rollback_on_no_progress,
        check_05c_ceiling_holds,
        check_05d_untouched_paragraphs_are_byte_identical,
        check_05e_no_engine_applies_nothing,
        check_05h_illegal_code_points,
        check_05i_failure_is_never_fatal,
        check_05f_ruling_reach_covers_the_action,
        check_05g_glossary_reaches_the_request,
        check_06a_live_repair,
        check_06b_evidence_is_current,
        check_07_switch_down_run,
        check_08a_no_vocabulary_literals,
        check_08b_upstream_scope,
        check_08c_ascii_prose,
        check_08d_no_request_path,
        check_08e_default_is_down,
        check_08f_registered,
        check_09_sweep,
    ]
    for check in checks:
        if harness.FAST_TIER and check.__name__ in PIPELINE_TIER:
            skip(check.__name__)
            continue
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(check.__name__, False, f"raised {exc!r}")
    print(f"\nspec_check_b8_2: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    _timer.write()
    _timer.print_summary()
    artifacts.write_stats("spec_check_b8_2")
    artifacts.print_stats("spec_check_b8_2")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
