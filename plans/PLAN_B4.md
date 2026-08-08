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

## 明确不做

不动翻译路径(B5);不做整文章页面归组;不做 chain-aware split(B5);不消费 segmentSentenceStart/End(B5 回填时写)。
