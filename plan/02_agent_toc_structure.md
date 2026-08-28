# Agent 执行计划 02：TOC 单行记录与块状记录

目标分支：`migration/minimal-v0.6.4`

输入：Stage 00 expectations 和已完成的 Stage 01 chain 功能

## 1. 任务

把已有 `line_split.py` 接入固定流水线，使双向 TOC 满足：

- 单行目录：一个源视觉行对应一个翻译 item，不能与下一行合并；
- 块状目录：同一紧密内容块继续按段翻译；
- `prose_exempt`：同页长正文保持段落，不能拆成逐行请求；
- 最终排版仍留在各自源 band/source block。

Courier p1 只作 diagnosis，中文 TOC 样张用于中译英验证。

## 2. 修改前必须阅读

- `babeldoc/magazine/minimal_pipeline.py::after_styles`
- `babeldoc/magazine/page_classifier.py`
- `babeldoc/magazine/hitl.py`
- `babeldoc/magazine/line_split.py`
- `babeldoc/magazine/chain_builder.py`
- `babeldoc/magazine/chain_signals.py`
- `babeldoc/format/pdf/document_il/midend/typesetting.py`
- 现有 structure/line-split 测试

## 3. 允许改动

- `babeldoc/magazine/minimal_pipeline.py`
- `babeldoc/magazine/line_split.py`，仅修聚焦测试暴露的问题
- `babeldoc/magazine/chain_builder.py`、`chain_signals.py`，仅处理 split 后 alias 和 record endpoint
- `babeldoc/magazine/hitl.py`，仅处理 split 前后 ruling 映射
- `babeldoc/format/pdf/document_il/midend/typesetting.py`，仅增加 no-expand 的 bounded render 调用
- `configs/line_split.json`，仅保留简单的最小可读 scale
- `tools/verify_magazine_demo.py` 的 `toc` 检查
- 新增 `tests/minimal/test_toc_demo.py`

禁止新增 TOC VLM、OCR、表格引擎、出版物特例、兼容层或完整 TOC IR。

## 4. 实现要求

固定顺序：

```text
PageClassifier
→ HITL page kind
→ line_split.apply
→ ChainBuilder
→ ArticleBuilder
```

要求：

- split 后再生成 chain/ArticleIR refs，避免陈旧索引。
- 标题+leader+folio 可保持一个视觉 record；下一行 byline 独立。
- 两个相邻单行 record 绝不重新粘合。
- uniform 多行块保持一个 block。
- 长 Editorial/prose 保持一个 paragraph。
- split 前后字符顺序和数量守恒。
- single/block record endpoint 不参与 chain；同页独立 prose 仍可参与正文 chain。
- report 保存 parent、ordered children、record kind、source band 和 source text hash。

正式 Typesetting 后：

- `single_visual_line` 在源 band 内单行排版；
- `block` 在源 block 内多行排版；
- `prose_exempt` 只在原 source box 内普通换行；
- 三类都禁止扩到相邻容器；装不下时保留完整文本并让 gate 失败。

## 5. 聚焦测试

新增 `tests/minimal/test_toc_demo.py`，覆盖双向：

- title/folio 与下一行 byline 分成两个 item；
- 两个单行记录不合并；
- 多行块保持一个 item；
- 长 prose 不拆行；
- split 后字符守恒、alias 唯一、ChainBuilder 使用新 refs；
- 混合 TOC/prose 页的正文 truth chain 仍 joint success；
- single 单行、block/prose 留在各自 source container；
- 无法容纳时明确失败，不吞字或借用相邻 band。

运行：

```text
uv run --no-sync pytest -q tests/minimal/test_toc_demo.py
```

## 6. 主控 paid 验收

运行非 Courier transfer、Courier diagnosis 和中文样张：

- 每个 single record 是独立翻译 item；
- block 按一个内容块翻译；
- prose 未被拆碎；
- split 前后文字完整；
- 相交 chain 仍准确联合翻译，无 fallback。

当前页若仍被 `article_flow` 或正式 Typesetting 移动，只记录问题并交给 Stage 03；source unit 错误必须在本阶段修复。

## 7. 返回主控

返回 pipeline 插入点、三类 record 结果、聚焦测试结果、双向 paid sidecar 摘要和需要 Stage 03 复核的页面。
