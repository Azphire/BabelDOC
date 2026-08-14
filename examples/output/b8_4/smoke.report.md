# B8.4 — the repair lands, and the one that could not land says why

Batch `b8.4`. Covers T8.4a through T8.4f: reading order, treated semantics,
the constraint the decision step was missing, the storage policy, and one real
run of the whole stack over the corpus.

The headline is not the one the plan wrote and is stated first. **Three repairs
reached a produced PDF and every one of them held its box. The subject of the
whole B8 line, `p6#15`, was for the first time sent to a model as the line it
actually is, came back correctly translated with the ruled publication name in
it — and was then refused at the write-back, because rendering that line needs
more room than the strip it stands in has.** The refusal is the batch's second
result and it was found by looking at pixels, not at the intermediate language,
which had reported the repair as a success.

## 1. What was run

| | |
| --- | --- |
| driver | `examples/output/b8_4/scripts/run_repair_smoke.py` |
| analysis | `analyze_repair_smoke.py`, `rasterize_subject.py` |
| model | `gpt-4o`, 4 qps, project-local cache |
| stack | identical to batch b8.3: every magazine switch up, `magazine_detect` and `magazine_repair` included |
| cost | **16 API calls, 30 635 prompt tokens, 26.6 minutes** over six samples |

Everything below the switches changed and nothing about them did, so a
difference between this run's output and b8.3's is this batch's doing.

## 2. The end to end record of `p6#15`

### a. Read as the line it is (T8.4a)

The strip is three style runs stored top of page first and read bottom of page
first. Two batches concatenated them in list order and sent a model the
permutation. The ordering rule is derived from the characters' own advance
direction, and on the frozen b8.3 fixture it moves **3 of 90 paragraphs**, all
of them vertical `fallback_line`s; the other 87 render byte for byte what they
rendered before.

```
before   r The UNESCO Courieréniako fo© Boris Sém
after    © Boris Séméniako for The UNESCO Courier
```

### b. Decided, and answered

One decision request, one orphan request, both live. The reply:

```
source:  © Boris Séméniako for The UNESCO Courier
reply:   © Boris Séméniako 为 联合国教科文组织《信使》
```

The ruled publication name is in it, matched by the same glossary matcher the
translation prompt uses. The photographer's name is correctly left in Latin,
which is the model doing the right thing and is also the reason the next step
fails.

### c. Refused at the write-back

Laying that line out again does not produce a vertical strip. Typesetting has
no vertical mode — a unicode unit is always emitted horizontal — so
`render_paragraph` widens the box until the line fits across the page:

| | box | area |
| --- | --- | ---: |
| before | (413.4, 711.2) .. (419.9, 826.0) | 746 pt² |
| after, unguarded | (413.4, 232.4) .. (530.7, 826.0) | 69 700 pt² |

Rendered, that is the credit reprinted horizontally across the top of the
artwork it used to run down the edge of. The first run of this smoke shipped
exactly that, and every measurement taken on the intermediate language called
it a success: conserved, one paragraph touched, one paragraph changed, the
target script present.

So the write-back now reads the box either side of laying a paragraph out
again and refuses a composition that needs more room than the paragraph had.
Shrinking is allowed; growing is not.

```
p6#15  retypesetting_needed_more_room_than_the_paragraph_had
       box unchanged, orientation flag unchanged, text unchanged
loop   stopped: no_paragraph_was_written   applications: 0   verdict: conserved
```

The loop stops with `no_paragraph_was_written` rather than with a rollback: an
iteration that wrote nothing has nothing to undo, and the document is what
typesetting left.

The rule is content-dependent rather than a blanket refusal of rotated
paragraphs, which is what it should be. Probed against the same fixture
paragraph:

| written back | box after | verdict |
| --- | --- | --- |
| `© Boris Séméniako 为 联合国教科文组织《信使》` | grows 93× | refused |
| `为联合国教科文组织《信使》拍摄` (pure target script) | unchanged | repaired |
| `信` | unchanged | repaired |

A line that can be set one character per line down a strip is set; one
carrying Latin words cannot be, and is not.

### d. The rendering evidence

`smoke/raster/b8_3.p6_15.png` and `smoke/raster/b8_4.p6_15.png` are the
finding's own region cropped out of both produced PDFs at 4x. They are
**byte-identical**, which is what a refusal has to look like. The strip still
reads, bottom to top:

> © Boris Séméniako for The UNESCO Courier

`b8_4.p6_15.page6.png` from the first run — the one the guard now prevents — is
not in the tree; what it showed is described above and is why the guard exists.

## 3. What did land

Three paragraphs, on two samples, each with its box held to the point:

| sample | ref | before | after | box |
| --- | --- | --- | --- | --- |
| CERNCourier-en | p2#32 | `Volume 66 Number 4  July/August 2026` | `第66卷第4期 2026年7月/8月` | unchanged |
| FD-en-v2 | p5#14 | `ADVISORS TO THE EDITOR` | `编辑顾问` | unchanged |
| FD-en-v2 | p5#9 | `PRODUCTION MANAGER` | `制作经理` | unchanged |

`smoke/raster/b8_3.p2_32.png` against `b8_4.p2_32.png` is the pair worth
looking at: the same masthead line, in the same place, at the same baseline, in
the target language. That is a landed repair with nothing else moved, and it is
the first one this project has produced.

All three are horizontal orphans. Every one of them was left standing by batch
b8.3, two of them because that batch's decision never named them.

## 4. Blast radius

| measurement | result |
| --- | --- |
| paragraphs digested from this run's typesetting checkpoint | **132** |
| paragraphs the loop touched on `Courier-en` | 0 |
| paragraphs changed outside what was touched | 0, on every sample |
| pages of the produced `Courier-en` PDF differing from b8.3's | 0 |
| conservation verdict | `conserved`, 6 of 6 |

`Courier-en` produces a PDF identical to b8.3's page for page, which is the
correct outcome for a run whose only candidate repair was refused. The two
samples that did repair differ from b8.3 only on the pages carrying a repaired
paragraph.

The cross-batch comparison b8.3 could make — per paragraph digests against the
batch-b7.5.2 typesetting checkpoint — is not available here, because the
retention policy this batch introduces removed that checkpoint. See section 7.

## 5. Decision quality (T8.4c)

The request now states the applicability rule it is feeding, rendered from the
same declaration the rule is applied from (`configs/repair_actions.json`,
`applicability.statements`), plus wording that a parameter is a ceiling rather
than a quota and that naming a finding the rule refuses costs the iteration.

Named against admissible, first decision of each run, measured from the
rendered request rather than from the loop's own verdicts:

| sample | b8.3 named / of those eligible | b8.4 named / of those eligible | eligible available |
| --- | --- | --- | ---: |
| Courier-en | 3 / 2 | 3 / **3** | 3 |
| AramcoWorld-en-v2 | 3 / 2 | 2 / **2** | 3 |
| CERNCourier-en | 3 / 0 | 1 / **1** | 4 |
| Courier-zh | 3 / 1 | 1 / **1** | 1 |
| FD-en-v2 | 3 / 0 | 8 / 2 | 7 |
| Vogue-en | 3 / 0 | **0 / 0** | 0 |
| **total** | **18 / 5 (28%)** | **15 / 9 (60%)** | |

Three things in that table are worth naming.

**The quota anchor is gone.** b8.3 named exactly three findings on all six
samples, including documents reporting 19, 25 and 32 of them; that was the
clearest sign it read `max_paragraphs: 3` as a target. No sample named three
for that reason here, and `Vogue-en` — where nothing at all qualifies — named
nothing, which no wording had previously achieved.

**The hit rate roughly doubled**, 28% to 60%, on a corpus where the eligible
sets did not move.

**`FD-en-v2` went the other way and is the honest counter-example.** It named
eight against seven eligible, which is over-naming rather than quota-filling —
and it is also the sample where two repairs landed, because two of the eight
were right. Over-naming costs a spent list entry; under-naming costs the
iteration. The batch is not claiming the model now selects correctly; it is
claiming the request no longer hides the filter from it, and the measurement is
recorded so the next batch can argue with it.

One sample, one model, temperature-0 sampling that is known non-deterministic
on this engine. This is a measurement, not a significance claim.

## 6. Treated semantics (T8.4b)

The convergence guard now counts findings the run has neither resolved nor made
smaller. A finding a repair improved without clearing is *treated*: not offered
again, not acted on again, not counted against the loop again. What quantifies
"smaller" is declared per issue kind in `configs/detectors.json`
(`progress_evidence`), so nothing in code names an evidence field.

Neither of the two bounds moved, and the gate checks that mechanically against
`git show batch-b8.3:` rather than against numbers written in a test:

| bound | b8.3 | b8.4 |
| --- | ---: | ---: |
| `residue_min_ratio_into_zh` (detector) | 0.6 | 0.6 |
| `min_residue_ratio` (action) | 0.9 | 0.9 |

`converged_with_residuals` — the new stop reason for a run whose every
remaining finding it has already improved — did not fire on any live document,
because the reading-order fix meant the one repair that was attempted either
resolved its finding outright or was refused. It is exercised by a synthetic
scenario in the gate, and recorded here as a mechanism with no live evidence
rather than as a demonstrated one.

The guard is not weaker for it. Two synthetic negatives hold: a repair that
rewrites a line into the same defect rolls back, and one that writes back more
of the defect than it replaced rolls back. Batch b8.2's own rollback case
passes unchanged.

## 7. Storage (T8.4d, T8.4f)

| | |
| --- | --- |
| `examples/output/` pruned | **1.91 GB**, 439 files, batches older than the two most recent |
| baseline checkpoints | 231 MB of directories → **13 MB** of archives |
| abandoned gate-cache builds swept | **2** (356 MB), where b8.3 knew of one |

`tools/prune_outputs.py` keeps every file git tracks, every path the corpus
manifest names, and the most recent batches whole; earlier batches keep their
`*.report.md` and `*.log`. `run_all` applies it at the end of every sweep.

The guarantee that this does not break a gate is the tracked-file rule, not the
retention window: every gate from b0 to b8.3 passes over the pruned tree
because the evidence each of them reads is committed. What it does cost is
stated in section 4 — the b7.5.2 typesetting checkpoint is gone, so a
cross-batch paragraph digest comparison against it can no longer be made. That
is the policy working as declared, and the next batch can still compare against
this one.

Baseline checkpoints are now `<name>.checkpoints.zip`. Every reader resolves a
checkpoint directory to the archive standing for it, so the manifest still
names the directory and nothing that reads a baseline knows the difference. The
round trip assertion the b7.5 gate makes about those files now runs through the
archive path.

## 8. Gate results

`spec_checks/spec_check_b8_4.py`: **32/32 assertions**, no API key and no
network request. `spec_checks/run_all.py`, full sweep: see the session log.

## 9. Left open

1. **A vertical typesetting mode.** This is now the thing standing between the
   loop and the strip. The request is right, the reply is right, and the write
   back is refused because the only composer available sets text across the
   page. Until there is one, `translate_orphan_lines` can repair a horizontal
   orphan and cannot repair a rotated one, and the gate asserts that it says so
   rather than pretending otherwise.
2. **`p1#9` remains out of reach**, unchanged from b8.3: a scrambled title the
   translator did render, whose ruling entry matches no prompt.
3. **`converged_with_residuals` has no live evidence.** Section 6.
4. **`escalation_surfacing` still has no live evidence.** Six more real runs
   raised no chain escalation.
5. **The selection is measured, not solved.** Section 5. `FD-en-v2` names more
   than qualifies; nothing in the request bounds how many a decision may name
   beyond the ceiling the action applies afterwards.
6. **`fragment_cluster` and `text_figure_overlap` remain report only.**

## 10. Provenance

- The runs redirect the review layer into each run's own directory with the
  ruling copied in read-only. `reviews/` and `corpus/registry.user.json` were
  read and not written.
- Two rounds of the decision prompt are frozen under `smoke/prompt_rounds/`
  with the trace and both sidecars each produced. Round 0 is the b8.3 prompt
  with the applicability rule injected and nothing else changed; round 1 adds
  the wording. The injection is not optional — the prompt loader is strict
  about variables in both directions, so a template without the section cannot
  be rendered by the code that supplies it.
- Round 0's sidecar was produced before the write-back read the box, and
  records `p6#15` as repaired; round 1's is the final run. The pair is a record
  of two promptings, not of two write-backs, and the difference between their
  `applications` counts is the guard of section 2c rather than anything the
  wording did.
- The first run of this smoke, which shipped the sprawled credit, is not in the
  tree. Its evidence is section 2c.
