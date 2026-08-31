"""A released title chain is accepted with its recorded reason, not fatal.

The chain translation stage releases a chain it cannot allocate -- a
cross-page title pair whose joint target fits no slot records
``chain_target_overflow`` and hands its members back to the per-paragraph
path. The typeset proof must read that release as the handled fallback it
is; only a proof that is missing or corrupt stays fatal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from babeldoc.magazine import title_typeset


class Config:
    def __init__(self, working_dir: Path):
        self.working_dir = working_dir

    def get_working_file_path(self, name: str) -> str:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return str(self.working_dir / name)


def _title(local_ref: str, chain_id: str, chain_index: int):
    return title_typeset.FrozenTitle(
        paragraph=object(),
        page=object(),
        physical_page=chain_index + 2,
        local_ref=local_ref,
        source_ref=local_ref,
        source_box=(10.0, 20.0, 110.0, 60.0),
        base_style=object(),
        base_font_size=24.0,
        target=f"half {chain_index}",
        target_sha256="0" * 64,
        target_compositions=(),
        target_segments=({},),
        chain_id=chain_id,
        chain_index=chain_index,
    )


def _ir(members: dict[str, str]):
    # The proof reads one mapping off the IR; a full canonical ArticleIR
    # would need real articles behind every element, which is not this
    # test's question.
    from types import SimpleNamespace

    return SimpleNamespace(by_chain_member=dict(members))


def test_a_recorded_release_is_returned_not_raised(tmp_path: Path) -> None:
    titles = [_title("p2#3", "XyZzy", 0), _title("p3#1", "XyZzy", 1)]
    (tmp_path / title_typeset.CHAIN_REPORT_NAME).write_text(
        json.dumps(
            {
                # A released chain never reaches the applied ``chains`` list;
                # the stage files its recorded outcome under ``outcomes``.
                "chains": [],
                "outcomes": [
                    {
                        "chain_id": "XyZzy",
                        "outcome": "failed_with_issue",
                        "fallback_reason": "chain_target_overflow",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    released = title_typeset._prove_title_chains(
        Config(tmp_path),
        _ir({"p2#3": "canon-1", "p3#1": "canon-1"}),
        titles,
    )

    assert released == [
        {
            "chain_id": "XyZzy",
            "reason": "chain_target_overflow",
            "members": ["p2#3", "p3#1"],
        }
    ]
    # The members keep their own targets: nothing merged them.
    assert [title.target for title in titles] == ["half 0", "half 1"]


def test_a_missing_proof_without_a_release_stays_fatal(tmp_path: Path) -> None:
    titles = [_title("p2#3", "XyZzy", 0), _title("p3#1", "XyZzy", 1)]
    (tmp_path / title_typeset.CHAIN_REPORT_NAME).write_text(
        json.dumps({"chains": []}), encoding="utf-8"
    )

    with pytest.raises(Exception, match="no unique joint-success"):
        title_typeset._prove_title_chains(
            Config(tmp_path),
            _ir({"p2#3": "canon-1", "p3#1": "canon-1"}),
            titles,
        )
