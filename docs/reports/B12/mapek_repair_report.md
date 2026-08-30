# MAPE-K repair evidence

Everything below is counted from what the runs wrote: the detection
sidecars, the decision audit log, and the termination record. A kind
the loop never repaired is written as zero rather than omitted.

## What was detected, nominated, refused and repaired

| defect kind | detected | nominated | refused by admission | repairs accepted |
| --- | ---: | ---: | ---: | ---: |
| `abnormal_blank` | 0 | 0 | 0 | 0 |
| `chain_conservation` | 0 | 0 | 0 | 0 |
| `fixed_asset_drift` | 0 | 0 | 0 | 0 |
| `fragment_cluster` | 1 | 0 | 0 | 0 |
| `instruction_compliance` | 4 | 0 | 0 | 0 |
| `out_of_page` | 0 | 0 | 0 | 0 |
| `text_figure_overlap` | 1 | 1 | 1 | 0 |
| `text_text_collision` | 0 | 0 | 0 | 0 |
| `untranslated_residue` | 17 | 3 | 3 | 0 |

## How each run ended

| sample | findings before | findings after | actions kept | rolled back | stopped because |
| --- | ---: | ---: | ---: | :-: | --- |
| `Courier-en` | 6 | 6 | 0 | no | `all_candidates_refused` |
| `bull-zh` | 17 | 17 | 0 | no | `all_candidates_refused` |

## Accepted repairs, one section each

No repair was accepted on any sample in this batch. The loop
ran, measured, and kept nothing; the per-kind table above says
where its nominations were refused.

