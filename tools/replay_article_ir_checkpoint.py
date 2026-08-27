"""Replay canonical C18 ArticleIR identity from a legacy ABB checkpoint.

The archived C16 checkpoint contains diagnostic labels inserted into the IL.
They are removed by strict geometry/class matching before the current physical
page resolver, owner grouping and owner-scoped chain builder are run.  This is
an offline diagnostic; it never substitutes the archived output for a source
PDF production run.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babeldoc.magazine.article_builder import ArticleBuilder  # noqa: E402
from babeldoc.magazine.chain_builder import ChainBuilder  # noqa: E402
from babeldoc.magazine.checkpoint import load_checkpoint  # noqa: E402
from babeldoc.magazine.page_identity import DocumentPageIndex  # noqa: E402
from babeldoc.magazine.page_identity import physical_page_number  # noqa: E402

SCHEMA_VERSION = "article-ir-checkpoint-replay.v1"
EXPECTED = {
    "checkpoint.07_page_classifier.xml": (
        "1c3f88ef69950e8a8bac3c24e8347b1b69da2996b1f07f673d01499cf0e1800f"
    ),
    "checkpoint.08_chain_builder.xml": (
        "1c3f88ef69950e8a8bac3c24e8347b1b69da2996b1f07f673d01499cf0e1800f"
    ),
    "article_ir.json": (
        "f522279e66d4bcd003c4cd05ca01a69f3a9ac0367c7d3a4ccd7fa1c437d9e440"
    ),
    "chain_report.json": (
        "1d01a009ca4abd3be3d5a36be647cbfb2904f69ee815314f956b079ef0171d16"
    ),
}


class ReplayConfig:
    def __init__(self, root: Path, selected_pages: tuple[int, ...]) -> None:
        self.root = root
        self.selected_pages = frozenset(selected_pages)
        self.magazine_article_group = True
        self.magazine_hitl_export = False
        self.magazine_hitl_apply = False
        self.only_include_translated_page = True

    def should_translate_page(self, physical_page: int) -> bool:
        return int(physical_page) in self.selected_pages

    def get_working_file_path(self, name: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        return str(self.root / name)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _coords(value) -> tuple[float, float, float, float]:
    holder = getattr(value, "box", value)
    return tuple(float(getattr(holder, name)) for name in ("x", "y", "x2", "y2"))


def _parse_pages(value: str) -> tuple[int, ...]:
    pages = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            left, right = (int(number) for number in item.split("-", 1))
            if left < 1 or right < left:
                raise argparse.ArgumentTypeError("page ranges must be positive and ordered")
            pages.extend(range(left, right + 1))
        else:
            page = int(item)
            if page < 1:
                raise argparse.ArgumentTypeError("pages must be positive")
            pages.append(page)
    result = tuple(dict.fromkeys(pages))
    if not result:
        raise argparse.ArgumentTypeError("at least one page is required")
    return result


def _remove_legacy_debug(document) -> tuple[object, tuple[dict, ...]]:
    """Remove only diagnostic label/rectangle pairs proven by page layouts."""
    cleaned = copy.deepcopy(document)
    removed = []
    for page in cleaned.page:
        physical_page = int(physical_page_number(page))
        layouts = tuple(page.page_layout or ())
        if not layouts:
            continue
        if len(page.pdf_paragraph or ()) < len(layouts) or len(
            page.pdf_rectangle or ()
        ) < len(layouts):
            raise ValueError(
                f"p{physical_page}: legacy debug adapter has incomplete pairs"
            )
        keys = []
        for index, layout in enumerate(layouts):
            paragraph = page.pdf_paragraph[index]
            rectangle = page.pdf_rectangle[index]
            layout_box = _coords(layout)
            key = (str(layout.class_name), layout_box)
            if key in keys:
                raise ValueError(f"p{physical_page}: ambiguous legacy layout key")
            keys.append(key)
            label_box = _coords(paragraph)
            expected_label = (
                layout_box[0],
                layout_box[3],
                layout_box[2],
                layout_box[3] + 5.0,
            )
            if (
                paragraph.unicode != layout.class_name
                or label_box[0] != expected_label[0]
                or label_box[2] != expected_label[2]
                or _coords(rectangle) != layout_box
            ):
                raise ValueError(
                    f"p{physical_page}: unmatched legacy diagnostic pair {index}"
                )
            removed.append(
                {
                    "physical_page": physical_page,
                    "layout_index": index,
                    "class_name": layout.class_name,
                    "layout_box": list(layout_box),
                }
            )
        del page.pdf_paragraph[: len(layouts)]
        del page.pdf_rectangle[: len(layouts)]
    return cleaned, tuple(removed)


def _legacy_summary(record: dict, selected: tuple[int, ...]) -> dict:
    owners = {
        str(page): record.get("by_page", {}).get(str(page))
        for page in selected
    }
    decisions = {}
    for article in record.get("articles", ()):  # legacy list-position model
        for evidence in article.get("policy_evidence", ()):
            page = int(evidence["page"])
            if page in selected:
                decisions[str(page)] = {
                    "page_kind": evidence.get("page_kind"),
                    "role": evidence.get("role"),
                }
    return {
        "schema_version": record.get("schema_version"),
        "selected_page_owners": owners,
        "selected_page_decisions": decisions,
    }


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--pages", required=True, type=_parse_pages)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    hashes = {name: _digest(args.root / name) for name in EXPECTED}
    mismatches = {
        name: {"expected": EXPECTED[name], "actual": value}
        for name, value in hashes.items()
        if value != EXPECTED[name]
    }
    if mismatches:
        raise ValueError(f"ABB_CHECKPOINT_HASH_MISMATCH: {mismatches}")

    archived_ir = json.loads(
        (args.root / "article_ir.json").read_text(encoding="utf-8")
    )
    checkpoint = load_checkpoint(args.root / "checkpoint.07_page_classifier.xml")
    cleaned, removed = _remove_legacy_debug(checkpoint)
    page_index = DocumentPageIndex(cleaned)
    source_physical_pages = tuple(
        int(physical_page_number(page))
        for page in cleaned.page
        if int(physical_page_number(page)) in args.pages
    )
    if source_physical_pages != args.pages:
        raise ValueError(
            f"requested physical pages are not present: {source_physical_pages!r}"
        )

    replay_root = args.report.parent / ".article-ir-replay-work"
    config = ReplayConfig(replay_root, args.pages)
    builder = ArticleBuilder(config)
    provisional = builder.build_provisional(cleaned)
    chain_result = ChainBuilder(config).process(cleaned, provisional)
    article_ir = builder.finalize(provisional, chain_result)

    roles = {
        int(physical_page_number(cleaned.page[position])): role
        for position, role in enumerate(provisional.grouping.roles)
    }
    decisions = {
        str(page): {
            "physical_page": page,
            "structural_position": page_index.structural_position_of(page),
            "page_kind": page_index.page_by_source_number(page).page_kind,
            "role": roles[page_index.structural_position_of(page)].role,
            "owner": article_ir.by_page.get(page),
        }
        for page in args.pages
    }
    selected_chains = [
        chain.to_record()
        for chain in article_ir.chains
        if set(chain.member_physical_pages).intersection(args.pages)
    ]
    cross_owner = [
        chain["chain_id"]
        for chain in selected_chains
        if len(
            {
                article_ir.by_page.get(page)
                for page in chain["member_physical_pages"]
            }
        )
        > 1
    ]
    expected_kinds = {"7": "toc", "8": "article_opener", "9": "article_opener"}
    actual_kinds = {page: row["page_kind"] for page, row in decisions.items()}
    owners = {page: row["owner"] for page, row in decisions.items()}
    if actual_kinds != expected_kinds:
        raise ValueError(
            f"physical page decisions changed: expected={expected_kinds}, "
            f"actual={actual_kinds}"
        )
    if owners["8"] is None or owners["9"] is None or owners["8"] == owners["9"]:
        raise ValueError(f"pages 8 and 9 are not independent owners: {owners}")
    if cross_owner:
        raise ValueError(f"owner-scoped replay retained cross-owner chains: {cross_owner}")

    report = {
        "schema_version": SCHEMA_VERSION,
        "archive_hashes": hashes,
        "source_physical_pages": list(source_physical_pages),
        "legacy_artifact": _legacy_summary(archived_ir, args.pages),
        "legacy_debug_adapter": {
            "removed_count": len(removed),
            "removed_by_physical_page": {
                str(page): sum(item["physical_page"] == page for item in removed)
                for page in args.pages
            },
            "semantic_legacy_debug_labels": 0,
        },
        "replayed_article_ir": {
            "schema_version": article_ir.schema_version,
            "page_selection_map": article_ir.page_selection_map.to_record(),
            "decisions": decisions,
            "selected_page_owners": owners,
            "selected_chains": selected_chains,
            "cross_owner_chains": cross_owner,
            "unsupported_pages": [
                item.to_record()
                for item in article_ir.unsupported_pages
                if item.page in args.pages
            ],
        },
    }
    _write_atomic(args.report, report)
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
