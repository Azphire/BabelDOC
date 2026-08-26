# BabelDOC Magazine

BabelDOC Magazine 是基于 [funstory-ai/BabelDOC](https://github.com/funstory-ai/BabelDOC) 0.6.4 扩展的杂志 PDF 版式保持翻译研究原型。项目面向原生数字 PDF，在固定页数、可检索文本和视觉资产保护的约束下，研究文章级上下文翻译、跨栏与跨页文本流、首字装置和可审计修复。

当前主评估方向为英文到中文。中文到英文已接入同一运行链，仍处于探索性验证阶段。输出适合研究对比、演示和低成本在线多语阅读试验；正式出版前需要人工校对与版面复核。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 统一命令入口 | 已有：`babeldoc` / `uv run babeldoc` |
| 杂志运行入口 | `--magazine-mode` 内置模式；`--magazine-profile` 自定义模式 |
| 内置模式 | `conservative`、`automatic`、`hitl-export`、`hitl-apply` |
| 发布形态 | 源码树与 wheel 均包含杂志配置和提示词资源 |
| 凭据 | CLI/TOML 显式 key 优先，空值回退到 `OPENAI_API_KEY` |
| Python | `>=3.10,<3.14` |
| 翻译服务 | OpenAI 兼容接口 |
| 主要输入 | 带文本层的原生数字 PDF |
| 明确边界 | 不实现同页多文章身份隔离；扫描件不属于主研究范围 |

这些入口、资源打包与短门禁由 [`plans/codex_plan_C16.md`](plans/codex_plan_C16.md) 统一收口。

## 核心能力

- 通过页面类型、连续链和 `ArticleDocumentIR` 建立跨页文章状态。
- 将同一连续链执行一次联合翻译，再按实测容量重新分配到原有栏位。
- 在同一文章区域内执行有边界的跨栏、相邻跨页文本回填。
- 对图片、表格、公式和受保护文本建立固定资产清单与几何守卫。
- 使用 `RunTrace` 连接源元素、文章、翻译请求、目标片段、修复代次和最终几何。
- 支持人工复核草稿与决定文件，覆盖术语、页面类型和首字装置。
- 分别实现英文凸起首字母与中文两行首字装置，并记录源颜色与几何证据。
- 在写出 PDF 前执行检测和有界修复，在写出后重新打开 PDF 执行合规检查。

## 设计边界

项目遵守以下版面约束：

- 输出页数保持不变，不通过新增页面解决溢出。
- 正文翻译保持为可检索文本。
- 图片、表格、公式、页眉页脚等固定视觉资产不能随文章文本流漂移。
- 跨页重排仅在已确认属于同一文章的相邻页面之间进行。
- 同页多文章身份隔离没有实现。此类页面会进入受限路径或记录为不支持状态。
- 扫描件检测仍保留上游能力，OCR 版面恢复不属于本扩展的主要目标。
- 检测与修复采用确定性规则、有限动作集合、单调验收和原子回滚。

## 架构

```mermaid
flowchart TB
    A["CLI、TOML 与运行 profile"] --> B["PDF 解析与 Document IL"]
    B --> C["页面策略、连续链与 Article IR"]
    C --> D["普通翻译与连续链联合翻译"]
    D --> E["实测容量分配与文章文本流"]
    E --> F["排版与首字装置渲染"]
    F --> G["检测、有界修复与事务回滚"]
    G --> H["PDF 写出与最终合规检查"]
    C -.-> I["人工复核草稿与决定"]
    I -.-> D
```

### 主要模块

| 路径 | 职责 |
| --- | --- |
| `babeldoc/main.py` | 命令行解析、翻译器和布局模型初始化、单文件或多文件调度 |
| `babeldoc/format/pdf/high_level.py` | PDF 到 IL、翻译、排版、写出和最终合规检查的总流水线 |
| `babeldoc/format/pdf/document_il/` | 上游 Document IL、解析中间件和排版实现 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | 当前 LLM 翻译主路径；接入文章上下文、连续链和运行追踪 |
| `babeldoc/magazine/runtime_profile.py` | 严格加载 22 个功能开关、校验依赖并写运行清单 |
| `babeldoc/magazine/page_classifier.py` | 页面类型识别及页面策略证据 |
| `babeldoc/magazine/chain_builder.py` | 跨栏、跨页连续链检测 |
| `babeldoc/magazine/article_builder.py`、`article_ir.py` | 构建稳定文章标识、区域槽位和跨页索引 |
| `babeldoc/magazine/article_context.py` | 从规范文章状态构建文章级翻译上下文 |
| `babeldoc/magazine/chain_translation.py` | 连续链一次联合翻译、失败状态和守恒记录 |
| `babeldoc/magazine/chain_backfill.py` | 按实测排版容量分配联合译文 |
| `babeldoc/magazine/article_flow.py` | 文章内跨栏文本流与事务提交 |
| `babeldoc/magazine/cross_page_reflow.py` | 相邻页面间的受限文章文本流 |
| `babeldoc/magazine/fixed_assets.py` | 固定资产识别、摘要与漂移检查 |
| `babeldoc/magazine/run_trace.py` | 源元素到最终几何的运行内追踪和守恒验证 |
| `babeldoc/magazine/drop_cap*.py` | 首字候选、语言策略、颜色继承、几何渲染和回滚守卫 |
| `babeldoc/magazine/detectors/` | 越界、碰撞、残留、资产漂移、所有权和守恒检查 |
| `babeldoc/magazine/transaction.py`、`acceptance.py` | 修复快照、原子回滚和单调验收 |
| `babeldoc/magazine/hitl.py` | 人工复核草稿导出、决定文件校验与应用 |
| `babeldoc/magazine/final_pdf_validator.py` | 重新打开最终 PDF，检查页数、文本、几何、资产和首字装置 |
| `configs/` | 页面策略、阈值、动作集合、profile 与合规规则 |
| `prompts/` | 版本化提示模板；运行时写入模板摘要清单 |
| `spec_checks/` | 批次规格检查与语料门禁 |

### 运行顺序

1. `runtime_profile` 在创建 IL 前加载 profile、校验开关依赖，并写入 `magazine_run_manifest.json`。
2. 上游解析器生成 Document IL，完成布局、段落、样式和公式处理。
3. 杂志扩展依次执行公式重分类、页面分类、连续链检测和文章归并。
4. `ArticleBuilder` 生成规范 `ArticleDocumentIR`，`RunTrace` 从该状态建立源记录。
5. 自动术语抽取和人工复核决定在翻译器创建前生效。
6. 普通段落进入 LLM-only 翻译路径；已确认连续链可进入一次联合翻译路径。
7. 译文按实测容量回填，在文章区域内执行跨栏和受限跨页文本流。
8. 排版完成后渲染首字装置，再运行确定性检测和已启用的修复动作。
9. PDF 写出后由最终验证器重新打开，生成合规状态，并把结果绑定回 `RunTrace`。

## 安装

### 前置条件

- Git
- [uv](https://docs.astral.sh/uv/)
- Python 3.10、3.11、3.12 或 3.13
- 可访问的 OpenAI 兼容接口及对应 API key

仓库提交 `uv.lock`。源码运行建议使用锁定环境：

```bash
git clone https://github.com/Azphire/BabelDOC.git
cd BabelDOC
uv sync --locked
```

首次运行前下载并校验布局模型与字体资源：

```bash
uv run babeldoc --warmup
```

### wheel 安装

wheel 内已包含 `configs/*.json` 和 `prompts/*.md`，安装后不需依赖仓库根目录。可在本地构建并安装到独立环境：

```bash
uv build --wheel --no-build-isolation
uv venv .venv-wheel
uv pip install --python .venv-wheel dist/babeldoc-0.6.4-py3-none-any.whl
```

Linux/macOS 从安装环境启动：

```bash
./.venv-wheel/bin/babeldoc --magazine-mode conservative --validate-config
```

Windows PowerShell 对应入口为：

```powershell
& .\.venv-wheel\Scripts\babeldoc.exe --magazine-mode conservative --validate-config
```

`spec_checks/spec_check_startup_distribution.py` 会在系统临时目录重建 wheel、安装到独立 venv，并从仓库外目录校验命令入口、包内资源和 manifest 逻辑路径。

## 快速启动

正常翻译仍必须显式选择 `--openai`。如果 CLI 或 TOML 未提供 `openai-api-key`，CLI 会自动读取 `OPENAI_API_KEY`。

### 保守模式

`conservative` 保留与既有 `magazine_runtime_profile.v1.json` 相同的部分功能组合，适合先进行低变更面运行：

```bash
export OPENAI_API_KEY="your-api-key"

uv run babeldoc \
  --files /absolute/path/to/input.pdf \
  --openai \
  --openai-model gpt-4o-mini \
  --lang-in en \
  --lang-out zh \
  --magazine-mode conservative \
  --working-dir runs/work \
  --output runs/output
```

### 自动模式

`automatic` 在 22 个开关中只关闭 HITL export/apply，启用其余自动功能链。先在不加载模型、不强制凭据的分支检查配置：

```bash
uv run babeldoc --magazine-mode automatic --validate-config
uv run babeldoc --magazine-mode automatic --print-effective-config
```

然后执行翻译：

```bash
export OPENAI_API_KEY="your-api-key"

uv run babeldoc \
  --files /absolute/path/to/input.pdf \
  --openai \
  --openai-model gpt-4o-mini \
  --lang-in en \
  --lang-out zh \
  --magazine-mode automatic \
  --working-dir runs/work \
  --output runs/output
```

Windows PowerShell 中可使用同一入口：

```powershell
$env:OPENAI_API_KEY = "your-api-key"

uv run babeldoc `
  --files "C:\path\to\input.pdf" `
  --openai `
  --openai-model gpt-4o-mini `
  --lang-in en `
  --lang-out zh `
  --magazine-mode automatic `
  --working-dir runs/work `
  --output runs/output
```

凭据优先级为：

1. CLI 或 TOML 中显式提供的主 key。
2. 显式值为空时的 `OPENAI_API_KEY`。
3. term extraction 显式 key；未设置时回退到上述最终主 key。

`--print-effective-config` 中的 key 始终是 `<redacted>` 或 `null`，base URL 不显示查询参数。不要把真实密钥写入仓库 TOML、命令历史或调试产物。

常用调整：

- 中文到英文：`--lang-in zh --lang-out en`
- 自定义兼容接口：增加 `--openai-base-url https://host.example/v1`
- 只生成单语 PDF：增加 `--no-dual`
- 只生成双语 PDF：增加 `--no-mono`
- 限定页码：增加 `--pages 1-5,8`
- 禁用自动术语抽取：增加 `--no-auto-extract-glossary`
- 查看全部参数：`uv run babeldoc --help`

`--working-dir runs/work` 会为每个输入文件追加文件名 stem。例如 `input.pdf` 的审计文件位于 `runs/work/input/`。

### 仅解析烟雾测试

`--only-parse-generate-pdf` 与明确跳过翻译的路径使用无网络翻译器：不需要 `--openai`，不读取 key，也不构造 OpenAI 客户端。

```bash
uv run babeldoc \
  --files examples/ci/test.pdf \
  --only-parse-generate-pdf \
  --skip-scanned-detection \
  --output runs/parse-only
```

首次真实 PDF 解析仍可能需要 `--warmup` 下载布局和字体资源，但不会访问翻译服务。

## 配置

项目有三层配置：

1. CLI 或 TOML：输入输出、语言、服务、并发和通用 PDF 选项。
2. 运行 profile：统一启用或停用杂志功能。
3. `configs/*.json` 与 `prompts/*.md`：算法阈值、封闭枚举、动作集合和提示模板。

### TOML 配置

`configargparse` 读取 `[babeldoc]` 表。建议只保存非敏感参数，密钥由 `OPENAI_API_KEY` 提供。

```toml
[babeldoc]
lang-in = "en"
lang-out = "zh"
output = "runs/output"
working-dir = "runs/work"
debug = true

openai = true
openai-model = "gpt-4o-mini"
qps = 4
pool-max-workers = 4
term-pool-max-workers = 2

magazine-mode = "automatic"
watermark-output-mode = "no_watermark"
no-dual = true
skip-scanned-detection = false
auto-extract-glossary = true
```

运行：

```bash
export OPENAI_API_KEY="your-api-key"
uv run babeldoc \
  --config local.toml \
  --files /absolute/path/to/input.pdf
```

`local.toml` 当前没有被 `.gitignore` 自动排除。请勿在其中保存密钥；需要本机专用参数时，可把文件名加入 `.git/info/exclude`。

### 杂志运行 profile

`configs/magazine_runtime_profile.v1.json` 使用严格结构：

```json
{
  "format_version": 1,
  "profile": "magazine-runtime",
  "version": 1,
  "switches": {
    "magazine_checkpoint": true
  }
}
```

上例只用于展示外层结构，不能直接运行。实际 profile 必须完整声明全部 22 个布尔开关，不能包含未知键。创建自定义 profile 时，请复制仓库内完整文件后修改值。

内置 profile 与用途如下：

| `--magazine-mode` | profile 资源 | 22 开关策略 | 适用阶段 |
| --- | --- | --- | --- |
| `conservative` | `magazine_runtime_profile.v1.json` | 保守组合，关闭联合翻译、文章上下文、HITL、首字和修复等高影响开关 | 快速基线与低变更面运行 |
| `automatic` | `magazine_runtime_profile.automatic.v1.json` | 除 `magazine_hitl_export` / `magazine_hitl_apply` 外全开 | 无人工决定的完整自动链 |
| `hitl-export` | `magazine_runtime_profile.hitl_export.v1.json` | `automatic` 加导出复核草稿 | HITL 第一次运行 |
| `hitl-apply` | `magazine_runtime_profile.hitl_apply.v1.json` | 22 开关全开，并要求匹配的 decisions 文件 | HITL 第二次运行 |

开关之间存在显式依赖。例如联合翻译依赖连续链检测，首字渲染依赖标记与应用，旋转文本通道依赖修复，文章文本流依赖检测、检查点和文章归并。依赖不满足时，流水线会在 IL 创建前终止，并把原因写入运行清单。

`--magazine-mode` 与 `--magazine-profile` 互斥。自定义 profile 可在不加载模型的情况下先校验：

```bash
uv run babeldoc \
  --magazine-profile configs/magazine_runtime_profile.v1.json \
  --validate-config
```

### 算法配置与提示模板

| 类别 | 代表文件 |
| --- | --- |
| 页面策略与特征 | `configs/page_types.json`、`page_features.json`、`page_types.pctl.json` |
| 文章与连续链 | `article_grouping.json`、`chain_detection.json`、`chain_translation.json`、`article_context.json` |
| 文本流与排版 | `article_flow.json`、`column_reflow.json`、`title_typeset.json`、`indent_policy.json` |
| 首字装置 | `drop_cap.json`、`drop_cap_render.json`、`initial_adjacent.json` |
| 检测与修复 | `detectors.json`、`repair_actions.json`、`repair_acceptance.json`、`decision_rounds.json` |
| 最终 PDF | `final_pdf_compliance.json`、`render_diff.json`、`metrics.json` |
| 人工复核 | `hitl.json`、`reviews/` |
| 提示模板 | `prompts/*.md` |

源码树直接读取根目录资源，wheel 读取 `babeldoc/_resources/`内的同内容副本。运行报告始终使用 `configs/<name>` 或 `prompts/<name>` 逻辑路径和 SHA-256，不写入安装机器的绝对路径。

阈值、枚举和提示文本应继续保存在这些外部文件中。不要在代码中加入刊物名、页码、样本标识或针对单一版面的条件分支。

## 人工复核文件

HITL 是两次明确运行，两次必须使用同一 `--magazine-reviews-dir`。第一次导出复核草稿：

```bash
export OPENAI_API_KEY="your-api-key"

uv run babeldoc \
  --files /absolute/path/to/input.pdf \
  --openai \
  --magazine-mode hitl-export \
  --magazine-reviews-dir runs/reviews \
  --working-dir runs/export-work \
  --output runs/export-output
```

人工核对 `<stem>.review.json` 或 HTML，然后手工维护 `runs/reviews/<stem>.decisions.json`。第二次应用决定：

```bash
uv run babeldoc \
  --files /absolute/path/to/input.pdf \
  --openai \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir runs/reviews \
  --working-dir runs/apply-work \
  --output runs/apply-output
```

`hitl-apply` 会在创建 IL 之前检查 `<stem>.decisions.json` 是否存在。相关文件如下：

| 文件 | 写入者 | 用途 |
| --- | --- | --- |
| `reviews/<stem>.review.json` | 程序 | 机器默认判断和可编辑字段的结构化草稿 |
| `reviews/<stem>.review.html` | 程序 | 便于阅读的本地审阅页面 |
| `reviews/<stem>.decisions.json` | 人工 | 术语、页面类型和首字决定 |
| `<working-dir>/<stem>/hitl_apply.report.json` | 程序 | 实际应用结果与未命中警告 |

程序不会生成带有效决定的 `decisions.json`。决定文件采用整文件校验；任一非法条目会阻止整份文件应用。`BABELDOC_REVIEWS_DIR` 仅作为兼容回退，优先级低于 CLI/TOML 的显式目录。

## 运行产物与审计

启用相应功能后，工作目录会出现以下核心文件：

| 文件 | 内容 |
| --- | --- |
| `magazine_run_manifest.json` | 代码提交、输入摘要、用户选择的 mode、profile 名称/版本/SHA-256/逻辑源路径、有效开关和依赖校验 |
| `magazine_config_manifest.json` | 本次读取的算法配置及摘要 |
| `prompts.manifest.json` | 本次读取的提示模板及摘要 |
| `article_ir.json` | 规范文章、区域槽位、源元素和跨页索引 |
| `chain_report.json` | 连续链成员、证据和判定 |
| `chain_translation.report.json` | 联合请求、译文和失败状态 |
| `article_flow.report.json` | 跨栏、跨页放置及事务结果 |
| `fixed_asset_inventory.report.json` | 固定资产类型、几何和摘要 |
| `run_trace.report.json` | 源、请求、片段、代次和最终几何对应 |
| `issues.json` | 确定性检测结果 |
| `drop_cap_intent.report.json` | 首字意图、语言策略和源颜色 |
| `drop_cap_render.report.json` | 首字几何、检测和回滚结果 |
| `final_pdf_compliance.json` | 最终 PDF 的 `pass`、`degraded` 或 `fail` 状态及证据 |
| `checkpoint.*.zip` | 开启检查点后保存的阶段性机器状态 |

调试 JSON 用于检查，XML 检查点是机器恢复与重放依据。运行产物可能包含文档内容或摘要，应按输入文档的保密等级保存和清理。

## 开发与短测试

安装开发依赖：

```bash
uv sync --group dev
```

推荐的短检查：

```bash
uv run python -m compileall -q babeldoc tools spec_checks
uv run ruff check .
SPEC_NO_NESTED=1 uv run python spec_checks/spec_check_gate_registration.py
SPEC_NO_NESTED=1 uv run python spec_checks/spec_check_drop_cap_intent.py
SPEC_NO_NESTED=1 uv run python spec_checks/spec_check_pdf_compliance.py
SPEC_NO_NESTED=1 uv run python spec_checks/spec_check_startup_modes.py
SPEC_NO_NESTED=1 uv run python spec_checks/spec_check_cli_credentials.py
SPEC_NO_NESTED=1 uv run python spec_checks/spec_check_startup_distribution.py
```

C01-C16 的已注册 fast 规格可通过一条命令运行：

```bash
uv run python spec_checks/run_all.py --set fast
```

`spec_checks/run_all.py` 同时包含历史 sweep 门禁。sweep 会重建语料输出，耗时可能达到数小时；短周期开发和 CI 只使用 `--set fast`，不启动 sweep。

每项功能使用独立提交。代码注释保持英文、数量最少，只解释必要约束。实现继续遵守 `CLAUDE.md` 中的唯一翻译路径、外部配置、固定资产、检查点和通用化规则。

## 2026-08-26 C16 短验证状态

C16 收口已完成以下本地短检查：

| 检查 | 结果 |
| --- | --- |
| `python -m compileall -q babeldoc tools spec_checks` | 通过 |
| `ruff check .` | 通过 |
| C01-C16 fast 注册与 C01-C15 交付提交证据 | 通过 |
| 首字当前意图、最终 PDF 合规 | 通过 |
| mode 启动、凭据脱敏与无网络路径 | 通过 |
| 源码入口与仓库外 wheel 入口 | 通过 |
| `examples/ci/test.pdf` 无服务/无 key 真实解析 | 通过，翻译 token 为 0 |
| 完整语料 sweep 与长视觉回归 | 未运行，符合 C16 测试预算 |

剩余边界与验证缺口：

1. 本项目仍是研究原型；正式出版需要人工语言校对与版面复核。
2. 同页多文章身份隔离没有实现，这类页面不应被视为已完整支持。
3. 扫描件与 OCR 版面恢复不属于杂志扩展的主研究范围。
4. C16 没有运行完整语料 sweep、长视觉回归或真实翻译 API 端到端；`automatic` 全自动开关组合不等于生产可用性承诺。
5. CI 已配置 Linux 上的源码、wheel、fast 规格和无 key 解析烟雾；本地交付不会 push，因此需在后续远程 CI 中观察该工作流。

## 上游与许可证

本项目建立在 [funstory-ai/BabelDOC](https://github.com/funstory-ai/BabelDOC) 上。上游差异和历史批次记录见 `UPSTREAM_DIFF.md`、`WAIVERS.md` 与 `plans/`。

代码按 [GNU Affero General Public License v3.0](LICENSE) 发布。使用、修改和部署前请确认符合许可证要求及输入文档的版权与保密要求。
