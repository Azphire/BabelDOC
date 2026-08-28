"""M2, the block conservation invariant: nothing is lost without being declared.

The background chapter promises this measure beside the mid-unit page-break rate
and defines neither, so this docstring is the definition.

The invariant is one sentence in three places: **everything translated is either
rendered or explicitly escalated, and nothing else changes.** Written out, for
one run :math:`r` with a set of levels :math:`L`,

.. math::

    \\mathrm{BCI}(r) = \\bigwedge_{\\ell \\in L} I_{\\ell}(r) \\in \\{0, 1\\},

which is a **Boolean invariant and not a ratio**: a paper reports how many runs
satisfy it, never a mean over runs. The three levels are

.. math::

    I_{\\text{chain}} :\\;
      \\forall c:\\;
      \\bigsqcup_{m \\in c} [s_m, e_m) = [0, |t_c|)
      \\;\\wedge\\;
      \\big\\Vert_{m \\in c} t_c[s_m{:}e_m] = t_c
      \\;\\wedge\\;
      |M_c| = |R_c| + |E_c|,

.. math::

    I_{\\text{repair}} :\\;
      P_{\\text{before}} = P_{\\text{after}}
      \\;\\wedge\\;
      N_{\\text{before}} = N_{\\text{after}}
      \\;\\wedge\\;
      C \\subseteq U
      \\;\\wedge\\;
      C \\setminus U = \\emptyset,

.. math::

    I_{\\text{document}} :\\; P_{\\text{source}} = P_{\\text{produced}},

where :math:`t_c` is a chain's translation, :math:`[s_m, e_m)` the interval its
member :math:`m` renders, :math:`M_c` the chain's members and :math:`R_c` and
:math:`E_c` the members that were rendered and the members that were escalated;
:math:`P` and :math:`N` count pages and paragraphs, :math:`U` the paragraphs a
repair declared it would touch and :math:`C` those that changed.

The first level is the one ledger row A-07 records as holding byte for byte; the
second is what ``react_repair.report.json`` already writes as its ``conservation``
verdict and row E-02 records at pixel level; the third is the page count row F-01
records the upstream baseline holding. What this module adds is that the three
are read through one judgement, so a run can be said to conserve or not to, and
the level that failed is named.

A level whose evidence is not present is ``None``, not ``True``. A conjunction
over absent evidence that came out true would be the most dangerous number in
the evaluation: it would say a run conserved when what happened is that nobody
looked.
"""

from __future__ import annotations

from dataclasses import dataclass

CHAIN_LEVEL = "chain"
REPAIR_LEVEL = "repair"
DOCUMENT_LEVEL = "document"
LEVELS = (CHAIN_LEVEL, REPAIR_LEVEL, DOCUMENT_LEVEL)


@dataclass(frozen=True)
class LevelVerdict:
    """One level of the invariant: whether it holds, and on what evidence."""

    level: str
    holds: bool | None
    subjects: int
    failures: tuple[str, ...]
    evidence: dict

    def as_record(self) -> dict:
        return {
            "level": self.level,
            "holds": self.holds,
            "subjects": self.subjects,
            "failures": list(self.failures),
            "evidence": self.evidence,
        }


def _absent(level: str, reason: str) -> LevelVerdict:
    return LevelVerdict(
        level=level, holds=None, subjects=0, failures=(), evidence={"absent": reason}
    )


def chain_level(report: dict | None) -> LevelVerdict:
    """The chain sidecar's own arithmetic, checked rather than trusted.

    The sidecar records, per chain, the translation and the interval of it each
    member renders. The check is that those intervals tile the translation from
    its first character to its last with no gap and no overlap, that joining the
    slices reproduces the translation exactly, and that every member the merge
    consumed is accounted for as either rendered or escalated.
    """
    if report is None:
        return _absent(CHAIN_LEVEL, "no chain translation report")
    chains = list(report.get("chains") or ())
    counts = report.get("counts") or {}
    escalated = list(report.get("escalated") or ())
    failures: list[str] = []

    rendered_members = 0
    for chain in chains:
        chain_id = chain.get("chain_id", "?")
        translation = chain.get("translation") or ""
        members = list(chain.get("members") or ())
        rendered_members += len(members)
        cursor = 0
        joined: list[str] = []
        for member in members:
            segment = member.get("segment") or {}
            start = segment.get("start")
            end = segment.get("end")
            if start is None or end is None:
                failures.append(f"{chain_id}: member {member.get('debug_id')} has no segment")
                break
            if int(start) != cursor:
                failures.append(
                    f"{chain_id}: member {member.get('debug_id')} starts at {start}, "
                    f"leaving {cursor} uncovered"
                )
                break
            if int(end) < int(start):
                failures.append(f"{chain_id}: member {member.get('debug_id')} runs backwards")
                break
            joined.append(translation[int(start) : int(end)])
            cursor = int(end)
        else:
            if cursor != len(translation):
                failures.append(
                    f"{chain_id}: members cover {cursor} of {len(translation)} characters"
                )
            elif "".join(joined) != translation:
                failures.append(f"{chain_id}: the joined members are not the translation")

    merged_members = counts.get("merged_members")
    if merged_members is not None and merged_members != rendered_members + len(escalated):
        failures.append(
            f"merged_members={merged_members} against {rendered_members} rendered "
            f"+ {len(escalated)} escalated"
        )

    return LevelVerdict(
        level=CHAIN_LEVEL,
        holds=not failures,
        subjects=len(chains),
        failures=tuple(failures),
        evidence={
            "chains": len(chains),
            "rendered_members": rendered_members,
            "escalated_members": len(escalated),
            "merged_members": merged_members,
        },
    )


def repair_level(report: dict | None) -> LevelVerdict:
    """The repair sidecar's conservation block, read as the invariant it is.

    The counts have to be unchanged, what changed has to be inside what the
    repair declared it would touch, and the report's own list of changes outside
    that declaration has to be empty. The verdict string the sidecar writes is
    carried through as evidence but is not what is checked: the fields are.
    """
    if report is None:
        return _absent(REPAIR_LEVEL, "no repair report")
    block = report.get("conservation")
    if not isinstance(block, dict):
        return _absent(REPAIR_LEVEL, "the repair report carries no conservation block")

    touched = set(block.get("touched_refs") or ())
    changed = set(block.get("changed_refs") or ())
    outside = list(block.get("changed_outside_touched") or ())
    failures: list[str] = []
    if block.get("pages_before") != block.get("pages_after"):
        failures.append(
            f"pages {block.get('pages_before')} -> {block.get('pages_after')}"
        )
    if block.get("paragraphs_before") != block.get("paragraphs_after"):
        failures.append(
            f"paragraphs {block.get('paragraphs_before')} -> "
            f"{block.get('paragraphs_after')}"
        )
    stray = sorted(changed - touched)
    if stray:
        failures.append(f"changed outside the declared touch set: {stray}")
    if outside:
        failures.append(f"the report itself lists {len(outside)} change(s) outside")
    fixed_assets = block.get("fixed_assets")
    if isinstance(fixed_assets, dict) and not fixed_assets.get("holds", False):
        failures.append("fixed asset count, bbox, digest, or page size changed")

    return LevelVerdict(
        level=REPAIR_LEVEL,
        holds=not failures,
        subjects=1,
        failures=tuple(failures),
        evidence={
            "pages_before": block.get("pages_before"),
            "pages_after": block.get("pages_after"),
            "paragraphs_before": block.get("paragraphs_before"),
            "paragraphs_after": block.get("paragraphs_after"),
            "touched": len(touched),
            "changed": len(changed),
            "changed_outside_touched": len(outside),
            "reported_verdict": block.get("verdict"),
            "fixed_assets": fixed_assets,
        },
    )


def document_level(source_pages: int | None, produced_pages: int | None) -> LevelVerdict:
    """One page in, one page out. The coarsest level and the hardest to argue with."""
    if source_pages is None or produced_pages is None:
        return _absent(DOCUMENT_LEVEL, "a page count is missing")
    holds = source_pages == produced_pages
    return LevelVerdict(
        level=DOCUMENT_LEVEL,
        holds=holds,
        subjects=1,
        failures=() if holds else (f"pages {source_pages} -> {produced_pages}",),
        evidence={"source_pages": source_pages, "produced_pages": produced_pages},
    )


def measure(
    chain_report: dict | None = None,
    repair_report: dict | None = None,
    source_pages: int | None = None,
    produced_pages: int | None = None,
) -> dict:
    """M2 over one run: the three levels, and the conjunction of what was present.

    ``holds`` is the conjunction over the levels that had evidence, and is
    ``None`` when no level did. ``levels_absent`` names what was not looked at,
    because a conjunction over two levels is a weaker statement than one over
    three and the difference has to be visible in the report rather than in the
    reader's memory of how the report was produced.
    """
    verdicts = [
        chain_level(chain_report),
        repair_level(repair_report),
        document_level(source_pages, produced_pages),
    ]
    present = [item for item in verdicts if item.holds is not None]
    return {
        "metric": "block_conservation_invariant",
        "holds": all(item.holds for item in present) if present else None,
        "levels_present": [item.level for item in present],
        "levels_absent": [item.level for item in verdicts if item.holds is None],
        "levels": {item.level: item.as_record() for item in verdicts},
    }
