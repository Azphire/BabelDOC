"""Snapshot frozen bytes and check formal evaluation methodology readiness."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.metrics.readiness import ReadinessError  # noqa: E402
from babeldoc.magazine.metrics.readiness import current_formal_report  # noqa: E402
from babeldoc.magazine.metrics.readiness import evaluate_formal  # noqa: E402
from babeldoc.magazine.metrics.readiness import validate_readiness_report  # noqa: E402

SNAPSHOT_SCHEMA_VERSION = "frozen-byte-snapshot.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_paths(path: str) -> list[str]:
    payload = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
    if not payload:
        raise ReadinessError("the NUL path list is empty")
    # A final NUL is conventional but not required: some Windows pipeline
    # hosts preserve all separators while dropping only the terminal one.
    encoded = payload[:-1] if payload.endswith(b"\0") else payload
    try:
        paths = [item.decode("utf-8") for item in encoded.split(b"\0")]
    except UnicodeDecodeError as exc:
        raise ReadinessError("path list is not UTF-8") from exc
    if any(not item for item in paths) or len(paths) != len(set(paths)):
        raise ReadinessError("path list contains an empty or duplicate path")
    return paths


def build_snapshot(paths: list[str]) -> dict:
    files = []
    for supplied in sorted(paths):
        relative = Path(supplied)
        if relative.is_absolute() or ".." in relative.parts:
            raise ReadinessError(
                f"snapshot path is not repository-relative: {supplied}"
            )
        target = ROOT / relative
        if not target.is_file():
            raise ReadinessError(f"snapshot path is not a file: {supplied}")
        files.append(
            {
                "path": relative.as_posix(),
                "size": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )
    return {"schema_version": SNAPSHOT_SCHEMA_VERSION, "files": files}


def _load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _snapshot(args: argparse.Namespace) -> int:
    snapshot = build_snapshot(_read_paths(args.paths_from0))
    _write_json(args.output, snapshot)
    print(json.dumps(snapshot, sort_keys=True, separators=(",", ":")))
    return 0


def _compare(args: argparse.Namespace) -> int:
    before = _load_json(args.before)
    after = _load_json(args.after)
    if before != after:
        print("FROZEN_BYTES_CHANGED", file=sys.stderr)
        return 1
    if (
        not isinstance(before, dict)
        or before.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
    ):
        raise ReadinessError("unknown snapshot schema")
    print(f"FROZEN_BYTES_IDENTICAL: {len(before.get('files', []))} file(s)")
    return 0


def _check(args: argparse.Namespace) -> int:
    if args.mode != "formal":
        raise ReadinessError("only formal readiness is a certificate mode")
    if args.evidence_manifest is None:
        report = current_formal_report(args.metric)
    else:
        report = evaluate_formal(args.metric, _load_json(args.evidence_manifest))
    validate_readiness_report(report)
    _write_json(args.output, report)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["computation_status"] == "computed" else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--paths-from0", required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.set_defaults(handler=_snapshot)

    compare = subparsers.add_parser("compare-snapshots")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.set_defaults(handler=_compare)

    check = subparsers.add_parser("check")
    check.add_argument("--metric", choices=("lopo", "ltcr", "seam-mqm"), required=True)
    check.add_argument("--mode", choices=("formal",), required=True)
    check.add_argument("--evidence-manifest", type=Path)
    check.add_argument("--output", type=Path, required=True)
    check.set_defaults(handler=_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.handler(args)
    except (OSError, json.JSONDecodeError, ReadinessError) as exc:
        print(f"READINESS_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
