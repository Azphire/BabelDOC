"""Immutable article-level checkpoints across the translation pipeline."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from babeldoc.magazine.legal_slots import digest_record
from babeldoc.magazine.runtime_profile import semantic_projection

ARTICLE_KNOWLEDGE_STATE_SCHEMA_VERSION = "article-knowledge-state.v1"
ARTICLE_CONTEXT_RECORD_SCHEMA_VERSION = "article-context-record.v1"
ARTICLE_STATE_MANIFEST_SCHEMA_VERSION = "article-state-manifest.v1"
ARTICLE_STATE_MANIFEST_NAME = "article_state.manifest.json"


class ArticleStateStage(StrEnum):
    SOURCE_RECONSTRUCTED = "SOURCE_RECONSTRUCTED"
    PRE_TRANSLATION = "PRE_TRANSLATION"
    TARGET_GENERATED = "TARGET_GENERATED"
    TARGET_ALLOCATED = "TARGET_ALLOCATED"
    TYPESET = "TYPESET"


class ArticleStateStatus(StrEnum):
    CAPTURED = "CAPTURED"
    NOT_EXERCISED = "NOT_EXERCISED"
    SKIPPED = "SKIPPED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True, slots=True)
class ArticleContextRecord:
    article_id: str
    ordered_source_refs: tuple[str, ...]
    chain_refs: tuple[str, ...]
    context_window_refs: tuple[str, ...]
    page_policy_refs: tuple[str, ...]
    page_policy_sha256: str
    style_policy_sha256: str
    manual_term_refs: tuple[str, ...]
    manual_term_inventory_sha256: str
    register_expectation: str
    delivery_expectation: str
    input_manifest_sha256: str
    record_sha256: str
    schema_version: str = ARTICLE_CONTEXT_RECORD_SCHEMA_VERSION

    def material(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "article_id": self.article_id,
            "ordered_source_refs": list(self.ordered_source_refs),
            "chain_refs": list(self.chain_refs),
            "context_window_refs": list(self.context_window_refs),
            "page_policy_refs": list(self.page_policy_refs),
            "page_policy_sha256": self.page_policy_sha256,
            "style_policy_sha256": self.style_policy_sha256,
            "manual_term_refs": list(self.manual_term_refs),
            "manual_term_inventory_sha256": self.manual_term_inventory_sha256,
            "register_expectation": self.register_expectation,
            "delivery_expectation": self.delivery_expectation,
            "input_manifest_sha256": self.input_manifest_sha256,
        }

    def to_record(self) -> dict:
        return {**self.material(), "record_sha256": self.record_sha256}


def _paragraphs_by_ref(docs) -> dict[str, object]:
    from babeldoc.magazine.page_identity import physical_page_number

    return {
        f"p{int(physical_page_number(page))}#{index}": paragraph
        for page in docs.page or ()
        for index, paragraph in enumerate(page.pdf_paragraph or ())
    }


def _manual_terms(translation_config) -> tuple[dict, ...]:
    shared = translation_config.shared_context_cross_split_part
    rows = []
    for glossary in shared.user_glossaries:
        for entry in glossary.entries:
            row = {
                "glossary": str(glossary.name),
                "source": str(entry.source),
                "target": str(entry.target),
                "target_language": getattr(entry, "target_language", None),
            }
            rows.append(row)
    return tuple(
        sorted(rows, key=lambda row: (row["glossary"], row["source"], row["target"]))
    )


def _style_policy_record(translation_config) -> dict:
    return {
        "lang_in": translation_config.lang_in,
        "lang_out": translation_config.lang_out,
        "custom_system_prompt": getattr(
            translation_config, "custom_system_prompt", None
        ),
        "person_names_policy": getattr(
            translation_config, "magazine_person_names_policy", None
        ),
    }


class ArticleContextRecordPlanner:
    """Build model-free, owner-scoped context inputs before translation."""

    def __init__(self, translation_config, article_document_ir) -> None:
        self.translation_config = translation_config
        self.article_document_ir = article_document_ir

    def plan(self, docs, *, delivery_expectation: str) -> tuple[ArticleContextRecord, ...]:
        paragraphs = _paragraphs_by_ref(docs)
        terms = _manual_terms(self.translation_config)
        records = []
        for article in self.article_document_ir.articles:
            source_refs = tuple(element.source_ref for element in article.elements)
            article_text = "\n".join(
                str(getattr(paragraphs.get(reference), "unicode", "") or "")
                for reference in source_refs
            ).casefold()
            active_terms = tuple(
                row for row in terms if row["source"].casefold() in article_text
            )
            term_refs = tuple(
                f"manual-term:{digest_record(row)}" for row in active_terms
            )
            policy_rows = tuple(item.to_record() for item in article.policy_evidence)
            page_policy_refs = tuple(
                f"page-policy:p{row['page']}:{digest_record(row)}"
                for row in policy_rows
            )
            style_rows = tuple(
                {
                    "source_ref": element.source_ref,
                    "style_hash": element.style_hash,
                    "role": element.role.value,
                }
                for element in article.elements
            )
            context_window = source_refs[: min(3, len(source_refs))]
            style_policy = _style_policy_record(self.translation_config)
            register_expectation = (
                "NOT_EXERCISED"
                if delivery_expectation == "NOT_EXERCISED"
                else (
                    "ARTICLE_BRIEF_REGISTER"
                    if self.translation_config.magazine_article_context
                    else "UNDECLARED"
                )
            )
            input_manifest = {
                "schema_version": ARTICLE_CONTEXT_RECORD_SCHEMA_VERSION,
                "article_id": article.article_id,
                "ordered_source_refs": list(source_refs),
                "chain_refs": list(article.chain_ids),
                "context_window_refs": list(context_window),
                "page_policy": list(policy_rows),
                "style_policy": list(style_rows),
                "translation_style_policy": style_policy,
                "manual_terms": list(active_terms),
                "generator": "ArticleContextRecordPlanner",
                "config": {
                    "lang_in": self.translation_config.lang_in,
                    "lang_out": self.translation_config.lang_out,
                    "magazine_article_context": bool(
                        self.translation_config.magazine_article_context
                    ),
                },
            }
            material = {
                "schema_version": ARTICLE_CONTEXT_RECORD_SCHEMA_VERSION,
                "article_id": article.article_id,
                "ordered_source_refs": list(source_refs),
                "chain_refs": list(article.chain_ids),
                "context_window_refs": list(context_window),
                "page_policy_refs": list(page_policy_refs),
                "page_policy_sha256": digest_record(policy_rows),
                "style_policy_sha256": digest_record(style_policy),
                "manual_term_refs": list(term_refs),
                "manual_term_inventory_sha256": digest_record(active_terms),
                "register_expectation": register_expectation,
                "delivery_expectation": delivery_expectation,
                "input_manifest_sha256": digest_record(input_manifest),
            }
            records.append(
                ArticleContextRecord(
                    article_id=article.article_id,
                    ordered_source_refs=source_refs,
                    chain_refs=article.chain_ids,
                    context_window_refs=context_window,
                    page_policy_refs=page_policy_refs,
                    page_policy_sha256=material["page_policy_sha256"],
                    style_policy_sha256=material["style_policy_sha256"],
                    manual_term_refs=term_refs,
                    manual_term_inventory_sha256=material[
                        "manual_term_inventory_sha256"
                    ],
                    register_expectation=register_expectation,
                    delivery_expectation=delivery_expectation,
                    input_manifest_sha256=material["input_manifest_sha256"],
                    record_sha256=digest_record(material),
                )
            )
        return tuple(records)


@dataclass(frozen=True, slots=True)
class ArticleKnowledgeState:
    generation: int
    previous_generation: int | None
    stage: ArticleStateStage
    status: ArticleStateStatus
    reason: str | None
    document_semantic_sha256: str
    page_selection_map_sha256: str
    article_ir_sha256: str
    run_trace_generation: int
    article_refs: tuple[str, ...]
    element_refs: tuple[str, ...]
    chain_refs: tuple[str, ...]
    legal_slot_refs: tuple[str, ...]
    legal_slots_sha256: str
    article_context_record_refs: tuple[str, ...]
    context_sha256: str | None
    context_input_manifest_sha256: str
    style_policy_sha256: str
    page_policy_sha256: str
    manual_term_inventory_sha256: str
    manual_constraint_refs: tuple[str, ...]
    fixed_asset_inventory_sha256: str
    fixed_asset_refs: tuple[str, ...]
    state_sha256: str
    schema_version: str = ARTICLE_KNOWLEDGE_STATE_SCHEMA_VERSION

    def material(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "generation": self.generation,
            "previous_generation": self.previous_generation,
            "stage": self.stage.value,
            "status": self.status.value,
            "reason": self.reason,
            "document_semantic_sha256": self.document_semantic_sha256,
            "page_selection_map_sha256": self.page_selection_map_sha256,
            "article_ir_sha256": self.article_ir_sha256,
            "run_trace_generation": self.run_trace_generation,
            "article_refs": list(self.article_refs),
            "element_refs": list(self.element_refs),
            "chain_refs": list(self.chain_refs),
            "legal_slot_refs": list(self.legal_slot_refs),
            "legal_slots_sha256": self.legal_slots_sha256,
            "article_context_record_refs": list(self.article_context_record_refs),
            "context_sha256": self.context_sha256,
            "context_input_manifest_sha256": self.context_input_manifest_sha256,
            "style_policy_sha256": self.style_policy_sha256,
            "page_policy_sha256": self.page_policy_sha256,
            "manual_term_inventory_sha256": self.manual_term_inventory_sha256,
            "manual_constraint_refs": list(self.manual_constraint_refs),
            "fixed_asset_inventory_sha256": self.fixed_asset_inventory_sha256,
            "fixed_asset_refs": list(self.fixed_asset_refs),
        }

    def to_record(self) -> dict:
        return {**self.material(), "state_sha256": self.state_sha256}


def _document_digest(docs) -> str:
    projection = semantic_projection("article_state", docs)
    projection.pop("stage", None)
    projection.pop("article_ir", None)
    return digest_record(projection)


def _selection_digest(article_document_ir) -> str:
    selection = article_document_ir.page_selection_map
    return digest_record(None if selection is None else selection.to_record())


def _manual_constraint_refs(translation_config) -> tuple[str, ...]:
    decisions = getattr(translation_config, "magazine_hitl_decisions", None)
    if decisions is None:
        return ()
    rows = []
    for name in ("terms", "page_kinds", "drop_caps"):
        value = getattr(decisions, name, None)
        if value:
            rows.append(f"manual-constraint:{name}:{digest_record(value)}")
    return tuple(rows)


class ArticleStateJournal:
    """Append-only article state generations plus one deterministic index."""

    def __init__(
        self,
        translation_config,
        docs,
        article_document_ir,
        run_trace,
        fixed_asset_inventory,
        legal_slot_plan,
    ) -> None:
        self.translation_config = translation_config
        self.docs = docs
        self.article_document_ir = article_document_ir
        self.run_trace = run_trace
        self.fixed_asset_inventory = fixed_asset_inventory
        self.legal_slot_plan = legal_slot_plan
        self.states: tuple[ArticleKnowledgeState, ...] = ()
        self.context_records: tuple[ArticleContextRecord, ...] = ()

    @property
    def working_dir(self) -> Path:
        return Path(
            self.translation_config.get_working_file_path(ARTICLE_STATE_MANIFEST_NAME)
        ).parent

    def plan_context(self, *, delivery_expectation: str) -> tuple[ArticleContextRecord, ...]:
        self.context_records = ArticleContextRecordPlanner(
            self.translation_config, self.article_document_ir
        ).plan(self.docs, delivery_expectation=delivery_expectation)
        return self.context_records

    def capture(
        self,
        stage: ArticleStateStage,
        *,
        status: ArticleStateStatus = ArticleStateStatus.CAPTURED,
        reason: str | None = None,
        include_context: bool = True,
        previous_generation: int | None = None,
    ) -> ArticleKnowledgeState:
        generation = len(self.states) + 1
        if self.states and stage in {item.stage for item in self.states}:
            raise ValueError(f"article state stage already captured: {stage.value}")
        if previous_generation is None and self.states:
            previous_generation = self.states[-1].generation
        context = self.context_records if include_context else ()
        context_records = tuple(item.to_record() for item in context)
        policy_records = self.context_records
        if not policy_records:
            style_policy = tuple(
                (
                    article.article_id,
                    digest_record(_style_policy_record(self.translation_config)),
                )
                for article in self.article_document_ir.articles
            )
            page_policy = tuple(
                (
                    article.article_id,
                    digest_record(
                        tuple(item.to_record() for item in article.policy_evidence)
                    ),
                )
                for article in self.article_document_ir.articles
            )
        else:
            style_policy = tuple(
                (item.article_id, item.style_policy_sha256)
                for item in policy_records
            )
            page_policy = tuple(
                (item.article_id, item.page_policy_sha256)
                for item in policy_records
            )
        term_inventory = _manual_terms(self.translation_config)
        inventory_record = self.fixed_asset_inventory.to_record()
        material = {
            "schema_version": ARTICLE_KNOWLEDGE_STATE_SCHEMA_VERSION,
            "generation": generation,
            "previous_generation": previous_generation,
            "stage": stage.value,
            "status": status.value,
            "reason": reason,
            "document_semantic_sha256": _document_digest(self.docs),
            "page_selection_map_sha256": _selection_digest(self.article_document_ir),
            "article_ir_sha256": digest_record(self.article_document_ir.to_record()),
            "run_trace_generation": int(self.run_trace.current_generation),
            "article_refs": [
                item.article_id for item in self.article_document_ir.articles
            ],
            "element_refs": sorted(self.article_document_ir.by_element),
            "chain_refs": sorted(self.article_document_ir.by_chain),
            "legal_slot_refs": [item.slot_id for item in self.legal_slot_plan.slots],
            "legal_slots_sha256": self.legal_slot_plan.digest,
            "article_context_record_refs": [
                f"article-context:{item.article_id}:{item.record_sha256}"
                for item in context
            ],
            "context_sha256": digest_record(context_records) if context else None,
            "context_input_manifest_sha256": digest_record(
                [item.input_manifest_sha256 for item in self.context_records]
            ),
            "style_policy_sha256": digest_record(style_policy),
            "page_policy_sha256": digest_record(page_policy),
            "manual_term_inventory_sha256": digest_record(term_inventory),
            "manual_constraint_refs": list(
                _manual_constraint_refs(self.translation_config)
            ),
            "fixed_asset_inventory_sha256": digest_record(inventory_record),
            "fixed_asset_refs": [
                item.reference for item in self.fixed_asset_inventory.assets
            ],
        }
        state = ArticleKnowledgeState(
            generation=generation,
            previous_generation=previous_generation,
            stage=stage,
            status=status,
            reason=reason,
            document_semantic_sha256=material["document_semantic_sha256"],
            page_selection_map_sha256=material["page_selection_map_sha256"],
            article_ir_sha256=material["article_ir_sha256"],
            run_trace_generation=material["run_trace_generation"],
            article_refs=tuple(material["article_refs"]),
            element_refs=tuple(material["element_refs"]),
            chain_refs=tuple(material["chain_refs"]),
            legal_slot_refs=tuple(material["legal_slot_refs"]),
            legal_slots_sha256=material["legal_slots_sha256"],
            article_context_record_refs=tuple(
                material["article_context_record_refs"]
            ),
            context_sha256=material["context_sha256"],
            context_input_manifest_sha256=material[
                "context_input_manifest_sha256"
            ],
            style_policy_sha256=material["style_policy_sha256"],
            page_policy_sha256=material["page_policy_sha256"],
            manual_term_inventory_sha256=material[
                "manual_term_inventory_sha256"
            ],
            manual_constraint_refs=tuple(material["manual_constraint_refs"]),
            fixed_asset_inventory_sha256=material[
                "fixed_asset_inventory_sha256"
            ],
            fixed_asset_refs=tuple(material["fixed_asset_refs"]),
            state_sha256=digest_record(material),
        )
        self.states = (*self.states, state)
        self._write(state)
        return state

    def _write(self, state: ArticleKnowledgeState) -> None:
        filename = (
            f"article_state.{state.generation:04d}."
            f"{state.stage.value.lower()}.json"
        )
        state_path = self.working_dir / filename
        _atomic_write(state_path, state.to_record())
        manifest = {
            "schema_version": ARTICLE_STATE_MANIFEST_SCHEMA_VERSION,
            "latest_generation": state.generation,
            "states": [
                {
                    "generation": item.generation,
                    "stage": item.stage.value,
                    "status": item.status.value,
                    "reason": item.reason,
                    "state_sha256": item.state_sha256,
                    "file": (
                        f"article_state.{item.generation:04d}."
                        f"{item.stage.value.lower()}.json"
                    ),
                }
                for item in self.states
            ],
            "context_records": [item.to_record() for item in self.context_records],
        }
        _atomic_write(self.working_dir / ARTICLE_STATE_MANIFEST_NAME, manifest)


def _atomic_write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
