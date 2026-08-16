"""Gate script for batch B9.1 (per sample language direction, person name policy).

Run from the repository root:

    python spec_checks/spec_check_b9_1.py

Exit code 0 when every assertion T9.1 answers for passes, 1 otherwise. Needs no
API key and makes no network request: every engine in this file is a stub, and
the one run that spent a credential left its evidence under
examples/output/b9_1/, which is what this gate reads.

01 is the direction (T9.1a). The registry gained two fields and the manifest
carries them verbatim, which is asserted the same way every other semantic field
is. The schema is asserted by probe rather than by reading it: a sample missing
a half of its direction, naming a language outside the vocabulary, or declaring
the same language twice each has to be refused, and the third is the one that
matters, because a sample translated into the language it is already written in
is exactly the F1 defect this batch exists to remove. Then every driver that
builds a run is asserted to read the direction of the sample it is about to run
rather than to hold one, and the one build helper that still holds a constant
direction is held to the invariant that makes that safe: it builds no mode in
which a translation happens at all.

02 is the standing instruction (T9.1b). PLAN B9.1 named the article brief
channel; that channel cannot reach every batch, so the instruction travels by
the system prompt slot instead, and the assertions here are about coverage.
Three prompt builders exist on the translation path -- the page batch, the
merged chain and the paragraph a failed batch retries alone -- and each is
driven here and asserted to carry the declared text. The three layers are then
put in one prompt together, because the precedence between them is a claim
about a prompt that holds all three and not about three prompts that hold one
each. Two more assertions hold the switch honest: under keep_source nothing is
written and the prompt is byte for byte the one built with no policy at all,
and a caller's own system prompt is kept and stated first.

03 is the smoke (T9.1c), read from the frozen evidence: the corrected direction
produced the target language, the contents page personal names moved, and the
terms a human ruled did not.

04 is the scope, and 05 the sweep.

Every assertion is static. There is no pipeline tier.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.midend.il_translator import (  # noqa: E402
    DocumentTranslateTracker,
)
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (  # noqa: E402
    ILTranslatorLLMOnly,
)
from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.glossary import Glossary  # noqa: E402
from babeldoc.glossary import GlossaryEntry  # noqa: E402
from babeldoc.magazine import chain_translation  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import translation_style  # noqa: E402
from babeldoc.progress_monitor import ProgressMonitor  # noqa: E402
from babeldoc.translator.translator import BaseTranslator  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b9.1"

PYTHON = sys.executable

NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

OUTPUT_DIR = ROOT / "examples" / "output" / "b9_1"
EVIDENCE = OUTPUT_DIR / "evidence.json"

# One evidence file per wording round of the person name policy. The ruling is
# asserted against all of them, not only against the wording that shipped.
ITERATION_DIR = OUTPUT_DIR / "iteration"
SMOKE_DRIVER = OUTPUT_DIR / "scripts" / "run_b9_1_smoke.py"

STYLE_CONFIG = ROOT / "configs" / "translation_style.json"

# Paths this batch may change.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "tools/",
    "spec_checks/",
    "plans/",
    "examples/output/",
    "corpus/manifest.json",
    "docs/",
)
ALLOWED_FILES = {
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
    "CLAUDE.md",
    # The corpus owner's own edit, which this batch's plan is built on having
    # been made. Permitted here and constrained by 04a2, which is where the
    # machine is asserted to be absent from it.
    "corpus/registry.user.json",
}

# Files a run may never write to.
READ_ONLY = ("corpus/registry.user.json", "corpus/page_labels.json")

# Every driver that builds a pipeline run over a named corpus sample. Each has
# to read that sample's direction; none may hold one.
SAMPLE_DRIVERS = (
    "examples/output/final/scripts/run_final.py",
    "tools/build_baseline.py",
    "tools/chain_report.py",
    "tools/page_classify_report.py",
    "tools/run_drift_trio.py",
)

# The shared build helper the gates use. It is not in the list above because it
# is not driven by a sample name, and it is allowed to keep one constant
# direction only for as long as 01d's invariant holds.
BUILD_HELPER = "spec_checks/artifacts.py"

# The code this batch adds or reworks, which the scope assertions hold to the
# conventions.
SESSION_CODE = (
    "babeldoc/magazine/translation_style.py",
    "babeldoc/magazine/corpus.py",
    *SAMPLE_DRIVERS,
    "examples/output/b9_1/scripts/run_b9_1_smoke.py",
    "examples/output/b9_1/scripts/analyze_name_policy.py",
    f"spec_checks/{Path(__file__).name}",
)

# The sample the prompt fixtures are built in the direction of, so that no
# language tag is written into this gate either.
FIXTURE_SAMPLE = "Courier-en"

# The sample whose direction this batch corrected, and the one whose contents
# page the person name comparison is drawn from.
REVERSED_SAMPLE = "Courier-zh"
NAMED_SAMPLE = "Courier-en"

# The two section names of the prompt the declared role text has to defer to.
# They are the headers `_build_llm_prompt` writes, and 02c asserts they really
# are before asserting the role text names them, so a renamed section fails
# here rather than silently making the precedence unreadable to the model.
GLOSSARY_SECTION = "Glossary"
HINTS_SECTION = "Contextual Hints"

# Invented tokens for the three layer fixture. Nothing here is a real name: the
# assertion is about which of three renderings of one token reaches the prompt,
# and a token that occurs in no corpus makes that unambiguous.
FIXTURE_TOKEN = "Qvaldrin"  # noqa: S105 - an invented word, not a secret
FIXTURE_RULED = "Qvaldrin-ruled"
FIXTURE_SUGGESTED = "Qvaldrin-suggested"

STUB_MAX_QPS = 1000

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b9_1_"))

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b9_1")


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


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def git_text(args: list[str]) -> tuple[int, str]:
    """``git_output`` for a file that is not ASCII.

    The corpus registry carries the owner's notes, which are not ASCII, and the
    default decoding here is the console's rather than the file's.
    """
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return proc.returncode, proc.stdout or ""


def changed_paths() -> set[str]:
    """This batch's delta: its tag where it exists, the working tree otherwise."""
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^..{BATCH_TAG}"])
        return {line.strip() for line in listing.splitlines() if line.strip()}
    _, listing = git_output(["diff", "--name-only", "HEAD"])
    paths = {line.strip() for line in listing.splitlines() if line.strip()}
    _, untracked = git_output(["status", "--porcelain", "--untracked-files=all"])
    for line in untracked.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def source_of(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def registry_entries() -> list[dict]:
    return corpus.load_registry()


def fixture_direction() -> tuple[str, str]:
    return corpus.direction_of(FIXTURE_SAMPLE)


# --- 01 the direction ----------------------------------------------------------


def check_01a_manifest_copies_the_registry_verbatim() -> None:
    """Positive 1a: both direction fields reach the manifest unchanged."""
    entries = {entry["file"]: entry for entry in registry_entries()}
    manifest = corpus.load_manifest()
    faults = []
    for field in corpus.DIRECTION_FIELDS:
        if field not in corpus.SEMANTIC_FIELDS:
            faults.append(f"{field} is not carried as a semantic field")
    seen = 0
    for sample in manifest.get("samples", []):
        entry = entries.get(sample.get("file"))
        if entry is None:
            faults.append(f"{sample.get('file')}: not in the registry")
            continue
        seen += 1
        for field in corpus.DIRECTION_FIELDS:
            if sample.get(field) != entry.get(field):
                faults.append(
                    f"{sample['file']}: {field} manifest={sample.get(field)!r} "
                    f"registry={entry.get(field)!r}"
                )
    if seen != len(entries):
        faults.append(f"{seen} sample(s) compared, registry holds {len(entries)}")
    record(
        "check_01a_manifest_copies_the_registry_verbatim",
        not faults and seen > 0,
        "; ".join(faults[:5]),
    )


def check_01b_the_schema_refuses_a_bad_direction() -> None:
    """Negative 1b: absent, out of vocabulary and equal directions are refused.

    Probed rather than read. The corpus on disk is valid, so the only way to
    assert what the validator rejects is to hand it something it has to reject
    and check that it names the field at fault.
    """
    entries = registry_entries()
    faults = []
    if corpus.validate_registry(entries):
        faults.append(
            "the corpus on disk does not validate, so the probes prove nothing"
        )

    def probe(label: str, mutate) -> None:
        broken = copy.deepcopy(entries)
        mutate(broken[0])
        errors = corpus.validate_registry(broken)
        named = [
            message
            for message in errors
            if any(field in message for field in corpus.DIRECTION_FIELDS)
        ]
        if not named:
            faults.append(f"{label}: accepted, or refused without naming the field")

    probe("absent", lambda entry: entry.pop(corpus.DIRECTION_FIELDS[0]))
    probe(
        "out of vocabulary",
        lambda entry: entry.__setitem__(corpus.DIRECTION_FIELDS[1], "xx"),
    )
    probe(
        "both halves equal",
        lambda entry: entry.__setitem__(
            corpus.DIRECTION_FIELDS[1], entry[corpus.DIRECTION_FIELDS[0]]
        ),
    )
    # A vocabulary that is not closed would make the second probe meaningless.
    if not corpus.languages():
        faults.append("no language vocabulary is declared")
    record(
        "check_01b_the_schema_refuses_a_bad_direction", not faults, "; ".join(faults)
    )


def check_01c_every_driver_reads_the_direction_per_sample() -> None:
    """Positive 1c: the six sample table, and no driver holding a direction.

    The table is asserted against the registry rather than written out here:
    what this batch owes is that a driver asks, not that any particular sample
    goes any particular way, and the corpus owner is the only one who decides
    the second.
    """
    faults = []
    declared = {
        Path(entry["file"]).stem: (
            entry[corpus.DIRECTION_FIELDS[0]],
            entry[corpus.DIRECTION_FIELDS[1]],
        )
        for entry in registry_entries()
    }
    if len(declared) != 6:
        faults.append(f"{len(declared)} sample(s) registered, expected 6")
    for sample, direction in declared.items():
        resolved = corpus.direction_of(sample)
        if resolved != direction:
            faults.append(f"{sample}: resolved {resolved}, declared {direction}")
        by_file = corpus.direction_of(f"{sample}.pdf")
        if by_file != direction:
            faults.append(f"{sample}: file name resolves to {by_file}")
    # A sample nobody registered has no direction, and asking for one raises
    # rather than returning a default: a default is the whole defect.
    try:
        corpus.direction_of("no-such-sample")
    except corpus.CorpusError:
        pass
    else:
        faults.append("an unregistered sample was given a direction")

    for relative in SAMPLE_DRIVERS:
        body = source_of(relative)
        if "direction_of" not in body:
            faults.append(f"{relative}: does not read a declared direction")
        held = _constant_language_arguments(body)
        if held:
            faults.append(f"{relative}: holds {sorted(held)}")
    record(
        "check_01c_every_driver_reads_the_direction_per_sample",
        not faults,
        "; ".join(faults[:5]),
    )


def _constant_language_arguments(body: str) -> set[str]:
    """``lang_in``/``lang_out`` keyword arguments given a string literal."""
    held: set[str] = set()
    for node in ast.walk(ast.parse(body)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in ("lang_in", "lang_out") and isinstance(
                keyword.value, ast.Constant
            ):
                held.add(f"{keyword.arg}={keyword.value.value!r}")
    return held


def check_01d_no_constant_direction_reaches_a_translation() -> None:
    """Negative 1d: the one helper still holding a direction translates nothing.

    ``spec_checks/artifacts.py`` builds every gate artefact from one constant
    direction. That is safe exactly while none of its modes runs the
    translation stage, so the condition is asserted rather than assumed: a mode
    added without ``skip_translation`` or ``only_parse_generate_pdf`` would put
    a held direction back on a translation path, and fails here.
    """
    faults = []
    held = _constant_language_arguments(source_of(BUILD_HELPER))
    if not held:
        faults.append(f"{BUILD_HELPER}: holds no direction, so this check is stale")
    for name, settings in artifacts.MODES.items():
        if not (
            settings.get("skip_translation") or settings.get("only_parse_generate_pdf")
        ):
            faults.append(f"{BUILD_HELPER}: mode {name} runs the translation stage")
    record(
        "check_01d_no_constant_direction_reaches_a_translation",
        not faults,
        "; ".join(faults[:5]),
    )


# --- 02 the standing instruction ------------------------------------------------


class StubTranslator(BaseTranslator):
    """An engine that answers every request the same way and keeps the prompt."""

    name = "b9-1-stub"

    def __init__(self, source_lang: str, target_lang: str):
        super().__init__(source_lang, target_lang, ignore_cache=True)
        self.prompts: list[str] = []

    def do_translate(self, text, rate_limit_params: dict = None):
        self.prompts.append(text)
        return text

    def do_llm_translate(self, text, rate_limit_params: dict = None):
        self.prompts.append(text)
        return json.dumps([{"id": 0, "output": FIXTURE_TOKEN}])


def _stage(
    label: str,
    custom_system_prompt: str | None = None,
    glossaries: list[Glossary] | None = None,
) -> ILTranslatorLLMOnly:
    """A translation stage built the way the pipeline builds one."""
    source_lang, target_lang = fixture_direction()
    work = _tmp_root / label
    work.mkdir(parents=True, exist_ok=True)
    monitor = ProgressMonitor([(ILTranslatorLLMOnly.stage_name, 1.0)])
    monitor.disable = True
    config = TranslationConfig(
        translator=StubTranslator(source_lang, target_lang),
        input_file="Sample.pdf",
        lang_in=source_lang,
        lang_out=target_lang,
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        working_dir=work,
        output_dir=work / "out",
        progress_monitor=monitor,
        auto_extract_glossary=False,
        qps=STUB_MAX_QPS,
        custom_system_prompt=custom_system_prompt,
    )
    if glossaries:
        config.shared_context_cross_split_part.initialize_glossaries(glossaries)
    return ILTranslatorLLMOnly(config.translator, config)


def _batch_prompt(stage: ILTranslatorLLMOnly, **kwargs) -> str:
    return stage._build_llm_prompt(
        json_input_str="[]",
        title_paragraph=None,
        local_title_paragraph=None,
        batch_text_for_glossary_matching=kwargs.pop("text", ""),
        **kwargs,
    )


def _chain_prompt(stage: ILTranslatorLLMOnly) -> str:
    """Drive the merged chain path and return the prompt it built."""
    plan = chain_translation.ChainPlan(stage)
    tracker = DocumentTranslateTracker().new_cross_page()
    members = [
        chain_translation.MemberPlan(
            paragraph=il_version_1.PdfParagraph(),
            tracker=tracker.new_paragraph(),
            translate_input=None,
            source=FIXTURE_TOKEN,
            page_index=index,
        )
        for index in range(2)
    ]
    plan._translate(FIXTURE_TOKEN, members, tracker)
    return stage.translate_engine.prompts[-1]


def declared_note() -> str:
    _, target_lang = fixture_direction()
    return translation_style.load_style_config().note_for(target_lang)


def check_02a_the_policy_is_declared_with_its_vocabulary() -> None:
    """Positive 2a: the switch is bounded, and every probe outside it refused."""
    faults = []
    raw = load_json(STYLE_CONFIG)
    vocabulary = raw.get(translation_style.VOCABULARY_KEY)
    if not isinstance(vocabulary, list) or len(vocabulary) < 2:
        faults.append("no vocabulary of at least two values is declared")
    if raw.get(translation_style.POLICY_KEY) not in (vocabulary or []):
        faults.append("the selected policy is outside its own vocabulary")
    if translation_style.POLICY_KEEP_SOURCE not in (vocabulary or []):
        faults.append("the vocabulary does not offer the way back")

    def probe(label: str, mutate) -> None:
        broken = copy.deepcopy(raw)
        mutate(broken)
        path = _tmp_root / f"style_{label}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(broken, f)
        try:
            translation_style.load_style_config(str(path))
        except translation_style.TranslationStyleError:
            return
        faults.append(f"{label}: accepted")

    probe(
        "outside_vocabulary",
        lambda config: config.__setitem__(translation_style.POLICY_KEY, "nonsense"),
    )
    probe(
        "no_vocabulary",
        lambda config: config.pop(translation_style.VOCABULARY_KEY),
    )
    probe(
        "no_entries",
        lambda config: config[translation_style.NOTES_KEY].__setitem__(
            translation_style.ENTRIES_KEY, {}
        ),
    )
    probe("unknown_key", lambda config: config.__setitem__("person_names_extra", 1))

    # Every direction the corpus declares has to have a role text to be stated
    # in, or the policy is undeliverable for a registered sample.
    policy = translation_style.load_style_config()
    for entry in registry_entries():
        try:
            policy.note_for(entry[corpus.DIRECTION_FIELDS[1]])
        except translation_style.TranslationStyleError:
            faults.append(f"{entry['file']}: no role text for its target language")
    record(
        "check_02a_the_policy_is_declared_with_its_vocabulary",
        not faults,
        "; ".join(faults[:5]),
    )


def check_02b_all_three_prompt_builders_carry_it() -> None:
    """Positive 2b: the page batch, the merged chain and the orphan retry.

    The third is the one PLAN B9.1's named channel could not reach: a batch
    that fails is retried a paragraph at a time through ``ILTranslator``, whose
    prompt has no article brief in it and never did.
    """
    note = declared_note()
    faults = []

    stage = _stage("coverage", custom_system_prompt=note)
    if note not in _batch_prompt(stage):
        faults.append("the page batch prompt does not carry it")
    if note not in _chain_prompt(stage):
        faults.append("the merged chain prompt does not carry it")
    # The object the fallback submits to, reached the way the fallback reaches
    # it, so a rename on that path fails here.
    if note not in stage.il_translator._build_role_block():
        faults.append("the orphan retry prompt does not carry it")

    # A batch belonging to no article carries no brief and still carries this.
    without_brief = _batch_prompt(stage, article_brief=None)
    if note not in without_brief:
        faults.append("a batch with no article brief does not carry it")
    record(
        "check_02b_all_three_prompt_builders_carry_it", not faults, "; ".join(faults)
    )


def check_02c_the_three_layers_are_ordered_where_the_model_reads_it() -> None:
    """Positive 2c: default, brief and ruling in one prompt, precedence stated."""
    note = declared_note()
    _, target_lang = fixture_direction()
    glossary = Glossary(
        "ruled",
        [GlossaryEntry(FIXTURE_TOKEN, FIXTURE_RULED, target_lang)],
    )
    stage = _stage("layers", custom_system_prompt=note, glossaries=[glossary])
    brief = f"{FIXTURE_TOKEN} -> {FIXTURE_SUGGESTED}"
    prompt = _batch_prompt(stage, text=FIXTURE_TOKEN, article_brief=brief)

    faults = []
    for label, token in (
        ("the default", note),
        ("the brief suggestion", FIXTURE_SUGGESTED),
        ("the ruled rendering", FIXTURE_RULED),
    ):
        if token not in prompt:
            faults.append(f"{label} is absent from a prompt holding all three")
    # The two sections the role text defers to have to be the sections the
    # prompt actually has, or the deferral names nothing.
    for section in (GLOSSARY_SECTION, HINTS_SECTION):
        if section not in prompt:
            faults.append(f"the prompt has no {section} section to defer to")
        if section.lower() not in note.lower():
            faults.append(f"the role text does not defer to {section}")
    # Stated for every declared target language, not only the fixture's.
    policy = translation_style.load_style_config()
    for tag in policy.notes:
        text = policy.note_for(tag).lower()
        for section in (GLOSSARY_SECTION, HINTS_SECTION):
            if section.lower() not in text:
                faults.append(f"{tag}: does not defer to {section}")
    record(
        "check_02c_the_three_layers_are_ordered_where_the_model_reads_it",
        not faults,
        "; ".join(faults[:5]),
    )


def check_02d_keep_source_writes_nothing() -> None:
    """Negative 2d: the way back is an empty slot, not a milder instruction."""
    policy = translation_style.load_style_config()
    off = dataclasses.replace(policy, person_names=translation_style.POLICY_KEEP_SOURCE)
    _, target_lang = fixture_direction()
    faults = []
    if translation_style.system_prompt(target_lang, policy=off) is not None:
        faults.append("a system prompt was composed under the policy that states none")

    plain = _stage("keep_source_plain")
    applied = _stage("keep_source_applied")
    written = translation_style.apply(applied.translation_config, target_lang, off)
    if written is not None:
        faults.append(f"apply wrote {written!r}")
    if applied.translation_config.custom_system_prompt is not None:
        faults.append("the slot was written to")
    if _batch_prompt(plain) != _batch_prompt(applied):
        faults.append("the prompt is not byte for byte the one built without a policy")
    # And the same run under the shipped policy does differ, or the comparison
    # above would pass for a policy that reaches nothing.
    on = _stage("keep_source_control")
    translation_style.apply(on.translation_config, target_lang, policy)
    if _batch_prompt(on) == _batch_prompt(plain):
        faults.append("the shipped policy changes no prompt")
    record("check_02d_keep_source_writes_nothing", not faults, "; ".join(faults))


def check_02e_a_callers_own_system_prompt_is_kept() -> None:
    """Positive 2e: a caller's voice is stated first and never overwritten.

    Nothing in this project sets one today. The assertion is here so that the
    first thing that does is not silently overruled by a default.
    """
    policy = translation_style.load_style_config()
    _, target_lang = fixture_direction()
    carried = "Keep every sentence under twenty words."
    composed = translation_style.system_prompt(target_lang, carried, policy)
    note = policy.note_for(target_lang)
    faults = []
    if composed is None or carried not in composed:
        faults.append("the caller's own system prompt was dropped")
    elif note not in composed:
        faults.append("the policy was dropped")
    elif composed.index(carried) > composed.index(note):
        faults.append("the policy was stated before the caller's own prompt")

    stage = _stage("carried", custom_system_prompt=carried)
    translation_style.apply(stage.translation_config, target_lang, policy)
    prompt = _batch_prompt(stage)
    for label, token in (("the caller's prompt", carried), ("the policy", note)):
        if token not in prompt:
            faults.append(f"{label} did not reach the built prompt")
    record(
        "check_02e_a_callers_own_system_prompt_is_kept", not faults, "; ".join(faults)
    )


# --- 03 the smoke ---------------------------------------------------------------


def evidence() -> dict:
    return load_json(EVIDENCE)


def _has_cjk(text: str) -> bool:
    return any(
        unicodedata.category(char) == "Lo" and ord(char) > 0x2E80 for char in text
    )


def check_03a_the_corrected_direction_produced_the_target_language() -> None:
    """Positive 3a: the reversed sample now comes out in its declared target."""
    data = evidence()
    sample = data.get("samples", {}).get(REVERSED_SAMPLE)
    faults = []
    if sample is None:
        record(
            "check_03a_the_corrected_direction_produced_the_target_language",
            False,
            f"{REVERSED_SAMPLE} is not in the evidence",
        )
        return
    source_lang, target_lang = corpus.direction_of(REVERSED_SAMPLE)
    if sample["direction"] != [source_lang, target_lang]:
        faults.append(
            f"ran as {sample['direction']}, declared {[source_lang, target_lang]}"
        )
    rows = [row for row in sample["comparison"]["paragraphs"] if row["after"].strip()]
    if not rows:
        faults.append("no translated paragraph to look at")
    # The declared target of this sample is written in a Latin script, so a
    # paragraph still carrying the source script is one the direction did not
    # reach. Measured as a majority rather than absolutely: a proper noun or a
    # figure legend may legitimately keep its source form.
    latin = [row for row in rows if not _has_cjk(row["after"])]
    if rows and len(latin) * 2 <= len(rows):
        faults.append(f"{len(latin)}/{len(rows)} paragraphs left the source script")
    moved = [row for row in rows if row["changed"]]
    if rows and not moved:
        faults.append("not one paragraph changed against F1")
    record(
        "check_03a_the_corrected_direction_produced_the_target_language",
        not faults,
        "; ".join(faults[:5]),
    )


def check_03b_the_contents_page_names_moved() -> None:
    """Positive 3b: the page the F1 review faulted renders differently now."""
    data = evidence()
    sample = data.get("samples", {}).get(NAMED_SAMPLE)
    faults = []
    if sample is None:
        record("check_03b_the_contents_page_names_moved", False, "no evidence")
        return
    if data.get("person_names") == translation_style.POLICY_KEEP_SOURCE:
        faults.append("the smoke ran under the policy that changes nothing")
    rows = [row for row in sample["comparison"]["paragraphs"] if row["after"].strip()]
    compared = [row for row in rows if row["before"] is not None]
    if not compared:
        faults.append("nothing to compare against F1")
    changed = [row for row in compared if row["changed"]]
    if compared and not changed:
        faults.append("no paragraph of the contents page changed")
    record("check_03b_the_contents_page_names_moved", not faults, "; ".join(faults[:5]))


def check_03c_the_ruling_outranks_the_default() -> None:
    """Positive 3c: every ruled rendering survived every wording of the default.

    Checked over each round of the wording iteration and not only over the last
    one. The default is a soft layer and its wording was tuned; the ruling is
    the hard guarantee, and a hard guarantee that only happened to hold for the
    wording that shipped would not be one. A round whose evidence is on disk is
    a round this has to hold for.
    """
    faults = []
    sources: list[tuple[str, dict]] = [("final", evidence())]
    sources += [
        (path.stem.replace(".evidence", ""), load_json(path))
        for path in sorted(ITERATION_DIR.glob("round_*.evidence.json"))
    ]
    if len(sources) < 2:
        faults.append("no round evidence, so the iteration is unattested")
    for label, data in sources:
        sample = data.get("samples", {}).get(NAMED_SAMPLE)
        if sample is None:
            faults.append(f"{label}: no evidence for the ruled sample")
            continue
        terms = sample.get("ruling", {}).get("terms", {})
        if not terms:
            faults.append(f"{label}: the sample carries no ruling")
            continue
        for source, row in terms.items():
            if row.get("in_before") and not row.get("in_after"):
                faults.append(f"{label}: {source}: the ruled rendering was lost")
    record(
        "check_03c_the_ruling_outranks_the_default", not faults, "; ".join(faults[:5])
    )


# --- 04 the scope ---------------------------------------------------------------


def check_04a_no_upstream_change() -> None:
    """Negative 4a: this batch changes no upstream file and no ground truth."""
    changed = changed_paths()
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    faults = []
    if upstream:
        faults.append(f"upstream changed: {upstream}")
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    for path in READ_ONLY:
        if (
            path in changed
            and path != corpus.REGISTRY_PATH.relative_to(ROOT).as_posix()
        ):
            faults.append(f"{path} is ground truth and was changed")
    if any(path.startswith("reviews/") for path in changed):
        faults.append("a ruling was edited")
    record("check_04a_no_upstream_change", not faults, "; ".join(faults))


def check_04a2_the_registry_carries_only_the_owners_edit() -> None:
    """Negative 4a2: the machine is absent from the one ground truth file that moved.

    The registry normally may not appear in a batch's diff at all. This batch is
    the declared exception -- the corpus owner added the two direction fields
    and the plan is built on their having done so -- so the assertion is not
    that the file is unchanged but that nothing except those two fields is.
    Every other field of every entry is compared against the previous commit
    byte for byte, which is what says a machine session did not take the
    opportunity to edit something else while the file was open.
    """
    relative = corpus.REGISTRY_PATH.relative_to(ROOT).as_posix()
    if relative not in changed_paths():
        record(
            "check_04a2_the_registry_carries_only_the_owners_edit",
            True,
            "the registry did not move",
        )
        return
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    revision = f"{BATCH_TAG}^" if code == 0 else "HEAD"
    code, before_text = git_text(["show", f"{revision}:{relative}"])
    faults = []
    if code != 0:
        faults.append(f"cannot read {relative} at {revision}")
        record(
            "check_04a2_the_registry_carries_only_the_owners_edit",
            False,
            "; ".join(faults),
        )
        return
    before = {entry["file"]: entry for entry in json.loads(before_text)["entries"]}
    after = {entry["file"]: entry for entry in registry_entries()}
    if set(before) != set(after):
        faults.append(f"the sample set moved: {sorted(set(before) ^ set(after))}")
    for name in sorted(set(before) & set(after)):
        added = sorted(set(after[name]) - set(before[name]))
        removed = sorted(set(before[name]) - set(after[name]))
        if added != sorted(corpus.DIRECTION_FIELDS):
            faults.append(f"{name}: added {added}")
        if removed:
            faults.append(f"{name}: removed {removed}")
        for field in set(before[name]):
            if before[name].get(field) != after[name].get(field):
                faults.append(f"{name}: {field} was rewritten")
    record(
        "check_04a2_the_registry_carries_only_the_owners_edit",
        not faults,
        "; ".join(faults[:5]),
    )


def check_04b_no_language_or_name_literals() -> None:
    """Negative 4b: no language tag and no rendered name is written into the code.

    The gate itself is exempt for the same reason it always is: it builds the
    fixtures the package is measured on and has to name what it builds them
    with. What may not name a language is the package the pipeline runs and the
    drivers that steer it.
    """
    tags = {tag.lower() for tag in corpus.languages()}
    tags |= {tag.lower() for tag in translation_style.load_style_config().notes}
    faults = []
    for relative in SESSION_CODE:
        if relative.startswith("spec_checks/"):
            continue
        tree = ast.parse(source_of(relative))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            )
            and ast.get_docstring(node) is not None
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and node.value.strip().lower() in tags
            ):
                faults.append(f"{relative}:{node.lineno} names {node.value!r}")
    # The declared wording lives in the configuration, never in the module.
    module = source_of("babeldoc/magazine/translation_style.py")
    note = declared_note()
    for sentence in note.split("\n"):
        stripped = sentence.strip()
        if len(stripped) > 20 and stripped in module:
            faults.append("the role wording is written into the module")
            break
    record("check_04b_no_language_or_name_literals", not faults, "; ".join(faults[:5]))


def check_04c_ascii_prose() -> None:
    """Negative 4c: every file this batch adds is ASCII."""
    faults = []
    for relative in (*SESSION_CODE, "configs/translation_style.json"):
        for number, line in enumerate(source_of(relative).splitlines(), start=1):
            if not line.isascii():
                offenders = [
                    unicodedata.name(char, hex(ord(char)))
                    for char in line
                    if not char.isascii()
                ]
                faults.append(f"{relative}:{number} {offenders[:3]}")
    record("check_04c_ascii_prose", not faults, "; ".join(faults[:5]))


def check_04d_registered() -> None:
    """Positive 4d: the plan is in the tree and the standing rule is written down."""
    faults = []
    if not (ROOT / "plans" / "PLAN_B9_1.md").is_file():
        faults.append("the plan is not in the tree")
    context = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for field in corpus.DIRECTION_FIELDS:
        if field not in context:
            faults.append(f"CLAUDE.md does not declare {field}")
    if not SMOKE_DRIVER.is_file():
        faults.append("the smoke driver is not in the tree")
    # The channel this batch used is a coupling to two upstream symbols and is
    # registered as one, since an upstream rename breaks the whole policy.
    upstream = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    if "custom_system_prompt" not in upstream:
        faults.append("the coupling registry does not name the channel")
    record("check_04d_registered", not faults, "; ".join(faults))


def check_04e_the_gate_spends_no_credential() -> None:
    """Negative 4e: this gate imports no driver and reads no credential."""
    tree = ast.parse(source_of(f"spec_checks/{Path(__file__).name}"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    faults = [
        f"imports {name}"
        for name in sorted(imported)
        if "openai" in name or name.endswith("run_b9_1_smoke") or name == "run_final"
    ]
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith(suffix)
        ):
            faults.append(f"line {node.lineno} names a credential variable")
    record("check_04e_the_gate_spends_no_credential", not faults, "; ".join(faults))


# --- 05 the sweep ---------------------------------------------------------------


def check_05_sweep() -> None:
    """Positive 5: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_05_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_05_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks = [
        check_01a_manifest_copies_the_registry_verbatim,
        check_01b_the_schema_refuses_a_bad_direction,
        check_01c_every_driver_reads_the_direction_per_sample,
        check_01d_no_constant_direction_reaches_a_translation,
        check_02a_the_policy_is_declared_with_its_vocabulary,
        check_02b_all_three_prompt_builders_carry_it,
        check_02c_the_three_layers_are_ordered_where_the_model_reads_it,
        check_02d_keep_source_writes_nothing,
        check_02e_a_callers_own_system_prompt_is_kept,
        check_03a_the_corrected_direction_produced_the_target_language,
        check_03b_the_contents_page_names_moved,
        check_03c_the_ruling_outranks_the_default,
        check_04a_no_upstream_change,
        check_04a2_the_registry_carries_only_the_owners_edit,
        check_04b_no_language_or_name_literals,
        check_04c_ascii_prose,
        check_04d_registered,
        check_04e_the_gate_spends_no_credential,
        check_05_sweep,
    ]
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(check.__name__, False, f"raised {exc!r}")
    print(f"\nspec_check_b9_1: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
