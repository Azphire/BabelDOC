"""C18 fast gate for closed ArticleIR roles and protected unknown elements."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# The gate must also run directly from its own directory.
# ruff: noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.article_builder import UNSUPPORTED_SAME_PAGE_MULTI_ARTICLE
from babeldoc.magazine.article_builder import ArticleBuilder
from babeldoc.magazine.article_flow import load_flow_config
from babeldoc.magazine.element_roles import PROTECTED_ROLES
from babeldoc.magazine.element_roles import ElementRole
from babeldoc.magazine.element_roles import load_element_role_config
from babeldoc.magazine.element_roles import map_layout_label

GATE_SET = "fast"


class Config:
    def __init__(self, root: Path):
        self.root = root
        self.magazine_article_group = True
        self.magazine_hitl_export = False
        self.magazine_hitl_apply = False
        self.only_include_translated_page = False

    def should_translate_page(self, _page: int) -> bool:
        return True

    def get_working_file_path(self, name: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        return str(self.root / name)


def policy_of(_kind):
    return {"opens_article": True, "chain_eligible": True, "translate": True}


def paragraph(label: str, text: str, x: float, *, debug_id="volatile"):
    return il_version_1.PdfParagraph(
        debug_id=debug_id,
        layout_label=label,
        unicode=text,
        box=il_version_1.Box(x=x, y=650.0, x2=x + 180.0, y2=680.0),
        pdf_style=il_version_1.PdfStyle(font_id="f", font_size=10.0),
    )


def document(paragraphs):
    frame = il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
    return il_version_1.Document(
        total_pages=1,
        page=[
            il_version_1.Page(
                page_number=0,
                page_kind="opener",
                page_kind_conf=1.0,
                mediabox=il_version_1.Mediabox(box=frame),
                cropbox=il_version_1.Cropbox(box=frame),
                pdf_paragraph=list(paragraphs),
            )
        ],
    )


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool) -> None:
        print(f"{'PASS' if condition else 'FAIL'} {name}")
        if not condition:
            failures.append(name)

    roles = load_element_role_config()
    check(
        "role vocabulary is exact and versioned",
        roles.schema_version == "element-roles.v1"
        and {role.value for role in ElementRole}
        == {
            "BODY",
            "HEADING",
            "CAPTION",
            "TOC_RECORD",
            "RECORD",
            "DROP_CAP",
            "FORMULA",
            "FURNITURE",
            "PASSTHROUGH",
            "UNCLASSIFIED",
        },
    )
    check(
        "known raw labels map before use",
        map_layout_label("text").role is ElementRole.BODY
        and map_layout_label("title").role is ElementRole.HEADING
        and map_layout_label("figure_caption").role is ElementRole.CAPTION
        and map_layout_label("formula").role is ElementRole.FORMULA,
    )
    unknown = map_layout_label("new_parser_label")
    check(
        "unknown raw label fails closed and protected",
        unknown.role is ElementRole.UNCLASSIFIED
        and unknown.role in PROTECTED_ROLES
        and unknown.reason == "unknown_raw_layout_label"
        and "article_flow" not in unknown.allowed_consumers,
    )
    flow = load_flow_config()
    check(
        "general article flow admits BODY only",
        flow.eligible_roles == (ElementRole.BODY,)
        and flow.eligible(ElementRole.BODY)
        and not flow.eligible(ElementRole.HEADING)
        and not flow.eligible(ElementRole.UNCLASSIFIED),
    )

    with tempfile.TemporaryDirectory(prefix="c18-article-ir-") as temp:
        root = Path(temp)
        docs = document(
            (
                paragraph("title", "Heading", 50.0),
                paragraph("text", "Body", 50.0),
                paragraph("new_parser_label", "Unknown", 50.0),
            )
        )
        first = ArticleBuilder(Config(root / "first"), policy_of=policy_of).process(
            docs
        )
        elements = first.articles[0].elements
        check(
            "ArticleIR keeps closed role plus raw mapping evidence",
            [item.role for item in elements]
            == [ElementRole.HEADING, ElementRole.BODY, ElementRole.UNCLASSIFIED]
            and [item.raw_layout_label for item in elements]
            == ["title", "text", "new_parser_label"]
            and elements[-1].role_mapping_reason == "unknown_raw_layout_label",
        )
        old_id = first.articles[0].article_id
        for index, item in enumerate(docs.page[0].pdf_paragraph):
            item.debug_id = f"other-debug-{index}"
        second = ArticleBuilder(
            Config(root / "second"), policy_of=policy_of
        ).process(docs)
        check(
            "deterministic identity excludes path and debug ids",
            old_id == second.articles[0].article_id,
        )

        unsupported_docs = document(
            (
                paragraph("title", "Left article", 30.0),
                paragraph("title", "Right article", 360.0),
            )
        )
        unsupported = ArticleBuilder(
            Config(root / "unsupported"), policy_of=policy_of
        ).process(unsupported_docs)
        check(
            "same-page multi-article remains unsupported with no slot",
            len(unsupported.unsupported_pages) == 1
            and unsupported.unsupported_pages[0].reason
            == UNSUPPORTED_SAME_PAGE_MULTI_ARTICLE
            and not unsupported.articles
            and not unsupported.by_page,
        )

    check(
        "debug overlay is not a declared semantic raw role",
        "debug_overlay" not in roles.mappings,
    )
    if failures:
        print(f"spec_check_article_ir_contract: FAIL {failures}")
        return 1
    print("spec_check_article_ir_contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
