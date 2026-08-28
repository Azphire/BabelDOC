# 主控执行计划：Courier report demo 最小修补

计划版本：2026-08-28  
目标分支：`migration/minimal-v0.6.4`  
审查基线：`04ad1485a34942bb249b5325bb2809ffdba332a2`  
执行拓扑：一个主控 + 一个持续复用的执行 agent + 一个 branch + 一个 worktree  

## 1. 目标和固定取舍

本轮只把 Courier 英译中样张修到可支撑报告展示。优先级依次为：不漏正文、联合翻译成立、源网格不被破坏、TOC/标题/首字可见。暂不处理发布、兼容、恢复、通用配置、全语料稳定性和完整文章重排。

固定取舍如下：

- 普通正文停用 `article_flow`，继续在原 paragraph box 内排版，允许译文变短后留白。
- 连续链仍可在自身相邻 member box 中做一次联合翻译和容量回填。
- TOC 复用已有 `line_split.py`，只保证视觉行/记录边界，不追求 leader dots 的像素级对齐。
- 中文标题复用已有 `title_typeset.py`，选定 demo 标题必须单行；低于可读字号下限的其他标题可报告降级。
- 首字复用现有 keep/flatten、intent 和 renderer，只修生产字形度量。
- 联合链在 claim freeze 前的 planning failure 回到普通翻译，任何失败链均不得造成静默漏译；apply/writeback 的 late failure 直接阻断阶段门。
- C22 已停止，不再作为依赖、门禁或等待条件。

## 2. 已核对的需求与基线事实

`main(3).tex` 的任务定义要求三项同时成立：翻译正确、版面可用、内容守恒。方法章节明确要求 ArticleIR 的源—译—渲染映射、连续链一次联合翻译、目标语容量回填、TOC/记录型文字使用角色政策、页面/术语/首字三类 HITL 决定、固定页面网格、LLM 受限规划和最终缺陷核查。用户本轮追加两个具体 demo 条件：单行 TOC 不得合并相邻视觉行；英译中标题应优先排为单行。

现有 paid Courier 结果已逐页核查：

| 缺陷 | 当前证据 | 根因 |
| --- | --- | --- |
| 大段漏译 | 16 个 residue，其中 12 个是失败链成员 | `_plan_chain` 预检前 claim，失败后仍阻止普通翻译 |
| 联合翻译 | 7 条链仅 1 条成功 | chain preflight 错用整栏 ArticleIR slot；unsupported 页没有 slot |
| p5 三栏塌成单栏 | 6 个正文段落进入一个宽槽 | 通栏导语与首栏正文被 union 后交给 `article_flow` |
| TOC | 标题、页码、作者相粘 | `line_split.py` 已存在但未接入固定流水线 |
| 跨页标题 | p2/p3 两段英文残留 | 标题链被 slot order `[0,2]` 拒绝；`title_typeset.py` 未接入 |
| 首字 | 3 个 keep 候选全部回滚 | PyMuPDF 的全字体 bbox 被当成逐字 bbox |

固定输入：

- `Courier-en.pdf`：8 页，SHA-256 `9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a`。
- paid 基线结果：`chains=7`、`merged=1`、`escalated=6`、`dropcap set=0/reverted=3`、p5 `placements=6`。
- 每次执行前由主控重新确认输入 hash；输入 PDF 不提交到 Git。

当前 TeX 有四组表述高于本轮 demo：

- 普通文章级跨容器重排关闭，需要收窄 RQ2、贡献 3 和 3.4 节。
- 当前 `minimal_repair.repair_once` 是确定性单动作检测—修复—重检，没有 TeX 中的 LLM autonomic manager、结构化工具选择和完整动作空间，需要收窄 RQ3、贡献 4 和 3.5 节。
- 最低 chain floor 允许非代表链 `fallback_ordinary`，低于 3.3.1 对所有连续链联合处理及 placeholder 失败保守路径的表述。
- 本轮只验证 Courier 英译中 demo，不产生 LOPO、MQM、LTCR、Overlap/Alignment 等正式实验结果，也不验证完整中译英范围。

本轮保留 ArticleIR、代表链 joint translation、三类 HITL 送达证据、确定性 detection/repair sidecar 和最终人工验收；上述报告收窄项不阻塞代码 demo。

## 3. 角色边界

### 主控

主控只做调度、独立验收、paid 运行、视觉检查和 Git 操作：

1. 启动时只创建一个执行 agent，后续所有阶段复用该 agent。
2. 每次只下发一份完整 agent plan，禁止并行产品代码修改。
3. agent 返回后检查 diff，独立运行离线门。
4. 离线门通过后由主控显式暂存允许路径并创建 candidate commit；这是主控唯一允许的产品工作树写操作，主控不编辑产品文件。
5. 需要 paid 的阶段由主控持有 API key 并运行；执行 agent 不接触 key。
6. 主控亲自打开渲染页，记录通过/失败理由。
7. 通过后把 candidate SHA 标记为 verified，立即下发下一份 plan。
8. 失败后把命令、日志、report、截图和精确断言发回同一 agent，继续当前阶段。

### 唯一执行 agent

执行 agent 负责只读定位、最小实现、聚焦测试和自检。它不得：

- 创建子 agent、branch 或 worktree；
- 使用真实 API key 或启动 paid 请求；
- 修改本阶段允许路径之外的文件；
- 执行 `git add`、`git commit`、`git stash`、`git reset`、`git clean`、rebase 或 force push；
- 提前进入下一份 plan。

每次返回必须列出：改动文件、关键行为、测试命令与 exit code、未解决项、建议 paid 页范围。工作树保留给主控验收。

## 4. 阶段顺序

严格串行执行：

1. `01_agent_chain_coverage.md`：修联合翻译 slot 与失败 claim，先消除大段漏译根因。
2. `02_agent_toc_structure.md`：把 TOC 行/块结构恢复接入翻译前路径。
3. `03_agent_conservative_layout.md`：固定 demo 路径关闭普通 article reflow，保住 p5 三栏。
4. `04_agent_title_typeset.md`：接入中文标题单行排版。
5. `05_agent_dropcap_render.md`：修真实字形度量并提交三处首字。
6. `06_agent_demo_completeness.md`：建立 Courier 专用完整性门和最终报告汇总。
7. 主控完成一次整本 paid 验收；失败项回到所属阶段，全部通过后结束。

阶段 3 必须先于阶段 5 完成，避免 p5 box 改动后重复调首字。阶段 1 必须先于阶段 4，确保标题已经有中文 target。

## 5. 每阶段状态机

```text
READY
→ EXECUTING
→ AGENT_HANDOFF
→ OFFLINE_GATE
→ CANDIDATE_COMMIT
→ PAID_GATE（需要时）
→ VISUAL_GATE（需要时）
→ VERIFIED
→ NEXT_PLAN
```

失败路径：

```text
GATE_FAILED
→ 保存失败证据
→ follow-up 同一 agent
→ AGENT_HANDOFF
→ 重新验收
```

600 秒仅是一轮观察窗口。主控把 `agent_id`、stage、previous/candidate SHA、`entry_mode`、`expected_head_sha`、`allowed_dirty_paths`、`handoff_tree_state_digest`、`tree_state_digest_version`、`tree_state_digest_helper_path`、`tree_state_digest_helper_sha256`、当前 actor、run root、页范围、脱敏命令摘要、session/child PID、开始/最近轮询时间、日志 size/mtime、`request_may_be_billed` 和 next action 写入 `.runtime/demo-repair/controller-state.json`；禁止记录 key、key hash 或 key 片段。长任务每 60 秒内检查一次进程/agent 与日志进展；600 秒到点仍有进展则继续等待同一任务，不 interrupt、不重启、不创建替代 agent。paid 状态不明时标记可能计费并停止自动重跑。

agent 入口有三种：`initial` 要求 HEAD=previous verified 且 clean；`dirty_followup` 要求 HEAD=expected HEAD，dirty paths 与 `tree-state-v1` digest 精确匹配 controller state；`committed_followup` 要求 HEAD=rejected candidate 且 clean。主控每次 follow-up 都显式设置一种，agent 不自行猜测。

## 6. 初始化与 Git 门

首次启动：

1. 七份计划必须先形成一个 docs-only 干净提交，或移出产品 worktree；记录 `code_review_baseline=04ad1485a34942bb249b5325bb2809ffdba332a2` 和 `execution_start_sha`，并确认前者是后者祖先。首次 previous verified SHA 使用 `execution_start_sha`。
2. 确认 branch 为 `migration/minimal-v0.6.4`，HEAD 为 execution start 或上一 verified SHA。
3. 确认只有一个 worktree，工作树干净且没有来源不明提交。
4. 运行一次 `uv sync`；仓库没有受控 `uv.lock`，禁止使用 `uv sync --frozen`。
5. 后续命令使用 `uv run --no-sync`。
6. 保存 Python、uv、PyMuPDF 和依赖快照到 `.runtime/demo-repair/bootstrap/`。
7. 把用户附件放到忽略路径 `examples/input/Courier-en.pdf`，重验 SHA-256 `9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a`；禁止提交该 PDF。
8. 把旧 paid 附件复制到忽略路径 `.runtime/demo-repair/fixtures/paid.zip`，重验 SHA-256 `bfddf9258bbd65e996de2e041623faba8fafb5ad6c946d510e34d768a3e3660a`，一次性解包到新的 `.runtime/demo-repair/fixtures/paid-bfddf9258bbd/`。解包后设为负例只读证据；在 controller state 以 `paid_fixture_archive`、`paid_fixture_root`、`old_output_pdf`、`old_work_courier_dir` 记录四个精确绝对路径，禁止阶段 agent 回退到 `upload/`、递归猜路径或改写 fixture。
9. 设置独立的 `.runtime/uv-cache`、`.runtime/babeldoc-cache`、TEMP/TMP/TMPDIR；不清理旧运行证据。当前 `Initialize-MigrationRuntime.ps1` 含固定 Windows 路径，本轮不调用。

`dirty_followup` 的工作树摘要固定为 `tree-state-v1`，不得用普通 `git diff` hash 代替：

1. 主控在首次 agent 启动前把唯一 helper 放到 `.runtime/demo-repair/bootstrap/tree_state_digest_v1.py`，在 controller state 记录其绝对路径和 SHA-256；主控与 agent 都只能调用这一个已验 hash 的 helper。
2. helper 以 controller state 的 `expected_head_sha` 为基线，用 `git -c status.renames=false status --porcelain=v1 -z --untracked-files=all` 枚举 tracked staged/unstaged/deleted 和全部 untracked 文件；拒绝 unresolved merge、submodule 和 unsupported special file。
3. 按原始相对路径字节做 C-locale 升序和去重。每项向 manifest 写入 `path NUL XY-status NUL type NUL mode NUL index-object-id NUL content-sha256 NUL`：`type` 仅为 `file/symlink/deleted`；现存对象用 `lstat` mode，删除项用基线 tree mode；普通文件 hash 原始 bytes，symlink hash 原始 link-target bytes，删除项写 `-`；未跟踪项的 index object id 写 `-`。路径本身禁止 Unicode/换行规范化。
4. manifest 以 `tree-state-v1 NUL expected-head-sha NUL` 开头；最终 `handoff_tree_state_digest=SHA256(manifest)`。helper 同时输出排序后的 path 清单，主控把它与 `allowed_dirty_paths` 精确比较。
5. bootstrap 自测必须分别改变 tracked worktree、staged index、tracked delete、untracked regular file 和 untracked symlink，证明任一状态/内容/mode 变化都会改变 digest；相同状态重复计算必须一致。helper 或自测不通过时禁止进入 agent 阶段。

agent handoff 时由 agent 先计算一次，主控在 agent idle 后用同一 helper 复算；两者 digest、path 清单、HEAD 和 helper SHA 必须全部一致。这样新建但尚未 `git add` 的 verifier/tests 也进入续作证据。

每阶段开始记录：

```text
previous verified SHA
branch / HEAD / git status
worktree list
输入 PDF 与配置 hash
阶段名与允许改动路径
```

agent 返回后主控执行：

```text
git status --porcelain=v1
git ls-files --others --exclude-standard
git diff --stat
git diff --name-status
git diff --check
uv run --no-sync pytest -q <聚焦测试>
uv run --no-sync pytest -q tests/minimal
uv run --no-sync ruff check <改动 Python 文件>
```

主控先确认所有 changed/untracked path 均在本阶段 allowlist，再逐路径执行 `git add -- <path...>`，随后运行 `git diff --cached --name-status` 和 `git diff --cached --check`；staged 集合必须精确等于已验收集合。创建 candidate commit 后，`git status --porcelain=v1` 必须为空，并用 `git show --name-status --format=fuller HEAD` 复核提交内容，才可进入 paid。测试或视觉失败时保留 rejected candidate 和证据，把失败包发给同一 agent；agent 在当前 HEAD 上向前修复，主控创建新的 fix commit，禁止 amend 已验收过的 SHA。只有尚无下游 candidate 且明确放弃整个阶段时，主控才对列明的 stage commits 执行 `git revert`；已有下游提交后只允许向前修复并按依赖重跑门禁。继续禁止 reset、clean 和 stash。

## 7. 运行目录与 paid key

每次门禁创建新目录：

```text
.runtime/demo-repair/<stage>/<UTC>-<short-sha>/
  work/
  output/
  temp/
  logs/
  render/
  gate.json
```

`working-dir` 会追加输入 stem。不要复用父 run root，否则 validator 可能读到多个 report。

用户给主控的 API key 只进入 BabelDOC 子进程环境：

- 不写入命令行、TOML、脚本、日志、测试、Git 或全局 shell 环境。
- 不把 key 转发给执行 agent。
- 计划 01 必须先交付使用 `getpass`/TTY 无回显读取的小型 launcher；launcher 复制环境后只给目标 child 增加 `OPENAI_API_KEY`，输出脱敏命令和 child PID。launcher 与 secret-isolation 测试未通过时禁止 paid。
- 退出后扫描本阶段 argv、日志、配置和 `git diff`，确认 key 没有落盘。

只在唯一执行 agent 已创建、candidate 已提交且 agent idle 后向用户索取 key。key 进入主控上下文后不再 spawn/fork 新 agent；任何 follow-up 失败包先对 key 精确脱敏。启动 launcher 必须分配 PTY，等待固定 prompt 后通过既有 session stdin 发送 key；无法获得 TTY 时立即停止，禁止降级为 argv、普通 pipe 或全局环境变量。

每次 paid 命令都带：

```text
--no-dual
--no-auto-extract-glossary
--skip-scanned-detection
```

翻译语义发生变化的阶段加 `--ignore-cache`。纯排版阶段可复用翻译缓存，并在 gate 记录 cache hit 情况。不要使用 `--only-include-translated-page`，输出必须保留完整 8 页和物理页映射。

`--pages` 使用 1-based 物理页，支持 `2-3`、`4,5,7`；`working-dir` 会追加 `Courier-en`。每次 run root 名含 stage、UTC、candidate SHA、页范围和随机后缀。规范 argv 形态：

```text
uv run --no-sync python tools/run_paid_subprocess.py
  --log <run>/logs/babeldoc.log
  --scan-root <run>
  --
  uv run --no-sync babeldoc
  --config <repo>/minimal.en-zh.toml
  --files <repo>/examples/input/Courier-en.pdf
  --pages <physical-pages>
  --working-dir <run>/work
  --output <run>/output
  --no-dual
  --no-auto-extract-glossary
  --skip-scanned-detection
  [--ignore-cache]
```

基础门紧随 CLI：

```text
uv run --no-sync python tools/verify_minimal_pdf.py
  --source <repo>/examples/input/Courier-en.pdf
  --output-dir <run>/output
  --run-dir <run>/work
  --translated-pages <逗号分隔物理页>
```

validator 的 `--translated-pages` 只接受逗号整数，例如 `2,3`；整本为 `1,2,3,4,5,6,7,8`。主控再运行该阶段的机器断言和 PDF render，不以自然语言检查替代 exit code。

## 8. 定向 paid 门

| 阶段 | 页范围 | 硬检查 | 视觉检查 |
| --- | --- | --- | --- |
| 1 联合翻译 | `2-3`、`6-8` 两个独立 run | exemplar chain 单请求；失败成员能普通翻译；无正文/标题 residue | p2 标题已有中文 target；p6–p8 无大块英文条带 |
| 2 TOC | `1` | `line_split.report.json` 有 split；记录未跨视觉行 | 左侧目录行独立，右侧 Editorial 未逐行碎裂 |
| 3 保守布局 | `5` | `article_flow` typed no-op，0 placement | 通栏导语下保持三条正文 x-band |
| 4 标题 | `2-3` | report 为 `single_line` 或合法单行 `unchanged` | 完整中文标题只在主标题区显示一行 |
| 5 首字 | `4,5,7` | 3 个 keep 均 committed | p4、p5、p7 首字可见；p5 仍为三栏 |
| 6 最终 | 整本 8 页 | Courier 专用完整性门全通过 | 8 页缩略图 + 风险区原分辨率复核 |

阶段 1 的首选目标为 7/7 canonical chain 全部 joint success。为了尽快交付，允许的最低 demo floor 为：至少一条同页跨栏正文链、一条跨页正文链和 p2–p3 标题链各自一次请求且守恒；其余失败链必须显式 `fallback_ordinary`，正文不得留英文。是否接受 floor 由主控在证据齐全后记录，禁止执行 agent自行放宽。

## 9. 最终硬验收

整本 paid run 只在计划 01–05 verified、计划 06 candidate 已通过独立离线门后启动；paid、完整 verifier 和视觉门通过后才把计划 06 candidate 标记为 verified。主控要求：

- 输出可重新打开，仍为 8 页，页面尺寸和固定图像不变。
- p1 左侧单行目录逐视觉行翻译，紧密多行 TOC 按块翻译；右侧 Editorial 保持普通长正文；页码/作者不粘到相邻条目。
- p2–p3 标题链生成一次完整中文译文，demo 标题为单行；第二个源标题 holder 可被 trailing release。
- p5 通栏导语下仍是三栏，普通 article flow 为 0 placement。
- 至少一个跨栏正文链和一个跨页正文链为 `joint_success`，每链恰好一次 translator call，回填 target 守恒。
- 所有 translate-eligible 的正文、continuation、plain text 和 title 均有 translated/joint/fallback 的显式状态；不存在无状态遗漏。
- `issues.after` 中无正文或标题 `untranslated_residue`；摄影署名等保留英文只能以显式 `intentional_preserve` 通过。
- `article_ir.json`、article map、article context 和 source→target→render coverage sidecar 存在且映射闭合；独立 source PDF 文本块 inventory 无未解释的大块缺失。
- HITL review/decision 引用仍匹配 source，page kind、3 个 drop-cap、glossary decisions hash 与实际条目数（当前基线 14）均送达，样张中出现的术语最终译法合规。
- `issues.before/after`、typed repair/no-op、重检和残余问题清单完整；该证据只代表确定性 minimal repair。
- title pass 之后再次确认 TOC record 数、视觉 band 和右侧 Editorial 未回归。
- p4、p5、p7 三个 keep 首字均 committed；任何 typed rollback 均算失败。
- 无新增越页、碰撞、文字/固定资产漂移。p1 logo 若在 source 已越界且未漂移，记录为 baseline condition；只有译后新增或恶化的 heading 越界才回到标题阶段。
- 主控打开全部 8 页缩略图，并以原分辨率检查 p1、p2–p3、p5、p6–p8。

每个 verified gate 保存 candidate SHA、命令、exit code、报告、PDF hash、PNG、视觉结论和 secret 扫描结果。CLI exit 0、PDF 文件存在或 `minimal_run.report.status=complete` 单独均不构成通过；必须同时通过 verifier 和视觉门。

## 10. 结束条件

满足最终硬验收后，主控：

1. 确认工作树干净、一个 worktree、HEAD 等于最终 verified SHA。
2. 输出按阶段的 verified SHA 和 paid evidence 路径。
3. 汇总已接受的降级：普通文章不跨容器重排、TOC 点线允许近似、非 demo 极端标题可换行、三个 Courier 目标之外的复杂首字可回滚。
4. 单列 TeX 尚需收窄的文章级重排、LLM planner、fallback chain 和正式评价表述，不在本轮修改论文。
5. 停止，不追加发布、兼容或重构工作。
