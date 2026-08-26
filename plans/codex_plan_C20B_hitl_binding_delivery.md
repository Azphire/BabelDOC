# Codex Plan C20B：v2/v3→v4 decisions binding、selected-page projection 与执行点送达

计划版本：2026-08-26 rev.3  
两天编排：C18合入后由WT3先交Commit 1（1–2h）；WT2的Commit 2/3预算=`5–7h总上限减实际seed耗时`（通常3–6h），与C19/C20C并行；累计active time硬上限7h  
推荐执行模型：`gpt-5.6-sol`，reasoning `xhigh`  
网络/API：synthetic PDF/IL与现有legacy review/decisions；禁止真实模型请求。  
目标提交序列：

1. `refactor(hitl): define canonical manual expectation protocol`
2. `feat(hitl): bind decisions to source and review manifests`
3. `feat(hitl): trace manual constraints to execution points`

## 0. 任务

把HITL人工裁决升级为source-bound v4 decisions envelope，并明确区分机器候选draft与人工decisions：

- `<stem>.review.json` 是机器生成候选清单；
- `<stem>.decisions.json` 是人工裁决，也是`hitl-apply`唯一执行输入；
- binder从legacy v2/v3 review+decisions、完整source PDF和canonical semantic pages生成新的v4文件，保留标准文件名；
- full-document binding在targeted `--pages`运行中先验证完整source identity，再只投影selected pages，未选决定记`not_selected`；
- 人工术语、page policy、drop-cap decision必须生成typed expectations并证明到达各自execution point和target state。

C18已提供canonical PageSelectionMap与现有validator所需的physical→output基础映射；同一类型的v2完整字段、Final typeset/PDF和manual compliance由C20C完成，不能新增第二份map。本计划不实现同页多文章；unsupported guard不被人工page kind解除。

本文件上下文自足；执行输入需满足第2节行为。命令由Codex在Linux/WSL Bash worktree执行。

## 1. 权威与当前ABB事实

- 审计基线：`57a12552da7a13523ad5a2e27b45473f24183208`。
- 英文TeX SHA-256：`a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08`。
- TeX 548、555、558、642：人工决策优先，写入typed state；constraints到达execution point与在target paragraph/final PDF中实际遵守要分别验证。

仓库当前已跟踪：

```text
babeldoc.zh-en.toml             SHA-256 0e704cddbf26e1a0da76e55c1a0cbdebbca3b19825f2246a9434e8ec98dd7ea9
reviews/ABB-zh.review.json      format_version 3，机器候选，SHA-256 c68f4c13c0adb98e7da0a7ed308de9bfa67f74f434abb5a1f005659c70d1637e
reviews/ABB-zh.decisions.json   format_version 2，人工裁决，SHA-256 0fe7312bd797ad51269ea574094f5c7c919f87ed6c2ec9ae404883d26315016f
```

最新提交只重生成了machine review，没有改人工decisions，也没有review-manifest/source binding。Binder不得谎称这两个legacy文件可证明来自同一次review cycle；它必须把v3 review当可重建draft，把v2显式人工值当迁移输入，并在binding report分别保存两者hash与`binding_mode=legacy_explicit_rebind`。

ABB v2 decisions内容：

- page kinds：1 `front_cover`，2 `toc`，3 `toc`，4 `section_divider`，5 `editorial`，6 `section_divider`，7 `toc`，8/9 `article_opener`；
- terms：`ABB 评论 -> ABB Review`；
- drop_caps为空。

原始PDF预期hash `e8249e884bea2f35239f708247367105aac029e1b758d1905eda6d5f90802f97`，当前审计workspace缺原文件。因此v4 ABB migration在原件就绪前为`BLOCKED_PENDING_ORIGINAL_PDF`；synthetic binding、mixed v3-review/v2-decisions和legacy loader tests仍必须完成。

## 2. 启动与行为前置

```bash
git status --short --branch
git rev-parse HEAD
mkdir -p .tmp/c20b/migration .tmp/c20b/fixtures
export UV_CACHE_DIR="$PWD/.tmp/c20b-uv-cache"
```

必须通过：

```bash
timeout 90s uv run python spec_checks/spec_check_debug_semantic_invariance.py
timeout 90s uv run python spec_checks/spec_check_physical_page_identity.py
timeout 90s uv run python spec_checks/spec_check_article_ir_contract.py
timeout 90s uv run python spec_checks/spec_check_article_state_checkpoints.py
timeout 90s uv run python spec_checks/spec_check_run_trace.py
```

并确认physical page refs、closed roles、ArticleKnowledgeState四stage和debug-free semantic digests已存在。未合入C20A不阻塞本批；本批不改repair transport。

## 3. 文件角色与v4 envelope

### 3.1 Machine review draft

`<stem>.review.json`由export生成，可重建，不是人工执行输入。v4至少包含：

```text
format_version = 4
sample
binding_summary {source_pdf_sha256, source_page_count, semantic_schema_version}
page_kinds[] candidates
terms[] candidates + occurrence refs
drop_caps[] candidates
candidate_manifest_sha256
```

候选manifest从review内容重算，不能信任文件内自报hash。Canonical projection排除rendered HTML、timestamp、absolute path、human choices。

### 3.2 Human decisions

`<stem>.decisions.json`是独立v4 envelope：

```text
format_version = 4
sample
source_binding
review_manifest_sha256
lineage
page_kinds{}
terms{}
drop_caps{}
decision_refs{}
```

`source_binding`至少：

```text
source_pdf_sha256
source_page_count
page_box_rotation_manifest_sha256
semantic_digest_schema_version
per_physical_page_semantic_sha256{}
parser/layout model identity + digest
semantic config digest
code contract version
```

`lineage`是decisions envelope中被canonical hash覆盖的必填对象，不得只放在可删除的report：

```text
binding_mode = native_v4 | legacy_explicit_rebind
legacy_review {format_version, sha256} | null
legacy_decisions {format_version, sha256} | null
legacy_review_cycle_unverified: bool
rebuilt_review_manifest_sha256
binding_evidence_schema_version
binding_evidence_sha256
```

`binding_evidence_sha256`覆盖source/config hashes、legacy lineage、重建review manifest、逐decision exact/changed-default/missing结果和tool/code schema；binding report保存同一canonical evidence payload及digest，另加输出路径/状态。这样避免对整个report与decisions做循环hash。Loader必须重算并比对该digest；删除、替换或篡改detached report/evidence时不可apply。`legacy_explicit_rebind`永远保留`legacy_review_cycle_unverified=true`，不能在后续serialize中洗成普通native binding。

`semantic config digest`必须从binder与runtime共用的versioned projection函数生成，至少覆盖：source language、parser/layout/OCR/scanned-detection选择、layout/table model identity、paragraph/formula/line-splitting参数、page-classifier/chain/ArticleIR配置及所有会改变source semantic IL的开关。它明确排除credential、translation model/QPS/output paths、debug overlay和selected pages；selected pages由projection单独记录。Binder不得手写另一份字段表。

每个decision有stable ref/fingerprint：page kind绑定physical page+page structural digest；term绑定source term+occurrence refs；drop cap绑定paragraph/source span/geometry fingerprint。

### 3.3 Canonical semantic digest

定义并测试，不留给执行者猜：

- scope按physical page分开hash，完整文档hash是ordered page hashes的Merkle/manifest hash；
- source PDF byte hash和page count单独锚定未选择页；
- semantic entries包含physical page、stable source ref、closed role、normalized source text、reading order、box；
- float finite、round-half-even至`1e-4` PDF point、`-0`归零；
- missing/null使用不同canonical tokens；
- ordering由reading order+stable ref；
- parser/layout model/config/code schema versions进入digest；
- debug overlay/path/timestamp/worker/debug ID不进入；
- 同一source/config的debug on/off、full/subset对应page hash相同。

## 4. Atomic apply与selected-page projection

`hitl-apply`在修改glossary/page/paragraph state前执行：

1. loader固定寻找`<stem>.decisions.json`；
2. format只接受v4用于apply；v2/v3返回`HITL_SCHEMA_REQUIRES_BINDING`；
3.验证source PDF bytes hash、full page count和page boxes/rotation manifest；
4.重算review candidate manifest并比对；
5.对本次selected physical pages重算per-page semantic hash；
6.验证selected decisions refs/fingerprints；
7.构建projection后一次性写typed state。

Apply期间四个bound v4 artifacts是不可变输入：review、decisions、review-manifest、binding-report/evidence。`hitl-apply`虽然profile同时启用export/apply，也不得调用现有`_write_draft()`覆盖bound review；新machine draft要么关闭，要么写到working-dir内不同名字`<stem>.runtime-review.json`。启动时记录四文件hash，run结束逐字节复核并重新验证binding；任何变化整次FAIL。不得靠当前进程已缓存的decisions掩盖磁盘文件被覆盖。

Full decisions用于subset运行的固定语义：

- source identity永远绑定完整PDF；
- 只对selected pages物化page/drop-cap/term occurrence constraints；
- 未选页decision在apply report中为`not_selected`，不是missing/stale；
- 某term在selected与unselected页均出现时，只投影selected occurrences，但expectation保留full occurrence count；
- 每个term occurrence在v4 manifest中记录closed ElementRole、stable source span、`translation_eligibility=eligible|protected_fixed`和versioned rule ID；eligible selected occurrences是mandatory，protected/fixed occurrences显式`not_applicable`并绑定fixed-asset/untouched evidence，任何occurrence不得静默从denominator消失；
- selected page中的decision缺ref或stale导致整次apply失败；不能尽量应用部分；
- `--only-include-translated-page`不改变physical refs。

typed errors至少：

```text
HITL_SCHEMA_REQUIRES_BINDING
HITL_SOURCE_PDF_MISMATCH
HITL_PAGE_MANIFEST_MISMATCH
HITL_SEMANTIC_PAGE_STALE
HITL_REVIEW_MANIFEST_MISMATCH
HITL_DECISION_REF_STALE
HITL_DECISION_AMBIGUOUS
```

失败前glossary、page policy、drop-cap/paragraph、ArticleKnowledgeState和cache key bit-for-bit不变。

## 5. Legacy v2/v3 binder

扩展`tools/hitl_review.py`，保留旧查看用法，并新增确切subcommand：

```bash
uv run python tools/hitl_review.py bind \
  --source ./examples/input/ABB-zh.pdf \
  --config ./babeldoc.zh-en.toml \
  --review ./reviews/ABB-zh.review.json \
  --decisions ./reviews/ABB-zh.decisions.json \
  --output-dir ./.tmp/c20b/migration/ABB-zh-v4
```

输出目录必须不存在或为空，由工具创建mode 0700；输出标准名字：

```text
ABB-zh.review.json
ABB-zh.decisions.json
ABB-zh.review-manifest.json
ABB-zh.binding-report.json
```

不能输出`*.v4.review.json`等loader找不到的suffix。`format_version:4`表达版本。

Binder步骤：

1.只读加载legacy v2或v3 review/decisions；
2.读取完整source并生成canonical review candidates/per-page digests；
   配置解析与production CLI共用同一个loader和semantic projection，binder强制离线/不构造translator，但不得改变parser/OCR/layout语义；
3.不信任legacy review candidate内容；从当前source/config重建v4 review，并把legacy review hash/version只写入lineage；
4.逐项将legacy显式human decision匹配到唯一stable refs；page-kind enum已改义、term occurrence缺失、drop-cap paragraph歧义一律失败；
5.报告exact/ambiguous/missing/changed-default和`legacy_review_cycle_unverified=true`；changed machine default本身不覆盖显式人工值，v4 review manifest指向本次重建候选；
6.只有全部人工decision唯一匹配、source/config hash正确时才写新文件；binding report必须清楚声明这是legacy explicit rebind，不能声称证明了原review cycle；
7.用临时文件+atomic rename；
8.绝不覆盖input或已存在output；
9.输出无credential/absolute user path。

v2/v3仍可显示、diff和bind，不能直接apply。歧义/缺失非零退出且不写可apply decisions。

## 6. ManualConstraintExpectation：delivery与target

Apply成功后从人工decisions生成immutable inventory；期望值只能来自human decision，禁止从model/output反推：

```text
expectation_id
kind = term | page_policy | drop_cap
human_value
source_occurrence_refs[]
selected_occurrence_refs[]
source_binding_sha256
delivery_status/evidence
target_status/evidence
typeset_status = pending
final_pdf_status = pending
```

### 6.1 术语

- review export为每个preidentified term给occurrence-level source refs/spans；
- 每个occurrence同时保存closed role、eligibility与rule ID；eligibility只能由versioned role/policy表决定，模型不能决定；
- normalization version固定：Unicode NFC、语言声明的case policy、空白规范；不做宽松substring；
- delivery：每个eligible selected occurrence均进入对应translation request glossary/context，并记录request digest/occurrence refs；protected/fixed occurrence不进request但必须有`not_applicable`+asset/untouched evidence；
- target：每个eligible occurrence有source→target span mapping，normalized target严格等于人工target或经明确morphology policy允许的形式；protected/fixed occurrence保持source asset，不可用别页正确字符串补偿；
- 人工`ABB Review`不能被模型实际输出改写expectation；
- 只在错误page/paragraph出现不算满足。

### 6.2 Page policy

新增versioned `page_policy_observables.json`，覆盖taxonomy中每个policy字段，而非只写示例：

| Policy field | Execution consumer/evidence | Target observable |
|---|---|---|
| translate | translator routing | selected translatable refs有target/terminal mapping |
| chain_eligible | ChainBuilder | false时无chain；true仍须signals/owner |
| starts_article | provisional owner builder | physical page建立hard start boundary |
| opens_article | ArticleBuilder | true时新owner；false不单独声明open |
| preserve_line_structure | record splitter/translator | record refs/order与target units对应 |
| indent_eligible | indent policy/typesetter input | declared indent token只对eligible body |
| repair_profile | repair state/config | allowed detector/action profile digest匹配 |

每种page kind的policy digest由`configs/page_types.json`重算；consumer记录实际读取digest。某字段无final直接视觉量时，本批target状态仍需执行证据，C20C按versioned表给`final observable`或合法`not_applicable`，不能由模型决定。

人工page kind不允许解除same-page multi-article unsupported guard。

### 6.3 Drop cap

- delivery绑定唯一paragraph/source span/fingerprint；
- target ownership、translated first character与keep/flatten verdict一致；
- typeset/final留pending，由C20C完成；
- stale/ambiguous ref整次apply失败。

## 7. 敏感数据与report

HITL apply/binder sidecars只保存decision/candidate/source/schema digests、bounded refs、statuses和typed reasons。不得保存完整translation prompt或raw provider response；术语/短bounded excerpt可按现有review明文策略保留。与C20A集成后，manual delivery evidence引用request digest，不复制prompt正文。

## 8. 测试

新增两个fast gates并声明`GATE_SET="fast"`。本分支直接逐项运行并把准确文件名交给WT0；只有WT0 integration owner修改统一`run_all.py` registry/meta-test，合入后验证存在、唯一、依赖顺序正确。

### 8.1 `spec_check_hitl_source_binding.py`

使用两个最小多页PDF/IL：

- v4同源full apply成功；
- full decisions投影pages `2-3,8-9`，未选页为not_selected；
- full与subset的selected per-page hashes相同；
- binder/runtime同TOML semantic projection一致；改OCR/scanned-detection/layout/paragraph参数会stale，改debug/output/QPS/credential不会改变semantic digest；
- 改一字、page box/rotation、reading order、parser/config version、candidate manifest分别stale；
- debug on/off不stale；
- v2/v3可读不可apply；
- mixed v3 review/v2 decisions正例只在所有显式人工值唯一重绑定时成功，report保留两个legacy hashes、`legacy_explicit_rebind`和未验证旧review-cycle事实；
- v4 decisions envelope本身包含并hash绑定legacy lineage/binding evidence；report删除、digest替换、lineage洗白或重建review manifest变化均拒绝apply；
- legacy review候选变化不会覆盖human value；enum改义、source occurrence缺失或decision歧义失败且不产出可apply文件；
- binder输出标准review/decisions文件名、原文件不变；
- apply开启export时bound四文件字节不变，runtime draft只写working-dir独立名字；故意覆盖任一文件使run失败；
- ambiguous/missing migration非零且无可apply文件；
- failure前state bit-for-bit不变。

用repo现有`reviews/ABB-zh.*.json`做schema/legacy smoke，不需要原始PDF，不把它们改写。

### 8.2 `spec_check_manual_constraint_delivery.py`

- `ABB 评论 -> ABB Review` expectation来自human target；
- fake model输出其他词时target失败且expectation不变；
- 正确词只在错误page/paragraph失败；
- term occurrence映射缺失/重复失败；
- ABB-like fixture包含protected/fixed occurrence与eligible occurrence：前者必须`not_applicable`+asset evidence，后者必须delivery/target；静默忽略、把protected当mandatory或用别页字符串补偿均失败；
- 每个page policy consumer digest和observable；
- policy被load但consumer未读/未执行失败；
- drop-cap wrong paragraph/stale失败；
- unsupported guard不被人工page kind覆盖；
- typeset/final在本stage明确pending而非伪pass。

## 9. 必跑命令

```bash
# 前置/回归
timeout 90s uv run python spec_checks/spec_check_debug_semantic_invariance.py
timeout 90s uv run python spec_checks/spec_check_physical_page_identity.py
timeout 90s uv run python spec_checks/spec_check_article_ir_contract.py
timeout 90s uv run python spec_checks/spec_check_article_state_checkpoints.py
timeout 90s uv run python spec_checks/spec_check_run_trace.py
timeout 90s uv run python spec_checks/spec_check_b7_3.py
timeout 90s uv run python spec_checks/spec_check_drop_cap_intent.py

# 本批
timeout 90s uv run python spec_checks/spec_check_hitl_source_binding.py
timeout 90s uv run python spec_checks/spec_check_manual_constraint_delivery.py
timeout 90s uv run python spec_checks/spec_check_gate_registration.py
timeout 600s uv run python spec_checks/run_all.py --set fast
```

有原始ABB PDF时执行第5节binder，再用生成目录做parse-only apply；没有时明确blocker，不用归档work input替代。

## 10. 提交与交接

Commit 1（1–2h interface seed）：只定义唯一canonical `ManualConstraintExpectation`、stage/status enum（含`not_exercised`）、evidence refs、serialization/schema tests；同时创建`spec_check_hitl_source_binding.py`并支持`--phase protocol`，覆盖schema、canonical serialization、round-trip、unknown/missing field和唯一type ownership。C18合入后WT3从WT0创建分支，运行`timeout 90s uv run python spec_checks/spec_check_hitl_source_binding.py --phase protocol`；通过后WT0立即合入，C20C与Commit 2只能从这个commit开始。  
Commit 2：WT2保存其旧C20A/C21 branch的commit IDs，clean后从已合入seed的integration commit执行`git switch -c c20b-remainder <seed-integration-commit>`；实现v4 review/decisions envelopes、canonical digests、atomic apply、selected projection、legacy binder和source-binding gate。  
Commit 3：在同一remainder branch实现expectation inventory、term/page/drop-cap delivery/target evidence、policy observables和delivery gate。不得reset/rebase旧branch；integration owner按Commit 2→3顺序cherry-pick。

精确stage，不用`git add -A`：

```bash
git status --short
git diff --check
git add -- <逐项审阅的hitl/config/tool/spec_checks精确pathspec>
git diff --cached --check
git diff --cached --stat
git commit -m "<固定commit主题>"
```

交接：三个commit、format/schema versions、canonical digest说明、standard filenames、binder report、selected projection语义、manual expectation schema、policy observable矩阵、测试退出码、ABB migration状态和原始input blocker。C20C只在Commit 1 canonical类型上追加typeset/final statuses，不保留stub。

## 11. 完成与停止条件

完成：

- review draft与human decisions角色/文件名清晰；
- v2/v3不可直接apply但可无覆盖迁移；
- v4绑定full source、per-page semantics、review manifest和decision refs；
- non-contiguous subset先验证full identity再投影，未选decision为not_selected；
- term/page/drop-cap delivery和target有typed evidence；
- page policy每个字段都有consumer/observable contract；
- debug/full/subset canonical规则稳定；
- 新gates声明为fast、分支内直接运行全绿，且WT0合入后完成canonical注册验证；
- 同页多文章仍unsupported；
- 无API、无raw prompt artifact。

停止：C17/C18前置不成立、source canonical form无法跨debug/subset稳定、legacy decision无法唯一匹配、需要覆盖人工decisions、loader必须改变标准suffix、page policy无法找到真实consumer、原始ABB hash不符、测试联网，或7小时到达仍不能atomic bind/apply。不得跳过binding来赶C22。
