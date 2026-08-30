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

**Prompt: unchanged.**  `prompts/react_repair_decide.md` was not edited.  Three
small block builders (`issues_block`, `actions_block`, `constraints_block`) were
written in `llm_decide.py` against the placeholder names the file already uses
(`{issues_block}`, `{actions_block}`, `{action_constraints}`), which was the
second of the two options offered.  No prompt audit summary needs updating.

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
