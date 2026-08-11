# PLAN B7 — HITL 两遍式裁决:术语 / 页型 / 下沉字(2 会话 + 用户回填后的冒烟微会话)

前置:batch-b6.3。承诺 1 的兑现批次;B1 剩余字段(dropCapCandidate/dropCapDecision、pageKindSource=human)的写入方。需求证据:b5.3(生物剽窃/spinifex 术语缺口)、b6.2(刊名跨文章翻转,issue 级家具需文档级裁决)。

## 设计原则

- **默认全自动**(CLAUDE.md §4.9):无裁决文件时流程与 batch-b6.3 逐位一致;裁决是可选覆盖层,任何裁决点都有机器默认。
- **用户主权**:`reviews/<sample>.decisions.json` 仅用户编辑;机器导出底稿 `reviews/<sample>.review.json`(+人读 HTML),读取定稿,校验严格(未知页号/非法页型名/畸形词条 → 逐条报错拒绝整份)。
- **单向注入**:裁决只流向运行时(user glossary / IL 覆盖),永不反写 registry、page_labels、词表。

## 任务

### T7.1(会话一):裁决单格式 + 术语与页型两通道

- **格式**:review.json 三节——terms(自动术语表逐条:source/auto_target/count/首现页)、page_kinds(逐页:machine_kind/conf/ambiguous)、drop_caps(会话二填充,先留空节)。decisions.json 同构三节,全部可选:terms 为 {source: target} 覆盖表(允许新增机器未抽到的词条——刊名类 issue 级家具的入口);page_kinds 为 {page: kind};drop_caps 为 {paragraph_ref: "keep"|"flatten"}。
- **导出**:开关 `magazine_hitl_export`(默认 False):AutomaticTermExtractor 之后导出 terms 节,PageClassifier 之后导出 page_kinds 节;流水线照常跑完(不阻塞)。
- **注入**:decisions.json 存在时(开关 `magazine_hitl_apply`,默认 False):
  - terms → 构造 user glossary 并入 translation_config 的 user_glossaries 通道。**前提复核**:user_glossaries 的消费时机与优先级(user 对 auto 的覆盖顺序),文件:行号证据;若 user 不能压过 auto,停止报告。
  - page_kinds → PageClassifier 判定后覆盖:pageKind=裁决值、pageKindConf=1.0、pageKindSource="human";下游(链/文章归组)自然消费覆盖后的 policy。
- 门禁(桩):两开关默认关零差异;导出节结构与内容断言;注入后合成断言——术语覆盖到达翻译输入(桩记录 glossary 命中)、页型覆盖翻转下游行为(合成用例:覆盖使某页 chain_eligible 翻转,边界评估行为随之变化)、source=human 写入;校验负向探针全谱;空 decisions 的第二遍与第一遍逐位一致(两遍式恒等断言)。

### T7.2(会话二):下沉字候选标记 + 裁决写回

- 候选信号(通用,configs/drop_cap.json 带 allowed_range):段落为其所属文章的首个 body 类段落(article_map 消费)或位于 opens_article 页;首字符样式 run 的字号 / 段落中位字号 ≥ 阈值;首 run 长度 ≤ 上限。命中写 dropCapCandidate=true(IL,B1 字段首写)。
- review.json 的 drop_caps 节填充:候选段落引用、首行摘录、字号比。
- decisions 注入:dropCapDecision 写入 IL("keep"/"flatten");**本批次无消费端,明确记录**(Typesetting 集成独立批次);机器默认 = 不写 decision(空值),流程零影响。
- 门禁:候选标记确定性、仅 body 类段落、默认关零差异、decision 写入与校验、b1 消费者白名单登记。

### T7.3(冒烟微会话,用户回填 decisions 后):真实两遍验证

用户对 Courier 填写 decisions(预期条目:biopiracy→生物剽窃、spinifex→鬣刺(或用户译法)、刊名统一译法、若干页型确认)。第二遍真实翻译(gpt-4o,缓存冻结对照第一遍):验证 b5.3 两处术语分歧消失、b6.2 刊名翻转消失、其余段落零意外扰动(diff 应集中于含裁决词条的段落);渲染件与四方对照表更新——承诺 1 的论文证据组。

## 负向(共通)

上游 ⊆ {high_level.py, translation_config.py, automatic_term_extractor 挂接点如需(逐函数登记)};decisions/review 文件机器只写 review 只读 decisions;代码零页型名;门禁无 API key;注释无中文。

## T7.1 执行裁决(会话一,前提复核后由用户裁定;与上文冲突处以本节为准)

前提复核发现:`get_glossaries_for_translation`(translation_config.py:130-140)
在 `auto_extract_glossary=True` 且自动术语表非空时只返回 `[auto]`,user
glossary 被整体丢弃,user 无法压过 auto。用户裁定走**方案 2(注入侧剔除
重建)**,不改上游选择规则:

1. decisions 的 terms 建为 user Glossary;auto glossary 非空时剔除与裁决
   source 重合的词条后重建(finalize 后的对象层面,`raw_extracted_terms`
   不碰);剔除清单(source / 被剔 auto_target / 生效 user_target)入
   sidecar。重建后的 auto glossary 一并移入 user glossary 列表、auto 槽
   置空——否则 auto=on 时裁决仍到不了 prompt(见 W-B7-01)。
2. 门禁在 auto=on 与 auto=off 两条桩路径各断言一次,两遍式恒等断言同样
   两种配置各一次。
3. review.json 的 terms 节字段为 source / auto_target / vote_count(抽取
   批次投票数)/ first_page(扩展侧扫 IL unicode 精确匹配,1-based);两
   字段的语义来源写入 `reviews/README.md`。
4. 上游挂接:`_do_translate_single` 两处调用(1003-1005 窗口的页型钩子、
   1029-1033 窗口的术语钩子)+ translation_config 两开关,逐函数登记。

## T7.2 执行裁决(会话二;与上文冲突处以本节为准)

1. **上游零改动**。本会话硬约束禁止任何上游新增改动,因此
   `magazine_drop_cap_mark` 不是 `TranslationConfig.__init__` 形参,而是
   配置对象上的属性(`getattr(..., False)`),由构造方设置;门禁与
   artifacts 通过 mode 的 `attributes` 项设置。登记为 W-B7-02。
2. **挂接点**:标记不新增 stage,复用既有 `hitl.after_term_extract`
   钩子(无条件、位于 ArticleBuilder 与译器构造之间),在同一钩子内
   完成"标记 → 导出 drop_caps 节 → 写裁决"。article_map.json 由该钩子
   读取,故 `magazine_article_group` 是硬依赖,缺失即 DropCapError。
3. **段落引用格式** `p<page>#<index>`(1-based 文件页 + 页内段落序号)。
   debug_id 每次运行重新生成,不能作为两遍式裁决的引用;未知引用在
   校验期整份拒绝。
4. **rank 阈值来自实测**:语料中三处真实首字下沉分别位于其文章的
   第 3/5/5 个 body 段(Courier p4 非开篇页、p5 与 p7 为开篇页),
   `max_body_rank_in_article` 取 5,使开篇页析取项不成为必要条件。
   字号比实测 6.67,阈值取 2.0(最近的假阳性为 1.43)。

## 明确不做

阻塞式交互;Typesetting 消费 dropCapDecision;裁决反写任何权威源;Web UI。
