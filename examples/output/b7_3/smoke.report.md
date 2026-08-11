# B7.3 — two real passes with a human ruling in between

The batch-b7.1 and batch-b7.2 gates prove the review loop works against
synthetic documents and against the corpus with the switches down. This is the
other half: one real document, translated twice by `gpt-4o` with a person
writing the ruling between the passes, and every claim below measured against
what the two runs actually produced.

Sample `Courier-en` (8 pages, 132 paragraphs). Stack up in both passes:
`magazine_checkpoint`, `page_classify`, `chain_detect`, `chain_translate`,
`article_group`, `article_context`, `drop_cap_mark`, `hitl_export`, plus
`auto_extract_glossary`. The only difference between the passes is
`magazine_hitl_apply`.

Driver `scripts/run_smoke.py`, evidence `scripts/analyze_smoke.py` and
`evidence.json`. Artefacts: `Courier-en.pass1.pdf`, `Courier-en.pass2.pdf`,
the two working directories, and the review draft each pass wrote.

## The ruling

Written by the user into `reviews/Courier-en.decisions.json` between the passes
and not edited since. Four term pairs, one page kind, three drop cap verdicts:

```json
{
    "terms": {"Marcelo Silva de Sousa": "马塞洛·席尔瓦·德·索萨",
    "Lagipoiva Cherelle Jackson": "拉吉波伊瓦·谢雷尔·杰克逊",
"Daniel Robinson": "丹尼尔·罗宾逊", "David Jefferson": "大卫·杰斐逊"},
    "page_kinds": {"1": "toc"},
    "drop_caps": {"p4#3": "keep", "p5#5": "flatten", "p7#8": "flatten"}
}
```

It validates clean against the pass-one document: eight pages, `toc` declared in
`configs/page_types.json`, all three paragraph references resolvable, no
normalised source collision.

## Cost, and the cache freeze

| | seconds | requests | cache hits | API calls | prompt tokens | completion tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pass 1 | 381.2 | 51 | 3 | 48 | 44417 | 10469 |
| pass 2 | 77.5 | 53 | 42 | 11 | 9153 | 2009 |

Pass two replayed 42 of 53 requests from the frozen project cache. The eleven it
did not replay are the ones whose prompt text the ruling changed; §6 accounts
for every paragraph they produced.

The request count moved 51 → 53 for reasons that are not the ruling reaching
more text. Both passes translate the same 27 paragraph batches. Pass two asked
for one fewer article brief (three articles instead of four, §4), and its log
carries two `Translation result is too long or too short` retries that pass one
does not — the length guard firing on a resampled reply. Retries are not
deterministic, so this difference is noise and is reported rather than
explained.

## 1. Terms — the ruled pairs, every occurrence

Four ruled sources, eight occurrence sites. Every one was Latin in pass one and
carries the ruled target in pass two.

| source | site | label | pass 1 | pass 2 |
| --- | --- | --- | --- | --- |
| Marcelo Silva de Sousa | `p1#14` | plain text | `巴西：水上人家的教训 ..... 9Marcelo Silva de Sousa` | `…9马塞洛·席尔瓦·德·索萨` |
| Marcelo Silva de Sousa | `p5#8` | abandon | `Marcelo Silva de Sousa` | `马塞洛·席尔瓦·德·索萨` |
| Lagipoiva Cherelle Jackson | `p1#13` | plain text | `Lagipoiva Cherelle Jackson` | `拉吉波伊瓦·谢雷尔·杰克逊` |
| Lagipoiva Cherelle Jackson | `p2#6` | title | `Lagipoiva Cherelle Jackson` | `拉吉波伊瓦·谢雷尔·杰克逊` |
| Daniel Robinson | `p1#15` | plain text | `当生物盗窃扎根时.12Daniel Robinson 和 David Jefferson` | `当生物盗窃扎根时.12丹尼尔·罗宾逊和大卫·杰斐逊` |
| Daniel Robinson | `p7#13` | abandon | `Daniel Robinson` | `丹尼尔·罗宾逊` |
| David Jefferson | `p1#15` | plain text | (the same paragraph, both names) | (the same paragraph, both names) |
| David Jefferson | `p7#15` | title | `David Jefferson` | `大卫·杰斐逊` |

Seven paragraphs, all of them furniture: two contents-page lines, two byline
rails and two author-credit lines. The extractor had already found all four
names and had rendered each as its own source form — the automatic glossary's
target for each was the Latin string itself — so the machine's default was to
leave them and the ruling is the only thing that moved them.

**Controls.** `biopiracy` (7 occurrences) and `spinifex` (1) were **not** ruled
on. Their renderings are identical in both passes at every occurrence:
`生物盗窃` at all seven, `针茅` at the one. The single site where the paragraph
text changed at all is `p1#15`, which changed because of the two ruled names it
also carries; `生物盗窃` inside it is unchanged.

This is not the b5.3 closure the plan anticipated. With
`auto_extract_glossary=True` the extractor already rendered `biopiracy` and
`spinifex` consistently across the document in pass one, so there was no
divergence left for a ruling to close, and the user ruled on names instead. What
is demonstrated is the mechanism — a ruled source reaches every prompt that
mentions it and overrides the automatic table — not the specific b5.3 pair.

## 2. Masthead — not closed

Six paragraphs carry the publication name. Pass one renders it three ways:

| site | label | source | pass 1 = pass 2 |
| --- | --- | --- | --- |
| `p1#9` | title | `CourierT H E UNESCO` | `信使H E 联合国教科文组织` |
| `p2#0` | abandon | `\| The UNESCO Courier • January-March 2026` | `联合国教科文组织信使 2026年1月至3月` |
| `p4#0` | abandon | same | `联合国教科文组织信使 2026年1月至3月` |
| `p6#0` | abandon | same | `联合国教科文组织信使 2026年1月至3月` |
| `p6#15` | fallback_line | `r The UNESCO Courier éniako fo © Boris Sém` | `r The UNESCO Courier éniako fo © Boris Sém` (untranslated) |
| `p7#0` | abandon | same as `p2#0` | `联合国教科文组织信使 2026年1月至3月` |

The ruling names no masthead term, so pass two is byte-identical to pass one at
all six. **The b6.2 gap is not closed by this run.** What the run does show is
that the entry point exists and that the disagreement is real and stable:
the display masthead on the contents page, the four page-header instances and
the credit rail disagree in pass one and would still disagree in pass two.
Whether a `Courier` or `UNESCO Courier` entry in the terms section would settle
all six is untested — `p6#15` is a `fallback_line` that was not translated at
all, and no glossary entry reaches a paragraph no prompt was built for.

## 3. Byline — the b6.3 residue caught by the ruling

batch-b6.3 reported three Latin words surviving in one byline paragraph after
the names fix, and reported them as residue rather than as fixed. Two of the
three are `Lagipoiva Cherelle Jackson` at `p2#6`:

- pass 1: `Lagipoiva Cherelle Jackson` — the brief's `suggested_translation`
  channel did not move it.
- pass 2: `拉吉波伊瓦·谢雷尔·杰克逊` — the ruling did.

The same name at `p1#13` moves the same way. The residue the automatic path left
is exactly the kind of thing the human layer is for, and the human layer took it.

## 4. Page kind — an override that travels

Page 1: `editorial` at confidence 0.867 from the deterministic classifier →
`toc` at 1.0 with `pageKindSource="human"`. The other seven pages are untouched
and keep `deterministic`.

The provenance is in the intermediate language from the classifier checkpoint
onward — `checkpoint.07`, `checkpoint.09` and `checkpoint.11` each carry one
`pageKindSource="human"` and seven `deterministic` in pass two, and eight
`deterministic` in pass one.

The override changes policy, and the policy is what downstream reads:

| | `chain_eligible` | `opens_article` | `starts_article` | `repair_profile` |
| --- | --- | --- | --- | --- |
| `editorial` | true | true | true | flow |
| `toc` | **false** | **false** | true | **grid** |

And the grouping follows, with no code anywhere naming either kind:

| | pass 1 | pass 2 |
| --- | --- | --- |
| articles | 4: pages [1], [2,3,4], [5,6], [7,8] | 3: pages [2,3,4], [5,6], [7,8] |
| unassigned | none | page 1, reason `not_chain_eligible` |

The 35 paragraphs of page 1 stop being an article, so they stop carrying an
article brief — which is where eight of the eighteen changed paragraphs come
from (§6).

## 5. Drop caps — the verdict is written and nothing acts on it

Pass one marks three candidates and writes no verdict. Pass two marks the same
three and writes all three verdicts, at the references the ruling used:

| reference | was candidate | verdict |
| --- | --- | --- |
| `p4#3` | true | `keep` |
| `p5#5` | true | `flatten` |
| `p7#8` | true | `flatten` |

Counted in the intermediate language:

| checkpoint | pass 1 `dropCapCandidate` / `dropCapDecision` | pass 2 |
| --- | --- | --- |
| `07_page_classifier` | 0 / 0 | 0 / 0 |
| `09_il_translated` | 3 / 0 | 3 / **3** |
| `11_typesetting` | 3 / 0 | 3 / **3** |

Both PDFs have 8 pages. Nothing reads `dropCapDecision` yet, and nothing in the
two renders differs on account of it; that is the documented state, not a defect.

## 6. Perturbation — all 18 changed paragraphs, all accounted for

114 of 132 paragraphs are byte-identical between the passes. The 18 that are not
are classified from the prompt each was actually translated under, read out of
`translate_tracking.json`, rather than guessed at from the text.

| cause | count |
| --- | ---: |
| the paragraph's own source names a ruled term | 7 |
| a batch-mate's source does (the glossary block is per batch) | 3 |
| the page kind override changed the article brief block | 8 |
| prompt unchanged and translation changed | **0** |

**No unexplained perturbation.** Every changed paragraph has a changed prompt,
and every changed prompt has a changed section that traces to the ruling.

The three in the second row are the finding worth naming, because they are the
one thing a reader would call an accident:

| site | prompt section that changed | what moved |
| --- | --- | --- |
| `p2#4` figure_caption | `## Glossary Tables` | `…创作的作品，使用` → `…创作，使用` |
| `p2#7` plain text | `## Glossary Tables` | `在美国波特兰州立大学` → `在波特兰州立大学（美国）` |
| `p7#14` plain text | `## Glossary Tables` | `他的研究重点` → `其研究重点` |

None of the three contains a ruled name. Each shares a translation batch with a
paragraph that does, and the glossary block is built for the batch, so ruling on
one paragraph rewrites the prompt of every paragraph beside it, misses the
cache, and resamples them. The drift is stylistic and the meaning is unchanged
in all three, but the mechanism is general: **the blast radius of a term ruling
is the batch, not the paragraph.** Anyone reading a two-pass diff as "what the
ruling decided" will over-count by however many batch-mates the ruled paragraphs
have.

The eight in the third row are page-1 paragraphs whose
`## Contextual Hints for Better Translation` block changed because page 1 left
its article. Two of them (`p1#16`, `p1#18`) also have a changed glossary block,
because the re-partition changed which terms their batch contains. All eight
sit on the page the ruling was about.

## 7. The rebuild sidecar, verbatim

`pass2/work/Courier-en/hitl_apply.report.json`, `terms` section as written:

```json
"terms": {
  "auto_glossary_kept": 141,
  "auto_glossary_relocated": "auto_extracted_glossary",
  "dropped_from_auto": [
    {"auto_target": "Lagipoiva Cherelle Jackson", "source": "Lagipoiva Cherelle Jackson", "user_target": "拉吉波伊瓦·谢雷尔·杰克逊"},
    {"auto_target": "Marcelo Silva de Sousa", "source": "Marcelo Silva de Sousa", "user_target": "马塞洛·席尔瓦·德·索萨"},
    {"auto_target": "Daniel Robinson", "source": "Daniel Robinson", "user_target": "丹尼尔·罗宾逊"},
    {"auto_target": "David Jefferson", "source": "David Jefferson", "user_target": "大卫·杰斐逊"}
  ],
  "entries": [
    {"source": "Marcelo Silva de Sousa", "target": "马塞洛·席尔瓦·德·索萨"},
    {"source": "Lagipoiva Cherelle Jackson", "target": "拉吉波伊瓦·谢雷尔·杰克逊"},
    {"source": "Daniel Robinson", "target": "丹尼尔·罗宾逊"},
    {"source": "David Jefferson", "target": "大卫·杰斐逊"}
  ],
  "glossary": "hitl_decisions"
}
```

145 extracted entries, 4 dropped, 141 rebuilt and relocated into the user
glossary list, and the automatic slot emptied — which is what W-B7-01 says has
to happen for a ruling to reach a prompt at all while extraction is on. The four
dropped entries are visible in the prompt diff: the automatic table loses the
row and a `### Glossary: hitl_decisions` table gains it.

## 8. The draft is the machine's verdict on both passes

`pass1/Courier-en.review.json` and `pass2/Courier-en.review.json` differ in three
lines: the article ids, which are minted afresh on every run. The `page_kinds`
section of the pass-two draft still reads `editorial` / 0.867 /
`deterministic` for page 1, not `toc` / 1.0 / `human`. A rerun cannot adopt its
own previous draft as a ruling, and a human reading the second draft reads what
the machine would have decided unaided.

## What this run does not show

- **b5.3 closure.** The two terms that batch reported as diverging were already
  consistent under the automatic glossary in pass one, and were not ruled on.
- **b6.2 closure.** The masthead disagreement is reproduced, unchanged, in both
  passes. No masthead entry was ruled.
- **Anything about sampling variance.** One pass per configuration, `gpt-4o` at
  temperature 0, which batch-b6.3 measured as non-deterministic. The three
  batch-mate drifts in §6 are consistent with resampling and are reported as
  observations, not as a measured effect size.
- **Any typesetting consequence of a drop cap verdict.** Nothing reads it yet.

## Leftovers

1. **A term ruling perturbs its whole batch** (§6). If the intent is that a
   ruling touches only what it names, the glossary block would have to be built
   per paragraph rather than per batch — which would cost cache hits everywhere
   else. Worth a decision, not a silent fix.
2. **`p<page>#<index>` is one-based in the page and zero-based in the index.**
   `drop_cap.document_references` builds the index from `range(len(...))`, while
   `reviews/README.md` describes it as "the paragraph's position on that page".
   The two files agree with each other, so no ruling is misread; the prose is
   what is wrong. Left as found — it is batch-b7.2 surface and this batch
   changes no behaviour.
3. **`p6#15` is never translated** (§2). A `fallback_line` carrying the masthead
   and a photo credit gets no prompt, so no glossary and no ruling can reach it.
   Out of scope here; relevant to whichever batch takes issue-level furniture on.
