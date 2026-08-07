"""Gate script for batch B3, session one (prompt infrastructure, cached client).

Run from the repository root:

    python spec_checks/spec_check_b3.py

Exit code 0 when every assertion this session owns passes, 1 otherwise. It
requires no API key and makes no network request: the client is exercised
through an injected transport that counts its calls, which is also how the
cache is proved to serve a repeated request without one.

Covered here are the T3.0 backlog (00) and PLAN_B3 assertions 1, 3, 7, 8 and 9.
Assertions 2, 4, 5 and 6 land with the classifier routing in session two,
because the behaviour they describe -- the fallback to the deterministic verdict
and the byte-for-byte equality of a disabled run -- lives at the call site
rather than in the client.

Every assertion is static tier: nothing here builds a pipeline artefact.
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
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import prompt_loader  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine import vlm_client  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.translator import cache as translator_cache  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Tag that freezes this batch; once it exists the scope assertions read the
# delta it introduced instead of the working tree.
BATCH_TAG = "batch-b3.1"

CLASSIFY_PROMPT = "page_classify_vlm"
CONFIG_PATH = ROOT / "configs" / "vlm.json"

# Files this session adds or rewrites whose text must stay free of page type
# names: the vocabulary reaches a prompt by injection from the JSON alone.
VOCABULARY_FREE_FILES = (
    "babeldoc/magazine/prompt_loader.py",
    "babeldoc/magazine/vlm_client.py",
    "babeldoc/magazine/taxonomy.py",
    "configs/vlm.json",
    "prompts/page_classify_vlm.md",
    "prompts/vlm_retry_notice.md",
    "spec_checks/spec_check_b3.py",
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
ALLOWED_FILES = {"CLAUDE.md", "plans/PLAN_B3.md"}

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


def changed_files() -> set[str]:
    """Every path this batch changed.

    Before the batch is committed that is the working tree delta against HEAD.
    Once the batch is tagged the same delta is the tag against its parent, so a
    later batch can re-run this gate without its own changes counting here.
    """
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^", BATCH_TAG])
        return {line.strip() for line in listing.splitlines() if line.strip()}

    _, listing = git_output(["status", "--porcelain", "--untracked-files=all"])
    paths: set[str] = set()
    for line in listing.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


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

    record(
        "08c this gate ran with no credential in its environment",
        not os.environ.get(config.api_key_env)
        and not config.enabled
        and not raw["enabled"],
        f"variable_set={bool(os.environ.get(config.api_key_env))} "
        f"enabled={raw['enabled']}",
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
    check_00_backlog()
    check_01_prompt_loader()
    check_03_cache()
    check_07_no_page_type_names()
    check_08_no_credentials()
    check_09_change_scope()

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
