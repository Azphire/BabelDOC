"""Gate: instruction_compliance reports human rulings the document lost.

The donor detector read a RunTrace that nothing builds, so it answered about
joint-call counts and rollback generations that this pipeline never records.
The human constraint the minimal path actually carries is the HITL decisions
file, and this detector is re-seated on that: a ruled term, a ruled drop-cap
verdict, a ruled page kind, each checked against the finished document.

The claim that matters is S2.  A compliance detector that fires on compliant
input is worse than no detector, because every downstream count becomes noise;
and the shape of this check makes that easy to get wrong, since a ruling is
*supposed* to differ from what the machine decided on its own.  So each rule is
exercised twice over the same fixture, once with the ruling honoured and once
with it lost, and only the second may report.

Seven claims:

S1  A ruled term whose page carried the source and whose finished text does not
    carry the target is reported, once, under term_adoption.
S2  The same fixture with every ruling honoured reports nothing at all.
S3  A lost drop-cap verdict and a lost page kind are each reported under their
    own rule name, and the evidence says both what was ruled and what the
    document carries, so a reader can tell "never landed" from "landed and was
    overwritten".
S4  A sample with no decisions file is not a violation and not an error: zero
    findings and a typed skip naming the absent file.
S5  The six pre-existing kinds detect identically with and without this
    detector wired in.
S6  The detector names no sample, no publication and no page anchor.  What it
    reports has to come from the decisions file it was handed, not from
    knowledge of which document it is reading.
S7  Detection writes nothing to the document.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.glossary import Glossary  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import minimal_detection  # noqa: E402
from babeldoc.magazine.detectors import instruction_compliance  # noqa: E402
from tests.minimal.fakes import document_digest  # noqa: E402
from tests.minimal.fakes import make_chain_fixture  # noqa: E402
from tools.spec_check_b12_t1a import LEGACY_KINDS  # noqa: E402

# Distinctive, and put on page 7 only, so the term claim also tests that a
# ruling is judged per page rather than across the document.
RULED_TERM_SOURCE = "ruled term"
RULED_TERM_TARGET = "标的译名"
RULED_DROP_CAP = "p7#0"
RULED_DROP_CAP_DECISION = "merge"
RULED_PAGE = 7
RULED_PAGE_KIND = "article_body"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _decisions(tmp: Path) -> hitl.Decisions:
    return hitl.Decisions(
        path=tmp / "fixture.decisions.json",
        terms={RULED_TERM_SOURCE: RULED_TERM_TARGET},
        page_kinds={RULED_PAGE: RULED_PAGE_KIND},
        drop_caps={
            RULED_DROP_CAP: hitl.DropCapRuling(
                reference=RULED_DROP_CAP,
                physical_page=RULED_PAGE,
                paragraph_index=0,
                decision=RULED_DROP_CAP_DECISION,
                raw=None,
            )
        },
    )


def _state(docs, decisions, *, applied: bool) -> hitl.HitlRunState:
    """The review state a run would hand detection, honoured or lost.

    ``applied`` says whether the rulings reached the document.  Both spellings
    build the same rulings over the same pages, so the only difference between
    the reported and the silent case is compliance itself.
    """
    report = {"applied": {"drop_caps": [], "page_kinds": []}, "skipped": []}
    if applied:
        report["applied"]["drop_caps"] = [
            {"paragraph": RULED_DROP_CAP, "decision": RULED_DROP_CAP_DECISION}
        ]
        report["applied"]["page_kinds"] = [
            {"page": RULED_PAGE, "kind": RULED_PAGE_KIND}
        ]
    return hitl.HitlRunState(
        docs_identity=id(docs),
        sample="fixture",
        total_pages=len(docs.page),
        selected_physical_pages=(7, 8),
        physical_to_local={7: 1, 8: 2},
        translator_identity=0,
        term_translator_identity=0,
        pipeline_ready=True,
        decisions_loaded=True,
        decisions=decisions,
        report=report,
        source_text_pages=tuple(
            (
                label,
                Glossary.normalize_source(
                    "\n".join(
                        paragraph.unicode or ""
                        for paragraph in (page.pdf_paragraph or ())
                    )
                ),
            )
            for label, page in ((7, docs.page[0]), (8, docs.page[1]))
        ),
    )


def _set_text(paragraph, text: str) -> None:
    """Set both spellings of a fixture paragraph's text.

    The source side of a term ruling is captured from ``unicode`` and the
    finished side is read off the composition, so a fixture that moved only one
    of them would make the honoured case unreachable.
    """
    paragraph.unicode = text
    holder = paragraph.pdf_paragraph_composition[0]
    holder.pdf_same_style_unicode_characters.unicode = text


def _fixture(work: Path, *, honoured: bool, decisions=True):
    docs, article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", work / "translator"
    )
    # The ruled source stands on page 7 and nowhere else, in both spellings of
    # the fixture, so the only thing that varies is whether the target followed.
    carried = f"source member {RULED_TERM_SOURCE}"
    if honoured:
        # The ruled term reaches the page, the ruled verdict reaches the
        # paragraph, and the ruled kind reaches the page.
        carried = f"{carried} {RULED_TERM_TARGET}"
        docs.page[0].pdf_paragraph[0].drop_cap_decision = RULED_DROP_CAP_DECISION
        docs.page[0].page_kind = RULED_PAGE_KIND
    _set_text(docs.page[0].pdf_paragraph[0], carried)
    ruled = _decisions(work) if decisions else None
    state = _state(docs, ruled, applied=honoured)
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )
    return docs, article_ir, baseline, state


def _detect(work: Path, docs, article_ir, baseline, state, *, name: str):
    return minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=True,
        working_dir=work / name,
        sidecar_name="issues.before.json",
        pass_index=0,
        hitl_state=state,
    )


def _compliance(result) -> list:
    return [
        issue
        for issue in result.issues
        if issue.kind == instruction_compliance.KIND
    ]


def _by_rule(result) -> dict[str, list]:
    rules: dict[str, list] = {}
    for issue in _compliance(result):
        rules.setdefault(issue.evidence["instruction"], []).append(issue)
    return rules


def _run(work: Path, *, honoured: bool, decisions=True, name: str):
    docs, article_ir, baseline, state = _fixture(
        work, honoured=honoured, decisions=decisions
    )
    return _detect(work, docs, article_ir, baseline, state, name=name)


def s1_lost_term_is_reported(work: Path) -> str:
    rules = _by_rule(_run(work, honoured=False, name="s1"))
    found = rules.get(instruction_compliance.RULE_TERM, [])
    _require(
        len(found) == 1,
        f"a lost term ruling raised {len(found)} findings, not one",
    )
    detail = found[0].evidence["detail"]
    _require(
        detail["source"] == RULED_TERM_SOURCE
        and detail["target"] == RULED_TERM_TARGET,
        f"the finding names {detail}",
    )
    _require(
        found[0].page == RULED_PAGE,
        f"the finding is filed against page {found[0].page}",
    )
    pages = {issue.page for issue in found}
    _require(
        pages == {RULED_PAGE},
        f"the ruling was reported against pages {sorted(pages)}, and the page "
        f"that never carried the source should not be among them",
    )
    return (
        f"a page carrying the ruled source without the ruled target is "
        f"reported under {instruction_compliance.RULE_TERM}"
    )


def s2_honoured_rulings_report_nothing(work: Path) -> str:
    found = _compliance(_run(work, honoured=True, name="s2"))
    _require(
        not found,
        "rulings the document honoured were reported anyway: "
        + str(
            [
                (issue.evidence["instruction"], issue.evidence["detail"])
                for issue in found
            ]
        ),
    )
    return "every ruling honoured by the document reports nothing"


def s3_lost_drop_cap_and_page_kind_are_reported(work: Path) -> str:
    rules = _by_rule(_run(work, honoured=False, name="s3"))
    for rule in (
        instruction_compliance.RULE_DROP_CAP,
        instruction_compliance.RULE_PAGE_KIND,
    ):
        found = rules.get(rule, [])
        _require(len(found) == 1, f"{rule} raised {len(found)} findings, not one")
        detail = found[0].evidence["detail"]
        _require(
            "ruled" in detail and "carried_by_document" in detail,
            f"{rule} evidence does not say what was ruled and what is carried: "
            f"{detail}",
        )
        _require(
            detail["ruled"] != detail["carried_by_document"],
            f"{rule} reported a ruling the document carries: {detail}",
        )
    _require(
        set(rules) == set(instruction_compliance.RULES),
        f"the lost fixture reported rules {sorted(rules)}, not all three",
    )
    return (
        "a lost drop-cap verdict and a lost page kind are each reported under "
        "their own rule, saying what was ruled and what the document carries"
    )


def s4_absent_decisions_file_is_a_typed_skip(work: Path) -> str:
    result = _run(work, honoured=False, decisions=False, name="s4")
    _require(
        not _compliance(result),
        "a sample with no decisions file reported a compliance violation",
    )
    rows = result.record["detector_records"].get(instruction_compliance.NAME, [])
    skips = [row for row in rows if row.get("status") == "skipped"]
    _require(
        len(skips) == 1,
        f"the absent decisions file left {len(skips)} typed skips",
    )
    _require(
        skips[0]["reason"] == instruction_compliance.SKIP_NO_DECISIONS
        and skips[0]["typed"] is True,
        f"the skip is recorded as {skips[0]}",
    )
    return (
        f"a sample with no decisions file reports nothing and records a typed "
        f"skip of {skips[0]['reason']!r}"
    )


def _legacy_record(result, working_dir: Path) -> str:
    rows = [
        {
            "kind": issue.kind,
            "page": issue.page,
            "paragraph_refs": list(issue.paragraph_refs),
            "severity": issue.severity,
            "evidence": issue.evidence,
            "geometry": issue.geometry,
        }
        for issue in result.issues
        if issue.kind in LEGACY_KINDS
    ]
    serialized = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    for spelling in (json.dumps(str(working_dir))[1:-1], str(working_dir)):
        serialized = serialized.replace(spelling, "<working_dir>")
    return serialized


def s5_old_kinds_are_untouched(work: Path) -> str:
    with_it = _legacy_record(
        _run(work, honoured=False, name="s5-with"), work / "s5-with"
    )
    original = instruction_compliance.detect
    instruction_compliance.detect = lambda context: []
    try:
        without = _legacy_record(
            _run(work, honoured=False, name="s5-without"), work / "s5-without"
        )
    finally:
        instruction_compliance.detect = original
    _require(
        with_it == without,
        "wiring instruction_compliance moved the six pre-existing findings:\n"
        f"  with:    {with_it}\n"
        f"  without: {without}",
    )
    return (
        f"the {len(LEGACY_KINDS)} pre-existing kinds detect identically with "
        f"and without this detector ({len(json.loads(with_it))} compared)"
    )


def s6_detector_names_no_sample_or_anchor() -> str:
    """The module may not know which document it is reading.

    The forbidden words are taken from the corpus and the review directory as
    they stand, so a sample added later is audited without this gate being
    edited.
    """
    source = Path(
        instruction_compliance.__file__
    ).read_text(encoding="utf-8")
    names = set()
    for directory, suffix in (
        (ROOT / "examples/input", ".pdf"),
        (ROOT / "reviews", ".json"),
    ):
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            if item.suffix.lower() == suffix:
                names.add(item.name.split(".")[0])
    _require(bool(names), "no sample names were found to audit against")
    named = sorted(name for name in names if name and name in source)
    _require(not named, f"the detector names samples {named}")
    anchors = re.findall(r"[\"']p[0-9]+#[0-9]+[\"']", source)
    _require(not anchors, f"the detector carries page anchors {anchors}")
    return (
        f"the detector names none of the {len(names)} known samples and carries "
        f"no page anchor"
    )


def s7_detection_writes_nothing(work: Path) -> str:
    docs, article_ir, baseline, state = _fixture(work, honoured=False)
    before = document_digest(docs)
    _detect(work, docs, article_ir, baseline, state, name="s7")
    _require(document_digest(docs) == before, "detection changed the document")
    return "detection leaves the document byte for byte unchanged"


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        claims = [
            ("S1", lambda: s1_lost_term_is_reported(work)),
            ("S2", lambda: s2_honoured_rulings_report_nothing(work)),
            ("S3", lambda: s3_lost_drop_cap_and_page_kind_are_reported(work)),
            ("S4", lambda: s4_absent_decisions_file_is_a_typed_skip(work)),
            ("S5", lambda: s5_old_kinds_are_untouched(work)),
            ("S6", s6_detector_names_no_sample_or_anchor),
            ("S7", lambda: s7_detection_writes_nothing(work)),
        ]
        for name, claim in claims:
            try:
                print(f"{name}  OK  {claim()}")
            except AssertionError as error:
                print(f"{name}  FAIL  {error}")
                return 1
    print("spec_check_b12_t1c: all claims hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
