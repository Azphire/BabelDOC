"""T4: conservation against the b10.5 on arm, and where each residue went.

The plan asks for the eighteen baseline residues one by one rather than as a
total, because b11.2 showed a total can fall for a reason that is not a repair:
three of its residues went away because a false positive stopped firing.

Residues are matched by their excerpt text, not by debug_id. Those are minted
per run (CLAUDE.md 5.13, GAP-32), so the same paragraph carries a different one
in every run and matching on them would compare nothing.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path("d:/Codes/BabelDOC")
BATCH = ROOT / "examples" / "output" / "b11_3"
BASELINE = ROOT / "examples" / "output" / "b10_5"
PREVIOUS = ROOT / "examples" / "output" / "b11_2"

SAMPLES = ("AramcoWorld-en-v2", "CERNCourier-en", "Courier-en",
           "FD-en-v2", "Vogue-en")

# The caption the plan singles out: it was sent as placeholders and came back
# with the words re-inserted and the spaces between them missing.
CAPTION_MARKER = "glacier"


def issues(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data.get("issues") or data.get("rows") or []


def paths_for(sample: str) -> dict:
    return {
        "now": BATCH / sample / "sidecars" / "issues.json",
        "previous": PREVIOUS / sample / "sidecars" / "issues.json",
        "baseline": BASELINE / sample / "on" / "work" / sample / "issues.json",
    }


def residues(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("kind") == "untranslated_residue"]


def excerpt_of(item: dict) -> str:
    """The residue's own text.

    It sits under ``evidence``; the detector puts what it read there and keeps
    the top level for the finding's identity and geometry.
    """
    return (item.get("evidence") or {}).get("excerpt", "")


def counts(rows: list[dict]) -> dict:
    return dict(collections.Counter(r["kind"] for r in rows))


def conservation(sample: str) -> dict:
    """Pages, paragraph counts and the page-local anchors, against the baseline."""
    path = BATCH / sample / "conservation.json"
    if not path.exists():
        return {"present": False}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    faults, pages = [], data.get("per_page") or {}
    if data.get("baseline_pages") is not None and data["pages"] != data["baseline_pages"]:
        faults.append(f"page count {data['baseline_pages']} -> {data['pages']}")
    anchors_moved, paragraphs_moved = [], []
    for label, row in pages.items():
        if "baseline_paragraphs" not in row:
            continue
        if row["paragraphs"] != row["baseline_paragraphs"]:
            paragraphs_moved.append(
                {"page": label, "baseline": row["baseline_paragraphs"],
                 "now": row["paragraphs"]})
        if set(row.get("text") or {}) != set(row.get("baseline_text") or {}):
            anchors_moved.append(label)
    return {
        "present": True,
        "pages": data.get("pages"),
        "baseline_pages": data.get("baseline_pages"),
        "page_count_conserved": not faults,
        "paragraph_counts_conserved": not paragraphs_moved,
        "paragraph_count_differences": paragraphs_moved,
        "anchor_sets_conserved": not anchors_moved,
        "pages_whose_anchor_set_moved": anchors_moved,
    }


def disposition(sample: str, against: str = "baseline") -> dict:
    """Each residue of the named run, and what became of it here.

    Two comparisons are kept, and they answer different questions. Against the
    b10.5 baseline is what the plan asks for, but that run predates b11.1's name
    policy, so a residue whose excerpt changed shape between the two counts as
    gone and a new one counts as appeared without this batch having done
    anything. Against b11.2 -- the tree immediately before this repair -- the
    only difference is the repair, which is the comparison that attributes.
    """
    p = paths_for(sample)
    base = residues(issues(p[against]))
    now = residues(issues(p["now"]))
    now_by_text = collections.Counter(excerpt_of(r) for r in now)
    consumed = collections.Counter()

    rows = []
    for item in base:
        text = excerpt_of(item)
        if consumed[text] < now_by_text[text]:
            consumed[text] += 1
            verdict = "still_a_residue"
        else:
            verdict = "gone"
        rows.append({"excerpt": text, "page": item.get("page"),
                     "layout_label": (item.get("evidence") or {}).get("layout_label"),
                     "verdict": verdict})
    appeared = []
    for text, n in now_by_text.items():
        base_n = sum(1 for r in base if excerpt_of(r) == text)
        for _ in range(max(0, n - base_n)):
            appeared.append({"excerpt": text, "verdict": "new_since_baseline"})
    return {"against": against,
            "baseline_total": len(base), "now_total": len(now),
            "rows": rows, "appeared": appeared,
            "gone": sum(1 for r in rows if r["verdict"] == "gone"),
            "still": sum(1 for r in rows if r["verdict"] == "still_a_residue")}


def caption_check() -> dict:
    """The one paragraph the plan asks about by name."""
    tracking = (BATCH / "FD-en-v2" / "work" / "FD-en-v2"
                / "translate_tracking.json")
    if not tracking.exists():
        return {"present": False}
    with tracking.open(encoding="utf-8") as f:
        data = json.load(f)
    found = []
    for root in ("page", "cross_page", "cross_column"):
        for group in data.get(root) or []:
            for para in group.get("paragraph") or []:
                if CAPTION_MARKER in (para.get("pdf_unicode") or ""):
                    found.append({"root": root,
                                  "source": para.get("pdf_unicode"),
                                  "request": para.get("input"),
                                  "reply": para.get("output")})
    record = {"present": bool(found), "records": found}
    if found:
        request = found[0]["request"] or ""
        record["request_is_placeholders"] = "{v" in request
        record["request_carries_the_words"] = CAPTION_MARKER in request
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = {"baseline": "examples/output/b10_5/<sample>/on",
           "previous_tree": "examples/output/b11_2/<sample>",
           "matched_by": "residue excerpt text, never debug_id",
           "samples": {}}
    for sample in SAMPLES:
        p = paths_for(sample)
        now, prev, base = (counts(issues(p["now"])), counts(issues(p["previous"])),
                           counts(issues(p["baseline"])))
        rose = {k: {"previous": prev.get(k, 0), "now": v}
                for k, v in now.items() if v > prev.get(k, 0)}
        out["samples"][sample] = {
            "conservation": conservation(sample),
            "detector_counts": {"baseline_b10_5": base, "previous_b11_2": prev,
                                "now_b11_3": now},
            "kinds_that_rose_against_the_previous_tree": rose,
            "residue_disposition_vs_b10_5": disposition(sample, "baseline"),
            "residue_disposition_vs_b11_2": disposition(sample, "previous"),
        }
    out["caption"] = caption_check()

    totals = {
        "kinds_that_rose_anywhere": {
            s: v["kinds_that_rose_against_the_previous_tree"]
            for s, v in out["samples"].items()
            if v["kinds_that_rose_against_the_previous_tree"]},
        "conservation_holds_everywhere": all(
            v["conservation"].get("page_count_conserved")
            and v["conservation"].get("paragraph_counts_conserved")
            and v["conservation"].get("anchor_sets_conserved")
            for v in out["samples"].values()),
    }
    out["totals"] = totals

    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
    print(f"conservation holds everywhere : {totals['conservation_holds_everywhere']}")
    print(f"kinds that rose vs b11.2      : {totals['kinds_that_rose_anywhere'] or 'none'}")
    for sample, v in out["samples"].items():
        a = v["residue_disposition_vs_b10_5"]
        b = v["residue_disposition_vs_b11_2"]
        print(f"  {sample:20s} vs b10.5 {a['baseline_total']:>3}->{a['now_total']:<3}"
              f" (gone {a['gone']}, new {len(a['appeared'])})"
              f"   | vs b11.2 {b['baseline_total']:>3}->{b['now_total']:<3}"
              f" (gone {b['gone']}, new {len(b['appeared'])})")
    cap = out["caption"]
    if cap.get("present"):
        print(f"caption request is placeholders: {cap.get('request_is_placeholders')}"
              f"  carries the words: {cap.get('request_carries_the_words')}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
