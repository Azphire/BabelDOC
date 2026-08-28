# 主控执行计划：双向多样张 demo 最小修补

计划版本：2026-08-28 demo-minimal-v2

目标分支：`migration/minimal-v0.6.4`

执行方式：一个主控、一个持续复用的执行 agent、一个 branch、一个 worktree，阶段串行。

## 1. 目标与边界

本轮只支撑 report 展示。实现必须能在多份样张和两个翻译方向上工作，但不开发发布级兼容、稳定、部署或恢复能力。

必须完成：

- 同一段落被分栏或分页切断时，准确识别全部成员，合并后联合翻译一次，再按顺序回填到各自源框。
- body chain 每个成员都有非空译文；任何 fallback、漏检、错序或普通翻译重复接管都不能通过验收。
- 单行 TOC 按源视觉行分别翻译和排版；块状 TOC 按块翻译；同页长正文不拆行。
- 关闭普通文章跨容器重排，保留多栏、通栏导语、图片和页脚的源布局。
- 英译中的中文标题尽量在源标题区单行排版；中译英标题完整留在源标题区。
- 首字下沉/放大使用真实单字度量并进入最终 PDF。
- 检查所有应译长段都有目标语输出，避免大段漏译。

Courier 只用于定位已知问题。产品代码中禁止出现刊物名、固定页码、固定坐标、固定文本或 source hash 特例。

## 2. 明确删除的工程内容

以下内容与 demo 功能无关，本轮全部取消：

- `tree-state-v1`、`tree-content-v1` 及其 helper；
- symlink、文件 mode、特殊文件名、NUL-safe、设备文件等文件系统测试；
- Windows Developer Mode、`Create symbolic links` 权限或跨平台兼容测试；
- append-only ledger、hash chain、`fsync`、atomic replace、high-water、崩溃恢复；
- paid 子进程状态恢复、PID/session 跟踪、重复计费防护框架；
- secret launcher、全盘 secret 扫描和 `/proc` 隔离测试；
- legacy paid 包兼容、旧 schema 回放和迁移层；
- schema vector、坐标量化一致性、fuzz、全测试套件和发布级回归；
- 新 CLI 开关、feature flag、配置兼容层、打包、部署和性能测试。

API key 由主控在 paid 命令运行时临时提供，不写入仓库文件或日志即可，不为此开发新框架。

## 3. 已确认的代码问题

- 失败 chain 在 claim 后没有释放，导致 12 个成员被普通翻译跳过。
- chain preflight 依赖 ArticleIR 整栏 slot，导致多数连续链失败。
- `line_split.py` 与 `title_typeset.py` 已有实现，但没有进入固定流水线。
- `article_flow` 把通栏导语和窄栏正文合成宽槽，Courier p5 三栏变成单栏。
- drop-cap 使用全字体 bbox 代替单字度量，真实首字全部回滚。
- 当前完整性检查偏向英译中，无法可靠发现中译英漏译。

## 4. 角色

主控负责：

1. 按顺序下发一份 agent 计划。
2. 检查改动范围和聚焦测试结果。
3. 提交当前阶段代码。
4. 用冻结样张运行 paid、机器检查和 PDF 目检。
5. 失败时把具体日志、sidecar 和页面截图交回同一 agent 修复。

执行 agent 负责：

- 实际阅读计划列出的代码；
- 只做该阶段的最小实现；
- 运行计划指定的聚焦测试；
- 返回改动文件、测试结果和剩余问题；
- 不运行 paid，不接触 API key，不自行进入下一阶段。

## 5. 样张与轮换

Stage 00 冻结至少五份不同 PDF：

- Courier en→zh diagnosis；
- 非 Courier en→zh transfer；
- 另一份非 Courier en→zh holdout；
- zh→en transfer；
- 另一份 zh→en holdout。

两个方向都必须包含至少一条正文跨栏 chain 和一条正文跨页 chain。每次功能修复后先运行另一刊物，再回归最初失败样张，最后运行未参与修改判断的 holdout。

当前仍缺两份非 Courier 英文 PDF；Stage 00 在获得真实文件和人工 chain 标注前停止，不能用 Courier 的裁剪页或重复运行替代。

## 6. 串行阶段

1. `00_agent_sample_matrix.md`：冻结样张、人工 expectations 和双向配置。
2. `01_agent_chain_coverage.md`：连续链检测、联合翻译一次、源框回填、失败 claim 释放。
3. `02_agent_toc_structure.md`：TOC 单行/块状结构和排版。
4. `03_agent_conservative_layout.md`：关闭普通重排并保护源容器；同时回归 chain 和 TOC 最终 PDF。
5. `04_agent_title_typeset.md`：接入双向标题排版。
6. `05_agent_dropcap_render.md`：修首字度量和渲染。
7. `06_agent_demo_completeness.md`：补双向内容完整性检查并运行最终整本 demo。

Stage 01/02 的 paid 结果只检查本阶段语义和 source unit；其最终几何在 Stage 03 关闭重排后统一验收。

## 7. 每阶段最小流程

1. 确认分支正确，工作树没有与本阶段冲突的用户改动。
2. 执行 agent 修改 allowlist 内文件并跑聚焦测试。
3. 主控检查 diff，测试通过后提交。
4. 运行冻结的 transfer 样张，再回归 diagnosis，最后运行 holdout。
5. 运行对应 verifier，并对涉及页面做原分辨率 source/output 对照。
6. 通过后进入下一阶段；失败则交回同一 agent。

不要求每阶段跑完整 `tests/minimal`、跨平台测试或 lint 全库。

## 8. paid 命令模板

使用现有 CLI，固定 fresh run：

```text
uv run --no-sync babeldoc \
  --config <minimal.en-zh.toml|minimal.zh-en.toml> \
  --files <source.pdf> \
  --pages <frozen-pages> \
  --working-dir <run>/work \
  --output <run>/output \
  --no-dual --no-auto-extract-glossary --skip-scanned-detection --ignore-cache
```

验收命令：

```text
uv run --no-sync python tools/verify_magazine_demo.py \
  --check <chain|toc|layout|title|dropcap|full> \
  --expectations <sample-expectations.json> \
  --source <source.pdf> --output <translated.pdf> \
  --run-dir <exact-run-dir> --pages <frozen-pages> \
  --target-lang <zh|en>
```

## 9. 阶段验收

| 阶段 | 必须看到的结果 |
| --- | --- |
| 01 chain | 双向跨栏/跨页 truth 全部准确成链；每链联合翻译一次；body fragments 全非空并回填源框；无 fallback |
| 02 TOC | 双向单行记录不合并，块状记录不拆散，prose 不碎；相关 chain 不退化 |
| 03 layout | 普通 flow 关闭；多栏和固定资产不漂移；chain 与 TOC 最终 PDF 仍在各自源框 |
| 04 title | 中文标题单行；英文标题完整留在源区；标题 chain 无重复或残留 |
| 05 drop-cap | 双向首字进入最终渲染，正文字符不丢失，相关 chain 不退化 |
| 06 full | 三份整本输出和双向 holdout 页窗通过；无大段漏译、错误方向残留或重大布局破坏 |

## 10. 最终交付

主控最终返回：代码 SHA、实际运行样张与方向、机器检查结果、关键页面截图、仍保留的 demo 降级。普通文章重排关闭、非正式 benchmark、非发布级稳定性必须如实写入报告。
