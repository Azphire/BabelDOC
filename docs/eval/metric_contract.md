# D2 指标合同(batch-e0)

评估阶段每个指标的**唯一定义来源、数据来源、工具状态与归属批次**。本文件是 E1–E4 的合同:
E1 之后任何指标实现若与本表不符,以本表为准或先改本表。

公式出处一律指 `docs/dissertation/background_chapter.tex` 中的 `\label{eq:...}` 标签。
本会话逐一 grep 核对过下表引用的每个标签,可解析。该 `.tex` 目前**未入库**(见
`docs/eval/gap_register.md` GAP-07)。

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
| M10 | GEMBA-MQM 拼接点标注 | `kocmi2023gemba_mqm` + 本项目的拼接点协议(背景章 §2.7 "targeted microscope") | E2 运行的拼接点对(chain_on / chain_off) | **需新建**:缓存判官,**judge 模型待用户定**(见 gap GAP-03) | E2 |
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
- **judge 模型**:待用户决策。同源偏倚(judge 与被测同为 gpt-4o)是已知风险,见
  `docs/eval/gap_register.md` GAP-03。
- 样本量上界由语料决定:全语料 5 条 link 边界 + 30 条 no-link 边界(台账 A-04)。
  **5 条正样本不足以支撑比率型主张**,GEMBA-MQM 在本项目里是定性微镜而非统计量。

### M11 d-BLEU / M12 BlonDe

- 参考侧只有 Courier 一刊有官方中文版,且背景章已定性为 **editorial adaptation**,
  故两者一律标"诊断",不进主结果表。
- M11 的参考原件当前**不在树内**(台账 A-15),须先重新取回并记哈希。

## 3. 本合同不涵盖

- 任何人工评分量表(MQM 人工评审的 rubric 属评估章,不属本表)。
- 任何模型选型/成本指标(成本数字在台账 A-14、D-08、E-04、E-11、F-01,不是"指标")。
- 显著性检验:本项目所有 A/B 均为单跑冻结重放,显著性主张须先有三跑设计,见
  `docs/eval/gap_register.md` GAP-01。
