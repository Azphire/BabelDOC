# Codex Plan C01 — 公开并校验 magazine 运行配置

状态：可执行  
仓库：https://github.com/Azphire/BabelDOC  
审计基线：3b163e9713353cc73085591a3d74e0c2e179fd49  
目标提交：feat(runtime): expose and validate magazine feature profile  
建议模型：GPT-5.6 Sol  
建议推理强度：high  
单批时间策略：开发短周期；每条测试命令最多 60 秒；完成本提交后停止。

## 0. 本文件的使用方式

本文件是 C01 的完整执行上下文。Codex 读取本文件和仓库根目录 CLAUDE.md 后即可执行，无需读取总计划或其他批次文件。

只实现本批次。依赖批次只用于前置检查，禁止顺手修改其他批次的目标。代码、配置、针对性测试和本批必要的说明应进入同一个 commit。

执行结束后必须：

1. 运行本文件规定的快速检查。
2. 检查最终 diff，排除无关修改。
3. 使用精确提交信息 “feat(runtime): expose and validate magazine feature profile” 创建一个 commit。
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

本批依赖：无；这是序列中的首个提交。

按顺序执行：

1. 运行 git fetch origin。
2. 记录 git status --short --branch、git rev-parse HEAD、git log -n 20 --oneline。
3. 检查工作树是否已有修改；有无关修改时保留并避开，有目标文件冲突时停止报告。
4. 检查依赖批次的目标 commit message 是否已在当前分支历史中。
5. 若 origin/main 已推进，查看从审计基线到 origin/main 的相关文件 diff。新代码改变了本批前提时停止并报告，不做盲目 merge、rebase 或旧设计套用。
6. 确认本批涉及的所有调用点、配置读取点、sidecar 写入点和现有 spec check。
7. 先写出 5–10 行实现微计划，再开始编辑。

若当前分支尚未建立本轮工作链，应从干净的最新 origin/main 创建专用 feature branch。不要在存在用户修改的 main 上直接切换或提交。

## 4. 当前代码事实与缺口

- translation_config.py 只公开了部分 magazine flags。
- drop-cap mark/apply/render、column reflow、repair、title typeset 等路径大量使用 getattr(config, name, default)。
- 工具脚本通过 setattr 临时开启功能，无法证明 CLI、构造器和运行报告使用了同一个配置。
- configs/checkpoint_stages.json 知道部分 sidecar 开关名称，但没有一个权威运行 profile。
- 某些功能依赖 magazine_detect 才会进入后续路径，当前没有启动前的依赖验证。

## 5. 本批唯一目标

建立一个公开、可序列化、可从正常入口启用且能在启动前验证的 magazine runtime profile。默认配置必须保持现有主分支行为。

## 6. 非目标

- 不修改文章分组算法。
- 不实现重排、连续链或首字几何。
- 不改变任何已有功能的默认启用状态。
- 不重写通用配置系统。

## 7. 必须实现的行为

1. 盘点所有 getattr(config, "magazine_*") 和工具脚本 setattr，形成唯一字段清单。
2. 将实际使用的开关加入 TranslationConfig 的公开字段、构造和序列化路径。
3. 提供一个版本化 magazine profile 配置文件；命名与现有 configs 约定一致。
4. 让 CLI 或项目的正式配置入口可以选择该 profile，不能依赖测试脚本直接 setattr。
5. 增加启动前 dependency validator，至少覆盖：
   - drop_cap_render 依赖 drop_cap_apply；
   - drop_cap_apply 依赖 mark/decision 可用；
   - column/article reflow 依赖 source checkpoint 和 article state；
   - repair 依赖 detect；
   - 需要源几何的 detector 在缺少 checkpoint 时不能伪装成已启用。
6. 写 magazine_run_manifest.json，记录有效开关、profile/version、配置文件哈希、代码 HEAD、输入摘要和 validation result。
7. 未选择 magazine profile 时保持原有默认行为。

## 8. 数据契约和不变量

- 同一开关只有一个权威字段名。
- 配置 round-trip 后值、类型和默认值不变。
- 非法组合在修改 Document IL 前失败。
- manifest 反映实际有效配置，不能只复制用户输入。
- 新 profile 不自动开启网络调用。

## 9. 预计修改范围

以下路径是审计时的主要落点。执行时必须先确认当前 HEAD 的真实调用关系，允许采用更小且等价的文件集合。

- babeldoc/translation_config.py
- 正式 CLI/config 入口
- configs/ 下的新 profile 或 schema
- tools/run_drift_trio.py 等仍使用临时 setattr 的入口
- 最邻近的 config/spec checks

禁止为了“顺便清理”进行大范围重命名、格式化或架构迁移。

## 10. 建议执行顺序

1. 使用 rg 找出全部 magazine_* 读取和 setattr 写入。
2. 建立字段表：名称、类型、默认值、消费者、依赖。
3. 先实现 TranslationConfig 和序列化，再实现 profile 载入。
4. 实现纯函数 dependency validation，并在 pipeline 修改 IL 前调用。
5. 实现 manifest，避免把不可序列化对象写入 JSON。
6. 修改工具入口，使其使用公开配置。
7. 添加短测试，确认默认兼容和非法组合早失败。

每一步完成后检查 diff。发现需要跨入其他批次时停止，把新增需求写入结果报告。

## 11. 快速测试要求

测试必须离线、确定性、可在短时间内重复。优先扩展最邻近的现有 spec check；没有合适文件时新增一个语义明确的短检查文件。

本批建议测试入口：spec_checks/spec_check_magazine_runtime_profile.py

必须覆盖：

- 默认构造值与修复前等价。
- 所有公开字段可以构造、序列化、反序列化。
- 正式入口可加载 profile。
- render without apply、repair without detect、reflow without checkpoint 被拒绝。
- 合法最小组合通过。
- manifest 的 effective values 和 config hashes 稳定。
- 测试不得真正运行翻译或 PDF 排版。

通用命令：

~~~bash
python -m compileall -q babeldoc tools spec_checks
python spec_checks/spec_check_magazine_runtime_profile.py
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

- [ ] 所有正在使用的 magazine 开关均有公开定义。
- [ ] 正式入口不再依赖临时 setattr。
- [ ] 非法依赖组合在 IL 变更前给出结构化错误。
- [ ] 默认配置行为保持兼容。
- [ ] manifest 可复现实际运行 profile。
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
git commit -m "feat(runtime): expose and validate magazine feature profile"
~~~

不要 amend、squash 或夹带下一批代码。测试和实现必须位于同一个 commit。

## 14. 最终报告格式

按以下格式返回：

~~~text
Batch: C01
Status: committed | blocked | not started
Commit: <hash> feat(runtime): expose and validate magazine feature profile
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

