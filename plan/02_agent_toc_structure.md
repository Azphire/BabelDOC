# Agent 执行计划 02：TOC 单行记录与块状记录

目标分支：`migration/minimal-v0.6.4`  
起始基线：主控在 `controller-state.json` 下发的上一 verified SHA；该 SHA 必须包含计划 01 的 verified 结果  
执行角色：controller state 记录的唯一、持续复用执行 agent  

## 独立执行契约

- 开始前确认 branch 精确为 `migration/minimal-v0.6.4` 且仅一个 worktree；按 controller state 的 `entry_mode` 验证：`initial` 要求 HEAD=previous verified 且 clean，`dirty_followup` 要求 HEAD=expected HEAD、`allowed_dirty_paths` 精确相等，并用 state 指定且 SHA-256 已验的 helper 复算 `tree-state-v1`（覆盖 tracked staged/unstaged/deleted 与全部 untracked 文件）的 `handoff_tree_state_digest`，`committed_followup` 要求 HEAD=rejected candidate 且 clean。任一不符立即停止。
- 当前 `agent_id` 必须等于 controller state；不得创建子 agent、branch 或 worktree。
- 重验 `examples/input/Courier-en.pdf` 的固定 SHA-256 `9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a`。
- 只修改本文件 allowlist；不访问 C22 工作目录，不读取/使用 API key，不运行 paid。
- 不执行 `git add/commit/stash/reset/clean/rebase/amend/push`；主控验收期间保持 idle。
- 所有 Python/test/lint 命令用 `uv run --no-sync`；失败后只处理本阶段 follow-up，不进入下一计划。

## 1. 任务结果

把已有 `line_split.py` 接入真实固定流水线，使 TOC 在翻译前恢复视觉记录：

- 单行目录：每个源视觉行独立成翻译单元，禁止和下一行作者、页码或相邻条目合并。
- 块状目录：紧密组成一个内容块的多行文本继续按段翻译。
- 同一物理页上的非 TOC 长正文保持段落，不被拆成逐行请求。

本计划把“单行型”定义为一个视觉行一个 record，把“块状型”定义为几何上紧密的多行 group 一个 record；p1 右侧 Editorial 属于 prose exemption。标题行和下一行 byline 分成两个视觉 record，逻辑 TOC entry 可用 parent/group 关联，但翻译请求不能重新合并两行。这是用户新增的 demo 规则；TeX 只要求完整 record 使用角色政策。

Courier p1 左侧是 Contents，右侧是 Editorial。页面级 HITL 已将 p1 标为 `toc`；本阶段必须依靠 line/record 判据保护右侧长正文，不能把整页粗暴拆行。

## 2. 必须先核对的现状

开始修改前实际阅读：

- `babeldoc/magazine/minimal_pipeline.py::after_styles`
- `babeldoc/magazine/page_classifier.py`
- `babeldoc/magazine/hitl.py` 的 page-kind pass 和 labeled pages
- `babeldoc/magazine/line_split.py`
- `babeldoc/magazine/fragment_stitch.py`
- `babeldoc/magazine/chain_builder.py`
- `configs/page_types.json`
- `configs/line_split.json`
- `tests/minimal/test_structure_pipeline.py`

当前真实顺序为：

```text
PageClassifier
→ HITL page kind
→ ChainBuilder
→ ArticleBuilder
```

`magazine_line_structure=true` 已设置，但没有 caller。paid p1 的 tracking 已出现类似：

```text
Brazil: lessons from the water people ..... 9
Marcelo Silva de Sousa
```

落在同一个 paragraph 的输入，模型无法可靠恢复源视觉行。`line_split.py` 已能从 character geometry 恢复 line，对 preserve-line page 拆短异质 record，并保留长 uniform prose。

## 3. 允许改动

产品代码：

- `babeldoc/magazine/minimal_pipeline.py`
- 只有聚焦测试或 p1 paid 证明确有窄缺口时，才允许最小修改 `babeldoc/magazine/line_split.py`

测试：

- 新增 `tests/minimal/test_toc_line_structure.py`
- 更新 `tests/minimal/test_structure_pipeline.py`
- 必要时更新 line-split 直接测试
- 扩展 `tools/verify_courier_demo.py --check toc` 与 `tests/minimal/test_courier_demo_validator.py`

禁止新增 TOC VLM、出版物名/页码特例、通用表格引擎、OCR、自动 TOC subtype 模型或新的排版框架。不要修改联合翻译、article flow、title/dropcap 和 detector。

## 4. 实现要求

### 4.1 固定接入点

在 `minimal_pipeline.after_styles()` 中：

```text
classifier.process(docs)
→ hitl.begin_run(...)
→ hitl.page_kind_pass(...)
→ line_split.apply(config, hitl.labeled_pages(docs))
→ ChainBuilder(config).process(docs)
→ ArticleBuilder(config).process(docs)
```

要求：

- import 和调用进入固定路径，不新增用户开关。
- `line_split.apply()` 返回值必须是合法 dict；silent `None` 或异常由 minimal pipeline 明确拒绝。
- split 完成后再生成 chain/ArticleIR 使用的 paragraph/source refs，禁止这些下游保留拆分前的陈旧索引。HITL page-kind 已先应用；Courier p1 不允许存在 paragraph-index/drop-cap ruling，其他 TOC 页的旧 paragraph ruling 自动重映射不在本轮范围。
- report 写到当前 run 的 `line_split.report.json`。

`fragment_stitch.py` 本轮先不接入。若执行 agent 证明 line_split 后普通正文出现独立碎片，先提交证据给主控；不得顺手扩大范围。

### 4.2 记录政策

复用现有配置和几何判据，必须满足：

- `preserve_line_structure=false` 的普通页面不变。
- TOC 中短、异质 style、带 leader/folio 的视觉行可独立拆分。
- 相邻视觉行即使水平范围接近，也不能因同一旧 paragraph 而重新粘合。
- 紧密多行且属于同一块的 uniform-style 文字可保持一个 block。
- 长 Editorial prose 保持段落。
- 数字页码和 leader 可与其所属标题行保持同一 record；作者若在下一视觉行则必须独立。
- split 前后字符顺序和字符总量守恒。
- 每个原字符及重建 composition 的 font id、font size、graphic state 语义守恒；paragraph base style 允许按 record 的主要字符样式重选。
- record group、page role 与原视觉 band 建立稳定映射，供后续 title pass 识别并跳过 preserve-line/record-structured TOC 内容。

若现有 `line_split.py` 已满足上述要求，只修改 pipeline 和测试。

## 5. 离线测试

新增合成 fixture，至少覆盖：

1. page classifier 先给 `editorial`，HITL 覆盖为 `toc`，line split 随后执行。
2. `title + leader + folio` 在第一视觉行，byline 在第二视觉行：输出两个 paragraph/record，翻译请求不得跨行。
3. 两个相邻单行目录：输出两个独立 record。
4. 紧密多行块状目录：保持一个 paragraph，按段翻译。
5. p1 右侧长 uniform-style Editorial：保持一个 paragraph。
6. 非 TOC 页面：document/paragraph digest 不变。
7. `lines_before == lines_after`、字符序列和字符级样式语义守恒；不要求 paragraph style object identity。
8. ChainBuilder/ArticleBuilder 使用 split 后 refs，无 stale ref。
9. `line_split.report.json` 的 `declared_pages`、`split_paragraphs`、`line_paragraphs`、`exempt_paragraphs`、`short_lines` 和每页 `lines_before/lines_after` 正确；字符/样式守恒由 fixture 直接比较，不扩展 report schema。

建议门：

```text
uv run --no-sync pytest -q tests/minimal/test_toc_line_structure.py
uv run --no-sync pytest -q tests/minimal/test_structure_pipeline.py
uv run --no-sync pytest -q tests/minimal/test_structure_real_pdf.py
uv run --no-sync pytest -q tests/minimal/test_courier_demo_validator.py
uv run --no-sync pytest -q tests/minimal
uv run --no-sync ruff check babeldoc/magazine/minimal_pipeline.py babeldoc/magazine/line_split.py tools/verify_courier_demo.py tests/minimal/test_toc_line_structure.py tests/minimal/test_structure_pipeline.py tests/minimal/test_courier_demo_validator.py
git diff --check
```

执行 agent 只跑离线/fake 测试，不启动 paid 请求。

## 6. 主控 paid 验收规格

主控创建新 run root，使用 `--pages 1 --ignore-cache`：

基础 validator 后运行机器门；exit 0 才进入视觉检查：

```text
uv run --no-sync python tools/verify_courier_demo.py --check toc --source <source.pdf> --output <output.pdf> --run-dir <run>/work/Courier-en --render-dir <run>/render --pages 1
```

报告与 tracking：

- p1 最终 page kind 为 HITL `toc`。
- `line_split.report.json` 存在且有非零 split。
- `Brazil...9` 与 `Marcelo...` 不在同一个翻译 paragraph。
- 各单行条目不包含下一视觉行的作者或相邻条目。
- 块状条目仍按一个内容块/段落进入翻译。
- 右侧 Editorial 长正文没有被拆成逐行 requests。
- split 前后字符守恒，无陈旧 source ref。
- `short_lines` 中没有应翻译却被长度门丢弃的目录标题；folio、专名、缩写只有带 typed reason 才可保留。

渲染检查 p1：

- 左侧选定单行目录保持单行和独立纵向 band；除 record group 明确认定的紧密多行块外，两条独立视觉记录不得合并。
- 页码、标题、作者不会粘到下一条记录。
- 块状目录保持块状层级，不被打散成零散行。
- 右侧 Editorial 仍是连续正文。
- 不新增裁切、覆盖或越页。

## 7. 可接受降级与停止条件

可接受：

- leader dots 长度、字距和右端对齐近似源版；
- subtype 依赖既有 HITL page kind 与几何分组，不自动识别所有杂志 TOC；
- 非关键 record 可在可读字号下无法容纳时进入 typed residual；选定 demo 单行若仍换行，本阶段停止并请求主控授权只作用于 TOC record 的窄 fitter，不能交通用标题 pass。
- p1 logo 若在 source 已越界且未漂移，记录为 baseline condition；本阶段不移动固定 page furniture。

不可接受：

- 按整页每个视觉行拆右侧 Editorial；
- 把两条源视觉行合成一个翻译段；
- 为 Courier 写页码、刊物名、固定坐标或文本内容特例；
- 破坏字符/样式守恒；
- 在本阶段开发点线排版器或完整 TOC IR。

## 8. 返回主控

完成离线门后立即返回，内容包括：

- pipeline 插入点和调用顺序；
- 是否改动 `line_split.py` 及其必要证据；
- 合成 fixture 中单行、块状、Editorial 三类结果；
- record/page-policy 语义如何让后续 title pass 跳过 TOC；
- 测试命令与 exit code；
- `git diff --stat` 和 `git diff --check`；
- 主控 p1 paid 检查所需 report 字段和裁剪区域。

保留未提交工作树，由主控完成 Git、paid 和视觉验收。
