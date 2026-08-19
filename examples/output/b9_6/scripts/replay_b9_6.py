"""B9.6 decision replay: one prompt round measured at four decision points.

What this batch iterates is wording, so what it measures is what a model chooses
when it is shown the same findings as before. Nothing here lays a page out or
writes a document: each case renders the decision request the shipped code
renders, sends it once through the run's engine with the cache bypassed, and
records the reply and the decision the shipped interpreter makes of it.

The four cases, and why each is here:

``cern_p1`` and ``courier_p1`` are the two decision points batch b9.5 missed,
replayed rather than approximated. Their findings are the sets those runs
detected, frozen under ``inputs/``, and the request rendered from each is held
against the cache key that run recorded -- rendered through b9.5's own copy of
the prompt, frozen beside them, so the reproduction stays provable after the
prompt in the tree is reworded. A qualifying ``out_of_page`` finding stood in
both and neither decision named it.

``synthetic_contain`` is the same shape built from nothing: one display heading
whose ink reaches past the top of its frame, several residues the orphan rule
refuses, and a cluster of short lines. Exactly one action has findings that
satisfy its conditions, so the correct choice is derived rather than asserted.

``orphan_spectrum`` is the nineteen finding fixture batch b8.4 measured
selection on, rebuilt from the rule the same way. Only the orphan action has
qualifying findings there, so it is the regression face: a wording round that
moves what this case chooses has cost something to buy whatever it gained.

Not part of the gate: this is the only thing in the batch that spends a
credential.

Usage:
    python replay_b9_6.py --round round0
    python replay_b9_6.py --round round1 --case cern_p1
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine import prompt_loader  # noqa: E402
from babeldoc.magazine.react import actions as orphan_actions  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import contain  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

BATCH_DIR = ROOT / "examples" / "output" / "b9_6"
INPUTS = BATCH_DIR / "inputs"
ROUNDS = BATCH_DIR / "rounds"
HISTORICAL_PROMPT_DIR = INPUTS / "prompt_b9_5"

MODEL = "gpt-4o"
QPS = 4
LANGUAGE = "zh"

# The identity the b9.5 arms ran under, which is half of the key their requests
# were filed by and therefore half of what proves a replay is the same request.
IDENTITY = f"OpenAITranslator/openai/{LANGUAGE}"

TRACE_NAME = "prompt_trace.jsonl"
DECISIONS_NAME = "decisions.json"
ISSUES_NAME = "issues.json"

PAGE_WIDTH = 600.0
PAGE_HEIGHT = 800.0
BODY_FONT = "body"
TARGET_FILL = "文"
RESIDUE_FILL = "c"

CASES = ("cern_p1", "courier_p1", "synthetic_contain", "orphan_spectrum")


# --- the shipped configuration ------------------------------------------------


def issue_kinds() -> tuple[str, ...]:
    return tuple(sorted(module.KIND for module in detectors.DETECTORS.values()))


def repair_config():
    return react_config.load_repair_config(None, issue_kinds())


def orphan_action(config):
    return config.actions[orphan_actions.NAME]


def contain_action(config):
    return config.actions[contain.NAME]


# --- findings read back from a frozen run -------------------------------------


@dataclass(frozen=True)
class FrozenIssue:
    """One finding as a run recorded it, in the shape the request reads."""

    id: str
    kind: str
    severity: str
    page: int
    paragraph_refs: list
    evidence: dict


def frozen_issues(path: Path) -> list[FrozenIssue]:
    recorded = json.loads(path.read_text(encoding="utf-8"))
    return [
        FrozenIssue(
            item["id"],
            item["kind"],
            item["severity"],
            item["page"],
            list(item["paragraph_refs"]),
            dict(item["evidence"]),
        )
        for item in recorded["issues"]
    ]


def request_blocks(config, issues) -> dict:
    """The three sections of the request, from the shipped builders."""
    return {
        "issues_block": decide.issues_block(
            issues, config.issue_excerpt_chars, config.max_issues_offered
        ),
        "actions_block": decide.actions_block(config),
        "action_constraints": decide.constraints_block(config),
    }


def historical_config():
    """The repair configuration as batch b9.5 shipped it, frozen under inputs/.

    A request carries the action descriptions, so reproducing one needs the
    configuration of the run as much as its prompt. This batch reworded one of
    those descriptions, which is exactly why the reproduction reads the frozen
    copy rather than the tree.
    """
    raw = json.loads(
        (INPUTS / "repair_actions.b9_5.json").read_text(encoding="utf-8")
    )
    return react_config.parse_repair_config(
        raw, "repair_actions.b9_5.json", set(issue_kinds())
    )


# --- what the stated conditions admit -----------------------------------------


def contains_qualify(config, issues) -> list[str]:
    """The findings the containment conditions admit, read as the request states.

    The two terms the request states for this action, applied to the evidence
    the request shows: the label is one of the declared containment classes and
    the reach is at or above the declared share. Which is what a correct answer
    to the request is, rather than what the loop would go on to do with it.
    """
    action = contain_action(config)
    labels = set(action.applicability[react_config.CONTAIN_LABELS_KEY])
    minimum = float(action.applicability[react_config.MIN_OVERFLOW_KEY])
    chosen = []
    for issue in issues:
        if issue.kind not in action.issue_kinds:
            continue
        ratio = issue.evidence.get("overflow_ratio")
        if issue.evidence.get("layout_label") in labels and isinstance(
            ratio, int | float
        ):
            if float(ratio) >= minimum:
                chosen.append(issue.id)
    return chosen


def orphans_qualify(config, issues) -> list[str]:
    """The findings the orphan conditions admit, read the same way."""
    action = orphan_action(config)
    labels = set(action.applicability[react_config.ORPHAN_LABELS_KEY])
    minimum = float(action.applicability[react_config.MIN_RATIO_KEY])
    chars = int(action.applicability[react_config.MIN_CHARS_KEY])
    chosen = []
    for issue in issues:
        if issue.kind not in action.issue_kinds:
            continue
        ratio = issue.evidence.get("residue_ratio")
        if issue.evidence.get("layout_label") not in labels:
            continue
        if not isinstance(ratio, int | float) or float(ratio) < minimum:
            continue
        if len(str(issue.evidence.get("excerpt") or "")) < chars:
            continue
        chosen.append(issue.id)
    return chosen


def qualifying(config, issues) -> dict[str, list[str]]:
    admitted = {
        contain.NAME: contains_qualify(config, issues),
        orphan_actions.NAME: orphans_qualify(config, issues),
    }
    return {name: ids for name, ids in admitted.items() if ids}


# --- the synthetic containment case -------------------------------------------


def style(font: str = BODY_FONT, size: float = 10.0):
    return il_version_1.PdfStyle(
        font_id=font, font_size=size, graphic_state=il_version_1.GraphicState()
    )


def character(text: str, x: float, y: float, width: float, size: float):
    box = il_version_1.Box(x=x, y=y, x2=x + width, y2=y + size)
    return il_version_1.PdfCharacter(
        char_unicode=text,
        box=box,
        visual_bbox=il_version_1.VisualBbox(box=copy.deepcopy(box)),
        pdf_style=style(BODY_FONT, size),
        advance=width / size,
        vertical=False,
        xobj_id=0,
    )


def laid_out(text: str, x: float, y: float, size: float, label: str, debug_id: str):
    """One paragraph as the typesetting stage leaves it: one character each."""
    step = size * 0.6
    characters = [
        character(letter, x + index * step, y, step, size)
        for index, letter in enumerate(text)
    ]
    ink = (
        min(item.box.x for item in characters),
        min(item.box.y for item in characters),
        max(item.box.x2 for item in characters),
        max(item.box.y2 for item in characters),
    )
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*ink),
        pdf_style=style(BODY_FONT, size),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(pdf_character=item)
            for item in characters
        ],
        unicode=text,
        layout_label=label,
        debug_id=debug_id,
        vertical=False,
        xobj_id=-1,
    )


def framed_page(paragraphs):
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(
            box=il_version_1.Box(0.0, 0.0, PAGE_WIDTH, PAGE_HEIGHT)
        ),
        cropbox=il_version_1.Cropbox(
            box=il_version_1.Box(0.0, 0.0, PAGE_WIDTH, PAGE_HEIGHT)
        ),
        pdf_paragraph=list(paragraphs),
        page_number=0,
        unit="point",
    )


def synthetic_document(config):
    """A page where exactly one action has a finding that satisfies its rule.

    The heading overflows the top of the frame by a share the containment rule
    admits and carries a label that rule lists. The residues are reported by the
    detector and refused by the orphan rule on both of its terms: their share is
    under its bound and their label is not one it lists. The short lines are a
    cluster nothing answers for. So the correct choice is derived from the two
    rules rather than written down here.
    """
    contain_rule = contain_action(config).applicability
    orphan_rule = orphan_action(config).applicability
    heading_label = contain_rule[react_config.CONTAIN_LABELS_KEY][0]
    body_label = next(
        name
        for name in ("plain text", "abandon", "text")
        if name not in orphan_rule[react_config.ORPHAN_LABELS_KEY]
        and name not in contain_rule[react_config.CONTAIN_LABELS_KEY]
    )
    floor = detectors.detector_config().residue_min_script_chars

    size = 40.0
    heading = "全球卫生报告二零二六"
    # Ink well past the top of the frame: a share the rule admits, on a
    # paragraph carrying a label the rule's own list names.
    overflow = 32.0
    paragraphs = [
        laid_out(
            heading, 40.0, PAGE_HEIGHT - size + overflow, size, heading_label, "head1"
        )
    ]

    # Residues the detector raises and the orphan rule refuses on both terms.
    share = float(orphan_rule[react_config.MIN_RATIO_KEY]) - 0.2
    latin = max(floor, round(share * 60))
    residue = (RESIDUE_FILL * latin) + (TARGET_FILL * (60 - latin))
    for index in range(4):
        paragraphs.append(
            laid_out(residue, 40.0, 600.0 - 60.0 * index, 9.0, body_label, f"res{index}")
        )

    # Short lines stacked close: a cluster, and no action answers for the kind.
    for index in range(4):
        paragraphs.append(
            laid_out(
                TARGET_FILL * 8, 40.0, 300.0 - 12.0 * index, 9.0, body_label,
                f"frag{index}",
            )
        )

    return il_version_1.Document(page=[framed_page(paragraphs)], total_pages=1)


# --- the b8.4 nineteen finding spectrum ---------------------------------------


def run_composition(text: str, boxes):
    characters = [
        il_version_1.PdfCharacter(
            char_unicode=letter,
            box=il_version_1.Box(*box),
            visual_bbox=il_version_1.VisualBbox(box=il_version_1.Box(*box)),
            pdf_style=style(),
            advance=0.6,
            vertical=False,
            xobj_id=0,
        )
        for letter, box in zip(text, boxes, strict=True)
    ]
    return il_version_1.PdfParagraphComposition(
        pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
            box=il_version_1.Box(
                min(item.box.x for item in characters),
                min(item.box.y for item in characters),
                max(item.box.x2 for item in characters),
                max(item.box.y2 for item in characters),
            ),
            pdf_style=style(),
            pdf_character=characters,
        )
    )


def horizontal_paragraph(text: str, label: str, index: int):
    boxes = [
        (10.0 + 6.0 * position, 100.0, 16.0 + 6.0 * position, 110.0)
        for position in range(len(text))
    ]
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(0.0, 95.0, 590.0, 115.0),
        pdf_paragraph_composition=[run_composition(text, boxes)],
        unicode=text,
        layout_label=label,
        debug_id=f"h{index:03d}",
        vertical=False,
        xobj_id=-1,
    )


def spectrum_document(config):
    """Batch b8.4's selection fixture, built from the rule rather than around it.

    Nineteen findings of one kind: strong evidence, evidence exactly at the
    bound, evidence under it, and evidence refused on its label. What comes back
    is the document and the references the rule ought to admit.
    """
    rule = orphan_action(config).applicability
    bound = float(rule[react_config.MIN_RATIO_KEY])
    orphan = rule[react_config.ORPHAN_LABELS_KEY][0]
    other = next(
        name
        for name in ("plain text", "title", "abandon")
        if name not in rule[react_config.ORPHAN_LABELS_KEY]
    )
    floor = detectors.detector_config().residue_min_script_chars

    def share(ratio: float, total: int = 60) -> tuple[int, int]:
        latin = max(floor, round(ratio * total))
        return latin, total - latin

    paragraphs = []
    expected: list[int] = []
    for latin in (60, 50, 40, 30):
        paragraphs.append(
            horizontal_paragraph(RESIDUE_FILL * latin, orphan, len(paragraphs))
        )
        expected.append(len(paragraphs) - 1)
    for _ in range(2):
        latin, han = share(bound)
        paragraphs.append(
            horizontal_paragraph(
                (RESIDUE_FILL * latin) + (TARGET_FILL * han), orphan, len(paragraphs)
            )
        )
        expected.append(len(paragraphs) - 1)
    for step in (0.05, 0.1, 0.15, 0.2, 0.22, 0.25, 0.28):
        latin, han = share(bound - step)
        paragraphs.append(
            horizontal_paragraph(
                (RESIDUE_FILL * latin) + (TARGET_FILL * han), orphan, len(paragraphs)
            )
        )
    for latin in (60, 50, 40, 30, 20, int(rule[react_config.MIN_CHARS_KEY])):
        paragraphs.append(
            horizontal_paragraph(RESIDUE_FILL * latin, other, len(paragraphs))
        )

    docs = il_version_1.Document(page=[framed_page(paragraphs)], total_pages=1)
    return docs, [f"p1#{index}" for index in expected]


def detected(docs):
    context = detectors.build_context(
        docs, detectors.detector_config(), LANGUAGE, None, translation_performed=True
    )
    return detectors.run_detectors(context)


# --- the cases ----------------------------------------------------------------


def build_cases() -> dict:
    """Every case: its findings, its expectation and where it came from."""
    config = repair_config()
    points = json.loads((INPUTS / "decision_points.json").read_text(encoding="utf-8"))
    cases: dict[str, dict] = {}

    for name, meta in points.items():
        issues = frozen_issues(INPUTS / f"{name}.issues.json")
        cases[name] = {
            "kind": "replay",
            "issues": issues,
            "expect_action": contain.NAME,
            "expect_ids": sorted(contains_qualify(config, issues)),
            "declared_target": meta["target"],
            "historical_cache_key": meta["cache_key"],
            "b9_5_decision": meta["b9_5_decision"],
            "qualifying": qualifying(config, issues),
        }

    issues = detected(synthetic_document(config))
    cases["synthetic_contain"] = {
        "kind": "synthetic",
        "issues": issues,
        "expect_action": contain.NAME,
        "expect_ids": sorted(contains_qualify(config, issues)),
        "qualifying": qualifying(config, issues),
    }

    docs, references = spectrum_document(config)
    issues = detected(docs)
    wanted = set(references)
    cases["orphan_spectrum"] = {
        "kind": "regression",
        "issues": issues,
        "expect_action": orphan_actions.NAME,
        "expect_ids": [
            issue.id for issue in issues if set(issue.paragraph_refs) & wanted
        ],
        "qualifying": qualifying(config, issues),
    }
    return cases


def as_record(issue) -> dict:
    return {
        "id": issue.id,
        "kind": issue.kind,
        "severity": issue.severity,
        "page": issue.page,
        "paragraph_refs": list(issue.paragraph_refs),
        "evidence": dict(issue.evidence),
    }


# --- the run ------------------------------------------------------------------


def load_dotenv() -> None:
    """Read the repository .env for a credential the shell does not carry."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def build_engine() -> OpenAITranslator:
    load_dotenv()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set; this driver spends a credential")
    return OpenAITranslator(
        lang_in="en",
        lang_out=LANGUAGE,
        model=MODEL,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=key,
        ignore_cache=True,
    )


def merge_lines(path: Path, lines: list[str]) -> None:
    """Append this invocation's entries, keeping any other case in the round."""
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    written = {json.loads(line)["case"] for line in lines}
    keep = [
        line
        for line in existing
        if line.strip() and json.loads(line)["case"] not in written
    ]
    path.write_text("\n".join([*keep, *lines]) + "\n", encoding="utf-8")


def merge_json(path: Path, payload: dict) -> None:
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    stored.update(payload)
    path.write_text(
        json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def replay_provenance(case: str, issues) -> dict:
    """What proves a replayed request is the one batch b9.5 sent.

    A pure function of the frozen inputs: their findings, b9.5's prompt file and
    b9.5's repair configuration, none of which the tree can move. It carries no
    sampling, so a round recorded before this was read from the frozen
    configuration can be brought up to date without asking a model anything.
    """
    points = json.loads((INPUTS / "decision_points.json").read_text(encoding="utf-8"))
    historical = prompt_loader.load_prompt(
        decide.DECIDE_PROMPT,
        request_blocks(historical_config(), issues),
        directory=HISTORICAL_PROMPT_DIR,
    )
    key = decide.cache_key(historical, IDENTITY)
    return {
        "historical_cache_key": key,
        "reproduces_b9_5": key == points[case]["cache_key"],
    }


def restate_provenance(directory: Path) -> None:
    """Rewrite one round's provenance fields from the frozen inputs."""
    stored = json.loads((directory / DECISIONS_NAME).read_text(encoding="utf-8"))
    for case in CASES:
        if stored.get(case, {}).get("case_kind") != "replay":
            continue
        issues = frozen_issues(INPUTS / f"{case}.issues.json")
        stored[case].update(replay_provenance(case, issues))
    merge_json(directory / DECISIONS_NAME, stored)
    print(f"{directory.name}: provenance restated")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    parser.add_argument("--case", action="append", default=None)
    parser.add_argument(
        "--provenance-only",
        action="store_true",
        help="recompute the replay provenance of a recorded round, no request",
    )
    args = parser.parse_args()

    directory = ROUNDS / args.round
    directory.mkdir(parents=True, exist_ok=True)

    if args.provenance_only:
        restate_provenance(directory)
        return 0

    set_translate_rate_limiter(QPS)
    engine = build_engine()
    identity = decide.engine_identity(engine, LANGUAGE)
    if identity != IDENTITY:
        raise SystemExit(f"engine identity is {identity!r}, expected {IDENTITY!r}")

    config = repair_config()
    client = decide.CachedDecisionClient(
        config,
        transport=decide.EngineTransport(engine),
        identity=identity,
        ignore_cache=True,
    )

    cases = build_cases()
    wanted = list(args.case or CASES)
    trace_lines: list[str] = []
    decisions: dict[str, dict] = {}
    issue_sets: dict[str, list[dict]] = {}

    for name in wanted:
        case = cases[name]
        issues = case["issues"]
        issue_sets[name] = [as_record(issue) for issue in issues]
        prompt = client.prompt(issues)
        entry = {
            "kind": "decide_prompt",
            "case": name,
            "prompt_file": f"{decide.DECIDE_PROMPT}.md",
            "prompt_sha256": prompt.digest,
            "request_sha256": hashlib.sha256(prompt.text.encode()).hexdigest(),
            "cache_key": decide.cache_key(prompt, identity),
            "prompt_text": prompt.text,
        }
        if case["kind"] == "replay":
            entry.update(replay_provenance(name, issues))
        trace_lines.append(json.dumps(entry, ensure_ascii=False))

        decision, log = client.decide(issues)
        trace_lines.append(
            json.dumps(
                {"kind": "decide_reply", "case": name, "replies": log.replies},
                ensure_ascii=False,
            )
        )
        chosen = list(decision.issue_ids)
        expected = list(case["expect_ids"])
        record = {
            "case_kind": case["kind"],
            "expect_action": case["expect_action"],
            "expect_ids": expected,
            "action": decision.action,
            "issue_ids": chosen,
            "parameters": decision.parameters,
            "reason": decision.reason,
            "attempts": decision.attempts,
            "violations": list(decision.violations),
            "action_matches": decision.action == case["expect_action"],
            "ids_match": sorted(chosen) == sorted(expected),
            "names_expected": bool(expected) and set(expected) <= set(chosen),
            "request_sha256": entry["request_sha256"],
            "prompt_sha256": entry["prompt_sha256"],
            "qualifying": case["qualifying"],
        }
        for key in ("declared_target", "b9_5_decision"):
            if key in case:
                record[key] = case[key]
        for key in ("historical_cache_key", "reproduces_b9_5"):
            if key in entry:
                record[key] = entry[key]
        decisions[name] = record
        print(
            f"{name}: {decision.action} {chosen} "
            f"(expected {case['expect_action']} {expected})"
        )

    merge_lines(directory / TRACE_NAME, trace_lines)
    merge_json(directory / DECISIONS_NAME, decisions)
    merge_json(directory / ISSUES_NAME, issue_sets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
