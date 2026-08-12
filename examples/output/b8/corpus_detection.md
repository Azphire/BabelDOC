# Corpus detection census

Written by `spec_checks/spec_check_b8.py`, one dry run per sample with
`magazine_detect` up. These runs perform no translation, so the two
detectors that answer about a translated document are skipped and say
so in their sidecar; what the residue detector finds is asserted
against the frozen translated fixture instead.

| sample | pages scanned | escalation_surfacing | fragment_cluster | text_figure_overlap | untranslated_residue | skipped |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Courier-en | 8 | 0 | 0 | 0 | 0 | escalation_surfacing, untranslated_residue |
| Vogue-en | 3 | 0 | 0 | 0 | 0 | escalation_surfacing, untranslated_residue |
| CERNCourier-en | 4 | 0 | 2 | 0 | 0 | escalation_surfacing, untranslated_residue |
| AramcoWorld-en-v2 | 9 | 0 | 0 | 0 | 0 | escalation_surfacing, untranslated_residue |
| FD-en-v2 | 9 | 0 | 1 | 0 | 0 | escalation_surfacing, untranslated_residue |
| Courier-zh | 8 | 0 | 0 | 0 | 0 | escalation_surfacing, untranslated_residue |

## What the report only detectors found

| sample | detector | page | paragraphs | evidence |
| --- | --- | ---: | --- | --- |
| CERNCourier-en | fragment_cluster | 2 | p2#36, p2#37, p2#38 | members=3 labels=plain text |
| CERNCourier-en | fragment_cluster | 2 | p2#56, p2#57, p2#58 | members=3 labels=plain text |
| FD-en-v2 | fragment_cluster | 5 | p5#15, p5#16, p5#17, p5#18, p5#19, p5#20, p5#21, p5#22, p5#23, p5#24 | members=10 labels=fallback_line |
