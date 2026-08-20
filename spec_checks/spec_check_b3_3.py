"""Gate script for batch B3.3 (transport capability profile, coverage metric).

Run from the repository root:

    python spec_checks/spec_check_b3_3.py

Exit code 0 when every assertion in plans/PLAN_B3_3.md passes, 1 otherwise.

Like spec_check_b3 this gate is offline by construction: the credential named
by ``configs/vlm.json`` is removed from this process's environment before the
first assertion runs, so a request shape is observed through an injected client
and never against an endpoint.

The assertion this batch exists for is 02b. A capability that every stored
reply was already produced under carries no information the stored keys do not
already encode, so naming it must leave those keys exactly where they are. The
gate proves that the only way it can be proved: batch-b3.2's client is loaded
out of git, handed batch-b3.2's configuration, and asked for the key it would
have written; the key this batch writes for the shipped configuration has to be
the same bytes. The same technique settles the evaluation tool -- both versions
are run over one corpus and their reports compared -- so "the single point
figures did not move" is a measurement rather than a reading of the diff.

Tiers: assertions 03c to 03e replay the evaluation tool over corpus checkpoints
and belong to the pipeline tier; the rest are static. Assertion 04 is the full
sweep and is suppressed when the runner is already performing one.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import types
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.magazine import prompt_loader  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine import vlm_client  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build:
# every document it asserts on is a stub it builds itself or evidence a
# batch froze, so it answers in seconds to a couple of minutes and runs on
# every batch.
GATE_SET = "fast"

os.environ.pop(vlm_client.load_vlm_config().api_key_env, None)

BATCH_TAG = "batch-b3.3"

# The batch whose stored replies must survive this one, and whose single point
# figures must come back out of the evaluation tool unchanged.
PREVIOUS_TAG = "batch-b3.2"

PYTHON = sys.executable

CLASSIFY_PROMPT = "page_classify_vlm"
CONFIG_PATH = ROOT / "configs" / "vlm.json"
CLIENT_MODULE = "babeldoc/magazine/vlm_client.py"
EVAL_TOOL = "tools/vlm_classify_eval.py"
OUTPUT_DIR = ROOT / "examples" / "output" / "b3_3"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = ("check_03cde_single_point_unchanged",)

# Paths this batch may change, per PLAN_B3_3 negative assertion 6.
ALLOWED_FILES = {CLIENT_MODULE, "configs/vlm.json", EVAL_TOOL, "plans/PLAN_B3_3.md"}
ALLOWED_PREFIXES = ("spec_checks/",)

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

# Markers of a client that reads a rejection and asks again under a different
# contract: a status code it recognises, an exception class it names, or the
# phrasing an endpoint rejects a parameter with. None of them belongs in a
# module whose declared answer to a rejected parameter is to fail.
REPARAMETERISATION_MARKERS = (
    "400",
    "BadRequest",
    "status_code",
    "unsupported_parameter",
    "unsupported parameter",
    "fallback_parameter",
)

# Stands in for a rendered page. Nothing here decodes a PNG; the transport only
# base64s whatever bytes it is handed.
IMAGE = b"\x89PNG\r\n\x1a\n" + b"b3_3-probe-page"

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b3_3_"))
_timer = harness.Timer("spec_check_b3_3")
_tool: types.ModuleType | None = None


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


def git_show(revision: str, path: str) -> bytes:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", "show", f"{revision}:{path}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return proc.stdout


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


def module_from_git(revision: str, relative: str, name: str) -> types.ModuleType:
    """Load one file as it stood at a revision, without writing it anywhere.

    ``__file__`` points at the path the file occupies in the working tree, so a
    module deriving the repository root or a configuration path from its own
    location finds the real one. The module is registered under a name of its
    own, which is what lets a dataclass declared inside it resolve annotations.
    """
    source = git_show(revision, relative).decode("utf-8")
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / relative)
    sys.modules[name] = module
    exec(compile(source, f"{revision}:{relative}", "exec"), module.__dict__)  # noqa: S102
    return module


def module_from_path(relative: str, name: str) -> types.ModuleType:
    """Import a working tree file that is not part of an installed package."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def eval_tool() -> types.ModuleType:
    """The evaluation tool as this batch ships it, imported once."""
    global _tool
    if _tool is None:
        _tool = module_from_path(EVAL_TOOL, "b3_3_vlm_classify_eval")
    return _tool


def canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def classify_prompt() -> prompt_loader.Prompt:
    vocabulary = taxonomy_module.load_taxonomy()
    return prompt_loader.load_prompt(
        CLASSIFY_PROMPT,
        {
            "taxonomy": taxonomy_module.vocabulary_block(vocabulary),
            "deterministic_verdict": "probe verdict",
            "page_context": "probe context",
        },
    )


def valid_reply(kind: str, confidence: float = 0.8) -> str:
    return json.dumps({"kind": kind, "confidence": confidence})


class RecordingClient:
    """Stands in for the endpoint's client and keeps every request body.

    Nothing leaves the process and no credential is read: the transport builds
    this instead of a real client, which is what the constructor seam is for.
    """

    def __init__(self, reply: str) -> None:
        self.bodies: list[dict] = []
        self.chat = types.SimpleNamespace(completions=self)
        self._reply = reply

    def create(self, **body):
        self.bodies.append(body)
        message = types.SimpleNamespace(content=self._reply)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class RejectingTransport:
    """Refuses every request the way an endpoint refuses a parameter it lacks.

    It records the body it was asked for before refusing, so the retry can be
    read for a client that quietly rewrote the request.
    """

    def __init__(self, message: str) -> None:
        self.bodies: list[dict] = []
        self.message = message

    def complete(self, config, prompt: str, image_png: bytes) -> str:
        self.bodies.append(vlm_client.build_request(config, prompt, image_png))
        raise RuntimeError(self.message)


def sent_request(config, reply: str) -> dict:
    """The body the real transport puts on the wire for one configuration."""
    client = RecordingClient(reply)
    transport = vlm_client.OpenAICompatibleTransport(client_factory=lambda _: client)
    transport.complete(config, "probe prompt", IMAGE)
    return client.bodies[-1]


# --- assertions -------------------------------------------------------------


def check_01_request_profile() -> None:
    """The declared capability profile is the shape a request actually takes."""
    config = vlm_client.load_vlm_config()
    names = vlm_client.ENUM_KEYS["token_parameter"]
    reply = valid_reply(taxonomy_module.load_taxonomy().names()[0])

    shapes: dict[str, list[str]] = {}
    problems: list[str] = []
    for name in names:
        body = sent_request(replace(config, token_parameter=name), reply)
        shapes[name] = sorted(key for key in body if key != "messages")
        if body.get(name) != config.max_output_tokens:
            problems.append(f"{name}: the limit is not carried under this name")
        for other in names:
            if other != name and other in body:
                problems.append(f"{name}: the request also carries {other}")
    record(
        "01a the token limit travels under whichever name the profile declares",
        not problems and len(names) == 2 and len(shapes) == len(names),
        f"declared={list(names)} shapes={shapes} problems={problems}",
    )

    absent = sent_request(replace(config, temperature=None), reply)
    present = sent_request(replace(config, temperature=0.25), reply)
    record(
        "01b a null temperature is left out of the request rather than sent",
        "temperature" not in absent
        and present.get("temperature") == 0.25
        and absent["model"] == present["model"] == config.model,
        f"null_keys={sorted(key for key in absent if key != 'messages')} "
        f"set_temperature={present.get('temperature')}",
    )

    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    refusals: dict[str, str] = {}
    probes = (
        ("a third token parameter name", {**raw, "token_parameter": "tokens_please"}),
        ("a temperature outside its range", {**raw, "temperature": 99}),
        (
            "no token parameter at all",
            {key: raw[key] for key in raw if key != "token_parameter"},
        ),
    )
    for label, probe in probes:
        try:
            vlm_client.parse_vlm_config(probe, "probe")
            refusals[label] = ""
        # The shared bounded validator raises the base class, this module's own
        # checks raise its subclass; both are a refusal.
        except vlm_client.ConfigError as exc:
            refusals[label] = str(exc)
    parsed_null = vlm_client.parse_vlm_config({**raw, "temperature": None}, "probe")
    record(
        "01c the profile is a closed declaration and a null temperature is legal",
        all(refusals.values()) and parsed_null.temperature is None,
        f"refusals={ {k: v[:50] for k, v in refusals.items()} } "
        f"null_temperature={parsed_null.temperature}",
    )


def check_02_cache_key() -> None:
    """Naming the profile moves the key only for a configuration that departs."""
    config = vlm_client.load_vlm_config()
    prompt = classify_prompt()
    base = vlm_client.cache_key(config, prompt, IMAGE)

    other = vlm_client.ENUM_KEYS["token_parameter"][1]
    variants = {
        "token_parameter": vlm_client.cache_key(
            replace(config, token_parameter=other), prompt, IMAGE
        ),
        "temperature to null": vlm_client.cache_key(
            replace(config, temperature=None), prompt, IMAGE
        ),
        "temperature to another value": vlm_client.cache_key(
            replace(config, temperature=1.0), prompt, IMAGE
        ),
    }
    unmoved = sorted(label for label, key in variants.items() if key == base)
    record(
        "02a either capability setting, changed, changes the cache key",
        not unmoved and len(set(variants.values())) == len(variants),
        f"unmoved={unmoved} distinct={len(set(variants.values()))} of {len(variants)}",
    )

    previous = module_from_git(PREVIOUS_TAG, CLIENT_MODULE, "b3_2_vlm_client")
    previous_raw = json.loads(
        git_show(PREVIOUS_TAG, "configs/vlm.json").decode("utf-8")
    )
    previous_config = previous.parse_vlm_config(previous_raw, "vlm.json")
    previous_key = previous.cache_key(previous_config, prompt, IMAGE)
    previous_params = canonical(previous_config.key_parameters())
    record(
        "02b the shipped configuration keys exactly as batch-b3.2 keyed it",
        previous_key == base and previous_params == canonical(config.key_parameters()),
        f"params={canonical(config.key_parameters())} then={previous_params} "
        f"key={base[:16]} then={previous_key[:16]}",
    )

    implied = vlm_client.IMPLIED_PARAMETERS
    at_implied = [
        name for name, value in implied.items() if getattr(config, name) == value
    ]
    record(
        "02c a setting at the value stored replies were produced under is elided",
        bool(at_implied)
        and all(name not in config.key_parameters() for name in at_implied)
        and set(implied) <= set(vlm_client.KEY_PARAMETERS),
        f"implied={implied} elided={at_implied} "
        f"key_parameters={sorted(config.key_parameters())}",
    )


def check_03ab_coverage_states() -> None:
    """The label set metric answers each of the three states it can be in."""
    tool = eval_tool()
    names = taxonomy_module.load_taxonomy().names()
    verdict, second, elsewhere = names[0], names[1], names[2]

    states = (
        ("secondary covers a label the verdict misses", second, [second], True, False),
        ("secondary names nothing the page carries", second, [elsewhere], False, False),
        ("no secondary offered", None, [verdict], True, True),
    )
    problems: list[str] = []
    observed: list[str] = []
    for label, secondary, expected, covers, hits in states:
        covered = tool.coverage_hit(verdict, {"secondary_kind": secondary}, expected)
        single = verdict in expected
        gain = covered and not single
        observed.append(f"{label}: coverage={covered} single={single} gain={gain}")
        if covered is not covers or single is not hits:
            problems.append(label)
        if gain is not (covers and not hits):
            problems.append(f"{label}: gain page")

    # A page the fallback never saw has no second candidate to widen it, which
    # is why the deterministic column is the single point column and not a
    # looser one.
    unrouted = tool.coverage_hit(verdict, None, [second])
    record(
        "03a the label set metric is correct in each of its three states",
        not problems and unrouted is False,
        f"states={observed} unrouted_covers_another_label={unrouted} "
        f"problems={problems}",
    )

    record(
        "03b the prediction set is the verdict plus a second candidate, no more",
        tool.predicted_set(verdict, None) == {verdict}
        and tool.predicted_set(verdict, {"secondary_kind": None}) == {verdict}
        and tool.predicted_set(verdict, {"secondary_kind": second})
        == {verdict, second},
        f"unrouted={sorted(tool.predicted_set(verdict, None))} "
        f"pair={sorted(tool.predicted_set(verdict, {'secondary_kind': second}))}",
    )


def check_03cde_single_point_unchanged() -> None:
    """The tool's single point figures are the ones batch-b3.2 reported.

    Both versions are run over the same corpus in this process and their
    reports compared: every section batch-b3.2 wrote must still be there, byte
    for byte, with the coverage columns beside it rather than in it.
    """
    previous_tool = module_from_git(PREVIOUS_TAG, EVAL_TOOL, "b3_2_vlm_classify_eval")
    current_tool = eval_tool()
    old_out = _tmp_root / "eval_previous"
    new_out = _tmp_root / "eval_current"
    codes = (
        previous_tool.main(["--out", str(old_out)]),
        current_tool.main(["--out", str(new_out)]),
    )
    old = json.loads((old_out / previous_tool.REPORT_FILE).read_text(encoding="utf-8"))
    new = json.loads((new_out / current_tool.REPORT_FILE).read_text(encoding="utf-8"))

    # "configuration" states the ablation setting and gains a key by design,
    # and "pages" gains a column per row. Every other section is untouched.
    grown = {"configuration", "pages"}
    differing = sorted(
        key
        for key in set(old) - grown
        if canonical(old[key]) != canonical(new.get(key))
    )
    record(
        "03c every section batch-b3.2 wrote comes back byte for byte the same",
        not differing and codes == (0, 0) and set(old) <= set(new),
        f"sections={sorted(set(old))} differing={differing} exits={codes} "
        f"added={sorted(set(new) - set(old))}",
    )

    changed_rows: list[str] = []
    for before, after in zip(old["pages"], new["pages"], strict=True):
        moved = sorted(
            key
            for key, value in before.items()
            if canonical(after.get(key)) != canonical(value)
        )
        if moved:
            changed_rows.append(f"{before['file']}#{before['page']}: {moved}")
    record(
        "03d every per page single point column keeps the value it had",
        not changed_rows and len(old["pages"]) > 0,
        f"pages={len(old['pages'])} changed={changed_rows[:3]}",
    )

    coverage = new["label_set_coverage"]
    agreement = new["agreement"]
    control = [
        label
        for label in ("deterministic", "routed_pages_deterministic")
        if canonical(coverage[label]) != canonical(agreement[label])
    ]
    looser = sorted(
        key
        for key in coverage["combined"]
        if coverage["combined"][key]["hits"] < agreement["combined"][key]["hits"]
    )
    record(
        "03e the deterministic column is its own control and coverage never loses",
        not control and not looser,
        f"control_columns_equal={not control} "
        f"pooled_single={agreement['combined']['']['hits']}"
        f"/{agreement['combined']['']['total']} "
        f"pooled_coverage={coverage['combined']['']['hits']}"
        f"/{coverage['combined']['']['total']} "
        f"gain_pages={len(coverage['secondary_gain_pages'])}",
    )


def check_04_sweep() -> None:
    """The full sweep is green."""
    name = "04a the full run_all sweep is green"
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


def check_05_no_reparameterisation() -> None:
    """A refused parameter fails the request; it never rewrites it."""
    source = (ROOT / CLIENT_MODULE).read_text(encoding="utf-8")
    retry_path = inspect.getsource(vlm_client.CachedVlmClient.classify)
    names = vlm_client.ENUM_KEYS["token_parameter"]
    markers = sorted(
        marker for marker in REPARAMETERISATION_MARKERS if marker in source
    )
    in_retry = sorted(
        needle
        for needle in (*names, "token_parameter", "temperature")
        if needle in retry_path
    )
    record(
        "05a no refusal is read for a parameter to switch to",
        not markers and not in_retry,
        f"markers={markers} retry_path_mentions={in_retry}",
    )

    config = replace(vlm_client.load_vlm_config(), enabled=True)
    use_project_cache(_tmp_root / "cache_root")
    transport = RejectingTransport(
        f"Error code: 400 - unsupported parameter: {names[0]!r}"
    )
    client = vlm_client.CachedVlmClient(config=config, transport=transport)
    verdict = client.classify(
        classify_prompt(), IMAGE, taxonomy_module.load_taxonomy().names()
    )
    attempted = [
        sorted(key for key in body if key != "messages") for body in transport.bodies
    ]
    record(
        "05b every retry asks for exactly the parameters the profile declares",
        not verdict.accepted
        and len(transport.bodies) == config.max_retries + 1
        and all(names[0] in body for body in transport.bodies)
        and all(names[1] not in body for body in transport.bodies)
        and len({tuple(shape) for shape in attempted}) == 1,
        f"attempts={verdict.attempts} bodies={len(transport.bodies)} "
        f"shapes={attempted} accepted={verdict.accepted}",
    )


def check_06_change_scope() -> None:
    changed = changed_files()
    unexpected = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "06a this batch changes only the paths the plan allows",
        not unexpected and bool(changed),
        f"changed={sorted(changed)} unexpected={unexpected}",
    )

    upstream = sorted(
        path
        for path in changed
        if path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    )
    record(
        "06b this batch touches no upstream file",
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
        "06c no CJK characters in the code this batch changed",
        not cjk and checked > 0,
        f"files={checked} offenders={cjk[:5]}",
    )

    config = vlm_client.load_vlm_config()
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    record(
        "06d this gate ran with the credential removed and the switch off",
        not os.environ.get(config.api_key_env)
        and not config.enabled
        and not raw["enabled"],
        f"variable={config.api_key_env} still_set="
        f"{bool(os.environ.get(config.api_key_env))} enabled={raw['enabled']}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    if not harness.FAST_TIER:
        with _timer.phase("warmup"):
            use_project_cache(ROOT)
            warmup()

    check_01_request_profile()
    check_02_cache_key()
    check_03ab_coverage_states()

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        check_03cde_single_point_unchanged()

    check_05_no_reparameterisation()
    check_06_change_scope()
    check_04_sweep()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b3_3")
    artifacts.print_stats("spec_check_b3_3")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b3_3: {len(_results) - len(failed)}/{len(_results)} passed")
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
