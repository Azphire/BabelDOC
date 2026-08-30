"""Collect what the repair loop actually did across a batch of runs.

The report this writes answers one question -- what did the loop repair, and on
what evidence -- and it answers it only from files the runs wrote. Every number
is counted from a sidecar, every decision is quoted from the audit log, and
every case points at two pictures of the same page. A defect kind the loop
never repaired is written as zero rather than left out, because "we did not see
this" and "this did not happen" are different claims and a report that drops
empty rows silently makes the first look like the second.

Usage:

    python tools/mapek_report.py <working-dir> [<working-dir> ...] \
        [--out docs/reports/B12/mapek_repair_report.md]

Each working directory is one sample's run directory: the one holding
issues.before.json, issues.after.json, termination.json, repair_decisions.jsonl
and evidence/.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import repair_evidence  # noqa: E402
from babeldoc.magazine.detectors import DETECTOR_NAMES  # noqa: E402

DEFAULT_OUT = ROOT / "docs/reports/B12/mapek_repair_report.md"
BEFORE_NAME = "issues.before.json"
AFTER_NAME = "issues.after.json"
TERMINATION_NAME = "termination.json"
DECISIONS_NAME = "repair_decisions.jsonl"


@dataclass
class SampleRun:
    """One sample's run, read from what it left behind."""

    name: str
    directory: Path
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    termination: dict = field(default_factory=dict)
    decisions: list = field(default_factory=list)

    @property
    def stopped(self) -> str:
        return self.termination.get("termination", "not recorded")

    @property
    def accepted_actions(self) -> list:
        return list(self.termination.get("accepted_actions") or ())

    @property
    def refusals(self) -> list:
        return list(self.termination.get("refusals") or ())

    def issues(self, which: str) -> list:
        source = self.before if which == "before" else self.after
        return list(source.get("issues") or ())

    def counts(self, which: str) -> dict[str, int]:
        source = self.before if which == "before" else self.after
        counts = (source.get("counts") or {}).get("by_kind")
        if isinstance(counts, dict):
            return {str(k): int(v) for k, v in counts.items()}
        tally: dict[str, int] = {}
        for issue in self.issues(which):
            tally[issue.get("kind", "?")] = tally.get(issue.get("kind", "?"), 0) + 1
        return tally

    def issue(self, issue_id: str) -> dict | None:
        for issue in self.issues("before"):
            if issue.get("id") == issue_id:
                return issue
        return None

    def nominations(self) -> dict[str, int]:
        """How many findings the model named per kind, refused or not."""
        tally: dict[str, int] = {}
        for row in self.termination.get("decisions") or ():
            if row.get("action") in (None, "no_op"):
                continue
            kind = row.get("kind", "?")
            tally[kind] = tally.get(kind, 0) + len(row.get("issue_ids") or ())
        return tally


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _read_jsonl(path: Path) -> list:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def load(directory: Path) -> SampleRun:
    directory = Path(directory)
    return SampleRun(
        name=directory.name,
        directory=directory,
        before=_read_json(directory / BEFORE_NAME),
        after=_read_json(directory / AFTER_NAME),
        termination=_read_json(directory / TERMINATION_NAME),
        decisions=_read_jsonl(directory / DECISIONS_NAME),
    )


def _relative(path: Path, out: Path) -> str:
    try:
        return Path(path).resolve().relative_to(out.parent.resolve()).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def _evidence(run: SampleRun) -> dict[int, tuple[Path, Path]]:
    directory = run.directory / repair_evidence.EVIDENCE_DIR
    if not directory.is_dir():
        return {}
    pages = {
        page
        for action in run.accepted_actions
        for page in (action.get("pages") or ())
    }
    return repair_evidence.pairs(directory, pages)


def _global_table(runs: list[SampleRun]) -> list[str]:
    detected: dict[str, int] = {}
    nominated: dict[str, int] = {}
    refused: dict[str, int] = {}
    accepted: dict[str, int] = {}
    for run in runs:
        for kind, count in run.counts("before").items():
            detected[kind] = detected.get(kind, 0) + count
        for kind, count in run.nominations().items():
            nominated[kind] = nominated.get(kind, 0) + count
        for row in run.refusals:
            kind = row.get("kind", "?")
            refused[kind] = refused.get(kind, 0) + 1
        for action in run.accepted_actions:
            kind = action.get("kind", "?")
            accepted[kind] = accepted.get(kind, 0) + 1
    lines = [
        "| defect kind | detected | nominated | refused by admission | repairs accepted |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for kind in DETECTOR_NAMES:
        lines.append(
            f"| `{kind}` | {detected.get(kind, 0)} | {nominated.get(kind, 0)} | "
            f"{refused.get(kind, 0)} | {accepted.get(kind, 0)} |"
        )
    return lines


def _termination_table(runs: list[SampleRun]) -> list[str]:
    lines = [
        "| sample | findings before | findings after | actions kept | rolled back | stopped because |",
        "| --- | ---: | ---: | ---: | :-: | --- |",
    ]
    for run in runs:
        lines.append(
            f"| `{run.name}` | {len(run.issues('before'))} | "
            f"{len(run.issues('after'))} | {len(run.accepted_actions)} | "
            f"{'yes' if run.termination.get('rolled_back') else 'no'} | "
            f"`{run.stopped}` |"
        )
    return lines


def _case(run: SampleRun, action: dict, evidence, out: Path) -> list[str]:
    issue_ids = action.get("issue_ids") or []
    issue = run.issue(issue_ids[0]) if issue_ids else None
    lines = [
        f"### `{run.name}` — {action.get('action')} on `{action.get('kind')}`",
        "",
        f"- **iteration**: {action.get('iteration')}",
        f"- **pages**: {', '.join(str(page) for page in action.get('pages') or [])}",
        f"- **paragraphs written**: "
        f"{', '.join(f'`{ref}`' for ref in action.get('written_refs') or []) or '—'}",
    ]
    if action.get("parameters"):
        lines.append(f"- **parameters**: `{json.dumps(action['parameters'])}`")
    if action.get("reason"):
        lines.append(f"- **the decision's reason**: {action['reason']}")
    if issue is not None:
        evidence_fields = issue.get("evidence") or {}
        shown = {
            key: value
            for key, value in sorted(evidence_fields.items())
            if key not in ("excerpt",) and not isinstance(value, (dict, list))
        }
        lines.append(
            f"- **the finding, before**: severity `{issue.get('severity')}`, "
            f"`{json.dumps(shown, ensure_ascii=False)}`"
        )
        survived = any(
            item.get("id") == issue.get("id") for item in run.issues("after")
        )
        lines.append(
            f"- **after the repair**: this finding "
            + ("still stands" if survived else "is gone")
        )
    for page in action.get("pages") or []:
        pair = evidence.get(page)
        if pair is None:
            continue
        lines.extend(
            [
                "",
                f"| page {page} before | page {page} after |",
                "| --- | --- |",
                f"| ![before]({_relative(pair[0], out)}) "
                f"| ![after]({_relative(pair[1], out)}) |",
            ]
        )
    lines.append("")
    return lines


def render(runs: list[SampleRun], out: Path) -> str:
    lines = [
        "# MAPE-K repair evidence",
        "",
        "Everything below is counted from what the runs wrote: the detection",
        "sidecars, the decision audit log, and the termination record. A kind",
        "the loop never repaired is written as zero rather than omitted.",
        "",
        "## What was detected, nominated, refused and repaired",
        "",
        *_global_table(runs),
        "",
        "## How each run ended",
        "",
        *_termination_table(runs),
        "",
        "## Accepted repairs, one section each",
        "",
    ]
    cases = 0
    for run in runs:
        evidence = _evidence(run)
        for action in run.accepted_actions:
            cases += 1
            lines.extend(_case(run, action, evidence, out))
    if not cases:
        lines.extend(
            [
                "No repair was accepted on any sample in this batch. The loop",
                "ran, measured, and kept nothing; the per-kind table above says",
                "where its nominations were refused.",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    runs = [load(directory) for directory in args.directories]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(runs, out), encoding="utf-8")
    accepted = sum(len(run.accepted_actions) for run in runs)
    print(
        f"wrote {out} from {len(runs)} run(s); {accepted} accepted repair(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
