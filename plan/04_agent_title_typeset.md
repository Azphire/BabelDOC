# Agent 执行计划 04：接入中文标题单行排版

目标分支：`migration/minimal-v0.6.4`  
起始基线：主控在 `controller-state.json` 下发的上一 verified SHA；该 SHA 必须包含计划 01–03 的 verified 结果  
执行角色：controller state 记录的唯一、持续复用执行 agent  

## 独立执行契约

- 开始前确认 branch 为 `migration/minimal-v0.6.4` 且仅一个 worktree；按 controller state 的 `entry_mode` 验证：`initial` 要求 HEAD=previous verified 且 clean，`dirty_followup` 要求 HEAD=expected HEAD、`allowed_dirty_paths` 精确相等，并用 state 指定且 SHA-256 已验的 helper 复算 `tree-state-v1`（覆盖 tracked staged/unstaged/deleted 与全部 untracked 文件）的 `handoff_tree_state_digest`，`committed_followup` 要求 HEAD=rejected candidate 且 clean。任一不符立即停止。
- `agent_id` 必须等于 controller state；不得创建子 agent、branch 或 worktree。
- 重验 `examples/input/Courier-en.pdf` 的 SHA-256 `9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a`。
- 只改 allowlist；不访问 C22，不接触 API key，不运行 paid。
- 不执行 `git add/commit/stash/reset/clean/rebase/amend/push`；主控验收时保持 idle。
- 所有命令使用 `uv run --no-sync`；失败后只处理当前阶段 follow-up，不进入下一计划。

## 1. 任务结果

把已有 `title_typeset.py` 接入正式排版后的固定路径。已经完成翻译的中文标题在原视觉区域内优先压为单行，保持可读字号下限、文本守恒和越界保护。

本阶段不补翻译。计划 01 必须先让 p2–p3 跨页标题获得一份完整中文 target；计划 03 必须先稳定 paragraph box。

“英译中 demo 标题优先单行”是用户新增验收；TeX 的原要求是标题在原视觉区域内按角色排版并保持可读字号下限。

## 2. 必须先核对的现状

开始修改前实际阅读：

- `babeldoc/magazine/title_typeset.py`
- `configs/title_typeset.json`
- `babeldoc/magazine/minimal_pipeline.py::configure`
- `babeldoc/magazine/minimal_pipeline.py::after_typesetting`
- `babeldoc/magazine/minimal_detection.py` 的 baseline/越界检测
- `babeldoc/magazine/drop_cap_render.py` 的调用顺序要求
- 标题/阶段顺序相关 tests

现有模块已经提供：

- title class 识别；
- 移除标题首行缩进；
- 中文/default 最低 scale `0.55`；
- 英文最低 scale `0.8`，到 floor 后可 wrap/escalate；
- 重复标题层处理；
- `title_typeset.report.json`。

当前 `minimal_pipeline.configure()` 将 `magazine_title_typeset` 固定为 false，pipeline 没有 import/call，因此 paid run 没有该 report。p5“巴西：水域人民的教训”和 p7“生物盗窃的根源”可作现有中文标题正例；p2–p3 跨页大标题要在计划 01 后验收。

## 3. 允许改动

产品代码：

- `babeldoc/magazine/minimal_pipeline.py`
- `babeldoc/magazine/title_typeset.py`（仅接入现有算法、增加 TOC/page-policy 排除及聚焦测试证明的窄 bug）

测试：

- 新增固定文件 `tests/minimal/test_title_typeset_pipeline.py`
- 更新 stage-order/minimal pipeline 测试
- 扩展 `tools/verify_courier_demo.py --check title` 与 `tests/minimal/test_courier_demo_validator.py`

禁止修改 chain 翻译、普通 article flow、TOC、drop-cap 算法、上游通用 Typesetting 或翻译 prompt。禁止添加 Courier 页码、标题文本和坐标特例。

## 4. 实现要求

### 4.1 固定接入

在 `minimal_pipeline.configure()` 中把 `magazine_title_typeset` 放入 fixed true。

在正式 `Typesetting.typesetting_document()` 之后的 `minimal_pipeline.after_typesetting()` 中调用 `title_typeset.apply(config, docs)`。固定顺序：

```text
title_typeset.apply
→ refresh fixed detection baseline
→ drop_cap_render.apply
→ detect / repair
```

理由：detector 要看到最终标题几何，首字 renderer 要在已稳定的标题和正文布局上工作。

要求：

- `apply()` 必须返回合法 dict；silent `None` 由 fixed pipeline 拒绝。
- report 写入当前 run root。
- title pass 不更换 canonical ArticleIR 对象。
- preserve-line/record-structured TOC 内容必须按 page policy 跳过通用 title pass，即使 line split 后仍继承 title-class label。
- 非标题 paragraph 和非标题 fixed assets 不变；ArticleIR identity、source refs、holder box 与目标文字守恒。标题 composition、optimal scale、indent 和重复层属于允许变化对象。
- 标题文本不能丢字、重复或回退到源英文。

### 4.2 单行政策

复用现有配置：

- 已译中文标题在 `scale >= 0.55` 能容纳时必须 `single_line`。
- 标题保持原 visual region、对齐/颜色的现有冻结结果，不越页面或固定资产。
- 需要小于 floor 才能单行时保留可读排版，并在 report 中 typed escalation；不得无限缩字。
- p2–p3 跨页标题的完整中文 target 应由计划 01 放入主要 title holder；trailing released holder 不再显示源英文。

## 5. 离线测试

至少覆盖：

1. 中文标题在 scale 1 会换行、在 `0.55–1` 可容纳：最终一条 line band，report 为 `single_line`，无首行缩进。
2. 需要 `<0.55` 才能单行：保留可读布局，report escalation，文本完整且不重复。
3. 已经单行的中文标题：幂等，可报告 `unchanged`，不产生第二层文字。
4. 非标题 paragraph：text/box/style digest 不变。
5. trailing released 标题 holder：保持空/释放状态，不恢复英文。
6. 单个标题 `_render` 失败时只恢复该标题的正式排版；不新增文档级事务。
7. pipeline 顺序严格为 title → baseline → drop cap → detect。
8. `title_typeset.report.json` 内 disposition totals 闭合；不为此扩展 minimal root summary。
9. `TOC → title pass → TOC unchanged`：p1 record 数、视觉 band、文本和右侧 Editorial digest 不变。

建议门：

```text
uv run --no-sync pytest -q tests/minimal/test_title_typeset_pipeline.py
uv run --no-sync pytest -q tests/minimal/test_detectors.py
uv run --no-sync pytest -q tests/minimal/test_one_repair.py
uv run --no-sync pytest -q tests/minimal/test_drop_cap_chinese.py
uv run --no-sync pytest -q tests/minimal/test_courier_demo_validator.py
uv run --no-sync pytest -q tests/minimal
uv run --no-sync ruff check babeldoc/magazine/minimal_pipeline.py babeldoc/magazine/title_typeset.py tools/verify_courier_demo.py tests/minimal/test_title_typeset_pipeline.py tests/minimal/test_courier_demo_validator.py
git diff --check
```

执行 agent 不运行 paid 请求。

## 6. 主控 paid 验收规格

主控用新 run root 跑 `--pages 2-3`，可复用计划 01 已验证的翻译缓存。

基础 validator 后运行机器门；exit 0 才进入视觉检查：

```text
uv run --no-sync python tools/verify_courier_demo.py --check title --source <source.pdf> --output <output.pdf> --run-dir <run>/work/Courier-en --render-dir <run>/render --pages 2,3
```

硬检查：

- chain/tracking 证明 p2–p3 title target 已是完整中文。
- `title_typeset.report.json` 存在。
- demo 标题记录为 `single_line`；或为 `unchanged` 且 `lines_before=1`、中文 target 完整并由视觉确认仍为一行。拒绝 `floor_reached`、`relayout_failed` 和源英文残留。
- p2 主要标题 holder 文本完整；p3 源标题 holder 无英文残留。
- 标题字符守恒、无重复层；`single_line` 的 report scale 不低于 `0.55`，`unchanged` 用最终字号与视觉可读性验收。

视觉检查：

- 完整中文标题只显示一行。
- 位于原主标题视觉区域内，无裁切、重叠或出页。
- 字号仍可读，正文和图像没有移动。

最终整本还需复核 p5、p7 已有中文标题继续保持单行，并确认 p1 TOC 不被 title pass 改写。源 p1 logo 若本来越界且未漂移属于 baseline condition；不得为固定 page furniture 增加标题特例。

## 7. 可接受降级与停止条件

可接受：

- 非 demo 极端标题在可读 floor 后保持有限多行并 typed escalation；
- 不精确复制源标题的字距/字偶距；
- 中文标题使用现有字体 fallback；
- p2–p3 的第二个源 holder作为 trailing release 清空。

不可接受：

- 用 `<0.55` 的极端缩放强行单行；
- 把未翻译英文标题当排版成功；
- 修改普通正文 box 或启用 article reflow；
- 标题字符丢失、重复或侵入固定图像；
- 在通用产品逻辑中硬编码 Courier 内容。

subset run 的 report 页码与本地 `pN#K` 可能采用不同坐标系；主控按 `page.page_number + 1` 映射物理 p2/p3。trailing holder 的清空由计划 01 完成，本阶段只保证英文不重新出现。

## 8. 返回主控

完成离线门后立即返回：

- fixed flag 和调用顺序变更；
- 正常单行、floor escalation、rollback 三类测试结果；
- title report 的关键字段；
- 所有测试命令与 exit code；
- `git diff --stat`、`git diff --check`；
- p2–p3、p5、p7 的视觉验收清单。

保留未提交工作树，等待主控处理 Git 与 paid gate。
