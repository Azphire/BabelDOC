# Codex Plan C11 — 保存首字 intent、源颜色并校验人工决策

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：feat(drop-cap): preserve initial intent style and source color  
建议模型：GPT-5.6 Sol  
建议推理强度：high  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C11 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “feat(drop-cap): preserve initial intent style and source color” 创建一个 commit。
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

本批依赖：C01–C10 必须已提交；RunTrace、ArticleIR、transaction 和 detector contract 可用。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 drop_cap.py 的 mark、decision、apply/flatten 顺序，以及 high_level.py 中 drop_cap_render 位于 typeset 后、PDF write 前。确认 PdfCharacter/PdfStyle 的颜色字段实际格式，不猜测 RGB/CMYK 表示。

## 4. 当前代码事实与缺口

- drop_cap.py 在 apply 阶段 flatten composition，源首字独立 graphic state 会被段落基准样式覆盖。
- 翻译写回也使用段落基准样式。
- drop_cap_render.py 只能读取翻译后首字符状态，源颜色在此之前已丢失。
- PDF writer 支持逐字符 graphic state，说明最终呈现层能够输出独立颜色。
- manual decision 当前可能命中非候选或过期候选。
- flatten 失败后仍可能保留 keep 并进入 render。
- 用户要求中英双向都保留英文原文或中文原文首字颜色。

## 5. 本批唯一目标

在 flatten 和翻译前冻结首字装置 intent 与源首字实际颜色，并把该颜色可靠应用到目标语言的一个 eligible 首字符；同时拒绝过期、非候选和 flatten 失败状态。

## 6. 非目标

- 不实现英文或中文的最终几何；分别属于 C12、C13。
- 不保留源首字字体；目标字体继续遵循目标语言策略。
- 不放大完整首单词。
- 不修改 PDF writer 的通用颜色渲染。
- 不让人工 decision 绕过 candidate validity。

## 7. 必须实现的行为

1. 定义 DropCapIntent 运行时结构，至少包含：
   - stable source ref、article ID；
   - source char/codepoint；
   - source style hash；
   - normalized fill color、stroke color、alpha；
   - source color space/转换证据；
   - target policy；
   - candidate fingerprint；
   - decision/version；
   - flatten status；
   - render status。
2. 在任何 flatten/translation 前，从源首字实际 PdfCharacter graphic state 捕获颜色。
3. 颜色标准化必须复用 PDF/IL 现有转换逻辑；保持填充色，必要时记录描边和 alpha。
4. 定义 target eligible initial：
   - 跳过 opening quote/bracket 等前置标点；
   - 英文目标选第一个 alphabetic code point；
   - 中文目标选第一个 CJK ideograph；
   - 只选一个 code point/grapheme；
   - 前置标点保持正文大小和颜色。
5. 将源颜色应用到目标 eligible initial；正文与前置标点保持目标段落样式。
6. 目标字体、字体回退和字形选择继续走目标语言 typesetter。
7. decision 必须同时匹配 candidate ID、source ref、source text/style fingerprint 和当前 config version。
8. flatten 失败时状态设为 failed，禁止 render，产生 typed issue 和 trace event。
9. RunTrace 记录 source style→intent→target initial style。

## 8. 数据契约和不变量

- 每个 active intent 对应一个当前有效 candidate。
- 源颜色在翻译前冻结，不从翻译后 composition 反推。
- 目标只有一个 eligible initial 获得源首字颜色。
- 前置标点、第二字符和正文不被意外染色。
- 源字体不随颜色迁移到目标。
- stale/noncandidate decision 不改变 IL。
- flatten failure 后没有 enlarged render。
- 颜色比较使用配置化容差和统一色彩空间。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/document_il/midend/drop_cap.py
- drop-cap intent/runtime state 模块
- babeldoc/document_il/midend/drop_cap_render.py 的最小 style 接口
- RunTrace
- drop-cap configs
- HITL decision validation
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 追踪源 PdfCharacter graphic state 到 PDF writer 的真实字段。
2. 定义 color normalization 和 DropCapIntent。
3. 在 mark/apply 前冻结 source style。
4. 实现 eligible initial selector。
5. 将 target initial 独立 style 与 body composition 关联。
6. 加入 decision fingerprint 和 flatten gate。
7. 接入 trace/detector evidence。
8. 用双向彩色夹具验证。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_drop_cap_intent.py

必须覆盖：

- 红色英文源首字翻译为中文后，目标首字保持红色。
- 蓝色中文源首字翻译为英文后，目标首字保持蓝色。
- 开头含引号/括号时，标点不放大、不继承首字色，后续首个 eligible 字符获得颜色。
- 首单词只有第一个字母获得 intent。
- 源字体与目标字体不同，颜色保留且字体不被复制。
- flatten exception 禁止 render。
- stale/noncandidate manual decision 被拒绝且 IL digest 不变。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_drop_cap_intent.py
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

- [ ] DropCapIntent 在 flatten 前保存源首字样式。
- [ ] 中英双向首字颜色可追踪并正确应用。
- [ ] 只有一个 eligible target character 获得颜色/放大身份。
- [ ] 前置标点和正文样式保持正常。
- [ ] stale/noncandidate/flatten-failed 路径受阻。
- [ ] 不改变目标字体选择。
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
git commit -m "feat(drop-cap): preserve initial intent style and source color"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C11
Status: committed | blocked | not started
Commit: <hash> feat(drop-cap): preserve initial intent style and source color
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

