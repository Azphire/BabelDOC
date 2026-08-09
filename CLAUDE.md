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
- checkpoint 规范形式为再序列化形式(to_xml(from_xml(x)));字节级比对一律先归一化。读取旧 checkpoint 时容忍 xsdata ConverterWarning,不容忍错误(W-B0-02)。
- 两层 IR 原则:Article IR(段落级 chainId)权威规定统一翻译边界;Page IR(pageKind→policy)只提供排版/修复策略与链构建软先验,冲突时段落级证据优先。
- VLM 兜底消融关账:四档模型均无 policy 级增益,enabled 保持 false;基础设施保留,待区域语义或分布漂移场景重启评估。
- 评估协议:A/B 对比以缓存冻结重放为准;模型采样方差(gpt-4o temp=0 实测非确定)为已知局限;显著性主张需三跑设计。
- corpus/registry.user.json 是语料语义元数据的唯一权威,仅用户可编辑;机器会话从它重建 manifest,任何批次的 git diff 中出现 registry.user.json 即违规,除非当次 prompt 显式声明用户已更新登记。toc_pages 为 PDF 文件页序(1-based)中出现目录版面的页码列表,空列表表示节选不含目录页。page_labels.json 的值为可接受类型名数组(1-based 页号),机器判定命中数组任一元素即计为一致;多元素用于单页多版面(如目录与卷首语同版)与复合拼版页。

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

1. **注释一律英文**。注释只解释代码当前为何如此;**禁止变更日志式注释**(不写 changed/fixed/added for batch N,不留注释掉的旧代码)。改动理由写进 commit message 与 PLAN 文件。
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
