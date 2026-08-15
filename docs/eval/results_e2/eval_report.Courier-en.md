# Evaluation metrics

Sample: `Courier-en.pdf`

| run | path | MBR linkable | MBR all | inherited open | conserved | LTCR | legacy share | Overlap delta | Alignment delta | image IoU | page delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| chain_off_1 | intermediate_language | 0.4000 | 0.5714 | 2 | yes | 0.4821 | 0.7667 | 0.0000 | 0.0000 | 1.0000 | 0 |
| chain_off_2 | intermediate_language | 0.4000 | 0.5714 | 2 | yes | 0.4286 | 0.7000 | 0.0000 | 0.0000 | 1.0000 | 0 |
| chain_on | intermediate_language | 0.4000 | 0.5714 | 2 | yes | 0.4464 | 0.7000 | 0.0000 | 0.0000 | 1.0000 | 0 |
| chain_off_1_pdf | pdf_extraction | 0.2000 | 0.4286 | 2 | yes | - | - | -0.0410 | 0.0033 | 1.0000 | 0 |
| chain_off_2_pdf | pdf_extraction | 0.2000 | 0.4286 | 2 | yes | - | - | -0.0406 | 0.0034 | 1.0000 | 0 |
| chain_on_pdf | pdf_extraction | 0.2000 | 0.4286 | 2 | yes | - | - | -0.0410 | 0.0034 | 1.0000 | 0 |

- `chain_off_1` could not measure:
  - chain_translation.report.json: no chain level of the conservation invariant
- `chain_off_2` could not measure:
  - chain_translation.report.json: no chain level of the conservation invariant
- `chain_off_1_pdf` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
- `chain_off_2_pdf` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
- `chain_on_pdf` could not measure:
  - no working directory: no chain or repair level of the conservation invariant
  - no source and translated checkpoint pair: no LTCR
