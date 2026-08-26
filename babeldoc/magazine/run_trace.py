"""Versioned runtime lineage from source paragraphs to rendered geometry."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from pathlib import Path

from babeldoc.magazine.article_ir import ArticleDocumentIR

SCHEMA_VERSION = "run-trace.v2"
CANONICALIZATION_VERSION = "utf8-lf-json-v1"
SOURCE_REF_FREEZE_STAGE = "post-article-builder-v1"
REPORT_NAME = "run_trace.report.json"
SWITCH = "magazine_article_group"

REQUEST_OPEN = "open"
REQUEST_COMPLETED = "completed"
REQUEST_FAILED = "failed"

ALLOCATION_ALLOCATED = "allocated"
ALLOCATION_FAILED = "failed"
ALLOCATION_INACTIVE = "inactive"
ALLOCATION_RELEASED = "released"

RENDER_PENDING = "pending"
RENDER_RENDERED = "rendered"
RENDER_INACTIVE = "inactive"

GENERATION_OPEN = "open"
GENERATION_COMMITTED = "committed"
GENERATION_ROLLED_BACK = "rolled_back"

_SOURCE_REF_RE = re.compile(r"^p([1-9][0-9]*)#([0-9]+)$")
BoxTuple = tuple[float, float, float, float]


class SourceTerminalState(str, Enum):
    """The required final disposition of one registered source element."""

    RENDERED = "rendered"
    PROTECTED = "protected"
    FAILED_WITH_ISSUE = "failed_with_issue"


class ChainResultState(str, Enum):
    """The only terminal outcomes of a confirmed continuity chain."""

    JOINT_SUCCESS = "joint_success"
    PROTECTED_UNTRANSLATED = "protected_untranslated"
    FAILED_WITH_ISSUE = "failed_with_issue"


def canonical_text(value: str) -> str:
    """Canonical text used by every text hash and target range."""
    return value.replace("\r\n", "\n").replace("\r", "\n")


def canonical_json_bytes(value) -> bytes:
    """Canonical JSON bytes used by deterministic identifiers and hashes."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def hash_record(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(canonical_text(value).encode("utf-8")).hexdigest()


def source_ref(page: int, index: int) -> str:
    if page < 1 or index < 0:
        raise ValueError("source page must be positive and index must be non-negative")
    return f"p{page}#{index}"


def parse_source_ref(reference: str) -> tuple[int, int]:
    match = _SOURCE_REF_RE.fullmatch(reference)
    if match is None:
        raise ValueError(f"invalid stable source ref: {reference!r}")
    return int(match.group(1)), int(match.group(2))


def _box_tuple(box) -> BoxTuple | None:
    if box is None:
        return None
    values = tuple(getattr(box, name, None) for name in ("x", "y", "x2", "y2"))
    if any(value is None for value in values):
        return None
    return tuple(float(value) for value in values)


def _checked_box(box: Sequence[float] | None) -> BoxTuple | None:
    if box is None:
        return None
    if len(box) != 4:
        raise ValueError("geometry boxes must contain four coordinates")
    values = tuple(float(value) for value in box)
    if values[0] > values[2] or values[1] > values[3]:
        raise ValueError("geometry box coordinates must be ordered")
    return values


def _style_record(paragraph) -> dict:
    style = getattr(paragraph, "pdf_style", None)
    graphic_state = None if style is None else getattr(style, "graphic_state", None)
    return {
        "font_id": None if style is None else getattr(style, "font_id", None),
        "font_size": None if style is None else getattr(style, "font_size", None),
        "graphic_state": None
        if graphic_state is None
        else getattr(graphic_state, "passthrough_per_char_instruction", None),
    }


def _composition_characters(paragraph) -> list:
    characters = []
    for composition in getattr(paragraph, "pdf_paragraph_composition", None) or ():
        character = getattr(composition, "pdf_character", None)
        if character is not None:
            characters.append(character)
        formula = getattr(composition, "pdf_formula", None)
        if formula is not None:
            characters.extend(getattr(formula, "pdf_character", None) or ())
        line = getattr(composition, "pdf_line", None)
        if line is not None:
            characters.extend(getattr(line, "pdf_character", None) or ())
        same_style = getattr(composition, "pdf_same_style_characters", None)
        if same_style is not None:
            characters.extend(getattr(same_style, "pdf_character", None) or ())
    return characters


def _union_box(boxes: Iterable[BoxTuple | None]) -> BoxTuple | None:
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    return (
        min(box[0] for box in present),
        min(box[1] for box in present),
        max(box[2] for box in present),
        max(box[3] for box in present),
    )


def _font_color_summary(paragraph) -> tuple[dict, dict]:
    characters = _composition_characters(paragraph)
    styles = [
        getattr(character, "pdf_style", None)
        for character in characters
        if getattr(character, "pdf_style", None) is not None
    ]
    if not styles and getattr(paragraph, "pdf_style", None) is not None:
        styles = [paragraph.pdf_style]
    fonts = sorted(
        {
            (getattr(style, "font_id", None), getattr(style, "font_size", None))
            for style in styles
        },
        key=lambda item: (str(item[0]), -1.0 if item[1] is None else float(item[1])),
    )
    graphic_hashes = sorted(
        {
            hash_text(instruction)
            for style in styles
            for graphic_state in (getattr(style, "graphic_state", None),)
            for instruction in (
                None
                if graphic_state is None
                else getattr(
                    graphic_state, "passthrough_per_char_instruction", None
                ),
            )
            if instruction is not None
        }
    )
    return (
        {
            "fonts": [
                {"font_id": font_id, "font_size": font_size}
                for font_id, font_size in fonts
            ]
        },
        {"graphic_state_hashes": graphic_hashes},
    )


@dataclass(slots=True)
class SourceRecord:
    source_ref: str
    page: int
    index: int
    source_box: BoxTuple | None
    text_hash: str
    style_hash: str
    article_id: str | None
    chain_id: str | None
    terminal_state: SourceTerminalState | None = None
    terminal_issue: str | None = None
    request_ids: set[str] = field(default_factory=set)
    fragment_ids: set[str] = field(default_factory=set)

    def to_record(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "page": self.page,
            "index": self.index,
            "source_box": None if self.source_box is None else list(self.source_box),
            "text_hash": self.text_hash,
            "style_hash": self.style_hash,
            "article_id": self.article_id,
            "chain_id": self.chain_id,
            "terminal_state": None
            if self.terminal_state is None
            else self.terminal_state.value,
            "terminal_issue": self.terminal_issue,
            "request_ids": sorted(self.request_ids),
            "fragment_ids": sorted(self.fragment_ids),
        }


@dataclass(slots=True)
class RequestRecord:
    request_id: str
    request_kind: str
    ordered_source_refs: tuple[str, ...]
    merged_source_hash: str
    prompt_config_hash: str
    translator_call_count: int = 0
    status: str = REQUEST_OPEN
    issue: str | None = None
    whole_target_hash: str | None = None
    whole_target_chars: int | None = None
    fragment_ids: set[str] = field(default_factory=set)

    def to_record(self) -> dict:
        return {
            "request_id": self.request_id,
            "request_kind": self.request_kind,
            "ordered_source_refs": list(self.ordered_source_refs),
            "merged_source_hash": self.merged_source_hash,
            "prompt_config_hash": self.prompt_config_hash,
            "translator_call_count": self.translator_call_count,
            "status": self.status,
            "issue": self.issue,
            "whole_target_hash": self.whole_target_hash,
            "whole_target_chars": self.whole_target_chars,
            "fragment_ids": sorted(self.fragment_ids),
        }


@dataclass(slots=True)
class ChainOutcomeRecord:
    chain_id: str
    ordered_source_refs: tuple[str, ...]
    result_state: ChainResultState
    request_id: str | None
    translator_call_count: int
    issue: str | None = None

    def to_record(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "ordered_source_refs": list(self.ordered_source_refs),
            "request_id": self.request_id,
            "translator_call_count": self.translator_call_count,
            "result_state": self.result_state.value,
            "issue": self.issue,
        }


@dataclass(slots=True)
class FragmentRecord:
    fragment_id: str
    request_id: str
    source_ref: str
    order: int
    text_start: int
    text_end: int
    text_hash: str
    allocation_status: str
    generation: int
    slot_id: str | None
    render_ref: str | None
    render_page: int | None
    measurement_summary: dict
    active: bool = True
    terminal_state: SourceTerminalState | None = None
    terminal_issue: str | None = None
    geometry_ids: set[str] = field(default_factory=set)

    def to_record(self) -> dict:
        return {
            "fragment_id": self.fragment_id,
            "request_id": self.request_id,
            "source_ref": self.source_ref,
            "order": self.order,
            "text_range": [self.text_start, self.text_end],
            "text_hash": self.text_hash,
            "allocation_status": self.allocation_status,
            "generation": self.generation,
            "slot_id": self.slot_id,
            "render_ref": self.render_ref,
            "render_page": self.render_page,
            "measurement_summary": dict(self.measurement_summary),
            "active": self.active,
            "terminal_state": None
            if self.terminal_state is None
            else self.terminal_state.value,
            "terminal_issue": self.terminal_issue,
            "geometry_ids": sorted(self.geometry_ids),
        }


@dataclass(slots=True)
class GeometryRecord:
    geometry_id: str
    fragment_id: str
    slot_id: str
    generation: int
    pre_repair_box: BoxTuple | None
    final_page: int | None
    final_box: BoxTuple | None
    font_summary: dict
    color_summary: dict
    render_status: str
    active: bool = True
    replaces_geometry_id: str | None = None
    binding_id: str | None = None
    binding_kind: str | None = None
    span_ids: tuple[str, ...] = ()

    def to_record(self) -> dict:
        return {
            "geometry_id": self.geometry_id,
            "fragment_id": self.fragment_id,
            "slot_id": self.slot_id,
            "generation": self.generation,
            "pre_repair_box": None
            if self.pre_repair_box is None
            else list(self.pre_repair_box),
            "final_page": self.final_page,
            "final_box": None if self.final_box is None else list(self.final_box),
            "font_summary": self.font_summary,
            "color_summary": self.color_summary,
            "render_status": self.render_status,
            "active": self.active,
            "replaces_geometry_id": self.replaces_geometry_id,
            "binding_id": self.binding_id,
            "binding_kind": self.binding_kind,
            "span_ids": list(self.span_ids),
        }


@dataclass(slots=True)
class GenerationRecord:
    generation: int
    reason: str
    status: str
    fragment_ids: list[str] = field(default_factory=list)
    geometry_ids: list[str] = field(default_factory=list)
    replaced_fragment_ids: list[str] = field(default_factory=list)
    flow_slot_ids: list[str] = field(default_factory=list)

    def to_record(self) -> dict:
        return {
            "generation": self.generation,
            "reason": self.reason,
            "status": self.status,
            "fragment_ids": sorted(self.fragment_ids),
            "geometry_ids": sorted(self.geometry_ids),
            "replaced_fragment_ids": sorted(self.replaced_fragment_ids),
            "flow_slot_ids": sorted(self.flow_slot_ids),
        }


@dataclass(slots=True)
class FlowSlotRecord:
    """One article-flow slot, including released and protected regions."""

    slot_id: str
    article_id: str
    page: int
    status: str
    box: BoxTuple | None
    source_ref: str | None = None
    render_ref: str | None = None
    previous_page: int | None = None
    previous_slot_id: str | None = None
    reason: str | None = None
    generation: int = 0
    active: bool = True

    def to_record(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "article_id": self.article_id,
            "page": self.page,
            "status": self.status,
            "box": None if self.box is None else list(self.box),
            "source_ref": self.source_ref,
            "render_ref": self.render_ref,
            "movement": None
            if self.previous_page is None and self.previous_slot_id is None
            else {
                "before": {
                    "page": self.previous_page,
                    "slot_id": self.previous_slot_id,
                },
                "after": {"page": self.page, "slot_id": self.slot_id},
            },
            "reason": self.reason,
            "generation": self.generation,
            "active": self.active,
        }


class RunTrace:
    """One thread-safe trace ledger for a complete translation run."""

    def __init__(self) -> None:
        self.sources: dict[str, SourceRecord] = {}
        self.requests: dict[str, RequestRecord] = {}
        self.chain_outcomes: dict[str, ChainOutcomeRecord] = {}
        self.fragments: dict[str, FragmentRecord] = {}
        self.geometries: dict[str, GeometryRecord] = {}
        self.flow_slots: dict[str, FlowSlotRecord] = {}
        self.generations: dict[int, GenerationRecord] = {
            0: GenerationRecord(0, "typeset", GENERATION_COMMITTED)
        }
        self.current_generation = 0
        self.unsupported_pages: set[int] = set()
        self.blocked_reasons: list[dict] = []
        self.drop_cap_events: list[dict] = []
        self.final_pdf_compliance: dict | None = None
        self._source_objects: dict[int, str] = {}
        self._whole_targets: dict[str, str] = {}
        self._fragment_text: dict[str, str] = {}
        self._generation_request_snapshots: dict[int, dict[str, set[str]]] = {}
        self._generation_fragment_snapshots: dict[
            int,
            dict[str, tuple[bool, str, SourceTerminalState | None, str | None]],
        ] = {}
        self._lock = threading.RLock()

    @classmethod
    def from_document(
        cls,
        document,
        article_document_ir: ArticleDocumentIR | None = None,
    ) -> RunTrace:
        trace = cls()
        trace.register_document(document, article_document_ir)
        return trace

    def register_document(
        self,
        document,
        article_document_ir: ArticleDocumentIR | None = None,
    ) -> None:
        """Freeze pN#k after structural stages and bind refs to runtime objects."""
        self.unsupported_pages = (
            set()
            if article_document_ir is None
            else {item.page for item in article_document_ir.unsupported_pages}
        )
        ir_elements = (
            {}
            if article_document_ir is None
            else {
                element.source_ref: element
                for article in article_document_ir.articles
                for element in article.elements
            }
        )
        article_by_ref: Mapping[str, str] = (
            {} if article_document_ir is None else article_document_ir.by_element
        )
        chain_by_ref: Mapping[str, str] = (
            {}
            if article_document_ir is None
            else article_document_ir.by_chain_member
        )
        raw_chains: dict[str, list[str]] = {}
        paragraphs: list[tuple[str, int, int, object]] = []
        for page_index, page in enumerate(document.page):
            for paragraph_index, paragraph in enumerate(page.pdf_paragraph or ()):
                reference = source_ref(page_index + 1, paragraph_index)
                paragraphs.append(
                    (reference, page_index + 1, paragraph_index, paragraph)
                )
                raw_chain_id = getattr(paragraph, "chain_id", None)
                if raw_chain_id:
                    raw_chains.setdefault(raw_chain_id, []).append(reference)
        fallback_chain_by_ref = {
            reference: f"chain-{hash_record(tuple(references))}"
            for references in raw_chains.values()
            for reference in references
        }
        for reference, page, index, paragraph in paragraphs:
            ir_element = ir_elements.get(reference)
            if ir_element is not None:
                raw_text_hash = hashlib.sha256(
                    (getattr(paragraph, "unicode", None) or "").encode("utf-8")
                ).hexdigest()
                if (
                    ir_element.page != page
                    or ir_element.source_box
                    != _box_tuple(getattr(paragraph, "box", None))
                    or ir_element.source_text_hash != raw_text_hash
                    or ir_element.style_hash != hash_record(_style_record(paragraph))
                ):
                    raise ValueError(
                        f"{reference} changed after canonical source refs froze"
                    )
            self.register_source(
                reference,
                page=page,
                index=index,
                source_box=_box_tuple(getattr(paragraph, "box", None)),
                text_hash=hash_text(getattr(paragraph, "unicode", None) or ""),
                style_hash=hash_record(_style_record(paragraph)),
                article_id=article_by_ref.get(reference),
                chain_id=chain_by_ref.get(reference)
                or fallback_chain_by_ref.get(reference),
                source_object=paragraph,
            )

    def register_source(
        self,
        reference: str,
        *,
        page: int,
        index: int,
        source_box: Sequence[float] | None,
        text_hash: str,
        style_hash: str,
        article_id: str | None = None,
        chain_id: str | None = None,
        source_object=None,
    ) -> None:
        parsed_page, parsed_index = parse_source_ref(reference)
        if (parsed_page, parsed_index) != (page, index):
            raise ValueError("source ref must agree with its frozen page and index")
        with self._lock:
            if reference in self.sources:
                raise ValueError(f"source ref registered twice: {reference}")
            self.sources[reference] = SourceRecord(
                source_ref=reference,
                page=page,
                index=index,
                source_box=_checked_box(source_box),
                text_hash=text_hash,
                style_hash=style_hash,
                article_id=article_id,
                chain_id=chain_id,
            )
            if source_object is not None:
                self._source_objects[id(source_object)] = reference

    def source_ref_for(self, source_object) -> str | None:
        return self._source_objects.get(id(source_object))

    def target_fragments_for_source(self, reference: str) -> tuple[dict, ...]:
        """Return the current target pieces owned by one frozen source."""
        with self._lock:
            if reference not in self.sources:
                raise KeyError(f"unknown source: {reference}")
            held = [
                self.fragments[fragment_id]
                for fragment_id in self.sources[reference].fragment_ids
                if fragment_id in self.fragments
                and self.fragments[fragment_id].active
            ]
            held.sort(key=lambda item: (item.text_start, item.order, item.fragment_id))
            return tuple(
                {
                    "fragment_id": fragment.fragment_id,
                    "request_id": fragment.request_id,
                    "source_ref": fragment.source_ref,
                    "text_start": fragment.text_start,
                    "text_end": fragment.text_end,
                    "text": self._fragment_text[fragment.fragment_id],
                    "slot_id": fragment.slot_id,
                    "render_ref": fragment.render_ref,
                    "render_page": fragment.render_page,
                    "measurement_summary": dict(fragment.measurement_summary),
                }
                for fragment in held
            )

    def target_fragment_text(self, fragment_id: str) -> str:
        with self._lock:
            if fragment_id not in self.fragments:
                raise KeyError(f"unknown target fragment: {fragment_id}")
            return self._fragment_text[fragment_id]

    def target_conservation_evidence(self, request_id: str) -> dict:
        """Return hash-and-range evidence for one request without target text."""
        with self._lock:
            request = self._request(request_id)
            fragments = sorted(
                (
                    self.fragments[fragment_id]
                    for fragment_id in request.fragment_ids
                    if fragment_id in self.fragments
                ),
                key=lambda item: (item.order, item.fragment_id),
            )
            reconstructed = "".join(
                self._fragment_text.get(fragment.fragment_id, "")
                for fragment in fragments
            )
            return {
                "request_id": request_id,
                "request_kind": request.request_kind,
                "ordered_source_refs": list(request.ordered_source_refs),
                "whole_target_hash": request.whole_target_hash,
                "whole_target_chars": request.whole_target_chars,
                "reconstructed_target_hash": hash_text(reconstructed),
                "reconstructed_target_chars": len(reconstructed),
                "fragments": [
                    {
                        "fragment_id": fragment.fragment_id,
                        "source_ref": fragment.source_ref,
                        "order": fragment.order,
                        "text_start": fragment.text_start,
                        "text_end": fragment.text_end,
                        "text_hash": fragment.text_hash,
                        "stored_text_hash": hash_text(
                            self._fragment_text.get(fragment.fragment_id, "")
                        ),
                        "active": fragment.active,
                    }
                    for fragment in fragments
                ],
            }

    def open_request(
        self,
        request_kind: str,
        ordered_source_refs: Sequence[str],
        merged_source: str,
        prompt_config_material,
    ) -> str:
        references = tuple(ordered_source_refs)
        if not references or len(references) != len(set(references)):
            raise ValueError("request source refs must be non-empty and unique")
        with self._lock:
            unknown = [
                reference for reference in references if reference not in self.sources
            ]
            if unknown:
                raise KeyError(f"request names unregistered source refs: {unknown}")
            material = {
                "canonicalization_version": CANONICALIZATION_VERSION,
                "request_kind": request_kind,
                "ordered_source_refs": references,
                "merged_source_hash": hash_text(merged_source),
                "prompt_config_hash": hash_record(prompt_config_material),
            }
            request_id = f"request-{hash_record(material)}"
            existing = self.requests.get(request_id)
            if existing is not None:
                return request_id
            request = RequestRecord(
                request_id=request_id,
                request_kind=request_kind,
                ordered_source_refs=references,
                merged_source_hash=material["merged_source_hash"],
                prompt_config_hash=material["prompt_config_hash"],
            )
            self.requests[request_id] = request
            for reference in references:
                self.sources[reference].request_ids.add(request_id)
            return request_id

    def record_translator_call(self, request_id: str) -> None:
        with self._lock:
            request = self._request(request_id)
            if request.status != REQUEST_OPEN:
                raise ValueError("translator calls can only be recorded on open requests")
            request.translator_call_count += 1

    def record_chain_outcome(
        self,
        chain_id: str,
        ordered_source_refs: Sequence[str],
        result_state: ChainResultState | str,
        *,
        request_id: str | None,
        translator_call_count: int,
        issue: str | None = None,
    ) -> None:
        """Record one terminal chain result, including zero-request failures."""
        references = tuple(ordered_source_refs)
        state = ChainResultState(result_state)
        if not chain_id:
            raise ValueError("chain outcome requires a stable chain id")
        if not references or len(references) != len(set(references)):
            raise ValueError("chain outcome source refs must be non-empty and unique")
        if translator_call_count not in (0, 1):
            raise ValueError("a confirmed chain can make at most one translator call")
        with self._lock:
            if chain_id in self.chain_outcomes:
                raise ValueError(f"chain outcome registered twice: {chain_id}")
            unknown = [
                reference for reference in references if reference not in self.sources
            ]
            if unknown:
                raise KeyError(
                    f"chain outcome names unregistered source refs: {unknown}"
                )
            request = None if request_id is None else self._request(request_id)
            if request is not None:
                if request.ordered_source_refs != references:
                    raise ValueError("chain outcome refs must equal its request refs")
                if request.translator_call_count != translator_call_count:
                    raise ValueError("chain outcome call count must equal its request")
            if state == ChainResultState.JOINT_SUCCESS:
                if request is None or request.status != REQUEST_COMPLETED:
                    raise ValueError("a successful chain requires a completed request")
                if translator_call_count != 1:
                    raise ValueError("a successful chain requires exactly one call")
            elif state == ChainResultState.PROTECTED_UNTRANSLATED:
                if request is not None or translator_call_count != 0:
                    raise ValueError("a protected chain must stop before its request")
                for reference in references:
                    self._set_terminal(reference, SourceTerminalState.PROTECTED, issue)
            else:
                if request is not None and request.status != REQUEST_FAILED:
                    raise ValueError("a failed chain request must be marked failed")
                if request is None and translator_call_count != 0:
                    raise ValueError("a failed chain call requires its request record")
                for reference in references:
                    if not self._source_has_rendered_geometry(reference):
                        self._set_terminal(
                            reference, SourceTerminalState.FAILED_WITH_ISSUE, issue
                        )
            self.chain_outcomes[chain_id] = ChainOutcomeRecord(
                chain_id=chain_id,
                ordered_source_refs=references,
                result_state=state,
                request_id=request_id,
                translator_call_count=translator_call_count,
                issue=issue,
            )

    def register_whole_target(self, request_id: str, target: str) -> str:
        with self._lock:
            request = self._request(request_id)
            if request.status != REQUEST_OPEN:
                raise ValueError("whole targets can only be registered on open requests")
            canonical = canonical_text(target)
            digest = hash_text(canonical)
            if request.whole_target_hash not in (None, digest):
                raise ValueError("a request can only own one whole target")
            request.whole_target_hash = digest
            request.whole_target_chars = len(canonical)
            self._whole_targets[request_id] = canonical
            return digest

    def allocate_target_fragment(
        self,
        request_id: str,
        source_reference: str,
        *,
        order: int,
        text_start: int,
        text_end: int,
        text: str,
        generation: int = 0,
        slot_id: str | None = None,
        render_ref: str | None = None,
        render_page: int | None = None,
        measurement_summary: Mapping | None = None,
        released: bool = False,
    ) -> str:
        with self._lock:
            request = self._request(request_id)
            if request.status != REQUEST_OPEN:
                raise ValueError("fragments can only be allocated on open requests")
            if source_reference not in request.ordered_source_refs:
                raise ValueError("fragment source must belong to its request")
            if generation not in self.generations:
                raise KeyError(f"unknown generation: {generation}")
            if self.generations[generation].status == GENERATION_ROLLED_BACK:
                raise ValueError("cannot allocate into a rolled-back generation")
            target = self._whole_targets.get(request_id)
            if target is None:
                raise ValueError("register the whole target before its fragments")
            canonical = canonical_text(text)
            if order < 0 or text_start < 0 or text_end < text_start:
                raise ValueError("fragment order and range must be non-negative")
            if slot_id is not None and not slot_id:
                raise ValueError("fragment slot id must be non-empty when provided")
            if render_ref is not None:
                parse_source_ref(render_ref)
            if render_page is not None and render_page < 1:
                raise ValueError("fragment render page must be positive")
            if released and text_start != text_end:
                raise ValueError("a released slot cannot consume target text")
            if text_end > len(target) or target[text_start:text_end] != canonical:
                raise ValueError("fragment text must equal its whole-target range")
            held = [
                self.fragments[fragment_id]
                for fragment_id in request.fragment_ids
                if self.fragments[fragment_id].active
            ]
            if any(fragment.order == order for fragment in held):
                raise ValueError("fragment order must be unique within a request")
            if any(
                text_start < fragment.text_end and fragment.text_start < text_end
                for fragment in held
            ):
                raise ValueError("target fragment ranges must not overlap")
            material = {
                "request_id": request_id,
                "source_ref": source_reference,
                "order": order,
                "text_range": [text_start, text_end],
                "text_hash": hash_text(canonical),
                "generation": generation,
            }
            if slot_id is not None:
                material["slot_id"] = slot_id
            if released:
                material["allocation_status"] = ALLOCATION_RELEASED
            fragment_id = f"fragment-{hash_record(material)}"
            if fragment_id in self.fragments:
                return fragment_id
            fragment = FragmentRecord(
                fragment_id=fragment_id,
                request_id=request_id,
                source_ref=source_reference,
                order=order,
                text_start=text_start,
                text_end=text_end,
                text_hash=material["text_hash"],
                allocation_status=(
                    ALLOCATION_RELEASED if released else ALLOCATION_ALLOCATED
                ),
                generation=generation,
                slot_id=slot_id,
                render_ref=render_ref,
                render_page=render_page,
                measurement_summary=dict(measurement_summary or {}),
                active=not released,
                terminal_state=(
                    SourceTerminalState.PROTECTED if released else None
                ),
                terminal_issue="released_target_slot" if released else None,
            )
            self.fragments[fragment_id] = fragment
            self._fragment_text[fragment_id] = canonical
            request.fragment_ids.add(fragment_id)
            self.sources[source_reference].fragment_ids.add(fragment_id)
            self.generations[generation].fragment_ids.append(fragment_id)
            return fragment_id

    def replace_request_fragments(
        self,
        generation: int,
        request_id: str,
        allocations: Sequence[Mapping],
    ) -> tuple[str, ...]:
        """Replace one completed request's allocation inside an open transaction."""
        with self._lock:
            generation_record = self._generation(generation)
            if generation_record.status != GENERATION_OPEN:
                raise ValueError("fragment replacement requires an open generation")
            request = self._request(request_id)
            if request.status != REQUEST_COMPLETED:
                raise ValueError("only completed requests can be reallocated")
            snapshots = self._generation_request_snapshots.setdefault(generation, {})
            if request_id in snapshots:
                raise ValueError("a request can be replaced once per generation")
            old_ids = set(request.fragment_ids)
            snapshots[request_id] = old_ids
            fragment_snapshots = self._generation_fragment_snapshots.setdefault(
                generation, {}
            )
            for fragment_id in old_ids:
                fragment = self.fragments[fragment_id]
                fragment_snapshots[fragment_id] = (
                    fragment.active,
                    fragment.allocation_status,
                    fragment.terminal_state,
                    fragment.terminal_issue,
                )
                fragment.active = False
                fragment.allocation_status = ALLOCATION_INACTIVE
                generation_record.replaced_fragment_ids.append(fragment_id)

            target = self._whole_targets[request_id]
            request.fragment_ids = set()
            created = []
            cursor = 0
            for order, allocation in enumerate(allocations):
                source_reference = str(allocation["source_ref"])
                if source_reference not in request.ordered_source_refs:
                    raise ValueError("replacement source must belong to its request")
                start = int(allocation["text_start"])
                end = int(allocation["text_end"])
                text = canonical_text(str(allocation["text"]))
                released = bool(allocation.get("released", False))
                if start != cursor or end < start or target[start:end] != text:
                    raise ValueError("replacement ranges must tile the whole target")
                if released and start != end:
                    raise ValueError("released replacement cannot consume target text")
                render_ref = allocation.get("render_ref")
                render_page = allocation.get("render_page")
                if render_ref is not None:
                    parse_source_ref(str(render_ref))
                if render_page is not None and int(render_page) < 1:
                    raise ValueError("replacement render page must be positive")
                material = {
                    "request_id": request_id,
                    "source_ref": source_reference,
                    "order": order,
                    "text_range": [start, end],
                    "text_hash": hash_text(text),
                    "generation": generation,
                    "slot_id": allocation.get("slot_id"),
                    "render_ref": render_ref,
                }
                fragment_id = f"fragment-{hash_record(material)}"
                if fragment_id in self.fragments:
                    raise ValueError("replacement fragment id already exists")
                fragment = FragmentRecord(
                    fragment_id=fragment_id,
                    request_id=request_id,
                    source_ref=source_reference,
                    order=order,
                    text_start=start,
                    text_end=end,
                    text_hash=material["text_hash"],
                    allocation_status=(
                        ALLOCATION_RELEASED if released else ALLOCATION_ALLOCATED
                    ),
                    generation=generation,
                    slot_id=allocation.get("slot_id"),
                    render_ref=None if render_ref is None else str(render_ref),
                    render_page=None if render_page is None else int(render_page),
                    measurement_summary=dict(
                        allocation.get("measurement_summary", {})
                    ),
                    active=not released,
                    terminal_state=(
                        SourceTerminalState.PROTECTED if released else None
                    ),
                    terminal_issue="released_target_slot" if released else None,
                )
                self.fragments[fragment_id] = fragment
                self._fragment_text[fragment_id] = text
                request.fragment_ids.add(fragment_id)
                self.sources[source_reference].fragment_ids.add(fragment_id)
                generation_record.fragment_ids.append(fragment_id)
                created.append(fragment_id)
                cursor = end
            if cursor != len(target):
                raise ValueError("replacement ranges stop before the whole target")
            self._validate_target(request)
            return tuple(created)

    def record_flow_slot(
        self,
        generation: int,
        *,
        slot_id: str,
        article_id: str,
        page: int,
        status: str,
        box: Sequence[float] | None,
        source_ref: str | None = None,
        render_ref: str | None = None,
        previous_page: int | None = None,
        previous_slot_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Record an allocated, released, or protected article-flow region."""
        with self._lock:
            record = self._generation(generation)
            if record.status != GENERATION_OPEN:
                raise ValueError("flow slots require an open generation")
            if not slot_id or slot_id in self.flow_slots:
                raise ValueError("flow slot ids must be new and non-empty")
            if source_ref is not None and source_ref not in self.sources:
                raise ValueError("flow slot source must be registered")
            if render_ref is not None:
                parse_source_ref(render_ref)
            if previous_page is not None and previous_page <= 0:
                raise ValueError("flow slot previous page must be positive")
            if previous_slot_id == "":
                raise ValueError("flow slot previous id cannot be empty")
            if (
                source_ref is not None
                and previous_page is not None
                and self.sources[source_ref].page != previous_page
            ):
                raise ValueError("flow slot previous page disagrees with its source")
            self.flow_slots[slot_id] = FlowSlotRecord(
                slot_id=slot_id,
                article_id=article_id,
                page=page,
                status=status,
                box=_checked_box(box),
                source_ref=source_ref,
                render_ref=render_ref,
                previous_page=previous_page,
                previous_slot_id=previous_slot_id,
                reason=reason,
                generation=generation,
            )
            record.flow_slot_ids.append(slot_id)

    def complete_request(self, request_id: str) -> None:
        with self._lock:
            request = self._request(request_id)
            if request.status != REQUEST_OPEN:
                raise ValueError("only an open request can complete")
            self._validate_target(request)
            request.status = REQUEST_COMPLETED

    def complete_request_with_fragments(
        self,
        request_id: str,
        fragments: Sequence[tuple[str, str]],
        *,
        generation: int = 0,
    ) -> list[str]:
        canonical_fragments = [
            (reference, canonical_text(text)) for reference, text in fragments
        ]
        whole_target = "".join(text for _reference, text in canonical_fragments)
        self.register_whole_target(request_id, whole_target)
        cursor = 0
        fragment_ids = []
        for order, (reference, text) in enumerate(canonical_fragments):
            end = cursor + len(text)
            fragment_ids.append(
                self.allocate_target_fragment(
                    request_id,
                    reference,
                    order=order,
                    text_start=cursor,
                    text_end=end,
                    text=text,
                    generation=generation,
                )
            )
            cursor = end
        self.complete_request(request_id)
        return fragment_ids

    def fail_request(self, request_id: str, issue: str) -> None:
        with self._lock:
            request = self._request(request_id)
            if request.status == REQUEST_COMPLETED:
                raise ValueError("a completed request cannot fail")
            request.status = REQUEST_FAILED
            request.issue = issue
            for fragment_id in request.fragment_ids:
                fragment = self.fragments[fragment_id]
                fragment.allocation_status = ALLOCATION_FAILED
                fragment.active = False
                fragment.terminal_state = SourceTerminalState.FAILED_WITH_ISSUE
                fragment.terminal_issue = issue
            for reference in request.ordered_source_refs:
                if not self._source_has_rendered_geometry(reference):
                    self._set_terminal(
                        reference, SourceTerminalState.FAILED_WITH_ISSUE, issue
                    )

    def rollback_completed_chain(
        self, chain_id: str, request_id: str, issue: str
    ) -> None:
        """Invalidate a completed chain after transactional writeback fails."""
        with self._lock:
            request = self._request(request_id)
            outcome = self.chain_outcomes.get(chain_id)
            if request.status != REQUEST_COMPLETED:
                raise ValueError("only a completed chain request can roll back")
            if (
                outcome is None
                or outcome.request_id != request_id
                or outcome.result_state != ChainResultState.JOINT_SUCCESS
            ):
                raise ValueError("completed chain outcome does not match its request")
            request.status = REQUEST_FAILED
            request.issue = issue
            for fragment_id in request.fragment_ids:
                fragment = self.fragments[fragment_id]
                fragment.allocation_status = ALLOCATION_FAILED
                fragment.active = False
                fragment.terminal_state = SourceTerminalState.FAILED_WITH_ISSUE
                fragment.terminal_issue = issue
            for reference in request.ordered_source_refs:
                source = self.sources[reference]
                if source.terminal_state != SourceTerminalState.RENDERED:
                    source.terminal_state = SourceTerminalState.FAILED_WITH_ISSUE
                    source.terminal_issue = issue
            outcome.result_state = ChainResultState.FAILED_WITH_ISSUE
            outcome.issue = issue

    def mark_source_protected(self, reference: str, reason: str) -> None:
        with self._lock:
            self._set_terminal(reference, SourceTerminalState.PROTECTED, reason)

    def mark_source_failed(self, reference: str, issue: str) -> None:
        with self._lock:
            self._set_terminal(
                reference, SourceTerminalState.FAILED_WITH_ISSUE, issue
            )

    def mark_fragment_protected(self, fragment_id: str, reason: str) -> None:
        with self._lock:
            fragment = self._fragment(fragment_id)
            fragment.terminal_state = SourceTerminalState.PROTECTED
            fragment.terminal_issue = reason
            self._set_terminal(
                fragment.source_ref, SourceTerminalState.PROTECTED, reason
            )

    def register_typeset_geometry(
        self,
        fragment_id: str,
        *,
        slot_id: str,
        pre_repair_box: Sequence[float] | None,
        font_summary: Mapping | None = None,
        color_summary: Mapping | None = None,
        generation: int = 0,
        final_page: int | None = None,
        final_box: Sequence[float] | None = None,
        render_status: str = RENDER_PENDING,
    ) -> str:
        with self._lock:
            fragment = self._fragment(fragment_id)
            if not fragment.active:
                raise ValueError("inactive fragments cannot receive geometry")
            generation_record = self.generations.get(generation)
            if generation_record is None:
                raise KeyError(f"unknown generation: {generation}")
            if generation_record.status == GENERATION_ROLLED_BACK:
                raise ValueError("cannot write geometry into a rolled-back generation")
            material = {
                "fragment_id": fragment_id,
                "slot_id": slot_id,
                "generation": generation,
            }
            geometry_id = f"geometry-{hash_record(material)}"
            existing = self.geometries.get(geometry_id)
            if existing is not None:
                existing.pre_repair_box = _checked_box(pre_repair_box)
                existing.final_page = final_page
                existing.final_box = _checked_box(final_box)
                existing.font_summary = dict(font_summary or {})
                existing.color_summary = dict(color_summary or {})
                existing.render_status = render_status
                existing.active = True
                return geometry_id
            previous = self._active_geometry(fragment_id)
            if previous is not None:
                previous.active = False
                previous.render_status = RENDER_INACTIVE
                if previous.binding_id is not None:
                    fragment.terminal_state = None
                    fragment.terminal_issue = None
                    source = self.sources[fragment.source_ref]
                    source.terminal_state = None
                    source.terminal_issue = None
            geometry = GeometryRecord(
                geometry_id=geometry_id,
                fragment_id=fragment_id,
                slot_id=slot_id,
                generation=generation,
                pre_repair_box=_checked_box(pre_repair_box),
                final_page=final_page,
                final_box=_checked_box(final_box),
                font_summary=dict(font_summary or {}),
                color_summary=dict(color_summary or {}),
                render_status=render_status,
                replaces_geometry_id=None
                if previous is None
                else previous.geometry_id,
            )
            self.geometries[geometry_id] = geometry
            fragment.geometry_ids.add(geometry_id)
            generation_record.geometry_ids.append(geometry_id)
            return geometry_id

    def capture_typeset_document(self, document) -> None:
        """Register the post-typesetting, pre-repair slot for each target fragment."""
        with self._lock:
            for fragment in self._active_fragments():
                render_ref = fragment.render_ref or fragment.source_ref
                paragraph = self._paragraph(document, render_ref)
                if paragraph is None:
                    continue
                fonts, colors = _font_color_summary(paragraph)
                slot_id = fragment.slot_id or (
                    f"slot-{hash_record({'source_ref': fragment.source_ref})}"
                )
                self.register_typeset_geometry(
                    fragment.fragment_id,
                    slot_id=slot_id,
                    pre_repair_box=_box_tuple(getattr(paragraph, "box", None)),
                    font_summary=fonts,
                    color_summary=colors,
                )

    def begin_repair_generation(self, reason: str) -> int:
        with self._lock:
            self.current_generation += 1
            self.generations[self.current_generation] = GenerationRecord(
                self.current_generation, reason, GENERATION_OPEN
            )
            return self.current_generation

    def transaction_snapshot(self) -> dict:
        """State needed to restore a failed mutation without trace residue."""
        names = (
            "sources",
            "requests",
            "chain_outcomes",
            "fragments",
            "geometries",
            "flow_slots",
            "generations",
            "current_generation",
            "unsupported_pages",
            "blocked_reasons",
            "drop_cap_events",
            "_source_objects",
            "_whole_targets",
            "_fragment_text",
            "_generation_request_snapshots",
            "_generation_fragment_snapshots",
        )
        with self._lock:
            return {name: copy.deepcopy(getattr(self, name)) for name in names}

    def restore_transaction_snapshot(self, snapshot: dict) -> None:
        """Restore a state produced by :meth:`transaction_snapshot` exactly."""
        with self._lock:
            for name, value in snapshot.items():
                setattr(self, name, copy.deepcopy(value))

    def transaction_digest(self) -> str:
        """Digest of the externally observable trace generation and lineage."""
        return hash_record(self.to_record())

    def transaction_allocator_digest(self) -> str:
        """Digest of active request allocation state used by flow transactions."""
        with self._lock:
            return hash_record(
                {
                    "requests": {
                        request_id: sorted(request.fragment_ids)
                        for request_id, request in sorted(self.requests.items())
                    },
                    "fragments": {
                        fragment_id: {
                            "active": fragment.active,
                            "allocation_status": fragment.allocation_status,
                            "generation": fragment.generation,
                            "slot_id": fragment.slot_id,
                            "render_ref": fragment.render_ref,
                            "render_page": fragment.render_page,
                        }
                        for fragment_id, fragment in sorted(self.fragments.items())
                    },
                }
            )

    def capture_repair_document(
        self,
        document,
        generation: int,
        source_refs: Iterable[str] | None = None,
    ) -> list[str]:
        """Write pending geometry only for fragments whose box changed."""
        selected = None if source_refs is None else set(source_refs)
        written = []
        with self._lock:
            for fragment in self._active_fragments():
                if selected is not None and fragment.source_ref not in selected:
                    continue
                render_ref = fragment.render_ref or fragment.source_ref
                paragraph = self._paragraph(document, render_ref)
                if paragraph is None:
                    continue
                previous = self._active_geometry(fragment.fragment_id)
                current_box = _box_tuple(getattr(paragraph, "box", None))
                previous_box = None
                if previous is not None:
                    previous_box = previous.final_box or previous.pre_repair_box
                if previous is not None and current_box == previous_box:
                    continue
                fonts, colors = _font_color_summary(paragraph)
                slot_id = (
                    previous.slot_id
                    if previous is not None
                    else f"slot-{hash_record({'source_ref': fragment.source_ref})}"
                )
                written.append(
                    self.register_typeset_geometry(
                        fragment.fragment_id,
                        slot_id=slot_id,
                        pre_repair_box=previous_box,
                        final_page=(
                            fragment.render_page
                            or self.sources[fragment.source_ref].page
                        ),
                        final_box=current_box,
                        font_summary=fonts,
                        color_summary=colors,
                        generation=generation,
                    )
                )
        return written

    def commit_generation(self, generation: int) -> None:
        with self._lock:
            record = self._generation(generation)
            if record.status != GENERATION_OPEN:
                raise ValueError("only an open generation can commit")
            record.status = GENERATION_COMMITTED

    def rollback_generation(self, generation: int) -> None:
        with self._lock:
            record = self._generation(generation)
            if generation == 0:
                raise ValueError("the base typeset generation cannot roll back")
            if record.status == GENERATION_ROLLED_BACK:
                return
            for geometry_id in reversed(record.geometry_ids):
                geometry = self.geometries[geometry_id]
                geometry.active = False
                geometry.render_status = RENDER_INACTIVE
                previous_id = geometry.replaces_geometry_id
                if previous_id is not None:
                    previous = self.geometries[previous_id]
                    previous.active = True
                    if previous.binding_id is not None:
                        previous.render_status = RENDER_RENDERED
                        source_reference = self.fragments[
                            previous.fragment_id
                        ].source_ref
                        self.fragments[
                            previous.fragment_id
                        ].terminal_state = SourceTerminalState.RENDERED
                        self.fragments[previous.fragment_id].terminal_issue = None
                        self._set_terminal(
                            source_reference, SourceTerminalState.RENDERED, None
                        )
                    else:
                        previous.render_status = RENDER_PENDING
            for fragment_id in reversed(record.fragment_ids):
                fragment = self.fragments[fragment_id]
                fragment.active = False
                fragment.allocation_status = ALLOCATION_INACTIVE
            for slot_id in record.flow_slot_ids:
                self.flow_slots[slot_id].active = False
            snapshots = self._generation_request_snapshots.get(generation, {})
            fragment_snapshots = self._generation_fragment_snapshots.get(
                generation, {}
            )
            for request_id, fragment_ids in snapshots.items():
                self.requests[request_id].fragment_ids = set(fragment_ids)
            for fragment_id, snapshot in fragment_snapshots.items():
                fragment = self.fragments[fragment_id]
                (
                    fragment.active,
                    fragment.allocation_status,
                    fragment.terminal_state,
                    fragment.terminal_issue,
                ) = snapshot
            record.status = GENERATION_ROLLED_BACK

    def rollback_generations_after(self, generation: int) -> None:
        with self._lock:
            for candidate in sorted(self.generations, reverse=True):
                if candidate > generation:
                    self.rollback_generation(candidate)

    def rollback_open_generations(self) -> None:
        with self._lock:
            for generation in sorted(self.generations, reverse=True):
                if self.generations[generation].status == GENERATION_OPEN:
                    self.rollback_generation(generation)

    def record_blocked_reason(self, issue: Mapping) -> None:
        """Retain one structured prerequisite failure in the run ledger."""
        row = dict(issue)
        with self._lock:
            if hash_record(row) not in {
                hash_record(existing) for existing in self.blocked_reasons
            }:
                self.blocked_reasons.append(row)

    def record_drop_cap_event(self, event: Mapping) -> None:
        """Append one source-style, intent, flatten, or target-style event."""
        row = dict(event)
        reference = row.get("source_ref")
        if reference not in self.sources:
            raise ValueError(f"drop-cap event names unknown source {reference!r}")
        with self._lock:
            self.drop_cap_events.append(row)

    def bind_final_pdf_compliance(self, result: Mapping) -> None:
        row = dict(result)
        if row.get("status") not in {"pass", "degraded", "fail"}:
            raise ValueError("final PDF compliance has an invalid status")
        with self._lock:
            self.final_pdf_compliance = row

    def bind_final_geometry(
        self,
        fragment_id: str,
        *,
        final_page: int,
        final_box: Sequence[float],
        binding_id: str,
        binding_kind: str = "pdf_block",
        span_ids: Sequence[str] = (),
        font_summary: Mapping | None = None,
        color_summary: Mapping | None = None,
    ) -> str:
        with self._lock:
            geometry = self._active_geometry(fragment_id)
            if geometry is None:
                raise ValueError("final geometry requires an active typeset slot")
            geometry.final_page = final_page
            geometry.final_box = _checked_box(final_box)
            geometry.binding_id = binding_id
            geometry.binding_kind = binding_kind
            geometry.span_ids = tuple(span_ids)
            if font_summary is not None:
                geometry.font_summary = dict(font_summary)
            if color_summary is not None:
                geometry.color_summary = dict(color_summary)
            geometry.render_status = RENDER_RENDERED
            fragment = self.fragments[fragment_id]
            fragment.terminal_state = SourceTerminalState.RENDERED
            fragment.terminal_issue = None
            source_reference = fragment.source_ref
            self._set_terminal(
                source_reference, SourceTerminalState.RENDERED, None
            )
            return geometry.geometry_id

    def capture_final_document(self, document) -> None:
        """Bind active slots to the paragraph blocks emitted by PDFCreater."""
        with self._lock:
            for fragment in self._active_fragments():
                render_ref = fragment.render_ref or fragment.source_ref
                paragraph = self._paragraph(document, render_ref)
                if paragraph is None:
                    fragment.terminal_state = SourceTerminalState.FAILED_WITH_ISSUE
                    fragment.terminal_issue = "source_missing_at_final_binding"
                    self.mark_source_failed(
                        fragment.source_ref, "source_missing_at_final_binding"
                    )
                    continue
                characters = _composition_characters(paragraph)
                boxes = [
                    _box_tuple(getattr(character, "box", None))
                    for character in characters
                ]
                final_box = _union_box(boxes)
                if not characters or final_box is None:
                    fragment.terminal_state = SourceTerminalState.FAILED_WITH_ISSUE
                    fragment.terminal_issue = "no_renderable_pdf_block"
                    self.mark_source_failed(
                        fragment.source_ref, "no_renderable_pdf_block"
                    )
                    continue
                page = fragment.render_page or self.sources[fragment.source_ref].page
                binding_material = {
                    "fragment_id": fragment.fragment_id,
                    "page": page,
                    "box": final_box,
                }
                binding_id = f"pdf-block-{hash_record(binding_material)}"
                span_ids = tuple(
                    f"{binding_id}:span:{index}" for index, _character in enumerate(characters)
                )
                fonts, colors = _font_color_summary(paragraph)
                self.bind_final_geometry(
                    fragment.fragment_id,
                    final_page=page,
                    final_box=final_box,
                    binding_id=binding_id,
                    span_ids=span_ids,
                    font_summary=fonts,
                    color_summary=colors,
                )

    def finalize_sources(self) -> None:
        """Assign one explicit terminal state to every registered source."""
        with self._lock:
            for fragment in self._active_fragments():
                geometry = self._active_geometry(fragment.fragment_id)
                if (
                    geometry is not None
                    and geometry.render_status == RENDER_RENDERED
                ):
                    fragment.terminal_state = SourceTerminalState.RENDERED
                    fragment.terminal_issue = None
                elif fragment.terminal_state is None:
                    fragment.terminal_state = SourceTerminalState.FAILED_WITH_ISSUE
                    fragment.terminal_issue = "target_not_bound_to_final_geometry"
            for reference, source in self.sources.items():
                if self._source_has_rendered_geometry(reference):
                    self._set_terminal(reference, SourceTerminalState.RENDERED, None)
                elif source.terminal_state is not None:
                    continue
                elif not source.request_ids:
                    self._set_terminal(
                        reference,
                        SourceTerminalState.PROTECTED,
                        "not_submitted_for_translation",
                    )
                else:
                    self._set_terminal(
                        reference,
                        SourceTerminalState.FAILED_WITH_ISSUE,
                        "target_not_bound_to_final_geometry",
                    )

    def trace_from_source(
        self, reference: str, *, include_inactive: bool = False
    ) -> dict:
        with self._lock:
            source = self.sources[reference]
            requests = []
            for request_id in sorted(source.request_ids):
                request = self.requests[request_id]
                fragments = []
                for fragment_id in sorted(request.fragment_ids):
                    fragment = self.fragments[fragment_id]
                    if fragment.source_ref != reference:
                        continue
                    if not include_inactive and not fragment.active:
                        continue
                    geometries = [
                        self.geometries[geometry_id].to_record()
                        for geometry_id in sorted(fragment.geometry_ids)
                        if include_inactive or self.geometries[geometry_id].active
                    ]
                    fragments.append(
                        {**fragment.to_record(), "geometry": geometries}
                    )
                requests.append({**request.to_record(), "fragments": fragments})
            return {"source": source.to_record(), "requests": requests}

    def trace_from_geometry(self, geometry_or_binding_id: str) -> dict:
        with self._lock:
            geometry = self.geometries.get(geometry_or_binding_id)
            if geometry is None:
                geometry = next(
                    (
                        candidate
                        for candidate in self.geometries.values()
                        if candidate.binding_id == geometry_or_binding_id
                        or geometry_or_binding_id in candidate.span_ids
                    ),
                    None,
                )
            if geometry is None:
                raise KeyError(geometry_or_binding_id)
            fragment = self.fragments[geometry.fragment_id]
            request = self.requests[fragment.request_id]
            return {
                "geometry": geometry.to_record(),
                "fragment": fragment.to_record(),
                "request": request.to_record(),
                "sources": [
                    self.sources[reference].to_record()
                    for reference in request.ordered_source_refs
                ],
            }

    def trace_from_final_geometry(
        self, final_page: int, final_box: Sequence[float]
    ) -> dict:
        """Reverse an exact final PDF block box to its translation lineage."""
        wanted_box = _checked_box(final_box)
        with self._lock:
            matches = [
                geometry
                for geometry in self.geometries.values()
                if geometry.active
                and geometry.final_page == final_page
                and geometry.final_box == wanted_box
            ]
            if len(matches) != 1:
                raise KeyError(
                    f"final geometry matched {len(matches)} trace records"
                )
            return self.trace_from_geometry(matches[0].geometry_id)

    def validate(self, *, require_terminal: bool = False) -> None:
        with self._lock:
            for request in self.requests.values():
                if not request.ordered_source_refs or len(
                    request.ordered_source_refs
                ) != len(set(request.ordered_source_refs)):
                    raise ValueError("request source refs must be non-empty and unique")
                if any(reference not in self.sources for reference in request.ordered_source_refs):
                    raise ValueError("request contains an unregistered source ref")
                if request.status == REQUEST_COMPLETED:
                    self._validate_target(request)
            for outcome in self.chain_outcomes.values():
                if any(
                    reference not in self.sources
                    for reference in outcome.ordered_source_refs
                ):
                    raise ValueError(
                        "chain outcome contains an unregistered source ref"
                    )
                request = (
                    None
                    if outcome.request_id is None
                    else self.requests.get(outcome.request_id)
                )
                if request is not None:
                    if request.ordered_source_refs != outcome.ordered_source_refs:
                        raise ValueError("chain outcome and request source refs differ")
                    if request.translator_call_count != outcome.translator_call_count:
                        raise ValueError("chain outcome and request call counts differ")
                if outcome.result_state == ChainResultState.JOINT_SUCCESS and (
                    request is None or request.status != REQUEST_COMPLETED
                ):
                    raise ValueError(
                        "successful chain outcome lacks a completed request"
                    )
                protected = (
                    outcome.result_state
                    == ChainResultState.PROTECTED_UNTRANSLATED
                )
                if protected and (
                    request is not None or outcome.translator_call_count != 0
                ):
                    raise ValueError(
                        "protected chain outcome crossed the request boundary"
                    )
                if (
                    outcome.result_state == ChainResultState.FAILED_WITH_ISSUE
                    and request is None
                    and outcome.translator_call_count != 0
                ):
                    raise ValueError("failed chain call lacks its request record")
            active_by_fragment: dict[str, int] = {}
            for fragment in self.fragments.values():
                if fragment.request_id not in self.requests:
                    raise ValueError("fragment points to an unknown request")
                if fragment.source_ref not in self.requests[
                    fragment.request_id
                ].ordered_source_refs:
                    raise ValueError("fragment source is outside its request")
                if fragment.active:
                    active_by_fragment[fragment.fragment_id] = 0
            for geometry in self.geometries.values():
                if geometry.fragment_id not in self.fragments:
                    raise ValueError("geometry points to an unknown fragment")
                if geometry.active:
                    fragment = self.fragments[geometry.fragment_id]
                    if not fragment.active:
                        raise ValueError("active geometry points to an inactive fragment")
                    active_by_fragment[geometry.fragment_id] = (
                        active_by_fragment.get(geometry.fragment_id, 0) + 1
                    )
            if any(count > 1 for count in active_by_fragment.values()):
                raise ValueError("a fragment can have only one active geometry")
            for slot in self.flow_slots.values():
                if slot.generation not in self.generations:
                    raise ValueError("flow slot points to an unknown generation")
                if slot.source_ref is not None and slot.source_ref not in self.sources:
                    raise ValueError("flow slot points to an unknown source")
                if (
                    slot.source_ref is not None
                    and slot.previous_page is not None
                    and self.sources[slot.source_ref].page != slot.previous_page
                ):
                    raise ValueError("flow slot movement starts on the wrong page")
            for generation in self.generations.values():
                if generation.status != GENERATION_ROLLED_BACK:
                    continue
                if any(self.fragments[item].active for item in generation.fragment_ids):
                    raise ValueError("rolled-back fragments must be inactive")
                if any(self.geometries[item].active for item in generation.geometry_ids):
                    raise ValueError("rolled-back geometry must be inactive")
                if any(self.flow_slots[item].active for item in generation.flow_slot_ids):
                    raise ValueError("rolled-back flow slots must be inactive")
            if require_terminal:
                missing = [
                    reference
                    for reference, source in self.sources.items()
                    if source.terminal_state is None
                ]
                if missing:
                    raise ValueError(f"sources lack a terminal state: {missing}")
                missing_fragments = [
                    fragment.fragment_id
                    for fragment in self._active_fragments()
                    if fragment.terminal_state is None
                ]
                if missing_fragments:
                    raise ValueError(
                        f"fragments lack a terminal state: {missing_fragments}"
                    )
                for fragment in self._active_fragments():
                    if (
                        fragment.terminal_state == SourceTerminalState.RENDERED
                        and not any(
                            self.geometries[geometry_id].active
                            and self.geometries[geometry_id].render_status
                            == RENDER_RENDERED
                            for geometry_id in fragment.geometry_ids
                        )
                    ):
                        raise ValueError(
                            "rendered fragment has no active final geometry"
                        )
                for reference, source in self.sources.items():
                    if (
                        source.terminal_state == SourceTerminalState.RENDERED
                        and not self._source_has_rendered_geometry(reference)
                    ):
                        raise ValueError("rendered source has no active final geometry")

    def to_record(self) -> dict:
        with self._lock:
            source_to_requests = {
                reference: sorted(source.request_ids)
                for reference, source in sorted(self.sources.items())
            }
            article_to_sources: dict[str, list[str]] = {}
            chain_to_sources: dict[str, list[str]] = {}
            for reference, source in sorted(self.sources.items()):
                if source.article_id is not None:
                    article_to_sources.setdefault(source.article_id, []).append(
                        reference
                    )
                if source.chain_id is not None:
                    chain_to_sources.setdefault(source.chain_id, []).append(reference)
            request_to_fragments = {
                request_id: sorted(request.fragment_ids)
                for request_id, request in sorted(self.requests.items())
            }
            fragment_to_geometry = {
                fragment_id: sorted(fragment.geometry_ids)
                for fragment_id, fragment in sorted(self.fragments.items())
            }
            geometry_to_fragment = {
                geometry_id: geometry.fragment_id
                for geometry_id, geometry in sorted(self.geometries.items())
            }
            binding_to_geometry = {
                geometry.binding_id: geometry_id
                for geometry_id, geometry in sorted(self.geometries.items())
                if geometry.binding_id is not None
            }
            span_to_geometry = {
                span_id: geometry_id
                for geometry_id, geometry in sorted(self.geometries.items())
                for span_id in geometry.span_ids
            }
            return {
                "schema_version": SCHEMA_VERSION,
                "canonicalization": {
                    "version": CANONICALIZATION_VERSION,
                    "text": "UTF-8 with CRLF and CR canonicalized to LF",
                    "records": "sorted-key compact JSON encoded as UTF-8",
                },
                "source_ref_freeze_stage": SOURCE_REF_FREEZE_STAGE,
                "sources": [
                    source.to_record()
                    for _reference, source in sorted(self.sources.items())
                ],
                "requests": [
                    request.to_record()
                    for _request_id, request in sorted(self.requests.items())
                ],
                "chain_outcomes": [
                    outcome.to_record()
                    for _chain_id, outcome in sorted(self.chain_outcomes.items())
                ],
                "fragments": [
                    fragment.to_record()
                    for _fragment_id, fragment in sorted(self.fragments.items())
                ],
                "geometry": [
                    geometry.to_record()
                    for _geometry_id, geometry in sorted(self.geometries.items())
                ],
                "flow_slots": [
                    slot.to_record()
                    for _slot_id, slot in sorted(self.flow_slots.items())
                ],
                "repair_generations": [
                    generation.to_record()
                    for _number, generation in sorted(self.generations.items())
                ],
                "unsupported_pages": sorted(self.unsupported_pages),
                "blocked_reasons": [
                    dict(reason)
                    for reason in sorted(
                        self.blocked_reasons, key=lambda item: canonical_json_bytes(item)
                    )
                ],
                "drop_cap_events": [dict(event) for event in self.drop_cap_events],
                **(
                    {}
                    if self.final_pdf_compliance is None
                    else {"final_pdf_compliance": dict(self.final_pdf_compliance)}
                ),
                "indexes": {
                    "article_to_sources": article_to_sources,
                    "chain_to_sources": chain_to_sources,
                    "source_to_requests": source_to_requests,
                    "request_to_fragments": request_to_fragments,
                    "fragment_to_geometry": fragment_to_geometry,
                    "geometry_to_fragment": geometry_to_fragment,
                    "final_binding_to_geometry": binding_to_geometry,
                    "final_span_to_geometry": span_to_geometry,
                },
            }

    def to_json_bytes(self) -> bytes:
        self.validate()
        return (
            json.dumps(
                self.to_record(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            )
            + "\n"
        ).encode("utf-8")

    def write(self, path: str | Path, *, require_terminal: bool = False) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.validate(require_terminal=require_terminal)
        destination.write_bytes(self.to_json_bytes())
        return destination

    def _request(self, request_id: str) -> RequestRecord:
        try:
            return self.requests[request_id]
        except KeyError as error:
            raise KeyError(f"unknown request: {request_id}") from error

    def _fragment(self, fragment_id: str) -> FragmentRecord:
        try:
            return self.fragments[fragment_id]
        except KeyError as error:
            raise KeyError(f"unknown fragment: {fragment_id}") from error

    def _generation(self, generation: int) -> GenerationRecord:
        try:
            return self.generations[generation]
        except KeyError as error:
            raise KeyError(f"unknown generation: {generation}") from error

    def _validate_target(self, request: RequestRecord) -> None:
        if request.translator_call_count < 1:
            raise ValueError("completed request must record a translator call")
        target = self._whole_targets.get(request.request_id)
        if target is None or request.whole_target_hash != hash_text(target):
            raise ValueError("completed request must retain its whole target hash")
        fragments = sorted(
            (
                self.fragments[fragment_id]
                for fragment_id in request.fragment_ids
            ),
            key=lambda fragment: fragment.order,
        )
        if not fragments:
            raise ValueError("completed request must allocate target fragments")
        cursor = 0
        joined = []
        for expected_order, fragment in enumerate(fragments):
            if fragment.order != expected_order:
                raise ValueError("target fragment orders must be contiguous")
            if fragment.text_start != cursor:
                raise ValueError("target fragment ranges must not contain gaps")
            text = self._fragment_text.get(fragment.fragment_id)
            if text is None or hash_text(text) != fragment.text_hash:
                raise ValueError("target fragment hash does not match its text")
            joined.append(text)
            cursor = fragment.text_end
        if cursor != len(target) or "".join(joined) != target:
            raise ValueError("target fragments must exactly reconstruct the whole target")

    def _active_fragments(self) -> list[FragmentRecord]:
        return sorted(
            (fragment for fragment in self.fragments.values() if fragment.active),
            key=lambda fragment: (
                self.sources[fragment.source_ref].page,
                self.sources[fragment.source_ref].index,
                fragment.order,
                fragment.fragment_id,
            ),
        )

    def _active_geometry(self, fragment_id: str) -> GeometryRecord | None:
        active = [
            self.geometries[geometry_id]
            for geometry_id in self.fragments[fragment_id].geometry_ids
            if self.geometries[geometry_id].active
        ]
        if len(active) > 1:
            raise ValueError("a fragment has more than one active geometry")
        return None if not active else active[0]

    def _paragraph(self, document, reference: str):
        page, index = parse_source_ref(reference)
        if page > len(document.page):
            return None
        paragraphs = document.page[page - 1].pdf_paragraph or ()
        if index >= len(paragraphs):
            return None
        return paragraphs[index]

    def _source_has_rendered_geometry(self, reference: str) -> bool:
        return any(
            geometry.active and geometry.render_status == RENDER_RENDERED
            for fragment_id in self.sources[reference].fragment_ids
            if self.fragments[fragment_id].active
            for geometry_id in self.fragments[fragment_id].geometry_ids
            for geometry in (self.geometries[geometry_id],)
        )

    def _set_terminal(
        self,
        reference: str,
        state: SourceTerminalState,
        issue: str | None,
    ) -> None:
        source = self.sources[reference]
        if source.terminal_state == SourceTerminalState.RENDERED and state != source.terminal_state:
            return
        if state == SourceTerminalState.RENDERED:
            source.terminal_state = state
            source.terminal_issue = None
            return
        if source.terminal_state is None:
            source.terminal_state = state
            source.terminal_issue = issue
