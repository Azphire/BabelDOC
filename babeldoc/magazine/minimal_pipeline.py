"""Fixed orchestration for the minimal magazine structure pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from babeldoc.magazine import article_flow
from babeldoc.magazine import drop_cap_render
from babeldoc.magazine import hitl
from babeldoc.magazine import indent_policy
from babeldoc.magazine import paren_dedup
from babeldoc.magazine.article_builder import ArticleBuilder
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.chain_builder import ChainBuilder
from babeldoc.magazine.page_classifier import PageClassifier


class MinimalPipelineStateError(RuntimeError):
    """Raised when the fixed pipeline state is missing or reused."""


@dataclass(slots=True)
class MagazineState:
    """The one in-memory state object owned by a translation run."""

    _article_document_ir: ArticleDocumentIR | None = None
    _structure_started: bool = False
    _structure_document_identity: int | None = None
    _hitl_state: hitl.HitlRunState | None = None
    _translation_prep_started: bool = False
    _translation_prep_completed: bool = False
    _flow_started: bool = False
    _flow_completed: bool = False
    _flow_document_identity: int | None = None
    _flow_report: dict | None = None
    _typesetter_identity: int | None = None
    _render_started: bool = False
    _render_completed: bool = False
    _render_document_identity: int | None = None
    _render_report: dict | None = None

    @property
    def article_document_ir(self) -> ArticleDocumentIR | None:
        return self._article_document_ir

    @property
    def structure_started(self) -> bool:
        return self._structure_started

    @property
    def structure_document_identity(self) -> int | None:
        return self._structure_document_identity

    @property
    def hitl_state(self) -> hitl.HitlRunState | None:
        return self._hitl_state

    @property
    def hitl_report(self) -> dict | None:
        return None if self._hitl_state is None else self._hitl_state.report

    @property
    def glossary_freeze(self) -> hitl.GlossaryFreezeEvidence | None:
        return None if self._hitl_state is None else self._hitl_state.glossary_freeze

    @property
    def translation_prep_started(self) -> bool:
        return self._translation_prep_started

    @property
    def translation_prep_completed(self) -> bool:
        return self._translation_prep_completed

    @property
    def flow_started(self) -> bool:
        return self._flow_started

    @property
    def flow_completed(self) -> bool:
        return self._flow_completed

    @property
    def flow_document_identity(self) -> int | None:
        return self._flow_document_identity

    @property
    def flow_report(self) -> dict | None:
        return self._flow_report

    @property
    def typesetter_identity(self) -> int | None:
        return self._typesetter_identity

    @property
    def render_started(self) -> bool:
        return self._render_started

    @property
    def render_completed(self) -> bool:
        return self._render_completed

    @property
    def render_document_identity(self) -> int | None:
        return self._render_document_identity

    @property
    def render_report(self) -> dict | None:
        return self._render_report


_FIXED_TRUE_ATTRIBUTES = (
    "magazine_page_classify",
    "magazine_chain_detect",
    "magazine_chain_translate",
    "magazine_article_group",
    "magazine_article_context",
    "magazine_hitl_apply",
    "magazine_hitl_export",
    "magazine_detect",
    "magazine_column_reflow",
    "magazine_drop_cap_apply",
    "magazine_drop_cap_mark",
    "magazine_drop_cap_render",
    "magazine_formula_reclass",
    "magazine_fragment_stitch",
    "magazine_indent_policy",
    "magazine_line_structure",
    "magazine_paren_dedup",
)

_FIXED_FALSE_ATTRIBUTES = (
    "magazine_checkpoint",
    "magazine_pdf_compliance",
    "magazine_repair",
    "magazine_rotated_lane",
    "magazine_title_typeset",
    "magazine_profile",
    "magazine_mode",
    "magazine_runtime_profile",
)

_MISSING = object()


def configure(config) -> None:
    """Configure one run for the fixed path and create its unique state."""
    if getattr(config, "magazine_state", _MISSING) is not _MISSING:
        raise MinimalPipelineStateError("magazine pipeline state is already configured")

    fixed = {
        **dict.fromkeys(_FIXED_TRUE_ATTRIBUTES, True),
        **dict.fromkeys(_FIXED_FALSE_ATTRIBUTES, False),
    }
    for name, expected in fixed.items():
        current = getattr(config, name, _MISSING)
        if current is not _MISSING and current is not expected:
            raise MinimalPipelineStateError(
                f"conflicting fixed pipeline attribute {name}"
            )

    for name, value in fixed.items():
        setattr(config, name, value)
    config.magazine_state = MagazineState()


def _state(config) -> MagazineState:
    state = getattr(config, "magazine_state", None)
    if not isinstance(state, MagazineState):
        raise MinimalPipelineStateError("magazine pipeline is not configured")
    return state


def after_styles(config, docs) -> ArticleDocumentIR:
    """Build page, chain, and canonical article structure exactly once."""
    state = _state(config)
    if state._structure_started or state._article_document_ir is not None:
        raise MinimalPipelineStateError(
            "canonical ArticleDocumentIR construction was already attempted"
        )

    state._structure_started = True
    state._structure_document_identity = id(docs)

    classifier = PageClassifier(config)
    if classifier.vlm_enabled:
        raise MinimalPipelineStateError(
            "VLM page classification must remain disabled in the minimal pipeline"
        )
    classifier.process(docs)
    hitl_state = hitl.begin_run(config, docs)
    state._hitl_state = hitl_state
    hitl.page_kind_pass(config, docs, hitl_state)
    ChainBuilder(config).process(docs)

    article_document_ir = ArticleBuilder(config).process(docs)
    if not isinstance(article_document_ir, ArticleDocumentIR):
        raise MinimalPipelineStateError(
            "ArticleBuilder did not return an ArticleDocumentIR"
        )
    state._article_document_ir = article_document_ir
    return article_document_ir


def before_translation(config, docs) -> dict:
    """Freeze HITL terms and drop-cap intent exactly once before translation."""
    state = _state(config)
    if state._translation_prep_started:
        raise MinimalPipelineStateError("translation preparation was already attempted")
    state._translation_prep_started = True
    article_document_ir = get_article_document_ir(config)
    if state.structure_document_identity != id(docs):
        raise MinimalPipelineStateError(
            "canonical ArticleDocumentIR belongs to a different document"
        )
    hitl_state = state.hitl_state
    if hitl_state is None:
        raise MinimalPipelineStateError("HITL state is not available")

    report = hitl.before_translation(
        config,
        docs,
        article_document_ir,
        hitl_state,
    )
    if state.article_document_ir is not article_document_ir:
        raise MinimalPipelineStateError("canonical ArticleDocumentIR identity changed")
    state._translation_prep_completed = True
    return report


def get_article_document_ir(config) -> ArticleDocumentIR:
    """Return the exact canonical object stored for this run."""
    article_document_ir = _state(config).article_document_ir
    if article_document_ir is None:
        raise MinimalPipelineStateError("canonical ArticleDocumentIR is not available")
    return article_document_ir


def after_translation(config, docs, typesetter) -> dict:
    """Run the fixed target-normalization and article-flow path exactly once."""
    state = _state(config)
    article_document_ir = get_article_document_ir(config)
    if state.structure_document_identity != id(docs):
        raise MinimalPipelineStateError(
            "canonical ArticleDocumentIR belongs to a different document"
        )
    if state._flow_started:
        raise MinimalPipelineStateError("article flow was already attempted")
    if getattr(typesetter, "translation_config", None) is not config:
        raise MinimalPipelineStateError(
            "article flow typesetter belongs to a different translation config"
        )

    state._flow_started = True
    state._flow_document_identity = id(docs)
    state._typesetter_identity = id(typesetter)
    paren_dedup.apply(config, docs)
    indent_policy.apply(config, docs, article_document_ir)
    report = article_flow.apply(
        config,
        docs,
        article_document_ir,
        typesetter=typesetter,
    )
    if not isinstance(report, dict):
        raise MinimalPipelineStateError("fixed article flow did not return a report")
    if state.article_document_ir is not article_document_ir:
        raise MinimalPipelineStateError("canonical ArticleDocumentIR identity changed")
    state._flow_report = report
    state._flow_completed = True
    return report


def after_typesetting(config, docs, typesetter) -> dict:
    """Render frozen drop-cap intents once after formal typesetting."""
    state = _state(config)
    if state._render_started:
        raise MinimalPipelineStateError("drop-cap render was already attempted")
    state._render_started = True
    state._render_document_identity = id(docs)
    article_document_ir = get_article_document_ir(config)
    if not state.translation_prep_completed:
        raise MinimalPipelineStateError("translation preparation did not complete")
    if not state.flow_completed:
        raise MinimalPipelineStateError("article flow did not complete")
    if state.structure_document_identity != id(docs):
        raise MinimalPipelineStateError(
            "canonical ArticleDocumentIR belongs to a different document"
        )
    if state.flow_document_identity != id(docs):
        raise MinimalPipelineStateError("article flow belongs to a different document")
    if state.typesetter_identity != id(typesetter):
        raise MinimalPipelineStateError("formal typesetter identity changed")
    if getattr(typesetter, "translation_config", None) is not config:
        raise MinimalPipelineStateError(
            "drop-cap renderer typesetter belongs to a different config"
        )

    report = drop_cap_render.apply(
        config,
        docs,
        article_document_ir=article_document_ir,
        typesetting_stage=typesetter,
    )
    if not isinstance(report, dict):
        raise MinimalPipelineStateError("drop-cap renderer did not return a report")
    if state.article_document_ir is not article_document_ir:
        raise MinimalPipelineStateError("canonical ArticleDocumentIR identity changed")
    state._render_report = report
    state._render_completed = True
    return report
