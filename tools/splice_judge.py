"""Annotate splice points with a cached MQM judge -- metric contract M10.

A *splice point* is a page boundary a reader crosses in one movement: the last
passage of running text on the page being left and the first on the page being
entered are read as one passage, and that passage is what is judged. The
material for one point is three windows -- the source passage spanning the
boundary, the tail, and the head -- and the answer is a list of MQM errors with
a category and a severity drawn from closed vocabularies, or an empty list.

Four properties, each of which is a rule this project already follows.

*Cached.* A reply is stored in the project-local database the translator cache
uses, under an engine name of its own, keyed by the model, the request
parameters that shape a reply, the identity of the prompt file and the rendered
prompt -- which is where the material enters the key. A second run over
unchanged artefacts therefore costs nothing, and ``--offline`` proves it: with
no transport at all, a point that is not already cached stops the run instead of
being re-requested, so the report a gate regenerates is the report the paid run
produced.

*Bounded.* Every setting comes from ``configs/splice_judge.json`` with a
declared range, including the two vocabularies and the three window sizes. The
credential is not a setting: the configuration names an environment variable and
the value is read from the process environment when a request is built.

*Constrained.* A reply is a JSON object whose every category and severity is a
name the configuration declares. Anything else is a violation, retried once with
the violation stated, and a second violation records the point as refused rather
than widening the vocabulary or repairing the answer. Nothing here edits what a
judge returned: the reply is stored verbatim beside the parse of it.

*Not the family under test.* The translations judged here were produced by
gpt-4o. The judge is configured to another family, which is option (a) of gap
register GAP-03; the sampled nature of the judge itself is what the manual
review list this tool writes is for.

The test points are read from the corpus adjudication and are every boundary it
rules ``link: true`` -- the positives, where a semantic unit is cut and the
continuation is on the next page. The arms are the frozen runs held for that
sample, named here rather than discovered, because a report that measured
whatever was lying in the output tree would change meaning between sweeps.

Usage:
    python tools/splice_judge.py --out docs/eval/results_e2
    python tools/splice_judge.py --out docs/eval/results_e2 --offline
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import warnings
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import chain_signals  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.metrics import load_metrics_config  # noqa: E402
from babeldoc.magazine.metrics import pdf_geometry  # noqa: E402
from babeldoc.magazine.page_features import ConfigError  # noqa: E402
from babeldoc.magazine.page_features import validate_bounded_config  # noqa: E402
from babeldoc.magazine.prompt_loader import Prompt  # noqa: E402
from babeldoc.magazine.prompt_loader import load_prompt  # noqa: E402
from babeldoc.magazine.vlm_client import unfence  # noqa: E402
from babeldoc.translator.cache import TranslationCache  # noqa: E402

CONFIG_PATH = ROOT / "configs" / "splice_judge.json"

# Engine name the cached replies are filed under, keeping them apart from the
# translated segments and the vision replies sharing the database.
ENGINE_NAME = "magazine_splice_judge"

# Bumped when the composition of the cache key changes, which retires every
# entry written under the old composition in one step.
CACHE_KEY_VERSION = 1

PROMPT_NAME = "splice_judge_mqm"

# The template that states a rejected reply back to the model on the retry. It
# is the one the vision client already uses: its wording names no modality and
# asks for exactly what a violation here needs asked again.
RETRY_PROMPT_NAME = "vlm_retry_notice"

# Where the frozen artefacts live. The upstream side is a translation by
# unmodified upstream BabelDOC and carries no intermediate language at all, so
# its windows are read from the produced PDF by the same extractor the metric
# suite reads an upstream PDF with.
UPSTREAM_PDF_DIR = ROOT / "examples" / "baseline" / "pdf"
FORK_RUN_DIR = ROOT / "examples" / "output" / "b8_4" / "smoke"
TRIO_RUN_DIR = ROOT / "examples" / "output" / "e2" / "r1"
MONO_PDF_GLOB = "*.mono.pdf"

# Samples for which batch E2 session one ran the three-arm design, and the arms
# it ran. For such a sample the chain switch has two measured states and the
# treatment arm stands for the full-stack configuration, which is what the
# frozen b8.4 run of that sample also is: listing both would put one
# configuration in the table twice under two names.
TRIO_SAMPLES = {"Courier-en": TRIO_RUN_DIR}
TRIO_ARMS = ("chain_off_1", "chain_off_2", "chain_on")

UPSTREAM_ARM = "upstream"
FORK_ARM = "fork_full"

# The stage each window is read from. The source side is the last checkpoint
# before translation, where paragraphs and their boxes are in place; the
# produced side is after typesetting, so a window is the text as it was set on
# the page rather than the string the translation round trip carried.
SOURCE_STAGE = "chain_builder"
TYPESET_STAGE = "typesetting"

# The floor GAP-03 puts under the manual check. The review draft carries every
# row rather than a selection, so this is a guard against an empty corpus of
# test points rather than a sampling rule.
MANUAL_REVIEW_MIN_POINTS = 5

# The fields a human answers in a review draft. A draft exports them null; any
# of them carrying a value makes the file a ruling, and a ruling is never
# rewritten by a run of this tool.
HUMAN_FIELDS = ("human_agrees", "human_errors", "human_note")

# Configuration keys that are not bounded numbers.
TEXT_KEYS: tuple[str, ...] = ("model", "base_url", "api_key_env")
VOCABULARY_KEYS: tuple[str, ...] = ("mqm_categories", "mqm_severities")
NUMERIC_KEYS: tuple[str, ...] = (
    "temperature",
    "max_output_tokens",
    "max_retries",
    "timeout_seconds",
    "max_errors",
    "source_window_characters",
    "tail_window_characters",
    "head_window_characters",
)
ENUM_KEYS: dict[str, tuple[str, ...]] = {
    "token_parameter": ("max_tokens", "max_completion_tokens"),
}
NULLABLE_NUMERIC_KEYS: tuple[str, ...] = ("temperature",)

# Request parameters that shape a reply, and therefore belong in the cache key.
# The window sizes and both vocabularies reach the model through the words of
# the prompt and are in the key through the rendered text, so they are not
# repeated here.
KEY_PARAMETERS: tuple[str, ...] = (
    "temperature",
    "max_output_tokens",
    "token_parameter",
)

DESCRIPTION_KEY = "description"
_RANGE_SUFFIX = "_allowed_range"

# The windows an error may be attributed to, which is the set the material has.
WINDOWS = ("source", "tail", "head")

# Fields one error must carry.
REQUIRED_ERROR_FIELDS = ("category", "severity", "window", "span", "explanation")


class SpliceJudgeError(ConfigError):
    """Raised when the configuration, the artefacts or the transport are unusable."""


@dataclass(frozen=True)
class JudgeConfig:
    model: str
    base_url: str
    api_key_env: str
    temperature: float | None
    max_output_tokens: int
    max_retries: int
    timeout_seconds: float
    max_errors: int
    source_window_characters: int
    tail_window_characters: int
    head_window_characters: int
    token_parameter: str
    mqm_categories: tuple[str, ...]
    mqm_severities: tuple[str, ...]

    def key_parameters(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in KEY_PARAMETERS}

    def pinned(self) -> dict[str, object]:
        """What every row of the report carries: which judge, asked how."""
        return {
            "judge_model": self.model,
            "judge_transport": {
                "token_parameter": self.token_parameter,
                "temperature": self.temperature,
                "max_output_tokens": self.max_output_tokens,
            },
        }


@dataclass(frozen=True)
class Judgement:
    """One annotation, accepted or refused. A refusal is a result like any other."""

    accepted: bool
    reading: str | None = None
    errors: tuple[dict, ...] = ()
    reason: str = ""
    reply: str = ""
    attempts: int = 0
    from_cache: bool = False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SpliceJudgeError(message)


def parse_judge_config(raw: dict, source: str) -> JudgeConfig:
    """Validate a decoded ``splice_judge.json`` and build its object model."""
    _require(isinstance(raw, dict), f"{source}: root must be an object")
    # The key set is closed. An undeclared key is the shape a planted credential
    # would take, and a closed set refuses it without guessing what one is named.
    declared = {
        DESCRIPTION_KEY,
        *TEXT_KEYS,
        *ENUM_KEYS,
        *VOCABULARY_KEYS,
        *NUMERIC_KEYS,
        *(f"{key}{_RANGE_SUFFIX}" for key in NUMERIC_KEYS),
    }
    unknown = sorted(set(raw) - declared)
    _require(
        not unknown,
        f"{source}: undeclared keys {unknown}; this file holds the declared "
        f"settings only and never a credential, which is read from the "
        f"environment variable it names",
    )
    for key in (*TEXT_KEYS, *ENUM_KEYS, *VOCABULARY_KEYS, *NUMERIC_KEYS):
        _require(key in raw, f"{source}: missing key {key!r}")
    for key in TEXT_KEYS:
        _require(
            isinstance(raw[key], str) and raw[key],
            f"{source}: {key} must be a non-empty string",
        )
    for key, choices in ENUM_KEYS.items():
        _require(
            raw[key] in choices,
            f"{source}: {key} must be one of {list(choices)}, not {raw[key]!r}",
        )
    for key in VOCABULARY_KEYS:
        value = raw[key]
        _require(
            isinstance(value, list)
            and value
            and all(isinstance(name, str) and name for name in value),
            f"{source}: {key} must be a non-empty list of names",
        )
        _require(
            len(set(value)) == len(value), f"{source}: {key} repeats a name"
        )

    bounded = {
        key: value
        for key, value in raw.items()
        if key not in TEXT_KEYS and key not in ENUM_KEYS and key not in VOCABULARY_KEYS
    }
    # A nullable setting at null is not sent, so there is no value to bound; its
    # range declaration stays required and bounds whatever replaces the null.
    omitted = tuple(key for key in NULLABLE_NUMERIC_KEYS if bounded.get(key) is None)
    for key in omitted:
        _require(
            f"{key}{_RANGE_SUFFIX}" in raw, f"{source}: {key} has no {_RANGE_SUFFIX}"
        )
        bounded.pop(key)
        bounded.pop(f"{key}{_RANGE_SUFFIX}")

    parameters = validate_bounded_config(bounded, Path(source))
    missing = sorted(set(NUMERIC_KEYS) - set(parameters) - set(omitted))
    _require(not missing, f"{source}: missing bounded parameters {missing}")

    temperature = parameters.get("temperature")
    return JudgeConfig(
        model=raw["model"],
        base_url=raw["base_url"],
        api_key_env=raw["api_key_env"],
        temperature=None if temperature is None else float(temperature),
        max_output_tokens=int(parameters["max_output_tokens"]),
        max_retries=int(parameters["max_retries"]),
        timeout_seconds=float(parameters["timeout_seconds"]),
        max_errors=int(parameters["max_errors"]),
        source_window_characters=int(parameters["source_window_characters"]),
        tail_window_characters=int(parameters["tail_window_characters"]),
        head_window_characters=int(parameters["head_window_characters"]),
        token_parameter=raw["token_parameter"],
        mqm_categories=tuple(raw["mqm_categories"]),
        mqm_severities=tuple(raw["mqm_severities"]),
    )


def load_judge_config(path: Path | None = None) -> JudgeConfig:
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_judge_config(raw, config_path.name)


# --- the material ---------------------------------------------------------


def digest_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def named(path: Path) -> str:
    """An artefact path as a report should carry it: relative, forward slashes."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _document(path: Path):
    with warnings.catch_warnings():
        # An older checkpoint may warn about a converter default; an error is
        # still an error and still raises.
        warnings.simplefilter("ignore")
        return load_checkpoint(path)


def _rendered_text(lines) -> str:
    """One paragraph as it was set: its rendered lines, in order, one per line."""
    return "\n".join(chain_signals.line_text(line) for line in lines).strip()


def windows_at(document, page_index: int, chain_config) -> tuple[str, str]:
    """The tail and head passages either side of one page boundary.

    The tail is the last endpoint candidate of the page being left and the head
    is the first of the page being entered, in the reading order the chain
    detector derives -- the same tail the mid-unit page-break rate reads, so the
    geometric verdict and the annotation are about one boundary and not two.
    """
    pages = list(document.page)
    if page_index + 1 >= len(pages):
        raise SpliceJudgeError(
            f"boundary {page_index + 1}->{page_index + 2} is past the last page"
        )
    tail = chain_signals.page_candidates(pages[page_index], chain_config)
    head = chain_signals.page_candidates(pages[page_index + 1], chain_config)
    return (
        _rendered_text(tail[-1][2]) if tail else "",
        _rendered_text(head[0][2]) if head else "",
    )


def cut(text: str, limit: int, keep_end: bool) -> str:
    """One window at its declared length, kept from the edge nearest the boundary."""
    if len(text) <= limit:
        return text
    return text[-limit:] if keep_end else text[:limit]


def source_window(tail: str, head: str, limit: int) -> str:
    """The source passage spanning the boundary, as one passage.

    Both halves are cut to half the declared length so that neither side of the
    boundary can crowd the other out of the window.
    """
    half = max(1, limit // 2)
    return f"{cut(tail, half, keep_end=True)}\n\n{cut(head, half, keep_end=False)}".strip()


# --- the test points and their arms ---------------------------------------


@dataclass(frozen=True)
class Arm:
    """One frozen configuration of one sample, and where its produced text is."""

    label: str
    working_dir: Path | None
    produced_pdf: Path | None


def _upstream_pdf(stem: str) -> Path | None:
    directory = UPSTREAM_PDF_DIR / stem
    if not directory.is_dir():
        return None
    produced = sorted(directory.glob(MONO_PDF_GLOB))
    return produced[0] if produced else None


def arms_of(stem: str) -> list[Arm]:
    """Every frozen arm held for one sample, in the order a table reads them."""
    arms: list[Arm] = []
    upstream = _upstream_pdf(stem)
    if upstream is not None:
        arms.append(Arm(UPSTREAM_ARM, None, upstream))
    trio = TRIO_SAMPLES.get(stem)
    if trio is not None:
        for label in TRIO_ARMS:
            working = trio / label / "work" / stem
            if working.is_dir():
                arms.append(Arm(label, working, None))
        return arms
    working = FORK_RUN_DIR / stem / "work" / stem
    if working.is_dir():
        arms.append(Arm(FORK_ARM, working, None))
    return arms


def required_checkpoints() -> list[Path]:
    """Every checkpoint ``build_material`` reads, for the whole test point set.

    The arms of a sample are discovered by looking for their working
    directories, so an arm whose checkpoints were retired by the output
    retention policy does not fail loudly -- it either drops out of the table or
    stops the run on the first read. Both are silent changes to frozen evidence,
    which is why a caller that wants to regenerate the table asks this first.
    """
    needed: list[Path] = []
    for point in linked_points():
        stem = point["stem"]
        working = source_working_dir(stem)
        if working is not None:
            needed.append(working / f"{checkpoint_stem(SOURCE_STAGE)}.xml")
        for arm in arms_of(stem):
            if arm.working_dir is None:
                continue
            needed.append(arm.working_dir / f"{checkpoint_stem(SOURCE_STAGE)}.xml")
            needed.append(arm.working_dir / f"{checkpoint_stem(TYPESET_STAGE)}.xml")
    unique: list[Path] = []
    for path in needed:
        if path not in unique:
            unique.append(path)
    return unique


def source_working_dir(stem: str) -> Path | None:
    """Where the source side of a sample is read from, whichever arms it has."""
    for arm in arms_of(stem):
        if arm.working_dir is not None:
            return arm.working_dir
    return None


def linked_points() -> list[dict]:
    """Every boundary the corpus adjudicates as cutting a semantic unit."""
    labels = corpus_module.load_chain_labels()
    points = []
    for sample, entry in corpus_module.chain_label_samples(labels).items():
        for boundary, ruling in entry.items():
            if not isinstance(ruling, dict) or not ruling.get("link"):
                continue
            pages = corpus_module.parse_boundary_key(boundary)
            if pages is None:
                continue
            points.append(
                {
                    "sample": sample,
                    "stem": Path(sample).stem,
                    "boundary": boundary,
                    "page_index": pages[0] - 1,
                    "note": str(ruling.get("note") or ""),
                }
            )
    points.sort(key=lambda item: (item["sample"], item["page_index"]))
    return points


def build_material(config: JudgeConfig) -> dict:
    """Every test point with its arms, their windows, and the source they share.

    The source window is read once per sample and then checked against every
    other arm that carries an intermediate language: the arms of one sample
    translated one document, and a source window that differed between them
    would mean the material is not the same question asked twice.
    """
    chain_config = load_chain_config()
    metrics_config = load_metrics_config()
    points = []
    faults: list[str] = []
    for point in linked_points():
        stem = point["stem"]
        working = source_working_dir(stem)
        if working is None:
            faults.append(f"{point['sample']}: no frozen run holds a source side")
            continue
        source_document = _document(
            working / f"{checkpoint_stem(SOURCE_STAGE)}.xml"
        )
        tail, head = windows_at(source_document, point["page_index"], chain_config)
        source = source_window(tail, head, config.source_window_characters)

        arms = []
        for arm in arms_of(stem):
            if arm.working_dir is not None:
                produced = _document(
                    arm.working_dir / f"{checkpoint_stem(TYPESET_STAGE)}.xml"
                )
                origin = named(arm.working_dir)
                path = "intermediate_language"
                other_tail, other_head = windows_at(
                    _document(arm.working_dir / f"{checkpoint_stem(SOURCE_STAGE)}.xml"),
                    point["page_index"],
                    chain_config,
                )
                if source_window(
                    other_tail, other_head, config.source_window_characters
                ) != source:
                    faults.append(
                        f"{point['sample']} {point['boundary']}: arm {arm.label} "
                        f"carries a different source window"
                    )
            else:
                produced = pdf_geometry.document_from_pdf(
                    arm.produced_pdf, metrics_config
                )
                origin = named(arm.produced_pdf)
                path = "pdf_extraction"
            arm_tail, arm_head = windows_at(
                produced, point["page_index"], chain_config
            )
            arms.append(
                {
                    "arm": arm.label,
                    "path": path,
                    "origin": origin,
                    "tail_window": cut(
                        arm_tail, config.tail_window_characters, keep_end=True
                    ),
                    "head_window": cut(
                        arm_head, config.head_window_characters, keep_end=False
                    ),
                }
            )
        points.append({**point, "source_window": source, "arms": arms})
    return {"points": points, "faults": faults}


# --- the judge ------------------------------------------------------------


def cache_key(config: JudgeConfig, prompt: Prompt) -> str:
    """Digest of everything that could change the reply to one request.

    The material is in the key through the rendered prompt text: two windows are
    two different prompts and cannot collide.
    """
    fields = (
        f"cache_key_version={CACHE_KEY_VERSION}",
        f"model={config.model}",
        "params="
        + json.dumps(config.key_parameters(), sort_keys=True, separators=(",", ":")),
        f"prompt_file_sha256={prompt.digest}",
        f"prompt_text_sha256={digest_of_text(prompt.text)}",
    )
    return hashlib.sha256("\n".join(fields).encode()).hexdigest()


def interpret_reply(reply: str, config: JudgeConfig) -> Judgement:
    """Turn a reply into an annotation, refusing anything outside the contract.

    Both vocabularies are closed. A category the configuration does not declare
    is a violation and never a new category, whatever the judge believes it saw.
    Nothing here repairs a reply: an answer that does not validate is asked for
    again, and the second failure is recorded as a refusal. One balanced code
    fence around the whole reply is peeled off before parsing, which is the same
    tolerance the vision client applies and changes no annotation; the reply is
    stored as it arrived either way.
    """
    try:
        payload = json.loads(unfence(reply))
    except (json.JSONDecodeError, TypeError) as exc:
        return Judgement(accepted=False, reason=f"reply is not valid JSON: {exc}", reply=reply)
    if not isinstance(payload, dict):
        return Judgement(
            accepted=False,
            reason=f"reply is a {type(payload).__name__}, expected a JSON object",
            reply=reply,
        )
    reading = payload.get("reading")
    if not isinstance(reading, str) or not reading.strip():
        return Judgement(
            accepted=False, reason="reading is missing or is not a sentence", reply=reply
        )
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return Judgement(
            accepted=False, reason="errors is missing or is not a list", reply=reply
        )
    if len(errors) > config.max_errors:
        return Judgement(
            accepted=False,
            reason=f"{len(errors)} errors reported, more than the {config.max_errors} asked for",
            reply=reply,
        )
    parsed = []
    for position, error in enumerate(errors):
        if not isinstance(error, dict):
            return Judgement(
                accepted=False, reason=f"error {position} is not an object", reply=reply
            )
        missing = sorted(set(REQUIRED_ERROR_FIELDS) - set(error))
        if missing:
            return Judgement(
                accepted=False,
                reason=f"error {position} is missing fields {missing}",
                reply=reply,
            )
        if error["category"] not in config.mqm_categories:
            return Judgement(
                accepted=False,
                reason=f"category {error['category']!r} is not one of the "
                f"{len(config.mqm_categories)} declared names",
                reply=reply,
            )
        if error["severity"] not in config.mqm_severities:
            return Judgement(
                accepted=False,
                reason=f"severity {error['severity']!r} is not one of the "
                f"{len(config.mqm_severities)} declared names",
                reply=reply,
            )
        if error["window"] not in WINDOWS:
            return Judgement(
                accepted=False,
                reason=f"window {error['window']!r} is not one of {list(WINDOWS)}",
                reply=reply,
            )
        for field in ("span", "explanation"):
            if not isinstance(error[field], str) or not error[field].strip():
                return Judgement(
                    accepted=False,
                    reason=f"error {position} has an empty {field}",
                    reply=reply,
                )
        parsed.append({name: error[name] for name in REQUIRED_ERROR_FIELDS})
    return Judgement(
        accepted=True, reading=reading, errors=tuple(parsed), reply=reply
    )


def build_request(config: JudgeConfig, prompt: str) -> dict:
    """The chat completion body one configuration asks for."""
    body = {
        "model": config.model,
        config.token_parameter: config.max_output_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if config.temperature is not None:
        body["temperature"] = config.temperature
    return body


def load_dotenv() -> None:
    """Read the repository .env for a credential the shell does not carry.

    The same reader ``tools/run_drift_trio.py`` uses, and called from the same
    place: only on the path that is about to build a transport, so an offline
    run never opens the file.
    """
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def read_api_key(config: JudgeConfig) -> str:
    key = os.environ.get(config.api_key_env, "")
    _require(
        bool(key),
        f"environment variable {config.api_key_env} is unset; the judge "
        f"credential is read from the environment only",
    )
    return key


class OpenAICompatibleTransport:
    """Chat completions over an OpenAI-compatible endpoint.

    The client is built on first use, so importing this module or running fully
    from cache neither reads a credential nor opens a connection. Token usage is
    accumulated because the cost of a paid run is part of its record.
    """

    def __init__(self) -> None:
        self._client = None
        self.requests = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _openai_client(self, config: JudgeConfig):
        if self._client is None:
            import openai

            self._client = openai.OpenAI(
                api_key=read_api_key(config),
                base_url=config.base_url,
                timeout=config.timeout_seconds,
            )
        return self._client

    def complete(self, config: JudgeConfig, prompt: str) -> str:
        response = self._openai_client(config).chat.completions.create(
            **build_request(config, prompt)
        )
        self.requests += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        return response.choices[0].message.content or ""


class CachedJudgeClient:
    """One annotation point: cache lookup, bounded retry, closed vocabulary."""

    def __init__(
        self,
        config: JudgeConfig,
        transport: OpenAICompatibleTransport | None,
        cache: TranslationCache | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.cache = (
            TranslationCache(ENGINE_NAME, {"cache_key_version": CACHE_KEY_VERSION})
            if cache is None
            else cache
        )
        self.cache_hits = 0

    def _retry_prompt(self, prompt: Prompt, violation: str) -> str:
        notice = load_prompt(RETRY_PROMPT_NAME, {"violation": violation})
        return f"{prompt.text}\n\n{notice.text}"

    def judge(self, prompt: Prompt) -> tuple[str, Judgement]:
        """Annotate one splice point, from cache when the request is not new."""
        key = cache_key(self.config, prompt)
        stored = self.cache.get(key)
        if stored is not None:
            judgement = interpret_reply(stored, self.config)
            if judgement.accepted:
                self.cache_hits += 1
                return key, replace(judgement, attempts=0, from_cache=True)
            # A stored reply that no longer validates means a vocabulary moved
            # under it. Ask again rather than serve a reply nothing can use.
        if self.transport is None:
            raise SpliceJudgeError(
                f"no usable cached reply for {key[:12]} and this run may not "
                f"spend; drop --offline to ask the judge"
            )

        text = prompt.text
        violations: list[str] = []
        attempts = 0
        last_reply = ""
        while attempts <= self.config.max_retries:
            attempts += 1
            try:
                reply = self.transport.complete(self.config, text)
            except Exception as exc:  # noqa: BLE001 - any failure is a violation
                violations.append(f"request failed: {type(exc).__name__}: {exc}")
            else:
                last_reply = reply
                judgement = interpret_reply(reply, self.config)
                if judgement.accepted:
                    self.cache.set(key, reply)
                    return key, replace(judgement, attempts=attempts, from_cache=False)
                violations.append(judgement.reason)
            if attempts <= self.config.max_retries:
                text = self._retry_prompt(prompt, violations[-1])
        return key, Judgement(
            accepted=False,
            reason="; ".join(violations),
            reply=last_reply,
            attempts=attempts,
            from_cache=False,
        )


REFUSED = "judge_refused"


def annotate(material: dict, config: JudgeConfig, offline: bool) -> dict:
    """Every arm of every test point, judged.

    The rows carry no cache provenance and no attempt count: a replay serves
    from cache what a paid run asked for, and a report whose bytes moved between
    the two could not be the evidence for either.
    """
    if offline:
        transport = None
    else:
        load_dotenv()
        transport = OpenAICompatibleTransport()
    client = CachedJudgeClient(config, transport)
    rows = []
    # How many attempts each row cost, kept out of the table and written to the
    # cost record: a replay serves from cache what a paid run asked for, so this
    # is a property of an occasion rather than of the annotation.
    attempts: list[dict] = []
    for point in material["points"]:
        for arm in point["arms"]:
            prompt = load_prompt(
                PROMPT_NAME,
                {
                    "categories": "\n".join(
                        f"- `{name}`" for name in config.mqm_categories
                    ),
                    "severities": "\n".join(
                        f"- `{name}`" for name in config.mqm_severities
                    ),
                    "max_errors": str(config.max_errors),
                    "source_window": point["source_window"],
                    "tail_window": arm["tail_window"],
                    "head_window": arm["head_window"],
                },
            )
            key, judgement = client.judge(prompt)
            attempts.append(
                {
                    "point": f"{point['stem']} {point['boundary']}",
                    "arm": arm["arm"],
                    "attempts": judgement.attempts,
                    "from_cache": judgement.from_cache,
                }
            )
            rows.append(
                {
                    "point": f"{point['stem']} {point['boundary']}",
                    "sample": point["sample"],
                    "boundary": point["boundary"],
                    "adjudication_note": point["note"],
                    "arm": arm["arm"],
                    "path": arm["path"],
                    "origin": arm["origin"],
                    **config.pinned(),
                    "prompt_file": "prompts/" + PROMPT_NAME + ".md",
                    "prompt_file_sha256": prompt.digest,
                    "cache_key": key,
                    "source_window": point["source_window"],
                    "tail_window": arm["tail_window"],
                    "head_window": arm["head_window"],
                    "status": "annotated" if judgement.accepted else REFUSED,
                    "refusal_reason": "" if judgement.accepted else judgement.reason,
                    "reading": judgement.reading,
                    "errors": list(judgement.errors),
                    "reply": judgement.reply,
                }
            )
    cost = {
        "attempts_by_row": attempts,
        "cache_hits": client.cache_hits,
        "transport_requests": 0 if transport is None else transport.requests,
        "prompt_tokens": 0 if transport is None else transport.prompt_tokens,
        "completion_tokens": 0 if transport is None else transport.completion_tokens,
        "refusals": sum(1 for row in rows if row["status"] == REFUSED),
        "rows": len(rows),
    }
    return {"rows": rows, "cost": cost}


# --- the reports ----------------------------------------------------------


def report_of(material: dict, annotated: dict, config: JudgeConfig) -> dict:
    """The judgement table as it is written: deterministic over frozen inputs."""
    rows = annotated["rows"]
    tally: dict[str, int] = {}
    for row in rows:
        for error in row["errors"]:
            name = f"{error['category']}/{error['severity']}"
            tally[name] = tally.get(name, 0) + 1
    return {
        "generated_by": "tools/splice_judge.py",
        "metric": "M10",
        "protocol": "docs/eval/splice_protocol.md",
        "judge": {
            **config.pinned(),
            "base_url": config.base_url,
            "cache_key_version": CACHE_KEY_VERSION,
            "cache_engine": ENGINE_NAME,
            "max_errors": config.max_errors,
            "mqm_categories": list(config.mqm_categories),
            "mqm_severities": list(config.mqm_severities),
            "windows": {
                "source_window_characters": config.source_window_characters,
                "tail_window_characters": config.tail_window_characters,
                "head_window_characters": config.head_window_characters,
            },
        },
        "material_faults": material["faults"],
        "points": len({row["point"] for row in rows}),
        "arms": sorted({row["arm"] for row in rows}),
        "error_tally": dict(sorted(tally.items())),
        "rows": rows,
    }


def manual_review_of(report: dict) -> dict:
    """The rows a human is asked to check, exported as a review draft.

    Every row: the corpus owner chose full coverage over the fifth of the points
    GAP-03 asks for, which is affordable at this size and removes the question
    of whether the sampled rows were the flattering ones. The human fields are
    left empty; a filled copy of this file is the ruling, in the same shape the
    HITL review draft and its decisions file already have.

    Once answered, the file stops being this function's output: ``main`` leaves
    a ruled draft where it is rather than writing over it, so re-running the
    tool cannot destroy a ruling.
    """
    chosen = list(report["rows"])
    items = [
        {
            "id": f"{row['point']} [{row['arm']}]",
            "point": row["point"],
            "sample": row["sample"],
            "boundary": row["boundary"],
            "arm": row["arm"],
            "adjudication_note": row["adjudication_note"],
            "source_window": row["source_window"],
            "tail_window": row["tail_window"],
            "head_window": row["head_window"],
            "judge_model": row["judge_model"],
            "judge_status": row["status"],
            "judge_reading": row["reading"],
            "judge_errors": row["errors"],
            "human_agrees": None,
            "human_errors": None,
            "human_note": None,
        }
        for row in chosen
    ]
    return {
        "format_version": 1,
        "generated_by": "tools/splice_judge.py",
        "instructions": (
            "One item per splice point and arm. Read the three windows, then "
            "the judge's annotation. Set human_agrees to true or false; where "
            "it is false, put the annotation you would have given in "
            "human_errors, in the same shape as judge_errors and using the "
            "same two vocabularies; human_note is free text. Leave nothing at "
            "null in a filled copy."
        ),
        "selection_rule": "every point on every arm",
        "items": items,
    }


def _cell(text: str, limit: int = 40) -> str:
    """One window as a table cell: one line, cut, with the pipes escaped."""
    flat = " ".join((text or "").split())
    if len(flat) > limit:
        flat = flat[: limit - 3] + "..."
    return flat.replace("|", "\\|")


def markdown(report: dict) -> str:
    if not report["rows"]:
        return "# M10 splice point annotation (batch-e2.2)\n\nNo test point.\n"
    lines = [
        "# M10 splice point annotation (batch-e2.2)",
        "",
        f"Judge `{report['judge']['judge_model']}`, "
        f"transport `{json.dumps(report['judge']['judge_transport'], sort_keys=True)}`, "
        f"prompt `{report['rows'][0]['prompt_file']}` "
        f"(`{report['rows'][0]['prompt_file_sha256'][:12]}`). "
        f"Produced by `tools/splice_judge.py`; the protocol is "
        f"`{report['protocol']}`.",
        "",
        "## Per point, per arm",
        "",
        "| point | arm | path | status | errors | categories |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for row in report["rows"]:
        categories = ", ".join(
            f"{error['category']} ({error['severity']})" for error in row["errors"]
        )
        lines.append(
            f"| {row['point']} | `{row['arm']}` | {row['path']} | {row['status']} | "
            f"{len(row['errors'])} | {categories or '--'} |"
        )
    lines += [
        "",
        "## Readings",
        "",
        "| point | arm | what a reader gets across the boundary |",
        "| --- | --- | --- |",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['point']} | `{row['arm']}` | {_cell(row['reading'] or '', 160)} |"
        )
    lines += [
        "",
        "## Error tally",
        "",
        "| category/severity | count |",
        "| --- | ---: |",
    ]
    for name, count in report["error_tally"].items():
        lines.append(f"| `{name}` | {count} |")
    if not report["error_tally"]:
        lines.append("| -- | 0 |")
    lines += ["", "## Windows", ""]
    for row in report["rows"]:
        lines += [
            f"### {row['point']} [{row['arm']}]",
            "",
            f"- origin `{row['origin']}`",
            f"- tail: {_cell(row['tail_window'], 200)}",
            f"- head: {_cell(row['head_window'], 200)}",
            "",
        ]
    return "\n".join(lines) + "\n"


def manual_review_markdown(review: dict) -> str:
    lines = [
        "# Manual spot check of the splice judge (batch-e2.2)",
        "",
        review["instructions"],
        "",
        f"Selection rule: {review['selection_rule']}. "
        f"{len(review['items'])} items.",
        "",
        "The machine readable copy is `splice_manual_review.json`; fill that "
        "one and keep this as the reading copy.",
        "",
    ]
    for item in review["items"]:
        lines += [
            f"## {item['id']}",
            "",
            f"- adjudication: {item['adjudication_note']}",
            "",
            "**Source across the boundary**",
            "",
            "```",
            item["source_window"],
            "```",
            "",
            "**Tail (end of the page being left)**",
            "",
            "```",
            item["tail_window"],
            "```",
            "",
            "**Head (start of the page being entered)**",
            "",
            "```",
            item["head_window"],
            "```",
            "",
            f"**Judge ({item['judge_model']}, {item['judge_status']})**",
            "",
            f"- reading: {item['judge_reading'] or '--'}",
        ]
        for error in item["judge_errors"]:
            lines.append(
                f"- `{error['category']}` / `{error['severity']}` in "
                f"{error['window']}: \"{error['span']}\" -- {error['explanation']}"
            )
        if not item["judge_errors"]:
            lines.append("- no error reported")
        lines += [
            "",
            "**Your verdict**",
            "",
            "- human_agrees: [ ] yes  [ ] no",
            "- human_errors (if no):",
            "- human_note:",
            "",
        ]
    return "\n".join(lines) + "\n"


def _write(out: Path, stem: str, payload: dict, text: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / f"{stem}.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    (out / f"{stem}.md").write_text(text, encoding="utf-8")


def is_ruled(path: Path) -> bool:
    """Whether a review draft has been answered by a human.

    A draft exports its human fields as null. Any of them carrying a value
    makes the file a ruling, which belongs to whoever wrote it: the same
    discipline the HITL decisions file has, where the machine writes the draft
    and reads the ruling and never the other way round.
    """
    if not path.is_file():
        return False
    try:
        with path.open(encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return any(
        item.get(field) is not None
        for item in existing.get("items", ())
        for field in HUMAN_FIELDS
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "eval" / "results_e2",
        help="where the judgement table and the review draft are written",
    )
    parser.add_argument(
        "--cost-out",
        type=Path,
        default=ROOT / "examples" / "output" / "e2" / "r2" / "judge_cost.json",
        help="where the cost of this run is written; it is not part of the table",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="build no transport: a point not already cached stops the run",
    )
    args = parser.parse_args(argv)

    use_project_cache()
    config = load_judge_config()
    material = build_material(config)
    annotated = annotate(material, config, args.offline)
    report = report_of(material, annotated, config)
    _write(args.out, "splice_judgements", report, markdown(report))

    review = manual_review_of(report)
    review_path = args.out / "splice_manual_review.json"
    ruled = is_ruled(review_path)
    if not ruled:
        _write(args.out, "splice_manual_review", review, manual_review_markdown(review))

    args.cost_out.parent.mkdir(parents=True, exist_ok=True)
    with args.cost_out.open("w", encoding="utf-8") as f:
        json.dump(annotated["cost"], f, indent=2, sort_keys=True)
        f.write("\n")

    for fault in material["faults"]:
        print(f"MATERIAL FAULT: {fault}")
    print(
        f"points {report['points']}, rows {len(report['rows'])}, "
        f"refusals {annotated['cost']['refusals']}, "
        f"cache hits {annotated['cost']['cache_hits']}, "
        f"requests {annotated['cost']['transport_requests']}"
    )
    if ruled:
        print(f"manual review: {review_path.name} carries a ruling and was left alone")
    else:
        print(f"manual review items: {len(review['items'])}")
    if len(review["items"]) < MANUAL_REVIEW_MIN_POINTS:
        print(
            f"ERROR: {len(review['items'])} review items, fewer than the "
            f"{MANUAL_REVIEW_MIN_POINTS} the protocol asks for"
        )
        return 1
    return 1 if material["faults"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
