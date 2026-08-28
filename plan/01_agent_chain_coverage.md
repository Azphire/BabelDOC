# Agent 执行计划 01：联合翻译与漏译止血

目标分支：`migration/minimal-v0.6.4`  
起始基线：主控在 `controller-state.json` 下发的 `previous_verified_sha`；首次为包含七份 plan 的 `execution_start_sha`，`04ad1485a34942bb249b5325bb2809ffdba332a2` 必须是其祖先  
执行角色：本项目唯一、持续复用的执行 agent  

## 独立执行契约

- 开始前确认 branch 精确为 `migration/minimal-v0.6.4` 且仅一个 worktree；按 controller state 的 `entry_mode` 验证：`initial` 要求 HEAD=previous verified 且 clean，`dirty_followup` 要求 HEAD=expected HEAD、`allowed_dirty_paths` 精确相等，并用 state 指定且 SHA-256 已验的 helper 复算 `tree-state-v1`（覆盖 tracked staged/unstaged/deleted 与全部 untracked 文件）的 `handoff_tree_state_digest`，`committed_followup` 要求 HEAD=rejected candidate 且 clean。任一不符立即停止。
- 当前 `agent_id` 必须等于 controller state 记录的唯一 executor；不得创建子 agent、branch 或 worktree。
- 确认 `examples/input/Courier-en.pdf` 存在且 SHA-256 为 `9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a`。
- 只修改“允许改动”中的路径；不访问已停止的 C22 工作目录。
- 不接收、读取或使用真实 API key，不启动 paid 请求。
- 不执行 `git add/commit/stash/reset/clean/rebase/amend/push`；主控验收期间保持 idle。
- 失败后只处理主控下发的本阶段 follow-up，不进入下一计划。
- 所有 Python/test/lint 命令使用当前 `.venv` 的 `uv run --no-sync`，cache/temp 只用 `.runtime` 下的独立路径。

## 1. 任务结果

修复连续链对 ArticleIR 整栏 slot 的错误依赖，让同页跨栏、相邻跨页和跨页标题链使用每个 canonical member 自己的源 box 做一次联合翻译与容量回填。任何规划阶段无法完成联合翻译的链必须在普通翻译调度前释放，避免整段保留英文。

本阶段同时解决当前 12 个链成员造成的大段漏译。普通摄影署名、TOC 和非链短标签留给后续阶段。

## 2. 必须先核对的现状

开始修改前实际阅读：

- `babeldoc/magazine/chain_translation.py`
- `babeldoc/magazine/chain_backfill.py`
- `babeldoc/magazine/article_ir.py`
- `babeldoc/magazine/article_builder.py`
- `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py`
- `babeldoc/format/pdf/document_il/midend/typesetting.py`
- `babeldoc/magazine/minimal_pipeline.py::_chain_and_backfill_summary`
- `tests/minimal/test_chain_single_request.py`
- `tests/minimal/test_chain_backfill_capacity.py`
- `tests/minimal/test_translation_invariants.py`

paid 基线必须对应以下事实：

| chain | members | 当前结果 | 错误来源 |
| --- | --- | --- | --- |
| `qKZQ2` | `p2#3,p3#1` | topology failure | 全局 slot order `[0,2]` 被要求连续 |
| `fLx1V` | `p5#4,p5#1` | joint success | 唯一有连续整栏 slot 的链 |
| `YFez2` | `p6#8,p6#3` | no legal slot | p6 被标为 unsupported |
| `bwcA3` | `p6#10,p6#5` | no legal slot | 同上 |
| `YPZu2` | `p7#4,p8#8` | no legal slot | p7/p8 被标为 unsupported |
| `UYUsp` | `p8#12,p8#4` | no legal slot | p8 被标为 unsupported |
| `r5L69` | `p8#7,p8#1` | no legal slot | p8 被标为 unsupported |

表中 raw chain ID 只用于定位这次基线；它由运行时生成，canonical hash 也可能随 subset 本地 refs 改变。测试和 paid 断言必须用物理页、debug/source hash 与 endpoint mapping 定位。

现有 `_plan_chain()` 在 `_preflight_members()` 之前调用 `_claim_chain()`。失败的 12 个成员继续被 cross-page、cross-column 和 page batch 排除，因此 `Paragraphs completed` 只有 `120/132`，并产生 12 个正文/标题 residue。

## 3. 允许改动

产品代码原则上只改：

- `babeldoc/magazine/chain_translation.py`
- `babeldoc/magazine/minimal_pipeline.py` 中与 chain/backfill 汇总语义直接相关的窄范围代码
- `babeldoc/magazine/minimal_detection.py` 中与新 fallback outcome/claim 闭合直接相关的窄范围代码
- `babeldoc/magazine/run_trace.py` 中 chain result/coverage state 的窄范围代码（只有现有 enum 无法表达 fallback 时）
- `tools/verify_minimal_pdf.py` 中 chain/fallback 新 schema 的基础门
- `tools/run_paid_subprocess.py`（首次 paid 前的强制 secret launcher）
- `tools/verify_courier_demo.py`（建立共同 CLI 与 `--check chain` 机器门）

测试可改：

- `tests/minimal/test_chain_single_request.py`
- `tests/minimal/test_chain_backfill_capacity.py`
- `tests/minimal/test_translation_invariants.py`
- 其他直接覆盖 chain claim/report 的 `tests/minimal/` 文件
- `tests/minimal/test_minimal_pdf_validator.py`
- `tests/minimal/test_paid_subprocess_secret.py`
- `tests/minimal/test_courier_demo_validator.py`

必须新增很小的 `tools/run_paid_subprocess.py`，固定 CLI 为 `--log <path> --scan-root <path> -- <child argv...>`，`--` 后严格按 argv list 解析。它用固定 prompt 和 `getpass`/TTY 无回显取 key，`shell=False` 启动，不修改父进程 `os.environ`，只在复制的 child env 中设置 `OPENAI_API_KEY`；创建 UTF-8 log、流式脱敏 stdout/stderr、记录 child PID，并原样传播 child exit code。child 退出后扫描 `scan-root`，命中哨兵/疑似 key 时以非零退出。哨兵测试证明 child 可读，父环境不变、测试创建的 sibling 不继承 key，argv、日志、runtime 文件和 diff 均无哨兵，child 非零退出也不泄漏。不得声称阻止同用户主动读取 child `/proc`；不得增加 provider、配置或兼容框架。

禁止改动 ChainBuilder 阈值、ArticleBuilder 的 unsupported 判定、普通翻译 prompt、detector 阈值、TOC、article flow、标题和首字模块。

## 4. 实现要求

### 4.1 chain member slot

在 `chain_translation.py` 内增加只供本模块使用的薄 slot adapter。字段至少包括：

```text
article_id
source_ref
page
column
slot_order
box
```

`_preflight_members()` 保留以下硬检查：

- 至少两个唯一 member；
- `chain_index` 为 `0..n-1`；
- 用 `page.page_number + 1` 的物理页标签检查不倒退且只跨同页/相邻页；`page_index`/`SourceElementRef.page` 在 subset run 中仍可能是本地页号；
- 所有 member 的 `by_element` owner 唯一且相同；同一物理页可以包含其他 article；
- canonical chain/member/owner 一致；
- canonical element 存在，`source_box` 有限且面积为正；
- member 的 canonical reading order 严格递增。

删除现有“整页 `by_page` owner 必须等于链 owner”的前提；链归属以所有 member 的 `by_element` 同属一个 article 为权威。

slot 部分改为：

1. 从 canonical article 的 `elements` 按 `source_ref` 取 `SourceElementRef`。
2. 每个 member 用自己的 `source_box` 建一个 slot。
3. slot order 按 chain index 重新编号为 `0..n-1`。
4. 允许 canonical reading order 中间存在无关元素。
5. 不查询 `article.slots`，不要求全局 slot order 连续，不因整页 `unsupported` 拒绝链。
6. adapter 继续保存 canonical article owner、chain order 和 source ref，不能退化为任意 bbox 回填。
7. report 同时保存本地 ref/page 与物理页标签或等价稳定 endpoint evidence，保证 `--pages` 子集可验收。

继续复用现有 `Typesetting.fit_text_to_slot`、placeholder protection、`merge_chain_text`、target allocation 和原子 writeback。fragment 写回 box 必须保持 member source box，禁止扩大成整栏 union box。

### 4.2 claim 生命周期与 coverage fallback

达到以下行为即可，具体采用延迟 claim 或 freeze 前原子 give-back 由执行 agent选择最小改法：

- 只有能进入 `JOINT_SUCCESS` 的链成员在普通 producer 开始前保持 active claim。
- preflight、prepare、token、placeholder、API response 或 allocation 的规划阶段失败时，所有 member 在 claim freeze 前恢复为普通可调度状态。
- 普通 producer 对每个释放 member 最多接管一次，不能同时进入两个普通请求。
- planning 只先记录 `fallback_ordinary_pending`/等价 typed 状态；普通 executor 与 `short_unit.apply()` 都完成后再确认 `fallback_ordinary_translated` 或 `uncovered`，并记录失败原因和各类 call count。short-unit 接管的 member 记录 `ordinary_producer=short_unit`。
- ordinary fallback 不得伪装成 joint success。
- joint 成功链仍由普通 cross-page、cross-column 和 page batch 全部排除。
- fallback member 从 active claim 中原子移除，不进入最终 chain skips；detector 的 claimed refs 只来自普通 producer 实际拒绝过的 active claim。
- late apply/writeback 失败继续原子回滚并报告，并直接使本阶段 gate 失败；普通 executor 此时已结束，禁止声称 ordinary fallback。

更新旧注释和 docstring 中“失败链永久保护”的约定。

### 4.3 汇总不变量

将联合翻译与内容覆盖分开汇总：

- `single_request_holds` 检查每个 `joint_success` 恰好一次成功请求，成功 joint request 数等于 joint success 数。
- failed attempt calls 单独计数，`attempted = successful + failed_attempts`；API 已消费后再 ordinary fallback 允许产生第二个 ordinary request，两个 request 类别不得混计。
- 另行记录 detected、joint success、fallback ordinary、failed late、claimed member 和 released member 计数。
- `coverage_holds` 要求每个 chain member 最终属于 joint target、ordinary target 或显式 intentional preserve；`protected_untranslated` 不得通过。
- `target_conservation_holds` 只对 joint success 的完整译文与回填 fragments 做严格拼接检查。

不得修改 detector 来隐藏失败。

同时建立 Courier 专用共同机器门 CLI：`--check <chain|toc|layout|title|dropcap|full> --source <pdf> --output <pdf> --run-dir <work/Courier-en> --render-dir <dir> --pages <逗号物理页> [--gate-output <json>]`。本阶段实现 `chain`；未传 `--gate-output` 时写 `<run-dir>/courier_demo_gate.<check>.json`，显式传入时只向该精确路径写 gate，且不得写回只读 `run-dir`。gate failure exit 1、I/O/usage/不可写 output exit 2；后续计划只扩展对应 check，不另建脚本。

## 5. 离线测试

至少新增以下场景：

1. `unsupported_pages` 且 `article.slots=()`：同页链和跨页链各一次请求、一次 writeback、target 拼接守恒、member box 不变。
2. ArticleIR 全局 slot order `[0,2]`：member reading order 合法时通过。
3. ChainBuilder 与 ArticleBuilder column 编号不一致：canonical refs 和 source boxes 有效时通过。
4. 标题 target 可全部容纳第一个 member：第一个 fragment 持有完整 target，第二个为 trailing released，文本守恒。
5. malformed reply、placeholder damage、token overflow、capacity failure：释放 active claim，`_plan_short_units` 与普通 page/cross-page producer 能重新发现 member，最终逐 member 只接管一次。
6. joint success：普通三条 producer 均拒绝 claimed member。
7. late atomic writeback failure：恢复所有 source members并保留 issue。
8. 同页含多个 article、但 chain members 同属一个 article：preflight 通过。
9. joint API 已产生失败 attempt 后 ordinary fallback：两类 request 分开计数且总式闭合。
10. subset run：本地 ref 重编号，但 physical page/endpoint 仍正确，邻接与 paid assertion 不错配。
11. fallback outcome refs 不进入 chain skips，updated validator 接受 typed fallback、拒绝 uncovered。
12. 现有 hyphen merge、placeholder order、capacity measurement 和 reconstruction 测试继续通过。

建议门：

```text
uv run --no-sync pytest -q tests/minimal/test_chain_single_request.py
uv run --no-sync pytest -q tests/minimal/test_chain_backfill_capacity.py
uv run --no-sync pytest -q tests/minimal/test_translation_invariants.py
uv run --no-sync pytest -q tests/minimal/test_detectors.py
uv run --no-sync pytest -q tests/minimal/test_structure_real_pdf.py
uv run --no-sync pytest -q tests/minimal/test_minimal_pdf_validator.py
uv run --no-sync pytest -q tests/minimal/test_paid_subprocess_secret.py
uv run --no-sync pytest -q tests/minimal/test_courier_demo_validator.py
uv run --no-sync pytest -q tests/minimal
uv run --no-sync ruff check babeldoc/magazine/chain_translation.py babeldoc/magazine/minimal_detection.py babeldoc/magazine/minimal_pipeline.py babeldoc/magazine/run_trace.py tools/verify_minimal_pdf.py tools/run_paid_subprocess.py tools/verify_courier_demo.py tests/minimal
git diff --check
```

执行 agent 不运行 paid job。所有测试使用 fake translator 或离线结构 fixture。

## 6. 主控 paid 验收规格

主控在本阶段离线门通过并创建 candidate commit 后，使用新 run root 和 `--ignore-cache` 分两次跑：

每个 run 在基础 validator 后执行可复制机器门：

```text
uv run --no-sync python tools/verify_courier_demo.py --check chain --source <source.pdf> --output <output.pdf> --run-dir <run>/work/Courier-en --render-dir <run>/render --pages <2,3 或 6,7,8>
```

只有 exit 0 才进入下述视觉验收。

### p2–p3

- 以物理页 2/3、debug/source hash 和 endpoint mapping 定位旧全量别名 `p2#3,p3#1`，对应 canonical chain 只有一个成功 translator call。
- 两个英文 title member 得到一份完整中文 target。
- target 优先装入第一个 title source box，后一个 holder 可 trailing release。
- `p2#3,p3#1` 不再产生 title residue。

### p6–p8

- 按物理页 endpoint mapping 定位旧全量 refs 的五条 canonical chain，尽可能全部 joint success，不依赖 raw ID 或 subset 本地 ref。
- 每条成功链恰好一个 translator call，回填 fragment 拼接等于完整 target。
- p6 四块、p7 一块、p8 五块大段英文全部消失。
- 每个 allocation box 等于对应 canonical source box。
- 若某链进入 ordinary fallback，报告必须给出原因，成员都有普通译文且只消费一次。

全阶段首选结果：7 条 canonical chain 最终在整本 run 中全部 joint success。最低 demo floor：p2–p3 标题链、至少一条同页跨栏正文链、至少一条跨页正文链为 joint success，其余链可 typed ordinary fallback，但不能漏正文。

## 7. 可接受降级与停止条件

可接受：

- source box 缺失或 canonical owner 真冲突时回到普通翻译；
- API/placeholder/容量 failure 在报告收窄清单中标为 demo ordinary fallback，并可产生一次额外普通请求；
- 目标语较短时 trailing member 为空并标记 released；
- p4 中未被 detector 建链的接缝暂不调整，只要两段均完成普通翻译。

不可接受：

- 保留 `protected_untranslated` 的正文或标题；
- 用普通 batch 冒充 joint request；
- 为了通过而放宽 chain detector/report；
- 用整栏 ArticleIR slot 改写 member box；
- 在本阶段修普通 article reflow 或页面专用逻辑。

## 8. 返回主控

完成离线门后立即返回，不进入下一阶段。返回内容必须含：

- 改动文件清单；
- preflight/slot/claim/report 的行为差异；
- 新增和更新的测试；
- 每条测试命令及 exit code；
- 当前 `git diff --stat`、`git diff --check` 结果；
- 建议主控核看的 report 字段和页区；
- 所有未解决的 chain outcome。

保留未提交工作树，由主控审查、暂存、提交和执行 paid/视觉门。
