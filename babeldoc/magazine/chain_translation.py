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

A confirmed chain is claimed before its preflight begins. If its topology,
article identity, placeholders, request, or redistribution cannot be trusted,
the members remain untranslated and protected from every per-paragraph path.
The sidecar and RunTrace both record the explicit terminal outcome.
"""

from __future__ import annotations

import json
import logging
import re
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
from babeldoc.magazine.run_trace import ChainResultState
from babeldoc.magazine.run_trace import hash_record

logger = logging.getLogger(__name__)

REPORT_NAME = "chain_translation.report.json"

# Why a confirmed chain could not produce an applicable joint result.
ESCALATION_PLACEHOLDER = "placeholder_bearing"
ESCALATION_CONSERVATION = "conservation_failure"
ESCALATION_MEMBER = "member_unavailable"
ESCALATION_TRANSLATION = "translation_unavailable"
ESCALATION_INCOMPLETE = "incomplete_chain"
ESCALATION_TOKEN_BUDGET = "token_budget"
ESCALATION_ARTICLE = "canonical_article_mismatch"
ESCALATION_TOPOLOGY = "invalid_chain_topology"

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

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        translator_call_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.translator_call_count = translator_call_count


@dataclass(frozen=True)
class CollectedMember:
    page_index: int
    paragraph_index: int
    page: object
    paragraph: object

    @property
    def source_ref(self) -> str:
        return f"p{self.page_index + 1}#{self.paragraph_index}"

    @property
    def chain_index(self):
        return getattr(self.paragraph, "chain_index", None)


@dataclass(frozen=True)
class ChainPreflight:
    canonical_chain_id: str
    article_id: str
    ordered_source_refs: tuple[str, ...]


@dataclass
class MemberPlan:
    """One member, prepared for the merge and waiting for its piece."""

    paragraph: object
    tracker: object
    translate_input: object
    source: str
    page_index: int
    source_ref: str
    placeholder_tokens: tuple[str, ...] = ()

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
    request_id: str | None = None
    canonical_chain_id: str | None = None
    article_id: str | None = None
    translator_call_count: int = 1
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
        record = {
            "chain_id": self.chain_id,
            "canonical_chain_id": self.canonical_chain_id,
            "article_id": self.article_id,
            "ordered_source_refs": [member.source_ref for member in self.members],
            "request_id": self.request_id,
            "translator_call_count": self.translator_call_count,
            "result_state": ChainResultState.JOINT_SUCCESS.value,
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
        return record


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
    result_state: str | None = None
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
            "result_state": self.result_state,
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
        self._released: list[SkipRecord] = []

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
        self.take_many([(paragraph, record)])

    def take_many(self, rows: list[tuple[object, SkipRecord]]) -> None:
        """Establish a complete claim without exposing a partial member set."""
        identities = [id(paragraph) for paragraph, _record in rows]
        if not identities or len(identities) != len(set(identities)):
            raise ValueError("claim members must be non-empty and unique")
        if any(identity in self._records for identity in identities):
            raise ValueError("a paragraph can be held by only one active claim")
        self._records.update(
            {
                id(paragraph): record
                for paragraph, record in rows
            }
        )

    def set_result(
        self, paragraphs: list[object], result_state: ChainResultState
    ) -> None:
        records = [self._records.get(id(paragraph)) for paragraph in paragraphs]
        if any(record is None for record in records):
            raise ValueError("a chain result requires every member to remain claimed")
        for record in records:
            record.result_state = result_state.value

    def release_all(self) -> None:
        """Close the guard window without exposing a partial release."""
        records = list(self._records.values())
        self._records.clear()
        self._released.extend(records)

    def records(self) -> list[SkipRecord]:
        return [*self._released, *self._records.values()]


# The claim a document with the switch down leaves behind: it claims nothing,
# so every call site reads the same with the pass absent as with it present.
EMPTY_CLAIM = ChainClaim()


def _collect_chains(docs) -> list[tuple[str, list[CollectedMember]]]:
    """The chains in the document, in page order, members in chain order.

    A member with no chain index sorts by its page, which keeps a chain whose
    order is missing readable rather than arbitrary; the plan refuses it further
    down rather than guessing at it here.
    """
    groups: dict[str, list[CollectedMember]] = {}
    for page_index, page in enumerate(docs.page):
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph):
            chain_id = getattr(paragraph, "chain_id", None)
            if not chain_id:
                continue
            groups.setdefault(chain_id, []).append(
                CollectedMember(page_index, paragraph_index, page, paragraph)
            )
    chains = []
    for chain_id, members in groups.items():
        ordered = sorted(
            members,
            key=lambda member: (
                member.page_index
                if member.chain_index is None
                else member.chain_index,
                member.page_index,
                member.paragraph_index,
            ),
        )
        chains.append((chain_id, ordered))
    chains.sort(key=lambda item: (item[1][0].page_index, item[0]))
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


def _placeholder_tokens(source: str, translate_input) -> tuple[str, ...]:
    """Return every protected token in source order or reject ambiguity."""
    occurrences: list[tuple[int, int, str]] = []
    for placeholder in getattr(translate_input, "placeholders", ()):
        if hasattr(placeholder, "placeholder") and hasattr(
            placeholder, "regex_pattern"
        ):
            patterns = (placeholder.regex_pattern,)
        elif all(
            hasattr(placeholder, name)
            for name in (
                "left_regex_pattern",
                "right_regex_pattern",
            )
        ):
            patterns = (
                placeholder.left_regex_pattern,
                placeholder.right_regex_pattern,
            )
        else:
            raise ChainTranslationError("unsupported placeholder shape")
        for pattern in patterns:
            matches = list(re.finditer(pattern, source, flags=re.IGNORECASE))
            if len(matches) != 1:
                raise ChainTranslationError(
                    "each injected placeholder token must occur exactly once"
                )
            match = matches[0]
            occurrences.append((match.start(), match.end(), match.group(0)))
    for token, expected_count in getattr(
        translate_input, "original_placeholder_tokens", {}
    ).items():
        matches = list(re.finditer(re.escape(token), source))
        if len(matches) != expected_count:
            raise ChainTranslationError(
                "original placeholder token count changed during preparation"
            )
        occurrences.extend(
            (match.start(), match.end(), match.group(0)) for match in matches
        )
    occurrences.sort(key=lambda item: (item[0], item[1]))
    if any(
        left[1] > right[0]
        for left, right in zip(occurrences, occurrences[1:], strict=False)
    ):
        raise ChainTranslationError("placeholder tokens overlap")
    return tuple(token for _start, _end, token in occurrences)


def _tokens_in(text: str, expected: tuple[str, ...]) -> tuple[str, ...]:
    vocabulary = sorted(set(expected), key=lambda token: (-len(token), token))
    if not vocabulary:
        return ()
    pattern = "|".join(re.escape(token) for token in vocabulary)
    return tuple(match.group(0) for match in re.finditer(pattern, text))


class ChainPlan:
    """Every chain of one document, merged and cut, waiting to be written back."""

    def __init__(
        self, translator, article_context=EMPTY_CONTEXT, article_document_ir=None
    ):
        self.translator = translator
        self.article_context = article_context
        self.article_document_ir = article_document_ir
        self.config = backfill.load_backfill_config()
        self.class_labels = load_chain_config()[CLASS_LABELS_KEY]
        self.language = translator.translation_config.lang_out
        self.entries: list[ChainEntry] = []
        self.escalated: list[dict] = []
        self.outcomes: list[dict] = []
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

    def _stable_chain_id(self, members: list[CollectedMember]) -> str:
        refs = tuple(member.source_ref for member in members)
        if self.article_document_ir is not None:
            canonical = {
                self.article_document_ir.by_chain_member.get(reference)
                for reference in refs
            }
            canonical.discard(None)
            if len(canonical) == 1:
                return canonical.pop()
        return f"chain-{hash_record(refs)}"

    def _claim_chain(self, chain_id: str, members: list[CollectedMember]) -> None:
        self.claim.take_many(
            [
                (
                    member.paragraph,
                    SkipRecord(
                        chain_id=chain_id,
                        chain_index=member.chain_index,
                        debug_id=getattr(member.paragraph, "debug_id", None),
                        page_index=member.page_index,
                    ),
                )
                for member in members
            ]
        )

    def _preflight_members(
        self, members: list[CollectedMember]
    ) -> tuple[ChainPreflight | None, str, str]:
        refs = tuple(member.source_ref for member in members)
        if len(members) < 2:
            return None, ESCALATION_INCOMPLETE, f"{len(members)} member(s)"
        unique_objects = {id(member.paragraph) for member in members}
        if len(refs) != len(set(refs)) or len(unique_objects) != len(members):
            return None, ESCALATION_TOPOLOGY, "ordered members are not unique"
        indices = [member.chain_index for member in members]
        if indices != list(range(len(members))):
            return None, ESCALATION_TOPOLOGY, f"chain indices are {indices}"
        pages = [member.page_index for member in members]
        page_pairs = zip(pages, pages[1:], strict=False)
        if any(right < left or right - left > 1 for left, right in page_pairs):
            return None, ESCALATION_TOPOLOGY, (
                f"member pages are not continuous: {pages}"
            )
        if self.article_document_ir is None:
            return None, ESCALATION_ARTICLE, (
                "canonical ArticleDocumentIR is unavailable"
            )
        articles = [
            self.article_document_ir.by_element.get(reference) for reference in refs
        ]
        if any(article is None for article in articles) or len(set(articles)) != 1:
            return None, ESCALATION_ARTICLE, f"member article ids are {articles}"
        page_articles = [
            self.article_document_ir.by_page.get(member.page_index + 1)
            for member in members
        ]
        if any(article != articles[0] for article in page_articles):
            return None, ESCALATION_ARTICLE, (
                f"member page article ids are {page_articles}"
            )
        canonical_chains = [
            self.article_document_ir.by_chain_member.get(reference)
            for reference in refs
        ]
        if any(chain is None for chain in canonical_chains) or len(
            set(canonical_chains)
        ) != 1:
            return None, ESCALATION_TOPOLOGY, (
                f"canonical chain ids are {canonical_chains}"
            )
        canonical_chain_id = canonical_chains[0]
        article_id = articles[0]
        if self.article_document_ir.by_chain.get(canonical_chain_id) != article_id:
            return None, ESCALATION_ARTICLE, (
                "canonical chain owner disagrees with members"
            )
        return (
            ChainPreflight(canonical_chain_id, article_id, refs),
            "",
            "",
        )

    def _record_outcome(
        self,
        chain_id: str,
        members: list[CollectedMember],
        state: ChainResultState,
        *,
        reason: str = "",
        detail: str = "",
        request_id: str | None = None,
        translator_call_count: int = 0,
        canonical_chain_id: str | None = None,
        article_id: str | None = None,
    ) -> None:
        stable_chain_id = canonical_chain_id or self._stable_chain_id(members)
        references = tuple(member.source_ref for member in members)
        self.claim.set_result([member.paragraph for member in members], state)
        record = {
            "chain_id": chain_id,
            "canonical_chain_id": stable_chain_id,
            "article_id": article_id,
            "ordered_source_refs": list(references),
            "request_id": request_id,
            "translator_call_count": translator_call_count,
            "result_state": state.value,
            "reason": reason,
            "detail": detail,
            "members": [
                {
                    "source_ref": member.source_ref,
                    "debug_id": getattr(member.paragraph, "debug_id", None),
                    "chain_index": member.chain_index,
                    "page_index": member.page_index,
                    "layout_label": getattr(member.paragraph, "layout_label", None),
                }
                for member in members
            ],
        }
        self.outcomes.append(record)
        if state != ChainResultState.JOINT_SUCCESS:
            logger.warning("chain %s protected after %s: %s", chain_id, reason, detail)
            self.escalated.append(record)
        trace = getattr(self.translator, "run_trace", None)
        if trace is not None:
            trace.record_chain_outcome(
                stable_chain_id,
                references,
                state,
                request_id=request_id,
                translator_call_count=translator_call_count,
                issue=detail or reason or None,
            )

    def _prepare(self, members, tracker) -> tuple[list[MemberPlan], str, str]:
        """Ask the pipeline for each member's source text and its placeholders.

        Nothing here writes to a paragraph. A refusal leaves its claim active.
        """
        prepared: list[MemberPlan] = []
        for member in members:
            paragraph = member.paragraph
            page_font_map, xobj_font_map = self.translator._build_font_maps(member.page)
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
            try:
                placeholder_tokens = _placeholder_tokens(text, translate_input)
            except (ChainTranslationError, re.error) as error:
                return (
                    [],
                    ESCALATION_PLACEHOLDER,
                    f"{member.source_ref}: {error}",
                )
            prepared.append(
                MemberPlan(
                    paragraph=paragraph,
                    tracker=member_tracker,
                    translate_input=translate_input,
                    source=text,
                    page_index=member.page_index,
                    source_ref=member.source_ref,
                    placeholder_tokens=placeholder_tokens,
                )
            )
        return prepared, "", ""

    def _plan_chain(
        self, chain_id: str, members: list[CollectedMember], tracker
    ) -> None:
        self._claim_chain(chain_id, members)
        preflight, reason, detail = self._preflight_members(members)
        if preflight is None:
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.PROTECTED_UNTRANSLATED,
                reason=reason,
                detail=detail,
            )
            return
        chain_tracker = tracker.new_cross_page()
        prepared, reason, detail = self._prepare(members, chain_tracker)
        if reason:
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.PROTECTED_UNTRANSLATED,
                reason=reason,
                detail=detail,
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
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
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.PROTECTED_UNTRANSLATED,
                reason=ESCALATION_MEMBER,
                detail=str(error),
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
            return
        expected_tokens = tuple(
            token for member in prepared for token in member.placeholder_tokens
        )
        if _tokens_in(merge.text, expected_tokens) != expected_tokens:
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.PROTECTED_UNTRANSLATED,
                reason=ESCALATION_PLACEHOLDER,
                detail="merged source changed placeholder order",
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
            return

        # Asked before the request, because the engine truncates an answer that
        # reaches its output ceiling instead of refusing it, and a truncated
        # answer is a string the redistribution would happily cut up. Splitting
        # the chain instead would put a page break back inside the sentence the
        # chain exists to close, so an oversized chain goes back whole.
        source_tokens = self.translator.calc_token_count(merge.text)
        if backfill.over_output_token_budget(source_tokens, self.config):
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.PROTECTED_UNTRANSLATED,
                reason=ESCALATION_TOKEN_BUDGET,
                detail=f"{source_tokens} source token(s) estimate "
                f"{backfill.estimated_output_tokens(source_tokens, self.config)} "
                f"output token(s), over the budget of "
                f"{self.config.output_token_budget}",
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
            return
        try:
            translated, request_id, translator_call_count = self._translate(
                merge.text, prepared, chain_tracker
            )
        except ChainTranslationError as error:
            logger.warning("chain %s could not be translated: %s", chain_id, error)
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.FAILED_WITH_ISSUE,
                reason=ESCALATION_TRANSLATION,
                detail=str(error),
                request_id=error.request_id,
                translator_call_count=error.translator_call_count,
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
            return
        if _tokens_in(translated, expected_tokens) != expected_tokens:
            detail = "joint response changed placeholder set or order"
            if request_id is not None:
                self.translator.run_trace.fail_request(request_id, detail)
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.FAILED_WITH_ISSUE,
                reason=ESCALATION_PLACEHOLDER,
                detail=detail,
                request_id=request_id,
                translator_call_count=translator_call_count,
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
            return
        try:
            redistribution = backfill.redistribute(
                merge,
                translated,
                self.language,
                strategy,
                self.config,
                aligned_lengths=None,
                align_enabled=self.align_enabled,
                capacities=self._capacities(prepared, strategy),
            )
        except backfill.ChainBackfillError as error:
            if request_id is not None:
                self.translator.run_trace.fail_request(
                    request_id, f"redistribution failed: {error}"
                )
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.FAILED_WITH_ISSUE,
                reason=ESCALATION_CONSERVATION,
                detail=str(error),
                request_id=request_id,
                translator_call_count=translator_call_count,
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
            return

        for member, segment in zip(prepared, redistribution.segments, strict=True):
            if _tokens_in(segment.text, expected_tokens) != member.placeholder_tokens:
                detail = f"{member.source_ref} did not retain its placeholder sequence"
                if request_id is not None:
                    self.translator.run_trace.fail_request(request_id, detail)
                self._record_outcome(
                    chain_id,
                    members,
                    ChainResultState.FAILED_WITH_ISSUE,
                    reason=ESCALATION_PLACEHOLDER,
                    detail=detail,
                    request_id=request_id,
                    translator_call_count=translator_call_count,
                    canonical_chain_id=preflight.canonical_chain_id,
                    article_id=preflight.article_id,
                )
                return

        if request_id is not None:
            try:
                for member, segment in zip(
                    prepared, redistribution.segments, strict=True
                ):
                    reference = self.translator.run_trace.source_ref_for(
                        member.paragraph
                    )
                    if reference is None:
                        raise ValueError("chain member has no frozen source ref")
                    self.translator.run_trace.allocate_target_fragment(
                        request_id,
                        reference,
                        order=segment.index,
                        text_start=segment.start,
                        text_end=segment.end,
                        text=segment.text,
                    )
                self.translator.run_trace.complete_request(request_id)
            except Exception as error:
                self.translator.run_trace.fail_request(
                    request_id, f"fragment allocation failed: {error}"
                )
                self._record_outcome(
                    chain_id,
                    members,
                    ChainResultState.FAILED_WITH_ISSUE,
                    reason=ESCALATION_CONSERVATION,
                    detail=str(error),
                    request_id=request_id,
                    translator_call_count=translator_call_count,
                    canonical_chain_id=preflight.canonical_chain_id,
                    article_id=preflight.article_id,
                )
                return

        entry = ChainEntry(
            chain_id=chain_id,
            pair_class=pair_class,
            strategy=strategy,
            members=prepared,
            merge=merge,
            translated=translated,
            redistribution=redistribution,
            request_id=request_id,
            canonical_chain_id=preflight.canonical_chain_id,
            article_id=preflight.article_id,
            translator_call_count=translator_call_count,
            capacity=self._capacity_record(prepared)
            if strategy == backfill.STRATEGY_CAPACITY
            else [],
        )
        self.entries.append(entry)
        self._record_outcome(
            chain_id,
            members,
            ChainResultState.JOINT_SUCCESS,
            request_id=request_id,
            translator_call_count=translator_call_count,
            canonical_chain_id=preflight.canonical_chain_id,
            article_id=preflight.article_id,
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

    def _translate(
        self, merged: str, members: list[MemberPlan], chain_tracker
    ) -> tuple[str, str | None, int]:
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
        placeholder_hints = {
            token: hint
            for member in members
            for token, hint in (
                member.translate_input.get_placeholders_hint() or {}
            ).items()
        }
        if (
            placeholder_hints
            and translator.translation_config.add_formula_placehold_hint
        ):
            json_input[0]["formula_placeholders_hint"] = placeholder_hints
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
        trace_request_id = None
        trace = getattr(translator, "run_trace", None)
        if trace is not None:
            references = [
                trace.source_ref_for(member.paragraph)
                for member in members
            ]
            if any(reference is None for reference in references):
                raise ChainTranslationError("chain member has no frozen source ref")
            if tuple(references) != tuple(member.source_ref for member in members):
                raise ChainTranslationError("frozen source refs changed before request")
            trace_request_id = trace.open_request(
                "continuity_chain",
                references,
                merged,
                translator._trace_prompt_config(prompt),
            )
        llm_trackers = [
            member.tracker.new_llm_translate_tracker() for member in members
        ]
        for llm_tracker in llm_trackers:
            llm_tracker.set_input(prompt)
        token_count = translator.calc_token_count(merged)
        translator_call_count = 0
        try:
            if trace_request_id is not None:
                trace.record_translator_call(trace_request_id)
            translator_call_count = 1
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
            if (
                not isinstance(parsed, list)
                or len(parsed) != 1
                or not isinstance(parsed[0], dict)
                or int(parsed[0].get("id", -1)) != _SINGLE_ITEM_ID
            ):
                raise ChainTranslationError(
                    "the engine did not return exactly one chain result"
                )
            translated = parsed[0].get("output", parsed[0].get("input"))
            if not isinstance(translated, str) or not translated.strip():
                raise ChainTranslationError(
                    f"the engine returned {type(translated).__name__} for a chain of "
                    f"{len(members)} members"
                )
            if trace_request_id is not None:
                trace.register_whole_target(trace_request_id, translated)
            return translated, trace_request_id, translator_call_count
        except Exception as error:
            if trace_request_id is not None:
                trace.fail_request(trace_request_id, str(error))
            if isinstance(error, ChainTranslationError):
                raise ChainTranslationError(
                    str(error),
                    request_id=trace_request_id,
                    translator_call_count=translator_call_count,
                ) from error
            raise ChainTranslationError(
                str(error),
                request_id=trace_request_id,
                translator_call_count=translator_call_count,
            ) from error

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
        self.claim.release_all()
        self.write_report()

    # --- reporting ----------------------------------------------------------

    def as_record(self) -> dict:
        merged_members = sum(len(entry.members) for entry in self.entries)
        claim_records = self.claim.records()
        return {
            "language": self.language,
            "counts": {
                "chains": self.chain_count,
                "merged": len(self.entries),
                "escalated": len(self.escalated),
                "merged_members": merged_members,
                "skips": len(claim_records),
                "translator_calls": sum(
                    outcome["translator_call_count"] for outcome in self.outcomes
                ),
                "alignment_requests": 0,
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
            "outcomes": list(self.outcomes),
            "skips": [record.as_record() for record in claim_records],
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
    translator,
    docs,
    tracker,
    article_context=EMPTY_CONTEXT,
    article_document_ir=None,
) -> ChainPlan:
    """Merge, translate and cut every chain in ``docs``, writing nothing yet."""
    return ChainPlan(translator, article_context, article_document_ir).plan(
        docs, tracker
    )
