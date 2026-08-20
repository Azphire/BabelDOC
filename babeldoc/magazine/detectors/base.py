"""What every detector is built from: the issue, the bounds, and the context.

An issue is a finding about a finished page, not a change to it. It names the
paragraphs it is about by the reference format the review layer already uses,
carries the geometry a human or a repair action would need to find them, and
records the measurement that produced it, so a finding can be argued with
without rerunning the detector that made it.

The bounds live in ``configs/detectors.json`` and are read once. Which
detectors answer for a page is decided there too, keyed by the repair profile
the page's kind declares; no detector, and nothing in this package, names a
page type.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.line_split import paragraph_characters
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config
from babeldoc.magazine.reading_order import paragraph_reading_text

CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "detectors.json"

# Structural sections of the configuration: everything that is not a bounded
# number, and so is validated against what it refers to instead of a range.
DIRECTIONS_KEY = "residue_directions"
SEVERITY_KEY = "severity"
SEVERITY_VOCABULARY_KEY = "severity_vocabulary"
PROFILE_DETECTORS_KEY = "profile_detectors"
DOCUMENT_DETECTORS_KEY = "document_detectors"
DEFAULT_PROFILE_KEY = "default_profile"
PROGRESS_EVIDENCE_KEY = "progress_evidence"

# The pipeline stage whose checkpoint holds the layout as the source drew it.
# A stage name rather than a number, validated against the declared stage order
# so that a checkpoint nobody writes cannot be asked for.
SOURCE_STAGE_KEY = "source_geometry_stage"

_STRUCTURAL_KEYS = (
    DIRECTIONS_KEY,
    SEVERITY_KEY,
    PROFILE_DETECTORS_KEY,
    DEFAULT_PROFILE_KEY,
    PROGRESS_EVIDENCE_KEY,
    SOURCE_STAGE_KEY,
)

# How a per direction threshold is named from the target language it governs.
RATIO_KEY_FORMAT = "residue_min_ratio_into_{language}"

# The policy flags read here. A page whose kind declares no translation has no
# residue to answer for, and the profile is how a page selects its detectors.
TRANSLATE_POLICY_FLAG = "translate"
REPAIR_PROFILE_POLICY_FLAG = "repair_profile"

# Where a page's frame is taken from, in the order it is tried. The crop box is
# what the reader is shown and what the writer offsets the content stream by;
# the media box is the sheet it was imposed on, and stands in only for a page
# carrying no crop box at all.
FRAME_SOURCES = ("cropbox", "mediabox")

# Where a paragraph's rendered extent was measured, as an issue records it.
BOX_FROM_CHARACTERS = "characters"
BOX_FROM_PARAGRAPH = "paragraph"

# Script buckets a character can fall in. Everything else -- digits, spacing,
# punctuation, symbols -- is in neither, and takes no part in the residue share.
LATIN_SCRIPT = "latin"
HAN_SCRIPT = "han"

# What ``unicodedata.name`` calls a character of each bucket. Matching on the
# name rather than on a codepoint range keeps the accented and extended blocks
# in without listing them.
_SCRIPT_NAME_PREFIX = {
    LATIN_SCRIPT: "LATIN ",
    HAN_SCRIPT: "CJK ",
}


class DetectorError(ConfigError):
    """Raised when the detector configuration is malformed."""


@dataclass(frozen=True)
class DetectorConfig:
    """Everything bounded about finding one issue."""

    residue_directions: dict[str, str]
    residue_ratios: dict[str, float]
    residue_min_script_chars: int
    fragment_max_chars: int
    fragment_min_cluster: int
    fragment_max_line_gap_ratio: float
    fragment_min_x_overlap_ratio: float
    fragment_font_size_tolerance: float
    overlap_min_iou: float
    page_safety_margin_ratio: float
    out_of_page_min_overflow_ratio: float
    collision_min_iou: float
    collision_min_coverage: float
    collision_source_min_iou: float
    collision_source_min_coverage: float
    excerpt_chars: int
    severity: dict[str, str]
    default_profile: str
    profile_detectors: dict[str, tuple[str, ...]]
    document_detectors: tuple[str, ...]
    progress_evidence: dict[str, tuple[str, ...]]
    source_geometry_stage: str

    def progress_fields(self, kind: str) -> tuple[str, ...]:
        """The evidence fields quantifying how much of the defect ``kind`` reports."""
        return self.progress_evidence.get(kind, ())

    def detectors_for_profile(self, profile: str | None) -> tuple[str, ...]:
        """Which page detectors answer for a page carrying ``profile``.

        A page whose kind is absent, outside the vocabulary, or declares a
        profile this configuration says nothing about falls to the declared
        default rather than to no detector at all: an unrecognised page is the
        one most likely to carry a defect, not the one least.
        """
        declared = self.profile_detectors.get(profile or "")
        if declared is not None:
            return declared
        return self.profile_detectors.get(self.default_profile, ())

    def residue_rule(self, language: str | None) -> tuple[str, float] | None:
        """The residue script and share for one target language, if declared."""
        script = self.residue_directions.get(language or "")
        if script is None:
            return None
        return script, self.residue_ratios[language]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DetectorError(message)


def _parse_directions(raw: object, source: str, ratios: dict[str, float]) -> dict:
    _require(isinstance(raw, dict) and raw, f"{source}: {DIRECTIONS_KEY} must be an object")
    directions: dict[str, str] = {}
    for language, script in raw.items():
        _require(
            script in _SCRIPT_NAME_PREFIX,
            f"{source}: {DIRECTIONS_KEY}.{language} names an unknown script "
            f"{script!r}; declared are {sorted(_SCRIPT_NAME_PREFIX)}",
        )
        _require(
            language in ratios,
            f"{source}: {DIRECTIONS_KEY}.{language} has no "
            f"{RATIO_KEY_FORMAT.format(language=language)} beside it",
        )
        directions[language] = script
    return directions


def _parse_profiles(raw: object, source: str, known: set[str]) -> dict:
    _require(
        isinstance(raw, dict) and raw,
        f"{source}: {PROFILE_DETECTORS_KEY} must be an object",
    )
    profiles: dict[str, tuple[str, ...]] = {}
    for profile, names in raw.items():
        _require(
            isinstance(names, list) and names,
            f"{source}: {PROFILE_DETECTORS_KEY}.{profile} must list detectors",
        )
        unknown = sorted(set(names) - known)
        _require(
            not unknown,
            f"{source}: {PROFILE_DETECTORS_KEY}.{profile} names unknown "
            f"detectors {unknown}",
        )
        profiles[profile] = tuple(names)
    return profiles


def _parse_progress(raw: object, source: str, kinds: set[str]) -> dict:
    """Validate the per kind list of evidence fields that quantify a defect."""
    if raw is None:
        return {}
    _require(
        isinstance(raw, dict),
        f"{source}: {PROGRESS_EVIDENCE_KEY} must be an object",
    )
    progress: dict[str, tuple[str, ...]] = {}
    for kind, fields in raw.items():
        _require(
            not kinds or kind in kinds,
            f"{source}: {PROGRESS_EVIDENCE_KEY}.{kind} names a kind no detector "
            f"raises; raised are {sorted(kinds)}",
        )
        _require(
            isinstance(fields, list)
            and bool(fields)
            and all(isinstance(name, str) for name in fields),
            f"{source}: {PROGRESS_EVIDENCE_KEY}.{kind} must list evidence fields",
        )
        progress[kind] = tuple(fields)
    return progress


def _parse_source_stage(raw: object, source: str) -> str:
    """Validate the stage whose checkpoint the source layout is read from.

    Against the declared stage order rather than against a list here, so a
    configuration can only name a stage the pipeline actually checkpoints.
    """
    from babeldoc.magazine.checkpoint import stage_names

    declared = stage_names()
    _require(
        isinstance(raw, str) and raw in declared,
        f"{source}: {SOURCE_STAGE_KEY} is {raw!r}, which is not one of the "
        f"declared pipeline stages {list(declared)}",
    )
    return str(raw)


def parse_detector_config(
    raw: dict, source: str, known: set[str], kinds: set[str]
) -> DetectorConfig:
    """Validate one configuration mapping against the detectors it steers."""
    flat = {
        key: value for key, value in raw.items() if key not in _STRUCTURAL_KEYS
    }
    try:
        parameters = dict(validate_bounded_config(flat, CONFIG_PATH))
    except ConfigError as exc:
        raise DetectorError(str(exc)) from exc

    ratios = {
        key.removeprefix(RATIO_KEY_FORMAT.format(language="")): float(value)
        for key, value in parameters.items()
        if key.startswith(RATIO_KEY_FORMAT.format(language=""))
    }
    directions = _parse_directions(raw.get(DIRECTIONS_KEY), source, ratios)

    vocabulary = set(parameters.get(SEVERITY_VOCABULARY_KEY, ()))
    _require(bool(vocabulary), f"{source}: missing {SEVERITY_VOCABULARY_KEY}")
    severity = raw.get(SEVERITY_KEY)
    _require(isinstance(severity, dict), f"{source}: {SEVERITY_KEY} must be an object")
    for kind, weight in severity.items():
        _require(
            weight in vocabulary,
            f"{source}: {SEVERITY_KEY}.{kind} is {weight!r}, outside "
            f"{sorted(vocabulary)}",
        )
    # Every kind a detector can raise has to carry a weight here, so a finding
    # never reaches a report with a severity nobody declared.
    undeclared = sorted(kinds - set(severity))
    _require(not undeclared, f"{source}: {SEVERITY_KEY} omits {undeclared}")

    profiles = _parse_profiles(raw.get(PROFILE_DETECTORS_KEY), source, known)
    default_profile = raw.get(DEFAULT_PROFILE_KEY)
    _require(
        default_profile in profiles,
        f"{source}: {DEFAULT_PROFILE_KEY} is {default_profile!r}, which "
        f"{PROFILE_DETECTORS_KEY} does not declare",
    )
    document = tuple(parameters.get(DOCUMENT_DETECTORS_KEY, ()))
    unknown = sorted(set(document) - known)
    _require(not unknown, f"{source}: {DOCUMENT_DETECTORS_KEY} names {unknown}")

    return DetectorConfig(
        residue_directions=directions,
        residue_ratios=ratios,
        residue_min_script_chars=int(parameters["residue_min_script_chars"]),
        fragment_max_chars=int(parameters["fragment_max_chars"]),
        fragment_min_cluster=int(parameters["fragment_min_cluster"]),
        fragment_max_line_gap_ratio=float(parameters["fragment_max_line_gap_ratio"]),
        fragment_min_x_overlap_ratio=float(parameters["fragment_min_x_overlap_ratio"]),
        fragment_font_size_tolerance=float(parameters["fragment_font_size_tolerance"]),
        overlap_min_iou=float(parameters["overlap_min_iou"]),
        page_safety_margin_ratio=float(parameters["page_safety_margin_ratio"]),
        out_of_page_min_overflow_ratio=float(
            parameters["out_of_page_min_overflow_ratio"]
        ),
        collision_min_iou=float(parameters["collision_min_iou"]),
        collision_min_coverage=float(parameters["collision_min_coverage"]),
        collision_source_min_iou=float(parameters["collision_source_min_iou"]),
        collision_source_min_coverage=float(
            parameters["collision_source_min_coverage"]
        ),
        excerpt_chars=int(parameters["excerpt_chars"]),
        severity=dict(severity),
        default_profile=str(default_profile),
        profile_detectors=profiles,
        document_detectors=document,
        progress_evidence=_parse_progress(
            raw.get(PROGRESS_EVIDENCE_KEY), source, kinds
        ),
        source_geometry_stage=_parse_source_stage(raw.get(SOURCE_STAGE_KEY), source),
    )


@lru_cache(maxsize=2)
def load_detector_config(
    path: str | None = None,
    known: tuple[str, ...] = (),
    kinds: tuple[str, ...] = (),
) -> DetectorConfig:
    """Load and validate ``configs/detectors.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return parse_detector_config(raw, config_path.name, set(known), set(kinds))


def script_of(character: str) -> str | None:
    """Which script bucket a character belongs to, or None for neither."""
    if not character.isalpha():
        return None
    try:
        name = unicodedata.name(character)
    except ValueError:
        return None
    for script, prefix in _SCRIPT_NAME_PREFIX.items():
        if name.startswith(prefix):
            return script
    return None


def script_counts(text: str) -> dict[str, int]:
    """How many characters of each declared script the text holds."""
    counts = dict.fromkeys(_SCRIPT_NAME_PREFIX, 0)
    for character in text:
        script = script_of(character)
        if script is not None:
            counts[script] += 1
    return counts


def rendered_text(paragraph) -> str:
    """What the page shows for this paragraph, as characters rather than markup.

    Read in the order a reader reads it rather than in the order the composition
    is stored in, which for a paragraph set along the vertical axis are not the
    same order. The ordering rule is shared with the repair path, so a detector
    and the action answering for what it found are looking at one string.
    """
    return paragraph_reading_text(paragraph)


def box_tuple(box) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    values = (box.x, box.y, box.x2, box.y2)
    if any(value is None for value in values):
        return None
    return tuple(float(value) for value in values)


def union_box(boxes) -> dict[str, float] | None:
    """The smallest box holding every box given, as an issue records geometry."""
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    return {
        "x": min(box[0] for box in present),
        "y": min(box[1] for box in present),
        "x2": max(box[2] for box in present),
        "y2": max(box[3] for box in present),
    }


def page_frame(page) -> tuple[tuple[float, float, float, float], str] | None:
    """The box a page's own coordinates are bounded by, and where it came from.

    The crop box, else the media box. This is the frame the rest of the
    pipeline already measures a page by -- the writer offsets the content
    stream it builds by the crop box origin, and the typesetting stage sizes
    its own insets from the same two numbers -- so a paragraph box and this
    box are in one space and can be compared without a transform.
    """
    for name in FRAME_SOURCES:
        holder = getattr(page, name, None)
        if holder is None:
            continue
        box = box_tuple(holder.box)
        if box is not None:
            return box, name
    return None


def inset(box, ratio: float) -> tuple[float, float, float, float]:
    """One box drawn in by a share of its own size, along each axis separately.

    A share of the page rather than an absolute distance, because the corpus is
    not one page size and a margin stated in points would mean something
    different on each sheet. Each axis is drawn in by a share of that axis's own
    extent, so the inset of a tall page is proportionally the same top and side.
    """
    left, bottom, right, top = box
    horizontal = (right - left) * ratio
    vertical = (top - bottom) * ratio
    return (
        left + horizontal,
        bottom + vertical,
        right - horizontal,
        top - vertical,
    )


def character_extent(characters) -> tuple[float, float, float, float] | None:
    """The smallest box holding every character box given."""
    boxes = [box_tuple(item.box) for item in characters]
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    return (
        min(box[0] for box in present),
        min(box[1] for box in present),
        max(box[2] for box in present),
        max(box[3] for box in present),
    )


def rendered_box(paragraph) -> tuple[tuple[float, float, float, float] | None, str]:
    """The extent of the ink a paragraph puts on the page, and how it was read.

    The union of the boxes of the characters the paragraph is laid out as,
    rather than the paragraph's own box, because the two are not the same thing
    and the difference is the defect: the box is where the stage decided the
    paragraph goes, and a character set larger than the line that box was
    measured for is drawn outside it. A paragraph carrying no character to
    measure -- one built by hand, or one whose composition is a unicode run
    nothing has laid out yet -- falls back to its box, and says so.
    """
    extent = character_extent(paragraph_characters(paragraph))
    if extent is not None:
        return extent, BOX_FROM_CHARACTERS
    return box_tuple(paragraph.box), BOX_FROM_PARAGRAPH


def overflow(box, bounds) -> dict[str, float]:
    """How far a box reaches past each side of the bounds, never below zero."""
    return {
        "left": max(0.0, bounds[0] - box[0]),
        "bottom": max(0.0, bounds[1] - box[1]),
        "right": max(0.0, box[2] - bounds[2]),
        "top": max(0.0, box[3] - bounds[3]),
    }


def intersection_over_union(left, right) -> float:
    """Area shared by two boxes over the area they cover together."""
    width = min(left[2], right[2]) - max(left[0], right[0])
    height = min(left[3], right[3]) - max(left[1], right[1])
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - shared
    return shared / union if union > 0 else 0.0


def coverage(left, right) -> float:
    """Area shared by two boxes over the area of the smaller of them.

    The measure that answers for the overlap the ratio over the union cannot
    see. A small box standing wholly inside a large one shares all of its own
    area and a small share of the area the two cover together, so the union
    ratio reports nearly nothing where this reports one. Zero where either box
    has no area, which is a box nothing can stand inside.
    """
    width = min(left[2], right[2]) - max(left[0], right[0])
    height = min(left[3], right[3]) - max(left[1], right[1])
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    smaller = min(
        max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1]),
        max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1]),
    )
    return shared / smaller if smaller > 0 else 0.0


@dataclass(frozen=True)
class Issue:
    """One finding about a finished document."""

    kind: str
    page: int
    paragraph_refs: tuple[str, ...]
    geometry: dict[str, float] | None
    severity: str
    evidence: dict
    detector: str
    detected_at_iteration: int = 0

    @property
    def id(self) -> str:
        """A name stable across runs of one detector over one document.

        Built from the detector, the page and the references, all of which are
        positional rather than minted per run, so the same finding carries the
        same name on a rerun and a repair loop can tell a surviving issue from
        a new one.
        """
        tail = "+".join(self.paragraph_refs) or self.evidence.get("chain_id") or "page"
        return f"{self.detector}:p{self.page}:{tail}"

    def as_record(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "page": self.page,
            "paragraph_refs": list(self.paragraph_refs),
            "geometry": self.geometry,
            "severity": self.severity,
            "evidence": self.evidence,
            "detector": self.detector,
            "detected_at_iteration": self.detected_at_iteration,
        }


@dataclass(frozen=True)
class PageView:
    """One page as a detector reads it, with its label and its policy."""

    label: int
    page: object
    policy: dict[str, object] | None

    def flag(self, name: str, default=None):
        return default if self.policy is None else self.policy.get(name, default)

    def reference(self, index: int) -> str:
        return paragraph_reference(self.label, index)


@dataclass
class DetectionContext:
    """Everything a detector may read, and nothing it may write."""

    pages: list[PageView]
    config: DetectorConfig
    language: str | None
    iteration: int = 0
    translation_performed: bool = True
    working_dir: Path | None = None
    # Where every paragraph stood before anything was translated, for the
    # detectors whose finding is about what the translation changed rather than
    # about what the finished page shows. None where the run kept no checkpoint
    # to read it from, in which case those detectors are not run at all.
    source_geometry: object | None = None
    notes: list[str] = field(default_factory=list)
    # Structured notes, filed by the detector that made them. A note in
    # ``notes`` is a sentence for a human and a row here is a fact a gate or a
    # census can read back: how many of a page's pairs a comparison answered
    # for, and which of the several routes to one verdict each of them took.
    records: dict[str, list] = field(default_factory=dict)

    def file(self, detector: str, row: dict) -> None:
        """Record one structured note under the detector that made it."""
        self.records.setdefault(detector, []).append(row)

    def severity_of(self, kind: str) -> str:
        """The declared weight of one issue kind, which validation guarantees."""
        return self.config.severity[kind]
