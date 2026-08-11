"""Gate script for batch B7 session three (the two-pass smoke with a real ruling).

Run from the repository root:

    python spec_checks/spec_check_b7_3.py

Exit code 0 when every assertion T7.3 answers for passes, 1 otherwise. Needs no
API key and makes no network request: the two passes were run once with a
credential and their evidence is frozen under examples/output/b7_3/, which is
what this gate reads.

01 is the metric maintenance the session carries: a candidate rendering may not
begin on a punctuation mark, and nothing else about the measurement moves.

02 is the frozen evidence. It is a gate over an artefact rather than over a
behaviour, so what it asserts is that the artefact says what the report says and
that it is internally consistent -- a report quoting numbers no file carries is
the failure mode this catches.

03 is what the ruling did: every ruled term at every occurrence, the page kind
provenance and the policy it flipped, the drop cap verdicts at the references
the ruling used, and the two controls the ruling did not name.

04 is the discipline: no paragraph changed without its prompt changing, and the
draft the second pass wrote is still the machine's own verdict.

05 is the scope: nothing upstream, nothing writing a decisions file, no page type
named in code, no non-ASCII prose in what this session adds.

Every assertion is static. There is no pipeline tier.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import drop_cap  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

BATCH_TAG = "batch-b7.3"

PYTHON = sys.executable

TOOL = "tools/term_consistency.py"
SMOKE_DIR = ROOT / "examples" / "output" / "b7_3"
EVIDENCE = SMOKE_DIR / "evidence.json"
REPORT = SMOKE_DIR / "smoke.report.md"
DRIVER = SMOKE_DIR / "scripts" / "run_smoke.py"
ANALYZER = SMOKE_DIR / "scripts" / "analyze_smoke.py"

# What the run recorded, and what the report quotes from it.
PASSES = ("pass1", "pass2")
SAMPLE = "Courier-en"
RULED_KIND_SOURCE = hitl.HUMAN_SOURCE

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Paths this session may change. Nothing under babeldoc/ at all: the session
# runs the pipeline, it does not modify it.
ALLOWED_PREFIXES = (
    "configs/",
    "prompts/",
    "reviews/",
    "tools/",
    "spec_checks/",
    "plans/",
    "examples/output/",
)
ALLOWED_FILES = {"UPSTREAM_DIFF.md", "WAIVERS.md"}

_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b7_3_"))

# The gate never writes a review draft into the working tree it asserts about.
os.environ[hitl.REVIEWS_ENV] = str(_tmp_root / "reviews")

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b7_3")


def record(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _total
    _total += 1
    seconds = _timer.mark(name)
    if ok:
        _passed += 1
        print(f"PASS: {name} ({seconds:.2f}s)")
    else:
        _failures.append(f"{name}: {detail}")
        print(f"FAIL: {name}: {detail} ({seconds:.2f}s)")


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def changed_paths() -> set[str]:
    """This batch's delta: its tag where it exists, the working tree otherwise."""
    code, _ = git_output(["rev-parse", "--verify", f"{BATCH_TAG}^{{commit}}"])
    if code == 0:
        _, listing = git_output(["diff", "--name-only", f"{BATCH_TAG}^..{BATCH_TAG}"])
        return {line.strip() for line in listing.splitlines() if line.strip()}
    _, listing = git_output(["diff", "--name-only", "HEAD"])
    paths = {line.strip() for line in listing.splitlines() if line.strip()}
    _, untracked = git_output(["status", "--porcelain", "--untracked-files=all"])
    for line in untracked.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def evidence() -> dict:
    with EVIDENCE.open(encoding="utf-8") as f:
        return json.load(f)


# --- 01 the metric maintenance ------------------------------------------------


def check_01_candidates_open_on_a_word() -> None:
    """Positive 1: a candidate rendering begins on a word, never on a mark.

    The batch-b6.3 sweep left two terms measured by a comma and the clause after
    it, under every setting of the tuning grid. The rule that removes them has to
    remove those and nothing else, so the generated set is checked against the
    unfiltered one: every piece that survives is a piece the old rule produced,
    and every piece that does not opens on punctuation.
    """
    import tools.term_consistency as tool

    config = tool.load_config()
    # Built from code points so this file stays ASCII: a full width comma, a
    # clause, an em dash and a name, which is the shape the sweep found.
    text = "".join(map(chr, (0xFF0C, 0x5B83, 0x4ECD, 0x7136, 0x2014, 0x2014, 0x6770)))
    unfiltered = {
        text[start : start + length]
        for length in range(config.candidate_min_chars, config.candidate_max_chars + 1)
        for start in range(0, len(text) - length + 1)
        if not any(char.isspace() for char in text[start : start + length])
    }
    generated = tool.candidates_from(text, config)
    opens_on_a_mark = [
        piece
        for piece in generated
        if unicodedata.category(piece[0]).startswith("P")
    ]
    removed = unfiltered - generated
    faults = []
    if opens_on_a_mark:
        faults.append(f"candidates opening on a mark: {sorted(opens_on_a_mark)}")
    if not generated <= unfiltered:
        faults.append("the rule invented candidates the old one did not produce")
    if not removed:
        faults.append("the rule removed nothing from a text that opens on a comma")
    surviving = [
        piece for piece in removed if not unicodedata.category(piece[0]).startswith("P")
    ]
    if surviving:
        faults.append(f"removed pieces that do not open on a mark: {sorted(surviving)}")
    record("check_01_candidates_open_on_a_word", not faults, "; ".join(faults))


# --- 02 the frozen evidence ---------------------------------------------------


def check_02a_artefacts_present() -> None:
    """Positive 2a: the run left the files the report is written from."""
    wanted = [
        EVIDENCE,
        REPORT,
        DRIVER,
        ANALYZER,
        SMOKE_DIR / "runs.json",
        *(SMOKE_DIR / which / f"{SAMPLE}{suffix}" for which in PASSES
          for suffix in (hitl.REVIEW_SUFFIX, hitl.REVIEW_HTML_SUFFIX, hitl.DECISIONS_SUFFIX)),
    ]
    missing = [str(path.relative_to(ROOT)) for path in wanted if not path.exists()]
    record("check_02a_artefacts_present", not missing, f"missing {missing}")


def check_02b_evidence_is_self_consistent() -> None:
    """Positive 2b: the histogram, the paragraph list and the ledger agree."""
    data = evidence()
    totals = data["totals"]
    changed = data["changed_paragraphs"]
    faults = []
    if totals["unchanged"] + totals["changed"] != totals["paragraphs"]:
        faults.append("changed and unchanged do not sum to the paragraph count")
    if len(changed) != totals["changed"]:
        faults.append(f"{len(changed)} rows against {totals['changed']} changed")
    if sum(totals["by_cause"].values()) != totals["changed"]:
        faults.append("the cause histogram does not sum to the changed count")
    for cause, count in totals["by_cause"].items():
        actual = sum(1 for row in changed if row["cause"] == cause)
        if actual != count:
            faults.append(f"cause {cause}: {actual} rows against {count}")
    for which in PASSES:
        if which not in data["cost"]:
            faults.append(f"no cost recorded for {which}")
    record("check_02b_evidence_is_self_consistent", not faults, "; ".join(faults))


def check_02c_ruling_matches_the_file() -> None:
    """Positive 2c: the applied ruling is the file the human wrote, entry for entry."""
    data = evidence()
    written = data["decisions"]
    applied = data["apply_report"]
    faults = []
    entries = {
        entry["source"]: entry["target"]
        for entry in applied.get("terms", {}).get("entries", ())
    }
    if entries != written.get("terms", {}):
        faults.append(f"terms applied {entries} against ruled {written.get('terms')}")
    ruled_pages = {
        str(record_["page"]): record_["kind"]
        for record_ in applied.get("page_kinds", ())
    }
    if ruled_pages != written.get("page_kinds", {}):
        faults.append(f"page kinds applied {ruled_pages}")
    ruled_caps = {
        record_["paragraph"]: record_["decision"]
        for record_ in applied.get("drop_caps", ())
    }
    if ruled_caps != written.get("drop_caps", {}):
        faults.append(f"drop caps applied {ruled_caps}")
    # The file in the working tree is the one the run read, unedited since. The
    # default directory is named rather than asked for: this gate redirects the
    # review directory so that nothing it does can write into the tree.
    ruling = hitl.DEFAULT_REVIEWS_DIR / f"{SAMPLE}{hitl.DECISIONS_SUFFIX}"
    with ruling.open(encoding="utf-8") as f:
        if json.load(f) != written:
            faults.append(f"{ruling.name} no longer matches the run")
    record("check_02c_ruling_matches_the_file", not faults, "; ".join(faults))


# --- 03 what the ruling did ---------------------------------------------------


def check_03a_every_ruled_occurrence_moved() -> None:
    """Positive 3a: each ruled source carries its ruled target at every occurrence."""
    data = evidence()
    ruled = data["decisions"]["terms"]
    faults = []
    for source, target in ruled.items():
        rows = data["terms"].get(source)
        if not rows:
            faults.append(f"{source!r}: no occurrence recorded")
            continue
        for row in rows:
            if target not in row["pass2"]:
                faults.append(f"{source!r} at {row['paragraph']}: target absent")
            if row["identical"]:
                faults.append(f"{source!r} at {row['paragraph']}: unchanged")
    record("check_03a_every_ruled_occurrence_moved", not faults, "; ".join(faults))


def check_03b_unruled_terms_did_not_move() -> None:
    """Negative 3b: a source no ruling names renders the same in both passes.

    The controls are the terms the report quotes as controls: they are in the
    evidence and are not in the ruling, which is what makes them controls.
    """
    data = evidence()
    ruled = set(data["decisions"]["terms"])
    controls = [source for source in data["terms"] if source not in ruled]
    faults = []
    if not controls:
        faults.append("no unruled term was measured")
    for source in controls:
        for row in data["terms"][source]:
            # A paragraph that also carries a ruled name is expected to move;
            # what the control asserts is the rendering of the control itself.
            carries_ruled = any(
                row["paragraph"] == other["paragraph"]
                for name in ruled
                for other in data["terms"].get(name, ())
            )
            if not row["identical"] and not carries_ruled:
                faults.append(f"{source!r} at {row['paragraph']} moved")
    record("check_03b_unruled_terms_did_not_move", not faults, "; ".join(faults))


def check_03c_page_kind_override_travels() -> None:
    """Positive 3c: the ruled page carries the human provenance and flips policy."""
    data = evidence()
    policy = load_taxonomy().policy_of
    faults = []
    ruled = {int(page): kind for page, kind in data["decisions"]["page_kinds"].items()}
    for row in data["page_kinds"]:
        before, after = row["pass1"], row["pass2"]
        if row["page"] in ruled:
            if after["kind"] != ruled[row["page"]]:
                faults.append(f"page {row['page']}: kind {after['kind']}")
            if after["source"] != RULED_KIND_SOURCE:
                faults.append(f"page {row['page']}: source {after['source']}")
            if after["conf"] != hitl.HUMAN_CONF:
                faults.append(f"page {row['page']}: conf {after['conf']}")
            if before["source"] == RULED_KIND_SOURCE:
                faults.append(f"page {row['page']}: pass one already claimed a human")
            if dict(policy(before["kind"])) == dict(policy(after["kind"])):
                faults.append(f"page {row['page']}: the override changed no policy")
        elif before != after:
            faults.append(f"page {row['page']}: unruled page changed {before} {after}")
    # The policy travelled: the ruled page left the grouping it was in.
    first = {tuple(article["pages"]) for article in data["articles"]["pass1"]}
    second = {tuple(article["pages"]) for article in data["articles"]["pass2"]}
    if first == second:
        faults.append("the grouping is the same in both passes")
    if not data["unassigned"]["pass2"]:
        faults.append("no page was left unassigned by the override")
    if data["unassigned"]["pass1"]:
        faults.append("pass one already had an unassigned page")
    record("check_03c_page_kind_override_travels", not faults, "; ".join(faults))


def check_03d_drop_cap_verdicts_written() -> None:
    """Positive 3d: the verdicts reach the intermediate language, and only on pass two."""
    data = evidence()
    ruled = data["decisions"]["drop_caps"]
    written = {row["paragraph"]: row for row in data["drop_cap_decisions"]["pass2"]}
    faults = []
    if data["drop_cap_decisions"]["pass1"]:
        faults.append("pass one wrote a verdict with no ruling applied")
    if set(written) != set(ruled):
        faults.append(f"written {sorted(written)} against ruled {sorted(ruled)}")
    for reference, verdict in ruled.items():
        row = written.get(reference)
        if row is None:
            continue
        if row["decision"] != verdict:
            faults.append(f"{reference}: {row['decision']} against {verdict}")
        # The reference format is the one both files speak, not a local guess.
        page, _, index = reference.partition("#")
        if drop_cap.paragraph_reference(int(page[1:]), int(index)) != reference:
            faults.append(f"{reference}: not the declared reference format")
    record("check_03d_drop_cap_verdicts_written", not faults, "; ".join(faults))


# --- 04 the discipline --------------------------------------------------------


def check_04a_no_unexplained_perturbation() -> None:
    """Negative 4a: no paragraph changed whose prompt did not.

    This is the claim the batch is for. A ruling is allowed to move what it names
    and what shares a prompt with what it names; a translation that moved under
    an unchanged prompt is the thing that would mean the loop is not controlled.
    """
    data = evidence()
    faults = []
    for row in data["changed_paragraphs"]:
        if row["cause"] in ("unexplained", "prompt_not_recorded"):
            faults.append(f"{row['paragraph']}: {row['cause']}")
        elif not row["prompt_sections_changed"]:
            faults.append(f"{row['paragraph']}: no prompt section changed")
    if not data["changed_paragraphs"]:
        faults.append("nothing changed at all, so nothing was explained")
    record("check_04a_no_unexplained_perturbation", not faults, "; ".join(faults))


def check_04b_second_draft_is_the_machine_verdict() -> None:
    """Positive 4b: the draft the applying pass wrote records the machine, not the human.

    The two drafts are compared with the article ids taken out, which are minted
    afresh on every run and name nothing across passes.
    """
    drafts = []
    for which in PASSES:
        draft_path = SMOKE_DIR / which / f"{SAMPLE}{hitl.REVIEW_SUFFIX}"
        with draft_path.open(encoding="utf-8") as f:
            draft = json.load(f)
        for row in draft.get("drop_caps", ()):
            row.pop("article_id", None)
        drafts.append(draft)
    faults = []
    if drafts[0] != drafts[1]:
        faults.append("the two drafts differ in more than their article ids")
    ruled = evidence()["decisions"]["page_kinds"]
    for row in drafts[1].get("page_kinds", ()):
        if str(row["page"]) in ruled and row["machine_kind"] == ruled[str(row["page"])]:
            faults.append(f"page {row['page']}: the draft adopted the ruling")
        if row["source"] == RULED_KIND_SOURCE:
            faults.append(f"page {row['page']}: the draft claims a human decided it")
    record("check_04b_second_draft_is_the_machine_verdict", not faults, "; ".join(faults))


# --- 05 the scope -------------------------------------------------------------


def check_05a_no_upstream_change() -> None:
    """Negative 5a: this batch changes no file under babeldoc/ at all."""
    changed = changed_paths()
    upstream = sorted(path for path in changed if path.startswith("babeldoc/"))
    stray = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES and not path.startswith(ALLOWED_PREFIXES)
    )
    faults = []
    if upstream:
        faults.append(f"babeldoc/ changed: {upstream}")
    if stray:
        faults.append(f"outside the declared paths: {stray}")
    if "corpus/registry.user.json" in changed:
        faults.append("the corpus registry was edited")
    record("check_05a_no_upstream_change", not faults, "; ".join(faults))


def check_05b_nothing_writes_a_decisions_file() -> None:
    """Negative 5b: no code in the session opens a decisions file for writing."""
    faults = []
    for relative in (
        "babeldoc/magazine/hitl.py",
        TOOL,
        str(DRIVER.relative_to(ROOT)).replace("\\", "/"),
        str(ANALYZER.relative_to(ROOT)).replace("\\", "/"),
        f"spec_checks/{Path(__file__).name}",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            named = getattr(function, "attr", None) or getattr(function, "id", None)
            if named not in ("open", "write_text"):
                continue
            source = ast.unparse(function)
            if "decisions_path" not in source:
                continue
            arguments = [ast.unparse(argument) for argument in node.args]
            if any("w" in argument for argument in arguments):
                faults.append(f"{relative}:{node.lineno} opens a ruling for writing")
    # The driver copies the ruling into the frozen run; that is a read.
    if "shutil.copyfile(decisions" not in DRIVER.read_text(encoding="utf-8"):
        faults.append("the driver no longer freezes the ruling it ran under")
    record("check_05b_nothing_writes_a_decisions_file", not faults, "; ".join(faults))


def check_05c_no_vocabulary_literals() -> None:
    """Negative 5c: no page type name is written into the session's code."""
    declared = set(load_taxonomy().names())
    faults = []
    for relative in (
        TOOL,
        str(DRIVER.relative_to(ROOT)).replace("\\", "/"),
        str(ANALYZER.relative_to(ROOT)).replace("\\", "/"),
        f"spec_checks/{Path(__file__).name}",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(text)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and node.value in declared
            ):
                faults.append(f"{relative}:{node.lineno} names {node.value!r}")
    record("check_05c_no_vocabulary_literals", not faults, "; ".join(faults))


def check_05d_ascii_prose() -> None:
    """Negative 5d: the code this session adds carries no non-ASCII prose."""
    faults = []
    for relative in (
        TOOL,
        str(DRIVER.relative_to(ROOT)).replace("\\", "/"),
        str(ANALYZER.relative_to(ROOT)).replace("\\", "/"),
        f"spec_checks/{Path(__file__).name}",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.isascii():
                faults.append(f"{relative}:{number}")
    record("check_05d_ascii_prose", not faults, "; ".join(faults[:5]))


# --- 06 the sweep -------------------------------------------------------------


def check_06_sweep() -> None:
    """Positive 6: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_06_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_06_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01_candidates_open_on_a_word,
        check_02a_artefacts_present,
        check_02b_evidence_is_self_consistent,
        check_02c_ruling_matches_the_file,
        check_03a_every_ruled_occurrence_moved,
        check_03b_unruled_terms_did_not_move,
        check_03c_page_kind_override_travels,
        check_03d_drop_cap_verdicts_written,
        check_04a_no_unexplained_perturbation,
        check_04b_second_draft_is_the_machine_verdict,
        check_05a_no_upstream_change,
        check_05b_nothing_writes_a_decisions_file,
        check_05c_no_vocabulary_literals,
        check_05d_ascii_prose,
        check_06_sweep,
    ]
    try:
        for check in checks:
            try:
                check()
            except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
                record(check.__name__, False, f"raised {exc!r}")
        print(f"\nspec_check_b7_3: {_passed}/{_total} assertions passed")
        for failure in _failures:
            print(f"  - {failure}")
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_b7_3")
    finally:
        shutil.rmtree(_tmp_root, ignore_errors=True)
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
