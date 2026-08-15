# Evaluation metrics

Sample: `FD-en-v2.pdf`

| run | path | MBR linkable | MBR all | inherited open | conserved | LTCR | legacy share | Overlap delta | Alignment delta | image IoU | page delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| upstream | pdf_extraction | 0.6250 | 0.6250 | 0 | yes | - | - | -0.0587 | 0.0030 | 1.0000 | 0 |
| fork_full_il | intermediate_language | 0.2857 | 0.2500 | 0 | yes | 0.0833 | 0.3750 | 0.0006 | 0.0000 | 1.0000 | 0 |
| fork_full_pdf | pdf_extraction | 0.6250 | 0.6250 | 0 | yes | - | - | -0.0596 | 0.0015 | 1.0000 | 0 |

- `upstream` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
- `fork_full_pdf` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
