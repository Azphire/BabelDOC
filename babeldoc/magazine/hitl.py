"""Human review layer: export what the machine decided, take back what a human ruled.

Two switches, both down by default. ``magazine_hitl_export`` writes a review
draft of the decisions the machine made on its own. ``magazine_hitl_apply``
reads the file a human wrote beside that draft and lets it overrule them. With
both down this module is reached at two call sites that return immediately, and
the pipeline is what it was without it.

The two files are deliberately not the same file. ``<sample>.review.json`` is
written by this module and never read by it: it is the machine's account of
itself, regenerated on every run. ``<sample>.decisions.json`` is written by a
human and never written by this module: an empty object is the whole of what a
machine may put there. Keeping the authorities apart is what makes the review
loop safe to repeat -- a rerun cannot quietly adopt its own previous draft as a
ruling, because the file it reads is one it has no way to produce.

A draft records the machine's verdict, never the human's. Both hooks export
before they apply, so a second pass exports the same draft the first pass did
and the human reads what the machine would have done unaided, on every pass.

Validation is all-or-nothing. A decisions file with one malformed entry is
refused whole, with every fault listed, rather than applied in part: a partly
applied ruling is a state no one authored, and the point of the loop is that
what runs is a state someone did.

Two channels are wired here.

Terms. The decided pairs become a glossary in the user glossary list. The
finalised automatic glossary, if the extractor built one, has every entry the
human ruled on removed from it and is rebuilt without them, so a decided source
reaches the translator from one table only and the human's target is the only
target offered for it. The rebuilt glossary is then moved into the user
glossary list as well, and the automatic slot is emptied. That move is what
makes the ruling arrive at all: the selection rule in
``TranslationConfig.get_glossaries_for_translation`` returns the automatic
glossary *alone* whenever extraction is enabled and that slot is filled, so a
ruling left in the user list beside a filled slot would be discarded before it
reached a prompt. Moving both tables into the one list the rule always reads
keeps every entry and changes no upstream code (see W-B7-01 for what the move
costs). Nothing touches ``raw_extracted_terms``: the extractor's own record of
what it saw stays as it was, and only the finalised object is rebuilt.

Page kinds. A ruled page takes the human's kind, a confidence of one and a
source naming the human, which is the provenance the intermediate language
carries for the rest of the run. No page type is named here; the ruling is
checked against whatever ``configs/page_types.json`` declares and everything
downstream reads the policy of the kind that ends up on the page.

Drop caps. The candidates are found by ``magazine/drop_cap.py``, which this
module calls at the same hook the term channel runs at, and the ruling on them
is written back into the intermediate language as a verdict per paragraph. That
verdict is the one thing a ruling can decide here that nothing in this batch
acts on; see that module for why, and for the sidecar that records it.

Line structure. ``magazine/line_split.py`` rides the page kind hook for the same
reason the drop cap pass rides the term one: the window it must run in holds no
other extension owned call. It runs after a ruling is applied, so it reads the
kind the run settled on, and it is behind its own switch.

A ruling that reaches nothing is the one failure the loop could not report on
its own, and a third hook after the translator closes it. A paragraph is
matched against the text the request was built from, which carries the markup
its style runs imply, while a human rules from the joined rendering the draft
shows; where a paragraph is set in several styles the two strings differ and a
ruling keyed on the rendering matches nothing at all. So the draft carries the
offered text beside the rendering, and an applied ruling records how many
offered texts each pair reached, warning where that is none. Both are read from
the tracking file the translator already writes, so neither costs a request.

That count covers every path that sends text to the engine, not only the
translator's. The repair loop translates the lines the translator was never
given, and a ruling that binds the document binds what the loop asks for too,
so a fourth hook after the loop recounts with the loop's own inputs included.
Without it a ruling whose only occurrence is on an orphan line would be
reported as having reached nothing, which is the same silence the third hook
exists to end.
"""

from __future__ import annotations

import html
import json
import logging
import os
import weakref
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from pathlib import Path

from babeldoc.glossary import Glossary
from babeldoc.glossary import GlossaryEntry
from babeldoc.magazine import drop_cap
from babeldoc.magazine import line_split
from babeldoc.magazine.page_classifier import REPORT_NAME as CLASSIFY_REPORT_NAME
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "hitl.json"

# Where the two files live. The environment variable is a test seam: a gate
# runs the export against a disposable directory rather than into the working
# tree it is asserting about.
REVIEWS_ENV = "BABELDOC_REVIEWS_DIR"
DEFAULT_REVIEWS_DIR = ROOT / "reviews"

REVIEW_SUFFIX = ".review.json"
REVIEW_HTML_SUFFIX = ".review.html"
DECISIONS_SUFFIX = ".decisions.json"

# What an applied ruling leaves behind, beside the checkpoints.
REPORT_NAME = "hitl_apply.report.json"

# The section names, by role. The declared order comes from the configuration;
# these name the individual sections for the code that fills one of them.
TERMS_SECTION = "terms"
PAGE_KINDS_SECTION = "page_kinds"
DROP_CAPS_SECTION = "drop_caps"

# Provenance and confidence a ruled page carries. A human ruling is not a
# measurement, so it is recorded at certainty rather than at a score.
HUMAN_SOURCE = "human"
HUMAN_CONF = 1.0

# Name of the glossary the decided pairs are built into. It appears as the
# table heading in the translation prompt, which is how a reader of a prompt
# tells a ruled term from an extracted one.
DECISIONS_GLOSSARY = "hitl_decisions"

_CONFIG_KEY_VERSION = "review_format_version"
_CONFIG_KEY_SECTIONS = "sections"
_CONFIG_KEY_DROP_CAP_DECISIONS = "drop_cap_decisions"
_CONFIG_KEY_TRANSLATOR_VIEW_CHARS = "translator_view_chars"
_CONFIG_KEY_MATCHED_EXCERPTS = "matched_prompt_excerpts"

# What the translator leaves beside a run, holding for every paragraph it built
# a request from both the joined rendering a human is shown and the text the
# request was actually built from.
TRACKING_NAME = "translate_tracking.json"

# The three lists of the tracking file, each a list of objects carrying one
# ``paragraph`` list. A request is a request whichever of them it came from.
_TRACKING_SECTIONS = ("page", "cross_page", "cross_column")

# The column the terms section carries the offered text in.
TRANSLATOR_VIEW_COLUMN = "translator_view"

# What ``matched_prompt_count`` counts, written into the report beside the
# counts themselves so a reader of the file needs nothing else to read them.
MATCH_DEFINITION = (
    "how many inputs -- the text a paragraph was offered as, which "
    "is what the glossary is matched against -- activate this entry, by the "
    "matcher the translation prompt itself uses; counted over every request "
    "this run built from the document, the repair loop's included"
)

# How many of the counted inputs came from the repair loop rather than from the
# translator, written beside the counts so the two paths stay distinguishable.
REPAIR_INPUTS_KEY = "repair_inputs"


class HitlError(ValueError):
    """Raised when the review configuration or a decisions file is malformed."""


@lru_cache(maxsize=1)
def load_hitl_config(path: str | None = None) -> dict:
    """Load and validate ``configs/hitl.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    try:
        parameters = dict(validate_bounded_config(raw, config_path))
    except ConfigError as exc:
        raise HitlError(str(exc)) from exc
    for key in (
        _CONFIG_KEY_VERSION,
        _CONFIG_KEY_SECTIONS,
        _CONFIG_KEY_DROP_CAP_DECISIONS,
        _CONFIG_KEY_TRANSLATOR_VIEW_CHARS,
        _CONFIG_KEY_MATCHED_EXCERPTS,
    ):
        if key not in parameters:
            raise HitlError(f"{config_path.name}: missing {key}")
    declared = parameters[_CONFIG_KEY_SECTIONS]
    for name in (TERMS_SECTION, PAGE_KINDS_SECTION, DROP_CAPS_SECTION):
        if name not in declared:
            raise HitlError(f"{config_path.name}: {_CONFIG_KEY_SECTIONS} omits {name}")
    return parameters


def sections() -> tuple[str, ...]:
    """The declared sections of both files, in declaration order."""
    return tuple(load_hitl_config()[_CONFIG_KEY_SECTIONS])


def reviews_dir() -> Path:
    override = os.environ.get(REVIEWS_ENV)
    return DEFAULT_REVIEWS_DIR if not override else Path(override)


def sample_name(translation_config) -> str:
    """The stem the two files of one sample are named after."""
    return Path(translation_config.input_file).stem


def review_path(sample: str) -> Path:
    return reviews_dir() / f"{sample}{REVIEW_SUFFIX}"


def review_html_path(sample: str) -> Path:
    return reviews_dir() / f"{sample}{REVIEW_HTML_SUFFIX}"


def decisions_path(sample: str) -> Path:
    return reviews_dir() / f"{sample}{DECISIONS_SUFFIX}"


def page_label(page, position: int) -> int:
    """One-based file page number of an intermediate language page.

    ``page_number`` is zero based where it is set at all; the label is what both
    files speak in, and what ``corpus/page_labels.json`` already speaks in.
    """
    index = page.page_number if page.page_number is not None else position
    return int(index) + 1


def labeled_pages(docs) -> list[tuple[int, object]]:
    """The document's pages, each with the number both files speak of it by."""
    return [
        (page_label(page, position), page) for position, page in enumerate(docs.page)
    ]


@dataclass
class Decisions:
    """One validated decisions file."""

    path: Path
    terms: dict[str, str] = field(default_factory=dict)
    page_kinds: dict[int, str] = field(default_factory=dict)
    drop_caps: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.terms or self.page_kinds or self.drop_caps)


def _require_object(raw: object, name: str, faults: list[str]) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        faults.append(f"section {name!r} must be an object")
        return {}
    return raw


def _validate_terms(raw: object, faults: list[str]) -> dict[str, str]:
    entries: dict[str, str] = {}
    seen: dict[str, str] = {}
    for source, target in _require_object(raw, TERMS_SECTION, faults).items():
        where = f"{TERMS_SECTION}[{source!r}]"
        if not isinstance(target, str):
            faults.append(f"{where}: target must be a string")
            continue
        if not source.strip() or not target.strip():
            faults.append(f"{where}: source and target must both be non-empty")
            continue
        if source != source.strip() or target != target.strip():
            faults.append(f"{where}: source and target must not be padded")
            continue
        # Matching is case and whitespace insensitive, so two sources that
        # differ only in those cannot both be honoured and neither is guessed
        # at.
        key = Glossary.normalize_source(source)
        if key in seen:
            faults.append(f"{where}: collides with {seen[key]!r} once normalised")
            continue
        seen[key] = source
        entries[source] = target
    return entries


def _validate_page_kinds(
    raw: object, pages: set[int], kinds: tuple[str, ...], faults: list[str]
) -> dict[int, str]:
    entries: dict[int, str] = {}
    for label, kind in _require_object(raw, PAGE_KINDS_SECTION, faults).items():
        where = f"{PAGE_KINDS_SECTION}[{label!r}]"
        try:
            number = int(label)
        except (TypeError, ValueError):
            faults.append(f"{where}: page must be a decimal integer")
            continue
        if str(number) != str(label):
            faults.append(f"{where}: page must be written as {number}")
            continue
        if number not in pages:
            faults.append(
                f"{where}: no such page; this document has "
                f"{min(pages) if pages else 0}..{max(pages) if pages else 0}"
            )
            continue
        if not isinstance(kind, str) or kind not in kinds:
            faults.append(f"{where}: {kind!r} is not a declared page type")
            continue
        entries[number] = kind
    return entries


def _validate_drop_caps(
    raw: object,
    verdicts: tuple[str, ...],
    references: set[str] | None,
    faults: list[str],
) -> dict[str, str]:
    entries: dict[str, str] = {}
    for reference, verdict in _require_object(raw, DROP_CAPS_SECTION, faults).items():
        where = f"{DROP_CAPS_SECTION}[{reference!r}]"
        if not reference.strip():
            faults.append(f"{where}: paragraph reference must be non-empty")
            continue
        if not isinstance(verdict, str) or verdict not in verdicts:
            faults.append(f"{where}: {verdict!r} is not one of {list(verdicts)}")
            continue
        # A reference is checked against the document only where the caller
        # knows the document. A ruling read against a document names paragraphs
        # of it or is refused, by the same rule a ruled page number is.
        if references is not None and reference not in references:
            faults.append(f"{where}: no such paragraph in this document")
            continue
        entries[reference] = verdict
    return entries


def parse_decisions(
    raw: object, path: Path, pages: set[int], references: set[str] | None = None
) -> Decisions:
    """Validate one decisions document, refusing it whole if anything is wrong."""
    faults: list[str] = []
    if not isinstance(raw, dict):
        raise HitlError(f"{path}: top level must be an object")
    declared = sections()
    for key in raw:
        if key not in declared:
            faults.append(f"{key!r} is not one of the declared sections {declared}")
    config = load_hitl_config()
    terms = _validate_terms(raw.get(TERMS_SECTION), faults)
    page_kinds = _validate_page_kinds(
        raw.get(PAGE_KINDS_SECTION), pages, load_taxonomy().names(), faults
    )
    drop_caps = _validate_drop_caps(
        raw.get(DROP_CAPS_SECTION),
        tuple(config[_CONFIG_KEY_DROP_CAP_DECISIONS]),
        references,
        faults,
    )
    if faults:
        listed = "\n  ".join(faults)
        raise HitlError(f"{path}: {len(faults)} fault(s), file rejected:\n  {listed}")
    return Decisions(
        path=path, terms=terms, page_kinds=page_kinds, drop_caps=drop_caps
    )


def load_decisions(
    path: Path, pages: set[int], references: set[str] | None = None
) -> Decisions | None:
    """Read and validate a decisions file, or return None where none was written."""
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise HitlError(f"{path}: not valid JSON: {exc}") from exc
    return parse_decisions(raw, path, pages, references)


# Per-run state. Both hooks contribute to one draft and one report, and a run is
# identified by the configuration object driving it, so nothing has to be
# threaded through the two upstream call sites.
_drafts: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_decisions: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_reports: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _draft(translation_config) -> dict:
    draft = _drafts.get(translation_config)
    if draft is None:
        draft = {
            "format_version": load_hitl_config()[_CONFIG_KEY_VERSION],
            "sample": sample_name(translation_config),
        }
        draft.update({name: [] for name in sections()})
        _drafts[translation_config] = draft
    return draft


def _write_draft(translation_config, draft: dict) -> Path:
    directory = reviews_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = review_path(draft["sample"])
    with path.open("w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    html_path = review_html_path(draft["sample"])
    with html_path.open("w", encoding="utf-8") as f:
        f.write(render_review_html(draft))
    return path


def _report(translation_config) -> dict:
    report = _reports.get(translation_config)
    if report is None:
        report = {"sample": sample_name(translation_config)}
        _reports[translation_config] = report
    return report


def _write_report(translation_config, report: dict) -> Path:
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def _decisions_for(translation_config, docs) -> Decisions | None:
    """The ruling governing this run, read and validated once."""
    if translation_config in _decisions:
        return _decisions[translation_config]
    labeled = labeled_pages(docs)
    pages = {label for label, _page in labeled}
    decisions = load_decisions(
        decisions_path(sample_name(translation_config)),
        pages,
        drop_cap.document_references(labeled),
    )
    _decisions[translation_config] = decisions
    return decisions


def _term_votes(shared_context) -> dict[str, int]:
    """How many extraction replies proposed each source, in first-seen order."""
    votes: dict[str, int] = {}
    for source, _target in shared_context.raw_extracted_terms:
        votes[source] = votes.get(source, 0) + 1
    return votes


def _first_pages(docs, sources: list[str]) -> dict[str, int | None]:
    """First page each source appears on, by exact match against page text."""
    found: dict[str, int | None] = dict.fromkeys(sources)
    outstanding = list(sources)
    for position, page in enumerate(docs.page):
        if not outstanding:
            break
        text = "\n".join(
            paragraph.unicode
            for paragraph in (page.pdf_paragraph or [])
            if paragraph.unicode
        )
        if not text:
            continue
        label = page_label(page, position)
        for source in list(outstanding):
            if source in text:
                found[source] = label
                outstanding.remove(source)
    return found


def _auto_targets(shared_context) -> dict[str, str]:
    """The target each source was finalised to, keyed by its normalised form."""
    glossary = shared_context.auto_extracted_glossary
    if glossary is None:
        return {}
    return {
        Glossary.normalize_source(entry.source): entry.target
        for entry in glossary.entries
    }


def export_terms(translation_config, docs) -> list[dict]:
    """The extractor's findings, one row per source, as a draft section.

    ``vote_count`` is how many extraction replies proposed the source, which is
    the only frequency the extractor records; it is not the number of times the
    term occurs in the document. ``first_page`` is not recorded by the extractor
    at all and is found here, by exact match of the source against the page
    text, in file page order.
    """
    shared = translation_config.shared_context_cross_split_part
    votes = _term_votes(shared)
    targets = _auto_targets(shared)
    pages = _first_pages(docs, list(votes))
    rows = [
        {
            "source": source,
            "auto_target": targets.get(Glossary.normalize_source(source)),
            "vote_count": count,
            "first_page": pages[source],
        }
        for source, count in votes.items()
    ]
    # Reading order for a human working through the document, with the terms
    # no page claimed at the end.
    rows.sort(
        key=lambda row: (
            row["first_page"] is None,
            row["first_page"] or 0,
            row["source"],
        )
    )
    return rows


def export_page_kinds(translation_config, docs) -> list[dict]:
    """What the classifier settled on for each page, as a draft section.

    ``ambiguous`` is the classifier's own account of whether its top candidates
    could be separated, which the intermediate language has no field for; it is
    read from the report that stage writes and is null where that report is not
    beside this run.
    """
    ambiguity: dict[int, bool] = {}
    report_path = Path(translation_config.get_working_file_path(CLASSIFY_REPORT_NAME))
    if report_path.exists():
        with report_path.open(encoding="utf-8") as f:
            report = json.load(f)
        for record in report.get("pages", ()):
            number = record.get("page_number")
            if number is not None:
                ambiguity[int(number) + 1] = bool(record.get("ambiguous"))
    rows = []
    for position, page in enumerate(docs.page):
        label = page_label(page, position)
        rows.append(
            {
                "page": label,
                "machine_kind": page.page_kind,
                "conf": page.page_kind_conf,
                "ambiguous": ambiguity.get(label),
                "source": page.page_kind_source,
            }
        )
    return rows


def _unique_glossary_name(base: str, existing: list) -> str:
    taken = {glossary.name for glossary in existing}
    name = base
    suffix = 0
    while name in taken:
        suffix += 1
        name = f"{base}#{suffix}"
    return name


def apply_terms(translation_config, decisions: Decisions) -> dict | None:
    """Put the ruled pairs where the translator reads its glossaries from.

    Returns what the ruling did, or None where it ruled on no term at all: with
    nothing to apply nothing is touched, which is what makes a run under an
    empty ruling the run it would have been with the switch down.
    """
    if not decisions.terms:
        return None
    shared = translation_config.shared_context_cross_split_part
    by_key = {
        Glossary.normalize_source(source): (source, target)
        for source, target in decisions.terms.items()
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
                continue
            dropped.append(
                {
                    "source": entry.source,
                    "auto_target": entry.target,
                    "user_target": ruling[1],
                }
            )
        shared.auto_extracted_glossary = None
        if kept:
            shared.user_glossaries.append(Glossary(name=auto.name, entries=kept))
            relocated = auto.name
            kept_count = len(kept)

    name = _unique_glossary_name(DECISIONS_GLOSSARY, shared.user_glossaries)
    shared.user_glossaries.append(
        Glossary(
            name=name,
            entries=[
                GlossaryEntry(source, target)
                for source, target in decisions.terms.items()
            ],
        )
    )
    logger.debug(
        "hitl: %d ruled term(s) as glossary %s, %d automatic entry(ies) dropped",
        len(decisions.terms),
        name,
        len(dropped),
    )
    return {
        "glossary": name,
        "entries": [
            {"source": source, "target": target}
            for source, target in decisions.terms.items()
        ],
        "dropped_from_auto": dropped,
        "auto_glossary_relocated": relocated,
        "auto_glossary_kept": kept_count,
    }


def apply_page_kinds(docs, decisions: Decisions) -> list[dict]:
    """Overrule the classifier where the ruling names a page."""
    records = []
    for position, page in enumerate(docs.page):
        label = page_label(page, position)
        kind = decisions.page_kinds.get(label)
        if kind is None:
            continue
        records.append(
            {
                "page": label,
                "machine_kind": page.page_kind,
                "machine_conf": page.page_kind_conf,
                "machine_source": page.page_kind_source,
                "kind": kind,
            }
        )
        page.page_kind = kind
        page.page_kind_conf = HUMAN_CONF
        page.page_kind_source = HUMAN_SOURCE
    return records


def after_page_classify(translation_config, docs) -> None:
    """Hook run once the classifier has settled every page.

    Placed before the checkpoint of that stage, so a checkpoint carries the kind
    the run went on to use rather than the one that was overruled.

    The line structure pass runs here too, behind its own switch, and last: its
    flag is a page policy, so it has to see the kind a ruling settled rather
    than the one the classifier proposed, and it has to run before the chain
    builder, which is the next thing the pipeline does.
    """
    if translation_config.magazine_hitl_export:
        draft = _draft(translation_config)
        draft[PAGE_KINDS_SECTION] = export_page_kinds(translation_config, docs)
        _write_draft(translation_config, draft)
    if translation_config.magazine_hitl_apply:
        decisions = _decisions_for(translation_config, docs)
        if decisions is not None:
            applied = apply_page_kinds(docs, decisions)
            if applied:
                report = _report(translation_config)
                report[PAGE_KINDS_SECTION] = applied
                report["decisions_file"] = str(decisions.path)
                _write_report(translation_config, report)
    line_split.apply(translation_config, labeled_pages(docs))


def after_term_extract(translation_config, docs) -> None:
    """Hook run once term extraction is over and before the translator is built.

    The translator caches its glossaries as it is constructed, so this is the
    last point at which a ruled term can reach a prompt. Drop cap marking runs
    here too, unconditionally and behind its own switch: it needs the article map
    the grouping stage writes earlier in the pipeline, and marking before the
    draft is written is what lets one hook export the candidates it just found.
    """
    labeled = labeled_pages(docs)
    candidates = drop_cap.mark(translation_config, labeled)
    if translation_config.magazine_hitl_export:
        draft = _draft(translation_config)
        draft[TERMS_SECTION] = export_terms(translation_config, docs)
        draft[DROP_CAPS_SECTION] = drop_cap.review_rows(candidates)
        _write_draft(translation_config, draft)
    if not translation_config.magazine_hitl_apply:
        return
    decisions = _decisions_for(translation_config, docs)
    if decisions is None:
        return
    applied = apply_terms(translation_config, decisions)
    ruled = drop_cap.apply_decisions(labeled, decisions.drop_caps)
    if applied or ruled:
        report = _report(translation_config)
        if applied:
            report[TERMS_SECTION] = applied
        if ruled:
            report[DROP_CAPS_SECTION] = ruled
        report["decisions_file"] = str(decisions.path)
        _write_report(translation_config, report)


def read_tracking(translation_config) -> list[dict]:
    """Every request the translator built, as the tracking file records them.

    Empty where no tracking file is beside the run, which is what a run that
    translated nothing leaves. Order is the file's own, which is document order
    within each of its three lists.
    """
    path = Path(translation_config.get_working_file_path(TRACKING_NAME))
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        tracking = json.load(f)
    records: list[dict] = []
    for name in _TRACKING_SECTIONS:
        for holder in tracking.get(name) or ():
            records.extend(holder.get("paragraph") or ())
    return records


def offered_text(record: dict) -> str:
    return record.get("input") or ""


def rendered_text(record: dict) -> str:
    return record.get("pdf_unicode") or ""


def translator_view(source: str, records: list[dict], limit: int) -> str | None:
    """The offered text of the first request whose rendering carries ``source``.

    Only where the two differ. A paragraph offered exactly what it renders as
    holds no disagreement to show, and a column repeating the source string for
    every term would bury the ones that do.
    """
    for record in records:
        rendered = rendered_text(record)
        offered = offered_text(record)
        if source not in rendered or offered == rendered:
            continue
        return offered[:limit]
    return None


def match_counts(
    entries: list[tuple[str, str]], records: list[dict], excerpts: int
) -> list[dict]:
    """How many offered texts each ruled pair reaches, and a few of them.

    Matching goes through the glossary type the translation prompt matches
    with, so a pair counted here is a pair that prompt would have carried.
    """
    counted: list[dict] = []
    for source, target in entries:
        glossary = Glossary(
            name=DECISIONS_GLOSSARY, entries=[GlossaryEntry(source, target)]
        )
        matched = [
            offered_text(record)
            for record in records
            if glossary.get_active_entries_for_text(offered_text(record))
        ]
        counted.append(
            {
                "source": source,
                "target": target,
                "matched_prompt_count": len(matched),
                "matched_excerpts": matched[:excerpts],
            }
        )
    return counted


def after_translate(translation_config) -> None:
    """Hook run once the translator has finished with the whole document.

    Two things are only knowable here, both about the gap between what a human
    is shown and what the machine matches on. The draft gains the text each
    ruled-on paragraph was actually offered, which is what a reviewer needs to
    write a ruling that can match. An applied ruling gains, per pair, how many
    of those offered texts it reached; a pair that reached none is a ruling
    that silently did nothing, and is reported as a warning rather than left to
    be discovered from an unchanged rendering.
    """
    if not (
        translation_config.magazine_hitl_export or translation_config.magazine_hitl_apply
    ):
        return
    records = read_tracking(translation_config)
    if not records:
        return
    config = load_hitl_config()

    if translation_config.magazine_hitl_export:
        draft = _draft(translation_config)
        limit = int(config[_CONFIG_KEY_TRANSLATOR_VIEW_CHARS])
        for row in draft.get(TERMS_SECTION) or ():
            row[TRANSLATOR_VIEW_COLUMN] = translator_view(
                row.get("source") or "", records, limit
            )
        _write_draft(translation_config, draft)

    if not translation_config.magazine_hitl_apply:
        return
    report = _report(translation_config)
    applied = report.get(TERMS_SECTION)
    if not applied:
        return
    counted = match_counts(
        [(entry["source"], entry["target"]) for entry in applied["entries"]],
        records,
        int(config[_CONFIG_KEY_MATCHED_EXCERPTS]),
    )
    applied["match_definition"] = MATCH_DEFINITION
    applied["matches"] = counted
    _warn_unreached(counted)
    _write_report(translation_config, report)


def _warn_unreached(counted: list[dict]) -> None:
    unreached = [record["source"] for record in counted if not record["matched_prompt_count"]]
    if unreached:
        logger.warning(
            "hitl: %d ruled term(s) matched no input and changed nothing: %s",
            len(unreached),
            ", ".join(repr(source) for source in unreached),
        )


def after_repair(translation_config, offered: list[str]) -> None:
    """Hook run once the repair loop has finished with the document.

    The loop sends text to the engine that the translator never saw, so a pair
    counted after the translator alone is counted over part of the run. This
    recounts over both, which is the only count a reader of the report can act
    on: a pair reported as reaching nothing has to mean it reached nothing
    anywhere.
    """
    if not translation_config.magazine_hitl_apply or not offered:
        return
    report = _report(translation_config)
    applied = report.get(TERMS_SECTION)
    if not applied:
        return
    config = load_hitl_config()
    records = read_tracking(translation_config) + [
        {"input": text} for text in offered
    ]
    counted = match_counts(
        [(entry["source"], entry["target"]) for entry in applied["entries"]],
        records,
        int(config[_CONFIG_KEY_MATCHED_EXCERPTS]),
    )
    applied["match_definition"] = MATCH_DEFINITION
    applied["matches"] = counted
    applied[REPAIR_INPUTS_KEY] = len(offered)
    _warn_unreached(counted)
    _write_report(translation_config, report)


_STYLE = """
body { font: 13px/1.5 sans-serif; margin: 24px; color: #1a1a1a; }
h1 { font-size: 20px; }
h2 { font-size: 15px; margin-top: 28px; }
.meta { color: #555; margin-bottom: 20px; }
table { border-collapse: collapse; margin-top: 8px; }
td, th { padding: 2px 14px 2px 0; text-align: left; vertical-align: top;
         border-bottom: 1px solid #eee; }
th { color: #555; font-weight: 500; }
.empty { color: #888; font-style: italic; }
.flag { background: #ffe9a8; padding: 1px 6px; border-radius: 3px; font-size: 12px; }
code { background: #f4f4f4; padding: 0 3px; }
"""

# Column order each section is read in, and the key each column shows.
_COLUMNS = {
    TERMS_SECTION: (
        "source",
        "auto_target",
        "vote_count",
        "first_page",
        TRANSLATOR_VIEW_COLUMN,
    ),
    PAGE_KINDS_SECTION: ("page", "machine_kind", "conf", "ambiguous", "source"),
    DROP_CAPS_SECTION: (
        "paragraph",
        "page",
        "article_id",
        "size_ratio",
        "first_run",
        "excerpt",
    ),
}


def _cell(value: object) -> str:
    if value is None:
        return "&mdash;"
    if value is True:
        return '<span class="flag">yes</span>'
    if value is False:
        return "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    return html.escape(str(value))


def _section_html(name: str, rows: list) -> str:
    if not rows:
        return f'<h2>{html.escape(name)}</h2><p class="empty">empty</p>'
    columns = _COLUMNS.get(name) or tuple(rows[0])
    head = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{_cell(row.get(column))}</td>" for column in columns)
        + "</tr>"
        for row in rows
    )
    return (
        f"<h2>{html.escape(name)} <span class='meta'>({len(rows)} rows)</span></h2>"
        f"<table><tr>{head}</tr>{body}</table>"
    )


def render_review_html(draft: dict) -> str:
    """The draft as one page a human reads before writing a ruling.

    Text only and self-contained. What a page looks like is a question
    ``tools/page_classify_report.py`` already answers with thumbnails; this page
    answers what was decided and what a ruling would have to say to change it.
    """
    sample = draft.get("sample", "")
    body = "".join(
        _section_html(name, draft.get(name) or []) for name in sections()
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>review draft: {html.escape(sample)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<h1>Review draft: {html.escape(sample)}</h1>"
        f"<p class='meta'>Machine defaults, format version "
        f"{_cell(draft.get('format_version'))}. Rulings go in "
        f"<code>{html.escape(sample)}{DECISIONS_SUFFIX}</code>, which this "
        f"pipeline never writes.</p>"
        f"{body}</body></html>"
    )
