# B6 session one — article grouping, delivery report

## What changed and why

Two questions were being answered by one policy flag. `starts_article` is the
chain detector's prior, introduced in B4: running text does not continue *into*
this page. Grouping needs a different one: an article *begins* on this page.
The two agree on the flowing page types and disagree on every piece of
furniture, because a contents page or a bought page is somewhere text begins
without being somewhere an article begins.

Reading the first flag as the second put 25 of the corpus's 31 pages down as
article openers, made every advertisement its own article, and attached the
opening body page of AramcoWorld's p30 feature to the contents page in front of
it. The `unassigned` branch the rule is written around was unreachable, because
every chain-ineligible type in the vocabulary also declared `starts_article`.

`opens_article` is now declared beside it, optional and defaulting to false, on
`article_opener`, `editorial` and `interview`. No `starts_article` declaration
moved, which assertion 01d checks against `batch-b6.0` directly, so the B4
detector's inputs are byte-identical.

## Grouping rule

- a page whose policy declares `opens_article` opens an article;
- a page declaring `chain_eligible` and `translate` but not `opens_article`
  joins the article that is running, and opens one if none is;
- any other page belongs to no article, takes no page with it, and does not
  close the article above it, so an article continues across it;
- a chain crossing a boundary this walk drew joins the two articles it touches,
  paragraph level evidence being authoritative over the page level prior.

`article_map.json` is the stage's only output. Nothing enters the intermediate
language, the stage leaves no checkpoint of its own, and it has no notion of a
contents page: the TOC comparison is a report-side matter driven by
`corpus/manifest.json`.

## Result on the corpus

14 articles over 31 pages, 12 pages belonging to no article.

| sample | article | member pages | title excerpt |
| --- | --- | --- | --- |
| Courier-en | A1 | 1 | Contents |
| | A2 | 2, 3, 4 | How Indigenous knowledge drives |
| | **A3** | **5, 6** | Brazil: lessons from the water people |
| | A4 | 7, 8 | The struggle for benefit-sharing |
| | unassigned | none | |
| Vogue-en | — | none | |
| | unassigned | 1, 2, 3 | two advertisements and the contents page |
| CERNCourier-en | A1 | 1 | CERNCOURIER July/August 2026 ... |
| | A2 | 3 | Policy |
| | A3 | 4 | C |
| | unassigned | 2 | contents sheet |
| FD-en | A1 | 6 | Kaleidoscope |
| | A2 | 7 | Point of View |
| | A3 | 8 | Franc Democracy |
| | unassigned | 1, 2, 3, 4, 5 | cover, two house ads, contents, masthead |
| AramcoWorld-en | A1 | 4 | PAINSTAKING RESTORATION IS A CALLING |
| | A2 | 5, 6 | Tawfiq Al Juhani drove at great speed, ... |
| | A3 | 7 | Reviews |
| | A4 | 8 | Reviews |
| | unassigned | 1, 2, 3 | cover, masthead, contents |

Read against `corpus/chain_labels.user.json`, whose notes state the issue page
each excerpt page came from, 13 of the 14 articles are right. The exception is
marked above and is the known limitation below.

The AramcoWorld case the batch was opened on is fixed: pages 1 to 3 stand
outside every article and page 4 opens the first one instead of joining the
contents page. Assertion 05 states exactly that.

## TOC comparison

Reported side by side, no judgement, driven by the registry rather than by
anything the stage knows.

| sample | registry `toc_pages` | heading-class paragraphs on them | articles detected |
| --- | --- | --- | --- |
| Courier-en | 1 | 10 | 4 |
| Vogue-en | 3 | 10 | 0 |
| CERNCourier-en | 2 | 24 | 3 |
| FD-en | 3 | 18 | 3 |
| AramcoWorld-en | 3 | 8 | 4 |

The two columns are not comparable as they stand: a contents page lists the
whole issue while a sample is a short excerpt of it, and the heading count is a
paragraph count rather than an entry count. The pairing is here to be looked at
over a full issue, which the corpus does not yet carry.

## Known limitation — Courier A3

Courier's excerpt is not contiguous in the issue: PDF pages 1 to 8 are the
contents page, issue pp. 4, 5, 6, 9, 38, 12 and 13, in that order. A3 therefore
merges issue p9 with issue p38, two unrelated articles, because p6 classifies as
`article_body` and the article opened on p5 is the one running when the walk
reaches it.

No page level or paragraph level signal available today separates them. The two
pages are set in the same measure at the same size, and the adjudicator's own
note for this boundary records the same trap from the other direction: p5's tail
dangles mid-sentence and its continuation is a page the excerpt does not carry.
The evidence that would settle it is the printed folio, which says p5 is issue 9
and p6 is issue 38 -- the `folio_adjacency` signal left over from B4. That is
where the fix belongs.

It is not special-cased here. A rule that broke an article on this pair without
folio evidence would have to break it on some geometric coincidence, and the
same coincidence holds on AramcoWorld pages 5 and 6, which are one article.
