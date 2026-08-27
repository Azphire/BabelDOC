"""The loop: detect, decide, act, lay out again, detect again.

The shape is the one the batch was planned around and every part of it is
bounded. Iterations stop at a declared ceiling. An iteration that does not
strictly reduce the number of *untreated* findings is undone and the loop ends,
so a repair that trades one defect for another cannot be mistaken for progress
and a loop that oscillates cannot run to the ceiling.

Untreated is the whole of the difference between this rule and a count of
findings. A repair can leave a finding standing and still have improved it: a
line half in the wrong script is measurably better than a line wholly in it,
and a detector reporting both says so in the evidence it carries. A finding
this run repaired into something its own detector measures as smaller is
treated -- it is not offered again, not acted on again, and not counted against
the loop again -- and one rewritten into the same defect is not, which is what
keeps the guard as strong as it was. A run whose every remaining finding has
been treated stops with that said rather than looping over work it has already
done. An iteration with no usable decision applies nothing.

An iteration asks for its decision one detector kind at a time. A round shows
the findings of a single kind and the actions that answer for that kind, and
nothing else; the model still chooses freely inside it, including to apply
nothing. What this buys is that a kind reported once is not a line among forty
lines of another kind, and what it costs is one request per kind that has both
findings standing and an action that answers for it. The order the rounds are
taken in is declared in ``configs/decision_rounds.json`` and nothing here
reasons about which kind a round is for. One iteration is every round taken
once, so the ceiling and the convergence guard below count what they counted
before: an iteration advances if its rounds together left fewer untreated
findings than they started with, and is undone whole if they did not.

Every iteration is written down -- what was found, what each round was asked,
what came back, what was rejected and why, what was written and what the
recheck then found -- because a loop whose reasoning is not on paper is one
nobody can audit after the fact.

Which mechanism carries out a decision is a table rather than a branch. Each
declared action has one row naming how many paragraphs a finding of its kind is
about, the rule that decides whether one finding is one it may act on, and the
method that carries it out. An action the configuration declares and the table
does not is refused: a vocabulary entry with no mechanism behind it must stop
the iteration, never be carried out by whichever mechanism happened to be
nearest.

Two conservation rules hold over the whole run and are checked rather than
trusted. The document keeps its pages and every page keeps its paragraphs. And
every paragraph outside the set this run wrote into is byte for byte what it
was, in the document's own serialisation: the check is a diff of per-paragraph
XML taken before the first iteration and after the last. A violation of either
restores the document as it stood before the loop and is reported; the repair
loop is not allowed to be the reason a translation changed somewhere nobody
looked.

The switch is ``magazine_repair`` and it is down by default. With it down this
module is not reached and detection behaves as it did before, one pass writing
one sidecar.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from pathlib import Path

from lxml import etree

from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import acceptance
from babeldoc.magazine import article_flow
from babeldoc.magazine import detectors
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import fixed_assets
from babeldoc.magazine import hitl
from babeldoc.magazine import rotated_lane
from babeldoc.magazine.checkpoint import to_checkpoint_xml
from babeldoc.magazine.detectors.base import CONFIG_PATH as DETECTOR_CONFIG_PATH
from babeldoc.magazine.detectors.base import box_tuple
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.legal_slots import slot_for_source_box
from babeldoc.magazine.react import actions
from babeldoc.magazine.react import chain_repair
from babeldoc.magazine.react import collision
from babeldoc.magazine.react import contain
from babeldoc.magazine.react import region_repair
from babeldoc.magazine.react import writeback
from babeldoc.magazine.react.config import CONFIG_PATH
from babeldoc.magazine.react.config import RepairConfigError
from babeldoc.magazine.react.config import load_repair_config
from babeldoc.magazine.react.decide import CachedDecisionClient
from babeldoc.magazine.react.decide import EngineTransport
from babeldoc.magazine.react.decide import engine_identity
from babeldoc.magazine.repair_contract import RepairAction
from babeldoc.magazine.repair_contract import RepairContractError
from babeldoc.magazine.repair_contract import RepairDecision
from babeldoc.magazine.repair_contract import build_repair_knowledge_state
from babeldoc.magazine.repair_detector_closure import CONFIG_PATH as CLOSURE_CONFIG_PATH
from babeldoc.magazine.repair_detector_closure import DetectorClosureRun
from babeldoc.magazine.repair_detector_closure import load_repair_detector_closure
from babeldoc.magazine.resource_paths import config_path
from babeldoc.magazine.taxonomy import record_config_manifest
from babeldoc.magazine.transaction import TransactionSnapshot

logger = logging.getLogger(__name__)

# The switch, by the name the caller sets on the translation config.
SWITCH = "magazine_repair"

REPORT_NAME = "react_repair.report.json"

# The rounds one iteration is made of, declared beside the other bounds rather
# than written here.
ROUNDS_CONFIG_PATH = config_path("decision_rounds.json")
KIND_ORDER_KEY = "kind_order"

# What carries the kind into the identity a round files its request under. Two
# rounds of one iteration ask different questions, so neither may be served the
# other's stored answer; the request narrowed under this batch is a different
# question again, and every entry filed under the old composition falls out of
# use of its own accord.
ROUND_KEY_PREFIX = "|kind="

# Why the loop stopped.
STOP_CEILING = "iteration_ceiling_reached"
STOP_NO_ISSUES = "nothing_left_to_repair"
STOP_NO_ENGINE = "no_translation_engine_configured"
STOP_NO_DECISION = "no_usable_decision"
STOP_NO_ACTION = "decision_applied_nothing"
STOP_NOTHING_APPLICABLE = "no_finding_the_action_may_act_on"
STOP_NO_MECHANISM = "the_chosen_action_has_no_mechanism_behind_it"
STOP_NOT_CONVERGING = "monotonic_acceptance_failed"
STOP_NOTHING_WRITTEN = "no_paragraph_was_written"
STOP_CONVERGED_WITH_RESIDUALS = "converged_with_residuals"
STOP_TRANSACTION_FAILED = "repair_action_or_detection_failed"

# How far a round got, least far first. An iteration that wrote nothing reports
# the furthest any of its rounds reached, because it is inert only where every
# one of them was, and the round that got closest to writing is the one whose
# reason says what stood in the way.
ROUND_PROGRESS = (
    STOP_NO_DECISION,
    STOP_NO_ACTION,
    STOP_NOTHING_APPLICABLE,
    STOP_NOTHING_WRITTEN,
)

# What an iteration did with itself.
OUTCOME_ADVANCED = "advanced"
OUTCOME_ROLLED_BACK = "rolled_back"
OUTCOME_INERT = "applied_nothing"

ACTION_ATTEMPTED = "attempted"
ACTION_NOT_EXECUTED = "not_executed"
ACTION_ROLLED_BACK = "rolled_back"
ACTION_COMMITTED = "committed"

# Conservation verdicts.
CONSERVED = "conserved"
VIOLATED = "violated"

def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


def load_kind_order(kinds, path: Path | str | None = None) -> tuple[str, ...]:
    """The order an iteration takes the detector kinds in, as configs declares it.

    Every kind a detector raises appears exactly once and nothing else appears
    at all. An order that omitted a kind would drop its findings out of every
    round in silence, and one naming a kind no detector raises would declare a
    round that never runs; both are faults in the file rather than surprises at
    run time.
    """
    source = ROUNDS_CONFIG_PATH if path is None else Path(path)
    with source.open(encoding="utf-8") as f:
        raw = json.load(f)
    declared = raw.get(KIND_ORDER_KEY)
    if not isinstance(declared, list) or not all(
        isinstance(item, str) for item in declared
    ):
        raise RepairConfigError(
            f"{source.name}: {KIND_ORDER_KEY} must be a list of kind names"
        )
    if len(set(declared)) != len(declared):
        raise RepairConfigError(f"{source.name}: {KIND_ORDER_KEY} names a kind twice")
    missing = sorted(set(kinds) - set(declared))
    unknown = sorted(set(declared) - set(kinds))
    if missing or unknown:
        raise RepairConfigError(
            f"{source.name}: {KIND_ORDER_KEY} omits {missing} and names {unknown}, "
            f"which no detector raises; raised are {sorted(kinds)}"
        )
    return tuple(declared)


def detector_kinds() -> tuple[str, ...]:
    return detectors.detector_kinds()


def round_vocabulary(config, kind: str):
    """The configuration one round is decided against: this kind's actions only.

    A round shows findings of one kind, so the vocabulary its reply is held to
    is the actions that answer for that kind. An action named from outside it is
    an answer to a question the round did not ask, and is refused as a violation
    rather than carried as far as the applicability rule that would refuse it on
    the kind anyway.
    """
    return replace(
        config,
        actions={
            name: action
            for name, action in config.actions.items()
            if action.answers_for(kind)
        },
    )


def round_plan(config, order, issues) -> list[tuple[str, list]]:
    """The rounds one iteration runs, in the declared order, with their findings.

    A kind with nothing standing has nothing to decide, and so has a kind no
    action answers for: neither is asked about, because a request whose only
    available answer is to apply nothing spends a request to learn what the
    configuration already says.
    """
    standing: dict[str, list] = {}
    for issue in issues:
        standing.setdefault(issue.kind, []).append(issue)
    plan: list[tuple[str, list]] = []
    for kind in order:
        offered = standing.get(kind)
        if not offered:
            continue
        if not any(action.answers_for(kind) for action in config.actions.values()):
            continue
        plan.append((kind, offered))
    return plan


@dataclass
class Snapshot:
    """What one iteration has to be able to put back."""

    paragraphs: dict[tuple[int, int], object] = field(default_factory=dict)
    curve_counts: dict[int, int] = field(default_factory=dict)
    form_counts: dict[int, int] = field(default_factory=dict)

    def take(self, page_position: int, page, paragraph_index: int) -> None:
        key = (page_position, paragraph_index)
        if key in self.paragraphs:
            return
        self.paragraphs[key] = copy.deepcopy(page.pdf_paragraph[paragraph_index])
        self.curve_counts.setdefault(page_position, len(page.pdf_curve or ()))
        self.form_counts.setdefault(page_position, len(page.pdf_form or ()))

    def restore(self, docs) -> None:
        for (page_position, paragraph_index), paragraph in self.paragraphs.items():
            docs.page[page_position].pdf_paragraph[paragraph_index] = paragraph
        for page_position, count in self.curve_counts.items():
            page = docs.page[page_position]
            if page.pdf_curve is not None and len(page.pdf_curve) > count:
                del page.pdf_curve[count:]
        for page_position, count in self.form_counts.items():
            page = docs.page[page_position]
            if page.pdf_form is not None and len(page.pdf_form) > count:
                del page.pdf_form[count:]


class RoundFailureError(RuntimeError):
    """An action failed after its auditable round record was opened."""

    def __init__(self, entry: dict, error: Exception):
        super().__init__(str(error))
        self.entry = entry
        self.error = error


def paragraph_digests(docs) -> dict[str, str]:
    """One digest per paragraph, of the bytes the document serialises it as.

    Taken from a single serialisation of the whole document and split by node,
    so what is compared is the intermediate language's own rendering of each
    paragraph rather than a projection of it chosen here.

    The checkpoint serialisation rather than the plain one, because a real
    document carries code points XML 1.0 does not admit -- which is why that
    serialisation escapes them -- and a parser handed the plain form refuses the
    whole document. The escaping is reversible and applied to both sides of the
    comparison, so what is compared is unaffected by it.
    """
    root = etree.fromstring(to_checkpoint_xml(docs).encode("utf-8"))
    labels = [label for label, _page in hitl.labeled_pages(docs)]
    nodes = root.findall("page")
    if len(labels) != len(nodes):
        raise ValueError("checkpoint pages lost their physical page identity")
    digests: dict[str, str] = {}
    for position, node in enumerate(nodes):
        label = labels[position]
        for index, paragraph_node in enumerate(node.findall("pdfParagraph")):
            digests[paragraph_reference(label, index)] = hashlib.sha256(
                etree.tostring(paragraph_node)
            ).hexdigest()
    return digests


def shape(docs) -> list[int]:
    """Pages, each carrying how many paragraphs it holds."""
    return [len(page.pdf_paragraph or ()) for page in docs.page]


def improved(before: dict, after: dict, fields) -> bool:
    """Whether one finding reports strictly less of the defect than it did.

    Every field the finding's kind declares as a measure of the defect has to be
    no higher than it was, and at least one strictly lower. A field either side
    cannot supply as a number leaves the comparison unanswerable, and
    unanswerable is not progress: a kind with nothing monotone to measure can be
    resolved but never improved.
    """
    strictly = False
    for name in fields:
        left = before.get(name)
        right = after.get(name)
        if isinstance(left, bool) or isinstance(right, bool):
            return False
        if not isinstance(left, int | float) or not isinstance(right, int | float):
            return False
        if right > left:
            return False
        if right < left:
            strictly = True
    return strictly


def counts_of(issues) -> dict:
    by_kind: dict[str, int] = {}
    for issue in issues:
        by_kind[issue.kind] = by_kind.get(issue.kind, 0) + 1
    return {"total": len(issues), "by_kind": by_kind}


def detect(
    translation_config,
    docs,
    config,
    iteration: int,
    source_geometry=None,
    *,
    article_document_ir=None,
    run_trace=None,
    fixed_inventory=None,
    current_inventory=None,
    legal_slot_plan=None,
):
    """One detection pass over the document as it currently stands.

    The working directory is deliberately not handed over: what a detector reads
    from it is the chain pass sidecar, which describes the run rather than this
    iteration, and surfacing it again on every pass would count one escalation
    once per iteration. The source layout is handed over instead, because it is
    about the document rather than about the run, and the loop loads it once.
    """
    context = detectors.build_context(
        docs,
        config,
        getattr(translation_config, "lang_out", None),
        None,
        translation_performed=not getattr(
            translation_config, "skip_translation", False
        ),
        iteration=iteration,
        source_geometry=source_geometry,
        article_document_ir=article_document_ir,
        run_trace=run_trace,
        fixed_inventory=fixed_inventory,
        current_inventory=current_inventory,
        legal_slot_plan=legal_slot_plan,
        finalized=True,
    )
    return detectors.run_detectors(context), context


@dataclass(frozen=True)
class Handler:
    """How one member of the action vocabulary is selected for and carried out.

    One row per declared action, and the row is the whole of the binding between
    the name a decision may say and the code that answers for it. An action with
    no row is an action the loop refuses to carry out rather than one it carries
    out with somebody else's mechanism.
    """

    paragraphs_per_finding: int | None
    resolve: object
    admits: object
    apply: object


@dataclass(frozen=True)
class PreparedRound:
    """A selected and deterministically preflighted action, before mutation."""

    entry: dict
    candidates: tuple
    action: object | None
    handler: Handler | None
    decision: RepairDecision | None


class RepairLoop:
    """One document, one run of the loop."""

    def __init__(
        self,
        translation_config,
        docs,
        decision_client=None,
        translator=None,
        run_trace=None,
        source_geometry=None,
        fixed_inventory=None,
        article_document_ir=None,
        article_state_journal=None,
        legal_slot_plan=None,
        manual_expectations=None,
    ):
        self.translation_config = translation_config
        self.docs = docs
        self.detector_config = detectors.detector_config()
        self.repair_config = load_repair_config(None, detector_kinds())
        self.detector_closure = load_repair_detector_closure()
        self.article_document_ir = article_document_ir
        self.legal_slot_plan = legal_slot_plan
        self.kind_order = load_kind_order(detector_kinds())
        self.working_dir = Path(
            translation_config.get_working_file_path(REPORT_NAME)
        ).parent
        self.engine = getattr(translation_config, "translator", None)
        self.language = getattr(translation_config, "lang_out", "") or ""
        self.identity = engine_identity(self.engine, self.language)
        self.ignore_cache = bool(getattr(translation_config, "ignore_cache", False))
        self.tool_call_request_limits = {
            "attempt_timeout_seconds": float(
                getattr(translation_config, "tool_call_timeout_seconds", 60.0)
            ),
            "max_attempts": int(
                getattr(translation_config, "max_tool_call_attempts", 1)
            ),
        }
        self.decision_client = decision_client
        self.translator = translator
        self.run_trace = run_trace
        self.protected_drop_cap_refs = drop_cap_intent.active_protected_refs(
            translation_config,
            rendered_only=True,
        )
        from babeldoc.magazine import column_reflow

        reflow_config = column_reflow.load_reflow_config()
        self.protected_paragraph_labels = reflow_config.protected_paragraph_labels
        self.fixed_inventory = (
            fixed_assets.build_inventory(
                docs,
                run_trace=run_trace,
                protected_paragraph_labels=self.protected_paragraph_labels,
            )
            if fixed_inventory is None
            else fixed_inventory
        )
        self.asset_bbox_tolerance_pt = reflow_config.asset_bbox_tolerance_pt
        self.trace_base_generation = None
        self.typesetting = None
        self.iterations: list[dict] = []
        self.handler_records: list[dict] = []
        self.article_state = article_state_journal
        self.manual_expectations = manual_expectations
        self.offered_texts: list[str] = []
        self.touched: set[str] = set()
        # Findings this run repaired into something the detectors still report,
        # by id. Run state and nothing else: the intermediate language is frozen
        # and carries no field for it, and a rerun starts with none of them.
        self.treated: dict[str, dict] = {}
        self.applications = 0
        # One row per call that reached the transport, in the order they were
        # made. The rows are written where the calls are made, so this is the
        # run's bill rather than an estimate of it.
        self.attributions: list[dict] = []
        # The document as it stood before the first iteration, taken once the
        # run begins and put back if the run cannot finish.
        self.baseline = None
        self.run_transaction = None
        self.failure = None
        # Where every paragraph stood before anything was translated, read from
        # the run's own checkpoint. Loaded once and handed to every pass: the
        # loop detects several times over one document and the file behind this
        # is the whole untranslated document.
        self.source_layout = (
            detectors.source_geometry_of(
                self.working_dir, self.detector_config, run_trace=run_trace
            )
            if source_geometry is None
            else source_geometry
        )

    def _latest_article_state(self):
        states = () if self.article_state is None else self.article_state.states
        if not states:
            raise RepairContractError("latest ArticleKnowledgeState is unavailable")
        return states[-1]

    def _repair_state(self, issues):
        limits = (
            ("max_actions", self.repair_config.max_iterations),
            ("max_candidate_issues", self.repair_config.max_issues_offered),
            ("max_decisions", self.repair_config.max_iterations),
            ("max_iterations", self.repair_config.max_iterations),
        )
        actions_allowed = {
            RepairAction.NO_ACTION,
            *(RepairAction(name) for name in self.repair_config.actions),
        }
        return build_repair_knowledge_state(
            self.docs,
            issues,
            article_document_ir=self.article_document_ir,
            article_state=self._latest_article_state(),
            legal_slot_plan=self.legal_slot_plan,
            fixed_asset_inventory=self.fixed_inventory,
            run_trace=self.run_trace,
            allowed_actions=actions_allowed,
            limits=limits,
            protected_refs=self.protected_drop_cap_refs,
        )

    def _detect(self, iteration: int):
        current_inventory = fixed_assets.build_inventory(
            self.docs,
            article_document_ir=self.article_document_ir,
            run_trace=self.run_trace,
            protected_paragraph_labels=self.protected_paragraph_labels,
        )
        return detect(
            self.translation_config,
            self.docs,
            self.detector_config,
            iteration,
            self.source_layout,
            article_document_ir=self.article_document_ir,
            run_trace=self.run_trace,
            fixed_inventory=self.fixed_inventory,
            current_inventory=current_inventory,
            legal_slot_plan=self.legal_slot_plan,
        )

    # -- clients ----------------------------------------------------------

    def _decision_client(self):
        if self.decision_client is None:
            self.decision_client = CachedDecisionClient(
                self.repair_config,
                transport=EngineTransport(self.engine),
                identity=self.identity,
                working_dir=self.working_dir,
                ignore_cache=self.ignore_cache,
                language=self.language,
                request_limits=self.tool_call_request_limits,
            )
        return self.decision_client

    def _round_client(self, kind: str) -> CachedDecisionClient:
        """The client of one round: this kind's vocabulary, this kind's cache key.

        Built from the run's own client rather than beside it, so a caller that
        supplied a transport or a cache is the one every round goes through. The
        kind enters the identity the request is filed under, which is what keeps
        two rounds of one iteration out of each other's stored answers.
        """
        base = self._decision_client()
        return CachedDecisionClient(
            round_vocabulary(base.config, kind),
            transport=base.transport,
            identity=f"{base.identity}{ROUND_KEY_PREFIX}{kind}",
            language=base.language,
            working_dir=base.working_dir,
            ignore_cache=base.ignore_cache,
            request_limits=base.request_limits,
        )

    def _translator(self):
        if self.translator is None:
            self.translator = actions.CachedOrphanTranslator(
                self.repair_config,
                transport=EngineTransport(self.engine),
                identity=self.identity,
                language=self.language,
                glossaries=self._glossaries(),
                working_dir=self.working_dir,
                ignore_cache=self.ignore_cache,
            )
        return self.translator

    def _glossaries(self):
        """The pairs binding this run, read where the translator reads them.

        The user list rather than the whole set: it is where a human ruling is
        put, and where the finalised automatic glossary is moved to when one is
        applied. What is read here is never written.
        """
        shared = getattr(
            self.translation_config, "shared_context_cross_split_part", None
        )
        return list(getattr(shared, "user_glossaries", None) or ())

    def _typesetting(self):
        if self.typesetting is None:
            if self.run_trace is None:
                self.typesetting = Typesetting(self.translation_config)
            else:
                self.typesetting = Typesetting(
                    self.translation_config, run_trace=self.run_trace
                )
        return self.typesetting

    def _handlers(self) -> dict[str, Handler]:
        """The mechanism behind each declared action, by the name it is named by.

        The whole binding between the vocabulary a decision may say and the code
        that answers for it, in one table. An action the configuration declares
        and this does not is refused rather than carried out by whichever
        mechanism happened to be nearest.
        """
        return {
            actions.NAME: Handler(
                paragraphs_per_finding=actions.PARAGRAPHS_PER_FINDING,
                resolve=lambda issue, pages, _context: actions.resolve(issue, pages),
                admits=actions.admits_candidate,
                apply=self._translate_orphans,
            ),
            chain_repair.NAME: Handler(
                paragraphs_per_finding=chain_repair.PARAGRAPHS_PER_FINDING,
                resolve=chain_repair.resolve_candidate,
                admits=chain_repair.admits,
                apply=self._reallocate_chain,
            ),
            region_repair.NAME: Handler(
                paragraphs_per_finding=region_repair.PARAGRAPHS_PER_FINDING,
                resolve=region_repair.resolve_candidate,
                admits=region_repair.admits,
                apply=self._retypeset_article_region,
            ),
            contain.NAME: Handler(
                paragraphs_per_finding=contain.PARAGRAPHS_PER_FINDING,
                resolve=lambda issue, pages, _context: actions.resolve(issue, pages),
                admits=contain.admits,
                apply=self._contain,
            ),
            collision.NAME: Handler(
                paragraphs_per_finding=collision.PARAGRAPHS_PER_FINDING,
                resolve=lambda issue, pages, _context: actions.resolve(issue, pages),
                admits=collision.admits,
                apply=self._resolve_collisions,
            ),
        }

    # -- one iteration ----------------------------------------------------

    def _candidates(self, issues, decision, action, context, handler):
        """The findings the decision named, resolved and filtered, in its order."""
        pages_by_label = {view.label: view for view in context.pages}
        by_id = {issue.id: issue for issue in issues}
        records: list[actions.Application] = []
        accepted: list[actions.Candidate] = []
        for issue_id in decision.issue_ids:
            issue = by_id.get(issue_id)
            if issue is None:
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference="",
                        accepted=False,
                        reason=actions.REASON_NO_PARAGRAPH,
                    )
                )
                continue
            if not action.answers_for(issue.kind):
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference=", ".join(issue.paragraph_refs),
                        accepted=False,
                        reason=actions.REASON_KIND,
                    )
                )
                continue
            if (
                handler.paragraphs_per_finding is not None
                and len(issue.paragraph_refs) != handler.paragraphs_per_finding
            ):
                # An action answers for findings of one shape: the orphan one
                # writes into a single paragraph, and a collision is a statement
                # about a pair. A finding of any other shape is a different
                # repair, and v1 does not have one.
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference=", ".join(issue.paragraph_refs),
                        accepted=False,
                        reason=actions.REASON_MANY,
                    )
                )
                continue
            candidate = handler.resolve(issue, pages_by_label, context)
            if candidate is None:
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference=", ".join(issue.paragraph_refs),
                        accepted=False,
                        reason=actions.REASON_NO_PARAGRAPH,
                    )
                )
                continue
            protected = sorted(
                set(issue.paragraph_refs) & self.protected_drop_cap_refs
            )
            if protected:
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference=", ".join(protected),
                        accepted=False,
                        reason=actions.REASON_PROTECTED_DROP_CAP,
                        source_text=candidate.source_text,
                        geometry={
                            "issue": {
                                "kind": drop_cap_intent.ISSUE_PROTECTED_CONFLICT,
                                "source_refs": protected,
                            }
                        },
                    )
                )
                continue
            protected_assets = sorted(
                set(issue.paragraph_refs)
                & self.fixed_inventory.protected_paragraph_refs
            )
            if protected_assets:
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference=", ".join(protected_assets),
                        accepted=False,
                        reason=actions.REASON_FIXED_ASSET,
                        source_text=candidate.source_text,
                    )
                )
                continue
            verdict = handler.admits(issue, candidate, action, context)
            if verdict != actions.ACCEPTED:
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference=candidate.reference,
                        accepted=False,
                        reason=verdict,
                        source_text=candidate.source_text,
                    )
                )
                continue
            if self.applications + len(accepted) >= action.max_applications:
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference=candidate.reference,
                        accepted=False,
                        reason=actions.REASON_CEILING,
                        source_text=candidate.source_text,
                    )
                )
                continue
            accepted.append(candidate)
        return accepted, records

    def _reallocate_chain(
        self, candidates, context, snapshot: Snapshot, _action, decision=None
    ):
        """Move existing chain fragments through the shared legal-slot fitter."""
        execution_parameters = (
            {} if decision is None else dict(decision.parameters)
        )
        positions = {
            view.label: position for position, view in enumerate(context.pages)
        }
        records = []
        for candidate in candidates:
            plan = chain_repair.plan(candidate, context, self._typesetting())
            for placement in plan.placements:
                snapshot.take(
                    positions[placement.page],
                    context.docs.page[positions[placement.page]],
                    placement.paragraph_index,
                )
            chain_repair.apply_plan(
                context.docs,
                self.run_trace,
                self.run_trace.current_generation,
                plan,
            )
            touched_refs = plan.touched_refs
            self.touched.update(touched_refs)
            self.applications += 1
            records.append(
                actions.Application(
                    issue_id=candidate.issue_id,
                    reference=touched_refs[0],
                    accepted=True,
                    reason=actions.ACCEPTED,
                    changed=True,
                    geometry={
                        "chain_id": plan.chain_id,
                        "article_id": plan.article_id,
                        "request_id": plan.request_id,
                        "whole_target_chars": len(plan.whole_target),
                        "execution_parameters": execution_parameters,
                        "touched_refs": list(touched_refs),
                        "placements": [
                            {
                                "source_ref": item.source_ref,
                                "page": item.page,
                                "slot_id": item.slot_id,
                                "box": list(item.box),
                                "text_range": [item.text_start, item.text_end],
                            }
                            for item in plan.placements
                        ],
                    },
                )
            )
        return records

    def _retypeset_article_region(
        self, candidates, context, _snapshot: Snapshot, _action, decision=None
    ):
        """Repack existing targets; the controller owns generation and rollback."""
        records = []
        for candidate in candidates:
            owner = region_repair.owner_for_issue(
                candidate.issue, self.article_document_ir
            )
            if owner is None:
                raise ValueError(region_repair.REASON_ARTICLE)
            result = article_flow.retypeset_existing_article_region(
                context.docs,
                self.article_document_ir,
                self.run_trace,
                self.fixed_inventory,
                self.legal_slot_plan,
                article_id=owner,
                page_number=candidate.issue.page,
                generation=self.run_trace.current_generation,
                typesetter=self._typesetting(),
                protected_refs=frozenset(self.protected_drop_cap_refs),
            )
            self.touched.update(result.touched_refs)
            self.applications += 1
            records.append(
                actions.Application(
                    issue_id=candidate.issue_id,
                    reference=result.touched_refs[0],
                    accepted=True,
                    reason=actions.ACCEPTED,
                    changed=True,
                    geometry={
                        **result.to_record(),
                        "execution_parameters": (
                            {} if decision is None else dict(decision.parameters)
                        ),
                    },
                )
            )
        return records

    def _contain(
        self, candidates, context, snapshot: Snapshot, action, decision=None
    ):
        """Put each admitted paragraph back inside its page. What happened.

        Where inside is the action's own declared margin, read from the
        vocabulary rather than taken from the finding: what a repair is measured
        against has to be the declaration and not a number that travelled
        through a request.

        The guard's bound is the detector's instead, taken from the bounds this
        pass is already running with: what the guard refuses to create is an
        overlap of the size the collision detector calls an overlap, so the two
        have to be reading one number.
        """
        positions = {
            view.label: position for position, view in enumerate(context.pages)
        }
        records: list[actions.Application] = []
        for candidate in candidates:
            position = positions[candidate.page_index]
            snapshot.take(position, candidate.page, candidate.paragraph_index)
            outcome = contain.apply_one(
                candidate, action, context.config.collision_min_iou
            )
            outcome.geometry["execution_parameters"] = (
                {} if decision is None else dict(decision.parameters)
            )
            if not outcome.changed:
                candidate.page.pdf_paragraph[candidate.paragraph_index] = (
                    snapshot.paragraphs.pop((position, candidate.paragraph_index))
                )
                records.append(outcome)
                continue
            self.touched.add(candidate.reference)
            self.applications += 1
            records.append(outcome)
        return records

    def _resolve_collisions(
        self, candidates, context, snapshot: Snapshot, action, decision=None
    ):
        """Slide the smaller member of each admitted pair clear. What happened.

        The paragraph put under snapshot is the one the plan would move, which
        is not always the one the finding was resolved to: a finding names a
        pair, and which of the two is the smaller is the plan's answer rather
        than the finding's order. Taking the snapshot from the plan is what
        keeps the restoration and the write about the same paragraph.
        """
        positions = {
            view.label: position for position, view in enumerate(context.pages)
        }
        records: list[actions.Application] = []
        for candidate in candidates:
            position = positions[candidate.page_index]
            outcome, found = collision.separate(candidate, action, context.config)
            outcome.geometry["execution_parameters"] = (
                {} if decision is None else dict(decision.parameters)
            )
            if found is None:
                records.append(outcome)
                continue
            snapshot.take(position, candidate.page, found.mover_index)
            collision.move(candidate.page.pdf_paragraph[found.mover_index], found)
            outcome = collision.finish(candidate, outcome, found, context.config)
            if not outcome.changed:
                candidate.page.pdf_paragraph[found.mover_index] = (
                    snapshot.paragraphs.pop((position, found.mover_index))
                )
                records.append(outcome)
                continue
            self.touched.add(outcome.reference)
            self.applications += 1
            records.append(outcome)
        return records

    def _translate_orphans(
        self, candidates, context, snapshot: Snapshot, action, decision
    ):
        """Translate and write each admitted candidate. Returns what happened."""
        pages_by_label = {view.label: view for view in context.pages}
        positions = {view.label: position for position, view in enumerate(context.pages)}
        translator = self._translator()
        typesetting = self._typesetting()
        records: list[actions.Application] = []
        max_source_chars = int(dict(decision.parameters)["max_source_chars"])
        for candidate in candidates:
            if len(candidate.source_text) > max_source_chars:
                records.append(
                    actions.Application(
                        issue_id=candidate.issue_id,
                        reference=candidate.reference,
                        accepted=False,
                        reason=actions.REASON_LIMIT,
                        source_text=candidate.source_text,
                        geometry={
                            "execution_parameters": dict(decision.parameters)
                        },
                    )
                )
                continue
            view = pages_by_label[candidate.page_index]
            context_text = actions.page_context(
                view, candidate.paragraph_index, self.repair_config.page_context_chars
            )
            outcome = translator.translate(candidate.source_text, context_text)
            outcome.geometry["execution_parameters"] = dict(decision.parameters)
            for row in outcome.calls:
                self.attributions.append({**row, "kind": actions.NAME})
            outcome.issue_id = candidate.issue_id
            outcome.reference = candidate.reference
            self.offered_texts.append(candidate.source_text)
            if not outcome.accepted:
                records.append(outcome)
                continue
            if outcome.translated_text == candidate.source_text:
                outcome.accepted = False
                outcome.reason = actions.REASON_UNCHANGED
                records.append(outcome)
                continue
            missing_manual_terms = [
                target
                for source, target in outcome.glossary_entries
                if source in candidate.source_text
                and target not in outcome.translated_text
            ]
            if missing_manual_terms:
                outcome.accepted = False
                outcome.reason = actions.REASON_MANUAL_TERM
                records.append(outcome)
                continue
            position = positions[candidate.page_index]
            snapshot.take(position, candidate.page, candidate.paragraph_index)
            box_before = box_tuple(candidate.paragraph.box)
            writeback.rebuild(candidate.paragraph, outcome.translated_text)
            laid_out = writeback.retypeset(
                typesetting, candidate.paragraph, candidate.page
            )
            rotated_lane.note_reference(candidate.reference)
            stayed = writeback.stayed_inside(
                box_before, box_tuple(candidate.paragraph.box)
            )
            if not laid_out or not stayed:
                # An empty composition would erase the line rather than repair
                # it, and one that needed more room than the paragraph had has
                # rearranged the page rather than repaired it. Either way this
                # one paragraph goes back and the rest continue.
                candidate.page.pdf_paragraph[candidate.paragraph_index] = (
                    snapshot.paragraphs.pop((position, candidate.paragraph_index))
                )
                outcome.accepted = False
                outcome.reason = (
                    actions.REASON_LAYOUT if not laid_out else actions.REASON_GEOMETRY
                )
                records.append(outcome)
                continue
            owner = self.article_document_ir.by_element[candidate.reference]
            article = self.article_document_ir.article(owner)
            element = next(
                item
                for item in article.elements
                if item.source_ref == candidate.reference
            )
            slot = slot_for_source_box(
                self.legal_slot_plan,
                article_id=owner,
                page=element.page,
                column=element.column,
                source_box=element.source_box,
            )
            if slot is None or self.run_trace is None:
                raise RepairContractError(actions.REASON_SLOT)
            generation = self.run_trace.current_generation
            request_id = self.run_trace.open_request(
                "repair_omitted_text",
                (candidate.reference,),
                candidate.source_text,
                {
                    "action": actions.NAME,
                    "article_id": owner,
                    "legal_slot_id": slot.slot_id,
                    "language": self.language,
                    "glossary_entries": outcome.glossary_entries,
                },
            )
            for _call in outcome.calls:
                self.run_trace.record_translator_call(request_id)
            self.run_trace.register_whole_target(
                request_id, outcome.translated_text
            )
            self.run_trace.allocate_target_fragment(
                request_id,
                candidate.reference,
                order=0,
                text_start=0,
                text_end=len(outcome.translated_text),
                text=outcome.translated_text,
                generation=generation,
                slot_id=slot.slot_id,
                render_ref=candidate.reference,
                render_page=element.page,
                measurement_summary={
                    "action": actions.NAME,
                    "box_before": list(box_before) if box_before else None,
                    "box_after": list(box_tuple(candidate.paragraph.box) or ()),
                },
            )
            self.run_trace.complete_request(request_id)
            outcome.geometry.update(
                {
                    "article_id": owner,
                    "legal_slot_id": slot.slot_id,
                    "request_id": request_id,
                    "touched_refs": [candidate.reference],
                }
            )
            outcome.changed = True
            self.touched.add(candidate.reference)
            self.applications += 1
            records.append(outcome)
        return records

    def _untreated(self, issues) -> list:
        """The findings this run has not already repaired into something better.

        A finding the loop treated is not offered again, not acted on again and
        not counted again: it stands in the report with what it still measures,
        and the loop's business is what it has not yet reached.
        """
        return [issue for issue in issues if issue.id not in self.treated]

    def _newly_treated(self, written, issues, rechecked, iteration: int) -> dict:
        """The findings this iteration repaired into something smaller.

        A finding the recheck no longer reports was resolved and is not one of
        these; a finding still reported with less of the defect in it was
        treated. Which evidence says so is the detector's declaration, read from
        the configuration rather than named here.
        """
        before = {issue.id: issue for issue in issues}
        after = {issue.id: issue for issue in rechecked}
        treated: dict[str, dict] = {}
        for item in written:
            was = before.get(item.issue_id)
            still = after.get(item.issue_id)
            if was is None or still is None:
                continue
            fields = self.detector_config.progress_fields(still.kind)
            if not improved(was.evidence, still.evidence, fields):
                continue
            treated[item.issue_id] = {
                "issue_id": item.issue_id,
                "paragraph_ref": item.reference,
                "kind": still.kind,
                "treated_at_iteration": iteration,
                "measured": list(fields),
                "before": {name: was.evidence.get(name) for name in fields},
                "residual": {name: still.evidence.get(name) for name in fields},
            }
        return treated

    def _prepare_round(
        self, kind: str, offered, context, repair_state
    ) -> PreparedRound:
        """Choose and preflight exactly one action without opening a generation.

        The round carries its own reason for having written nothing, so an
        iteration that wrote nothing anywhere can say which of its rounds got
        closest and what stopped it. A vocabulary entry with no mechanism behind
        it stops the whole iteration and says so here, because carrying it out
        with whichever mechanism happened to be nearest is the one thing the
        table exists to prevent.
        """
        entry: dict = {
            "kind": kind,
            "offered": len(offered),
            "offered_ids": [issue.id for issue in offered],
            "vocabulary": sorted(round_vocabulary(self.repair_config, kind).actions),
            "applicability": [],
            "executed": [],
            "written": [],
            "attempted": False,
            "action_status": ACTION_NOT_EXECUTED,
            "protected_skips": [],
            "repair_state_sha256": repair_state.sha256(),
        }
        decision, request = self._round_client(kind).decide(
            offered, repair_state=repair_state
        )
        entry["decision"] = {
            **({} if decision is None else decision.to_record()),
            "logical_calls": request.logical_calls,
            "provider_attempts": request.provider_attempts,
            "cache_hits": request.cache_hits,
            "violations": list(request.violations),
            "action_status": ACTION_NOT_EXECUTED,
        }
        entry["request"] = {
            "prompt_sha256": request.prompt_digest,
            "cache_key": request.key,
            "calls": [dict(row) for row in request.calls],
        }
        for row in request.calls:
            self.attributions.append({**row, "kind": kind})
        if decision is None:
            entry["reason"] = STOP_NO_DECISION
            return PreparedRound(entry, (), None, None, None)
        if decision.action is RepairAction.NO_ACTION:
            entry["reason"] = STOP_NO_ACTION
            return PreparedRound(entry, (), None, None, None)

        action = self.repair_config.action(decision.action.value)
        handler = self._handlers().get(decision.action.value)
        if handler is None:
            logger.error(
                "react: the vocabulary declares %r but nothing here carries it "
                "out; no paragraph was touched",
                decision.action.value,
            )
            entry["reason"] = STOP_NO_MECHANISM
            return PreparedRound(entry, (), action, None, None)

        candidates, rejected = self._candidates(
            offered, decision, action, context, handler
        )
        entry["applicability"] = [item.as_record() for item in rejected]
        entry["protected_skips"] = [
            item.reference
            for item in rejected
            if item.reason == actions.REASON_PROTECTED_DROP_CAP
        ]
        repair_state.preflight(decision, self.detector_closure)
        entry["canonical_decision"] = decision.to_record()
        entry["reason"] = "" if candidates else STOP_NOTHING_APPLICABLE
        return PreparedRound(
            entry, tuple(candidates), action, handler, decision
        )

    def _execute_round(
        self,
        prepared: PreparedRound,
        context,
        snapshot: Snapshot,
    ) -> tuple[dict, list]:
        """Execute the one preflighted handler inside the caller's generation."""
        entry = prepared.entry
        if not prepared.candidates or prepared.handler is None:
            return entry, []
        entry["attempted"] = True
        entry["action_status"] = ACTION_ATTEMPTED
        entry["decision"]["action_status"] = ACTION_ATTEMPTED
        try:
            applied = prepared.handler.apply(
                list(prepared.candidates),
                context,
                snapshot,
                prepared.action,
                prepared.decision,
            )
        except Exception as error:  # noqa: BLE001 - preserve the round record
            entry["failure"] = f"{type(error).__name__}: {error}"
            raise RoundFailureError(entry, error) from error
        written = [item for item in applied if item.changed]
        entry["executed"] = [
            {**item.as_record(), "action_status": ACTION_ATTEMPTED}
            for item in applied
        ]
        entry["written"] = [item.reference for item in written]
        entry["reason"] = "" if written else STOP_NOTHING_WRITTEN
        return entry, written

    @staticmethod
    def _finish_rounds(rounds, status: str) -> None:
        for entry in rounds:
            if not entry.get("attempted"):
                continue
            if entry.get("written") or entry.get("failure"):
                entry["action_status"] = status
                entry["decision"]["action_status"] = status
            for application in entry.get("executed", ()):
                if application.get("changed"):
                    application["action_status"] = status

    def _iterate(self, iteration: int, issues, context) -> tuple[str, str, list]:
        """Choose, execute, and immediately recheck exactly one action."""
        working = self._untreated(issues)
        record: dict = {
            "iteration": iteration,
            "detected": counts_of(issues),
            "detected_ids": [issue.id for issue in issues],
            "untreated": counts_of(working),
            "action_status": ACTION_NOT_EXECUTED,
        }
        self.iterations.append(record)

        if self.engine is None:
            record["outcome"] = OUTCOME_INERT
            record["decision"] = None
            record["rounds"] = []
            record["transaction"] = {"status": ACTION_NOT_EXECUTED, "pages": []}
            return OUTCOME_INERT, STOP_NO_ENGINE, issues

        repair_state = self._repair_state(issues)
        record["repair_state_sha256"] = repair_state.sha256()
        record["repair_state_schema_version"] = repair_state.schema_version

        def inventory_builder():
            return fixed_assets.build_inventory(
                self.docs,
                run_trace=self.run_trace,
                protected_paragraph_labels=self.protected_paragraph_labels,
            )

        transaction = TransactionSnapshot.capture(
            self.docs,
            run_trace=self.run_trace,
            fixed_inventory=self.fixed_inventory,
            fixed_inventory_builder=inventory_builder,
            article_state=self.article_state,
            manual_expectations=self.manual_expectations,
            repair_records=self.handler_records,
            repair_knowledge_state=repair_state,
        )
        action_snapshot = Snapshot()
        rounds: list[dict] = []
        written: list = []
        touched_before = set(self.touched)
        applications_before = self.applications
        treated_before = dict(self.treated)

        def summarise_rounds() -> None:
            record["rounds"] = rounds
            record["applicability"] = [
                item for entry in rounds for item in entry.get("applicability", ())
            ]
            record["executed"] = [
                item for entry in rounds for item in entry.get("executed", ())
            ]
            leading = next(
                (entry for entry in rounds if not entry.get("reason")),
                rounds[0] if rounds else None,
            )
            record["decision"] = None if leading is None else leading.get("decision")
            record["request"] = None if leading is None else leading.get("request")

        try:
            plan = round_plan(self.repair_config, self.kind_order, working)
            if plan:
                kind, offered = plan[0]
                prepared = self._prepare_round(
                    kind, offered, context, repair_state
                )
                rounds.append(prepared.entry)
                if prepared.candidates and prepared.handler is not None:
                    transaction.begin_generation(f"react_iteration_{iteration}")
                    try:
                        entry, applied = self._execute_round(
                            prepared, context, action_snapshot
                        )
                    except RoundFailureError as failure:
                        rounds[0] = failure.entry
                        raise failure.error from failure
                else:
                    entry, applied = prepared.entry, []
                rounds[0] = entry
                written.extend(applied)
            summarise_rounds()

            if not written:
                record["outcome"] = OUTCOME_INERT
                record["action_status"] = (
                    ACTION_ATTEMPTED
                    if any(entry.get("attempted") for entry in rounds)
                    else ACTION_NOT_EXECUTED
                )
                record["transaction"] = transaction.not_executed()
                reasons = [entry["reason"] for entry in rounds if entry["reason"]]
                if STOP_NO_MECHANISM in reasons:
                    return OUTCOME_INERT, STOP_NO_MECHANISM, issues
                return (
                    OUTCOME_INERT,
                    max(reasons, key=ROUND_PROGRESS.index)
                    if reasons
                    else STOP_NOTHING_APPLICABLE,
                    issues,
                )

            rechecked, new_context = self._detect(iteration)
            asset_comparison = fixed_assets.compare(
                self.fixed_inventory,
                inventory_builder(),
                self.asset_bbox_tolerance_pt,
            )
            policy = acceptance.load_acceptance_policy()
            compared_after = list(rechecked)
            if not asset_comparison.holds:
                compared_after.append(
                    acceptance.measured_issue(
                        f"fixed_asset_guard:iteration:{iteration}",
                        "fixed_asset_drift",
                        policy.severity_order[-1],
                        {"drift_count": 1},
                        ("drift_count",),
                        schema_version=policy.schema_version,
                    )
                )
            decision = prepared.decision
            if decision is None:
                raise RepairContractError("executed round lacks canonical decision")
            canonical_action = decision.action
            closure_run = DetectorClosureRun(
                action=canonical_action,
                registry_version=self.detector_closure.schema_version,
                ran_detectors=self.detector_closure.complete_detector_suite,
                conservation_invariants_passed=asset_comparison.holds,
            )
            closure_run.require_complete(self.detector_closure)
            target_issue_ids = decision.issue_ids
            touched_refs = {
                reference
                for item in written
                for reference in item.geometry.get(
                    "touched_refs", (item.reference,)
                )
            }
            touched_scope_valid = {
                item.issue_id for item in written
            }.issubset(target_issue_ids) and all(
                (
                    self.article_document_ir.by_element.get(reference)
                    in decision.target.article_refs
                    or (
                        reference.startswith("p")
                        and "#" in reference
                        and self.article_document_ir.by_page.get(
                            int(reference[1:].split("#", 1)[0])
                        )
                        in decision.target.article_refs
                    )
                )
                for reference in touched_refs
            )
            monotonic = acceptance.compare_repair_action(
                issues,
                compared_after,
                policy,
                action=canonical_action,
                target_issue_ids=target_issue_ids,
                closure_complete=True,
                conservation_holds=asset_comparison.holds,
                touched_scope_valid=touched_scope_valid,
            )
            before_ids = {issue.id for issue in issues}
            after_ids = {issue.id for issue in rechecked}
            newly = self._newly_treated(written, issues, rechecked, iteration)
            untreated = [
                issue
                for issue in rechecked
                if issue.id not in (set(self.treated) | set(newly))
            ]
            record["recheck"] = counts_of(rechecked)
            record["untreated_after"] = counts_of(untreated)
            record["resolved_ids"] = sorted(before_ids - after_ids)
            record["new_ids"] = sorted(after_ids - before_ids)
            record["treated_ids"] = sorted(newly)
            record["acceptance"] = monotonic.as_record()
            record["fixed_asset_comparison"] = asset_comparison.to_record()

            if not monotonic.accepted:
                self.touched.clear()
                self.touched.update(touched_before)
                self.applications = applications_before
                self.treated = treated_before
                self._finish_rounds(rounds, ACTION_ROLLED_BACK)
                summarise_rounds()
                record["outcome"] = OUTCOME_ROLLED_BACK
                record["action_status"] = ACTION_ROLLED_BACK
                record["rolled_back_refs"] = [item.reference for item in written]
                record["treated_ids"] = []
                record["transaction"] = transaction.rollback()
                logger.warning(
                    "react: iteration %d failed monotonic acceptance (%s); "
                    "rolled back and stopped",
                    iteration,
                    ", ".join(monotonic.reasons),
                )
                return OUTCOME_ROLLED_BACK, STOP_NOT_CONVERGING, issues

            self.treated.update(newly)
            next_article_state = self.article_state.capture_repair_checkpoint()
            self.handler_records.append(
                {
                    "action": canonical_action.value,
                    "before_repair_state_sha256": repair_state.sha256(),
                    "article_state_sha256": next_article_state.state_sha256,
                    "run_trace_generation": self.run_trace.current_generation,
                    "target_issue_ids": list(target_issue_ids),
                    "acceptance": monotonic.as_record(),
                }
            )
            transaction_record = transaction.commit(
                item.reference for item in written
            )
            self._finish_rounds(rounds, ACTION_COMMITTED)
            summarise_rounds()
            record["transaction"] = transaction_record
            record["action_status"] = ACTION_COMMITTED
            record["outcome"] = OUTCOME_ADVANCED
            return OUTCOME_ADVANCED, "", (rechecked, new_context)
        except Exception as error:  # noqa: BLE001 - a partial action must restore
            rolled_back_refs = sorted(set(self.touched) - touched_before)
            self.touched.clear()
            self.touched.update(touched_before)
            self.applications = applications_before
            self.treated = treated_before
            self._finish_rounds(rounds, ACTION_ROLLED_BACK)
            summarise_rounds()
            record["outcome"] = OUTCOME_ROLLED_BACK
            record["action_status"] = (
                ACTION_ROLLED_BACK
                if any(entry.get("attempted") for entry in rounds)
                else ACTION_NOT_EXECUTED
            )
            record["rolled_back_refs"] = rolled_back_refs
            record["failure"] = {
                "type": type(error).__name__,
                "detail": str(error),
            }
            record["transaction"] = transaction.rollback()
            self.failure = record["failure"]
            logger.exception(
                "react: iteration %d failed; the complete touched set was restored",
                iteration,
            )
            return OUTCOME_ROLLED_BACK, STOP_TRANSACTION_FAILED, issues

    # -- the run ----------------------------------------------------------

    def _standing(self, issues) -> str:
        """Why the loop would stop if it stopped here, given what still stands.

        Nothing reported at all is a document with nothing left to repair.
        Everything reported already repaired into something smaller is a
        different ending and is named as one: the loop converged, and what it
        leaves behind is residue it improved rather than defects it missed.
        """
        if not issues:
            return STOP_NO_ISSUES
        if not self._untreated(issues):
            return STOP_CONVERGED_WITH_RESIDUALS
        return STOP_CEILING

    def run(self):
        if self.run_trace is not None:
            self.trace_base_generation = self.run_trace.current_generation
        before_digests = paragraph_digests(self.docs)
        before_shape = shape(self.docs)
        before_document = copy.deepcopy(self.docs)
        self.baseline = before_document
        self.run_transaction = TransactionSnapshot.capture(
            self.docs,
            run_trace=self.run_trace,
            fixed_inventory=self.fixed_inventory,
            fixed_inventory_builder=lambda: fixed_assets.build_inventory(
                self.docs,
                run_trace=self.run_trace,
                protected_paragraph_labels=self.protected_paragraph_labels,
            ),
            article_state=self.article_state,
            manual_expectations=self.manual_expectations,
            repair_records=self.handler_records,
        )

        issues, context = self._detect(0)
        stop = self._standing(issues)
        iteration = 0
        while self._untreated(issues) and iteration < self.repair_config.max_iterations:
            iteration += 1
            outcome, reason, result = self._iterate(iteration, issues, context)
            if outcome != OUTCOME_ADVANCED:
                stop = reason
                break
            issues, context = result
            stop = self._standing(issues)

        after_shape = shape(self.docs)
        after_digests = paragraph_digests(self.docs)
        asset_comparison = fixed_assets.compare(
            self.fixed_inventory,
            fixed_assets.build_inventory(
                self.docs,
                run_trace=self.run_trace,
                protected_paragraph_labels=self.protected_paragraph_labels,
            ),
            self.asset_bbox_tolerance_pt,
        )
        changed = sorted(
            reference
            for reference, digest in after_digests.items()
            if before_digests.get(reference) != digest
        )
        outside = sorted(set(changed) - self.touched)
        conservation = {
            "verdict": CONSERVED,
            "pages_before": len(before_shape),
            "pages_after": len(after_shape),
            "paragraphs_before": sum(before_shape),
            "paragraphs_after": sum(after_shape),
            "touched_refs": sorted(self.touched),
            "changed_refs": changed,
            "changed_outside_touched": outside,
            "fixed_assets": asset_comparison.to_record(),
        }
        if before_shape != after_shape or outside or not asset_comparison.holds:
            conservation["verdict"] = VIOLATED
            logger.error(
                "react: conservation violated (shape %s -> %s, %d paragraph(s) "
                "changed outside the repaired set, fixed assets conserved=%s); "
                "the document is restored to "
                "what it was before the loop",
                before_shape,
                after_shape,
                len(outside),
                asset_comparison.holds,
            )
            conservation["rollback"] = self.run_transaction.rollback()
            self.touched.clear()
            self.treated.clear()
            stop = f"{VIOLATED}: conservation"
            issues, context = self._detect(0)

        self._write(issues, context, conservation, stop, iteration)
        hitl.after_repair(self.translation_config, self.offered_texts)
        return issues

    def _treated_record(self, issues) -> list[dict]:
        """What the run repaired, and what each repaired finding still reports.

        The residual is refreshed from the findings standing at the end rather
        than left at what it was when the repair was made, so the report says
        what the produced document carries.
        """
        standing = {issue.id: issue for issue in issues}
        rows: list[dict] = []
        for issue_id, entry in sorted(self.treated.items()):
            row = dict(entry)
            final = standing.get(issue_id)
            row["still_reported"] = final is not None
            if final is not None:
                row["residual"] = {
                    name: final.evidence.get(name) for name in entry["measured"]
                }
            rows.append(row)
        return rows

    def _write(self, issues, context, conservation, stop: str, iterations: int) -> None:
        detectors.write_report(
            self.working_dir, detectors.as_record(context, issues)
        )
        action_statuses: dict[str, int] = {}
        for iteration in self.iterations:
            status = iteration.get("action_status", ACTION_NOT_EXECUTED)
            action_statuses[status] = action_statuses.get(status, 0) + 1
        record = {
            "switch": SWITCH,
            "config": self.repair_config.as_record(),
            "kind_order": list(self.kind_order),
            "engine_configured": self.engine is not None,
            "iterations_run": iterations,
            "stopped_because": stop,
            "applications": self.applications,
            "iterations": self.iterations,
            "conservation": conservation,
            "offered_texts": list(self.offered_texts),
            "treated": self._treated_record(issues),
            "final": counts_of(issues),
            "final_untreated": counts_of(self._untreated(issues)),
            "api_calls": len(self.attributions),
            "api_attributions": [dict(row) for row in self.attributions],
            "action_statuses": dict(sorted(action_statuses.items())),
            "failure": self.failure,
            "protected_drop_cap_refs": sorted(self.protected_drop_cap_refs),
            "protected_drop_cap_skips": sum(
                len(round_record.get("protected_skips", ()))
                for iteration in self.iterations
                for round_record in iteration.get("rounds", ())
            ),
        }
        path = self.working_dir / REPORT_NAME
        with path.open("w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
        record_config_manifest(
            self.working_dir,
            [
                CONFIG_PATH,
                DETECTOR_CONFIG_PATH,
                ROUNDS_CONFIG_PATH,
                acceptance.CONFIG_PATH,
                CLOSURE_CONFIG_PATH,
            ],
        )


def repair_document(
    translation_config,
    docs,
    run_trace=None,
    *,
    source_geometry=None,
    fixed_inventory=None,
    article_document_ir=None,
    article_state_journal=None,
    legal_slot_plan=None,
    manual_expectations=None,
):
    """Run the loop over one finished document and return what it left standing.

    A failure anywhere in the loop puts the document back as typesetting left it
    and falls through to plain detection. The loop is an improvement on a
    finished translation and is never a precondition for one: a run that could
    not repair has to produce the PDF it would have produced with the switch
    down, rather than no PDF at all.
    """
    loop = RepairLoop(
        translation_config,
        docs,
        run_trace=run_trace,
        source_geometry=source_geometry,
        fixed_inventory=fixed_inventory,
        article_document_ir=article_document_ir,
        article_state_journal=article_state_journal,
        legal_slot_plan=legal_slot_plan,
        manual_expectations=manual_expectations,
    )
    try:
        return loop.run()
    except Exception as error:  # noqa: BLE001 - the loop never stops a translation
        logger.exception(
            "react: the repair loop failed; the document is left as typesetting "
            "produced it and detection alone is reported"
        )
        rollback_record = None
        if loop.run_transaction is not None:
            rollback_record = loop.run_transaction.rollback()
        elif loop.baseline is not None:
            docs.page = loop.baseline.page
        if run_trace is not None and loop.run_transaction is None:
            if loop.trace_base_generation is None:
                run_trace.rollback_open_generations()
            else:
                run_trace.rollback_generations_after(
                    loop.trace_base_generation
                )
        loop.failure = {"type": type(error).__name__, "detail": str(error)}
        config = detectors.detector_config()
        try:
            issues, context = loop._detect(0)
        except Exception as detection_error:  # noqa: BLE001 - report the failure
            issues = []
            context = detectors.build_context(
                docs,
                config,
                getattr(translation_config, "lang_out", None),
                None,
                translation_performed=not getattr(
                    translation_config, "skip_translation", False
                ),
                iteration=0,
                source_geometry=loop.source_layout,
            )
            loop.failure["fallback_detection_failure"] = {
                "type": type(detection_error).__name__,
                "detail": str(detection_error),
            }
            context.notes.append(
                "repair fallback detection failed; no findings were classified"
            )
        attempted = any(
            iteration.get("action_status")
            in {ACTION_ATTEMPTED, ACTION_ROLLED_BACK, ACTION_COMMITTED}
            for iteration in loop.iterations
        )
        loop.iterations.append(
            {
                "iteration": len(loop.iterations) + 1,
                "outcome": OUTCOME_ROLLED_BACK if attempted else OUTCOME_INERT,
                "action_status": (
                    ACTION_ROLLED_BACK if attempted else ACTION_NOT_EXECUTED
                ),
                "failure": loop.failure,
                "rounds": [],
                "transaction": rollback_record,
            }
        )
        loop._write(
            issues,
            context,
            {
                "verdict": VIOLATED,
                "pages_before": len(docs.page),
                "pages_after": len(docs.page),
                "paragraphs_before": sum(shape(docs)),
                "paragraphs_after": sum(shape(docs)),
                "touched_refs": [],
                "changed_refs": [],
                "changed_outside_touched": [],
                "fixed_assets": fixed_assets.compare(
                    loop.fixed_inventory,
                    fixed_assets.build_inventory(
                        docs,
                        run_trace=run_trace,
                        protected_paragraph_labels=loop.protected_paragraph_labels,
                    ),
                    loop.asset_bbox_tolerance_pt,
                ).to_record(),
                "failure": loop.failure,
                "rollback": rollback_record,
            },
            STOP_TRANSACTION_FAILED,
            len(loop.iterations),
        )
        return issues
