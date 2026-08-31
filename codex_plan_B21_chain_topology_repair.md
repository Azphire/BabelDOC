# Codex Plan B21：FD-zh p5 chain topology 前置检测—决策—修复

## 0. 执行方式

本文件是一份可直接交给 Codex 执行的完整计划。执行者必须完整读取后再开始。

- 仓库：`Azphire/BabelDOC`
- 分支：`migration/minimal-v0.6.4`
- 已知起点：`c2d514b`（若远端已有更新，以 `git pull --ff-only` 后的 HEAD 为准）
- 输入：`examples\input\fd-zh.pdf`
- B21 输出根目录：`examples\output\B21`
- 报告证据目录：`docs\reports\B21`
- 方向：中文到英文，配置 `minimal.zh-en.toml`
- 执行环境：Windows PowerShell、仓库内 `.venv`、仓库根目录 `.env`
- 执行模型：单一 Codex 执行者；不启用子 agent、不建立新 branch、不建立 worktree

本批只处理 FD-zh p5 的 chain topology 释放。先完成代码与两个 focused tests，随后只跑
p5。p5 达到门槛后，记录修复过程，再运行一次完整 fd-zh。样张运行不请求人工授权，
直接加载 `.env` 并调用现有翻译 API。

------

## 1. 目标与已知事实

### 1.1 目标缺陷

FD-zh 物理 p5：

- `p5#6` 末尾：`而全球金融危机之后的情况与严重萧`
- `p5#7`：`条毫无二致。`
- 正确 chain 顺序：`p5#6 → p5#7`
- B20 结果：chain 已形成，joint translation 在 preflight 被释放，`p5#7` 随后单独翻译为
  `The条毫无二致。`

### 1.2 B20 已确认的代码事实

1. `ChainBuilder` 已接纳上述边，记录为 `linked=true`、`pairing=intra_column`。
2. 该 p5 边的 `score=null`。它由非终止标点、样式一致、clear head、唯一最近邻等硬门槛
   接纳，不能用“数值 score 超过阈值”作为本次 LLM 入口。
3. `ArticleIR` 将 `p5#7` 排为 reading order 184、`p5#6` 排为 191。
4. `chain_translation.ChainPlan._preflight_members()` 因 `[191, 184]` 返回
   `invalid_chain_topology`，`translator_call_count=0`。
5. joint allocation 已按 chain member 顺序创建 `slot_order=0,1`，并使用每个成员自己的
   source box。只要确定性准入允许继续，现有分配器可以按 `p5#6 → p5#7` 安全工作。
6. 当前 post-layout `repair_loop.py` 执行得太晚；`reallocate_chain_cut` 只重切已有 whole
   target，不能处理 `translator_call_count=0` 的 chain。
7. `detectors/escalation.py` 与 `decision_rounds.json` 中虽有 `chain_escalation` 骨架，minimal
   detector 没调用该 detector，repair action vocabulary 也没有可重新联合翻译的动作。
   本批不得把这段未接通的骨架描述成现有能力。

### 1.3 本批目标

在普通段落翻译之前增加一个只处理 reading-order inversion 的单轮结构修复回路：

1. **检测**：preflight 把“其余结构条件全部通过、仅 reading order 反转”的情况转成类型化
   `chain_topology_conflict`。
2. **决策**：把成员原文、显式边界和拼接原文交给外接 LLM；闭集动作只有
   `confirm_joint_chain` 与 `no_op`。
3. **确定性准入**：仅允许 `reading_order_inversion` 进入动作；任何其他 topology 错误仍关闭。
4. **修复动作**：`confirm_joint_chain` 允许当前 ChainPlan 继续已有的 joint translation 与
   slot allocation；不重写全局 ArticleIR。
5. **复检**：排版后的现有 `chain_conservation`、residue detector 和视觉检查验证结果。

该回路只运行一轮，不增加通用迭代器，不引入第二套 repair controller。

------

## 2. 范围红线

### 2.1 允许修改

- `babeldoc/magazine/chain_translation.py`
- 一个新的小模块：`babeldoc/magazine/chain_topology_repair.py`
- 一个新的 focused test 文件：`tests/minimal/test_chain_topology_repair.py`
- 成功后的报告文件：`docs/reports/B21/repair_process.md`
- 成功后的三张报告图片：
  - `docs/reports/B21/fd-p5-source.png`
  - `docs/reports/B21/fd-p5-before-b20.png`（仅在 B20 PDF 仍存在时生成）
  - `docs/reports/B21/fd-p5-after-b21.png`
- 本计划文件本身

`chain_topology_repair.py` 只承载 issue、闭集决策解析、确定性准入结果和审计 record；
`chain_translation.py` 保留成员准备、joint translation、allocation 和最终 outcome。不得再拆分更多
框架文件。

### 2.2 禁止修改

- 不改 `article_builder.py` 的全局 column/read-order 算法。
- 不改 `repair_loop.py`、`minimal_repair.py` 的 post-layout 动作。
- 不接通或重构未使用的 `detectors/escalation.py`。
- 不改 page classifier、element classifier、TOC、drop cap、article flow、tail fill。
- 不修 p3 `translation_owner=ordinary` 的报告归属问题；本批只要求 p3 文本继续译成
  `Editor's Note`。
- 不增加开关、兼容层、迁移逻辑、发布测试、部署文件、symlink、tree-state 或父目录 fsync。
- 不加入 fd-zh、p5、`p5#6`、`p5#7`、具体坐标或具体中文句子的产品硬编码。
- 不改变其他 `invalid_chain_topology` 的关闭行为。
- 不运行完整 pytest 套件，不扩大到其他语料。
- 不删除或覆盖已有 B20/B21 文件；发现同名非空 B21 目录时先停止并报告。

### 2.3 调用与运行上限

- focused tests：两个 nodeid，一次统一调用。
- p5 样张：一次。
- 完整 fd-zh：仅在 p5 成功后运行一次。
- topology decision：每个 eligible conflict 最多一次 LLM 调用，无格式重试。
- topology decision 与 joint translation 分开计数。
- 样张门失败后立即停止，不补跑、不顺手修改其他问题。

------

## 3. T0：执行前核对

在仓库根目录执行：

```powershell
git branch --show-current
git pull --ff-only
git status --short
git log -5 --oneline
```

门槛：

- 当前 branch 必须是 `migration/minimal-v0.6.4`。
- `b15c466` 与 `c2d514b` 必须在当前历史中。
- 允许本计划文件处于未提交状态；任何其他与目标文件重叠的本地修改都触发停止。
- `examples\input\fd-zh.pdf`、`minimal.zh-en.toml`、`.venv\Scripts\babeldoc.exe`、`.env`
  必须存在。
- `examples\output\B21` 若已存在且非空，停止并列出内容；不得清空或覆盖。
- 读取 `.env` 后只检查 `OPENAI_API_KEY` 是否非空，禁止打印值。

只做一次上述核对。后续不反复执行 pull/status 来代替开发判断。

------

## 4. T1：实现翻译前 topology 检测—决策—修复

### 4.1 精确插入点

现有顺序保持：

1. `_collect_chains()` 按 `chain_index` 收集成员。
2. `_preflight_members()` 验证结构并创建 member source slots。
3. `_prepare()` 生成真实翻译输入与 placeholder 信息。
4. `backfill.merge_chain_text()` 生成 joint source。
5. `_translate()` 发起 joint translation。
6. `_allocate_target()` 分配 whole target。

修改点：

- `_preflight_members()` 遇到 reading order 反转时不立即把整个 chain 释放。
- 它返回一个带 `TopologyConflict` 的 `ChainPreflight`；其余结构错误仍按原路径返回
  `invalid_chain_topology`。
- `_plan_chain()` 完成 `_prepare()` 与 `merge_chain_text()` 后、joint translation 前，调用
  topology 单轮回路。
- 只有 `confirm_joint_chain` 且通过确定性准入时继续 `_translate()`。

### 4.2 类型化检测记录

新增最小不可变数据结构，至少包含：

- `kind = "chain_topology_conflict"`
- `subtype = "reading_order_inversion"`
- runtime chain id 与 canonical chain id
- article id
- ordered runtime/physical source refs
- chain indices
- ArticleIR reading orders
- 每个 member 的 source fragment
- `merge_chain_text()` 产生的 merged source
- `builder_accepted = true`
- 原始 detail，例如 `chain members do not follow canonical reading order: [191, 184]`

“builder accepted”已覆盖两类上游接纳：

- 数值 score 已通过 `link_min_score` 的边；
- `score=null`、通过确定性硬门槛的边。

本批不要为了重新读取 score 而解析 `chain_report.json`，也不要向 IL 增加 score 字段。

### 4.3 LLM 决策协议

复用当前 `translator.translate_engine.llm_translate()` transport 与 `.env` 凭据，不创建新的
OpenAI client。

Prompt 只询问一件事：后一个 fragment 是否在语法和语义上直接续接前一个 fragment，二者
是否应当作为同一连续单元联合翻译。输入必须同时给出：

- 按 chain index 排序的 fragments；
- fragment 之间的显式 `<CHAIN_BOUNDARY>`；
- `merge_chain_text()` 的完整拼接原文；
- 禁止翻译、改写或评价版面美观的指令。

闭集返回：

```json
{
  "action": "confirm_joint_chain",
  "reason": "short explanation"
}
```

或：

```json
{
  "action": "no_op",
  "reason": "short explanation"
}
```

约束：

- JSON 对象只能有 `action`、`reason` 两个字段。
- `action` 只能取上述两个值。
- 一次调用，不做 retry。
- API 异常、空响应、非 JSON、字段不全、额外字段、未知动作均归为 `no_op`，并记录闭表理由。
- `reason` 只作审计说明，不参与准入。

建议的闭表状态：

- `confirmed`
- `model_no_op`
- `decision_unavailable`
- `invalid_decision_reply`
- `admission_refused`

### 4.4 确定性准入

LLM 决策后再次检查：

- conflict subtype 恰为 `reading_order_inversion`；
- member refs 与 preflight 时完全一致；
- chain indices 为 `0..n-1`；
- members 唯一、页码连续、属于同一 article；
- canonical chain owner 一致；
- source boxes 完整；
- merged source hash 与送给 LLM 的内容一致。

任一条件不满足，动作拒绝并沿原 `invalid_chain_topology` 释放路径返回。

### 4.5 修复动作

`confirm_joint_chain` 的动作只解除这一条 reading-order 单调检查：

- member 顺序继续使用 ChainBuilder 冻结的 chain index；
- `MemberSourceSlot.slot_order` 继续为 `0..n-1`；
- 每个 slot 继续使用对应 source element 的原始 box；
- 后续 placeholder、token budget、translation、allocation、conservation、fit 等所有守卫原样执行；
- 任何后续失败仍使用现有失败状态，不因 LLM 确认而强行写回。

不要修改 ArticleIR 对象，不要伪造新的 reading order。

### 4.6 报告接线

在现有 `chain_translation.report.json` 增加一个独立区块，例如：

```json
{
  "topology_adjudication": {
    "counts": {
      "detected": 1,
      "decision_calls": 1,
      "confirmed": 1,
      "admitted": 1
    },
    "records": []
  }
}
```

每条 record 写入：

- 完整类型化 issue；
- decision action、reason、raw reply hash、call count；
- admission accepted/reason；
- repair action applied；
- 最终 chain result state 与 joint translator call count。

计数要求：

- topology `decision_calls` 与既有 `translator_calls` 分开。
- p5 成功时 topology decision 为 1 次，joint translator 为 1 次。
- 原有 `counts.translator_calls` 仍只统计真正产生译文的 joint translation。
- minimal detector 对现有 chain report 的解析继续通过；不得靠放宽 detector schema 隐藏错误。

------

## 5. T2：两个 focused tests

新增 `tests/minimal/test_chain_topology_repair.py`，只保留两个测试。

### 5.1 接受路径

`test_confirmed_reading_order_conflict_reaches_joint_translation`

夹具要求：

- 两个同 article、同 canonical chain 的成员；
- chain indices `[0,1]`；
- ArticleIR reading orders 反转，例如 `[9,4]`；
- fake decision response 为 `confirm_joint_chain`；
- fake joint translation 返回一个合法 whole target。

断言：

- decision call 恰好 1；
- joint translation call 恰好 1；
- plan 产生一个 `joint_success` entry；
- claim 包含两个成员，ordinary path 无权再次领取；
- ordered source refs 与 fragment slot order 都按 chain index；
- topology report record 为 detected/confirmed/admitted/applied。

### 5.2 关闭路径

`test_topology_decision_cannot_override_other_or_invalid_conflicts`

在同一个测试函数内顺序执行两个独立夹具子案例，保持它仍是一个 pytest nodeid：

- reading-order conflict 收到非法 JSON；
- topology conflict 还带另一个结构错误，即使 fake model 返回 `confirm_joint_chain` 也不得调用模型或 joint translator。

断言：

- 没有 chain entry；
- 没有 chain claim；
- joint translator call 为 0；
- fallback 仍为 `invalid_chain_topology`；
- 决策/准入理由进入闭表记录。

### 5.3 唯一测试命令

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q `
  'tests/minimal/test_chain_topology_repair.py::test_confirmed_reading_order_conflict_reaches_joint_translation' `
  'tests/minimal/test_chain_topology_repair.py::test_topology_decision_cannot_override_other_or_invalid_conflicts'
```

门槛：两个 nodeid 全部通过。失败则停止，不运行样张。

### 5.4 Commit 1

仅暂存实现和 focused tests；不要暂存计划、PDF、日志或输出目录。

```powershell
git add -- `
  'babeldoc/magazine/chain_translation.py' `
  'babeldoc/magazine/chain_topology_repair.py' `
  'tests/minimal/test_chain_topology_repair.py'
git diff --cached --check
git commit -m 'fix(magazine): adjudicate topology-only chain conflicts'
```

Commit 1 只允许上述两个产品文件和这两个 focused tests。

------

## 6. T3：FD-zh p5 单页门

### 6.1 加载环境

在同一个 PowerShell 会话中执行，禁止打印 key：

```powershell
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

Get-Content -LiteralPath '.env' | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
        $parts = $line -split '=', 2
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path ("Env:" + $name) -Value $value
    }
}

if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw 'OPENAI_API_KEY is absent after loading .env'
}
```

### 6.2 单次 p5 命令

```powershell
New-Item -ItemType Directory -Force -Path 'examples\output\B21\p5' | Out-Null
Start-Transcript -LiteralPath 'examples\output\B21\p5\fd-zh-p5.log' -Force | Out-Null
try {
    & '.\.venv\Scripts\babeldoc.exe' `
      --config 'minimal.zh-en.toml' `
      --files 'examples\input\fd-zh.pdf' `
      --output 'examples\output\B21\p5' `
      --working-dir 'examples\output\B21\p5\work' `
      --pages '5' `
      --only-include-translated-page
    $runExit = $LASTEXITCODE
} finally {
    Stop-Transcript | Out-Null
}
if ($runExit -ne 0) { throw "p5 run failed with exit code $runExit" }
```

这是唯一一次 p5 样张运行。

### 6.3 p5 机器门槛

检查 `examples\output\B21\p5\work\fd-zh` 下的 sidecars。由于单页选择会把 runtime page
编号归一化，机器核对优先使用 physical refs `p5#6`、`p5#7`；runtime refs 可能为
`p1#6`、`p1#7`，不得因此误判。

必须全部成立：

1. `chain_report.json` 仍有 `p5#6 → p5#7` 的 accepted edge 与同一 chain。
2. topology adjudication：
   - detected = 1（目标 chain）；
   - decision_calls = 1；
   - action = `confirm_joint_chain`；
   - admission accepted；
   - repair action applied。
3. `chain_translation.report.json`：
   - 目标 chain `result_state=joint_success`；
   - `translator_call_count=1`；
   - ordered physical refs 为 `p5#6,p5#7`；
   - 两个 fragment 非空，whole target conservation 成立。
4. `translate_tracking.json` 中 `p5#7` 没有独立 ordinary translation request。
5. `issues.after.json` 中不存在 `p5#7` 的 `untranslated_residue`，也不存在目标 chain 的
   `non_joint_success`/`translator_call_count` violation。
6. 输出 PDF 存在且只有所选译文页。
7. 提取成品文本后不存在 `The条毫无二致。`，也不存在目标中文残留 `条毫无二致。`。

### 6.4 p5 视觉门槛

只查看目标页：

- 原句语义连续；译文不再在 `萧/条` 边界断裂。
- 两个 source boxes 都有可见英文 fragment。
- 无新文字叠压、越界或不可读缩小。
- 不要求本页其他既有检测问题在本批清零。

### 6.5 p5 停止条件

任一机器或视觉门槛失败：

- 立即停止；
- 保留 Commit 1 和 `examples\output\B21\p5` 工件；
- 不创建成功报告，不运行完整 fd-zh，不追加代码修改或第二次 p5 运行；
- 最终反馈精确失败点、decision/action/call count 和目标 residue 状态。

------

## 7. T4：成功后记录 repair 过程

只有 p5 门全部通过才执行本节。

### 7.1 报告文件

使用 `apply_patch` 创建：

`docs\reports\B21\repair_process.md`

内容必须来自 B20/B21 实际 sidecars，不使用计划值替代实测值。报告至少包含：

1. branch、起点、Commit 1 SHA、输入和运行命令。
2. B20 缺陷证据：accepted chain、`[191,184]`、`invalid_chain_topology`、joint calls 0、
   `The条毫无二致。`。
3. B21 四阶段表：
   - detection：issue/subtype/refs/reading orders；
   - decision：送入 LLM 的 fragments、boundary、merged source、action/reason；
   - deterministic admission：逐条结构门槛与结果；
   - repair/verification：joint call、allocation、residue、chain conservation。
4. 清楚注明 p5 edge 的 `score=null`，上游依据是确定性硬门槛；“accepted chain”才是本次
   决策入口。
5. LLM 负责语义连续性判断；确定性代码保留结构否决权。
6. ArticleIR 仍保留原 reading order；本批没有全局重排。
7. p5 前后机器指标与视觉结论。
8. 完整运行结果（T5 后补写）。

不要在报告中声称当前 post-layout `repair_loop.py` 执行了这次动作。准确名称使用：

> pre-translation structural detection–decision–repair round

### 7.2 报告图片

从 PDF 渲染 144–180 dpi PNG，并用报告中的目标 `source_boxes` union 加约 20–30pt padding
计算裁剪范围；不得把 p5 坐标写进产品代码或测试。

- `fd-p5-source.png`：`examples\input\fd-zh.pdf` 物理 p5。
- `fd-p5-before-b20.png`：优先使用
  `examples\output\B20\fd-zh.no_watermark.en.mono.pdf` 物理 p5。
- `fd-p5-after-b21.png`：B21 p5 单页成品的唯一页面。

若 B20 PDF 已不存在：

- 不重跑 B20；
- 省略 `fd-p5-before-b20.png`；
- 在报告中注明 B20 视觉文件缺失，并引用 B20 sidecar 的文本证据。

报告图片只服务本次 report，不额外生成整页截图集。

------

## 8. T5：一次完整 fd-zh 运行

只有 T3 成功且 T4 初稿已写入后执行。

### 8.1 唯一完整运行命令

继续使用已经加载 `.env` 的 PowerShell 会话：

```powershell
New-Item -ItemType Directory -Force -Path 'examples\output\B21' | Out-Null
Start-Transcript -LiteralPath 'examples\output\B21\fd-zh.log' -Force | Out-Null
try {
    & '.\.venv\Scripts\babeldoc.exe' `
      --config 'minimal.zh-en.toml' `
      --files 'examples\input\fd-zh.pdf' `
      --output 'examples\output\B21' `
      --working-dir 'examples\output\B21\work'
    $runExit = $LASTEXITCODE
} finally {
    Stop-Transcript | Out-Null
}
if ($runExit -ne 0) { throw "full fd-zh run failed with exit code $runExit" }

```

不带 `--pages`。这是唯一一次完整 fd-zh 运行。

### 8.2 完整运行门槛

必须核对：

1. exit code 0，最终 mono PDF 存在，页数与源 PDF 相同。
2. p5 目标 chain 在完整运行中仍为 `joint_success`：
   - topology decision call = 1；
   - joint translator call = 1；
   - ordered refs = `p5#6,p5#7`；
   - conservation 成立。
3. 完整成品和 `issues.after.json` 中不再有 p5#7 的目标 residue。
4. `translate_tracking.json` 中 p5#7 未被 ordinary path 单独翻译。
5. p3 `编者的话` 仍译为 `Editor's Note`，视觉清晰。
6. p5 连续句视觉正常，无目标成员新增 out-of-page、text-text collision 或不可读缩小。
7. 其他已知问题只记录，不扩大 B21 修复范围。

只视觉检查 p3 与 p5。不逐页复核完整样张。

### 8.3 完整运行失败处理

完整运行只跑一次。若失败：

- 不修改 Commit 1，不补跑；
- 在 `repair_process.md` 中如实记录“p5 gate 成功、full run 失败”、失败阶段和目标 chain 状态；
- 保留运行日志与 work sidecars；
- 后续问题交给新计划。

### 8.4 更新报告

将完整运行的实测值补入 `repair_process.md`：

- full run exit/status/page count；
- topology decision 与 joint translation call counts；
- p3/p5 验收；
- issues.before/after 中与目标 chain 直接相关的变化；
- 完整运行成功或失败结论。

禁止把全局 issue 总数下降写成 B21 功劳；只归因目标 chain 的直接变化。

------

## 9. T6：文档 Commit 2 与最终状态

只暂存计划与 `docs\reports\B21`。运行目录全部由 `.gitignore` 排除，`.env`、PDF、日志、
work sidecars 不得强制加入 Git。

```powershell
git add -- `
  'codex_plan_B21_chain_topology_repair.md' `
  'docs/reports/B21/repair_process.md' `
  'docs/reports/B21/*.png'
git diff --cached --check
git commit -m 'docs(b21): record topology chain repair evidence'

```

若 B20 before PNG 缺失，只暂存实际生成的文件，不创建占位图片。

最后只执行一次：

```powershell
git status --short --branch
git log -3 --oneline

```

允许 `examples\output\B21` 被忽略；不应存在其他未提交的源码或报告修改。

------

## 10. 最终交付格式

Codex 最终回复必须简洁列出：

1. Commit 1 SHA 与代码修复结果。
2. 两个 focused nodeids 的结果。
3. p5 单页门：decision/action、decision calls、joint calls、residue、视觉结论。
4. `docs\reports\B21\repair_process.md` 与图片清单。
5. 完整 fd-zh：exit、页数、p3、p5、目标 chain 和 residue 结果。
6. Commit 2 SHA。
7. 最终工作树状态。
8. 若在停止条件处结束，明确指出未执行的后续阶段；不要用额外复跑补齐。

### 完成定义

B21 只有在以下条件全部成立时标记完成：

- 两个 focused tests 通过；
- p5 单页门成功；
- repair 过程报告与实际证据已生成；
- 完整 fd-zh 已按计划恰好运行一次；
- p5 目标 residue 消失，joint chain 守恒；
- p3 `Editor's Note` 保持；
- 两个 commit 边界符合计划；
- 无范围外产品改动。
