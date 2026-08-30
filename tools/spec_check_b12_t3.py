"""Gate: three new actions, each bounded, each refusing rather than half-acting.

The vocabulary goes from three actions to six.  The three added here all move
ink that is already on the page rather than asking for new text, and they share
one failure mode: a relayout that succeeds for some of what it touched and
fails for the rest leaves a page worse than the finding complained about.  A
heading shrunk past legibility, a region where three paragraphs moved and the
fourth did not, a chain where one member overflows because the others took its
characters -- each is a repair that made the document worse while reporting
success.

So every claim here comes in a pair: the action does what it says on input it
admits, and it refuses *whole* on input it does not.  S8 is the claim underneath
all of them -- whatever an action touches, every paragraph outside the set it
wrote is byte-for-byte what it was.

Eight claims:

S1  contain_heading lays an overflowing heading back inside the box its source
    occupied, leaving the text and the box itself unchanged.
S2  contain_heading refuses a heading that will not fit at the declared floor,
    and refuses a paragraph whose role is not a heading role at all.  Failing
    closed leaves an overflow visible; shrinking past the floor would not.
S3  retypeset_article_region lays out every owned member of one region.
S4  retypeset_article_region reaches into no second article, and refuses a
    region whose member count is over the declared ceiling.
S5  retypeset_article_region refuses whole when one member will not fit: the
    members laid out before it are not left moved.
S6  reallocate_chain_cut cuts the chain's translation again one cascade level
    down, conserving it exactly -- the same characters, differently divided.
S7  reallocate_chain_cut refuses at the bottom of the cascade, refuses a member
    that overflows its box, and refuses a chain the report does not carry.
S8  Every action leaves every paragraph outside the set it wrote byte for byte
    unchanged, compared paragraph by paragraph.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import (  # noqa: E402
    BoundedTypesettingError,
)
from babeldoc.magazine import fixed_assets  # noqa: E402
from babeldoc.magazine import minimal_detection  # noqa: E402
from babeldoc.magazine import minimal_repair  # noqa: E402
from babeldoc.magazine.article_ir import ArticleDocumentIR  # noqa: E402
from babeldoc.magazine.article_ir import ArticleIR  # noqa: E402
from babeldoc.magazine.article_ir import SourceElementRef  # noqa: E402
from babeldoc.magazine.detectors.base import Issue  # noqa: E402
from tests.minimal.fakes import FixedWidthMapper  # noqa: E402

# Production layout labels, not the fixture-only "body" the older repair suite
# uses: the region action's vocabulary comes from the body pair class, and a
# gate that tested it against a label no document carries would prove nothing.
BODY_ROLE = "text"
TITLE_ROLE = "title"

HEADING_BOX = (10.0, 80.0, 110.0, 95.0)
MEMBER_BOXES = ((10.0, 60.0, 110.0, 75.0), (10.0, 40.0, 110.0, 55.0))
OTHER_BOX = (10.0, 10.0, 110.0, 25.0)
CHAIN_BOXES = ((10.0, 10.0, 60.0, 25.0), (65.0, 10.0, 115.0, 25.0))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class BoundedFakeTypesetter:
    """A typesetter that lays text inside a box, or declares it will not fit.

    ``refuse`` names the source references whose relayout fails, which is how a
    fixture puts one unfittable member among fittable ones without depending on
    real font metrics.
    """

    def __init__(self, *, refuse: set[str] | None = None):
        self.font_mapper = FixedWidthMapper()
        self.refuse = refuse or set()
        self.laid_out: list[str] = []

    def create_typesetting_units(self, paragraph, fonts):
        return list(paragraph.unicode or "")

    def retypeset_bounded_text(
        self,
        paragraph,
        page,
        typesetting_units,
        *,
        source_ref,
        source_box,
        minimum_scale,
        maximum_lines,
        use_english_line_break=True,
        preserve_wrapped_spaces=False,
    ):
        if source_ref in self.refuse:
            raise BoundedTypesettingError(
                f"{source_ref}: does not fit bounded source container"
            )
        style = minimal_repair._paragraph_style(paragraph)
        left, bottom, right, top = source_box
        text = paragraph.unicode or ""
        width = (right - left) / max(len(text), 1)
        paragraph.box = il_version_1.Box(*source_box)
        paragraph.pdf_paragraph_composition = [
            il_version_1.PdfParagraphComposition(
                pdf_character=il_version_1.PdfCharacter(
                    pdf_style=copy.deepcopy(style),
                    box=il_version_1.Box(
                        left + index * width,
                        bottom,
                        left + (index + 1) * width,
                        top,
                    ),
                    char_unicode=character,
                )
            )
            for index, character in enumerate(text)
        ]
        self.laid_out.append(source_ref)
        return typesetting_units


def _paragraph(text, debug_id, box, *, label, chain_id=None, chain_index=None):
    style = il_version_1.PdfStyle(font_id="body", font_size=10.0)
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(*box),
        pdf_style=style,
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=(
                    il_version_1.PdfSameStyleUnicodeCharacters(
                        pdf_style=copy.deepcopy(style), unicode=text
                    )
                )
            )
        ],
        unicode=text,
        debug_id=debug_id,
        layout_label=label,
        chain_id=chain_id,
        chain_index=chain_index,
    )


def _page(number, paragraphs):
    box = il_version_1.Box(0.0, 0.0, 120.0, 100.0)
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=box),
        cropbox=il_version_1.Cropbox(box=box),
        pdf_font=[il_version_1.PdfFont(font_id="body", name="Fixed")],
        pdf_paragraph=paragraphs,
        base_operations=il_version_1.BaseOperations(value=""),
        page_number=number,
        unit="point",
    )


def _element(ref, page, order, role, box):
    return SourceElementRef(
        source_ref=ref,
        page=page,
        column=0,
        reading_order=order,
        role=role,
        source_box=box,
        source_text_hash=f"source-{ref}",
        style_hash="style",
    )


def fixture():
    """A page carrying a heading, two region members and a chain, and a
    second page carrying the article no action of the first page's may reach.
    """
    paragraphs = [
        _paragraph("翻译后的过长标题文字", "heading", (5.0, 78.0, 118.0, 97.0), label=TITLE_ROLE),
        _paragraph("第一段正文内容", "member-0", MEMBER_BOXES[0], label=BODY_ROLE),
        _paragraph("第二段正文内容", "member-1", MEMBER_BOXES[1], label=BODY_ROLE),
        _paragraph("链首", "chain-0", CHAIN_BOXES[0], label=BODY_ROLE, chain_id="chain-a", chain_index=0),
        _paragraph("链尾", "chain-1", CHAIN_BOXES[1], label=BODY_ROLE, chain_id="chain-a", chain_index=1),
    ]
    # A page carries at most one article, so the second article -- the one no
    # action of this page's may reach -- stands on a page of its own.
    other = [_paragraph("另一篇文章的正文", "other", OTHER_BOX, label=BODY_ROLE)]
    docs = il_version_1.Document(
        page=[_page(6, paragraphs), _page(7, other)], total_pages=2
    )
    elements_a = (
        _element("p1#0", 1, 0, TITLE_ROLE, HEADING_BOX),
        _element("p1#1", 1, 1, BODY_ROLE, MEMBER_BOXES[0]),
        _element("p1#2", 1, 2, BODY_ROLE, MEMBER_BOXES[1]),
        _element("p1#3", 1, 3, BODY_ROLE, CHAIN_BOXES[0]),
        _element("p1#4", 1, 4, BODY_ROLE, CHAIN_BOXES[1]),
    )
    element_b = _element("p2#0", 2, 5, BODY_ROLE, OTHER_BOX)
    article_ir = ArticleDocumentIR(
        articles=(
            ArticleIR("article-a", (1,), elements_a, (), ("chain-a",), ()),
            ArticleIR("article-b", (2,), (element_b,), (), (), ()),
        ),
        by_page={1: "article-a", 2: "article-b"},
        by_element={
            **dict.fromkeys((item.source_ref for item in elements_a), "article-a"),
            "p2#0": "article-b",
        },
        by_chain={"chain-a": "article-a"},
        by_chain_member={"p1#3": "chain-a", "p1#4": "chain-a"},
    )
    baseline = minimal_detection.capture_baseline(
        docs, article_ir, labeled_pages=((7, docs.page[0]), (8, docs.page[1]))
    )
    return docs, article_ir, baseline


def _issue(kind, refs, evidence=None):
    return Issue(
        kind=kind,
        page=7,
        paragraph_refs=tuple(refs),
        geometry=None,
        severity="high",
        evidence=evidence or {},
        detector=kind,
    )


def _digests(docs) -> dict[str, str]:
    """One digest per paragraph, under the reference it is named by."""
    return {
        fixed_assets.paragraph_reference(position + 1, index): (
            fixed_assets.content_digest(paragraph)
        )
        for position, page in enumerate(docs.page)
        for index, paragraph in enumerate(page.pdf_paragraph or ())
    }


def _moved(before: dict[str, str], after: dict[str, str]) -> set[str]:
    _require(set(before) == set(after), "the paragraph set itself changed")
    return {ref for ref in before if before[ref] != after[ref]}


CONFIG = minimal_repair.load_repair_config()


def s1_contain_heading_pulls_a_title_back() -> str:
    docs, article_ir, baseline = fixture()
    typesetter = BoundedFakeTypesetter()
    before_text = docs.page[0].pdf_paragraph[0].unicode
    target = minimal_repair._contain_heading(
        _issue("out_of_page", ("p7#0",)),
        docs,
        baseline,
        article_ir,
        typesetter,
        frozenset(),
        CONFIG,
    )
    laid = docs.page[0].pdf_paragraph[0]
    _require(
        minimal_repair._box_tuple(laid.box) == HEADING_BOX,
        f"the heading was left in {minimal_repair._box_tuple(laid.box)}, not the "
        f"box its source occupied {HEADING_BOX}",
    )
    _require(laid.unicode == before_text, "the heading's text changed")
    _require(target.physical_ref == "p7#0", f"it acted on {target.physical_ref}")
    return "an overflowing heading is laid out again inside its own source box"


def s2_contain_heading_refuses_whole() -> str:
    docs, article_ir, baseline = fixture()
    before = _digests(docs)
    typesetter = BoundedFakeTypesetter(refuse={"p7#0"})
    try:
        minimal_repair._contain_heading(
            _issue("out_of_page", ("p7#0",)),
            docs, baseline, article_ir, typesetter, frozenset(), CONFIG,
        )
        raise AssertionError("a heading that does not fit was accepted")
    except minimal_repair._RepairRefusalError as refusal:
        _require(
            refusal.reason == "heading_does_not_fit_source_box",
            f"it refused as {refusal.reason!r}",
        )
    _require(
        not _moved(before, _digests(docs)),
        "a refused heading still changed the document",
    )

    # A body paragraph is not a heading, whatever its geometry reports.
    reason = minimal_repair.admits_heading(
        _issue("out_of_page", ("p7#1",)),
        docs, baseline, article_ir, frozenset(), CONFIG,
    )
    _require(
        reason == "heading_role_not_allowed",
        f"a body paragraph was admitted as a heading: {reason!r}",
    )
    return (
        "a heading that will not fit at the floor is refused whole, and a body "
        "paragraph is not admitted as a heading at all"
    )


def s3_region_lays_out_every_owned_member() -> str:
    docs, article_ir, baseline = fixture()
    before = _digests(docs)
    typesetter = BoundedFakeTypesetter()
    members = minimal_repair._retypeset_region(
        _issue("fragment_cluster", ("p7#1",)),
        docs, baseline, article_ir, typesetter, frozenset(), CONFIG,
    )
    refs = {target.physical_ref for target in members}
    _require(
        refs == {"p7#1", "p7#2"},
        f"the region laid out {sorted(refs)}, not its two owned body members",
    )
    for index, box in ((1, MEMBER_BOXES[0]), (2, MEMBER_BOXES[1])):
        laid = minimal_repair._box_tuple(docs.page[0].pdf_paragraph[index].box)
        _require(laid == box, f"member {index} was left in {laid}, not {box}")
    _require(
        _moved(before, _digests(docs)) == {"p1#1", "p1#2"},
        f"the region wrote {sorted(_moved(before, _digests(docs)))}",
    )
    return "every owned body member of the region is laid out again in its own box"


def s4_region_stays_inside_one_article() -> str:
    docs, article_ir, baseline = fixture()
    typesetter = BoundedFakeTypesetter()
    minimal_repair._retypeset_region(
        _issue("fragment_cluster", ("p7#1",)),
        docs, baseline, article_ir, typesetter, frozenset(), CONFIG,
    )
    _require(
        "p8#0" not in set(typesetter.laid_out),
        "the region reached into the second article",
    )
    # The chain members are the same article and the same page, and are still
    # not the region's to move: a chain is another action's business.
    _require(
        {"p7#3", "p7#4"}.isdisjoint(set(typesetter.laid_out)),
        "the region moved chain members",
    )
    narrow = minimal_repair.parse_repair_config(
        {
            **json.loads(
                (ROOT / "configs/repair_actions.json").read_text(encoding="utf-8")
            ),
            "retypeset_article_region": {
                "eligible_roles": [BODY_ROLE],
                "region_min_scale": 0.7,
                "region_min_scale_allowed_range": "0.4..1.0",
                "region_max_members": 1,
                "region_max_members_allowed_range": "1..40",
            },
        },
        "narrowed",
    )
    reason = minimal_repair.admits_region(
        _issue("fragment_cluster", ("p7#1",)),
        docs, baseline, article_ir, frozenset(), narrow,
    )
    _require(
        reason == "region_exceeds_member_ceiling",
        f"a region over its ceiling was admitted: {reason!r}",
    )
    return (
        "the region touches neither the second article nor the chain, and is "
        "refused when its member count is over the declared ceiling"
    )


def s5_region_refuses_whole() -> str:
    docs, article_ir, baseline = fixture()
    before = _digests(docs)
    # The second member is the one that will not fit, so a partial action would
    # leave the first one moved.
    typesetter = BoundedFakeTypesetter(refuse={"p7#2"})
    try:
        minimal_repair._retypeset_region(
            _issue("fragment_cluster", ("p7#1",)),
            docs, baseline, article_ir, typesetter, frozenset(), CONFIG,
        )
        raise AssertionError("a region with an unfittable member was accepted")
    except minimal_repair._RepairRefusalError as refusal:
        _require(
            refusal.reason == "region_member_does_not_fit",
            f"it refused as {refusal.reason!r}",
        )
    moved = _moved(before, _digests(docs))
    _require(
        moved == {"p1#1"},
        f"the refusal left {sorted(moved)} moved; the caller's transaction is "
        f"what puts them back, and this records exactly what it must undo",
    )
    return (
        "one unfittable member refuses the whole region, and what the attempt "
        "moved before refusing is exactly the members it had reached"
    )


def _chain_report(directory: Path, *, strategy: str, translation: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "chain_translation.report.json"
    path.write_text(
        json.dumps(
            {
                "chains": [
                    {
                        "chain_id": "chain-a",
                        "canonical_chain_id": "chain-a",
                        "strategy": strategy,
                        "translation": translation,
                        "merge": {
                            "chars": 41,
                            "member_chars": [20, 20],
                            "separators": ["", " "],
                            "dropped_hyphens": [],
                            "member_count": 2,
                        },
                        "members": [
                            {"runtime_source_ref": "p1#3", "chain_index": 0},
                            {"runtime_source_ref": "p1#4", "chain_index": 1},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _chain_issue(path: Path):
    return _issue(
        "chain_conservation",
        (),
        {"chain_id": "chain-a", "report_path": str(path), "violation_count": 1},
    )


TRANSLATION = "这是整条链的译文，一共有两个成员分别承担它的两半内容。"


def s6_chain_is_cut_again_and_conserved(work: Path) -> str:
    docs, article_ir, baseline = fixture()
    path = _chain_report(work / "s6", strategy="slot_tail_aligned", translation=TRANSLATION)
    typesetter = BoundedFakeTypesetter()
    targets = minimal_repair._reallocate_chain_cut(
        _chain_issue(path),
        docs, baseline, article_ir, typesetter, frozenset(), CONFIG,
        language="zh",
    )
    _require(len(targets) == 2, f"the chain came back with {len(targets)} members")
    pieces = [docs.page[0].pdf_paragraph[index].unicode for index in (3, 4)]
    _require(
        "".join(pieces) == TRANSLATION,
        f"the members do not join back to the translation: {pieces!r}",
    )
    _require(
        all(pieces),
        f"a member was left with no text: {pieces!r}",
    )
    for index, box in ((3, CHAIN_BOXES[0]), (4, CHAIN_BOXES[1])):
        laid = minimal_repair._box_tuple(docs.page[0].pdf_paragraph[index].box)
        _require(laid == box, f"chain member {index} was left in {laid}, not {box}")
    return (
        f"the chain is cut again one level down and the {len(TRANSLATION)} "
        f"characters are conserved exactly across its members"
    )


def s7_chain_refuses_whole(work: Path) -> str:
    # At the bottom of the cascade there is no level below to try.
    docs, article_ir, baseline = fixture()
    bottom = _chain_report(work / "s7-bottom", strategy="slot_capacity", translation=TRANSLATION)
    reason = minimal_repair.admits_chain_reallocation(
        _chain_issue(bottom), docs, baseline, article_ir, frozenset(), CONFIG
    )
    _require(
        reason == "chain_realloc_no_further_strategy",
        f"a chain at the bottom of the cascade was admitted: {reason!r}",
    )

    # A member that cannot hold its new piece takes the whole chain down.
    docs, article_ir, baseline = fixture()
    before = _digests(docs)
    path = _chain_report(work / "s7-overflow", strategy="slot_tail_aligned", translation=TRANSLATION)
    typesetter = BoundedFakeTypesetter(refuse={"p7#4"})
    try:
        minimal_repair._reallocate_chain_cut(
            _chain_issue(path),
            docs, baseline, article_ir, typesetter, frozenset(), CONFIG,
            language="zh",
        )
        raise AssertionError("a chain with an overflowing member was accepted")
    except minimal_repair._RepairRefusalError as refusal:
        _require(
            refusal.reason == "chain_realloc_member_overflow",
            f"it refused as {refusal.reason!r}",
        )
    _require(
        _moved(before, _digests(docs)) <= {"p1#3", "p1#4"},
        "the refused reallocation reached outside the chain",
    )

    # A finding about a chain the report does not carry is not a finding this
    # action can answer.
    docs, article_ir, baseline = fixture()
    missing = _issue(
        "chain_conservation",
        (),
        {"chain_id": "chain-absent", "report_path": str(path)},
    )
    reason = minimal_repair.admits_chain_reallocation(
        missing, docs, baseline, article_ir, frozenset(), CONFIG
    )
    _require(
        reason == "chain_not_in_report",
        f"an unknown chain was admitted: {reason!r}",
    )
    return (
        "the chain action refuses at the bottom of the cascade, refuses whole "
        "on an overflowing member, and refuses a chain it has no record of"
    )


def s8_nothing_outside_the_written_set_moves(work: Path) -> str:
    """Every action, measured paragraph by paragraph against what it wrote."""
    expected = {
        "contain_heading": {"p1#0"},
        "retypeset_article_region": {"p1#1", "p1#2"},
        "reallocate_chain_cut": {"p1#3", "p1#4"},
    }
    observed = {}

    docs, article_ir, baseline = fixture()
    before = _digests(docs)
    minimal_repair._contain_heading(
        _issue("out_of_page", ("p7#0",)),
        docs, baseline, article_ir, BoundedFakeTypesetter(), frozenset(), CONFIG,
    )
    observed["contain_heading"] = _moved(before, _digests(docs))

    docs, article_ir, baseline = fixture()
    before = _digests(docs)
    minimal_repair._retypeset_region(
        _issue("fragment_cluster", ("p7#1",)),
        docs, baseline, article_ir, BoundedFakeTypesetter(), frozenset(), CONFIG,
    )
    observed["retypeset_article_region"] = _moved(before, _digests(docs))

    docs, article_ir, baseline = fixture()
    before = _digests(docs)
    path = _chain_report(work / "s8", strategy="slot_tail_aligned", translation=TRANSLATION)
    minimal_repair._reallocate_chain_cut(
        _chain_issue(path),
        docs, baseline, article_ir, BoundedFakeTypesetter(), frozenset(), CONFIG,
        language="zh",
    )
    observed["reallocate_chain_cut"] = _moved(before, _digests(docs))

    for action, wrote in sorted(observed.items()):
        _require(
            wrote == expected[action],
            f"{action} wrote {sorted(wrote)}, not {sorted(expected[action])}; "
            f"a paragraph outside its own set was changed",
        )
    return (
        "each action writes exactly its own paragraphs; every other paragraph "
        "is byte for byte what it was"
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        claims = [
            ("S1", s1_contain_heading_pulls_a_title_back),
            ("S2", s2_contain_heading_refuses_whole),
            ("S3", s3_region_lays_out_every_owned_member),
            ("S4", s4_region_stays_inside_one_article),
            ("S5", s5_region_refuses_whole),
            ("S6", lambda: s6_chain_is_cut_again_and_conserved(work)),
            ("S7", lambda: s7_chain_refuses_whole(work)),
            ("S8", lambda: s8_nothing_outside_the_written_set_moves(work)),
        ]
        for name, claim in claims:
            try:
                print(f"{name}  OK  {claim()}")
            except AssertionError as error:
                print(f"{name}  FAIL  {error}")
                return 1
    print("spec_check_b12_t3: all claims hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
