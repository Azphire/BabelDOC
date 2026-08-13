# B8 session two — the repair controller and translate_orphan_lines

Batch `b8.2`. Covers T8.2: the action vocabulary, the decision point, the
write-back, the loop and its guards. T8.3 is not in this session, so nothing
here was translated by a model — every engine in this batch's evidence is a
stub that answers from a rule written beside it.

## 1. Premise review

Four premises, each checked against the tree before any code was written, three
of them by running the code rather than by reading it. All four hold. Nothing
in the plan was contradicted and no upstream change turned out to be needed.

### a. Whether a translation can be written into a paragraph shaped like p6#15

**The existing round trip cannot do it, three times over, and the third failure
would be silent.** Read from the b7.5 second pass typesetting checkpoint, page 6
paragraph 15 is `vertical=true`, carries `pdf_style=null`, and holds its 40
characters in three `pdfFormula` compositions whose characters do carry styles
(`T1_1` and `T1_3` at 6.5pt).

| gate | where | what it does with this paragraph |
| --- | --- | --- |
| `ILTranslator.pre_translate_paragraph` | `il_translator.py:962-963` | `if paragraph.vertical: return None, None` |
| `ILTranslator.get_translate_input` | `il_translator.py:589-590` | returns None for a placeholder-only paragraph |
| `ILTranslator.post_translate_paragraph` | `il_translator.py:1011-1018` | sets the rebuilt run's style from `paragraph.pdf_style`, which is null here |

The third is the one that decides the question. Even reached past the first two,
the writer would leave a run with `pdf_style=None`, and
`Typesetting.create_typesetting_units` (`typesetting.py:1509-1517`) logs a
warning and **drops** such a run. The paragraph would come back empty rather
than untranslated: the round trip does not merely decline this shape, it
destroys it.

**So the write-back is the magazine-layer one the session authorised**, and it
is small: `babeldoc/magazine/react/writeback.py` takes the source text from the
composition the page renders, replaces the composition with one
`PdfSameStyleUnicodeCharacters` run set in a style taken from the paragraph's
own first character where the paragraph has none, and leaves the box, the
orientation flag and every other field alone.

**Laying it out again is the existing stage, one paragraph at a time.**
`Typesetting.render_paragraph(paragraph, page, fonts)` is public and per
paragraph. `render_page` is not used: it opens by nudging the boxes of
paragraphs that overlap each other (`typesetting.py:1157-1215`), which would
move paragraphs this repair is not allowed to touch.

**The vertical case was the open question and it was settled by running it.**
Typesetting has no vertical mode — a unicode unit is emitted with
`vertical=False` unconditionally (`typesetting.py:834`) — so the concern was
that a 6.5pt-wide strip would fail to fit at every scale and leave an empty
composition. It does not. Run against the real checkpoint:

```
before: 3 formula compositions, 'r The UNESCO Courieréniako fo© Boris Sém'
after : 15 characters, scale 0.85, box unchanged (413.37, 711.22)..(419.87, 826.03)
        vertical flag on the paragraph unchanged (true)
        first character '为' SourceHanSerifCN-Regular.ttf 5.52pt at y 820.51..826.03
        each subsequent character one line lower
```

One character per line down the strip, top to bottom, which is the conventional
vertical setting for text in Han script. The paragraph's `vertical` flag is kept
and the characters are emitted horizontal, which is what upstream typesetting
does for every rebuilt run; `PDFCreater` renders per character
(`pdf_creater.py:111-120`), so the two are consistent.

The horizontal case needed no investigation and was checked anyway, on `p8#15`
of the same document: 37 characters in, 15 out, box and scale unchanged.

### b. Font registration, and when it happens

**No rerun of anything is needed, and there is no FontMapper stage to rerun.**
Despite the stage list in CLAUDE.md, `_do_translate_single` never constructs a
`FontMapper`: `PDFCreater.__init__` does (`pdf_creater.py:625`) and
`PDFCreater.write` calls `add_font(pdf, self.docs)` (`pdf_creater.py:1134`,
`:1460`). Both are strictly after the detection hook at `high_level.py:1100`,
which is where this loop runs.

What `add_font` registers is `get_used_font_ids(il)` (`fontmap.py:215-226`),
which reads `pdf_style.font_id` off the characters each paragraph is laid out
as. A repaired paragraph's characters are produced by the same typesetting call
every other translated paragraph's are, so they name a mapped target-language
font. Measured on the repaired document: every character of the repaired p6#15
carries `SourceHanSerifCN-Regular.ttf`, and that id is in the mapper's
`fontid2fontpath`, so `add_font` will register it. The gate asserts this rather
than restating it (`check_04b_font_is_registered`).

### c. Incremental relayout

Two public entry points exist and were checked on the live document rather than
read: `Typesetting.render_paragraph` (`typesetting.py:1254`) and
`Typesetting.retypeset_with_precomputed_scale` (`:1096`). The first is used.
`paragraph.optimal_scale`, set by the earlier full typesetting pass and already
capped at the document's modal scale, is left in place and used as the starting
scale, so a repaired paragraph is not set larger than the document around it.
A rebuilt run contributes no curves and no forms, so the page's curve and form
lists do not grow; the loop snapshots their lengths anyway and truncates on
rollback.

### d. Glossary reachability at the hook

`translation_config.shared_context_cross_split_part.user_glossaries`
(`translation_config.py:39`, list built at `:323-325`) is a list of `Glossary`
objects, readable at the hook and not otherwise touched. It is where a human
ruling is put and, under W-B7-01, where the rebuilt automatic glossary is moved
to as well, so reading the user list alone reaches both tables.

The action's request is built in the magazine layer from
`prompts/react_translate_orphan.md`, and the pairs whose source occurs in the
orphan line are matched with `Glossary.get_active_entries_for_text` — the same
call `ILTranslatorLLMOnly._build_llm_prompt` matches a batch with
(`il_translator_llm_only.py:1040-1044`) — and stated in the same table shape,
from `prompts/react_orphan_glossary.md`.

The reach count is extended to cover it. `hitl.after_translate` runs before
typesetting, so it cannot see requests the loop has not made yet; a fourth hook,
`hitl.after_repair`, recounts once the loop is done, over the translator's
tracking file plus what the loop offered, and records how many of the counted
inputs came from the loop. Without it a ruling whose only occurrence is on an
orphan line would be reported as having reached nothing, which is the silence
T8.0 existed to end.

## 2. What was built

- `configs/repair_actions.json` — the loop's bounds and the action vocabulary,
  every number ranged at every depth, applicability declared per action.
- `prompts/react_repair_decide.md`, `prompts/react_translate_orphan.md`,
  `prompts/react_orphan_glossary.md`. The retry notice is the one the vision
  client already uses.
- `babeldoc/magazine/react/` — `config.py` (the vocabulary and its parser),
  `decide.py` (the cached decision point), `actions.py` (applicability and the
  cached orphan translator), `writeback.py` (composition rebuild and one
  paragraph relayout), `controller.py` (the loop, the guards, the sidecar).
- `detectors.detect_issues` hands the pass to the controller when
  `magazine_repair` is set; `hitl.after_repair` closes the reach count;
  `react_repair.report.json` is declared in the run inventory.
- No upstream file is changed. W-B8-01 records the switch: because this batch
  is delivered under a zero-upstream-change constraint, `magazine_repair` is not
  a `TranslationConfig.__init__` parameter like its siblings but an attribute
  read off the configuration object with `getattr(..., False)` and set by
  whoever builds it, exactly as `magazine_drop_cap_mark` is under W-B7-02, and
  the loop is reached through the `magazine_detect` hook rather than through a
  call site of its own. The waiver is lifted when a batch is authorised to touch
  `translation_config.py` and `high_level.py` again, at which point the flag
  becomes a constructor parameter and the loop takes its own hook.

Two properties are worth naming because both were found by running the loop
over a real pipeline document rather than a built one.

**The conservation check reads the checkpoint serialisation, not the plain
one.** A real intermediate language carries code points XML 1.0 does not admit
— which is the whole reason `magazine/checkpoint.py` escapes them — and a
parser handed the plain serialisation refuses the document entire. The
per-paragraph digest is taken from the escaped form, on both sides of the
comparison, so the escaping cannot affect what is compared. A synthetic
document never carries such a character, so nothing but the pipeline-tier
assertion would have caught this; the gate now builds one that does.

**A failure in the loop is never a failure of the run.** The loop improves a
finished translation and is not a precondition for one, so `repair_document`
puts the document back as typesetting left it, falls through to plain
detection, and lets the PDF be written. A run that could not repair produces
the PDF it would have produced with the switch down, rather than none.

## 3. The applicability filter

Two conditions, both deterministic and neither the deciding model's to
overrule.

- **Share of the wrong script at or above 0.9.** A paragraph almost entirely in
  the wrong script was not translated; a mixed one is a translation that kept a
  name in its source form.
- **Layout label in the declared orphan set, which is `fallback_line` alone.**
  That label is what `generate_fallback_line_layout_for_page` mints for a line
  cluster the layout model left outside every block, and it is the only way a
  paragraph reaches typesetting without ever having been offered to the
  translator. A paragraph carrying any other label *was* offered, and what it
  renders as is that translator's decision.

That second condition is what absorbs the precision problem b8.1 left open. Of
the six residue findings on the live document:

| finding | label | share | verdict |
| --- | --- | ---: | --- |
| `p6#15` | `fallback_line` | 1.00 | repaired |
| `p3#2` | `fallback_line` | 1.00 | repaired |
| `p5#10` | `fallback_line` | 1.00 | repaired |
| `p8#15` | `abandon` | 1.00 | refused: the translator was given it and left it |
| `p1#20` | `plain text` | 0.80 | refused: same, and below the share bound as well |
| `p1#25` | `plain text` | 1.00 | refused: same |

`p1#20` renders `与Ora Marek-Martinez的访谈` and `p1#25` is the byline
`Jim Al-Khalili`; both are correct as they stand and both are refused on the
label. `p8#15` is a photo credit the translator saw and returned unchanged,
which is a decision this action does not overrule. The gate builds both name
shapes in their measured form and asserts the refusal
(`check_03a_applicability_filter`).

## 4. The loop under a stub, end to end

`examples/output/b8/Courier-en.orphans.fixture.xml` is a second freeze of the
b7.5 second pass typesetting checkpoint, narrower than the b8.1 one and deeper:
the five pages carrying an orphan, with the orphan paragraphs kept exactly as
the run left them — characters, styles, formula grouping, boxes — and every
other paragraph kept as its rendered text. The b8.1 fixture keeps everything
the detectors read and nothing the repair needs. Both are built by scripts
beside them.

`scripts/repair_fixture.py` drives the loop over it with a stub that decides
every offered finding and renders every line. The result, recorded in
`fixture_repair.json`:

```
iteration 1  advanced        found 6   recheck 3
    wrote    p3#2   p5#10   p6#15
    refused  p1#13..p1#16  kind_outside_action
             p1#20         layout_label_not_orphan
             p1#25         layout_label_not_orphan
iteration 2  applied nothing found 3   recheck -
stopped: no_finding_the_action_may_act_on
conservation: conserved (8 pages, 132 paragraphs, 3 changed, 0 outside)
```

The same run against the untrimmed 5 MB checkpoint gives the same three
repaired references and the same two refusals.

**The rollback, in full.** A stub that renders every line into text still in the
source script produces an iteration that repairs nothing measurable:

```
iteration 1  found 2  recheck 2  ->  not strictly decreasing
             rolled_back_refs: p1#0, p1#1
stopped: finding_count_did_not_strictly_decrease
applications: 0        changed_refs: []
document: byte for byte its own serialisation before the iteration
log: "react: iteration 1 left 2 finding(s) against 2 before it; rolled back and stopped"
```

The convergence rule is strict decrease rather than no-increase precisely so
that a repair trading one finding for another cannot be mistaken for progress.

**The decision spectrum.** Six reply shapes through the decision client, all
with one rule: one retry stating the violation back, then the iteration applies
nothing.

| reply | attempts | acts |
| --- | ---: | --- |
| legal | 1 | yes |
| action outside the vocabulary | 2 | no |
| a finding that was not offered | 2 | no |
| a parameter outside its range | 2 | no |
| malformed JSON | 2 | no |
| a field nothing asked for | 2 | no |
| `"none"` — a reply that declines | 1 | no, and it is a decision rather than a violation |

A second decision over the same findings costs no request; the cache key names
the prompt file, so a reworded template is a different request.

## 5. Left open

1. **No model has run this.** Every number above comes from a stub. The real
   translation, the 6/6 masthead agreement and the before-and-after on the
   Courier-en run are T8.3, and this session deliberately did not spend a
   credential on them.
2. **`p8#15` is left standing.** It is a photo credit in the source script and
   the filter refuses it on principle — the translator was given it. Whether
   that principle is right for `abandon` regions specifically is a question for
   the batch that has a second action to offer.
3. **The vertical setting is conventional for Han script and untested for
   anything else.** An orphan strip in a document finished into a language set
   horizontally would be laid out one character per line, which would be wrong.
   Nothing in the corpus exercises it and no bound in the configuration guards
   it.
4. **`fragment_cluster` and `text_figure_overlap` remain report only.** The
   controller refuses their findings by kind and records the refusal; the action
   that answers for them does not exist.
5. **The switch is not a constructor parameter** (W-B8-01), so a caller
   misspelling `magazine_repair` gets a run with repair off rather than an
   error, and the loop cannot run with detection off.
6. **`issues.json` is still absent from the run inventory.** The detection
   sidecar b8.1 introduced was never declared in
   `configs/checkpoint_stages.json`; the repair sidecar beside it now is.
   Declaring the first is b8.1's to do and was left alone rather than fixed in
   passing.
7. **The conservation guard costs two serialisations of the whole document**
   per run, about a second each on an eight page magazine. It is only paid with
   the switch up, and nothing about it scales with the number of iterations,
   but a long document would feel it.
