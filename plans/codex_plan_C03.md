# Codex Plan C03 — 建立源元素到最终几何的 RunTrace

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：feat(trace): connect source translation fragments and geometry  
建议模型：GPT-5.6 Sol  
建议推理强度：xhigh  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C03 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “feat(trace): connect source translation fragments and geometry” 创建一个 commit。
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

本批依赖：C01、C02 必须已提交；ArticleDocumentIR 已成为唯一文章状态。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 canonical source ref 的冻结时点和格式。若现有 pN#k 在结构阶段后会变化，先定义冻结阶段并写测试，禁止继续使用不稳定引用。

## 4. 当前代码事实与缺口

- DocumentTranslateTracker 主要保存文本和 prompt，没有稳定 page/ref/article/chain/final geometry。
- article_map、chain report、column_reflow report 各自保存局部信息，主键不统一。
- chain sidecar 没有最终几何；reflow sidecar 缺少 request/fragment/article 联结。
- 现有 debug_id 不适合作为验收门控键。
- methodology 要求普通段落和连续链都能回答 source、request、target、render 的完整对应。

## 5. 本批唯一目标

建立一个运行时 RunTrace 账本和统一 sidecar，使 source element、ArticleIR、translation request、target fragment、typeset slot 与 final PDF geometry 可以双向查询。

## 6. 非目标

- 不改变翻译内容或调用次数。
- 不实现跨栏/跨页回填算法。
- 不把 trace 字段写入冻结的 XML schema。
- 不记录完整敏感 prompt 明文；采用必要摘要和哈希。

## 7. 必须实现的行为

1. 定义 RunTrace API，集中管理以下阶段：
   - source registration；
   - request open/complete/fail；
   - whole target registration；
   - target fragment allocation；
   - typeset geometry；
   - repair generation/rollback；
   - final PDF span/block binding。
2. source 记录 stable source ref、page/index、source box、text/style hash、article ID、chain ID。
3. request ID 使用确定性材料生成，记录 request kind、ordered source refs、merged source hash、prompt/config hash 和 translator call count。
4. target 记录 whole target hash、fragment ID/order/text range/text hash、allocation status。
5. geometry 记录 slot ID、pre-repair box、final page/box、font/color summary、render status。
6. 定义 source/fragment 终态枚举：rendered、protected、failed_with_issue。
7. 提供查询索引：source→request→fragments→geometry，以及 final geometry→fragment→request→source。
8. sidecar JSON 输出稳定排序；阶段更新必须经统一 API，禁止消费者自行写不兼容结构。
9. high_level 创建一个 trace 实例并显式传递。

## 8. 数据契约和不变量

- 每个 request 的 ordered source refs 非空且无重复。
- 每个 fragment 只属于一个 request。
- chain fragments 依 order 拼接后等于规范化 whole target。
- target 字符范围不重叠、不缺口。
- 每个 registered source 最终有一个明确终态。
- rollback 增加 generation，并撤销该 generation 的 geometry/fragment active 状态。
- 哈希使用明确的 canonicalization 和版本字段。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- 新的 run_trace 模块
- babeldoc/high_level.py
- babeldoc/document_il/midend/il_translator_llm_only.py
- babeldoc/document_il/midend/chain_translation.py
- typeset/reflow 的最小 trace hook
- sidecar/report writer
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 列出现有 tracker 和 sidecar 字段，确认可复用与废弃映射。
2. 定义 versioned trace schema 和纯数据 API。
3. 在 source/ArticleIR 构建后注册 source。
4. 在 translator 和 chain path 接入 request/target 事件。
5. 提供 typeset/final geometry 的 hook；尚未实现的阶段允许 pending，不能伪造坐标。
6. 加入 terminal-state validator 和双向查询。
7. 写稳定 JSON 并测试 rollback generation。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_run_trace.py

必须覆盖：

- 普通段落单请求完整链路。
- 两页 continuity chain 的 whole target 和 fragments。
- request fail/protected 的显式终态。
- fragment range 重叠、缺口和重复 source ref 被拒绝。
- rollback 后旧 geometry inactive、新 generation 可写。
- final geometry 能反查 source；source 能正查 final geometry。
- 重复运行 JSON 顺序和 ID 稳定。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_run_trace.py
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

- [ ] source、article、chain、request、fragment、geometry 共用稳定主键。
- [ ] 普通段落和 chain 均可双向查询。
- [ ] pending、rendered、protected、failed 状态区分清晰。
- [ ] trace 不依赖 debug_id 门控。
- [ ] rollback generation 可审计。
- [ ] 未完成的下游 geometry 保持 pending。
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
git commit -m "feat(trace): connect source translation fragments and geometry"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C03
Status: committed | blocked | not started
Commit: <hash> feat(trace): connect source translation fragments and geometry
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

