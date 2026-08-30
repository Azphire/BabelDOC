"""Gate: text_figure_overlap joins the closed vocabulary without moving it.

The minimal path counted six kinds of defect.  The paper claims nine, and the
first of the three new ones is text over artwork.  Wiring a detector into a
closed vocabulary is two separate promises, and this gate is here because only
the first of them is obvious:

  - the new detector reports what it says it reports, and stays silent where it
    says it stays silent; and
  - adding it changes nothing about the six findings that were already there.

The second is the one that can rot quietly.  The page detectors share one
DetectionContext and one paragraph list, and a detector that read a box, sorted
a list in place, or filed a note under a name another detector reads would move
the old evidence without anybody noticing until a repair acted on it.  So S3
runs detection twice over the same document -- once with the new detector in
the tuple and once with it taken out -- and requires the six old kinds to come
back byte for byte identical.  That is a stronger claim than comparing against
a constant frozen today, because a constant only catches the change that
happens after somebody writes it down.

Five claims:

S1  A paragraph sharing a figure's space at or above the declared floor is
    reported once, as text_figure_overlap, carrying the evidence the config
    says quantifies that kind.
S2  The same paragraph moved clear of the figure is not reported.  The floor is
    a floor and not a formality.
S3  The six pre-existing kinds detect identically with and without the new
    detector wired in.
S4  The vocabulary is nine kinds and every one of them carries a severity, a
    progress-evidence list, and a suggested action.  A kind that is declared
    without a weight cannot reach a report, and base.py already refuses to load
    such a config; this asserts the closure rather than trusting the loader.
S5  Detection writes nothing to the document.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import minimal_detection  # noqa: E402
from babeldoc.magazine.detectors import DETECTOR_NAMES  # noqa: E402
from babeldoc.magazine.detectors import detector_config  # noqa: E402
from babeldoc.magazine.detectors import overlap  # noqa: E402
from tests.minimal.fakes import _paragraph  # noqa: E402
from tests.minimal.fakes import document_digest  # noqa: E402
from tests.minimal.fakes import make_chain_fixture  # noqa: E402

# The six kinds the minimal path reported before this batch.  Named here so S3
# compares against the old vocabulary rather than against whatever the current
# one happens to be.
LEGACY_KINDS = (
    "untranslated_residue",
    "out_of_page",
    "text_text_collision",
    "fragment_cluster",
    "chain_conservation",
    "fixed_asset_drift",
)

# Where the figure stands on the fixture's first page, and the two places the
# probe paragraph is put: one squarely on the figure, one clear of it.
FIGURE_BOX = (10.0, 40.0, 70.0, 90.0)
ON_FIGURE = (12.0, 42.0, 68.0, 88.0)
OFF_FIGURE = (75.0, 5.0, 110.0, 20.0)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _fixture(work: Path, *, probe_box=None, with_figure: bool):
    """The shared chain fixture, optionally carrying artwork and a probe."""
    docs, article_ir, paragraphs, _translator = make_chain_fixture(
        "目标文本", work / "translator"
    )
    page = docs.page[0]
    if with_figure:
        page.pdf_figure = [
            il_version_1.PdfFigure(box=il_version_1.Box(*FIGURE_BOX))
        ]
    if probe_box is not None:
        page.pdf_paragraph.append(_paragraph("图上的文字", "probe", probe_box))
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


def _overlaps(result) -> list:
    return [issue for issue in result.issues if issue.kind == overlap.KIND]


def s1_overlapping_paragraph_is_reported(work: Path) -> str:
    docs, article_ir, baseline = _fixture(
        work, probe_box=ON_FIGURE, with_figure=True
    )
    found = _overlaps(_detect(work, docs, article_ir, baseline, name="s1"))
    _require(
        len(found) == 1,
        f"a paragraph on the figure raised {len(found)} overlap findings",
    )
    issue = found[0]
    config = detector_config()
    for field in config.progress_evidence[overlap.KIND]:
        _require(
            issue.evidence.get(field) is not None,
            f"the overlap finding carries no {field!r}, which the config says "
            f"quantifies it",
        )
    _require(
        issue.evidence["iou"] >= config.overlap_min_iou,
        f"the finding's iou {issue.evidence['iou']} is under the floor "
        f"{config.overlap_min_iou} it was raised at",
    )
    _require(
        issue.severity == config.severity[overlap.KIND],
        f"the finding carries severity {issue.severity!r}",
    )
    return (
        f"a paragraph over artwork is reported once as {overlap.KIND} at iou "
        f"{issue.evidence['iou']}"
    )


def s2_clear_paragraph_is_not_reported(work: Path) -> str:
    docs, article_ir, baseline = _fixture(
        work, probe_box=OFF_FIGURE, with_figure=True
    )
    found = _overlaps(_detect(work, docs, article_ir, baseline, name="s2"))
    _require(
        not found,
        f"a paragraph clear of the figure raised {len(found)} overlap findings",
    )
    return "a paragraph clear of the artwork raises nothing"


def _legacy_record(result, working_dir: Path) -> str:
    """The six old kinds' findings, in a form two runs can be compared by.

    A run names its own working directory inside chain-conservation evidence,
    and the two runs compared here must use different directories or the second
    would read the first's sidecar.  That path is a fact about the machine and
    not about the document, so it is folded to a constant before comparing;
    everything else is compared exactly as it was reported.
    """
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
    # Both the raw and the JSON-escaped spelling of the path can appear.
    for spelling in (json.dumps(str(working_dir))[1:-1], str(working_dir)):
        serialized = serialized.replace(spelling, "<working_dir>")
    return serialized


def s3_old_kinds_are_untouched(work: Path) -> str:
    detectors = minimal_detection._PAGE_DETECTORS
    _require(
        overlap in detectors,
        "the overlap detector is not wired into the page detectors",
    )
    without = tuple(module for module in detectors if module is not overlap)

    docs, article_ir, baseline = _fixture(
        work, probe_box=ON_FIGURE, with_figure=True
    )
    with_overlap = _legacy_record(
        _detect(work, docs, article_ir, baseline, name="s3-with"),
        work / "s3-with",
    )

    docs, article_ir, baseline = _fixture(
        work, probe_box=ON_FIGURE, with_figure=True
    )
    minimal_detection._PAGE_DETECTORS = without
    try:
        without_overlap = _legacy_record(
            _detect(work, docs, article_ir, baseline, name="s3-without"),
            work / "s3-without",
        )
    finally:
        minimal_detection._PAGE_DETECTORS = detectors

    _require(
        with_overlap == without_overlap,
        "wiring the overlap detector moved the six pre-existing findings:\n"
        f"  with:    {with_overlap}\n"
        f"  without: {without_overlap}",
    )
    count = len(json.loads(with_overlap))
    return (
        f"the {len(LEGACY_KINDS)} pre-existing kinds detect identically with "
        f"and without the new detector ({count} finding(s) compared)"
    )


def s4_vocabulary_is_closed_at_nine() -> str:
    config = detector_config()
    _require(
        len(DETECTOR_NAMES) == 9,
        f"the vocabulary declares {len(DETECTOR_NAMES)} kinds, not nine",
    )
    _require(
        set(DETECTOR_NAMES) == set(minimal_detection.ISSUE_KINDS),
        "the detector vocabulary and the detection vocabulary disagree: "
        f"{sorted(set(DETECTOR_NAMES) ^ set(minimal_detection.ISSUE_KINDS))}",
    )
    for kind in DETECTOR_NAMES:
        _require(kind in config.severity, f"{kind} carries no severity")
        _require(
            kind in config.progress_evidence,
            f"{kind} carries no progress evidence",
        )
        _require(
            kind in config.suggested_actions,
            f"{kind} carries no suggested action",
        )
    return (
        f"all {len(DETECTOR_NAMES)} kinds carry a severity, a progress-evidence "
        f"list, and a suggested action"
    )


def s5_detection_writes_nothing(work: Path) -> str:
    docs, article_ir, baseline = _fixture(
        work, probe_box=ON_FIGURE, with_figure=True
    )
    before = document_digest(docs)
    _detect(work, docs, article_ir, baseline, name="s5")
    _require(
        document_digest(docs) == before,
        "detection changed the document",
    )
    return "detection leaves the document byte for byte unchanged"


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        claims = [
            ("S1", lambda: s1_overlapping_paragraph_is_reported(work)),
            ("S2", lambda: s2_clear_paragraph_is_not_reported(work)),
            ("S3", lambda: s3_old_kinds_are_untouched(work)),
            ("S4", s4_vocabulary_is_closed_at_nine),
            ("S5", lambda: s5_detection_writes_nothing(work)),
        ]
        for name, claim in claims:
            try:
                print(f"{name}  OK  {claim()}")
            except AssertionError as error:
                print(f"{name}  FAIL  {error}")
                return 1
    print("spec_check_b12_t1a: all claims hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
