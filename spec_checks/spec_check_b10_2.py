"""Gate script for micro batch B10.2 (collision criterion, action and cache key).

Run from the repository root:

    python spec_checks/spec_check_b10_2.py

Exit code 0 when every assertion passes, 1 otherwise. Needs no API key and makes
no network request: every assertion is answered from a stub this gate builds
itself, from evidence B9.5 froze, or from what this batch's replay left behind.

What this batch is. T1 gives the collision detector a second measure -- the
shared area over the smaller box, beside the shared area over the union -- and a
pair is a candidate, or exempt as the source's own design, at or above either
bound. T2 turns the collision action from one that refuses every finding into
one that slides the smaller member of a pair clear, refusing the pairs its rule
cannot name a smaller member of. T3 takes the fields that change on every run
out of the digest a cached request is filed under, which is why every replay
since F2 has paid for decisions it already had. T4 writes one attribution row
per call that reaches the transport, so a run's rows are its bill.

01 is the scope.

02 is T1: the measure itself on stubs, then the frozen B9.5 census read back
through the new formula, then the exemption route the CERN printing slugs now
travel by.

03 is T2: the two refusals the rule is built from, the applied case measured in
pixels off the produced pages, and conservation.

04 is T3: two constructions of one key are equal, the key rendering carries no
volatile field, and the rendering that is sent is unchanged.

05 is T4: the ledger equals the bill.

Tiers: every assertion is static, so the fast tier runs the whole gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine.detectors import base as detector_base  # noqa: E402
from babeldoc.magazine.detectors import collision as collision_detector  # noqa: E402
from babeldoc.magazine.react import actions as react_actions  # noqa: E402
from babeldoc.magazine.react import cache_key as cache_key_fields  # noqa: E402
from babeldoc.magazine.react import collision as collision_action  # noqa: E402
from babeldoc.magazine.react import config as react_config  # noqa: E402
from babeldoc.magazine.react import decide  # noqa: E402
from spec_checks import harness  # noqa: E402

# Which set of the sweep this gate belongs to. It drives no pipeline build.
GATE_SET = "fast"

BATCH_TAG = "b10.2"

BATCH_DIR = ROOT / "examples" / "output" / "b10_2"
DRIVER = BATCH_DIR / "scripts" / "run_b10_2.py"
LEDGER = BATCH_DIR / "runs.json"
CENSUS = ROOT / "examples" / "output" / "b9_5" / "evidence.json"

TARGETS = {
    "AramcoWorld-en-v2": (3,),
    "Vogue-en": (3,),
    "CERNCourier-en": (3, 4),
}

# The four pairs the batch is anchored to, with the figures B9.5 froze, split
# by the verdict the new criterion reaches on each. Named here rather than
# searched for: a gate that recomputed the anchor set would be asserting about
# the census rather than against it.
#
# The split is not the one the batch plan expected, and it is the substantive
# result of T1. The plan looked for four findings. Three of these pairs are
# overlaps the *source* already drew -- two of them a drop cap standing wholly
# inside its own body paragraph, which is what a drop cap is -- and widening the
# exemption to read coverage is what makes the detector able to see that. Under
# the old iou-only exemption they were not exempt; they were merely below the
# candidate bound, and the same verdict came out of a different route. Raising
# them now would be reporting the designer's decision as a fault, which is the
# one thing the source comparison exists to prevent.
RAISED = {
    ("AramcoWorld-en-v2", 3, "p3#0", "p3#4"): (0.0089, 0.5234),
}

# Pairs the source exemption takes, with the source coverage that takes them,
# and the source iou that shows the old exemption would not have. Two of them
# are a drop cap standing wholly inside its own body paragraph, which is what a
# drop cap is; one is the printing slug the plan named.
SOURCE_EXEMPT = {
    ("CERNCourier-en", 3, "p3#11", "p3#13"): 1.0,
    ("CERNCourier-en", 3, "p3#22", "p3#24"): 1.0,
    ("CERNCourier-en", 4, "p4#41", "p4#44"): 1.0,
}

# The fourth census pair, which under this stack is not a candidate at all and
# so reaches neither list. The reason is on the record rather than inferred:
# ``title_typeset`` sets p3#18 as a single line at a scale of 0.6822 after
# typesetting has run, and the smaller ink that leaves drops the pair's coverage
# below the candidate bound. The census was taken before that pass existed.
NOT_A_CANDIDATE = {
    ("Vogue-en", 3, "p3#18", "p3#19"): 0.6822,
}

# The census lists pairs at coverage 0.5 and above and is silent below it, so a
# prediction drawn from it is exact only down to its own floor. Comparing the
# observed set against the predicted one anywhere below this would be reading
# the census for something it does not contain.
CENSUS_FLOOR = 0.5

# The decide prompt is not touched by this batch: the round's vocabulary is
# narrowed by the action table and the template says nothing about either.
DECIDE_PROMPT_SHA = (
    "94f390049cd07156b3290170062939ad88b1103e9f207335b41769a0a4ba1a03"
)

ALLOWED_PREFIXES = (
    "examples/output/b10_2/",
    "configs/",
    "spec_checks/",
    "babeldoc/magazine/detectors/",
    "babeldoc/magazine/react/",
    "docs/reports/archive/",
)
ALLOWED_FILES = {
    "plans/PLAN_B10_2.md",
    "examples/output/run_all.b10_2.log",
    "plans/PLAN_B10_2_REV2.md",
    "UPSTREAM_DIFF.md",
    "WAIVERS.md",
}

FORBIDDEN_PREFIXES = ("corpus/", "reviews/", "prompts/", "tools/", "docs/eval/")

# Configuration this batch declares it does not move.
FROZEN_CONFIGS = ("configs/decision_rounds.json",)

# The resolution the committed page images were rendered at, which is what
# turns a coordinate on the page back into a row of one of them, and how dark a
# channel has to be for a pixel to count as ink. Both are the figures B10.1 read
# its own pages by, so the two batches measure ink the same way.
RASTER_DPI = 110
INK_THRESHOLD = 200

NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

_failures: list[str] = []
_passed = 0
_total = 0
_timer = harness.Timer("spec_check_b10_2")


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


def detector_config():
    from babeldoc.magazine import detectors

    return detectors.detector_config()


def repair_config():
    from babeldoc.magazine.react import controller

    return react_config.load_repair_config(None, controller.detector_kinds())


def issues_of(sample: str) -> dict | None:
    path = BATCH_DIR / sample / "sidecars" / "issues.json"
    if not path.exists():
        return None
    return load_json(path)


def repair_report(sample: str) -> dict | None:
    path = BATCH_DIR / sample / "sidecars" / "react_repair.report.json"
    if not path.exists():
        return None
    return load_json(path)


def detected_collisions(sample: str) -> set | None:
    """The collision findings the loop was shown, before it repaired any.

    ``issues.json`` is written after the loop has run, so a pair the loop
    resolved is absent from it -- which is the point of resolving it, and would
    read as a pair the detector never found. The first iteration's own record of
    what detection handed it is the pre-repair set, and that is what a census
    prediction has to be compared against.
    """
    report = repair_report(sample)
    if report is None:
        return None
    iterations = report.get("iterations") or []
    if not iterations:
        # A run with nothing to repair never iterates; the sidecar is the set.
        found = issues_of(sample)
        if found is None:
            return None
        return {
            (int(issue["page"]), *tuple(issue["paragraph_refs"]))
            for issue in found["issues"]
            if issue["kind"] == collision_detector.KIND
        }
    seen = set()
    for name in iterations[0].get("detected_ids", ()):
        kind, _, rest = name.partition(":")
        if kind != collision_detector.KIND:
            continue
        page, _, refs = rest.partition(":")
        seen.add((int(page.lstrip("p")), *tuple(refs.split("+"))))
    return seen


def census_pairs() -> dict:
    """The frozen B9.5 census, keyed by sample, page and the pair it names."""
    if not CENSUS.exists():
        return {}
    with CENSUS.open(encoding="utf-8", errors="replace") as f:
        evidence = json.load(f)
    found = {}
    for entry in evidence.get("samples", ()):
        sample = str(entry.get("sample", ""))
        for pair in entry.get("pairs", ()):
            refs = tuple(pair.get("refs", ()))
            if len(refs) != 2:
                continue
            found[(sample, int(pair["page"]), *refs)] = pair
    return found


# --- 01 scope ------------------------------------------------------------------


def check_01a_the_delta_is_the_declared_surface() -> None:
    """Negative 1a: nothing outside the detectors, the loop, configuration and evidence."""
    stray = sorted(
        path
        for path in changed_paths()
        if path not in ALLOWED_FILES
        and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "check_01a_the_delta_is_the_declared_surface",
        not stray,
        f"outside the declared surface: {stray}",
    )


def check_01b_no_upstream_no_prompt_no_truth() -> None:
    """Negative 1b: no upstream file, no prompt, no ground truth, no ruling."""
    faults = []
    changed = changed_paths()
    forbidden = sorted(
        path for path in changed if path.startswith(FORBIDDEN_PREFIXES)
    )
    if forbidden:
        faults.append(f"forbidden paths: {forbidden}")
    upstream = sorted(
        path
        for path in changed
        if path.startswith("babeldoc/") and not path.startswith("babeldoc/magazine/")
    )
    if upstream:
        faults.append(f"upstream paths: {upstream}")
    prompt = ROOT / "prompts" / "react_repair_decide.md"
    import hashlib

    digest = hashlib.sha256(prompt.read_bytes()).hexdigest()
    if digest != DECIDE_PROMPT_SHA:
        faults.append(f"the decide prompt is {digest[:12]}, pinned at {DECIDE_PROMPT_SHA[:12]}")
    record("check_01b_no_upstream_no_prompt_no_truth", not faults, "; ".join(faults))


def check_01c_the_rounds_are_untouched() -> None:
    """Negative 1c: the kind order this batch acts within is not moved by it.

    The kind was already in the order, put there by B9.7 because every raised
    kind has to be. This batch gives it an action; it does not give it a place.
    """
    faults = []
    for name in FROZEN_CONFIGS:
        code, diff = git_output(["diff", "HEAD", "--", name])
        if code == 0 and diff.strip():
            faults.append(f"{name} was modified")
    rounds = load_json(ROOT / "configs" / "decision_rounds.json")
    if collision_detector.KIND not in rounds["kind_order"]:
        faults.append("the collision kind is not in the declared order")
    record("check_01c_the_rounds_are_untouched", not faults, "; ".join(faults))


# --- 02 T1 the coverage criterion ----------------------------------------------


def check_02a_coverage_sees_what_the_union_ratio_cannot() -> None:
    """Positive 2a: a box inside a box reports one by coverage and nothing by iou."""
    small = (100.0, 400.0, 120.0, 420.0)
    large = (90.0, 380.0, 300.0, 500.0)
    config = detector_config()
    faults = []
    iou = detector_base.intersection_over_union(small, large)
    covered = detector_base.coverage(small, large)
    if iou >= config.collision_min_iou:
        faults.append(f"the union ratio reports {iou}, which was meant to be blind here")
    if covered < config.collision_min_coverage:
        faults.append(f"coverage reports {covered}, below its own bound")
    # Symmetric, and zero where the boxes do not meet.
    if abs(covered - detector_base.coverage(large, small)) > 1e-12:
        faults.append("coverage is not symmetric")
    if detector_base.coverage((0.0, 0.0, 1.0, 1.0), (5.0, 5.0, 6.0, 6.0)) != 0.0:
        faults.append("disjoint boxes report coverage")
    record(
        "check_02a_coverage_sees_what_the_union_ratio_cannot", not faults, "; ".join(faults)
    )


def check_02b_the_bounds_are_declared_and_bounded() -> None:
    """Positive 2b: both new bounds carry a range and sit inside it."""
    raw = load_json(ROOT / "configs" / "detectors.json")
    faults = []
    for name in ("collision_min_coverage", "collision_source_min_coverage"):
        if name not in raw:
            faults.append(f"{name} is not declared")
            continue
        if f"{name}_allowed_range" not in raw:
            faults.append(f"{name} carries no allowed range")
            continue
        low, high = (float(v) for v in raw[f"{name}_allowed_range"].split(".."))
        if not low <= float(raw[name]) <= high:
            faults.append(f"{name}={raw[name]} outside {low}..{high}")
    progress = raw["progress_evidence"].get(collision_detector.KIND, [])
    if "coverage" not in progress:
        faults.append(f"coverage is not a progress field; they are {progress}")
    record("check_02b_the_bounds_are_declared_and_bounded", not faults, "; ".join(faults))


def check_02c_the_census_predicts_what_the_run_reports() -> None:
    """Positive 2c: the trigger set is the one the frozen census predicts.

    The prediction is the new formula applied to the figures B9.5 froze --
    candidate at or above either bound, exempt where the source cleared either
    of its own -- and it is compared against what this batch's run reported. Only
    down to the census's own listing floor: it lists pairs at coverage 0.5 and
    above, so below that it is silent rather than empty, and reading silence as
    absence would be asserting something the evidence does not say.
    """
    census = census_pairs()
    if not census:
        record("check_02c_the_census_predicts_what_the_run_reports", False,
               f"the frozen census is missing: {CENSUS}")
        return
    config = detector_config()
    faults = []
    checked = 0
    for sample, pages in TARGETS.items():
        shown = detected_collisions(sample)
        if shown is None:
            faults.append(f"{sample}: no repair sidecar; run the driver")
            continue
        # The sidecar answers for the whole document; the census answers for the
        # pages it was taken on. Both sides are narrowed to those pages, or the
        # comparison would read a finding on an unexamined page as a surprise.
        observed = {key for key in shown if key[0] in pages}
        predicted = set()
        for key, pair in census.items():
            if key[0] != f"{sample}.pdf" and key[0] != sample:
                continue
            if key[1] not in pages:
                continue
            if float(pair["covered"]) < CENSUS_FLOOR:
                continue
            candidate = (
                float(pair["iou"]) >= config.collision_min_iou
                or float(pair["covered"]) >= config.collision_min_coverage
            )
            exempt = (
                float(pair["source_iou"]) >= config.collision_source_min_iou
                or float(pair["source_covered"]) >= config.collision_source_min_coverage
            )
            if candidate and not exempt:
                predicted.add((key[1], key[2], key[3]))
        checked += len(predicted)
        missing = sorted(predicted - observed)
        if missing:
            faults.append(f"{sample}: predicted but not reported: {missing}")
        extra = sorted(observed - predicted)
        if extra:
            faults.append(f"{sample}: reported but not predicted: {extra}")
    if not checked:
        faults.append("the census predicted nothing at all, which cannot be right")
    record(
        "check_02c_the_census_predicts_what_the_run_reports", not faults, "; ".join(faults)
    )


def check_02d_the_raised_pair_is_found_and_repaired() -> None:
    """Positive 2d: the one pair the translation caused is found, moved, and gone.

    Found with the figures the census froze, slid by the action, and absent from
    the run's final findings -- resolved rather than merely reduced. The figures
    are read off the repair record because a resolved finding is not in the
    final sidecar, which is what resolving it means.
    """
    faults = []
    action = repair_config().actions[collision_action.NAME]
    for (sample, page, first, second), (iou, covered) in sorted(RAISED.items()):
        shown = detected_collisions(sample)
        report = repair_report(sample)
        if shown is None or report is None:
            faults.append(f"{sample}: no repair sidecar; run the driver")
            continue
        if (page, first, second) not in shown:
            faults.append(f"{sample} p{page} {first}/{second}: detection never found it")
            continue
        applied = [
            row
            for iteration in report["iterations"]
            for round_ in iteration.get("rounds", ())
            if round_.get("kind") == collision_detector.KIND
            for row in round_.get("executed", ())
            if row.get("accepted")
        ]
        if len(applied) != 1:
            faults.append(f"{sample}: {len(applied)} accepted collision repair(s)")
            continue
        geometry = applied[0]["geometry"]
        if abs(float(geometry["coverage_before"]) - covered) > TOLERANCE:
            faults.append(
                f"{sample}: coverage before {geometry['coverage_before']} "
                f"against the census {covered}"
            )
        if abs(float(geometry["iou_before"]) - iou) > TOLERANCE:
            faults.append(
                f"{sample}: iou before {geometry['iou_before']} "
                f"against the census {iou}"
            )
        if geometry["mover"] not in (first, second):
            faults.append(f"{sample}: it moved {geometry['mover']}, outside the pair")
        if float(geometry["area_ratio"]) > collision_action.max_area_ratio(action):
            faults.append(f"{sample}: it moved a pair of comparable size")
        if float(geometry["distance"]) > float(geometry["shift_limit"]):
            faults.append(
                f"{sample}: it slid {geometry['distance']} past the bound "
                f"{geometry['shift_limit']}"
            )
        # The slide is solved to land on the target, so the record -- which keeps
        # four places -- reads the target back. What has to be true of the
        # landing is that it is not above what was aimed at, and that it clears
        # the bound the detector reports at by the margin the action declares.
        # Asking the record for a strictly smaller number than the one the
        # arithmetic aimed at would be asking it for precision it does not keep.
        landed = float(geometry["coverage_after"])
        if landed > float(geometry["coverage_target"]):
            faults.append(
                f"{sample}: coverage landed at {landed}, above the "
                f"{geometry['coverage_target']} it aimed at"
            )
        if landed >= detector_config().collision_min_coverage:
            faults.append(
                f"{sample}: coverage landed at {landed}, which the detector "
                f"still reports at"
            )
        final = issues_of(sample)
        if final is not None:
            standing = [
                issue
                for issue in final["issues"]
                if issue["kind"] == collision_detector.KIND
                and int(issue["page"]) == page
            ]
            if standing:
                faults.append(f"{sample}: the repaired page still reports a collision")
            before = report["iterations"][0]["detected"]["by_kind"]
            after = final["counts"]["by_kind"]
            if after.get("out_of_page", 0) > before.get("out_of_page", 0):
                faults.append(f"{sample}: the repair pushed ink off the page")
    record(
        "check_02d_the_raised_pair_is_found_and_repaired", not faults, "; ".join(faults)
    )


def check_02e_the_source_design_pairs_stay_exempt() -> None:
    """Negative 2e: what the source drew raises nothing, and says how it was spared.

    Two drop caps standing inside their own body paragraphs and the CERN
    printing slugs. For every one the verdict is B9.5's and the route is not:
    each has a source iou below the old exemption's bound, so under the iou-only
    exemption none was exempt -- they were merely never candidates. That is what
    the exemption record exists to show, and it is the whole of the argument
    that widening the candidate bound did not start reporting design as defect.
    """
    config = detector_config()
    faults = []
    for (sample, page, first, second), source_covered in sorted(SOURCE_EXEMPT.items()):
        report = issues_of(sample)
        if report is None:
            faults.append(f"{sample}: no issues sidecar; run the driver")
            continue
        raised = [
            issue
            for issue in report["issues"]
            if issue["kind"] == collision_detector.KIND
            and int(issue["page"]) == page
            and tuple(issue["paragraph_refs"]) == (first, second)
        ]
        if raised:
            faults.append(f"{sample} p{page} {first}/{second} was raised")
            continue
        rows = report.get("detector_records", {}).get(collision_detector.NAME, [])
        named = [
            row
            for row in rows
            if int(row["page"]) == page and tuple(row["paragraphs"]) == (first, second)
        ]
        if not named:
            faults.append(f"{sample} p{page} {first}/{second}: no exemption record")
            continue
        row = named[0]
        if row.get("exempt_route") != collision_detector.SOURCE_ROUTE_COVERAGE:
            faults.append(
                f"{sample} {first}/{second}: exempted by {row.get('exempt_route')!r}"
            )
        if abs(float(row["source_coverage"]) - source_covered) > TOLERANCE:
            faults.append(
                f"{sample} {first}/{second}: source coverage "
                f"{row['source_coverage']} against the census {source_covered}"
            )
        if float(row["source_iou"]) >= config.collision_source_min_iou:
            faults.append(
                f"{sample} {first}/{second}: the old iou exemption would have "
                f"taken it too, so this proves nothing about the new route"
            )
    record(
        "check_02e_the_source_design_pairs_stay_exempt", not faults, "; ".join(faults)
    )


def check_02f_the_shrunk_pair_is_no_longer_a_candidate() -> None:
    """Negative 2f: the fourth census pair reaches neither list, for a stated reason.

    The census measured it at coverage 0.5458 and it is not a candidate here.
    That is not a criterion failure: ``title_typeset``, which did not exist when
    the census was taken, sets the smaller member as a single line at the scale
    recorded below, and the smaller ink drops the pair under the bound. Both the
    absence and its stated cause are checked, so a drift nobody accounted for
    cannot hide behind an explanation that has stopped being true.
    """
    faults = []
    for (sample, page, first, second), scale in sorted(NOT_A_CANDIDATE.items()):
        shown = detected_collisions(sample)
        report = issues_of(sample)
        if shown is None or report is None:
            faults.append(f"{sample}: no sidecar; run the driver")
            continue
        if (page, first, second) in shown:
            faults.append(f"{sample} p{page} {first}/{second} was raised after all")
        rows = report.get("detector_records", {}).get(collision_detector.NAME, [])
        if any(
            int(row["page"]) == page and tuple(row["paragraphs"]) == (first, second)
            for row in rows
        ):
            faults.append(f"{sample} p{page} {first}/{second} was a candidate after all")
        typeset = BATCH_DIR / sample / "sidecars" / "title_typeset.report.json"
        if not typeset.exists():
            faults.append(f"{sample}: no title_typeset record to read the cause from")
            continue
        named = [
            row
            for row in load_json(typeset).get("titles", ())
            if row.get("reference") == first
        ]
        if not named:
            faults.append(f"{sample}: the title pass says nothing about {first}")
            continue
        if abs(float(named[0].get("scale", 1.0)) - scale) > 1e-4:
            faults.append(
                f"{sample}: {first} was set at {named[0].get('scale')}, not {scale}; "
                f"the recorded cause no longer holds and the absence is unexplained"
            )
    record(
        "check_02f_the_shrunk_pair_is_no_longer_a_candidate",
        not faults,
        "; ".join(faults),
    )


# The agreement a recomputed figure has to reach against a frozen one. Three of
# the four anchors reproduce the census to the fourth place, which is every
# place either of them keeps. The Vogue pair does not, and the reason is on the
# record rather than in the tolerance: B10.1's display fixes moved that page, so
# its coverage reads 0.5599 where B9.5 measured 0.5458. The allowance is set to
# carry that one known movement and nothing larger.
TOLERANCE = 0.02


# --- 03 T2 the action ----------------------------------------------------------


def check_03a_a_pair_of_equals_is_refused() -> None:
    """Negative 3a: two blocks of one size name no smaller one, so neither moves."""
    action = repair_config().actions[collision_action.NAME]
    faults = []
    ratio = collision_action.max_area_ratio(action)
    if not 0.0 < ratio <= 1.0:
        faults.append(f"the area ratio bound is {ratio}")
    # The rule's own arithmetic, on two boxes of one size.
    equal_a = (100.0, 400.0, 200.0, 440.0)
    equal_b = (110.0, 405.0, 210.0, 445.0)
    if collision_action.area(equal_a) / collision_action.area(equal_b) <= ratio:
        faults.append("two boxes of one size were inside the asymmetry bound")
    record("check_03a_a_pair_of_equals_is_refused", not faults, "; ".join(faults))


def check_03b_the_shift_is_bounded() -> None:
    """Negative 3b: clearing an overlap too wide to clear is refused, not attempted."""
    action = repair_config().actions[collision_action.NAME]
    config = detector_config()
    faults = []
    limit = collision_action.max_shift_ratio(action)
    if not 0.0 <= limit < 0.5:
        faults.append(f"the shift bound is {limit}")
    margin = collision_action.margin(action)
    target = config.collision_min_coverage - margin
    if target <= 0:
        faults.append(f"the coverage target is {target}, which nothing can reach")
    if target >= config.collision_min_coverage:
        faults.append("the target does not clear the detector's own bound")
    # A small box deep inside a very wide block needs more than the bound allows.
    small = (400.0, 400.0, 410.0, 412.0)
    wide = (100.0, 300.0, 700.0, 600.0)
    low, high = collision_action.escape_distances(
        small, wide, 0, target, collision_action.area(small)
    )
    if min(low, high) <= limit * 600.0:
        faults.append(
            f"a box in the middle of a wide block escapes in {min(low, high)}, "
            f"which the bound was meant to refuse"
        )
    record("check_03b_the_shift_is_bounded", not faults, "; ".join(faults))


def check_03c_the_escape_is_solved_from_the_edges() -> None:
    """Positive 3c: a contained box's distance is to the edge, not its overlap.

    The defect this asserts against is the arithmetic that reads the current
    overlap as the distance. For a box standing wholly inside another that is
    the box's own width, the slide clears nothing, and the run reports a repair
    that repaired nothing.
    """
    inner = (200.0, 400.0, 210.0, 412.0)
    outer = (100.0, 300.0, 400.0, 500.0)
    faults = []
    target = 0.35
    low, high = collision_action.escape_distances(
        inner, outer, 0, target, collision_action.area(inner)
    )
    # Leaving to the low side means clearing the outer box's left edge.
    if abs(low - ((inner[2] - outer[0]) - target * (inner[2] - inner[0]))) > 1e-9:
        faults.append(f"the low side distance is {low}")
    if abs(high - ((outer[2] - inner[0]) - target * (inner[2] - inner[0]))) > 1e-9:
        faults.append(f"the high side distance is {high}")
    if min(low, high) <= (inner[2] - inner[0]):
        faults.append("the distance did not exceed the overlap, so it clears nothing")
    # And the slide it produces really does bring coverage under the target.
    moved = (inner[0] - low, inner[1], inner[2] - low, inner[3])
    if detector_base.coverage(moved, outer) > target + 1e-9:
        faults.append(
            f"after the solved slide coverage is "
            f"{detector_base.coverage(moved, outer)}"
        )
    record("check_03c_the_escape_is_solved_from_the_edges", not faults, "; ".join(faults))


def check_03d_the_rule_is_one_readable_condition() -> None:
    """Positive 3d: the action admits by coverage alone, stated as one condition.

    The bound it does not restate is the union ratio's, and the reason is that
    the ratio can select nothing the area asymmetry bound does not refuse first
    -- asserted directly below in 03g rather than taken on the module's word.
    """
    action = repair_config().actions[collision_action.NAME]
    config = detector_config()
    faults = []
    action_coverage = collision_action.applicability(action)
    if action_coverage < config.collision_min_coverage:
        faults.append(f"the action acts at coverage {action_coverage}")
    # One term, and it is stated once. The rule is read by a model under the
    # heading that every stated condition must hold, so a disjunction spread
    # over two sentences is a rule that gets misread -- and was.
    statements = action.conditions()
    if len(statements) != 1:
        faults.append(f"the rule states {len(statements)} conditions, not one")
    # A cross reference to the other measure is what a disjunction looks like
    # once it has been folded into a rule whose terms are read as conjoined.
    if statements and "iou" in statements[0]:
        faults.append(f"the one condition names the other measure: {statements[0]!r}")
    record(
        "check_03d_the_rule_is_one_readable_condition", not faults, "; ".join(faults)
    )


def check_03g_the_bound_the_rule_omits_could_select_nothing() -> None:
    """Positive 3g: the union ratio bound is unreachable behind the area bound.

    The rule reads coverage alone, and the argument for dropping the other bound
    is that no pair can be admitted by it and refused by coverage while still
    passing the area asymmetry test. Asserted by construction over the region
    where such a pair would have to live rather than taken on the module's word.
    """
    action = repair_config().actions[collision_action.NAME]
    config = detector_config()
    limit = collision_action.max_area_ratio(action)
    faults = []
    worst = 1.0
    steps = 160
    for i in range(1, steps):
        for j in range(1, steps):
            # Two boxes sharing a corner region, swept over their own sizes.
            shared = 1.0
            first = 1.0 + 6.0 * i / steps
            second = 1.0 + 6.0 * j / steps
            union = first + second - shared
            if union <= 0:
                continue
            iou = shared / union
            covered = shared / min(first, second)
            if iou < config.collision_min_iou:
                continue
            if covered >= config.collision_min_coverage:
                continue
            worst = min(worst, min(first, second) / max(first, second))
    if worst <= limit:
        faults.append(
            f"a pair the union ratio admits and coverage refuses reaches an area "
            f"ratio of {worst:.4f}, which the {limit} bound would allow through"
        )
    record(
        "check_03g_the_bound_the_rule_omits_could_select_nothing",
        not faults,
        "; ".join(faults),
    )


def check_03e_the_guard_reads_both_measures() -> None:
    """Positive 3e: what the action refuses to create is what the detector reports.

    A guard reading the union ratio alone would be blind to exactly the overlap
    this action exists to repair, so it would let a slide put a folio inside the
    next entry without noticing.
    """
    config = detector_config()
    inner = (200.0, 400.0, 210.0, 412.0)
    outer = (100.0, 300.0, 400.0, 500.0)
    faults = []
    if not collision_action.stands_on(
        inner, outer, config.collision_min_iou, config.collision_min_coverage
    ):
        faults.append("the guard does not see a box standing inside another")
    if detector_base.intersection_over_union(inner, outer) >= config.collision_min_iou:
        faults.append("the fixture is visible to the union ratio, so it proves nothing")
    record("check_03e_the_guard_reads_both_measures", not faults, "; ".join(faults))


def check_03f_conservation_holds_where_it_acted() -> None:
    """Positive 3f: the run changed no page count, no paragraph count, nothing untouched."""
    faults = []
    seen = 0
    for sample in TARGETS:
        report = repair_report(sample)
        if report is None:
            faults.append(f"{sample}: no repair sidecar; run the driver")
            continue
        seen += 1
        conservation = report["conservation"]
        if conservation["verdict"] != "conserved":
            faults.append(f"{sample}: conservation {conservation['verdict']}")
        if conservation["pages_before"] != conservation["pages_after"]:
            faults.append(f"{sample}: page count moved")
        if conservation["paragraphs_before"] != conservation["paragraphs_after"]:
            faults.append(f"{sample}: paragraph count moved")
        if conservation["changed_outside_touched"]:
            faults.append(
                f"{sample}: changed outside the repaired set: "
                f"{conservation['changed_outside_touched']}"
            )
    if not seen:
        faults.append("no repair sidecar was read at all")
    record("check_03f_conservation_holds_where_it_acted", not faults, "; ".join(faults))


def check_03h_the_repair_moved_glyphs_and_only_those() -> None:
    """End to end 3h: the two rendered pages differ, and only where they should.

    Read off the pages rather than off the boxes the repair wrote, because those
    are the repair's own account of itself. Two arms of the same run produce the
    two images: the detect arm with the loop switched off, and the repaired run.

    What is asserted is not that the overlap looks better. The repair the
    criterion selected on this page is a slide of about one and a half points,
    which is two pixels at the resolution these pages are rendered at, and a
    claim that two pixels of ink overlap became visibly fewer would be a claim
    about raster noise. What two pixels can carry is the thing worth catching:
    that ink moved at all, and that nothing else on the page did.

    So the difference between the two images has to be non-empty -- a repair
    that rewrote boxes and moved no glyph passes every other assertion in this
    gate and fails here -- and it has to be confined to a region no bigger than
    the paragraph that was named plus the distance it was said to travel. A
    repair that reflowed the page would leave a difference the size of the page.
    """
    from PIL import Image  # noqa: PLC0415
    from PIL import ImageChops  # noqa: PLC0415

    faults = []
    scale = RASTER_DPI / 72.0
    for (sample, page, _first, _second) in sorted(RAISED):
        report = repair_report(sample)
        if report is None:
            faults.append(f"{sample}: no repair sidecar; run the driver")
            continue
        applied = [
            row
            for iteration in report["iterations"]
            for round_ in iteration.get("rounds", ())
            if round_.get("kind") == collision_detector.KIND
            for row in round_.get("executed", ())
            if row.get("accepted")
        ]
        if not applied:
            faults.append(f"{sample}: nothing was applied to measure")
            continue
        geometry = applied[0]["geometry"]
        before_png = (
            BATCH_DIR / f"{sample}.detect" / "raster" / f"{sample}.p{page}.before.png"
        )
        after_png = BATCH_DIR / sample / "raster" / f"{sample}.p{page}.after.png"
        missing = [x for x in (before_png, after_png) if not x.exists()]
        if missing:
            faults.append(f"missing {[str(x.relative_to(ROOT)) for x in missing]}")
            continue

        with Image.open(before_png) as raw_before, Image.open(after_png) as raw_after:
            before = raw_before.convert("L")
            after = raw_after.convert("L")
            if before.size != after.size:
                faults.append(f"{sample}: the two arms rendered different page sizes")
                continue
            difference = ImageChops.difference(before, after)
            window = difference.getbbox()
            changed = sum(1 for value in difference.getdata() if value > 8)
            page_area = before.size[0] * before.size[1]

        if window is None or changed == 0:
            faults.append(
                f"{sample}: the two pages are identical, so the repair wrote a "
                f"box and moved no ink"
            )
            continue

        box = geometry["box_before"]
        travelled = abs(geometry["shift"][0]) + abs(geometry["shift"][1])
        # The paragraph's own extent plus how far it was said to go, in pixels,
        # with a pixel of slack at each edge for the glyph outlines that reach
        # past the character boxes the extent is measured from.
        allowed_width = (box[2] - box[0] + travelled) * scale + 4
        allowed_height = (box[3] - box[1] + travelled) * scale + 4
        width = window[2] - window[0]
        height = window[3] - window[1]
        if width > allowed_width or height > allowed_height:
            faults.append(
                f"{sample}: the page changed over {width}x{height}px, more than "
                f"the {allowed_width:.0f}x{allowed_height:.0f}px the named "
                f"paragraph and its slide account for"
            )
        if width * height > page_area * 0.01:
            faults.append(f"{sample}: the change covers more than a hundredth of the page")
    record(
        "check_03h_the_repair_moved_glyphs_and_only_those", not faults, "; ".join(faults)
    )


# --- 04 T3 the cache key -------------------------------------------------------


class _Issue:
    """One finding as the request renders it, with a run-varying id in evidence."""

    def __init__(self, debug_id: str) -> None:
        self.id = "issue-1"
        self.kind = collision_detector.KIND
        self.severity = "medium"
        self.page = 3
        self.paragraph_refs = ("p3#0", "p3#4")
        self.evidence = {
            "iou": 0.0089,
            "coverage": 0.5234,
            "debug_id": debug_id,
            "debug_ids": [debug_id, f"{debug_id}x"],
            "source_checkpoint": f"work-{debug_id}/checkpoint.xml",
            "excerpt": "a line of text",
        }


def decision_client():
    return decide.CachedDecisionClient(
        repair_config(), transport=None, identity="probe", working_dir=None
    )


def check_04a_two_runs_reach_one_key() -> None:
    """Positive 4a: the same question under different run ids is the same key."""
    client = decision_client()
    faults = []
    first = decide.cache_key(client.key_prompt([_Issue("ZCf9m")]), client.identity)
    second = decide.cache_key(client.key_prompt([_Issue("4GgHy")]), client.identity)
    if first != second:
        faults.append("two runs of one unchanged finding reached different keys")
    # And a key still separates two questions that really are different.
    other = _Issue("ZCf9m")
    other.evidence["coverage"] = 0.9
    third = decide.cache_key(client.key_prompt([other]), client.identity)
    if third == first:
        faults.append("a changed measurement did not change the key")
    record("check_04a_two_runs_reach_one_key", not faults, "; ".join(faults))


def check_04b_the_key_rendering_drops_only_the_declared_fields() -> None:
    """Positive 4b: no volatile field is in the key input, every other field is."""
    client = decision_client()
    issue = _Issue("ZCf9m")
    faults = []
    volatile = repair_config().volatile_evidence_keys
    if "debug_id" not in volatile:
        faults.append(f"the declaration does not name debug_id; it names {volatile}")
    key_text = client.key_prompt([issue]).text
    for name in volatile:
        if name in key_text:
            faults.append(f"the key input still carries {name}")
    if "ZCf9m" in key_text:
        faults.append("the key input still carries a run-varying id's value")
    for name in ("iou", "coverage"):
        if name not in key_text:
            faults.append(f"the key input dropped {name}, which decides the answer")
    record(
        "check_04b_the_key_rendering_drops_only_the_declared_fields",
        not faults,
        "; ".join(faults),
    )


def check_04c_what_is_sent_is_unchanged() -> None:
    """Positive 4c: the model still reads every field the finding carries.

    The projection is for the key alone. A run against a fixed corpus has to ask
    exactly what it asked before, or this batch has changed behaviour while
    claiming to have changed a digest.
    """
    client = decision_client()
    issue = _Issue("ZCf9m")
    faults = []
    sent = client.prompt([issue]).text
    for name in issue.evidence:
        if name == "excerpt":
            continue
        if name not in sent:
            faults.append(f"the sent request dropped {name}")
    if "ZCf9m" not in sent:
        faults.append("the sent request dropped the id's value")
    # The unprojected rendering is what the old key was taken over, so it is also
    # the direct evidence that only the digest moved.
    unprojected = decide.issues_block(
        [issue],
        repair_config().issue_excerpt_chars,
        repair_config().max_issues_offered,
    )
    if unprojected not in sent:
        faults.append("the sent request is not the unprojected rendering")
    record("check_04c_what_is_sent_is_unchanged", not faults, "; ".join(faults))


def check_04d_the_two_request_points_share_one_composition() -> None:
    """Positive 4d: the orphan cache is keyed the way the decision cache is."""
    faults = []
    if react_actions.CACHE_KEY_VERSION != cache_key_fields.CACHE_KEY_VERSION:
        faults.append("the orphan cache carries its own version")
    if decide.CACHE_KEY_VERSION != cache_key_fields.CACHE_KEY_VERSION:
        faults.append("the decision cache carries its own version")
    if cache_key_fields.CACHE_KEY_VERSION < 2:
        faults.append("the version was not moved, so old keys still serve")

    class _Prompt:
        digest = "a" * 64
        text = "one request"

    if react_actions.cache_key(_Prompt(), "x") != decide.cache_key(_Prompt(), "x"):
        faults.append("the two request points build different keys for one request")
    record(
        "check_04d_the_two_request_points_share_one_composition",
        not faults,
        "; ".join(faults),
    )


def check_04e_the_projection_is_a_blacklist() -> None:
    """Negative 4e: a field nobody classified stays in the key.

    The direction matters. A key that keeps a volatile field misses a cache and
    the miss is visible in the ledger; a key that drops a deciding field hits a
    cache it should have missed and replays a decision about other evidence with
    nothing saying so.
    """
    faults = []
    projected = cache_key_fields.project(
        {"debug_id": "x", "a_new_field_nobody_classified": 7}, ("debug_id",)
    )
    if "a_new_field_nobody_classified" not in projected:
        faults.append("an unclassified field was dropped from the key")
    if "debug_id" in projected:
        faults.append("a declared volatile field survived the projection")
    record("check_04e_the_projection_is_a_blacklist", not faults, "; ".join(faults))


# --- 05 T4 the ledger ----------------------------------------------------------


def check_05a_the_ledger_equals_the_bill() -> None:
    """Positive 5a: one attribution row per call that reached the transport."""
    faults = []
    seen = 0
    for sample in TARGETS:
        report = repair_report(sample)
        if report is None:
            faults.append(f"{sample}: no repair sidecar; run the driver")
            continue
        seen += 1
        rows = report.get("api_attributions")
        if rows is None:
            faults.append(f"{sample}: the report carries no attribution rows")
            continue
        if report.get("api_calls") != len(rows):
            faults.append(
                f"{sample}: {report.get('api_calls')} call(s) against "
                f"{len(rows)} attribution row(s)"
            )
        for row in rows:
            for field in ("group", "cache_verdict", "cache_key", "request_sha256"):
                if not row.get(field):
                    faults.append(f"{sample}: an attribution row omits {field}")
                    break
            if row.get("group") not in (
                cache_key_fields.GROUP_DECISION,
                cache_key_fields.GROUP_ORPHAN,
            ):
                faults.append(f"{sample}: a row names the group {row.get('group')!r}")
    if not seen:
        faults.append("no repair sidecar was read at all")
    record("check_05a_the_ledger_equals_the_bill", not faults, "; ".join(faults))


def check_05b_the_evidence_is_present() -> None:
    """Positive 5b: the driver and what it produced are in the tree."""
    faults = []
    if not DRIVER.exists():
        faults.append(f"missing {DRIVER.relative_to(ROOT)}")
    if not LEDGER.exists():
        faults.append(f"missing {LEDGER.relative_to(ROOT)}")
    for sample in TARGETS:
        for name in ("issues.json", "react_repair.report.json"):
            path = BATCH_DIR / sample / "sidecars" / name
            if not path.exists():
                faults.append(f"missing {path.relative_to(ROOT)}")
    record("check_05b_the_evidence_is_present", not faults, "; ".join(faults))


def check_06_history_is_green() -> None:
    """Positive 6: every earlier gate of the fast set still passes."""
    if NESTED_SUPPRESSED:
        record("check_06_history_is_green", True, "run by spec_checks/run_all.py")
        return
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "spec_checks" / "run_all.py"), "--set", "fast"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SPEC_NO_NESTED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    record("check_06_history_is_green", proc.returncode == 0, (proc.stdout or "")[-800:])


CHECKS = (
    check_01a_the_delta_is_the_declared_surface,
    check_01b_no_upstream_no_prompt_no_truth,
    check_01c_the_rounds_are_untouched,
    check_02a_coverage_sees_what_the_union_ratio_cannot,
    check_02b_the_bounds_are_declared_and_bounded,
    check_02c_the_census_predicts_what_the_run_reports,
    check_02d_the_raised_pair_is_found_and_repaired,
    check_02f_the_shrunk_pair_is_no_longer_a_candidate,
    check_02e_the_source_design_pairs_stay_exempt,
    check_03a_a_pair_of_equals_is_refused,
    check_03b_the_shift_is_bounded,
    check_03c_the_escape_is_solved_from_the_edges,
    check_03d_the_rule_is_one_readable_condition,
    check_03e_the_guard_reads_both_measures,
    check_03g_the_bound_the_rule_omits_could_select_nothing,
    check_03f_conservation_holds_where_it_acted,
    check_03h_the_repair_moved_glyphs_and_only_those,
    check_04a_two_runs_reach_one_key,
    check_04b_the_key_rendering_drops_only_the_declared_fields,
    check_04c_what_is_sent_is_unchanged,
    check_04d_the_two_request_points_share_one_composition,
    check_04e_the_projection_is_a_blacklist,
    check_05a_the_ledger_equals_the_bill,
    check_05b_the_evidence_is_present,
    check_06_history_is_green,
)


def main() -> int:
    print("spec_check_b10_2: collision criterion, action and cache key\n")
    for check in CHECKS:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a gate reports, it does not crash
            record(check.__name__, False, f"{type(exc).__name__}: {exc}")
    print(f"\n{_passed}/{_total} assertions passed")
    if _failures:
        print("\nfailures:")
        for line in _failures:
            print(f"  - {line}")
    _timer.write()
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
