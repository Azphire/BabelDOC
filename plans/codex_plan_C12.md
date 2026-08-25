# Codex Plan C12 — 实现英文 raised initial 几何

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：fix(drop-cap): implement English raised initial geometry  
建议模型：GPT-5.6 Sol  
建议推理强度：xhigh  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C12 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “fix(drop-cap): implement English raised initial geometry” 创建一个 commit。
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

本批依赖：C01–C11 必须已提交；DropCapIntent、asset guard、transaction 和 drop_cap_geometry detector contract 可用。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

先确认“英文目标”的判定使用 target language/policy，不能以源语言或单个字符脚本替代。若 HuaweiTech p4/p6 文件不可用，使用生成式夹具完成代码测试，并把真实页验证列为 skipped。

## 4. 当前代码事实与缺口

- drop_cap_render.py 正常路径只选择 lines[0][0] 的一个 Unicode 字母，因此当前观察到的“首单词放大”更可能来自候选未命中、flatten 失败、render 被拒或旧样式残留。
- 现有共享 top 公式以 first baseline + body size 为基准，大 glyph 会向下沉。
- 现有 guard 要求 glyph ink 完全位于 paragraph box，阻止英文首字上缘高出正文文本块。
- 旧 B11.8 设计含两行 reserve 倾向，与本轮用户指定的英文行为不符。
- 用户指定：仅放大首字母；底边和第一行对齐；上边缘超出文本块；第二行不受首字占位。

## 5. 本批唯一目标

实现英文目标的 raised initial：只放大一个首字母，首字 ink 底边与第一行正文 ink 底边对齐，上缘允许高出正文文本块，水平占位只影响第一行。

## 6. 非目标

- 不实现中文两行嵌入式首字；属于 C13。
- 不放大首单词、词首 cluster 或前置标点。
- 不通过扩大整个 paragraph box 放宽普通正文越界规则。
- 不允许首字穿越 page/article envelope 或固定资产。
- 不在代码中写 HuaweiTech 页码特例。

## 7. 必须实现的行为

1. 在 render 前验证 active DropCapIntent 和 target_policy=english_raised_initial。
2. 选择一个 eligible alphabetic code point；opening punctuation 以 body style 正常排版。
3. 分离两个几何对象：
   - body logical box/lines；
   - decorative initial ink box。
4. 使用实际 font glyph metrics/ink bbox 计算缩放和位置。
5. 垂直契约：
   - initial_ink_bottom 对齐 first_line_ink_bottom；
   - 误差容差来自 drop-cap config；
   - initial_ink_top 可高于 paragraph body box top；
   - decorative box 必须位于 article/page envelope 且不碰 fixed assets/title。
6. 水平契约：
   - 第一行正文从 initial_ink_right + gutter 后开始；
   - 只为第一行保留水平空间；
   - 第二行及后续行恢复 body column x；
   - leading punctuation 的顺序和 body styling 不变。
7. 大字 size/cap-height 策略进入 config，并设最小/最大界限。
8. 无法满足 collision/bounds 时回滚该 intent，保留普通正文并报告 issue。
9. RunTrace 写 initial char、ink bbox、first-line metrics、reserve lines=1、color/style evidence。

## 8. 数据契约和不变量

- enlarged character count 恒为 1。
- initial_ink_bottom 与 first_line_ink_bottom 的差不超过 tolerance。
- initial_ink_top 高出 body box 是允许状态，不得被普通 paragraph bounds detector误判。
- decorative box 仍受 page/article/fixed-asset guard。
- second_line_start_x 等于正常 body x tolerance 范围。
- source color 来自 C11 intent。
- failure 恢复普通 searchable text，不丢字符、不重复字符。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/drop_cap_render.py
- drop-cap geometry/config
- typesetter line/ink metrics 接口
- bounds/overlap detector 的 decorative geometry policy
- RunTrace
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 先写一个能重现旧下沉公式失败的 font-metric 测试。
2. 实现 body/decorative box 分离。
3. 依据 glyph ink metrics 计算 scale 和 bottom alignment。
4. 实现 first-line-only horizontal reserve。
5. 放宽 decorative top 相对 body box 的限制，同时保留 article/page/assets guard。
6. 接入 detector、transaction、trace。
7. 测试字体差异、前置引号、窄栏和上方标题。
8. 若真实 HuaweiTech p4/p6 可用，只运行这两页的冻结翻译 smoke，并记录路径原因。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_drop_cap_english.py

必须覆盖：

- 首单词为多个字母时只有首字母放大。
- opening quote/bracket 保持 body size，后续首字母放大。
- initial bottom 与第一行 ink bottom 对齐。
- initial top 高于 body text box top。
- 第二行 x 恢复正常栏起点。
- 不同字体 cap height/descent 下仍满足容差。
- 彩色首字保持 C11 颜色。
- 上方 title/fixed asset 碰撞时回滚普通正文。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_drop_cap_english.py
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

- [ ] 英文 enlarged span 只含一个字母。
- [ ] 底边按真实 ink metrics 对齐第一行。
- [ ] 上缘可高出正文框。
- [ ] 第一行保留 gutter，第二行恢复全宽。
- [ ] decorative geometry 受 page/article/asset 守卫。
- [ ] 失败回滚后文本可搜索且守恒。
- [ ] HuaweiTech 局部 smoke 已 PASS，或因文件缺失明确 SKIPPED。
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
git commit -m "fix(drop-cap): implement English raised initial geometry"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C12
Status: committed | blocked | not started
Commit: <hash> fix(drop-cap): implement English raised initial geometry
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

