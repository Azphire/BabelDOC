# PLAN B10.2 rev2 — 碰撞判据、碰撞动作改写、决策缓存修复（微批次，1 会话）

前置：batch tag `b10.1`（2f9e52c）。本文件**取代** PLAN_B10_2 初版；初版按 b9.5
时代的树起草，前提 4 与 T2 对现状为假，rev2 依 2f9e52c 逐行核实重写。初版留档
不删，本文件头部即为作废记录。周期减免 §W（W-B10-01..04）继续适用。

## 前提校验（对 2f9e52c，任一不符即停）

1. `configs/decision_rounds.json`：`kind_order` 含 `text_text_collision` 于第 2 位
   （b9.7 起 kind_order 须覆盖全部 raised kinds，`load_kind_order` 拒缺项）。
2. `configs/detectors.json`：`collision_min_iou = 0.2`、`collision_source_min_iou
   = 0.05`，带范围。
3. `babeldoc/magazine/react/collision.py`：`NAME = "resolve_collision"`（:41），
   `admits` 恒拒（`REASON_REPORT_ONLY` / `REASON_IOU`），模块注释载明 b9.5 的
   escalate-only 理由（"causes heterogeneous, answers opposite"）。
4. `babeldoc/magazine/react/decide.py:128` 与
   `babeldoc/magazine/react/actions.py:243`：两处 `cache_key` 同构——
   `CACHE_KEY_VERSION` + engine identity + prompt 文件摘要 + **渲染后 prompt 全
   文哈希**；`debug_id` 经 issues_block 渲染进入全文，从而进入 key。
5. b9.5 census 四对与坐标数值（AW p3#0/#4 0.0089/0.5234、Vogue p3#18/#19
   0.1031/0.5458、CERN p3#11/#13 0.0016/0.7876、p3#22/#24 0.0052/0.8184）在
   b9.5 report 冻结；census 中另有共享成员的近邻对（CERN p3#12/#13、p3#23/#24）
   与 Vogue p3#36/#38、p3#37/#38 清过 0.5。
6. CERN p4 slug 对分属"源设计豁免"与"低于阈值"两类；p4#41/#44 源 coverage 1.0。

## T1 — coverage 判据（同初版，一处措辞更新）

`configs/detectors.json` 增 `collision_min_coverage`（交面积/较小框面积，默认
0.4，range 0.05..1.0），候选条件 = iou ≥ 旧阈 **OR** coverage ≥ 本阈；增
`collision_source_min_coverage`（默认 0.4，range 0.0..1.0），源豁免同为 OR 口
径。ink 口径不变；`progress_evidence` 为该 kind 增列 `coverage`。

**豁免路线变更需在 sidecar 留痕**：CERN p4#41/#44 在旧判据下因"低于阈值"不成
候选，OR 后成候选、改经源 coverage 豁免——结论相同、路线不同，evidence 记
`exempt_route: source_coverage`，门禁按新路线断言。

## T2 — resolve_collision：由 escalate-only 改写为受限写入

这是对 b9.5 一项**在案设计决定的定向推翻**，理由必须写进配置描述与交付报告：

b9.5 拒写的前提是"重叠成因异质、对策相反"。该前提当时成立的条件有二，如今
均已不在：(i) IoU 判据下零 finding，无从区分成因——T1 的 coverage 判据与源几
何豁免先行剔除了最大的异质类（源设计重叠）；(ii) 当时无逐 finding 的判别层
——b9.7 的分轮决策正是体系对"成因异质"的结构性回答：异质该由决策裁，而非
由动作恒拒。故改写不是否定 b9.5 的推理，是其前提失效后的续篇；**且异质性以
受理面收窄的方式继续被尊重**，而非修辞带过：

- 受理（`admits` 改写）：仅当 (a) coverage ≥ 判据阈；(b) 面积不对称明确——
  较小段/较大段面积比 ≤ `resolve_max_area_ratio`（新旋钮，默认 0.5，带范围）；
  (c) 预估位移 ≤ `resolve_max_shift_ratio`（默认 0.08，占该轴页尺寸比）。三者
  齐备才 ACCEPTED；不满足 (b)(c) 者沿用 b9.5 的拒绝理由词表进 escalation——
  "moves nothing" 收窄为 "moves only the class the criteria can now isolate"。
- 写入：对较小段沿重叠较小轴向脱离方向位移，步进至 coverage <
  `collision_min_coverage` − `resolve_margin`（默认 0.05）；位移后 ink 不越页
  框；任一界触发即整项失败回滚。守卫/守恒/回滚复用容纳动作机制层。
- `applicability` 由只读 `MIN_COLLISION_IOU_KEY` 扩为与检测器判据对称的 OR
  （iou 或 coverage），键声明在 `configs/repair_actions.json`。
- 共享成员对（如 p3#12/#13 与 p3#11/#13 同涉 #13）：动作后循环的 re-detect 自
  然消解连带对，无需特判；门禁允许"一次位移关闭多个 finding"。
- 模块注释重写：保留 b9.5 原理由为历史段，续写失效条件与本批受理面。

`decision_rounds.json` **不改**（kind 已在轮中）。`prompts/react_repair_decide.md`
不动一字（摘要 94f39004 不变）；轮内动作词表仍由 repair_actions 收窄。

## T3 — 决策缓存修复（形态按核实结果重定）

key 站点不在 controller 而在两处 `cache_key`（decide.py:128、actions.py:243），
`debug_id` 经渲染文本入 key，key 处无 evidence dict 可投影。两个先定的设计裁定：

1. **投影位置**：不改模型可见文本。做 key 侧规范化——issues_block 渲染出两份：
   展示件（原样入 prompt，模型所见与 F2 逐字节同）与 key 件（剔除易变键后的
   渲染），`cache_key` 哈希 key 件。理由：本周期一切以 F3 可比性优先，prompt
   内容变更是行为变更，留给 b11 之后议。
2. **黑名单而非白名单**（推翻我在 b10.1 裁决里的白名单要求，理由记录在案）：
   决策缓存的两种错法不对称——漏删易变键 → miss，多花钱、可见（T4 归因行会
   暴露）；白名单漏列决策相关键 → 不同 evidence 假命中 → **错误决策被复用**，
   不可见且有害。取可见的错法：`configs/` 声明 `volatile_evidence_keys`
   （初始 `["debug_id"]`），渲染 key 件时按名剔除。
3. 两处 `cache_key` 同构，抽为一个共享模块（`react/cache_key.py`），
   `translate_orphan_lines` 的缓存（actions.py:243）同法修复——它与 decide 同
   病，是 b10.1 报告"未溯源调用"的真正第二嫌疑。`CACHE_KEY_VERSION` 递增一次
   （旧 key 全体自然失效，属预期，报告注明）。
4. **翻译器缓存不在范围**：b10.1 已核实 translate_tracking 三组全部逐字节命中，
   `babeldoc/translator/cache.py` 的 key（engine+params+源文）无易变字段。初版
   rider (1) 的锚点作废。

验证锚点：b10.1 期间每样张恰一次 `from_cache: false` 的决策调用——修复后重放
任一样张目标页，决策命中缓存（归因行 `from_cache: true`）。

## T4 — API 调用归因行（原 rider (2)）

两处 magazine 调用点已记 `from_cache`；落一行归因（组名/缓存判定/请求摘要/
key 前缀）入 run sidecar。门禁：`api_calls` 数 = 归因行数，逐样张。

## 验证（目标页局部跑 + 脚本臂，留档 PDF）

`--pages`：AramcoWorld p3；Vogue p3；CERN p3,4。产物入库
`examples/output/b10_2/<sample>/`：局部 PDF、施加前后 PNG、检测/修复 sidecar、
归因行。采样与门禁分离不变：**施加断言走脚本臂**，模型臂真实采样一次只留痕。

## 门禁 `spec_checks/spec_check_b10_2.py`（标注 fast）

1. 锚点正向：四具名对全部产出 finding，evidence 的 coverage 与 census 容差内一
   致；**完备性口径**——目标页触发集合 = 由冻结 census 按同公式（coverage ≥
   0.4 OR iou ≥ 0.2，减源豁免）算出的预测集合，不多不少（近邻对与 Vogue 两对
   由此自动纳入，无需逐一点名）；CERN slug 类零 finding，p4#41/#44 的
   `exempt_route = source_coverage`。
2. 端到端（像素）：脚本臂对 AW p3#0/#4 施加后重算 coverage 低于阈值；前后 PNG
   上折页号 `8` 与正文 ink 交叠像素数下降；位移 ≤ 界；无新增 out_of_page。
3. 受理面负向：构造面积比超 `resolve_max_area_ratio` 的对与预估位移超界的对，
   `admits` 拒绝且理由入 escalation 词表。
4. 缓存：同一冻结决策点两次构造 key 逐位相等且第二次命中；key 件不含
   `debug_id` 字面；展示件与修复前渲染逐字节相同（模型所见不变的直接证明）；
   orphan 缓存同断言。
5. 归因：各样张 `api_calls` = 归因行数。
6. `run_all --set fast` 全绿；b8.4 十九发现谱（桩驱动）判定不变。

负向范围：改动 ⊆ {`babeldoc/magazine/detectors/`, `babeldoc/magazine/react/`
（含 collision.py 改写、cache_key.py 新建）, `configs/`, `spec_checks/`, 本文件,
`examples/output/b10_2/`}；上游零改动；prompts/ 与真值/裁决只读；
`decision_rounds.json` 字节不变。

## 明确不做

GAP-24/25 剩余、GAP-26；prompt 内容级的 evidence 精简（b11 后议）；翻译器缓
存；gate cache LRU 根修（完整性预检若本会话时间富余可做，做则单列断言，不做
则明记推迟至 F3 前微批）。

单 commit，tag `b10.2`。交付报告须含：b9.5 决定推翻的完整论证段、模型臂留痕、
触发集合预测表 vs 实测表、缓存修复前后归因行对照。
