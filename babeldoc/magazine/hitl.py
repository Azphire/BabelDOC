"""Minimal two-pass human review for the fixed magazine pipeline."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from pathlib import Path

from babeldoc.glossary import Glossary
from babeldoc.glossary import GlossaryEntry
from babeldoc.magazine import drop_cap
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import load_taxonomy

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = config_path("hitl.json")
SOURCE_REVIEWS_DIR = ROOT / "reviews"
GENERATED_REVIEWS_DIR = ROOT / ".runtime" / "reviews-generated"

REVIEW_SUFFIX = ".review.json"
DECISIONS_SUFFIX = ".decisions.json"
REPORT_NAME = "hitl_apply.report.json"

TERMS_SECTION = "terms"
PAGE_KINDS_SECTION = "page_kinds"
DROP_CAPS_SECTION = "drop_caps"
METADATA_KEYS = ("format_version", "sample")
HUMAN_SOURCE = "human"
HUMAN_CONF = 1.0
DECISIONS_GLOSSARY = "hitl_decisions"
OUT_OF_SELECTED_SCOPE = "out_of_selected_scope"

_CONFIG_KEY_VERSION = "review_format_version"
_CONFIG_KEY_SECTIONS = "sections"
_CONFIG_KEY_DROP_CAP_DECISIONS = "drop_cap_decisions"
_CONFIG_KEY_TRANSLATOR_VIEW_CHARS = "translator_view_chars"
_CONFIG_KEY_MATCHED_EXCERPTS = "matched_prompt_excerpts"
_REFERENCE_RE = re.compile(r"p([1-9][0-9]*)#([0-9]+)\Z")


class HitlError(ValueError):
    """Raised when fixed HITL state or a decisions file is invalid."""


@dataclass(frozen=True, slots=True)
class DropCapRuling:
    reference: str
    physical_page: int
    paragraph_index: int
    decision: str
    raw: object
    source_text_hash: str | None = None


@dataclass(frozen=True, slots=True)
class Decisions:
    path: Path
    terms: dict[str, str]
    page_kinds: dict[int, str]
    drop_caps: dict[str, DropCapRuling]


@dataclass(frozen=True, slots=True)
class GlossaryFreezeEvidence:
    sha256: str
    glossary_object_ids: tuple[int, ...]
    names: tuple[str, ...]
    entry_count: int

    def as_record(self) -> dict:
        return {
            "sha256": self.sha256,
            "names": list(self.names),
            "entry_count": self.entry_count,
        }


@dataclass(slots=True)
class HitlRunState:
    """The two-pass state explicitly owned by one MagazineState."""

    docs_identity: int
    sample: str
    total_pages: int
    selected_physical_pages: tuple[int, ...]
    physical_to_local: dict[int, int]
    translator_identity: int
    term_translator_identity: int
    pipeline_ready: bool
    decisions_loaded: bool = False
    decisions: Decisions | None = None
    page_pass_started: bool = False
    page_pass_completed: bool = False
    translation_pass_started: bool = False
    translation_pass_completed: bool = False
    draft: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)
    glossary_freeze: GlossaryFreezeEvidence | None = None


@lru_cache(maxsize=1)
def load_hitl_config(path: str | None = None) -> dict:
    """Load the bounded vocabulary shared with the drop-cap pass."""
    source = CONFIG_PATH if path is None else Path(path)
    with source.open(encoding="utf-8") as file:
        raw = json.load(file)
    try:
        parameters = dict(validate_bounded_config(raw, source))
    except ConfigError as exc:
        raise HitlError(str(exc)) from exc
    required = (
        _CONFIG_KEY_VERSION,
        _CONFIG_KEY_SECTIONS,
        _CONFIG_KEY_DROP_CAP_DECISIONS,
        _CONFIG_KEY_TRANSLATOR_VIEW_CHARS,
        _CONFIG_KEY_MATCHED_EXCERPTS,
    )
    missing = [key for key in required if key not in parameters]
    if missing:
        raise HitlError(f"{source.name}: missing {missing}")
    declared = parameters[_CONFIG_KEY_SECTIONS]
    for section in (TERMS_SECTION, PAGE_KINDS_SECTION, DROP_CAPS_SECTION):
        if section not in declared:
            raise HitlError(f"{source.name}: sections omits {section}")
    return parameters


def sections() -> tuple[str, ...]:
    return tuple(load_hitl_config()[_CONFIG_KEY_SECTIONS])


def sample_name(translation_config) -> str:
    return Path(translation_config.input_file).stem


def source_review_path(sample: str) -> Path:
    return SOURCE_REVIEWS_DIR / f"{sample}{REVIEW_SUFFIX}"


def decisions_path(sample: str) -> Path:
    return SOURCE_REVIEWS_DIR / f"{sample}{DECISIONS_SUFFIX}"


def page_label(page, position: int) -> int:
    """Return the one-based physical page label used by review files."""
    index = page.page_number if page.page_number is not None else position
    return int(index) + 1


def labeled_pages(docs) -> list[tuple[int, object]]:
    return [
        (page_label(page, position), page) for position, page in enumerate(docs.page)
    ]


def begin_run(translation_config, docs) -> HitlRunState:
    labeled = labeled_pages(docs)
    labels = tuple(label for label, _page in labeled)
    if len(labels) != len(set(labels)):
        raise HitlError("selected pages have duplicate physical labels")
    total_pages = int(getattr(docs, "total_pages", 0) or 0)
    if total_pages <= 0:
        total_pages = max(labels, default=0)
    if any(label < 1 or label > total_pages for label in labels):
        raise HitlError("selected physical page is outside document total_pages")
    sample = sample_name(translation_config)
    translator = getattr(translation_config, "translator", None)
    term_getter = getattr(translation_config, "get_term_extraction_translator", None)
    shared = getattr(translation_config, "shared_context_cross_split_part", None)
    pipeline_ready = (
        translator is not None and callable(term_getter) and shared is not None
    )
    term_translator = term_getter() if pipeline_ready else None
    draft = {
        "format_version": load_hitl_config()[_CONFIG_KEY_VERSION],
        "sample": sample,
        **{section: [] for section in sections()},
    }
    report = {
        "sample": sample,
        "decisions_file": None,
        "applied": {
            TERMS_SECTION: None,
            PAGE_KINDS_SECTION: [],
            DROP_CAPS_SECTION: [],
        },
        "skipped": [],
        "passes": {"page_kinds": False, "before_translation": False},
    }
    return HitlRunState(
        docs_identity=id(docs),
        sample=sample,
        total_pages=total_pages,
        selected_physical_pages=labels,
        physical_to_local={label: index + 1 for index, label in enumerate(labels)},
        translator_identity=id(translator),
        term_translator_identity=id(term_translator),
        pipeline_ready=pipeline_ready,
        draft=draft,
        report=report,
    )


def _require_object(raw: object, section: str, faults: list[str]) -> dict:
    if raw is None or raw == []:
        return {}
    if not isinstance(raw, dict):
        faults.append(f"section {section!r} must be an object")
        return {}
    return raw


def _validate_terms(raw: object, faults: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    normalized: dict[str, str] = {}
    for source, target in _require_object(raw, TERMS_SECTION, faults).items():
        where = f"{TERMS_SECTION}[{source!r}]"
        if not isinstance(source, str) or not isinstance(target, str):
            faults.append(f"{where}: source and target must be strings")
            continue
        if not source.strip() or not target.strip():
            faults.append(f"{where}: source and target must be non-empty")
            continue
        if source != source.strip() or target != target.strip():
            faults.append(f"{where}: source and target must not be padded")
            continue
        key = Glossary.normalize_source(source)
        if key in normalized:
            faults.append(f"{where}: collides with {normalized[key]!r}")
            continue
        normalized[key] = source
        result[source] = target
    return result


def _validate_page_kinds(
    raw: object,
    total_pages: int,
    faults: list[str],
) -> dict[int, str]:
    result: dict[int, str] = {}
    vocabulary = set(load_taxonomy().names())
    for key, kind in _require_object(raw, PAGE_KINDS_SECTION, faults).items():
        where = f"{PAGE_KINDS_SECTION}[{key!r}]"
        if not isinstance(key, str) or not key.isdecimal():
            faults.append(f"{where}: page must be a decimal integer")
            continue
        page = int(key)
        if str(page) != key or not 1 <= page <= total_pages:
            faults.append(f"{where}: page is outside 1..{total_pages}")
            continue
        if not isinstance(kind, str) or kind not in vocabulary:
            faults.append(f"{where}: {kind!r} is not a declared page type")
            continue
        result[page] = kind
    return result


def _drop_cap_value(
    reference: str,
    raw: object,
    verdicts: tuple[str, ...],
    faults: list[str],
) -> tuple[str | None, str | None]:
    where = f"{DROP_CAPS_SECTION}[{reference!r}]"
    if isinstance(raw, str):
        decision = raw
        source_hash = None
    elif isinstance(raw, dict):
        full_fields = {
            "decision",
            "candidate_id",
            "source_ref",
            "source_text_fingerprint",
            "source_style_hash",
            "config_version",
            "decision_version",
        }
        simple_fields = (
            {"decision"},
            {"decision", "source_hash"},
            {"decision", "source_text_hash"},
        )
        if set(raw) == full_fields:
            try:
                drop_cap.parse_manual_decision(reference, raw, verdicts)
            except drop_cap.DropCapError as exc:
                faults.append(f"{where}: {exc}")
                return None, None
            decision = raw["decision"]
            source_hash = None
        elif set(raw) in simple_fields:
            decision = raw["decision"]
            source_hash = raw.get("source_text_hash", raw.get("source_hash"))
            if source_hash is not None and (
                not isinstance(source_hash, str) or not source_hash
            ):
                faults.append(f"{where}: source hash must be a non-empty string")
                return None, None
        else:
            faults.append(f"{where}: decision object has unsupported fields")
            return None, None
    else:
        faults.append(f"{where}: decision must be a string or object")
        return None, None
    if decision not in verdicts:
        faults.append(f"{where}: {decision!r} is outside {sorted(verdicts)}")
        return None, None
    return decision, source_hash


def _validate_drop_caps(
    raw: object,
    state: HitlRunState,
    docs,
    faults: list[str],
) -> dict[str, DropCapRuling]:
    selected = dict(labeled_pages(docs))
    verdicts = tuple(load_hitl_config()[_CONFIG_KEY_DROP_CAP_DECISIONS])
    result: dict[str, DropCapRuling] = {}
    for reference, raw_value in _require_object(
        raw, DROP_CAPS_SECTION, faults
    ).items():
        where = f"{DROP_CAPS_SECTION}[{reference!r}]"
        if not isinstance(reference, str):
            faults.append(f"{where}: paragraph reference must be a string")
            continue
        match = _REFERENCE_RE.fullmatch(reference)
        if match is None:
            faults.append(f"{where}: paragraph reference must match pN#K")
            continue
        page = int(match.group(1))
        index = int(match.group(2))
        if not 1 <= page <= state.total_pages:
            faults.append(f"{where}: page is outside 1..{state.total_pages}")
            continue
        decision, source_hash = _drop_cap_value(
            reference, raw_value, verdicts, faults
        )
        if decision is None:
            continue
        selected_page = selected.get(page)
        if selected_page is not None and index >= len(selected_page.pdf_paragraph or ()):
            faults.append(f"{where}: no such paragraph on selected page")
            continue
        result[reference] = DropCapRuling(
            reference=reference,
            physical_page=page,
            paragraph_index=index,
            decision=decision,
            raw=raw_value,
            source_text_hash=source_hash,
        )
    return result


def _load_decisions(state: HitlRunState, docs) -> Decisions | None:
    if state.decisions_loaded:
        return state.decisions
    state.decisions_loaded = True
    path = decisions_path(state.sample)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HitlError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise HitlError(f"{path}: top level must be an object")
    faults: list[str] = []
    declared = set(sections()) | set(METADATA_KEYS)
    for key in raw:
        if key not in declared:
            faults.append(f"{key!r} is not a declared decisions section")
    sample = raw.get("sample")
    if sample is not None and sample != state.sample:
        faults.append(f"sample {sample!r} does not bind input {state.sample!r}")
    terms = _validate_terms(raw.get(TERMS_SECTION), faults)
    page_kinds = _validate_page_kinds(
        raw.get(PAGE_KINDS_SECTION), state.total_pages, faults
    )
    drop_caps = _validate_drop_caps(raw.get(DROP_CAPS_SECTION), state, docs, faults)
    if faults:
        detail = "\n  ".join(faults)
        raise HitlError(f"{path}: {len(faults)} fault(s), file rejected:\n  {detail}")
    decisions = Decisions(path, terms, page_kinds, drop_caps)
    state.decisions = decisions
    state.report["decisions_file"] = str(path)
    return decisions


def export_page_kinds(docs) -> list[dict]:
    return [
        {
            "page": page_label(page, position),
            "machine_kind": page.page_kind,
            "conf": page.page_kind_conf,
            "source": page.page_kind_source,
        }
        for position, page in enumerate(docs.page)
    ]


def _term_votes(shared_context) -> dict[str, int]:
    votes: dict[str, int] = {}
    for source, _target in shared_context.raw_extracted_terms:
        votes[source] = votes.get(source, 0) + 1
    return votes


def export_terms(translation_config, docs) -> list[dict]:
    shared = translation_config.shared_context_cross_split_part
    targets = {}
    if shared.auto_extracted_glossary is not None:
        targets = {
            Glossary.normalize_source(entry.source): entry.target
            for entry in shared.auto_extracted_glossary.entries
        }
    votes = _term_votes(shared)
    first_pages: dict[str, int | None] = dict.fromkeys(votes)
    for position, page in enumerate(docs.page):
        text = "\n".join(
            paragraph.unicode or "" for paragraph in (page.pdf_paragraph or ())
        )
        for source, first_page in tuple(first_pages.items()):
            if first_page is None and source in text:
                first_pages[source] = page_label(page, position)
    rows = [
        {
            "source": source,
            "observed_target": targets.get(Glossary.normalize_source(source)),
            "vote_count": count,
            "first_page": first_pages[source],
        }
        for source, count in votes.items()
    ]
    rows.sort(
        key=lambda row: (
            row["first_page"] is None,
            row["first_page"] or 0,
            row["source"],
        )
    )
    return rows


def _unique_glossary_name(base: str, existing: list[Glossary]) -> str:
    taken = {glossary.name for glossary in existing}
    name = base
    suffix = 0
    while name in taken:
        suffix += 1
        name = f"{base}#{suffix}"
    return name


def apply_terms(translation_config, decisions: Decisions | None) -> dict | None:
    ruled = {} if decisions is None else decisions.terms
    if not ruled:
        return None
    shared = translation_config.shared_context_cross_split_part
    by_key = {
        Glossary.normalize_source(source): (source, target)
        for source, target in ruled.items()
    }
    dropped: list[dict] = []
    relocated: str | None = None
    kept_count = 0
    auto = shared.auto_extracted_glossary
    if auto is not None:
        kept: list[GlossaryEntry] = []
        for entry in auto.entries:
            ruling = by_key.get(Glossary.normalize_source(entry.source))
            if ruling is None:
                kept.append(entry)
            else:
                dropped.append(
                    {
                        "source": entry.source,
                        "auto_target": entry.target,
                        "human_target": ruling[1],
                    }
                )
        shared.auto_extracted_glossary = None
        if kept:
            shared.user_glossaries.append(Glossary(auto.name, kept))
            relocated = auto.name
            kept_count = len(kept)
    name = _unique_glossary_name(DECISIONS_GLOSSARY, shared.user_glossaries)
    shared.user_glossaries.append(
        Glossary(
            name,
            [GlossaryEntry(source, target) for source, target in ruled.items()],
        )
    )
    return {
        "glossary": name,
        "entries": [
            {"source": source, "target": target, "decided_by": HUMAN_SOURCE}
            for source, target in ruled.items()
        ],
        "ruled": len(ruled),
        "dropped_from_auto": dropped,
        "auto_glossary_relocated": relocated,
        "auto_glossary_kept": kept_count,
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_machine_review(translation_config, state: HitlRunState) -> None:
    working = Path(
        translation_config.get_working_file_path(f"{state.sample}{REVIEW_SUFFIX}")
    )
    _write_json(working, state.draft)
    if not source_review_path(state.sample).exists():
        _write_json(
            GENERATED_REVIEWS_DIR / f"{state.sample}{REVIEW_SUFFIX}", state.draft
        )


def _write_report(translation_config, state: HitlRunState) -> None:
    _write_json(
        Path(translation_config.get_working_file_path(REPORT_NAME)), state.report
    )


def _scope_records(state: HitlRunState, decisions: Decisions | None) -> list[dict]:
    if decisions is None:
        return []
    selected = set(state.selected_physical_pages)
    records = [
        {
            "section": PAGE_KINDS_SECTION,
            "key": str(page),
            "page": page,
            "reason": OUT_OF_SELECTED_SCOPE,
        }
        for page in decisions.page_kinds
        if page not in selected
    ]
    records.extend(
        {
            "section": DROP_CAPS_SECTION,
            "key": reference,
            "page": ruling.physical_page,
            "reason": OUT_OF_SELECTED_SCOPE,
        }
        for reference, ruling in decisions.drop_caps.items()
        if ruling.physical_page not in selected
    )
    return records


def page_kind_pass(
    translation_config,
    docs,
    state: HitlRunState,
) -> None:
    if state.page_pass_started:
        raise HitlError("HITL page-kind pass was already attempted")
    state.page_pass_started = True
    if state.docs_identity != id(docs):
        raise HitlError("HITL state belongs to a different document")
    if not state.pipeline_ready:
        state.report["inactive_reason"] = "structure_only_config"
        state.report["passes"]["page_kinds"] = True
        state.page_pass_completed = True
        return
    decisions = _load_decisions(state, docs)
    state.draft[PAGE_KINDS_SECTION] = export_page_kinds(docs)
    _write_machine_review(translation_config, state)
    state.report["skipped"] = _scope_records(state, decisions)
    applied: list[dict] = []
    if decisions is not None:
        for position, page in enumerate(docs.page):
            physical = page_label(page, position)
            kind = decisions.page_kinds.get(physical)
            if kind is None:
                continue
            applied.append(
                {
                    "page": physical,
                    "machine_kind": page.page_kind,
                    "machine_conf": page.page_kind_conf,
                    "machine_source": page.page_kind_source,
                    "kind": kind,
                }
            )
            page.page_kind = kind
            page.page_kind_conf = HUMAN_CONF
            page.page_kind_source = HUMAN_SOURCE
    state.report["applied"][PAGE_KINDS_SECTION] = applied
    state.report["passes"]["page_kinds"] = True
    _write_report(translation_config, state)
    state.page_pass_completed = True


def _canonical_element(
    article_document_ir: ArticleDocumentIR,
    source_ref: str,
):
    for article in article_document_ir.articles:
        for element in article.elements:
            if element.source_ref == source_ref:
                return element
    return None


def _selected_drop_cap_decisions(
    translation_config,
    state: HitlRunState,
    article_document_ir: ArticleDocumentIR,
) -> dict[str, object]:
    decisions = state.decisions
    if decisions is None:
        return {}
    selected = set(state.selected_physical_pages)
    raw: dict[str, object] = {}
    for reference, ruling in decisions.drop_caps.items():
        if ruling.physical_page not in selected:
            continue
        local_page = state.physical_to_local[ruling.physical_page]
        local_ref = f"p{local_page}#{ruling.paragraph_index}"
        element = _canonical_element(article_document_ir, local_ref)
        if element is None:
            raise HitlError(
                f"{reference}: selected paragraph is absent from canonical ArticleDocumentIR"
            )
        if (
            ruling.source_text_hash is not None
            and ruling.source_text_hash != element.source_text_hash
        ):
            raise HitlError(f"{reference}: source text hash does not match canonical IR")
        raw[reference] = (
            ruling.raw
            if isinstance(ruling.raw, dict) and "candidate_id" in ruling.raw
            else ruling.decision
        )
    try:
        return drop_cap.validate_manual_decisions(translation_config, raw)
    except drop_cap.DropCapError as exc:
        raise HitlError(str(exc)) from exc


def _freeze_glossaries(translation_config) -> GlossaryFreezeEvidence:
    shared = translation_config.shared_context_cross_split_part
    glossaries = shared.get_glossaries_for_translation(
        translation_config.auto_extract_glossary
    )
    records = [
        {
            "name": glossary.name,
            "entries": [
                {
                    "source": entry.source,
                    "target": entry.target,
                    "target_language": entry.target_language,
                }
                for entry in glossary.entries
            ],
        }
        for glossary in glossaries
    ]
    payload = json.dumps(
        records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return GlossaryFreezeEvidence(
        sha256=hashlib.sha256(payload).hexdigest(),
        glossary_object_ids=tuple(id(glossary) for glossary in glossaries),
        names=tuple(glossary.name for glossary in glossaries),
        entry_count=sum(len(glossary.entries) for glossary in glossaries),
    )


def _restore_dataclass(target, snapshot) -> None:
    for name in target.__dataclass_fields__:
        setattr(target, name, copy.deepcopy(getattr(snapshot, name)))


class _BeforeTranslationTransaction:
    """Rollback every in-memory mutation made while preparing translation."""

    def __init__(self, translation_config, docs, state: HitlRunState):
        self._translation_config = translation_config
        self._pages = [(page, copy.deepcopy(page)) for page in docs.page]
        self._shared = translation_config.shared_context_cross_split_part
        self._user_glossaries_ref = self._shared.user_glossaries
        self._user_glossaries = list(self._shared.user_glossaries)
        self._auto_glossary = self._shared.auto_extracted_glossary
        self._intent_generation = drop_cap_intent.current_generation(
            translation_config
        )
        self._intents = copy.deepcopy(
            list(drop_cap_intent.intents_for(translation_config).values())
        )
        self._state = state
        self._draft_ref = state.draft
        self._draft = copy.deepcopy(state.draft)
        self._report_ref = state.report
        self._report = copy.deepcopy(state.report)
        self._glossary_freeze = state.glossary_freeze
        self._translation_pass_completed = state.translation_pass_completed
        self._committed = False

    def __enter__(self):
        return self

    def commit(self) -> None:
        self._committed = True

    def _restore_intents(self) -> None:
        drop_cap_intent.clear(self._translation_config)
        for generation in range(1, self._intent_generation + 1):
            intents = (
                copy.deepcopy(self._intents)
                if generation == self._intent_generation
                else []
            )
            drop_cap_intent.replace_intents(self._translation_config, intents)

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is not None or not self._committed:
            for page, snapshot in self._pages:
                _restore_dataclass(page, snapshot)
            self._user_glossaries_ref[:] = self._user_glossaries
            self._shared.user_glossaries = self._user_glossaries_ref
            self._shared.auto_extracted_glossary = self._auto_glossary
            self._restore_intents()
            self._draft_ref.clear()
            self._draft_ref.update(copy.deepcopy(self._draft))
            self._state.draft = self._draft_ref
            self._report_ref.clear()
            self._report_ref.update(copy.deepcopy(self._report))
            self._state.report = self._report_ref
            self._state.glossary_freeze = self._glossary_freeze
            self._state.translation_pass_completed = (
                self._translation_pass_completed
            )
        return False


def before_translation(
    translation_config,
    docs,
    article_document_ir: ArticleDocumentIR,
    state: HitlRunState,
) -> dict:
    if state.translation_pass_started or state.glossary_freeze is not None:
        raise HitlError("HITL before-translation pass was already attempted")
    state.translation_pass_started = True
    if state.docs_identity != id(docs):
        raise HitlError("HITL state belongs to a different document")
    if not state.page_pass_completed:
        raise HitlError("HITL page-kind pass did not complete")
    if not state.pipeline_ready:
        state.report["passes"]["before_translation"] = True
        state.translation_pass_completed = True
        return state.report
    if id(translation_config.translator) != state.translator_identity:
        raise HitlError("translation client identity changed before HITL freeze")
    if (
        id(translation_config.get_term_extraction_translator())
        != state.term_translator_identity
    ):
        raise HitlError("term-translation client identity changed before HITL freeze")

    with _BeforeTranslationTransaction(
        translation_config, docs, state
    ) as transaction:
        labeled = labeled_pages(docs)
        candidates = drop_cap.mark(
            translation_config,
            labeled,
            article_document_ir=article_document_ir,
        )
        selected_decisions = _selected_drop_cap_decisions(
            translation_config, state, article_document_ir
        )
        state.draft[TERMS_SECTION] = export_terms(translation_config, docs)
        state.draft[DROP_CAPS_SECTION] = drop_cap.review_rows(
            candidates, translation_config
        )
        _write_machine_review(translation_config, state)

        terms_record = apply_terms(translation_config, state.decisions)
        drop_records = drop_cap.apply_decisions(
            translation_config, labeled, selected_decisions
        )
        apply_record = drop_cap.apply(translation_config, labeled)
        freeze = _freeze_glossaries(translation_config)

        if id(translation_config.translator) != state.translator_identity:
            raise HitlError("translation client identity changed during HITL freeze")
        if (
            id(translation_config.get_term_extraction_translator())
            != state.term_translator_identity
        ):
            raise HitlError(
                "term-translation client identity changed during HITL freeze"
            )
        state.glossary_freeze = freeze
        state.report["applied"][TERMS_SECTION] = terms_record
        state.report["applied"][DROP_CAPS_SECTION] = drop_records
        state.report["drop_cap_apply"] = apply_record
        state.report["glossary_freeze"] = freeze.as_record()
        state.report["passes"]["before_translation"] = True
        _write_report(translation_config, state)
        state.translation_pass_completed = True
        transaction.commit()
    return state.report
