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
resolves towards not linking: a column boundary on a page declared to preserve
its line structure is never scored, a signal the geometry cannot supply
contributes nothing, and a boundary that would cross a split part is dropped
rather than guessed at. Page classification stays a soft prior and cannot veto
complete paragraph-level continuity evidence.

Everything the intermediate language has no field for goes to the sidecar
report: the per signal values behind each score, the boundaries that were not
scored and why, and the chains as they came out.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.paragraph_finder import generate_base58_id
from babeldoc.magazine.chain_signals import BOUNDARY_PRIORITY_KEY
from babeldoc.magazine.chain_signals import CONFIG_PATH as CHAIN_CONFIG_PATH
from babeldoc.magazine.chain_signals import DROPPED_HEAD_TAKEN
from babeldoc.magazine.chain_signals import DROPPED_TAIL_TAKEN
from babeldoc.magazine.chain_signals import PAIR_RULES_KEY
from babeldoc.magazine.chain_signals import REASON_NONADJACENT_PHYSICAL_PAGE
from babeldoc.magazine.chain_signals import REASON_SPLIT_BOUNDARY
from babeldoc.magazine.chain_signals import SIGNAL_NAMES
from babeldoc.magazine.chain_signals import BoundaryVerdict
from babeldoc.magazine.chain_signals import evaluate_boundary
from babeldoc.magazine.chain_signals import evaluate_column_boundaries
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.taxonomy import DEFAULT_CONFIG_PATHS
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

REPORT_NAME = "chain_report.json"

# The position a chain's first member holds. Every member after it resumes a
# paragraph the layout broke rather than opening one, which is a fact several
# passes downstream need and none of them should restate as an integer test.
CHAIN_HEAD_INDEX = 0


def is_chain_continuation(paragraph) -> bool:
    """Whether this paragraph resumes a chain rather than opening one.

    Read off ``chain_index``, which assembly already writes, rather than off a
    second mark meaning the same thing: the intermediate language is frozen, and
    a mark derived from the field that decides it cannot disagree with it.
    """
    index = getattr(paragraph, "chain_index", None)
    return index is not None and index > CHAIN_HEAD_INDEX


class ChainBuilder:
    """Link paragraphs across page boundaries and write the resulting chains."""

    stage_name = "ChainBuilder"

    def __init__(self, translation_config):
        self.translation_config = translation_config
        self.config = load_chain_config()
        self.taxonomy = load_taxonomy()

    def process(self, docs: il_version_1.Document) -> il_version_1.Document:
        verdicts = self._score_boundaries(docs)
        taken, dropped = _accepted_edges(verdicts, self.config[BOUNDARY_PRIORITY_KEY])
        chains = _chains_from(taken)
        self._write_chains(chains)
        self._write_report(docs, verdicts, chains, taken, dropped)
        return docs

    def _score_boundaries(self, docs: il_version_1.Document) -> list[BoundaryVerdict]:
        """Every boundary of the document, in the order a reader meets them.

        A page's own column boundaries come before the boundary out of it, so a
        report row's position is where the handover it describes happens.
        """
        pages = docs.page
        verdicts: list[BoundaryVerdict] = []
        for index, page in enumerate(pages):
            page_number = getattr(page, "page_number", index)
            physical_index = index if page_number is None else int(page_number)
            verdicts.extend(
                evaluate_column_boundaries(
                    page, physical_index, self.taxonomy.policy_of, self.config
                )
            )
            if index + 1 < len(pages):
                following_number = getattr(pages[index + 1], "page_number", index + 1)
                following_index = (
                    index + 1 if following_number is None else int(following_number)
                )
                if following_index != physical_index + 1:
                    verdicts.append(
                        BoundaryVerdict(
                            tail_page=physical_index,
                            head_page=following_index,
                            eligible=False,
                            reason=REASON_NONADJACENT_PHYSICAL_PAGE,
                            pair=None,
                            values=dict.fromkeys(SIGNAL_NAMES),
                            score=None,
                            linked=False,
                            tail_fill_ratio=None,
                            tail=None,
                            head=None,
                        )
                    )
                    continue
                verdicts.append(
                    evaluate_boundary(
                        page,
                        pages[index + 1],
                        physical_index,
                        following_index,
                        self.taxonomy.policy_of,
                        self.config,
                    )
                )
        return verdicts

    def _write_chains(self, chains: list[list[il_version_1.PdfParagraph]]) -> None:
        """Give every member of every chain an id and its position in the chain.

        Ids come from the same base58 generator that names paragraphs, so a
        chain id reads like the debug ids beside it and collides no more often.
        """
        for chain in chains:
            chain_id = generate_base58_id()
            for index, paragraph in enumerate(chain):
                paragraph.chain_id = chain_id
                paragraph.chain_index = index

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
        last = len(docs.page)
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
        chains: list[list[il_version_1.PdfParagraph]],
        taken: list[BoundaryVerdict],
        dropped: list[tuple[BoundaryVerdict, str]],
    ) -> Path:
        member_audit = {}
        for local_page_index, page in enumerate(docs.page):
            physical_page = getattr(page, "page_number", local_page_index)
            physical_page = (
                local_page_index + 1
                if physical_page is None
                else int(physical_page) + 1
            )
            for paragraph_index, paragraph in enumerate(page.pdf_paragraph):
                box = getattr(paragraph, "box", None)
                member_audit[id(paragraph)] = {
                    "source_ref": f"p{physical_page}#{paragraph_index}",
                    "physical_page": physical_page,
                    "source_box": None
                    if box is None
                    else [
                        float(getattr(box, name))
                        for name in ("x", "y", "x2", "y2")
                    ],
                    "source_text_sha256": hashlib.sha256(
                        (getattr(paragraph, "unicode", "") or "").encode("utf-8")
                    ).hexdigest(),
                    "role": getattr(paragraph, "layout_label", None),
                }
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
                    "tail": member_audit.get(id(verdict.tail.paragraph)),
                    "head": member_audit.get(id(verdict.head.paragraph)),
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
            "chains": [
                {
                    "chain_id": chain[0].chain_id,
                    "length": len(chain),
                    "members": [
                        {
                            "debug_id": p.debug_id,
                            "chain_index": p.chain_index,
                            "order": p.chain_index,
                            **member_audit[id(p)],
                        }
                        for p in chain
                    ],
                }
                for chain in chains
            ],
        }
        path = Path(self.translation_config.get_working_file_path(REPORT_NAME))
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
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
        and verdict.values.get("body_label_pair") == 1.0
        and _textually_continuous(verdict)
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


def _textually_continuous(verdict: BoundaryVerdict) -> bool:
    """Conservative source-text guard for a body handover.

    In a Latin-script paragraph, a continuation normally resumes with a
    lower-case word.  An upper-case opener is instead evidence that the next
    record starts independently (the common TOC/byline false positive).  CJK
    text has no case and is left entirely to geometry/style evidence.
    """
    tail_text = verdict.tail.paragraph.unicode or ""
    head_text = verdict.head.paragraph.unicode or ""
    if any("\u3400" <= char <= "\u9fff" for char in tail_text + head_text):
        return True
    first_alpha = next((char for char in head_text if char.isalpha()), None)
    return first_alpha is None or not first_alpha.isupper()


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
