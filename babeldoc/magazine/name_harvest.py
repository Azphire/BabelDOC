"""The personal names printed on a page no article claims.

Where the names are
-------------------

A magazine prints most of its names in the two places it prints least of its
prose: the contents page and the masthead. Those are also the pages the grouping
walk leaves unassigned, so they carry no article brief, and a name on them
reaches the model with less context than a name anywhere else in the document.
The F1 and F2 reviews found personal names surviving in their source script
there more often than anywhere else.

Two rounds of prompt work did not close it, and a third would not either: what
the model is missing on a contents page is not an instruction but the knowledge
that ``Margaux Anbouba`` is a person and not a section of the magazine. That is
a judgement, and the project already has a channel for a judgement -- the
ruling loop, and the glossary the ruled pairs become.

So this module finds the candidates, offers a rendering for each, and puts both
in front of a person. Nothing here decides anything.

Three steps, and only the middle one calls a model
--------------------------------------------------

**Harvest** is deterministic and reads shapes. A run of capitalised words, of a
bounded length, none of which is a closed class word a sentence starts with and
none of which is a word an organisation's name is built from. It is written
against the shape of the writing: no list here names a person, a publication or
a place, because a list that did would be a rule about one magazine.

**Render** is one batched request per document, through
``prompts/name_transliterate.md``, and it is asked for two things at once: the
target form, and whether the entry is a personal name at all. The second is what
makes the harvest's false positives visible to the person ruling rather than
buried in a table of a hundred rows.

**Offer** puts the pairs in the terms section of the review draft, which is the
section the ruling loop already reads and whose decided pairs already become a
glossary in the user glossary list. There is no second way in. A harvested name
travels the same road a ruled extractor term travels, and the matching and the
injection are upstream's, untouched.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.glossary import Glossary
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "name_harvest.json"
REPORT_NAME = "name_harvest.report.json"
PROMPT_NAME = "name_transliterate"
ARTICLE_MAP_NAME = "article_map.json"

SWITCH_KEY = "switch"
PARTICLES_KEY = "name_particles"
STOPWORDS_KEY = "stopwords"
INSTITUTION_KEY = "institution_words"
_VOCABULARIES = (PARTICLES_KEY, STOPWORDS_KEY, INSTITUTION_KEY)

# Where a harvested pair is recorded as having come from, in the draft row the
# person reads. The extractor's own rows carry no origin, so the absence of one
# is what it always was.
ORIGIN = "name_harvest"

# One word of a capitalised run: a capital, then letters, with an internal
# apostrophe or hyphen allowed. Written over letter categories rather than over
# an alphabet, so a name carrying a diacritic is one word and not two.
_WORD = re.compile(r"^[^\W\d_][^\W\d_]*(?:['’\-][^\W\d_]+)*$", re.UNICODE)

# What separates two candidates inside one paragraph. A candidate never crosses
# one of these, so a name at the end of one entry and a name at the start of the
# next are two candidates rather than one four word run.
_SPLIT = re.compile(r"[^\w'’\-\s]+|\d+", re.UNICODE)


class NameHarvestError(ConfigError):
    """Raised when the name harvest configuration is unusable."""


@dataclass(frozen=True)
class HarvestConfig:
    min_words: int
    max_words: int
    min_word_chars: int
    max_word_chars: int
    all_caps_max_words: int
    max_candidates_per_sample: int
    render_batch_max: int
    switch: str
    particles: frozenset[str]
    stopwords: frozenset[str]
    institution_words: frozenset[str]


@lru_cache(maxsize=2)
def load_harvest_config(path: str | None = None) -> HarvestConfig:
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    switch = raw.get(SWITCH_KEY)
    if not isinstance(switch, str) or not switch or switch.strip() != switch:
        raise NameHarvestError(
            f"{config_path.name}: {SWITCH_KEY} must name the run attribute the "
            f"harvest is read from"
        )
    try:
        parameters = dict(
            validate_bounded_config(
                {key: value for key, value in raw.items() if key != SWITCH_KEY},
                config_path,
            )
        )
    except ConfigError as exc:
        raise NameHarvestError(str(exc)) from exc
    for key in _VOCABULARIES:
        if key not in parameters:
            raise NameHarvestError(f"{config_path.name}: missing {key}")
    if int(parameters["min_words"]) > int(parameters["max_words"]):
        raise NameHarvestError(
            f"{config_path.name}: min_words is above max_words, so no run could "
            f"satisfy both"
        )
    if int(parameters["min_word_chars"]) > int(parameters["max_word_chars"]):
        raise NameHarvestError(
            f"{config_path.name}: min_word_chars is above max_word_chars, so no "
            f"word could satisfy both"
        )
    return HarvestConfig(
        min_words=int(parameters["min_words"]),
        max_words=int(parameters["max_words"]),
        min_word_chars=int(parameters["min_word_chars"]),
        max_word_chars=int(parameters["max_word_chars"]),
        all_caps_max_words=int(parameters["all_caps_max_words"]),
        max_candidates_per_sample=int(parameters["max_candidates_per_sample"]),
        render_batch_max=int(parameters["render_batch_max"]),
        switch=switch,
        particles=frozenset(item.lower() for item in parameters[PARTICLES_KEY]),
        stopwords=frozenset(item.lower() for item in parameters[STOPWORDS_KEY]),
        institution_words=frozenset(
            item.lower() for item in parameters[INSTITUTION_KEY]
        ),
    )


def enabled(translation_config, config: HarvestConfig | None = None) -> bool:
    config = load_harvest_config() if config is None else config
    return bool(getattr(translation_config, config.switch, False))


# --- the harvest ------------------------------------------------------------


def _is_name_word(word: str, config: HarvestConfig) -> bool:
    if not config.min_word_chars <= len(word) <= config.max_word_chars:
        return False
    if not _WORD.match(word):
        return False
    return word[0].isupper()


def _runs(text: str, config: HarvestConfig) -> list[list[str]]:
    """Every maximal run of capitalised words in one text, particles allowed."""
    found: list[list[str]] = []
    for piece in _SPLIT.split(text or ""):
        run: list[str] = []
        for word in piece.split():
            if _is_name_word(word, config):
                run.append(word)
                continue
            if run and word.lower() in config.particles:
                run.append(word)
                continue
            if run:
                found.append(run)
            run = []
        if run:
            found.append(run)
    return [run for run in found if run]


def _acceptable(run: list[str], config: HarvestConfig) -> bool:
    # A run ending on a particle is a run that ran out before its last word.
    while run and run[-1].lower() in config.particles:
        run.pop()
    if not config.min_words <= len(run) <= config.max_words:
        return False
    words = [word for word in run if word.lower() not in config.particles]
    if len(words) < config.min_words:
        return False
    if any(word.lower() in config.stopwords for word in words):
        return False
    if any(word.lower() in config.institution_words for word in words):
        return False
    capitals = sum(1 for word in words if word.isupper() and len(word) > 1)
    return capitals <= config.all_caps_max_words


def harvest_text(text: str, config: HarvestConfig) -> list[str]:
    """Every candidate personal name in one text, in the order it is written."""
    found = []
    for run in _runs(text, config):
        candidate = list(run)
        if _acceptable(candidate, config):
            found.append(" ".join(candidate))
    return found


def unassigned_pages(translation_config) -> list[int]:
    """The pages the grouping walk claimed for no article, read from its map.

    Read from the map rather than decided here, and the map records a page as
    unassigned without this module knowing or asking what kind of page it is.
    """
    path = Path(translation_config.get_working_file_path(ARTICLE_MAP_NAME))
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        record = json.load(f)
    return sorted(
        int(item["page"])
        for item in record.get("unassigned", ())
        if isinstance(item, dict) and item.get("page") is not None
    )


def harvest(docs, pages: list[int], config: HarvestConfig) -> list[dict]:
    """One row per distinct candidate found on the given pages.

    A candidate found more than once carries the count and the first page it was
    found on, which is what the draft's other rows carry.
    """
    counts: dict[str, dict] = {}
    wanted = set(pages)
    for page_index, page in enumerate(docs.page or ()):
        label = page_index + 1
        if label not in wanted:
            continue
        for paragraph in page.pdf_paragraph or ():
            for candidate in harvest_text(paragraph.unicode or "", config):
                row = counts.setdefault(
                    candidate,
                    {"source": candidate, "occurrences": 0, "first_page": label},
                )
                row["occurrences"] += 1
    rows = sorted(counts.values(), key=lambda row: (row["first_page"], row["source"]))
    return rows[: config.max_candidates_per_sample]


def without_glossary_hits(rows: list[dict], glossaries) -> list[dict]:
    """Drop the candidates a glossary the run holds already decides."""
    decided = set()
    for glossary in glossaries or ():
        for entry in getattr(glossary, "entries", ()) or ():
            decided.add(Glossary.normalize_source(entry.source))
    return [
        row for row in rows if Glossary.normalize_source(row["source"]) not in decided
    ]


# --- the rendering ----------------------------------------------------------


def render_names(
    translation_config, rows: list[dict], target_lang: str, engine
) -> dict:
    """Ask once for the target form of every entry, and whether it is a name.

    One request per document, over every entry of the merged table whose source
    is shaped like a personal name -- whichever finder reached it, because a
    name the extractor found needs a rendering exactly as much as one the
    harvest found.

    The reply decides nothing. It fills ``observed_target``, which is what the
    policy derivation then makes a default out of, and it says whether the
    entry looked like a person at all, which is what makes the shape rule's
    false positives visible to whoever rules rather than buried in the table.
    """
    if not rows:
        return {"requested": 0, "answered": 0, "batches": 0, "prompt_sha256": None}
    if engine is None:
        return {
            "requested": len(rows),
            "answered": 0,
            "batches": 0,
            "prompt_sha256": None,
        }
    config = load_harvest_config()
    working = Path(translation_config.get_working_file_path(REPORT_NAME)).parent
    answered = 0
    batches = 0
    digest = None
    failures: list[str] = []
    for start in range(0, len(rows), config.render_batch_max):
        batch = rows[start : start + config.render_batch_max]
        prompt = load_prompt(
            PROMPT_NAME,
            {
                "target_language": target_lang,
                "names": "\n".join(f"- {row['source']}" for row in batch),
            },
            working_dir=working,
        )
        digest = prompt.digest
        batches += 1
        try:
            raw = engine.llm_translate(
                prompt.text, rate_limit_params={"request_json_mode": True}
            )
        except Exception as error:  # the engine and its output are both foreign
            logger.warning("name harvest: a rendering request failed: %s", error)
            failures.append(str(error))
            continue
        answers = _parse_answers(raw)
        if not answers:
            failures.append("a reply carried no entry this could read")
        answered += len(answers)
        for row in batch:
            answer = answers.get(row["source"])
            if answer is None:
                continue
            target = (answer.get("target") or "").strip()
            if target:
                row["observed_target"] = target
            row["is_person"] = bool(answer.get("is_person"))
    record = {
        "requested": len(rows),
        "answered": answered,
        "batches": batches,
        "prompt_sha256": digest,
    }
    if failures:
        record["failures"] = failures
    return record


def _parse_answers(raw: str) -> dict[str, dict]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -len("```")]
    try:
        parsed = json.loads(text)
    except ValueError as error:
        logger.warning("name harvest: the reply could not be read: %s", error)
        return {}
    if isinstance(parsed, dict):
        parsed = parsed.get("names", [parsed])
    if not isinstance(parsed, list):
        return {}
    answers = {}
    for item in parsed:
        if isinstance(item, dict) and isinstance(item.get("source"), str):
            answers[item["source"]] = item
    return answers


# --- what a policy makes of one name ----------------------------------------

# The policies whose default is the rendered form, which is every one that
# renders. Named against the policy vocabulary rather than written into a
# branch, so a policy added to the matrix is a policy this reads.
_RENDERS = ("transliterate", "translate")
_KEEPS = "keep"
_ANNOTATES = "annotate"


def derive(
    source: str,
    observed: str | None,
    policy: str,
    brackets: tuple[str, str] | None,
) -> tuple[str | None, list[str]]:
    """What one name defaults to under one policy, and what else is offered.

    The default is the policy's own semantics, so a run under any policy needs
    no ruling to behave as that policy says: under a policy that renders, the
    default is the rendering and the source form is offered beside it; under
    ``keep`` the two swap places, so ruling an exception is choosing an offered
    value rather than typing one; under ``annotate`` the default is the
    combined form and both halves are offered.

    ``None`` where the policy renders and nothing was rendered: a default that
    silently fell back to the source form would make a failed request look like
    a decision.
    """
    rendered = (observed or "").strip() or None
    if policy == _KEEPS:
        return source, [item for item in (rendered,) if item]
    if policy == _ANNOTATES:
        if rendered is None or brackets is None:
            return None, [source]
        opener, closer = brackets
        return f"{rendered}{opener}{source}{closer}", [source, rendered]
    if policy in _RENDERS:
        return rendered, [source]
    # A policy that states nothing states nothing here either.
    return None, [item for item in (rendered,) if item]


def is_person_shaped(source: str, config: HarvestConfig) -> bool:
    """Whether a source is, as a whole, one run of the shape a name has.

    Applied to every entry of the merged table rather than to the harvest's own
    findings alone, so a personal name the term extractor found is derived from
    the policy exactly as a harvested one is.
    """
    found = harvest_text(source, config)
    return len(found) == 1 and found[0] == (source or "").strip()


# --- what the draft is offered ----------------------------------------------


def draft_rows(rows: list[dict]) -> list[dict]:
    """The harvested candidates in the shape the terms section of a draft has."""
    return [
        {
            "source": row["source"],
            "observed_target": row.get("auto_target"),
            "vote_count": row["occurrences"],
            "first_page": row["first_page"],
            "origin": ORIGIN,
            "is_person": row.get("is_person"),
        }
        for row in rows
    ]


def write_report(translation_config, record: dict) -> Path:
    path = Path(translation_config.get_working_file_path(REPORT_NAME))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    return path


def harvested_rows(translation_config, docs) -> list[dict]:
    """The harvest's own findings, in the shape the merged table has.

    Deterministic and free: no model is asked anything here. The rendering is
    asked once, over the merged table, by whoever merges it.
    """
    config = load_harvest_config()
    pages = unassigned_pages(translation_config)
    rows = harvest(docs, pages, config)
    shared = translation_config.shared_context_cross_split_part
    rows = without_glossary_hits(rows, getattr(shared, "user_glossaries", ()) or ())
    return draft_rows(rows)


def write_merged_report(translation_config, rows: list[dict], request: dict) -> Path:
    """What the merged table holds, and what the one request cost."""
    shaped = [row for row in rows if row.get("person_shaped")]
    record = {
        "switch": load_harvest_config().switch,
        "pages": unassigned_pages(translation_config),
        "policy": (shaped[0].get("policy") if shaped else None),
        "counts": {
            "rows": len(rows),
            "person_shaped": len(shaped),
            "harvested": sum(1 for row in rows if row.get("origin") == ORIGIN),
            "said_person": sum(1 for row in shaped if row.get("is_person")),
            "defaulted": sum(
                1
                for row in shaped
                if isinstance(row.get("auto_target"), str)
                and row["auto_target"].strip()
            ),
        },
        "request": request,
        "rows": rows,
    }
    return write_report(translation_config, record)
