# Codex Plan C04 — 补齐固定视觉资产守卫和几何前置条件

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：fix(reflow): complete fixed asset guards and prerequisites  
建议模型：GPT-5.6 Sol  
建议推理强度：high  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C04 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “fix(reflow): complete fixed asset guards and prerequisites” 创建一个 commit。
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

本批依赖：C01–C03 必须已提交；ArticleIR 与 RunTrace 可用。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 source checkpoint 的正式位置、解析 API 和失败语义。确认 fixed asset 分类与 IL 的 PdfXobject、PdfFigure、PdfForm、PdfCurve、PdfRectangle、公式组件相对应。

## 4. 当前代码事实与缺口

- column_reflow.py 已有 source geometry、formula/XObject paragraph anchoring、obstacle 检查和页/栏 rollback 基础。
- configs/column_reflow.json 的 obstacle collections 漏掉 pdf_xobject。
- overlap detector 已检查 XObject，说明 reflow 与 detector 对固定对象集合不一致。
- source_geometry.py 捕获异常后返回 None；依赖源几何的检测器随后可能跳过。
- 当前 conservation 没有完整检查固定资产数量、bbox、内容摘要和页面尺寸。

## 5. 本批唯一目标

在任何文章重排或 repair 位移前建立完整、统一的 fixed asset inventory；源几何不可用时安全阻断相关动作。

## 6. 非目标

- 不实现文章跨栏或跨页流。
- 不改变固定视觉资产本身。
- 不对图像做 OCR、重绘或语义分类。
- 不放宽页边界和碰撞容差。

## 7. 必须实现的行为

1. 建立统一 fixed asset classification，供 reflow、detector、transaction 和 PDF QA 复用。
2. 将 pdf_xobject 加入 column_reflow obstacles。
3. inventory 至少记录：
   - asset ref/type/page；
   - bbox；
   - 稳定对象或内容摘要；
   - movable/protected policy；
   - 所属 formula/figure 关系。
4. 纳入 figure、xobject、form、curve、rectangle、公式组件、页眉页脚及未参与重排的页面家具。
5. 对 source checkpoint 建立明确结果：available、missing、invalid。
6. 需要源几何的动作遇到 missing/invalid 时：
   - 不修改 IL；
   - 产生结构化 issue；
   - 在 trace/manifest 记录 blocked reason。
7. 事务前后比较 fixed asset count、bbox 和摘要；任一变化触发回滚。
8. ArticleIR 标记的 unsupported page 全部禁止 article reflow。

## 8. 数据契约和不变量

- reflow 和 overlap detector 使用同一 asset category source。
- fixed asset inventory 在一次运行中不可被普通 reflow 修改。
- source geometry failure 不得静默降级为“无问题”。
- protected asset bbox 在容差内完全不变。
- 资产摘要算法稳定且不依赖对象内存地址。
- asset guard failure 必须发生在提交事务前或触发完整回滚。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- configs/column_reflow.json
- babeldoc/document_il/midend/column_reflow.py
- source_geometry.py
- overlap detector 及共享 asset inventory 模块
- transaction/conservation hook
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 盘点 IL 全部可见视觉对象类型及现有 detector 分类。
2. 定义一个共享 inventory builder。
3. 修复配置中的 pdf_xobject 漏项。
4. 将 source geometry 的异常转换为 typed result/issue。
5. 在 reflow 候选前做 obstacle 查询，在事务后做 inventory 比较。
6. 加入 unsupported page guard。
7. 用生成式 IL/PDF 夹具验证 XObject、form、curve。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_fixed_asset_guard.py

必须覆盖：

- 候选文本位移穿越 PdfXobject 时拒绝。
- figure、form、curve、rectangle 和 formula 保护仍有效。
- 合法空白区位移可通过。
- source checkpoint missing 和 invalid 都阻断动作并产生 issue。
- fixed asset bbox/count/digest 漂移触发回滚。
- unsupported same-page multi-article 页面不运行重排。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_fixed_asset_guard.py
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

- [ ] XObject 已进入统一障碍物集合。
- [ ] reflow、detector、transaction 共享同一资产分类。
- [ ] 源几何错误具有显式 blocked 状态。
- [ ] 固定资产变化触发完整回滚。
- [ ] unsupported 页面受保护。
- [ ] 默认未启用 reflow 的运行保持兼容。
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
git commit -m "fix(reflow): complete fixed asset guards and prerequisites"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C04
Status: committed | blocked | not started
Commit: <hash> fix(reflow): complete fixed asset guards and prerequisites
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

