"""Measure the deterministic classifier and its vision fallback side by side.

Usage:
    python tools/vlm_classify_eval.py
    python tools/vlm_classify_eval.py --sample Courier-en.pdf --out examples/output/b3

Writes ``vlm_eval.report.json`` and prints a summary of it. The report answers
three questions and nothing else: how often the fallback refuses and the
deterministic verdict stands, how often the fallback is right on the pages it is
actually given, and whether the two layers together agree with the hand written
ground truth more often than the deterministic layer does alone.

Two scores answer the last question, reported side by side and never merged.
The single point score asks whether the one kind a page was given is among the
kinds it carries. The label set score asks whether anything the layer named --
its verdict and, where the fallback offered one, its second candidate -- is
among them; a composite sheet the ground truth records under two names is then
scored on whether the system saw either. The deterministic layer names one kind
and never a second, so its two columns are equal by construction, which is what
makes the pair readable as a comparison instead of as two unrelated numbers.

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
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
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


def pooled(table: dict[str, list[int]]) -> None:
    """Add the corpus wide row every table carries under the empty key."""
    table[""] = [
        sum(hits for hits, _ in table.values()),
        sum(total for _, total in table.values()),
    ]


def predicted_set(kind: str, outcome: dict | None) -> set[str]:
    """The kinds a layer named for one page: its verdict and its runner up.

    A page the fallback never saw, and one it saw without offering a second
    candidate, are both a single name -- so this collapses to the single point
    prediction wherever there is no second candidate to add.
    """
    predicted = {kind}
    if outcome is not None and outcome.get("secondary_kind") is not None:
        predicted.add(outcome["secondary_kind"])
    return predicted


def coverage_hit(kind: str, outcome: dict | None, expected: list[str]) -> bool:
    """Whether anything the layer named is among the labels the page carries."""
    return bool(predicted_set(kind, outcome) & set(expected))


def policy_hit(kind: str, expected: list[str], policy_of) -> bool:
    """Whether the kind named leads to a policy one of the accepted kinds leads to.

    The column ledger row C-04 says was never produced. Everything downstream of
    the classifier consumes the policy flags and never the name, so two kinds
    declaring the same policy are the same decision, and a page called one of
    them when the truth is the other is a naming difference rather than a
    misclassification. Reported beside the kind column and never instead of it:
    the two answer different questions and the looser one alone would flatter.
    """
    if kind in expected:
        return True
    own = policy_of(kind)
    if own is None:
        return False
    return any(policy_of(candidate) == own for candidate in expected)


def policy_columns(pages: list[dict], policy_of, publication_of) -> dict:
    """The policy level agreement of both layers, from per page verdicts.

    Takes the rows a report already carries, so it recomputes the column over a
    frozen report at no cost and with no replay: the kinds are in the report and
    the mapping is in the vocabulary, and nothing else is needed.
    """
    deterministic: dict[str, list[int]] = {}
    combined: dict[str, list[int]] = {}
    routed_deterministic: dict[str, list[int]] = {}
    routed_combined: dict[str, list[int]] = {}
    for row in pages:
        expected = row.get("labels")
        if not expected:
            continue
        publication = publication_of.get(row["file"], row["file"])
        before = policy_hit(row["deterministic_kind"], expected, policy_of)
        after = policy_hit(row["final_kind"], expected, policy_of)
        tally(deterministic, publication, before)
        tally(combined, publication, after)
        if row.get("vlm") is not None:
            tally(routed_deterministic, publication, before)
            tally(routed_combined, publication, after)
    for table in (deterministic, combined, routed_deterministic, routed_combined):
        pooled(table)
    return {
        "deterministic": as_pairs(deterministic),
        "combined": as_pairs(combined),
        "routed_pages_deterministic": as_pairs(routed_deterministic),
        "routed_pages_combined": as_pairs(routed_combined),
    }


def publication_index() -> dict[str, str]:
    """Sample file name to the publication it came from, as the manifest says."""
    manifest = corpus_module.load_manifest()
    return {
        entry["file"]: entry.get("publication", entry["file"])
        for entry in manifest["samples"]
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
    coverage_deterministic: dict[str, list[int]] = {}
    coverage_combined: dict[str, list[int]] = {}
    routed_coverage_deterministic: dict[str, list[int]] = {}
    routed_coverage_combined: dict[str, list[int]] = {}
    secondary_gain: list[dict] = []
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
                # The label set columns, beside the single point ones above and
                # computed from the same verdicts.
                row["deterministic_coverage_hit"] = coverage_hit(
                    record["kind"], None, expected
                )
                row["final_coverage_hit"] = coverage_hit(
                    record["final_kind"], outcome, expected
                )
                tally(
                    coverage_deterministic,
                    publication,
                    row["deterministic_coverage_hit"],
                )
                tally(coverage_combined, publication, row["final_coverage_hit"])
                if row["final_coverage_hit"] and not row["final_hit"]:
                    secondary_gain.append(
                        {
                            "file": file_name,
                            "page": int(page_key),
                            "labels": expected,
                            "kind": record["final_kind"],
                            "secondary_kind": outcome["secondary_kind"],
                        }
                    )
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
                tally(
                    routed_coverage_deterministic,
                    publication,
                    row["deterministic_coverage_hit"],
                )
                tally(routed_coverage_combined, publication, row["final_coverage_hit"])

    for table in (
        deterministic,
        combined,
        routed_deterministic,
        routed_model,
        coverage_deterministic,
        coverage_combined,
        routed_coverage_deterministic,
        routed_coverage_combined,
    ):
        pooled(table)

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
            "token_parameter": config.token_parameter,
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
        "policy_agreement": policy_columns(
            pages, load_taxonomy().policy_of, {
                entry["file"]: entry.get("publication", entry["file"])
                for entry in samples
            }
        ),
        "label_set_coverage": {
            "deterministic": as_pairs(coverage_deterministic),
            "combined": as_pairs(coverage_combined),
            "routed_pages_deterministic": as_pairs(routed_coverage_deterministic),
            "routed_pages_combined": as_pairs(routed_coverage_combined),
            "secondary_gain_pages": secondary_gain,
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
    # The ablation setting travels with every accuracy figure below it: two
    # models measured at different supported settings are not comparable, and a
    # number quoted without the setting cannot be checked.
    lines.append(
        f"setting: temperature={configuration['temperature']} "
        f"token_parameter={configuration['token_parameter']} "
        f"max_output_tokens={configuration['max_output_tokens']}"
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
    coverage = report["label_set_coverage"]
    for label in ("routed_pages_deterministic", "routed_pages_combined"):
        total = agreement[label][""]
        covered = coverage[label][""]
        lines.append(
            f"{label}: {total['hits']}/{total['total']} = {total['rate']} "
            f"| coverage {covered['hits']}/{covered['total']} = {covered['rate']}"
        )
    lines.append(
        "agreement by publication (deterministic -> combined) "
        "| label set coverage (deterministic -> combined):"
    )
    for key in sorted(agreement["combined"]):
        before = agreement["deterministic"][key]
        after = agreement["combined"][key]
        covered_before = coverage["deterministic"][key]
        covered_after = coverage["combined"][key]
        lines.append(
            f"  {key or 'overall':16s} {before['hits']}/{before['total']} "
            f"({before['rate']}) -> {after['hits']}/{after['total']} ({after['rate']})"
            f" | {covered_before['hits']}/{covered_before['total']} "
            f"({covered_before['rate']}) -> "
            f"{covered_after['hits']}/{covered_after['total']} "
            f"({covered_after['rate']})"
        )
    gains = coverage["secondary_gain_pages"]
    lines.append(f"pages the second candidate alone covers: {len(gains)}")
    for item in gains:
        lines.append(
            f"  gain {item['file']}#{item['page']}: {item['kind']} + "
            f"{item['secondary_kind']} against {item['labels']}"
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


def recompute_policy(paths: list[Path]) -> dict:
    """The policy column of frozen ablation reports, without running anything.

    Ledger row C-04 states a conclusion -- no model tier gains at the policy
    level -- that the produced reports never carried the column for. This
    recomputes it from the reports themselves. It is offline for every tier
    alike, including the one whose replies were never cached: what is read is
    the frozen verdict, not the model, so no tier costs a request and all four
    have the same provenance.
    """
    policy_of = load_taxonomy().policy_of
    publication_of = publication_index()
    tiers = []
    for path in paths:
        with path.open(encoding="utf-8") as f:
            report = json.load(f)
        columns = policy_columns(report["pages"], policy_of, publication_of)
        kind = report["agreement"]
        # Which samples the frozen run measured that the corpus no longer
        # registers. The ablation predates a corpus swap, so the column is a
        # property of the corpus it ran on and is not the same denominator as a
        # figure quoted for the corpus registered today.
        unregistered = sorted(
            {
                row["file"]
                for row in report["pages"]
                if row.get("labels") and row["file"] not in publication_of
            }
        )
        tiers.append(
            {
                "report": path.as_posix(),
                "unregistered_samples": unregistered,
                "model": report["configuration"]["model"],
                "enabled": report["configuration"]["enabled"],
                "cost": report["cost"],
                "kind_agreement": {
                    name: kind[name][""] for name in sorted(kind)
                },
                "policy_agreement": {
                    name: columns[name][""] for name in sorted(columns)
                },
                "policy_by_publication": columns["combined"],
                "policy_gain": {
                    name: columns["combined"][name]["hits"]
                    - columns["deterministic"][name]["hits"]
                    for name in sorted(columns["combined"])
                },
            }
        )
    return {
        "generated_by": "tools/vlm_classify_eval.py --from-report",
        "ledger_row": "C-04",
        "note": (
            "Recomputed offline from the frozen ablation reports. No model "
            "request was made and no reply cache was consulted: the reports "
            "carry every verdict the column needs. Any sample named under "
            "unregistered_samples was in the corpus the ablation ran on and is "
            "not in the corpus registered today, so these denominators are not "
            "the denominators of a figure quoted for the current corpus."
        ),
        "tiers": tiers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        action="append",
        default=None,
        help="restrict to one registered sample file name; repeatable",
    )
    parser.add_argument(
        "--from-report",
        action="append",
        type=Path,
        default=None,
        metavar="REPORT_JSON",
        help="recompute the policy column of a frozen report; runs nothing",
    )
    parser.add_argument(
        "--name",
        default="vlm_policy",
        help="stem of the file --from-report writes into --out",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.ERROR)

    if args.from_report:
        missing = [path for path in args.from_report if not path.is_file()]
        if missing:
            print(f"ERROR: no such report: {[str(path) for path in missing]}")
            return 1
        report = recompute_policy(args.from_report)
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / f"{args.name}.json"
        with target.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write("\n")
        for tier in report["tiers"]:
            kind = tier["kind_agreement"]["combined"]
            policy = tier["policy_agreement"]["combined"]
            print(
                f"{tier['model']:16s} kind={kind['hits']}/{kind['total']} "
                f"({kind['rate']}) policy={policy['hits']}/{policy['total']} "
                f"({policy['rate']}) policy_gain={tier['policy_gain']['']}"
            )
        print(f"\nvlm_classify_eval: {len(report['tiers'])} tier(s) -> {target}")
        return 0
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
