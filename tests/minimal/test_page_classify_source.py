"""The page classifier's source switch: "local" asks no model at all.

``page_classify_source`` in ``configs/vlm.json`` selects which layer finishes
a page.  Under "local" the deterministic geometry verdict stands and the
adjudication step returns before it renders a page, builds a client or reads
a credential -- whatever ``enabled`` says.  Under "vlm" the standing behavior
is unchanged.  The B15 T2b audit (docs/reports/B15/page_classify_audit.md)
set the shipped default to "vlm"; this file pins the switch's mechanics, not
the default's wisdom.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from babeldoc.magazine.page_classifier import PageClassifier
from babeldoc.magazine.vlm_client import load_vlm_config
from babeldoc.magazine.vlm_client import parse_vlm_config


def classifier_with(source: str, enabled: bool = True) -> PageClassifier:
    config = dataclasses.replace(
        load_vlm_config(), page_classify_source=source, enabled=enabled
    )
    built = PageClassifier.__new__(PageClassifier)
    built.translation_config = SimpleNamespace()
    built.vlm_config = config
    built._vlm_client = None
    return built


def docs_with_pages(count: int):
    return SimpleNamespace(page=[SimpleNamespace() for _ in range(count)])


def test_shipped_default_is_declared_and_valid():
    assert load_vlm_config().page_classify_source == "vlm"


def test_local_source_skips_adjudication_entirely():
    classifier = classifier_with("local", enabled=True)
    # No taxonomy, no input file, no client on the object: reaching for any
    # of them would raise, which is the proof nothing model-shaped runs.
    assert classifier._adjudicate(docs_with_pages(3), [], []) == {}


def test_vlm_source_with_vlm_disabled_still_asks_nothing():
    classifier = classifier_with("vlm", enabled=False)
    assert classifier._adjudicate(docs_with_pages(3), [], []) == {}


def test_unknown_source_is_refused_by_the_config():
    raw = {"page_classify_source": "oracle"}
    try:
        parse_vlm_config(
            {**_raw_shipped(), **raw},
            "vlm.json",
        )
    except Exception as error:
        assert "page_classify_source" in str(error)
    else:
        raise AssertionError("an undeclared source was accepted")


def _raw_shipped() -> dict:
    import json

    from babeldoc.magazine.vlm_client import CONFIG_PATH

    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
