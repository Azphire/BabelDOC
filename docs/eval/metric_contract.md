# D2 指标合同(batch-e0)

评估阶段每个指标的**唯一定义来源、数据来源、工具状态与归属批次**。本文件是 E1–E4 的合同:
E1 之后任何指标实现若与本表不符,以本表为准或先改本表。

公式出处一律指 `docs/dissertation/background_chapter.tex` 中的 `\label{eq:...}` 标签。
batch-e0 逐一 grep 核对过下表引用的每个标签,可解析。该 `.tex` 已由 batch-e1 会话一入库
(GAP-07 分级入库),`spec_checks/spec_check_e0.py` 的断言 04 每次 sweep 复核一遍标签可解析。

## 1. 合同表

| # | 指标 | 公式出处 | 数据源 | 工具状态 | 批次 |
| --- | --- | --- | --- | --- | --- |
| M1 | mid-unit page-break rate | **新定义**(背景章 `sec:background-layoutmetrics` 小节末段承诺 "a mid-unit page-break rate and a block conservation invariant, defined formally in Chapter~\ref{chap:eval}") | E2 运行的 `checkpoint.11_typesetting` 几何 + `corpus/chain_labels.user.json` 裁定边界 | **需新建**;方法原型是 b5.3 §1b 的末行末字符读法,须从"一条链的两个成员"推广到"每个页边界" | E1 |
| M2 | block conservation invariant | **新定义** | 冻结的链 sidecar 与 react sidecar;E2 运行的前后 checkpoint | **现成需泛化**:链 sidecar 的守恒断言与 `react_repair.report.json` 的 `conserved` 判定已在跑,须提为可跨阶段复用的指标 | E1 |
| M3 | LTCR | `eq:ltcr` | E2 运行的 `checkpoint.09_il_translated` | **需对齐**:`tools/term_consistency.py` 现测的是"该词所在段落中含所选候选串的份额",不是 eq:ltcr 的 $C_k^2$ 成对一致率;须按成对定义正名或另立指标名 | E1 |
| M4 | Overlap | `eq:overlap` | E2 运行的 `checkpoint.11_typesetting` 的 IL box 集 | **近似现成需对齐**:`babeldoc/magazine/detectors/overlap.py` 算的是"段落 vs 图版"的 IoU 且带门限,eq:overlap 是**全体元素两两**的 $A(b_i\cap b_j)/A(b_i)$ 求和、按 $1/N$ 归一、**无门限**。两者不可互换 | E1 |
| M5 | Alignment | `eq:alignment` | 同 M4 | **需新建**:$g(x)=-\log(1-x)$、六坐标最小偏差、按 $1/N$ 归一 | E1 |
| M6 | policy 级一致率 | **既有定义**(页型判定经 `configs/page_types.json` 映射到 policy 后与 `corpus/page_labels.json` 比对) | 已冻结:现行值 0.879 (29/33),见 `docs/eval/evidence_ledger.md` B-04 | **现成**:`spec_checks/spec_check_b2.py` 断言 06c 与 `tools/page_classify_report.py` | E1(只需搬运,不需重跑) |
| M7 | image-area delta | **新定义**(导师图形学指标) | E2 运行的源侧与译侧 IL box 集 | **需新建**;确定性,无 API | E1 |
| M8 | page-count delta | **新定义**(导师图形学指标) | 成品 PDF 页数;上游侧已冻结在 `examples/baseline/manifest.json` | **需新建**(平凡);上游侧数据已在,见台账 F-01 | E1 |
| M9 | image IoU | **新定义**(导师图形学指标) | 同 M7 | **需新建**;可复用 `babeldoc/magazine/detectors/base.py` 的 `intersection_over_union` | E1 |
| M10 | GEMBA-MQM 拼接点标注 | `kocmi2023gemba_mqm` + 本项目的拼接点协议(背景章 §2.7 "targeted microscope") | E2 运行的拼接点对(chain_on / chain_off) | **已建**(batch-e2.2):`tools/splice_judge.py` + `prompts/splice_judge_mqm.md` + `configs/splice_judge.json`,判官 `gpt-5.6-terra`(异族,GAP-03 方案 a);协议 `docs/eval/splice_protocol.md`,细则见 §2e | E2 |
| M11 | d-BLEU(诊断) | `liu2020mbart`(背景章正文,无独立 eq 标签;BLEU 本体为 `eq:bleu`) | 官方中文版作参考;E2 运行的译文 | **需新建**;脚注级,不作主指标 | E2 |
| M12 | BlonDe(诊断,仅 zh→en) | `jiang2022blonde` | Courier-zh 方向的 E2 运行 | **可选**;背景章已声明 en→zh 方向不适用 | E4 |

## 2. 逐指标的合同细则

### M1 mid-unit page-break rate

- **分母**:一次运行中所有相邻页边界数(等于页数 − 1,逐样张计,不跨样张相加分子分母之前先声明口径)。
- **分子**:译文侧页 $n$ 的最后一个渲染框的最后一个非空白字符**不是**句末标记的边界数。
- 句末标记表读自 `configs/chain_detection.json` 的 `terminal_punctuation`,不在指标代码里另写一份。
- **必须从排版后 checkpoint 读**,不能从字符串层读:b5.3 §1b 的整个方法就建立在"按 box 的 y 分行、取末行、读末字符"上。
- 已知边界条件(b5.3 §1b 原文):标题链成员按设计以普通字符收尾(`proportional` 策略,句区间记 `-1/-1`),**须从分子中排除**或单列一档,否则会把设计行为记成缺陷。
- 现有可引的单点实录见台账 A-08。

### M2 block conservation invariant

- 三个层面,合同要求 E1 把三者统一到一个可复用判定下:
  1. **链级**:成员译文按 segment 区间拼接 == 链整体译文,逐字节(台账 A-07)。
  2. **修复级**:`pages` 与 `paragraphs` 计数不变、`changed_refs ⊆ touched_refs`、`changed_outside_touched` 为空(台账 E-02)。
  3. **文档级**:上游基线的页数 1:1 守恒(台账 F-01)。
- 该指标是**布尔不变量而非比率**;论文里报"多少次运行满足",不报平均值。

### M3 LTCR

$$\mathrm{LTCR}(w) = \frac{\sum_{i<j}\mathbf{1}(t_i=t_j)}{C_k^2}\times 100\%$$

- 语料级按 lyu2021ltcr 的做法**分子分母分别求和**,不是逐词平均。
- 与现状的差:`tools/term_consistency.py` 不做词对齐,而是搜一个在该词所在段落中出现最多、
  在同篇其余段落中出现不超过 `candidate_max_outside_share` 的子串,再报"该词自己的段落中
  携带该子串的份额"。这既不是 $C_k^2$ 成对口径,也不保证候选串确实是该词的译名——
  b6.3 自陈 38 行中 4 行候选不可用(台账 G-04)。
- **合同**:E1 要么实现 eq:ltcr 的成对口径并把现有量改名为别的东西,要么显式声明现有量是
  LTCR 的一个无对齐近似并给出两者在同一数据上的差。**不允许把现有数字直接标成 LTCR。**

### M4 Overlap / M5 Alignment

- 元素集合口径必须写死并声明:**取 `checkpoint.11_typesetting` 中每页的 `pdf_paragraph` 的 box**,
  是否纳入 `pdf_figure` / `pdf_xobject` 由 E1 决定并记入本文件(默认:纳入,因为 eq:overlap
  的原始语境是版面元素而非仅文本块)。
- 两者都按 Kikuchi 的 $1/N$ 逐元素归一,不用 Li 的未归一形式。
- 报告口径:**同一份 IL,源侧与译侧各算一次,报差值**;绝对值跨刊物不可比。
- 与 `overlap.py` 检测器**不共享阈值**:检测器的 `overlap_min_iou` 是发现缺陷用的门限,指标无门限。

### M7 / M8 / M9 图形学三件套

- 三者都是确定性几何量,**不消耗任何 API**,因此可以在 E1 直接对已冻结的 checkpoint 跑,
  不必等 E2 的新运行。凡能在冻结产物上算的,E1 就算,写进台账。
- M9 的匹配规则须声明:源侧与译侧图像按什么配对(建议按页内序号 + 面积最近邻),
  以及未配对图像如何计入。

### M10 GEMBA-MQM 拼接点标注

- **协议**:标注单位是"拼接点",不是文档。每个拼接点给判官三段材料——页 $n$ 尾、页 $n+1$ 首、
  以及源文对应区间——问"拼接是否引入了 omission / mistranslation / fluency break"。
- **必须走统一缓存客户端**(CLAUDE.md §4.8),cache key 含 prompt 文件哈希;prompt 进 `prompts/`。
- **judge 模型**:**已定为 `gpt-5.6-terra`**(batch-e2.2,GAP-03 方案 a 异族判官);同源偏倚
  因此不适用,代价按 GAP-03 原文由人工抽验承担。
- 样本量上界由语料决定:全语料 5 条 link 边界 + 30 条 no-link 边界(台账 A-04)。
  **5 条正样本不足以支撑比率型主张**,GEMBA-MQM 在本项目里是定性微镜而非统计量。

### M11 d-BLEU / M12 BlonDe

- 参考侧只有 Courier 一刊有官方中文版,且背景章已定性为 **editorial adaptation**,
  故两者一律标"诊断",不进主结果表。
- M11 的参考原件当前**不在树内**(台账 A-15),须先重新取回并记哈希。

## 2b. batch-e1 会话一的实现决议(本表授权的裁量点,已定案)

实现落在 `babeldoc/magazine/metrics/`,参数在 `configs/metrics.json`(每项带 allowed_range),
统一入口 `tools/eval_report.py`;M2 落在 `babeldoc/magazine/metrics/conservation.py`。各指标的 LaTeX 定义随模块 docstring 给出;
沿用已有公式者只引本表第 1 节列出的公式标签,新定义者自成一式(E4 收编进论文)。

1. **M1 的边界口径**(`babeldoc/magazine/metrics/mid_break_rate.py`):合同的分母(页数 − 1)为**主序列**;`plans/PLAN_E1.md` 另要求的
   **栏边界**作为**第二序列**并列输出,分母为逐页"栏数 − 1"之和,两序列不混算。
2. **M1 的 tail 定义**:页 N 的 tail 取 `chain_signals.page_candidates` 派生阅读序的**最后一个
   端点候选**,而非最后一个盒——与链检测器共用同一口径,否则指标与检测器谈的不是同一条边界。
3. **M1 的 by-design 档**:合同允许"从分子中排除或单列一档",本实现**两者都做**:`designed`
   自成一档(链成员、后继成员存在、句区间记 `-1/-1`),`rate` 保留合同分母,`strict_rate` 从
   分母中扣除 `designed`。另有 `axis_unsupported`(竖排 tail)与 `no_tail` 两档,不进任何分子。
4. **M3 的 $t_i$ 代理**(`babeldoc/magazine/metrics/ltcr.py`):本项目无词对齐,`eq:ltcr` 的 $t_i$ 由候选串迭代分组导出(每轮取最广
   共享的区别性子串,覆盖到的段落成一组,剩余段落再来一轮,无人共享者自成单元素组),
   $\mathrm{LTCR} = \sum_t C(m_t,2)/C(k,2)$。旧量(b6.3 的 $m_1/k$)以 `legacy_share` 并列输出,
   **不得标为 LTCR**。两者关系已证并进门禁:`LTCR ≤ legacy_share`;`LTCR = 1 ⟺ legacy_share = 1`;
   `LTCR = 0 ⟺ legacy_share = 1/k`。两者在 $k=2$ 时**不**相等(无共享译名时旧量记 0.5、
   LTCR 记 0),这一差正是成对口径的代价,论文引用时须只引 LTCR。
5. **M4 / M5 的元素集**(`babeldoc/magazine/metrics/layout_geometry.py`):`pdf_paragraph` 的 box **∪** 图像元素,图像取 `pdf_figure` 与
   `page_layout` 中 `class_name` 落在 `configs/metrics.json` 的 `image_layout_classes` 内者
   ——语料上 `pdf_figure` 恒为空,图像全部以 layout 区域形式存在。**排除 `pdf_xobject`**
   (容器,其内容已被计入)与文本类 layout 区域(段落由其派生,计两次)。
6. **M4 / M5 的坐标**:按页框(cropbox,无则 mediabox)归一到单位页;Kikuchi 的 $1/N$ 逐元素
   归一;`g(x) = -\log(1-x)` 的定义域由 `alignment_max_delta` 夹断,元素数 < 2 的页返回
   `None` 而非 0.0。
7. **M4 / M5 的报告口径**:源侧取 `checkpoint.08_chain_builder`(翻译前最后一个 checkpoint,
   段落与盒已就位),译侧取 `checkpoint.11_typesetting`,报两侧与差值。
8. **M9 的配对规则**:源侧图像按页内序号遍历,取面积比最接近的未配对译侧图像,面积比超过
   `image_pair_max_area_ratio` 者拒绝配对;并列时以译侧页内序号定序。未配对图像按 IoU 0
   计入分母(分母 = 两侧图像数的较大者)并在报告中单列。

## 2c. batch-e1.2 会话二的实测裁定(冻结产物计算)

本节的每个数字都由 `tools/eval_report.py` 的 `--corpus` 模式在冻结产物上算出,落盘于
`docs/eval/results_e1/`(逐样张 `eval_report.<sample>.json`,汇总 `eval_corpus.json` 与
`eval_corpus.md`)。零 API、零翻译运行。

### 2c.1 M1 分层输出(本会话授权追加)

每条页边界按 `corpus/chain_labels.user.json` 的裁定归入三档,归档规则写在
`babeldoc/magazine/metrics/mid_break_rate.py` 的 `adjudications_of`:

| 档 | 判据 | 语义 |
| --- | --- | --- |
| `linked` | `link=true` | 语义单元被切断,续接就在下一页。此处 open 是本项目要治的缺陷 |
| `trap` | `link=false` 且 note 含 `configs/metrics.json` 的 `truth_trap_markers` 声明标记 | 悬尾的续接**不在文档内**(节选跳页)。任何生产者都无法闭合 |
| `clean` | 其余 `link=false` | 源侧本就句末收束。此处 open 是排版侧引入的 |
| `unlabelled` | 裁定单无此边界 | 既不进主数分母也不进 trap 计数 |

- **主数** `mbr_linkable` = open(linked ∪ clean) / (answerable(linked ∪ clean) − designed),
  即合同 strict 分母限制到"生产者应答"的边界上;
- `mbr_all` 保留合同分母(页数 − 1),两者并列;
- `source_inherited_open` = trap 档的 open 计数,**不进任何分子**,单列。

无裁定单的样张 `stratified` 记 `null`,不给默认分层。逐档完整判决计数一并落盘,任何其他
分母都可从记录复算。

### 2c.2 上游几何路径与方法差异(合同细则 M4/M5/M7/M9 的补充)

上游六份基线只有 PDF,没有 IL。`babeldoc/magazine/metrics/pdf_geometry.py` 用 PyMuPDF 把 PDF
重建为最小 IL 文档(一个文本块 → 一个 `pdf_paragraph`,标签取 `pdf_block_label`;一张位图 →
一个 `pdf_figure`;坐标翻转到 IL 的下左原点),因此**同一套指标代码**同时跑两条路径。

方法差异在 fork 自己的产物上定量:同一份译后 PDF,一路走 IL(`checkpoint.08_chain_builder` 对
`checkpoint.11_typesetting`),一路走 PDF 抽取(输入 PDF 对译后 PDF)。判定门限
`method_comparable_max_relative_delta = 0.1`(相对偏差按两读数中较大者归一)。六样张实测:

| 指标键 | 可比样张数 | 相对偏差范围 | 裁定 |
| --- | --- | --- | --- |
| `overlap_source` | 0/6 | 0.571–1.000 | **not-comparable** |
| `overlap_produced` | 0/6 | 0.488–1.000 | **not-comparable** |
| `overlap_delta` | 1/6 | 0.000–1.010 | **not-comparable** |
| `alignment_source` | 2/6 | 0.000–0.913 | **not-comparable** |
| `alignment_produced` | 0/6 | 0.245–0.899 | **not-comparable** |
| `alignment_delta` | 0/6 | 0.996–1.200 | **not-comparable** |
| `image_area_delta` | 4/6 | 0.000–1.000 | 有条件可比(见下) |
| `image_placement_iou` | 6/6 | 0.000–0.039 | 可比 |
| `mid_break_rate.rate` | 3/6 | 0.000–0.600 | 比率不可比;判决级 30/35 一致 |

三条结论,均按实测写,不硬凑:

1. **M4 Overlap 与 M5 Alignment 的上游列记 not-comparable。** 两条路径的元素集不是同一个划分:
   PDF 抽取的文本块数对 IL 段落数的比值实测 1.00–1.72(逐样张 140/199、43/62、217/255、
   165/283、211/210、142/154),而 eq:overlap 与 eq:alignment 都按 $1/N$ 归一,元素数直接进分母。
   论文中上游与 fork 的 Overlap/Alignment **只能在同一条路径内比**(即两侧都走 PDF 抽取),
   跨路径的差值不得出现。差异也不是一个可校正的固定偏置:`overlap_produced` 在稀疏页上
   PDF 路径更低(Vogue-en 0.126→0.000、Courier-zh 0.026→0.000,抽取块本就互不重叠),在密排页上
   PDF 路径更高(CERNCourier-en 0.164→0.340、AramcoWorld-en-v2 0.049→0.432,图像 bbox 压在文本块上),
   方向随版面翻转,故不存在"乘一个系数换算过去"的选项。
2. **M7 与 M9 可比。** `image_placement_iou` 六样张全部在门限内;`image_area_delta` 两处出界
   (CERNCourier-en、AramcoWorld-en-v2)都是"两读数皆≈0"的情形——IL 侧恒为 0.000000,PDF 侧
   为 0.0003 与 −0.0045,相对度量在近零处失效而绝对差 ≤0.0045。这两处按绝对差报告,不按相对
   偏差判不可比。
3. **M1 的比率不可跨路径比,判决可比。** 逐边界判决一致率 30/35(0.857):Courier-en 6/7、
   Vogue-en 2/2、CERNCourier-en 3/3、AramcoWorld-en-v2 7/8、FD-en-v2 5/8、Courier-zh 7/7。
   分歧全部出在 tail 选取:IL 路径按 `layout_label` 过滤版面家具,PDF 路径没有标签可读,页码条、
   图注栏与版权竖排因此可能充当 tail(FD-en-v2 的 3 处分歧即此)。故上游 M1 **以逐边界判决表**
   进论文(见 `eval_corpus.md` §3),比率只在同路径内引用。

### 2c.3 IL 路径的 before/after 几何差值是结构性零

实测:六样张的 fork IL 路径中,四份的 `overlap_source` 与 `overlap_produced`、
`alignment_source` 与 `alignment_produced` 在 6 位小数上**完全相等**(Courier-en 0.018821、
Vogue-en 0.125767、AramcoWorld-en-v2 0.049050、Courier-zh 0.025811),另两份(CERNCourier-en、
FD-en-v2)差在第 4 位小数。原因是排版阶段沿用源段落框、只在框内重排行,段落 box 基本不变。

**因此:M4/M5/M7/M9 的"源侧 vs 译侧差值"若从 IL 读,测的是段落框的账面而不是落墨后的版面。**
译前译后的版面变化一律从 PDF 路径读(两侧同一抽取器,抽取方法在差值中抵消);IL 路径的绝对值
仍可用于同一路径内的横向比较。该判定不改任何已有定义,只规定读数来源。

### 2c.4 M1 的判别力边界(A-09 的对照)

Courier-en 的 `7->8` 是裁定单里的 MID-SENTENCE BODY SPLIT。三列实测判决全部是 `closed`:
上游末字符为 `。`(译文把悬空从句**虚构收束**为"…以及一种复合材料。",即台账 A-09),fork
末字符也是 `。`(链级联合翻译重排后的真实句末,"…了专利。")。**M1 作为几何量无法区分
"真收束"与"虚构收束"**,该边界上的优劣判定必须由 A-09 的语义证据(先行词丢失、悬空从句)
承担,不得只引 M1。反例是 AramcoWorld-en-v2 的 `6->7`(同为 linked):上游 `open`、fork
`closed`,该处 M1 独立成立。

## 2d. batch-e2.1 的链 A/B 实测(R1 三跑)

E1.2 遗留 1 是"冻结产物里没有 chain_on/chain_off 的指标级 A/B"。R1 三跑补上了:
`chain_off ×2 + chain_on ×1`,同一全栈配置只差一个开关,六列(三臂 × IL/PDF 两路径)在
`docs/eval/results_e2/eval_report.Courier-en.json`,表在 `docs/eval/results_e2/README.md` §4。
本节只写它对**合同本身**的三条补充,数字进台账 A-20。

1. **M1 在链 A/B 上零判别力,§2c.4 的边界因此扩大。** §2c.4 此前只证到 Courier-en `7->8`
   在"上游 vs fork"两列都 closed;R1 证到**同一 fork 的开关两态也都 closed**,且三臂七条
   边界的逐边界判决**逐条相同**,`mbr_linkable` 三臂同为 0.4000(IL)。这一次两侧是同一套
   排版代码与同一条读数路径,排除了"两条路径口径不同"这一解释:M1 分不出"虚构收束"与
   "真句末",是指标本身的性质而非方法学噪声。**该边界的优劣一律引 A-09 的语义证据**,且
   A-09 可引的那一半以 GAP-13 重述后的措辞为准。
2. **M3 的臂间差小于跑间方差,本语料上不作 A/B 用。** LTCR 三臂 0.482143 / 0.428571 /
   0.446429,**两个 off 臂之差(0.0536)大于 off 与 on 之差(0.0357 与 0.0179)**,而三臂
   的合格词条数都只有 3。合同第 1 节把 M3 列为主指标之一;在本语料的词条规模下,它对开关
   两态没有分辨力,论文引用 LTCR 时须与该事实一并陈述。
3. **M2 的 `absent` 与 0 必须分开读。** 两个 off 臂没有 `chain_translation.report.json`,
   链级那一层记 `absent`——开关是关的,没有链可守恒,与"守恒失败"是两件事。三臂的文档级与
   修复级守恒全部 hold(8→8 页、132→132 段)。

## 3. 本合同不涵盖

- 任何人工评分量表(MQM 人工评审的 rubric 属评估章,不属本表)。
- 任何模型选型/成本指标(成本数字在台账 A-14、D-08、E-04、E-11、F-01,不是"指标")。
- 显著性检验:本项目所有 A/B 均为单跑冻结重放,显著性主张须先有三跑设计,见
  `docs/eval/gap_register.md` GAP-01。

## 2e. batch-e2.2 的 M10 实测裁定(R2 判官跑)

M10 在第 1 节只有一行"需新建"。本节写它落地后对**合同本身**的补充,协议全文在
`docs/eval/splice_protocol.md`,数字进台账 A-22~A-24。

1. **标注单位与 M1 的 tail 共用同一口径。** 合同 §M10 只说"页 n 尾、页 n+1 首、源文对应
   区间"。实现把"页 n 尾"钉死为 `chain_signals.page_candidates` 派生阅读序的**最后一个端点
   候选**,即 §2b.2 给 M1 定的那一个;"页 n+1 首"是同一序列的第一个。因此几何判决(M1)与
   语义标注(M10)谈的是**同一条边界**,双证表可以左右并读,而不是两张各自定义边界的表。
2. **样本量上界比合同写的更紧。** 合同说"5 条正样本不足以支撑比率型主张";实际运行的点集
   **就是**那 5 条,臂展开后 14 行,**且没有负控**(30 条 `link: false` 未跑)。所以 M10 在
   本项目里连"判官能否分辨好坏拼接"都未验证,只验证了"在被裁定切断的边界上判官报出了
   什么"。论文引用 M10 一律作定性微镜,**不合成 MQM 分数**(与 kocmi2023 的偏离之一,
   协议 §6.1)。
3. **上游列与 fork 列的窗口来自两条读数路径。** upstream 无 IL,窗口经 PyMuPDF 抽取重建;
   fork 各臂从 `checkpoint.11_typesetting` 读。G-07 已裁定几何比率跨路径不可比;对**窗口
   文本**,两条路径抽的是同一批字符,但 tail 选取的一处分歧就能换掉整个窗口,故 M10 的逐点
   跨臂比较须连同各行的 `origin` 一起引。
4. **`Courier-zh` 的 fork 臂不是方向对照。** 上游那一跑是 zh→en,而 b8.4 全栈那一跑对该样张
   走 en→zh,落在中文文档上等于未译(135 段中 45 段与源文逐字相同)。该样张的 M10 两行只能
   各自作产物观察。zh 校准是 PLAN_E2 明确不做的事。

### 2e.1 人工裁决后的两条追加(batch-e2.2 会话二后半)

5. **M10 的有效集口径。** 人工裁决(`docs/eval/results_e2/splice_manual_review.json`)发现
   窗口选取取的是**页几何端点**,而展示标题切断被裁定的是两个 display 段落:两个 `2->3` 点的
   6 行没有测到被裁定的切断,标 `PROTOCOL-INVALID` 并排除。**M10 的有效集因此是 8 行 / 3 点**
   (`Courier-en 7->8` 四臂、`AramcoWorld-en-v2 6->7` 两臂、`Courier-zh 7->8` 两臂),论文的
   M10 主证据只能取这 8 行,判官与人工的一致率报 **6/8**。缺陷登记为 GAP-14。
6. **M1 与 M10 共用同一个 tail 口径,因此共享同一个局限。** §2b.2 把 M1 的 tail 定为"阅读序
   最后一个端点候选",M10 沿用它;而 `chain_signals.page_endpoints` 本就**逐类**给出端点
   (running text 与 display 行结束在不同地方)。展示标题切断上,两个指标谈的都不是被裁定的
   那对单元。**这不改 M1 的定义**——定义写的就是"最后一个端点候选",数字照旧成立——但引用
   `2->3` 这类边界的 M1 判决时须加此限定(台账 A-16)。修法与 M10 同(GAP-14),届时两处
   一起改,否则两个指标会谈两条不同的边界。

## 2f. 重放边界(batch-b9.5 会话一追加)

第 1 节与 §2d 把"A/B 以缓存冻结重放为准"作为全部对照的前提。该前提有一处例外,写在这里
一次,此后引用不再重述:

> 修复环决策按设计绕缓存,为流水线唯一不可重放环节;跨跑差异按归因地板处置(E2.1 与 b9.4
> 两次实测)。

含义与出处:`babeldoc/magazine/react/decide.py` 的 `EngineTransport` 以 `ignore_cache=True`
调用引擎,决策自带的缓存以**请求全文**为键,而请求全文含当次检出的全部 finding 及其证据。
因此上游任何一处差异都换掉键,决策重新采样。E2.1 实测 `gpt-4o` 在 `temperature=0` 下非
确定(GAP-01),b9.4 实测同一份文档的三臂在同一个 finding 上作出不同决策,导致一处未声明
页的成品差异(`docs/eval/gap_register.md` GAP-20 的同一归因口径)。两次实测的处置一致:
差异逐页归因,归因地板下无未解释项即成立,不主张逐字节封闭。

