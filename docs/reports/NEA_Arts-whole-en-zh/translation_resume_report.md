# NEA Arts whole-issue recovery run

## Result

Final status: `failed`.

The one permitted `final-r2` run completed with exit code 0 and passed every machine-side core gate. It produced an openable 24-page PDF, applied all 24 page-kind decisions, conserved all 37 ruled terms at the HITL application boundary, applied and rendered the single ruled drop cap, conserved all 17 chains / 34 members, and left no unowned source in the coverage report.

The run failed the required visual gate. The cover contains a damaged composite title (`工作` over the source `WORKING`, with `MIND` and `SPIRIT` left in English), and page 3 contains a severely overprinted article title (`O选项为HEALING` over the source decorative title). These are structural visual defects, so the plan forbids treating the run as passed. No threshold, verdict, layout rule, or code was changed after the run, and the whole issue was not rerun.

## Locked identity and commits

- Branch: `migration/minimal-v0.6.4`
- Locked baseline: `5518b33aa218b6c99ccbc4797f4f31bdc7364862`
- Commit A: `470199930ee5e75511ab36e555a47c929a95cb83` — `fix(dropcap): keep HITL identity stable across article regrouping`
- Commit B: `3e222988175f5e525eb0e65cb0dad099385fa307` — `chore(nea): refresh source-bound drop-cap decision`
- Commit C / execution HEAD: `ba22870bfe7ebb8e45b014683e052a40e10e1cd9` — `fix(cli): fail when translation emits an error`

## Input, decisions, and output identities

| Artifact | Path | SHA-256 | Other identity |
| --- | --- | --- | --- |
| Input PDF | `examples/input/NEA_Arts-whole-en.pdf` | `91c8dacf4096d86fbccc964cbcd624ccdd499bb49d02bd0864f5e76fe3da67f9` | 24 pages |
| HITL decisions | `reviews/NEA_Arts-whole-en.decisions.json` | `2880c2d63b492f10739bc64f5759b84374ecafebfd5dc33fb29194fa52406568` | format v3; 24 page kinds, 37 terms, 1 drop cap |
| Final candidate PDF | `examples/output/NEA_Arts-whole-en-zh/final-r2/NEA_Arts-whole-en.no_watermark.zh.mono.pdf` | `46c0ada68f60e1f89b8cbf2322bad0b3f694f5230ae774b9670d375acd5c0d9e` | 24 pages; 5,671,730 bytes |

The output is retained as failed-run evidence and is not represented as an accepted release artifact.

## Drop-cap identity repair

The v1 candidate payload contained the source-stable fields plus `article_id` and `config_version=1`. The v2 payload contains only:

1. `source_ref`
2. `source_char`
3. `source_text_fingerprint`
4. `source_style_hash`
5. `visual_initial_ref`
6. `binding_proof`
7. `config_version=2`

`article_id` remains in the intent and audit report but no longer participates in the HITL identity fingerprint. The review-export and first formal sidecars agreed on every source-stable field for `p16#5`, while their article topology differed:

| Evidence | Article ID | Old v1 candidate ID |
| --- | --- | --- |
| review-export | `article-c9d64bf60b6cf60051630817aa7365c929f3aa0934c849c9011b67206943760f` | `dropcap-7b3f05958a514bc8334917494701c897ad1e8581c62c8c6c3be1f0fec6ef39e7` |
| first formal run | `article-3c30ff53d4209c4af709d137cfcfcd05cd822963ad5c9c9866b8149099a62634` | `dropcap-6c31fc8b724cc583d2cbb8318e56a799d5298c426f8fb8ec33298bece007adcc` |

The migrated v2 candidate ID is `dropcap-c0620078275e4623fa31077fcb08a89b1961f1896ea51c81266d1f73267fa266`. The `final-r2` intent retained the formal article ID `article-3c30ff53d4209c4af709d137cfcfcd05cd822963ad5c9c9866b8149099a62634` and matched the migrated decision successfully.

## Focused tests

Only the focused node IDs required by the plan were run; full pytest was not run.

| Commit | Node ID | Result |
| --- | --- | --- |
| A | `tests/minimal/test_drop_cap_keep_flatten.py::test_bound_decision_survives_article_regrouping` | passed |
| A | `tests/minimal/test_drop_cap_keep_flatten.py::test_bound_decision_rejects_source_or_config_drift` | passed |
| C | `tests/minimal/test_cli_error_status.py::test_error_event_fails_cli` | passed |

The Commit A invocation ended with `2 passed, 1 warning`; the Commit C invocation ended with `1 passed, 1 warning`. The warnings were pytest cache-write warnings and did not affect the assertions.

## Unique formal run

Command:

```powershell
.\.venv\Scripts\babeldoc.exe --config minimal.en-zh.toml --files examples\input\NEA_Arts-whole-en.pdf --output examples\output\NEA_Arts-whole-en-zh\final-r2 --working-dir examples\output\NEA_Arts-whole-en-zh\final-r2\work
```

- Started: `2026-09-01T09:56:57.8641074+01:00`
- Ended: `2026-09-01T10:03:42.3703827+01:00`
- Wall time: 404.506 seconds
- BabelDOC translate duration: 397.809 seconds
- Exit code: 0
- Process status: completed
- Acceptance status: failed at the subsequent visual gate
- Transcript: `examples/output/NEA_Arts-whole-en-zh/final-r2/NEA_Arts-whole-en-zh.log`

This was the only `final-r2` execution. It used no page subset, skip-translation, ignore-cache, parse-only, or split argument. No review export, p16 subset, or second formal run was performed.

## Machine acceptance

### Page and element classification

- Page VLM: 24/24 accepted, 24/24 from cache, zero fallback, zero new attempts.
- Effective page kinds: 15 `article_opener`, 6 `article_body`, 1 `front_cover`, 1 `editorial`, and 1 `photo_spread`.
- Element classification: 242 paragraphs total; 193 classified, 49 excluded, and 22 relabelled.
- Final roles: 149 body, 22 caption, 17 other display, 5 pull quote, and 49 excluded.
- Actions: 171 preserve, 22 relabel, and 49 exclude.

### HITL and drop cap

- `hitl_apply.report.json` binds decisions SHA-256 `2880c2d63b492f10739bc64f5759b84374ecafebfd5dc33fb29194fa52406568`.
- Page kinds: 24/24 applied.
- Terms at the HITL application boundary: `ruled=37`, `applied=37`, `skipped=0`.
- Drop caps: `p16#5` 1/1 applied; both page-kind and before-translation passes completed.
- Drop-cap apply: one ruled `keep`, one merge, and one synthesized separator removed.
- Drop-cap render: `status=success`, one committed, zero failed, zero reverted, and zero render rollback.

Term enforcement later evaluated 125 occurrences: 92 applied, 11 variant-substituted, 12 retried successfully, and 10 escalated; its conservation equation holds. The ten escalations are retained evidence and account for part of the instruction-compliance residue rather than being hidden by a threshold change.

### Chain, coverage, and repair

- Chain translation: 17 chains, 34 unique members, 17 translator calls, 17 `joint_success` outcomes, and zero escalation/fallback.
- Every member occurred in exactly one chain and had exactly one verified `allocated` destination; no slot was released or left dangling.
- Backfill allocation, chain claim exclusion, single-request behavior, and target conservation all hold.
- Demo coverage: `status=complete`, 259 sources, owner totals 185 ordinary / 34 joint / 5 preserve / 35 none, and `unowned_sources=[]`.
- Fixed assets: 421 before and after, with no add/remove/digest/bbox/page-size drift.
- Issues before and after: 31 in both snapshots — 3 low fragment clusters, 14 high instruction-compliance findings, and 14 medium text/figure-overlap findings; all other detector kinds are zero.
- Repair: one iteration, three `no_op` decisions, no accepted action, no refusal, no affected element, no translator request, no rollback, termination `converged_all_treated`.

### Call, cache, fallback, and token accounting

| Stage | Recorded accounting |
| --- | --- |
| Ordinary translation | 121 pipeline requests; 219 translated records; 226 attempt trackers; 7 `fallback_to_translate` trackers |
| Chain translation | 17 requests/calls; 0 fallback; 0 escalation |
| Article context | 5 requests; 0 cache hits; 0 failures |
| Repair | 0 translator requests |
| Term extraction | 31 tracked extraction records; frozen glossary contains 231 entries |
| Translator aggregate | 143 total requests across ordinary/chain/article-context counters; 31 translator cache hits |

The runtime sidecars do not emit prompt, completion, or total-token usage. Token counts are therefore recorded as unavailable rather than inferred. No API key value, length, or fragment is present in this report.

## Visual acceptance

The final PDF was rendered to two 12-page contact sheets and inspected as a 24-page whole. The issue pages 1, 2, 3, 6, 7, 8, 9, 12, 13, 17, 19, and 24 were inspected at page scale, and p16 was rendered at 3× for the drop-cap check.

- Whole issue: no blank page, out-of-page content, gross page clipping, or broken page boundary was observed. Ordinary body pages are generally readable.
- p2 TOC: hierarchy and page-number columns remain legible and aligned. Several ruled display terms render as semantic variants or without the ruled quotation marks; these are listed below.
- p16 `p16#5`: the target initial `美` is present in teal, aligned to the first two text lines, followed by the complete first sentence beginning `美国国家艺术基金会…`; no missing initial, boundary escape, collision, or damaged wrap was observed. This repair objective passed.
- Cover: page boundary and cover image are intact, but the composite display title is structurally damaged and contains visible English residue. This is a failure.
- p3 opener: body text and photograph are intact, but the main title is severely overprinted and partially untranslated. This is a failure.
- Back cover: image, caption, footer rule, address, and social marks remain within the page and readable.

### Final issue dispositions

Each row uniquely identifies one entry in `issues.after.json`. The disposition vocabulary is the one required by the plan.

| # | Issue identity | Disposition | Visual / semantic finding |
| ---: | --- | --- | --- |
| 1 | `fragment_cluster` p2 `p2#37–p2#41` | `accepted` | Five short contributor names form the intended narrow staff column and remain readable. |
| 2 | `fragment_cluster` p12 `p12#5–p12#7` | `accepted` | Three caption lines under the photograph are readable without collision or clipping. |
| 3 | `fragment_cluster` p13 `p13#11–p13#15` | `accepted` | Five short lines form an intentionally narrow photo-caption stack; no structural damage is visible. |
| 4 | `instruction_compliance` p1 `The Healing Power of the Arts` | `failed` | The ruled `“艺术的疗愈力量”` is absent; the cover shows `艺术的治愈力量`, alongside the failed composite title. |
| 5 | `instruction_compliance` p2 `A Public Health and Art Initiative to Help Prevent Suicide` | `known demo limitation` | The TOC renders the fluent reordered variant `一项公共卫生与艺术倡议，助力预防自杀`, not the exact ruled string. |
| 6 | `instruction_compliance` p2 `Advancing Recovery` | `known demo limitation` | `推进复原` is readable but omits the ruled quotation marks. |
| 7 | `instruction_compliance` p2 `Ask the Question` | `known demo limitation` | `问出那个问题` is readable but omits the ruled quotation marks. |
| 8 | `instruction_compliance` p2 `Bridging the Urban-Rural Divide through Theater` | `known demo limitation` | `以戏剧弥合城乡鸿沟` is readable but omits the ruled quotation marks. |
| 9 | `instruction_compliance` p2 `Community Connections` | `known demo limitation` | The TOC uses `社区连接项目`, not the ruled `“社区联结”项目`. |
| 10 | `instruction_compliance` p2 `Music as Medicine` | `known demo limitation` | `音乐即良药` is readable but omits the ruled quotation marks. |
| 11 | `instruction_compliance` p2 `Only Connect` | `known demo limitation` | `唯有联结` is readable but omits the ruled quotation marks. |
| 12 | `instruction_compliance` p2 `The Arts and Culture in Disaster Relief` | `known demo limitation` | `灾害救援中的艺术与文化` is readable but omits the ruled quotation marks. |
| 13 | `instruction_compliance` p2 `The Power of Music in a Healthcare Setting` | `known demo limitation` | `医疗环境中的音乐力量` is readable but omits the ruled quotation marks. |
| 14 | `instruction_compliance` p6 `clinic-to-community continuum` | `known demo limitation` | The body uses `诊所与社区的连续性中`, a semantic variant of the ruled `临床到社区连续服务体系`. |
| 15 | `instruction_compliance` p7 `The Arts and Culture in Disaster Relief` | `known demo limitation` | The opener title is readable as `灾害救援中的艺术与文化` but omits the ruled quotation marks. |
| 16 | `instruction_compliance` p9 `Creative Forces` | `known demo limitation` | The body uses unquoted `创意力量计划`; the exact ruled `“创意力量”计划` is absent on the page. |
| 17 | `instruction_compliance` p19 `Shakespeare Festival St. Louis` | `known demo limitation` | The body uses `圣路易斯莎士比亚节`, not the ruled `圣路易斯莎士比亚戏剧节`. |
| 18 | `text_figure_overlap` p1 `p1#0` | `failed` | Translated `工作` is overprinted on the source `WORKING`, producing visibly garbled lettering. |
| 19 | `text_figure_overlap` p1 `p1#1` | `accepted` | The translated `和` remains legible; the detector is reacting to the cover background XObject. |
| 20 | `text_figure_overlap` p1 `p1#2` | `failed` | `MIND` remains visibly untranslated in the composite title. |
| 21 | `text_figure_overlap` p1 `p1#3` | `accepted` | The translated `在` remains legible; no obscuring collision is visible. |
| 22 | `text_figure_overlap` p1 `p1#4` | `failed` | `SPIRIT` remains visibly untranslated in the composite title. |
| 23 | `text_figure_overlap` p1 `p1#6` | `accepted` | The Chinese cover subtitle is readable over the background image; its terminology failure is separately recorded in row 4. |
| 24 | `text_figure_overlap` p3 `p3#6` | `failed` | A large source `O` remains behind the translated opener title and contributes to severe overprinting. |
| 25 | `text_figure_overlap` p3 `p3#7` | `failed` | The visible title reads `选项为HEALING` over source lettering, leaving English residue and damaged hierarchy. |
| 26 | `text_figure_overlap` p7 `p7#0` | `accepted` | `恢复` is readable in the intended staggered opener composition; the image XObject does not obscure it. |
| 27 | `text_figure_overlap` p7 `p7#1` | `accepted` | `推进` is readable in the intended staggered opener composition; the image XObject does not obscure it. |
| 28 | `text_figure_overlap` p8 `p8#7` | `accepted` | The small ornament-path intersection does not obscure the caption or cause clipping. |
| 29 | `text_figure_overlap` p17 `p17#9` | `accepted` | The tiny ornament-path intersection is visually harmless and body text remains readable. |
| 30 | `text_figure_overlap` p19 `p19#6` | `known demo limitation` | The decorative source `O / ONLY CONNECT` composite is retained while a Chinese subtitle is supplied below; it is readable but not a fully localized title. |
| 31 | `text_figure_overlap` p24 `p24#1` | `accepted` | The social-mark ornament intersection does not impair the footer text, icons, or page boundary. |

Disposition totals: 11 `accepted`, 14 `known demo limitation`, and 6 `failed`.

## Stop point

The direct blocker is the structural visual damage on the cover and page 3 opener. Work stopped after the single visual acceptance round. The following were intentionally not executed: layout-rule changes, detector-threshold changes, HITL verdict changes, repair-policy changes, a new review export, a p16 subset, or a second whole-issue translation run.
