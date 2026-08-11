"""Gate script for batch B7 session one (human review export and injection).

Run from the repository root:

    python spec_checks/spec_check_b7.py

Exit code 0 when every assertion T7.1 answers for passes, 1 otherwise. Needs no
API key and makes no network request: the one place a model would be reached is
answered by a stub that reads its work out of the prompt the stage built, so the
real prompt path and the real glossary selection are exercised without a
credential.

What the batch adds is a layer that writes down what the machine decided and
lets a human overrule it. The assertions follow that shape.

01 is the declared surface: the configuration, the format the two files are
written in, and the two switches.

02 is the validator, which is the whole safety of the loop. A decisions file is
refused whole or applied whole, so the probes are a spectrum of single faults,
a multi-fault file that has to report all of them, and a well-formed file that
has to survive.

03 is the export. The two term fields the extractor does not record -- how many
replies proposed a source, and the page it first appears on -- are asserted
against documents built so the answer is known, and the draft is asserted to
hold the machine's verdict even on a pass that overrules it.

04 and 05 are the term channel, once under each setting of automatic
extraction, because the selection rule those two settings choose between is
what the injection has to survive. With extraction off the ruling is the only
glossary. With it on the rebuilt automatic glossary has zero hits for a ruled
source, that source reaches the prompt from the ruling's table alone, and every
entry the ruling did not name is still offered.

06 is the page channel: the ruled page carries the human's kind at certainty
with the human named as its source, its neighbours are untouched, the policy
the vocabulary declares for the new kind is what the run goes on to read, and
the checkpoint holds the ruled kind rather than the overruled one.

07 is the two-pass identity, under both extraction settings: a second pass
under an empty ruling is the first pass byte for byte, and leaves no report.

08 is the default: with both switches down nothing is written anywhere and the
pipeline is what it was.

09 is the scope: no page type is named in the new code, the machine has no path
that writes a decisions file, and every upstream file this batch touched is
registered.

10 is the full sweep, suppressed when the runner is already performing one.

Tiers: 06c, 06d and 07 need pipeline artefacts and belong to the pipeline tier;
everything else is static or synthetic.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.glossary import Glossary  # noqa: E402
from babeldoc.glossary import GlossaryEntry  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import sidecar_names  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b7.1"

PYTHON = sys.executable

MODULE = "babeldoc/magazine/hitl.py"
TOOL = "tools/hitl_review.py"
CONFIG = "configs/hitl.json"
STAGE_CONFIG = "configs/checkpoint_stages.json"
README = "reviews/README.md"
HIGH_LEVEL = "babeldoc/format/pdf/high_level.py"
TRANSLATION_CONFIG = "babeldoc/format/pdf/translation_config.py"
OUTPUT_DIR = ROOT / "examples" / "output" / "b7"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = (
    "check_06c_policy_flip",
    "check_06d_checkpoint_carries_ruling",
    "check_07_two_pass_identity",
)

# Paths this session may change.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "reviews/",
    "tools/",
    "spec_checks/",
    "plans/",
)
ALLOWED_FILES = {
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    # The two review files are JSON under a global *.json ignore; without an
    # exception the ruling a run obeyed would not be in the repository the run
    # is reproduced from.
    ".gitignore",
    HIGH_LEVEL,
    TRANSLATION_CONFIG,
}

# The only upstream files this batch is allowed to have touched.
UPSTREAM_ALLOWED = {HIGH_LEVEL, TRANSLATION_CONFIG}

# What the two upstream call sites are named, and the order they have to stand
# in relative to the statements around them.
PAGE_HOOK = "hitl.after_page_classify"
TERM_HOOK = "hitl.after_term_extract"

# The stub engine answers a batch request by echoing the input back; the header
# is how it finds that input, and is the translator's own wording.
INPUT_HEADER = "## Here is the input:"
STUB_MAX_QPS = 16

# What the stub answers the per paragraph fallback with. Any fixed string will
# do; what matters is that it is the same one on both passes.
FALLBACK_REPLY = "stub fallback translation"

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b7_"))

# The gate never writes a review draft into the working tree it asserts about.
os.environ[hitl.REVIEWS_ENV] = str(_tmp_root / "reviews")

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b7")


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
        _, listing = git_output(
            ["diff", "--name-only", f"{BATCH_TAG}^..{BATCH_TAG}"]
        )
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
    return [ROOT / "examples" / "input" / e["file"] for e in manifest["samples"]]


class WorkingDir:
    """The whole of what this layer asks a translation config for."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def get_working_file_path(self, name: str) -> str:
        return str(self.directory / name)


class FakeSharedContext:
    """The two glossary slots the injection reads and writes."""

    def __init__(self, raw=(), auto: Glossary | None = None, users=()):
        self.raw_extracted_terms = list(raw)
        self.auto_extracted_glossary = auto
        self.user_glossaries = list(users)


class FakeConfig:
    """A translation config with only the fields this layer touches."""

    def __init__(
        self,
        directory: Path,
        input_file: str = "Sample.pdf",
        export: bool = False,
        apply: bool = False,
        shared: FakeSharedContext | None = None,
    ):
        self.working = WorkingDir(directory)
        self.input_file = input_file
        self.magazine_hitl_export = export
        self.magazine_hitl_apply = apply
        self.shared_context_cross_split_part = shared or FakeSharedContext()

    def get_working_file_path(self, name: str) -> str:
        return self.working.get_working_file_path(name)


def synthetic_document(page_texts: list[list[str]]) -> il_version_1.Document:
    """A document with the page and paragraph text the caller names, and nothing else."""
    pages = []
    for index, paragraphs in enumerate(page_texts):
        pages.append(
            il_version_1.Page(
                page_number=index,
                pdf_paragraph=[
                    il_version_1.PdfParagraph(unicode=text, debug_id=f"p{index}-{n}")
                    for n, text in enumerate(paragraphs)
                ],
            )
        )
    return il_version_1.Document(page=pages)


def write_decisions(directory: Path, sample: str, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sample}{hitl.DECISIONS_SUFFIX}"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


# --- 01 the declared surface --------------------------------------------------


def check_01a_config() -> None:
    """Positive 1a: the configuration declares the sections and the vocabulary."""
    try:
        config = hitl.load_hitl_config()
    except hitl.HitlError as exc:
        record("check_01a_config", False, str(exc))
        return
    faults = []
    if tuple(config["sections"]) != ("terms", "page_kinds", "drop_caps"):
        faults.append(f"sections are {config['sections']}")
    if tuple(config["drop_cap_decisions"]) != ("keep", "flatten"):
        faults.append(f"drop cap vocabulary is {config['drop_cap_decisions']}")
    if not isinstance(config["review_format_version"], int | float):
        faults.append("format version is not a number")
    record("check_01a_config", not faults, "; ".join(faults))


def check_01b_switches() -> None:
    """Positive 1b: both switches exist on the config and are down by default."""
    import inspect

    from babeldoc.format.pdf.translation_config import TranslationConfig

    signature = inspect.signature(TranslationConfig.__init__)
    faults = []
    for name in ("magazine_hitl_export", "magazine_hitl_apply"):
        parameter = signature.parameters.get(name)
        if parameter is None:
            faults.append(f"{name} is not a constructor parameter")
        elif parameter.default is not False:
            faults.append(f"{name} defaults to {parameter.default!r}")
    record("check_01b_switches", not faults, "; ".join(faults))


def check_01c_format_documented() -> None:
    """Positive 1c: the format note explains the two derived term fields."""
    path = ROOT / README
    if not path.exists():
        record("check_01c_format_documented", False, f"{README} is missing")
        return
    text = path.read_text(encoding="utf-8")
    required = (
        "vote_count",
        "first_page",
        hitl.DECISIONS_SUFFIX,
        hitl.REVIEW_SUFFIX,
        "one-based",
    )
    missing = [token for token in required if token not in text]
    record(
        "check_01c_format_documented",
        not missing,
        f"{README} does not explain {missing}",
    )


def check_01d_sidecar_declared() -> None:
    """Positive 1d: the report an applied ruling leaves is in the run inventory."""
    declared = sidecar_names()
    record(
        "check_01d_sidecar_declared",
        hitl.REPORT_NAME in declared,
        f"{hitl.REPORT_NAME} is not declared in {STAGE_CONFIG}: {declared}",
    )


# --- 02 the validator ---------------------------------------------------------

PAGES = {1, 2, 3}


def negative_probes() -> tuple:
    """One fault each, across every rule the validator holds.

    The page type a probe carries is read from the vocabulary rather than
    written down, so this gate names no page type either.
    """
    kind = load_taxonomy().names()[0]
    return (
        ("not an object", [], "top level"),
        ("unknown section", {"termz": {}}, "declared sections"),
        ("terms not an object", {"terms": []}, "must be an object"),
        ("terms target not a string", {"terms": {"a": 3}}, "must be a string"),
        ("terms empty source", {"terms": {"": "x"}}, "non-empty"),
        ("terms empty target", {"terms": {"a": "  "}}, "non-empty"),
        ("terms padded source", {"terms": {" a": "x"}}, "padded"),
        ("terms padded target", {"terms": {"a": "x "}}, "padded"),
        ("terms normalised collision", {"terms": {"A b": "x", "a  B": "y"}}, "collides"),
        ("page kinds not an object", {"page_kinds": []}, "must be an object"),
        ("page kind not a number", {"page_kinds": {"one": kind}}, "decimal integer"),
        ("page kind padded number", {"page_kinds": {"01": kind}}, "written as 1"),
        ("page kind unknown page", {"page_kinds": {"9": kind}}, "no such page"),
        ("page kind zero", {"page_kinds": {"0": kind}}, "no such page"),
        (
            "page kind unknown type",
            {"page_kinds": {"1": "not_a_kind"}},
            "declared page type",
        ),
        ("drop caps not an object", {"drop_caps": []}, "must be an object"),
        ("drop caps empty ref", {"drop_caps": {" ": "keep"}}, "non-empty"),
        ("drop caps unknown verdict", {"drop_caps": {"p": "burn"}}, "one of"),
    )


def check_02a_negative_probes() -> None:
    """Negative 2a: every malformed shape refuses the whole file, saying why."""
    faults = []
    for label, payload, expected in negative_probes():
        try:
            hitl.parse_decisions(payload, Path("probe.json"), PAGES)
        except hitl.HitlError as exc:
            if expected not in str(exc):
                faults.append(f"{label}: message does not mention {expected!r}")
            continue
        faults.append(f"{label}: accepted")
    record("check_02a_negative_probes", not faults, "; ".join(faults))


def check_02b_all_faults_reported() -> None:
    """Negative 2b: a file with several faults reports all of them, not the first."""
    payload = {
        "terms": {"": "x", " b": "y"},
        "page_kinds": {"9": load_taxonomy().names()[0], "1": "not_a_kind"},
        "drop_caps": {"p": "burn"},
    }
    try:
        hitl.parse_decisions(payload, Path("probe.json"), PAGES)
    except hitl.HitlError as exc:
        message = str(exc)
        count = message.count("\n  ")
        record(
            "check_02b_all_faults_reported",
            count == 5,
            f"reported {count} of 5 faults: {message}",
        )
        return
    record("check_02b_all_faults_reported", False, "accepted a file with five faults")


def check_02c_valid_accepted() -> None:
    """Positive 2c: a well-formed file yields exactly what it declared."""
    kind = load_taxonomy().names()[0]
    payload = {
        "terms": {"biopiracy": "X"},
        "page_kinds": {"2": kind},
        "drop_caps": {"ref": "flatten"},
    }
    try:
        decisions = hitl.parse_decisions(payload, Path("probe.json"), PAGES)
    except hitl.HitlError as exc:
        record("check_02c_valid_accepted", False, str(exc))
        return
    faults = []
    if decisions.terms != {"biopiracy": "X"}:
        faults.append(f"terms are {decisions.terms}")
    if decisions.page_kinds != {2: kind}:
        faults.append(f"page kinds are {decisions.page_kinds}")
    if decisions.drop_caps != {"ref": "flatten"}:
        faults.append(f"drop caps are {decisions.drop_caps}")
    empty = hitl.parse_decisions({}, Path("probe.json"), PAGES)
    if not empty.is_empty():
        faults.append("an empty object does not read as an empty ruling")
    record("check_02c_valid_accepted", not faults, "; ".join(faults))


# --- 03 the export ------------------------------------------------------------


def check_03a_terms_section() -> None:
    """Positive 3a: the four term fields, on a document built so each is known."""
    document = synthetic_document(
        [
            ["nothing of interest here"],
            ["the spinifex grass", "unrelated"],
            ["spinifex again and biopiracy"],
        ]
    )
    shared = FakeSharedContext(
        raw=[
            ("spinifex", "A"),
            ("spinifex", "A"),
            ("spinifex", "B"),
            ("biopiracy", "C"),
            ("absent term", "D"),
        ],
        auto=Glossary(
            name="auto_extracted_glossary",
            entries=[
                GlossaryEntry("spinifex", "A"),
                GlossaryEntry("biopiracy", "C"),
                GlossaryEntry("absent term", "D"),
            ],
        ),
    )
    config = FakeConfig(_tmp_root / "export_terms", shared=shared)
    rows = hitl.export_terms(config, document)
    by_source = {row["source"]: row for row in rows}
    faults = []
    if set(by_source) != {"spinifex", "biopiracy", "absent term"}:
        faults.append(f"sources are {sorted(by_source)}")
    if by_source.get("spinifex", {}).get("vote_count") != 3:
        faults.append(f"spinifex votes {by_source.get('spinifex')}")
    if by_source.get("spinifex", {}).get("first_page") != 2:
        faults.append(f"spinifex first page {by_source.get('spinifex')}")
    if by_source.get("biopiracy", {}).get("first_page") != 3:
        faults.append(f"biopiracy first page {by_source.get('biopiracy')}")
    if by_source.get("absent term", {}).get("first_page") is not None:
        faults.append("a term no page carries got a page")
    if by_source.get("spinifex", {}).get("auto_target") != "A":
        faults.append("the finalised target is not the one reported")
    if [row["source"] for row in rows] != ["spinifex", "biopiracy", "absent term"]:
        faults.append(f"rows are not in reading order: {[r['source'] for r in rows]}")
    for row in rows:
        if set(row) != {"source", "auto_target", "vote_count", "first_page"}:
            faults.append(f"row fields are {sorted(row)}")
            break
    record("check_03a_terms_section", not faults, "; ".join(faults))


def check_03b_page_kinds_section() -> None:
    """Positive 3b: one row per page, with the ambiguity the report alone holds."""
    document = synthetic_document([["a"], ["b"]])
    kinds = load_taxonomy().names()
    for index, page in enumerate(document.page):
        page.page_kind = kinds[index]
        page.page_kind_conf = 0.5 + index / 10
        page.page_kind_source = "deterministic"
    config = FakeConfig(_tmp_root / "export_kinds")
    report = Path(config.get_working_file_path("page_classify.report.json"))
    with report.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "pages": [
                    {"page_number": 0, "ambiguous": True},
                    {"page_number": 1, "ambiguous": False},
                ]
            },
            f,
        )
    rows = hitl.export_page_kinds(config, document)
    faults = []
    if [row["page"] for row in rows] != [1, 2]:
        faults.append(f"pages are {[row['page'] for row in rows]}")
    if [row["machine_kind"] for row in rows] != list(kinds[:2]):
        faults.append("the kinds on the pages are not the kinds reported")
    if [row["ambiguous"] for row in rows] != [True, False]:
        faults.append("ambiguity did not come from the report")
    for row in rows:
        if set(row) != {"page", "machine_kind", "conf", "ambiguous", "source"}:
            faults.append(f"row fields are {sorted(row)}")
            break
    # With no report beside the run the field is absent rather than guessed.
    quiet = FakeConfig(_tmp_root / "export_kinds_quiet")
    if any(row["ambiguous"] is not None for row in hitl.export_page_kinds(quiet, document)):
        faults.append("ambiguity was invented without a report")
    record("check_03b_page_kinds_section", not faults, "; ".join(faults))


def check_03c_draft_holds_machine_verdict() -> None:
    """Positive 3c: a pass that overrules still drafts what the machine decided."""
    kinds = load_taxonomy().names()
    document = synthetic_document([["a"], ["b"]])
    for page in document.page:
        page.page_kind = kinds[0]
        page.page_kind_conf = 0.5
        page.page_kind_source = "deterministic"
    reviews = _tmp_root / "reviews_verdict"
    write_decisions(reviews, "Sample", {"page_kinds": {"1": kinds[1]}})
    previous = os.environ[hitl.REVIEWS_ENV]
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    try:
        config = FakeConfig(
            _tmp_root / "verdict", export=True, apply=True
        )
        hitl.after_page_classify(config, document)
        with hitl.review_path("Sample").open(encoding="utf-8") as f:
            draft = json.load(f)
    finally:
        os.environ[hitl.REVIEWS_ENV] = previous
    faults = []
    drafted = {row["page"]: row for row in draft["page_kinds"]}
    if drafted[1]["machine_kind"] != kinds[0]:
        faults.append(f"the draft recorded the ruling: {drafted[1]}")
    if drafted[1]["source"] != "deterministic":
        faults.append("the draft recorded the human as the source")
    if document.page[0].page_kind != kinds[1]:
        faults.append("the ruling was not applied")
    record("check_03c_draft_holds_machine_verdict", not faults, "; ".join(faults))


def check_03d_html_draft() -> None:
    """Positive 3d: the draft renders to one self-contained page, section by section."""
    draft = {
        "format_version": 1,
        "sample": "Sample",
        "terms": [
            {
                "source": "spinifex",
                "auto_target": "A",
                "vote_count": 3,
                "first_page": 2,
            }
        ],
        "page_kinds": [
            {
                "page": 1,
                "machine_kind": load_taxonomy().names()[0],
                "conf": 0.5,
                "ambiguous": True,
                "source": "deterministic",
            }
        ],
        "drop_caps": [],
    }
    page = hitl.render_review_html(draft)
    faults = []
    for token in ("spinifex", "vote_count", "first_page", "terms", "page_kinds"):
        if token not in page:
            faults.append(f"the page does not carry {token!r}")
    if "http://" in page or "https://" in page:
        faults.append("the page reaches outside itself")
    if hitl.DECISIONS_SUFFIX not in page:
        faults.append("the page does not say where a ruling goes")
    record("check_03d_html_draft", not faults, "; ".join(faults))


# --- 04 and 05 the term channel ----------------------------------------------


def apply_over(auto: Glossary | None, terms: dict[str, str], users=()) -> tuple:
    """Apply one ruling over one glossary state and return what came of it."""
    shared = FakeSharedContext(auto=auto, users=users)
    config = FakeConfig(
        _tmp_root / f"apply_{len(terms)}_{auto is not None}_{len(users)}",
        apply=True,
        shared=shared,
    )
    decisions = hitl.parse_decisions({"terms": terms}, Path("probe.json"), PAGES)
    applied = hitl.apply_terms(config, decisions)
    return shared, applied


def selected(shared: FakeSharedContext, auto_enabled: bool) -> list[Glossary]:
    """The glossaries the translator would cache, by the upstream rule itself."""
    from babeldoc.format.pdf.translation_config import SharedContextCrossSplitPart

    real = SharedContextCrossSplitPart()
    real.initialize_glossaries(shared.user_glossaries)
    real.auto_extracted_glossary = shared.auto_extracted_glossary
    return real.get_glossaries_for_translation(auto_enabled)


def check_04_auto_off() -> None:
    """Positive 4: with extraction off the ruling is the only glossary offered."""
    shared, applied = apply_over(None, {"biopiracy": "RULED"})
    chosen = selected(shared, False)
    faults = []
    if len(chosen) != 1 or chosen[0].name != hitl.DECISIONS_GLOSSARY:
        faults.append(f"the selected glossaries are {[g.name for g in chosen]}")
    elif chosen[0].get_active_entries_for_text("a text about biopiracy") != [
        ("biopiracy", "RULED")
    ]:
        faults.append("the ruled pair does not match the text it was ruled for")
    if applied["dropped_from_auto"]:
        faults.append("something was dropped with no automatic glossary present")
    if applied["auto_glossary_relocated"] is not None:
        faults.append("a glossary that does not exist was relocated")
    record("check_04_auto_off", not faults, "; ".join(faults))


def auto_glossary() -> Glossary:
    return Glossary(
        name="auto_extracted_glossary",
        entries=[
            GlossaryEntry("biopiracy", "AUTO"),
            GlossaryEntry("spinifex", "KEPT"),
        ],
    )


def check_05a_auto_on_zero_hits() -> None:
    """Positive 5a: the rebuilt automatic glossary no longer knows a ruled source."""
    shared, applied = apply_over(auto_glossary(), {"biopiracy": "RULED"})
    chosen = selected(shared, True)
    rebuilt = [g for g in chosen if g.name == "auto_extracted_glossary"]
    faults = []
    if len(rebuilt) != 1:
        faults.append(f"the automatic table is {[g.name for g in chosen]}")
    else:
        hits = rebuilt[0].get_active_entries_for_text("biopiracy and spinifex")
        if any(source == "biopiracy" for source, _ in hits):
            faults.append(f"the rebuilt table still matches the ruled source: {hits}")
        if ("spinifex", "KEPT") not in hits:
            faults.append(f"an entry no one ruled on was lost: {hits}")
    if [entry["source"] for entry in applied["dropped_from_auto"]] != ["biopiracy"]:
        faults.append(f"the dropped list is {applied['dropped_from_auto']}")
    else:
        dropped = applied["dropped_from_auto"][0]
        if dropped["auto_target"] != "AUTO" or dropped["user_target"] != "RULED":
            faults.append(f"the dropped entry does not name both targets: {dropped}")
    record("check_05a_auto_on_zero_hits", not faults, "; ".join(faults))


def check_05b_reaches_the_prompt() -> None:
    """Positive 5b: with extraction on, a ruled source is in the ruling's table only."""
    shared, _ = apply_over(auto_glossary(), {"biopiracy": "RULED"})
    prompt = build_prompt(shared, True, "a passage about biopiracy and spinifex")
    faults = []
    if prompt is None:
        record("check_05b_reaches_the_prompt", False, "no prompt was built")
        return
    tables = split_glossary_tables(prompt)
    for name, rows in tables.items():
        ruled = [row for row in rows if row[0] == "biopiracy"]
        if name == hitl.DECISIONS_GLOSSARY:
            if ruled != [("biopiracy", "RULED")]:
                faults.append(f"the ruling's table offers {ruled}")
        elif ruled:
            faults.append(f"table {name} also offers the ruled source: {ruled}")
    if hitl.DECISIONS_GLOSSARY not in tables:
        faults.append(f"the ruling built no table; tables are {sorted(tables)}")
    if "auto_extracted_glossary" not in tables:
        faults.append("the entries no one ruled on reached no table")
    record("check_05b_reaches_the_prompt", not faults, "; ".join(faults))


def check_05c_report_written() -> None:
    """Positive 5c: what a ruling did is recorded beside the run, entry by entry."""
    reviews = _tmp_root / "reviews_report"
    write_decisions(reviews, "Sample", {"terms": {"biopiracy": "RULED"}})
    previous = os.environ[hitl.REVIEWS_ENV]
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    try:
        shared = FakeSharedContext(auto=auto_glossary())
        config = FakeConfig(_tmp_root / "report", apply=True, shared=shared)
        hitl.after_term_extract(config, synthetic_document([["biopiracy"]]))
        path = Path(config.get_working_file_path(hitl.REPORT_NAME))
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    finally:
        os.environ[hitl.REVIEWS_ENV] = previous
    faults = []
    if report is None:
        faults.append("no report was written")
    else:
        terms = report.get("terms", {})
        if terms.get("dropped_from_auto") != [
            {"source": "biopiracy", "auto_target": "AUTO", "user_target": "RULED"}
        ]:
            faults.append(f"the dropped list is {terms.get('dropped_from_auto')}")
        if terms.get("auto_glossary_relocated") != "auto_extracted_glossary":
            faults.append("the report does not say where the automatic table went")
        if "decisions_file" not in report:
            faults.append("the report does not name the file it obeyed")
    record("check_05c_report_written", not faults, "; ".join(faults))


def build_prompt(shared: FakeSharedContext, auto_enabled: bool, text: str):
    """The real prompt the translator would build for one batch of text."""
    from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
        ILTranslatorLLMOnly,
    )
    from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.progress_monitor import ProgressMonitor
    from babeldoc.translator.translator import BaseTranslator

    class StubTranslator(BaseTranslator):
        name = "b7-stub"

        def __init__(self):
            super().__init__("en", "zh", ignore_cache=True)

        def do_translate(self, text, rate_limit_params: dict = None):
            return text

        def do_llm_translate(self, text, rate_limit_params: dict = None):
            if text is None:
                return None
            return json.dumps(
                [
                    {"id": item["id"], "output": item["input"]}
                    for item in json.loads(text.split(INPUT_HEADER, 1)[1].strip())
                ]
            )

    work = _tmp_root / "prompt"
    work.mkdir(parents=True, exist_ok=True)
    monitor = ProgressMonitor([(ILTranslatorLLMOnly.stage_name, 1.0)])
    monitor.disable = True
    config = TranslationConfig(
        translator=StubTranslator(),
        input_file="Sample.pdf",
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        working_dir=work,
        output_dir=work / "out",
        progress_monitor=monitor,
        auto_extract_glossary=auto_enabled,
        qps=STUB_MAX_QPS,
    )
    config.shared_context_cross_split_part.initialize_glossaries(
        shared.user_glossaries
    )
    config.shared_context_cross_split_part.auto_extracted_glossary = (
        shared.auto_extracted_glossary
    )
    stage = ILTranslatorLLMOnly(config.translator, config)
    return stage._build_llm_prompt(
        json_input_str="[]",
        title_paragraph=None,
        local_title_paragraph=None,
        batch_text_for_glossary_matching=text,
    )


def split_glossary_tables(prompt: str) -> dict[str, list[tuple[str, str]]]:
    """The glossary tables of a built prompt, by the heading each stands under."""
    tables: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for line in prompt.splitlines():
        if line.startswith("### Glossary: "):
            current = line[len("### Glossary: ") :].strip()
            tables[current] = []
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2 or cells[0] in {"Source Term", ""} or set(cells[0]) == {"-"}:
            continue
        tables[current].append((cells[0], cells[1]))
    return tables


# --- 06 the page channel ------------------------------------------------------


def check_06a_ruled_page() -> None:
    """Positive 6a: a ruled page carries the human's kind, at certainty, named."""
    kinds = load_taxonomy().names()
    document = synthetic_document([["a"], ["b"], ["c"]])
    for page in document.page:
        page.page_kind = kinds[0]
        page.page_kind_conf = 0.42
        page.page_kind_source = "deterministic"
    decisions = hitl.parse_decisions(
        {"page_kinds": {"2": kinds[1]}}, Path("probe.json"), {1, 2, 3}
    )
    applied = hitl.apply_page_kinds(document, decisions)
    ruled, first = document.page[1], document.page[0]
    faults = []
    if (ruled.page_kind, ruled.page_kind_conf, ruled.page_kind_source) != (
        kinds[1],
        1.0,
        "human",
    ):
        faults.append(
            f"the ruled page carries {ruled.page_kind}/"
            f"{ruled.page_kind_conf}/{ruled.page_kind_source}"
        )
    if (first.page_kind, first.page_kind_conf, first.page_kind_source) != (
        kinds[0],
        0.42,
        "deterministic",
    ):
        faults.append("a page no one ruled on was touched")
    if len(applied) != 1 or applied[0]["machine_kind"] != kinds[0]:
        faults.append(f"the record does not hold what was overruled: {applied}")
    record("check_06a_ruled_page", not faults, "; ".join(faults))


def check_06b_no_page_type_named() -> None:
    """Negative 6b: no page type is named anywhere in the new code."""
    declared = set(load_taxonomy().names())
    faults = []
    for relative in (MODULE, TOOL, f"spec_checks/{Path(__file__).name}"):
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
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
                faults.append(f"{relative}:{node.lineno} names the page type")
    record("check_06b_no_page_type_named", not faults, "; ".join(faults))


def classified_checkpoints() -> list[tuple[str, Path]]:
    found = []
    for pdf in sample_pdfs():
        built = artifacts.get_artifacts(pdf, "classified")
        checkpoint = built.working_dir / f"{checkpoint_stem('page_classifier')}.xml"
        if checkpoint.exists():
            found.append((pdf.stem, checkpoint))
    return found


def check_06c_policy_flip() -> None:
    """Positive 6c: what the run reads downstream is the policy of the ruled kind."""
    from babeldoc.magazine.article_builder import ELIGIBILITY_POLICY_FLAG

    taxonomy = load_taxonomy()
    eligible = [
        name
        for name in taxonomy.names()
        if taxonomy.policy_of(name).get(ELIGIBILITY_POLICY_FLAG)
    ]
    ineligible = [
        name
        for name in taxonomy.names()
        if not taxonomy.policy_of(name).get(ELIGIBILITY_POLICY_FLAG)
    ]
    if not eligible or not ineligible:
        record(
            "check_06c_policy_flip",
            False,
            "the vocabulary declares no pair to flip between",
        )
        return
    checkpoints = classified_checkpoints()
    if not checkpoints:
        record("check_06c_policy_flip", False, "no classified checkpoint was built")
        return
    _, checkpoint = checkpoints[0]
    document = read_checkpoint(checkpoint)
    target = next(
        (
            index
            for index, page in enumerate(document.page)
            if taxonomy.policy_of(page.page_kind)
            and taxonomy.policy_of(page.page_kind).get(ELIGIBILITY_POLICY_FLAG)
        ),
        None,
    )
    if target is None:
        record("check_06c_policy_flip", False, "no eligible page to overrule")
        return
    label = hitl.page_label(document.page[target], target)
    before = taxonomy.policy_of(document.page[target].page_kind)[
        ELIGIBILITY_POLICY_FLAG
    ]
    decisions = hitl.parse_decisions(
        {"page_kinds": {str(label): ineligible[0]}},
        Path("probe.json"),
        {hitl.page_label(p, i) for i, p in enumerate(document.page)},
    )
    hitl.apply_page_kinds(document, decisions)
    after = taxonomy.policy_of(document.page[target].page_kind)[
        ELIGIBILITY_POLICY_FLAG
    ]
    record(
        "check_06c_policy_flip",
        bool(before) and not after,
        f"eligibility went from {before} to {after}",
    )


def check_06d_checkpoint_carries_ruling() -> None:
    """Positive 6d: the hook stands before the checkpoint of the stage it follows."""
    source = (ROOT / HIGH_LEVEL).read_text(encoding="utf-8").splitlines()
    hook = next((n for n, line in enumerate(source) if PAGE_HOOK in line), None)
    classifier = next(
        (n for n, line in enumerate(source) if "PageClassifier(" in line), None
    )
    dumps = [
        n for n, line in enumerate(source) if 'dump_checkpoint(docs, translation_config, "page_classifier"' in line
    ]
    faults = []
    if hook is None or classifier is None or not dumps:
        faults.append(f"hook {hook}, classifier {classifier}, checkpoints {dumps}")
    elif not classifier < hook < dumps[0]:
        faults.append(
            f"the hook at {hook + 1} is not between the stage at "
            f"{classifier + 1} and its checkpoint at {dumps[0] + 1}"
        )
    term_hook = next((n for n, line in enumerate(source) if TERM_HOOK in line), None)
    translator = next(
        (n for n, line in enumerate(source) if "ILTranslatorLLMOnly(translate_engine" in line),
        None,
    )
    if term_hook is None or translator is None or term_hook > translator:
        faults.append(
            f"the term hook at {term_hook} does not precede the translator at {translator}"
        )
    record("check_06d_checkpoint_carries_ruling", not faults, "; ".join(faults))


# --- 07 the two-pass identity -------------------------------------------------


def stub_translation(checkpoint: Path, label: str, apply: bool, auto_on: bool) -> str:
    """One run of the translation stage over one checkpoint, as serialised XML."""
    from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
        ILTranslatorLLMOnly,
    )
    from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.progress_monitor import ProgressMonitor
    from babeldoc.translator.translator import BaseTranslator
    from babeldoc.translator.translator import set_translate_rate_limiter

    class StubTranslator(BaseTranslator):
        name = "b7-stub"

        def __init__(self):
            super().__init__("en", "zh", ignore_cache=True)
            self.prompts: list[str] = []
            self.lock = threading.Lock()

        def do_translate(self, text, rate_limit_params: dict = None):
            return text

        def do_llm_translate(self, text, rate_limit_params: dict = None):
            if text is None:
                return None
            with self.lock:
                self.prompts.append(text)
            # A prompt with no input header is the per paragraph fallback, whose
            # reply is the translated text itself rather than a batch of them.
            if INPUT_HEADER not in text:
                return FALLBACK_REPLY
            return json.dumps(
                [
                    {"id": item["id"], "output": item["input"]}
                    for item in json.loads(text.split(INPUT_HEADER, 1)[1].strip())
                ]
            )

    set_translate_rate_limiter(STUB_MAX_QPS)
    document = read_checkpoint(checkpoint)
    work = _tmp_root / "identity" / label
    work.mkdir(parents=True, exist_ok=True)
    monitor = ProgressMonitor([(ILTranslatorLLMOnly.stage_name, 1.0)])
    monitor.disable = True
    config = TranslationConfig(
        translator=StubTranslator(),
        input_file=str(checkpoint.with_suffix(".pdf")),
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        working_dir=work,
        output_dir=work / "out",
        progress_monitor=monitor,
        auto_extract_glossary=auto_on,
        qps=STUB_MAX_QPS,
        magazine_hitl_apply=apply,
    )
    if auto_on:
        config.shared_context_cross_split_part.auto_extracted_glossary = auto_glossary()
    from babeldoc.format.pdf import high_level

    # The hook the pipeline reaches between extraction and the translator,
    # called here as the pipeline calls it so the identity is over that path.
    high_level.hitl.after_term_extract(config, document)
    stage = ILTranslatorLLMOnly(config.translator, config)
    stage.translate(document)
    # Sorted, because the order prompts arrive in is the order the pool
    # scheduled them in and is not a property of the ruling. What the two
    # passes are compared on is the set of requests and the document, both of
    # which a ruling does change.
    prompts = "\n".join(sorted(config.translator.prompts))
    return XMLConverter().to_xml(document) + "\n" + prompts


def check_07_two_pass_identity() -> None:
    """Positive 7: a pass under an empty ruling is the pass without one, byte for byte."""
    checkpoints = classified_checkpoints()
    if not checkpoints:
        record("check_07_two_pass_identity", False, "no classified checkpoint was built")
        return
    name, checkpoint = checkpoints[0]
    reviews = _tmp_root / "reviews_identity"
    write_decisions(reviews, checkpoint.with_suffix(".pdf").stem, {})
    previous = os.environ[hitl.REVIEWS_ENV]
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    faults = []
    try:
        for auto_on in (False, True):
            tag = "on" if auto_on else "off"
            first = stub_translation(checkpoint, f"{name}.{tag}.1", False, auto_on)
            second = stub_translation(checkpoint, f"{name}.{tag}.2", True, auto_on)
            if first != second:
                faults.append(f"auto={tag}: the two passes differ")
            report = _tmp_root / "identity" / f"{name}.{tag}.2" / hitl.REPORT_NAME
            if report.exists():
                faults.append(f"auto={tag}: an empty ruling left a report")
    finally:
        os.environ[hitl.REVIEWS_ENV] = previous
    record("check_07_two_pass_identity", not faults, "; ".join(faults))


# --- 08 the default -----------------------------------------------------------


def check_08_switches_down() -> None:
    """Negative 8: with both switches down nothing is written and nothing is read."""
    reviews = _tmp_root / "reviews_down"
    write_decisions(reviews, "Sample", {"terms": {"biopiracy": "RULED"}})
    previous = os.environ[hitl.REVIEWS_ENV]
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    faults = []
    try:
        shared = FakeSharedContext(auto=auto_glossary())
        work = _tmp_root / "down"
        config = FakeConfig(work, shared=shared)
        document = synthetic_document([["biopiracy"]])
        hitl.after_page_classify(config, document)
        hitl.after_term_extract(config, document)
        if shared.user_glossaries:
            faults.append("a glossary was injected with the switch down")
        if shared.auto_extracted_glossary is None:
            faults.append("the automatic glossary was taken with the switch down")
        if list(reviews.glob(f"*{hitl.REVIEW_SUFFIX}")):
            faults.append("a draft was written with the switch down")
        if Path(config.get_working_file_path(hitl.REPORT_NAME)).exists():
            faults.append("a report was written with the switch down")
    finally:
        os.environ[hitl.REVIEWS_ENV] = previous
    record("check_08_switches_down", not faults, "; ".join(faults))


# --- 09 the scope -------------------------------------------------------------


def check_09a_never_writes_decisions() -> None:
    """Negative 9a: the package has no path that writes a decisions file."""
    faults = []
    for path in sorted((ROOT / "babeldoc" / "magazine").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if hitl.DECISIONS_SUFFIX not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            # A write is an open() in write mode; the suffix appearing in a
            # path helper or a message is not one.
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = getattr(function, "attr", None) or getattr(function, "id", None)
            if name != "open":
                continue
            for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and "w" in argument.value
                ):
                    source = ast.get_source_segment(text, node) or ""
                    if "decisions" in source:
                        faults.append(
                            f"{path.name}:{node.lineno} opens a decisions file to write"
                        )
    skeleton = ROOT / "reviews" / f"Courier-en{hitl.DECISIONS_SUFFIX}"
    if skeleton.exists() and json.loads(skeleton.read_text(encoding="utf-8")) != {}:
        faults.append("the committed skeleton is not empty")
    record("check_09a_never_writes_decisions", not faults, "; ".join(faults))


def check_09b_comments_ascii() -> None:
    """Negative 9b: the new files carry no non-ASCII prose."""
    faults = []
    for relative in (MODULE, TOOL, CONFIG, f"spec_checks/{Path(__file__).name}"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{relative}:{number}")
    record("check_09b_comments_ascii", not faults, "; ".join(faults[:5]))


def check_09c_upstream_registered() -> None:
    """Negative 9c: the upstream delta is the two allowed files, both registered."""
    changed = changed_paths()
    upstream = {
        path
        for path in changed
        if path.startswith("babeldoc/")
        and not path.startswith("babeldoc/magazine/")
    }
    faults = []
    stray = sorted(upstream - UPSTREAM_ALLOWED)
    if stray:
        faults.append(f"unregistered upstream files: {stray}")
    registry = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    for path in sorted(upstream):
        if path not in registry:
            faults.append(f"{path} is not in UPSTREAM_DIFF.md")
    for token in (PAGE_HOOK, TERM_HOOK, "magazine_hitl_export", "magazine_hitl_apply"):
        if token not in registry:
            faults.append(f"UPSTREAM_DIFF.md does not describe {token}")
    record("check_09c_upstream_registered", not faults, "; ".join(faults))


def check_09d_change_scope() -> None:
    """Negative 9d: nothing outside the declared paths changed."""
    changed = changed_paths()
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES
        and not path.startswith(ALLOWED_PREFIXES)
        and not path.startswith("examples/output/")
    )
    faults = []
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    if "corpus/registry.user.json" in changed:
        faults.append("the corpus registry was edited")
    record("check_09d_change_scope", not faults, "; ".join(faults))


# --- 10 the sweep -------------------------------------------------------------


def check_10_sweep() -> None:
    """Positive 10: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_10_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record(
        "check_10_sweep",
        proc.returncode == 0,
        (proc.stdout or proc.stderr)[-2000:],
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks = [
        check_01a_config,
        check_01b_switches,
        check_01c_format_documented,
        check_01d_sidecar_declared,
        check_02a_negative_probes,
        check_02b_all_faults_reported,
        check_02c_valid_accepted,
        check_03a_terms_section,
        check_03b_page_kinds_section,
        check_03c_draft_holds_machine_verdict,
        check_03d_html_draft,
        check_04_auto_off,
        check_05a_auto_on_zero_hits,
        check_05b_reaches_the_prompt,
        check_05c_report_written,
        check_06a_ruled_page,
        check_06b_no_page_type_named,
        check_06c_policy_flip,
        check_06d_checkpoint_carries_ruling,
        check_07_two_pass_identity,
        check_08_switches_down,
        check_09a_never_writes_decisions,
        check_09b_comments_ascii,
        check_09c_upstream_registered,
        check_09d_change_scope,
        check_10_sweep,
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
        print(f"\nspec_check_b7: {_passed}/{_total} assertions passed")
        for failure in _failures:
            print(f"  - {failure}")
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_b7")
    finally:
        shutil.rmtree(_tmp_root, ignore_errors=True)
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
