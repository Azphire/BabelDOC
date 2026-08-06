"""Deterministic page classification stage.

Runs between StylesAndFormulas and translation, writes the page level kind
fields into the IL, and drops a per page report next to the other working
directory artefacts. The stage is data driven: it evaluates whatever vocabulary
``configs/page_types.json`` declares and never names a page type itself.

The stage is off by default. With ``magazine_page_classify`` disabled the
pipeline is untouched and the three IL attributes stay unset.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine.page_features import FEATURE_NAMES
from babeldoc.magazine.page_features import extract_document_features
from babeldoc.magazine.page_features import percentile_feature_names
from babeldoc.magazine.taxonomy import DEFAULT_CONFIG_PATHS
from babeldoc.magazine.taxonomy import classify
from babeldoc.magazine.taxonomy import load_configs
from babeldoc.magazine.taxonomy import record_config_manifest

logger = logging.getLogger(__name__)

REPORT_NAME = "page_classify.report.json"

# Provenance recorded in Page.pageKindSource, distinguishing this stage from
# the model assisted classifier a later batch adds.
SOURCE = "deterministic"


class PageClassifier:
    """Assign a page kind, a confidence and a source to every IL page."""

    stage_name = "PageClassifier"

    def __init__(self, translation_config):
        self.translation_config = translation_config
        self.feature_config, self.taxonomy = load_configs()

    def process(self, docs: il_version_1.Document) -> il_version_1.Document:
        records = []
        percentile_names = percentile_feature_names(self.feature_config)
        vectors = extract_document_features(docs, self.feature_config)
        for page, features in zip(docs.page, vectors, strict=True):
            verdict = classify(features, self.taxonomy)
            page.page_kind = verdict.kind
            page.page_kind_conf = verdict.confidence
            page.page_kind_source = SOURCE
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
                }
            )
        self._write_report(records)
        return docs

    def _write_report(self, records: list[dict]) -> Path:
        report = {
            "taxonomy_version": self.taxonomy.version,
            "source": SOURCE,
            "ambiguity_margin": self.taxonomy.ambiguity_margin,
            "pages": records,
        }
        path = Path(self.translation_config.get_working_file_path(REPORT_NAME))
        with path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
        record_config_manifest(path.parent, list(DEFAULT_CONFIG_PATHS))
        ambiguous = sum(record["ambiguous"] for record in records)
        logger.debug(
            "classified %d pages, %d ambiguous, report at %s",
            len(records),
            ambiguous,
            path,
        )
        return path
