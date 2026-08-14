"""B8.4 evidence: what the loop did, what moved, and what the selection cost.

Reads what the runs left and writes one evidence file the report and the gate
are both derived from. Nothing here re-runs the pipeline and nothing spends a
credential: every number is taken from a sidecar, a snapshot, a checkpoint or a
produced PDF.

Four measurements, each from a source that does not share one with the others.

The subject, `p6#15`: what the loop was given for it, what it wrote back, and
the box and orientation flag either side of the write. From the driver's
paragraph snapshot, which is the document before and after the loop rather than
what the loop says about it.

The blast radius: per paragraph digests of the previous batch's typesetting
checkpoint against this run's, and page by page text of the previous batch's
PDF against this one's. The first says the translation stack reproduced itself;
the second says the rendering moved only where the document did.

The decision quality: how many findings each decision named, how many of those
the applicability rule would admit, and how many admissible findings were on
the table. Stated beside the same three numbers from the previous batch, whose
sidecars are in the repository. The rule is re-derived from the configuration
rather than read out of the loop's own verdicts, so the measurement and the
thing it measures do not share a source.

Usage:
    python analyze_repair_smoke.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402

BATCH_DIR = ROOT / "examples" / "output" / "b8_4"
SMOKE_DIR = BATCH_DIR / "smoke"
PREVIOUS_DIR = ROOT / "examples" / "output" / "b8" / "smoke"

SAMPLE = "Courier-en"
SUBJECT = "p6#15"

PARAGRAPHS_NAME = "paragraphs.json"
EVIDENCE_NAME = "evidence.json"

# The checkpoint both runs are compared at: the document as typesetting left
# it, which is before either loop touched anything.
TYPESET_STAGE = "typesetting"


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def repair_config():
    return react_config.load_repair_config(
        None, tuple(sorted(module.KIND for module in detectors.DETECTORS.values()))
    )


def admissible(issue: dict) -> bool:
    """Whether the applicability rule would admit one finding, from its evidence.

    Re-derived here from the configuration rather than read out of the loop's
    verdicts. The rule's third term, a floor on how many characters may be sent,
    is not checked: the detector's own floor on residue characters is at least
    as high, so every finding that exists already clears it.
    """
    action = repair_config().actions[actions.NAME]
    rule = action.applicability
    if not action.answers_for(issue.get("kind", "")):
        return False
    evidence = issue.get("evidence") or {}
    if evidence.get("layout_label") not in rule[react_config.ORPHAN_LABELS_KEY]:
        return False
    ratio = evidence.get("residue_ratio")
    if not isinstance(ratio, int | float):
        return False
    return float(ratio) >= float(rule[react_config.MIN_RATIO_KEY])


# One finding as the decision request states it: the id it is named by, and the
# evidence line the applicability rule is read against.
_OFFERED_ID = re.compile(r'^- id: "([^"]+)"')
_EVIDENCE = re.compile(r"^\s+evidence: (.*)$")
_FIELD = re.compile(r"(\w+)=('[^']*'|[^,]+)")


def offered_findings(trace: Path) -> list[dict] | None:
    """The findings the first decision request carried, as that request stated them.

    Parsed from the rendered prompt rather than from the detection sidecar,
    because the sidecar a run leaves describes the document after the loop: a
    finding a repair resolved is not in it, and counting a decision's naming
    against it would score every landed repair as a finding nobody named.
    """
    if not trace.exists():
        return None
    for line in trace.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("kind") != "decide_prompt":
            continue
        findings: list[dict] = []
        current: dict | None = None
        for row in entry["prompt_text"].splitlines():
            named = _OFFERED_ID.match(row)
            if named is not None:
                current = {"id": named.group(1), "kind": "", "evidence": {}}
                findings.append(current)
                continue
            if current is None:
                continue
            if row.strip().startswith("kind:"):
                current["kind"] = row.split(":", 1)[1].strip()
            evidence = _EVIDENCE.match(row)
            if evidence is not None:
                for key, value in _FIELD.findall(evidence.group(1)):
                    text = value.strip()
                    if text.startswith("'"):
                        current["evidence"][key] = text.strip("'")
                    else:
                        try:
                            current["evidence"][key] = float(text)
                        except ValueError:
                            current["evidence"][key] = text
        return findings
    return None


def selection_of(working: Path, trace: Path | None = None) -> dict:
    """What one run's first decision named, against what it could have named.

    The findings are the ones the request carried where a trace of it was kept.
    Without one the detection sidecar stands in, which is exact for a run that
    wrote no paragraph -- there being nothing for the recheck to have resolved.
    """
    repair = load(working / controller.REPORT_NAME)
    offered = offered_findings(trace) if trace is not None else None
    if offered is None:
        offered = load(working / detectors.REPORT_NAME).get("issues", [])
    available = [issue for issue in offered if admissible(issue)]
    iterations = repair.get("iterations") or []
    decision = (iterations[0].get("decision") or {}) if iterations else {}
    named = list(decision.get("issue_ids") or [])
    admitted = {issue["id"] for issue in available}
    return {
        "named": len(named),
        "eligible_named": len([item for item in named if item in admitted]),
        "eligible_available": len(available),
        "findings": len(offered),
        "stopped_because": repair.get("stopped_because"),
        "applications": repair.get("applications", 0),
        "treated": len(repair.get("treated") or []),
    }


def previous_working(sample: str) -> Path | None:
    run = PREVIOUS_DIR / sample / "run.json"
    if not run.exists():
        return None
    return ROOT / load(run)["working_dir"]


def paragraph_digests(path: Path) -> dict[str, str]:
    """One digest per paragraph of a checkpoint, by the reference it is named by."""
    from lxml import etree

    root = etree.fromstring(
        checkpoint_module.read_checkpoint_text(path).encode("utf-8")
    )
    digests: dict[str, str] = {}
    for position, node in enumerate(root.findall("page")):
        label = node.get("pageNumber")
        label = int(label) + 1 if label is not None else position + 1
        for index, paragraph in enumerate(node.findall("pdfParagraph")):
            digests[f"p{label}#{index}"] = hashlib.sha256(
                etree.tostring(paragraph)
            ).hexdigest()
    return digests


def page_texts(pdf: Path) -> list[str]:
    with pymupdf.open(pdf) as document:
        return [page.get_text() for page in document]


def blast_radius(working: Path, previous: Path | None, produced: Path, was: Path) -> dict:
    stem = checkpoint_module.checkpoint_stem(TYPESET_STAGE)
    mine = paragraph_digests(working / f"{stem}.xml")
    record: dict = {"paragraphs_compared": len(mine)}
    if previous is not None and (previous / f"{stem}.xml").exists():
        theirs = paragraph_digests(previous / f"{stem}.xml")
        differing = sorted(
            reference
            for reference in set(mine) | set(theirs)
            if mine.get(reference) != theirs.get(reference)
        )
        record["changed_before_repair"] = differing
        record["stack_reproduced"] = not differing
    repair = load(working / controller.REPORT_NAME)
    conservation = repair["conservation"]
    record["touched_by_repair"] = conservation["touched_refs"]
    record["changed_by_repair"] = conservation["changed_refs"]
    record["changed_outside_touched"] = conservation["changed_outside_touched"]
    record["pdf_pages_of_touched"] = sorted(
        {int(reference.split("#")[0][1:]) for reference in conservation["touched_refs"]}
    )
    if produced.exists() and was.exists():
        mine_pages = page_texts(produced)
        their_pages = page_texts(was)
        record["pdf_pages_changed"] = sorted(
            index + 1
            for index in range(max(len(mine_pages), len(their_pages)))
            if mine_pages[index : index + 1] != their_pages[index : index + 1]
        )
    else:
        record["pdf_pages_changed"] = []
    return record


def subject_evidence(working: Path, destination: Path) -> dict:
    issues = load(working / detectors.REPORT_NAME).get("issues", [])
    detected = [
        issue for issue in issues if SUBJECT in (issue.get("paragraph_refs") or ())
    ]
    snapshot = load(destination / PARAGRAPHS_NAME)
    before = snapshot["before"].get(SUBJECT) or {}
    after = snapshot["after"].get(SUBJECT) or {}
    repair = load(working / controller.REPORT_NAME)
    offered = ""
    written = ""
    for iteration in repair.get("iterations") or []:
        for row in iteration.get("executed") or []:
            if row.get("paragraph_ref") != SUBJECT:
                continue
            offered = row.get("source_text") or offered
            written = row.get("translated_text") or written
    return {
        "detected": detected,
        "source_offered": offered,
        "translation_written": written,
        "rendered_before": before.get("text", ""),
        "rendered_after": after.get("text", ""),
        "box_before": before.get("box"),
        "box_after": after.get("box"),
        "vertical_before": before.get("vertical"),
        "vertical_after": after.get("vertical"),
        "layout_label": after.get("layout_label"),
        "changed": SUBJECT in snapshot.get("changed", []),
    }


def landed(ledger) -> list[dict]:
    """Every paragraph a repair landed on, with its box either side of the write.

    The box is the property a landed repair may not change: a rendering that
    needed more room than the paragraph had would have rearranged the page, and
    the write-back refuses one. Reported per paragraph so the claim is checkable
    rather than asserted once over the corpus.
    """
    rows: list[dict] = []
    for row in ledger:
        sample = Path(row["sample"]).stem
        repair = load(ROOT / row["working_dir"] / controller.REPORT_NAME)
        snapshot = load(SMOKE_DIR / sample / "paragraphs.json")
        for reference in repair["conservation"]["touched_refs"]:
            before = snapshot["before"].get(reference) or {}
            after = snapshot["after"].get(reference) or {}
            rows.append(
                {
                    "sample": row["sample"],
                    "paragraph_ref": reference,
                    "box_before": before.get("box"),
                    "box_after": after.get("box"),
                    "box_held": before.get("box") == after.get("box"),
                    "vertical": after.get("vertical"),
                    "text_before": before.get("text", ""),
                    "text_after": after.get("text", ""),
                }
            )
    return rows


def refusals(ledger) -> list[dict]:
    """Every finding a translation was obtained for and then not written."""
    rows: list[dict] = []
    for row in ledger:
        repair = load(ROOT / row["working_dir"] / controller.REPORT_NAME)
        for iteration in repair.get("iterations") or []:
            for executed in iteration.get("executed") or []:
                if executed.get("changed"):
                    continue
                rows.append(
                    {
                        "sample": row["sample"],
                        "paragraph_ref": executed.get("paragraph_ref"),
                        "reason": executed.get("reason"),
                        "source_text": executed.get("source_text"),
                        "translated_text": executed.get("translated_text"),
                    }
                )
    return rows


def main() -> int:
    ledger = load(SMOKE_DIR / "runs.json")
    primary = next(row for row in ledger if row["sample"] == f"{SAMPLE}.pdf")
    working = ROOT / primary["working_dir"]
    destination = SMOKE_DIR / SAMPLE

    quality: dict[str, dict] = {}
    for row in ledger:
        sample = Path(row["sample"]).stem
        current = selection_of(
            ROOT / row["working_dir"], SMOKE_DIR / sample / "prompt_trace.jsonl"
        )
        previous = previous_working(sample)
        if previous is not None:
            was = selection_of(previous, PREVIOUS_DIR / sample / "prompt_trace.jsonl")
            current["previous_named"] = was["named"]
            current["previous_eligible_named"] = was["eligible_named"]
            current["previous_eligible_available"] = was["eligible_available"]
            current["previous_stopped_because"] = was["stopped_because"]
        else:
            for key in (
                "previous_named",
                "previous_eligible_named",
                "previous_eligible_available",
                "previous_stopped_because",
            ):
                current[key] = None
        quality[row["sample"]] = current

    evidence = {
        "run": primary,
        "loop": load(working / controller.REPORT_NAME),
        "issues_final": load(working / detectors.REPORT_NAME),
        "subject": subject_evidence(working, destination),
        "blast_radius": blast_radius(
            working,
            previous_working(SAMPLE),
            SMOKE_DIR / f"{SAMPLE}.b8_4.pdf",
            PREVIOUS_DIR / f"{SAMPLE}.b8_3.pdf",
        ),
        "decision_quality": quality,
        "landed": landed(ledger),
        "refusals": refusals(ledger),
    }
    path = SMOKE_DIR / EVIDENCE_NAME
    with path.open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(
        json.dumps(
            {
                "subject": {
                    key: evidence["subject"][key]
                    for key in ("source_offered", "rendered_after", "changed")
                },
                "blast_radius": evidence["blast_radius"],
                "landed": evidence["landed"],
                "decision_quality": quality,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
