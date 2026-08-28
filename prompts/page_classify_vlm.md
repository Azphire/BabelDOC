# Page kind classification

You are looking at one rendered page of a printed periodical. Decide what kind
of page it is, choosing only from the vocabulary below.

## Vocabulary

Each line gives a name and a description of what such a page looks like. The
name, spelled exactly as it appears here, is the only value you may return.

A description lists what such a page usually carries, not a set of conditions
all of which must hold. A page still belongs to a kind when one of the things
its description mentions is absent -- the artwork above all, which many pages of
every kind do without -- and carrying something the description does not mention
does not rule that kind out. Weigh how the page is set against every
description and take the closest, rather than eliminating the kinds whose
descriptions are not satisfied word for word.

{taxonomy}

## Where this page sits

{page_context}

## Reference judgement

A deterministic classifier already scored this page from its geometry: counts,
areas, type sizes and column structure, with no sight of the image. Its ranked
candidates and their scores are below. It agrees with a human roughly nine
pages in ten, and where it is wrong it is usually because the distinction turns
on something the image shows and geometry cannot.

{deterministic_verdict}

## How to decide

- Judge the layout, not the subject: how the type is set, how the space is
  divided and what the artwork is doing carry the answer.
- Start from the reference judgement above and look for what would contradict
  it. Replace it when the image positively shows something else; keep it when
  the page could reasonably be read either way. A page you are unsure about is
  a page the reference judgement should keep.
- Where the question is whether a page starts a piece of writing or carries on
  one already under way, decide it on what is printed at the top of the page.
  A page that starts one announces itself: a title set far larger than the
  running text, usually with a line naming the writer or a short standing
  paragraph under it, and text beneath that begins rather than resumes. A page
  that carries one on has none of that -- it opens straight into running text
  at body size, at most under a small subheading, and its first line often
  completes a sentence begun elsewhere. The display type settles it on its own.
  A page with a large title, a byline and a standing paragraph is starting
  something even when it carries no picture at all, and a large picture at the
  top of a page is not by itself the mark of a beginning. An outsized initial
  letter on the first paragraph is another mark of a beginning.
- Return exactly one name from the vocabulary as `kind`.
- Report your own certainty as `confidence`, a number between 0 and 1.
- Some sheets are printed as two unrelated layouts at once: a band across the
  foot, a column down one side, one half of a spread, a panel occupying a
  clearly bounded region whose type, framing and purpose belong to a different
  kind of page from the rest. Give the larger or dominant layout as `kind` and
  name the other one in `secondary_kind`, saying in one short sentence which
  region it occupies in `secondary_reason`. Use both fields only for a sheet
  that really carries two layouts; where one layout fills the sheet, both are
  null.
- If nothing fits well, still return the closest name in the vocabulary and say
  so with a low confidence. Never invent a name that is not listed.

## Output

Reply with a single JSON object and nothing else: no commentary before or
after, and no code fence.

{"kind": "<a name from the vocabulary>", "confidence": 0.0, "secondary_kind": null, "secondary_reason": null}
