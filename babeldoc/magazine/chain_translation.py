"""Chain level joint translation: the translation stage's half of it.

A chain is a semantic unit the page break split. ``chain_backfill`` is the
string layer -- merge the members, cut the translation back up, hold the
conservation law -- and this module is what puts that layer on the translation
path: it finds the chains in the document, sends each one to the engine as a
single unit through the machinery the per paragraph path already uses, and
writes each member back the piece the backfill cut for it.

The pass is a plan and an application, deliberately in that order. Planning
merges, translates and cuts every chain before the per paragraph machinery
starts, and application writes the pieces back after that machinery has
finished. Nothing between those two points reads a member's text, so the
context the per paragraph path builds as it goes -- the running title above all
-- is built from exactly the same source text it would have been built from
with the pass switched off. What does change for it is the batching: a claimed
member no longer occupies a slot in a page batch, so the batches around it are
composed differently. That is unavoidable, being the whole point.

:class:`ChainClaim` is the single point at which a member is withheld from the
per paragraph machinery. Every other mechanism asks it and records the refusal,
so the sidecar answers who wanted a member and who got it; an empty claim
answers no to everything, which is what the switch being off leaves behind.

A chain the pass cannot see through goes back to the per paragraph path whole,
and the reason is written down: a member carrying a formula or style
placeholder, a member the pipeline will not hand over text for, an engine that
returns nothing usable, or a cut that fails the conservation law. Falling back
is the escape hatch, not a way of swallowing the error, so every one of them
appears in the report and in the counts, which is what makes ``chains ==
merged + escalated`` checkable from the sidecar alone.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from babeldoc.magazine import chain_backfill as backfill
from babeldoc.magazine.chain_signals import CLASS_LABELS_KEY
from babeldoc.magazine.chain_signals import load_chain_config

logger = logging.getLogger(__name__)

REPORT_NAME = "chain_translation.report.json"

# Why a chain was handed back to the per paragraph path.
ESCALATION_PLACEHOLDER = "placeholder_bearing"
ESCALATION_CONSERVATION = "conservation_failure"
ESCALATION_MEMBER = "member_unavailable"
ESCALATION_TRANSLATION = "translation_unavailable"
ESCALATION_INCOMPLETE = "incomplete_chain"

# Why a member is invisible to everything else.
SKIP_REASON = "chain_member"

# The mechanisms that ask for a paragraph and can be refused it.
MECHANISM_CROSS_PAGE = "cross_page"
MECHANISM_CROSS_COLUMN = "cross_column"
MECHANISM_PAGE_BATCH = "page_batch"

# The one item a merged chain is sent as. The engine is asked for the same
# shape it is asked for everywhere else, so one chain is one row of the batch
# protocol rather than a second protocol beside it.
_SINGLE_ITEM_ID = 0


class ChainTranslationError(RuntimeError):
    """Raised when a chain's merged translation cannot be used."""


@dataclass
class MemberPlan:
    """One member, prepared for the merge and waiting for its piece."""

    paragraph: object
    tracker: object
    translate_input: object
    source: str
    page_index: int

    @property
    def debug_id(self):
        return getattr(self.paragraph, "debug_id", None)

    @property
    def chain_index(self):
        return getattr(self.paragraph, "chain_index", None)


@dataclass
class ChainEntry:
    """One chain, merged and cut, waiting to be written back."""

    chain_id: str
    pair_class: str | None
    strategy: str
    members: list[MemberPlan]
    merge: backfill.ChainMerge
    translated: str
    redistribution: backfill.Redistribution

    def as_record(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "pair_class": self.pair_class,
            "strategy": self.strategy,
            "merged_source_chars": len(self.merge.text),
            "merged_translation_chars": len(self.translated),
            # Written out whole so that the conservation law can be stated over
            # the report and the document alone: the members of a chain join
            # back to exactly this string.
            "translation": self.translated,
            "merge": self.merge.as_record(),
            "redistribution": self.redistribution.as_record(),
            "members": [
                {
                    "debug_id": member.debug_id,
                    "chain_index": member.chain_index,
                    "page_index": member.page_index,
                    "layout_label": getattr(member.paragraph, "layout_label", None),
                    "source_chars": len(member.source),
                    "segment": segment.as_record(),
                }
                for member, segment in zip(
                    self.members, self.redistribution.segments, strict=True
                )
            ],
        }


@dataclass
class SkipRecord:
    """One member, and every mechanism that asked for it and was refused."""

    chain_id: str
    chain_index: int | None
    debug_id: str | None
    page_index: int
    declined_by: list[str] = field(default_factory=list)

    def decline(self, mechanism: str) -> None:
        if mechanism not in self.declined_by:
            self.declined_by.append(mechanism)

    def as_record(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "chain_index": self.chain_index,
            "debug_id": self.debug_id,
            "page_index": self.page_index,
            "reason": SKIP_REASON,
            "declined_by": list(self.declined_by),
        }


class ChainClaim:
    """The paragraphs the chain pass has taken, and who else asked for them.

    Every question is asked from the thread that walks the document, which is
    the same thread for all three mechanisms; the translation work they queue
    never reaches this object, so the record needs no lock.
    """

    def __init__(self, records: dict[int, SkipRecord] | None = None):
        self._records: dict[int, SkipRecord] = records or {}

    def __bool__(self) -> bool:
        return bool(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def _decline(self, paragraph, mechanism: str) -> bool:
        record = self._records.get(id(paragraph))
        if record is None:
            return False
        record.decline(mechanism)
        return True

    def claims_paragraph(self, paragraph) -> bool:
        """Whether the page batch has to leave this paragraph alone."""
        return self._decline(paragraph, MECHANISM_PAGE_BATCH)

    def declines_cross_page(self, tail, head) -> bool:
        """Whether the cross page pairing has to drop this endpoint pair."""
        left = self._decline(tail, MECHANISM_CROSS_PAGE)
        right = self._decline(head, MECHANISM_CROSS_PAGE)
        return left or right

    def declines_cross_column(self, first, second) -> bool:
        """Whether the cross column pairing has to drop this pair."""
        left = self._decline(first, MECHANISM_CROSS_COLUMN)
        right = self._decline(second, MECHANISM_CROSS_COLUMN)
        return left or right

    def take(self, paragraph, record: SkipRecord) -> None:
        """Withhold one paragraph from every other mechanism."""
        self._records[id(paragraph)] = record

    def records(self) -> list[SkipRecord]:
        return list(self._records.values())


# The claim a document with the switch down leaves behind: it claims nothing,
# so every call site reads the same with the pass absent as with it present.
EMPTY_CLAIM = ChainClaim()


def _collect_chains(docs) -> list[tuple[str, list[tuple[int, object, object]]]]:
    """The chains in the document, in page order, members in chain order.

    A member with no chain index sorts by its page, which keeps a chain whose
    order is missing readable rather than arbitrary; the plan refuses it further
    down rather than guessing at it here.
    """
    groups: dict[str, list[tuple[int, object, object]]] = {}
    for page_index, page in enumerate(docs.page):
        for paragraph in page.pdf_paragraph:
            chain_id = getattr(paragraph, "chain_id", None)
            if not chain_id:
                continue
            groups.setdefault(chain_id, []).append((page_index, page, paragraph))
    chains = []
    for chain_id, members in groups.items():
        ordered = sorted(
            members,
            key=lambda item: (
                item[0]
                if getattr(item[2], "chain_index", None) is None
                else item[2].chain_index,
                item[0],
            ),
        )
        chains.append((chain_id, ordered))
    chains.sort(key=lambda item: (item[1][0][0], item[0]))
    return chains


def pair_class_of(labels: list[str | None], class_labels: dict) -> str | None:
    """The endpoint pair class a chain's members all belong to, if exactly one.

    The classes come from the chain detection vocabulary, so the strategy a
    chain is cut by is read from the same declaration the chain was built
    under. Members spanning two classes, or none, resolve to no class and take
    the declared default.
    """
    matches = [
        name
        for name, members in class_labels.items()
        if all(label in members for label in labels)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


class ChainPlan:
    """Every chain of one document, merged and cut, waiting to be written back."""

    def __init__(self, translator):
        self.translator = translator
        self.config = backfill.load_backfill_config()
        self.class_labels = load_chain_config()[CLASS_LABELS_KEY]
        self.language = translator.translation_config.lang_out
        self.entries: list[ChainEntry] = []
        self.escalated: list[dict] = []
        self.chain_count = 0
        self.claim = ChainClaim()
        self.applied = False

    # --- planning -----------------------------------------------------------

    def plan(self, docs, tracker) -> ChainPlan:
        for chain_id, members in _collect_chains(docs):
            self.chain_count += 1
            self._plan_chain(chain_id, members, tracker)
        return self

    def _escalate(self, chain_id, members, reason: str, detail: str = "") -> None:
        logger.debug("chain %s left to the paragraph path: %s", chain_id, reason)
        self.escalated.append(
            {
                "chain_id": chain_id,
                "reason": reason,
                "detail": detail,
                "members": [
                    {
                        "debug_id": getattr(paragraph, "debug_id", None),
                        "chain_index": getattr(paragraph, "chain_index", None),
                        "page_index": page_index,
                        "layout_label": getattr(paragraph, "layout_label", None),
                    }
                    for page_index, _page, paragraph in members
                ],
            }
        )

    def _prepare(self, members, tracker) -> tuple[list[MemberPlan], str, str]:
        """Ask the pipeline for each member's source text and its placeholders.

        Nothing here writes to a paragraph, so a chain refused after this point
        goes back to the per paragraph path exactly as it arrived.
        """
        prepared: list[MemberPlan] = []
        for page_index, page, paragraph in members:
            page_font_map, xobj_font_map = self.translator._build_font_maps(page)
            member_tracker = tracker.new_paragraph()
            text, translate_input = (
                self.translator.il_translator.pre_translate_paragraph(
                    paragraph, member_tracker, page_font_map, xobj_font_map
                )
            )
            if text is None or translate_input is None:
                return (
                    [],
                    ESCALATION_MEMBER,
                    f"member {getattr(paragraph, 'debug_id', None)} has no text to "
                    f"translate",
                )
            if translate_input.placeholders:
                return (
                    [],
                    ESCALATION_PLACEHOLDER,
                    f"member {getattr(paragraph, 'debug_id', None)} carries "
                    f"{len(translate_input.placeholders)} placeholder(s)",
                )
            prepared.append(
                MemberPlan(
                    paragraph=paragraph,
                    tracker=member_tracker,
                    translate_input=translate_input,
                    source=text,
                    page_index=page_index,
                )
            )
        return prepared, "", ""

    def _plan_chain(self, chain_id: str, members, tracker) -> None:
        if len(members) < 2:
            self._escalate(
                chain_id,
                members,
                ESCALATION_INCOMPLETE,
                f"{len(members)} member(s) carry this chain id",
            )
            return

        chain_tracker = tracker.new_cross_page()
        prepared, reason, detail = self._prepare(members, chain_tracker)
        if reason:
            self._escalate(chain_id, members, reason, detail)
            return

        pair_class = pair_class_of(
            [getattr(member.paragraph, "layout_label", None) for member in prepared],
            self.class_labels,
        )
        strategy = backfill.strategy_for_pair_class(pair_class, self.config)
        try:
            merge = backfill.merge_chain_text(
                [member.source for member in prepared], self.config
            )
        except backfill.ChainBackfillError as error:
            self._escalate(chain_id, members, ESCALATION_MEMBER, str(error))
            return
        try:
            translated = self._translate(merge.text, prepared, chain_tracker)
        except Exception as error:  # the engine and its output are both foreign
            logger.warning("chain %s could not be translated: %s", chain_id, error)
            self._escalate(chain_id, members, ESCALATION_TRANSLATION, str(error))
            return
        try:
            redistribution = backfill.redistribute(
                merge, translated, self.language, strategy, self.config
            )
        except backfill.ChainBackfillError as error:
            self._escalate(chain_id, members, ESCALATION_CONSERVATION, str(error))
            return

        entry = ChainEntry(
            chain_id=chain_id,
            pair_class=pair_class,
            strategy=strategy,
            members=prepared,
            merge=merge,
            translated=translated,
            redistribution=redistribution,
        )
        self.entries.append(entry)
        for member in prepared:
            self.claim.take(
                member.paragraph,
                SkipRecord(
                    chain_id=chain_id,
                    chain_index=member.chain_index,
                    debug_id=member.debug_id,
                    page_index=member.page_index,
                ),
            )

    def _translate(self, merged: str, members: list[MemberPlan], chain_tracker) -> str:
        """Send one merged chain through the machinery a batch already uses."""
        translator = self.translator
        shared = translator.translation_config.shared_context_cross_split_part
        json_input = [
            {
                "id": _SINGLE_ITEM_ID,
                "input": merged,
                "layout_label": getattr(members[0].paragraph, "layout_label", None),
            }
        ]
        prompt = translator._build_llm_prompt(
            json_input_str=json.dumps(json_input, ensure_ascii=False, indent=2),
            title_paragraph=shared.first_paragraph,
            local_title_paragraph=shared.recent_title_paragraph,
            batch_text_for_glossary_matching=merged,
        )
        llm_trackers = [
            member.tracker.new_llm_translate_tracker() for member in members
        ]
        for llm_tracker in llm_trackers:
            llm_tracker.set_input(prompt)
        token_count = translator.calc_token_count(merged)
        raw = translator.translate_engine.llm_translate(
            prompt,
            rate_limit_params={
                "paragraph_token_count": token_count,
                "request_json_mode": True,
            },
        )
        for llm_tracker in llm_trackers:
            llm_tracker.set_output(raw)
        parsed = json.loads(translator._clean_json_output(raw.strip()))
        if isinstance(parsed, dict):
            parsed = [parsed]
        results = {
            int(item["id"]): item.get("output", item.get("input"))
            for item in parsed
            if isinstance(item, dict) and "id" in item
        }
        translated = results.get(_SINGLE_ITEM_ID)
        if not isinstance(translated, str) or not translated.strip():
            raise ChainTranslationError(
                f"the engine returned {type(translated).__name__} for a chain of "
                f"{len(members)} members"
            )
        return translated

    # --- application --------------------------------------------------------

    def apply(self, pbar=None) -> None:
        """Write each member the piece the backfill cut for it, then report.

        The pieces were verified against the conservation law when they were
        cut, so this walks a plan rather than deciding anything, and it runs
        after the per paragraph machinery so that nothing it writes can reach
        the context that machinery built.
        """
        translator = self.translator
        for entry in self.entries:
            for member, segment in zip(
                entry.members, entry.redistribution.segments, strict=True
            ):
                translator.il_translator.post_translate_paragraph(
                    member.paragraph,
                    member.tracker,
                    member.translate_input,
                    segment.text,
                )
                member.paragraph.segment_sentence_start = segment.sentence_start
                member.paragraph.segment_sentence_end = segment.sentence_end
                translator.total_count += 1
                translator.ok_count += 1
                if pbar:
                    pbar.advance(1)
        self.applied = True
        self.write_report()

    # --- reporting ----------------------------------------------------------

    def as_record(self) -> dict:
        merged_members = sum(len(entry.members) for entry in self.entries)
        return {
            "language": self.language,
            "counts": {
                "chains": self.chain_count,
                "merged": len(self.entries),
                "escalated": len(self.escalated),
                "merged_members": merged_members,
                "skips": len(self.claim),
            },
            "applied": self.applied,
            "chains": [entry.as_record() for entry in self.entries],
            "escalated": list(self.escalated),
            "skips": [record.as_record() for record in self.claim.records()],
        }

    def write_report(self) -> Path:
        path = Path(
            self.translator.translation_config.get_working_file_path(REPORT_NAME)
        )
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.as_record(), f, indent=2, sort_keys=True)
        logger.debug(
            "chain translation: %d chain(s), %d merged, %d escalated, report at %s",
            self.chain_count,
            len(self.entries),
            len(self.escalated),
            path,
        )
        return path


def plan_chain_translation(translator, docs, tracker) -> ChainPlan:
    """Merge, translate and cut every chain in ``docs``, writing nothing yet."""
    return ChainPlan(translator).plan(docs, tracker)
