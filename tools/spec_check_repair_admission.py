"""Gate: a repair run's one action is chosen from the candidates it may act on.

A run gets one repair action.  Before this gate's subject existed, the run
ranked every finding the detector reported, took the first, and only then asked
whether that finding could be acted on at all; a finding that ranked first and
could never be acted on took the whole run down with it while an actionable
finding waited behind it in the same list.  Both shipped samples ended that
way, and the second of them had an actionable candidate one place further down.

So the question "may this be acted on" moved in front of the ranking.  That is
only sound while the question is answerable without doing anything: an
admission that writes to the document, or that spends a translator request, is
not a filter but a first action under another name, and asking it of every
candidate would spend the budget many times over.  S3 and S4 are the checks
that hold it to that, and they are the reason the rest of the gate means
anything.

Six claims:

S1  An owned paragraph is not orphan text, whatever label it carries, and the
    predicate says so by the same name the action used to refuse it by.
S2  A labelled orphan with no owner and residue over the floor is admitted.
S3  Asking the orphan predicate changes no paragraph on the document: not its
    text, not its box, not its style.
S4  The same, for the refit predicate.
S5  A run whose every candidate is refused is reported as such, by a name of
    its own, and spends no action and no request.  "Nothing was actionable" is
    not "the detector reported nothing" and the two must not share a word.
E6  The sample shape: an inadmissible finding that sorts first and an
    admissible one behind it.  The admissible one is acted on, and the finding
    that was passed over is named in the report together with why.

The fixtures are the ones the repair suite already runs on, imported rather
than rebuilt, so this gate and that suite cannot drift apart in what they think
a repairable document looks like.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine import fixed_assets  # noqa: E402
from babeldoc.magazine import minimal_repair  # noqa: E402
from tests.minimal.test_one_repair import make_issue  # noqa: E402
from tests.minimal.test_one_repair import repair_fixture  # noqa: E402
from tests.minimal.test_one_repair import run_repair  # noqa: E402

# The fixture's paragraph 0 is claimed by article-a; paragraph 2 is the
# fallback line no article claims.  Both live on physical page 7.
OWNED_REF = "p7#0"
ORPHAN_REF = "p7#2"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _fixture(*, owned_label: str | None = None):
    docs, article_ir, baseline, flow = repair_fixture()
    if owned_label is not None:
        docs.page[0].pdf_paragraph[0].layout_label = owned_label
    flow_refs = minimal_repair._flow_refs(flow, article_ir)
    return docs, article_ir, baseline, flow_refs


def _translation_config():
    return SimpleNamespace(lang_out="zh", translator=None)


def _document_state(docs) -> list[tuple]:
    """Everything the two predicates are forbidden to touch, per paragraph."""
    state = []
    for page in docs.page:
        for paragraph in page.pdf_paragraph or ():
            style = minimal_repair._paragraph_style(paragraph)
            state.append(
                (
                    paragraph.debug_id,
                    paragraph.unicode,
                    minimal_repair._box_tuple(paragraph.box),
                    None if style is None else fixed_assets.content_digest(style),
                    fixed_assets.content_digest(paragraph),
                )
            )
    return state


def s1_owned_text_is_not_an_orphan() -> str:
    docs, article_ir, baseline, flow_refs = _fixture(owned_label="title")
    issue = make_issue(
        "untranslated_residue", (OWNED_REF,), minimal_repair.TRANSLATE_ORPHAN
    )
    reason = minimal_repair.admits_orphan(
        issue,
        docs,
        baseline,
        article_ir,
        _translation_config(),
        flow_refs,
        minimal_repair.load_repair_config(),
    )
    _require(
        reason == "orphan_is_canonical_article_text",
        f"an owned title was refused as {reason!r}",
    )
    return "an owned title is refused as canonical article text"


def s2_labelled_orphan_is_admitted() -> str:
    docs, article_ir, baseline, flow_refs = _fixture()
    issue = make_issue(
        "untranslated_residue", (ORPHAN_REF,), minimal_repair.TRANSLATE_ORPHAN
    )
    paragraph = docs.page[0].pdf_paragraph[2]
    _require(
        paragraph.layout_label == "fallback_line",
        f"the fixture orphan carries {paragraph.layout_label!r}",
    )
    reason = minimal_repair.admits_orphan(
        issue,
        docs,
        baseline,
        article_ir,
        _translation_config(),
        flow_refs,
        minimal_repair.load_repair_config(),
    )
    _require(reason is None, f"the fixture orphan was refused as {reason!r}")
    return "an unowned fallback line over the residue floor is admitted"


def s3_orphan_predicate_writes_nothing() -> str:
    docs, article_ir, baseline, flow_refs = _fixture()
    config = minimal_repair.load_repair_config()
    before = _document_state(docs)
    for ref in (OWNED_REF, ORPHAN_REF, "p7#3", "p7#4", "p7#5", "p7#99"):
        minimal_repair.admits_orphan(
            make_issue(
                "untranslated_residue", (ref,), minimal_repair.TRANSLATE_ORPHAN
            ),
            docs,
            baseline,
            article_ir,
            _translation_config(),
            flow_refs,
            config,
        )
    _require(_document_state(docs) == before, "the orphan predicate wrote to the page")
    return "the orphan predicate leaves text, box and style untouched"


def s4_refit_predicate_writes_nothing() -> str:
    docs, article_ir, baseline, flow_refs = _fixture()
    config = minimal_repair.load_repair_config()
    before = _document_state(docs)
    cases = (
        ("out_of_page", (OWNED_REF,)),
        ("out_of_page", ("p7#3",)),
        ("out_of_page", ("p7#5",)),
        ("text_text_collision", ("p7#0", "p8#0")),
        ("text_text_collision", ("p7#0", "p7#1")),
    )
    for kind, refs in cases:
        minimal_repair.admits_refit(
            make_issue(kind, refs, minimal_repair.REFIT_OWNED),
            docs,
            baseline,
            article_ir,
            flow_refs,
            config,
        )
    _require(_document_state(docs) == before, "the refit predicate wrote to the page")
    return "the refit predicate leaves text, box and style untouched"


def s5_a_wholly_refused_run_says_so(tmp: Path) -> str:
    chain = make_issue("out_of_page", ("p7#3",), minimal_repair.REFIT_OWNED)
    result, _docs, translator, typesetter, callback, _before = run_repair(
        tmp, "refused", [chain]
    )
    record = result.record
    _require(
        record["reason"] == "all_candidates_refused",
        f"a wholly refused run reported {record['reason']!r}",
    )
    _require(record["reason"] != "no_issues", "refusal and silence share a name")
    _require(record["selected"] is None, "a refused run still selected an action")
    _require(
        record["action_count"] == 0 and record["applied_count"] == 0,
        "a refused run counted an action",
    )
    _require(record["translator_requests"] == 0, "a refused run spent a request")
    _require(
        translator.calls == callback.calls == typesetter.calls == [],
        "a refused run reached the translator, detector or typesetter",
    )
    _require(
        [row["reason"] for row in record["filtered_candidates"]] == ["chain_member"],
        f"the refusal was not named: {record['filtered_candidates']}",
    )
    return "a run with no admissible candidate is named, and spends nothing"


def e6_an_admissible_candidate_behind_a_refused_one(tmp: Path) -> str:
    owned = make_issue(
        "untranslated_residue", (OWNED_REF,), minimal_repair.TRANSLATE_ORPHAN
    )
    orphan = make_issue(
        "untranslated_residue", (ORPHAN_REF,), minimal_repair.TRANSLATE_ORPHAN
    )
    _require(
        owned.severity == orphan.severity and owned.sort_key() < orphan.sort_key(),
        "the sample shape needs the refused candidate to sort first",
    )
    result, docs, translator, _typesetter, _callback, _before = run_repair(
        tmp, "passed-over", [owned, orphan]
    )
    record = result.record
    _require(
        record["selected"] == minimal_repair.TRANSLATE_ORPHAN,
        f"the run selected {record['selected']!r}",
    )
    _require(
        record["target"]["physical_ref"] == ORPHAN_REF,
        f"the run acted on {record['target']}",
    )
    _require(
        record["filtered_candidates"]
        == [
            {
                "id": owned.id,
                "kind": "untranslated_residue",
                "action": minimal_repair.TRANSLATE_ORPHAN,
                "reason": "orphan_is_canonical_article_text",
            }
        ],
        f"the passed-over candidate was not reported: {record['filtered_candidates']}",
    )
    _require(len(translator.calls) == 1, "the run spent more than one request")
    _require(
        docs.page[0].pdf_paragraph[0].unicode == "目标正文",
        "the owned text moved",
    )
    return "the admissible candidate behind a refused one is the one acted on"


SYMBOL_CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("S1", s1_owned_text_is_not_an_orphan),
    ("S2", s2_labelled_orphan_is_admitted),
    ("S3", s3_orphan_predicate_writes_nothing),
    ("S4", s4_refit_predicate_writes_nothing),
)

RUN_CHECKS: tuple[tuple[str, Callable[[Path], str]], ...] = (
    ("S5", s5_a_wholly_refused_run_says_so),
    ("E6", e6_an_admissible_candidate_behind_a_refused_one),
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
