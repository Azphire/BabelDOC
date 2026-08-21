# PLAN B10.5 rev2 — 栏级 reflow（源相对收敛版）+ F3 收口

前置：batch tag `b10.4`（61f092d 为 HEAD，含裁定扩展 commit）。本文件**取代**
PLAN_B10_5 初版；初版验证表 5 页中 4 页落在 poster 而非 flow（作用面外），
前提 1 的"F2 §d 在案"为伪造引证（缺陷真、出处错——实为用户审阅轮共性问
题 2），门禁 1/2 照初版不可产出。rev2 按 b10.5 前提差异报告（实测表在案）
重写。初版留档，此段即作废记录。W-B10-01..04 适用至 F3 当日。

本批零 LLM、零翻译路径触碰。基线在案：61f092d `run_all --set fast` 19/19
（540.3s）。

## 前提校验（对 61f092d，任一不符即停）

1. 上游 typesetting 合同：每段译文渲染入自身 `paragraph.box`，段间 y 继承源
   版式。欠填缺陷**实测在案**（b10.5 前提差异报告）：Courier-en 欠填中位
   23.2pt / 最大 86.5pt / >4pt 占比 91% / 栏内间隙方差最大 1814.8（p8）；
   CERN 10.4/54.0/71%/372.6（p4）；AW 8.6/20.1/88%/207.9（p4 右栏）。出处
   为**用户审阅轮**（非 F2 §d）；F3 补记 gap register。
2. flow 页全集（en→zh）：Courier-en 4,6,8；CERNCourier-en 1,4；AW 4,6,7；
   Vogue 与 FD **零 flow 页**（本 pass 于两样张恒空跑，作用面事实）。
3. 碰撞豁免比对**源几何 checkpoint**；源间隙可自同一 checkpoint 逐段对读出
   （段索引 `pN#k` 稳定 → 段对配对平凡）。
4. reflow 前几何快照可复用既有 stage。
5. magazine 开关房规：`getattr(config, SWITCH, False)` 显式开启；artifacts.py
   的 MODES 全部 `skip_translation: True`。
6. `reviews/Courier-zh.decisions.json` format 2、page_kinds 8 条（超集，F3 前
   置满足，哈希重钉待 F3 文档 pass）。

## T1 — 栏级 reflow：源相对超出量收敛

新 pass `babeldoc/magazine/column_reflow.py` + `configs/column_reflow.json` +
开关 `magazine_column_reflow`（**默认关**，房规一致；标准 run config 显式开）。
排在 typesetting 之后、检测器之前。

**语义（裁决三，取代初版"收敛到统一值"）**：
- 逐栏（x 重叠聚类、y 排序）、逐相邻段对：`excess = gap_translated −
  gap_source`（源间隙自源几何 checkpoint 同段对读出）。仅当 excess >
  `min_excess_pt`（默认 4，range 0..20）时收敛：下段上移
  min(excess, `max_shift_ratio` × 栏高)（默认 0.25，range 0..0.5），位移向上
  游累积（段序 y 单调保持）。富余沉栏底。
- **源版式意图天然保留**：源本有的大间隙（小节分隔）excess≈0，不动。
- skip_translation 下译后几何 = 源几何 → excess 恒 0 → **按构造 no-op**（冻
  结比对双保险：默认关 + 语义 no-op）。
- 三重收窄照旧（flow 页 × zh 目标 × 仅竖向间隙）；不动非文本锚定物；任何盒
  不越栏界页框。
- fail-open 按栏（守卫触发整栏回退快照，sidecar 记守卫名）；施加页重检出
  **新** finding → 整页回退。

## T2 — 证据与观测（同初版）

sidecar 逐栏：位移向量、间隙/超出量前后分布、回退计数。前后 PNG 双份。

## 验证（全文档重放，证据界定到目标页；零新增 API）

| 样张 | 目标页 | 角色 |
| --- | --- | --- |
| Courier-en | 4, 6, 8 | 主锚点（p8 方差 1814.8） |
| AramcoWorld-en-v2 | 4, 7 | 施加面 |
| CERNCourier-en | 4 | 施加面 |
| CERNCourier-en | 1 | **负向对照**：var 20.2、excess≈0 → 零位移 |

产物入库 `examples/output/b10_5/`。

## 门禁 `spec_checks/spec_check_b10_5.py`（fast）

1. 定量正向（逐施加栏）：Σ|gap − gap_source| 较快照下降；超出量中位收入
   `min_excess_pt` 容差；栏底富余增量 = 位移总量（竖向空间守恒）。
2. 负向对照：CERN p1 零位移、sidecar 记"excess 低于阈"而非施加。
3. 像素：目标页前后 PNG，位移段 ink 仅现新位置；非施加页（含 Vogue/FD 全
   部）逐字节同 b10.4 基线。
4. 守卫负向（桩）：越界/超位移/新 finding 三例各触发对应回退且留痕。
5. skip_translation no-op：artifacts MODES 任一 run 下 pass 零写入（构造断
   言，语义 no-op 的直接证明）；开关默认值 = False（房规断言）。
6. 守恒：段数页数文本逐段不变；`pN#k` 不移；施加页源豁免结论同 b10.4。
7. `run_all --set fast` 全绿（对 19/19 基线）。

负向范围：改动 ⊆ {`babeldoc/magazine/column_reflow.py`(新), `configs/`,
`spec_checks/`, 本文件, `examples/output/b10_5/`} 加开关注册点；上游零改动；
prompts/ 与真值/裁决只读。

裁决后打 tag `b10.5`。F3 时间受挤压时本批仍为唯一整体可砍项。

---

## F3 收口清单（b10.5 裁决后，单独会话，全量）

运行：sweep 集补跑（141 分钟预算，一次一个、杀前留 log）+ 全量六样张（消费
8 条裁定）+ 阶段计时 sidecar。报告两张主表：F2 §c/§d 逐条终态；本周期新引
入异常清单。专节：

1. 文档迁移：W-B10-05/06/10/11 迁出 WAIVERS 各归其位；WAIVERS 留 01–04 按
   条款失效关闭。
2. gap register：GAP-18 关（T5）；GAP-22/23 关（b10.2）；GAP-27 开（跨对象
   paint 单例 + Vogue B 假说否证记录）；fragment_cluster 记录块过标记开条；
   解析层第八静默通道立项（source_audit 雏形）；**段间距欠填缺陷补记**（出
   处用户审阅轮 + b10.5 实测表 + 本批处置）。
3. F2 读法作废两条归档（p5#17；p4 五片）；**计划层前提伪造引证一例自记**
   （"F2 §d"，rev 链 b10.2/b10.3/b10.5 同模式教训）。
4. 评测协议修订："修复环绕过缓存 = 唯一不可重放段"条款作废（b10.2 key 修
   复 + b10.4 R1 双 run 零调用），重写并引证。
5. 零受理机制与缓建项登记（首字放大规则、VLM 四档；chain_cuts、CJK 收割
   器、keep/annotate 行为批）。
6. 失败分类账新增：空间重复执行（pre_translate_paragraph 二次地板）、截断
   静默自默认（FD 80 名，已 gated）。
7. 批内修正案先例（rev2 版）与三条件边界登记。
8. 裁定扩展与哈希重钉（Courier-zh 8 条、review format 2 再生成）。
9. Courier-zh 恢复量化表（分类 2/8 → 全对；brief 2→实测≥3；链 0→实测）。
10. 性能：阶段计时汇总 → b11 靶单。

F3 全绿后：W-B10-01..04 失效，周期关闭。
