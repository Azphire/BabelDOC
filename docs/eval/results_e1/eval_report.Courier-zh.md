# Evaluation metrics

Sample: `Courier-zh.pdf`

| run | path | MBR linkable | MBR all | inherited open | conserved | LTCR | legacy share | Overlap delta | Alignment delta | image IoU | page delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| upstream | pdf_extraction | 0.3333 | 0.2857 | 0 | yes | - | - | 0.0084 | 0.0017 | 1.0000 | 0 |
| fork_full_il | intermediate_language | 0.5000 | 0.5714 | 1 | yes | - | - | -0.0000 | 0.0000 | 1.0000 | 0 |
| fork_full_pdf | pdf_extraction | 0.5000 | 0.5714 | 1 | yes | - | - | 0.0000 | 0.0012 | 1.0000 | 0 |

- `upstream` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
- `fork_full_pdf` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
