# Page kind classification

You are looking at one rendered page of a printed periodical. Decide what kind
of page it is, choosing only from the vocabulary below.

## Vocabulary

Each line gives a name and a description of what such a page looks like. The
name, spelled exactly as it appears here, is the only value you may return.

A description lists the visual role of a page, not a set of conditions all of
which must hold. Classify the printed page that is visible, in any language.
Do not depend on recognizing particular words: hierarchy, repeated entry
patterns, relative type size, framing, whitespace, columns and the balance of
artwork to prose are the primary evidence.

{taxonomy}

## Where this page sits

{page_context}

## Reference judgement

A deterministic classifier already scored this page from extracted geometry:
counts, areas, type sizes and column structure, with no sight of the rendered
page. Treat its ranking as a weak prior, not as an answer and not as
probabilities. Extraction can split CJK text into many apparent blocks, miss
artwork, or mistake display type for multiple modules. Prefer contradictory
visual evidence whenever the rendered page shows it.

{deterministic_verdict}

## Measured visual evidence

These measurements are additional evidence, not independent verdicts. Ratios
whose name ends in `_ratio` are page fractions except
`max_font_size_ratio`, which is the largest visible text size divided by the
median text size. A value near 1 means there is no strong display headline;
values far above 1 mean a strong size hierarchy. Counts and mean character
length can be distorted by extraction and language, so use them together with
the rendered page.

{page_features}

## How to decide

First identify the page's visible publishing role. Apply these distinctions in
order; they are valid across languages and magazine styles.

- A contents layout is a navigational index: several separate entry titles or
  section names are paired with page numbers, often in aligned rows or a
  repeated grid. A visual preview of upcoming stories, with thumbnails or
  captions paired with destination folio numbers, is also a contents layout;
  three destinations are enough. Chapter numbers, years, chart values or steps
  without destination page numbers are not contents. A contents region remains
  `toc` when it shares the sheet with an editor's letter, imprint or image. If
  the other layout is larger, return that other layout as `kind` and `toc` as
  `secondary_kind`; do not make the contents region disappear.
- `front_cover` identifies the publication or issue with a masthead or issue
  title. A sparse branded product or service promotion is `advertisement`, not
  a cover. `masthead` is staff, publisher, address, copyright and imprint
  furniture. `editorial` is a continuous editor's letter or signed foreword;
  ordinary front-of-book prose is not automatically editorial.
- An `article_opener` visibly announces a named story: a headline markedly
  larger than body text, commonly a deck, byline or author block, and then the
  beginning of prose. Artwork is optional. An `article_body` continues prose
  at body size, commonly in columns. Subheads, pull quotes, drop caps, pictures,
  charts and changes of type size inside one continuous story do not turn a
  body page into `sidebar_heavy`. A single page-wide headline followed by one
  deck and one article is an opener even when extraction reports many columns
  or font sizes. Conversely, a highlighted pull quote, callout box or subhead
  surrounded by the same continuing article is not an independent module.
  For an opener-versus-body dispute, use the measured hierarchy as a check: a
  `max_font_size_ratio` above about 3 together with substantial text coverage
  is strong opener evidence, while a value below about 2.7 with substantial
  prose is strong body evidence. A cover, contents page, editorial, masthead,
  advertisement or section divider keeps its own role despite large type.
- A `photo_spread` is an editorial photograph or illustration that dominates
  the page while running prose is absent or minor. It may carry a display
  phrase, quotation or caption and need not be full bleed. A large image plus
  substantial continuing prose is still `article_body`; a named story with a
  clear headline/byline/opening-prose apparatus is `article_opener`. Large
  display words alone do not make an opener: a phrase above or beside a
  page-dominating image, with no byline, deck or substantial opening prose, is
  a `photo_spread`. Commercial branding, product focus or a call to action
  instead indicates `advertisement`.
- `sidebar_heavy` requires several visibly independent modules, briefs, boxes
  or side stories. Multiple columns or many font sizes inside one article are
  insufficient. `infographic` requires data, a process, map, chart or labelled
  explanatory graphic to be the central communication, not merely an ordinary
  photograph beside prose.
- `contributors` is a collection of multiple short biographies or profiles,
  often with one portrait per person. An author/byline block or several quoted
  experts inside one continuing story does not make a contributors page.
- `interview` requires a repeated question-and-answer pattern. One portrait and
  one large quotation are not an interview. A front-of-book signed message,
  often with one portrait or signature, is `editorial` rather than an article
  opener.
- `section_divider` is a sparse thematic break or section title without the
  byline/deck/body apparatus of a named article. It can be a full-colour branded
  introduction carrying a short mission statement, or a large section word
  with preview images and folio numbers. Use the remaining vocabulary by the
  same visible-role principle.

Use page position only as supporting evidence for front and back covers. Never
infer an alternating pattern or a page kind merely from its page number.

Before answering, explicitly check the rendered page for four things: whether
it contains repeated title-plus-page-number entries; whether it presents one
continuous story or several independent stories; whether a large headline is
followed by real opening prose; and whether artwork dominates with only a
display phrase or caption. Use those observations even when they contradict
the deterministic ranking, especially when that ranking says `sidebar_heavy`,
`masthead` or `contributors` on a CJK page.

- Return exactly one name from the vocabulary as `kind`.
- Report your own certainty as `confidence`, a number between 0 and 1.
- Some sheets are printed as two unrelated layouts at once: a band across the
  foot, a column down one side, one half of a spread, a panel occupying a
  clearly bounded region whose type, framing and purpose belong to a different
  kind of page from the rest. Give the larger or dominant layout as `kind` and
  name the other one in `secondary_kind`, saying in one short sentence which
  region it occupies in `secondary_reason`. A navigational contents region is
  always worth reporting as one of the two layouts. Otherwise use both fields
  only for a sheet that really carries two layouts; where one layout fills the
  sheet, both are null.
- If nothing fits well, still return the closest name in the vocabulary and say
  so with a low confidence. Never invent a name that is not listed.

## Output

Reply with a single JSON object and nothing else: no commentary before or
after, and no code fence.

{"kind": "<a name from the vocabulary>", "confidence": 0.0, "secondary_kind": null, "secondary_reason": null}
