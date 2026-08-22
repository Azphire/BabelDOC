# PLAN B11.2 — 未译单元判定、上游变更暴露面探测、页内跨栏测量、门禁证据根修

前置：batch tag `b11.1`。规格即当次 prompt，本文件是其归档。

**本批的性质**：五项任务里三项是**判定与测量**（离线读既有产物，零改动、零
API），两项是修复。**不做全量跑**：跑哪些样张由 T2 的暴露面探测**用证据决
定**，而不是预先声明——这是对"只跑受影响部分"的严格实现，而非省略。

**一条继承自 b11.1 的债务，先摆明**：b11.1 的 T1（恒等短路复活）与 T2（悬
挂界）是**上游行为变更，影响面为全语料**，而验证只在 FD 做过。本批的 T2 就
是来结这笔账的——用离线探测把"影响面"从"理论上全语料"收敛成"实测的这几
个样张"，再只跑它们。若探测结果是六样张全都有暴露，那就必须全跑，届时另行
裁决，不得自行缩减。

---

## 前提校验（对 b11.1 的 HEAD，逐条记行号入报告；任一不符即停）

1. f3 基线产物路径为 `examples/output/F3/cold/FD-en-v2/` 一类（**cold/warm
   两臂**，b11.1 前提报告已更正），六样张各两臂；两臂 41 页栅格 SHA-256 相
   同的记录在 f3 报告在案。确认 warm 臂为引用臂。
2. 各样张 f3 工作目录仍在（未被保留策略淘汰），且其中含
   `translate_tracking.json` 与 `checkpoint.09_il_translated.*`。**若已被淘
   汰**：停，报告，先做 T4 再重开本批（这正是 T4 要根治的病）。
3. FD f3 在案的 18 条 `untranslated_residue`（`issues.json`），含
   `Xsq3w#L0`/`Y5B2Q#L0`/`EBXbA#L0`/`PSrBx#L0`/`v178u#L0`/`7BCR5#L0`
   与 p9 的 `y1HqM`。
4. 同一段落的两种读法确实不一致：`source_audit.report.json` 的 p5#5 文本为
   `MANAGINGEDITOR`（14 字符），`issues.json` 的 `Y5B2Q#L0` excerpt 为
   `MANAGING EDITOR`（15 字符，含空格）。输出 PDF 的字符流在 `'ANAGING'`
   与 `'EDITOR'` 之间有真实空格字形（x 365.74→369.77）。
5. `repair_actions.json` 的 `translate_orphan_lines` 受理面
   `orphan_layout_labels = ["fallback_line"]`，`min_residue_ratio = 0.9`，
   `min_source_chars = 12`。
6. b11.1 在案：`hang_max_em` 生效（9 悬挂 / 7 回退 / 0 拒绝）；恒等短路复活
   后 FD 有 15 段命中、12 段文本未变。

---

## T1 — 未译单元判定（离线，零改动，判定完成前不得改任何代码）

**要回答的唯一问题**：FD 那 18 条残留，**送去翻译的请求文本到底是什么**。

方法：对每条残留，从 `translate_tracking.json`（或 `09_il_translated`）取出
该段的三样东西并逐条列表——`input`（送出的文本）、`output`（收回的文本）、
是否出现在任何请求中。三分类，每条给出证据：

- **A 类 · 请求文本粘连**：input 形如 `MANAGINGEDITOR`（空格丢失）。
  → 病在 `paragraph.unicode` 的构造：空格字符存在于字符流却未进 unicode。
- **B 类 · 请求文本正确、模型原样返回**：input 为 `MANAGING EDITOR`，
  output 相同。→ 病在合规性。
- **C 类 · 从未送出**：该段不在任何请求里。→ 病在选取（`_should_translate_
  paragraph` / `pre_translate_paragraph` 的某个短路），须定位到行。

**输出**：18 条逐条分类表（段号、input、output、类别、证据）。**本批只判定
不修**，除非分类结果全部落在单一类且修法是单点（见 T5 的条件分支）。

同法处理 p9 `y1HqM`（`A glacierbuttercupappears on…`）：它不在 declared
page 上、65 字符、`plain text`，与 p5 的行单元不同源，须单独分类。

**为什么不许先修**：我上一轮据 `source_audit` 判定为"源侧字距导致无空格"，
而输出 PDF 的字符流证明空格存在——两个读取器不一致，翻译器读的是第三个字
段。在没有 input 原文之前动手，修的是猜想。

## T2 — b11.1 上游变更的暴露面探测（离线，零 API，决定后续跑哪些样张）

对**六样张的 f3 warm 臂产物**做两项静态计数，产出 `exposure.report.json`：

1. **T1 暴露（恒等短路）**：从 `translate_tracking.json` 数每样张
   `output == input.unicode`（逐字节）的段数，并逐段记其 layout_label 与
   是否曾被重排。这些段在 b11.1 之后**将不再重排**，是行为变更的全部作用面。
2. **T2 暴露（悬挂界）**：从 f3 的 typesetting checkpoint 逐段逐行计算
   `(行末悬挂串右端 − box.x2)`，数出超过 `hang_max_em × font_size` 的行数。
   这些行在 b11.1 之后**将触发回退**，是行为变更的全部作用面。

**跑批范围由此决定**（写进报告，作为本批的范围裁定证据）：
- 两项暴露计数**均为 0** 的样张 → 不跑，报告注明"零暴露"。
- 任一项 > 0 的样张 → 必须跑，与 FD 一同进入 §验证。
- 六样张全部 > 0 → 停并报告，等我裁决是否全量跑（不得自行缩减）。

**附带核对**（b11.1 裁决处置三）：对需要跑的样张，跑后比对
`title_typeset` 的 `floor_reached` / `escalations` 计数相对 f3 是否上升——
悬挂回退多出的行会推高缩放需求，这条耦合只在 FD 见过。

## T3 — 页内跨栏续接：测量批（离线，report-only，零行为改动）

**动机与证据**：FD f3 p6 第 2 栏末段以 `…高度依赖以及` 结尾（句未完），第 3
栏首段以 `这些成本正在加剧…` 开头；源文为
`…fuel imports and rising food and fertilizer` ｜ `costs that are worsening…`
——一个名词短语被栏界劈开、两半各自翻译。跨页链
（`chain_builder` 只遍历相邻**页**对）按构造够不到它。

**做什么**：新工具 `tools/column_continuity.py`（**只读、只出报告，不改任何
段落、不进流水线**），对六样张 f3 产物：

1. 复用 `chain_signals.page_candidates` 的列带推导（`_column_bands` /
   `column_split_gap_ratio`）划栏，取每栏首段与末段；
2. 对每对**列序相邻**的（第 n 栏末段，第 n+1 栏首段）计算跨页链的现成信号：
   `tail_no_terminal_punct`、`tail_line_fill`、`style_continuity`、
   `body_label_pair`；`column_position` 换为页内语义（尾在栏底、头在栏顶）；
   `opener_prior` **置零**（页内无此语义，须在报告里明说而不是硬套）；
3. 英文源另计一条**连字符续词**信号：断尾以 `-` 结束（本批只记录，不并入
   加权，因为它的权重从未被校准过）；
4. 用 f3 的现行权重与 `link_min_score` 打分，输出每对：分数、逐信号值、
   建议判定（会连 / 不会连）。

**必须人工核验**：报告须给出**建议连接的全部对**的双侧文本节选，由我逐对判
真假（这是测量批的产出，不是自动结论）。同时给出**已知真阳性**（FD p6 那一
对）是否被现行权重捕获——若捕获不到，说明权重需要重标定，这个结论比"能连
多少"更重要。

**本批不实现任何页内连接**。

## T4 — 门禁证据的保留策略根修

**问题（模式，非事故）**：b10.1、b10.3、b10.4 三批的断言先后因
`keep_recent_batches: 2` 淘汰证据而转 SKIPPED。fast 集里仍在跑的门禁，其证据
不该被淘汰。

**修法（择一，实现前在报告里说明选择理由）**：
- (a) **豁免在用证据**：保留策略读取 `spec_checks/` 中 fast 集门禁声明的证据
  路径清单，凡在清单内的产物不淘汰；
- (b) **门禁读归档**：门禁改为在工作区产物缺失时回落读
  `docs/reports/archive/<batch>.zip`，读不到才失败。

倾向 (b)：归档本就是入库件，且 b11.1 已证明归档补救可行；(a) 会让输出目录随
批次单调增长。无论择哪条，**已 SKIPPED 的三批断言必须恢复为真实执行**并在
门禁输出中可见——这是本 T 的验收标准，不是附带。

## T5 — 两处小修

1. **Masthead 词表钉住**（b11.1 裁决处置一）：`reviews/FD-en-v2.decisions.json`
   的 terms 段加 `Masthead → 报头`。裁定文件由我签署格式、由执行方写入，写
   入后哈希记入报告。
2. **恒等判据收紧**（b11.1 裁决处置二）：判定改为**逐字节相等**；NFKC 仅用
   于记录，新增计数 `nfkc_equal_not_byte_equal` 与逐段清单（含两串原文）。
   若该收紧使 b11.1 的某个 `F&D` 重新折行，**停并报告该段两串原文**，不得自
   行放宽。

---

## 验证（范围由 T2 决定；离线任务无需跑）

- **必跑**：FD-en-v2（T5 两项的验证面）。
- **条件跑**：T2 判定为有暴露的样张，逐个全文档跑并出完整 PDF。
- **不跑**：T2 判定零暴露的样张；sweep 集（本批不触碰历史门禁锚点，除 T4 外
  ——T4 的验收本身即在 fast 集内可见）。
- 产物入库 `examples/output/b11_2/<sample>/`：完整 PDF、目标页 PNG、
  `run.json`、`exposure.report.json`、T1 判定表、T3 测量报告、
  `conservation.json`、归因行。

## 门禁 `spec_check_b11_2.py`（fast）

1. **T1 判定完备**：18 条残留 + p9 一条，逐条有类别与证据；无 `undetermined`。
   （判定类断言：证据齐备即通过，**不断言分类结果本身**。）
2. **T2 探测完备**：六样张各有两项暴露计数；报告的"跑/不跑"名单与实际跑的
   样张集合**完全一致**（范围裁定可核验）。
3. **T2 回归（对每个实跑样张）**：页数、段数、`pN#k` 与 f3 相同；
   `issues.json` 各 kind 计数不高于 f3；`title_typeset` 的 `floor_reached` /
   `escalations` 不高于 f3，高则报告逐段归因。
4. **T3 只读**：工具运行前后，六样张产物与 IL **逐字节不变**（零副作用的直
   接证明）；报告含建议连接对的双侧文本节选；FD p6 那一对的捕获与否有明确记录。
5. **T4 验收**：b10.1/b10.3/b10.4 的三条曾 SKIPPED 的断言**真实执行并通过**；
   构造一次证据缺失，断言回落归档读取成功。
6. **T5.1**：FD 输出的 p5#0 渲染为 `报头`；裁定文件哈希记入 run.json。
7. **T5.2**：恒等判据为逐字节；`nfkc_equal_not_byte_equal` 计数与清单入
   sidecar；FD 页 5/6/8 的 `F&D` 仍为单行（收紧未引入回归）。
8. **守恒与归因**：`api_calls` = 归因行数；每次真实调用有组名与缓存判定。
9. `run_all --set fast` 全绿（本批因 T4 必须跑 fast 集）。

## 负向范围

改动 ⊆ {
`tools/column_continuity.py`(新，只读)、
`spec_checks/`（新门禁 + T4 的读取回落）、
`configs/`（保留策略键、恒等判据记录字段）、
`babeldoc/format/pdf/document_il/midend/il_translator.py`（仅 T5.2 判据收紧）、
`reviews/FD-en-v2.decisions.json`（仅 T5.1 一条 term）、
`UPSTREAM_DIFF.md`、`WAIVERS.md`、本文件、`examples/output/b11_2/`
}。

`prompts/` 不动一字；`corpus/` 只读；`chain_builder.py` / `chain_signals.py`
**不得改动**（T3 是只读复用，不是改造）；其余裁定文件字节不变。

## §W

- W-B11-04：跑批范围由 T2 的暴露探测决定而非预先声明。理由：b11.1 的上游变
  更影响面未知，用证据收敛优于凭声明缩减。失效：本批结束。
- W-B11-01（承继）：其代价在本批部分结清——结清的部分是"有暴露的样张已
  跑"，未结清的部分是"零暴露样张仍未跑过 b11.1 之后的代码"，须在报告里明写。

## 明确不做

页内跨栏的任何连接实现（视 T3 结果另议）；词界修复（视 T1 判定另议）；修复
层受理面扩类（同上）；首行缩进开关（b11.3）；gate cache LRU；checkpoint I/O。

单 commit，tag `b11.2`（裁决后打）。交付报告须含：T1 十九条判定表、T2 暴露
矩阵与范围裁定、T3 建议连接对全集与 FD p6 捕获结论、T4 选择理由与三条断言恢
复证据、T5.2 的 NFKC 清单、API 归因。
