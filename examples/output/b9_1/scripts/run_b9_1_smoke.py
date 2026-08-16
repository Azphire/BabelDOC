"""B9.1 smoke: the two Courier editions rerun under the B9.1 changes.

Two things changed for a translation run in this batch and both are visible
here. The direction is read from the corpus registry per sample, which turns
Courier-zh from a Chinese document translated into Chinese into one translated
into English; and every request now carries a standing instruction about how a
personal name is rendered, which is what the Courier-en contents page is reread
for.

The stack is not restated. This driver imports the F1 driver and runs its
``run_one`` with the output directory pointed here, so "the same run as F1, with
this batch's changes in it" is true by construction rather than by two lists of
switches being kept in step.

What it writes beside the runs is the comparison the delivery report quotes:
for each sample, every paragraph of the pages asked about, as F1 translated it
and as this run translates it, read from the two runs' translated intermediate
language rather than from the PDFs. The ruled terms are looked up in both, which
is what makes "the ruling still outranks the new default" a measurement.

Usage:
    python run_b9_1_smoke.py --all
    python run_b9_1_smoke.py --sample Courier-zh
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples" / "output" / "final" / "scripts"))

import run_final  # noqa: E402
from babeldoc.docvision.doclayout import DocLayoutModel  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import translation_style  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b9_1"
FINAL_DIR = ROOT / "examples" / "output" / "final"

RUN = "b9_1"

# The samples this smoke is about, and the pages of each the comparison is
# drawn from. Courier-en's contents page is where the F1 review found personal
# names left in their source script; Courier-zh's first page is the quick look
# at whether the corrected direction produced English at all.
SUBJECTS = {
    "Courier-en": (1,),
    "Courier-zh": (1,),
}

# The translated intermediate language of a run, which is what a paragraph's
# rendering is read from: the PDF has been through typesetting and font mapping
# and a string read back out of it is no longer the string the engine returned.
TRANSLATED_STAGE = "il_translated"

EVIDENCE = OUT_DIR / "evidence.json"


def working_dir(root: Path, sample: str) -> Path:
    return root / sample / "work" / sample


def translated_checkpoint(root: Path, sample: str) -> Path:
    return working_dir(root, sample) / f"{checkpoint_stem(TRANSLATED_STAGE)}.xml"


def paragraphs_of(checkpoint: Path, pages: tuple[int, ...]) -> dict[str, dict]:
    """Every paragraph of the named pages, keyed by where it sits on its page.

    Keyed by position rather than by debug id: an id is minted per run and two
    runs over the same document mint different ones, so an id would pair
    nothing with nothing. Position is stable here because everything before the
    translation stage is identical between the two runs being compared -- same
    input, same layout model, same parse -- which is the same assumption the
    render diff between two runs already rests on.
    """
    document = load_checkpoint(checkpoint)
    found: dict[str, dict] = {}
    for number in pages:
        if number > len(document.page):
            continue
        page = document.page[number - 1]
        for order, paragraph in enumerate(page.pdf_paragraph):
            found[f"p{number}#{order}"] = {
                "page": number,
                "order": order,
                "debug_id": paragraph.debug_id,
                "layout_label": paragraph.layout_label,
                "text": paragraph.unicode or "",
            }
    return found


def comparison(sample: str, pages: tuple[int, ...]) -> dict:
    """The same paragraphs as F1 rendered them and as this run renders them."""
    before_path = translated_checkpoint(FINAL_DIR, sample)
    after_path = translated_checkpoint(OUT_DIR, sample)
    before = paragraphs_of(before_path, pages) if before_path.is_file() else {}
    after = paragraphs_of(after_path, pages) if after_path.is_file() else {}
    rows = []
    for key in sorted(
        after, key=lambda name: (after[name]["page"], after[name]["order"])
    ):
        row = dict(after[key])
        row["position"] = key
        row["before"] = before.get(key, {}).get("text")
        row["after"] = row.pop("text")
        row["changed"] = row["before"] != row["after"]
        rows.append(row)
    return {
        "pages": list(pages),
        "before_checkpoint": str(before_path.relative_to(ROOT))
        if before_path.is_file()
        else None,
        "after_checkpoint": str(after_path.relative_to(ROOT))
        if after_path.is_file()
        else None,
        "paragraphs": rows,
    }


def ruled_terms(sample: str) -> dict[str, str]:
    """The terms a human ruled for this sample, source form to ruled rendering."""
    path = hitl.decisions_path(sample)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return dict(json.load(f).get("terms", {}))


def ruling_survival(sample: str) -> dict:
    """Where each ruled rendering occurs in each run's whole translation.

    Read over the whole document rather than over the compared pages: a ruled
    term is a decision about the document, and the assertion it answers for is
    that the new default did not move it anywhere.
    """
    terms = ruled_terms(sample)
    if not terms:
        return {"terms": {}}
    rendered = {}
    for label, root in (("before", FINAL_DIR), ("after", OUT_DIR)):
        path = translated_checkpoint(root, sample)
        if not path.is_file():
            rendered[label] = None
            continue
        document = load_checkpoint(path)
        text = "\n".join(
            paragraph.unicode or ""
            for page in document.page
            for paragraph in page.pdf_paragraph
        )
        rendered[label] = text
    return {
        "terms": {
            source: {
                "ruled": target,
                "in_before": None
                if rendered["before"] is None
                else target in rendered["before"],
                "in_after": None
                if rendered["after"] is None
                else target in rendered["after"],
                "source_form_in_after": None
                if rendered["after"] is None
                else source in rendered["after"],
            }
            for source, target in terms.items()
        }
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--evidence-only",
        action="store_true",
        help="rebuild the comparison from runs already on disk, spending nothing",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = list(SUBJECTS) if args.all else (args.sample or ["Courier-zh"])
    unknown = [sample for sample in wanted if sample not in SUBJECTS]
    if unknown:
        raise SystemExit(f"not a subject of this smoke: {unknown}")

    ledger: list[dict] = []
    if not args.evidence_only:
        run_final.load_dotenv()
        use_project_cache(ROOT)
        set_translate_rate_limiter(run_final.QPS)
        # The F1 driver writes into the directory it was written for; this smoke
        # is that driver pointed here, so the stack cannot drift between them.
        run_final.OUT_DIR = OUT_DIR
        run_final.RUN = RUN
        layout_model = DocLayoutModel.load_onnx()
        for sample in wanted:
            ledger.append(run_final.run_one(sample, layout_model))
        path = OUT_DIR / "runs.json"
        existing = []
        if path.exists():
            with path.open(encoding="utf-8") as f:
                existing = [
                    row
                    for row in json.load(f)
                    if row["sample"] not in {item["sample"] for item in ledger}
                ]
        with path.open("w", encoding="utf-8") as f:
            json.dump(existing + ledger, f, indent=2, ensure_ascii=False)

    policy = translation_style.load_style_config()
    evidence = {
        "person_names": policy.person_names,
        "samples": {
            sample: {
                "direction": list(run_final.corpus.direction_of(sample)),
                "comparison": comparison(sample, SUBJECTS[sample]),
                "ruling": ruling_survival(sample),
            }
            for sample in SUBJECTS
            if translated_checkpoint(OUT_DIR, sample).is_file()
        },
    }
    with EVIDENCE.open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"evidence -> {EVIDENCE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
