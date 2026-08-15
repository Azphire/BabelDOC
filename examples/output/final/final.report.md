# F1 — full-stack reviewed translation run

Six samples, one run each, every magazine switch up and the ruling under
`reviews/` applied where there is one. This is not an evaluation: nothing is
ablated and nothing is compared against a baseline. The artefact is the
finished PDF, and this file is what to look at while reading it.

Generated 2026-08-15T16:29:57+0100. Configuration and per-sample digests in
`final.manifest.json` beside this file.


## 0. Configuration

| switch | value |
| --- | --- |
| magazine_checkpoint | True |
| magazine_page_classify | True |
| magazine_chain_detect | True |
| magazine_chain_translate | True |
| magazine_article_group | True |
| magazine_article_context | True |
| magazine_drop_cap_mark | True |
| magazine_detect | True |
| magazine_repair | True |
| magazine_hitl_apply | True |
| magazine_hitl_export | False |

`magazine_hitl_export` is the one switch down. Export writes its draft into
`reviews/`, which is the user's directory, and no prompt depends on it.


| option | value |
| --- | --- |
| model | gpt-4o |
| lang_in | en |
| lang_out | zh |
| qps | 4 |
| auto_extract_glossary | True |
| no_dual | True |
| watermark_output_mode | NoWatermark |
| debug | False |
| doc_layout_model | onnx |
| cache_db | examples/cache/cache.v1.db |
| cache_eviction | disabled |
| reviews_dir | reviews |

### What is on disk

`examples/output/final/<sample>/` holds the finished `<sample>.final.pdf`, the
run's `out/` and `work/` directories, and `run.json`. The working directory is
the whole sidecar set: every stage checkpoint as XML and JSON, the classifier,
chain, article-map, article-context, drop-cap, HITL-apply, detection and repair
reports, the glossary files and the prompt manifest. `scripts/` holds the driver
and this report's builder, `cache_probe/` the evidence for §5, `run.log` the
drivers' console output (its first lines were lost to the capture; the per-run
records in `runs.json` are complete).


## 1. Cost and cache

| sample | seconds | requests | cache hits | API calls | hit rate | repair-layer misses | prompt tok | completion tok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | 98.9 | 77 | 73 | 4 | 94.8% | 1 | 6347 | 909 |
| CERNCourier-en | 63.9 | 86 | 83 | 3 | 96.5% | 3 | 10387 | 158 |
| Courier-en | 64.8 | 54 | 53 | 1 | 98.1% | 1 | 1733 | 93 |
| Courier-zh | 105.2 | 83 | 82 | 1 | 98.8% | 1 | 1703 | 62 |
| FD-en-v2 | 62.7 | 66 | 64 | 2 | 97.0% | 2 | 7195 | 235 |
| Vogue-en | 39.5 | 13 | 12 | 1 | 92.3% | 1 | 1272 | 30 |
| **total** | 435.0 | 379 | 367 | 12 | 96.8% | 9 | 28637 | 1487 |

`requests` counts everything that reached the engine object. The repair layer
reaches it with the engine's own cache bypassed -- a repair decision and an
orphan translation are served by the decision cache and the orphan cache
instead -- so a repair request that misses those two shows here as an API
call rather than as a cache hit. The last column is that number, counted
independently from `react_repair.report.json`.


They agree on `CERNCourier-en`, `Courier-en`, `Courier-zh`, `FD-en-v2`, `Vogue-en`: every translator request there was served from the project cache and
every API call came from the repair layer. The remainder is translator
work whose prompt the cache had not seen — `AramcoWorld-en-v2` 3 — and it is now cached; see §5.


## 2. What each mechanism did

| sample | pages | chains det/merged | articles/briefs | drop caps cand/ruled | ruling terms/pages | issues | repair iters/apps |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | 9 | 1/1 | 4/4 (4 cached) | 0/0 | — | 19 | 1/0 |
| CERNCourier-en | 4 | 0/0 | 3/3 (3 cached) | 0/0 | — | 31 | 2/1 |
| Courier-en | 8 | 2/2 | 3/3 (3 cached) | 3/3 | 6/1 | 7 | 1/0 |
| Courier-zh | 8 | 0/0 | 2/2 (2 cached) | 0/0 | — | 7 | 1/0 |
| FD-en-v2 | 9 | 0/0 | 3/3 (3 cached) | 0/0 | — | 23 | 2/2 |
| Vogue-en | 3 | 0/0 | 0/0 (0 cached) | 0/0 | — | 3 | 1/0 |

### Per sample

**AramcoWorld-en-v2** — `examples/output/final/AramcoWorld-en-v2/AramcoWorld-en-v2.final.pdf`

9 pages classified deterministic (article_body ×3, article_opener ×3, front_cover ×1, masthead ×1, toc ×1), 5 ambiguous. 8 page boundaries examined, 1 linked into 1 chain(s); 1 translated jointly over 2 member(s), 0 escalated. 4 article(s) grouped (3 page(s) unassigned), 4 brief(s) built of 4 requested, 4 from cache, 0 failed. 0 drop-cap candidate(s) marked, 0 ruled on (0 flattened). No ruling file; every decision point ran on the machine default. Detection found 19 issue(s) (untranslated_residue ×19); the repair loop ran 1 iteration(s), chose translate_orphan_lines (0/1 decisions from cache), applied 0, treated 0, stopped on `no_paragraph_was_written`, conservation conserved (146 → 146 paragraphs).

**CERNCourier-en** — `examples/output/final/CERNCourier-en/CERNCourier-en.final.pdf`

4 pages classified deterministic (article_opener ×1, editorial ×1, interview ×1, toc ×1), 4 ambiguous. 3 page boundaries examined, 0 linked into 0 chain(s); 0 translated jointly over 0 member(s), 0 escalated. 3 article(s) grouped (1 page(s) unassigned), 3 brief(s) built of 3 requested, 3 from cache, 0 failed. 0 drop-cap candidate(s) marked, 0 ruled on (0 flattened). No ruling file; every decision point ran on the machine default. Detection found 31 issue(s) (fragment_cluster ×4, untranslated_residue ×27); the repair loop ran 2 iteration(s), chose translate_orphan_lines, translate_orphan_lines (0/2 decisions from cache), applied 1, treated 0, stopped on `no_paragraph_was_written`, conservation conserved (202 → 202 paragraphs).

**Courier-en** — `examples/output/final/Courier-en/Courier-en.final.pdf`

8 pages classified deterministic (article_body ×3, article_opener ×3, editorial ×1, photo_spread ×1), 4 ambiguous. 7 page boundaries examined, 2 linked into 2 chain(s); 2 translated jointly over 4 member(s), 0 escalated. 3 article(s) grouped (1 page(s) unassigned), 3 brief(s) built of 3 requested, 3 from cache, 0 failed. 3 drop-cap candidate(s) marked, 3 ruled on (2 flattened). Ruling `reviews/Courier-en.decisions.json` applied: 6 term(s), of which 5 reached an input; 1 page kind(s) overruled; 4 auto-glossary entry/entries displaced, 141 kept. Detection found 7 issue(s) (fragment_cluster ×1, untranslated_residue ×6); the repair loop ran 1 iteration(s), chose translate_orphan_lines (0/1 decisions from cache), applied 0, treated 0, stopped on `no_paragraph_was_written`, conservation conserved (132 → 132 paragraphs).

**Courier-zh** — `examples/output/final/Courier-zh/Courier-zh.final.pdf`

8 pages classified deterministic (advertisement ×1, article_opener ×2, sidebar_heavy ×5), 6 ambiguous. 7 page boundaries examined, 0 linked into 0 chain(s); 0 translated jointly over 0 member(s), 0 escalated. 2 article(s) grouped (6 page(s) unassigned), 2 brief(s) built of 2 requested, 2 from cache, 0 failed. 0 drop-cap candidate(s) marked, 0 ruled on (0 flattened). No ruling file; every decision point ran on the machine default. Detection found 7 issue(s) (untranslated_residue ×7); the repair loop ran 1 iteration(s), chose translate_orphan_lines (0/1 decisions from cache), applied 0, treated 0, stopped on `no_paragraph_was_written`, conservation conserved (135 → 135 paragraphs).

**FD-en-v2** — `examples/output/final/FD-en-v2/FD-en-v2.final.pdf`

9 pages classified deterministic (advertisement ×2, article_opener ×3, front_cover ×1, masthead ×2, toc ×1), 4 ambiguous. 8 page boundaries examined, 0 linked into 0 chain(s); 0 translated jointly over 0 member(s), 0 escalated. 3 article(s) grouped (6 page(s) unassigned), 3 brief(s) built of 3 requested, 3 from cache, 0 failed. 0 drop-cap candidate(s) marked, 0 ruled on (0 flattened). No ruling file; every decision point ran on the machine default. Detection found 23 issue(s) (fragment_cluster ×1, untranslated_residue ×22); the repair loop ran 2 iteration(s), chose translate_orphan_lines, translate_orphan_lines (0/2 decisions from cache), applied 2, treated 0, stopped on `no_paragraph_was_written`, conservation conserved (189 → 189 paragraphs).

**Vogue-en** — `examples/output/final/Vogue-en/Vogue-en.final.pdf`

3 pages classified deterministic (advertisement ×2, toc ×1), 2 ambiguous. 2 page boundaries examined, 0 linked into 0 chain(s); 0 translated jointly over 0 member(s), 0 escalated. 0 article(s) grouped (3 page(s) unassigned), 0 brief(s) built of 0 requested, 0 from cache, 0 failed. 0 drop-cap candidate(s) marked, 0 ruled on (0 flattened). No ruling file; every decision point ran on the machine default. Detection found 3 issue(s) (untranslated_residue ×3); the repair loop ran 1 iteration(s), chose none (0/1 decisions from cache), applied 0, treated 0, stopped on `decision_applied_nothing`, conservation conserved (39 → 39 paragraphs).


## 3. Quick-look anomaly list

**Invariants and things that should not happen**

- `Courier-en` — ruled term 'CourierT H E UNESCO' matched no input and changed nothing

**Worth an eye while reading**

- `AramcoWorld-en-v2` — 19 untreated untranslated_residue issue(s) stand in the finished PDF
- `AramcoWorld-en-v2` — 4 request(s) missed cache and reached the API (attributed in §5)
- `CERNCourier-en` — 1 repair application(s) wrote paragraph(s) p2#32
- `CERNCourier-en` — 4 untreated fragment_cluster issue(s) stand in the finished PDF
- `CERNCourier-en` — 27 untreated untranslated_residue issue(s) stand in the finished PDF
- `CERNCourier-en` — 3 request(s) missed cache and reached the API (attributed in §5)
- `Courier-en` — 1 untreated fragment_cluster issue(s) stand in the finished PDF
- `Courier-en` — 6 untreated untranslated_residue issue(s) stand in the finished PDF
- `Courier-en` — 1 request(s) missed cache and reached the API (attributed in §5)
- `Courier-zh` — 7 untreated untranslated_residue issue(s) stand in the finished PDF
- `Courier-zh` — 1 request(s) missed cache and reached the API (attributed in §5)
- `FD-en-v2` — 2 repair application(s) wrote paragraph(s) p5#14, p5#9
- `FD-en-v2` — 1 untreated fragment_cluster issue(s) stand in the finished PDF
- `FD-en-v2` — 22 untreated untranslated_residue issue(s) stand in the finished PDF
- `FD-en-v2` — 2 request(s) missed cache and reached the API (attributed in §5)
- `Vogue-en` — 3 untreated untranslated_residue issue(s) stand in the finished PDF
- `Vogue-en` — 1 request(s) missed cache and reached the API (attributed in §5)

## 4. The PDFs

| sample | path | pages | chars | CJK share | sha256 |
| --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | `examples/output/final/AramcoWorld-en-v2/AramcoWorld-en-v2.final.pdf` | 9 | 9043 | 0.655 | `7dcea269bab62d76…` |
| CERNCourier-en | `examples/output/final/CERNCourier-en/CERNCourier-en.final.pdf` | 4 | 7868 | 0.575 | `934d6670ddbb36ec…` |
| Courier-en | `examples/output/final/Courier-en/Courier-en.final.pdf` | 8 | 7165 | 0.749 | `51dde26d08d33782…` |
| Courier-zh | `examples/output/final/Courier-zh/Courier-zh.final.pdf` | 8 | 8165 | 0.732 | `c2a9330083f54da4…` |
| FD-en-v2 | `examples/output/final/FD-en-v2/FD-en-v2.final.pdf` | 9 | 5728 | 0.57 | `7ddfa3793286223f…` |
| Vogue-en | `examples/output/final/Vogue-en/Vogue-en.final.pdf` | 3 | 1292 | 0.415 | `bafd6da522a2e4cd…` |

The last two columns are a sanity read of the produced file rather than a
metric: text is present on every page set and the Chinese share is where a
translated magazine page should put it, lowest on the sample that is mostly
photography and brand marks.


## 5. Notes from the run

**1. The repair decision cache cannot hit across runs, and the reason is generic.**
0 of 8 repair decisions came from cache. That is not a cold
cache: the same decisions were requested by earlier smoke runs of the same
configuration. The decide request states each finding's evidence, and the
evidence carries the paragraph's `debug_id`, which the IL regenerates every run.
A repeat of `AramcoWorld-en-v2` immediately after this run detected the *same*
19 issues with the same ids, evidence and excerpts, and still missed the
decision cache — the two evidence blocks differ only in `debug_id`
(`Z3ngq` against `T1XNw`). Artefacts in `cache_probe/`. So the repair layer pays
one decide request per iteration on every run, and its cache serves only a rerun
inside the same process. Worth a bounded fix later — the key is the prompt text,
and an identifier that is not stable across runs does not belong in it.

**2. Three translator requests missed cache, all in `AramcoWorld-en-v2`.**
The repeat above ran the whole sample with the engine wrapped and logged every
call the cache did not serve: **one**, the decide request of note 1, and zero
translator requests (`cache_probe/AramcoWorld-en-v2.misses.json`). So the three
were prompts the project cache had never held, and it holds them now; the same
sample replays free. What made them new is not settled here — the request groups
this run built are identical to the historical smoke's, group for group, so the
difference is in the per-paragraph fallback path rather than in batching.

**3. Untranslated residue is the dominant standing issue.**
84 of the 90 findings that stand in the finished PDFs are
`untranslated_residue`, concentrated in the ad-heavy and masthead-heavy samples.
The repair loop is allowed to act on them and mostly declines: across six samples
it applied 3 repair(s) and treated 0 findings, stopping on
`no_paragraph_was_written` in 5 of 6.
Reading the PDFs is the point of this run, so read those pages knowing the loop
saw them and left them.

**4. `magazine_hitl_export` was down, so `reviews/` is untouched by this run.**
Verified: the four files under `reviews/` carry the same digests before and
after. Only `Courier-en` has a ruling; the other five ran fully automatic, which
is what an empty ruling means operationally.

