"""Gate: the residue detector reports which way a paragraph is set.

The census had a rotation branch keyed on ``record.vertical`` and nothing
anywhere assigned it, so the branch was dead and every rotated record was in
fact decided by a box-shape threshold declared for the census alone. The IL had
the fact the whole time -- ``vertical`` is declared in il_version_1.rnc and
paragraph_finder sets it from the paragraph's first character -- but no issue
ever put it in evidence. A judgement with no producer is the shape of defect
this repository has just finished removing once; this closes the second one.

The detector's behaviour does not change. It reports one more thing about what
it already found, and no threshold in it reads the new field.

What does change is the census. A record that carries the flag is classified on
the flag, and the box shape is not consulted for it -- including when the flag
says the paragraph is horizontal and the box is tall and narrow, which is a
column of ordinary text and not a rotation. The threshold survives only for
records that have no flag to read: every population B record comes from the
coverage ledger with no issue behind it, and artifacts written before this
change carry no ``vertical`` either. Which of the two decided a record is
recorded in its ``criterion``.

Five claims:

1  The detector puts ``vertical`` in evidence, and its value is the paragraph's
   own -- true, false, or absent where the IL never said.
2  A record whose evidence says vertical is rotated, by the flag.
3  A record whose evidence says horizontal is not rotated, even where the box
   shape would have said otherwise. Evidence overrules shape.
4  A record with no evidence still falls through to the shape, unchanged.
5  The six frozen b11.12 artifacts census identically. They predate the field,
   so nothing about them may move.

Run offline; no network, no translator request.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import residue_census  # noqa: E402
from babeldoc.magazine import minimal_detection  # noqa: E402
from tests.minimal.fakes import make_chain_fixture  # noqa: E402

BASELINE = ROOT / "examples/output/b11.12/full"
FROZEN_CENSUS = BASELINE / "census/residue_census.json"
SAMPLES = (
    "AramcoWorld-en-v2",
    "Courier-en",
    "FD-en-v2",
    "Courier-zh",
    "WIPO-zh",
    "bull-zh",
)
# The census numbers frozen by b11.12 report section 10.
FROZEN_TOTALS = {"A": 58, "B": 90, "A&B": 27, "S": 28, "total": 149}

results: list[str] = []


def record(ok: bool, label: str, detail: str = "") -> None:
    results.append(f"{'pass' if ok else 'FAIL'} {label}" + (f": {detail}" if detail else ""))


def _residue_evidence(work: Path, vertical) -> list[dict]:
    """Run the real detector over a document whose paragraphs are set as given."""
    docs, article_ir, _paragraphs, _translator = make_chain_fixture(
        "目标文本", work / "translator"
    )
    for page in docs.page:
        for paragraph in page.pdf_paragraph or ():
            paragraph.vertical = vertical
    baseline = minimal_detection.capture_baseline(
        docs,
        article_ir,
        labeled_pages=((7, docs.page[0]), (8, docs.page[1])),
    )
    result = minimal_detection.detect(
        docs,
        article_ir,
        baseline,
        language="zh",
        translation_performed=True,
        working_dir=work / "detect",
        sidecar_name="issues.before.json",
        pass_index=0,
    )
    return [
        issue["evidence"]
        for issue in result.record["issues"]
        if issue["kind"] == "untranslated_residue"
    ]


def claim_1() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seen = {}
        for setting in (True, False, None):
            evidence = _residue_evidence(Path(raw) / str(setting), setting)
            if not evidence:
                record(False, "1 evidence carries vertical", "no residue issue found")
                return
            seen[setting] = {item.get("vertical") for item in evidence}
            if any("vertical" not in item for item in evidence):
                record(False, "1 evidence carries vertical", f"key absent for {setting!r}")
                return
    ok = seen == {True: {True}, False: {False}, None: {None}}
    record(ok, "1 evidence carries vertical", f"reported {seen}")


def _record(**kwargs) -> residue_census.Record:
    item = residue_census.Record(
        sample="probe",
        direction="en-zh",
        physical_ref="p1#0",
        runtime_ref="p1#0",
        physical_page=1,
    )
    for key, value in kwargs.items():
        setattr(item, key, value)
    return item


def _classify(**kwargs) -> residue_census.Record:
    item = _record(**kwargs)
    residue_census.classify(item, min_text_length=5, is_short_unit=False)
    return item


def claim_2() -> None:
    # A tall narrow box as well, so the flag is not merely agreeing with shape.
    item = _classify(vertical=True, aspect_ratio=0.1, source_chars=40, tracking_rows=1)
    ok = item.category == residue_census.ROTATED and item.criterion == "paragraph.vertical"
    record(ok, "2 vertical evidence rotates", f"{item.category} by {item.criterion!r}")


def claim_3() -> None:
    # The shape alone would have called this rotated; the flag says otherwise
    # and the flag wins, so the record lands wherever it truly belongs.
    shape_only = _classify(vertical=None, aspect_ratio=0.1, source_chars=40, tracking_rows=1)
    item = _classify(vertical=False, aspect_ratio=0.1, source_chars=40, tracking_rows=1)
    ok = (
        shape_only.category == residue_census.ROTATED
        and item.category != residue_census.ROTATED
        and "aspect_ratio" not in item.criterion
    )
    record(
        ok,
        "3 horizontal evidence overrules shape",
        f"shape-only={shape_only.category}, with-evidence={item.category} "
        f"by {item.criterion!r}",
    )


def claim_4() -> None:
    # A population B record has no issue, so no evidence, so the shape stands.
    item = _classify(vertical=None, aspect_ratio=0.1, source_chars=40, tracking_rows=1)
    ok = (
        item.category == residue_census.ROTATED
        and item.criterion == f"aspect_ratio<{residue_census.ROTATED_MAX_ASPECT}"
    )
    record(ok, "4 no evidence keeps the shape fallback", f"{item.category} by {item.criterion!r}")


def claim_5() -> None:
    if not FROZEN_CENSUS.is_file():
        record(False, "5 frozen census unchanged", f"missing {FROZEN_CENSUS}")
        return
    with tempfile.TemporaryDirectory() as raw:
        out = Path(raw) / "census"
        code = residue_census.main(
            [str(BASELINE / sample) for sample in SAMPLES] + ["--out", str(out)]
        )
        if code != 0:
            record(False, "5 frozen census unchanged", f"census exited {code}")
            return
        fresh = json.loads((out / "residue_census.json").read_text(encoding="utf-8"))
    frozen = json.loads(FROZEN_CENSUS.read_text(encoding="utf-8"))
    # ``run_dir`` echoes the path the census was invoked with, so it moves with
    # the caller and not with the census. Everything else must be identical.
    for payload in (fresh, frozen):
        for run in payload["runs"]:
            run["run_dir"] = Path(run.pop("run_dir")).name
    rows = [row for run in fresh["runs"] for row in run["records"]]
    totals = {
        "A": sum("A" in row["populations"] for row in rows),
        "B": sum("B" in row["populations"] for row in rows),
        "A&B": sum(
            "A" in row["populations"] and "B" in row["populations"] for row in rows
        ),
        "S": sum("S" in row["populations"] for row in rows),
        "total": len(rows),
    }
    identical = fresh == frozen
    carried = sum(row["vertical"] is not None for row in rows)
    ok = identical and totals == FROZEN_TOTALS and carried == 0
    record(
        ok,
        "5 frozen census unchanged",
        f"identical={identical}, totals={totals}, records carrying vertical={carried}",
    )


def main() -> int:
    claim_1()
    claim_2()
    claim_3()
    claim_4()
    claim_5()
    for line in results:
        print(line)
    failed = [line for line in results if line.startswith("FAIL")]
    print(f"\n{len(results) - len(failed)}/{len(results)} claims hold")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
