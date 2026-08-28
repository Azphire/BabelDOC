# Agent 执行计划 04：双向标题排版

目标分支：`migration/minimal-v0.6.4`

输入：已通过最终源容器验收的 Stage 01–03 代码和标题 expectations

## 1. 任务

把已有 `title_typeset.py` 接入固定流水线：

- en→zh 的 required 中文标题在源标题区域内排成单行；
- zh→en 标题保持完整、可读，并留在源标题区域；
- 标题 chain 的完整 target、holder 和最终渲染守恒；
- TOC record 不被标题 pass 二次处理。

## 2. 修改前必须阅读

- `babeldoc/magazine/title_typeset.py`
- `babeldoc/magazine/minimal_pipeline.py::after_typesetting`
- 正式 Typesetting 实例的传递路径
- Stage 01 title/display chain report
- Stage 02 typed TOC record 标记
- 现有标题测试

## 3. 允许改动

- `babeldoc/magazine/minimal_pipeline.py`
- `babeldoc/magazine/title_typeset.py`
- `babeldoc/format/pdf/document_il/midend/typesetting.py`，仅复用 no-expand bounded render
- `configs/title_typeset.json`，仅保留双向最小 scale/行数政策
- `tools/verify_magazine_demo.py` 的 `title` 检查
- 新增 `tests/minimal/test_title_demo.py`

禁止修改 chain、TOC 分类、普通 flow、drop-cap、prompt，或增加刊物/页码/文本特例、兼容层和新排版框架。

## 4. 实现要求

固定顺序：

```text
正式 Typesetting
→ TOC record fitter
→ title_typeset.apply
→ drop-cap（Stage 05）
→ 最终 PDF
```

要求：

- 复用正式 Typesetting/font mapper 实例，不新建第二套。
- 在正式排版前保存 title source box 和基础字体大小。
- TOC single/block/prose、caption、credit、folio 不进入标题 pass。
- zh target 在 source title box 内寻找可读的单行 scale。
- en target 允许 expectations 指定的有限换行，但不得截断或越出 source box。
- 标题 target 在 pass 前后字符序列不变。
- title/display chain 若使用唯一 active holder，trailing holder 不得重新显示源文本或重复 target。
- 装不下时报告 failure，不能清空、裁切或借用正文栏。

## 5. 聚焦测试

新增 `tests/minimal/test_title_demo.py`，覆盖：

- 两个不同中文长度的 en→zh 标题在源框内单行；
- zh→en 长标题完整保留并限制行数；
- TOC record、caption、credit 不被处理；
- 两 member title chain 只有一个有效 target owner，无重复/残留；
- target digest 和字符序列守恒；
- 无法容纳时明确失败。

运行：

```text
uv run --no-sync pytest -q tests/minimal/test_title_demo.py
```

## 6. 主控 paid 验收

先跑非 Courier 英文标题页，再回归 Courier，最后跑中文源标题页：

- required zh 标题单行且可读；
- en 标题完整留在源区；
- title chain joint once、无 fallback、无重复 holder；
- 正文、TOC、图片和页脚没有被标题 pass 移动；
- 无源标题残留、裁切或重叠。

## 7. 返回主控

返回接入顺序、改动文件、聚焦测试结果、双向标题页面截图和仍无法在最小 scale 内容纳的标题。
