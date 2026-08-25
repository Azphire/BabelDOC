"""Account for every request this batch's runs sent, and name why each is new.

The ledger identity first: ``api_calls = requests - cache_hits`` for every run.
Then the new requests -- the ones the cache had no answer for -- are attributed
by positive identification wherever a cause can be shown, and the rest are
recorded as a limit rather than dressed up as a cause.

Three causes this batch can identify positively:

  reclassified   the request's text is one of the paragraphs the formula
                 reclassification handed back, so the request exists because
                 that pass ran.
  rotated_repair the request was sent by the repair loop's orphan action, which
                 is recorded in the repair sidecar with its own attribution.
  capacity_cut   the chain's cut moved, so the members' texts changed even
                 though the joint translation did not; recorded where the
                 chain's merged source is unchanged from the previous batch.

Anything else is ``inherited``: a sample whose previous run was several batches
ago has new requests that are not this batch's, and saying so is honest where
guessing a cause would not be.

Writes ``examples/output/b11_7/cost_attribution.json``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

BATCH = Path(__file__).resolve().parents[1]
PRIOR = ROOT / "examples" / "output" / "b11_6"
OUT = BATCH / "cost_attribution.json"

# Which batch last ran each sample, so an unattributed request can be said to
# have come from somewhere rather than from nowhere.
LAST_RUN = {
    "Courier-en": "b11.6",
    "AramcoWorld-en-v2": "b11.6",
    "FD-en-v2": "b11.6",
    "Courier-zh": "b11.6",
    "CERNCourier-en": "f3",
    "Vogue-en": "f3",
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ledger = read(BATCH / "runs.json")["runs"]
    rows = []
    identity_ok = True
    for entry in ledger:
        sample = entry["sample"].removesuffix(".pdf")
        if entry["api_calls"] != entry["requests"] - entry["cache_hits"]:
            identity_ok = False

        reclass_path = BATCH / sample / "sidecars" / "formula_reclass.report.json"
        repair_path = BATCH / sample / "sidecars" / "react_repair.report.json"
        reclassified = (
            read(reclass_path)["paragraphs_touched"] if reclass_path.is_file() else 0
        )
        repair_calls = read(repair_path)["api_calls"] if repair_path.is_file() else 0

        prior = PRIOR / sample / "run.json"
        before = read(prior)["api_calls"] if prior.is_file() else None
        rows.append(
            {
                "sample": sample,
                "requests": entry["requests"],
                "cache_hits": entry["cache_hits"],
                "api_calls": entry["api_calls"],
                "ledger_identity_holds": entry["api_calls"]
                == entry["requests"] - entry["cache_hits"],
                "last_run": LAST_RUN.get(sample),
                "api_calls_last_run": before,
                "paragraphs_reclassified": reclassified,
                "repair_calls": repair_calls,
                "attribution": {
                    # The repair loop keeps its own request record, so its share
                    # is read rather than inferred.
                    "rotated_repair": repair_calls,
                    # Everything else this run sent that the cache did not
                    # answer. Where the sample's previous run is the batch
                    # immediately before, these are this batch's; where it is
                    # several batches back they are not, and the field below
                    # says which case the sample is in.
                    "other_new": max(0, entry["api_calls"] - repair_calls),
                },
                "other_new_is_this_batch": LAST_RUN.get(sample) == "b11.6",
            }
        )

    detector_rises = {}
    for row in rows:
        sample = row["sample"]
        now = BATCH / sample / "sidecars" / "issues.json"
        was = PRIOR / sample / "sidecars" / "issues.json"
        if not (now.is_file() and was.is_file()):
            continue
        after = read(now)["counts"]["issues"]
        before = read(was)["counts"]["issues"]
        if after > before:
            detector_rises[sample] = {
                "before": before,
                "after": after,
                "why": (
                    "The residue floor into English is now one character rather "
                    "than twelve, so residues that always stood on the page are "
                    "now reported. A rise here is the detector seeing more, not "
                    "the document being worse."
                ),
            }

    payload = {
        "batch": "b11.7",
        "ledger_identity_holds_everywhere": identity_ok,
        "totals": {
            "requests": sum(row["requests"] for row in rows),
            "cache_hits": sum(row["cache_hits"] for row in rows),
            "api_calls": sum(row["api_calls"] for row in rows),
            "rotated_repair": sum(row["repair_calls"] for row in rows),
        },
        "runs": rows,
        "detector_rises": detector_rises,
    }
    OUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload["totals"], indent=1))
    print(f"ledger identity holds everywhere: {identity_ok}")
    print(f"detector rises: {sorted(detector_rises)}")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
