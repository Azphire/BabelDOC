"""Gate script for micro batch B9.7 (per kind decision rounds).

Run from the repository root:

    python spec_checks/spec_check_b9_7.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: the batch's one instrument spends a credential and this gate
reads what it froze.

What this batch is. Batch b9.6 reworded the decision request and recovered two
of its four points; the one it did not recover was a single ``out_of_page``
finding sitting seventeenth in a list of forty, most of which were of another
kind. This batch changes the shape of the request rather than its wording: an
iteration asks for its decision one detector kind at a time, so a round carries
the findings of one kind and the actions that answer for it, and the order the
rounds are taken in is declared in ``configs/decision_rounds.json``. The prompt
file is not touched, which is what makes the measurement about the shape alone.

01 is the scope: the delta is the one file of the package this batch may move,
plus configuration, gates and evidence, and no ground truth or ruling.

02 is the newline pin. The digests several gates identify a file by are digests
of its bytes, so a checkout that rewrote its newlines would produce a digest no
frozen record names. ``.gitattributes`` pins the checkout, the working tree is
asserted to hold what the pin declares, and the two digest assertions that
depend on it are recomputed here under it.

03 is the mechanism, which is this batch's whole positive face and is asserted
without a model: what the rounds are, that each carries one kind, that each may
name only the actions answering for its kind, that the order is the declared one
and that it is complete, and that the kind reaches the cache key.

04 is the replay, read off the frozen decisions: the three points that had to
recover, the nineteen finding spectrum that had to not move, and the containment
guard driven through the loop under the new shape.

05 is the record: the report carries the figures the decisions carry.

Tiers: 01, 02, 03 and 05 are static. 04 mixes frozen decisions with two live
stub driven runs of the loop, which spend no credential.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import prompt_loader  # noqa: E402
from babeldoc.magazine.react import actions as orphan_actions  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from spec_checks import harness  # noqa: E402
from spec_checks import spec_check_b9_5 as b95  # noqa: E402

BATCH_TAG = "batch-b9.7"
PREVIOUS_TAG = "batch-b9.6"

ATTRIBUTES = ROOT / ".gitattributes"
DECIDE_PROMPT = ROOT / "prompts" / "react_repair_decide.md"
REPAIR_CONFIG = ROOT / "configs" / "repair_actions.json"
ROUNDS_CONFIG = ROOT / "configs" / "decision_rounds.json"

BATCH_DIR = ROOT / "examples" / "output" / "b9_7"
DRIVER = BATCH_DIR / "scripts" / "replay_b9_7.py"
DECISIONS = BATCH_DIR / "decisions.json"
ISSUES = BATCH_DIR / "issues.json"
TRACE = BATCH_DIR / "prompt_trace.jsonl"
REPORT = BATCH_DIR / "report.md"

PREVIOUS_DIR = ROOT / "examples" / "output" / "b9_6"
PREVIOUS_INPUTS = PREVIOUS_DIR / "inputs"
PREVIOUS_ROUNDS = PREVIOUS_DIR / "rounds"
HISTORICAL_PROMPT_DIR = PREVIOUS_INPUTS / "prompt_b9_5"
HISTORICAL_CONFIG = PREVIOUS_INPUTS / "repair_actions.b9_5.json"

# The identity the b9.5 arms ran under, which is half of what a request is filed
# by and therefore half of what proves a replay is the same request.
IDENTITY = "OpenAITranslator/openai/zh"

# The three points that had to recover, and the one that had to not move.
RECOVERED = ("synthetic_contain", "courier_p1", "cern_p1")
REGRESSION = "orphan_spectrum"
CASES = (*RECOVERED, REGRESSION)

# The directories the newline pin covers, and the one exception inside them.
PINNED_DIRS = ("prompts", "configs", "spec_checks", "docs")
PIN_EXCEPTION = "docs/eval/results_"

# Paths this batch is allowed to have touched.
ALLOWED_PREFIXES = (
    "examples/output/b9_7/",
    "spec_checks/",
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    ".gitattributes",
    "babeldoc/magazine/react/controller.py",
    "configs/decision_rounds.json",
    "plans/PLAN_B9_7.md",
    "examples/output/run_all.b9_7.log",
}

# The one module of the package this batch may move.
ALLOWED_SOURCE = "babeldoc/magazine/react/controller.py"

# No ground truth and no ruling moves in this batch, and no tool.
FORBIDDEN_PREFIXES = ("corpus/", "reviews/", "tools/")

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b9_7")
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b9_7_"))


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


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def issue_kinds() -> tuple[str, ...]:
    return controller.detector_kinds()


def repair_config():
    return react_config.load_repair_config(None, issue_kinds())


def decisions() -> dict:
    return load_json(DECISIONS)


def frozen_issues() -> dict:
    return load_json(ISSUES)


class Frozen:
    """One recorded finding, in the shape the request builder reads."""

    def __init__(self, item: dict) -> None:
        self.id = item["id"]
        self.kind = item["kind"]
        self.severity = item["severity"]
        self.page = item["page"]
        self.paragraph_refs = list(item["paragraph_refs"])
        self.evidence = dict(item["evidence"])


def frozen_case(name: str) -> list[Frozen]:
    return [Frozen(item) for item in frozen_issues()[name]]


# --- 01 the scope --------------------------------------------------------------


def check_01a_the_delta_is_the_one_module_and_its_configuration() -> None:
    """Negative 1a: the batch moved the controller and nothing else that runs.

    A structural change to the loop is allowed exactly one file of the package,
    because every other way of asking a decision -- the client, the request
    builders, the vocabulary parser -- is shared with the paths this batch is
    not measuring.
    """
    faults = []
    delta = sorted(changed_paths())
    for path in delta:
        if path.startswith(FORBIDDEN_PREFIXES):
            faults.append(f"{path} is ground truth, a ruling or a tool")
        elif path.startswith("babeldoc/") and path != ALLOWED_SOURCE:
            faults.append(f"{path} is a second module of the package")
        elif path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES):
            faults.append(f"{path} is not registered for this batch")
    if not any(path == ALLOWED_SOURCE for path in delta):
        faults.append(f"{ALLOWED_SOURCE} is not in the delta at all")
    record(
        "check_01a_the_delta_is_the_one_module_and_its_configuration",
        not faults,
        "; ".join(faults),
    )


def check_01b_the_prompt_and_the_vocabulary_did_not_move() -> None:
    """Negative 1b: this batch measures a shape, so it changed no wording.

    The decision prompt and the repair vocabulary are asserted byte identical to
    the previous batch's, which is what makes the recovery below attributable to
    the rounds and to nothing else.
    """
    faults = []
    for tracked, path in (
        ("prompts/react_repair_decide.md", DECIDE_PROMPT),
        ("configs/repair_actions.json", REPAIR_CONFIG),
    ):
        code, previous = git_output(["show", f"{PREVIOUS_TAG}:{tracked}"])
        if code != 0:
            faults.append(f"{PREVIOUS_TAG} is not in the repository")
        elif previous != path.read_text(encoding="utf-8"):
            faults.append(f"{tracked} moved in a batch that changes no wording")
    record(
        "check_01b_the_prompt_and_the_vocabulary_did_not_move",
        not faults,
        "; ".join(faults),
    )


# --- 02 the newline pin --------------------------------------------------------


def check_02a_the_checkout_is_pinned() -> None:
    """Positive 2a: the newline of a digested file is declared, not inherited.

    Every directory the pin covers resolves to ``eol=lf``, and so does the frozen
    copy of the prompt a replay reproduces a request through. The exception is
    asserted to be an exception: the produced evaluation results are left to the
    clone, because each of them is compared byte for byte with a recomputation
    that writes the newline of the platform it runs on.
    """
    faults = []
    if not ATTRIBUTES.is_file():
        record("check_02a_the_checkout_is_pinned", False, "no .gitattributes")
        return
    probes = {
        "prompts/react_repair_decide.md": "lf",
        "configs/repair_actions.json": "lf",
        "configs/decision_rounds.json": "lf",
        "spec_checks/run_all.py": "lf",
        "docs/eval/gap_register.md": "lf",
        "examples/output/b9_6/inputs/prompt_b9_5/react_repair_decide.md": "lf",
        "docs/eval/results_e2/drift_attribution.json": "unspecified",
    }
    for path, wanted in probes.items():
        code, out = git_output(["check-attr", "eol", "--", path])
        got = out.strip().rsplit(": ", 1)[-1] if code == 0 else "<error>"
        if got != wanted:
            faults.append(f"{path}: eol is {got}, expected {wanted}")
    record("check_02a_the_checkout_is_pinned", not faults, "; ".join(faults))


def check_02b_the_working_tree_holds_what_the_pin_declares() -> None:
    """Positive 2b: the tree these assertions run over is the pinned tree.

    A declaration a checkout has not been brought up to is a declaration that
    describes a different tree than the one being measured, so every tracked file
    under the pinned directories is asserted to carry the pinned newline.
    """
    faults = []
    code, listing = git_output(["ls-files", "--eol", "--", *PINNED_DIRS])
    if code != 0:
        record(
            "check_02b_the_working_tree_holds_what_the_pin_declares",
            False,
            "git could not list the tree",
        )
        return
    for line in listing.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        path = fields[-1].strip()
        if path.startswith(PIN_EXCEPTION):
            continue
        working = line.split()[1]
        if working not in ("w/lf", "w/none", "w/-text"):
            faults.append(f"{path} is {working} in the working tree")
    record(
        "check_02b_the_working_tree_holds_what_the_pin_declares",
        not faults,
        "; ".join(faults[:5]),
    )


def check_02c_the_digest_assertions_hold_under_the_pin() -> None:
    """Positive 2c: the assertions that read bytes are recomputed under LF.

    Two of them, both inherited. The prompt in the tree is still the one batch
    b9.6's last round sent, and b9.6's two replayed requests still render to the
    cache keys those runs filed them under. Both are computed here from the files
    as the pin leaves them, so a pin that had moved either would fail here rather
    than in a later batch.
    """
    faults = []
    rounds = sorted(path for path in PREVIOUS_ROUNDS.iterdir() if path.is_dir())
    last = rounds[-1]
    sent = {
        json.loads(line)["prompt_sha256"]
        for line in (last / "prompt_trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["kind"] == "decide_prompt"
    }
    if sent != {file_digest(DECIDE_PROMPT)}:
        faults.append(
            f"{last.name} sent {sorted(item[:12] for item in sent)} and the tree "
            f"digests to {file_digest(DECIDE_PROMPT)[:12]}"
        )

    points = load_json(PREVIOUS_INPUTS / "decision_points.json")
    historical = react_config.parse_repair_config(
        load_json(HISTORICAL_CONFIG), HISTORICAL_CONFIG.name, set(issue_kinds())
    )
    for case, meta in points.items():
        recorded = load_json(PREVIOUS_INPUTS / f"{case}.issues.json")
        issues = [Frozen(item) for item in recorded["issues"]]
        prompt = prompt_loader.load_prompt(
            decide.DECIDE_PROMPT,
            {
                "issues_block": decide.issues_block(
                    issues,
                    historical.issue_excerpt_chars,
                    historical.max_issues_offered,
                ),
                "actions_block": decide.actions_block(historical),
                "action_constraints": decide.constraints_block(historical),
            },
            directory=HISTORICAL_PROMPT_DIR,
        )
        key = decide.cache_key(prompt, IDENTITY)
        if key != meta["cache_key"]:
            faults.append(
                f"{case}: rendered {key[:12]}, b9.5 filed {meta['cache_key'][:12]}"
            )
    record(
        "check_02c_the_digest_assertions_hold_under_the_pin",
        not faults,
        "; ".join(faults),
    )


# --- 03 the mechanism ----------------------------------------------------------


def check_03a_the_order_is_declared_and_complete() -> None:
    """Positive 3a: the rounds are taken in the order configs declares, and all of it.

    Every kind a detector raises has a place, nothing else has one, and reading
    the file twice gives the same order. Completeness is the load bearing half:
    a kind with no place would have its findings dropped out of every round in
    silence, which is the failure this batch is supposed to remove rather than
    move.
    """
    faults = []
    kinds = issue_kinds()
    order = controller.load_kind_order(kinds)
    declared = load_json(ROUNDS_CONFIG)[controller.KIND_ORDER_KEY]
    if list(order) != declared:
        faults.append("the loaded order is not the declared one")
    if sorted(order) != sorted(kinds):
        faults.append(f"the order is {sorted(order)} against kinds {sorted(kinds)}")
    if controller.load_kind_order(kinds) != order:
        faults.append("two loads of one file gave two orders")
    record(
        "check_03a_the_order_is_declared_and_complete", not faults, "; ".join(faults)
    )


def check_03b_an_incomplete_order_is_refused() -> None:
    """Negative 3b: a declaration that does not cover the detectors is an error.

    Three ways of being wrong -- a kind left out, a kind that no detector raises,
    and a kind named twice -- each asserted to raise rather than to run. A loader
    that silently accepted the first would drop a whole kind's findings.
    """
    faults = []
    kinds = issue_kinds()
    declared = list(controller.load_kind_order(kinds))
    broken = {
        "omits a kind": declared[:-1],
        "names an unraised kind": [*declared, "a_kind_no_detector_raises"],
        "names a kind twice": [*declared, declared[0]],
    }
    for label, order in broken.items():
        path = _tmp_root / f"rounds_{label.replace(' ', '_')}.json"
        path.write_text(
            json.dumps({controller.KIND_ORDER_KEY: order}), encoding="utf-8"
        )
        try:
            controller.load_kind_order(kinds, path)
        except react_config.RepairConfigError:
            continue
        except Exception as exc:  # noqa: BLE001 - any other failure is the wrong one
            faults.append(f"{label}: raised {type(exc).__name__}")
            continue
        faults.append(f"an order that {label} was accepted")
    record("check_03b_an_incomplete_order_is_refused", not faults, "; ".join(faults))


def check_03c_a_round_carries_one_kind_and_its_actions() -> None:
    """Positive 3c: the structural claim of the batch, over the frozen findings.

    For every case: the rounds are in the declared order, each carries findings
    of exactly one kind, the kinds are distinct, together they are every kind
    that has both a standing finding and an action answering for it, and each
    round's vocabulary is exactly that kind's actions. The last one is what makes
    the round narrow rather than merely sorted.
    """
    faults = []
    config = repair_config()
    order = controller.load_kind_order(issue_kinds())
    for name in CASES:
        issues = frozen_case(name)
        plan = controller.round_plan(config, order, issues)
        kinds = [kind for kind, _offered in plan]
        if kinds != [kind for kind in order if kind in kinds]:
            faults.append(f"{name}: rounds {kinds} are not in the declared order")
        if len(set(kinds)) != len(kinds):
            faults.append(f"{name}: a kind was given two rounds")
        for kind, offered in plan:
            carried = {issue.kind for issue in offered}
            if carried != {kind}:
                faults.append(f"{name}/{kind}: the round carries {sorted(carried)}")
            vocabulary = controller.round_vocabulary(config, kind).actions
            answering = {
                action.name
                for action in config.actions.values()
                if action.answers_for(kind)
            }
            if set(vocabulary) != answering:
                faults.append(
                    f"{name}/{kind}: vocabulary {sorted(vocabulary)} against "
                    f"{sorted(answering)}"
                )
        expected = sorted(
            {
                issue.kind
                for issue in issues
                if any(
                    action.answers_for(issue.kind) for action in config.actions.values()
                )
            }
        )
        if sorted(kinds) != expected:
            faults.append(f"{name}: rounds {sorted(kinds)} against {expected}")
    record(
        "check_03c_a_round_carries_one_kind_and_its_actions", not faults, "; ".join(faults)
    )


def check_03d_a_round_states_only_its_own_actions() -> None:
    """Positive 3d: what the round renders names no action from outside it.

    The narrowing has to reach the text, not only the table: an actions block
    still listing every action would put the finding back among the choices this
    batch exists to take it out of. Asserted over the shipped builders, for every
    kind that has a round at all.
    """
    faults = []
    config = repair_config()
    for kind in controller.load_kind_order(issue_kinds()):
        narrowed = controller.round_vocabulary(config, kind)
        if not narrowed.actions:
            continue
        rendered = decide.actions_block(narrowed)
        for name in config.actions:
            named = f'- name: "{name}"' in rendered
            if named != (name in narrowed.actions):
                faults.append(f"{kind}: the block {'names' if named else 'omits'} {name}")
        if f'- name: "{react_config.NO_ACTION}"' not in rendered:
            faults.append(f"{kind}: the round cannot answer with nothing")
        constraints = decide.constraints_block(narrowed)
        for name, action in config.actions.items():
            if name in narrowed.actions:
                continue
            for sentence in action.conditions():
                if sentence in constraints:
                    faults.append(f"{kind}: states a condition of {name}")
    record(
        "check_03d_a_round_states_only_its_own_actions", not faults, "; ".join(faults)
    )


def check_03e_the_kind_reaches_the_cache_key() -> None:
    """Positive 3e: two rounds of one iteration cannot share a stored answer.

    The key is asserted from the frozen trace, which is what the driver actually
    filed under, and independently recomputed here from the identity the round
    is built with. A key that did not carry the kind would let the first round's
    answer be served to the second, which is the one way a narrowed request could
    still be answered by a wide one.
    """
    faults = []
    entries = [
        json.loads(line)
        for line in TRACE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    prompts = [entry for entry in entries if entry["kind"] == "decide_prompt"]
    for name in CASES:
        keys = [entry["cache_key"] for entry in prompts if entry["case"] == name]
        if len(set(keys)) != len(keys):
            faults.append(f"{name}: two rounds filed under one key")
    # Recomputed: the same findings under two identities differing only in the
    # kind must not collide, and neither may equal the unnarrowed identity's.
    config = repair_config()
    issues = frozen_case("cern_p1")
    order = controller.load_kind_order(issue_kinds())
    seen: dict[str, str] = {}
    for kind, offered in controller.round_plan(config, order, issues):
        narrowed = controller.round_vocabulary(config, kind)
        client = decide.CachedDecisionClient(narrowed, identity=IDENTITY)
        wide = decide.cache_key(client.prompt(offered), IDENTITY)
        keyed = decide.cache_key(
            client.prompt(offered), f"{IDENTITY}{controller.ROUND_KEY_PREFIX}{kind}"
        )
        if wide == keyed:
            faults.append(f"{kind}: the kind does not reach the key")
        seen[kind] = keyed
    if len(set(seen.values())) != len(seen):
        faults.append(f"two kinds computed one key: {seen}")
    record("check_03e_the_kind_reaches_the_cache_key", not faults, "; ".join(faults))


def two_kind_document():
    """A page carrying a finding of two kinds at once, each with an action for it.

    The heading's ink reaches past the head of the frame, which is the kind the
    containment action answers for; the line below it is wholly in the source
    script and carries the label the orphan rule lists, which is the kind the
    orphan action answers for. Both labels are read off the shipped rules rather
    than written here, so the fixture stays a fixture of two rounds if either
    rule moves.
    """
    config = repair_config()
    heading_label = config.actions[contain.NAME].applicability[
        react_config.CONTAIN_LABELS_KEY
    ][0]
    orphan_rule = config.actions[orphan_actions.NAME].applicability
    orphan_label = orphan_rule[react_config.ORPHAN_LABELS_KEY][0]
    length = max(int(orphan_rule[react_config.MIN_CHARS_KEY]) * 4, 60)
    heading = b95.laid_out(
        "HEADLINE", 100.0, 780.0, size=30.0, label=heading_label, debug_id="head"
    )
    residue = b95.laid_out(
        "c" * length, 40.0, 200.0, size=8.0, label=orphan_label, debug_id="residue"
    )
    return b95.document([b95.page([heading, residue])])


def check_03f_an_iteration_is_every_round_once() -> None:
    """Positive 3f: the ceiling and the guard still count what they counted.

    A run over a document with two kinds standing records one iteration holding
    two rounds rather than two iterations of one round each: the run makes more
    rounds than it makes iterations, and the ceiling still bounds the iterations.
    Beside it, the two things the rounds could have quietly changed -- the
    guard's denominator, which is the whole of what was untreated when the
    iteration began rather than one round's share of it, and the aggregate the
    report has always carried, which is the rounds concatenated rather than one
    round chosen from them.
    """
    docs = two_kind_document()
    loop = b95.build_loop(_tmp_root / "iteration_shape", docs, RoundDecider([]))
    loop.run()
    report = load_json(loop.working_dir / controller.REPORT_NAME)
    faults = []
    first = report["iterations"][0]
    rounds = first["rounds"]
    total_rounds = sum(len(entry["rounds"]) for entry in report["iterations"])
    if len(rounds) < 2:
        faults.append(f"the first iteration held {len(rounds)} round(s)")
    if total_rounds <= report["iterations_run"]:
        faults.append(
            f"{total_rounds} round(s) over {report['iterations_run']} iteration(s): "
            f"a round is being counted as an iteration"
        )
    if report["iterations_run"] > repair_config().max_iterations:
        faults.append(f"{report['iterations_run']} iteration(s) past the ceiling")
    for entry in report["iterations"]:
        kinds = [item["kind"] for item in entry["rounds"]]
        if kinds != [kind for kind in report["kind_order"] if kind in set(kinds)]:
            faults.append(f"iteration {entry['iteration']}: rounds {kinds} out of order")
        if entry["untreated"]["total"] < sum(
            item["offered"] for item in entry["rounds"]
        ):
            faults.append("the guard counted less than the rounds were offered")
        aggregate = [row for item in entry["rounds"] for row in item["executed"]]
        if entry["executed"] != aggregate:
            faults.append("the executed aggregate is not the rounds concatenated")
    for key in ("detected", "decision", "executed", "recheck", "applicability"):
        if key not in first:
            faults.append(f"the iteration record omits {key}")
    record("check_03f_an_iteration_is_every_round_once", not faults, "; ".join(faults))


class RoundDecider(b95.Engine):
    """A stub that answers each round in the vocabulary that round declares.

    Which is itself an assertion: a round offering only the containment action is
    answered with containment, and a round that does not offer it is answered
    with nothing, because the stub can read no other name out of the request.
    """

    def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
        self.requests.append(text)
        if f'- name: "{contain.NAME}"' in text:
            return b95.decision_reply(b95.offered_ids(text), contain.NAME)
        return b95.decision_reply([], react_config.NO_ACTION)


# --- 04 the replay -------------------------------------------------------------


def check_04a_the_three_points_recovered() -> None:
    """Positive 4a: each of the three points chose containment, in its own round.

    The two b9.5 missed and the synthetic one whose correct answer is derived
    from the rule. What is asserted is the round for the kind the containment
    action answers for -- not any round -- and that it named exactly the findings
    the shipped rule admits.
    """
    faults = []
    chosen = decisions()
    kind = repair_config().actions[contain.NAME].issue_kinds[0]
    for name in RECOVERED:
        case = chosen[name]
        if case["subject_kind"] != kind:
            faults.append(f"{name}: scored on the {case['subject_kind']} round")
        if case["action"] != contain.NAME:
            faults.append(f"{name}: the round chose {case['action']!r}")
        if not case["ids_match"]:
            faults.append(
                f"{name}: named {case['issue_ids']}, the rule admits {case['expect_ids']}"
            )
        if kind not in case["round_kinds"]:
            faults.append(f"{name}: no round was run for {kind}")
    record("check_04a_the_three_points_recovered", not faults, "; ".join(faults))


def check_04b_the_expectations_are_derived_from_the_rule() -> None:
    """Negative 4b: no case writes its own correct answer down.

    The identifiers each recovered point was scored against are recomputed here
    from the shipped applicability terms over that case's own frozen evidence, so
    a case cannot be made to pass by editing what it was supposed to choose.
    """
    faults = []
    config = repair_config()
    action = config.actions[contain.NAME]
    labels = set(action.applicability[react_config.CONTAIN_LABELS_KEY])
    minimum = float(action.applicability[react_config.MIN_OVERFLOW_KEY])
    chosen = decisions()
    recorded = frozen_issues()
    for name in RECOVERED:
        admitted = sorted(
            item["id"]
            for item in recorded[name]
            if item["kind"] in action.issue_kinds
            and item["evidence"].get("layout_label") in labels
            and isinstance(item["evidence"].get("overflow_ratio"), int | float)
            and float(item["evidence"]["overflow_ratio"]) >= minimum
        )
        if sorted(chosen[name]["expect_ids"]) != admitted:
            faults.append(
                f"{name}: recorded expectation {chosen[name]['expect_ids']}, "
                f"the rule admits {admitted}"
            )
    if not DRIVER.exists():
        faults.append("the driver that produced the decisions is not in the tree")
    record(
        "check_04b_the_expectations_are_derived_from_the_rule",
        not faults,
        "; ".join(faults),
    )


def check_04c_the_orphan_spectrum_did_not_regress() -> None:
    """Positive/negative 4c: the nineteen finding fixture chose what it chose.

    Batch b8.4's spectrum, where only the orphan action has qualifying findings.
    The same action, no finding named that the rule refuses, and at least as many
    named as the last b9.6 round named. The identity of the findings inside the
    eligible set is not asserted: it is the model's to choose and it varies
    between samples, which is a recorded limitation rather than a regression.
    """
    faults = []
    config = repair_config()
    case = decisions()[REGRESSION]
    action = config.actions[orphan_actions.NAME]
    labels = set(action.applicability[react_config.ORPHAN_LABELS_KEY])
    floor = float(action.applicability[react_config.MIN_RATIO_KEY])
    chars = int(action.applicability[react_config.MIN_CHARS_KEY])
    eligible = {
        item["id"]
        for item in frozen_issues()[REGRESSION]
        if item["kind"] in action.issue_kinds
        and item["evidence"].get("layout_label") in labels
        and isinstance(item["evidence"].get("residue_ratio"), int | float)
        and float(item["evidence"]["residue_ratio"]) >= floor
        and len(str(item["evidence"].get("excerpt") or "")) >= chars
    }
    previous = load_json(
        sorted(path for path in PREVIOUS_ROUNDS.iterdir() if path.is_dir())[-1]
        / "decisions.json"
    )[REGRESSION]
    if case["action"] != orphan_actions.NAME:
        faults.append(f"the spectrum chose {case['action']!r}")
    if case["subject_kind"] not in case["round_kinds"]:
        faults.append("no round was run for the orphan kind")
    outside = sorted(set(case["issue_ids"]) - eligible)
    if outside:
        faults.append(f"named findings the rule refuses: {outside}")
    if len(case["issue_ids"]) < len(previous["issue_ids"]):
        faults.append(
            f"named {len(case['issue_ids'])} against b9.6's "
            f"{len(previous['issue_ids'])}"
        )
    if set(case["qualifying"]) != {orphan_actions.NAME}:
        faults.append(f"the fixture is no longer single action: {case['qualifying']}")
    if len(case["round_kinds"]) != 1:
        faults.append(f"the fixture ran {case['round_kinds']}, expected one round")
    record(
        "check_04c_the_orphan_spectrum_did_not_regress", not faults, "; ".join(faults)
    )


def check_04d_the_containment_guard_did_not_regress() -> None:
    """Positive/negative 4d: b9.5's guard spectrum, driven through the new shape.

    The guard is what decides whether a heading is slid, shrunk where it stands
    or left alone, and it runs underneath the decision. Both of its fixtures are
    put through the whole loop here rather than through the mechanism alone: the
    one with somewhere to go is contained, by the fallback and not by the slide,
    and the one with nowhere to go is escalated with the document byte identical.
    A round structure that had changed either would have changed what the loop
    writes, which is the only thing the guard is for.
    """
    faults = []
    docs, _heading, issue = b95.guard_fixture([b95.GUARD_UNDER_THE_SLIDE])
    if issue is None:
        faults.append("the fallback fixture detected nothing")
    loop = b95.build_loop(_tmp_root / "guard_fallback", docs, RoundDecider([]))
    loop.run()
    report = load_json(loop.working_dir / controller.REPORT_NAME)
    accepted = [
        row
        for iteration in report["iterations"]
        for row in iteration.get("executed", ())
        if row["accepted"]
    ]
    if len(accepted) != 1:
        faults.append(f"{len(accepted)} accepted application(s) on the fallback fixture")
    elif accepted[0]["geometry"].get("state") != contain.STATE_SCALED_IN_PLACE:
        faults.append(
            f"the fallback fixture was contained by "
            f"{accepted[0]['geometry'].get('state')!r}"
        )
    if report["conservation"]["verdict"] != controller.CONSERVED:
        faults.append(f"conservation: {report['conservation']['verdict']}")
    if report["conservation"]["changed_outside_touched"]:
        faults.append("a paragraph outside the contained set changed")

    docs, _heading, issue = b95.guard_fixture(
        [b95.GUARD_UNDER_THE_SLIDE, b95.GUARD_INSIDE_THE_SHRINK]
    )
    if issue is None:
        faults.append("the escalation fixture detected nothing")
    before = checkpoint_module.to_checkpoint_xml(docs)
    loop = b95.build_loop(_tmp_root / "guard_escalated", docs, RoundDecider([]))
    loop.run()
    report = load_json(loop.working_dir / controller.REPORT_NAME)
    reasons = {
        row["reason"]
        for iteration in report["iterations"]
        for row in (*iteration.get("executed", ()), *iteration.get("applicability", ()))
    }
    if report["applications"] != 0:
        faults.append(f"{report['applications']} application(s) on an escalated heading")
    if contain.REASON_INDUCED not in reasons:
        faults.append(f"the escalation was not recorded; reasons were {sorted(reasons)}")
    if checkpoint_module.to_checkpoint_xml(docs) != before:
        faults.append("the escalated document was not left exactly as it was")
    record(
        "check_04d_the_containment_guard_did_not_regress", not faults, "; ".join(faults)
    )


# --- 05 the record -------------------------------------------------------------


def check_05a_the_report_carries_the_decisions() -> None:
    """Positive 5a: the prose figures are the frozen figures.

    The prompt digest every round ran, and the identifier of every finding the
    three recovered points named, read out of the decisions and looked for in the
    report. A report drifting from its evidence is the failure this catches.
    """
    faults = []
    if not REPORT.exists():
        record("check_05a_the_report_carries_the_decisions", False, "no report")
        return
    report = REPORT.read_text(encoding="utf-8")
    chosen = decisions()
    digests = {
        item["prompt_sha256"]
        for case in chosen.values()
        for item in case["rounds"]
    }
    for digest in digests:
        if digest[:8] not in report:
            faults.append(f"the report does not carry the prompt {digest[:8]}")
    for name in RECOVERED:
        for issue_id in chosen[name]["issue_ids"]:
            if issue_id not in report:
                faults.append(f"the report does not carry {issue_id}")
        if name not in report:
            faults.append(f"the report does not name {name}")
    if REGRESSION not in report:
        faults.append(f"the report does not name {REGRESSION}")
    record("check_05a_the_report_carries_the_decisions", not faults, "; ".join(faults))


# --- 06 the sweep --------------------------------------------------------------


def check_06_history_is_green() -> None:
    """Positive 6: every earlier gate still passes with the new round shape in.

    Suppressed under the runner, which drives the whole history linearly and
    would otherwise run it once per gate.
    """
    if NESTED_SUPPRESSED:
        record("check_06_history_is_green", True, "run by spec_checks/run_all.py")
        return
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "spec_checks" / "run_all.py"), "--fast"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    record("check_06_history_is_green", proc.returncode == 0, (proc.stdout or "")[-800:])


CHECKS = (
    check_01a_the_delta_is_the_one_module_and_its_configuration,
    check_01b_the_prompt_and_the_vocabulary_did_not_move,
    check_02a_the_checkout_is_pinned,
    check_02b_the_working_tree_holds_what_the_pin_declares,
    check_02c_the_digest_assertions_hold_under_the_pin,
    check_03a_the_order_is_declared_and_complete,
    check_03b_an_incomplete_order_is_refused,
    check_03c_a_round_carries_one_kind_and_its_actions,
    check_03d_a_round_states_only_its_own_actions,
    check_03e_the_kind_reaches_the_cache_key,
    check_03f_an_iteration_is_every_round_once,
    check_04a_the_three_points_recovered,
    check_04b_the_expectations_are_derived_from_the_rule,
    check_04c_the_orphan_spectrum_did_not_regress,
    check_04d_the_containment_guard_did_not_regress,
    check_05a_the_report_carries_the_decisions,
    check_06_history_is_green,
)


def main() -> int:
    print("spec_check_b9_7: per kind decision rounds\n")
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
