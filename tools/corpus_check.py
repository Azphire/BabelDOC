"""Validate corpus/manifest.json against the actual sample files.

Usage:
    python tools/corpus_check.py [--manifest corpus/manifest.json]

Checks that every registered sample exists under examples/input/ with the
recorded SHA-256 and page count, and warns about unregistered PDFs. Registered
baseline artefacts under examples/output/ are verified when present; they are
build products and are not tracked by version control, so a missing baseline is
a warning rather than an error.

Exit codes: 0 all registered samples valid, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "examples" / "input"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"

# Read size for incremental hashing; a pure I/O buffer, not a tuning knob.
_HASH_CHUNK_BYTES = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def page_count(path: Path) -> int:
    with pymupdf.open(path) as doc:
        return doc.page_count


def check(manifest_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not manifest_path.exists():
        return [f"manifest not found: {manifest_path}"], warnings

    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)

    registered: set[str] = set()
    for entry in manifest.get("samples", []):
        rel = entry["file"]
        registered.add(rel)
        path = INPUT_DIR / rel
        if not path.exists():
            errors.append(f"{rel}: missing from {INPUT_DIR}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != entry["sha256"]:
            errors.append(
                f"{rel}: sha256 mismatch, manifest={entry['sha256']} actual={actual_hash}"
            )
        actual_pages = page_count(path)
        if actual_pages != entry["pages"]:
            errors.append(
                f"{rel}: page count mismatch, manifest={entry['pages']} actual={actual_pages}"
            )

        baseline = entry.get("baseline")
        if baseline:
            baseline_pdf = ROOT / baseline["pdf"]
            if not baseline_pdf.exists():
                warnings.append(f"{rel}: baseline PDF not built at {baseline['pdf']}")
            else:
                actual_baseline_hash = sha256_file(baseline_pdf)
                if actual_baseline_hash != baseline["sha256"]:
                    errors.append(
                        f"{rel}: baseline sha256 mismatch, "
                        f"manifest={baseline['sha256']} actual={actual_baseline_hash}"
                    )
            checkpoints = ROOT / baseline["checkpoints"]
            if not checkpoints.is_dir():
                warnings.append(
                    f"{rel}: baseline checkpoints not built at {baseline['checkpoints']}"
                )

    if INPUT_DIR.is_dir():
        for pdf in sorted(INPUT_DIR.rglob("*.pdf")):
            rel = pdf.relative_to(INPUT_DIR).as_posix()
            if rel not in registered:
                warnings.append(f"{rel}: present in examples/input but not registered")
    else:
        errors.append(f"sample directory missing: {INPUT_DIR}")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)

    errors, warnings = check(args.manifest)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"corpus_check: FAILED ({len(errors)} error(s))")
        return 1
    print(f"corpus_check: OK ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
