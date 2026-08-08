# PLAN B5 — 链级联合翻译与句边界回填(3 会话)

前置:batch-b4.2。本批次首次修改上游翻译路径文件 il_translator_llm_only.py(项目至今唯一的译路径改动,逐处登记);B1 字段 segmentSentenceStart/End 的第一个写入方。

## 目标

被 chainId 标记的跨页语义单元作为一个整体翻译,译文按句边界拆回各成员 box,使"句中翻页"在译文侧不可能出现;全程受守恒不变量看守。

## 核心语义

1. **合并**:同链成员按 chainIndex 序拼接原文(成员间以空格/无缝连接,按尾行悬断形态定,参数化)。
2. **翻译**:合并文本作为单一单元进入既有翻译调用(享受既有 glossary/上下文机制)。
3. **回填**:
   - body 链:译文按目标语句边界集(configs 声明,中英各一套:。!?…!?. 等+收尾引号)切分,句子按成员原文字符占比贪心分派,切点只落句边界;句数 < 成员数时余量成员按字符比例切并记 `fallback=proportional`。
   - title 链:无句边界,按成员原文长度比例切,切点吸附到目标语的合法断点(中文任意字符间,英文词边界)。
   - 每成员写 segmentSentenceStart/End(title 链记 -1/-1 加 sidecar 说明)。
4. **守恒不变量(硬)**:join(成员译文) == 链整体译文,逐字节;成员数、段落数、页数不变。
5. **单一执法点**:链成员段落对 process_cross_page_paragraph 不可见(跳过),该跳过必须有 sidecar 记录;未成链边界旧机制不变。
6. **豁免通道**:成员含公式/样式占位符的链不合并,走旧路径,sidecar 记 `escalated=placeholder_bearing`;翻译计数守恒:链总数 == 合并翻译数 + 豁免数。

## 任务

- **T5.1(会话一,纯函数层,零上游)**:`babeldoc/magazine/chain_backfill.py` —— merge_chain_text / split_sentences(声明式终止符集)/ redistribute(body/title 两策略)/ 守恒校验函数;`configs/chain_translation.json`(终止符集、连接策略、比例参数,带 allowed_range);穷举合成用例门禁(含:句数<成员数、单句跨三成员、中英双向、空成员拒绝)。
- **T5.2(会话二,译路径接入)**:il_translator_llm_only.py 挂接——开关 `magazine_chain_translate: bool = False`;链收集(按 chainId 分组、chainIndex 排序、跨 part 链已被 B4 丢弃故不出现)、合并送翻、回填写回、segment 字段写入、跳过标记;UPSTREAM_DIFF 逐函数登记。桩翻译器(确定性假译,保留句结构)驱动全部守恒门禁:字符串等式、计数守恒、默认关闭零差异、单一执法点(桩断言旧配对函数对链成员零调用)。
- **T5.3(会话三,真实冒烟+排版验收)**:真实 API 对 Courier(7→8 body 链、2→3 title 链)与全语料跑通;渲染后验收指标:**链成员尾框末行以句末标点或成员内延续收束(零句中翻页,几何可验证)**;长度失衡由既有缩放/扩展吸收,溢出进 escalation;报告:译文质量人工抽查表、与官方中文版该段落对照(Courier 平行语料首次实战)。

## 门禁要点(spec_check_b5)

正向:合成用例全谱;桩驱动全语料——join 等式逐链断言、chain 总数 == 合并 + 豁免、segment 区间无重叠无空洞覆盖 [0, 句数)、跳过记录与链成员一一对应;开关关闭产物与 batch-b4.2 逐位一致。
负向:非链段落译文与开关关闭时逐字节相同(链机制零外溢);上游改动 ⊆ {il_translator_llm_only.py, translation_config.py, high_level.py 如需};代码零页型名;无 API key 全绿(真实冒烟仅报告);注释无中文。

## 明确不做

文章归组与文章级上下文(B6);folio 信号(B4 待办);spread 切分;不改 Typesetting(长度差交给既有机制,不足处走 escalation 记录)。
