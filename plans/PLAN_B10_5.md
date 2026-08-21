# PLAN B10.5 — 栏级 reflow（降级版）+ F3 收口（微批次 + 全量回归，1+1 会话）

前置：batch tag `b10.4`（a397591 后打）。规格即当次 prompt。W-B10-01..04 适
用至 F3 当日。本批零 LLM、零翻译路径触碰（纯译后几何 pass），预算重心在
F3 当日（sweep 141 分钟 + 全量六样张 + 文档 pass）。

## 前提校验（任一不符即停）

1. 上游 typesetting 合同：每段译文渲染入该段自身 `paragraph.box`；段间 y 继
   承源版式（欠填堆积成超宽段间距的机制，F2 §d 在案）。
2. 栏聚类几何键可复用（fragment 键组的 x 重叠、行距比）。
3. 碰撞检测器的源设计豁免比对**源几何 checkpoint**（b10.2 T1 landed），与译
   后盒无关——reflow 移动译后盒不改豁免语义。核实比对读取点。
4. `repair_profile` 可判 flow 页集合；en→zh 五样张的 flow 页清单产出入报告。
5. 置备 reflow 前几何快照（新 checkpoint 或复用既有 stage）供回退与门禁对比。
6. F3 前置：`reviews/Courier-zh.decisions.json` 已扩展至六条页类（用户补
   四条），哈希重钉记录在案。**未扩展则 F3 缓行，b10.5 本体不受阻。**

## T1 — 栏聚类与间隙重排

新 pass `babeldoc/magazine/column_reflow.py` + `configs/column_reflow.json` +
开关 `magazine_column_reflow`（默认开，范围守卫见下）。排在 typesetting 之
后、检测器之前。

- 作用面三重收窄（硬编码为 config 声明而非代码分支）：`repair_profile =
  flow` 的页；目标语言 zh；段间距重排**只均衡竖向间隙**，不改栏宽、不改段
  内排版、不动图/caption/pull quote 等非文本锚定物。
- 栏聚类：x 重叠 ≥ 键值的段归栏，按 y 排序。
- 重排：栏内以译后实际 ink 高度重算各段 y，使相邻段间隙收敛到统一值（目标
  间隙 = 栏内中位行距 × `gap_line_ratio`，默认 1.0，range 0.5..3.0）；单段位
  移 ≤ `max_shift_ratio`（占栏高比，默认 0.25，range 0..0.5）；段序 y 单调保
  持；任何盒不得越栏界与页框。
- **fail-open 按栏**：任一守卫触发，该栏整体回退快照几何；sidecar 记
  `reflow_reverted` 与触发守卫名。
- **重排后再检**：对施加页重跑碰撞/出页检测；出现**新** finding → 该页整页
  回退（宁不改不引新伤）。

## T2 — 证据与观测

sidecar 逐栏记：位移向量表、间隙前后分布（中位/方差）、回退计数。目标页前
后 PNG 双份入库。

## 验证（全文档重放，证据界定到目标页；零新增 API）

| 样张 | 目标页 | 看什么 |
| --- | --- | --- |
| AramcoWorld-en-v2 | 4, 9 | 长文 flow 栏，F2 超宽间距在案 |
| CERNCourier-en | 3 | 新闻栏 |
| Courier-en | 5, 7 | article_body 栏 |

产物入库 `examples/output/b10_5/`。

## 门禁 `spec_checks/spec_check_b10_5.py`（fast）

1. 定量正向：施加栏的段间隙方差较快照下降（逐栏断言，阈值入 config）；间隙
   中位落在目标值容差内。
2. 像素：目标页前后 PNG，位移段的 ink 仅出现在新位置；非施加页逐字节同
   b10.4 基线。
3. 守卫负向：桩构造越界/超位移/新 finding 三例，各自触发对应回退路径且
   sidecar 留痕。
4. 守恒：段数、页数、文本逐段不变（纯几何 pass 的直接断言）；`pN#k` 不移。
5. 检测器语义：施加页源豁免结论与 b10.4 相同（源几何比对不受移动影响的直
   接证明）。
6. `run_all --set fast` 全绿。

负向范围：改动 ⊆ {`babeldoc/magazine/column_reflow.py`(新), `configs/`,
`spec_checks/`, 本文件, `examples/output/b10_5/`} 加开关注册点；上游零改动；
prompts/ 与真值/裁决只读。

裁决后打 tag `b10.5`。若 F3 当日时间受挤压，本批为唯一整体可砍项（改善项
非缺陷修复）；砍则 F3 提前，本 PLAN 留档标注未执行。

---

## F3 收口清单（b10.5 裁决后，单独会话，全量）

运行：sweep 集补跑（预算 141 分钟，一次一个、杀前留 log）+ 全量六样张（消
费扩展后的 Courier-zh 裁定）+ 阶段计时 sidecar（纯观测，b11 定靶数据）。

报告两张主表：F2 §c/§d 逐条终态；本周期新引入异常清单。另附专节：

1. 文档迁移：W-B10-05/06/10/11 迁出 WAIVERS（永久性内容各归其位：断言合同
   变更入批报告附录、检测器议题入 gap register、scoped gap 入 limitation 登
   记）；WAIVERS 只留 01–04 并按失效条件关闭。
2. gap register 收口：GAP-18 按 T5 关账；GAP-27 开账（跨对象 paint，维持单
   例——Vogue B 假说已被源审计否证的记录并入）；GAP-22/23 关账（b10.2）；
   fragment_cluster 记录块过标记开新条目；解析层第八静默通道立项
   （source_audit 为检测器雏形）。
3. F2 读法作废两条归档（p5#17 遮挡非叠印；p4 五片同栏横向）。
4. 评测协议修订：**"修复环绕过缓存 = 唯一不可重放段"条款作废**——b10.2
   key 修复 + b10.4 R1 双 run 证据，重放确定性覆盖修复决策；重写该节并引证。
5. 零受理机制清单（首字放大规则、VLM 四档）与缓建项（chain_cuts、CJK 收割
   器、`keep`/`annotate` 行为批）登记。
6. 失败分类账新增两例：空间重复执行（pre_translate_paragraph 二次地板）、
   截断静默自默认（FD 80 名，已 gated）。
7. 批内修正案先例（rev2）与适用边界三条件登记。
8. 裁定扩展记录与哈希重钉（Courier-zh 四条、review 文件 format 2 再生成）。
9. Courier-zh 恢复量化表（分类 2/8 → 裁定后全对；brief 2→实测；链 0→实测）
   ——HITL 承诺的定量证据。
10. 性能：阶段计时汇总 → b11 靶单（checkpoint I/O、gate cache LRU 根修、
    翻译缓存段粒度评估、sweep 并行化）。

F3 全绿后：W-B10-01..04 按条款失效，周期关闭。
