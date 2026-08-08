"""Validate the sample corpus in three directions.

Usage:
    python tools/corpus_check.py [--registry PATH] [--manifest PATH]

The checks are:

1. the registry covers every PDF under examples/input/ and satisfies its
   schema, an unregistered sample being an error;
2. every semantic field in the manifest equals the registry value verbatim,
   the registry being the sole authority for them;
3. every mechanical field in the manifest matches the sample file on disk.

Registered baseline artefacts are verified when present; they are build
products and are not tracked by version control, so a missing baseline is a
warning rather than an error. A per publication breakdown is printed for the
leave-one-publication-out tuning protocol.

Exit codes: 0 the corpus is consistent, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import corpus  # noqa: E402


def check(registry_path: Path, manifest_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not registry_path.exists():
        return [f"registry not found: {registry_path}"], warnings
    if not manifest_path.exists():
        return [f"manifest not found: {manifest_path}"], warnings

    entries = corpus.load_registry(registry_path)
    errors.extend(corpus.validate_registry(entries))

    manifest = corpus.load_manifest(manifest_path)
    manifest_errors, manifest_warnings = corpus.validate_manifest(manifest, entries)
    errors.extend(manifest_errors)
    warnings.extend(manifest_warnings)

    # Boundary ground truth is optional: a corpus nobody has adjudicated yet is
    # unlabelled, not wrong. What is written down is bound to the manifest's
    # page counts, so a boundary naming a page the sample does not have is
    # reported here as the editing mistake it is.
    if corpus.CHAIN_LABELS_PATH.exists():
        pages_by_file = {
            sample["file"]: sample.get("pages", 0)
            for sample in manifest.get("samples", [])
            if "file" in sample
        }
        errors.extend(
            corpus.validate_chain_labels(
                corpus.load_chain_labels(), pages_by_file=pages_by_file
            )
        )
    return errors, warnings


def print_groups(manifest_path: Path) -> None:
    if not manifest_path.exists():
        return
    groups = corpus.group_by_publication(corpus.load_manifest(manifest_path))
    print(f"publications: {len(groups)}")
    for publication, samples in groups.items():
        roles = sorted(
            {role for sample in samples for role in sample.get("corpus_role", [])}
        )
        pages = sum(sample.get("pages", 0) for sample in samples)
        files = ", ".join(sample["file"] for sample in samples)
        print(
            f"  {publication}: {len(samples)} sample(s), {pages} page(s), "
            f"roles={roles} [{files}]"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=corpus.REGISTRY_PATH)
    parser.add_argument("--manifest", type=Path, default=corpus.MANIFEST_PATH)
    args = parser.parse_args(argv)

    errors, warnings = check(args.registry, args.manifest)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print_groups(args.manifest)
    if errors:
        print(f"corpus_check: FAILED ({len(errors)} error(s))")
        return 1
    print(f"corpus_check: OK ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
