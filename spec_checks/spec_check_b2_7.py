"""Gate script for batch B2.7 (percentile vocabulary unlock, cache maintenance).

Run from the repository root:

    python spec_checks/spec_check_b2_7.py

Exit code 0 when every assertion in plans/PLAN_B2_7.md passes, 1 otherwise.
Requires no API key: the pipeline is exercised with skip_translation.

The batch's decision is that the percentile candidate vocabulary is *not*
adopted. Both measured agreement tables are frozen here as a regression
baseline, so the shipped ruleset and the archived candidate stay comparable and
neither can drift unnoticed before the model assisted classifier lands.

One assertion drives a whole sweep (05). Under spec_checks/run_all.py it is
suppressed, the same SPEC_NO_NESTED contract the earlier gates use; running
this file on its own executes it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine import page_features  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402
from spec_checks import run_all as runner  # noqa: E402

PYTHON = sys.executable
# Tag that freezes this batch; once it exists the scope assertions read the
# delta it introduced instead of the working tree.
BATCH_TAG = "batch-b2.7"
# The commit this batch builds on. The shipped vocabulary must equal the one it
# carries, byte for byte, because the candidate was not adopted.
PREVIOUS_TAG = "batch-b2.6"

MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
LABELS_PATH = ROOT / "corpus" / "page_labels.json"
INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output" / "b2_7"

TAXONOMY_PATH = ROOT / "configs" / "page_types.json"
CANDIDATE_PATH = ROOT / "configs" / "page_types.pctl.json"

# Hand written corpus files no batch may touch without the corpus owner saying
# so; the machine side rebuilds the manifest from the registry and reads both.
FROZEN_CORPUS_FILES = {
    "corpus/page_labels.json",
    "corpus/registry.user.json",
    "corpus/manifest.json",
}

# Files this batch is allowed to change, per PLAN_B2_7 negative assertion 8.
ALLOWED_CHANGES = {
    "CLAUDE.md",
    "babeldoc/magazine/taxonomy.py",
    "configs/gate_cache.json",
    "configs/page_features.json",
    "configs/page_types.pctl.json",
    "plans/PLAN_B2_7.md",
    "spec_checks/artifacts.py",
    "spec_checks/run_all.py",
    "spec_checks/spec_check_b2_1.py",
    "spec_checks/spec_check_b2_2.py",
    "spec_checks/spec_check_b2_7.py",
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

# Documents whose prose is Chinese by design; the CJK scan covers code only.
CJK_SCAN_SUFFIXES = (".py", ".json")
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# Agreement measured in T2.7c, as (kind hits, labelled pages). Frozen numbers:
# the point of recomputing them here is that a later edit to a threshold, a
# feature or the corpus cannot move either table without saying so.
RAW_AGREEMENT = {
    "": (28, 31),
    "aramcoworld": (6, 8),
    "cern_courier": (3, 4),
    "imf_fd": (8, 8),
    "unesco_courier": (8, 8),
    "vogue_us": (3, 3),
}
CANDIDATE_AGREEMENT = {
    "": (28, 31),
    "aramcoworld": (8, 8),
    "cern_courier": (2, 4),
    "imf_fd": (8, 8),
    "unesco_courier": (7, 8),
    "vogue_us": (3, 3),
}

# Largest per publication fall the adoption criterion tolerates.
MAX_FAMILY_DROP = 0.1

# The T2.7c verdict. The candidate ties the shipped ruleset overall but loses a
# quarter of one publication family, which the criterion does not allow.
CANDIDATE_ADOPTED = False

# Percentile evidence thresholds the validator must refuse and must accept. The
# refusals bracket the midrank a constant feature column lands on, which is the
# value the rule exists to keep positive evidence clear of.
REJECTED_PCTL_THRESHOLDS = (0.0, 0.25, 0.4, 0.5)
ACCEPTED_PCTL_THRESHOLDS = (0.55, 0.7, 0.9)

# Set by spec_checks/run_all.py. The sweep assertion is the fallback for running
# this file on its own; under the runner it would repeat the sweep in progress.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Checks that need an artefact built during this run.
PIPELINE_TIER = ("check_01_pctl_scoring", "check_03_agreement_tables")

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b2_7_"))
_timer = harness.Timer("spec_check_b2_7")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


# --- helpers ----------------------------------------------------------------


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def batch_tag_exists() -> bool:
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{BATCH_TAG}^{{commit}}"])
    return code == 0


def changed_files() -> set[str]:
    """Every path this batch changed.

    Before the batch is committed that is the working tree delta against HEAD.
    Once the batch is tagged the same delta is the tag against its parent, so a
    later batch can re-run this gate without its own changes counting here.
    """
    if batch_tag_exists():
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^", BATCH_TAG])
        return {line.strip() for line in listing.splitlines() if line.strip()}

    _, listing = git_output(["status", "--porcelain", "--untracked-files=all"])
    paths: set[str] = set()
    for line in listing.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def classifier_checkpoint(working_dir: Path) -> Path:
    stem = checkpoint_module.checkpoint_stem("page_classifier")
    return working_dir / f"{stem}.xml"


def synthetic_pctl_vocabulary() -> taxonomy_module.Taxonomy:
    """Smallest vocabulary that exercises a percentile rule end to end.

    One type, one positive evidence rule on a percentile companion and one
    penalty on a raw feature: enough for scoring to have to resolve both key
    families, and small enough that a failure names the cause.
    """
    percentile = page_features.percentile_feature_names()[0]
    raw = {
        "taxonomy_version": "synthetic",
        "ambiguity_margin": 0.1,
        "default_type": "probe",
        "require_positive_evidence": True,
        "page_types": [
            {
                "name": "probe",
                "description": "Synthetic probe type over one percentile feature.",
                "rules": [
                    {
                        "feature": percentile,
                        "op": "ge",
                        "threshold": 0.55,
                        "weight": 2.0,
                    },
                    {
                        "feature": page_features.FEATURE_NAMES[0],
                        "op": "ge",
                        "threshold": 0.9,
                        "weight": -1.0,
                    },
                ],
                "policy": {
                    "chain_eligible": False,
                    "translate": True,
                    "repair_profile": "flow",
                },
            }
        ],
    }
    return taxonomy_module.parse_taxonomy(raw, "synthetic")


def candidate_rules(raw: dict) -> list[tuple[str, dict]]:
    return [
        (entry["name"], rule) for entry in raw["page_types"] for rule in entry["rules"]
    ]


def agreement_table(
    vocabulary: taxonomy_module.Taxonomy,
    classified: dict[str, Path],
    labels: dict[str, dict[str, list[str]]],
    publication_of: dict[str, str],
) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """Kind agreement of ``vocabulary``, overall and per publication.

    Reclassifies the corpus offline from the checkpoints the classifier stage
    produced, using the document level vectors the stage itself scores against.
    The empty key holds the pooled figure.
    """
    config = page_features.load_feature_config()
    tallies: dict[str, list[int]] = {}
    misses: list[str] = []
    for file_name, expected_by_page in labels.items():
        stem = Path(file_name).stem
        publication = publication_of.get(file_name, file_name)
        docs = checkpoint_module.load_checkpoint(
            classifier_checkpoint(classified[stem])
        )
        vectors = page_features.extract_document_features(docs, config)
        kinds: dict[str, str] = {}
        for position, (page, vector) in enumerate(zip(docs.page, vectors, strict=True)):
            index = page.page_number if page.page_number is not None else position
            kinds[str(index + 1)] = taxonomy_module.classify(vector, vocabulary).kind
        tally = tallies.setdefault(publication, [0, 0])
        for page_number, accepted in sorted(
            expected_by_page.items(), key=lambda item: int(item[0])
        ):
            tally[1] += 1
            actual = kinds.get(page_number)
            if actual in accepted:
                tally[0] += 1
            else:
                misses.append(
                    f"{file_name}#{page_number}: {actual!r} not in {accepted}"
                )
    table = {name: (hits, total) for name, (hits, total) in tallies.items()}
    table[""] = (
        sum(hits for hits, _ in table.values()),
        sum(total for _, total in table.values()),
    )
    return table, misses


def rate(pair: tuple[int, int]) -> float:
    hits, total = pair
    return hits / total if total else 0.0


# --- assertions -------------------------------------------------------------


def check_01_pctl_scoring(classified: dict[str, Path]) -> None:
    """A vocabulary with a percentile rule scores; the per-page vector cannot.

    01b is the defect T2.7a repaired stated as an assertion: feeding
    ``extract_page_features`` output to a vocabulary that references a
    percentile companion is a lookup failure, not a low score, so a gate doing
    that was not testing what it claimed to.
    """
    vocabulary = synthetic_pctl_vocabulary()
    config = page_features.load_feature_config()
    name, working = next(iter(sorted(classified.items())))
    docs = checkpoint_module.load_checkpoint(classifier_checkpoint(working))
    vectors = page_features.extract_document_features(docs, config)

    scored = 0
    out_of_range: list[str] = []
    failure = ""
    try:
        for page, vector in zip(docs.page, vectors, strict=True):
            for kind, score in taxonomy_module.score_page_types(
                vector, vocabulary
            ).items():
                scored += 1
                if not 0.0 <= score <= 1.0:
                    out_of_range.append(f"{name}#{page.page_number}:{kind}={score}")
    except KeyError as exc:
        failure = f"KeyError {exc}"
    record(
        "01a a vocabulary carrying a percentile rule scores the document vectors",
        scored > 0 and not out_of_range and not failure,
        f"sample={name} scores={scored} failure={failure} "
        f"out_of_range={out_of_range[:3]}",
    )

    page = docs.page[0]
    per_page = page_features.extract_page_features(page, docs, config)
    try:
        taxonomy_module.score_page_types(per_page, vocabulary)
        rejected = False
    except KeyError:
        rejected = True
    record(
        "01b the per-page vector alone cannot satisfy a percentile rule lookup",
        rejected,
        f"percentile_keys_in_page_vector="
        f"{[k for k in per_page if k.endswith(page_features.PERCENTILE_SUFFIX)]}",
    )

    # The production stage and the repaired gate assertion must read the same
    # keys, which is what makes 01a evidence about production at all.
    expected = set(page_features.known_feature_names())
    actual = set(vectors[0])
    record(
        "01c the document vector carries exactly the feature names a rule may use",
        actual == expected,
        f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}",
    )


def check_02_pctl_evidence_rule() -> None:
    """Positive evidence on a percentile feature must clear the constant midrank."""
    percentile = page_features.percentile_feature_names()[0]
    raw_feature = page_features.FEATURE_NAMES[0]

    def probe(feature: str, op: str, threshold: float, weight: float) -> str:
        entry = {
            "taxonomy_version": "probe",
            "ambiguity_margin": 0.1,
            "default_type": "probe",
            "require_positive_evidence": True,
            "page_types": [
                {
                    "name": "probe",
                    "description": "Probe type.",
                    "rules": [
                        {
                            "feature": feature,
                            "op": op,
                            "threshold": threshold,
                            "weight": weight,
                        },
                        {
                            "feature": raw_feature,
                            "op": "ge",
                            "threshold": 0.1,
                            "weight": 1.0,
                        },
                    ],
                    "policy": {
                        "chain_eligible": False,
                        "translate": True,
                        "repair_profile": "flow",
                    },
                }
            ],
        }
        try:
            taxonomy_module.parse_taxonomy(entry, "probe")
        except taxonomy_module.TaxonomyError as exc:
            return str(exc)
        return ""

    survived = [
        f"{op}@{threshold}"
        for threshold in REJECTED_PCTL_THRESHOLDS
        for op in sorted(taxonomy_module.EVIDENCE_OPERATORS)
        if not probe(percentile, op, threshold, 1.0)
    ]
    record(
        "02a percentile evidence at or below the constant column midrank is rejected",
        not survived,
        f"feature={percentile} midrank={taxonomy_module.CONSTANT_COLUMN_MIDRANK} "
        f"thresholds={list(REJECTED_PCTL_THRESHOLDS)} survived={survived}",
    )

    complaint = probe(percentile, "ge", REJECTED_PCTL_THRESHOLDS[-1], 1.0)
    record(
        "02b the refusal names the feature, the bound and the reason",
        percentile in complaint
        and str(taxonomy_module.CONSTANT_COLUMN_MIDRANK) in complaint
        and "constant" in complaint,
        f"message={complaint[:160]!r}",
    )

    refused = [
        f"{op}@{threshold}: {probe(percentile, op, threshold, 1.0)}"
        for threshold in ACCEPTED_PCTL_THRESHOLDS
        for op in sorted(taxonomy_module.EVIDENCE_OPERATORS)
        if probe(percentile, op, threshold, 1.0)
    ]
    record(
        "02c percentile evidence above the midrank is accepted",
        not refused,
        f"thresholds={list(ACCEPTED_PCTL_THRESHOLDS)} refused={refused[:3]}",
    )

    # The rule is about positive evidence, not about percentile features: a
    # penalty and a le/lt rule state something a low percentile can honestly
    # satisfy, so neither is bound by it.
    unrelated = {
        "penalty below the midrank": probe(percentile, "ge", 0.3, -1.0),
        "le rule below the midrank": probe(percentile, "le", 0.3, 1.0),
        "lt rule below the midrank": probe(percentile, "lt", 0.3, 1.0),
        "raw feature evidence below the midrank": probe(raw_feature, "ge", 0.3, 1.0),
    }
    blocked = sorted(label for label, message in unrelated.items() if message)
    record(
        "02d the rule binds positive percentile evidence only",
        not blocked,
        f"wrongly_rejected={blocked}",
    )


def check_03_agreement_tables(classified: dict[str, Path], manifest: dict) -> None:
    """Both measured agreement tables hold, and the adoption verdict follows."""
    shipped = taxonomy_module.load_taxonomy()
    candidate = taxonomy_module.parse_taxonomy(
        json.loads(CANDIDATE_PATH.read_text(encoding="utf-8")), CANDIDATE_PATH.name
    )
    labels = corpus_module.normalize_page_labels(
        corpus_module.load_page_labels(LABELS_PATH)
    )
    publication_of = {
        sample["file"]: sample.get("publication", "") for sample in manifest["samples"]
    }

    measured = {}
    for label, vocabulary, frozen in (
        ("raw", shipped, RAW_AGREEMENT),
        ("candidate", candidate, CANDIDATE_AGREEMENT),
    ):
        table, misses = agreement_table(vocabulary, classified, labels, publication_of)
        measured[label] = table
        drifted = sorted(
            f"{key or 'overall'}: measured={table.get(key)} frozen={frozen[key]}"
            for key in set(frozen) | set(table)
            if table.get(key) != frozen.get(key)
        )
        print(f"    {label} agreement (kind hits / labelled pages):")
        for key in sorted(table):
            print(f"      {key or 'overall'}: {table[key][0]}/{table[key][1]}")
        record(
            f"03a the measured {label} agreement matches the frozen table",
            not drifted,
            f"overall={rate(table['']):.4f} drift={drifted[:5]} misses={misses[:3]}",
        )

    shipped_rate = rate(measured["raw"][""])
    candidate_rate = rate(measured["candidate"][""])
    families = sorted(key for key in measured["raw"] if key)
    drops = {
        key: rate(measured["raw"][key]) - rate(measured["candidate"][key])
        for key in families
    }
    offenders = sorted(key for key, drop in drops.items() if drop > MAX_FAMILY_DROP)
    adopted = candidate_rate >= shipped_rate and not offenders
    rounded = {key: round(value, 4) for key, value in drops.items()}
    record(
        "03b the adoption criterion resolves the way the batch recorded",
        adopted == CANDIDATE_ADOPTED,
        f"overall_shipped={shipped_rate:.4f} overall_candidate={candidate_rate:.4f} "
        f"max_family_drop_allowed={MAX_FAMILY_DROP} offenders={offenders} "
        f"drops={rounded} adopted={adopted} recorded={CANDIDATE_ADOPTED}",
    )

    # The candidate is archived rather than loaded. Nothing may reach for it.
    live = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    candidate_raw = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    percentile_names = set(page_features.percentile_feature_names())
    record(
        "03c the archived candidate is the percentile ruleset and is not the live one",
        any(
            rule["feature"] in percentile_names
            for _, rule in candidate_rules(candidate_raw)
        )
        and not any(
            rule["feature"] in percentile_names for _, rule in candidate_rules(live)
        )
        and taxonomy_module.TAXONOMY_PATH == TAXONOMY_PATH,
        f"candidate_pctl_rules="
        f"{sum(1 for _, r in candidate_rules(candidate_raw) if r['feature'] in percentile_names)} "  # noqa: E501
        f"live_pctl_rules="
        f"{sum(1 for _, r in candidate_rules(live) if r['feature'] in percentile_names)}",
    )


def check_04_fingerprint_scope() -> None:
    """The cache key follows the package and the configuration, nothing else."""
    outside = ROOT / "spec_checks" / "run_all.py"
    # A configuration file the classifier reads. configs/gate_cache.json steers
    # the artefact cache rather than a run, so its keys are declared outside the
    # fingerprint and it can no longer stand for "a configuration file" here;
    # spec_check_b3 09 asserts that exclusion in its own right.
    inside = ROOT / "configs" / "page_features.json"
    outside_bytes = outside.read_bytes()
    inside_bytes = inside.read_bytes()

    before = artifacts.workspace_fingerprint(refresh=True)
    try:
        outside.write_bytes(outside_bytes + b"\n")
        after_outside = artifacts.workspace_fingerprint(refresh=True)
    finally:
        outside.write_bytes(outside_bytes)
    try:
        inside.write_bytes(inside_bytes + b"\n")
        after_inside = artifacts.workspace_fingerprint(refresh=True)
    finally:
        inside.write_bytes(inside_bytes)
    restored = artifacts.workspace_fingerprint(refresh=True)

    record(
        "04a editing a gate script leaves the workspace fingerprint alone",
        after_outside == before,
        f"file={outside.relative_to(ROOT).as_posix()} before={before[:16]} "
        f"after={after_outside[:16]}",
    )
    record(
        "04b editing a configuration file mints a new workspace fingerprint",
        after_inside != before,
        f"file={inside.relative_to(ROOT).as_posix()} before={before[:16]} "
        f"after={after_inside[:16]}",
    )
    record(
        "04c both probe files are restored byte for byte",
        restored == before
        and outside.read_bytes() == outside_bytes
        and inside.read_bytes() == inside_bytes,
        f"restored={restored[:16]}",
    )
    record(
        "04d the fingerprint declares the two paths it follows",
        artifacts.FINGERPRINT_PATHS == ("babeldoc", "configs"),
        f"paths={artifacts.FINGERPRINT_PATHS}",
    )


def check_05_sweep_and_marker() -> None:
    """The full sweep is green and leaves a complete completion marker."""
    names = (
        "05a the full run_all sweep is green",
        "05b the sweep leaves a complete run_all.done.json",
        "05c classification agreement clears the configured minimum",
    )
    if NESTED_SUPPRESSED:
        for name in names:
            print(f"SKIPPED: nested run suppressed :: {name}")
        return

    if runner.DONE_PATH.exists():
        runner.DONE_PATH.unlink()
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
        names[0],
        proc.returncode == 0 and not failures,
        f"exit={proc.returncode} failures={failures[:5]}",
    )

    payload: dict = {}
    if runner.DONE_PATH.exists():
        payload = json.loads(runner.DONE_PATH.read_text(encoding="utf-8"))
    missing = sorted(set(runner.DONE_FIELDS) - set(payload))
    timestamps_parse = all(
        isinstance(payload.get(key), str) and bool(datetime.fromisoformat(payload[key]))
        for key in ("started_at", "finished_at")
        if key in payload
    )
    gates_covered = {entry.get("gate") for entry in payload.get("gates", [])} == set(
        runner.GATES
    )
    record(
        names[1],
        not missing
        and payload.get("exit_code") == proc.returncode
        and isinstance(payload.get("elapsed_seconds"), int | float)
        and payload["elapsed_seconds"] > 0
        and timestamps_parse
        and gates_covered,
        f"path={runner.DONE_PATH.name} missing={missing} "
        f"exit_code={payload.get('exit_code')} "
        f"elapsed={payload.get('elapsed_seconds')} "
        f"timestamps_parse={timestamps_parse} gates_covered={gates_covered}",
    )

    minimum = page_features.load_feature_config()["label_agreement_min"]
    reported = [
        line.strip()
        for line in proc.stdout.splitlines()
        if "kind_agreement=" in line and "[PASS]" in line
    ]
    measured = 0.0
    if reported:
        measured = float(reported[0].split("kind_agreement=")[1].split()[0].rstrip(","))
    record(
        names[2],
        bool(reported) and measured >= minimum,
        f"kind_agreement={measured:.4f} minimum={minimum}",
    )


def check_09_cache_trim() -> None:
    """The ceiling is honoured and the slots that go are the least recent ones.

    Exercised against a disposable cache root: the trim deletes artefacts, and a
    test of it must not be able to delete the real ones.
    """
    limit_gb = float(artifacts.load_cache_config()["gate_cache_max_gb"])
    low, high = 0.5, 256.0
    record(
        "09a the cache ceiling is a bounded configuration parameter",
        artifacts.CACHE_CONFIG_PATH.exists() and low <= limit_gb <= high,
        f"gate_cache_max_gb={limit_gb} range={low}..{high} "
        f"source={artifacts.CACHE_CONFIG_PATH.name}",
    )

    root = _tmp_root / "trim_cache"
    real_root, real_stats = artifacts.CACHE_ROOT, artifacts.STATS_DIR
    artifacts.CACHE_ROOT, artifacts.STATS_DIR = root, root / "stats"
    try:
        payload = 4096
        ordered = ["oldest", "middle", "newest"]
        for age, name in enumerate(ordered):
            slot = root / f"generation_{name}" / f"sample.{name}"
            slot.mkdir(parents=True)
            (slot / "meta.json").write_text("{}", encoding="utf-8")
            (slot / "mono.pdf").write_bytes(b"\0" * payload)
            os.utime(slot, (1_700_000_000 + age, 1_700_000_000 + age))
        artifacts.STATS_DIR.mkdir(parents=True)

        measured = artifacts.cache_size_bytes()
        untouched = artifacts.trim_cache(measured)
        # Room for one slot only, so the two least recent must go.
        dropped, freed = artifacts.trim_cache(measured // len(ordered))
        survivors = sorted(slot.name for slot in artifacts._slots())
        remaining = artifacts.cache_size_bytes()
    finally:
        artifacts.CACHE_ROOT, artifacts.STATS_DIR = real_root, real_stats

    record(
        "09b a cache already inside its ceiling is left alone",
        untouched == (0, 0) and measured >= payload * len(ordered),
        f"size={measured} trimmed={untouched}",
    )
    record(
        "09c the trim drops least recently used slots until the cache fits",
        dropped == len(ordered) - 1
        and survivors == ["sample.newest"]
        and remaining <= measured // len(ordered)
        and freed > 0,
        f"dropped={dropped} freed={freed} survivors={survivors} "
        f"remaining={remaining} limit={measured // len(ordered)}",
    )
    record(
        "09d the real cache root was never the one under test",
        artifacts.CACHE_ROOT == real_root
        and artifacts.STATS_DIR == real_stats
        and root != real_root,
        f"restored={artifacts.CACHE_ROOT.name}",
    )


def check_06_frozen_corpus() -> None:
    changed = changed_files()
    touched = sorted(changed & FROZEN_CORPUS_FILES)
    record(
        "06 the hand written corpus files are untouched",
        not touched,
        f"frozen={sorted(FROZEN_CORPUS_FILES)} touched={touched}",
    )


def check_07_vocabulary_unchanged() -> None:
    """The candidate was not adopted, so the shipped vocabulary must not move."""
    if CANDIDATE_ADOPTED:
        record(
            "07 the shipped vocabulary is byte identical to the previous batch",
            True,
            "candidate adopted; the vocabulary is expected to differ",
        )
        return
    # Anchored to this batch's own tag once it exists, so a later batch editing
    # the vocabulary is not read as this batch having moved it.
    revisions = [PREVIOUS_TAG, BATCH_TAG] if batch_tag_exists() else [PREVIOUS_TAG]
    code, listing = git_output(
        ["diff", "--name-only", *revisions, "--", "configs/page_types.json"]
    )
    differing = [line.strip() for line in listing.splitlines() if line.strip()]
    record(
        "07 the shipped vocabulary is byte identical to the previous batch",
        code == 0 and not differing,
        f"against={PREVIOUS_TAG} at={revisions[-1]} exit={code} differing={differing}",
    )


def check_08_change_scope() -> None:
    changed = changed_files()
    unexpected = sorted(changed - ALLOWED_CHANGES)
    record(
        "08a this batch changes only the files the plan allows",
        not unexpected,
        f"changed={sorted(changed)} unexpected={unexpected}",
    )
    upstream = sorted(
        path
        for path in changed
        if path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    )
    record(
        "08b this batch touches no upstream file",
        not upstream,
        f"upstream={upstream}",
    )

    cjk: list[str] = []
    checked = 0
    for relative in sorted(ALLOWED_CHANGES):
        path = ROOT / relative
        if not path.exists() or path.suffix not in CJK_SCAN_SUFFIXES:
            continue
        checked += 1
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if has_cjk(line):
                cjk.append(f"{relative}:{number}")
    record(
        "08c no CJK characters in the code this batch changed",
        not cjk and checked > 0,
        f"files={checked} offenders={cjk[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    with _timer.phase("warmup"):
        use_project_cache(ROOT)
        warmup()

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        classified: dict[str, Path] = {}
        for entry in manifest["samples"]:
            name = Path(entry["file"]).stem
            with _timer.phase(f"pipeline:classified:{name}"):
                built = artifacts.get_artifacts(INPUT_DIR / entry["file"], "classified")
            classified[name] = built.working_dir

        check_01_pctl_scoring(classified)
        check_03_agreement_tables(classified, manifest)

    check_02_pctl_evidence_rule()
    check_04_fingerprint_scope()
    check_09_cache_trim()
    check_06_frozen_corpus()
    check_07_vocabulary_unchanged()
    check_08_change_scope()
    check_05_sweep_and_marker()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b2_7")
    artifacts.print_stats("spec_check_b2_7")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b2_7: {len(_results) - len(failed)}/{len(_results)} passed")
    for name in failed:
        print(f"  FAILED: {name}")
    shutil.rmtree(_tmp_root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
