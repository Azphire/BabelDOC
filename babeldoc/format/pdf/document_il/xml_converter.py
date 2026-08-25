import copy
from pathlib import Path

import orjson
from xsdata.formats.converter import Converter
from xsdata.formats.converter import converter
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.frontend.il_creater_active_support import (
    LazyPassthroughInstruction,
)


def _orjson_default(value):
    if isinstance(value, LazyPassthroughInstruction):
        return value.materialize()
    raise TypeError


class _LazyPassthroughConverter(Converter):
    """Write a deferred passthrough instruction as the string it stands for.

    The schema declares ``passthroughPerCharInstruction`` a string, and the
    frontend sometimes fills it with a wrapper that renders that string only
    when something asks. The JSON writer above asks; this is the XML writer
    asking the same question, because xsdata dispatches on the concrete class
    and had no answer for this one. Without it a document holding a deferred
    instruction can be written as JSON and not as XML, and the checkpoint is
    XML -- one reader of the same field disagreeing with the other about
    whether the document can be written at all.

    Deserialisation returns the value untouched: what comes back from XML is
    already the materialised string, which is what the eager path produces too,
    so a round trip through either writer lands on the same type.
    """

    def deserialize(self, value, **kwargs):
        return value

    def serialize(self, value, **kwargs) -> str:
        return value.materialize()


converter.register_converter(LazyPassthroughInstruction, _LazyPassthroughConverter())


class XMLConverter:
    def __init__(self):
        self.parser = XmlParser()
        config = SerializerConfig(indent="  ")
        context = XmlContext()
        self.serializer = XmlSerializer(context=context, config=config)

    def write_xml(self, document: il_version_1.Document, path: str):
        with Path(path).open("w", encoding="utf-8") as f:
            f.write(self.to_xml(document))

    def read_xml(self, path: str) -> il_version_1.Document:
        with Path(path).open(encoding="utf-8") as f:
            return self.from_xml(f.read())

    def to_xml(self, document: il_version_1.Document) -> str:
        return self.serializer.render(document)

    def from_xml(self, xml: str) -> il_version_1.Document:
        return self.parser.from_string(
            xml,
            il_version_1.Document,
        )

    def deepcopy(self, document: il_version_1.Document) -> il_version_1.Document:
        return copy.deepcopy(document)
        # return self.from_xml(self.to_xml(document))

    def to_json(self, document: il_version_1.Document) -> str:
        return orjson.dumps(
            document,
            option=orjson.OPT_APPEND_NEWLINE
            | orjson.OPT_INDENT_2
            | orjson.OPT_SORT_KEYS,
            default=_orjson_default,
        ).decode()

    def write_json(self, document: il_version_1.Document, path: str):
        with Path(path).open("w", encoding="utf-8") as f:
            f.write(self.to_json(document))
