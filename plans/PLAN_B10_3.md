# PLAN B10.3 — 段落粒度与风格：译前缝合、目录双模式、切段风格、游离首字（微批次，1 会话）

前置：batch tag `b10.2`。规格即当次 prompt，本文件是其归档。周期减免
W-B10-01..04 适用。本批是五日周期唯一**触碰翻译路径**的一批：缝合改变受影响
段的请求文本，该影响面在 §Cost 内声明并被门禁围住——W-B10-01 的"逐批影响
以 PLAN 声明为准"条款即为此批而设。

运行方式沿 b10.2 澄清：全文档重放，不用 `--pages`；证据界定到目标页。

## 前提校验（任一不符即停）

1. `configs/detectors.json` 中 fragment_cluster 的几何判据键在（同字体字号容差、
   同栏 x 重叠比、行距比上限）；该检测器现为**译后 report-only**。
2. F2 在案：Vogue p3 八个 fragment cluster；Courier-en p4 五碎片句（A1）；
   CERN p2 目录 18 段行切、颜色坍塌为蓝、字号断层；Courier-en p1 行切目录
   正常（b9 系修复后状态，作本批负向基线）。
3. b10.2 重归因在案：CERN p3 叠印 = 游离首字残片（A7 类），两对 source_coverage
   1.0 经源豁免退出碰撞类；Vogue p3#18 经标题缩放退出候选。
4. `babeldoc/magazine/line_split.py` 切段时新段段级 `pdf_style` 继承母段（核实
   继承点行号）；组合级 style 保真。
5. `configs/page_types.json` 的 policy 含布尔 `preserve_line_structure`；代码零
   页面类型名（模式经 policy 键分派，不经类型名分支）。
6. b10.1 在案：`unicode` 与 compositions 可分歧（Courier-en p7#3）；哪些检测器
   读 `unicode`、哪些读 compositions——逐一列出，写进交付报告。
7. `_suppress` 式置空机制可复用（b9.2 去重所用：段存续、文本置空、计数留痕）。

## 硬约束（先于任务，违反即停）

- **置空不删段**：一切合并将文本并入首成员（按阅读序），其余成员段对象存续、
  文本置空、sidecar 记 `stitched_into`。全语料 `pN#k` 索引不增不删不移——裁决
  文件、检测报告、冻结证据的引用因此稳定。守恒断言：段数不变、字符总数不变、
  置空段数 = 合并数。
- **双写同步**：本批一切文本变更在同一操作内写 `unicode` 与 compositions 两处；
  改后逐段断言两处规范化相等。b10.1 发现的分歧（p7#3 类）不得新增。
- **上游零改动为构造目标**：T3 的修法必须落在 magazine 侧（line_split 产段时把
  段级 style 算对，让上游既有渲染自然出对的结果）。诊断若表明非动上游写回点
  不可——停，报告，不得就地扩范围。

## T1 — 译前碎片缝合

新 pass `babeldoc/magazine/fragment_stitch.py` + `configs/fragment_stitch.json`
+ 开关 `magazine_fragment_stitch`（默认开）。位置：paragraph_finder 之后、行切
与翻译之前。判据复用 fragment_cluster 的几何键（同字体字号容差内、同栏 x 重叠、
行距比内、阅读序相邻），另加：`line_structure_mode = per_line` 的页**整页不缝**
（目录记录不许并行）。合并按置空约束执行；缝合段以多数派字号/风格重排（T4）。

## T2 — 目录双模式

`configs/page_types.json` policy 把 `preserve_line_structure` 扩为
`line_structure_mode: per_line | per_block | off`（向后兼容：旧布尔 true 读作
per_line，false 读作 off——历史冻结配置须可解析，b10.2 教训）。`per_block`：
不行切、允许缝合、按块整体排版。模式由 policy 按 kind 声明；本批声明使
Vogue p3 / CERN p2 走 per_block，Courier-en p1 保持 per_line。代码只读模式键。

## T3 — 切段段级风格重算

line_split 产出的新段，其段级 `pdf_style` 改为按**该段自身字符**的多数派重算
（字体、字号、graphic_state 一致取齐），不再继承母段。CERN p2 蓝色坍塌与字号
断层的第一半由此闭合；第二半（缝合段）由 T4 的多数派取齐闭合。

## T4 — 缝合段风格统一

缝合段的渲染风格取成员字符多数派；少数派字符随段重排为统一风格。sidecar 记
`style_normalized: {from: [...], to: ...}`。

## T5 — 游离首字残片并入正文（承接 b10.2 重归因）

CERN p3 / Vogue p3 的 A7 类：源首字（`T` / `"Th`）自成微段压在译文上，
drop_cap mark 的候选判据未覆盖。在缝合 pass 内加一条受限接纳规则：字号显著
大于邻段正文（`initial_min_font_ratio`，默认 1.6，带范围）、单簇 ≤
`initial_max_chars`（默认 3）、与紧邻正文段左上邻接、且该正文段以续词形开头
——满足则并入该正文段（置空约束同上），译前即成完整句。不满足者不动（不做
激进兜底）。CERN p3 的可见叠印以此路径关闭，像素断言见门禁 4。

## §Cost — 翻译路径影响声明

受影响段（被缝合/被并入/风格重算不改文本者除外）的请求文本变更，缓存必然
miss。预估新增真实调用集中于 Vogue p3、CERN p2/p3、Courier-en p4，量级数十
条；其余请求须与 F2 逐字节相同（parity 白名单机制：允许清单 = 缝合影响段的
请求，清单外一条不许变）。归因行（b10.2 T4）逐条可见。resample 差异按 b10.1
的 parity 冻结惯例处置。

## 验证（全文档重放，证据界定到目标页）

| 样张 | 目标页 | 看什么 |
| --- | --- | --- |
| Vogue-en | 3 | T1 缝合、T2 per_block、T4 风格 |
| CERNCourier-en | 2, 3 | T2/T3（p2 颜色与字号）、T5（p3 残片） |
| Courier-en | 1, 4 | p1 per_line 负向基线；p4 五碎片句 |

产物入库 `examples/output/b10_3/<sample>/`：局部 PDF、目标页 PNG、缝合/风格
sidecar、parity（含白名单）、conservation。

## 门禁 `spec_checks/spec_check_b10_3.py`（标注 fast）

1. Vogue p3 fragment_cluster 计数 8 → 0；缝合 sidecar 的合并数与置空数相等。
2. CERN p2 目录逐记录：渲染 graphic_state 与源该记录字符多数派一致（不再整栏
   蓝）；同一记录内无字号断层；per_block 模式留痕。
3. Courier-en p4 五碎片句并为单请求且译文成句（请求文本含完整句源文）；
   Courier-en p1 行切目录与 b10.2 基线逐段相同（per_line 负向）。
4. T5 像素：CERN p3 目标区源 `T` 字形 ink 不再叠于译文之上（前后 PNG 对照，
   残片区交叠像素归零或仅余背景）；并入段的译文以完整句开头。
5. 索引稳定端到端：Courier-en 裁决 14 术语重放全部落字（`pN#k` 引用未漂移的
   直接证明）；全语料段数与 F2 逐页相等。
6. 双写：本批触碰的每一段，`unicode` 与 compositions 规范化相等；p7#3 类分歧
   计数不增。
7. parity：白名单外请求与 F2 逐字节相同；`api_calls` = 归因行数。
8. `run_all --set fast` 全绿。

负向范围：改动 ⊆ {`babeldoc/magazine/fragment_stitch.py`(新),
`babeldoc/magazine/line_split.py`, `babeldoc/magazine/drop_cap.py`(仅当 T5 判据
需引用其常量), `configs/`, `spec_checks/`, 本文件, `examples/output/b10_3/`}
加开关注册点；上游零改动（硬约束三兜底）；prompts/ 不动一字；真值/裁决只读。

## 明确不做

栏级 reflow（b10.5）；人名词表化与 HITL 裁定（b10.4）；检测器读 `unicode` 改
读 compositions 的迁移（本批只列清单进报告，改法随 F3 后统一议——本批不给
读者换地基）；zh 分类器词表；A5 目录双行记录若与 per_line 冲突，记录现象不
强行缝合。

单 commit，tag `b10.3`。交付报告须含：前提 6 的读者清单、§Cost 实测（新增调
用数与归因行对照）、T5 接纳/拒绝逐例表。
