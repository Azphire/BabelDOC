"""Gate for the demo verifier's skip adjudication and chain scoping.

Two holes are closed here and each is checked from both sides.

The first is ownership. Two passes take a paragraph out of the page batch and
each writes its own skip record; before this gate the verifier knew only about
the chain pass, so a short unit's record arrived as ``('', None)`` and was
rejected as unadjudicated. Ownership is now read off ``taken_by`` and each
owner is judged against the evidence that owner actually leaves behind.

The second is scope. The detector walks the whole document while the frozen
truth is authored over the staged pages, so a chain outside that scope has no
truth to be judged against. It is skipped and counted, never waved through
silently, and a chain that straddles the boundary is a hard failure because
the truth covers only part of it.

The symbolic cases mutate a real sample's reports so the verifier is exercised
through its own front door; the end-to-end cases then run the five registered
samples and the frozen control.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from verify_magazine_demo import VerificationError  # noqa: E402
from verify_magazine_demo import main as verify_main  # noqa: E402
from verify_magazine_demo import verify_chain  # noqa: E402

BASELINE = ROOT / "examples/output/b11.12/full"
CONTROL = ROOT / "examples/output/fix0829"
MATRIX = json.loads(
    (ROOT / "tests/fixtures/demo/sample_matrix.json").read_text(encoding="utf-8")
)
SAMPLES = {sample["sample_id"]: sample for sample in MATRIX}
TRANSLATION_REPORT = "chain_translation.report.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class Case:
    """One sample's artifacts, copied so a case can rewrite them freely."""

    def __init__(self, stack, sample_id: str, run: Path = BASELINE):
        self.sample = SAMPLES[sample_id]
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.work = self.root / "work"
        shutil.copytree(run / sample_id / "work" / sample_id, self.work)
        self.expectations = self.root / "expectations.json"
        shutil.copyfile(ROOT / self.sample["expectations_path"], self.expectations)
        self.output = next((run / sample_id).glob("*.mono.pdf"))

    def translation(self) -> dict:
        return _read(self.work / TRANSLATION_REPORT)

    def put_translation(self, payload: dict) -> None:
        _write(self.work / TRANSLATION_REPORT, payload)

    def put_expectations(self, payload: dict) -> None:
        _write(self.expectations, payload)

    def run(self) -> dict:
        return verify_chain(
            self.expectations,
            ROOT / self.sample["source_path"],
            self.output,
            self.work,
            self.sample["source_lang"],
            self.sample["target_lang"],
        )


def _skips(report: dict, owner: str) -> list[dict]:
    return [item for item in report["skips"] if item["taken_by"] == owner]


def _expect_failure(case: Case, fragment: str, label: str) -> str:
    try:
        case.run()
    except VerificationError as error:
        if fragment not in str(error):
            return f"FAIL {label}: expected {fragment!r}, got {str(error)!r}"
        return f"pass {label}: {error}"
    return f"FAIL {label}: no error raised"


def _drop_page(case: Case, page: int) -> dict:
    """Narrow the declared scope, and the truth with it, by one page."""
    expectations = _read(case.expectations)
    expectations["stage_pages"] = [
        item for item in expectations["stage_pages"] if item != page
    ]
    expectations["chains"] = [
        chain
        for chain in expectations["chains"]
        if all(member["physical_page"] != page for member in chain["ordered_members"])
    ]
    case.put_expectations(expectations)
    return expectations


def symbolic(stack) -> list[str]:
    lines = []

    # 1. A report with chain skips only is adjudicated exactly as before.
    case = Case(stack, "Courier-en")
    report = case.translation()
    report["skips"] = _skips(report, "chain")
    report["short_units"] = None
    case.put_translation(report)
    result = case.run()
    before = {k: v for k, v in result.items() if k not in {"out_of_scope_chains", "short_unit_skips"}}
    ok = before == {
        "check": "chain",
        "sample_id": "Courier-en",
        "chains": 6,
        "members": 12,
        "status": "pass",
    } and result["short_unit_skips"] == 0 and result["out_of_scope_chains"] == 0
    lines.append(f"{'pass' if ok else 'FAIL'} 1 chain-only report unchanged: {before}")

    # 2. n short unit skips against an admitted count of n.
    case = Case(stack, "Courier-en")
    report = case.translation()
    admitted = report["short_units"]["admitted"]
    count = len(_skips(report, "short_unit"))
    result = case.run()
    ok = admitted == count == result["short_unit_skips"] == 1
    lines.append(f"{'pass' if ok else 'FAIL'} 2 admitted={admitted} skips={count}")

    # 3. One admitted unit too many.
    case = Case(stack, "Courier-en")
    report = case.translation()
    report["short_units"]["admitted"] += 1
    case.put_translation(report)
    lines.append(
        _expect_failure(
            case, "short unit skips do not cover every admitted unit", "3 admitted n+1"
        )
    )

    # 4. A short unit record that carries a chain identity.
    case = Case(stack, "Courier-en")
    report = case.translation()
    for item in report["skips"]:
        if item["taken_by"] == "short_unit":
            item["chain_id"] = "borrowed"
    case.put_translation(report)
    lines.append(
        _expect_failure(case, "short unit skip carries chain identity", "4 chain id set")
    )

    # 5. A short unit the page batch is recorded as having asked for. The page
    #    batch applies its length floor before it ever asks the claim, and a
    #    short unit is by definition below that floor, so a decline here means
    #    the record is wrong -- the inverse of the chain side's proof.
    case = Case(stack, "Courier-en")
    report = case.translation()
    for item in report["skips"]:
        if item["taken_by"] == "short_unit":
            item["declined_by"] = ["page_batch"]
    case.put_translation(report)
    lines.append(
        _expect_failure(
            case, "refused a producer it never reached", "5 short unit declined"
        )
    )

    # 6. A third owner is never waved through.
    case = Case(stack, "Courier-en")
    report = case.translation()
    for item in report["skips"]:
        if item["taken_by"] == "short_unit":
            item["taken_by"] = "mystery"
    case.put_translation(report)
    lines.append(_expect_failure(case, "unknown skip owner", "6 unknown owner"))

    # 7. Short unit records without the report that should account for them.
    case = Case(stack, "Courier-en")
    report = case.translation()
    report["short_units"] = None
    case.put_translation(report)
    lines.append(
        _expect_failure(
            case, "short unit skips without a short unit report", "7 no short unit report"
        )
    )

    # 8. A chain wholly outside the declared scope, with no truth reaching out
    #    to claim it, is skipped and counted.
    case = Case(stack, "Courier-en")
    _drop_page(case, 5)
    result = case.run()
    ok = result["out_of_scope_chains"] == 1 and result["chains"] == 5
    lines.append(
        f"{'pass' if ok else 'FAIL'} 8 out of scope skipped: "
        f"out_of_scope={result['out_of_scope_chains']} chains={result['chains']}"
    )

    # 9. A chain with one foot inside the scope and one outside is a failure:
    #    the truth covers only half of it.
    case = Case(stack, "Courier-en")
    _drop_page(case, 8)
    lines.append(
        _expect_failure(case, "chain straddles the declared scope", "9 straddling chain")
    )

    # 10. Everything inside the scope keeps the original adjudication path.
    case = Case(stack, "Courier-en")
    result = case.run()
    ok = (
        result["out_of_scope_chains"] == 0
        and result["chains"] == 6
        and result["members"] == 12
        and result["status"] == "pass"
    )
    lines.append(f"{'pass' if ok else 'FAIL'} 10 in scope unchanged: {result}")

    return lines


def _run_cli(run: Path, sample: dict, check: str) -> tuple[int, dict]:
    """Drive the verifier through its own argument parser, as a caller would."""
    output = next((run / sample["sample_id"]).glob("*.mono.pdf"))
    argv = [
        "--check", check,
        "--expectations", str(ROOT / sample["expectations_path"]),
        "--source", str(ROOT / sample["source_path"]),
        "--output", str(output),
        "--working-dir", str(run / sample["sample_id"] / "work" / sample["sample_id"]),
        "--source-lang", sample["source_lang"],
        "--target-lang", sample["target_lang"],
        "--pages", ",".join(str(page) for page in sample["stage_pages"]),
    ]
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = verify_main(argv)
    try:
        payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload = {"error": stream.getvalue().strip()[-200:]}
    return code, payload


def end_to_end() -> list[str]:
    lines = []

    # 11. The five registered samples, each over its own declared pages.
    for sample in MATRIX:
        code, payload = _run_cli(BASELINE, sample, "chain")
        ok = code == 0 and payload.get("status") == "pass"
        detail = (
            f"out_of_scope={payload.get('out_of_scope_chains')} "
            f"short_unit_skips={payload.get('short_unit_skips')}"
            if ok
            else payload.get("error")
        )
        lines.append(f"{'pass' if ok else 'FAIL'} 11 {sample['sample_id']}: {detail}")

    # 12. The frozen control must not move.
    code, payload = _run_cli(CONTROL, SAMPLES["Courier-en"], "full")
    checks = payload.get("checks", {})
    ok = (
        code == 0
        and payload.get("status") == "pass"
        and len(checks) == 7
        and all(item.get("status") == "pass" for item in checks.values())
    )
    lines.append(
        f"{'pass' if ok else 'FAIL'} 12 control fix0829/Courier-en: "
        f"{len(checks)} checks, {payload.get('status', payload.get('error'))}"
    )
    return lines


def main() -> int:
    with contextlib.ExitStack() as stack:
        lines = symbolic(stack) + end_to_end()
    for line in lines:
        print(line)
    failed = [line for line in lines if line.startswith("FAIL")]
    print(f"\n{len(lines) - len(failed)}/{len(lines)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
