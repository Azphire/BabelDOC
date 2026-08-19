# reviews/

The two-pass human review loop lives here, one pair of files per sample.

| file | written by | read by |
| --- | --- | --- |
| `<sample>.review.json` | the pipeline, on every run with `magazine_hitl_export` | a human |
| `<sample>.review.html` | the pipeline, from the draft above | a human |
| `<sample>.decisions.json` | a human, by hand | the pipeline, with `magazine_hitl_apply` |

The pipeline never writes a decisions file. An empty object is the whole of
what a machine may put there, so that a rerun cannot adopt its own previous
draft as a ruling.

## Passes

1. Run with `magazine_hitl_export=True`. The draft records what the machine
   decided unaided. It is regenerated on every run, including runs that apply a
   ruling: what it holds is always the machine's own verdict, never the
   human's.
2. Edit `<sample>.decisions.json`. Every section is optional and an empty
   object rules on nothing.
3. Run again with `magazine_hitl_apply=True`. What was applied is recorded in
   `hitl_apply.report.json` in the run's working directory. A run that applied
   nothing writes no report.

Regenerate the HTML from an edited draft with:

    python tools/hitl_review.py <sample>

## review.json

```json
{
  "format_version": 1,
  "sample": "<sample>",
  "terms": [
    {"source": "...", "auto_target": "...", "vote_count": 2, "first_page": 4}
  ],
  "page_kinds": [
    {"page": 1, "machine_kind": "...", "conf": 0.71,
     "ambiguous": false, "source": "deterministic"}
  ],
  "drop_caps": [
    {"paragraph": "p4#8", "page": 4, "article_id": "...", "size_ratio": 6.668,
     "first_run": "L", "excerpt": "L ong before satellites orbited Earth,"}
  ]
}
```

Two term fields carry a meaning the name alone does not give:

- `vote_count` is how many extraction replies proposed the source. The
  extractor records no other frequency; this is **not** how often the term
  occurs in the document.
- `first_page` is not recorded by the extractor at all. It is found by exact,
  case-sensitive match of the source against the text of each page in file
  order, and is `null` where no page matched. Page numbers are one-based file
  page numbers, the same numbering `corpus/page_labels.json` uses.

`conf` and `ambiguous` come from the classifier: `ambiguous` is that stage's
own account of whether its top candidates could be separated, which the
intermediate language has no field for, and is `null` where the classifier's
report is not beside the run.

`drop_caps` holds the paragraphs the machine thinks open with an oversized
initial. It is filled only on a run with `magazine_drop_cap_mark` up, which also
requires `magazine_article_group`: a candidate is judged against the article it
belongs to, and a run raising the first switch without the second is refused
rather than quietly finding nothing. `size_ratio` is the size of the paragraph's
first style run over that paragraph's own median character size; `first_run` is
what that run says, which for a drop cap is the initial itself.

`paragraph` is how a paragraph is named in both files: `p<page>#<index>`, the
one-based file page and the paragraph's position on that page. It is not the
paragraph's debug id, which is minted afresh on every run and would name nothing
on the second pass.

## decisions.json

```json
{
  "terms": {"biopiracy": "生物剽窃"},
  "page_kinds": {"4": "feature_body"},
  "drop_caps": {"<paragraph ref>": "keep"}
}
```

- `terms` maps source to the target that must be used. A source the machine
  never extracted is allowed: that is the entry point for issue-level furniture
  such as a masthead, which no single article's extraction would surface.
- `page_kinds` maps a one-based page number, written as a decimal string, to a
  page type name declared in `configs/page_types.json`. A ruled page is
  recorded at confidence 1.0 with source `human`.
- `drop_caps` maps a paragraph reference to `keep` or `flatten`. The reference
  is the `paragraph` field of the draft, and a reference this document has no
  paragraph for refuses the whole file. A paragraph the machine did not flag may
  still be ruled on, as an unextracted term may be. The verdict is written into
  the intermediate language as `dropCapDecision` and **batch b9.4 gave it a
  reader**: behind `magazine_drop_cap_apply`, `flatten` merges the enlarged
  initial into the text it opens so the first word reaches the engine as a
  word, and `keep` leaves the paragraph as an unruled one is left. A candidate
  nobody ruled takes the verdict its target language declares in
  `configs/drop_cap.json`, so a run with no human in it still decides.
  `drop_cap_apply.report.json` in the run's working directory says what the
  reader did with each verdict.

Validation is all-or-nothing. An unknown section, a page number this document
does not have, a page type the vocabulary does not declare, a padded or empty
term, two sources that collide once case and whitespace are normalised, an
unknown drop cap verdict, or a paragraph reference this document cannot resolve:
any of these refuses the whole file with every fault listed. Nothing is applied
in part.

## What a ruling may not do

A ruling flows one way, into the run. It never writes back into
`corpus/registry.user.json`, `corpus/page_labels.json`, or any glossary the
machine keeps.
