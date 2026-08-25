# Codex Plan C07 — 实现文章区域内跨栏重排

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：feat(article-flow): reflow text across columns within an article  
建议模型：GPT-5.6 Sol  
建议推理强度：high  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C07 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “feat(article-flow): reflow text across columns within an article” 创建一个 commit。
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

本批依赖：C01–C06 必须已提交；ArticleIR slots、asset guard、RunTrace 和目标容量测量可用。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 ArticleIR role policy 可以区分 body/continuation 与 title、caption、formula、footer。若 role 未知，默认保护该元素，不扩大本批推断范围。

## 4. 当前代码事实与缺口

- column_reflow.py 当前只在单页列内做段落框纵向移动。
- 它没有以 article 为容器，也没有让普通正文共享目标文本流。
- C06 只解决 confirmed continuity chain 的 slot backfill。
- methodology 要求文章区域内的正文可以跨源栏界重新分配，同时保留固定视觉资产和角色边界。

## 5. 本批唯一目标

让同一 article、同一页面中的普通正文和 continuity chain 共享有序 region slots，按目标排版容量跨栏流动。

## 6. 非目标

- 不跨页面；该范围属于 C08。
- 不让 title、caption、formula、footer 进入 body flow。
- 不重新定位固定图像和设计资产。
- 不推断同页多个 article。
- 不改变翻译文本。

## 7. 必须实现的行为

1. 定义 page-local ArticleFlowSegment：
   - article ID、page、ordered slots；
   - eligible body sources/fragments；
   - hard boundaries 和 protected elements。
2. role policy 只允许 body/continuation 参与正文流；未知角色默认 protected。
3. 将 C06 的 measure/fit 复用于普通 paragraph stream，禁止复制另一套字符估算算法。
4. 用显式 paragraph-boundary token 保留：
   - source paragraph identity；
   - paragraph order；
   - indentation/spacing policy；
   - target fragment trace。
5. 固定资产从 region 中切出合法 slots；文本不得越过 obstacle 或 page/article envelope。
6. short target 可压缩并释放栏尾空白；long target 可进入同页下一栏。
7. 写回作为 page/article 原子事务；任何 overlap、bounds、ownership 或 conservation 失败都恢复完整 segment。
8. RunTrace 更新 fragment→slot→geometry，对 released slots 和 protected elements 记录状态。

## 8. 数据契约和不变量

- reading order 由 ArticleIR 决定，不能从 PDF 对象遍历顺序临时推断。
- 段落边界和源身份保持可追踪。
- 每个 target fragment 恰好渲染一次。
- title/caption/formula/footer 与 unknown role 不进入 body flow。
- 文本只使用同一 article、同一 page 的合法 slots。
- fixed asset inventory 和 untouched element digest 不变。
- 失败时整个 page/article segment 回滚。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/column_reflow.py 或新的 article_flow 模块
- ArticleIR slot/role policy
- 共享 typesetter measure/fit
- RunTrace
- reflow configs
- detectors/transaction hooks
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 将现有 column reflow 行为拆成可复用的 slot/transaction 层，保持旧默认。
2. 定义 eligible role 与 hard boundary。
3. 构建 page-local stream 和 boundary tokens。
4. 复用 C06 capacity allocator 分配同页 slots。
5. 一次性写回并更新 trace。
6. 接入 asset guard 和最小 pre-commit detectors。
7. 添加短译文收缩、长译文跨栏和角色保护测试。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_article_cross_column.py

必须覆盖：

- 双栏正文从第一栏溢流到第二栏。
- 短译文释放第一栏/第二栏空间且 reading order 正确。
- 栏间 PdfXobject/figure 受保护。
- title、caption、formula、footer 和 unknown role 不参与。
- paragraph identity 和 target ranges 可由 trace 反查。
- detector 失败时完整 segment 回滚。
- unsupported multi-article page 不运行。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_article_cross_column.py
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

- [ ] 普通正文可在同 article、同页 slots 内跨栏。
- [ ] 连续链与普通正文共享统一容量接口。
- [ ] 角色边界得到保护。
- [ ] 资产、页面和未触及内容守恒。
- [ ] trace 覆盖所有分配片段。
- [ ] 失败事务完整回滚。
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
git commit -m "feat(article-flow): reflow text across columns within an article"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C07
Status: committed | blocked | not started
Commit: <hash> feat(article-flow): reflow text across columns within an article
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

