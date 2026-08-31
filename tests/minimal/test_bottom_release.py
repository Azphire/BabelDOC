"""B19 T4 -- a body paragraph is not squeezed below the size a reader reads.

The width corridor B18 built for a word unit, turned through ninety degrees.
Courier-zh page 4 set two body paragraphs at 3.5pt and 4.38pt: the search had
nowhere to go but down, so down is where it went. Now, before it crosses the
declared visual floor, the source box's bottom edge is released into the
deterministic corridor beneath it, and the paragraph is set at a readable size
in a taller box.

The negative half is what keeps it honest: a paragraph with a neighbour
directly beneath has no corridor and is left exactly as it was, with the
attempt recorded either way.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
from babeldoc.magazine.indent_policy import load_indent_config
from tests.minimal.fakes import _page
from tests.minimal.fakes import _paragraph
from tests.minimal.test_word_fit import Config
from tests.minimal.test_word_fit import RenderMapper
from tests.minimal.test_word_fit import _units

# Enough text that the source box can only hold it by shrinking hard.
CROWDED = "traditional knowledge systems are parallel systems of knowledge"


def _crowded_page(box, blocker=None, label="plain text"):
    """One over-full body paragraph, optionally with something below it."""
    subject = _paragraph(CROWDED, "crowded-1", box, label=label)
    subject.xobj_id = -1
    paragraphs = [subject]
    if blocker is not None:
        below = _paragraph("occupied", "below-1", blocker, label=label)
        below.xobj_id = -1
        paragraphs.append(below)
    return subject, _page(0, paragraphs)


def _set(typesetter, paragraph, page, font_size=10.0):
    units = _units(typesetter, CROWDED, font_size=font_size)
    scale, _laid = typesetter._find_optimal_scale_and_layout(
        paragraph, page, units, apply_layout=True
    )
    return scale, scale * font_size


def _release_records(typesetter):
    return [
        record
        for record in typesetter._word_fit_records
        if record["kind"] == "bottom_release"
    ]


def test_a_squeezed_paragraph_is_released_down_the_corridor(tmp_path):
    """The positive: a shallow box with free space beneath it grows into it.

    Asked of the release itself rather than of a whole layout search, because
    the pre-existing expansion this pass sits beside also reaches downward and
    a page arranged to trigger one triggers the other. What is under test here
    is the corridor's own answer: three edges of the source box untouched, the
    fourth let out to the nearest blocker plus the standing clearance.
    """
    subject, page = _crowded_page((10.0, 88.0, 60.0, 96.0))
    typesetter = Typesetting(Config(tmp_path), RenderMapper())

    released = typesetter._release_paragraph_bottom(subject, page, subject.box)

    assert released is not None
    assert float(released.y) < 88.0
    assert (float(released.x), float(released.x2), float(released.y2)) == (
        10.0,
        60.0,
        96.0,
    )


def test_the_release_stops_at_the_neighbour_beneath_it(tmp_path):
    """The corridor is the nearest blocker plus the standing clearance."""
    clearance = load_indent_config().functional_clearance_pt
    subject, page = _crowded_page(
        (10.0, 88.0, 60.0, 96.0), blocker=(10.0, 40.0, 60.0, 70.0)
    )
    typesetter = Typesetting(Config(tmp_path), RenderMapper())

    released = typesetter._release_paragraph_bottom(subject, page, subject.box)

    assert released is not None
    assert float(released.y) == pytest.approx(70.0 + clearance)
    # Zero overlap with the thing it stopped for.
    assert float(released.y) > 70.0


def test_a_paragraph_with_no_room_below_is_not_released(tmp_path):
    """The negative: a blocker directly beneath buys nothing, so nothing goes."""
    subject, page = _crowded_page(
        (10.0, 88.0, 60.0, 96.0), blocker=(10.0, 40.0, 60.0, 87.5)
    )
    typesetter = Typesetting(Config(tmp_path), RenderMapper())

    assert typesetter._release_paragraph_bottom(subject, page, subject.box) is None


def test_the_floor_binds_running_body_text_only(tmp_path):
    """A folio set small is set small on purpose."""
    labels = load_indent_config().body_labels
    assert "abandon" not in labels
    body, page = _crowded_page((10.0, 88.0, 60.0, 96.0))
    typesetter = Typesetting(Config(tmp_path), RenderMapper())
    units = _units(typesetter, CROWDED)

    assert typesetter._visual_floor_scale(body, units) == pytest.approx(
        load_indent_config().min_visual_font_pt / 10.0
    )
    folio, _page_two = _crowded_page((10.0, 88.0, 60.0, 96.0), label="abandon")
    assert typesetter._visual_floor_scale(folio, units) is None


def test_the_release_is_taken_and_recorded_in_a_real_search(tmp_path):
    """The integration: a body paragraph the floor binds ends up in a taller box.

    The record is the deliverable as much as the box is -- a release that left
    no trace would be a paragraph whose geometry no longer matches its source
    with nothing to say why.
    """
    subject, page = _crowded_page((10.0, 88.0, 60.0, 96.0))
    typesetter = Typesetting(Config(tmp_path), RenderMapper())
    _set(typesetter, subject, page)

    assert float(subject.box.y) < 88.0
    assert (float(subject.box.x), float(subject.box.x2), float(subject.box.y2)) == (
        10.0,
        60.0,
        96.0,
    )
    for record in _release_records(typesetter):
        assert record["outcome"] in {"released", "corridor_exhausted"}
        assert record["debug_id"] == "crowded-1"
        assert record["floor_scale"] == pytest.approx(0.6)


def test_a_box_someone_else_chose_is_never_released(tmp_path):
    """A flow slot or a bounded rewrite is not this paragraph's box to grow."""
    subject, page = _crowded_page((10.0, 88.0, 60.0, 96.0))
    typesetter = Typesetting(Config(tmp_path), RenderMapper())
    units = _units(typesetter, CROWDED)
    slot = il_version_1.Box(10.0, 88.0, 60.0, 96.0)

    typesetter._find_optimal_scale_and_layout(
        subject, page, units, apply_layout=True, box_override=slot
    )

    assert _release_records(typesetter) == []


def test_the_corridor_is_the_width_corridor_turned_ninety_degrees(tmp_path):
    """Both directions read one clearance, from one file."""
    clearance = load_indent_config().functional_clearance_pt
    subject, page = _crowded_page((10.0, 50.0, 60.0, 60.0), blocker=(10.0, 10.0, 60.0, 30.0))
    typesetter = Typesetting(Config(tmp_path), RenderMapper())

    corridor = typesetter._paragraph_corridor_y(subject, page, subject.box)

    assert corridor == pytest.approx(30.0 + clearance)
    # A blocker that shares no x with the paragraph does not bound it.
    _subject2, page2 = _crowded_page((10.0, 50.0, 60.0, 60.0), blocker=(80.0, 10.0, 110.0, 30.0))
    aside = typesetter._paragraph_corridor_y(
        page2.pdf_paragraph[0], page2, page2.pdf_paragraph[0].box
    )
    assert aside == pytest.approx(float(page2.cropbox.box.y) + clearance)


class TestConfigBounds:
    def test_the_floor_is_declared_with_a_range(self):
        config = load_indent_config()
        assert 4 <= config.min_visual_font_pt <= 10

    def test_out_of_range_floor_is_refused(self):
        import json

        from babeldoc.magazine import indent_policy

        with indent_policy.CONFIG_PATH.open(encoding="utf-8") as f:
            raw = json.load(f)
        raw["min_visual_font_pt"] = 99
        with pytest.raises(indent_policy.IndentPolicyError):
            indent_policy.parse_indent_config(raw, "indent_policy.json")


def _unused(path: Path) -> None:  # pragma: no cover - import anchor
    return None
