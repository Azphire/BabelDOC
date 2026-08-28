from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = (ROOT / ".runtime").resolve()

CONST_PROBE = """
import json
import os

from babeldoc import const

print(json.dumps({
    "cache": str(const.CACHE_FOLDER),
    "tiktoken": str(const.TIKTOKEN_CACHE_FOLDER),
    "tiktoken_env": os.environ["TIKTOKEN_CACHE_DIR"],
    "tiktoken_exists": const.TIKTOKEN_CACHE_FOLDER.is_dir(),
}))
"""


def _probe_const(environment: dict[str, str]) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", CONST_PROBE],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _assert_beneath(path: str | Path, parent: Path) -> Path:
    normalized = Path(path).resolve()
    assert normalized.is_relative_to(parent.resolve())
    return normalized


def test_babeldoc_cache_override_controls_import_time_paths() -> None:
    with tempfile.TemporaryDirectory(
        prefix="m0-cache-override-",
        dir=RUNTIME_ROOT / "temp",
    ) as temp_dir:
        cache_root = (Path(temp_dir) / "override-cache").resolve()
        environment = os.environ.copy()
        environment["BABELDOC_CACHE_DIR"] = str(cache_root)

        record = _probe_const(environment)

        assert Path(str(record["cache"])).resolve() == cache_root
        assert Path(str(record["tiktoken"])).resolve() == cache_root / "tiktoken"
        assert Path(str(record["tiktoken_env"])).resolve() == (
            cache_root / "tiktoken"
        )
        assert record["tiktoken_exists"] is True
        _assert_beneath(cache_root, RUNTIME_ROOT)


def test_unset_cache_override_uses_controlled_home() -> None:
    with tempfile.TemporaryDirectory(
        prefix="m0-cache-fallback-",
        dir=RUNTIME_ROOT / "temp",
    ) as temp_dir:
        controlled_home = (Path(temp_dir) / "controlled-home").resolve()
        controlled_home.mkdir()
        environment = os.environ.copy()
        environment.pop("BABELDOC_CACHE_DIR", None)
        environment["USERPROFILE"] = str(controlled_home)
        environment["HOME"] = str(controlled_home)

        record = _probe_const(environment)
        expected_cache = controlled_home / ".cache" / "babeldoc"

        assert Path(str(record["cache"])).resolve() == expected_cache
        assert Path(str(record["tiktoken"])).resolve() == expected_cache / "tiktoken"
        assert Path(str(record["tiktoken_env"])).resolve() == (
            expected_cache / "tiktoken"
        )
        assert record["tiktoken_exists"] is True
        _assert_beneath(expected_cache, RUNTIME_ROOT)


def test_runtime_initializer_sets_and_creates_isolated_paths() -> None:
    powershell = shutil.which("powershell.exe")
    assert powershell is not None
    command = """
. ".\\tools\\Initialize-MigrationRuntime.ps1"
[ordered]@{
    UV_CACHE_DIR = $env:UV_CACHE_DIR
    BABELDOC_CACHE_DIR = $env:BABELDOC_CACHE_DIR
    TEMP = $env:TEMP
    TMP = $env:TMP
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(  # noqa: S603
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    record = json.loads(result.stdout)

    for name in ("UV_CACHE_DIR", "BABELDOC_CACHE_DIR", "TEMP", "TMP"):
        runtime_path = _assert_beneath(record[name], RUNTIME_ROOT)
        assert runtime_path.is_dir()
    assert Path(record["TEMP"]).resolve() == Path(record["TMP"]).resolve()
