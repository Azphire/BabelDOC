"""Cost attribution: which of this batch's requests were new, and why.

The run's ledger says how many calls reached the API and how many were answered
from cache. That is an accounting identity, not an explanation. This names the
cause of each new request, and is careful about what it can name.

T2 changes requests in two ways and both are identified positively, from the
source text each request carried rather than from a difference alone:

  the merge      a column chain is sent as one request, so a request whose
                 source is the merged source of a chain this run built is one
                 T2 created. The merge is recomputed with the pipeline's own
                 function, so the match is against the exact string sent.
  the claim      a member the chain pass claims is withheld from its page
                 batch, so the batch around it is composed differently. Such a
                 request is recognised by its prior counterpart: a request of
                 the previous run whose source contains this one's source and,
                 besides it, a claimed member's text.

The third bucket is a limit and is written as one. Three of the four samples
were last run several batches ago -- Courier-en and AramcoWorld-en-v2 at b11.3,
Courier-zh at b10.5 -- and every batch since changed something that reaches a
prompt. A new request of theirs that is neither of the two shapes above is not
this batch's to claim, and it is recorded with the batches standing between.
FD-en-v2 was last run at b11.5, the batch immediately before, and it is the
sample the sharp claim is made on: there every new request has to be T2's.

Two counts that do not match, and why neither is wrong. Not every engine call
appears here: the glossary extraction and the name harvest call the engine
without writing to the translation tracking file, so a run's request count can
exceed the number of prompts this reads. And not every chain produces a new
request: a chain that also existed in the prior run sent the same merged text
then, so its request is a cache hit now. Both are recorded per sample rather
than averaged away.

Writes examples/output/b11_6/cost_attribution.json.

Usage:
    python t_cost.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import chain_backfill as backfill  # noqa: E402

THIS = ROOT / "examples" / "output" / "b11_6"
OUT = THIS / "cost_attribution.json"
TRACKING = "translate_tracking.json"

SECTIONS = ("cross_page", "cross_column", "page")

# The most recent run of each sample before this one, and the batches that stand
# between it and this batch. Declared rather than searched for, because which
# run a comparison is against is a statement about the comparison.
PRIOR = {
    "Courier-en": {
        "tracking": "examples/output/b11_3/Courier-en/work/Courier-en",
        "batch": "b11.3",
        "between": ["b11.4", "b11.5"],
    },
    "AramcoWorld-en-v2": {
        "tracking": "examples/output/b11_3/AramcoWorld-en-v2/work/AramcoWorld-en-v2",
        "batch": "b11.3",
        "between": ["b11.4", "b11.5"],
    },
    "FD-en-v2": {
        "tracking": "examples/output/b11_5/FD-en-v2/work/FD-en-v2",
        "batch": "b11.5",
        "between": [],
    },
    "Courier-zh": {
        "tracking": "examples/output/b10_5/Courier-zh/on/work/Courier-zh",
        "batch": "b10.5",
        "between": ["b11.1", "b11.2", "b11.3", "b11.4", "b11.5"],
    },
}

CAUSE_MERGE = "T2 a column chain was sent to the engine as one request"
CAUSE_CLAIM = "T2 a page batch was recomposed around a member the chain pass claimed"

# The sample whose prior run is the batch immediately before this one, and on
# which every new request therefore has to be this batch's.
SHARP_SAMPLE = "FD-en-v2"


def requests_of(directory: Path) -> list[dict]:
    """Every distinct request one run sent, with what it was built around.

    One request is one prompt, and the tracking file records the prompt on every
    paragraph that travelled in it -- a batch of five records it five times, and
    a chain records it once per member. So the rows are folded by prompt, and
    each keeps the set of paragraph sources that rode in it. That set is what
    the causes below are read from: a prompt also carries a glossary table and a
    standing instruction, which move for reasons of their own.
    """
    path = directory / TRACKING
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        tracking = json.load(f)
    folded: dict[str, dict] = {}
    for section in SECTIONS:
        for holder in tracking.get(section) or ():
            for paragraph in holder.get("paragraph") or ():
                source = paragraph.get("pdf_unicode") or ""
                for tracker in paragraph.get("llm_translate_trackers") or ():
                    text = tracker.get("input")
                    if not text:
                        continue
                    row = folded.setdefault(
                        text, {"section": section, "text": text, "sources": []}
                    )
                    if source and source not in row["sources"]:
                        row["sources"].append(source)
    return list(folded.values())


def chains_of(sample: str) -> list[dict]:
    """Every chain this run built, with its merged source and its members."""
    path = THIS / sample / "chain_evidence.json"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        report = json.load(f)
    config = backfill.load_backfill_config()
    chains = []
    for chain in report["chains"]:
        texts = [member["source"] for member in chain["members"]]
        if any(not text.strip() for text in texts):
            continue
        try:
            merged = backfill.merge_chain_text(texts, config).text
        except backfill.ChainBackfillError:
            continue
        chains.append(
            {
                "pages": chain["pages"],
                "in_page": len(chain["pages"]) == 1,
                "members": texts,
                "merged": merged,
                # A chain the translation pass handed back to the per paragraph
                # path never sent a merged request, so it cannot be expected to
                # have one. It is carried here rather than filtered out, so the
                # count below says how many chains were given up on.
                "escalated": chain["joint_translation"] is None,
            }
        )
    return chains


def attribute(sample: str) -> dict:
    prior = PRIOR[sample]
    mine = requests_of(THIS / sample / "work" / sample)
    theirs = requests_of(ROOT / prior["tracking"])
    their_texts = {row["text"] for row in theirs}
    chains = chains_of(sample)
    claimed = [text for chain in chains for text in chain["members"]]

    for chain in chains:
        chain["merged_source_sent_before"] = any(
            chain["merged"] in row["text"] for row in theirs
        )

    carried = (
        f"carried over: the prior run of this sample is {prior['batch']}, with "
        f"{', '.join(prior['between'])} between"
        if prior["between"]
        else f"carried over: the prior run of this sample is {prior['batch']}"
    )

    def cause_of(row: dict) -> str:
        # The merge is read off the prompt, because the merged text is what the
        # prompt was built around and no paragraph of the run carries it whole.
        for chain in chains:
            if chain["merged"] and chain["merged"] in row["text"]:
                return CAUSE_MERGE
        # The claim is read off the batch composition: a prior request that
        # carried some of this one's paragraphs and, besides them, a paragraph
        # the chain pass has since taken away.
        mine_sources = set(row["sources"])
        if mine_sources:
            for other in theirs:
                theirs_sources = set(other["sources"])
                if not (mine_sources & theirs_sources):
                    continue
                if any(
                    text and text in theirs_sources and text not in mine_sources
                    for text in claimed
                ):
                    return CAUSE_CLAIM
        return carried

    seen: set[str] = set()
    rows = []
    rows_text: list[str] = []
    by_cause: dict[str, int] = {}
    for row in mine:
        if row["text"] in their_texts or row["text"] in seen:
            continue
        seen.add(row["text"])
        rows_text.append(row["text"])
        cause = cause_of(row)
        by_cause[cause] = by_cause.get(cause, 0) + 1
        rows.append(
            {
                "section": row["section"],
                "cause": cause,
                "chars": len(row["text"]),
                "paragraphs": len(row["sources"]),
                "source_excerpt": (row["sources"][0] if row["sources"] else "")[:140],
            }
        )

    with (THIS / sample / "run.json").open(encoding="utf-8") as f:
        ledger = json.load(f)
    merged_new = sum(1 for chain in chains if not chain["merged_source_sent_before"])
    # Which chains actually produced a request new to this run. Not the same
    # count as the rows: one merged source can appear in more than one distinct
    # prompt, because the glossary table a prompt carries is built per request
    # and moves under it. So the identity worth asserting is that every chain
    # whose merged source is new to this run has a request carrying it, not that
    # the two counts are equal.
    fresh_texts = list(rows_text)
    expected_a_request = [
        chain
        for chain in chains
        if not chain["merged_source_sent_before"] and not chain["escalated"]
    ]
    chains_with_a_request = sum(
        1
        for chain in expected_a_request
        if any(chain["merged"] in text for text in fresh_texts)
    )
    return {
        "sample": sample,
        "compared_against": prior["tracking"] + "/" + TRACKING,
        "prior_batch": prior["batch"],
        "batches_between": prior["between"],
        "chains": {
            "built": len(chains),
            "in_page": sum(1 for chain in chains if chain["in_page"]),
            "merged_source_new_to_this_run": merged_new,
            "escalated": sum(1 for chain in chains if chain["escalated"]),
            "pages": [chain["pages"] for chain in chains],
        },
        "ledger": {
            "requests": ledger["requests"],
            "cache_hits": ledger["cache_hits"],
            "api_calls": ledger["api_calls"],
        },
        "ledger_identity_holds": ledger["api_calls"]
        == ledger["requests"] - ledger["cache_hits"],
        "tracked_requests": len(mine),
        "untracked_requests": ledger["requests"] - len(mine),
        "requests_new_to_this_run": len(rows),
        "by_cause": by_cause,
        "merge_rows": by_cause.get(CAUSE_MERGE, 0),
        "claim_rows": by_cause.get(CAUSE_CLAIM, 0),
        "chains_with_a_new_request": chains_with_a_request,
        "chains_expected_to_send_one": len(expected_a_request),
        "every_new_chain_sent_a_request": chains_with_a_request
        == len(expected_a_request),
        "carried_over_rows": by_cause.get(carried, 0),
        "unattributed": [row for row in rows if row["cause"] == "unattributed"],
        "rows": rows,
    }


def main() -> int:
    samples = {}
    for sample in PRIOR:
        if not (THIS / sample / "run.json").is_file():
            continue
        samples[sample] = attribute(sample)

    sharp = samples.get(SHARP_SAMPLE) or {}
    totals = {
        "requests": sum(s["ledger"]["requests"] for s in samples.values()),
        "cache_hits": sum(s["ledger"]["cache_hits"] for s in samples.values()),
        "api_calls": sum(s["ledger"]["api_calls"] for s in samples.values()),
        "requests_new_to_this_run": sum(
            s["requests_new_to_this_run"] for s in samples.values()
        ),
        "merge_rows": sum(s["merge_rows"] for s in samples.values()),
        "claim_rows": sum(s["claim_rows"] for s in samples.values()),
        "carried_over_rows": sum(s["carried_over_rows"] for s in samples.values()),
        "chains_built": sum(s["chains"]["built"] for s in samples.values()),
        "chains_in_page": sum(s["chains"]["in_page"] for s in samples.values()),
    }
    record = {
        "batch": "b11_6",
        "method": (
            "A request present in this run and absent from the prior run of the "
            "same sample is a request that run did not send. It is claimed for "
            "this batch where its source is a chain's merged source, or where "
            "the prior run sent a request whose source contained both this "
            "request's source and a member the chain pass has since claimed. "
            "Otherwise it is recorded with the batches standing between the two "
            "runs, because a difference against a run several batches old is not "
            "this batch's to claim. FD-en-v2's prior run is the batch "
            "immediately before, so it is the sample on which every new request "
            "has to be this batch's."
        ),
        "sharp_sample": SHARP_SAMPLE,
        "sharp_sample_is_wholly_attributed": bool(sharp)
        and sharp["carried_over_rows"] == 0
        and sharp["requests_new_to_this_run"]
        == sharp["merge_rows"] + sharp["claim_rows"],
        "every_ledger_identity_holds": all(
            s["ledger_identity_holds"] for s in samples.values()
        ),
        "every_new_chain_sent_a_request": all(
            s["every_new_chain_sent_a_request"] for s in samples.values()
        ),
        "note": (
            "requests counts every call the engine made; tracked_requests counts "
            "the ones the translation tracking file records. The difference is "
            "the glossary extraction and the name harvest, which call the engine "
            "on their own paths. So requests_new_to_this_run is not expected to "
            "equal api_calls, and the identity asserted is the ledger's -- "
            "api_calls = requests - cache_hits -- together with every new "
            "tracked request carrying a named cause."
        ),
        "totals": totals,
        "unattributed": [
            row for sample in samples.values() for row in sample["unattributed"]
        ],
        "samples": samples,
    }
    OUT.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for name, sample in samples.items():
        print(
            f"{name:20s} api={sample['ledger']['api_calls']:3d} "
            f"new={sample['requests_new_to_this_run']:3d} "
            f"merge={sample['merge_rows']:2d}/{sample['chains']['merged_source_new_to_this_run']:2d} "
            f"claim={sample['claim_rows']:3d} "
            f"carried={sample['carried_over_rows']:3d} "
            f"untracked={sample['untracked_requests']:3d}"
        )
    print(f"totals: {totals}")
    print(f"sharp sample wholly attributed: {record['sharp_sample_is_wholly_attributed']}")
    print(f"report: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
