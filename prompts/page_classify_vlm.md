# Page kind classification

You are looking at one rendered page of a printed periodical. Decide what kind
of page it is, choosing only from the vocabulary below.

## Vocabulary

Each line gives a name and a description of what such a page looks like. The
name, spelled exactly as it appears here, is the only value you may return.

{taxonomy}

## Where this page sits

{page_context}

## Reference judgement

A deterministic classifier already scored this page from its geometry: counts,
areas, type sizes and column structure, with no sight of the image. Its ranked
candidates and their scores are below, for reference only. It is right more
often than not, and it is known to be weak wherever the distinction depends on
whether a page begins a piece of writing or continues one, because that
difference barely shows in geometry. Where the image tells you otherwise,
override it.

{deterministic_verdict}

## How to decide

- Judge the layout, not the subject: how the type is set, how the space is
  divided and what the artwork is doing carry the answer.
- Return exactly one name from the vocabulary as `kind`.
- Report your own certainty as `confidence`, a number between 0 and 1.
- A single sheet occasionally carries two separate layouts side by side or one
  above the other. Only in that case, name the second layout in
  `secondary_kind`, and say in one short sentence which region of the sheet it
  occupies in `secondary_reason`. In every other case both fields are null.
- If nothing fits well, still return the closest name in the vocabulary and say
  so with a low confidence. Never invent a name that is not listed.

## Output

Reply with a single JSON object and nothing else: no commentary before or
after, and no code fence.

{"kind": "<a name from the vocabulary>", "confidence": 0.0, "secondary_kind": null, "secondary_reason": null}
