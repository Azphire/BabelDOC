# PLAN B8 — ReAct 检测修复循环(3 会话)

前置:batch-b7.5.2。承诺 3 兑现批次。需求证据:p6#15 fallback_line 未译残留(两次实测)、p1#9 裁决静默落空(界面正确性)、b2 线的碎段/重叠病灶史。

## 定位

排版后检测(IL 几何为主)→ 有界修复动作 → 增量重跑 → 复检,迭代上限 + 收敛守卫 + 动作日志。v1 唯一实动作 translate_orphan_lines;碎段/重叠检测器上线但 report-only。VLM 检测器插件与更多动作留后续批次。

## T8.0 授权维护(会话一先行)

1. configs/gate_cache.json:gate_cache_max_gb 8→16。
2. HITL 裁决命中告警:hitl apply 后每条 term 裁决记 matched_prompt_count 入 sidecar;为 0 时运行日志显式 WARN(裁决落空不再静默)。review sheet 的 terms 节为含占位符标记的段落补一列 translator_view(翻译器实收文本摘录)——人所见与机所匹配的错位在评审时即可见。各配断言。
3. examples/output/b7_2/drop_cap_candidates.md 移出 git 跟踪(sweep 重生成产物);b7_2 门禁允许清单同步。

## 任务

### T8.1(会话一):Issue 框架与确定性检测器

- Issue schema(sidecar issues.json):{id, kind, page, paragraph_refs, geometry, severity, evidence, detector, detected_at_iteration}。
- 检测器(babeldoc/magazine/detectors/,configs/detectors.json 带 allowed_range;按页 policy repair_profile 选择检测器组):
  a. untranslated_residue:目标语文档中,段落译文与源文相同、或目标语为 zh 时拉丁字符占比 ≥ 阈值(语言方向感知,阈值分向声明);fallback_line 类段落显式纳入扫描域(它们不经翻译,正是主病灶);
  b. fragment_cluster:相邻短段(长度 ≤ 阈值)同 style、行距连续、数量 ≥ 阈值 → 合并候选簇(report-only);
  c. text_figure_overlap:段落 box × figure/xobject box IoU ≥ 阈值(report-only);
  d. escalation_surfacing:链翻译 sidecar 的 escalated 项(token_budget/placeholder_bearing/conservation_failure)提升为 issue(检测器只是搬运,零新逻辑)。
- 挂接:Typesetting 之后、PDFCreater 之前,开关 magazine_detect(默认 False);checkpoint/sidecar 照旧。
- 门禁:合成用例逐检测器(阳性/阴性/阈值边界);默认关零差异;真实语料检测报告(p6#15 必须被 a 检出——活证据断言);确定性;代码零页型名(profile 经 policy)。

### T8.2(会话二):控制器与 translate_orphan_lines

- configs/repair_actions.json:动作词表声明(name、适用 issue kind、参数及边界、max_applications);v1 仅 translate_orphan_lines(参数:每次迭代最多处理段数,默认上限进 configs)。
- prompts/react_repair_decide.md:输入 issues 摘要 + 动作词表,输出严格 JSON 的动作选择与界内参数;经缓存客户端;越界/非法输出重试一次后放弃该迭代(保守:不修优于乱修)。
- 执行 translate_orphan_lines:选中段落以纯文本 + 页面上下文送翻(复用翻译器与 glossary 通道——裁决词条自然可达,p6#15 的刊名统一由此闭环);译文写回段落,重排该页(复用增量重排既有设施),复检。
- 循环守卫:迭代上限(configs,默认 3);收敛判据 issue 总数严格递减,否则回滚本迭代并终止;动作日志(逐迭代:检出集、决策原文、执行集、复检差分)入 sidecar;守恒:页数/段数不变,未触碰段落译文逐字节不变(负向断言)。
- 门禁:桩 LLM 全谱(合法/越界/坏 JSON/拒绝);守卫触发合成用例(注入不收敛桩,断言回滚+终止);默认关零差异;无 API key 全绿。

### T8.3(会话三):真实冒烟与承诺 3 证据组

全栈 + magazine_detect + 修复开启,Courier-en 真实运行:p6#15 检出 → 决策 → 送翻 → 刊名 6/6 统一的前后对照(承诺 1+3 的交汇证据);全语料检测报告(碎段/重叠 report-only 清单——B8 后续批次的病灶普查);迭代与收敛实录;与 batch-b7.5.2 译版 diff 的爆炸半径核对。报告 examples/output/b8/。

## 负向(共通)

上游改动 ⊆ {high_level.py, translation_config.py 挂接}(逐函数登记);修复永不触碰源 IL 几何之外的既有译文(白名单段落之外逐字节不变);prompt 零内联;真值/裁决只读;注释无中文;门禁无 API key。

## 明确不做

fragment/overlap 的实动作;VLM 检测器;多模态 critic;zh 校准;Typesetting 算法改动。
