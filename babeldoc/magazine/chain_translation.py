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
placeholder, a member the pipeline will not hand over text for, a chain whose
answer would be larger than the engine will return in one piece, an engine that
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
from babeldoc.magazine import short_unit
from babeldoc.magazine.article_context import EMPTY_CONTEXT
from babeldoc.magazine.chain_signals import BOUNDARY_COLUMN
from babeldoc.magazine.chain_signals import BOUNDARY_PAGE
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
ESCALATION_TOKEN_BUDGET = "token_budget"

# Which pass holds a claimed paragraph.
TAKEN_BY_CHAIN = "chain"
TAKEN_BY_SHORT_UNIT = "short_unit"

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
    capacity: list[dict] = field(default_factory=list)

    @property
    def boundary_kinds(self) -> list[str]:
        """What broke the chain between each pair of consecutive members.

        Read off the pages the two members sit on rather than off the detector's
        verdicts: a handover inside one page is a column edge and a handover
        between two is a page edge, and that is the whole of the distinction.
        It is recorded and not acted on -- a running paragraph is cut the same
        way whichever edge interrupted it -- so that the record can show the
        two kinds were treated alike instead of asserting it.
        """
        return [
            BOUNDARY_COLUMN if left.page_index == right.page_index else BOUNDARY_PAGE
            for left, right in zip(self.members, self.members[1:], strict=False)
        ]

    def as_record(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "pair_class": self.pair_class,
            "strategy": self.strategy,
            "boundary_kinds": self.boundary_kinds,
            "capacity": self.capacity,
            "cut_displacement": [
                None if cut.estimate is None else cut.position - cut.estimate
                for cut in self.redistribution.cuts
            ],
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
    """One paragraph another pass has taken, and who asked for it and was refused.

    ``taken_by`` names which pass has it. Two do: the chain pass, which merges
    it with the rest of its chain, and the short unit pass, which translates it
    on its own because the length floor never offered it a request. Either way
    the page batch has to leave it alone, and the record says which pass to ask
    about it.
    """

    chain_id: str
    chain_index: int | None
    debug_id: str | None
    page_index: int
    taken_by: str = TAKEN_BY_CHAIN
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
            "taken_by": self.taken_by,
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

    def __init__(self, translator, article_context=EMPTY_CONTEXT):
        self.translator = translator
        self.article_context = article_context
        self.config = backfill.load_backfill_config()
        self.class_labels = load_chain_config()[CLASS_LABELS_KEY]
        self.language = translator.translation_config.lang_out
        self.entries: list[ChainEntry] = []
        self.escalated: list[dict] = []
        self.chain_count = 0
        self.claim = ChainClaim()
        self.applied = False
        self.align_enabled = bool(
            getattr(translator.translation_config, self.config.align_switch, False)
        )
        self.alignment_calls = 0
        # The short unit pass rides here rather than at a hook of its own: the
        # translation stage offers exactly one place a magazine pass can run
        # before the page batches, and this is it. What it needs from the stage
        # is what the chain pass needs -- the translator, the document, the
        # tracker and the article context -- and what it gives back is a claim
        # of the same kind, so the two travel together and upstream sees one.
        self.short_units = None

    # --- planning -----------------------------------------------------------

    def plan(self, docs, tracker) -> ChainPlan:
        for chain_id, members in _collect_chains(docs):
            self.chain_count += 1
            self._plan_chain(chain_id, members, tracker)
        self._plan_short_units(docs, tracker)
        return self

    def _plan_short_units(self, docs, tracker) -> None:
        """Translate the paragraphs the length floor never offered a request.

        Run after the chains, so a paragraph a chain has taken is already
        claimed and is not offered twice. A claimed paragraph is skipped by the
        admission test through the same claim the page batch reads.
        """
        translation_config = self.translator.translation_config
        if not short_unit.enabled(translation_config):
            return
        plan_result = short_unit.plan(
            self.translator, docs, tracker, self.article_context
        )
        self.short_units = plan_result
        for unit in plan_result.units:
            if self.claim.claims_paragraph(unit.paragraph):
                continue
            self.claim.take(
                unit.paragraph,
                SkipRecord(
                    chain_id="",
                    chain_index=None,
                    debug_id=getattr(unit.paragraph, "debug_id", None),
                    page_index=unit.page_index,
                    taken_by=TAKEN_BY_SHORT_UNIT,
                ),
            )

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

        # Asked before the request, because the engine truncates an answer that
        # reaches its output ceiling instead of refusing it, and a truncated
        # answer is a string the redistribution would happily cut up. Splitting
        # the chain instead would put a page break back inside the sentence the
        # chain exists to close, so an oversized chain goes back whole.
        source_tokens = self.translator.calc_token_count(merge.text)
        if backfill.over_output_token_budget(source_tokens, self.config):
            self._escalate(
                chain_id,
                members,
                ESCALATION_TOKEN_BUDGET,
                f"{source_tokens} source token(s) estimate "
                f"{backfill.estimated_output_tokens(source_tokens, self.config)} "
                f"output token(s), over the budget of "
                f"{self.config.output_token_budget}",
            )
            return
        try:
            translated = self._translate(merge.text, prepared, chain_tracker)
        except Exception as error:  # the engine and its output are both foreign
            logger.warning("chain %s could not be translated: %s", chain_id, error)
            self._escalate(chain_id, members, ESCALATION_TRANSLATION, str(error))
            return
        try:
            redistribution = backfill.redistribute(
                merge,
                translated,
                self.language,
                strategy,
                self.config,
                aligned_lengths=self._aligned_lengths(prepared, strategy),
                align_enabled=self.align_enabled,
                capacities=self._capacities(prepared, strategy),
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
            capacity=self._capacity_record(prepared)
            if strategy == backfill.STRATEGY_CAPACITY
            else [],
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

    def _capacities(
        self, members: list[MemberPlan], strategy: str
    ) -> list[int] | None:
        """How many characters of the target language each member's box holds.

        This is the half of the capacity cut that needs the document, which is
        why it lives here and not in the pure module: the boxes are on the
        paragraphs and the estimate is arithmetic over them.

        The typesetting stage's own packer was the first candidate and it
        cannot serve. It is a method of the stage, it needs the mapped font and
        a list of typesetting units built from laid out characters, and at this
        point in the run the translation is a string with no characters behind
        it -- there is nothing for that packer to pack. The grid is declared in
        the configuration and measured against the frozen runs instead.

        Returns None where any member cannot be measured, so a chain is cut by
        one method throughout: a mixture of measured and estimated cuts in one
        chain would put a boundary of unknown provenance in the middle of it.
        """
        if strategy != backfill.STRATEGY_CAPACITY:
            return None
        grid = self.config.capacity
        capacities = []
        for member in members:
            box = getattr(member.paragraph, "box", None)
            style = getattr(member.paragraph, "pdf_style", None)
            font_size = getattr(style, "font_size", None) if style else None
            if box is None or font_size is None:
                return None
            try:
                width = float(box.x2) - float(box.x)
                height = float(box.y2) - float(box.y)
            except TypeError:
                return None
            characters = grid.characters_in(width, height, float(font_size), self.language)
            if characters <= 0:
                return None
            capacities.append(characters)
        return capacities

    def _capacity_record(self, members: list[MemberPlan]) -> list[dict]:
        """What each member's box was measured as, for the sidecar."""
        grid = self.config.capacity
        rows = []
        for member in members:
            box = getattr(member.paragraph, "box", None)
            style = getattr(member.paragraph, "pdf_style", None)
            font_size = getattr(style, "font_size", None) if style else None
            if box is None or font_size is None:
                rows.append({"chain_index": member.chain_index, "measurable": False})
                continue
            width = float(box.x2) - float(box.x)
            height = float(box.y2) - float(box.y)
            rows.append(
                {
                    "chain_index": member.chain_index,
                    "measurable": True,
                    "page_index": member.page_index,
                    "box": [round(float(v), 2) for v in (box.x, box.y, box.x2, box.y2)],
                    "font_size": round(float(font_size), 3),
                    "fitted_lines": grid.lines_in(height, float(font_size), self.language),
                    "capacity_chars": grid.characters_in(
                        width, height, float(font_size), self.language
                    ),
                }
            )
        return rows

    def _aligned_lengths(
        self, members: list[MemberPlan], strategy: str
    ) -> list[int] | None:
        """Measure each member's own translation, for the cut to be placed by.

        Only for a chain with no sentence structure to cut on. A body chain
        cuts on sentence ends, which are positions in the joint translation and
        need no estimate; a display line chain has nothing but the share, and
        the share is the quantity this replaces.

        The answers are measured and discarded. Nothing a chain writes back
        comes from anywhere but the joint translation, so the auxiliary text is
        never returned from here and never stored: what leaves this method is a
        list of integers. Each request goes through the engine's own cache, so a
        rerun of the same chain sends nothing.

        Returns None where the alignment cannot be had, which the caller records
        as such and the cascade falls softly past.
        """
        if not self.align_enabled or strategy != backfill.STRATEGY_PROPORTIONAL:
            return None
        lengths = []
        engine = self.translator.translate_engine
        for member in members:
            try:
                answer = engine.translate(member.source)
            except Exception as error:  # the engine is foreign and may refuse
                logger.warning(
                    "chain alignment: a member could not be measured: %s", error
                )
                return None
            if not isinstance(answer, str) or not answer.strip():
                return None
            self.alignment_calls += 1
            lengths.append(len(answer))
        return lengths

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
        # A chain never crosses an article, so its members share one brief and
        # the first of them answers for all: a chain is one batch of its
        # article and carries what the article's other batches carry. A chain
        # with no brief asks for exactly the prompt it asked for before, the
        # argument not being passed at all rather than passed as nothing.
        brief = self.article_context.brief_for_page_index(members[0].page_index)
        extra = {"article_brief": brief} if brief else {}
        prompt = translator._build_llm_prompt(
            json_input_str=json.dumps(json_input, ensure_ascii=False, indent=2),
            title_paragraph=shared.first_paragraph,
            local_title_paragraph=shared.recent_title_paragraph,
            batch_text_for_glossary_matching=merged,
            **extra,
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
        if self.short_units is not None:
            short_unit.apply(translator, self.short_units, pbar)
            short_unit.write_report(translator.translation_config, self.short_units)
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
                "alignment_requests": self.alignment_calls,
                "aligned_cuts": sum(
                    1
                    for entry in self.entries
                    if entry.redistribution.alignment is not None
                    and entry.redistribution.alignment.used
                ),
            },
            "align_enabled": self.align_enabled,
            "short_units": None
            if self.short_units is None
            else {
                "admitted": len(self.short_units.units),
                "refused": len(self.short_units.refused),
                "requests": self.short_units.requests,
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


def plan_chain_translation(
    translator, docs, tracker, article_context=EMPTY_CONTEXT
) -> ChainPlan:
    """Merge, translate and cut every chain in ``docs``, writing nothing yet."""
    return ChainPlan(translator, article_context).plan(docs, tracker)
