"""Minimal, sample-independent source-to-target coverage evidence.

The inventory is frozen after structural processing, while source paragraphs
still carry their original text and geometry.  Translation outcomes are joined
later from the two existing producer reports; this module does not influence
which paragraphs are translated.

Conservation (B17)
------------------

Every frozen source has to end the run in exactly one of four states: owned by
a translation path, preserved on purpose, skipped for a reason this module can
name, or listed. The naming is a closed vocabulary -- ``SKIP_REASONS`` -- and a
paragraph that holds source-script text, was translated by nobody, and fits no
reason in the vocabulary goes to ``unowned_sources``. A non-empty list is a
defect signal, recorded rather than raised, because the ledger's job is to make
a hole visible, not to decide whether the hole was acceptable.

The ledger covers the paragraph census. Ink that never became a paragraph -- a
figure, an xobject, text fused into a formula object -- is owned by the fixed
asset inventory and is protected by construction, not accounted here.

The snapshot also carries a byte-exact guard: the sha256 of every paragraph's
``unicode`` at freeze time. A translation path that binds a paragraph whose
text has drifted since the freeze is enqueueing something the inventory never
saw, and the guard fails closed at the enqueue site rather than letting the
drifted text reach a model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from babeldoc.format.pdf.document_il.utils.layout_helper import (
    get_char_unicode_string,
)
from babeldoc.format.pdf.document_il.utils.paragraph_helper import is_cid_paragraph
from babeldoc.format.pdf.document_il.utils.paragraph_helper import (
    is_placeholder_only_paragraph,
)
from babeldoc.magazine import drop_cap_intent
from babeldoc.magazine import line_split
from babeldoc.magazine.detectors.base import HAN_SCRIPT
from babeldoc.magazine.detectors.base import LATIN_SCRIPT
from babeldoc.magazine.detectors.base import script_counts

REPORT_NAME = "demo_coverage.report.json"
SCHEMA_VERSION = "demo-coverage.v1"
# ``display_glyph`` is the label the display glyph pass pins fixed ink under
# (fixed_assets.DISPLAY_GLYPH_LABEL): preserved on purpose, like the marks.
_PRESERVE_ROLES = frozenset({"brand", "credit", "folio", "display_glyph"})

# The closed vocabulary of reasons a source may end untranslated without being
# a hole in the ledger. Order is precedence: the first reason that holds names
# the row. Anything untranslated that earns none of these is unowned.
SKIP_REASONS = (
    "furniture_withheld",
    "vertical",
    "cid_encoding",
    "placeholder_only",
    "bilingual_companion_visible",
    "no_source_script",
    "below_length_floor",
)

# The closed vocabulary of companion visibility verdicts.  Only ``visible``
# earns the bilingual exemption; every other verdict fails open to
# translation, because an untranslated label is worse than a doubled one.
COMPANION_VISIBLE = "visible"
COMPANION_OUTSIDE_PAGE_BODY = "outside_page_body"
COMPANION_NO_INK = "no_ink_evidence"
COMPANION_UNRENDERABLE = "unrenderable"
COMPANION_VISIBILITIES = (
    COMPANION_VISIBLE,
    COMPANION_OUTSIDE_PAGE_BODY,
    COMPANION_NO_INK,
    COMPANION_UNRENDERABLE,
)


def _source_script(lang_in: str) -> str:
    """Which script bucket carries this run's source language.

    Mirrors ``residue_directions`` in configs/detectors.json read from the
    other end: that table names the script a *target* would show as residue,
    which is the script its source was written in.
    """
    return HAN_SCRIPT if str(lang_in or "").lower().startswith("zh") else LATIN_SCRIPT


def wholly_scripted(text: str) -> str | None:
    """The one script bucket a text's letters all belong to, or None.

    Digits, punctuation and spacing take no part; a text whose letters split
    across buckets, or that has no letters at all, belongs to no one bucket.
    """
    counts = script_counts(text or "")
    han, latin = counts[HAN_SCRIPT], counts[LATIN_SCRIPT]
    if han and not latin:
        return HAN_SCRIPT
    if latin and not han:
        return LATIN_SCRIPT
    return None


def _boxes_intersect(left, right) -> bool:
    return (
        min(left[2], right[2]) > max(left[0], right[0])
        and min(left[3], right[3]) > max(left[1], right[1])
    )


def cross_script_companions(paragraph, neighbours) -> list:
    """Every other-script double sharing this paragraph's ink area."""
    own_script = wholly_scripted(getattr(paragraph, "unicode", "") or "")
    if own_script is None:
        return []
    try:
        own_box = _box(getattr(paragraph, "box", None))
    except ValueError:
        return []
    if own_box is None:
        return []
    companions = []
    for other in neighbours:
        if other is paragraph:
            continue
        other_script = wholly_scripted(getattr(other, "unicode", "") or "")
        if other_script is None or other_script == own_script:
            continue
        try:
            other_box = _box(getattr(other, "box", None))
        except ValueError:
            continue
        if other_box is not None and _boxes_intersect(own_box, other_box):
            companions.append(other)
    return companions


def companion_visibility(companion, page, translation_config) -> tuple[str, dict]:
    """Whether one companion demonstrably renders as visible ink.

    Three criteria, decided from standing facts.  Inside the page body is a
    geometric fact against the crop box.  Ink and non-occlusion are one
    rendering fact: the source page's own pixels over the companion's box --
    a companion drawn in background colour, wholly covered by an opaque
    object, or clipped away leaves no non-background pixels there, whatever
    the IL says about its operators.  Whenever visibility cannot be
    established (no readable source file, a partial-page run whose page
    numbers do not match the file, a degenerate box), the verdict is
    ``unrenderable`` and the caller must not exempt.
    """
    evidence: dict = {
        "companion_debug_id": getattr(companion, "debug_id", None),
        "companion_excerpt": (getattr(companion, "unicode", "") or "")[:40],
    }
    try:
        box = _box(getattr(companion, "box", None))
    except ValueError:
        box = None
    if box is None:
        return COMPANION_UNRENDERABLE, evidence
    evidence["companion_box"] = list(box)
    crop = getattr(getattr(page, "cropbox", None), "box", None)
    if crop is not None:
        tolerance = 1.0
        inside = (
            float(crop.x) - tolerance <= box[0]
            and float(crop.y) - tolerance <= box[1]
            and box[2] <= float(crop.x2) + tolerance
            and box[3] <= float(crop.y2) + tolerance
        )
        if not inside:
            evidence["cropbox"] = [
                float(crop.x), float(crop.y), float(crop.x2), float(crop.y2)
            ]
            return COMPANION_OUTSIDE_PAGE_BODY, evidence
    if getattr(translation_config, "page_ranges", None):
        # A subset run renders from a file whose page numbers no longer
        # match the IL's; a wrong region proves nothing.
        return COMPANION_UNRENDERABLE, evidence
    input_file = getattr(translation_config, "input_file", None)
    page_number = getattr(page, "page_number", None)
    if not input_file or page_number is None:
        return COMPANION_UNRENDERABLE, evidence
    from babeldoc.magazine.short_unit import load_short_unit_config

    try:
        config = load_short_unit_config()
        min_fraction = config.companion_ink_min_fraction
        zoom = config.companion_render_zoom
    except Exception:
        return COMPANION_UNRENDERABLE, evidence
    try:
        import pymupdf

        with pymupdf.open(str(input_file)) as source:
            source_page = source[int(page_number)]
            height = float(source_page.mediabox.y1)
            clip = pymupdf.Rect(
                box[0], height - box[3], box[2], height - box[1]
            )
            pix = source_page.get_pixmap(
                matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False
            )
        if pix.width < 2 or pix.height < 2:
            return COMPANION_UNRENDERABLE, evidence
        stride = pix.n
        samples = pix.samples
        counts: dict[bytes, int] = {}
        total = pix.width * pix.height
        for offset in range(0, total * stride, stride):
            pixel = bytes(samples[offset : offset + stride])
            counts[pixel] = counts.get(pixel, 0) + 1
        modal = max(counts.values())
        ink_fraction = 1.0 - (modal / total)
    except Exception:
        return COMPANION_UNRENDERABLE, evidence
    evidence["ink_fraction"] = round(ink_fraction, 4)
    evidence["ink_min_fraction"] = min_fraction
    if ink_fraction >= min_fraction:
        return COMPANION_VISIBLE, evidence
    return COMPANION_NO_INK, evidence


def visible_cross_script_twin(
    paragraph, neighbours, page, translation_config
) -> tuple[bool, dict | None]:
    """The bilingual exemption, now conditional on a visible companion.

    Returns ``(exempt, evidence)``.  Exempt only when at least one
    other-script double demonstrably renders -- the page already shows the
    same label in the target reader's script.  A companion whose visibility
    cannot be proven does not exempt: the unit stays on the translation
    path, because an untranslated label harms more than a doubled one.
    """
    companions = cross_script_companions(paragraph, neighbours)
    if not companions:
        return False, None
    last_evidence: dict | None = None
    for companion in companions:
        verdict, evidence = companion_visibility(
            companion, page, translation_config
        )
        evidence["visibility"] = verdict
        if verdict == COMPANION_VISIBLE:
            return True, evidence
        last_evidence = evidence
    return False, last_evidence


def cross_script_twin(paragraph, neighbours) -> bool:
    """Whether this paragraph shares its ink area with its other-script double.

    The shape of a bilingual masthead: the page prints one label in two
    languages on one spot (fd's contents header sets a Han label over its
    own English rendering). The half written in the run's source script is
    already accompanied by its target-language text, so translating it would
    say the same thing twice on the same ink. The test is symmetric and
    direction-free: one wholly-scripted box intersecting a wholly-scripted
    box of the other bucket.
    """
    own_script = wholly_scripted(getattr(paragraph, "unicode", "") or "")
    if own_script is None:
        return False
    try:
        own_box = _box(getattr(paragraph, "box", None))
    except ValueError:
        return False
    if own_box is None:
        return False
    for other in neighbours:
        if other is paragraph:
            continue
        other_script = wholly_scripted(getattr(other, "unicode", "") or "")
        if other_script is None or other_script == own_script:
            continue
        try:
            other_box = _box(getattr(other, "box", None))
        except ValueError:
            continue
        if other_box is not None and _boxes_intersect(own_box, other_box):
            return True
    return False


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _box(box) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    values = tuple(float(getattr(box, name)) for name in ("x", "y", "x2", "y2"))
    if values[0] > values[2] or values[1] > values[3]:
        raise ValueError("coverage source box is not ordered")
    return values


def _role(paragraph, unit, article_role: str | None) -> str:
    label = str(getattr(paragraph, "layout_label", "") or "").strip().lower()
    if label in _PRESERVE_ROLES:
        return label
    if unit is not None:
        return unit.record_kind
    if article_role:
        return article_role
    if label in {"plain text", "paragraph", "paragraph_hybrid", "text"}:
        return "body"
    return label or "body"


@dataclass(frozen=True, slots=True)
class FrozenCoverageItem:
    runtime_source_ref: str
    source_ref: str
    physical_page: int
    role: str
    source_text_sha256: str
    source_box: tuple[float, float, float, float] | None
    preserve_candidate: bool
    chain_member: bool
    # Measurements, not judgments: which script bucket the frozen text holds
    # and what standing traits the paragraph carried at freeze time. The
    # direction-dependent judgment (which bucket is "the source script") is
    # taken at finalize, where the run's languages are known.
    han_chars: int = 0
    latin_chars: int = 0
    text_length: int = 0
    skip_traits: tuple[str, ...] = ()


@dataclass(slots=True)
class CoverageSnapshot:
    """Frozen source inventory plus identity-based ref lookup for trackers."""

    items: tuple[FrozenCoverageItem, ...]
    _refs_by_object: dict[int, tuple[str, str]]
    _unicode_sha_by_object: dict[int, str] = field(default_factory=dict)
    _chars_sha_by_object: dict[int, str] = field(default_factory=dict)

    def source_refs_for(self, paragraph) -> tuple[str, str] | None:
        """Return ``(physical source ref, runtime source ref)`` for a paragraph."""
        return self._refs_by_object.get(id(paragraph))

    def refreeze_source(self, paragraph) -> None:
        """Accept one sanctioned pre-translation rewrite of a frozen source.

        The drop-cap apply channel merges a visual initial into its owner --
        or empties the standalone holder it came from -- before translation:
        a recorded, transactional rewrite of text this ledger froze earlier.
        The guard's shas follow the sanctioned text so that everything after
        this point stays protected; the frozen item keeps naming the
        original text it froze, because the ledger reports what the source
        page said, not what a pass rewrote it into.
        """
        identity = id(paragraph)
        if identity not in self._unicode_sha_by_object:
            return
        self._unicode_sha_by_object[identity] = _sha256(
            str(getattr(paragraph, "unicode", "") or "")
        )
        self._chars_sha_by_object[identity] = _sha256(
            get_char_unicode_string(line_split.paragraph_characters(paragraph))
        )

    def assert_source_unchanged(self, paragraph) -> None:
        """Fail closed when a paragraph's text drifted since the freeze.

        Called at the enqueue sites. A paragraph the snapshot never froze is
        not this guard's question -- the ref binding above it already raises
        for that -- so an unknown identity passes through.

        One rewrite is sanctioned: the per-paragraph fallback re-derives
        ``unicode`` from the paragraph's own characters before retrying
        (il_translator.translate_paragraph, use_as_fallback), and a CJK page
        renders fullwidth punctuation over ASCII character codes, so the
        derived text can differ from the finder's. The characters are the
        ground truth (the B16 lesson), so a current text that equals the
        text derived from an unchanged character stream passes; anything
        else -- a foreign value, a truncation, a tampered stream -- fails.
        """
        frozen = self._unicode_sha_by_object.get(id(paragraph))
        if frozen is None:
            return
        text = str(getattr(paragraph, "unicode", "") or "")
        if _sha256(text) == frozen:
            return
        derived = get_char_unicode_string(
            line_split.paragraph_characters(paragraph)
        )
        if (
            text == derived
            and _sha256(derived) == self._chars_sha_by_object.get(id(paragraph))
        ):
            return
        refs = self._refs_by_object.get(id(paragraph))
        raise ValueError(
            "translation source drifted from the frozen coverage inventory: "
            f"{refs[0] if refs else '<unbound>'} "
            f"(now {len(text)} chars, type {type(getattr(paragraph, 'unicode', None)).__name__}: "
            f"{text[:60]!r})"
        )


def _skip_traits(
    paragraph,
    furniture_plan,
    page_paragraphs,
    page=None,
    translation_config=None,
) -> tuple[str, ...]:
    """The standing reasons this paragraph would not be enqueued, at freeze."""
    traits: list[str] = []
    if furniture_plan is not None and furniture_plan.withholds(
        getattr(paragraph, "debug_id", None)
    ):
        traits.append("furniture_withheld")
    if getattr(paragraph, "vertical", False):
        traits.append("vertical")
    if is_cid_paragraph(paragraph):
        traits.append("cid_encoding")
    # The helper reads an empty composition list as "nothing but placeholders";
    # a paragraph with no composition at all holds no formula, so ask only
    # where there is a composition to ask about.
    if getattr(
        paragraph, "pdf_paragraph_composition", None
    ) and is_placeholder_only_paragraph(paragraph):
        traits.append("placeholder_only")
    exempt, _evidence = visible_cross_script_twin(
        paragraph, page_paragraphs, page, translation_config
    )
    if exempt:
        traits.append("cross_script_twin_visible")
    return tuple(traits)


def freeze(
    _docs,
    article_document_ir,
    labeled_pages,
    furniture_plan=None,
    translation_config=None,
) -> CoverageSnapshot:
    """Freeze source text, boxes, roles and both ref namespaces."""
    article_elements = {
        element.source_ref: element
        for article in article_document_ir.articles
        for element in article.elements
    }
    chain_refs = set(article_document_ir.by_chain_member)
    items: list[FrozenCoverageItem] = []
    refs_by_object: dict[int, tuple[str, str]] = {}
    unicode_sha_by_object: dict[int, str] = {}
    chars_sha_by_object: dict[int, str] = {}
    seen_physical: set[str] = set()

    for runtime_page, (physical_page, page) in enumerate(labeled_pages, start=1):
        physical_index = 0
        for runtime_index, paragraph in enumerate(page.pdf_paragraph or ()):
            if line_split.is_debug_overlay(paragraph):
                continue
            runtime_ref = f"p{runtime_page}#{runtime_index}"
            unit = line_split.source_unit(paragraph, physical_page)
            physical_ref = (
                unit.source_ref
                if unit is not None
                else f"p{physical_page}#{physical_index}"
            )
            physical_index += 1
            if physical_ref in seen_physical:
                raise ValueError(f"coverage source ref is not unique: {physical_ref}")
            seen_physical.add(physical_ref)

            element = article_elements.get(runtime_ref)
            text = (
                unit.source_text
                if unit is not None
                else str(getattr(paragraph, "unicode", "") or "")
            )
            source_box = (
                unit.source_box
                if unit is not None
                else (
                    element.source_box
                    if element is not None and element.source_box is not None
                    else _box(getattr(paragraph, "box", None))
                )
            )
            role = _role(
                paragraph,
                unit,
                None if element is None else element.role,
            )
            chain_member = runtime_ref in chain_refs or bool(
                getattr(paragraph, "chain_id", None)
            )
            if chain_member:
                role = "chain"
            preserve = role in _PRESERVE_ROLES or bool(
                unit is not None and unit.fixed_companion
            )
            scripts = script_counts(text)
            item = FrozenCoverageItem(
                runtime_source_ref=runtime_ref,
                source_ref=physical_ref,
                physical_page=physical_page,
                role=role,
                source_text_sha256=_sha256(text),
                source_box=source_box,
                preserve_candidate=preserve,
                chain_member=chain_member,
                han_chars=scripts[HAN_SCRIPT],
                latin_chars=scripts[LATIN_SCRIPT],
                text_length=len(text),
                skip_traits=_skip_traits(
                    paragraph,
                    furniture_plan,
                    page.pdf_paragraph or (),
                    page=page,
                    translation_config=translation_config,
                ),
            )
            items.append(item)
            refs_by_object[id(paragraph)] = (physical_ref, runtime_ref)
            unicode_sha_by_object[id(paragraph)] = _sha256(
                str(getattr(paragraph, "unicode", "") or "")
            )
            chars_sha_by_object[id(paragraph)] = _sha256(
                get_char_unicode_string(line_split.paragraph_characters(paragraph))
            )

    return CoverageSnapshot(
        tuple(items), refs_by_object, unicode_sha_by_object, chars_sha_by_object
    )


def _read_optional(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _ordinary_outcomes(tracking: dict) -> dict[str, list[dict]]:
    outcomes: dict[str, list[dict]] = {}
    for scope in ("page", "cross_page", "cross_column"):
        for page in tracking.get(scope, ()):
            if not isinstance(page, dict):
                continue
            for paragraph in page.get("paragraph", ()):
                if not isinstance(paragraph, dict):
                    continue
                runtime_ref = paragraph.get("runtime_source_ref")
                if isinstance(runtime_ref, str):
                    outcomes.setdefault(runtime_ref, []).append(dict(paragraph))
    return outcomes


def _joint_outcomes(report: dict) -> dict[str, list[dict]]:
    outcomes: dict[str, list[dict]] = {}
    rows = report.get("chains", ())
    if not isinstance(rows, list):
        return outcomes
    for row in rows:
        if not isinstance(row, dict):
            continue
        runtime_refs = row.get("runtime_source_refs")
        physical_refs = row.get("ordered_source_refs")
        fragments = row.get("ordered_fragments")
        if not all(isinstance(value, list) for value in (runtime_refs, physical_refs)):
            continue
        if not isinstance(fragments, list):
            fragments = []
        for index, runtime_ref in enumerate(runtime_refs):
            if not isinstance(runtime_ref, str):
                continue
            outcomes.setdefault(runtime_ref, []).append(
                {
                    "physical_source_ref": (
                        physical_refs[index] if index < len(physical_refs) else None
                    ),
                    "fragment": fragments[index] if index < len(fragments) else None,
                    "outcome": row.get("outcome") or row.get("result_state"),
                    "fallback_reason": row.get("fallback_reason"),
                    "joint_call_count": row.get("joint_call_count"),
                }
            )
    return outcomes


def _skip_reason(
    item: FrozenCoverageItem, source_script: str, length_floor: int
) -> str | None:
    """The first closed-vocabulary reason this untranslated item earns, or None.

    Trait reasons come first because they hold at any length; the script test
    next, because a paragraph with nothing in the source script was never a
    translation's business; the length floor last, so a short unit is named by
    the floor that refused it rather than by what it contains.
    """
    for trait in item.skip_traits:
        if trait in SKIP_REASONS:
            return trait
    script_chars = (
        item.han_chars if source_script == HAN_SCRIPT else item.latin_chars
    )
    other_chars = (
        item.latin_chars if source_script == HAN_SCRIPT else item.han_chars
    )
    # The measurement is direction-free; the judgment is not. Only the half
    # written wholly in the run's source script is a companion the target
    # language already covers -- the other half is the coverage the page came
    # with.
    if (
        "cross_script_twin_visible" in item.skip_traits
        and script_chars
        and not other_chars
    ):
        return "bilingual_companion_visible"
    if script_chars == 0:
        return "no_source_script"
    if item.text_length < length_floor:
        return "below_length_floor"
    return None


def finalize(config, snapshot: CoverageSnapshot) -> dict:
    """Join frozen sources to existing producer outcomes and write evidence."""
    report_path = Path(config.get_working_file_path(REPORT_NAME))
    working_dir = report_path.parent
    ordinary = _ordinary_outcomes(
        _read_optional(working_dir / "translate_tracking.json")
    )
    joint = _joint_outcomes(
        _read_optional(working_dir / "chain_translation.report.json")
    )
    companion_refs = {
        intent.visual_initial_ref
        for intent in drop_cap_intent.intents_for(config).values()
        if isinstance(intent.visual_initial_ref, str)
        and intent.visual_initial_ref != intent.source_ref
        and intent.binding_proof.get("kind") == "standalone_visual_initial"
    }
    source_script = _source_script(getattr(config, "lang_in", ""))
    length_floor = int(getattr(config, "min_text_length", 0) or 0)

    rows: list[dict] = []
    unowned: list[dict] = []
    for item in snapshot.items:
        ordinary_rows = ordinary.get(item.runtime_source_ref, [])
        joint_rows = joint.get(item.runtime_source_ref, [])
        target_text: str | None = None

        if item.source_ref in companion_refs and not joint_rows and not ordinary_rows:
            translation_owner = "none"
            final_status = "merged_into_drop_cap_owner"
        elif joint_rows:
            translation_owner = "joint"
            evidence = joint_rows[0]
            target_text = evidence.get("fragment")
            physical_match = evidence.get("physical_source_ref") == item.source_ref
            # Chain writeback intentionally reuses one historical paragraph
            # tracker.  It is the same joint outcome when its output equals
            # the chain fragment; a second tracker or a different output is a
            # real ordinary takeover and must stay visible.
            tracker_disagrees = len(ordinary_rows) > 1 or (
                len(ordinary_rows) == 1
                and (
                    ordinary_rows[0].get("source_ref") != item.source_ref
                    or ordinary_rows[0].get("output") != target_text
                )
            )
            if len(joint_rows) != 1:
                final_status = "duplicate_joint_outcome"
            elif tracker_disagrees:
                final_status = "duplicate_ownership"
            elif not physical_match:
                final_status = "source_ref_mismatch"
            elif (
                evidence.get("outcome") != "joint_success"
                or evidence.get("joint_call_count") != 1
                or evidence.get("fallback_reason") is not None
            ):
                final_status = str(evidence.get("outcome") or "joint_failed")
            elif not isinstance(target_text, str) or not target_text:
                final_status = "empty_target"
            else:
                final_status = "joint_success"
        elif ordinary_rows:
            translation_owner = "ordinary"
            evidence = ordinary_rows[0]
            target_text = evidence.get("output")
            if len(ordinary_rows) != 1:
                final_status = "duplicate_ordinary_outcome"
            elif evidence.get("source_ref") != item.source_ref:
                final_status = "source_ref_mismatch"
            elif not isinstance(target_text, str) or not target_text:
                final_status = "empty_target"
            else:
                final_status = "translated"
        elif item.preserve_candidate:
            translation_owner = "preserve"
            final_status = "preserved"
        else:
            translation_owner = "none"
            final_status = (
                "missing_joint_outcome" if item.chain_member else "untranslated"
            )

        skip_reason = (
            _skip_reason(item, source_script, length_floor)
            if final_status == "untranslated"
            else None
        )
        rows.append(
            {
                "source_ref": item.source_ref,
                "runtime_source_ref": item.runtime_source_ref,
                "physical_page": item.physical_page,
                "role": (
                    "drop_cap_companion"
                    if item.source_ref in companion_refs
                    else item.role
                ),
                "source_text_sha256": item.source_text_sha256,
                "source_box": (
                    None if item.source_box is None else list(item.source_box)
                ),
                "translation_owner": translation_owner,
                "target_text_sha256": (
                    _sha256(target_text if isinstance(target_text, str) else "")
                    if translation_owner in {"joint", "ordinary"}
                    else None
                ),
                "final_status": final_status,
                "skip_reason": skip_reason,
            }
        )
        if final_status == "untranslated" and skip_reason is None:
            unowned.append(
                {
                    "source_ref": item.source_ref,
                    "runtime_source_ref": item.runtime_source_ref,
                    "physical_page": item.physical_page,
                    "role": item.role,
                    "source_script_chars": (
                        item.han_chars
                        if source_script == HAN_SCRIPT
                        else item.latin_chars
                    ),
                    "text_length": item.text_length,
                }
            )

    owner_totals = dict.fromkeys(("joint", "ordinary", "preserve", "none"), 0)
    for row in rows:
        owner_totals[row["translation_owner"]] += 1
    skip_reason_totals = dict.fromkeys(SKIP_REASONS, 0)
    for row in rows:
        if row["skip_reason"] is not None:
            skip_reason_totals[row["skip_reason"]] += 1
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "direction": (
            f"{getattr(config, 'lang_in', '')}-{getattr(config, 'lang_out', '')}"
        ),
        "source_lang": str(getattr(config, "lang_in", "")),
        "target_lang": str(getattr(config, "lang_out", "")),
        "items": rows,
        "totals": {"sources": len(rows), "owners": owner_totals},
        "source_script": source_script,
        "skip_reason_totals": skip_reason_totals,
        "unowned_sources": unowned,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
