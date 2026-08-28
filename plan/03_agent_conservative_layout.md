# Agent 执行计划 03：关闭普通重排并保持源容器

目标分支：`migration/minimal-v0.6.4`

输入：Stage 01 chain、Stage 02 TOC 和冻结 layout expectations

## 1. 任务

固定 demo 路径关闭普通文章跨容器重排，阻止正文、chain member 和 TOC holder 被正式 Typesetting 扩到邻栏或移动出源容器。

本阶段接受短译文留下空白，不实现完整文章级 reflow。

## 2. 修改前必须阅读

- `babeldoc/magazine/minimal_pipeline.py::configure/after_translation/after_typesetting`
- `babeldoc/magazine/article_flow.py`
- `babeldoc/magazine/cross_page_reflow.py`
- `babeldoc/magazine/article_builder.py::_slot_box`
- `babeldoc/format/pdf/document_il/midend/typesetting.py`
- Stage 01/02 report 和测试

Courier p5 已知通栏导语和第一栏被 union 成宽槽，随后 6 个正文 paragraph 被放入单栏，这是必须修复的 diagnosis。

## 3. 允许改动

- `babeldoc/magazine/minimal_pipeline.py`
- `babeldoc/magazine/article_flow.py`
- `babeldoc/format/pdf/document_il/midend/typesetting.py`
- 必要时新增极小的 `babeldoc/magazine/layout_report.py`
- `tools/verify_magazine_demo.py` 的 `layout` 检查
- 新增 `tests/minimal/test_conservative_layout_demo.py`

不新增配置文件、CLI 开关、兼容模式、布局事务、碰撞恢复或完整 reflow 框架。minimal 路径直接固定关闭普通 flow。

## 4. 实现要求

- `minimal_pipeline.configure()` 固定 `magazine_column_reflow=false`。
- `article_flow.apply()` 在关闭时返回简单 report，且不修改 text、box、style、reading order 或 fixed assets。
- 正式 Typesetting 对 body、chain member、`single_visual_line`、`block`、`prose_exempt` 使用各自冻结 source box/band。
- 允许在源框内缩小和换行；禁止扩框、移到相邻栏、清空或截断 target。
- body chain 的 allocation box、formal holder 和最终文字区域必须都属于该 member source box。
- single TOC 保持单行；block/prose 只在原 block 内排版。
- target 在当前最小可读 scale 仍装不下时记录 overflow 并使 gate 失败，不开发自动重排。

`layout_report.json` 只需保存：

```text
source_ref / role / source_box
allocation_box / final_holder_box / final_text_box
status / overflow_reason
article_flow_applied=false
```

不需要多阶段 geometry lifecycle、checkpoint、seal 或 schema 兼容。

## 5. 聚焦测试

新增 `tests/minimal/test_conservative_layout_demo.py`，覆盖：

- 通栏导语+三栏正文保持原 x-band；
- disabled flow 对文档内容和固定资产零修改；
- en→zh、zh→en 的普通正文和 chain member留在源框；
- Stage 01 fragments 不被二次移动或合并；
- single/block/prose TOC 最终仍在源容器；
- 过长 target 明确 overflow，不扩框或删字。

运行：

```text
uv run --no-sync pytest -q tests/minimal/test_conservative_layout_demo.py
```

## 6. 主控 paid 验收

在当前代码上重新运行 Stage 01 chain、Stage 02 TOC 和 Stage 03 layout 页窗，覆盖 Courier、非 Courier 英文和中文多栏样张。

机器与视觉硬门：

- `article_flow_applied=false`；
- 所有正文/chain/TOC holder 唯一映射到 expectations；
- chain 仍 joint once、body fragment 非空、无 fallback；
- 通栏导语、各窄栏、图片和页脚不漂移；
- 最终文字不跨栏、不裁切、不越页；
- TOC single/block/prose 保持各自结构。

全部通过后再进入标题阶段。

## 7. 返回主控

返回固定关闭位置、聚焦测试结果、三份方向/刊物不同的 paid 页面对照，以及无法在源框内容纳的具体 element。
