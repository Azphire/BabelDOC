# CLAUDE.md — BabelDOC Magazine Extension (v1)

本文件是本项目所有 Claude Code 会话的持久上下文。每个会话开始时先完整阅读本文件与当次的 PLAN 文件,除此之外不依赖任何口头约定。

## 1. 项目使命

在 BabelDOC(上游:布局保持型 PDF 翻译流水线)基础上扩展杂志翻译能力,三条主线:

1. **HITL**:术语、首字母下沉、页面类型等裁决点由人工两遍式仲裁(导出裁决单 → 人工修订 → 带裁决文件重跑)。
2. **分页分段 IR**:页面类型(pageKind)与文章链(chainId)进入 IL schema,跨页文章链级联合翻译 + 句边界回填,消除页尾切断语义。
3. **ReAct 自修复**:排版后检测(IL 几何为主、VLM 兜底)→ 有界修复动作 → 增量重排 → 复检,带迭代上限与回滚。

## 2. 代码库关键事实(已验证,修改前仍须现场复核)

- 流水线入口:`babeldoc/format/pdf/high_level.py` 的 `_do_translate_single`。stage 顺序:
  `DetectScannedFile → LayoutParser → TableParser → ParagraphFinder → StylesAndFormulas → AutomaticTermExtractor → ILTranslator[LLMOnly] → Typesetting → FontMapper → PDFCreater`
- **翻译路径唯一指定为 `il_translator_llm_only.py`**(`ILTranslatorLLMOnly`,当 `translator_supports_llm` 为真时启用)。禁止修改 `il_translator.py` 的行为;若某改动似乎必须落在 `il_translator.py`,停止并报告。
- IL 定义:`babeldoc/format/pdf/document_il/il_version_1.py`,由 `il_version_1.xsd` 经 xsdata 生成(`pyproject.toml` 含 `xsdata[cli,lxml,soap]>=24.12`)。schema 同时存在 `.rnc` / `.rng` / `.xsd` 三份,修改时三者必须同步。
- IL 序列化:`document_il/xml_converter.py`。`write_xml/read_xml/from_xml/to_xml` 为完整往返;`to_json/write_json`(orjson)**只写不读**,是人读/工具分析用的检查格式。约定:**XML 为机器往返格式(checkpoint/重放),JSON 为检查格式**。
- debug 模式下 `_do_translate_single` 已在各 stage 之后 `write_json` 落盘(`create_il.debug.json`、`layout_generator.json`、`paragraph_finder.json`、`styles_and_formulas.json`、`il_translated.json` 等),路径由 `translation_config.get_working_file_path()` 决定(`working_dir` 下)。
- `TranslationConfig`(`format/pdf/translation_config.py`):含 `debug`、`working_dir`、`custom_system_prompt`、glossary 体系(`user_glossaries` / `auto_extracted_glossary`)。
- `split_manager.py` 按页范围切分长文档为多 part 串行翻译;文章链将来不得横跨 split 边界(B9 处理)。
- 布局标签:`PdfParagraph.layout_label` 为自由字符串,无枚举约束。字符→layout 指派见 `document_il/utils/layout_helper.py`(`layout_priority` 列表、`is_text_layout`)。
- `ILTranslatorLLMOnly._is_body_text_paragraph` 白名单:`text / plain text / paragraph_hybrid`;`process_cross_page_paragraph` 目前仅配对"页 N 末段 + 页 N+1 首段"。
- 无 API key 的干跑方式:`only_parse_generate_pdf` 配置跳过全部翻译相关 stage,仍产出 PDF。
- 打包:hatchling,包名 `BabelDOC`,Python >=3.10,<3.14。
- **本地翻译缓存已内建**:`translator/cache.py`,peewee SQLite,DB 默认 `~/.cache/babeldoc/cache.v1.db`(`const.CACHE_FOLDER`),key = 引擎名 + 引擎参数 + 原文。`BaseTranslator.translate` 与 `llm_translate` 均先查缓存(受 `ignore_cache` 控制)。注意:`init_db()` 在 `cache.py` 模块导入时执行且路径硬编码;`MAX_CACHE_ROWS = 50_000` 超限即删旧行。B0 起缓存重定向到项目本地并禁用淘汰(见 §3)。
- checkpoint 规范形式为再序列化形式(to_xml(from_xml(x)));字节级比对一律先归一化。读取旧 checkpoint 时容忍 xsdata ConverterWarning,不容忍错误(W-B0-02)。checkpoint 序列化对 XML 1.0 非法码位做可逆转义,转义引导符自转义保证无歧义;规范形式比较在还原后进行。
- 两层 IR 原则:Article IR(段落级 chainId)权威规定统一翻译边界;Page IR(pageKind→policy)只提供排版/修复策略与链构建软先验,冲突时段落级证据优先。
- VLM 兜底消融关账:四档模型均无 policy 级增益,enabled 保持 false;基础设施保留,待区域语义或分布漂移场景重启评估。
- 评估协议:A/B 对比以缓存冻结重放为准;模型采样方差(gpt-4o temp=0 实测非确定)为已知局限;显著性主张需三跑设计。
- corpus/registry.user.json 是语料语义元数据的唯一权威,仅用户可编辑;机器会话从它重建 manifest,任何批次的 git diff 中出现 registry.user.json 即违规,除非当次 prompt 显式声明用户已更新登记。toc_pages 为 PDF 文件页序(1-based)中出现目录版面的页码列表,空列表表示节选不含目录页。page_labels.json 的值为可接受类型名数组(1-based 页号),机器判定命中数组任一元素即计为一致;多元素用于单页多版面(如目录与卷首语同版)与复合拼版页。source_lang/target_lang 为样张翻译方向声明,仅用户可写;一切运行驱动按样张读取方向,禁止全局方向配置覆盖。

## 3. 目录与代码落点约定

新代码尽量集中在扩展包内,最小化上游文件改动:

```
babeldoc/magazine/          # 全部扩展代码(classifier, chains, hitl, react, checkpoint 等)
prompts/                    # 全部 LLM/VLM prompt,一 prompt 一文件,禁止内联在代码中
configs/                    # page_types.json, repair_actions.json 等声明式配置
tools/                      # 独立脚本(render_diff.py 等)
examples/input/             # 翻译测试用 PDF(用户本地维护,不入库大文件)
examples/output/            # 一切实际翻译测试产物(译后 PDF、基线、diff 报告)
examples/cache/             # 项目本地 LLM 缓存 DB(cache.v1.db)
corpus/manifest.json        # 样张登记(指向 examples/input,含哈希/页数)
spec_checks/                # 每批次门禁脚本 spec_check_<batch>.py
UPSTREAM_DIFF.md            # 被触碰的上游文件登记表(文件、函数、改动目的、所属批次)
WAIVERS.md                  # 偏离/豁免登记表
```

对上游文件的每一处修改,必须在同一会话内登记进 `UPSTREAM_DIFF.md`。

## 4. 硬性编码约定

1. **注释一律英文(语料真值文件除外)**。注释只解释代码当前为何如此;**禁止变更日志式注释**(不写 changed/fixed/added for batch N,不留注释掉的旧代码)。改动理由写进 commit message 与 PLAN 文件。
2. **禁止在代码中按页面类型名分支**(不得出现 `if page_kind == "toc"` 之类)。下游只消费 `configs/page_types.json` 中声明的 policy 标志(`chain_eligible` / `translate` / `repair_profile`)。
3. **prompt 不进代码**。所有 LLM/VLM 调用的 prompt 从 `prompts/` 加载;prompt loader 在运行时把所加载文件的 SHA-256 记入 working_dir 的运行清单。
4. **阈值不散落**。新引入的数值阈值/开关一律进 `configs/` 的 JSON(有界参数:名称、取值、允许范围);禁止裸字面量启发式。
5. **通用信号约束**:所有判别与修复只能使用通用几何、统计、来源可靠性信号;禁止针对特定出版物(如 UNESCO Courier)的字面量或特判。
6. schema 改动:同步修改 `.rnc/.rng/.xsd` 三份,优先用 xsdata 重生成 `il_version_1.py`;若重生成配置不可复现,允许按生成物既有风格手工添加字段,但必须在 `WAIVERS.md` 登记。
7. 新增 IL 属性一律 optional,保证旧 XML 可解析(后向兼容是门禁断言)。
8. **所有 LLM/VLM 调用一律可缓存**:翻译路径复用内建 `TranslationCache`;新引入的调用点(页面分类 VLM、ReAct 决策等)必须经统一的缓存客户端封装(B3 建立),cache key 含 prompt 文件哈希。缓存 DB 使用项目本地 `examples/cache/cache.v1.db`,禁用行数淘汰;相同输入直接命中缓存,不发起 API 调用。
9. **人工介入(HITL)一律为可选层**:默认配置下全流程自动运行,每个裁决点必须有机器默认决策;启用人工裁决需显式开关,裁决结果作为覆盖输入。ReAct 修复循环同理,默认全自动。
10. IL schema 冻结:W-B1-01 解除前禁止新增/修改 IL 字段;批次运行期数据一律写入 working_dir 的 sidecar 文件(如 *.report.json)。
11. VLM 输出必须约束在声明词表内,越界输出按违规处理并回退确定性判定;VLM 判定只写 pageKindSource="vlm",次判定与失败原因一律走 sidecar。
12. 裁决文件哈希钉仅锚定'机器零改动';用户更新裁决时,钉随重钉条款更新并留变更记录,不构成门禁失败。
13. **冻结证据只读**:凡 git 跟踪的产出证据(`docs/eval/results_*` 及其同类),门禁与工具一律只读校验——重算写入临时目录再逐字节比对,依赖产物缺失时报 SKIPPED/FAIL 并指明缺失路径,严禁就地重算覆写。**保留策略永不淘汰四类路径**:git 跟踪的文件、`corpus/manifest.json` 命名的文件、`configs/output_retention.json` 的 `protected_paths` 登记的路径(与 `spec_checks/spec_check_e0.py` 的分级入库清单同步)、以及非批次目录。**淘汰前必先归档**:被淘汰批次匹配 `archive_patterns` 且不超过 `archive_max_file_kb` 的文件自动打包进 `docs/reports/archive/<batch>.zip` 并入库,大件仍删除;一次淘汰不得等于一次丢失。冻结产物一经淘汰不得以重跑顶替,受影响台账条目改记 `artifact pruned, sha recorded` 并在缺口登记中说明。

14. **单臂默认**:凡跑批,**未在 PLAN 中明写要求双臂时,只跑 on 臂**(标准 run config 全开关生效的那一臂),不跑 off 臂。off 臂只在该批的证据本身**就是两臂之差**时才跑(b10.5 的 reflow 施加/不施加即属此类),且须在 PLAN 里点名说明理由与用途。理由:双臂成本翻倍、产物翻倍、保留策略压力翻倍,而绝大多数批次的断言锚在终态而非差值上。
15. **会话不得静默丢弃自己的产出**:任何会话在删除自身产出前,须先归档(打包进 `docs/reports/archive/`)或在 `WAIVERS.md` 登记豁免并写明理由。保留策略只认批次目录(`tools/prune_outputs.py` 的 `^b(\d+)`),`F3` 一类非批次目录它按构造够不到,所以那里的删除**没有任何机制在看**——F3 会话自愿删掉两臂 work/ 与 out/ 约 4.5 GB,一个批次之后 b11.2 需要它作基线时才发现,而归档里没有 F3.zip。"可重放所以可再生"不是丢弃的理由:可再生的是字节,不可再生的是"这些字节是那次运行产出的"这件事。
16. **门禁证据由批次在跑时提取为衍生件**:门禁不得直接读 stage checkpoint 或完整 PDF。批次须在跑时把断言所需的量提取成**小体积衍生件**——体积与扩展名落在 `archive_patterns` 与 `archive_max_file_kb` 之内(现值:`*.report.md` / `*.json` / `*.log`,≤ 2048 KB)——门禁读衍生件。理由:checkpoint 是几 MB 到几十 MB 的 `.json` 与 `.xml`,两项归档条件一项都不满足,所以它**从来就进不了归档**;b10.1 / b10.3 / b10.4 共八条断言正是这样在证据被淘汰后永久失去了执行能力(见缺口登记 GAP-31),而它们要的其实只是几个数。门禁另须用 `spec_checks/evidence.py` 读证据,工作区缺失时自动回落读 `docs/reports/archive/<batch>.zip`;门禁自身读的路径由模块级 `GATE_EVIDENCE` 声明,保留策略据此绕行(`tools/prune_outputs.py` 的 `gate_evidence`)。本条自 b11.2 起对**新门禁**生效,既有门禁的回溯改写登记为缺口,不在本批回溯。


17. **门禁与 sweep 的输出一律不得丢弃**。任何 `spec_check_*` / `run_all.py` 的
    运行,其 stdout 与 stderr 必须落到可读之处——终端回显,或一个**不被 git 跟踪
    的**临时文件——**禁止重定向到 `/dev/null` 或 `$null`**。理由:b11.3 的 b3_3
    失败信息正因此不可复原,而重跑那次运行需要的是它当时说了什么,不是它现在会说
    什么。两条配套处置:(a) 单文件独立运行门禁会触发**嵌套 sweep**(§5.7 的兜底
    路径),置 `SPEC_NO_NESTED=1` 抑制;(b) 嵌套 sweep 被中断会留下**孤儿进程持有
    `sweep.lock`**,下一次 `run_all` 会因此挂住——先确认无活动 sweep 再删锁,不要
    先删锁再看。另注:sweep 输出**不得**重定向进 git 跟踪的日志文件,那会让每次复
    跑都改动冻结证据并使门禁全红。

18. **消费者清单为改判类修法的前置**。任何改变 IL 元素类型或标注归属的修法
    (把 `pdf_formula` 改判为文本、把某类字符移出某个 holder 之类),动手前必须先
    列出**所有**消费该标注的下游站点,并逐站点回答"改判后这里会发生什么",答案落
    进批次产物。**列表不得跨批复用**——机制不变而代码会变,复用的清单是没人核过的
    清单。b11.3 由此挡住一次静默丢图元:`PdfFormula` 有 `pdf_curve` / `pdf_form`
    而 `PdfLine` 两者皆无,`pdf_creater.py:867` 是这些图元唯一的渲染入口,改判即
    丢图且无任何报错。**携带 `pdf_form` / `pdf_curve` 的 composition 一律不得改
    判**,该项为绝对项,不因任何判定结果松动;清单须给出携带者计数,使"计数为零"
    是一次断言而不是一次沿袭。

## 5. 会话执行协议

1. 一个会话只执行一个 PLAN 文件中的一个任务批次;不顺手做计划外改动。
2. 动手前复核 PLAN 中引用的代码事实(符号名、行为);**若事实与 PLAN 前提不符,停止执行并输出差异报告**,不要自行改计划。
3. 每个批次交付必须包含 `spec_checks/spec_check_<batch>.py` 并全绿。门禁脚本必须同时含:
   - 正向断言(必须存在的行为/产物)
   - 负向断言(必须不存在的行为:未触碰的路径、不得出现的输出)
   - 端到端断言(基线样张跑通,关键守恒量:页数、段落数、渲染差异)
4. 会话结束输出:改动文件清单、UPSTREAM_DIFF.md 增量、门禁运行结果、遗留问题。
5. 每批次全绿后提交为单个 commit 并打 tag batch-<n>;所有门禁的 diff 断言以工作区对 HEAD 的增量为基准。
6. 门禁的 changed-files 类断言一律锚定本批次 tag(tag 存在时读 batch-<n>^..batch-<n>,否则读工作区对 HEAD);新批次门禁自创建起即用此写法。
7. 历史门禁复跑一律经 spec_checks/run_all.py 线性执行,门禁内部的嵌套复跑仅作为单文件独立运行时的兜底。
8. 迭代开发期用 run_all --fast 快速回归;批次提交打 tag 前必须全量 run_all 全绿(断言 6 的 EXPECTED-RED 状态除外,直至调参批次达标)。
9. plans/PLAN_<batch>.md 默认属于该批次门禁白名单,无须逐批枚举。
10. _pctl 特征的正向证据规则阈值必须 > 0.5(常量列 midrank 恒为 0.5)。
11. **单会话约定:一个会话结束时必须自己提交并打自己的 tag**。批次跨会话时(e1.1/e1.2、e2.1/e2.2 这种),tag 取 `batch-<n>.<m>`,`<m>` 是会话序号;断言 5 的"每批次一个 commit"按会话读。会话内因人工裁决而分成两段的,两段各自提交(裁决前一次、裁决入库后一次),tag 打在最后一次。**未提交的会话产物不得留给下一会话**:若发现上一会话未提交,本会话开工前先定归属——补打它自己的 tag,或在本次 commit message 里写明它随本次入库(`batch-e2.1` 即属后者)。
12. **人工裁决文件一经填写即归用户所有,机器会话只读**:导出草稿的工具必须能识别"已填写"并跳过覆写(`tools/splice_judge.py` 的 `is_ruled` 是现成写法),门禁断言裁决处于已填写状态。这一条覆盖 `reviews/` 之外的裁决文件(如 `docs/eval/results_e2/splice_manual_review.json`)。
13. **门禁通篇不引用任何 debug_id**:debug_id 每次运行重新分配,同一段落在不同运行里带不同的 id,锚定它的断言只对造出它的那次运行成立。段落一律用页内序号(`p<页>#<序>`)或文本本身锚定。本批(b10.4)起生效,新老门禁一体适用。
14. **批内修正案(PLAN_..._REV2)是合法手段,受三条件约束**。本周期五个批次里有四个由一份写在树上的修正案取代初版计划,该做法就此成为先例,边界是:(a) **前提差异先于修正**——修正案必须由一次对当前树的实测触发,并把实测表写进修正案本身;§5.2 的"事实与 PLAN 前提不符即停止并报告"是它的前置,修正案是那份报告之后的合法续作,不是绕过它的路;(b) **原件留档**——被取代的计划留在 `plans/` 内并在文首标注作废与作废理由,删除原件会让"这个批次一直就是这么计划的"成为可能的读法;(c) **只收窄或重指,不放宽**——修正案改的是"要断什么"而不是"阈值取多少",任何为使计划预期的数字成立而改动的旋钮一律禁止。断言层面的收窄/扩写/重指按 `docs/reports/assertion_contracts.md` 登记。
