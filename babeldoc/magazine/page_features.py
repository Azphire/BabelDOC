"""Deterministic per-page feature extraction from the BabelDOC IL.

Every feature is derived from geometry, counts and character statistics that
any magazine shares: nothing here inspects a publication, a language or a page
type name, and no LLM or network call is involved. ``extract_page_features`` is
a pure function of its arguments, so the same IL page always yields bit
identical values.

All tunable numbers live in ``configs/page_features.json``; this module holds
no numeric heuristic literals.
"""

from __future__ import annotations

import json
import re
import statistics
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "page_features.json"

# Feature vector layout. The order is the report order; scoring is by name.
FEATURE_NAMES: tuple[str, ...] = (
    "text_coverage_ratio",
    "image_area_ratio",
    "paragraph_count",
    "mean_paragraph_chars",
    "short_paragraph_ratio",
    "numeric_token_density",
    "leader_dot_line_ratio",
    "title_label_ratio",
    "distinct_font_size_count",
    "max_font_size_ratio",
    "column_count_estimate",
    "page_relative_position",
)

# Features whose definition bounds them to [0, 1]; asserted by the gate.
RATIO_FEATURES: frozenset[str] = frozenset(
    {
        "text_coverage_ratio",
        "image_area_ratio",
        "short_paragraph_ratio",
        "numeric_token_density",
        "leader_dot_line_ratio",
        "title_label_ratio",
        "page_relative_position",
    }
)

# Substring that marks a layout label as a heading. This is a layout label from
# the upstream layout model, not a page type name.
_TITLE_LABEL_MARKER = "title"

# Ellipsis is expanded before leader dot detection so that a run is always
# measured in dots, whichever way the publisher typeset it.
_ELLIPSIS = "…"
# Characters a publisher may set between the dots of a leader.
_DOT_SEPARATORS = "  "

_RANGE_SUFFIX = "_allowed_range"


class ConfigError(ValueError):
    """Raised when a magazine JSON configuration file is malformed."""


def _parse_range(raw: object, key: str) -> tuple[float, float]:
    if not isinstance(raw, str) or ".." not in raw:
        raise ConfigError(f"{key}: allowed range must be a 'low..high' string")
    low_text, _, high_text = raw.partition("..")
    try:
        low, high = float(low_text), float(high_text)
    except ValueError:
        raise ConfigError(f"{key}: allowed range bounds must be numbers") from None
    if low > high:
        raise ConfigError(f"{key}: allowed range is inverted")
    return low, high


def validate_bounded_config(config: dict, path: Path) -> dict:
    """Check that every numeric entry declares and respects an allowed range.

    Returns the parameter mapping without the ``description`` and range keys,
    so callers index it by plain parameter name.
    """
    parameters: dict[str, float] = {}
    for key, value in config.items():
        if key == "description" or key.endswith(_RANGE_SUFFIX):
            continue
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ConfigError(f"{path.name}: {key} is not a number")
        range_key = f"{key}{_RANGE_SUFFIX}"
        if range_key not in config:
            raise ConfigError(f"{path.name}: {key} has no {_RANGE_SUFFIX}")
        low, high = _parse_range(config[range_key], f"{path.name}:{key}")
        if not low <= value <= high:
            raise ConfigError(
                f"{path.name}: {key}={value} outside allowed range {low}..{high}"
            )
        parameters[key] = value

    orphans = [
        key
        for key in config
        if key.endswith(_RANGE_SUFFIX) and key[: -len(_RANGE_SUFFIX)] not in parameters
    ]
    if orphans:
        raise ConfigError(f"{path.name}: allowed range without parameter: {orphans}")
    return parameters


REQUIRED_PARAMETERS: frozenset[str] = frozenset(
    {
        "grid_resolution",
        "short_char_limit",
        "leader_dot_min_run",
        "column_gap_ratio",
        "column_count_max",
        "font_size_bucket",
        "label_agreement_min",
    }
)


@lru_cache(maxsize=1)
def load_feature_config(path: str | None = None) -> dict[str, float]:
    """Load and validate ``configs/page_features.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = validate_bounded_config(raw, config_path)
    missing = sorted(REQUIRED_PARAMETERS - set(parameters))
    if missing:
        raise ConfigError(f"{config_path.name}: missing parameters {missing}")
    return parameters


@lru_cache(maxsize=8)
def _leader_dot_pattern(min_run: int) -> re.Pattern[str]:
    """A run of ``min_run`` dots, optionally separated by single spaces."""
    separator = re.escape(_DOT_SEPARATORS)
    return re.compile(rf"\.(?:[{separator}]?\.){{{min_run - 1},}}")


def _box_of(cropbox: il_version_1.Cropbox | None) -> il_version_1.Box | None:
    return cropbox.box if cropbox is not None else None


def _grid_coverage(
    boxes: list[il_version_1.Box],
    frame: il_version_1.Box,
    resolution: int,
) -> float:
    """Fraction of a ``resolution`` square grid over ``frame`` that ``boxes`` hit.

    A cell counts as occupied as soon as it intersects one of the boxes, which
    keeps the measure independent of how a publisher splits a region into
    objects.
    """
    width = frame.x2 - frame.x
    height = frame.y2 - frame.y
    if width <= 0 or height <= 0:
        return 0.0

    occupied: set[int] = set()
    for box in boxes:
        low_x = min(box.x, box.x2)
        high_x = max(box.x, box.x2)
        low_y = min(box.y, box.y2)
        high_y = max(box.y, box.y2)
        if high_x < frame.x or low_x > frame.x2:
            continue
        if high_y < frame.y or low_y > frame.y2:
            continue
        first_column = _cell_index(low_x - frame.x, width, resolution)
        last_column = _cell_index(high_x - frame.x, width, resolution)
        first_row = _cell_index(low_y - frame.y, height, resolution)
        last_row = _cell_index(high_y - frame.y, height, resolution)
        for row in range(first_row, last_row + 1):
            base = row * resolution
            occupied.update(range(base + first_column, base + last_column + 1))
    return len(occupied) / float(resolution * resolution)


def _cell_index(offset: float, extent: float, resolution: int) -> int:
    index = int(offset / extent * resolution)
    return max(0, min(resolution - 1, index))


def _paragraph_font_sizes(page: il_version_1.Page) -> list[float]:
    sizes = []
    for paragraph in page.pdf_paragraph:
        style = paragraph.pdf_style
        if style is not None and style.font_size:
            sizes.append(float(style.font_size))
    return sizes


def _column_count(
    page: il_version_1.Page,
    frame: il_version_1.Box,
    gap_ratio: float,
    maximum: int,
) -> int:
    """Cluster paragraph box centres along x, splitting on wide gaps."""
    centres = sorted(
        (paragraph.box.x + paragraph.box.x2) / 2.0
        for paragraph in page.pdf_paragraph
        if paragraph.box is not None
    )
    if not centres:
        return 0
    gap_threshold = (frame.x2 - frame.x) * gap_ratio
    clusters = 1
    previous = centres[0]
    for centre in centres[1:]:
        if centre - previous >= gap_threshold:
            clusters += 1
        previous = centre
    return min(clusters, maximum)


def extract_page_features(
    page: il_version_1.Page,
    document: il_version_1.Document,
    config: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute the deterministic feature vector of one IL page.

    Pure: it reads ``page`` and ``document`` and returns a new dict, mutating
    nothing. A page without paragraphs scores zero on every feature.
    """
    parameters = load_feature_config() if config is None else config
    resolution = int(parameters["grid_resolution"])
    short_char_limit = parameters["short_char_limit"]
    leader_dot_min_run = int(parameters["leader_dot_min_run"])
    font_size_bucket = parameters["font_size_bucket"]

    frame = _box_of(page.cropbox)
    paragraphs = list(page.pdf_paragraph)
    texts = [paragraph.unicode or "" for paragraph in paragraphs]
    joined = "".join(texts)

    if frame is None:
        text_coverage = image_coverage = 0.0
        columns = 0
    else:
        text_coverage = _grid_coverage(
            [p.box for p in paragraphs if p.box is not None], frame, resolution
        )
        image_coverage = _grid_coverage(
            [f.box for f in page.pdf_figure if f.box is not None], frame, resolution
        )
        columns = _column_count(
            page,
            frame,
            parameters["column_gap_ratio"],
            int(parameters["column_count_max"]),
        )

    count = len(paragraphs)
    if count:
        mean_chars = sum(len(text) for text in texts) / count
        short_ratio = sum(len(text) <= short_char_limit for text in texts) / count
        pattern = _leader_dot_pattern(leader_dot_min_run)
        leader_ratio = (
            sum(bool(pattern.search(text.replace(_ELLIPSIS, "..."))) for text in texts)
            / count
        )
        title_ratio = (
            sum(
                _TITLE_LABEL_MARKER in (paragraph.layout_label or "").lower()
                for paragraph in paragraphs
            )
            / count
        )
    else:
        mean_chars = short_ratio = leader_ratio = title_ratio = 0.0

    non_space = sum(not character.isspace() for character in joined)
    digits = sum(character.isdigit() for character in joined)
    numeric_density = digits / non_space if non_space else 0.0

    sizes = _paragraph_font_sizes(page)
    if sizes:
        distinct_sizes = len({round(size / font_size_bucket) for size in sizes})
        median = statistics.median(sizes)
        size_ratio = max(sizes) / median if median > 0 else 0.0
    else:
        distinct_sizes = 0
        size_ratio = 0.0

    total_pages = document.total_pages or 0
    page_number = page.page_number or 0
    position = page_number / total_pages if total_pages > 0 else 0.0

    return {
        "text_coverage_ratio": text_coverage,
        "image_area_ratio": image_coverage,
        "paragraph_count": float(count),
        "mean_paragraph_chars": mean_chars,
        "short_paragraph_ratio": short_ratio,
        "numeric_token_density": numeric_density,
        "leader_dot_line_ratio": leader_ratio,
        "title_label_ratio": title_ratio,
        "distinct_font_size_count": float(distinct_sizes),
        "max_font_size_ratio": size_ratio,
        "column_count_estimate": float(columns),
        "page_relative_position": min(1.0, max(0.0, position)),
    }
