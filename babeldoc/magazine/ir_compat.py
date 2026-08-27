"""Round-trip and backward-compatibility checks for the extended IL schema.

The IL gained optional page-level and paragraph-level attributes. Nothing in
the pipeline writes them yet, so the two properties that matter are: a document
carrying the new attributes survives an XML round trip unchanged, and a
checkpoint written before the schema change still parses with every new field
left at ``None``.

XML is the only round-trippable IL format, and its canonical form is the
re-serialised form ``to_xml(from_xml(x))``: the first serialisation of a
pipeline document normalises boolean and float literals, so byte comparisons
are made between canonical forms only.
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from pathlib import Path

from xsdata.exceptions import ConverterWarning

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter
from babeldoc.magazine.checkpoint import read_checkpoint_text

# Fields added to the IL by batch B1, as Python attribute names.
NEW_PAGE_FIELDS = (
    "page_kind",
    "page_kind_conf",
    "page_kind_source",
)
NEW_PARAGRAPH_FIELDS = (
    "chain_id",
    "chain_index",
    "drop_cap_candidate",
    "drop_cap_decision",
    "segment_sentence_start",
    "segment_sentence_end",
)

# Values used by the round-trip probe; each one differs from the field default
# and from any other value of the same type.
_PAGE_PROBE = {
    "page_kind": "probe-kind",
    "page_kind_conf": 0.75,
    "page_kind_source": "deterministic",
}
_PARAGRAPH_PROBE = {
    "chain_id": "probe-chain",
    "chain_index": 3,
    "drop_cap_candidate": True,
    "drop_cap_decision": "flatten",
    "segment_sentence_start": 2,
    "segment_sentence_end": 5,
}


@lru_cache(maxsize=1)
def _converter() -> XMLConverter:
    return XMLConverter()


def normalize_xml(xml: str) -> str:
    """Strip line-ending and trailing-whitespace noise before byte comparison."""
    lines = xml.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def canonical_xml(docs: il_version_1.Document) -> str:
    """Return the canonical XML form of ``docs``."""
    converter = _converter()
    return converter.to_xml(converter.from_xml(converter.to_xml(docs)))


def read_document(path: str | Path) -> il_version_1.Document:
    """Parse an IL XML file, tolerating converter warnings but not errors.

    Documents written by the upstream pipeline can carry attribute values that
    do not match their declared type (see W-B0-02); xsdata reports those as
    ``ConverterWarning`` and keeps the value. Any other warning is promoted to
    an error so that schema regressions cannot pass unnoticed.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warnings.simplefilter("ignore", ConverterWarning)
        return _converter().from_xml(read_checkpoint_text(path))


def roundtrip_equal(docs: il_version_1.Document) -> bool:
    """True when re-serialising ``docs`` through XML is stable."""
    first = canonical_xml(docs)
    second = _converter().to_xml(_converter().from_xml(first))
    return normalize_xml(first) == normalize_xml(second)


def build_probe_document() -> il_version_1.Document:
    """Build a minimal one-page one-paragraph document with all new fields set."""
    box = il_version_1.Box(x=0.0, y=0.0, x2=10.0, y2=10.0)
    style = il_version_1.PdfStyle(
        font_id="probe-font",
        font_size=12.0,
        graphic_state=il_version_1.GraphicState(),
    )
    paragraph = il_version_1.PdfParagraph(
        box=il_version_1.Box(x=1.0, y=1.0, x2=9.0, y2=4.0),
        pdf_style=style,
        unicode="probe",
        **_PARAGRAPH_PROBE,
    )
    page = il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=box),
        cropbox=il_version_1.Cropbox(box=box),
        pdf_paragraph=[paragraph],
        base_operations=il_version_1.BaseOperations(value=""),
        page_number=0,
        unit="point",
        **_PAGE_PROBE,
    )
    return il_version_1.Document(page=[page], total_pages=1)


def assert_new_fields_roundtrip() -> il_version_1.Document:
    """Check that every new field survives an XML round trip unchanged."""
    docs = build_probe_document()
    parsed = _converter().from_xml(_converter().to_xml(docs))

    if len(parsed.page) != 1 or len(parsed.page[0].pdf_paragraph) != 1:
        raise AssertionError(f"probe document lost structure: pages={len(parsed.page)}")

    page = parsed.page[0]
    for name, expected in _PAGE_PROBE.items():
        actual = getattr(page, name)
        if actual != expected:
            raise AssertionError(f"page.{name}: expected {expected!r}, got {actual!r}")

    paragraph = page.pdf_paragraph[0]
    for name, expected in _PARAGRAPH_PROBE.items():
        actual = getattr(paragraph, name)
        if actual != expected:
            raise AssertionError(
                f"paragraph.{name}: expected {expected!r}, got {actual!r}"
            )

    if not roundtrip_equal(docs):
        raise AssertionError("probe document XML is not stable across a round trip")
    return parsed


def unset_new_fields(docs: il_version_1.Document) -> list[str]:
    """Return a report of every new field that is set on ``docs``."""
    populated: list[str] = []
    for structural_position, page in enumerate(docs.page):
        for name in NEW_PAGE_FIELDS:
            if getattr(page, name) is not None:
                populated.append(f"page[{structural_position}].{name}")
        for para_index, paragraph in enumerate(page.pdf_paragraph):
            for name in NEW_PARAGRAPH_FIELDS:
                if getattr(paragraph, name) is not None:
                    populated.append(
                        f"page[{structural_position}].pdf_paragraph[{para_index}].{name}"
                    )
    return populated


def assert_backward_compat(old_xml_path: str | Path) -> il_version_1.Document:
    """Check that a checkpoint written before the schema change still parses.

    Every new field must be ``None``, which proves both that the attributes are
    optional and that nothing in the pipeline populates them yet.
    """
    path = Path(old_xml_path)
    docs = read_document(path)
    if docs.total_pages != len(docs.page):
        raise AssertionError(
            f"{path}: total_pages={docs.total_pages} but {len(docs.page)} pages parsed"
        )
    populated = unset_new_fields(docs)
    if populated:
        raise AssertionError(f"{path}: new fields unexpectedly set: {populated}")
    return docs
