"""Gate: a first line indent is decided only for article body, only at its head.

Four claims are under test, one per stated requirement.

1. Only running body text the canonical article grouping actually claimed is
   indented. A page the vocabulary does not admit stops the whole page; a
   paragraph no article holds stops that paragraph, whatever page it sits on.
2. A title is never indented by this pass.
3. Only the paragraph that opens a translated chain is indented; a member that
   resumes one is not.
4. Where the flow pass breaks one paragraph across columns or across pages, only
   the first piece carries the indent.

Claims 2, 3 and 4 already held before this gate existed and are pinned here
rather than repaired. Claim 1 is the one this batch added, and its page space
half - a run over a selected page range asked the article index its question in
the wrong page number space - is pinned by E6.

Nothing here writes down a page type name, a layout label or a language tag that
the shipped configuration does not already declare: every fixture reads its
vocabulary out of the configuration, so a gate that passes is a statement about
the policy the pipeline runs on rather than about a copy of it.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import FIT_PREFIX  # noqa: E402
from babeldoc.magazine import article_flow  # noqa: E402
from babeldoc.magazine import drop_cap_intent  # noqa: E402
from babeldoc.magazine import indent_policy  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticlePolicyEvidence  # noqa: E402
from babeldoc.magazine.article_ir import ArticleRegionSlot  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.taxonomy import load_taxonomy  # noqa: E402

# The labels a page sets to its own rules rather than to the body convention.
# S3 asserts none of them is inside the body set; the behavioural checks borrow
# the first as the title a real page would carry.
TITLE_LABELS = ("title", "doc_title", "paragraph_title", "caption")

# Language tags no entry of the shipped configuration is expected to claim.
# One of them standing in for "a target this pass has no opinion about" keeps
# E8 honest without this file asserting which languages are declared.
UNCLAIMED_CANDIDATES = ("fr", "de", "ja", "es", "it")


class CheckError(AssertionError):
    """Raised when one assertion of this gate does not hold."""


def require(condition: object, detail: str) -> None:
    if not condition:
        raise CheckError(detail)


# --------------------------------------------------------------------------
# vocabulary, read out of the shipped configuration
# --------------------------------------------------------------------------


def authoritative_target() -> str:
    """A target language the configuration gives this pass authority over."""
    config = indent_policy.load_indent_config()
    for tag in config.by_target:
        mode, _origin = config.mode_for(tag)
        if indent_policy.mode_is_authoritative(mode):
            return tag
    raise CheckError("no target language is declared with an authoritative mode")


def unclaimed_target() -> str:
    """A target language that falls back to reproducing the source."""
    config = indent_policy.load_indent_config()
    for tag in UNCLAIMED_CANDIDATES:
        mode, _origin = config.mode_for(tag)
        if not indent_policy.mode_is_authoritative(mode):
            return tag
    raise CheckError("every candidate target language is declared")


def body_label() -> str:
    return indent_policy.load_indent_config().body_labels[0]


def eligible_kind() -> str:
    """A page kind whose declared policy admits a paragraph convention."""
    taxonomy = load_taxonomy()
    for name in taxonomy.names():
        policy = taxonomy.policy_of(name) or {}
        if policy.get(indent_policy.PAGE_ELIGIBILITY_POLICY_FLAG, False):
            return name
    raise CheckError("no page kind declares the indent eligibility policy")


def ineligible_kind() -> str:
    taxonomy = load_taxonomy()
    for name in taxonomy.names():
        policy = taxonomy.policy_of(name) or {}
        if not policy.get(indent_policy.PAGE_ELIGIBILITY_POLICY_FLAG, False):
            return name
    raise CheckError("every page kind declares the indent eligibility policy")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


class RuntimeConfig:
    """The smallest object ``indent_policy.apply`` reads."""

    def __init__(self, working_dir: Path, target: str) -> None:
        self.working_dir = working_dir
        self.lang_out = target
        self.magazine_indent_policy = True

    def get_working_file_path(self, name: str) -> str:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return str(self.working_dir / name)


def pdf_style() -> il.PdfStyle:
    return il.PdfStyle(
        font_id="target-body",
        font_size=10.0,
        graphic_state=il.GraphicState(),
    )


def paragraph(
    text: str,
    *,
    label: str | None = None,
    chain_index: int | None = None,
    first_line_indent: bool = False,
) -> il.PdfParagraph:
    style = pdf_style()
    item = il.PdfParagraph(
        box=il.Box(10.0, 60.0, 160.0, 78.0),
        pdf_style=style,
        unicode=text,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_unicode_characters=il.PdfSameStyleUnicodeCharacters(
                    unicode=text,
                    pdf_style=style,
                )
            )
        ],
        layout_label=body_label() if label is None else label,
        first_line_indent=first_line_indent,
    )
    if chain_index is not None:
        item.chain_index = chain_index
    return item


def make_document(
    pages: list[list[il.PdfParagraph]],
    *,
    physical_pages: list[int],
    kinds: list[str],
    total_pages: int = 12,
) -> il.Document:
    """A document whose pages carry physical numbers of the caller's choosing.

    ``page_number`` is zero based and physical; the position of a page inside
    ``docs.page`` is the canonical number. Handing the two different values is
    the whole point of E6, so the fixture never derives one from the other.
    """
    page_box = il.Box(0.0, 0.0, 180.0, 120.0)
    return il.Document(
        page=[
            il.Page(
                page_number=physical - 1,
                unit="pt",
                mediabox=il.Mediabox(box=copy.deepcopy(page_box)),
                cropbox=il.Cropbox(box=copy.deepcopy(page_box)),
                pdf_paragraph=paragraphs,
                page_kind=kind,
            )
            for paragraphs, physical, kind in zip(
                pages, physical_pages, kinds, strict=True
            )
        ],
        total_pages=total_pages,
    )


def make_article_ir(claimed: dict[int, list[int]]) -> ArticleDocumentIR:
    """One article holding exactly the canonical references named by ``claimed``.

    Keyed by canonical page, one based, to the paragraph indexes on that page
    the article grouping claims. A paragraph left out of the mapping is one no
    article holds, which is the case this gate exists to tell apart.
    """
    article_id = "article-fixture"
    order = 0
    elements = []
    for canonical_page in sorted(claimed):
        for index in sorted(claimed[canonical_page]):
            elements.append(
                SourceElementRef(
                    source_ref=f"p{canonical_page}#{index}",
                    page=canonical_page,
                    column=0,
                    reading_order=order,
                    role="body",
                    source_box=(10.0, 60.0, 160.0, 78.0),
                    source_text_hash=hashlib.sha256(b"").hexdigest(),
                    style_hash=drop_cap_intent.style_hash(pdf_style()),
                )
            )
            order += 1
    pages = tuple(sorted(claimed))
    article = ArticleIR(
        article_id=article_id,
        pages=pages,
        elements=tuple(elements),
        slots=tuple(
            ArticleRegionSlot(
                article_id=article_id,
                page=page,
                column=0,
                slot_order=position,
                box=(0.0, 0.0, 180.0, 120.0),
                fixed_obstacle_refs=(),
                capacity_hint=21600.0,
            )
            for position, page in enumerate(pages)
        ),
        chain_ids=(),
        policy_evidence=tuple(
            ArticlePolicyEvidence(page, "body", None, None, True) for page in pages
        ),
    )
    return ArticleDocumentIR(
        articles=(article,),
        by_page=dict.fromkeys(pages, article_id),
        by_element={element.source_ref: article_id for element in elements},
        by_chain={},
    )


def run(
    tmp: Path,
    name: str,
    pages: list[list[il.PdfParagraph]],
    claimed: dict[int, list[int]],
    *,
    physical_pages: list[int],
    kinds: list[str],
    target: str | None = None,
) -> tuple[dict, il.Document]:
    docs = make_document(pages, physical_pages=physical_pages, kinds=kinds)
    config = RuntimeConfig(
        tmp / name, authoritative_target() if target is None else target
    )
    record = indent_policy.apply(config, docs, make_article_ir(claimed))
    require(record is not None, "the pass returned no record")
    return record, docs


def row_of(record: dict, canonical_ref: str) -> dict:
    for row in record["paragraphs"]:
        if row["canonical_ref"] == canonical_ref:
            return row
    raise CheckError(f"no row for {canonical_ref}")


# --------------------------------------------------------------------------
# symbol level
# --------------------------------------------------------------------------


def s1_reason_declared() -> str:
    require(
        indent_policy.SKIP_OUTSIDE_ARTICLE == "outside_article",
        f"the reason is spelled {indent_policy.SKIP_OUTSIDE_ARTICLE!r}",
    )
    require(
        indent_policy.SKIP_OUTSIDE_ARTICLE in indent_policy.SKIP_REASONS,
        "the reason is not in the closed set the sidecar publishes",
    )
    return "a paragraph outside every article has a reason of its own to be named by"


def s2_clear_order() -> str:
    expected = (
        indent_policy.SKIP_PAGE_INELIGIBLE,
        indent_policy.SKIP_OUTSIDE_BODY,
        indent_policy.SKIP_OUTSIDE_ARTICLE,
        indent_policy.SKIP_MODE,
        indent_policy.CLEAR_CHAIN_CONTINUATION,
    )
    require(
        indent_policy.CLEAR_ORDER == expected,
        f"CLEAR_ORDER is {indent_policy.CLEAR_ORDER!r}",
    )
    return "page, then label, then article, then mode, then chain: widest first"


def s3_titles_are_not_body() -> str:
    labels = set(indent_policy.load_indent_config().body_labels)
    overlap = sorted(labels.intersection(TITLE_LABELS))
    require(not overlap, f"body_labels admits the title label(s) {overlap}")
    return "no title label is inside the closed set of body labels"


# --------------------------------------------------------------------------
# behaviour level
# --------------------------------------------------------------------------


def e1_body_in_article_is_indented(tmp: Path) -> str:
    record, docs = run(
        tmp,
        "e1",
        [[paragraph("body text of an article", chain_index=0)]],
        {1: [0]},
        physical_pages=[4],
        kinds=[eligible_kind()],
    )
    row = row_of(record, "p1#0")
    require(row["skipped"] is None, f"skipped is {row['skipped']!r}")
    require(row["after"] is True, f"after is {row['after']!r}")
    require(
        docs.page[0].pdf_paragraph[0].first_line_indent is True,
        "the paragraph itself was not indented",
    )
    return "body an article holds, opening a chain, on an admitted page, indents"


def e2_outside_article_is_flush(tmp: Path) -> str:
    record, docs = run(
        tmp,
        "e2",
        [
            [
                paragraph("body an article holds", chain_index=0),
                paragraph("copy no article holds", chain_index=0),
            ]
        ],
        {1: [0]},
        physical_pages=[4],
        kinds=[eligible_kind()],
    )
    held = row_of(record, "p1#0")
    loose = row_of(record, "p1#1")
    require(held["skipped"] is None, f"the held paragraph skipped {held['skipped']!r}")
    require(
        loose["skipped"] == indent_policy.SKIP_OUTSIDE_ARTICLE,
        f"the loose paragraph skipped {loose['skipped']!r}",
    )
    require(loose["after"] is False, f"the loose paragraph is {loose['after']!r}")
    require(loose["article_id"] is None, "a loose paragraph was given an article id")
    require(loose["in_article"] is False, "a loose paragraph was recorded as held")
    require(
        docs.page[0].pdf_paragraph[1].first_line_indent is False,
        "the loose paragraph itself was left indented",
    )
    return "identical body text on one page parts on whether an article holds it"


def e3_ineligible_page_wins(tmp: Path) -> str:
    record, _docs = run(
        tmp,
        "e3",
        [[paragraph("body text on a page of the wrong kind", chain_index=0)]],
        {},
        physical_pages=[4],
        kinds=[ineligible_kind()],
    )
    row = row_of(record, "p1#0")
    require(
        row["skipped"] == indent_policy.SKIP_PAGE_INELIGIBLE,
        f"skipped is {row['skipped']!r}",
    )
    require(row["after"] is False, f"after is {row['after']!r}")
    require(row["in_article"] is False, "the fixture paragraph was held after all")
    return "a page the vocabulary does not admit reports before the article gate does"


def e4_title_is_flush(tmp: Path) -> str:
    record, _docs = run(
        tmp,
        "e4",
        [[paragraph("A Headline", label=TITLE_LABELS[0], chain_index=0)]],
        {1: [0]},
        physical_pages=[4],
        kinds=[eligible_kind()],
    )
    row = row_of(record, "p1#0")
    require(
        row["skipped"] == indent_policy.SKIP_OUTSIDE_BODY,
        f"skipped is {row['skipped']!r}",
    )
    require(row["after"] is False, f"after is {row['after']!r}")
    return "a title inside an article on an admitted page is still set flush"


def e5_chain_continuation_is_flush(tmp: Path) -> str:
    record, _docs = run(
        tmp,
        "e5",
        [
            [
                paragraph("the paragraph that opens the chain", chain_index=0),
                paragraph("the same paragraph resumed", chain_index=1),
            ]
        ],
        {1: [0, 1]},
        physical_pages=[4],
        kinds=[eligible_kind()],
    )
    head = row_of(record, "p1#0")
    tail = row_of(record, "p1#1")
    require(head["skipped"] is None, f"the chain head skipped {head['skipped']!r}")
    require(head["after"] is True, "the chain head was not indented")
    require(
        tail["skipped"] == indent_policy.CLEAR_CHAIN_CONTINUATION,
        f"the continuation skipped {tail['skipped']!r}",
    )
    require(tail["after"] is False, "a resumed paragraph was indented")
    return "a resumed chain member meets the other four conditions and is still flush"


def e6_page_number_spaces(tmp: Path) -> str:
    record, _docs = run(
        tmp,
        "e6",
        [
            [paragraph("first page body", chain_index=0)],
            [paragraph("second page body", chain_index=0)],
            [paragraph("third page body", chain_index=0)],
        ],
        {1: [0], 2: [0], 3: [0]},
        physical_pages=[3, 8, 9],
        kinds=[eligible_kind()] * 3,
    )
    rows = record["paragraphs"]
    require(len(rows) == 3, f"{len(rows)} row(s) for three paragraphs")
    require(
        all(row["article_id"] is not None for row in rows),
        "a selected page lost its article: "
        + repr([(row["page"], row["article_id"]) for row in rows]),
    )
    require(
        [row["page"] for row in rows] == [3, 8, 9],
        f"physical pages are {[row['page'] for row in rows]}",
    )
    require(
        [row["canonical_page"] for row in rows] == [1, 2, 3],
        f"canonical pages are {[row['canonical_page'] for row in rows]}",
    )
    require(
        [row["reference"] for row in rows] == ["p3#0", "p8#0", "p9#0"],
        f"references are {[row['reference'] for row in rows]}",
    )
    require(
        [row["canonical_ref"] for row in rows] == ["p1#0", "p2#0", "p3#0"],
        f"canonical refs are {[row['canonical_ref'] for row in rows]}",
    )
    require(
        [row["body_rank"] for row in rows] == [1, 2, 3],
        f"body ranks are {[row['body_rank'] for row in rows]}",
    )
    require(
        [page["page"] for page in record["page_records"]] == [3, 8, 9],
        "the page records do not carry the selected physical pages",
    )
    return "a run not starting at page one keeps both page numbers and keeps them apart"


def e7_conservation(tmp: Path) -> str:
    record, _docs = run(
        tmp,
        "e7",
        [
            [
                paragraph("body an article holds", chain_index=0),
                paragraph("copy no article holds", chain_index=0),
                paragraph("A Headline", label=TITLE_LABELS[0], chain_index=0),
                paragraph("the same paragraph resumed", chain_index=1),
            ],
            [paragraph("body on a page of the wrong kind", chain_index=0)],
        ],
        {1: [0, 3]},
        physical_pages=[4, 5],
        kinds=[eligible_kind(), ineligible_kind()],
    )
    totals = record["totals"]
    require(
        totals["decided"] + totals["left_alone"] == totals["paragraphs"],
        f"decided {totals['decided']} + left alone {totals['left_alone']} "
        f"!= {totals['paragraphs']}",
    )
    require(record["authoritative"] is True, "the fixture mode is not authoritative")
    require(
        sum(totals["skipped"].values()) + totals["indented_after"]
        == totals["paragraphs"],
        f"skipped {sum(totals['skipped'].values())} + indented "
        f"{totals['indented_after']} != {totals['paragraphs']}",
    )
    require(
        totals["paragraphs_in_article"] + totals["paragraphs_outside_article"]
        == totals["paragraphs"],
        "the article membership tallies do not cover every paragraph",
    )
    # One paragraph per reason, and the one paragraph nothing objects to. The
    # title is claimed by the article and sits on an admitted page, so it can
    # only be reported under its label; the loose paragraph is body text on the
    # same admitted page, so it can only be reported under its article.
    wanted = {
        indent_policy.SKIP_PAGE_INELIGIBLE: 1,
        indent_policy.SKIP_OUTSIDE_BODY: 1,
        indent_policy.SKIP_OUTSIDE_ARTICLE: 1,
        indent_policy.SKIP_MODE: 0,
        indent_policy.CLEAR_CHAIN_CONTINUATION: 1,
    }
    require(totals["skipped"] == wanted, f"skipped is {totals['skipped']!r}")
    require(totals["indented_after"] == 1, f"indented {totals['indented_after']}")
    return "every paragraph is accounted for exactly once, by decision and by reason"


def e8_source_mode_still_reports(tmp: Path) -> str:
    record, docs = run(
        tmp,
        "e8",
        [
            [
                paragraph(
                    "body carried in indented",
                    first_line_indent=True,
                    chain_index=0,
                )
            ],
            [paragraph("body carried in flush", chain_index=0)],
        ],
        {1: [0], 2: [0]},
        physical_pages=[3, 4],
        kinds=[eligible_kind()] * 2,
        target=unclaimed_target(),
    )
    require(record["authoritative"] is False, "an unclaimed target claimed authority")
    for row in record["paragraphs"]:
        require(
            row["before"] == row["after"],
            f"{row['canonical_ref']} moved from {row['before']} to {row['after']}",
        )
        require(row["decided"] is False, f"{row['canonical_ref']} was decided")
        require(
            row["article_id"] is not None,
            f"{row['canonical_ref']} lost its article",
        )
        require(row["canonical_ref"], "a row carries no canonical reference")
        require(row["canonical_page"], "a row carries no canonical page")
    require(
        [row["page"] for row in record["paragraphs"]] == [3, 4],
        "the physical page numbers are not the selected ones",
    )
    require(
        docs.page[0].pdf_paragraph[0].first_line_indent is True,
        "a source mode run overwrote the flag it was told to keep",
    )
    require(record["totals"]["changed"] == 0, "a source mode run changed a paragraph")
    return "a source mode run decides nothing and still names every paragraph fully"


# --------------------------------------------------------------------------
# E9: the flow pass, read only
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StubFit:
    """Exactly what ``allocate_segment`` reads back from the fit API."""

    consumed: int
    bottom: float

    @property
    def status(self) -> str:
        return FIT_PREFIX

    @property
    def consumed_range(self) -> tuple[int, int]:
        return (0, self.consumed)

    @property
    def ink_bounds(self) -> tuple[float, float, float, float]:
        return (0.0, self.bottom, 100.0, self.bottom + 10.0)

    def to_record(self) -> dict:
        return {"status": self.status, "consumed": self.consumed}


class StubTypesetter:
    """A fitter that always takes a fixed number of characters.

    The claim under test belongs to ``allocate_segment`` - which piece of a
    broken paragraph keeps the indent - and not to the measurement that decides
    where the break falls, so the measurement is held fixed rather than
    reproduced with real fonts. What the fitter is asked for is recorded too,
    because the indent the typesetting stage is told to set on each piece is the
    other half of the claim: a placement flagged correctly and a fitter asked
    incorrectly would still print the wrong page.
    """

    def __init__(self, per_slot: int, lang_out: str = "zh") -> None:
        self._per_slot = per_slot
        self.translation_config = type("Cfg", (), {"lang_out": lang_out})()
        self.paragraph_starts: list[bool] = []

    def fit_text_to_slot(self, text, _style, _lang, box, *, paragraph_start, **_kw):
        self.paragraph_starts.append(paragraph_start)
        return StubFit(min(self._per_slot, len(text)), float(box.y) + 1.0)


def flow_slot(slot_id: str, page: int, column: int, order: int):
    return article_flow.ArticleFlowSlot(
        slot_id=slot_id,
        article_id="article-fixture",
        page=page,
        column=column,
        slot_order=order,
        box=(0.0, 0.0, 100.0, 200.0),
        obstacle_refs=(),
    )


def flow_segment(slots: tuple, text: str):
    boundary = article_flow.ParagraphBoundaryToken(
        source_ref="p1#0",
        source_page=1,
        source_slot_id="source-holder:p1#0",
        paragraph_order=0,
        request_id="article-flow-source:p1#0",
        fragment_id="article-flow-target-fixture",
        target_start=0,
        target_end=len(text),
        text=text,
        first_line_indent=True,
        spacing_before=0.0,
        style=pdf_style(),
        original_font=None,
        paragraph=paragraph(text),
    )
    return article_flow.ArticleFlowSegment(
        segment_id="segment-fixture",
        article_id="article-fixture",
        page=1,
        ordered_source_refs=("p1#0",),
        ordered_slots=slots,
        boundaries=(boundary,),
        protected_elements=(),
    )


def e9_only_the_first_piece_indents(_tmp: Path) -> str:
    config = article_flow.load_flow_config()
    text = "x" * 90
    cases = {
        "across columns of one page": (
            (
                flow_slot("slot-a", 1, 0, 0),
                flow_slot("slot-b", 1, 1, 1),
                flow_slot("slot-c", 1, 2, 2),
            ),
            1,
        ),
        "across pages": (
            (
                flow_slot("slot-a", 1, 0, 0),
                flow_slot("slot-b", 2, 0, 1),
                flow_slot("slot-c", 3, 0, 2),
            ),
            3,
        ),
    }
    for name, (slots, wanted_pages) in cases.items():
        typesetter = StubTypesetter(per_slot=30)
        placements = article_flow.allocate_segment(
            flow_segment(slots, text), typesetter, config
        )
        require(len(placements) == 3, f"{name}: {len(placements)} piece(s), wanted 3")
        flags = [item.first_line_indent for item in placements]
        require(flags == [True, False, False], f"{name}: the pieces carry {flags}")
        require(
            typesetter.paragraph_starts == [True, False, False],
            f"{name}: the fitter was asked for {typesetter.paragraph_starts}",
        )
        pages = sorted({item.page for item in placements})
        require(
            len(pages) == wanted_pages,
            f"{name}: the pieces landed on pages {pages}",
        )
    return "a paragraph broken across columns or pages indents its first piece only"


SYMBOL_CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("S1", s1_reason_declared),
    ("S2", s2_clear_order),
    ("S3", s3_titles_are_not_body),
)

RUN_CHECKS: tuple[tuple[str, Callable[[Path], str]], ...] = (
    ("E1", e1_body_in_article_is_indented),
    ("E2", e2_outside_article_is_flush),
    ("E3", e3_ineligible_page_wins),
    ("E4", e4_title_is_flush),
    ("E5", e5_chain_continuation_is_flush),
    ("E6", e6_page_number_spaces),
    ("E7", e7_conservation),
    ("E8", e8_source_mode_still_reports),
    ("E9", e9_only_the_first_piece_indents),
)


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        checks: list[tuple[str, Callable[[], str]]] = [
            *SYMBOL_CHECKS,
            *((name, (lambda f=check: f(tmp))) for name, check in RUN_CHECKS),
        ]
        for name, check in checks:
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
