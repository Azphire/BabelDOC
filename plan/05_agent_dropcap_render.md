# Agent 执行计划 05：首字下沉与放大首字渲染

目标分支：`migration/minimal-v0.6.4`

输入：Stage 00 的 keep/flatten expectations 和已通过 Stage 01–04 的布局

## 1. 任务

修复真实运行中 keep drop-cap 因字形度量错误而回滚的问题，并把现有首字模块接入最终流水线。

双向政策：

- en→zh：目标中文首字采用两行嵌入式下沉/放大布局；
- zh→en：目标英文首字母采用单行 raised initial；
- 首字节点与正文共同保持完整目标字符序列；
- drop-cap 所在段若属于 body chain，必须先 joint success，再处理目标 fragment。

## 2. 修改前必须阅读

- `babeldoc/magazine/drop_cap.py`
- `babeldoc/magazine/drop_cap_intent.py`
- `babeldoc/magazine/drop_cap_render.py`
- `babeldoc/magazine/minimal_pipeline.py::after_typesetting`
- `babeldoc/format/pdf/document_il/midend/typesetting.py` 的 font metrics
- 现有中英文 drop-cap 测试

当前错误来源：代码把全字体 bbox 当作单字符 bbox，得到不合理尺寸并触发 rollback。

## 3. 允许改动

- `babeldoc/format/pdf/document_il/midend/typesetting.py`，只增加当前字体实例的单字符度量 helper
- `babeldoc/magazine/drop_cap_render.py`
- `babeldoc/magazine/minimal_pipeline.py`
- `configs/drop_cap_render.json`，仅保留中英文现有布局参数
- `tools/verify_magazine_demo.py` 的 `dropcap` 检查
- 新增 `tests/minimal/test_dropcap_demo.py`

禁止开发跨平台字体兼容表、字体探测框架、缓存、回退字体管理、发布级 metrics abstraction 或刊物特例。

## 4. 实现要求

- 逐字符取得 glyph/advance bbox；不能再读取全字体 bbox。
- 如果当前字体 API 只有 advance，使用有限的 advance+em box 作为本次 demo 的简单度量，并在 report 标明来源。
- metric 必须有限、面积为正，并与当前 paragraph font/size 对应。
- 在 `title_typeset` 后调用 drop-cap renderer，使用同一正式 Typesetting/font mapper。
- 根据实际 target 找到第一个合法中文字符或 Latin 字母，记录 target index。
- 从正文 composition 中移出该字符并建立一个视觉首字 owner；最终字符序列仍与处理前完全相等。
- zh 的后续两行绕排，第三行恢复段框左边缘；en 只做单行 raised initial。
- metric 或布局失败时恢复该段原排版并让当前 gate 失败；不做文档级事务或自动重试。

`drop_cap_render.report.json` 每项只保存：

```text
source_ref / decision / target_char / target_index
direction_policy / metric_source / initial_box
before_target_sha256 / after_target_sha256
status / failure_reason
```

## 5. 聚焦测试

新增 `tests/minimal/test_dropcap_demo.py`，使用当前仓库可用字体覆盖：

- 全字体 bbox 不再进入单字度量；
- 中文首字和英文首字母度量有限且明显小于全字体 bbox；
- zh 两行嵌入、en raised initial 的最终布局；
- 标点开头时 target index 正确；
- 前后字符序列严格相等；
- chain fragment 先 joint success再处理，source box不变；
- metric失败时只恢复该 paragraph并返回 failure。

运行：

```text
uv run --no-sync pytest -q tests/minimal/test_dropcap_demo.py
```

不要求不同操作系统、系统字体集合或渲染后端兼容测试。

## 6. 主控 paid 验收

按样张轮换运行双向 drop-cap 页：

- 所有 required keep candidate 都进入 committed render；
- target_char 与实际译文首个合法字符一致；
- 中文两行下沉和英文 raised initial 视觉正确；
- 正文没有丢字、重复首字、重叠或越框；
- 相关 chain joint once、无 fallback且 fragments 不变；
- Courier 只作为最后的 diagnosis 回归。

## 7. 返回主控

返回 metric 修复位置、聚焦测试结果、每个 keep candidate 的 report 状态和双向页面截图。
