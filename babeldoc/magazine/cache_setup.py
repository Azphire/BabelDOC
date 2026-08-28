"""Redirect the BabelDOC translation cache to a project-local database.

The upstream cache initialises itself on import against ``~/.cache/babeldoc``
and evicts rows beyond MAX_CACHE_ROWS. For magazine work the cache is a
reproducibility asset: it must live with the project and must never drop a
previously translated segment. Every entry point of this project calls
``use_project_cache`` before performing any translation.
"""

from __future__ import annotations

import logging
from pathlib import Path

from babeldoc.translator.cache import init_db

logger = logging.getLogger(__name__)

# Location of the project-local cache database, relative to the project root.
PROJECT_CACHE_RELPATH = Path("examples") / "cache" / "cache.v1.db"


def project_root() -> Path:
    """Return the repository root that contains ``examples/`` and ``configs/``."""
    return Path(__file__).resolve().parents[2]


def use_project_cache(
    root: Path | str | None = None,
    relative_db_path: Path | str = PROJECT_CACHE_RELPATH,
    enable_cleanup: bool = False,
) -> Path:
    """Point the translation cache at ``<root>/examples/cache/cache.v1.db``.

    ``enable_cleanup`` defaults to False so that no cached translation is ever
    evicted; the only supported value for magazine runs is False, True exists
    to restore upstream eviction in ad-hoc tooling. Returns the database path.
    """
    root = project_root() if root is None else Path(root)
    db_path = root / relative_db_path
    init_db(db_path=db_path, enable_cleanup=enable_cleanup)
    logger.debug("translation cache redirected to %s", db_path)
    return db_path
