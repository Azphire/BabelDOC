"""Read-only compliance checks for the final searchable PDF."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import pymupdf

from babeldoc.magazine.hitl_expectation import ManualConstraintExpectation
from babeldoc.magazine.page_identity import UNBOUND_SOURCE_PDF_SHA256
from babeldoc.magazine.page_identity import PageSelectionMap
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import record_config_manifest

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = config_path("final_pdf_compliance.json")
REPORT_NAME = "final_pdf_compliance.json"
SCHEMA_VERSION = "final-pdf-compliance.v1"
NORMALIZATION_VERSION = "nfkc-whitespace-v1"
SWITCH = "magazine_pdf_compliance"
STATUS_PASS = "pass"  # noqa: S105 - compliance status, not a credential
STATUS_DEGRADED = "degraded"
STATUS_FAIL = "fail"

Box = tuple[float, float, float, float]


class FinalPdfConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FinalPdfConfig:
    page_box_tolerance_pt: float
    text_bound_tolerance_pt: float
    asset_bbox_tolerance_pt: float
    allowed_extra_target_occurrences: int
    minimum_touched_text_characters: int
    minimum_text_retention_ratio: float
    drop_cap_font_size_tolerance_ratio: float
    drop_cap_min_body_size_ratio: float
    drop_cap_bbox_tolerance_pt: float
    drop_cap_color_tolerance: float


@dataclass(frozen=True, slots=True)
class TargetExpectation:
    fragment_id: str
    source_ref: str
    page: int
    text: str
    box: Box | None = None
    article_bounds: tuple[Box, ...] = ()


@dataclass(frozen=True, slots=True)
class DropCapExpectation:
    source_ref: str
    page: int
    character: str
    policy: str
    box: Box | None
    font_size: float | None
    rgb: tuple[float, float, float] | None
    body_text: str | None = None


@dataclass(frozen=True, slots=True)
class ComplianceExpectations:
    expected_page_count: int | None = None
    touched_pages: tuple[int, ...] = ()
    targets: tuple[TargetExpectation, ...] = ()
    protected_bounds: dict[int, tuple[Box, ...]] = field(default_factory=dict)
    drop_caps: tuple[DropCapExpectation, ...] = ()
    page_selection_map: PageSelectionMap | None = None
    expected_source_page_geometry_by_physical_page: Mapping[int, dict] = field(
        default_factory=dict
    )
    expected_page_labels_by_physical_page: Mapping[int, str] = field(
        default_factory=dict
    )
    fixed_assets_by_physical_page: Mapping[int, tuple[dict, ...]] = field(
        default_factory=dict
    )
    article_refs_by_physical_page: Mapping[int, tuple[str, ...]] = field(
        default_factory=dict
    )
    chain_refs_by_physical_page: Mapping[int, tuple[str, ...]] = field(
        default_factory=dict
    )
    runtrace_refs_by_physical_page: Mapping[int, tuple[str, ...]] = field(
        default_factory=dict
    )
    manual_constraint_expectations: tuple[ManualConstraintExpectation, ...] = ()


@dataclass(frozen=True, slots=True)
class ComplianceResult:
    status: str
    report_path: Path
    record: dict

    @property
    def fully_compliant(self) -> bool:
        return self.status == STATUS_PASS

    def trace_binding(self) -> dict:
        selection = self.record.get("page_selection_map") or {}
        return {
            "schema_version": self.record.get("schema_version"),
            "status": self.status,
            "fully_compliant": self.fully_compliant,
            "report": str(self.report_path),
            "issue_count": len(self.record.get("issues", ())),
            "output_sha256": self.record.get("output", {}).get("sha256"),
            "page_selection_mapping_sha256": selection.get("mapping_sha256"),
        }


def _parse_range(value: object, key: str) -> tuple[float, float]:
    match = re.fullmatch(
        r"(-?(?:\d+(?:\.\d*)?|\.\d+))\.\.(-?(?:\d+(?:\.\d*)?|\.\d+))", str(value)
    )
    if match is None:
        raise FinalPdfConfigError(f"{key} must be a low..high range")
    return float(match.group(1)), float(match.group(2))


def load_config(path: str | Path = CONFIG_PATH) -> FinalPdfConfig:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise FinalPdfConfigError("unsupported final PDF compliance schema")
    if raw.get("normalization_version") != NORMALIZATION_VERSION:
        raise FinalPdfConfigError("unsupported final PDF normalization version")
    names = tuple(FinalPdfConfig.__dataclass_fields__)
    expected = {"schema_version", "normalization_version"}
    expected.update(names)
    expected.update(f"{name}_allowed_range" for name in names)
    if set(raw) != expected:
        raise FinalPdfConfigError(f"{source.name}: keys must be {sorted(expected)}")
    values: dict[str, int | float] = {}
    integer_names = {
        "allowed_extra_target_occurrences",
        "minimum_touched_text_characters",
    }
    for name in names:
        value = raw[name]
        if name in integer_names:
            if not isinstance(value, int) or isinstance(value, bool):
                raise FinalPdfConfigError(f"{name} must be an integer")
        elif not isinstance(value, int | float) or isinstance(value, bool):
            raise FinalPdfConfigError(f"{name} must be numeric")
        low, high = _parse_range(raw[f"{name}_allowed_range"], name)
        if not low <= float(value) <= high:
            raise FinalPdfConfigError(f"{name} is outside its allowed range")
        values[name] = value
    return FinalPdfConfig(**values)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    return " ".join(normalized.split())


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_summary(path: Path) -> dict:
    exists = path.is_file()
    return {
        "path": str(path),
        "exists": exists,
        "size": path.stat().st_size if exists else None,
        "sha256": _sha256(path),
    }


def _box(value: Any) -> Box:
    if hasattr(value, "x0"):
        return tuple(float(getattr(value, name)) for name in ("x0", "y0", "x1", "y1"))
    return tuple(float(item) for item in value)


def _box_close(left: Box, right: Box, tolerance: float) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(left, right, strict=True))


def _flip_box(value: Box, height: float) -> Box:
    return value[0], height - value[3], value[2], height - value[1]


def _box_variants(value: Box, height: float) -> tuple[Box, ...]:
    flipped = _flip_box(value, height)
    return (value,) if _box_close(value, flipped, 0.0) else (value, flipped)


def _contains(outer: Box, inner: Box, tolerance: float) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def _box_consistent(left: Box, right: Box, tolerance: float) -> bool:
    return (
        _box_close(left, right, tolerance)
        or _contains(left, right, tolerance)
        or _contains(right, left, tolerance)
    )


def _overlaps(left: Box, right: Box, tolerance: float) -> bool:
    return (
        min(left[2], right[2]) - max(left[0], right[0]) > tolerance
        and min(left[3], right[3]) - max(left[1], right[1]) > tolerance
    )


def _union(boxes: list[Box]) -> Box | None:
    if not boxes:
        return None
    return (
        min(item[0] for item in boxes),
        min(item[1] for item in boxes),
        max(item[2] for item in boxes),
        max(item[3] for item in boxes),
    )


def _raw_page(page) -> tuple[str, list[Box | None], list[dict]]:
    raw = page.get_text("rawdict")
    characters: list[tuple[str, Box | None]] = []
    spans: list[dict] = []
    for block in raw.get("blocks", ()):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", ()):
            for span in line.get("spans", ()):
                span_chars = span.get("chars", ())
                text = "".join(item.get("c", "") for item in span_chars)
                spans.append(
                    {
                        "text": text,
                        "bbox": list(_box(span["bbox"])),
                        "font": span.get("font"),
                        "size": span.get("size"),
                        "color": span.get("color"),
                    }
                )
                for item in span_chars:
                    characters.append((item.get("c", ""), _box(item["bbox"])))
            characters.append((" ", None))
    output: list[str] = []
    mapping: list[Box | None] = []
    pending_space = False
    for character, bbox in characters:
        expanded = unicodedata.normalize("NFKC", character)
        for item in expanded:
            if item in ("\u200b", "\ufeff"):
                continue
            if item.isspace():
                pending_space = bool(output)
                continue
            if pending_space:
                output.append(" ")
                mapping.append(None)
                pending_space = False
            output.append(item)
            mapping.append(bbox)
    return "".join(output), mapping, spans


def _occurrences(haystack: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    found = []
    cursor = 0
    while True:
        index = haystack.find(needle, cursor)
        if index < 0:
            return found
        found.append((index, index + len(needle)))
        cursor = index + 1


def _occurrence_boxes(
    mapping: list[Box | None], ranges: list[tuple[int, int]]
) -> list[Box | None]:
    return [
        _union([box for box in mapping[start:end] if box is not None])
        for start, end in ranges
    ]


def _page_geometry(page) -> dict:
    return {
        "mediabox": list(_box(page.mediabox)),
        "cropbox": list(_box(page.cropbox)),
        "rotation": int(page.rotation),
    }


def _catalog_ok(document) -> tuple[bool, dict]:
    catalog = int(document.pdf_catalog())
    pages_type, pages_value = document.xref_get_key(catalog, "Pages")
    page_nodes = []
    ok = catalog > 0 and pages_type != "null" and pages_value != "null"
    for page in document:
        type_name = document.xref_get_key(page.xref, "Type")[1]
        page_ok = page.xref > 0 and type_name == "/Page"
        ok = ok and page_ok
        page_nodes.append(
            {
                "page": page.number + 1,
                "xref": page.xref,
                "type": type_name,
                "ok": page_ok,
            }
        )
    return ok, {"catalog_xref": catalog, "pages": pages_value, "page_nodes": page_nodes}


def _asset_records(page) -> list[dict]:
    records = []
    for item in page.get_image_info(xrefs=True):
        bbox = item.get("bbox")
        digest = item.get("digest")
        records.append(
            {
                "kind": "image",
                "bbox": None if bbox is None else _box(bbox),
                "digest": digest.hex() if isinstance(digest, bytes) else digest,
            }
        )
    for item in page.get_xobjects():
        bbox = item[3] if len(item) > 3 else None
        records.append(
            {"kind": "form_xobject", "bbox": None if bbox is None else _box(bbox)}
        )
    for item in page.get_drawings():
        rect = item.get("rect")
        records.append(
            {"kind": "drawing", "bbox": None if rect is None else _box(rect)}
        )
    return records


def _compare_assets(before: list[dict], after: list[dict], tolerance: float) -> dict:
    counts_before = Counter(item["kind"] for item in before)
    counts_after = Counter(item["kind"] for item in after)
    drift = []
    for kind in sorted(set(counts_before) | set(counts_after)):
        left = [item for item in before if item["kind"] == kind]
        right = [item for item in after if item["kind"] == kind]
        unmatched = list(right)
        for asset in left:
            bbox = asset["bbox"]
            candidate = next(
                (
                    item
                    for item in unmatched
                    if (
                        (bbox is None and item["bbox"] is None)
                        or (
                            bbox is not None
                            and item["bbox"] is not None
                            and _box_close(bbox, item["bbox"], tolerance)
                        )
                    )
                    and asset.get("digest") == item.get("digest")
                ),
                None,
            )
            if candidate is None:
                drift.append(
                    {
                        "kind": kind,
                        "bbox": None if bbox is None else list(bbox),
                        "digest": asset.get("digest"),
                    }
                )
            else:
                unmatched.remove(candidate)
    return {
        "holds": counts_before == counts_after and not drift,
        "counts_before": dict(sorted(counts_before.items())),
        "counts_after": dict(sorted(counts_after.items())),
        "bbox_drift": drift,
    }


def _rgb(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, int):
        return None
    return ((value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255)


def _eligible(character: str, policy: str) -> bool:
    if len(character) != 1:
        return False
    codepoint = ord(character)
    if policy == "chinese_two_line_initial":
        return 0x3400 <= codepoint <= 0x9FFF or 0xF900 <= codepoint <= 0xFAFF
    return character.isalpha()


def expectations_from_runtime(
    run_trace,
    *,
    expected_page_count: int | None,
    article_document_ir=None,
    fixed_asset_inventory=None,
    manual_constraint_expectations=(),
) -> ComplianceExpectations:
    page_selection_map = (
        None
        if article_document_ir is None
        else article_document_ir.page_selection_map
    )
    expected_geometry: dict[int, dict] = {}
    fixed_by_page: dict[int, list[dict]] = {}
    if fixed_asset_inventory is not None:
        expected_geometry = {
            int(page): {
                "mediabox": None if media is None else list(media),
                "cropbox": None if crop is None else list(crop),
                "rotation": None,
            }
            for page, media, crop in fixed_asset_inventory.page_sizes
        }
        for asset in fixed_asset_inventory.assets:
            fixed_by_page.setdefault(int(asset.page), []).append(asset.to_record())
    article_refs: dict[int, list[str]] = {}
    chain_refs: dict[int, list[str]] = {}
    if article_document_ir is not None:
        for article in article_document_ir.articles:
            for page in article.pages:
                article_refs.setdefault(int(page), []).append(article.article_id)
        for chain in article_document_ir.chains:
            for page, reference in zip(
                chain.member_physical_pages,
                chain.ordered_member_refs,
                strict=True,
            ):
                chain_refs.setdefault(int(page), []).append(
                    f"{chain.chain_id}:{reference}"
                )
    runtrace_refs: dict[int, list[str]] = {}
    if run_trace is not None:
        for reference, source in run_trace.sources.items():
            runtrace_refs.setdefault(int(source.page), []).append(reference)
    common = {
        "expected_source_page_geometry_by_physical_page": expected_geometry,
        "fixed_assets_by_physical_page": {
            page: tuple(sorted(items, key=lambda item: item["reference"]))
            for page, items in fixed_by_page.items()
        },
        "article_refs_by_physical_page": {
            page: tuple(sorted(set(items))) for page, items in article_refs.items()
        },
        "chain_refs_by_physical_page": {
            page: tuple(sorted(set(items))) for page, items in chain_refs.items()
        },
        "runtrace_refs_by_physical_page": {
            page: tuple(sorted(set(items))) for page, items in runtrace_refs.items()
        },
        "manual_constraint_expectations": tuple(manual_constraint_expectations),
    }
    if run_trace is None:
        return ComplianceExpectations(
            expected_page_count=expected_page_count,
            page_selection_map=page_selection_map,
            **common,
        )
    article_bounds: dict[tuple[str, int], tuple[Box, ...]] = {}
    if article_document_ir is not None:
        for article in article_document_ir.articles:
            for page in article.pages:
                article_bounds[(article.article_id, page)] = tuple(
                    tuple(float(value) for value in slot.box)
                    for slot in article.slots
                    if slot.page == page and slot.box is not None
                )
    targets = []
    touched = set()
    for fragment in run_trace.fragments.values():
        if not fragment.active:
            continue
        geometries = [
            run_trace.geometries[item]
            for item in fragment.geometry_ids
            if run_trace.geometries[item].active
            and run_trace.geometries[item].render_status == "rendered"
        ]
        if len(geometries) != 1 or geometries[0].final_page is None:
            continue
        geometry = geometries[0]
        source = run_trace.sources[fragment.source_ref]
        page = int(geometry.final_page)
        touched.add(page)
        targets.append(
            TargetExpectation(
                fragment_id=fragment.fragment_id,
                source_ref=fragment.source_ref,
                page=page,
                text=run_trace.target_fragment_text(fragment.fragment_id),
                box=geometry.final_box,
                article_bounds=article_bounds.get((source.article_id, page), ()),
            )
        )
    protected: dict[int, list[Box]] = {}
    if fixed_asset_inventory is not None:
        for asset in fixed_asset_inventory.assets:
            if asset.asset_type == "pdf_paragraph_furniture" and asset.bbox is not None:
                protected.setdefault(asset.page, []).append(asset.bbox)
    latest_drop_caps: dict[str, dict] = {}
    for event in run_trace.drop_cap_events:
        if (
            event.get("render_status") == "applied"
            and event.get("initial_char_count") == 1
        ):
            latest_drop_caps[str(event["source_ref"])] = event
    drop_caps = []
    for reference, event in sorted(latest_drop_caps.items()):
        source = run_trace.sources.get(reference)
        if source is None:
            continue
        page = source.page
        touched.add(page)
        style = event.get("style_evidence") or {}
        color = event.get("color_evidence") or {}
        fill = color.get("fill") or {}
        rgb = fill.get("rgb")
        body_fragments = run_trace.target_fragments_for_source(reference)
        drop_caps.append(
            DropCapExpectation(
                source_ref=reference,
                page=page,
                character=str(
                    event.get("target_char") or event.get("initial_char") or ""
                ),
                policy=str(event.get("target_policy") or ""),
                box=None
                if event.get("initial_ink_box") is None
                else tuple(float(value) for value in event["initial_ink_box"]),
                font_size=None
                if style.get("font_size") is None
                else float(style["font_size"]),
                rgb=None if rgb is None else tuple(float(value) for value in rgb),
                body_text="".join(item["text"] for item in body_fragments) or None,
            )
        )
    return ComplianceExpectations(
        expected_page_count=expected_page_count,
        touched_pages=tuple(sorted(touched)),
        targets=tuple(targets),
        protected_bounds={page: tuple(boxes) for page, boxes in protected.items()},
        drop_caps=tuple(drop_caps),
        page_selection_map=page_selection_map,
        **common,
    )


def offset_expectations(
    expectations: ComplianceExpectations, page_offset: int
) -> ComplianceExpectations:
    return ComplianceExpectations(
        expected_page_count=expectations.expected_page_count,
        touched_pages=tuple(page + page_offset for page in expectations.touched_pages),
        targets=tuple(
            TargetExpectation(
                fragment_id=target.fragment_id,
                source_ref=target.source_ref,
                page=target.page + page_offset,
                text=target.text,
                box=target.box,
                article_bounds=target.article_bounds,
            )
            for target in expectations.targets
        ),
        protected_bounds={
            page + page_offset: boxes
            for page, boxes in expectations.protected_bounds.items()
        },
        drop_caps=tuple(
            DropCapExpectation(
                source_ref=item.source_ref,
                page=item.page + page_offset,
                character=item.character,
                policy=item.policy,
                box=item.box,
                font_size=item.font_size,
                rgb=item.rgb,
                body_text=item.body_text,
            )
            for item in expectations.drop_caps
        ),
        page_selection_map=expectations.page_selection_map,
        expected_source_page_geometry_by_physical_page={
            page + page_offset: geometry
            for page, geometry in expectations.expected_source_page_geometry_by_physical_page.items()
        },
        expected_page_labels_by_physical_page={
            page + page_offset: label
            for page, label in expectations.expected_page_labels_by_physical_page.items()
        },
        fixed_assets_by_physical_page={
            page + page_offset: assets
            for page, assets in expectations.fixed_assets_by_physical_page.items()
        },
        article_refs_by_physical_page={
            page + page_offset: refs
            for page, refs in expectations.article_refs_by_physical_page.items()
        },
        chain_refs_by_physical_page={
            page + page_offset: refs
            for page, refs in expectations.chain_refs_by_physical_page.items()
        },
        runtrace_refs_by_physical_page={
            page + page_offset: refs
            for page, refs in expectations.runtrace_refs_by_physical_page.items()
        },
        manual_constraint_expectations=expectations.manual_constraint_expectations,
    )


def merge_expectations(
    items: tuple[ComplianceExpectations, ...], expected_page_count: int
) -> ComplianceExpectations:
    return ComplianceExpectations(
        expected_page_count=expected_page_count,
        touched_pages=tuple(
            sorted({page for item in items for page in item.touched_pages})
        ),
        targets=tuple(target for item in items for target in item.targets),
        protected_bounds={
            page: tuple(
                box for item in items for box in item.protected_bounds.get(page, ())
            )
            for page in sorted(
                {page for item in items for page in item.protected_bounds}
            )
        },
        drop_caps=tuple(drop_cap for item in items for drop_cap in item.drop_caps),
        page_selection_map=None,
        expected_source_page_geometry_by_physical_page={
            page: geometry
            for item in items
            for page, geometry in item.expected_source_page_geometry_by_physical_page.items()
        },
        expected_page_labels_by_physical_page={
            page: label
            for item in items
            for page, label in item.expected_page_labels_by_physical_page.items()
        },
        fixed_assets_by_physical_page={
            page: assets
            for item in items
            for page, assets in item.fixed_assets_by_physical_page.items()
        },
        article_refs_by_physical_page={
            page: refs
            for item in items
            for page, refs in item.article_refs_by_physical_page.items()
        },
        chain_refs_by_physical_page={
            page: refs
            for item in items
            for page, refs in item.chain_refs_by_physical_page.items()
        },
        runtrace_refs_by_physical_page={
            page: refs
            for item in items
            for page, refs in item.runtrace_refs_by_physical_page.items()
        },
        manual_constraint_expectations=tuple(
            expectation
            for item in items
            for expectation in item.manual_constraint_expectations
        ),
    )


def record_pipeline_status(translation_config, result: ComplianceResult) -> Path:
    from babeldoc.magazine.runtime_profile import RUN_MANIFEST_NAME

    path = Path(translation_config.get_working_file_path(RUN_MANIFEST_NAME))
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = {"manifest_version": 1}
    manifest["final_pdf_compliance"] = result.trace_binding()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


class FinalPdfValidator:
    def __init__(self, config: FinalPdfConfig | None = None):
        self.config = config or load_config()

    def validate(
        self,
        source_pdf: str | Path,
        output_pdf: str | Path,
        report_path: str | Path,
        *,
        expectations: ComplianceExpectations | None = None,
        writer_warnings=(),
    ) -> ComplianceResult:
        source_path = Path(source_pdf)
        output_path = Path(output_pdf)
        destination = Path(report_path)
        expected = expectations or ComplianceExpectations()
        record = {
            "schema_version": SCHEMA_VERSION,
            "normalization": {
                "version": NORMALIZATION_VERSION,
                "unicode": "NFKC",
                "whitespace": "collapse",
            },
            "status": STATUS_FAIL,
            "fully_compliant": False,
            "input": _file_summary(source_path),
            "output": _file_summary(output_path),
            "touched_pages": list(expected.touched_pages),
            "page_selection_map": (
                None
                if expected.page_selection_map is None
                else expected.page_selection_map.to_record()
            ),
            "checks": [],
            "evidence": {
                "pages": [],
                "assets": [],
                "drop_caps": [],
                "mapping": {},
                "references": [],
            },
            "trace_reconciliation": [],
            "writer_warnings": [dict(item) for item in writer_warnings],
            "issues": [],
        }

        def check(
            name: str,
            holds: bool,
            evidence=None,
            *,
            code: str | None = None,
            detail: str | None = None,
            page: int | None = None,
            reference: str | None = None,
        ) -> None:
            row = {"name": name, "status": STATUS_PASS if holds else STATUS_FAIL}
            if evidence is not None:
                row["evidence"] = evidence
            record["checks"].append(row)
            if not holds:
                record["issues"].append(
                    {
                        "code": code or name,
                        "check": name,
                        "page": page,
                        "reference": reference,
                        "detail": detail or f"{name} failed",
                    }
                )

        source = None
        output = None
        try:
            try:
                output = pymupdf.open(output_path)
                output.authenticate("")
                record["output"]["page_count"] = len(output)
                check(
                    "output_reopen",
                    not output.needs_pass and not output.is_repaired,
                    {
                        "page_count": len(output),
                        "encrypted": bool(output.needs_pass),
                        "repaired": bool(output.is_repaired),
                    },
                    code="output_unreadable",
                )
            except Exception as exc:
                check(
                    "output_reopen",
                    False,
                    code="output_unreadable",
                    detail=f"{type(exc).__name__}: {exc}",
                )
                return self._finish(record, destination)
            try:
                source = pymupdf.open(source_path)
                source.authenticate("")
                record["input"]["page_count"] = len(source)
                check(
                    "input_reopen",
                    not source.needs_pass,
                    {"page_count": len(source)},
                    code="input_unreadable",
                )
            except Exception as exc:
                check(
                    "input_reopen",
                    False,
                    code="input_unreadable",
                    detail=f"{type(exc).__name__}: {exc}",
                )
                return self._finish(record, destination)

            selection = expected.page_selection_map
            if selection is None:
                selection = PageSelectionMap.from_source_pdf(source_path)
            record["page_selection_map"] = selection.to_record()
            actual_source_sha256 = record["input"]["sha256"]
            source_hash_holds = (
                selection.source_pdf_sha256 != UNBOUND_SOURCE_PDF_SHA256
                and selection.source_pdf_sha256 == actual_source_sha256
            )
            check(
                "page_mapping_source_binding",
                source_hash_holds,
                {
                    "expected_sha256": selection.source_pdf_sha256,
                    "actual_sha256": actual_source_sha256,
                    "source_page_count": selection.source_page_count,
                },
                code="page_mapping_source_mismatch",
            )
            check(
                "page_mapping_source_count",
                selection.source_page_count == len(source),
                {
                    "expected": selection.source_page_count,
                    "actual": len(source),
                },
                code="page_mapping_source_count_mismatch",
            )

            mapped_physical_pages = tuple(
                int(page)
                for page in selection.output_index_to_physical_page.values()
            )
            mapped_output_indexes = tuple(
                int(index) for index in selection.output_index_to_physical_page
            )
            mapping_holds = (
                mapped_output_indexes == tuple(range(len(output)))
                and len(mapped_physical_pages) == len(set(mapped_physical_pages))
            )
            record["evidence"]["mapping"] = {
                "mapping_sha256": selection.mapping_sha256,
                "physical_pages": list(mapped_physical_pages),
                "output_indexes": list(mapped_output_indexes),
                "holds": mapping_holds,
            }
            check(
                "page_mapping_coverage",
                mapping_holds,
                record["evidence"]["mapping"],
                code="page_mapping_coverage_mismatch",
            )

            expected_count = expected.expected_page_count
            if expected_count is None:
                expected_count = len(selection.output_index_to_physical_page)
            check(
                "page_count",
                len(output) == expected_count
                == len(selection.output_index_to_physical_page),
                {
                    "expected": expected_count,
                    "mapping": len(selection.output_index_to_physical_page),
                    "actual": len(output),
                },
                code="page_count_mismatch",
            )

            catalog_holds, catalog_evidence = _catalog_ok(output)
            check(
                "catalog_page_tree",
                catalog_holds,
                catalog_evidence,
                code="catalog_page_tree_invalid",
            )
            source_labels = {
                physical_page: source[physical_page - 1].get_label()
                for physical_page in mapped_physical_pages
                if 1 <= physical_page <= len(source)
            }
            projected_labels = {
                physical_page: expected.expected_page_labels_by_physical_page.get(
                    physical_page, label
                )
                for physical_page, label in source_labels.items()
            }
            output_labels = {
                physical_page: output[output_index].get_label()
                for output_index, physical_page in enumerate(mapped_physical_pages)
                if output_index < len(output)
            }
            check(
                "page_labels",
                projected_labels == output_labels,
                {"expected": projected_labels, "output": output_labels},
                code="page_labels_mismatch",
            )

            geometry_pairs = tuple(
                (int(physical), int(output_index))
                for output_index, physical in selection.output_index_to_physical_page.items()
            )
            geometry_holds = len(geometry_pairs) == len(output)
            page_evidence = []
            for physical_page, output_index in geometry_pairs:
                if not 1 <= physical_page <= len(source) or not 0 <= output_index < len(output):
                    geometry_holds = False
                    continue
                source_geometry = _page_geometry(source[physical_page - 1])
                declared = expected.expected_source_page_geometry_by_physical_page.get(
                    physical_page, {}
                )
                left = {
                    key: source_geometry[key]
                    if declared.get(key) is None
                    else declared[key]
                    for key in ("mediabox", "cropbox", "rotation")
                }
                right = _page_geometry(output[output_index])
                holds = (
                    _box_close(
                        tuple(left["mediabox"]),
                        tuple(right["mediabox"]),
                        self.config.page_box_tolerance_pt,
                    )
                    and _box_close(
                        tuple(left["cropbox"]),
                        tuple(right["cropbox"]),
                        self.config.page_box_tolerance_pt,
                    )
                    and left["rotation"] == right["rotation"]
                )
                geometry_holds = geometry_holds and holds
                page_evidence.append(
                    {
                        "physical_page": physical_page,
                        "output_index": output_index,
                        "source": source_geometry,
                        "input": left,
                        "output": right,
                        "holds": holds,
                    }
                )
            record["evidence"]["pages"] = page_evidence
            check(
                "page_geometry",
                geometry_holds,
                {"pages": page_evidence},
                code="page_geometry_mismatch",
            )

            self._check_mapped_assets(
                source,
                output,
                selection,
                expected,
                record,
                check,
            )
            self._check_reference_projection(selection, expected, record, check)

            self._check_touched(source, output, selection, expected, record, check)
        except Exception as exc:
            check(
                "validator_exception",
                False,
                code="validator_exception",
                detail=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if output is not None:
                output.close()
            if source is not None:
                source.close()
        return self._finish(record, destination)

    def _check_mapped_assets(
        self, source, output, selection, expected, record, check
    ) -> None:
        for output_index, physical in selection.output_index_to_physical_page.items():
            page_number = int(physical)
            if not 1 <= page_number <= len(source) or not 0 <= output_index < len(output):
                continue
            before_assets = _asset_records(source[page_number - 1])
            after_assets = _asset_records(output[output_index])
            comparison = _compare_assets(
                before_assets, after_assets, self.config.asset_bbox_tolerance_pt
            )
            comparison.update(
                {
                    "physical_page": page_number,
                    "output_index": int(output_index),
                    "inventory_refs": [
                        item.get("reference")
                        for item in expected.fixed_assets_by_physical_page.get(
                            page_number, ()
                        )
                    ],
                }
            )
            record["evidence"]["assets"].append(comparison)
            check(
                "fixed_assets",
                comparison["holds"],
                comparison,
                code="fixed_asset_drift",
                page=page_number,
            )

    def _check_reference_projection(self, selection, expected, record, check) -> None:
        projected = {
            int(page)
            for page in selection.output_index_to_physical_page.values()
        }
        for kind, references in (
            ("article", expected.article_refs_by_physical_page),
            ("chain", expected.chain_refs_by_physical_page),
            ("runtrace", expected.runtrace_refs_by_physical_page),
        ):
            for physical_page, refs in sorted(references.items()):
                if int(physical_page) not in projected:
                    continue
                output_index = selection.output_index_of(int(physical_page))
                holds = output_index is not None and bool(refs)
                evidence = {
                    "kind": kind,
                    "physical_page": int(physical_page),
                    "output_index": None if output_index is None else int(output_index),
                    "refs": list(refs),
                }
                record["evidence"]["references"].append(evidence)
                check(
                    f"{kind}_reference_projection",
                    holds,
                    evidence,
                    code=f"{kind}_reference_projection_missing",
                    page=int(physical_page),
                )

    def _check_touched(
        self, source, output, selection, expected, record, check
    ) -> None:
        page_cache = {}
        for page_number in expected.touched_pages:
            output_index = selection.output_index_of(page_number)
            if output_index is None or not 0 <= output_index < len(output):
                check(
                    "touched_page_exists",
                    False,
                    code="touched_page_missing",
                    page=page_number,
                )
                continue
            page = output[output_index]
            text, mapping, spans = _raw_page(page)
            page_cache[page_number] = (text, mapping, spans)
            source_text = (
                normalize_text(source[page_number - 1].get_text("text"))
                if page_number <= len(source)
                else ""
            )
            visible = len(text.replace(" ", ""))
            retention = (
                1.0
                if not source_text
                else visible / max(1, len(source_text.replace(" ", "")))
            )
            text_holds = (
                visible >= self.config.minimum_touched_text_characters
                and retention >= self.config.minimum_text_retention_ratio
            )
            check(
                "touched_page_searchable_text",
                text_holds,
                {
                    "characters": visible,
                    "source_characters": len(source_text.replace(" ", "")),
                    "retention_ratio": retention,
                },
                code="touched_page_abnormally_blank",
                page=page_number,
            )
            page_box = _box(page.cropbox)
            span_holds = all(
                _contains(
                    page_box, tuple(span["bbox"]), self.config.text_bound_tolerance_pt
                )
                for span in spans
            )
            check(
                "text_spans_within_page",
                span_holds,
                {
                    "span_count": len(spans),
                    "font_color_summary": [
                        {
                            "font": item["font"],
                            "size": item["size"],
                            "color": item["color"],
                        }
                        for item in spans
                    ],
                },
                code="text_span_outside_page",
                page=page_number,
            )

        grouped = Counter(
            (target.page, normalize_text(target.text))
            for target in expected.targets
            if normalize_text(target.text)
        )
        occurrence_cache: dict[
            tuple[int, str], tuple[list[tuple[int, int]], list[Box | None]]
        ] = {}
        for (page_number, target_text), expected_occurrences in sorted(grouped.items()):
            if page_number not in page_cache:
                continue
            text, mapping, _spans = page_cache[page_number]
            ranges = _occurrences(text, target_text)
            boxes = _occurrence_boxes(mapping, ranges)
            occurrence_cache[(page_number, target_text)] = ranges, boxes
            coverage = len(ranges) >= expected_occurrences
            duplicate_holds = (
                len(ranges)
                <= expected_occurrences + self.config.allowed_extra_target_occurrences
            )
            check(
                "target_fragment_coverage",
                coverage,
                {
                    "target_hash": hashlib.sha256(target_text.encode()).hexdigest(),
                    "expected": expected_occurrences,
                    "actual": len(ranges),
                },
                code="target_fragment_missing",
                page=page_number,
            )
            check(
                "target_fragment_duplicates",
                duplicate_holds,
                {
                    "target_hash": hashlib.sha256(target_text.encode()).hexdigest(),
                    "expected": expected_occurrences,
                    "actual": len(ranges),
                },
                code="target_fragment_duplicate",
                page=page_number,
            )

        assigned: dict[tuple[int, str], int] = Counter()
        for target in expected.targets:
            target_text = normalize_text(target.text)
            ranges, boxes = occurrence_cache.get((target.page, target_text), ([], []))
            index = assigned[(target.page, target_text)]
            assigned[(target.page, target_text)] += 1
            actual_box = boxes[index] if index < len(boxes) else None
            page_height = (
                output[
                    selection.require_output_index(target.page)
                ].rect.height
                if selection.output_index_of(target.page) is not None
                else 0.0
            )
            geometry_holds = actual_box is not None
            if geometry_holds and target.box is not None:
                geometry_holds = any(
                    _box_consistent(
                        candidate, actual_box, self.config.text_bound_tolerance_pt
                    )
                    for candidate in _box_variants(target.box, page_height)
                )
            article_holds = actual_box is not None
            if article_holds and target.article_bounds:
                article_holds = any(
                    _contains(
                        candidate, actual_box, self.config.text_bound_tolerance_pt
                    )
                    for bound in target.article_bounds
                    for candidate in _box_variants(bound, page_height)
                )
            protected_holds = actual_box is not None and not any(
                _overlaps(actual_box, candidate, self.config.text_bound_tolerance_pt)
                for bound in expected.protected_bounds.get(target.page, ())
                for candidate in _box_variants(bound, page_height)
            )
            reconciliation = {
                "fragment_id": target.fragment_id,
                "source_ref": target.source_ref,
                "page": target.page,
                "located": actual_box is not None,
                "actual_box": None if actual_box is None else list(actual_box),
                "geometry_holds": geometry_holds,
                "article_bounds_hold": article_holds,
                "protected_bounds_hold": protected_holds,
            }
            record["trace_reconciliation"].append(reconciliation)
            check(
                "target_fragment_bounds",
                geometry_holds and article_holds and protected_holds,
                reconciliation,
                code="target_fragment_out_of_bounds",
                page=target.page,
                reference=target.source_ref,
            )

        for expectation in expected.drop_caps:
            self._check_drop_cap(
                output,
                page_cache,
                expectation,
                record,
                check,
                selection,
            )

    def _check_drop_cap(
        self, output, page_cache, expectation, record, check, page_selection_map
    ) -> None:
        if expectation.page not in page_cache:
            return
        page = output[
            expectation.page - 1
            if page_selection_map is None
            else page_selection_map.require_output_index(expectation.page)
        ]
        text, _mapping, spans = page_cache[expectation.page]
        candidates = []
        for span in spans:
            if normalize_text(span["text"]) == expectation.character:
                candidates.append(span)
        page_height = page.rect.height
        chosen = None
        for candidate in candidates:
            if expectation.box is None or any(
                _box_consistent(
                    tuple(candidate["bbox"]),
                    variant,
                    self.config.drop_cap_bbox_tolerance_pt,
                )
                for variant in _box_variants(expectation.box, page_height)
            ):
                chosen = candidate
                break
        eligible = _eligible(expectation.character, expectation.policy)
        single = chosen is not None and len(normalize_text(chosen["text"])) == 1
        size_holds = chosen is not None
        if size_holds and expectation.font_size is not None:
            size_holds = math.isclose(
                float(chosen["size"]),
                expectation.font_size,
                rel_tol=self.config.drop_cap_font_size_tolerance_ratio,
                abs_tol=0.0,
            )
        body_sizes = [
            float(item["size"])
            for item in spans
            if item is not chosen and item.get("size")
        ]
        if size_holds and body_sizes:
            body_sizes.sort()
            size_holds = (
                float(chosen["size"])
                >= body_sizes[len(body_sizes) // 2]
                * self.config.drop_cap_min_body_size_ratio
            )
        color_holds = chosen is not None
        actual_rgb = None if chosen is None else _rgb(chosen.get("color"))
        if color_holds and expectation.rgb is not None:
            color_holds = actual_rgb is not None and all(
                abs(a - b) <= self.config.drop_cap_color_tolerance
                for a, b in zip(actual_rgb, expectation.rgb, strict=True)
            )
        body_holds = (
            expectation.body_text is None
            or normalize_text(expectation.body_text) in text
        )
        evidence = {
            "source_ref": expectation.source_ref,
            "page": expectation.page,
            "character": expectation.character,
            "eligible": eligible,
            "single_character_span": single,
            "font_size_holds": size_holds,
            "color_holds": color_holds,
            "bbox_holds": chosen is not None,
            "body_searchable": body_holds,
            "actual": chosen,
            "actual_rgb": actual_rgb,
        }
        record["evidence"]["drop_caps"].append(evidence)
        check(
            "drop_cap",
            eligible
            and single
            and size_holds
            and color_holds
            and chosen is not None
            and body_holds,
            evidence,
            code="drop_cap_noncompliant",
            page=expectation.page,
            reference=expectation.source_ref,
        )

    def _finish(self, record: dict, destination: Path) -> ComplianceResult:
        if record["issues"]:
            status = STATUS_FAIL
        elif record["writer_warnings"]:
            status = STATUS_DEGRADED
        else:
            status = STATUS_PASS
        record["status"] = status
        record["fully_compliant"] = status == STATUS_PASS
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record_config_manifest(destination.parent, [CONFIG_PATH])
        return ComplianceResult(status=status, report_path=destination, record=record)


def validate_final_pdf(
    translation_config,
    source_pdf,
    output_pdf,
    *,
    run_trace=None,
    article_document_ir=None,
    fixed_asset_inventory=None,
    writer_warnings=(),
    expected_page_count: int | None = None,
) -> ComplianceResult:
    report_path = translation_config.get_working_file_path(REPORT_NAME)
    expectations = expectations_from_runtime(
        run_trace,
        expected_page_count=expected_page_count,
        article_document_ir=article_document_ir,
        fixed_asset_inventory=fixed_asset_inventory,
    )
    return FinalPdfValidator().validate(
        source_pdf,
        output_pdf,
        report_path,
        expectations=expectations,
        writer_warnings=writer_warnings,
    )
