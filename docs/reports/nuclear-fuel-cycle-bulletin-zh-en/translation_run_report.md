# Nuclear Fuel Cycle Bulletin whole-issue translation run

## Final status

`incomplete`

The single formal whole-issue run stopped on a CLI translation error event and exited with code 1. No formal PDF was produced. The run was not retried, and no product code, prompt, configuration, threshold or HITL decision was changed after the failure.

Unique stopping error:

```text
outcome 9wsBE.runtime_source_refs ref is outside canonical IR: p6#12
```

The CLI emitted this as `translate error`, the progress monitor handled a `translate_error` event, and `babeldoc.main.TranslationEventError` propagated it to the process exit. The completed `chain_translation.report.json` binds chain `9wsBE` to runtime/source refs `p6#12` and `p6#18`, records `canonical_article_mismatch`, and marks the outcome `protected_untranslated`; the later canonical-IR validation rejected `p6#12`.

## Provenance

- Branch: `migration/minimal-v0.6.4`.
- Locked code baseline: `f7d0904ca14b9aae07df9d38117867857add9f10`.
- Formal run HEAD / Commit A: `0c7a0f14aabfdda3b05a36141900f4eb9888cc71` (`chore(nuclear): record whole-issue proxy decisions`).
- Changes from the locked baseline before the formal run: only `reviews/nuclear-fuel-cycle-bulletin-zh.decisions.json` and `docs/reports/nuclear-fuel-cycle-bulletin-zh-en/proxy_strategy_review.md`.
- Input: `examples/input/nuclear-fuel-cycle-bulletin-zh.pdf`.
- Input identity: 36 pages, 16,884,507 bytes, SHA-256 `189bff3bf92e359c74476514b47a6608f7ef1a07bc585ff8ede77a356d7c363d`.
- Input text gate: 35/36 pages with at least 20 extracted characters (97.22%); OCR workaround disabled.
- Direction/config: Chinese to English (`zh -> en`), `minimal.zh-en.toml`, `gpt-4o-mini`, QPS 1, ordinary worker 1, term worker 1, monolingual/no-watermark output.
- Decisions: `reviews/nuclear-fuel-cycle-bulletin-zh.decisions.json`, SHA-256 `0b182763f3f2f8c340fdad8ac064ad6135bf2946c9e35a451a083f57c5be3094`.
- The input SHA-256 was unchanged after the failed formal run.

## Commands and timing

### Review export

```powershell
.\.venv\Scripts\babeldoc.exe `
  --config minimal.zh-en.toml `
  --files examples\input\nuclear-fuel-cycle-bulletin-zh.pdf `
  --output examples\output\nuclear-fuel-cycle-bulletin-zh-en\review-export `
  --working-dir examples\output\nuclear-fuel-cycle-bulletin-zh-en\review-export\work `
  --skip-translation
```

- Executions: exactly one.
- Started: `2026-09-01T11:14:53.4545349+01:00`.
- Ended: `2026-09-01T11:17:42.1462914+01:00`.
- Elapsed: 168.69 seconds.
- Exit code: 0.
- Result: complete review v3; translation was not performed; translation and term-extraction tokens were 0.

### Formal whole-issue run

```powershell
.\.venv\Scripts\babeldoc.exe `
  --config minimal.zh-en.toml `
  --files examples\input\nuclear-fuel-cycle-bulletin-zh.pdf `
  --output examples\output\nuclear-fuel-cycle-bulletin-zh-en\final `
  --working-dir examples\output\nuclear-fuel-cycle-bulletin-zh-en\final\work
```

- Executions: exactly one; no `--pages`, `--max-pages-per-part`, `--ignore-cache`, OCR argument or retry.
- Started: `2026-09-01T11:29:42.2006050+01:00`.
- Ended: `2026-09-01T11:39:41.0678101+01:00`.
- Elapsed: 598.87 seconds.
- Exit code: 1.
- Command transcript: `examples/output/nuclear-fuel-cycle-bulletin-zh-en/final/formal-run.log`. PowerShell recorded the command envelope and timing; the external CLI error diagnostics were emitted to the run console rather than copied into the transcript.
- Last completed JSON sidecar by write time: `examples/output/nuclear-fuel-cycle-bulletin-zh-en/final/work/nuclear-fuel-cycle-bulletin-zh/drop_cap_intent.report.json` at `2026-09-01T11:39:27.7221269+01:00`.
- Direct chain evidence: `examples/output/nuclear-fuel-cycle-bulletin-zh-en/final/work/nuclear-fuel-cycle-bulletin-zh/chain_translation.report.json`.

## Page classification and HITL application

### Page VLM

- Pages: 36.
- Accepted VLM results: 36.
- Fresh VLM calls: 0.
- Cache hits: 36.
- Rejected/fallback: 0/0.
- Final classification source: `vlm` for every page.

### Decisions conservation

- Decisions SHA-256 bound by `hitl_apply.report.json`: `0b182763f3f2f8c340fdad8ac064ad6135bf2946c9e35a451a083f57c5be3094`.
- `passes.page_kinds=true`; `passes.before_translation=true`.
- Page kinds: 36 ruled, 36 applied, 0 skipped; physical pages are exactly `1..36`.
- Terms: 27 ruled, 26 applied, 1 skipped.
  - Skipped term: `耐事故/ 先进技术燃料`.
  - Reason: `absent_from_source` in the formal canonical source representation.
  - Automatic glossary entries retained: 406; human glossary entries applied: 26; frozen glossary total: 432.
- Proxy drop cap: 1 ruled, 1 applied, 0 skipped (`p3#3`, `keep`).

The formal pass discovered eight drop-cap candidates after the manual page-kind decisions were applied. `drop_cap_apply.report.json` therefore records 8 decisions: 1 from the proxy ruling and 7 from the default `keep` policy. This is not full manual-ruling conservation against the formal candidate set and is recorded without changing or rerunning the decisions.

## Model activity available before failure

The error occurred before the CLI's normal post-run token-usage logger and before `minimal_run.report.json`; prompt, completion, total-token and cache-hit-token totals are therefore unavailable. Available call evidence is:

- OpenAI translator invocation counter at shutdown: 237 total calls, including 1 translation-cache hit; 236 calls were uncached.
- Automatic term extraction: 60 tracked LLM request/response records across all 36 pages.
- Translation units: 466 total; 460 direct successes and 6 fallbacks.
- Article-context translation: 11 requests for 11 articles/briefs; 1 from cache; 0 failed.
- Short-unit translation: 27 units admitted, 2 refused, 10 requests.
- Chain translation: 15 translator/joint calls.
- Chain topology adjudication: 0 detected, 0 decision calls, 0 applied.
- Term-enforcement retry budget: 20/20 spent.
- Repair translation: 0; the detector/repair stage was not reached.

Fallback warnings observed before the terminal event included one malformed JSON response, short/empty responses and bounded-layout failures. The translator's aggregate result above is the authoritative completed translation-stage count; no manual override was applied.

## Coverage and chain state

### Coverage

`demo_coverage.report.json` completed successfully before the terminal event:

- Source records: 547.
- Owners: joint 28, ordinary 440, preserve 0, none 79.
- Unowned source records: 0.
- Skipped-source reasons accounting for the 79 `none` owners: below length floor 4, furniture withheld 36, no source script 10, placeholder only 12, vertical text 17, CID encoding 0, bilingual companion visible 0.

### Chain translation

- Detected chains: 20.
- Merged chains: 14, covering 28 members.
- Joint successes: 14.
- Escalated outcomes: 6: one `placeholder_bearing` and five `canonical_article_mismatch`.
- Final outcome states in the completed sidecar: 14 `joint_success`, 1 `failed_with_issue`, 5 `protected_untranslated`.
- Skips: 55 chain-member records.
- Tail alignment: 12 tail-aligned chains and 2 capacity-strategy chains; 1,219 characters moved, none pushed.
- The terminal chain `9wsBE` was one of the `canonical_article_mismatch` protected outcomes before the later canonical-IR assertion failed.

## Term enforcement and typesetting state

`term_enforce.report.json` completed and its conservation equation holds:

- Ruled cases: 464.
- Applied: 318.
- Variant substituted: 30.
- Retried successfully: 5.
- Escalated: 111.
- Conservation: `464 = 318 + 30 + 5 + 111`.

Four bounded typesetting attempts were observed falling back to unbounded layout because their complete targets did not fit: `p2#23`, `p9#4`, `p24#2` and `p27#12`. No detector result exists to classify their final impact because the run stopped first.

## Drop-cap state

- Apply stage: 8 `keep`, 0 `flatten`; 8 merged; sources were 1 ruled and 7 default.
- Render stage status: `failure`.
- Render results: 4 committed and 4 rolled back/reverted.
- Failure reasons: 3 `post_render_coverage_failed`, 1 `reached_past_its_own_box`; all other configured reason counts were 0.
- Intent report: generation 1, 8 active intents, 4 rendered, 0 flatten failures.

These results are pre-terminal sidecar state, not a final validation result.

## Detector, repair, termination and final validator

The run stopped before these stages could produce their required outputs:

- `issues.before.json`: not produced.
- `issues.after.json`: not produced.
- `termination.json`: not produced.
- Repair actions/accepted actions: none; stage not reached.
- Repair rollbacks: none; stage not reached.
- Final PDF validator sidecar: not produced.
- `minimal_run.report.json`: not produced.

Accordingly there is no issues-after set to summarize and no machine-complete status.

## Output

- Expected PDF: `examples/output/nuclear-fuel-cycle-bulletin-zh-en/final/nuclear-fuel-cycle-bulletin-zh.no_watermark.en.mono.pdf`.
- Result: `not produced`.
- Final PDF page count/size/SHA-256: not available.
- `minimal_run.report.json` status: not produced.
- The work directory and all completed sidecars/logs were preserved in `examples/output/nuclear-fuel-cycle-bulletin-zh-en/final/` and remain uncommitted.

## Stop boundary and human review

The plan stopped at the first formal translation error event. There was no code repair, prompt/config/threshold change, decision refresh, sub-file run or second paid formal run. The proxy decisions remain exactly those committed in Commit A.

No final translated PDF was available for review. Final human translation and visual review was not performed by Codex; the task remains incomplete pending a separate recovery plan for the canonical-IR defect.
