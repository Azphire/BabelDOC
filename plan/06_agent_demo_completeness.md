# Agent 执行计划 06：双向内容完整性与最终 demo 门

目标分支：`migration/minimal-v0.6.4`

输入：Stage 00 expectations 和已通过功能验收的 Stage 01–05 代码

## 1. 任务

补一个样张无关的最终 verifier，重点发现：

- 大段源文从未进入翻译；
- chain 漏检、fallback、空 body fragment或重复普通翻译；
- TOC、标题、drop-cap 或多栏布局退化；
- 翻译方向错误导致长源脚本残留。

本阶段只做 demo 证据，不建设完整 request lineage、审计平台或发布级 validator。

## 2. 修改前必须阅读

- `tools/verify_minimal_pdf.py`
- `tools/verify_magazine_demo.py`
- `babeldoc/magazine/minimal_pipeline.py`
- ordinary translation tracking
- `chain_translation.report.json`
- `line_split.report.json`
- `layout_report.json`
- `title_typeset.report.json`
- `drop_cap_render.report.json`
- `issues.before.json`、`issues.after.json`

## 3. 允许改动

- `tools/verify_magazine_demo.py`
- `tools/verify_minimal_pdf.py`
- `babeldoc/magazine/minimal_pipeline.py`
- 必要时新增 `babeldoc/magazine/demo_coverage.py`
- ordinary translation producer 中仅增加 source ref → target outcome 的简单记录
- 新增 `tests/minimal/test_demo_completeness.py`

禁止修改功能算法来迎合 verifier，禁止增加 request lifecycle、transport event、article-context 审计、append-only ledger、旧结果兼容、自动修复、部署或跨平台框架。

## 4. 最小 coverage report

在 line split 和 ArticleBuilder 完成后、drop-cap 改写 source 前，冻结本次页面的 source paragraph 清单：

```text
source_ref / physical_page / role
source_text_sha256 / source_box
translation_owner: joint|ordinary|preserve|none
target_text_sha256 / final_status
```

要求：

- chain member 从 `chain_translation.report.json` 取得 joint outcome；
- 普通 paragraph 从现有 translation tracking 取得 target outcome；
- expectations 明确允许的 folio/credit/brand 可 preserve；
- 其他正文不得 `none` 或空 target；
- body chain 的每个 member 必须是 joint owner，不能 ordinary/fallback；
- 产品代码不读取 expectations；豁免只由 verifier 解释。

不记录 transport retry、request started/completed event、article brief、render owner lifecycle 或多阶段 seal。

## 5. 独立大段漏译检查

verifier 用 PyMuPDF 从 source PDF 提取较长文本块，并按方向检查：

- source 为英文时，长 Latin block 必须能映射到 coverage item或人工 exemption；
- source 为中文时，长 Han block 必须能映射到 coverage item或人工 exemption；
- 输出对应页面不得保留超过 expectations 阈值的长源脚本块。

该检查只用于发现整段漏采，不追求正式 OCR 对齐或 benchmark 精度。

## 6. 通用 verifier

固定命令：

```text
uv run --no-sync python tools/verify_magazine_demo.py \
  --check <chain|toc|layout|title|dropcap|full> \
  --expectations <json> \
  --source <source.pdf> --output <translated.pdf> \
  --run-dir <exact-run-dir> --pages <physical-pages> \
  --target-lang <zh|en>
```

要求：

- 只读取命令给出的 source/output/run-dir，不递归猜文件。
- 样张页码、box、文本和数量全部来自 expectations。
- `chain` 检查 truth、negative、joint count、fragments、fallback和source boxes。
- `toc` 检查 single/block/prose结构和最终容器。
- `layout` 检查 source/final box、多栏和 fixed assets。
- `title` 检查双向标题政策和字符守恒。
- `dropcap` 检查 keep candidate、目标首字和字符守恒。
- `full` 再加 coverage、长块漏译、页数/page size和长源脚本残留。
- 失败时输出简短 JSON 结果和具体 element/page，便于修复。

不做旧 schema 兼容、legacy paid 包回放、自动 migration 或 verifier 内自动修 PDF。

## 7. 聚焦测试

新增 `tests/minimal/test_demo_completeness.py`，覆盖两套不同命名、不同页码的 en→zh/zh→en fixture：

- 合格 fixture 通过 full；
- 整段 source block 未进入 coverage 时失败；
- ordinary paragraph 无 target时失败；
- chain 漏检、fallback、空 body fragment或普通重复 ownership 时失败；
- TOC/layout/title/drop-cap 任一核心断言失败时 full 失败；
- target-lang 与配置方向不一致时失败；
- verifier 不包含 Courier 名称、固定页码、坐标、文本或候选数量。

运行：

```text
uv run --no-sync pytest -q tests/minimal/test_demo_completeness.py
```

## 8. 主控最终 paid 验收

使用 fresh run 完整运行：

- Courier en→zh 整本；
- 非 Courier en→zh 整本；
- 中文源 zh→en 整本；
- 两个方向各自未参与修改的 holdout chain/feature 页窗。

每份输出必须：

- PDF 可打开，页数和页面尺寸不变；
- 所有 truth chain joint once、无 fallback、body fragments非空；
- TOC 单行/块状/prose正确；
- 多栏和固定资产无重大漂移；
- 双向标题与首字通过；
- 所有 required source paragraph 有目标输出；
- 没有未解释的长源脚本残留、大段漏译、明显裁切或跨栏。

主控渲染全页缩略图，并对 expectations 中的 chain、TOC、layout、title、drop-cap和高风险长段做原分辨率对照。

## 9. 返回主控

返回 verifier 改动、coverage 字段、聚焦测试结果、三份整本和双向 holdout 结果、失败页面与最终可展示范围。无需提供发布稳定性、跨平台或正式 benchmark 结论。
