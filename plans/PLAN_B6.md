# PLAN B6 — 文章归组与文章级翻译上下文(2 会话)

前置:batch-b5.3。两层定位:B5 的链解决"切断"(排版刚性),本批次解决"连贯"(内容软性)——风格/术语/指代跨页一致,机制是共享上下文,不是巨型调用。

## T6.0 授权维护(会话一先行)

1. UPSTREAM_DIFF.md 补 coupling 两行:chain_translation.py 依赖 il_translator.pre_translate_paragraph / post_translate_paragraph。
2. 链 token 预算豁免:chain_translation.py 送翻前按合并文本估算输出 token(估算系数进 configs/chain_translation.json,带 allowed_range),超 max_tokens 预算即整链 `escalated=token_budget` 走旧路径;spec_check_b5 加对应合成断言(超长链被豁免而非截断)。
3. check_12_switch_on docstring 按 b5.3 实测修正措辞(断言本体不动)。
4. CLAUDE.md §2 追加(原文照录):「评估协议:A/B 对比以缓存冻结重放为准;模型采样方差(gpt-4o temp=0 实测非确定)为已知局限;显著性主张需三跑设计。」

## 任务

### T6.1 文章归组(会话一)

`babeldoc/magazine/article_builder.py` + sidecar `article_map.json`:

- 边界规则(全确定性):policy `starts_article=true` 的页开启新文章;其后页顺序归属,直到下一个起点;chainId 跨越拟定边界时合并两侧(链是"同文章"最强证据,优先级高于先验——两层 IR 原则的再次实例化);`translate=false` 或 `chain_eligible=false` 且非起点的页(广告/刊头等)标记为 unassigned,不断开其两侧归属(文章可隔广告页续)。
- 每篇文章记录:article_id(base58)、成员页序列、标题段引用(起点页上首个 title 类段落,标签集复用 chain_detection.json 的 pair_classes 声明——零字面量)、成员段落 id 清单。
- TOC 对照(报告项):toc 页(policy 声明,经现有机制)解析出的条目数与检出文章数并排呈报,不做判定。
- 挂接:chain_builder 之后,开关 `magazine_article_group: bool = False`。
- 门禁:每页恰属一篇或 unassigned;链永不跨文章;合成用例(隔广告续文、双起点连排、无起点文档整体成一篇);默认关闭零差异;确定性。

### T6.2 文章级上下文注入(会话二)

- **Article brief**:开关 `magazine_article_context` 开启时,每篇文章翻译前一次 LLM 调用生成简报(prompts/article_brief.md:输入 = 标题段原文 + 首成员页正文首段;输出 = 严格 JSON:译名建议的标题、语域一句话、人名/机构名清单)。brief 经缓存客户端模式调用(key 含 prompt 哈希),失败则该文章无 brief 照常翻译(优雅降级,sidecar 记录)。
- **注入**:该文章全部段落批(含链)的上下文槽携带 brief 文本;实现复用既有 title 上下文通道,上游改动最小化并逐函数登记。同时兑现 B5 遗留:链与段落的"最近标题"扫描按 title 类标签集实现,作用域收窄为本文章内。
- **术语一致率指标**(报告,非门禁):tools/term_consistency.py——文章内重复出现(≥ 阈值次)的源词条,其译文的一致率;与 glossary 命中情况并列;对全语料出双模式对照表(brief 开/关)。
- 门禁:桩 LLM 驱动——brief 生成一次/文章(计数)、成员批 prompt 含 brief(桩记录 prompt 断言)、非成员批不含、brief 失败降级留痕、默认关闭产物与 batch-b6.1 逐位一致;无 API key 全绿。
- 真实冒烟(报告):Courier 全开关翻译,brief 内容、术语一致率双模式对照、与 b5.3 译版的 diff 观察。

## 门禁负向(两会话共通)

上游改动 ⊆ {il_translator_llm_only.py, translation_config.py, high_level.py};代码零页型名零标签字面量(标签集只经 configs);article_map 不进 IL(schema 冻结,机器只写 sidecar);brief 不写 glossary(单向消费,防止 LLM 输出污染术语权威源);注释无中文。

## 明确不做

滚动上下文(前文摘要随批注入——机制成本高,等术语一致率数据证明 brief 不足时再立项);articleId 进 schema(等 W-B1-01);语料刷新(独立批次,B6 后);HITL(独立线)。
