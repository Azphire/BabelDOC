"""Run the detectors over the frozen translated fixture and record what they say.

The corpus census is built from dry runs, which translate nothing, so the two
detectors that answer about a translated document are skipped there. This is
where they answer: one really translated document, frozen from the batch b7.5
second pass, detected offline and written out as evidence.

Usage:
    python detect_fixture.py
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import detectors  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b8"
FIXTURE = OUT_DIR / "Courier-en.typeset.fixture.xml"
EVIDENCE_NAME = "fixture_detection.json"

# The target language the frozen pass was finished into.
LANGUAGE = "zh"


def main() -> int:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs = checkpoint_module.load_checkpoint(FIXTURE)
    config = detectors.detector_config()
    context = detectors.build_context(docs, config, LANGUAGE, None)
    issues = detectors.run_detectors(context)
    record = detectors.as_record(context, issues)
    with (OUT_DIR / EVIDENCE_NAME).open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print(f"{record['counts']['issues']} issue(s): {record['counts']['by_kind']}")
    for issue in record["issues"]:
        evidence = issue["evidence"]
        print(
            f"  {issue['kind']:<22} {','.join(issue['paragraph_refs']):<40} "
            f"{evidence.get('layout_label') or evidence.get('layout_labels')} "
            f"ratio={evidence.get('residue_ratio')} "
            f"chars={evidence.get('residue_chars')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
