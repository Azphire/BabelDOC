"""Gate script for batch B7 session two (drop cap candidates and their verdict).

Run from the repository root:

    python spec_checks/spec_check_b7_2.py

Exit code 0 when every assertion T7.2 answers for passes, 1 otherwise. Needs no
API key and makes no network request.

What the batch adds is a finding and a ruling on it: the pipeline says which
paragraphs open with an oversized initial, and a human says what to do about
each. Nothing acts on the ruling yet, so the assertions are about the finding
being right, the ruling arriving intact, and neither of them touching a run that
did not ask for them.

01 is the declared surface: the bounded configuration, the switch and its
dependency, the sidecar in the run inventory and the format note.

02 is the signal, on documents built so that each of its three parts can be
failed one at a time, plus the determinism the finding has to have to be worth
ruling on.

03 is the corpus: every candidate the five samples produce is body text inside
an article and clears the declared ratio, the sidecar and the intermediate
language agree, and the table of what was found is written out beside the gate.

04 is the default. With the switch down no attribute is written, no sidecar
appears, and the hook is byte for byte the hook batch-b7.1 shipped -- loaded
from that tag and run beside the current one.

05 is the ruling: the verdict reaches the intermediate language, the validator
refuses a reference this document has no paragraph for, and the report says what
was ruled. 06 is the two-pass identity under an empty drop cap section.

07 is the scope, including this batch's hard constraint: nothing upstream is
touched at all.

Tiers: 03 and 04a need pipeline artefacts and belong to the pipeline tier;
everything else is static or synthetic.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import sidecar_names  # noqa: E402
from babeldoc.magazine.page_features import ConfigError  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b7.2"
BASE_TAG = "batch-b7.1"

PYTHON = sys.executable

MODULE = "babeldoc/magazine/drop_cap.py"
HITL_MODULE = "babeldoc/magazine/hitl.py"
CONFIG = "configs/drop_cap.json"
README = "reviews/README.md"
OUTPUT_DIR = ROOT / "examples" / "output" / "b7_2"
TABLE_NAME = "drop_cap_candidates.md"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = (
    "check_03a_corpus_candidates",
    "check_03b_conservation",
    "check_04a_switch_down_artifacts",
)

# Paths this session may change. Nothing under babeldoc/ outside the extension
# package is in it: this batch touches no upstream file at all.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "prompts/",
    "reviews/",
    "tools/",
    "spec_checks/",
    "plans/",
)
ALLOWED_FILES = {"UPSTREAM_DIFF.md", "WAIVERS.md"}

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b7_2_"))

# The gate never writes a review draft into the working tree it asserts about.
os.environ[hitl.REVIEWS_ENV] = str(_tmp_root / "reviews")

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b7_2")


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


def read_checkpoint(path: Path) -> il_version_1.Document:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return XMLConverter().read_xml(str(path))


def sample_pdfs() -> list[Path]:
    manifest = corpus.load_manifest()
    return [ROOT / "examples" / "input" / entry["file"] for entry in manifest["samples"]]


class WorkingDir:
    """The whole of what this layer asks a translation config for."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def get_working_file_path(self, name: str) -> str:
        return str(self.directory / name)


class FakeSharedContext:
    """The two glossary slots the term channel reads and writes."""

    def __init__(self):
        self.raw_extracted_terms = []
        self.auto_extracted_glossary = None
        self.user_glossaries = []


class FakeConfig:
    """A translation config with only the fields these two layers touch."""

    def __init__(
        self,
        directory: Path,
        input_file: str = "Sample.pdf",
        export: bool = False,
        apply: bool = False,
        mark: bool = False,
        group: bool = True,
    ):
        self.working = WorkingDir(directory)
        self.input_file = input_file
        self.magazine_hitl_export = export
        self.magazine_hitl_apply = apply
        self.magazine_article_group = group
        self.shared_context_cross_split_part = FakeSharedContext()
        if mark:
            setattr(self, drop_cap.MARK_SWITCH, True)

    def get_working_file_path(self, name: str) -> str:
        return self.working.get_working_file_path(name)


def body_label() -> str:
    return drop_cap.body_labels()[0]


def styled_paragraph(text: str, initial_size: float, body_size: float, initial: str):
    """One body paragraph whose first style run is the caller's to choose.

    Built the way the styling stage leaves a paragraph: a list of same-style
    runs, the first of them holding the initial.
    """

    def run(content: str, size: float):
        style = il_version_1.PdfStyle(
            font_id="f", font_size=size, graphic_state=il_version_1.GraphicState()
        )
        return il_version_1.PdfParagraphComposition(
            pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                pdf_style=style,
                pdf_character=[
                    il_version_1.PdfCharacter(char_unicode=character, pdf_style=style)
                    for character in content
                ],
            )
        )

    return il_version_1.PdfParagraph(
        unicode=initial + text,
        layout_label=body_label(),
        pdf_paragraph_composition=[run(initial, initial_size), run(text, body_size)],
    )


def synthetic_document(paragraphs_per_page: list[list]) -> il_version_1.Document:
    pages = []
    for index, paragraphs in enumerate(paragraphs_per_page):
        for position, paragraph in enumerate(paragraphs):
            paragraph.debug_id = f"p{index}-{position}"
        pages.append(il_version_1.Page(page_number=index, pdf_paragraph=paragraphs))
    return il_version_1.Document(page=pages)


def write_article_map(config: FakeConfig, articles: list[dict]) -> Path:
    path = Path(config.get_working_file_path(article_builder.REPORT_NAME))
    with path.open("w", encoding="utf-8") as f:
        json.dump({"articles": articles}, f)
    return path


def write_decisions(directory: Path, sample: str, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sample}{hitl.DECISIONS_SUFFIX}"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


# --- 01 the declared surface --------------------------------------------------


def check_01a_config() -> None:
    """Positive 1a: every parameter is declared, bounded and inside its bound."""
    faults = []
    try:
        config = drop_cap.load_drop_cap_config()
    except ConfigError as exc:
        record("check_01a_config", False, str(exc))
        return
    with (ROOT / CONFIG).open(encoding="utf-8") as f:
        raw = json.load(f)
    for name in drop_cap.DropCapConfig.__dataclass_fields__:
        if name not in raw:
            faults.append(f"{name} is not declared")
        elif f"{name}_allowed_range" not in raw:
            faults.append(f"{name} has no allowed range")
    if config.min_first_run_size_ratio <= 1.0:
        faults.append("a ratio of one or less makes every paragraph a candidate")
    if config.max_first_run_chars < 1:
        faults.append("no first run can be short enough")

    # A parameter outside its declared range is refused at load.
    broken = _tmp_root / "broken_drop_cap.json"
    payload = dict(raw)
    payload["max_first_run_chars"] = 999
    with broken.open("w", encoding="utf-8") as f:
        json.dump(payload, f)
    try:
        drop_cap.load_drop_cap_config(str(broken))
    except ConfigError:
        pass
    else:
        faults.append("a parameter outside its range was accepted")
    finally:
        drop_cap.load_drop_cap_config.cache_clear()
    record("check_01a_config", not faults, "; ".join(faults))


def check_01b_switch_and_dependency() -> None:
    """Negative 1b: the switch is down unless set, and needs the grouping stage."""
    faults = []

    class Bare:
        pass

    if drop_cap.mark_enabled(Bare()):
        faults.append("the switch is up on a config that never set it")
    try:
        drop_cap.require_dependencies(Bare())
    except drop_cap.DropCapError as exc:
        faults.append(f"a run that asked for nothing was refused: {exc}")

    lonely = FakeConfig(_tmp_root / "lonely", mark=True, group=False)
    try:
        drop_cap.require_dependencies(lonely)
    except drop_cap.DropCapError as exc:
        message = str(exc)
        if drop_cap.GROUP_SWITCH not in message:
            faults.append(f"the refusal does not name the missing switch: {message}")
    else:
        faults.append("marking without the grouping stage was allowed")

    paired = FakeConfig(_tmp_root / "paired", mark=True, group=True)
    try:
        drop_cap.require_dependencies(paired)
    except drop_cap.DropCapError as exc:
        faults.append(f"a run with both switches up was refused: {exc}")

    # The refusal is explicit rather than a silent fallback: reaching the pass
    # itself raises rather than marking nothing.
    document = synthetic_document([[styled_paragraph("ext", 30.0, 10.0, "T")]])
    try:
        drop_cap.mark(lonely, hitl.labeled_pages(document))
    except drop_cap.DropCapError:
        pass
    else:
        faults.append("the marking pass degraded silently instead of refusing")
    record("check_01b_switch_and_dependency", not faults, "; ".join(faults))


def check_01c_sidecar_and_note() -> None:
    """Positive 1c: the sidecar is in the inventory and the format note explains."""
    faults = []
    if drop_cap.REPORT_NAME not in sidecar_names():
        faults.append(f"{drop_cap.REPORT_NAME} is not a declared sidecar")
    text = (ROOT / README).read_text(encoding="utf-8")
    for token in ("p<page>#<index>", drop_cap.MARK_SWITCH, "dropCapDecision"):
        if token not in text:
            faults.append(f"{README} does not mention {token}")
    # The one thing a reader has to be told: the ruling is not acted on yet.
    if "no stage reads it yet" not in text:
        faults.append(f"{README} does not say the verdict is not consumed")
    module = (ROOT / MODULE).read_text(encoding="utf-8")
    if "Nothing consumes the ruling" not in module:
        faults.append("the module docstring does not say the verdict is not consumed")
    record("check_01c_sidecar_and_note", not faults, "; ".join(faults))


# --- 02 the signal ------------------------------------------------------------


ONE_ARTICLE = [{"article_id": "A1", "pages": [1], "start_page": 1}]


def marked_references(config: FakeConfig, document) -> list[str]:
    return [
        candidate.reference
        for candidate in drop_cap.mark(config, hitl.labeled_pages(document))
    ]


def check_02a_signal_parts() -> None:
    """Positive 2a: one candidate, and each of the three signals failed alone."""
    config = drop_cap.load_drop_cap_config()
    faults = []
    long_run = "T" * (config.max_first_run_chars + 1)
    small = config.min_first_run_size_ratio * 10.0 * 0.9
    cases = {
        "candidate": ([styled_paragraph("ext follows", 60.0, 10.0, "T")], ["p1#0"]),
        "run too long": (
            [styled_paragraph("ext follows", 60.0, 10.0, long_run)],
            [],
        ),
        "ratio too small": (
            [styled_paragraph("ext follows", small, 10.0, "T")],
            [],
        ),
        "not body text": (
            [styled_paragraph("ext follows", 60.0, 10.0, "T")],
            [],
        ),
    }
    for label, (paragraphs, expected) in cases.items():
        if label == "not body text":
            paragraphs[0].layout_label = "not_a_body_label"
        work = FakeConfig(_tmp_root / f"signal_{label.replace(' ', '_')}", mark=True)
        document = synthetic_document([paragraphs])
        write_article_map(work, ONE_ARTICLE)
        found = marked_references(work, document)
        if found != expected:
            faults.append(f"{label}: marked {found}, expected {expected}")

    # A paragraph in no article is never a candidate, however it is set.
    outside = FakeConfig(_tmp_root / "signal_outside", mark=True)
    document = synthetic_document([[styled_paragraph("ext", 60.0, 10.0, "T")]])
    write_article_map(outside, [])
    if marked_references(outside, document):
        faults.append("a paragraph outside every article was marked")

    # Too deep into an article that does not open on this page.
    deep = FakeConfig(_tmp_root / "signal_deep", mark=True)
    filler = [
        styled_paragraph("ordinary text", 10.0, 10.0, "A")
        for _ in range(config.max_body_rank_in_article)
    ]
    document = synthetic_document(
        [[styled_paragraph("first", 10.0, 10.0, "A")], filler + [styled_paragraph("ext", 60.0, 10.0, "T")]]
    )
    write_article_map(
        deep, [{"article_id": "A1", "pages": [1, 2], "start_page": 1}]
    )
    if marked_references(deep, document):
        faults.append("a paragraph past the rank bound on a later page was marked")

    # The same paragraph on a page its article opens on is a candidate whatever
    # its rank, which is the disjunct the bound is written with.
    opener = FakeConfig(_tmp_root / "signal_opener", mark=True)
    document = synthetic_document(
        [filler + [styled_paragraph("ext", 60.0, 10.0, "T")]]
    )
    write_article_map(opener, ONE_ARTICLE)
    if marked_references(opener, document) != [f"p1#{len(filler)}"]:
        faults.append("a deep paragraph on an opening page was not marked")
    record("check_02a_signal_parts", not faults, "; ".join(faults))


def check_02b_determinism() -> None:
    """Positive 2b: the same document marks the same way, sidecar included."""
    faults = []
    document = synthetic_document(
        [
            [
                styled_paragraph("irst body", 10.0, 10.0, "F"),
                styled_paragraph("ext follows", 60.0, 10.0, "T"),
            ]
        ]
    )
    first = FakeConfig(_tmp_root / "determinism_1", mark=True)
    write_article_map(first, ONE_ARTICLE)
    one = marked_references(first, document)
    report_one = Path(first.get_working_file_path(drop_cap.REPORT_NAME)).read_bytes()

    again = synthetic_document(
        [
            [
                styled_paragraph("irst body", 10.0, 10.0, "F"),
                styled_paragraph("ext follows", 60.0, 10.0, "T"),
            ]
        ]
    )
    second = FakeConfig(_tmp_root / "determinism_2", mark=True)
    write_article_map(second, ONE_ARTICLE)
    two = marked_references(second, again)
    report_two = Path(second.get_working_file_path(drop_cap.REPORT_NAME)).read_bytes()

    if one != two or one != ["p1#1"]:
        faults.append(f"references are {one} and {two}")
    if report_one != report_two:
        faults.append("two runs over one document wrote different sidecars")

    # A reference names a position, never an identity minted per run.
    for page in again.page:
        for index, paragraph in enumerate(page.pdf_paragraph):
            paragraph.debug_id = f"reminted-{index}"
    third = FakeConfig(_tmp_root / "determinism_3", mark=True)
    write_article_map(third, ONE_ARTICLE)
    if marked_references(third, again) != one:
        faults.append("re-minting the debug ids changed the references")
    record("check_02b_determinism", not faults, "; ".join(faults))


def check_02c_only_the_candidate_is_written() -> None:
    """Negative 2c: a paragraph that is not a candidate carries no attribute."""
    document = synthetic_document(
        [
            [
                styled_paragraph("rdinary", 10.0, 10.0, "O"),
                styled_paragraph("ext follows", 60.0, 10.0, "T"),
                styled_paragraph("lso ordinary", 10.0, 10.0, "A"),
            ]
        ]
    )
    config = FakeConfig(_tmp_root / "written", mark=True)
    write_article_map(config, ONE_ARTICLE)
    drop_cap.mark(config, hitl.labeled_pages(document))
    flags = [paragraph.drop_cap_candidate for paragraph in document.page[0].pdf_paragraph]
    decisions = [
        paragraph.drop_cap_decision for paragraph in document.page[0].pdf_paragraph
    ]
    record(
        "check_02c_only_the_candidate_is_written",
        flags == [None, True, None] and decisions == [None, None, None],
        f"candidates={flags} decisions={decisions}",
    )


# --- 03 the corpus ------------------------------------------------------------

_corpus_rows: list[dict] = []


def corpus_runs() -> list[tuple[str, artifacts.Artifacts]]:
    return [(pdf.stem, artifacts.get_artifacts(pdf, "drop_capped")) for pdf in sample_pdfs()]


def check_03a_corpus_candidates() -> None:
    """Positive 3a: every candidate the corpus produces answers for itself."""
    config = drop_cap.load_drop_cap_config()
    labels = drop_cap.body_labels()
    faults = []
    rows = []
    for name, built in corpus_runs():
        checkpoint = built.working_dir / f"{checkpoint_stem('il_translated')}.xml"
        report_path = built.working_dir / drop_cap.REPORT_NAME
        if not checkpoint.exists() or not report_path.exists():
            faults.append(f"{name}: no checkpoint or no sidecar")
            continue
        document = read_checkpoint(checkpoint)
        with report_path.open(encoding="utf-8") as f:
            report = json.load(f)
        marked = {
            drop_cap.paragraph_reference(label, index): paragraph
            for label, page in hitl.labeled_pages(document)
            for index, paragraph in enumerate(page.pdf_paragraph)
            if paragraph.drop_cap_candidate
        }
        reported = {entry["paragraph"]: entry for entry in report["candidates"]}
        if set(marked) != set(reported):
            faults.append(f"{name}: sidecar {sorted(reported)} vs IL {sorted(marked)}")
        for reference, paragraph in marked.items():
            entry = reported.get(reference, {})
            if paragraph.layout_label not in labels:
                faults.append(f"{name}:{reference} is labelled {paragraph.layout_label}")
            if entry.get("article_id") is None:
                faults.append(f"{name}:{reference} belongs to no article")
            if entry.get("size_ratio", 0) < config.min_first_run_size_ratio:
                faults.append(f"{name}:{reference} ratio {entry.get('size_ratio')}")
            if paragraph.drop_cap_decision is not None:
                faults.append(f"{name}:{reference} carries a verdict nobody ruled")
            rows.append({"sample": name, **entry})
    _corpus_rows.extend(rows)
    write_table(rows)
    record(
        "check_03a_corpus_candidates",
        not faults and bool(rows),
        f"candidates={len(rows)} faults={faults[:4]}",
    )


def write_table(rows: list[dict]) -> Path:
    """The candidate table, as the session reports it."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Drop cap candidates",
        "",
        "| sample | paragraph | page | article | body rank | opens article | "
        "size ratio | first run | excerpt |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        excerpt = (row.get("excerpt") or "").replace("|", "/")
        lines.append(
            f"| {row['sample']} | `{row['paragraph']}` | {row['page']} | "
            f"{row['article_id']} | {row['body_rank']} | {row['opens_article']} | "
            f"{row['size_ratio']} | `{row['first_run']}` | {excerpt} |"
        )
    if not rows:
        lines.append("| _none_ | | | | | | | | |")
    path = OUTPUT_DIR / TABLE_NAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def check_03b_conservation() -> None:
    """Positive 3b: marking changes the flags and nothing else about the run."""
    faults = []
    for pdf in sample_pdfs():
        marked = artifacts.get_artifacts(pdf, "drop_capped")
        plain = artifacts.get_artifacts(pdf, "grouped")
        left = read_checkpoint(
            marked.working_dir / f"{checkpoint_stem('il_translated')}.xml"
        )
        right = read_checkpoint(
            plain.working_dir / f"{checkpoint_stem('il_translated')}.xml"
        )
        if len(left.page) != len(right.page):
            faults.append(f"{pdf.stem}: {len(left.page)} pages against {len(right.page)}")
            continue
        for index, (one, two) in enumerate(zip(left.page, right.page, strict=True)):
            if len(one.pdf_paragraph) != len(two.pdf_paragraph):
                faults.append(f"{pdf.stem}: page {index + 1} paragraph count moved")
                continue
            for first, second in zip(one.pdf_paragraph, two.pdf_paragraph, strict=True):
                if (first.unicode or "") != (second.unicode or ""):
                    faults.append(f"{pdf.stem}: page {index + 1} text moved")
                    break
        # The produced PDF is compared by what it renders rather than by its
        # bytes: two runs of one pipeline over one document do not write the
        # same file, and what the assertion is about is that marking moves no
        # pixel, nothing downstream reading the flag yet.
        if marked.mono_pdf and plain.mono_pdf:
            proc = subprocess.run(  # noqa: S603
                [
                    PYTHON,
                    str(ROOT / "tools" / "render_diff.py"),
                    str(plain.mono_pdf),
                    str(marked.mono_pdf),
                    "--out",
                    str(_tmp_root / f"render_{pdf.stem}"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                faults.append(f"{pdf.stem}: the render differs, exit={proc.returncode}")
    record("check_03b_conservation", not faults, "; ".join(faults[:4]))


# --- 04 the default -----------------------------------------------------------


def check_04a_switch_down_artifacts() -> None:
    """Negative 4a: with the switch down no field and no sidecar is written."""
    faults = []
    needles = ("dropCapCandidate", "dropCapDecision")
    for pdf in sample_pdfs():
        plain = artifacts.get_artifacts(pdf, "grouped")
        if (plain.working_dir / drop_cap.REPORT_NAME).exists():
            faults.append(f"{pdf.stem}: a sidecar was written with the switch down")
        for checkpoint in sorted(plain.working_dir.glob("*.xml")):
            text = checkpoint.read_text(encoding="utf-8")
            for needle in needles:
                if needle in text:
                    faults.append(f"{pdf.stem}: {checkpoint.name} carries {needle}")
    record("check_04a_switch_down_artifacts", not faults, "; ".join(faults[:4]))


def load_module_at(revision: str, relative: str, name: str):
    """One module as a revision shipped it, with its paths pointed at this tree."""
    proc = subprocess.run(  # noqa: S603
        ["git", "show", f"{revision}:{relative}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"{revision} does not carry {relative}")
    path = _tmp_root / f"{name}.py"
    path.write_bytes(proc.stdout)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # A dataclass resolves its own module out of sys.modules while it is being
    # built, so the module has to be registered before its body runs.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # The module computed its configuration paths from its own location, which
    # is now a temporary directory; point them back at the repository.
    module.ROOT = ROOT
    module.CONFIG_PATH = ROOT / "configs" / "hitl.json"
    module.DEFAULT_REVIEWS_DIR = ROOT / "reviews"
    return module


def hook_run(module, directory: Path, export: bool, apply: bool, document) -> dict:
    """One call of the term hook, as what it left behind."""
    config = FakeConfig(directory, export=export, apply=apply)
    module.after_term_extract(config, document)
    return {
        "xml": XMLConverter().to_xml(document),
        "files": sorted(path.name for path in directory.iterdir()),
    }


def check_04b_hook_matches_previous_batch() -> None:
    """Negative 4b: with the switch down the hook is batch-b7.1's hook."""
    try:
        previous = load_module_at(BASE_TAG, HITL_MODULE, "hitl_b7_1")
    except RuntimeError as exc:
        record("check_04b_hook_matches_previous_batch", False, str(exc))
        return
    reviews = _tmp_root / "reviews_previous"
    write_decisions(reviews, "Sample", {})
    held = os.environ[hitl.REVIEWS_ENV]
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    previous.DEFAULT_REVIEWS_DIR = reviews
    faults = []
    try:
        for export, apply in ((False, False), (True, True)):
            tag = f"{int(export)}{int(apply)}"
            old = hook_run(
                previous,
                _tmp_root / f"previous_{tag}",
                export,
                apply,
                synthetic_document([[styled_paragraph("ext", 60.0, 10.0, "T")]]),
            )
            new = hook_run(
                hitl,
                _tmp_root / f"current_{tag}",
                export,
                apply,
                synthetic_document([[styled_paragraph("ext", 60.0, 10.0, "T")]]),
            )
            if old["xml"] != new["xml"]:
                faults.append(f"export={export} apply={apply}: the document differs")
            if old["files"] != new["files"]:
                faults.append(
                    f"export={export} apply={apply}: files {old['files']} "
                    f"against {new['files']}"
                )
        # The draft the two batches write differs only in a section that was
        # declared empty before and is empty here too, the switch being down.
        old_draft = json.loads(
            (reviews / f"Sample{hitl.REVIEW_SUFFIX}").read_text(encoding="utf-8")
        )
        if old_draft.get(hitl.DROP_CAPS_SECTION) != []:
            faults.append(f"the drop cap section is {old_draft.get('drop_caps')}")
    finally:
        os.environ[hitl.REVIEWS_ENV] = held
    record("check_04b_hook_matches_previous_batch", not faults, "; ".join(faults))


# --- 05 the ruling ------------------------------------------------------------


def check_05a_decision_written() -> None:
    """Positive 5a: a ruled paragraph carries the verdict, and only it does."""
    verdicts = tuple(hitl.load_hitl_config()["drop_cap_decisions"])
    document = synthetic_document(
        [
            [
                styled_paragraph("ext follows", 60.0, 10.0, "T"),
                styled_paragraph("rdinary", 10.0, 10.0, "O"),
            ]
        ]
    )
    reviews = _tmp_root / "reviews_ruled"
    write_decisions(
        reviews,
        "Sample",
        {"drop_caps": {"p1#0": verdicts[0], "p1#1": verdicts[1]}},
    )
    held = os.environ[hitl.REVIEWS_ENV]
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    faults = []
    try:
        config = FakeConfig(_tmp_root / "ruled", apply=True, mark=True)
        write_article_map(config, ONE_ARTICLE)
        hitl.after_term_extract(config, document)
        report_path = Path(config.get_working_file_path(hitl.REPORT_NAME))
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    finally:
        os.environ[hitl.REVIEWS_ENV] = held
    paragraphs = document.page[0].pdf_paragraph
    if [p.drop_cap_decision for p in paragraphs] != [verdicts[0], verdicts[1]]:
        faults.append(f"verdicts are {[p.drop_cap_decision for p in paragraphs]}")
    if paragraphs[1].drop_cap_candidate is not None:
        faults.append("ruling on a paragraph made it a candidate")
    ruled = {entry["paragraph"]: entry for entry in report.get("drop_caps", [])}
    if set(ruled) != {"p1#0", "p1#1"}:
        faults.append(f"the report records {sorted(ruled)}")
    elif ruled["p1#0"]["was_candidate"] is not True or ruled["p1#1"]["was_candidate"]:
        faults.append(f"the report does not say which was flagged: {ruled}")
    if "decisions_file" not in report:
        faults.append("the report does not name the file it obeyed")
    record("check_05a_decision_written", not faults, "; ".join(faults))


def check_05b_negative_probes() -> None:
    """Negative 5b: every malformed drop cap ruling refuses the whole file."""
    verdicts = tuple(hitl.load_hitl_config()["drop_cap_decisions"])
    references = {"p1#0", "p1#1"}
    probes = (
        ("section not an object", {"drop_caps": []}, "must be an object"),
        ("empty reference", {"drop_caps": {"  ": verdicts[0]}}, "non-empty"),
        ("unknown verdict", {"drop_caps": {"p1#0": "burn"}}, "one of"),
        ("verdict not a string", {"drop_caps": {"p1#0": 3}}, "one of"),
        (
            "unknown paragraph",
            {"drop_caps": {"p9#4": verdicts[0]}},
            "no such paragraph",
        ),
    )
    faults = []
    for label, payload, expected in probes:
        try:
            hitl.parse_decisions(payload, Path("probe.json"), {1}, references)
        except hitl.HitlError as exc:
            if expected not in str(exc):
                faults.append(f"{label}: message does not mention {expected!r}")
            continue
        faults.append(f"{label}: accepted")

    # Two faults are both reported, and a well formed ruling survives.
    try:
        hitl.parse_decisions(
            {"drop_caps": {"p9#4": verdicts[0], "p1#0": "burn"}},
            Path("probe.json"),
            {1},
            references,
        )
    except hitl.HitlError as exc:
        if str(exc).count("\n  ") != 2:
            faults.append(f"a two-fault file reported {str(exc).count(chr(10) + '  ')}")
    else:
        faults.append("a two-fault file was accepted")
    good = hitl.parse_decisions(
        {"drop_caps": {"p1#0": verdicts[0]}}, Path("probe.json"), {1}, references
    )
    if good.drop_caps != {"p1#0": verdicts[0]}:
        faults.append(f"a well formed ruling read as {good.drop_caps}")
    # Without a document to check against, the shape is still checked and the
    # reference is not: that is the call the b7.1 gate makes.
    blind = hitl.parse_decisions(
        {"drop_caps": {"anything": verdicts[0]}}, Path("probe.json"), {1}
    )
    if blind.drop_caps != {"anything": verdicts[0]}:
        faults.append("a ruling read without a document was altered")
    record("check_05b_negative_probes", not faults, "; ".join(faults))


def check_05c_no_consumer() -> None:
    """Negative 5c: nothing reads the verdict, and the writers are registered."""
    faults = []
    readers = []
    field = "drop_cap_decision"
    for path in sorted((ROOT / "babeldoc").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        # The module that writes it, the round-trip prober that names every new
        # field, and the schema that declares it. A mention anywhere else is a
        # consumer, and the point of this assertion is that there is none.
        if relative in {MODULE, "babeldoc/magazine/ir_compat.py"} or relative.endswith(
            "il_version_1.py"
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == field:
                readers.append(f"{relative}:{node.lineno}")
    if readers:
        faults.append(f"the verdict is read by {readers}")

    # The writer is on the B1 consumer allow list, which is what keeps the
    # paragraph level fields answerable for.
    gate = (ROOT / "spec_checks" / "spec_check_b1.py").read_text(encoding="utf-8")
    for entry in (MODULE, f"spec_checks/{Path(__file__).name}"):
        if entry not in gate:
            faults.append(f"{entry} is not on the B1 consumer allow list")
    record("check_05c_no_consumer", not faults, "; ".join(faults))


# --- 06 the two-pass identity -------------------------------------------------


def check_06_two_pass_identity() -> None:
    """Positive 6: a second pass under an empty drop cap section changes nothing."""
    reviews = _tmp_root / "reviews_identity"
    write_decisions(reviews, "Sample", {"drop_caps": {}})
    held = os.environ[hitl.REVIEWS_ENV]
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    faults = []
    try:
        results = []
        for index, apply in enumerate((False, True)):
            document = synthetic_document(
                [
                    [
                        styled_paragraph("ext follows", 60.0, 10.0, "T"),
                        styled_paragraph("rdinary", 10.0, 10.0, "O"),
                    ]
                ]
            )
            directory = _tmp_root / f"identity_{index}"
            config = FakeConfig(directory, export=True, apply=apply, mark=True)
            write_article_map(config, ONE_ARTICLE)
            hitl.after_term_extract(config, document)
            results.append(
                (
                    XMLConverter().to_xml(document),
                    (reviews / f"Sample{hitl.REVIEW_SUFFIX}").read_text(
                        encoding="utf-8"
                    ),
                    Path(config.get_working_file_path(hitl.REPORT_NAME)).exists(),
                )
            )
        first, second = results
        if first[0] != second[0]:
            faults.append("the two passes left different documents")
        if first[1] != second[1]:
            faults.append("the two passes drafted differently")
        if second[2]:
            faults.append("an empty ruling left a report")
    finally:
        os.environ[hitl.REVIEWS_ENV] = held
    record("check_06_two_pass_identity", not faults, "; ".join(faults))


# --- 07 the scope -------------------------------------------------------------


def check_07a_no_vocabulary_literals() -> None:
    """Negative 7a: no page type and no layout label is named in the new code."""
    declared = set(load_taxonomy().names()) | set(drop_cap.body_labels())
    faults = []
    for relative in (MODULE, f"spec_checks/{Path(__file__).name}"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(text)
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
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and node.value in declared
            ):
                faults.append(f"{relative}:{node.lineno} names {node.value!r}")
    record("check_07a_no_vocabulary_literals", not faults, "; ".join(faults))


def check_07b_no_upstream_change() -> None:
    """Negative 7b: this batch changes no upstream file at all."""
    changed = changed_paths()
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES
        and not path.startswith(ALLOWED_PREFIXES)
        and not path.startswith("examples/output/")
    )
    faults = []
    if upstream:
        faults.append(f"upstream files changed: {upstream}")
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    if "corpus/registry.user.json" in changed:
        faults.append("the corpus registry was edited")
    waivers = (ROOT / "WAIVERS.md").read_text(encoding="utf-8")
    if drop_cap.MARK_SWITCH not in waivers:
        faults.append("the switch that is not a constructor parameter is not waived")
    record("check_07b_no_upstream_change", not faults, "; ".join(faults))


def check_07c_ascii_prose() -> None:
    """Negative 7c: the files this session adds carry no non-ASCII prose."""
    faults = []
    for relative in (
        MODULE,
        HITL_MODULE,
        CONFIG,
        "babeldoc/magazine/article_context.py",
        "tools/term_consistency.py",
        f"spec_checks/{Path(__file__).name}",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{relative}:{number}")
    record("check_07c_ascii_prose", not faults, "; ".join(faults[:5]))


# --- 08 the sweep -------------------------------------------------------------


def check_08_sweep() -> None:
    """Positive 8: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_08_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_08_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks = [
        check_01a_config,
        check_01b_switch_and_dependency,
        check_01c_sidecar_and_note,
        check_02a_signal_parts,
        check_02b_determinism,
        check_02c_only_the_candidate_is_written,
        check_03a_corpus_candidates,
        check_03b_conservation,
        check_04a_switch_down_artifacts,
        check_04b_hook_matches_previous_batch,
        check_05a_decision_written,
        check_05b_negative_probes,
        check_05c_no_consumer,
        check_06_two_pass_identity,
        check_07a_no_vocabulary_literals,
        check_07b_no_upstream_change,
        check_07c_ascii_prose,
        check_08_sweep,
    ]
    try:
        for check in checks:
            if harness.FAST_TIER and check.__name__ in PIPELINE_TIER:
                skip(check.__name__)
                continue
            try:
                check()
            except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
                record(check.__name__, False, f"raised {exc!r}")
        print(f"\nspec_check_b7_2: {_passed}/{_total} assertions passed")
        for failure in _failures:
            print(f"  - {failure}")
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_b7_2")
    finally:
        shutil.rmtree(_tmp_root, ignore_errors=True)
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
