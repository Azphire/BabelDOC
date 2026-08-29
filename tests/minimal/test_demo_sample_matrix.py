from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections import defaultdict
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault(
    "BABELDOC_CACHE_DIR", str(ROOT / ".runtime" / "stage00-test-cache")
)

from babeldoc import main as main_module  # noqa: E402

MATRIX_PATH = ROOT / "tests" / "fixtures" / "demo" / "sample_matrix.json"
MATRIX_KEYS = {
    "sample_id",
    "publication_id",
    "role",
    "source_path",
    "source_sha256",
    "source_lang",
    "target_lang",
    "config_path",
    "expectations_path",
    "stage_pages",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_REF_RE = re.compile(r"p(?P<page>[1-9][0-9]*)#(?P<index>[0-9]+)")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _anchors(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def _assert_box(actual, expected, tolerance: float = 1e-5) -> None:
    assert len(actual) == len(expected) == 4
    assert actual == pytest.approx(expected, abs=tolerance)


def _union_box(nodes) -> list[float]:
    boxes = [node["source_box"] for node in nodes]
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _assert_member(member, nodes_by_ref) -> None:
    matches = SOURCE_REF_RE.findall(member["diagnostic_ref"])
    assert len(matches) == 1, member
    match = SOURCE_REF_RE.search(member["diagnostic_ref"])
    assert match is not None
    source_ref = match.group(0)
    assert int(match.group("page")) == member["physical_page"]
    node = nodes_by_ref[source_ref]
    assert node["physical_page"] == member["physical_page"]
    assert node["source_text_sha256"] == member["source_text_sha256"]
    assert SHA256_RE.fullmatch(member["source_text_sha256"])
    _assert_box(node["source_box"], member["source_box"])
    assert f"debug_id={node['debug_id']}" in member["diagnostic_ref"]


def test_frozen_demo_sample_matrix_is_readable_unique_and_complete() -> None:
    matrix = _load(MATRIX_PATH)
    assert len(matrix) == 5
    assert all(set(sample) == MATRIX_KEYS for sample in matrix)
    assert Counter(
        (sample["role"], sample["source_lang"], sample["target_lang"])
        for sample in matrix
    ) == Counter(
        {
            ("diagnosis", "en", "zh"): 1,
            ("transfer", "en", "zh"): 1,
            ("holdout", "en", "zh"): 1,
            ("transfer", "zh", "en"): 1,
            ("holdout", "zh", "en"): 1,
        }
    )

    source_hashes = set()
    publications = defaultdict(dict)
    coverage = defaultdict(
        lambda: {
            "transitions": set(),
            "negative": False,
            "toc": set(),
            "layout": False,
            "title": False,
            "dropcap": False,
        }
    )

    for sample in matrix:
        source = ROOT / sample["source_path"]
        expectations_path = ROOT / sample["expectations_path"]
        corpus_path = ROOT / "corpus" / f"{sample['sample_id']}.json"
        config_path = ROOT / sample["config_path"]
        assert source.is_file()
        assert expectations_path.is_file()
        assert corpus_path.is_file()
        assert config_path.is_file()
        assert _sha256(source) == sample["source_sha256"]
        assert sample["source_sha256"] not in source_hashes
        source_hashes.add(sample["source_sha256"])

        direction = f"{sample['source_lang']}-{sample['target_lang']}"
        if sample["role"] in {"transfer", "holdout"}:
            publications[direction][sample["role"]] = sample["publication_id"]

        expectations = _load(expectations_path)
        corpus = _load(corpus_path)
        assert expectations["sample_id"] == corpus["sample_id"] == sample["sample_id"]
        assert expectations["source_sha256"] == corpus["source_sha256"] == sample["source_sha256"]
        assert expectations["direction"] == direction
        assert expectations["stage_pages"] == sample["stage_pages"]

        nodes = corpus["nodes"]
        refs = [node["source_ref"] for node in nodes]
        assert len(refs) == len(set(refs))
        assert all(SOURCE_REF_RE.fullmatch(ref) for ref in refs)
        assert all(SHA256_RE.fullmatch(node["source_text_sha256"]) for node in nodes)
        nodes_by_ref = {node["source_ref"]: node for node in nodes}

        with pymupdf.open(source) as document:
            assert all(1 <= page <= document.page_count for page in sample["stage_pages"])
            for region in expectations["layout_regions"]:
                assert region["role"] == "multi_column_page"
                page = document[region["physical_page"] - 1]
                _assert_box(list(page.cropbox), region["source_box"], tolerance=2e-5)

        for chain in expectations["chains"]:
            assert chain["role"] == "body"
            assert len(chain["transitions"]) == len(chain["ordered_members"]) - 1
            assert set(chain["transitions"]) <= {"cross_column", "cross_page"}
            for member in chain["ordered_members"]:
                _assert_member(member, nodes_by_ref)
            coverage[direction]["transitions"].update(chain["transitions"])

        for pair in expectations["negative_chain_pairs"]:
            assert len(pair["endpoints"]) == 2
            for endpoint in pair["endpoints"]:
                _assert_member(endpoint, nodes_by_ref)
            coverage[direction]["negative"] = True

        for section in ("toc_records", "titles"):
            for record in expectations[section]:
                record_nodes = [nodes_by_ref[ref] for ref in _anchors(record["anchor"])]
                _assert_box(_union_box(record_nodes), record["source_box"])

        for dropcap in expectations["dropcaps"]:
            assert dropcap["decision"] in {"keep", "flatten"}
            assert dropcap["anchor"] in nodes_by_ref
            assert f"paragraph_owner={dropcap['anchor']}" in dropcap["diagnostic_ref"]
            for ref in SOURCE_REF_RE.findall(dropcap["diagnostic_ref"]):
                assert f"p{ref[0]}#{ref[1]}" in nodes_by_ref

        for exemption in expectations["coverage_exemptions"]:
            assert exemption["reason"].strip()
            if "anchor" in exemption:
                assert exemption["anchor"] in nodes_by_ref
            else:
                assert exemption["physical_page"] >= 1
                assert len(exemption["source_box"]) == 4

        coverage[direction]["toc"].update(
            record["kind"] for record in expectations["toc_records"]
        )
        coverage[direction]["layout"] |= bool(expectations["layout_regions"])
        coverage[direction]["title"] |= bool(expectations["titles"])
        coverage[direction]["dropcap"] |= any(
            record["decision"] == "keep" for record in expectations["dropcaps"]
        )

    for direction in ("en-zh", "zh-en"):
        assert publications[direction]["transfer"] != publications[direction]["holdout"]
        assert coverage[direction]["transitions"] == {"cross_column", "cross_page"}
        assert coverage[direction]["negative"]
        assert {"single_visual_line", "block", "prose_exempt"} <= coverage[direction]["toc"]
        assert coverage[direction]["layout"]
        assert coverage[direction]["title"]
        assert coverage[direction]["dropcap"]


def test_zh_en_config_loads_with_the_existing_cli_parser() -> None:
    args = main_module.create_parser().parse_args(
        ["--config", str(ROOT / "minimal.zh-en.toml")]
    )
    assert args.lang_in == "zh"
    assert args.lang_out == "en"
    assert args.openai is True
    assert args.openai_model == "gpt-4o-mini"
    assert args.no_dual is True
    assert args.qps == 1
    assert args.pool_max_workers == 1
    assert args.term_pool_max_workers == 1
    assert args.watermark_output_mode == "no_watermark"
