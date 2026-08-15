"""Attribute the neighbour drift of the chain A/B to a cause, paragraph by paragraph.

Ledger row A-12 records fifteen paragraphs of Courier-en changing between a run
with chain level joint translation down and one with it up, and D3 GAP-01 holds
that the two-run design cannot say why: eleven of the fifteen are batch
neighbours whose changes are the size this engine's repeat noise is, and the
paragraphs that did *not* change were served from cache and were therefore
identical by construction rather than by measurement.

The three runs of ``tools/run_drift_trio.py`` remove the construction. Both off
arms sample the engine afresh on identical prompts, so a paragraph that is
identical between them is identical by measurement, and a paragraph that is not
has been shown to move under resampling alone.

The rule D3 GAP-01 specifies is reported as ``gap01_verdict`` and is a pure
function of the three translation columns, so any reader can recompute it:

* a paragraph the chain pass merged is a ``chain_member`` -- it is the mechanism
  itself and is not evidence about neighbours;
* otherwise, ``off1 != off2`` is ``sampling_noise``: two independent draws of one
  question already disagree here;
* otherwise, ``off1 == off2 != on`` is ``rebatch_effect``: the two draws agree and
  the arm whose batches were recomposed is the one that differs.

That rule attributes to recomposition every row the two off draws happen to
agree about, including rows on pages where nothing was recomposed, so a second
discriminator is carried beside it and the reported ``verdict`` uses both. Every
request the runs built was traced with the paragraphs it was built from, so for
each paragraph it is known whether the batch it was asked about moved between
the arms -- which is the recomposition of ledger row A-13 measured directly
rather than inferred. A row the two off draws agree about, whose batch did not
move, is ``run_variance``: the on arm asked an identical question of an identical
batch and is simply a third draw, taken on another occasion.

The prompt bytes are *not* used as that discriminator, and the reason is a
finding of these runs rather than a design choice. The automatic term extractor
is itself an engine pass, so each arm extracts its own glossary; ten of the
thirty-six batches carry a glossary block in one off arm and not in the other,
with identical batch membership. Prompt inequality therefore confounds
recomposition with glossary resampling, and batch membership does not.

Nothing here makes a model request. Every input is a frozen artefact of the three
runs and the answer is a pure function of them.

Usage:
    python tools/drift_attribution.py --out docs/eval/results_e2
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402

RUN_DIR = ROOT / "examples" / "output" / "e2" / "r1"
SAMPLE = "Courier-en"

SOURCE_STAGE = "chain_builder"
TRANSLATED_STAGE = "il_translated"

# The arm each column of the table is, in the order the table reads them. The
# first off arm is the A/B reference: the changed set is measured against it,
# which is what makes the row set the same kind of set A-12 counted.
REFERENCE = "chain_off_1"
CONTROL = "chain_off_2"
TREATMENT = "chain_on"
ARMS = (REFERENCE, CONTROL, TREATMENT)

CHAIN_MEMBER = "chain_member"
SAMPLING_NOISE = "sampling_noise"
REBATCH_EFFECT = "rebatch_effect"
RUN_VARIANCE = "run_variance"

# How much of a paragraph a table cell shows. The full strings are in the JSON.
EXCERPT_CHARS = 48


def _document(working_dir: Path, stage: str):
    path = working_dir / f"{checkpoint_stem(stage)}.xml"
    if not path.is_file():
        raise SystemExit(f"missing checkpoint: {path}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_checkpoint(path)


def _working_dir(arm: str) -> Path:
    return RUN_DIR / arm / "work" / SAMPLE


def _reference(page_number: int, index: int) -> str:
    """A paragraph as the rest of this project names one: 1-based page, 0-based slot."""
    return f"p{page_number + 1}#{index}"


def read_arm(arm: str) -> dict:
    """One arm reduced to what an attribution needs: source, target, prompt, chain."""
    working_dir = _working_dir(arm)
    source = _document(working_dir, SOURCE_STAGE)
    translated = _document(working_dir, TRANSLATED_STAGE)

    rows: dict[str, dict] = {}
    by_debug_id: dict[str, str] = {}
    for page in source.page:
        for index, paragraph in enumerate(page.pdf_paragraph):
            key = _reference(page.page_number, index)
            rows[key] = {
                "reference": key,
                "page": page.page_number + 1,
                "index": index,
                "source": paragraph.unicode or "",
                "layout_label": paragraph.layout_label,
                "chain_id": paragraph.chain_id,
                "chain_index": paragraph.chain_index,
                "translation": None,
                "prompt_sha256": [],
                "batch": None,
            }
            if paragraph.debug_id:
                by_debug_id[paragraph.debug_id] = key

    for page in translated.page:
        for index, paragraph in enumerate(page.pdf_paragraph):
            key = _reference(page.page_number, index)
            if key in rows:
                rows[key]["translation"] = paragraph.unicode or ""

    trace_path = RUN_DIR / arm / "prompt_trace.json"
    chain_prompts = []
    if trace_path.is_file():
        with trace_path.open(encoding="utf-8") as f:
            trace = json.load(f)
        for entry in trace:
            sha = entry.get("prompt_sha256")
            if sha is None:
                continue
            if entry["kind"] == "chain":
                chain_prompts.append(sha)
                continue
            members = tuple(
                sorted(
                    by_debug_id.get(debug_id, debug_id)
                    for debug_id in entry.get("paragraphs", ())
                )
            )
            for debug_id in entry.get("paragraphs", ()):
                key = by_debug_id.get(debug_id)
                if key is not None:
                    rows[key]["prompt_sha256"].append(sha)
                    rows[key]["batch"] = members
    for row in rows.values():
        row["prompt_sha256"] = sorted(set(row["prompt_sha256"]))

    return {
        "arm": arm,
        "working_dir": working_dir.relative_to(ROOT).as_posix(),
        "pages": len(source.page),
        "paragraphs": len(rows),
        "rows": rows,
        "chain_prompts": sorted(chain_prompts),
    }


def premises(arms: dict[str, dict]) -> dict:
    """What has to hold before a difference between arms means anything.

    Everything before the translator is deterministic, so the three arms must
    agree paragraph for paragraph about the document they are translating. If
    they do not, the columns are not about the same paragraph and no verdict
    below is worth reading.
    """
    reference = arms[REFERENCE]["rows"]
    faults: list[str] = []

    for arm in (CONTROL, TREATMENT):
        rows = arms[arm]["rows"]
        if set(rows) != set(reference):
            faults.append(f"{arm}: paragraph set differs from {REFERENCE}")
            continue
        for key, row in reference.items():
            if rows[key]["source"] != row["source"]:
                faults.append(f"{arm}: source text differs at {key}")
            if rows[key]["layout_label"] != row["layout_label"]:
                faults.append(f"{arm}: layout label differs at {key}")

    chain_positions = {
        arm: sorted(key for key, row in arms[arm]["rows"].items() if row["chain_id"])
        for arm in ARMS
    }
    if len({tuple(value) for value in chain_positions.values()}) != 1:
        faults.append(f"chain membership differs by arm: {chain_positions}")

    # The two off arms must have asked about the same batches: that is what
    # makes them two draws of one configuration rather than two experiments.
    batch_faults = [
        key
        for key, row in reference.items()
        if arms[CONTROL]["rows"][key]["batch"] != row["batch"]
    ]
    # Their prompt bytes need not agree, and do not. The glossary the automatic
    # extractor produced is itself sampled per arm, so a batch can carry a
    # glossary block in one arm and none in the other with the same members.
    prompt_faults = [
        key
        for key, row in reference.items()
        if arms[CONTROL]["rows"][key]["prompt_sha256"] != row["prompt_sha256"]
    ]
    glossary_only = [key for key in prompt_faults if key not in set(batch_faults)]
    # The same fact counted in batches rather than paragraphs, which is the unit
    # the glossary block belongs to: one block per request, not per paragraph.
    differing_batches = {
        reference[key]["batch"]
        for key in glossary_only
        if reference[key]["batch"] is not None
    }
    total_batches = {
        row["batch"] for row in reference.values() if row["batch"] is not None
    }

    return {
        "documents_identical_before_translation": not faults,
        "off_arm_batches_identical": not batch_faults,
        "off_arm_batch_faults": sorted(batch_faults)[:20],
        "off_arm_prompt_differences": len(prompt_faults),
        "off_arm_prompt_differences_with_identical_batch": len(glossary_only),
        "off_arm_batches": len(total_batches),
        "off_arm_batches_with_a_differing_prompt": len(differing_batches),
        "chain_members": chain_positions[TREATMENT],
        "faults": faults[:20],
    }


def gap01_verdict(row: dict) -> str:
    """The rule D3 GAP-01 states, over the three translation columns alone."""
    if row["chain_member"]:
        return CHAIN_MEMBER
    if row["off1"] != row["off2"]:
        return SAMPLING_NOISE
    return REBATCH_EFFECT


def classify(row: dict) -> str:
    """The reported verdict: the rule above, with the batch evidence applied.

    Only the last branch differs. A row the two off draws agree about is
    attributed to recomposition when the batch it was asked about was in fact
    recomposed, and to between-run variance when it was not -- there the on arm
    asked an identical question of an identical batch, so what separates it from
    the off arms is the occasion it was drawn on and nothing else.
    """
    verdict = gap01_verdict(row)
    if verdict != REBATCH_EFFECT:
        return verdict
    return REBATCH_EFFECT if row["batch_moved"] else RUN_VARIANCE


def attribute(arms: dict[str, dict]) -> dict:
    reference = arms[REFERENCE]["rows"]
    control = arms[CONTROL]["rows"]
    treatment = arms[TREATMENT]["rows"]

    matched = [
        key
        for key in sorted(reference, key=lambda item: (reference[item]["page"], reference[item]["index"]))
        if reference[key]["translation"] is not None
        and control[key]["translation"] is not None
        and treatment[key]["translation"] is not None
    ]

    noise_population = [
        key
        for key in matched
        if reference[key]["translation"] != control[key]["translation"]
    ]
    changed = [
        key
        for key in matched
        if reference[key]["translation"] != treatment[key]["translation"]
    ]

    recomposed = [
        key for key in matched if reference[key]["batch"] != treatment[key]["batch"]
    ]

    rows = []
    for key in changed:
        row = {
            "reference": key,
            "page": reference[key]["page"],
            "layout_label": reference[key]["layout_label"],
            "chain_member": bool(treatment[key]["chain_id"]),
            "source": reference[key]["source"],
            "off1": reference[key]["translation"],
            "off2": control[key]["translation"],
            "on": treatment[key]["translation"],
            "off1_equals_off2": reference[key]["translation"]
            == control[key]["translation"],
            "off2_equals_on": control[key]["translation"]
            == treatment[key]["translation"],
            "batch": {
                REFERENCE: list(reference[key]["batch"] or ()),
                TREATMENT: list(treatment[key]["batch"] or ()),
            },
            "batch_moved": reference[key]["batch"] != treatment[key]["batch"],
            "prompt_moved": reference[key]["prompt_sha256"]
            != treatment[key]["prompt_sha256"],
        }
        row["gap01_verdict"] = gap01_verdict(row)
        row["verdict"] = classify(row)
        rows.append(row)

    counts: dict[str, int] = {}
    gap01_counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
        gap01_counts[row["gap01_verdict"]] = (
            gap01_counts.get(row["gap01_verdict"], 0) + 1
        )

    # What b5.3's design could have seen at all. There an unchanged prompt was
    # served from the shared cache, so only a paragraph whose batch moved could
    # differ; that set is the like-for-like comparison against ledger row A-12.
    detectable = [row["reference"] for row in rows if row["batch_moved"]]
    detectable_counts: dict[str, int] = {}
    for row in rows:
        if not row["batch_moved"]:
            continue
        detectable_counts[row["verdict"]] = detectable_counts.get(row["verdict"], 0) + 1

    return {
        "matched": len(matched),
        "changed_reference_vs_treatment": len(changed),
        "noise_population": len(noise_population),
        "noise_rate": (
            round(len(noise_population) / len(matched), 6) if matched else None
        ),
        "recomposed_paragraphs": len(recomposed),
        "recomposed_pages": sorted({int(key[1:].split("#")[0]) for key in recomposed}),
        "changed_and_recomposed": detectable,
        "changed_and_recomposed_verdicts": detectable_counts,
        "verdict_counts": counts,
        "gap01_verdict_counts": gap01_counts,
        "rows": rows,
    }


def _table(rows: list[dict]) -> list[str]:
    lines = [
        "| # | paragraph | label | off1 | off2 | on | off1=off2 | batch moved | "
        "gap01 | verdict |",
        "| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for position, row in enumerate(rows, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(position),
                    f"`{row['reference']}`",
                    row["layout_label"] or "-",
                    f"`{_excerpt(row['off1'])}`",
                    f"`{_excerpt(row['off2'])}`",
                    f"`{_excerpt(row['on'])}`",
                    "yes" if row["off1_equals_off2"] else "no",
                    "yes" if row["batch_moved"] else "no",
                    row["gap01_verdict"],
                    row["verdict"],
                ]
            )
            + " |"
        )
    return lines


def markdown(report: dict) -> str:
    result = report["attribution"]
    a12 = [row for row in result["rows"] if row["batch_moved"]]
    lines = [
        "# R1 drift attribution (batch-e2.1)",
        "",
        f"Sample: `{SAMPLE}.pdf`. The three columns are the three runs of "
        "`tools/run_drift_trio.py`: two `chain_off` arms drawn independently "
        "under one configuration, and the frozen `chain_on` arm replayed from "
        "cache.",
        "",
        f"Matched paragraphs **{result['matched']}**; changed between "
        f"`{REFERENCE}` and `{TREATMENT}` **"
        f"{result['changed_reference_vs_treatment']}**; the two off arms "
        f"disagree about **{result['noise_population']}** of the "
        f"{result['matched']} on their own, which is this configuration's "
        f"run-to-run variance ({result['noise_rate']}). "
        f"**{result['recomposed_paragraphs']}** paragraphs sat in a batch the "
        f"chain pass recomposed, on pages {result['recomposed_pages']}.",
        "",
        "`gap01` is the rule D3 GAP-01 states, computed from the three text "
        "columns alone and recomputable by any reader from them; `verdict` is "
        "that rule with the batch evidence applied, which separates a "
        "recomposed batch from a third draw of an identical one.",
        "",
        "## 1. The A-12 set",
        "",
        "Changed **and** in a recomposed batch. This is the whole of what the "
        "shared-cache design of b5.3 could see at all -- there a paragraph "
        "whose batch did not move was served from the cache and was identical "
        "by construction -- so it is the like-for-like counterpart of ledger "
        f"row A-12. It has **{len(a12)}** members: "
        + ", ".join(f"`{row['reference']}`" for row in a12)
        + ".",
        "",
    ]
    lines += _table(a12)
    lines += ["", "Verdicts over this set:", ""]
    for verdict, count in sorted(result["changed_and_recomposed_verdicts"].items()):
        lines.append(f"- `{verdict}`: {count}")
    lines += [
        "",
        "## 2. Every changed paragraph",
        "",
        "The set above read against the whole document. The rows that are not "
        "in it changed without their batch moving, which is what the two off "
        "arms measure the size of.",
        "",
    ]
    lines += _table(result["rows"])
    lines += ["", "Verdict counts over this table:", ""]
    for verdict, count in sorted(result["verdict_counts"].items()):
        lines.append(
            f"- `{verdict}`: {count} "
            f"(GAP-01 rule: {result['gap01_verdict_counts'].get(verdict, 0)})"
        )
    lines.append("")
    return "\n".join(lines)


def _excerpt(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) <= EXCERPT_CHARS:
        return text
    return text[:EXCERPT_CHARS] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="directory to write the report to")
    args = parser.parse_args(argv)

    arms = {arm: read_arm(arm) for arm in ARMS}
    runs_path = RUN_DIR / "runs.json"
    runs = []
    if runs_path.is_file():
        with runs_path.open(encoding="utf-8") as f:
            runs = json.load(f)

    report = {
        "generated_by": "tools/drift_attribution.py",
        "sample": f"{SAMPLE}.pdf",
        "arms": {
            arm: {
                "working_dir": arms[arm]["working_dir"],
                "pages": arms[arm]["pages"],
                "paragraphs": arms[arm]["paragraphs"],
                "chain_prompts": arms[arm]["chain_prompts"],
            }
            for arm in ARMS
        },
        "runs": runs,
        "premises": premises(arms),
        "attribution": attribute(arms),
    }

    text = markdown(report)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        with (out / "drift_attribution.json").open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
        with (out / "drift_attribution.md").open("w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {out / 'drift_attribution.json'}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
