# B6 session two — article brief injection, delivery report

## What was built

One small request per article, made before that article's paragraphs are
translated, whose answer every batch of that article then carries.

The request is `prompts/article_brief.md`, asked from the article's heading and
the opening of its first body paragraph, and answered with a JSON object of
three fields: a rendered title, a sentence about the register, and the names
occurring in the source. The answer reaches the translating model through
`prompts/article_brief_context.md`, rendered into one more entry of the
contextual hints block the running title already uses. Nothing about either
request is composed in code, and both templates' SHA-256 land in the run's
`prompts.manifest.json`.

The pass also pays off a B5 leftover. With the switch up the running title is
read from the heading label set the configuration declares -- `title` and
`paragraph_title`, through `article_grouping.json` into `chain_detection.json`
-- instead of from the single label the stage had written into itself, and it is
cleared wherever an article opens, so a heading never carries into the next
piece. With the switch down that snapshot is exactly what it was.

## Prerequisite review, before any change

The plan asks the brief to reuse the existing title-context channel. What that
channel is, in the working tree at `batch-b6.1` -- every line number below is
that revision's, before any change this session made:

- `TitleContextSnapshot`, a frozen three-field record, at
  [translation_config.py:28](babeldoc/format/pdf/translation_config.py#L28); the
  two slots that hold one at
  [translation_config.py:36-37](babeldoc/format/pdf/translation_config.py#L36-L37)
  and the snapshotter at
  [translation_config.py:47](babeldoc/format/pdf/translation_config.py#L47).
- Seeded once per document in
  [il_translator_llm_only.py:183-195](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L183-L195),
  and advanced as the walk passes a heading at
  [il_translator_llm_only.py:620-625](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L620-L625).
- Read at each of the four submit points and passed **by value** into the
  executor task -- [472-473](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L472-L473),
  [551-552](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L551-L552),
  [645-646](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L645-L646),
  [663-664](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L663-L664)
  -- arriving as the `title_paragraph` / `local_title_paragraph` parameters of
  `translate_paragraph` at
  [677-678](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L677-L678).
- Rendered into the prompt by `_build_llm_prompt` at
  [931-981](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L931-L981),
  which turns whatever it was given into a numbered list under
  `## Contextual Hints for Better Translation` and substitutes it into
  `$contextual_hints_block` of the module's one prompt template
  ([line 91](babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L91)).
- The chain path reaches the same builder from
  [chain_translation.py:436-441](babeldoc/magazine/chain_translation.py#L436-L441),
  passing the same two slots.

So the channel is: a per-batch value, snapshotted on the walking thread at
submit time, carried as an argument into the worker, and rendered as one entry
of a numbered block. Its lifetime is the batch. That is exactly the shape "one
more block of text per batch" needs, and a brief is one more argument of the
same kind rather than a second mechanism beside it. Nothing about the channel
was incompatible, so the session proceeded.

## The cache, and why it is not the vision client

`configs/vlm.json`'s client owns its own transport, because a vision model is
not the model translating the document. A brief is a text request to the model
that *is* translating the document, so `CachedBriefClient` keeps the vision
client's three rules and swaps only that one part:

- **Transport**: `BaseTranslator.llm_translate` on the run's own engine, called
  with `ignore_cache=True`. The credential, the endpoint and the rate limiter
  are configured once for the run rather than twice, and there is no second
  place a key could be read from.
- **Cache**: `TranslationCache` under an engine name of its own, exactly as the
  vision client files vision replies, keyed by a digest of the key version, the
  engine identity, the prompt **file** SHA-256 and the rendered prompt SHA-256.
  The file digest is in the key on purpose: a reworded template must not be
  answered out of replies to the old wording.
- **Contract**: a reply is the object it was asked for or it is refused. A
  field of the wrong type is a refusal; a field longer than its declared bound
  is cut to it, a verbose brief still being usable guidance.

The engine's own cache is bypassed so that exactly one cache serves a brief and
the count of requests stays meaningful. A run that ignores the translation cache
ignores this one too, which is what lets the gate count calls at all.

## Smoke: Courier, both modes, real API

`gpt-4o`, project-local cache, `examples/output/b6_smoke/`.

| mode | seconds | engine calls | served from cache | API calls | prompt tok | completion tok |
| --- | --- | --- | --- | --- | --- | --- |
| `context_on` | 85.0 | 41 | 3 | 38 | 28 556 | 6 986 |
| `context_off` | 53.8 | 39 | 39 | 0 | 0 | 0 |

`context_on` is 4 brief requests plus 37 batch requests and no fallback.
`context_off` is 37 batch requests plus 2 per-paragraph fallbacks, every one of
them served from the frozen cache -- so the switch-down arm is a replay of what
`batch-b5.3` already paid for, which is the A/B protocol CLAUDE.md §2 asks for.
Three of `context_on`'s batch prompts were byte-identical to prompts already in
the cache. Courier's excerpt has exactly three page boundaries that fall between
two articles, and an endpoint pair straddling two articles carries no brief by
rule; the counts agree, which is consistent with that being the whole
explanation, and it was not verified further.

### Each article's brief, verbatim

Grouping is `batch-b6.1`'s: four articles, no page outside one.

| article | pages | heading it was asked from |
| --- | --- | --- |
| A1 | 1 | `Contents` |
| A2 | 2, 3, 4 | `How Indigenous knowledge drives` |
| A3 | 5, 6 | `Brazil: lessons from the water people` |
| A4 | 7, 8 | `The struggle for benefit-sharing` |

A1 — title `内容`; register
`文章采用正式的语气，属于论述性文章，探讨了土著知识的重要性及其在现代社会中的重新关注。`;
names: none.

A2 — title `土著知识的驱动力`; register
`文章采用正式的报道风格，旨在介绍和分析土著知识在气候变化和生物多样性下降背景下的重要性。`;
names `Aboriginal; Inuit; zaï`.

A3 — title `巴西：水上人家的启示`; register
`文章采用叙述性风格，语气较为正式，不直接与读者对话。`; names `pirarucus; Paumari`.

A4 — title `利益分享的斗争`; register
`文章采用正式的报道风格，描述了有关阿甘油利益分享的现状，未直接与读者对话。`;
names `Moroccan; Argania spinosa L.; Amazigh; Berber`.

Four articles, four requests, four briefs, nothing refused.

### Term consistency, both modes

`tools/term_consistency.py`, thresholds from `configs/term_consistency.json`
(≥ 3 occurrences inside one article, ≥ 4 characters, at least one occurrence
away from a sentence opening).

| article | pages | terms (off) | mean (off) | terms (on) | mean (on) |
| --- | --- | --- | --- | --- | --- |
| A1 | 1 | 1 | 1.00 | 1 | 1.00 |
| A2 | 2, 3, 4 | 1 | 0.40 | 1 | 0.60 |
| A3 | 5, 6 | 0 | – | 0 | – |
| A4 | 7, 8 | 2 | 0.65 | 2 | 0.80 |
| **all** | | **4** | **0.675** | **4** | **0.800** |

Per term, with the substring the measure settled on:

| article | term | occurrences | off | candidate | on | candidate |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | Indigenous | 5 | 1.00 | `知识` | 1.00 | `土著知识` |
| A2 | Indigenous | 5 | 0.40 | `LINKS` | 0.60 | `土著和` |
| A4 | Amazigh | 3 | 1.00 | `阿甘油` | 1.00 | `阿甘油` |
| A4 | Indigenous | 11 | 0.30 | `研究`… | 0.60 | `研究` |

**This table does not support a claim.** Four terms is not a sample, and the
candidate column shows the measure latching onto strings that are plainly not
the term's rendering -- `LINKS` for *Indigenous*, and in the `off` arm of A4 a
punctuation bigram. The number moves the right way and that is all that can be
said; a claim would need the three-run design CLAUDE.md §2 names, over more
than one sample.

The glossary column is empty throughout: this run configures no glossary, so
the coverage question is unanswered rather than answered negatively.

### Diff against the b5.3 translation

Compared by (page, position), 132 paragraphs:

- `batch-b5.3` `chain_on` vs this session's `context_off`: **0 differing**. The
  switch-down arm reproduces the previous batch's translation exactly, which is
  what the all-cache-hit count above already implied.
- `context_off` vs `context_on`: **63 of 132 differ**, on all eight pages
  (10, 3, 1, 16, 7, 6, 11, 9).

Most differences are ordinary rewording of the kind `gpt-4o` produces between
any two prompts. Three are worth naming.

**The names list is being read as an instruction.** On page 5 the A3 brief lists
`pirarucus; Paumari`, and with the brief on those names stay in **source form**
where they had been rendered in the target script: `Paumari` appears 5 times in
the target with the brief on against 1 with it off, and `pirarucu` 1 against 0.
`保马里人` became `Paumari人`, `巨骨舌鱼` became `pirarucu鱼`. The template says
those names are given "in source form" as guidance; the model took that as a
direction to leave them untranslated. This is a defect of wording, it makes the
target text worse, and it is the first thing to fix in the template.

**The intended effect is visible too.** `土著` (Indigenous) rises on every page
of A2 with the brief on (5→8, 3→4, 0→1, 6→13 by page), which is the term being
used where the off arm reached for a synonym or dropped it.

**An article-level brief cannot fix issue-level furniture.** The running head
`The UNESCO Courier` is rendered `通讯` on page 6 and `信使` on page 7 with the
brief on, and the other way round with it off. The two pages belong to two
articles and therefore to two briefs, so nothing in this mechanism makes a
string shared by the whole issue consistent. That is a limit of the design, not
a defect of this run.

## Known limitation — the cost of Courier's A3 mis-merge

`batch-b6.1` recorded that Courier's A3 merges issue p9 (the Brazil/Paumari
feature) with issue p38 (a quantum-sensing piece in the IDEAS section), because
the excerpt is not contiguous and no page- or paragraph-level signal available
today separates them. This session is the first time that mis-merge had a
consequence to measure: the two pages share one brief, and that brief is built
from the opening page alone, so page 6 was translated carrying a description of
an article it is not part of -- title `巴西：水上人家的启示`, register
"narrative", names `pirarucus; Paumari`.

What actually happened on page 6:

- **No contamination.** `Paumari`, `pirarucu`, `巴西` and `土著` each occur zero
  times in page 6's target text, in both modes. The wrong brief did not put
  Brazil vocabulary into a quantum article.
- **No benefit either.** Six of page 6's paragraphs differ between the modes,
  and they are ordinary rewordings -- `无法接近组织，但在相机中可以产生` against
  `无法接近组织，但可以在相机中产生`. Nothing in the differences reads as the
  brief steering the text, which is expected: a narrative register and a list of
  river-people names have nothing to say about quantum sensors.
- **One second-order effect.** Page 6 is where the masthead flip above shows up,
  and page 6 got A3's brief while page 7 got A4's; had the grouping been right,
  page 6 would have opened an article of its own and had a brief describing
  quantum sensing.

So the measured cost of this mis-merge is *a wasted brief, not a damaged
translation*. A model given a description that does not match the text in front
of it ignored the description. That is a milder outcome than the mis-merge
deserved and it should not be read as licence: the failure mode a brief could
cause -- a register or a name list from the wrong piece bleeding into the text --
did not occur here on six paragraphs of one sample, which is evidence about this
case and not about the mechanism. The fix stays where `batch-b6.1` put it, in
the `folio_adjacency` signal left over from B4.

## What is not here

- No rolling context. The brief is fixed for the article; nothing summarises
  what earlier batches decided. PLAN_B6 defers that until the consistency
  measurement can show a brief is not enough, and the measurement above is not
  yet able to show anything.
- No brief on the per-paragraph fallback path. A batch that fails and falls back
  re-enters `il_translator.py`, which this project may not change, so a
  fallen-back paragraph is translated without the brief. `context_on` had no
  fallbacks on this sample; the case is untested in the wild.
- Nothing written anywhere. The brief is consumed by the request that carries it:
  not into the intermediate language, which is frozen, and above all not into the
  glossary.
