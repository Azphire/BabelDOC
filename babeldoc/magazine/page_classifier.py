"""Page classification stage: deterministic verdict, model adjudicated fallback.

Runs between StylesAndFormulas and translation, writes the page level kind
fields into the IL, and drops a per page report next to the other working
directory artefacts. The stage is data driven: it evaluates whatever vocabulary
``configs/page_types.json`` declares and never names a page type itself.

The stage is off by default. With ``magazine_page_classify`` disabled the
pipeline is untouched and the three IL attributes stay unset.

Two layers decide a page. The deterministic layer scores geometry against the
declared vocabulary and marks a page ambiguous when its top two candidates are
too close to separate. Only those pages reach the second layer: the page is
rendered and put to a vision model, which sees the image the geometry cannot
describe. The model's answer is adopted whole or not at all -- kind, confidence
and provenance move together -- and a refusal leaves the deterministic verdict
exactly as it was. Everything the IL has no field for, the second candidate on a
composite sheet and the reason a refusal was refused among it, goes to the
sidecar report.

The fallback is off unless ``configs/vlm.json`` turns it on. With it off this
stage performs no render, builds no client and reads no credential, and what it
writes is what the deterministic layer alone produced.
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
        adjudged = self._adjudicate(docs, verdicts)

        for position, (page, features, verdict) in enumerate(
            zip(docs.page, vectors, verdicts, strict=True)
        ):
            decision = adjudged.get(position)
            accepted = decision is not None and decision.accepted
            page.page_kind = decision.kind if accepted else verdict.kind
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
                    "vlm": _vlm_record(decision),
                }
            )
        self._write_report(records)
        return docs

    def _adjudicate(
        self, docs: il_version_1.Document, verdicts: list[Verdict]
    ) -> dict[int, VlmVerdict]:
        """Put every ambiguous page to the vision model, one render each.

        Returns the outcome per page position, refusals included: a refusal is
        recorded so the report can say why a page kept its deterministic kind.
        """
        routed = [
            position for position, verdict in enumerate(verdicts) if verdict.ambiguous
        ]
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
