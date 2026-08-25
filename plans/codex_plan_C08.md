# Codex Plan C08 — 将文章重排扩展到相邻页面

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：feat(article-flow): extend bounded reflow across adjacent pages  
建议模型：GPT-5.6 Sol  
建议推理强度：xhigh  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C08 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “feat(article-flow): extend bounded reflow across adjacent pages” 创建一个 commit。
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

本批依赖：C01–C07 必须已提交；页内 article flow 已通过短测。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认跨页 segment 的起止边界完全来自 canonical ArticleIR。禁止仅因版式相似或页面相邻就跨页移动正文。

## 4. 当前代码事实与缺口

- 现有 column_reflow 没有跨页容器。
- ArticleIR 可提供 article pages 和 ordered slots。
- C07 只允许同页跨栏。
- methodology 允许同一 article 在相邻页面间重排，同时要求 page count、页面尺寸和固定资产保持不变。
- 页间 hard boundary、unsupported page 和大面积受保护设计区域需要终止 flow。

## 5. 本批唯一目标

让同一 canonical article 的目标正文在明确允许的相邻页面 slots 间继续流动，使用有界事务保持整段跨页一致性。

## 6. 非目标

- 不跨越 article boundary。
- 不跨越 unsupported same-page multi-article 页面。
- 不新增、删除或重排页面。
- 不移动固定视觉资产或页面家具。
- 不处理非相邻页面跳转。

## 7. 必须实现的行为

1. 定义 CrossPageArticleFlowSegment，包含：
   - article ID；
   - contiguous pages；
   - ordered page/column slots；
   - hard boundaries；
   - touched sources/fragments/assets。
2. 跨页连接条件全部满足才可连接：
   - page adjacency；
   - 相同 deterministic article ID；
   - ArticleIR reading order 连续；
   - 无 hard boundary/unsupported state；
   - source geometry 和 fixed asset inventory 可用。
3. 复用 C06/C07 的 measure/fit 和 boundary token。
4. 长译文从当前页末进入下一页首个合法 slot；短译文可让后续 slot released。
5. 保持 page count、mediabox、cropbox、rotation、page labels 和固定家具。
6. 事务快照覆盖整个 cross-page segment。任一页检测失败时恢复所有 touched pages 和 trace generation。
7. 对 capacity exhaustion、hard boundary 和 page ownership conflict 产生 typed issue。
8. 在 report/trace 中记录跨页移动前后 page/slot。

## 8. 数据契约和不变量

- target fragment 只能在同一 article 的连续页面内移动。
- page sequence、page count 和 page geometry 完全不变。
- target ranges 全覆盖且顺序单调。
- fixed asset inventory 每页保持不变。
- 跨页 rollback 是全 segment 原子操作。
- hard boundary 后的 slot 从未进入候选集合。
- unsupported page 既不接收，也不输出 article flow 文本。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- article_flow/cross_page_reflow 模块
- babeldoc/high_level.py 的 article flow 调用
- ArticleIR boundary policy
- RunTrace/transaction
- page geometry conservation
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 写明确的 page connection predicate 和负例测试。
2. 构建只读 cross-page allocation plan。
3. 将同页 allocator 扩展为 page-aware slot iterator。
4. 增加全 segment snapshot 和 restore。
5. 一次性写回所有 touched pages。
6. 运行 per-page detectors 和 segment invariants。
7. 更新 trace/report，覆盖 page movement。
8. 测试第三页新文章、XObject、hard boundary 和 overflow。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_article_cross_page.py

必须覆盖：

- 两页同一文章的长目标跨页。
- 前两页同文、第三页新文，目标不进入第三页。
- 中间页含 XObject，slot 绕开资产。
- hard boundary 阻断 flow。
- unsupported page 阻断输入和输出。
- 第二页检测失败时两页共同回滚。
- page count、mediabox/cropbox、rotation 和 labels 不变。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_article_cross_page.py
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

- [ ] 仅 canonical same-article adjacent pages 被连接。
- [ ] 跨页目标 ranges 顺序和守恒正确。
- [ ] page count 和所有 page geometry 不变。
- [ ] fixed assets 与页面家具不漂移。
- [ ] hard boundary/unsupported page 生效。
- [ ] 任一页失败时全 segment 回滚。
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
git commit -m "feat(article-flow): extend bounded reflow across adjacent pages"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C08
Status: committed | blocked | not started
Commit: <hash> feat(article-flow): extend bounded reflow across adjacent pages
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

