"""The loop: detect, decide, act, lay out again, detect again.

The shape is the one the batch was planned around and every part of it is
bounded. Iterations stop at a declared ceiling. An iteration that does not
strictly reduce the number of findings is undone and the loop ends, so a repair
that trades one defect for another cannot be mistaken for progress and a loop
that oscillates cannot run to the ceiling. An iteration with no usable decision
applies nothing. Every iteration is written down -- what was found, what was
asked, what came back, what was rejected and why, what was written and what the
recheck then found -- because a loop whose reasoning is not on paper is one
nobody can audit after the fact.

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
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.react import actions
from babeldoc.magazine.react import writeback
from babeldoc.magazine.react.config import CONFIG_PATH
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
STOP_NOT_CONVERGING = "finding_count_did_not_strictly_decrease"
STOP_NOTHING_WRITTEN = "no_paragraph_was_written"

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


def counts_of(issues) -> dict:
    by_kind: dict[str, int] = {}
    for issue in issues:
        by_kind[issue.kind] = by_kind.get(issue.kind, 0) + 1
    return {"total": len(issues), "by_kind": by_kind}


def detect(translation_config, docs, config, iteration: int):
    context = detectors.build_context(
        docs,
        config,
        getattr(translation_config, "lang_out", None),
        None,
        translation_performed=not getattr(
            translation_config, "skip_translation", False
        ),
        iteration=iteration,
    )
    return detectors.run_detectors(context), context


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
        self.applications = 0
        # The document as it stood before the first iteration, taken once the
        # run begins and put back if the run cannot finish.
        self.baseline = None

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

    # -- one iteration ----------------------------------------------------

    def _candidates(self, issues, decision, action, context):
        """The findings the decision named, resolved and filtered, in its order."""
        pages_by_label = {view.label: view for view in context.pages}
        by_id = {issue.id: issue for issue in issues}
        records: list[actions.Application] = []
        accepted: list[actions.Candidate] = []
        limit = int(decision.parameters.get(actions.MAX_PARAGRAPHS, 0))
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
            if len(issue.paragraph_refs) != 1:
                # This action writes into one paragraph. A finding about a run
                # of them is a different repair, and v1 does not have one.
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
            verdict = actions.admits(
                issue, candidate.paragraph, action, candidate.source_text
            )
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

    def _apply(self, candidates, context, snapshot: Snapshot):
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
            writeback.rebuild(candidate.paragraph, outcome.translated_text)
            laid_out = writeback.retypeset(
                typesetting, candidate.paragraph, candidate.page
            )
            if not laid_out:
                # An empty composition would erase the line rather than repair
                # it, so this one paragraph goes back and the rest continue.
                candidate.page.pdf_paragraph[candidate.paragraph_index] = (
                    snapshot.paragraphs.pop((position, candidate.paragraph_index))
                )
                outcome.accepted = False
                outcome.reason = actions.REASON_LAYOUT
                records.append(outcome)
                continue
            outcome.changed = True
            self.touched.add(candidate.reference)
            self.applications += 1
            records.append(outcome)
        return records

    def _iterate(self, iteration: int, issues, context) -> tuple[str, str, list]:
        """One iteration. Returns (outcome, stop reason or empty, new issues)."""
        record: dict = {
            "iteration": iteration,
            "detected": counts_of(issues),
            "detected_ids": [issue.id for issue in issues],
        }
        self.iterations.append(record)

        if self.engine is None:
            record["outcome"] = OUTCOME_INERT
            record["decision"] = None
            return OUTCOME_INERT, STOP_NO_ENGINE, issues

        decision, request = self._decision_client().decide(issues)
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
        candidates, rejected = self._candidates(issues, decision, action, context)
        snapshot = Snapshot()
        applied = self._apply(candidates, context, snapshot) if candidates else []
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
            self.translation_config, self.docs, self.detector_config, iteration
        )
        before = {issue.id for issue in issues}
        after = {issue.id for issue in rechecked}
        record["recheck"] = counts_of(rechecked)
        record["resolved_ids"] = sorted(before - after)
        record["new_ids"] = sorted(after - before)

        if len(rechecked) >= len(issues):
            # Not strictly decreasing: undo this iteration and stop. A repair
            # that trades one finding for another is not progress, and a loop
            # that cannot tell the difference will run to its ceiling.
            snapshot.restore(self.docs)
            for item in written:
                self.touched.discard(item.reference)
                self.applications -= 1
            record["outcome"] = OUTCOME_ROLLED_BACK
            record["rolled_back_refs"] = [item.reference for item in written]
            logger.warning(
                "react: iteration %d left %d finding(s) against %d before it; "
                "rolled back and stopped",
                iteration,
                len(rechecked),
                len(issues),
            )
            return OUTCOME_ROLLED_BACK, STOP_NOT_CONVERGING, issues

        record["outcome"] = OUTCOME_ADVANCED
        return OUTCOME_ADVANCED, "", (rechecked, new_context)

    # -- the run ----------------------------------------------------------

    def run(self):
        before_digests = paragraph_digests(self.docs)
        before_shape = shape(self.docs)
        before_document = copy.deepcopy(self.docs)
        self.baseline = before_document

        issues, context = detect(
            self.translation_config, self.docs, self.detector_config, 0
        )
        stop = STOP_NO_ISSUES if not issues else STOP_CEILING
        iteration = 0
        while issues and iteration < self.repair_config.max_iterations:
            iteration += 1
            outcome, reason, result = self._iterate(iteration, issues, context)
            if outcome != OUTCOME_ADVANCED:
                stop = reason
                break
            issues, context = result
            stop = STOP_NO_ISSUES if not issues else STOP_CEILING

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
            stop = f"{VIOLATED}: conservation"
            issues, context = detect(
                self.translation_config, self.docs, self.detector_config, 0
            )

        self._write(issues, context, conservation, stop, iteration)
        hitl.after_repair(self.translation_config, self.offered_texts)
        return issues

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
            "final": counts_of(issues),
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
        issues, context = detect(translation_config, docs, config, 0)
        detectors.write_report(
            loop.working_dir, detectors.as_record(context, issues)
        )
        return issues
