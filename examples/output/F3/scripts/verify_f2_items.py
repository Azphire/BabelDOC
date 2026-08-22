"""Read the F3 documents back and state, item by item, what became of every
open item the F2 review listed.

F2 section c is the open items with the page each is visible on, and section d
is the fourteen anomalies found by turning all forty-one pages. This script does
not judge any of them: for each it states a fact that can be read off the
produced document -- a string is present or absent on a page, a finding is in
the run's own list or is not, a sidecar counts what it counts -- and prints that
fact beside the item. The reading is in the report.

Usage:
    python verify_f2_items.py [--arm warm]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "examples" / "output" / "F3"

# One probe per item. ``needles`` are strings looked for in the page's extracted
# text; ``absent`` are strings whose absence is the interesting fact. Both are
# reported either way -- the script states what it found, not what it wanted.
PROBES = [
    # --- section c ---
    {
        "id": "c.GAP-24",
        "kind": "findings",
        "detector": "out_of_page",
        "detail": "out_of_page findings and the label each carries",
    },
    {
        "id": "c.GAP-22/23",
        "kind": "findings",
        "detector": "text_text_collision",
        "detail": "text_text_collision findings that survived to the end",
    },
    {
        "id": "c.GAP-25",
        "kind": "repair",
        "detail": "what the repair loop chose, per kind",
    },
    {
        "id": "c.GAP-26",
        "kind": "text",
        "sample": "CERNCourier-en",
        "page": 1,
        "needles": ["快报"],
    },
    {
        "id": "c.leader-dots",
        "kind": "text",
        "sample": "Courier-en",
        "page": 1,
        "needles": [".4", ".12", ".14", ".36", ".44"],
    },
    {
        "id": "c.short-lines",
        "kind": "text",
        "sample": "Courier-zh",
        "page": 1,
        "absent": [
            "社论",
            "总编辑",
            "广角",
            "聚焦",
            "观点",
            "嘉宾",
            "深度阅读",
        ],
    },
    {
        "id": "c.short-lines.p3",
        "kind": "text",
        "sample": "Courier-zh",
        "page": 3,
        "absent": ["土著知识"],
    },
    {
        "id": "c.font-failure",
        "kind": "title",
        "sample": "FD-en-v2",
        "detail": "the escalated headings the title pass recorded",
    },
    # --- section d ---
    {
        "id": "d.A1",
        "kind": "text",
        "sample": "Courier-en",
        "page": 4,
        "absent": ["There are many more examples of how t", "raditional knowledge"],
    },
    {
        "id": "d.A2",
        "kind": "text",
        "sample": "Courier-zh",
        "page": 1,
        "needles": ["ecosyste", "this ty"],
    },
    {
        "id": "d.A3",
        "kind": "empty-page",
        "sample": "Vogue-en",
        "page": 2,
        "detail": "characters the produced page carries",
    },
    {
        "id": "d.A4",
        "kind": "text",
        "sample": "AramcoWorld-en-v2",
        "page": 9,
        "needles": ["lamic life has always emerged not through sameness"],
    },
    {
        "id": "d.A5",
        "kind": "text",
        "sample": "Courier-en",
        "page": 1,
        "needles": ["传统傣医学"],
    },
    {
        "id": "d.A6",
        "kind": "text",
        "sample": "CERNCourier-en",
        "page": 1,
        "needles": ["DAVIDE DE BIASIO", "DE BIASIO"],
    },
    {
        "id": "d.A7.cern",
        "kind": "text",
        "sample": "CERNCourier-en",
        "page": 3,
        "needles": ["“Th"],
    },
    {
        "id": "d.A7.vogue",
        "kind": "fragments",
        "sample": "Vogue-en",
        "detail": "fragment clusters the census still counts",
    },
    {
        "id": "d.A8",
        "kind": "text",
        "sample": "FD-en-v2",
        "page": 5,
        "needles": ["اقرأ", "اللغة"],
    },
    {
        "id": "d.A9",
        "kind": "text",
        "sample": "Courier-zh",
        "page": 5,
        "needles": ["heartbreaking"],
    },
    {
        "id": "d.A10",
        "kind": "text",
        "sample": "Courier-zh",
        "page": 5,
        "needles": ["巴西"],
    },
    {
        "id": "d.A11",
        "kind": "text",
        "sample": "AramcoWorld-en-v2",
        "page": 3,
        "needles": ["Tilya-Kori", "封面"],
    },
    {
        "id": "d.A12",
        "kind": "text",
        "sample": "AramcoWorld-en-v2",
        "page": 8,
        "needles": ["JAMIE S. SCOT T", "JAMIE S. SCOTT"],
    },
    {
        "id": "d.A13",
        "kind": "text",
        "sample": "Courier-en",
        "page": 5,
        "needles": ["发现什么都没有了"],
    },
    {
        "id": "d.A14",
        "kind": "text",
        "sample": "CERNCourier-en",
        "page": 1,
        "needles": ["CCJulAug26_Cover"],
    },
]


def page_texts(pdf: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(pdf) as document:
        return [page.get_text() for page in document]


def squeezed(text: str) -> str:
    return " ".join(text.split())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="warm")
    args = parser.parse_args(argv)

    arm = OUT_DIR / args.arm
    ledger = json.loads((arm / "runs.json").read_text(encoding="utf-8"))
    pdfs = {Path(row["sample"]).stem: ROOT / row["pdf"] for row in ledger}
    texts = {name: page_texts(path) for name, path in pdfs.items()}

    results = []
    for probe in PROBES:
        entry = {"id": probe["id"], "kind": probe["kind"]}
        if probe["kind"] in {"text", "empty-page"}:
            sample, page = probe["sample"], probe["page"]
            body = squeezed(texts[sample][page - 1])
            entry["sample"] = f"{sample} p{page}"
            entry["characters"] = len(body)
            entry["present"] = {
                needle: (needle in body) for needle in probe.get("needles", ())
            }
            entry["absent"] = {
                needle: (needle not in body) for needle in probe.get("absent", ())
            }
        elif probe["kind"] == "findings":
            rows = []
            for sample in sorted(pdfs):
                path = arm / sample / "sidecars" / "issues.json"
                if not path.exists():
                    continue
                issues = json.loads(path.read_text(encoding="utf-8"))
                wanted = probe["detector"]
                for finding in issues.get("issues") or ():
                    if finding.get("kind") != wanted:
                        continue
                    rows.append(
                        {
                            "sample": sample,
                            "kind": finding.get("kind"),
                            "refs": finding.get("paragraph_refs"),
                            "labels": (finding.get("evidence") or {}).get(
                                "layout_labels"
                            ),
                        }
                    )
                entry.setdefault("by_kind", {})[sample] = (
                    issues.get("counts") or {}
                ).get("by_kind")
            entry["findings"] = rows
        elif probe["kind"] == "repair":
            rows = []
            for sample in sorted(pdfs):
                report = arm / sample / "sidecars" / "react_repair.report.json"
                if not report.exists():
                    continue
                data = json.loads(report.read_text(encoding="utf-8"))
                applied = data.get("applications")
                chosen = []
                for iteration in data.get("iterations") or ():
                    decision = iteration.get("decision") or {}
                    if decision.get("action"):
                        chosen.append(
                            {
                                "action": decision["action"],
                                "from_cache": decision.get("from_cache"),
                                "issues": decision.get("issue_ids"),
                            }
                        )
                rows.append(
                    {
                        "sample": sample,
                        "rounds": len(data.get("iterations") or ()),
                        "chosen": chosen,
                        "applications": applied
                        if isinstance(applied, int)
                        else len(applied or []),
                        "final": len(data.get("final") or []),
                        "api_calls": data.get("api_calls"),
                    }
                )
            entry["repair"] = rows
        elif probe["kind"] == "title":
            path = arm / probe["sample"] / "sidecars" / "title_typeset.report.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = data.get("titles") or data.get("paragraphs") or []
            entry["escalated"] = [
                {
                    "reference": row.get("reference"),
                    "disposition": row.get("disposition"),
                    "scale": row.get("scale"),
                }
                for row in rows
                if row.get("disposition") == "floor_reached"
            ]
        elif probe["kind"] == "fragments":
            path = arm / probe["sample"] / "sidecars" / "fragment_stitch.report.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            entry["totals"] = data.get("totals")
            entry["census"] = data.get("census")
        results.append(entry)

    destination = OUT_DIR / f"f2_items.{args.arm}.json"
    with destination.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nwritten: {destination.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
