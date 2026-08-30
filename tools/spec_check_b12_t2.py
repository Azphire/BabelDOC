"""Gate: the decision step is held to shape and vocabulary, and to nothing else.

Two failures are possible here and they pull in opposite directions.  A
validator that checks too little lets a malformed reply reach the actions.  A
validator that checks too much -- in particular, one that also enforces the
admission rules -- turns an ordinary outcome into a protocol violation: the
model is shown the rules but the rules are applied from measurements it cannot
recompute, so "named a finding the rule refuses" is expected, not an error.
Spending the round's one retry on it would lose the round.

So this gate pins both edges.  S4 walks every violation class and requires each
to be refused; S5 requires a reply that names a finding the admission rule would
throw out to be accepted here anyway, because it is a nomination and the veto
lives elsewhere.

Nine claims:

S1  A well-formed reply becomes a decision on the first attempt, with no
    violation recorded.
S2  A violating reply is asked once more and, on a second violation, the round
    is abandoned rather than guessed: outcome abandoned_after_retry, action
    no_op, exactly the declared number of calls, both violations kept.
S3  A violating reply followed by a good one decides on the second attempt, and
    the first violation is still recorded.
S4  Every violation class is refused: a reply that is not JSON, one that is
    not an object, a missing field, an extra field, an action outside the
    round's offered set, an unoffered finding id, an undeclared parameter, an
    out-of-range parameter, and no_op named with findings.
S5  A reply naming a finding the admission rule would refuse is accepted.  The
    decision is a nomination; admission is not this validator's question.
S6  Every attempt is appended to the audit log with its request and its reply
    in full, so a decision can be read back to the words that produced it.
S7  Outside react/, the donor ReAct package is imported in exactly the two
    known writeback places.  A second decision path waking up unnoticed is the
    failure this gate exists to make loud.
S8  A decision record names no sample and carries no page anchor of its own.
S9  The prompt never tells the model to name an action the round does not
    offer.  A prompt that asks for one word and a vocabulary that offers
    another costs a violation and a retry on every round that takes it, and
    the retry hides the contradiction by recovering from it.

Run offline; the client is a recorded stub and no request leaves the machine.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import llm_decide  # noqa: E402
from babeldoc.magazine.detectors.base import Issue  # noqa: E402

# The two places outside react/ that may import the donor package, both of them
# the same typesetting writeback helper.
ALLOWED_REACT_IMPORTS = {
    "babeldoc/magazine/rotated_lane.py",
    "babeldoc/magazine/title_typeset.py",
}

KIND = "untranslated_residue"

# Words that would be an instruction to name an action, if the prompt used
# them. "none" is the one the donor prompt was written around.
_ACTION_WORDS = {"none", "no_op", "nothing", "skip"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class RecordingClient:
    """The model, replaced by a list of replies recorded in advance."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("the decision step asked for more replies than given")
        return self.replies.pop(0)


def _issue(reference: str, *, ratio: float = 1.0) -> Issue:
    return Issue(
        kind=KIND,
        page=7,
        paragraph_refs=(reference,),
        geometry=None,
        severity="high",
        evidence={
            "residue_ratio": ratio,
            "residue_chars": 40,
            "layout_label": "fallback_line",
            "excerpt": "a line the translation did not take",
        },
        detector=KIND,
    )


ISSUES = (_issue("p7#0"), _issue("p7#2", ratio=0.95))


def _config(*, parameters: dict | None = None) -> llm_decide.DecideConfig:
    """The shipped configuration, optionally given a parameter to declare.

    The shipped vocabulary declares no settable parameter yet, so the parameter
    rules are exercised against an explicit declaration rather than against a
    number invented in the configuration file.
    """
    raw = json.loads(
        (ROOT / "configs/repair_actions.json").read_text(encoding="utf-8")
    )
    if parameters is not None:
        raw["decide_parameters"] = parameters
    return llm_decide.parse_decide_config(raw, "repair_actions.json")


def _reply(**fields) -> str:
    return json.dumps(fields)


GOOD = _reply(
    action="translate_orphan_text",
    issue_ids=["p7#0"],
    parameters={},
    reason="the evidence reports full residue over the floor",
)


def _ids(issues) -> list[str]:
    return [issue.id for issue in issues]


def _decide(work: Path, client, *, config=None, name: str = "run"):
    return llm_decide.decide_round(
        KIND,
        ISSUES,
        client,
        config or _config(),
        working_dir=work / name,
    )


def s1_good_reply_decides_first_attempt(work: Path) -> str:
    offered = _ids(ISSUES)
    good = _reply(
        action="translate_orphan_text",
        issue_ids=[offered[0]],
        parameters={},
        reason="full residue over the floor",
    )
    client = RecordingClient(good)
    decision = _decide(work, client, name="s1")
    _require(
        decision.outcome == llm_decide.DECIDED,
        f"a good reply ended as {decision.outcome!r}",
    )
    _require(decision.attempts == 1, f"it took {decision.attempts} attempts")
    _require(not decision.violations, f"it recorded {decision.violations}")
    _require(
        decision.action == "translate_orphan_text"
        and decision.issue_ids == (offered[0],),
        f"the decision is {decision.as_record()}",
    )
    _require(len(client.prompts) == 1, f"it made {len(client.prompts)} calls")
    return "a well-formed reply decides on the first attempt with no violation"


def s2_two_violations_abandon_the_round(work: Path) -> str:
    bad = _reply(
        action="translate_orphan_text",
        issue_ids=_ids(ISSUES)[:1],
        parameters={},
        reason="ok",
        confidence=0.9,
    )
    client = RecordingClient(bad, bad)
    decision = _decide(work, client, name="s2")
    _require(
        decision.outcome == llm_decide.ABANDONED_AFTER_RETRY,
        f"two violations ended as {decision.outcome!r}",
    )
    _require(
        decision.action == llm_decide.NO_OP and not decision.issue_ids,
        f"the abandoned round still acts: {decision.as_record()}",
    )
    _require(
        len(client.prompts) == 2,
        f"the round made {len(client.prompts)} calls, not two",
    )
    _require(
        len(decision.violations) == 2,
        f"it kept {len(decision.violations)} violations",
    )
    _require(
        "confidence" in decision.violations[0],
        f"the violation does not name the offending field: "
        f"{decision.violations[0]!r}",
    )
    _require(
        "rejected" in client.prompts[1],
        "the second request does not state the rejection back to the model",
    )
    return (
        "a second violation abandons the round as "
        f"{llm_decide.ABANDONED_AFTER_RETRY} and applies nothing"
    )


def s3_retry_can_succeed(work: Path) -> str:
    offered = _ids(ISSUES)
    bad = _reply(action="translate_orphan_text", issue_ids=[], parameters={})
    good = _reply(
        action="translate_orphan_text",
        issue_ids=[offered[1]],
        parameters={},
        reason="second time",
    )
    client = RecordingClient(bad, good)
    decision = _decide(work, client, name="s3")
    _require(
        decision.outcome == llm_decide.DECIDED and decision.attempts == 2,
        f"the retry ended as {decision.outcome!r} at attempt {decision.attempts}",
    )
    _require(
        len(decision.violations) == 1,
        f"the first violation was not kept: {decision.violations}",
    )
    return "a violation followed by a good reply decides on the second attempt"


def s4_every_violation_class_is_refused(work: Path) -> str:
    offered = _ids(ISSUES)
    config = _config(
        parameters={
            "translate_orphan_text": {
                "minimum_scale": {"default": 0.7, "allowed_range": "0.4..1.0"}
            }
        }
    )
    cases = {
        "not an object": "[1, 2, 3]",
        "not JSON": "sorry, I cannot help with that",
        "missing field": _reply(
            action="translate_orphan_text", issue_ids=offered[:1], parameters={}
        ),
        "extra field": _reply(
            action="translate_orphan_text",
            issue_ids=offered[:1],
            parameters={},
            reason="r",
            note="extra",
        ),
        "action outside the offered set": _reply(
            action="retypeset_article_region",
            issue_ids=offered[:1],
            parameters={},
            reason="r",
        ),
        "unoffered finding id": _reply(
            action="translate_orphan_text",
            issue_ids=["p99#7"],
            parameters={},
            reason="r",
        ),
        "undeclared parameter": _reply(
            action="translate_orphan_text",
            issue_ids=offered[:1],
            parameters={"maximum_lines": 3},
            reason="r",
        ),
        "out-of-range parameter": _reply(
            action="translate_orphan_text",
            issue_ids=offered[:1],
            parameters={"minimum_scale": 0.1},
            reason="r",
        ),
        "no_op named with findings": _reply(
            action=llm_decide.NO_OP,
            issue_ids=offered[:1],
            parameters={},
            reason="r",
        ),
    }
    for label, reply in cases.items():
        decision, violation = llm_decide.interpret(
            reply,
            offered_actions=config.offered_actions(KIND),
            offered_ids=set(offered),
            config=config,
            kind=KIND,
        )
        _require(
            decision is None and bool(violation),
            f"{label} was accepted rather than refused",
        )
    return f"all {len(cases)} violation classes are refused, each with a reason"


def s5_admission_is_not_the_validators_question(work: Path) -> str:
    """A nomination the admission rule will throw out still validates here."""
    offered = _ids(ISSUES)
    # This finding reports a residue ratio of 0.95, over the configured floor,
    # but the admission rule also asks about article ownership and the label --
    # questions this validator must not be asking at all.  The reply names both
    # findings, one of which any real admission pass may well refuse.
    reply = _reply(
        action="translate_orphan_text",
        issue_ids=offered,
        parameters={},
        reason="both lines report residue",
    )
    decision, violation = llm_decide.interpret(
        reply,
        offered_actions=_config().offered_actions(KIND),
        offered_ids=set(offered),
        config=_config(),
        kind=KIND,
    )
    _require(
        decision is not None,
        f"a nomination was refused by the shape validator: {violation}",
    )
    _require(
        decision.issue_ids == tuple(offered),
        f"the nomination was altered to {decision.issue_ids}",
    )
    source = (ROOT / "babeldoc/magazine/llm_decide.py").read_text(encoding="utf-8")
    for forbidden in ("admits_", "article_document_ir", "by_element"):
        _require(
            forbidden not in source,
            f"the decision module reaches for {forbidden!r}, which is the "
            f"admission rule's to apply and not the validator's",
        )
    return (
        "a nomination the admission rule may refuse is accepted here, and the "
        "module reaches for no admission state at all"
    )


def s6_every_attempt_is_logged(work: Path) -> str:
    bad = _reply(
        action="translate_orphan_text",
        issue_ids=_ids(ISSUES)[:1],
        parameters={},
        reason="ok",
        confidence=1,
    )
    client = RecordingClient(bad, bad)
    _decide(work, client, name="s6")
    path = work / "s6" / llm_decide.DECISION_LOG_NAME
    _require(path.is_file(), f"no audit log was written at {path}")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _require(len(rows) == 2, f"the log holds {len(rows)} rows, not one per attempt")
    for index, row in enumerate(rows, start=1):
        _require(
            row["attempt"] == index and row["kind"] == KIND,
            f"row {index} is {row['attempt']} of {row['kind']}",
        )
        _require(
            bool(row["request"]) and bool(row["reply"]) and bool(row["violation"]),
            f"row {index} does not carry request, reply and violation in full",
        )
    _require(
        rows[0]["request"] != rows[1]["request"],
        "the retry logged the same request as the first attempt",
    )
    return "every attempt is logged with its request, its reply and its violation"


def s7_react_stays_asleep() -> str:
    found = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "-E",
            r"from babeldoc\.magazine\.react|from babeldoc\.magazine import react",
            "--",
            "*.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    files = {
        line.strip().replace("\\", "/")
        for line in found.stdout.splitlines()
        if line.strip()
    }
    outside = {
        name for name in files if not name.startswith("babeldoc/magazine/react/")
    }
    _require(
        outside == ALLOWED_REACT_IMPORTS,
        f"the donor ReAct package is imported outside react/ at "
        f"{sorted(outside)}; the allowed places are "
        f"{sorted(ALLOWED_REACT_IMPORTS)}",
    )
    return (
        f"outside react/, the donor package is imported only at the "
        f"{len(ALLOWED_REACT_IMPORTS)} known writeback places"
    )


def s8_decision_names_no_sample_or_anchor(work: Path) -> str:
    offered = _ids(ISSUES)
    client = RecordingClient(
        _reply(
            action="translate_orphan_text",
            issue_ids=offered[:1],
            parameters={},
            reason="residue over the floor",
        )
    )
    record = json.dumps(_decide(work, client, name="s8").as_record())
    names = {
        item.name.split(".")[0]
        for directory in (ROOT / "examples/input", ROOT / "reviews")
        if directory.is_dir()
        for item in directory.iterdir()
    }
    named = sorted(name for name in names if name and name in record)
    _require(not named, f"the decision record names samples {named}")
    source = (ROOT / "babeldoc/magazine/llm_decide.py").read_text(encoding="utf-8")
    anchors = re.findall(r"[\"']p[0-9]+#[0-9]+[\"']", source)
    _require(not anchors, f"the decision module carries page anchors {anchors}")
    return (
        f"the decision record names none of the {len(names)} known samples, and "
        f"the module carries no page anchor"
    )


def s9_the_prompt_offers_only_what_the_round_offers(work: Path) -> str:
    """Every action word the request uses has to be one the round accepts."""
    config = _config()
    offered = set(config.offered_actions(KIND))
    template = (ROOT / "prompts/react_repair_decide.md").read_text(encoding="utf-8")
    quoted = set(re.findall(r'"([a-z][a-z_]{2,})"', template))
    # Words the template quotes that are field names rather than actions.
    fields = set(llm_decide.REQUIRED_FIELDS) | {"id"}
    named_actions = {word for word in quoted - fields if word in _ACTION_WORDS}
    outside = sorted(named_actions - offered)
    _require(
        not outside,
        f"the prompt names {outside} as an action, which no round offers; the "
        f"model that follows it is refused and asked again for nothing",
    )
    client = RecordingClient(
        _reply(
            action="translate_orphan_text",
            issue_ids=_ids(ISSUES)[:1],
            parameters={},
            reason="residue over the floor",
        )
    )
    _decide(work, client, name="s9")
    request = client.prompts[0]
    for action in offered:
        _require(
            action in request,
            f"the request never names {action!r}, which the round accepts",
        )
    return (
        f"the prompt names no action outside the round's offer, and the request "
        f"carries all {len(offered)} it accepts"
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        claims = [
            ("S1", lambda: s1_good_reply_decides_first_attempt(work)),
            ("S2", lambda: s2_two_violations_abandon_the_round(work)),
            ("S3", lambda: s3_retry_can_succeed(work)),
            ("S4", lambda: s4_every_violation_class_is_refused(work)),
            ("S5", lambda: s5_admission_is_not_the_validators_question(work)),
            ("S6", lambda: s6_every_attempt_is_logged(work)),
            ("S7", s7_react_stays_asleep),
            ("S8", lambda: s8_decision_names_no_sample_or_anchor(work)),
            ("S9", lambda: s9_the_prompt_offers_only_what_the_round_offers(work)),
        ]
        for name, claim in claims:
            try:
                print(f"{name}  OK  {claim()}")
            except AssertionError as error:
                print(f"{name}  FAIL  {error}")
                return 1
    print("spec_check_b12_t2: all claims hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
