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

Every iteration is written down -- what was found, what was asked, what came
back, what was rejected and why, what was written and what the recheck then
found -- because a loop whose reasoning is not on paper is one nobody can audit
after the fact.

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
from pathlib import Path

from lxml import etree

from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine import detectors
from babeldoc.magazine import hitl
from babeldoc.magazine.checkpoint import to_checkpoint_xml
from babeldoc.magazine.detectors.base import CONFIG_PATH as DETECTOR_CONFIG_PATH
from babeldoc.magazine.detectors.base import box_tuple
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.react import actions
from babeldoc.magazine.react import collision
from babeldoc.magazine.react import contain
from babeldoc.magazine.react import writeback
from babeldoc.magazine.react.config import CONFIG_PATH
from babeldoc.magazine.react.config import MAX_PARAGRAPHS
from babeldoc.magazine.react.config import load_repair_config
from babeldoc.magazine.react.decide import CachedDecisionClient
from babeldoc.magazine.react.decide import EngineTransport
from babeldoc.magazine.react.decide import engine_identity
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

# The switch, by the name the caller sets on the translation config.
SWITCH = "magazine_repair"

REPORT_NAME = "react_repair.report.json"

# Why the loop stopped.
STOP_CEILING = "iteration_ceiling_reached"
STOP_NO_ISSUES = "nothing_left_to_repair"
STOP_NO_ENGINE = "no_translation_engine_configured"
STOP_NO_DECISION = "no_usable_decision"
STOP_NO_ACTION = "decision_applied_nothing"
STOP_NOTHING_APPLICABLE = "no_finding_the_action_may_act_on"
STOP_NO_MECHANISM = "the_chosen_action_has_no_mechanism_behind_it"
STOP_NOT_CONVERGING = "finding_count_did_not_strictly_decrease"
STOP_NOTHING_WRITTEN = "no_paragraph_was_written"
STOP_CONVERGED_WITH_RESIDUALS = "converged_with_residuals"

# What an iteration did with itself.
OUTCOME_ADVANCED = "advanced"
OUTCOME_ROLLED_BACK = "rolled_back"
OUTCOME_INERT = "applied_nothing"

# Conservation verdicts.
CONSERVED = "conserved"
VIOLATED = "violated"


def enabled(translation_config) -> bool:
    return bool(getattr(translation_config, SWITCH, False))


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
    digests: dict[str, str] = {}
    for position, node in enumerate(root.findall("page")):
        label = labels[position] if position < len(labels) else position + 1
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


def detect(translation_config, docs, config, iteration: int, source_geometry=None):
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

    paragraphs_per_finding: int
    admits: object
    apply: object


class RepairLoop:
    """One document, one run of the loop."""

    def __init__(self, translation_config, docs, decision_client=None, translator=None):
        self.translation_config = translation_config
        self.docs = docs
        self.detector_config = detectors.detector_config()
        self.repair_config = load_repair_config(
            None,
            tuple(sorted(module.KIND for module in detectors.DETECTORS.values())),
        )
        self.working_dir = Path(
            translation_config.get_working_file_path(REPORT_NAME)
        ).parent
        self.engine = getattr(translation_config, "translator", None)
        self.language = getattr(translation_config, "lang_out", "") or ""
        self.identity = engine_identity(self.engine, self.language)
        self.ignore_cache = bool(getattr(translation_config, "ignore_cache", False))
        self.decision_client = decision_client
        self.translator = translator
        self.typesetting = None
        self.iterations: list[dict] = []
        self.offered_texts: list[str] = []
        self.touched: set[str] = set()
        # Findings this run repaired into something the detectors still report,
        # by id. Run state and nothing else: the intermediate language is frozen
        # and carries no field for it, and a rerun starts with none of them.
        self.treated: dict[str, dict] = {}
        self.applications = 0
        # The document as it stood before the first iteration, taken once the
        # run begins and put back if the run cannot finish.
        self.baseline = None
        # Where every paragraph stood before anything was translated, read from
        # the run's own checkpoint. Loaded once and handed to every pass: the
        # loop detects several times over one document and the file behind this
        # is the whole untranslated document.
        self.source_layout = detectors.source_geometry_of(
            self.working_dir, self.detector_config
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
            )
        return self.decision_client

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
            self.typesetting = Typesetting(self.translation_config)
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
                admits=actions.admits_candidate,
                apply=self._translate_orphans,
            ),
            contain.NAME: Handler(
                paragraphs_per_finding=contain.PARAGRAPHS_PER_FINDING,
                admits=contain.admits,
                apply=self._contain,
            ),
            collision.NAME: Handler(
                paragraphs_per_finding=collision.PARAGRAPHS_PER_FINDING,
                admits=collision.admits,
                apply=self._apply_nothing,
            ),
        }

    # -- one iteration ----------------------------------------------------

    def _candidates(self, issues, decision, action, context, handler):
        """The findings the decision named, resolved and filtered, in its order."""
        pages_by_label = {view.label: view for view in context.pages}
        by_id = {issue.id: issue for issue in issues}
        records: list[actions.Application] = []
        accepted: list[actions.Candidate] = []
        limit = int(decision.parameters.get(MAX_PARAGRAPHS, 0))
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
            if len(issue.paragraph_refs) != handler.paragraphs_per_finding:
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
            candidate = actions.resolve(issue, pages_by_label)
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
            verdict = handler.admits(issue, candidate, action)
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
            if len(accepted) >= limit:
                records.append(
                    actions.Application(
                        issue_id=issue_id,
                        reference=candidate.reference,
                        accepted=False,
                        reason=actions.REASON_LIMIT,
                        source_text=candidate.source_text,
                    )
                )
                continue
            accepted.append(candidate)
        return accepted, records

    def _apply_nothing(self, candidates, context, snapshot: Snapshot, action):
        """The mechanism of an action that writes nothing. Nothing is written.

        Reached only where an action admitted a candidate without having a
        mechanism to apply to it, which no declared action does; the loop then
        stops with nothing written rather than with something unexplained.
        """
        return []

    def _contain(self, candidates, context, snapshot: Snapshot, action):
        """Put each admitted paragraph back inside its page. What happened.

        Where inside is the action's own declared margin, read from the
        vocabulary rather than taken from the finding: what a repair is measured
        against has to be the declaration and not a number that travelled
        through a request.
        """
        positions = {
            view.label: position for position, view in enumerate(context.pages)
        }
        records: list[actions.Application] = []
        for candidate in candidates:
            position = positions[candidate.page_index]
            snapshot.take(position, candidate.page, candidate.paragraph_index)
            outcome = contain.apply_one(candidate, action)
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

    def _translate_orphans(self, candidates, context, snapshot: Snapshot, action):
        """Translate and write each admitted candidate. Returns what happened."""
        pages_by_label = {view.label: view for view in context.pages}
        positions = {view.label: position for position, view in enumerate(context.pages)}
        translator = self._translator()
        typesetting = self._typesetting()
        records: list[actions.Application] = []
        for candidate in candidates:
            view = pages_by_label[candidate.page_index]
            context_text = actions.page_context(
                view, candidate.paragraph_index, self.repair_config.page_context_chars
            )
            outcome = translator.translate(candidate.source_text, context_text)
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
            position = positions[candidate.page_index]
            snapshot.take(position, candidate.page, candidate.paragraph_index)
            box_before = box_tuple(candidate.paragraph.box)
            writeback.rebuild(candidate.paragraph, outcome.translated_text)
            laid_out = writeback.retypeset(
                typesetting, candidate.paragraph, candidate.page
            )
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

    def _iterate(self, iteration: int, issues, context) -> tuple[str, str, list]:
        """One iteration. Returns (outcome, stop reason or empty, new issues)."""
        working = self._untreated(issues)
        record: dict = {
            "iteration": iteration,
            "detected": counts_of(issues),
            "detected_ids": [issue.id for issue in issues],
            "untreated": counts_of(working),
        }
        self.iterations.append(record)

        if self.engine is None:
            record["outcome"] = OUTCOME_INERT
            record["decision"] = None
            return OUTCOME_INERT, STOP_NO_ENGINE, issues

        decision, request = self._decision_client().decide(working)
        record["decision"] = decision.as_record()
        record["request"] = {
            "prompt_sha256": request.prompt_digest,
            "cache_key": request.key,
        }
        if decision.refused:
            record["outcome"] = OUTCOME_INERT
            return OUTCOME_INERT, STOP_NO_DECISION, issues
        if not decision.acts:
            record["outcome"] = OUTCOME_INERT
            return OUTCOME_INERT, STOP_NO_ACTION, issues

        action = self.repair_config.action(decision.action)
        handler = self._handlers().get(decision.action)
        if handler is None:
            record["outcome"] = OUTCOME_INERT
            logger.error(
                "react: the vocabulary declares %r but nothing here carries it "
                "out; no paragraph was touched",
                decision.action,
            )
            return OUTCOME_INERT, STOP_NO_MECHANISM, issues
        candidates, rejected = self._candidates(
            working, decision, action, context, handler
        )
        snapshot = Snapshot()
        applied = (
            handler.apply(candidates, context, snapshot, action) if candidates else []
        )
        record["applicability"] = [item.as_record() for item in rejected]
        record["executed"] = [item.as_record() for item in applied]
        written = [item for item in applied if item.changed]
        if not written:
            record["outcome"] = OUTCOME_INERT
            snapshot.restore(self.docs)
            return (
                OUTCOME_INERT,
                STOP_NOTHING_APPLICABLE if not candidates else STOP_NOTHING_WRITTEN,
                issues,
            )

        rechecked, new_context = detect(
            self.translation_config,
            self.docs,
            self.detector_config,
            iteration,
            self.source_layout,
        )
        before = {issue.id for issue in issues}
        after = {issue.id for issue in rechecked}
        newly = self._newly_treated(written, issues, rechecked, iteration)
        self.treated.update(newly)
        untreated = self._untreated(rechecked)
        record["recheck"] = counts_of(rechecked)
        record["untreated_after"] = counts_of(untreated)
        record["resolved_ids"] = sorted(before - after)
        record["new_ids"] = sorted(after - before)
        record["treated_ids"] = sorted(newly)

        if len(untreated) >= len(working):
            # Not strictly decreasing: undo this iteration and stop. A repair
            # that trades one finding for another is not progress, and a loop
            # that cannot tell the difference will run to its ceiling. What is
            # counted is the findings this run has neither resolved nor made
            # smaller, so a repair that improved a finding without clearing it
            # is progress and one that rewrote a line into the same defect is
            # not.
            for issue_id in newly:
                self.treated.pop(issue_id, None)
            snapshot.restore(self.docs)
            for item in written:
                self.touched.discard(item.reference)
                self.applications -= 1
            record["outcome"] = OUTCOME_ROLLED_BACK
            record["rolled_back_refs"] = [item.reference for item in written]
            record["treated_ids"] = []
            logger.warning(
                "react: iteration %d left %d untreated finding(s) against %d "
                "before it; rolled back and stopped",
                iteration,
                len(untreated),
                len(working),
            )
            return OUTCOME_ROLLED_BACK, STOP_NOT_CONVERGING, issues

        record["outcome"] = OUTCOME_ADVANCED
        return OUTCOME_ADVANCED, "", (rechecked, new_context)

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
        before_digests = paragraph_digests(self.docs)
        before_shape = shape(self.docs)
        before_document = copy.deepcopy(self.docs)
        self.baseline = before_document

        issues, context = detect(
            self.translation_config,
            self.docs,
            self.detector_config,
            0,
            self.source_layout,
        )
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
        }
        if before_shape != after_shape or outside:
            conservation["verdict"] = VIOLATED
            logger.error(
                "react: conservation violated (shape %s -> %s, %d paragraph(s) "
                "changed outside the repaired set); the document is restored to "
                "what it was before the loop",
                before_shape,
                after_shape,
                len(outside),
            )
            self.docs.page = before_document.page
            self.touched.clear()
            self.treated.clear()
            stop = f"{VIOLATED}: conservation"
            issues, context = detect(
                self.translation_config,
                self.docs,
                self.detector_config,
                0,
                self.source_layout,
            )

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
        record = {
            "switch": SWITCH,
            "config": self.repair_config.as_record(),
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
        }
        path = self.working_dir / REPORT_NAME
        with path.open("w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
        record_config_manifest(self.working_dir, [CONFIG_PATH, DETECTOR_CONFIG_PATH])


def repair_document(translation_config, docs):
    """Run the loop over one finished document and return what it left standing.

    A failure anywhere in the loop puts the document back as typesetting left it
    and falls through to plain detection. The loop is an improvement on a
    finished translation and is never a precondition for one: a run that could
    not repair has to produce the PDF it would have produced with the switch
    down, rather than no PDF at all.
    """
    loop = RepairLoop(translation_config, docs)
    try:
        return loop.run()
    except Exception:  # noqa: BLE001 - the loop never stops a translation
        logger.exception(
            "react: the repair loop failed; the document is left as typesetting "
            "produced it and detection alone is reported"
        )
        if loop.baseline is not None:
            docs.page = loop.baseline.page
        config = detectors.detector_config()
        issues, context = detect(
            translation_config,
            docs,
            config,
            0,
            detectors.source_geometry_of(loop.working_dir, config),
        )
        detectors.write_report(
            loop.working_dir, detectors.as_record(context, issues)
        )
        return issues
