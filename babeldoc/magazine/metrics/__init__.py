"""Evaluation metrics: what a produced document is measured by, and by nothing else.

Every module in this package answers one question about a finished run, and
every one of them obeys the same four rules.

*Deterministic.* A metric reads artefacts and returns numbers. No module here
makes a model request, opens a network connection or reads a credential, so a
metric can be recomputed from a frozen checkpoint years after the run that made
it, and two runs of a metric over one artefact return the same bits.

*Defined once.* Each metric carries its own definition, in LaTeX, in the
docstring of the module that implements it. Where the definition already exists
in ``docs/dissertation/background_chapter.tex`` the docstring cites the
``\\label{eq:...}`` rather than restating it, so the paper and the code cannot
drift; where the metric is new to this project the docstring is the definition
and the paper will quote it. ``docs/eval/metric_contract.md`` is the register of
which is which.

*Bounded.* Every number a metric needs is in ``configs/metrics.json`` with its
allowed range, except for the ones it shares with something else: the sentence
enders, the line banding rule and the column split rule come from
``configs/chain_detection.json`` and the source term qualification from
``configs/term_consistency.json``. A metric that repeated one of those would
let a retune move the detector and leave the measurement behind.

*Blind to the publication.* A metric sees geometry, counts and characters. No
module here names a magazine, a page type or a layout label outside the
vocabularies the configuration declares.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config

CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "metrics.json"


class MetricError(ConfigError):
    """Raised when a metric cannot be computed from what it was given."""


@dataclass(frozen=True)
class MetricsConfig:
    """Everything bounded about measuring a produced document."""

    image_layout_classes: tuple[str, ...]
    min_element_area_ratio: float
    alignment_max_delta: float
    image_pair_max_area_ratio: float
    ltcr_min_occurrences: int
    ltcr_min_paragraphs: int
    report_float_digits: int


@lru_cache(maxsize=2)
def load_metrics_config(path: str | None = None) -> MetricsConfig:
    """Load and validate ``configs/metrics.json``."""
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    try:
        parameters = validate_bounded_config(raw, config_path)
    except ConfigError as exc:
        raise MetricError(str(exc)) from exc
    missing = sorted(set(MetricsConfig.__dataclass_fields__) - set(parameters))
    if missing:
        raise MetricError(f"{config_path.name}: missing parameters {missing}")
    return MetricsConfig(
        image_layout_classes=tuple(parameters["image_layout_classes"]),
        min_element_area_ratio=float(parameters["min_element_area_ratio"]),
        alignment_max_delta=float(parameters["alignment_max_delta"]),
        image_pair_max_area_ratio=float(parameters["image_pair_max_area_ratio"]),
        ltcr_min_occurrences=int(parameters["ltcr_min_occurrences"]),
        ltcr_min_paragraphs=int(parameters["ltcr_min_paragraphs"]),
        report_float_digits=int(parameters["report_float_digits"]),
    )


def rounded(value, digits: int):
    """One number as a report writes it, leaving anything that is not one alone."""
    if isinstance(value, float):
        return round(value, digits)
    return value
