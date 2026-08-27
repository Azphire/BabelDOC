# Formal evaluation methodology status (v2)

This sidecar corrects labels without rewriting any tracked historical result.
The byte hashes and per-artifact mappings are in
`docs/eval/methodology_status.v2.json`; those historical files remain useful,
but their values are `legacy_noncomparable` with formal methodology.

| Historical label | Accurate current label | Class | Formal status |
| --- | --- | --- | --- |
| `lopo_v2` | `descriptive_publication_matrix` | descriptive | `formal_lopo`: not ready, not computed, value null |
| `ltcr` | `substring_consistency_proxy` | proxy | `formal_ltcr`: not ready, not computed, value null |
| `M10` | `exploratory_endpoint_window_annotations` | exploratory | `formal_seam_mqm`: not ready, not computed, value null |

The publication matrix did not refit policy, thresholds, or prompts within
each fold and its hand-tuned configuration had held-out contact. The substring
grouping has neither a preidentified frozen term manifest nor source-target
word alignment. The endpoint windows were not frozen as complete adjudicated
member/arm mappings before output, include post-hoc invalid windows, and use a
legacy taxonomy, severities, weights, and prompt rather than the required
three-shot TeX MQM contract. The existing 14/14 human review is retained and is
not described as incomplete.

Formal commands therefore write a valid `not_computed` report and exit 3.
Only a machine-validated evidence manifest may change that status; a proxy
number, free-text proof, missing evidence, zero, NaN, or empty object cannot.
