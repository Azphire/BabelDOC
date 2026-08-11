"""B7.3 evidence: what the ruling changed between the two passes, and what it did not.

The two passes translate the same document with the same stack, so a paragraph
is the same paragraph in both and is matched by where it sits: file page, then
position on that page. Debug ids are minted afresh on every run and match
nothing across passes.

Every changed paragraph is classified, because the claim under test is not that
the ruling worked but that it worked and nothing else moved. The classification
is made from the prompt each paragraph was actually translated under, recorded
in translate_tracking.json, rather than guessed at from the text: a paragraph
whose prompt did not change and whose translation did is the only thing that
would be unaccounted for, and it is named as such.

Paragraphs are translated in batches and the glossary block is built for the
batch, so a ruled term in one paragraph rewrites the prompt of every paragraph
beside it. That is a real effect of a ruling and it is reported under its own
cause rather than folded into the ruled paragraphs or left unexplained.

Writes evidence.json beside the report, and prints the tables the report quotes.
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(r"d:\Codes\BabelDOC")
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b7_3"
SAMPLE = "Courier-en"
PASSES = ("pass1", "pass2")

SOURCE_STAGE = "checkpoint.08_chain_builder.xml"
TARGET_STAGE = "checkpoint.09_il_translated.xml"
CLASSIFIED_STAGE = "checkpoint.07_page_classifier.xml"

# Rich text tags and formula placeholders, taken out before two renderings are
# compared: they are not what a reader reads.
MARKUP = re.compile(r"<[^<>]*>|\{\s*v\s*\d+\s*\}")

# Sources whose rendering the report quotes but which no ruling names. They are
# the control: the ruling says nothing about them and they must not move.
CONTROL_TERMS = ("biopiracy", "spinifex")

# The issue-level furniture of this sample, as it appears in the source. The key
# it is reported under names the thing, not the page type that shares its name.
PUBLICATION_NAME = "Courier"

# The prompt is sectioned by markdown headings. Two of its sections are the ones
# a ruling can reach: the glossary tables, and the block the article brief and
# the running title are injected into.
SECTION_HEADING = "## "
GLOSSARY_SECTION = "## Glossary Tables"
CONTEXT_SECTION = "## Contextual Hints for Better Translation"


def work(which: str) -> Path:
    return OUT_DIR / which / "work" / SAMPLE


def read(path: Path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return XMLConverter().read_xml(str(path))


def plain(text: str | None) -> str:
    return MARKUP.sub("", text or "")


def paragraph_key(page_index: int, position: int) -> str:
    """The name a paragraph answers to in the review draft and in a ruling.

    Built by the same function the two files are built by, so a reference in
    this report and a reference in the decisions file are the same reference.
    """
    return drop_cap.paragraph_reference(page_index + 1, position)


def load_pass(which: str) -> dict:
    source = read(work(which) / SOURCE_STAGE)
    target = read(work(which) / TARGET_STAGE)
    classified = read(work(which) / CLASSIFIED_STAGE)
    by_key: dict[str, dict] = {}
    target_by_id = {
        paragraph.debug_id: paragraph
        for page in target.page
        for paragraph in page.pdf_paragraph or []
        if paragraph.debug_id
    }
    for page_index, page in enumerate(source.page):
        for position, paragraph in enumerate(page.pdf_paragraph or []):
            translated = target_by_id.get(paragraph.debug_id)
            by_key[paragraph_key(page_index, position)] = {
                "page": page_index + 1,
                "debug_id": paragraph.debug_id,
                "layout_label": paragraph.layout_label,
                "source": paragraph.unicode or "",
                "target": plain(translated.unicode if translated else ""),
            }
    with (work(which) / "article_map.json").open(encoding="utf-8") as f:
        article_map = json.load(f)
    context_path = work(which) / "article_context.report.json"
    briefs = {}
    if context_path.exists():
        with context_path.open(encoding="utf-8") as f:
            report = json.load(f)
        for entry in report.get("articles", ()):
            briefs[entry.get("article_id")] = entry
    return {
        "paragraphs": by_key,
        "pages": [
            {
                "page": index + 1,
                "kind": page.page_kind,
                "conf": page.page_kind_conf,
                "source": page.page_kind_source,
            }
            for index, page in enumerate(classified.page)
        ],
        "article_map": article_map,
        "briefs": briefs,
        "target_document": target,
    }


def prompts_by_source(which: str) -> dict[str, list[str]]:
    """The prompt text every paragraph was translated under, keyed by its source."""
    path = work(which) / "translate_tracking.json"
    with path.open(encoding="utf-8") as f:
        tracking = json.load(f)
    found: dict[str, list[str]] = {}
    for batches in tracking.values():
        for batch in batches:
            for paragraph in batch.get("paragraph", ()):
                text = paragraph.get("pdf_unicode") or ""
                for tracker in paragraph.get("llm_translate_trackers") or ():
                    found.setdefault(text, []).append(tracker["input"])
    return found


def sections_of(prompt: str) -> dict[str, str]:
    """One prompt split at its markdown headings, in the order they appear."""
    parts: dict[str, list[str]] = {}
    heading = ""
    for line in prompt.splitlines():
        if line.startswith(SECTION_HEADING) and not line.startswith("###"):
            heading = line.strip()
        parts.setdefault(heading, []).append(line)
    return {name: "\n".join(lines) for name, lines in parts.items()}


def changed_sections(before: str, after: str) -> list[str]:
    first, second = sections_of(before), sections_of(after)
    names = list(dict.fromkeys([*first, *second]))
    return [name for name in names if first.get(name) != second.get(name)]


def article_of(article_map: dict) -> dict[str, str]:
    """Which article each debug id belongs to, by that pass's own ids."""
    owner = {}
    for article in article_map.get("articles", ()):
        for paragraph in article.get("paragraphs", ()):
            owner[paragraph["debug_id"]] = article["article_id"]
    return owner


def brief_text(briefs: dict, article_id: str | None) -> str:
    entry = briefs.get(article_id) or {}
    brief = entry.get("brief")
    return json.dumps(brief, ensure_ascii=False, sort_keys=True) if brief else ""


def main() -> int:
    decisions_raw = json.loads(
        hitl.decisions_path(SAMPLE).read_text(encoding="utf-8")
    )
    ruled_terms = list(decisions_raw.get("terms", {}))
    runs = {which: load_pass(which) for which in PASSES}
    first, second = runs["pass1"], runs["pass2"]

    owner1, owner2 = article_of(first["article_map"]), article_of(second["article_map"])

    prompts = {which: prompts_by_source(which) for which in PASSES}

    changed, unchanged = [], 0
    for key, before in first["paragraphs"].items():
        after = second["paragraphs"][key]
        if before["target"] == after["target"]:
            unchanged += 1
            continue
        names_ruled = [term for term in ruled_terms if term in before["source"]]
        article_before = owner1.get(before["debug_id"])
        article_after = owner2.get(after["debug_id"])
        brief_before = brief_text(first["briefs"], article_before)
        brief_after = brief_text(second["briefs"], article_after)
        moved = (article_before is None) != (article_after is None)
        prompt_before = prompts["pass1"].get(before["source"], [])
        prompt_after = prompts["pass2"].get(after["source"], [])
        if prompt_before and prompt_after:
            sections = changed_sections(prompt_before[0], prompt_after[0])
        else:
            sections = None
        changed.append(
            {
                "paragraph": key,
                "page": before["page"],
                "layout_label": before["layout_label"],
                "ruled_terms": names_ruled,
                "article_membership_changed": moved,
                "brief_changed": brief_before != brief_after,
                "prompt_sections_changed": sections,
                "source": before["source"],
                "pass1": before["target"],
                "pass2": after["target"],
            }
        )
    for row in changed:
        sections = row["prompt_sections_changed"]
        if row["ruled_terms"]:
            row["cause"] = "ruled_term"
        elif sections is None:
            row["cause"] = "prompt_not_recorded"
        elif not sections:
            row["cause"] = "unexplained"
        elif CONTEXT_SECTION in sections:
            row["cause"] = "brief_scope"
        elif GLOSSARY_SECTION in sections:
            row["cause"] = "ruled_term_batch"
        else:
            row["cause"] = "unexplained"

    def occurrences(needle: str) -> list[dict]:
        rows = []
        for key, before in first["paragraphs"].items():
            if needle not in before["source"]:
                continue
            after = second["paragraphs"][key]
            rows.append(
                {
                    "paragraph": key,
                    "page": before["page"],
                    "layout_label": before["layout_label"],
                    "source": before["source"],
                    "pass1": before["target"],
                    "pass2": after["target"],
                    "identical": before["target"] == after["target"],
                }
            )
        return rows

    terms_evidence = {
        term: occurrences(term) for term in [*ruled_terms, *CONTROL_TERMS]
    }
    publication_name = occurrences(PUBLICATION_NAME)

    policy = load_taxonomy().policy_of
    page_kinds = []
    for before, after in zip(first["pages"], second["pages"], strict=True):
        page_kinds.append(
            {
                "page": before["page"],
                "pass1": before,
                "pass2": after,
                "pass1_policy": dict(policy(before["kind"])) if before["kind"] else None,
                "pass2_policy": dict(policy(after["kind"])) if after["kind"] else None,
            }
        )

    def drop_cap_decisions(which: str) -> list[dict]:
        document = runs[which]["target_document"]
        found = []
        for page_index, page in enumerate(document.page):
            for position, paragraph in enumerate(page.pdf_paragraph or []):
                verdict = getattr(paragraph, "drop_cap_decision", None)
                if verdict is None:
                    continue
                found.append(
                    {
                        "paragraph": paragraph_key(page_index, position),
                        "decision": verdict,
                        "candidate": getattr(paragraph, "drop_cap_candidate", None),
                    }
                )
        return found

    def articles_of(which: str) -> list[dict]:
        return [
            {
                "article_id": article["article_id"],
                "pages": article["pages"],
                "paragraphs": len(article["paragraphs"]),
                "chains": article.get("chains", []),
            }
            for article in runs[which]["article_map"].get("articles", ())
        ]

    with (OUT_DIR / "runs.json").open(encoding="utf-8") as f:
        ledger = {entry["pass"]: entry for entry in json.load(f)}

    apply_report = json.loads(
        (work("pass2") / hitl.REPORT_NAME).read_text(encoding="utf-8")
    )

    evidence = {
        "sample": SAMPLE,
        "decisions": decisions_raw,
        "totals": {
            "paragraphs": len(first["paragraphs"]),
            "unchanged": unchanged,
            "changed": len(changed),
            "by_cause": {
                cause: sum(1 for row in changed if row["cause"] == cause)
                for cause in (
                    "ruled_term",
                    "ruled_term_batch",
                    "brief_scope",
                    "prompt_not_recorded",
                    "unexplained",
                )
            },
        },
        "changed_paragraphs": changed,
        "terms": terms_evidence,
        "publication_name": publication_name,
        "page_kinds": page_kinds,
        "articles": {which: articles_of(which) for which in PASSES},
        "unassigned": {
            which: runs[which]["article_map"].get("unassigned") for which in PASSES
        },
        "drop_cap_decisions": {which: drop_cap_decisions(which) for which in PASSES},
        "apply_report": apply_report,
        "cost": {
            which: {
                key: ledger[which][key]
                for key in ("seconds", "requests", "cache_hits", "api_calls")
            }
            for which in PASSES
        },
    }
    path = OUT_DIR / "evidence.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)
    print(f"wrote {path}")
    print(json.dumps(evidence["totals"], ensure_ascii=False, indent=2))
    for cause in ("ruled_term_batch", "brief_scope", "prompt_not_recorded", "unexplained"):
        rows = [row for row in changed if row["cause"] == cause]
        print(f"{cause}: {len(rows)}")
        for row in rows:
            print(f"  {row['paragraph']} [{row['layout_label']}] {row['prompt_sections_changed']}")
            print(f"    EN: {row['source'][:150]}")
            print(f"    P1: {row['pass1'][:150]}")
            print(f"    P2: {row['pass2'][:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
