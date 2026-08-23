> **作废(SUPERSEDED)** —— 本文件由 `plans/PLAN_B11_5_REV2.md` 取代,留档不执行。
>
> **作废理由**:前提校验第 4 条为伪。实测三档 checkpoint(06/07/08 一致)显示
> p8#9 为三段 composition —— `W`(GTFlexaMono-Thin 39.36)+ `hen `(**pdf_formula**,
> LyonText 9.25)+ 正文;请求文本实为 `<style id='1'>W</style>{v3}it comes…`,带一个
> 公式占位符。`flatten` 之拒发生在 `drop_cap.py:746-747`(`tail_kind == pdf_formula
> ∉ _MERGEABLE`),那是 `drop_cap.py:147-151` 的**明文守卫**,不是"缺一个归一分支"。
> 本文件 T2 的修法在该守卫之前到不了;即便提前,`{v3}` 仍原样还原 `hen `,渲染成
> `当hen 涉及…` —— **本文件自己的门禁断言 3 因此不可满足**。差异报告见
> `examples/output/b11_5/premise_check.json`;§5.14(b) 要求原件留档并在文首标注,
> 此段即该标注。
>
> 另:本文件前提 5 的行号 `typesetting.py:1361` 亦为误,实为 1462-1463。

# PLAN B11.5 — F&D 词表钉住、段内首字风格归一、首行缩进策略、masthead 收尾

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
3. b11.4 FD 在案：`drop_cap.report.json` 候选 `BpaLV`（p8#9，first_run "W"，
   size_ratio 4.255，段内风格 run 非独立段）；`drop_cap_apply` 裁定
   `flatten`（source: ruled，default 亦 flatten）而 `characters_merged: 0`；
   输出 p8 有 39.4pt 的 `当`（坐标 ~376,74.7）与首行旁 28pt 竖向空洞（首行
   y≈109，次行 y≈150.7）。
4. `drop_cap.py` 的 flatten 路径与 `merged_style` 逻辑：仅覆盖"独立段落合并"
   情形；段内大字号风格 run 无归一分支（核实行号）。
5. `paragraph_finder.py:160` 一带：`first_line_indent` 由源几何逐段推断；
   `typesetting.py:1361` 一带消费之（+`space_width*4`）；无任何全局控制。
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

## T2 — flatten 对段内首字风格 run 的归一

**缺陷**：flatten 只会合并独立段落；候选首字是段内风格 run 时
`characters_merged: 0` 静默通过，4.255 倍字号的 run 存活进翻译请求
（`<style id='1'>W</style>hen…`），模型跨占位符映射（`当` 入大字号 style），
排版渲染出中文下沉与错形留白。**内容无损**（当+涉及国际贸易时=完整译文），
缺陷是纯排版层。

**修法**（`drop_cap.py` flatten 分支，magazine 侧零上游）：候选 first_run 为
段内风格 run 且裁定为 flatten 时，把该 run 的 style 归一为段 body style
（复用独立段落情形的 `merged_style` 取法），盒几何按 b10.1 T1 的规则收到正文
（起排边取 tail）。归一后该段为单一风格 → 请求无占位符 → 译文全程正文字号。
sidecar 记 `run_style_normalized: true` 与前后 style 摘要。

**守卫**：仅作用于 `decision == flatten` 的候选；`keep` 裁定不动（保留下沉是
合法选项，风格 run 正是它的实现载体）。

## T3 — 首行缩进策略 pass

新 pass `babeldoc/magazine/indent_policy.py` + `configs/indent_policy.json` +
开关 `magazine_indent_policy`（默认关，标准 run config 显式开；房规）。窗口：
翻译之后、Typesetting 之前（与 paren_dedup 同窗）。

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
3. **T2**：p8#9 无 >15pt 字形；行距均匀（首行与次行 y 差 ≤ 1.5 行高）；提取
   文本以 `当涉及国际贸易` 起头（内容完整的直接证明）；sidecar 含
   `run_style_normalized`；构造 `keep` 裁定桩，断言不归一（守卫负向）。
4. **T3**：FD 各 body 段 `first_line_indent` 全真（zh:all 的直接后果）；标
   题/图注/masthead 列表段全假（作用面负向）；开关关则逐字节回落现状（回落
   负向）；p8 正文首段渲染有缩进（像素）。
5. **T4**：两条裁定消费落字；`2communiqué` 保持原文（或按裁定）；三条 gap
   登记在册。
6. **守恒**：九页、段数、`pN#k` 同基线；detector 计数不升；`api_calls` = 归
   因行数；产物 < 1 GB。

## 负向范围

改动 ⊆ {`babeldoc/magazine/drop_cap.py`、`babeldoc/magazine/indent_policy.py`
(新)、`configs/`、`reviews/FD-en-v2.decisions.json`（terms 增量）、
`spec_checks/`（新门禁 + check_06d 重指 + check_00b 转记）、
`docs/eval/gap_register.md`、`WAIVERS.md`、本文件、
`examples/output/b11_5/`}。上游零改动；`prompts/` 不动一字；`corpus/` 只读。

## 明确不做

漂移检测的通用机制（只落第一例与登记）；收割形状规则扩展；窄盒竖条的修法；
`corner_mark`；GAP-33；b11.2 未竟的暴露面探测与页内跨栏测量（仍候批）；
磁盘清理（仓外）。

执行序：T1 → T2 → T3 → T5 → T4（暂停裁定）→ 跑 FD → 门禁。单 commit，
tag `b11.5`（裁决后打）。交付报告须含：T1 落点论证、T2 前后 style 摘要与像
素对照、T3 作用面清单、T4 裁定记录、遗留红处置、§Cost 实测。
