"""Source text still standing in a finished translation.

After the translator has run, a paragraph's rendering is its translation. Where
translation never reached it the rendering is still its source, and that is
readable from the scripts the text is written in alone: a paragraph rendered in
Latin script in a document finished into Chinese was not translated, whatever
the reason it was not.

The share is directional and declared per target language, because the fact
being measured is the presence of the *wrong* script rather than of any
particular one. It is measured over cased characters of the declared scripts
only, so a folio, a price or a run of punctuation neither raises nor lowers it,
and a floor on how many such characters the paragraph holds keeps a page number
or a copyright glyph from being evidence of anything.

The scan takes in every paragraph of every page whose kind declares that it is
translated at all, layout label included: the paragraphs this exists to find
are exactly the ones the translator never saw, and a scope defined by the
labels the translator accepts would define them out of it. The line the layout
parser recovers outside any block is the standing case -- it carries no
paragraph style, its characters are grouped as a formula, and it is marked
vertical, each of which is on its own enough for the translator to pass it by.
"""

from __future__ import annotations

from babeldoc.magazine.detectors import base

NAME = "untranslated_residue"
KIND = "untranslated_residue"

# A residue finding is only meaningful about a document translation was asked
# for: where it was not, every paragraph is its source by construction.
REQUIRES_TRANSLATION = True


def measure(text: str, script: str) -> tuple[int, int, float]:
    """Characters of the residue script, of all declared scripts, and the share."""
    counts = base.script_counts(text)
    total = sum(counts.values())
    residue = counts.get(script, 0)
    return residue, total, (residue / total if total else 0.0)


def detect(context: base.DetectionContext) -> list[base.Issue]:
    config = context.config
    rule = config.residue_rule(context.language)
    if rule is None:
        context.notes.append(
            f"{NAME}: no residue direction is declared for target language "
            f"{context.language!r}; nothing was scanned"
        )
        return []
    script, min_ratio = rule
    found: list[base.Issue] = []
    for view in context.pages:
        if not view.flag(base.TRANSLATE_POLICY_FLAG, True):
            continue
        for index, paragraph in enumerate(view.page.pdf_paragraph or ()):
            text = base.rendered_text(paragraph).strip()
            if not text:
                continue
            residue, total, ratio = measure(text, script)
            if residue < config.residue_min_script_chars or ratio < min_ratio:
                continue
            found.append(
                base.Issue(
                    kind=KIND,
                    page=view.label,
                    paragraph_refs=(view.reference(index),),
                    geometry=base.union_box([base.box_tuple(paragraph.box)]),
                    severity=context.severity_of(KIND),
                    evidence={
                        "residue_script": script,
                        "residue_chars": residue,
                        "script_chars": total,
                        "residue_ratio": round(ratio, 4),
                        "min_ratio": min_ratio,
                        "layout_label": paragraph.layout_label,
                        "debug_id": paragraph.debug_id,
                        "excerpt": text[: config.excerpt_chars],
                    },
                    detector=NAME,
                    detected_at_iteration=context.iteration,
                )
            )
    return found
