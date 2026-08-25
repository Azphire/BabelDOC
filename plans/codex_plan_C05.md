# Codex Plan C05 — 强制连续链严格单次联合翻译

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：fix(chain): enforce one joint translation request  
建议模型：GPT-5.6 Sol  
建议推理强度：high  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C05 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “fix(chain): enforce one joint translation request” 创建一个 commit。
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

本批依赖：C01–C03 必须已提交；C04 建议已提交，以便后续回填使用统一守卫。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 il_translator_llm_only.py 的 chain claim 仍阻止 cross-page、cross-column 和 page-batch 旧路径处理已认领成员。确认 translator engine 可以由 spy/stub 统计调用。

## 4. 当前代码事实与缺口

- chain_translation.py 已实现 prepare、merge、联合 llm_translate、redistribute 和 claim。
- il_translator_llm_only.py 已在多个旧翻译分支检查 claim。
- _aligned_lengths() 在相关开关启用时会逐成员调用 engine.translate()。
- 当前 confirmed chain 发生失败时可能进入不够清晰的 fallback。
- chain request 使用首个成员的 article brief，缺少所有成员同属 canonical article 的强校验。

## 5. 本批唯一目标

确保一个 confirmed continuity chain 在语义层最多产生一个翻译请求，并为失败链提供显式、可审计的保护状态。

## 6. 非目标

- 不实现真实排版容量回填；该工作属于 C06。
- 不改变普通非 chain 段落的翻译行为。
- 不使用第二个 LLM 请求做对齐、切分、评分或重写。
- 不修改 legacy il_translator.py。

## 7. 必须实现的行为

1. 删除或替换 _aligned_lengths() 中的逐成员 engine.translate()。
2. 对齐/断点提示只能来自：
   - 已得到的 whole target；
   - 确定性语言边界；
   - 无模型的权重；
   - 后续 typesetter measurement。
3. 联合请求前验证：
   - ordered members 非空、无重复；
   - 所有成员属于同一 canonical article；
   - reading order 连续且 chain 无分叉；
   - placeholder 集合和顺序可保护。
4. confirmed chain 的结果状态限定为：
   - joint_success；
   - protected_untranslated；
   - failed_with_issue。
5. 不允许 confirmed chain 静默回落到逐成员翻译。
6. RunTrace 记录 request ID、ordered refs、translator call count 和结果状态。
7. claim 的建立与释放必须事务化；失败状态不能让旧路径再次翻译同一成员。

## 8. 数据契约和不变量

- N 个成员的 successful chain，translator call count 恒为 1。
- 预检查失败可以为 0 次调用；请求已发出后的失败为 1 次。
- 任何 confirmed chain 都不会产生 member translation request。
- placeholder 在 whole source、request、whole target 中可追踪。
- 所有成员使用同一个 canonical article context。
- protected/failed 状态不会伪装成 rendered。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/chain_translation.py
- babeldoc/document_il/midend/il_translator_llm_only.py
- RunTrace request hooks
- chain translation config
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 用 spy engine 还原当前调用图和多调用测试。
2. 删除成员翻译对齐路径，保留纯确定性接口。
3. 加入 canonical article 和 chain topology validator。
4. 定义 chain outcome enum/typed result。
5. 修正 claim 生命周期和旧路径守卫。
6. 接入 RunTrace call count。
7. 覆盖 success、preflight fail、placeholder fail 和 engine exception。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_chain_single_request.py

必须覆盖：

- 2、3、5 成员 successful chain 均只调用一次。
- alignment 开关开启时仍只调用一次。
- article 不一致时调用数为 0，并产生 issue。
- placeholder preflight 失败时为 0；响应占位符损坏时最多为 1。
- engine exception 后成员不进入旧路径。
- 普通非 chain 段落的调用行为不受影响。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_chain_single_request.py
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

- [ ] confirmed chain 的语义请求数满足 0 或 1 契约。
- [ ] _aligned_lengths 不再调用翻译引擎。
- [ ] article、顺序、拓扑、placeholder 均在请求前校验。
- [ ] 失败链状态显式且 trace 完整。
- [ ] claim 防止旧路径重复翻译。
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
git commit -m "fix(chain): enforce one joint translation request"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C05
Status: committed | blocked | not started
Commit: <hash> fix(chain): enforce one joint translation request
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

