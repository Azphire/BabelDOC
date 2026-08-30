"""Gate: abnormal_blank measures ink against its box, and knows where to stop.

The donor detector answered this question from a RunTrace nothing in this
repository builds, so it could never have reported anything here.  It is
re-seated on what the minimal path actually produces: the characters a
paragraph was laid out as, the box the layout stage gave it, and the article
membership the canonical ArticleIR already knows.

The whole risk of that reseating is false positives, because a paragraph that
does not fill its box is usually correct.  An article ends somewhere, and the
member it ends on is short by design.  So the detector excludes the last member
an article has on a page, and S2 is the claim that carries the batch: the same
under-filled geometry that is reported in the middle of an article is silent at
the end of one.  If S1 passed and S2 did not, the detector would report every
article's last paragraph on every page of every sample and the finding would
mean nothing.

Six claims:

S1  A member in the middle of an article whose ink fills less of its box than
    the declared floor, leaving a hole worth a declared share of the page, is
    reported once with both declared dimensions.
S2  The article's last member on that page, under-filled by exactly the same
    geometry, is not reported.
S3  Moving the ink back up over the fill floor silences S1's finding.  The
    floor is a floor.
S4  Both declared dimensions count blank rather than fill, so that a smaller
    number is always the better document -- which is the direction
    acceptance.py compares severity vectors in.
S5  The six pre-existing kinds detect identically with and without this
    detector wired in.
S6  Detection writes nothing to the document.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import minimal_detection  # noqa: E402
from babeldoc.magazine.detectors import abnormal_blank  # noqa: E402
from babeldoc.magazine.detectors import detector_config  # noqa: E402
from tests.minimal.fakes import document_digest  # noqa: E402
from tests.minimal.fakes import make_chain_fixture  # noqa: E402
from tools.spec_check_b12_t1a import LEGACY_KINDS  # noqa: E402

# The fixture page is 120 x 100, so 12000 square points.  Each of the two
# members on it is given a box of 110 x 45 -- 4950 points, comfortably over the
# fifth of the page the area floor asks for -- so that the only thing separating
# the reported case from the silent one is which member of the article it is.
PAGE_AREA = 120.0 * 100.0
UPPER_BOX = (0.0, 50.0, 110.0, 95.0)
LOWER_BOX = (0.0, 0.0, 110.0, 45.0)
BOXES = (UPPER_BOX, LOWER_BOX, UPPER_BOX, LOWER_BOX)

# 900 points of ink in a 4950 point box is a fill of 0.18, under the 0.2 floor,
# and leaves 4050 points blank, which is 0.34 of the page and over that floor.
SPARSE_INK = {0: (2.0, 52.0, 32.0, 82.0), 1: (2.0, 2.0, 32.0, 32.0)}
# 4000 points of ink in the same box is a fill of 0.81, well clear of the floor.
FULL_INK = {0: (2.0, 52.0, 102.0, 92.0), 1: (2.0, 2.0, 102.0, 42.0)}

MIDDLE_REF = "p7#0"  # reading order 0 of article-a on physical page 7
LAST_REF = "p7#1"  # reading order 1, the last member the article has there


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _lay_out(paragraph, box) -> None:
    """Replace a fixture paragraph's composition with ink filling ``box``.

    The fake paragraphs carry a unicode run, which is text nothing has laid out
    yet; ``rendered_box`` falls back to the paragraph's own box for those and
    the measurement would be vacuously perfect.  Two characters spanning the
    given rectangle give the detector real ink to measure.
    """
    left, bottom, right, top = box
    middle = (left + right) / 2
    paragraph.pdf_paragraph_composition = [
        il_version_1.PdfParagraphComposition(
            pdf_character=il_version_1.PdfCharacter(
                box=il_version_1.Box(left, bottom, middle, top),
                char_unicode="文",
            )
        ),
        il_version_1.PdfParagraphComposition(
            pdf_character=il_version_1.PdfCharacter(
                box=il_version_1.Box(middle, bottom, right, top),
                char_unicode="字",
            )
        ),
    ]


def _fixture(work: Path, ink):
    docs, article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", work / "translator", boxes=BOXES
    )
    for index, box in ink.items():
        _lay_out(docs.page[0].pdf_paragraph[index], box)
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )
    return docs, article_ir, baseline


def _detect(work: Path, docs, article_ir, baseline, *, name: str):
    return minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=True,
        working_dir=work / name,
        sidecar_name="issues.before.json",
        pass_index=0,
    )


def _blanks(result) -> list:
    return [
        issue for issue in result.issues if issue.kind == abnormal_blank.KIND
    ]


def _run(work: Path, ink, *, name: str):
    docs, article_ir, baseline = _fixture(work, ink)
    return docs, _detect(work, docs, article_ir, baseline, name=name)


def s1_underfilled_middle_member_is_reported(work: Path) -> str:
    _docs, result = _run(work, SPARSE_INK, name="s1")
    found = _blanks(result)
    _require(
        len(found) == 1,
        f"an under-filled article member raised {len(found)} findings, "
        f"not one: {[issue.paragraph_refs for issue in found]}",
    )
    issue = found[0]
    _require(
        issue.paragraph_refs == (MIDDLE_REF,),
        f"the finding names {issue.paragraph_refs}, not the middle member",
    )
    config = detector_config()
    for field in config.progress_evidence[abnormal_blank.KIND]:
        _require(
            isinstance(issue.evidence.get(field), int | float),
            f"the finding carries no numeric {field!r}, which the config says "
            f"quantifies this kind",
        )
    _require(
        issue.evidence["fill_ratio"] < config.abnormal_blank_min_capacity_ratio,
        f"the finding's fill {issue.evidence['fill_ratio']} is not under the "
        f"floor {config.abnormal_blank_min_capacity_ratio}",
    )
    _require(
        issue.evidence["blank_area_ratio"]
        >= config.abnormal_blank_min_area_ratio,
        f"the finding's blank share {issue.evidence['blank_area_ratio']} is "
        f"under the floor {config.abnormal_blank_min_area_ratio}",
    )
    _require(
        issue.evidence["article_id"] == "article-a",
        f"the finding names article {issue.evidence['article_id']!r}",
    )
    return (
        f"a mid-article member filling {issue.evidence['fill_ratio']} of its "
        f"box is reported, leaving {issue.evidence['blank_area_ratio']} of the "
        f"page blank"
    )


def s2_last_member_on_the_page_is_silent(work: Path) -> str:
    _docs, result = _run(work, SPARSE_INK, name="s2")
    named = {ref for issue in _blanks(result) for ref in issue.paragraph_refs}
    _require(
        LAST_REF not in named,
        f"the article's last member on the page was reported: {sorted(named)}",
    )
    # The exclusion has to be the reason, not an accident of the geometry: both
    # members were given the same box area and the same ink area.
    docs, _article_ir, _baseline = _fixture(work, SPARSE_INK)
    boxes = [
        docs.page[0].pdf_paragraph[index].box for index in (0, 1)
    ]
    areas = [
        (float(box.x2) - float(box.x)) * (float(box.y2) - float(box.y))
        for box in boxes
    ]
    _require(
        abs(areas[0] - areas[1]) < 1e-9,
        f"the two members were not given equal boxes: {areas}",
    )
    return (
        f"the article's last member on the page, under-filled in an equal "
        f"{areas[1]:.0f}-point box, raises nothing"
    )


def s3_filled_box_is_silent(work: Path) -> str:
    _docs, result = _run(work, FULL_INK, name="s3")
    found = _blanks(result)
    _require(
        not found,
        f"a member filling its box raised {len(found)} blank findings",
    )
    return "a member whose ink fills its box raises nothing"


def s4_dimensions_count_blank_not_fill(work: Path) -> str:
    _docs, sparse = _run(work, SPARSE_INK, name="s4-sparse")
    issue = _blanks(sparse)[0]
    config = detector_config()
    fields = config.progress_evidence[abnormal_blank.KIND]
    _require(
        set(fields) == {"blank_area_ratio", "blank_capacity_ratio"},
        f"the declared dimensions are {fields}",
    )
    # A better document is a fuller box, and a fuller box has to score lower on
    # every declared dimension, because acceptance.py reads any rise as a
    # worsening.
    _require(
        abs(
            issue.evidence["blank_capacity_ratio"]
            + issue.evidence["fill_ratio"]
            - 1.0
        )
        < 1e-6,
        "blank_capacity_ratio is not the complement of fill_ratio: "
        f"{issue.evidence['blank_capacity_ratio']} + "
        f"{issue.evidence['fill_ratio']}",
    )
    _require(
        issue.evidence["blank_capacity_ratio"] > 0.5,
        "a nearly empty box should score high on a dimension counting blank, "
        f"and scores {issue.evidence['blank_capacity_ratio']}",
    )
    return (
        "both dimensions count blank, so a fuller box scores lower on each, "
        "which is the direction acceptance compares them in"
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
    detectors = minimal_detection._PAGE_DETECTORS
    _require(
        abnormal_blank in detectors,
        "the abnormal_blank detector is not wired into the page detectors",
    )
    without = tuple(
        module for module in detectors if module is not abnormal_blank
    )
    _docs, result = _run(work, SPARSE_INK, name="s5-with")
    with_blank = _legacy_record(result, work / "s5-with")

    minimal_detection._PAGE_DETECTORS = without
    try:
        _docs, result = _run(work, SPARSE_INK, name="s5-without")
        without_blank = _legacy_record(result, work / "s5-without")
    finally:
        minimal_detection._PAGE_DETECTORS = detectors

    _require(
        with_blank == without_blank,
        "wiring abnormal_blank moved the six pre-existing findings:\n"
        f"  with:    {with_blank}\n"
        f"  without: {without_blank}",
    )
    count = len(json.loads(with_blank))
    return (
        f"the {len(LEGACY_KINDS)} pre-existing kinds detect identically with "
        f"and without this detector ({count} finding(s) compared)"
    )


def s6_detection_writes_nothing(work: Path) -> str:
    docs, article_ir, baseline = _fixture(work, SPARSE_INK)
    before = document_digest(docs)
    _detect(work, docs, article_ir, baseline, name="s6")
    _require(document_digest(docs) == before, "detection changed the document")
    return "detection leaves the document byte for byte unchanged"


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        claims = [
            ("S1", lambda: s1_underfilled_middle_member_is_reported(work)),
            ("S2", lambda: s2_last_member_on_the_page_is_silent(work)),
            ("S3", lambda: s3_filled_box_is_silent(work)),
            ("S4", lambda: s4_dimensions_count_blank_not_fill(work)),
            ("S5", lambda: s5_old_kinds_are_untouched(work)),
            ("S6", lambda: s6_detection_writes_nothing(work)),
        ]
        for name, claim in claims:
            try:
                print(f"{name}  OK  {claim()}")
            except AssertionError as error:
                print(f"{name}  FAIL  {error}")
                return 1
    print("spec_check_b12_t1b: all claims hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
