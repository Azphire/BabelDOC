"""Place every short paragraph of a page in one of a closed set of classes.

Why this exists
---------------

A page whose declared policy says its lines are records is a page the fragment
stitch is not allowed to touch, and B10.3 excluded such a page from the stitch
whole. That is right for the vertical rule, which joins paragraphs down a
column and would happily join two records; it is too wide for the horizontal
rule, which works inside one line band and by construction cannot cross a
record boundary. So the horizontal rule can be let back in -- but only once it
is known what the short paragraphs on those pages actually are.

There are two shapes and they want opposite repairs. A **true fracture** is one
written word the paragraph finder left as several paragraphs: ``NAD`` ``+``
``i`` ``n`` ``f`` ``us`` ``i`` ``ons``. Stitching those is the whole point. A
**duplicate layer** is text the page holds more than once, and stitching that
builds a paragraph saying everything twice; what it wants is for the surplus to
be blanked. Applying either repair to the other case damages the page, so the
class is established first, and a fragment this audit cannot place is left
exactly as it is.

How a class is established
--------------------------

The audit reads the page twice, through two pieces of code that share nothing:
the pipeline's own intermediate language, and PyMuPDF's word extractor. Neither
is treated as the truth. What is used is where they disagree.

Within one line band, both readings are reduced to a run of characters with the
whitespace taken out. Where the two runs are equal, the band holds each of its
characters once, in order, and every short paragraph in it is a piece of a word
the independent reading holds whole -- **true_fracture** -- which is checked by
asking whether the paragraph's span begins at a word start and ends at a word
end. Where the intermediate language's run holds characters the independent one
does not, those characters are a layer the page holds twice and the paragraphs
sitting on them are **duplicate_layer**. The reverse is **dropped_text**. Where
the two runs hold the same characters in a different order, the band is an
**extraction_order_fault**: something below both of these passes read the page
out of order, which is not this batch's to repair and is reported as it stands.

Everything else is **undetermined**, and a fragment that is undetermined gets no
repair at all.

Nothing here calls a model, and nothing here writes to the document. The output
is one sidecar per document.

The command line over this module is ``tools/source_audit.py``, which is how
the audit is run on its own against a working directory that already exists.
The pipeline calls :func:`audit_pages` directly, at the point the stitch runs.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from babeldoc.magazine.line_split import ATOMIC
from babeldoc.magazine.line_split import SPLITTABLE
from babeldoc.magazine.page_features import ConfigError
from babeldoc.magazine.page_features import validate_bounded_config

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "source_audit.json"

CLASSES_KEY = "classes"
DESCRIPTION_KEY = "description"

CLASS_TRUE_FRACTURE = "true_fracture"
CLASS_DUPLICATE_LAYER = "duplicate_layer"
CLASS_DROPPED_TEXT = "dropped_text"
CLASS_ORDER_FAULT = "extraction_order_fault"
CLASS_UNDETERMINED = "undetermined"

REPORT_NAME = "source_audit.report.json"

# Every kind of composition a paragraph may be made of. Read from the one place
# in this package that names them, so a kind added there is a kind this reads
# and no second list can fall behind the first.
_COMPOSITION_KINDS = (*SPLITTABLE, *ATOMIC)


class SourceAuditError(ConfigError):
    """Raised when the source audit configuration is unusable."""


@dataclass(frozen=True)
class AuditConfig:
    band_overlap_ratio: float
    max_fragment_chars: int
    min_evidence_chars: int
    classes: tuple[str, ...]


def load_audit_config(path: str | None = None) -> AuditConfig:
    config_path = CONFIG_PATH if path is None else Path(path)
    with config_path.open(encoding="utf-8") as f:
        raw = json.load(f)
    flat = {key: value for key, value in raw.items() if key != CLASSES_KEY}
    parameters = validate_bounded_config(flat, config_path)
    declared = raw.get(CLASSES_KEY)
    if not isinstance(declared, list) or not declared:
        raise SourceAuditError(f"{config_path.name}: {CLASSES_KEY} must be a list")
    implemented = {
        CLASS_TRUE_FRACTURE,
        CLASS_DUPLICATE_LAYER,
        CLASS_DROPPED_TEXT,
        CLASS_ORDER_FAULT,
        CLASS_UNDETERMINED,
    }
    if set(declared) != implemented:
        raise SourceAuditError(
            f"{config_path.name}: {CLASSES_KEY} declares {sorted(declared)} and "
            f"this module implements {sorted(implemented)}"
        )
    return AuditConfig(
        band_overlap_ratio=float(parameters["band_overlap_ratio"]),
        max_fragment_chars=int(parameters["max_fragment_chars"]),
        min_evidence_chars=int(parameters["min_evidence_chars"]),
        classes=tuple(declared),
    )


# --- the two readings -------------------------------------------------------


def normalise(text: str) -> str:
    """One comparable form: compatibility composed, with the whitespace gone.

    Whitespace goes because the disagreement being looked for is about which
    characters a page holds and in what order, and the two readings space a
    line differently by construction: one groups by layout region and the other
    by PDF text object.
    """
    folded = unicodedata.normalize("NFKC", text)
    return "".join(char for char in folded if not char.isspace())


def _field(item, name: str):
    """One field of either reading of the intermediate language.

    The audit is run two ways: over a checkpoint file, where the document is
    JSON, and inside the pipeline, where it is the generated dataclasses. The
    field names are the same in both because the JSON is written from those
    classes, so one accessor serves both and the audit has one implementation
    rather than two that could drift.
    """
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def il_paragraphs(document: dict, page_number: int) -> list[dict]:
    """The paragraphs of one page, in the order the intermediate language holds."""
    pages = [
        page
        for page in document.get("page", ())
        if page.get("page_number") == page_number
    ]
    if not pages:
        return []
    return list(pages[0].get("pdf_paragraph") or ())


def _box(raw: object) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    try:
        return (
            float(_field(raw, "x")),
            float(_field(raw, "y")),
            float(_field(raw, "x2")),
            float(_field(raw, "y2")),
        )
    except (TypeError, ValueError):
        return None


def _composition_characters(composition) -> list:
    """The drawn characters one composition holds, whichever kind it is.

    A paragraph's composition is rewritten as it moves down the pipeline: the
    paragraph finder leaves lines, the style pass leaves runs of one style, and
    a formula or a lone character stands on its own. The audit runs at the point
    the stitch runs and reads a checkpoint from anywhere, so it reads every kind
    rather than the one kind it happened to be written against. A composition
    holding a unicode run and no characters draws nothing this can measure and
    contributes nothing.
    """
    for name in _COMPOSITION_KINDS:
        holder = _field(composition, name)
        if holder is None:
            continue
        if name == "pdf_character":
            return [holder]
        return list(_field(holder, "pdf_character") or ())
    return []


def paragraph_characters(paragraph: dict, index: int) -> list[dict]:
    """One record per drawn character of one paragraph, with its own box.

    The audit bands characters rather than lines. The intermediate language's
    own line boxes are not lines here: on the page this was written against, a
    paragraph beginning at the end of one row and running into the next carries
    a single line box eighteen points tall, spanning both rows, and a band built
    from it holds two rows of two columns. A character box is the smallest thing
    either reading has, and it is the only one whose extent is a line's.
    """
    characters = []
    for composition in _field(paragraph, "pdf_paragraph_composition") or ():
        for character in _composition_characters(composition):
            text = _field(character, "char_unicode") or ""
            if not normalise(text):
                continue
            # The em box rather than the inked one. Two characters set on one
            # baseline at one size have the same em box and different inked
            # boxes -- an ``a`` and a ``p`` differ by the descender -- so
            # banding by the inked box puts the letters of a word on different
            # lines.
            box = _box(_field(character, "box"))
            if box is None:
                continue
            characters.append(
                {
                    "paragraph": index,
                    "text": text,
                    "x": box[0],
                    "y": box[1],
                    "x2": box[2],
                    "y2": box[3],
                }
            )
    return characters


def independent_words(pdf_path: Path, page_number: int) -> list[dict]:
    """One reading of the page that shares no code with the pipeline's.

    PyMuPDF measures from the top of the page and the intermediate language
    from the bottom, so the boxes are put on the intermediate language's axis
    here and nowhere else.
    """
    import pymupdf

    with pymupdf.open(pdf_path) as document:
        page = document[page_number]
        height = page.rect.height
        words = page.get_text("words")
    return [
        {
            "text": word,
            "x": float(x0),
            "y": height - float(y1),
            "x2": float(x1),
            "y2": height - float(y0),
        }
        for x0, y0, x1, y1, word, _block, _line, _no in words
    ]


# --- bands ------------------------------------------------------------------


def _overlaps(low_a, high_a, low_b, high_b, ratio: float) -> bool:
    """Whether two vertical extents stand on one line.

    The overlap has to reach the ratio of *both* heights rather than of the
    shorter one. Measuring against the shorter alone lets anything tall swallow
    anything short standing beside it -- a rotated credit rail running the
    height of the page overlaps most of the shorter of itself and any line it
    crosses -- and a rail is not on the line it crosses.
    """
    overlap = min(high_a, high_b) - max(low_a, low_b)
    if overlap <= 0:
        return False
    height_a = high_a - low_a
    height_b = high_b - low_b
    if height_a <= 0 or height_b <= 0:
        return False
    return overlap / height_a >= ratio and overlap / height_b >= ratio


def line_bands(items: list[dict], config: AuditConfig) -> list[list[int]]:
    """Group items into the lines they stand on, by vertical overlap with a seed.

    Each band keeps the extent of the item that opened it rather than growing to
    hold every member. A growing extent is transitive, and on a page of stacked
    blocks transitivity puts the whole column in one band; a seed keeps a band
    the width of one line, which is what the horizontal rule works across.
    """
    ordered = sorted(
        range(len(items)),
        key=lambda index: (
            -(items[index]["y2"] + items[index]["y"]) / 2,
            items[index]["x"],
        ),
    )
    bands: list[list[int]] = []
    seeds: list[tuple[float, float]] = []
    for index in ordered:
        item = items[index]
        placed = False
        for position, (low, high) in enumerate(seeds):
            if _overlaps(item["y"], item["y2"], low, high, config.band_overlap_ratio):
                bands[position].append(index)
                placed = True
                break
        if not placed:
            bands.append([index])
            seeds.append((item["y"], item["y2"]))
    return [sorted(band, key=lambda index: items[index]["x"]) for band in bands]


# --- the three tests --------------------------------------------------------


def _runs(texts: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """One character run out of several texts, and each text's span inside it."""
    run = ""
    spans = []
    for text in texts:
        piece = normalise(text)
        spans.append((len(run), len(run) + len(piece)))
        run += piece
    return run, spans


def _word_edges(words: list[str]) -> tuple[set[int], set[int]]:
    """Where the independent reading says a word starts and where it ends."""
    starts, ends = set(), set()
    cursor = 0
    for word in words:
        piece = normalise(word)
        if not piece:
            continue
        starts.add(cursor)
        cursor += len(piece)
        ends.add(cursor)
    return starts, ends


def align_band(
    paragraph_texts: list[str], word_texts: list[str]
) -> tuple[str, list[tuple], dict]:
    """Align the band's two readings, and say what the alignment shows.

    The verdict is about the band as a whole and is reported for context. What
    a fragment is placed by is the alignment itself, because the two readings
    disagree about a band for reasons that have nothing to do with the fragment
    standing in it: a rotated credit rail crossing the band is a word the
    independent reading files here and the intermediate language files on its
    own line, and a band holding one is not thereby a band that lost text.

    So the two directions of disagreement are kept apart. Characters the
    intermediate language holds and the independent reading does not are a
    layer the page carries twice, and they are the fragment's business.
    Characters the independent reading holds and the intermediate language does
    not, *in this band*, may be either loss or filing, and are reported without
    being charged to a fragment.
    """
    il_run, spans = _runs(paragraph_texts)
    ind_run, _ = _runs(word_texts)
    opcodes = SequenceMatcher(None, ind_run, il_run, autojunk=False).get_opcodes()
    inserted = [
        (j1, j2)
        for tag, _i1, _i2, j1, j2 in opcodes
        if tag in ("insert", "replace") and j2 > j1
    ]
    deleted = [
        (i1, i2)
        for tag, i1, i2, _j1, _j2 in opcodes
        if tag in ("delete", "replace") and i2 > i1
    ]
    evidence = {
        "il_chars": len(il_run),
        "independent_chars": len(ind_run),
        "paragraph_spans": [list(span) for span in spans],
        "inserted_spans": [list(span) for span in inserted],
        "deleted_spans": [list(span) for span in deleted],
    }
    if il_run == ind_run:
        verdict = CLASS_TRUE_FRACTURE
    elif sorted(il_run) == sorted(ind_run):
        verdict = CLASS_ORDER_FAULT
    elif inserted and not deleted:
        verdict = CLASS_DUPLICATE_LAYER
    elif deleted and not inserted:
        verdict = CLASS_DROPPED_TEXT
    else:
        verdict = CLASS_UNDETERMINED
    return verdict, opcodes, evidence


def map_span(span: tuple[int, int], opcodes: list[tuple]) -> tuple[int, int] | None:
    """Where a span of the intermediate language's run stands in the independent one.

    None where the span is not carried by one equal block: a span that spills
    across an edit is a span the two readings do not agree on, and there is no
    position in the other reading to place it at.
    """
    for tag, i1, _i2, j1, j2 in opcodes:
        if tag != "equal":
            continue
        if j1 <= span[0] and span[1] <= j2:
            return (i1 + (span[0] - j1), i1 + (span[1] - j1))
    return None


def _spans_overlap(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(span[0] < high and low < span[1] for low, high in spans)


def audit_page(
    page,
    words: list[dict],
    page_label: int,
    config: AuditConfig,
) -> list[dict]:
    """One record per fragment of one page, each carrying its class and evidence.

    A fragment is a paragraph short enough to be one. It is placed by the band
    its characters stand in, and a long paragraph sharing that band contributes
    only the characters it has there, which is what keeps a block of running
    text from dragging the whole of itself into a neighbour's evidence.
    """
    # A page, or the list of paragraphs already taken out of one. The pipeline
    # holds the first and the command line over a checkpoint holds the second.
    held = _field(page, "pdf_paragraph")
    paragraphs = list(page if held is None else held)

    characters: list[dict] = []
    fragments: set[int] = set()
    for index, paragraph in enumerate(paragraphs):
        own = paragraph_characters(paragraph, index)
        if not own:
            continue
        if (
            len(normalise(_field(paragraph, "unicode") or ""))
            <= config.max_fragment_chars
        ):
            fragments.add(index)
        characters.extend(own)
    if not characters:
        return []

    records = []
    for band in line_bands(characters, config):
        members = [characters[position] for position in band]
        # A word joins the band when it stands on a line with one of the band's
        # own characters, not with the union of them. The union of a band set in
        # two sizes is taller than either, and a taller extent reaches the row
        # above and the row below.
        band_words = sorted(
            (
                word
                for word in words
                if any(
                    _overlaps(
                        word["y"],
                        word["y2"],
                        item["y"],
                        item["y2"],
                        config.band_overlap_ratio,
                    )
                    for item in members
                )
            ),
            key=lambda word: word["x"],
        )
        verdict, opcodes, evidence = align_band(
            [item["text"] for item in members],
            [word["text"] for word in band_words],
        )
        starts, ends = _word_edges([word["text"] for word in band_words])
        spans = [tuple(span) for span in evidence["paragraph_spans"]]
        inserted = [tuple(span) for span in evidence["inserted_spans"]]

        # One span per paragraph present in the band, from its first character
        # to its last. A paragraph whose characters are not consecutive in the
        # band is interleaved with another and is not placed here.
        present: dict[int, list[int]] = {}
        for position, item in enumerate(members):
            present.setdefault(item["paragraph"], []).append(position)

        for index, positions in sorted(present.items()):
            if index not in fragments:
                continue
            consecutive = positions == list(range(positions[0], positions[-1] + 1))
            span = (spans[positions[0]][0], spans[positions[-1]][1])
            text = "".join(members[position]["text"] for position in positions)
            piece = normalise(text)
            mapped = None if not consecutive else map_span(span, opcodes)
            # What the rest of the band says, which is where a repeat would be
            # found. Read from the other paragraphs of the band rather than
            # from the whole page: a duplicate layer is drawn where the text it
            # repeats is drawn.
            neighbours = normalise(
                "".join(
                    members[other]["text"]
                    for other in range(len(members))
                    if other not in positions
                )
            )
            if not consecutive:
                fragment_class = CLASS_UNDETERMINED
                detail = (
                    "this paragraph's characters are not consecutive in the band, "
                    "so it has no one span to be placed by"
                )
            elif not band_words:
                fragment_class = CLASS_UNDETERMINED
                detail = (
                    "the independent reading holds nothing in this band, so there "
                    "is no second reading to place this paragraph against"
                )
            elif _spans_overlap(span, inserted) and piece and piece in neighbours:
                fragment_class = CLASS_DUPLICATE_LAYER
                detail = (
                    "these characters are ones the independent reading of the band "
                    "does not hold, and another paragraph of the band holds them "
                    "too, so the page carries them twice"
                )
            elif _spans_overlap(span, inserted):
                fragment_class = CLASS_UNDETERMINED
                detail = (
                    "these characters are ones the independent reading of the band "
                    "does not hold, but no other paragraph of the band holds them "
                    "either, so what the surplus is has not been established"
                )
            elif mapped is None:
                fragment_class = CLASS_UNDETERMINED
                detail = (
                    "this paragraph's span crosses a disagreement between the two "
                    "readings, so it has no position in the independent one"
                )
            elif verdict == CLASS_ORDER_FAULT:
                fragment_class = CLASS_ORDER_FAULT
                detail = (
                    "the band's two readings hold the same characters in a "
                    "different order, which is a fault below both of these passes"
                )
            else:
                whole_word = mapped[0] in starts and mapped[1] in ends
                fragment_class = (
                    CLASS_UNDETERMINED if whole_word else CLASS_TRUE_FRACTURE
                )
                detail = (
                    "the independent reading holds these characters in the same "
                    "order and this paragraph's span "
                    + ("is" if whole_word else "is not")
                    + " a whole word of it"
                )
            if len(piece) < config.min_evidence_chars:
                fragment_class = CLASS_UNDETERMINED
                detail = (
                    f"{len(piece)} character(s) is below the shortest fragment the "
                    f"audit will place"
                )
            records.append(
                {
                    "page": page_label,
                    "paragraph": f"p{page_label}#{index}",
                    "text": text,
                    "chars": len(piece),
                    "class": fragment_class,
                    "band_verdict": verdict,
                    "band_members": len(present),
                    "band_span": list(span),
                    "independent_span": None if mapped is None else list(mapped),
                    "detail": detail,
                    "band_evidence": {
                        "il_chars": evidence["il_chars"],
                        "independent_chars": evidence["independent_chars"],
                        "inserted_spans": evidence.get("inserted_spans", []),
                        "deleted_spans": evidence.get("deleted_spans", []),
                    },
                }
            )
    return sorted(
        records,
        key=lambda record: (
            record["page"],
            int(record["paragraph"].split("#")[1]),
        ),
    )


# --- driving ----------------------------------------------------------------


def audit_document(
    checkpoint: Path, pdf: Path, pages: list[int] | None, config: AuditConfig
) -> dict:
    with checkpoint.open(encoding="utf-8") as f:
        document = json.load(f)
    labels = [int(page.get("page_number", 0)) + 1 for page in document.get("page", ())]
    wanted = labels if pages is None else [label for label in labels if label in pages]
    records = []
    for label in wanted:
        records.extend(
            audit_page(
                il_paragraphs(document, label - 1),
                independent_words(pdf, label - 1),
                label,
                config,
            )
        )
    counts: dict[str, int] = dict.fromkeys(config.classes, 0)
    for record in records:
        counts[record["class"]] += 1
    return {
        "checkpoint": str(checkpoint),
        "pdf": str(pdf),
        "pages": wanted,
        "band_overlap_ratio": config.band_overlap_ratio,
        "max_fragment_chars": config.max_fragment_chars,
        "min_evidence_chars": config.min_evidence_chars,
        "counts": counts,
        "fragments": records,
    }


def write_report(working_dir: Path, record: dict) -> Path:
    """Put the audit beside the run it was made of."""
    path = Path(working_dir) / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True, ensure_ascii=False)
    return path
