"""Gate: every pass the configuration declares a switch for has a decided value.

A magazine pass names its own switch in its own configuration file and reads
the run attribute of that name, defaulting to off when the attribute is absent.
The fixed pipeline decides that attribute for every pass it runs, by listing it
as fixed-true or fixed-false. Nothing until now checked that the two sets
agreed.

They did not. ``magazine_short_unit`` was declared in ``short_unit.json``,
wired into the chain pass, covered by nine test files -- and named in neither
fixed list, so ``getattr(config, "magazine_short_unit", False)`` was False in
every run the pipeline had ever made and the pass had never once executed
outside its own unit tests. Nothing failed. The only trace was a report that
did not mention it, which is indistinguishable from a report of a pass that ran
and found nothing to do.

That is the failure this gate exists to make loud, because it is silent by
construction: a module can be written, configured, tested and merged, and still
never run, and no assertion anywhere would notice. So the check is not "is
short_unit on" -- that is one instance and it would pass forever after being
fixed once. The check is that the two sets agree, run at startup, on whatever
the configuration directory holds at the time.

Five claims:

S1  On the shipped tree, every declared switch is decided.
S2  A switch dropped from the fixed lists is caught, and the failure names the
    switch and the file that declares it. This is the regression the gate is
    for: it reproduces the defect and shows the assertion catching it.
S3  A configuration file declaring an unknown switch is caught the same way.
    A new pass is added by writing its configuration, so the check has to fail
    on arrival rather than on the first report someone reads closely.
S4  The switch the batch turned on is on after ``configure``, read through the
    pass's own accessor rather than through the attribute name spelled twice.
S5  The check is over the shipped configuration directory, not a list copied
    into the code: a switch added to a config file is seen without editing this
    gate or the pipeline's scanner.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import minimal_pipeline  # noqa: E402
from babeldoc.magazine import resource_paths  # noqa: E402
from babeldoc.magazine import short_unit  # noqa: E402

# The switch this batch wired up, and the file that declares it.  Named here
# only so S2 has something real to remove; the checks themselves read the
# configuration directory.
WIRED_SWITCH = "magazine_short_unit"
WIRED_SOURCE = "short_unit.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FixedLists:
    """Swap the pipeline's fixed lists for the body of one check."""

    def __init__(self, *, true_names=None, false_names=None):
        self.true_names = true_names
        self.false_names = false_names

    def __enter__(self):
        self._saved = (
            minimal_pipeline._FIXED_TRUE_ATTRIBUTES,
            minimal_pipeline._FIXED_FALSE_ATTRIBUTES,
        )
        if self.true_names is not None:
            minimal_pipeline._FIXED_TRUE_ATTRIBUTES = tuple(self.true_names)
        if self.false_names is not None:
            minimal_pipeline._FIXED_FALSE_ATTRIBUTES = tuple(self.false_names)
        return self

    def __exit__(self, *_exc):
        (
            minimal_pipeline._FIXED_TRUE_ATTRIBUTES,
            minimal_pipeline._FIXED_FALSE_ATTRIBUTES,
        ) = self._saved
        return False


class _ConfigDir:
    """Point the resource resolver at a copy of the shipped configuration."""

    def __init__(self, tmp: Path, extra: dict | None = None, name: str = "extra.json"):
        self.tmp = tmp
        self.extra = extra
        self.name = name

    def __enter__(self):
        target = self.tmp / "configs"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(resource_paths.resource_dir("configs"), target)
        if self.extra is not None:
            (target / self.name).write_text(
                json.dumps(self.extra, ensure_ascii=False), encoding="utf-8"
            )
        self._saved = resource_paths.resource_dir
        resource_paths.resource_dir = lambda kind: (
            target if kind == "configs" else self._saved(kind)
        )
        return target

    def __exit__(self, *_exc):
        resource_paths.resource_dir = self._saved
        return False


def _fresh_config():
    return SimpleNamespace()


def s1_shipped_tree_decides_every_switch() -> str:
    declared = minimal_pipeline.declared_switches()
    _require(bool(declared), "no configuration declares a switch at all")
    minimal_pipeline._assert_every_switch_is_decided()
    minimal_pipeline.configure(_fresh_config())
    return f"all {len(declared)} declared switches are decided"


def s2_a_dropped_switch_is_caught() -> str:
    kept = tuple(
        name
        for name in minimal_pipeline._FIXED_TRUE_ATTRIBUTES
        if name != WIRED_SWITCH
    )
    _require(
        len(kept) == len(minimal_pipeline._FIXED_TRUE_ATTRIBUTES) - 1,
        f"{WIRED_SWITCH} is not in the fixed-true list to begin with",
    )
    with _FixedLists(true_names=kept):
        try:
            minimal_pipeline.configure(_fresh_config())
        except minimal_pipeline.MinimalPipelineStateError as error:
            message = str(error)
        else:
            raise AssertionError("a dangling switch did not fail the run")
    _require(WIRED_SWITCH in message, f"the failure does not name the switch: {message}")
    _require(WIRED_SOURCE in message, f"the failure does not name the file: {message}")
    return "a switch dropped from the fixed lists fails the run by name"


def s3_an_unknown_switch_is_caught(tmp: Path) -> str:
    with _ConfigDir(tmp, extra={"switch": "magazine_not_wired_up"}):
        try:
            minimal_pipeline.configure(_fresh_config())
        except minimal_pipeline.MinimalPipelineStateError as error:
            message = str(error)
        else:
            raise AssertionError("an unknown declared switch did not fail the run")
    _require(
        "magazine_not_wired_up" in message and "extra.json" in message,
        f"the failure does not name the new switch and its file: {message}",
    )
    return "a configuration declaring an undecided switch fails the run by name"


def s4_the_wired_switch_is_on() -> str:
    config = _fresh_config()
    minimal_pipeline.configure(config)
    _require(
        short_unit.enabled(config),
        "the short-unit exemption is still off after configure",
    )
    return "short_unit.enabled is true for a configured run"


def s5_the_scan_reads_the_shipped_directory(tmp: Path) -> str:
    baseline = set(minimal_pipeline.declared_switches())
    _require(
        WIRED_SWITCH in baseline,
        f"{WIRED_SWITCH} is not read out of the configuration directory",
    )
    with _ConfigDir(tmp, extra={"switch": "magazine_seen_without_editing_the_gate"}):
        widened = minimal_pipeline.declared_switches()
    _require(
        widened.get("magazine_seen_without_editing_the_gate") == "extra.json",
        f"a switch added to the directory was not seen: {sorted(widened)}",
    )
    _require(
        set(minimal_pipeline.declared_switches()) == baseline,
        "the scan did not go back to the shipped directory",
    )
    return "the scan is over the configuration directory, not a list in the code"


SYMBOL_CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("S1", s1_shipped_tree_decides_every_switch),
    ("S2", s2_a_dropped_switch_is_caught),
    ("S4", s4_the_wired_switch_is_on),
)

RUN_CHECKS: tuple[tuple[str, Callable[[Path], str]], ...] = (
    ("S3", s3_an_unknown_switch_is_caught),
    ("S5", s5_the_scan_reads_the_shipped_directory),
)


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        checks: list[tuple[str, Callable[[], str]]] = [
            *SYMBOL_CHECKS,
            *((name, (lambda f=check: f(tmp))) for name, check in RUN_CHECKS),
        ]
        for name, check in sorted(checks):
            try:
                detail = check()
            except Exception as error:  # noqa: BLE001 - the gate reports, never raises
                failures += 1
                print(f"{name} FAIL  {type(error).__name__}: {error}")
            else:
                print(f"{name} ok    {detail}")
    total = len(SYMBOL_CHECKS) + len(RUN_CHECKS)
    print(f"\n{total - failures}/{total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
