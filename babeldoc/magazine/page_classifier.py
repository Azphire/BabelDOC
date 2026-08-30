"""Page classification stage: deterministic verdict, model adjudication.

Runs between StylesAndFormulas and translation, writes the page level kind
fields into the IL, and drops a per page report next to the other working
directory artefacts. The stage is data driven: it evaluates whatever vocabulary
``configs/page_types.json`` declares and never names a page type itself.

The stage is off by default. With ``magazine_page_classify`` disabled the
pipeline is untouched and the three IL attributes stay unset.

Two layers decide a page. The deterministic layer scores geometry against the
declared vocabulary and marks close candidates as ambiguous. When
``configs/vlm.json`` enables the second layer, every page is rendered and put
to a vision model, with the ranked deterministic candidates included as
reference. The model's answer is adopted whole or not at all -- kind,
confidence and provenance move together -- and a refusal leaves that page's
deterministic verdict exactly as it was.

For a composite page, the report retains the model's primary and secondary
kinds. The effective kind written into the IL is selected from those two by the
taxonomy's ``preserve_line_structure`` policy. With the switch off this stage
performs no render, builds no client and reads no credential.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pymupdf

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.page_features import FEATURE_NAMES
from babeldoc.magazine.page_features import extract_document_features
from babeldoc.magazine.page_features import percentile_feature_names
from babeldoc.magazine.prompt_loader import load_prompt
from babeldoc.magazine.taxonomy import DEFAULT_CONFIG_PATHS
from babeldoc.magazine.taxonomy import Verdict
from babeldoc.magazine.taxonomy import classify
from babeldoc.magazine.taxonomy import load_configs
from babeldoc.magazine.taxonomy import record_config_manifest
from babeldoc.magazine.taxonomy import vocabulary_block
from babeldoc.magazine.vlm_client import CachedVlmClient
from babeldoc.magazine.vlm_client import VlmVerdict
from babeldoc.magazine.vlm_client import load_vlm_config

logger = logging.getLogger(__name__)

REPORT_NAME = "page_classify.report.json"

# Provenance recorded in Page.pageKindSource. A page carries the name of the
# layer that decided it, which is the only way a reader of the IL can tell an
# adjudicated page from one geometry settled on its own.
SOURCE = "deterministic"
VLM_SOURCE = "vlm"

# The prompt the fallback sends, by name; its text lives in prompts/.
CLASSIFY_PROMPT = "page_classify_vlm"


class PageClassifier:
    """Assign a page kind, a confidence and a source to every IL page."""

    stage_name = "PageClassifier"

    def __init__(self, translation_config, vlm_client: CachedVlmClient | None = None):
        self.translation_config = translation_config
        self.feature_config, self.taxonomy = load_configs()
        self.vlm_config = load_vlm_config() if vlm_client is None else vlm_client.config
        self._vlm_client = vlm_client

    @property
    def working_dir(self) -> Path:
        """Directory the stage writes its report and manifests into."""
        return Path(self.translation_config.get_working_file_path(REPORT_NAME)).parent

    @property
    def vlm_enabled(self) -> bool:
        return bool(self.vlm_config.enabled)

    def client(self) -> CachedVlmClient:
        """The adjudicating client, built on first use rather than at import."""
        if self._vlm_client is None:
            self._vlm_client = CachedVlmClient(
                config=self.vlm_config, working_dir=self.working_dir
            )
        return self._vlm_client

    def process(self, docs: il_version_1.Document) -> il_version_1.Document:
        records = []
        percentile_names = percentile_feature_names(self.feature_config)
        vectors = extract_document_features(docs, self.feature_config)
        verdicts = [classify(features, self.taxonomy) for features in vectors]
        adjudged = self._adjudicate(docs, verdicts, vectors)

        for position, (page, features, verdict) in enumerate(
            zip(docs.page, vectors, verdicts, strict=True)
        ):
            decision = adjudged.get(position)
            accepted = decision is not None and decision.accepted
            if accepted:
                effective_kind, effective_kind_reason = _effective_vlm_kind(
                    decision,
                    self.taxonomy.policy_of,
                    deterministic=verdict,
                    features=features,
                    page_types=self.taxonomy.page_types,
                )
            else:
                effective_kind = verdict.kind
                effective_kind_reason = (
                    "deterministic_fallback_after_vlm_rejection"
                    if decision is not None
                    else "deterministic_without_vlm"
                )
            page.page_kind = effective_kind
            page.page_kind_conf = (
                decision.confidence if accepted else verdict.confidence
            )
            page.page_kind_source = VLM_SOURCE if accepted else SOURCE
            records.append(
                {
                    "page_number": page.page_number,
                    "kind": verdict.kind,
                    "conf": verdict.confidence,
                    "ambiguous": verdict.ambiguous,
                    # Raw and percentile values are reported side by side: a
                    # reviewer reading a rule needs the absolute quantity and
                    # the position it maps to within this document.
                    "features": {name: features[name] for name in FEATURE_NAMES},
                    "features_pctl": {
                        name: features[name] for name in percentile_names
                    },
                    "scores": verdict.scores,
                    # What the page ended up with, which is the deterministic
                    # verdict above unless the fallback replaced it.
                    "final_kind": page.page_kind,
                    "final_conf": page.page_kind_conf,
                    "source": page.page_kind_source,
                    "effective_kind": effective_kind,
                    "effective_kind_reason": effective_kind_reason,
                    "vlm": _vlm_record(decision),
                }
            )
        self._write_report(records)
        return docs

    def _adjudicate(
        self,
        docs: il_version_1.Document,
        verdicts: list[Verdict],
        features: list[dict[str, float]],
    ) -> dict[int, VlmVerdict]:
        """Put every page to the vision model, one render each.

        Returns the outcome per page position, refusals included: a refusal is
        recorded so the report can say why a page kept its deterministic kind.
        """
        routed = range(len(docs.page))
        if not self.vlm_enabled or not routed:
            return {}

        vocabulary = self.taxonomy.names()
        taxonomy_text = vocabulary_block(self.taxonomy)
        source_pdf = Path(self.translation_config.input_file)
        outcomes: dict[int, VlmVerdict] = {}
        with pymupdf.open(source_pdf) as rendered:
            for position in routed:
                page = docs.page[position]
                index = page.page_number if page.page_number is not None else position
                if not 0 <= index < rendered.page_count:
                    outcomes[position] = VlmVerdict(
                        accepted=False,
                        reason=f"page index {index} is outside {source_pdf.name}",
                    )
                    continue
                prompt = load_prompt(
                    CLASSIFY_PROMPT,
                    {
                        "taxonomy": taxonomy_text,
                        "deterministic_verdict": _verdict_block(
                            verdicts[position], self.vlm_config.verdict_rows
                        ),
                        "page_features": _feature_block(features[position]),
                        "page_context": _page_context(index, rendered.page_count),
                    },
                    working_dir=self.working_dir,
                )
                image = _render_page(rendered, index, self.vlm_config.render_dpi)
                outcomes[position] = self.client().classify(prompt, image, vocabulary)
        return outcomes

    def _write_report(self, records: list[dict]) -> Path:
        report = {
            "taxonomy_version": self.taxonomy.version,
            "source": SOURCE,
            "ambiguity_margin": self.taxonomy.ambiguity_margin,
            "vlm_enabled": self.vlm_enabled,
            "pages": records,
        }
        path = Path(self.translation_config.get_working_file_path(REPORT_NAME))
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
        record_config_manifest(path.parent, list(DEFAULT_CONFIG_PATHS))
        ambiguous = sum(record["ambiguous"] for record in records)
        adjudicated = sum(record["source"] == VLM_SOURCE for record in records)
        logger.debug(
            "classified %d pages, %d ambiguous, %d adjudicated, report at %s",
            len(records),
            ambiguous,
            adjudicated,
            path,
        )
        return path


def _render_page(document: pymupdf.Document, index: int, dpi: int) -> bytes:
    """One page as PNG bytes, the only form the model sees a page in."""
    return document[index].get_pixmap(dpi=dpi, alpha=False).tobytes("png")


def _verdict_block(verdict: Verdict, rows: int) -> str:
    """The deterministic layer's ranked candidates, as reference for the model."""
    ranked = sorted(verdict.scores.items(), key=lambda item: (-item[1], item[0]))
    return "\n".join(
        f"{position}. {name} (score {score:.3f})"
        for position, (name, score) in enumerate(ranked[:rows], start=1)
    )


def _page_context(index: int, total: int) -> str:
    return f"Page {index + 1} of {total} in this file."


def _feature_block(features: dict[str, float]) -> str:
    """Measured visual evidence, with the same stable names used by taxonomy."""
    return "\n".join(
        f"- {name}: {features[name]:.3f}" for name in FEATURE_NAMES
    )


def _effective_vlm_kind(
    decision: VlmVerdict,
    policy_of,
    *,
    deterministic: Verdict | None = None,
    features: dict[str, float] | None = None,
    page_types=(),
) -> tuple[str, str]:
    """Select the IL kind from a model's primary and secondary candidates."""
    primary = decision.kind
    secondary = decision.secondary_kind
    primary_policy = policy_of(primary) or {}
    secondary_policy = policy_of(secondary) or {}
    primary_preserves = primary_policy.get("preserve_line_structure") is True
    secondary_preserves = secondary_policy.get("preserve_line_structure") is True

    if primary_preserves != secondary_preserves:
        if secondary_preserves:
            return secondary, "secondary_only_preserves_line_structure"
        return primary, "primary_only_preserves_line_structure"

    if deterministic is not None and features is not None:
        deterministic_policy = policy_of(deterministic.kind) or {}
        if (
            features["image_area_ratio"] >= 0.5
            and features["text_coverage_ratio"] <= 0.15
            and features["max_font_size_ratio"] < 3.0
            and deterministic_policy.get("repair_profile") == "figure"
            and deterministic_policy.get("chain_eligible") is True
            and primary_policy.get("indent_eligible") is True
        ):
            return deterministic.kind, "deterministic_image_dominant_policy"

        continuous_story = (
            features["text_coverage_ratio"] >= 0.3
            and features["mean_paragraph_chars"] >= 60.0
            and features["short_paragraph_ratio"] <= 0.7
        )
        primary_is_article_or_grid = (
            primary_policy.get("indent_eligible") is True
            or primary_policy.get("repair_profile") == "grid"
        )
        if continuous_story and primary_is_article_or_grid:
            max_font_ratio = features["max_font_size_ratio"]
            if max_font_ratio >= 3.0:
                effective = _article_policy_kind(page_types, opens_article=True)
                if effective is not None:
                    return effective, "taxonomy_article_opener_hierarchy_policy"
            elif max_font_ratio <= 2.7:
                effective = _article_policy_kind(page_types, opens_article=False)
                if effective is not None:
                    return effective, "taxonomy_article_body_hierarchy_policy"

    return primary, "primary_retained_same_preserve_line_structure_policy"


def _article_policy_kind(page_types, *, opens_article: bool) -> str | None:
    """Find the declared prose kind matching one article-boundary policy."""
    for page_type in page_types:
        policy = page_type.policy
        if policy.get("indent_eligible") is not True:
            continue
        if opens_article and policy.get("opens_article") is True:
            return page_type.name
        if not opens_article and policy.get("starts_article") is False:
            return page_type.name
    return None


def _vlm_record(decision: VlmVerdict | None) -> dict | None:
    """The fallback's outcome for one page, or null where it was not consulted."""
    if decision is None:
        return None
    return {
        "accepted": decision.accepted,
        "kind": decision.kind,
        "confidence": decision.confidence,
        "secondary_kind": decision.secondary_kind,
        "secondary_reason": decision.secondary_reason,
        "reason": decision.reason,
        "attempts": decision.attempts,
        "from_cache": decision.from_cache,
    }
