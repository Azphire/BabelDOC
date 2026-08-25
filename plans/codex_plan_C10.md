# Codex Plan C10 — 增加 trace 驱动的重排合规检测

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：feat(detectors): add trace-backed reflow compliance findings  
建议模型：GPT-5.6 Sol  
建议推理强度：high  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C10 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “feat(detectors): add trace-backed reflow compliance findings” 创建一个 commit。
4. 停止继续开发，提交结果报告，等待下一批指令。

## 1. 项目目标与全局工程约束

BabelDOC 本轮工作的目标是建立可追踪、可回滚的杂志文章翻译与排版路径：

- page 是渲染和验收单位。
- article 是上下文、阅读顺序和允许重排区域的单位。
- continuity chain 是联合翻译单位。
- 连续链采用“合并源文本、一次联合翻译、按目标排版容量重新分栏和跨页回填”的路径。
- 源元素、ArticleIR、翻译请求、目标片段和最终几何必须在一次运行中可双向追踪。
- 页面数量、页面尺寸、固定视觉资产和未触及内容必须保持守恒。
- 重排和修复只接受缺陷总量下降、存留同类缺陷指标不恶化的结果；失败时恢复完整 touched set。
- LLM 只承担翻译或现有明确许可的文本任务。文章归并、阅读顺序、几何分配、检测、验收和回滚保持确定性。
- 当前项目处理 born-digital、具有可搜索文本层的 PDF。

明确范围：

- 不实现同页多文章身份隔离。
- 一页最多映射到一个参与文章流的 article。
- 发现疑似同页多文章时，记录 unsupported 状态并禁止该页文章重排。
- 不新增页面，不重建 OCR 文本层，不加入刊物名、文档名或页码特例。
- 不在本批运行全 corpus、整本杂志、正式 MQM/LTCR/LOPO、在线翻译或长时间视觉回归。

## 2. 仓库规则

执行前完整阅读当前仓库的 CLAUDE.md。以下规则在本批始终有效：

- 主翻译实现沿用 il_translator_llm_only.py 的唯一路径。
- 如需改变 il_translator.py 的 legacy 行为，立即停止并报告理由；不要直接修改。
- IL XML schema 视为冻结。优先使用显式运行时对象和 JSON sidecar；只有本批明确授权时才可提议 schema 变更。
- 禁止使用 debug_id 作为门控键。诊断引用优先采用稳定的 pN#k/source ref；debug_id 仅可辅助日志。
- 所有新注释使用英文，数量保持最少，只解释必要不变量。
- 禁止添加修改说明、批次历史、修复记录类代码注释。
- 阈值、容差和策略值进入 configs；禁止散落 magic numbers。
- 禁止 publication-specific、document-specific、page-number-specific 分支。
- 保留用户已有修改和无关文件。不得使用 git reset --hard、git checkout -- 或其他破坏性清理命令。
- 一个工作树只允许一个写入者。若使用 reviewer，只允许只读检查，不得同时编辑或提交。

## 3. 起始状态和前置检查

本批依赖：C01–C09 必须已提交；RunTrace、ArticleIR、fixed asset inventory 和 severity-aware transaction 可用。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 detector 层保持只读。任何“自动修复建议”只能返回封闭 action type 和证据，不能在 detector 内直接修改 IL。

## 4. 当前代码事实与缺口

- 当前 detector 集合已覆盖 residue、fragment、text-artwork overlap、bounds、collision 和部分 chain escalation。
- 没有独立的 article ownership、完整 chain target conservation、render coverage 和 fixed asset drift detector。
- abnormal blank 主要依附特定 reflow 路径，缺少通用且能排除设计留白的检测。
- instruction compliance 和最终 geometry 的证据没有利用统一 RunTrace。
- source geometry 缺失可能导致检测跳过，C04 已计划把它变成显式状态。

## 5. 本批唯一目标

补齐 article reflow、continuity chain 和 drop-cap 后续验收所需的只读、类型化、trace-backed detectors。

## 6. 非目标

- 不实现 repair action。
- 不调整翻译文本。
- 不实现 drop-cap 几何；本批只定义可供后续使用的通用 detector contract。
- 不做 PDF 写出后检查；该范围属于 C15。

## 7. 必须实现的行为

1. 新增或加强 detector：
   - article_ownership：fragment/geometry 必须属于同一 article 和允许页面；
   - chain_conservation：whole target 与 ordered fragments 完整一致；
   - render_coverage：每个 source/fragment 有合法终态和必要 geometry；
   - abnormal_blank：检测 article region 中由流分配造成的大空白，排除 fixed assets、hard boundary 和设计留白；
   - fixed_asset_drift：count、bbox、digest 漂移；
   - instruction_compliance：joint call count、protected state、rollback state；
   - drop_cap_geometry contract：字符数、policy、ink/reserve/collision/color 字段接口，供 C11–C14 填充。
2. 每个 issue 包含 detector kind、page/article/source/fragment refs、几何证据、severity vector 和建议的封闭 action type。
3. detector 只读取 ArticleIR、RunTrace、IL 和 inventory。
4. 缺少必需输入时产生 detector_prerequisite_missing，不能返回空问题集合。
5. abnormal blank 的阈值进入 configs，并以 article slot capacity/area 归一化。
6. 同一输入输出稳定排序和稳定 issue ID。

## 8. 数据契约和不变量

- detector 完全只读，运行前后 IL/trace digest 不变。
- issue 必须携带足够证据用于 C09 comparator。
- source、fragment、article 引用使用稳定 refs。
- 缺少几何或 trace 时显式失败。
- 设计留白和固定资产占据区域不计 abnormal blank。
- chain conservation 使用 target ranges/hash，不依赖肉眼文本搜索。
- issue ordering 和 IDs 确定性。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/detectors/
- detectors/base.py
- shared configs
- ArticleIR/RunTrace read APIs
- high_level detect aggregation
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 定义 detector input contract 和 prerequisite behavior。
2. 为每个新 detector 先构造一正一负夹具。
3. 实现 ownership、chain conservation、render coverage。
4. 实现 normalized abnormal blank 和 asset drift。
5. 实现 instruction/drop-cap contract。
6. 接入统一 aggregation 和 severity vectors。
7. 运行只读 digest 测试与稳定性测试。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_reflow_compliance.py

必须覆盖：

- article fragment 落入错误 article/page。
- chain fragment 缺失、重复、乱序和完整通过。
- source/fragment 缺少 final state。
- 真异常空白与图像/设计留白的区分。
- fixed asset bbox/digest 漂移。
- joint call count 不合规。
- prerequisite missing 产生 issue。
- detector 前后 IL/trace digest 不变，重复运行 ID 稳定。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_reflow_compliance.py
git diff --check
~~~

如果项目当前使用 pytest 管理相同测试，可换成最窄的 pytest 命令。任何命令运行到 60 秒仍未完成时立即终止，记录已运行时长和停留位置。缺少依赖时报告确切模块，不安装与本批无关的新工具，也不把环境缺包记为功能失败。

禁止运行：

- run_all 或 corpus sweep
- 整本杂志翻译
- 在线 LLM/VLM 请求
- 无限定页面渲染
- 预计超过 60 秒的测试集合

## 12. 验收清单

- [ ] ownership、conservation、coverage、blank、asset drift 和 instruction detectors 可用。
- [ ] 每个 issue 含 stable refs、evidence、severity。
- [ ] prerequisite 缺失不会静默跳过。
- [ ] detector 保持只读。
- [ ] abnormal blank 排除固定资产和 hard boundary。
- [ ] 输出顺序和 ID 稳定。
- [ ] compileall、目标 spec check、diff check 全部通过。

全部满足后才能提交。任一核心项无法验证时保留工作树、停止提交并报告阻塞。

## 13. 提交规约

提交前执行：

~~~bash
git status --short
git diff --stat
git diff
git diff --check
~~~

确认 staged files 只属于本批，然后创建一个 commit：

~~~bash
git commit -m "feat(detectors): add trace-backed reflow compliance findings"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C10
Status: committed | blocked | not started
Commit: <hash> feat(detectors): add trace-backed reflow compliance findings
Base HEAD: <hash>
Final HEAD: <hash>

Implemented:
- ...

Files changed:
- ...

Tests:
- <exact command> — <duration> — PASS/FAIL/SKIPPED

Acceptance:
- <criterion> — PASS/FAIL/UNVERIFIED

Skipped:
- <check and reason>

Risks or premise changes:
- ...

Next batch:
- Stop here. Do not start it.
~~~

