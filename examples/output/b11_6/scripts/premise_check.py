"""The seven premises PLAN_B11_6 asks to be verified before anything is built.

Each is checked against the tree as it stood when the batch opened -- the tag
b11.5 revision of every file the premise names -- so a premise stays checkable
after the batch has changed those files. What the plan asks for is a line
number per premise; what is recorded here is that and the fact each line
carries, because a line number alone stops being evidence the moment the file
moves.

Writes examples/output/b11_6/premise_check.json.

Usage:
    python premise_check.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

BASE_TAG = "b11.5"
OUT = ROOT / "examples" / "output" / "b11_6" / "premise_check.json"
MEASUREMENT = ROOT / "examples" / "output" / "b11_2" / "column_continuity.report.json"
INDENT_REPORT = (
    ROOT / "examples" / "output" / "b11_5" / "FD-en-v2" / "sidecars"
    / "indent_policy.report.json"
)


def at_base(path: str) -> str:
    """One file as the batch's base tag holds it."""
    result = subprocess.run(  # noqa: S603
        ["git", "show", f"{BASE_TAG}:{path}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def find(text: str, needle: str) -> int | None:
    """The 1-based line a string first appears on, or None."""
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    return None


def premise_1() -> dict:
    """indent_policy.json acts on body labels alone: no page gate, no box gate."""
    raw = at_base("configs/indent_policy.json")
    config = json.loads(raw)
    keys = sorted(config)
    return {
        "premise": (
            "configs/indent_policy.json reaches only body_labels; it declares no "
            "page level gate and no boxed exclusion"
        ),
        "body_labels_line": find(raw, '"body_labels"'),
        "body_labels": config["body_labels"],
        "keys": keys,
        "page_gate_keys": [k for k in keys if "eligib" in k or "page" in k],
        "boxed_keys": [k for k in keys if "box" in k],
        "holds": (
            config["body_labels"] == ["text", "plain text", "paragraph_hybrid"]
            and not [k for k in keys if "eligib" in k or "box" in k]
        ),
    }


def premise_2() -> dict:
    """page_types.json takes boolean policy flags, and no code names a type."""
    raw = at_base("configs/page_types.json")
    taxonomy_source = at_base("babeldoc/magazine/taxonomy.py")
    config = json.loads(raw)
    declared = sorted(
        {key for entry in config["page_types"] for key in entry["policy"]}
    )
    precedents = [
        name
        for name in ("chain_eligible", "preserve_line_structure")
        if name in declared
    ]
    names = {entry["name"] for entry in config["page_types"]}
    code = list((ROOT / "babeldoc" / "magazine").rglob("*.py"))
    offenders = []
    for path in code:
        text = path.read_text(encoding="utf-8")
        for name in names:
            if f'"{name}"' in text or f"'{name}'" in text:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{name}")
    return {
        "premise": (
            "the page type policy takes boolean flags, with chain_eligible and "
            "preserve_line_structure as precedents, and no code names a type"
        ),
        "optional_defaults_line": find(taxonomy_source, "OPTIONAL_POLICY_DEFAULTS"),
        "optional_boolean_line": find(
            taxonomy_source, "OPTIONAL_BOOLEAN_POLICY_KEYS"
        ),
        "declared_policy_keys": declared,
        "precedents": precedents,
        "page_type_names_in_code": sorted(offenders),
        "holds": len(precedents) == 2 and not offenders,
    }


def premise_3() -> dict:
    """The b11.2 measurement is in the tree and says what the plan cites."""
    if not MEASUREMENT.is_file():
        return {"premise": "the b11.2 column measurement is in the tree", "holds": False}
    with MEASUREMENT.open(encoding="utf-8") as f:
        report = json.load(f)
    pairs = sum(v["pairs"] for v in report["samples"].values() if "pairs" in v)
    linked = sum(v["would_link"] for v in report["samples"].values() if "pairs" in v)
    rows = {
        (sample, row["page"], row["tail_column"], row["head_column"]): row
        for sample, result in report["samples"].items()
        for row in result.get("rows", ())
    }
    fertilizer = rows.get(("FD-en-v2", 6, 1, 3))
    hyphen = rows.get(("FD-en-v2", 6, 0, 1))
    return {
        "premise": (
            "107 pairs, 24 would link, the FD p6 true positives are both caught, "
            "and the three honest treatments are in place"
        ),
        "pairs": pairs,
        "would_link": linked,
        "fertilizer_costs_score": None if fertilizer is None else fertilizer["score"],
        "fertilizer_costs_signals": None
        if fertilizer is None
        else fertilizer["signals"],
        "supply_chains_hyphen": None
        if hyphen is None
        else hyphen["tail_ends_on_hyphen"],
        "constants": report["constants"],
        "unweighed_signal": report["unweighed_signal"],
        "holds": (
            pairs == 107
            and linked == 24
            and fertilizer is not None
            and fertilizer["score"] == 1.0
            and hyphen is not None
            and hyphen["tail_ends_on_hyphen"] is True
            and report["constants"] == {"column_position": 1.0, "opener_prior": 0.0}
            and report["unweighed_signal"] == "tail_ends_on_hyphen"
        ),
    }


def premise_4() -> dict:
    """The appendix rules on 24 pairs, 16 true and 8 false, in the shape T2 names."""
    path = ROOT / "reviews" / "column_pairs.adjudication.json"
    if not path.is_file():
        return {"premise": "the adjudication is in the tree", "holds": False}
    with path.open(encoding="utf-8") as f:
        ruling = json.load(f)
    false_rows = [row for row in ruling["pairs"] if not row["continues"]]
    by_reason: dict[str, list[str]] = {}
    for row in false_rows:
        by_reason.setdefault(row["reason"], []).append(
            f"{row['sample']} p{row['page']} c{row['tail_column']}->c{row['head_column']}"
        )
    # The two hard cases are the false rows that are neither a redundant skip
    # nor the contents page, which is how the plan's appendix partitions them.
    common = sorted(by_reason, key=lambda reason: -len(by_reason[reason]))[:2]
    hard = [name for reason, names in by_reason.items() if reason not in common
            for name in names]
    return {
        "premise": "24 ruled pairs: 16 true, 8 false = 5 skips + 1 contents page + 2 hard",
        "counts": ruling["counts"],
        "false_by_reason": {
            reason: len(names) for reason, names in sorted(by_reason.items())
        },
        "hard_cases": sorted(hard),
        "holds": ruling["counts"]
        == {"pairs": 24, "continues": 16, "does_not_continue": 8}
        and len(hard) == 2,
    }


def premise_5() -> dict:
    """The chain machinery the plan builds on is where it says it is."""
    builder = at_base("babeldoc/magazine/chain_builder.py")
    translation = at_base("babeldoc/magazine/chain_translation.py")
    fill = at_base("babeldoc/magazine/chain_backfill.py")
    return {
        "premise": (
            "the builder walks adjacent page pairs, and joint translation, "
            "backfill and the conservation law already exist"
        ),
        "adjacent_pair_walk_line": find(builder, "for index in range(len(pages) - 1)"),
        "chain_plan_line": find(translation, "class ChainPlan"),
        "redistribute_line": find(fill, "def redistribute("),
        "verify_redistribution_line": find(fill, "def verify_redistribution("),
        "holds": all(
            value is not None
            for value in (
                find(builder, "for index in range(len(pages) - 1)"),
                find(translation, "class ChainPlan"),
                find(fill, "def redistribute("),
                find(fill, "def verify_redistribution("),
            )
        ),
    }


def premise_6() -> dict:
    """The b10.5 vector reading exists and names the collections it reads."""
    reflow = at_base("babeldoc/magazine/column_reflow.py")
    config = json.loads(at_base("configs/column_reflow.json"))
    collections = config["obstacle_collections"]
    return {
        "premise": "the reflow pass reads declared page level collections as obstacles",
        "obstacle_boxes_line": find(reflow, "def obstacle_boxes("),
        "obstacle_collections": collections,
        "holds": find(reflow, "def obstacle_boxes(") is not None
        and "pdf_curve" in collections
        and "pdf_rectangle" in collections,
    }


def premise_7() -> dict:
    """b11.5's own record shows the indent reaching the contents page."""
    if not INDENT_REPORT.is_file():
        return {"premise": "b11.5's indent record is in the tree", "holds": False}
    with INDENT_REPORT.open(encoding="utf-8") as f:
        report = json.load(f)
    by_page: dict[int, int] = {}
    for row in report["paragraphs"]:
        if row["decided"]:
            by_page[row["page"]] = by_page.get(row["page"], 0) + 1
    page3 = [row for row in report["paragraphs"] if row["page"] == 3]
    return {
        "premise": (
            "b11.5 decided 103 paragraphs on FD-en-v2, and page 3 -- the contents "
            "page -- is among them, which is the page gate's absence as evidence"
        ),
        "decided_total": report["totals"]["decided"],
        "decided_by_page": dict(sorted(by_page.items())),
        "page_3_decided": by_page.get(3, 0),
        "page_3_changed": sum(1 for row in page3 if row["before"] != row["after"]),
        "holds": report["totals"]["decided"] == 103 and by_page.get(3, 0) > 0,
    }


def main() -> int:
    premises = {
        "1": premise_1(),
        "2": premise_2(),
        "3": premise_3(),
        "4": premise_4(),
        "5": premise_5(),
        "6": premise_6(),
        "7": premise_7(),
    }
    record = {
        "batch": "b11_6",
        "base_tag": BASE_TAG,
        "premises": premises,
        "all_hold": all(entry["holds"] for entry in premises.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for name, entry in premises.items():
        print(f"{name}: {'holds' if entry['holds'] else 'FAILS'} -- {entry['premise']}")
    print(f"all_hold: {record['all_hold']}")
    print(f"report: {OUT}")
    return 0 if record["all_hold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
