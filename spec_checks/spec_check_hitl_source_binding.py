"""Offline checks for the HITL source-binding protocol seed."""

from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
import json
import sys
import tempfile
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.hitl_binding import BINDING_REPORT_SUFFIX  # noqa: E402
from babeldoc.magazine.hitl_binding import DECISIONS_SUFFIX  # noqa: E402
from babeldoc.magazine.hitl_binding import HITL_BINDING_EVIDENCE_MISMATCH  # noqa: E402
from babeldoc.magazine.hitl_binding import HITL_DECISION_AMBIGUOUS  # noqa: E402
from babeldoc.magazine.hitl_binding import HITL_DECISION_REF_STALE  # noqa: E402
from babeldoc.magazine.hitl_binding import HITL_REVIEW_MANIFEST_MISMATCH  # noqa: E402
from babeldoc.magazine.hitl_binding import HITL_SCHEMA_REQUIRES_BINDING  # noqa: E402
from babeldoc.magazine.hitl_binding import HITL_SEMANTIC_PAGE_STALE  # noqa: E402
from babeldoc.magazine.hitl_binding import REVIEW_MANIFEST_SUFFIX  # noqa: E402
from babeldoc.magazine.hitl_binding import REVIEW_SUFFIX  # noqa: E402
from babeldoc.magazine.hitl_binding import HitlBindingError  # noqa: E402
from babeldoc.magazine.hitl_binding import bind_legacy_files  # noqa: E402
from babeldoc.magazine.hitl_binding import binding_evidence_payload  # noqa: E402
from babeldoc.magazine.hitl_binding import canonical_json_bytes  # noqa: E402
from babeldoc.magazine.hitl_binding import canonical_sha256  # noqa: E402
from babeldoc.magazine.hitl_binding import file_sha256  # noqa: E402
from babeldoc.magazine.hitl_binding import load_bound_decisions  # noqa: E402
from babeldoc.magazine.hitl_binding import load_toml_semantic_config  # noqa: E402
from babeldoc.magazine.hitl_binding import semantic_config_sha256  # noqa: E402
from babeldoc.magazine.hitl_binding import source_snapshot  # noqa: E402
from babeldoc.magazine.hitl_binding import verify_bound_artifacts  # noqa: E402
from babeldoc.magazine.hitl_expectation import (  # noqa: E402
    MANUAL_EXPECTATION_SCHEMA_VERSION,
)
from babeldoc.magazine.hitl_expectation import ManualConstraintEvidence  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintExpectation  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintKind  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintStage  # noqa: E402
from babeldoc.magazine.hitl_expectation import ManualConstraintStatus  # noqa: E402
from babeldoc.magazine.hitl_expectation import (  # noqa: E402
    ManualExpectationProtocolError,
)
from babeldoc.magazine.hitl_expectation import (  # noqa: E402
    manual_constraint_expectation_schema,
)
from babeldoc.magazine.hitl_expectation import pending_stage_evidence  # noqa: E402


def _sample() -> ManualConstraintExpectation:
    return ManualConstraintExpectation(
        expectation_id="term:abb-review",
        kind=ManualConstraintKind.TERM,
        human_value="ABB Review",
        source_occurrence_refs=("page:7/paragraph:2/span:0-11", "page:2/p:4"),
        selected_occurrence_refs=("page:2/p:4",),
        source_binding_sha256="a" * 64,
        stage_evidence=pending_stage_evidence(),
    )


def _assert_protocol_error(callback: Callable[[], Any], needle: str) -> None:
    try:
        callback()
    except ManualExpectationProtocolError as exc:
        assert needle in str(exc), (needle, str(exc))
    else:
        raise AssertionError("expected ManualExpectationProtocolError")


def check_closed_enums() -> None:
    assert [item.value for item in ManualConstraintKind] == [
        "term",
        "page_policy",
        "drop_cap",
    ]
    assert [item.value for item in ManualConstraintStage] == [
        "delivery",
        "target",
        "typeset",
        "final_pdf",
    ]
    assert [item.value for item in ManualConstraintStatus] == [
        "pending",
        "pass",
        "fail",
        "not_exercised",
        "not_selected",
        "not_applicable",
    ]


def check_strict_schema() -> None:
    schema = manual_constraint_expectation_schema()
    assert schema["$id"] == MANUAL_EXPECTATION_SCHEMA_VERSION
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    evidence = schema["properties"]["stage_evidence"]
    assert evidence["minItems"] == evidence["maxItems"] == 4
    assert evidence["items"] is False
    assert [
        item["properties"]["stage"]["const"] for item in evidence["prefixItems"]
    ] == ["delivery", "target", "typeset", "final_pdf"]
    for item_schema in evidence["prefixItems"]:
        assert item_schema["additionalProperties"] is False
        assert set(item_schema["required"]) == set(item_schema["properties"])
        assert "not_exercised" in item_schema["properties"]["status"]["enum"]
    # The caller cannot mutate a later schema result through an earlier one.
    schema["properties"].clear()
    assert manual_constraint_expectation_schema()["properties"]


def check_canonical_serialization() -> None:
    expectation = _sample()
    first = expectation.to_json_bytes()
    second = _sample().to_json_bytes()
    assert first == second
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")
    assert expectation.source_occurrence_refs == (
        "page:2/p:4",
        "page:7/paragraph:2/span:0-11",
    )
    decoded = json.loads(first)
    assert list(decoded) == sorted(decoded)
    assert decoded["stage_evidence"] == [
        {"evidence_refs": [], "stage": stage, "status": "pending"}
        for stage in ("delivery", "target", "typeset", "final_pdf")
    ]


def check_round_trip() -> None:
    expected = _sample()
    restored = ManualConstraintExpectation.from_json_bytes(expected.to_json_bytes())
    assert restored == expected
    assert restored.to_json_bytes() == expected.to_json_bytes()


def check_unknown_and_missing_top_level_fields() -> None:
    record = _sample().to_record()
    unknown = copy.deepcopy(record)
    unknown["model_inferred_value"] = "forbidden"
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(unknown), "unknown fields"
    )
    missing = copy.deepcopy(record)
    del missing["human_value"]
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(missing), "missing fields"
    )


def check_unknown_and_missing_evidence_fields() -> None:
    record = _sample().to_record()
    unknown = copy.deepcopy(record)
    unknown["stage_evidence"][0]["provider_response"] = "forbidden"
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(unknown), "unknown fields"
    )
    missing = copy.deepcopy(record)
    del missing["stage_evidence"][0]["evidence_refs"]
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(missing), "missing fields"
    )


def check_binding_and_occurrence_invariants() -> None:
    record = _sample().to_record()
    bad_sha = copy.deepcopy(record)
    bad_sha["source_binding_sha256"] = "A" * 64
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(bad_sha),
        "64 lowercase hexadecimal",
    )
    outside = copy.deepcopy(record)
    outside["selected_occurrence_refs"] = ["page:99/p:1"]
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(outside), "must be a subset"
    )
    duplicates = copy.deepcopy(record)
    duplicates["source_occurrence_refs"].append(duplicates["source_occurrence_refs"][0])
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(duplicates), "unique refs"
    )


def check_stage_status_and_evidence_invariants() -> None:
    record = _sample().to_record()
    wrong_order = copy.deepcopy(record)
    wrong_order["stage_evidence"].reverse()
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(wrong_order),
        "canonical order",
    )
    unknown_status = copy.deepcopy(record)
    unknown_status["stage_evidence"][0]["status"] = "skipped"
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(unknown_status),
        "unknown manual constraint status",
    )
    no_evidence = copy.deepcopy(record)
    no_evidence["stage_evidence"][0]["status"] = "not_exercised"
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(no_evidence),
        "requires evidence refs",
    )
    pending_with_evidence = copy.deepcopy(record)
    pending_with_evidence["stage_evidence"][0]["evidence_refs"] = ["request:sha256:abc"]
    _assert_protocol_error(
        lambda: ManualConstraintExpectation.from_record(pending_with_evidence),
        "pending status cannot carry evidence refs",
    )
    exercised = ManualConstraintEvidence(
        stage=ManualConstraintStage.DELIVERY,
        status=ManualConstraintStatus.NOT_EXERCISED,
        evidence_refs=("reason:no-selected-eligible-occurrence",),
    )
    assert exercised.status is ManualConstraintStatus.NOT_EXERCISED


def check_immutable_value_graph() -> None:
    expectation = _sample()
    assert isinstance(expectation.source_occurrence_refs, tuple)
    assert isinstance(expectation.stage_evidence, tuple)
    assert all(
        isinstance(item.evidence_refs, tuple) for item in expectation.stage_evidence
    )
    try:
        expectation.human_value = "model output"  # type: ignore[misc]
    except (dataclasses.FrozenInstanceError, AttributeError):
        pass
    else:
        raise AssertionError("ManualConstraintExpectation must be immutable")


def check_unique_type_ownership() -> None:
    owners: list[Path] = []
    for path in sorted((ROOT / "babeldoc").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == (
                "ManualConstraintExpectation"
            ):
                owners.append(path.relative_to(ROOT))
    assert owners == [Path("babeldoc/magazine/hitl_expectation.py")], owners


PROTOCOL_CHECKS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("closed kind/stage/status enums", check_closed_enums),
    ("closed JSON schema", check_strict_schema),
    ("canonical serialization", check_canonical_serialization),
    ("canonical round-trip", check_round_trip),
    ("unknown/missing expectation fields", check_unknown_and_missing_top_level_fields),
    ("unknown/missing evidence fields", check_unknown_and_missing_evidence_fields),
    (
        "source binding and occurrence invariants",
        check_binding_and_occurrence_invariants,
    ),
    ("stage/status/evidence invariants", check_stage_status_and_evidence_invariants),
    ("immutable value graph", check_immutable_value_graph),
    ("unique type ownership", check_unique_type_ownership),
)


class _RuntimeConfig(dict):
    def __init__(self, values: dict[str, Any], selected: set[int] | None = None):
        super().__init__(values)
        self.selected = selected

    def should_translate_page(self, page: int) -> bool:
        return self.selected is None or page in self.selected


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(canonical_json_bytes(value, pretty=True))


def _make_pdf(path: Path, page_texts: tuple[str, ...]) -> None:
    import pymupdf

    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page(width=300, height=400)
        page.insert_text((36, 72), text)
    document.save(path)
    document.close()


@contextmanager
def _bound_fixture(*, selected: set[int] | None = None) -> Iterator[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="c20b-binding-") as folder:
        root = Path(folder)
        source = root / "Sample.pdf"
        config_path = root / "babeldoc.toml"
        legacy_review_path = root / "Sample.review.legacy.json"
        legacy_decisions_path = root / "Sample.decisions.legacy.json"
        output = root / "bound"
        _make_pdf(
            source,
            (
                "alpha appears on page one",
                "page two carries policy",
                "alpha appears on page three",
                "page four remains outside a subset",
            ),
        )
        config_path.write_text(
            '[babeldoc]\nlang-in = "en"\nmagazine-mode = "hitl-apply"\n',
            encoding="utf-8",
        )
        review = {
            "format_version": 3,
            "sample": "Sample",
            "page_kinds": [
                {
                    "page": page,
                    "machine_kind": "article_body",
                    "conf": 1.0,
                    "ambiguous": False,
                    "source": "deterministic",
                }
                for page in range(1, 5)
            ],
            "terms": [{"source": "alpha", "auto_target": "AUTO"}],
            "drop_caps": [],
        }
        decisions = {
            "format_version": 2,
            "sample": "Sample",
            "page_kinds": {
                "1": "front_cover",
                "2": "toc",
                "4": "article_body",
            },
            "terms": {"alpha": "HUMAN ALPHA"},
            "drop_caps": {},
        }
        _write_json(legacy_review_path, review)
        _write_json(legacy_decisions_path, decisions)
        before = {
            legacy_review_path: legacy_review_path.read_bytes(),
            legacy_decisions_path: legacy_decisions_path.read_bytes(),
        }
        report = bind_legacy_files(
            source=source,
            config_path=config_path,
            review_path=legacy_review_path,
            decisions_path=legacy_decisions_path,
            output_dir=output,
        )
        values = load_toml_semantic_config(config_path)
        runtime = _RuntimeConfig(values, selected)
        yield {
            "root": root,
            "source": source,
            "config_path": config_path,
            "config": runtime,
            "legacy_review": legacy_review_path,
            "legacy_decisions": legacy_decisions_path,
            "legacy_before": before,
            "output": output,
            "report": report,
            "decisions_path": output / f"Sample{DECISIONS_SUFFIX}",
        }


def _expect_binding_error(callback: Callable[[], Any], code: str) -> HitlBindingError:
    try:
        callback()
    except HitlBindingError as exc:
        assert exc.code == code, (code, exc.code, str(exc))
        return exc
    raise AssertionError(f"expected {code}")


def check_v4_binding_and_standard_outputs() -> None:
    with _bound_fixture() as fixture:
        output = fixture["output"]
        assert sorted(path.name for path in output.iterdir()) == [
            f"Sample{BINDING_REPORT_SUFFIX}",
            f"Sample{DECISIONS_SUFFIX}",
            f"Sample{REVIEW_MANIFEST_SUFFIX}",
            f"Sample{REVIEW_SUFFIX}",
        ]
        for path, expected in fixture["legacy_before"].items():
            assert path.read_bytes() == expected
        decisions = json.loads(fixture["decisions_path"].read_text(encoding="utf-8"))
        lineage = decisions["lineage"]
        assert lineage["binding_mode"] == "legacy_explicit_rebind"
        assert lineage["legacy_review_cycle_unverified"] is True
        assert lineage["legacy_review"]["sha256"] == file_sha256(
            fixture["legacy_review"]
        )
        assert lineage["legacy_decisions"]["sha256"] == file_sha256(
            fixture["legacy_decisions"]
        )
        assert decisions["terms"]["alpha"] == "HUMAN ALPHA"
        bound = load_bound_decisions(
            fixture["decisions_path"],
            source=fixture["source"],
            config=fixture["config"],
        )
        assert bound.terms == {"alpha": "HUMAN ALPHA"}
        assert bound.page_kinds == {
            1: "front_cover",
            2: "toc",
            4: "article_body",
        }


def check_exact_bind_cli_interface() -> None:
    from tools.hitl_review import main as review_main

    with _bound_fixture() as fixture:
        output = fixture["root"] / "cli-output"
        exit_code = review_main(
            [
                "bind",
                "--source",
                str(fixture["source"]),
                "--config",
                str(fixture["config_path"]),
                "--review",
                str(fixture["legacy_review"]),
                "--decisions",
                str(fixture["legacy_decisions"]),
                "--output-dir",
                str(output),
            ]
        )
        assert exit_code == 0
        assert (output / f"Sample{DECISIONS_SUFFIX}").is_file()
        assert (output / f"Sample{BINDING_REPORT_SUFFIX}").is_file()


def check_runtime_loader_and_separate_draft() -> None:
    from babeldoc.magazine import hitl
    from babeldoc.magazine.runtime_profile import resolve_magazine_profile

    class Runtime:
        def __init__(self, fixture: dict[str, Any]):
            values = dict(fixture["config"])
            self.input_file = fixture["source"]
            self.magazine_reviews_dir = fixture["output"]
            self.magazine_mode = "hitl-apply"
            self.magazine_hitl_apply = True
            self.magazine_hitl_export = True
            self.working_dir = fixture["root"] / "work"
            self.working_dir.mkdir()
            self._values = values
            profile = resolve_magazine_profile("hitl-apply", None)
            assert profile is not None
            for name, value in profile.switches.items():
                setattr(self, name, value)

        def __getattr__(self, name: str) -> Any:
            if name in self._values:
                return self._values[name]
            dashed = name.replace("_", "-")
            if dashed in self._values:
                return self._values[dashed]
            raise AttributeError(name)

        def should_translate_page(self, page: int) -> bool:
            return page in {2, 3}

        def get_working_file_path(self, name: str) -> Path:
            return self.working_dir / name

    with _bound_fixture(selected={2, 3}) as fixture:
        config = Runtime(fixture)
        docs = SimpleNamespace(
            page=[
                SimpleNamespace(page_number=index, pdf_paragraph=[])
                for index in range(4)
            ]
        )
        decisions = hitl._decisions_for(config, docs)
        assert decisions is not None
        assert decisions.page_kinds == {2: "toc"}
        assert decisions.terms == {"alpha": "HUMAN ALPHA"}
        review_path = fixture["output"] / f"Sample{REVIEW_SUFFIX}"
        before = review_path.read_bytes()
        runtime_path = hitl._write_run_draft(
            config,
            {
                "format_version": 4,
                "sample": "Sample",
                "page_kinds": [],
                "terms": [],
                "drop_caps": [],
            },
        )
        assert runtime_path.name == "Sample.runtime-review.json"
        assert review_path.read_bytes() == before


def check_noncontiguous_selected_projection() -> None:
    with _bound_fixture(selected={2, 3}) as fixture:
        bound = load_bound_decisions(
            fixture["decisions_path"],
            source=fixture["source"],
            config=fixture["config"],
        )
        assert bound.selected_pages == (2, 3)
        assert bound.page_kinds == {2: "toc"}
        assert bound.terms == {"alpha": "HUMAN ALPHA"}
        by_decision = {
            (item["section"], item["decision"]): item
            for item in bound.projection_report
        }
        assert by_decision[("page_kinds", "1")]["status"] == "not_selected"
        assert by_decision[("page_kinds", "4")]["status"] == "not_selected"
        assert by_decision[("terms", "alpha")]["full_occurrence_count"] == 2
        assert len(by_decision[("terms", "alpha")]["selected_occurrence_refs"]) == 1
        full = source_snapshot(fixture["source"], fixture["config"])
        assert full.source_binding["per_physical_page_semantic_sha256"]["3"]


def check_semantic_config_projection_boundary() -> None:
    base = {"lang-in": "en", "magazine-mode": "hitl-apply"}
    expected = semantic_config_sha256(base)
    diagnostic = {
        **base,
        "debug": True,
        "show-char-box": True,
        "qps": 99,
        "pages": "2-3,8-9",
        "output-dir": "elsewhere",
        "openai-api-key": "do-not-bind",
        "openai-model": "provider-choice-does-not-change-source-il",
    }
    assert semantic_config_sha256(diagnostic) == expected
    for key, value in (
        ("ocr-workaround", True),
        ("skip-scanned-detection", True),
        ("split-short-lines", True),
        ("min-text-length", 9),
    ):
        assert semantic_config_sha256({**base, key: value}) != expected


def check_legacy_apply_and_detached_evidence_fail_closed() -> None:
    with _bound_fixture() as fixture:
        _expect_binding_error(
            lambda: load_bound_decisions(
                fixture["legacy_decisions"],
                source=fixture["source"],
                config=fixture["config"],
            ),
            HITL_SCHEMA_REQUIRES_BINDING,
        )
        report_path = fixture["output"] / f"Sample{BINDING_REPORT_SUFFIX}"
        report_path.unlink()
        _expect_binding_error(
            lambda: load_bound_decisions(
                fixture["decisions_path"],
                source=fixture["source"],
                config=fixture["config"],
            ),
            HITL_BINDING_EVIDENCE_MISMATCH,
        )


def check_candidate_lineage_and_ref_tamper_fail_closed() -> None:
    with _bound_fixture() as fixture:
        review_path = fixture["output"] / f"Sample{REVIEW_SUFFIX}"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["terms"][0]["source"] = "tampered"
        _write_json(review_path, review)
        _expect_binding_error(
            lambda: load_bound_decisions(
                fixture["decisions_path"],
                source=fixture["source"],
                config=fixture["config"],
            ),
            HITL_REVIEW_MANIFEST_MISMATCH,
        )
    with _bound_fixture() as fixture:
        decisions = json.loads(fixture["decisions_path"].read_text(encoding="utf-8"))
        decisions["lineage"]["legacy_review_cycle_unverified"] = False
        _write_json(fixture["decisions_path"], decisions)
        _expect_binding_error(
            lambda: load_bound_decisions(
                fixture["decisions_path"],
                source=fixture["source"],
                config=fixture["config"],
            ),
            HITL_BINDING_EVIDENCE_MISMATCH,
        )
    with _bound_fixture() as fixture:
        decisions = json.loads(fixture["decisions_path"].read_text(encoding="utf-8"))
        decisions["decision_refs"]["page_kinds"]["2"]["fingerprint"] = "0" * 64
        evidence = binding_evidence_payload(
            source_binding=decisions["source_binding"],
            review_manifest_sha256=decisions["review_manifest_sha256"],
            lineage=decisions["lineage"],
            decisions=decisions,
            binding_results=decisions["binding_results"],
        )
        evidence_sha = canonical_sha256(evidence)
        decisions["lineage"]["binding_evidence_sha256"] = evidence_sha
        decisions["binding_evidence"] = evidence
        _write_json(fixture["decisions_path"], decisions)
        report_path = fixture["output"] / f"Sample{BINDING_REPORT_SUFFIX}"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["binding_evidence"] = evidence
        report["binding_evidence_sha256"] = evidence_sha
        _write_json(report_path, report)
        _expect_binding_error(
            lambda: load_bound_decisions(
                fixture["decisions_path"],
                source=fixture["source"],
                config=fixture["config"],
            ),
            HITL_DECISION_REF_STALE,
        )


def check_source_and_config_staleness() -> None:
    with _bound_fixture() as fixture:
        changed = fixture["root"] / "changed.pdf"
        _make_pdf(
            changed,
            (
                "alpha appears on page one",
                "page two changed by one word",
                "alpha appears on page three",
                "page four remains outside a subset",
            ),
        )
        _expect_binding_error(
            lambda: load_bound_decisions(
                fixture["decisions_path"],
                source=changed,
                config=fixture["config"],
            ),
            HITL_SEMANTIC_PAGE_STALE,
        )
        changed_config = _RuntimeConfig(
            {**fixture["config"], "split-short-lines": True}
        )
        _expect_binding_error(
            lambda: load_bound_decisions(
                fixture["decisions_path"],
                source=fixture["source"],
                config=changed_config,
            ),
            HITL_SEMANTIC_PAGE_STALE,
        )


def check_legacy_missing_and_ambiguous_are_nonproductive() -> None:
    with tempfile.TemporaryDirectory(prefix="c20b-negative-") as folder:
        root = Path(folder)
        source = root / "Sample.pdf"
        config_path = root / "babeldoc.toml"
        review_path = root / "review.json"
        decisions_path = root / "decisions.json"
        output = root / "out"
        _make_pdf(source, ("alpha only",))
        config_path.write_text('[babeldoc]\nlang-in = "en"\n', encoding="utf-8")
        review = {
            "format_version": 3,
            "sample": "Sample",
            "page_kinds": [],
            "terms": [],
            "drop_caps": [],
        }
        decisions = {
            "format_version": 2,
            "sample": "Sample",
            "page_kinds": {},
            "terms": {"missing": "target"},
            "drop_caps": {},
        }
        _write_json(review_path, review)
        _write_json(decisions_path, decisions)
        _expect_binding_error(
            lambda: bind_legacy_files(
                source=source,
                config_path=config_path,
                review_path=review_path,
                decisions_path=decisions_path,
                output_dir=output,
            ),
            HITL_DECISION_REF_STALE,
        )
        assert not output.exists() or not any(output.iterdir())
        decisions["terms"] = {}
        decisions["page_kinds"] = {"1": "article_body"}
        review["page_kinds"] = [
            {"page": 1, "machine_kind": "article_body"},
            {"page": 1, "machine_kind": "toc"},
        ]
        _write_json(review_path, review)
        _write_json(decisions_path, decisions)
        _expect_binding_error(
            lambda: bind_legacy_files(
                source=source,
                config_path=config_path,
                review_path=review_path,
                decisions_path=decisions_path,
                output_dir=output,
            ),
            HITL_DECISION_AMBIGUOUS,
        )
        assert not output.exists() or not any(output.iterdir())


def check_bound_artifacts_are_immutable() -> None:
    with _bound_fixture() as fixture:
        bound = load_bound_decisions(
            fixture["decisions_path"],
            source=fixture["source"],
            config=fixture["config"],
        )
        report_path = fixture["output"] / f"Sample{BINDING_REPORT_SUFFIX}"
        report_path.write_bytes(report_path.read_bytes() + b" ")
        _expect_binding_error(
            lambda: verify_bound_artifacts(
                bound, source=fixture["source"], config=fixture["config"]
            ),
            HITL_BINDING_EVIDENCE_MISMATCH,
        )


BINDING_CHECKS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("v4 binding and standard outputs", check_v4_binding_and_standard_outputs),
    ("exact bind CLI interface", check_exact_bind_cli_interface),
    ("runtime loader and separate draft", check_runtime_loader_and_separate_draft),
    ("non-contiguous selected projection", check_noncontiguous_selected_projection),
    ("semantic config projection boundary", check_semantic_config_projection_boundary),
    (
        "legacy apply and detached evidence fail closed",
        check_legacy_apply_and_detached_evidence_fail_closed,
    ),
    (
        "candidate, lineage, and ref tamper fail closed",
        check_candidate_lineage_and_ref_tamper_fail_closed,
    ),
    ("source and config staleness", check_source_and_config_staleness),
    (
        "legacy missing/ambiguous are nonproductive",
        check_legacy_missing_and_ambiguous_are_nonproductive,
    ),
    ("bound artifacts are immutable", check_bound_artifacts_are_immutable),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("protocol", "binding", "all"),
        default="all",
        help="bounded phase to run",
    )
    args = parser.parse_args()
    checks = {
        "protocol": PROTOCOL_CHECKS,
        "binding": BINDING_CHECKS,
        "all": PROTOCOL_CHECKS + BINDING_CHECKS,
    }[args.phase]

    failures = 0
    print("HITL source-binding protocol checks")
    for label, check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - gate reports every assertion.
            failures += 1
            print(f"FAIL: {label}: {exc}")
        else:
            print(f"PASS: {label}")
    passed = len(checks) - failures
    print(f"RESULT: {passed}/{len(checks)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
