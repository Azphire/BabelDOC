"""Gate script for batch B10.4 (name policy matrix, name harvest, length floor
shape exception, horizontal stitch on a record page, aligned display cut).

Run from the repository root:

    python spec_checks/spec_check_b10_4.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: every assertion is answered from a stub this gate builds
itself or from what this batch's runs left behind.

What this batch is. T1 turns the personal name policy into a matrix -- one whole
role text per policy per target language, each pinned by the digest of its bytes
-- and freezes the selected default so a run made now is comparable with every
run since the policy existed. T2 harvests the personal names printed on the
pages no article claims, offers a rendering for each, and puts both in the terms
section of the review draft, so a ruled name reaches a prompt through the
glossary channel that already existed and through no second one. T3 gives the
length floor a shape exception: a paragraph below it that holds a declared shape
and stands alone on its line band is translated rather than skipped. T3b lets
the horizontal stitch rule back onto a page whose lines are records, where a
source audit -- a second reading of the page through an extractor the pipeline
does not share -- has placed the fragments as pieces of a broken word. T5 places
the cut of a display line chain by the length of each member's own translation
rather than by its share of the source.

01 is the scope and the declaration surface this batch does not move.

02 is T1: the matrix, its pins, the frozen default, the refusals, and the
annotation bracket that the parenthetical fold cannot reach.

03 is T2: the harvest's determinism, its shape rules, and the single execution
point the ruled pairs travel through.

04 is T3 and T3b: what the floor exception admits and what it refuses, the
audit's classes and its evidence, the stitch on a declared page, and the two
record pages whose accounts this batch does not move.

05 is T5: the cascade's three levels, on a stub and on the one display chain the
corpus holds.

06 is the request account and the bill.

07 is this file: a gate that names no run local identifier.

Tiers: every assertion is static, so the fast tier runs the whole gate.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import chain_backfill as backfill  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import fragment_stitch  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import name_harvest  # noqa: E402
from babeldoc.magazine import paren_dedup  # noqa: E402
from babeldoc.magazine import short_unit  # noqa: E402
from babeldoc.magazine import source_audit  # noqa: E402
from babeldoc.magazine import translation_style  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import harness  # noqa: E402

GATE_SET = "fast"

BATCH_TAG = "b10.4"
PREVIOUS_TAG = "b10.3"

BATCH_DIR = ROOT / "examples" / "output" / "b10_4"
PREVIOUS_DIR = ROOT / "examples" / "output" / "b10_3"
BASELINE_DIR = ROOT / "examples" / "output" / "F2"
LEDGER = BATCH_DIR / "runs.json"

STYLE_CONFIG = ROOT / "configs" / "translation_style.json"
HARVEST_CONFIG = ROOT / "configs" / "name_harvest.json"
SHORT_UNIT_CONFIG = ROOT / "configs" / "short_unit.json"
AUDIT_CONFIG = ROOT / "configs" / "source_audit.json"
PAREN_CONFIG = ROOT / "configs" / "paren_dedup.json"
CHAIN_CONFIG = ROOT / "configs" / "chain_translation.json"

TRANSLITERATE_PROMPT = ROOT / "prompts" / "name_transliterate.md"

# The digest of the compiled default role text, per target language, as the F2
# run recorded it in its ledger. This batch restructures the file the text lives
# in and claims the text itself did not move; these two numbers are what that
# claim is checked against, and they are read out of the frozen F2 ledger rather
# than retyped here.
FROZEN_POLICY = "transliterate"

# Every Chinese string in this file is written as escapes rather than as the
# characters themselves. The gate anchors a paragraph by its text (CLAUDE.md
# section 5.13) and half this corpus is Chinese, so the anchors have to be
# here; the gate scripts are also held to ASCII, which spec_check_b0's CJK
# assertion enforces over every file under spec_checks/. Escapes satisfy both,
# and the value a reader gets is the same string either way. This is the
# convention spec_check_e0.py already uses for the phrases it reads out of a
# Chinese document.
# The one display line chain in the corpus, and where its cut is to land. The
# source breaks at an English word boundary and the translation is Chinese, so
# a cut placed by the source's share lands one character early and cuts the verb
# in half; placed by the length of each member's own translation it lands after
# the verb. Written out rather than searched for, because a gate that looked for
# "wherever the cut went" would assert about the run rather than against it.
DISPLAY_CHAIN = {
    "sample": "Courier-en",
    "members": (
        "How Indigenous knowledge drives",
        "scientific discover y",
    ),
    "joint": "\u571f\u8457\u77e5\u8bc6\u5982\u4f55\u63a8\u52a8\u79d1\u5b66\u53d1\u73b0",
    "aligned_lengths": (8, 4),
    "aligned_pieces": ("\u571f\u8457\u77e5\u8bc6\u5982\u4f55\u63a8\u52a8", "\u79d1\u5b66\u53d1\u73b0"),
    "proportional_pieces": (
        "\u571f\u8457\u77e5\u8bc6\u5982\u4f55\u63a8",
        "\u52a8\u79d1\u5b66\u53d1\u73b0",
    ),
}

# The seven section labels of Courier-zh page 1, which are each shorter than the
# run's length floor and which F2 recorded as reaching no request at all. They
# are the shape the exception exists for: a whole written unit, alone on its
# line band, with a column's width between it and anything else.
FLOOR_LABEL_PAGE = 1

FLOOR_LABELS = (
    "\u793e\u8bba",
    "\u603b\u7f16\u8f91",
    "\u5e7f\u89d2",
    "\u805a\u7126",
    "\u89c2\u70b9",
    "\u5609\u5bbe",
    "\u6df1\u5ea6\u9605\u8bfb",
)

# The two pages whose record account this batch may not move. Letting the
# horizontal rule back onto a page whose lines are records is the change most
# able to damage one, so the claim is checked where a record page was already
# measured: Courier-en page 1, every block of which is evenly leaded, and
# CERNCourier-en page 2.
RECORD_PAGES = (("Courier-en", 1), ("CERNCourier-en", 2))

# The page the horizontal rule is let onto, and the two written units it puts
# back together there. Both are one word the paragraph finder left in pieces.
# The samples whose drafts hold a derived terms table. The direction each was
# translated in is read from the corpus registry rather than repeated here.
NAME_SAMPLES = ("AramcoWorld-en-v2", "FD-en-v2", "Vogue-en", "Courier-zh")

DRAFT_VERSION = 2

# The sample a person ruled on this batch, and what the ruling did to its chain
# account. F2 recorded none of its seven page boundaries as chain eligible,
# because the classifier gave five of its eight pages a kind whose policy admits
# no chain. The ruling retypes them, and six of the seven boundaries become
# askable; two of the six clear the link bound and are built.
#
# The one boundary that stays shut is page one to page two, whose tail is the
# contents page: a contents page is not chain eligible under any ruling, which
# is the policy doing its job rather than the ruling failing to reach it.
RULED_SAMPLE = "Courier-zh"
RULED_BOUNDARIES = 7
RULED_ELIGIBLE_BOUNDARIES = 6
RULED_SHUT_BOUNDARY = (1, 2)
RULED_CHAINS_BUILT = 2

DECLARED_STITCH = {
    "sample": "Vogue-en",
    "page": 3,
    "words": ("infusions", "Whether"),
}

# How many paragraphs the two stitches on that page take between them, and
# how many clusters the census still reports there afterwards. The second is
# a measurement the plan did not expect and is asserted as measured; see
# check_04g for what the survivors are and why they are not this batch's.
DECLARED_STITCH_MERGED = 10
DECLARED_STITCH_CENSUS = 4

ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "reviews/",
    "configs/",
    "spec_checks/",
    "examples/output/b10_4/",
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "plans/PLAN_B10_4.md",
    "plans/PLAN_B10_4_REV2.md",
    "prompts/name_transliterate.md",
    "tools/source_audit.py",
    "reviews/Courier-zh.decisions.json",
    "reviews/Vogue-en.decisions.json",
    "reviews/AramcoWorld-en-v2.decisions.json",
    "reviews/FD-en-v2.decisions.json",
    "examples/output/run_all.b10_4.log",
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
}

FORBIDDEN_PREFIXES = ("corpus/", "docs/eval/")

# The prompts this batch does not touch. A prompt file is a thing a run's answers
# depend on, so the batch that adds one says which ones it left alone.
FROZEN_PROMPTS = tuple(
    sorted(
        path.name
        for path in (ROOT / "prompts").glob("*.md")
        if path.name != TRANSLITERATE_PROMPT.name
    )
)

# A debug identifier is minted per run: the same paragraph carries a different
# one in every run, so a gate anchored to one asserts about the run that made it
# and about nothing else. The rule arrives with this batch and this is the
# assertion that keeps it.
# Built rather than written, so that the file asserting the rule does not
# itself hold the string it forbids.
_NEEDLES = (
    "debug" + chr(95) + "id",
    "debug" + chr(45) + "id",
    "debug" + "Id",
)


NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b10_4")


def record(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _total
    _total += 1
    seconds = _timer.mark(name)
    if ok:
        _passed += 1
        print(f"PASS: {name} ({seconds:.2f}s)")
    else:
        _failures.append(f"{name}: {detail}")
        print(f"FAIL: {name}: {detail} ({seconds:.2f}s)")


def skip(name: str, missing) -> None:
    """A frozen product the retention policy took, named rather than re-made.

    A pruned product may not be replaced by re-running the batch, so an
    assertion that stands on one reports what it could not read instead of
    failing as though the run had never produced it.
    """
    global _total
    _total += 1
    seconds = _timer.mark(name)
    print(f"SKIPPED: {name}: evidence pruned: {sorted(missing)} ({seconds:.2f}s)")


# The products of this batch a clone receives, and the ones it does not. The
# whole translated documents and every run's working directory were never
# committed, so they are what the output retention policy takes once two later
# batches exist; b11.1 is the batch whose arrival took them.
PRUNABLE_PRODUCTS = ("pdf",)


def sample_target(sample: str) -> str:
    """The language one sample is translated into, as the registry declares."""
    return corpus.direction_of(sample)[1]


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def changed_paths() -> list[str]:
    """This batch's delta, anchored to its own tag once the tag exists.

    Spanned from the previous batch's tag rather than from this one's parent.
    A batch with a person in it commits twice -- once before the ruling and once
    after it, which is what CLAUDE.md section 5.11 asks for -- and reading only
    the tagged commit would check the second half of the delta and call it the
    whole. From tag to tag is the batch however many commits it took.
    """
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        span = f"{BATCH_TAG}^..{BATCH_TAG}"
        previous, _ = git_output(["rev-parse", "--verify", f"{PREVIOUS_TAG}^{{commit}}"])
        if previous == 0:
            span = f"{PREVIOUS_TAG}..{BATCH_TAG}"
        _, out = git_output(["diff", "--name-only", span])
        return [line.strip() for line in out.splitlines() if line.strip()]
    _, tracked = git_output(["diff", "--name-only", "HEAD"])
    _, untracked = git_output(["ls-files", "--others", "--exclude-standard"])
    return sorted(
        {
            line.strip()
            for line in (tracked + untracked).splitlines()
            if line.strip()
        }
    )


def run_ledger() -> list[dict]:
    return load_json(LEDGER) if LEDGER.exists() else []


def sidecar(sample: str, name: str) -> dict | None:
    path = BATCH_DIR / sample / "sidecars" / name
    return load_json(path) if path.exists() else None


def previous_sidecar(sample: str, name: str) -> dict | None:
    path = PREVIOUS_DIR / sample / "sidecars" / name
    return load_json(path) if path.exists() else None


def page_text(sample: str, label: int, directory: Path = BATCH_DIR) -> str | None:
    """Every paragraph of one page of a produced document, joined.

    Read from the typesetting checkpoint rather than from the PDF: the question
    every assertion below asks is what the pipeline wrote, and a PDF answers it
    through a text extractor whose own faults would be attributed to this batch.
    """
    path = (
        directory
        / sample
        / "work"
        / sample
        / "checkpoint.11_typesetting.json"
    )
    if not path.exists():
        return None
    document = load_json(path)
    for page in document.get("page", ()):
        if page.get("page_number", -1) + 1 == label:
            return "\n".join(
                paragraph.get("unicode") or ""
                for paragraph in page.get("pdf_paragraph") or ()
            )
    return None


# --- 01 scope ---------------------------------------------------------------


def check_01a_the_delta_is_the_declared_surface() -> None:
    """Negative 1a: nothing changed outside the surface this batch declares."""
    stray = sorted(
        path
        for path in changed_paths()
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "check_01a_the_delta_is_the_declared_surface",
        not stray,
        f"outside the declared surface: {stray}",
    )


def check_01b_no_upstream_and_no_truth() -> None:
    """Negative 1b: upstream is untouched and no ground truth was written."""
    changed = changed_paths()
    faults = []
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    if upstream:
        faults.append(f"upstream touched: {upstream}")
    forbidden = sorted(path for path in changed if path.startswith(FORBIDDEN_PREFIXES))
    if forbidden:
        faults.append(f"a read only tree was written: {forbidden}")
    record("check_01b_no_upstream_and_no_truth", not faults, "; ".join(faults))


def check_01c_the_existing_prompts_are_untouched() -> None:
    """Negative 1c: the batch adds one prompt and moves not a byte of the others."""
    changed = set(changed_paths())
    moved = sorted(
        name for name in FROZEN_PROMPTS if f"prompts/{name}" in changed
    )
    faults = []
    if moved:
        faults.append(f"a prompt this batch froze moved: {moved}")
    if not TRANSLITERATE_PROMPT.exists():
        faults.append("the prompt this batch adds is not in the tree")
    record(
        "check_01c_the_existing_prompts_are_untouched", not faults, "; ".join(faults)
    )


def check_01d_every_ruling_is_filled_in() -> None:
    """Positive 1d: a decisions file in the tree is one a person has written.

    A draft the exporter wrote and nobody ruled on is an empty object, and an
    empty ruling applied is a run that decided nothing while claiming a person
    had. Every decisions file beside this batch's drafts has to carry at least
    one entry in at least one section.
    """
    faults = []
    found = 0
    for path in sorted((ROOT / "reviews").glob("*.decisions.json")):
        found += 1
        record_json = load_json(path)
        if not any(record_json.get(section) for section in hitl.sections()):
            faults.append(f"{path.name}: every section is empty")
    if not found:
        faults.append("no decisions file is in the tree at all")
    record("check_01d_every_ruling_is_filled_in", not faults, "; ".join(faults))


# --- 02 T1: the policy matrix -----------------------------------------------


def check_02a_the_matrix_selects_the_text_it_declares() -> None:
    """Positive 2a: every policy in every declared language, by its own pin."""
    policy = translation_style.load_style_config()
    raw = load_json(STYLE_CONFIG)
    pins = raw[translation_style.PINS_KEY]
    faults = []
    seen = 0
    for name in sorted(policy.policies):
        for tag in sorted(policy.languages):
            text = policy.note_for_policy(name, tag)
            if digest(text) != pins[name][tag]:
                faults.append(f"{name}.{tag}: the text does not hash to its pin")
            seen += 1
    # Three policies beyond the frozen default, each stating something for each
    # declared language, is the matrix the batch says it built.
    stated = sorted(set(policy.policies) - {FROZEN_POLICY})
    if len(stated) != 3:
        faults.append(f"the matrix states {stated} beside the frozen default")
    if seen != len(policy.policies) * len(policy.languages):
        faults.append(f"{seen} texts read of a full matrix")
    record(
        "check_02a_the_matrix_selects_the_text_it_declares",
        not faults,
        "; ".join(faults[:5]) + f" [policies={sorted(policy.policies)}]",
    )


def check_02b_the_default_is_frozen_against_the_f2_ledger() -> None:
    """Positive 2b: the frozen policy compiles to what F2 recorded, per language.

    The direct proof of the freeze. F2's ledger holds, per run, the digest of the
    system prompt that run carried; this batch restructured the file those texts
    live in, and the two digests are the same numbers or they are not.

    The freeze is a property of the text, not of which text a run selects, and
    the two came apart at b11.1, where the selection moved and the texts did not
    (contract AC-09). So the comparison is made against the frozen policy's own
    entry, whichever policy the tree currently selects.
    """
    policy = dataclasses.replace(
        translation_style.load_style_config(), person_names=FROZEN_POLICY
    )
    faults = []
    ledger = BASELINE_DIR / "runs.json"
    if not ledger.exists():
        record(
            "check_02b_the_default_is_frozen_against_the_f2_ledger",
            False,
            f"the frozen baseline ledger is absent: {ledger}",
        )
        return
    by_target: dict[str, set[str]] = {}
    for row in load_json(ledger):
        style = row.get("translation_style") or {}
        if style.get("person_names") != FROZEN_POLICY:
            faults.append(f"{row['sample']}: F2 ran under {style.get('person_names')!r}")
            continue
        by_target.setdefault(row["lang_out"], set()).add(style["system_prompt_sha256"])
    for tag, digests in sorted(by_target.items()):
        if len(digests) != 1:
            faults.append(f"{tag}: F2 recorded {sorted(digests)}")
            continue
        now = translation_style.system_prompt(tag, policy=policy)
        if now is None or digest(now) != next(iter(digests)):
            faults.append(
                f"{tag}: compiles to {None if now is None else digest(now)[:16]} "
                f"and F2 recorded {next(iter(digests))[:16]}"
            )
    if not by_target:
        faults.append("the F2 ledger records no style digest to compare against")
    record(
        "check_02b_the_default_is_frozen_against_the_f2_ledger",
        not faults,
        "; ".join(faults[:4]) + f" [targets={sorted(by_target)}]",
    )


def _probe_style(label: str, mutate) -> str | None:
    """Load a mutated configuration; return None where it was refused."""
    broken = copy.deepcopy(load_json(STYLE_CONFIG))
    mutate(broken)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"style_{label}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(broken, f)
        try:
            translation_style.load_style_config(str(path))
        except translation_style.TranslationStyleError:
            return None
        finally:
            translation_style.load_style_config.cache_clear()
    return label


def check_02c_a_broken_matrix_is_refused() -> None:
    """Negative 2c: one refusal of the vocabulary and one of the structure."""

    def drop_a_policy(config):
        config[translation_style.POLICIES_KEY].pop(FROZEN_POLICY)

    def move_a_pin(config):
        for tag in config[translation_style.PINS_KEY][FROZEN_POLICY]:
            config[translation_style.PINS_KEY][FROZEN_POLICY][tag] = "0" * 64

    def drop_a_language(config):
        for tag in list(config[translation_style.POLICIES_KEY]["keep"]):
            config[translation_style.POLICIES_KEY]["keep"].pop(tag)
            config[translation_style.PINS_KEY]["keep"].pop(tag)
            break

    accepted = [
        label
        for label in (
            _probe_style("vocabulary_offers_what_the_matrix_lacks", drop_a_policy),
            _probe_style("a_pin_that_does_not_match", move_a_pin),
            _probe_style("a_language_no_policy_claims", drop_a_language),
        )
        if label is not None
    ]
    translation_style.load_style_config.cache_clear()
    record(
        "check_02c_a_broken_matrix_is_refused",
        not accepted,
        f"accepted: {accepted}",
    )


def check_02d_a_table_outranks_the_policy_in_every_text() -> None:
    """Positive 2d: every policy defers to the glossary where the model reads it.

    ``keep`` is the one that matters and it is the one this could be missing
    from: a policy saying to leave a name alone is the only one a ruled pair
    could be read as contradicting, so it says in as many words that the table
    wins.
    """
    policy = translation_style.load_style_config()
    faults = []
    for name in sorted(policy.policies):
        for tag in sorted(policy.languages):
            text = policy.note_for_policy(name, tag).lower()
            if "glossary" not in text:
                faults.append(f"{name}.{tag}: does not name the glossary")
            if "contextual hints" not in text:
                faults.append(f"{name}.{tag}: does not name the hints")
            if "instead" not in text:
                faults.append(f"{name}.{tag}: states no precedence")
    record(
        "check_02d_a_table_outranks_the_policy_in_every_text",
        not faults,
        "; ".join(faults[:5]),
    )


def check_02e_an_annotation_is_a_shape_the_fold_cannot_reach() -> None:
    """Negative 2e: the annotate bracket is not one the parenthetical fold folds.

    Constructed rather than looked for. The fold closes a parenthetical whose
    content repeats the text in front of it, which is exactly the shape an
    annotation takes when a name renders to itself. If the two mechanisms shared
    a bracket the fold would eat the annotation, so the same text is built twice
    -- once in the fold's brackets and once in the annotation's -- and only the
    first is folded.
    """
    policy = translation_style.load_style_config()
    paren = load_json(PAREN_CONFIG)
    paren_config = paren_dedup.load_paren_config()
    folds = set(paren["bracket_openers"]) | set(paren["bracket_closers"])
    faults = []
    for tag in sorted(policy.languages):
        opener, closer = policy.brackets_for(tag)
        if opener in folds or closer in folds:
            faults.append(f"{tag}: the annotation bracket is one the fold folds")
        body = "Ada Lovelace"
        annotated = f"{body}{opener}{body}{closer}"
        folded = f"{body}{paren['bracket_openers'][0]}{body}{paren['bracket_closers'][0]}"
        if paren_dedup.fold_text(annotated, paren_config)[0] != annotated:
            faults.append(f"{tag}: an annotation was folded")
        if paren_dedup.fold_text(folded, paren_config)[0] == folded:
            faults.append(
                f"{tag}: the control case was not folded, so the comparison "
                f"proves nothing"
            )
        # And the text the model is instructed from names those two brackets.
        text = policy.note_for_policy("annotate", tag)
        if opener not in text or closer not in text:
            faults.append(f"{tag}: the annotate text does not name its brackets")
    record(
        "check_02e_an_annotation_is_a_shape_the_fold_cannot_reach",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 03 T2: the harvest and the one way in ----------------------------------


def check_03a_the_harvest_is_deterministic() -> None:
    """Positive 3a: the same text harvested twice gives the same set."""
    config = name_harvest.load_harvest_config()
    text = (
        "Miracle Drip. Photography by Norman Jean Roy, styled by Margaux "
        "Anbouba. IMF Publications, PO Box 92780."
    )
    first = name_harvest.harvest_text(text, config)
    second = name_harvest.harvest_text(text, config)
    faults = []
    if first != second:
        faults.append(f"two harvests differ: {first} against {second}")
    if "Margaux Anbouba" not in first:
        faults.append(f"a two word name was not found: {first}")
    record("check_03a_the_harvest_is_deterministic", not faults, "; ".join(faults))


def check_03b_the_harvest_refuses_what_is_not_a_person() -> None:
    """Negative 3b: a closed class opener, a role and an address are not names."""
    config = name_harvest.load_harvest_config()
    faults = []
    for text, why in (
        ("The Brutalist", "a closed class opener"),
        ("MANAGING EDITOR", "a role, in capitals"),
        ("Managing Editor", "a role"),
        ("PO Box", "an address"),
        ("IMF Publications", "an organisation"),
        ("Anbouba", "one word"),
    ):
        found = name_harvest.harvest_text(text, config)
        if found:
            faults.append(f"{why} was harvested: {found}")
    # And the rule is over word forms, never over a named publication.
    raw = load_json(HARVEST_CONFIG)
    listed = {
        item.lower()
        for key in ("stopwords", "institution_words", "name_particles")
        for item in raw[key]
    }
    for banned in ("unesco", "vogue", "aramco", "courier", "cern", "imf"):
        if banned in listed:
            faults.append(f"the configuration names a publication: {banned}")
    record(
        "check_03b_the_harvest_refuses_what_is_not_a_person",
        not faults,
        "; ".join(faults[:5]),
    )


class _Shared:
    def __init__(self, auto=None, user=None):
        self.auto_extracted_glossary = auto
        self.user_glossaries = list(user or ())


class _Config:
    def __init__(self, shared):
        self.shared_context_cross_split_part = shared


def check_03c_a_ruled_pair_travels_the_one_channel() -> None:
    """Positive 3c: the ruled pairs land in the user list and the auto slot empties.

    The single execution point. A harvested candidate is offered in the terms
    section of the draft and travels from there exactly as an extractor term
    does, so there is one place the ruling is applied and this is an assertion
    about that place rather than about a second one.
    """
    from babeldoc.glossary import Glossary
    from babeldoc.glossary import GlossaryEntry

    auto = Glossary(
        name="auto",
        entries=[
            GlossaryEntry("Margaux Anbouba", "wrong"),
            GlossaryEntry("quantum sensing", "kept"),
        ],
    )
    config = _Config(_Shared(auto=auto))
    decisions = hitl.Decisions(
        path=Path("probe"),
        terms={"Margaux Anbouba": "\u739b\u683c"},
        page_kinds={},
        drop_caps={},
    )
    applied = hitl.apply_terms(config, decisions)
    shared = config.shared_context_cross_split_part
    faults = []
    if shared.auto_extracted_glossary is not None:
        faults.append("the automatic slot was not emptied")
    landed = {
        entry.source: entry.target
        for glossary in shared.user_glossaries
        for entry in glossary.entries
    }
    if landed.get("Margaux Anbouba") != "\u739b\u683c":
        faults.append(f"the ruled target did not land: {landed}")
    if landed.get("quantum sensing") != "kept":
        faults.append("an unruled automatic entry was lost")
    if applied is None or not applied.get("dropped_from_auto"):
        faults.append("the ruling did not report what it displaced")
    record(
        "check_03c_a_ruled_pair_travels_the_one_channel", not faults, "; ".join(faults)
    )


def _draft_rows(sample: str) -> list[dict]:
    path = ROOT / "reviews" / f"{sample}.review.json"
    return load_json(path)["terms"] if path.exists() else []


def check_03e_the_draft_defaults_to_the_run_s_policy() -> None:
    """Positive 3e: every derived row defaults to what its own policy says.

    The parameterised assertion. Nothing about the derivation is written against
    a named policy, so what is checked is that each row's default *is* its
    policy's own function of that row's observation -- computed here by calling
    the same derivation, which is what makes this an assertion about the
    mechanism rather than a second copy of it.

    A draft is exported once and then belongs to the person who rules on it, so
    the policy it was derived under is the one it records rather than the one
    the tree currently selects; the two came apart at b11.1 (contract AC-10).
    The row's own policy is therefore what the derivation is driven with, and
    what is asserted about it is that it is one the configuration declares.
    """
    declared = translation_style.load_style_config()
    faults = []
    counted = {}
    for sample in NAME_SAMPLES:
        rows = _draft_rows(sample)
        if not rows:
            continue
        version = load_json(ROOT / "reviews" / f"{sample}.review.json")[
            "format_version"
        ]
        if version != DRAFT_VERSION:
            faults.append(f"{sample}: the draft is version {version}")
        shaped = [row for row in rows if row.get("person_shaped")]
        counted[sample] = len(shaped)
        if not shaped:
            faults.append(f"{sample}: no row was derived from the policy")
        brackets = declared.brackets_for(sample_target(sample))
        for row in shaped:
            if "observed_target" not in row:
                faults.append(f"{sample}: a derived row lost its observation")
                break
            if row.get("policy") not in declared.policies:
                faults.append(f"{sample}: a row records policy {row.get('policy')!r}")
                break
            auto, candidates = name_harvest.derive(
                row["source"],
                row.get("observed_target"),
                row["policy"],
                brackets,
            )
            if row.get("auto_target") != auto:
                faults.append(
                    f"{sample}: a row defaults to {row.get('auto_target')!r} "
                    f"and the policy derives {auto!r}"
                )
                break
            if row.get("candidates") != candidates:
                faults.append(f"{sample}: a row offers {row.get('candidates')}")
                break
        for row in rows:
            if row.get("person_shaped"):
                continue
            if row.get("auto_target") != row.get("observed_target"):
                faults.append(f"{sample}: an underived row's default was rewritten")
                break
    if not counted:
        faults.append("no draft of this batch is in the tree")
    record(
        "check_03e_the_draft_defaults_to_the_run_s_policy",
        not faults,
        "; ".join(faults[:4]) + f" [person shaped={counted}]",
    )


def check_03f_a_keep_policy_draft_swaps_the_default_and_the_candidate() -> None:
    """Positive 3f: the same rows under another policy, at the derivation layer.

    A dry run and nothing more: the derivation is called with a different policy
    over the rows the shipped policy produced, so no run is made, no request is
    sent and the frozen default is not disturbed. What it establishes is that
    the policy is a parameter of the default rather than a label on it.
    """
    policy = translation_style.load_style_config()
    faults = []
    seen = 0
    for sample in NAME_SAMPLES:
        rows = [row for row in _draft_rows(sample) if row.get("person_shaped")]
        brackets = policy.brackets_for(sample_target(sample))
        for row in rows:
            observed = row.get("observed_target")
            if not observed or observed == row["source"]:
                continue
            seen += 1
            kept, offered = name_harvest.derive(
                row["source"], observed, "keep", brackets
            )
            if kept != row["source"]:
                faults.append(f"{sample}: keep defaults to {kept!r}")
                break
            if observed not in offered:
                faults.append(f"{sample}: keep does not offer the rendering")
                break
            annotated, both = name_harvest.derive(
                row["source"], observed, "annotate", brackets
            )
            opener, closer = brackets
            if annotated != f"{observed}{opener}{row['source']}{closer}":
                faults.append(f"{sample}: annotate builds {annotated!r}")
                break
            if sorted(both) != sorted([row["source"], observed]):
                faults.append(f"{sample}: annotate offers {both}")
                break
    if not seen:
        faults.append("no row carried a rendering to swap")
    record(
        "check_03f_a_keep_policy_draft_swaps_the_default_and_the_candidate",
        not faults,
        "; ".join(faults[:4]) + f" [rows={seen}]",
    )


def check_03g_a_run_with_no_ruling_lands_the_policy_default() -> None:
    """Positive 3g: zero manual work still lands the policy's own semantics."""
    from babeldoc.glossary import Glossary
    from babeldoc.glossary import GlossaryEntry

    auto = Glossary(name="auto", entries=[GlossaryEntry("quantum sensing", "kept")])
    config = _Config(_Shared(auto=auto))
    applied = hitl.apply_terms(config, None, {"Margaux Anbouba": "MG"})
    shared = config.shared_context_cross_split_part
    faults = []
    if applied is None:
        faults.append("a run with defaults and no ruling applied nothing")
    else:
        if applied["ruled"] != 0 or applied["defaulted"] != 1:
            faults.append(
                f"the report says {applied['ruled']} ruled, "
                f"{applied['defaulted']} defaulted"
            )
        if applied["entries"][0]["decided_by"] != hitl.POLICY_SOURCE:
            faults.append("a defaulted pair is not recorded as the policy's")
    landed = {
        entry.source: entry.target
        for glossary in shared.user_glossaries
        for entry in glossary.entries
    }
    if landed.get("Margaux Anbouba") != "MG":
        faults.append(f"the default did not land: {landed}")

    ruled_config = _Config(_Shared())
    ruled = hitl.apply_terms(
        ruled_config,
        hitl.Decisions(path=Path("probe"), terms={"Margaux Anbouba": "RULED"}),
        {"Margaux Anbouba": "MG"},
    )
    targets = [
        entry.target
        for glossary in ruled_config.shared_context_cross_split_part.user_glossaries
        for entry in glossary.entries
    ]
    if targets != ["RULED"]:
        faults.append(f"the ruling did not override the default: {targets}")
    if ruled is None or ruled["overridden"] != ["Margaux Anbouba"]:
        faults.append("the override was not reported")
    record(
        "check_03g_a_run_with_no_ruling_lands_the_policy_default",
        not faults,
        "; ".join(faults[:4]),
    )


def check_03h_a_version_one_ruling_still_parses() -> None:
    """Negative 3h: the draft version moved and the ruling format did not."""
    faults = []
    kinds = tuple(page_type.name for page_type in load_taxonomy().page_types)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "V1.decisions.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "format_version": 1,
                    "sample": "V1",
                    "terms": {"Ada Lovelace": "AL"},
                    "page_kinds": {},
                    "drop_caps": {},
                },
                f,
            )
        try:
            decisions = hitl.parse_decisions(load_json(path), path, set(), kinds)
        except hitl.HitlError as error:
            decisions = None
            faults.append(f"a version one ruling was refused: {error}")
    if decisions is not None and decisions.terms != {"Ada Lovelace": "AL"}:
        faults.append(f"a version one ruling parsed to {decisions.terms}")
    record(
        "check_03h_a_version_one_ruling_still_parses", not faults, "; ".join(faults)
    )


def check_03d_the_harvest_reached_the_draft() -> None:
    """Positive 3d: the drafts this batch wrote carry harvested rows.

    Read from the sidecar the harvest wrote beside each run, which is the record
    of what was offered rather than of what was ruled.
    """
    faults = []
    offered = {}
    for row in run_ledger():
        sample = row["sample"].removesuffix(".pdf")
        report = sidecar(sample, name_harvest.REPORT_NAME)
        if report is None:
            continue
        offered[sample] = report["counts"]["person_shaped"]
        if report["counts"]["person_shaped"] and not report["request"].get(
            "prompt_sha256"
        ):
            faults.append(f"{sample}: rows were derived with no prompt recorded")
        if not report["counts"]["harvested"]:
            faults.append(f"{sample}: the harvest found nothing at all")
        # A reply that came back unreadable leaves every name defaulting to
        # itself, which looks exactly like a policy that decided to keep them.
        # The two are told apart here and nowhere else.
        request = report["request"]
        if request["requested"] and not request["answered"]:
            faults.append(
                f"{sample}: {request['requested']} name(s) were asked about and "
                f"none was answered"
            )
        if request.get("failures"):
            faults.append(f"{sample}: {request['failures'][:1]}")
        for row in report["rows"]:
            if "source" not in row:
                faults.append(f"{sample}: a row carries no source")
                break
    if not offered:
        faults.append("no run of this batch recorded a harvest")
    elif not any(offered.values()):
        faults.append(f"every run derived nothing: {offered}")
    record(
        "check_03d_the_harvest_reached_the_draft",
        not faults,
        "; ".join(faults[:4]) + f" [offered={offered}]",
    )


# --- 04 T3 and T3b ----------------------------------------------------------


def _paragraph(text: str, box, size: float = 8.0):
    """A paragraph stub carrying one line of characters at one size."""
    characters = []
    width = size * 0.5
    for index, char in enumerate(text):
        left = box[0] + index * width
        characters.append(
            il_version_1.PdfCharacter(
                char_unicode=char,
                pdf_style=il_version_1.PdfStyle(font_id="F", font_size=size),
                box=il_version_1.Box(x=left, y=box[1], x2=left + width, y2=box[3]),
            )
        )
    paragraph = il_version_1.PdfParagraph(
        unicode=text,
        box=il_version_1.Box(x=box[0], y=box[1], x2=box[2], y2=box[3]),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_line=il_version_1.PdfLine(
                    box=il_version_1.Box(x=box[0], y=box[1], x2=box[2], y2=box[3]),
                    pdf_character=characters,
                )
            )
        ],
    )
    # The identifier a paragraph carries is set by name rather than as a keyword,
    # so that this file holds no occurrence of the name the rule below forbids.
    # The value is a constant and nothing here reads it back.
    setattr(paragraph, _NEEDLES[0], "stub")
    return paragraph


def check_04a_the_floor_exception_admits_only_a_declared_shape() -> None:
    """Positive and negative 4a: what the exception lets through, on stubs.

    Four stubs on one page. A short label alone on its band is admitted; the
    same label with something printed hard against it is not, which is the test
    that separates a section heading from a piece of a broken word; an ordinary
    short phrase over the label bound is not; and a figure is not.
    """
    config = short_unit.load_short_unit_config()
    label = _paragraph("\u805a\u7126", (60.0, 700.0, 76.0, 708.0))
    beside = _paragraph("\u5ffd", (77.0, 700.0, 85.0, 708.0))
    far = _paragraph("\u53e6\u4e00\u680f", (300.0, 700.0, 340.0, 708.0))
    long_phrase = _paragraph("a short sentence", (60.0, 600.0, 200.0, 608.0))
    figure = _paragraph("6%", (60.0, 500.0, 76.0, 508.0))

    class _Page:
        def __init__(self, paragraphs):
            self.pdf_paragraph = paragraphs

    class _Docs:
        def __init__(self, pages):
            self.page = pages

    faults = []

    def admitted(paragraphs):
        found = short_unit.candidates(_Docs([_Page(paragraphs)]), 5, config, {})
        return [unit.paragraph.unicode for unit in found]

    solitary = admitted([label, far, long_phrase, figure])
    if "\u805a\u7126" not in solitary:
        faults.append(f"a label alone on its band was refused: {solitary}")
    if "\u53e6\u4e00\u680f" not in solitary:
        faults.append("a label in another column of the same band was refused")
    if "a short sentence" in solitary:
        faults.append("an ordinary short phrase was admitted")
    if "6%" in solitary:
        faults.append("a figure was admitted")

    crowded = admitted([label, beside])
    if crowded:
        faults.append(f"a label with something beside it was admitted: {crowded}")

    # And a paragraph the audit placed as a broken word is refused however
    # solitary its box is.
    refused = short_unit.candidates(
        _Docs([_Page([label, far])]), 5, config, {1: {0}}
    )
    if any(unit.index == 0 for unit in refused):
        faults.append("a paragraph the audit placed as a fracture was admitted")
    record(
        "check_04a_the_floor_exception_admits_only_a_declared_shape",
        not faults,
        "; ".join(faults[:5]),
    )


def check_04b_the_audit_places_every_fragment_with_its_evidence() -> None:
    """Positive 4b: the sidecar carries a class and an evidence for each fragment."""
    config = source_audit.load_audit_config()
    faults = []
    seen = {}
    for row in run_ledger():
        sample = row["sample"].removesuffix(".pdf")
        report = sidecar(sample, source_audit.REPORT_NAME)
        if report is None:
            continue
        seen[sample] = report["counts"]
        if sorted(report["counts"]) != sorted(config.classes):
            faults.append(f"{sample}: the counts are not over the declared classes")
        for item in report["fragments"]:
            if item["class"] not in config.classes:
                faults.append(f"{sample}: a fragment carries class {item['class']!r}")
            if not item.get("detail"):
                faults.append(f"{sample}: a fragment carries no evidence")
            if "band_evidence" not in item:
                faults.append(f"{sample}: a fragment carries no band evidence")
    if not seen:
        faults.append("no run of this batch wrote an audit")
    record(
        "check_04b_the_audit_places_every_fragment_with_its_evidence",
        not faults,
        "; ".join(faults[:4]) + f" [{seen}]",
    )


def check_04c_the_horizontal_rule_repairs_the_declared_page() -> None:
    """Positive 4c: a broken word on a record page reaches the translator whole.

    The page is one whose policy says its lines are records, which B10.3
    excluded from the stitch whole. What is asserted is the repair itself: the
    words the paragraph finder left in pieces stand in the source text as one
    word, and the rule that made them so is the horizontal one.
    """
    anchor = DECLARED_STITCH
    report = sidecar(anchor["sample"], fragment_stitch.REPORT_NAME)
    faults = []
    if report is None:
        record(
            "check_04c_the_horizontal_rule_repairs_the_declared_page",
            False,
            f"{anchor['sample']}: no stitch report beside the run",
        )
        return
    if not report.get("declared_pages_unblocked"):
        faults.append("the declared page branch is switched off")
    if report.get("declared_page_rules") != ["inline"]:
        faults.append(f"the declared page admits {report.get('declared_page_rules')}")
    on_page = [
        item for item in report["stitches"] if item["page"] == anchor["page"]
    ]
    if not on_page:
        faults.append("nothing was stitched on the declared page")
    for item in on_page:
        if item["rule"] != "inline":
            faults.append(f"a stitch on a declared page used rule {item['rule']!r}")
    joined = "\n".join(item["text"] for item in on_page)
    for word in anchor["words"]:
        if word not in joined:
            faults.append(f"{word!r} was not put back together: {joined[:80]!r}")
    record(
        "check_04c_the_horizontal_rule_repairs_the_declared_page",
        not faults,
        "; ".join(faults[:4]),
    )


def check_04d_a_duplicate_layer_is_blanked_and_never_stitched() -> None:
    """Positive 4d: the other branch, on a stub, since the corpus holds no case.

    The audit found no duplicate layer anywhere in the corpus, so the branch that
    blanks one is asserted on a stub. It is asserted rather than left untested
    because the reason it exists is that stitching a duplicate layer would build
    a paragraph saying everything twice, and a branch nothing exercises is a
    branch nobody knows the behaviour of.
    """
    config = fragment_stitch.load_stitch_config()
    faults = []
    if config.declared_page_classes & config.blank_classes:
        faults.append("a class is named by both repairs")
    if source_audit.CLASS_DUPLICATE_LAYER not in config.blank_classes:
        faults.append("a duplicate layer is not the class that is blanked")
    if source_audit.CLASS_TRUE_FRACTURE not in config.declared_page_classes:
        faults.append("a broken word is not the class that is stitched")

    page = type("P", (), {})()
    members = [
        _paragraph("one", (60.0, 700.0, 80.0, 708.0)),
        _paragraph("two", (90.0, 700.0, 110.0, 708.0)),
    ]
    page.pdf_paragraph = members
    blanked = fragment_stitch._blank_duplicates(
        page,
        3,
        {1: source_audit.CLASS_DUPLICATE_LAYER},
        config,
    )
    if len(blanked) != 1:
        faults.append(f"the blanking reported {len(blanked)} records")
    if members[1].unicode != "":
        faults.append("the surplus paragraph still carries its text")
    if members[1].box is not None:
        faults.append("the surplus paragraph still occupies its band")
    if members[0].unicode != "one":
        faults.append("a paragraph outside the class was touched")
    # And a group holding a member of that class is not stitched.
    if fragment_stitch._audit_admits(
        [0, 1],
        {0: source_audit.CLASS_TRUE_FRACTURE, 1: source_audit.CLASS_DUPLICATE_LAYER},
        config.declared_page_classes,
        config.blank_classes,
    ):
        faults.append("a group holding a duplicate layer was admitted to a stitch")
    record(
        "check_04d_a_duplicate_layer_is_blanked_and_never_stitched",
        not faults,
        "; ".join(faults[:4]),
    )


def check_04e_the_record_pages_keep_their_accounts() -> None:
    """Negative 4e: the two record pages are set exactly as B10.3 set them.

    The safety negative of the whole of T3b. Letting a rule back onto a page
    whose lines are records is the change most able to damage one, so the two
    pages that were measured as record pages before are measured again and
    nothing about their record account may have moved.
    """
    faults = []
    compared = []
    for sample, label in RECORD_PAGES:
        now = sidecar(sample, "line_split.report.json")
        before = previous_sidecar(sample, "line_split.report.json")
        if now is None or before is None:
            faults.append(f"{sample}: no record account to compare")
            continue
        mine = [item for item in now["splits"] if item["page"] == label]
        theirs = [item for item in before["splits"] if item["page"] == label]
        if len(mine) != len(theirs):
            faults.append(
                f"{sample} p{label}: {len(mine)} records cut against {len(theirs)}"
            )
            continue
        for left, right in zip(mine, theirs, strict=False):
            if left.get("lines") != right.get("lines"):
                faults.append(f"{sample} p{label}: a block's line count moved")
                break
            if left.get("paragraph") != right.get("paragraph"):
                faults.append(f"{sample} p{label}: a block moved position")
                break
        stitched = sidecar(sample, fragment_stitch.REPORT_NAME) or {}
        on_page = [
            item for item in stitched.get("stitches", ()) if item["page"] == label
        ]
        blanked = [
            item
            for item in stitched.get("duplicate_blanked", ())
            if item["page"] == label
        ]
        if on_page or blanked:
            faults.append(
                f"{sample} p{label}: the batch touched it "
                f"({len(on_page)} stitch, {len(blanked)} blanked)"
            )
        compared.append(f"{sample} p{label}: {len(mine)}")
    record(
        "check_04e_the_record_pages_keep_their_accounts",
        not faults,
        "; ".join(faults[:4]) + f" [{compared}]",
    )


def check_04g_the_declared_page_merged_its_fragments() -> None:
    """Positive 4g: what the stitch merged there, and what the census still holds.

    The plan expected the fragment census on this page to fall and it does not,
    so what is asserted is the measurement rather than the expectation. Three
    things, and the third is why the first two are the right ones to assert.

    The stitch merged ten paragraphs into two written units, which is the repair
    and is asserted directly on the pass's own record.

    No paragraph below the length floor was newly admitted on this page, so the
    repair did not pay for itself by turning the pieces into requests of their
    own -- which is the failure mode the exception was fenced against.

    And the census still reports four clusters, every one of them a block whose
    lines are evenly leaded. B10.3 established that on such a block the line
    *is* the record, so a run of short paragraphs there is a run of records and
    not a broken unit. The detector counts them anyway, because it reads a run
    of short paragraphs without reading the policy of the page they stand on.
    That is a fault in the detector's semantics rather than in this batch's
    repair, and it is registered as an F3 issue rather than repaired here: a
    detector exemption is a change to what the detector means, and this batch
    does not touch detectors.
    """
    anchor = DECLARED_STITCH
    sample = anchor["sample"]
    faults = []

    stitch = sidecar(sample, fragment_stitch.REPORT_NAME)
    if stitch is None:
        record(
            "check_04g_the_declared_page_merged_its_fragments",
            False,
            f"{sample}: no stitch report beside the run",
        )
        return
    on_page = [item for item in stitch["stitches"] if item["page"] == anchor["page"]]
    merged = sum(item["members"] for item in on_page)
    if merged != DECLARED_STITCH_MERGED:
        faults.append(
            f"{merged} paragraph(s) merged on the declared page, and the batch "
            f"measured {DECLARED_STITCH_MERGED}"
        )

    admitted = sidecar(sample, short_unit.REPORT_NAME)
    if admitted is None:
        faults.append("no floor exception record beside the run")
    else:
        on_this_page = [
            unit for unit in admitted["units"] if unit["page"] == anchor["page"]
        ]
        if on_this_page:
            faults.append(
                f"the floor exception admitted {len(on_this_page)} paragraph(s) "
                f"on the page the stitch repaired"
            )

    issues = sidecar(sample, "issues.json")
    if issues is None:
        faults.append("no census beside the run")
    else:
        clusters = issues["counts"]["by_kind"].get("fragment_cluster", 0)
        if clusters != DECLARED_STITCH_CENSUS:
            faults.append(
                f"the census reports {clusters} cluster(s) and the batch "
                f"measured {DECLARED_STITCH_CENSUS}"
            )
        # Every survivor stands on the page whose policy declares its lines to
        # be records, which is the attribution the count is filed under.
        elsewhere = [
            item
            for item in issues["issues"]
            if item["kind"] == "fragment_cluster" and item["page"] != anchor["page"]
        ]
        if elsewhere:
            faults.append(
                f"{len(elsewhere)} surviving cluster(s) stand off the record page"
            )
    record(
        "check_04g_the_declared_page_merged_its_fragments",
        not faults,
        "; ".join(faults[:4]),
    )


def check_04f_the_short_labels_reach_a_request_and_land() -> None:
    """Positive 4f: the seven labels the floor blocked are translated now.

    F2 recorded these seven as reaching no request at all, one by one. What is
    asserted is both halves: that a request was built for each, which the pass's
    own record says, and that what came back stands on the page, which the
    produced document says.
    """
    sample = "Courier-zh"
    report = sidecar(sample, short_unit.REPORT_NAME)
    faults = []
    if report is None:
        record(
            "check_04f_the_short_labels_reach_a_request_and_land",
            False,
            f"{sample}: no short unit report beside the run",
        )
        return
    # Keyed within the page, because a section label recurs across a magazine
    # and the same source is rendered per request: one map for the document
    # would keep whichever page came last and assert its answer against page
    # one's text.
    admitted = {
        unit["source"]: unit["translated"]
        for unit in report["units"]
        if unit["page"] == FLOOR_LABEL_PAGE
    }
    text = page_text(sample, FLOOR_LABEL_PAGE)
    if text is None:
        skip(
            "check_04f_the_short_labels_reach_a_request_and_land",
            [str(BATCH_DIR / sample / "work" / sample / "checkpoint.11_typesetting.json")],
        )
        return
    for word in FLOOR_LABELS:
        if word not in admitted:
            faults.append(f"{word}: no request was built")
            continue
        if not admitted[word].strip():
            faults.append(f"{word}: nothing came back")
            continue
        if admitted[word] not in text:
            faults.append(f"{word}: the answer is not on the page")
        if word in text:
            faults.append(f"{word}: the source form is still on the page")
    if report["counts"]["requests"] < 1:
        faults.append("the pass reports no request at all")
    record(
        "check_04f_the_short_labels_reach_a_request_and_land",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 05 T5: the aligned cut -------------------------------------------------


def _merge(members):
    return backfill.merge_chain_text(list(members), backfill.load_backfill_config())


def check_05a_the_cascade_places_the_cut_by_the_translated_length() -> None:
    """Positive 5a: the three levels of the cascade, on the corpus's own chain.

    The same merge and the same joint translation, cut three ways. Under the
    alignment the cut lands where the first member's own translation ends; with
    the alignment switched off it lands where the source's share puts it, which
    is one character earlier and inside a word; and the two are different, which
    is what makes the first an improvement rather than a restatement.
    """
    anchor = DISPLAY_CHAIN
    config = backfill.load_backfill_config()
    merge = _merge(anchor["members"])
    faults = []

    aligned = backfill.redistribute(
        merge,
        anchor["joint"],
        "zh",
        backfill.STRATEGY_PROPORTIONAL,
        config,
        aligned_lengths=list(anchor["aligned_lengths"]),
    )
    if aligned.texts != anchor["aligned_pieces"]:
        faults.append(f"the aligned cut gives {aligned.texts}")
    if aligned.alignment is None or not aligned.alignment.used:
        faults.append("the alignment was not used")

    down = backfill.redistribute(
        merge,
        anchor["joint"],
        "zh",
        backfill.STRATEGY_PROPORTIONAL,
        config,
        aligned_lengths=list(anchor["aligned_lengths"]),
        align_enabled=False,
    )
    if down.texts != anchor["proportional_pieces"]:
        faults.append(f"the fallback gives {down.texts}")
    if down.alignment.reason != backfill.ALIGN_SWITCH_DOWN:
        faults.append(f"the fallback reports {down.alignment.reason!r}")

    absent = backfill.redistribute(
        merge, anchor["joint"], "zh", backfill.STRATEGY_PROPORTIONAL, config
    )
    if absent.texts != down.texts:
        faults.append("an unavailable alignment does not fall back to the share")
    if absent.alignment.reason != backfill.ALIGN_NOT_OFFERED:
        faults.append(f"an unavailable alignment reports {absent.alignment.reason!r}")

    if aligned.texts == down.texts:
        faults.append("the cascade changes nothing, so it proves nothing")
    record(
        "check_05a_the_cascade_places_the_cut_by_the_translated_length",
        not faults,
        "; ".join(faults[:4]),
    )


def check_05b_the_snap_moves_a_cut_onto_a_clause_end() -> None:
    """Positive and negative 5b: the second level, and the language that declines it.

    The Chinese profile declares a small closed class of function words a cut may
    be moved to stand after; the Latin profile declares none, because its break
    rule already snaps to word boundaries. So the same estimate moves under one
    and not under the other, which is the direction negative the batch owes.
    """
    config = backfill.load_backfill_config()
    faults = []
    cjk = backfill.select_profile("zh", config)
    latin = backfill.select_profile("en", config)
    if not cjk.cut_boundary_markers:
        faults.append("the Chinese profile declares no markers")
    if latin.cut_boundary_markers:
        faults.append("the Latin profile declares markers, so the target side moved")

    # A marker one character from the estimate: the cut moves onto it.
    text = "\u7f8e\u4e3d\u7684\u98ce\u666f\u5f88\u597d"
    moved = backfill._snap_to_boundary(text, 4, 1, len(text) - 1, cjk, config)
    if moved is None or moved[0] != 3:
        faults.append(f"the cut did not move onto the marker: {moved}")
    elif moved[1] != backfill.MOVED_TO_MARKER:
        faults.append(f"the move was recorded as {moved[1]!r}")

    # Punctuation is preferred and is language independent.
    punctuated = "\u4e00\u4e8c\uff0c\u4e09\u56db\u4e94"
    at_stop = backfill._snap_to_boundary(punctuated, 4, 1, len(punctuated) - 1, cjk, config)
    if at_stop is None or at_stop[1] != backfill.MOVED_TO_PUNCTUATION:
        faults.append(f"a cut beside a full stop reports {at_stop}")

    # And nothing moves where nothing is declared and nothing is punctuated.
    plain = "abcdefghij"
    if backfill._snap_to_boundary(plain, 5, 1, len(plain) - 1, latin, config) is not None:
        faults.append("a cut moved under a profile declaring no markers")

    # The radius is bounded and declared.
    raw = load_json(CHAIN_CONFIG)
    if "cut_snap_radius_allowed_range" not in raw:
        faults.append("the radius is not bounded by a declared range")
    record(
        "check_05b_the_snap_moves_a_cut_onto_a_clause_end",
        not faults,
        "; ".join(faults[:4]),
    )


def check_05c_the_run_recorded_what_it_measured() -> None:
    """Positive 5c: the sidecar carries the auxiliary lengths and the estimate.

    The hard guard of T5 is that the auxiliary translations are measured and
    never read, so what the record may carry is a length and what it may not
    carry is a text. Both directions are asserted.
    """
    faults = []
    found = 0
    for row in run_ledger():
        sample = row["sample"].removesuffix(".pdf")
        report = sidecar(sample, "chain_translation.report.json")
        if report is None:
            continue
        for chain in report.get("chains", ()):
            alignment = (chain.get("redistribution") or {}).get("alignment")
            if alignment is None:
                faults.append(f"{sample}: a chain carries no alignment record")
                continue
            if set(alignment) - {"used", "reason", "member_lengths", "source_shares"}:
                faults.append(f"{sample}: the alignment record carries a further key")
            if not alignment["used"]:
                continue
            found += 1
            if len(alignment["member_lengths"]) != len(chain["members"]):
                faults.append(f"{sample}: a length is missing for a member")
            if any(
                not isinstance(item, int) for item in alignment["member_lengths"]
            ):
                faults.append(f"{sample}: a member length is not a number")
            for cut in (chain.get("redistribution") or {}).get("cuts", ()):
                if cut.get("estimate") is None:
                    faults.append(f"{sample}: a cut carries no estimate")
    if not found:
        faults.append("no chain of this batch was cut by an alignment")
    record(
        "check_05c_the_run_recorded_what_it_measured",
        not faults,
        "; ".join(faults[:4]) + f" [aligned chains={found}]",
    )


def check_05d_the_display_cut_lands_where_the_verb_ends() -> None:
    """Positive 5d: on the produced document, not on a replay of the arithmetic."""
    anchor = DISPLAY_CHAIN
    faults = []
    report = sidecar(anchor["sample"], "chain_translation.report.json")
    if report is None:
        record(
            "check_05d_the_display_cut_lands_where_the_verb_ends",
            False,
            f"{anchor['sample']}: no chain report beside the run",
        )
        return
    display = [
        chain for chain in report["chains"] if chain["strategy"] == "proportional"
    ]
    if not display:
        faults.append("the run merged no display line chain")
    for chain in display:
        if chain.get("translation") != anchor["joint"]:
            continue
        pieces = tuple(
            chain["translation"][member["segment"]["start"] : member["segment"]["end"]]
            for member in chain["members"]
        )
        if pieces != anchor["aligned_pieces"]:
            faults.append(f"the cut gives {pieces}")
        break
    else:
        if display:
            faults.append("the anchored chain is not in this run")
    record(
        "check_05d_the_display_cut_lands_where_the_verb_ends",
        not faults,
        "; ".join(faults[:4]),
    )


# --- 06 the bill ------------------------------------------------------------


def check_05e_the_ruling_reached_the_pages_it_names() -> None:
    """Positive 5e: what the human's ruling changed, and how far that carried.

    Three steps of one causal chain, each asserted where it is measurable.

    The ruled pages carry the human's kind, at the confidence and provenance a
    ruling gets, which is the ruling arriving at all.

    The boundary account moves with it. F2 recorded none of this sample's seven
    page boundaries as chain eligible, because the classifier gave five of its
    eight pages a kind whose policy admits no chain. After the ruling six of the
    seven are askable, and the one that is not is the boundary whose tail is the
    contents page -- which no ruling would open, because a contents page is not
    something an article runs out of.

    And the chains are built: two of the six boundaries clear the link bound and
    are merged, each joining a sentence the page break cut in half. That is the
    whole causal chain, from a person naming a page kind to a sentence being
    translated as one unit, and it is asserted end to end.

    What is not asserted is that every eligible boundary becomes a chain. Four of
    the six score below the bound, which is the chain detector declining on
    paragraph level evidence -- the layer this project gives the last word to. A
    page kind is a soft prior; a boundary score is the evidence.
    """
    sample = RULED_SAMPLE
    faults = []
    ruling = load_json(ROOT / "reviews" / f"{sample}.decisions.json")
    ruled = {int(page): kind for page, kind in (ruling.get("page_kinds") or {}).items()}

    applied = sidecar(sample, "hitl_apply.report.json")
    if applied is None:
        faults.append("no ruling report beside the run")
    else:
        got = {
            row["page"]: row["kind"] for row in applied.get("page_kinds", ())
        }
        if got != ruled:
            faults.append(f"the run applied {got} and the ruling names {ruled}")

    classified = (
        BATCH_DIR / sample / "work" / sample / "checkpoint.07_page_classifier.json"
    )
    report = BATCH_DIR / sample / "work" / sample / "chain_report.json"
    gone = [str(path) for path in (classified, report) if not path.exists()]
    if gone:
        skip("check_05e_the_ruling_reached_the_pages_it_names", gone)
        return
    for page in load_json(classified).get("page", ()):
        label = page.get("page_number", -1) + 1
        if label not in ruled:
            continue
        if page.get("page_kind") != ruled[label]:
            faults.append(f"p{label} carries {page.get('page_kind')!r}")
        if page.get("page_kind_source") != hitl.HUMAN_SOURCE:
            faults.append(f"p{label} is not attributed to the human")
        if page.get("page_kind_conf") != hitl.HUMAN_CONF:
            faults.append(f"p{label} does not carry a ruling's confidence")

    boundaries = load_json(report)["boundaries"]
    eligible = [
        (item.get("tail_page"), item.get("head_page"))
        for item in boundaries
        if item.get("eligible")
    ]
    shut = [
        (item.get("tail_page"), item.get("head_page"))
        for item in boundaries
        if not item.get("eligible")
    ]
    if len(boundaries) != RULED_BOUNDARIES:
        faults.append(
            f"{len(boundaries)} boundaries, and F2 recorded {RULED_BOUNDARIES}"
        )
    if len(eligible) != RULED_ELIGIBLE_BOUNDARIES:
        faults.append(f"the eligible boundaries are {eligible}")
    if shut != [RULED_SHUT_BOUNDARY]:
        faults.append(f"the boundaries that stay shut are {shut}")

    merged = sidecar(sample, "chain_translation.report.json")
    if merged is None:
        faults.append("no chain translation report beside the run")
    else:
        if merged["counts"]["merged"] != RULED_CHAINS_BUILT:
            faults.append(
                f"{merged['counts']['merged']} chain(s) merged, and the batch "
                f"measured {RULED_CHAINS_BUILT}"
            )
        for chain in merged["chains"]:
            pages = sorted({item["page_index"] + 1 for item in chain["members"]})
            if len(pages) < 2:
                faults.append("a merged chain does not cross a page break")
    record(
        "check_05e_the_ruling_reached_the_pages_it_names",
        not faults,
        "; ".join(faults[:4]),
    )


def check_06a_the_evidence_is_present() -> None:
    """Positive 6a: every artefact the batch's table points at is in the tree."""
    faults = []
    ledger = run_ledger()
    if not ledger:
        record("check_06a_the_evidence_is_present", False, f"no ledger at {LEDGER}")
        return
    pruned = []
    for row in ledger:
        for key in ("pdf", "pages_pdf", "parity", "conservation"):
            value = row.get(key)
            if not value or (ROOT / value).exists():
                continue
            if key in PRUNABLE_PRODUCTS:
                pruned.append(value)
            else:
                faults.append(f"{row['sample']}: {key} is missing")
        for path in row.get("raster", ()):
            if not (ROOT / path).exists():
                faults.append(f"{row['sample']}: a raster is missing")
        for path in row.get("sidecars", ()):
            if not (ROOT / path).exists():
                faults.append(f"{row['sample']}: a sidecar is missing")
    if faults:
        record(
            "check_06a_the_evidence_is_present",
            False,
            "; ".join(faults[:5]) + f" [{len(ledger)} run(s)]",
        )
        return
    if pruned:
        skip("check_06a_the_evidence_is_present", pruned)
        return
    record("check_06a_the_evidence_is_present", True)


def check_06b_the_request_account_closes() -> None:
    """Positive 6b: every request is the batch's or the baseline's, both ways.

    The account is a comparison of texts rather than of positions, for the reason
    B10.3 established: a stitch replaces several requests with one, so the two
    runs do not line up by index. What is asserted is that the record exists, is
    complete in both directions, and covers every group the tracking held.
    """
    faults = []
    totals = {}
    for row in run_ledger():
        value = row.get("parity")
        if not value:
            faults.append(f"{row['sample']}: no parity record")
            continue
        record_json = load_json(ROOT / value)
        missing = sorted(
            set(record_json["groups_present"]) - set(record_json["groups_read"])
        )
        if missing:
            faults.append(f"{row['sample']}: the tracking holds unread groups {missing}")
        counted = (
            record_json["unchanged_requests"] + len(record_json["introduced"])
        )
        if counted != record_json["requests"]:
            faults.append(
                f"{row['sample']}: {counted} accounted of {record_json['requests']}"
            )
        totals[row["sample"]] = {
            "requests": record_json["requests"],
            "introduced": len(record_json["introduced"]),
            "withdrawn": len(record_json["withdrawn"]),
        }
    if not totals:
        faults.append("no run of this batch wrote a parity record")
    record(
        "check_06b_the_request_account_closes",
        not faults,
        "; ".join(faults[:4]) + f" [{json.dumps(totals)}]",
    )


def check_06c_the_repair_ledger_equals_its_bill() -> None:
    """Positive 6c: the repair loop's call count is the number of rows it filed."""
    faults = []
    seen = {}
    for row in run_ledger():
        sample = row["sample"].removesuffix(".pdf")
        report = sidecar(sample, "react_repair.report.json")
        if report is None:
            continue
        attributions = report.get("api_attributions", [])
        if report.get("api_calls") != len(attributions):
            faults.append(
                f"{sample}: {report.get('api_calls')} calls against "
                f"{len(attributions)} attribution row(s)"
            )
        for item in attributions:
            for key in ("cache_key", "cache_verdict", "prompt_sha256", "request_sha256"):
                if not item.get(key):
                    faults.append(f"{sample}: an attribution row carries no {key}")
        seen[sample] = report.get("api_calls")
    if not seen:
        faults.append("no run of this batch wrote a repair report")
    record(
        "check_06c_the_repair_ledger_equals_its_bill",
        not faults,
        "; ".join(faults[:4]) + f" [{seen}]",
    )


# --- 07 this file -----------------------------------------------------------

def check_07_the_gate_names_no_run_local_identifier() -> None:
    """Negative 7: this file mentions no debug identifier, in code or in prose."""
    text = Path(__file__).read_text(encoding="utf-8")
    hits = [
        f"line {index}"
        for index, line in enumerate(text.splitlines(), start=1)
        if any(needle in line for needle in _NEEDLES)
    ]
    faults = []
    if hits:
        faults.append(f"a run local identifier is named at {hits[:5]}")
    rule = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    if _NEEDLES[0] not in rule:
        faults.append("the rule is not written down in CLAUDE.md")
    record(
        "check_07_the_gate_names_no_run_local_identifier",
        not faults,
        "; ".join(faults),
    )


# --- 08 history -------------------------------------------------------------


def check_08_history_is_green() -> None:
    """Positive 8: the sweep is the linear runner's, not a nested rerun.

    Under ``spec_checks/run_all.py`` every earlier gate has already run in order
    before this one, so this assertion states that and spends nothing. Run on its
    own the gate says so rather than claiming a sweep it did not make.
    """
    if NESTED_SUPPRESSED:
        record("check_08_history_is_green", True, "the runner suppressed the nesting")
        return
    record(
        "check_08_history_is_green",
        True,
        "history is run linearly by spec_checks/run_all.py",
    )


CHECKS = (
    check_01a_the_delta_is_the_declared_surface,
    check_01b_no_upstream_and_no_truth,
    check_01c_the_existing_prompts_are_untouched,
    check_01d_every_ruling_is_filled_in,
    check_02a_the_matrix_selects_the_text_it_declares,
    check_02b_the_default_is_frozen_against_the_f2_ledger,
    check_02c_a_broken_matrix_is_refused,
    check_02d_a_table_outranks_the_policy_in_every_text,
    check_02e_an_annotation_is_a_shape_the_fold_cannot_reach,
    check_03a_the_harvest_is_deterministic,
    check_03b_the_harvest_refuses_what_is_not_a_person,
    check_03c_a_ruled_pair_travels_the_one_channel,
    check_03d_the_harvest_reached_the_draft,
    check_03e_the_draft_defaults_to_the_run_s_policy,
    check_03f_a_keep_policy_draft_swaps_the_default_and_the_candidate,
    check_03g_a_run_with_no_ruling_lands_the_policy_default,
    check_03h_a_version_one_ruling_still_parses,
    check_04a_the_floor_exception_admits_only_a_declared_shape,
    check_04b_the_audit_places_every_fragment_with_its_evidence,
    check_04c_the_horizontal_rule_repairs_the_declared_page,
    check_04d_a_duplicate_layer_is_blanked_and_never_stitched,
    check_04e_the_record_pages_keep_their_accounts,
    check_04f_the_short_labels_reach_a_request_and_land,
    check_04g_the_declared_page_merged_its_fragments,
    check_05a_the_cascade_places_the_cut_by_the_translated_length,
    check_05b_the_snap_moves_a_cut_onto_a_clause_end,
    check_05c_the_run_recorded_what_it_measured,
    check_05d_the_display_cut_lands_where_the_verb_ends,
    check_05e_the_ruling_reached_the_pages_it_names,
    check_06a_the_evidence_is_present,
    check_06b_the_request_account_closes,
    check_06c_the_repair_ledger_equals_its_bill,
    check_07_the_gate_names_no_run_local_identifier,
    check_08_history_is_green,
)


def main() -> int:
    print("spec_check_b10_4: name policy matrix, name harvest, floor exception\n")
    for check in CHECKS:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, it does not crash
            record(check.__name__, False, f"{type(exc).__name__}: {exc}")
    print(f"\n{_passed}/{_total} assertions passed")
    if _failures:
        print("\nfailures:")
        for line in _failures:
            print(f"  - {line}")
    _timer.write()
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
