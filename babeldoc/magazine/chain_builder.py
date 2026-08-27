"""Article chain stage: score the boundaries, then write the chains they imply.

Runs after the page classifier and before translation. Two kinds of boundary are
scored by ``chain_signals``: every adjacent page pair, and every pair of columns
inside one page. The boundaries scored as linked are edges between the paragraph
that ends one side and the paragraph that begins the other, and the components
of those edges are the chains. Members carry ``chain_id`` and a ``chain_index``
running from zero, which is the first writer of those two intermediate language
fields.

Assembly is exclusive. A paragraph is the tail of at most one edge and the head
of at most one, so a chain is a path and never a fork, and where two edges want
the same end the one whose kind stands earlier in the declared priority takes it
while the other is dropped with its reason recorded. That is what removes the
edge which skips a column already handed over to: a column that hands on to its
neighbour cannot also hand on past it, and the edge that says it does is
redundant rather than additional.

The stage is off by default. With ``magazine_chain_detect`` disabled the
pipeline is untouched and both attributes stay unset.

The failure modes are deliberately asymmetric. Linking too little costs nothing
beyond the per page behaviour the pipeline already had, so every uncertainty
resolves towards not linking: a boundary whose pages are not both declared chain
eligible is never scored, a column boundary on a page declared to preserve its
line structure is never scored, a signal the geometry cannot supply contributes
nothing, and a boundary that would cross a split part is dropped rather than
guessed at.

Everything the intermediate language has no field for goes to the sidecar
report: the per signal values behind each score, the boundaries that were not
scored and why, and the chains as they came out.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.article_ir import ArticleChain
from babeldoc.magazine.article_ir import ArticleIssue
from babeldoc.magazine.article_ir import ChainHeadStartEvidence
from babeldoc.magazine.article_ir import ChainSourceRange
from babeldoc.magazine.article_ir import ChainTailEndEvidence
from babeldoc.magazine.chain_signals import BOUNDARY_PRIORITY_KEY
from babeldoc.magazine.chain_signals import CONFIG_PATH as CHAIN_CONFIG_PATH
from babeldoc.magazine.chain_signals import DROPPED_HEAD_TAKEN
from babeldoc.magazine.chain_signals import DROPPED_TAIL_TAKEN
from babeldoc.magazine.chain_signals import PAIR_RULES_KEY
from babeldoc.magazine.chain_signals import REASON_SPLIT_BOUNDARY
from babeldoc.magazine.chain_signals import BoundaryVerdict
from babeldoc.magazine.chain_signals import evaluate_boundary
from babeldoc.magazine.chain_signals import evaluate_column_boundaries
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.element_roles import ElementRole
from babeldoc.magazine.page_identity import physical_page_number
from babeldoc.magazine.taxonomy import DEFAULT_CONFIG_PATHS
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

REPORT_NAME = "chain_report.json"

# The position a chain's first member holds. Every member after it resumes a
# paragraph the layout broke rather than opening one, which is a fact several
# passes downstream need and none of them should restate as an integer test.
CHAIN_HEAD_INDEX = 0
CHAIN_CROSSES_PROVISIONAL_OWNER = "CHAIN_CROSSES_PROVISIONAL_OWNER"
CHAIN_ENDPOINT_ROLE_NOT_BODY = "CHAIN_ENDPOINT_ROLE_NOT_BODY"
CHAIN_HEAD_START_EVIDENCE_MISSING = "CHAIN_HEAD_START_EVIDENCE_MISSING"
CHAIN_TAIL_END_EVIDENCE_MISSING = "CHAIN_TAIL_END_EVIDENCE_MISSING"
CHAIN_UNASSIGNED_OWNER = "CHAIN_UNASSIGNED_OWNER"
CHAIN_UNSUPPORTED_PAGE = "CHAIN_UNSUPPORTED_PAGE"
CHAIN_NON_ADJACENT_PHYSICAL_PAGES = "CHAIN_NON_ADJACENT_PHYSICAL_PAGES"


@dataclass(frozen=True, slots=True)
class ChainRefusal:
    boundary: str
    code: str
    article_ids: tuple[str, ...]
    element_refs: tuple[str, ...]

    def to_record(self) -> dict:
        return {
            "boundary": self.boundary,
            "code": self.code,
            "article_ids": list(self.article_ids),
            "element_refs": list(self.element_refs),
        }


@dataclass(frozen=True, slots=True)
class ChainBuildResult:
    document: il_version_1.Document
    chains: tuple[ArticleChain, ...]
    issues: tuple[ArticleIssue, ...]
    refusals: tuple[ChainRefusal, ...]


def is_chain_continuation(paragraph) -> bool:
    """Whether this paragraph resumes a chain rather than opening one.

    Read off ``chain_index``, which assembly already writes, rather than off a
    second mark meaning the same thing: the intermediate language is frozen, and
    a mark derived from the field that decides it cannot disagree with it.
    """
    index = getattr(paragraph, "chain_index", None)
    return index is not None and index > CHAIN_HEAD_INDEX


def _paragraph_locations(docs, provisional_owners) -> dict[int, tuple[str, int, object]]:
    elements = {
        element.source_ref: element
        for held in provisional_owners.elements_by_structural_position.values()
        for element in held
    }
    locations = {}
    for page in docs.page:
        physical = int(physical_page_number(page))
        for index, paragraph in enumerate(page.pdf_paragraph):
            reference = f"p{physical}#{index}"
            element = elements.get(reference)
            if element is not None:
                locations[id(paragraph)] = (reference, physical, element)
    return locations


def _head_start_evidence(
    verdict: BoundaryVerdict,
) -> ChainHeadStartEvidence | None:
    if verdict.tail_page == verdict.head_page:
        return ChainHeadStartEvidence.NOT_APPLICABLE_SAME_PAGE_COLUMN
    text = "" if verdict.head is None else (verdict.head.paragraph.unicode or "")
    stripped = text.lstrip()
    if not stripped:
        return None
    first = stripped[0]
    if not first.isalpha() or first.islower():
        return ChainHeadStartEvidence.LOWERCASE_OR_PUNCTUATION_CONTINUATION
    if first.upper() == first.lower():
        return ChainHeadStartEvidence.SENTENCE_CONTINUATION
    return None


def _tail_end_evidence(verdict: BoundaryVerdict) -> ChainTailEndEvidence | None:
    if verdict.tail_page == verdict.head_page:
        return ChainTailEndEvidence.NOT_APPLICABLE_SAME_PAGE_COLUMN
    if verdict.hyphen_tail:
        return ChainTailEndEvidence.HYPHENATED_CONTINUATION
    if float(verdict.values.get("tail_no_terminal_punct") or 0.0) > 0.0:
        return ChainTailEndEvidence.NO_TERMINAL_PUNCTUATION
    return None


class ChainBuilder:
    """Link paragraphs across page boundaries and write the resulting chains."""

    stage_name = "ChainBuilder"

    def __init__(self, translation_config):
        self.translation_config = translation_config
        self.config = load_chain_config()
        self.taxonomy = load_taxonomy()

    def process(self, docs: il_version_1.Document, provisional_owners=None) -> ChainBuildResult:
        if provisional_owners is None:
            from babeldoc.magazine.article_builder import ArticleBuilder

            provisional_owners = ArticleBuilder(
                self.translation_config
            ).build_provisional(docs)
        verdicts = self._score_boundaries(docs)
        scoped, refusals = self._owner_scoped(
            docs, verdicts, provisional_owners
        )
        taken, dropped = _accepted_edges(
            scoped, self.config[BOUNDARY_PRIORITY_KEY]
        )
        chains = _chains_from(taken)
        self._clear_chains(docs)
        evidence = self._write_chains(
            docs, chains, taken, provisional_owners
        )
        issues = tuple(
            ArticleIssue(
                code=refusal.code,
                chain_id=(
                    "chain-candidate-"
                    + hashlib.sha256(
                        "\0".join(refusal.element_refs).encode("utf-8")
                    ).hexdigest()
                ),
                article_ids=refusal.article_ids,
                element_refs=refusal.element_refs,
            )
            for refusal in refusals
            if refusal.code == CHAIN_CROSSES_PROVISIONAL_OWNER
        )
        self._write_report(
            docs, verdicts, evidence, taken, dropped, refusals
        )
        return ChainBuildResult(docs, evidence, issues, refusals)

    def _score_boundaries(self, docs: il_version_1.Document) -> list[BoundaryVerdict]:
        """Every boundary of the document, in the order a reader meets them.

        A page's own column boundaries come before the boundary out of it, so a
        report row's position is where the handover it describes happens.
        """
        pages = docs.page
        verdicts: list[BoundaryVerdict] = []
        for index, page in enumerate(pages):
            page_number = int(physical_page_number(page))
            verdicts.extend(
                evaluate_column_boundaries(
                    page, page_number, self.taxonomy.policy_of, self.config
                )
            )
            if index + 1 < len(pages):
                next_page_number = int(physical_page_number(pages[index + 1]))
                if next_page_number != page_number + 1:
                    continue
                verdicts.append(
                    evaluate_boundary(
                        page,
                        pages[index + 1],
                        page_number,
                        next_page_number,
                        self.taxonomy.policy_of,
                        self.config,
                    )
                )
        return verdicts

    def _owner_scoped(
        self,
        docs: il_version_1.Document,
        verdicts: list[BoundaryVerdict],
        provisional_owners,
    ) -> tuple[list[BoundaryVerdict], tuple[ChainRefusal, ...]]:
        """Admit linked candidates only after owner, role, and evidence checks."""
        locations = _paragraph_locations(docs, provisional_owners)
        unsupported = {
            item.page for item in provisional_owners.unsupported_pages
        }
        admitted = []
        refusals = []
        for verdict in verdicts:
            if (
                not verdict.linked
                or verdict.tail is None
                or verdict.head is None
            ):
                admitted.append(verdict)
                continue
            tail = locations.get(id(verdict.tail.paragraph))
            head = locations.get(id(verdict.head.paragraph))
            if tail is None or head is None:
                refusals.append(
                    ChainRefusal(verdict.label, CHAIN_UNASSIGNED_OWNER, (), ())
                )
                continue
            tail_ref, tail_page, tail_element = tail
            head_ref, head_page, head_element = head
            refs = (tail_ref, head_ref)
            owners = (
                provisional_owners.owner_of_element(tail_ref),
                provisional_owners.owner_of_element(head_ref),
            )
            article_ids = tuple(sorted({owner for owner in owners if owner}))
            if not (
                tail_page == head_page or head_page == tail_page + 1
            ):
                code = CHAIN_NON_ADJACENT_PHYSICAL_PAGES
            elif tail_page in unsupported or head_page in unsupported:
                code = CHAIN_UNSUPPORTED_PAGE
            elif None in owners:
                code = CHAIN_UNASSIGNED_OWNER
            elif owners[0] != owners[1]:
                code = CHAIN_CROSSES_PROVISIONAL_OWNER
            elif (
                tail_element.role is not ElementRole.BODY
                or head_element.role is not ElementRole.BODY
            ):
                code = CHAIN_ENDPOINT_ROLE_NOT_BODY
            elif _head_start_evidence(verdict) is None:
                code = CHAIN_HEAD_START_EVIDENCE_MISSING
            elif _tail_end_evidence(verdict) is None:
                code = CHAIN_TAIL_END_EVIDENCE_MISSING
            else:
                admitted.append(verdict)
                continue
            refusals.append(
                ChainRefusal(verdict.label, code, article_ids, refs)
            )
        return admitted, tuple(refusals)

    @staticmethod
    def _clear_chains(docs: il_version_1.Document) -> None:
        for page in docs.page:
            for paragraph in page.pdf_paragraph:
                paragraph.chain_id = None
                paragraph.chain_index = None

    def _write_chains(
        self,
        docs: il_version_1.Document,
        chains: list[list[il_version_1.PdfParagraph]],
        edges: list[BoundaryVerdict],
        provisional_owners,
    ) -> tuple[ArticleChain, ...]:
        """Give every member of every chain an id and its position in the chain.

        IDs derive only from ordered canonical source refs, never debug IDs.
        """
        locations = _paragraph_locations(docs, provisional_owners)
        by_pair = {
            (id(verdict.tail.paragraph), id(verdict.head.paragraph)): verdict
            for verdict in edges
        }
        evidence = []
        for chain in chains:
            refs = tuple(locations[id(paragraph)][0] for paragraph in chain)
            chain_id = "chain-" + hashlib.sha256(
                "\0".join(refs).encode("utf-8")
            ).hexdigest()
            for index, paragraph in enumerate(chain):
                paragraph.chain_id = chain_id
                paragraph.chain_index = index
            owner = provisional_owners.owner_of_element(refs[0])
            if owner is None:
                raise ValueError("owner-scoped chain lost its provisional owner")
            verdicts = [
                by_pair[(id(left), id(right))]
                for left, right in zip(chain, chain[1:], strict=False)
            ]
            head_evidence = next(
                (
                    _head_start_evidence(verdict)
                    for verdict in verdicts
                    if _head_start_evidence(verdict)
                    is not ChainHeadStartEvidence.NOT_APPLICABLE_SAME_PAGE_COLUMN
                ),
                ChainHeadStartEvidence.NOT_APPLICABLE_SAME_PAGE_COLUMN,
            )
            tail_evidence = next(
                (
                    _tail_end_evidence(verdict)
                    for verdict in verdicts
                    if _tail_end_evidence(verdict)
                    is not ChainTailEndEvidence.NOT_APPLICABLE_SAME_PAGE_COLUMN
                ),
                ChainTailEndEvidence.NOT_APPLICABLE_SAME_PAGE_COLUMN,
            )
            ranges = tuple(
                ChainSourceRange(
                    source_ref=reference,
                    start=0,
                    end=len(paragraph.unicode or ""),
                    source_sha256=hashlib.sha256(
                        (paragraph.unicode or "").encode("utf-8")
                    ).hexdigest(),
                )
                for reference, paragraph in zip(refs, chain, strict=True)
            )
            evidence.append(
                ArticleChain(
                    chain_id=chain_id,
                    article_id=owner,
                    ordered_member_refs=refs,
                    source_ranges=ranges,
                    member_physical_pages=tuple(
                        locations[id(paragraph)][1] for paragraph in chain
                    ),
                    head_start_evidence=head_evidence,
                    tail_end_evidence=tail_evidence,
                    decision_reason="linked_owner_scoped_boundaries",
                )
            )
        return tuple(evidence)

    def _split_records(self, docs: il_version_1.Document) -> list[dict]:
        """Boundaries this run cannot see because the document was split.

        Splitting hands each part to the pipeline as its own document, so the
        boundary at a part edge never appears among the adjacent page pairs
        above. It is recorded here rather than passed over silently: a chain that
        would have run across the edge is being given up, and the report is where
        that shows.
        """
        if getattr(self.translation_config, "split_strategy", None) is None:
            return []
        if not docs.page:
            return []
        last = int(physical_page_number(docs.page[-1]))
        return [
            {
                "boundary": f"{last}->{last + 1}",
                "tail_page": last,
                "head_page": last + 1,
                "eligible": False,
                "reason": REASON_SPLIT_BOUNDARY,
                "dropped_reason": REASON_SPLIT_BOUNDARY,
                "pair": None,
                "signals": {},
                "score": None,
                "linked": False,
            }
        ]

    def _write_report(
        self,
        docs: il_version_1.Document,
        verdicts: list[BoundaryVerdict],
        chains: tuple[ArticleChain, ...],
        taken: list[BoundaryVerdict],
        dropped: list[tuple[BoundaryVerdict, str]],
        refusals: tuple[ChainRefusal, ...],
    ) -> Path:
        records = [verdict.as_record() for verdict in verdicts]
        records.extend(self._split_records(docs))
        report = {
            "link_min_score": self.config["link_min_score"],
            "weights": {
                name: value
                for name, value in sorted(self.config.items())
                if name.startswith("weight_")
            },
            # One profile per allowed pairing, so a score in the rows below can
            # be recomputed from the report alone.
            "pair_weights": {
                rule.name: dict(sorted(rule.weights.items()))
                for rule in self.config[PAIR_RULES_KEY]
            },
            "boundary_priority": list(self.config[BOUNDARY_PRIORITY_KEY]),
            "boundaries": records,
            # Which linked boundaries assembly took, and which it dropped for
            # wanting an end another edge already held. A linked boundary that
            # is not an edge is the whole of what exclusive assembly does, so it
            # is written down rather than inferable from the difference between
            # two other lists.
            "edges": [
                {
                    "boundary": verdict.label,
                    "kind": verdict.kind,
                    "pairing": verdict.pairing,
                    "score": verdict.score,
                }
                for verdict in taken
            ],
            "dropped_edges": [
                {
                    "boundary": verdict.label,
                    "kind": verdict.kind,
                    "pairing": verdict.pairing,
                    "score": verdict.score,
                    "dropped_reason": reason,
                }
                for verdict, reason in dropped
            ],
            "owner_refusals": [item.to_record() for item in refusals],
            "chains": [chain.to_record() for chain in chains],
        }
        path = Path(self.translation_config.get_working_file_path(REPORT_NAME))
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
        record_config_manifest(path.parent, [*DEFAULT_CONFIG_PATHS, CHAIN_CONFIG_PATH])
        linked = sum(1 for verdict in verdicts if verdict.linked)
        logger.debug(
            "scored %d boundaries, %d linked, %d edges, %d chains, report at %s",
            len(verdicts),
            linked,
            len(taken),
            len(chains),
            path,
        )
        return path


def _accepted_edges(
    verdicts: list[BoundaryVerdict], priority: tuple[str, ...]
) -> tuple[list[BoundaryVerdict], list[tuple[BoundaryVerdict, str]]]:
    """The linked boundaries assembly takes, and the ones it drops, with reasons.

    Exclusive by construction: a paragraph hands on once and resumes once, so an
    edge whose tail has already handed on, or whose head has already resumed, is
    refused. Which of two competing edges is refused is decided by the declared
    priority and never by the order the document happened to be walked in, so
    the answer is a property of the configuration rather than of the walk.

    An edge joining a paragraph to itself is refused as well. It cannot arise
    from a page boundary, and it arises from a column boundary only where one
    column offers a single candidate that is both its last and its first, which
    is a band with one paragraph in it rather than a handover.
    """
    order = {name: position for position, name in enumerate(priority)}
    linked = [
        (position, verdict)
        for position, verdict in enumerate(verdicts)
        if verdict.linked and verdict.tail is not None and verdict.head is not None
    ]
    ranked = sorted(
        linked,
        key=lambda item: (order.get(item[1].priority_name, len(order)), item[0]),
    )
    taken: list[tuple[int, BoundaryVerdict]] = []
    dropped: list[tuple[int, BoundaryVerdict, str]] = []
    tails: set[int] = set()
    heads: set[int] = set()
    for position, verdict in ranked:
        tail = id(verdict.tail.paragraph)
        head = id(verdict.head.paragraph)
        if tail == head or tail in tails:
            dropped.append((position, verdict, DROPPED_TAIL_TAKEN))
            continue
        if head in heads:
            dropped.append((position, verdict, DROPPED_HEAD_TAKEN))
            continue
        tails.add(tail)
        heads.add(head)
        taken.append((position, verdict))
    # Back into document order, so both lists read the way the document does
    # while the decision above was taken by declared priority alone.
    taken.sort(key=lambda item: item[0])
    dropped.sort(key=lambda item: item[0])
    return (
        [verdict for _position, verdict in taken],
        [(verdict, reason) for _position, verdict, reason in dropped],
    )


def _chains_from(
    edges: list[BoundaryVerdict],
) -> list[list[il_version_1.PdfParagraph]]:
    """The components of the accepted edges, in the order a reader meets them.

    An edge joins the paragraph ending one side of a boundary to the paragraph
    beginning the other, and two edges belong to the same chain only when they
    meet at the same paragraph: that happens where the paragraph in the middle
    both resumes and hands on. Where it does not, the two edges are two chains,
    and the paragraphs between them stay outside both.

    Assembly having given every paragraph at most one edge in each role, each
    component is a path: it is entered at the one paragraph nothing hands on to
    and followed by the one edge leaving each member. A chain may hold two
    paragraphs of one page, which is what a column boundary produces, and
    consecutive members therefore sit on the same page or on consecutive ones.
    """
    successor: dict[int, il_version_1.PdfParagraph] = {}
    resumed: set[int] = set()
    starts: list[il_version_1.PdfParagraph] = []
    for edge in edges:
        tail = edge.tail.paragraph
        head = edge.head.paragraph
        successor[id(tail)] = head
        resumed.add(id(head))
        starts.append(tail)

    chains: list[list[il_version_1.PdfParagraph]] = []
    for paragraph in starts:
        if id(paragraph) in resumed:
            continue
        chain = [paragraph]
        following = successor.get(id(paragraph))
        while following is not None:
            chain.append(following)
            following = successor.get(id(following))
        chains.append(chain)
    return chains
