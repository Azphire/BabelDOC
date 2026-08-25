# Codex Plan C09 — 修复验收单调性并实现原子回滚

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：fix(repair): require monotonic improvement and atomic rollback  
建议模型：GPT-5.6 Sol  
建议推理强度：xhigh  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C09 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “fix(repair): require monotonic improvement and atomic rollback” 创建一个 commit。
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

本批依赖：C01–C08 必须已提交；RunTrace、asset inventory、页内和跨页事务都可用。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认现有 Issue.id 的构成和每个 detector 可提供的量化证据。若某类 issue 暂无合理 severity metric，应采用明确的不可恶化布尔/等级规则，禁止只比较 ID。

## 4. 当前代码事实与缺口

- column_reflow.py 目前主要比较 after issue IDs 与 before issue IDs。
- Issue.id 由 detector/page/refs 等稳定材料构成；同一 overlap 或 overflow 的严重度恶化时 ID 可能不变。
- repair controller 已有最多三轮和 action limit。
- conservation 主要覆盖页数、段落数和段落 XML digest。
- repair exception 路径会恢复对象，但报告不总能完整表达失败、rollback 和恢复摘要。
- methodology 要求 defect count 下降，存留同类指标改进且无指标恶化。

## 5. 本批唯一目标

建立统一的单调改善判定和可验证的 touched-set 原子事务，使 reflow/repair 失败、异常或指标恶化时完整恢复。

## 6. 非目标

- 不新增具体 detector 类型；该范围属于 C10。
- 不增加 repair 轮数或扩大许可动作。
- 不让 LLM 决定是否接受几何修改。
- 不实现最终 PDF reopen QA。

## 7. 必须实现的行为

1. 为 Issue 增加或派生 versioned severity vector，示例：
   - overlap area/ratio；
   - overflow distance/area；
   - collision area；
   - unrendered chars；
   - abnormal blank area；
   - fragment count；
   - fixed asset drift count/distance。
2. 定义统一 acceptance comparator：
   - 比较 before/after 总数和按类型数量；
   - 同 ID 存留 issue 的 severity 不得恶化；
   - 新高严重度 issue 直接拒绝；
   - 只有满足配置化 lexicographic/typed policy 时接受。
3. 定义 TransactionSnapshot，覆盖：
   - touched paragraphs/compositions/boxes；
   - relevant page geometry；
   - drop-cap intent；
   - RunTrace generation；
   - fixed asset digest；
   - allocator state。
4. 所有 reflow/repair action 经 begin→mutate→detect→compare→commit/rollback。
5. rollback 后重新计算 digest，验证恢复成功。
6. exception、cache/transport no-op、detector failure 均写完整 report，区分 attempted、not_executed、rolled_back、committed。
7. 保留现有 action/round limits。

## 8. 数据契约和不变量

- acceptance 不依赖 issue ID 集合差值这一单一信号。
- 同一 issue 的任何关键 severity 维度恶化都会拒绝。
- 新 critical issue 会拒绝，即使旧问题数量减少。
- rollback 后 touched XML/geometry/trace/asset digest 与事务前一致。
- exception 不能留下部分 action。
- 未执行动作不计为成功修复。
- comparator 是确定性纯函数。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/detectors/base.py
- babeldoc/document_il/midend/column_reflow.py
- babeldoc/document_il/midend/repair/controller.py
- transaction/snapshot 模块
- RunTrace rollback hook
- repair report schema/sidecar
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 列出当前 issue types 和已有 metrics。
2. 定义 severity schema 与 comparator 纯函数。
3. 先添加“同 ID 指标恶化”失败测试。
4. 实现 transaction snapshot 和 digest。
5. 将 column reflow 接入统一事务。
6. 将 repair actions 接入统一事务。
7. 补齐 exception/no-op 报告。
8. 验证 commit 和 rollback 后的 trace generation。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_repair_transaction.py

必须覆盖：

- 同一 issue ID 的 overlap area 增大，必须回滚。
- 一个旧 issue 消失，同时新增越界 critical issue，必须回滚。
- 指标实际改善且无新增问题，可以 commit。
- action 中途抛异常，所有 touched pages 恢复。
- 多页第二页失败，两页共同恢复。
- cache/transport failure 标为 not_executed。
- rollback 后 XML、geometry、trace 和 asset digests 相同。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_repair_transaction.py
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

- [ ] severity-aware comparator 取代纯 ID 集合验收。
- [ ] 所有文章 flow/repair 使用统一事务边界。
- [ ] exception 和 multi-page failure 完整恢复。
- [ ] 报告准确区分各 action 状态。
- [ ] round/action limits 保持不变。
- [ ] rollback 恢复通过摘要验证。
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
git commit -m "fix(repair): require monotonic improvement and atomic rollback"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C09
Status: committed | blocked | not started
Commit: <hash> fix(repair): require monotonic improvement and atomic rollback
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

