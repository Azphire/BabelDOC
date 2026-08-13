# B8 session three — the real smoke and what the loop actually did

Batch `b8.3`. Covers T8.3.0 (authorised maintenance) and T8.3 (the real-API
smoke and the promise 3 evidence set). One configuration, six samples, one
credential spent.

The headline is not the one the plan hoped for and is stated first so nothing
below reads as a build-up to it: **the loop found the standing defect, decided
to repair it, sent it with the human ruling binding the answer, got the ruled
rendering back, wrote it into the paragraph, laid that paragraph out again — and
then rolled the whole iteration back**, because its own convergence guard saw
the same number of findings after the repair as before it. The produced PDF is
therefore the batch-b7.5.2 PDF, page for page, and every one of the six samples
ended the same way: nothing repaired, everything conserved.

Two independent mechanisms produced that, and one of them means the rollback was
the right outcome for a reason nobody designed. Both are in section 6. Every
number below is what came out.

## 1. What was run

| | |
| --- | --- |
| driver | `examples/output/b8/scripts/run_repair_smoke.py` |
| analysis | `analyze_repair_smoke.py`, `rasterize_subject.py`, `summarize_regression.py` |
| model | `gpt-4o`, 4 qps, project-local cache |
| stack | every magazine switch up, including `magazine_hitl_apply`, plus `magazine_detect` and `magazine_repair` |
| against | batch-b7.5.2 second pass, which is the same stack minus the last two |

The comparison is the point of holding the rest still. Every body paragraph is
the request it already was under batch-b7.5.2 and is replayed from the cache, so
a difference between the two outputs is the loop's doing or it is a defect. The
run confirms the premise rather than assuming it: **132 paragraphs compared, 0
different** before the loop touched anything.

The loop's own requests are recorded as they were made. The sidecar carries what
was decided and what came back; the driver additionally wraps the two prompt
builders and the transport, so `prompt_trace.jsonl` beside each run carries the
exact rendered text of every request. Wrapping is observation only — each
wrapper calls through and returns what it got.

## 2. The end to end record of `p6#15`

### a. Detected

`issues.json`, iteration 0, from the deterministic residue detector:

```
id:        untranslated_residue:p6:p6#15
kind:      untranslated_residue      severity: high
page:      6                          layout_label: fallback_line
geometry:  (413.37, 711.22) .. (419.87, 826.03)
evidence:  residue_script=latin  residue_chars=33  script_chars=33
           residue_ratio=1.0     min_ratio=0.6
excerpt:   "r The UNESCO Courieréniako fo© Boris Sém"
```

### b. Decided

One request, `prompts/react_repair_decide.md`
(`744bfb666e22851a...`), answered live. The reply verbatim:

```json
{"action": "translate_orphan_lines",
 "issue_ids": ["untranslated_residue:p6:p6#15",
               "untranslated_residue:p8:p8#15",
               "untranslated_residue:p5:p5#10"],
 "parameters": {"max_paragraphs": 3},
 "reason": "The untranslated residues have high residue ratios and character
            counts, indicating clear untranslated text that needs translation."}
```

Three of the six residue findings, the subject first. The deterministic
applicability rule then refused `p8#15` on its layout label — it is an
`abandon` region, which means the translator *was* offered it and what it
renders as is that translator's decision, not an omission.

### c. Sent, with the ruling in the request

The rendered orphan prompt for `p6#15` carries the glossary block, and the
ruled entry is in it beside the automatically extracted ones:

```
| Source Term        | Target Term          |
| Courier            | 信使                  |
| UNESCO             | 联合国教科文组织        |
| UNESCO Courier     | 联合国教科文组织信使     |
| The UNESCO Courier | 联合国教科文组织《信使》  |   <- the human ruling
```

This is the closing of the b7.5.2 gap in the mechanism: the ruling reaches a
paragraph the translator never saw, because the repair path matches glossaries
with the same matcher the translation prompt does. The reach counter agrees —
`hitl_apply.report.json` now reports `The UNESCO Courier` activating
**5** prompts against the 4 translator-side sites, and `repair_inputs: 2`.

### d. Translated and written back

```
source:  r The UNESCO Courieréniako fo© Boris Sém
reply:   {"translation": "r 联合国教科文组织《信使》éniako fo© Boris Sém"}
```

Written into the paragraph, the paragraph laid out again on its own through the
existing typesetting stage: `accepted`, `changed: true`. One paragraph, one
relayout.

### e. Rechecked, and rolled back

The recheck found the same 7 findings it started with. `p6#15` was still among
them:

| | residue chars | script chars | ratio | detector bound |
| --- | ---: | ---: | ---: | ---: |
| before | 33 | 33 | 1.000 | 0.60 |
| after | 17 | 27 | **0.630** | 0.60 |

The repair cut the residue by nearly half and missed clearing the bound by
0.03. The finding count therefore did not strictly decrease, the convergence
guard undid the iteration, and the loop stopped:

```
iteration 1  detected 7  ->  recheck 7   resolved: []   new: []
outcome: rolled_back
stopped: finding_count_did_not_strictly_decrease
applications: 0   touched_refs: []   changed_refs: []   verdict: conserved
```

## 3. The ruled publication name, site by site

The six sites are the ones batch-b7.5.2 enumerated, so this is a fixed list
rather than whatever this run happened to find. Two readings of "now": the
document the PDF was written from, and the same document with the rolled-back
write put back.

| site | label | b7.5.2 pass 2 | b8.3 as produced | b8.3 as repaired |
| --- | --- | --- | --- | --- |
| p1#9 | title | 信使T H E 联合国教科文组织 | unchanged | unchanged |
| p2#0 | abandon | 联合国教科文组织《信使》… | same | same |
| p4#0 | abandon | 联合国教科文组织《信使》… | same | same |
| p6#0 | abandon | 联合国教科文组织《信使》… | same | same |
| p6#15 | fallback_line | r The UNESCO Courier… | **unchanged** | r 联合国教科文组织《信使》éniako fo© Boris Sém |
| p7#0 | abandon | 联合国教科文组织《信使》… | same | same |

**4 of 6 as produced; 5 of 6 as repaired.** Not 6 of 6 under either reading,
and `p1#9` is the site that cannot be reached from here: its source text is the
scrambled `CourierT H E UNESCO`, the ruling's entry for that exact string
matches no prompt (`matched_prompt_count: 0`, and the b8.1 warning fires on the
run), and the paragraph is a `title` the translator was offered and did render.
It is not an orphan, so no action in the v1 vocabulary answers for it. Recorded
as unreachable rather than counted as a near miss.

The "as repaired" column is a substring test — the ruled target occurs in the
text the repair wrote — and section 6a is why that is not the same as the site
reading correctly. Even the 5 of 6 is a count of where the name arrived, not of
where the line came out right.

## 4. Blast radius

Four independent measurements, none of them reading the sidecar that makes the
claim.

1. **Translation stack.** Per-paragraph digests of the batch-b7.5.2 second-pass
   typesetting checkpoint against this run's: **132 paragraphs, 0 changed.**
   The stack reproduced itself exactly, which is what makes the rest of this
   section attributable to the loop.
2. **The loop's own conservation.** `pages 8 -> 8`, `paragraphs 132 -> 132`,
   `touched_refs: []`, `changed_refs: []`, `changed_outside_touched: []`,
   verdict `conserved`. Changed is a subset of touched trivially, both being
   empty after the rollback.
3. **The rendering.** Text extracted page by page from the batch-b7.5.2 mono PDF
   and from this run's: **0 pages differ.** The two files are the same length
   and differ in bytes only where a PDF carries per-run identifiers.
4. **The pixels.** Page 6 rasterised at 4x out of both PDFs is byte-identical
   (`d06294a6b05e9374…`), and so is the crop of the disputed region
   (`0d419706e8117591…`). This is the strongest form the claim takes: not that
   the text is the same, but that the page draws the same.

## 5. The rendering evidence

`smoke/raster/b8_3.p6_15.png` is the finding's own geometry cropped out of page
6 of the produced PDF at 4x, with an 18 pt margin. It shows the strip standing
in its source language, set bottom-to-top along the right edge of the artwork:

> © Boris Séméniako for The UNESCO Courier

Reading that image against the text the detector was given exposes something no
measurement in this batch was looking for, and it is section 6's first item.

## 6. Two mechanisms, named

### a. The paragraph is read in the reverse of its reading order

The strip is three style runs. In the intermediate language they are stored top
of page first; the strip is set rotated, so a reader reads them bottom of page
first. `rendered_text` concatenates them in list order, so what every detector
and the repair action see is the reverse of the line:

| run | y band | text |
| ---: | --- | --- |
| 0 | 768.4 .. 824.9 | `r The UNESCO Courier` |
| 1 | 743.4 .. 768.4 | `éniako fo` |
| 2 | 711.0 .. 743.4 | `© Boris Sém` |

Read 2, 1, 0 and the line is `© Boris Séméniako for The UNESCO Courier`. Read
0, 1, 2 — which is what the request carried — and it is the garble quoted in
section 2.

Consequences, in order of severity. The residue detector is unaffected: it
counts scripts, and a permutation does not change a count. The repair action is
badly affected: it sent a scrambled line to a model, and the model did the only
sensible thing with it, which was to substitute the one recognisable phrase and
leave the rest alone. Had the iteration survived, the page would have carried a
Chinese publication name embedded in a still-scrambled credit. **The rollback
prevented a bad rendering, for a reason unrelated to why it fired.**

Nothing in b8.1 or b8.2 knew this. It is visible only by putting the raster and
the request side by side, which is why the rendering evidence was worth taking.

### b. The convergence guard cannot see a repair that improved without resolving

Strict decrease in the finding count is the guard PLAN_B8 specifies, and it is
the right guard for the failure it was written against — a repair that trades
one defect for another. It cannot express "the same finding, but less of it".
A partial repair of a mixed-script line is exactly that case: the ratio fell
from 1.00 to 0.63 and the finding survived, so a genuine improvement was
indistinguishable from no progress and was undone.

The two bounds involved are 0.60 (the detector's, from `configs/detectors.json`)
and 0.90 (the action's applicability, from `configs/repair_actions.json`). After
the repair the paragraph sits between them: still reported, no longer eligible
to be acted on. That interval is where a partial repair lands by construction,
and nothing in v1 has a way to say so.

Neither of these was tuned away. Moving either bound to make this document
converge would be fitting a threshold to one page of one magazine, which
`CLAUDE.md` §4.5 forbids and which would have made this report a worse one.

## 7. The regression face

Same configuration, all six samples, one row each. Every one of them ran to a
finished PDF and every one came through with its pages, its paragraphs and every
paragraph the loop did not write byte for byte as typesetting left it.

| sample | pages | paras | detected | named | refused | written | stopped because |
| --- | ---: | ---: | --- | ---: | --- | ---: | --- |
| Courier-en | 8 | 132 | 6 residue, 1 fragment | 3 | 1 label, 1 unchanged | 1 → rolled back | count did not decrease |
| Courier-zh | 8 | 135 | 7 residue | 3 | 2 label | 1 → rolled back | count did not decrease |
| AramcoWorld-en-v2 | 9 | 146 | 19 residue | 3 | 1 label, 1 unchanged | 1 → rolled back | count did not decrease |
| FD-en-v2 | 9 | 189 | 24 residue, 1 fragment | 3 | 3 label | 0 | nothing the action may act on |
| CERNCourier-en | 4 | 202 | 28 residue, 4 fragment | 3 | 3 label | 0 | nothing the action may act on |
| Vogue-en | 3 | 39 | 3 residue | 3 | 3 label | 0 | nothing the action may act on |

**6 of 6 conserved. 0 paragraphs repaired in any produced PDF.** Three
documents had a repair written and rolled back by the convergence guard; three
never got past the applicability rule, which refused every finding the decision
named on its layout label — those paragraphs were offered to the translator and
what they render as is that translator's decision, which is the rule working as
designed rather than failing.

`escalation_surfacing` fired on nothing. Six real runs, no chain escalation, so
that detector still has no live evidence and its only exercise remains the b8.1
fixture. Recorded as a gap rather than as a pass.

Cost across the six: **292 API calls, 229 462 prompt tokens, 58 minutes** of
wall clock. `Courier-en` accounts for 2 of those calls; the other five were
translated for the first time under this stack and paid for it.

`Courier-zh` is an already-Chinese document run under the corpus-wide `en -> zh`
setting like every other sample. That it still yields 7 residue findings is not
a defect in the detector: they are Latin credits and URLs standing in a Chinese
page, which is what the rule says they are.

### The pattern worth naming

Every one of the six named exactly three findings, which is
`max_paragraphs`'s default and the value the decision itself chose. The round 1
wording asks for every finding whose evidence shows the defect, on the explicit
grounds that a refused finding costs nothing and an unnamed one costs the
iteration. The model named three anyway, on documents reporting 19, 24 and 28 of
them. On `Vogue-en`, `CERNCourier-en` and `FD-en-v2` all three it named were
refused on the same ground, and a fourth would have cost one more line of JSON.

## 8. Prompt iteration (T3.4 discipline)

One prompt was reworked, in one round, against a ceiling of three. Both rounds
are frozen under `smoke/prompt_rounds/` with the trace, the repair sidecar and
the detection sidecar each produced.

| round | `prompts/react_repair_decide.md` | what the decision named | written |
| --- | --- | --- | ---: |
| 0 | `61fafa9e370e2b19…` | p1#25, p3#2, p5#10 — three of six, the strongest evidence not among them | 0 |
| 1 | `744bfb666e22851a…` | p6#15, p8#15, p5#10 — strongest evidence first | 1 |

Round 0 named three findings and stopped at three, and the three it chose
included two the applicability rule refused outright. Nothing in the request
told the model that naming a finding the rule refuses costs nothing while
leaving one out costs the iteration, and nothing told it how to order what it
named. The round 1 wording states both as general properties of the loop —
name every finding whose evidence shows the defect, order by how much of the
defect the evidence reports — and names no document, no publication, no page
type and no layout label.

## 9. Maintenance delivered (T8.3.0)

**a. The gate cache fits a build in before publishing it.** The opening trim in
`run_all` bounds what a sweep starts from and not what it reaches: a sweep on a
new fingerprint builds a whole generation on top of a cache already at the
ceiling. `spec_checks/artifacts.py` now measures a staged build, sweeps least
recently used slots until that much room exists, and only then publishes. The
sweep is best effort by construction — a slot it cannot remove is left alone and
the build publishes anyway, because a cache over its ceiling is a disk bill
while a build that raised is a gate that cannot run. A slot larger than the
whole budget is published with the overrun reported, since no sweep could make
it fit. Both the fitting and the hostile case are asserted against fabricated
slots in a disposable cache root (`check_01a`, `check_01b`), and the publish
path is asserted to go through the seam before the atomic move (`check_01c`).

One consequence of that work is worth stating rather than leaving to be found:
a staging directory is now excluded from the slot listing outright, so a sweep
can never delete the build it is making room for. The cost is that a staging
directory abandoned by an interrupted build is invisible to the size accounting
and is never reclaimed. The trade is deliberate and it is the right way round —
before the change a staging directory that had reached its `meta.json` was a
slot like any other and a concurrent sweep could delete it mid-build — but an
orphaned `.partial` is now dead weight that only `--clear-cache` removes. One
is sitting in the cache from an interrupted build in this session.

**b. `issues.json` is in the run inventory.** The b8.1 detection sidecar was
never declared in `configs/checkpoint_stages.json`; the b8.2 repair sidecar was.
Both are now, and `check_02` scans the magazine package recursively rather than
globbing its top level, which is the hole the first one fell through.

**c. W-B8-01 is stated in full where it is cited.** The b8.2 delivery report
named the waiver by id alone. It now carries what the waiver says — that
`magazine_repair` is an attribute read with `getattr(..., False)` rather than a
`TranslationConfig.__init__` parameter, and that the loop is reached through the
`magazine_detect` hook — and its lift condition: a batch authorised to touch
`translation_config.py` and `high_level.py` again, after which the flag becomes
a constructor parameter and the loop takes its own hook.

## 10. Gate results

`spec_checks/run_all.py`, full sweep, no API key and no network request:
**21/21 gates, 578/578 assertions, 19 780 s.** The configuration edit in T8.3.0b
is inside the cache fingerprint, so this was a cold rebuild: 49 slots built,
147 served, 9 446 s spent building.

That sweep is also the first measurement of what a whole generation costs:
**15.19 GB**, against the 16 GB ceiling T8.0 had just raised from 8. In-sweep
trims dropped 0 slots, which is the mechanism reporting that it was armed and
not needed. Under the old 8 GB ceiling the same sweep would have spent its
second half sweeping away slots of the generation it was still building, and
every gate that came after would have rebuilt them — which is the failure the
pre-publish check exists for and which the raised ceiling means nobody had to
watch happen.

## 11. Provenance notes

- The runs were made with the driver writing its review drafts into the
  repository `reviews/` directory. The working tree was restored afterwards and
  the driver now redirects the review layer into each run's own directory, with
  the ruling copied in read-only. The change moves where a file is written and
  nothing the loop does.
- The ruling itself (`reviews/Courier-en.decisions.json`) and
  `corpus/registry.user.json` were read and not written, which `check_07a`
  asserts against the batch delta.
- `Courier-en` cost 2 API calls and 2 827 prompt tokens: one decision and one
  orphan line. Everything else was served from the project cache.

## 12. Left open

1. **Reading order of rotated and vertical paragraphs.** Section 6a. The repair
   action needs the line, and `rendered_text` gives it a permutation of the
   line. A composition-order rule that sorts runs by their band along the
   writing direction would fix it, and every detector and action that reads a
   paragraph as text is affected, so it is not a change to make in passing.
2. **A convergence rule that can see partial progress.** Section 6b. Strict
   decrease in the count is not the only ordering available: the same findings
   with strictly less evidence in each is progress by any reading, and the
   detectors already report the quantity that would say so.
3. **`p1#9` remains out of reach.** A scrambled title the translator did render.
   No v1 action answers for it, and the ruling entry written for its exact
   source string matches nothing. Promise 1 closes at 5 of 6 sites in the
   mechanism and 4 of 6 in the artefact.
4. **The decision model's selection quality is the live risk**, and it is the
   thing the stub tests could not have found. Three behaviours, all from real
   runs and none in b8.2's spectrum:

   - **It anchors on the parameter it just set.** Six documents, six decisions,
     three findings named every time — including on documents reporting 19, 24
     and 28. It reads `max_paragraphs: 3` as a quota to fill rather than as a
     ceiling the action applies for it, and the round 1 wording saying
     otherwise in as many words did not move it.
   - **Its ordering is not stable and was not evidence-led until it was told
     to be.** Round 0 named the three findings carrying the *least* untranslated
     text out of six, with the two strongest excluded and no ordering rule in
     the request. One paragraph of wording fixed it, which is the good news and
     also the bad news.
   - **It cannot see the applicability rule and so it burns its quota.** On
     three of six samples every finding it named was refused on the layout
     label. The rule is declared in `configs/repair_actions.json` and is not in
     the request at all: the request lists an action's *kinds*, not what it may
     act on. A decision step that cannot see the filter it is feeding will keep
     feeding it things the filter throws away.

   What follows for the next batch is a test shape, not a wording fix. b8.2's
   stub spectrum covers reply *shape* — legal, out of vocabulary, bad JSON,
   unknown id — and every one of the three above is a reply of perfect shape and
   poor judgement. Those need a fixture with a known-correct selection and an
   assertion about which findings were named, which is a different kind of test
   from the ones the batch has.
5. **`fragment_cluster` and `text_figure_overlap` remain report only**, and the
   census they produce across the corpus is in `smoke/regression.json`: 6
   clusters over the six samples, no overlaps at all, which is a thinner harvest
   than the fragment and overlap history of the b2 line suggested, and worth a
   look before an action is written for either.
6. **`escalation_surfacing` still has no live evidence.** Six real runs raised
   no chain escalation, so the detector that only moves records from one sidecar
   to another has been exercised by a fixture and never by a document.
