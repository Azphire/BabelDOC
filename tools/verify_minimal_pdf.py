"""Fail-closed validator for one completed minimal BabelDOC run."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import fitz

RUN_REPORT_NAME = "minimal_run.report.json"
RUN_SCHEMA_VERSION = "minimal-run.v1"
DETECTION_SCHEMA_VERSION = "minimal-detection.v1"
ISSUE_KINDS = (
    "untranslated_residue",
    "out_of_page",
    "text_text_collision",
    "fragment_cluster",
    "chain_conservation",
    "fixed_asset_drift",
)
ROOT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "translation_performed",
        "completed",
        "chain",
        "ordinary",
        "backfill",
        "flow",
        "dropcap",
        "issues",
        "detector",
        "repair",
        "fixed",
        "output",
    }
)
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class MinimalPdfValidationError(ValueError):
    """Raised when a PDF or its minimal-run evidence is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MinimalPdfValidationError(message)


def _object(value, where: str, keys: frozenset[str] | None = None) -> dict:
    _require(isinstance(value, dict), f"{where} must be an object")
    if keys is not None:
        _require(set(value) == keys, f"{where} keys are not the closed schema")
    return value


def _integer(value, where: str) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{where} must be a non-negative integer",
    )
    return value


def _boolean(value, where: str) -> bool:
    _require(isinstance(value, bool), f"{where} must be boolean")
    return value


def _text(value, where: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{where} must be text")
    return value


def _load_json(path: Path, where: str) -> dict:
    _require(path.is_file(), f"{where} is missing: {path}")
    return _object(json.loads(path.read_text(encoding="utf-8")), where)


def _unique(paths, where: str) -> Path:
    found = tuple(sorted({path.resolve() for path in paths}))
    _require(len(found) == 1, f"{where} must resolve to exactly one file")
    return found[0]


def _parse_pages(value: str) -> tuple[int, ...]:
    pieces = value.split(",")
    if not pieces or any(not piece.isdigit() for piece in pieces):
        raise argparse.ArgumentTypeError("translated pages must be comma-separated integers")
    pages = tuple(int(piece) for piece in pieces)
    if any(page < 1 for page in pages) or len(pages) != len(set(pages)):
        raise argparse.ArgumentTypeError("translated pages must be unique and positive")
    return pages


def _validate_box(value, where: str) -> None:
    _require(
        isinstance(value, tuple | list) and len(value) == 4,
        f"{where} must contain four coordinates",
    )
    box = tuple(float(coordinate) for coordinate in value)
    _require(all(math.isfinite(coordinate) for coordinate in box), f"{where} is not finite")
    _require(box[0] <= box[2] and box[1] <= box[3], f"{where} is not ordered")


def _validate_pdf(source: Path, output: Path, pages, allow_untranslated: bool) -> int:
    _require(source.is_file(), f"source PDF is missing: {source}")
    _require(output.is_file(), f"output PDF is missing: {output}")
    with fitz.open(source) as source_document, fitz.open(output) as output_document:
        _require(source_document.page_count > 0, "source PDF has no pages")
        _require(
            output_document.page_count == source_document.page_count,
            "source and output page counts differ",
        )
        _require(all(page <= output_document.page_count for page in pages), "selected page is outside the PDF")
        for page_index, page in enumerate(output_document):
            payload = page.get_text("dict")
            for block_index, block in enumerate(payload.get("blocks", ())):
                if block.get("type") != 0:
                    continue
                _validate_box(block.get("bbox"), f"page {page_index + 1} block {block_index}")
                for line_index, line in enumerate(block.get("lines", ())):
                    _validate_box(
                        line.get("bbox"),
                        f"page {page_index + 1} line {line_index}",
                    )
                    for span_index, span in enumerate(line.get("spans", ())):
                        _validate_box(
                            span.get("bbox"),
                            f"page {page_index + 1} span {span_index}",
                        )
        for selected in pages:
            extracted = output_document[selected - 1].get_text("text").strip()
            _require(bool(extracted), f"selected page {selected} has no extractable text")
            if not allow_untranslated:
                _require(HAN.search(extracted) is not None, f"selected page {selected} has no Han target text")
        return output_document.page_count


def _issue_counts(value, where: str) -> dict:
    summary = _object(value, where, frozenset({"total", "by_kind"}))
    total = _integer(summary["total"], f"{where}.total")
    by_kind = _object(summary["by_kind"], f"{where}.by_kind")
    _require(set(by_kind) == set(ISSUE_KINDS), f"{where} issue kinds changed")
    normalized = {
        kind: _integer(by_kind[kind], f"{where}.{kind}") for kind in ISSUE_KINDS
    }
    _require(total == sum(normalized.values()), f"{where} issue counts disagree")
    return {"total": total, "by_kind": normalized}


def _validate_sidecar(path: Path, expected, pass_index: int, mirrored: bool) -> None:
    sidecar = _load_json(path, path.name)
    _require(sidecar.get("schema_version") == DETECTION_SCHEMA_VERSION, f"{path.name} schema changed")
    _require(_integer(sidecar.get("pass_index"), f"{path.name}.pass_index") == pass_index, f"{path.name} pass index disagrees")
    counts = _object(sidecar.get("counts"), f"{path.name}.counts")
    actual = _issue_counts(
        {"total": counts.get("issues"), "by_kind": counts.get("by_kind")},
        f"{path.name}.counts",
    )
    _require(actual == expected, f"{path.name} counts disagree with run report")
    _require(("mirrored_after" in sidecar) == mirrored, f"{path.name} mirror evidence disagrees")


def _validate_report(report_path: Path, output: Path, allow_untranslated: bool) -> dict:
    report = _load_json(report_path, RUN_REPORT_NAME)
    _object(report, RUN_REPORT_NAME, ROOT_KEYS)
    _require(report["schema_version"] == RUN_SCHEMA_VERSION, "minimal run schema changed")
    _require(report["status"] == "complete", "minimal run is not complete")
    _require(_boolean(report["completed"], "completed"), "minimal run did not complete")
    translated = _boolean(report["translation_performed"], "translation_performed")
    _require(translated is not allow_untranslated, "validator mode disagrees with translation evidence")

    chain = _object(
        report["chain"],
        "chain",
        frozenset(
            {
                "status",
                "report_path",
                "requests",
                "merged",
                "members",
                "claimed_members",
                "single_request_holds",
                "claim_exclusion_holds",
                "conservation_holds",
                "typed_offline",
            }
        ),
    )
    chain_requests = _integer(chain["requests"], "chain.requests")
    merged = _integer(chain["merged"], "chain.merged")
    members = _integer(chain["members"], "chain.members")
    claimed = _integer(chain["claimed_members"], "chain.claimed_members")
    for name in (
        "single_request_holds",
        "claim_exclusion_holds",
        "conservation_holds",
        "typed_offline",
    ):
        _boolean(chain[name], f"chain.{name}")
    _require(chain["single_request_holds"], "chain single-request invariant failed")
    _require(chain["claim_exclusion_holds"], "chain claim exclusion failed")
    _require(chain["conservation_holds"], "chain conservation failed")
    if translated:
        _require(chain["status"] == "available" and chain["typed_offline"] is False, "translated chain report is unavailable")
        chain_path = Path(_text(chain["report_path"], "chain.report_path"))
        _require(chain_path.is_file(), "chain report path is missing")
        _require(chain_requests == merged and claimed == members, "chain counts violate one-request/claim conservation")
    else:
        _require(chain["status"] == "skipped_translation_not_performed", "offline chain status changed")
        _require(chain["report_path"] is None and chain["typed_offline"] is True, "offline chain evidence is not typed")
        _require(chain_requests == merged == members == claimed == 0, "offline chain counts are non-zero")

    backfill = _object(
        report["backfill"],
        "backfill",
        frozenset(
            {
                "members",
                "released_members",
                "allocation_verified",
                "target_conservation_holds",
                "only_trailing_released",
            }
        ),
    )
    _require(_integer(backfill["members"], "backfill.members") == members, "backfill members disagree with chain")
    _require(_integer(backfill["released_members"], "backfill.released_members") <= members, "released backfill members overflow")
    for name in ("allocation_verified", "target_conservation_holds", "only_trailing_released"):
        _require(_boolean(backfill[name], f"backfill.{name}"), f"backfill {name} failed")

    ordinary = _object(
        report["ordinary"],
        "ordinary",
        frozenset(
            {
                "translator_total",
                "translator_cache",
                "chain_requests",
                "article_context_requests",
                "short_unit_requests",
                "repair_requests",
                "requests",
                "claimed_members_excluded",
            }
        ),
    )
    ordinary_counts = {
        name: _integer(ordinary[name], f"ordinary.{name}")
        for name in (
            "translator_total",
            "translator_cache",
            "chain_requests",
            "article_context_requests",
            "short_unit_requests",
            "repair_requests",
            "requests",
        )
    }
    _require(ordinary_counts["chain_requests"] == chain_requests, "ordinary chain deduction disagrees")
    _require(ordinary_counts["translator_cache"] <= ordinary_counts["translator_total"], "translator cache exceeds total")
    deducted = sum(
        ordinary_counts[name]
        for name in (
            "chain_requests",
            "article_context_requests",
            "short_unit_requests",
            "repair_requests",
            "requests",
        )
    )
    _require(deducted == ordinary_counts["translator_total"], "ordinary translator accounting disagrees")
    _require(_boolean(ordinary["claimed_members_excluded"], "ordinary.claimed_members_excluded"), "ordinary translation included claimed members")
    if not translated:
        _require(not any(ordinary_counts.values()), "offline translator accounting is non-zero")

    flow = _object(
        report["flow"],
        "flow",
        frozenset(
            {
                "segments",
                "placements",
                "cross_page_movements",
                "rolled_back",
                "owner_boundary_holds",
                "physical_adjacency_holds",
                "target_conservation_holds",
            }
        ),
    )
    for name in ("segments", "placements", "cross_page_movements", "rolled_back"):
        _integer(flow[name], f"flow.{name}")
    for name in ("owner_boundary_holds", "physical_adjacency_holds", "target_conservation_holds"):
        _require(_boolean(flow[name], f"flow.{name}"), f"flow {name} failed")

    dropcap = _object(
        report["dropcap"],
        "dropcap",
        frozenset(
            {
                "decided",
                "set",
                "reverted",
                "invalid_intent",
                "typed_no_candidate",
            }
        ),
    )
    decided = _integer(dropcap["decided"], "dropcap.decided")
    rendered = _integer(dropcap["set"], "dropcap.set")
    reverted = _integer(dropcap["reverted"], "dropcap.reverted")
    invalid_intent = _integer(
        dropcap["invalid_intent"],
        "dropcap.invalid_intent",
    )
    _require(
        decided == rendered + reverted + invalid_intent,
        "drop-cap counts do not conserve candidates",
    )
    typed_no_candidate = _boolean(dropcap["typed_no_candidate"], "dropcap.typed_no_candidate")
    expected_typed_no_candidate = decided == 0 or (
        rendered == 0 and reverted + invalid_intent == decided
    )
    _require(
        typed_no_candidate is expected_typed_no_candidate,
        "drop-cap typed no-candidate evidence disagrees with counts",
    )
    _require(rendered > 0 or typed_no_candidate, "drop-cap path has neither render nor typed no-candidate evidence")

    issues = _object(report["issues"], "issues", frozenset({"before", "after"}))
    before = _issue_counts(issues["before"], "issues.before")
    after = _issue_counts(issues["after"], "issues.after")
    detector = _object(
        report["detector"],
        "detector",
        frozenset(
            {
                "passes",
                "before_path",
                "after_path",
                "before_pass_index",
                "after_pass_index",
                "after_mirrored",
            }
        ),
    )
    passes = _integer(detector["passes"], "detector.passes")
    _require(passes in (1, 2), "detector passes must be one or two")
    before_index = _integer(detector["before_pass_index"], "detector.before_pass_index")
    after_index = _integer(detector["after_pass_index"], "detector.after_pass_index")
    mirrored = _boolean(detector["after_mirrored"], "detector.after_mirrored")
    _require(before_index == 0, "before detector pass must be zero")

    repair = _object(
        report["repair"],
        "repair",
        frozenset(
            {
                "selected",
                "reason",
                "action_count",
                "applied_count",
                "translator_requests",
                "detection_passes_added",
                "accepted",
                "rolled_back",
            }
        ),
    )
    selected = repair["selected"]
    _require(
        selected is None
        or selected
        in {"translate_orphan_text", "refit_or_reflow_owned_paragraph", "no_op"},
        "repair selected an unallowed action",
    )
    _text(repair["reason"], "repair.reason")
    action_count = _integer(repair["action_count"], "repair.action_count")
    applied_count = _integer(repair["applied_count"], "repair.applied_count")
    repair_requests = _integer(repair["translator_requests"], "repair.translator_requests")
    added_passes = _integer(repair["detection_passes_added"], "repair.detection_passes_added")
    accepted = _boolean(repair["accepted"], "repair.accepted")
    rolled_back = _boolean(repair["rolled_back"], "repair.rolled_back")
    _require(action_count <= 1 and applied_count <= action_count, "repair action count exceeds one")
    _require(added_passes in (0, 1) and passes == 1 + added_passes, "repair/detector pass counts disagree")
    _require(repair_requests == ordinary_counts["repair_requests"], "repair request accounting disagrees")
    _require(not (accepted and rolled_back), "repair cannot be accepted and rolled back")
    expected_after_index = 1 if accepted else 0
    _require(after_index == expected_after_index, "final after pass index disagrees with repair")
    _require(mirrored is not accepted, "final after mirror evidence disagrees with repair")

    before_path = Path(_text(detector["before_path"], "detector.before_path")).resolve()
    after_path = Path(_text(detector["after_path"], "detector.after_path")).resolve()
    _require(before_path == (report_path.parent / "issues.before.json").resolve(), "before sidecar is outside report directory")
    _require(after_path == (report_path.parent / "issues.after.json").resolve(), "after sidecar is outside report directory")
    _validate_sidecar(before_path, before, before_index, False)
    _validate_sidecar(after_path, after, after_index, mirrored)

    fixed = _object(report["fixed"], "fixed", frozenset({"holds", "drift_count"}))
    _require(_boolean(fixed["holds"], "fixed.holds"), "fixed assets drifted")
    _require(_integer(fixed["drift_count"], "fixed.drift_count") == 0, "fixed drift count is non-zero")

    output_record = _object(
        report["output"],
        "output",
        frozenset({"status", "mono", "dual", "no_watermark_mono", "no_watermark_dual"}),
    )
    _require(output_record["status"] == "complete", "output status is not complete")
    mono = Path(_text(output_record["mono"], "output.mono")).resolve()
    _require(mono == output.resolve(), "run report mono output differs from selected PDF")
    for name in ("dual", "no_watermark_mono", "no_watermark_dual"):
        value = output_record[name]
        if value is not None:
            _require(Path(_text(value, f"output.{name}")).is_file(), f"output.{name} is missing")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--translated-pages", type=_parse_pages, default=(7, 8))
    parser.add_argument("--allow-untranslated", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    _require(args.output_dir.is_dir(), f"output directory is missing: {args.output_dir}")
    _require(args.run_dir.is_dir(), f"run directory is missing: {args.run_dir}")
    output = _unique(args.output_dir.glob("*.mono.pdf"), "monolingual output")
    page_count = _validate_pdf(
        args.source,
        output,
        args.translated_pages,
        args.allow_untranslated,
    )
    report_path = _unique(
        args.run_dir.rglob(RUN_REPORT_NAME),
        RUN_REPORT_NAME,
    )
    _validate_report(report_path, output, args.allow_untranslated)
    print(
        json.dumps(
            {
                "status": "MINIMAL_PDF_VALID",
                "output": str(output),
                "pages": page_count,
                "translated_pages": list(args.translated_pages),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
