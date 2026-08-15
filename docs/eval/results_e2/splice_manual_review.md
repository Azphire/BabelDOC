# Manual spot check — re-annotation (per discussion, supersedes user's first pass)

Scope note (applies to all rows): human_agrees is judged on splice-attributable errors only.
Non-splice translation noise (lexical choice, name transliteration, patent status wording) is
recorded in human_note but does not enter agrees/errors. Rows whose windows do not target the
adjudicated splice are marked PROTOCOL-INVALID and excluded from the agreement count.

Vocabulary: categories accuracy/{omission,addition,mistranslation,untranslated}, fluency/grammar,
no-error; severities minor/major/critical; human_errors ∈ {missed_error, false_positive,
wrong_category, severity_off, accepted_invalid_input}.

---

## AramcoWorld-en-v2 6->7 [upstream]
- human_agrees: [-] yes  [ ] no
- human_errors (if no):
- human_note: splice-attributable: sentence broken at boundary ("水" / "哈兰以南的路线"), tail
  half-clause dangles and head restarts mid-phrase → accuracy/omission major (Nicholson quote
  window mismatch is upstream tail-window artefact, judge's omission call is defensible).
  Judge's tail mistranslation call is the same defect from the other side; category defensible.

## AramcoWorld-en-v2 6->7 [fork_full]
- human_agrees: [-] yes  [ ] no
- human_errors (if no):
- human_note: no-error. Boundary reads as one sentence; "豪兰/哈兰" transliteration variance is
  non-splice, not counted. **This is the M1-independent positive: upstream open, fork closed.**

## Courier-en 2->3 [upstream]
- human_agrees: [ ] yes  [ ] no  — PROTOCOL-INVALID
- human_errors (if no): accepted_invalid_input
- human_note: windows taken from page-tail figure caption + page-head title, not from the two
  title chain members ("How Indigenous knowledge drives" / "scientific discovery"). Row does not
  test the adjudicated title split. Judge's chambira omission call is non-splice. Excluded.

## Courier-en 2->3 [chain_off_1]
- human_agrees: [ ] yes  [ ] no  — PROTOCOL-INVALID
- human_errors (if no): accepted_invalid_input
- human_note: same window defect as above. Excluded.

## Courier-en 2->3 [chain_off_2]
- human_agrees: [ ] yes  [ ] no  — PROTOCOL-INVALID
- human_errors (if no): accepted_invalid_input
- human_note: same window defect. Excluded.

## Courier-en 2->3 [chain_on]
- human_agrees: [ ] yes  [ ] no  — PROTOCOL-INVALID (but see note)
- human_errors (if no): accepted_invalid_input
- human_note: window defect as above; however the head "动科学发现" is a real observation — it is
  the proportional-split residue of the merged title "原住民知识如何推动科学发现" (title chain
  RRF4T, b5.3 §1a). Judge's addition/minor call is correct as a symptom but misattributed to
  source; the "动" is by design (title-chain redistribution), not addition. Excluded from count;
  carry as a note for GAP (title-chain redistribution visible at page head).

## Courier-en 7->8 [upstream]
- human_agrees: [-] yes  [ ] no
- human_errors (if no):
- human_note: splice-attributable: tail "…以及一种复合材料。" = fabricated closure
  (accuracy/addition + omission of "from the grass has been patented"); head "草地已经被申请了专利"
  = antecedent lost → "草地" (accuracy/mistranslation). Severity critical agreed. Non-splice:
  spinifex untranslated, "申请/获得" (minor, all arms). Judge category defensible.

## Courier-en 7->8 [chain_off_1]
- human_agrees: [-] yes  [ ] no
- human_errors (if no):
- human_note: splice-attributable: same fabricated closure ("以及一种复合材料。") + head restarts
  "这种草已经被申请了专利" — patent sentence split into two self-contained sentences
  (accuracy/addition + mistranslation), critical agreed. Note "这种草" not "草地": antecedent-loss
  rendering is unstable across samples (GAP-13). Non-splice: "申请/获得" minor, "针茅" for
  spinifex acceptable, not counted.

## Courier-en 7->8 [chain_off_2]
- human_agrees: [-] yes  [ ] no
- human_errors (if no):
- human_note: identical splice defect to off_1 with different upstream wording — closure and head
  restart byte-identical across the two independent samples → structural, not sampling noise
  (E2.1 finding). Critical agreed. Non-splice as above.

## Courier-en 7->8 [chain_on]
- human_agrees: [ ] yes  [-] no
- human_errors (if no): false_positive (as splice error), severity_off
- human_note: splice-attributable: NONE — tail ends "…并已为这种草的复合材料申请了专利。" (true
  sentence end), head begins next sentence "根据协议…". The only error present is "申请了专利"
  for "has been patented": accuracy/mistranslation **minor**, non-splice, present in all four arms.
  Judge scored it critical and attributed it to the splice window → severity_off + counted as
  splice error. Correct verdict for this row: no splice error.

## Courier-zh 2->3 [upstream]
- human_agrees: [ ] yes  [ ] no  — PROTOCOL-INVALID (window), judge call retained as observation
- human_errors (if no): accepted_invalid_input
- human_note: window is caption + title, not the two title members ("时代变迁背景下的" / "土著知识");
  row does not test the split. Judge's untranslated/major on "土著知识" is a correct observation of
  the head window (upstream leaves display headings untranslated zh→en, cf. baseline family 3)
  but is not the adjudicated splice. Excluded from count.

## Courier-zh 2->3 [fork_full]
- human_agrees: [ ] yes  [-] no  — PROTOCOL-INVALID (window) AND judge failure
- human_errors (if no): accepted_invalid_input, missed_error
- human_note: (a) window defect as above; (b) both windows are Chinese in a zh→en arm — judge did
  not flag language mismatch, gave a "reading" of source-language text as if translated. Pending
  IL check: source leaked into window vs paragraph genuinely untranslated (chain masked by
  sidebar_heavy misclassification, b7.5.2). Excluded from count; judge failure recorded.

## Courier-zh 7->8 [upstream]
- human_agrees: [-] yes  [ ] no
- human_errors (if no):
- human_note: splice-attributable: "…included" / "to include benefit-sharing clauses" — head
  restarts the verb, "included to include" ungrammatical duplication → fluency/grammar major
  agreed. Symptom-correct category (zh→en side surfaces as grammar break, en→zh side as semantic
  rewrite; different symptoms, both from the same split mechanism). Non-splice: "Triodia" fine.

## Courier-zh 7->8 [fork_full]
- human_agrees: [ ] yes  [-] no
- human_errors (if no): missed_error ×2 (language mismatch; boundary character duplication)
- human_note: (a) windows are Chinese in a zh→en arm, judge did not flag; (b) boundary duplication
  "协议中包 / 包含" — source has one "包", rendered text has two → accuracy/addition, splice-
  attributable, judge read it as "natural" and reported no error; (c) chain not linked/translated
  in fork for this sample (zh page-kind collapse → chain_eligible=false → boundary masked,
  b7.5.2). Pending IL confirmation of paragraph translation status.

---

## Tally (for the judge-credibility report)

Valid rows (splice-targeted, correct windows): 8 → agree 7 / disagree 1
  disagreement: Courier-en 7->8 [chain_on] — judge severity_off + non-splice error counted as splice
PROTOCOL-INVALID rows: 6 (both 2->3 points, all arms) — window taken from geometric page tail/head
  instead of chain members; excluded from agreement; of these, judge failures on invalid input: 1
  (Courier-zh 2->3 fork_full: language mismatch not flagged)
Judge missed_error on valid rows: 1 row (Courier-zh 7->8 fork_full: language mismatch + "包"
  duplication) — counted in the disagreement above? No: that row is valid-window; recount:

Corrected tally: valid rows 8 → agree 6 / disagree 2
  - Courier-en 7->8 [chain_on]: severity_off, non-splice counted as splice
  - Courier-zh 7->8 [fork_full]: missed_error ×2
Splice-attributable agreement on valid rows: 6/8.

Findings for GAP register:
  G-a  window selection must use chain members, not geometric page tail/head (2 points × 3 arms invalid)
  G-b  judge does not check target-language of windows (2 zh rows)
  G-c  judge conflates non-splice lexical errors with splice errors (7->8 chain_on)
  G-d  boundary character duplication "包/包含" in Courier-zh fork output — new defect, cause TBD
  G-e  "动科学发现" at page head = title-chain proportional redistribution residue, visible in
       display text; design behaviour but reader-visible, note for typesetting/title-chain policy