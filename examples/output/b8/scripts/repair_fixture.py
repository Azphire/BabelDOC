"""Drive the repair loop over the frozen orphan fixture with a stub engine.

No credential and no request: the engine below decides and renders offline, so
what this measures is the loop -- which findings the action admits, what the
write-back leaves in the intermediate language, and what the recheck then finds
-- over paragraphs a real translated run really produced.

Usage:
    python repair_fixture.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine.detectors import base  # noqa: E402
from babeldoc.magazine.react import actions  # noqa: E402
from babeldoc.magazine.react import controller  # noqa: E402
from babeldoc.magazine.react.decide import CachedDecisionClient  # noqa: E402
from babeldoc.magazine.react.decide import EngineTransport  # noqa: E402

OUT_DIR = ROOT / "examples" / "output" / "b8"
FIXTURE = OUT_DIR / "Courier-en.orphans.fixture.xml"
EVIDENCE_NAME = "fixture_repair.json"

LANGUAGE = "zh"

# What the stub renders every orphan as. One string, so the evidence is about
# which paragraphs were rewritten rather than about a model's wording.
RENDERED = "为联合国教科文组织《信使》拍摄"


class _LayoutModel:
    stage_name = "stub"

    def predict(self, *args, **kwargs):
        return []


class StubEngine:
    """Decides every offered finding, renders every line, spends nothing."""

    name = "stub"

    def __init__(self):
        self.requests: list[str] = []

    def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
        self.requests.append(text)
        if "Actions available" in text:
            ids = [
                line.split('"')[1]
                for line in text.splitlines()
                if line.strip().startswith("- id:")
            ]
            return json.dumps(
                {
                    "action": actions.NAME,
                    "issue_ids": ids,
                    "parameters": {actions.MAX_PARAGRAPHS: 8},
                    "reason": "orphan lines are still in the source script",
                }
            )
        return json.dumps({actions.TRANSLATION_FIELD: RENDERED})


class NoCache:
    """The evidence is about the loop, not about a database."""

    def get(self, key):
        return None

    def set(self, key, value):
        return None


def main() -> int:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        docs = checkpoint_module.load_checkpoint(FIXTURE)

    work = Path(tempfile.mkdtemp(prefix="b8_repair_fixture_"))
    engine = StubEngine()
    config = TranslationConfig(
        translator=engine,
        input_file=str(ROOT / "examples" / "input" / "Courier-en.pdf"),
        lang_in="en",
        lang_out=LANGUAGE,
        doc_layout_model=_LayoutModel(),
        working_dir=work,
        output_dir=work / "out",
        progress_monitor=None,
        auto_extract_glossary=False,
    )
    config.magazine_detect = True
    config.magazine_repair = True

    loop = controller.RepairLoop(config, docs)
    loop.decision_client = CachedDecisionClient(
        loop.repair_config,
        transport=EngineTransport(engine),
        cache=NoCache(),
        working_dir=loop.working_dir,
    )
    loop.translator = actions.CachedOrphanTranslator(
        loop.repair_config,
        transport=EngineTransport(engine),
        cache=NoCache(),
        language=LANGUAGE,
        glossaries=[],
        working_dir=loop.working_dir,
    )
    loop.run()

    report = json.loads(
        (loop.working_dir / controller.REPORT_NAME).read_text(encoding="utf-8")
    )
    report["rendered_after"] = {
        reference: base.rendered_text(paragraph)
        for reference, paragraph in _by_reference(docs).items()
        if reference in report["conservation"]["touched_refs"]
    }
    report["requests_made"] = len(engine.requests)
    with (OUT_DIR / EVIDENCE_NAME).open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print(f"stopped: {report['stopped_because']}")
    print(
        f"iterations: {report['iterations_run']}  applications: "
        f"{report['applications']}  requests: {report['requests_made']}"
    )
    print(f"conservation: {report['conservation']['verdict']}")
    for iteration in report["iterations"]:
        print(
            f"  iteration {iteration['iteration']}: {iteration['outcome']}  "
            f"found {iteration['detected']['total']}  "
            f"recheck {(iteration.get('recheck') or {}).get('total')}"
        )
        for item in iteration.get("executed") or ():
            print(f"    wrote    {item['paragraph_ref']:<8} {item['reason']}")
        for item in iteration.get("applicability") or ():
            print(f"    rejected {item['paragraph_ref']:<8} {item['reason']}")
    return 0


def _by_reference(docs) -> dict:
    from babeldoc.magazine.drop_cap import paragraph_reference
    from babeldoc.magazine.hitl import labeled_pages

    return {
        paragraph_reference(label, index): paragraph
        for label, page in labeled_pages(docs)
        for index, paragraph in enumerate(page.pdf_paragraph or ())
    }


if __name__ == "__main__":
    sys.exit(main())
