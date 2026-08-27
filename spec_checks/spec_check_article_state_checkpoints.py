"""C18 fast gate for immutable article state and shared legal slots."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import article_flow  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticlePolicyEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ArticleRegionSlot  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.article_state import (  # noqa: E402
    ARTICLE_CONTEXT_RECORD_SCHEMA_VERSION,
)
from babeldoc.magazine.article_state import (  # noqa: E402
    ARTICLE_KNOWLEDGE_STATE_SCHEMA_VERSION,
)
from babeldoc.magazine.article_state import ArticleStateJournal  # noqa: E402
from babeldoc.magazine.article_state import ArticleStateStage  # noqa: E402
from babeldoc.magazine.article_state import ArticleStateStatus  # noqa: E402
from babeldoc.magazine.element_roles import ElementRole  # noqa: E402
from babeldoc.magazine.fixed_assets import AssetRecord  # noqa: E402
from babeldoc.magazine.fixed_assets import FixedAssetInventory  # noqa: E402
from babeldoc.magazine.legal_slots import LEGAL_SLOT_SCHEMA_VERSION  # noqa: E402
from babeldoc.magazine.legal_slots import plan_legal_slots  # noqa: E402
from babeldoc.magazine.page_identity import PageSelectionMap  # noqa: E402
from babeldoc.magazine.run_trace import RunTrace  # noqa: E402
from babeldoc.magazine.run_trace import hash_record  # noqa: E402

GATE_SET = "fast"


class Config:
    def __init__(self, root: Path, *, skip_translation: bool = False):
        self.root = root
        self.working_dir = root
        self.lang_in = "en"
        self.lang_out = "zh"
        self.magazine_article_context = True
        self.magazine_column_reflow = True
        self.skip_translation = skip_translation
        self.magazine_hitl_decisions = None
        self.shared_context_cross_split_part = SimpleNamespace(
            user_glossaries=[
                SimpleNamespace(
                    name="manual",
                    entries=[
                        SimpleNamespace(
                            source="Alpha",
                            target="阿尔法",
                            target_language=None,
                        ),
                        SimpleNamespace(
                            source="Beta",
                            target="贝塔",
                            target_language=None,
                        ),
                    ],
                )
            ]
        )

    def get_working_file_path(self, name: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        return str(self.root / name)


def _box(x: float, y: float, x2: float, y2: float):
    return il_version_1.Box(x=x, y=y, x2=x2, y2=y2)


def _document():
    frame = _box(0, 0, 100, 100)
    return il_version_1.Document(
        total_pages=2,
        page=[
            il_version_1.Page(
                page_number=0,
                mediabox=il_version_1.Mediabox(box=frame),
                cropbox=il_version_1.Cropbox(box=frame),
                pdf_paragraph=[
                    il_version_1.PdfParagraph(
                        debug_id="volatile-a",
                        unicode="Alpha article body",
                        layout_label="text",
                        box=_box(0, 0, 100, 100),
                    )
                ],
            ),
            il_version_1.Page(
                page_number=1,
                mediabox=il_version_1.Mediabox(box=frame),
                cropbox=il_version_1.Cropbox(box=frame),
                pdf_paragraph=[
                    il_version_1.PdfParagraph(
                        debug_id="volatile-b",
                        unicode="Beta article body",
                        layout_label="text",
                        box=_box(0, 0, 100, 100),
                    )
                ],
            ),
        ],
    )


def _article(
    article_id: str,
    page: int,
    order: int,
    source_ref: str,
    source_text: str,
):
    element = SourceElementRef(
        source_ref=source_ref,
        page=page,
        column=0,
        reading_order=order,
        role=ElementRole.BODY,
        source_box=(0.0, 0.0, 100.0, 100.0),
        source_text_hash=hashlib.sha256(source_text.encode()).hexdigest(),
        style_hash=hash_record(
            {"font_id": None, "font_size": None, "graphic_state": None}
        ),
        raw_layout_label="text",
    )
    return ArticleIR(
        article_id=article_id,
        pages=(page,),
        elements=(element,),
        slots=(
            ArticleRegionSlot(
                article_id=article_id,
                page=page,
                column=0,
                slot_order=order,
                box=(0.0, 0.0, 100.0, 100.0),
                fixed_obstacle_refs=(),
                capacity_hint=10000.0,
            ),
        ),
        chain_ids=(),
        policy_evidence=(
            ArticlePolicyEvidence(
                page=page,
                role="article_opener",
                page_kind="feature",
                reason="fixture",
                article_reflow_allowed=True,
            ),
        ),
    )


def _ir(docs):
    articles = (
        _article("article-a", 1, 0, "p1#0", "Alpha article body"),
        _article("article-b", 2, 1, "p2#0", "Beta article body"),
    )
    return ArticleDocumentIR(
        articles=articles,
        by_page={1: "article-a", 2: "article-b"},
        by_element={"p1#0": "article-a", "p2#0": "article-b"},
        by_chain={},
        page_selection_map=PageSelectionMap.from_document(docs),
    )


def _inventory():
    return FixedAssetInventory(
        assets=(
            AssetRecord(
                reference="p1:pdf_figure#0",
                asset_type="pdf_figure",
                page=1,
                bbox=(40.0, 40.0, 60.0, 60.0),
                digest="fixture-asset",
                movable=False,
                protected=True,
                figure_ref="p1:pdf_figure#0",
            ),
        ),
        page_sizes=(
            (1, (0.0, 0.0, 100.0, 100.0), (0.0, 0.0, 100.0, 100.0)),
            (2, (0.0, 0.0, 100.0, 100.0), (0.0, 0.0, 100.0, 100.0)),
        ),
    )


def _overlap(left, right) -> bool:
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def main() -> int:
    failures = []

    def check(name: str, condition: bool) -> None:
        print(f"{'PASS' if condition else 'FAIL'} {name}")
        if not condition:
            failures.append(name)

    docs = _document()
    article_ir = _ir(docs)
    inventory = _inventory()
    slots = plan_legal_slots(article_ir, inventory)
    slots_again = plan_legal_slots(article_ir, inventory)
    page_one = tuple(slot for slot in slots.slots if slot.page == 1)

    check(
        "knowledge, context and legal-slot schemas are versioned",
        ARTICLE_KNOWLEDGE_STATE_SCHEMA_VERSION == "article-knowledge-state.v1"
        and ARTICLE_CONTEXT_RECORD_SCHEMA_VERSION == "article-context-record.v1"
        and LEGAL_SLOT_SCHEMA_VERSION == "legal-slots.v1",
    )
    check(
        "fixed obstacle produces real two-dimensional fragments",
        len(page_one) == 4
        and all(not _overlap(slot.box, (40.0, 40.0, 60.0, 60.0)) for slot in page_one)
        and all(slot.page == 1 for slot in page_one),
    )
    check(
        "legal-slot identity and digest are deterministic",
        slots.digest == slots_again.digest
        and [item.slot_id for item in slots.slots]
        == [item.slot_id for item in slots_again.slots]
        and [item.slot_order for item in slots.slots]
        == list(range(len(slots.slots))),
    )
    capable_type = type("ILTranslatorLLMOnly", (), {})
    capable = capable_type()
    capable.translation_config = Config(Path("unused-capability-root"))
    trace_for_preflight = RunTrace.from_document(docs, article_ir)
    ready = article_flow.preflight_runtime(
        capable, article_ir, trace_for_preflight, inventory, slots
    )
    refused = False
    incapable = SimpleNamespace(translation_config=capable.translation_config)
    try:
        article_flow.preflight_runtime(
            incapable, article_ir, trace_for_preflight, inventory, slots
        )
    except article_flow.ArticleFlowCapabilityError:
        refused = True
    check(
        "article-flow capability preflight runs before target mutation",
        ready["status"] == "ready"
        and ready["legal_slots_sha256"] == slots.digest
        and refused,
    )

    with tempfile.TemporaryDirectory(prefix="c18-state-") as temp:
        root = Path(temp)
        trace = RunTrace.from_document(docs, article_ir)
        journal = ArticleStateJournal(
            Config(root), docs, article_ir, trace, inventory, slots
        )
        source = journal.capture(
            ArticleStateStage.SOURCE_RECONSTRUCTED, include_context=False
        )
        context = journal.plan_context(delivery_expectation="ARTICLE_SCOPED_CONTEXT")
        pre = journal.capture(ArticleStateStage.PRE_TRANSLATION)
        target = journal.capture(ArticleStateStage.TARGET_GENERATED)
        allocated = journal.capture(
            ArticleStateStage.TARGET_ALLOCATED,
            status=ArticleStateStatus.ROLLED_BACK,
            reason="ARTICLE_FLOW_ROLLED_BACK",
        )
        typeset = journal.capture(ArticleStateStage.TYPESET)

        check(
            "context records are owner scoped with no term leakage",
            [record.article_id for record in context]
            == ["article-a", "article-b"]
            and context[0].ordered_source_refs == ("p1#0",)
            and context[1].ordered_source_refs == ("p2#0",)
            and len(context[0].manual_term_refs) == 1
            and len(context[1].manual_term_refs) == 1
            and context[0].manual_term_refs != context[1].manual_term_refs,
        )
        check(
            "five capture generations are immutable and monotonic",
            [state.generation for state in journal.states] == [1, 2, 3, 4, 5]
            and [state.stage for state in journal.states] == list(ArticleStateStage)
            and len({state.state_sha256 for state in journal.states}) == 5
            and source.previous_generation is None
            and typeset.previous_generation == 4,
        )
        check(
            "rollback state retains previous generation and frozen refs",
            allocated.status is ArticleStateStatus.ROLLED_BACK
            and allocated.previous_generation == target.generation
            and allocated.legal_slots_sha256 == slots.digest
            and allocated.fixed_asset_refs == ("p1:pdf_figure#0",),
        )
        manifest = json.loads((root / "article_state.manifest.json").read_text())
        check(
            "every generation has a checkpoint and manifest binding",
            manifest["latest_generation"] == 5
            and len(manifest["states"]) == 5
            and all((root / row["file"]).is_file() for row in manifest["states"])
            and manifest["states"][1]["state_sha256"] == pre.state_sha256,
        )

        skip_root = root / "skip"
        skip_journal = ArticleStateJournal(
            Config(skip_root, skip_translation=True),
            docs,
            article_ir,
            RunTrace.from_document(docs, article_ir),
            inventory,
            slots,
        )
        skip_journal.capture(
            ArticleStateStage.SOURCE_RECONSTRUCTED, include_context=False
        )
        skip_journal.plan_context(delivery_expectation="NOT_EXERCISED")
        skip_pre = skip_journal.capture(
            ArticleStateStage.PRE_TRANSLATION,
            status=ArticleStateStatus.NOT_EXERCISED,
            reason="SKIP_TRANSLATION",
            include_context=False,
        )
        check(
            "skip translation checkpoints deterministic unexercised context",
            skip_pre.status is ArticleStateStatus.NOT_EXERCISED
            and skip_pre.reason == "SKIP_TRANSLATION"
            and not skip_pre.article_context_record_refs
            and skip_pre.context_sha256 is None
            and bool(skip_pre.context_input_manifest_sha256)
            and all(
                record.delivery_expectation == "NOT_EXERCISED"
                for record in skip_journal.context_records
            ),
        )

        debug_root = root / "debug"
        for page in docs.page:
            for paragraph in page.pdf_paragraph:
                paragraph.debug_id = "changed-overlay-only"
        debug_journal = ArticleStateJournal(
            Config(debug_root),
            docs,
            article_ir,
            RunTrace.from_document(docs, article_ir),
            inventory,
            slots,
        )
        debug_source = debug_journal.capture(
            ArticleStateStage.SOURCE_RECONSTRUCTED, include_context=False
        )
        check(
            "semantic state digest excludes debug identity",
            source.document_semantic_sha256 == debug_source.document_semantic_sha256,
        )

    if failures:
        print(f"spec_check_article_state_checkpoints: FAIL {failures}")
        return 1
    print("spec_check_article_state_checkpoints: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
