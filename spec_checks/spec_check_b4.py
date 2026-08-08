"""Gate script for batch B4.1 (chain signals, builder, IL chain writing).

Run from the repository root:

    python spec_checks/spec_check_b4.py

Exit code 0 when every assertion in plans/PLAN_B4.md passes, 1 otherwise.

Needs no API key and makes no network request: chain detection is deterministic
geometry, and the pipeline runs it with skip_translation.

The assertions this batch exists for are 01 and 02. 01 is the shape of what was
written: an id appears on a paragraph exactly when a scored boundary linked it,
indices run from zero without a gap, and a chain walks consecutive pages. 02 is
what was not written: the stage is handed the document the classifier produced
and hands back the same document with two attributes more, so the checkpoints
either side of it are compared field by field and only the chain pair may
differ. Those two together say the stage writes the chains it found and nothing
else.

04 is a weight structure assertion rather than a corpus measurement. The page
level prior is soft by design, so a boundary carrying every continuity signal at
full strength has to survive every prior firing against it; the gate proves that
holds for the shipped weights and that the loader refuses a weight set where it
does not.

05 scores the detector against ``corpus/chain_labels.user.json``. That file is
the corpus owner's to write and is empty until they do, so the assertion reports
SKIPPED rather than passing vacuously.

Tiers: assertions 01, 02, 05, 06 and 08b need a pipeline run and belong to the
pipeline tier; the rest are static or synthetic. Assertion 07 is the full sweep
and is suppressed when the runner is already performing one.
"""

from __future__ import annotations

import ast
import copy
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.chain_builder import REPORT_NAME  # noqa: E402
from babeldoc.magazine.chain_builder import ChainBuilder  # noqa: E402
from babeldoc.magazine.chain_signals import SIGNAL_NAMES  # noqa: E402
from babeldoc.magazine.chain_signals import ChainConfigError  # noqa: E402
from babeldoc.magazine.chain_signals import combine  # noqa: E402
from babeldoc.magazine.chain_signals import evaluate_boundary  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.chain_signals import positive_weight  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b4.1"

PYTHON = sys.executable

CHAIN_CONFIG_PATH = ROOT / "configs" / "chain_detection.json"
CHAIN_LABELS_PATH = corpus.CHAIN_LABELS_PATH
OUTPUT_DIR = ROOT / "examples" / "output" / "b4"

# The two modules this batch adds, which are the ones the page type name scan
# and the B1 consumer registration apply to.
NEW_MODULES = (
    "babeldoc/magazine/chain_signals.py",
    "babeldoc/magazine/chain_builder.py",
)

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = (
    "check_01_chain_shape",
    "check_02_conservation",
    "check_05_label_agreement",
    "check_06_determinism",
    "check_08b_switch_off_render",
)

# The paragraph level fields B1 declared. The switch-off assertion is the B2.2
# assertion 09 continued: with the switch down not one of them may appear.
PARAGRAPH_FIELD_ATTRIBUTES = (
    "chainId",
    "chainIndex",
    "dropCapCandidate",
    "dropCapDecision",
    "segmentSentenceStart",
    "segmentSentenceEnd",
)

# The pair this batch is allowed to start writing.
CHAIN_FIELDS = ("chain_id", "chain_index")

# Paths this batch may change, per PLAN_B4 negative assertion 11.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "tools/",
    "spec_checks/",
    "plans/",
)
ALLOWED_FILES = {
    "corpus/chain_labels.user.json",
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
}
# The only upstream files this batch hooks into.
ALLOWED_UPSTREAM = {
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/format/pdf/translation_config.py",
}

# Trees and root documents owned by the magazine extension; the upstream scope
# assertion ignores them.
PROJECT_OWNED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "corpus/",
    "examples/",
    "plans/",
    "prompts/",
    "spec_checks/",
    "tools/",
)
PROJECT_OWNED_FILES = {"CLAUDE.md", "UPSTREAM_DIFF.md", "WAIVERS.md"}

# Files this batch adds or edits that must stay free of CJK.
CJK_SCAN_FILES = (
    *NEW_MODULES,
    "spec_checks/spec_check_b4.py",
    "configs/chain_detection.json",
    "corpus/chain_labels.user.json",
)
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# A credential in the diff would mean this batch shipped one. The scan looks for
# the shapes a key is written in rather than for one particular provider.
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token)\b\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']"),
)

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b4_"))
_timer = harness.Timer("spec_check_b4")


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


def skip(name: str, detail: str) -> None:
    print(f"SKIPPED: {detail} :: {name}")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def git_output(args: list[str]) -> tuple[int, str]:
    # Decoded explicitly: a diff carries whatever bytes the files carry, and the
    # platform default encoding is not required to be able to read them.
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def batch_tag_exists() -> bool:
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{BATCH_TAG}^{{commit}}"])
    return code == 0


def batch_revisions() -> list[str]:
    """Revision arguments selecting the delta this batch introduced."""
    return [f"{BATCH_TAG}^", BATCH_TAG] if batch_tag_exists() else ["HEAD"]


def changed_files() -> set[str]:
    _, listing = git_output(["diff", "--name-only", *batch_revisions()])
    return {path for path in (line.strip() for line in listing.splitlines()) if path}


def read_checkpoint(path: Path) -> il_version_1.Document:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return XMLConverter().read_xml(str(path))


def sample_pdfs() -> list[Path]:
    manifest = corpus.load_manifest()
    return [ROOT / "examples" / "input" / e["file"] for e in manifest["samples"]]


def chained_runs() -> dict[str, dict]:
    """The chain-detecting run of every corpus sample, keyed by file stem."""
    runs: dict[str, dict] = {}
    for pdf in sample_pdfs():
        built = artifacts.get_artifacts(pdf, "chained")
        work = built.working_dir
        report_path = work / REPORT_NAME
        runs[pdf.stem] = {
            "file": pdf.name,
            "working_dir": work,
            "mono": built.mono_pdf,
            "report": json.loads(report_path.read_text(encoding="utf-8"))
            if report_path.exists()
            else None,
        }
    return runs


def checkpoint_of(working_dir: Path, stage: str) -> Path | None:
    from babeldoc.magazine.checkpoint import checkpoint_stem

    path = working_dir / f"{checkpoint_stem(stage)}.xml"
    return path if path.exists() else None


# --- 01 ---------------------------------------------------------------------


def check_01_chain_shape(runs: dict[str, dict]) -> None:
    """Positive 1: an id marks a linked endpoint, and a chain is a page walk."""
    id_problems: list[str] = []
    index_problems: list[str] = []
    page_problems: list[str] = []
    written = 0

    for stem, run in runs.items():
        report = run["report"]
        checkpoint = checkpoint_of(run["working_dir"], "chain_builder")
        if report is None or checkpoint is None:
            id_problems.append(f"{stem}: no report or checkpoint")
            continue
        docs = read_checkpoint(checkpoint)

        # Paragraphs the report says were linked, against paragraphs carrying an id.
        expected: set[str] = set()
        for entry in report["boundaries"]:
            if entry.get("linked"):
                expected.add(entry["tail_debug_id"])
                expected.add(entry["head_debug_id"])

        by_chain: dict[str, list[tuple[int, int, str]]] = {}
        carrying: set[str] = set()
        for page in docs.page:
            for paragraph in page.pdf_paragraph:
                if paragraph.chain_id is None and paragraph.chain_index is None:
                    continue
                if paragraph.chain_id is None or paragraph.chain_index is None:
                    index_problems.append(f"{stem}: half a chain pair written")
                    continue
                carrying.add(paragraph.debug_id)
                by_chain.setdefault(paragraph.chain_id, []).append(
                    (paragraph.chain_index, page.page_number, paragraph.debug_id)
                )
        written += len(carrying)
        if carrying != expected:
            id_problems.append(
                f"{stem}: carrying-but-not-linked={sorted(carrying - expected)[:3]} "
                f"linked-but-unmarked={sorted(expected - carrying)[:3]}"
            )

        for chain_id, members in by_chain.items():
            members.sort()
            indices = [index for index, _, _ in members]
            if indices != list(range(len(members))):
                index_problems.append(f"{stem}/{chain_id}: indices {indices}")
            pages = [page for _, page, _ in members]
            if any(b - a != 1 for a, b in zip(pages, pages[1:], strict=False)):
                page_problems.append(f"{stem}/{chain_id}: pages {pages}")
            if len(members) < 2:
                index_problems.append(f"{stem}/{chain_id}: chain of one")

    record(
        "01a an id is carried by exactly the endpoints of the linked boundaries",
        not id_problems,
        f"problems={id_problems[:3]} paragraphs_marked={written}",
    )
    record(
        "01b chain indices run from zero without a gap",
        not index_problems,
        f"problems={index_problems[:3]}",
    )
    record(
        "01c members of a chain sit on consecutive pages",
        not page_problems,
        f"problems={page_problems[:3]}",
    )


def check_01d_closure_shape() -> None:
    """Positive 1, on a document built to produce a chain longer than an edge.

    01a to 01c read the corpus, and the corpus may hand this batch no linked
    boundary at all; passing on an empty set says nothing about the shape of a
    chain. Here three pages are built to link end to end, with the middle page
    carrying the one paragraph that both resumes and hands on, which is the only
    way two edges meet and therefore the only path that produces a chain of more
    than two. The indices, the page walk and the closure are read off that.
    """
    from babeldoc.magazine.chain_builder import _chains_from

    config = load_chain_config()
    pages = [
        _synthetic_page(0, _TAIL_TEXT, at_bottom=True),
        _synthetic_page(1, _HEAD_TEXT, at_bottom=True),
        _synthetic_page(2, _HEAD_TEXT, at_bottom=False),
    ]
    verdicts = [
        evaluate_boundary(pages[i], pages[i + 1], i, i + 1, _policy(), config)
        for i in range(len(pages) - 1)
    ]
    chains = _chains_from(verdicts)
    for chain in chains:
        for index, paragraph in enumerate(chain):
            paragraph.chain_id = "synthetic"
            paragraph.chain_index = index

    linked = [v.linked for v in verdicts]
    members = [p.debug_id for p in chains[0]] if chains else []
    indices = [p.chain_index for p in chains[0]] if chains else []
    record(
        "01d two linked boundaries meeting at one paragraph close into one chain",
        all(linked)
        and len(chains) == 1
        and members == ["p0", "p1", "p2"]
        and indices == [0, 1, 2],
        f"linked={linked} chains={len(chains)} members={members} indices={indices}",
    )


# --- 02 ---------------------------------------------------------------------


def _paragraph_fingerprint(paragraph: il_version_1.PdfParagraph) -> dict:
    """Every paragraph field except the pair this stage may write.

    The compositions are included: they hold the text and the geometry, which is
    the bulk of what a stage could damage, and comparing them is what makes this
    a conservation assertion rather than an attribute spot check.
    """
    return {
        name: getattr(paragraph, name)
        for name in paragraph.__dataclass_fields__
        if name not in CHAIN_FIELDS
    }


def check_02_conservation(runs: dict[str, dict]) -> None:
    """Positive 2: the stage adds two attributes and changes nothing else.

    The comparison is between the checkpoint written just before the stage and
    the one written just after it, inside a single run. Two separate runs would
    not do: paragraph debug ids are drawn at random, so a difference between
    runs proves nothing about this stage.
    """
    problems: list[str] = []
    compared = 0
    for stem, run in runs.items():
        before_path = checkpoint_of(run["working_dir"], "page_classifier")
        after_path = checkpoint_of(run["working_dir"], "chain_builder")
        if before_path is None or after_path is None:
            problems.append(f"{stem}: missing a checkpoint either side of the stage")
            continue
        before, after = read_checkpoint(before_path), read_checkpoint(after_path)
        if len(before.page) != len(after.page):
            problems.append(
                f"{stem}: page count {len(before.page)} -> {len(after.page)}"
            )
            continue
        if before.total_pages != after.total_pages:
            problems.append(f"{stem}: total_pages changed")
        for page_a, page_b in zip(before.page, after.page, strict=True):
            if len(page_a.pdf_paragraph) != len(page_b.pdf_paragraph):
                problems.append(
                    f"{stem} page {page_a.page_number}: paragraph count "
                    f"{len(page_a.pdf_paragraph)} -> {len(page_b.pdf_paragraph)}"
                )
                continue
            for name in (
                "page_number",
                "page_kind",
                "page_kind_conf",
                "page_kind_source",
            ):
                if getattr(page_a, name) != getattr(page_b, name):
                    problems.append(f"{stem} page {page_a.page_number}: {name} changed")
            for para_a, para_b in zip(
                page_a.pdf_paragraph, page_b.pdf_paragraph, strict=True
            ):
                compared += 1
                if _paragraph_fingerprint(para_a) != _paragraph_fingerprint(para_b):
                    problems.append(
                        f"{stem} page {page_a.page_number}: paragraph "
                        f"{para_a.debug_id} changed outside the chain pair"
                    )
                if para_a.chain_id is not None or para_a.chain_index is not None:
                    problems.append(
                        f"{stem}: the classifier checkpoint already carries a chain"
                    )
    record(
        "02 the stage writes only the chain pair and conserves everything else",
        not problems and compared > 0,
        f"paragraphs={compared} problems={problems[:3]}",
    )


# --- 03 and 04 --------------------------------------------------------------


_FONT = il_version_1.PdfFont(font_id="F0", name="ABCDEF+TestFace-Regular")

# Continuation text: it fills its measure and stops without a sentence ender, so
# every continuity signal the geometry can supply fires on it.
_TAIL_TEXT = "the sentence continues past the foot of this page and"
_HEAD_TEXT = "resumes here at the head of the next one without a break"


def _synthetic_page(number: int, text: str, at_bottom: bool) -> il_version_1.Page:
    """One page carrying a single paragraph built to look like running text.

    Everything the signals read is set deliberately: two lines of equal width,
    so the measure equals the last line's width and the fill ratio is exactly
    one; a last line that stops mid sentence; one family at one size; the
    running text label; and a position at the foot or the head of the measure.
    """
    characters = []
    for row, y in enumerate((120.0, 100.0) if at_bottom else (700.0, 680.0)):
        for column, letter in enumerate(text):
            characters.append(
                il_version_1.PdfCharacter(
                    # Only the last line's text is read, so the line above it is
                    # filled with a placeholder of the same width.
                    char_unicode=letter if row else "x",
                    box=il_version_1.Box(
                        x=50.0 + column * 5.0,
                        y=y,
                        x2=55.0 + column * 5.0,
                        y2=y + 10.0,
                    ),
                )
            )
    paragraph = il_version_1.PdfParagraph(
        box=il_version_1.Box(
            x=50.0,
            y=100.0 if at_bottom else 680.0,
            x2=50.0 + len(text) * 5.0,
            y2=130.0 if at_bottom else 710.0,
        ),
        pdf_style=il_version_1.PdfStyle(font_id="F0", font_size=10.0),
        layout_label="plain text",
        debug_id=f"p{number}",
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    pdf_character=characters
                )
            )
        ],
    )
    return il_version_1.Page(
        page_number=number,
        cropbox=il_version_1.Cropbox(
            box=il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
        ),
        pdf_font=[_FONT],
        pdf_paragraph=[paragraph],
        page_kind="synthetic",
        page_kind_conf=1.0,
    )


def _synthetic_pair(
    tail_text: str = _TAIL_TEXT, head_text: str = _HEAD_TEXT
) -> tuple[il_version_1.Page, il_version_1.Page]:
    """Two pages built to carry full continuity evidence."""
    return (
        _synthetic_page(0, tail_text, at_bottom=True),
        _synthetic_page(1, head_text, at_bottom=False),
    )


def _policy(eligible: bool = True, starts: bool = False):
    def lookup(_kind):
        return {
            "chain_eligible": eligible,
            "translate": True,
            "starts_article": starts,
            "repair_profile": "flow",
        }

    return lookup


def check_03_eligibility_mask() -> None:
    """Positive 3: a page the vocabulary excludes takes its boundary out of scoring."""
    config = load_chain_config()
    tail, head = _synthetic_pair()

    scored = evaluate_boundary(tail, head, 0, 1, _policy(eligible=True), config)
    masked = evaluate_boundary(tail, head, 0, 1, _policy(eligible=False), config)

    def mixed(kind):
        # Only the head page is excluded, which must be enough on its own.
        return {
            "chain_eligible": kind != "excluded",
            "translate": True,
            "starts_article": False,
            "repair_profile": "flow",
        }

    head_excluded = copy.deepcopy(head)
    head_excluded.page_kind = "excluded"
    one_sided = evaluate_boundary(tail, head_excluded, 0, 1, mixed, config)

    record(
        "03a the same boundary scores when both pages are chain eligible",
        scored.eligible and scored.score is not None,
        f"score={scored.score} values={scored.values}",
    )
    record(
        "03b an ineligible page leaves the boundary unscored",
        not masked.eligible
        and masked.score is None
        and not masked.linked
        and all(value is None for value in masked.values.values()),
        f"reason={masked.reason} score={masked.score}",
    )
    record(
        "03c one ineligible page of the two is enough to mask the boundary",
        not one_sided.eligible and not one_sided.linked,
        f"reason={one_sided.reason}",
    )


def check_04_evidence_beats_prior() -> None:
    """Positive 4: full paragraph level evidence survives every prior against it."""
    config = load_chain_config()

    full = {name: 0.0 if name == "opener_prior" else 1.0 for name in SIGNAL_NAMES}
    against = dict.fromkeys(SIGNAL_NAMES, 1.0)
    record(
        "04a the shipped weights let complete evidence outscore every prior",
        combine(against, config) >= config["link_min_score"],
        f"with_prior={combine(against, config):.3f} without={combine(full, config):.3f} "
        f"link_min_score={config['link_min_score']}",
    )

    # The same property end to end: the head page is declared to be where an
    # article starts, at full confidence, and the boundary still links.
    tail, head = _synthetic_pair()
    conflicted = evaluate_boundary(tail, head, 0, 1, _policy(starts=True), config)
    quiet = evaluate_boundary(tail, head, 0, 1, _policy(starts=False), config)
    record(
        "04b a boundary carrying full evidence links despite the opener prior",
        conflicted.linked and quiet.linked,
        f"with_prior={conflicted.score} without={quiet.score} "
        f"values={conflicted.values}",
    )
    record(
        "04c the prior is felt at all, so 04b is not vacuous",
        conflicted.score < quiet.score and conflicted.values["opener_prior"] > 0,
        f"with_prior={conflicted.score} without={quiet.score}",
    )

    # A weight set in which the prior can overrule complete evidence is refused
    # at load rather than shipped.
    raw = json.loads(CHAIN_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["weight_opener_prior"] = -1.0
    raw["link_min_score"] = 0.9
    broken = _tmp_root / "overruling_prior.json"
    broken.write_text(json.dumps(raw), encoding="utf-8")
    load_chain_config.cache_clear()
    try:
        load_chain_config(str(broken))
        refused = False
    except ChainConfigError:
        refused = True
    finally:
        load_chain_config.cache_clear()
    record(
        "04d a weight set where the prior overrules full evidence is refused",
        refused,
        f"positive_weight={positive_weight(config)}",
    )


# --- 05 ---------------------------------------------------------------------


def check_05_label_agreement(runs: dict[str, dict]) -> None:
    """Positive 5: the detector agrees with the adjudicated boundaries."""
    name = "05 adjudicated boundaries agree with the detector"
    if not CHAIN_LABELS_PATH.exists():
        skip(name, "no boundary ground truth file")
        return
    labels = corpus.load_chain_labels()
    errors = corpus.validate_chain_labels(labels)
    if errors:
        record(name, False, f"ground truth is malformed: {errors[:3]}")
        return
    labelled = sum(len(entries) for entries in labels.values())
    if not labelled:
        skip(name, "boundary ground truth is empty; the corpus owner writes it")
        return

    config = load_chain_config()
    by_file = {run["file"]: run for run in runs.values()}
    hits = total = 0
    misses: list[str] = []
    for file_name, entries in labels.items():
        run = by_file.get(file_name)
        if run is None or run["report"] is None:
            misses.append(f"{file_name}: no run")
            continue
        verdicts = {
            entry["boundary"]: bool(entry.get("linked"))
            for entry in run["report"]["boundaries"]
        }
        for key, entry in entries.items():
            if key not in verdicts:
                misses.append(f"{file_name} {key}: boundary absent from the report")
                continue
            total += 1
            if verdicts[key] == entry["link"]:
                hits += 1
            else:
                misses.append(f"{file_name} {key}: want {entry['link']}")
    rate = hits / total if total else 0.0
    record(
        name,
        total > 0 and rate >= config["boundary_agreement_min"],
        f"agreement={rate:.3f} ({hits}/{total}) "
        f"min={config['boundary_agreement_min']} misses={misses[:5]}",
    )


# --- 06 ---------------------------------------------------------------------


class _StubConfig:
    """The little of a TranslationConfig the stage reads, pointed at a temp dir."""

    def __init__(self, working_dir: Path):
        self._working_dir = working_dir
        self.split_strategy = None

    def get_working_file_path(self, name: str) -> str:
        self._working_dir.mkdir(parents=True, exist_ok=True)
        return str(self._working_dir / name)


def check_06_determinism(runs: dict[str, dict]) -> None:
    """Positive 6: two runs partition the same paragraphs the same way."""
    problems: list[str] = []
    checked = 0
    for stem, run in runs.items():
        source = checkpoint_of(run["working_dir"], "page_classifier")
        if source is None:
            problems.append(f"{stem}: no classifier checkpoint")
            continue

        def partition(
            index: int, path: Path = source, key: str = stem
        ) -> list[list[str]]:
            docs = read_checkpoint(path)
            ChainBuilder(_StubConfig(_tmp_root / f"det_{key}_{index}")).process(docs)
            chains: dict[str, list[tuple[int, str]]] = {}
            for page in docs.page:
                for paragraph in page.pdf_paragraph:
                    if paragraph.chain_id is None:
                        continue
                    chains.setdefault(paragraph.chain_id, []).append(
                        (paragraph.chain_index, paragraph.debug_id)
                    )
            # Ids may differ between runs; the membership and the order may not.
            return sorted(
                [debug_id for _, debug_id in sorted(members)]
                for members in chains.values()
            )

        first, second = partition(0), partition(1)
        checked += 1
        if first != second:
            problems.append(f"{stem}: {first} != {second}")
    record(
        "06 repeated runs produce the same chain membership and order",
        not problems and checked > 0,
        f"samples={checked} problems={problems[:2]}",
    )


# --- 07 ---------------------------------------------------------------------


def check_07_sweep() -> None:
    """Positive 7: the full sweep is green."""
    name = "07 the full run_all sweep is green"
    if NESTED_SUPPRESSED:
        print(f"SKIPPED: nested run suppressed :: {name}")
        return
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "run_all.full.log").write_text(proc.stdout, encoding="utf-8")
    failures = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith("[FAIL]")
    ]
    record(
        name,
        proc.returncode == 0 and not failures,
        f"exit={proc.returncode} failures={failures[:5]}",
    )


# --- 08 ---------------------------------------------------------------------


def check_08a_switch_default() -> None:
    """Negative 8: the switch is off unless a caller asks for it."""
    from babeldoc.format.pdf.translation_config import TranslationConfig

    signature = __import__("inspect").signature(TranslationConfig.__init__)
    parameter = signature.parameters.get("magazine_chain_detect")
    record(
        "08a the chain switch exists and defaults to False",
        parameter is not None and parameter.default is False,
        f"default={parameter.default if parameter else 'absent'}",
    )


def check_08b_switch_off_render(runs: dict[str, dict]) -> None:
    """Negative 8: with the switch down nothing is written and nothing moves."""
    hits: list[str] = []
    scanned = 0
    for pdf in sample_pdfs():
        for mode in ("stages", "classified"):
            built = artifacts.get_artifacts(pdf, mode)
            for path in sorted(built.working_dir.glob("checkpoint.*.xml")):
                scanned += 1
                text = path.read_text(encoding="utf-8")
                hits.extend(
                    f"{pdf.stem}/{mode}/{path.name}: {needle}"
                    for needle in PARAGRAPH_FIELD_ATTRIBUTES
                    if needle in text
                )
    record(
        "08b no paragraph level field is written while the switch is down",
        not hits and scanned > 0,
        f"scanned={scanned} hits={hits[:3]}",
    )

    # Turning the switch on must not move a pixel: the stage annotates the IL
    # and nothing downstream of it reads the annotation yet.
    codes: list[str] = []
    for pdf in sample_pdfs():
        off = artifacts.get_artifacts(pdf, "classified").mono_pdf
        on = runs[pdf.stem]["mono"]
        if off is None or on is None:
            codes.append(f"{pdf.stem}: no produced PDF")
            continue
        out = _tmp_root / f"rd_{pdf.stem}"
        proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
            [
                PYTHON,
                str(ROOT / "tools" / "render_diff.py"),
                str(off),
                str(on),
                "--out",
                str(out),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            codes.append(f"{pdf.stem}: exit={proc.returncode}")
    record(
        "08c the produced PDF is unchanged by turning the switch on",
        not codes,
        f"failures={codes[:3]}",
    )


# --- 09 to 11 ---------------------------------------------------------------


def check_09_no_page_type_names() -> None:
    """Negative 9: the prior reaches the code as a flag, never as a type name."""
    names = taxonomy_module.load_taxonomy().names()
    offenders: list[str] = []
    for relative in NEW_MODULES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for name in names:
                if re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", line
                ):
                    offenders.append(f"{relative}:{number}: {name}")
    record(
        "09a no page type name appears in the chain modules",
        not offenders,
        f"vocabulary={len(names)} offenders={offenders[:5]}",
    )

    # The prior has exactly one route into the score, and it is the policy flag.
    signals = (ROOT / "babeldoc/magazine/chain_signals.py").read_text(encoding="utf-8")
    record(
        "09b the opener prior is read through the starts_article policy flag",
        'OPENER_POLICY_FLAG = "starts_article"' in signals
        and signals.count("starts_article") == 1,
        f"mentions={signals.count('starts_article')}",
    )


def check_10_b1_registration() -> None:
    """Negative 10: the new writers are registered with the B1 consumer list."""
    source = (ROOT / "spec_checks" / "spec_check_b1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    listed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "NAME_REFERENCE_ALLOW_LIST"
            for t in node.targets
        ):
            listed = {
                element.value
                for element in ast.walk(node.value)
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    missing = sorted(set(NEW_MODULES) - listed)
    record(
        "10 the chain modules are registered as B1 field consumers",
        not missing,
        f"missing={missing} listed={len(listed)}",
    )


def check_11a_change_scope() -> None:
    changed = changed_files()
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES
        and path not in ALLOWED_UPSTREAM
        and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "11a every changed path is inside the declared scope",
        not stray,
        f"changed={len(changed)} stray={stray}",
    )

    upstream = sorted(
        path
        for path in changed
        if path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    )
    record(
        "11b the only upstream files touched are the two hook points",
        set(upstream) <= ALLOWED_UPSTREAM,
        f"upstream={upstream}",
    )

    registry = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    unregistered = [path for path in upstream if path not in registry]
    record(
        "11c every touched upstream file is registered in UPSTREAM_DIFF.md",
        not unregistered,
        f"unregistered={unregistered}",
    )


def check_11d_no_cjk() -> None:
    offenders: list[str] = []
    for relative in CJK_SCAN_FILES:
        path = ROOT / relative
        if not path.exists():
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if has_cjk(line):
                offenders.append(f"{relative}:{number}")
    _, diff = git_output(
        ["diff", "-U0", *batch_revisions(), "--", *sorted(ALLOWED_UPSTREAM)]
    )
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++") and has_cjk(line):
            offenders.append(f"added upstream line: {line.strip()}")
    record(
        "11d no CJK characters in this batch's code",
        not offenders,
        f"offenders={offenders[:5]}",
    )


def check_11e_no_secret() -> None:
    _, diff = git_output(["diff", *batch_revisions()])
    hits = [
        pattern.pattern
        for pattern in SECRET_PATTERNS
        for line in diff.splitlines()
        if line.startswith("+") and pattern.search(line)
    ]
    record(
        "11e this batch ships no credential",
        not hits,
        f"patterns_hit={sorted(set(hits))}",
    )


def check_11f_truth_has_no_writer() -> None:
    """Negative 11: the boundary ground truth is the corpus owner's alone."""
    needle = CHAIN_LABELS_PATH.name
    offenders: list[str] = []
    skip_parts = {".git", "__pycache__", ".venv", "examples", ".ruff_cache"}
    for path in ROOT.rglob("*.py"):
        if set(path.relative_to(ROOT).parts) & skip_parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if needle not in text and "CHAIN_LABELS_PATH" not in text:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if "CHAIN_LABELS_PATH" not in line and needle not in line:
                continue
            if re.search(r"\.(write_text|write_bytes|open)\s*\(|json\.dump", line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    record(
        "11f nothing in the repository writes the boundary ground truth",
        not offenders,
        f"offenders={offenders[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    runs: dict[str, dict] = {}
    if not harness.FAST_TIER:
        with _timer.phase("warmup"):
            use_project_cache(ROOT)
            warmup()
        with _timer.phase("artifacts"):
            runs = chained_runs()

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        check_01_chain_shape(runs)
        check_02_conservation(runs)

    check_01d_closure_shape()
    check_03_eligibility_mask()
    check_04_evidence_beats_prior()

    if not harness.FAST_TIER:
        check_05_label_agreement(runs)
        check_06_determinism(runs)

    check_08a_switch_default()
    if not harness.FAST_TIER:
        check_08b_switch_off_render(runs)

    check_09_no_page_type_names()
    check_10_b1_registration()
    check_11a_change_scope()
    check_11d_no_cjk()
    check_11e_no_secret()
    check_11f_truth_has_no_writer()
    check_07_sweep()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b4")
    artifacts.print_stats("spec_check_b4")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b4: {len(_results) - len(failed)}/{len(_results)} passed")
    for name in failed:
        print(f"  FAILED: {name}")
    shutil.rmtree(_tmp_root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
