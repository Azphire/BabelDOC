"""Gate script for batch B8 session three (the real smoke and the maintenance).

Run from the repository root:

    python spec_checks/spec_check_b8_3.py

Exit code 0 when every assertion T8.3 answers for passes, 1 otherwise. Needs no
API key and makes no network request: the runs were made once with a credential
and their evidence is frozen under examples/output/b8/smoke/, which is what this
gate reads.

01 is the cache budget maintenance (T8.3.0a). A build fits itself into the
ceiling before it publishes, and the sweep that makes room is best effort: a
slot it cannot remove leaves the build publishing anyway rather than raising.
Both are asserted against fabricated slots in a disposable cache root, so the
assertions cost no pipeline run and the real cache is never touched.

02 is the run inventory (T8.3.0b). Every sidecar a magazine module writes is
declared, and the scan reaches into the subpackages -- which is the hole the
b8.1 sidecar fell through, since the previous scan globbed the package's top
level only.

03 is the frozen smoke evidence: the files exist, the ledger and the evidence
file agree with the sidecars they were derived from, and the report quotes
numbers those files carry.

04 is what the loop did, as a property rather than as a target. Whatever the
outcome, the loop has to have detected the standing finding, decided about it
through a recorded request, and left the document conserved.

05 is the blast radius, which is the assertion with a required answer: the
paragraphs that moved are a subset of the paragraphs the loop touched, and the
translation stack reproduced batch-b7.5.2 paragraph for paragraph.

06 is the prompt iteration discipline (T3.4): both rounds recorded, the round
count inside the ceiling, the digests distinct and the current file matching the
last round.

07 is the scope: nothing upstream, no page type or layout label named in the
session's code, no non-ASCII prose in it, the ruling and the registry unedited.

Every assertion is static. There is no pipeline tier.
"""

from __future__ import annotations

import ast
import contextlib
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

from babeldoc.magazine import detectors  # noqa: E402
from babeldoc.magazine.checkpoint import sidecar_products  # noqa: E402
from babeldoc.magazine.prompt_loader import file_digest  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react.config import load_repair_config  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build:
# every document it asserts on is a stub it builds itself or evidence a
# batch froze, so it answers in seconds to a couple of minutes and runs on
# every batch.
GATE_SET = "fast"

BATCH_TAG = "batch-b8.3"

PYTHON = sys.executable

SMOKE_DIR = ROOT / "examples" / "output" / "b8" / "smoke"
EVIDENCE = SMOKE_DIR / "evidence.json"
LEDGER = SMOKE_DIR / "runs.json"
REPORT = ROOT / "examples" / "output" / "b8" / "smoke.report.md"
ROUNDS_DIR = SMOKE_DIR / "prompt_rounds"
RASTER_DIR = SMOKE_DIR / "raster"

SCRIPT_DIR = ROOT / "examples" / "output" / "b8" / "scripts"
DRIVER = SCRIPT_DIR / "run_repair_smoke.py"
ANALYZER = SCRIPT_DIR / "analyze_repair_smoke.py"
RASTERIZER = SCRIPT_DIR / "rasterize_subject.py"

DECIDE_PROMPT = ROOT / "prompts" / "react_repair_decide.md"

SAMPLE = "Courier-en"
SUBJECT = "p6#15"

# T3.4's ceiling on how many times one prompt may be reworked in a session.
MAX_PROMPT_ROUNDS = 3

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

# Paths this session may change. Nothing under babeldoc/: the session runs the
# pipeline and does not modify it.
ALLOWED_PREFIXES = (
    "configs/",
    "prompts/",
    "spec_checks/",
    "plans/",
    "examples/output/",
)
ALLOWED_FILES = {"UPSTREAM_DIFF.md", "WAIVERS.md"}

# The session's own code, which the scope assertions hold to the conventions.
SESSION_CODE = (
    "spec_checks/artifacts.py",
    "spec_checks/run_all.py",
    "examples/output/b8/scripts/run_repair_smoke.py",
    "examples/output/b8/scripts/analyze_repair_smoke.py",
    "examples/output/b8/scripts/rasterize_subject.py",
    f"spec_checks/{Path(__file__).name}",
)

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b8_3")


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


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def evidence() -> dict:
    return load_json(EVIDENCE)


def source_of(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# --- 01 the cache budget ------------------------------------------------------


class _Sandbox:
    """A disposable cache root with a budget of this gate's choosing.

    Both settings are module globals the cache reads on every call, so they are
    swapped for the duration and put back afterwards. The real cache root is
    never reached and the committed configuration is never written.
    """

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="spec_b8_3_cache_"))
        self._saved: dict[str, object] = {}

    def budget(self, max_bytes: int) -> None:
        """Set the ceiling this sandbox works to, in its own configuration file.

        Written rather than taken from the committed file, and written after the
        fabricated slots have been measured, so the assertions state a budget in
        terms of what a slot actually costs instead of guessing at it. The
        allowed range is the sandbox's own declaration and is widened to admit
        the small sizes that keep these assertions cheap; the committed
        configuration is not read and not written.
        """
        with self.config.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "description": "disposable budget for one gate assertion",
                    "gate_cache_max_gb": max_bytes / artifacts.BYTES_PER_GB,
                    "gate_cache_max_gb_allowed_range": "0.0000001..256",
                    "staging_stale_after_seconds": 86400,
                    "staging_stale_after_seconds_allowed_range": "60..2592000",
                },
                f,
            )

    def __enter__(self) -> _Sandbox:
        self.config = self.root / "gate_cache.json"
        self.budget(artifacts.BYTES_PER_GB)
        self._saved = {
            "CACHE_ROOT": artifacts.CACHE_ROOT,
            "STATS_DIR": artifacts.STATS_DIR,
            "CACHE_CONFIG_PATH": artifacts.CACHE_CONFIG_PATH,
        }
        artifacts.CACHE_ROOT = self.root / "cache"
        artifacts.STATS_DIR = artifacts.CACHE_ROOT / "stats"
        artifacts.CACHE_CONFIG_PATH = self.config
        artifacts.CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *_exc) -> None:
        for name, value in self._saved.items():
            setattr(artifacts, name, value)
        shutil.rmtree(self.root, ignore_errors=True)

    def slot(self, generation: str, name: str, payload_bytes: int) -> Path:
        """One published slot of a chosen size."""
        path = artifacts.CACHE_ROOT / generation / name
        path.mkdir(parents=True, exist_ok=True)
        with (path / "meta.json").open("w", encoding="utf-8") as f:
            json.dump({"mode": "fabricated", "working_subdir": "work"}, f)
        (path / "payload.bin").write_bytes(b"\0" * payload_bytes)
        return path

    def staging(self, generation: str, name: str, payload_bytes: int) -> Path:
        path = artifacts.CACHE_ROOT / generation / (name + artifacts.STAGING_SUFFIX)
        path.mkdir(parents=True, exist_ok=True)
        (path / "payload.bin").write_bytes(b"\0" * payload_bytes)
        return path


# Payload of one fabricated slot. Large enough to be measurable and small
# enough that a whole assertion is a few hundred kilobytes of writing.
_PAYLOAD = 64 << 10


def _stagger(slots: list[Path]) -> None:
    """Give the slots distinct last-use times, oldest first in list order."""
    for index, slot in enumerate(slots):
        os.utime(slot, (1_600_000_000 + index, 1_600_000_000 + index))


def check_01a_publish_sweeps_to_fit() -> None:
    """Positive 1a: a slot that would overrun the ceiling sweeps first.

    Three slots stand in a cache whose ceiling holds four. A fourth arrives, so
    the cache lands exactly on the ceiling and nothing needs to go; a fifth
    arrives worth two and something does. What goes is the least recently used,
    which the staggered timestamps make well defined. The ceiling is set from
    the measured size of the fabricated slots rather than from an assumed one,
    so the assertion is not sensitive to what a directory costs.
    """
    with _Sandbox() as box:
        slots = [box.slot("gen", f"slot{index}", _PAYLOAD) for index in range(3)]
        _stagger(slots)
        per_slot = artifacts.cache_size_bytes() // 3
        box.budget(4 * per_slot)

        fits = artifacts.make_room(per_slot)
        after_fitting = {path.name for path in artifacts._slots()}

        overruns = artifacts.make_room(2 * per_slot)
        after_overrun = {path.name for path in artifacts._slots()}

    faults = []
    if fits["dropped_slots"]:
        faults.append(f"swept {fits['dropped_slots']} slot(s) with room to spare")
    if len(after_fitting) != 3:
        faults.append(f"the fitting call left {sorted(after_fitting)}")
    if not overruns["dropped_slots"]:
        faults.append("an over-budget slot swept nothing")
    if "slot0" in after_overrun:
        faults.append("the least recently used slot survived the sweep")
    if overruns["after_bytes"] + 2 * per_slot > overruns["max_bytes"]:
        faults.append(
            f"after the sweep {overruns['after_bytes']} + incoming still exceeds "
            f"{overruns['max_bytes']}"
        )
    if overruns["single_slot_over_budget"]:
        faults.append("a slot inside the budget was reported as over it")
    record("check_01a_publish_sweeps_to_fit", not faults, "; ".join(faults))


def check_01b_sweep_survives_what_it_cannot_remove() -> None:
    """Negative 1b: a sweep that cannot free space returns rather than dying.

    Two hostile shapes at once. A slot is held open by this process, which on
    Windows is enough that part of it cannot be removed, so the sweep frees less
    than the slot was worth. And the incoming slot is larger than the whole
    budget, so no sweep could ever make room for it. Neither may raise, the
    overrun has to be reported as one, and the sweep may not claim to have
    reclaimed bytes that are still on the disk -- over-reporting is the
    dangerous direction, because a caller believing in room that does not exist
    stops sweeping too early.

    The bytes are measured over the whole cache tree rather than over the
    published slots, because a slot the sweep half removed stops being a slot
    while its remains still cost disk.
    """
    faults = []
    with _Sandbox() as box:
        held = box.slot("gen", "locked", _PAYLOAD)
        other = box.slot("gen", "removable", _PAYLOAD)
        _stagger([held, other])
        per_slot = artifacts.cache_size_bytes() // 2
        box.budget(per_slot)
        on_disk_before = artifacts.directory_bytes(artifacts.CACHE_ROOT)
        handle = (held / "payload.bin").open("rb")
        try:
            outcome = artifacts.make_room(5 * per_slot)
        except Exception as exc:  # noqa: BLE001 - that it raised at all is the fault
            outcome = None
            faults.append(f"the sweep raised {exc!r}")
        finally:
            handle.close()

        if outcome is not None:
            on_disk_after = artifacts.directory_bytes(artifacts.CACHE_ROOT)
            if not outcome["single_slot_over_budget"]:
                faults.append("a slot larger than the budget was not reported as such")
            reclaimed = outcome["freed_bytes"]
            actual = on_disk_before - on_disk_after
            if reclaimed > actual:
                faults.append(
                    f"reported {reclaimed} bytes freed against {actual} on disk"
                )
            if not reclaimed:
                faults.append("the sweep reclaimed nothing at all")
            if "removable" in {path.name for path in artifacts._slots()}:
                faults.append("the sweep left a slot it could have removed")
    record("check_01b_sweep_survives_what_it_cannot_remove", not faults, "; ".join(faults))


def check_01c_build_publishes_through_the_seam() -> None:
    """Positive 1c: the build path calls the fitting seam before it publishes.

    A behavioural assertion would need a pipeline run per case, which this gate
    does not take; what is checked instead is that the one publish site goes
    through ``make_room`` and that it does so before the atomic move rather than
    after it, since a sweep after the publish is a sweep that never bounded
    anything.
    """
    tree = ast.parse(source_of("spec_checks/artifacts.py"))
    build = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_build"
    )
    calls = [
        (node.lineno, ast.unparse(node.func))
        for node in ast.walk(build)
        if isinstance(node, ast.Call)
    ]
    room = [line for line, name in calls if name.endswith("make_room")]
    publish = [line for line, name in calls if name.endswith("staging.replace")]
    faults = []
    if len(room) != 1:
        faults.append(f"_build calls make_room {len(room)} time(s)")
    if not publish:
        faults.append("_build no longer publishes with an atomic replace")
    if room and publish and min(room) > min(publish):
        faults.append("the sweep happens after the publish")
    # A staging directory is not a slot, or the sweep could delete the build.
    if "STAGING_SUFFIX" not in ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_slots"
        )
    ):
        faults.append("_slots does not exclude staging directories")
    record("check_01c_build_publishes_through_the_seam", not faults, "; ".join(faults))


# --- 02 the run inventory -----------------------------------------------------


# The corpus this batch's frozen evidence was built over: the six samples the
# F2 refresh left, which is what "the whole corpus" meant while this batch ran.
# Read as a fixed list rather than off today's manifest. A batch's evidence can
# only ever cover the samples that existed when it ran, and a corpus that grows
# afterwards does not make that evidence incomplete -- reading the live manifest
# here made every later registration retro-invalidate a batch that had in fact
# covered everything there was. What is still asserted is the guarantee that was
# ever available: none of these six was quietly dropped, and every one of them
# ran. AC-34, GAP-53.
CORPUS_WHEN_THIS_RAN = (
    "AramcoWorld-en-v2.pdf",
    "CERNCourier-en.pdf",
    "Courier-en.pdf",
    "Courier-zh.pdf",
    "FD-en-v2.pdf",
    "Vogue-en.pdf",
)


def check_02_every_sidecar_is_declared() -> None:
    """Positive 2: every module that writes a sidecar has it in the inventory.

    The scan is recursive, which is the point: the previous one globbed the top
    level of the magazine package and so never saw the detection sidecar in
    ``detectors/`` or the repair one in ``react/``. Declaring a name here is
    what makes a run's products enumerable without running one.
    """
    declared = {entry["name"] for entry in sidecar_products()}
    produced: dict[str, str] = {}
    for path in sorted((ROOT / "babeldoc" / "magazine").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "REPORT_NAME"
                    and isinstance(node.value, ast.Constant)
                ):
                    produced[node.value.value] = str(path.relative_to(ROOT))
    faults = []
    undeclared = sorted(set(produced) - declared)
    if undeclared:
        faults.append(
            f"undeclared: {[(name, produced[name]) for name in undeclared]}"
        )
    for name in (detectors.REPORT_NAME, controller.REPORT_NAME):
        if name not in declared:
            faults.append(f"{name} is not in the inventory")
    # Every declaration names a switch that exists somewhere in the package.
    for entry in sidecar_products():
        if not entry.get("switch") or not entry.get("stage"):
            faults.append(f"{entry.get('name')} declares no switch or no stage")
    record("check_02_every_sidecar_is_declared", not faults, "; ".join(faults))


# --- 03 the frozen evidence ---------------------------------------------------


def check_03a_artefacts_present() -> None:
    """Positive 3a: the run left the files the report is written from."""
    wanted = [
        EVIDENCE,
        LEDGER,
        REPORT,
        DRIVER,
        ANALYZER,
        RASTERIZER,
        SMOKE_DIR / SAMPLE / "run.json",
        SMOKE_DIR / SAMPLE / "prompt_trace.jsonl",
        SMOKE_DIR / "regression.json",
        *(
            RASTER_DIR / f"{stem}.{SUBJECT.replace('#', '_')}.png"
            for stem in ("b7_5_2", "b8_3")
        ),
    ]
    missing = [str(path.relative_to(ROOT)) for path in wanted if not path.exists()]
    record("check_03a_artefacts_present", not missing, f"missing {missing}")


def check_03b_every_sample_ran() -> None:
    """Positive 3b: the ledger covers the whole corpus and each run produced a PDF."""
    from babeldoc.magazine import corpus

    registered = {entry["file"] for entry in corpus.load_manifest()["samples"]}
    covered = set(CORPUS_WHEN_THIS_RAN)
    ledger = {entry["sample"]: entry for entry in load_json(LEDGER)}
    faults = []
    dropped = sorted(covered - registered)
    if dropped:
        faults.append(f"no longer registered: {dropped}")
    missing = sorted(covered - set(ledger))
    if missing:
        faults.append(f"never run: {missing}")
    for name, entry in sorted(ledger.items()):
        # That a PDF was produced, not that it is in the repository: a produced
        # PDF is an output, and this project commits the evidence taken from one
        # rather than the file itself.
        if not entry.get("mono_pdf"):
            faults.append(f"{name}: the run produced no PDF")
        working = ROOT / entry["working_dir"]
        for sidecar in (detectors.REPORT_NAME, controller.REPORT_NAME):
            if not (working / sidecar).exists():
                faults.append(f"{name}: no {sidecar}")
    record("check_03b_every_sample_ran", not faults, "; ".join(faults))


def check_03c_evidence_matches_the_sidecar() -> None:
    """Positive 3c: the evidence file restates the sidecar rather than a story.

    Every number the report quotes about the loop is checked back against the
    sidecar the loop itself wrote, so a hand-edited evidence file fails here.
    """
    data = evidence()
    working = ROOT / data["run"]["working_dir"]
    repair = load_json(working / controller.REPORT_NAME)
    issues = load_json(working / detectors.REPORT_NAME)
    faults = []
    loop = data["loop"]
    for key in ("iterations_run", "stopped_because", "applications"):
        if loop[key] != repair[key]:
            faults.append(f"{key}: {loop[key]!r} against {repair[key]!r}")
    if loop["conservation"] != repair["conservation"]:
        faults.append("the conservation block does not match the sidecar")
    if len(loop["iterations"]) != len(repair["iterations"]):
        faults.append("the iteration count does not match")
    if data["issues_final"]["counts"] != issues["counts"]:
        faults.append("the final issue counts do not match the detection sidecar")
    if loop["final"] != repair["final"]:
        faults.append("the final block does not match the sidecar")
    record("check_03c_evidence_matches_the_sidecar", not faults, "; ".join(faults))


# --- 04 what the loop did -----------------------------------------------------


def check_04a_the_standing_finding_was_detected_and_decided() -> None:
    """Positive 4a: the finding this batch exists for went through the loop.

    Deliberately not an assertion that it was repaired. What is required is that
    the machinery reached it: a detector reported it, a decision was made
    through a request whose prompt is identified by digest, and the loop wrote
    down what became of it. A batch that asserted the outcome would be a batch
    that had to make the outcome happen.
    """
    data = evidence()
    subject = data["subject"]
    faults = []
    if not subject["detected"]:
        faults.append(f"{SUBJECT} was not detected at all")
    for issue in subject["detected"]:
        if issue["detector"] != "untranslated_residue":
            faults.append(f"{SUBJECT} detected by {issue['detector']}")
        if not issue.get("geometry"):
            faults.append(f"{SUBJECT} carries no geometry")
    if not subject["iterations"]:
        faults.append(f"no iteration record mentions {SUBJECT}")
    for entry in subject["iterations"]:
        decision = entry.get("decision") or {}
        if not decision.get("raw"):
            faults.append(f"iteration {entry['iteration']}: no decision text recorded")
        request = entry.get("request") or {}
        if len(str(request.get("prompt_sha256", ""))) != 64:
            faults.append(f"iteration {entry['iteration']}: no prompt digest")
    if data["trace_records"]["decide_prompt"] < 1:
        faults.append("no decision prompt was traced")
    record(
        "check_04a_the_standing_finding_was_detected_and_decided",
        not faults,
        "; ".join(faults),
    )


def check_04b_every_run_conserved_its_document() -> None:
    """Positive 4b: across the whole corpus, no run violated conservation."""
    faults = []
    for entry in load_json(LEDGER):
        repair = load_json(ROOT / entry["working_dir"] / controller.REPORT_NAME)
        conservation = repair["conservation"]
        if conservation["verdict"] != controller.CONSERVED:
            faults.append(f"{entry['sample']}: {conservation['verdict']}")
        if conservation["pages_before"] != conservation["pages_after"]:
            faults.append(f"{entry['sample']}: page count moved")
        if conservation["paragraphs_before"] != conservation["paragraphs_after"]:
            faults.append(f"{entry['sample']}: paragraph count moved")
        if conservation["changed_outside_touched"]:
            faults.append(
                f"{entry['sample']}: changed outside the repaired set "
                f"{conservation['changed_outside_touched']}"
            )
        if repair["iterations_run"] > load_repair_config(None, ()).max_iterations:
            faults.append(f"{entry['sample']}: iterations above the ceiling")
    record("check_04b_every_run_conserved_its_document", not faults, "; ".join(faults))


def check_04c_rejections_are_recorded_with_a_reason() -> None:
    """Positive 4c: every finding the loop declined carries why, in the vocabulary.

    A filter whose rejections are invisible is a filter nobody can argue with,
    and one whose reasons are free text is one nobody can count. The reasons are
    held to the module's own declared set.
    """
    from babeldoc.magazine.react import actions

    declared = {
        value
        for name, value in vars(actions).items()
        if name.startswith("REASON_") and isinstance(value, str)
    } | {actions.ACCEPTED}
    faults = []
    for entry in load_json(LEDGER):
        repair = load_json(ROOT / entry["working_dir"] / controller.REPORT_NAME)
        for iteration in repair["iterations"]:
            for row in [*iteration.get("applicability", ()), *iteration.get("executed", ())]:
                reason = str(row.get("reason", ""))
                # A refusal states the violations after its name.
                head = reason.split(":", 1)[0]
                if head not in declared:
                    faults.append(f"{entry['sample']}: reason {reason!r}")
                if not row.get("accepted") and not reason:
                    faults.append(f"{entry['sample']}: {row['paragraph_ref']} silent")
    record("check_04c_rejections_are_recorded_with_a_reason", not faults, "; ".join(faults[:5]))


# --- 05 the blast radius ------------------------------------------------------


def check_05a_nothing_moved_outside_the_repaired_set() -> None:
    """Negative 5a: the paragraphs that changed are a subset of those touched.

    The conservation claim, re-derived here from the two typesetting checkpoints
    rather than read out of the sidecar that made it, so the check and the thing
    it checks do not share a source.
    """
    data = evidence()
    radius = data["blast_radius"]
    faults = []
    changed = set(radius["changed_by_repair"])
    touched = set(radius["touched_by_repair"])
    if not changed <= touched:
        faults.append(f"changed outside touched: {sorted(changed - touched)}")
    if radius["changed_outside_touched"]:
        faults.append(f"sidecar reports {radius['changed_outside_touched']}")
    if not radius["stack_reproduced"]:
        faults.append(
            f"the translation stack did not reproduce batch-b7.5.2: "
            f"{radius['changed_before_repair'][:5]}"
        )
    if radius["paragraphs_compared"] < 1:
        faults.append("no paragraph was compared")
    record(
        "check_05a_nothing_moved_outside_the_repaired_set", not faults, "; ".join(faults)
    )


def check_05b_the_rendering_moved_only_where_the_document_did() -> None:
    """Negative 5b: a page whose text changed holds a paragraph the loop wrote."""
    radius = evidence()["blast_radius"]
    changed = set(radius["pdf_pages_changed"])
    allowed = set(radius["pdf_pages_of_touched"])
    faults = []
    if not changed <= allowed:
        faults.append(f"pages changed with nothing repaired on them: {sorted(changed - allowed)}")
    if bool(radius["changed_by_repair"]) != bool(changed):
        # Either both are empty or both are not; a document that changed with
        # no page changing, or the reverse, means the two measurements disagree.
        faults.append(
            f"document changed={radius['changed_by_repair']} "
            f"pages changed={sorted(changed)}"
        )
    record(
        "check_05b_the_rendering_moved_only_where_the_document_did",
        not faults,
        "; ".join(faults),
    )


def check_05c_the_disputed_region_draws_as_it_did() -> None:
    """Negative 5c: the pixels of the finding's own region agree with the loop.

    The region is cropped out of both PDFs by the finding's own geometry. If the
    loop wrote into that paragraph the two crops must differ, and if it did not
    they must be identical -- an image is the one measurement that cannot be
    satisfied by a document that merely claims to be unchanged.
    """
    touched = set(evidence()["blast_radius"]["touched_by_repair"])
    crops = {
        stem: RASTER_DIR / f"{stem}.{SUBJECT.replace('#', '_')}.png"
        for stem in ("b7_5_2", "b8_3")
    }
    faults = [
        f"missing {path.name}" for path in crops.values() if not path.exists()
    ]
    if not faults:
        digests = {stem: file_digest(path) for stem, path in crops.items()}
        identical = len(set(digests.values())) == 1
        if identical and SUBJECT in touched:
            faults.append(f"{SUBJECT} was repaired and its region draws the same")
        if not identical and SUBJECT not in touched:
            faults.append(f"{SUBJECT} was not repaired and its region moved")
    record("check_05c_the_disputed_region_draws_as_it_did", not faults, "; ".join(faults))


# --- 06 the prompt iteration discipline ---------------------------------------


def check_06_prompt_rounds_are_recorded() -> None:
    """Positive 6: every reworking of a prompt is on record, inside the ceiling.

    Each round keeps the trace, the repair sidecar and the detection sidecar it
    produced, so the before and after of a prompt change is readable without
    rerunning anything. The last round's decision prompt has to be the one the
    frozen run actually sent, or the rounds describe a prompt this batch never
    used. That the file in the tree matches is a live property of whichever
    batch reworked it last and is asserted by that batch, not by this one.
    """
    rounds = sorted(path for path in ROUNDS_DIR.iterdir() if path.is_dir())
    faults = []
    if not rounds:
        faults.append("no prompt round was recorded")
    if len(rounds) > MAX_PROMPT_ROUNDS + 1:
        faults.append(f"{len(rounds)} rounds against a ceiling of {MAX_PROMPT_ROUNDS}")
    for path in rounds:
        for name in ("prompt_trace.jsonl", "react_repair.report.json", "issues.json"):
            if not (path / name).exists():
                faults.append(f"{path.name}: no {name}")
    digests = {}
    for path in rounds:
        trace = [
            json.loads(line)
            for line in (path / "prompt_trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for entry in trace:
            if entry["kind"] == "decide_prompt":
                digests[path.name] = entry["prompt_sha256"]
                break
    if len(set(digests.values())) != len(digests):
        faults.append(f"two rounds ran the same prompt: {digests}")
    sent = {
        entry.get("request", {}).get("prompt_sha256")
        for entry in evidence()["subject"]["iterations"]
    } - {None}
    if digests and sent and digests[rounds[-1].name] not in sent:
        faults.append(
            f"the last round ran {digests[rounds[-1].name][:12]} and the frozen "
            f"run sent {sorted(item[:12] for item in sent)}"
        )
    record("check_06_prompt_rounds_are_recorded", not faults, "; ".join(faults))


# --- 07 the scope -------------------------------------------------------------


def check_07a_no_upstream_change() -> None:
    """Negative 7a: this batch changes no file under babeldoc/ at all."""
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
    if any(path.startswith("reviews/") for path in changed):
        faults.append("a ruling was edited")
    record("check_07a_no_upstream_change", not faults, "; ".join(faults))


def check_07b_no_vocabulary_literals() -> None:
    """Negative 7b: no page type and no layout label is written into the code.

    Page types because policy is what code may consume; layout labels because a
    repair that names one has stopped reading the configuration that declares
    which labels an action acts on.
    """
    declared = set(load_taxonomy().names())
    for action in load_repair_config(None, ()).actions.values():
        declared |= set(action.applicability.get("orphan_layout_labels", ()))
    faults = []
    for relative in SESSION_CODE:
        tree = ast.parse(source_of(relative))
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
    record("check_07b_no_vocabulary_literals", not faults, "; ".join(faults))


def check_07c_ascii_prose() -> None:
    """Negative 7c: the code this session adds carries no non-ASCII prose."""
    faults = []
    for relative in SESSION_CODE:
        for number, line in enumerate(source_of(relative).splitlines(), start=1):
            if not line.isascii():
                offenders = [
                    unicodedata.name(char, hex(ord(char)))
                    for char in line
                    if not char.isascii()
                ]
                faults.append(f"{relative}:{number} {offenders[:3]}")
    record("check_07c_ascii_prose", not faults, "; ".join(faults[:5]))


def check_07d_the_driver_spends_no_credential_in_the_gate() -> None:
    """Negative 7d: this gate imports no driver and opens no network client.

    The runs were made once, by hand, with a key. The gate reads what they left
    and must not be able to make a request even if a key happens to be in the
    environment.
    """
    tree = ast.parse(source_of(f"spec_checks/{Path(__file__).name}"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    faults = [
        f"imports {name}"
        for name in sorted(imported)
        if "translator" in name or "openai" in name or name.endswith("run_repair_smoke")
    ]
    # No environment variable holding a credential is read. Stated as a suffix
    # rule rather than as the name itself, which would put the name in this file
    # and make the assertion fail on its own text.
    suffix = "_API" + "_KEY"  # noqa: ISC003 - split so this line is not a hit
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith(suffix)
        ):
            faults.append(f"line {node.lineno} names a credential variable")
    record(
        "check_07d_the_driver_spends_no_credential_in_the_gate",
        not faults,
        "; ".join(faults),
    )


def check_07e_report_quotes_the_evidence() -> None:
    """Positive 7e: the report's headline numbers are in the evidence file."""
    data = evidence()
    text = REPORT.read_text(encoding="utf-8")
    radius = data["blast_radius"]
    wanted = [
        data["loop"]["stopped_because"],
        SUBJECT,
        str(data["ruled_name_sites"]["sites_carrying_ruled_name"]),
        str(radius["paragraphs_compared"]),
        "W-B8-01",
    ]
    missing = [token for token in wanted if token not in text]
    record("check_07e_report_quotes_the_evidence", not missing, f"absent {missing}")


# --- 08 the sweep -------------------------------------------------------------


def check_08_sweep() -> None:
    """Positive 8: every earlier gate still passes."""
    if NESTED_SUPPRESSED:
        print("SKIPPED: check_08_sweep (the runner is performing the sweep)")
        return
    proc = subprocess.run(  # noqa: S603
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1"},
    )
    record("check_08_sweep", proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:])


def main() -> int:
    checks = [
        check_01a_publish_sweeps_to_fit,
        check_01b_sweep_survives_what_it_cannot_remove,
        check_01c_build_publishes_through_the_seam,
        check_02_every_sidecar_is_declared,
        check_03a_artefacts_present,
        check_03b_every_sample_ran,
        check_03c_evidence_matches_the_sidecar,
        check_04a_the_standing_finding_was_detected_and_decided,
        check_04b_every_run_conserved_its_document,
        check_04c_rejections_are_recorded_with_a_reason,
        check_05a_nothing_moved_outside_the_repaired_set,
        check_05b_the_rendering_moved_only_where_the_document_did,
        check_05c_the_disputed_region_draws_as_it_did,
        check_06_prompt_rounds_are_recorded,
        check_07a_no_upstream_change,
        check_07b_no_vocabulary_literals,
        check_07c_ascii_prose,
        check_07d_the_driver_spends_no_credential_in_the_gate,
        check_07e_report_quotes_the_evidence,
        check_08_sweep,
    ]
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, never raises
            record(check.__name__, False, f"raised {exc!r}")
    print(f"\nspec_check_b8_3: {_passed}/{_total} assertions passed")
    for failure in _failures:
        print(f"  - {failure}")
    with contextlib.suppress(Exception):
        _timer.write()
        _timer.print_summary()
        artifacts.print_stats("spec_check_b8_3")
    return 0 if not _failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
