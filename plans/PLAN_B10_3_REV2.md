# PLAN B10.3 rev2 — 段落粒度与风格：译前缝合（双规则）、记录分组、切段风格、游离首字

前置：batch tag `b10.2`。本文件**取代** PLAN_B10_3 初版；初版 T2 把模式挂在
kind 上，与"五个 toc 页同 kind 异构"的事实不相容（Courier-en p1 系
`reviews/Courier-en.decisions.json` 人工裁决 `{"1": "toc"}`），T1 判据够不到
Courier-en p4 的横向碎片，门禁 5 与 T2 自相矛盾。三处均按 2f9e52c 及其后
b10.2 树核实重写。初版留档，此段即作废记录。W-B10-01..04 适用。

本批触碰翻译路径；影响面在 §Cost 声明。运行方式：全文档重放，证据界定到目
标页。

## 前提校验（任一不符即停）

1. `babeldoc/magazine/taxonomy.py:78`：`preserve_line_structure` 为 kind 级布尔
   policy 键，`configs/page_types.json` 两个类型声明 true；代码零类型名分支。
2. toc kind 实际覆盖五页：Courier-en p1（人工裁决）、Vogue p3、CERN p2、
   AramcoWorld p3、FD p3（对 F2 页类型表核实）。
3. `configs/detectors.json` fragment 键组：`fragment_max_chars 40`、
   `fragment_min_cluster 3`、`fragment_max_line_gap_ratio 1.5`、
   `fragment_min_x_overlap_ratio 0.5`、`fragment_font_size_tolerance 0.05`，各带
   范围；该检测器译后 report-only。
4. Courier-en p4 五片坐标（F2 checkpoint）：#4(68,639,212,650) #5(213,639,289,650)
   同行 x 相接；#6(57,627,213,638) #7(215,627,289,638) 同行 x 相接；
   #8(57,495,209,626) 在下。成员间 x 重叠 = 0。F2 报告"两片在第二栏"之读法作废。
5. `babeldoc/magazine/line_split.py` 新段段级 `pdf_style` 继承母段（核实行号）；
   行结构 pass 的切分点（当前：逐行）。
6. b10.1 在案：unicode/compositions 分歧（p7#3）；列出读 `unicode` 的检测器清单。
7. `_suppress` 式置空机制可复用。
8. b10.2 重归因在案：CERN p3 叠印 = A7 游离首字残片。

## 硬约束（违反即停）

- **置空不删段**：合并并入首成员，其余置空留痕 `stitched_into`；置空段数 =
  合并数；无删除无重编号。
- **双写同步**：一切文本变更同操作写 `unicode` 与 compositions，改后逐段规范
  化相等；p7#3 类分歧不新增。
- **上游零改动为构造目标**；诊断指向上游写回点即停。
- **门禁不硬编码不可独立核实的数**：AW p3 / FD p3 的记录分组以报告表交裁决，
  不入断言。

## T1 — 译前碎片缝合：两条接纳规则

新 pass `babeldoc/magazine/fragment_stitch.py` + `configs/fragment_stitch.json`
+ 开关 `magazine_fragment_stitch`。位置：paragraph_finder 之后、行结构 pass 与
翻译之前。`preserve_line_structure` 为 true 的页整页不缝（记录组装归 T2）。

- 规则 V（纵向，复用键）：同字体字号容差、同栏 x 重叠 ≥ 0.5、行距比 ≤ 1.5、
  阅读序相邻。
- 规则 H（横向，**新增**，初版"复用几何键"的说法对此为假）：同行带
  （y 重叠比 ≥ `stitch_min_y_overlap_ratio`，默认 0.6）、x 间隙 ≤
  `stitch_max_inline_gap_ratio` × 字号（默认 0.8）、风格容差同 V、阅读序相邻。
  先 H 后 V：行内片并齐，再由 V 连行（p4 案例：#4+#5、#6+#7 并后对 #8 的 x
  重叠即满足 V）。

两规则喂同一置空合并机制；缝合段风格按 T4 取齐。旋钮全带范围。

## T2 — 记录分组：模式判定下沉到块级行距结构

**取代初版 per_block 政策键**（同 kind 无法声明两种模式；按页分流撞 §4.2/§4.5）。
`preserve_line_structure` 语义不变、声明面不变。行结构 pass 内部，逐块判定记
录粒度：

- 计块内相邻行距序列与其中位数；行距 ≥ `record_gap_ratio` × 中位（新旋钮，
  默认 1.6，range 1.1..5.0）处为记录边界。
- 无一行距过阈（单峰）→ 逐行即记录，**现行路径不变**——Courier-en p1 按构
  造逐字节等于 b10.2 基线，此为门禁断言而非愿望。
- 有过阈行距 → 行距组为记录：组即段（置于组框），组内不再逐行切，作整体翻
  译单元。判据是排印机制本身（组内密排、组间留白），不是对已知页拟阈值；
  中位字符数一类页级统计**不采**。

波及面 = 全部五个 toc 页。AW p3 / FD p3 非投诉页但同 kind 必然被扫到：五页
全出前后证据，分组表进报告交裁。

## T3 — 切段段级风格重算（同初版）

line_split / 记录分组产出的段，其段级 `pdf_style` 按该段自身字符多数派重算
（字体、字号、graphic_state），不继承母段。

## T4 — 缝合/分组段风格统一（同初版）

渲染风格取成员字符多数派，少数派随段取齐；sidecar 记 `style_normalized`。

## T5 — 游离首字残片并入正文（同初版）

接纳四条件：字号比 ≥ `initial_min_font_ratio`(1.6)、簇 ≤ `initial_max_chars`(3)、
与紧邻正文段左上邻接、正文以续词形开头。满足则并入（置空约束），不满足不动。
CERN p3 / Vogue p3 的 A7 可见叠印由此关闭。

## §Cost — 翻译路径影响声明（较初版扩大）

白名单 = 缝合影响段 + T5 并入段 + **五 toc 页的记录级请求**（分组改变请求
文本）。白名单外请求逐字节等于 F2。新增真实调用预估上修至百条以内，归因行
逐条可见；resample 按 parity 冻结惯例。

## 验证（全文档重放，证据界定到目标页）

| 样张 | 目标页 | 看什么 |
| --- | --- | --- |
| Vogue-en | 3 | T1/T2/T4 |
| CERNCourier-en | 2, 3 | T2/T3（p2）、T5（p3） |
| Courier-en | 1, 4 | p1 逐字节负向；p4 双规则缝合 |
| AramcoWorld-en-v2 | 3 | T2 波及面证据 |
| FD-en-v2 | 3 | T2 波及面证据 |

产物入库 `examples/output/b10_3/<sample>/`：局部 PDF、目标页 PNG、缝合/分组/
风格 sidecar、parity（白名单）、conservation。

## 门禁 `spec_checks/spec_check_b10_3.py`（fast）

1. Vogue p3 fragment_cluster 8 → 0；合并数 = 置空数。
2. CERN p2 逐记录：渲染 graphic_state 与源记录字符多数派一致；记录内无字号断
   层；记录边界仅出现于过阈行距处、组内行距全部低于阈（机制不变量）。
3. Courier-en p4：H+V 缝合后五片单请求成句（请求含完整句源文）；
   Courier-en p1 输出与 b10.2 基线**逐字节相同**。
4. T5 像素：CERN p3 残片区源字形 ink 与译文交叠归零；并入段译文成句起头。
5. 守恒（初版此条自相矛盾，修正）：段数逐页等于 F2，**声明页除外**（五 toc
   页 + 缝合/T5 影响页）；声明页以切分/合并账目闭合断言（记录组数 + 置空数
   + 未动段数 = 对账）。Courier-en 裁决 14 术语重放全部落字。
6. 双写：触碰段 unicode/compositions 规范化相等；分歧计数不增。
7. parity：白名单外逐字节同 F2；`api_calls` = 归因行数。
8. `run_all --set fast` 全绿。

负向范围：改动 ⊆ {`babeldoc/magazine/fragment_stitch.py`(新),
`babeldoc/magazine/line_split.py`, `babeldoc/magazine/` 行结构 pass 所在文件,
`babeldoc/magazine/drop_cap.py`(仅 T5 引用常量), `configs/`, `spec_checks/`,
本文件, `examples/output/b10_3/`} 加开关注册点；`taxonomy.py` 与
`page_types.json` 的 policy 声明**字节不变**（T2 不动声明层是本 rev 的要点）；
上游零改动；prompts/ 不动一字；真值/裁决只读。

## 明确不做

栏级 reflow；人名词表化与 HITL 裁定；检测器 unicode→compositions 迁移（仅列
清单）；zh 分类器词表；per_block 政策键（已废案）。

单 commit，tag `b10.3`。交付报告须含：前提 6 读者清单、五页记录分组表（AW/FD
两页交裁）、T5 接纳/拒绝逐例、§Cost 实测与归因对照、F2 p4 读法作废记录。
