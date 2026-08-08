"""Gate script for batch B3 (prompt infrastructure, cached client, fallback).

Run from the repository root:

    python spec_checks/spec_check_b3.py

Exit code 0 when every assertion in plans/PLAN_B3.md passes, 1 otherwise.

The gate needs no API key and makes no network request, and that is a property
it enforces rather than assumes: the credential named by ``configs/vlm.json`` is
removed from this process's environment before anything else runs, so every
model call here reaches an injected transport that counts what it was asked.
Any assertion that came to depend on a real reply would fail rather than pass
quietly, which is the only arrangement under which "the gates are offline" stays
true as the model call points multiply.

Covered are the T3.0 backlog (00) and every PLAN_B3 assertion. Assertions 2, 4
and 5 exercise the classifier stage itself, driving it over the checkpoints the
corpus builds produce; 6 is the full sweep and is suppressed when the runner is
already performing one.

Tiers: assertions 2, 4 and 5 need a corpus artefact and belong to the pipeline
tier; the rest are static.
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
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine import page_features  # noqa: E402
from babeldoc.magazine import prompt_loader  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine import vlm_client  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.page_classifier import REPORT_NAME  # noqa: E402
from babeldoc.magazine.page_classifier import SOURCE  # noqa: E402
from babeldoc.magazine.page_classifier import VLM_SOURCE  # noqa: E402
from babeldoc.magazine.page_classifier import PageClassifier  # noqa: E402
from babeldoc.translator import cache as translator_cache  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402
from spec_checks import run_all as runner  # noqa: E402

# The credential is removed before the first assertion runs, so this gate is
# offline by construction rather than by the accident of an unset variable on
# the machine it happens to run on. Child processes inherit the cleared
# environment, which extends the same guarantee to the nested sweep.
os.environ.pop(vlm_client.load_vlm_config().api_key_env, None)

# The batch spans two sessions and therefore two commits. The scope assertions
# read the whole batch: from the parent of the first tag to the second one, or
# to the working tree while the second is still unwritten.
FIRST_TAG = "batch-b3.1"
BATCH_TAG = "batch-b3.2"

PYTHON = sys.executable

CLASSIFY_PROMPT = "page_classify_vlm"
CONFIG_PATH = ROOT / "configs" / "vlm.json"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
LABELS_PATH = ROOT / "corpus" / "page_labels.json"
INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output" / "b3"

# The batch the disabled run must still be equal to, and the agreement table it
# froze, as (kind hits, labelled pages) keyed by publication with the empty key
# holding the pooled figure. Recomputed here from artefacts this batch's code
# produced: if the fallback layer leaked into a disabled run, or a threshold
# moved, this table is where it shows.
PREVIOUS_TAG = "batch-b2.7"
FROZEN_AGREEMENT = {
    "": (28, 31),
    "aramcoworld": (6, 8),
    "cern_courier": (3, 4),
    "imf_fd": (8, 8),
    "unesco_courier": (8, 8),
    "vogue_us": (3, 3),
}

# Set by spec_checks/run_all.py. The sweep assertion is the fallback for running
# this file on its own; under the runner it would repeat the sweep in progress.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Checks that need an artefact built during this run.
PIPELINE_TIER = (
    "check_02_reply_classes",
    "check_04_disabled_run",
    "check_05_routed_pages",
)

# Files this session adds or rewrites whose text must stay free of page type
# names: the vocabulary reaches a prompt by injection from the JSON alone.
VOCABULARY_FREE_FILES = (
    "babeldoc/magazine/page_classifier.py",
    "babeldoc/magazine/prompt_loader.py",
    "babeldoc/magazine/vlm_client.py",
    "babeldoc/magazine/taxonomy.py",
    "configs/vlm.json",
    "prompts/page_classify_vlm.md",
    "prompts/vlm_retry_notice.md",
    "spec_checks/spec_check_b3.py",
    "tools/vlm_classify_eval.py",
)

# Path prefixes and root documents this batch may change, per PLAN_B3 negative
# assertion 9.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "prompts/",
    "spec_checks/",
    "tools/",
)
ALLOWED_FILES = {"CLAUDE.md", "WAIVERS.md", "plans/PLAN_B3.md"}

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

# Documents whose prose is Chinese by design; the CJK scan covers code only.
CJK_SCAN_SUFFIXES = (".py", ".json")
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# Credential shapes. Each needs a run of key characters after its prefix, so the
# patterns do not match their own source text.
CREDENTIAL_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"(?i)(api[_\-]?key|authorization|bearer)[\"'\s:=]+[A-Za-z0-9_\-]{24,}"),
)

# Suffixes the credential scan reads. Everything else in the working tree is
# either binary or generated.
SCANNED_SUFFIXES = (".py", ".json", ".md", ".toml", ".xsd", ".rnc", ".rng", ".txt")

# A count of gates, calls or runs written into prose goes stale the moment a
# gate is added and nothing fails, so the shared artefact docstring may not
# carry one in either digits or words.
COUNT_PHRASE = re.compile(
    r"(?i)\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|dozen)"
    r"\s+(?:gates?|calls?|pairs?|samples?|runs?|sixths?|modes?)\b"
)

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b3_"))
_timer = harness.Timer("spec_check_b3")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


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
    """Every path this batch changed, across both of its sessions.

    The base is the commit the batch started from. The head is the tag that
    closes it once it exists, and the working tree until then, so the same
    assertion holds while the second session is in progress and after a later
    batch has moved on.
    """
    base = f"{FIRST_TAG}^" if tag_exists(FIRST_TAG) else "HEAD"
    if tag_exists(BATCH_TAG):
        _, listing = git_output(["diff", "--name-only", base, BATCH_TAG])
        return {line.strip() for line in listing.splitlines() if line.strip()}

    _, tracked = git_output(["diff", "--name-only", base])
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


def git_show(revision: str, path: str) -> bytes:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", "show", f"{revision}:{path}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def normalized(payload: bytes) -> bytes:
    """Line-ending normalised bytes, so a checkout convention is not a change."""
    return payload.replace(b"\r\n", b"\n")


def classifier_checkpoint(working_dir: Path) -> Path:
    stem = checkpoint_module.checkpoint_stem("page_classifier")
    return working_dir / f"{stem}.xml"


@dataclass(frozen=True)
class RoutedSample:
    """The corpus sample the routing assertions replay, and what it routes."""

    name: str
    sample: Path
    checkpoint: Path
    count: int


def pick_routed_sample(classified: dict[str, Path], manifest: dict) -> RoutedSample:
    """The sample with the most ambiguous pages, which routes the most work.

    Ambiguity is a property of the corpus rather than of this gate, so the
    sample is chosen by measurement instead of being named here; a retune that
    moves which pages are ambiguous moves the choice with it.
    """
    file_of = {
        Path(sample["file"]).stem: sample["file"] for sample in manifest["samples"]
    }
    best: RoutedSample | None = None
    for name, working in sorted(classified.items()):
        report = json.loads((working / REPORT_NAME).read_text(encoding="utf-8"))
        count = sum(entry["ambiguous"] for entry in report["pages"])
        if best is None or count > best.count:
            best = RoutedSample(
                name=name,
                sample=INPUT_DIR / file_of[name],
                checkpoint=classifier_checkpoint(working),
                count=count,
            )
    return best


class WorkingDirConfig:
    """The whole of ``TranslationConfig`` the classifier stage actually reads.

    Driving the stage from a checkpoint instead of a pipeline run is what makes
    the routing assertions affordable: the corpus is built once for the sweep,
    and each reply class replays the stage over it in milliseconds.
    """

    def __init__(self, working_dir: Path, input_file: Path) -> None:
        self.working_dir = working_dir
        self.input_file = input_file

    def get_working_file_path(self, filename: str) -> Path:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return self.working_dir / filename


def run_stage(
    sample: Path,
    checkpoint: Path,
    working: Path,
    replies,
    enabled: bool = True,
) -> tuple[object, dict, StubTransport]:
    """Replay the classifier stage over one checkpoint against scripted replies.

    Each call gets a database of its own, so one reply class never answers the
    next one from the cache.
    """
    use_project_cache(working / "cache_root")
    transport = StubTransport(replies)
    config = replace(vlm_client.load_vlm_config(), enabled=enabled)
    client = vlm_client.CachedVlmClient(
        config=config, transport=transport, working_dir=working
    )
    docs = checkpoint_module.load_checkpoint(checkpoint)
    stage = PageClassifier(WorkingDirConfig(working, sample), vlm_client=client)
    stage.process(docs)
    report = json.loads((working / REPORT_NAME).read_text(encoding="utf-8"))
    return docs, report, transport


def scannable_files() -> list[Path]:
    """Tracked and untracked working tree files the credential scan reads."""
    _, tracked = git_output(["ls-files"])
    _, untracked = git_output(["ls-files", "--others", "--exclude-standard"])
    seen: dict[str, Path] = {}
    for line in (*tracked.splitlines(), *untracked.splitlines()):
        relative = line.strip()
        if not relative:
            continue
        path = ROOT / relative
        if path.is_file() and path.suffix in SCANNED_SUFFIXES:
            seen[relative] = path
    return [seen[key] for key in sorted(seen)]


class StubTransport:
    """A transport that answers from a script and counts what it was asked.

    Nothing leaves the process. A scripted entry that is an exception is raised
    instead of returned, which is how a failed request is exercised without one.
    """

    def __init__(self, replies) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, config, prompt: str, image_png: bytes) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        reply = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


def valid_reply(kind: str, confidence: float = 0.8) -> str:
    return json.dumps({"kind": kind, "confidence": confidence})


def fenced_reply(kind: str, tag: str = "json") -> str:
    """A contract-abiding answer wrapped in the code fence chat models add."""
    return f"```{tag}\n{valid_reply(kind)}\n```"


def load_classify_prompt(
    directory: Path | None = None, working_dir: Path | None = None
) -> prompt_loader.Prompt:
    vocabulary = taxonomy_module.load_taxonomy()
    return prompt_loader.load_prompt(
        CLASSIFY_PROMPT,
        {
            "taxonomy": taxonomy_module.vocabulary_block(vocabulary),
            "deterministic_verdict": "probe verdict",
            "page_context": "probe context",
        },
        working_dir=working_dir,
        directory=directory,
    )


def fresh_client(transport: StubTransport, config=None) -> vlm_client.CachedVlmClient:
    return vlm_client.CachedVlmClient(
        config=vlm_client.load_vlm_config() if config is None else config,
        transport=transport,
    )


# --- assertions -------------------------------------------------------------


def check_00_backlog() -> None:
    """The T3.0 maintenance items hold."""
    inert = ROOT / "configs" / "gate_cache.json"
    steering = ROOT / "configs" / "page_features.json"
    inert_bytes, steering_bytes = inert.read_bytes(), steering.read_bytes()
    inert_config = json.loads(inert_bytes)

    before = artifacts.workspace_fingerprint(refresh=True)
    try:
        moved = dict(inert_config)
        moved["gate_cache_max_gb"] = float(moved["gate_cache_max_gb"]) / 2
        inert.write_text(json.dumps(moved, indent=2) + "\n", encoding="utf-8")
        after_inert = artifacts.workspace_fingerprint(refresh=True)
    finally:
        inert.write_bytes(inert_bytes)
    try:
        steering.write_bytes(steering_bytes + b"\n")
        after_steering = artifacts.workspace_fingerprint(refresh=True)
    finally:
        steering.write_bytes(steering_bytes)
    restored = artifacts.workspace_fingerprint(refresh=True)

    record(
        "00a an inert configuration key is outside the workspace fingerprint",
        after_inert == before and restored == before,
        f"file={inert.name} excluded="
        f"{artifacts.FINGERPRINT_EXCLUDED_KEYS.get('configs/gate_cache.json')} "
        f"before={before[:16]} after={after_inert[:16]}",
    )
    record(
        "00b a configuration file that steers a run is still inside it",
        after_steering != before
        and inert.read_bytes() == inert_bytes
        and steering.read_bytes() == steering_bytes,
        f"file={steering.name} before={before[:16]} after={after_steering[:16]}",
    )

    # The client's own configuration is split the same way: what shapes a reply
    # stays in the key, what only shapes delivery does not.
    excluded = set(artifacts.FINGERPRINT_EXCLUDED_KEYS.get("configs/vlm.json", ()))
    steering_keys = {"enabled", "model", *vlm_client.KEY_PARAMETERS, "render_dpi"}
    record(
        "00c the vision configuration keeps its run-steering keys in the key",
        not (excluded & steering_keys) and "base_url" in excluded,
        f"excluded={sorted(excluded)} steering={sorted(steering_keys)}",
    )

    retired = (ROOT / "spec_checks" / "spec_check_b2_5.py").read_text(encoding="utf-8")
    successor = (ROOT / "spec_checks" / "spec_check_b2_7.py").read_text(
        encoding="utf-8"
    )
    record(
        "00d the stale expected-red assertion is retired, its successor intact",
        "EXPECTED_RED" not in retired
        and "05a the full run_all sweep is green" in successor,
        f"expected_red_in_b2_5={'EXPECTED_RED' in retired} "
        f"unconditional_sweep_in_b2_7="
        f"{'05a the full run_all sweep is green' in successor}",
    )

    docstring = artifacts.__doc__ or ""
    counted = sorted(set(COUNT_PHRASE.findall(docstring)))
    digits = sorted(set(re.findall(r"\d+", docstring)))
    record(
        "00e the shared artefact docstring states no count that can go stale",
        not counted and not digits and bool(docstring),
        f"count_phrases={counted} digits={digits}",
    )

    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    # The clause names the IL provenance field it constrains. Spelling that
    # field out here would make this gate a declared consumer of a B1 attribute,
    # which it is not, so the assertion reads the value the clause pins instead.
    clause = '="vlm"'
    record(
        "00f CLAUDE.md carries the vision output constraint",
        clause in claude and "sidecar" in claude,
        f"clause_present={clause in claude}",
    )


def check_01_prompt_loader() -> None:
    """Rendering is strict, and the manifest records what was really loaded."""
    prompt = load_classify_prompt()
    vocabulary = taxonomy_module.load_taxonomy()
    names = vocabulary.names()
    declared = set(prompt.variables)
    remaining = prompt_loader.template_variables(prompt.text)
    record(
        "01a rendering substitutes every declared variable and leaves none behind",
        declared == {"taxonomy", "deterministic_verdict", "page_context"}
        and not remaining
        and "probe verdict" in prompt.text
        and all(name in prompt.text for name in names),
        f"declared={sorted(declared)} unreplaced={list(remaining)} "
        f"injected_names={len(names)}",
    )

    template = "head {alpha} tail {beta}"
    failures = {}
    for label, variables in (
        ("missing", {"alpha": "a"}),
        ("undeclared", {"alpha": "a", "beta": "b", "gamma": "c"}),
        ("planted", {"alpha": "{beta}", "beta": "{alpha}"}),
    ):
        try:
            prompt_loader.render(template, variables, "probe")
            failures[label] = ""
        except prompt_loader.PromptError as exc:
            failures[label] = str(exc)
    record(
        "01b an unsupplied, undeclared or self-substituting variable is refused",
        all(failures.values())
        and "beta" in failures["missing"]
        and "gamma" in failures["undeclared"],
        f"messages={ {k: v[:60] for k, v in failures.items()} }",
    )

    working = _tmp_root / "manifest_run"
    working.mkdir(parents=True, exist_ok=True)
    load_classify_prompt(working_dir=working)
    load_classify_prompt(working_dir=working)
    manifest_path = working / prompt_loader.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    key = prompt_loader.manifest_key(prompt.path)
    recomputed = prompt_loader.file_digest(prompt.path)
    record(
        "01c the manifest records the digest the prompt file actually hashes to",
        manifest.get(key) == recomputed == prompt.digest and len(manifest) == 1,
        f"key={key} entries={len(manifest)} digest={recomputed[:16]}",
    )

    # A second load of a changed file replaces its entry rather than adding one,
    # so the manifest states what the run used and not what it once used.
    edited_dir = _tmp_root / "prompts_edited"
    edited_dir.mkdir(parents=True, exist_ok=True)
    edited = edited_dir / prompt.path.name
    edited.write_bytes(prompt.path.read_bytes() + b"\n")
    load_classify_prompt(directory=edited_dir, working_dir=working)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record(
        "01d a reloaded prompt updates its manifest entry in place",
        len(manifest) == 2
        and manifest[key] == prompt.digest
        and manifest[prompt_loader.manifest_key(edited)]
        == prompt_loader.file_digest(edited),
        f"entries={sorted(manifest)}",
    )


def check_03_cache() -> None:
    """A repeated request costs no call, and every key input moves the key."""
    db_path = use_project_cache(_tmp_root / "cache_root")
    prompt = load_classify_prompt()
    names = taxonomy_module.load_taxonomy().names()
    image = b"\x89PNG\r\n\x1a\n" + b"page-image-bytes"

    transport = StubTransport([valid_reply(names[0])])
    client = fresh_client(transport)
    first = client.classify(prompt, image, names)
    after_first = transport.calls
    second = client.classify(prompt, image, names)
    record(
        "03a a repeated request is served from the cache with no transport call",
        first.accepted
        and second.accepted
        and second.kind == first.kind
        and after_first == 1
        and transport.calls == 1
        and second.from_cache
        and not first.from_cache,
        f"calls_after_first={after_first} calls_after_second={transport.calls} "
        f"kind={second.kind} from_cache={second.from_cache}",
    )

    # A different page is a different request; the cache must not answer it.
    other = client.classify(prompt, image + b"x", names)
    record(
        "03b a different page image is a different request",
        other.accepted and transport.calls == 2 and not other.from_cache,
        f"calls={transport.calls} from_cache={other.from_cache}",
    )

    config = vlm_client.load_vlm_config()
    base = vlm_client.cache_key(config, prompt, image)
    edited_dir = _tmp_root / "prompts_key"
    edited_dir.mkdir(parents=True, exist_ok=True)
    edited = edited_dir / prompt.path.name
    edited.write_bytes(prompt.path.read_bytes() + b" ")
    edited_prompt = load_classify_prompt(directory=edited_dir)
    variants = {
        "prompt file byte": vlm_client.cache_key(config, edited_prompt, image),
        "image bytes": vlm_client.cache_key(config, prompt, image + b"x"),
        "model": vlm_client.cache_key(
            replace(config, model=config.model + "-x"), prompt, image
        ),
        "temperature": vlm_client.cache_key(
            replace(config, temperature=config.temperature + 0.5), prompt, image
        ),
    }
    delivery = {
        "base_url": vlm_client.cache_key(
            replace(config, base_url=config.base_url + "/x"), prompt, image
        ),
        "timeout_seconds": vlm_client.cache_key(
            replace(config, timeout_seconds=config.timeout_seconds + 1), prompt, image
        ),
    }
    unmoved = sorted(label for label, key in variants.items() if key == base)
    moved = sorted(label for label, key in delivery.items() if key != base)
    record(
        "03c every input that can change a reply changes the cache key",
        not unmoved and len(set(variants.values())) == len(variants),
        f"unmoved={unmoved} distinct={len(set(variants.values()))} of {len(variants)}",
    )
    record(
        "03d delivery settings that cannot change a reply leave the key alone",
        not moved,
        f"wrongly_moved={moved} probed={sorted(delivery)}",
    )

    rows = translator_cache._TranslationCache.select().where(
        translator_cache._TranslationCache.translate_engine == vlm_client.ENGINE_NAME
    )
    stored = [row.original_text for row in rows]
    record(
        "03e replies are stored in the project-local database under their own engine",
        db_path.exists()
        and len(stored) == 2
        and base in stored
        and db_path.parts[-3:] == ("examples", "cache", "cache.v1.db"),
        f"db={db_path.name} engine={vlm_client.ENGINE_NAME} rows={len(stored)}",
    )


def check_02_reply_classes(routed: RoutedSample) -> None:
    """Each class of reply lands where the contract says it lands.

    A usable answer is adopted, a fenced one is adopted after the fence is
    peeled off, and everything else -- a name outside the vocabulary, an
    unparseable body, a request that never returned -- is retried once and then
    refused, leaving the deterministic verdict in place with the reason beside
    it in the sidecar.
    """
    names = taxonomy_module.load_taxonomy().names()
    adopted = names[0]
    budget = vlm_client.load_vlm_config().max_retries + 1
    classes = (
        ("02a a reply inside the contract is adopted", valid_reply(adopted), True, ""),
        (
            "02b a reply wrapped in one code fence is adopted",
            fenced_reply(adopted),
            True,
            "",
        ),
        (
            "02c a name outside the vocabulary is retried once and refused",
            valid_reply("a name the vocabulary does not declare"),
            False,
            "is not one of",
        ),
        (
            "02d an unparseable reply is retried once and refused",
            "{ this was never JSON",
            False,
            "not valid JSON",
        ),
        (
            "02e a request that fails is retried once and refused",
            TimeoutError("the stub transport timed out"),
            False,
            "request failed",
        ),
    )

    retry_notices: list[bool] = []
    for index, (name, reply, accept, marker) in enumerate(classes):
        working = _tmp_root / f"class_{index}"
        docs, report, transport = run_stage(
            routed.sample, routed.checkpoint, working, [reply]
        )
        entries = [entry for entry in report["pages"] if entry["vlm"] is not None]
        pages = {page.page_number: page for page in docs.page}
        expected_calls = routed.count * (1 if accept else budget)
        problems: list[str] = []
        if len(entries) != routed.count:
            problems.append(f"routed {len(entries)} of {routed.count}")
        if transport.calls != expected_calls:
            problems.append(f"calls {transport.calls} expected {expected_calls}")
        for entry in entries:
            page = pages[entry["page_number"]]
            outcome = entry["vlm"]
            if outcome["accepted"] is not accept:
                problems.append(
                    f"#{entry['page_number']}: accepted={outcome['accepted']}"
                )
                continue
            if accept:
                if (
                    page.page_kind_source != VLM_SOURCE
                    or page.page_kind != adopted
                    or entry["source"] != VLM_SOURCE
                    or outcome["attempts"] != 1
                ):
                    problems.append(f"#{entry['page_number']}: not adopted whole")
            else:
                if (
                    page.page_kind_source != SOURCE
                    or page.page_kind != entry["kind"]
                    or page.page_kind_conf != entry["conf"]
                    or outcome["attempts"] != budget
                ):
                    problems.append(
                        f"#{entry['page_number']}: deterministic verdict moved"
                    )
                if marker not in outcome["reason"]:
                    problems.append(
                        f"#{entry['page_number']}: reason {outcome['reason'][:60]!r}"
                    )
        if not accept:
            retry_notices.append(
                len(transport.prompts) >= 2
                and transport.prompts[1] != transport.prompts[0]
                and transport.prompts[1].startswith(transport.prompts[0])
            )
        record(
            name,
            not problems,
            f"routed={routed.count} calls={transport.calls} problems={problems[:3]}",
        )

    record(
        "02f a retry states the violation that rejected the previous reply",
        all(retry_notices) and bool(retry_notices),
        f"retried_classes={len(retry_notices)} carried_notice={retry_notices}",
    )


def check_04_disabled_run(classified: dict[str, Path], manifest: dict) -> None:
    """With the switch off the corpus is decided exactly as batch-b2.7 decided it."""
    feature_config = page_features.load_feature_config()
    vocabulary = taxonomy_module.load_taxonomy()
    drift: list[str] = []
    routed: list[str] = []
    pages_seen = 0
    for name, working in sorted(classified.items()):
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(working))
        report = json.loads((working / REPORT_NAME).read_text(encoding="utf-8"))
        if report.get("vlm_enabled"):
            routed.append(f"{name}: report says the fallback ran")
        for page, features, entry in zip(
            docs.page,
            page_features.extract_document_features(docs, feature_config),
            report["pages"],
            strict=True,
        ):
            pages_seen += 1
            verdict = taxonomy_module.classify(features, vocabulary)
            if (
                page.page_kind != verdict.kind
                or page.page_kind_conf != verdict.confidence
                or page.page_kind_source != SOURCE
            ):
                drift.append(f"{name}#{page.page_number}")
            if entry["vlm"] is not None:
                routed.append(f"{name}#{page.page_number}")
    record(
        "04a a disabled run decides every page deterministically and consults nothing",
        not drift and not routed and pages_seen > 0,
        f"pages={pages_seen} drift={drift[:3]} routed={routed[:3]}",
    )

    unchanged = {
        relative: normalized((ROOT / relative).read_bytes())
        == normalized(git_show(PREVIOUS_TAG, relative))
        for relative in ("configs/page_types.json", "configs/page_features.json")
    }
    record(
        "04b the vocabulary those verdicts come from is the one batch-b2.7 shipped",
        all(unchanged.values()),
        f"identical={unchanged} against={PREVIOUS_TAG}",
    )

    labels = corpus_module.normalize_page_labels(
        corpus_module.load_page_labels(LABELS_PATH)
    )
    publication_of = {
        sample["file"]: sample.get("publication", "") for sample in manifest["samples"]
    }
    tallies: dict[str, list[int]] = {}
    misses: list[str] = []
    for file_name, expected_by_page in labels.items():
        working = classified[Path(file_name).stem]
        docs = checkpoint_module.load_checkpoint(classifier_checkpoint(working))
        kinds = {
            str((page.page_number if page.page_number is not None else position) + 1): (
                page.page_kind
            )
            for position, page in enumerate(docs.page)
        }
        tally = tallies.setdefault(publication_of.get(file_name, file_name), [0, 0])
        for page_number, accepted in expected_by_page.items():
            tally[1] += 1
            if kinds.get(page_number) in accepted:
                tally[0] += 1
            else:
                misses.append(f"{file_name}#{page_number}: {kinds.get(page_number)!r}")
    table = {key: (hits, total) for key, (hits, total) in tallies.items()}
    table[""] = (
        sum(hits for hits, _ in table.values()),
        sum(total for _, total in table.values()),
    )
    moved = sorted(
        f"{key or 'overall'}: now={table.get(key)} frozen={FROZEN_AGREEMENT.get(key)}"
        for key in set(table) | set(FROZEN_AGREEMENT)
        if table.get(key) != FROZEN_AGREEMENT.get(key)
    )
    record(
        "04c the agreement of the disabled run is the table batch-b2.7 froze",
        not moved,
        f"overall={table['']} moved={moved[:3]} misses={len(misses)}",
    )


def check_04d_render(manifest: dict) -> None:
    """The produced PDF is still the registered baseline, page for page."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outcomes: list[str] = []
    for entry in manifest["samples"]:
        name = Path(entry["file"]).stem
        with _timer.phase(f"pipeline:parse_only_plain:{name}"):
            built = artifacts.get_artifacts(
                INPUT_DIR / entry["file"], "parse_only_plain"
            )
        produced = OUTPUT_DIR / f"{name}.b3.pdf"
        shutil.copyfile(built.mono_pdf, produced)
        proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
            [
                PYTHON,
                str(ROOT / "tools" / "render_diff.py"),
                str(ROOT / entry["baseline"]["pdf"]),
                str(produced),
                "--out",
                str(_tmp_root / f"rd_{name}"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            outcomes.append(f"{name}: exit={proc.returncode}")
    record(
        "04d the batch leaves the produced PDF identical to the baseline",
        not outcomes and bool(manifest["samples"]),
        f"samples={len(manifest['samples'])} differing={outcomes}",
    )


def check_05_routed_pages(routed: RoutedSample) -> None:
    """With the switch on, exactly the ambiguous pages are adjudicated."""
    names = taxonomy_module.load_taxonomy().names()
    adopted = names[0]
    working = _tmp_root / "routed"
    before = checkpoint_module.load_checkpoint(routed.checkpoint)
    docs, report, transport = run_stage(
        routed.sample, routed.checkpoint, working, [valid_reply(adopted)]
    )

    wrong: list[str] = []
    for page, entry in zip(docs.page, report["pages"], strict=True):
        expected = VLM_SOURCE if entry["ambiguous"] else SOURCE
        if page.page_kind_source != expected:
            wrong.append(f"#{page.page_number}: {page.page_kind_source} != {expected}")
        if entry["ambiguous"] != (entry["vlm"] is not None):
            wrong.append(f"#{page.page_number}: routing does not follow ambiguity")
    adjudicated = sum(page.page_kind_source == VLM_SOURCE for page in docs.page)
    record(
        "05a every ambiguous page is adjudicated and no other page is",
        not wrong and adjudicated == routed.count and transport.calls == routed.count,
        f"sample={routed.name} ambiguous={routed.count} adjudicated={adjudicated} "
        f"calls={transport.calls} wrong={wrong[:3]}",
    )

    pages_before = len(before.page)
    pages_after = len(docs.page)
    paragraphs_before = sum(len(page.pdf_paragraph) for page in before.page)
    paragraphs_after = sum(len(page.pdf_paragraph) for page in docs.page)
    record(
        "05b adjudication conserves pages and paragraphs",
        pages_before == pages_after and paragraphs_before == paragraphs_after,
        f"pages={pages_before}->{pages_after} "
        f"paragraphs={paragraphs_before}->{paragraphs_after}",
    )

    manifest_path = working / prompt_loader.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    template = ROOT / "prompts" / f"{CLASSIFY_PROMPT}.md"
    key = prompt_loader.manifest_key(template)
    record(
        "05c the run records the digest of the prompt it actually sent",
        manifest.get(key) == prompt_loader.file_digest(template),
        f"entries={sorted(manifest)} digest={str(manifest.get(key))[:16]}",
    )


def check_06_sweep() -> None:
    """The full sweep is green and leaves a complete completion marker."""
    names = (
        "06a the full run_all sweep is green",
        "06b the sweep leaves a complete run_all.done.json",
    )
    if NESTED_SUPPRESSED:
        for name in names:
            print(f"SKIPPED: nested run suppressed :: {name}")
        return

    if runner.DONE_PATH.exists():
        runner.DONE_PATH.unlink()
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
        names[0],
        proc.returncode == 0 and not failures,
        f"exit={proc.returncode} failures={failures[:5]}",
    )

    payload: dict = {}
    if runner.DONE_PATH.exists():
        payload = json.loads(runner.DONE_PATH.read_text(encoding="utf-8"))
    missing = sorted(set(runner.DONE_FIELDS) - set(payload))
    timestamps_parse = all(
        isinstance(payload.get(key), str) and bool(datetime.fromisoformat(payload[key]))
        for key in ("started_at", "finished_at")
        if key in payload
    )
    gates_covered = {entry.get("gate") for entry in payload.get("gates", [])} == set(
        runner.GATES
    )
    record(
        names[1],
        not missing
        and payload.get("exit_code") == proc.returncode
        and isinstance(payload.get("elapsed_seconds"), int | float)
        and payload["elapsed_seconds"] > 0
        and timestamps_parse
        and gates_covered,
        f"missing={missing} exit_code={payload.get('exit_code')} "
        f"timestamps_parse={timestamps_parse} gates_covered={gates_covered}",
    )


def check_07_no_page_type_names() -> None:
    """No page type name is spelled out anywhere in the new code or prompts."""
    names = taxonomy_module.load_taxonomy().names()
    patterns = {
        name: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        for name in names
    }
    offenders: list[str] = []
    scanned = 0
    for relative in VOCABULARY_FREE_FILES:
        path = ROOT / relative
        if not path.is_file():
            offenders.append(f"{relative}: missing")
            continue
        scanned += 1
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            offenders.extend(
                f"{relative}:{number} {name}"
                for name, pattern in patterns.items()
                if pattern.search(line)
            )
    record(
        "07a the new code and prompts spell out no page type name",
        not offenders and scanned == len(VOCABULARY_FREE_FILES),
        f"files={scanned} vocabulary={len(names)} offenders={offenders[:5]}",
    )

    # The names reach the prompt by injection instead, from the JSON alone.
    block = taxonomy_module.vocabulary_block(taxonomy_module.load_taxonomy())
    raw = json.loads((ROOT / "configs" / "page_types.json").read_text(encoding="utf-8"))
    declared = [entry["name"] for entry in raw["page_types"]]
    template = (ROOT / "prompts" / f"{CLASSIFY_PROMPT}.md").read_text(encoding="utf-8")
    record(
        "07b the vocabulary reaches the prompt through the taxonomy variable",
        "{taxonomy}" in template
        and all(name in block for name in declared)
        and all(entry["description"] in block for entry in raw["page_types"]),
        f"declared={len(declared)} block_lines={len(block.splitlines())}",
    )


def check_08_no_credentials() -> None:
    """No file carries a credential, and this gate ran without one."""
    hits: list[str] = []
    scanned = 0
    for path in scannable_files():
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            hits.extend(
                f"{path.relative_to(ROOT).as_posix()}:{number}"
                for pattern in CREDENTIAL_PATTERNS
                if pattern.search(line)
            )
    record(
        "08a no working tree file matches a credential pattern",
        not hits and scanned > 0,
        f"files={scanned} patterns={len(CREDENTIAL_PATTERNS)} hits={hits[:5]}",
    )

    config = vlm_client.load_vlm_config()
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    planted = dict(raw)
    planted["api_key"] = "a value that must never be accepted here"
    try:
        vlm_client.parse_vlm_config(planted, "probe")
        refusal = ""
    except vlm_client.VlmError as exc:
        refusal = str(exc)
    record(
        "08b the configuration names an environment variable and refuses a value",
        raw["api_key_env"] == config.api_key_env
        and "api_key" not in raw
        and bool(refusal)
        and "api_key" in refusal,
        f"api_key_env={config.api_key_env} refusal={refusal[:80]!r}",
    )

    # Not an observation about the machine: the variable was removed at import,
    # so this states that everything above ran without one and that the shipped
    # switch is off. An assertion that had come to need a real reply would have
    # failed on the way here rather than reaching this line.
    record(
        "08c this gate ran with the credential removed and the switch off",
        not os.environ.get(config.api_key_env)
        and not config.enabled
        and not raw["enabled"],
        f"variable={config.api_key_env} still_set="
        f"{bool(os.environ.get(config.api_key_env))} enabled={raw['enabled']}",
    )


def check_09_change_scope() -> None:
    changed = changed_files()
    unexpected = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "09a this batch changes only the paths the plan allows",
        not unexpected,
        f"changed={len(changed)} unexpected={unexpected}",
    )

    upstream = sorted(
        path
        for path in changed
        if path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    )
    record(
        "09b this batch touches no upstream file",
        not upstream,
        f"upstream={upstream}",
    )

    cjk: list[str] = []
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
                cjk.append(f"{relative}:{number}")
    record(
        "09c no CJK characters in the code this batch changed",
        not cjk and checked > 0,
        f"files={checked} offenders={cjk[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    if not harness.FAST_TIER:
        with _timer.phase("warmup"):
            use_project_cache(ROOT)
            warmup()
    check_00_backlog()
    check_01_prompt_loader()
    check_03_cache()

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        with MANIFEST_PATH.open(encoding="utf-8") as f:
            manifest = json.load(f)
        classified: dict[str, Path] = {}
        for entry in manifest["samples"]:
            name = Path(entry["file"]).stem
            with _timer.phase(f"pipeline:classified:{name}"):
                built = artifacts.get_artifacts(INPUT_DIR / entry["file"], "classified")
            classified[name] = built.working_dir

        check_04_disabled_run(classified, manifest)
        check_04d_render(manifest)
        routed = pick_routed_sample(classified, manifest)
        check_02_reply_classes(routed)
        check_05_routed_pages(routed)

    check_07_no_page_type_names()
    check_08_no_credentials()
    check_09_change_scope()
    check_06_sweep()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b3")
    artifacts.print_stats("spec_check_b3")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b3: {len(_results) - len(failed)}/{len(_results)} passed")
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
