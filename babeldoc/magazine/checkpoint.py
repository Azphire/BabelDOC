"""XML checkpoints for the BabelDOC intermediate language (IL).

The upstream pipeline already writes per-stage JSON dumps in debug mode, but
JSON is a write-only inspection format. XML is the only round-trippable IL
format, so checkpoints are written as XML and can be reloaded into a
``Document`` object. A JSON sibling is written next to each XML checkpoint for
human inspection only.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter

logger = logging.getLogger(__name__)

CHECKPOINT_PREFIX = "checkpoint."

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "checkpoint_stages.json"
)


class CheckpointError(RuntimeError):
    """Raised when a checkpoint cannot be written or fails its integrity check."""


@lru_cache(maxsize=1)
def _stage_config() -> tuple[tuple[str, ...], int]:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        config = json.load(f)
    return tuple(config["stages"]), int(config["ordinal_width"])


@lru_cache(maxsize=1)
def _converter() -> XMLConverter:
    return XMLConverter()


def stage_names() -> tuple[str, ...]:
    """Return the declared pipeline stage names in execution order."""
    return _stage_config()[0]


def checkpoint_stem(stage_name: str) -> str:
    """Build the checkpoint file stem for a stage, without extension.

    The stage ordinal is zero padded so that lexicographic order over the
    resulting filenames equals pipeline execution order.
    """
    stages, width = _stage_config()
    try:
        ordinal = stages.index(stage_name) + 1
    except ValueError:
        raise CheckpointError(
            f"unknown checkpoint stage {stage_name!r}; "
            f"declare it in {_CONFIG_PATH.name}"
        ) from None
    return f"{CHECKPOINT_PREFIX}{ordinal:0{width}d}_{stage_name}"


def dump_checkpoint(
    docs: il_version_1.Document,
    translation_config,
    stage_name: str,
) -> Path:
    """Write an XML checkpoint of ``docs`` for ``stage_name``.

    A same-named ``.json`` file is written alongside for human inspection. The
    XML path is returned.
    """
    stem = checkpoint_stem(stage_name)
    xml_path = Path(translation_config.get_working_file_path(f"{stem}.xml"))
    json_path = Path(translation_config.get_working_file_path(f"{stem}.json"))

    converter = _converter()
    converter.write_xml(docs, str(xml_path))
    converter.write_json(docs, str(json_path))
    logger.debug("wrote IL checkpoint %s", xml_path)
    return xml_path


def load_checkpoint(path: str | Path) -> il_version_1.Document:
    """Read an XML checkpoint back into a ``Document``.

    Verifies that the declared ``total_pages`` matches the number of pages
    actually present, which catches truncated or hand-edited checkpoints.
    """
    path = Path(path)
    docs = _converter().read_xml(str(path))
    if docs.total_pages != len(docs.page):
        raise CheckpointError(
            f"corrupt checkpoint {path}: total_pages={docs.total_pages} "
            f"but {len(docs.page)} page elements present"
        )
    return docs
