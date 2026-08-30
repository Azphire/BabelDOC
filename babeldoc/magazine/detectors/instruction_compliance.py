"""Human rulings that did not survive to the finished document.

The human constraint this pipeline actually carries is the HITL decisions file:
a ruled glossary term, a ruled drop-cap verdict, a ruled page kind. Each is
applied by an early pass and then has to survive every later pass -- retrieval,
translation, line splitting, typesetting, repair -- to reach the reader. This
detector asks, at the end, whether it did.

The question is deliberately asked of the finished document rather than of the
report the applying pass wrote about itself. A pass reporting that it applied a
ruling is evidence that it ran, not evidence that the ruling is still there; the
two answers differ exactly when something downstream overwrote it, which is the
only case worth reporting. Where an applying pass keeps a record, that record is
read as well, so a finding can say whether the ruling never landed or landed and
was later lost.

Three rules, one per section of the decisions file:

``term_adoption``    a page whose source carried a ruled term, whose finished
                     text does not carry the ruling's target.
``drop_cap_ruling``  a ruled paragraph whose drop-cap verdict is not the one
                     that was ruled.
``page_kind_ruling`` a ruled page whose kind is not the one that was ruled.

A sample with no decisions file is not a violation and not an error: there was
no constraint to comply with, and the run is recorded as skipped for that
reason. Report only; nothing here writes to the document.
"""

from __future__ import annotations

from babeldoc.glossary import Glossary
from babeldoc.magazine.detectors import base

NAME = "instruction_compliance"
KIND = "instruction_compliance"

REQUIRES_TRANSLATION = False
REQUIRES_SOURCE_GEOMETRY = False
REQUIRES_HITL_STATE = True
FINAL_ONLY = True

RULE_TERM = "term_adoption"
RULE_DROP_CAP = "drop_cap_ruling"
RULE_PAGE_KIND = "page_kind_ruling"
RULES = (RULE_TERM, RULE_DROP_CAP, RULE_PAGE_KIND)

SKIP_NO_HITL_STATE = "hitl_state_absent"
SKIP_NO_DECISIONS = "decisions_file_absent"

# Sections of the HITL report this detector reads, named once so a rename shows
# up here rather than as a silently empty check.
_APPLIED = "applied"
_SKIPPED = "skipped"
_DROP_CAPS_SECTION = "drop_caps"
_PAGE_KINDS_SECTION = "page_kinds"


def _normalize(value: str) -> str:
    """The one spelling both sides of a term comparison are reduced to.

    The same normalisation the HITL pass captured its source pages under, so a
    term is looked for here exactly as it was looked for there.
    """
    return Glossary.normalize_source(value or "")


def _page_text(view) -> str:
    """What one finished page shows, normalised for term matching."""
    return _normalize(
        "\n".join(
            base.rendered_text(paragraph, physical_page=view.label)
            for paragraph in (view.page.pdf_paragraph or ())
        )
    )


def _issue(context, rule: str, identity: str, page: int, detail, *, refs=()):
    return base.Issue(
        kind=KIND,
        page=page,
        paragraph_refs=tuple(refs),
        geometry=None,
        severity=context.severity_of(KIND),
        evidence={
            "instruction": rule,
            "instruction_ref": identity,
            "detail": detail,
            "violation_count": 1,
            "identity_ref": f"{rule}:{identity}",
        },
        detector=NAME,
        detected_at_iteration=context.iteration,
    )


def _skip(context, reason: str) -> list:
    context.file(NAME, {"status": "skipped", "reason": reason, "typed": True})
    return []


def _report_section(report, *path):
    value = report if isinstance(report, dict) else {}
    for name in path:
        if not isinstance(value, dict):
            return None
        value = value.get(name)
    return value


def _skipped_keys(report, section: str) -> frozenset[str]:
    """Rulings the applying pass recorded as out of the run's own scope.

    A ruling for a page this run did not select was never asked to land, so it
    is not a ruling that was lost.
    """
    rows = _report_section(report, _SKIPPED)
    if not isinstance(rows, list):
        return frozenset()
    return frozenset(
        str(row.get("key"))
        for row in rows
        if isinstance(row, dict) and row.get("section") == section
    )


def _term_findings(context, decisions, state) -> list:
    found = []
    pages = {view.label: view for view in context.pages}
    texts: dict[int, str] = {}
    for label, source_text in state.source_text_pages or ():
        view = pages.get(label)
        if view is None:
            continue
        for source, target in sorted(decisions.terms.items()):
            needle = _normalize(source)
            if not needle or needle not in source_text:
                continue
            if label not in texts:
                texts[label] = _page_text(view)
            wanted = _normalize(target)
            if not wanted or wanted in texts[label]:
                continue
            found.append(
                _issue(
                    context,
                    RULE_TERM,
                    f"{source}->{target}:p{label}",
                    label,
                    {
                        "source": source,
                        "target": target,
                        "page": label,
                    },
                )
            )
    return found


def _drop_cap_findings(context, decisions, state) -> list:
    found = []
    out_of_scope = _skipped_keys(state.report, _DROP_CAPS_SECTION)
    applied = {
        str(row.get("paragraph")): row.get("decision")
        for row in (
            _report_section(state.report, _APPLIED, _DROP_CAPS_SECTION) or ()
        )
        if isinstance(row, dict)
    }
    paragraphs = {
        (view.label, index): paragraph
        for view in context.pages
        for index, paragraph in enumerate(view.page.pdf_paragraph or ())
    }
    for reference, ruling in sorted(decisions.drop_caps.items()):
        if reference in out_of_scope:
            continue
        recorded = applied.get(reference)
        live = paragraphs.get((ruling.physical_page, ruling.paragraph_index))
        carried = None if live is None else live.drop_cap_decision
        if recorded == ruling.decision and carried == ruling.decision:
            continue
        found.append(
            _issue(
                context,
                RULE_DROP_CAP,
                reference,
                ruling.physical_page,
                {
                    "ruled": ruling.decision,
                    "recorded_as_applied": recorded,
                    "carried_by_document": carried,
                    "reached_document": live is not None,
                },
                refs=() if live is None else (reference,),
            )
        )
    return found


def _page_kind_findings(context, decisions, state) -> list:
    found = []
    out_of_scope = _skipped_keys(state.report, _PAGE_KINDS_SECTION)
    applied = {
        row.get("page"): row.get("kind")
        for row in (
            _report_section(state.report, _APPLIED, _PAGE_KINDS_SECTION) or ()
        )
        if isinstance(row, dict)
    }
    pages = {view.label: view for view in context.pages}
    for page, kind in sorted(decisions.page_kinds.items()):
        if str(page) in out_of_scope:
            continue
        view = pages.get(page)
        if view is None:
            continue
        carried = getattr(view.page, "page_kind", None)
        recorded = applied.get(page)
        if recorded == kind and carried == kind:
            continue
        found.append(
            _issue(
                context,
                RULE_PAGE_KIND,
                str(page),
                page,
                {
                    "ruled": kind,
                    "recorded_as_applied": recorded,
                    "carried_by_document": carried,
                },
            )
        )
    return found


def detect(context: base.DetectionContext) -> list[base.Issue]:
    state = context.hitl_state
    if state is None:
        return _skip(context, SKIP_NO_HITL_STATE)
    decisions = getattr(state, "decisions", None)
    if decisions is None:
        return _skip(context, SKIP_NO_DECISIONS)
    return [
        *_term_findings(context, decisions, state),
        *_drop_cap_findings(context, decisions, state),
        *_page_kind_findings(context, decisions, state),
    ]
