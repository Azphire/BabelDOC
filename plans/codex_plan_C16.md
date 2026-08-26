# Codex Plan C16：统一启动、运行资源打包与短门禁收口

- 状态：可直接执行
- 仓库：https://github.com/Azphire/BabelDOC
- 参考基线：`cda5ccc3159ee271af8ba1f978b13ec275b47b3b`
- 开发方式：短周期、原子提交、无真实翻译请求
- 建议主模型：GPT-5.6 Sol
- 建议推理强度：xhigh
- 建议服务层：priority
- 备选模型：GPT-5.5，推理强度 xhigh

## 一、交给 Codex 的执行 prompt

```text
完整读取 plans/codex_plan_C16.md、仓库根目录 CLAUDE.md 和本计划列出的必读文件，然后按计划直接实施。

先确认工作树、分支和 origin/main，不覆盖任何已有改动。参考基线仅用于定位审计结果；如果 origin/main 已前进，先阅读新增提交并重新确认计划中的事实，再继续实施。

严格遵守以下要求：
1. 每个独立 feature 或修复使用单独 commit，使用计划指定的提交顺序与提交主题。
2. 不运行语料 sweep、真实模型翻译、长时间视觉回归或任何预计超过 60 秒的本地命令。
3. 每个提交只运行与本提交直接相关的短测试；所有测试必须有 60 秒超时。
4. 注释使用英文，只保留解释必要约束的最少注释；不要写修改说明、批次说明或 changelog 式注释。
5. 不增加刊物名、页码、样本 ID、debug_id 或单一样本特判；阈值、枚举、profile 和提示文本继续外置。
6. 保持 il_translator_llm_only.py 为 LLM 主翻译路径，不把新行为接回旧 il_translator.py。
7. 不修改 Document IL schema；运行追踪和新增状态继续使用 sidecar 或运行时对象。
8. 不降低固定资产守卫、决定指纹校验、守恒检查、原子回滚或最终 PDF 合规标准来换取测试通过。
9. 不把 API key 写进文件、日志、manifest、测试快照或命令输出。
10. 不推送远端。完成后给出提交列表、短测试结果、未运行项目和剩余风险。

遇到规格与实现冲突时，先根据生产流水线的真实数据合同判断。只有在证据表明测试 fixture 已过期时才更新 fixture；生产路径也违反合同时修复生产代码。
```

## 二、任务背景

仓库已经完成 C01-C15 的文章状态、连续链联合翻译、跨栏与跨页文本流、运行追踪、固定资产守卫、首字装置和最终 PDF 合规开发。2026-08-26 的短审计发现：

1. 主 CLI 已支持 `--magazine-profile`，随仓库提供的 profile 关闭 9 个关键开关，完整功能组合没有一键入口。
2. `spec_check_drop_cap_intent.py` 在中文渲染用例中失败。C14 引入“当前决定”指纹守卫后，C11 fixture 生成的意图被记录为 `invalid_intent`。
3. C01-C15 的 15 个规格文件没有加入 `spec_checks/run_all.py`，也没有声明 `GATE_SET`。
4. 部分规格依赖不存在的 `batch-C*` tag；在干净 HEAD 上回退到 `git diff HEAD` 会得到空集合。
5. `ruff check .` 失败，共 78 项；现有 GitHub Checks 工作流会因此失败。
6. wheel 可以构建，但不包含根目录的 `configs/` 和 `prompts/`。杂志模块从源码树根目录取资源，安装后的扩展无法完整启动。
7. CLI 不会自动读取 `OPENAI_API_KEY`。解析专用模式仍要求 `--openai` 和 API key。
8. `uv.lock` 被忽略且未提交；`regex` 被源码直接导入但未声明为直接依赖；项目 URL 仍指向上游仓库。
9. 当前短检查结果为：compileall 通过、wheel 构建通过、C01-C15 独立规格 14/15 通过、最终 PDF 合规规格 10/10 通过。完整语料 sweep 未运行。

## 三、最终目标

完成后，源码检出环境和安装 wheel 的环境都应提供同一组可验证命令：

```bash
babeldoc --magazine-mode conservative --validate-config
babeldoc --magazine-mode automatic --validate-config
babeldoc --magazine-mode hitl-export --validate-config
babeldoc --magazine-mode hitl-apply --magazine-reviews-dir /path/to/reviews --files input.pdf --validate-config
```

真实翻译的最短命令应支持：

```bash
export OPENAI_API_KEY="..."
babeldoc \
  --files input.pdf \
  --openai \
  --magazine-mode automatic \
  --lang-in en \
  --lang-out zh
```

解析烟雾测试应支持：

```bash
babeldoc \
  --files examples/ci/test.pdf \
  --only-parse-generate-pdf \
  --skip-scanned-detection
```

以上解析命令不得要求翻译服务或 API key，也不得创建网络翻译请求。

## 四、范围

### 必须完成

- 修复 C11/C14 首字意图规格回归，保留“当前决定”守卫。
- 把 C01-C15 新规格纳入统一 fast 门禁。
- 移除规格对缺失 batch tag 的空范围回退。
- 恢复仓库级 Ruff 门禁。
- 把杂志配置和提示模板作为 wheel 运行资源交付。
- 增加统一 `--magazine-mode`，保留 `--magazine-profile` 自定义入口。
- 增加 `OPENAI_API_KEY` 环境变量回退，定义并测试优先级。
- 让解析专用路径在没有翻译器凭据时运行。
- 增加只校验配置和打印脱敏有效配置的命令。
- 增加显式人工复核目录参数。
- 修正项目 URL、直接依赖和仓库级依赖锁。
- 更新 README 命令、配置表、已知问题和验证状态。
- 增加源码环境与 wheel 环境的短启动烟雾测试。

### 不在本批次

- 同页多文章身份隔离。
- 新的文章识别、跨栏、跨页或首字算法。
- Document IL schema 变更。
- 新翻译服务实现。
- 扫描件 OCR 版面恢复。
- 全语料 sweep、真实 API 翻译、人工视觉评分。
- 更改 C01-C15 已冻结的通用版面约束。
- 发布 PyPI、创建 GitHub Release、推送分支或 tag。

## 五、不可破坏的合同

1. `--magazine-profile PATH` 继续可用，旧命令含义不变。
2. `--magazine-mode` 与 `--magazine-profile` 互斥；同时提供时由 argparse 以退出码 2 拒绝。
3. 未提供 mode 或 profile 时维持当前上游兼容行为。
4. 所有内置 profile 都完整声明 22 个布尔开关，并通过现有严格解析器。
5. profile 依赖在创建 IL、加载模型和发出请求前验证。
6. CLI 参数或 TOML 中显式提供的 key 优先于环境变量；环境变量只在显式值为空时使用。
7. 所有有效配置输出必须把 key 显示为 `<redacted>`，不能输出可逆摘要。
8. `--validate-config` 不加载布局模型、不下载资源、不打开翻译连接、不创建输出 PDF。
9. 解析专用路径使用明确的无网络翻译器对象，不能伪造真实凭据。
10. HITL 决定文件仍由人工维护；程序不能写入有效决定。
11. `hitl-apply` 在缺少对应 `<stem>.decisions.json` 时必须在 IL 创建前给出明确错误。
12. 固定资产、事务回滚、运行追踪和最终 PDF 合规语义保持不变。
13. 源码树和 wheel 必须读取相同内容的配置与提示模板，并保留 SHA-256 manifest。
14. 所有新增 JSON、报告和有效配置输出使用稳定排序及 UTF-8。

## 六、内置运行模式

新增 `--magazine-mode`，允许值如下：

| mode | 用途 | 开关规则 |
| --- | --- | --- |
| `conservative` | 当前可用的保守流水线 | 精确复用 `configs/magazine_runtime_profile.v1.json` |
| `automatic` | 无人工决定的完整自动功能链 | 除 `magazine_hitl_export`、`magazine_hitl_apply` 外，其余 20 个开关全部开启 |
| `hitl-export` | 生成机器草稿供人工复核 | `automatic` 全部开关，加开 `magazine_hitl_export` |
| `hitl-apply` | 重新生成草稿并应用人工决定 | 22 个开关全部开启 |

新增并版本化：

- `configs/magazine_runtime_profile.automatic.v1.json`
- `configs/magazine_runtime_profile.hitl_export.v1.json`
- `configs/magazine_runtime_profile.hitl_apply.v1.json`

`conservative` 直接指向现有 `configs/magazine_runtime_profile.v1.json`，避免复制同一事实。mode 到资源名的映射放在一个封闭常量中。

不提供 mode 或 profile 时继续使用当前默认行为；该状态不作为新的 mode 暴露。

## 七、必读文件

开始编辑前完整阅读：

- `CLAUDE.md`
- `README.md`
- `pyproject.toml`
- `.gitignore`
- `.github/workflows/checks.yml`
- `.github/workflows/lint.yml`
- `babeldoc/main.py`
- `babeldoc/const.py`
- `babeldoc/format/pdf/translation_config.py`
- `babeldoc/format/pdf/high_level.py`
- `babeldoc/translator/translator.py`
- `babeldoc/magazine/runtime_profile.py`
- `babeldoc/magazine/prompt_loader.py`
- `babeldoc/magazine/taxonomy.py`
- `babeldoc/magazine/hitl.py`
- `babeldoc/magazine/drop_cap.py`
- `babeldoc/magazine/drop_cap_intent.py`
- `babeldoc/magazine/drop_cap_render.py`
- `spec_checks/run_all.py`
- C01-C15 的 15 个 `spec_check_*.py`

先用 `rg` 枚举所有 `Path(__file__).resolve().parents[2]`、`ROOT / "configs"`、`ROOT / "prompts"` 和直接读取 `reviews/` 的位置。资源修复必须覆盖实际调用点。

## 八、提交与实施顺序

### Commit 1：修复首字意图回归

提交主题：

```text
fix(drop-cap): preserve current intent through render guards
```

步骤：

1. 单独运行 `spec_checks/spec_check_drop_cap_intent.py` 并保留失败报告。
2. 对比生产路径 `drop_cap.mark -> hitl/drop_cap.apply -> drop_cap_intent -> drop_cap_render` 与规格中的 `source_intent()` fixture。
3. 确认 `decision_version`、候选摘要、源样式摘要、配置摘要和当前决定指纹在哪一步生成。
4. 如果生产路径生成当前指纹且 fixture 绕过该步骤，改为通过公开生产 helper 构建 fixture。
5. 如果生产路径也会留下过期指纹，修复生产状态传播，并为该路径增加断言。
6. 禁止删除、跳过或放宽 C14 的 `decision_current` 校验。
7. 验证英文只放大首字母、中文两行首字、双向源颜色继承和过期决定回滚。

短测试：

```bash
timeout 60s uv run python spec_checks/spec_check_drop_cap_intent.py
timeout 60s uv run python spec_checks/spec_check_drop_cap_english.py
timeout 60s uv run python spec_checks/spec_check_drop_cap_chinese.py
timeout 60s uv run python spec_checks/spec_check_drop_cap_repair_guard.py
```

### Commit 2：注册 C01-C15 短门禁

提交主题：

```text
test(gates): register C01-C15 fast specifications
```

步骤：

1. 给以下 15 个规格文件声明 `GATE_SET = "fast"`：
   - `spec_check_magazine_runtime_profile.py`
   - `spec_check_article_flow_ir.py`
   - `spec_check_run_trace.py`
   - `spec_check_fixed_asset_guard.py`
   - `spec_check_chain_single_request.py`
   - `spec_check_chain_slot_backfill.py`
   - `spec_check_article_cross_column.py`
   - `spec_check_article_cross_page.py`
   - `spec_check_repair_transaction.py`
   - `spec_check_reflow_compliance.py`
   - `spec_check_drop_cap_intent.py`
   - `spec_check_drop_cap_english.py`
   - `spec_check_drop_cap_chinese.py`
   - `spec_check_drop_cap_repair_guard.py`
   - `spec_check_pdf_compliance.py`
2. 按 C01-C15 的交付顺序追加到 `spec_checks/run_all.py::GATES`。
3. 新增 `spec_checks/delivery_commits.py`，以只读常量记录 C01-C15 的交付 SHA。
4. 把 C02、C06、C07、C08 等 tag/fallback 范围逻辑改为读取对应交付 SHA，并用 `git diff-tree` 检查该提交的真实文件集合。
5. 交付 SHA 不存在时明确失败；禁止回退为空的 `git diff HEAD`。
6. 增加一个纯 Python 元检查，确认新增规格均在 `GATES` 中、均声明合法集合、交付 SHA 可解析。

交付 SHA：

| 批次 | SHA |
| --- | --- |
| C01 | `39e7c68` |
| C02 | `9aa7a53` |
| C03 | `05ef7ca` |
| C04 | `5c6fff5` |
| C05 | `b08a948` |
| C06 | `51d30bc` |
| C07 | `4130f98` |
| C08 | `9884e26` |
| C09 | `c32161b` |
| C10 | `7d04a09` |
| C11 | `a63e8f1` |
| C12 | `4923446` |
| C13 | `5e75fa8` |
| C14 | `a318011` |
| C15 | `cda5ccc` |

短测试：

```bash
timeout 60s uv run python spec_checks/spec_check_gate_registration.py
timeout 60s uv run python spec_checks/spec_check_magazine_runtime_profile.py
timeout 60s uv run python spec_checks/spec_check_drop_cap_intent.py
timeout 60s uv run python spec_checks/spec_check_pdf_compliance.py
```

### Commit 3：恢复静态门禁

提交主题：

```text
fix(lint): restore repository static gate
```

步骤：

1. 运行 `ruff check . --statistics`，以当前 78 项为起点。
2. 先使用 `ruff check . --fix` 处理可证明等价的机械问题。
3. 手工处理剩余未使用参数、lambda 赋值、异常类命名和 subprocess 告警。
4. `lxml` 告警只能在输入确实来自内部生成的 checkpoint XML 时增加带简短英文理由的局部 `noqa`；外部输入需要安全解析配置。
5. 固定 argv 的 git 子进程允许局部 `noqa`，理由保持一行英文。
6. 不使用全局 ignore 隐藏本批次新增问题。
7. 检查自动修复没有改变导入副作用或规格注入顺序。

短测试：

```bash
timeout 60s uv run ruff check .
timeout 60s uv run python -m compileall -q babeldoc tools spec_checks
```

### Commit 4：打包运行资源与锁定直接依赖

提交主题：

```text
build(resources): package magazine runtime data
```

步骤：

1. 新增一个小型资源路径模块，例如 `babeldoc/magazine/resource_paths.py`。
2. 源码检出环境优先读取仓库根目录的 `configs/` 和 `prompts/`。
3. wheel 环境读取 `babeldoc/_resources/configs/` 与 `babeldoc/_resources/prompts/`。
4. 在 Hatch wheel 配置中使用 `force-include`，把根目录资源映射到上述包内目录；不要维护两份手工复制文件。
5. 将杂志模块的默认配置和提示路径统一改用资源路径 helper。显式调用方传入的路径继续优先。
6. manifest 中的逻辑资源名保持 `configs/<name>` 或 `prompts/<name>`，避免因安装位置不同改变审计记录。
7. 把 `regex` 加入直接依赖。
8. 将 `Homepage` 和 `Issues` 更新到 `Azphire/BabelDOC`。
9. 从 `.gitignore` 移除 `uv.lock`，运行 `uv lock --python 3.12` 并提交锁文件。
10. 构建 wheel，确认 wheel 列表含全部 JSON 与 Markdown 运行资源。

短测试：

```bash
timeout 60s uv run python spec_checks/spec_check_magazine_runtime_profile.py
timeout 60s uv build --wheel --out-dir .tmp/c16-wheel
timeout 60s uv run python -c "from babeldoc.magazine.resource_paths import config_path, prompt_path; assert config_path('hitl.json').is_file(); assert prompt_path('article_brief.md').is_file()"
```

测试完成后删除 `.tmp/c16-wheel`，不要提交构建产物。

### Commit 5：增加统一运行模式和配置检查

提交主题：

```text
feat(cli): add validated magazine run modes
```

步骤：

1. 新增三份完整 profile：automatic、hitl_export、hitl_apply。
2. 在 `runtime_profile.py` 增加封闭 mode 注册表和 mode 解析函数。
3. 在 CLI 中增加互斥参数 `--magazine-mode` 与 `--magazine-profile`。
4. 增加 `--magazine-reviews-dir PATH`，传入 `TranslationConfig`，由 `hitl.py` 显式读取。
5. 保留 `BABELDOC_REVIEWS_DIR` 作为测试兼容回退，优先级为 CLI/TOML 路径、环境变量、源码环境默认目录。
6. 增加 `--validate-config`。该分支应在模型加载、文件解析和凭据强制校验前返回。
7. 增加 `--print-effective-config`，输出稳定 JSON，包含 mode/profile、22 个有效开关、输入摘要字段、复核目录、服务配置和资源可用性。
8. 所有 key 字段固定输出 `<redacted>` 或 `null`。
9. `hitl-apply` 在给定输入文件后检查对应 decisions 文件存在；缺失时明确失败。
10. 运行 manifest 增加用户选择的 mode，同时保留 profile 名称、版本和 SHA。

建议命令语义：

```bash
babeldoc --magazine-mode automatic --validate-config
babeldoc --magazine-profile custom.json --validate-config
babeldoc --magazine-mode automatic --magazine-profile custom.json
```

第三条必须退出 2。前两条必须在无 API key、无模型缓存环境下完成。

短测试：

```bash
timeout 60s uv run babeldoc --magazine-mode conservative --validate-config
timeout 60s uv run babeldoc --magazine-mode automatic --print-effective-config
timeout 60s uv run python spec_checks/spec_check_magazine_runtime_profile.py
timeout 60s uv run python spec_checks/spec_check_startup_modes.py
```

### Commit 6：环境凭据与无 key 解析路径

提交主题：

```text
feat(cli): support environment credentials and parse-only runs
```

步骤：

1. 当 `--openai-api-key` 或 TOML 值为空时读取 `OPENAI_API_KEY`。
2. term extraction key 维持当前显式值优先，并回退到最终主 key。
3. 增加最小无网络翻译器，供 `--only-parse-generate-pdf` 与其他明确跳过翻译的路径使用。
4. 解析专用路径不实例化 `OpenAITranslator`，不要求 `--openai`，不读取 key。
5. 普通翻译继续要求显式选择服务；缺失最终 key 时在加载模型前失败。
6. 错误消息不能包含 key、base URL 查询参数或配置文件原文。
7. 增加测试覆盖 CLI/TOML 值高于环境变量、环境变量回退、缺失 key、脱敏输出和解析路径零网络调用。

短测试：

```bash
timeout 60s uv run python spec_checks/spec_check_cli_credentials.py
timeout 60s uv run babeldoc --files examples/ci/test.pdf --only-parse-generate-pdf --skip-scanned-detection
```

如果第二条首次运行需要下载布局资源，使用已 warmup 的本地缓存；没有缓存时只运行 mock smoke，并在交付报告中标明未运行真实 PDF。

### Commit 7：增加 wheel 与 CI 短启动烟雾测试

提交主题：

```text
test(startup): verify source and wheel entry points
```

步骤：

1. 新增 `spec_checks/spec_check_startup_distribution.py`，标记为 fast。
2. 在临时目录构建 wheel、创建隔离 venv、安装 wheel，并从仓库外工作目录运行：
   - `babeldoc --help`
   - `babeldoc --magazine-mode conservative --validate-config`
   - `babeldoc --magazine-mode automatic --print-effective-config`
3. 断言包内配置和提示模板可读取，输出 manifest 使用稳定逻辑路径。
4. 断言输出不包含测试 key。
5. 更新 `.github/workflows/checks.yml`：
   - 保留 compileall、Ruff、wheel 构建。
   - 增加配置验证和 wheel 外部目录 smoke。
   - 将解析 smoke 改为无 dummy key 命令。
   - 增加 C01-C16 fast 规格入口，禁止触发 sweep。
6. 所有临时 venv、wheel 和输出写入系统临时目录或 `.tmp/`，测试结束清理。

短测试：

```bash
timeout 60s uv run python spec_checks/spec_check_startup_distribution.py
timeout 60s uv run ruff check .
timeout 60s uv run python -m compileall -q babeldoc tools spec_checks
```

### Commit 8：同步中文 README

提交主题：

```text
docs(readme): document unified magazine startup
```

步骤：

1. 把快速启动主命令改为 `--magazine-mode conservative` 和 `--magazine-mode automatic`。
2. 增加 HITL export/apply 两次运行示例及 `--magazine-reviews-dir`。
3. 把仅解析示例改为无服务、无 key 命令。
4. 增加 `OPENAI_API_KEY` 自动回退和优先级说明。
5. 将安装说明扩展为源码与 wheel 两种经过验证的路径。
6. 更新 profile 表、运行清单、测试入口和已知问题。
7. 移除已经解决的 C11、门禁注册、wheel 资源和 Ruff 失败条目。
8. 保留研究原型定位、同页多文章限制和未运行全语料 sweep 的声明。
9. 逐条复制 README 命令到 shell 执行 `--help` 或 `--validate-config` 级验证。

短测试：

```bash
timeout 60s uv run python -m compileall -q babeldoc tools spec_checks
timeout 60s uv run ruff check .
timeout 60s uv run babeldoc --magazine-mode automatic --validate-config
git diff --check HEAD^
```

## 九、测试预算

每条命令使用 `timeout 60s`。本批次允许：

- compileall。
- Ruff。
- 纯 Python 规格。
- stub/mock 翻译器规格。
- 配置加载与 profile 依赖校验。
- wheel 构建、隔离安装和 CLI help/validate smoke。
- 已 warmup 环境中的一页解析 smoke。

本批次禁止：

- `spec_checks/run_all.py --set sweep`。
- 无 `--fast` 的全门禁。
- 任何真实 OpenAI 兼容接口请求。
- 下载大型模型作为验收步骤。
- 全杂志、多页真实翻译。
- 长时间视觉渲染比较。

如果某项短测试超过 60 秒，立即终止并记录为未运行。不得提高超时来等待完成。

## 十、验收矩阵

| ID | 验收项 | 通过条件 |
| --- | --- | --- |
| A1 | C11/C14 回归 | 四个首字规格全部通过，当前决定守卫仍能拒绝过期状态 |
| A2 | 门禁发现性 | C01-C15 全部出现在 `GATES`，均声明 `fast` |
| A3 | 范围证据 | C02/C06/C07/C08 使用真实交付提交，缺失证据时失败 |
| A4 | 静态质量 | `ruff check .` 退出 0 |
| A5 | 编译 | compileall 退出 0 |
| A6 | profile 完整性 | 4 个内置 mode 均解析为完整 22 开关 |
| A7 | 自动模式 | automatic 只关闭两个 HITL 开关 |
| A8 | HITL 模式 | export/apply 开关组合符合模式表 |
| A9 | 参数冲突 | mode 与自定义 profile 同时出现时退出 2 |
| A10 | 配置验证 | 无模型、无 key 情况下 validate 退出 0 |
| A11 | 密钥回退 | CLI/TOML 高于环境变量，环境变量可作为缺省值 |
| A12 | 密钥安全 | help、validate、effective config、错误输出和 manifest 均不泄露 key |
| A13 | 仅解析 | 无 `--openai`、无 key 可执行解析专用路径 |
| A14 | 源码资源 | 从仓库根目录读取全部配置和提示模板 |
| A15 | wheel 资源 | 从仓库外目录安装 wheel 后读取相同资源 |
| A16 | 资源一致性 | 源码与 wheel 资源内容 SHA-256 一致 |
| A17 | HITL 目录 | 显式目录优先，apply 缺决定文件时前置失败 |
| A18 | 构建元数据 | 项目 URL 指向 fork，`regex` 是直接依赖，`uv.lock` 已提交 |
| A19 | CI | Checks 使用无 key 解析 smoke 和短规格，不触发 sweep |
| A20 | 文档 | README 中所有 validate/help 示例可复制执行 |

## 十一、完成前检查

每个提交后执行：

```bash
git status --short
git show --stat --oneline HEAD
git diff --check HEAD^
```

最终执行以下短汇总，单项仍需 60 秒超时：

```bash
timeout 60s uv run ruff check .
timeout 60s uv run python -m compileall -q babeldoc tools spec_checks
timeout 60s uv run python spec_checks/spec_check_gate_registration.py
timeout 60s uv run python spec_checks/spec_check_drop_cap_intent.py
timeout 60s uv run python spec_checks/spec_check_pdf_compliance.py
timeout 60s uv run python spec_checks/spec_check_startup_modes.py
timeout 60s uv run python spec_checks/spec_check_cli_credentials.py
timeout 60s uv run python spec_checks/spec_check_startup_distribution.py
```

检查工作树只包含预期提交，不包含：

- API key 或本地凭据文件。
- wheel、venv、缓存、PDF 输出或临时 review 文件。
- 语料生成物。
- 自动格式化造成的无关大范围改动。
- 针对特定刊物、页面或样本的条件分支。

## 十二、交付报告格式

Codex 最终回复必须包含：

1. 基线与最终 HEAD。
2. 按顺序列出 8 个提交 SHA 和主题。
3. 列出实际修改的用户入口。
4. 给出源码模式、wheel 模式、automatic、HITL export/apply、仅解析的最终命令。
5. 给出每项短测试的通过、失败或未运行状态及耗时。
6. 明确声明没有运行 sweep、真实 API 翻译和长时间视觉回归。
7. 列出任何剩余风险，禁止用“全部完成”概括未验证的真实样本质量。
8. 如果某个提交未完成，保留工作树、说明阻塞点和最小下一步，不用占位实现掩盖失败。
