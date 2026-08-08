"""Gate script for batch B5.1 (chain backfill pure functions).

Run from the repository root:

    python spec_checks/spec_check_b5.py

Exit code 0 when every assertion in plans/PLAN_B5.md that T5.1 answers for
passes, 1 otherwise.

This session delivers the pure layer only: strings in, strings out. Nothing
here runs a translator, reads a credential or touches the translation path, so
every assertion but one is a synthetic case run directly against
``babeldoc/magazine/chain_backfill.py``. The exception is assertion 07, which
takes the chains batch-b4.2 actually found in the corpus, merges their members
and cuts a deterministic stand-in translation back up, so the conservation law
is stated over real chain shapes and not only over the cases this file thought
to write down.

The synthetic cases are the whole point of the session, so they are exhaustive
in the directions that matter: both translation directions, sentence counts
above, equal to and below the member count, a single sentence spanning three
members, and the boundary cases of the terminator model -- an ellipsis, a
sentence closed by a quotation mark, a decimal point, an initial and an
abbreviation. The last two are known limitations rather than successes, and the
assertions state the behaviour that actually occurs rather than the behaviour
one might wish for.

CJK fixtures are built from code points instead of being written out, because
assertion 08c requires every file this batch changes to be ASCII.

Tiers: assertion 07 needs the corpus artefacts and belongs to the pipeline
tier; everything else is static. Assertion 09 is the full sweep and is
suppressed when the runner is already performing one.
"""

from __future__ import annotations

import json
import logging
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

BATCH_TAG = "batch-b5.1"

PYTHON = sys.executable

MODULE = "babeldoc/magazine/chain_backfill.py"
CONFIG = "configs/chain_translation.json"
CONFIG_PATH = ROOT / CONFIG
OUTPUT_DIR = ROOT / "examples" / "output" / "b5"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = ("check_07_real_chains",)

# Paths this session may change. The upstream translation path is session two's
# business and must not appear here.
ALLOWED_PREFIXES = ("spec_checks/", "plans/")
ALLOWED_FILES = {MODULE, CONFIG}

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

# The intermediate language fields B1 declared for the sentence range. This
# session writes neither, so neither name may appear in what it ships; session
# two registers itself with the B1 consumer list when it becomes their writer.
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

    malformed = {
        "out_of_range": out_of_range,
        "unknown_rule": unknown_rule,
        "duplicate_prefix": duplicate_prefix,
        "unknown_strategy": unknown_strategy,
        "no_range": no_range,
        "no_terminators": no_terminators,
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

    # Known limitation, asserted as it behaves: an abbreviation long enough to
    # clear the floor is read as a sentence end and offers a cut position
    # mid-sentence. It cannot break the conservation law, only the prose.
    abbreviated = backfill.split_sentences("Dr. Smith arrived. He left.", profile)
    record(
        "03g an abbreviation past the floor still over-splits, as documented",
        abbreviated == ("Dr. ", "Smith arrived. ", "He left."),
        f"sentences={abbreviated}",
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
    """Negative 8: the session stays inside the pure layer."""
    changed = changed_files()
    outside = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "08a this session changes only the files T5.1 declares",
        not outside and bool(changed),
        f"changed={len(changed)} outside={outside}",
    )

    upstream = sorted(
        path
        for path in changed
        if path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    )
    record(
        "08b this session touches no upstream file",
        not upstream,
        f"upstream={upstream}",
    )

    cjk_lines: list[str] = []
    checked = 0
    for relative in sorted(changed):
        path = ROOT / relative
        if not path.is_file() or path.suffix not in CJK_SCAN_SUFFIXES:
            continue
        checked += 1
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if has_cjk(line):
                cjk_lines.append(f"{relative}:{number}")
    record(
        "08c no CJK characters in the code this session changed",
        not cjk_lines and checked > 0,
        f"files={checked} offenders={cjk_lines[:5]}",
    )

    source = (ROOT / MODULE).read_text(encoding="utf-8")
    names = taxonomy_module.load_taxonomy().names()
    named = [
        name
        for name in names
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", source)
    ]
    record(
        "08d the module names no page type",
        not named,
        f"vocabulary={len(names)} named={named}",
    )

    pipeline_imports = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
        and "babeldoc" in line
        and "babeldoc.magazine" not in line
    ]
    record(
        "08e the module imports nothing from the translation pipeline",
        not pipeline_imports,
        f"imports={pipeline_imports}",
    )

    written = [needle for needle in SEGMENT_FIELD_NAMES if needle in source]
    record(
        "08f the pure layer writes no intermediate language field",
        not written and "il_version_1" not in source,
        f"written={written}",
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

    check_08_change_scope()
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
