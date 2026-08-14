"""M1, the mid-unit page-break rate: how often a break lands inside a sentence.

The background chapter promises "a mid-unit page-break rate and a block
conservation invariant, defined formally in Chapter~\\ref{chap:eval}" and gives
no equation for either, so this docstring is the definition and the paper will
quote it.

Let a run produce pages :math:`1..P`. A *boundary* is a place where the reader
leaves one region of set text and enters the next: the page boundaries
:math:`(n, n+1)` for :math:`n = 1..P-1`, and, reported as a second series, the
column boundaries inside a page, one for each step from a column to the column
right of it. Let :math:`B` be the boundary set of one series and let
:math:`\\tau(b)` be the *tail* of boundary :math:`b` -- the last paragraph of the
region being left, in derived reading order. Let :math:`c(b)` be the last
non-space character of the last rendered line of :math:`\\tau(b)`, read after
trailing closing marks, combining marks and format characters have been stripped
from it. Let :math:`T` be the declared set of sentence enders and let
:math:`D(b)` hold when :math:`\\tau(b)` is a chain member that is continued by a
further member and whose redistribution recorded no sentence interval, which is
the shape a display line takes by design. Then

.. math::

    \\mathrm{MBR} = \\frac{1}{|B|}\\sum_{b \\in B}
        \\mathbf{1}\\big(c(b) \\notin T \\;\\wedge\\; \\neg D(b)\\big),

and the strict form divides instead by :math:`|B| - |\\{b : D(b)\\}|`, which is
the same numerator over the boundaries the metric can be answerable for. Both
are reported: the first is comparable across runs of one document because its
denominator is a property of the document, the second is the rate among the
boundaries where ending mid-sentence would be a defect rather than the design.

Four commitments the definition makes, each of which is a choice that could have
gone the other way:

*It is read from geometry, never from the string layer.* :math:`c(b)` is the
last character of the last **rendered line**, found by banding the laid out
characters of the tail by their boxes, which is the method batch b5.3 section 1b
established and the number in ledger row A-08 was read with. A paragraph's
``unicode`` still carries the markup the translation round trip was carried out
in, and its last character is frequently a tag.

*The tail is the last endpoint candidate, not the last box.* The order and the
filtering are ``chain_signals.page_candidates``, shared with the chain detector,
so the metric and the detector are answering about the same boundary. A folio,
a credit rail or a boxed aside is not the thing the reader was reading when the
page ended, and letting one stand in for the tail measures the furniture.

*A display continuation is not a defect.* Ledger row A-08 records both title
chain members ending on an ordinary character with sentence interval ``-1/-1``:
the ``proportional`` strategy has no sentence structure to cut at, so ending
mid-phrase is what that strategy does. :math:`D(b)` puts those in their own
bucket instead of counting them as failures of the thing that produced them.

*Only the horizontal axis is measured.* Banding by box and taking the bottom
line's rightmost character is the reading end for a left-to-right horizontal
script and is not for anything else. A tail the intermediate language marks
``vertical`` is reported with the verdict ``axis_unsupported`` and takes part in
no rate, so an unmeasurable boundary is visible rather than silently counted as
sound.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from dataclasses import field

from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import chain_signals
from babeldoc.magazine.drop_cap import paragraph_reference
from babeldoc.magazine.metrics import MetricsConfig
from babeldoc.magazine.metrics import load_metrics_config
from babeldoc.magazine.metrics import rounded

# The two boundary series. A page boundary is the reader leaving a page; a
# column boundary is the reader leaving a column for the one right of it.
PAGE_SERIES = "page"
COLUMN_SERIES = "column"
SERIES = (PAGE_SERIES, COLUMN_SERIES)

# The verdicts one boundary can take. Only OPEN is in the numerator; DESIGNED is
# the display continuation the redistribution strategy produces on purpose, and
# the last two are boundaries the method cannot answer for and says so.
CLOSED = "closed"
DESIGNED = "designed"
OPEN = "open"
AXIS_UNSUPPORTED = "axis_unsupported"
NO_TAIL = "no_tail"
VERDICTS = (CLOSED, DESIGNED, OPEN, AXIS_UNSUPPORTED, NO_TAIL)

# Verdicts that are measurable at all, which is what a rate has a denominator of
# once the unmeasurable ones are set aside.
_ANSWERABLE = (CLOSED, DESIGNED, OPEN)

# Character categories that carry no punctuation of their own and would hide the
# ender they sit on. The same two the chain detector strips.
_INVISIBLE_CATEGORIES = ("Mn", "Cf")

# The sentence interval a redistribution records when it had no sentence to cut
# at, as the chain translation writes it into the intermediate language.
_NO_SENTENCE = -1


@dataclass(frozen=True)
class Tail:
    """The end of one region of set text, as this metric reads it."""

    reference: str
    page_index: int
    paragraph_index: int
    layout_label: str
    column_index: int
    chain_id: str | None
    vertical: bool
    last_line_text: str
    last_character: str | None
    last_character_x: float | None
    last_character_y: float | None


@dataclass(frozen=True)
class Boundary:
    """One place a reader leaves set text, and what the text did on the way out."""

    series: str
    page_index: int
    to_page_index: int
    from_column: int
    to_column: int
    verdict: str
    tail: Tail | None
    truth_link: bool | None = None

    @property
    def label(self) -> str:
        """How the corpus ground truth names this boundary, in 1-based pages."""
        if self.series == PAGE_SERIES:
            return f"{self.page_index + 1}->{self.to_page_index + 1}"
        return f"p{self.page_index + 1}c{self.from_column}->c{self.to_column}"

    def as_record(self) -> dict:
        return {
            "series": self.series,
            "label": self.label,
            "page_index": self.page_index,
            "to_page_index": self.to_page_index,
            "from_column": self.from_column,
            "to_column": self.to_column,
            "verdict": self.verdict,
            "truth_link": self.truth_link,
            "tail": None if self.tail is None else vars(self.tail),
        }


@dataclass
class SeriesResult:
    """One boundary series: its boundaries and the rate over them."""

    series: str
    boundaries: list[Boundary] = field(default_factory=list)

    def count(self, verdict: str) -> int:
        return sum(1 for item in self.boundaries if item.verdict == verdict)

    @property
    def answerable(self) -> int:
        return sum(1 for item in self.boundaries if item.verdict in _ANSWERABLE)

    @property
    def rate(self) -> float | None:
        """The numerator over every boundary the series has, answerable or not."""
        if not self.boundaries:
            return None
        return self.count(OPEN) / len(self.boundaries)

    @property
    def strict_rate(self) -> float | None:
        """The numerator over the boundaries ending mid-sentence would be a defect at."""
        denominator = self.answerable - self.count(DESIGNED)
        if denominator <= 0:
            return None
        return self.count(OPEN) / denominator

    def as_record(self, digits: int) -> dict:
        return {
            "series": self.series,
            "boundaries_total": len(self.boundaries),
            "answerable": self.answerable,
            **{f"{verdict}_count": self.count(verdict) for verdict in VERDICTS},
            "rate": rounded(self.rate, digits),
            "strict_rate": rounded(self.strict_rate, digits),
            "boundaries": [item.as_record() for item in self.boundaries],
        }


def _centre(box) -> tuple[float, float] | None:
    if box is None or any(
        value is None for value in (box.x, box.y, box.x2, box.y2)
    ):
        return None
    return ((float(box.x) + float(box.x2)) / 2, (float(box.y) + float(box.y2)) / 2)


def _strip_to_ender(text: str, closers) -> str:
    """One line with what hides its sentence ender taken off the end."""
    text = text.rstrip()
    changed = True
    while text and changed:
        changed = False
        while text and text[-1] in closers:
            text = text[:-1].rstrip()
            changed = True
        while text and unicodedata.category(text[-1]) in _INVISIBLE_CATEGORIES:
            text = text[:-1]
            changed = True
    return text


def _last_character(line) -> tuple[str | None, float | None, float | None]:
    """The rightmost non-space character of one rendered line, with where it sits."""
    for character in reversed(line):
        text = character.char_unicode or ""
        if not text.strip():
            continue
        centre = _centre(character.box)
        return text, None if centre is None else centre[0], (
            None if centre is None else centre[1]
        )
    return None, None, None


def _chain_last_index(document: il_version_1.Document) -> dict[str, int]:
    """The greatest member index each chain reaches, over the whole document."""
    reach: dict[str, int] = {}
    for page in document.page:
        for paragraph in page.pdf_paragraph:
            chain_id = paragraph.chain_id
            if chain_id is None or paragraph.chain_index is None:
                continue
            index = int(paragraph.chain_index)
            reach[chain_id] = max(reach.get(chain_id, index), index)
    return reach


def _is_designed(paragraph, chain_reach: dict[str, int]) -> bool:
    """Whether this tail is a display continuation rather than a cut sentence.

    Three conditions together, because any one of them alone catches paragraphs
    that are nothing of the kind: the paragraph belongs to a chain, a further
    member of that chain carries on after it, and its redistribution recorded no
    sentence interval, which is what the ``proportional`` strategy leaves behind
    when the unit it cut had no sentence structure to cut at.
    """
    chain_id = paragraph.chain_id
    if chain_id is None or paragraph.chain_index is None:
        return False
    if int(paragraph.chain_index) >= chain_reach.get(chain_id, -1):
        return False
    start = paragraph.segment_sentence_start
    end = paragraph.segment_sentence_end
    return (start is None or int(start) == _NO_SENTENCE) and (
        end is None or int(end) == _NO_SENTENCE
    )


def _candidates_with_columns(page, chain_config) -> list[tuple[object, str, list, int]]:
    """The page's endpoint candidates in reading order, each with its column.

    The banding is the chain detector's, reached through its own helpers rather
    than restated here: a metric that split columns its own way would report a
    boundary the detector does not believe in.
    """
    candidates = chain_signals.page_candidates(page, chain_config)
    if not candidates:
        return []
    frame = chain_signals._page_frame(page)  # noqa: SLF001 - one column rule, shared
    if frame is None:
        return []
    gap = (frame.x2 - frame.x) * chain_config["column_split_gap_ratio"]
    lefts = [chain_signals.line_left(item[2][0]) for item in candidates]
    bands = chain_signals._column_bands(lefts, gap)  # noqa: SLF001 - as above
    return [
        (paragraph, label, lines, chain_signals._band_index(bands, left))  # noqa: SLF001
        for (paragraph, label, lines), left in zip(candidates, lefts, strict=True)
    ]


def _tail_of(page, page_index, item) -> Tail:
    paragraph, label, lines, column = item
    # By identity rather than by equality: two paragraphs of one page can hold
    # equal field values, and the reference has to name the one that is here.
    index = next(
        position
        for position, item in enumerate(page.pdf_paragraph)
        if item is paragraph
    )
    text = chain_signals.line_text(lines[-1])
    character, x, y = _last_character(lines[-1])
    return Tail(
        reference=paragraph_reference(page_index + 1, index),
        page_index=page_index,
        paragraph_index=index,
        layout_label=label,
        column_index=column,
        chain_id=paragraph.chain_id,
        vertical=bool(paragraph.vertical),
        last_line_text=text,
        last_character=character,
        last_character_x=x,
        last_character_y=y,
    )


def _verdict_of(tail: Tail, paragraph, chain_reach, chain_config) -> str:
    if tail.vertical:
        return AXIS_UNSUPPORTED
    stripped = _strip_to_ender(tail.last_line_text, chain_config["terminal_closers"])
    if not stripped:
        return NO_TAIL
    if stripped[-1] in chain_config["terminal_punctuation"]:
        return CLOSED
    if _is_designed(paragraph, chain_reach):
        return DESIGNED
    return OPEN


def boundaries_of(
    document: il_version_1.Document,
    chain_config: dict,
    truth: dict[str, bool] | None = None,
) -> dict[str, SeriesResult]:
    """Every boundary of a produced document, judged, in both series.

    ``truth`` is the corpus adjudication for this sample keyed the way
    ``corpus/chain_labels.user.json`` keys it, and is carried through onto the
    page boundaries so a report can split the rate by whether a human called the
    boundary a cut unit. It steers nothing: the verdict is read off the geometry
    either way.
    """
    chain_reach = _chain_last_index(document)
    pages = list(document.page)
    per_page = [_candidates_with_columns(page, chain_config) for page in pages]

    results = {name: SeriesResult(series=name) for name in SERIES}

    for index in range(len(pages) - 1):
        items = per_page[index]
        tail = None
        verdict = NO_TAIL
        if items:
            paragraph = items[-1][0]
            tail = _tail_of(pages[index], index, items[-1])
            verdict = _verdict_of(tail, paragraph, chain_reach, chain_config)
        results[PAGE_SERIES].boundaries.append(
            Boundary(
                series=PAGE_SERIES,
                page_index=index,
                to_page_index=index + 1,
                from_column=-1,
                to_column=-1,
                verdict=verdict,
                tail=tail,
                truth_link=None if truth is None else truth.get(f"{index + 1}->{index + 2}"),
            )
        )

    for index, items in enumerate(per_page):
        columns = sorted({item[3] for item in items})
        for position, column in enumerate(columns[:-1]):
            in_column = [item for item in items if item[3] == column]
            paragraph = in_column[-1][0]
            tail = _tail_of(pages[index], index, in_column[-1])
            results[COLUMN_SERIES].boundaries.append(
                Boundary(
                    series=COLUMN_SERIES,
                    page_index=index,
                    to_page_index=index,
                    from_column=column,
                    to_column=columns[position + 1],
                    verdict=_verdict_of(tail, paragraph, chain_reach, chain_config),
                    tail=tail,
                )
            )
    return results


def measure(
    document: il_version_1.Document,
    chain_config: dict,
    truth: dict[str, bool] | None = None,
    config: MetricsConfig | None = None,
) -> dict:
    """M1 over one produced document, both series, with every boundary shown."""
    config = config or load_metrics_config()
    results = boundaries_of(document, chain_config, truth)
    digits = config.report_float_digits
    return {
        "metric": "mid_unit_page_break_rate",
        "pages": len(document.page),
        "series": {
            name: results[name].as_record(digits) for name in SERIES
        },
        "rate": rounded(results[PAGE_SERIES].rate, digits),
        "strict_rate": rounded(results[PAGE_SERIES].strict_rate, digits),
    }
