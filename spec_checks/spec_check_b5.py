"""Gate script for batch B5 (chain level joint translation).

Run from the repository root:

    python spec_checks/spec_check_b5.py

Exit code 0 when every assertion in plans/PLAN_B5.md that T5.1 and T5.2 answer
for passes, 1 otherwise.

Assertions 01 to 08 belong to T5.1, the pure layer: strings in, strings out,
nothing that runs a translator or touches the pipeline. Every one of them is a
synthetic case run directly against ``babeldoc/magazine/chain_backfill.py``,
except assertion 07, which takes the chains batch-b4.2 actually found in the
corpus, merges their members and cuts a deterministic stand-in translation back
up, so the conservation law is stated over real chain shapes and not only over
the cases this file thought to write down.

The synthetic cases are exhaustive in the directions that matter: both
translation directions, sentence counts above, equal to and below the member
count, a single sentence spanning three members, and the boundary cases of the
terminator model -- an ellipsis, a sentence closed by a quotation mark, a
decimal point, an initial and an abbreviation.

Assertions 10 to 15 belong to T5.2, the translation path. They drive the real
translation stage over the whole corpus with a stub engine, so no credential is
read and no request leaves the machine, and state the conservation law over
what the stage actually wrote: the members of a chain join back to exactly the
translation their chain was sent, every paragraph is translated exactly once,
the sentence spans tile the translation, and the switch being down reproduces
batch-b5.1's translator byte for byte. The stub is loaded twice per sample --
once against this session's translator and once against the one git holds at
batch-b5.1 -- which is what makes that last claim a comparison rather than an
assertion of intent.

Assertions 01g, 01h and 13b were added by batch B6's maintenance pass and cover
the output token budget: a chain whose answer would be larger than the engine
returns in one piece is handed back to the per paragraph path rather than sent
and truncated. 01g states that the size at which that happens is read from the
configuration, 01h that the budget stays under the ceiling the engine itself
applies, and 13b drives the exemption through the real stage with the budget
lowered until no chain fits, then asserts the members carry the per paragraph
translation.

CJK fixtures are built from code points instead of being written out, because
assertion 08c requires every file this batch changes to be ASCII.

Tiers: assertions 07 and 10 to 13 need the corpus artefacts and belong to the
pipeline tier; everything else is static. Assertion 09 is the full sweep and is
suppressed when the runner is already performing one.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import warnings
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import chain_backfill as backfill  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.chain_signals import CLASS_LABELS_KEY  # noqa: E402
from babeldoc.magazine.chain_signals import load_chain_config  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It asks the artifact builder
# for documents, so a cold slot means re-running the pipeline over the
# corpus -- minutes per sample -- and it runs on the cycle's full sweep
# rather than on every batch.
GATE_SET = "sweep"

BATCH_TAG = "batch-b5.2"

# The translator this session changed, as git holds it before the change. The
# switch-off comparison runs both and asks for the same bytes.
BASELINE_TAG = "batch-b5.1"

PYTHON = sys.executable

MODULE = "babeldoc/magazine/chain_backfill.py"
STAGE_MODULE = "babeldoc/magazine/chain_translation.py"
TRANSLATOR = "babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py"

# Where the engine's own output ceiling is written. The chain budget is
# measured against it rather than against a number this gate repeats.
ENGINE = "babeldoc/translator/translator.py"
ENGINE_CEILING_PATTERN = r"max_tokens\s*=\s*(\d+)"

CONFIG = "configs/chain_translation.json"
CONFIG_PATH = ROOT / CONFIG
OUTPUT_DIR = ROOT / "examples" / "output" / "b5"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = (
    "check_07_real_chains",
    "check_10_stub_corpus",
    "check_11_switch_off",
    "check_12_switch_on",
    "check_13_escalation",
    "check_15_sidecar",
)

# Paths this session may change.
ALLOWED_PREFIXES = ("spec_checks/", "plans/")
ALLOWED_FILES = {MODULE, STAGE_MODULE, CONFIG, "UPSTREAM_DIFF.md"}

# The two upstream files T5.2 declares. Everything else upstream is out of
# bounds, the per paragraph translator il_translator.py above all.
ALLOWED_UPSTREAM = {TRANSLATOR, "babeldoc/format/pdf/translation_config.py"}

# The upstream functions this session changed, each of which UPSTREAM_DIFF.md
# has to name in a row of its own.
UPSTREAM_SYMBOLS = (
    "ILTranslatorLLMOnly.translate",
    "ILTranslatorLLMOnly.process_cross_page_paragraph",
    "ILTranslatorLLMOnly.process_cross_column_paragraph",
    "ILTranslatorLLMOnly.process_page",
    "TranslationConfig.__init__",
)

# Trees and root documents owned by the magazine extension; the upstream scope
# assertion ignores them.
PROJECT_OWNED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "corpus/",
    "examples/",
    "plans/",
    "prompts/",
    "spec_checks/",
    "tools/",
)
PROJECT_OWNED_FILES = {"CLAUDE.md", "UPSTREAM_DIFF.md", "WAIVERS.md"}

CJK_SCAN_SUFFIXES = (".py", ".json")
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# The intermediate language fields B1 declared for the sentence range. The pure
# layer writes neither: they are written by the stage module, which is
# registered with the B1 consumer list as their first writer.
SEGMENT_FIELD_NAMES = ("segmentSentence", "segment_sentence")

# Fixtures. Ideographs stand in for target language text without this file
# holding any, and the punctuation is named rather than typed.
IDEOGRAPHS = "".join(chr(0x4E00 + offset) for offset in range(48))
CJK_FULL_STOP = "\u3002"
CJK_EXCLAMATION = "\uff01"
CJK_QUESTION = "\uff1f"
CJK_CLOSE_BRACKET = "\u300d"
CJK_OPEN_BRACKET = "\u300c"
ELLIPSIS = "\u2026"
SOFT_HYPHEN = "\u00ad"

# How long a stand-in translation is made, as a share of the source it stands
# in for. Only assertion 07 uses it and only to size deterministic filler.
STANDIN_LENGTH_RATIO = 0.6

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b5_"))
_timer = harness.Timer("spec_check_b5")


def ascii_only(text: str) -> str:
    """Escape what a console cannot encode.

    Half the fixtures here are target language text, so a detail line carries
    characters that a terminal in a single byte code page cannot print, and the
    sweep runner re-prints every line a gate emits. Escaping keeps the evidence
    readable and keeps a gate's own output from being the thing that fails.
    """
    return text.encode("ascii", "backslashreplace").decode("ascii")


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    detail = ascii_only(detail)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


# --- helpers ----------------------------------------------------------------


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def tag_exists(tag: str) -> bool:
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{tag}^{{commit}}"])
    return code == 0


def changed_files() -> set[str]:
    """Every path this batch changed, anchored on its tag once it exists."""
    if tag_exists(BATCH_TAG):
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^", BATCH_TAG])
        return {line.strip() for line in listing.splitlines() if line.strip()}

    _, tracked = git_output(["diff", "--name-only", "HEAD"])
    paths = {line.strip() for line in tracked.splitlines() if line.strip()}
    _, listing = git_output(["status", "--porcelain", "--untracked-files=all"])
    for line in listing.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def batch_revisions() -> list[str]:
    """Revision arguments selecting the delta this session introduced.

    Once the session is committed and tagged that is the tag against its parent;
    while it is still uncommitted it is the working tree against HEAD, so what
    is being written now is inside the scope as well.
    """
    if tag_exists(BATCH_TAG):
        return [f"{BATCH_TAG}^", BATCH_TAG]
    return ["HEAD"]


def config() -> backfill.BackfillConfig:
    return backfill.load_backfill_config()


def latin() -> backfill.LanguageProfile:
    return backfill.select_profile("en", config())


def cjk() -> backfill.LanguageProfile:
    return backfill.select_profile("zh", config())


def write_config(name: str, mutate) -> str:
    """A copy of the shipped configuration with one thing changed."""
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    path = _tmp_root / f"{name}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return str(path)


def first_over_budget(candidate: backfill.BackfillConfig) -> int:
    """The smallest merged chain, in source tokens, this configuration refuses.

    Walked rather than solved, so the boundary comes out of the module's own
    decision instead of out of this file's arithmetic.
    """
    ceiling = candidate.output_token_budget + 1
    for count in range(math.ceil(ceiling / candidate.output_token_ratio) + 2):
        if backfill.over_output_token_budget(count, candidate):
            return count
    raise AssertionError(f"nothing is over the budget of {candidate}")


def refuses(path: str) -> str | None:
    """The complaint a malformed configuration draws, or None if it loads."""
    try:
        backfill.load_backfill_config(path)
    except backfill.ConfigError as error:
        return str(error)
    return None


def invariants(
    merge: backfill.ChainMerge,
    translated: str,
    result: backfill.Redistribution,
) -> list[str]:
    """Everything the conservation law says, checked independently of it.

    The gate re-derives the law from the arguments rather than calling the
    module's own verifier alone, so a verifier that agreed with a broken
    redistribution would still be caught here.
    """
    problems: list[str] = []
    if "".join(result.texts) != translated:
        problems.append("the pieces do not join back to the translation")
    if len(result.segments) != len(merge.members):
        problems.append("the member count changed")
    if any(not segment.text for segment in result.segments):
        problems.append("a member received an empty piece")
    cursor = 0
    for segment in result.segments:
        if segment.start != cursor or segment.end <= segment.start:
            problems.append(f"span {segment.start}..{segment.end} at {cursor}")
        if segment.text != translated[segment.start : segment.end]:
            problems.append(f"member {segment.index} is not the text at its span")
        cursor = segment.end
    if cursor != len(translated):
        problems.append(f"the spans stop at {cursor} of {len(translated)}")
    if "".join(result.sentences) != translated:
        problems.append("the sentences do not join back to the translation")

    marked = {
        segment.sentence_start == backfill.NO_SENTENCE_INDEX
        for segment in result.segments
    }
    if len(marked) != 1:
        problems.append("only some members claim a sentence range")
    elif not marked.pop():
        cursor = 0
        for segment in result.segments:
            if segment.sentence_start != cursor or segment.sentence_end < cursor:
                problems.append(
                    f"sentence range {segment.sentence_start}.."
                    f"{segment.sentence_end} at {cursor}"
                )
            cursor = segment.sentence_end
        if cursor != len(result.sentences):
            problems.append(
                f"the sentence ranges stop at {cursor} of {len(result.sentences)}"
            )
    report = backfill.verify_redistribution(merge, translated, result)
    if not report.ok:
        problems.extend(report.violations)
    return problems


def read_checkpoint(path: Path) -> il_version_1.Document:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return XMLConverter().read_xml(str(path))


def sample_pdfs() -> list[Path]:
    manifest = corpus.load_manifest()
    return [
        ROOT / "examples" / "input" / entry["file"] for entry in manifest["samples"]
    ]


# --- 01 configuration -------------------------------------------------------


def check_01_configuration() -> None:
    """Positive 1: every parameter is declared, bounded and actually consulted."""
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    flat = {
        key: value
        for key, value in raw.items()
        if key not in backfill.NESTED_KEYS and key != backfill.DESCRIPTION_KEY
    }
    unbounded = [
        key
        for key, value in flat.items()
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and f"{key}{backfill.RANGE_SUFFIX}" not in flat
    ]
    loaded = config()
    record(
        "01a every flat parameter declares an allowed range and loads",
        not unbounded and loaded.sentence_min_chars > 0,
        f"unbounded={unbounded} parameters={sorted(flat)}",
    )

    profiles = loaded.profiles
    unimplemented_rules = sorted(
        {
            profile.break_rule
            for profile in profiles.values()
            if profile.break_rule not in backfill.BREAK_RULES
        }
    )
    named = {loaded.default_strategy, *loaded.strategy_by_pair_class.values()}
    unimplemented_strategies = sorted(named - set(backfill.STRATEGIES))
    record(
        "01b every strategy and break rule named is one the module implements",
        not unimplemented_rules
        and not unimplemented_strategies
        and loaded.default_profile in profiles,
        f"strategies={sorted(named)} rules={sorted({p.break_rule for p in profiles.values()})}",
    )

    declared_classes = set(load_chain_config()[CLASS_LABELS_KEY])
    unknown_classes = sorted(set(loaded.strategy_by_pair_class) - declared_classes)
    # The route session two takes: a chain arrives with the pair class it was
    # built under and leaves with the strategy declared for it, and a class
    # nobody declared takes the default rather than failing.
    routed = {
        pair_class: backfill.strategy_for_pair_class(pair_class, loaded)
        for pair_class in (*sorted(declared_classes), "unclaimed", None)
    }
    record(
        "01c every pair class routed to a strategy is one chain detection declares",
        not unknown_classes
        and bool(loaded.strategy_by_pair_class)
        and routed
        == {
            **loaded.strategy_by_pair_class,
            "unclaimed": loaded.default_strategy,
            None: loaded.default_strategy,
        },
        f"routed={routed} declared={sorted(declared_classes)} unknown={unknown_classes}",
    )

    def out_of_range(raw_config: dict) -> None:
        entry = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]["latin"]
        entry[backfill.SENTENCE_MIN_CHARS_KEY] = 4000

    def unknown_rule(raw_config: dict) -> None:
        entry = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]["latin"]
        entry["break_rule"] = "syllable"

    def duplicate_prefix(raw_config: dict) -> None:
        entries = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]
        entries["cjk"]["language_prefixes"] = ["zh", "en"]

    def unknown_strategy(raw_config: dict) -> None:
        raw_config[backfill.STRATEGIES_KEY][backfill.BY_PAIR_CLASS_KEY]["body"] = (
            "guess"
        )

    def no_range(raw_config: dict) -> None:
        del raw_config[f"snap_search_ratio{backfill.RANGE_SUFFIX}"]

    def no_terminators(raw_config: dict) -> None:
        entry = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]["latin"]
        entry["terminators"] = []
        entry["space_gated_terminators"] = []

    def toothless_abbreviation(raw_config: dict) -> None:
        entry = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]["latin"]
        entry[backfill.NON_TERMINAL_PREFIXES_KEY] = ["Doctor"]

    malformed = {
        "out_of_range": out_of_range,
        "unknown_rule": unknown_rule,
        "duplicate_prefix": duplicate_prefix,
        "unknown_strategy": unknown_strategy,
        "no_range": no_range,
        "no_terminators": no_terminators,
        "toothless_abbreviation": toothless_abbreviation,
    }
    accepted = [
        name
        for name, mutate in malformed.items()
        if refuses(write_config(name, mutate)) is None
    ]
    record(
        "01d a malformed configuration is refused at load",
        not accepted,
        f"cases={sorted(malformed)} accepted={accepted}",
    )

    # The thresholds live in the file, not in the code: moving them moves the
    # behaviour. Ungating the full stop makes a decimal point end a sentence,
    # and raising the floor swallows a short one.
    def ungate(raw_config: dict) -> None:
        entry = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]["latin"]
        entry["terminators"] = [
            *entry["terminators"],
            *entry["space_gated_terminators"],
        ]
        entry["space_gated_terminators"] = []

    def raise_floor(raw_config: dict) -> None:
        entry = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]["latin"]
        entry[backfill.SENTENCE_MIN_CHARS_KEY] = 40

    decimal = "It costs 3.14 today. Next one."
    shipped = backfill.split_sentences(decimal, latin())
    ungated_config = backfill.load_backfill_config(write_config("ungated", ungate))
    ungated = backfill.split_sentences(
        decimal, backfill.select_profile("en", ungated_config)
    )
    floored_config = backfill.load_backfill_config(write_config("floored", raise_floor))
    floored = backfill.split_sentences(
        decimal, backfill.select_profile("en", floored_config)
    )
    record(
        "01e the terminator set and the floor are read from the file, not the code",
        len(shipped) == 2 and len(ungated) == 3 and len(floored) == 1,
        f"shipped={len(shipped)} ungated={len(ungated)} floored={len(floored)} "
        f"decimal_kept={shipped[0]!r}",
    )

    # Substituting the vocabulary substitutes the behaviour completely: the
    # marks the file names end sentences and the ones it drops stop doing so.
    # A module carrying a fallback terminator set of its own could not do that.
    marker = "~"

    def substitute(raw_config: dict) -> None:
        entry = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]["latin"]
        entry["terminators"] = [marker]
        entry["space_gated_terminators"] = []
        entry["closers"] = []
        # The abbreviations go with them: an abbreviation is read at a
        # terminator, so a profile that no longer declares the terminator it
        # was written with cannot declare the abbreviation either.
        entry[backfill.NON_TERMINAL_PREFIXES_KEY] = []

    substituted = backfill.select_profile(
        "en", backfill.load_backfill_config(write_config("substituted", substitute))
    )
    marked = backfill.split_sentences("one~ two~ three", substituted)
    unmarked = backfill.split_sentences("one. two! three?", substituted)
    source = (ROOT / MODULE).read_text(encoding="utf-8")
    vocabulary = sorted(
        set(latin().all_terminators)
        | set(latin().closers)
        | set(cjk().all_terminators)
        | set(cjk().closers)
        | set(config().join.trailing_hyphens)
    )
    # Only the marks that are not Python syntax can be told apart from the
    # language the module is written in; the CJK scan of assertion 08c covers
    # the rest of the ideographic vocabulary.
    literals = [
        f"U+{ord(char):04X}"
        for char in vocabulary
        if ord(char) > 0x7F and char in source
    ]
    record(
        "01f the module carries no terminator vocabulary of its own",
        len(marked) == 3 and len(unmarked) == 1 and not literals,
        f"substituted={marked} shipped_marks={unmarked} "
        f"vocabulary={len(vocabulary)} literals={literals}",
    )

    # The output budget is a threshold like any other: the size at which a
    # chain stops being sent as one unit moves when the file moves, down with
    # the budget and up as the coefficient falls.
    def halve_budget(raw_config: dict) -> None:
        raw_config["output_token_budget"] = raw_config["output_token_budget"] // 2

    def halve_ratio(raw_config: dict) -> None:
        raw_config["output_token_ratio"] = raw_config["output_token_ratio"] / 2

    shipped_config = config()
    smaller = backfill.load_backfill_config(write_config("small_budget", halve_budget))
    cheaper = backfill.load_backfill_config(write_config("small_ratio", halve_ratio))
    limits = {
        name: first_over_budget(candidate)
        for name, candidate in (
            ("shipped", shipped_config),
            ("halved_budget", smaller),
            ("halved_ratio", cheaper),
        )
    }
    monotone = all(
        backfill.estimated_output_tokens(count, shipped_config)
        <= backfill.estimated_output_tokens(count + 1, shipped_config)
        for count in range(0, limits["shipped"] + 2)
    )
    record(
        "01g the output budget and its coefficient are read from the file",
        limits["halved_budget"] < limits["shipped"] < limits["halved_ratio"]
        and not backfill.over_output_token_budget(0, shipped_config)
        and monotone,
        f"first_over={limits}",
    )

    # The budget exists because the engine truncates rather than refusing, so
    # it has to sit under the ceiling the engine actually applies. That number
    # is read out of the engine rather than repeated here, so this fails if
    # upstream moves it.
    ceilings = [
        int(found)
        for found in re.findall(
            ENGINE_CEILING_PATTERN, (ROOT / ENGINE).read_text(encoding="utf-8")
        )
    ]
    record(
        "01h the chain budget stays under the ceiling the engine applies",
        bool(ceilings) and shipped_config.output_token_budget < min(ceilings),
        f"budget={shipped_config.output_token_budget} engine_ceilings={ceilings}",
    )


# --- 02 merge ---------------------------------------------------------------


def check_02_merge() -> None:
    """Positive 2: members merge in order and the merge can be read back."""
    parts = ["Alpha beta gamma", "delta epsilon", "zeta eta."]
    merge = backfill.merge_chain_text(parts, config())
    rebuilt = "".join(
        separator + member
        for separator, member in zip(merge.separators, merge.members, strict=True)
    )
    spans_ok = all(
        merge.text[start:end] == member
        for (start, end), member in zip(merge.spans, merge.members, strict=True)
    )
    record(
        "02a the merge is the members in chain order, joined by what it records",
        rebuilt == merge.text
        and spans_ok
        and list(merge.members) == parts
        and merge.separators[0] == "",
        f"text={merge.text!r}",
    )

    broken = backfill.merge_chain_text(["Alpha beta gam-", "ma delta."], config())
    soft = backfill.merge_chain_text(
        [f"Alpha beta gam{SOFT_HYPHEN}", "ma delta."], config()
    )
    standalone = backfill.merge_chain_text(["a dash -", "next word"], config())
    record(
        "02b a page break hyphen closes up and a standalone hyphen does not",
        broken.text == "Alpha beta gamma delta."
        and broken.dropped_hyphens == (0,)
        and soft.text == "Alpha beta gamma delta."
        and standalone.text == "a dash - next word"
        and standalone.dropped_hyphens == (),
        f"broken={broken.text!r} standalone={standalone.text!r}",
    )

    ideographic = backfill.merge_chain_text(
        [IDEOGRAPHS[:4], IDEOGRAPHS[4:8] + CJK_FULL_STOP], config()
    )
    roman = backfill.merge_chain_text(["first half", "second half"], config())
    mixed = backfill.merge_chain_text([IDEOGRAPHS[:4], "second half"], config())
    record(
        "02c a spaceless script closes up and everything else takes a space",
        ideographic.separators == ("", "")
        and roman.separators == ("", " ")
        and mixed.separators == ("", " "),
        f"ideographic={ideographic.separators} roman={roman.separators} "
        f"mixed={mixed.separators}",
    )

    rejected = []
    for case in ([], [""], ["fine", "   "], ["fine", "\n\t "]):
        try:
            backfill.merge_chain_text(case, config())
        except backfill.ChainBackfillError:
            rejected.append(True)
        else:
            rejected.append(False)
    non_string = False
    try:
        backfill.merge_chain_text(["fine", None], config())
    except backfill.ChainBackfillError:
        non_string = True
    record(
        "02d an empty chain and a member carrying no text are refused",
        all(rejected) and non_string,
        f"rejected={rejected} non_string={non_string}",
    )

    shares = backfill.merge_chain_text(["aaaa", "bbbbbbbb"], config()).shares
    record(
        "02e a member's share of the source is its share of the characters",
        abs(shares[0] - 1 / 3) < 1e-9 and abs(shares[1] - 2 / 3) < 1e-9,
        f"shares={shares}",
    )


# --- 03 sentences -----------------------------------------------------------


def check_03_sentences() -> None:
    """Positive 3: the sentence model, including where it is known to be wrong."""
    cases = [
        "The first one ends here. The second follows it. And a third.",
        f"Wait{ELLIPSIS} What? Yes.",
        'He said "Stop!" Then he left.',
        "It costs 3.14 dollars today. Next one.",
        "Dr. Smith arrived. He left.",
        "J. R. Smith wrote it. Later on.",
        "no terminator at all",
        "Ends on a space. ",
    ]
    profile = latin()
    broken = [
        text
        for text in cases
        if "".join(backfill.split_sentences(text, profile)) != text
    ]
    ideographic = [
        IDEOGRAPHS[:3] + CJK_FULL_STOP + IDEOGRAPHS[3:6] + CJK_EXCLAMATION,
        CJK_OPEN_BRACKET + IDEOGRAPHS[:3] + CJK_FULL_STOP + CJK_CLOSE_BRACKET,
        IDEOGRAPHS[:5],
    ]
    broken.extend(
        text
        for text in ideographic
        if "".join(backfill.split_sentences(text, cjk())) != text
    )
    record(
        "03a the sentences of a text always join back to exactly that text",
        not broken,
        f"cases={len(cases) + len(ideographic)} broken={broken[:2]}",
    )

    plain = backfill.split_sentences(cases[0], profile)
    record(
        "03b three sentences come out of three",
        len(plain) == 3 and plain[0] == "The first one ends here. ",
        f"sentences={plain}",
    )

    dotted = backfill.split_sentences(f"Wait{ELLIPSIS} What? Yes.", profile)
    triple = backfill.split_sentences("Wait... What? Yes.", profile)
    record(
        "03c an ellipsis is one boundary, written either way",
        len(dotted) == 3
        and dotted[0] == f"Wait{ELLIPSIS} "
        and len(triple) == 3
        and triple[0] == "Wait... ",
        f"single={dotted} spelled={triple}",
    )

    quoted = backfill.split_sentences('He said "Stop!" Then he left.', profile)
    record(
        "03d a sentence closed by a quotation mark ends after the quotation",
        len(quoted) == 2 and quoted[0] == 'He said "Stop!" ',
        f"sentences={quoted}",
    )

    decimal = backfill.split_sentences(
        "It costs 3.14 dollars today. Next one.", profile
    )
    versioned = backfill.split_sentences("Read v1.2.3 first. Then go.", profile)
    record(
        "03e a decimal point and a version number do not end a sentence",
        len(decimal) == 2 and len(versioned) == 2,
        f"decimal={decimal} versioned={versioned}",
    )

    # Known limitation, asserted as it behaves. The floor absorbs an initial
    # only while the sentence so far is shorter than it, so a run of initials
    # splits once the run itself clears the floor.
    initials = backfill.split_sentences("J. R. Smith wrote it. Later on.", profile)
    record(
        "03f an initial at the head of a sentence is absorbed by the floor",
        initials == ("J. R. ", "Smith wrote it. ", "Later on."),
        f"sentences={initials}",
    )

    # Was a known limitation until the abbreviation table: an abbreviation long
    # enough to clear the floor used to be read as a sentence end and to offer
    # a cut position mid-sentence. A declared one no longer does.
    declared = [
        backfill.split_sentences(text, profile)
        for text in (
            "Dr. Smith arrived. He left.",
            "See Fig. 3 for the layout. Then go.",
            "The U.S. delegation left. It rained.",
            "Read vol. 4 first. Then go.",
        )
    ]
    record(
        "03g a declared abbreviation no longer ends a sentence",
        all(len(sentences) == 2 for sentences in declared)
        and declared[0][0] == "Dr. Smith arrived. ",
        f"sentences={[len(s) for s in declared]} first={declared[0]}",
    )

    # The table is a table, not a rule: an abbreviation nobody declared still
    # over-splits, and removing the shipped table brings the old behaviour back,
    # which is what shows the behaviour lives in the file.
    def drop_prefixes(raw_config: dict) -> None:
        entry = raw_config[backfill.PROFILES_KEY][backfill.ENTRIES_KEY]["latin"]
        entry[backfill.NON_TERMINAL_PREFIXES_KEY] = []

    stripped = backfill.select_profile(
        "en", backfill.load_backfill_config(write_config("no_prefixes", drop_prefixes))
    )
    undeclared = backfill.split_sentences("A config. of sorts. Next.", profile)
    without = backfill.split_sentences("Dr. Smith arrived. He left.", stripped)
    record(
        "03j the abbreviation table comes from the file and covers only what it names",
        without == ("Dr. ", "Smith arrived. ", "He left.")
        and len(undeclared) == 3
        and "".join(without) == "Dr. Smith arrived. He left."
        and "".join(undeclared) == "A config. of sorts. Next.",
        f"without_table={without} undeclared={undeclared}",
    )

    record(
        "03h a text with no terminator is one sentence, and an empty text none",
        backfill.split_sentences("no terminator at all", profile)
        == ("no terminator at all",)
        and backfill.split_sentences("", profile) == (),
        "",
    )

    enders = (
        IDEOGRAPHS[:3]
        + CJK_FULL_STOP
        + IDEOGRAPHS[3:6]
        + CJK_EXCLAMATION
        + IDEOGRAPHS[6:9]
        + CJK_QUESTION
    )
    bracketed = backfill.split_sentences(
        CJK_OPEN_BRACKET
        + IDEOGRAPHS[:3]
        + CJK_FULL_STOP
        + CJK_CLOSE_BRACKET
        + IDEOGRAPHS[3:6]
        + CJK_FULL_STOP,
        cjk(),
    )
    record(
        "03i the target script has its own enders and its own closing mark",
        len(backfill.split_sentences(enders, cjk())) == 3
        and len(bracketed) == 2
        and bracketed[0].endswith(CJK_CLOSE_BRACKET),
        f"enders={len(backfill.split_sentences(enders, cjk()))} "
        f"bracketed={len(bracketed)}",
    )


# --- 04 body redistribution -------------------------------------------------


def body_case(members: list[str], translated: str, language: str):
    merge = backfill.merge_chain_text(members, config())
    result = backfill.redistribute(
        merge, translated, language, backfill.STRATEGY_SENTENCE_GREEDY, config()
    )
    return merge, result


def check_04_body() -> None:
    """Positive 4: a body chain is cut on sentence ends wherever it can be."""
    members = [
        "First part of the article body.",
        "Second part continues it.",
        "Third part ends it.",
    ]
    six = " ".join(f"Sentence number {index} lands here." for index in range(1, 7))
    merge, result = body_case(members, six, "en")
    ends = set(backfill.sentence_end_offsets(result.sentences))
    on_boundary = all(cut.position in ends for cut in result.cuts)
    record(
        "04a with sentences to spare every cut lands on a sentence end",
        not invariants(merge, six, result)
        and on_boundary
        and result.fallback is None
        and all(cut.mode == backfill.CUT_SENTENCE for cut in result.cuts)
        and result.segments[-1].sentence_end == len(result.sentences),
        f"cuts={[(c.position, c.mode) for c in result.cuts]} "
        f"sentences={len(result.sentences)}",
    )

    two = "Sentence one lands right here. Sentence two lands over there as well."
    merge, result = body_case(members, two, "en")
    modes = [cut.mode for cut in result.cuts]
    record(
        "04b with fewer sentences than members the remainder is cut by share",
        not invariants(merge, two, result)
        and result.fallback == backfill.FALLBACK_PROPORTIONAL
        and backfill.CUT_SENTENCE in modes
        and backfill.CUT_PROPORTIONAL in modes
        and all(segment.text.strip() for segment in result.segments),
        f"modes={modes} pieces={[len(s.text) for s in result.segments]}",
    )

    one = "A single unbroken sentence that has to serve all three of the members here."
    merge, result = body_case(members, one, "en")
    ranges = [(s.sentence_start, s.sentence_end) for s in result.segments]
    record(
        "04c one sentence spanning three members is cut by share throughout",
        not invariants(merge, one, result)
        and result.fallback == backfill.FALLBACK_PROPORTIONAL
        and all(cut.mode == backfill.CUT_PROPORTIONAL for cut in result.cuts)
        and len(result.sentences) == 1
        and ranges[-1][1] == 1,
        f"ranges={ranges} cuts={[c.position for c in result.cuts]}",
    )

    # The source is English and the target the ideographic script; then the
    # other way round. Both have to hold every invariant, and each has to
    # resolve to the profile of its own target.
    forward_source = ["The first paragraph of the body.", "The second paragraph ends."]
    forward_target = IDEOGRAPHS[:8] + CJK_FULL_STOP + IDEOGRAPHS[8:16] + CJK_FULL_STOP
    forward_merge, forward = body_case(forward_source, forward_target, "zh-CN")
    back_source = [IDEOGRAPHS[:10] + CJK_FULL_STOP, IDEOGRAPHS[10:18] + CJK_FULL_STOP]
    back_target = "The first part is here. The second part follows it."
    back_merge, back = body_case(back_source, back_target, "en")
    record(
        "04d both translation directions hold, each on its target's profile",
        not invariants(forward_merge, forward_target, forward)
        and not invariants(back_merge, back_target, back)
        and forward.profile == cjk().name
        and back.profile == latin().name
        and forward.fallback is None
        and back.fallback is None,
        f"forward={forward.profile}/{[s.text for s in forward.segments]} "
        f"back={back.profile}",
    )

    equal = ["a" * 20, "b" * 20, "c" * 20]
    merge, result = body_case(equal, six, "en")
    counts = [s.sentence_end - s.sentence_start for s in result.segments]
    record(
        "04e equal source shares over six sentences give each member two",
        counts == [2, 2, 2] and not invariants(merge, six, result),
        f"counts={counts}",
    )

    # Exhaustive over the shape that matters: member count against sentence
    # count, in both directions, every combination.
    problems: list[str] = []
    for member_count in range(1, 6):
        for sentence_count in range(1, 8):
            for language, ender, filler in (
                ("en", ".", "word "),
                ("zh", CJK_FULL_STOP, IDEOGRAPHS[:4]),
            ):
                source = [f"member {index} text" for index in range(member_count)]
                translated = "".join(
                    f"{filler * 2}{index}{ender} "
                    if language == "en"
                    else f"{filler}{index}{ender}"
                    for index in range(sentence_count)
                )
                merge = backfill.merge_chain_text(source, config())
                result = backfill.redistribute(
                    merge,
                    translated,
                    language,
                    backfill.STRATEGY_SENTENCE_GREEDY,
                    config(),
                )
                failures = invariants(merge, translated, result)
                if failures:
                    problems.append(
                        f"{member_count}x{sentence_count}/{language}: {failures[0]}"
                    )
                short = sentence_count < member_count
                if short and result.fallback != backfill.FALLBACK_PROPORTIONAL:
                    problems.append(
                        f"{member_count}x{sentence_count}/{language}: "
                        f"fewer sentences than members went unreported"
                    )
    record(
        "04f every member count against every sentence count holds the law",
        not problems,
        f"combinations={5 * 7 * 2} problems={problems[:3]}",
    )


# --- 05 title redistribution ------------------------------------------------


def check_05_title() -> None:
    """Positive 5: a display line chain is cut by share and claims no sentences."""
    members = ["The Long Headline That", "Runs Across The Break"]
    merge = backfill.merge_chain_text(members, config())

    target = IDEOGRAPHS[:14]
    result = backfill.redistribute(
        merge, target, "zh", backfill.STRATEGY_PROPORTIONAL, config()
    )
    marked = all(
        segment.sentence_start == backfill.NO_SENTENCE_INDEX
        and segment.sentence_end == backfill.NO_SENTENCE_INDEX
        for segment in result.segments
    )
    record(
        "05a a title chain claims no sentence range and reports no fallback",
        not invariants(merge, target, result)
        and marked
        and result.fallback is None
        and all(cut.mode == backfill.CUT_PROPORTIONAL for cut in result.cuts),
        f"ranges={[(s.sentence_start, s.sentence_end) for s in result.segments]}",
    )

    shares = merge.shares
    actual = [len(segment.text) / len(target) for segment in result.segments]
    drift = max(abs(a - b) * len(target) for a, b in zip(actual, shares, strict=True))
    record(
        "05b an ideographic target is cut anywhere, tracking the source shares",
        drift <= 1.0 and not invariants(merge, target, result),
        f"source={[round(s, 3) for s in shares]} cut={[round(a, 3) for a in actual]} "
        f"drift_chars={drift:.2f}",
    )

    headline = "The Long Headline That Runs Across The Break"
    roman = backfill.redistribute(
        merge, headline, "en", backfill.STRATEGY_PROPORTIONAL, config()
    )
    mid_word = [
        cut.position
        for cut in roman.cuts
        if not (
            headline[cut.position - 1].isspace()
            and not headline[cut.position].isspace()
        )
    ]
    record(
        "05c a word boundary target is only ever cut between words",
        not mid_word
        and all(cut.snapped for cut in roman.cuts)
        and not invariants(merge, headline, roman),
        f"cuts={[c.position for c in roman.cuts]} mid_word={mid_word} "
        f"pieces={[s.text for s in roman.segments]}",
    )

    # Known limitation, asserted as it behaves: with no legal break inside the
    # search radius the cut is placed at the position share asks for and says
    # it was not snapped. The law still holds; only the word does not.
    unbroken = "a" * 40
    forced = backfill.redistribute(
        merge, unbroken, "en", backfill.STRATEGY_PROPORTIONAL, config()
    )
    record(
        "05d with no legal break in reach the cut is unsnapped and says so",
        not any(cut.snapped for cut in forced.cuts)
        and not invariants(merge, unbroken, forced),
        f"cuts={[(c.position, c.snapped) for c in forced.cuts]}",
    )


# --- 06 conservation --------------------------------------------------------


def check_06_conservation() -> None:
    """Negative 6: the conservation law refuses a result that breaks it."""
    members = ["First part of the body.", "Second part of the body."]
    translated = "Sentence one is here. Sentence two is here."
    merge = backfill.merge_chain_text(members, config())
    good = backfill.redistribute(
        merge, translated, "en", backfill.STRATEGY_SENTENCE_GREEDY, config()
    )
    record(
        "06a the law accepts a redistribution the module produced",
        backfill.verify_redistribution(merge, translated, good).ok,
        f"pieces={[s.text for s in good.segments]}",
    )

    first, second = good.segments

    def doctor(segments) -> backfill.Redistribution:
        return replace(good, segments=tuple(segments))

    cases = {
        "changed_character": doctor([replace(first, text=first.text.upper()), second]),
        "overlap": doctor([first, replace(second, start=second.start - 3)]),
        "gap": doctor(
            [replace(first, end=first.end - 3, text=first.text[:-3]), second]
        ),
        "empty_member": doctor(
            [
                replace(first, end=first.start, text=""),
                replace(second, start=first.start),
            ]
        ),
        "dropped_member": doctor([first]),
        "sentence_overlap": doctor(
            [replace(first, sentence_end=2), replace(second, sentence_start=0)]
        ),
        "sentence_gap": doctor([replace(first, sentence_end=0), second]),
        "sentence_truncated": doctor([first, replace(second, sentence_end=1)]),
        "half_marked": doctor(
            [replace(first, sentence_start=backfill.NO_SENTENCE_INDEX), second]
        ),
    }
    accepted = [
        name
        for name, broken in cases.items()
        if backfill.verify_redistribution(merge, translated, broken).ok
    ]
    record(
        "06b the law refuses a doctored redistribution of every shape",
        not accepted,
        f"cases={sorted(cases)} accepted={accepted}",
    )

    refused: dict[str, bool] = {}
    for name, arguments in (
        ("too_short", (merge, "a", "en", backfill.STRATEGY_SENTENCE_GREEDY)),
        ("blank", (merge, "   \n ", "en", backfill.STRATEGY_SENTENCE_GREEDY)),
        ("unknown_strategy", (merge, translated, "en", "vibes")),
    ):
        try:
            backfill.redistribute(*arguments, config())
        except backfill.ChainBackfillError:
            refused[name] = True
        else:
            refused[name] = False
    record(
        "06c a translation that cannot be shared out is refused, not truncated",
        all(refused.values()),
        f"refused={refused}",
    )


# --- 07 real chains ---------------------------------------------------------


def standin_translation(source: str, profile: backfill.LanguageProfile) -> str:
    """A deterministic stand-in translation that keeps the sentence structure.

    Every source sentence becomes one target sentence of proportional length,
    built from ideographs. No translator runs and no credential is read; the
    point is the shape of the text, not its meaning.
    """
    pieces: list[str] = []
    for order, sentence in enumerate(backfill.split_sentences(source, profile)):
        length = max(1, round(len(sentence) * STANDIN_LENGTH_RATIO))
        pieces.append(
            "".join(
                IDEOGRAPHS[(order + index) % len(IDEOGRAPHS)] for index in range(length)
            )
        )
        pieces.append(CJK_FULL_STOP)
    return "".join(pieces) if pieces else IDEOGRAPHS[:4] + CJK_FULL_STOP


def endpoint_pairs(report: dict) -> list[list[str]]:
    """Every endpoint pair the detector scored, linked or not.

    The chains the corpus actually produced are few, because the detector is
    deliberately reluctant to link. Every pair it scored is nonetheless a real
    pair of magazine paragraphs that a differently tuned detector would chain,
    so they all stand as candidate chains here and widen this assertion from
    the handful of chains to the whole boundary set.
    """
    candidates: list[list[str]] = []
    for boundary in report["boundaries"]:
        for scored in boundary.get("pairs") or ():
            members = [scored.get("tail_text") or "", scored.get("head_text") or ""]
            if all(member.strip() for member in members):
                candidates.append(members)
    return candidates


def check_07_real_chains() -> None:
    """Positive 7: the law holds over the chains the corpus actually produced."""
    from babeldoc.magazine.checkpoint import checkpoint_stem

    chains: list[list[str]] = []
    candidates: list[list[str]] = []
    for pdf in sample_pdfs():
        built = artifacts.get_artifacts(pdf, "chained")
        report_path = built.working_dir / "chain_report.json"
        checkpoint = built.working_dir / f"{checkpoint_stem('chain_builder')}.xml"
        if not report_path.exists() or not checkpoint.exists():
            continue
        document = read_checkpoint(checkpoint)
        texts = {
            paragraph.debug_id: paragraph.unicode
            for page in document.page
            for paragraph in page.pdf_paragraph
            if paragraph.debug_id is not None and paragraph.unicode is not None
        }
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for chain in report["chains"]:
            members = [
                texts.get(member["debug_id"], "")
                for member in sorted(chain["members"], key=lambda m: m["chain_index"])
            ]
            if all(member.strip() for member in members):
                chains.append(members)
        candidates.extend(endpoint_pairs(report))

    problems: list[str] = []
    covered = 0
    source_profile = backfill.select_profile("en", config())
    for members in (*chains, *candidates):
        merge = backfill.merge_chain_text(members, config())
        for translated, language in (
            (merge.text, "en"),
            (standin_translation(merge.text, source_profile), "zh"),
        ):
            for strategy in backfill.STRATEGIES:
                try:
                    result = backfill.redistribute(
                        merge, translated, language, strategy, config()
                    )
                except backfill.ChainBackfillError as error:
                    problems.append(f"{language}/{strategy}: refused :: {error}")
                    continue
                failures = invariants(merge, translated, result)
                if failures:
                    problems.append(f"{language}/{strategy}: {failures[0]}")
                covered += 1
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "real_chains.json").write_text(
        json.dumps(
            {
                "chains": len(chains),
                "scored_pairs": len(candidates),
                "redistributions": covered,
                "member_counts": [len(members) for members in chains],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    record(
        "07 the law holds over every chain the corpus produced",
        bool(chains) and bool(candidates) and not problems,
        f"chains={len(chains)} scored_pairs={len(candidates)} "
        f"redistributions={covered} problems={problems[:3]}",
    )


# --- 08 change scope --------------------------------------------------------


def check_08_change_scope() -> None:
    """Negative 8: the batch stays inside the files it declares."""
    changed = changed_files()
    outside = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES
        and path not in ALLOWED_UPSTREAM
        and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "08a this session changes only the files B5 declares",
        not outside and bool(changed),
        f"changed={len(changed)} outside={outside}",
    )

    upstream = sorted(
        path
        for path in changed
        if path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    )
    registry = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    unregistered = [path for path in upstream if path not in registry]
    unnamed = [symbol for symbol in UPSTREAM_SYMBOLS if symbol not in registry]
    record(
        "08b the only upstream files touched are the two the plan names",
        set(upstream) <= ALLOWED_UPSTREAM,
        f"upstream={upstream} allowed={sorted(ALLOWED_UPSTREAM)}",
    )
    record(
        "08b2 every touched upstream file and function is registered",
        not unregistered and not unnamed,
        f"unregistered={unregistered} unnamed={unnamed}",
    )

    # An upstream file carries the comments it always carried, so only the
    # lines this batch added are its business; a project file is scanned whole.
    cjk_lines: list[str] = []
    checked = 0
    for relative in sorted(changed):
        path = ROOT / relative
        if (
            not path.is_file()
            or path.suffix not in CJK_SCAN_SUFFIXES
            or relative in ALLOWED_UPSTREAM
        ):
            continue
        checked += 1
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if has_cjk(line):
                cjk_lines.append(f"{relative}:{number}")
    _, diff = git_output(
        ["diff", "-U0", *batch_revisions(), "--", *sorted(ALLOWED_UPSTREAM)]
    )
    added = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
            if has_cjk(line):
                cjk_lines.append(f"added upstream line: {line.strip()}")
    record(
        "08c no CJK characters in the code this batch changed or added",
        not cjk_lines and checked > 0,
        f"files={checked} added_upstream_lines={added} offenders={cjk_lines[:5]}",
    )

    source = (ROOT / MODULE).read_text(encoding="utf-8")
    stage_source = (ROOT / STAGE_MODULE).read_text(encoding="utf-8")
    names = taxonomy_module.load_taxonomy().names()
    named = [
        f"{relative}: {name}"
        for relative, text in ((MODULE, source), (STAGE_MODULE, stage_source))
        for name in names
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text)
    ]
    record(
        "08d neither chain module names a page type",
        not named,
        f"vocabulary={len(names)} named={named}",
    )

    pipeline_imports = [
        f"{relative}: {line}"
        for relative, text in ((MODULE, source), (STAGE_MODULE, stage_source))
        for line in text.splitlines()
        if line.startswith(("import ", "from "))
        and "babeldoc" in line
        and "babeldoc.magazine" not in line
    ]
    record(
        "08e neither chain module imports from the translation pipeline",
        not pipeline_imports,
        f"imports={pipeline_imports}",
    )

    written = [needle for needle in SEGMENT_FIELD_NAMES if needle in source]
    upstream_written = [
        f"{relative}: {needle}"
        for relative in ALLOWED_UPSTREAM
        for needle in SEGMENT_FIELD_NAMES
        if needle in (ROOT / relative).read_text(encoding="utf-8")
    ]
    record(
        "08f the sentence range is written by the stage module and nowhere else",
        not written
        and "il_version_1" not in source
        and not upstream_written
        and all(needle in stage_source for needle in ("segment_sentence",)),
        f"pure_layer={written} upstream={upstream_written}",
    )


# --- stub driven runs of the translation stage -------------------------------

# What the stub puts in front of a translation. Six characters, because the per
# paragraph path falls back when a translation is within five edits of its
# input.
MARKER = "zzzzz "

# Where the prompt template ends and the batch begins. The stub reads its work
# out of the prompt the stage built, so it exercises the real prompt path.
INPUT_HEADER = "## Here is the input:"

# Below this many tokens the stub returns the input unchanged. The per
# paragraph path falls back when the output is more than three times the input
# in tokens, and on a paragraph of a few tokens the marker alone would clear
# that; returning the input is safe there because the same-as-input fallback
# only applies above ten tokens. The point is to measure the chain machinery
# rather than the fallback machinery, which the run asserts by requiring no
# fallback at all.
STUB_TOKEN_FLOOR = 10

# Requests per second the stub run allows itself, and with it the number of
# workers the stage runs. Nothing leaves the machine, so the only thing the
# shipped default would buy here is waiting.
STUB_MAX_QPS = 16

# Where a stub run puts its working files.
STUB_WORK = _tmp_root / "stub"


_TOKENIZER = None


def tokenizer():
    """The tokenizer the stage itself uses, so the stub sees the same counts."""
    global _TOKENIZER
    if _TOKENIZER is None:
        import tiktoken

        _TOKENIZER = tiktoken.encoding_for_model("gpt-4o")
    return _TOKENIZER


def pseudo_translate(text: str) -> str:
    """A deterministic stand-in translation of one batch item."""
    if len(tokenizer().encode(text, disallowed_special=())) > STUB_TOKEN_FLOOR:
        return MARKER + text
    return text


def build_stub_translator():
    from babeldoc.translator.translator import BaseTranslator

    class StubTranslator(BaseTranslator):
        """An engine that answers the prompt without leaving the machine."""

        name = "b5-stub"

        def __init__(self):
            super().__init__("en", "zh", ignore_cache=True)
            self.calls = 0
            self.prompts: list[str] = []

        def do_translate(self, text, rate_limit_params: dict = None):
            return pseudo_translate(text)

        def do_llm_translate(self, text, rate_limit_params: dict = None):
            if text is None:
                return None
            self.calls += 1
            self.prompts.append(text)
            items = json.loads(text.split(INPUT_HEADER, 1)[1].strip())
            return json.dumps(
                [
                    {"id": item["id"], "output": pseudo_translate(item["input"])}
                    for item in items
                ],
                ensure_ascii=False,
            )

    return StubTranslator()


class StubRun:
    """One run of the translation stage over one document."""

    def __init__(self, name: str, document, config, stage, engine, calls):
        self.name = name
        self.document = document
        self.config = config
        self.stage = stage
        self.engine = engine
        self.calls = calls

    @property
    def paragraphs(self) -> dict:
        return {
            paragraph.debug_id: paragraph
            for page in self.document.page
            for paragraph in page.pdf_paragraph
            if paragraph.debug_id is not None
        }

    def xml(self) -> str:
        return XMLConverter().to_xml(self.document)

    def report(self) -> dict | None:
        path = Path(self.config.get_working_file_path("chain_translation.report.json"))
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def load_translator_class(revision: str | None):
    """The translator stage class, from the working tree or from a revision."""
    from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
        ILTranslatorLLMOnly,
    )

    if revision is None:
        return ILTranslatorLLMOnly

    import importlib.util

    # Read as bytes and decode explicitly: the file carries comments in a
    # script the console code page cannot represent, and git hands them over
    # as the UTF-8 they were written in.
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", "show", f"{revision}:{TRANSLATOR}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    source = proc.stdout.decode("utf-8")
    if proc.returncode != 0 or not source.strip():
        raise RuntimeError(f"{revision} does not carry {TRANSLATOR}")
    path = _tmp_root / f"translator_{revision.replace('.', '_').replace('-', '_')}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"baseline_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ILTranslatorLLMOnly


def run_stub(
    checkpoint: Path,
    label: str,
    chain_translate: bool,
    revision: str | None = None,
    prepare=None,
) -> StubRun:
    """Run the translation stage over one checkpoint with the stub engine.

    Every call to the per paragraph writer is counted, keyed by the paragraph
    it wrote, which is what lets the assertions say that each paragraph was
    translated exactly once however it got there.
    """
    import threading

    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator
    from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.progress_monitor import ProgressMonitor
    from babeldoc.translator.translator import set_translate_rate_limiter

    # The engine is local, so the rate limiter is pure waiting; lifting it and
    # the worker count is what keeps the gate quick, and it puts real
    # concurrency behind the assertions rather than a single worker.
    set_translate_rate_limiter(STUB_MAX_QPS)
    stage_class = load_translator_class(revision)
    document = read_checkpoint(checkpoint)
    monitor = ProgressMonitor([(stage_class.stage_name, 1.0)])
    monitor.disable = True
    work = STUB_WORK / label
    work.mkdir(parents=True, exist_ok=True)
    config = TranslationConfig(
        translator=build_stub_translator(),
        input_file=str(checkpoint),
        lang_in="en",
        lang_out="zh",
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        working_dir=work,
        output_dir=work / "out",
        progress_monitor=monitor,
        auto_extract_glossary=False,
        qps=STUB_MAX_QPS,
        magazine_chain_translate=chain_translate,
    )
    stage = stage_class(config.translator, config)
    if prepare is not None:
        prepare(stage)

    calls: list[str] = []
    lock = threading.Lock()
    original = ILTranslator.post_translate_paragraph

    def counted(self, paragraph, tracker, translate_input, translated_text):
        with lock:
            calls.append(paragraph.debug_id)
        return original(self, paragraph, tracker, translate_input, translated_text)

    ILTranslator.post_translate_paragraph = counted
    try:
        stage.translate(document)
    finally:
        ILTranslator.post_translate_paragraph = original
    return StubRun(label, document, config, stage, config.translator, calls)


def chained_checkpoints() -> list[tuple[str, Path]]:
    """The chain builder checkpoint of every sample, built once by the cache."""
    from babeldoc.magazine.checkpoint import checkpoint_stem

    found: list[tuple[str, Path]] = []
    for pdf in sample_pdfs():
        built = artifacts.get_artifacts(pdf, "chained")
        checkpoint = built.working_dir / f"{checkpoint_stem('chain_builder')}.xml"
        if checkpoint.exists():
            found.append((pdf.stem, checkpoint))
    return found


_stub_runs: dict[str, dict[str, StubRun]] = {}


def stub_runs() -> dict[str, dict[str, StubRun]]:
    """One switched-off run, one switched-on run and one baseline, per sample."""
    if _stub_runs:
        return _stub_runs
    for name, checkpoint in chained_checkpoints():
        _stub_runs[name] = {
            "off": run_stub(checkpoint, f"{name}.off", False),
            "on": run_stub(checkpoint, f"{name}.on", True),
            "baseline": run_stub(
                checkpoint, f"{name}.baseline", False, revision=BASELINE_TAG
            ),
        }
    return _stub_runs


def chain_members(run: StubRun) -> dict[str, list]:
    """The members of every chain in one document, in chain order."""
    chains: dict[str, list] = {}
    for page in run.document.page:
        for paragraph in page.pdf_paragraph:
            if paragraph.chain_id:
                chains.setdefault(paragraph.chain_id, []).append(paragraph)
    for members in chains.values():
        members.sort(key=lambda p: p.chain_index if p.chain_index is not None else 0)
    return chains


# --- 10 the law over the stub driven corpus ----------------------------------


def check_10_stub_corpus() -> None:
    """Positive 10: the stage holds the conservation law over the whole corpus."""
    runs = stub_runs()
    joins: list[str] = []
    counts: list[str] = []
    spans: list[str] = []
    skips: list[str] = []
    once: list[str] = []
    chains_seen = 0
    members_seen = 0
    table: list[dict] = []

    for name, variants in runs.items():
        run = variants["on"]
        report = run.report()
        if report is None:
            counts.append(f"{name}: no report written")
            continue
        paragraphs = run.paragraphs
        found = len(chain_members(run))
        if report["counts"]["chains"] != found:
            counts.append(
                f"{name}: report counts {report['counts']['chains']} chains, the "
                f"document carries {found}"
            )
        if (
            report["counts"]["chains"]
            != report["counts"]["merged"] + report["counts"]["escalated"]
        ):
            counts.append(f"{name}: {report['counts']} does not add up")

        for entry in report["chains"]:
            chains_seen += 1
            members = entry["members"]
            members_seen += len(members)
            pieces = [paragraphs[member["debug_id"]].unicode for member in members]
            if "".join(pieces) != entry["translation"]:
                joins.append(f"{name}/{entry['chain_id']}: pieces do not join back")
            cursor = 0
            for member, piece in zip(members, pieces, strict=True):
                segment = member["segment"]
                if segment["start"] != cursor or segment["end"] <= segment["start"]:
                    spans.append(
                        f"{name}/{entry['chain_id']}: span {segment['start']}.."
                        f"{segment['end']} at {cursor}"
                    )
                if entry["translation"][segment["start"] : segment["end"]] != piece:
                    spans.append(
                        f"{name}/{entry['chain_id']}: member {member['chain_index']} "
                        f"is not the text at its own span"
                    )
                cursor = segment["end"]
            if cursor != len(entry["translation"]):
                spans.append(
                    f"{name}/{entry['chain_id']}: spans stop at {cursor} of "
                    f"{len(entry['translation'])}"
                )

            sentence_cursor = 0
            marked = {
                member["segment"]["sentence_start"] == backfill.NO_SENTENCE_INDEX
                for member in members
            }
            if len(marked) != 1:
                spans.append(f"{name}/{entry['chain_id']}: only some members marked")
            elif not marked.pop():
                for member in members:
                    segment = member["segment"]
                    if segment["sentence_start"] != sentence_cursor:
                        spans.append(
                            f"{name}/{entry['chain_id']}: sentence range starts at "
                            f"{segment['sentence_start']}, not {sentence_cursor}"
                        )
                    sentence_cursor = segment["sentence_end"]
                if sentence_cursor != entry["redistribution"]["sentence_count"]:
                    spans.append(
                        f"{name}/{entry['chain_id']}: sentence ranges stop at "
                        f"{sentence_cursor}"
                    )
            table.append(
                {
                    "sample": name,
                    "chain_id": entry["chain_id"],
                    "pair_class": entry["pair_class"],
                    "strategy": entry["strategy"],
                    "fallback": entry["redistribution"]["fallback"],
                    "sentences": entry["redistribution"]["sentence_count"],
                    "members": [
                        {
                            "debug_id": member["debug_id"],
                            "chain_index": member["chain_index"],
                            "page_index": member["page_index"],
                            "layout_label": member["layout_label"],
                            "source_chars": member["source_chars"],
                            "span": [
                                member["segment"]["start"],
                                member["segment"]["end"],
                            ],
                            "sentences": [
                                member["segment"]["sentence_start"],
                                member["segment"]["sentence_end"],
                            ],
                            "text": paragraphs[member["debug_id"]].unicode,
                        }
                        for member in members
                    ],
                }
            )

        claimed = {
            member["debug_id"]
            for entry in report["chains"]
            for member in entry["members"]
        }
        recorded = {record_["debug_id"] for record_ in report["skips"]}
        if claimed != recorded:
            skips.append(
                f"{name}: {sorted(claimed - recorded)} unrecorded, "
                f"{sorted(recorded - claimed)} recorded without a chain"
            )
        undeclined = [
            record_["debug_id"]
            for record_ in report["skips"]
            if not record_["declined_by"]
        ]
        if undeclined:
            skips.append(f"{name}: nothing asked for {undeclined}")

        for label, variant in variants.items():
            repeated = sorted(
                {
                    debug_id
                    for debug_id in variant.calls
                    if variant.calls.count(debug_id) > 1
                }
            )
            if repeated:
                once.append(f"{name}/{label}: {repeated[:3]} written more than once")
            if variant.stage.fallback_count:
                once.append(
                    f"{name}/{label}: {variant.stage.fallback_count} paragraph(s) "
                    f"fell back, which the stub is built not to provoke"
                )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "chain_translation.stub.json").write_text(
        json.dumps(table, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    record(
        "10a every chain is either merged or escalated, and the counts add up",
        not counts and chains_seen > 0,
        f"samples={len(runs)} chains={chains_seen} problems={counts[:3]}",
    )
    record(
        "10b the members of a chain join back to exactly its translation",
        not joins and members_seen > 0,
        f"chains={chains_seen} members={members_seen} problems={joins[:3]}",
    )
    record(
        "10c the member spans tile the translation and the sentence ranges partition",
        not spans,
        f"problems={spans[:3]}",
    )
    record(
        "10d one skip record per member, each with a mechanism that asked for it",
        not skips,
        f"problems={skips[:3]}",
    )
    record(
        "10e every paragraph is written exactly once, in every variant",
        not once,
        f"problems={once[:3]}",
    )


# --- 11 the switch down -------------------------------------------------------


def check_11_switch_off() -> None:
    """Negative 11: with the switch down this is batch-b5.1's translator."""
    from babeldoc.format.pdf.translation_config import TranslationConfig

    signature = __import__("inspect").signature(TranslationConfig.__init__)
    parameter = signature.parameters.get("magazine_chain_translate")
    record(
        "11a the chain translation switch exists and defaults to False",
        parameter is not None and parameter.default is False,
        f"default={parameter.default if parameter else 'absent'}",
    )

    runs = stub_runs()
    differing = [
        name
        for name, variants in runs.items()
        if variants["off"].xml() != variants["baseline"].xml()
    ]
    record(
        "11b with the switch down the document matches batch-b5.1 byte for byte",
        not differing and bool(runs),
        f"samples={len(runs)} differing={differing}",
    )

    wrote = [
        name for name, variants in runs.items() if variants["off"].report() is not None
    ]
    fields = [
        f"{name}: {paragraph.debug_id}"
        for name, variants in runs.items()
        for paragraph in variants["off"].paragraphs.values()
        if paragraph.segment_sentence_start is not None
        or paragraph.segment_sentence_end is not None
    ]
    record(
        "11c with the switch down nothing is written and no sidecar appears",
        not wrote and not fields,
        f"reports={wrote} fields={fields[:3]}",
    )


# --- 12 the switch up ---------------------------------------------------------


def check_12_switch_on() -> None:
    """Positive 12: under the stub the chain mechanism reaches its members only.

    Assertion 12a states that a paragraph outside a chain comes out exactly as
    it does with the switch down. That is a property of this stub rather than of
    the pass: the stub's answer is a pure function of the item's own input, so
    recomposing the batch around a paragraph cannot change what comes back for
    it. Under a real engine it does not hold. The batch-b5.3 smoke measured it
    on Courier -- 15 of 123 paragraphs changed between the two modes, 4 chain
    members and 11 neighbours, all on the three pages whose batches were
    recomposed -- and could not separate that drift from the engine's own
    repeat noise, gpt-4o at temperature 0 having returned three different
    answers to one re-sent prompt.

    So what 12a pins down is the enforcement point, not the output: exactly the
    claimed members are withheld, nothing else is withheld with them, and the
    per paragraph path is otherwise entered as it was. The consequence a
    recomposed batch has on a real engine's wording is a measurement, reported
    in examples/output/b5_smoke/smoke.report.md, and is not asserted here.
    """
    runs = stub_runs()
    spilled: list[str] = []
    moved: list[str] = []
    rewritten: list[str] = []
    fields: list[str] = []
    strategies: dict[str, str] = {}
    compared = 0
    claimed_total = 0
    for name, variants in runs.items():
        off = variants["off"].paragraphs
        on = variants["on"].paragraphs
        # Every claimed member, against the piece of its chain's translation
        # the backfill cut for it. Read out of the sidecar rather than out of
        # the paragraph, so the two have to agree.
        claimed = {
            member["debug_id"]: entry["translation"][
                member["segment"]["start"] : member["segment"]["end"]
            ]
            for entry in (variants["on"].report() or {}).get("chains", ())
            for member in entry["members"]
        }
        # Not every sample carries a chain; the detector is reluctant by
        # design. The corpus as a whole has to carry one, which the count
        # below asserts.
        claimed_total += len(claimed)
        for debug_id, paragraph in on.items():
            before = off.get(debug_id)
            if before is None:
                spilled.append(f"{name}: {debug_id} appeared out of nowhere")
                continue
            if debug_id in claimed:
                if paragraph.unicode != claimed[debug_id]:
                    moved.append(
                        f"{name}: {debug_id} does not carry the piece its chain "
                        f"was cut into"
                    )
                if paragraph.unicode != before.unicode:
                    rewritten.append(debug_id)
                if (
                    paragraph.segment_sentence_start is None
                    or paragraph.segment_sentence_end is None
                ):
                    fields.append(f"{name}: {debug_id} carries no sentence range")
                continue
            compared += 1
            if paragraph.unicode != before.unicode:
                spilled.append(f"{name}: {debug_id} changed without being claimed")
            if (
                paragraph.segment_sentence_start is not None
                or paragraph.segment_sentence_end is not None
            ):
                fields.append(f"{name}: {debug_id} carries a range it never earned")
        for entry in (variants["on"].report() or {}).get("chains", ()):
            strategies[entry["pair_class"] or "unclassed"] = entry["strategy"]

        if len(off) != len(on) or len(variants["on"].document.page) != len(
            variants["off"].document.page
        ):
            spilled.append(f"{name}: the paragraph or page count moved")

    record(
        "12a a paragraph outside a chain is translated exactly as with the switch down",
        not spilled and compared > 0,
        f"compared={compared} problems={spilled[:3]}",
    )
    record(
        "12b every claimed member carries the piece its chain was cut into",
        not moved and bool(rewritten) and claimed_total > 0,
        f"claimed={claimed_total} rewritten={len(rewritten)} problems={moved[:3]}",
    )
    record(
        "12c the sentence range is written for claimed members and for nobody else",
        not fields,
        f"problems={fields[:3]}",
    )
    expected = {
        pair_class: backfill.strategy_for_pair_class(pair_class, config())
        for pair_class in strategies
    }
    record(
        "12d each chain is cut by the strategy its pair class declares",
        bool(strategies) and strategies == expected,
        f"observed={strategies} declared={expected}",
    )


# --- 13 the escape hatch ------------------------------------------------------


def check_13_escalation() -> None:
    """Negative 13: a chain the pass cannot see through goes back, and says so."""
    from babeldoc.magazine import chain_translation

    checkpoints = [
        (name, path)
        for name, path in chained_checkpoints()
        if any(
            paragraph.chain_id
            for page in read_checkpoint(path).page
            for paragraph in page.pdf_paragraph
        )
    ]
    if not checkpoints:
        record("13 a chain that cannot be merged goes back to the old path", False, "")
        return
    name, checkpoint = checkpoints[0]

    def bearing(stage) -> None:
        """Make the first member of every chain carry a placeholder.

        Only on the first preparation of a paragraph, which is the chain pass:
        the escalated member is prepared a second time by the per paragraph
        path, and that preparation has to be the untouched one.
        """
        translator = stage.il_translator
        original = translator.pre_translate_paragraph
        seen: set[int] = set()

        def patched(paragraph, tracker, page_font_map, xobj_font_map):
            text, translate_input = original(
                paragraph, tracker, page_font_map, xobj_font_map
            )
            first = id(paragraph) not in seen
            seen.add(id(paragraph))
            if (
                first
                and translate_input is not None
                and getattr(paragraph, "chain_index", None) == 0
            ):
                translate_input.placeholders = [object()]
            return text, translate_input

        translator.pre_translate_paragraph = patched

    refusing_calls = {"count": 0}

    def refusing(stage) -> None:  # noqa: ARG001 - the hook takes the stage
        """Make every redistribution fail the conservation law."""

        def patched(*args, **kwargs):  # noqa: ARG001 - it refuses whatever it is asked
            """Stand in for ``redistribute``, whatever its signature has become.

            It was written out in full and broke the day b10.4 gave the real
            function two more keyword arguments: a stub that mirrors a
            signature is a second declaration of it, and the two drift. What
            this one asserts is that a redistribution which raises is escalated
            and never written, and that is true of every call, so it takes
            every call.
            """
            refusing_calls["count"] += 1
            raise backfill.ChainBackfillError("injected conservation failure")

        chain_translation.backfill.redistribute = patched

    def starved(stage) -> None:  # noqa: ARG001 - the hook takes the stage
        """Shrink the output budget until no chain fits inside it.

        Nothing else is touched, so the chain is one an engine could translate
        and the pass declines to send only because the answer would come back
        cut off. The corpus carries no chain that reaches the shipped budget,
        which is why the budget rather than the chain is what moves here.
        """
        original = chain_translation.backfill.load_backfill_config

        def patched(path: str | None = None) -> backfill.BackfillConfig:
            return replace(original(path), output_token_budget=1)

        chain_translation.backfill.load_backfill_config = patched

    # What the switch-down run made of the same document. An escalated member
    # has to carry exactly this: a chain that is handed back is translated by
    # the per paragraph path, not written a truncated piece of a chain answer.
    switched_off = stub_runs().get(name, {}).get("off")
    off_texts = (
        {debug_id: paragraph.unicode for debug_id, paragraph in switched_off.paragraphs.items()}
        if switched_off is not None
        else {}
    )

    outcomes: dict[str, dict] = {}
    for label, prepare, reason in (
        ("placeholder", bearing, chain_translation.ESCALATION_PLACEHOLDER),
        ("conservation", refusing, chain_translation.ESCALATION_CONSERVATION),
        ("token_budget", starved, chain_translation.ESCALATION_TOKEN_BUDGET),
    ):
        original_redistribute = chain_translation.backfill.redistribute
        original_loader = chain_translation.backfill.load_backfill_config
        try:
            run = run_stub(checkpoint, f"{name}.{label}", True, prepare=prepare)
        finally:
            chain_translation.backfill.redistribute = original_redistribute
            chain_translation.backfill.load_backfill_config = original_loader
        report = run.report() or {}
        reasons = {entry["reason"] for entry in report.get("escalated", ())}
        repeated = sorted(
            {debug_id for debug_id in run.calls if run.calls.count(debug_id) > 1}
        )
        fields = [
            paragraph.debug_id
            for paragraph in run.paragraphs.values()
            if paragraph.segment_sentence_start is not None
        ]
        members = {
            member["debug_id"]
            for entry in report.get("escalated", ())
            for member in entry["members"]
        }
        translated = [
            debug_id for debug_id in members if debug_id not in set(run.calls)
        ]
        written = run.paragraphs
        diverged = sorted(
            debug_id
            for debug_id in members
            if debug_id in off_texts
            and written[debug_id].unicode != off_texts[debug_id]
        )
        outcomes[label] = {
            "counts": report.get("counts"),
            "reasons": sorted(reasons),
            "expected": reason,
            "repeated": repeated,
            "fields": fields,
            "untranslated": sorted(translated),
            "diverged": diverged,
        }

    broken = [
        f"{label}: {outcome}"
        for label, outcome in outcomes.items()
        if outcome["reasons"] != [outcome["expected"]]
        or outcome["counts"]["merged"] != 0
        or outcome["counts"]["escalated"] != outcome["counts"]["chains"]
        or outcome["repeated"]
        or outcome["fields"]
        or outcome["untranslated"]
        or outcome["diverged"]
    ]
    record(
        "13a an unmergeable chain is escalated by reason and left to the old path",
        not broken and refusing_calls["count"] > 0 and bool(off_texts),
        f"outcomes={ascii_only(json.dumps(outcomes))[:400]}",
    )

    # The oversized case specifically: the chain is handed back whole, and its
    # members carry the per paragraph translation rather than a piece cut out
    # of an answer the engine would have truncated.
    budget = outcomes[chain_translation.ESCALATION_TOKEN_BUDGET]
    record(
        "13b a chain too large to answer in one piece is exempted, not truncated",
        budget["reasons"] == [chain_translation.ESCALATION_TOKEN_BUDGET]
        and budget["counts"]["merged"] == 0
        and budget["counts"]["escalated"] > 0
        and not budget["diverged"]
        and not budget["untranslated"]
        and not budget["fields"],
        f"outcome={ascii_only(json.dumps(budget))[:300]}",
    )


# --- 14 the enforcement point -------------------------------------------------


def check_14_single_enforcement() -> None:
    """Negative 14: the claim is the only thing that hides a member."""
    source = (ROOT / TRANSLATOR).read_text(encoding="utf-8")
    stage_source = (ROOT / STAGE_MODULE).read_text(encoding="utf-8")

    # Every mechanism that could take a paragraph asks the claim, and the two
    # pairings ask after they have chosen their endpoints, never before.
    asks = {
        "process_cross_page_paragraph": "declines_cross_page",
        "process_cross_column_paragraph": "declines_cross_column",
        "process_page": "claims_paragraph",
    }
    missing = [name for name, call in asks.items() if call not in source]
    selection = source.find("last_curr_paragraph = curr_body_paragraphs[-1]")
    decline = source.find("chain_claim.declines_cross_page")
    column_selection = source.find("p2 = body_paragraphs[idx + 1]")
    column_decline = source.find("chain_claim.declines_cross_column")
    record(
        "14a every mechanism asks the claim, and the pairings ask after selecting",
        not missing
        and 0 < selection < decline
        and 0 < column_selection < column_decline,
        f"missing={missing} cross_page={selection}<{decline} "
        f"cross_column={column_selection}<{column_decline}",
    )

    # The filter that feeds the selection is untouched, so a claimed member is
    # still what the endpoint role is decided from.
    record(
        "14b the endpoint filter knows nothing about chains",
        "chain" not in source.split("def _filter_paragraphs")[1].split("def ")[0]
        and "chain"
        not in source.split("def _should_translate_paragraph")[1].split("def ")[0],
        "",
    )

    # The stage module never reaches into the per paragraph translator, which is
    # the file this batch is forbidden to change.
    record(
        "14c the stage module leaves the per paragraph translator alone",
        "il_translator.py" not in stage_source
        and "ILTranslator(" not in stage_source
        and TRANSLATOR not in stage_source,
        "",
    )


# --- 15 the sidecar -----------------------------------------------------------


def check_15_sidecar() -> None:
    """Positive 15: the sidecar carries what the intermediate language cannot."""
    runs = stub_runs()
    missing: list[str] = []
    for name, variants in runs.items():
        report = variants["on"].report()
        if report is None:
            missing.append(f"{name}: no report")
            continue
        for key in ("counts", "chains", "escalated", "skips", "language", "applied"):
            if key not in report:
                missing.append(f"{name}: no {key}")
        if not report.get("applied"):
            missing.append(f"{name}: the plan was never applied")
    record(
        "15 the run leaves a sidecar naming every chain, escalation and skip",
        not missing and bool(runs),
        f"samples={len(runs)} problems={missing[:3]}",
    )


# --- 09 sweep ---------------------------------------------------------------


def check_09_sweep() -> None:
    """The full sweep is green."""
    name = "09 the full run_all sweep is green"
    if NESTED_SUPPRESSED:
        print(f"SKIPPED: nested run suppressed :: {name}")
        return

    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "run_all.full.log").write_text(proc.stdout, encoding="utf-8")
    failures = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith("[FAIL]")
    ]
    record(
        name,
        proc.returncode == 0 and not failures,
        f"exit={proc.returncode} failures={failures[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)

    check_01_configuration()
    check_02_merge()
    check_03_sentences()
    check_04_body()
    check_05_title()
    check_06_conservation()

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        check_07_real_chains()
        with _timer.phase("stub runs"):
            stub_runs()
        check_10_stub_corpus()
        check_11_switch_off()
        check_12_switch_on()
        check_13_escalation()
        check_15_sidecar()

    check_08_change_scope()
    check_14_single_enforcement()
    check_09_sweep()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b5")
    artifacts.print_stats("spec_check_b5")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b5: {len(_results) - len(failed)}/{len(_results)} passed")
    for name in failed:
        print(f"  FAILED: {name}")
    shutil.rmtree(_tmp_root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
