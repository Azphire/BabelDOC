"""F2 analysis: turn six runs into the manifest and the mechanism tables.

Nothing here re-runs the pipeline. Every number is read from what the runs
wrote: the per-run record the driver kept, the sidecars in each working
directory, and the produced PDF itself. The point is a reviewer's index -- for
each mechanism, whether it fired, on which paragraph, and on which page of the
finished document -- so that a claim in the report can be checked by turning to
that page.

Page numbers are the PDF's own, one based, throughout. The sidecars count pages
from zero in some places and from one in others, so each reader below states
which it is reading and normalises to one.

Outputs, beside this script's parent directory:
    f2.manifest.json     what was run, with what, and what came out
    f2.mechanisms.json   per sample, what each mechanism did and where
    pagetext/<sample>.json   the produced text of every page, for reading

Usage:
    python analyze_f2.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "examples" / "output" / "F2"
MANIFEST = OUT_DIR / "f2.manifest.json"
MECHANISMS = OUT_DIR / "f2.mechanisms.json"
PAGETEXT_DIR = OUT_DIR / "pagetext"

# The sidecars this report reads, by the name the pass writes them under.
SIDECARS = (
    "page_classify.report.json",
    "chain_report.json",
    "chain_translation.report.json",
    "article_map.json",
    "article_context.report.json",
    "drop_cap.report.json",
    "drop_cap_apply.report.json",
    "hitl_apply.report.json",
    "line_split.report.json",
    "title_typeset.report.json",
    "issues.json",
    "react_repair.report.json",
    "prompts.manifest.json",
    "magazine_config_manifest.json",
)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def load(path: Path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def runs() -> list[dict]:
    with (OUT_DIR / "runs.json").open(encoding="utf-8") as f:
        return json.load(f)


def work_dir(record: dict) -> Path:
    return ROOT / Path(record["working_dir"])


def page_of(reference: str) -> int | None:
    """The one based page a paragraph reference names, as in ``p4#3``."""
    match = re.match(r"^p(\d+)#", reference or "")
    return int(match.group(1)) if match else None


def page_text(pdf: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(pdf) as document:
        return [page.get_text() for page in document]


def cjk_share(text: str) -> float:
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return 0.0
    cjk = sum(1 for c in letters if "一" <= c <= "鿿")
    return round(cjk / len(letters), 4)


def squeezed(text: str) -> str:
    """The text with every run of whitespace removed.

    A name set across a line break is two runs of text in the extracted stream
    with a newline between them, and a name set with the tracking a display face
    carries can arrive with a space between every glyph. Neither is a different
    name, so the comparison is made with the whitespace taken out of both sides.
    """
    return re.sub(r"\s+", "", text)


def where_rendered(pages: list[str], needle: str) -> list[int]:
    """One based pages whose text contains this string, ignoring whitespace."""
    if not needle:
        return []
    wanted = squeezed(needle)
    if not wanted:
        return []
    return [index + 1 for index, text in enumerate(pages) if wanted in squeezed(text)]


# --- the mechanisms ----------------------------------------------------------


def classifier_row(report) -> dict:
    if report is None:
        return {}
    pages = report.get("pages", [])
    kinds: dict[str, list[int]] = {}
    for entry in pages:
        # page_number is zero based here.
        kinds.setdefault(entry["final_kind"], []).append(entry["page_number"] + 1)
    return {
        "pages": len(pages),
        "kinds": {kind: sorted(where) for kind, where in sorted(kinds.items())},
        "ambiguous_pages": sorted(
            entry["page_number"] + 1 for entry in pages if entry.get("ambiguous")
        ),
        "vlm_used": sorted(
            entry["page_number"] + 1 for entry in pages if entry.get("vlm")
        ),
    }


def chain_row(detection, translation) -> dict:
    row: dict = {"boundaries": [], "chains": []}
    if detection is not None:
        for entry in detection.get("boundaries", []):
            row["boundaries"].append(
                {
                    "boundary": entry["boundary"],
                    "eligible": entry.get("eligible"),
                    "linked": entry.get("linked"),
                    "score": entry.get("score"),
                    "reason": entry.get("reason"),
                    "pair": entry.get("pair"),
                }
            )
        row["linked"] = sum(
            1 for e in detection.get("boundaries", []) if e.get("linked")
        )
    if translation is not None:
        for chain in translation.get("chains", []):
            row["chains"].append(
                {
                    "chain_id": chain["chain_id"],
                    # page_index is zero based in this sidecar.
                    "pages": sorted(
                        member["page_index"] + 1 for member in chain["members"]
                    ),
                    "members": [member["debug_id"] for member in chain["members"]],
                    "pair_class": chain.get("pair_class"),
                    "merged_source_chars": chain.get("merged_source_chars"),
                    "merged_translation_chars": chain.get("merged_translation_chars"),
                    "cuts": chain.get("redistribution", {}).get("cuts", []),
                    "fallback": chain.get("redistribution", {}).get("fallback"),
                }
            )
        row["escalated"] = translation.get("escalated", [])
        row["counts"] = translation.get("counts", {})
    return row


def article_row(mapping, context) -> dict:
    row: dict = {}
    if mapping is not None:
        row["articles"] = [
            {
                "article_id": article["article_id"],
                "pages": article["pages"],
                "paragraphs": len(article["paragraphs"]),
                "chains": article.get("chains", []),
            }
            for article in mapping.get("articles", [])
        ]
        row["unassigned_pages"] = mapping.get("unassigned", [])
        row["counts"] = mapping.get("counts", {})
    if context is not None:
        row["briefs"] = [
            {
                "article_id": article["article_id"],
                "pages": article.get("pages", []),
                "requested": article.get("requested"),
                "from_cache": article.get("from_cache"),
                "failed": article.get("brief_failed"),
                "title_translation": (article.get("brief") or {}).get(
                    "title_translation"
                ),
                "names": [
                    name["source"]
                    for name in (article.get("brief") or {}).get("names", [])
                ],
            }
            for article in context.get("articles", [])
        ]
        row["brief_counts"] = context.get("counts", {})
    return row


def paragraph_texts(work: Path) -> list[tuple[int, str, str]]:
    """(page, reference, text) for every paragraph of the finished document.

    Read from the typesetting checkpoint rather than from the produced PDF: the
    extractor returns a page's glyphs in the order they were painted, and a
    contents page whose records were laid out column by column comes back with
    two records interleaved character by character. The checkpoint still holds
    each paragraph as one string, which is what a term has to be looked for in.
    """
    checkpoint = work / "checkpoint.11_typesetting.json"
    if not checkpoint.exists():
        return []
    with checkpoint.open(encoding="utf-8") as f:
        document = json.load(f)
    rows = []
    for index, page in enumerate(document.get("page", [])):
        for order, paragraph in enumerate(page.get("pdf_paragraph", []) or []):
            rows.append(
                (index + 1, f"p{index + 1}#{order}", paragraph.get("unicode") or "")
            )
    return rows


def where_written(paragraphs, needle: str) -> list[str]:
    """Paragraph references whose text carries this string, ignoring whitespace."""
    wanted = squeezed(needle)
    if not wanted:
        return []
    return [
        reference for _page, reference, text in paragraphs if wanted in squeezed(text)
    ]


def ruling_row(report, pages: list[str], paragraphs) -> dict:
    """Every ruled item, with what it matched and where it can be seen."""
    if report is None:
        return {}
    row: dict = {"decisions_file": report.get("decisions_file")}
    terms = report.get("terms") or {}
    matches = {entry["source"]: entry for entry in terms.get("matches", [])}
    rows = []
    for entry in terms.get("entries", []):
        source = entry["source"]
        matched = matches.get(source, {})
        rows.append(
            {
                "source": source,
                "target": entry["target"],
                "matched_prompt_count": matched.get("matched_prompt_count", 0),
                "written_in_paragraphs": where_written(paragraphs, entry["target"]),
                "source_left_in_paragraphs": where_written(paragraphs, source),
                "rendered_on_pages": where_rendered(pages, entry["target"]),
                "source_still_on_pages": where_rendered(pages, source),
            }
        )
    row["terms"] = rows
    row["auto_glossary_kept"] = terms.get("auto_glossary_kept")
    row["dropped_from_auto"] = [
        entry["source"] for entry in terms.get("dropped_from_auto", [])
    ]
    row["page_kinds"] = report.get("page_kinds", [])
    row["drop_caps"] = report.get("drop_caps", [])
    return row


def drop_cap_row(marks, applied) -> dict:
    row: dict = {}
    if marks is not None:
        row["candidates"] = [
            {
                "paragraph": entry["paragraph"],
                "page": entry["page"],
                "initial": entry["first_run"],
                "size_ratio": entry["size_ratio"],
                "opens_article": entry.get("opens_article"),
                "body_rank": entry.get("body_rank"),
            }
            for entry in marks.get("candidates", [])
        ]
    if applied is not None:
        row["decisions"] = [
            {
                "paragraph": entry["paragraph"],
                "page": entry["page"],
                "decision": entry["decision"],
                "source": entry["source"],
                "merged": entry.get("merged"),
                "initial": entry.get("initial"),
                "unicode_after": entry.get("unicode_after"),
            }
            for entry in applied.get("decisions", [])
        ]
        row["totals"] = applied.get("totals", {})
        row["default_decision"] = applied.get("default_decision")
    return row


def line_split_row(report) -> dict:
    if report is None:
        return {}
    pages = report.get("pages", [])
    return {
        "declared_pages": [entry["page"] for entry in pages if entry.get("declared")],
        "split": [
            {
                "page": entry["page"],
                "paragraphs": entry["paragraphs"],
                "split_paragraphs": entry["split_paragraphs"],
                "exempt_paragraphs": entry["exempt_paragraphs"],
                "lines_before": entry["lines_before"],
                "lines_after": entry["lines_after"],
            }
            for entry in pages
            if entry.get("declared")
        ],
        "exemptions": report.get("exemptions", []),
        "max_line_chars": report.get("max_line_chars"),
        "min_text_length": report.get("min_text_length"),
    }


def title_row(report) -> dict:
    if report is None:
        return {}
    titles = report.get("titles", [])
    by_disposition: dict[str, list[str]] = {}
    for entry in titles:
        by_disposition.setdefault(entry["disposition"], []).append(entry["reference"])
    return {
        "titles": len(titles),
        "by_disposition": {
            name: sorted(refs) for name, refs in sorted(by_disposition.items())
        },
        "single_line": [
            {
                "reference": entry["reference"],
                "page": entry["page"],
                "lines_before": entry.get("lines_before"),
                "scale": entry.get("scale"),
            }
            for entry in titles
            if entry["disposition"] == "single_line"
        ],
        "escalations": report.get("escalations", []),
        "duplicates": report.get("duplicates", []),
        "title_min_scale": report.get("title_min_scale"),
        "totals": report.get("totals", {}),
    }


def issue_row(issues) -> dict:
    if issues is None:
        return {}
    rows = issues.get("issues", issues) if isinstance(issues, dict) else issues
    by_kind: dict[str, list[str]] = {}
    for entry in rows:
        by_kind.setdefault(entry["kind"], []).append(entry["id"])
    return {
        "total": len(rows),
        "by_kind": {kind: len(ids) for kind, ids in sorted(by_kind.items())},
        "ids_by_kind": {kind: sorted(ids) for kind, ids in sorted(by_kind.items())},
        "findings": [
            {
                "id": entry["id"],
                "kind": entry["kind"],
                "page": entry.get("page"),
                "refs": entry.get("paragraph_refs", []),
                "excerpt": (entry.get("evidence") or {}).get("excerpt"),
                "layout_label": (entry.get("evidence") or {}).get("layout_label"),
            }
            for entry in rows
        ],
    }


def repair_row(report) -> dict:
    if report is None:
        return {}
    iterations = []
    for entry in report.get("iterations", []):
        decision = entry.get("decision") or {}
        executed = entry.get("executed") or []
        iterations.append(
            {
                "detected": entry.get("detected", {}),
                "decision_action": decision.get("action"),
                "decision_ids": decision.get("issue_ids", []),
                "decision_reason": decision.get("reason"),
                "from_cache": decision.get("from_cache"),
                "rounds": [
                    {
                        "kind": round_entry.get("kind"),
                        "action": (round_entry.get("decision") or {}).get("action"),
                        "offered": len(round_entry.get("offered_ids", [])),
                        "named": (round_entry.get("decision") or {}).get(
                            "issue_ids", []
                        ),
                        "vocabulary": round_entry.get("vocabulary"),
                        "written": round_entry.get("written"),
                        "reason": (round_entry.get("decision") or {}).get("reason"),
                    }
                    for round_entry in entry.get("rounds", [])
                ],
                "executed": [
                    {
                        "issue_id": item.get("issue_id"),
                        "reference": item.get("paragraph_ref"),
                        "page": page_of(item.get("paragraph_ref") or ""),
                        "accepted": item.get("accepted"),
                        "changed": item.get("changed"),
                        "state": (item.get("geometry") or {}).get("state"),
                        "shift": (item.get("geometry") or {}).get("shift"),
                        "scale": (item.get("geometry") or {}).get("scale"),
                        "overflow_before": (item.get("geometry") or {}).get(
                            "overflow_before"
                        ),
                        "overflow_after": (item.get("geometry") or {}).get(
                            "overflow_after"
                        ),
                        "translated_text": item.get("translated_text"),
                        "source_text": item.get("source_text"),
                        "reason": item.get("reason"),
                    }
                    for item in executed
                ],
            }
        )
    return {
        "applications": report.get("applications"),
        "iterations_run": report.get("iterations_run"),
        "stopped_because": report.get("stopped_because"),
        "kind_order": report.get("kind_order"),
        "conservation": report.get("conservation"),
        "final": report.get("final"),
        "final_untreated": report.get("final_untreated"),
        "treated": report.get("treated"),
        "iterations": iterations,
    }


def main() -> int:
    PAGETEXT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_samples = []
    mechanism_samples = []
    for record in runs():
        sample = Path(record["sample"]).stem
        work = work_dir(record)
        pdf = ROOT / Path(record["pdf"])
        pages = page_text(pdf)
        with (PAGETEXT_DIR / f"{sample}.json").open(
            "w", encoding="utf-8", newline="\n"
        ) as f:
            json.dump(
                [{"page": index + 1, "text": text} for index, text in enumerate(pages)],
                f,
                ensure_ascii=False,
                indent=1,
            )

        sidecars = {name: load(work / name) for name in SIDECARS}
        paragraphs = paragraph_texts(work)
        whole = "".join(pages)
        manifest_samples.append(
            {
                "sample": sample,
                "input": {
                    "path": f"examples/input/{sample}.pdf",
                    "pages": record["input_pages"],
                },
                "direction": f"{record['lang_in']} -> {record['lang_out']}",
                "pdf": {
                    "path": str(pdf.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": record["pdf_sha256"],
                    "pages": record["output_pages"],
                    "characters": len(whole),
                    "cjk_share": cjk_share(whole),
                },
                "working_dir": record["working_dir"].replace("\\", "/"),
                "switches": record["switches"],
                "cost": {
                    "seconds": record["seconds"],
                    "requests": record["requests"],
                    "cache_hits": record["cache_hits"],
                    "api_calls": record["api_calls"],
                    "prompt_tokens": record["prompt_tokens"],
                    "completion_tokens": record["completion_tokens"],
                },
                "ruling": {
                    "path": (record["ruling"]["path"] or "").replace("\\", "/") or None,
                    "sha256": record["ruling"]["sha256"],
                    "present": record["ruling"]["present"],
                },
                "translation_style": record["translation_style"],
                "prompts": sidecars["prompts.manifest.json"],
                "configs": sidecars["magazine_config_manifest.json"],
                "sidecars": sorted(name for name in SIDECARS if (work / name).exists()),
            }
        )

        mechanism_samples.append(
            {
                "sample": sample,
                "classifier": classifier_row(sidecars["page_classify.report.json"]),
                "chains": chain_row(
                    sidecars["chain_report.json"],
                    sidecars["chain_translation.report.json"],
                ),
                "articles": article_row(
                    sidecars["article_map.json"],
                    sidecars["article_context.report.json"],
                ),
                "ruling": ruling_row(
                    sidecars["hitl_apply.report.json"], pages, paragraphs
                ),
                "drop_caps": drop_cap_row(
                    sidecars["drop_cap.report.json"],
                    sidecars["drop_cap_apply.report.json"],
                ),
                "line_split": line_split_row(sidecars["line_split.report.json"]),
                "titles": title_row(sidecars["title_typeset.report.json"]),
                "issues": issue_row(sidecars["issues.json"]),
                "repair": repair_row(sidecars["react_repair.report.json"]),
            }
        )

    totals = {
        "samples": len(manifest_samples),
        "pages": sum(entry["pdf"]["pages"] or 0 for entry in manifest_samples),
        "seconds": round(sum(e["cost"]["seconds"] for e in manifest_samples), 1),
        "requests": sum(e["cost"]["requests"] for e in manifest_samples),
        "cache_hits": sum(e["cost"]["cache_hits"] for e in manifest_samples),
        "api_calls": sum(e["cost"]["api_calls"] for e in manifest_samples),
        "prompt_tokens": sum(e["cost"]["prompt_tokens"] for e in manifest_samples),
        "completion_tokens": sum(
            e["cost"]["completion_tokens"] for e in manifest_samples
        ),
    }
    with MANIFEST.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(
            {
                "run": "F2",
                "model": "gpt-4o",
                "purpose": "full-stack review run over the whole corpus, for human reading",
                "driver": "examples/output/F2/scripts/run_f2.py",
                "analysis": "examples/output/F2/scripts/analyze_f2.py",
                "cache_db": "examples/cache/cache.v1.db",
                "totals": totals,
                "samples": manifest_samples,
            },
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        f.write("\n")
    with MECHANISMS.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(
            {"run": "F2", "samples": mechanism_samples},
            f,
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        )
        f.write("\n")
    print(json.dumps(totals, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
