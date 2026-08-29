"""Minimal, sample-independent source-to-target coverage evidence.

The inventory is frozen after structural processing, while source paragraphs
still carry their original text and geometry.  Translation outcomes are joined
later from the two existing producer reports; this module does not influence
which paragraphs are translated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import line_split

REPORT_NAME = "demo_coverage.report.json"
SCHEMA_VERSION = "demo-coverage.v1"
_PRESERVE_ROLES = frozenset({"brand", "credit", "folio"})


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _box(box) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    values = tuple(float(getattr(box, name)) for name in ("x", "y", "x2", "y2"))
    if values[0] > values[2] or values[1] > values[3]:
        raise ValueError("coverage source box is not ordered")
    return values


def _role(paragraph, unit, article_role: str | None) -> str:
    label = str(getattr(paragraph, "layout_label", "") or "").strip().lower()
    if label in _PRESERVE_ROLES:
        return label
    if unit is not None:
        return unit.record_kind
    if article_role:
        return article_role
    if label in {"plain text", "paragraph", "paragraph_hybrid", "text"}:
        return "body"
    return label or "body"


@dataclass(frozen=True, slots=True)
class FrozenCoverageItem:
    runtime_source_ref: str
    source_ref: str
    physical_page: int
    role: str
    source_text_sha256: str
    source_box: tuple[float, float, float, float] | None
    preserve_candidate: bool
    chain_member: bool


@dataclass(slots=True)
class CoverageSnapshot:
    """Frozen source inventory plus identity-based ref lookup for trackers."""

    items: tuple[FrozenCoverageItem, ...]
    _refs_by_object: dict[int, tuple[str, str]]

    def source_refs_for(self, paragraph) -> tuple[str, str] | None:
        """Return ``(physical source ref, runtime source ref)`` for a paragraph."""
        return self._refs_by_object.get(id(paragraph))


def freeze(_docs, article_document_ir, labeled_pages) -> CoverageSnapshot:
    """Freeze source text, boxes, roles and both ref namespaces."""
    article_elements = {
        element.source_ref: element
        for article in article_document_ir.articles
        for element in article.elements
    }
    chain_refs = set(article_document_ir.by_chain_member)
    items: list[FrozenCoverageItem] = []
    refs_by_object: dict[int, tuple[str, str]] = {}
    seen_physical: set[str] = set()

    for runtime_page, (physical_page, page) in enumerate(labeled_pages, start=1):
        physical_index = 0
        for runtime_index, paragraph in enumerate(page.pdf_paragraph or ()):
            if line_split.is_debug_overlay(paragraph):
                continue
            runtime_ref = f"p{runtime_page}#{runtime_index}"
            unit = line_split.source_unit(paragraph, physical_page)
            physical_ref = (
                unit.source_ref
                if unit is not None
                else f"p{physical_page}#{physical_index}"
            )
            physical_index += 1
            if physical_ref in seen_physical:
                raise ValueError(f"coverage source ref is not unique: {physical_ref}")
            seen_physical.add(physical_ref)

            element = article_elements.get(runtime_ref)
            text = (
                unit.source_text
                if unit is not None
                else str(getattr(paragraph, "unicode", "") or "")
            )
            source_box = (
                unit.source_box
                if unit is not None
                else (
                    element.source_box
                    if element is not None and element.source_box is not None
                    else _box(getattr(paragraph, "box", None))
                )
            )
            role = _role(
                paragraph,
                unit,
                None if element is None else element.role,
            )
            chain_member = runtime_ref in chain_refs or bool(
                getattr(paragraph, "chain_id", None)
            )
            if chain_member:
                role = "chain"
            preserve = role in _PRESERVE_ROLES or bool(
                unit is not None and unit.fixed_companion
            )
            item = FrozenCoverageItem(
                runtime_source_ref=runtime_ref,
                source_ref=physical_ref,
                physical_page=physical_page,
                role=role,
                source_text_sha256=_sha256(text),
                source_box=source_box,
                preserve_candidate=preserve,
                chain_member=chain_member,
            )
            items.append(item)
            refs_by_object[id(paragraph)] = (physical_ref, runtime_ref)

    return CoverageSnapshot(tuple(items), refs_by_object)


def _read_optional(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _ordinary_outcomes(tracking: dict) -> dict[str, list[dict]]:
    outcomes: dict[str, list[dict]] = {}
    for scope in ("page", "cross_page", "cross_column"):
        for page in tracking.get(scope, ()):
            if not isinstance(page, dict):
                continue
            for paragraph in page.get("paragraph", ()):
                if not isinstance(paragraph, dict):
                    continue
                runtime_ref = paragraph.get("runtime_source_ref")
                if isinstance(runtime_ref, str):
                    outcomes.setdefault(runtime_ref, []).append(dict(paragraph))
    return outcomes


def _joint_outcomes(report: dict) -> dict[str, list[dict]]:
    outcomes: dict[str, list[dict]] = {}
    rows = report.get("chains", ())
    if not isinstance(rows, list):
        return outcomes
    for row in rows:
        if not isinstance(row, dict):
            continue
        runtime_refs = row.get("runtime_source_refs")
        physical_refs = row.get("ordered_source_refs")
        fragments = row.get("ordered_fragments")
        if not all(isinstance(value, list) for value in (runtime_refs, physical_refs)):
            continue
        if not isinstance(fragments, list):
            fragments = []
        for index, runtime_ref in enumerate(runtime_refs):
            if not isinstance(runtime_ref, str):
                continue
            outcomes.setdefault(runtime_ref, []).append(
                {
                    "physical_source_ref": (
                        physical_refs[index] if index < len(physical_refs) else None
                    ),
                    "fragment": fragments[index] if index < len(fragments) else None,
                    "outcome": row.get("outcome") or row.get("result_state"),
                    "fallback_reason": row.get("fallback_reason"),
                    "joint_call_count": row.get("joint_call_count"),
                }
            )
    return outcomes


def finalize(config, snapshot: CoverageSnapshot) -> dict:
    """Join frozen sources to existing producer outcomes and write evidence."""
    report_path = Path(config.get_working_file_path(REPORT_NAME))
    working_dir = report_path.parent
    ordinary = _ordinary_outcomes(
        _read_optional(working_dir / "translate_tracking.json")
    )
    joint = _joint_outcomes(
        _read_optional(working_dir / "chain_translation.report.json")
    )
    companion_refs = {
        intent.visual_initial_ref
        for intent in drop_cap_intent.intents_for(config).values()
        if isinstance(intent.visual_initial_ref, str)
        and intent.visual_initial_ref != intent.source_ref
        and intent.binding_proof.get("kind") == "standalone_visual_initial"
    }

    rows: list[dict] = []
    for item in snapshot.items:
        ordinary_rows = ordinary.get(item.runtime_source_ref, [])
        joint_rows = joint.get(item.runtime_source_ref, [])
        target_text: str | None = None

        if item.source_ref in companion_refs and not joint_rows and not ordinary_rows:
            translation_owner = "none"
            final_status = "merged_into_drop_cap_owner"
        elif joint_rows:
            translation_owner = "joint"
            evidence = joint_rows[0]
            target_text = evidence.get("fragment")
            physical_match = evidence.get("physical_source_ref") == item.source_ref
            # Chain writeback intentionally reuses one historical paragraph
            # tracker.  It is the same joint outcome when its output equals
            # the chain fragment; a second tracker or a different output is a
            # real ordinary takeover and must stay visible.
            tracker_disagrees = len(ordinary_rows) > 1 or (
                len(ordinary_rows) == 1
                and (
                    ordinary_rows[0].get("source_ref") != item.source_ref
                    or ordinary_rows[0].get("output") != target_text
                )
            )
            if len(joint_rows) != 1:
                final_status = "duplicate_joint_outcome"
            elif tracker_disagrees:
                final_status = "duplicate_ownership"
            elif not physical_match:
                final_status = "source_ref_mismatch"
            elif (
                evidence.get("outcome") != "joint_success"
                or evidence.get("joint_call_count") != 1
                or evidence.get("fallback_reason") is not None
            ):
                final_status = str(evidence.get("outcome") or "joint_failed")
            elif not isinstance(target_text, str) or not target_text:
                final_status = "empty_target"
            else:
                final_status = "joint_success"
        elif ordinary_rows:
            translation_owner = "ordinary"
            evidence = ordinary_rows[0]
            target_text = evidence.get("output")
            if len(ordinary_rows) != 1:
                final_status = "duplicate_ordinary_outcome"
            elif evidence.get("source_ref") != item.source_ref:
                final_status = "source_ref_mismatch"
            elif not isinstance(target_text, str) or not target_text:
                final_status = "empty_target"
            else:
                final_status = "translated"
        elif item.preserve_candidate:
            translation_owner = "preserve"
            final_status = "preserved"
        else:
            translation_owner = "none"
            final_status = (
                "missing_joint_outcome" if item.chain_member else "untranslated"
            )

        rows.append(
            {
                "source_ref": item.source_ref,
                "runtime_source_ref": item.runtime_source_ref,
                "physical_page": item.physical_page,
                "role": (
                    "drop_cap_companion"
                    if item.source_ref in companion_refs
                    else item.role
                ),
                "source_text_sha256": item.source_text_sha256,
                "source_box": (
                    None if item.source_box is None else list(item.source_box)
                ),
                "translation_owner": translation_owner,
                "target_text_sha256": (
                    _sha256(target_text if isinstance(target_text, str) else "")
                    if translation_owner in {"joint", "ordinary"}
                    else None
                ),
                "final_status": final_status,
            }
        )

    owner_totals = dict.fromkeys(("joint", "ordinary", "preserve", "none"), 0)
    for row in rows:
        owner_totals[row["translation_owner"]] += 1
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "direction": (
            f"{getattr(config, 'lang_in', '')}-{getattr(config, 'lang_out', '')}"
        ),
        "source_lang": str(getattr(config, "lang_in", "")),
        "target_lang": str(getattr(config, "lang_out", "")),
        "items": rows,
        "totals": {"sources": len(rows), "owners": owner_totals},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
