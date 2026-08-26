# Codex Plan C18：Physical page identity、closed ArticleIR 与 owner-scoped chain/state/slots

计划版本：2026-08-26 rev.3  
两天编排：WT1，在C17合入后顺序执行，预计 8–10 agent-hours  
推荐执行模型：`gpt-5.6-sol`，reasoning `xhigh`  
网络/API：全部使用 synthetic IL、失败 checkpoint 和 parse-only；不调用翻译/VLM。  
目标提交序列：

1. `refactor(ir): preserve physical page identity and closed roles`
2. `fix(chain): scope continuity to provisional article owners`
3. `feat(ir): checkpoint article state and obstacle-free slots`

## 0. 任务

在单页最多一个 article owner 的既定范围内，完成四项生产合同：

1. `--pages` 过滤后仍使用原始 physical source page identity，不能把列表位置当页号；
2. ArticleIR element role 为闭集，raw parser label只作为映射证据；
3. 先建立 provisional owner，再在同 owner 内建 chain，chain不能反向合并两个文章；
4. 记录 source→pre-translation context→target→allocated→typeset article state，并让 chain/article allocation只使用扣除 fixed obstacles 后的 legal slots；
5. magazine subset始终从全本结构恢复ArticleIR，仅限制translation/output，并在本批建立physical→output page mapping基础。

同页多文章/多章节不实现。疑似页保持 `unsupported_same_page_multi_article`、`by_page` 为 0/1 owner、无 slot、无 reflow。

本文件上下文自足。执行输入必须是通过 C17 行为 gate 的分支；无需阅读 C17 plan，只需验证第 2 节的前置行为。命令供 Codex 在 Linux/WSL Bash 独立 worktree执行。

## 1. 权威与基线

- 审计基线：`57a12552da7a13523ad5a2e27b45473f24183208`。
- 英文 TeX SHA-256：`a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08`。
- ABB 失败归档 SHA-256：`ca2af3fe9de87089b766dd698c9f200ae3afaf668b7d676d74fbac4cec42165b`。
- 原始 ABB PDF 预期 SHA-256：`e8249e884bea2f35239f708247367105aac029e1b758d1905eda6d5f90802f97`；当前审计 workspace 缺该文件，不能用归档 work input替代。

TeX 关键合同：

- 495、507、510：ArticleIR连接源页面、文章、连续链、目标区域与渲染状态；
- 517：page type和element role均为closed vocabulary；
- 527：chain端点属于同一article；
- 569、576、579：article region可跨同文章相邻栏/相邻页，角色政策不同；
- 592：文字、reading order、article attribution、fixed assets守恒，失败rollback。

## 2. 启动与 C17 行为前置

```bash
git status --short --branch
git rev-parse HEAD
mkdir -p .tmp/c18/replay .tmp/c18/subset
export UV_CACHE_DIR="$PWD/.tmp/c18-uv-cache"
```

必须先通过：

```bash
timeout 90s uv run python spec_checks/spec_check_debug_semantic_invariance.py
timeout 90s uv run python spec_checks/spec_check_geometry_write_guard.py
timeout 90s uv run python spec_checks/spec_check_run_trace.py
```

并确认：

- semantic iterator不含 `DEBUG_OVERLAY`；
- physical page metadata可从 IL page读取；
- 非法 geometry不会进入 ArticleIR；
- `--debug/--no-debug` 不改变 semantic state。

任一不成立，以 `BLOCKED_BY_SEMANTIC_INPUT_CONTRACT` 停止。不得在本分支复制另一套 debug filter。

## 3. 当前代码缺口

### 3.1 页号错误

`ILCreater.create_il()` 过滤 `docs.page` 时保留原 `page.page_number`；`ArticleBuilder` 多处用 `enumerate(docs.page)` 重新生成 1..N ID。`article_flow.py` 又用 `docs.page[page_number-1]`。因此：

- `--pages 7-9` 的 canonical IDs可能被写成 p1/p2/p3；
- `--pages 1,3` 的两个列表邻居可能被误判为相邻源页；
- 直接改 ArticleIR页号会让稠密索引消费者越界。

### 3.2 role仍是自由字符串

`ArticleElement.role`/slot role是 `str`，`ArticleBuilder` 写 `paragraph.layout_label or "unclassified"`。`configs/article_flow.json` 的 `eligible_roles` 混合 `body/continuation/paragraph_hybrid/plain text/text`，把semantic role和raw layout label混在一起。

### 3.3 chain先于owner

当前 high-level顺序是 PageClassifier→ChainBuilder→ArticleBuilder；ArticleBuilder可根据chain再合并provisional articles。这样“最终同 owner”无法证明chain建立时端点已经同 owner。

### 3.4 state/slot不完整

已有single-owner ArticleIR、RunTrace、chain single request、typesetter fit和rollback可复用；缺少canonical chain order、阶段state、context references，以及在chain allocation处真正减掉fixed obstacles的共享slot planner。

## 4. Physical page identity

### 4.1 类型

新增不可混淆类型：

```text
PhysicalPageNumber = 1-based source PDF page
SelectedPagePosition = 0-based position in filtered docs.page
OutputPageIndex = 0-based page in produced targeted PDF

PageSelectionMap:
  translation_selected_physical_pages[]
  physical_page_number -> structural_position
  output_index -> physical_page_number
  physical_page_number -> output_index | absent
```

Magazine modes启用ArticleIR/HITL时采用固定合同：完整source PDF先建立全本structural IL、page policies、provisional owners和chains；`--pages`只控制哪些physical pages进入translation与最终output，不在结构恢复前删除未选页。这样subset从文章中段开始仍能读取opener、前页、完整owner和chain evidence。非magazine mode保持既有selection行为。

若未来为性能引入持久structural index，必须与同一source/config/code digest绑定并等价于全本重建；本批不允许用partial ArticleIR冒充full identity。

当前`split_strategy`会在进入`_do_translate_single()`前先切part PDF并重置页号，无法满足本合同。两天范围选择typed fail-closed：只要ArticleIR/HITL magazine开关启用且split strategy会产生多个part，必须在任何split/IL mutation前返回`MAGAZINE_FULL_STRUCTURE_SPLIT_UNSUPPORTED`；普通非magazine split保持原行为。未来若要支持，需另立计划在split前建立一次source-bound full structural index。本批禁止让每个part生成partial ArticleIR后冒充full identity。

`PhysicalPageNumber`必须来自parser保留的source page metadata，不能由enumerate重建。建立一个canonical resolver，例如 `DocumentPageIndex`：

```python
page_by_source_number(n)
selected_position_of(n)
output_index_of(n)
are_source_adjacent(a, b)  # abs(a-b)==1 且方向/边界合法
```

### 4.2 全消费者迁移

使用 `rg` 盘点并迁移所有：

```text
enumerate(docs.page) 后把 index+1 当 identity
docs.page[page_number-1]
by_page/list-position混用
相邻性仅按 filtered list position
```

至少覆盖：PageClassifier reports、ChainBuilder、ArticleBuilder、ArticleIR serializer、RunTrace、fixed assets、article_flow、chain allocation、detectors、HITL page refs、`ComplianceExpectations`/FinalPdfValidator touched lookup、checkpoint/report writers。需要稠密访问时通过resolver取对象，不修改physical ID。

### 4.3 不变量

- 同一源PDF全本运行与subset运行中，同一semantic element的source page/ref/ArticleIR ID一致；
- subset从文章中段开始时仍使用全本owner/context/chain identity；
- `--pages 1,3` 不创建跨页chain；
- `--pages 2-3,8-9` 只允许2↔3、8↔9候选，3↔8永不相邻；
- selected page缺失时返回typed absent，不负索引/越界/猜页；
- 本批把PageSelectionMap传入`ComplianceExpectations`和现有FinalPdfValidator，使physical 7/8/9不会直接索引3-page output；C20C扩展全部render/manual checks，但不能修复一个本批已知会静默错页的临时状态。

## 5. Closed ElementRole 与 raw-label mapping

定义versioned enum，建议最小闭集：

```text
BODY
HEADING
CAPTION
TOC_RECORD
RECORD
DROP_CAP
FORMULA
FURNITURE
PASSTHROUGH
UNCLASSIFIED
```

要求：

- `UNCLASSIFIED` 是closed值，必须带mapping reason，默认protected/no-reflow；
- continuity member/head/tail是chain membership，不冒充element role；
- debug overlay不会映射成任何role；
- raw `layout_label`保留在evidence中，不直接驱动allocator/repair；
- formula/furniture/passthrough永远不进translation/reflow slot；
- BODY才可进入通用flow；HEADING/CAPTION/TOC_RECORD/RECORD使用各自policy；
- drop-cap protection独立于BODY ownership。

新增 `configs/element_roles.json`（或等价versioned mapping），列出每个已知raw label→role、allowed consumers和unknown fallback。把 `configs/article_flow.json.eligible_roles` 改为enum值，不能再出现 `plain text/text/paragraph_hybrid`。

用AST/运行时盘点所有role消费者，测试mapping coverage。新增raw label必须先更新配置/schema；未知值fail closed为UNCLASSIFIED，不能自动归BODY。

## 6. Provisional owner在chain之前

将高层顺序改为：

```text
PageClassifier
→ ArticleBuilder.build_provisional(docs, physical_page_index)
→ ChainBuilder.process(docs, provisional_owners)
→ ArticleBuilder.finalize(provisional, chains)
→ RunTrace.from_document(final ArticleIR)
```

### 6.1 Provisional ownership

- page policy的 `opens_article/starts_article/chain_eligible/translate` 建立0/1 owner；
- 疑似同页多文章页标unsupported且0 owner/no slot；
- page kind缺失/ambiguous且无法安全归属时unassigned；
- page 8与9如果均 `article_opener`，必须是两个owner，即便相邻、字体/栏位相似。

### 6.2 Chain eligibility

chain candidate只有同时满足才可建立：

```text
same provisional article_id
physical pages same page or abs(diff)==1
page policy chain_eligible
endpoint roles BODY
typed continuity signals pass
head-start evidence pass
no unsupported/hard boundary
```

禁止finalizer因chain把两个provisional owners合并。若旧chain signal跨owner，记录 `CHAIN_CROSSES_PROVISIONAL_OWNER`并拒绝；不修改owner。

### 6.3 Chain identity/order/evidence

ArticleIR显式记录：

```text
chain_id
article_id
ordered_member_refs[]
source_ranges[]
member_physical_pages[]
head_start_evidence
tail_end_evidence
decision_reason/version
```

member order由reading order + physical adjacency确定，不按debug ID或当前list insertion。拼合source必须与ordered members conservation一致。

`head_start_evidence` 是closed evidence，例如 `sentence_continuation`、`lowercase_or_punctuation_continuation`、`manual_adjudication`、`not_applicable_same_page_column`；自由文本只作说明，不能驱动decision。

## 7. ArticleKnowledgeState 与精确capture点

新增immutable、versioned `ArticleKnowledgeState`，每次新generation不原地覆盖历史：

```text
document_semantic_sha256
page_selection_map_sha256
article_ir_sha256
run_trace_generation
stage
articles / elements / chains / legal_slots refs
article_context_record_refs / context_sha256
context_input_manifest_sha256
style_policy_sha256 / page_policy_sha256
manual_term_inventory_sha256
manual_constraint_refs
fixed_asset_inventory_sha256
status/reason
```

把`ILTranslatorLLMOnly.translate()`内临时生成的article context抽成versioned `ArticleContextRecord` planner。每条record只读取本article的ordered semantic refs、chain/context window、page/element policies、style/register summary和人工术语；记录input refs、generator/config version和canonical digest。Article B不得读取Article A的brief/terms/source text。

在 `high_level.py` 明确捕获：

1. `SOURCE_RECONSTRUCTED`：ArticleBuilder.finalize与RunTrace创建后，term extraction前；
2. `PRE_TRANSLATION`：automatic terms与`hitl.after_term_extract`完成后、translator第一次调用前；正常翻译持久化每article的context/style/page-policy/manual-term records和request-delivery预期。`skip_translation`时checkpoint仍必须存在，但只写deterministic `context_input_manifest_sha256`（source refs、policy、style、manual-term inventory）；`context_record_refs=[]`、`context_sha256=null`，context brief generation与delivery状态均为`NOT_EXERCISED`，reason/scope=`SKIP_TRANSLATION`，不得调用模型或伪造summary/delivery evidence；
3. `TARGET_GENERATED`：`il_translator.translate`和`hitl.after_translate`后、任何article_flow前；skip translation时为`NOT_EXERCISED`并带scope/reason；
4. `TARGET_ALLOCATED`：`article_flow.apply`后、`il_translated` checkpoint前；flow disabled/unavailable时明确`SKIPPED`；失败rollback记录`ROLLED_BACK`及previous generation；
5. `TYPESET`：semantic Typesetting、formula restore与drop-cap render后、post-typesetting detectors/repair前。

每个stage写checkpoint/manifest record；state digest不含路径、timestamp、overlay/debug ID。C19 repair创建后续generation；本批只提供PageSelectionMap和基础PDF页映射，C20C增加完整final/manual evidence，不在本批伪造。

## 8. Shared legal-slot planner

从canonical ArticleIR region和fixed-asset inventory构造矩形集合：

```text
article envelope
minus fixed visual assets
minus protected roles（heading/caption/toc/record/formula/furniture/drop-cap等）
minus other article regions
= ordered legal slots
```

要求：

- source physical page identity贯穿；
- subtract是真正几何差集/分段，不只是给slot附obstacle metadata；
- 去掉小于config minimum的碎片；
- slot order按article reading order/column/page；
- same-page multiple columns可属于同一owner；相邻页必须physical adjacent且same owner；
- chain backfill和ordinary article flow调用同一planner；
- fit只通过现有真实typesetter measure/fit入口；
- source/target ranges、fixed assets、untouched text全部守恒；
- unsupported/unassigned页返回无slot和typed reason。

不要在本批实现新的排版算法；复用C06/C07/C08实现，统一其slot来源和page resolver。

## 9. Runtime dependency与capability preflight

三个时期分开检查，不能都塞进parse前的`preflight_magazine_runtime()`：

1. 配置期（PDF/IL前）：`magazine_chain_translate` requires `magazine_chain_detect` + `magazine_article_group`；`magazine_column_reflow` requires配置开关层的article group/chain/fixed-asset功能；
2. translator构造后、任何target mutation前：article flow production入口只允许支持该路径的translator（当前`ILTranslatorLLMOnly`）；不支持时fail closed/residual。`skip_translation`明确绕过translator capability并把target stages记`NOT_EXERCISED`；
3. ArticleIR/RunTrace/fixed inventory建立后、`article_flow.apply`前：document-specific preflight验证RunTrace、inventory、owner-scoped chains、legal-slot planner和state digests真实存在。

使用真实开关名 `magazine_column_reflow`，测试和文档不得写不存在的 `article_flow=true`。

## 10. 测试矩阵

新增fast gates，全部声明 `GATE_SET = "fast"`。本分支直接逐项运行并把准确文件名交给 WT0；只有 WT0 integration owner 修改统一 `run_all.py` registry/meta-test，合入后验证存在、唯一、依赖顺序正确。

### 10.1 `spec_check_physical_page_identity.py`

- full doc与`--pages 7-9`的source refs/physical page/ArticleIR IDs一致；
- subset从文章中段开始仍恢复full owner/context；没有opener/前页的partial fixture必须失败而非生成不同article ID；
- `--pages 1,3`不相邻、不建chain；
- `2-3,8-9` resolver映射正确，无3↔8；
- `docs.page[page_number-1]`类consumer已被行为测试覆盖；
- absent page typed failure；
- serializer round-trip保持identity。
- 3-page targeted output的physical 7/8/9经PageSelectionMap映射到output 0/1/2，现有FinalPdfValidator不直接访问`output[6]`。
- magazine+multi-part split在切PDF前typed fail-closed且零partial ArticleIR/HITL mutation；普通非magazine split保持既有行为。

### 10.2 `spec_check_article_ir_contract.py`

- 每个semantic processable element恰好一个owner或typed unassigned；
- closed role mapping覆盖已知labels；unknown→UNCLASSIFIED/protected；
- debug overlay 0 elements；
- config eligible roles只有enum；
- unsupported same-page multi-article fixture无owner list、slot、reflow；
- deterministic IDs不含path/debug ID。

### 10.3 `spec_check_chain_owner_scope.py`

- same owner同页跨栏、相邻physical pages正例；
- 不同owner、两个article opener、1↔3、3↔8、unsupported、role非BODY均拒绝；
- chain不能让finalizer合并owner；
- member order、head-start evidence、source拼合守恒；
- page 8/9独立article。

### 10.4 `spec_check_article_state_checkpoints.py`

- 五个capture点顺序和digest；
- 正常翻译的PRE_TRANSLATION context records可重放，Article A/B context/terms/style互不泄漏，人工术语优先且request delivery引用context digest；
- skip_translation仍有PRE_TRANSLATION checkpoint和deterministic input-manifest，但context refs/digest为empty/null、generation/delivery为NOT_EXERCISED且零模型调用；disabled/unavailable/rollback状态同样显式；
- generation monotonic；
- debug on/off相同；
- source/pre-translation state不含target fields，target state不伪造typeset/final。

### 10.5 legal slots

扩展 `spec_check_chain_slot_backfill.py` 和 `spec_check_article_flow_ir.py`：真实障碍把一个大slot切成多个合法片段；任何allocated glyph不与障碍/other owner相交；chain/ordinary flow使用同一slot digest；fragment拼合等于完整target；不足时rollback/residual。

## 11. ABB checkpoint与production入口

使用与C17相同、由总调度器在worktree外提供的只读绝对目录契约；本文件不依赖C17的`.tmp`：

```bash
test -n "${ABB_FAILURE_ROOT:-}"
test -d "$ABB_FAILURE_ROOT/ABB-zh/work/ABB-zh"
```

当前审计环境可设置`ABB_FAILURE_ROOT=/workspace/scratch/c4885b0ecb55/abb_extracted`。目录/关键hash不符时`BLOCKED_PENDING_ABB_FAILURE_ROOT`。回放：

```text
checkpoint.07_page_classifier.xml
checkpoint.08_chain_builder.xml
article_ir.json
chain_report.json
```

Expected SHA-256（本文件自足，不回查C17）：

```text
checkpoint.07_page_classifier.xml 1c3f88ef69950e8a8bac3c24e8347b1b69da2996b1f07f673d01499cf0e1800f
checkpoint.08_chain_builder.xml    1c3f88ef69950e8a8bac3c24e8347b1b69da2996b1f07f673d01499cf0e1800f
article_ir.json                    f522279e66d4bcd003c4cd05ca01a69f3a9ac0367c7d3a4ccd7fa1c437d9e440
chain_report.json                  1d01a009ca4abd3be3d5a36be647cbfb2904f69ee815314f956b079ef0171d16
```

回放前执行单次机器校验；任一missing/mismatch停止：

```bash
uv run python -c 'import hashlib,os,pathlib; r=pathlib.Path(os.environ["ABB_FAILURE_ROOT"])/"ABB-zh/work/ABB-zh"; e={"checkpoint.07_page_classifier.xml":"1c3f88ef69950e8a8bac3c24e8347b1b69da2996b1f07f673d01499cf0e1800f","checkpoint.08_chain_builder.xml":"1c3f88ef69950e8a8bac3c24e8347b1b69da2996b1f07f673d01499cf0e1800f","article_ir.json":"f522279e66d4bcd003c4cd05ca01a69f3a9ac0367c7d3a4ccd7fa1c437d9e440","chain_report.json":"1d01a009ca4abd3be3d5a36be647cbfb2904f69ee815314f956b079ef0171d16"}; bad=[n for n,h in e.items() if not (r/n).is_file() or hashlib.sha256((r/n).read_bytes()).hexdigest()!=h]; assert not bad, ("ABB_CHECKPOINT_HASH_MISMATCH",bad)'
```

```bash
timeout 180s uv run python tools/replay_article_ir_checkpoint.py \
  --root "$ABB_FAILURE_ROOT/ABB-zh/work/ABB-zh" \
  --pages 7-9 \
  --report .tmp/c18/replay/article-ir.json
```

工具诊断旧artifact的列表位置/physical page差异，并用新resolver重建：

- source physical pages仍为7、8、9；
- decisions中的page 7 toc、8/9 article_opener按physical页绑定；
- page 8和9是独立owner；
- 无8↔9跨owner chain；
- legacy debug labels由C17 replay adapter排除，production不按文本猜。

原始 PDF/config存在时再跑：

```bash
timeout 720s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir ./reviews \
  --files ./examples/input/ABB-zh.pdf \
  --pages 7-9 --only-include-translated-page \
  --skip-translation --no-debug \
  --working-dir ./.tmp/c18/subset/work \
  --output ./.tmp/c18/subset/output
```

缺原始输入时标外部acceptance pending，不用归档input替代。

## 12. 必跑回归

```bash
# C17回归必须在本批改动后重跑
timeout 90s uv run python spec_checks/spec_check_debug_semantic_invariance.py
timeout 90s uv run python spec_checks/spec_check_geometry_write_guard.py
timeout 90s uv run python spec_checks/spec_check_run_trace.py

# 本批新gate
timeout 90s uv run python spec_checks/spec_check_physical_page_identity.py
timeout 90s uv run python spec_checks/spec_check_article_ir_contract.py
timeout 90s uv run python spec_checks/spec_check_chain_owner_scope.py
timeout 90s uv run python spec_checks/spec_check_article_state_checkpoints.py

# 既有行为
timeout 90s uv run python spec_checks/spec_check_chain_single_request.py
timeout 90s uv run python spec_checks/spec_check_chain_slot_backfill.py
timeout 90s uv run python spec_checks/spec_check_article_flow_ir.py
timeout 90s uv run python spec_checks/spec_check_article_cross_column.py
timeout 90s uv run python spec_checks/spec_check_article_cross_page.py
timeout 90s uv run python spec_checks/spec_check_fixed_asset_guard.py
timeout 90s uv run python spec_checks/spec_check_gate_registration.py
timeout 600s uv run python spec_checks/run_all.py --set fast
```

## 13. 原子提交与集成交接

按三个commit执行，每个commit前后跑直接相关gate并精确stage。禁止 `git add -A`。

### Commit 1

Physical page resolver、closed role schema/mapping、所有消费者迁移、对应tests/config。

### Commit 2

Provisional owner→owner-scoped ChainBuilder→final ArticleIR顺序、chain evidence与tests。

### Commit 3

ArticleKnowledgeState、capture points、shared legal-slot planner、runtime dependency与tests。

每次：

```bash
git status --short
git diff --check
git add -- <本commit逐项审阅过的精确pathspec>
git diff --cached --check
git diff --cached --stat
git commit -m "<上述固定主题>"
```

不要把C17分支文件重新实现一份。交接列出3个commit、schema versions、page resolver API、role mapping coverage、chain refusals、state capture点、slot digest、全测试退出码、RAR/production replay状态。Integration owner按commit顺序cherry-pick，并在合并后再跑第12节。

## 14. 完成与停止条件

完成必须同时满足：

- full/subset physical identity稳定，non-contiguous pages不被当相邻；
- ArticleIR/HITL magazine的multi-part split在切分前typed fail-closed，零partial state；
- 所有page consumers通过resolver；
- element role闭集、unknown protected、raw label不驱动allocator；
- provisional owner在chain之前且chain永不跨owner；
- page 8/9两个article opener保持独立；
- chain order/head-start/state refs显式；
- 五个stage checkpoint真实捕获，pre-translation context可审计，skip/rollback不伪造；
- chain和article flow共享扣除obstacle后的legal slots；
- runtime使用正确开关/依赖；
- C17、本批和既有gates全绿；
- 同页多文章仍unsupported/no-reflow。

停止条件：C17前置失败、需要支持同页多个owner或magazine split而不能fail-closed、page identity缺失且只能靠list位置猜、closed role mapping会把未知值默认BODY、chain必须合并owners才能过、legal slot必须移动fixed assets、原始input hash不符、任一测试联网，或10小时到达仍未满足核心不变量。停止时提交已独立通过的原子commit，不提交半迁移schema，并报告下一个可执行点。
