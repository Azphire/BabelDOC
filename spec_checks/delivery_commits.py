"""Immutable delivery commits used by historical scope checks."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

DELIVERY_COMMITS: Mapping[str, str] = MappingProxyType(
    {
        "C01": "39e7c68",
        "C02": "9aa7a53",
        "C03": "05ef7ca",
        "C04": "5c6fff5",
        "C05": "b08a948",
        "C06": "51d30bc",
        "C07": "4130f98",
        "C08": "9884e26",
        "C09": "c32161b",
        "C10": "7d04a09",
        "C11": "a63e8f1",
        "C12": "4923446",
        "C13": "5e75fa8",
        "C14": "a318011",
        "C15": "cda5ccc",
    }
)


class DeliveryCommitError(RuntimeError):
    """Raised when frozen delivery evidence is absent or unreadable."""


def _git() -> str:
    executable = shutil.which("git")
    if executable is None:
        raise DeliveryCommitError("git executable not found")
    return executable


def resolve_delivery_commit(batch: str, root: Path) -> str:
    """Resolve one frozen delivery SHA to a full commit, failing if absent."""
    try:
        short_sha = DELIVERY_COMMITS[batch]
    except KeyError as exc:
        raise DeliveryCommitError(f"unknown delivery batch {batch!r}") from exc
    result = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
        [_git(), "rev-parse", "--verify", f"{short_sha}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    resolved = result.stdout.strip()
    if result.returncode != 0 or not resolved:
        raise DeliveryCommitError(
            f"{batch} delivery commit {short_sha} is unavailable"
        )
    return resolved


def delivery_files(batch: str, root: Path) -> set[str]:
    """Return the files recorded by one delivery commit via ``diff-tree``."""
    commit = resolve_delivery_commit(batch, root)
    result = subprocess.run(  # noqa: S603 - fixed Git argv reads repository history
        [
            _git(),
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            commit,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DeliveryCommitError(f"unable to read {batch} delivery commit {commit}")
    return {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }
