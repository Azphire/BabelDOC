# Codex Plan C19：Repair state、完整动作闭集、逐 action 事务与 TeX 615 比较器

计划版本：2026-08-26 rev.3  
两天编排：WT1，在C18与C20B interface seed合入WT0后从该tip新建clean branch；与C20B remainder/C20C并行，预计7–9 agent-hours  
推荐执行模型：`gpt-5.6-sol`，reasoning `xhigh`  
网络/API：只用 deterministic decision stub、fake translator和生成fixture；禁止真实请求。  
目标提交序列：

1. `fix(repair): enforce one-action transactions and strict acceptance`
2. `feat(repair): complete bounded methodology action handlers`

## 0. 任务

完成英文 TeX 604–615 中由确定性 repair层负责的子合同：typed knowledge state、六项closed action vocabulary、action→detector closure、一个transaction只执行一个action、action后立即重检、严格accept/rollback，以及五个修改动作的真实bounded handler。

Structured tool-call transport由C20A实现；本批接收typed `Decision`接口和deterministic stub，完成后不得声称TeX 608已经整体对齐。本文件上下文自足，但行为输入必须满足第2节的C17/C18 gates。命令供Codex在Linux/WSL Bash独立worktree执行。

同页多文章不实现；unsupported页上的article/chain/region actions一律不可用。

## 1. 权威合同与当前偏差

- Git审计基线：`57a12552da7a13523ad5a2e27b45473f24183208`。
- 英文TeX SHA-256：`a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08`。

TeX 604–605：detectors覆盖residue、fragment、overlap、bounds、collision、blank、chain backfill和manual compliance；issues为closed types并带page/article/element/text/geometry evidence；manager只能读取显式state和许可动作。

TeX 607–608：六项选择为：

```text
reprocess_omitted_text
reallocate_continuity_chain
retypeset_article_region
contain_overflowing_heading
resolve_text_collision
no_action
```

Decision只含action、target objects、bounded params；deterministic executor重验article/page/fixed assets/role/conservation。

TeX 614–615：action后重跑适用detectors；缺陷数下降，并且仍存在的同类缺陷至少一项metric改善、无metric恶化，才接受；否则整个round rollback并停止。

当前偏差：

- action config只有translate orphan、contain、collision三项；
- controller可在一个iteration执行多个action后统一detect，一个改善可掩盖另一个恶化；
- comparator允许count不增+任意局部改善；
- 当前正例接受“总数不变但一个overlap area变小”；
- 缺少chain reallocation和article-region retypeset生产handler；
- issue ID/metric matching、action→detector closure未成为versioned contract。

## 2. 启动与行为前置

```bash
git status --short --branch
git rev-parse HEAD
mkdir -p .tmp/c19
export UV_CACHE_DIR="$PWD/.tmp/c19-uv-cache"
```

必须通过：

```bash
timeout 90s uv run python spec_checks/spec_check_debug_semantic_invariance.py
timeout 90s uv run python spec_checks/spec_check_physical_page_identity.py
timeout 90s uv run python spec_checks/spec_check_article_ir_contract.py
timeout 90s uv run python spec_checks/spec_check_chain_owner_scope.py
timeout 90s uv run python spec_checks/spec_check_article_state_checkpoints.py
timeout 90s uv run python spec_checks/spec_check_chain_slot_backfill.py
timeout 90s uv run python spec_checks/spec_check_run_trace.py
```

前置行为：debug不在semantic state；physical page identity稳定；single-owner、closed role、chain order和shared legal slots可查询；unsupported页无slot；RunTrace generation可回滚。任一失败以 `BLOCKED_BY_REPAIR_STATE_PREREQUISITE` 停止，不在本批复制ArticleIR/page resolver。

## 3. RepairKnowledgeState

新增immutable、serializable、versioned state：

```text
schema_version
document_semantic_sha256
physical_page_selection_sha256
article_knowledge_state_sha256
run_trace_generation
issues[]
page_policies{}
article_regions{}
element_roles{}
chain_states{}
legal_slot_digests{}
fixed_asset_inventory_sha256
manual_constraint_refs[]
protected_refs[]
allowed_actions[]
action_detector_closure_version
limits{}
```

要求：

- issue kind为closed enum；
- issue stable identity不含severity metric、当前box坐标、debug ID、path或timestamp，使合法移动后仍可匹配persistent issue；
- evidence携带physical page、article owner、stable element refs、bounded text excerpt、metric vector；
- article region/slot只能引用C18 canonical state，manager不能造box；
- state hash进入decision cache key、transaction record、residual report；
- decision看到的state digest与executor preflight使用的一致，否则`STALE_REPAIR_STATE`；
- unsupported/unassigned page、unknown role/ref、missing fixed-asset snapshot fail closed。

## 4. Action→detector closure

新增versioned配置，例如 `configs/repair_detector_closure.json`。每个action声明：

```text
trigger_issue_kinds
primary_detectors
conservation_detectors
potential_side_effect_kinds
required_state
```

所有修改动作必须重跑：

- 它的primary detector；
- geometry ordering/bounds；
- text conservation/omission；
- collision/text-image overlap；
- owner/reading order；
- fixed assets/untouched content；
- RunTrace terminal/generation；
- manual compliance（若触及受约束ref）。

特定closure至少包括：

| Action | Primary | 必须额外防的副作用 |
|---|---|---|
| reprocess omitted | residue/omission | overflow、collision、term/manual、trace |
| reallocate chain | chain backfill | missing/duplication、bounds、collision、order |
| retypeset region | whitespace/overflow/fragment | all geometry、conservation、other owner |
| contain heading | heading bounds | collision、readability、article region |
| resolve collision | collision | bounds、new collision、order、fixed asset |

config缺action、detector未知、closure为空或漏全局conservation detector时startup失败。为保证`after_all`完整，本批在每个action后重跑注册的完整closed detector suite，action closure只规定primary优先级、必须包含的side-effect checks和evidence scope；它不能省略其他detectors。未来若优化为carry-forward，必须另有机器证明某detector不受touched refs影响，本批不实现。不得把closure输出直接当全局after而让未重跑issue假装resolved。

## 5. 单action transaction

controller改为：

```text
detect full applicable baseline
→ build immutable RepairKnowledgeState
→ choose exactly one typed Decision
→ deterministic preflight
→ snapshot all mutable state + trace generation
→ begin exactly one transactional RunTrace generation
→ execute exactly one handler
→ rerun primary/closure checks, then the complete detector suite immediately
→ compare
→ commit OR rollback full snapshot and stop
```

禁止一个iteration按多个kind循环执行。下一action必须进入下一iteration，从刚commit的全新state/detector result选择。

`TransactionSnapshot`至少覆盖docs semantic IL、ArticleKnowledgeState generation、RunTrace、fixed asset digest、manual expectation statuses、repair records和所有handler side effects。每个action恰好一个RunTrace transaction generation：在任何mutation前开始，所有handler只写当前generation；accept后commit为before+1，reject后恢复原generation/digest。Handler不得自行再创建generation。Rollback后byte/canonical digest等于before，失败action不可留下cache-visible成功状态。

limits同时约束iterations、decisions、actions、candidate issues、touched articles/pages/elements、translation calls、text chars和wall time。触发limit→residual+stop，不部分commit。

## 6. TeX 615 comparator的无歧义解释

Decision必须显式列目标issue IDs。定义：

```text
target_kinds = kinds(before issue_ids selected by Decision)
persistent = stable IDs in before and after
new = stable IDs only in after
resolved = stable IDs only in before
```

`before_all`和`after_all`必须来自相同detector registry/version和完整document scope；任何未重跑的baseline finding仍须出现在after集合，不能因未被观察而算resolved。

接受条件为严格合取：

1. `len(after_all) < len(before_all)`；
2. `new`为空；
3. 对每个 `persistent` 且kind属于`target_kinds`：至少一个declared metric严格改善，所有metrics均不恶化；
4. 对每个 `persistent` 且kind不属于`target_kinds`：所有metrics均不恶化，允许完全不变；
5. applicable detector closure完整运行且所有conservation invariants通过；
6. action只触及preflight许可对象。

这使“同类”精确指本action目标issue的kind，不会要求一个heading action同时改善无关chain issue；无关issue可以保持不变，但不能恶化或新增。若target_kinds为空，只允许`no_action`，不接受mutation。

Metric direction/type/version由issue schema声明，例如area/overflow distance越小越好；不可比较、缺metric、NaN/Inf、duplicate ID、kind变化均拒绝。合法geometry变化不能改变stable issue ID；如detector无法保持identity，先修ID生成，不用模糊文本/IoU猜配。

`no_action`不执行mutation、不进入accept comparator，直接输出residual/stop。

## 7. 六项action handler

### 7.1 reprocess_omitted_text

复用orphan translation path，但：

- 只处理detector证明未进入translation request的semantic source ref；
- owner/role/physical page/manual glossary存在；
- fake tests用CachedOrphanTranslator；生产可调用现有translator但受call/char limit；
- target与相关合法slot写入同一个controller已开启的transactional RunTrace generation；handler不得另建generation；
- manual term不能被模型输出覆盖。

### 7.2 reallocate_continuity_chain

- 读取一次已生成的完整chain target；不重翻；
- owner、ordered members、placeholder、完整target range与C18 state一致；
- 调用shared legal-slot planner和existing typesetter fit；
- fragments按order拼合严格等于完整target normalized contract；
- 无完整target/slot时本次target可`unavailable`+residual，但handler必须在独立正例fixture真实执行并commit。

### 7.3 retypeset_article_region

从existing article flow抽取“对已有target segments重新分配/排版”的pure entry：

- 输入article ID、existing targets、canonical legal slots、bounded fit/spacing tokens；
- planner不能给coordinate；
- 不调用translator；
- 不跨owner/page adjacency/fixed asset/protected role；
- 所有RunTrace记录写入controller已开启的唯一transaction generation，text conservation完整。

### 7.4 contain_overflowing_heading

- 仅closed HEADING+heading-bounds issue；
- 先在legal heading region内平移，再按declared readability minimum有限缩放/换行；
- 不触及BODY/CAPTION/RECORD/FORMULA/FURNITURE；
- 新collision或可读性下限失败rollback。

### 7.5 resolve_text_collision

- 只处理detector证明为translation-introduced、满足配置area/size/ownership的text-text collision；
- source-existing overlap、不同owner、fixed asset、protected drop cap、无法唯一选择较小对象均unavailable；
- 使用existing collision separation和atomic geometry helper；
- 不能造bounds/order/new collision。

### 7.6 no_action

无issue、target、parameters、mutation；输出`NO_PROVABLY_SAFE_ACTION`或更具体stop reason。

## 8. Decision与bounded parameters

C19定义纯typed接口，C20A接transport：

```text
Decision:
  action: Action enum
  issue_ids: tuple[StableIssueId]
  target: typed refs only
  parameters: per-action closed bounded object
  state_sha256
```

无自由文本reason、arbitrary coordinate、replacement text、prompt/code/URL。旧action name只允许显式config migration，runtime不能同时接受同义词或静默fallback。

Deterministic preflight逐项验证action↔issue kind、owner、role、physical page、legal slots、fixed assets、protected/manual refs、limits和state digest。失败时executor零调用、零mutation。

## 9. 测试

新增两个fast gates，均声明`GATE_SET="fast"`。本分支直接逐项运行并把准确文件名交给WT0；只有WT0 integration owner修改统一`run_all.py` registry/meta-test，合入后验证存在、唯一、依赖顺序正确。

### 9.1 `spec_check_repair_methodology_contract.py`

至少覆盖：

A. count下降、target-kind每个persistent均改善、无恶化→commit；  
B. count不变但metric改善→rollback+stop；  
C. count下降但一个target-kind persistent不变→rollback；  
D. count下降但一个target-kind metric恶化→rollback；  
E. count下降、无关kind不变→允许；  
F. count下降、无关kind恶化→rollback；  
G. 新issue出现→rollback；  
H. duplicate/changed-kind/uncomparable/NaN metric→rollback；  
I. 一个iteration返回两个actions→schema/controller拒绝；  
J. action成功后才允许下一iteration，第二action读取新state digest；  
K. detector closure缺配置或漏conservation detector→startup拒绝；  
L. rollback恢复docs/state/trace/assets/manual statuses；  
M. stable issue ID在合法geometry移动后仍匹配。
N. 未被本action触发的无关issue仍由完整after suite发现并计入after_total，不会因closure遗漏形成虚假count下降。

每个fixture标明issue kind、target_kinds和metric direction，避免组合测试逻辑自相矛盾。

### 9.2 `spec_check_repair_action_handlers.py`

五个mutating handler各有独立production-path fixture，必须至少一次：preflight pass→真实mutation→closure detect→strict accept→commit。另为每个handler提供boundary refusal。组合orchestration fixture随后依次在多个iterations执行不同handlers；无关issues保持不变不应阻塞，但任何恶化阻塞。

同时覆盖unsupported page、other owner、protected role、fixed asset、stale state、limit、no_action。

## 10. 必跑回归

```bash
# C17/C18在本批修改后重跑
timeout 90s uv run python spec_checks/spec_check_debug_semantic_invariance.py
timeout 90s uv run python spec_checks/spec_check_geometry_write_guard.py
timeout 90s uv run python spec_checks/spec_check_physical_page_identity.py
timeout 90s uv run python spec_checks/spec_check_article_ir_contract.py
timeout 90s uv run python spec_checks/spec_check_chain_owner_scope.py
timeout 90s uv run python spec_checks/spec_check_article_state_checkpoints.py
timeout 90s uv run python spec_checks/spec_check_chain_slot_backfill.py
timeout 90s uv run python spec_checks/spec_check_run_trace.py

# 本批
timeout 90s uv run python spec_checks/spec_check_repair_methodology_contract.py
timeout 90s uv run python spec_checks/spec_check_repair_action_handlers.py

# 既有repair/compliance
timeout 90s uv run python spec_checks/spec_check_repair_transaction.py
timeout 90s uv run python spec_checks/spec_check_reflow_compliance.py
timeout 90s uv run python spec_checks/spec_check_fixed_asset_guard.py
timeout 90s uv run python spec_checks/spec_check_drop_cap_repair_guard.py
timeout 90s uv run python spec_checks/spec_check_gate_registration.py
timeout 600s uv run python spec_checks/run_all.py --set fast
```

## 11. 两页production orchestration fixture

生成一个2-page、single-owner、两个相邻栏/页、含heading/fixed image/omission/collision/chain overflow的小PDF/IL，走真实high-level repair entry但使用fake translator/typed decision queue：

1. baseline detect多个kind；
2.每iteration只修一个；
3.每个handler的独立正例已先证明可用；
4.组合中无关issues允许不变；
5.故意在某action造new collision时整action rollback并停止；
6. PDF仍可生成、residual含未处理issues/stop reason；
7. 每个accepted action的RunTrace/ArticleKnowledgeState generation恰好+1，rollback后generation/digest不变。

该fixture无publication/page硬编码、无网络，单次<120秒。

## 12. 提交与交接

Commit 1只含knowledge state、detector closure、single-action controller、strict comparator及methodology gate。Commit 2含六项action config/handlers、handler gate和orchestration fixture。

每次精确stage：

```bash
git status --short
git diff --check
git add -- <本commit逐项审阅的babeldoc/config/spec_checks精确pathspec>
git diff --cached --check
git diff --cached --stat
git commit -m "<固定commit主题>"
```

禁止`git add -A`。交接列：两个commit、state/action/detector schema versions、action→closure矩阵、A–N结果、五handler正例与拒绝、组合fixture、全部C17/C18回归、无API证明。C20A只消费typed Decision和state schema，不得重新实现comparator。

## 13. 完成与停止条件

完成：

- 六项action闭集且五个mutating handler有真实正例；
- 一个transaction/iteration恰好一个action，立即重检；
- detector closure完整且startup fail closed；
- TeX 615比较器满足第6节，错误旧正例已改为负例；
- stable issue identity不依赖geometry metric/debug ID；
- rollback恢复全部state/trace/assets/manual status；
- unsupported同页多文章页永不可repair/reflow；
- C17/C18、本批、既有fast gates全绿；
- 未实现/伪称structured tool calling，未发API。

停止：前置state不成立、两个缺失handler只能做空壳/永久unavailable、需要模型生成coordinate、closure不能覆盖side effects、issue identity只能模糊猜、fixed assets/owners必须放宽、测试意外联网，或9小时到达仍无single-action+strict comparator。时间盒到达时优先交付可独立cherry-pick的Commit 1，不用空handler把Commit 2标绿。
