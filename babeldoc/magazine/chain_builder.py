"""Article chain stage: score page boundaries, then write the chains they imply.

Runs after the page classifier and before translation. Every adjacent page pair
is scored by ``chain_signals``; the pairs scored as linked are edges between the
paragraph that ends one page and the paragraph that begins the next, and the
connected components of those edges are the chains. Members carry ``chain_id``
and a ``chain_index`` running from zero, which is the first writer of those two
intermediate language fields.

The stage is off by default. With ``magazine_chain_detect`` disabled the
pipeline is untouched and both attributes stay unset.

The failure modes are deliberately asymmetric. Linking too little costs nothing
beyond the per page behaviour the pipeline already had, so every uncertainty
resolves towards not linking: a boundary whose pages are not both declared chain
eligible is never scored, a signal the geometry cannot supply contributes
nothing, and a boundary that would cross a split part is dropped rather than
guessed at.

Everything the intermediate language has no field for goes to the sidecar
report: the per signal values behind each score, the boundaries that were not
scored and why, and the chains as they came out.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.paragraph_finder import generate_base58_id
from babeldoc.magazine.chain_signals import CONFIG_PATH as CHAIN_CONFIG_PATH
from babeldoc.magazine.chain_signals import PAIR_RULES_KEY
from babeldoc.magazine.chain_signals import REASON_SPLIT_BOUNDARY
from babeldoc.magazine.chain_signals import BoundaryVerdict
from babeldoc.magazine.chain_signals import evaluate_boundary
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.taxonomy import DEFAULT_CONFIG_PATHS
from babeldoc.magazine.taxonomy import load_taxonomy
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

REPORT_NAME = "chain_report.json"


class ChainBuilder:
    """Link paragraphs across page boundaries and write the resulting chains."""

    stage_name = "ChainBuilder"

    def __init__(self, translation_config):
        self.translation_config = translation_config
        self.config = load_chain_config()
        self.taxonomy = load_taxonomy()

    def process(self, docs: il_version_1.Document) -> il_version_1.Document:
        verdicts = self._score_boundaries(docs)
        chains = _chains_from(verdicts)
        self._write_chains(chains)
        self._write_report(docs, verdicts, chains)
        return docs

    def _score_boundaries(self, docs: il_version_1.Document) -> list[BoundaryVerdict]:
        pages = docs.page
        return [
            evaluate_boundary(
                pages[index],
                pages[index + 1],
                index,
                index + 1,
                self.taxonomy.policy_of,
                self.config,
            )
            for index in range(len(pages) - 1)
        ]

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
            "boundaries": records,
            "chains": [
                {
                    "chain_id": chain[0].chain_id,
                    "length": len(chain),
                    "members": [
                        {"debug_id": p.debug_id, "chain_index": p.chain_index}
                        for p in chain
                    ],
                }
                for chain in chains
            ],
        }
        path = Path(self.translation_config.get_working_file_path(REPORT_NAME))
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
        record_config_manifest(path.parent, [*DEFAULT_CONFIG_PATHS, CHAIN_CONFIG_PATH])
        linked = sum(1 for verdict in verdicts if verdict.linked)
        logger.debug(
            "scored %d boundaries, %d linked, %d chains, report at %s",
            len(verdicts),
            linked,
            len(chains),
            path,
        )
        return path


def _chains_from(
    verdicts: list[BoundaryVerdict],
) -> list[list[il_version_1.PdfParagraph]]:
    """Transitive closure of the linked boundaries, in page order.

    A linked boundary is an edge between the paragraph ending one page and the
    paragraph beginning the next, and two edges belong to the same chain only
    when they meet at the same paragraph: that happens when the page in the
    middle both resumes and hands on through one paragraph. Where it does not,
    the two edges are two chains, and the paragraphs between them stay outside
    both. That is the closure the edges actually support, and it is why a chain
    never holds two paragraphs from one page and its members always sit on
    consecutive pages.

    Boundaries arrive in page order, so an open chain can only ever be extended
    by the next one, and one pass is enough to find every component.
    """
    chains: list[list[il_version_1.PdfParagraph]] = []
    open_chain: list[il_version_1.PdfParagraph] | None = None
    for verdict in verdicts:
        if not verdict.linked or verdict.tail is None or verdict.head is None:
            open_chain = None
            continue
        if open_chain is not None and open_chain[-1] is verdict.tail.paragraph:
            open_chain.append(verdict.head.paragraph)
        else:
            open_chain = [verdict.tail.paragraph, verdict.head.paragraph]
            chains.append(open_chain)
    return chains
