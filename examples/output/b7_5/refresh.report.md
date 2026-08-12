# B7.5 corpus refresh — delivery report

Sessions: `batch-b7.5.1` (registration and rebuild), `batch-b7.5.2` (migration
verification and the masthead ruling). Every number here is reproducible from
the scripts under `examples/output/b7_5/scripts/` and the gate
`spec_checks/spec_check_b7_5.py`.

## 1. Corpus ledger

Six samples, five publications, 41 pages, 35 adjudicated boundaries.

| sample | role | pages | boundaries | link | no link | page types covered |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Courier-en.pdf | binding + translation_eval | 8 | 7 | 2 | 5 | toc, editorial, article_opener, photo_spread, section_divider, article_body |
| Vogue-en.pdf | binding | 3 | 2 | 0 | 2 | advertisement, toc |
| CERNCourier-en.pdf | binding | 4 | 3 | 0 | 3 | editorial, front_cover, advertisement, toc, article_opener, article_body |
| AramcoWorld-en-v2.pdf | binding | 9 | 8 | 1 | 7 | front_cover, masthead, toc, article_body, article_opener |
| FD-en-v2.pdf | binding | 9 | 8 | 0 | 8 | + infographic, sidebar_heavy |
| Courier-zh.pdf | observed (translation_eval) | 8 | 7 | 2 | 5 | toc, editorial, article_opener, photo_spread, article_body |

`binding` is the constrained role `layout_generalization`, on which the
agreement rates are gate assertions. The observed sample is measured the same
way and gates nothing: the thresholds were never tuned against its
distribution, so its numbers are the baseline a later calibration is judged
from rather than a verdict on the current one.

- constrained domain: 5 samples, 33 pages, 28 boundaries (3 link, 25 no link)
- observed: 1 sample, 8 pages, 7 boundaries (2 link, 5 no link)
- page type coverage: 11 of the 15 declared types. Not covered: `back_cover`,
  `contributors`, `interview`, `letters_page`.

## 2. Agreement, against the corpus this replaced

| | v1 (batch-b7.3) | v2 (this batch) | minimum |
| --- | --- | --- | --- |
| page kind agreement (06c) | 0.903 (28/31) | **0.879 (29/33)** | 0.70 |
| boundary agreement | 1.000 (26/26) | **1.000 (28/28)** | 0.80 |
| false links on adjudicated negatives | 0 | **0** | 0 |

No retune was started and none was needed. `configs/page_types.json` and
`configs/chain_detection.json` are byte for byte what batch-b7.5.1 inherited,
which `check_05d_no_retune_happened` asserts.

## 3. Migration drift

Every page the two replaced samples share with their successors was checked
against the v1 ground truth and against the miss list the batch-b7.3 sweep
froze. **No page changed verdict.** The `drift` column of the full table
(`scripts/` reproduces it) is `none` on all 25 shared pages and `new` on the
three pages the refresh added.

| sample | v2 page | v1 page | truth | verdict | drift |
| --- | ---: | ---: | --- | --- | --- |
| AramcoWorld-en-v2 | 1–6 | 1–6 | unchanged | correct | none |
| AramcoWorld-en-v2 | **7** | new | article_body | article_body | new, correct |
| AramcoWorld-en-v2 | **8** | 7 | article_body | article_opener | none — wrong under v1 as well |
| AramcoWorld-en-v2 | **9** | 8 | article_body | article_opener | none — wrong under v1 as well |
| FD-en-v2 | 1–6, 8, 9 | 1–6, 7, 8 | unchanged | correct | none |
| FD-en-v2 | **7** | new | infographic / sidebar_heavy | masthead | new, wrong |
| CERNCourier-en | 4 | 4 | article_body | interview | none — wrong under v1 as well |

The rate arithmetic closes on the two new pages alone: 28/31 plus one hit and
two labelled pages is 29/33.

### Why the three misses miss

The refresh was expected to move `page_relative_position` and the percentile
columns, and the plan authorised a retune for that. The feature level
attribution says it did not happen: **no miss is decided by a position or
percentile feature.**

- **AramcoWorld-en-v2 p8 and p9** (Reviews, issue pp. 40–41).
  `article_opener` 0.875 against `article_body` 0.833, ambiguous. One feature
  decides it in both directions at once: `max_font_size_ratio = 4.286` satisfies
  the opener's `ge 2.5` (weight 2.5) and fails the body's `le 2.5` (weight 1.5
  of 9). A book review page carries an oversized display headline, and the
  ruleset reads that as an opener. The same two pages were wrong under v1 with
  the same verdict.
- **FD-en-v2 p7** (Kaleidoscope, new). `masthead` 1.000 against `infographic`
  0.722, ambiguous, with `contributors` also at 1.000. The page is 33 paragraphs
  of quote rail and photo brief: `short_paragraph_ratio 0.879`,
  `mean_paragraph_chars 37.7`, `text_coverage_ratio 0.197` — the colophon
  signature. The one infographic rule that fails is
  `numeric_token_density ge 0.08`, measured at **0.0503**: the bar chart panel's
  numerals do not reach the density the type expects.

## 4. Chain detection

Zero false links across the whole corpus, observed sample included — the hard
line `check_02d_no_false_link_anywhere` holds over all 30 adjudicated negatives.
Both new traps are correctly refused: AramcoWorld-en-v2 `7->8` (tail dangles
mid sentence but the next page is not its continuation) and FD-en-v2 `6->7`
(adjacent, same department, clean sentence boundary).

The three positives in the constrained domain are all found:

| sample | boundary | kind | score | signal vector |
| --- | --- | --- | ---: | --- |
| Courier-en | 2->3 | display title split | 0.950 | style_continuity 1.0, tail_line_fill 1.0, tail_no_terminal_punct 1.0, column_position 0.5, body_label_pair 0, opener_prior 0 |
| Courier-en | 7->8 | mid sentence body split | 0.950 | body_label_pair 1.0, style_continuity 1.0, tail_line_fill 1.0, tail_no_terminal_punct 1.0, column_position 0.5 |
| AramcoWorld-en-v2 | **6->7** | mid sentence body split (new) | **1.000** | all six at full strength; a second pairing `title->title` scored 0.900 beside it |

### The two observed-domain positives, and why they are missed

Courier-zh `2->3` and `7->8` are both missed, and **no signal fell short**:
the boundaries were never scored at all.

| boundary | eligible | reason | signals |
| --- | --- | --- | --- |
| 2->3 | false | `not_chain_eligible:head` | all null |
| 7->8 | false | `not_chain_eligible:tail,head` | all null |

The cause is three steps upstream of the chain detector. Chinese page kinds are
misread, the misread kinds are ones whose policy sets `chain_eligible` false,
and an ineligible endpoint masks the boundary before it is scored. zh p3 is
classified `advertisement`; zh p7 and p8 are classified `sidebar_heavy`; none of
the three is chain eligible.

The page kind error is itself attributable to one threshold. On zh p8,
`sidebar_heavy` scores 1.000 against `article_body` 0.389, and the only
`article_body` rule that fails is `mean_paragraph_chars ge 110`, measured at
**98.6**. The same threshold family works twice against the right answer: at 98.6
the `sidebar_heavy` penalty `mean_paragraph_chars ge 140` also fails to trip, so
the wrong type keeps its full weight. A character count is a language dependent
quantity — the same content carries far fewer characters in Chinese than in
English — so a threshold tuned on English sits too high for Chinese. Correcting
it is zh calibration work and is out of scope here; it is recorded as the first
target when that work starts.

## 5. The masthead ruling

The b6.2 gap was that this document rendered its own masthead two different ways
and nothing could settle it. The corpus owner ruled
`The UNESCO Courier -> 联合国教科文组织《信使》` and, for the display masthead,
`CourierT H E UNESCO -> 联合国教科文组织《信使》`. Two passes were run with the
project cache frozen, pass one with no ruling applied and pass two with it.

| pass | requests | cache hits | live API calls | tokens in / out |
| --- | ---: | ---: | ---: | --- |
| pass1 | 51 | 51 | **0** | 0 / 0 |
| pass2 | 53 | 49 | **4** | 5137 / 1180 |

Pass one spent nothing: with no ruling applied it is the same set of requests
batch-b7.3 already made, replayed. Pass two changed four prompts, which bounds
what could have moved: 27 of 132 paragraphs differ, and every one of them sits
in one of those four batches. Four control paragraphs carrying `biopiracy` in
batches the ruling did not touch are byte identical across the passes.

### Six sites, three outcomes

| # | paragraph | page | layout label | outcome | pass 1 | pass 2 |
| ---: | --- | ---: | --- | --- | --- | --- |
| 1 | `p1#9` | 1 | `title` | **offered but unmatched** | 信使H E 联合国教科文组织 | 信使H E 联合国教科文组织 |
| 2 | `p2#0` | 2 | `abandon` | ruling matched | 联合国教科文组织信使 2026年1月至3月 | 联合国教科文组织《信使》2026年1月至3月 |
| 3 | `p4#0` | 4 | `abandon` | ruling matched | 联合国教科文组织信使 2026年1月至3月 | 联合国教科文组织《信使》 2026年1月至3月 |
| 4 | `p6#0` | 6 | `abandon` | ruling matched | 联合国教科文组织信使 2026年1月至3月 | 联合国教科文组织《信使》 2026年1月至3月 |
| 5 | `p7#0` | 7 | `abandon` | ruling matched | 联合国教科文组织信使 2026年1月至3月 | 联合国教科文组织《信使》2026年1月至3月 |
| 6 | `p6#15` | 6 | `fallback_line` | **not offered** | untranslated | untranslated |

Four of six now carry the ruled name and the cross article flip between them is
gone. The plan expected five, and the fifth did not land; both shortfalls are
recorded below rather than argued away.

### The two sites the ruling could not reach are not the same defect

**`p6#15`, never offered.** The layout parser recovered this line outside any
block and gave it `fallback_line`. Such a paragraph is not handed to the
translator at all — its rendering is its source, unchanged, in both passes. No
ruling can reach a paragraph that has no prompt. This is the standing
requirement batch-b7 recorded and it is now a measured fact rather than an
expectation.

**`p1#9`, offered but unmatched — new, and the sharper of the two.** The review
draft shows a human the paragraph's joined rendering, `CourierT H E UNESCO`, and
the owner ruled on exactly that string. The text the batch is actually built
from carries the rich text markup the paragraph's style runs imply, and for this
paragraph that is:

```
offered to the translator: <b1>Courier</b1><b3>H E UNESCO
ruled by the human:        CourierT H E UNESCO
```

The ruled source does not occur in the offered text, so the glossary never
matched and no prompt ever carried the ruling. `probe_prompt_inputs.py` captures
this from the built prompts: of 123 prompts, none contains the joined string,
and the ruled source `CourierT H E UNESCO` matches nothing offered while
`The UNESCO Courier` matches the four folio sites' input
`<b1>The UNESCO Courier <b2><b3>January-March 2026</b3>`.

This is a silent disagreement between what a human is shown and what the machine
matches on. A ruling written from the draft can therefore fail with no
diagnostic at all — the reviewer sees a term they ruled on rendering the old way
and has nothing to tell them why. It belongs at the top of the B8 requirement
list, above the fallback line item: the fallback line case is a coverage gap, and
this one is a correctness trap in the review interface itself.

## 6. Gate

`spec_checks/spec_check_b7_5.py`, 23 assertions, all green, and the full sweep
`spec_checks/run_all.py` green over 18 gates. No assertion in the gate spends a
credential: the two passes are frozen under `examples/output/b7_5/`.

One earlier gate needed the corpus refresh reflected in it.
`spec_check_b7_3.check_02c_ruling_matches_the_file` compared its frozen evidence
against the ruling in the working tree, which this session's masthead entries
grew; it now compares against the copy of the ruling frozen beside the run that
read it, since a ruling is a living document and the evidence has to agree with
the ruling as it stood when the passes were made.

The maintenance this session carried, authorised as T7.5.2.0:

- `spec_checks/artifacts.py` refuses to publish a cache slot for a run that
  produced no PDF or no checkpoint, and raises `BuildIncomplete` instead. The
  failure it closes was silent: `translate` swallows some failures and returns a
  result with no PDF, the cache published that as finished, and every gate served
  from the slot measured an empty working directory as zero agreement.
  `check_04c_incomplete_build_is_not_published` reproduces the failure and
  asserts the refusal, the absent slot and the staging directory left to look at.
- `CLAUDE.md` §4.1 now reads "注释一律英文(语料真值文件除外)": the corpus
  ground truth adjudicates documents, and a Chinese edition is adjudicated by
  quoting the Chinese it splits.
- `check_04b_two_pass_identity` re-runs the property the human loop rests on —
  a pass under an empty ruling is the pass that would have happened with the
  switch down — over all six samples of the refreshed corpus, with a stub
  translator.
