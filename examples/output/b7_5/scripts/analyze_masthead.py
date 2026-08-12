"""B7.5.2 evidence: what the masthead ruling reached, and the one site it cannot.

The two passes translate the same document with the same stack, so a paragraph
is the same paragraph in both and is matched by where it sits: file page, then
position on that page. Debug ids are minted afresh on every run and match
nothing across passes.

The claim under test has two halves. Every site the translator can see renders
the ruled name, identically, where before the two passes of b7.3 showed the
document rendering its own masthead two different ways. And the site the
translator cannot see is named: a paragraph the layout parser recovered as a
fallback line never reaches a prompt, so no ruling can reach it either. That
second half is not a defect of the ruling layer and is recorded as the standing
requirement it is.

The controls are the paragraphs no ruling names. They are here because the
claim is not that the ruling worked but that it worked and nothing else moved.

Writes masthead.evidence.json beside the report, and prints the tables the
report quotes.
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b7_5"
SAMPLE = "Courier-en"
PASSES = ("pass1", "pass2")

SOURCE_STAGE = "checkpoint.08_chain_builder.xml"
TARGET_STAGE = "checkpoint.09_il_translated.xml"

# Rich text tags and formula placeholders, taken out before two renderings are
# compared: they are not what a reader reads.
MARKUP = re.compile(r"<[^<>]*>|\{\s*v\s*\d+\s*\}")

# The word that identifies a masthead site in the source, whatever the display
# typography did to the rest of the line.
MASTHEAD_NEEDLE = "Courier"

# The layout class the parser gives a line it recovered outside any block. Such
# a paragraph is not offered to the translator, so nothing a ruling says can
# reach it. Named here because the report's second half is about this label.
UNREACHABLE_LABEL = "fallback_line"

# Sources whose rendering the report quotes but which no ruling names.
CONTROL_TERMS = ("biopiracy", "spinifex")


def work(which: str) -> Path:
    return OUT_DIR / which / "work" / SAMPLE


def read(path: Path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return checkpoint_module.load_checkpoint(path)


def plain(text: str | None) -> str:
    return MARKUP.sub("", text or "")


def load_pass(which: str) -> dict[str, dict]:
    source = read(work(which) / SOURCE_STAGE)
    target = read(work(which) / TARGET_STAGE)
    target_by_id = {
        paragraph.debug_id: paragraph
        for page in target.page
        for paragraph in page.pdf_paragraph or []
        if paragraph.debug_id
    }
    by_key: dict[str, dict] = {}
    for page_index, page in enumerate(source.page):
        for position, paragraph in enumerate(page.pdf_paragraph or []):
            translated = target_by_id.get(paragraph.debug_id)
            by_key[drop_cap.paragraph_reference(page_index + 1, position)] = {
                "page": page_index + 1,
                "layout_label": paragraph.layout_label,
                "source": paragraph.unicode or "",
                "target": plain(translated.unicode if translated else ""),
            }
    return by_key


def main() -> int:
    passes = {which: load_pass(which) for which in PASSES}
    ruling = hitl.load_decisions(
        ROOT / "reviews" / f"{SAMPLE}{hitl.DECISIONS_SUFFIX}",
        pages={row["page"] for row in passes["pass1"].values()},
        references=set(passes["pass1"]),
    )
    ruled_targets = {
        target
        for source, target in ruling.terms.items()
        if MASTHEAD_NEEDLE in source
    }

    # Why a site the ruling did not reach was not reached, captured by
    # probe_prompt_inputs.py: the text a batch is built from carries the rich
    # text markup the paragraph's style runs imply, and where a display masthead
    # is set in several styles that is not the joined rendering the draft shows.
    with (OUT_DIR / "prompt_inputs.evidence.json").open(encoding="utf-8") as f:
        offered = json.load(f)

    # A site is classified by what happened to it. A paragraph the parser
    # recovered outside any block is never offered to the translator, which its
    # rendering having survived the pass untranslated is the evidence of; of the
    # rest, the ones carrying the ruled name are the ones the ruling reached.
    sites = []
    for key, first in passes["pass1"].items():
        if MASTHEAD_NEEDLE not in first["source"]:
            continue
        second = passes["pass2"].get(key, {})
        carries = any(name in second.get("target", "") for name in ruled_targets)
        if first["layout_label"] == UNREACHABLE_LABEL:
            reach = "not_offered"
        elif carries:
            reach = "ruling_matched"
        else:
            reach = "offered_but_unmatched"
        sites.append(
            {
                "paragraph": key,
                "page": first["page"],
                "layout_label": first["layout_label"],
                "source": first["source"],
                "pass1": first["target"],
                "pass2": second.get("target", ""),
                "reach": reach,
                "carries_ruled_name": carries,
                "moved": first["target"] != second.get("target", ""),
            }
        )

    controls = []
    for key, first in passes["pass1"].items():
        second = passes["pass2"].get(key, {})
        for term in CONTROL_TERMS:
            if term in first["source"].lower():
                controls.append(
                    {
                        "paragraph": key,
                        "term": term,
                        "pass1": first["target"],
                        "pass2": second.get("target", ""),
                        "identical": first["target"] == second.get("target", ""),
                    }
                )
                break

    changed = [
        key
        for key, first in passes["pass1"].items()
        if first["target"] != passes["pass2"].get(key, {}).get("target", "")
    ]

    matched = [site for site in sites if site["reach"] == "ruling_matched"]
    unmatched = [site for site in sites if site["reach"] == "offered_but_unmatched"]
    not_offered = [site for site in sites if site["reach"] == "not_offered"]

    evidence = {
        "sample": SAMPLE,
        "ruling": {
            "terms": dict(ruling.terms),
            "page_kinds": {str(k): v for k, v in ruling.page_kinds.items()},
            "drop_caps": dict(ruling.drop_caps),
        },
        "ruled_masthead_targets": sorted(ruled_targets),
        "sites": sites,
        "ruling_matched": len(matched),
        "offered_but_unmatched": len(unmatched),
        "not_offered": len(not_offered),
        "matched_all_carry_ruled_name": all(
            site["carries_ruled_name"] for site in matched
        ),
        "matched_renderings": sorted({site["pass2"] for site in matched}),
        "unmatched_unmoved": [
            site["paragraph"] for site in unmatched if not site["moved"]
        ],
        "not_offered_untranslated": [
            site["paragraph"]
            for site in not_offered
            if site["pass1"] == site["source"] and site["pass2"] == site["source"]
        ],
        "controls": controls,
        "paragraphs": len(passes["pass1"]),
        "changed_paragraphs": changed,
        "offered_text": offered,
    }
    with (OUT_DIR / "masthead.evidence.json").open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)

    print(
        f"masthead sites: {len(sites)} ({len(matched)} the ruling matched, "
        f"{len(unmatched)} offered but unmatched, {len(not_offered)} not offered)"
    )
    for site in sites:
        print(
            f"\n  {site['paragraph']} p{site['page']} "
            f"[{site['layout_label']}] {site['reach']}"
        )
        print(f"    source: {site['source']}")
        print(f"    pass1 : {site['pass1']}")
        print(f"    pass2 : {site['pass2']}")
    print(f"\nrenderings where the ruling matched: {evidence['matched_renderings']}")
    print(f"every matched site carries the ruled name: "
          f"{evidence['matched_all_carry_ruled_name']}")
    print(f"offered but unmatched, and unmoved: {evidence['unmatched_unmoved']}")
    print(f"not offered and untranslated: {evidence['not_offered_untranslated']}")
    print(f"\nparagraphs={len(passes['pass1'])} changed={len(changed)} {changed}")
    print("\ncontrols (no ruling names them):")
    for control in controls:
        print(f"  {control['paragraph']} {control['term']}: "
              f"identical={control['identical']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
