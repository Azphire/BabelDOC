# Codex Plan C02 — 构建唯一、确定性的跨页 ArticleFlowIR

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：feat(article-ir): build one canonical cross-page article state  
建议模型：GPT-5.6 Sol  
建议推理强度：xhigh  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。
开发分支：codex/c01

## 0. 本文件的使用方式

本文件是 C02 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “feat(article-ir): build one canonical cross-page article state” 创建一个 commit。
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

本批依赖：C01 必须已提交；当前分支历史应包含 “feat(runtime): expose and validate magazine feature profile”。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 C01 的公开 profile 能显式控制 article grouping/context。确认当前 IL schema 仍处于冻结状态。

## 4. 当前代码事实与缺口

- high_level.py 在 ChainBuilder 后调用 ArticleBuilder。
- article_builder.py 依据页面策略和连续链合并页面，但当前 article ID 使用随机生成。
- article_builder.py 的主要产物是 article_map.json，文档说明它不影响下游。
- article_context.py 又独立重建文章分组和上下文。
- Article 结构只记录有限 pages/id 信息，没有完整 element role、source geometry 和 region slots。
- 本项目已经决定不实现同页多文章身份隔离。

## 5. 本批唯一目标

一次运行只构建一个 canonical ArticleDocumentIR，提供确定性的跨页文章身份、元素顺序和可重排区域槽位，所有后续组件复用同一实例。

## 6. 非目标

- 不处理同页多个文章身份。
- 不改变翻译请求或目标回填。
- 不修改 XML IL schema。
- 不推断复杂语义文章边界或引入新的 LLM 分类。

## 7. 必须实现的行为

1. 新增明确的运行时数据结构：
   - SourceElementRef：stable source ref、page、column、reading order、role、source box、source text hash、style hash。
   - ArticleRegionSlot：article ID、page、column、slot order、box、fixed obstacle refs、capacity hint。
   - ArticleIR：deterministic ID、pages、elements、slots、chain IDs、policy evidence。
   - ArticleDocumentIR：articles 以及 by_page、by_element、by_chain 索引和 unsupported pages。
2. ArticleBuilder 成为唯一构建器，并返回 ArticleDocumentIR。
3. ArticleContext 改为消费该对象，删除或封闭独立重建身份的路径。
4. article ID 由规范化页序列、首个稳定 source ref、chain signature 等确定性材料计算。
5. by_page 的值只能为零个或一个 article ID。检测到同页多文章证据时：
   - 写 unsupported_same_page_multi_article；
   - 不进行身份拆分；
   - 将该页标记为禁止 article reflow。
6. 在 high_level.py 中显式保存和传递对象；禁止通过随机全局状态或重新读取 sidecar 作为运行时来源。
7. 写 article_ir.json 供审计，内容顺序稳定。

## 8. 数据契约和不变量

- 同一输入、配置和代码版本重复运行产生相同 article ID 和 JSON 顺序。
- 每个可参与文章流的 source ref 恰好属于一个 article。
- continuity chain 的所有成员必须能映射到同一个 article；冲突写结构化 issue。
- page index、column order、reading order 单调且无重复。
- unsupported 页面不进入 reflow slots。
- 运行时对象是权威来源；sidecar 只用于审计。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/article_builder.py
- babeldoc/document_il/midend/article_context.py
- babeldoc/high_level.py
- 新的 article_ir 数据结构模块
- 相关 sidecar writer
- 文章分组 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 画出现有 ArticleBuilder、ArticleContext、ChainBuilder 的调用和数据流。
2. 定义最小 immutable/dataclass API 与稳定序列化。
3. 将现有构建逻辑集中到唯一 builder，替换随机 ID。
4. 在 high_level 中显式传递对象。
5. 改造 ArticleContext 消费 canonical state。
6. 加入 same-page multi-article unsupported guard。
7. 对 sidecar 做稳定排序和重复运行比较。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_article_flow_ir.py

必须覆盖：

- 两页同文通过 chain 合并为一个 article。
- 相邻页无连续证据时遵循现有页面策略。
- 三页中前两页同文、第三页新文。
- 疑似同页双文被标为 unsupported，且无 reflow slots。
- 相同夹具运行两次，article IDs 和 JSON bytes 一致。
- chain 成员跨两个 article 时产生 issue。
- ArticleContext 不再生成第二套身份。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_article_flow_ir.py
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

- [ ] 运行中只有一个 ArticleDocumentIR。
- [ ] article ID 完全确定性。
- [ ] 下游 ArticleContext 使用同一 ID 和元素集合。
- [ ] 同页多文章按 unsupported 处理。
- [ ] 不修改 IL XML schema。
- [ ] sidecar 稳定且可由 source ref 反查 article。
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
git commit -m "feat(article-ir): build one canonical cross-page article state"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C02
Status: committed | blocked | not started
Commit: <hash> feat(article-ir): build one canonical cross-page article state
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

