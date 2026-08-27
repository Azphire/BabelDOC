"""C18 fast gate for provisional-owner-scoped continuity chains."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

# The gate must also run directly from its own directory.
# ruff: noqa: E402
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.article_builder import ArticleBuilder
from babeldoc.magazine.article_ir import ArticleDocumentIR
from babeldoc.magazine.chain_builder import CHAIN_CROSSES_PROVISIONAL_OWNER
from babeldoc.magazine.chain_builder import CHAIN_ENDPOINT_ROLE_NOT_BODY
from babeldoc.magazine.chain_builder import CHAIN_NON_ADJACENT_PHYSICAL_PAGES
from babeldoc.magazine.chain_builder import CHAIN_UNSUPPORTED_PAGE
from babeldoc.magazine.chain_builder import ChainBuilder
from babeldoc.magazine.chain_signals import BOUNDARY_COLUMN
from babeldoc.magazine.chain_signals import BOUNDARY_PAGE
from babeldoc.magazine.chain_signals import BoundaryVerdict
from babeldoc.magazine.chain_signals import Endpoint
from babeldoc.magazine.element_roles import ElementRole

GATE_SET = "fast"


POLICIES = {
    "excluded": {
        "opens_article": False,
        "chain_eligible": False,
        "translate": False,
    },
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
}


def policy_of(kind):
    return POLICIES.get(kind)


class Config:
    def __init__(self, root: Path):
        self.root = root
        self.magazine_article_group = True
        self.magazine_hitl_export = False
        self.magazine_hitl_apply = False
        self.only_include_translated_page = False
        self.split_strategy = None

    def should_translate_page(self, _page: int) -> bool:
        return True

    def get_working_file_path(self, name: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        return str(self.root / name)


def paragraph(text: str, label: str = "text", *, x: float = 20.0):
    return il_version_1.PdfParagraph(
        debug_id="volatile-debug-id",
        layout_label=label,
        unicode=text,
        box=il_version_1.Box(x=x, y=600.0, x2=x + 180.0, y2=630.0),
        pdf_style=il_version_1.PdfStyle(font_id="body", font_size=10.0),
    )


def page(physical: int, kind: str, paragraphs):
    frame = il_version_1.Box(x=0.0, y=0.0, x2=600.0, y2=800.0)
    return il_version_1.Page(
        page_number=physical - 1,
        page_kind=kind,
        page_kind_conf=1.0,
        mediabox=il_version_1.Mediabox(box=frame),
        cropbox=il_version_1.Cropbox(box=frame),
        pdf_paragraph=list(paragraphs),
    )


def document(pages):
    held = list(pages)
    return il_version_1.Document(page=held, total_pages=len(held))


def full_document(last_page: int, replacements: dict[int, tuple[str, list]]):
    return document(
        page(number, *replacements.get(number, ("excluded", [])))
        for number in range(1, last_page + 1)
    )


def endpoint(paragraph, physical: int, label: str, column: int) -> Endpoint:
    return Endpoint(
        paragraph=paragraph,
        page_index=physical,
        label=label,
        column_index=column,
        column_count=2,
        last_line_text=paragraph.unicode or "",
        last_line_width=100.0,
        width=100.0,
        measure=100.0,
        font_family="body",
        font_size=10.0,
    )


def verdict(
    tail,
    head,
    tail_page: int,
    head_page: int,
    *,
    tail_label: str = "text",
    head_label: str = "text",
) -> BoundaryVerdict:
    same_page = tail_page == head_page
    return BoundaryVerdict(
        tail_page=tail_page,
        head_page=head_page,
        eligible=True,
        reason=None,
        pair="body_to_body",
        values={"tail_no_terminal_punct": 1.0},
        score=1.0,
        linked=True,
        tail_fill_ratio=1.0,
        tail=endpoint(tail, tail_page, tail_label, 0),
        head=endpoint(head, head_page, head_label, 1 if same_page else 0),
        kind=BOUNDARY_COLUMN if same_page else BOUNDARY_PAGE,
        pairing="adjacent" if same_page else None,
        tail_column=0,
        head_column=1 if same_page else 0,
        column_count=2 if same_page else None,
    )


def run(root: Path, docs, candidates):
    config = Config(root)
    article_builder = ArticleBuilder(config, policy_of=policy_of)
    provisional = article_builder.build_provisional(docs)
    chain_builder = ChainBuilder(config)
    chain_builder._score_boundaries = lambda _docs: list(candidates)
    result = chain_builder.process(docs, provisional)
    final = article_builder.finalize(provisional, result)
    return provisional, result, final


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool) -> None:
        print(f"{'PASS' if condition else 'FAIL'} {name}")
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="c18-chain-owner-") as temp:
        root = Path(temp)

        same_page_docs = document(
            [
                page(
                    1,
                    "opener",
                    [paragraph("tail continues", x=20.0), paragraph("lower head", x=320.0)],
                )
            ]
        )
        left, right = same_page_docs.page[0].pdf_paragraph
        provisional, result, final = run(
            root / "same-page",
            same_page_docs,
            [verdict(left, right, 1, 1)],
        )
        check(
            "same owner same-page columns form one chain",
            len(result.chains) == 1
            and result.chains[0].article_id == provisional.by_page[1]
            and final.chains == result.chains,
        )

        adjacent_docs = document(
            [
                page(1, "opener", [paragraph("tail continues")]),
                page(2, "member", [paragraph("lower head")]),
            ]
        )
        tail = adjacent_docs.page[0].pdf_paragraph[0]
        head = adjacent_docs.page[1].pdf_paragraph[0]
        provisional, result, final = run(
            root / "adjacent",
            adjacent_docs,
            [verdict(tail, head, 1, 2)],
        )
        chain = result.chains[0]
        positive_chain = chain
        positive_final = final
        joined_source = "".join(
            adjacent_docs.page[page - 1].pdf_paragraph[0].unicode
            for page in chain.member_physical_pages
        )
        check(
            "same owner adjacent physical pages preserve order and source",
            chain.ordered_member_refs == ("p1#0", "p2#0")
            and chain.member_physical_pages == (1, 2)
            and [item.end for item in chain.source_ranges]
            == [len(tail.unicode), len(head.unicode)]
            and all(
                item.source_sha256
                == hashlib.sha256(text.encode("utf-8")).hexdigest()
                for item, text in zip(
                    chain.source_ranges,
                    (tail.unicode, head.unicode),
                    strict=True,
                )
            )
            and joined_source == tail.unicode + head.unicode
            and final.by_chain[chain.chain_id] == provisional.by_page[1],
        )

        opener_docs = full_document(
            9,
            {
                8: ("opener", [paragraph("tail continues")]),
                9: ("opener", [paragraph("lower head")]),
            },
        )
        tail = opener_docs.page[7].pdf_paragraph[0]
        head = opener_docs.page[8].pdf_paragraph[0]
        provisional, result, final = run(
            root / "two-openers",
            opener_docs,
            [verdict(tail, head, 8, 9)],
        )
        check(
            "page 8 and 9 openers stay distinct and cross-owner chain is refused",
            len(set(provisional.by_page.values())) == 2
            and not result.chains
            and any(
                item.code == CHAIN_CROSSES_PROVISIONAL_OWNER
                for item in result.refusals
            )
            and len(final.articles) == 2
            and not final.by_chain
            and any(
                issue.code == CHAIN_CROSSES_PROVISIONAL_OWNER
                for issue in final.issues
            ),
        )

        for left_page, right_page in ((1, 3), (3, 8)):
            gap_docs = full_document(
                right_page,
                {
                    left_page: ("opener", [paragraph("tail continues")]),
                    right_page: ("member", [paragraph("lower head")]),
                },
            )
            tail = gap_docs.page[left_page - 1].pdf_paragraph[0]
            head = gap_docs.page[right_page - 1].pdf_paragraph[0]
            _provisional, result, _final = run(
                root / f"gap-{left_page}-{right_page}",
                gap_docs,
                [verdict(tail, head, left_page, right_page)],
            )
            check(
                f"physical {left_page}<->{right_page} is never adjacent",
                not result.chains
                and result.refusals[0].code
                == CHAIN_NON_ADJACENT_PHYSICAL_PAGES,
            )

        role_docs = document(
            [
                page(1, "opener", [paragraph("Heading", "title")]),
                page(2, "member", [paragraph("lower body")]),
            ]
        )
        tail = role_docs.page[0].pdf_paragraph[0]
        head = role_docs.page[1].pdf_paragraph[0]
        _provisional, result, _final = run(
            root / "role",
            role_docs,
            [verdict(tail, head, 1, 2, tail_label="title")],
        )
        check(
            "non-BODY endpoint is refused",
            not result.chains
            and result.refusals[0].code == CHAIN_ENDPOINT_ROLE_NOT_BODY,
        )

        unsupported_docs = document(
            [
                page(
                    1,
                    "opener",
                    [
                        paragraph("Left title", "title", x=20.0),
                        paragraph("Right title", "title", x=320.0),
                    ],
                )
            ]
        )
        tail, head = unsupported_docs.page[0].pdf_paragraph
        provisional, result, final = run(
            root / "unsupported",
            unsupported_docs,
            [
                verdict(
                    tail,
                    head,
                    1,
                    1,
                    tail_label="title",
                    head_label="title",
                )
            ],
        )
        check(
            "unsupported same-page multi-article has zero owner, slot, and chain",
            1 not in provisional.by_page
            and not final.articles
            and not final.by_page
            and not final.by_chain
            and result.refusals[0].code == CHAIN_UNSUPPORTED_PAGE,
        )

    high_level = (ROOT / "babeldoc/format/pdf/high_level.py").read_text(
        encoding="utf-8"
    )
    order = [
        high_level.index("build_provisional(docs)"),
        high_level.index("ChainBuilder(translation_config).process"),
        high_level.index("article_builder.finalize"),
        high_level.index("RunTrace.from_document(docs, article_document_ir)"),
    ]
    check("runtime order is provisional then chain then final then trace", order == sorted(order))

    check(
        "chain evidence uses closed roles and versions",
        ElementRole.BODY.value == "BODY"
        and positive_chain.decision_version == "owner-scoped-continuity.v1",
    )
    check(
        "chain evidence serializer round-trip is exact",
        ArticleDocumentIR.from_record(positive_final.to_record()).to_record()
        == positive_final.to_record(),
    )

    if failures:
        print(f"spec_check_chain_owner_scope: FAIL {failures}")
        return 1
    print("spec_check_chain_owner_scope: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
