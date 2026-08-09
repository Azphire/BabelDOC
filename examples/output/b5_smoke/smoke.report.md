# B5.3 — real-API smoke and layout acceptance

Session three of batch B5 (`plans/PLAN_B5.md`, T5.3). Ten pipeline runs against a
real `gpt-4o` endpoint: every corpus sample, once with the magazine switches all
up and once with chain translation down. No code and no configuration changed in
this session; the gate still runs no real translation.

Artefacts: `examples/output/b5_smoke/`
— `<sample>.<mode>.pdf` finished PDFs, `<sample>.<mode>/work/` checkpoints and
sidecars, `analysis/` the derived JSON, `diff/` the render comparisons and
overlays, `scripts/` the drivers, `parallel/` the official Chinese reference.

---

## 0. What ran

### Engine parameters, verbatim from upstream

`OpenAITranslator.do_llm_translate`, `babeldoc/translator/translator.py:303-335`,
sends exactly this and nothing else:

| parameter | value | where it comes from |
| --- | --- | --- |
| `model` | `gpt-4o` | constructor argument, unchanged for all ten runs |
| `temperature` | `0` | `self.options`, sent because `send_temperature=True` (`translator.py:222`, `:273`) |
| `max_tokens` | `2048` | hardcoded (`translator.py:324`) |
| `messages` | one `user` message carrying the whole prompt | `translator.py:325-330` |
| `response_format` | **not sent** — `enable_json_mode_if_requested` is `False`, the CLI default (`main.py:428-431`) | `translator.py:310-313` |
| `extra_headers` | `{}` — no dashscope header | `translator.py:315-319` |
| `extra_body` | `{}` — no `reasoning`, no `thinking` | `translator.py:229-255` |
| retry | `openai.RateLimitError` only, 100 attempts, exponential 1–15s | `translator.py:297-302` |

All four wire parameters are ordinary Chat Completions fields that `gpt-4o`
accepts; there is no `max_completion_tokens`-only path and no reasoning-effort
field in play. Confirmed empirically: 216 requests reached the API across the
eleven runs, none rejected.

One parameter is worth carrying forward as a risk rather than a finding:
`max_tokens=2048` caps a **merged chain** exactly as it caps a page batch. The
one real chain merged here was 826 source characters and answered in well under
the cap, but a longer chain would be truncated mid-JSON, fail
`_clean_json_output`/`json.loads`, and escalate as `translation_unavailable`.
The escape hatch is correct; the ceiling is not chain-aware.

### Run configuration

`lang_in=en`, `lang_out=zh`, ONNX layout model, `qps=4` (the CLI default),
`watermark_output_mode=NoWatermark`, `no_dual=True`, `auto_extract_glossary=False`,
`debug=False`. Cache: the project-local `examples/cache/cache.v1.db` via
`use_project_cache`, eviction disabled.

- `chain_on` — `magazine_checkpoint`, `magazine_page_classify`,
  `magazine_chain_detect`, `magazine_chain_translate` all `True`.
- `chain_off` — the same but `magazine_chain_translate=False`. Chain detection
  stays on, so the two runs differ in exactly one thing: whether a detected
  chain is translated as one unit.

---

## 1. Smoke one — the chain focus (Courier-en)

Two chains detected, two merged, zero escalated
(`Courier-en.chain_on/work/Courier-en/chain_translation.report.json`).

### 1a. Per-member segment table with the real translations

**Chain `RRF4T` — title, pages 2→3, strategy `proportional`, no fallback**

Merged source: `How Indigenous knowledge drives scientific discover y`
Chain translation: `原住民知识如何推动科学发现`

| # | page | label | source | segment written back | cut | sentence range | last rendered char |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 2 | title | `How Indigenous knowledge drives` | `原住民知识如何推` | proportional | `-1 / -1` | `推` (line 1 of 1) |
| 1 | 3 | title | `scientific discover y` | `动科学发现` | — | `-1 / -1` | `现` (line 1 of 1) |

**Chain `ktff8` — body, pages 7→8, strategy `sentence_greedy`, no fallback, 5 sentences**

Merged source (826 chars, members joined by one space, no hyphen dropped):

> Not all commercial use of Indigenous knowledge linked to genetic resources constitutes biopiracy; some projects are mutually beneficial. For instance, the Indjalandji-Dhidhanu people in Australia have worked with researchers at the University of Queensland to build upon their Indigenous knowledge of spinifex, a hardy perennial tussock grass tradition- ally used for a variety of purposes. The collaborative research agreement includes provisions for benefit sharing. A spinoff company is now developing medical gels from cellulose nanofibers extracted from spinifex, and a composite material from the grass has been patented. Benefits that have already been shared under the agreement include employment opportunities for First Nations youth and funding for training and educational opportunities for Indigenous Australians.

Chain translation:

> 并非所有与遗传资源相关的土著知识的商业使用都构成生物盗窃；有些项目是互利的。例如，澳大利亚的Indjalandji-Dhidhanu族人与昆士兰大学的研究人员合作，基于他们对spinifex（一种传统上用于多种用途的耐旱多年生草丛）的土著知识进行研究。该合作研究协议包括利益分享的条款。目前，一家衍生公司正在开发从spinifex中提取的纤维素纳米纤维制成的医用凝胶，并已为这种草的复合材料申请了专利。根据协议，已经分享的利益包括为第一民族青年提供就业机会，以及为澳大利亚土著人提供培训和教育机会的资金。

| # | page | source ends on | segment written back | cut | sentence range |
| --- | --- | --- | --- | --- | --- |
| 0 | 7 | `…and a composite material from` (**mid-sentence**) | `并非所有…并已为这种草的复合材料申请了专利。` (4 sentences) | `sentence` | `0 / 4` |
| 1 | 8 | `…for Indigenous Australians.` | `根据协议，已经分享的利益包括为第一民族青年提供就业机会，以及为澳大利亚土著人提供培训和教育机会的资金。` | — | `4 / 5` |

Conservation held for both chains: the members' segments join back to exactly
the chain translation, byte for byte. The IL fields agree with the sidecar
(`segment_sentence_start/end` = `0/4` and `4/5` for the body chain, `-1/-1` for
both title members).

### 1b. Zero mid-sentence page break — geometric verification

Read from the **post-typesetting** checkpoint (`checkpoint.11_typesetting.xml`),
not from the string layer: characters grouped into rendered lines by their box
`y`, last line taken, last non-space character read off it.

| chain | member | rendered lines | last line's last character | sentence-final mark |
| --- | --- | --- | --- | --- |
| `ktff8` body | 0, page 7 | 12 | `。` at x=471.28, y=199.14 | **yes** |
| `ktff8` body | 1, page 8 | 4 | `。` at x=75.26, y=443.8 | **yes** |
| `RRF4T` title | 0, page 2 | 1 | `推` | no — by design |
| `RRF4T` title | 1, page 3 | 1 | `现` | no — by design |

The body result is the first real evidence for the claim. The English source of
member 0 ends `…and a composite material from`, with no terminator: the
publisher's own page break falls inside a sentence. After joint translation the
frame on page 7 closes on `专利。` and page 8 opens a new sentence. The claim is
about body chains only; a title chain carries no sentence structure, takes the
`proportional` strategy and records `-1/-1`, which is why its members end on an
ordinary character.

**The A/B that gives the number its meaning.** The same two paragraphs, from the
`chain_off` run (`analysis/ab.json`):

| page | translated alone (`chain_off`) | translated as a chain (`chain_on`) |
| --- | --- | --- |
| 7 | `…一家衍生公司现在正在开发从spinifex中提取的纤维素纳米纤维制成的医用凝胶，以及一种复合材料。` | `…目前，一家衍生公司正在开发从spinifex中提取的纤维素纳米纤维制成的医用凝胶，并已为这种草的复合材料申请了专利。` |
| 8 | `草地已经被申请了专利。根据协议，已经共享的利益包括…` | `根据协议，已经分享的利益包括…` |

Translating the truncated fragment on its own produced two defects that the
joint path does not have: an **invented sentence ending** for the dangling
clause `and a composite material from` (`…以及一种复合材料。`), and a
**mistranslation caused by the lost antecedent** — `the grass` (spinifex)
rendered as `草地`, lawn. Both are exactly the failure the batch exists to
remove, and both disappear.

### 1c. Passthrough check (observation, not a gate)

Neither chain was echoed back. `merged_source == translation` is `False` for
both; CJK share of the translation is `1.0` for the title chain and `0.802` for
the body chain, the Latin remainder being the proper nouns the source itself
carries (`Indjalandji-Dhidhanu`, `spinifex`). Nothing to escalate.

A related observation worth recording: the chain translation of the display
title, `原住民知识如何推动科学发现`, is character-for-character what the
contents page on PDF page 1 got for the same headline in **both** runs, whereas
the `chain_off` split rendered it `土著知识如何推动` + `科学发现`. Merging made
the spread agree with the contents page; it was not asked to.

### 1d. Side by side with the official Chinese edition

Source: UNESCO Courier Jan–Mar 2026, official Chinese edition, retrieved
2026-08-09, sha256 `fa789f8a…46a7d3ac`, full provenance and quotations in
`parallel/courier_official_zh.md`. **Not corpus** — nothing under `corpus/` was
touched; promoting this issue to a parallel sample is a `registry.user.json`
edit and belongs to the user.

Pagination: the Chinese edition runs two pages ahead. English pp. 12–13
(`Courier-en.pdf` pages 7–8) are Chinese pp. 10–11. Same article, same column
grid, same break position in the running text.

| | page 12 / 10 frame | page 13 / 11 frame |
| --- | --- | --- |
| **English source** | `Not all commercial use … and a composite material from` | `the grass has been patented. Benefits … Indigenous Australians.` |
| **Official Chinese** | `并非所有与遗传资源相关的土著知识商业化利用行为都构成生物剽窃；部分项目实现了互利共赢。以澳大利亚的印贾兰吉-迪达努（Indjalandji-Dhidhanu）部族为例，该部族与昆士兰大学的研究人员合作，根据其关于三齿稃（一种多年生丛生草本植物，传统用途广泛）的土著知识开展研究。双方签订的合作研究协议中包` | `含惠益分享条款。一家衍生企业目前正利用从三齿稃中提取的纤维素纳米纤维开发医用凝胶，同时，该草本植物制成的复合材料也已获得专利。根据该协议，已实现的惠益分享包括为第一民族青年提供就业机会，并为澳大利亚土著群体提供培训与教育相关的资金支持。` |
| **Ours (chain on)** | `并非所有与遗传资源相关的土著知识的商业使用都构成生物盗窃；有些项目是互利的。例如，澳大利亚的Indjalandji-Dhidhanu族人与昆士兰大学的研究人员合作，基于他们对spinifex（一种传统上用于多种用途的耐旱多年生草丛）的土著知识进行研究。该合作研究协议包括利益分享的条款。目前，一家衍生公司正在开发从spinifex中提取的纤维素纳米纤维制成的医用凝胶，并已为这种草的复合材料申请了专利。` | `根据协议，已经分享的利益包括为第一民族青年提供就业机会，以及为澳大利亚土著人提供培训和教育机会的资金。` |
| **Ours (chain off)** | `…一家衍生公司现在正在开发从spinifex中提取的纤维素纳米纤维制成的医用凝胶，以及一种复合材料。` | `草地已经被申请了专利。根据协议，已经共享的利益包括…` |

Reading, for human assessment:

1. **The official edition splits mid-word.** It breaks the page at
   `…协议中包` / `含惠益分享条款。` — inside 包含. A professional human
   translation filling the same two frames took a mid-word break because the
   frames are the size they are. Our machinery instead moves the boundary to the
   nearest sentence end and lets the length imbalance be absorbed by the
   existing scaling. Neither is wrong; they are different trade-offs, and ours
   is the one that keeps a frame semantically closed.
2. **Terminology.** The official edition uses 生物剽窃 and 惠益分享 (the treaty
   register) and translates the plant name 三齿稃; we produce 生物盗窃,
   利益分享, and leave `spinifex` in Latin. This is a glossary gap, not a chain
   gap — the same choices appear in the `chain_off` output.
3. **Register.** The official text is markedly more formal
   (以…为例, 根据其…开展研究) against our plainer 例如, 基于他们对…进行研究.
   Content is equivalent; no factual divergence found in this passage.
4. **The title chain has no like-for-like counterpart.** The English opener runs
   the dossier title across the spread; the Chinese edition runs the article
   title instead (`时代变迁背景下的` / `土著知识`). It is still evidence about
   splitting a display line across a spread — the official edition also splits
   it, at a phrase boundary — but not a translation comparison of the same
   words. Recorded with the caveat rather than tabulated as a match.

---

## 2. Smoke two — the regression face (all five samples)

### Table 1 — escalations

| sample | chains | merged | escalated | `placeholder_bearing` | `conservation_failure` | other |
| --- | --- | --- | --- | --- | --- | --- |
| Courier-en | 2 | 2 | 0 | 0 | 0 | 0 |
| Vogue-en | 0 | 0 | 0 | 0 | 0 | 0 |
| CERNCourier-en | 0 | 0 | 0 | 0 | 0 | 0 |
| FD-en | 0 | 0 | 0 | 0 | 0 | 0 |
| AramcoWorld-en | 0 | 0 | 0 | 0 | 0 | 0 |

Zero escalations of any kind, anywhere. `chains == merged + escalated` holds by
inspection of every sidecar. Read this as *the escape hatch was never needed on
this corpus*, not as *the escape hatch works*: `placeholder_bearing` and
`conservation_failure` remain exercised only by the gate's synthetic cases and
its fault-injecting stub (`spec_check_b5` assertions 06 and 13). The four
non-Courier samples detect no chain at all, so the whole chain path is inert in
them — which is itself the result the B4 detector's reluctance predicts.

### Table 2 — overflow and layout anomalies

Spill is measured from the post-typesetting geometry: a paragraph counts as
spilling when its last rendered line falls more than one line height below its
own box, or when any character lands outside the page crop box.

| sample | pages | spill pages (chain on) | spill pages (chain off) | worst below-line depth (on) | labels involved |
| --- | --- | --- | --- | --- | --- |
| Courier-en | 8 | none | none | 0.31 lines | — |
| Vogue-en | 3 | none | none | 0.61 lines | — |
| CERNCourier-en | 4 | 1, 3, 4 | 1, 3, 4 | 2.91 lines | `title`, `abandon` ×2 |
| FD-en | 8 | 2, 4 | 2, 4 | 0.29 lines | `fallback_line` ×2 (off-page only) |
| AramcoWorld-en | 8 | 1, 5 | 1, 5 | 0.28 lines | `fallback_line` ×3 (off-page only) |

**The spill sets are identical between the two modes, sample by sample and
paragraph by paragraph, down to the same measured numbers.** Chain translation
introduced no overflow anywhere. The flagged paragraphs are pre-existing and all
carry non-body labels: the CERN digital edition's navigation chrome and cover
masthead (`abandon`, `title`) and the rotated credit rails of FD and AramcoWorld
(`fallback_line`), whose character boxes legitimately sit outside the crop box.
No body paragraph spills in any run.

### Table 3 — render diff, chain-on against chain-off

`tools/render_diff.py` at the shipped 150 dpi, threshold 16, tolerance 0.

| sample | compared pages | differing pages | max diff ratio | overlays |
| --- | --- | --- | --- | --- |
| Courier-en | 8 | **2, 3, 7, 8** | 0.0289 | `diff/Courier-en/page_000{1,2,6,7}.diff.png` |
| Vogue-en | 3 | none | 0.0 | — |
| CERNCourier-en | 4 | none | 0.0 | — |
| FD-en | 8 | none | 0.0 | — |
| AramcoWorld-en | 8 | none | 0.0 | — |

Four of five samples render **pixel-identical** with the switch up and down. The
only sample that moves is the only sample that has chains, and it moves on
exactly the four pages its chain members sit on. Pages 1, 4, 5 and 6 of Courier
are pixel-identical.

The page-7 overlay was reviewed by eye. Three things show as red: the chain
member's rewritten tail (the expected change), the pull quote and running head,
and several neighbouring body paragraphs — see the outflow finding in §3.
Nothing shows as displaced, clipped, or overset; the changes are all in-place
character substitutions inside unmoved frames.

### Table 4 — timing, requests and cache

| sample | mode | seconds | requests | cache hits | API calls | prompt tokens | completion tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en | chain_on (cold) | 387.3 | 39 | 0 | 39 | 23 779 | 7 300 |
| Courier-en | chain_off | 303.3 | 45 | 31 | 14 | 6 071 | 1 492 |
| Courier-en | chain_on (repeat) | 341.1 | 39 | 39 | 0 | 0 | 0 |
| Vogue-en | chain_on | 174.9 | 8 | 0 | 8 | 4 730 | 1 262 |
| Vogue-en | chain_off | 163.0 | 8 | 8 | 0 | 0 | 0 |
| CERNCourier-en | chain_on | 382.4 | 65 | 0 | 65 | 36 634 | 10 448 |
| CERNCourier-en | chain_off | 363.2 | 65 | 65 | 0 | 0 | 0 |
| FD-en | chain_on | 298.4 | 38 | 0 | 38 | 21 383 | 5 516 |
| FD-en | chain_off | 294.9 | 38 | 38 | 0 | 0 | 0 |
| AramcoWorld-en | chain_on | 370.7 | 52 | 0 | 52 | 28 158 | 8 835 |
| AramcoWorld-en | chain_off | 412.5 | 52 | 52 | 0 | 0 | 0 |

Total: 449 translate calls across the eleven runs, of which 216 reached the API
and 233 were served from the project-local cache; 120 755 prompt tokens and
34 853 completion tokens.

Cache reading. On the four chainless samples the `chain_off` run hit cache
**100 %** — identical prompts, so the switch changed nothing that reaches the
engine. On Courier the `chain_off` run hit 31 of 45 and paid for 14: the six
requests the chain pass had absorbed came back as per-paragraph work, and the
pages that were rebatched produced prompts the cache had never seen. Courier
`chain_on` was run twice (the first run's directory was rebuilt by the sweep);
the repeat hit cache 39/39, which is a useful incidental result — the merged
chain request is cacheable like any other, so a re-run of the chain path is
free. Wall-clock is dominated by parsing and typesetting, not by the API: the
fully-cached runs are within 10 % of the cold ones.

---

## 3. Leftover issues

**1. Assertion 12a's stub premise does not survive a real engine — measured.**
The b5.2 gate asserts "a paragraph outside a chain is translated exactly as with
the switch down". Under the stub that is true by construction: the stub's answer
is a pure function of the item's own input, so recomposing a batch cannot change
it. Under `gpt-4o` it is false. Matching Courier's paragraphs by source text between
the two runs — 123 matched (`analysis/outflow.json`): **15 changed —
4 chain members and 11 neighbours**, on pages 2, 7 and 8, which are precisely
the pages whose batches were recomposed. Pages 1, 4, 5 and 6 are untouched.

Batch-level evidence for the mechanism (`analysis/batches.json`): page 2 went
from one batch of 6 items to one of 5, page 3 from 2 to 1 — the withheld
members. Pages 7 and 8 went from `[6,3]` to `[6,4]` and from `[3,6]` to
`[3,6,1]`, gaining an item each: the body members' cross-column partners, freed
when `ChainClaim.declines_cross_column` refused the pair, fell back into the
page batch. The sidecar agrees, recording `declined_by: ["cross_column",
"page_batch"]` for both body members and `["page_batch"]` for both title
members. Cross-column tracked groups went 14 → 12 while cross-page real pairs
stayed at 5. So the enforcement point behaves exactly as designed; what the stub
could not show is that the *downstream consequence* is visible in the output.

**2. …but the drift is not attributable to rebatching.** A control was run
(`analysis/determinism.json`): one prompt the `chain_off` run actually sent,
re-sent twice with the cache bypassed. `gpt-4o` at `temperature=0` returned
**three different answers** — similarity 0.989 and 0.995, differing by single
word choices (`盗`→`剽`, `现在`→`目前`). The 11 neighbour changes are of the
same character and magnitude: 土著→原住民, 生根→扎根, 车间→作坊, 广角视野→广角.
The runs cannot separate rebatching drift from engine repeat noise, because the
paragraphs whose prompts did **not** change were served from cache rather than
re-requested and are therefore identical by construction, not by measurement.
Settling this needs a three-run design (chain-off twice with `ignore_cache`,
then chain-on) and is not something to assert either way from these ten runs.

One neighbour change is larger than synonym noise and should be looked at:
the author byline `Daniel Robinson` on page 7 came back **untranslated** in the
`chain_on` run (`丹尼尔·罗宾逊` with the switch down). This is the
same-as-input fallback firing — the cold run logged
`Translation result is the same as input, fallback` — and given finding 2 it may
be noise rather than a chain effect. Worth a repeat before it is treated as a
regression.

**3. Gate wording.** `check_12_switch_on`'s docstring, "the chain mechanism
reaches its members and nothing else", is true of the stub and stronger than
what holds in production. The module docstring in `chain_translation.py` already
states the honest version ("What does change for it is the batching… That is
unavoidable, being the whole point"). Recommend the gate's prose be aligned in a
later batch; the assertion itself is still the right thing to check with a
deterministic engine and should not be weakened.

**4. Three real chains is the whole evidence base.** Two chains, one of each
pair class, in one sample. The other four samples detect none, so the corpus
gives one body chain to verify the sentence-boundary claim on. The claim holds
where it could be tested; it has not been stress-tested. Widening this needs
either a less reluctant detector (B4 follow-up) or more samples with genuine
cross-page running text.

**5. `max_tokens=2048` is not chain-aware** (§0). A merged chain long enough to
exceed it truncates, fails to parse, and escalates as `translation_unavailable`.
Correct behaviour, but it converts a long chain into a silent fallback rather
than a warning. Worth a bounded parameter and a sidecar note in a later batch.

**6. Coupling breadth.** `UPSTREAM_DIFF.md` now registers this session's three
authorised couplings (`_build_llm_prompt`, `_clean_json_output`,
`_build_font_maps`). `chain_translation.py` also calls
`il_translator.pre_translate_paragraph` and `post_translate_paragraph` on the
frozen per-paragraph translator. Those are read-only calls onto a public
surface, and registering them was outside this session's authorisation, so they
are flagged here rather than added.

**7. Glossary gap, not a chain gap.** The official-edition comparison (§1d)
shows consistent terminology divergence (生物盗窃 vs 生物剽窃, 利益分享 vs
惠益分享, untranslated `spinifex`). The same divergence appears with the switch
down, so it belongs to the glossary/term-extraction line of work, not to B5.
Recorded here because §1d is the first time the project has had an authoritative
target text to measure against.
