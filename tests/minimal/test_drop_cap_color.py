"""Named color space resolution for the frozen drop cap color.

A magazine that defines its palette as ICCBased streams paints an initial with
``/CS0 cs 0.741 0.744 0.326 scn`` and nothing in that instruction says what
the three numbers are. These tests pin the two halves of the fix: the capture
consumes a resolver and normalizes ``scn`` components through it, and the
resolver reads only what the source document declares -- ICCBased by its /N,
direct device names as themselves, everything else refused so the capture
keeps its recorded black fallback.
"""

from __future__ import annotations

from types import SimpleNamespace

import pymupdf
import pytest
from babeldoc.magazine import drop_cap
from babeldoc.magazine import drop_cap_intent

from tests.minimal.test_drop_cap_keep_flatten import pdf_style


def test_scn_components_resolve_through_named_icc_space() -> None:
    style = pdf_style(instruction="/CS0 cs 0.741 0.744 0.326 scn")
    frozen = drop_cap_intent.freeze_color(
        style, {"CS0": "DeviceRGB"}.get
    )
    assert frozen.fill.rgb == (0.741, 0.744, 0.326)
    assert frozen.fill.source_space == "DeviceRGB"
    assert frozen.fill.operator == "scn"
    assert "cs:/CS0" in frozen.evidence
    assert "resolve:/CS0->DeviceRGB" in frozen.evidence


def test_unresolved_named_space_keeps_the_black_fallback() -> None:
    style = pdf_style(instruction="/CS0 cs 0.741 0.744 0.326 scn")
    frozen = drop_cap_intent.freeze_color(style, lambda _name: None)
    assert frozen.fill.rgb == (0.0, 0.0, 0.0)
    assert frozen.fill.operator == "default"
    assert "resolve:/CS0:unsupported" in frozen.evidence
    assert "scn:CS0:unsupported" in frozen.evidence


def test_no_resolver_behaves_exactly_as_before() -> None:
    style = pdf_style(instruction="/CS0 cs 0.741 0.744 0.326 scn")
    frozen = drop_cap_intent.freeze_color(style)
    assert frozen.fill.rgb == (0.0, 0.0, 0.0)
    assert "scn:CS0:unsupported" in frozen.evidence
    assert not any(item.startswith("resolve:") for item in frozen.evidence)


@pytest.fixture
def synthetic_source(tmp_path):
    """One page declaring /CS0 as ICCBased N=3 and /CS1 as a Separation."""
    document = pymupdf.open()
    page = document.new_page(width=200, height=200)
    icc = document.get_new_xref()
    document.update_object(icc, "<< /N 3 >>")
    # A fresh page's Resources is an indirect object and xref_set_key refuses
    # to write through indirects, so the keys are set on the dictionary itself.
    kind, value = document.xref_get_key(page.xref, "Resources")
    resources = int(value.split()[0]) if kind == "xref" else page.xref
    prefix = "" if kind == "xref" else "Resources/"
    document.xref_set_key(
        resources, f"{prefix}ColorSpace/CS0", f"[/ICCBased {icc} 0 R]"
    )
    document.xref_set_key(
        resources,
        f"{prefix}ColorSpace/CS1",
        "[/Separation /Spot /DeviceCMYK]",
    )
    document.xref_set_key(resources, f"{prefix}ColorSpace/CS2", "/DeviceCMYK")
    path = tmp_path / "synthetic.pdf"
    document.save(str(path))
    document.close()
    return path


def test_resolver_reads_page_resources(synthetic_source) -> None:
    resolver = drop_cap._ColorSpaceResolver(
        SimpleNamespace(input_file=str(synthetic_source))
    )
    try:
        resolve = resolver.for_character(
            1, SimpleNamespace(pdf_xobject=[]), SimpleNamespace(xobj_id=None)
        )
        assert resolve("CS0") == "DeviceRGB"
        assert resolve("CS1") is None
        assert resolve("CS2") == "DeviceCMYK"
        assert resolve("Missing") is None
    finally:
        resolver.close()


def test_resolver_and_capture_close_the_loop(synthetic_source) -> None:
    resolver = drop_cap._ColorSpaceResolver(
        SimpleNamespace(input_file=str(synthetic_source))
    )
    try:
        resolve = resolver.for_character(
            1, SimpleNamespace(pdf_xobject=[]), SimpleNamespace(xobj_id=None)
        )
        colored = drop_cap_intent.freeze_color(
            pdf_style(instruction="/CS0 cs 0.741 0.744 0.326 scn"), resolve
        )
        assert colored.fill.rgb == (0.741, 0.744, 0.326)
        separation = drop_cap_intent.freeze_color(
            pdf_style(instruction="/CS1 cs 0.5 scn"), resolve
        )
        assert separation.fill.rgb == (0.0, 0.0, 0.0)
        assert "scn:CS1:unsupported" in separation.evidence
    finally:
        resolver.close()


def test_resolver_survives_a_missing_source() -> None:
    resolver = drop_cap._ColorSpaceResolver(
        SimpleNamespace(input_file="does-not-exist.pdf")
    )
    try:
        resolve = resolver.for_character(
            1, SimpleNamespace(pdf_xobject=[]), SimpleNamespace(xobj_id=None)
        )
        assert resolve("CS0") is None
    finally:
        resolver.close()
