"""C20C fast gate for typeset and final-PDF manual constraints."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pymupdf

# The gate must also run directly from its own directory.
# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.final_pdf_validator import ComplianceExpectations
from babeldoc.magazine.final_pdf_validator import FinalPdfValidator
from babeldoc.magazine.hitl_expectation import ManualConstraintEvidence
from babeldoc.magazine.hitl_expectation import ManualConstraintExpectation
from babeldoc.magazine.hitl_expectation import ManualConstraintKind
from babeldoc.magazine.hitl_expectation import ManualConstraintStage
from babeldoc.magazine.hitl_expectation import ManualConstraintStatus
from babeldoc.magazine.manual_constraint_validator import ManualOccurrenceObservation
from babeldoc.magazine.manual_constraint_validator import TranslationEligibility
from babeldoc.magazine.manual_constraint_validator import ValidationScope
from babeldoc.magazine.manual_constraint_validator import evaluate_manual_constraints
from babeldoc.magazine.manual_constraint_validator import load_page_policy_observables
from babeldoc.magazine.page_identity import PageSelectionMap

GATE_SET = "fast"
SHA = "a" * 64
PAGE_BOX = (0.0, 0.0, 300.0, 400.0)
REGION = (30.0, 20.0, 230.0, 90.0)
BOX = (40.0, 30.0, 120.0, 60.0)


def _stages(
    delivery=ManualConstraintStatus.PASS,
    target=ManualConstraintStatus.PASS,
):
    rows = []
    for stage, status in (
        (ManualConstraintStage.DELIVERY, delivery),
        (ManualConstraintStage.TARGET, target),
        (ManualConstraintStage.TYPESET, ManualConstraintStatus.PENDING),
        (ManualConstraintStage.FINAL_PDF, ManualConstraintStatus.PENDING),
    ):
        rows.append(
            ManualConstraintEvidence(
                stage=stage,
                status=status,
                evidence_refs=()
                if status is ManualConstraintStatus.PENDING
                else (f"seed:{stage.value}:{status.value}",),
            )
        )
    return tuple(rows)


def _expectation(
    expectation_id: str,
    kind: ManualConstraintKind,
    human_value: str,
    refs=("p2:a1#term",),
    selected=None,
    *,
    delivery=ManualConstraintStatus.PASS,
    target=ManualConstraintStatus.PASS,
):
    return ManualConstraintExpectation(
        expectation_id=expectation_id,
        kind=kind,
        human_value=human_value,
        source_occurrence_refs=tuple(refs),
        selected_occurrence_refs=tuple(refs if selected is None else selected),
        source_binding_sha256=SHA,
        stage_evidence=_stages(delivery, target),
    )


def _term_observation(reference="p2:a1#term", **changes):
    values = {
        "occurrence_ref": reference,
        "physical_page": 2,
        "output_index": 1,
        "article_id": "a1",
        "source_article_id": "a1",
        "eligibility": TranslationEligibility.ELIGIBLE,
        "policy_rule_id": "term-eligibility.v1:body",
        "typeset_text_fragments": ("ABB ", "Review"),
        "typeset_fragment_refs": ("fragment:1", "fragment:2"),
        "typeset_boxes": (BOX,),
        "final_text": "ABB Review",
        "final_glyph_boxes": (BOX,),
        "target_region": REGION,
        "page_box": PAGE_BOX,
    }
    values.update(changes)
    return ManualOccurrenceObservation(**values)


def _protected_observation(reference="p2:a1#fixed", **changes):
    values = {
        "occurrence_ref": reference,
        "physical_page": 2,
        "output_index": 1,
        "article_id": "a1",
        "source_article_id": "a1",
        "eligibility": TranslationEligibility.PROTECTED_FIXED,
        "policy_rule_id": "protected-fixed.v1:furniture",
        "target_region": REGION,
        "page_box": PAGE_BOX,
        "source_fixed_asset_sha256": "b" * 64,
        "final_fixed_asset_sha256": "b" * 64,
        "source_fixed_asset_box": BOX,
        "final_fixed_asset_box": BOX,
        "untouched": True,
    }
    values.update(changes)
    return ManualOccurrenceObservation(**values)


def _policy_observation(reference="p2:a1#policy", **changes):
    declared = load_page_policy_observables()["observables"]
    values = {
        "occurrence_ref": reference,
        "physical_page": 2,
        "output_index": 1,
        "article_id": "a1",
        "source_article_id": "a1",
        "eligibility": TranslationEligibility.ELIGIBLE,
        "policy_rule_id": "page-policy-observables.v1:article_opener",
        "typeset_boxes": (BOX,),
        "final_glyph_boxes": (BOX,),
        "target_region": REGION,
        "page_box": PAGE_BOX,
        "typeset_observables": {
            stages["typeset"]: True for stages in declared.values()
        },
        "final_pdf_observables": {
            stages["final_pdf"]: True for stages in declared.values()
        },
    }
    values.update(changes)
    return ManualOccurrenceObservation(**values)


def _drop_observation(reference, language, decision, **changes):
    typeset = {
        "drop_cap_owner_matches": True,
        "drop_cap_first_character_matches": True,
        "drop_cap_layout_generation_matches": True,
        "drop_cap_geometry_legal": True,
        f"drop_cap_{decision}_style_geometry": True,
    }
    final = {
        "drop_cap_owner_matches": True,
        "drop_cap_occurs_once": True,
        "drop_cap_first_character_matches": True,
        "drop_cap_geometry_legal": True,
        f"drop_cap_{decision}_style_geometry": True,
    }
    values = {
        "occurrence_ref": reference,
        "physical_page": 2,
        "output_index": 1,
        "article_id": "a1",
        "source_article_id": "a1",
        "eligibility": TranslationEligibility.ELIGIBLE,
        "policy_rule_id": f"drop-cap-final.v1:{language}:{decision}",
        "typeset_boxes": (BOX,),
        "final_glyph_boxes": (BOX,),
        "target_region": REGION,
        "page_box": PAGE_BOX,
        "typeset_observables": typeset,
        "final_pdf_observables": final,
        "drop_cap_character": "A" if language == "en" else "中",
        "drop_cap_language": language,
    }
    values.update(changes)
    return ManualOccurrenceObservation(**values)


def _pdf(path: Path, page_two_text: str) -> None:
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 45), "ABB Review on the wrong physical page")
    page = document.new_page(width=300, height=400)
    if page_two_text:
        page.insert_text((40, 45), page_two_text)
    document.save(path)
    document.close()


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool) -> None:
        print(f"{'PASS' if condition else 'FAIL'} {name}")
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="c20c-manual-") as temp:
        root = Path(temp)
        source = root / "source.pdf"
        _pdf(source, "ABB Review")
        mapping = PageSelectionMap.from_source_pdf(source)

        policy_contract = load_page_policy_observables()
        check(
            "C20C policy observables strictly extend the canonical C20B base",
            policy_contract["schema_version"]
            == "babeldoc.page-policy-observables.v1"
            and policy_contract["owner"] == "C20B-manual-delivery-target-base"
            and all(
                set(declaration)
                == {
                    "consumer",
                    "runtime_event",
                    "target_observable",
                    "final_observable",
                    "typeset_observable",
                    "final_pdf_observable",
                }
                for declaration in policy_contract["fields"].values()
            ),
        )

        term = _expectation(
            "term:abb-review",
            ManualConstraintKind.TERM,
            "ABB Review",
        )
        result = evaluate_manual_constraints(
            (term,), (_term_observation(),), mapping
        )
        check(
            "eligible term occurrences pass typeset and final from human value",
            result.accepted
            and result.expectations[0].human_value == "ABB Review"
            and result.expectations[0]
            .evidence_for(ManualConstraintStage.FINAL_PDF)
            .status
            is ManualConstraintStatus.PASS,
        )

        protected = _expectation(
            "term:fixed",
            ManualConstraintKind.TERM,
            "ABB Review",
            refs=("p2:a1#fixed",),
            delivery=ManualConstraintStatus.NOT_APPLICABLE,
            target=ManualConstraintStatus.NOT_APPLICABLE,
        )
        protected_result = evaluate_manual_constraints(
            (protected,), (_protected_observation(),), mapping
        )
        check(
            "protected fixed occurrence is explicit not_applicable with asset evidence",
            protected_result.accepted
            and protected_result.expectations[0]
            .evidence_for(ManualConstraintStage.TYPESET)
            .status
            is ManualConstraintStatus.NOT_APPLICABLE,
        )
        check(
            "protected fixed cannot be silently dropped or treated without policy evidence",
            not evaluate_manual_constraints((protected,), (), mapping).accepted
            and not evaluate_manual_constraints(
                (protected,),
                (_protected_observation(policy_rule_id="model-says-fixed"),),
                mapping,
            ).accepted,
        )

        negatives = {
            "model target wrong": _term_observation(typeset_text_fragments=("Other",)),
            "typeset repair changed term": _term_observation(
                typeset_text_fragments=("ABB Reviews",)
            ),
            "final term missing": _term_observation(final_text=""),
            "final term duplicate": _term_observation(
                final_text="ABB Review ABB Review"
            ),
            "wrong mapped page": _term_observation(output_index=0),
            "wrong article": _term_observation(article_id="a2"),
        }
        for name, observation in negatives.items():
            check(
                f"{name} fails occurrence-bound validation",
                not evaluate_manual_constraints((term,), (observation,), mapping).accepted,
            )
        check(
            "missing and duplicate occurrence fail denominator conservation",
            not evaluate_manual_constraints((term,), (), mapping).accepted
            and not evaluate_manual_constraints(
                (term,), (_term_observation(), _term_observation()), mapping
            ).accepted,
        )

        policy = _expectation(
            "policy:article-opener",
            ManualConstraintKind.PAGE_POLICY,
            "article_opener",
            refs=("p2:a1#policy",),
        )
        positive_policy = _policy_observation()
        check(
            "every page policy field has positive typeset and final observables",
            evaluate_manual_constraints(
                (policy,), (positive_policy,), mapping
            ).accepted,
        )
        declared = load_page_policy_observables()["observables"]
        policy_negatives = []
        for _field_name, stages in declared.items():
            broken_typeset = dict(positive_policy.typeset_observables)
            broken_typeset[stages["typeset"]] = False
            broken_final = dict(positive_policy.final_pdf_observables)
            broken_final[stages["final_pdf"]] = False
            policy_negatives.append(
                not evaluate_manual_constraints(
                    (policy,),
                    (
                        _policy_observation(
                            typeset_observables=broken_typeset,
                        ),
                    ),
                    mapping,
                ).accepted
                and not evaluate_manual_constraints(
                    (policy,),
                    (_policy_observation(final_pdf_observables=broken_final),),
                    mapping,
                ).accepted
            )
        check(
            "each page policy field has a typeset and final negative case",
            len(policy_negatives) == 7 and all(policy_negatives),
        )
        check(
            "loading policy without executing observables fails",
            not evaluate_manual_constraints(
                (policy,),
                (
                    _policy_observation(
                        typeset_observables={},
                        final_pdf_observables={},
                    ),
                ),
                mapping,
            ).accepted,
        )

        drop_positive = []
        for language, decision in (
            ("en", "keep"),
            ("en", "flatten"),
            ("zh", "keep"),
            ("zh", "flatten"),
        ):
            reference = f"p2:a1#drop-{language}-{decision}"
            expectation = _expectation(
                f"drop:{language}:{decision}",
                ManualConstraintKind.DROP_CAP,
                decision,
                refs=(reference,),
            )
            observation = _drop_observation(reference, language, decision)
            drop_positive.append(
                evaluate_manual_constraints(
                    (expectation,), (observation,), mapping
                ).accepted
            )
            broken = dict(observation.final_pdf_observables)
            broken["drop_cap_occurs_once"] = False
            check(
                f"{language} {decision} lost or duplicate drop cap fails",
                not evaluate_manual_constraints(
                    (expectation,),
                    (
                        _drop_observation(
                            reference,
                            language,
                            decision,
                            final_pdf_observables=broken,
                        ),
                    ),
                    mapping,
                ).accepted,
            )
        check("English/Chinese keep/flatten positive matrix", all(drop_positive))

        pending = _expectation(
            "term:pending",
            ManualConstraintKind.TERM,
            "ABB Review",
            delivery=ManualConstraintStatus.PENDING,
            target=ManualConstraintStatus.PENDING,
        )
        check(
            "pending or not_exercised cannot pass full_translation",
            not evaluate_manual_constraints(
                (pending,), (_term_observation(),), mapping
            ).accepted
            and not evaluate_manual_constraints(
                (
                    _expectation(
                        "term:not-exercised",
                        ManualConstraintKind.TERM,
                        "ABB Review",
                        delivery=ManualConstraintStatus.NOT_EXERCISED,
                        target=ManualConstraintStatus.NOT_EXERCISED,
                    ),
                ),
                (_term_observation(),),
                mapping,
            ).accepted,
        )
        not_selected = _expectation(
            "term:not-selected",
            ManualConstraintKind.TERM,
            "ABB Review",
            selected=(),
            delivery=ManualConstraintStatus.NOT_SELECTED,
            target=ManualConstraintStatus.NOT_SELECTED,
        )
        ns_result = evaluate_manual_constraints((not_selected,), (), mapping)
        check(
            "not_selected is explicit and does not fail selected acceptance",
            ns_result.accepted
            and ns_result.expectations[0]
            .evidence_for(ManualConstraintStage.FINAL_PDF)
            .status
            is ManualConstraintStatus.NOT_SELECTED,
        )
        parse_result = evaluate_manual_constraints(
            (pending,), (), mapping, scope=ValidationScope.PARSE_ONLY
        )
        check(
            "parse_only marks all translation-dependent stages not_exercised",
            parse_result.status == "parse_gate_pass"
            and all(
                item.status is ManualConstraintStatus.NOT_EXERCISED
                for item in parse_result.expectations[0].stage_evidence
            ),
        )
        parse_final = FinalPdfValidator().validate(
            source,
            source,
            root / "manual-parse-only.json",
            expectations=ComplianceExpectations(
                page_selection_map=mapping,
                manual_constraint_expectations=(pending,),
                validation_scope=ValidationScope.PARSE_ONLY,
            ),
        )
        check(
            "parse_only pipeline reports parse_gate_pass, never full compliance",
            parse_final.status == "parse_gate_pass"
            and not parse_final.fully_compliant,
        )

        final_result = FinalPdfValidator().validate(
            source,
            source,
            root / "manual-positive.json",
            expectations=ComplianceExpectations(
                page_selection_map=mapping,
                manual_constraint_expectations=(term,),
                manual_constraint_observations=(_term_observation(),),
            ),
        )
        check(
            "pipeline FinalPdfValidator extracts the bound region itself",
            final_result.fully_compliant
            and final_result.record["manual_constraints"]["status"] == "pass",
        )
        wrong_output_result = FinalPdfValidator().validate(
            source,
            source,
            root / "manual-wrong-output-index.json",
            expectations=ComplianceExpectations(
                page_selection_map=mapping,
                manual_constraint_expectations=(term,),
                manual_constraint_observations=(
                    _term_observation(output_index=0),
                ),
            ),
        )
        check(
            "PDF binding never repairs a claimed wrong output index",
            not wrong_output_result.fully_compliant,
        )
        wrong_pdf = root / "wrong.pdf"
        _pdf(wrong_pdf, "")
        wrong_map = PageSelectionMap.from_source_pdf(wrong_pdf)
        wrong_result = FinalPdfValidator().validate(
            wrong_pdf,
            wrong_pdf,
            root / "manual-wrong-page.json",
            expectations=ComplianceExpectations(
                page_selection_map=wrong_map,
                manual_constraint_expectations=(term,),
                manual_constraint_observations=(_term_observation(),),
            ),
        )
        check(
            "correct string on another page cannot compensate",
            not wrong_result.fully_compliant,
        )

    if failures:
        print(f"spec_check_manual_constraint_final: FAIL {failures}")
        return 1
    print("spec_check_manual_constraint_final: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
