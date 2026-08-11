"""Drop cap candidates, and the verdict a human returns on them.

A drop cap is the oversized initial a magazine opens a piece of running text
with. It is a typographic decision rather than a linguistic one, and it is not
one a translation can take on its own: the initial is a style run of a single
character, and a target language that renders that character as part of a word
leaves the paragraph with an inset first line and nothing to fill it. So this
module finds the paragraphs that carry one and says so in the intermediate
language, and the review layer beside it carries the finding out to a human and
the ruling back in.

Three signals decide a candidate, all general, all bounded in
``configs/drop_cap.json``, and none of them naming a publication or a page type.

The paragraph is body text, by the label vocabulary every other stage reads. It
belongs to an article, and stands within the first few body paragraphs of it or
on the page that article opens on -- which is where an opening initial goes, and
which is why this needs the article map: a paragraph in no article is never a
candidate, and a run without the grouping stage has no map to read. Its first
style run is large against the paragraph's own median character size and short
enough to be an initial rather than a heading the paragraph finder swept in.

The size ratio is measured against the paragraph's median rather than the
document's: a magazine sets its body text at several sizes, and what makes an
initial an initial is that it towers over the text it opens, not over the
average of the issue.

The switch is ``magazine_drop_cap_mark``, down by default, and it is an
attribute of the translation configuration rather than a constructor parameter
of it: this batch adds nothing upstream, so the flag is read from whatever the
caller set on the object and is off wherever nobody set it (see W-B7-02). It
requires ``magazine_article_group``, and a run that raises one without the other
is refused rather than quietly marking nothing, because a run that was asked for
candidates and produced none has to be a run that found none.

Nothing consumes the ruling. ``dropCapDecision`` is written into the
intermediate language and read by no stage in this batch: making typesetting act
on a verdict is a batch of its own. The sidecar this module writes says so too,
so a run whose ruling appears to have changed nothing is explained by its own
inventory rather than by reading the code.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine import article_builder
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "drop_cap.json"

REPORT_NAME = "drop_cap.report.json"

# Where the body label vocabulary is declared, once for the whole project.
BODY_LABELS_KEY = "body_labels"

# The two switches, by the names the caller sets on the translation config.
MARK_SWITCH = "magazine_drop_cap_mark"
GROUP_SWITCH = "magazine_article_group"

# How a decisions file names one paragraph: its one-based file page and its
# position among that page's paragraphs. Neither half is generated per run, so a
# reference a human writes after the first pass still names the same paragraph on
# the second, which a debug id -- minted afresh on every run -- would not.
REFERENCE_FORMAT = "p{page}#{index}"


class DropCapError(ConfigError):
    """Raised when the drop cap configuration or its dependencies are wrong."""


@dataclass(frozen=True)
class DropCapConfig:
    """Everything bounded about finding one candidate."""

    min_first_run_size_ratio: float
    max_first_run_chars: int
    max_body_rank_in_article: int
    excerpt_chars: int


@lru_cache(maxsize=1)
def load_drop_cap_config(path: str | None = None) -> DropCapConfig:
    """Load and validate ``configs/drop_cap.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = validate_bounded_config(raw, config_path)
    missing = sorted(set(DropCapConfig.__dataclass_fields__) - set(parameters))
    if missing:
        raise DropCapError(f"{config_path.name}: missing parameters {missing}")
    return DropCapConfig(
        min_first_run_size_ratio=float(parameters["min_first_run_size_ratio"]),
        max_first_run_chars=int(parameters["max_first_run_chars"]),
        max_body_rank_in_article=int(parameters["max_body_rank_in_article"]),
        excerpt_chars=int(parameters["excerpt_chars"]),
    )


def body_labels() -> tuple[str, ...]:
    """Layout labels that count as running text, in declaration order."""
    return tuple(load_chain_config()[BODY_LABELS_KEY])


def mark_enabled(translation_config) -> bool:
    return bool(getattr(translation_config, MARK_SWITCH, False))


def require_dependencies(translation_config) -> None:
    """Refuse a run that asks for marking without the stage marking needs."""
    if not mark_enabled(translation_config):
        return
    if not getattr(translation_config, GROUP_SWITCH, False):
        raise DropCapError(
            f"{MARK_SWITCH} requires {GROUP_SWITCH}: a candidate is decided "
            f"against the article it belongs to, and without the grouping stage "
            f"there is no article map to decide it against"
        )


def paragraph_reference(page_label: int, index: int) -> str:
    """How one paragraph is named in the review draft and in a decisions file."""
    return REFERENCE_FORMAT.format(page=page_label, index=index)


def document_references(labeled_pages) -> set[str]:
    """Every reference the paragraphs of one document answer to."""
    return {
        paragraph_reference(label, index)
        for label, page in labeled_pages
        for index in range(len(page.pdf_paragraph))
    }


def first_style_run(paragraph):
    """The paragraph's opening style run, as (font size, text).

    Only the first composition is consulted. A paragraph whose text does not
    begin with a run of characters -- one opening with a formula, or one no
    styling pass has grouped -- opens with no initial either.
    """
    compositions = paragraph.pdf_paragraph_composition or []
    if not compositions:
        return None, ""
    run = compositions[0].pdf_same_style_characters
    if run is None or run.pdf_style is None:
        return None, ""
    text = "".join(character.char_unicode or "" for character in run.pdf_character)
    return run.pdf_style.font_size, text


def median_font_size(paragraph) -> float | None:
    """The median size over every character of the paragraph."""
    sizes: list[float] = []
    for composition in paragraph.pdf_paragraph_composition or []:
        for holder in (
            composition.pdf_same_style_characters,
            composition.pdf_line,
            composition.pdf_formula,
        ):
            if holder is None:
                continue
            sizes.extend(
                character.pdf_style.font_size
                for character in holder.pdf_character
                if character.pdf_style is not None and character.pdf_style.font_size
            )
    return statistics.median(sizes) if sizes else None


@dataclass(frozen=True)
class Candidate:
    """One paragraph that opens with what looks like a drop cap."""

    reference: str
    page: int
    index: int
    debug_id: str | None
    article_id: str | None
    body_rank: int
    opens_article: bool
    size_ratio: float
    first_run: str
    excerpt: str

    def as_record(self) -> dict:
        return {
            "paragraph": self.reference,
            "page": self.page,
            "debug_id": self.debug_id,
            "article_id": self.article_id,
            "body_rank": self.body_rank,
            "opens_article": self.opens_article,
            "size_ratio": round(self.size_ratio, 4),
            "first_run": self.first_run,
            "excerpt": self.excerpt,
        }


def read_article_map(path: Path) -> tuple[dict[int, str], set[int]]:
    """Which article each page belongs to, and the pages articles open on."""
    with path.open(encoding="utf-8") as f:
        report = json.load(f)
    article_of_page: dict[int, str] = {}
    openers: set[int] = set()
    for article in report.get("articles", ()):
        openers.add(int(article["start_page"]))
        for page in article.get("pages", ()):
            article_of_page[int(page)] = article.get("article_id")
    return article_of_page, openers


def find_candidates(
    labeled_pages,
    article_of_page: dict[int, str],
    openers: set[int],
    config: DropCapConfig,
    labels: tuple[str, ...],
) -> list[Candidate]:
    """Every candidate of one document, in page then paragraph order."""
    found: list[Candidate] = []
    rank_of_article: dict[str, int] = {}
    for label, page in labeled_pages:
        article_id = article_of_page.get(label)
        for index, paragraph in enumerate(page.pdf_paragraph):
            text = (paragraph.unicode or "").strip()
            if paragraph.layout_label not in labels or not text:
                continue
            if article_id is None:
                # A paragraph outside every article is measured against no
                # article, so the position signal cannot be satisfied at all.
                continue
            rank = rank_of_article.get(article_id, 0) + 1
            rank_of_article[article_id] = rank
            opens = label in openers
            if rank > config.max_body_rank_in_article and not opens:
                continue
            size, run_text = first_style_run(paragraph)
            median = median_font_size(paragraph)
            if not size or not median:
                continue
            initial = run_text.strip()
            # An initial is a character. A first run holding only the space
            # after one is not the initial itself, whatever it is set at.
            if not initial or len(initial) > config.max_first_run_chars:
                continue
            ratio = size / median
            if ratio < config.min_first_run_size_ratio:
                continue
            found.append(
                Candidate(
                    reference=paragraph_reference(label, index),
                    page=label,
                    index=index,
                    debug_id=paragraph.debug_id,
                    article_id=article_id,
                    body_rank=rank,
                    opens_article=opens,
                    size_ratio=ratio,
                    first_run=initial,
                    excerpt=text[: config.excerpt_chars],
                )
            )
    return found


def mark(translation_config, labeled_pages) -> list[Candidate]:
    """Find the candidates of one document and say so in the document.

    Returns them in page order, empty where the switch is down. Only a candidate
    is written: a paragraph that is not one carries no attribute at all, so a run
    with the switch down and a run that found nothing leave the same document.
    """
    require_dependencies(translation_config)
    if not mark_enabled(translation_config):
        return []
    config = load_drop_cap_config()
    map_path = Path(
        translation_config.get_working_file_path(article_builder.REPORT_NAME)
    )
    if not map_path.exists():
        raise DropCapError(
            f"{map_path.name} is not beside this run; the grouping stage writes "
            f"it and {MARK_SWITCH} needs it"
        )
    article_of_page, openers = read_article_map(map_path)
    pages = dict(labeled_pages)
    candidates = find_candidates(
        labeled_pages, article_of_page, openers, config, body_labels()
    )
    for candidate in candidates:
        pages[candidate.page].pdf_paragraph[candidate.index].drop_cap_candidate = True
    _write_report(translation_config, config, candidates)
    logger.debug("drop cap: %d candidate(s)", len(candidates))
    return candidates


def _write_report(
    translation_config, config: DropCapConfig, candidates: list[Candidate]
) -> Path:
    report = {
        "counts": {
            "candidates": len(candidates),
            "articles": len({c.article_id for c in candidates}),
            "pages": len({c.page for c in candidates}),
        },
        "parameters": {
            "min_first_run_size_ratio": config.min_first_run_size_ratio,
            "max_first_run_chars": config.max_first_run_chars,
            "max_body_rank_in_article": config.max_body_rank_in_article,
            "excerpt_chars": config.excerpt_chars,
        },
        "body_labels": list(body_labels()),
        "reference_format": REFERENCE_FORMAT,
        "candidates": [candidate.as_record() for candidate in candidates],
        # What reads the verdict a human returns, which in this batch is
        # nothing: the field is carried in the intermediate language and acted
        # on by no stage until typesetting is taught to.
        "decision_consumers": [],
    }
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    with path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
    record_config_manifest(path.parent, [CONFIG_PATH])
    return path


def review_rows(candidates: list[Candidate]) -> list[dict]:
    """The candidates as the review draft states them, one row each."""
    return [
        {
            "paragraph": candidate.reference,
            "page": candidate.page,
            "article_id": candidate.article_id,
            "size_ratio": round(candidate.size_ratio, 3),
            "first_run": candidate.first_run,
            "excerpt": candidate.excerpt,
        }
        for candidate in candidates
    ]


def apply_decisions(labeled_pages, verdicts: dict[str, str]) -> list[dict]:
    """Write the ruled verdicts into the document, one paragraph at a time.

    A ruling may name a paragraph the marking pass did not flag, exactly as a
    ruling on terms may name a source the extractor never proposed: the human is
    the authority on what carries an initial, and the candidate list is the
    machine's opening bid rather than the set of questions allowed.
    """
    records: list[dict] = []
    if not verdicts:
        return records
    for label, page in labeled_pages:
        for index, paragraph in enumerate(page.pdf_paragraph):
            verdict = verdicts.get(paragraph_reference(label, index))
            if verdict is None:
                continue
            records.append(
                {
                    "paragraph": paragraph_reference(label, index),
                    "page": label,
                    "debug_id": paragraph.debug_id,
                    "was_candidate": bool(paragraph.drop_cap_candidate),
                    "decision": verdict,
                }
            )
            paragraph.drop_cap_decision = verdict
    return records
