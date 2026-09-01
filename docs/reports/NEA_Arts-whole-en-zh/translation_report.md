# NEA Arts whole-issue translation run report

## Final status

**Run incomplete; whole-issue acceptance did not pass.** The single formal command stopped before translation because the pipeline rejected the bound drop-cap decision for `p16#5` as stale. No final PDF was produced. In accordance with the locked run plan, the decisions file was not edited and the formal command was not run again.

The CLI process reported exit code 0 despite logging a translation error. This report therefore treats the missing final PDF, missing `minimal_run.report.json`, and explicit error event as authoritative completion failures rather than treating the process exit code as success.

## Run identity

- Code/run HEAD before the task commits: `5b30d60a377bdd15650e33481b5d9eab53e52d93`
- Proxy-decision commit: `97124590d9da7a648d84de7662ed31afd05a62cc`
- Input: `examples/input/NEA_Arts-whole-en.pdf`
- Input SHA-256: `91c8dacf4096d86fbccc964cbcd624ccdd499bb49d02bd0864f5e76fe3da67f9`
- Input size/pages: 5,294,257 bytes / 24 pages
- Extractable-text ratio: 24/24 pages (100%); automatic OCR was not enabled.
- Direction: English to Chinese (`en` to `zh`)
- Configuration: `minimal.en-zh.toml`
- Translation/page-VLM model: `gpt-4o-mini`
- Page VLM profile: enabled, source `vlm`, 150 DPI, one retry maximum
- Translation profile: QPS 1, ordinary worker pool 1, term worker pool 1, monolingual output, no watermark
- Decisions: `reviews/NEA_Arts-whole-en.decisions.json`
- Decisions SHA-256: `1e90bdb24d504b8e9367fc1f63a75894060001e88dffa9a43335edc82023574d`

No API key value, length, or fragment was recorded.

## Commands and timing

Review export, the only `--skip-translation` whole-issue traversal:

```powershell
.\.venv\Scripts\babeldoc.exe --config minimal.en-zh.toml --files examples\input\NEA_Arts-whole-en.pdf --output examples\output\NEA_Arts-whole-en-zh\review-export --working-dir examples\output\NEA_Arts-whole-en-zh\review-export\work --skip-translation
```

- Process exit code: 0
- BabelDOC elapsed time: 88.88 seconds
- Result: review export completed; `translation_performed=false`; translator, chain-translation, and repair-translation requests were all 0.

Formal run, executed exactly once:

```powershell
.\.venv\Scripts\babeldoc.exe --config minimal.en-zh.toml --files examples\input\NEA_Arts-whole-en.pdf --output examples\output\NEA_Arts-whole-en-zh\final --working-dir examples\output\NEA_Arts-whole-en-zh\final\work
```

- Transcript interval: 2026-09-01 09:16:36 to 09:22:11 Europe/London, approximately 335 seconds wall time.
- Process exit code: 0, but logical pipeline status: failed/incomplete.
- Error: `drop-cap decisions rejected: p16#5: candidate or source/config fingerprint is stale`.
- Progress stopped at 52%; the final PDF save stage was not reached.

Neither command used `--pages`, `--max-pages-per-part`, `--ignore-cache`, or `--only-parse-generate-pdf`.

## Review-export gate and VLM reuse

The review gate passed before any decisions were authored:

- `minimal_run.report.json`: `status=complete`, `completed=true`, `translation_performed=false`.
- Page classifier: 24 rows, 24 VLM accepted, 0 cache hits, 0 rejections, 0 deterministic fallbacks.
- Review schema: format 3, correct sample, 24 physical page rows, 0 terms as required by `--skip-translation`, and 1 drop-cap candidate.
- Element classifier: 24 pages, 242 paragraphs, 193 classified, 49 excluded, and 22 relabelled; declared role vocabulary exactly matched the six configured roles.
- Offline translator counters: ordinary 0, chain 0, repair 0.

The formal run reused every page-classification result:

- Page classifier: 24 rows, 24 VLM accepted records, 24 cache hits, 0 fresh VLM calls, and 0 fallbacks.
- Element classifier: 24 pages, 242 paragraphs, 193 classified, 49 excluded, and 22 relabelled.
- Observed final element roles before termination: body, caption, other_display, and pull_quote; all are members of the declared six-role vocabulary.

## HITL application

The decisions file contains 24 page kinds, 37 exact source terms, and 1 fully bound drop-cap ruling.

| HITL class | Ruled | Applied | Skipped | Result |
| --- | ---: | ---: | ---: | --- |
| Page kind | 24 | 24 | 0 | Applied successfully; `passes.page_kinds=true`. All downstream page kinds were human decisions at confidence 1.0. |
| Terms | 37 | 0 | Not available | Not reached; `applied.terms=null` and no terms-conservation record was emitted. |
| Drop cap | 1 | 0 | Not available | Rejected before application; `applied.drop_caps=[]`. |

`hitl_apply.report.json` binds the expected decisions SHA-256. Its pass state is `page_kinds=true`, `before_translation=false`; therefore the required two-pass HITL completion condition is false.

## Automatic terms and token/call accounting

Automatic term extraction ran before the failure:

- Term-extraction worker count: 1.
- Tracking output records: 31.
- Generated automatic glossary rows: 220.
- Process token counters at failure: 27,288 total and 20,647 prompt tokens. The 6,641-token difference is the implied completion count.
- Human term override/freeze: not reached, so none of the 37 ruled terms can be claimed as applied.
- Ordinary paragraph translation, chain translation, and repair translation: not reached; no translated PDF text was produced.

## Drop-cap binding failure

The review and formal runs both found the same genuine decorative T on physical page 16 at `p16#5`. The source-stable binding evidence was identical:

- Source reference: equal (`p16#5`).
- Source text fingerprint: equal (`84d0a43cc20671d903fd436e01ad0d57460f966fb086f531c8a03ce975631424`).
- Source style hash: equal (`d642014aaa3670b4a0c8aa58a359d112d5adfb3d45268f5839db59a01233fd32`).
- Binding proof, source/initial geometry, size ratio, and configuration/decision versions: equal.
- Proxy decision: `keep`.

The topology-dependent identifiers did change:

| Evidence | Review export | Formal run |
| --- | --- | --- |
| Article ID | `article-c9d64bf60b6cf60051630817aa7365c929f3aa0934c849c9011b67206943760f` | `article-3c30ff53d4209c4af709d137cfcfcd05cd822963ad5c9c9866b8149099a62634` |
| Candidate ID | `dropcap-7b3f05958a514bc8334917494701c897ad1e8581c62c8c6c3be1f0fec6ef39e7` | `dropcap-6c31fc8b724cc583d2cbb8318e56a799d5298c426f8fb8ec33298bece007adcc` |
| Article-map SHA-256 | `f54de213837afb37a1a99e63c803847d18ada45e902adadafa9be9599988734d` | `fc1ea44662cb02f9ef24233979294d0b3da2a95ac3e07eafa1437cbb87023396` |

The implementation includes `article_id` in the candidate fingerprint and requires exact candidate-ID equality when validating a manual decision. The evidence therefore identifies a general two-pass binding defect: full human page-kind application changed article topology while the drop-cap's source-stable identity did not change, causing an otherwise source-identical decision to be rejected. This run records the defect without changing code, configuration, thresholds, or decisions.

## Chain, coverage, detector, repair, and visual status

Pre-translation topology construction completed with 142 boundaries, 17 edges, 10 dropped edges, 17 chains, and 34 chain members. Translation-time chain conservation did not run, so no chain request, fallback, or final member-destination claim is made.

The following required formal artifacts do not exist because the run stopped before translation:

- `minimal_run.report.json`
- `demo_coverage.report.json`
- `article_flow.report.json`
- `drop_cap_apply.report.json`
- `drop_cap_render.report.json`
- `issues.before.json`
- `issues.after.json`
- final monolingual no-watermark PDF

Consequently:

- Coverage owners and `unowned_sources`: not evaluated.
- Untranslated residue: not evaluated.
- Chain conservation/fallback: not evaluated.
- Drop-cap committed/rollback counts: 0 applied; render/rollback not reached.
- Repair decision, accepted actions, termination, and evidence pages: not reached.
- Detector issue dispositions for out-of-page, text collision, figure overlap, and residue: not available.

The complete two-sheet source contact sheet was reviewed during proxy adjudication, with enlarged checks of physical pages 2, 4, 16, and 24 for the composite TOC, continuation boundary, drop cap, and back cover. Final-PDF contact-sheet generation and final visual inspection were not executed because there is no final PDF. No visual acceptance claim is made.

## Output and stopping boundary

Expected output, not produced:

`examples/output/NEA_Arts-whole-en-zh/final/NEA_Arts-whole-en.no_watermark.zh.mono.pdf`

Page count and SHA-256 are therefore unavailable.

The stopping boundary was T3, during the only formal whole-issue run, after page-kind application and automatic term extraction but before the HITL before-translation pass. T4 final integrity checks, issue adjudication, final contact-sheet inspection, residue/coverage/repair acceptance, and output hashing were not executed. The available logs and work sidecars were retained as evidence; no second formal run was attempted.
