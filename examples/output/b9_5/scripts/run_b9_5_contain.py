"""B9.5 acceptance: the containment arm, with the decision scripted.

Why this arm exists. Everything the repair loop does passes through a model that
is asked which findings to act on, and that request is by design not served from
the cache. On the three arms this batch ran, that model chose the orphan action
on every sample that had an orphan to translate and never chose containment, so
the arms produced no page with a contained heading on it and no pixels to show.
A mechanism that cannot be shown is not accepted.

So this arm scripts the decision and nothing else. The prompt is still rendered
-- so the run pays what the request costs to build and the trace is a real one
-- and what is returned in place of the model's answer is: contain every out of
page finding this iteration reported, and nothing in the next iteration. The
action then holds each of those findings against its own rule exactly as it
would have, the guard measures each plan against the page exactly as it would
have, and the writer writes the result exactly as it would have. What is removed
from the measurement is the sampling, not the mechanism.

The scripted answer names every out of page finding without reading its
evidence, which is deliberately worse than what the model is asked for: it is
the action's own applicability rule, and not the chooser, that has to keep the
paragraphs it may not touch away from it. A finding the rule refuses is recorded
as a refusal and that is the escalation list.

Usage:
    python run_b9_5_contain.py --all
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_b9_5_ab as base  # noqa: E402
from babeldoc.docvision.doclayout import DocLayoutModel  # noqa: E402
from babeldoc.magazine.detectors import page_bounds  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

ARM = "contain"

# The ceiling the scripted answer asks for. The vocabulary's own range for this
# parameter, so the answer never asks for more than the configuration permits
# and the action's ceiling is what bounds the run.
MAX_PARAGRAPHS = 20


class ScriptedDecision:
    """Answers every decision point with containment, then with nothing.

    Installed by wrapping and removed afterwards, so a second sample in the same
    process is not answered by the first one's state.
    """

    def __init__(self) -> None:
        self._restore = None
        self.answers: list[dict] = []

    def install(self) -> None:
        original = decide.CachedDecisionClient.decide
        answers = self.answers

        def scripted(inner_self, issues):
            prompt = inner_self.prompt(issues)
            log = decide.RequestLog(
                prompt_digest=prompt.digest,
                prompt_text=prompt.text,
                key=decide.cache_key(prompt, inner_self.identity),
            )
            ids = tuple(
                issue.id for issue in issues if issue.kind == page_bounds.KIND
            )
            if not ids:
                decision = decide.Decision(
                    action=decide.NO_ACTION,
                    issue_ids=(),
                    parameters={},
                    reason="the scripted answer acts on out of page findings only",
                )
            else:
                decision = decide.Decision(
                    action=contain.NAME,
                    issue_ids=ids,
                    parameters={"max_paragraphs": float(MAX_PARAGRAPHS)},
                    reason=(
                        "scripted: every out of page finding is named and the "
                        "action's own rule decides which of them it may touch"
                    ),
                )
            answers.append(decision.as_record())
            return decision, log

        decide.CachedDecisionClient.decide = scripted
        self._restore = original

    def remove(self) -> None:
        if self._restore is not None:
            decide.CachedDecisionClient.decide = self._restore
            self._restore = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    base.load_dotenv()
    from babeldoc.magazine.cache_setup import use_project_cache

    use_project_cache(ROOT)
    set_translate_rate_limiter(base.QPS)
    base.ARMS[ARM] = True
    base.OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = list(base.SAMPLES) if args.all else (args.sample or [base.SAMPLES[0]])
    layout_model = DocLayoutModel.load_onnx()
    written = []
    for sample in wanted:
        script = ScriptedDecision()
        script.install()
        try:
            record = base.run_one(sample, ARM, layout_model)
        finally:
            script.remove()
        record["scripted_decisions"] = script.answers
        with (base.OUT_DIR / ARM / sample / "run.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        written.append(record)

    path = base.ledger_path(ARM)
    existing = []
    if path.exists() and not args.all:
        with path.open(encoding="utf-8") as f:
            existing = [
                row
                for row in json.load(f)
                if row["sample"] not in {item["sample"] for item in written}
            ]
    with path.open("w", encoding="utf-8") as f:
        json.dump(existing + written, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
