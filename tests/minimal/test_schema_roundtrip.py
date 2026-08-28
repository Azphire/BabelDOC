from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import MISSING
from dataclasses import fields
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "babeldoc" / "format" / "pdf" / "document_il"
RNG_NAMESPACE = {"rng": "http://relaxng.org/ns/structure/1.0"}
XSD_NAMESPACE = {"xs": "http://www.w3.org/2001/XMLSchema"}

NEW_ATTRIBUTES = {
    "pageKind": ("page", il_version_1.Page, "page_kind", "string"),
    "pageKindConf": ("page", il_version_1.Page, "page_kind_conf", "float"),
    "pageKindSource": ("page", il_version_1.Page, "page_kind_source", "string"),
    "chainId": ("pdfParagraph", il_version_1.PdfParagraph, "chain_id", "string"),
    "chainIndex": ("pdfParagraph", il_version_1.PdfParagraph, "chain_index", "int"),
    "dropCapCandidate": (
        "pdfParagraph",
        il_version_1.PdfParagraph,
        "drop_cap_candidate",
        "boolean",
    ),
    "dropCapDecision": (
        "pdfParagraph",
        il_version_1.PdfParagraph,
        "drop_cap_decision",
        "string",
    ),
    "segmentSentenceStart": (
        "pdfParagraph",
        il_version_1.PdfParagraph,
        "segment_sentence_start",
        "int",
    ),
    "segmentSentenceEnd": (
        "pdfParagraph",
        il_version_1.PdfParagraph,
        "segment_sentence_end",
        "int",
    ),
}

PAGE_VALUES = {
    "page_kind": "article_body",
    "page_kind_conf": 0.875,
    "page_kind_source": "deterministic",
}
PARAGRAPH_VALUES = {
    "chain_id": "synthetic-chain",
    "chain_index": 2,
    "drop_cap_candidate": True,
    "drop_cap_decision": "keep",
    "segment_sentence_start": 3,
    "segment_sentence_end": 7,
}


def _probe_document(*, include_new_fields: bool) -> il_version_1.Document:
    box = il_version_1.Box(x=0.0, y=0.0, x2=100.0, y2=100.0)
    paragraph = il_version_1.PdfParagraph(
        box=il_version_1.Box(x=5.0, y=5.0, x2=95.0, y2=20.0),
        pdf_style=il_version_1.PdfStyle(
            font_id="probe-font",
            font_size=10.0,
            graphic_state=il_version_1.GraphicState(),
        ),
        unicode="probe",
        **(PARAGRAPH_VALUES if include_new_fields else {}),
    )
    page = il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=box),
        cropbox=il_version_1.Cropbox(box=box),
        pdf_paragraph=[paragraph],
        base_operations=il_version_1.BaseOperations(value=""),
        page_number=0,
        unit="point",
        **(PAGE_VALUES if include_new_fields else {}),
    )
    return il_version_1.Document(page=[page], total_pages=1)


def _assert_field_values(document: il_version_1.Document) -> None:
    page = document.page[0]
    paragraph = page.pdf_paragraph[0]
    for name, expected in PAGE_VALUES.items():
        assert getattr(page, name) == expected
    for name, expected in PARAGRAPH_VALUES.items():
        assert getattr(paragraph, name) == expected


def _rnc_element_body(text: str, element: str) -> str:
    match = re.search(rf"\n{re.escape(element)}\s*=\s*\n\s*element\s+\w+\s*{{", text)
    assert match is not None
    index = match.end()
    depth = 1
    while depth:
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    return text[match.end() : index - 1]


def test_old_documents_parse_with_new_fields_unset() -> None:
    converter = XMLConverter()
    xml = converter.to_xml(_probe_document(include_new_fields=False))

    assert not any(attribute in xml for attribute in NEW_ATTRIBUTES)
    parsed = converter.from_xml(xml)

    page = parsed.page[0]
    paragraph = page.pdf_paragraph[0]
    assert all(getattr(page, name) is None for name in PAGE_VALUES)
    assert all(getattr(paragraph, name) is None for name in PARAGRAPH_VALUES)


def test_new_fields_survive_xml_and_json_converter_roundtrips() -> None:
    converter = XMLConverter()
    document = _probe_document(include_new_fields=True)

    from_xml = converter.from_xml(converter.to_xml(document))
    json_payload = json.loads(converter.to_json(document))
    from_json = json.loads(json.dumps(json_payload, sort_keys=True))

    _assert_field_values(from_xml)
    for name, expected in PAGE_VALUES.items():
        assert from_json["page"][0][name] == expected
    for name, expected in PARAGRAPH_VALUES.items():
        assert from_json["page"][0]["pdf_paragraph"][0][name] == expected


def test_schema_quartet_defines_the_same_optional_attributes() -> None:
    python_fields = {
        model: {item.name: item for item in fields(model)}
        for model in {entry[1] for entry in NEW_ATTRIBUTES.values()}
    }
    rnc_text = (SCHEMA_DIR / "il_version_1.rnc").read_text(encoding="utf-8")
    rng_root = ET.parse(SCHEMA_DIR / "il_version_1.rng").getroot()  # noqa: S314
    xsd_root = ET.parse(SCHEMA_DIR / "il_version_1.xsd").getroot()  # noqa: S314

    for attribute, (element, model, field_name, schema_type) in NEW_ATTRIBUTES.items():
        python_field = python_fields[model][field_name]
        assert python_field.default is None
        assert python_field.default_factory is MISSING
        assert python_field.metadata["name"] == attribute
        assert python_field.metadata["type"] == "Attribute"

        rnc_owner = "Page" if element == "page" else "PDFParagraph"
        rnc_body = _rnc_element_body(rnc_text, rnc_owner)
        assert re.search(
            rf"attribute\s+{re.escape(attribute)}\s*{{\s*xsd:{schema_type}\s*}}\?",
            rnc_body,
        )

        rng_element = rng_root.find(f".//rng:element[@name='{element}']", RNG_NAMESPACE)
        assert rng_element is not None
        rng_attribute = rng_element.find(
            f".//rng:optional/rng:attribute[@name='{attribute}']",
            RNG_NAMESPACE,
        )
        assert rng_attribute is not None
        rng_data = rng_attribute.find("rng:data", RNG_NAMESPACE)
        assert rng_data is not None
        assert rng_data.get("type") == schema_type

        xsd_element = xsd_root.find(f"xs:element[@name='{element}']", XSD_NAMESPACE)
        assert xsd_element is not None
        xsd_attribute = xsd_element.find(
            f"xs:complexType/xs:attribute[@name='{attribute}']",
            XSD_NAMESPACE,
        )
        assert xsd_attribute is not None
        assert xsd_attribute.get("type") == f"xs:{schema_type}"
        assert xsd_attribute.get("use") != "required"
