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
