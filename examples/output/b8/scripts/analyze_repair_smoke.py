"""B8.3 evidence extraction: what the repair loop did to one real document.

Reads what the smoke run left behind and writes one evidence file the report is
quoted from. Nothing here decides anything; every number is a measurement of an
artefact on disk, and where a measurement comes out badly it is written down as
it came out.

Four measurements, and one note on how each is taken.

**The end to end trace of one finding.** The sidecar carries the finding, the
decision, the applicability verdicts and what was written; the driver's trace
carries the prompts those requests were rendered from. Joined on the paragraph
reference, they are the whole life of one repair.

**Where the ruled publication name stands, at every site.** The sites are the
ones batch-b7.5.2 enumerated, so the comparison is against a fixed list rather
than against whatever this run happens to find. A site's final rendering is the
text the repair wrote where the repair wrote one, and the text in the
typesetting checkpoint everywhere else -- which is sound exactly because the
loop's conservation check says the untouched paragraphs did not move, and that
check is re-derived here from the two checkpoints rather than believed.

**The blast radius.** Per-paragraph digests of the batch-b7.5.2 second pass
typesetting checkpoint against this run's, which answers whether the
translation stack reproduced itself; then the loop's own before-and-after over
the paragraphs it touched. The first is the control and the second is the
change, and a paragraph appearing in the second but not the first would be a
repair that reached outside its whitelist.

**The rendering.** Text extracted page by page from the batch-b7.5.2 mono PDF
and from this run's, diffed by line. This is the only measurement taken on the
artefact a reader would actually see.

Usage:
    python analyze_repair_smoke.py
"""

from __future__ import annotations

import dataclasses
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.detectors import residue  # noqa: E402
from babeldoc.magazine.drop_cap import paragraph_reference  # noqa: E402
from babeldoc.magazine.react import actions as react_actions  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react.config import MIN_RATIO_KEY  # noqa: E402
from babeldoc.magazine.react.config import load_repair_config  # noqa: E402

B8_DIR = ROOT / "examples" / "output" / "b8"
SMOKE_DIR = B8_DIR / "smoke"
PREVIOUS_DIR = ROOT / "examples" / "output" / "b7_5"

SAMPLE = "Courier-en"

# The finding the batch exists for, by the reference both batches name it by.
SUBJECT = "p6#15"

TYPESET_STAGE = "typesetting"

# The bound the repair action holds a finding to, read from its own declaration
# rather than written down, so the report quotes the configuration in force.
ACTION_MIN_RATIO = load_repair_config(None, ()).actions[
    react_actions.NAME
].applicability[MIN_RATIO_KEY]

EVIDENCE = SMOKE_DIR / "evidence.json"


def checkpoint_path(working: Path) -> Path:
    return working / f"{checkpoint_stem(TYPESET_STAGE)}.xml"


def paragraph_texts(document) -> dict[str, str]:
    """Every paragraph of a document as the page renders it, by reference."""
    texts: dict[str, str] = {}
    for label, page in hitl.labeled_pages(document):
        for index, paragraph in enumerate(page.pdf_paragraph or ()):
            texts[paragraph_reference(label, index)] = detectors.base.rendered_text(
                paragraph
            ).strip()
    return texts


def page_of(reference: str) -> int:
    return int(reference.split("#", 1)[0][1:])


def composition_runs(document, reference: str) -> list[dict]:
    """One paragraph's style runs, each with the band of the page it occupies.

    The detectors and the repair action both read a paragraph as the
    concatenation of its runs in list order. Whether that order is the order a
    reader reads them in is a separate question, and for a strip set across the
    page it is answered here rather than assumed: each run is reported with the
    vertical band its characters occupy, so the two orders can be compared.
    """
    page_label = page_of(reference)
    index = int(reference.split("#", 1)[1])
    for label, page in hitl.labeled_pages(document):
        if label != page_label:
            continue
        paragraphs = page.pdf_paragraph or ()
        if index >= len(paragraphs):
            return []
        paragraph = paragraphs[index]
        runs = []
        for position, member in enumerate(paragraph.pdf_paragraph_composition or ()):
            characters = []
            for field in dataclasses.fields(member):
                held = getattr(member, field.name, None)
                characters = getattr(held, "pdf_character", None) or []
                if characters:
                    break
            if not characters:
                continue
            tops = [
                character.box.y2 for character in characters if character.box is not None
            ]
            bottoms = [
                character.box.y for character in characters if character.box is not None
            ]
            runs.append(
                {
                    "position": position,
                    "text": "".join(
                        character.char_unicode or "" for character in characters
                    ),
                    "y_low": min(bottoms) if bottoms else None,
                    "y_high": max(tops) if tops else None,
                }
            )
        return runs
    return []


def pdf_lines(path: Path) -> list[list[str]]:
    """Text of each page, as non-empty lines in reading order."""
    pages: list[list[str]] = []
    with pymupdf.open(path) as document:
        for page in document:
            pages.append(
                [line.strip() for line in page.get_text().splitlines() if line.strip()]
            )
    return pages


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_trace(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def executed_rows(repair: dict) -> list[dict]:
    """Every application the loop attempted, iteration by iteration."""
    rows = []
    for iteration in repair.get("iterations", ()):
        for row in iteration.get("executed", ()):
            rows.append({"iteration": iteration["iteration"], **row})
    return rows


def written_texts(repair: dict, surviving_only: bool = True) -> dict[str, str]:
    """The text of every paragraph the loop wrote, by reference.

    A later iteration overwriting an earlier one wins, which is the order the
    rows are in. With ``surviving_only`` a rolled back iteration contributes
    nothing, because nothing it wrote is in the document any more; without it
    the rolled back writes are included, which is how what a repair produced is
    read separately from what survived the loop's own guard.
    """
    kept: dict[str, str] = {}
    for iteration in repair.get("iterations", ()):
        if surviving_only and iteration.get("outcome") != controller.OUTCOME_ADVANCED:
            continue
        for row in iteration.get("executed", ()):
            if row.get("changed"):
                kept[row["paragraph_ref"]] = row["translated_text"]
    return kept


def subject_trace(repair: dict, issues: dict, trace: list[dict]) -> dict:
    """The whole life of one finding, from detection to recheck."""
    detected = [
        issue
        for issue in issues.get("issues", ())
        if SUBJECT in issue.get("paragraph_refs", ())
    ]
    story: dict = {"reference": SUBJECT, "detected": detected, "iterations": []}
    for iteration in repair.get("iterations", ()):
        rows = [
            row
            for row in iteration.get("executed", ())
            if row.get("paragraph_ref") == SUBJECT
        ]
        rejections = [
            row
            for row in iteration.get("applicability", ())
            if row.get("paragraph_ref") == SUBJECT
        ]
        if not rows and not rejections:
            continue
        story["iterations"].append(
            {
                "iteration": iteration["iteration"],
                "outcome": iteration.get("outcome"),
                "decision": iteration.get("decision"),
                "request": iteration.get("request"),
                "executed": rows,
                "applicability": rejections,
                "resolved_ids": iteration.get("resolved_ids", []),
                "new_ids": iteration.get("new_ids", []),
                "recheck": iteration.get("recheck"),
            }
        )
    source = ""
    written = ""
    for row in executed_rows(repair):
        if row.get("paragraph_ref") == SUBJECT:
            source = row.get("source_text", "") or source
            written = row.get("translated_text", "") or written

    # Why the recheck answered as it did, in the detector's own arithmetic. A
    # repair that cut the defect without clearing the bound is a different
    # outcome from one that did nothing, and only the numbers separate them.
    config = detectors.detector_config()
    rule = config.residue_rule("zh")
    if rule is not None and source:
        script, min_ratio = rule
        story["residue"] = {
            "script": script,
            "detector_min_ratio": min_ratio,
            "action_min_ratio": ACTION_MIN_RATIO,
            "before": dict(
                zip(
                    ("residue_chars", "script_chars", "ratio"),
                    residue.measure(source, script),
                    strict=True,
                )
            ),
            "after": dict(
                zip(
                    ("residue_chars", "script_chars", "ratio"),
                    residue.measure(written, script),
                    strict=True,
                )
            )
            if written
            else None,
        }
    story["prompts"] = [
        record
        for record in trace
        if record.get("kind") == "orphan_prompt" and source and source in record.get(
            "prompt_text", ""
        )
    ]
    story["decision_prompts"] = [
        record for record in trace if record.get("kind") == "decide_prompt"
    ]
    return story


def ruled_name_table(before_texts, produced_texts, repaired_texts, ruling_targets) -> dict:
    """Every site batch-b7.5.2 enumerated, under both readings of "now".

    ``produced`` is the document the PDF was written from. ``repaired`` is the
    same document with the writes the loop's convergence guard undid put back,
    which is what the repair produced as opposed to what survived it. The two
    differ exactly where an iteration was rolled back, and reporting only the
    first would hide a repair that worked from a guard that reverted it, while
    reporting only the second would claim an output the reader does not have.
    """
    previous = load_json(PREVIOUS_DIR / "masthead.evidence.json")

    def carries(text: str) -> bool:
        return any(target in text for target in ruling_targets)

    rows = []
    for site in previous["sites"]:
        reference = site["paragraph"]
        produced = produced_texts.get(reference, "")
        repaired = repaired_texts.get(reference, "")
        rows.append(
            {
                "paragraph": reference,
                "page": site["page"],
                "layout_label": site["layout_label"],
                "source": site["source"],
                "b7_5_2_pass2": site["pass2"],
                "b7_5_2_reach": site["reach"],
                "b8_3_before_repair": before_texts.get(reference, ""),
                "b8_3_as_repaired": repaired,
                "b8_3_as_produced": produced,
                "carries_ruled_name_as_produced": carries(produced),
                "carries_ruled_name_as_repaired": carries(repaired),
                "moved_since_b7_5_2": produced != site["pass2"],
            }
        )
    return {
        "ruled_targets": list(ruling_targets),
        "sites": rows,
        "sites_total": len(rows),
        "sites_carrying_ruled_name": sum(
            1 for row in rows if row["carries_ruled_name_as_produced"]
        ),
        "sites_carrying_ruled_name_as_repaired": sum(
            1 for row in rows if row["carries_ruled_name_as_repaired"]
        ),
        "sites_not_carrying": [
            row["paragraph"]
            for row in rows
            if not row["carries_ruled_name_as_produced"]
        ],
    }


def main() -> int:
    working = SMOKE_DIR / SAMPLE / "work" / SAMPLE
    repair = load_json(working / controller.REPORT_NAME)
    issues = load_json(working / detectors.REPORT_NAME)
    trace = load_trace(SMOKE_DIR / SAMPLE / "prompt_trace.jsonl")

    typeset = load_checkpoint(checkpoint_path(working))
    now = paragraph_texts(typeset)
    then = paragraph_texts(
        load_checkpoint(checkpoint_path(PREVIOUS_DIR / "pass2" / "work" / SAMPLE))
    )
    stack_diff = sorted(
        reference
        for reference in set(now) | set(then)
        if now.get(reference) != then.get(reference)
    )

    written = written_texts(repair)
    attempted = written_texts(repair, surviving_only=False)
    produced = {**now, **written}
    repaired = {**now, **attempted}

    ruling = load_json(PREVIOUS_DIR / "masthead.evidence.json")
    ruled_name = ruled_name_table(
        now, produced, repaired, ruling["ruled_masthead_targets"]
    )

    previous_pdf = PREVIOUS_DIR / f"{SAMPLE}.pass2.pdf"
    current_pdf = SMOKE_DIR / f"{SAMPLE}.b8_3.pdf"
    before_pages, after_pages = pdf_lines(previous_pdf), pdf_lines(current_pdf)
    page_diffs = []
    for index in range(max(len(before_pages), len(after_pages))):
        old = before_pages[index] if index < len(before_pages) else []
        new = after_pages[index] if index < len(after_pages) else []
        if old == new:
            continue
        page_diffs.append(
            {
                "page": index + 1,
                "removed": [
                    line[2:]
                    for line in difflib.unified_diff(old, new, n=0, lineterm="")
                    if line.startswith("-") and not line.startswith("---")
                ],
                "added": [
                    line[2:]
                    for line in difflib.unified_diff(old, new, n=0, lineterm="")
                    if line.startswith("+") and not line.startswith("+++")
                ],
            }
        )

    conservation = repair.get("conservation", {})
    touched = set(conservation.get("touched_refs", ()))
    evidence = {
        "sample": SAMPLE,
        "run": load_json(SMOKE_DIR / SAMPLE / "run.json"),
        "loop": {
            "iterations_run": repair.get("iterations_run"),
            "stopped_because": repair.get("stopped_because"),
            "applications": repair.get("applications"),
            "final": repair.get("final"),
            "conservation": conservation,
            "iterations": [
                {
                    "iteration": item["iteration"],
                    "detected": item.get("detected"),
                    "detected_ids": item.get("detected_ids", []),
                    "outcome": item.get("outcome"),
                    "decision": item.get("decision"),
                    "recheck": item.get("recheck"),
                    "resolved_ids": item.get("resolved_ids", []),
                    "new_ids": item.get("new_ids", []),
                    "accepted": [
                        row["paragraph_ref"]
                        for row in item.get("executed", ())
                        if row.get("changed")
                    ],
                    "rejected": [
                        {"ref": row["paragraph_ref"], "reason": row["reason"]}
                        for row in [
                            *item.get("applicability", ()),
                            *(
                                row
                                for row in item.get("executed", ())
                                if not row.get("changed")
                            ),
                        ]
                    ],
                }
                for item in repair.get("iterations", ())
            ],
        },
        "issues_final": {
            "counts": issues.get("counts"),
            "by_reference": sorted(
                reference
                for issue in issues.get("issues", ())
                for reference in issue.get("paragraph_refs", ())
            ),
            "notes": issues.get("notes", []),
        },
        "subject": {
            **subject_trace(repair, issues, trace),
            "composition_runs": composition_runs(typeset, SUBJECT),
        },
        "ruled_name_sites": ruled_name,
        "blast_radius": {
            "stack_reproduced": not stack_diff,
            "paragraphs_compared": len(set(now) | set(then)),
            "changed_before_repair": stack_diff,
            "touched_by_repair": sorted(touched),
            "changed_by_repair": conservation.get("changed_refs", []),
            "changed_outside_touched": conservation.get("changed_outside_touched", []),
            "pdf_pages_changed": [entry["page"] for entry in page_diffs],
            "pdf_pages_of_touched": sorted({page_of(ref) for ref in touched}),
            "pdf_page_diffs": page_diffs,
        },
        "trace_records": {
            kind: sum(1 for record in trace if record.get("kind") == kind)
            for kind in ("decide_prompt", "orphan_prompt", "transport")
        },
    }

    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    with EVIDENCE.open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"wrote {EVIDENCE.relative_to(ROOT)}")
    print(
        json.dumps(
            {
                "iterations_run": evidence["loop"]["iterations_run"],
                "stopped_because": evidence["loop"]["stopped_because"],
                "applications": evidence["loop"]["applications"],
                "stack_reproduced": evidence["blast_radius"]["stack_reproduced"],
                "sites_carrying_ruled_name": ruled_name["sites_carrying_ruled_name"],
                "sites_total": ruled_name["sites_total"],
                "pdf_pages_changed": evidence["blast_radius"]["pdf_pages_changed"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
