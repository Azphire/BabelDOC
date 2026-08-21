# PLAN B10.4 — 人名三档策略、人名词表化（复用上游通道）、长度地板例外、Courier-zh 裁定

前置：batch tag `b10.3`（59c7708）。规格即当次 prompt。W-B10-01..04 适用。
本批含一个**人在环节点**：草案导出后暂停，等待用户裁定，随后消费并复跑。
Cost 声明见 §Cost；**parity 白名单按批圈定**（b10.3 长效规则：翻译缓存按批
不按段，任何请求变更的爆炸半径为共享 prompt 的整批）。

## 前提校验（任一不符即停）

1. 上游能力边界（论文边界句的代码证据，全部核实并记行号入报告）：
   a. `automatic_term_extractor.py` 与 `glossary.py` 存在于 fork 基线：
      `git log 17480db9 -1 -- <两文件>` 有输出。若空——停，报告版本归属，
      本批机制不变但报告措辞改按 concurrent work。
   b. `hitl.py:28–40`：裁定对入用户词表列表、自动槽清空的单执行点机制在。
   c. 上游风格面仅 `custom_system_prompt` 自由槽（translation_config.py:197）
      与默认单句 system prompt（translator.py:289）；无人名类策略键。
2. `configs/translation_style.json`：现行结构为按目标语言的角色文本表，
   `person_names` 现值 `transliterate`；两份文本的 SHA-256 与 runs.json 在案值
   一致（**zh 目标** 74666d71…、**en 目标** 6f5e4231…；初稿标签互换，已按
   b10.4 前提报告更正）。
3. `min_text_length = 5` 的读取点与作用面：Courier-zh p1 七个栏目标签（<5
   全挡，实测成立）、Vogue p3 存留簇 10 段（实测成立）。初稿第三项
   （Markelova 署名）经定位为假——该段 23 字符、已在请求并落字——撤销，
   不入任何断言。
4. Courier-zh 分类现状（F2 在案）：p1 落 `sidebar_heavy`、6/8 页与 en 版异类、
   7 边界 0 链、2 brief；hitl 页类裁定通道可导出可消费（Courier-en p1 先例）。
5. 标题链切点当前不可裁：`reviews/*.decisions.json` 无该类型；chain_backfill
   的 display 链切点为 proportional + any_char（GAP-18）。
6. b10.3 交付在案：重放 9 次修复环调用未定性（rider R1）。

## T1 — 人名三档策略（机制本批落地，默认档行为冻结）

`person_names` 词表扩为 `{translate, keep, annotate}`：
- `translate`：全译，**不带**备注（en→zh 音译、zh→en 罗马化）。
- `keep`：全保留原文。
- `annotate`：译名（原名），备注仅限**翻译单元内首现**；链/文章级不重复挂注。
配置升为策略 × 目标语言矩阵 `person_names_policies.<policy>.<lang>`，逐段角色
文本、逐段 SHA-256 钉住、词表与结构校验同 by_target 惯例。编译进
`custom_system_prompt` 槽的既有逻辑不变；runs.json 记选中策略与哈希。

三段文本共同的明文条款：**词表优先于策略**——`keep` 档下词表命中仍按词表
落字（裁定永远赢）；`annotate` 的备注为异形括注，与 paren_dedup 的同形折叠
互不相干（构造用例入门禁）。

**冻结约束**：默认档沿用现行 `transliterate` 文本，**逐字节不动**（F3 可比性；
现行文本语义近 `annotate` 宽松版，归档标签问题 F3 后议）。`keep`/`annotate`
的行为级验证（真跑样张）明确**不在本批**——每档一跑即全量真实请求；排 F3
后特性批，届时出三档对照表。本批门禁到编译层为止。

## T2 — 人名收割入词表，注入端零新建

en→zh 三样张的未归属页（masthead/toc）：
- 收割：**确定性**模式（拉丁大写词序列、长度与词数界、排除词表命中与纯机构
  词形——规则与旋钮入 `configs/name_harvest.json`），不用 LLM 收割。
- 音译：每样张一次批请求，新 prompt `prompts/name_transliterate.md`（全文入
  库，SHA-256 登记入 Registry 惯例位），产出 source→target 对。
- 入口：候选对与抽取器条目按 `source` **合并为单一 terms 表**（批内修正案
  rev2，裁决在案）：人名形条目的 `auto_target` 与候选集由**当前
  `person_names` 策略派生**，禁止硬编码任何一档——
  translate/现行 transliterate 档：默认 = 音译，候选含原文；
  keep 档：默认 = 原文，音译入候选位（例外翻译时免手写）；
  annotate 档：默认 = 译名（原名）组合形，候选含原文与纯音译。
  模型观测值一律移新字段 `observed_target`（保留 `vote_count` /
  `translator_view` 作审计）。非人名形条目不进派生表，语义不变（auto_target
  = 观测值，一致性钉住）。消费语义：未裁按 `auto_target` 落地（**任何档下
  默认即该档语义，零人工**），裁定为覆盖；decided-pairs 单执行点不变——
  **不建第二注入通道**。草案 `format_version` 1→2，向后兼容 v1。

## T3 — 长度地板形状例外（孤行判据保留）

`min_text_length` 增形状例外（`configs/` 有界声明）：name-shaped（拉丁人名
形）与 label-shaped（≤N 字符、**独占行带**的短段，N=`short_label_max_chars`，
默认 8）地板降至 2。孤行判据为裁定保留项：独立行带的完整语义单元（社论/
广角类）是例外的目标形状；同带并排的词下碎屑（Wh/e/th 类）不得逐条成请求
——它们归 T3b。作用面：Courier-zh p1 七标签、署名类孤行短段。该变更改请求
集合——受影响**批**入白名单。

## T3b — H 规则对行结构页解禁（measure-then-apply）

b10.3 对 `preserve_line_structure` 页的整页排除对 V 规则正确（纵向缝合可并
记录）、对 H 规则过宽（H 仅同行带作业，按构造不跨记录边界）。分两步：

（措辞更正：初稿"源提取双流交错"为误——源为单语，交错是输出层假象：未
译碎屑与邻段译文的盒同带穿插。干跑判定程序升级为**源审计三分类**。）

1. **源审计**（新工具 `tools/source_audit.py`，确定性、零 LLM，PyMuPDF 既有
   依赖）：对目标页做三测——(i) 独立提取交叉核对（PyMuPDF 词流 vs IL 字符
   集的 token 级覆盖：独立现一次而 IL 现两次 = 重复层；IL 缺 = 丢字；序异
   = 提取序故障）；(ii) 几何连贯性（段内阅读序单调性、段间同带穿插度）；
   (iii) 碎屑溯源（文本为同带邻段区间之重复 → **B 重复层**；与邻段拼接恰补
   全独立提取之 token → **A 真碎裂**）。逐碎屑三分类 sidecar 入库。
2. **按类施加**：A 类 → H 规则缝合（含单元守卫）；B 类 → 判重**置空**（复
   用置空机制，证据 = token 重复证明；缝合对 B 类是错的——会拼入重复文
   本）；提取序故障类 → 不动，定性入报告（上游解析层，F3 后议，limitation
   素材；候选为静默失败第八通道"解析层"的立项证据）。
3. 无一碎屑可归 A/B（审计不确定）→ 不施加，开关保持关。

安全负向（各分支共同）：Courier-en p1 与 CERN p2 的记录账目与 b10.3 基线逐
段相同（解禁与置空均不得触碰记录页既有产出）。

## T4 — Courier-zh 裁定（人在环节点）

1. `hitl_export` 对 Courier-zh 出草案：页类逐页候选 + T2 同款收割的反向
   （zh→en：中文人名→罗马化候选）。
2. **暂停，用户裁定**（页类至少裁 p1；人名候选按需）。
3. `hitl_apply` 消费后复跑 Courier-zh 全文档。

`chain_cuts` 可裁类型**本批缓建**：T5 的默认机制关闭语料内唯一案例后零需
求；类型留 F3 后按需补（登记入报告"缓建项"）。

## T5 — display 链切点：对齐估计 + 边界吸附 + 比例兜底（zh 目标侧三级级联）

问题：源切口在英文词界（drives | scientific），任何把**源字符比例**转移到无
空格中文的做法都无理由落在词界，更无理由落在**对齐**的词界（GAP-18）。三
级级联，逐级 fail-soft：

1. **对齐估计**：display 链每源片段发一条辅助翻译微请求（可缓存，temp=0），
   **只取译文长度**构成比例，对联合译文估计切点并钳制到 [1, len−1]。硬守
   卫：辅助译文的**文本一律不用**——链输出唯一来自联合翻译（b5.3 教训、
   承诺 (2) 完整性）；sidecar 记两片辅助长度与估计点。
2. **边界吸附**：估计点 ±`cut_snap_radius`（默认 2，range 0..4）内吸附
   (a) 标点之后、(b) `cut_boundary_markers`（按语言声明的封闭类功能词小词
   表，configs 内可裁剪）成员之后；多候选取最近。
3. **比例兜底**：辅助请求失败或 `magazine_chain_cut_align` 开关关闭时回落
   纯比例（现行为），级联不劣化。

已知失效模式写入 config 描述：联合译文跨界倒序时不存在对齐切点，级联退化
为比例 + 吸附，损害封在半径内。en 目标侧不动（空格吸附已由 break_rule 覆
盖）。预期结果："土著知识如何推动 | 科学发现"（drives 的译文留在其源行）。

## Rider R1 — 重放 9 调用定性

对 b10.3 重放的 9 次修复环调用：dump 两 run 的 key 输入并 diff，定性（浮点
抖动/首见未缓存/其他）入报告；**只定性不修**，修法挂 b11 或 F3 后。

## §Cost

新增真实调用：音译批请求（每样张 1）+ T3 放行的短段所在**批** + T4 复跑
Courier-zh 中因裁定与词表变更的批 + 词表命中段所在批（词表注入改 prompt，
整批换新）。白名单按批列举，清单外逐字节同 b10.3 基线。另加 display 链辅助翻译微请求（全语料 +2）。预估中位一百至二百
调用，归因行逐条对账。

## 验证（全文档重放，证据界定到目标页）

| 样张 | 目标页 | 看什么 |
| --- | --- | --- |
| AramcoWorld-en-v2 | 2 | masthead 人名落字（词表路径） |
| FD-en-v2 | 5 | 编辑板人名 |
| Vogue-en | 3 | T3 后存留簇终态（b10.3 挂账复测） |
| Courier-zh | 1, 2, 3, 5 | 裁定消费：p1 目录行结构、p2/3 链、切点、标签落字 |

产物入库 `examples/output/b10_4/`：局部 PDF、目标页 PNG、草案与裁定文件
（哈希钉住）、词表消费 sidecar、parity（按批白名单）、归因行。

## 门禁 `spec_checks/spec_check_b10_4.py`（fast）

1. 矩阵编译：3 策略 × 2 目标各选中正确文本、逐段 SHA 相符；默认档编译产物
   哈希 = F2 在案值（冻结的直接证明）；词表/结构校验拒绝用例各一。
2. 收割确定性：同输入两次收割集合相等；**策略参数化断言**——当前档
   （transliterate）下 AW 草案 29 条人名形默认 = 音译、候选含原文、
   `observed_target` 保留；以配置切换构造 keep 档**干跑草案**一份（仅草案
   层，不消费不翻译——默认档冻结不破），同批条目默认 = 原文、候选含音译；
   **不裁直接 apply** 路径下（当前档）人名音译落字；v1 解析回归；裁定后进
   用户词表槽、自动槽清空（单执行点断言）。
3. 落字：AW p2 / FD p5 点名人名按裁定词表落字（提取文本断言）；annotate 异形
   括注构造用例不被 paren_dedup 折叠。
4. T3/T3b：Courier-zh p1 七标签出现在请求且译文落字；地板例外仅命中声明形
   状（负向：普通短句与同带碎屑均不放行）。T3b：源审计三分类 sidecar 入库
   且每片碎屑有类别与证据；A 类缝合后 Vogue p3 簇数下降、无新增 <5 请求；
   B 类置空后该文本在提取文本恰现一次（去重正向）；不施加分支断言开关关闭
   + 定性在档；各分支均断言 p1 / CERN p2 记录账目与 b10.3 逐段相同。
5. T4/T5：Courier-zh brief 数 ≥ 6、p2/3 跨页链成链；"土著知识"链切点落于
   "推动"**之后**（对齐正向，提取文本断言）；sidecar 载两片辅助长度与估计
   点；关闭 `magazine_chain_cut_align` 重放，切点 = 比例 + 吸附（兜底负
   向）；en 目标链切分与 b10.3 基线相同（方向负向）。
6. parity：白名单（按批）外逐字节同 b10.3；`api_calls` = 归因行数。
7. 门禁通篇不引用任何 debug_id（本批起 CLAUDE.md §6 新规，规则行随本批
   commit 落）。
8. `run_all --set fast` 全绿。

负向范围：改动 ⊆ {`babeldoc/magazine/`（translation_style、hitl、
chain_backfill、fragment_stitch、name_harvest 新）、`configs/`、`prompts/name_transliterate.md`
(新)、`spec_checks/`、`tools/source_audit.py`(新)、`reviews/Courier-zh.decisions.json`(经裁定流程产生)、
CLAUDE.md §6 一行、本文件、`examples/output/b10_4/`}；上游零改动；既有
prompts 不动一字（含默认档角色文本，字节断言）；真值只读；其余裁决文件字节
不变。

## 明确不做

`keep`/`annotate` 行为级跑批（F3 后特性批 + 三档对照表）；zh 分类器词表重调
（裁定通道即本周期答案）；翻译缓存段粒度化（b11）；重放 9 调用的修复（R1
只定性）；默认档文本改档。

单 commit，tag `b10.4`（裁决后打，恢复默认序）。交付报告须含：批内修正案执行记录、前提 1 的行号
表与版本归属结论、收割候选全集与裁定对照、R1 定性、T3b 干跑表与分叉裁定、按批白名单实测。
