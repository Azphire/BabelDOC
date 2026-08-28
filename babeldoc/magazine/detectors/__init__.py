"""Side-effect-free facade for the minimal detector package.

The copied donor package also contains a profile-driven unified runner. The
minimal pipeline deliberately does not expose that runner: importing a direct
detector must not import runtime profiles, taxonomy, checkpoints, RunTrace, or
the multi-round repair controller.
"""

from __future__ import annotations

from babeldoc.magazine.detectors.base import CONFIG_PATH
from babeldoc.magazine.detectors.base import DetectionContext
from babeldoc.magazine.detectors.base import DetectorConfig
from babeldoc.magazine.detectors.base import DetectorError
from babeldoc.magazine.detectors.base import Issue
from babeldoc.magazine.detectors.base import PageView
from babeldoc.magazine.detectors.base import load_detector_config

DETECTOR_NAMES = (
    "chain_conservation",
    "fixed_asset_drift",
    "fragment_cluster",
    "out_of_page",
    "text_text_collision",
    "untranslated_residue",
)
DETECTOR_KINDS = DETECTOR_NAMES

__all__ = [
    "CONFIG_PATH",
    "DETECTOR_KINDS",
    "DETECTOR_NAMES",
    "DetectionContext",
    "DetectorConfig",
    "DetectorError",
    "Issue",
    "PageView",
    "detector_config",
    "detector_kinds",
]


def detector_kinds() -> tuple[str, ...]:
    """Return the closed issue vocabulary of the minimal detector path."""
    return DETECTOR_KINDS


def detector_config() -> DetectorConfig:
    """Load the minimal bounded config without importing the unified runner."""
    return load_detector_config(CONFIG_PATH.as_posix(), DETECTOR_NAMES, DETECTOR_KINDS)
