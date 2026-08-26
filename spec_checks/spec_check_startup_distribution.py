"""Build and exercise the installed wheel from outside the repository."""

from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
import time
from pathlib import Path

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = "c16-distribution-test-key"
RESULTS: list[tuple[str, bool, str]] = []
OUTPUTS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}{': ' + detail if detail else ''}")


def run(
    arguments: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603 - argv is assembled from fixed local paths
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    OUTPUTS.extend((result.stdout, result.stderr))
    return result


def installed_executables(venv: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe", venv / "Scripts" / "babeldoc.exe"
    return venv / "bin" / "python", venv / "bin" / "babeldoc"


def main() -> int:
    started = time.perf_counter()
    uv = shutil.which("uv")
    check("01 uv executable is available", uv is not None)
    if uv is None:
        return 1

    environment = os.environ.copy()
    environment["OPENAI_API_KEY"] = TEST_KEY
    environment["PYTHONPATH"] = os.pathsep.join(site.getsitepackages())
    with tempfile.TemporaryDirectory(prefix="babeldoc-c16-distribution-") as temporary:
        temp = Path(temporary)
        wheels = temp / "wheels"
        outside = temp / "outside"
        venv = temp / "venv"
        wheels.mkdir()
        outside.mkdir()

        built = run(
            [
                uv,
                "build",
                "--wheel",
                "--no-build-isolation",
                "--out-dir",
                str(wheels),
                str(ROOT),
            ],
            cwd=ROOT,
            environment=environment,
        )
        wheel_files = sorted(wheels.glob("*.whl"))
        check(
            "02 wheel builds into the temporary directory",
            built.returncode == 0 and len(wheel_files) == 1,
            (built.stdout + built.stderr)[-300:],
        )
        if len(wheel_files) != 1:
            return 1

        created = run(
            [uv, "venv", str(venv), "--python", sys.executable],
            cwd=outside,
            environment=environment,
        )
        python, cli = installed_executables(venv)
        installed = run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                "--link-mode",
                "copy",
                str(wheel_files[0]),
            ],
            cwd=outside,
            environment=environment,
        )
        check(
            "03 wheel installs into an isolated virtual environment",
            created.returncode == 0
            and installed.returncode == 0
            and python.is_file()
            and cli.is_file(),
            (created.stdout + created.stderr + installed.stdout + installed.stderr)[
                -300:
            ],
        )
        if installed.returncode != 0 or not cli.is_file():
            return 1

        help_result = run([str(cli), "--help"], cwd=outside, environment=environment)
        conservative = run(
            [str(cli), "--magazine-mode", "conservative", "--validate-config"],
            cwd=outside,
            environment=environment,
        )
        automatic = run(
            [
                str(cli),
                "--magazine-mode",
                "automatic",
                "--print-effective-config",
            ],
            cwd=outside,
            environment=environment,
        )
        effective = json.loads(automatic.stdout) if automatic.returncode == 0 else {}
        check(
            "04 installed entry point starts from outside the repository",
            help_result.returncode == 0
            and "--magazine-mode" in help_result.stdout
            and conservative.returncode == 0
            and "Configuration valid." in conservative.stdout
            and automatic.returncode == 0
            and effective.get("mode") == "automatic"
            and effective.get("validation") == {"errors": [], "ok": True},
            (help_result.stderr + conservative.stderr + automatic.stderr)[-300:],
        )

        resource_code = """
import json
import sys
from pathlib import Path
import babeldoc
from babeldoc.magazine.resource_paths import config_path, prompt_path, resource_availability
from babeldoc.magazine.taxonomy import record_config_manifest

root = Path(sys.argv[1])
config = config_path("magazine_runtime_profile.automatic.v1.json")
prompt = prompt_path("article_brief.md")
manifest_path = record_config_manifest(root, [config])
print(json.dumps({
    "availability": resource_availability(),
    "config": str(config),
    "config_readable": bool(config.read_text(encoding="utf-8")),
    "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
    "package": str(Path(babeldoc.__file__).resolve()),
    "prompt": str(prompt),
    "prompt_readable": bool(prompt.read_text(encoding="utf-8")),
}, sort_keys=True))
"""
        resources = run(
            [str(python), "-c", resource_code, str(outside)],
            cwd=outside,
            environment=environment,
        )
        resource_report = (
            json.loads(resources.stdout) if resources.returncode == 0 else {}
        )
        availability = resource_report.get("availability", {})
        manifest = resource_report.get("manifest", {})
        check(
            "05 wheel resources are readable and use logical manifest names",
            resources.returncode == 0
            and availability.get("configs", {}).get("available") is True
            and availability.get("prompts", {}).get("available") is True
            and resource_report.get("config_readable") is True
            and resource_report.get("prompt_readable") is True
            and str(venv.resolve()) in resource_report.get("package", "")
            and "_resources" in resource_report.get("config", "")
            and "_resources" in resource_report.get("prompt", "")
            and list(manifest) == ["configs/magazine_runtime_profile.automatic.v1.json"]
            and len(next(iter(manifest.values()), "")) == 64,
            resources.stderr[-300:],
        )

    combined = "".join(OUTPUTS)
    check(
        "06 installed startup output never reveals the environment key",
        TEST_KEY not in combined,
    )
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(
        "spec_check_startup_distribution: "
        f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed "
        f"in {time.perf_counter() - started:.3f}s"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
