# Agent 执行计划 01：连续链联合翻译与源框回填

目标分支：`migration/minimal-v0.6.4`

输入：Stage 00 已冻结的 sample matrix 和 expectations

## 1. 任务

修复英译中和中译英的跨栏、跨页连续段落：

1. detector 准确找到人工 positive truth，且不连接 negative endpoints；
2. 同一 chain 合并源文后只进行一次语义翻译；
3. 完整 target 按 member 顺序分配；
4. 每个 body member 得到非空 fragment；
5. fragment 写回该 member 自己的 source box；
6. planning 失败时释放 claim，避免成员永久漏译，但该 run 仍判失败。

Courier 已知 7 条 chain 只有 1 条成功、12 个成员漏译，是 diagnosis，不得写成产品特例。

## 2. 修改前必须阅读

- `babeldoc/magazine/chain_builder.py`
- `babeldoc/magazine/chain_signals.py`
- `babeldoc/magazine/chain_translation.py`
- `babeldoc/magazine/chain_backfill.py`
- `babeldoc/magazine/article_builder.py`
- `babeldoc/magazine/article_ir.py`
- `babeldoc/magazine/minimal_pipeline.py`
- 普通 page/cross-column/cross-page translation producer
- 现有 chain 相关测试

## 3. 允许改动

- `babeldoc/magazine/chain_builder.py`
- `babeldoc/magazine/chain_signals.py`
- `babeldoc/magazine/article_builder.py`，仅统一 reading order/region evidence
- 必要时新增 `babeldoc/magazine/column_grid.py`
- `babeldoc/magazine/chain_translation.py`
- `babeldoc/magazine/chain_backfill.py`
- `babeldoc/magazine/minimal_pipeline.py`
- `babeldoc/magazine/minimal_detection.py`
- `babeldoc/magazine/short_unit.py` 或其固定调用点，仅用于释放成员的漏译保护
- `tools/verify_magazine_demo.py` 的 `chain` 检查
- 新增 `tests/minimal/test_chain_demo.py`

禁止新增 publication/page/ref 特例、feature flag、兼容层、重试框架、secret launcher、状态 ledger 或发布级测试。

## 4. 实现要求

### 4.1 detector

- 同页跨栏和相邻跨页使用通用几何、角色、样式、文本连续性信号。
- 混合栏页面按局部垂直区域判断相邻栏，不能用全页单一 x-band。
- 物理页不相邻时不能形成跨页 chain。
- title、caption、credit、byline 和不同文章正文不能误连。
- report 保存 detected chain 的物理页、source ref、source text hash、source box、role 和 member order，供 verifier 与 expectations 比较。

### 4.2 联合翻译和回填

- chain slot 直接来自每个 `SourceElementRef.source_box`，不使用整栏 `article.slots`。
- preflight 在永久 claim 前完成；失败后所有 member 回到普通可调度状态。
- 合并文本只进入一次 application-level semantic translation。
- body target 分配时为后续 member 保留至少一个合法切分单元，所有 body fragments 非空。
- fragment 拼接后必须等于完整 target，并写回各自 source box。
- title/display 仅在两个 holder 确实是重复视觉层时允许由一个 holder 承载完整 target；body 不允许空 trailing member。
- joint success 后，普通翻译 producer 必须跳过这些 member。
- 释放后的短 member 必须能进入现有 short-unit 路径，不能停在 pending。

### 4.3 最小 sidecar

`chain_translation.report.json` 每条 chain 保存：

```text
chain_id / ordered_source_refs / source_boxes
merged_source_sha256 / joint_call_count
whole_target_sha256 / ordered_fragments
fragment_boxes / outcome / fallback_reason
```

无需 request transport ledger、PID、retry 或跨版本 schema。

## 5. 聚焦测试

新增一个 `tests/minimal/test_chain_demo.py`，覆盖：

- en→zh、zh→en 各一条跨栏和跨页 body chain；
- 一条三 member `column → page` chain；
- 相邻 negative endpoint 不成链；
- unsupported page/不连续 ArticleIR slot 仍使用 member source box成功；
- 每条 success 只调用一次 fake translator；
- body fragments 全非空，拼接守恒，box 不变；
- planning failure 释放 claim，short-unit/普通路径能接管一次，但 verifier 拒绝 fallback run；
- joint member 不被普通 producer 重复翻译。

运行：

```text
uv run --no-sync pytest -q tests/minimal/test_chain_demo.py
```

不跑全测试套件、并发/重试、跨平台或旧 schema 兼容测试。

## 6. 主控 paid 验收

按 Stage 00 顺序运行另一刊物 transfer、Courier diagnosis 和双向 holdout。此阶段只检查 chain report 与写回后的 IL：

- 所有 positive truth exact member/order 命中；
- negative 和额外未裁决 chain 为零；
- 每条 truth `joint_call_count=1`、无 fallback；
- body fragments 全非空并分别使用 member source box；
- 普通 producer 没有 joint member；
- 两个方向都覆盖跨栏和跨页正文。

最终 PDF 是否仍留在源框由 Stage 03 关闭 `article_flow` 后统一复核，避免因已知下游布局问题阻塞本阶段。

## 7. 返回主控

返回改动文件、实现要点、聚焦测试结果、各样张 chain report 摘要和未解决的 truth chain。不得进入 TOC、普通重排、标题或首字代码。
