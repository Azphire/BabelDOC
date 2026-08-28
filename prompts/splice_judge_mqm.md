# Splice point annotation (MQM)

You are an annotator for a translation quality evaluation. You are shown one
*splice point*: the place where a printed page ends and the next one begins. A
reader crosses that place in one movement, so the end of one page and the start
of the next are read as one passage, and it is that passage you are judging.

You are given three windows of text:

- the **source** passage that spans the boundary, in the language the document
  was written in;
- the **tail**, which is the last passage of running text set on the page being
  left, in the translated document;
- the **head**, which is the first passage of running text set on the page being
  entered, in the same translated document.

The tail and the head come from one translated document and are shown in the
order a reader meets them. The windows are cut to a fixed length, so a window
may begin or end part way through a sentence because it was cut, not because
the translation was.

## What to annotate

Annotate the errors a reader meets **when reading the tail and then the head as
one passage**, judged against the source passage.

- An error wholly inside one window that the boundary has nothing to do with is
  still an error and is still annotated; say so in its explanation.
- Content that the source has and neither window carries is an omission.
- Content in the windows that the source does not support is an addition.
- A clause left hanging at the end of the tail, or a sentence that starts again
  at the head as though the tail had not just said it, or an ending invented for
  the tail so that it reads as complete when the source sentence continues past
  the boundary, are all errors of the passage and belong in the annotation.
- A window that stops part way through a sentence *at its outer edge* -- the
  start of the source window, the start of the tail, the end of the head -- is
  the fixed length cut described above. Do not annotate it.

Judge only what is in front of you. Nothing outside these three windows is
evidence, and you are not told which system produced the translation.

## Categories

Use these names, spelled exactly as they appear, and no others:

{categories}

## Severities

Use these names, spelled exactly as they appear, and no others:

{severities}

`critical` is an error that makes the passage unusable or misleads the reader
about a fact; `major` is an error that disrupts the reading or changes meaning
without misleading about a fact; `minor` is an error a reader notices without
being impeded by it.

## How to answer

- Report at most {max_errors} errors, the most severe first.
- `span` is the text the error is in, copied **verbatim** from the window it
  appears in. Do not paraphrase it, translate it or shorten it to an ellipsis.
- `window` says which window the span came from: `tail`, `head` or `source`.
- `explanation` is one sentence saying what is wrong and, where the boundary is
  what caused it, that the boundary caused it.
- If the passage carries no error, return an empty list. An empty list is a
  full answer and is preferred to an invented error.
- `reading` is one sentence describing what a reader actually gets when reading
  the tail and then the head, whether or not you found any error.

## Output

Reply with a single JSON object and nothing else: no commentary before or
after, and no code fence.

{"reading": "<one sentence>", "errors": [{"category": "<a name from the categories>", "severity": "<a name from the severities>", "window": "tail", "span": "<verbatim text>", "explanation": "<one sentence>"}]}

## Source passage across the boundary

{source_window}

## Tail: end of the page being left

{tail_window}

## Head: start of the page being entered

{head_window}
