"""B9.7 decision replay: the same four decision points, asked one kind per round.

Batch b9.6 measured wording at four decision points and recovered two of them.
This batch changes the shape of the request instead: an iteration asks for its
decision one detector kind at a time, so a round shows the findings of a single
kind and the actions that answer for it. The prompt file is not touched, which
is what makes this measurement about the shape and nothing else.

The four cases are batch b9.6's own, imported from the driver that built them
rather than rebuilt here. A zero regression claim about a fixture is worth
nothing if the fixture was rebuilt by the batch making the claim, and the same
goes for the two replays: their findings, their prompt copy and their repair
configuration are the frozen inputs b9.6 registered, and this driver reads them
where they sit.

What is different is how each case is asked. Instead of one request carrying
every finding and every action, the case is put through the rounds the shipped
controller would put it through -- ``round_plan`` for which rounds there are and
in what order, ``round_vocabulary`` for what each one may name -- and every
round is sent, sampled and interpreted separately. A case is a hit when the
round for the kind its finding belongs to chose the action the declared rule
admits it under, and named the findings that rule admits.

Not part of the gate: this is the only thing in the batch that spends a
credential.

Usage:
    python replay_b9_7.py
    python replay_b9_7.py --case cern_p1
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.react import actions as orphan_actions  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

BATCH_DIR = ROOT / "examples" / "output" / "b9_7"
PREVIOUS_DIR = ROOT / "examples" / "output" / "b9_6"
PREVIOUS_DRIVER = PREVIOUS_DIR / "scripts" / "replay_b9_6.py"

MODEL = "gpt-4o"
QPS = 4
LANGUAGE = "zh"

# The identity the b9.5 arms ran under, and therefore the one a replayed request
# has to be filed by before the round narrows it further.
IDENTITY = f"OpenAITranslator/openai/{LANGUAGE}"

TRACE_NAME = "prompt_trace.jsonl"
DECISIONS_NAME = "decisions.json"
ISSUES_NAME = "issues.json"

CASES = ("cern_p1", "courier_p1", "synthetic_contain", "orphan_spectrum")

# Which action each case is a case about, and therefore which round's choice is
# the case's verdict. Derived from the fixture rather than declared about it:
# the kind is the one the expected action answers for.
EXPECTED_ACTION = {
    "cern_p1": contain.NAME,
    "courier_p1": contain.NAME,
    "synthetic_contain": contain.NAME,
    "orphan_spectrum": orphan_actions.NAME,
}


def previous_driver():
    """Batch b9.6's driver, loaded from where it sits and never copied.

    The fixtures this batch is measured on are that batch's fixtures. Importing
    them is what makes the comparison one between two shapes of request rather
    than one between two sets of findings that happen to look alike.
    """
    spec = importlib.util.spec_from_file_location("replay_b9_6", PREVIOUS_DRIVER)
    module = importlib.util.module_from_spec(spec)
    # Registered before it is executed, because a frozen dataclass declared in it
    # resolves its own annotations through sys.modules while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def issue_kinds() -> tuple[str, ...]:
    return controller.detector_kinds()


def repair_config():
    return react_config.load_repair_config(None, issue_kinds())


def as_record(issue) -> dict:
    return {
        "id": issue.id,
        "kind": issue.kind,
        "severity": issue.severity,
        "page": issue.page,
        "paragraph_refs": list(issue.paragraph_refs),
        "evidence": dict(issue.evidence),
    }


def load_dotenv() -> None:
    """Read the repository .env for a credential the shell does not carry."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def build_engine() -> OpenAITranslator:
    load_dotenv()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set; this driver spends a credential")
    return OpenAITranslator(
        lang_in="en",
        lang_out=LANGUAGE,
        model=MODEL,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=key,
        ignore_cache=True,
    )


def merge_lines(path: Path, lines: list[str]) -> None:
    """Append this invocation's entries, keeping any other case's."""
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    written = {json.loads(line)["case"] for line in lines}
    keep = [
        line
        for line in existing
        if line.strip() and json.loads(line)["case"] not in written
    ]
    path.write_text("\n".join([*keep, *lines]) + "\n", encoding="utf-8", newline="\n")


def merge_json(path: Path, payload: dict) -> None:
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    stored.update(payload)
    path.write_text(
        json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", default=None)
    args = parser.parse_args()

    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    previous = previous_driver()
    config = repair_config()
    order = controller.load_kind_order(issue_kinds())

    set_translate_rate_limiter(QPS)
    engine = build_engine()
    identity = decide.engine_identity(engine, LANGUAGE)
    if identity != IDENTITY:
        raise SystemExit(f"engine identity is {identity!r}, expected {IDENTITY!r}")

    cases = previous.build_cases()
    wanted = list(args.case or CASES)
    trace_lines: list[str] = []
    decisions: dict[str, dict] = {}
    issue_sets: dict[str, list[dict]] = {}

    for name in wanted:
        case = cases[name]
        issues = case["issues"]
        issue_sets[name] = [as_record(issue) for issue in issues]
        expected_action = EXPECTED_ACTION[name]
        # The round whose choice is this case's verdict: the one for the kind the
        # expected action answers for. Read off the vocabulary, so a fixture
        # cannot be scored against a round chosen by hand.
        subject_kind = config.actions[expected_action].issue_kinds[0]

        rounds: list[dict] = []
        for kind, offered in controller.round_plan(config, order, issues):
            narrowed = controller.round_vocabulary(config, kind)
            client = decide.CachedDecisionClient(
                narrowed,
                transport=decide.EngineTransport(engine),
                identity=f"{identity}{controller.ROUND_KEY_PREFIX}{kind}",
                ignore_cache=True,
            )
            prompt = client.prompt(offered)
            entry = {
                "kind": "decide_prompt",
                "case": name,
                "round_kind": kind,
                "vocabulary": sorted(narrowed.actions),
                "offered_ids": [issue.id for issue in offered],
                "prompt_file": f"{decide.DECIDE_PROMPT}.md",
                "prompt_sha256": prompt.digest,
                "request_sha256": hashlib.sha256(prompt.text.encode()).hexdigest(),
                "cache_key": decide.cache_key(
                    prompt, f"{identity}{controller.ROUND_KEY_PREFIX}{kind}"
                ),
                "prompt_text": prompt.text,
            }
            trace_lines.append(json.dumps(entry, ensure_ascii=False))

            decision, log = client.decide(offered)
            trace_lines.append(
                json.dumps(
                    {
                        "kind": "decide_reply",
                        "case": name,
                        "round_kind": kind,
                        "replies": log.replies,
                    },
                    ensure_ascii=False,
                )
            )
            rounds.append(
                {
                    "round_kind": kind,
                    "vocabulary": sorted(narrowed.actions),
                    "offered_ids": [issue.id for issue in offered],
                    "action": decision.action,
                    "issue_ids": list(decision.issue_ids),
                    "parameters": decision.parameters,
                    "reason": decision.reason,
                    "attempts": decision.attempts,
                    "violations": list(decision.violations),
                    "request_sha256": entry["request_sha256"],
                    "prompt_sha256": entry["prompt_sha256"],
                    "cache_key": entry["cache_key"],
                }
            )

        subject = next(
            (item for item in rounds if item["round_kind"] == subject_kind), None
        )
        chosen = list(subject["issue_ids"]) if subject else []
        expected = list(case["expect_ids"])
        record = {
            "case_kind": case["kind"],
            "subject_kind": subject_kind,
            "expect_action": expected_action,
            "expect_ids": expected,
            "rounds": rounds,
            "round_kinds": [item["round_kind"] for item in rounds],
            "action": subject["action"] if subject else "",
            "issue_ids": chosen,
            "action_matches": bool(subject) and subject["action"] == expected_action,
            "ids_match": sorted(chosen) == sorted(expected),
            "names_expected": bool(expected) and set(expected) <= set(chosen),
            "qualifying": case["qualifying"],
        }
        for key in ("declared_target", "b9_5_decision"):
            if key in case:
                record[key] = case[key]
        decisions[name] = record
        print(
            f"{name}: round {subject_kind} -> "
            f"{record['action']} {chosen} (expected {expected_action} {expected}); "
            f"rounds {record['round_kinds']}"
        )

    merge_lines(BATCH_DIR / TRACE_NAME, trace_lines)
    merge_json(BATCH_DIR / DECISIONS_NAME, decisions)
    merge_json(BATCH_DIR / ISSUES_NAME, issue_sets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
