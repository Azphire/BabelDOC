"""Offline contract checks for the canonical cross-page ArticleDocumentIR."""

from __future__ import annotations

import inspect
import sys
import tempfile
import types
from pathlib import Path

GATE_SET = "fast"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec_checks.delivery_commits import delivery_files  # noqa: E402

try:
    import peewee  # noqa: F401
except ModuleNotFoundError:
    cache_module = types.ModuleType("babeldoc.translator.cache")

    class TranslationCache:
        pass

    cache_module.TranslationCache = TranslationCache
    sys.modules[cache_module.__name__] = cache_module

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine import article_context  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


class Config:
    def __init__(self, root: Path):
        self.root = root
        self.working_dir = root
        self.lang_out = "zh"

    def get_working_file_path(self, name: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        return str(self.root / name)


class BriefClient:
    def brief(self, _prompt):
        return article_context.BriefOutcome(
            brief=article_context.ArticleBrief(
                title_translation="Canonical title",
                register="formal",
                names=(),
            ),
            attempts=1,
        )


POLICIES = {
    "opener": {
        "opens_article": True,
        "chain_eligible": True,
        "translate": True,
    },
    "member": {
        "opens_article": False,
        "chain_eligible": True,
        "translate": True,
    },
    "excluded": {
        "opens_article": False,
        "chain_eligible": False,
        "translate": False,
    },
}


def policy_of(kind):
    return POLICIES.get(kind)


def paragraph(
    text: str,
    label: str = "text",
    *,
    x: float = 40.0,
    y: float = 600.0,
    x2: float = 280.0,
    y2: float = 630.0,
    chain_id: str | None = None,
    chain_index: int | None = None,
):
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(x=x, y=y, x2=x2, y2=y2),
        pdf_style=il_version_1.PdfStyle(font_id="body", font_size=10.0),
        unicode=text,
        layout_label=label,
        chain_id=chain_id,
        chain_index=chain_index,
    )


def page(number: int, kind: str, paragraphs):
    frame = il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=frame),
        cropbox=il_version_1.Cropbox(box=frame),
        pdf_paragraph=list(paragraphs),
        # IL page metadata is zero-based; ArticleIR exposes physical pages as 1-based.
        page_number=number - 1,
        unit="pt",
        page_kind=kind,
        page_kind_conf=1.0,
    )


def document(pages):
    return il_version_1.Document(page=list(pages), total_pages=len(pages))


def two_page_chain(raw_chain_id: str):
    return document(
        [
            page(
                1,
                "opener",
                [paragraph("first half", chain_id=raw_chain_id, chain_index=0)],
            ),
            page(
                2,
                "opener",
                [paragraph("second half", chain_id=raw_chain_id, chain_index=1)],
            ),
        ]
    )


def build(docs, root: Path):
    ir = article_builder.ArticleBuilder(Config(root), policy_of=policy_of).process(docs)
    return ir, (root / article_builder.IR_REPORT_NAME).read_bytes()


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(f"{name}: {detail or 'condition was false'}")


def check_two_pages_merge_and_report_issue(root: Path) -> None:
    docs = two_page_chain("run-a")
    docs.page[0].pdf_figure.append(
        il_version_1.PdfFigure(
            box=il_version_1.Box(x=300.0, y=500.0, x2=560.0, y2=700.0)
        )
    )
    ir, _payload = build(docs, root / "two-page")
    check("two opener pages stay two provisional articles", len(ir.articles) == 2)
    check(
        "provisional article pages are not chain-merged",
        [article.pages for article in ir.articles] == [(1,), (2,)],
    )
    check("page index is singular", len(ir.by_page) == 2)
    elements = tuple(
        element for article in ir.articles for element in article.elements
    )
    check(
        "source elements carry stable audit material",
        [element.source_ref for element in elements] == ["p1#0", "p2#0"]
        and all(element.source_box is not None for element in elements)
        and all(len(element.source_text_hash) == 64 for element in elements)
        and all(len(element.style_hash) == 64 for element in elements),
    )
    check(
        "element order is monotonic and unique",
        [element.reading_order for element in elements]
        == sorted({element.reading_order for element in elements}),
    )
    check(
        "slots are indexed geometry",
        all(
            slot.article_id in ir.by_page.values()
            and slot.capacity_hint > 0
            for article in ir.articles
            for slot in article.slots
        ),
    )
    check(
        "slots name fixed obstacles",
        "p1:pdf_figure#0" in ir.articles[0].slots[0].fixed_obstacle_refs,
    )
    check(
        "canonical chains reverse-index articles",
        not ir.by_chain and all(not article.chain_ids for article in ir.articles),
    )
    check(
        "chain conflict is structured",
        not ir.issues,
    )


def check_page_policy_without_chain(root: Path) -> None:
    joined, _ = build(
        document(
            [
                page(1, "opener", [paragraph("opening")]),
                page(2, "member", [paragraph("continuation")]),
            ]
        ),
        root / "policy-join",
    )
    split, _ = build(
        document(
            [
                page(1, "opener", [paragraph("one")]),
                page(2, "opener", [paragraph("two")]),
            ]
        ),
        root / "policy-split",
    )
    check("member follows current page policy", len(joined.articles) == 1)
    check("opener follows current page policy", len(split.articles) == 2)


def check_three_page_split(root: Path) -> None:
    docs = document(
        [
            page(
                1,
                "opener",
                [paragraph("one", chain_id="joined", chain_index=0)],
            ),
            page(
                2,
                "opener",
                [paragraph("two", chain_id="joined", chain_index=1)],
            ),
            page(3, "opener", [paragraph("three")]),
        ]
    )
    ir, _ = build(docs, root / "three-page")
    check("three opener pages stay three articles", len(ir.articles) == 3)
    check(
        "legacy chain fields cannot merge owners",
        [article.pages for article in ir.articles] == [(1,), (2,), (3,)],
    )


def check_same_page_multi_article_guard(root: Path) -> None:
    docs = document(
        [
            page(
                1,
                "opener",
                [
                    paragraph("First feature", "title", x=40.0, x2=280.0),
                    paragraph("body one", y=540.0),
                    paragraph(
                        "Second feature",
                        "title",
                        x=320.0,
                        x2=560.0,
                    ),
                    paragraph("body two", x=320.0, y=540.0, x2=560.0),
                ],
            )
        ]
    )
    ir, _ = build(docs, root / "unsupported")
    unsupported = ir.unsupported_pages
    check(
        "same-page multi-article is unsupported",
        len(unsupported) == 1
        and unsupported[0].reason
        == article_builder.UNSUPPORTED_SAME_PAGE_MULTI_ARTICLE,
    )
    check("unsupported page has no article or slots", not ir.articles)
    check(
        "unsupported policy forbids article reflow",
        not any(article.slots for article in ir.articles),
    )
    check(
        "unsupported page remains one identity",
        not ir.by_page,
    )
    joined_title = document(
        [
            page(
                1,
                "opener",
                [
                    paragraph(
                        "One broken",
                        "title",
                        chain_id="display",
                        chain_index=0,
                    ),
                    paragraph(
                        "heading",
                        "title",
                        x=320.0,
                        x2=560.0,
                        chain_id="display",
                        chain_index=1,
                    ),
                ],
            )
        ]
    )
    joined_ir, _ = build(joined_title, root / "joined-title")
    check(
        "legacy chain fields cannot bypass same-page unsupported guard",
        bool(joined_ir.unsupported_pages) and not joined_ir.by_page,
    )


def check_fresh_run_determinism(root: Path) -> None:
    first, first_bytes = build(two_page_chain("random-one"), root / "det-one")
    second, second_bytes = build(two_page_chain("random-two"), root / "det-two")
    check(
        "article ids are deterministic",
        [item.article_id for item in first.articles]
        == [item.article_id for item in second.articles],
    )
    check("article IR JSON bytes are deterministic", first_bytes == second_bytes)
    check(
        "source refs reverse-index articles",
        set(first.by_element)
        == {
            element.source_ref
            for article in first.articles
            for element in article.elements
        },
    )


def check_context_consumes_same_ir(root: Path) -> None:
    docs = document(
        [
            page(
                1,
                "opener",
                [
                    paragraph("A title", "title", y=700.0),
                    paragraph("Opening body", y=620.0),
                ],
            )
        ]
    )
    config = Config(root / "context")
    ir = article_builder.ArticleBuilder(config, policy_of=policy_of).process(docs)
    context = article_context.ArticleContextPlan(
        config, article_document_ir=ir, client=BriefClient()
    ).plan(docs)
    check("context retains canonical object", context.article_document_ir is ir)
    check(
        "context serves canonical article",
        context.brief_for_page(docs.page[0]) is not None,
    )
    source = inspect.getsource(article_context.ArticleContextPlan.plan)
    check("context does not rebuild article identity", "build_articles" not in source)


def changed_files() -> set[str]:
    return delivery_files("C02", ROOT)


def check_negative_contracts() -> None:
    changed = changed_files()
    schemas = {
        path
        for path in changed
        if path.startswith("babeldoc/format/pdf/document_il/il_version_1.")
    }
    check("IL schema remains frozen", not schemas, f"changed {sorted(schemas)}")
    high_level = (ROOT / "babeldoc/format/pdf/high_level.py").read_text(
        encoding="utf-8"
    )
    check(
        "high level retains the canonical object",
        "provisional_owners = article_builder.build_provisional(docs)"
        in high_level
        and "article_document_ir = article_builder.finalize(" in high_level,
    )
    check(
        "high level passes the canonical object to context",
        "article_document_ir=article_document_ir" in high_level,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="article-flow-ir-") as temp:
        root = Path(temp)
        check_two_pages_merge_and_report_issue(root)
        check_page_policy_without_chain(root)
        check_three_page_split(root)
        check_same_page_multi_article_guard(root)
        check_fresh_run_determinism(root)
        check_context_consumes_same_ir(root)
        check_negative_contracts()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} ArticleFlowIR checks failed")
        for failure in FAILURES:
            print(f"- {failure}")
        return 1
    print(f"PASS: {CHECKS} ArticleFlowIR checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
