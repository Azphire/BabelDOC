"""Count untranslated text over a finished run, and say why each piece is untranslated.

Every residue number this project has published so far was counted over a three
to five page window chosen from the truth nodes of ``corpus/*.json`` -- pages
picked because they were known to be interesting. A census taken over those
pages measures the problems that were used to pick them. This tool exists to
take the same count over whole documents, so the distribution it reports is one
the sampling did not choose.

It reads two populations rather than one, because they are not the same
population:

``A``  the ``untranslated_residue`` issues in ``issues.after.json`` -- what the
       detector saw.
``B``  the ``demo_coverage.report.json`` items whose ``final_status`` is
       ``untranslated`` -- what the coverage ledger holds was never translated.

``B \\ A`` is the detector's blind spot, and it has never been looked at. A
third set is carried alongside them:

``S``  the units ``short_unit.report.json`` admitted -- paragraphs short enough
       that the ordinary translation path would have passed them by, which the
       short-unit lane took instead. They are in neither ``A`` nor ``B``
       precisely because that lane worked, and counting them is how the lane's
       contribution stays visible.

Populations A and B are NOT comparable across directions. ``configs/detectors.json``
declares a residue floor of 12 characters into Chinese and 1 into English, so
the same paragraph raises an issue in one direction and not in the other. Every
aggregate this tool prints is therefore split by direction, and only B may be
compared across the split.

The tool is read-only. It opens the artifacts of a run and writes its own two
files; it never touches a run's own products.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

# ---------------------------------------------------------------------------
# The vocabulary. Closed, and fixed before any full-document run was looked at.
# ---------------------------------------------------------------------------

# Categories, in the order their criteria are tried. The first criterion that
# holds decides, and nothing outside this tuple may be assigned: a record the
# tuple does not describe is UNCLASSIFIED, which is the finding, not a failure.
ROTATED = "rotated"
BELOW_LENGTH_FLOOR = "below_length_floor"
SHORT_UNIT_HANDLED = "short_unit_handled"
NEVER_SUBMITTED = "never_submitted"
RETURNED_UNCHANGED = "returned_unchanged"
TRANSLATED_WITH_RESIDUE = "translated_with_residue"
UNCLASSIFIED = "unclassified"

CATEGORIES = (
    ROTATED,
    BELOW_LENGTH_FLOOR,
    SHORT_UNIT_HANDLED,
    NEVER_SUBMITTED,
    RETURNED_UNCHANGED,
    TRANSLATED_WITH_RESIDUE,
    UNCLASSIFIED,
)

# Why a member of B \ A never became a member of A. Also closed: residue.py
# skips a paragraph at exactly two places, and a record that neither explains
# means a third path exists that this vocabulary did not know about.
CAUSE_PAGE_POLICY = "page_policy"  # residue.py:60 -- page declares no translation
CAUSE_BELOW_THRESHOLD = "below_threshold"  # residue.py:65 -- under the declared floor
BLIND_SPOT_CAUSES = (CAUSE_PAGE_POLICY, CAUSE_BELOW_THRESHOLD, UNCLASSIFIED)

# Declared for this census and for nothing else. This number classifies. It
# does not enter any pipeline judgement.
#
# The IL has always known which way a paragraph is set: ``vertical`` is
# declared in il_version_1.rnc and paragraph_finder sets it from the first
# character. What was missing was a producer -- no issue put it in evidence --
# so this census could only guess rotation from the shape of the box, a
# paragraph set vertically being many times taller than it is wide. The
# residue detector now reports the flag, and a record that carries it is
# classified on the flag alone.
#
# The threshold stays for the records that still have no flag: every B record
# comes from the coverage ledger and has no issue behind it, and artifacts
# written before the detector reported it carry no ``vertical`` either. Which
# of the two decided a record is recorded in its ``criterion``, so a reader can
# count how much of the rotated population rests on evidence and how much on
# shape.
ROTATED_MAX_ASPECT = 0.25

# The census reads a paragraph's rendered text from indent_policy's excerpt,
# which is ``paragraph.unicode`` cut at that stage's own 60-character cap. The
# detector reads ``paragraph_reading_text``, which drops the placeholder markup
# that ``unicode`` still carries. Dropping it here too is what makes the two
# strings countable against each other.
_MARKUP = re.compile(r"</?style[^>]*>|\{v\d+\}|</?formula[^>]*>")

_SCRIPT_NAME_PREFIX = {"latin": "LATIN ", "han": "CJK "}

_REF = re.compile(r"^p(\d+)#(\d+)$")

# The cap indent_policy cuts its excerpt at; an excerpt this long may be short
# of the paragraph, which the census records rather than hides.
_EXCERPT_CAP = 60

REQUIRED_ARTIFACTS = (
    "issues.after.json",
    "issues.before.json",
    "demo_coverage.report.json",
    "article_ir.json",
    "translate_tracking.json",
    "short_unit.report.json",
    "page_classify.report.json",
    "minimal_run.report.json",
    # Not named in the plan's read list, and needed anyway: indent_policy is the
    # only artifact carrying per-paragraph rendered text (so the length floor
    # and the residue estimate can be evaluated at all) and the page kind as it
    # stood after the article stages revised it, which is the kind the detector
    # read. line_split is where the run records its own min_text_length.
    "indent_policy.report.json",
    "line_split.report.json",
    "layout_report.json",
)


class CensusError(RuntimeError):
    """Raised when a run cannot be censused, always naming what was wrong."""


# ---------------------------------------------------------------------------
# Measurement, matching babeldoc.magazine.detectors.base
# ---------------------------------------------------------------------------


def script_counts(text: str) -> dict[str, int]:
    """How many characters of each declared script the text holds."""
    counts = dict.fromkeys(_SCRIPT_NAME_PREFIX, 0)
    for character in text:
        if not character.isalpha():
            continue
        try:
            name = unicodedata.name(character)
        except ValueError:
            continue
        for script, prefix in _SCRIPT_NAME_PREFIX.items():
            if name.startswith(prefix):
                counts[script] += 1
    return counts


def strip_markup(text: str | None) -> str:
    return _MARKUP.sub("", text or "")


def aspect_ratio(box: list[float] | None) -> float | None:
    """Width over height of a box given as ``[x, y, x2, y2]``."""
    if box is None:
        return None
    width = float(box[2]) - float(box[0])
    height = float(box[3]) - float(box[1])
    if height <= 0:
        return None
    return width / height


def parse_ref(ref: str) -> tuple[int, int]:
    match = _REF.match(ref)
    if match is None:
        raise CensusError(f"paragraph reference {ref!r} is not of the form pN#M")
    return int(match.group(1)), int(match.group(2))


def ref_sort_key(ref: str) -> tuple[int, int]:
    try:
        return parse_ref(ref)
    except CensusError:
        return (10**9, 0)


# ---------------------------------------------------------------------------
# One record
# ---------------------------------------------------------------------------


@dataclass
class Record:
    sample: str
    direction: str
    physical_ref: str
    runtime_ref: str | None
    physical_page: int | None
    populations: list[str] = field(default_factory=list)
    category: str = UNCLASSIFIED
    criterion: str = ""
    blind_spot_cause: str | None = None
    blind_spot_criterion: str | None = None
    box: list[float] | None = None
    aspect_ratio: float | None = None
    vertical: bool | None = None
    source_chars: int | None = None
    source_chars_basis: str | None = None
    excerpt: str = ""
    excerpt_truncated: bool = False
    layout_label: str | None = None
    role: str | None = None
    page_kind: str | None = None
    page_kind_at_classify: str | None = None
    owner: str | None = None
    repair_refusal: str | None = None
    issue_id: str | None = None
    tracking_rows: int = 0
    tracking_all_identical: bool | None = None
    residue_script: str | None = None
    residue_chars: int | None = None
    residue_script_chars: int | None = None
    residue_ratio: float | None = None
    residue_basis: str | None = None

    def as_dict(self) -> dict:
        data = dict(self.__dict__)
        data["populations"] = sorted(self.populations)
        return data


# ---------------------------------------------------------------------------
# The criteria
# ---------------------------------------------------------------------------


def classify(record: Record, min_text_length: int, is_short_unit: bool) -> None:
    """Assign the first category whose criterion holds. Order is the vocabulary."""
    if record.vertical is not None:
        # The paragraph itself says which way it is set, so the shape of its
        # box is not consulted: a tall narrow column of horizontal text is not
        # rotated, and saying so from the box would be a guess overruling a
        # fact. Only a record with no such fact falls through to the shape.
        if record.vertical:
            record.category, record.criterion = ROTATED, "paragraph.vertical"
            return
    elif record.aspect_ratio is not None and record.aspect_ratio < ROTATED_MAX_ASPECT:
        record.category, record.criterion = (
            ROTATED,
            f"aspect_ratio<{ROTATED_MAX_ASPECT}",
        )
        return
    if (
        record.source_chars is not None
        and record.source_chars < min_text_length
        and not is_short_unit
    ):
        record.category, record.criterion = (
            BELOW_LENGTH_FLOOR,
            f"source_chars<{min_text_length}",
        )
        return
    if is_short_unit:
        record.category, record.criterion = SHORT_UNIT_HANDLED, "short_unit.admitted"
        return
    if record.tracking_rows == 0:
        record.category, record.criterion = NEVER_SUBMITTED, "no translate_tracking row"
        return
    if record.tracking_all_identical:
        record.category, record.criterion = RETURNED_UNCHANGED, "tracking output==input"
        return
    record.category, record.criterion = (
        TRANSLATED_WITH_RESIDUE,
        "tracking output!=input",
    )


def attribute_blind_spot(
    record: Record, page_policies: dict, min_chars: int, min_ratio: float
) -> None:
    """Why residue.py passed over a paragraph the ledger holds untranslated."""
    policy = page_policies.get(record.page_kind)
    # residue.py:59 reads the flag with a default of True, so a page whose kind
    # the vocabulary does not know is scanned rather than skipped.
    if policy is not None and policy.get("translate", True) is False:
        record.blind_spot_cause = CAUSE_PAGE_POLICY
        record.blind_spot_criterion = f"page_types[{record.page_kind}].translate=false"
        return
    if record.residue_chars is not None and record.residue_script_chars is not None:
        if record.residue_chars < min_chars:
            record.blind_spot_cause = CAUSE_BELOW_THRESHOLD
            record.blind_spot_criterion = f"residue_chars<{min_chars}"
            return
        if (record.residue_ratio or 0.0) < min_ratio:
            record.blind_spot_cause = CAUSE_BELOW_THRESHOLD
            record.blind_spot_criterion = f"residue_ratio<{min_ratio}"
            return
    record.blind_spot_cause = UNCLASSIFIED
    record.blind_spot_criterion = None


# ---------------------------------------------------------------------------
# Loading one run
# ---------------------------------------------------------------------------


def resolve_run_dir(path: Path) -> Path:
    """The directory holding a run's artifacts, from the run root or itself."""
    if (path / "issues.after.json").is_file():
        return path
    work = path / "work"
    if work.is_dir():
        candidates = sorted(
            child for child in work.iterdir() if (child / "issues.after.json").is_file()
        )
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            named = [str(candidate) for candidate in candidates]
            raise CensusError(
                f"{path}: {len(candidates)} artifact directories under work/; "
                f"name one of {named} directly"
            )
    raise CensusError(f"{path}: no issues.after.json here or under work/*/")


def load_artifacts(run_dir: Path) -> dict[str, object]:
    missing = [name for name in REQUIRED_ARTIFACTS if not (run_dir / name).is_file()]
    if missing:
        raise CensusError(f"{run_dir}: missing artifact(s) {', '.join(missing)}")
    loaded: dict[str, object] = {}
    for name in REQUIRED_ARTIFACTS:
        with (run_dir / name).open(encoding="utf-8") as handle:
            loaded[name] = json.load(handle)
    return loaded


def _direction_thresholds(
    artifacts: dict, target_lang: str, detectors_config: dict
) -> tuple[str, int, float]:
    """The residue floor and share this run was measured against.

    Taken from ``configs/detectors.json`` and checked against the run's own
    issue evidence, which records what the run actually used. A disagreement
    means the config moved since the run, and is a stop rather than a choice.
    """
    script = detectors_config["residue_directions"].get(target_lang)
    if script is None:
        raise CensusError(
            f"configs/detectors.json declares no residue direction for target "
            f"language {target_lang!r}"
        )
    min_chars = detectors_config[f"residue_min_script_chars_into_{target_lang}"]
    min_ratio = detectors_config[f"residue_min_ratio_into_{target_lang}"]
    for issue in artifacts["issues.after.json"]["issues"]:
        if issue.get("kind") != "untranslated_residue":
            continue
        evidence = issue["evidence"]
        observed = (
            evidence["residue_script"],
            evidence["min_script_chars"],
            evidence["min_ratio"],
        )
        if observed != (script, min_chars, min_ratio):
            raise CensusError(
                f"issue {issue['id']} was measured against {observed} but "
                f"configs/detectors.json now declares "
                f"{(script, min_chars, min_ratio)}; the config moved since the "
                f"run and the census cannot reconcile them"
            )
    return script, min_chars, min_ratio


def census_run(run_root: Path, detectors_config: dict, page_policies: dict) -> dict:
    run_dir = resolve_run_dir(run_root)
    sample = run_dir.name
    art = load_artifacts(run_dir)

    coverage = art["demo_coverage.report.json"]
    direction = coverage["direction"]
    target_lang = coverage["target_lang"]
    script, min_chars, min_ratio = _direction_thresholds(
        art, target_lang, detectors_config
    )

    min_text_length = art["line_split.report.json"]["min_text_length"]
    declared = art["short_unit.report.json"].get("min_text_length")
    if declared is not None and declared != min_text_length:
        raise CensusError(
            f"{run_dir}: line_split declares min_text_length {min_text_length} "
            f"but short_unit declares {declared}"
        )

    # physical page <-> local (runtime) page, as the run recorded it.
    physical_to_local = {
        int(key): int(value)
        for key, value in art["issues.before.json"]["physical_to_local"].items()
    }
    local_to_physical: dict[int, int] = {}
    for physical, local in physical_to_local.items():
        if local in local_to_physical:
            raise CensusError(
                f"{run_dir}: local page {local} maps from both physical "
                f"{local_to_physical[local]} and {physical}"
            )
        local_to_physical[local] = physical

    def to_physical_ref(runtime_ref: str) -> str:
        page, index = parse_ref(runtime_ref)
        if page not in local_to_physical:
            raise CensusError(
                f"{run_dir}: runtime ref {runtime_ref!r} sits on local page "
                f"{page}, which physical_to_local does not cover"
            )
        return f"p{local_to_physical[page]}#{index}"

    # ---- reference table -------------------------------------------------
    runtime_of: dict[str, str] = {}
    physical_page_of: dict[str, int] = {}
    for item in coverage["items"]:
        runtime_of[item["source_ref"]] = item["runtime_source_ref"]
        physical_page_of[item["source_ref"]] = item["physical_page"]

    indent = {
        para["reference"]: para
        for para in art["indent_policy.report.json"]["paragraphs"]
    }
    for ref, para in indent.items():
        canonical = para.get("canonical_ref")
        if canonical is None:
            continue
        known = runtime_of.get(ref)
        if known is None:
            runtime_of[ref] = canonical
            physical_page_of.setdefault(ref, para.get("page"))
        elif known != canonical:
            raise CensusError(
                f"{run_dir}: {ref} is runtime {known!r} in demo_coverage but "
                f"{canonical!r} in indent_policy"
            )

    page_kind_of = {
        int(record["page"]): record["page_kind"]
        for record in art["indent_policy.report.json"]["page_records"]
    }
    # page_classify numbers its pages from zero over the physical document.
    classify_kind_of = {
        int(page["page_number"]) + 1: page.get("final_kind")
        for page in art["page_classify.report.json"]["pages"]
    }

    # Every coverage item carries a box, translated or not; layout_report covers
    # only the elements that reached typesetting, so it fills gaps rather than
    # leading.
    boxes = {
        element["source_ref"]: element.get("source_box")
        for element in art["layout_report.json"]["elements"]
    }
    for item in coverage["items"]:
        boxes[item["source_ref"]] = item["source_box"]

    # ---- tracking --------------------------------------------------------
    tracking: dict[str, list[dict]] = {}
    for entries in art["translate_tracking.json"].values():
        for entry in entries:
            for para in entry.get("paragraph", []):
                ref = para.get("source_ref")
                if ref is None:
                    continue
                tracking.setdefault(ref, []).append(para)

    # ---- short units -----------------------------------------------------
    short_units: dict[str, dict] = {}
    for unit in art["short_unit.report.json"].get("units", []):
        short_units[to_physical_ref(unit["paragraph"])] = unit

    owners = art["article_ir.json"].get("by_element", {})

    refusals = {
        candidate["id"]: candidate.get("reason")
        for candidate in art["minimal_run.report.json"]["repair"].get(
            "filtered_candidates", []
        )
    }

    # ---- the three populations ------------------------------------------
    issues: dict[str, dict] = {}
    for issue in art["issues.after.json"]["issues"]:
        if issue.get("kind") != "untranslated_residue":
            continue
        refs = issue.get("paragraph_refs") or []
        if len(refs) != 1:
            raise CensusError(
                f"{run_dir}: issue {issue['id']} carries {len(refs)} paragraph "
                f"refs; the census assumes one per residue issue"
            )
        issues[refs[0]] = issue

    untranslated = {
        item["source_ref"]: item
        for item in coverage["items"]
        if item["final_status"] == "untranslated"
    }

    records: dict[str, Record] = {}

    def record_for(ref: str) -> Record:
        if ref not in records:
            records[ref] = Record(
                sample=sample,
                direction=direction,
                physical_ref=ref,
                runtime_ref=runtime_of.get(ref),
                physical_page=physical_page_of.get(ref) or ref_sort_key(ref)[0],
            )
        return records[ref]

    for ref in issues:
        record_for(ref).populations.append("A")
    for ref in untranslated:
        record_for(ref).populations.append("B")
    for ref in short_units:
        record_for(ref).populations.append("S")

    # ---- fill each record ------------------------------------------------
    for ref, record in records.items():
        issue = issues.get(ref)
        item = untranslated.get(ref)
        para = indent.get(ref)

        if issue is not None:
            geometry = issue.get("geometry") or {}
            corners = [geometry.get(name) for name in ("x", "y", "x2", "y2")]
            record.box = None if any(v is None for v in corners) else corners
            record.issue_id = issue["id"]
            record.layout_label = issue["evidence"].get("layout_label")
            record.repair_refusal = refusals.get(issue["id"])
            evidence = issue["evidence"]
            record.residue_script = evidence["residue_script"]
            record.residue_chars = evidence["residue_chars"]
            record.residue_script_chars = evidence["script_chars"]
            record.residue_ratio = evidence["residue_ratio"]
            record.residue_basis = "detector"
            # Absent from artifacts written before the detector reported it,
            # and absent from every B record, which has no issue at all.
            record.vertical = evidence.get("vertical")
        if record.box is None and item is not None:
            record.box = list(item["source_box"])
        if record.box is None:
            record.box = boxes.get(ref)
        record.aspect_ratio = aspect_ratio(record.box)

        if item is not None:
            record.role = item.get("role")
        if para is not None:
            record.excerpt = para.get("excerpt") or ""
            record.excerpt_truncated = len(record.excerpt) >= _EXCERPT_CAP
            if record.layout_label is None:
                record.layout_label = para.get("layout_label")
        record.page_kind = page_kind_of.get(record.physical_page)
        record.page_kind_at_classify = classify_kind_of.get(record.physical_page)

        rows = tracking.get(ref, [])
        record.tracking_rows = len(rows)
        if rows:
            record.tracking_all_identical = all(
                (row.get("input") or "") == (row.get("output") or "") for row in rows
            )

        # How long the paragraph's text is. Three artifacts bear on it and each
        # is a lower bound rather than the number itself: the translator's input
        # is the source exactly but only exists where the paragraph was
        # submitted; the detector's script count omits every character that is
        # neither Latin nor Han; the indent excerpt is cut at 60 characters and,
        # where a paragraph is composed of formulae, may be markup alone. The
        # criterion asks whether the text is SHORTER than the floor, so the
        # greatest of the available bounds is the one that cannot invent a hit.
        bounds: list[tuple[int, str]] = []
        if rows:
            bounds.append(
                (len(strip_markup(rows[0].get("input"))), "translate_tracking.input")
            )
        if record.residue_basis == "detector":
            bounds.append((record.residue_script_chars, "issue.script_chars"))
        if para is not None:
            bounds.append((len(strip_markup(record.excerpt)), "indent_policy.excerpt"))
        if bounds:
            record.source_chars, record.source_chars_basis = max(bounds)

        # Residue measurement for a record the detector never measured.
        if record.residue_basis is None and record.excerpt:
            counts = script_counts(strip_markup(record.excerpt))
            total = sum(counts.values())
            record.residue_script = script
            record.residue_chars = counts[script]
            record.residue_script_chars = total
            record.residue_ratio = round(counts[script] / total, 4) if total else 0.0
            record.residue_basis = (
                "excerpt_estimate_truncated"
                if record.excerpt_truncated
                else "excerpt_estimate"
            )

        record.owner = owners.get(record.runtime_ref) if record.runtime_ref else None

        classify(record, min_text_length, ref in short_units)
        if "B" in record.populations and "A" not in record.populations:
            attribute_blind_spot(record, page_policies, min_chars, min_ratio)

    return {
        "sample": sample,
        "run_dir": run_dir.as_posix(),
        "direction": direction,
        "source_lang": coverage["source_lang"],
        "target_lang": target_lang,
        "physical_pages": sorted(physical_to_local),
        "thresholds": {
            "residue_script": script,
            "residue_min_script_chars": min_chars,
            "residue_min_ratio": min_ratio,
            "min_text_length": min_text_length,
            "rotated_max_aspect": ROTATED_MAX_ASPECT,
        },
        "totals": {
            "coverage_sources": coverage["totals"]["sources"],
            "population_a": sum(1 for r in records.values() if "A" in r.populations),
            "population_b": sum(1 for r in records.values() if "B" in r.populations),
            "population_s": sum(1 for r in records.values() if "S" in r.populations),
            "a_and_b": sum(
                1
                for r in records.values()
                if "A" in r.populations and "B" in r.populations
            ),
            "b_minus_a": sum(
                1
                for r in records.values()
                if "B" in r.populations and "A" not in r.populations
            ),
            "a_minus_b": sum(
                1
                for r in records.values()
                if "A" in r.populations and "B" not in r.populations
            ),
            # A record with no box cannot be tested for rotation at all, so the
            # rotated count is only as trustworthy as this number is small.
            "records_without_geometry": sum(
                1 for r in records.values() if r.aspect_ratio is None
            ),
        },
        "records": [
            records[ref].as_dict() for ref in sorted(records, key=ref_sort_key)
        ],
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def tally(records: list[dict], categories: tuple[str, ...], key) -> dict[str, int]:
    counts = dict.fromkeys(categories, 0)
    for record in records:
        value = key(record)
        if value is None:
            continue
        if value not in counts:
            raise CensusError(
                f"record {record['sample']}:{record['physical_ref']} carries "
                f"{value!r}, which the vocabulary does not declare"
            )
        counts[value] += 1
    return counts


def _table(header: list[str], rows: list[list]) -> list[str]:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return lines


def _cell(text: str) -> str:
    return "`" + (text or "").replace("|", "\\|").replace("\n", " ") + "`"


def render_markdown(runs: list[dict]) -> str:
    out: list[str] = ["# Untranslated-text census", ""]
    out.append(
        f"Rotation threshold `aspect_ratio < {ROTATED_MAX_ASPECT}`, declared for "
        "this census only. Population A and population B are not comparable "
        "across directions; only B is."
    )
    out.append("")

    out.append("## Runs")
    out.append("")
    out += _table(
        [
            "sample",
            "direction",
            "pages",
            "sources",
            "A",
            "B",
            "S",
            "A&B",
            "B-A",
            "A-B",
            "no-geom",
        ],
        [
            [
                run["sample"],
                run["direction"],
                len(run["physical_pages"]),
                run["totals"]["coverage_sources"],
                run["totals"]["population_a"],
                run["totals"]["population_b"],
                run["totals"]["population_s"],
                run["totals"]["a_and_b"],
                run["totals"]["b_minus_a"],
                run["totals"]["a_minus_b"],
                run["totals"]["records_without_geometry"],
            ]
            for run in runs
        ],
    )
    out.append("")

    directions = sorted({run["direction"] for run in runs})
    populations = (
        ("A", "Population A -- what the detector saw"),
        ("B", "Population B -- what the ledger holds untranslated"),
        ("S", "Population S -- units the short-unit lane took"),
    )
    for tag, label in populations:
        out.append(f"## {label}")
        out.append("")
        rows = []
        for direction in directions:
            selected = [
                record
                for run in runs
                if run["direction"] == direction
                for record in run["records"]
                if tag in record["populations"]
            ]
            counts = tally(selected, CATEGORIES, lambda record: record["category"])
            rows.append(
                [direction, len(selected)] + [counts[name] for name in CATEGORIES]
            )
        out += _table(["direction", "n", *CATEGORIES], rows)
        out.append("")

    out.append("## B minus A -- the detector's blind spot")
    out.append("")
    rows = []
    for direction in directions:
        selected = [
            record
            for run in runs
            if run["direction"] == direction
            for record in run["records"]
            if "B" in record["populations"] and "A" not in record["populations"]
        ]
        counts = tally(
            selected, BLIND_SPOT_CAUSES, lambda record: record["blind_spot_cause"]
        )
        rows.append(
            [direction, len(selected)] + [counts[name] for name in BLIND_SPOT_CAUSES]
        )
    out += _table(["direction", "n", *BLIND_SPOT_CAUSES], rows)
    out.append("")

    out.append("## Unclassified")
    out.append("")
    unclassified = [
        record
        for run in runs
        for record in run["records"]
        if record["category"] == UNCLASSIFIED
        or record["blind_spot_cause"] == UNCLASSIFIED
    ]
    if not unclassified:
        out.append("None.")
    else:
        out += _table(
            [
                "sample",
                "ref",
                "pops",
                "category",
                "cause",
                "aspect",
                "chars",
                "label",
                "excerpt",
            ],
            [
                [
                    record["sample"],
                    record["physical_ref"],
                    "".join(record["populations"]),
                    record["category"],
                    record["blind_spot_cause"],
                    None
                    if record["aspect_ratio"] is None
                    else f"{record['aspect_ratio']:.3f}",
                    record["source_chars"],
                    record["layout_label"],
                    _cell(record["excerpt"]),
                ]
                for record in unclassified
            ],
        )
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path, help="run directories")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--detectors",
        type=Path,
        default=Path("configs/detectors.json"),
        help="detector configuration the runs were measured against",
    )
    parser.add_argument(
        "--page-types",
        type=Path,
        default=Path("configs/page_types.json"),
        help="page type policies",
    )
    args = parser.parse_args(argv)

    with args.detectors.open(encoding="utf-8") as handle:
        detectors_config = json.load(handle)
    with args.page_types.open(encoding="utf-8") as handle:
        page_types = json.load(handle)
    page_policies = {
        entry["name"]: entry.get("policy", {}) for entry in page_types["page_types"]
    }

    runs = [census_run(path, detectors_config, page_policies) for path in args.runs]
    runs.sort(key=lambda run: (run["direction"], run["sample"]))

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "residue-census.v1",
        "vocabulary": {
            "categories": list(CATEGORIES),
            "blind_spot_causes": list(BLIND_SPOT_CAUSES),
            "rotated_max_aspect": ROTATED_MAX_ASPECT,
        },
        "runs": runs,
    }
    census_path = args.out / "residue_census.json"
    with census_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    markdown_path = args.out / "residue_census.md"
    with markdown_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_markdown(runs))
    print(f"wrote {census_path}")
    print(f"wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CensusError as error:
        print(f"residue_census: {error}", file=sys.stderr)
        sys.exit(2)
