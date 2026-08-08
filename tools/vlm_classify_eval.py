"""Measure the deterministic classifier and its vision fallback side by side.

Usage:
    python tools/vlm_classify_eval.py
    python tools/vlm_classify_eval.py --sample Courier-en.pdf --out examples/output/b3

Writes ``vlm_eval.report.json`` and prints a summary of it. The report answers
three questions and nothing else: how often the fallback refuses and the
deterministic verdict stands, how often the fallback is right on the pages it is
actually given, and whether the two layers together agree with the hand written
ground truth more often than the deterministic layer does alone.

This is a report, not a gate. The numbers go into the delivery as they come out.
Nothing here has a target to clear, and the only permitted response to a
disappointing number is a prompt edit -- recorded, with its hash and the numbers
either side of it -- or leaving the fallback switched off.

How it runs
-----------

Every sample is put through the pipeline once with translation skipped, which
costs no key and produces the classifier's checkpoint; the shared gate artefact
cache holds those, so a second run of this tool rebuilds nothing. The stage is
then replayed over each checkpoint in this process, which is what makes a prompt
iteration affordable: the pipeline is not run again, and every page whose prompt
and image are unchanged is answered from the reply cache without a request.

The switch and every parameter come from ``configs/vlm.json`` as they do in a
real run. With the switch off the tool still runs and reports a system that
refuses every page, which is the honest description of that configuration.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.magazine import corpus as corpus_module  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import checkpoint_stem  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.page_classifier import REPORT_NAME  # noqa: E402
from babeldoc.magazine.page_classifier import VLM_SOURCE  # noqa: E402
from babeldoc.magazine.page_classifier import PageClassifier  # noqa: E402
from babeldoc.magazine.prompt_loader import MANIFEST_NAME  # noqa: E402
from babeldoc.magazine.vlm_client import CachedVlmClient  # noqa: E402
from babeldoc.magazine.vlm_client import OpenAICompatibleTransport  # noqa: E402
from babeldoc.magazine.vlm_client import load_vlm_config  # noqa: E402
from spec_checks import artifacts  # noqa: E402

logger = logging.getLogger(__name__)

INPUT_DIR = ROOT / "examples" / "input"
DEFAULT_OUT_DIR = ROOT / "examples" / "output" / "b3"
REPORT_FILE = "vlm_eval.report.json"

# Pipeline configuration the checkpoints come from, by the name the shared
# artefact cache files it under.
ARTIFACT_MODE = "classified"


class CountingTransport:
    """The real transport with a tally, so the report can state what it cost."""

    def __init__(self) -> None:
        self.inner = OpenAICompatibleTransport()
        self.requests = 0

    def complete(self, config, prompt: str, image_png: bytes) -> str:
        self.requests += 1
        return self.inner.complete(config, prompt, image_png)


class WorkingDirConfig:
    """The whole of ``TranslationConfig`` the classifier stage reads."""

    def __init__(self, working_dir: Path, input_file: Path) -> None:
        self.working_dir = working_dir
        self.input_file = input_file

    def get_working_file_path(self, filename: str) -> Path:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return self.working_dir / filename


def rate(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def tally(table: dict[str, list[int]], key: str, hit: bool) -> None:
    entry = table.setdefault(key, [0, 0])
    entry[1] += 1
    entry[0] += int(hit)


def as_pairs(table: dict[str, list[int]]) -> dict[str, dict]:
    return {
        key: {"hits": hits, "total": total, "rate": round(rate(hits, total), 4)}
        for key, (hits, total) in sorted(table.items())
    }


def _build_requests(working_dir: Path) -> int:
    """Requests the pipeline run itself made while producing these checkpoints.

    A run performed with the switch on adjudicates as it goes, and those calls
    are as real as the ones this tool makes; counting only the replay would
    report a corpus as free the first time it was ever classified.
    """
    path = working_dir / REPORT_NAME
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8") as f:
        report = json.load(f)
    return sum(
        record["vlm"]["attempts"]
        for record in report["pages"]
        if record.get("vlm") and not record["vlm"]["from_cache"]
    )


def replay(sample: Path, checkpoint: Path, working: Path, client: CachedVlmClient):
    """Run the classifier stage over one checkpoint and return its sidecar."""
    docs = load_checkpoint(checkpoint)
    stage = PageClassifier(WorkingDirConfig(working, sample), vlm_client=client)
    stage.process(docs)
    with (working / REPORT_NAME).open(encoding="utf-8") as f:
        return json.load(f)


def evaluate(samples: list[dict], out_dir: Path) -> dict:
    config = load_vlm_config()
    transport = CountingTransport()
    client = CachedVlmClient(config=config, transport=transport)
    labels = corpus_module.normalize_page_labels(corpus_module.load_page_labels())

    deterministic: dict[str, list[int]] = {}
    combined: dict[str, list[int]] = {}
    routed_deterministic: dict[str, list[int]] = {}
    routed_model: dict[str, list[int]] = {}
    refusals: list[str] = []
    reasons: Counter[str] = Counter()
    secondary: list[dict] = []
    pages: list[dict] = []
    routed = 0
    accepted = 0
    cached = 0
    attempts = 0
    pipeline_requests = 0

    for entry in samples:
        file_name = entry["file"]
        name = Path(file_name).stem
        publication = entry.get("publication", name)
        built = artifacts.get_artifacts(INPUT_DIR / file_name, ARTIFACT_MODE)
        pipeline_requests += _build_requests(built.working_dir)
        checkpoint = built.working_dir / f"{checkpoint_stem('page_classifier')}.xml"
        working = out_dir / "work" / name
        report = replay(INPUT_DIR / file_name, checkpoint, working, client)

        expected_by_page = labels.get(file_name, {})
        for position, record in enumerate(report["pages"]):
            number = record["page_number"]
            page_key = str((number if number is not None else position) + 1)
            expected = expected_by_page.get(page_key)
            outcome = record["vlm"]
            row = {
                "file": file_name,
                "page": int(page_key),
                "labels": expected,
                "deterministic_kind": record["kind"],
                "deterministic_conf": round(record["conf"], 4),
                "ambiguous": record["ambiguous"],
                "final_kind": record["final_kind"],
                "final_conf": round(record["final_conf"], 4),
                "source": record["source"],
                "vlm": outcome,
            }
            if expected is not None:
                row["deterministic_hit"] = record["kind"] in expected
                row["final_hit"] = record["final_kind"] in expected
                tally(deterministic, publication, row["deterministic_hit"])
                tally(combined, publication, row["final_hit"])
            pages.append(row)

            if outcome is None:
                continue
            routed += 1
            attempts += outcome["attempts"]
            cached += int(outcome["from_cache"])
            if outcome["accepted"]:
                accepted += 1
                if outcome["secondary_kind"] is not None:
                    secondary.append(
                        {
                            "file": file_name,
                            "page": int(page_key),
                            "kind": outcome["kind"],
                            "secondary_kind": outcome["secondary_kind"],
                            "secondary_reason": outcome["secondary_reason"],
                        }
                    )
            else:
                refusals.append(f"{file_name}#{page_key}: {outcome['reason'][:120]}")
                reasons[outcome["reason"].split(":")[0][:60]] += 1
            if expected is not None:
                tally(routed_deterministic, publication, record["kind"] in expected)
                tally(routed_model, publication, record["final_kind"] in expected)

    for table in (deterministic, combined, routed_deterministic, routed_model):
        table[""] = [
            sum(hits for hits, _ in table.values()),
            sum(total for _, total in table.values()),
        ]

    manifest_paths = sorted((out_dir / "work").glob(f"*/{MANIFEST_NAME}"))
    prompts: dict[str, str] = {}
    for path in manifest_paths:
        with path.open(encoding="utf-8") as f:
            prompts.update(json.load(f))

    return {
        "configuration": {
            "enabled": config.enabled,
            "model": config.model,
            "temperature": config.temperature,
            "max_output_tokens": config.max_output_tokens,
            "max_retries": config.max_retries,
            "render_dpi": config.render_dpi,
            "verdict_rows": config.verdict_rows,
        },
        "prompts": prompts,
        "cost": {
            "routed_pages": routed,
            "transport_requests": transport.requests,
            "pipeline_requests": pipeline_requests,
            "cache_hits": cached,
            "attempts": attempts,
        },
        "fallback": {
            "routed": routed,
            "accepted": accepted,
            "refused": routed - accepted,
            "refusal_rate": round(rate(routed - accepted, routed), 4),
            "refusal_reasons": dict(reasons),
            "refusals": refusals[:20],
        },
        "agreement": {
            "deterministic": as_pairs(deterministic),
            "combined": as_pairs(combined),
            "routed_pages_deterministic": as_pairs(routed_deterministic),
            "routed_pages_combined": as_pairs(routed_model),
        },
        "secondary_kinds": secondary,
        "pages": pages,
    }


def summarize(report: dict) -> str:
    lines: list[str] = []
    configuration = report["configuration"]
    lines.append(
        f"model={configuration['model']} enabled={configuration['enabled']} "
        f"dpi={configuration['render_dpi']} rows={configuration['verdict_rows']}"
    )
    for path, digest in sorted(report["prompts"].items()):
        lines.append(f"prompt {path} {digest}")

    cost = report["cost"]
    lines.append(
        f"cost: routed={cost['routed_pages']} requests={cost['transport_requests']} "
        f"pipeline_requests={cost['pipeline_requests']} "
        f"cache_hits={cost['cache_hits']} attempts={cost['attempts']}"
    )
    fallback = report["fallback"]
    lines.append(
        f"fallback: accepted={fallback['accepted']}/{fallback['routed']} "
        f"refused={fallback['refused']} rate={fallback['refusal_rate']}"
    )
    for reason, count in sorted(fallback["refusal_reasons"].items()):
        lines.append(f"  refusal {count} x {reason}")

    agreement = report["agreement"]
    for label in ("routed_pages_deterministic", "routed_pages_combined"):
        pooled = agreement[label][""]
        lines.append(f"{label}: {pooled['hits']}/{pooled['total']} = {pooled['rate']}")
    lines.append("agreement by publication (deterministic -> combined):")
    for key in sorted(agreement["combined"]):
        before = agreement["deterministic"][key]
        after = agreement["combined"][key]
        lines.append(
            f"  {key or 'overall':16s} {before['hits']}/{before['total']} "
            f"({before['rate']}) -> {after['hits']}/{after['total']} ({after['rate']})"
        )
    for item in report["secondary_kinds"]:
        lines.append(
            f"secondary {item['file']}#{item['page']}: {item['kind']} + "
            f"{item['secondary_kind']} :: {item['secondary_reason']}"
        )
    changed = [
        f"{row['file']}#{row['page']} {row['deterministic_kind']} -> {row['final_kind']}"
        f" ({'hit' if row.get('final_hit') else 'miss'})"
        for row in report["pages"]
        if row["source"] == VLM_SOURCE
        and row["deterministic_kind"] != row["final_kind"]
    ]
    lines.append(f"pages the fallback moved: {len(changed)}")
    lines.extend(f"  {line}" for line in changed)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        action="append",
        default=None,
        help="restrict to one registered sample file name; repeatable",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.ERROR)
    use_project_cache(ROOT)
    warmup()

    manifest = corpus_module.load_manifest()
    samples = [
        entry
        for entry in manifest["samples"]
        if args.sample is None or entry["file"] in set(args.sample)
    ]
    if not samples:
        print(f"ERROR: no registered sample matches {args.sample}")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    report = evaluate(samples, args.out)
    target = args.out / REPORT_FILE
    with target.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    summary = summarize(report)
    (args.out / "vlm_eval.summary.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    print(f"\nvlm_classify_eval: {len(report['pages'])} page(s) -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
