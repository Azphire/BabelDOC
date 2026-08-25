# Codex Plan C15 — 增加 PDF 写出后合规验证

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：feat(pdf-qa): validate final searchable PDF compliance  
建议模型：GPT-5.6 Sol  
建议推理强度：high  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C15 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “feat(pdf-qa): validate final searchable PDF compliance” 创建一个 commit。
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

本批依赖：C01–C14 必须已提交；RunTrace 能记录 final geometry，asset inventory 和 drop-cap evidence 可用。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

确认 PDFCreater.write 的唯一主调用点、输出路径生命周期和异常处理。validator 必须在文件关闭并可 reopen 后执行。测试使用生成式 1–2 页 PDF，不依赖 corpus 文件。

## 4. 当前代码事实与缺口

- high_level.py 当前在 PDFCreater.write 前运行 detection。
- 写出后没有 reopen validator。
- PDF writer 对部分 XObject font、stream、mediabox 恢复异常记录后继续。
- 当前守恒主要依赖 IL 层，无法证明最终 PDF 仍可打开、可搜索且资产/颜色/几何正确。
- methodology 的最终合规需要页数、固定资产、可搜索文本、目标覆盖和首字装置证据。

## 5. 本批唯一目标

在 PDF 写出完成后使用 PyMuPDF reopen，执行轻量、可配置的最终结构与内容合规检查，并将结果写入 RunTrace/报告和 pipeline 状态。

## 6. 非目标

- 不运行全页面高分辨率视觉回归。
- 不做 OCR 或像素级出版质量评分。
- 不修复 writer；validator 只报告并阻止合格状态。
- 不删除失败 PDF。
- 不检查未触及页面的昂贵 span 细节。

## 7. 必须实现的行为

1. 新增 FinalPdfValidator，在输出文件关闭后 reopen。
2. 全局检查：
   - 文件可打开；
   - page count；
   - mediabox/cropbox/rotation/page labels；
   - 基本 catalog/page tree 完整。
3. touched pages 检查：
   - 文本可提取且非异常空白；
   - RunTrace target fragments 可经明确 normalization 定位；
   - 无超出容差的重复 target；
   - text blocks/spans 在 page/article/protected bounds 内；
   - font/span color summary 可读取。
4. fixed assets 检查：
   - image/XObject/drawing/form 的可观测数量和 bbox；
   - 与 source/final inventory 在容差内一致；
   - 无异常漂移或丢失。
5. drop-cap 检查：
   - enlarged span 只含一个 eligible character；
   - 字号/颜色/bbox 与 RunTrace intent 和语言几何策略一致；
   - body 文本仍完整可搜索。
6. writer 已记录 XObject font/stream/mediabox restoration error 时，validator 结果至少为 degraded；若结构/内容不合规则 fail。
7. 输出 final_pdf_compliance.json：
   - status=pass/degraded/fail；
   - input/output摘要；
   - checks、evidence、touched pages；
   - trace reconciliation；
   - writer warnings。
8. pipeline 只有 pass 才标记 fully compliant。degraded/fail 保留 PDF 和诊断文件，并返回非合格状态。
9. 成本控制：全局结构检查覆盖所有页；span/asset 深检只覆盖 touched pages。

## 8. 数据契约和不变量

- validator 完全只读，不修改最终 PDF。
- page count 和 page boxes 与源/manifest 一致。
- 每个 rendered target fragment 有 final PDF evidence，或产生明确 issue。
- failed PDF 仍保留用于诊断。
- normalization 版本化，不能用宽松模糊匹配掩盖缺失/重复。
- validator exception 转换为 fail 报告，不能被吞掉。
- 没有 touched pages 时仍执行基本可打开、页数和页面尺寸检查。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- 新的 final_pdf_validator 模块
- babeldoc/high_level.py 的 post-write 调用
- PDFCreater warning handoff
- RunTrace final binding
- final PDF QA configs/report
- 相关 spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 定位 write 完成和 file-close 边界。
2. 定义 validator result/schema 和 pass/degraded/fail 规则。
3. 先实现 reopen、page count/geometry。
4. 实现 touched-page text/fragment reconciliation。
5. 实现 fixed asset 和 drop-cap evidence checks。
6. 接入 writer warnings。
7. 接入 high_level 和 manifest/trace。
8. 用生成式 PDF 注入失败测试，确认文件保留。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_pdf_compliance.py

必须覆盖：

- 正常 1–2 页 searchable PDF 通过。
- 损坏/不可打开文件失败并有报告。
- page count 或 mediabox 改变失败。
- target fragment 缺失和异常重复失败。
- text span 越界失败。
- image/XObject bbox 漂移失败。
- drop-cap 字符数、颜色或 bbox 错误失败。
- writer warning 产生 degraded/fail 的预期状态。
- validator 前后 PDF bytes/hash 不变。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_pdf_compliance.py
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

- [ ] PDF write 后确实 reopen。
- [ ] 全局页数和页面 geometry 得到验证。
- [ ] touched-page 目标覆盖、重复和 bounds 得到验证。
- [ ] fixed asset 和 drop-cap 证据得到验证。
- [ ] writer warnings 进入最终状态。
- [ ] pass/degraded/fail 语义明确。
- [ ] 失败 PDF 和诊断报告被保留。
- [ ] validator 只读且短测在时限内。
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
git commit -m "feat(pdf-qa): validate final searchable PDF compliance"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C15
Status: committed | blocked | not started
Commit: <hash> feat(pdf-qa): validate final searchable PDF compliance
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

