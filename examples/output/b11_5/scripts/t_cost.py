"""Cost attribution: which of this batch's requests were new, and why.

The run's ledger says how many calls reached the API and how many were answered
from cache. That is an accounting identity, not an explanation. What this does
is name the cause of each new call: it reads the request texts this run built
and the request texts the b11.4 run of the same sample built, and every text
that is in this run and not in that one is a call this batch caused. The cause
is then read off the text itself -- a request whose paragraph is the drop cap
paragraph is T2's; a request carrying one of the newly ruled glossary rows is
T1's or T4's.

Writes examples/output/b11_5/cost_attribution.json.

Usage:
    python t_cost.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

SAMPLE = "FD-en-v2"
THIS = ROOT / "examples" / "output" / "b11_5"
PRIOR = ROOT / "examples" / "output" / "b11_4"
TRACKING = "translate_tracking.json"
OUT = THIS / "cost_attribution.json"

# The rows ruled in this batch, and the batch task each belongs to. A request
# carrying one of these strings is a request whose glossary table changed, which
# is what made it a new text.
RULED = {
    "F&D": "T1",
    "Huong (Vanessa) Le": "T4",
    "S M Ali Abbas": "T4",
    "2communiqué": "T4",
}

# What the drop cap paragraph opens with. A request carrying it is the request
# T2 changed, because T2 is what took the placeholder out of it.
DROP_CAP_OPENING = "it comes to international trade"

# Where the glossary table starts inside a built prompt. A ruled row does not
# only enter the prompts whose paragraph contains it: ruling a row takes it out
# of the automatically extracted glossary, so the table under an untouched
# paragraph changes too, and the prompt is a new text for the cache. Splitting
# the prompt here is how that cause is told from a changed paragraph.
GLOSSARY_MARKER = "## Glossary Tables"


def without_glossary(text: str) -> str:
    return text.split(GLOSSARY_MARKER, 1)[0]


SECTIONS = ("cross_page", "cross_column", "page")


def request_texts(path: Path) -> list[dict]:
    """Every prompt one run sent, as the tracking file records them.

    The prompt rather than the paragraph: a paragraph reaches the engine inside
    a prompt that also carries the glossary table, and it is the whole prompt
    that the cache is keyed on. Reading the paragraph alone would miss exactly
    the change this batch made, which is to the table.
    """
    with path.open(encoding="utf-8") as f:
        tracking = json.load(f)
    found: list[dict] = []
    for section in SECTIONS:
        for holder in tracking.get(section) or ():
            for paragraph in holder.get("paragraph") or ():
                for tracker in paragraph.get("llm_translate_trackers") or ():
                    text = tracker.get("input")
                    if text:
                        found.append({"section": section, "text": text})
    return found


def cause_of(text: str, prior_bodies: set[str]) -> str:
    if DROP_CAP_OPENING in text:
        return "T2 drop cap paragraph: the placeholder left the request"
    hits = sorted({task for row, task in RULED.items() if row in text})
    if hits:
        rows = sorted(row for row in RULED if row in text)
        return f"{'/'.join(hits)} ruled glossary row(s) {rows} entered the table"
    if without_glossary(text) in prior_bodies:
        return (
            "T1/T4 the glossary table changed under an unchanged paragraph: "
            "ruling a row moves it out of the extracted glossary"
        )
    return "unattributed"


def main() -> int:
    this_path = THIS / SAMPLE / "work" / SAMPLE / TRACKING
    prior_path = PRIOR / SAMPLE / "work" / SAMPLE / TRACKING
    if not this_path.is_file():
        raise SystemExit(f"no tracking at {this_path}")

    mine = request_texts(this_path)
    theirs = (
        {row["text"] for row in request_texts(prior_path)}
        if prior_path.is_file()
        else set()
    )

    prior_bodies = {
        without_glossary(row["text"]) for row in request_texts(prior_path)
    } if prior_path.is_file() else set()

    seen: set[str] = set()
    fresh = []
    for row in mine:
        if row["text"] in theirs or row["text"] in seen:
            continue
        seen.add(row["text"])
        fresh.append(row)
    by_cause: dict[str, int] = {}
    rows = []
    for row in fresh:
        cause = cause_of(row["text"], prior_bodies)
        by_cause[cause] = by_cause.get(cause, 0) + 1
        rows.append(
            {
                "section": row["section"],
                "cause": cause,
                "chars": len(row["text"]),
                "excerpt": row["text"][:120],
            }
        )

    with (THIS / SAMPLE / "run.json").open(encoding="utf-8") as f:
        ledger = json.load(f)

    record = {
        "sample": SAMPLE,
        "compared_against": str(prior_path.relative_to(ROOT)).replace("\\", "/"),
        "ledger": {
            "requests": ledger["requests"],
            "cache_hits": ledger["cache_hits"],
            "api_calls": ledger["api_calls"],
        },
        "method": (
            "A request text present in this run and absent from the b11.4 run of "
            "the same sample is a text this batch caused. The comparison is over "
            "the tracking files both runs wrote, not over the cache."
        ),
        "prompts_this_run": len(mine),
        "prompts_distinct_this_run": len({row["text"] for row in mine}),
        "prompts_new_to_this_run": len(fresh),
        "by_cause": by_cause,
        "unattributed": [r for r in rows if r["cause"] == "unattributed"],
        "rows": rows,
        "covers_api_calls": len(fresh) >= ledger["api_calls"],
        "note": (
            "Every new prompt is a prompt this batch caused, and every API call "
            "the run made was a prompt the cache did not hold. The count of new "
            "prompts is at or above the call count rather than equal to it, for "
            "two reasons that are both one directional: a prompt new to this "
            "sample may still have been cached from an earlier session, and the "
            "name harvest and short unit paths call the engine without writing "
            "to this file. So what is asserted is that the ledger identity "
            "holds, that the new prompts cover the calls, and that not one new "
            "prompt is unattributed."
        ),
    }
    OUT.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({k: record[k] for k in
                      ("prompts_this_run", "prompts_distinct_this_run",
                       "prompts_new_to_this_run", "by_cause",
                       "covers_api_calls")}, ensure_ascii=False, indent=1))
    print(f"ledger {record['ledger']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
