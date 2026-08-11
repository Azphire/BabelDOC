"""Gate script for batch B6 session two (article brief injection).

Run from the repository root:

    python spec_checks/spec_check_b6_2.py

Exit code 0 when every assertion T6.2 answers for passes, 1 otherwise. Needs no
API key and makes no network request: every model call is answered by a stub
that reads its work out of the prompt the stage built, so the real prompt path,
the real batching and the real injection point are all exercised without a
credential.

What the batch adds is one small request per article, made before that
article's paragraphs are translated, whose answer every batch of that article
then carries. So the assertions are about four things and in this order.

01 to 03 are the request: the two templates live in ``prompts/`` and declare
exactly the variables the code supplies, a reply that is not the object it was
asked for is refused rather than guessed at, and the cache that serves a brief
is keyed by the prompt file it came from, so a reworded template cannot be
answered out of replies to the old wording.

04 and 05 are the injection: exactly one request per article that has text to
describe, every batch of an article carrying its brief, chains included, and no
batch of a page belonging to no article carrying anything. 05d is the
degradation -- with every request failing, the sidecar says so for every
article and the document is translated all the same.

06 is the switch. With it down the stage is batch-b6.1's translator byte for
byte, over the same stub and the same checkpoints, and it leaves no sidecar.

07 is the one thing a brief may never do. A brief is a model's reading of one
opening paragraph; the glossary is an authority over terminology. The brief is
consumed by the same request that carries it and reaches nothing else, which is
asserted statically and again over a run.

08 is the change scope, and it carries this session's two maintenance items:
the b6.1 gate's output-tree prefix is now a file list, and every sidecar a
magazine stage writes is declared in the run inventory.

09 is the measurement tool, on documents built so the answer is known. 10 is
the full sweep, suppressed when the runner is already performing one.

Tiers: 05, 06b, 06c and 07b need pipeline artefacts and belong to the pipeline
tier; everything else is static or synthetic.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine import article_context as context_module  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import sidecar_names  # noqa: E402
from babeldoc.magazine.prompt_loader import file_digest  # noqa: E402
from babeldoc.magazine.prompt_loader import load_prompt  # noqa: E402
from babeldoc.magazine.prompt_loader import prompt_path  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# The commit this session starts from, and what the switch-down comparison is
# made against: with the context down this is that translator, byte for byte.
BASE_TAG = "batch-b6.1"
BATCH_TAG = "batch-b6.2"

PYTHON = sys.executable

MODULE = "babeldoc/magazine/article_context.py"
CHAIN_MODULE = "babeldoc/magazine/chain_translation.py"
TOOL = "tools/term_consistency.py"
CONFIG = "configs/article_context.json"
TOOL_CONFIG = "configs/term_consistency.json"
STAGE_CONFIG = "configs/checkpoint_stages.json"
TRANSLATOR = "babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py"
B6_GATE = "spec_checks/spec_check_b6.py"
OUTPUT_DIR = ROOT / "examples" / "output" / "b6_2"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = (
    "check_05_stub_corpus",
    "check_06b_switch_down",
    "check_06c_no_sidecar",
    "check_07b_glossary_untouched",
)

# Paths this session may change, named file by file under the output tree for
# the reason assertion 08d states.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "prompts/",
    "tools/",
    "spec_checks/",
    "plans/",
)
ALLOWED_FILES = {
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
    "examples/output/b6/article_grouping.report.md",
    "examples/output/b6_smoke/brief_injection.report.md",
}

# The two upstream files T6.2 allows. The third PLAN_B6 names, high_level.py, is
# not touched this session: the brief pass hangs off the translation stage.
ALLOWED_UPSTREAM = {TRANSLATOR, "babeldoc/format/pdf/translation_config.py"}

# The upstream functions this session changed, each of which UPSTREAM_DIFF.md
# has to name in a row of its own.
UPSTREAM_SYMBOLS = (
    "ILTranslatorLLMOnly.translate",
    "ILTranslatorLLMOnly.process_cross_page_paragraph",
    "ILTranslatorLLMOnly.process_cross_column_paragraph",
    "ILTranslatorLLMOnly.process_page",
    "ILTranslatorLLMOnly.translate_paragraph",
    "ILTranslatorLLMOnly._build_llm_prompt",
    "TranslationConfig.__init__",
)

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

CJK_SCAN_FILES = (MODULE, TOOL, CONFIG, TOOL_CONFIG, "spec_checks/spec_check_b6_2.py")
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# The three templates and the variables each declares. Written here because the
# assertion is about the contract between the templates and the code: a
# variable renamed on one side and not the other is exactly what this catches.
# The names line is a template of its own so that a brief stating no name can
# leave it out; the condition is at the call site, not in a template language.
BRIEF_VARIABLES = ("title_paragraph", "first_body_excerpt", "target_language")
CONTEXT_VARIABLES = ("title_translation", "register", "names_block")
NAMES_VARIABLES = ("names",)

# What the stub puts in a brief so that a prompt carrying one is recognisable.
BRIEF_MARK = "ZQBRIEFMARK"

# Libraries that reach a network. The brief pass may import none of them: it is
# a model call point that borrows the run's engine rather than opening anything.
NETWORK_LIBRARIES = ("openai", "requests", "httpx", "urllib", "http", "socket")

# What the stub puts in front of a translation, and where the batch begins in a
# prompt. Both as batch-b5's stub has them: six characters clear the edit
# distance fallback, and a request with no input header is a brief request.
MARKER = "zzzzz "
INPUT_HEADER = "## Here is the input:"
STUB_TOKEN_FLOOR = 10
STUB_MAX_QPS = 16

# Synthetic page kinds and the policy each stands for, as batch-b6.1's gate has
# them: the walk is driven from a policy this file controls, so the assertions
# state the rule rather than the corpus.
KIND_OPENS = "synthetic_opens"
KIND_MEMBER = "synthetic_member"
KIND_FURNITURE = "synthetic_furniture"

SYNTHETIC_POLICY = {
    KIND_OPENS: {"opens_article": True, "chain_eligible": True, "translate": True},
    KIND_MEMBER: {"opens_article": False, "chain_eligible": True, "translate": True},
    KIND_FURNITURE: {
        "opens_article": False,
        "chain_eligible": False,
        "translate": True,
    },
}

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b6_2_"))
_timer = harness.Timer("spec_check_b6_2")


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    detail = detail.encode("ascii", "backslashreplace").decode("ascii")
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


def skip(name: str, detail: str) -> None:
    print(f"SKIPPED: {detail} :: {name}")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def tag_exists(tag: str) -> bool:
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{tag}^{{commit}}"])
    return code == 0


def changed_files() -> set[str]:
    """Every path this session changed, anchored on its tag once it exists."""
    if tag_exists(BATCH_TAG):
        _, listing = git_output(["diff", "--name-only", BASE_TAG, BATCH_TAG])
        return {line.strip() for line in listing.splitlines() if line.strip()}

    _, listing = git_output(["diff", "--name-only", BASE_TAG])
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


def read_checkpoint(path: Path) -> il_version_1.Document:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return XMLConverter().read_xml(str(path))


def sample_pdfs() -> list[Path]:
    manifest = corpus.load_manifest()
    return [ROOT / "examples" / "input" / e["file"] for e in manifest["samples"]]


def code_strings(path: Path) -> set[str]:
    """Every string constant a module uses in code, docstrings excluded."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def module_literal(path: Path, name: str):
    """One module level literal, read without importing the module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise KeyError(f"{path.name} declares no {name}")


class WorkingDir:
    """The whole of what the plan asks a translation config for."""

    def __init__(self, directory: Path, lang_out: str = "zh"):
        self.directory = directory
        self.lang_out = lang_out
        directory.mkdir(parents=True, exist_ok=True)

    def get_working_file_path(self, name: str) -> str:
        return str(self.directory / name)


class MemoryCache:
    """A cache with the two methods the client uses, and a call count."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.reads = 0
        self.writes = 0

    def get(self, key: str):
        self.reads += 1
        return self.store.get(key)

    def set(self, key: str, value: str) -> None:
        self.writes += 1
        self.store[key] = value


class RecordingTransport:
    """A transport that answers every brief the same way and counts the asking."""

    def __init__(self, reply: str | None = None, fail: bool = False):
        self.calls: list[str] = []
        self.fail = fail
        self.reply = reply if reply is not None else stub_brief_reply()

    def complete(self, prompt_text: str) -> str:
        self.calls.append(prompt_text)
        if self.fail:
            raise RuntimeError("the endpoint refused the request")
        return self.reply


def stub_brief_reply(index: int = 0) -> str:
    return json.dumps(
        {
            "title_translation": f"{BRIEF_MARK}-title-{index}",
            "register": f"{BRIEF_MARK}-register-{index}",
            "names": [
                {
                    context_module.NAME_SOURCE_FIELD: f"{BRIEF_MARK}-source",
                    context_module.NAME_TARGET_FIELD: f"{BRIEF_MARK}-rendering",
                }
            ],
        }
    )


# --- 01 the templates ---------------------------------------------------------


def check_01_templates() -> None:
    """Positive 1: the prompts live in files and declare what the code supplies."""
    declared: dict[str, tuple[str, ...]] = {}
    missing: list[str] = []
    for name, expected in (
        (context_module.BRIEF_PROMPT, BRIEF_VARIABLES),
        (context_module.CONTEXT_PROMPT, CONTEXT_VARIABLES),
        (context_module.NAMES_PROMPT, NAMES_VARIABLES),
    ):
        path = prompt_path(name)
        if not path.is_file():
            missing.append(name)
            continue
        prompt = load_prompt(name, dict.fromkeys(expected, "x"))
        declared[name] = prompt.variables
    record(
        "01a every template exists and declares exactly the variables the code supplies",
        not missing
        and set(declared.get(context_module.BRIEF_PROMPT, ())) == set(BRIEF_VARIABLES)
        and set(declared.get(context_module.CONTEXT_PROMPT, ()))
        == set(CONTEXT_VARIABLES)
        and set(declared.get(context_module.NAMES_PROMPT, ())) == set(NAMES_VARIABLES),
        f"missing={missing} declared={ {k: sorted(v) for k, v in declared.items()} }",
    )

    work = WorkingDir(_tmp_root / "manifest")
    for name, expected in (
        (context_module.BRIEF_PROMPT, BRIEF_VARIABLES),
        (context_module.CONTEXT_PROMPT, CONTEXT_VARIABLES),
        (context_module.NAMES_PROMPT, NAMES_VARIABLES),
    ):
        load_prompt(name, dict.fromkeys(expected, "x"), working_dir=work.directory)
    manifest = json.loads(
        (work.directory / "prompts.manifest.json").read_text(encoding="utf-8")
    )
    wrong = [
        name
        for name in (
            context_module.BRIEF_PROMPT,
            context_module.CONTEXT_PROMPT,
            context_module.NAMES_PROMPT,
        )
        if manifest.get(f"prompts/{name}.md") != file_digest(prompt_path(name))
    ]
    record(
        "01b loading a template records its SHA-256 in the run manifest",
        not wrong,
        f"entries={sorted(manifest)} wrong={wrong}",
    )

    # Nothing composes the text of either request in code. The templates are the
    # only place the wording lives, so the module carries no sentence of it.
    source = (ROOT / MODULE).read_text(encoding="utf-8")
    borrowed = [
        line.strip()
        for name in (
            context_module.BRIEF_PROMPT,
            context_module.CONTEXT_PROMPT,
            context_module.NAMES_PROMPT,
        )
        for line in prompt_path(name).read_text(encoding="utf-8").splitlines()
        if len(line.strip()) > 24 and line.strip() in source
    ]
    record(
        "01c no line of any template appears in the code",
        not borrowed,
        f"borrowed={borrowed[:2]}",
    )


# --- 02 the reply contract ----------------------------------------------------


def named(source: str, target: str) -> dict:
    """One entry of the names array, in the shape the template asks for."""
    return {
        context_module.NAME_SOURCE_FIELD: source,
        context_module.NAME_TARGET_FIELD: target,
    }


def check_02_reply_contract() -> None:
    """Positive 2: a reply is the object it was asked for, or it is refused.

    A name is a source-and-rendering pair from batch-b6.3 on. A bare list could
    only say which names occur, and the batch-b6.2 smoke found the engine
    reading such a list as an instruction to leave those names untranslated, so
    the shape the contract enforces is the pair.
    """
    config = context_module.load_context_config()

    accepted = context_module.interpret_reply(
        json.dumps(
            {
                "title_translation": " a title ",
                "register": "a register",
                "names": [
                    named("One", " First "),
                    named(" Two ", "Second"),
                    named("", "nothing"),
                    named("no rendering", "  "),
                ],
            }
        ),
        config,
    )
    record(
        "02a a well formed reply becomes a brief, trimmed and without empties",
        not accepted.failed
        and accepted.brief.title_translation == "a title"
        and [name.as_record() for name in accepted.brief.names]
        == [named("One", "First"), named("Two", "Second")],
        f"brief={None if accepted.failed else accepted.brief.as_record()}",
    )

    fenced = context_module.interpret_reply(
        "```json\n" + stub_brief_reply() + "\n```", config
    )
    record(
        "02b one code fence around the whole reply is peeled off",
        not fenced.failed,
        f"reason={fenced.reason}",
    )

    refusals = {
        "not json": "sorry, here is your brief",
        "not an object": json.dumps(["a", "b"]),
        "missing a field": json.dumps({"title_translation": "t", "register": "r"}),
        "field of the wrong type": json.dumps(
            {"title_translation": 1, "register": "r", "names": []}
        ),
        "names not an array": json.dumps(
            {"title_translation": "t", "register": "r", "names": "One"}
        ),
        "a name that is not an object": json.dumps(
            {"title_translation": "t", "register": "r", "names": ["One"]}
        ),
        "a name that is the old bare form": json.dumps(
            {"title_translation": "t", "register": "r", "names": [1]}
        ),
        "a name missing its rendering": json.dumps(
            {
                "title_translation": "t",
                "register": "r",
                "names": [{context_module.NAME_SOURCE_FIELD: "One"}],
            }
        ),
        "a name whose rendering is not a string": json.dumps(
            {"title_translation": "t", "register": "r", "names": [named("One", 1)]}
        ),
    }
    accepted_wrongly = [
        label
        for label, reply in refusals.items()
        if not context_module.interpret_reply(reply, config).failed
    ]
    record(
        "02c a reply that is not the object it was asked for is refused",
        not accepted_wrongly,
        f"accepted={accepted_wrongly}",
    )

    long = context_module.interpret_reply(
        json.dumps(
            {
                "title_translation": "t" * (config.max_title_translation_chars + 50),
                "register": "r" * (config.max_register_chars + 50),
                "names": [
                    named(
                        "s" * (config.max_name_chars + 20),
                        "t" * (config.max_name_chars + 20),
                    )
                    for _ in range(config.max_names + 10)
                ],
            }
        ),
        config,
    )
    record(
        "02d an over-long field is cut to its declared bound rather than refused",
        not long.failed
        and len(long.brief.title_translation) == config.max_title_translation_chars
        and len(long.brief.register) == config.max_register_chars
        and len(long.brief.names) == config.max_names
        and all(
            len(name.source) == config.max_name_chars
            and len(name.suggested_translation) == config.max_name_chars
            for name in long.brief.names
        ),
        f"title={len(long.brief.title_translation) if not long.failed else 0}",
    )

    # The rendering the brief states reaches the batch as a pair, arrow and
    # all: a batch that was given only the source form is the batch-b6.2
    # defect this micro batch exists to remove.
    work = WorkingDir(_tmp_root / "rendering")
    plan = context_module.ArticleContextPlan(
        work,
        client=context_module.CachedBriefClient(
            transport=RecordingTransport(), cache=MemoryCache(), identity="gate"
        ),
        policy_of=SYNTHETIC_POLICY.get,
    )
    rendered = plan._context_text(accepted.brief)
    record(
        "02e a stated rendering reaches the batch beside the name it renders",
        f"One{context_module.NAME_ARROW}First" in rendered
        and f"Two{context_module.NAME_ARROW}Second" in rendered,
        f"line={[line for line in rendered.splitlines() if 'One' in line][:1]}",
    )

    # An article with no name to render receives no sentence about names. What
    # the block says when there is one to render is unchanged, so the block a
    # brief with names carries is the block it carried before.
    bare = context_module.ArticleBrief(
        title_translation=accepted.brief.title_translation,
        register=accepted.brief.register,
        names=(),
    )
    without = plan._context_text(bare)
    names_template = prompt_path(context_module.NAMES_PROMPT).read_text(
        encoding="utf-8"
    )
    first_line = names_template.splitlines()[0].strip()
    record(
        "02f a brief stating no name renders the block without the names line",
        first_line not in without
        and first_line in rendered
        and bare.title_translation in without
        and bare.register in without
        and not without.endswith("\n"),
        f"tail={without.splitlines()[-1][:60]!r}",
    )


# --- 03 the cache -------------------------------------------------------------


def check_03_cache() -> None:
    """Positive 3: one request per distinct prompt, keyed by the file behind it."""
    cache = MemoryCache()
    transport = RecordingTransport()
    client = context_module.CachedBriefClient(
        transport=transport, cache=cache, identity="gate"
    )
    prompt = load_prompt(
        context_module.BRIEF_PROMPT, dict.fromkeys(BRIEF_VARIABLES, "x")
    )
    first = client.brief(prompt)
    second = client.brief(prompt)
    record(
        "03a the same request twice over costs one call into the transport",
        len(transport.calls) == 1
        and not first.failed
        and not second.failed
        and second.from_cache
        and not first.from_cache,
        f"calls={len(transport.calls)} from_cache={second.from_cache}",
    )

    # The key names the file a request came from, so a reworded template cannot
    # be answered out of replies written for the old wording.
    reworded = context_module.Prompt(
        name=prompt.name,
        path=prompt.path,
        digest="0" * 64,
        text=prompt.text,
        variables=prompt.variables,
    )
    retexted = context_module.Prompt(
        name=prompt.name,
        path=prompt.path,
        digest=prompt.digest,
        text=prompt.text + " one more sentence",
        variables=prompt.variables,
    )
    keys = {
        client.cache_key(prompt),
        client.cache_key(reworded),
        client.cache_key(retexted),
    }
    other = context_module.CachedBriefClient(
        transport=transport, cache=cache, identity="another engine"
    )
    record(
        "03b the key separates prompt file, rendered text and engine",
        len(keys) == 3 and other.cache_key(prompt) not in keys,
        f"distinct={len(keys)}",
    )

    failing = RecordingTransport(fail=True)
    empty = MemoryCache()
    refused = context_module.CachedBriefClient(
        transport=failing, cache=empty, identity="gate"
    ).brief(prompt)
    record(
        "03c a failed request yields no brief and is never cached",
        refused.failed
        and empty.writes == 0
        and context_module.REASON_TRANSPORT in refused.reason,
        f"reason={refused.reason[:60]} writes={empty.writes}",
    )

    watched = MemoryCache()
    bypass = context_module.CachedBriefClient(
        transport=RecordingTransport(), cache=watched, identity="gate", ignore_cache=True
    )
    bypass.brief(prompt)
    bypass.brief(prompt)
    record(
        "03d a run ignoring the translation cache ignores the brief cache too",
        watched.reads == 0 and watched.writes == 0,
        f"reads={watched.reads} writes={watched.writes}",
    )


# --- 04 the synthetic injection ----------------------------------------------


def synthetic_document(kinds: list[str]) -> il_version_1.Document:
    labels = article_builder.title_labels(article_builder.load_grouping_config())
    pages = []
    for index, kind in enumerate(kinds):
        pages.append(
            il_version_1.Page(
                page_number=index,
                page_kind=kind,
                page_kind_conf=1.0,
                pdf_paragraph=[
                    il_version_1.PdfParagraph(
                        debug_id=f"h{index}",
                        layout_label=labels[0],
                        unicode=f"Heading {index}",
                    ),
                    il_version_1.PdfParagraph(
                        debug_id=f"p{index}",
                        layout_label=body_label(),
                        unicode=f"Body text of page {index}.",
                    ),
                ],
            )
        )
    return il_version_1.Document(page=pages)


def body_label() -> str:
    from babeldoc.magazine.chain_signals import load_chain_config

    return load_chain_config()[context_module.BODY_LABELS_KEY][0]


def check_04_synthetic_injection() -> None:
    """Positive 4: one brief per article, carried by its pages and by nobody else."""
    docs = synthetic_document([KIND_OPENS, KIND_MEMBER, KIND_FURNITURE, KIND_OPENS])
    transport = RecordingTransport()
    work = WorkingDir(_tmp_root / "synthetic")
    client = context_module.CachedBriefClient(
        transport=transport, cache=MemoryCache(), identity="gate"
    )
    plan = context_module.ArticleContextPlan(
        work, client=client, policy_of=SYNTHETIC_POLICY.get
    )
    context = plan.plan(docs)
    report = json.loads(
        (work.directory / context_module.REPORT_NAME).read_text(encoding="utf-8")
    )

    record(
        "04a one request per article, and one brief per request",
        len(transport.calls) == 2
        and report["counts"]["articles"] == 2
        and report["counts"]["briefs"] == 2
        and report["counts"]["requests"] == 2,
        f"calls={len(transport.calls)} counts={report['counts']}",
    )

    carried = [bool(context.brief_for_page(page)) for page in docs.page]
    record(
        "04b every page of an article carries a brief and no other page does",
        carried == [True, True, False, True],
        f"carried={carried}",
    )

    record(
        "04c a pair straddling two articles carries none",
        bool(context.brief_for_page_pair(docs.page[0], docs.page[1]))
        and not context.brief_for_page_pair(docs.page[1], docs.page[3])
        and not context.brief_for_page_pair(docs.page[1], docs.page[2]),
        "",
    )

    opens = [context.opens_article(page) for page in docs.page]
    labels = article_builder.title_labels(article_builder.load_grouping_config())
    record(
        "04d the context declares where an article opens and what a heading is",
        opens == [True, False, False, True]
        and context.declares_titles
        and context.title_labels == labels,
        f"opens={opens} labels={context.title_labels}",
    )

    # An article with nothing to describe is not asked about, and says so.
    empty = synthetic_document([KIND_OPENS])
    for paragraph in empty.page[0].pdf_paragraph:
        paragraph.unicode = ""
    quiet = RecordingTransport()
    quiet_work = WorkingDir(_tmp_root / "synthetic_empty")
    context_module.ArticleContextPlan(
        quiet_work,
        client=context_module.CachedBriefClient(
            transport=quiet, cache=MemoryCache(), identity="gate"
        ),
        policy_of=SYNTHETIC_POLICY.get,
    ).plan(empty)
    quiet_report = json.loads(
        (quiet_work.directory / context_module.REPORT_NAME).read_text(encoding="utf-8")
    )
    record(
        "04e an article with no text to describe is not asked about, and is recorded",
        not quiet.calls
        and quiet_report["counts"]["requested"] == 0
        and quiet_report["articles"][0]["brief_failed"]
        and quiet_report["articles"][0]["reason"] == context_module.REASON_NO_SOURCE,
        f"calls={len(quiet.calls)} counts={quiet_report['counts']}",
    )


# --- stub driven runs of the translation stage -------------------------------


_TOKENIZER = None


def tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        import tiktoken

        _TOKENIZER = tiktoken.encoding_for_model("gpt-4o")
    return _TOKENIZER


def pseudo_translate(text: str) -> str:
    if len(tokenizer().encode(text, disallowed_special=())) > STUB_TOKEN_FLOOR:
        return MARKER + text
    return text


def build_stub_translator(brief_fails: bool = False):
    """An engine answering both kinds of request without leaving the machine.

    A request carrying no input header is a brief request: it is the batch
    template that ends with one, so the two are told apart by the shape of what
    the stage built rather than by a flag the gate passes in.
    """
    from babeldoc.translator.translator import BaseTranslator

    class StubTranslator(BaseTranslator):
        name = "b62-stub"

        def __init__(self):
            super().__init__("en", "zh", ignore_cache=True)
            self.batch_prompts: list[str] = []
            self.brief_prompts: list[str] = []

        def do_translate(self, text, rate_limit_params: dict = None):
            return pseudo_translate(text)

        def do_llm_translate(self, text, rate_limit_params: dict = None):
            if text is None:
                return None
            if INPUT_HEADER not in text:
                self.brief_prompts.append(text)
                if brief_fails:
                    raise RuntimeError("the endpoint refused the brief request")
                return stub_brief_reply(len(self.brief_prompts))
            self.batch_prompts.append(text)
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

    def __init__(self, name, document, config, engine, batches, writes):
        self.name = name
        self.document = document
        self.config = config
        self.engine = engine
        self.batches = batches
        self.writes = writes

    def xml(self) -> str:
        return XMLConverter().to_xml(self.document)

    def sidecar(self, name: str):
        path = Path(self.config.get_working_file_path(name))
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
    article_context: bool,
    chain_translate: bool = True,
    revision: str | None = None,
    brief_fails: bool = False,
) -> StubRun:
    """Run the translation stage over one checkpoint with the stub engine.

    Every batch is recorded with the paragraphs it held and the brief it was
    given, which is the injection point itself rather than a reading of the
    prompt; the prompts the stub collected are what the reading is done on.
    """
    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator
    from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel
    from babeldoc.format.pdf.translation_config import TranslationConfig
    from babeldoc.progress_monitor import ProgressMonitor
    from babeldoc.translator.translator import set_translate_rate_limiter

    set_translate_rate_limiter(STUB_MAX_QPS)
    stage_class = load_translator_class(revision)
    document = read_checkpoint(checkpoint)
    monitor = ProgressMonitor([(stage_class.stage_name, 1.0)])
    monitor.disable = True
    work = _tmp_root / "stub" / label
    work.mkdir(parents=True, exist_ok=True)
    config = TranslationConfig(
        translator=build_stub_translator(brief_fails=brief_fails),
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
        magazine_article_context=article_context,
    )
    stage = stage_class(config.translator, config)

    batches: list[dict] = []
    writes: list[str] = []
    lock = threading.Lock()
    original_batch = stage_class.translate_paragraph
    original_write = ILTranslator.post_translate_paragraph

    def watched_batch(self, batch_paragraph, *args, **kwargs):
        with lock:
            batches.append(
                {
                    "debug_ids": [
                        paragraph.debug_id for paragraph in batch_paragraph.paragraphs
                    ],
                    "brief": kwargs.get("article_brief"),
                }
            )
        return original_batch(self, batch_paragraph, *args, **kwargs)

    def counted(self, paragraph, tracker, translate_input, translated_text):
        with lock:
            writes.append(paragraph.debug_id)
        return original_write(self, paragraph, tracker, translate_input, translated_text)

    stage_class.translate_paragraph = watched_batch
    ILTranslator.post_translate_paragraph = counted
    try:
        stage.translate(document)
    finally:
        stage_class.translate_paragraph = original_batch
        ILTranslator.post_translate_paragraph = original_write
    return StubRun(label, document, config, config.translator, batches, writes)


def chained_checkpoints() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for pdf in sample_pdfs():
        built = artifacts.get_artifacts(pdf, "chained")
        checkpoint = built.working_dir / f"{checkpoint_stem('chain_builder')}.xml"
        if checkpoint.exists():
            found.append((pdf.stem, checkpoint))
    return found


_stub_runs: dict[str, dict[str, StubRun]] = {}


def stub_runs() -> dict[str, dict[str, StubRun]]:
    """Four runs of every sample: the baseline, the switch down, up, and failing."""
    if _stub_runs:
        return _stub_runs
    for name, checkpoint in chained_checkpoints():
        _stub_runs[name] = {
            "baseline": run_stub(
                checkpoint, f"{name}.baseline", False, revision=BASE_TAG
            ),
            "off": run_stub(checkpoint, f"{name}.off", False),
            "on": run_stub(checkpoint, f"{name}.on", True),
            "failing": run_stub(
                checkpoint, f"{name}.failing", True, brief_fails=True
            ),
        }
    return _stub_runs


def page_of(document, debug_id: str) -> int | None:
    for index, page in enumerate(document.page):
        for paragraph in page.pdf_paragraph:
            if paragraph.debug_id == debug_id:
                return index + 1
    return None


# --- 05 the corpus under the stub ---------------------------------------------


def check_05_stub_corpus() -> None:
    """Positive 5: on real documents, exactly the members of an article carry it."""
    counts: list[str] = []
    membership: list[str] = []
    prompts: list[str] = []
    chains: list[str] = []
    degraded: list[str] = []
    table: list[dict] = []

    for name, variants in stub_runs().items():
        run = variants["on"]
        report = run.sidecar(context_module.REPORT_NAME)
        if report is None:
            counts.append(f"{name}: no sidecar")
            continue
        requested = [row for row in report["articles"] if row["requested"]]
        if len(run.engine.brief_prompts) != len(requested):
            counts.append(
                f"{name}: {len(run.engine.brief_prompts)} request(s) for "
                f"{len(requested)} article(s)"
            )
        if report["counts"]["requests"] != len(requested):
            counts.append(f"{name}: the sidecar counts a different number of requests")

        held = {
            page: row["article_id"]
            for row in report["articles"]
            for page in row["pages"]
        }
        with_brief = {
            row["article_id"] for row in report["articles"] if not row["brief_failed"]
        }
        for batch in run.batches:
            pages = {
                page_of(run.document, debug_id) for debug_id in batch["debug_ids"]
            }
            owners = {held.get(page) for page in pages}
            carried = batch["brief"] is not None
            if owners == {None}:
                if carried:
                    membership.append(f"{name}: a batch outside every article carried one")
                continue
            if len(owners) == 1 and owners <= with_brief:
                if not carried:
                    membership.append(
                        f"{name}: a batch of {sorted(owners)} carried none"
                    )
            elif carried and not owners <= with_brief:
                membership.append(f"{name}: a batch of {sorted(owners)} carried one")

        marked_batches = sum(
            1 for batch in run.batches if batch["brief"] is not None
        )
        chain_report = run.sidecar("chain_translation.report.json") or {}
        merged = chain_report.get("chains", [])
        chain_with_brief = 0
        for entry in merged:
            page = entry["members"][0]["page_index"] + 1
            if held.get(page) in with_brief:
                chain_with_brief += 1
        marked_prompts = sum(
            1 for prompt in run.engine.batch_prompts if BRIEF_MARK in prompt
        )
        if marked_prompts != marked_batches + chain_with_brief:
            prompts.append(
                f"{name}: {marked_prompts} prompt(s) carry the brief for "
                f"{marked_batches} batch(es) and {chain_with_brief} chain(s)"
            )
        if merged and chain_with_brief == 0 and with_brief:
            chains.append(f"{name}: no merged chain fell inside an article with a brief")

        failing = variants["failing"]
        failing_report = failing.sidecar(context_module.REPORT_NAME)
        if failing_report is None:
            degraded.append(f"{name}: the failing run wrote no sidecar")
        else:
            still_briefed = [
                row["article_id"]
                for row in failing_report["articles"]
                if not row["brief_failed"]
            ]
            marks = [p for p in failing.engine.batch_prompts if BRIEF_MARK in p]
            if still_briefed or marks:
                degraded.append(f"{name}: a brief survived a failing transport")
            if sorted(failing.writes) != sorted(variants["off"].writes):
                degraded.append(
                    f"{name}: {len(failing.writes)} paragraph(s) written against "
                    f"{len(variants['off'].writes)} with the switch down"
                )

        table.append(
            {
                "sample": name,
                "articles": report["counts"]["articles"],
                "requested": report["counts"]["requested"],
                "briefs": report["counts"]["briefs"],
                "brief_requests": len(run.engine.brief_prompts),
                "batches": len(run.batches),
                "batches_with_brief": marked_batches,
                "prompts_with_brief": marked_prompts,
                "merged_chains": len(merged),
                "chains_with_brief": chain_with_brief,
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "brief_injection.corpus.json").write_text(
        json.dumps(table, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    record(
        "05a exactly one brief request per article that has text to describe",
        not counts and bool(table),
        f"samples={len(table)} problems={counts[:3]}",
    )
    record(
        "05b a batch of an article carries its brief and a batch outside one does not",
        not membership,
        f"problems={membership[:3]}",
    )
    record(
        "05c every batch given a brief sends it, and no other prompt carries one",
        not prompts and sum(row["prompts_with_brief"] for row in table) > 0,
        f"problems={prompts[:3]}",
    )
    record(
        "05d a merged chain inside an article carries that article's brief",
        not chains and sum(row["chains_with_brief"] for row in table) > 0,
        f"chains={sum(row['chains_with_brief'] for row in table)} problems={chains[:2]}",
    )
    record(
        "05e a failing transport leaves no brief and translates the document anyway",
        not degraded,
        f"problems={degraded[:3]}",
    )


# --- 06 the switch ------------------------------------------------------------


def check_06a_switch() -> None:
    """Negative 6a: the switch exists and defaults to off."""
    import inspect

    from babeldoc.format.pdf.translation_config import TranslationConfig

    parameter = inspect.signature(TranslationConfig.__init__).parameters.get(
        "magazine_article_context"
    )
    source = (ROOT / TRANSLATOR).read_text(encoding="utf-8")
    gated = re.search(
        r"if self\.translation_config\.magazine_article_context:\s*\n"
        r"\s*article_context = plan_article_context\(",
        source,
    )
    record(
        "06a the switch exists, defaults to False, and is the only way in",
        parameter is not None
        and parameter.default is False
        and gated is not None
        and source.count("plan_article_context(") == 1,
        f"default={parameter.default if parameter else 'absent'} gated={bool(gated)}",
    )


def check_06b_switch_down() -> None:
    """Negative 6b: with the switch down this is batch-b6.1's translator."""
    differing = [
        name
        for name, variants in stub_runs().items()
        if variants["off"].xml() != variants["baseline"].xml()
    ]
    record(
        "06b with the switch down the document matches batch-b6.1 byte for byte",
        not differing and bool(stub_runs()),
        f"samples={len(stub_runs())} differing={differing}",
    )


def check_06c_no_sidecar() -> None:
    """Negative 6c: with the switch down nothing is asked and nothing is written."""
    wrote = [
        name
        for name, variants in stub_runs().items()
        if variants["off"].sidecar(context_module.REPORT_NAME) is not None
    ]
    asked = [
        name
        for name, variants in stub_runs().items()
        if variants["off"].engine.brief_prompts
    ]
    carried = [
        name
        for name, variants in stub_runs().items()
        if any(batch["brief"] is not None for batch in variants["off"].batches)
    ]
    record(
        "06c with the switch down no request is made and no sidecar appears",
        not wrote and not asked and not carried,
        f"sidecars={wrote} requests={asked} batches={carried}",
    )


# --- 07 the glossary is never written -----------------------------------------


def check_07a_glossary_untouched_statically() -> None:
    """Negative 7a: the brief module knows nothing about the glossary."""
    source = (ROOT / MODULE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    imports = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "glossar" in line.lower()
    ]
    touched = sorted(
        name
        for name in attributes | names
        if "glossar" in name.lower() or "shared_context" in name.lower()
    )
    record(
        "07a the brief module names no glossary and no shared translation context",
        not imports and not touched,
        f"imports={imports} names={touched}",
    )

    # The brief pass is a model call point, and spec_check_b2 declares it as
    # one; what keeps that declaration from being a hole is that it opens no
    # transport of its own. The engine already configured for the run is the
    # only way out of this module.
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    record(
        "07c the brief module opens no transport of its own",
        not modules & set(NETWORK_LIBRARIES),
        f"network={sorted(modules & set(NETWORK_LIBRARIES))}",
    )


def check_07b_glossary_untouched() -> None:
    """Negative 7b: over a run, no glossary and no extracted term moves."""
    problems: list[str] = []
    checked = 0
    for name, variants in stub_runs().items():
        run = variants["on"]
        shared = run.config.shared_context_cross_split_part
        checked += 1
        if shared.auto_extracted_glossary is not None:
            problems.append(f"{name}: an automatic glossary appeared")
        if shared.raw_extracted_terms:
            problems.append(
                f"{name}: {len(shared.raw_extracted_terms)} term pair(s) were added"
            )
        if shared.user_glossaries:
            problems.append(f"{name}: a user glossary appeared")
        # A brief carries names, and a glossary table in a prompt is how a
        # glossary would show itself; the stub configures none, so none may
        # appear whatever a brief said.
        if any("Glossary Tables" in prompt for prompt in run.engine.batch_prompts):
            problems.append(f"{name}: a glossary table reached a prompt")
    record(
        "07b no glossary and no extracted term pair is written by a brief run",
        not problems and checked > 0,
        f"samples={checked} problems={problems[:3]}",
    )


# --- 08 the change scope ------------------------------------------------------


def check_08_scope() -> None:
    """Negative 8: the session stays inside its scope, with its two maintenance items."""
    changed = changed_files()
    outside = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES
        and path not in ALLOWED_UPSTREAM
        and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "08a this session changes only the paths PLAN_B6 allows",
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
    missing_symbols = [
        symbol
        for symbol in UPSTREAM_SYMBOLS
        if f"`{symbol}`" not in registry and symbol not in registry
    ]
    record(
        "08b the upstream files touched are the two allowed, every function registered",
        set(upstream) <= ALLOWED_UPSTREAM
        and not unregistered
        and not missing_symbols,
        f"upstream={upstream} unregistered={unregistered} symbols={missing_symbols}",
    )

    # Neither the brief module nor the tool names a page type or a layout label:
    # both vocabularies arrive through configuration.
    vocabulary = set(taxonomy_module.load_taxonomy().names())
    from babeldoc.magazine.chain_signals import load_chain_config

    chain_config = load_chain_config()
    labels = set(chain_config["endpoint_labels"]) | set(chain_config["body_labels"])
    named = [
        f"{relative}: {value}"
        for relative in (MODULE, TOOL)
        for value in code_strings(ROOT / relative)
        if value in vocabulary or value in labels
    ]
    record(
        "08c neither the brief module nor the tool names a page type or a label",
        not named,
        f"named={named}",
    )

    # T6.2.0a: the b6.1 gate no longer admits the whole output tree by prefix.
    gate_path = ROOT / B6_GATE
    prefixes = tuple(module_literal(gate_path, "ALLOWED_PREFIXES"))
    files = set(module_literal(gate_path, "ALLOWED_FILES"))
    record(
        "08d the b6.1 gate admits output paths file by file, not by prefix",
        not any(prefix.startswith("examples/") for prefix in prefixes)
        and any(path.startswith("examples/output/") for path in files),
        f"prefixes={list(prefixes)} files={sorted(files)}",
    )

    # T6.2.0b: every sidecar a magazine stage writes is in the run inventory.
    declared = set(sidecar_names())
    produced = set()
    for path in sorted((ROOT / "babeldoc" / "magazine").glob("*.py")):
        try:
            produced.add(module_literal(path, "REPORT_NAME"))
        except KeyError:
            continue
    record(
        "08e every sidecar a magazine stage writes is declared in the run inventory",
        produced <= declared and article_builder.REPORT_NAME in declared,
        f"produced={sorted(produced)} undeclared={sorted(produced - declared)}",
    )

    cjk: list[str] = []
    for relative in CJK_SCAN_FILES:
        path = ROOT / relative
        if not path.is_file():
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if has_cjk(line):
                cjk.append(f"{relative}:{number}")
    _, diff = git_output(["diff", "-U0", BASE_TAG, "--", *sorted(ALLOWED_UPSTREAM)])
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++") and has_cjk(line):
            cjk.append(f"added upstream line: {line.strip()}")
    record(
        "08f no CJK characters in the code this session adds",
        not cjk,
        f"offenders={cjk[:5]}",
    )

    # The brief is consumed, never stored: the schema is frozen and the sidecar
    # is the only place an article level fact may land.
    schema = (ROOT / "babeldoc/format/pdf/document_il/il_version_1.xsd").read_text(
        encoding="utf-8"
    )
    record(
        "08g the brief stays out of the intermediate language schema",
        "brief" not in schema.lower() and "article" not in schema.lower(),
        "",
    )


# --- 09 the measurement tool --------------------------------------------------


def measurement_run(sources: list[str], targets: list[str]):
    """A run object over one synthetic article, source and translation given."""
    import tools.term_consistency as tool

    label = body_label()
    page = il_version_1.Page(
        page_number=0,
        page_kind=KIND_OPENS,
        page_kind_conf=1.0,
        pdf_paragraph=[
            il_version_1.PdfParagraph(
                debug_id=f"p{index}", layout_label=label, unicode=text
            )
            for index, text in enumerate(sources)
        ],
    )
    document = il_version_1.Document(page=[page])
    return tool, tool.Run(
        label="synthetic",
        working_dir=_tmp_root,
        source=document,
        target_text={f"p{index}": text for index, text in enumerate(targets)},
    )


def check_09_measurement() -> None:
    """Positive 9: the metric answers what it is built to answer."""
    from babeldoc.magazine.chain_signals import load_chain_config

    chain_config = load_chain_config()
    labels = tuple(chain_config["body_labels"])
    terminals = tuple(chain_config["terminal_punctuation"])

    tool, _ = measurement_run([], [])
    config = tool.load_config()
    # Three renderings and a stretch of filler, all built from code points so
    # that this file stays ASCII, and all disjoint so that a substring shared
    # between two translations can only be a shared rendering.
    rendering = "".join(map(chr, (0x8FBE, 0x5C14, 0x6587)))
    other = "".join(map(chr, (0x53E6, 0x5916, 0x8BD1)))
    third = "".join(map(chr, (0x7B2C, 0x4E09, 0x7A2E)))
    filler = "".join(map(chr, range(0x9000, 0x9000 + 60)))

    term = "Darfur Valley"
    sources = [
        "The city of Darfur Valley was quiet. Reports from Darfur Valley say so.",
        "Later, Darfur Valley grew. The people of Darfur Valley agreed.",
        "Nobody in Darfur Valley disagreed with Darfur Valley at all.",
    ]
    consistent = [rendering + filler[:20] for _ in sources]
    _, consistent_run = measurement_run(sources, consistent)
    rows = tool.measure_article(
        consistent_run, [0], labels, terminals, config, glossary_terms=None
    )
    same = next((row for row in rows if row["term"] == term), None)
    record(
        "09a a term rendered one way throughout scores 1.0",
        same is not None and same["consistency"] == 1.0 and same["occurrences"] >= 3,
        f"row={same}",
    )

    scattered = [
        rendering + filler[0:20],
        other + filler[20:40],
        third + filler[40:60],
    ]
    _, run = measurement_run(sources, scattered)
    split_rows = tool.measure_article(
        run, [0], labels, terminals, config, glossary_terms=None
    )
    split = next((row for row in split_rows if row["term"] == term), None)
    record(
        "09b a term rendered three ways over three paragraphs scores 1/3",
        split is not None and abs(split["consistency"] - 1 / 3) < 1e-9,
        f"row={split}",
    )

    # A word capitalised only because a sentence opened with it never qualifies,
    # however often it occurs.
    openers = [
        "Reports say so. Reports again. Reports once more.",
        "Reports still. Reports yet again. Reports finally.",
    ]
    _, quiet = measurement_run(openers, [filler[0:20], filler[20:40]])
    opener_rows = tool.measure_article(
        quiet, [0], labels, terminals, config, glossary_terms=None
    )
    record(
        "09c a word capitalised only at a sentence opening never qualifies",
        not any(row["term"] == "Reports" for row in opener_rows),
        f"terms={[row['term'] for row in opener_rows]}",
    )

    hits = tool.measure_article(
        consistent_run,
        [0],
        labels,
        terminals,
        config,
        glossary_terms={term.casefold()},
    )
    covered = next((row for row in hits if row["term"] == term), None)
    record(
        "09d the glossary column is reported beside the measurement, never inside it",
        covered is not None
        and covered["in_glossary"] is True
        and covered["consistency"] == same["consistency"]
        and all(row["in_glossary"] is None for row in rows),
        f"row={covered}",
    )

    # Markup is not text. A style tag shared by every translation was winning
    # the candidate column under every setting of the batch-b6.3 tuning grid;
    # it is taken out of the translation before candidates are generated, and
    # what is measured is unchanged by that.
    tag = "<style id='1'>"
    marked = [
        tag + text[: len(text) // 2] + "</style>" + "{v1}" + text[len(text) // 2 :]
        for text in consistent
    ]
    cleaned = [tool.strip_markup(text) for text in marked]
    _, dirty_run = measurement_run(sources, cleaned)
    dirty_rows = tool.measure_article(
        dirty_run, [0], labels, terminals, config, glossary_terms=None
    )
    dirty = next((row for row in dirty_rows if row["term"] == term), None)
    record(
        "09e markup is stripped before candidates are generated, and only that",
        all(tag not in text and "{v1}" not in text for text in cleaned)
        and all(len(text) > 0 for text in cleaned)
        and dirty is not None
        and dirty["consistency"] == same["consistency"]
        and dirty["candidate"] is not None
        and "<" not in dirty["candidate"],
        f"row={dirty} cleaned={cleaned[0][:24]!r}",
    )


# --- 10 sweep -----------------------------------------------------------------


def check_10_sweep() -> None:
    name = "10 the full run_all sweep is green"
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

    check_01_templates()
    check_02_reply_contract()
    check_03_cache()
    check_04_synthetic_injection()
    check_06a_switch()
    check_07a_glossary_untouched_statically()
    check_09_measurement()

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        with _timer.phase("stub runs"):
            stub_runs()
        check_05_stub_corpus()
        check_06b_switch_down()
        check_06c_no_sidecar()
        check_07b_glossary_untouched()

    check_08_scope()
    check_10_sweep()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b6_2")
    artifacts.print_stats("spec_check_b6_2")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b6_2: {len(_results) - len(failed)}/{len(_results)} passed")
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
