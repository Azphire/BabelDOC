# Codex Plan M0–M6：BabelDOC Magazine 最小迁移

计划版本：2026-08-27 rev.2
执行形式：一个主控 Agent + 一个持续复用的执行 Agent
开发拓扑：一个独立 clone、一个开发分支、零额外 worktree
并行条件：旧仓库 C22 可继续运行；迁移仓库在 M6 付费门之前全程禁止翻译 API 请求
目标环境：Windows 11、PowerShell、Python 3.12、`uv`、源码树运行

---

## 0. 给主控 Agent 的执行摘要

本计划在干净的 BabelDOC v0.6.4 上游提交上，迁移杂志翻译的最小研究交付路径。当前复杂仓库只充当只读 donor。

最终固定流水线为：

```text
PDF 解析
→ 确定性页面分类
→ 连续链检测
→ 唯一 ArticleDocumentIR
→ HITL 页面/术语/首字决定应用
→ 文章上下文
→ 连续链一次联合翻译 + 普通段落翻译
→ 按排版容量回填
→ 文章内跨栏及相邻跨页文本流
→ 正式排版
→ 中英文首字装置
→ 确定性检测
→ 最多一次受限修复
→ PDF 写出
→ 外部 PDF smoke validation
```

正常翻译运行时，上述保留功能全部进入同一固定路径。没有 magazine mode、runtime profile 或用户功能开关。HITL apply 仅由固定目录中是否存在 decisions 文件决定；这是输入存在性判断。

主控必须先完成仓库审计和 M0。每一阶段只交给同一个执行 Agent 一个短轮次；执行者结束当前轮次后返回，不得自行进入下一阶段。

计划包含两个可交付里程碑：

| 状态 | 完成范围 | 用途 |
| --- | --- | --- |
| `CORE_RUNNABLE` | M0–M3 | Article IR、联合翻译、容量回填、跨栏/跨页文本流可运行 |
| `MINIMAL_FEATURE_COMPLETE` | M0–M5 | 再含 HITL、首字、检测和一次修复；全部离线门通过 |
| `MINIMAL_DELIVERY_PASS` | M0–M6 | C22 结束后唯一一次真实翻译 smoke 通过 |

M4 或 M5 被阻塞时，已经验证的 `CORE_RUNNABLE` 提交仍保留，禁止回退或覆盖它。

---

## 1. 权威提交与冻结快照

截至 2026-08-27 已核对：

| 名称 | 完整 SHA | 用途 |
| --- | --- | --- |
| `UPSTREAM_BASE` | `17480db9df92ddcb37349ce34b312335226e8ec9` | 唯一开发基线；BabelDOC Release v0.6.4 |
| `DONOR_C16` | `57a12552da7a13523ad5a2e27b45473f24183208` | 主要实现 donor；含 C01–C16，避开 C17–C22 工程层 |
| `LEGACY_MAIN_SNAPSHOT` | `450935f57a45f154a04fec8b51d0b2598aa33a47` | 计划和 README 参考；产品源码与 `DONOR_C16` 相同 |
| `DONOR_PRE_C22` | `3a315b947ef5b04a7de4ac7f047bdfd06bea5e3b` | C17–C21 集成及 C22 失败状态，只读问题参考 |
| 当时 `upstream/main` | `38d3896dcde9b5a940c62cf5563cadea673a64d3` | 信息项；不得作为迁移基线 |

`v0.6.4` 是 annotated tag。tag object 为 `63a1dff04f2e61c004f8512136745fd2a8564d96`，实际 commit 为 `17480db...`。所有 checkout、比较和基线校验均使用实际 commit SHA。

### 1.1 donor 使用优先级

1. 产品实现优先读取 `DONOR_C16`。
2. `LEGACY_MAIN_SNAPSHOT` 只用于读取计划、README 和 `UPSTREAM_DIFF.md`。
3. `DONOR_PRE_C22` 只在某个已复现错误明确对应 C17–C21 时读取相关函数 diff。
4. C22 后续修复提交不自动进入本计划。
5. 禁止 merge、rebase 或 cherry-pick 任一 donor 历史提交。

### 1.2 已知可选正确性补丁

只有阶段测试或真实样本证明需要时，才评估以下集成提交中的局部逻辑：

```text
8e398be  chain 仅在 provisional article owner 内连接
9fc0d47  physical page identity；仅 pages/split/targeted-output 场景需要
b55f0ae  debug overlay 与 semantic geometry 隔离；本计划默认关闭 debug
```

读取后仍须手工应用到上游文件。不得复制整个集成版本文件。

---

## 2. 产品范围

### 2.1 必须迁移并固定启用

1. 确定性页面分类；VLM fallback 不进入执行路径。
2. 连续链检测及稳定 paragraph/chain identity。
3. 每次运行唯一的 `ArticleDocumentIR`。
4. 文章级上下文。
5. 连续链一次联合翻译。
6. claimed paragraph 从 ordinary、cross-column 和 cross-page producer 中排除。
7. 联合译文按真实排版容量切分和回填。
8. 同文章内的同页跨栏文本流。
9. 同文章内、相邻物理页之间的受限文本流。
10. 固定资产守卫。
11. HITL review JSON 导出；固定目录中存在 decisions 时自动应用。
12. `keep` / `flatten` 首字决定。
13. 英文单行放大首字母和中文两行嵌入式首字。
14. 确定性问题检测。
15. 最多一次受限修复和一次重检。
16. 输出 PDF 可重新打开、页数不变、正文可提取。
17. 一个轻量 `minimal_run.report.json`，记录验收所需计数和状态。

### 2.2 明确排除

```text
runtime profile 与 22 个用户开关
magazine CLI mode/profile 参数
profile 依赖校验与运行 manifest
wheel/_resources 发布支持
多系统、多 Python 版本兼容
多文件并行和 split-document 支持
完整 checkpoint 恢复体系
C01–C22 全门禁
VLM 页面分类 fallback
C18–C21 forced tool-call transport 与通用 repair schema
source-bound v4 HITL binding/delivery
ArticleStateJournal 和完整 RunTrace 终态合规层
多轮 repair、动作预算系统、完整事务框架
C15/C20C final compliance 状态机
完整语料 sweep、LOPO、正式实验评价
debug overlay 语义等价支持
任意 PDF 的容错和发布级错误恢复
```

`babeldoc/magazine/` 中可能保留未接线模块。未进入固定流水线的代码不构成交付功能，也不要求清理。

### 2.3 固定支持环境

```text
一次一个原生数字 PDF
主要方向 en → zh
固定 OpenAI-compatible provider
固定模型 gpt-4o-mini，除非用户已有 TOML 明确指定另一模型
源码树 + uv
Windows 11 + Python 3.12
真实 smoke 只翻译 Courier-en.pdf 的 source pages 7–8
debug 关闭
```

中文到英文只用 synthetic IL 验证英文首字路径；不运行真实 zh→en paid job。

---

## 3. C22 并行隔离规则

### 3.1 目录

```text
D:\codes\magazine-translation          # 旧仓库，C22 正在运行
D:\codes\babeldoc-minimal-migration    # 本计划唯一工作目录
```

迁移 Agent 禁止进入、修改、清理、切分支、fetch 或停止旧仓库中的任何进程。用户在启动前只读复制一次 `Courier-en.pdf`，此后 Agent 不访问旧目录。

### 3.2 独立资源

两个仓库必须分别使用：

```text
.venv
UV cache
BabelDOC cache 和翻译 SQLite
TEMP/TMP
working-dir
output
测试日志
```

上游 v0.6.4 把 BabelDOC cache 硬编码到 `Path.home()/.cache/babeldoc`。M0 的第一项产品改动必须增加 `BABELDOC_CACHE_DIR` 环境变量覆盖。完成该改动前，禁止执行任何会 import `babeldoc` 的命令。

### 3.3 C22 运行期间允许的工作

```text
Git 查询和 donor 阅读
依赖安装与独立 cache 中的 asset warmup
M0–M5 代码修改
静态检查
synthetic/fake translator 单元与集成测试
parse-only 和 skip-translation 离线 PDF smoke
```

### 3.4 C22 运行期间禁止的工作

```text
真实翻译、术语提取或 repair 模型请求
读取或打印 API key
使用旧仓库的 working/output/cache
更新已经冻结的 donor tag
重复 C22 paid command
```

M5 完成而 C22 仍未终止时，状态写为 `MINIMAL_FEATURE_COMPLETE / PAID_GATE_DEFERRED`，保存提交并停止在 M6.4 之前。

---

## 4. 用户先执行：建立独立仓库

以下命令在新的 Windows PowerShell 窗口运行。不要在 C22 所在终端执行。

### 4.1 初始化并获取三个固定对象

```powershell
$ErrorActionPreference = "Stop"

function Assert-GitSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

$C22Repo = (Resolve-Path -LiteralPath "D:\codes\magazine-translation").Path
$Target = [System.IO.Path]::GetFullPath(
    "D:\codes\babeldoc-minimal-migration"
)

if (
    $Target -eq $C22Repo -or
    $Target.StartsWith(
        $C22Repo + "\",
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "迁移仓库必须位于 C22 仓库之外"
}

if (Test-Path -LiteralPath $Target) {
    throw "目标目录已经存在，请先人工确认：$Target"
}

New-Item -ItemType Directory -Path $Target | Out-Null
Set-Location -LiteralPath $Target

git init
Assert-GitSuccess "git init"

git remote add upstream https://github.com/funstory-ai/BabelDOC.git
Assert-GitSuccess "add upstream"

git remote add legacy https://github.com/Azphire/BabelDOC.git
Assert-GitSuccess "add legacy"

git remote add origin https://github.com/Azphire/BabelDOC.git
Assert-GitSuccess "add origin"

git fetch --no-tags upstream `
    "+refs/heads/main:refs/remotes/upstream/main" `
    "+refs/tags/v0.6.4:refs/tags/v0.6.4"
Assert-GitSuccess "fetch upstream"

git fetch --no-tags legacy `
    "+refs/heads/main:refs/remotes/legacy/main" `
    "+refs/heads/integration/c17-c22:refs/remotes/legacy/integration-c17-c22"
Assert-GitSuccess "fetch legacy"

git remote set-url --push upstream "https://push-disabled.invalid/upstream"
Assert-GitSuccess "disable upstream push"
git remote set-url --push legacy "https://push-disabled.invalid/legacy"
Assert-GitSuccess "disable legacy push"

git config --local remote.pushDefault origin
Assert-GitSuccess "set default push remote"
git config --local push.default current
Assert-GitSuccess "set push mode"
git config --local remote.origin.push `
    "refs/heads/migration/minimal-v0.6.4:refs/heads/migration/minimal-v0.6.4"
Assert-GitSuccess "set migration push refspec"
```

### 4.2 固定并验证 SHA

```powershell
$Base = "17480db9df92ddcb37349ce34b312335226e8ec9"
$DonorC16 = "57a12552da7a13523ad5a2e27b45473f24183208"
$LegacyMain = "450935f57a45f154a04fec8b51d0b2598aa33a47"
$DonorPreC22 = "3a315b947ef5b04a7de4ac7f047bdfd06bea5e3b"

foreach ($Sha in @($Base, $DonorC16, $LegacyMain, $DonorPreC22)) {
    git cat-file -e "${Sha}^{commit}"
    Assert-GitSuccess "resolve $Sha"
}

$TagCommit = (git rev-parse "refs/tags/v0.6.4^{}").Trim()
Assert-GitSuccess "peel v0.6.4"

if ($TagCommit -ne $Base) {
    throw "v0.6.4 实际 commit 与固定基线不一致：$TagCommit"
}

git merge-base --is-ancestor $Base $DonorC16
Assert-GitSuccess "base is ancestor of C16 donor"

git merge-base --is-ancestor $Base $DonorPreC22
Assert-GitSuccess "base is ancestor of pre-C22 donor"

git tag migration-base-v0.6.4 $Base
Assert-GitSuccess "tag migration base"
git tag donor-c16-20260827 $DonorC16
Assert-GitSuccess "tag C16 donor"
git tag legacy-main-20260827 $LegacyMain
Assert-GitSuccess "tag legacy main snapshot"
git tag donor-pre-c22-20260827 $DonorPreC22
Assert-GitSuccess "tag pre-C22 donor"

git switch --create "migration/minimal-v0.6.4" $Base
Assert-GitSuccess "create migration branch"

git config --local migration.baseCommit $Base
Assert-GitSuccess "record migration base"
git config --local migration.donorC16 $DonorC16
Assert-GitSuccess "record C16 donor"
git config --local migration.legacyMain $LegacyMain
Assert-GitSuccess "record legacy main snapshot"
git config --local migration.donorPreC22 $DonorPreC22
Assert-GitSuccess "record pre-C22 donor"

if ((git rev-parse HEAD).Trim() -ne $Base) {
    throw "初始 HEAD 偏离固定上游基线"
}

if (git status --porcelain) {
    throw "初始工作树不干净"
}

git status --short --branch
git remote -v
git config --local --get-regexp "^migration\."
```

远端分支在 C22 完成后可能前移；本计划继续使用本地固定 tag。不得把移动后的 branch head 替换进当前迁移。

### 4.3 复制唯一真实样本

本计划使用 `Courier-en.pdf`，避免与 C22 的 `ABB-zh.pdf` 输入重合。

```powershell
$SourcePdf = "D:\codes\magazine-translation\examples\input\Courier-en.pdf"
$InputDir = Join-Path $Target "examples\input"
$TargetPdf = Join-Path $InputDir "Courier-en.pdf"
$ExpectedPdfHash = `
    "9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a"

if (-not (Test-Path -LiteralPath $SourcePdf)) {
    throw "缺少 Courier-en.pdf：$SourcePdf"
}

$SourceHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $SourcePdf
).Hash.ToLowerInvariant()

if ($SourceHash -ne $ExpectedPdfHash) {
    throw "Courier-en.pdf hash 不一致：$SourceHash"
}

New-Item -ItemType Directory -Force -Path $InputDir | Out-Null
Copy-Item -LiteralPath $SourcePdf -Destination $TargetPdf

$CopiedHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $TargetPdf
).Hash.ToLowerInvariant()

if ($CopiedHash -ne $ExpectedPdfHash) {
    throw "复制后的 Courier-en.pdf hash 不一致：$CopiedHash"
}
```

禁止复制旧仓库的 `.git`、`.venv`、`.tmp`、cache、working-dir 或 output。

### 4.4 放入本计划

把本文件保存到：

```text
D:\codes\babeldoc-minimal-migration\codex_plan_M0_M6_minimal_migration.md
```

然后提交计划文件：

```powershell
Set-Location -LiteralPath $Target

git add -- "codex_plan_M0_M6_minimal_migration.md"
git commit -m "docs: add minimal migration plan"
Assert-GitSuccess "commit migration plan"
```

### 4.5 建立独立运行环境并从此窗口打开 VS Code

```powershell
$RuntimeRoot = Join-Path $Target ".runtime"
$InfoExclude = Join-Path $Target ".git\info\exclude"

# M0 尚未提交 .gitignore；先用本地 exclude 保持初始化审计干净。
$ExcludeLines = @(Get-Content -LiteralPath $InfoExclude)
if ($ExcludeLines -notcontains "/.runtime/") {
    Add-Content -LiteralPath $InfoExclude -Value "/.runtime/"
}

$env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"
$env:BABELDOC_CACHE_DIR = Join-Path $RuntimeRoot "babeldoc-cache"
$env:TEMP = Join-Path $RuntimeRoot "temp"
$env:TMP = $env:TEMP

New-Item -ItemType Directory -Force -Path `
    $env:UV_CACHE_DIR, `
    $env:BABELDOC_CACHE_DIR, `
    $env:TEMP | Out-Null

Set-Location -LiteralPath $Target
code -n .
```

若 `code` 命令不可用，手工打开该文件夹；随后在 VS Code 新终端重新设置本节四个环境变量。

本节变量只对当前 PowerShell 进程有效。M0 必须创建并提交
`tools/Initialize-MigrationRuntime.ps1`；从 M0-R2 起，每个测试、CLI、门禁和恢复流程的第一条命令都必须 dot-source 该脚本，不能依赖 VS Code 继承的旧环境。

### 4.6 给主控 Codex 的第一条消息

```text
完整读取仓库根目录的 codex_plan_M0_M6_minimal_migration.md，并严格按计划开始执行。

你是 migration_controller。只创建一个 migration_executor，并在后续所有轮次持续复用它。执行 Agent 是唯一产品代码写入者；主控负责阶段拆分、只读 diff 审查、独立门禁和是否继续。

禁止创建 worktree、额外开发分支或第二个写入 Agent。
禁止访问或修改 D:\codes\magazine-translation。
先完成初始化审计，再只执行 M0-R0。不要一次下发整个 M0，更不能一次下发 M0–M6。
C22 终止前禁止任何翻译 API 请求。
```

---

## 5. 一主控一执行协议

### 5.1 固定角色

只允许两个 Agent：

- `migration_controller`：主控；不修改产品代码，不创建产品提交。负责读取计划、拆轮次、检查仓库、审查 diff、独立运行阶段门、决定继续或停止。
- `migration_executor`：唯一执行者；负责 donor 阅读、代码修改、聚焦测试和候选提交。不得创建子 Agent。

整个迁移只 spawn 一次 `migration_executor`。后续任务统一通过 `followup_task` 发送给同一执行者。
首次 spawn 成功后，主控立即把执行者的 canonical agent ID 和 `generation: 1` 写入本地状态文件；后续不得只凭显示名称寻找执行者。

禁止：

```text
额外 worktree
第二个迁移分支
第二个写入 Agent
主控和执行者同时修改文件
执行者自行进入下一阶段
主控在执行者仍运行时启动门禁
因一次 600 秒等待到期而终止或重启任务
```

### 5.2 每阶段固定轮次

| 轮次 | 执行者任务 | 是否允许修改 |
| --- | --- | --- |
| `Mx-R0` | 只读检查上游接口、donor 函数和依赖；返回精确迁移映射 | 否 |
| `Mx-R1` | 实现一个最小可导入切片 | 是 |
| `Mx-R2` | 增加聚焦测试并修复当前切片 | 是 |
| `Mx-R3` | 运行阶段测试、检查范围、创建候选提交 | 是 |
| `Mx-GATE` | 主控独立验收 | 主控只读 |
| `Mx-RF<n>` | 同一执行者按实际失败证据修复 | 是 |
| `Mx-RV` | 记录 verified SHA；不得开始下一阶段 | 只更新本地状态 |

预计超过 8 分钟的写入轮次必须拆为 `R1a`、`R1b`。耗时命令可以继续运行更久；它由 session/PID 和日志追踪。

### 5.3 600 秒只表示轮询窗口

任何 wait 或界面窗口在 600 秒返回时：

1. 不改变阶段状态。
2. 先检查执行者状态、终端 session、PID、日志和输出。
3. 已有进程仍运行时继续等待。
4. 执行者 idle 时向同一执行者发送恢复包。
5. 未确认旧进程结束前，不得重复同一测试或运行命令。
6. 真实请求发出后，任何超时均禁止自动重试。

长命令执行前，执行者必须记录：

```text
完整命令
UTC 开始时间
session ID 或 PID
日志路径
是否可能发起翻译 API 请求
是否可能消耗 paid attempt
```

### 5.4 本地状态文件

使用未跟踪文件：

```text
.runtime/migration-state.md
```

每个轮次结束时记录：

```markdown
## Current state

- Stage: M2
- Round: M2-R2
- Status: IMPLEMENTING
- Executor canonical ID: <agent id>
- Executor generation: 1
- Last confirmed executor status: running|idle|completed|lost
- Branch: migration/minimal-v0.6.4
- Upstream base: 17480db...
- Donor C16: 57a1255...
- Last verified SHA: <sha>
- Current HEAD: <sha>
- Dirty paths: <paths or none>
- Last command: <command>
- Exit code: <code>
- Running session/PID: <id or none>
- Translation API request started: no
- Paid attempt consumed: no
- First relevant failure: <text or none>
- Next allowed action: <one action>
```

Git 状态和真实文件优先于状态文件。

### 5.5 恢复包

执行者 idle 且阶段未完成时，主控发送：

```text
RESUME <stage-round>

Repository: D:\codes\babeldoc-minimal-migration
Branch: migration/minimal-v0.6.4
Last verified SHA: <sha>
Current HEAD: <sha>
Donor C16: 57a12552da7a13523ad5a2e27b45473f24183208
Current git status: <exact output>
Last completed action: <action>
Known failure: <exact evidence or none>
Running process/session: <id or none>
Next allowed action: <one action>

Preserve all current changes. Do not reset, clean, stash, reclone, create a branch,
or repeat a command whose earlier process has not been proven terminated.
```

同一 Codex thread 中，主控必须使用状态文件记录的 canonical ID 恢复该执行者。跨会话后原 ID 无法寻址时，只有以下条件全部满足才可创建 replacement：

1. 平台已经明确报告旧 ID 不存在、已完成或永久丢失；一次 wait 超时不满足该条件。
2. 主控已检查旧 terminal session/PID，没有仍在运行的写入、Git、测试或 BabelDOC 进程。
3. 已保存 `git status --short --branch`、HEAD、dirty paths、最近日志和最后 verified SHA。
4. `.runtime/migration-state.md` 记录 replacement 原因，并把 generation 加一。
5. replacement 收到完整恢复包，继续当前轮次；禁止重做已经完成的动作。

replacement 创建后仍只有一个写入者。若无法证明旧执行者和其进程已经终止，状态必须保持 `BLOCKED_RECOVERY`，不得 spawn。

### 5.6 候选提交和主控门禁

执行者仅在以下条件全部满足时创建候选提交：

```text
当前阶段功能完成
聚焦测试 exit 0
git diff --check exit 0
没有超出 allowlist
没有整体覆盖上游集中式文件
没有外部翻译请求
```

每阶段只使用显式 staging：

```powershell
git status --short
git add -- <本阶段明确文件或目录>
git diff --cached --stat
git diff --cached --check
git commit -m "<stage message>"
```

禁止 `git add -A`、`git add .`。

主控在执行者 idle 后独立运行：

```powershell
$PreviousVerified = "<sha>"
git status --short --branch
git diff --stat "$PreviousVerified..HEAD"
git diff --name-status "$PreviousVerified..HEAD"
git diff --check "$PreviousVerified..HEAD"
git show --stat --oneline HEAD
# 当前阶段规定的测试命令
```

执行者报告不能代替主控实际门禁。

### 5.7 失败修复上限

主控把以下失败包交回同一执行者：

```text
GATE FAILED: <stage>
Command: <exact command>
Exit code: <code>
First relevant failure: <excerpt>
Expected invariant: <expected>
Current HEAD: <sha>
Allowed action: fix this stage only
```

同一阶段最多三轮 `RF`。以下情况进入 `BLOCKED`：

```text
相同根因连续两轮没有变化
三轮修复后阶段门仍失败
需要引入排除范围中的工程层
需要整体覆盖 high_level.py、main.py、translation_config.py、translator.py 或 typesetting.py
前一阶段不变量其实未满足
C22 仍运行且继续工作必须访问翻译 API
```

### 5.8 Git 回退规则

测试失败或等待超时不触发自动回退。优先在当前阶段向前修复。

主控明确放弃某阶段时：

1. 保存 HEAD、diff、命令、日志和第一条错误。
2. dirty 修改先由执行者创建 `WIP blocked <stage>` 证据提交。
3. 主控列出精确阶段提交。
4. 执行者使用 `git revert` 创建可追踪回退提交。
5. 主控重跑上一 verified smoke。

禁止：

```text
git reset --hard
git clean
git checkout -- <path>
git restore .
git stash
force push
```

---

## 6. 固定迁移规则

### 6.1 donor 阅读

每次从 local config 读取固定 SHA：

```powershell
$Base = (git config --get migration.baseCommit).Trim()
$Donor = (git config --get migration.donorC16).Trim()
$PreC22 = (git config --get migration.donorPreC22).Trim()

git show "${Donor}:babeldoc/magazine/chain_translation.py"
git diff "$Base..$Donor" -- "babeldoc/format/pdf/high_level.py"
git diff "$Donor..$PreC22" -- "babeldoc/magazine/chain_translation.py"
```

禁止使用会移动的 `legacy/main` 名称作为实现来源。

### 6.2 文件复制边界

M1 允许整体复制：

```text
babeldoc/magazine/**
configs/**
prompts/**
```

复制目的为复用算法和隐式 import closure。只有固定编排器接入的模块进入运行路径。不要在迁移期间清理未使用 extension 文件。

以下 IL schema 四件套可以从 `DONOR_C16` 同步复制，因为它们只在同一上游 pin 上增加字段：

```text
babeldoc/format/pdf/document_il/il_version_1.py
babeldoc/format/pdf/document_il/il_version_1.rnc
babeldoc/format/pdf/document_il/il_version_1.rng
babeldoc/format/pdf/document_il/il_version_1.xsd
```

### 6.3 只能手工重接的上游文件

以下文件始终以 `UPSTREAM_BASE` 内容为底：

```text
babeldoc/const.py
babeldoc/main.py
babeldoc/format/pdf/high_level.py
babeldoc/format/pdf/translation_config.py
babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py
babeldoc/format/pdf/document_il/midend/il_translator.py
babeldoc/format/pdf/document_il/midend/typesetting.py
babeldoc/format/pdf/document_il/midend/styles_and_formulas.py
babeldoc/format/pdf/document_il/utils/formular_helper.py
babeldoc/translator/cache.py
babeldoc/translator/translator.py
```

默认禁止修改 `translation_config.py`、`translator.py` 和 `cache.py`。内部兼容属性由新建的 `babeldoc/magazine/minimal_pipeline.py` 写入 config 实例。

### 6.4 薄编排器

新增：

```text
babeldoc/magazine/minimal_pipeline.py
```

它负责：

```text
设置内部兼容属性
固定 reviews 目录
保存唯一 article_ir 和必要运行态
包装翻译前、译后、排版后钩子
写 minimal_run.report.json
```

`high_level.py` 只保留少量显式调用。不得把 donor 中 profile、manifest、checkpoint、full PDF compliance 和 CLI mode 逻辑带入。

建议接口：

```python
def configure(config) -> None: ...
def after_styles(config, docs): ...
def after_terms(config, docs): ...
def before_translation(config, docs): ...
def after_translation(config, docs, typesetting_factory): ...
def after_typesetting(config, docs, typesetting): ...
def write_report(config, docs) -> None: ...
```

执行者可以根据上游真实调用栈调整参数，接口职责和阶段顺序不能改变。

### 6.5 内部固定属性

用户看不到这些属性；它们仅用于兼容 donor 模块：

```text
True:
  magazine_page_classify
  magazine_chain_detect
  magazine_chain_translate
  magazine_article_group
  magazine_article_context
  magazine_hitl_export
  magazine_detect
  magazine_column_reflow
  magazine_drop_cap_apply
  magazine_drop_cap_mark
  magazine_drop_cap_render
  magazine_formula_reclass
  magazine_fragment_stitch
  magazine_indent_policy
  magazine_line_structure
  magazine_paren_dedup

Dynamic:
  magazine_hitl_apply = fixed decisions file exists

False / unused:
  magazine_checkpoint
  magazine_pdf_compliance
  magazine_repair
  magazine_rotated_lane
  magazine_title_typeset
  magazine_profile
  magazine_mode
  magazine_runtime_profile
```

`magazine_repair` 保持 false，用于阻止 donor detector 自动进入复杂多轮 controller。M5 由 `minimal_pipeline` 显式调用一次 `minimal_repair`，因此交付路径中的修复功能仍固定启用。

若 detector 的现有实现强依赖 checkpoint，M5 应增加一个最小内存 source-geometry snapshot。禁止重新接入 checkpoint archive/profile 体系。

### 6.6 fail-fast

以下不变量失败时直接抛出窄异常：

```text
ArticleDocumentIR 未建立
同一运行重建第二份 canonical ArticleDocumentIR
claimed IDs 与 ordinary/cross-column/cross-page IDs 相交
同一 chain 产生多于一次 semantic translation request
chain member 未全部回填
target text 守恒失败
article flow 越过 owner 或非相邻物理页
fixed asset digest 改变
decisions 文件存在但格式或目标无效
修复动作不在许可集合
```

禁止 broad `except Exception: warning + continue`。保留上游资源释放、文件关闭、线程池关闭和 `finally`。

---

## 7. 阶段总览

| 阶段 | 目标 | 外部翻译请求 | 候选提交 |
| --- | --- | --- | --- |
| M0 | cache/CLI 离线隔离；证明干净上游 | 0 | `M0: isolate runtime and verify upstream baseline` |
| M1 | extension、schema、页面/chain/Article IR | 0 | `M1: migrate canonical magazine structure` |
| M2 | article context、一次联合翻译、容量回填 | 0，fake only | `M2: migrate joint chain translation` |
| M3 | 同页及相邻跨页 article flow、资产守恒 | 0，fake only | `M3: migrate bounded article flow` |
| M4 | HITL 两遍和中英文首字 | 0，fake only | `M4: migrate HITL and drop caps` |
| M5 | 检测、最多一次修复、最终 smoke validator | 0，fake only | `M5: add bounded detection and repair` |
| M6 | 全离线总门 + 一次真实 pages 7–8 smoke | 最多一个 CLI job | `M6: verify minimal delivery`，无代码时不建空提交 |

---

## 8. M0：隔离运行环境并证明上游基线

### 8.1 M0-R0，只读映射

执行者检查：

```powershell
git rev-parse --show-toplevel
git branch --show-current
git status --short --branch
git worktree list
git rev-parse HEAD
git config --local --get-regexp "^migration\."
git show migration-base-v0.6.4:babeldoc/const.py
git show donor-c16-20260827:babeldoc/translator/no_network.py
git diff migration-base-v0.6.4..donor-c16-20260827 -- babeldoc/main.py
```

必须确认：

```text
当前根目录精确等于 D:\codes\babeldoc-minimal-migration
当前分支为 migration/minimal-v0.6.4
worktree list 只有当前目录
产品 diff 为空；只允许已提交 plan
BABELDOC_CACHE_DIR、UV_CACHE_DIR、TEMP、TMP 全部指向新目录
```

R0 只返回最小 patch 映射，不运行 Python、uv 或 BabelDOC。

### 8.2 M0-R1，允许修改

```text
.gitignore
babeldoc/const.py
babeldoc/main.py
babeldoc/translator/no_network.py
tools/Initialize-MigrationRuntime.ps1
tests/minimal/test_runtime_isolation.py
tests/minimal/test_offline_cli_selection.py
```

要求：

1. `.gitignore` 增加 `/.runtime/`；运行状态、cache、日志和输出不得进入 Git。
2. `CACHE_FOLDER` 优先读取 `BABELDOC_CACHE_DIR`，未设置时保持原默认。
3. `only_parse_generate_pdf` 或 `skip_translation` 时构造 `NoNetworkTranslator`，不要求 API key。
4. 普通 `--openai` 路径保持上游行为。
5. 普通 paid 路径允许从 `OPENAI_API_KEY` 读取 key；禁止打印值、长度、前后缀。
6. 不复制 donor 的完整 `main.py`。
7. 不修改翻译 cache schema。
8. 新增 `tools/Initialize-MigrationRuntime.ps1`，它从 `git rev-parse --show-toplevel` 计算根目录，设置并创建四个隔离路径，并断言它们全部位于 `<repo>/.runtime` 内。

cache 改动目标形态：

```python
CACHE_FOLDER = Path(
    os.getenv(
        "BABELDOC_CACHE_DIR",
        str(Path.home() / ".cache" / "babeldoc"),
    )
)
```

运行环境脚本的最小职责：

```powershell
$MigrationRoot = [System.IO.Path]::GetFullPath(
    (git rev-parse --show-toplevel).Trim()
)
if ($LASTEXITCODE -ne 0) {
    throw "无法解析迁移仓库根目录"
}

$ExpectedMigrationRoot = [System.IO.Path]::GetFullPath(
    "D:\codes\babeldoc-minimal-migration"
)
if ($MigrationRoot -ne $ExpectedMigrationRoot) {
    throw "迁移仓库根目录错误：$MigrationRoot"
}
Set-Location -LiteralPath $MigrationRoot

$RuntimeRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $MigrationRoot ".runtime")
)

$env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"
$env:BABELDOC_CACHE_DIR = Join-Path $RuntimeRoot "babeldoc-cache"
$env:TEMP = Join-Path $RuntimeRoot "temp"
$env:TMP = $env:TEMP

foreach ($RuntimePath in @(
    $env:UV_CACHE_DIR,
    $env:BABELDOC_CACHE_DIR,
    $env:TEMP,
    $env:TMP
)) {
    $ResolvedRuntimePath = [System.IO.Path]::GetFullPath($RuntimePath)
    if (-not $ResolvedRuntimePath.StartsWith(
        $RuntimeRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "运行路径越出 .runtime：$ResolvedRuntimePath"
    }
    New-Item -ItemType Directory -Force -Path $ResolvedRuntimePath | Out-Null
}
```

### 8.3 M0-R2/M0-GATE

每个命令先重新建立并验证隔离环境：

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv sync --frozen
uv run pytest -q `
    tests/minimal/test_runtime_isolation.py `
    tests/minimal/test_offline_cli_selection.py

uv run babeldoc `
    --files ".\examples\ci\test.pdf" `
    --only-parse-generate-pdf `
    --no-dual `
    --skip-scanned-detection `
    --working-dir ".\.runtime\m0\work" `
    --output ".\.runtime\m0\output"

uv run python -c `
    "import fitz,pathlib; p=next(pathlib.Path('.runtime/m0/output').glob('*.pdf')); d=fitz.open(p); assert len(d)>0; d.close(); print(p)"

uv run ruff check `
    babeldoc/const.py `
    babeldoc/main.py `
    babeldoc/translator/no_network.py `
    tests/minimal/test_runtime_isolation.py `
    tests/minimal/test_offline_cli_selection.py

git diff --check
```

M0 通过条件：

```text
cache 实际路径位于 .runtime/babeldoc-cache
offline CLI 不读取 credential
translator semantic request count = 0
parse-only exit 0
输出 PDF 可打开
旧 C22 目录无任何变化
```

候选提交：

```text
M0: isolate runtime and verify upstream baseline
```

---

## 9. M1：页面、连续链和唯一 ArticleDocumentIR

### 9.1 M1-R0，只读映射

执行者读取：

```text
DONOR_C16:babeldoc/magazine/**
DONOR_C16:configs/**
DONOR_C16:prompts/**
DONOR_C16:babeldoc/format/pdf/document_il/il_version_1.{py,rnc,rng,xsd}
DONOR_C16:babeldoc/format/pdf/high_level.py 中：
  StylesAndFormulas 后的 formula/page/chain/article hooks
DONOR_C16:spec_checks/spec_check_b1.py
DONOR_C16:spec_checks/spec_check_b2.py
DONOR_C16:spec_checks/spec_check_b4.py
DONOR_PRE_C22:spec_checks/spec_check_article_ir_contract.py（只读不变量，不复制 C18 工程层）
```

R0 必须给出：

```text
high_level 中精确插入窗口
ArticleBuilder 返回值如何保存
Page/PdfParagraph schema 字段清单
extension import closure 是否可在上游 base 导入
本阶段需要的最小 high_level diff
```

### 9.2 M1-R1，复制 extension 和 schema

先修改 `.gitignore`，允许跟踪 `/configs/*.json`。继续忽略 `examples/input/*.pdf`、`.runtime`、输出和 cache。

在 clean stage 状态下执行：

```powershell
$Donor = (git config --get migration.donorC16).Trim()

git restore --source=$Donor --worktree -- `
    babeldoc/magazine `
    configs `
    prompts `
    babeldoc/format/pdf/document_il/il_version_1.py `
    babeldoc/format/pdf/document_il/il_version_1.rnc `
    babeldoc/format/pdf/document_il/il_version_1.rng `
    babeldoc/format/pdf/document_il/il_version_1.xsd
```

新增 `babeldoc/magazine/minimal_pipeline.py`。本阶段只接：

```text
configure
formula_reclass（只在现有模块不改变文本时）
PageClassifier
ChainBuilder
ArticleBuilder
唯一 ArticleDocumentIR 保存
结构报告
```

`RunTrace` 可以由 extension 内部建立供后续模块读取；M1 不接最终 trace 合规、manifest 或 PDF validator。

### 9.3 M1 初始 allowlist

```text
.gitignore
babeldoc/magazine/**
configs/**
prompts/**
babeldoc/format/pdf/document_il/il_version_1.py
babeldoc/format/pdf/document_il/il_version_1.rnc
babeldoc/format/pdf/document_il/il_version_1.rng
babeldoc/format/pdf/document_il/il_version_1.xsd
babeldoc/format/pdf/high_level.py
tests/minimal/test_schema_roundtrip.py
tests/minimal/test_structure_pipeline.py
tests/minimal/test_structure_real_pdf.py
```

禁止修改 `translation_config.py` 和 `main.py`。

### 9.4 顺序不变量

```text
StylesAndFormulas 完成
→ formula_reclass（若接入）
→ PageClassifier
→ HITL page hook 在 M4 才启用
→ ChainBuilder
→ ArticleBuilder
→ 冻结唯一 ArticleDocumentIR
```

M1 采用 C16 顺序。若 selected sample 的 owner-scope test 复现跨 article chain，才评估 `8e398be` 的：

```text
ArticleBuilder.build_provisional
→ ChainBuilder(... provisional owners)
→ ArticleBuilder.finalize
```

### 9.5 M1-R2/M1-GATE

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run pytest -q `
    tests/minimal/test_schema_roundtrip.py `
    tests/minimal/test_structure_pipeline.py `
    tests/minimal/test_structure_real_pdf.py

uv run babeldoc `
    --files ".\examples\input\Courier-en.pdf" `
    --pages 7-8 `
    --skip-translation `
    --no-dual `
    --skip-scanned-detection `
    --working-dir ".\.runtime\m1\work" `
    --output ".\.runtime\m1\output"

git diff --check
```

必须断言：

```text
零翻译 API 请求
configs/vlm.json 的 enabled=false，结构阶段报告 vlm_enabled=false，页面分类模型请求数为 0
page classify、chain 和 article reports 存在
每个 processable paragraph 有稳定 ref
chain index 连续且无重复 member
每个 chain member 只有一个 article owner
运行中只有一个 canonical ArticleDocumentIR object identity
第二次构建尝试 fail-fast
skip-translation 仍输出可打开 PDF
```

候选提交：

```text
M1: migrate canonical magazine structure
```

---

## 10. M2：文章上下文、一次联合翻译和容量回填

### 10.1 M2-R0，只读映射

执行者读取：

```text
DONOR_C16:babeldoc/magazine/article_context.py
DONOR_C16:babeldoc/magazine/chain_translation.py
DONOR_C16:babeldoc/magazine/chain_backfill.py
DONOR_C16:babeldoc/magazine/short_unit.py
DONOR_C16:babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py diff
DONOR_C16:babeldoc/format/pdf/document_il/midend/typesetting.py diff
DONOR_C16:spec_checks/spec_check_chain_single_request.py
DONOR_C16:spec_checks/spec_check_chain_slot_backfill.py
DONOR_C16:spec_checks/spec_check_b6.py
```

R0 返回：

```text
chain plan 的 prepare/translate/apply 生命周期
claim 在 ordinary/cross-column/cross-page producer 的全部过滤点
article brief 注入点
typesetter slot measurement 所需的最小 symbols
donor 对 il_translator_llm_only.py/typesetting.py 的最小逐函数 diff
```

### 10.2 M2-R1a：翻译闭环

手工移植：

```text
plan article context
plan chain translation
创建不可变 claim
普通/跨栏/跨页 producer 跳过 claimed member
每条 chain 一次 semantic request
executor 全部关闭后 apply/backfill
普通非 chain 翻译保持上游路径
```

`ILTranslatorLLMOnly` 从 `translation_config.magazine_state` 或 `minimal_pipeline` 提供的同一 state 读取 `ArticleDocumentIR`。不得在翻译器内部调用 `ArticleBuilder`。

### 10.3 M2-R1b：排版容量 API

从 donor `typesetting.py` 只移植：

```text
SlotLineMetric
SlotFitResult
FIT_* constants
fit_text_to_slot
LINE_TAIL_FORBIDDEN_PUNCTUATION / 必需 line-head 规则
```

测量 API 必须：

```text
使用真实字体映射和断行器
只创建临时 units
不修改 docs、paragraph、page 或 PDF
返回最大合法 target prefix 和度量证据
```

不要复制 hang report、debug capture、selected-page 或 full trace 修改。

### 10.4 M2 allowlist

```text
babeldoc/magazine/minimal_pipeline.py
babeldoc/magazine/article_context.py（仅在适配必需时）
babeldoc/magazine/chain_translation.py（仅在适配必需时）
babeldoc/magazine/chain_backfill.py（仅在适配必需时）
babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py
babeldoc/format/pdf/document_il/midend/il_translator.py（只允许 identity/writeback 窄补丁）
babeldoc/format/pdf/document_il/midend/typesetting.py
babeldoc/format/pdf/high_level.py（只允许传递同一 state 或一个 hook）
tests/minimal/fakes.py
tests/minimal/test_article_context.py
tests/minimal/test_chain_single_request.py
tests/minimal/test_chain_backfill_capacity.py
tests/minimal/test_translation_invariants.py
```

### 10.5 M2-R2/M2-GATE

只使用 fake/recorded translator：

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run pytest -q `
    tests/minimal/test_article_context.py `
    tests/minimal/test_chain_single_request.py `
    tests/minimal/test_chain_backfill_capacity.py `
    tests/minimal/test_translation_invariants.py

uv run ruff check `
    babeldoc/magazine/minimal_pipeline.py `
    babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py `
    babeldoc/format/pdf/document_il/midend/typesetting.py `
    tests/minimal

git diff --check
```

硬断言：

```text
每条 chain semantic request count == 1
claimed ∩ ordinary == ∅
claimed ∩ cross_column == ∅
claimed ∩ cross_page == ∅
所有 chain member 共享同一 article brief
所有 member 都收到且只收到一次 backfill
规范化后的 fragments 拼接等于 whole target
续段不以禁排行首标点开始
slot measurement 前后 docs digest 相同
普通非 chain paragraph 仍翻译一次
malformed chain response fail-fast
```

候选提交：

```text
M2: migrate joint chain translation
```

---

## 11. M3：受限文章文本流与固定资产守恒

### 11.1 M3-R0，只读映射

读取：

```text
DONOR_C16:babeldoc/magazine/article_flow.py
DONOR_C16:babeldoc/magazine/cross_page_reflow.py
DONOR_C16:babeldoc/magazine/fixed_assets.py
DONOR_C16:babeldoc/magazine/transaction.py
DONOR_C16:babeldoc/magazine/acceptance.py
DONOR_C16:spec_checks/spec_check_article_cross_column.py
DONOR_C16:spec_checks/spec_check_article_cross_page.py
DONOR_C16:spec_checks/spec_check_fixed_asset_guard.py
DONOR_C16:spec_checks/spec_check_article_flow_ir.py
```

R0 必须区分：

```text
同页 slot 顺序
相邻物理页判断
owner hard boundary
固定资产 fingerprint
formula/rotated/furniture anchor
应用前后文本守恒
```

### 11.2 M3-R1

顺序固定为：

```text
翻译和 chain backfill 完成
→ paren_dedup
→ indent_policy
→ page-local article_flow
→ adjacent cross-page reflow
→ 正式 Typesetting
```

简化约束：

```text
只处理同一 ArticleDocumentIR owner
只处理相邻物理页
只处理明确支持的正文 slot
公式、旋转文本、标题、图片、表格、曲线和 form 固定
怀疑同页多文章时保持原 slot
无法证明合法时不移动并记录 typed reason
每次运行只做一次 flow pass
```

可以复用 donor 的局部 snapshot。禁止接入多动作 repair transaction 或多轮 acceptance。

### 11.3 M3 allowlist

```text
babeldoc/magazine/minimal_pipeline.py
babeldoc/magazine/article_flow.py（仅在适配必需时）
babeldoc/magazine/cross_page_reflow.py（仅在适配必需时）
babeldoc/magazine/fixed_assets.py（仅在适配必需时）
babeldoc/format/pdf/high_level.py
babeldoc/format/pdf/document_il/midend/typesetting.py（仅 flow 所需窄 API）
configs/article_flow.json
tests/minimal/test_article_flow_column.py
tests/minimal/test_article_flow_page.py
tests/minimal/test_fixed_assets.py
tests/minimal/test_flow_conservation.py
```

### 11.4 M3-R2/M3-GATE

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run pytest -q `
    tests/minimal/test_article_flow_column.py `
    tests/minimal/test_article_flow_page.py `
    tests/minimal/test_fixed_assets.py `
    tests/minimal/test_flow_conservation.py

uv run babeldoc `
    --files ".\examples\input\Courier-en.pdf" `
    --pages 7-8 `
    --skip-translation `
    --no-dual `
    --skip-scanned-detection `
    --working-dir ".\.runtime\m3\work" `
    --output ".\.runtime\m3\output"

git diff --check
```

硬断言：

```text
页数不变
源文本和 target 文本分别守恒
flow 不跨 owner
flow 不跨非相邻物理页
fixed asset digest 前后相同
formula/furniture/rotated lane 不移动
拒绝路径不产生半应用状态
输出 PDF 可打开
```

通过后标记：

```text
CORE_RUNNABLE at <verified SHA>
```

候选提交：

```text
M3: migrate bounded article flow
```

---

## 12. M4：HITL 两遍和首字装置

### 12.1 M4-R0，只读映射

读取：

```text
DONOR_C16:babeldoc/magazine/hitl.py
DONOR_C16:babeldoc/magazine/drop_cap.py
DONOR_C16:babeldoc/magazine/drop_cap_intent.py
DONOR_C16:babeldoc/magazine/drop_cap_render.py
DONOR_C16:babeldoc/magazine/detectors/drop_cap_geometry.py
DONOR_C16:babeldoc/format/pdf/document_il/midend/styles_and_formulas.py diff
DONOR_C16:babeldoc/format/pdf/document_il/midend/typesetting.py 的 glyph metric diff
DONOR_C16:spec_checks/spec_check_drop_cap_intent.py
DONOR_C16:spec_checks/spec_check_drop_cap_english.py
DONOR_C16:spec_checks/spec_check_drop_cap_chinese.py
DONOR_C16:spec_checks/spec_check_b7_3.py
```

不读取或迁移 pre-C22 的 v4 binder、delivery、manual expectation protocol。

### 12.2 固定两遍行为

reviews 根目录固定为源码树：

```text
reviews/<input-stem>.review.json
reviews/<input-stem>.decisions.json
```

每次运行：

1. 导出 machine review JSON 到 working-dir；若源码树没有同名 review，可写一份候选 review 到 `.runtime/reviews-generated/`。
2. 固定 decisions 文件存在时校验并应用。
3. decisions 不存在时使用 machine default，运行继续。
4. 无 HTML 要求。
5. 不覆盖用户已有 decisions。

M4-R1 必须显式加入本样本的固定 decisions。先在 `.gitignore` 的 `*.json` 规则后增加：

```gitignore
!/reviews/Courier-en.decisions.json
```

随后从冻结 donor 复制并验证：

```powershell
$Donor = (git config --get migration.donorC16).Trim()
$ExpectedDecisionBlob = "39b40b848671f41b3a6415cedbc4a0ecefc586ec"
$SourceDecisionBlob = (
    git rev-parse "${Donor}:reviews/Courier-en.decisions.json"
).Trim()

if ($LASTEXITCODE -ne 0 -or $SourceDecisionBlob -ne $ExpectedDecisionBlob) {
    throw "Courier decisions donor blob 不一致：$SourceDecisionBlob"
}

New-Item -ItemType Directory -Force -Path ".\reviews" | Out-Null
git restore --source=$Donor --worktree -- `
    "reviews/Courier-en.decisions.json"
if ($LASTEXITCODE -ne 0) {
    throw "复制 Courier decisions 失败"
}

$Decisions = Get-Content `
    -Raw `
    -LiteralPath ".\reviews\Courier-en.decisions.json" |
    ConvertFrom-Json

if (
    -not $Decisions.terms -or
    $Decisions.page_kinds."1" -ne "toc" -or
    $Decisions.drop_caps."p7#8" -ne "keep"
) {
    throw "Courier decisions 语义检查失败"
}
```

执行者不得从正在运行的旧工作目录读取该文件；唯一来源是固定 Git object。

最小 decisions 兼容 donor C16 简单结构：

```json
{
  "terms": {"source": "target"},
  "page_kinds": {"1": "toc"},
  "drop_caps": {"p7#8": "keep"}
}
```

存在 decisions 时，至少绑定 input stem、可解析 paragraph ref 和合法枚举；若另有 source hash 字段则必须匹配。无效文件直接失败。

上游 `--pages 7-8` 只把所选页放入 IL。固定 decisions 中指向未选物理页的合法条目（本文件的 page 1、`p4#3`、`p5#5`）必须记录为 `out_of_selected_scope` 并跳过；它们不算无效引用。指向已选页的 `p7#8` 必须成功绑定并应用。已选页内无法解析的引用或任何非法枚举仍 fail-fast。

### 12.3 首字顺序

```text
page classify 后应用 page_kinds
读取 decisions 后把 terms 合并到本次运行 glossary，并在首次 paragraph/chain 翻译前冻结；不重建已经由 CLI 构造的 translator client
翻译前冻结 drop-cap intent 和 keep/flatten
正式 Typesetting 后调用 drop_cap_render
detector 在最终首字几何上运行
```

目标语言路径：

```text
zh：两行嵌入式首字
en：单行放大首字母
flatten：普通正文，不生成额外首字 glyph
```

### 12.4 M4 allowlist

```text
.gitignore（仅 reviews decisions 跟踪规则）
reviews/Courier-en.decisions.json
babeldoc/magazine/minimal_pipeline.py
babeldoc/magazine/hitl.py（仅在最小适配必需时）
babeldoc/magazine/drop_cap*.py（仅在最小适配必需时）
babeldoc/format/pdf/high_level.py
babeldoc/format/pdf/document_il/midend/styles_and_formulas.py
babeldoc/format/pdf/document_il/midend/typesetting.py（仅 glyph_ink_metrics）
babeldoc/format/pdf/document_il/utils/formular_helper.py（只有测试证明 Mono 误判时）
configs/hitl.json
configs/drop_cap.json
configs/drop_cap_render.json
configs/initial_adjacent.json
tests/minimal/test_hitl_export_apply.py
tests/minimal/test_drop_cap_keep_flatten.py
tests/minimal/test_drop_cap_english.py
tests/minimal/test_drop_cap_chinese.py
```

### 12.5 M4-R2/M4-GATE

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run pytest -q `
    tests/minimal/test_hitl_export_apply.py `
    tests/minimal/test_drop_cap_keep_flatten.py `
    tests/minimal/test_drop_cap_english.py `
    tests/minimal/test_drop_cap_chinese.py

git diff --check
```

硬断言：

```text
无 decisions 时 review 可导出且运行继续
有 decisions 时三类决定在正确阶段处理；terms 与 p7#8 应用，未选页决定合法跳过
未选页的合法决定记录 out_of_selected_scope；已选页内无效 paragraph ref 或任何非法枚举 fail-fast
keep 不造成源首字和目标首字重复
flatten 不生成装饰 glyph
英文和中文 geometry 各自满足 synthetic contract
首字颜色继承源 intent
首字不侵入固定资产
```

候选提交：

```text
M4: migrate HITL and drop caps
```

---

## 13. M5：检测、最多一次修复和最终验证

### 13.1 M5-R0，只读映射

读取：

```text
DONOR_C16:babeldoc/magazine/detectors/**
DONOR_C16:babeldoc/magazine/react/controller.py
DONOR_C16:babeldoc/magazine/react/actions.py
DONOR_C16:babeldoc/magazine/acceptance.py
DONOR_C16:babeldoc/magazine/transaction.py
DONOR_C16:babeldoc/magazine/final_pdf_validator.py
DONOR_C16:spec_checks/spec_check_b8.py
DONOR_C16:spec_checks/spec_check_repair_transaction.py
DONOR_C16:spec_checks/spec_check_pdf_compliance.py
```

R0 只提取最小调用路径。C18 forced tool transport 和 C19–C21 contract 不进入。
若 `babeldoc.magazine.detectors.__init__` 会连带导入 runtime profile、完整 taxonomy、checkpoint 或复杂 controller，新增 `minimal_detection.py` 直接调用本节固定 detector；禁止为复用统一入口而重新接入排除层。

### 13.2 检测范围

固定检测：

```text
未译残留/孤立可译文本
页面越界
新增文字碰撞
异常碎片
chain/backfill 守恒
fixed asset 漂移
```

只读 detector 可以写 `issues.before.json` 和 `issues.after.json`。

### 13.3 一次修复

固定流程：

```python
issues_before = detect(docs)
action = select_at_most_one_allowed_action(issues_before)
if action is not None:
    snapshot = snapshot_affected_state(docs, action)
    apply(action)
    retypeset_affected_paragraphs()
    issues_after = detect(docs)
    if not strictly_better(issues_before, issues_after):
        restore(snapshot)
        issues_after = detect(docs)
else:
    issues_after = issues_before
```

许可动作只保留：

```text
translate_orphan_text
refit_or_reflow_owned_paragraph
no_op
```

规则：

```text
每次运行最多一个 action
无多轮循环
无通用 tool-call transport
无 action retry
无跨 article repair
无 fixed asset 修改
accept 必须严格减少目标 hard issue 且不新增 hard issue
reject 必须完整恢复受影响状态
```

若现有 controller 很难裁剪，新增一个短 `minimal_repair.py` 包装现有 action primitives；禁止整体接入复杂 controller。

### 13.4 最小最终 validator

新增：

```text
tools/verify_minimal_pdf.py
```

它只做：

```text
输出文件存在且唯一可识别
PyMuPDF reopen 成功
输入与输出页数相同
paid 验证时 pages 7–8 可提取 target 文本；`--allow-untranslated` 离线模式只要求正文文本可提取
box 坐标有限且有序
minimal_run.report.json 与 issues sidecar 存在
chain request/backfill/fixed asset/repair 计数满足不变量
```

不要移植 C15/C20C 完整状态机。

### 13.5 M5 allowlist

```text
babeldoc/magazine/minimal_pipeline.py
babeldoc/magazine/minimal_detection.py（如统一 detector 入口带入排除层）
babeldoc/magazine/minimal_repair.py（如需要）
babeldoc/magazine/detectors/**（仅最小适配）
babeldoc/magazine/react/actions.py（仅复用 primitive 的窄适配）
babeldoc/format/pdf/high_level.py
babeldoc/format/pdf/document_il/midend/typesetting.py（仅 affected retypeset API）
configs/detectors.json
configs/repair_actions.json
tools/verify_minimal_pdf.py
minimal.en-zh.toml
tests/minimal/test_detectors.py
tests/minimal/test_one_repair.py
tests/minimal/test_repair_rollback.py
tests/minimal/test_minimal_pdf_validator.py
```

### 13.6 M5-R2/M5-GATE

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run pytest -q `
    tests/minimal/test_detectors.py `
    tests/minimal/test_one_repair.py `
    tests/minimal/test_repair_rollback.py `
    tests/minimal/test_minimal_pdf_validator.py

uv run babeldoc `
    --config ".\minimal.en-zh.toml" `
    --files ".\examples\input\Courier-en.pdf" `
    --pages 7-8 `
    --skip-translation `
    --no-dual `
    --skip-scanned-detection `
    --working-dir ".\.runtime\m5\work" `
    --output ".\.runtime\m5\output"

uv run python tools/verify_minimal_pdf.py `
    --source ".\examples\input\Courier-en.pdf" `
    --output-dir ".\.runtime\m5\output" `
    --run-dir ".\.runtime\m5\work" `
    --allow-untranslated

git diff --check
```

硬断言：

```text
translation API request count = 0
detector 执行一次；有 action 时再执行一次
action count <= 1
malformed/unallowed action fail-fast
拒绝的 action 完整回滚
页数不变
PDF 可打开、文本可提取
minimal_run.report.json 记录 chain/ordinary/backfill/flow/dropcap/issues/repair 计数
```

本阶段同时提交无 secret 的固定 `minimal.en-zh.toml`，内容采用第 14.5 节。M5 离线 gate 必须用 `--skip-translation` 验证该 TOML 可解析。

通过后标记：

```text
MINIMAL_FEATURE_COMPLETE at <verified SHA>
```

候选提交：

```text
M5: add bounded detection and repair
```

---

## 14. M6：总门与唯一真实翻译 smoke

### 14.1 M6.1 全离线总门

C22 是否结束不影响本节。全部命令必须使用独立环境变量。

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run pytest -q tests/minimal

$MinimalLintPaths = @(
    "babeldoc/magazine/minimal_pipeline.py",
    "babeldoc/magazine/minimal_detection.py",
    "babeldoc/magazine/minimal_repair.py",
    "babeldoc/magazine/article_builder.py",
    "babeldoc/magazine/article_context.py",
    "babeldoc/magazine/article_flow.py",
    "babeldoc/magazine/article_ir.py",
    "babeldoc/magazine/chain_backfill.py",
    "babeldoc/magazine/chain_builder.py",
    "babeldoc/magazine/chain_translation.py",
    "babeldoc/magazine/cross_page_reflow.py",
    "babeldoc/magazine/drop_cap.py",
    "babeldoc/magazine/drop_cap_intent.py",
    "babeldoc/magazine/drop_cap_render.py",
    "babeldoc/magazine/fixed_assets.py",
    "babeldoc/magazine/hitl.py",
    "babeldoc/magazine/page_classifier.py",
    "babeldoc/magazine/page_features.py",
    "babeldoc/magazine/react/actions.py",
    "babeldoc/const.py",
    "babeldoc/main.py",
    "babeldoc/translator/no_network.py",
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py",
    "babeldoc/format/pdf/document_il/midend/typesetting.py",
    "tools/verify_minimal_pdf.py",
    "tests/minimal"
) | Where-Object { Test-Path -LiteralPath $_ }

uv run ruff check -- $MinimalLintPaths

git diff --check migration-base-v0.6.4..HEAD
git status --short --branch
```

M1 整包复制但未接线的 extension 文件不属于最终 lint 门；M6.2 必须确认它们没有被 `minimal_pipeline` 或 `minimal_detection` 导入。固定执行路径、上游接线文件和所有最小测试仍全部进入 lint。

再运行一次真实 PDF 离线 smoke：

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run babeldoc `
    --config ".\minimal.en-zh.toml" `
    --files ".\examples\input\Courier-en.pdf" `
    --pages 7-8 `
    --skip-translation `
    --no-dual `
    --skip-scanned-detection `
    --working-dir ".\.runtime\m6\offline\work" `
    --output ".\.runtime\m6\offline\output"

uv run python tools/verify_minimal_pdf.py `
    --source ".\examples\input\Courier-en.pdf" `
    --output-dir ".\.runtime\m6\offline\output" `
    --run-dir ".\.runtime\m6\offline\work" `
    --allow-untranslated
```

### 14.2 M6.2 diff 审计

主控检查：

```powershell
$Base = (git config --get migration.baseCommit).Trim()

git log --oneline --decorate "$Base..HEAD"
git diff --stat "$Base..HEAD"
git diff --name-status "$Base..HEAD"
git diff "$Base..HEAD" -- `
    babeldoc/format/pdf/high_level.py `
    babeldoc/main.py `
    babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py `
    babeldoc/format/pdf/document_il/midend/typesetting.py
```

必须确认：

```text
上游集中式文件是逐函数窄 diff
没有 runtime profile/CLI magazine mode
没有 C18–C21 transport/binder/journal
没有 secret、原始 provider response 或真实 prompt 被提交
没有 input PDF、output、cache 被提交
工作树干净
```

### 14.3 M6.3 等待 C22 终态

若用户尚未明确告知 C22 已结束：

```text
状态：MINIMAL_FEATURE_COMPLETE / PAID_GATE_DEFERRED
Translation API request started: no
Paid attempt consumed: no
```

停止当前轮次。不得自行检查或停止旧仓库进程。

用户明确确认 C22 已结束后，主控才进入 M6.4。C22 新 commit 不自动导入；如需比较，另建后续只读审计任务。

### 14.4 M6.4 付费前置条件

以下必须全部成立：

```text
M0–M5 verified
M6.1/M6.2 全绿
工作树干净
Courier-en.pdf hash = 9fcb6b5e...
OPENAI_API_KEY configured，值不打印
固定 model/provider 已确认
working/output/cache 均在新仓库 .runtime
本迁移 paid attempt count = 0
C22 已明确终止
```

检查 key 只判断存在：

```powershell
if (-not $env:OPENAI_API_KEY) {
    throw "OPENAI_API_KEY 未配置"
}
```

不要输出 key 的值、长度、首尾字符或 hash。

### 14.5 M6.5 唯一一次 paid CLI job

M5 已提交无 secret 的固定配置：

```text
minimal.en-zh.toml
```

固定内容：

```toml
[babeldoc]
lang-in = "en"
lang-out = "zh"
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

主控执行；执行 Agent 不接触 credential：

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run babeldoc `
    --config ".\minimal.en-zh.toml" `
    --files ".\examples\input\Courier-en.pdf" `
    --pages 7-8 `
    --no-dual `
    --no-auto-extract-glossary `
    --skip-scanned-detection `
    --working-dir ".\.runtime\m6\paid\work" `
    --output ".\.runtime\m6\paid\output"
```

说明：

```text
不使用 --only-include-translated-page；保留完整 PDF 页映射
只翻译 source pages 7–8
不使用 --ignore-cache
不切换 model/provider
不运行参数 sweep
不运行第二个 CLI paid job
```

### 14.6 付费失败语义

```text
首个翻译 API 请求前失败：paid attempt 未消费；保存证据并回到所属离线门
任何翻译 API 请求发出后失败：paid attempt 已消费；本计划禁止重试
provider 余额/权限/rate limit：BLOCKED_EXTERNAL_PROVIDER；不换 provider/model
超时：先确认进程终止；禁止盲目重启
```

### 14.7 M6.6 自动验收

```powershell
. ".\tools\Initialize-MigrationRuntime.ps1"

uv run python tools/verify_minimal_pdf.py `
    --source ".\examples\input\Courier-en.pdf" `
    --output-dir ".\.runtime\m6\paid\output" `
    --run-dir ".\.runtime\m6\paid\work" `
    --translated-pages 7,8
```

必须：

```text
CLI exit 0
输出 PDF 可 reopen
输出页数与输入相同
pages 7–8 target text 非空并包含目标语言文本
每条连续链只产生一次请求
claimed member 未进入普通翻译
backfill 覆盖全部 member 且 target 守恒
article flow 不跨 owner/非相邻页
fixed asset digest 不变
Courier-en decisions 被发现并应用
中文首字路径已执行或有明确 typed no-candidate reason
detector 已执行
repair action count <= 1
无未处理异常
```

技术验收通过后状态：

```text
MINIMAL_DELIVERY_PASS
```

如果自动验收通过但用户尚未查看 pages 7–8，可额外记录：

```text
Visual review: pending
```

视觉复核不阻止代码状态成立。

---

## 15. 最终报告

主控写：

```text
.runtime/m6/final-report.md
```

内容：

```text
最终状态
UPSTREAM_BASE / DONOR_C16 / 当前 HEAD
M0–M5 verified SHA
工作树状态
修改文件列表
各阶段命令和 exit code
Courier-en input hash
外部请求是否发出
paid CLI job count
输出 PDF 路径和 hash
page/chain/article/backfill/flow/drop-cap/issues/repair 计数
第一条 residual 或 blocker
旧 C22 仓库是否被访问（必须为 no，用户初始化复制除外）
下一条唯一建议动作
```

最终状态只能取：

```text
CORE_RUNNABLE
MINIMAL_FEATURE_COMPLETE
MINIMAL_FEATURE_COMPLETE / PAID_GATE_DEFERRED
MINIMAL_DELIVERY_PASS
BLOCKED
FAIL
```

---

## 16. 停止条件

出现以下任一项立即停止当前阶段：

```text
仓库根目录或分支不符
出现第二个 worktree 或开发分支
存在来源不明的 dirty 修改
固定 SHA 对象缺失或 ancestry 校验失败
运行 cache/working/output 指向旧 C22 目录
迁移 Agent 尝试进入旧仓库
执行者尝试整体覆盖集中式上游文件
需要 merge/cherry-pick donor
同一 chain 多次翻译
claimed 段落进入普通翻译
ArticleDocumentIR 被重建
fixed asset 改变
三轮修复仍无法通过阶段门
继续必须引入明确排除的 C18–C21 工程层
C22 仍运行且下一步需要翻译 API
paid job 发出请求后失败
需要第二次 paid job、整本参数 sweep 或更换 provider/model
```

停止报告必须包含：

```text
阶段和轮次
仓库路径和分支
last verified SHA / current HEAD
git status --short
git diff --stat
最近命令和 exit code
第一条有效错误
运行 session/PID
translation API 是否已经发出请求
paid attempt 是否消费
修改文件和日志路径
旧 C22 仓库是否被触碰
下一条唯一动作
```

---

## 17. 执行 Agent 固定提示词

主控创建唯一执行者时附上：

```markdown
You are `migration_executor`, the sole implementation agent for the minimal
BabelDOC migration.

Repository: D:\codes\babeldoc-minimal-migration
Branch: migration/minimal-v0.6.4
Upstream base: 17480db9df92ddcb37349ce34b312335226e8ec9
Primary donor: 57a12552da7a13523ad5a2e27b45473f24183208
Pre-C22 donor: 3a315b947ef5b04a7de4ac7f047bdfd06bea5e3b

Work only in the supplied repository and branch. Do not create branches,
worktrees, sub-agents, or parallel implementation tasks. Do not access or
modify D:\codes\magazine-translation. Read donor code only through pinned Git
objects using git show, git diff, or the explicitly authorized one-time restore
of extension-package paths in M1.

Complete only the named round. Return to the controller after that round. Do
not enter the next round or stage without a follow-up task.

Before editing, verify repository root, branch, HEAD, worktree count, working
tree status, and isolated runtime environment variables. Preserve upstream
orchestration files and apply narrow function-level hooks.

Until the controller explicitly opens M6 paid execution after C22 ends, never
make a translation, term-extraction, VLM, or repair model request. Use fake or
NoNetwork translators only.

Treat a 600-second wait expiry as a polling event. Preserve state. Before
repeating a long command, inspect its earlier session, PID, log, and output.

Use fail-fast behavior for invalid internal state. Do not hide failure with
broad exception handling. Do not reset, clean, stash, force-push, merge, rebase,
or cherry-pick.

At the end of each round report:
- stage, round, and status;
- HEAD and last verified SHA;
- changed paths;
- commands and exit codes;
- running session/PID;
- translation API and paid-attempt status;
- first relevant failure, if any;
- exact next recommended action.
```

---

## 18. 中断恢复与最终 push

### 18.1 会话中断后

用户或新主控先运行：

```powershell
Set-Location "D:\codes\babeldoc-minimal-migration"

if (Test-Path -LiteralPath ".\tools\Initialize-MigrationRuntime.ps1") {
    . ".\tools\Initialize-MigrationRuntime.ps1"
} else {
    # 仅供 M0-R1 尚未创建脚本时恢复；不得运行 Python/uv/BabelDOC。
    $RuntimeRoot = [System.IO.Path]::GetFullPath(".\.runtime")
    $env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"
    $env:BABELDOC_CACHE_DIR = Join-Path $RuntimeRoot "babeldoc-cache"
    $env:TEMP = Join-Path $RuntimeRoot "temp"
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Force -Path `
        $env:UV_CACHE_DIR, `
        $env:BABELDOC_CACHE_DIR, `
        $env:TEMP | Out-Null
}

$Base = (git config --get migration.baseCommit).Trim()
$Branch = (git branch --show-current).Trim()

git status
git log --oneline --decorate -12
git reflog --date=local -12
git worktree list

if ($Branch -ne "migration/minimal-v0.6.4") {
    throw "当前分支错误：$Branch"
}

git merge-base --is-ancestor $Base HEAD
if ($LASTEXITCODE -ne 0) {
    throw "当前 HEAD 脱离固定基线"
}
```

恢复消息：

```text
上次会话中断。保留全部现有修改和进程状态。
完整读取计划，检查 git status、log、diff、.runtime/migration-state.md 和最近日志。
读取 executor canonical ID、generation 和最后状态；确认最后 verified SHA 和未完成轮次，优先复用原 migration_executor。
原 ID 无法寻址时，严格执行第 5.5 节 replacement 五项前置检查；无法证明旧写入者和进程终止时停止。
不要 reset、clean、stash、reclone 或重跑尚未确认终止的命令。
```

### 18.2 阶段通过后推送

主控确认工作树干净后：

```powershell
git push --set-upstream origin "migration/minimal-v0.6.4"
if ($LASTEXITCODE -ne 0) {
    throw "迁移分支 push 失败"
}

git ls-remote --heads origin `
    "refs/heads/migration/minimal-v0.6.4"
if ($LASTEXITCODE -ne 0) {
    throw "无法验证远端迁移分支"
}
```

只推送这个分支。禁止：

```text
git push origin HEAD:main
git push --all
git push --tags
git push --force
```

### 18.3 最终人工检查

```powershell
$Base = (git config --get migration.baseCommit).Trim()

git status --short --branch
git log --oneline --decorate "$Base..HEAD"
git diff --stat "$Base..HEAD"
git diff --check "$Base..HEAD"
git diff --name-status "$Base..HEAD"

git grep -n -I -E `
    "sk-[[:alnum:]_-]{20,}|OPENAI_API_KEY[[:space:]]*=" `
    HEAD -- .
```

示例变量名可能命中；人工确认不存在真实 key。输入 PDF、`.runtime`、cache、output 和 provider 原始响应均不得出现在提交中。

---

## 19. 完成定义

本计划的最小成功条件：

1. 从 `17480db...` 建立唯一迁移分支。
2. C22 旧仓库和进程未被迁移 Agent 触碰。
3. extension 算法来自固定 `57a1255...` donor。
4. 上游集中式文件保持窄 diff。
5. 正常运行没有 magazine mode/profile/用户 feature flags。
6. M0–M5 离线门全部通过。
7. `Courier-en.pdf` pages 7–8 的唯一一次 paid job 完成。
8. 输出 PDF 可打开、页数与输入相同、目标文本可提取。
9. chain 单请求、claim 排除、backfill 守恒、owner/asset 边界成立。
10. HITL、中文首字、detector 和最多一次 repair 均执行或给出合法 typed no-candidate 状态。
11. 没有第二次 paid job。
12. 当前分支已推送，工作树干净，最终报告存在。

满足 1–12 且自动验收通过时，状态为 `MINIMAL_DELIVERY_PASS`。
