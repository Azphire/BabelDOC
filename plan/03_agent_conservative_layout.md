# Agent 执行计划 03：关闭普通文章重排并保住 p5 三栏

目标分支：`migration/minimal-v0.6.4`  
起始基线：主控在 `controller-state.json` 下发的上一 verified SHA；该 SHA 必须包含计划 01–02 的 verified 结果  
执行角色：controller state 记录的唯一、持续复用执行 agent  

## 独立执行契约

- 开始前确认 branch 为 `migration/minimal-v0.6.4` 且仅一个 worktree；按 controller state 的 `entry_mode` 验证：`initial` 要求 HEAD=previous verified 且 clean，`dirty_followup` 要求 HEAD=expected HEAD、`allowed_dirty_paths` 精确相等，并用 state 指定且 SHA-256 已验的 helper 复算 `tree-state-v1`（覆盖 tracked staged/unstaged/deleted 与全部 untracked 文件）的 `handoff_tree_state_digest`，`committed_followup` 要求 HEAD=rejected candidate 且 clean。任一不符立即停止。
- `agent_id` 必须等于 controller state；不得创建子 agent、branch 或 worktree。
- 重验 `examples/input/Courier-en.pdf` 的 SHA-256 `9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a`。
- 只改 allowlist；不访问 C22，不接触 API key，不运行 paid。
- 不执行 `git add/commit/stash/reset/clean/rebase/amend/push`；主控验收时保持 idle。
- 所有命令用 `uv run --no-sync`；失败后只处理本阶段 follow-up，不进入下一计划。

## 1. 任务结果

固定 demo 路径停止对普通文章 paragraph box 做跨容器重新分配，让上游 Typesetting 在原源框内排版。p5 的通栏导语、三条正文栏、图片和页脚必须保持各自原几何区域。

本阶段保留计划 01 的连续链联合翻译与 member-box backfill。只关闭 `article_flow -> cross_page_reflow` 对普通段落的二次重排。

这是对 `main(3).tex` RQ2、贡献 3 和 3.4 节的有意 demo 降级。typed no-op 只证明固定路径没有破坏源网格，不能作为“完整文章级重排已实现”的证据。

## 2. 必须先核对的现状

开始修改前实际阅读：

- `babeldoc/magazine/minimal_pipeline.py::configure`
- `babeldoc/magazine/minimal_pipeline.py::after_translation`
- `babeldoc/magazine/article_flow.py`
- `babeldoc/magazine/cross_page_reflow.py`
- `babeldoc/magazine/article_builder.py::_slot_box`
- `babeldoc/format/pdf/document_il/midend/typesetting.py`
- `tests/minimal/test_article_flow_column.py`
- `tests/minimal/test_article_flow_page.py`
- `tests/minimal/test_flow_conservation.py`

paid p5 的真实源框：

- 通栏导语 `p5#7`：约 x=`56.8–471.8`。
- 第一栏 `p5#5`：约 x=`56.8–209.9`。
- 第二栏正文：约 x=`222.5–373.2`。
- 第三栏正文：约 x=`388.5–538.5`。

`ArticleBuilder._slot_box()` 将通栏导语和第一栏 union 成约 x=`56.8–471.8` 的宽槽；`article_flow` 随后把 6 个 paragraph 全部放入该槽。当前只有 p5 执行了普通 flow：1 segment、6 placements、0 真正跨页 movement。

## 3. 允许改动

产品代码：

- `babeldoc/magazine/minimal_pipeline.py`
- `babeldoc/magazine/article_flow.py`

测试：

- 新增固定文件 `tests/minimal/test_article_flow_disabled.py`
- 必要时更新 pipeline 固定属性测试
- 保留现有 direct article-flow unit tests
- 扩展 `tools/verify_courier_demo.py --check layout` 与 `tests/minimal/test_courier_demo_validator.py`

禁止改动 chain translation、ArticleBuilder 的几何/unsupported 启发式、dormant `column_reflow.py`、上游 Typesetting、TOC、标题、首字和 fixed asset 模块。

## 4. 实现要求

### 4.1 固定开关

在 `minimal_pipeline.configure()` 中把 `magazine_column_reflow` 从 fixed true 移到 fixed false。不要新增 CLI 参数、profile 或页面白名单。

`minimal_pipeline.after_translation()` 仍调用 `article_flow.apply()` 并要求 dict report，保持固定流水线和审计输出。

### 4.2 typed no-op report

`article_flow.apply()` 在开关关闭时不得返回 `None`。实现一个与当前 report schema 兼容的 typed no-op：

- `switch: magazine_column_reflow`
- `cross_page_segments: []`
- `issues: []`
- 保留 `eligible_roles`
- 每个 canonical article page 有一条 `status=skipped`、`action_status=not_executed`、`reason=switch_disabled`
- totals 明确写出 `segments_considered/applied/rolled_back`、`pages_considered/applied/rolled_back/skipped`、`placements` 和 `cross_page_movements`，所有 applied/movement/rollback 为 0
- considered/skipped 计数闭合
- 继续写 `article_flow.report.json`

no-op 路径不得修改 paragraph text、box、style、reading order、fixed assets 或 ArticleIR identity。direct 调用 flow 算法的现有单元测试继续保留，证明 dormant 实现仍可测试；固定 demo path 只选择 no-op。

## 5. 离线测试

构造一页包含：

- 一个全宽导语；
- 与它左边界接近的窄第一栏；
- 两个相邻窄正文栏；
- 一个 chain member pair；
- 一个固定图像障碍。

通过 `minimal_pipeline.after_translation()` 断言：

1. 直接调用 disabled `article_flow.apply()` 时全文 text/box/style/fixed inventory digest 严格不变。
2. 三条窄栏的 x-band 不变，通栏 box 不向下扩成正文容器。
3. chain 阶段已经写入的 member target 和 source box 不被二次移动。
4. fixed asset inventory 不变。
5. no-op report schema 完整，0 segment/placement/movement。
6. 每页 skipped reason 为 `switch_disabled`。
7. 完整 `after_translation()` 使用不会触发 paren/indent 的中性 fixture，重点断言 box/x-band、ArticleIR identity、chain allocation 和 fixed assets 不变。
8. minimal pipeline 仍完成 flow stage，不因 `None` 失败。
9. 直接调用 article/cross-page flow 的既有算法测试仍通过。

建议门：

```text
uv run --no-sync pytest -q tests/minimal/test_article_flow_disabled.py
uv run --no-sync pytest -q tests/minimal/test_article_flow_column.py
uv run --no-sync pytest -q tests/minimal/test_article_flow_page.py
uv run --no-sync pytest -q tests/minimal/test_flow_conservation.py
uv run --no-sync pytest -q tests/minimal/test_fixed_assets.py
uv run --no-sync pytest -q tests/minimal/test_courier_demo_validator.py
uv run --no-sync pytest -q tests/minimal
uv run --no-sync ruff check babeldoc/magazine/minimal_pipeline.py babeldoc/magazine/article_flow.py tools/verify_courier_demo.py tests/minimal/test_article_flow_disabled.py tests/minimal/test_courier_demo_validator.py
git diff --check
```

执行 agent 不启动 paid 请求。

## 6. 主控 paid 验收规格

主控创建新 run root，使用 `--pages 5`。本阶段只改变排版，可复用已验证翻译缓存；主控记录 cache hit 情况。

基础 validator 后运行机器门；exit 0 才进入视觉检查：

```text
uv run --no-sync python tools/verify_courier_demo.py --check layout --source <source.pdf> --output <output.pdf> --run-dir <run>/work/Courier-en --render-dir <run>/render --pages 5
```

报告：

- `article_flow.report.json` 存在且 typed no-op。
- `pages_applied=0`、`segments_applied=0`、`placements=0`、`cross_page_movements=0`。
- p5 translate-eligible 段落仍有 target；关闭 flow 不得制造漏译。
- chain report 中 p5 成功链仍守恒，allocation box 等于 source member box。

渲染：

- 通栏导语留在图像下/正文上方的原区域。
- 正文保留三个独立 x-band，近似为 `57–210`、`223–373`、`389–539`。
- 不出现横跨约 `57–538` 的正文 paragraph。
- 图片、标题、页脚和侧边 credit 不移动。
- 输出页数/page size 不变，source-fixed asset 几何/IoU 稳定。
- 无新增重叠、越页和裁切。

subset run 的 `pN#K` 可能按本地页重编号；主控必须用 `page.page_number + 1` 映射物理 p5，不能靠 ref 字符串判断页面。

## 7. 可接受降级与停止条件

可接受：

- 中文较短造成栏底留白；
- 普通段落继续使用 upstream 原框缩放；
- 非 demo 页面过长译文可保留 typed overflow/residual，后续由完整性门决定；p5 demo 内容不允许靠遗漏 target 获得无 overflow 的整洁页面；
- 完整文章级跨栏/跨页空间再分配暂不提供。

不可接受：

- 接入 dormant `column_reflow.py` 或重做 ArticleIR slot 模型；
- 在产品逻辑中硬编码 p5/页码/坐标；
- 同时关闭 chain joint translation；
- 为美观清空或截断装不下的 target；
- report 声称 applied 但没有实际 placement，或关闭后不产出 report。

## 8. 返回主控

完成离线门后立即返回：

- 固定开关与 no-op report 的实现位置；
- 前后 document/box/fixed-asset digest 证据；
- direct flow tests 与 fixed-path tests 的结果；
- 所有命令和 exit code；
- `git diff --stat`、`git diff --check`；
- p5 paid 视觉 checklist。

保留未提交工作树，等待主控 Git 与验收。
