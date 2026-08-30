# B12 delivery report — MAPE-K demo

Branch `migration/minimal-v0.6.4`, from `73b411a` to `b12-mapek-demo`.
Everything below is measured, not estimated. Where a thing was not done, it says
so and why.

## 1. T0 premise check

| # | premise | result |
| --- | --- | --- |
| P1 | fixed-path switches | **holds** — `minimal_pipeline.py:237-268` |
| P2 | repair entry between typesetting and the writer | **holds** — `high_level.py:1052-1056` |
| P3 | one-shot deterministic repair, `max_actions_per_run: 1` | **holds** — `minimal_repair.py:26-38` |
| P4 | six-kind vocabulary, four page detectors | **holds** |
| P5 | three dormant detectors, contract-compatible | **partly false — see below** |
| P6 | `decision_rounds.json` declares 13 kinds | **holds**, unchanged by this batch |
| P7 | decide and retry prompts exist | **holds** (the decide prompt's wording was wrong — §5) |
| P8 | typed_lexicographic acceptance, rollback available | **holds** — `acceptance.py:306-343` |
| P9 | `retypeset_bounded_text(minimum_scale, maximum_lines)` | **holds** — `typesetting.py:1596-1630` |
| P10 | `redistribute` / `verify_redistribution` / slot cascade reusable | **holds with two caveats — §4** |
| P11 | key from `OPENAI_API_KEY` | **holds** |
| P12 | six sample PDFs in `examples/input/` | **understated — twelve** |

**P5 is the one that stopped the batch.** The three modules exist and their
config parameters exist, so the premise as written is true. What is not true is
that all three are contract-compatible:

- `overlap.py` needed nothing and was wired as written.
- `abnormal_blank.py` loops over `run_trace.flow_slots`. **Nothing in the
  repository constructs a `RunTrace`**, and `minimal_detection` never passes one,
  so the field is always `None`. Re-pointing it at the live `flow_report` does
  not help either: `article_flow.SWITCH` is `magazine_column_reflow`, which the
  fixed path pins false, so `apply` always returns its disabled record.
- `instruction_compliance.py` is entirely `RunTrace`-driven with no half that
  survives without one.

Reported at the T1 boundary rather than improvised around. The adjudicated
answer — nine kinds, names unchanged, no `RunTrace`, both detectors re-seated on
data the minimal path actually produces — is what was built.

**P12**: twelve samples, not six (`ABB-zh`, `AramcoWorld-en-v2`,
`CERNCourier-en`, `Courier-en`, `Courier-zh`, `FD-en-v2`, `HuaweiTech-zh`,
`ITU-zh`, `Vogue-en`, `WIPO-zh`, `bull-zh`, `fd-zh`; five `en`, seven `zh`).

## 2. Gate results

All seven B12 gates pass. Fifty-two claims in total.

| gate | claims | subject |
| --- | ---: | --- |
| `spec_check_b12_t1a.py` | 5 | overlap wired; the six old kinds detect identically with and without it |
| `spec_check_b12_t1b.py` | 6 | under-filled member reported; the article's last member on the page is not |
| `spec_check_b12_t1c.py` | 7 | lost rulings reported; **honoured rulings report nothing** |
| `spec_check_b12_t2.py` | 9 | shape and vocabulary only; a nomination the admission rule refuses still validates |
| `spec_check_b12_t3.py` | 8 | three actions, each refusing whole; nothing outside the written set moves |
| `spec_check_b12_t4.py` | 9 | oscillation rolled back entire; four "did nothing" stops told apart |
| `spec_check_b12_t5.py` | 6 | evidence exists **iff** there is a repair to show |

## 3. Regression

Measured at `73b411a` before any change, so "green" means "no worse than it
was", not "passes":

- `tests/minimal`: **9 failed / 306 passed**, before and after, the same nine by
  name. The nine are pre-existing; the newest of them
  (`test_courier_pages_seven_and_eight_build_offline_structure`) fails because
  `c307ca3` turned VLM classification on and the test still asserts it is off.
- `spec_check_expectations_scope.py` fails at baseline (3/5 fixtures) and still
  does. Every other pre-existing gate passes.
- `verify_minimal_pdf.py` on the Courier-en run: **`MINIMAL_PDF_VALID`**.

**`verify_magazine_demo.py` does not pass on Courier-en** —
`unadjudicated detector chain: ('p2#3', 'p3#1')`. This batch touched no
structure, chain-detection or page-classification code, and `chain_report.json`
is produced entirely upstream of anything changed here
(`git diff --stat 73b411a..HEAD` covers 11 files, none of them on that path).
Treated as pre-existing fixture drift and **not fixed**; flagged rather than
worked around.

## 4. Deviations from the plan

Every one is in `UPSTREAM_DIFF.md` in full. The four that change what the paper
can claim:

**T1c C3 is inverted from the literal spec.** The plan said to compare a
`page_kinds` ruling against the page-classify report. That cannot work:
`PageClassifier.process` writes its report at `minimal_pipeline.py:427`, *before*
`hitl.page_kind_pass` at `:431` overwrites `page.page_kind` with the human
ruling. The literal check would report every correctly applied override as a
violation and stay silent when a ruling was genuinely lost. What is implemented
compares against the finished document and carries both `recorded_as_applied`
and `carried_by_document`, so a reader can tell "never landed" from "landed and
was overwritten".

**`reallocate_chain_cut` needed two decisions the plan did not anticipate.** The
source member texts are gone by repair time, so the `ChainMerge` is rebuilt from
the lengths the chain report kept — sound because `redistribute` and
`verify_redistribution` read only `len(members)` and a ratio of lengths, and
guarded by a reconstruction-size check that fails closed if a future cut planner
starts reading the text. And the report's `slot_capacity` is not a cascade name,
so "one level down" strips the prefix and steps the cascade. **A chain already
cut at the bottom of the cascade is refused**, which is a real reason this action
may report zero on any corpus.

**The loop runs only where there is a model to decide with.** `repair_once` is
kept, not deprecated: a run that translated nothing, or that does not translate
through a provider the decision can reach, keeps the deterministic pass. The
choice is made from the run's own translator, not from whether `OPENAI_API_KEY`
is in the shell — keying on the environment would make the same code behave one
way on a developer machine and another on CI.

**`max_candidate_issues_per_round` was not added.** It is the same number as
`decide_max_issues_per_round`, which T2 already declared, and the loop reads
that one. A second declaration of one number is a second source.

## 5. What the runs found

Two samples, chosen on measured layout contrast and on decision-file coverage,
from the five with expectation fixtures on record:

| | pages | images | chars/page | ruled terms / page kinds / drop caps |
| --- | ---: | ---: | ---: | --- |
| `Courier-en` (en→zh) | 8 | 5 | **2939** | 14 / 1 / **3** |
| `bull-zh` (zh→en) | 9 | **23** | 664 | 11 / **9** / 0 |

`Courier-en` is the densest-body sample in the corpus and **the only one of all
twelve with all three decision sections non-empty**, so it is the only sample
that can exercise C1, C2 and C3 together. `bull-zh` is the figure-heavy
counterpart with the richest page-kind rulings.

### Measured

| | wall | translation cache | decision calls | violations | findings | stopped |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `Courier-en` | 43 s | 57/57 (**100%**) | 2 | 0 | 6 | `all_candidates_refused` |
| `bull-zh` | 5 m 53 s | 62/62 (**100%**) | 4 | 0 | 17 | `all_candidates_refused` |

Both runs completed (`status: complete`), produced their PDFs, and spent **zero
translation API cost** — every request was a cache hit, because the corpus had
been translated by earlier runs in this session. The only billed calls are the
six decision requests, about 47 KB of prompt in total; at `gpt-4o` rates that is
cents, not dollars. A cold run would cost what translation costs and is
unchanged by this batch.

**Zero repairs were accepted, on either sample.** That is the honest result and
the report states it as zero rather than omitting the rows.

### What the loop actually did

All three new detectors fired on real documents:

- `instruction_compliance` — 1 on Courier-en, 3 on bull-zh. On Courier-en it
  found one genuinely non-adopted term ruling on page 1 **and verified the other
  17 rulings were honoured**, which is the "compliant input stays silent"
  property holding on real data rather than only in a fixture.
- `text_figure_overlap` — 1 on bull-zh.
- `abnormal_blank` — 0 on both. Expected: the two adjudicated floors together
  require the blank remainder to be at least a fifth of the *page*, so only a
  paragraph whose box is itself a large share of the page can ever be reported.

The decision step behaved: on Courier-en it nominated exactly the four residue
findings at or above the 0.9 floor and skipped the one at 0.889. Every
nomination was then refused by the deterministic admission rule —
`orphan_is_canonical_article_text` (the residue is article-owned body text, not
orphan lines) and `region_target_has_no_canonical_owner`. **The veto held against
well-formed decisions**, which is the property the whole design rests on.

So the loop is demonstrably wired end to end — detect, decide, admit, measure,
stop for a named reason — and on these two samples it correctly concluded that
nothing it was allowed to do was worth doing.

### Six defects the real runs found that the gates did not

Every gate was green throughout. These reached live runs:

1. The loop had **no branch for `translate_orphan_text`** — fixtures reach an
   action only through an admission rule that admits it, so an unimplemented
   branch behind a refusal is unreachable in testing.
2. The run report reads `repair["translator_requests"]` by name and the loop
   record lacked it, so a loop run did all its work and died assembling its own
   report.
3. `verify_minimal_pdf.py` assumed the one-shot repair schema.
4. `TransactionSnapshot.capture` deep-copied pages past the recursion ceiling on
   a large document.
5. `transaction._page_xml_digests` failed outright where the checkpoint
   serializer meets `LazyPassthroughInstruction`, which bull-zh carries and
   Courier-en does not.
6. The decide prompt told the model to answer `"none"` while the vocabulary
   offers `no_op`, costing a violation and a retry on every do-nothing round —
   and **the retry concealed it**, because the second answer was right. Visible
   only in `repair_decisions.jsonl`.

The pattern is one thing, not six: **the gates test the loop's logic thoroughly
and its contact with a real document not at all.** A fixture is small,
well-formed, serializable, and only ever exercises admitted actions. Closing
this class needs a gate that drives the real pipeline over one real sample; that
is its own task and is not done here.

## 6. Artifacts

- `docs/reports/B12/mapek_repair_report.md` — the per-kind evidence report over
  both samples, zeros written as zeros.
- `examples/output/B12/Courier-en-loop/work/Courier-en/` and
  `examples/output/B12/bull-zh/work/bull-zh/` — each holding
  `issues.before.json`, `issues.after.json`, `termination.json`,
  `repair_decisions.jsonl` and `minimal_run.report.json`.
- No `evidence/` directory and no before/after PNGs on either sample: nothing was
  accepted, so there is no repair to show. The gate checks that biconditional in
  both directions.
