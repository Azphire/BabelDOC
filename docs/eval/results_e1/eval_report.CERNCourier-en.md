# Evaluation metrics

Sample: `CERNCourier-en.pdf`

| run | path | MBR linkable | MBR all | inherited open | conserved | LTCR | legacy share | Overlap delta | Alignment delta | image IoU | page delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| upstream | pdf_extraction | 0.6667 | 0.6667 | 0 | yes | - | - | -0.0469 | -0.0000 | 0.9997 | 0 |
| fork_full_il | intermediate_language | 0.6667 | 0.6667 | 0 | yes | 0.8182 | 0.9500 | 0.0001 | 0.0000 | 1.0000 | 0 |
| fork_full_pdf | pdf_extraction | 0.6667 | 0.6667 | 0 | yes | - | - | -0.0570 | -0.0000 | 0.9997 | 0 |

- `upstream` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
- `fork_full_pdf` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
