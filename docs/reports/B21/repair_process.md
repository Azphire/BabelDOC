# B21 FD-zh p5 chain topology repair evidence

## Run identity

- Branch: `migration/minimal-v0.6.4`
- B21 start: `c2d514b251a08c0e4eccefcf0fe51d42d68ad6b9`
- Implementation commit: `0dc8f94fac7f51fee70a52d23a7afd1068ace8b2`
- Input: `examples/input/fd-zh.pdf`
- Configuration: `minimal.zh-en.toml` (Chinese to English, OpenAI
  `gpt-4o-mini`)
- Focused tests: the two planned nodeids passed (`2 passed`). The first
  sandboxed collection attempt could not open the existing SQLite translation
  cache; the identical command then ran with cache access and executed both
  nodeids successfully.
- p5 command:

  ```powershell
  & '.\.venv\Scripts\babeldoc.exe' `
    --config 'minimal.zh-en.toml' `
    --files 'examples\input\fd-zh.pdf' `
    --output 'examples\output\B21\p5' `
    --working-dir 'examples\output\B21\p5\work' `
    --pages '5' `
    --only-include-translated-page
  ```

The repair is a **pre-translation structural detection–decision–repair
round**. It is not an action performed by the post-layout `repair_loop.py`.

## B20 defect evidence

The B20 `chain_report.json` accepted the physical edge `p5#6 -> p5#7` as
`linked=true`, `kind=intra_column`, and `pairing=intra_column`. Its `score` is
`null`: the builder accepted it through deterministic hard gates, not a
numeric score threshold. That accepted chain is the B21 semantic-decision
entry condition.

The B20 `chain_translation.report.json` then rejected the same two-member
chain before translation:

| Field | B20 value |
| --- | --- |
| ordered refs | `p5#6`, `p5#7` |
| chain indices | `0`, `1` |
| ArticleIR reading orders | `[191, 184]` |
| result | `protected_untranslated` |
| fallback | `invalid_chain_topology` |
| detail | `chain members do not follow canonical reading order: [191, 184]` |
| joint translator calls | `0` |

Because the chain was released, B20's ordinary batch translated `p5#7`
separately as `The条毫无二致。`; both `translate_tracking.json` and the B20
PDF contain that mixed-script result.

## B21 detection–decision–repair round

The p5-only run normalizes the selected physical page to runtime page 1.
Consequently the same physical members are `p1#6,p1#7` at runtime, and the
same reading-order inversion is `[53,46]` in the selected-page ArticleIR.

| Stage | Measured evidence | Result |
| --- | --- | --- |
| Detection | `kind=chain_topology_conflict`; `subtype=reading_order_inversion`; physical refs `p5#6,p5#7`; runtime refs `p1#6,p1#7`; chain indices `[0,1]`; reading orders `[53,46]`; `builder_accepted=true` | Eligible topology-only conflict detected once |
| Decision | Fragments: `与典型的经济减速不同,严重 萧条(通常伴随着金融危机)包括大 规模持久性的产出下降。这些产出损 失反映的不仅是就业和投资的持续 下降,还有生产力的持久下降(见图 2)。 而全球金融危机之后的情况与严重萧` and `条毫无二致。`, separated explicitly by `<CHAIN_BOUNDARY>`; merged source: `与典型的经济减速不同,严重 萧条(通常伴随着金融危机)包括大 规模持久性的产出下降。这些产出损 失反映的不仅是就业和投资的持续 下降,还有生产力的持久下降(见图 2)。 而全球金融危机之后的情况与严重萧条毫无二致。`; merged SHA-256 `2d075661cc64d3faf921b541877a8a463d0381fe60bee293367b3e3a1def8c2a` | One decision call returned `confirm_joint_chain`: “The later source fragment directly continues the preceding fragment in grammar and meaning.” |
| Deterministic admission | subtype exact; refs unchanged; indices exactly `0..1`; members unique; runtime pages `[1,1]` continuous; one article owner; one canonical chain owner; both source boxes complete and unchanged; prepared fragments unchanged; merged-source hash equal to the value sent for decision | `accepted=true`, reason `all_structural_guards_passed` |
| Repair and verification | repair action `confirm_joint_chain` applied; original ArticleIR not rewritten; joint translator calls `1`; allocation verified; slot orders `[0,1]`; ranges `[0,388]`, `[388,398]`; fragment lengths `388,10` | `joint_success`; fragments reconstruct all 398 target characters; no target residue or chain-conservation violation |

The LLM decides only semantic continuity. Deterministic code retains the
structural veto and can still reject the model action. The implementation does
not synthesize reading orders or globally reorder ArticleIR; `[53,46]` remains
the selected-page ArticleIR evidence after admission.

## p5 gate

| Check | B20 | B21 p5 |
| --- | --- | --- |
| topology decision calls | not available | `1` |
| target joint calls | `0` | `1` |
| target chain result | `protected_untranslated` | `joint_success` |
| target fragments | none | 388 chars + 10 chars |
| whole-target conservation | not applicable | `true` (398 chars) |
| p5#7 ordinary request | yes | no; p5#6 and p5#7 carry the same single joint prompt/reply hashes |
| `untranslated_residue` | mixed-script target present in output | detector count `0`; neither `The条毫无二致。` nor `条毫无二致。` is present in the B21 PDF |
| target chain violations | `non_joint_success` / zero-call failure | none; `result_state=joint_success`, `translator_call_count=1` |

The p5 command exited 0 and produced a one-page PDF, as required by
`--only-include-translated-page`. Two unrelated low-severity
`fragment_cluster` findings remain; B21 does not attribute or repair them.

At 160 dpi the target crop shows both allocated English fragments. The first
box ends with “a severe” and the second begins with “recession.”, so the
semantic unit is continuous and the former `萧/条` mixed-script break is gone.
There is no new target overlap or out-of-page text. The measured first-fragment
font size is about 4.9 pt at scale 0.5; it remains legible in the rendered crop.

Evidence images use the union of the two recorded source boxes plus 25 pt
padding:

- `fd-p5-source.png`: source physical p5
- `fd-p5-before-b20.png`: B20 translated physical p5
- `fd-p5-after-b21.png`: B21 p5-only output page

## Full fd-zh run

The single planned full run used the same loaded environment and command:

```powershell
& '.\.venv\Scripts\babeldoc.exe' `
  --config 'minimal.zh-en.toml' `
  --files 'examples\input\fd-zh.pdf' `
  --output 'examples\output\B21' `
  --working-dir 'examples\output\B21\work'
```

It exited 0 and produced
`examples/output/B21/fd-zh.no_watermark.en.mono.pdf`. The source and output
both have six pages.

The full-document target chain is `DbWt6`; physical and runtime refs are both
`p5#6,p5#7`. The original ArticleIR inversion `[191,184]` remains recorded.
Topology counts for the target are `detected=1`, `decision_calls=1`,
`confirmed=1`, `admitted=1`, and `applied=1`. The decision was
`confirm_joint_chain` with the same semantic-continuity reason as the p5 gate,
and deterministic admission again returned
`all_structural_guards_passed`.

The chain finished as `joint_success` with `translator_call_count=1` and
`joint_call_count=1`. Its two allocated fragments contain 388 and 10
characters, cover target ranges `[0,388]` and `[388,398]`, use slot order
`[0,1]`, and have `allocation.verified=true`. Both members carry the same
joint prompt and reply hashes in `translate_tracking.json`; `p5#7` therefore
has no independent ordinary translation request. Neither the complete PDF nor
`issues.after.json` contains the former target residue, and the latter has no
issue associated with chain `DbWt6`, `p5#6`, or `p5#7`.

The required visual checks also passed:

- p3 renders `编者的话` as a clear `Editor's Note`, without a relevant
  collision;
- p5 retains the continuous English ending “indistinguishable from a severe
  recession.” across both target boxes, with no target out-of-page text,
  text-text collision, or unreadable shrinkage.

For completeness, the full `issues.after.json` contains 23 findings elsewhere
in the document: 2 `chain_conservation`, 4 `fragment_cluster`, 8
`instruction_compliance`, 2 `out_of_page`, and 7 `text_figure_overlap`.
There are no `untranslated_residue` or `text_text_collision` findings. These
global counts include pre-existing, non-target conditions and are not claimed
as B21 improvements. B21's attributable result is limited to the admitted p5
topology conflict, its one-call joint translation, verified allocation, and
removal of the target mixed-script residue.
