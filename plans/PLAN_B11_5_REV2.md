# PLAN B11.5 rev2 — F&D 词表钉住、首字放大邻接的角标豁免、首行缩进策略、masthead 收尾

本文件**取代** PLAN_B11_5 初版。初版前提 4 为伪：p8#9 在 stage-06 即为三段
composition（W 39.36 / hen 为 pdf_formula / 正文），请求实为
`<style id='1'>W</style>{v3}it comes…`；`hen` 由角标规则假阳吞入
（`styles_and_formulas.py:471-505`，9.25 < 39.36×0.79，状态分支携走 e/n），
flatten 之拒是 `drop_cap.py:147-151` **明文守卫**（tail 为 formula 不并），
不是"缺归一分支"。初版 T2 照写不可达（守卫前置归一只去 style span，`{v3}`
仍原样还原 hen，渲染为 `当hen涉及…`，门禁 3 不可满足）。rev2 依 b11.5 前提
差异报告重写 T2；初版留档，此段即作废记录。两笔计划层错误自记入报告：机制
叙述在证据不足处补位（`characters_merged: 0` → 臆造"缺分支"）；对用户答复
中"内容没丢、hen 系误读"为错——`{v3}` 还原的 `hen` 实际渲染于 y=87.84，
用户的原始读法正确。

前置：batch tag `b11.4`。规格即当次 prompt，本文件是其归档。单臂默认适用。
验证范围：FD-en-v2 单样张（四项修法的证据面全部在 FD）；T2/T3 为全语料行为
变更，其跨样张回归债记入 §W 并入既有未结清账（与 b11.1 同款处置）。
含一个**微型人在环节点**（T4，两条音译候选裁定）。

## 前提校验（任一不符即停，逐条记行号）

1. b11.4 FD 在案：`short_unit` 五处 `F&D → 财政与发展`、`identity_skipped:
   false`（p3#0、p5#3、p6#1、p7#1、p8#1）；GAP-36 的成因链（`.*Mono` 移除 →
   批重采样）在 gap register。
2. `reviews/FD-en-v2.decisions.json` 现含 `Masthead → 报头`（b11.4 T5）；词表
   优先于策略的条款在三档角色文本明文（b10.4）。
3. b11.4 FD 在案：候选 `BpaLV`（p8#9）、裁定 flatten（ruled）、
   `characters_merged: 0`；输出 p8 有 39.36pt `当` @ [376.0,74.74,…]、
   **游离 `hen` @ y=87.84**、首行 y=109.36 / 次行 y=150.69（行高 13.87，空洞
   27.5pt）。
4. **（rev2 更正）**stage-06/07/08 一致：p8#9 = 三段 composition——
   `W`（GTFlexaMono-Thin 39.36）+ `hen`（**pdf_formula**，LyonText 9.25，
   curves 0 / forms 0）+ 正文（LyonText 9.25）；请求文本
   `<style id='1'>W</style>{v3}it comes…`。角标成因：
   `styles_and_formulas.py:471-505`，`is_corner_mark` 因 9.25 < 39.36×0.79
   触发，状态分支（9.25 < 9.25×1.1）吞入 e/n，尾随空格随
   `in_formula_state` 携走；该处注释自称"同时考虑首字母放大的情况"。
   flatten 之拒为 `drop_cap.py:147-151` / :744-747 的明文守卫
   （tail_kind == pdf_formula ∉ _MERGEABLE）。
5. `paragraph_finder.py:160-170` 推断 `first_line_indent`；消费端
   `typesetting.py:1462-1463`（初版行号 1361 为误）。magazine 侧已有两处写
   该字段：`title_typeset.py:816`、`line_split.py:705`——T3 的 pass 须与两
   者明确共存序（见 T3 附注），"无任何全局控制"仅指无策略级开关。
6. `name_harvest.report.json`（b11.4 FD）：`Huong (Vanessa) Le` /
   `S M Ali Abbas` / `2communiqué` 三条 `person_shaped: false`；
   `Ali Abbas → 阿里·阿巴斯` 子串条目在库。
7. b11.4 遗留红：`run_all` 41/43；`spec_check_b11_2` 30/32（`check_00b` 对照
   件被 prune 永久丢失；`check_06d` 读冻结 PDF、经 §4.13 覆盖重跑后为真红，
   即 GAP-36 本体）。

## T1 — F&D 词表钉住（内容裁决在案：保留原文）

`reviews/FD-en-v2.decisions.json` terms 段加 keep 条目 `F&D → F&D`。落点论证
（写进报告）：不进 `formular_helper`——用公式标注实现"不译"是借名义达目的，
GAP-35 刚记过这种"标注错了但结果对了"的形态，不再新造一个；词表 keep 是为
此设计的通道，且命中后恒等短路（b11.1 T1）保源渲染，连字体不换。

**顺带修 b11.4 遗留红**（前提 7）：`check_06d` 从"读冻结 PDF"重指为"读当次
运行的衍生证据"（§4.16 规则），断言内容不变（三页 F&D 以源形渲染）——冻结
件防篡改、衍生件测漂移，两职分离即 GAP-36 的一般化结论落地第一例；
`check_00b` 对照件确证不可恢复，按 AC 先例转 SKIPPED-with-cause。

## T2 — 首字放大邻接的角标豁免（rev2 重指；按 §4.18/b11.3 序）

**范围声明**：本 T **不是** corner_mark 全类修复（b11.4 缓议的理由继续成立：
该分支同时命中真上标与小型大写正文）。修的只是一族自反讽假阳——注释自称
"考虑首字母放大"，而规则恰被首字母放大触发。

1. **豁免谓词，先冻结**（哈希钉住，spec 断言）：段首放大 run（首 run 且
   size_ratio ≥ `initial_adjacent_ratio`，默认 2.0，与 drop_cap 候选阈同源）
   之后 `initial_adjacent_chars`（默认 8，带范围）个字符内，`is_corner_mark`
   不成立。谓词只看几何与序，不看内容。
2. **离线测量**（b10.5 stage-06 checkpoint，受保护在盘，零 API）：数出全语
   料被该谓词改判的全部实例，逐条给页/段/字体/字号/文本；**双向复核**——
   改判者中有无真上标/真公式（有 → **停，登记，回落"砍 T2 记 gap"**）；
   b11.4 已计的 corner_mark 4 条与本族的交集单列。
3. **消费者清单本批新做**（§4.18，不得复用 b11.4 清单）：逐站点回答"这些
   composition 由 formula 改判为文本后会发生什么"；携带 pdf_form/pdf_curve
   者（预期 0，p8 实例已证 0/0）一律不改判并单列。
4. **修法**：`styles_and_formulas.py` 单谓词修正（上游一处，UPSTREAM_DIFF
   逐函数登记）；配置键入 `configs/`（带范围）。
5. **贯通链自然发生，不另写代码**：hen 回归文本 → tail ∈ _MERGEABLE →
   flatten 守卫放行 → W 并入正文、`merged_style` 归一 → 请求为纯文本
   `When it comes…`。sidecar 断言 `characters_merged ≥ 1`。

## T3 — 首行缩进策略 pass

新 pass `babeldoc/magazine/indent_policy.py` + `configs/indent_policy.json` +
开关 `magazine_indent_policy`（默认关，标准 run config 显式开；房规）。窗口：
翻译之后、Typesetting 之前（与 paren_dedup 同窗）。

- 共存序附注（前提 5 更正的后果）：`line_split.py:705` 在译前写该字段，本
  pass 在译后覆写（本 pass 赢，记入 config 描述）；`title_typeset.py:816` 在
  排版后写、且只及 title 类——与本 pass 作用面（body 类）不相交，互不覆盖，
  spec 各取一例断言。
- 词表 `indent_mode ∈ {source, all, none, all_but_first}`；按目标语言映射
  （`indent_mode_by_target`，匹配规则同既有 by_target 惯例）。本批声明
  `zh: all`（用户裁决：中文默认全缩进）；`source` 为无映射时的回落（行为等
  同现状）。
- `indent_em` 旋钮（默认 4 半角宽 = 现行为，带范围）。
- 作用面：body 类 layout_label（清单入 config）；标题、图注、目录记录、
  masthead 列表不动。`all_but_first` 的"首段"以 article_map 的段序为准。
- 实现：覆写 `paragraph.first_line_indent`，消费端（上游 typesetting）零改动。

## T4 — masthead 两条人名 + 一条品牌裁定（微型人在环）

1. 以既有音译 prompt 为 `Huong (Vanessa) Le` 与 `S M Ali Abbas` 生成候选
   （含缩写与括号昵称的完整形，如 `S·M·阿里·阿巴斯` 形），写入草案，**暂停
   由用户裁定两条**（改写或 keep 均可），apply 后进词表。
2. `2communiqué` **默认不动**（品牌，保留原文为正确行为）；用户若在裁定时要
   求翻译，按裁定执行。
3. 三个收割形状盲区（括号昵称、单字母缩写、数字开头）登记 gap，不扩规则。

## T5 — 观察登记（零改动）

1. GAP-36 一般化：冻结件防篡改、不测漂移；本项目多条断言属此形态，T1 重指
   `check_06d` 为第一例，其余逐条迁移登记为缺口（不在本批做）。
2. p5 `Natalia Venegas Figueroa` 音译后一字一行竖条（窄盒换行）——新观察，
   记页/段/盒宽证据，归"译文长于源致盒溢出"族，与 GAP 既有条目并案与否由
   register 编辑时定。
3. 磁盘 99%（5.8 GB 余）：仓外 506 GB 非本项目所辖，记入报告提醒用户；本批
   产物预算 < 1 GB，超预算即停。

## §Cost 与验证

- T1/T4 改词表 → 命中批重采样；T2 改 drop-cap 段请求文本（去占位符）→ 该批
  重采样。预估数十次调用，归因行对账。
- 跑 FD-en-v2 on 臂一次（T4 裁定后），完整 PDF + 九页 PNG 入库
  `examples/output/b11_5/FD-en-v2/`。
- T2/T3 的跨样张回归债记 W-B11-12（并入 b11.1 未结清账，措辞同款：下一次多
  样张跑到期结清）。

## 门禁 `spec_check_b11_5.py`（fast）

1. **T1 像素+机制**：p3/p5/p6/p8 的 `F&D` 以源字形渲染（无 `财政与发展` 于
   页眉区；提取文本页眉区含 `F&D`）；`short_unit` 记录 `translated == "F&D"`
   且 `identity_skipped: true`；词表条目哈希入 run.json。
2. **T1 遗留红**：`check_06d` 重指后在当次证据上为真；`check_00b` 转
   SKIPPED-with-cause 且 AC 登记；`run_all --set fast` 全绿（43/43 或经登记
   的 SKIPPED）。
3. **T2**：豁免谓词哈希 = 报告记录值；测量表完备且双向复核在库；p8#9 无
   >15pt 字形；行距均匀（首行与次行 y 差 ≤ 1.5 行高）；提取文本以
   `当涉及国际贸易` 起头**且全页无游离 `hen`**（文本与像素双向）；
   `drop_cap_apply` 记 `characters_merged ≥ 1`；构造 `keep` 裁定桩断言不并
   （守卫负向）；改判实例所在其余段落 detector 计数不升。
4. **T3**：FD 各 body 段 `first_line_indent` 全真（zh:all 的直接后果）；标
   题/图注/masthead 列表段全假（作用面负向）；开关关则逐字节回落现状（回落
   负向）；p8 正文首段渲染有缩进（像素）。
5. **T4**：两条裁定消费落字；`2communiqué` 保持原文（或按裁定）；三条 gap
   登记在册。
6. **守恒**：九页、段数、`pN#k` 同基线；detector 计数不升；`api_calls` = 归
   因行数；产物 < 1 GB。

## 负向范围

改动 ⊆ {`babeldoc/format/pdf/document_il/midend/styles_and_formulas.py`
（仅 T2 单谓词，UPSTREAM_DIFF 登记）、`babeldoc/magazine/indent_policy.py`
(新)、`configs/`、`reviews/FD-en-v2.decisions.json`（terms 增量）、
`spec_checks/`（新门禁 + check_06d 重指 + check_00b 转记）、
`docs/eval/gap_register.md`、`WAIVERS.md`、本文件、
`examples/output/b11_5/`}。上游零改动；`prompts/` 不动一字；`corpus/` 只读。

## 明确不做

漂移检测的通用机制（只落第一例与登记）；收割形状规则扩展；窄盒竖条的修法；
**corner_mark 全类修复**（本批只做首字放大邻接豁免一族）；GAP-33；b11.2 未竟的暴露面探测与页内跨栏测量（仍候批）；
磁盘清理（仓外）。

执行序：T1 → T2 → T3 → T5 → T4（暂停裁定）→ 跑 FD → 门禁。单 commit，
tag `b11.5`（裁决后打）。交付报告须含：T1 落点论证、T2 前后 style 摘要与像
素对照、T3 作用面清单、T4 裁定记录、遗留红处置、§Cost 实测。
