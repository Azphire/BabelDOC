# B6.3 — brief names semantics fix and metric tuning, delivery report

Micro batch closing B6. Two things: the defect the `batch-b6.2` smoke found in
the brief's names field, and one round of tuning on the term consistency
measurement. Nothing upstream was touched.

## 1. The names field

### What changed, both ends

`names` was an array of source forms. It is now an array of
`{source, suggested_translation}` pairs, and the block that carries a brief into
a batch states the pairs as `name in the source -> how to render it` with the
scope of the instruction spelled out.

The per-round wording, digests and motives are in
[`template_iteration.log.md`](template_iteration.log.md). Four rounds ran, the
cap; round 3 ships because round 4 did not improve on it.

The module side follows the field: `NameRendering` is a frozen pair,
`interpret_reply` refuses an entry that is not an object carrying both fields as
strings, and an entry naming nothing or saying nothing about how it reads is
dropped rather than refused. Both halves are bounded by the existing
`max_name_chars`.

### A/B criteria, one by one

Courier, `context_on` against the frozen `context_off` arm. The `off` arm was
served 39 of 39 prompts from the cache and made no API call, so it is the same
translation `batch-b5.3` and `batch-b6.2` were measured against.

**(i) The two named regressions are gone.** Page 5, the exact strings the
`batch-b6.2` report probed:

| string | in source | off | b6.2 on | b6.3 on |
| --- | --- | --- | --- | --- |
| `Paumari` | 5 | 1 | **5** | **1** |
| `pirarucu` | 4 | 0 | **1** | **0** |
| `保马里` | 0 | 4 | – | 4 |
| `巨骨舌鱼` | 0 | 4 | – | 4 |

Source-form retention is back to the `off` arm's level and the target renderings
are back at the `off` arm's counts. Over all ten names the four briefs state, no
name's source form occurs more often in the `on` arm than in the `off` arm:
`regressions: 0` in [`ab.rfinal.md`](ab.rfinal.md).

The mechanism also does what it was rebuilt for: `Paumari`'s stated rendering
`保马里族` occurs 1 time in the `off` arm and 3 in the `on` arm, so the article
now uses one form where it previously alternated.

**(ii) The consistency gain is retained.** `土著` across the eight pages,
`off` = 26, `on` = 32. Per page: 5→8, 3→2, 0→1, 6→8, 1→1, 0→0, 9→10, 2→2. The
total gain survives; on page 2 the `on` arm is one below the `off` arm, which it
was not in `batch-b6.2` (3→4 there). The corpus term consistency table below is
the same finding measured the other way.

For scale: `batch-b6.2` had `off` 26, `on` 39. This batch's `on` arm is 32. The
b6.2 number was produced by a template that was also suppressing name
translation, so the two are not comparable as a like-for-like loss, and the gain
against the frozen baseline — the only comparison that is controlled — is
intact.

**(iii) New retention of the same kind: 3, not 0.** This criterion is not met in
full and is reported as such.

A sweep over every Latin word of four or more letters, per page, counting words
more frequent in the `on` arm than in the `off` arm:

| round | count | which |
| --- | --- | --- |
| 1 | 13 | `Adichie` `Al-Khalili` `Chimamanda` `Marek-Martinez` `Ngozi` `Carolina` `Cherelle` `Jackson` `Lagipoiva` `Zambrano` `chambira` `David` `Jefferson` |
| 2 | 7 | `Al-Khalili` `Marek-Martinez` `Cherelle` `Jackson` `Lagipoiva` `David` `Jefferson` |
| 3 (ships) | **3** | `Lagipoiva` `Cherelle` `Jackson` |
| 4 | 4 | `Lagipoiva` `Cherelle` `Jackson` `UNESCO` |

What remains is one byline paragraph on page 2, `Lagipoiva Cherelle Jackson`,
which the `off` arm renders `拉吉波伊瓦·切雷尔·杰克逊` and the `on` arm leaves in
Latin. It is a paragraph consisting of nothing but a personal name, which is the
shape round 3 explicitly addressed and did not fully fix.

Three notes on how much this is worth. First, it is a residue rather than the
defect: the batch opened on names the brief itself listed being suppressed, and
none of those is affected any more. Second, none of the three words is on any
brief's names list, so the mechanism at fault is the block's presence rather
than its content. Third, `gpt-4o` at temperature 0 is not deterministic in this
project's own measurements, and a movement of one byline between rounds is
inside that noise — which is exactly why round 4's 3→4 is reported as *no
improvement* and not as a regression.

## 2. Metric tuning

Only declared values moved, each inside its declared range, and the tool was not
changed.

**Objective:** the candidate column should not report a function word or a
punctuation n-gram as a term's rendering.

`candidate_min_chars` and `candidate_max_outside_share` were swept over the ten
runs (five samples, two modes). Score per setting: candidates carrying
punctuation or markup — the interpunct and hyphens excepted, since
`阿尔·朱哈尼` and `FCC-ee` are correct answers — plus candidates occurring in
more than a fifth of the sample's translated paragraphs. Full grid in
[`tuning.sweep.json`](tuning.sweep.json), the side-by-side candidate column in
[`tuning.compare.txt`](tuning.compare.txt).

| `candidate_min_chars` | `candidate_max_outside_share` | unusable of 38 | mean off | mean on |
| --- | --- | --- | --- | --- |
| 2 (was) | 0.25 (was) | 5 | 0.734 | 0.773 |
| 2 | 0.15 | 5 | 0.693 | 0.726 |
| 2 | 0.05 | 5 | 0.621 | 0.639 |
| **3 (now)** | **0.25 (kept)** | **4** | 0.703 | 0.742 |
| 3 | 0.15 | 4 | 0.687 | 0.701 |
| 3 | 0.05 | 5 | 0.569 | 0.605 |

**Changed:** `candidate_min_chars` 2 → 3. It removes the two-character
candidates, which is where the punctuation bigrams and the commonest word
fragments were: Courier A4's `，并` becomes `原住民知识`, Courier A1's `知识`
becomes `土著知识`, and CERNCourier's `Higgs` stops being measured by the string
`CERN`.

**Not changed:** `candidate_max_outside_share` stays at 0.25. Tightening it was
the obvious move and the sweep says it does not work: a correct rendering
appears in an article's other paragraphs too, so a low outside share throws the
rendering away and leaves the search to pick something worse — at 0.05,
CERNCourier's `CERN` is measured by `更新` and AramcoWorld's `Ottoman` by `他的`.
The setting was left where it is rather than moved for the sake of moving.

**The change costs something and it is stated:** raising the floor also drops
two-character renderings that were right. Courier A2's `土著` becomes `LINKS`,
and CERNCourier's `CERN's` becomes `理事会`. Three clear repairs against two
clear losses is the whole of the improvement, on 38 rows.

**What tuning cannot reach.** Four unusable candidates survive every setting in
the grid: `</style>` for AramcoWorld's `Islamic Ecumene` in both modes, and
`，它仍然` for its `Hijaz` in both modes. The first is style markup, which the
tool generates candidates from because it reads paragraph text as stored; the
second is punctuation-led. Both need the tool to strip markup and reject
candidates carrying punctuation before generating them, which is code and
outside this micro batch's scope. Filed below.

### Dual-mode table, five samples, after tuning

| sample | article | pages | terms (off) | mean (off) | terms (on) | mean (on) |
| --- | --- | --- | --- | --- | --- | --- |
| Courier-en | A1 | 1 | 1 | 0.60 | 1 | 1.00 |
| | A2 | 2, 3, 4 | 1 | 0.40 | 1 | 0.40 |
| | A3 | 5, 6 | 0 | – | 0 | – |
| | A4 | 7, 8 | 2 | 0.60 | 2 | 0.65 |
| | **all** | | **4** | **0.550** | **4** | **0.675** |
| Vogue-en | — | none | 0 | – | 0 | – |
| CERNCourier-en | A1 | 1 | 0 | – | 0 | – |
| | A2 | 3 | 4 | 1.00 | 4 | 1.00 |
| | A3 | 4 | 0 | – | 0 | – |
| | **all** | | **4** | **1.000** | **4** | **1.000** |
| FD-en | A3 | 8 | 2 | 0.38 | 2 | 0.38 |
| | **all** | | **2** | **0.375** | **2** | **0.375** |
| AramcoWorld-en | A1 | 4 | 0 | – | 0 | – |
| | A2 | 5, 6 | 4 | 0.85 | 4 | 0.92 |
| | A3 | 7 | 2 | 1.00 | 2 | 1.00 |
| | A4 | 8 | 3 | 0.89 | 3 | 0.89 |
| | **all** | | **9** | **0.885** | **9** | **0.917** |

19 qualifying terms across the corpus. Two samples move (Courier +0.125,
AramcoWorld +0.032), two are flat, one has nothing to measure. **No claim is
made.** Nineteen terms over five short excerpts, with a measure whose candidate
column is still wrong four times in thirty-eight, is not a result; it is a
number that is not contradicting the mechanism. A claim needs the three-run
design CLAUDE.md §2 names.

Vogue-en has no articles at all — the excerpt is two advertisements and a
contents page, all of which the grouping walk leaves unassigned — so it makes no
brief and has no term to measure. That is the correct outcome, not a gap.

## Cost

| sample | mode | API calls | prompt tok | completion tok |
| --- | --- | --- | --- | --- |
| Courier-en | on (rounds 1–4 + replay) | 38 + 34 + 35 + 34 + 0 | — | — |
| Courier-en | off | 0 (39/39 cache) | 0 | 0 |
| Vogue-en | on / off | 0 / 0 | 0 | 0 |
| CERNCourier-en | on / off | 30 / 0 | — | 0 |
| FD-en | on / off | 12 / 0 | — | 0 |
| AramcoWorld-en | on / off | 28 / 0 | 25 982 | 0 |

Every `context_off` arm was a complete cache replay, which is what makes the A/B
controlled: the two arms differ in the brief and in nothing else.

## Outstanding

1. **One byline paragraph still keeps its source form** (`Lagipoiva Cherelle
   Jackson`, Courier page 2). Criterion (iii) is met at 3 of 13, not at 0. The
   iteration cap was reached; a fifth round would be the place to try moving the
   names line to the end of the block or dropping the line entirely when a brief
   states no name, neither of which was tried.
2. **The block is rendered even when the names list is empty.** Courier A1 has
   no names and still receives the sentence about names, which is where five of
   round 1's thirteen retentions were. Suppressing the line for an empty list
   needs either a second template or a conditional, and templates are not
   conditional today.
3. **The measurement cannot see markup.** `</style>` is a candidate because the
   tool reads stored paragraph text. Stripping style tags and rejecting
   punctuation-carrying candidates before generation is a small change to
   `tools/term_consistency.py`, out of scope here, and would remove all four
   surviving unusable candidates.
4. **Two-character renderings are now invisible.** `土著` is a real rendering
   and the new floor excludes it. A length floor is a blunt instrument for
   "not a function word"; a frequency-based exclusion computed over the corpus
   rather than the article would be the better mechanism, and is also code.
5. **Courier A3 is still one article made of two.** Unchanged from
   `batch-b6.1`; the brief for it still describes only the Brazil piece. The fix
   remains the `folio_adjacency` signal.
