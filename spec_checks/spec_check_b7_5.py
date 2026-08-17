"""Gate script for batch B7.5 session one (corpus refresh and role-scoped rates).

Run from the repository root:

    python spec_checks/spec_check_b7_5.py

Exit code 0 when every assertion T7.5.1 answers for passes, 1 otherwise. Needs
no API key and makes no network request: every run it performs is a dry run of
the parsing and classifying stages.

01 is the registration. The registry, the manifest and the two ground truth
files have to say the same thing about the same corpus: the manifest is the
registry rebuilt, the page labels name pages the samples have, and the
boundaries name adjacent pairs that exist. A retired sample leaves nothing
behind, in the corpus or in the artefacts built from it.

02 is the agreement, and it is where this batch's principle lives. The rates are
binding on the samples carrying the constrained role and are measured on every
sample. A distribution nothing was tuned against belongs in the report, not in
the gate, so a sample outside the role is scored, printed, and not allowed to
decide whether the tuned thresholds still hold. One assertion there is not a
rate and is not scoped: linking two pages the corpus owner ruled unconnected
corrupts a translation unit, and that is wrong everywhere.

03 is the checkpoint escape the refresh forced. A sample whose font names an
Adobe glyph list control glyph puts a codepoint in the IL that XML 1.0 cannot
carry in any form. The encoding that lets a checkpoint hold it has to be a
bijection -- including on a document that spells an escape sequence out --  and
has to leave every document that needs no escape exactly as it was, or every
checkpoint written before this batch would stop reading.

04 is what has to survive the refresh unchanged. The same sample classified
twice produces the same verdicts, and a pass under an empty ruling is the pass
that would have happened with the switch down -- established on one sample by
B7 and re-run here over every sample the corpus now holds, because the refresh
is what put it at risk. Beside them sits the cache's own honesty: a run that
produced nothing has to refuse to publish, or the gates served from it measure
an empty directory as zero agreement and say nothing.

05 is the scope. The three ground truth files are the corpus owner's; this batch
reads them and their digests are pinned here, so a machine edit is a failure
rather than a diff nobody looked at. No retired file name survives anywhere. The
tuning configuration did not move, which is the record that no retune happened.

07 is the masthead ruling, read from the evidence the two credentialed passes
left behind. It closes the b6.2 gap as far as a ruling can close it and is
honest about the rest: what the ruling reached, the two different reasons a site
can be out of reach, and the bound on how much of the document could have moved
at all, which is the number of prompts the ruling changed.

Tiers: 02 and 04 need pipeline artefacts and belong to the pipeline tier; the
rest are static, 07 included -- the passes are frozen and no assertion here
spends a credential.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import page_features  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.chain_builder import REPORT_NAME  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b7.5.2"

# The batch this one continues; the change scope covers both sessions.
BASE_TAG = "batch-b7.5.1"

# What the stub translator answers with, and how a batched prompt is recognised.
# A prompt without the header is the per paragraph fallback, whose reply is the
# translated text rather than a batch of them.
INPUT_HEADER = "## Here is the input:"
FALLBACK_REPLY = "stub fallback translation"
STUB_MAX_QPS = 16

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b7_5_"))

# Nothing this gate does may write a draft into the working tree it asserts on.
os.environ[hitl.REVIEWS_ENV] = str(_tmp_root / "reviews")

PYTHON = sys.executable

BASELINE_DIR = ROOT / "examples" / "output" / "baseline"
INPUT_DIR = ROOT / "examples" / "input"

# The frozen evidence of the masthead ruling. The two passes that produced it
# spent a credential once; this gate reads what they left behind.
SMOKE_DIR = ROOT / "examples" / "output" / "b7_5"
MASTHEAD_EVIDENCE = SMOKE_DIR / "masthead.evidence.json"
LEDGER = SMOKE_DIR / "runs.json"
REPORT = SMOKE_DIR / "refresh.report.md"

# The layout class the parser gives a line recovered outside any block. Such a
# paragraph is never offered to the translator.
UNREACHABLE_LABEL = "fallback_line"

# The corpus owner's files, pinned at the digests they were delivered with. The
# batch reads them and never writes them, so a difference here is a machine edit
# and not a corpus revision: a revision arrives with a session that says so and
# repins these.
TRUTH_DIGESTS = {
    # Repinned by B9.1: the owner added source_lang and target_lang to all six
    # entries, which is the revision the paragraph above says arrives with a
    # session that says so. That the revision added those two fields and
    # nothing else is asserted separately, by spec_check_b9_1's 04a2.
    "corpus/registry.user.json": (
        "64d08f6d00fb0812b8324c00ada89889a224ce6d24b81b5ac70b9db47903f2ec"
    ),
    "corpus/page_labels.json": (
        "eabef80e11262f1d56d750cf71905cf9a3427e56af2081edb17468a0e5bbb2c6"
    ),
    "corpus/chain_labels.user.json": (
        "71629c8dae18af77836cac6113186811cff13b617ed7b09d682ad47cca829687"
    ),
    # The ruling is the corpus owner's too, and for the same reason: the machine
    # reads it, applies it and reports on it, and never writes a word of it. Its
    # digest is taken after the owner wrote the masthead entries and before the
    # two passes ran, so a difference here means a pass wrote back into it.
    #
    # Repinned by B9.2 under CLAUDE.md 4.12, which is what this pin has always
    # meant: it anchors "no machine edited this file in that batch", not "this
    # file never changes again". A ruling is a living document and the two pass
    # process is how it grows.
    #   was: c86c16c136583a4cf5be63ee9a0df8184035ff128775d16e37989c56b4ad1cfe
    #   now: 372a6f7cbcdd942ffa971cfa5184689510b53089ace10e73920a195bb07a4fc4
    #   what: eight person name terms added, and the p4#3 drop cap verdict moved
    #         from keep to flatten
    #   who:  the corpus owner, in commit "ruling: person-name terms and
    #         drop-cap flatten for F2", which carries no machine edit
    #   why:  the F2 ruling update, following B9.1's person name policy
    # That the revision is those two things and nothing else is asserted
    # separately, by spec_check_b9_2's 04d, which also revalidates the whole
    # file against the loader that will read it.
    "reviews/Courier-en.decisions.json": (
        "372a6f7cbcdd942ffa971cfa5184689510b53089ace10e73920a195bb07a4fc4"
    ),
}

# The samples this refresh retired. They are named here and nowhere else: what
# the assertion wants is that no other file in the repository names them.
RETIRED_SAMPLES = ("AramcoWorld-en", "FD-en")

# Where a retired name would survive as a reference something still resolves.
# Build products are excluded, an artefact frozen under an older corpus being
# history rather than a reference; so is corpus/, where the owner's notes say
# which sample superseded which and are meant to keep saying it.
SCAN_DIRECTORIES = ("babeldoc", "configs", "prompts", "tools", "spec_checks")

# Tuning configuration. The refresh was authorised to retune these two if the
# constrained rates fell; they did not, so an edit to either is unaccounted for.
TUNING_CONFIGS = ("configs/page_types.json", "configs/chain_detection.json")

# Paths this batch may change.
ALLOWED_PREFIXES = (
    "corpus/",
    "reviews/",
    "tools/",
    "spec_checks/",
    "plans/",
    "examples/output/",
)
ALLOWED_FILES = {
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "babeldoc/magazine/corpus.py",
    "babeldoc/magazine/checkpoint.py",
}

# Strings a document may carry that XML cannot, and strings that spell the
# encoding of one out. The second kind is what makes the encoding a bijection
# rather than merely reversible for the inputs we happen to have met.
ESCAPE_PROBES = (
    "\x1a",
    "\x00\x08\x0b\x0c\x0e\x1f",
    "\ufffe\uffff",
    "\ud800",
    "plain text with no escape at all",
    "\\u001a",
    "\\\\u001a",
    "\\",
    "\\\\",
    "\\u001a\x1a\\",
    "a\\ub",
    "tab\tnewline\nreturn\r are legal",
    "",
)

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b7_5")
_runs: dict[str, dict] = {}


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


def skip(name: str, why: str) -> None:
    print(f"SKIPPED: {name} ({why})")


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
    """This batch's delta: its tags where they exist, the working tree otherwise.

    The batch was delivered in two sessions, each tagged, so the range runs from
    the commit before the first to the second session's tag and nothing either
    session changed escapes the scope assertions.
    """
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        _, listing = git_output(["diff", "--name-only", f"{BASE_TAG}^..{BATCH_TAG}"])
        return {line.strip() for line in listing.splitlines() if line.strip()}
    # Before the second tag exists: the first session's commit plus whatever the
    # second has done so far.
    _, listing = git_output(["diff", "--name-only", f"{BASE_TAG}^"])
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


def baseline_checkpoint_containers() -> list[Path]:
    """Every frozen baseline checkpoint set, whether directory or archive."""
    return sorted(
        BASELINE_DIR.glob(f"*.checkpoints{checkpoint_module.CHECKPOINT_ARCHIVE_SUFFIX}")
    ) + sorted(BASELINE_DIR.glob("*.checkpoints"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict:
    return corpus.load_manifest()


def pages_by_file() -> dict[str, int]:
    return {
        sample["file"]: sample.get("pages", 0) for sample in manifest().get("samples", [])
    }


def runs() -> dict[str, dict]:
    """The chain-detecting run of every corpus sample, keyed by file name."""
    if _runs:
        return _runs
    use_project_cache(ROOT)
    with _timer.phase("build"):
        for sample in manifest()["samples"]:
            name = sample["file"]
            built = artifacts.get_artifacts(INPUT_DIR / name, "chained")
            stem = checkpoint_module.checkpoint_stem("page_classifier")
            classified = built.working_dir / f"{stem}.xml"
            kinds: dict[str, str] = {}
            if classified.exists():
                docs = checkpoint_module.load_checkpoint(classified)
                for position, page in enumerate(docs.page):
                    index = page.page_number if page.page_number is not None else position
                    kinds[str(index + 1)] = page.page_kind
            report_path = built.working_dir / REPORT_NAME
            _runs[name] = {
                "artifacts": built,
                "kinds": kinds,
                "report": json.loads(report_path.read_text(encoding="utf-8"))
                if report_path.exists()
                else None,
            }
    return _runs


def kind_agreement(name: str) -> tuple[int, int, list[str]]:
    """Hits, labelled pages and misses for one sample's page kinds."""
    labels = corpus.normalize_page_labels(corpus.load_page_labels()).get(name, {})
    produced = runs().get(name, {}).get("kinds", {})
    hits = 0
    misses = []
    for page, accepted in labels.items():
        if produced.get(page) in accepted:
            hits += 1
        else:
            misses.append(f"{name} p{page}: {produced.get(page)!r} not in {accepted}")
    return hits, len(labels), misses


def boundary_agreement(name: str) -> tuple[int, int, list[str]]:
    """Hits, adjudicated boundaries and misses for one sample's boundaries."""
    truth = corpus.chain_label_samples(corpus.load_chain_labels()).get(name, {})
    report = runs().get(name, {}).get("report")
    if report is None:
        return 0, 0, [f"{name}: no chain report"]
    verdicts = {
        entry["boundary"]: bool(entry.get("linked")) for entry in report["boundaries"]
    }
    hits = seen = 0
    misses = []
    for key, entry in truth.items():
        if key not in verdicts:
            misses.append(f"{name} {key}: absent from the report")
            continue
        seen += 1
        if verdicts[key] == entry["link"]:
            hits += 1
        else:
            misses.append(f"{name} {key}: want {entry['link']}")
    return hits, seen, misses


# --- 01 the registration ------------------------------------------------------


def check_01a_registry_and_input_cover_each_other() -> None:
    """Positive 1a: every registered sample is present and every present one registered."""
    entries = corpus.load_registry()
    errors = corpus.validate_registry(entries)
    manifest_errors, _ = corpus.validate_manifest(manifest(), entries)
    faults = errors + manifest_errors
    record(
        "check_01a_registry_and_input_cover_each_other",
        not faults,
        f"errors={faults[:5]}",
    )


def check_01b_truth_files_validate_against_the_corpus() -> None:
    """Positive 1b: both ground truth files fit the corpus they adjudicate."""
    known = set(taxonomy_module.load_taxonomy().names())
    bounds = pages_by_file()
    faults = corpus.validate_page_labels(
        corpus.load_page_labels(), known, pages_by_file=bounds
    )
    faults += corpus.validate_chain_labels(
        corpus.load_chain_labels(), pages_by_file=bounds
    )
    # A truth file naming a sample the corpus no longer holds is a migration
    # left half done, which neither validator is asked to notice.
    registered = set(bounds)
    for source, raw in (
        ("page_labels", corpus.load_page_labels()),
        ("chain_labels", corpus.chain_label_samples(corpus.load_chain_labels())),
    ):
        stray = sorted(set(raw) - registered)
        if stray:
            faults.append(f"{source}: adjudicates unregistered {stray}")
    record(
        "check_01b_truth_files_validate_against_the_corpus",
        not faults,
        f"errors={faults[:5]}",
    )


def check_01c_manifest_is_the_registry_rebuilt() -> None:
    """Positive 1c: rebuilding the manifest from the registry changes nothing."""
    entries = corpus.load_registry()
    rebuilt = corpus.build_manifest(entries, manifest())
    record(
        "check_01c_manifest_is_the_registry_rebuilt",
        rebuilt == manifest(),
        "the manifest on disk is not what the registry rebuilds to",
    )


def check_01d_baselines_are_complete() -> None:
    """Positive 1d: every registered sample has its baseline and no retired one lingers."""
    faults = []
    for sample in manifest()["samples"]:
        baseline = sample.get("baseline")
        if not baseline:
            faults.append(f"{sample['file']}: no baseline registered")
            continue
        pdf = ROOT / baseline["pdf"]
        checkpoints = ROOT / baseline["checkpoints"]
        if not pdf.exists():
            faults.append(f"{sample['file']}: baseline PDF missing")
        elif sha256_file(pdf) != baseline["sha256"]:
            faults.append(f"{sample['file']}: baseline PDF digest moved")
        if not checkpoint_module.checkpoint_paths(checkpoints, "*.xml"):
            faults.append(f"{sample['file']}: baseline checkpoints missing")
    for retired in RETIRED_SAMPLES:
        leftovers = sorted(
            path.name for path in BASELINE_DIR.glob(f"{retired}.*")
        ) + sorted(path.name for path in BASELINE_DIR.glob(f"{retired}.checkpoints*"))
        if leftovers:
            faults.append(f"{retired}: retired baseline still present {leftovers}")
        if (INPUT_DIR / f"{retired}.pdf").exists():
            faults.append(f"{retired}.pdf: retired sample still in the input directory")
    record("check_01d_baselines_are_complete", not faults, f"problems={faults[:5]}")


# --- 02 the agreement ---------------------------------------------------------


def check_02a_page_kind_agreement_in_the_constrained_role() -> None:
    """Positive 2a: page kinds agree with the labels on the samples the rate binds on."""
    name = "check_02a_page_kind_agreement_in_the_constrained_role"
    if harness.FAST_TIER:
        harness.fast_skip(name)
        return
    minimum = page_features.load_feature_config()["label_agreement_min"]
    binding = corpus.constrained_samples(manifest())
    hits = total = 0
    misses: list[str] = []
    for sample in binding:
        got, seen, problems = kind_agreement(sample)
        hits += got
        total += seen
        misses.extend(problems)
        print(f"    binding {sample}: {got}/{seen}")
    rate = hits / total if total else 0.0
    record(
        name,
        total > 0 and rate >= minimum,
        f"agreement={rate:.3f} ({hits}/{total}) over {len(binding)} sample(s), "
        f"minimum={minimum}, misses={misses[:5]}",
    )


def check_02b_boundary_agreement_in_the_constrained_role() -> None:
    """Positive 2b: boundaries agree with the adjudications, and no negative links."""
    name = "check_02b_boundary_agreement_in_the_constrained_role"
    if harness.FAST_TIER:
        harness.fast_skip(name)
        return
    minimum = load_chain_config()["boundary_agreement_min"]
    binding = corpus.constrained_samples(manifest())
    truth = corpus.chain_label_samples(corpus.load_chain_labels())
    hits = total = 0
    misses: list[str] = []
    false_links: list[str] = []
    for sample in binding:
        got, seen, problems = boundary_agreement(sample)
        hits += got
        total += seen
        misses.extend(problems)
        report = runs().get(sample, {}).get("report")
        verdicts = (
            {entry["boundary"]: bool(entry.get("linked")) for entry in report["boundaries"]}
            if report
            else {}
        )
        for key, entry in truth.get(sample, {}).items():
            if not entry["link"] and verdicts.get(key):
                false_links.append(f"{sample} {key}")
        print(f"    binding {sample}: {got}/{seen}")
    rate = hits / total if total else 0.0
    record(
        name,
        total > 0 and rate >= minimum and not false_links,
        f"agreement={rate:.3f} ({hits}/{total}) over {len(binding)} sample(s), "
        f"minimum={minimum}, false_links={false_links}, misses={misses[:5]}",
    )


def check_02c_observed_samples_are_measured_not_gated() -> None:
    """Positive 2c: a sample outside the role is measured, and no rate of it binds.

    What this asserts is that the numbers exist. Their value is the report's
    business: the corpus carries them so a later calibration for that
    distribution has something to be judged against, and gating on them now
    would be gating on a distribution nothing was tuned for.
    """
    name = "check_02c_observed_samples_are_measured_not_gated"
    if harness.FAST_TIER:
        harness.fast_skip(name)
        return
    binding = set(corpus.constrained_samples(manifest()))
    observed = [
        sample["file"] for sample in manifest()["samples"] if sample["file"] not in binding
    ]
    faults = []
    if not observed:
        faults.append("no sample sits outside the constrained role")
    for sample in observed:
        kind_hits, kind_total, _ = kind_agreement(sample)
        link_hits, link_total, problems = boundary_agreement(sample)
        if kind_total == 0:
            faults.append(f"{sample}: no page label to measure against")
        if link_total == 0:
            faults.append(f"{sample}: no boundary measured ({problems[:2]})")
        print(
            f"    observed {sample}: page kind {kind_hits}/{kind_total}, "
            f"boundaries {link_hits}/{link_total}"
        )
    record(name, not faults, f"problems={faults[:5]}")


def check_02d_no_false_link_anywhere() -> None:
    """Negative 2d: no adjudicated negative is linked, on any sample at all.

    The agreement rate is scoped by role because a rate is a measurement of a
    distribution. This is not a rate: joining two pages the corpus owner ruled
    unconnected corrupts the translation unit, and it is as wrong on a sample
    nothing was tuned for as on one that was. The hard line therefore covers the
    whole corpus.
    """
    name = "check_02d_no_false_link_anywhere"
    if harness.FAST_TIER:
        harness.fast_skip(name)
        return
    truth = corpus.chain_label_samples(corpus.load_chain_labels())
    false_links = []
    negatives = 0
    for sample, entries in truth.items():
        report = runs().get(sample, {}).get("report")
        verdicts = (
            {
                entry["boundary"]: bool(entry.get("linked"))
                for entry in report["boundaries"]
            }
            if report
            else {}
        )
        for key, adjudication in entries.items():
            if adjudication["link"]:
                continue
            negatives += 1
            if verdicts.get(key):
                false_links.append(f"{sample} {key}")
    record(
        name,
        not false_links and negatives > 0,
        f"negatives={negatives} false_links={false_links}",
    )


# --- 03 the checkpoint escape -------------------------------------------------


def check_03a_escape_is_a_bijection() -> None:
    """Positive 3a: encoding then decoding returns the string, escape sequences included."""
    faults = []
    for probe in ESCAPE_PROBES:
        encoded = checkpoint_module.escape_text(probe)
        if checkpoint_module.unescape_text(encoded) != probe:
            faults.append(f"{probe!r} did not survive the round trip")
        if checkpoint_module._XML_ILLEGAL.search(encoded):
            faults.append(f"{probe!r} encoded to something XML still cannot carry")
    # Distinct inputs stay distinct, which is the half a reversal alone does not
    # give: without the lead being doubled these two would collide.
    if checkpoint_module.escape_text("\\u001a") == checkpoint_module.escape_text("\x1a"):
        faults.append("a literal escape sequence collides with the codepoint it names")
    record("check_03a_escape_is_a_bijection", not faults, "; ".join(faults[:5]))


def check_03b_documents_needing_no_escape_are_untouched() -> None:
    """Negative 3b: a document XML can carry goes through the escape untouched.

    This is what keeps every checkpoint written before this batch readable: a
    file whose document needs no escape carries no marker and is serialised by
    the path that existed before, so a literal lead in an older file is never
    mistaken for one. The comparison is against what the plain serialiser
    produces rather than against the bytes on disk, which is the normalisation
    the canonical form is defined at.
    """
    faults = []
    marked = []
    plain = checkpoint_module._converter()
    for directory in baseline_checkpoint_containers():
        for path in checkpoint_module.checkpoint_paths(directory, "*.xml"):
            text = checkpoint_module.read_checkpoint_text(path)
            docs = checkpoint_module.load_checkpoint(path)
            has_illegal = checkpoint_module._holds_illegal(docs)
            declares = checkpoint_module._ESCAPE_MARKER in text
            if declares != has_illegal:
                faults.append(
                    f"{directory.name}/{path.name}: marker={declares} "
                    f"illegal={has_illegal}"
                )
            if declares:
                marked.append(f"{directory.name}/{path.name}")
                continue
            if checkpoint_module.to_checkpoint_xml(docs) != plain.to_xml(docs):
                faults.append(f"{directory.name}/{path.name}: the escape path was taken")
    if not marked:
        faults.append("no baseline checkpoint carries the escape, so nothing proves it")
    record(
        "check_03b_documents_needing_no_escape_are_untouched",
        not faults,
        f"marked={marked} problems={faults[:5]}",
    )


def check_03c_the_corpus_codepoint_survives() -> None:
    """Positive 3c: the codepoint that forced the escape is in the checkpoint it was in."""
    faults = []
    found = []
    for directory in baseline_checkpoint_containers():
        for path in checkpoint_module.checkpoint_paths(directory, "*.xml"):
            if checkpoint_module._ESCAPE_MARKER not in (
                checkpoint_module.read_checkpoint_text(path)
            ):
                continue
            docs = checkpoint_module.load_checkpoint(path)
            for page in docs.page:
                for index, char in enumerate(page.pdf_character or []):
                    value = char.char_unicode or ""
                    if checkpoint_module._XML_ILLEGAL.search(value):
                        found.append(
                            f"{directory.name} p{page.page_number} #{index} "
                            f"U+{ord(value):04X}"
                        )
            # The canonical form of an escaped checkpoint is stable: reading it
            # and writing it again produces what reading that again produces.
            once = checkpoint_module.to_checkpoint_xml(docs)
            twice = checkpoint_module.to_checkpoint_xml(
                checkpoint_module.from_checkpoint_xml(once)
            )
            if once != twice:
                faults.append(f"{directory.name}/{path.name}: canonical form moves")
    if not found:
        faults.append("no escaped codepoint was recovered from any checkpoint")
    record(
        "check_03c_the_corpus_codepoint_survives",
        not faults,
        f"recovered={found} problems={faults[:5]}",
    )


# --- 04 determinism over the refreshed corpus ---------------------------------


def check_04_classification_is_reproducible() -> None:
    """Positive 4: classifying a sample twice produces the same verdicts.

    The second pass reads the checkpoint the first one wrote rather than running
    the pipeline again: what is asserted is that the verdicts survive the format
    they are stored in, which is the property the refresh put at risk.
    """
    name = "check_04_classification_is_reproducible"
    if harness.FAST_TIER:
        harness.fast_skip(name)
        return
    faults = []
    checked = 0
    for sample, run in runs().items():
        built = run["artifacts"]
        stem = checkpoint_module.checkpoint_stem("page_classifier")
        path = built.working_dir / f"{stem}.xml"
        if not path.exists():
            faults.append(f"{sample}: no classifier checkpoint")
            continue
        docs = checkpoint_module.load_checkpoint(path)
        again = checkpoint_module.from_checkpoint_xml(
            checkpoint_module.to_checkpoint_xml(docs)
        )
        first = [page.page_kind for page in docs.page]
        second = [page.page_kind for page in again.page]
        if first != second:
            faults.append(f"{sample}: {first} against {second}")
        if first != [run["kinds"][key] for key in sorted(run["kinds"], key=int)]:
            faults.append(f"{sample}: the run and the checkpoint disagree")
        checked += 1
    record(name, not faults and checked > 0, f"samples={checked} problems={faults[:5]}")


def check_04c_incomplete_build_is_not_published() -> None:
    """Negative 4c: a run that produced nothing leaves no slot for a gate to read.

    The failure this closes is silent: `translate` swallows some failures and
    returns a result with no PDF, the cache published that as a finished slot,
    and every later gate served from it measured an empty working directory as
    zero agreement against the ground truth. What has to happen instead is that
    the build refuses to publish and the consumer is told, so the run is
    reproduced here with a translate that returns exactly that.
    """
    from babeldoc.format.pdf import high_level

    sample = INPUT_DIR / manifest()["samples"][0]["file"]
    cache_root = _tmp_root / "cache_refusal"
    faults = []

    class NothingProduced:
        mono_pdf_path = None

    previous_root = artifacts.CACHE_ROOT
    previous_translate = high_level.translate
    artifacts.CACHE_ROOT = cache_root
    high_level.translate = lambda config: NothingProduced()
    try:
        raised = None
        try:
            artifacts.get_artifacts(sample, "parse_only")
        except artifacts.BuildIncomplete as exc:
            raised = exc
        except Exception as exc:  # noqa: BLE001 - any other failure is reported too
            faults.append(f"raised {type(exc).__name__} rather than BuildIncomplete")
        if raised is None and not faults:
            faults.append("an empty run was accepted")
        published = [path for path in cache_root.rglob("meta.json")]
        if published:
            faults.append(f"a slot was published anyway: {published}")
        if not list(cache_root.rglob("*.partial")):
            faults.append("the failed run left no staging directory to look at")
    finally:
        artifacts.CACHE_ROOT = previous_root
        high_level.translate = previous_translate
    record(
        "check_04c_incomplete_build_is_not_published", not faults, "; ".join(faults)
    )


def stub_translation(document, label: str, apply_ruling: bool) -> str:
    """Run the translation stage over one document, as serialised XML plus prompts.

    The translator is a stub that echoes its input, so the run needs no
    credential and no network. What the two passes are compared on is the
    document and the set of prompts, both of which a ruling does change.
    """
    from babeldoc.format.pdf import high_level
    from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
        ILTranslatorLLMOnly,
    )
    from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.progress_monitor import ProgressMonitor
    from babeldoc.translator.translator import BaseTranslator
    from babeldoc.translator.translator import set_translate_rate_limiter

    class StubTranslator(BaseTranslator):
        name = "b7-5-stub"

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
            if INPUT_HEADER not in text:
                return FALLBACK_REPLY
            return json.dumps(
                [
                    {"id": item["id"], "output": item["input"]}
                    for item in json.loads(text.split(INPUT_HEADER, 1)[1].strip())
                ]
            )

    set_translate_rate_limiter(STUB_MAX_QPS)
    work = _tmp_root / "identity" / label
    work.mkdir(parents=True, exist_ok=True)
    monitor = ProgressMonitor([(ILTranslatorLLMOnly.stage_name, 1.0)])
    monitor.disable = True
    config = TranslationConfig(
        translator=StubTranslator(),
        input_file=str(INPUT_DIR / f"{label.split('.')[0]}.pdf"),
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        working_dir=work,
        output_dir=work / "out",
        progress_monitor=monitor,
        auto_extract_glossary=False,
        qps=STUB_MAX_QPS,
        magazine_hitl_apply=apply_ruling,
    )
    # The hook the pipeline reaches between extraction and the translator,
    # called here as the pipeline calls it so the identity is over that path.
    high_level.hitl.after_term_extract(config, document)
    stage = ILTranslatorLLMOnly(config.translator, config)
    stage.translate(document)
    # Sorted, because the order prompts arrive in is the order the pool
    # scheduled them in and is not a property of the ruling.
    prompts = "\n".join(sorted(config.translator.prompts))
    return checkpoint_module.to_checkpoint_xml(document) + "\n" + prompts


def check_04b_two_pass_identity() -> None:
    """Positive 4b: an empty ruling changes nothing, on every refreshed sample.

    The property is the one the human loop rests on: applying a ruling that
    rules on nothing has to be the run that would have happened with the switch
    down. B7 established it on one sample; the refresh is what puts it at risk
    again, so it is re-run here over every sample the corpus now holds.
    """
    name = "check_04b_two_pass_identity"
    if harness.FAST_TIER:
        harness.fast_skip(name)
        return
    reviews = _tmp_root / "reviews_identity"
    reviews.mkdir(parents=True, exist_ok=True)
    previous = os.environ[hitl.REVIEWS_ENV]
    os.environ[hitl.REVIEWS_ENV] = str(reviews)
    faults = []
    checked = 0
    try:
        for sample, run in runs().items():
            stem = Path(sample).stem
            # An empty ruling for this sample, which is what the pass applies.
            with (reviews / f"{stem}{hitl.DECISIONS_SUFFIX}").open(
                "w", encoding="utf-8"
            ) as f:
                json.dump({}, f)
            path = (
                run["artifacts"].working_dir
                / f"{checkpoint_module.checkpoint_stem('page_classifier')}.xml"
            )
            if not path.exists():
                faults.append(f"{sample}: no classified checkpoint")
                continue
            first = stub_translation(
                checkpoint_module.load_checkpoint(path), f"{stem}.1", False
            )
            second = stub_translation(
                checkpoint_module.load_checkpoint(path), f"{stem}.2", True
            )
            if first != second:
                faults.append(f"{sample}: the two passes differ")
            if (_tmp_root / "identity" / f"{stem}.2" / hitl.REPORT_NAME).exists():
                faults.append(f"{sample}: an empty ruling left a report")
            checked += 1
    finally:
        os.environ[hitl.REVIEWS_ENV] = previous
    record(name, not faults and checked > 0, f"samples={checked} problems={faults[:3]}")


# --- 07 the masthead ruling ---------------------------------------------------


def masthead_evidence() -> dict:
    with MASTHEAD_EVIDENCE.open(encoding="utf-8") as f:
        return json.load(f)


def check_07a_masthead_ruling_reached_what_it_could() -> None:
    """Positive 7a: every site the ruling matched renders the ruled name.

    The b6.2 gap was the document rendering its own masthead two ways with
    nothing able to settle it. What settles it is the ruling, and this is the
    measurement of how far it got: every site it matched carries the ruled name
    and no site it matched was left on its old rendering.
    """
    data = masthead_evidence()
    faults = []
    matched = [site for site in data["sites"] if site["reach"] == "ruling_matched"]
    if not matched:
        faults.append("the ruling matched no site at all")
    for site in matched:
        if not site["carries_ruled_name"]:
            faults.append(f"{site['paragraph']}: does not carry the ruled name")
        if not site["moved"]:
            faults.append(f"{site['paragraph']}: unchanged by the ruling")
    # The ruling is the file the corpus owner wrote, unedited by any machine
    # since the run. Read as a superset rather than as an equality, under
    # CLAUDE.md 4.12: the owner may add to a ruling between batches and did, so
    # what this can assert is that every term the run applied is still on disk
    # rendering the same way. A term the run applied that has gone missing, or
    # come back rendered differently, is the defect this was written for; a term
    # the owner added afterwards is not.
    with (ROOT / "reviews" / "Courier-en.decisions.json").open(encoding="utf-8") as f:
        written = json.load(f)
    on_disk = written.get("terms") or {}
    for term, rendering in (data["ruling"]["terms"] or {}).items():
        if term not in on_disk:
            faults.append(f"{term!r}: the run applied it and the ruling no longer has it")
        elif on_disk[term] != rendering:
            faults.append(f"{term!r}: rendered differently on disk than the run applied")
    record(
        "check_07a_masthead_ruling_reached_what_it_could",
        not faults,
        f"matched={len(matched)} problems={faults[:3]}",
    )


def check_07b_unreached_sites_are_recorded() -> None:
    """Positive 7b: each site the ruling could not reach is named, with its reason.

    Two mechanisms keep a site out of reach and they are not the same defect. A
    paragraph the parser recovered outside any block is never offered to the
    translator, so no prompt exists to carry a ruling. A paragraph that is
    offered can still be unreachable, because the text a batch is built from
    carries the markup its style runs imply and a display masthead set in
    several styles is not the joined rendering the review draft showed the human
    who wrote the ruling. The second is the sharper requirement: it is a silent
    disagreement between what a human is shown and what the machine matches on.
    """
    data = masthead_evidence()
    faults = []
    not_offered = [site for site in data["sites"] if site["reach"] == "not_offered"]
    unmatched = [
        site for site in data["sites"] if site["reach"] == "offered_but_unmatched"
    ]
    if not not_offered:
        faults.append("no site is recorded as never offered to the translator")
    for site in not_offered:
        if site["pass1"] != site["source"] or site["pass2"] != site["source"]:
            faults.append(f"{site['paragraph']}: was translated after all")
        if site["layout_label"] != UNREACHABLE_LABEL:
            faults.append(f"{site['paragraph']}: label is {site['layout_label']}")
    for site in unmatched:
        if site["moved"]:
            faults.append(f"{site['paragraph']}: moved without the ruling matching")
    # The mechanism behind the unmatched site, captured from the built prompts.
    offered = data["offered_text"]
    unreached = [
        source
        for source, matches in offered["ruled_source_matches_offered_text"].items()
        if not matches
    ]
    if unmatched and not unreached:
        faults.append("a site went unmatched but every ruled source matched something")
    record(
        "check_07b_unreached_sites_are_recorded",
        not faults,
        f"not_offered={[s['paragraph'] for s in not_offered]} "
        f"offered_but_unmatched={[s['paragraph'] for s in unmatched]} "
        f"ruled_sources_matching_nothing={unreached} problems={faults[:3]}",
    )


def check_07c_blast_radius_is_bounded() -> None:
    """Negative 7c: the ruling perturbed only batches whose prompt it changed.

    Pass two replays from the project cache every request whose prompt text the
    ruling left alone, so the number of live calls bounds how much of the
    document could have moved at all. A paragraph outside those batches was
    served from the cache and is unchanged by construction; the controls are
    the ones inside no ruled batch, and they are checked to have held still.
    """
    data = masthead_evidence()
    with LEDGER.open(encoding="utf-8") as f:
        ledger = {entry["pass"]: entry for entry in json.load(f)}
    faults = []
    if ledger["pass1"]["api_calls"] != 0:
        faults.append(
            f"pass one spent {ledger['pass1']['api_calls']} call(s); it should "
            "have replayed the frozen cache entirely"
        )
    live = ledger["pass2"]["api_calls"]
    if live == 0:
        faults.append("pass two changed no prompt at all")
    if live >= ledger["pass2"]["requests"]:
        faults.append("pass two replayed nothing, so the cache was not frozen")
    held = [control for control in data["controls"] if control["identical"]]
    if not held:
        faults.append("no control paragraph held still")
    record(
        "check_07c_blast_radius_is_bounded",
        not faults,
        f"pass1_api_calls={ledger['pass1']['api_calls']} "
        f"pass2_api_calls={live}/{ledger['pass2']['requests']} "
        f"changed={len(data['changed_paragraphs'])}/{data['paragraphs']} "
        f"controls_held={len(held)}/{len(data['controls'])} problems={faults[:3]}",
    )


def check_07d_report_quotes_the_evidence() -> None:
    """Positive 7d: the delivery report states what the evidence files hold.

    A report quoting numbers no artefact carries is the failure this catches,
    and it is the one that matters most for a document whose whole purpose is to
    be read instead of the artefacts.
    """
    faults = []
    if not REPORT.exists():
        record("check_07d_report_quotes_the_evidence", False, "no report written")
        return
    text = REPORT.read_text(encoding="utf-8")
    data = masthead_evidence()
    with LEDGER.open(encoding="utf-8") as f:
        ledger = {entry["pass"]: entry for entry in json.load(f)}
    counts = {
        "ruling matched": data["ruling_matched"],
        "offered but unmatched": data["offered_but_unmatched"],
        "not offered": data["not_offered"],
    }
    for label, count in counts.items():
        if label not in text:
            faults.append(f"the report does not name the {label} outcome")
    quoted = [
        str(ledger["pass2"]["api_calls"]),
        str(ledger["pass1"]["requests"]),
        f"{len(data['changed_paragraphs'])} of {data['paragraphs']}",
    ]
    for value in quoted:
        if value not in text:
            faults.append(f"the report does not quote {value!r}")
    for site in data["sites"]:
        if site["paragraph"] not in text:
            faults.append(f"the report does not name {site['paragraph']}")
    record("check_07d_report_quotes_the_evidence", not faults, f"problems={faults[:4]}")


# --- 05 the scope -------------------------------------------------------------


def check_05a_truth_files_are_unchanged() -> None:
    """Negative 5a: the owner's files carry the digests they were delivered with.

    The ground truth of the corpus and the ruling the human wrote are both here.
    The machine reads all four and writes none of them, so a difference is a
    machine edit rather than a revision: a revision arrives with a session that
    says so and repins these.
    """
    faults = []
    for relative, expected in TRUTH_DIGESTS.items():
        path = ROOT / relative
        if not path.exists():
            faults.append(f"{relative}: missing")
            continue
        actual = sha256_file(path)
        if actual != expected:
            faults.append(f"{relative}: {actual} against {expected}")
    record("check_05a_truth_files_are_unchanged", not faults, "; ".join(faults))


def check_05b_no_retired_name_survives() -> None:
    """Negative 5b: no retired sample name is still resolved by code or configuration.

    The corpus registry and the manifest are outside the scan: the owner's notes
    record which sample superseded which, and that sentence is the migration's
    documentation rather than a reference left dangling.
    """
    faults = []
    here = Path(__file__).name
    for directory in SCAN_DIRECTORIES:
        base = ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".json", ".md", ".txt"):
                continue
            if path.name == here:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for retired in RETIRED_SAMPLES:
                # The superseding sample's name contains the retired one, so the
                # match has to end where the retired name does.
                for suffix in (".pdf", '"', "'", " ", ".checkpoints"):
                    if f"{retired}{suffix}" in text:
                        faults.append(
                            f"{path.relative_to(ROOT).as_posix()} names {retired}"
                        )
                        break
    record(
        "check_05b_no_retired_name_survives",
        not faults,
        f"survivors={sorted(set(faults))[:5]}",
    )


def check_05c_change_scope() -> None:
    """Negative 5c: nothing upstream moved and nothing outside the declared paths."""
    changed = changed_paths()
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and path not in ALLOWED_FILES
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
    record("check_05c_change_scope", not faults, "; ".join(faults))


def check_05d_no_retune_happened() -> None:
    """Negative 5d: the tuning configuration did not move.

    The refresh was authorised to retune if the constrained rates fell. They did
    not, so an edit to either file is a change nothing in this batch accounts
    for, and the record of that is this assertion passing.
    """
    changed = changed_paths()
    moved = sorted(path for path in TUNING_CONFIGS if path in changed)
    record(
        "check_05d_no_retune_happened",
        not moved,
        f"tuning configuration changed: {moved}",
    )


def check_05e_ascii_prose() -> None:
    """Negative 5e: the code this batch changed carries no non-ASCII prose."""
    faults = []
    for relative in (
        "babeldoc/magazine/checkpoint.py",
        "babeldoc/magazine/corpus.py",
        "tools/corpus_check.py",
        "spec_checks/spec_check_b0.py",
        "spec_checks/spec_check_b1.py",
        "spec_checks/spec_check_b2.py",
        "spec_checks/spec_check_b2_2.py",
        "spec_checks/spec_check_b2_7.py",
        "spec_checks/spec_check_b3.py",
        "spec_checks/spec_check_b4.py",
        "spec_checks/spec_check_b6.py",
        "spec_checks/run_all.py",
        f"spec_checks/{Path(__file__).name}",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{relative}:{number}")
    record("check_05e_ascii_prose", not faults, f"lines={faults[:5]}")


# --- 06 the sweep -------------------------------------------------------------


def check_06_sweep() -> None:
    """Positive 6: every earlier gate still passes over the refreshed corpus."""
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
        check_01a_registry_and_input_cover_each_other,
        check_01b_truth_files_validate_against_the_corpus,
        check_01c_manifest_is_the_registry_rebuilt,
        check_01d_baselines_are_complete,
        check_02a_page_kind_agreement_in_the_constrained_role,
        check_02b_boundary_agreement_in_the_constrained_role,
        check_02c_observed_samples_are_measured_not_gated,
        check_02d_no_false_link_anywhere,
        check_03a_escape_is_a_bijection,
        check_03b_documents_needing_no_escape_are_untouched,
        check_03c_the_corpus_codepoint_survives,
        check_04_classification_is_reproducible,
        check_04b_two_pass_identity,
        check_04c_incomplete_build_is_not_published,
        check_05a_truth_files_are_unchanged,
        check_05b_no_retired_name_survives,
        check_05c_change_scope,
        check_05d_no_retune_happened,
        check_05e_ascii_prose,
        check_07a_masthead_ruling_reached_what_it_could,
        check_07b_unreached_sites_are_recorded,
        check_07c_blast_radius_is_bounded,
        check_07d_report_quotes_the_evidence,
        check_06_sweep,
    ]
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(check.__name__, False, f"raised {exc!r}")
    print(f"\nspec_check_b7_5: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    _timer.write()
    _timer.print_summary()
    artifacts.print_stats("spec_check_b7_5")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
