"""Gate script for micro batch B9.6 (the decide prompt's selection of containment).

Run from the repository root:

    python spec_checks/spec_check_b9_6.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: the batch's one instrument spends a credential and this gate
reads what it froze.

What this batch is. Batch b9.5 shipped ``contain_in_page`` and proved it on an
arm whose decision was scripted; on the arm where a model chose, the action was
never chosen. This batch reworded the request and nothing else -- one prompt file
and one ``description`` string -- and measured the rewording at four decision
points over three rounds.

01 is the scope, which is the batch's whole negative face: no source file
changed, ``configs/repair_actions.json`` changed in one ``description`` and in
nothing else, and no ground truth or ruling moved.

02 is the rounds. Every round keeps its request text, its replies and its
decisions; no two rounds ran the same prompt; the prompt in the tree is the last
round. That last assertion is the live one batch b8.4 declared belongs to
whichever batch reworks the prompt last, and this is that batch.

03 is the replay. The two decision points b9.5 missed are frozen here as the
findings those runs detected, and each is held against the cache key that run
filed its request under -- rendered through b9.5's own copy of the prompt, frozen
beside them, so the reproduction survives the prompt moving. A replay that no
longer reproduces is not evidence about wording.

04 is what the rounds chose, read against expectations derived from the
conditions the request states rather than written down: the two points that
recovered, the point that did not, and the regression face that did not move.

05 is the report, which has to carry the figures the decisions carry, and the
gap register, which has to have stopped saying the action is never selected.

06 is the mechanism, stub driven: the shipped applicability rule still admits
the containment finding at each recovered point and still admits exactly the
eligible set of b8.4's spectrum, so a gate that passes on wording cannot be
passing on a rule that quietly moved.

Tiers: every assertion here is static. Nothing in this gate runs the pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import prompt_loader  # noqa: E402
from babeldoc.magazine.react import actions as orphan_actions  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build:
# every document it asserts on is a stub it builds itself or evidence a
# batch froze, so it answers in seconds to a couple of minutes and runs on
# every batch.
GATE_SET = "fast"

BATCH_TAG = "batch-b9.6"
PREVIOUS_TAG = "batch-b9.5"

DECIDE_PROMPT = ROOT / "prompts" / "react_repair_decide.md"
REPAIR_CONFIG = ROOT / "configs" / "repair_actions.json"

BATCH_DIR = ROOT / "examples" / "output" / "b9_6"
INPUTS = BATCH_DIR / "inputs"
ROUNDS_DIR = BATCH_DIR / "rounds"
DRIVER = BATCH_DIR / "scripts" / "replay_b9_6.py"
REPORT = BATCH_DIR / "report.md"
HISTORICAL_PROMPT_DIR = INPUTS / "prompt_b9_5"
HISTORICAL_CONFIG = INPUTS / "repair_actions.b9_5.json"

GAP_REGISTER = ROOT / "docs" / "eval" / "gap_register.md"

# T3.4's ceiling on how many times one prompt may be reworked in a session, and
# the baseline round that is not a rework.
MAX_PROMPT_ROUNDS = 2
BASELINE_ROUND = "round0"

# The identity the b9.5 arms ran under, which is half of what a request is
# filed by and therefore half of what proves a replay is the same request.
B9_5_CACHE_KEY_VERSION = 1

IDENTITY = "OpenAITranslator/openai/zh"

# The four decision points, and what each one is for.
REPLAYS = ("cern_p1", "courier_p1")
SYNTHETIC = "synthetic_contain"
REGRESSION = "orphan_spectrum"
CASES = (*REPLAYS, SYNTHETIC, REGRESSION)

# The points this batch recovered and the one it did not, which the report says
# in prose and this gate holds to the frozen decisions.
RECOVERED = (SYNTHETIC, "courier_p1")
NOT_RECOVERED = ("cern_p1",)

# Paths this batch is allowed to have touched. The whole point of the batch is
# that the first two are the only behaviour it changes.
ALLOWED_PREFIXES = (
    "examples/output/b9_6/",
    "spec_checks/",
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "prompts/react_repair_decide.md",
    "configs/repair_actions.json",
    "plans/PLAN_B9_6.md",
    "docs/eval/gap_register.md",
    "examples/output/run_all.b9_6.log",
}

# No source file of the package may move in this batch, and no ground truth.
FORBIDDEN_PREFIXES = ("babeldoc/", "corpus/", "reviews/", "tools/")

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

LANGUAGE = "zh"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b9_6")


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


def rounds() -> list[Path]:
    if not ROUNDS_DIR.is_dir():
        return []
    return sorted(path for path in ROUNDS_DIR.iterdir() if path.is_dir())


def decisions_of(path: Path) -> dict:
    return load_json(path / "decisions.json")


def trace_of(path: Path) -> list[dict]:
    lines = (path / "prompt_trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def issue_kinds() -> tuple[str, ...]:
    return tuple(sorted(module.KIND for module in detectors.DETECTORS.values()))


def repair_config():
    return react_config.load_repair_config(None, issue_kinds())


# --- 01 the scope --------------------------------------------------------------


def check_01a_no_code_moved() -> None:
    """Negative 1a: the batch changed wording and nothing that runs.

    The hard constraint of a wording batch, asserted as a path set rather than
    as a promise: no module of the package, no tool, no ground truth and no
    ruling is in the delta.
    """
    faults = []
    for path in sorted(changed_paths()):
        if path.startswith(FORBIDDEN_PREFIXES):
            faults.append(f"{path} is outside a wording batch")
        elif path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES):
            faults.append(f"{path} is not registered for this batch")
    record("check_01a_no_code_moved", not faults, "; ".join(faults))


def as_this_batch_had_it(tracked: str, path):
    """One tracked file as this batch left it, or as the tree holds it.

    The batch's own tag where it exists, the working tree before it is cut. The
    claim being made is about what *this* batch did to the file, and reading the
    tree instead makes the claim about every batch since -- so it turns false the
    first time a later batch legitimately changes the same file, which is a gate
    that fails for having been overtaken rather than for a fault. CLAUDE.md
    section 5 asks changed-file assertions to anchor on the batch's own tag for
    exactly this reason.
    """
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code != 0:
        return path.read_text(encoding="utf-8")
    code, shipped = git_output(["show", f"{BATCH_TAG}:{tracked}"])
    return shipped if code == 0 else path.read_text(encoding="utf-8")


def check_01b_only_a_description_changed_in_the_config() -> None:
    """Negative 1b: the repair configuration moved in prose and nowhere else.

    Read against the previous batch's commit, key by key: every number, every
    vocabulary and every rule term identical, and the one difference a
    ``description``. A threshold moved under cover of a wording batch would be a
    behaviour change this batch is not allowed to make.
    """
    code, previous = git_output(["show", f"{PREVIOUS_TAG}:configs/repair_actions.json"])
    if code != 0:
        record(
            "check_01b_only_a_description_changed_in_the_config",
            False,
            f"{PREVIOUS_TAG} is not in the repository",
        )
        return
    was = json.loads(previous)
    now = json.loads(as_this_batch_had_it("configs/repair_actions.json", REPAIR_CONFIG))

    def stripped(node):
        """The configuration with every description removed, at any depth."""
        if isinstance(node, dict):
            return {
                key: stripped(value)
                for key, value in node.items()
                if key != "description"
            }
        if isinstance(node, list):
            return [stripped(item) for item in node]
        return node

    faults = []
    if stripped(was) != stripped(now):
        faults.append("the configuration changed somewhere other than a description")
    changed = [
        name
        for name in sorted(set(was["actions"]) | set(now["actions"]))
        if was["actions"].get(name, {}).get("description")
        != now["actions"].get(name, {}).get("description")
    ]
    if changed != [contain.NAME]:
        faults.append(f"descriptions changed for {changed}, expected [{contain.NAME!r}]")
    record(
        "check_01b_only_a_description_changed_in_the_config", not faults, "; ".join(faults)
    )


def check_01c_the_prompt_was_reworked() -> None:
    """Positive 1c: the prompt in the tree is not the one the previous batch sent.

    With the two properties the request has to keep whatever the wording is: it
    is still ASCII, and it still declares exactly the variables the shipped
    builders supply, so a section cannot have been dropped by renaming it.
    """
    faults = []
    text = DECIDE_PROMPT.read_text(encoding="utf-8")
    code, previous = git_output(
        ["show", f"{PREVIOUS_TAG}:prompts/react_repair_decide.md"]
    )
    if code != 0:
        faults.append(f"{PREVIOUS_TAG} is not in the repository")
    elif previous == text:
        faults.append("the prompt was not reworked at all")
    if not text.isascii():
        faults.append("the prompt is not ASCII")
    declared = set(prompt_loader.template_variables(text))
    supplied = {"issues_block", "actions_block", "action_constraints"}
    if declared != supplied:
        faults.append(f"the prompt declares {sorted(declared)}, supplied {sorted(supplied)}")
    record("check_01c_the_prompt_was_reworked", not faults, "; ".join(faults))


# --- 02 the rounds -------------------------------------------------------------


def check_02a_every_round_is_recorded() -> None:
    """Positive 2a: each round keeps what it sent, what came back and what it chose.

    Inside the ceiling, counting the baseline separately because the baseline is
    the prompt as it stood and not a rework of it.
    """
    faults = []
    recorded = rounds()
    if not recorded:
        record("check_02a_every_round_is_recorded", False, "no round was recorded")
        return
    if recorded[0].name != BASELINE_ROUND:
        faults.append(f"the first round is {recorded[0].name}, expected {BASELINE_ROUND}")
    if len(recorded) > MAX_PROMPT_ROUNDS + 1:
        faults.append(
            f"{len(recorded)} rounds against a ceiling of {MAX_PROMPT_ROUNDS} reworks"
        )
    for path in recorded:
        for name in ("prompt_trace.jsonl", "decisions.json", "issues.json"):
            if not (path / name).exists():
                faults.append(f"{path.name}: no {name}")
                continue
        if not (path / "decisions.json").exists():
            continue
        chosen = decisions_of(path)
        missing = [case for case in CASES if case not in chosen]
        if missing:
            faults.append(f"{path.name}: no decision for {missing}")
        trace = {entry["case"] for entry in trace_of(path) if entry["kind"] == "decide_prompt"}
        if trace != set(CASES):
            faults.append(f"{path.name}: the trace carries {sorted(trace)}")
    record("check_02a_every_round_is_recorded", not faults, "; ".join(faults))


def check_02b_no_two_rounds_ran_the_same_prompt() -> None:
    """Positive 2b: a round is a different request, not a rerun of one.

    And every case inside one round ran the same prompt as its siblings, or the
    round is not one round.
    """
    faults = []
    digests: dict[str, str] = {}
    for path in rounds():
        seen = {entry["prompt_sha256"] for entry in trace_of(path) if entry["kind"] == "decide_prompt"}
        if len(seen) != 1:
            faults.append(f"{path.name} ran {len(seen)} different prompts")
            continue
        digests[path.name] = seen.pop()
    if len(set(digests.values())) != len(digests):
        faults.append(f"two rounds ran the same prompt: {digests}")
    record("check_02b_no_two_rounds_ran_the_same_prompt", not faults, "; ".join(faults))


def check_02c_the_tree_carries_the_last_round() -> None:
    """Positive 2c: the prompt in the tree is the one the last round sent.

    The live half of the rounds discipline. Batch b8.4 declared it belongs to
    whichever batch reworked the prompt last and this is that batch, so it is
    asserted here and by nothing earlier. Its companion: the baseline round ran
    the prompt the previous batch shipped, or the diagnosis below it describes a
    request that batch never sent.
    """
    faults = []
    recorded = rounds()
    if not recorded:
        record("check_02c_the_tree_carries_the_last_round", False, "no round recorded")
        return
    current = file_digest(DECIDE_PROMPT)
    last = {
        entry["prompt_sha256"]
        for entry in trace_of(recorded[-1])
        if entry["kind"] == "decide_prompt"
    }
    if last != {current}:
        faults.append(
            f"{recorded[-1].name} ran {sorted(item[:12] for item in last)} and the "
            f"tree carries {current[:12]}"
        )
    code, previous = git_output(
        ["show", f"{PREVIOUS_TAG}:prompts/react_repair_decide.md"]
    )
    if code == 0:
        was = hashlib.sha256(previous.encode()).hexdigest()
        baseline = {
            entry["prompt_sha256"]
            for entry in trace_of(recorded[0])
            if entry["kind"] == "decide_prompt"
        }
        if baseline != {was}:
            faults.append(
                f"the baseline ran {sorted(item[:12] for item in baseline)} and "
                f"{PREVIOUS_TAG} shipped {was[:12]}"
            )
    record("check_02c_the_tree_carries_the_last_round", not faults, "; ".join(faults))


# --- 03 the replay -------------------------------------------------------------


def check_03a_the_replays_reproduce_the_missed_decisions() -> None:
    """Positive 3a: each replayed request is the request b9.5 sent, key for key.

    Rendered here from the frozen findings through b9.5's own copy of the prompt,
    and held against the cache key that run recorded. Recomputed rather than read
    back from the driver's own verdict, so a driver that stopped checking would
    fail here.
    """
    faults = []
    points = load_json(INPUTS / "decision_points.json")
    # b9.5's own configuration, because a request carries the action
    # descriptions and this batch reworded one of them. Reproducing the request
    # needs the configuration of that run as much as its prompt.
    config = react_config.parse_repair_config(
        load_json(HISTORICAL_CONFIG), HISTORICAL_CONFIG.name, set(issue_kinds())
    )
    # And the two frozen copies are the previous batch's own, or the whole
    # reproduction is circular: a copy of whatever the tree happens to say.
    for frozen_path, tracked in (
        (HISTORICAL_PROMPT_DIR / "react_repair_decide.md", "prompts/react_repair_decide.md"),
        (HISTORICAL_CONFIG, "configs/repair_actions.json"),
    ):
        code, shipped = git_output(["show", f"{PREVIOUS_TAG}:{tracked}"])
        if code != 0:
            faults.append(f"{PREVIOUS_TAG} is not in the repository")
        elif shipped != frozen_path.read_text(encoding="utf-8"):
            faults.append(f"{frozen_path.name} is not what {PREVIOUS_TAG} shipped")
    for case in REPLAYS:
        if case not in points:
            faults.append(f"{case} is not a registered decision point")
            continue
        frozen = load_json(INPUTS / f"{case}.issues.json")
        digest = file_digest(INPUTS / f"{case}.issues.json")
        if digest != points[case]["source_sha256"]:
            faults.append(f"{case}: the frozen findings are not the ones registered")
        blocks = {
            "issues_block": decide.issues_block(
                [Frozen(item) for item in frozen["issues"]],
                config.issue_excerpt_chars,
                config.max_issues_offered,
            ),
            "actions_block": decide.actions_block(config),
            "action_constraints": decide.constraints_block(config),
        }
        prompt = prompt_loader.load_prompt(
            decide.DECIDE_PROMPT, blocks, directory=HISTORICAL_PROMPT_DIR
        )
        # Under the composition b9.5 filed its keys with. B10.2 bumped the
        # current one, deliberately, to retire every key taken over an
        # unprojected request; recomputing these under today's composition would
        # assert only that today's code agrees with itself, where what is being
        # asserted is that the request b9.5 sent is reproduced here.
        key = decide.cache_key(prompt, IDENTITY, version=B9_5_CACHE_KEY_VERSION)
        if key != points[case]["cache_key"]:
            faults.append(
                f"{case}: rendered {key[:12]}, b9.5 filed {points[case]['cache_key'][:12]}"
            )
        if points[case]["target"] not in {item["id"] for item in frozen["issues"]}:
            faults.append(f"{case}: {points[case]['target']} is not in the frozen set")
    record(
        "check_03a_the_replays_reproduce_the_missed_decisions", not faults, "; ".join(faults)
    )


class Frozen:
    """One recorded finding, in the shape the request builder reads."""

    def __init__(self, item: dict) -> None:
        self.id = item["id"]
        self.kind = item["kind"]
        self.severity = item["severity"]
        self.page = item["page"]
        self.paragraph_refs = list(item["paragraph_refs"])
        self.evidence = dict(item["evidence"])


def check_03b_the_baseline_reproduced_what_b9_5_decided() -> None:
    """Positive 3b: the diagnosis rests on a reproduction, not on a recollection.

    The baseline round sent b9.5's own requests through b9.5's own prompt and is
    asserted to have come back with b9.5's own action at each replayed point. A
    baseline that decided something else would make the whole comparison below
    a comparison of two different things.
    """
    faults = []
    points = load_json(INPUTS / "decision_points.json")
    baseline = decisions_of(ROUNDS_DIR / BASELINE_ROUND)
    for case in REPLAYS:
        chosen = baseline[case]
        was = points[case]["b9_5_decision"]["action"]
        if chosen["action"] != was:
            faults.append(f"{case}: b9.5 chose {was}, the baseline chose {chosen['action']}")
        if chosen.get("reproduces_b9_5") is not True:
            faults.append(f"{case}: the baseline did not reproduce b9.5's request")
        if points[case]["target"] in chosen["issue_ids"]:
            faults.append(f"{case}: the baseline named the finding b9.5 missed")
    record(
        "check_03b_the_baseline_reproduced_what_b9_5_decided", not faults, "; ".join(faults)
    )


# --- 04 what the rounds chose --------------------------------------------------


def check_04a_containment_is_selected_where_it_is_the_only_answer() -> None:
    """Positive 4a: the synthetic point, where one action alone qualifies.

    Built so that exactly one action has a finding its conditions admit, which
    makes the correct choice derived rather than preferred. The baseline failed
    it and the last round has to pass it, or this batch bought nothing.
    """
    faults = []
    baseline = decisions_of(ROUNDS_DIR / BASELINE_ROUND)[SYNTHETIC]
    final = decisions_of(rounds()[-1])[SYNTHETIC]
    qualifying = final["qualifying"]
    if set(qualifying) != {contain.NAME}:
        faults.append(f"the case is no longer unambiguous: {sorted(qualifying)}")
    if baseline["action"] == contain.NAME:
        faults.append("the baseline already selected containment; the case proves nothing")
    if final["action"] != contain.NAME:
        faults.append(f"the last round chose {final['action']}")
    if not final["ids_match"]:
        faults.append(
            f"the last round named {final['issue_ids']}, the rule admits {final['expect_ids']}"
        )
    record(
        "check_04a_containment_is_selected_where_it_is_the_only_answer",
        not faults,
        "; ".join(faults),
    )


def check_04b_one_replayed_miss_was_recovered() -> None:
    """Positive 4b: the real decision point this batch turned round.

    The finding b9.5 left standing is named by the last round, and it is the
    finding the containment conditions admit rather than any finding at all.
    """
    faults = []
    points = load_json(INPUTS / "decision_points.json")
    final = decisions_of(rounds()[-1])
    for case in RECOVERED:
        if case not in REPLAYS:
            continue
        chosen = final[case]
        if chosen["action"] != contain.NAME:
            faults.append(f"{case}: chose {chosen['action']}")
        if points[case]["target"] not in chosen["issue_ids"]:
            faults.append(f"{case}: did not name {points[case]['target']}")
        if not chosen["ids_match"]:
            faults.append(f"{case}: named {chosen['issue_ids']}, admits {chosen['expect_ids']}")
    record("check_04b_one_replayed_miss_was_recovered", not faults, "; ".join(faults))


def check_04c_the_point_that_did_not_move_is_reported_as_such() -> None:
    """Negative 4c: the batch does not pass by quietly dropping what it missed.

    The point still failing is asserted to be still failing, and to be named in
    the report and in the gap register. A batch that had recovered it would fail
    here and would be right to: the assertion is that the record matches the
    decisions, in either direction.
    """
    faults = []
    final = decisions_of(rounds()[-1])
    report = REPORT.read_text(encoding="utf-8")
    for case in NOT_RECOVERED:
        chosen = final[case]
        if chosen["action"] == contain.NAME:
            faults.append(f"{case} now selects containment and is recorded as not moving")
        if case not in report:
            faults.append(f"the report does not name {case}")
    if "GAP-25" not in report:
        faults.append("the report does not carry the gap this leaves open")
    record(
        "check_04c_the_point_that_did_not_move_is_reported_as_such",
        not faults,
        "; ".join(faults),
    )


def check_04d_the_existing_action_did_not_regress() -> None:
    """Positive/negative 4d: the action that already worked chose what it chose.

    B8.4's spectrum, where only the orphan action has qualifying findings. Across
    every round: the same action, at least as many findings named as the baseline
    named, and every one of them inside the set the rule admits. Naming a finding
    the rule refuses is the regression that matters, because it spends the
    iteration on something that was never going to be repaired.
    """
    faults = []
    baseline = decisions_of(ROUNDS_DIR / BASELINE_ROUND)[REGRESSION]
    eligible = set(baseline["expect_ids"])
    if baseline["action"] != orphan_actions.NAME:
        faults.append(f"the baseline chose {baseline['action']}")
    for path in rounds():
        chosen = decisions_of(path)[REGRESSION]
        if chosen["action"] != orphan_actions.NAME:
            faults.append(f"{path.name}: chose {chosen['action']}")
        outside = sorted(set(chosen["issue_ids"]) - eligible)
        if outside:
            faults.append(f"{path.name}: named findings the rule refuses: {outside}")
        if len(chosen["issue_ids"]) < len(baseline["issue_ids"]):
            faults.append(
                f"{path.name}: named {len(chosen['issue_ids'])} against the "
                f"baseline's {len(baseline['issue_ids'])}"
            )
        if set(chosen["qualifying"]) != {orphan_actions.NAME}:
            faults.append(f"{path.name}: the fixture is no longer single action")
    record("check_04d_the_existing_action_did_not_regress", not faults, "; ".join(faults))


# --- 05 the record -------------------------------------------------------------


def check_05a_the_report_carries_the_decisions() -> None:
    """Positive 5a: the prose figures are the frozen figures.

    Every round's prompt digest, and the identifier of every recovered finding,
    read out of the decisions and looked for in the report. A report drifting
    from its evidence is the failure this catches.
    """
    faults = []
    if not REPORT.exists():
        record("check_05a_the_report_carries_the_decisions", False, "no report")
        return
    report = REPORT.read_text(encoding="utf-8")
    for path in rounds():
        digest = next(
            entry["prompt_sha256"]
            for entry in trace_of(path)
            if entry["kind"] == "decide_prompt"
        )
        if digest[:8] not in report:
            faults.append(f"the report does not carry {path.name}'s prompt {digest[:8]}")
    final = decisions_of(rounds()[-1])
    for case in RECOVERED:
        for issue_id in final[case]["issue_ids"]:
            if issue_id not in report:
                faults.append(f"the report does not carry {issue_id}")
    record("check_05a_the_report_carries_the_decisions", not faults, "; ".join(faults))


def check_05b_the_gap_register_is_current() -> None:
    """Negative 5b: the gap no longer says what this batch disproved.

    GAP-25 was written on b9.5's figure of never. It stays open, because one of
    two replayed points still fails, and it may not still read as never.
    """
    faults = []
    text = GAP_REGISTER.read_text(encoding="utf-8")
    if "GAP-25" not in text:
        record("check_05b_the_gap_register_is_current", False, "GAP-25 is not registered")
        return
    section = text.split("### GAP-25", 1)[1].split("### GAP-26", 1)[0]
    if "b9.6" not in section:
        faults.append("GAP-25 does not carry this batch's measurement")
    if "0/2" in section and "1/2" not in section:
        faults.append("GAP-25 still reports the selection rate this batch moved")
    record("check_05b_the_gap_register_is_current", not faults, "; ".join(faults))


# --- 06 the mechanism ----------------------------------------------------------


def check_06a_the_rule_still_admits_what_was_selected() -> None:
    """Positive 6a: the wording is measured against a rule that did not move.

    The shipped applicability terms, applied here to the frozen evidence of every
    finding the last round named. A gate that only read decisions could pass on a
    rule that had been loosened underneath it; this is what stops that.
    """
    faults = []
    config = repair_config()
    action = config.actions[contain.NAME]
    labels = set(action.applicability[react_config.CONTAIN_LABELS_KEY])
    minimum = float(action.applicability[react_config.MIN_OVERFLOW_KEY])
    final = rounds()[-1]
    chosen = decisions_of(final)
    frozen = load_json(final / "issues.json")
    for case in RECOVERED:
        evidence = {item["id"]: item["evidence"] for item in frozen[case]}
        for issue_id in chosen[case]["issue_ids"]:
            terms = evidence.get(issue_id)
            if terms is None:
                faults.append(f"{case}: {issue_id} is not in the round's findings")
                continue
            if terms.get("layout_label") not in labels:
                faults.append(f"{case}: {issue_id} carries {terms.get('layout_label')!r}")
            ratio = terms.get("overflow_ratio")
            if not isinstance(ratio, int | float) or float(ratio) < minimum:
                faults.append(f"{case}: {issue_id} reports overflow_ratio {ratio}")
    record("check_06a_the_rule_still_admits_what_was_selected", not faults, "; ".join(faults))


def check_06b_the_request_still_states_the_rule() -> None:
    """Positive 6b: the reworded request still feeds the filter it describes.

    Batch b8.4's property, reasserted because this batch rewrote the file around
    it: every condition of every action, with its own figure in it, in the text
    the builders render. A rewording that dropped the constraints block would
    pass every decision assertion above by accident and fail here.
    """
    faults = []
    config = repair_config()
    text = decide.constraints_block(config)
    for action in config.actions.values():
        conditions = action.conditions()
        if not conditions:
            faults.append(f"{action.name} states no condition at all")
        for sentence in conditions:
            if sentence not in text:
                faults.append(f"the request does not state {sentence!r}")
    prompt = DECIDE_PROMPT.read_text(encoding="utf-8")
    if "{action_constraints}" not in prompt:
        faults.append("the prompt no longer places the constraints block")
    record("check_06b_the_request_still_states_the_rule", not faults, "; ".join(faults))


def check_06c_the_driver_derives_its_expectations() -> None:
    """Negative 6c: no case writes its own correct answer down.

    Every expectation the driver records is derived from the declared rule, so a
    round cannot be made to pass by editing what it was supposed to choose. The
    finding identifiers the recovered points expect are asserted to be exactly
    what the shipped terms admit over the round's own frozen evidence.
    """
    faults = []
    config = repair_config()
    action = config.actions[contain.NAME]
    labels = set(action.applicability[react_config.CONTAIN_LABELS_KEY])
    minimum = float(action.applicability[react_config.MIN_OVERFLOW_KEY])
    final = rounds()[-1]
    chosen = decisions_of(final)
    frozen = load_json(final / "issues.json")
    for case in (*REPLAYS, SYNTHETIC):
        admitted = sorted(
            item["id"]
            for item in frozen[case]
            if item["kind"] in action.issue_kinds
            and item["evidence"].get("layout_label") in labels
            and isinstance(item["evidence"].get("overflow_ratio"), int | float)
            and float(item["evidence"]["overflow_ratio"]) >= minimum
        )
        if sorted(chosen[case]["expect_ids"]) != admitted:
            faults.append(
                f"{case}: recorded expectation {chosen[case]['expect_ids']}, "
                f"the rule admits {admitted}"
            )
    if not DRIVER.exists():
        faults.append("the driver that produced the rounds is not in the tree")
    record("check_06c_the_driver_derives_its_expectations", not faults, "; ".join(faults))


# --- 07 the sweep --------------------------------------------------------------


def check_07_history_is_green() -> None:
    """Positive 7: every earlier gate still passes with this batch's wording in.

    Suppressed under the runner, which drives the whole history linearly and
    would otherwise run it once per gate.
    """
    if NESTED_SUPPRESSED:
        record("check_07_history_is_green", True, "run by spec_checks/run_all.py")
        return
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "spec_checks" / "run_all.py"), "--fast"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    record(
        "check_07_history_is_green",
        proc.returncode == 0,
        (proc.stdout or "")[-800:],
    )


CHECKS = (
    check_01a_no_code_moved,
    check_01b_only_a_description_changed_in_the_config,
    check_01c_the_prompt_was_reworked,
    check_02a_every_round_is_recorded,
    check_02b_no_two_rounds_ran_the_same_prompt,
    check_02c_the_tree_carries_the_last_round,
    check_03a_the_replays_reproduce_the_missed_decisions,
    check_03b_the_baseline_reproduced_what_b9_5_decided,
    check_04a_containment_is_selected_where_it_is_the_only_answer,
    check_04b_one_replayed_miss_was_recovered,
    check_04c_the_point_that_did_not_move_is_reported_as_such,
    check_04d_the_existing_action_did_not_regress,
    check_05a_the_report_carries_the_decisions,
    check_05b_the_gap_register_is_current,
    check_06a_the_rule_still_admits_what_was_selected,
    check_06b_the_request_still_states_the_rule,
    check_06c_the_driver_derives_its_expectations,
    check_07_history_is_green,
)


def main() -> int:
    print("spec_check_b9_6: the decide prompt's selection of containment\n")
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
