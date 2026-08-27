"""Descriptive publication matrix over the page classifier, on the v2 corpus.

Usage:
    python tools/lopo.py
    python tools/lopo.py --out output

Writes the fold matrix as JSON and prints it. Deterministic, no API key, no
pipeline run: the classifier is replayed in this process over the frozen
checkpoints of the last full-stack run, so two invocations produce the same
bytes and a reader years from now can reproduce them.

What this is and what it is not
-------------------------------

Ledger row B-02 carried a holdout agreement of 0.938 whose only source was a
plan file's recollection of a tuning session. The fold split, the fold matrix
and the tuning trace were never written down, and the v1 corpus two of whose
samples have since been replaced no longer exists. GAP-02 is the standing
decision about that number: it may not be restored and it may not be quoted.
This tool produces the replacement, and it is honest about what it can be.

**The configuration is not refitted per fold.** ``configs/page_types.json`` is a
hand tuned vocabulary of rules, and this repository holds no tuner. A leave one
out protocol is a statement about *fitting*: fold *k* is trained without
publication *k* and then measured on it. With a configuration that is the same
in every fold, the held out measurement of fold *k* is exactly the agreement on
publication *k*, and the in-fold measurement is exactly the agreement on the
other five. The fold matrix is therefore **compositional rather than a
generalisation estimate**, and the report says so in the field
``refit_per_fold``. What it does give, and what B-02 has never had, is the
per-publication matrix itself, written down, in git, recomputable.

**The vocabulary has seen this corpus.** Whoever tuned the rules had the whole
v2 corpus in front of them. No fold of this design is free of that contact, and
no number here may be presented as a held out result. The honest reading is the
one GAP-02 already fixes: report the corpus wide agreement, report the spread
across publications, and make no holdout claim.

Two numbers per fold, as everywhere else in this evaluation: agreement on the
kind a page was given, and agreement on the *policy* that kind maps to, since
two kinds sharing a policy are interchangeable to everything downstream. A page
the ground truth gives several acceptable kinds is a hit on any of them.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine import page_features  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.taxonomy import classify  # noqa: E402
from babeldoc.magazine.taxonomy import load_configs  # noqa: E402

logger = logging.getLogger(__name__)

# The frozen run the classifier is replayed over, and the stage inside it. The
# stage before the classifier is the one whose document the classifier saw, so
# replaying over it reproduces the deterministic verdict exactly -- including on
# a page a human adjudication later overrode, which is what this measurement is
# supposed to be blind to.
FORK_RUN_DIR = ROOT / "examples" / "output" / "b8_4" / "smoke"
CLASSIFIER_INPUT_STAGE = "styles_and_formulas"

DEFAULT_OUT = ROOT / "docs" / "eval" / "results_e1"
DEFAULT_NAME = "descriptive_publication_matrix"
LEGACY_NAME = "lopo_v2"


def checkpoint_path(stem: str) -> Path:
    """Where one sample's classifier input checkpoint sits in the frozen run."""
    return (
        FORK_RUN_DIR
        / stem
        / "work"
        / stem
        / f"{checkpoint_stem(CLASSIFIER_INPUT_STAGE)}.xml"
    )


def classify_sample(stem: str) -> list[str] | None:
    """The deterministic kind of every page of one sample, in page order."""
    path = checkpoint_path(stem)
    if not path.is_file():
        return None
    feature_config, taxonomy = load_configs()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        document = load_checkpoint(path)
    vectors = page_features.extract_document_features(document, feature_config)
    return [classify(features, taxonomy).kind for features in vectors]


def score_sample(
    file_name: str, kinds: list[str], expected_by_page: dict, policy_of
) -> dict:
    """One sample's page by page verdicts against the labels it carries."""
    pages = []
    kind_hits = 0
    policy_hits = 0
    for position, kind in enumerate(kinds):
        accepted = expected_by_page.get(str(position + 1))
        if not accepted:
            continue
        kind_hit = kind in accepted
        own = policy_of(kind)
        policy_hit = kind_hit or (
            own is not None
            and any(policy_of(candidate) == own for candidate in accepted)
        )
        kind_hits += int(kind_hit)
        policy_hits += int(policy_hit)
        pages.append(
            {
                "page": position + 1,
                "kind": kind,
                "accepted": accepted,
                "kind_hit": kind_hit,
                "policy_hit": policy_hit,
            }
        )
    return {
        "file": file_name,
        "labelled_pages": len(pages),
        "kind_hits": kind_hits,
        "policy_hits": policy_hits,
        "pages": pages,
    }


def _rate(hits: int, total: int) -> float | None:
    return hits / total if total else None


def _totals(rows: list[dict]) -> dict:
    labelled = sum(row["labelled_pages"] for row in rows)
    kind_hits = sum(row["kind_hits"] for row in rows)
    policy_hits = sum(row["policy_hits"] for row in rows)
    return {
        "samples": sorted(row["file"] for row in rows),
        "labelled_pages": labelled,
        "kind_hits": kind_hits,
        "kind_agreement": _rate(kind_hits, labelled),
        "policy_hits": policy_hits,
        "policy_agreement": _rate(policy_hits, labelled),
    }


def build_report(*, legacy: bool = False) -> dict:
    manifest = corpus_module.load_manifest()
    labels = corpus_module.normalize_page_labels(corpus_module.load_page_labels())
    _, taxonomy = load_configs()
    constrained = set(corpus_module.constrained_samples(manifest))

    scored: list[dict] = []
    missing: list[str] = []
    for entry in manifest["samples"]:
        file_name = entry["file"]
        stem = Path(file_name).stem
        kinds = classify_sample(stem)
        if kinds is None:
            missing.append(f"{file_name}: no {checkpoint_path(stem)}")
            continue
        row = score_sample(
            file_name, kinds, labels.get(file_name, {}), taxonomy.policy_of
        )
        row["publication"] = entry.get("publication", file_name)
        row["binding"] = file_name in constrained
        scored.append(row)

    publications = sorted({row["publication"] for row in scored})
    folds = []
    for publication in publications:
        held_out = [row for row in scored if row["publication"] == publication]
        in_fold = [row for row in scored if row["publication"] != publication]
        folds.append(
            {
                "held_out_publication": publication,
                "held_out": _totals(held_out),
                "in_fold": _totals(in_fold),
            }
        )

    binding = [row for row in scored if row["binding"]]
    observed = [row for row in scored if not row["binding"]]
    report = {
        "generated_by": "tools/lopo.py",
        "protocol": {
            "split": "leave one publication out",
            "folds": len(folds),
            "refit_per_fold": False,
            "refit_note": (
                "configs/page_types.json is hand tuned and this repository holds "
                "no tuner, so no fold refits anything. Each fold's held out "
                "figure is therefore the agreement on that publication and each "
                "in-fold figure the agreement on the rest; the matrix is "
                "compositional and is not a generalisation estimate. See "
                "docs/eval/gap_register.md GAP-02."
            ),
            "tuning_contact": (
                "the vocabulary was tuned with the whole v2 corpus available, so "
                "no fold is free of tuner contact and no figure here may be "
                "presented as a held out result"
            ),
            "source_stage": CLASSIFIER_INPUT_STAGE,
            "vocabulary_version": taxonomy.version,
            "constrained_role": corpus_module.CONSTRAINED_ROLE,
        },
        "corpus": {
            "binding": _totals(binding),
            "observed_only": _totals(observed),
            "all": _totals(scored),
        },
        "folds": folds,
        "samples": scored,
        "missing": missing,
    }
    if legacy:
        return report
    return {
        "metric_id": "descriptive_publication_matrix",
        "metric_class": "descriptive",
        "generalisation_claim": False,
        "compatibility": "current",
        **report,
    }


def summarize(report: dict) -> str:
    lines = [
        f"folds={report['protocol']['folds']} "
        f"refit_per_fold={report['protocol']['refit_per_fold']} "
        f"vocabulary={report['protocol']['vocabulary_version']}",
    ]
    for name in ("binding", "observed_only", "all"):
        totals = report["corpus"][name]
        lines.append(
            f"{name:14s} kind={totals['kind_hits']}/{totals['labelled_pages']} "
            f"policy={totals['policy_hits']}/{totals['labelled_pages']}"
        )
    lines.append("fold (held out | in fold), kind and policy:")
    for fold in report["folds"]:
        held = fold["held_out"]
        rest = fold["in_fold"]
        lines.append(
            f"  {fold['held_out_publication']:16s} "
            f"held_out kind={held['kind_hits']}/{held['labelled_pages']} "
            f"policy={held['policy_hits']}/{held['labelled_pages']} | "
            f"in_fold kind={rest['kind_hits']}/{rest['labelled_pages']} "
            f"policy={rest['policy_hits']}/{rest['labelled_pages']}"
        )
    for line in report["missing"]:
        lines.append(f"missing {line}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--name",
        default=DEFAULT_NAME,
        help=(
            "output stem (default: descriptive_publication_matrix); explicit "
            "lopo_v2 writes the legacy non-comparable shape with a warning"
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    legacy = args.name == LEGACY_NAME
    if legacy:
        warnings.warn(
            "lopo_v2 is a legacy non-comparable descriptive artifact, not formal LOPO",
            DeprecationWarning,
            stacklevel=2,
        )
    report = build_report(legacy=legacy)
    target = args.out / f"{args.name}.json"

    # A run that could not read some sample's checkpoint has not produced a
    # fold matrix; it has produced a matrix over whatever was left. Writing
    # that is how the frozen copy of this file was destroyed once: the default
    # output path is the tracked one, and a caller re-running the tool to check
    # determinism got a degenerate report written over the thing it was
    # checking. So nothing is written unless every sample was classified.
    if report["missing"]:
        print(summarize(report))
        print(
            f"\nlopo: {len(report['missing'])} sample(s) could not be classified; "
            f"{target} was left untouched"
        )
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(summarize(report))
    print(f"\nlopo: {len(report['samples'])} sample(s) -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
