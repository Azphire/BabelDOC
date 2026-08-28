# Agent 执行计划 05：首字下沉生产字形度量修复

目标分支：`migration/minimal-v0.6.4`  
起始基线：主控在 `controller-state.json` 下发的上一 verified SHA；该 SHA 必须包含计划 01–04 的 verified 结果  
执行角色：controller state 记录的唯一、持续复用执行 agent  

## 独立执行契约

- 开始前确认 branch 为 `migration/minimal-v0.6.4` 且仅一个 worktree；按 controller state 的 `entry_mode` 验证：`initial` 要求 HEAD=previous verified 且 clean，`dirty_followup` 要求 HEAD=expected HEAD、`allowed_dirty_paths` 精确相等，并用 state 指定且 SHA-256 已验的 helper 复算 `tree-state-v1`（覆盖 tracked staged/unstaged/deleted 与全部 untracked 文件）的 `handoff_tree_state_digest`，`committed_followup` 要求 HEAD=rejected candidate 且 clean。任一不符立即停止。
- `agent_id` 必须等于 controller state；不得创建子 agent、branch 或 worktree。
- 重验 `examples/input/Courier-en.pdf` 的 SHA-256 `9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a`，并记录当前 uv runtime 的 PyMuPDF 版本。
- 只改 allowlist；不访问 C22，不接触 API key，不运行 paid。
- 不执行 `git add/commit/stash/reset/clean/rebase/amend/push`；主控验收时保持 idle。
- 所有命令使用 `uv run --no-sync`；失败后只处理当前阶段 follow-up，不进入下一计划。

## 1. 任务结果

让 Courier 的三个 `keep` 决定真正生成可见中文两行嵌入式首字：

| source ref | 源首字 | 旧 paid target 首字（诊断值） |
| --- | --- | --- |
| `p4#3` | `L` | `在` |
| `p5#5` | `O` | `在` |
| `p7#8` | `T` | `世` |

现有候选识别、HITL、首字与正文逻辑合并、翻译 intent、打包、回滚和几何守卫继续使用。本阶段只修 `Typesetting.glyph_ink_metrics()` 将字体全局 bbox 当成逐字 bbox 的生产故障。

新 paid run 的译文可能变化，硬门使用“rendered initial 等于完整目标译文第一个合法目标字符，target index 指向该位置，渲染字符序列与 paragraph target 完全相等”；不写死表中的三个旧字符，也不按 Unicode 值统计自然重复字。

## 2. 必须先核对的现状

开始修改前实际阅读：

- `babeldoc/format/pdf/document_il/midend/typesetting.py::GlyphInkMetric`
- `babeldoc/format/pdf/document_il/midend/typesetting.py::glyph_ink_metrics`
- `babeldoc/magazine/drop_cap.py`
- `babeldoc/magazine/drop_cap_intent.py`
- `babeldoc/magazine/drop_cap_render.py`
- `configs/drop_cap_render.json`
- `tests/minimal/test_drop_cap_chinese.py`
- `tests/minimal/test_drop_cap_english.py`
- `tests/minimal/test_drop_cap_keep_flatten.py`

paid 基线中三条均已满足：

- HITL `keep` 应用；
- 源首字与正文合并翻译；
- target intent valid；
- `ink_top_delta=0`、`ink_bottom_delta=0`，打包位置与锚点公式内部自洽；视觉 ink 锚定仍待修复后验证。

三条最终都在 `_set_chinese_two_line_initial()` 的 `body_fits` 守卫回滚，reason 为 `reached_past_its_own_box`。不同 CJK glyph id 得到相同约 `3.9263em × 2.8579em` bbox，强烈表明 `pymupdf.Font.glyph_bbox()` 在该生产字体返回全字体 bbox。现有成功测试使用手写 `0.9em × 1em` metric，因此没有覆盖真实故障。

## 3. 允许改动

产品代码：

- `babeldoc/format/pdf/document_il/midend/typesetting.py`
- 如需要补充审计说明，可窄改 `configs/drop_cap_render.json`

测试：

- `tests/minimal/test_drop_cap_chinese.py`
- `tests/minimal/test_drop_cap_english.py`
- 新增固定文件 `tests/minimal/test_glyph_ink_metrics_production.py`
- 扩展 `tools/verify_courier_demo.py --check dropcap` 与 `tests/minimal/test_courier_demo_validator.py`

原则上不修改：

- `drop_cap.py`
- `drop_cap_intent.py`
- `drop_cap_render.py`
- `hitl.py`
- `minimal_pipeline.py`
- 人工 decisions

若执行 agent 证明 renderer 仍有独立 bug，先把最小复现和拟改文件发给主控，等待 follow-up；不要顺手放宽页面/文章/碰撞守卫。

## 4. 实现要求

在 `Typesetting.glyph_ink_metrics()`：

1. 正常读取 `glyph_bbox(codepoint)`、`glyph_advance(codepoint)` 和 glyph id。
2. 同时取得 `font.bbox`。用 `x0/y0/x1/y1` 或 `pymupdf.Rect(...)` 统一规范化 `Rect` 与不可迭代 `FzRect`；禁止直接 `tuple(font.bbox)`。
3. 只有 global bbox 存在、可规范化且全部有限时才比较；用 `math.isclose(..., rel_tol=1e-6, abs_tol=1e-6)` 比较四坐标。
4. 两者四个坐标近似相同，判为无法获得逐字 ink bbox。
5. 此时继续使用真实 `advance_em`，ink box 固定降级为 `(0.0, 0.0, advance_em, 1.0)`。
6. `GlyphInkMetric.source` 记录 `advance_em_box_fallback`。
7. global bbox 缺失/不可用/非有限时，只要 glyph bbox 合法就保留原路径；正常且明显不同的逐字 bbox 也保持原 source。
8. 非有限 glyph 值、缺字形、非正 advance 等现有 invalid 分支保持返回 `None`；新增属性读取不得吞掉既有未知异常语义。
9. 更新 `glyph_ink_metrics()` docstring，说明 fallback 忽略 bearing、descender 和 overhang，守卫使用的是近似 em box。

修改前先在实际 uv runtime 输出 PyMuPDF 版本、font global bbox、`在/世/A` 的 glyph bbox 与 advance，保存为离线根因证据，不写出版物特例。

不要通过调大容差、扩大段框、关闭 `body_fits` 或降低碰撞阈值来绕过问题。页面边界、文章边界、正文守恒、固定资产和事务回滚继续生效。

## 5. 离线测试

### production metric regression

假字体行为：

- `font.bbox` 是不可迭代 Rect-like；不同 codepoint/glyph id 的 `glyph_bbox()` 都返回与它相同的 `3.9263 × 2.8579`。
- `glyph_advance()` 返回各字符真实正值。

断言 resolver：

- 选择 `advance_em_box_fallback`；
- glyph id 和 advance 保留；
- ink box 有限、宽度为 advance、高度为 1em；
- 正常逐字 bbox 仍走原 source；
- 明确不同的合法 global/glyph bbox 保持原 source；
- global bbox 缺失/非有限时保留合法 glyph 路径；无字形、异常值和未知异常传播测试继续通过。

### renderer integration

用真实 `Typesetting.glyph_ink_metrics()` 接口和上述假字体调用真实 `drop_cap_render.apply()`，不可 monkeypatch `set_one()`。断言：

- `decided=1`、`set=1`、`reverted=0`；
- render state 为 committed；
- 首字字号明显大于正文；
- 中文前两行在首字右侧，第三行恢复段框左边缘；
- 全部文字逐字守恒；
- fixed asset 和 page/article bounds 守卫仍会对真实冲突回滚。
- `validation.post_render.valid=true` 且四项 checks 全真；collision、page bounds、article bounds 分别制造冲突并验证完整 digest 回滚。
- 至少一条英文路径也走 production resolver；中文 fixture 含标点、数字和 Latin 片段。

同时保留英文单行放大首字、keep/flatten 和 HITL 测试。

建议门：

```text
uv run --no-sync pytest -q tests/minimal/test_glyph_ink_metrics_production.py
uv run --no-sync pytest -q tests/minimal/test_drop_cap_english.py
uv run --no-sync pytest -q tests/minimal/test_drop_cap_chinese.py
uv run --no-sync pytest -q tests/minimal/test_drop_cap_keep_flatten.py
uv run --no-sync pytest -q tests/minimal/test_hitl_export_apply.py
uv run --no-sync pytest -q tests/minimal/test_fixed_assets.py
uv run --no-sync pytest -q tests/minimal/test_courier_demo_validator.py
uv run --no-sync pytest -q tests/minimal
uv run --no-sync ruff check babeldoc/format/pdf/document_il/midend/typesetting.py tools/verify_courier_demo.py tests/minimal/test_glyph_ink_metrics_production.py tests/minimal/test_drop_cap_chinese.py tests/minimal/test_drop_cap_english.py tests/minimal/test_courier_demo_validator.py
git diff --check
```

执行 agent 不运行 paid 请求。

## 6. 主控 paid 验收规格

主控使用新 run root 跑 `--pages 4,5,7`。本阶段只改字形/首字渲染；可尝试复用已验证 translation cache，但仍提供 key 并记录实际 hit/miss。

基础 validator 后必须先运行本阶段机器门；exit 0 才进入原分辨率视觉检查：

```text
uv run --no-sync python tools/verify_courier_demo.py --check dropcap --source <source.pdf> --output <output.pdf> --run-dir <run>/work/Courier-en --render-dir <run>/render --pages 4,5,7
```

报告硬检查：

- `drop_cap.report.json` 恰有 `p4#3,p5#5,p7#8` 候选。
- `hitl_apply.report.json` 三条均为 `keep`。
- `drop_cap_apply.report.json` 为 `decided=3, merged=3`。
- `drop_cap_render.report.json` 为 `decided=3, set=3, reverted=0`。
- 逐 `paragraphs[].paragraph` 断言三条均 `render_state=committed`、`set=true`、`reverted=false`、`reserve_lines=2`、`validation.valid=true`、`validation.post_render.valid=true` 且四项 checks 全真。
- `paragraphs[].style_evidence.metric_source` 可以是 `advance_em_box_fallback`，也可以是实际 runtime 中有限且与 global bbox 明显不同的真实逐字 metric；禁止把 global bbox 继续当逐字 metric。
- `drop_cap_intent.report.json` 为 `rendered=3`，每个 initial 等于该段完整 target 的第一个合法中文字符，target index 正确；post-render coverage 为真且没有额外插入/删除首字节点。
- 旧 `typed_no_candidate` 汇总不能替代上述硬计数。

视觉/几何检查：

- 三个首字 `initial_size/body_size >= 1.8`，肉眼可见。
- `ink_top_delta/bottom_delta` 在配置容差内；前两行正文起点不早于 `initial_ink_box.right + gutter`，第三行恢复原左边缘。
- 首字和正文均在文章/page bounds 内，无碰撞、裁切和固定资产漂移。
- p5 仍保持计划 03 的三栏。
- 输出仍为完整 8 页、文字可选择。

## 7. 可接受降级与停止条件

可接受：

- 使用 advance/em 近似，暂不追求光学级单字 ink bbox；
- 近似会忽略 bearing、descender 和 overhang，p4/p5/p7 原分辨率视觉检查因此是不可替代门；
- 不精确复制 ICC、专色或源首字字形；
- 三条 Courier keep 之外，真正少于两行、过窄或与固定资产冲突的候选继续 typed rollback；
- zh→en 本轮只证明 production resolver 与流程可运行，不承诺复杂拉丁字形的精确碰撞检测。

不可接受：

- Courier 三个 keep 仍有任一 rollback；
- 关闭几何守卫或放宽段框来掩盖全字体 bbox；
- 首字文字从正文中重复或丢失；
- 重新实现首字候选/HITL/renderer；
- 在本阶段修改 p5 栏布局。

## 8. 返回主控

完成离线门后立即返回：

- glyph/global bbox 判定和 fallback 记录方式；
- production resolver regression 与真实 renderer integration 结果；
- 中英文、keep/flatten、fixed asset 测试结果；
- 所有命令及 exit code；
- `git diff --stat`、`git diff --check`；
- 三个 paid 首字需要核查的 report 字段和视觉点。

保留未提交工作树，由主控完成 Git、paid 和视觉门。
