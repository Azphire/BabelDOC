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
decide whether the tuned thresholds still hold.

03 is the checkpoint escape the refresh forced. A sample whose font names an
Adobe glyph list control glyph puts a codepoint in the IL that XML 1.0 cannot
carry in any form. The encoding that lets a checkpoint hold it has to be a
bijection -- including on a document that spells an escape sequence out --  and
has to leave every document that needs no escape exactly as it was, or every
checkpoint written before this batch would stop reading.

04 is determinism over the refreshed corpus: the same sample classified twice
produces the same verdicts. The two-pass identity of the human ruling loop is a
different property over a different artefact and belongs to T7.5.2, which reruns
it against the frozen cache.

05 is the scope. The three ground truth files are the corpus owner's; this batch
reads them and their digests are pinned here, so a machine edit is a failure
rather than a diff nobody looked at. No retired file name survives anywhere. The
tuning configuration did not move, which is the record that no retune happened.

Tiers: 02 and 04 need pipeline artefacts and belong to the pipeline tier; the
rest are static.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import page_features  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.chain_builder import REPORT_NAME  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b7.5.1"

PYTHON = sys.executable

BASELINE_DIR = ROOT / "examples" / "output" / "baseline"
INPUT_DIR = ROOT / "examples" / "input"

# The corpus owner's files, pinned at the digests they were delivered with. The
# batch reads them and never writes them, so a difference here is a machine edit
# and not a corpus revision: a revision arrives with a session that says so and
# repins these.
TRUTH_DIGESTS = {
    "corpus/registry.user.json": (
        "6747286f971e38ae54c8481d750576b9ee3b2b0fc51f62d82ec2b9c24341e5b8"
    ),
    "corpus/page_labels.json": (
        "eabef80e11262f1d56d750cf71905cf9a3427e56af2081edb17468a0e5bbb2c6"
    ),
    "corpus/chain_labels.user.json": (
        "71629c8dae18af77836cac6113186811cff13b617ed7b09d682ad47cca829687"
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
        if not checkpoints.is_dir() or not list(checkpoints.glob("*.xml")):
            faults.append(f"{sample['file']}: baseline checkpoints missing")
    for retired in RETIRED_SAMPLES:
        leftovers = sorted(
            path.name for path in BASELINE_DIR.glob(f"{retired}.*")
        ) + sorted(path.name for path in BASELINE_DIR.glob(f"{retired}.checkpoints"))
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
    for directory in sorted(BASELINE_DIR.glob("*.checkpoints")):
        for path in sorted(directory.glob("*.xml")):
            text = path.read_text(encoding="utf-8")
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
    for directory in sorted(BASELINE_DIR.glob("*.checkpoints")):
        for path in sorted(directory.glob("*.xml")):
            if checkpoint_module._ESCAPE_MARKER not in path.read_text(encoding="utf-8"):
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


# --- 05 the scope -------------------------------------------------------------


def check_05a_truth_files_are_unchanged() -> None:
    """Negative 5a: the corpus owner's files carry the digests they were delivered with."""
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
        check_03a_escape_is_a_bijection,
        check_03b_documents_needing_no_escape_are_untouched,
        check_03c_the_corpus_codepoint_survives,
        check_04_classification_is_reproducible,
        check_05a_truth_files_are_unchanged,
        check_05b_no_retired_name_survives,
        check_05c_change_scope,
        check_05d_no_retune_happened,
        check_05e_ascii_prose,
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
