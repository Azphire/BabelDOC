# Codex Plan C13 — 实现中文两行嵌入式首字几何

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：fix(drop-cap): implement Chinese two-line embedded geometry  
建议模型：GPT-5.6 Sol  
建议推理强度：xhigh  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C13 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “fix(drop-cap): implement Chinese two-line embedded geometry” 创建一个 commit。
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

本批依赖：C01–C12 必须已提交；中文目标可复用 DropCapIntent、字体 ink metrics、transaction 和 detector。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认“中文目标”的判定来自 target language/policy。确认 CJK 字体 fallback 返回可用 glyph metrics；metrics 不可用时必须安全回滚，不能以固定字号猜测。

## 4. 当前代码事实与缺口

- 现有 sink/initial 配置在 reserve/grid 上有差异，但中英文共用主要纵向公式。
- 当前没有显式保证中文首字顶边随第一行 ink top、底边随第二行 ink bottom。
- reserve/gutter 不充分时，首字底部会与正文重叠。
- 用户指定：中文首字顶边和第一行对齐，底边与第二行对齐，前两行避让，且双向保留源首字颜色。

## 5. 本批唯一目标

实现中文目标的两行嵌入式首字：单个 CJK 首字覆盖两行高度，顶边对齐第一行、底边对齐第二行，前两行保持 gutter，第三行恢复全栏宽度。

## 6. 非目标

- 不改变 C12 的英文 raised initial。
- 不放大两个中文字符。
- 不让 opening punctuation 成为放大字符。
- 不使用固定像素偏移或刊物专用参数。
- 不允许首字和正文或固定资产重叠。

## 7. 必须实现的行为

1. 验证 active DropCapIntent 和 target_policy=chinese_two_line_initial。
2. 跳过 opening punctuation，选择一个 eligible CJK ideograph。
3. 先 dry-run 至少两行正文，获取：
   - first_line_ink_top；
   - second_line_ink_bottom；
   - line baselines、body x 和 line height。
4. 使用目标 CJK glyph 的实际 ink bbox 计算 scale，使：
   - initial_ink_top 对齐 first_line_ink_top；
   - initial_ink_bottom 对齐 second_line_ink_bottom。
5. 前两行 body start x 位于 initial_ink_right + gutter 后；第三行恢复正常 body x。
6. glyph ink、body ink、article/page envelope 和 fixed assets 均纳入碰撞检查。
7. 正文不足两行、字体 metrics 无效、宽度不足或碰撞无法解决时：
   - 回滚 drop-cap decoration；
   - 保留普通正文；
   - 写 typed issue。
8. source color 使用 C11 intent，目标字体使用中文字体策略。
9. RunTrace 记录 reserve lines=2、top/bottom anchors、gutter 和 style evidence。

## 8. 数据契约和不变量

- enlarged character count 恒为 1。
- initial top 与 first-line ink top、initial bottom 与 second-line ink bottom 均在 tolerance 内。
- 第一、二行正文不进入 initial ink + gutter 区域。
- 第三行恢复正常 body x。
- initial/body/fixed assets 无 overlap。
- 颜色来自源 intent，字体来自目标语言。
- 失败回滚后字符顺序、文本内容和可搜索性保持。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/drop_cap_render.py
- drop-cap geometry/config
- CJK typesetter/font metrics
- drop_cap_geometry detector
- RunTrace/transaction
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 写旧共享公式导致顶底错位/重叠的失败测试。
2. 获取两行 body ink anchors。
3. 依据 CJK glyph ink bbox 求 scale/position。
4. 实现两行 reserve 和第三行恢复。
5. 接入碰撞、bounds、asset guard。
6. 接入 C11 颜色和 RunTrace。
7. 覆盖短正文、窄栏、字体 fallback 和前置标点。
8. 验证失败路径恢复普通正文。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_drop_cap_chinese.py

必须覆盖：

- 单个中文首字覆盖两行，顶底 anchors 在容差内。
- 第一、二行 x 位于 cap+gutter 后，第三行恢复。
- opening punctuation 不放大。
- 两行和三行以上正文。
- 不同中文字体与 fallback。
- 彩色源首字在目标中文保持颜色。
- 窄栏、正文不足两行和固定资产碰撞时回滚。
- cap 与正文 ink 零 overlap。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_drop_cap_chinese.py
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

- [ ] 中文 enlarged span 只含一个 CJK 字符。
- [ ] 顶边与第一行、底边与第二行对齐。
- [ ] 前两行 reserve 和 gutter 正确。
- [ ] 第三行恢复正常 x。
- [ ] 颜色保留且目标字体正确。
- [ ] 无正文/资产碰撞。
- [ ] 失败安全回滚。
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
git commit -m "fix(drop-cap): implement Chinese two-line embedded geometry"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C13
Status: committed | blocked | not started
Commit: <hash> fix(drop-cap): implement Chinese two-line embedded geometry
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

