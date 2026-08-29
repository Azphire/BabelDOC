"""Chain level joint translation: the translation stage's half of it.

A chain is a semantic unit a column or page boundary split. ``chain_backfill``
merges its source members, and this module sends that source to the engine as a
single unit before measuring the resulting target against the canonical
ArticleIR slots. The verified target ranges are then written to those slots in
reading order.

The pass is a plan and an application, deliberately in that order. Planning
merges, translates and measures every chain before the per paragraph machinery
starts, and application writes the allocation after that machinery has
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

A confirmed chain is claimed only after preflight, translation and allocation
have produced one complete, applicable plan.  A planning failure therefore
falls through to the ordinary producers; the sidecar still records that
fallback and the verifier still rejects the run as a successful chain run.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from babeldoc.format.pdf.document_il import Box
from babeldoc.magazine import chain_backfill as backfill
from babeldoc.magazine import line_split
from babeldoc.magazine import short_unit
from babeldoc.magazine.article_context import EMPTY_CONTEXT
from babeldoc.magazine.article_ir import SourceElementRef
from babeldoc.magazine.chain_signals import BOUNDARY_COLUMN
from babeldoc.magazine.chain_signals import BOUNDARY_PAGE
from babeldoc.magazine.chain_signals import CLASS_LABELS_KEY
from babeldoc.magazine.chain_signals import load_chain_config
from babeldoc.magazine.run_trace import ChainResultState
from babeldoc.magazine.run_trace import canonical_text
from babeldoc.magazine.run_trace import hash_record

logger = logging.getLogger(__name__)

REPORT_NAME = "chain_translation.report.json"

# Why a confirmed chain could not produce an applicable joint result.
ESCALATION_PLACEHOLDER = "placeholder_bearing"
ESCALATION_CONSERVATION = "conservation_failure"
ESCALATION_MEMBER = "member_unavailable"
ESCALATION_TRANSLATION = "translation_unavailable"
ESCALATION_INCOMPLETE = "incomplete_chain"
ESCALATION_TOKEN_BUDGET = "token_budget"  # noqa: S105 - reason code, not a secret
ESCALATION_ARTICLE = "canonical_article_mismatch"
ESCALATION_TOPOLOGY = "invalid_chain_topology"
ESCALATION_OVERFLOW = "chain_target_overflow"

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
SLOT_CAPACITY_STRATEGY = "slot_capacity"
SLOT_ALLOCATED = "allocated"
SLOT_RELEASED = "released"

# Scales visited by Typesetting._find_optimal_scale_and_layout.  Capacity is
# measured at the smallest visited scale which still respects the configured
# readable font floor, so the later application pass can reach the exact same
# geometry without needing a typesetter mutation.
_APPLICATION_SCALES = (
    1.0,
    0.95,
    0.9,
    0.85,
    0.8,
    0.75,
    0.7,
    0.65,
    0.6,
    0.5,
    0.4,
    0.3,
    0.2,
    0.1,
)


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
    def runtime_source_ref(self) -> str:
        return f"p{self.page_index + 1}#{self.paragraph_index}"

    @property
    def physical_source_ref(self) -> str:
        page_number = getattr(self.page, "page_number", self.page_index)
        physical_index = self.page_index if page_number is None else int(page_number)
        return f"p{physical_index + 1}#{self.paragraph_index}"

    @property
    def source_ref(self) -> str:
        """Canonical runtime ref retained for ArticleIR and RunTrace joins."""
        return self.runtime_source_ref

    @property
    def chain_index(self):
        return getattr(self.paragraph, "chain_index", None)


@dataclass(frozen=True)
class ChainPreflight:
    canonical_chain_id: str
    article_id: str
    ordered_source_refs: tuple[str, ...]
    ordered_slots: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class MemberSourceSlot:
    """The immutable source box owned by one canonical source element."""

    article_id: str
    page: int
    column: int
    slot_order: int
    box: tuple[float, float, float, float]


@dataclass
class MemberPlan:
    """One member, prepared for the merge and waiting for its piece."""

    paragraph: object
    page: object
    tracker: object
    translate_input: object
    style: object
    source_font: object
    page_font_map: dict
    xobj_font_map: dict
    source: str
    page_index: int
    source_ref: str
    physical_source_ref: str
    placeholder_tokens: tuple[str, ...] = ()
    protected_placeholder_tokens: tuple[str, ...] = ()
    rich_text_placeholder_tokens: tuple[str, ...] = ()

    @property
    def debug_id(self):
        return getattr(self.paragraph, "debug_id", None)

    @property
    def chain_index(self):
        return getattr(self.paragraph, "chain_index", None)


@dataclass(frozen=True, slots=True)
class SlotAllocationFragment:
    """One verified whole-target range assigned to one canonical article slot."""

    member: MemberPlan
    slot_id: str
    page: int
    column: int
    slot_order: int
    box: tuple[float, float, float, float] | None
    text: str
    start: int
    end: int
    released: bool
    measurement_record: dict

    def segment_record(self) -> dict:
        return {
            "index": self.member.chain_index,
            "start": self.start,
            "end": self.end,
            "chars": len(self.text),
            "sentence_start": backfill.NO_SENTENCE_INDEX,
            "sentence_end": backfill.NO_SENTENCE_INDEX,
        }

    def as_record(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "page": self.page,
            "column": self.column,
            "slot_order": self.slot_order,
            "source_ref": self.member.physical_source_ref,
            "runtime_source_ref": self.member.source_ref,
            "target_range": [self.start, self.end],
            "chars": len(self.text),
            "status": SLOT_RELEASED if self.released else SLOT_ALLOCATED,
            "box": None
            if self.box is None
            else [round(value, 3) for value in self.box],
            "measurement": dict(self.measurement_record),
        }


@dataclass(frozen=True, slots=True)
class ChainAllocationPlan:
    """An immutable, fully measured allocation committed as one transaction."""

    whole_target: str
    fragments: tuple[SlotAllocationFragment, ...]

    def __post_init__(self) -> None:
        if not self.fragments:
            raise ValueError("a chain allocation requires at least one slot")
        if [fragment.slot_order for fragment in self.fragments] != sorted(
            fragment.slot_order for fragment in self.fragments
        ):
            raise ValueError("chain allocation slots must follow ArticleIR order")
        cursor = 0
        joined = []
        for fragment in self.fragments:
            if fragment.start != cursor or fragment.end < fragment.start:
                raise ValueError("chain allocation target ranges must be contiguous")
            if fragment.text != self.whole_target[fragment.start : fragment.end]:
                raise ValueError("chain fragment must equal its whole-target range")
            if fragment.released or fragment.start == fragment.end:
                raise ValueError("body chain members must receive non-empty text")
            joined.append(fragment.text)
            cursor = fragment.end
        if cursor != len(self.whole_target) or "".join(joined) != self.whole_target:
            raise ValueError("chain allocation must reconstruct the whole target")

    def as_record(self) -> dict:
        return {
            "verified": True,
            "whole_target_chars": len(self.whole_target),
            "fragments": [fragment.as_record() for fragment in self.fragments],
            "released_slot_ids": [
                fragment.slot_id for fragment in self.fragments if fragment.released
            ],
        }

    def as_redistribution_record(self) -> dict:
        return {
            "strategy": SLOT_CAPACITY_STRATEGY,
            "profile": None,
            "fallback": None,
            "sentence_count": 0,
            "members": [fragment.segment_record() for fragment in self.fragments],
            "cuts": [
                {
                    "index": index,
                    "position": fragment.end,
                    "mode": SLOT_CAPACITY_STRATEGY,
                    "snapped": False,
                    "estimate": None,
                    "moved_to": None,
                }
                for index, fragment in enumerate(self.fragments[:-1])
            ],
            "alignment": None,
        }


@dataclass
class ChainEntry:
    """One chain with a verified slot allocation waiting to be written back."""

    chain_id: str
    pair_class: str | None
    strategy: str
    members: list[MemberPlan]
    merge: backfill.ChainMerge
    translated: str
    allocation: ChainAllocationPlan
    request_id: str | None = None
    canonical_chain_id: str | None = None
    article_id: str | None = None
    translator_call_count: int = 1

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
            "ordered_source_refs": [
                member.physical_source_ref for member in self.members
            ],
            "runtime_source_refs": [member.source_ref for member in self.members],
            "source_boxes": [
                None if fragment.box is None else list(fragment.box)
                for fragment in self.allocation.fragments
            ],
            "merged_source_sha256": hashlib.sha256(
                self.merge.text.encode("utf-8")
            ).hexdigest(),
            "joint_call_count": self.translator_call_count,
            "whole_target_sha256": hashlib.sha256(
                self.translated.encode("utf-8")
            ).hexdigest(),
            "ordered_fragments": [
                fragment.text for fragment in self.allocation.fragments
            ],
            "fragment_boxes": [
                None if fragment.box is None else list(fragment.box)
                for fragment in self.allocation.fragments
            ],
            "outcome": ChainResultState.JOINT_SUCCESS.value,
            "fallback_reason": None,
            "request_id": self.request_id,
            "translator_call_count": self.translator_call_count,
            "result_state": ChainResultState.JOINT_SUCCESS.value,
            "pair_class": self.pair_class,
            "strategy": self.strategy,
            "boundary_kinds": self.boundary_kinds,
            "capacity": [
                fragment.measurement_record for fragment in self.allocation.fragments
            ],
            "cut_displacement": [],
            "merged_source_chars": len(self.merge.text),
            "merged_translation_chars": len(self.translated),
            # Written out whole so that the conservation law can be stated over
            # the report and the document alone: the members of a chain join
            # back to exactly this string.
            "translation": self.translated,
            "merge": self.merge.as_record(),
            "allocation": self.allocation.as_record(),
            "redistribution": self.allocation.as_redistribution_record(),
            "members": [
                {
                    "debug_id": member.debug_id,
                    "source_ref": member.physical_source_ref,
                    "runtime_source_ref": member.source_ref,
                    "chain_index": member.chain_index,
                    "page_index": member.page_index,
                    "layout_label": getattr(member.paragraph, "layout_label", None),
                    "source_chars": len(member.source),
                    "segment": fragment.segment_record(),
                }
                for member, fragment in zip(
                    self.members, self.allocation.fragments, strict=True
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
        self._membership_frozen = False
        self._membership_released = False

    def __bool__(self) -> bool:
        return bool(self._records)

    def __len__(self) -> int:
        return len(self._records)

    @property
    def membership_frozen(self) -> bool:
        return self._membership_frozen

    @property
    def active_paragraph_ids(self) -> frozenset[int]:
        """Current admission set without recording a producer decline."""
        return frozenset(self._records)

    def freeze(self) -> None:
        """Close admission before any competing producer sees the claim."""
        if self._membership_frozen:
            raise ValueError("claim membership is already frozen")
        self._membership_frozen = True

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
        if self._membership_frozen:
            raise ValueError("claim membership is frozen")
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
        if not self._membership_frozen:
            raise ValueError("claim membership must be frozen before release")
        if self._membership_released:
            raise ValueError("claim membership was already released")
        records = list(self._records.values())
        self._records.clear()
        self._released.extend(records)
        self._membership_released = True

    def records(self) -> list[SkipRecord]:
        return [*self._released, *self._records.values()]


# The claim a document with the switch down leaves behind: it claims nothing,
# so every call site reads the same with the pass absent as with it present.
EMPTY_CLAIM = ChainClaim()
EMPTY_CLAIM.freeze()


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


def _placeholder_tokens(
    source: str, translate_input
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return all, hard-protected and inline-style tokens in source order."""
    occurrences: list[tuple[int, int, str]] = []
    protected_occurrences: list[tuple[int, int, str]] = []
    rich_text_occurrences: list[tuple[int, int, str]] = []
    for placeholder in getattr(translate_input, "placeholders", ()):
        if hasattr(placeholder, "placeholder") and hasattr(
            placeholder, "regex_pattern"
        ):
            patterns = (placeholder.regex_pattern,)
            destination = protected_occurrences
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
            destination = rich_text_occurrences
        else:
            raise ChainTranslationError("unsupported placeholder shape")
        for pattern in patterns:
            matches = list(re.finditer(pattern, source, flags=re.IGNORECASE))
            if len(matches) != 1:
                raise ChainTranslationError(
                    "each injected placeholder token must occur exactly once"
                )
            match = matches[0]
            occurrence = (match.start(), match.end(), match.group(0))
            occurrences.append(occurrence)
            destination.append(occurrence)
    for token, expected_count in getattr(
        translate_input, "original_placeholder_tokens", {}
    ).items():
        matches = list(re.finditer(re.escape(token), source))
        if len(matches) != expected_count:
            raise ChainTranslationError(
                "original placeholder token count changed during preparation"
            )
        held = [(match.start(), match.end(), match.group(0)) for match in matches]
        occurrences.extend(held)
        protected_occurrences.extend(held)
    occurrences.sort(key=lambda item: (item[0], item[1]))
    protected_occurrences.sort(key=lambda item: (item[0], item[1]))
    rich_text_occurrences.sort(key=lambda item: (item[0], item[1]))
    if any(
        left[1] > right[0]
        for left, right in zip(occurrences, occurrences[1:], strict=False)
    ):
        raise ChainTranslationError("placeholder tokens overlap")
    return (
        tuple(token for _start, _end, token in occurrences),
        tuple(token for _start, _end, token in protected_occurrences),
        tuple(token for _start, _end, token in rich_text_occurrences),
    )


def _tokens_in(text: str, expected: tuple[str, ...]) -> tuple[str, ...]:
    vocabulary = sorted(set(expected), key=lambda token: (-len(token), token))
    if not vocabulary:
        return ()
    pattern = "|".join(re.escape(token) for token in vocabulary)
    return tuple(match.group(0) for match in re.finditer(pattern, text))


def _token_ranges(text: str, expected: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    vocabulary = sorted(set(expected), key=lambda token: (-len(token), token))
    if not vocabulary:
        return ()
    pattern = "|".join(re.escape(token) for token in vocabulary)
    return tuple((match.start(), match.end()) for match in re.finditer(pattern, text))


def _slot_id(slot) -> str:
    material = {
        "article_id": slot.article_id,
        "page": slot.page,
        "column": slot.column,
        "slot_order": slot.slot_order,
        "box": list(slot.box),
    }
    return f"slot-{hash_record(material)}"


class ChainPlan:
    """Every chain of one document, measured and waiting to be written back."""

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
        self._typesetter = None
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
        self.claim.freeze()
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
            self.translator,
            docs,
            tracker,
            self.article_context,
            excluded_paragraph_ids=self.claim.active_paragraph_ids,
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
        if all(article is None for article in articles):
            # A wholly ungrouped ArticleIR has no ownership evidence to consult.
            # The detector has already frozen member order, so create canonical
            # source-element snapshots from each member's own source box.  A
            # partially grouped document still fails closed below.
            if not self.article_document_ir.by_element:
                elements = []
                for order, member in enumerate(members):
                    box = getattr(member.paragraph, "box", None)
                    if box is None:
                        return None, ESCALATION_ARTICLE, (
                            f"member {member.source_ref} has no source box"
                        )
                    source_box = tuple(
                        float(getattr(box, name))
                        for name in ("x", "y", "x2", "y2")
                    )
                    elements.append(
                        SourceElementRef(
                            source_ref=member.source_ref,
                            page=member.page_index + 1,
                            column=order,
                            reading_order=order,
                            role=getattr(
                                member.paragraph, "layout_label", None
                            )
                            or "unclassified",
                            source_box=source_box,
                            source_text_hash=hashlib.sha256(
                                (
                                    getattr(member.paragraph, "unicode", "") or ""
                                ).encode("utf-8")
                            ).hexdigest(),
                            style_hash=hash_record(
                                {
                                    "font_id": getattr(
                                        getattr(member.paragraph, "pdf_style", None),
                                        "font_id",
                                        None,
                                    ),
                                    "font_size": getattr(
                                        getattr(member.paragraph, "pdf_style", None),
                                        "font_size",
                                        None,
                                    ),
                                }
                            ),
                        )
                    )
                canonical_chain_id = f"chain-{hash_record(refs)}"
                article_id = f"article-unsupported-{hash_record(refs)}"
                return (
                    ChainPreflight(
                        canonical_chain_id,
                        article_id,
                        refs,
                        tuple(
                            MemberSourceSlot(
                                article_id=article_id,
                                page=element.page,
                                column=element.column,
                                slot_order=order,
                                box=element.source_box,
                            )
                            for order, element in enumerate(elements)
                        ),
                    ),
                    "",
                    "",
                )
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
        article_lookup = getattr(self.article_document_ir, "article", None)
        article = article_lookup(article_id) if article_lookup is not None else None
        if article is None:
            article = next(
                (
                    candidate
                    for candidate in getattr(self.article_document_ir, "articles", ())
                    if candidate.article_id == article_id
                ),
                None,
            )
        if article is None:
            return None, ESCALATION_ARTICLE, "canonical article object is unavailable"
        elements = {element.source_ref: element for element in article.elements}
        ordered_slots = []
        reading_orders = []
        for order, reference in enumerate(refs):
            element = elements.get(reference)
            if element is None:
                return None, ESCALATION_ARTICLE, (
                    f"member {reference} has no canonical article element"
                )
            if element.source_box is None:
                return None, ESCALATION_ARTICLE, (
                    f"member {reference} has no canonical source box"
                )
            reading_orders.append(element.reading_order)
            ordered_slots.append(
                MemberSourceSlot(
                    article_id=article_id,
                    page=element.page,
                    column=element.column,
                    slot_order=order,
                    box=tuple(float(value) for value in element.source_box),
                )
            )
        if reading_orders != sorted(reading_orders):
            return None, ESCALATION_TOPOLOGY, (
                f"chain members do not follow canonical reading order: "
                f"{reading_orders}"
            )
        return (
            ChainPreflight(
                canonical_chain_id,
                article_id,
                refs,
                tuple(ordered_slots),
            ),
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
        runtime_references = tuple(member.source_ref for member in members)
        physical_references = tuple(
            member.physical_source_ref for member in members
        )
        source_boxes = []
        source_texts = []
        for member in members:
            box = getattr(member.paragraph, "box", None)
            source_boxes.append(
                None
                if box is None
                else [
                    float(getattr(box, name))
                    for name in ("x", "y", "x2", "y2")
                ]
            )
            source_texts.append(getattr(member.paragraph, "unicode", "") or "")
        try:
            merged_source = backfill.merge_chain_text(source_texts, self.config).text
        except backfill.ChainBackfillError:
            merged_source = "".join(source_texts)
        record = {
            "chain_id": chain_id,
            "canonical_chain_id": stable_chain_id,
            "article_id": article_id,
            "ordered_source_refs": list(physical_references),
            "runtime_source_refs": list(runtime_references),
            "source_boxes": source_boxes,
            "merged_source_sha256": hashlib.sha256(
                merged_source.encode("utf-8")
            ).hexdigest(),
            "joint_call_count": translator_call_count,
            "whole_target_sha256": None,
            "ordered_fragments": [],
            "fragment_boxes": [],
            "request_id": request_id,
            "translator_call_count": translator_call_count,
            "result_state": state.value,
            "outcome": state.value,
            "fallback_reason": reason or None,
            "reason": reason,
            "detail": detail,
            "members": [
                {
                    "source_ref": member.physical_source_ref,
                    "runtime_source_ref": member.source_ref,
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
            logger.warning("chain %s released after %s: %s", chain_id, reason, detail)
            self.escalated.append(record)
        trace = getattr(self.translator, "run_trace", None)
        if trace is not None:
            trace.record_chain_outcome(
                stable_chain_id,
                runtime_references,
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
                (
                    placeholder_tokens,
                    protected_placeholder_tokens,
                    rich_text_placeholder_tokens,
                ) = _placeholder_tokens(text, translate_input)
            except (ChainTranslationError, re.error) as error:
                return (
                    [],
                    ESCALATION_PLACEHOLDER,
                    f"{member.source_ref}: {error}",
                )
            style = getattr(translate_input, "base_style", None) or getattr(
                paragraph, "pdf_style", None
            )
            active_fonts = xobj_font_map.get(
                getattr(paragraph, "xobj_id", None), page_font_map
            )
            source_font = (
                None
                if style is None
                else active_fonts.get(getattr(style, "font_id", None))
            )
            prepared.append(
                MemberPlan(
                    paragraph=paragraph,
                    page=member.page,
                    tracker=member_tracker,
                    translate_input=translate_input,
                    style=style,
                    source_font=source_font,
                    page_font_map=page_font_map,
                    xobj_font_map=xobj_font_map,
                    source=text,
                    page_index=member.page_index,
                    source_ref=member.source_ref,
                    physical_source_ref=member.physical_source_ref,
                    placeholder_tokens=placeholder_tokens,
                    protected_placeholder_tokens=protected_placeholder_tokens,
                    rich_text_placeholder_tokens=rich_text_placeholder_tokens,
                )
            )
        return prepared, "", ""

    def _plan_chain(
        self, chain_id: str, members: list[CollectedMember], tracker
    ) -> None:
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
        strategy = SLOT_CAPACITY_STRATEGY
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
        protected_tokens = tuple(
            token
            for member in prepared
            for token in member.protected_placeholder_tokens
        )
        rich_text_tokens = tuple(
            token
            for member in prepared
            for token in member.rich_text_placeholder_tokens
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
        translated_protected = _tokens_in(translated, protected_tokens)
        translated_rich_text = _tokens_in(translated, rich_text_tokens)
        rich_text_preserved = translated_rich_text == rich_text_tokens
        rich_text_dropped = not translated_rich_text
        if (
            translated_protected != protected_tokens
            or not (rich_text_preserved or rich_text_dropped)
        ):
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
        allocation_tokens = (
            expected_tokens if rich_text_preserved else protected_tokens
        )
        try:
            allocation = (
                self._allocate_target(
                    merge,
                    translated,
                    prepared,
                    preflight.ordered_slots,
                    allocation_tokens,
                )
                if preflight.ordered_slots
                else self._legacy_allocation(merge, translated, prepared, pair_class)
            )
        except (ChainTranslationError, ValueError) as error:
            detail = f"slot measurement failed: {error}"
            if request_id is not None:
                self.translator.run_trace.fail_request(request_id, detail)
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.FAILED_WITH_ISSUE,
                reason=ESCALATION_CONSERVATION,
                detail=detail,
                request_id=request_id,
                translator_call_count=translator_call_count,
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
            return
        if allocation is None:
            if request_id is not None:
                self.translator.run_trace.fail_request(request_id, ESCALATION_OVERFLOW)
            self._record_outcome(
                chain_id,
                members,
                ChainResultState.FAILED_WITH_ISSUE,
                reason=ESCALATION_OVERFLOW,
                detail=ESCALATION_OVERFLOW,
                request_id=request_id,
                translator_call_count=translator_call_count,
                canonical_chain_id=preflight.canonical_chain_id,
                article_id=preflight.article_id,
            )
            return

        if request_id is not None:
            try:
                for order, fragment in enumerate(allocation.fragments):
                    member = fragment.member
                    reference = self.translator.run_trace.source_ref_for(
                        member.paragraph
                    )
                    if reference is None:
                        raise ValueError("chain member has no frozen source ref")
                    self.translator.run_trace.allocate_target_fragment(
                        request_id,
                        reference,
                        order=order,
                        text_start=fragment.start,
                        text_end=fragment.end,
                        text=fragment.text,
                        slot_id=fragment.slot_id,
                        measurement_summary=fragment.measurement_record,
                        released=fragment.released,
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
            allocation=allocation,
            request_id=request_id,
            canonical_chain_id=preflight.canonical_chain_id,
            article_id=preflight.article_id,
            translator_call_count=translator_call_count,
        )
        # Admission is the commit point.  Everything above is preflight and
        # planning; a failure there leaves the members visible to the ordinary
        # and short-unit producers.
        self._claim_chain(chain_id, members)
        self.entries.append(entry)
        self.claim.set_result(
            [member.paragraph for member in members],
            ChainResultState.JOINT_SUCCESS,
        )
        self._record_outcome(
            chain_id,
            members,
            ChainResultState.JOINT_SUCCESS,
            request_id=request_id,
            translator_call_count=translator_call_count,
            canonical_chain_id=preflight.canonical_chain_id,
            article_id=preflight.article_id,
        )
        self.outcomes[-1].update(
            {
                "whole_target_sha256": hashlib.sha256(
                    translated.encode("utf-8")
                ).hexdigest(),
                "ordered_fragments": [
                    fragment.text for fragment in allocation.fragments
                ],
                "fragment_boxes": [
                    None if fragment.box is None else list(fragment.box)
                    for fragment in allocation.fragments
                ],
            }
        )

    def _slot_typesetter(self):
        if self._typesetter is None:
            from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting

            self._typesetter = Typesetting(
                self.translator.translation_config,
                font_mapper=getattr(self.translator.il_translator, "font_mapper", None),
            )
        return self._typesetter

    def _measurement_unit_factory(
        self,
        members: list[MemberPlan],
        member: MemberPlan,
        typesetter,
        measurement_scale: float,
    ):
        parser = getattr(self.translator.il_translator, "parse_translate_output", None)
        if parser is None:
            return None
        fonts = dict(member.page_font_map)
        fonts.update(getattr(typesetter.font_mapper, "fontid2font", {}))
        for xobj_id, held in member.xobj_font_map.items():
            fonts[xobj_id] = dict(held)
        translate_input = self._translate_input_for_members(members, member)

        def make_units(text: str):
            paragraph = copy.copy(member.paragraph)
            tracker = copy.deepcopy(member.tracker)
            paragraph.unicode = text
            paragraph.pdf_paragraph_composition = parser(
                translate_input,
                text,
                tracker,
                tracker.last_llm_translate_tracker(),
            )
            for composition in paragraph.pdf_paragraph_composition:
                same_style = composition.pdf_same_style_unicode_characters
                if same_style is not None and same_style.pdf_style is None:
                    same_style.pdf_style = member.style
            units = typesetter.create_typesetting_units(paragraph, fonts)
            if measurement_scale < 1.0:
                # These units were built from a copied paragraph and are used
                # only for capacity measurement.  Relocating them at the
                # configured readable scale gives the same proportional glyph
                # geometry final typesetting is allowed to use, without
                # mutating source IL or weakening the source-box gate.
                units = [
                    unit.relocate(0.0, 0.0, measurement_scale) for unit in units
                ]
            return units

        return make_units

    def _allocate_target(
        self,
        merge: backfill.ChainMerge,
        translated: str,
        members: list[MemberPlan],
        slots: tuple[object, ...],
        protected_tokens: tuple[str, ...],
    ) -> ChainAllocationPlan | None:
        """Allocate against each member's source box, never an article-wide box.

        First measure the capacity of every immutable source box, then let the
        language-aware splitter place all cuts together.  That global split is
        what reserves a legal, non-empty unit for every later body member.
        Finally every proposed fragment is measured in its own box; a single
        overflow invalidates the whole plan.
        """
        if len(members) != len(slots):
            return None
        protected = _token_ranges(translated, protected_tokens)
        typesetter = self._slot_typesetter()
        minimum_readable_scale = (
            line_split.load_line_split_config().minimum_readable_scale
        )

        def measurement_style(member):
            style = member.style
            source_size = getattr(style, "font_size", None)
            if source_size is None:
                return style, 1.0
            source_size = float(source_size)
            if source_size <= 0:
                return style, 1.0
            readable_scales = [
                scale
                for scale in _APPLICATION_SCALES
                if scale >= minimum_readable_scale
                and source_size * scale >= self.config.slot_min_font_size
            ]
            scale = min(readable_scales) if readable_scales else 1.0
            held = copy.copy(style)
            held.font_size = source_size * scale
            return held, scale

        def measure(text, member, slot, order, ranges=()):
            slot_box = Box(*slot.box)
            style, scale = measurement_style(member)
            return typesetter.fit_text_to_slot(
                text,
                style,
                self.language,
                slot_box,
                paragraph_start=(
                    order == 0
                    and bool(getattr(member.paragraph, "first_line_indent", False))
                ),
                original_font=member.source_font,
                protected_ranges=ranges,
                unit_factory=self._measurement_unit_factory(
                    members, member, typesetter, scale
                ),
                minimum_font_size=self.config.slot_min_font_size,
                fit_tolerance=self.config.slot_fit_tolerance,
                line_skip=(
                    self.config.capacity.line_skip_cjk
                    if self.config.capacity.is_cjk_target(self.language)
                    else self.config.capacity.line_skip_latin
                ),
                line_head_forbidden=self.config.line_head_forbidden,
                line_tail_forbidden=self.config.line_tail_forbidden,
            )

        capacities = []
        for order, (member, slot) in enumerate(zip(members, slots, strict=True)):
            result = measure(translated, member, slot, order, protected)
            if result.status == "invalid":
                raise ChainTranslationError(
                    f"slot {_slot_id(slot)} has no valid target style or box"
                )
            capacity = result.consumed_range[1]
            if capacity <= 0:
                return None
            capacities.append(capacity)

        try:
            split = backfill.redistribute(
                merge,
                translated,
                self.language,
                backfill.STRATEGY_CAPACITY,
                self.config,
                aligned_lengths=None,
                align_enabled=False,
                capacities=capacities,
            )
        except backfill.ChainBackfillError:
            return None

        # Protected placeholders are indivisible even where a legal language
        # boundary happens to occur inside one.
        cut_positions = [segment.end for segment in split.segments[:-1]]
        if any(start < cut < end for cut in cut_positions for start, end in protected):
            return None

        fragments = []
        for order, (member, slot, segment) in enumerate(
            zip(members, slots, split.segments, strict=True)
        ):
            local_ranges = tuple(
                (start - segment.start, end - segment.start)
                for start, end in protected
                if segment.start <= start and end <= segment.end
            )
            result = measure(segment.text, member, slot, order, local_ranges)
            if result.status == "invalid" or result.consumed_range[1] != len(
                segment.text
            ):
                return None
            measurement = result.to_record()
            measurement["whole_target_range"] = [segment.start, segment.end]
            style, scale = measurement_style(member)
            measurement["measurement_scale"] = scale
            measurement["measurement_font_size"] = getattr(
                style, "font_size", None
            )
            fragments.append(
                SlotAllocationFragment(
                    member=member,
                    slot_id=_slot_id(slot),
                    page=slot.page,
                    column=slot.column,
                    slot_order=slot.slot_order,
                    box=tuple(float(value) for value in slot.box),
                    text=segment.text,
                    start=segment.start,
                    end=segment.end,
                    released=False,
                    measurement_record=measurement,
                )
            )
        try:
            return ChainAllocationPlan(translated, tuple(fragments))
        except ValueError:
            return None

    def _legacy_allocation(
        self,
        merge: backfill.ChainMerge,
        translated: str,
        members: list[MemberPlan],
        pair_class: str | None,
    ) -> ChainAllocationPlan | None:
        """Keep callers without canonical slot objects readable but unmeasured."""
        redistribute = backfill.redistribute
        try:
            result = redistribute(
                merge,
                translated,
                self.language,
                backfill.strategy_for_pair_class(pair_class, self.config),
                self.config,
                aligned_lengths=None,
                align_enabled=self.align_enabled,
                capacities=None,
            )
        except backfill.ChainBackfillError:
            return None
        fragments = []
        for member, segment in zip(members, result.segments, strict=True):
            paragraph_box = getattr(member.paragraph, "box", None)
            box = (
                None
                if paragraph_box is None
                else tuple(
                    float(getattr(paragraph_box, name))
                    for name in ("x", "y", "x2", "y2")
                )
            )
            slot_identifier = f"slot-{hash_record({'source_ref': member.source_ref})}"
            fragments.append(
                SlotAllocationFragment(
                    member=member,
                    slot_id=slot_identifier,
                    page=member.page_index + 1,
                    column=member.chain_index or 0,
                    slot_order=member.chain_index or 0,
                    box=box,
                    text=segment.text,
                    start=segment.start,
                    end=segment.end,
                    released=False,
                    measurement_record={
                        "fit_status": "legacy_unmeasured",
                        "whole_target_range": [segment.start, segment.end],
                        "chars": len(segment.text),
                        "line_metrics": [],
                        "ink_bounds": None,
                    },
                )
            )
        return ChainAllocationPlan(translated, tuple(fragments))

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
            translated = canonical_text(translated)
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

    @staticmethod
    def _member_snapshot(member: MemberPlan) -> dict:
        paragraph = member.paragraph
        return {
            "box": copy.deepcopy(getattr(paragraph, "box", None)),
            "unicode": getattr(paragraph, "unicode", None),
            "pdf_paragraph_composition": copy.deepcopy(
                getattr(paragraph, "pdf_paragraph_composition", None)
            ),
            "segment_sentence_start": getattr(
                paragraph, "segment_sentence_start", None
            ),
            "segment_sentence_end": getattr(paragraph, "segment_sentence_end", None),
        }

    @staticmethod
    def _restore_member(member: MemberPlan, snapshot: dict) -> None:
        for name, value in snapshot.items():
            setattr(member.paragraph, name, copy.deepcopy(value))

    @staticmethod
    def _translate_input_for_members(
        members: list[MemberPlan], member: MemberPlan
    ):
        translate_input = copy.copy(member.translate_input)
        translate_input.placeholders = [
            placeholder
            for held in members
            for placeholder in getattr(held.translate_input, "placeholders", ())
        ]
        original_tokens = {}
        for held in members:
            for token, count in getattr(
                held.translate_input, "original_placeholder_tokens", {}
            ).items():
                original_tokens[token] = original_tokens.get(token, 0) + count
        translate_input.original_placeholder_tokens = original_tokens
        translate_input.base_style = member.style
        return translate_input

    def _record_writeback_failure(self, entry: ChainEntry, detail: str) -> None:
        self.claim.set_result(
            [member.paragraph for member in entry.members],
            ChainResultState.FAILED_WITH_ISSUE,
        )
        record = next(
            (
                outcome
                for outcome in self.outcomes
                if outcome["canonical_chain_id"] == entry.canonical_chain_id
            ),
            None,
        )
        if record is None:
            raise ValueError("writeback failure has no planned chain outcome")
        record["result_state"] = ChainResultState.FAILED_WITH_ISSUE.value
        record["reason"] = ESCALATION_CONSERVATION
        record["detail"] = detail
        self.escalated.append(record)
        if entry.request_id is not None:
            self.translator.run_trace.rollback_completed_chain(
                entry.canonical_chain_id,
                entry.request_id,
                detail,
            )

    def apply(self, pbar=None) -> None:
        """Commit each verified allocation atomically, then report.

        It runs after the per paragraph machinery so that nothing it writes can
        reach the context that machinery built. A failed write restores every
        paragraph in the chain before its trace request is failed.
        """
        translator = self.translator
        applied_entries = []
        for entry in self.entries:
            snapshots = [self._member_snapshot(member) for member in entry.members]
            try:
                for member, fragment in zip(
                    entry.members, entry.allocation.fragments, strict=True
                ):
                    translator.il_translator.post_translate_paragraph(
                        member.paragraph,
                        member.tracker,
                        self._translate_input_for_members(entry.members, member),
                        fragment.text,
                    )
                    if fragment.box is not None:
                        member.paragraph.box = Box(*fragment.box)
                    member.paragraph.segment_sentence_start = backfill.NO_SENTENCE_INDEX
                    member.paragraph.segment_sentence_end = backfill.NO_SENTENCE_INDEX
                joined = "".join(
                    getattr(member.paragraph, "unicode", "") or ""
                    for member in entry.members
                )
                if canonical_text(joined) != entry.translated:
                    raise ChainTranslationError(
                        "writeback fragments do not reconstruct the whole target"
                    )
            except Exception as error:
                for member, snapshot in zip(
                    entry.members, snapshots, strict=True
                ):
                    self._restore_member(member, snapshot)
                self._record_writeback_failure(
                    entry, f"writeback failed: {error}"
                )
                continue
            if entry.request_id is not None:
                for fragment in entry.allocation.fragments:
                    if fragment.released:
                        translator.run_trace.mark_source_protected(
                            fragment.member.source_ref, "released_target_slot"
                        )
            translator.total_count += len(entry.members)
            translator.ok_count += len(entry.members)
            if pbar:
                pbar.advance(len(entry.members))
            applied_entries.append(entry)
        self.entries = applied_entries
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
                "aligned_cuts": 0,
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
