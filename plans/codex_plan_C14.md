# Codex Plan C14 — 防止 repair 或失败路径破坏首字装置

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：fix(drop-cap): guard render and repair interactions  
建议模型：GPT-5.6 Sol  
建议推理强度：high  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C14 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “fix(drop-cap): guard render and repair interactions” 创建一个 commit。
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

本批依赖：C01–C13 必须已提交；中英文首字 intent、geometry、detectors 和 transaction 均可用。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 repair action registry 中所有可能重建 paragraph composition 或修改 box 的动作。使用 source ref/intent 关系识别受保护段落，不能依赖 debug_id。

## 4. 当前代码事实与缺口

- 已知 react repair 可能重新 typeset drop-cap 段落并覆盖首字 composition。
- 当前 offline gate 能发现部分交叠，主运行时缺少统一保护。
- flatten 失败、stale decision 或非候选 keep 可能进入 render。
- C11–C13 将建立 intent 和几何契约，本批负责封闭其他 action 破坏这些结果的路径。
- repair controller 采用封闭 action 类型和有界轮数。

## 5. 本批唯一目标

确保只有有效 intent 能进入 render，并阻止 repair/reflow 在未重新验证的情况下破坏已完成的首字装置。

## 6. 非目标

- 不调整英文或中文几何参数。
- 不新增新的 repair 类型。
- 不让 repair 自动重新翻译。
- 不扩大人工 decision 权限。
- 不运行整本 PDF 回归。

## 7. 必须实现的行为

1. 建立 active drop-cap protected refs 索引，来源为 canonical source ref 和 current intent generation。
2. 对所有可能修改 paragraph composition/box 的 repair actions 做 preflight：
   - action touched refs 与 active intents 相交时默认拒绝；
   - 返回 protected_drop_cap_conflict issue；
   - 不执行半程修改。
3. 只有在现有架构已提供小范围、同事务 re-render API 且能完整验证时，才允许“正文 repair 后重新 render drop-cap”；不要为本批扩大设计。
4. render 入口强制验证：
   - candidate_valid；
   - decision_current；
   - flatten_success；
   - target initial available；
   - geometry policy known；
   - current transaction generation。
5. render 后立即运行 drop_cap_geometry、color、coverage 和 collision checks；失败则回滚该段落到普通正文。
6. 其他 article reflow 若移动含 drop-cap 的 slot，必须保留 decorative anchor 关系或拒绝事务。
7. report/trace 区分 protected skip、invalid intent、render rollback 和 committed。
8. 清理任何仅依赖 debug_id 的 drop-cap gate。

## 8. 数据契约和不变量

- 无有效 intent 的段落不会产生 enlarged glyph。
- active drop-cap paragraph 不会被通用 repair 静默重建。
- 被拒 action 不修改 IL/trace。
- render validation 与 transaction generation 一致。
- render 后几何、颜色或 coverage 失败会恢复普通正文。
- 正文字符仍恰好出现一次。
- decision 不能绕过 candidate/flatten checks。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/repair/controller.py
- repair action implementations/registry
- babeldoc/document_il/midend/drop_cap.py
- babeldoc/document_il/midend/drop_cap_render.py
- RunTrace/transaction
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 盘点所有能触及 paragraph composition/box 的 repair actions。
2. 写 protected-ref index 和 preflight 冲突测试。
3. 在 render 入口集中验证 intent。
4. 把 post-render detectors 接入同一事务。
5. 确保 article reflow 对 decorative anchor 有明确策略。
6. 补齐 report/trace 状态。
7. 覆盖 exception、stale keep、noncandidate 和 repair collision。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_drop_cap_repair_guard.py

必须覆盖：

- 通用 retypeset/overlap repair 试图修改 active drop-cap 段落时被拒。
- 被拒 action 前后 IL/trace digest 一致。
- flatten exception、stale keep、noncandidate keep 不 render。
- render 后颜色丢失或 geometry 不合规时回滚普通正文。
- unrelated paragraph repair 正常执行。
- article reflow 移动 drop-cap slot 时 anchor 保持或事务拒绝。
- report 状态准确。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_drop_cap_repair_guard.py
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

- [ ] repair action 全部经过 active intent preflight。
- [ ] 通用 repair 无法静默抹除首字 composition。
- [ ] render 只接受完整有效 intent。
- [ ] post-render detector 失败触发回滚。
- [ ] 非 drop-cap repair 行为保持兼容。
- [ ] 报告和 trace 区分所有失败/保护状态。
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
git commit -m "fix(drop-cap): guard render and repair interactions"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C14
Status: committed | blocked | not started
Commit: <hash> fix(drop-cap): guard render and repair interactions
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

