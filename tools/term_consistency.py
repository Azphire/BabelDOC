"""Term consistency inside an article, measured over a finished run.

A brief exists so that an article translated in a dozen independent requests
comes out in one voice and with one set of names. The voice is not measurable;
the names are. This tool takes the runs a session produced, finds the source
terms that recur inside one article, and asks how consistently each was
rendered -- once per mode, so that brief on and brief off stand side by side.

There is no word alignment anywhere in this project, so the rendering of a term
is found rather than read. A term's paragraphs are translated into some set of
strings, and the tool looks for a short substring that appears in as many of
those translations as it can while staying out of the article's other
translated paragraphs; the share of the term's own paragraphs carrying that
substring is its consistency. A distinctive rendering used throughout scores
1.0. A term rendered three ways across three paragraphs scores 0.33, because no
one substring can cover more than one of them. What the measure cannot tell
apart is a term rendered consistently and a term rendered by a string so
ordinary that the outside filter throws it away; that shows up as a low score
with no candidate reported, and the per-term table carries the candidate so the
case is visible rather than silent.

A translation is read with its markup taken out. The rich text tags and formula
placeholders the translator carries through a request are not text anyone reads,
so a candidate drawn from them measures nothing; the batch-b6.3 sweep found one
term measured by a style tag under every setting of the tuning grid.

A source term is a run of capitalised words -- the general proxy for a proper
name, needing no word list and naming no publication -- that occurs often
enough, is long enough, and occurs at least once away from a sentence opening.
Every one of those bounds is in configs/term_consistency.json.

The glossary is reported beside the measurement, never folded into it: a term
the glossary covers is a term whose rendering was decided before the model saw
it, and the two columns answer different questions.

Usage:

    python tools/term_consistency.py \
        --run brief_off=examples/output/b6_smoke/Courier-en.context_off/work/Courier-en \
        --run brief_on=examples/output/b6_smoke/Courier-en.context_on/work/Courier-en \
        --out examples/output/b6_smoke

A working directory is one produced with ``magazine_checkpoint`` up: the source
text is read from the chain builder checkpoint and the translation from the
translated one, matched by paragraph debug id.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.page_features import validate_bounded_config  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402

logger = logging.getLogger(__name__)

CONFIG_PATH = ROOT / "configs" / "term_consistency.json"

# The two checkpoints one measurement needs: the document before translation and
# the same document after it.
SOURCE_STAGE = "chain_builder"
TARGET_STAGE = "il_translated"

# Where the body label vocabulary and the sentence enders are declared.
BODY_LABELS_KEY = "body_labels"
TERMINALS_KEY = "terminal_punctuation"

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
    min_article_occurrences: int
    source_term_min_chars: int
    connector_max_chars: int
    candidate_min_chars: int
    candidate_max_chars: int
    candidate_max_outside_share: float
    max_terms_per_article: int


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> Config:
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


# --- reading a run -----------------------------------------------------------


def strip_markup(text: str) -> str:
    """A translation with the tags and placeholders taken out of it.

    Input cleaning only: what is measured, and how, is unchanged. It is applied
    to every translation the run produced, so a candidate is counted inside and
    outside a term's paragraphs against the same cleaned text.
    """
    return _MARKUP.sub("", text)


def read_checkpoint(path: Path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return XMLConverter().read_xml(str(path))


def checkpoint_path(working_dir: Path, stage: str) -> Path:
    return working_dir / f"{checkpoint_stem(stage)}.xml"


@dataclass
class Run:
    """One produced run: its source document, its translation and its articles."""

    label: str
    working_dir: Path
    source: object
    target_text: dict[str, str]

    @property
    def pages(self) -> list:
        return list(self.source.page)


def load_run(label: str, working_dir: Path) -> Run:
    source_path = checkpoint_path(working_dir, SOURCE_STAGE)
    target_path = checkpoint_path(working_dir, TARGET_STAGE)
    for path in (source_path, target_path):
        if not path.exists():
            raise FileNotFoundError(f"{label}: {path} is missing")
    source = read_checkpoint(source_path)
    target = read_checkpoint(target_path)
    translated = {
        paragraph.debug_id: strip_markup(paragraph.unicode or "")
        for page in target.page
        for paragraph in page.pdf_paragraph
        if paragraph.debug_id is not None
    }
    return Run(
        label=label, working_dir=working_dir, source=source, target_text=translated
    )


# --- source side: which terms recur ------------------------------------------


def tokens_of(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in _WORD.finditer(text)]


def sentence_openings(text: str, tokens: list[tuple[str, int, int]], terminals) -> list[bool]:
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


# --- target side: how consistently a term was rendered ------------------------


def candidates_from(text: str, config: Config) -> set[str]:
    """Every whitespace-free substring of the declared lengths."""
    found: set[str] = set()
    for length in range(config.candidate_min_chars, config.candidate_max_chars + 1):
        for start in range(0, len(text) - length + 1):
            piece = text[start : start + length]
            if not any(char.isspace() for char in piece):
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


# --- one article --------------------------------------------------------------


def measure_article(run: Run, pages, body_labels, terminals, config, glossary_terms):
    """Every qualifying term of one article, with how consistently it was rendered."""
    paragraphs = [
        paragraph
        for index in pages
        for paragraph in run.source.page[index].pdf_paragraph
        if paragraph.debug_id is not None
        and paragraph.layout_label in body_labels
        and (paragraph.unicode or "").strip()
    ]
    occurrences: dict[tuple[str, ...], int] = defaultdict(int)
    non_initial: dict[tuple[str, ...], bool] = defaultdict(bool)
    holders: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for paragraph in paragraphs:
        seen: set[tuple[str, ...]] = set()
        for term, mid_sentence in terms_in(paragraph.unicode, terminals, config):
            occurrences[term] += 1
            non_initial[term] = non_initial[term] or mid_sentence
            if term not in seen:
                seen.add(term)
                holders[term].append(paragraph.debug_id)

    qualifying = [
        term
        for term, count in occurrences.items()
        if count >= config.min_article_occurrences
        and non_initial[term]
        and len(" ".join(term)) >= config.source_term_min_chars
    ]
    qualifying.sort(key=lambda term: (-occurrences[term], " ".join(term)))
    qualifying = qualifying[: config.max_terms_per_article]

    all_targets = {
        paragraph.debug_id: run.target_text.get(paragraph.debug_id, "")
        for paragraph in paragraphs
    }
    rows = []
    for term in qualifying:
        text = " ".join(term)
        held = holders[term]
        inside = [all_targets.get(debug_id, "") for debug_id in held]
        inside = [item for item in inside if item.strip()]
        outside = [
            value
            for debug_id, value in all_targets.items()
            if debug_id not in set(held) and value.strip()
        ]
        share, candidate = rendering(inside, outside, config)
        rows.append(
            {
                "term": text,
                "occurrences": occurrences[term],
                "paragraphs": len(held),
                "measured_paragraphs": len(inside),
                "consistency": share,
                "candidate": candidate,
                "in_glossary": text.casefold() in glossary_terms
                if glossary_terms is not None
                else None,
            }
        )
    return rows


def summarise(rows) -> dict:
    measured = [row for row in rows if row["consistency"] is not None]
    total = sum(row["consistency"] for row in measured)
    hits = [row for row in rows if row["in_glossary"]]
    return {
        "terms": len(rows),
        "measured": len(measured),
        "mean_consistency": round(total / len(measured), 4) if measured else None,
        "fully_consistent": sum(1 for row in measured if row["consistency"] == 1.0),
        "glossary_hits": len(hits) if rows and rows[0]["in_glossary"] is not None else None,
    }


# --- driving ------------------------------------------------------------------


def load_glossary_terms(paths: list[Path], lang_out: str) -> set[str] | None:
    if not paths:
        return None
    from babeldoc.glossary import Glossary

    terms: set[str] = set()
    for path in paths:
        glossary = Glossary.from_csv(path, lang_out)
        terms.update(entry.source.casefold() for entry in glossary.entries)
    return terms


def measure_run(run: Run, config: Config, glossary_terms) -> dict:
    chain_config = load_chain_config()
    body_labels = tuple(chain_config[BODY_LABELS_KEY])
    terminals = tuple(chain_config[TERMINALS_KEY])
    labels = article_builder.title_labels(article_builder.load_grouping_config())
    grouping = article_builder.build_articles(
        run.source, load_taxonomy().policy_of, labels
    )
    articles = []
    for article in grouping.articles:
        rows = measure_article(
            run, article.pages, body_labels, terminals, config, glossary_terms
        )
        articles.append(
            {
                "pages": [index + 1 for index in article.pages],
                "start_page": article.pages[0] + 1,
                "summary": summarise(rows),
                "terms": rows,
            }
        )
    every = [row for article in articles for row in article["terms"]]
    return {
        "label": run.label,
        "working_dir": str(run.working_dir),
        "articles": articles,
        "summary": summarise(every),
    }


def markdown(report: dict) -> str:
    """The dual mode table, one row per article, one column pair per mode."""
    labels = [entry["label"] for entry in report["runs"]]
    by_label = {entry["label"]: entry for entry in report["runs"]}
    lines: list[str] = ["# Term consistency", ""]
    lines.append(f"Sample: `{report['sample']}`")
    lines.append("")
    header = "| article | pages | " + " | ".join(
        f"terms ({label}) | mean ({label})" for label in labels
    ) + " |"
    lines.append(header)
    lines.append("| --- | --- | " + " | ".join("--- | ---" for _ in labels) + " |")

    starts = sorted(
        {
            article["start_page"]
            for entry in report["runs"]
            for article in entry["articles"]
        }
    )
    for position, start in enumerate(starts, start=1):
        cells = []
        pages = ""
        for label in labels:
            article = next(
                (
                    item
                    for item in by_label[label]["articles"]
                    if item["start_page"] == start
                ),
                None,
            )
            if article is None:
                cells.append("- | -")
                continue
            pages = ", ".join(str(page) for page in article["pages"])
            summary = article["summary"]
            mean = summary["mean_consistency"]
            cells.append(f"{summary['terms']} | {'-' if mean is None else f'{mean:.2f}'}")
        lines.append(f"| A{position} | {pages} | " + " | ".join(cells) + " |")

    lines.append("")
    totals = []
    for label in labels:
        summary = by_label[label]["summary"]
        mean = summary["mean_consistency"]
        totals.append(
            f"{label}: {summary['terms']} term(s), {summary['measured']} measured, "
            f"mean {'-' if mean is None else f'{mean:.3f}'}, "
            f"{summary['fully_consistent']} fully consistent"
        )
    lines.extend(f"- {line}" for line in totals)
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=WORKING_DIR",
        help="a produced working directory to measure, named by its mode",
    )
    parser.add_argument("--out", default=None, help="directory to write the report to")
    parser.add_argument(
        "--glossary",
        action="append",
        default=[],
        help="glossary CSV to report term coverage against",
    )
    parser.add_argument("--lang-out", default="zh")
    parser.add_argument("--sample", default=None, help="name the report carries")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    config = load_config()
    glossary_terms = load_glossary_terms(
        [Path(path) for path in args.glossary], args.lang_out
    )

    runs = []
    for spec in args.run:
        if "=" not in spec:
            raise SystemExit(f"--run wants LABEL=WORKING_DIR, got {spec!r}")
        label, path = spec.split("=", 1)
        runs.append(load_run(label, Path(path)))

    report = {
        "sample": args.sample or runs[0].working_dir.name,
        "config": config.__dict__,
        "glossary_terms": None if glossary_terms is None else len(glossary_terms),
        "runs": [measure_run(run, config, glossary_terms) for run in runs],
    }

    text = markdown(report)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        stem = f"term_consistency.{report['sample']}"
        (out / f"{stem}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out / f"{stem}.md").write_text(text, encoding="utf-8")
        print(f"wrote {out / (stem + '.json')}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
