# B8 session one — issue framework and deterministic detectors

Batch `b8.1`. Covers T8.0 (authorised maintenance) and T8.1 (issue schema,
four detectors, the pipeline hook). T8.2 and T8.3 are not in this session.

## 1. Premise review

Three premises the plan rests on, each checked against the tree before any
code was written.

### a. What a `fallback_line` paragraph looks like in the intermediate language

`babeldoc/format/pdf/document_il/midend/layout_parser.py:178-208`
(`generate_fallback_line_layout_for_page`) mints a `PageLayout` with
`class_name="fallback_line"` for every line cluster the detector model left
outside a block. The label is in the priority list and in the text-layout set
(`document_il/utils/layout_helper.py:725`, `:844`), so characters are assigned
to it and it becomes a paragraph.

The standing instance, read from the batch b7.5 second pass typesetting
checkpoint (`examples/output/b7_5/pass2/work/Courier-en/`), page 6 paragraph
15:

| field | value |
| --- | --- |
| `layout_label` | `fallback_line` |
| `pdf_style` | **null** — the paragraph carries no style of its own |
| `box` | complete: `(413.37, 711.22) .. (419.87, 826.03)` |
| `vertical` | **true** |
| `unicode` | `r The UNESCO Courier éniako fo © Boris Sém` |
| `pdf_paragraph_composition` | three `pdfFormula` members — every character was grouped as formula |
| `debug_id` | present (`aJ4j4`, minted per run) |

Three independent reasons this paragraph never reaches the translator, each
sufficient on its own: `ILTranslator.pre_translate_paragraph`
(`il_translator.py:962`) returns `(None, None)` for a vertical paragraph;
`get_translate_input` returns None for a placeholder-only paragraph; and the
label is outside `_is_body_text_paragraph`'s whitelist.

**Consequence for the scan domain, and one scope note.** The detector takes in
every paragraph of every page whose policy declares it translated, label
included — a scope drawn from the translator's own whitelist would define the
target out of existence. It must also tolerate a null `pdf_style`, which it
does; only the fragment detector requires one, and a paragraph without one can
never join a cluster.

The plan words the residue rule as "the translation equals the source, **or**
the Latin share is at or above the bound". Only the second disjunct is
computable at the permitted hook: the source text is not carried anywhere in
the intermediate language after `post_translate_paragraph` has rewritten the
composition, and reaching a pre-translation checkpoint would be a second hook
the plan's negative forbids. The share rule is implemented; the equality rule
is not, and this is a recall bound, recorded rather than worked around.

### b. The hook window

`babeldoc/format/pdf/high_level.py`: `Typesetting(...).typesetting_document(docs)`
at what was line 1083, the `magazine_checkpoint`-gated `typesetting` dump at
1090-1091, `PDFCreater(...)` constructed at 1093. The hook goes between the
dump and the construction.

State of the intermediate language there, read from the same checkpoint (which
is written at exactly that point):

- **Translation written back.** Page 6 paragraph 3 renders as
  `在一个嘈杂、令人感到幽闭恐惧的机器内长时间保持静止。` — target language, in the
  paragraph itself.
- **Geometry final.** Every paragraph carries `scale`, `optimal_scale` and a
  complete `box`; typesetting is what sets the first two.
- **Compositions are laid out characters**, not markup. This matters: after
  translation `paragraph.unicode` still carries the round-trip markup
  (`<style id='1'>…</style>`, `{v3}`), whose Latin letters would have counted
  as residue. The detectors measure the composition instead, which is what the
  page renders. That is `base.rendered_text`, and it was the one correction the
  first probe forced.

### c. The escalated records the surfacing detector carries

`babeldoc/magazine/chain_translation.py:287-304` (`ChainPlan._escalate`) appends

```
{chain_id, reason, detail, members: [{debug_id, chain_index, page_index, layout_label}]}
```

to `self.escalated`, and `as_record` (`:528`) writes it under `"escalated"` in
`chain_translation.report.json`. The three reasons the plan names exist as
constants: `ESCALATION_TOKEN_BUDGET = "token_budget"` (`:58`),
`ESCALATION_PLACEHOLDER = "placeholder_bearing"` (`:53`),
`ESCALATION_CONSERVATION = "conservation_failure"` (`:54`); there are three more
beside them. The detector reads that list and restates it, deciding nothing.

**Honest note.** The one credentialed run in the tree escalated nothing
(`counts.escalated = 0`), and the dry runs the census is built from run no chain
translation at all. So the detector's live count is zero everywhere and its
correctness rests on the synthetic case in the gate, which drives all three
named reasons through it.

All three premises hold. Nothing in the plan was contradicted.

## 2. What the detectors found

### Live evidence: the frozen translated document

`examples/output/b8/Courier-en.typeset.fixture.xml` is the b7.5 pass-two
typesetting checkpoint trimmed to what the detectors read (5.14 MB to 115 KB;
provenance and the trimming rule in the companion `.json`, the trimmer in
`scripts/build_fixture.py`). The trim preserves the rendered text exactly, and
the detectors produce identical findings on the full checkpoint and on the
fixture — checked when it was built.

Seven findings, reproduced by `scripts/detect_fixture.py`:

| kind | paragraphs | label | share | residue chars |
| --- | --- | --- | ---: | ---: |
| `untranslated_residue` | **`p6#15`** | `fallback_line` | 1.00 | 33 |
| `untranslated_residue` | `p3#2` | `fallback_line` | 1.00 | 16 |
| `untranslated_residue` | `p5#10` | `fallback_line` | 1.00 | 20 |
| `untranslated_residue` | `p8#15` | `abandon` | 1.00 | 30 |
| `untranslated_residue` | `p1#20` | `plain text` | 0.80 | 16 |
| `untranslated_residue` | `p1#25` | `plain text` | 1.00 | 12 |
| `fragment_cluster` | `p1#13..p1#16` | `plain text` | — | 4 members |

**`p6#15` is detected**, which is the batch's standing requirement and is a
gate assertion (`check_03a_live_residue`) rather than a number in this file.
The other two `fallback_line` findings are photo credits with the same defect,
and `p8#15` is a credit line the translator left as it was.

Two of the six are arguably not defects: `p1#20` renders
`与Ora Marek-Martinez的访谈` — a translated line retaining a personal name — and
`p1#25` is `Jim Al-Khalili`, a byline that is correct untranslated. Both clear
the bound because a name is Latin script and long enough. The thresholds were
not moved to exclude them: doing so would be tuning to this sample, and the
precision cost lands in T8.2, where the repair action has to decide what is
worth sending back through the translator.

### Corpus census

`corpus_detection.md` / `.json`, written by the gate from one dry run per
sample. These runs perform no translation, so `untranslated_residue` and
`escalation_surfacing` declare themselves not applicable and record the reason
in their own sidecar rather than reporting every paragraph of an untranslated
document as untranslated.

| sample | pages scanned | fragment_cluster | text_figure_overlap |
| --- | ---: | ---: | ---: |
| Courier-en | 8 | 0 | 0 |
| Vogue-en | 3 | 0 | 0 |
| CERNCourier-en | 4 | 2 | 0 |
| AramcoWorld-en-v2 | 9 | 0 | 0 |
| FD-en-v2 | 9 | 1 | 0 |
| Courier-zh | 8 | 0 | 0 |

Clusters found:

| sample | page | paragraphs | members | labels |
| --- | ---: | --- | ---: | --- |
| CERNCourier-en | 2 | `p2#36, p2#37, p2#38` | 3 | `plain text` |
| CERNCourier-en | 2 | `p2#56, p2#57, p2#58` | 3 | `plain text` |
| FD-en-v2 | 5 | `p5#15 .. p5#24` | 10 | `fallback_line` |

The FD-en-v2 cluster is the interesting one: ten consecutive `fallback_line`
paragraphs down one column of the infographic page, which is the same recovery
path that produced `p6#15` and here produced a whole column of it.

**Recall, recorded and not fixed.** Three clusters over 41 pages is low for a
corpus with this much broken column structure, and `text_figure_overlap` found
nothing at all — a caption printed inside a full-page photograph shares almost
none of that photograph's area, so intersection over union, which is the
quantity the plan specifies, does not see it. Both detectors are report only in
v1 and the plan's instruction is to record the recall problem rather than tune
it; the batch that acts on either finding is the batch that should choose the
measure.

## 3. What was built

- `configs/detectors.json` — every threshold bounded with an
  `_allowed_range`, the severity vocabulary, and the profile-to-detector map.
- `babeldoc/magazine/detectors/` — `base.py` (issue, bounds, context, script
  and geometry helpers), `residue.py`, `fragment.py`, `overlap.py`,
  `escalation.py`, `__init__.py` (registry, selection, sidecar).
- Hook in `high_level.py` behind `magazine_detect`, default off.
- T8.0: gate cache ceiling 8 to 16 GB; `hitl.after_translate`, which puts the
  offered text into the review draft and the reach of every ruled term into the
  apply report, warning where a ruling reached nothing; the b7.2 candidate
  table out of git.

## 4. Left open

1. The residue equality rule (premise a) is not implemented, so a paragraph
   translated into text of the same script as its source is not caught.
2. `fragment_cluster` and `text_figure_overlap` recall, above.
3. `escalation_surfacing` has no live confirmation; its evidence is synthetic.
4. Two of six residue findings on the live document are names rather than
   defects. Precision at this bound is T8.2's problem to absorb.
5. `severity` is declared and carried and nothing reads it yet; the repair
   controller of T8.2 is its first consumer.
