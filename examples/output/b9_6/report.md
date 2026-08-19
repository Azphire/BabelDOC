# B9.6 — the decide prompt and what it selects

One micro batch, one instrument. Batch b9.5 delivered `contain_in_page` and
proved the mechanism end to end on a fourth arm whose decision was scripted; on
the arm where a model chose, the action was never chosen, on either of the two
samples that carried a finding it could act on. This batch reworded the request
and measured what the rewording bought, at four decision points, three rounds
of wording, one sample each.

Nothing here lays out a page. Every figure below is a decision: a request
rendered by the shipped builders, sent once through the run's engine with the
cache bypassed, and read back through the shipped interpreter. The driver is
`scripts/replay_b9_6.py`; each round's frozen request text, replies and
decisions are under `rounds/`.

## 0. Diagnosis, before any rewording

Both of b9.5's missed decisions were replayed rather than approximated. Their
findings are the sets those runs detected, frozen under `inputs/`, and each
request rendered from them is held against the cache key that run recorded.
A request carries the action descriptions as well as the prompt, and this batch
reworded one of each, so the reproduction is rendered through b9.5's own copy of
both -- `inputs/prompt_b9_5/react_repair_decide.md` and
`inputs/repair_actions.b9_5.json`, each checked against what `batch-b9.5`
shipped, or the reproduction would only be a copy of whatever the tree says.
Both keys match:

| point | sample, iteration | cache key b9.5 filed | reproduced |
| --- | --- | --- | --- |
| `cern_p1` | CERNCourier-en, iteration 2 | `f29131bd…` | yes |
| `courier_p1` | Courier-en, iteration 1 | `5d6fb5b8…` | yes |

Round 0 sent those exact requests again. It returned b9.5's decisions: at
`courier_p1` the same `none` with the same sentence behind it, at `cern_p1` the
same `translate_orphan_lines`. The misses are a property of the request, not of
one unlucky sample.

Read against the request text, three things in the wording account for them.

**The conditions and the evidence were not tied together by name.** The
`out_of_page` evidence is fifteen flat fields, and `min_overflow_ratio=0.002` --
the detector's own noise floor -- sits four fields away from `overflow_ratio`,
which is the field the condition actually names. Nothing in the request said
that a condition names a field exactly, so a near-miss field was available to be
read instead of the one that decides. The sharpest evidence is `courier_p1`:
its `out_of_page` finding reports `layout_label='title'` and
`overflow_ratio=0.013762`, both conditions plainly met, and the reply said "the
out_of_page finding does not have a layout_label of title or paragraph_title".
The field was in front of it and was not read.

**The cost framing was one action's cost, written when there was one action.**
"a paragraph rewritten that was already correct costs a correct paragraph" is
what `translate_orphan_lines` risks; `contain_in_page` does not change a
character. In the same breath the request asked for findings "whose evidence
plainly describes the defect that action repairs", which sends the reader back
to the quoted text -- and the quoted text of an out of page heading reads
perfectly well, because what is wrong with it is where it is printed. That
contradicts the request's own opening, which says the choice is not a
re-judgement of the detectors.

**Nothing said how to choose between actions.** The ordering rule the request
carried is an ordering rule *within* one action. Findings are listed grouped by
the detector that made them, so at `cern_p1` the one `out_of_page` finding is
line 17 of a list of 48, between sixteen `fragment_cluster` findings and
thirty-one `untranslated_residue` ones. With no rule for choosing between
actions, the kind that fills the list wins by filling it.

## 1. The rounds

Two rounds of rewording against a ceiling of two, each recorded whole.

| round | prompt sha256 | what changed, and why |
| --- | --- | --- |
| round0 | `cf9cd8e5…` | The prompt as b9.5 sent it. Baseline, not a change. |
| round1 | `3fe00931…` | Three edits, one per diagnosed defect. A section on reading a finding against the conditions: a condition names a field exactly, a resembling name is a different measurement (`overflow_ratio` is not `min_overflow_ratio`), a label is read from the evidence, and geometric evidence is not weaker than textual evidence with the quoted text being identification rather than evidence. The cost sentence generalised from "a paragraph rewritten" to "whatever that action changes". A paragraph on choosing between actions: weigh an action by whether its conditions are met and not by how much of the list its kind occupies, and treat the choice as scheduling, since the loop runs few iterations under per-action ceilings. Beside the prompt, `contain_in_page`'s `description` in `configs/repair_actions.json` was rewritten defect first -- what it puts right, that it moves ink and changes no text, then the mechanism. |
| round2 | `94f39004…` | Aimed at the one point round1 did not move. A procedure: take the actions one at a time in the order listed and sweep the whole finding list for each before choosing, since a kind reported once is one line among many; and a finding is admitted or refused by the fields it carries itself, never by what the findings around it report. A tie-break under the scheduling paragraph: where two actions qualify evenly, take the one fewer of whose findings qualify, because whatever crowds it out now will crowd it out next iteration too. |

The tree carries round2.

## 2. What each round chose

Four decision points. `expected` is derived from the conditions the request
itself states, applied to the evidence the request itself shows -- not written
down here.

| point | what it is | round0 | round1 | round2 |
| --- | --- | --- | --- | --- |
| `cern_p1` | replay of a missed decision; both actions have qualifying findings (containment 1, orphan 3) | `translate_orphan_lines` ×2 | `translate_orphan_lines` ×3 | `translate_orphan_lines` ×3 |
| `courier_p1` | replay of the other missed decision; containment 1, orphan 3 | `none` | **`contain_in_page` `out_of_page:p1:p1#10`** | **`contain_in_page` `out_of_page:p1:p1#10`** |
| `synthetic_contain` | built so exactly one action has a qualifying finding | `none` | **`contain_in_page` `out_of_page:p1:p1#0`** | **`contain_in_page` `out_of_page:p1:p1#0`** |
| `orphan_spectrum` | b8.4's nineteen finding fixture; only the orphan action qualifies | `translate_orphan_lines`, 3 of the 6 eligible | same 3 | same 3 |

Two of the three containment points were recovered and held across both rounds.
The regression face did not move: same action, same three findings, every one of
them inside the set the rule admits.

### The point that did not move

`cern_p1` is the hardest of the four and is still wrong. Round1 named
`untranslated_residue:p3:p3#28`, whose evidence reports `layout_label='plain
text'`; round2 named `untranslated_residue:p2:p2#33`, whose evidence reports
`layout_label='title'`. Both replies claimed the label was `fallback_line`, and
both passed over the `out_of_page` finding entirely. So the residual failure is
not the tie-break -- it is that at 48 findings the reply is generalising from the
list rather than reading fields, and it generalises to the kind that fills it.
Round2's sweep instruction was written for exactly this and did not buy it back.

Round2 is measurably even with round1 on all four points. It is what the tree
carries because it is not worse and its wording is aimed at the failure that
remains; it is not being reported as an improvement, because nothing measured
here improved.

### On what "correct" means at the two replays

At both replayed points the orphan action also has qualifying findings, so
naming the containment finding is a scheduling preference and not the only
defensible answer. The point where containment is the only correct answer is
`synthetic_contain`, and it moved. The replays are reported as what they are:
the two decisions b9.5 missed, one of them now taken.

## 3. Zero regression

`orphan_spectrum` is batch b8.4's selection fixture rebuilt from the rule --
nineteen findings, six of them eligible by the orphan rule, the eligible set
derived from the bound rather than written down. Only the orphan action has
qualifying findings there, so it measures whether the rewording cost the action
that already worked. Across all three rounds the reply is
`translate_orphan_lines` naming `p1#0`, `p1#1`, `p1#2` -- three of the six
eligible, in descending order of the share they carry, every one inside the
eligible set and none outside it. Unchanged from round0, which is the
requirement.

The mechanism side is unchanged by construction: this batch touched
`prompts/react_repair_decide.md` and one `description` string in
`configs/repair_actions.json` and no code at all, which
`spec_checks/spec_check_b9_6.py` asserts as a negative.

## 4. What this leaves open

GAP-25 stays open and is updated with these figures: the default path's
selection rate for `contain_in_page` went from 0 of 2 to 1 of 2 on the replayed
decisions, and from failing to passing on a synthetic point where it is the only
correct answer. What did not change is the shape of the risk -- selection is
sampled, and at a long finding list dominated by one kind it still fails. The
two structural remedies GAP-25 already lists are untouched by this batch and are
what would close it: offer one kind per round so geometric findings do not
compete with residues, or pre-select deterministically for actions whose rule is
decidable and leave the model the rest. Both are controller changes and are out
of scope here.
