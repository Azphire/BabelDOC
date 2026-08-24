# PLAN B11.6 — 缩进双闸（页级/盒级）、页内栏界链（合并翻译与统一渲染）

前置：batch tag `b11.5`（5c168a6）。规格即当次 prompt。单臂默认适用。
本批两项均为用户明确需求；T2 是继跨页链之后对承诺 (2) 的页内扩展，裁定材料
（b11.2 T3 测量 + 本轮 24 对逐对裁定）已在案。

## 前提校验（任一不符即停，逐条记行号）

1. `configs/indent_policy.json`：作用面仅 `body_labels`（text / plain text /
   paragraph_hybrid），无页级闸、无盒级排除。
2. `configs/page_types.json` 的 policy 机制可加布尔键（`chain_eligible` /
   `preserve_line_structure` 先例）；代码零类型名。
3. `tools/column_continuity.py` 与 `examples/output/b11_2/
   column_continuity.report.json` 在库：107 对、24 判连、FD p6 真阳性
   （`fertilizer|costs` 全信号 1.0）与连字符案例（`sup-|ply chains`）均被捕
   获；`column_position` 记常量、`opener_prior` 置零、连字符信号记录不计分
   ——三处如实处理在案。
4. 本轮裁定在案（写入 `reviews/column_pairs.adjudication.json`，格式见 T2）：
   24 对 = 真 16 / 假 8；假 8 = 跳栏对 5 + 目录页 1 + 难例 2（AW p8 评论页
   col1→3、Courier-zh p4 col3→4）。
5. `chain_builder.py` 遍历相邻页对；`chain_translation` / `chain_backfill` /
   切点级联（b10.4）/ 守恒 join≡whole 为既有机制。
6. b10.5 的矢量读取（obstacle/填充矩形）可复用于盒级排除。
7. b11.5 FD 在案：indent 已作用 103 段——核对其中是否含 p3（toc）记录（预
   期含，即页级闸缺失的直接证据；不含则本前提改记并缩 T1 范围）。

## T1 — 缩进双闸

1. **页级闸**：policy 键 `indent_eligible`，在 `page_types.json` 对文章首页
   与文章正文两类声明 true，其余不声明（缺省 false）。`indent_policy.py` 读
   键；不合格页整页跳过并 sidecar 记 `page_ineligible`。
2. **盒级排除（determination-first）**：
   a. 先测量：复用矢量读取，对六样张（离线，b10.5 on 臂）数出"body 标签段
      落盒落在填充矩形（面积 ≥ `boxed_min_area_ratio` × 页面积，默认 0.02，
      带范围）内"的实例，列清单入报告；
   b. 测量确认清单即边栏/信息框（人工抽验写入报告）→ 启用排除：命中段
      sidecar 记 `boxed_excluded`；清单显示误伤正文 → 停该子项，只落页级
      闸，盒级记 gap。
3. 门禁：FD p3 目录记录零缩进（页级闸正向）；文章页 body 段维持全缩进（不
   回归）；边栏案例一例排除留痕（若 2b 启用）。

## T2 — 页内栏界链

**裁定基础**（前提 4）：现行权重迁移可行（真阳性全捕获），假阳有结构，三道
闸消 6/8，剩 2 难例以第四道闸 + escalation 兜底。**不确定不连**原则原样继承。

1. **边界泛化**：`chain_builder` 的边界对象加 `kind ∈ {page, column}`；
   column 边界 = 同页列带序相邻的（前栏末候选，后栏首候选），列带推导复用
   `column_continuity` 已验证的那套（同源函数，不复制代码）。
2. **闸（四道，全部声明式）**：
   - 行结构页（`preserve_line_structure` 为 true）整页不产栏边界；
   - 边独占：链装配时一个端点至多入一条边，列序邻接边优先于跳栏
     （body_next）边；
   - 阈值沿用 `link_min_score`（0.8），信号权重不动；`column_position` 恒 1
     入分（如实声明），`opener_prior` 恒 0；
   - 头段贴题拒：头段正上方 `head_clear_gap_em`（默认 1.5，带范围）内存在
     title/attribution 类端点即拒（AW p8 难例的针对闸），拒绝理由入
     escalation 词表。
   - 连字符信号维持记录不计分（权重未标定，b11.2 的立场不变）。
3. **下游零新机制**：连上的栏链进 `chain_translation` 联合翻译；
   `chain_backfill` 以栏界为切点，body 链走句界回填、display 链走三级级联
   （均既有）；守恒 join≡whole 扩至页内链（断言器改动登记）。
4. **裁定文件为门禁真值**：`reviews/column_pairs.adjudication.json` 记 24 对
   的裁定（true/false/理由），由本 PLAN 附录固化、执行方写入、哈希钉住。门
   禁以它断言：实现后的实际连接集 ⊇ 真集 ∩ 三闸可达者、∩ 假集 = ∅。
   注意跳栏 5 条：断言其**不以跳栏边**成链，但其覆盖的文本经邻接边成链（即
   col0→1→2 两段链覆盖 col0→2 的内容——这才是正确形态）。

## §Cost 与验证

新栏链改变其成员段的请求（联合翻译文本），所在批重采样。按裁定分布，受影
响样张 = Courier-en、AramcoWorld、FD、Courier-zh（CERN 0 对、Vogue 0 对判
连，不跑）。四样张各跑 on 臂一次，完整 PDF 入库 `examples/output/b11_6/`。
预估调用一百上下，归因行对账。

## 门禁 `spec_check_b11_6.py`（fast）

1. T1：FD p3 零缩进、文章页缩进不回归、（若启用）盒级排除一例留痕、页级闸
   负向（未声明 kind 的页整页 `page_ineligible`）。
2. T2 连接集：= 裁定真集经四闸过滤后的可达集，不多不少；假集零成链；跳栏
   内容经邻接边覆盖（上文形态断言）。
3. T2 翻译与渲染：FD p6 `以及`断裂修复——提取文本中"高度依赖"与"成本"所
   在句连贯成句（联合翻译的直接证明）；`sup-|ply chains` 案例译文成句；每
   条栏链两段各渲染于自身栏盒（统一渲染 = 联合译文 + 分栏回填）。
4. 守恒：join≡whole 含页内链；段数页数 `pN#k` 不变；detector 计数不升。
5. 裁定文件哈希 = PLAN 附录值；`api_calls` = 归因行数；
   `run_all --set fast` 全绿。

## 负向范围

改动 ⊆ {`babeldoc/magazine/chain_builder.py`、`chain_signals.py`（列带函数
共享化）、`chain_backfill.py`（栏界切点）、`indent_policy.py`、`configs/`、
`reviews/column_pairs.adjudication.json`(新，本 PLAN 附录固化)、
`spec_checks/`、`docs/eval/gap_register.md`、`WAIVERS.md`、本文件、
`examples/output/b11_6/`}。上游零改动；`prompts/` 不动一字。

## 明确不做

连字符信号入权重（未标定）；难例 2 的机制化修复超出第四道闸者（escalation
兜底 + gap 登记）；跨样张回归债清算（W-B11-12 继续挂账，**下批必须是六样张
全量清算批**，本文件立此存照）；corner_mark 全类；GAP-33。

## 附录 — 24 对裁定（执行方原样写入 adjudication 文件）

真（16）：Courier-en p5 c1→2、p6 c0→1、p6 c1→2、p8 c0→1、p8 c1→2；
AW p5 c1→2、p6 c0→2（跳过图注栏，属 body_next 正当形）；FD p6 c0→1
（连字符）、p6 c1→3（跳过标题栏，正当形）、p9 c0→1；Courier-zh p5 c0→1、
p5 c1→2、p6 c1→2、p7 c0→1、p8 c0→1、p8 c1→2。
假（8）：跳栏冗余 5——Courier-en p6 c0→2、p8 c0→2、Courier-zh p5 c0→2、
p7 c0→2、p8 c0→2（内容由邻接边覆盖）；目录页 1——FD p3 c0→1；难例 2——
AW p8 c1→3（跨评论单元）、Courier-zh p4 c3→4（撞署名块）。

执行序：T1 → T2 → 四样张跑 → 门禁。单 commit，tag `b11.6`（裁决后打）。
交付报告须含：T1 测量清单与抽验、T2 连接集对照裁定表、FD p6 前后文对照、
守恒扩展说明、§Cost 实测。
