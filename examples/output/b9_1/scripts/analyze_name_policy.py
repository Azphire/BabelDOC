"""Compare the person-name candidates across the wording rounds.

Each round of the person-name wording iteration leaves an
``iteration/round_N.evidence.json`` behind. This reads all of them and builds
the two tables the delivery report quotes: the candidate names of the contents
page as F1 rendered them and as each round rendered them, and the ruled terms
of the same sample checked round by round.

Which rows are candidates is derived, not listed. A row is a candidate when any
round's rendering of it carries something shaped like a personal name in Latin
script -- two or more capitalised words, particles allowed between them. No
person is named in this file: which names the corpus holds is the corpus
owner's business and a hard-coded list here would have to be revised every time
a sample changed.

Usage:
    python analyze_name_policy.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "examples" / "output" / "b9_1"
ITERATION_DIR = OUT_DIR / "iteration"
REPORT = ITERATION_DIR / "name_policy.md"

# The sample whose contents page the person name policy is measured on.
SAMPLE = "Courier-en"

# A personal name in Latin script: two or more capitalised words, with the
# particles a name may carry between them. Deliberately loose -- a false
# positive costs one extra row in a table a human reads, while a false negative
# would hide the very case the iteration is about.
# Letters are written as escapes so that this file, like every other source
# file of the project, is ASCII: the accented range covers Latin-1 supplement
# through Latin Extended-B, and the last character is a typographic apostrophe.
_LETTER = "[A-Za-z\u00c0-\u024f'\u2019-]"
NAME_SHAPE = re.compile(
    f"[A-Z]{_LETTER}+"
    r"(?:\s+(?:de|von|van|del|da|bin|al|Al-)?\s*"
    f"[A-Z]{_LETTER}+)+"
)

# Words that match the shape above and are not people.
NOT_A_PERSON = frozenset({"LINKS"})

# Markup the typesetting stage leaves in a paragraph's text.
STYLE_TAG = re.compile(r"</?style[^>]*>")


def rounds() -> list[tuple[str, dict]]:
    """Every round's evidence, in round order."""
    found = []
    for path in sorted(ITERATION_DIR.glob("round_*.evidence.json")):
        with path.open(encoding="utf-8") as f:
            found.append((path.stem.replace(".evidence", ""), json.load(f)))
    return found


def plain(text: str) -> str:
    return STYLE_TAG.sub("", text or "").strip()


def looks_like_a_name(text: str) -> bool:
    return any(match not in NOT_A_PERSON for match in NAME_SHAPE.findall(plain(text)))


def rows_of(evidence: dict) -> dict[str, dict]:
    sample = evidence.get("samples", {}).get(SAMPLE)
    if sample is None:
        return {}
    return {row["position"]: row for row in sample["comparison"]["paragraphs"]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    collected = rounds()
    if not collected:
        raise SystemExit(f"no round evidence under {ITERATION_DIR}")

    by_round = {label: rows_of(evidence) for label, evidence in collected}
    positions = sorted(
        {
            position
            for rows in by_round.values()
            for position, row in rows.items()
            if looks_like_a_name(row["after"]) or looks_like_a_name(row["before"] or "")
        },
        key=lambda name: int(name.split("#")[1]),
    )

    labels = [label for label, _ in collected]
    lines = [
        f"# Person-name candidates on the {SAMPLE} contents page",
        "",
        "F1 is the run this batch is measured against. Each round column is one",
        "wording of the declared role text; only that text changed between them.",
        "",
        "| position | F1 | " + " | ".join(labels) + " |",
        "| --- | --- | " + " | ".join("---" for _ in labels) + " |",
    ]
    for position in positions:
        first = next(rows[position] for rows in by_round.values() if position in rows)
        cells = [plain(first["before"] or "")]
        cells += [
            plain(by_round[label].get(position, {}).get("after", ""))
            for label in labels
        ]
        lines.append(f"| {position} | " + " | ".join(cells) + " |")

    lines += ["", "## Ruled terms, round by round", ""]
    lines.append("| ruled source | ruled rendering | F1 | " + " | ".join(labels) + " |")
    lines.append("| --- | --- | --- | " + " | ".join("---" for _ in labels) + " |")
    terms = collected[0][1]["samples"][SAMPLE]["ruling"]["terms"]
    for source in sorted(terms):
        cells = []
        for _label, evidence in collected:
            row = evidence["samples"][SAMPLE]["ruling"]["terms"][source]
            cells.append("present" if row["in_after"] else "LOST")
        before = "present" if terms[source]["in_before"] else "absent"
        lines.append(
            f"| {source} | {terms[source]['ruled']} | {before} | "
            + " | ".join(cells)
            + " |"
        )

    text = "\n".join(lines) + "\n"
    ITERATION_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"written to {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
