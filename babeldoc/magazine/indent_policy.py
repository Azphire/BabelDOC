"""The first line indent of a translated body paragraph, decided rather than copied.

Two facts about the pipeline meet here. The paragraph finder writes
``first_line_indent`` per paragraph by measuring the source: a paragraph whose
first character starts more than a point right of its own box is indented, and
one that does not is not. The typesetting stage reads that flag and, where it is
up, moves the pen in by a fixed multiple of a space width before setting the
first line. Between the two there was nowhere to state a rule, so a translated
page inherited the source language's paragraph convention one box at a time.

That is a defect once the two languages differ on the convention, and they do.
English magazine setting runs the opening paragraph of a section flush and
indents what follows, or runs everything flush with vertical space between
paragraphs; Chinese setting indents every paragraph, the first included. A
Chinese page built by copying English geometry is therefore wrong in a way no
amount of care in the copying can fix, because the copying is the error.

What this pass does is state the flag rather than adjust it. Where the mode has
an opinion, the flag every paragraph carries afterwards is this pass's answer
and nothing else's: it is the conjunction of five conditions -- the page admits
a paragraph convention, the label is running body text, some article claims this
paragraph, the mode indents a paragraph of this rank, and the paragraph opens
rather than resumes a chain -- and a paragraph failing any of them is set flush.
What the source geometry said,
and what the line splitting pass wrote on the fragments it made, are therefore
overwritten in both directions rather than only upward. It computes no geometry
and it sets no text. The stage that acts on the flag is not touched, which is
why the indent still moves the pen by the amount the stage has always moved it
-- the configuration pins that amount rather than setting it, and a gate holds
the stage to the pin.

Being the only writer is the point. A flag that three passes may raise and one
may lower has no answer to "why is this line indented" that can be read off any
one of them, and the contents page of a magazine is where that showed: the flag
arrived there from the source geometry, no pass had lowered it, and the page set
its records as if they were prose.

Two of the five conditions are ones this pass cannot see for itself, and it
reads both rather than forming a second opinion. A chain's later members are one
paragraph the layout broke into several, and a resumed paragraph opens no new
one, so indenting it prints a paragraph break the author did not write; assembly
already records which members those are. And running body text is not the same
thing as an article's running body text: an advertisement block, a sidebar or a
page whose classification fell back to the default type all carry body labels
without belonging to any article, and the canonical article grouping is what
already knows the difference. That answer is per paragraph rather than per page,
because a page belonging to a feature does not make everything printed on it
part of the feature.

Both readings are asked in the canonical page space -- the position of a page
inside the document this run holds -- because that is the space the article
grouping keyed its references in. A run over a selected page range carries two
page numbers for every page, and the physical one a reader sees appears only in
the record, alongside the canonical one, so nothing downstream has to guess
which space a number came from.

Where this sits
---------------

After the translation is written back and before the typesetting stage lays it
out, the same window the bracket folding pass uses. Earlier would be wrong twice
over: the flag would be read off a document whose paragraphs are still the
source's, and the line splitting pass writes the flag itself on the fragments it
makes, so a decision taken before it would be quietly undone.

What it does not touch
----------------------

A run whose mode is ``source``. That mode says the source convention is the one
to reproduce, so a pass claiming authority under it would be claiming the right
to overrule the answer it was told to give, and ``source`` would become a second
spelling of ``none``. Under it this pass decides nothing at all and every
paragraph keeps the flag it arrived with.

The page kind gate is read off the declared policy rather than off the kind's
name, so this pass names no page type. A page carrying no kind, or a kind the
vocabulary does not hold, is not eligible: an undeclared page sets its text
flush, which is the answer that adds nothing a reader has to unlearn.

The title pass writes the flag too, after the typesetting stage rather than
before it, and only on titles; the two do not meet, which the gate asserts from
both ends.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from babeldoc.magazine import chain_builder
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.cross_page_reflow import _physical_page_number
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import TAXONOMY_PATH
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path("indent_policy.json")

REPORT_NAME = "indent_policy.report.json"

# The switch, by the name the caller sets on the translation config. Down unless
# something puts it up: this pass changes how every body paragraph of a document
# is set, which is not something a run should acquire by upgrading.
SWITCH = "magazine_indent_policy"

# The policy flag a page is qualified by. Declared in the page type vocabulary
# and read by name here, which is what keeps page type names out of this module.
PAGE_ELIGIBILITY_POLICY_FLAG = "indent_eligible"

# Why a paragraph this pass decided is set flush. One reason per unmet
# condition, declared here rather than written at each site, so a reader of the
# sidecar meets a closed set. The names are the conditions, not the outcome: a
# paragraph flush for its page and one flush for its label are different
# findings and a sidecar that could not tell them apart would answer neither.
SKIP_PAGE_INELIGIBLE = "page_ineligible"
SKIP_OUTSIDE_BODY = "outside_body_labels"
SKIP_OUTSIDE_ARTICLE = "outside_article"
SKIP_MODE = "mode_decides_nothing"
CLEAR_CHAIN_CONTINUATION = "chain_continuation"
SKIP_REASONS = (
    SKIP_PAGE_INELIGIBLE,
    SKIP_OUTSIDE_BODY,
    SKIP_OUTSIDE_ARTICLE,
    SKIP_MODE,
    CLEAR_CHAIN_CONTINUATION,
)

# The order the unmet conditions are reported in. A paragraph may fail more than
# one, and the sidecar names the first in this order rather than all of them, so
# every flush paragraph carries exactly one reason. Page before label before
# article before mode before chain is widest first: the reason given is the one
# that would still hold if every narrower one were repaired. Article membership
# sits between label and mode because it is a fact about where the paragraph is,
# which is narrower than the label it carries and wider than the convention the
# mode chooses.
CLEAR_ORDER = (
    SKIP_PAGE_INELIGIBLE,
    SKIP_OUTSIDE_BODY,
    SKIP_OUTSIDE_ARTICLE,
    SKIP_MODE,
    CLEAR_CHAIN_CONTINUATION,
)

MODE_SOURCE = "source"
MODE_ALL = "all"
MODE_NONE = "none"
MODE_ALL_BUT_FIRST = "all_but_first"

BY_TARGET_KEY = "indent_mode_by_target"
FALLBACK_KEY = "fallback_mode"
VOCABULARY_KEY = "indent_mode_vocabulary"
ENTRIES_KEY = "entries"
_STRUCTURAL_KEYS = (BY_TARGET_KEY, FALLBACK_KEY)


class IndentPolicyError(ConfigError):
    """Raised when the indent policy configuration is malformed."""


@dataclass(frozen=True)
class IndentConfig:
    """Everything declared about deciding one paragraph's first line indent."""

    modes: tuple[str, ...]
    by_target: MappingProxyType
    fallback: str
    body_labels: tuple[str, ...]
    article_opening_rank: int
    indent_em: int
    excerpt_chars: int

    def mode_for(self, target_lang: str) -> tuple[str, str]:
        """The mode one run is laid out under, and where it came from.

        Matched by longest declared prefix rather than by equality, because a
        target language reaches this project as a tag and a tag carries a
        region: a rule for a language is a rule for every variety of it. A tag
        no entry claims takes the declared fallback, which reproduces the
        source, because a layout convention guessed for an unnamed language is
        worse than none.
        """
        tag = (target_lang or "").strip().lower()
        claimed = [key for key in self.by_target if tag.startswith(key.lower())]
        if not claimed:
            return self.fallback, "fallback"
        return self.by_target[max(claimed, key=len)], "declared"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IndentPolicyError(message)


def _read_by_target(raw: object, source: str, modes: tuple[str, ...]):
    """The table of per target language modes, checked against the vocabulary."""
    _require(isinstance(raw, dict), f"{source}: {BY_TARGET_KEY} must be an object")
    entries = raw.get(ENTRIES_KEY)
    _require(
        isinstance(entries, dict) and bool(entries),
        f"{source}: {BY_TARGET_KEY}.{ENTRIES_KEY} must be a non-empty object",
    )
    for key, value in entries.items():
        _require(
            isinstance(key, str) and bool(key.strip()),
            f"{source}: {BY_TARGET_KEY}.{ENTRIES_KEY} has a key that is not a "
            f"language tag: {key!r}",
        )
        _require(
            value in modes,
            f"{source}: {BY_TARGET_KEY}.{ENTRIES_KEY}[{key!r}]={value!r} is "
            f"outside the declared modes {sorted(modes)}",
        )
    return MappingProxyType({key.strip(): value for key, value in entries.items()})


def parse_indent_config(raw: dict, source: str) -> IndentConfig:
    """Validate one configuration mapping into the policy it declares."""
    flat = {key: value for key, value in raw.items() if key not in _STRUCTURAL_KEYS}
    try:
        parameters = dict(validate_bounded_config(flat, CONFIG_PATH))
    except ConfigError as exc:
        raise IndentPolicyError(str(exc)) from exc

    modes = tuple(parameters.get(VOCABULARY_KEY, ()))
    _require(bool(modes), f"{source}: missing {VOCABULARY_KEY}")
    for name in (MODE_SOURCE, MODE_ALL, MODE_NONE, MODE_ALL_BUT_FIRST):
        _require(
            name in modes,
            f"{source}: {VOCABULARY_KEY} omits {name!r}, which this pass acts on",
        )
    fallback = raw.get(FALLBACK_KEY)
    _require(
        fallback in modes,
        f"{source}: {FALLBACK_KEY}={fallback!r} is outside {sorted(modes)}",
    )
    labels = tuple(parameters.get("body_labels", ()))
    _require(bool(labels), f"{source}: missing body_labels")
    numbers = ("article_opening_rank", "indent_em", "excerpt_chars")
    missing = sorted(set(numbers) - set(parameters))
    _require(not missing, f"{source}: missing parameters {missing}")
    return IndentConfig(
        modes=modes,
        by_target=_read_by_target(raw.get(BY_TARGET_KEY), source, modes),
        fallback=str(fallback),
        body_labels=labels,
        article_opening_rank=int(parameters["article_opening_rank"]),
        indent_em=int(parameters["indent_em"]),
        excerpt_chars=int(parameters["excerpt_chars"]),
    )


@lru_cache(maxsize=1)
def load_indent_config(path: str | None = None) -> IndentConfig:
    """Load and validate ``configs/indent_policy.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise IndentPolicyError(f"{config_path.name}: root must be an object")
    return parse_indent_config(raw, config_path.name)


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def article_of_element(
    article_document_ir: ArticleDocumentIR | None,
) -> dict[str, str]:
    """Which article each paragraph belongs to in the canonical runtime state.

    Keyed by the canonical source reference, one entry per paragraph, rather
    than by page: a page belonging to an article does not make every paragraph
    on it that article's running text, and an advertisement block sharing a page
    with a feature is not part of the feature. A paragraph the article builder
    never claimed - fixed artwork, a stray rule, anything on a page whose
    classification failed into the default type - is simply absent here, which
    is the answer this pass wants.
    """
    if article_document_ir is None:
        return {}
    return dict(article_document_ir.by_element)


def mode_is_authoritative(mode: str) -> bool:
    """Whether this mode gives the pass an answer of its own to write."""
    return mode != MODE_SOURCE


def mode_indents(mode: str, body_rank: int | None, config: IndentConfig) -> bool:
    """Whether the mode alone would indent a body paragraph of this rank.

    Asked only of a mode that is authoritative, so ``source`` never reaches
    here. A rank the article numbering could not supply is not the opening
    paragraph of anything, so a mode that exempts the opening paragraph indents
    it: the exemption is a statement about a position, and a paragraph outside
    every article holds no position to be exempted at.
    """
    if mode == MODE_ALL:
        return True
    if mode == MODE_NONE:
        return False
    if mode == MODE_ALL_BUT_FIRST:
        return body_rank != config.article_opening_rank
    return False


def decide(
    label: str | None,
    mode: str,
    eligible_page: bool,
    in_article: bool,
    body_rank: int | None,
    continuation: bool,
    config: IndentConfig,
) -> tuple[bool, str | None] | None:
    """What one paragraph's flag becomes and the condition that decided it.

    ``None`` where the mode is not authoritative, which is the one case this
    pass leaves a paragraph as it found it. Otherwise the flag is the
    conjunction of the five conditions and the second member names the first
    unmet one, or is ``None`` where all five are met.
    """
    if not mode_is_authoritative(mode):
        return None
    unmet = {
        SKIP_PAGE_INELIGIBLE: not eligible_page,
        SKIP_OUTSIDE_BODY: label not in config.body_labels,
        SKIP_OUTSIDE_ARTICLE: not in_article,
        SKIP_MODE: not mode_indents(mode, body_rank, config),
        CLEAR_CHAIN_CONTINUATION: continuation,
    }
    for reason in CLEAR_ORDER:
        if unmet[reason]:
            return False, reason
    return True, None


def as_record(
    config: IndentConfig,
    mode: str,
    origin: str,
    target_lang: str,
    rows: list[dict],
    pages: list[dict],
) -> dict:
    changed = [row for row in rows if row["before"] != row["after"]]
    return {
        "switch": SWITCH,
        "target_lang": target_lang,
        "mode": mode,
        "mode_source": origin,
        "modes": list(config.modes),
        "fallback_mode": config.fallback,
        "body_labels": list(config.body_labels),
        "article_opening_rank": config.article_opening_rank,
        "indent_em": config.indent_em,
        "page_eligibility_flag": PAGE_ELIGIBILITY_POLICY_FLAG,
        "skip_reasons": list(SKIP_REASONS),
        "pages": len(pages),
        "page_records": pages,
        "authoritative": mode_is_authoritative(mode),
        "totals": {
            "paragraphs": len(rows),
            "decided": sum(1 for row in rows if row["decided"]),
            "left_alone": sum(1 for row in rows if not row["decided"]),
            "changed": len(changed),
            "cleared": sum(1 for row in rows if row["cleared"]),
            "raised": sum(1 for row in rows if row["after"] and not row["before"]),
            "chain_continuations": sum(
                1 for row in rows if row["chain_continuation"]
            ),
            "indented_after": sum(1 for row in rows if row["after"]),
            "paragraphs_in_article": sum(1 for row in rows if row["in_article"]),
            "paragraphs_outside_article": sum(
                1 for row in rows if not row["in_article"]
            ),
            "pages_eligible": sum(1 for page in pages if page["indent_eligible"]),
            "pages_ineligible": sum(
                1 for page in pages if not page["indent_eligible"]
            ),
            "skipped": {
                reason: sum(1 for row in rows if row["skipped"] == reason)
                for reason in SKIP_REASONS
            },
        },
        "paragraphs": rows,
    }


def _require_conservation(record: dict) -> None:
    """Every paragraph is accounted for exactly once, or the record is a lie.

    The first equation holds in every mode: a paragraph is either one this pass
    decided or one it left alone. The second holds only where the mode is
    authoritative, because a pass that declines to decide records ``SKIP_MODE``
    for every paragraph without setting any of them, so the skipped tally and
    the surviving indents would double count the same paragraph.
    """
    totals = record["totals"]
    paragraphs = totals["paragraphs"]
    if totals["decided"] + totals["left_alone"] != paragraphs:
        raise IndentPolicyError(
            f"indent policy decided {totals['decided']} and left alone "
            f"{totals['left_alone']} of {paragraphs} paragraph(s)"
        )
    if not record["authoritative"]:
        return
    skipped = sum(totals["skipped"].values())
    if skipped + totals["indented_after"] != paragraphs:
        raise IndentPolicyError(
            f"indent policy skipped {skipped} and indented "
            f"{totals['indented_after']} of {paragraphs} paragraph(s)"
        )


def write_report(working_dir: Path, record: dict) -> Path:
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH, TAXONOMY_PATH])
    return path


def page_is_eligible(page, taxonomy) -> tuple[bool, str | None]:
    """Whether one page's declared policy admits a paragraph convention.

    Returns the answer and the kind it was read from, so the record can say
    which page the answer belongs to without this module naming a type. A kind
    the vocabulary does not hold has no policy to consume and is not eligible:
    the caller states what an absent policy means rather than the vocabulary
    handing back a default that looks declared.
    """
    kind = getattr(page, "page_kind", None)
    policy = taxonomy.policy_of(kind)
    if policy is None:
        return False, kind
    return bool(policy.get(PAGE_ELIGIBILITY_POLICY_FLAG, False)), kind


def apply(
    translation_config,
    docs,
    article_document_ir: ArticleDocumentIR | None = None,
) -> dict | None:
    """Decide the first line indent of every paragraph. None where the switch is down.

    Returns the record it wrote, so a caller holding the document can assert
    about the pass without reading the sidecar back.

    Three gates stand in front of the decision and all three are declarative.
    The page gate asks the page type vocabulary whether this page sets the kind
    of text a paragraph convention is written for; the label gate asks whether
    this paragraph is running body text; the article gate asks whether the
    canonical article grouping claimed this paragraph as part of an article at
    all. A paragraph that fails any of them is recorded with the reason it
    failed by, because a paragraph left alone by the page it sits on, one left
    alone by its own label and one left alone because it belongs to no article
    are three different findings and a sidecar that could not tell them apart
    would answer none of them.
    """
    if not enabled(translation_config):
        return None
    if article_document_ir is None:
        raise IndentPolicyError(
            "indent policy requires the canonical ArticleDocumentIR"
        )
    config = load_indent_config()
    taxonomy = load_taxonomy()
    target_lang = getattr(translation_config, "lang_out", "") or ""
    mode, origin = config.mode_for(target_lang)
    of_element = article_of_element(article_document_ir)

    rank_of_article: dict[str, int] = {}
    rows: list[dict] = []
    page_rows: list[dict] = []
    # Iterated in the canonical page space, one position per page of the
    # document this run actually holds, because that is the space the article
    # builder keyed its references in. The physical page a reader sees is
    # derived per page and used only to name things in the record: a run over a
    # selected page range has two page numbers for every page, and asking one
    # space a question the other space answered is how a paragraph ends up
    # holding a neighbour's article.
    for position, page in enumerate(docs.page):
        canonical_page = position + 1
        physical_page = _physical_page_number(docs, canonical_page)
        if physical_page is None:
            raise IndentPolicyError(
                f"canonical page {canonical_page} has no physical page number"
            )
        eligible, kind = page_is_eligible(page, taxonomy)
        decided_here = 0
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            canonical_ref = f"p{canonical_page}#{index}"
            article_id = of_element.get(canonical_ref)
            in_article = article_id is not None
            layout_label = paragraph.layout_label
            in_body = layout_label in config.body_labels
            body_rank = None
            # Counted over body paragraphs carrying text, in document order
            # within the article, which is the rank the drop cap pass counts.
            # A paragraph with no text is not a paragraph a reader numbers.
            # Counted on every page, eligible or not, because the rank belongs
            # to that pass and not to this one: withholding a decision here may
            # not renumber the article for the pass that shares the count.
            if in_body and in_article and (paragraph.unicode or "").strip():
                body_rank = rank_of_article.get(article_id, 0) + 1
                rank_of_article[article_id] = body_rank
            before = bool(paragraph.first_line_indent)
            continuation = chain_builder.is_chain_continuation(paragraph)
            decision = decide(
                layout_label,
                mode,
                eligible,
                in_article,
                body_rank,
                continuation,
                config,
            )
            if decision is None:
                skipped = SKIP_MODE
            else:
                value, skipped = decision
                paragraph.first_line_indent = value
                decided_here += 1
            after = bool(paragraph.first_line_indent)
            rows.append(
                {
                    "page": physical_page,
                    "canonical_page": canonical_page,
                    "reference": paragraph_reference(physical_page, index),
                    "canonical_ref": canonical_ref,
                    "layout_label": layout_label,
                    "page_kind": kind,
                    "indent_eligible_page": eligible,
                    "article_id": article_id,
                    "in_article": in_article,
                    "body_rank": body_rank,
                    "chain_continuation": continuation,
                    "before": before,
                    "after": after,
                    "decided": decision is not None,
                    "cleared": before and not after,
                    "skipped": skipped,
                    "excerpt": (paragraph.unicode or "")[: config.excerpt_chars],
                }
            )
        page_rows.append(
            {
                "page": physical_page,
                "canonical_page": canonical_page,
                "page_kind": kind,
                "indent_eligible": eligible,
                "paragraphs": len(page.pdf_paragraph or ()),
                "decided": decided_here,
            }
        )

    record = as_record(config, mode, origin, target_lang, rows, page_rows)
    _require_conservation(record)
    working_dir = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    write_report(working_dir, record)
    logger.debug(
        "indent policy: mode %s, %d of %d page(s) eligible, %d paragraph(s) "
        "decided, %d changed",
        mode,
        record["totals"]["pages_eligible"],
        record["pages"],
        record["totals"]["decided"],
        record["totals"]["changed"],
    )
    return record
