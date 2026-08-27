"""Fail-closed v4 binding between source PDF, review, and HITL decisions.

The binder and runtime deliberately share every canonical projection in this
module.  A decisions file is useful only together with the source PDF and the
three detached artifacts it names; legacy files remain readable elsewhere but
cannot cross this apply boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN
from decimal import Decimal
from pathlib import Path
from typing import Any
from typing import Final

import tomllib

from babeldoc.magazine.element_roles import ELEMENT_ROLE_SCHEMA_VERSION
from babeldoc.magazine.runtime_profile import resolve_magazine_profile
from babeldoc.magazine.taxonomy import load_taxonomy

FORMAT_VERSION: Final = 4
SOURCE_BINDING_SCHEMA_VERSION: Final = "hitl-source-binding.v1"
SEMANTIC_DIGEST_SCHEMA_VERSION: Final = "hitl-source-semantic.v1"
SEMANTIC_CONFIG_SCHEMA_VERSION: Final = "hitl-semantic-config.v1"
REVIEW_MANIFEST_SCHEMA_VERSION: Final = "hitl-review-manifest.v1"
BINDING_EVIDENCE_SCHEMA_VERSION: Final = "hitl-binding-evidence.v1"
CODE_CONTRACT_VERSION: Final = "hitl-v4-binding.v1"
PARSER_IDENTITY: Final = "pymupdf-source-blocks.v1"
TERM_ELIGIBILITY_RULE_VERSION: Final = "element-role-eligibility.v1"

REVIEW_SUFFIX: Final = ".review.json"
DECISIONS_SUFFIX: Final = ".decisions.json"
REVIEW_MANIFEST_SUFFIX: Final = ".review-manifest.json"
BINDING_REPORT_SUFFIX: Final = ".binding-report.json"
RUNTIME_REVIEW_SUFFIX: Final = ".runtime-review.json"

HITL_SCHEMA_REQUIRES_BINDING: Final = "HITL_SCHEMA_REQUIRES_BINDING"
HITL_SOURCE_PDF_MISMATCH: Final = "HITL_SOURCE_PDF_MISMATCH"
HITL_PAGE_MANIFEST_MISMATCH: Final = "HITL_PAGE_MANIFEST_MISMATCH"
HITL_SEMANTIC_PAGE_STALE: Final = "HITL_SEMANTIC_PAGE_STALE"
HITL_REVIEW_MANIFEST_MISMATCH: Final = "HITL_REVIEW_MANIFEST_MISMATCH"
HITL_DECISION_REF_STALE: Final = "HITL_DECISION_REF_STALE"
HITL_DECISION_AMBIGUOUS: Final = "HITL_DECISION_AMBIGUOUS"
HITL_BINDING_EVIDENCE_MISMATCH: Final = "HITL_BINDING_EVIDENCE_MISMATCH"

_SECTIONS: Final = ("page_kinds", "terms", "drop_caps")
_SEMANTIC_FIELDS: Final = {
    "lang_in": None,
    "skip_scanned_detection": False,
    "ocr_workaround": False,
    "auto_enable_ocr_workaround": False,
    "split_short_lines": False,
    "short_line_split_factor": 0.8,
    "min_text_length": 5,
    "disable_rich_text_translate": False,
    "add_formula_placehold_hint": False,
    "enable_graphic_element_process": True,
    "merge_alternating_line_numbers": True,
    "remove_non_formula_lines": False,
    "non_formula_line_iou_threshold": 0.9,
    "figure_table_protection_threshold": 0.9,
    "skip_formula_offset_calculation": False,
}
_MAGAZINE_SEMANTIC_SWITCHES: Final = (
    "magazine_page_classify",
    "magazine_chain_detect",
    "magazine_article_group",
    "magazine_detect",
    "magazine_drop_cap_mark",
    "magazine_formula_reclass",
    "magazine_fragment_stitch",
    "magazine_line_structure",
    "magazine_rotated_lane",
)
_SEMANTIC_RESOURCES: Final = (
    "article_context.json",
    "article_flow.json",
    "article_grouping.json",
    "chain_detection.json",
    "element_roles.json",
    "formula_reclass.json",
    "line_split.json",
    "page_features.json",
    "page_types.json",
)

ROOT = Path(__file__).resolve().parents[2]


class HitlBindingError(ValueError):
    """A typed refusal at the v4 binding/apply boundary."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def canonical_json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    """Canonical UTF-8 JSON bytes; pretty form is the on-disk representation."""

    options: dict[str, Any] = {
        "allow_nan": False,
        "ensure_ascii": False,
        "sort_keys": True,
    }
    if pretty:
        options["indent"] = 2
        options["separators"] = (",", ": ")
    else:
        options["separators"] = (",", ":")
    return (json.dumps(value, **options) + ("\n" if pretty else "")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HitlBindingError(
                    HITL_BINDING_EVIDENCE_MISMATCH,
                    f"{path.name} repeats field {key!r}",
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite number {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, HitlBindingError):
            raise
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH, f"cannot read {path.name}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH, f"{path.name} must contain an object"
        )
    return value


def _config_value(config: object, name: str, default: Any) -> Any:
    if isinstance(config, Mapping):
        if name in config:
            return config[name]
        dashed = name.replace("_", "-")
        return config.get(dashed, default)
    return getattr(config, name, default)


def _model_identity(config: object) -> dict[str, str]:
    declared = _config_value(config, "doc_layout_model", None)
    if declared is None:
        # The production CLI constructs the built-in ONNX implementation even
        # for parse-only runs.  Binder TOML has no object to inspect, so its
        # default must name that same concrete built-in implementation rather
        # than the abstract loader facade.
        identity = "babeldoc.docvision.doclayout.OnnxModel"
    elif isinstance(declared, str):
        identity = declared
    else:
        explicit = getattr(declared, "hitl_identity", None) or getattr(
            declared, "model_id", None
        )
        identity = str(
            explicit or f"{type(declared).__module__}.{type(declared).__qualname__}"
        )
    return {
        "layout_model": identity,
        "parser": PARSER_IDENTITY,
        "table_model": "retired",
    }


def semantic_config_projection(config: object) -> dict[str, Any]:
    """Shared binder/runtime projection of source-semantic configuration.

    Credentials, provider/model selection, QPS, output/debug paths, overlay
    switches, and selected pages are intentionally absent.
    """

    values = {
        name: _config_value(config, name, default)
        for name, default in _SEMANTIC_FIELDS.items()
    }
    if values["ocr_workaround"]:
        values["skip_scanned_detection"] = True
        values["disable_rich_text_translate"] = True
    if values["auto_enable_ocr_workaround"]:
        values["ocr_workaround"] = False
        values["skip_scanned_detection"] = False

    mode = _config_value(config, "magazine_mode", None)
    profile_switches: Mapping[str, Any] = {}
    if isinstance(config, Mapping) and mode is None:
        mode = "hitl-apply"
    if isinstance(config, Mapping) and mode:
        profile = resolve_magazine_profile(str(mode), None)
        if profile is not None:
            profile_switches = profile.switches
    switches = {
        name: bool(_config_value(config, name, profile_switches.get(name, False)))
        for name in _MAGAZINE_SEMANTIC_SWITCHES
    }
    resources = {
        name: file_sha256(ROOT / "configs" / name) for name in _SEMANTIC_RESOURCES
    }
    return {
        "schema_version": SEMANTIC_CONFIG_SCHEMA_VERSION,
        "source_language": values.pop("lang_in"),
        "parser_layout_model": _model_identity(config),
        "semantic_parameters": values,
        "magazine_semantic_switches": switches,
        "resource_sha256": resources,
        "element_role_schema_version": ELEMENT_ROLE_SCHEMA_VERSION,
    }


def semantic_config_sha256(config: object) -> str:
    return canonical_sha256(semantic_config_projection(config))


def load_toml_semantic_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    section = raw.get("babeldoc")
    if not isinstance(section, dict):
        raise HitlBindingError(
            HITL_SEMANTIC_PAGE_STALE,
            f"{path.name} has no [babeldoc] configuration",
        )
    return section


def _canonical_coordinate(value: object) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise HitlBindingError(
            HITL_PAGE_MANIFEST_MISMATCH, "PDF page coordinates must be finite"
        )
    rounded = Decimal(str(number)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        rounded = Decimal("0")
    return format(rounded, "f")


def _canonical_text(value: object) -> str:
    return (
        unicodedata.normalize("NFC", str(value or ""))
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    source_binding: Mapping[str, Any]
    pages: tuple[Mapping[str, Any], ...]


def source_snapshot(source: Path, config: object) -> SourceSnapshot:
    """Read full source identity and debug-free page semantics offline."""

    try:
        import pymupdf
    except ModuleNotFoundError as exc:  # pragma: no cover - production dependency.
        raise HitlBindingError(
            HITL_SOURCE_PDF_MISMATCH, "PyMuPDF is required for source binding"
        ) from exc
    if not source.is_file():
        raise HitlBindingError(
            HITL_SOURCE_PDF_MISMATCH, f"source PDF is missing: {source.name}"
        )
    config_projection = semantic_config_projection(config)
    config_sha = canonical_sha256(config_projection)
    model_identity = config_projection["parser_layout_model"]
    pages: list[dict[str, Any]] = []
    page_boxes: list[dict[str, Any]] = []
    try:
        document = pymupdf.open(source)
    except Exception as exc:  # noqa: BLE001 - normalize parser failures.
        raise HitlBindingError(
            HITL_SOURCE_PDF_MISMATCH, f"cannot open source PDF: {exc}"
        ) from exc
    try:
        for position, page in enumerate(document):
            physical = position + 1
            media = [_canonical_coordinate(value) for value in page.mediabox]
            crop = [_canonical_coordinate(value) for value in page.cropbox]
            page_boxes.append(
                {
                    "physical_page": physical,
                    "mediabox": media,
                    "cropbox": crop,
                    "rotation": int(page.rotation),
                }
            )
            entries: list[dict[str, Any]] = []
            for reading_order, block in enumerate(page.get_text("blocks", sort=True)):
                block_type = int(block[6]) if len(block) > 6 else 0
                if block_type != 0:
                    continue
                text = _canonical_text(block[4])
                if not text:
                    continue
                block_number = int(block[5]) if len(block) > 5 else reading_order
                entries.append(
                    {
                        "physical_page": physical,
                        "stable_source_ref": f"p{physical}#pdf-block-{block_number}",
                        "role": "BODY",
                        "normalized_source_text": text,
                        "reading_order": reading_order,
                        "box": [_canonical_coordinate(value) for value in block[:4]],
                    }
                )
            page_projection = {
                "schema_version": SEMANTIC_DIGEST_SCHEMA_VERSION,
                "physical_page": physical,
                "parser_layout_model": model_identity,
                "semantic_config_sha256": config_sha,
                "entries": entries,
            }
            pages.append(
                {
                    "physical_page": physical,
                    "entries": entries,
                    "semantic_sha256": canonical_sha256(page_projection),
                }
            )
    finally:
        document.close()
    page_hashes = {
        str(page["physical_page"]): page["semantic_sha256"] for page in pages
    }
    binding = {
        "schema_version": SOURCE_BINDING_SCHEMA_VERSION,
        "source_pdf_sha256": file_sha256(source),
        "source_page_count": len(pages),
        "page_box_rotation_manifest_sha256": canonical_sha256(page_boxes),
        "semantic_digest_schema_version": SEMANTIC_DIGEST_SCHEMA_VERSION,
        "per_physical_page_semantic_sha256": page_hashes,
        "document_semantic_sha256": canonical_sha256(
            [[int(page), page_hashes[page]] for page in sorted(page_hashes, key=int)]
        ),
        "parser_layout_model": model_identity,
        "semantic_config_schema_version": SEMANTIC_CONFIG_SCHEMA_VERSION,
        "semantic_config_sha256": config_sha,
        "code_contract_version": CODE_CONTRACT_VERSION,
    }
    return SourceSnapshot(source_binding=binding, pages=tuple(pages))


def source_binding_sha256(source_binding: Mapping[str, Any]) -> str:
    return canonical_sha256(dict(source_binding))


def _term_occurrences(
    source: str, pages: tuple[Mapping[str, Any], ...]
) -> list[dict[str, Any]]:
    needle = unicodedata.normalize("NFC", source)
    found: list[dict[str, Any]] = []
    for page in pages:
        for entry in page["entries"]:
            text = entry["normalized_source_text"]
            start = 0
            while True:
                position = text.find(needle, start)
                if position < 0:
                    break
                end = position + len(needle)
                occurrence = {
                    "source_ref": (
                        f"{entry['stable_source_ref']}:span:{position}-{end}"
                    ),
                    "physical_page": page["physical_page"],
                    "stable_source_ref": entry["stable_source_ref"],
                    "source_span": [position, end],
                    "role": entry["role"],
                    "translation_eligibility": "eligible",
                    "eligibility_rule_id": (
                        f"{TERM_ELIGIBILITY_RULE_VERSION}:{entry['role']}"
                    ),
                }
                occurrence["fingerprint"] = canonical_sha256(occurrence)
                found.append(occurrence)
                start = end
    return found


def _review_sources(review: Mapping[str, Any]) -> tuple[str, ...]:
    sources: list[str] = []
    for row in review.get("terms") or ():
        if isinstance(row, Mapping) and isinstance(row.get("source"), str):
            sources.append(row["source"])
    return tuple(dict.fromkeys(sources))


def review_candidate_projection(review: Mapping[str, Any]) -> dict[str, Any]:
    return {name: review.get(name) or [] for name in _SECTIONS}


def candidate_manifest_sha256(review: Mapping[str, Any]) -> str:
    return canonical_sha256(review_candidate_projection(review))


def runtime_review_envelope(
    draft: Mapping[str, Any], *, source: Path, config: object
) -> dict[str, Any]:
    """Bind a machine-only runtime draft to current source candidates."""

    snapshot = source_snapshot(source, config)
    page_semantics = {
        int(page["physical_page"]): page["semantic_sha256"] for page in snapshot.pages
    }
    page_rows: list[dict[str, Any]] = []
    for original in draft.get("page_kinds") or ():
        row = dict(original)
        page = int(row["page"])
        row["stable_ref"] = f"physical-page:{page}"
        row["page_semantic_sha256"] = page_semantics.get(page)
        row["fingerprint"] = canonical_sha256(
            {
                "page": page,
                "stable_ref": row["stable_ref"],
                "page_semantic_sha256": row["page_semantic_sha256"],
                "machine_kind": row.get("machine_kind"),
            }
        )
        page_rows.append(row)
    term_rows: list[dict[str, Any]] = []
    for original in draft.get("terms") or ():
        row = dict(original)
        source_term = str(row["source"])
        row["stable_ref"] = f"term:{canonical_sha256(source_term)}"
        row["occurrences"] = _term_occurrences(source_term, snapshot.pages)
        row["normalization_version"] = "unicode-nfc-exact.v1"
        row["fingerprint"] = canonical_sha256(
            {
                "source": source_term,
                "stable_ref": row["stable_ref"],
                "occurrences": row["occurrences"],
                "normalization_version": row["normalization_version"],
            }
        )
        term_rows.append(row)
    drop_rows: list[dict[str, Any]] = []
    for original in draft.get("drop_caps") or ():
        row = dict(original)
        reference = str(row.get("paragraph") or row.get("reference") or "")
        row["reference"] = reference
        row["stable_ref"] = reference
        try:
            row["physical_page"] = int(reference.split("#", 1)[0].removeprefix("p"))
        except ValueError:
            row["physical_page"] = None
        row["fingerprint"] = canonical_sha256(
            {
                "reference": reference,
                "stable_ref": reference,
                "physical_page": row["physical_page"],
                "candidate_fingerprint": row.get("candidate_fingerprint"),
                "source_text_fingerprint": row.get("source_text_fingerprint"),
                "source_style_fingerprint": row.get("source_style_fingerprint"),
                "config_fingerprint": row.get("config_fingerprint"),
            }
        )
        drop_rows.append(row)
    envelope = {
        "format_version": FORMAT_VERSION,
        "sample": draft["sample"],
        "binding_summary": {
            "source_pdf_sha256": snapshot.source_binding["source_pdf_sha256"],
            "source_page_count": snapshot.source_binding["source_page_count"],
            "semantic_schema_version": SEMANTIC_DIGEST_SCHEMA_VERSION,
        },
        "page_kinds": page_rows,
        "terms": term_rows,
        "drop_caps": drop_rows,
    }
    envelope["candidate_manifest_sha256"] = candidate_manifest_sha256(envelope)
    return envelope


def _legacy_version(record: Mapping[str, Any], *, label: str) -> int:
    version = record.get("format_version")
    if version not in (2, 3):
        raise HitlBindingError(
            HITL_SCHEMA_REQUIRES_BINDING,
            f"{label} must be legacy format_version 2 or 3",
        )
    return int(version)


def _legacy_sections(record: Mapping[str, Any], *, label: str) -> None:
    allowed = {"format_version", "sample", *_SECTIONS}
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise HitlBindingError(
            HITL_DECISION_AMBIGUOUS,
            f"{label} contains unknown fields: {', '.join(unknown)}",
        )


def _mapping_section(record: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = record.get(name)
    if value is None or value == []:
        return {}
    if not isinstance(value, dict):
        raise HitlBindingError(
            HITL_DECISION_AMBIGUOUS, f"legacy {name} must be an object"
        )
    return dict(value)


def _legacy_review_pages(review: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for row in review.get("page_kinds") or ():
        if not isinstance(row, Mapping) or not isinstance(row.get("page"), int):
            continue
        page = int(row["page"])
        if page in result:
            raise HitlBindingError(
                HITL_DECISION_AMBIGUOUS,
                f"legacy review repeats page candidate {page}",
            )
        result[page] = row
    return result


def rebuild_review(
    sample: str,
    snapshot: SourceSnapshot,
    legacy_review: Mapping[str, Any],
    legacy_decisions: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Rebuild v4 candidates from current source and explicit legacy values."""

    page_defaults = _legacy_review_pages(legacy_review)
    human_pages = _mapping_section(legacy_decisions, "page_kinds")
    human_terms = _mapping_section(legacy_decisions, "terms")
    human_drop_caps = _mapping_section(legacy_decisions, "drop_caps")
    taxonomy_names = set(load_taxonomy().names())
    page_rows: list[dict[str, Any]] = []
    for page in snapshot.pages:
        number = int(page["physical_page"])
        legacy_default = page_defaults.get(number, {}).get("machine_kind")
        candidate = {
            "page": number,
            "stable_ref": f"physical-page:{number}",
            "page_semantic_sha256": page["semantic_sha256"],
            "machine_kind": None,
            "legacy_observed_machine_kind": legacy_default,
            "candidate_source": "source_rebind_unclassified",
        }
        candidate["fingerprint"] = canonical_sha256(candidate)
        page_rows.append(candidate)

    term_sources = tuple(
        dict.fromkeys([*_review_sources(legacy_review), *human_terms.keys()])
    )
    term_rows: list[dict[str, Any]] = []
    for source in term_sources:
        if not isinstance(source, str) or not source.strip():
            raise HitlBindingError(
                HITL_DECISION_AMBIGUOUS, "legacy term source must be non-empty"
            )
        occurrences = _term_occurrences(source, snapshot.pages)
        if source in human_terms and not occurrences:
            raise HitlBindingError(
                HITL_DECISION_REF_STALE,
                f"legacy term {source!r} has no source occurrence",
            )
        candidate = {
            "source": source,
            "stable_ref": f"term:{canonical_sha256(source)}",
            "occurrences": occurrences,
            "normalization_version": "unicode-nfc-exact.v1",
        }
        candidate["fingerprint"] = canonical_sha256(candidate)
        term_rows.append(candidate)

    drop_rows: list[dict[str, Any]] = []
    seen_drop: set[str] = set()
    for row in legacy_review.get("drop_caps") or ():
        if not isinstance(row, Mapping):
            continue
        reference = row.get("paragraph") or row.get("reference")
        if not isinstance(reference, str) or not reference:
            continue
        if reference in seen_drop:
            raise HitlBindingError(
                HITL_DECISION_AMBIGUOUS,
                f"legacy review repeats drop-cap {reference}",
            )
        seen_drop.add(reference)
        try:
            page = int(str(reference).split("#", 1)[0].removeprefix("p"))
        except ValueError as exc:
            raise HitlBindingError(
                HITL_DECISION_REF_STALE,
                f"drop-cap reference {reference!r} has no physical page",
            ) from exc
        candidate = {
            "reference": reference,
            "stable_ref": reference,
            "physical_page": page,
            "source_candidate": {
                key: value
                for key, value in row.items()
                if key
                in {
                    "candidate_fingerprint",
                    "source_text_fingerprint",
                    "source_style_fingerprint",
                    "config_fingerprint",
                }
            },
        }
        candidate["fingerprint"] = canonical_sha256(candidate)
        drop_rows.append(candidate)
    missing_drop = sorted(set(human_drop_caps) - seen_drop)
    if missing_drop:
        raise HitlBindingError(
            HITL_DECISION_REF_STALE,
            f"legacy drop-cap decisions have no unique candidate: {missing_drop}",
        )

    page_by_number = {int(row["page"]): row for row in page_rows}
    term_by_source = {str(row["source"]): row for row in term_rows}
    drop_by_ref = {str(row["reference"]): row for row in drop_rows}
    decision_refs = {name: {} for name in _SECTIONS}
    outcomes: list[dict[str, Any]] = []
    for raw_page, kind in human_pages.items():
        try:
            page = int(raw_page)
        except (TypeError, ValueError) as exc:
            raise HitlBindingError(
                HITL_DECISION_REF_STALE, f"invalid page decision {raw_page!r}"
            ) from exc
        if str(page) != str(raw_page) or page not in page_by_number:
            raise HitlBindingError(
                HITL_DECISION_REF_STALE, f"page decision {raw_page!r} is stale"
            )
        if kind not in taxonomy_names:
            raise HitlBindingError(
                HITL_DECISION_REF_STALE,
                f"page kind {kind!r} is not in the current taxonomy",
            )
        candidate = page_by_number[page]
        decision_refs["page_kinds"][str(page)] = {
            "stable_ref": candidate["stable_ref"],
            "fingerprint": candidate["fingerprint"],
        }
        outcomes.append(
            {
                "section": "page_kinds",
                "decision": str(page),
                "result": (
                    "exact"
                    if candidate["legacy_observed_machine_kind"] == kind
                    else "changed_default"
                ),
            }
        )
    for source, target in human_terms.items():
        if not isinstance(target, str) or not target.strip():
            raise HitlBindingError(
                HITL_DECISION_AMBIGUOUS,
                f"term {source!r} target must be a non-empty string",
            )
        candidate = term_by_source[source]
        decision_refs["terms"][source] = {
            "stable_ref": candidate["stable_ref"],
            "fingerprint": candidate["fingerprint"],
            "occurrence_refs": [
                item["source_ref"] for item in candidate["occurrences"]
            ],
        }
        outcomes.append({"section": "terms", "decision": source, "result": "exact"})
    for reference in human_drop_caps:
        candidate = drop_by_ref[reference]
        decision_refs["drop_caps"][reference] = {
            "stable_ref": candidate["stable_ref"],
            "fingerprint": candidate["fingerprint"],
        }
        outcomes.append(
            {"section": "drop_caps", "decision": reference, "result": "exact"}
        )
    review = {
        "format_version": FORMAT_VERSION,
        "sample": sample,
        "binding_summary": {
            "source_pdf_sha256": snapshot.source_binding["source_pdf_sha256"],
            "source_page_count": snapshot.source_binding["source_page_count"],
            "semantic_schema_version": SEMANTIC_DIGEST_SCHEMA_VERSION,
        },
        "page_kinds": page_rows,
        "terms": term_rows,
        "drop_caps": drop_rows,
    }
    review["candidate_manifest_sha256"] = candidate_manifest_sha256(review)
    return review, decision_refs, outcomes


def _decision_material(decisions: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "page_kinds": decisions["page_kinds"],
        "terms": decisions["terms"],
        "drop_caps": decisions["drop_caps"],
        "decision_refs": decisions["decision_refs"],
    }


def _lineage_for_evidence(lineage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in lineage.items() if key != "binding_evidence_sha256"
    }


def binding_evidence_payload(
    *,
    source_binding: Mapping[str, Any],
    review_manifest_sha256: str,
    lineage: Mapping[str, Any],
    decisions: Mapping[str, Any],
    binding_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": BINDING_EVIDENCE_SCHEMA_VERSION,
        "code_contract_version": CODE_CONTRACT_VERSION,
        "source_binding_sha256": source_binding_sha256(source_binding),
        "semantic_config_sha256": source_binding["semantic_config_sha256"],
        "review_manifest_sha256": review_manifest_sha256,
        "lineage": _lineage_for_evidence(lineage),
        "decision_material_sha256": canonical_sha256(_decision_material(decisions)),
        "binding_results": binding_results,
    }


def _atomic_output_set(output_dir: Path, records: Mapping[str, dict[str, Any]]) -> None:
    temporary: list[tuple[Path, Path]] = []
    try:
        for name, record in records.items():
            target = output_dir / name
            temp = output_dir / f".{name}.{os.getpid()}.tmp"
            with temp.open("xb") as stream:
                stream.write(canonical_json_bytes(record, pretty=True))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.append((temp, target))
        for temp, target in temporary:
            temp.replace(target)
    finally:
        for temp, _target in temporary:
            temp.unlink(missing_ok=True)


def bind_legacy_files(
    *,
    source: Path,
    config_path: Path,
    review_path: Path,
    decisions_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Migrate explicit legacy values into a complete source-bound v4 set."""

    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise HitlBindingError(
            HITL_DECISION_AMBIGUOUS,
            "binding output directory must not exist or must be empty",
        )
    legacy_review = _strict_json(review_path)
    legacy_decisions = _strict_json(decisions_path)
    review_version = _legacy_version(legacy_review, label="review")
    decision_version = _legacy_version(legacy_decisions, label="decisions")
    _legacy_sections(legacy_review, label="review")
    _legacy_sections(legacy_decisions, label="decisions")
    sample = legacy_decisions.get("sample")
    if not isinstance(sample, str) or not sample:
        raise HitlBindingError(
            HITL_DECISION_AMBIGUOUS, "legacy decisions must name a sample"
        )
    if legacy_review.get("sample") != sample:
        raise HitlBindingError(
            HITL_DECISION_AMBIGUOUS, "legacy review and decisions samples differ"
        )
    config = load_toml_semantic_config(config_path)
    snapshot = source_snapshot(source, config)
    review, decision_refs, outcomes = rebuild_review(
        sample, snapshot, legacy_review, legacy_decisions
    )
    review_bytes = canonical_json_bytes(review, pretty=True)
    review_manifest = {
        "schema_version": REVIEW_MANIFEST_SCHEMA_VERSION,
        "sample": sample,
        "review_file_sha256": hashlib.sha256(review_bytes).hexdigest(),
        "candidate_manifest_sha256": review["candidate_manifest_sha256"],
        "source_binding_sha256": source_binding_sha256(snapshot.source_binding),
    }
    review_manifest_sha = canonical_sha256(review_manifest)
    lineage: dict[str, Any] = {
        "binding_mode": "legacy_explicit_rebind",
        "legacy_review": {
            "format_version": review_version,
            "sha256": file_sha256(review_path),
        },
        "legacy_decisions": {
            "format_version": decision_version,
            "sha256": file_sha256(decisions_path),
        },
        "legacy_review_cycle_unverified": True,
        "rebuilt_review_manifest_sha256": review_manifest_sha,
        "binding_evidence_schema_version": BINDING_EVIDENCE_SCHEMA_VERSION,
    }
    decisions: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "sample": sample,
        "source_binding": dict(snapshot.source_binding),
        "review_manifest_sha256": review_manifest_sha,
        "lineage": lineage,
        "page_kinds": _mapping_section(legacy_decisions, "page_kinds"),
        "terms": _mapping_section(legacy_decisions, "terms"),
        "drop_caps": _mapping_section(legacy_decisions, "drop_caps"),
        "decision_refs": decision_refs,
        "binding_results": outcomes,
    }
    evidence = binding_evidence_payload(
        source_binding=snapshot.source_binding,
        review_manifest_sha256=review_manifest_sha,
        lineage=lineage,
        decisions=decisions,
        binding_results=outcomes,
    )
    evidence_sha = canonical_sha256(evidence)
    lineage["binding_evidence_sha256"] = evidence_sha
    decisions["binding_evidence"] = evidence
    report = {
        "schema_version": BINDING_EVIDENCE_SCHEMA_VERSION,
        "status": "bound",
        "sample": sample,
        "binding_mode": "legacy_explicit_rebind",
        "legacy_review_cycle_unverified": True,
        "binding_evidence": evidence,
        "binding_evidence_sha256": evidence_sha,
        "outputs": {
            "review": f"{sample}{REVIEW_SUFFIX}",
            "decisions": f"{sample}{DECISIONS_SUFFIX}",
            "review_manifest": f"{sample}{REVIEW_MANIFEST_SUFFIX}",
            "binding_report": f"{sample}{BINDING_REPORT_SUFFIX}",
        },
    }
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        output_dir.chmod(0o700)
    except OSError:
        pass
    names = report["outputs"]
    _atomic_output_set(
        output_dir,
        {
            names["review"]: review,
            names["decisions"]: decisions,
            names["review_manifest"]: review_manifest,
            names["binding_report"]: report,
        },
    )
    return report


@dataclass(frozen=True, slots=True)
class BoundDecisionProjection:
    """Validated selected-page projection and immutable artifact snapshot."""

    path: Path
    terms: Mapping[str, str]
    page_kinds: Mapping[int, str]
    drop_caps: Mapping[str, Any]
    projection_report: tuple[Mapping[str, Any], ...]
    decisions: Mapping[str, Any]
    review: Mapping[str, Any]
    artifact_sha256: Mapping[Path, str]
    selected_pages: tuple[int, ...]


def artifact_paths(decisions_path: Path, sample: str) -> dict[str, Path]:
    directory = decisions_path.parent
    return {
        "review": directory / f"{sample}{REVIEW_SUFFIX}",
        "decisions": decisions_path,
        "review_manifest": directory / f"{sample}{REVIEW_MANIFEST_SUFFIX}",
        "binding_report": directory / f"{sample}{BINDING_REPORT_SUFFIX}",
    }


def _require_keys(
    record: Mapping[str, Any], expected: set[str], *, label: str, code: str
) -> None:
    missing = sorted(expected - set(record))
    unknown = sorted(set(record) - expected)
    if missing or unknown:
        raise HitlBindingError(
            code,
            f"{label} fields differ (missing={missing}, unknown={unknown})",
        )


def _selected_pages(config: object, page_count: int) -> tuple[int, ...]:
    selector = getattr(config, "should_translate_page", None)
    if selector is None:
        return tuple(range(1, page_count + 1))
    return tuple(page for page in range(1, page_count + 1) if selector(page))


def _review_indexes(review: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    indexes: dict[str, dict[str, Any]] = {
        "page_kinds": {},
        "terms": {},
        "drop_caps": {},
    }
    for row in review["page_kinds"]:
        key = str(row["page"])
        if key in indexes["page_kinds"]:
            raise HitlBindingError(
                HITL_DECISION_AMBIGUOUS, f"review repeats page {key}"
            )
        indexes["page_kinds"][key] = row
    for row in review["terms"]:
        key = str(row["source"])
        if key in indexes["terms"]:
            raise HitlBindingError(
                HITL_DECISION_AMBIGUOUS, f"review repeats term {key!r}"
            )
        indexes["terms"][key] = row
    for row in review["drop_caps"]:
        key = str(row["reference"])
        if key in indexes["drop_caps"]:
            raise HitlBindingError(
                HITL_DECISION_AMBIGUOUS, f"review repeats drop-cap {key!r}"
            )
        indexes["drop_caps"][key] = row
    return indexes


def _verify_decision_ref(
    *,
    section: str,
    key: str,
    references: Mapping[str, Any],
    candidates: Mapping[str, Any],
) -> Mapping[str, Any]:
    reference = references.get(key)
    candidate = candidates.get(key)
    if not isinstance(reference, Mapping) or not isinstance(candidate, Mapping):
        raise HitlBindingError(
            HITL_DECISION_REF_STALE, f"{section} decision {key!r} has no candidate"
        )
    if reference.get("stable_ref") != candidate.get("stable_ref") or reference.get(
        "fingerprint"
    ) != candidate.get("fingerprint"):
        raise HitlBindingError(
            HITL_DECISION_REF_STALE, f"{section} decision {key!r} is stale"
        )
    return candidate


def _validate_envelope_set(
    decisions_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Path],
]:
    decisions = _strict_json(decisions_path)
    if decisions.get("format_version") != FORMAT_VERSION:
        raise HitlBindingError(
            HITL_SCHEMA_REQUIRES_BINDING,
            "hitl-apply accepts only format_version 4 decisions",
        )
    expected = {
        "format_version",
        "sample",
        "source_binding",
        "review_manifest_sha256",
        "lineage",
        "page_kinds",
        "terms",
        "drop_caps",
        "decision_refs",
        "binding_results",
        "binding_evidence",
    }
    _require_keys(
        decisions,
        expected,
        label="decisions",
        code=HITL_BINDING_EVIDENCE_MISMATCH,
    )
    sample = decisions["sample"]
    if not isinstance(sample, str) or decisions_path.name != (
        f"{sample}{DECISIONS_SUFFIX}"
    ):
        raise HitlBindingError(
            HITL_SCHEMA_REQUIRES_BINDING,
            "decisions must use the standard <sample>.decisions.json name",
        )
    paths = artifact_paths(decisions_path, sample)
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH,
            f"bound artifact set is incomplete: {missing}",
        )
    review = _strict_json(paths["review"])
    manifest = _strict_json(paths["review_manifest"])
    report = _strict_json(paths["binding_report"])
    return decisions, review, manifest, report, paths


def load_bound_decisions(
    decisions_path: Path,
    *,
    source: Path,
    config: object,
) -> BoundDecisionProjection:
    """Validate the complete v4 set, then project decisions to selected pages."""

    decisions, review, manifest, report, paths = _validate_envelope_set(decisions_path)
    _require_keys(
        review,
        {
            "format_version",
            "sample",
            "binding_summary",
            "page_kinds",
            "terms",
            "drop_caps",
            "candidate_manifest_sha256",
        },
        label="review",
        code=HITL_REVIEW_MANIFEST_MISMATCH,
    )
    if review["format_version"] != FORMAT_VERSION:
        raise HitlBindingError(
            HITL_REVIEW_MANIFEST_MISMATCH, "bound review is not format_version 4"
        )
    if candidate_manifest_sha256(review) != review["candidate_manifest_sha256"]:
        raise HitlBindingError(
            HITL_REVIEW_MANIFEST_MISMATCH, "review candidate manifest changed"
        )
    _require_keys(
        manifest,
        {
            "schema_version",
            "sample",
            "review_file_sha256",
            "candidate_manifest_sha256",
            "source_binding_sha256",
        },
        label="review manifest",
        code=HITL_REVIEW_MANIFEST_MISMATCH,
    )
    if (
        manifest["schema_version"] != REVIEW_MANIFEST_SCHEMA_VERSION
        or manifest["review_file_sha256"] != file_sha256(paths["review"])
        or manifest["candidate_manifest_sha256"] != review["candidate_manifest_sha256"]
        or canonical_sha256(manifest) != decisions["review_manifest_sha256"]
    ):
        raise HitlBindingError(
            HITL_REVIEW_MANIFEST_MISMATCH, "review manifest does not bind review"
        )
    lineage = decisions["lineage"]
    if not isinstance(lineage, Mapping):
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH, "lineage must be an object"
        )
    _require_keys(
        lineage,
        {
            "binding_mode",
            "legacy_review",
            "legacy_decisions",
            "legacy_review_cycle_unverified",
            "rebuilt_review_manifest_sha256",
            "binding_evidence_schema_version",
            "binding_evidence_sha256",
        },
        label="lineage",
        code=HITL_BINDING_EVIDENCE_MISMATCH,
    )
    mode = lineage.get("binding_mode")
    if mode not in {"native_v4", "legacy_explicit_rebind"}:
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH, f"unknown binding mode {mode!r}"
        )
    if mode == "legacy_explicit_rebind" and (
        lineage["legacy_review_cycle_unverified"] is not True
        or not lineage["legacy_review"]
        or not lineage["legacy_decisions"]
    ):
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH,
            "legacy lineage cannot be washed into a native binding",
        )
    if mode == "native_v4" and (
        lineage["legacy_review_cycle_unverified"] is not False
        or lineage["legacy_review"] is not None
        or lineage["legacy_decisions"] is not None
    ):
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH,
            "native v4 lineage cannot claim legacy inputs",
        )
    if (
        lineage["rebuilt_review_manifest_sha256"] != decisions["review_manifest_sha256"]
        or lineage["binding_evidence_schema_version"] != BINDING_EVIDENCE_SCHEMA_VERSION
    ):
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH, "lineage schema or review digest changed"
        )
    expected_evidence = binding_evidence_payload(
        source_binding=decisions["source_binding"],
        review_manifest_sha256=decisions["review_manifest_sha256"],
        lineage=lineage,
        decisions=decisions,
        binding_results=decisions["binding_results"],
    )
    evidence_sha = canonical_sha256(expected_evidence)
    if (
        decisions["binding_evidence"] != expected_evidence
        or lineage.get("binding_evidence_sha256") != evidence_sha
        or report.get("binding_evidence") != expected_evidence
        or report.get("binding_evidence_sha256") != evidence_sha
    ):
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH,
            "decisions and detached binding evidence disagree",
        )

    expected_binding = decisions["source_binding"]
    if not isinstance(expected_binding, Mapping):
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH, "source_binding must be an object"
        )
    _require_keys(
        expected_binding,
        {
            "schema_version",
            "source_pdf_sha256",
            "source_page_count",
            "page_box_rotation_manifest_sha256",
            "semantic_digest_schema_version",
            "per_physical_page_semantic_sha256",
            "document_semantic_sha256",
            "parser_layout_model",
            "semantic_config_schema_version",
            "semantic_config_sha256",
            "code_contract_version",
        },
        label="source binding",
        code=HITL_BINDING_EVIDENCE_MISMATCH,
    )
    for section in _SECTIONS:
        if not isinstance(decisions[section], Mapping):
            raise HitlBindingError(
                HITL_DECISION_AMBIGUOUS,
                f"decisions.{section} must be an object",
            )
    if not isinstance(decisions["decision_refs"], Mapping):
        raise HitlBindingError(
            HITL_DECISION_REF_STALE, "decision_refs must be an object"
        )
    summary = review["binding_summary"]
    if not isinstance(summary, Mapping) or summary != {
        "source_pdf_sha256": expected_binding["source_pdf_sha256"],
        "source_page_count": expected_binding["source_page_count"],
        "semantic_schema_version": expected_binding["semantic_digest_schema_version"],
    }:
        raise HitlBindingError(
            HITL_REVIEW_MANIFEST_MISMATCH,
            "review binding summary disagrees with source binding",
        )
    snapshot = source_snapshot(source, config)
    actual_binding = snapshot.source_binding
    if actual_binding["source_page_count"] != expected_binding.get("source_page_count"):
        raise HitlBindingError(
            HITL_SOURCE_PDF_MISMATCH, "full source page count changed"
        )
    if actual_binding["page_box_rotation_manifest_sha256"] != expected_binding.get(
        "page_box_rotation_manifest_sha256"
    ):
        raise HitlBindingError(
            HITL_PAGE_MANIFEST_MISMATCH, "page boxes or rotation changed"
        )
    if source_binding_sha256(expected_binding) != manifest["source_binding_sha256"]:
        raise HitlBindingError(
            HITL_REVIEW_MANIFEST_MISMATCH, "source binding digest changed"
        )
    selected = _selected_pages(config, int(expected_binding["source_page_count"]))
    if actual_binding["semantic_config_sha256"] != expected_binding.get(
        "semantic_config_sha256"
    ):
        raise HitlBindingError(
            HITL_SEMANTIC_PAGE_STALE, "source-semantic configuration changed"
        )
    expected_pages = expected_binding["per_physical_page_semantic_sha256"]
    actual_pages = actual_binding["per_physical_page_semantic_sha256"]
    for page in selected:
        if actual_pages.get(str(page)) != expected_pages.get(str(page)):
            raise HitlBindingError(
                HITL_SEMANTIC_PAGE_STALE, f"physical page {page} semantics changed"
            )
    if actual_binding["source_pdf_sha256"] != expected_binding.get("source_pdf_sha256"):
        raise HitlBindingError(
            HITL_SOURCE_PDF_MISMATCH,
            "source PDF bytes changed outside the selected semantic projection",
        )

    indexes = _review_indexes(review)
    references = decisions["decision_refs"]
    for section in _SECTIONS:
        if not isinstance(references.get(section), Mapping):
            raise HitlBindingError(
                HITL_DECISION_REF_STALE, f"decision_refs.{section} is missing"
            )
    selected_set = set(selected)
    projected_pages: dict[int, str] = {}
    projected_terms: dict[str, str] = {}
    projected_drop: dict[str, Any] = {}
    projection: list[dict[str, Any]] = []
    for raw_page, kind in decisions["page_kinds"].items():
        page = int(raw_page)
        if page not in selected_set:
            projection.append(
                {
                    "section": "page_kinds",
                    "decision": str(page),
                    "status": "not_selected",
                }
            )
            continue
        _verify_decision_ref(
            section="page_kinds",
            key=str(page),
            references=references["page_kinds"],
            candidates=indexes["page_kinds"],
        )
        projected_pages[page] = str(kind)
        projection.append(
            {"section": "page_kinds", "decision": str(page), "status": "selected"}
        )
    for source_term, target in decisions["terms"].items():
        candidate = indexes["terms"].get(source_term)
        occurrences = candidate.get("occurrences", ()) if candidate else ()
        selected_occurrences = [
            item for item in occurrences if int(item["physical_page"]) in selected_set
        ]
        if not selected_occurrences:
            projection.append(
                {
                    "section": "terms",
                    "decision": source_term,
                    "status": "not_selected",
                    "full_occurrence_count": len(occurrences),
                    "selected_occurrence_refs": [],
                }
            )
            continue
        verified = _verify_decision_ref(
            section="terms",
            key=source_term,
            references=references["terms"],
            candidates=indexes["terms"],
        )
        occurrence_refs = [item["source_ref"] for item in verified["occurrences"]]
        if references["terms"][source_term].get("occurrence_refs") != occurrence_refs:
            raise HitlBindingError(
                HITL_DECISION_REF_STALE,
                f"term decision {source_term!r} occurrence set changed",
            )
        projected_terms[source_term] = str(target)
        projection.append(
            {
                "section": "terms",
                "decision": source_term,
                "status": "selected",
                "full_occurrence_count": len(occurrences),
                "selected_occurrence_refs": [
                    item["source_ref"] for item in selected_occurrences
                ],
            }
        )
    for reference, verdict in decisions["drop_caps"].items():
        candidate = indexes["drop_caps"].get(reference)
        page = int(candidate["physical_page"]) if candidate else -1
        if page not in selected_set:
            projection.append(
                {
                    "section": "drop_caps",
                    "decision": reference,
                    "status": "not_selected",
                }
            )
            continue
        _verify_decision_ref(
            section="drop_caps",
            key=reference,
            references=references["drop_caps"],
            candidates=indexes["drop_caps"],
        )
        projected_drop[reference] = verdict
        projection.append(
            {"section": "drop_caps", "decision": reference, "status": "selected"}
        )
    snapshots = {path: file_sha256(path) for path in paths.values()}
    return BoundDecisionProjection(
        path=decisions_path,
        terms=projected_terms,
        page_kinds=projected_pages,
        drop_caps=projected_drop,
        projection_report=tuple(projection),
        decisions=decisions,
        review=review,
        artifact_sha256=snapshots,
        selected_pages=selected,
    )


def verify_bound_artifacts(
    bound: BoundDecisionProjection, *, source: Path, config: object
) -> None:
    """Recheck immutable bytes and the binding at a later execution point."""

    changed = [
        path.name
        for path, expected in bound.artifact_sha256.items()
        if not path.is_file() or file_sha256(path) != expected
    ]
    if changed:
        raise HitlBindingError(
            HITL_BINDING_EVIDENCE_MISMATCH,
            f"bound artifacts changed during apply: {changed}",
        )
    load_bound_decisions(bound.path, source=source, config=config)


__all__ = [
    "BINDING_EVIDENCE_SCHEMA_VERSION",
    "BINDING_REPORT_SUFFIX",
    "CODE_CONTRACT_VERSION",
    "DECISIONS_SUFFIX",
    "FORMAT_VERSION",
    "HITL_BINDING_EVIDENCE_MISMATCH",
    "HITL_DECISION_AMBIGUOUS",
    "HITL_DECISION_REF_STALE",
    "HITL_PAGE_MANIFEST_MISMATCH",
    "HITL_REVIEW_MANIFEST_MISMATCH",
    "HITL_SCHEMA_REQUIRES_BINDING",
    "HITL_SEMANTIC_PAGE_STALE",
    "HITL_SOURCE_PDF_MISMATCH",
    "HitlBindingError",
    "REVIEW_MANIFEST_SCHEMA_VERSION",
    "REVIEW_MANIFEST_SUFFIX",
    "REVIEW_SUFFIX",
    "RUNTIME_REVIEW_SUFFIX",
    "SEMANTIC_CONFIG_SCHEMA_VERSION",
    "SEMANTIC_DIGEST_SCHEMA_VERSION",
    "SOURCE_BINDING_SCHEMA_VERSION",
    "SourceSnapshot",
    "artifact_paths",
    "bind_legacy_files",
    "candidate_manifest_sha256",
    "canonical_json_bytes",
    "canonical_sha256",
    "file_sha256",
    "load_bound_decisions",
    "load_toml_semantic_config",
    "rebuild_review",
    "review_candidate_projection",
    "runtime_review_envelope",
    "semantic_config_projection",
    "semantic_config_sha256",
    "source_binding_sha256",
    "source_snapshot",
    "verify_bound_artifacts",
]
