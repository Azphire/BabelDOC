"""M3, the lexical translation consistency ratio, by the pairwise definition.

The definition is ``eq:ltcr`` of ``docs/dissertation/background_chapter.tex``,
after lyu2021ltcr: for a source word :math:`w` occurring :math:`k` times in a
document with word-aligned translations :math:`(t_1, \\dots, t_k)`,

.. math::

    \\mathrm{LTCR}(w) =
      \\frac{\\sum_{i=1}^{k}\\sum_{j=i+1}^{k}\\mathbf{1}(t_i = t_j)}{C_k^2}
      \\times 100\\%,

extended to a corpus by summing numerators and denominators over all words of
interest rather than by averaging per word.

**The one deviation, stated plainly.** ``eq:ltcr`` presupposes a word alignment,
and this project has none anywhere. So :math:`t_i` is not read; it is derived,
and the derivation is declared here rather than buried:

1. The term's translated paragraphs are searched for the most widely shared
   substring that stays out of the article's other translated paragraphs -- the
   candidate search this module owns and ``tools/term_consistency.py`` calls.
   Every paragraph carrying that substring is labelled with it.
2. The paragraphs it did not cover are searched again the same way, and again,
   until no substring is shared by two of the remainder.
3. :math:`t_i` is the label paragraph :math:`i` came out with, a paragraph
   labelled by nothing being its own singleton. The pair :math:`(i, j)` counts
   when the two carry the same label.

So the labels partition the :math:`k` paragraphs into groups of sizes
:math:`m_1 \\ge m_2 \\ge \\dots \\ge m_g`, and the metric is exactly

.. math::

    \\mathrm{LTCR}(w) = \\frac{\\sum_{t} \\binom{m_t}{2}}{\\binom{k}{2}}.

**Its relation to what this project measured before.** Batch b6.3's quantity --
the share of a term's own paragraphs carrying the single best candidate,
:math:`m_1/k` -- is reported beside it under the name ``legacy_share``, because
the contract forbids relabelling it as LTCR. The two are related exactly, and
the relation is an assertion of the gate rather than a remark:

* :math:`\\mathrm{LTCR}(w) \\le \\texttt{legacy\\_share}(w)`, always. The legacy
  share is :math:`m_1/k`, and writing
  :math:`\\sum_t m_t(m_t-1) \\le m_1 \\sum_t (m_t - 1) = m_1(k-g) \\le m_1(k-1)`
  and dividing by :math:`k(k-1)` gives it.
* :math:`\\mathrm{LTCR}(w) = 1` if and only if :math:`\\texttt{legacy\\_share}(w) = 1`,
  since either forces a single group of size :math:`k`.
* :math:`\\mathrm{LTCR}(w) = 0` if and only if
  :math:`\\texttt{legacy\\_share}(w) = 1/k`, since either says every group is a
  singleton and no two paragraphs agree.

They do **not** agree at :math:`k = 2`, and the disagreement is the point: two
paragraphs rendering a term differently score :math:`1/2` under the old measure
-- one of two paragraphs carries the best rendering there is, which is
vacuously the one it carries itself -- and :math:`0` here, because the only pair
there is disagrees. The gap is the price of the pairwise reading, and it is
paid throughout: a term rendered two ways in four paragraphs scores :math:`0.5`
under the old measure and :math:`0.333` here. The second number is the one the
paper may call LTCR.

Ledger row G-04 records the known weakness both inherit -- four of thirty-eight
candidate rows were unusable, the search having found a piece of the sentence
around the term rather than the term. The pairwise reading does not fix that;
the candidate reported beside each group is what makes it visible.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from math import comb
from pathlib import Path

from babeldoc.magazine.metrics import MetricsConfig
from babeldoc.magazine.metrics import load_metrics_config
from babeldoc.magazine.metrics import rounded
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("term_consistency.json")

# A word: letters only, with internal apostrophes and hyphens kept, so a name
# carrying one stays a single token. The joiners are written as escapes to keep
# this file ASCII, as the configuration files are.
_JOINERS = "'" + "".join(map(chr, (0x2019, 0x2010, 0x2011, 0x2012, 0x2013))) + "-"
_WORD = re.compile(rf"[^\W\d_]+(?:[{_JOINERS}][^\W\d_]+)*")

# What the translator puts into a paragraph's text that is not text: the rich
# text tags it asks the model to carry through unchanged, and the placeholders
# standing for formulas. Both are stripped from a translation before candidate
# renderings are generated from it, because a candidate is a piece of what a
# reader reads and neither of these is read at all. Removed rather than spaced
# out: a tag occupies no width on the page, so the characters either side of one
# are adjacent to the reader as well.
_MARKUP = re.compile(r"<[^<>]*>|\{\s*v\s*\d+\s*\}")


@dataclass(frozen=True)
class Config:
    """The source term qualification and the candidate search, bounded."""

    min_article_occurrences: int
    source_term_min_chars: int
    connector_max_chars: int
    candidate_min_chars: int
    candidate_max_chars: int
    candidate_max_outside_share: float
    max_terms_per_article: int


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> Config:
    """Load and validate ``configs/term_consistency.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = validate_bounded_config(raw, config_path)
    missing = sorted(set(Config.__dataclass_fields__) - set(parameters))
    if missing:
        raise KeyError(f"{config_path.name}: missing parameters {missing}")
    return Config(
        min_article_occurrences=int(parameters["min_article_occurrences"]),
        source_term_min_chars=int(parameters["source_term_min_chars"]),
        connector_max_chars=int(parameters["connector_max_chars"]),
        candidate_min_chars=int(parameters["candidate_min_chars"]),
        candidate_max_chars=int(parameters["candidate_max_chars"]),
        candidate_max_outside_share=float(parameters["candidate_max_outside_share"]),
        max_terms_per_article=int(parameters["max_terms_per_article"]),
    )


# --- what a translation is read as -------------------------------------------


def strip_markup(text: str) -> str:
    """A translation with the tags and placeholders taken out of it.

    Input cleaning only: what is measured, and how, is unchanged. It is applied
    to every translation the run produced, so a candidate is counted inside and
    outside a term's paragraphs against the same cleaned text.
    """
    return _MARKUP.sub("", text)


# --- source side: which terms recur ------------------------------------------


def tokens_of(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in _WORD.finditer(text)]


def sentence_openings(
    text: str, tokens: list[tuple[str, int, int]], terminals
) -> list[bool]:
    """Whether each token opens a sentence, read from the declared enders."""
    flags: list[bool] = []
    previous_end = 0
    for index, (_word, start, end) in enumerate(tokens):
        gap = text[previous_end:start]
        flags.append(index == 0 or any(char in terminals for char in gap))
        previous_end = end
    return flags


def capitalised(word: str) -> bool:
    return bool(word) and word[0].isupper()


def terms_in(text: str, terminals, config: Config) -> list[tuple[tuple[str, ...], bool]]:
    """Every maximal run of capitalised words, with whether it ever ran mid-sentence.

    A short lower case word is allowed inside a run when a capitalised word
    follows it, which keeps a name carrying a particle in one piece. The bound
    is a length rather than a list of words, so no language's function words are
    written down here.
    """
    tokens = tokens_of(text)
    opens = sentence_openings(text, tokens, terminals)
    found: list[tuple[tuple[str, ...], bool]] = []
    index = 0
    while index < len(tokens):
        if not capitalised(tokens[index][0]):
            index += 1
            continue
        run = [tokens[index][0]]
        non_initial = not opens[index]
        cursor = index + 1
        while cursor < len(tokens):
            word = tokens[cursor][0]
            if capitalised(word):
                run.append(word)
                non_initial = non_initial or not opens[cursor]
                cursor += 1
                continue
            follows = cursor + 1 < len(tokens) and capitalised(tokens[cursor + 1][0])
            if follows and len(word) <= config.connector_max_chars:
                run.append(word)
                cursor += 1
                continue
            break
        found.append((tuple(run), non_initial))
        index = cursor
    return found


# --- target side: how a term was rendered ------------------------------------


def opens_with_punctuation(piece: str) -> bool:
    """Whether a candidate begins on a mark rather than on a word.

    A substring starting at a comma or a dash is a piece of the sentence around
    a term, not a piece of the term: the mark before a rendering says where the
    clause broke, and two paragraphs sharing one share the punctuation habit of
    the model rather than a name. The batch-b6.3 sweep left two such candidates
    standing under every setting of the tuning grid.
    """
    return bool(piece) and unicodedata.category(piece[0]).startswith("P")


def candidates_from(text: str, config: Config) -> set[str]:
    """Every whitespace-free substring of the declared lengths, word-initial."""
    found: set[str] = set()
    for length in range(config.candidate_min_chars, config.candidate_max_chars + 1):
        for start in range(0, len(text) - length + 1):
            piece = text[start : start + length]
            if any(char.isspace() for char in piece):
                continue
            if opens_with_punctuation(piece):
                continue
            found.add(piece)
    return found


def rendering(inside: list[str], outside: list[str], config: Config):
    """The most widely shared distinctive substring of ``inside``, and its share.

    Candidates are drawn from the shortest translation only: a string shared by
    all of them is in that one too, and generating from every translation costs
    more than the answer is worth. Counting inside comes first because it is
    cheap, and the outside filter is applied only to the candidates that could
    still win, which keeps the work bounded on a long article.
    """
    if len(inside) < 2:
        return None, None
    shortest = min(inside, key=len)
    by_count: dict[int, list[str]] = defaultdict(list)
    for candidate in candidates_from(shortest, config):
        count = sum(1 for text in inside if candidate in text)
        if count >= 2:
            by_count[count].append(candidate)

    outside_total = len(outside)
    for count in sorted(by_count, reverse=True):
        for candidate in sorted(by_count[count], key=lambda item: (-len(item), item)):
            if outside_total:
                share = sum(1 for text in outside if candidate in text) / outside_total
                if share > config.candidate_max_outside_share:
                    continue
            return count / len(inside), candidate
    return 1 / len(inside), None


# --- the pairwise reading -----------------------------------------------------


@dataclass(frozen=True)
class Grouping:
    """How the renderings of one term partition its paragraphs."""

    groups: tuple[tuple[int, ...], ...]
    candidates: tuple[str | None, ...]

    @property
    def sizes(self) -> tuple[int, ...]:
        return tuple(len(group) for group in self.groups)


def rendering_groups(inside: list[str], outside: list[str], config: Config) -> Grouping:
    """Partition a term's translated paragraphs by the rendering they carry.

    The candidate search is run, the paragraphs it covered are taken out, and it
    is run again on what is left, until no substring is shared by two of the
    remainder. Each round's survivors form one group; whatever never joins a
    group is a group of one, since a paragraph whose rendering nothing else
    shares agrees with nothing.

    Order is deterministic and does not depend on dictionary iteration: rounds
    come out largest first because the search returns the most widely shared
    candidate, and ties inside the search are already broken by length and then
    by the string itself.
    """
    remaining = list(range(len(inside)))
    groups: list[tuple[int, ...]] = []
    candidates: list[str | None] = []
    while len(remaining) >= 2:
        texts = [inside[index] for index in remaining]
        _share, candidate = rendering(texts, outside, config)
        if candidate is None:
            break
        covered = tuple(index for index in remaining if candidate in inside[index])
        if len(covered) < 2:
            break
        groups.append(covered)
        candidates.append(candidate)
        remaining = [index for index in remaining if index not in set(covered)]
    for index in remaining:
        groups.append((index,))
        candidates.append(None)
    return Grouping(groups=tuple(groups), candidates=tuple(candidates))


def ltcr_of(inside: list[str], outside: list[str], config: Config) -> dict:
    """LTCR for one term, with the legacy share and the grouping beside it.

    ``pairs_total`` and ``pairs_agreeing`` are carried out rather than only the
    ratio, because a corpus level LTCR sums numerators and denominators and
    cannot be recovered from per term ratios.
    """
    measured = len(inside)
    if measured < 2:
        return {
            "k": measured,
            "pairs_total": 0,
            "pairs_agreeing": 0,
            "ltcr": None,
            "legacy_share": None,
            "legacy_candidate": None,
            "group_sizes": [],
            "group_candidates": [],
        }
    grouping = rendering_groups(inside, outside, config)
    legacy_share, legacy_candidate = rendering(inside, outside, config)
    agreeing = sum(comb(size, 2) for size in grouping.sizes)
    total = comb(measured, 2)
    return {
        "k": measured,
        "pairs_total": total,
        "pairs_agreeing": agreeing,
        "ltcr": agreeing / total,
        "legacy_share": legacy_share,
        "legacy_candidate": legacy_candidate,
        "group_sizes": list(grouping.sizes),
        "group_candidates": list(grouping.candidates),
    }


# --- one document -------------------------------------------------------------


def qualifying_terms(
    sources: dict[str, str],
    terminals,
    config: Config,
    metrics: MetricsConfig,
) -> list[tuple[str, list[str], int]]:
    """The measurable terms of one region: the term, its paragraphs, its occurrences.

    A term qualifies on the source side alone -- it recurs at least
    ``ltcr_min_occurrences`` times, it is long enough, and it occurs at least
    once away from a sentence opening so that an ordinary word capitalised only
    by a full stop before it does not enter -- and is measurable when those
    occurrences fall in at least ``ltcr_min_paragraphs`` distinct paragraphs,
    below which the combination :math:`C_k^2` has no pair in it.
    """
    occurrences: dict[tuple[str, ...], int] = defaultdict(int)
    non_initial: dict[tuple[str, ...], bool] = defaultdict(bool)
    holders: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for debug_id, text in sources.items():
        seen: set[tuple[str, ...]] = set()
        for term, mid_sentence in terms_in(text, terminals, config):
            occurrences[term] += 1
            non_initial[term] = non_initial[term] or mid_sentence
            if term not in seen:
                seen.add(term)
                holders[term].append(debug_id)

    qualified = [
        term
        for term, count in occurrences.items()
        if count >= metrics.ltcr_min_occurrences
        and non_initial[term]
        and len(" ".join(term)) >= config.source_term_min_chars
        and len(holders[term]) >= metrics.ltcr_min_paragraphs
    ]
    qualified.sort(key=lambda term: (-occurrences[term], " ".join(term)))
    qualified = qualified[: config.max_terms_per_article]
    return [(" ".join(term), holders[term], occurrences[term]) for term in qualified]


def measure_region(
    sources: dict[str, str],
    targets: dict[str, str],
    terminals,
    config: Config,
    metrics: MetricsConfig,
) -> list[dict]:
    """Every measurable term of one region, with its LTCR and its legacy share."""
    rows = []
    for text, held, count in qualifying_terms(sources, terminals, config, metrics):
        inside = [targets.get(debug_id, "") for debug_id in held]
        inside = [item for item in inside if item.strip()]
        outside = [
            value
            for debug_id, value in targets.items()
            if debug_id not in set(held) and value.strip()
        ]
        row = {"term": text, "occurrences": count, "paragraphs": len(held)}
        row.update(ltcr_of(inside, outside, config))
        rows.append(row)
    return rows


def summarise(rows: list[dict], digits: int) -> dict:
    """The corpus rule: numerators and denominators summed, never ratios averaged."""
    measured = [row for row in rows if row["ltcr"] is not None]
    agreeing = sum(row["pairs_agreeing"] for row in measured)
    total = sum(row["pairs_total"] for row in measured)
    legacy = [row["legacy_share"] for row in measured if row["legacy_share"] is not None]
    return {
        "terms": len(rows),
        "measured": len(measured),
        "pairs_agreeing": agreeing,
        "pairs_total": total,
        "ltcr": rounded(agreeing / total, digits) if total else None,
        "legacy_mean_share": rounded(sum(legacy) / len(legacy), digits)
        if legacy
        else None,
        "fully_consistent": sum(1 for row in measured if row["ltcr"] == 1.0),
    }


def measure(
    regions: list[tuple[str, dict[str, str], dict[str, str]]],
    terminals,
    config: Config | None = None,
    metrics: MetricsConfig | None = None,
) -> dict:
    """M3 over a document given as its regions, each a source and a target mapping.

    A region is whatever the caller wants a term to be counted inside -- an
    article for a magazine, a whole document for a report. The metric never
    decides that for itself, because "repeated in the document" and "repeated in
    the article" are different questions and only the caller knows which one is
    being asked.
    """
    config = config or load_config()
    metrics = metrics or load_metrics_config()
    digits = metrics.report_float_digits
    measured = []
    for name, sources, targets in regions:
        rows = measure_region(sources, targets, terminals, config, metrics)
        measured.append(
            {"region": name, "summary": summarise(rows, digits), "terms": rows}
        )
    every = [row for region in measured for row in region["terms"]]
    return {
        "metric": "ltcr",
        "min_occurrences": metrics.ltcr_min_occurrences,
        "min_paragraphs": metrics.ltcr_min_paragraphs,
        "regions": measured,
        "summary": summarise(every, digits),
    }
