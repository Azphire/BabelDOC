# Codex Plan C22：ABB 非连续4页的一次付费job与最终验收

计划版本：2026-08-26 rev.3  
两天编排：WT0集成分支最后阶段，预计 3–5 agent-hours；paid job硬超时20分钟  
推荐执行模型：主执行`gpt-5.6-sol`，reasoning `high`；可选只读复核`gpt-5.6-terra`，reasoning `high`  
网络/API：前置全部离线；只允许一次paid CLI job，job内翻译/术语/repair请求数按effective bounded profile执行并统计。  
代码提交：默认无代码改动/无空commit；若任何前置gate失败，返回对应C17–C21分支修复后重新从离线gate开始。

## 0. 任务与当前blocker

用仓库跟踪且hash固定的`babeldoc.zh-en.toml`和source-bound v4 `ABB-zh.decisions.json`，只翻译source pages 2、3、8、9，生成恰好4页target PDF，跑pipeline内/外自动验收并生成2×2 contact sheet供用户核对。

当前审计workspace缺：

```text
examples/input/ABB-zh.pdf
```

因此在原始PDF进入执行worktree前，本计划状态是`BLOCKED_PENDING_ORIGINAL_PDF`。仓库TOML不内嵌API key，当前审计未读取或推断环境secret；第4节exact run-intent若确认credential不可用，另标`BLOCKED_PENDING_CREDENTIAL`。RAR中的failed `work/ABB-zh/input.pdf` hash不同，禁止替代。Machine review为v3、人工decisions为v2，必须由C20B binder验证review-cycle provenance并生成标准文件名的v4副本后apply。

本文件上下文自足，不实现同页多文章。命令供Codex在Linux/WSL Bash集成worktree执行；Windows用户无需手工复制Bash命令。

## 1. 权威与输入hash

```text
Git审计基线: 57a12552da7a13523ad5a2e27b45473f24183208
English TeX SHA-256: a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08
ABB-zh.rar SHA-256: ca2af3fe9de87089b766dd698c9f200ae3afaf668b7d676d74fbac4cec42165b
Original ABB-zh.pdf expected SHA-256: e8249e884bea2f35239f708247367105aac029e1b758d1905eda6d5f90802f97
Failed archive work input SHA-256: e9d0b6c7351421a0dccd06694577e498c10508e05f2ea76c6bae2b4adbd477bc
babeldoc.zh-en.toml SHA-256: 0e704cddbf26e1a0da76e55c1a0cbdebbca3b19825f2246a9434e8ec98dd7ea9
```

英文TeX唯一决定architecture/methodology；旧plan/旧设计冲突处无效。

## 2. Git、目录与不可修改对象

```bash
git status --short --branch
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
```

集成分支必须包含C17、C18、C19、C20A、C20B、C20C、C21所有已审commit。工作树不干净或有未审冲突时停止。

创建全新目录：

```bash
mkdir -p \
  .tmp/c22/preflight \
  .tmp/c22/reviews-v4 \
  .tmp/c22/parse-debug-off \
  .tmp/c22/parse-debug-on \
  .tmp/c22/paid-run \
  .tmp/c22/acceptance
export UV_CACHE_DIR="$PWD/.tmp/c22-uv-cache"
```

不得复用、删除或写入：

```text
examples/output/c16/ABB-zh/
用户原始PDF
babeldoc.zh-en.toml
reviews/ABB-zh.review.json
reviews/ABB-zh.decisions.json
RAR及其失败workdir
```

## 3. 输入/config/credential preflight

```bash
test -f ./examples/input/ABB-zh.pdf
test -f ./babeldoc.zh-en.toml
test -f ./reviews/ABB-zh.review.json
test -f ./reviews/ABB-zh.decisions.json
```

跨平台hash检查，不依赖Windows `certutil`：

```bash
uv run python -c "import hashlib,pathlib; p=pathlib.Path('examples/input/ABB-zh.pdf'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
uv run python -c "import hashlib,pathlib; p=pathlib.Path('babeldoc.zh-en.toml'); assert hashlib.sha256(p.read_bytes()).hexdigest() == '0e704cddbf26e1a0da76e55c1a0cbdebbca3b19825f2246a9434e8ec98dd7ea9'"
```

不等于`e8249e…`时`ABB_SOURCE_HASH_MISMATCH`停止。

验证config并保存redacted effective config：

```bash
timeout 90s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode conservative \
  --validate-config
```

此处只检查TOML/translator基本合法性；使用v4 decisions和paid overrides的最终effective config在第4节binder后生成。Credential从config声明的常规env/provider配置读取；只验证available，不打印值/长度/前后缀。

Asset warmup最多5分钟，不算paid translation job：

```bash
timeout 300s uv run babeldoc --config ./babeldoc.zh-en.toml --warmup
```

失败即停止。

## 4. Legacy v3 review + v2 decisions → v4 binding

当前ABB machine review为`format_version:3`、人工decisions为`format_version:2`，均不能直接hitl-apply。运行C20B固定binder：

```bash
uv run python tools/hitl_review.py bind \
  --source ./examples/input/ABB-zh.pdf \
  --config ./babeldoc.zh-en.toml \
  --review ./reviews/ABB-zh.review.json \
  --decisions ./reviews/ABB-zh.decisions.json \
  --output-dir ./.tmp/c22/reviews-v4
```

输出必须为：

```text
.tmp/c22/reviews-v4/ABB-zh.review.json
.tmp/c22/reviews-v4/ABB-zh.decisions.json
.tmp/c22/reviews-v4/ABB-zh.review-manifest.json
.tmp/c22/reviews-v4/ABB-zh.binding-report.json
```

检查`ABB-zh.decisions.json`为format 4，绑定full PDF hash/page count、page box/rotation manifest、per-physical-page semantic digests、重建v4 review manifest和decision refs。Decisions envelope自身的hashed lineage与binding report/evidence必须同时记录legacy v3 review/v2 decisions hashes、`binding_mode=legacy_explicit_rebind`、`legacy_review_cycle_unverified=true`及相同`binding_evidence_sha256`；删除/替换report或洗白lineage后loader必须拒绝，不能谎称两份旧文件来自同一次review cycle。人工值保持：

```text
1 front_cover
2 toc
3 toc
4 section_divider
5 editorial
6 section_divider
7 toc
8 article_opener
9 article_opener
ABB 评论 -> ABB Review
drop_caps = empty
```

若用户有意更改，应在原人工流程中确认后重新bind，C22不能覆盖。Ambiguous/missing/stale立即停止。

```bash
export C22_REVIEWS_DIR="$PWD/.tmp/c22/reviews-v4"
test -f "$C22_REVIEWS_DIR/ABB-zh.decisions.json"
```

从此刻起四个v4文件是bound只读输入：`ABB-zh.review.json`、`ABB-zh.decisions.json`、`ABB-zh.review-manifest.json`、`ABB-zh.binding-report.json`。写`.tmp/c22/preflight/bound-artifact-hashes.json`记录逐文件SHA；每次parse和paid job后逐字节重算并调用C20B loader复验。`hitl-apply`产生的新machine draft只能在对应working-dir用`ABB-zh.runtime-review.json`等不同名字，任一bound文件变化立即FAIL。

Subset运行先验证full source binding，再投影selected pages；未选decisions必须报告`not_selected`，不能因IL只含4页而被视为stale。

现在用实际v4目录和paid job的精确override生成/验证最终effective config：

```bash
timeout 90s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir "$C22_REVIEWS_DIR" \
  --files ./examples/input/ABB-zh.pdf \
  --pages 2-3,8-9 --only-include-translated-page --debug \
  --working-dir ./.tmp/c22/paid-run/work \
  --output ./.tmp/c22/paid-run/output \
  --validate-config

timeout 90s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir "$C22_REVIEWS_DIR" \
  --files ./examples/input/ABB-zh.pdf \
  --pages 2-3,8-9 --only-include-translated-page --debug \
  --working-dir ./.tmp/c22/paid-run/work \
  --output ./.tmp/c22/paid-run/output \
  --print-effective-config \
  > ./.tmp/c22/preflight/effective-config.redacted.json

timeout 90s uv run python tools/validate_bounded_run_intent.py \
  --effective-config ./.tmp/c22/preflight/effective-config.redacted.json \
  --decisions "$C22_REVIEWS_DIR/ABB-zh.decisions.json" \
  --binding-report "$C22_REVIEWS_DIR/ABB-zh.binding-report.json" \
  --require-external-credentials \
  --report ./.tmp/c22/preflight/run-intent-validation.json
```

机器检查source `zh`、target `en`、input SHA、pages、work/output类别、translator/model、term translator、magazine profile、repair limits、`max_tool_call_attempts`、timeouts和QPS/concurrency；这些字段由C20A扩展后的同源report提供，缺字段不能人工脑补。Credential值只能`<redacted>`/null，base URL无query；但OpenAI enabled时`credential_configured`必须为true，否则`BLOCKED_PENDING_CREDENTIAL`。Binder与runtime调用同一个semantic-config projection；parse-only和paid job除`skip_translation`/debug/selected page scope等明确非source-semantic字段外，OCR/scanned detection/layout/paragraph/formula配置必须一致。任何semantic projection digest差异在外部请求前停止。

## 5. 集成行为gate（离线，总硬预算25分钟）

先确认新gate均注册为fast：

```bash
timeout 90s uv run python spec_checks/spec_check_gate_registration.py
```

运行统一fast set并写机器结果；若`run_all.py`尚无JSON参数，用其现有输出并保存日志：

```bash
timeout 900s uv run python spec_checks/run_all.py --set fast \
  > ./.tmp/c22/preflight/fast-gates.log 2>&1
```

至少确认fast registry包含并通过：

```text
C17: debug_semantic_invariance, debug_overlay_render, geometry_write_guard
C18: physical_page_identity, article_ir_contract, chain_owner_scope,
     article_state_checkpoints, chain_slot_backfill
C19: repair_methodology_contract, repair_action_handlers, repair_transaction
C20A: tool_call_transport, repair_tool_schema
C20B: hitl_source_binding, manual_constraint_delivery
C20C: targeted_page_compliance, manual_constraint_final,
      targeted_pdf_acceptance, pdf_compliance
C21: evaluation_readiness, eval_labels
```

为防registry误配，三个最终高风险gate再直接跑一次：

```bash
timeout 120s uv run python spec_checks/spec_check_hitl_source_binding.py
timeout 120s uv run python spec_checks/spec_check_targeted_page_compliance.py
timeout 120s uv run python spec_checks/spec_check_manual_constraint_final.py
```

任一失败停止。禁止`|| true`、删测试、放宽assertion或先跑API。

上述各command timeout之和只是单项保险；用总调度器的monotonic deadline包住本节，elapsed达到1500秒即终止尚在运行的gate并FAIL，不能依次耗尽所有上限。

## 6. ABB page 3 debug off/on parse-only

两次都使用仓库hash固定的TOML与v4 decisions，唯一差异为C17明确提供的debug override。`--skip-translation`不得构造外部translator；若日志出现外部请求即失败。

### Debug off

```bash
timeout 720s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir "$C22_REVIEWS_DIR" \
  --files ./examples/input/ABB-zh.pdf \
  --pages 3 --only-include-translated-page \
  --skip-translation \
  --no-debug \
  --working-dir ./.tmp/c22/parse-debug-off/work \
  --output ./.tmp/c22/parse-debug-off/output
```

### Debug on

```bash
timeout 720s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir "$C22_REVIEWS_DIR" \
  --files ./examples/input/ABB-zh.pdf \
  --pages 3 --only-include-translated-page \
  --skip-translation \
  --debug \
  --working-dir ./.tmp/c22/parse-debug-on/work \
  --output ./.tmp/c22/parse-debug-on/output
```

两次运行显式使用`validation_scope=parse_only`。必须：exit0、越过ArticleIR/RunTrace source registration、semantic passthrough Typesetting和parse-scope PDF geometry validator；semantic stage digests相同；debug PDF额外overlay；physical page仍3并映射到output0；v4 full binding成功、其余页not_selected；无geometry/slate/TOC suppressed error；外部request count=0。

由于`--skip-translation`，`ABB Review`等manual expectations的delivery/target/typeset/final状态必须为`not_exercised`并带`SKIP_TRANSLATION_PARSE_GATE`，整体结果只能称`parse_gate_pass`，不能称full compliance。Parse-only validator只要求source binding、projection、geometry、owner/source trace和fixed assets；它不得把pending/not_exercised记pass到full status。第7节full job中任何mandatory stage仍pending/not_exercised则最终FAIL。

## 7. 唯一一次paid CLI job

### 7.1 Run intent

只有第3–6节全过才写`.tmp/c22/paid-run/run-intent.json`，包含但不含secret/raw prompt：

```text
git commit and clean status
TeX/source/v4 review/decisions/manifest/effective-config hashes
translator/term/repair model and endpoint identity（URL query removed）
selected physical pages 2,3,8,9
PageSelectionMap expectation 0->2,1->3,2->8,3->9
profile call/retry/time/concurrency bounds
paid_job_attempt 1 of 1
hard timeout 1200s
```

### 7.2 Command

```bash
timeout 1200s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir "$C22_REVIEWS_DIR" \
  --files ./examples/input/ABB-zh.pdf \
  --pages 2-3,8-9 \
  --only-include-translated-page \
  --debug \
  --working-dir ./.tmp/c22/paid-run/work \
  --output ./.tmp/c22/paid-run/output
```

选项是单数`--only-include-translated-page`。禁止ignore-cache、model/provider切换、参数sweep、整本页码或第二次CLI paid job。

一次job会正常产生多次translation/term/repair HTTP calls；统计每类logical call、transport attempt、cache hit/miss/error和model。重试不得超effective bounded profile。若本PDF没有repair issue，structured repair tool-call E2E状态写`not_exercised`，不能伪写pass；C20A fake/integration gate仍是功能证据。

### 7.3 失败语义

- 首个外部请求前deterministic失败：保存证据，返回所属计划修复；修复后重新跑离线gate，paid attempt仍未消费；
- 任何外部请求发出后失败/timeout：保存checkpoint、attribution、residual，本批不自动发第二个paid job；
- provider rate/余额/权限：`BLOCKED_EXTERNAL_PROVIDER`，不换provider/model；
- timeout后确认worker终止，不无限等待。

## 8. 自动验收

```bash
timeout 180s uv run python tools/verify_targeted_pdf_run.py \
  --source ./examples/input/ABB-zh.pdf \
  --source-pages 2,3,8,9 \
  --run-dir ./.tmp/c22/paid-run/work/ABB-zh \
  --output-dir ./.tmp/c22/paid-run/output \
  --reviews-dir "$C22_REVIEWS_DIR" \
  --report ./.tmp/c22/acceptance/automatic.json
```

Mandatory：

### PDF/mapping

- run manifest必须唯一指出不含diagnostic overlay的semantic PDF；所有final compliance在该文件上判断，debug copy只做overlay不变性/视觉检查；
- 恰好4页，mapping `output 0..3 -> source 2,3,8,9`；
- MediaBox/CropBox/rotation/page labels匹配对应source；
- outline/TOC destination只指正确selected output，无suppressed TypeError；
- PDF可open，英文target text可选择且非空；
- semantic/final boxes无NaN/Inf/reversed/未许可越界；
- 日志无`geometry box coordinates must be ordered`、`translate slate error`或swallowed validation exception。

### Article/chain/assets

- processables唯一owner或typed unsupported/unassigned；
- debug/formula/furniture/fixed assets不当BODY；
- pages8/9均`article_opener`且article IDs不同，无跨owner chain/request/allocation/repair；
- 只有2↔3、8↔9可能按physical adjacency判断，3↔8永不相邻；
- chain order/target conservation/terminal RunTrace完整；
- legal slots不侵入fixed assets/other owner，fixed asset fingerprints守恒；
- same-page multi-article suspected页无reflow。

### Repair/HITL

- 每transaction恰一action、immediate detector closure、strict accept或full rollback；
- residual有typed reason；
- `ABB 评论 -> ABB Review` expectation在eligible selected occurrences的delivery/target/typeset/final全pass；
- v4 term occurrence inventory中每个eligible selected occurrence均四stage pass；protected/fixed occurrence只能按versioned rule显式`not_applicable`并有asset/untouched证据，不能静默漏掉或用别页字符串补偿；
- 正确词在别页不抵消；
- pages2/3 `toc`、8/9 `article_opener`的policy consumers/final observables通过；
- drop_caps为空仍记录validated empty human decision，不伪造initial；
- full v4 decisions未选页为not_selected。

### Eval/security

- formal LOPO/LTCR/seam-MQM仍not_computed/value null/正确reasons；
- descriptive/proxy/exploratory值不写formal key；
- validator内置scanner遍历整个`.tmp/c22/paid-run`与acceptance tree；对logs、request/decision sidecars、cache-attribution metadata和reports检查credential、raw prompt、full provider request/response及cache-error原文/译文泄露。Semantic checkpoints/PDF可合法含文档文本，但不得含provider envelope；scanner只输出命中count、文件类别和redacted path摘要，不回显内容，也不把env secret传命令行/日志；
- 普通translator cache-set error、provider error/retry/refusal及repair error日志都必须通过上述scanner；
- source/config/originalreviews/旧output未修改；四个bound v4 artifacts在parse/paid前后逐字节hash一致且binding仍有效。

## 9. Contact sheet与人工核查

```bash
timeout 180s uv run python tools/render_targeted_contact_sheet.py \
  --run-report ./.tmp/c22/acceptance/automatic.json \
  --output ./.tmp/c22/acceptance/ABB-pages-2-3-8-9-contact-sheet.png \
  --dpi 144 --columns 2
```

标注只在页外margin显示physical source page。Codex先做技术视觉review并记录`pass/fail/uncertain`，但它不能替用户给最终验收回执：

| Source page | 必查 |
|---|---|
| 2 | TOC条目/页码/leader/order、英文术语、图形资产 |
| 3 | 双栏TOC reading order、底部两个服务说明块、原geometry错误消失、`ABB Review`绑定位置、无debug label侵入正文 |
| 8 | article opener标题/双栏正文/主图、红色pull quote保真、无裁切/碰撞、独立owner |
| 9 | 独立article opener，无从8错误续接；下半页流程图的图标、箭头、标签与左下参考文献均作为fixed assets保持 |

共同检查：无消失/重复/大块未译/乱码/越界/异常缩小、formula/furniture位移、drop-cap重复。`uncertain`不算pass，保留crop/evidence请用户核对。把target PDF、automatic report与contact sheet交给用户；只有用户对相同artifact hashes明确逐页回复4个pass后，才写`user-visual-verdict.json`，字段含PDF/contact-sheet SHA、physical page verdicts、`reviewer=user`和UTC time。Codex不得自行生成用户pass。

## 10. 最终报告与完成条件

写`.tmp/c22/acceptance/final-report.md`：

```text
FULL_PASS | AWAITING_USER_VISUAL_ACCEPTANCE | CODE_COMPLETE_ACCEPTANCE_BLOCKED | FAIL
git commit/clean status
all authority/input/config/review hashes
exact redacted command
models/provider and bounded retry profile
paid job attempt count/wall time
logical calls/transport attempts/cache counts
fast gate and parse parity results
PageSelectionMap + PDF/ArticleIR/chain/RunTrace/assets/repair/HITL checks
manual page checklist
formal eval statuses
residuals/stop reasons
output PDF/report/contact-sheet paths + hashes
```

`FULL_PASS`要求：

- 原始input/config/v4 decisions有效；
- 离线fast gates总elapsed≤25分钟全过；
- 两次page3 parse exit0且semantic parity；
- 一次paid CLI job≤20分钟完成；
- output恰4页且pipeline/外部validator全过；
- `ABB Review`四stage合规；
- pages8/9独立owner；
- Codex技术视觉check无fail/uncertain，且收到并hash绑定用户四页pass回执；
- formal proxies未冒充；
- 无secret/raw prompt、无用户文件修改。

自动验收和Codex技术视觉检查通过、artifact已交用户但尚无明确用户回执时，状态必须是`AWAITING_USER_VISUAL_ACCEPTANCE`。代码/gates完成但原始PDF或credential/provider不可用时为`CODE_COMPLETE_ACCEPTANCE_BLOCKED`，不声称实际PDF证据。用户任一页fail/uncertain或任何自动/gate失败为`FAIL`。

立即停止：输入/config/decision binding缺失或hash不符；任一gate失败；page3仍geometry/slate/TOC error；debug语义不同；paid job已发请求后失败；需要第二次paid job/整本/sweep/换model；发现必须实现同页多文章；或5小时验收时间盒到达。停止时报告是否发出外部请求和最后成功stage，不创建空commit。
