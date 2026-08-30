# UPSTREAM_DIFF

Deviations from the donor code and from the plan a batch was executed under.
One entry per deviation, newest batch last.  A deviation is anything a later
reader would otherwise have to reconstruct from a diff: a signature that moved,
a test whose expectation was rewritten rather than fixed, a plan premise that
turned out not to hold.

## B12 — MAPE-K demo (`b12-mapek-demo`)

### T0 premise deviations

**P5 is only literally true.**  The plan recorded that the three dormant
detector modules exist and that `configs/detectors.json` already carries
`overlap` and `abnormal_blank` parameters.  Both hold.  What does not hold is
the premise T1 rested on — that all three are contract-compatible and need at
most a minimal in-module adaptation:

- `detectors/overlap.py` is compatible and was wired as written.
- `detectors/abnormal_blank.py` loops over `run_trace.flow_slots`.  Nothing in
  the repository constructs a `RunTrace`; `minimal_detection.py` does not pass
  one to `DetectionContext`, so the field is always `None`.  Re-pointing it at
  the live `flow_report` does not help either: `article_flow.SWITCH` is
  `magazine_column_reflow`, which `minimal_pipeline._FIXED_FALSE_ATTRIBUTES`
  pins false, so `article_flow.apply` always returns its disabled record with
  no slots at all.
- `detectors/instruction_compliance.py` is entirely `RunTrace`-driven and has
  no half that survives without one.

Reported at the T1 boundary rather than improvised around.  The adjudicated
answer was to keep the closed vocabulary at nine kinds and the kind names
unchanged, build no `RunTrace`, leave `magazine_column_reflow` false, and
re-seat the two blocked detectors on data the minimal path actually produces.
`decision_rounds.json` `kind_order` is unchanged.

**P12 is understated.**  `examples/input/` holds twelve sample PDFs, not six:
`ABB-zh`, `AramcoWorld-en-v2`, `CERNCourier-en`, `Courier-en`, `Courier-zh`,
`FD-en-v2`, `HuaweiTech-zh`, `ITU-zh`, `Vogue-en`, `WIPO-zh`, `bull-zh`,
`fd-zh` (five `en`, seven `zh`).  Adjudicated to run all twelve in T6.

### Baselines this batch is measured against

Measured at `73b411a` before any change, so that "still green" means "no worse
than it was" rather than "passes":

- `tests/minimal`: **9 failed, 306 passed**.  The nine are four
  `test_malformed_chain_reply_is_protected_without_fallback` parameterisations
  plus `test_placeholder_damage_fails_closed`
  (`test_chain_single_request.py`), `test_explicit_selection_restores_source_total_before_structure`
  and `test_after_typesetting_refreshes_fixed_before_dropcap`
  (`test_detectors.py`), `test_after_typesetting_is_one_shot_after_success_and_failure`
  (`test_drop_cap_keep_flatten.py`), and
  `test_courier_pages_seven_and_eight_build_offline_structure`
  (`test_structure_real_pdf.py`).
- `tools/spec_check_expectations_scope.py` already fails at `73b411a`
  (3/5 fixtures).  Every other `spec_check_*` passes.

### T1a — `text_figure_overlap` wired

- `babeldoc/magazine/detectors/__init__.py`: `DETECTOR_NAMES` 6 → 9.  All three
  new kinds are declared here, because `detectors/base.py:328-329` requires
  every declared kind to carry a severity; the detectors behind
  `abnormal_blank` and `instruction_compliance` arrive in T1b and T1c.
- `configs/detectors.json`: `severity`, `progress_evidence` and
  `suggested_actions` entries for the three new kinds; `text_figure_overlap`
  added to `profile_detectors.minimal`; the `description`'s "six-detector"
  wording replaced.  All three new kinds map to `no_op` at this stage — real
  actions arrive in T3.
- `babeldoc/magazine/minimal_detection.py`: `overlap` imported and added to
  `_PAGE_DETECTORS`; `ISSUE_KINDS` 6 → 9.
- `tools/verify_minimal_pdf.py`: `ISSUE_KINDS` 6 → 9, tracking the vocabulary.
- `tests/minimal/test_detectors.py`: the `set(DETECTOR_KINDS) == {...six...}`
  assertion rewritten to the nine kinds.  This test asserts the closed
  vocabulary, and the vocabulary is what deliberately changed, so the
  expectation was rewritten rather than the code bent to keep it.
- `tests/minimal/test_minimal_pdf_validator.py`: its local six-kind `KINDS`
  tuple replaced by `verify_minimal_pdf.ISSUE_KINDS`.  A third copy of the
  vocabulary would have been a second default source, which the batch's red
  lines forbid; importing the one declaration removes the drift instead of
  duplicating the edit.

### Environment

`pytest` was missing from the `babeldoc` conda environment despite being a
declared dev dependency (`pyproject.toml:158`); installed there so the suite
and the gates run in the environment the pipeline runs in.

### T1b — `abnormal_blank` re-seated on geometry

`detectors/abnormal_blank.py` was **replaced in place**, not extended.  The
donor implementation looped over `run_trace.flow_slots` and its every input --
`RunTrace`, released flow slots, article slot capacity hints -- reached it
through a producer this pipeline does not have.  Keeping it beside a working
implementation would have left a dead branch that reads as a supported path, so
the RunTrace version is gone rather than guarded.  Nothing else imported it.

What it measures now, all from fields `DetectionContext` already carries:

- ink is `base.rendered_box(paragraph)`, the union extent of the characters the
  paragraph was laid out as.  That helper already existed and is the shared
  detectors-side function the plan asked for, so no second one was written.
  A paragraph with no laid-out character falls back to its own box and is
  skipped rather than measured as perfectly full.
- membership and reading order come from `context.article_document_ir`;
  protection from `context.fixed_inventory.protected_paragraph_refs`, which is
  the same question the rest of the pipeline asks about what may be touched.
- physical-to-local reference mapping goes through
  `context.source_geometry.local_ref`, the route `_with_contract` already uses,
  rather than a positional convention invented here.

The thresholds are the two keys that were already in `configs/detectors.json`;
no new key and no second default.  `abnormal_blank_min_capacity_ratio` is read
as the adjudicated spelling -- ink over box below the floor -- while the two
*declared severity dimensions* count blank rather than fill
(`blank_capacity_ratio == 1 - fill_ratio`), because `acceptance.py:258-260`
reads any rise in a dimension as a worsening, so a fuller box has to score
lower.  `fill_ratio` is carried in the evidence beside them for readability.

The last member an article has on a page is excluded, per adjudication.  Taken
per page, not per article: a member ending at a page or column break is where
body text is legitimately allowed to stop short.  This is the more conservative
of the two readings and is what `spec_check_b12_t1b.py` S2 pins.

Note on reachability: the two floors together require the blank remainder to be
at least a fifth of the *page*, so only a paragraph whose box is itself a large
share of the page can ever be reported.  This is the adjudicated rule as
written; whether real samples trip it is a T6 measurement, reported as measured.

### T1c — `instruction_compliance` re-seated on HITL rulings

`detectors/instruction_compliance.py` was **replaced in place**.  Every input of
the donor version -- `trace.chain_outcomes`, `trace.sources`,
`trace.generations`, `trace.fragments`, `trace.geometries` -- came from a
`RunTrace`, and it had no half that survives without one.  Nothing else
imported it.

Prechecks the adjudication made conditional, all confirmed before writing:

- `MinimalPipelineState` retains the review state (`minimal_pipeline.py:81`,
  `:125`) and it is live at `after_typesetting`, carrying both `.decisions` and
  `.source_text_pages`.
- All twelve samples have a decisions file in `reviews/`, with 1--46 ruled
  terms each (eleven of twelve non-empty), 0--9 ruled page kinds (nine of
  twelve non-empty) and ruled drop caps in two (`Courier-en`, `FD-en-v2`).
- The drop-cap application record exists and is locatable per page: `hitl`
  stores it at `state.report["applied"]["drop_caps"]`, rows carrying
  `paragraph` (a `p<physical>#<index>` reference) and `decision`.

**Deviation from the literal C3 wording, and why.**  The adjudication said to
compare the `page_kinds` ruling against the `page_classify` report.  That
comparison cannot work: `PageClassifier.process` runs and writes
`page_classify.report.json` at `minimal_pipeline.py:427`, *before*
`hitl.page_kind_pass` at `:431` overwrites `page.page_kind` with the human
ruling.  The report therefore records what the machine decided, and a human
ruling is supposed to differ from it -- so the literal check would report every
correctly applied override as a violation, and report nothing when a ruling was
genuinely lost.  It is exactly inverted.

What is implemented instead answers the intent -- did the human constraint
survive to the finished document -- by comparing the ruling against the live
document (`page.page_kind`, `paragraph.drop_cap_decision`) and, beside it, the
applying pass's own record.  Carrying both lets a finding distinguish "never
landed" from "landed and was later overwritten", which is in the evidence as
`recorded_as_applied` and `carried_by_document`.  The "only check where there is
a report" clause is kept: the records are read from the HITL report, and their
absence yields no finding.  `spec_check_b12_t1c.py` S2 pins the consequence --
a fixture with every ruling honoured reports nothing.

**Contract change.**  `DetectionContext` gained one optional field,
`hitl_state: object | None = None`, alongside the optional pass-through
references it already carries (`article_document_ir`, `fixed_inventory`,
`run_trace`).  `minimal_detection.detect` gained a matching keyword-only
`hitl_state=None`, and `minimal_pipeline` passes `state.hitl_state` at both
detection call sites.  Additive: every existing caller and detector is
unaffected.  The detector imports `babeldoc.glossary` for the one normalisation
both sides of a term comparison must share; that module imports nothing from
`babeldoc.magazine`, so the package docstring's ban on pulling in taxonomy,
profiles, checkpoints or RunTrace still holds.  `hitl` itself is deliberately
**not** imported, because it does pull in `taxonomy`.

`configs/detectors.json` names `instruction_compliance` in `document_detectors`
beside `chain_conservation` and `fixed_asset_drift`, and `minimal_detection`
runs it there rather than in the page loop.

### T2 — the model decision layer

Adjudicated: **react/ stays asleep.**  `babeldoc/magazine/llm_decide.py` is a new
module and imports nothing from `babeldoc/magazine/react/`.

Why the plan's "reuse react/decide.py's validators" was not taken.  Both
`react/config.py:39` and `minimal_repair.py:23` read the same
`configs/repair_actions.json`, under mutually incompatible schemas: react wants
`actions` as an object carrying `applicability`/`parameters`/`max_applications`,
while the minimal parser wants a list of names and rejects unknown root keys.
Worse, `react/config.py:112-116` declares `REQUIRED_APPLICABILITY` for exactly
three actions -- `translate_orphan_lines`, `contain_in_page`,
`resolve_collision` -- and refuses to parse any action name not in it.  None of
the six action names this batch uses is among them, so the reuse would have
meant editing react's own vocabulary declaration and migrating
`minimal_repair`'s configuration parsing, its two tests and its admission gate.

**Validation scope, as adjudicated: shape and vocabulary only.**  `interpret`
checks exactly four fields; the action within the set that round offered;
`issue_ids` a subset of the ids shown; parameters declared by the chosen action
and inside their ranges.  No admission semantics.  A decision is a *nomination*;
`admits_*` keeps the veto.  `spec_check_b12_t2.py` S5 pins this from the other
side: a nomination the admission rule would refuse must still validate, and the
module is grepped for `admits_`, `article_document_ir` and `by_element` to prove
it reaches for no admission state at all.

**Prompt: the placeholders were kept, the wording was not.**  Three small block
builders (`issues_block`, `actions_block`, `constraints_block`) were written in
`llm_decide.py` against the placeholder names the file already uses
(`{issues_block}`, `{actions_block}`, `{action_constraints}`), which was the
second of the two options offered.

That was recorded here as "prompt unchanged", and it was wrong.  The donor text
around those slots told the model to answer `"none"` to apply nothing, while the
vocabulary the new `actions_block` emits names that entry `no_op`.  Every round
that chose to do nothing therefore spent a violation and a retry recovering from
a contradiction inside its own request -- and the retry hid it, because the
second answer was right and the round succeeded.  It was visible only in
`repair_decisions.jsonl`, which is the first thing that audit trail was good for.

The prompt now points at the offered vocabulary instead of naming a word of its
own, and `spec_check_b12_t2.py` S9 refuses any action word in the template that
no round accepts.  Filling a slot is not the same as reading the page it sits
in; the lesson is the general one.

The `constraints_block` sentence templates live in code and the numbers they
state come from the configuration, so the rule the model reads and the rule
`admits_*` applies cannot state different figures.

**New gate assertion, as adjudicated.**  `spec_check_b12_t2.py` S7 greps the
whole repository and requires that, outside `react/`, the donor package is
imported at exactly two places -- `babeldoc/magazine/rotated_lane.py:60` and
`babeldoc/magazine/title_typeset.py:35`, both the same writeback helper.  A
second decision path waking up unnoticed now fails a gate.

**Configuration.**  `configs/repair_actions.json` gained `decide_model` (with a
closed `decide_model_vocabulary` rather than a range, a model name not being a
threshold), `decide_temperature`, `decide_max_attempts`,
`decide_max_issues_per_round`, `decide_issue_excerpt_chars` -- each with its
`*_allowed_range` -- and `decide_parameters`, which is empty because no action in
the current vocabulary takes a settable parameter yet.  `minimal_repair`'s
`_ROOT_KEYS` gained these names via a separate `_DECIDE_KEYS` frozenset so that
the two readers of the file stay explicit about which keys are whose;
`minimal_repair` reads none of them.  The parameter rules are therefore
exercised in the gate against an explicit declaration rather than against a
number invented in the shipped file.

### T3 — three new actions, a six-action closed vocabulary

`configs/repair_actions.json` is now `mapek-demo.v1`.  `actions` holds the six;
`issue_actions` is the kind-to-permitted-set table the decision rounds choose
from (no_op always implicit, an empty set meaning escalate-only).

**`deterministic_issue_actions` is a second mapping, deliberately.**  The
one-shot `repair_once` pass picks an action from the kind alone, and three
existing tests plus `spec_check_repair_admission.py` pin what it picks.  Rather
than change what that pass does as a side effect of widening the vocabulary, its
old single-action mapping is frozen under its own key and `repair_once` reads
only that.  The two mappings answer different questions -- "what the frozen
one-shot pass does" and "what a decision round may choose from" -- and
`repair_once` is superseded by the loop in T4.

`tests/minimal/test_one_repair.py::test_closed_actions_and_deterministic_selection`
asserted the three-action vocabulary; rewritten to the six, with an added
assertion that the frozen mapping is unchanged, so the test now pins the thing
that must not move rather than the thing that did.

Role vocabularies come from the layout-label space the rest of the pipeline
uses: `contain_heading` takes the title pair class of `chain_detection.json`
(`title`, `paragraph_title`) and `retypeset_article_region` the body pair class
(`text`, `plain text`, `paragraph_hybrid`).  Note that the pre-existing
`refit_or_reflow_owned_paragraph.eligible_roles` names `body`, which is not a
label any pair class declares and appears only there and in the older repair
fixture; it was left alone as out of scope, and `spec_check_b12_t3.py` uses the
production labels so the new actions are not tested against a label no document
carries.

#### Two judgment calls in `reallocate_chain_cut` — flagged for review

The plan warned to stop rather than improvise if `redistribute`'s calling
surface did not match P10.  It very nearly does, and the action is implemented,
but two things the plan did not anticipate had to be decided.  Both are local
and reversible, and both fail closed.

**1. The merge is rebuilt from the report, not carried.**  `redistribute` wants
a `ChainMerge`.  By repair time the paragraphs carry the translation and the
source member texts are gone; `chain_translation.report.json` keeps their
*lengths* (`merge.member_chars`), the separators, and -- importantly -- the full
merged `translation` string.  Reading the two functions settles what this costs:
`redistribute` touches only `len(merge.members)` and `merge.shares` (a ratio of
lengths), and `verify_redistribution` only `len(merge.members)`.  So the merge is
rebuilt at the recorded lengths with filler member text, and the rebuild is
refused unless the reconstructed length matches the recorded `merge.chars`.  If
a later cut planner starts reading member text, that check fails and the action
refuses rather than cutting on filler.

**2. Reported strategy names are not cascade names.**  The chain pass reports
the level it settled on as `slot_tail_aligned` / `slot_capacity`, while
`chain_translation.json`'s `slot_cascade` names the strategies without the
prefix (`tail_aligned`, `capacity`).  "One level down" is therefore read by
stripping the prefix and stepping the cascade; a chain already at the bottom, or
reported under a name the cascade does not carry, is refused as
`chain_realloc_no_further_strategy`.  On the sample report inspected, the
recorded strategy is `slot_capacity` -- the bottom -- so **this action will
refuse on chains cut that way**, which is a real reason it may report zero
repairs on the corpus.

If either call is wrong, the fix is local to `_rebuilt_merge` and
`_next_strategy`.

All three actions refuse *whole*: the first member that will not fit takes the
action down, and the caller's transaction restores what it had reached.
`spec_check_b12_t3.py` S8 compares the document paragraph by paragraph and
requires each action to have written exactly its own set.

### T4 — the bounded loop, and how it reaches the pipeline

`babeldoc/magazine/repair_loop.py` is new.  Ceilings live in
`configs/repair_actions.json` (`max_iterations`, `max_actions_per_iteration`,
`max_affected_elements_per_run`, each with its range).  The plan's
`max_candidate_issues_per_round` was **not** added: it is the same number as
`decide_max_issues_per_round`, which T2 already declared, and the loop reads
that one rather than declaring it twice.  `spec_check_b12_t4.py` S6 pins that
the two agree by construction.

**The call site chooses between the loop and the one-shot pass.**  The plan said
to change `minimal_pipeline` to call `repair_loop`.  It does -- but only for a
run that has a model to decide with.  `repair_once` is kept, not deprecated, as
the answer for a run that translated nothing or does not translate through a
provider the decision can reach; the loop degenerates to exactly that, and
keeping the real pass is better than simulating it.  `_decision_client` returns
None for such a run rather than raising.

That choice is deliberately made from the run's own translator -- a run given
the offline translator, or none, has no provider to put a question to -- and
**not** from whether `OPENAI_API_KEY` is in the environment.  (The first
attempt keyed on `config.openai`, which `TranslationConfig` does not carry, so
the loop would silently never have engaged; caught by the first sample run,
before it cost anything.)
Keying on the environment would make an offline test run take the loop on a
developer machine with the credential exported and the one-shot pass on CI --
the same code behaving differently by shell.  S8 pins this.

The run report now branches: a one-shot result goes through `_repair_summary`
unchanged, and a loop result through the new `_loop_summary`, which holds it to
the closed termination vocabulary and the closed action vocabulary.  The
one-shot path is byte-for-byte what it was, which is why the offline suite is
still exactly at baseline.

The loop writes the same `issues.after.json` the one-shot pass does, mirroring
the before-result whenever it kept nothing, so a finished run reads the same
whichever ran.

### T5 — before/after evidence, and the report

**Signature change.**  `minimal_pipeline.after_typesetting` gained two optional
positional arguments, `temp_pdf_path` and `mediabox_data`, and
`babeldoc/format/pdf/high_level.py:1054` passes them.  They are what the writer
needs to render the pre-repair document; both default to None, so a caller that
does not have them (every test that drives the pass directly) is unaffected.

Two test doubles of the internal `_detect_and_repair` had fixed arity and were
relaxed to `*_args, **_kwargs`
(`tests/minimal/test_title_demo.py:1020`,
`tests/minimal/test_drop_cap_keep_flatten.py:630`).  They stub an internal
function whose signature changed; nothing about what they assert moved.

**The "after" picture is the delivered document, not a second render.**  The
plan had the final product serve as "after", and it does: the pre-repair PDF is
written during `after_typesetting`, and the after-side pages are rasterised in
`finalize_result` from the run's own finished mono PDF.  So a reader compares
the page that was actually produced against the page that would have been.

The pre-repair PDF goes through the ordinary writer with a *shadowed* config --
a shallow copy with its own `output_dir`, no watermark, no dual -- so the two
pictures differ by the repair and not by how they were drawn, and the run's own
output directory is never written to by the evidence path.

**Rendering never fails a run.**  The translated document is the deliverable and
the pictures are an account of it, so a render that raises is logged and the run
finishes.  The snapshot itself is only taken when there is something to render
with, so an offline run pays no deepcopy.

`tools/mapek_report.py` reads only what runs wrote.  `spec_check_b12_t5.py`
checks the biconditional in both directions -- a page has a pair if and only if
an accepted action wrote to it -- because both halves fail silently: two renders
of an unchanged page look like evidence of a repair, and a repair that rendered
nothing leaves a claim nobody can check.

### What the first real runs exposed

Three gaps that only a real run could show, all fixed and all gated:

1. **The loop never implemented `translate_orphan_text`.**  `_apply` handled the
   four geometric actions and would have raised on the one action that asks for
   new text.  It never surfaced in the synthetic gates because the fixtures
   reach `_apply` only through actions the admission rule admits, and on the
   corpus every orphan nomination was refused before it got there.  Implemented,
   and the action now returns what it spent as well as what it wrote.

2. **The run report reads `repair["translator_requests"]` by name.**  The loop
   record did not carry it, so a run that took the loop died in
   `_build_run_report` with a bare `KeyError` after doing all its work -- the
   translated PDF was produced and then the report failed.  The loop now
   accounts for its own requests, and `spec_check_b12_t4.py` S8 pins that the
   record carries every field the report reads by name.

3. **`tools/verify_minimal_pdf.py` assumed the one-shot repair schema.**  It now
   branches: a loop run is validated against the loop's closed termination and
   action vocabularies on its own terms rather than flattened into the other
   shape.  Its root schema also gained `repair_evidence`, and the synthetic
   fixture in `tests/minimal/test_minimal_pdf_validator.py` gained the same
   section.

The first of these is the one worth remembering: the synthetic gates were green
throughout, because a fixture that only ever exercises admitted actions cannot
reach an unimplemented branch behind a refusal.

## B13 — render fixes (`b13-render-fixes`)

### T0 premise deviation: the exact-equality skip was dead code

The plan's C2 premise read `il_translator.post_translate_paragraph` as already
skipping composition rewrite on exact equality, with only near-equality as the
gap.  Literally false: upstream commit `a515ea2` ("update input reference")
changed the comparison from `translated_text == translate_input.unicode` to
`translated_text == translate_input` — a `str` against the `TranslateInput`
object — so the branch could never fire and even byte-identical output re-set
the paragraph from a generated holder.  `short_unit.identity_skipped` was
likewise always false.  The fix direction is unchanged (the planned normalized
comparison replaces that line anyway and has to read `.unicode` to normalize),
so this was recorded rather than stopped on: the defect the plan attributes to
near-equality was in fact produced by *any* equality.

### T2 — upstream file touched

`babeldoc/format/pdf/document_il/midend/il_translator.py`
(`post_translate_paragraph`): the unchanged-translation test is now
`_identity_normalized(translated) == _identity_normalized(input.unicode)` where
the normal form is exactly NFC + interior whitespace runs folded to one space +
outer whitespace stripped.  No wider fuzz (no case folding, no punctuation
width folding).  On a skip the paragraph keeps its source composition, which
downstream (`layout_report._has_generated_target`, protected passthrough in
`typesetting.render_paragraph`, `title_typeset`'s generated-target freeze)
already treats as fixed source furniture; T2 fixtures pin that chain.

### T4 premise deviation: the same-line merge already existed, unwired

The plan's T4a specified writing a new magazine pass to merge x-cut same-line
fragments.  `babeldoc/magazine/fragment_stitch.py` already implemented it —
rules, guards, source audit, report, its docstring literally naming the
Courier-en p4 defect — with the switch pinned true, **zero callers and zero
tests**: a finished module nobody wired up, invisible because the switch
completeness check only proves a switch is decided, not that the pass runs.
T4a therefore wired it (structure phase, after the classifiers, before
line_split and the chain builder) instead of writing a parallel pass, and
narrowed the shipped rules to `inline` alone: `vertical` would union a wide
band with the column below into one rectangle that overrides wrap-around
geometry (measured against p4: the union would overlap the pull quote), and
`initial` restyles an oversized opening letter to the body majority at
source-character level, destroying the style/color evidence the drop-cap lane
freezes (and which T1 just extended).  The rules validator now admits a
non-empty subset; both narrowed rules stay implemented and re-enter by
declaration.  The plan's T4a thresholds (`same_line_y_overlap` 0.7,
`same_line_max_gap_em` 1.0) were not minted: the module's own declared bounds
(`stitch_min_y_overlap_ratio` 0.6, `stitch_max_inline_gap_ratio` 0.8em)
already govern the same judgement.

T4b (band-sequence chaining) was new as planned: boundary kind
`intra_column` in `chain_signals`/`chain_builder`, deterministic gates, one
new bounded parameter `intra_column_chain_max_gap_pt` (6, range 1..24), the
lowest assembly priority, everything downstream (pair class, strategies,
joint translation, conservation) reused untouched.

## B14 — anchor, tails, masthead (`b14`)

### T3 — upstream files touched

`babeldoc/format/pdf/document_il/midend/styles_and_formulas.py`
(`is_translatable_formula`): the rescue that hands a swallowed formula back to
the translator accepted only digit/comma runs.  It now also accepts a run of
ordinary words — letters joined by word punctuation with at least one
two-letter sequence — because the formula-font name table claims any font
whose name contains "Mono", and FD's masthead role lines (GTFlexaMono-Light,
"EDITOR-IN-CHIEF", …) were swallowed whole by their typeface alone and never
offered to the translator.  A single letter still stays a formula (that is
what a variable looks like), as do raised runs and anything carrying digits
or operators.

`babeldoc/format/pdf/document_il/midend/il_translator.py`
(`post_translate_paragraph`, tracking serializer): the unchanged-translation
skip now consults `babeldoc.magazine.echo_retry` before pasting back — one
bounded, explicitly-instructed retry for a short unit that echoed in the
wrong script for the target (a personal name, a role line), configured in
`configs/echo_retry.json` and prompted by `prompts/echo_retry.md`.  A retry
that still echoes keeps the pasteback exactly as before and is recorded; the
tracking rows carry the outcome under `echo_retry`.
