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
from bisect import bisect_left
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.resource_paths import config_path

CONFIG_PATH = config_path("page_features.json")

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

# Suffix of the document level companion of a raw feature: where the page sits
# among the pages of its own document, rather than an absolute quantity.
PERCENTILE_SUFFIX = "_pctl"

# Substring that marks a layout label as a heading. This is a layout label from
# the upstream layout model, not a page type name.
_TITLE_LABEL_MARKER = "title"

# Ellipsis is expanded before leader dot detection so that a run is always
# measured in dots, whichever way the publisher typeset it.
_ELLIPSIS = "…"
# Characters a publisher may set between the dots of a leader.
_DOT_SEPARATORS = "  "

_RANGE_SUFFIX = "_allowed_range"
_CHOICE_SUFFIX = "_allowed"

# A configuration entry is either a bounded number or a closed vocabulary of
# IL structure values.
Parameter = float | str | tuple[str, ...]


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


def validate_bounded_config(config: dict, path: Path) -> dict[str, Parameter]:
    """Check that every entry declares and respects its bounds.

    A numeric entry is bounded by its ``<name>_allowed_range`` sibling. A list
    entry is a closed vocabulary of IL structure values, so the list is its own
    bound: it must hold at least one non-empty string and takes no range. A
    string entry selects one policy out of the closed vocabulary its
    ``<name>_allowed`` sibling declares, so an unknown selection is refused by
    the batch that declares the vocabulary rather than the one that reads it.

    Returns the parameter mapping without the ``description`` and range keys,
    so callers index it by plain parameter name.
    """
    parameters: dict[str, Parameter] = {}
    for key, value in config.items():
        if key == "description" or key.endswith(_RANGE_SUFFIX):
            continue
        if isinstance(value, list):
            if not value or any(
                not isinstance(item, str) or not item for item in value
            ):
                raise ConfigError(
                    f"{path.name}: {key} must list at least one non-empty string"
                )
            if f"{key}{_RANGE_SUFFIX}" in config:
                raise ConfigError(f"{path.name}: {key} is a vocabulary, not a range")
            parameters[key] = tuple(value)
            continue
        if isinstance(value, str):
            choice_key = f"{key}{_CHOICE_SUFFIX}"
            allowed = config.get(choice_key)
            if not isinstance(allowed, list):
                raise ConfigError(f"{path.name}: {key} has no {choice_key} vocabulary")
            if value not in allowed:
                raise ConfigError(
                    f"{path.name}: {key}={value!r} is not one of {sorted(allowed)}"
                )
            parameters[key] = value
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
        "min_image_side_ratio",
        "column_min_width_ratio",
        "image_form_types",
        "column_estimate_labels",
        "percentile_features",
    }
)


@lru_cache(maxsize=1)
def load_feature_config(path: str | None = None) -> dict[str, Parameter]:
    """Load and validate ``configs/page_features.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    parameters = validate_bounded_config(raw, config_path)
    missing = sorted(REQUIRED_PARAMETERS - set(parameters))
    if missing:
        raise ConfigError(f"{config_path.name}: missing parameters {missing}")
    selected = parameters["percentile_features"]
    unknown = sorted(set(selected) - set(FEATURE_NAMES))
    if unknown:
        raise ConfigError(
            f"{config_path.name}: percentile_features names unknown features {unknown}"
        )
    if len(set(selected)) != len(selected):
        raise ConfigError(f"{config_path.name}: percentile_features repeats a feature")
    return parameters


def percentile_feature_names(
    config: dict[str, Parameter] | None = None,
) -> tuple[str, ...]:
    """Percentile keys ``extract_document_features`` adds, in configured order."""
    parameters = load_feature_config() if config is None else config
    return tuple(
        f"{name}{PERCENTILE_SUFFIX}" for name in parameters["percentile_features"]
    )


def known_feature_names(
    config: dict[str, Parameter] | None = None,
) -> tuple[str, ...]:
    """Every feature name a rule may reference: raw features plus percentiles."""
    return FEATURE_NAMES + percentile_feature_names(config)


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


def _image_boxes(
    page: il_version_1.Page,
    frame: il_version_1.Box,
    form_types: tuple[str, ...],
    min_side_ratio: float,
) -> list[il_version_1.Box]:
    """Boxes of the artwork occupying a page.

    Upstream files a raster image under ``pdf_form`` with one of the configured
    form types; ``pdf_figure`` only fills on the legacy parse path, so both are
    read. Boxes degenerate on either axis are dropped: page wrapping forms
    flattened to zero extent and hairline decorations occupy no visual area,
    and counting them would swamp the real artwork.
    """
    width = frame.x2 - frame.x
    height = frame.y2 - frame.y
    candidates = [figure.box for figure in page.pdf_figure if figure.box is not None]
    candidates.extend(
        form.box
        for form in page.pdf_form
        if form.box is not None and form.form_type in form_types
    )
    return [
        box
        for box in candidates
        if abs(box.x2 - box.x) >= width * min_side_ratio
        and abs(box.y2 - box.y) >= height * min_side_ratio
    ]


def _column_count(
    page: il_version_1.Page,
    frame: il_version_1.Box,
    gap_ratio: float,
    maximum: int,
    labels: tuple[str, ...],
    min_width_ratio: float,
) -> int:
    """Cluster paragraph box centres along x, splitting on wide gaps.

    Only running text of a full measure votes. Page furniture, captions and
    stray fragments sit at their own x positions and would otherwise each open
    a cluster, pinning the estimate at its ceiling on every page.
    """
    width = frame.x2 - frame.x
    minimum_width = width * min_width_ratio
    centres = sorted(
        (paragraph.box.x + paragraph.box.x2) / 2.0
        for paragraph in page.pdf_paragraph
        if paragraph.box is not None
        and (paragraph.layout_label or "") in labels
        and paragraph.box.x2 - paragraph.box.x >= minimum_width
    )
    if not centres:
        return 0
    gap_threshold = width * gap_ratio
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
    config: dict[str, Parameter] | None = None,
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
            _image_boxes(
                page,
                frame,
                parameters["image_form_types"],
                parameters["min_image_side_ratio"],
            ),
            frame,
            resolution,
        )
        columns = _column_count(
            page,
            frame,
            parameters["column_gap_ratio"],
            int(parameters["column_count_max"]),
            parameters["column_estimate_labels"],
            parameters["column_min_width_ratio"],
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

    # page_number is 0-based upstream, so the ordinal is one past it and the
    # last page of a document sits exactly at 1.0.
    total_pages = document.total_pages or 0
    page_number = page.page_number or 0
    position = (page_number + 1) / total_pages if total_pages > 0 else 0.0

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


def _midranks(values: list[float]) -> list[float]:
    """Midrank percentile of every value among the values of its own document.

    ``(count(v < x) + 0.5 * count(v == x)) / n``. Ties share a rank, so a
    feature that is constant across a document lands on 0.5 on every page and
    simply stops discriminating, and no value ever reaches 0 or 1.
    """
    total = len(values)
    ordered = sorted(values)
    ranks = []
    for value in values:
        below = bisect_left(ordered, value)
        equal = bisect_right(ordered, value) - below
        ranks.append((below + 0.5 * equal) / total)
    return ranks


def extract_document_features(
    document: il_version_1.Document,
    config: dict[str, Parameter] | None = None,
) -> list[dict[str, float]]:
    """Feature vectors of every page, each carrying its document percentiles.

    The raw keys are exactly what ``extract_page_features`` returns for the
    same page. The ``_pctl`` companions state where the page sits inside this
    document, so a threshold written against one reads as a relative position
    in the issue at hand rather than an absolute quantity of a design grid,
    which is what lets it carry across publications.

    Pure and deterministic: the same IL always yields the same list, in page
    order.
    """
    parameters = load_feature_config() if config is None else config
    vectors = [
        extract_page_features(page, document, parameters) for page in document.page
    ]
    if not vectors:
        return vectors
    for name in parameters["percentile_features"]:
        key = f"{name}{PERCENTILE_SUFFIX}"
        ranks = _midranks([vector[name] for vector in vectors])
        for vector, rank in zip(vectors, ranks, strict=True):
            vector[key] = rank
    return vectors
