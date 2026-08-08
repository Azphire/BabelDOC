# PLAN B4 — 文章链检测:跨页段落延续性判定与 chainId 写入(2 会话)

前置:batch-b3.3;Courier#3 真值修订已提交;VLM 消融关账(enabled=false 保持)。本批次是 B1 段落级字段(chainId/chainIndex)的**第一个写入方**;不触碰翻译路径(链级联合翻译属 B5)。

## 设计原则(来自两层 IR 裁定)

Article IR(段落级)权威,Page IR(页面级)只供软先验:链接判定由段落级延续性证据主导,pageKind 经 policy 标志以有界权重参与,证据与先验冲突时证据赢。错判的失败模式必须是优雅降级:少连 = 退回上游逐页现状;错连由负向真值边界看守。

## 任务

### T4.0 授权维护(会话一开始)

1. 提交用户的真值修订:page_labels.json(Courier#3 → 双标签)+ corpus/page_labels.CHANGELOG.md,单独 commit "truth: Courier#3 dual-label revision (user adjudicated)"。
2. CLAUDE.md §2 追加(原文照录):「两层 IR 原则:Article IR(段落级 chainId)权威规定统一翻译边界;Page IR(pageKind→policy)只提供排版/修复策略与链构建软先验,冲突时段落级证据优先。」「VLM 兜底消融关账:四档模型均无 policy 级增益,enabled 保持 false;基础设施保留,待区域语义或分布漂移场景重启评估。」
3. 复跑 spec_check_b2 确认 06c 在修订后真值下仍 ≥ 0.7(确定性层该页判 photo_spread,本在数组内,预期不变)。

### T4.1 边界真值机制(用户文件,与 registry 同族)

`corpus/chain_labels.user.json`(仅用户编辑,机器只读;门禁断言无写入方):

```json
{ "Courier-en.pdf": { "7->8": {"link": true,  "note": "mid-sentence split, biopiracy article"},
                      "1->2": {"link": false, "note": "toc/editorial -> opener"} } }
```

键为 1-based 相邻页对;缺席 = 未标注不计分。校验:页对相邻且在页数范围内、link 为布尔。`corpus_check` 纳入三重校验同款纪律。

### T4.2 延续性信号与配置

`configs/chain_detection.json`(全部带 _allowed_range):信号权重 + `link_min_score` + 辅助参数。信号(`babeldoc/magazine/chain_signals.py`,逐信号纯函数):

1. `tail_no_terminal_punct` — 尾段末行不以句末标点集结尾(标点集含中英:。!?.!?… 及收尾引号,进 configs)
2. `tail_line_fill` — 尾段末行宽 / 所在栏宽 ≥ 阈值
3. `style_continuity` — 尾/头段字号差 ≤ 容差且字体族一致
4. `body_label_pair` — 两段 layout_label 均属正文白名单(白名单进 configs,与译路径一致:text/plain text/paragraph_hybrid)
5. `column_position` — 尾段位于页 N 末栏底部带、头段位于页 N+1 首栏顶部带(带宽参数化)
6. `opener_prior`(负向)— 页 N+1 的 policy `starts_article` 为 true 时按 `pageKindConf` 加权扣分

硬性资格掩码(非评分):两页 policy `chain_eligible` 必须均为 true,否则边界直接不评。得分 ≥ `link_min_score` 判连。

policy 扩展:page_types.json 每型 policy 增第四键 `starts_article`(布尔);taxonomy 校验器接受该键,缺省按 false(后向兼容,15 型现场补齐声明)。

### T4.3 链构建与 IL 写入

`babeldoc/magazine/chain_builder.py`:相邻页边界逐一评分 → 判连边界的(尾段,头段)传递闭包成链 → 链成员写 `chain_id`(与 debug_id 同族 base58)、`chain_index`(0 起连续)。挂接 `_do_translate_single`:PageClassifier 之后,开关 `magazine_chain_detect: bool = False`(上游改动:high_level.py + translation_config.py,登记 UPSTREAM_DIFF.md)。sidecar `chain_report.json`:逐边界信号向量、得分、判定、资格掩码结果;checkpoint 序号顺延占位。split_manager 激活且链跨 part 边界时:放弃该链接并在 sidecar 记 `dropped_reason=split_boundary`(保守降级;chain-aware 切分属 B5)。

### T4.4 审阅报告工具

`tools/chain_report.py`:逐边界渲染尾/头段文本摘录 + 信号值 + 判定,单文件 HTML 至 examples/output/b4/——既是你标注 chain_labels 的底稿,也是阈值调参界面(改 configs → 重跑,零代码)。

## 门禁 `spec_checks/spec_check_b4.py`

正向:1) 开关开启对全语料:chainId 仅出现在判连边界成员段,chainIndex 逐链 0..k 连续,同链成员页号相邻;2) 守恒:页数/段落数/既有属性与关闭时逐位一致(仅新增两属性);3) 资格掩码:构造 chain_eligible=false 页的合成用例,边界不评分;4) starts_article 先验:合成强证据 vs 先验冲突用例,证据赢(权重结构断言);5) chain_labels 非空时,已标注边界的判定一致率 ≥ `boundary_agreement_min`(configs,默认 0.8,可 SKIPPED);6) 确定性:两次运行 chainId 集合结构同构(id 值可异,成员划分与序相同);7) run_all 全绿。

负向:8) 开关默认 False:全部 checkpoint 段落级六字段零命中(b2_2 门禁 09 语义延续),产物与基线 render_diff 退出 0;9) 代码零页型名(先验仅经 starts_article 标志);10) spec_check_b1 消费者白名单登记 chain_builder/chain_signals;11) 改动 ⊆ {babeldoc/magazine/*, configs/*, tools/*, spec_checks/*, corpus/chain_labels.user.json(仅用户), CLAUDE.md, plans/PLAN_B4.md, high_level.py, translation_config.py};上游仅限点名两文件;注释无中文;无 API key。

## 会话切分

会话一:T4.0–T4.3 + 门禁 1/2/3/4/6/8–11。会话二:T4.4 + 用户标注后门禁 5 生效 + 阈值按报告工具人工/受限调参 + 全量收尾。

## 会话二执行记录(b4.2,用户裁决的三项机制授权)

授权(与上文冲突处以此为准):(一)资格掩码按端点语义,article_opener 的 `chain_eligible` 改 true,其"首端点非延续"由 `starts_article` 负向信号看守;(二)端点候选须满足自身宽度 ≥ 页宽 × `chain_endpoint_min_width_ratio`(新参数);(三)`configs/chain_detection.json` 新增 `pair_classes`:声明端点类(标签集合)、允许的配对、各配对的权重档,代码只消费声明。

调参轮次(每轮守卫:24 个负边界零误连,新增假阳性立即回退):

| 轮 | 改动 | 动机 | 26 边界结果 |
| --- | --- | --- | --- |
| 1 | 三项机制按授权默认值落地(宽度比 0.12;title 档 0.45/0/0.45/0/0.1;权重与阈值沿用 b4.1) | 装机制,先量后调 | 23/26。假阳性 1:Courier 5->6(0.750,随 opener 解除掩码而暴露);漏检 2:2->3(头端点 photo_spread 不合格)、7->8(尾端点选到作者栏,页宽占比 0.140) |
| 2 | `chain_endpoint_min_width_ratio` 0.12 → 0.19 | 0.12 排不掉作者栏(0.140)与署名标题(0.178);0.19 位于它们与最窄正文栏(0.209)之间 | 24/26。7->8 尾端点回到正文末段("…a composite material from"),0.950 判连;负边界无变化 |
| 3 | photo_spread policy:`chain_eligible` false→true、`starts_article` true→false | 2->3 是跨版切断的显示标题,落页被判 photo_spread;端点语义下掩码只应排除确无流动文本的页,且图版页不是文章起点 | 25/26。2->3 经 title->title 判连 0.950;新可评的 3->4 停在 0.500 |
| 4 | `link_min_score` 0.55 → 0.80,`weight_opener_prior` -0.35 → -0.15 | 仅剩 5->6(0.750)对两条真边界(0.950),阈值须落在两者之间;载入器的软先验守卫随之要求先验不强于 -0.20 | 26/26,零假阳性 |
| 5 | 权重:punct 0.30→0.25、fill 0.20→0.15、style 0.20→0.35、body 0.20→0.15 | 第 4 轮最强负边界距阈值仅 0.05;区分 5->6 与 7->8 的正是 style_continuity(前者接引言字号不同,后者接同字号正文),把权重移过去以拉开裕度 | 26/26,零假阳性;最强负边界 0.600,最弱正边界 0.950 |

达标即停(两正样本判连、零假阳性、裕度 0.20/0.15)。门禁 5 生效:agreement 26/26 ≥ `boundary_agreement_min` 0.8。新增门禁 12(宽度过滤)、13(配对类与权重档)、14(Courier 7->8 尾端点为正文段的实例断言)。

已知边界(非本批缺陷):CERN 拼版页内部的续流(issue p24 第 3 栏 → p25 第 1 栏落在同一 PDF 页)对页边界链接不可见,属 spread 切分待办。

## 明确不做

不动翻译路径(B5);不做整文章页面归组;不做 chain-aware split(B5);不消费 segmentSentenceStart/End(B5 回填时写)。
