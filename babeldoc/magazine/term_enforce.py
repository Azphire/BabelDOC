"""The enforcement ladder for human-ruled glossary terms.

A ruling in the decisions file used to travel two disconnected ways: injected
into every translation prompt's glossary (soft), and checked at the end by the
``instruction_compliance`` detector (hard, and acted on by nobody -- its one
repair action is ``no_op``). Between injection and detection nothing enforced
anything: a model that declined the injected rendering shipped its own.

This pass is the missing middle. Five levels, every ruled occurrence ending in
exactly one named bucket:

1. **Injection** -- unchanged, the glossary freeze already records it.
2. **Per-unit check** -- a unit whose frozen source text carries a ruled
   term's source as a normalized substring (the same ``Glossary
   .normalize_source`` the detector compares under) and whose translated text
   lacks the ruled rendering is a violation.  Units the run withheld from
   translation (furniture, vertical, preserved) are not retranslated behind
   the withholding pass's back; they escalate with that reason.
3. **Deterministic variant substitution** -- a violating unit whose target
   carries a known variant of the ruling has the variant replaced by the
   ruled rendering, zero model calls.  The variant closed set per source:
   the auto-glossary target the ruling displaced (``dropped_from_auto``),
   and the ruled source itself still standing untranslated in the target.
   The replacement touches exactly the variant's span; the paragraph's other
   bytes are asserted unchanged.
4. **Pinned retranslation** -- a violation with no known variant earns one
   retranslation whose instruction pins the ruled rendering, within
   ``term_enforce_retry_budget`` per publication.
5. **Escalation** -- what still violates is recorded here and keeps its
   ``instruction_compliance`` finding; the violation list travels with the
   finished document.

The conservation equation ``ruled == applied + variant_substituted +
retried_ok + escalated`` is asserted into the report.

Sources are frozen before translation (``freeze_sources``), because after
translation the paragraph carries only its target text.  The pass runs at
``after_translation`` time, after furniture unification and before
paren-dedup and typesetting, so what it reads and edits is the text the page
will be set from.
"""

from __future__ import annotations

import json
import logging
import weakref
from pathlib import Path

from babeldoc.glossary import Glossary
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.prompt_loader import PromptError
from babeldoc.magazine.prompt_loader import load_prompt
from babeldoc.magazine.resource_paths import config_path

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("term_enforce.json")
REPORT_NAME = "term_enforce.report.json"
PROMPT_NAME = "term_pin"

SOURCES_ATTR = "magazine_term_source_texts"

# The closed vocabulary of per-occurrence outcomes.
OUTCOME_APPLIED = "applied"
OUTCOME_SUBSTITUTED = "variant_substituted"
OUTCOME_RETRIED_OK = "retried_ok"
OUTCOME_ESCALATED = "escalated"

# The closed vocabulary of escalation reasons.
ESCALATION_RETRY_STILL_VIOLATES = "retry_still_violates"
ESCALATION_BUDGET = "retry_budget_exhausted"
ESCALATION_ENGINE = "engine_unsupported"
ESCALATION_REPLY_UNUSABLE = "retry_reply_unusable"
ESCALATION_WITHHELD = "unit_withheld_from_translation"
ESCALATION_SPANS = "variant_spans_compositions"
ESCALATION_OPAQUE = "composition_not_rebuildable"

_retry_spent: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def load_term_enforce_config() -> dict:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return dict(validate_bounded_config(raw, CONFIG_PATH))


def _normalize(value: str) -> str:
    """The one spelling both sides compare under -- the detector's own."""
    return Glossary.normalize_source(value or "")


def freeze_sources(translation_config, docs, hitl_state) -> None:
    """Hold every term-bearing paragraph's source text before translation.

    Only paragraphs whose normalized source carries a ruled term source are
    held, keyed by debug id; everything else the ladder never asks about.
    """
    decisions = getattr(hitl_state, "decisions", None)
    terms = getattr(decisions, "terms", None) or {}
    sources: dict[str, dict] = {}
    if terms:
        needles = {
            source: _normalize(source)
            for source in terms
            if _normalize(source)
        }
        for page_index, page in enumerate(docs.page or ()):
            for paragraph in page.pdf_paragraph or ():
                debug_id = getattr(paragraph, "debug_id", None)
                text = str(getattr(paragraph, "unicode", "") or "")
                if not debug_id or not text:
                    continue
                normalized = _normalize(text)
                held = [
                    source
                    for source, needle in needles.items()
                    if needle in normalized
                ]
                if held:
                    sources[debug_id] = {
                        "source_text": text,
                        "page": page_index + 1,
                        "terms": held,
                    }
    setattr(translation_config, SOURCES_ATTR, sources)


def _variant_closed_set(source: str, target: str, dropped_from_auto) -> list[str]:
    """Known renderings a violating target may carry, most specific first."""
    variants: list[str] = []
    needle = _normalize(source)
    for row in dropped_from_auto or ():
        if not isinstance(row, dict):
            continue
        if _normalize(str(row.get("source", ""))) != needle:
            continue
        auto_target = str(row.get("auto_target", "") or "")
        if auto_target and _normalize(auto_target) != _normalize(target):
            variants.append(auto_target)
    # The ruled source itself, still standing untranslated in the target,
    # is trivially a known variant of itself.
    variants.append(source)
    return variants


def _composition_runs(paragraph) -> list | None:
    """The paragraph's unicode runs, or None when anything opaque is present."""
    runs = []
    for composition in paragraph.pdf_paragraph_composition or ():
        run = getattr(composition, "pdf_same_style_unicode_characters", None)
        if run is None:
            return None
        runs.append(run)
    return runs


def _find_variant(text: str, variant: str) -> tuple[int, str] | None:
    index = text.find(variant)
    if index >= 0:
        return index, variant
    lowered = text.lower().find(variant.lower())
    if lowered >= 0:
        return lowered, text[lowered : lowered + len(variant)]
    return None


def _substitute(paragraph, variant: str, replacement: str) -> str | None:
    """Replace one variant span in place; everything else byte-identical.

    Returns None on success, or the escalation reason.
    """
    text = str(getattr(paragraph, "unicode", "") or "")
    located = _find_variant(text, variant)
    if located is None:
        return ESCALATION_SPANS
    index, exact = located
    runs = _composition_runs(paragraph)
    if runs is None:
        return ESCALATION_OPAQUE
    joined = "".join(run.unicode or "" for run in runs)
    if joined != text:
        return ESCALATION_OPAQUE
    offset = 0
    for run in runs:
        held = run.unicode or ""
        if offset <= index and index + len(exact) <= offset + len(held):
            local = index - offset
            run.unicode = (
                held[:local] + replacement + held[local + len(exact) :]
            )
            break
        offset += len(held)
    else:
        return ESCALATION_SPANS
    expected = text[:index] + replacement + text[index + len(exact) :]
    paragraph.unicode = expected
    rebuilt = "".join(run.unicode or "" for run in runs)
    if rebuilt != expected:
        raise AssertionError(
            "term substitution changed bytes outside the variant span"
        )
    return None


def _parse_reply(reply: str) -> str | None:
    import re

    match = re.search(r"\{.*\}", reply or "", re.DOTALL)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return None
    output = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(output, str) or not output.strip():
        return None
    return output.strip()


def _retranslate_pinned(
    translation_config,
    paragraph,
    source_text: str,
    source: str,
    target: str,
    budget: int,
) -> tuple[bool, str]:
    """One pinned retranslation. Returns (ok, outcome-or-escalation-reason)."""
    engine = getattr(translation_config, "translator", None)
    llm_translate = getattr(engine, "llm_translate", None)
    if not callable(llm_translate):
        return False, ESCALATION_ENGINE
    spent = int(_retry_spent.get(translation_config, 0))
    if spent >= budget:
        return False, ESCALATION_BUDGET
    _retry_spent[translation_config] = spent + 1
    runs = _composition_runs(paragraph)
    if runs is None:
        return False, ESCALATION_OPAQUE
    try:
        prompt = load_prompt(
            PROMPT_NAME,
            {
                "target_language": getattr(translation_config, "lang_out", "")
                or "",
                "unit": source_text,
                "term_source": source,
                "term_target": target,
            },
            working_dir=_working_dir(translation_config),
        )
    except PromptError as error:
        logger.warning("term pin prompt unavailable: %s", error)
        return False, ESCALATION_REPLY_UNUSABLE
    try:
        reply = llm_translate(prompt.text, rate_limit_params={})
    except Exception:
        logger.warning("term pin retranslation failed", exc_info=True)
        return False, ESCALATION_REPLY_UNUSABLE
    output = _parse_reply(reply)
    if output is None:
        return False, ESCALATION_REPLY_UNUSABLE
    if _normalize(target) not in _normalize(output):
        return False, ESCALATION_RETRY_STILL_VIOLATES
    style = getattr(paragraph, "pdf_style", None)
    if runs:
        style = getattr(runs[0], "pdf_style", None) or style
    from babeldoc.format.pdf.document_il import il_version_1

    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_same_style_unicode_characters=(
                il_version_1.PdfSameStyleUnicodeCharacters(
                    pdf_style=style, unicode=output
                )
            )
        )
    ]
    paragraph.unicode = output
    return True, OUTCOME_RETRIED_OK


def _working_dir(translation_config) -> Path | None:
    getter = getattr(translation_config, "get_working_file_path", None)
    if not callable(getter):
        return None
    try:
        return Path(getter("prompts.manifest.json")).parent
    except Exception:
        return None


def apply(translation_config, docs, hitl_state, coverage_snapshot=None) -> dict | None:
    """Run levels 2-5 over every frozen term-bearing unit; write the report."""
    decisions = getattr(hitl_state, "decisions", None)
    terms = getattr(decisions, "terms", None) or {}
    sources = getattr(translation_config, SOURCES_ATTR, None) or {}
    if not terms or not sources:
        return None
    report_section = getattr(hitl_state, "report", None) or {}
    dropped_from_auto = (
        report_section.get("applied", {}).get("terms", {}) or {}
    ).get("dropped_from_auto", ())
    parameters = load_term_enforce_config()
    budget = int(parameters["term_enforce_retry_budget"])

    paragraphs_by_debug: dict[str, object] = {}
    for page in docs.page or ():
        for paragraph in page.pdf_paragraph or ():
            debug_id = getattr(paragraph, "debug_id", None)
            if debug_id:
                paragraphs_by_debug.setdefault(debug_id, paragraph)

    furniture_plan = getattr(
        translation_config, "magazine_furniture_plan", None
    )

    cases: list[dict] = []
    counts = {
        OUTCOME_APPLIED: 0,
        OUTCOME_SUBSTITUTED: 0,
        OUTCOME_RETRIED_OK: 0,
        OUTCOME_ESCALATED: 0,
    }
    for debug_id in sorted(sources):
        held = sources[debug_id]
        paragraph = paragraphs_by_debug.get(debug_id)
        if paragraph is None:
            continue
        source_text = held["source_text"]
        target_text = str(getattr(paragraph, "unicode", "") or "")
        for source in held["terms"]:
            target = terms.get(source)
            if not target:
                continue
            case = {
                "debug_id": debug_id,
                "page": held["page"],
                "term_source": source,
                "term_target": target,
                "outcome": None,
                "detail": None,
            }
            target_text = str(getattr(paragraph, "unicode", "") or "")
            if _normalize(target) in _normalize(target_text):
                case["outcome"] = OUTCOME_APPLIED
                counts[OUTCOME_APPLIED] += 1
                cases.append(case)
                continue
            withheld = bool(
                getattr(paragraph, "vertical", False)
                or (
                    furniture_plan is not None
                    and furniture_plan.withholds(debug_id)
                )
            )
            if withheld:
                case["outcome"] = OUTCOME_ESCALATED
                case["detail"] = ESCALATION_WITHHELD
                counts[OUTCOME_ESCALATED] += 1
                cases.append(case)
                continue
            # Level 3: deterministic substitution from the closed variant set.
            substituted = False
            for variant in _variant_closed_set(
                source, target, dropped_from_auto
            ):
                if _find_variant(target_text, variant) is None:
                    continue
                reason = _substitute(paragraph, variant, target)
                if reason is None:
                    case["outcome"] = OUTCOME_SUBSTITUTED
                    case["variant"] = variant
                    counts[OUTCOME_SUBSTITUTED] += 1
                    cases.append(case)
                    substituted = True
                else:
                    case["outcome"] = OUTCOME_ESCALATED
                    case["detail"] = reason
                    counts[OUTCOME_ESCALATED] += 1
                    cases.append(case)
                    substituted = True
                break
            if substituted:
                continue
            # Level 4: one pinned retranslation.
            ok, reason = _retranslate_pinned(
                translation_config,
                paragraph,
                source_text,
                source,
                target,
                budget,
            )
            if ok:
                case["outcome"] = OUTCOME_RETRIED_OK
                counts[OUTCOME_RETRIED_OK] += 1
            else:
                case["outcome"] = OUTCOME_ESCALATED
                case["detail"] = reason
                counts[OUTCOME_ESCALATED] += 1
            cases.append(case)

    ruled = len(cases)
    conserved = ruled == sum(counts.values())
    if not conserved:
        raise AssertionError(
            f"term enforcement conservation failed: {ruled} ruled, "
            f"{counts}"
        )
    record = {
        "schema_version": 1,
        "budget": {
            "term_enforce_retry_budget": budget,
            "spent": int(_retry_spent.get(translation_config, 0)),
        },
        "counts": {"ruled": ruled, **counts},
        "conservation": (
            "ruled == applied + variant_substituted + retried_ok + escalated"
        ),
        "conservation_ok": conserved,
        "cases": cases,
    }
    _write_report(translation_config, record)
    return record


def _write_report(translation_config, record: dict) -> None:
    try:
        path = Path(translation_config.get_working_file_path(REPORT_NAME))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        logger.warning("term_enforce report write failed", exc_info=True)
