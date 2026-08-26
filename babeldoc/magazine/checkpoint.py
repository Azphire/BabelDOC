"""XML checkpoints for the BabelDOC intermediate language (IL).

The upstream pipeline already writes per-stage JSON dumps in debug mode, but
JSON is a write-only inspection format. XML is the only round-trippable IL
format, so checkpoints are written as XML and can be reloaded into a
``Document`` object. A JSON sibling is written next to each XML checkpoint for
human inspection only.

XML 1.0 cannot carry a handful of codepoints in any form, not even as a
character reference, and a PDF whose font names an Adobe glyph list control
glyph puts one of them in the IL. Such a document is escaped on the way out and
restored on the way in, so the checkpoint still holds what the parser produced.
The JSON sibling is written from the document itself, escape and all left off:
JSON can represent those codepoints, and the inspection format showing what the
parser saw is worth more than the two files agreeing character for character.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import re
import zipfile
from functools import lru_cache
from pathlib import Path

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter
from babeldoc.magazine.resource_paths import config_path

logger = logging.getLogger(__name__)

CHECKPOINT_PREFIX = "checkpoint."

# A set of checkpoints kept for the long term is kept as one archive rather than
# as a directory of files. They are XML and JSON of one shape, so they compress
# by about an order of magnitude, and the whole set of a run is read start to
# finish or not at all. A member is named the way a file in the directory was:
# ``<name>.checkpoints.zip/checkpoint.11_typesetting.xml`` is a path a caller
# builds by joining, and every reader below resolves it.
CHECKPOINT_ARCHIVE_SUFFIX = ".zip"

# The complement of the XML 1.0 Char production, restricted to what a Python
# string can hold: the C0 controls other than tab, newline and carriage return,
# the surrogate halves, and the two non-characters ending the BMP. Every one of
# them is below U+10000, which is why the escape below needs four hex digits and
# no more.
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")

# Lead character of the escape, escaped by doubling. Doubling is what makes the
# encoding unambiguous rather than merely reversible for the strings we happen
# to meet: a document already containing an escape sequence literally still
# round trips, because its lead was doubled on the way out.
_ESCAPE_LEAD = "\\"

# Digits an escaped codepoint is written with.
_ESCAPE_WIDTH = 4

# Introduces an escaped codepoint, following the lead.
_ESCAPE_TAG = "u"

# Written into a file whose strings were escaped, and read back as the
# instruction to decode. A document needing no escape is written exactly as it
# was before and carries no marker, so a checkpoint from an earlier batch reads
# unchanged and a literal lead in one is never mistaken for an escape.
_ESCAPE_MARKER = "<!-- magazine-checkpoint-escape v1 -->"

_CONFIG_PATH = config_path("checkpoint_stages.json")


class CheckpointError(RuntimeError):
    """Raised when a checkpoint cannot be written or fails its integrity check."""


@lru_cache(maxsize=1)
def _stage_config() -> tuple[tuple[str, ...], int]:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        config = json.load(f)
    return tuple(config["stages"]), int(config["ordinal_width"])


@lru_cache(maxsize=1)
def sidecar_products() -> tuple[dict[str, str], ...]:
    """Return every declared sidecar a magazine run may leave in its working dir.

    A checkpoint holds the intermediate language; a sidecar holds what a stage
    found that the frozen schema has nowhere for. Both are products of a run, so
    both are declared, and a stage writing only a sidecar is in the inventory
    even though it appends no checkpoint.
    """
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        config = json.load(f)
    return tuple(dict(entry) for entry in config.get("sidecars", ()))


def sidecar_names() -> tuple[str, ...]:
    """Filenames of the declared sidecars, in declaration order."""
    return tuple(entry["name"] for entry in sidecar_products())


@lru_cache(maxsize=1)
def _converter() -> XMLConverter:
    return XMLConverter()


def stage_names() -> tuple[str, ...]:
    """Return the declared pipeline stage names in execution order."""
    return _stage_config()[0]


def checkpoint_stem(stage_name: str) -> str:
    """Build the checkpoint file stem for a stage, without extension.

    The stage ordinal is zero padded so that lexicographic order over the
    resulting filenames equals pipeline execution order.
    """
    stages, width = _stage_config()
    try:
        ordinal = stages.index(stage_name) + 1
    except ValueError:
        raise CheckpointError(
            f"unknown checkpoint stage {stage_name!r}; "
            f"declare it in {_CONFIG_PATH.name}"
        ) from None
    return f"{CHECKPOINT_PREFIX}{ordinal:0{width}d}_{stage_name}"


def escape_text(text: str) -> str:
    """Encode one string so XML can carry it, reversibly.

    The lead is doubled wherever it already occurs, which is what keeps the
    encoding a bijection: without that, a string spelling an escape sequence
    out would decode to something it never was.
    """
    pieces: list[str] = []
    for char in text:
        if char == _ESCAPE_LEAD:
            pieces.append(_ESCAPE_LEAD * 2)
        elif _XML_ILLEGAL.match(char):
            pieces.append(
                f"{_ESCAPE_LEAD}{_ESCAPE_TAG}{ord(char):0{_ESCAPE_WIDTH}x}"
            )
        else:
            pieces.append(char)
    return "".join(pieces)


def unescape_text(text: str) -> str:
    """Decode one string ``escape_text`` produced.

    A lead followed by anything else is not something the encoder emits; it is
    passed through rather than rejected, so a hand edited checkpoint still
    loads and says what it says.
    """
    pieces: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != _ESCAPE_LEAD:
            pieces.append(char)
            index += 1
            continue
        following = text[index + 1 : index + 2]
        if following == _ESCAPE_LEAD:
            pieces.append(_ESCAPE_LEAD)
            index += 2
            continue
        digits = text[index + 2 : index + 2 + _ESCAPE_WIDTH]
        if following == _ESCAPE_TAG and len(digits) == _ESCAPE_WIDTH:
            try:
                pieces.append(chr(int(digits, 16)))
            except ValueError:
                pieces.append(char)
                index += 1
                continue
            index += 2 + _ESCAPE_WIDTH
            continue
        pieces.append(char)
        index += 1
    return "".join(pieces)


def _map_strings(node, transform):
    """Apply ``transform`` to every string in an IL object tree, in place."""
    if dataclasses.is_dataclass(node):
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            mapped = _map_strings(value, transform)
            if mapped is not value:
                setattr(node, field.name, mapped)
        return node
    if isinstance(node, list):
        for position, item in enumerate(node):
            mapped = _map_strings(item, transform)
            if mapped is not item:
                node[position] = mapped
        return node
    if isinstance(node, str):
        return transform(node)
    return node


def _holds_illegal(node) -> bool:
    """Whether any string in an IL object tree is one XML cannot carry."""
    if dataclasses.is_dataclass(node):
        return any(
            _holds_illegal(getattr(node, field.name))
            for field in dataclasses.fields(node)
        )
    if isinstance(node, list):
        return any(_holds_illegal(item) for item in node)
    if isinstance(node, str):
        return _XML_ILLEGAL.search(node) is not None
    return False


def to_checkpoint_xml(docs: il_version_1.Document) -> str:
    """Serialise a document, escaping it only if XML cannot carry it as it is.

    A document XML can carry is serialised exactly as before and carries no
    marker, so nothing that was written by an earlier batch moves and nothing
    that reads one has to know about the escape.
    """
    converter = _converter()
    if not _holds_illegal(docs):
        return converter.to_xml(docs)
    escaped = copy.deepcopy(docs)
    _map_strings(escaped, escape_text)
    return f"{converter.to_xml(escaped)}\n{_ESCAPE_MARKER}\n"


def from_checkpoint_xml(text: str) -> il_version_1.Document:
    """Parse a checkpoint, restoring the escape when the file declares one."""
    docs = _converter().from_xml(text)
    if _ESCAPE_MARKER in text:
        _map_strings(docs, unescape_text)
    return docs


def dump_checkpoint(
    docs: il_version_1.Document,
    translation_config,
    stage_name: str,
) -> Path:
    """Write an XML checkpoint of ``docs`` for ``stage_name``.

    A same-named ``.json`` file is written alongside for human inspection. The
    XML path is returned.
    """
    stem = checkpoint_stem(stage_name)
    xml_path = Path(translation_config.get_working_file_path(f"{stem}.xml"))
    json_path = Path(translation_config.get_working_file_path(f"{stem}.json"))

    with xml_path.open("w", encoding="utf-8") as f:
        f.write(to_checkpoint_xml(docs))
    _converter().write_json(docs, str(json_path))
    logger.debug("wrote IL checkpoint %s", xml_path)
    return xml_path


def archive_member(path: str | Path) -> tuple[Path, str] | None:
    """The archive and member ``path`` names, or None where it names a file.

    A path is inside an archive when one of its components is an archive that
    exists and something follows it. Nothing is opened to decide this, so the
    question is cheap enough to ask on every read.
    """
    path = Path(path)
    for index, part in enumerate(path.parts):
        if not part.endswith(CHECKPOINT_ARCHIVE_SUFFIX):
            continue
        member = "/".join(path.parts[index + 1 :])
        archive = Path(*path.parts[: index + 1])
        if member and archive.is_file():
            return archive, member
    return None


def read_checkpoint_text(path: str | Path) -> str:
    """The text of one checkpoint, whether it is a file or inside an archive."""
    found = archive_member(path)
    if found is None:
        return Path(path).read_text(encoding="utf-8")
    archive, member = found
    with zipfile.ZipFile(archive) as bundle:
        return bundle.read(member).decode("utf-8")


def checkpoint_container(path: str | Path) -> Path:
    """The archive standing for a checkpoint directory, or the directory itself.

    Callers name the directory; what is on the disk may be either, and which one
    is not something a caller should have to know.
    """
    path = Path(path)
    archive = path.with_name(path.name + CHECKPOINT_ARCHIVE_SUFFIX)
    if not path.is_dir() and archive.is_file():
        return archive
    return path


def checkpoint_paths(container: str | Path, pattern: str = "*") -> list[Path]:
    """Every checkpoint in a directory or an archive, as paths that can be read.

    A path into an archive does not exist on the filesystem and is not meant to:
    it is what ``read_checkpoint_text`` and ``load_checkpoint`` accept, and it
    keeps the name a caller would have used for the file.
    """
    container = checkpoint_container(container)
    if container.is_dir():
        return sorted(container.glob(pattern))
    if not container.is_file():
        return []
    with zipfile.ZipFile(container) as bundle:
        names = [name for name in bundle.namelist() if not name.endswith("/")]
    return sorted(
        container / name for name in names if Path(name).match(pattern)
    )


def write_checkpoint_archive(paths, destination: Path) -> Path:
    """Pack the given checkpoint files into one archive and return its path.

    Members are named by their filename alone, which is what makes an archive a
    drop-in replacement for the directory the files were in.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as bundle:
        for item in sorted(Path(path) for path in paths):
            if item.is_file():
                bundle.write(item, item.name)
    return destination


def load_checkpoint(path: str | Path) -> il_version_1.Document:
    """Read an XML checkpoint back into a ``Document``.

    Verifies that the declared ``total_pages`` matches the number of pages
    actually present, which catches truncated or hand-edited checkpoints.
    """
    path = Path(path)
    docs = from_checkpoint_xml(read_checkpoint_text(path))
    if docs.total_pages != len(docs.page):
        raise CheckpointError(
            f"corrupt checkpoint {path}: total_pages={docs.total_pages} "
            f"but {len(docs.page)} page elements present"
        )
    return docs
