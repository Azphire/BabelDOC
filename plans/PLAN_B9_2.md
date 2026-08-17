# PLAN B9.2 — 标题排版策略:单行禁换、禁缩进、缩放适配、幽灵层去重(2 会话)

前置:batch-b9.1。F1 缺陷 #3 的兑现批次。验收病例(F1 实景):AW-v2 p5 "铁路" 双重渲染+第二层源文擦除不净;CERN p1 封面标题换行溢出页外;Courier-en 多处标题换行(含词中断行)。

## 语义

title 类段落(标签集复用 configs/chain_detection.json 的 pair_classes title 声明,零字面量)的排版规则:

1. **单行**:禁止换行;缩放 = min(1, 框宽 / 单行自然宽),低于 `title_min_scale`(configs,带 allowed_range)时按 `on_floor` 策略处置(`wrap`(退回换行)| `escalate`(记 issue 不硬塞),默认 escalate);
2. **禁首行缩进**;
3. **幽灵层去重**:同页 title 段两两满足 bbox IoU ≥ 阈值 且 规范化文本相似度 ≥ 阈值(参数进 configs)→ 判定为同一显示单元的重叠层;仅主层(面积大者)翻译渲染,副层标 `duplicate_of` 跳过渲染,**两层源文均须擦除**;sidecar 记录去重对。

开关 `magazine_title_typeset`(默认 False,零差异断言)。

## 任务

### T9.2.1(会话一):前提复核 + 机制

前提复核(逐条文件:行号证据,不符即停):
a. 上游对"渲染段落时源文如何被擦除"的机制——跳过渲染的段落其源文是否仍被擦除?AW"第二层没消干净"的成因先定位再设计去重的擦除路径;
b. 单段强制单行的可行通道:render_paragraph / retypeset_with_precomputed_scale 是否支持给定 scale 下禁换行,或需 magazine 层自建单行铺设(B8.4 写回工具的延伸);
c. 首行缩进在 IL/排版中的承载(段属性还是排版期推断),关闭通道;
d. 标题链(2→3 类)成员本就各自单行,新策略与链回填的相互作用(回填后的成员文本再经单行缩放,顺序必须是回填先、缩放后)。

实现:magazine 后排版 pass(Typesetting 之后、detect 之前,与 B8 检测同窗口),按上述语义处理全部 title 段;合成用例门禁(超宽标题缩放/触底 escalate/缩进关闭/重叠层去重与双擦除/链成员回填后缩放次序);默认关零差异;守恒(段数不变、非 title 段逐字节不变)。

### T9.2.2(会话二):真实验收

全栈 + 新开关对五份英文样张真实运行(缓存大量命中,新增为标题重排零翻译成本):
- AW-v2 p5:单一"铁路"渲染、幽灵层去重记录、源文双擦除的**光栅证据**(b8.4 规矩:修复类证据必含像素检查);
- CERN p1:封面标题落在页框内(几何断言 + 光栅);
- Courier-en:全部 title 段单行、无词中断行(IL 断言:title 段渲染行数 == 1 或 escalate 记录);
- 全语料 escalate 清单(触底标题逐条:缩放需求值、处置);
- 与 batch-b9.1 译版 diff:变化仅限 title 段几何(译文字节不变——本批不动翻译)。

## 负向(共通)

上游零改动(擦除路径若必须动上游,停止报告);翻译路径零触碰(纯排版批次,译文逐字节守恒是灵魂断言);真值/裁决只读;代码零标签字面量;门禁无 API key(会话二真实运行为验收,断言用其冻结产物)。

## 明确不做

行结构保持(B9.3)、下沉字(B9.4)、碰撞检测(B9.5);正文段落排版;zh 线。

## 会话一前提复核结论(T9.2.1 实测,不改计划,只登记事实)

四条前提的证据与它们对设计的约束。§语义 的意图全部兑现,但其中三处**假定的机制**
与实测不符,实现按实测走,差异逐条记在这里。

### a. 源文擦除:根本不存在"擦除",只有"省略"

- `pdf_creater.py:1674-1682` `update_page_content_stream` 起手是空 `BitStream` +
  `ctm` ——页面自身的 `base_operations` 那三行被注释掉(`:1676-1680`)。页面内容流
  **整条从 IL 重建**。
- xobject 流确实携带 `xobj.base_operations`(`:1670-1672`),但
  `new_parser/base_operations.py:39-62` `collect_page_base_inner_operation` 对
  page 与 xobject 用同一个采集器,凡 `operator.startswith("T")` 一律丢弃 ——
  `Tf` 被丢掉即无字体可选,`Tj/TJ/Tm/Td` 一并丢掉;`BT/ET` 残留但画不出任何字。
- 推论:**一个段落的源文只可能经该段落进入输出**。段落 composition 清空 =
  该段落在输出里彻底消失,源文与译文一起。所以"两层源文均须擦除"不需要专门的
  擦除路径,它是结构性成立的;§语义 3 里的这半句在实现上是零代码。

### AW-v2 p5 幽灵层的确切成因(去重设计的依据)

不是两个段落叠在一起,是**一个段落里的两条 style run**:

- `checkpoint.08_chain_builder` p5(page_number=4)idx17,`layout_label=title`,
  `debug_id=j95wZ`,box=(54.1,695.5,566.6,753.9),`ncomp=2`,文本
  `"RAILWAY?RAILWAY?"`。两条 run 的**每个字符 box 完全相同**
  (R 都在 47.82..130.84),差别只在 graphic_state:
  comp[0] `/CS0 cs 1 scn ... 0 0 0 0.755 k`(实色层),
  comp[1] `/CS2 cs /P0 scn`(图案/渐变层)。原版画面上二者精确重叠,合成
  "RAILWAY?" 的渐隐效果。
- ParagraphFinder 因两层同行同位把它们并成一段,译文遂为 `铁路?铁路?`;
  `checkpoint.11_typesetting` 里六个字符**同一 y(674.81)、横向排开至 x=528.9**。
- 成品 PDF p5 抽字只有 `铁路?铁路?`,**没有任何 RAILWAY 残留** ——
  即"第二层没消干净"看到的浅色鬼影,是第二层的**译文副本**(图案层近白),
  不是未擦除的源文。光栅确认:examples/output/final 的 p5 上半幅,深色
  "铁路?" 之后紧跟一份几乎透明的 "铁路?" 压在正文上。
- 设计约束:排版后段内两层的几何证据已经消失(重排后并列而非重叠),所以
  **段内判据不能用 IoU**,改用"同 font_id + 同字号(容差内)+ 规范化文本一致 +
  长度下限"。段间判据仍用 IoU + 文本相似度,按 §语义 3 原样实现。两种粒度都做,
  段间那条是超集里计划已声明的那半。

### b. 强制单行:上游没有这个开关,单行只能"得到"而不能"要求"

- `typesetting.py:1407-1417` 换行条件只看 `current_x + unit_width > box.x2`,
  `_layout_typesetting_units` / `retypeset_with_precomputed_scale` /
  `render_paragraph` 的签名里都没有任何禁换行参数。
- 通道:给定 scale 使整行自然宽 ≤ 框宽即不触发换行。故实现为
  "估 scale → 重排 → 数行带 → 不足则收缩重试",**以重排结果为准**,估算只定起点。
- 另一条必须知道的事实:`calc_can_passthrough` 返回 `self.unicode is None`
  (`typesetting.py:436-437`),所以把排版后的 PdfCharacter 原样喂回
  `render_paragraph` 会走 passthrough 分支、**完全不重排**。必须先把段落
  重建成 `PdfSameStyleUnicodeCharacters` run(每条 run 保留自己的 style),
  这也是 B8.4 `react/writeback.py` 的既有写法的延伸。

### c. 首行缩进:IL 段属性,关闭即写 False

- 承载:`PdfParagraph.first_line_indent`,由
  `paragraph_finder.py:160-170` 依首行起点相对段框的偏移推断。
- 消费:`typesetting.py:1361-1362`,`current_x += space_width * 4`。
- 关闭通道:重排前置 False。无 schema 改动(既有字段),不触 W-B1-01。

### d. 标题链与本策略的次序:由流水线本身保证

`high_level.py:1045` `il_translator.translate(docs)`(链级联合翻译与句边界回填
在其内部完成)< `:1088` `Typesetting(...).typesetting_document(docs)` <
`:1101` `detectors.detect_issues(...)`(本 pass 的挂载点)。"回填先、缩放后"
不需要额外协调,门禁按这三行的先后次序断言。

### 由上述事实导致的三处实现取舍(与 §语义 的差异)

1. **"仅主层翻译渲染" → 本批只做"仅主层渲染"**。零上游改动下,排版后是唯一可
   落脚的窗口,而那时翻译早已完成;要做到"仅主层翻译"必须在译前去重,那会改变
   该标题段的译文字节,与"译文逐字节守恒"和"不动翻译"直接冲突。故本批去重发生
   在渲染层。译前去重(省一次 token、根治 `铁路?铁路?` 这类译文)留待后续批次。
2. **`duplicate_of` 记 sidecar 不记 IL**。W-B1-01 未解除,IL schema 冻结,
   按 CLAUDE.md §4.10 走 `title_typeset.report.json`。
3. **pass 通过 `detectors.detect_issues` 进入流水线**,因而 `magazine_title_typeset`
   实际依赖 `magazine_detect`(见"与 B8 检测同窗口")。这是零上游改动的代价,
   已记入模块与 sidecar(`window_switch` 字段)。会话二真实运行两开关同开。
4. `on_floor` 的两个取值渲染结果相同(都退回上游的换行),差别在 `escalate`
   额外把该标题连同它要的 scale 记进 `escalations` 清单。

## 会话一附带处理:裁决重钉(用户裁定,CLAUDE.md 4.12)

开工时工作区带着上一会话未提交的用户编辑。按 §5.11 定归属,用户裁定为
"裁决是用户主权的活文档,哈希钉锚定的是'该批次内机器零改动',不是'此文件永不再变'",
按 b9.1 的重钉先例处理:

- **裁决单独一个 commit**(`fbc6ba4`,先于 B9.2 机制 commit),逐字节保留用户编辑,
  机器一字未改。内含 `reviews/Courier-en.decisions.json`(新增 8 条人名词条、
  p4#3 keep→flatten)、`corpus/page_labels.CHANGELOG.md`(用户对该 drop-cap 变更的
  自述记录)、`CLAUDE.md` 第 4.12 条(用户新写的重钉条款本身)。
- **重钉**:`spec_checks/spec_check_b7_5.py` 的 `TRUTH_DIGESTS`
  `c86c16c1…4ad1cfe` → `372a6f7c…07a4fc4`,重钉记录(旧→新、变更摘要、
  变更主体=用户、依据=F2 裁决更新)写在钉点注释处,与 b9.1 重钉 registry 的写法一致。
- b7_5 的 `check_07a` 由"整表相等"放宽为"超集":该次运行应用过的每条词条仍在盘上
  且渲染不变。它原本要防的是"机器回写裁决",这个命题在放宽后完整保留;
  用户事后新增词条不再算失败。
- **字段级复核**落在本批门禁 `spec_check_b9_2` 的 `04d`:用管线自己的
  `hitl.parse_decisions` 对着 B8 committed 的 Courier-en 真实文档复跑
  (格式、页面类型名、drop-cap verdict 词表、段落引用合法性),并断言相对前一版本
  只有"词条新增"与"drop-cap verdict 变更",无词条删除/改写、无 page_kind 变动、
  无 drop-cap 引用增减,且盘上哈希 == 钉住的哈希。
- 重钉后 b7_5 23/23。

## 会话一事故:保留策略删除了 e0/e1/e2 依赖的冻结产物(known-red,不重推导)

### 成因

本批门禁原样照抄 b8.4 的骨架,声明并 `mkdir` 了 `examples/output/b9_2/`,
但整批门禁不往那里写任何东西。空目录对 `tools/prune_outputs.py` 仍然算一个批次目录:
`keep_recent_batches: 2` 的保护窗从 `[b9_1, b8_4]` 移到 `[b9_2, b9_1]`,
b8_4 掉出窗口,其**未被 git 跟踪**的产物在 sweep 收尾的 prune 中被删除
(第一次 sweep 912 文件 / 14.22 GB,第二次 658 文件 / 11.80 GB)。
被跟踪的 b8_4 产物全部存活(策略从不删跟踪文件),故 b8_4 门禁自身 32/32。

### 损失清单(全部位于 `examples/output/b8_4/smoke/`,全部未跟踪)

| 门禁 | 断言 | 缺失产物 |
| --- | --- | --- |
| e0 | `check_02_no_dead_link` | `raster/b8_4.p6_15.page6.png`(被跟踪的 `docs/eval/evidence_ledger.md:57` 引用) |
| e1 | `check_06` / `check_11a` / `check_11b` | `<sample>/work/<sample>/checkpoint.06_styles_and_formulas.xml` × 6 |
| e2 | `check_12` | `<sample>/work/<sample>/checkpoint.08_chain_builder.xml` |

### 已排除的恢复路径(实测,不是推测)

gate_cache 永不被 prune,里面有全部 6 个样张的 stage-06 checkpoint。实测拷回原位后
e1 `check_11b` 重算 fold matrix **与被跟踪的 `lopo_v2.json` 不一致**,
故 gate_cache 变体与 b8.4 那一跑不可互换;若照此"恢复"等于静默篡改证据链。
拷贝已全部撤回,相关路径恢复为 prune 之后的空状态(`docs/` 无改动,
被跟踪的 `lopo_v2.json` 完好:`folds=5`、`missing=[]`)。

### 本会话已做的止血

门禁不再声明也不再创建任何 `examples/output/` 批次目录,原因写在门禁源码注释里。
**注意这只是推迟**:会话二会带着真实产物创建 `examples/output/b9_2/`,
届时 b8_4 会再次掉出窗口。曾试过把 `keep_recent_batches` 提到 3,
但 b8_4 的 `check_04c_retention_keeps_what_it_declares` 断言策略必须确有可删项,
提到 3 即转红,故已回退;`configs/output_retention.json` 本批零改动。

### 交接给恢复批次(用户裁定的 2b 降级路径,本会话不执行)

1. 受影响台账条目状态改为 `artifact pruned, sha recorded`:引文内容存活于被跟踪台账,
   仅失去产物级复验。**不重跑**——role block 已改变 prompt 空间,原理上无法复现原件。
2. e0 的 workspace 档断言接受该状态。
3. 同批做根因修复:prune 保护清单并入 e0 登记的全部 path+sha 路径,并加负向断言;
   CLAUDE.md 保留策略条款补句照录。b8_4 的 `check_04c` 需同步调整,
   否则 `keep_recent_batches` 无法上调。
4. 此后冻结证据的引用一律以台账文本为权威,产物为可选附件;本次降级是该原则的首次全面适用。
