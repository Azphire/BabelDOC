# Agent 执行计划 00：冻结双向多样张与外部验收真值

目标分支：`migration/minimal-v0.6.4`
起始基线：主控在 `.runtime/demo-repair/controller-state.json` 下发的 `execution_start_sha`
执行角色：本项目唯一、后续持续复用的执行 agent
本阶段性质：只准备可复现输入、配置、expectations 和 gate matrix，不修改翻译或排版产品逻辑

## 独立执行契约

- 确认 branch 精确为 `migration/minimal-v0.6.4`，仅一个 worktree，HEAD 与 controller state 一致。Stage 00 首次 `initial` 入口要求 clean；先按本计划实现并测试 `tools/tree_state_v1.py`。后续 dirty handoff 才按 state 中 helper path/hash 验证 digest；任一不符立即停止。
- `agent_id` 必须等于 controller state 中的唯一 executor；不得创建子 agent、branch 或 worktree。
- 不接触 API key，不启动 paid translation，不访问已停止的 C22 目录。
- 不执行 `git add/commit/stash/reset/clean/rebase/amend/push`；只修改本计划 allowlist，完成后把未提交工作树交给主控。
- controller state 必须逐项给出只读输入的精确路径与 SHA-256；禁止递归猜路径、按文件名从网络下载替代品、把同一 PDF 的裁剪件当独立样张，或把 detector 当前输出当真值。
- 样张专属文本 hash、bbox、record、标题、首字和 endpoint anchor 只允许写入 `tests/fixtures/demo/expectations/*.json`；paid matrix 只可镜像 gate ID、物理页窗、closure和内容 hash，并须与 expectations 逐字一致。产品代码与后续通用 verifier 源码不得包含这些值。

## 1. 任务结果

冻结一套能区分“定位样张、迁移样张、独立 holdout”的双向 demo 矩阵，并生成后续六个阶段唯一可用的外部 expectations。Courier 只保留为已知失败 diagnosis；任何阶段修复后必须先跑另一刊物，再回归 Courier，最后跑未用于实现判断的 holdout。

本阶段还要新增最小中译英配置，验证两个方向使用同一产品路径。被分栏或分页切断的同一段落是必验功能：每个方向都必须冻结至少一条同页跨栏 truth chain 和一条相邻跨页 truth chain；每条均标为 `required_joint=true`，后续不得以普通翻译 fallback 获得 accepted gate。相邻但不连续的 negative endpoint 也必须冻结；运行时检测必须与 positive truth 一一匹配，命中 negative 或产生未裁决 detected chain 都失败。

## 2. 输入权威与当前已知缺口

按以下优先级读取并交叉核对，低优先级证据不能覆盖高优先级人工决定：

1. 实际 source PDF 字节、页数、cropbox、原分辨率页面。
2. `<repo-root>/reviews/*.decisions.json` 中的人工 page kind、drop-cap 和术语决定。
3. `<repo-root>/corpus/registry.user.json`、`page_labels.json`、`chain_labels.user.json`。
4. controller state `historical_runs[]` 明列且带tree digest的可选历史 IL/debug/source-box目录；当前repo不假定 `example/ci/output_baseline` 或其他固定目录存在。历史证据只帮助定位source element，不能决定truth。
5. 旧 paid Courier 包；它只能作为负例，不能生成正例 expectations。

当前计划编写时已核实：

- 本地英文刊物字节只有 `Courier-en.pdf`；`examples/ci/test.pdf` 是一页测试 fixture，不能充当非 Courier 杂志。
- 本地有 ABB、HuaweiTech、ITU、WIPO、bull、fd 六份中文 PDF。
- 当前最小 branch 没有 `corpus/`、`examples/input/` 和 `minimal.zh-en.toml`，`reviews/` 只有 Courier decisions。
- 现有 `chain_labels.user.json` schema 只表达相邻页 boundary 的 `link`，不能单独证明精确 member 顺序，也不能覆盖同页跨栏。

因此，主控必须在下发本阶段前提供完整 truth 资产和至少两份互不相同的非 Courier 英文刊物：一份 transfer、一份 holdout。任一缺失时，本 agent 输出精确 blocker 清单后停止；不得缩减为 Courier-only，也不得让一份英文 PDF同时承担 transfer 与 holdout。

## 3. 允许改动

允许新增或修改：

- `minimal.zh-en.toml`
- `tests/fixtures/demo/sample_matrix.json`
- `tests/fixtures/demo/paid_gate_matrix.json`
- `tests/fixtures/demo/rotation_queue.json`
- `tests/fixtures/demo/expectations_manifest.json`
- `tests/fixtures/demo/legacy_negative.json`
- `tests/fixtures/demo/expectations/*.json`
- `tools/validate_demo_matrix.py`
- `tools/tree_state_v1.py`
- 新增 `babeldoc/magazine/demo_schema.py`
- `tests/minimal/test_demo_sample_matrix.py`
- `tests/minimal/test_tree_state_v1.py`
- 新增 `tests/minimal/test_demo_schema_vectors.py`
- 新增 `tests/fixtures/demo/schema_vectors.json`

只有权威人工文件确已由主控放在仓库标准位置且内容必须随分支执行时，才允许把它们原样加入：

- `corpus/registry.user.json`
- `corpus/page_labels.json`
- `corpus/chain_labels.user.json`
- `reviews/*.decisions.json`

除纯schema helper `babeldoc/magazine/demo_schema.py` 外，禁止修改其他`babeldoc/`产品代码、现有detector/config阈值、翻译prompt、排版算法或二进制PDF。该helper本阶段只供validator/测试导入，不接入或改变运行产品行为；后续阶段才由report path import。PDF只放在controller state指向的`.runtime/demo-repair/fixtures/sources/`，不提交Git。

## 4. 样张选择硬约束

`sample_matrix.json` 每个 entry 固定：`sample_id / publication_id / provenance_id / role / source_lang / target_lang / source_sha256 / page_count / config_relpath+sha256 / expectations_relpath+sha256 / authority_relpaths+hashes`。tracked matrix 不保存 source 绝对路径；controller state 另有 `samples[sample_id].source_path`，并复验该字节 hash。后续命令中的 source 一律从 state map 解析，config/expectations 从 repo-relative 字段解析，禁止出现未定义的 `matrix.source_path`。

`expectations_manifest.json` 是实体文件：`accepted_samples[]` 列出 `sample_id / expectations_relpath / expectations_sha256 / source_sha256 / config_sha256 / schema_version`，按 sample ID排序且与sample matrix双向一一对应；`legacy_negative[]` 只引用独立legacy spec/expectations path+hash，不进入五份accepted sample计数。controller state中的manifest path/hash指向该文件，不得用未落盘逻辑集合冒充manifest。

`legacy_negative.json` 固定 `schema_version / archive_sha256 / source_sha256 / output_sha256 / run_tree_digest_algorithm=tree-content-v1 / run_tree_digest / expectations_relpath+sha256 / globally_unique_sample_id+gate_id / physical_pages+closure_pages / readable_sidecars[]`。它不含临时绝对路径、不充当 transfer/holdout/accepted row。主控物化后把 archive/source/output/work-dir绝对路径、各hash、只读tree digest算法与值、IDs与`pages_arg`写入 state的 `legacy_negative` object；Stage 06只能读取该object，不自行解包猜路径。

### 4.1 最低独立样张集合

矩阵至少有五个不同 source hash：

| 角色 | 方向 | 要求 |
| --- | --- | --- |
| `diagnosis` | en→zh | Courier；仅用于复现已知问题和回归 |
| `transfer` | en→zh | 非 Courier 英文刊物；用于第一次泛化门 |
| `holdout` | en→zh | 另一份非 Courier 英文刊物；实现期间不得用于调阈值 |
| `transfer` | zh→en | 中文刊物；不得与 holdout 同 hash |
| `holdout` | zh→en | 另一份中文刊物；实现期间不得用于调阈值 |

同一刊物不同页窗仍是同一 sample，不能同时算 transfer 和 holdout；不同导出字节但 `publication_id/provenance_id` 相同也不能伪装独立样张。transfer 与 holdout 必须同时具有不同 source hash 和不同 publication/provenance identity。一个 sample 可以承担多个 feature gate，但它在全部阶段的 diagnosis/transfer/holdout 角色固定不变。

### 4.2 结构覆盖

每个方向分别满足，且这里的必备 chain 全部是 `chain_role=body`：

- 至少一条 `same_page_cross_column` truth chain；
- 至少一条 `adjacent_cross_page` truth chain；
- 至少一个多栏 layout 页；
- 至少一个标题页；
- 至少一个冻结 `keep` drop-cap；
- TOC 有单行 record、块状 record 和同页 prose exemption。若一页不能同时提供三类，可由同方向多份样张组合。

en→zh 的跨栏/跨页 body truth 必须由非 Courier transfer 与 holdout 的并集覆盖，二者各至少包含一条 body truth；zh→en 也由其 transfer/holdout 并集覆盖两类，且两份样张都不能没有 body truth。Courier 的 title/display 或 body diagnosis chain 都不能单独满足这些槽位。

若实际 corpus 无法满足其中一项，矩阵 validator 必须失败并列出缺失类别。计划不得把“未找到”改为 optional；主控应补样张或人工标注后重新运行 Stage 00。

## 5. expectations schema

每份 `expectations/<sample-id>.json` 至少包含：

```text
schema_version / chain_adjudication=exhaustive_for_gate_windows
sample_id / publication_id / provenance_id / source_sha256 / page_count
source_lang / target_lang / config_id / config_sha256
normalization_profile: id + version + explicit rules
direction_profile: profile_id + source_script + target_script + residue_script + threshold IDs/values
authority_files[]: path + sha256
truth_chains[]
chain_adjudications[]
toc_expectations[]
layout_expectations[]
title_expectations[]
dropcap_expectations[]
coverage_exemptions[]
gate_windows[]
```

truth、chain adjudication、TOC、layout、title、drop-cap与coverage exemption对象都有共同 header：全sample唯一且跨数组不复用的 `expectation_id`、closed `expectation_type=truth_chain|chain_adjudication|toc_record|layout_region|title|dropcap|coverage_exemption`、`required`。transition的 `adjudication_id` 引用chain-adjudication对象的 expectation ID。

每个 `gate_windows[]` 必须给出全局唯一 `gate_id`、`check`、`acceptance=semantic_pre_layout|final`、升序唯一的 `physical_pages` 与 `closure_pages`、`required_expectation_ids`、`truth_chain_ids`、`chain_adjudication_ids`、`candidate_universe_version/hash` 和 `exhaustive_chain_adjudication=true`。gate ID 在全部 expectations、paid matrix与legacy gate中不得复用；这些 ID 只引用本文件中存在的对象并恰好解析一次，`check` 只能引用其允许的expectation types，window覆盖所有引用member的完整closure。Stage 00 validator要求其选择字段（含acceptance）与 `paid_gate_matrix` 对应 row逐字一致；verifier只从该gate window获得acceptance authority，不自行读取paid matrix。

### 5.1 连续链真值

每条 `truth_chains[]` 必须有稳定 expectation ID、`chain_role=body|title|display`、article/role、`required_joint=true`、`representation_policy` 和两个以上 ordered members。`transitions[]` 长度必须等于 `members.length-1`，每项保存 `from_order / to_order / boundary_kind=same_page_cross_column|adjacent_cross_page / adjudication_id`；不能用单个 `boundary_kind` 概括三 member 的 `column -> page` 链。`representation_policy.mode` 只能是 `all_members_nonempty|single_active_holder`：body 固定前者；后者只允许人工确认的 title/display，并指定唯一 `active_holder_order`。每个 member 的 `source_anchor` 至少保存：

```text
order
physical_page_1based
source_text_sha256
normalized_source_length
source_box_pt / match_tolerance_pt
normalized_source_box   # cropbox-relative，四个固定六位小数字符串
role
endpoint_kind
diagnostic_alias        # 可选；pN#K 只作旧产物定位，不能作唯一 anchor
```

`normalization_version=demo-text-v1` 固定：Unicode NFKC；删除U+00AD；仅当ASCII hyphen后紧接换行且两侧均为Unicode letter时删除hyphen+换行；其余Unicode whitespace按一个ASCII space折叠并strip，大小写与标点保持。

唯一实现所有者是本阶段新增的 `babeldoc/magazine/demo_schema.py`；Stage 00 validator和Stage 01–06产品/report helper都import它，不复制算法。canonical坐标固定为 `pymupdf_cropbox_top_left_points`：先把任意IL box转换到cropbox左上原点、x向右/y向下的point坐标，再除以cropbox width/height；用`Decimal(str(value))`按`ROUND_HALF_EVEN`量化到`0.000001`，以固定六位十进制字符串保存。canonical JSON固定为Python `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")`，payload只含字符串和整数，不含float。`audit_ref = sha256(canonical-json(anchor_schema_version, physical_page_1based, normalization_version, box_quantization_version, source_text_sha256, normalized_source_length, normalized_source_box, role))`。`match_tolerance_pt`只属于外部expectation且不进入identity；产品report只写`audit_ref + observed_anchor/observed_box`，不复制人工tolerance。运行时映射必须唯一，0/multiple match都失败。local/debug ref、page label和diagnostic alias只作evidence。TOC/layout/title/drop-cap/coverage exemption使用同一anchor；line split后以`parent_audit_ref -> ordered child_audit_refs`关联。

`tests/fixtures/demo/schema_vectors.json` 冻结至少Latin、Han、软连字符/断词、bottom-left IL→top-left cropbox转换和量化half-even的input→normalized text/anchor JSON/audit hash向量。Stage 00 validator、demo_schema与所有后续sidecar测试必须跑同一向量；任何version/向量变更回到Stage 00并使证据失效。

冻结步骤：

1. 用人工 chain/page label 找到候选边界。
2. 在 source PDF 原分辨率页面确认语义确为同一段落，并人工确定 reading order。
3. 用历史 IL/debug 或离线 PyMuPDF 文本块定位 member；不得运行当前 ChainBuilder 后照抄其结果。
4. 用版本化规则（至少 NFKC、软连字符、空白折叠和行末断词政策）规范化文本，计算 hash/长度，记录 point 与 normalized source box及小容差；重新从 PDF/历史 IL 独立解析一次并匹配。
5. 对 gate window 中 detector 可能接触的所有相邻 column/page endpoint 建立 `chain_adjudications[]`：稳定左右 source anchor、boundary kind、`label=positive|negative`、reason/evidence、`adjudicated=true`。truth transitions 引用 positive adjudication；negative 不另用无 schema 列表。主控逐条查看 source crop 和完整合并文本后签署。每个 gate window 冻结 candidate universe version/hash 与全量 adjudication IDs；未裁决 endpoint 存在时不得标记 exhaustive。

`chain_labels.user.json` 的 boundary `link=true` 只是候选依据。member 数量、精确顺序和同页跨栏必须由上述 adjudication 补齐；相邻但不相连的 endpoint 以 negative adjudication 冻结，防止为提高召回而把不同文章/段落硬接在一起。

### 5.2 其他 feature expectations

- TOC：每个 record 保存 source anchor、`single_visual_line|block|prose_exempt`、record group、source line/band 数；不冻结具体 LLM target 文本。
- layout：保存 source x-band、容差、fixed asset inventory hash，以及允许留白但禁止跨栏的角色。
- title：保存 source anchor、目标脚本政策；`target_lang=zh` 时 required Chinese title 为 `single_line_if_scale_at_least_0.55`，`target_lang=en` 时要求完整、可读且仍在 source title region。
- drop-cap：保存 source anchor、人工 `keep|flatten` 决定和目标语渲染政策；不写死翻译后的首字符。
- coverage exemption：只允许带人工 role/reason 的 credit、folio、品牌或明确 furniture；不能用字符长度阈值批量豁免正文。
- gate window：物理页 1-based，必须包含相交 truth chain 的完整 transitive closure；不能把 chain 另一端裁掉。

所有 feature report 共同使用 run envelope：`schema_version / report_kind / source_sha256 / config_sha256 / source_lang / target_lang / resolved_product_facts+sha256 / normalization_version / snapshot_stage / entries / totals`。`resolved_product_facts`只来自TranslationConfig和共享代码实际解析出的语言/开关/阈值，不含外部direction-profile ID/hash或人工tolerance；verifier把它与expectations中的direction profile比较，并把profile ID/hash写入gate JSON。产品report是run-scoped，不含gate ID，也不得读取expectations；`required`、representation/preserve许可只由verifier将通用事实与外部expectations叠加判定。Stage 00 expectations另冻结旧Courier paid包专用的`legacy_negative` sample/gate，记录archive/source/output/run-tree hash与可解释sidecar列表，只供Stage06 exit-1回放，不计作accepted row。

## 6. 双向配置

以 `minimal.en-zh.toml` 为模板新增 `minimal.zh-en.toml`，只做最小方向差异：

```toml
[babeldoc]
lang-in = "zh"
lang-out = "en"
openai = true
openai-model = "gpt-4o-mini"
no-dual = true
qps = 1
pool-max-workers = 1
term-pool-max-workers = 1
report-interval = 0.5
debug = false
watermark-output-mode = "no_watermark"
```

用现有配置加载器离线解析两份 TOML，断言除方向字段外的固定 demo 参数一致。文件显式 UTF-8，无 BOM；不写 API key、绝对路径或样张名。

## 7. paid gate matrix 与轮换队列

`paid_gate_matrix.json` 的每一行至少记录：

```text
gate_id / stage / check / acceptance=semantic_pre_layout|final
sample_id / direction / sample_role
physical_pages / closure_pages
required / cache_policy
source_sha256 / config_sha256 / expectations_sha256
required_expectation_ids / truth_chain_ids / chain_adjudication_ids
closes_gate_ids[]
required_revalidation_gate_ids[]
```

该 matrix 是内容寻址的只读 gate spec，不保存可变 `status`。Stage 01/02 的第一次真实取证 row 固定 `acceptance=semantic_pre_layout`，只允许产生 `integration_pending_layout`；Stage 03 必须另有 `acceptance=final` 的 closure rows，并用 `closes_gate_ids[]` 显式关闭相交的 Stage01 chain、Stage02 TOC 与 Stage03 layout gates。主控将 `pending|integration_pending_layout|pass|fail|invalidated`、candidate SHA、attempt ID、exit 与 artifact hashes 追加到 `.runtime/demo-repair/gate-results.jsonl`，以 `(candidate_sha, gate_id, attempt_id)` 唯一关联；任何阶段都不得改 frozen matrix 记结果。

每个 Stage 01–05 的队列按以下顺序冻结；Stage 01/02 的“通过”在本段只表示当前 step 得到 `integration_pending_layout`，最终 pass仍由 Stage 03 closure row产生：

1. 已知 diagnosis fixture 或旧负例用于定位，不产生新 paid 通过证据。
2. candidate 提交后先跑另一刊物的 transfer gate；方向按该阶段矩阵交替。
3. transfer 通过后回归 diagnosis gate。
4. 前两项通过后才运行 holdout；同一 executor 在 Stage 00 已见过 source/truth，所以这里的 holdout 仅表示“首次 paid 前未用于产品阈值/实现判断”，不声称人员盲测。首次 translated target、失败 crop和视觉结论在此之前不得用于改代码。
5. holdout 失败时保留原 expectations；该样张一旦向执行 agent 回传并用于修复，即升格为 transfer，原 holdout 身份失效。主控必须补一份从未披露且 publication/provenance 均独立的新 holdout并重新执行 Stage 00；补不出就停止。不得现场修改 truth 或只缩小页窗。

`rotation_queue.json` 为每个 stage 冻结有序 `step_id / sample_id / source_sha256 / publication_id / direction / role / paid_gate_id / predecessor_step_ids / required_predecessor_result / on_pass_step_id / on_fail_step_id / disclose_policy`。`on_pass_step_id/on_fail_step_id` 必须指向同一冻结 queue 的唯一 step或显式 `blocked`；failure只能进入另一条 transfer/validation row或`blocked`，不得进入diagnosis、holdout或下一stage。每个stage的queue还必须逐项包含其paid rows声明的`required_revalidation_gate_ids[]`，以当前candidate和声明acceptance重跑，不能靠主控临场补步。主控另在 `.runtime/demo-repair/rotation-history.jsonl` 追加 `candidate_sha / tuning_sample_ids[] / step_id / executed_sample_id / result / evidence_hash`及candidate变化时的`cursor_reset`。每次paid前由validator核对：首次transfer与本轮全部定位/调参sources不同；相邻执行不重复publication/source；所有predecessor在同一candidate SHA下达到声明的required result；下一step严格等于上一result选择的冻结分支；顺序固定为transfer→diagnosis regression→未披露holdout；引用的paid row唯一且required。各功能计划不得自行重排。

Stage 06 冻结三个整本 required gate：Courier en→zh、非 Courier en→zh、中文源 zh→en。另一个方向的 holdout 页窗仍必须进入最终 chain/coverage 汇总。

## 8. 离线 validator 与测试

`tools/validate_demo_matrix.py` 只校验输入和 schema，不执行产品功能。exit 语义：`0=全部闭合`、`1=truth/coverage 不足且输出完整 JSON`、`2=参数或 I/O fatal`。

`tools/tree_state_v1.py` 实现controller统一算法：repo-relative path以Git的NUL分隔bytes读取并以byte order排序，digest记录path bytes、file mode、tracked index blob/status、worktree status与regular/symlink content hash；包含固定排除外的全部untracked（ignored与non-ignored），不限allowlist。固定排除仅为`.git/**`、`.runtime/demo-repair/**`、`.venv/**`、`.pytest_cache/**`、`.ruff_cache/**`、`**/__pycache__/**`；拒绝越界/绝对allowlist路径。测试覆盖staged/unstaged/deleted、mode/symlink、两类untracked、allowlist外ignored文件、NUL-safe特殊文件名以及runtime state自引用排除。

同一 helper 还提供只用于显式外部只读目录的 `tree-content-v1`：以传入 root 为边界，NUL-safe 的 repo-independent relative path bytes排序；每项纳入entry type、permission mode，以及regular file内容SHA-256或symlink target原始bytes，绝不跟随symlink。遇到绝对/越界路径、device、socket或FIFO立即失败，不应用`tree-state-v1`的Git/runtime排除，也没有隐式exclude。Stage 00冻结legacy run tree时计算一次，Stage 06回放前后用同一helper、同一算法和同一root复算；算法名和值都必须与spec/state一致。

测试至少覆盖：

1. 五个唯一 source hash、publication/provenance identity、方向与角色数量闭合；transfer/holdout 的三种 identity 任一重复都失败。
2. 缺少非 Courier 英文 transfer/holdout 时失败。
3. 每个方向的两类必备 truth 都是 body；en→zh 由非 Courier transfer+holdout 覆盖且两份各有 body truth，zh→en 同样。title/display 不计入这四类槽位。
4. truth 少于两个 member、顺序重复、bbox 越界、无 `required_joint=true`，或 `transitions.length != members.length-1` 时失败；三 member `column -> page` 保留两个 transition kinds。
5. member/feature 没有统一 source_anchor/audit_ref、只写 `pN#K`，或复合 anchor 在独立解析中 0/multiple match 时失败。
6. body 使用 `single_active_holder`、title/display 未显式许可却空 trailing，或 active holder 不唯一时失败。
7. positive/negative adjudication 冲突、transition 未引用 positive adjudication、candidate universe 缺 hash或非 exhaustive 时失败。
8. gate ID在任意sample/legacy row复用，gate window缺check/acceptance/required IDs、未包含closure，或`acceptance/physical_pages/closure_pages/required IDs`与paid row不完全一致时失败。
9. 所有 required positive transition、truth chain 和 negative adjudication ID 必须至少被一个 `required=true` paid row 覆盖；matrix union 少任一 ID、引用不存在 ID或 window 未覆盖 closure 时失败。
10. 逐 `stage+check+direction+sample_role` 验证 required rows：Stage 01/02 有双向 `semantic_pre_layout` rows，Stage 03 有显式关闭相交01/02/03 gates的 `final` rows，Stage 04–05 均有冻结双向真实 transfer/holdout 与 diagnosis/regression依赖，Stage 01 holdout 含 required body truth；Stage 06 有三个 full rows和双向独立 validation chain/feature rows。rotation每个step唯一解析到required paid row，且每个stage的`required_revalidation_gate_ids[]`依主控invalidation表完整进入该stage queue、顺序/acceptance闭合；任一漏项或重复均失败。
11. holdout 提前用于产品判断，runtime history 重复 tuning sample、相邻同 publication/source、越过 predecessor、实际下一step不等于冻结 `on_pass/on_fail` 分支，failure跳入diagnosis/holdout/下一stage，或跳过 transfer→diagnosis→holdout 顺序时失败。
12. anti-literal forbidden set 来自冻结完整 publication/sample aliases、完整 source/text hashes、diagnostic refs和序列化样张坐标；扫描本轮实际新增/修改的 product、verifier、通用 validator及runtime config allowlist，至少包含 `configs/chain_detection.json`、`line_split.json`、`conservative_typesetting.json`、title相关config、`drop_cap_render.json`和demo TOML。expectations/plan/合成 fixtures排除，既有未改上游文件以 baseline hash豁免；禁止裸搜字体族词 `Courier` 造成合法 font metrics误报。两份改名且页码/anchor数不同的 fixture须产生相同语义结论。
13. 两份 TOML 可按 UTF-8 解析，方向正确且不含 secret/绝对路径；config/direction/normalization profile hash闭合。
14. authority/source/config/expectation hash 变更时失败。
15. 任一feature/adjudication缺共同header、expectation ID跨数组重复、gate check引用错误type或required ID不能恰好解析一次时失败。
16. validator与`demo_schema.py`对全部canonical向量产生逐字相同normalized text/anchor JSON/audit hash；坐标原点、half-even、JSON number/string编码任一漂移时失败。
17. `legacy_negative.json`缺任一hash、`run_tree_digest_algorithm=tree-content-v1`、tree digest、全局唯一ID/pages或误进入accepted sample计数时失败；symlink逃逸、特殊文件类型、任意内容/mode/link-target变化都失败。
18. controller-state sample materialization map缺ID、路径猜测、bytes hash不符或存在matrix未声明source时失败。
19. Stage01/02 row若使用`final`、provisional event伪装`pass/visual-pass`、Stage03 closure漏任一依赖gate或跨candidate关闭时失败；只有`integration_pending_layout`可沿冻结01→02→03过渡。
20. 三份runtime ledger按主控统一event schema做replay/fold测试：未知event、seq/hash-chain/high-water错误、尾部半行、跨candidate/attempt悬空引用、未授权fail后pass、未按`on_pass/on_fail`游标前进均fail closed。

建议门：

```text
uv run --no-sync python tools/validate_demo_matrix.py \
  --matrix tests/fixtures/demo/sample_matrix.json \
  --paid-matrix tests/fixtures/demo/paid_gate_matrix.json \
  --rotation tests/fixtures/demo/rotation_queue.json \
  --controller-state .runtime/demo-repair/controller-state.json \
  --gate-output .runtime/demo-repair/stage00/gate.json
uv run --no-sync pytest -q tests/minimal/test_demo_sample_matrix.py
uv run --no-sync pytest -q tests/minimal/test_tree_state_v1.py
uv run --no-sync pytest -q tests/minimal/test_demo_schema_vectors.py
uv run --no-sync pytest -q tests/minimal
uv run --no-sync ruff check babeldoc/magazine/demo_schema.py tools/validate_demo_matrix.py tools/tree_state_v1.py tests/minimal/test_demo_sample_matrix.py tests/minimal/test_tree_state_v1.py tests/minimal/test_demo_schema_vectors.py
git diff --check
```

## 9. 主控验收与冻结

主控不得只看 validator exit 0。它必须：

- 复算全部 PDF、authority、config 和 JSON hash；
- 原分辨率查看每条 positive/negative adjudication crop、完整 truth chain、TOC record、title、drop-cap 和 layout x-band；
- 确认 holdout 未参与产品判断，rotation queue 能在每轮换刊物；
- 确认没有把旧 paid detector 输出当 truth；
- 确认 tracked 文件无绝对 materialization path 和 secret；
- 因仓库 `.gitignore` 当前包含 `*.json`，使用精确 allowlist 的 `git add -f -- <Stage00 JSON paths>`；提交前以 `git ls-files --error-unmatch` 逐个证明 matrix、expectations、authority JSON 已实际进入 candidate，禁止对目录或未知文件广泛强制暂存；
- 显式暂存 allowlist，创建 Stage 00 candidate commit；
- 把 `sample_matrix_path/hash`、逐 sample source materialization path/hash、`expectations_manifest_path/hash`、逐 sample expectations path/hash、`paid_gate_matrix_path/hash` 和 `rotation_queue_path/hash` 写入 controller state；runtime status/history 不改变 frozen JSON。

主控 verified 后，Stage 00 的 JSON 全部只读。后续发现标注错误必须回到本计划重新 adjudicate；一旦 hash 改变，Stage 01–06 的 paid 证据全部失效。

## 10. 可接受降级、停止条件与返回

可接受：只冻结 demo 所需页窗；不用建立正式 corpus benchmark；视觉 tolerance 采用明确、可解释的小容差。

不可接受：Courier-only；缺少任一方向；把 fallback 当联合翻译通过；用 detector 反推 truth；复用同一 source 充当 transfer 与 holdout；把 publication-specific 值写入产品/verifier；为凑矩阵伪造不存在的 source 或人工决定。

完成或阻塞后立即返回主控，必须列出：实际输入路径与 hash、选中/拒绝样张及理由、每条 truth transition与negative adjudication evidence、结构覆盖表、生成文件、测试命令与 exit code、`git diff --stat`、`git diff --check`、全部 blocker。不得进入 Stage 01。
