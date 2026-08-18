"""Export a drop cap review draft for the candidates a sample carries.

The candidate on FD-en-v2 page 8 is one the F1 review found by eye and the
marking pass used to miss, and it is now found. Nobody has ruled it, so the run
acts on it under the default its target language declares -- and the ruling
itself is the user's. This writes the draft that ruling is written on.

Into this batch's own tree rather than into ``reviews/``, through the review
layer's own directory override, for the reason every runner of this project keeps
export down: the files beside a ruling belong to the person who wrote it, and a
machine session that rewrote them would be overwriting an answer with a question.
Copying the draft into ``reviews/`` is the user's step.

No pipeline and no request: the candidates are recomputed from the checkpoint the
arm with the switch up already wrote, which is the document as the marking pass
found it.

Usage:
    python export_candidates.py --sample FD-en-v2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "examples" / "output" / "b9_4"
DRAFT_DIR = OUT_DIR / "reviews"

# Set before the review layer is imported, so its directory is this batch's tree
# from the first read.
os.environ["BABELDOC_REVIEWS_DIR"] = str(DRAFT_DIR)

from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402

ARM = "on"


def work_dir(sample: str) -> Path:
    return OUT_DIR / ARM / sample / "work" / sample


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True)
    args = parser.parse_args(argv)

    if hitl.reviews_dir() != DRAFT_DIR:
        raise SystemExit(
            f"the review layer reads {hitl.reviews_dir()}, and this tool writes "
            f"drafts only into {DRAFT_DIR}"
        )
    work = work_dir(args.sample)
    checkpoint = work / f"{checkpoint_stem('chain_builder')}.xml"
    article_map = work / article_builder.REPORT_NAME
    for path in (checkpoint, article_map):
        if not path.is_file():
            raise SystemExit(f"{path} is not in the workspace; run the arm first")

    document = load_checkpoint(checkpoint)
    settings = drop_cap.load_drop_cap_config()
    article_of_page, openers = drop_cap.read_article_map(article_map)
    candidates = drop_cap.find_candidates(
        hitl.labeled_pages(document),
        article_of_page,
        openers,
        settings,
        drop_cap.body_labels(),
    )

    draft = {
        "format_version": hitl.load_hitl_config()["review_format_version"],
        "sample": args.sample,
    }
    draft.update({name: [] for name in hitl.sections()})
    draft[hitl.DROP_CAPS_SECTION] = drop_cap.review_rows(candidates)

    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    path = hitl.review_path(args.sample)
    with path.open("w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    with hitl.review_html_path(args.sample).open("w", encoding="utf-8") as f:
        f.write(hitl.render_review_html(draft))

    # The skeleton the ruling is written into, with the verdict left empty: a
    # machine session states the question and never the answer.
    skeleton = {
        name: {} if name != hitl.TERMS_SECTION else []
        for name in hitl.sections()
    }
    skeleton[hitl.DROP_CAPS_SECTION] = {
        candidate.reference: "" for candidate in candidates
    }
    skeleton_path = DRAFT_DIR / f"{args.sample}.decisions.skeleton.json"
    with skeleton_path.open("w", encoding="utf-8") as f:
        json.dump(skeleton, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    print(
        json.dumps(
            {
                "sample": args.sample,
                "candidates": [candidate.reference for candidate in candidates],
                "verdicts_available": list(drop_cap.decision_vocabulary()),
                "draft": path.relative_to(ROOT).as_posix(),
                "skeleton": skeleton_path.relative_to(ROOT).as_posix(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
