"""Offline contract checks for strict single-request continuity chains."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "pymupdf" not in sys.modules:
    pymupdf_stub = types.ModuleType("pymupdf")
    pymupdf_stub.Font = object
    sys.modules["pymupdf"] = pymupdf_stub
if "babeldoc.translator.cache" not in sys.modules:
    cache_stub = types.ModuleType("babeldoc.translator.cache")
    cache_stub.TranslationCache = object
    sys.modules["babeldoc.translator.cache"] = cache_stub

from babeldoc.magazine import chain_translation  # noqa: E402
from babeldoc.magazine.article_context import EMPTY_CONTEXT  # noqa: E402
from babeldoc.magazine.run_trace import ChainResultState  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402

CHECKS = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"PASS: {name}")
        return
    FAILURES.append(f"{name}: {detail}")
    print(f"FAIL: {name} :: {detail}")


class Placeholder:
    def __init__(self, token: str) -> None:
        self.placeholder = token
        self.regex_pattern = re.escape(token)


class TranslateInput:
    def __init__(self, placeholders=()) -> None:
        self.placeholders = list(placeholders)
        self.original_placeholder_tokens = {}

    def get_placeholders_hint(self):
        return None


class LLMTracker:
    def set_input(self, _value) -> None:
        pass

    def set_output(self, _value) -> None:
        pass


class ParagraphTracker:
    def new_llm_translate_tracker(self) -> LLMTracker:
        return LLMTracker()


class Tracker:
    def new_cross_page(self):
        return self

    def new_paragraph(self) -> ParagraphTracker:
        return ParagraphTracker()


class StubEngine:
    def __init__(self, target: str, error: Exception | None = None) -> None:
        self.target = target
        self.error = error
        self.llm_calls = 0
        self.member_calls = 0

    def llm_translate(self, _prompt, rate_limit_params=None) -> str:
        self.llm_calls += 1
        if self.error is not None:
            raise self.error
        return json.dumps([{"id": 0, "output": self.target}], ensure_ascii=False)

    def translate(self, _source: str) -> str:
        self.member_calls += 1
        return "forbidden member translation"


class StubILTranslator:
    def __init__(self, prepared: dict[int, TranslateInput]) -> None:
        self.prepared = prepared
        self.posted: list[int] = []

    def pre_translate_paragraph(
        self, paragraph, _tracker, _page_font_map, _xobj_font_map
    ):
        return paragraph.unicode, self.prepared.get(id(paragraph), TranslateInput())

    def post_translate_paragraph(
        self, paragraph, _tracker, _translate_input, translated_text
    ) -> None:
        paragraph.unicode = translated_text
        self.posted.append(id(paragraph))


class StubTranslator:
    def __init__(self, docs, work: Path, target: str, *, align=False, error=None):
        self.translation_config = SimpleNamespace(
            lang_out="zh",
            magazine_chain_cut_align=align,
            magazine_short_unit=False,
            add_formula_placehold_hint=False,
            shared_context_cross_split_part=SimpleNamespace(
                first_paragraph=None,
                recent_title_paragraph=None,
            ),
            get_working_file_path=lambda name: work / name,
        )
        self.translate_engine = StubEngine(target, error)
        self.il_translator = StubILTranslator({})
        self.run_trace = RunTrace.from_document(docs)
        self.total_count = 0
        self.ok_count = 0

    def _build_font_maps(self, _page):
        return {}, {}

    def calc_token_count(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _build_llm_prompt(self, *, json_input_str: str, **_kwargs) -> str:
        return json_input_str

    def _trace_prompt_config(self, prompt: str) -> dict:
        return {"prompt": prompt}

    def _clean_json_output(self, output: str) -> str:
        return output


def paragraph(text: str, chain_id: str | None, chain_index: int | None):
    return SimpleNamespace(
        unicode=text,
        chain_id=chain_id,
        chain_index=chain_index,
        debug_id=f"debug-{chain_id}-{chain_index}",
        layout_label="title",
        box=None,
        pdf_style=None,
        pdf_paragraph_composition=[],
    )


def fixture(member_count: int, *, ordinary=False):
    members = [
        paragraph(f"source member {index} continues", "raw-chain", index)
        for index in range(member_count)
    ]
    pages = []
    for index, member in enumerate(members):
        rows = [member]
        if index == 0 and ordinary:
            rows.append(paragraph("ordinary paragraph", None, None))
        pages.append(SimpleNamespace(pdf_paragraph=rows))
    docs = SimpleNamespace(page=pages)
    refs = tuple(f"p{index + 1}#0" for index in range(member_count))
    canonical_chain = f"chain-canonical-{member_count}"
    article_ir = SimpleNamespace(
        by_page={index + 1: "article-a" for index in range(member_count)},
        by_element=dict.fromkeys(refs, "article-a"),
        by_chain_member=dict.fromkeys(refs, canonical_chain),
        by_chain={canonical_chain: "article-a"},
    )
    return docs, members, refs, article_ir


def run_plan(
    member_count: int,
    *,
    align=False,
    target: str | None = None,
    error: Exception | None = None,
    ordinary=False,
    mutate=None,
):
    docs, members, refs, article_ir = fixture(member_count, ordinary=ordinary)
    if mutate is not None:
        mutate(docs, members, refs, article_ir)
    work = Path(tempfile.mkdtemp(prefix="babeldoc-c05-"))
    translated = target or ("联合译文" * (member_count * 8))
    translator = StubTranslator(docs, work, translated, align=align, error=error)
    plan = chain_translation.plan_chain_translation(
        translator,
        docs,
        Tracker(),
        EMPTY_CONTEXT,
        article_ir,
    )
    return plan, translator, docs, members, refs


def check_success_counts() -> None:
    for count in (2, 3, 5):
        plan, translator, _docs, members, refs = run_plan(count)
        outcome = plan.outcomes[0]
        trace_outcome = next(iter(translator.run_trace.chain_outcomes.values()))
        check(
            f"{count} members make one joint call",
            translator.translate_engine.llm_calls == 1
            and translator.translate_engine.member_calls == 0
            and outcome["translator_call_count"] == 1
            and outcome["ordered_source_refs"] == list(refs)
            and outcome["result_state"] == ChainResultState.JOINT_SUCCESS.value
            and trace_outcome.translator_call_count == 1,
            str(outcome),
        )
        plan.apply()
        check(
            f"{count} successful members apply once and release atomically",
            len(translator.il_translator.posted) == count
            and not plan.claim
            and all(
                item.unicode != f"source member {i} continues"
                for i, item in enumerate(members)
            ),
        )


def check_alignment_is_deterministic() -> None:
    plan, translator, _docs, _members, _refs = run_plan(3, align=True)
    check(
        "alignment switch creates no member request",
        plan.align_enabled
        and translator.translate_engine.llm_calls == 1
        and translator.translate_engine.member_calls == 0
        and plan.as_record()["counts"]["alignment_requests"] == 0,
    )


def check_article_preflight() -> None:
    def mismatch(_docs, _members, refs, article_ir) -> None:
        article_ir.by_element[refs[-1]] = "article-b"

    plan, translator, _docs, members, _refs = run_plan(3, mutate=mismatch)
    outcome = plan.outcomes[0]
    check(
        "article mismatch stops before the engine and records an issue",
        translator.translate_engine.llm_calls == 0
        and outcome["reason"] == chain_translation.ESCALATION_ARTICLE
        and outcome["result_state"]
        == ChainResultState.PROTECTED_UNTRANSLATED.value
        and all(plan.claim.claims_paragraph(member) for member in members),
        str(outcome),
    )


def check_topology_preflight() -> None:
    def branch(_docs, members, _refs, _article_ir) -> None:
        members[-1].chain_index = members[-2].chain_index

    plan, translator, _docs, members, _refs = run_plan(3, mutate=branch)
    check(
        "branching chain stops before the engine and remains claimed",
        translator.translate_engine.llm_calls == 0
        and plan.outcomes[0]["reason"] == chain_translation.ESCALATION_TOPOLOGY
        and all(plan.claim.claims_paragraph(member) for member in members),
    )


def check_placeholder_failures() -> None:
    docs, members, _refs, article_ir = fixture(2)
    work = Path(tempfile.mkdtemp(prefix="babeldoc-c05-preflight-"))
    translator = StubTranslator(docs, work, "unused")
    translator.il_translator.prepared[id(members[0])] = TranslateInput([object()])
    plan = chain_translation.plan_chain_translation(
        translator, docs, Tracker(), EMPTY_CONTEXT, article_ir
    )
    check(
        "placeholder preflight failure makes zero calls",
        translator.translate_engine.llm_calls == 0
        and plan.outcomes[0]["reason"] == chain_translation.ESCALATION_PLACEHOLDER
        and plan.outcomes[0]["translator_call_count"] == 0,
        str(plan.outcomes[0]),
    )

    docs, members, refs, article_ir = fixture(2)
    members[0].unicode = "[[0]] source member zero"
    work = Path(tempfile.mkdtemp(prefix="babeldoc-c05-placeholder-"))
    translator = StubTranslator(docs, work, "损坏占位符的联合译文" * 5)
    translator.il_translator.prepared[id(members[0])] = TranslateInput(
        [Placeholder("[[0]]")]
    )
    plan = chain_translation.plan_chain_translation(
        translator, docs, Tracker(), EMPTY_CONTEXT, article_ir
    )
    outcome = plan.outcomes[0]
    check(
        "damaged response placeholder makes at most one call and fails explicitly",
        translator.translate_engine.llm_calls == 1
        and outcome["translator_call_count"] == 1
        and outcome["reason"] == chain_translation.ESCALATION_PLACEHOLDER
        and outcome["result_state"] == ChainResultState.FAILED_WITH_ISSUE.value
        and all(plan.claim.claims_paragraph(member) for member in members),
        str(outcome),
    )


def check_engine_exception_is_contained() -> None:
    plan, translator, _docs, members, _refs = run_plan(
        3, error=RuntimeError("injected engine failure")
    )
    outcome = plan.outcomes[0]
    check(
        "engine exception cannot release members to legacy paths",
        translator.translate_engine.llm_calls == 1
        and translator.translate_engine.member_calls == 0
        and outcome["result_state"] == ChainResultState.FAILED_WITH_ISSUE.value
        and outcome["translator_call_count"] == 1
        and all(plan.claim.claims_paragraph(member) for member in members),
        str(outcome),
    )


def check_ordinary_paragraph_is_untouched() -> None:
    plan, translator, docs, _members, _refs = run_plan(2, ordinary=True)
    ordinary = docs.page[0].pdf_paragraph[1]
    source = (
        ROOT
        / "babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py"
    ).read_text(encoding="utf-8")
    check(
        "ordinary paragraph remains available to the unchanged page path",
        not plan.claim.claims_paragraph(ordinary)
        and ordinary.unicode == "ordinary paragraph"
        and translator.translate_engine.llm_calls == 1
        and all(
            guard in source
            for guard in (
                "chain_claim.declines_cross_page",
                "chain_claim.declines_cross_column",
                "chain_claim.claims_paragraph",
            )
        ),
    )


def check_source_contract() -> None:
    source = (ROOT / "babeldoc/magazine/chain_translation.py").read_text(
        encoding="utf-8"
    )
    check(
        "chain alignment contains no translation call",
        "def _aligned_lengths" not in source
        and "translate_engine.translate(" not in source
        and "aligned_lengths=None" in source,
    )


def main() -> int:
    check_success_counts()
    check_alignment_is_deterministic()
    check_article_preflight()
    check_topology_preflight()
    check_placeholder_failures()
    check_engine_exception_is_contained()
    check_ordinary_paragraph_is_untouched()
    check_source_contract()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} chain checks")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(f"PASS: {CHECKS} chain single-request checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
