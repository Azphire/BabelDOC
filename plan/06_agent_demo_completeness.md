# Agent 执行计划 06：Courier 内容守恒与最终 demo 门

目标分支：`migration/minimal-v0.6.4`  
起始基线：主控在 `controller-state.json` 下发的上一 verified SHA；该 SHA 必须包含计划 01–05 的 verified 结果  
执行角色：controller state 记录的唯一、持续复用执行 agent  

## 独立执行契约

- 开始前确认 branch 为 `migration/minimal-v0.6.4` 且仅一个 worktree；按 controller state 的 `entry_mode` 验证：`initial` 要求 HEAD=previous verified 且 clean，`dirty_followup` 要求 HEAD=expected HEAD、`allowed_dirty_paths` 精确相等，并用 state 指定且 SHA-256 已验的 helper 复算 `tree-state-v1`（覆盖 tracked staged/unstaged/deleted 与全部 untracked 文件）的 `handoff_tree_state_digest`，`committed_followup` 要求 HEAD=rejected candidate 且 clean。任一不符立即停止。
- `agent_id` 必须等于 controller state；不得创建子 agent、branch 或 worktree。
- 重验 `examples/input/Courier-en.pdf` 的 SHA-256 `9fcb6b5e7d5a51972d766b98518554c64ef39080371ec98b4d04570402ea275a`。
- 旧 paid 负例只从 controller state 记录的 `.runtime/demo-repair/fixtures/paid.zip` 读取；先重验 SHA-256 `bfddf9258bbd65e996de2e041623faba8fafb5ad6c946d510e34d768a3e3660a`，并使用 state 中固定的只读解包目录、旧 output PDF 和旧 `work/Courier-en` 路径。路径或 hash 不符立即停止，禁止回退到 `upload/` 或递归猜文件。
- 只改 allowlist；不访问 C22，不接触 API key，不运行 paid。
- 不执行 `git add/commit/stash/reset/clean/rebase/amend/push`；主控验收时保持 idle。
- 所有命令使用 `uv run --no-sync`；失败后只处理当前阶段 follow-up，不进入下一计划。

## 1. 任务结果

补齐一个窄的 Courier demo 完整性 verifier 和最小汇总，使整本 paid run 不能再以“CLI exit 0 / PDF 存在 / report complete”通过。硬门直接覆盖用户指出的六类问题，并区分正文漏译与允许保留的摄影署名。

本阶段主要写验收代码和报告汇总。若离线 fixture 暴露此前阶段的功能回归，只提交证据给主控；主控会将失败包送回对应计划，避免在最终门中混做产品修复。

## 2. 必须先核对的现状

开始修改前实际阅读：

- `tools/verify_minimal_pdf.py`
- `babeldoc/magazine/minimal_pipeline.py` 的 final summary
- `babeldoc/magazine/run_trace.py`
- `babeldoc/magazine/minimal_detection.py`
- `babeldoc/magazine/detectors/chain_conservation.py`
- `translate_tracking.json`、`chain_translation.report.json`、`article_flow.report.json`
- `article_ir.json`、`article_map.json`、`article_context.report.json`、`page_classify.report.json`、`hitl_apply.report.json`
- `line_split.report.json`、`title_typeset.report.json`、`drop_cap_render.report.json`
- `issues.after.json`、`minimal_run.report.json`
- `tests/minimal/test_minimal_pdf_validator.py`

现有 validator 的缺口：

- selected page 只要出现任意汉字即可；
- chain 数为 0 或失败链被 typed 保护仍可能从其他字段绕过；
- drop cap `set=0` 可被 `typed_no_candidate` 接受；
- 不检查 TOC 行、中文标题单行或 p5 x-band；
- bbox 只检查有限/有序，不检查 cropbox；
- 不要求 translate-eligible source ref 有明确终态；
- `babeldoc/main.py` 遇到异步 error event 后可能仍以 0 退出。

## 3. 允许改动

延续计划 01 已创建的共用阶段 verifier，并在本阶段补齐 `full` 检查：

- `tools/verify_courier_demo.py`
- `tests/minimal/test_courier_demo_validator.py`

新增 coverage 汇总：

- `babeldoc/magazine/translation_coverage.py`
- `tests/minimal/test_translation_coverage.py`

为接入最小 coverage 快照，允许窄改：

- `babeldoc/magazine/minimal_pipeline.py`
- `babeldoc/magazine/run_trace.py`
- 若计划 01 的基础 schema 仍缺字段，可同步窄改 `tools/verify_minimal_pdf.py` 和 `tests/minimal/test_minimal_pdf_validator.py`

禁止改动翻译、chain、TOC、article flow、title、drop-cap 和通用 detector 行为。不得把 Courier 页码/坐标写进产品流水线；Courier-specific 条件只能存在于 `tools/verify_courier_demo.py` 和其测试 fixture。

## 4. verifier 输入与输出

命令至少接收：

```text
--source <Courier-en.pdf>
--output <translated.pdf>
--run-dir <work/Courier-en>
--render-dir <path>
[--gate-output <json>]
```

可选 `--pages` 仅用于阶段回放；最终默认检查全部 8 页。未传 `--gate-output` 时输出 `<run-dir>/courier_demo_gate.<check>.json`；传入时只写该精确 JSON，允许从只读 `run-dir` 回放到 fixture 外的可写目录。`0=pass`、`1=gate failure 且已写完整 JSON`、`2=参数/I/O/output fatal`。`--render-dir` 由 verifier 写入新生成的 PNG，不消费旧 PNG。

verifier 必须：

1. 明确打开 source/output PDF，验证页数、页面尺寸、可提取文本和 cropbox。
2. `--run-dir` 已明确时按精确文件名读取 sidecar，不递归猜候选；缺文件、多个候选、stale 路径均记录失败，但继续累计其他可判缺陷。
3. 校验 source SHA-256 等于计划固定值。
4. 逐项输出 `pass/fail/evidence`，不只给总布尔值。
5. 在失败时列出 source refs、页面、角色、文本摘要和 report path。

## 5. 硬检查

### 5.1 内容覆盖

现有 paid run 没有持久化 RunTrace，`translate_tracking.json` 也没有稳定 source ref/page，无法回建普通翻译 lineage。本阶段必须新增 `translation_coverage.report.json`，禁止由 executor 自行判断是否需要。

最小 sidecar 在 `before_translation()` 完成 HITL、line split 和 drop-cap source mutation 后快照全部当前 paragraph，包括 TOC 与未分配 ArticleIR 的对象。每项至少记录：

```text
physical_page / local_ref / debug_id
derived_from / source_alias（发生 split/首字 source mutation 时）
role / layout_label / page policy / article_owner
source text hash / script counts / source box
scheduler_eligible / coverage_required / exclusion or preserve reason
```

在 title/drop-cap/repair 后补 final target hash、script counts、final IL composition/box、producer ownership 和 represented-by 关系。`scheduler_eligible` 严格镜像真实 CID、长度、纯数字、placeholder 等调度过滤；`coverage_required` 表示 demo 内容政策，覆盖正文、标题、TOC record、图注、pull quote、sidebar 等。credit/furniture 可为 false，但必须有 preserve reason。intentional preserve 只能来自明确 role/policy。

每个 ref 的终态为：

```text
joint_translated
ordinary_translated
fallback_ordinary_translated
joint_trailing_released
intentional_preserve
untranslated
render_missing
```

至少要求：

- 所有 `coverage_required=true` 的 ref 不得是 `untranslated`、`render_missing` 或无状态。
- joint member 只能属于 joint target 或 typed ordinary fallback，不能只因 claim 被跳过。
- `joint_trailing_released` 只允许属于守恒 joint request、只出现在 trailing fragment、完整 target 已由前序 fragment 承载、holder 无源英文残留，并通过 `represented_by` 指回 active target owner。
- 每个 active target owner 唯一，防止同一 source 被重复渲染。
- `issues.after` 中 `coverage_required=true` 的对象不得有 `untranslated_residue`。
- 大于 80 个拉丁字符的源块若仍主要以源文出现在 target/最终 IL，直接失败；该阈值只做额外兜底，不替代 ref ledger。
- 摄影署名、credit、abandon/furniture 可保留英文，但必须有 `intentional_preserve` 和具体 reason；不能靠 detector 阈值静默忽略。
- chain target fragments 拼接等于完整 target，普通 translated ref 有非空 render target。

另用 PyMuPDF 的独立原生文本块提取路径读取 source PDF。在同一物理页内对空白、软连字符和行末断词做规范化，再以 many-to-many containment/concatenation 匹配；每个规范化后超过 80 个拉丁字符的 source block 必须映射到 coverage source inventory，或有明确 furniture/non-translate exemption。“整段从未进入 IL/ArticleIR”必须失败。该对照是大块遗漏兜底，不宣称精确 source-ref render lineage。

证据边界固定为：joint ownership 来自 chain report；fallback ownership 来自计划 01 typed fallback 与最终 target；普通翻译终态由 source/final hash、目标脚本和非空 final composition 推导，不声称精确 API batch lineage；`render_missing` 指最终 IL composition 缺失，PDF 原生提取只做页面/大块兜底。

coverage sidecar 和独立提取只服务本轮审计，不扩展成通用状态机。

### 5.2 结构与上下文

- `article_ir.json`、`article_map.json`、`article_context.report.json` 存在；只要求 `article_owner != null` 的 coverage 子集与其闭合。TOC/未分配 furniture 必须显式 `article_owner=null` 并带 page policy/exemption reason。
- 每条 chain 的 members 同属一个 article、chain order 稳定、source→target→render ownership 唯一。
- 普通批次和 joint request 记录实际消费的 article/context 标识或明确无上下文 reason；context 不跨 article 泄漏。unsupported page 可以禁止普通 reflow，但不能抹去 member ownership。

### 5.3 联合翻译

- 至少一条同页跨栏正文链 joint success。
- 至少一条跨页正文链 joint success。
- p2–p3 标题链 joint success。
- 每个 joint success 恰好一个 translator call，member claim exclusion 和 target conservation 成立。
- 其余 canonical chains 若 fallback，必须有 ordinary target 和原因。

### 5.4 TOC

- p1 page kind 为 HITL toc。
- `line_split.report.json` 有有效 conservation 和非零 split。
- 已知单行 record 的 source refs 相互独立；不得出现一个 tracking item 跨两个视觉行。
- block record 保持按块；右侧 Editorial 没有逐视觉行碎裂。
- title pass 完成后再次核对 record 数、视觉 band 和右侧 Editorial，捕获计划 02/04 的交叉回归。

### 5.5 布局与标题

- `article_flow.report.json` 为 typed disabled/no-op，0 placement。
- 物理 p5 正文 refs（全量旧别名：左 `p5#5`、中 `p5#3/#4`、右 `p5#1/#2`，排除通栏 `p5#7`）按 physical/local mapping 落在三条 source x-band 小容差内；禁止正文 bbox 横跨三栏总宽。
- 物理 p2 主中文标题只有一个 line band，p3 无残留英文标题；`single_line` 时 scale 不低于 `0.55`，`unchanged` 时要求 `lines_before=1`、target 完整且视觉可读。
- coverage ledger 中所有新/改文字 bbox 位于 cropbox 1pt 容差内；source 已存在且未漂移的 logo/furniture 越界作为 baseline condition，固定资产比较通过。

### 5.6 首字

- 按物理页/debug/source mapping 定位的三个旧全量 refs `p4#3,p5#5,p7#8` 均 `keep + committed`。
- totals 为 `decided=3,set=3,reverted=0`。
- 首字字号/正文大小比达到可见下限，前两行避让且第三行恢复左边缘。
- rendered initial 等于各段完整 target 的第一个合法目标字符，target index 正确；渲染字符序列与 paragraph target 完全相等，不按 Unicode 值误判自然重复字。
- `typed_no_candidate` 不能替代 set 计数。

### 5.7 HITL 与确定性修复证据

- review/decision 引用和 source hash 匹配；page kind、drop-cap、人工 glossary 都进入唯一有效约束路径。
- human glossary 的 decisions hash、实际条目数（当前基线为 14）及专名条目冻结并送达；样张中实际出现的词项在 target/最终 PDF 中符合指定译法。人工覆盖自动冲突用离线 fixture 验证。
- `issues.before/after`、typed action/no-op、参数范围、重检 pass index、接受/回滚原因完整；no-op 带 stop reason。
- 保留一个离线 accepted-repair fixture 和一个 rollback fixture，最终输出 residual issue 列表供主控人工验收。
- 这些 sidecar 只证明确定性 `minimal_repair`，不能作为 TeX 中 LLM planner 的实现证据。

## 6. 离线测试

用小型 JSON/PDF fixture 覆盖 pass 与每一种 fail：

1. CLI/report complete 但有一个 body ref untranslated：失败。
2. chain planning failure 已 ordinary fallback 且有 target：coverage 通过、joint 计数如实降低。
3. joint trailing holder 合法 release：通过；没有 `represented_by` 或仍有英文：失败。
4. 摄影署名带 intentional preserve：通过；无 reason：失败。
5. source PDF 有整段文字、coverage/IL inventory 完全缺失：失败。
6. 同一 source 有两个 active target owners：失败。
7. p5 只有一个宽 x-band：失败；三个窄 band：通过。
8. 一个 tracking paragraph/input item 含两个独立视觉 record、输出 item 数/顺序不守恒，或 title pass 后 record/band 改变：失败；同一 batch request 可包含多个独立 item。
9. 中文标题两行或低于 floor：失败。
10. dropcap set 0 且 typed rollback：失败。
11. bbox 越 cropbox、固定资产漂移、页数变化：失败；未漂移的 source baseline logo 不要求移动。
12. HITL glossary 未冻结/未送达/最终译法不符：失败。
13. repair/no-op 缺重检或 stop reason：失败。
14. 缺 sidecar、stale path、source hash 不符：累计失败，不首错退出。
15. 完整合格 fixture 生成 gate JSON 并 exit 0。
16. 只读 `run-dir` 配合 fixture 外 `--gate-output`：能聚合失败并 exit 1，且只读树 digest 不变；缺少可写 gate output 时 exit 2。

建议门：

```text
uv run --no-sync pytest -q tests/minimal/test_translation_coverage.py
uv run --no-sync pytest -q tests/minimal/test_courier_demo_validator.py
uv run --no-sync pytest -q tests/minimal/test_minimal_pdf_validator.py
uv run --no-sync pytest -q tests/minimal/test_one_repair.py tests/minimal/test_repair_rollback.py
uv run --no-sync pytest -q tests/minimal
uv run --no-sync ruff check babeldoc/magazine/translation_coverage.py babeldoc/magazine/minimal_pipeline.py tools/verify_courier_demo.py tests/minimal/test_translation_coverage.py tests/minimal/test_courier_demo_validator.py
git diff --check
```

用 controller state 固定的 `.runtime/demo-repair/fixtures/paid.zip` 及其只读解包目录作为负例；进入回放前再次校验 SHA-256 `bfddf9258bbd65e996de2e041623faba8fafb5ad6c946d510e34d768a3e3660a`，记录只读 fixture tree digest。创建新的可写 `.runtime/demo-repair/replay/<UTC>-paid-negative/` 后运行：

```text
uv run --no-sync python tools/verify_courier_demo.py --check full --source <repo>/examples/input/Courier-en.pdf --output <state.old_output_pdf> --run-dir <state.old_work_courier_dir> --render-dir <replay>/render --gate-output <replay>/courier_demo_gate.full.json
```

预期 exit 1 且 gate JSON 完整。旧 archive 缺新 sidecar且含 Windows 绝对路径；verifier 必须记录这些错误后继续聚合，并至少报告 6 个 chain failure、12 个正文/标题 residue、p5 单宽栏、3 个 dropcap rollback。回放前后只读 fixture tree digest 必须相同。该回放不调用 API，也不改写 fixture；exit 2 属于 verifier/路径错误，不能当作负例通过。

## 7. 主控最终 paid 验收规格

主控在本阶段 candidate 已提交并通过独立离线门、尚未标记 verified 时启动一次整本 8 页 paid run；翻译语义包含计划 01–02 的变更，因此使用新 run root 和 `--ignore-cache`。paid、完整 verifier 和视觉门通过后才标记 verified。运行后依次执行：

1. 原 `verify_minimal_pdf.py` 基础结构门。
2. 运行以下 `verify_courier_demo.py` 完整门，exit 0 才进入视觉检查：

   ```text
   uv run --no-sync python tools/verify_courier_demo.py --check full --source <source.pdf> --output <output.pdf> --run-dir <run>/work/Courier-en --render-dir <run>/render --gate-output <run>/gate/courier_demo_gate.full.json
   ```

3. 渲染全部 8 页缩略图。
4. 原分辨率打开 p1、p2–p3、p5、p6–p8 风险区。
5. 保存 `gate/courier_demo_gate.full.json`、所有 sidecar、PDF/PNG hash 和视觉 checklist。

完整门不通过时，本 agent 只修 verifier 自身的可证明误报。真实功能失败由主控发回对应阶段：

- chain/coverage → 计划 01；
- TOC → 计划 02；
- p5 grid → 计划 03；
- title/logo → 计划 04；
- drop cap → 计划 05。

以上均发回 controller state 中的同一个 agent，作为对应计划的 follow-up；不启动新 agent。若发现非 chain 普通调度漏译，主控另下发一个窄 follow-up，再回到本计划验收，verifier 本身不得修翻译。

## 8. 可接受降级与停止条件

可接受：

- verifier 为 Courier demo 专用，不提供 profile 框架或跨刊兼容；
- TOC leader dots 与字距不做像素级评分；
- 普通 article flow 关闭后出现空白；
- 有明确 reason 的摄影署名/品牌名保留原文；
- 复杂非 demo 标题和首字以 typed residual 留待后续。
- Courier verifier 只是 demo-specific gate，不构成 TeX 3.6 节的 LOPO、MQM、LTCR 或正式几何评价结果。

不可接受：

- 通过降低 residue/几何阈值掩盖已知 paid 缺陷；
- 只检查汉字存在或 PDF 存在；
- 在 product pipeline 中硬编码 Courier 页码/文本/坐标；
- verifier 自动修 PDF；
- 执行 agent 使用 API key或自行跑 paid。

## 9. 返回主控

完成离线门和旧 paid 负例回放后立即返回：

- verifier 的输入、输出和 exit 语义；
- coverage ledger 的终态来源；
- 每个负例断言的结果；
- 当前 paid.zip 被拒绝的完整原因摘要；
- 所有测试命令及 exit code；
- `git diff --stat`、`git diff --check`；
- 主控最终整本 gate 命令模板和视觉清单。

保留未提交工作树，由主控完成 Git、最终 paid 和验收。
