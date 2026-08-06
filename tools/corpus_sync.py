"""Rebuild corpus/manifest.json from the user owned corpus/registry.user.json.

Usage:
    python tools/corpus_sync.py [--registry PATH] [--manifest PATH] [--check]

Semantic metadata is copied verbatim from the registry; the content hash and
page count are measured from the sample files. A baseline block survives the
rebuild only while the sample content is unchanged.

With ``--check`` nothing is written and the exit code reports whether the
manifest on disk already equals the rebuilt one.

Exit codes: 0 written (or already in sync), 1 the registry is unusable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import corpus  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=corpus.REGISTRY_PATH)
    parser.add_argument("--manifest", type=Path, default=corpus.MANIFEST_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the manifest is in sync without writing it",
    )
    args = parser.parse_args(argv)

    entries = corpus.load_registry(args.registry)
    errors = corpus.validate_registry(entries)
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"corpus_sync: FAILED ({len(errors)} registry error(s))")
        return 1

    previous = corpus.load_manifest(args.manifest) if args.manifest.exists() else None
    manifest = corpus.build_manifest(entries, previous)

    if args.check:
        in_sync = previous == manifest
        print(f"corpus_sync: {'in sync' if in_sync else 'OUT OF SYNC'}")
        return 0 if in_sync else 1

    corpus.write_manifest(manifest, args.manifest)
    kept = sum("baseline" in sample for sample in manifest["samples"])
    print(
        f"corpus_sync: {len(manifest['samples'])} sample(s) -> {args.manifest}, "
        f"{kept} baseline block(s) carried over"
    )
    print(json.dumps([sample["file"] for sample in manifest["samples"]]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
