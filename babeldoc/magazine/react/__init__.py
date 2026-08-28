"""ReAct repair: act on what detection found, within declared bounds.

Detection reads a finished document and reports. This package is what is
allowed to change one, and everything about it is bounded by declaration: the
actions it may take and their parameters come from
``configs/repair_actions.json``, the prompts it sends come from ``prompts/``,
the findings it may act on are decided by a rule that is not the model's to
overrule, and what it wrote is checked against what it was allowed to write
before the document goes on to be rendered.

The switch is ``magazine_repair``, down by default, and the detection pass is
unchanged with it down.
"""

from __future__ import annotations

from babeldoc.magazine.react.config import CONFIG_PATH
from babeldoc.magazine.react.config import NO_ACTION
from babeldoc.magazine.react.config import RepairConfig
from babeldoc.magazine.react.config import RepairConfigError
from babeldoc.magazine.react.config import load_repair_config
from babeldoc.magazine.react.controller import REPORT_NAME
from babeldoc.magazine.react.controller import SWITCH
from babeldoc.magazine.react.controller import RepairLoop
from babeldoc.magazine.react.controller import enabled
from babeldoc.magazine.react.controller import paragraph_digests
from babeldoc.magazine.react.controller import repair_document

__all__ = [
    "CONFIG_PATH",
    "NO_ACTION",
    "REPORT_NAME",
    "SWITCH",
    "RepairConfig",
    "RepairConfigError",
    "RepairLoop",
    "enabled",
    "load_repair_config",
    "paragraph_digests",
    "repair_document",
]
