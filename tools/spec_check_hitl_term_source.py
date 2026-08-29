"""Gate: a ruled term reaches the translator only if the source still says it.

The claim under test is that human decisions are checked against the source
document before they join the single constraint path the translation and
typesetting passes read. This script asserts both halves of that: the symbols
that carry the rule exist and are configured, and a real two-pass run keeps,
skips and accounts for ruled terms accordingly.

Run offline; no network, no PDF, no translator request.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from collections.abc import Callable
from inspect import signature
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.glossary import Glossary  # noqa: E402
from babeldoc.glossary import GlossaryEntry  # noqa: E402
from babeldoc.magazine import hitl  # noqa: E402
from babeldoc.magazine import line_split  # noqa: E402
from tests.minimal.test_hitl_export_apply import selected_fixture  # noqa: E402

PRESENT_TERM = "Katerina Markelova"
ABSENT_TERM = "Nobody Mentioned Anywhere"
CASE_FOLDED_TERM = "kATERINA    markelova"


class CheckError(AssertionError):
    """Raised when one assertion of this gate does not hold."""


def require(condition: object, detail: str) -> None:
    if not condition:
        raise CheckError(detail)


class ReviewPaths:
    """Point the review reader and writer at throwaway directories."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._saved: tuple[Path, Path] | None = None

    def __enter__(self) -> Path:
        self._saved = (hitl.SOURCE_REVIEWS_DIR, hitl.GENERATED_REVIEWS_DIR)
        source = self._root / "source-reviews"
        source.mkdir(parents=True, exist_ok=True)
        hitl.SOURCE_REVIEWS_DIR = source
        hitl.GENERATED_REVIEWS_DIR = self._root / "generated-reviews"
        return source

    def __exit__(self, *_exc: object) -> bool:
        assert self._saved is not None
        hitl.SOURCE_REVIEWS_DIR, hitl.GENERATED_REVIEWS_DIR = self._saved
        return False


def write_decisions(source: Path, sample: str, terms: dict[str, str]) -> Path:
    payload = {
        "sample": sample,
        "terms": terms,
        "page_kinds": {},
        "drop_caps": {},
    }
    path = source / f"{sample}.decisions.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def run_two_passes(tmp: Path, sample: str, terms: dict[str, str] | None):
    """One full offline HITL run, returning its config, state and report."""
    with ReviewPaths(tmp / sample) as source:
        if terms is not None:
            write_decisions(source, sample, terms)
        config, docs, article_ir = selected_fixture(tmp / sample, sample=sample)
        state = hitl.begin_run(config, docs)
        hitl.page_kind_pass(config, docs, state)
        report = hitl.before_translation(config, docs, article_ir, state)
    return config, state, report


def glossary_sources(config) -> set[str]:
    shared = config.shared_context_cross_split_part
    names = list(shared.user_glossaries)
    if shared.auto_extracted_glossary is not None:
        names.append(shared.auto_extracted_glossary)
    return {entry.source for glossary in names for entry in glossary.entries}


def decisions_glossary_names(config) -> list[str]:
    shared = config.shared_context_cross_split_part
    return [
        glossary.name
        for glossary in shared.user_glossaries
        if glossary.name.startswith(hitl.DECISIONS_GLOSSARY)
    ]


# --- symbol level ----------------------------------------------------------


def s1_absent_reason() -> str:
    require(
        hitl.ABSENT_FROM_SOURCE == "absent_from_source",
        f"ABSENT_FROM_SOURCE is {hitl.ABSENT_FROM_SOURCE!r}",
    )
    return "skipped reason constant is declared beside the scope reason"


def s2_match_rule_declared() -> str:
    rule = hitl.load_hitl_config()["term_source_match"]
    require(rule == "normalized_substring", f"term_source_match is {rule!r}")
    allowed = hitl.load_hitl_config()["term_source_match_allowed"]
    require(rule in allowed, f"{rule!r} is outside {allowed!r}")
    return f"match rule {rule!r} is config text, not a code literal"


def s3_unknown_rule_refused() -> str:
    raw = json.loads(hitl.CONFIG_PATH.read_text(encoding="utf-8"))
    raw["term_source_match"] = "levenshtein"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hitl.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        hitl.load_hitl_config.cache_clear()
        try:
            hitl.load_hitl_config(str(path))
        except hitl.HitlError:
            reason = "an undeclared match rule is refused at load"
        else:
            raise CheckError("load_hitl_config accepted an undeclared match rule")
        finally:
            hitl.load_hitl_config.cache_clear()
    return reason


def s4_export_terms_has_no_docs() -> str:
    parameters = signature(hitl.export_terms).parameters
    require("docs" not in parameters, f"export_terms still takes {tuple(parameters)}")
    require(
        "state" in parameters,
        f"export_terms does not read run state: {tuple(parameters)}",
    )
    return "export_terms reads the snapshot, never the rebuilt paragraphs"


def s5_state_carries_snapshot() -> str:
    fields = hitl.HitlRunState.__dataclass_fields__
    require("source_text_pages" in fields, "HitlRunState has no source_text_pages")
    return "the run state owns the one source snapshot"


def s6_review_format_unchanged() -> str:
    version = hitl.load_hitl_config()["review_format_version"]
    require(version == 3, f"review_format_version is {version!r}, expected 3")
    return "decisions file format is untouched, only the checking is new"


# --- end to end ------------------------------------------------------------


def e1_present_term_is_applied(tmp: Path) -> str:
    config, _state, report = run_two_passes(
        tmp, "PresentTerm", {PRESENT_TERM: "target"}
    )
    require(
        PRESENT_TERM in glossary_sources(config),
        f"{PRESENT_TERM!r} did not reach the frozen glossaries",
    )
    require(
        decisions_glossary_names(config) == [hitl.DECISIONS_GLOSSARY],
        f"decisions glossary missing: {decisions_glossary_names(config)}",
    )
    require(
        not [r for r in report["skipped"] if r["section"] == hitl.TERMS_SECTION],
        f"a present term was skipped: {report['skipped']}",
    )
    require(
        report["applied"]["terms"]["ruled"] == 1,
        f"applied terms record is {report['applied']['terms']!r}",
    )
    return "a term the source still carries reaches the translator's glossary"


def e2_absent_term_is_skipped(tmp: Path) -> str:
    config, _state, report = run_two_passes(tmp, "AbsentTerm", {ABSENT_TERM: "target"})
    require(
        ABSENT_TERM not in glossary_sources(config),
        f"{ABSENT_TERM!r} reached a glossary despite being absent from the source",
    )
    require(
        decisions_glossary_names(config) == [],
        f"an empty ruling still built a glossary: {decisions_glossary_names(config)}",
    )
    skipped = [r for r in report["skipped"] if r["section"] == hitl.TERMS_SECTION]
    require(len(skipped) == 1, f"expected one skipped term, got {skipped}")
    require(
        skipped[0]
        == {
            "section": hitl.TERMS_SECTION,
            "key": ABSENT_TERM,
            "page": None,
            "reason": hitl.ABSENT_FROM_SOURCE,
        },
        f"skipped record shape is {skipped[0]!r}",
    )
    require(
        report["passes"]["before_translation"],
        "an absent term stopped the second pass instead of being skipped",
    )
    return "a term the source never says is dropped per entry, run continues"


def e3_normalization(tmp: Path) -> str:
    config, _state, report = run_two_passes(
        tmp, "FoldedTerm", {CASE_FOLDED_TERM: "target"}
    )
    require(
        CASE_FOLDED_TERM in glossary_sources(config),
        "a term differing only in case and spacing was treated as absent",
    )
    require(
        not [r for r in report["skipped"] if r["section"] == hitl.TERMS_SECTION],
        f"case folded term was skipped: {report['skipped']}",
    )
    return "matching folds case and whitespace, as the declared rule says"


def line_structured_paragraph(
    lines: tuple[str, ...],
    faces: tuple[str, ...],
) -> il.PdfParagraph:
    """One paragraph typeset over measured lines, as line splitting expects it.

    The faces differ across lines because line splitting only rebuilds a
    paragraph whose styling is heterogeneous; the term under test straddles two
    lines that share the body face, which is the ordinary case.
    """
    characters = []
    for row, (text, face) in enumerate(zip(lines, faces, strict=True)):
        y = 20.0 + (len(lines) - row - 1) * 14.0
        style = il.PdfStyle(font_id=face, font_size=10.0)
        for column, glyph in enumerate(text):
            characters.append(
                il.PdfCharacter(
                    char_unicode=glyph,
                    box=il.Box(
                        10.0 + column * 3.0,
                        y,
                        10.0 + (column + 1) * 3.0,
                        y + 10.0,
                    ),
                    pdf_style=style,
                )
            )
    style = il.PdfStyle(font_id=faces[0], font_size=10.0)
    width = max(len(line) for line in lines) * 3.0
    return il.PdfParagraph(
        box=il.Box(10.0, 20.0, 10.0 + width, 20.0 + (len(lines) - 1) * 14.0 + 10.0),
        pdf_style=style,
        pdf_paragraph_composition=[
            il.PdfParagraphComposition(
                pdf_same_style_characters=il.PdfSameStyleCharacters(
                    pdf_style=style,
                    pdf_character=characters,
                )
            )
        ],
        unicode="".join(lines),
        debug_id="split-probe",
        layout_label="plain text",
        xobj_id=-1,
    )


def e4_term_across_a_split_point(tmp: Path) -> str:
    """The snapshot predates line splitting, so a split term is still found."""
    sample = "SplitTerm"
    with ReviewPaths(tmp / sample):
        config, docs, _article_ir = selected_fixture(tmp / sample, sample=sample)
        config.magazine_line_structure = True
        config.min_text_length = 1
        config.split_strategy = None
        lines = ("the profile of Katerina ", "Markelova ends ", "in italics here")
        page = docs.page[0]
        # Line splitting only rebuilds paragraphs on a page whose kind declares
        # line structure; on such a page the term below spans two of its lines.
        page.page_kind = "toc"
        page.pdf_paragraph = [
            line_structured_paragraph(lines, ("body", "body", "italic"))
        ]
        shared = config.shared_context_cross_split_part
        shared.raw_extracted_terms = [(PRESENT_TERM, "target")]

        state = hitl.begin_run(config, docs)
        hitl.page_kind_pass(config, docs, state)
        require(
            line_split.enabled(config),
            "line splitting is disabled, this check would prove nothing",
        )
        line_split.apply(config, hitl.labeled_pages(docs))
        require(
            len(page.pdf_paragraph) > 1,
            "line splitting did not rebuild the paragraph, check is inconclusive",
        )
        post_split_text = "\n".join(
            paragraph.unicode or "" for paragraph in page.pdf_paragraph
        )
        require(
            PRESENT_TERM not in post_split_text,
            "the term survived splitting intact, check is inconclusive",
        )
        require(
            hitl.first_source_page(state, PRESENT_TERM) == 7,
            "a term straddling a split point was judged absent from the source",
        )
        rows = hitl.export_terms(config, state)
        row = next(row for row in rows if row["source"] == PRESENT_TERM)
        require(
            row["first_page"] == 7,
            f"export_terms reported first_page {row['first_page']!r}",
        )
    return "a term broken across a split point is still located, on its real page"


def e5_conservation(tmp: Path) -> str:
    terms = {PRESENT_TERM: "target", ABSENT_TERM: "target", "Yang Sha": "target"}
    _config, state, report = run_two_passes(tmp, "MixedTerms", terms)
    conservation = report["applied"]["terms_conservation"]
    require(
        conservation == {"ruled": 3, "applied": 2, "skipped": 1},
        f"terms_conservation is {conservation!r}",
    )
    ruled = len(state.decisions.terms)
    applied = len(report["applied"]["terms"]["entries"])
    skipped = len(
        [r for r in report["skipped"] if r["section"] == hitl.TERMS_SECTION]
    )
    require(
        ruled == applied + skipped == 3,
        f"{ruled} ruled but {applied} applied and {skipped} skipped",
    )
    require(
        conservation == {"ruled": ruled, "applied": applied, "skipped": skipped},
        "the recorded conservation disagrees with the report it summarises",
    )
    return "every ruled term is either applied or named as skipped, never lost"


def e6_decisions_file_is_read_only(tmp: Path) -> str:
    sample = "ReadOnly"
    with ReviewPaths(tmp / sample) as source:
        path = write_decisions(source, sample, {PRESENT_TERM: "target"})
        before = path.read_bytes()
        config, docs, article_ir = selected_fixture(tmp / sample, sample=sample)
        state = hitl.begin_run(config, docs)
        hitl.page_kind_pass(config, docs, state)
        report = hitl.before_translation(config, docs, article_ir, state)
        after = path.read_bytes()
    require(before == after, "the decisions file changed during the run")
    digest = hashlib.sha256(before).hexdigest()
    require(
        report["decisions_sha256"] == digest,
        f"report records {report['decisions_sha256']!r}, file hashes to {digest!r}",
    )
    return "the report carries the digest of the bytes the run actually read"


def e7_rollback_restores_skipped(tmp: Path) -> str:
    sample = "Rollback"

    class SentinelError(Exception):
        pass

    original = hitl._freeze_glossaries
    with ReviewPaths(tmp / sample) as source:
        write_decisions(
            source, sample, {PRESENT_TERM: "target", ABSENT_TERM: "target"}
        )
        config, docs, article_ir = selected_fixture(tmp / sample, sample=sample)
        shared = config.shared_context_cross_split_part
        shared.user_glossaries.append(
            Glossary("existing", [GlossaryEntry("existing source", "existing target")])
        )
        state = hitl.begin_run(config, docs)
        hitl.page_kind_pass(config, docs, state)
        after_first_pass = copy.deepcopy(state.report["skipped"])

        def explode(_translation_config):
            raise SentinelError("injected after the terms were applied")

        hitl._freeze_glossaries = explode
        try:
            hitl.before_translation(config, docs, article_ir, state)
        except SentinelError:
            pass
        else:
            raise CheckError("the injected failure did not propagate")
        finally:
            hitl._freeze_glossaries = original

    require(
        state.report["skipped"] == after_first_pass,
        f"skipped list kept second-pass records: {state.report['skipped']!r}",
    )
    require(
        "terms_conservation" not in state.report["applied"],
        "a rolled back run left its conservation record behind",
    )
    require(
        decisions_glossary_names(config) == [],
        f"a rolled back run left {decisions_glossary_names(config)!r} behind",
    )
    require(
        [glossary.name for glossary in config.shared_context_cross_split_part.user_glossaries]
        == ["existing"],
        "rollback did not restore the pre-existing glossaries",
    )
    return "a failure after apply leaves neither glossary nor skipped residue"


def e8_no_decisions_file(tmp: Path) -> str:
    config, state, report = run_two_passes(tmp, "NoDecisions", None)
    require(state.decisions is None, "a decisions file appeared from nowhere")
    require(
        report["applied"]["terms"] is None,
        f"applied terms is {report['applied']['terms']!r}",
    )
    require(report["skipped"] == [], f"skipped is {report['skipped']!r}")
    require(
        report["applied"]["terms_conservation"] == {
            "ruled": 0,
            "applied": 0,
            "skipped": 0,
        },
        f"terms_conservation is {report['applied']['terms_conservation']!r}",
    )
    require(
        "decisions_sha256" not in report,
        "a run without a decisions file recorded a digest",
    )
    require(
        decisions_glossary_names(config) == [],
        "a run without decisions built a decisions glossary",
    )
    return "an unruled run behaves exactly as it did before this check existed"


SYMBOL_CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("S1", s1_absent_reason),
    ("S2", s2_match_rule_declared),
    ("S3", s3_unknown_rule_refused),
    ("S4", s4_export_terms_has_no_docs),
    ("S5", s5_state_carries_snapshot),
    ("S6", s6_review_format_unchanged),
)

RUN_CHECKS: tuple[tuple[str, Callable[[Path], str]], ...] = (
    ("E1", e1_present_term_is_applied),
    ("E2", e2_absent_term_is_skipped),
    ("E3", e3_normalization),
    ("E4", e4_term_across_a_split_point),
    ("E5", e5_conservation),
    ("E6", e6_decisions_file_is_read_only),
    ("E7", e7_rollback_restores_skipped),
    ("E8", e8_no_decisions_file),
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
    print(
        f"\n{len(SYMBOL_CHECKS) + len(RUN_CHECKS) - failures}"
        f"/{len(SYMBOL_CHECKS) + len(RUN_CHECKS)} checks passed"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
