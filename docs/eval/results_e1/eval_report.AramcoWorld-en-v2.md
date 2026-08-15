# Evaluation metrics

Sample: `AramcoWorld-en-v2.pdf`

| run | path | MBR linkable | MBR all | inherited open | conserved | LTCR | legacy share | Overlap delta | Alignment delta | image IoU | page delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| upstream | pdf_extraction | 0.2857 | 0.3750 | 1 | yes | - | - | 0.1197 | 0.0005 | 0.9606 | 0 |
| fork_full_il | intermediate_language | 0.0000 | 0.1250 | 1 | yes | 0.7246 | 0.8500 | 0.0000 | 0.0000 | 1.0000 | 0 |
| fork_full_pdf | pdf_extraction | 0.1429 | 0.2500 | 1 | yes | - | - | 0.1157 | 0.0004 | 0.9606 | 0 |

- `upstream` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
- `fork_full_pdf` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
