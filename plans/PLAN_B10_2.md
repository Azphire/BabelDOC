# PLAN B10.2 — 碰撞判据与碰撞动作（微批次，1 会话）

前置：batch tag `b10.1`。规格即当次 prompt，本文件是其归档。周期减免 §W
（见 PLAN_B10_1）继续适用。

## 前提校验（任一不符即停）

1. `configs/detectors.json`：`collision_min_iou = 0.2`（:29 附近），
   `collision_source_min_iou = 0.05`，两者带 `_allowed_range`；detectors 按
   `profile_detectors` 分派。
2. b9.5 census 在案的四对（页号一基）：AramcoWorld `p3#0/#4`（iou 0.0089，
   coverage 0.523）、Vogue `p3#18/#19`（0.103 / 0.546）、CERNCourier
   `p3#11/#13`（0.0016 / 0.788）、`p3#22/#24`（0.0052 / 0.818）。F2 全程零
   `text_text_collision`。
3. CERNCourier 每页底边的印刷 slug 为源设计，b9.5 census 已豁免——豁免语义
   换口径后必须保持豁免。
4. `configs/decision_rounds.json`（b9.7）声明 kind 迭代序，缺项/多项报错；
   `text_text_collision` 当前**不在**声明中（因无动作应答该 kind——校验此点，
   若已在则停）。
5. `configs/repair_actions.json` 与 `babeldoc/magazine/react/` 下容纳动作
   （contain_in_page）的实现：位移施加、守卫、回滚、守恒检查的复用面在此。
6. 决策缓存跨 run 0 命中的成因（F1 §5 note 1 / F2 §b#8）：evidence 块携带每
   run 重生成的 `debug_id`。校验：在 controller 的 cache key 构造处确认
   `debug_id`（及任何 run 级易变字段）进入了被哈希的输入。找不到即停。

## T1 — coverage 判据

`configs/detectors.json` 增：
- `collision_min_coverage`（交面积 / 较小框面积；默认 0.4，range 0.05..1.0）。
  候选条件改为 **iou ≥ collision_min_iou OR coverage ≥ collision_min_coverage**。
- `collision_source_min_coverage`（默认 0.4，range 0.0..1.0）。源设计豁免同步
  为 OR 口径：源几何下 iou ≥ 旧阈 **或** coverage ≥ 本阈，即豁免。
- ink 口径不变（字符并集，falling back to box）；`progress_evidence` 为
  `text_text_collision` 增列 `coverage`（单调递减可计进展）。

检测器实现只读新键、算 coverage、并入判据与 evidence；不动其他 kind。

## T2 — resolve_collision 动作

`configs/repair_actions.json` 增 `resolve_collision`，规则与旋钮全部声明式：
- 受理：kind = `text_text_collision`；动作对**较小段**施加位移。
- 位移方向：沿两盒重叠量较小的轴，向脱离方向；步进直至
  coverage < `collision_min_coverage` − `resolve_margin`（新旋钮，默认 0.05）。
- 界：`resolve_max_shift_ratio`（占该轴页尺寸比，默认 0.08，带 range）；位移后
  ink 不得越页框（复用 out_of_page 的框语义）。任一界触发即该项失败回滚。
- 守卫/守恒/回滚复用容纳动作的机制层：段数页数不变、只有被点名段变化、迭代
  级回滚撤销全部写入。

`configs/decision_rounds.json` 增 `text_text_collision` 轮（序放 `out_of_page`
之后）。prompt 与动作词表机制不变：轮内词表由 repair_actions 收窄，
`prompts/react_repair_decide.md` **不动一字**（断言摘要 `94f39004…` 不变）。

## T3 — 决策缓存 key 规范化

controller 构造 cache key 前，对 evidence 做规范化投影：剔除 `debug_id` 与其
他 run 级易变字段（以白名单列举保留字段，不以黑名单剔除——新字段默认不入
key，防再犯）。b9.7 的"key 含 kind（经 round identity）"语义保持。旧缓存自然
失效属预期。

## 验证（目标页局部跑 + 桩驱动，留档 PDF）

API 支出仅本批新增决策轮请求（个位数）。`--pages`：

| 样张 | 页 | 看什么 |
| --- | --- | --- |
| AramcoWorld-en-v2 | 3 | p3#0/#4 触发 + 动作施加 |
| Vogue-en | 3 | p3#18/#19 触发 |
| CERNCourier-en | 3,4 | p3 两对触发；p4 slug 源豁免零误报 |

**采样与门禁分离**（GAP-25 教训）：动作**施加**断言走脚本臂（点名判定，同
b9.5 第四臂），模型臂真实采样一次、只留痕不作为门禁条件；交付报告记录模型
臂选择供 GAP-25 证据链累积。

产物入库 `examples/output/b10_2/<sample>/`：局部 PDF、目标页 PNG（施加前后
两份）、检测与修复 sidecar。

## 门禁 `spec_checks/spec_check_b10_2.py`

1. 正向锚点：四对全部产出 `text_text_collision` finding，evidence 含 coverage
   且与 census 数值容差内一致；CERN p3/p4 的 slug 类零 finding（源豁免）。
2. 端到端（修复类，含像素）：脚本臂对 AW p3#0/#4 施加后，目标区重算 coverage
   低于阈值，且施加前后 PNG 上折页号 `8` 的 ink 与正文 ink 交叠像素数下降；
   位移量 ≤ 界；无新增 out_of_page finding。
3. 守恒：施加样张目标页段数不变，除点名段外逐段与 b10.1 基线相同。
4. 缓存：一个冻结决策点连续两次构造，key 逐位相等且第二次命中（可桩驱动）；
   key 输入投影中不含 `debug_id` 字段名。
5. 零回归：b8.4 十九发现谱（桩驱动，快）判定不变；`run_all` 全绿。

负向：改动 ⊆ {`babeldoc/magazine/detectors/`, `babeldoc/magazine/react/`,
`configs/`, `spec_checks/`, 本文件, `examples/output/b10_2/`}；上游零改动；
prompts/ 与真值/裁决只读；`reviews/` 字节不变。

## 明确不做

`fallback_line` 出页项的容纳扩类（GAP-24 维持原措辞）；孤儿动作配额措辞
（GAP-25 剩余）；GAP-26 em 盒；碎片缝合与 reflow；gap register 的关账编辑
（F3 后统一做）。

单 commit，tag `b10.2`。交付报告含模型臂留痕与四对 coverage 实测表。
