# D1 证据台账(batch-e0)

评估阶段可引数字的逐条清点。本批次不实现任何指标、不发起任何翻译运行:每一行的数字
都是**本会话现场从其出处文件重新读出并核对过的**,不从记忆或历史会话报告转录。

## 使用约定

- **出处**列写作 `tag · 路径` 加定位(行号或小节号)。路径一律以仓库根为基准,写在反引号内。
- 行号写在反引号**外**(`path`:482),因为行号会随文件重写漂移而路径不会。
- **状态**取四值之一:

  | 状态 | 含义 |
  | --- | --- |
  | `直接可引` | 数字有现存出处,本会话已核对,可直接写进论文(附带列出的限定语) |
  | `需三跑` | 数字存在且正确,但其**因果归因**在当前设计下不可分辨,须三跑设计才可作断言 |
  | `needs-recompute` | 出处产物已不在树内,或从未落盘;数字不得引用,须按指定来源重算 |
  | `需重述` | 数字本身可引,但现有措辞与产物不符或已被后续批次推翻,须改写后再引 |

- **入库**列取 `git` / `worktree` / `none`:`worktree` 表示该出处文件只存在于工作区、未进任何
  tag,一次 clone 就会失去(`tools/prune_outputs.py` 的保留策略本身不会删它们,见 D3 GAP-07);
  `none` 表示该数字从未落盘。

<!-- status-vocabulary: `直接可引` `需三跑` `needs-recompute` `需重述` -->
<!-- provenance-vocabulary: `git` `worktree` `none` -->

- 语料换血(batch-b7.5.1)把 `AramcoWorld-en` / `FD-en` 换成了 `-v2` 长节选,页数与边界数都
  变了。凡跨换血的数字一律**同时列 v1 与 v2**,并注明论文里该引哪一个。

## 已失效产物登记(负向断言区)

下列路径在其批次报告里被引用过,如今**不在树内**。它们是 `configs/output_retention.json`
的保留策略按设计淘汰的结果(git 跟踪的文件永不淘汰,未跟踪的批次中间产物只保留
`*.report.md` 与 `*.log`)。任何台账条目都不得把它们当作出处;凡依赖它们复算的数字一律
记为 `needs-recompute`。

<!-- absent-paths:begin -->
| 路径 | 曾承载 | 现状 |
| --- | --- | --- |
| `examples/output/b5_smoke/analysis/ab.json` | b5.3 chain_off/chain_on 逐段 A/B | 已淘汰,结论保留在 b5.3 报告 §1b |
| `examples/output/b5_smoke/analysis/determinism.json` | 0.989/0.995 相似度对照 | 已淘汰,结论保留在 §3.2 |
| `examples/output/b5_smoke/analysis/outflow.json` | 123 匹配 / 15 变的邻段漂移表 | 已淘汰,结论保留在 §3.1 |
| `examples/output/b5_smoke/analysis/batches.json` | 批次重组前后组成 | 已淘汰,结论保留在 §3.1 |
| `examples/output/b5_smoke/parallel/courier_official_zh.md` | 官方中文版原件与 sha256 | 已淘汰,哈希无法现场核验 |
| `examples/output/b5_smoke/diff/Courier-en/page_0001.diff.png` | 链 A/B 渲染叠加图 | 已淘汰,论文图另有出处(见本节末) |
| `examples/output/b6_smoke/ab.rfinal.md` | b6.3 名称 A/B 明细 | 已淘汰,结论保留在 `names_fix.report.md` |
| `examples/output/b6_smoke/tuning.sweep.json` | 调参网格全表 | 已淘汰,六行摘要保留在报告 §2 |
| `examples/output/b6_smoke/tuning.compare.txt` | 候选列并排 | 已淘汰 |
| `examples/output/b7_3/Courier-en.pass1.pdf` | HITL 两遍的成品 PDF | 已淘汰,两遍的 review/decisions/run.json 仍入库 |
<!-- absent-paths:end -->

论文用的链 A/B 图不依赖已淘汰的叠加图:四张 300 dpi 栅格在
`docs/dissertation_assets/Courier-en.chain_on.p7.png` 及同目录另三张,配套说明在
`docs/dissertation_assets/dissertation_b5_evidence_section_filled.md`。

`examples/output/b8_4/smoke.report.md` §2d 提到的第一次冒烟页栅格(展示被守卫拦下的横排信用行)
本就未写入树内,不构成失效产物;树内的
`examples/output/b8_4/smoke/raster/b8_4.p6_15.page6.png` 是最终受守卫那一跑的产物,
与 b8.3 的同名图逐字节相同,恰是"拒绝"应有的样子。

---

## A 链线(跨页文章链)

| # | 数字 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| A-01 | 边界一致 **1.000 (26/26)**,门限 0.8,零 miss(v1 语料) | batch-b4.2 · `examples/output/b4/run_all.b4_2.final.log`:482;可由 `spec_checks/spec_check_b4.py` 断言 05 现场重算 | git | 链检测器达标的原始证据 | 直接可引(须标注"v1 语料") |
| A-02 | 边界一致 **1.000 (28/28)**,限于 `layout_generalization` 角色(v2 语料) | batch-b7.5.1 · `examples/output/b7_5/refresh.report.md` §2;现行 witness `examples/output/run_all.b8_3.log`:508 | git | **论文正文该引这一条**,26/26 作换血前的沿革 | 直接可引 |
| A-03 | 零假阳性:**30** 条裁定负边界无一被连 | `corpus/chain_labels.user.json`(本会话现场统计);`spec_checks/spec_check_b7_5.py` `check_02d_no_false_link_anywhere` PASS,见 `examples/output/run_all.b8_3.log`:1500 | git | 检测器的"宁缺毋滥"性质 | 直接可引 |
| A-04 | 语料边界台账:全语料 **35** 条(link 5 / no-link 30);约束域 **28** 条(link 3 / no-link 25);观察样张 7 条(link 2 / no-link 5) | `corpus/chain_labels.user.json`,本会话逐样张现场重算 | git | 语料章的边界规模 | 直接可引 |
| A-05 | 约束域三条正样本得分 **0.950 / 0.950 / 1.000** | batch-b7.5.1 · `examples/output/b7_5/refresh.report.md` §4 | git | 正样本裕度 | 直接可引 |
| A-06 | 链 `ktff8`:2 成员、合并源文 **826** 字符、`sentence_greedy`、5 句、segment 区间 0/4 与 4/5 | batch-b5.3 · `examples/output/b5_smoke/smoke.report.md` §1a(826 已由本会话逐字符复核) | git | 案例设定 | 直接可引 |
| A-07 | 守恒不变量:成员译文拼接与链整体译文**逐字节相等**;IL 字段与 sidecar 一致 | `examples/output/b5_smoke/smoke.report.md` §1a | git | block conservation invariant 的实录 | 直接可引 |
| A-08 | 排版后几何:页 7 框末字符 `。`(x=471.28, y=199.14);页 8 框末字符 `。`(x=75.26, y=443.8) | `examples/output/b5_smoke/smoke.report.md` §1b | git | mid-unit page-break rate 的方法原型 | 直接可引 |
| A-09 | A/B 缺陷对:悬空从句被虚构收束(`…以及一种复合材料。`)+ 先行词丢失致 `the grass`→`草地` | `examples/output/b5_smoke/smoke.report.md` §1b | git | 切断损害翻译质量的存在性论证 | 直接可引(底层 `ab.json` 已失效,引用限于报告原文) |
| A-10 | 零外溢:五样张 A/B 渲染,四份逐像素相同;唯一含链样张仅在页 **2, 3, 7, 8** 有差异,最大差异比 **0.0289** | `examples/output/b5_smoke/smoke.report.md` §2 表 3 | git | 爆炸半径与链成员严格重合 | 直接可引 |
| A-11 | spill 集合两模式逐样张逐段相同;**无正文段外溢** | `examples/output/b5_smoke/smoke.report.md` §2 表 2 | git | 链翻译不引入版式回归 | 直接可引 |
| A-12 | 邻段漂移:123 段匹配,**15 段变**(4 成员 + 11 邻段),集中在页 2/7/8 | `examples/output/b5_smoke/smoke.report.md` §3.1 | git | 重组效应的规模 | **需三跑**(见 D3 GAP-01) |
| A-13 | 重组机制:页 2 一批 6→5、页 3 由 2 批→1 批、页 7 [6,3]→[6,4]、页 8 [3,6]→[3,6,1];cross-column 跟踪组 14→12,cross-page 真对稳定在 5 | `examples/output/b5_smoke/smoke.report.md` §3.1 | git | 机制可见性(与 A-12 的归因分开陈述) | 直接可引(机制);归因需三跑 |
| A-14 | 成本:十一跑合计 **449** 次 translate(216 上行 / 233 缓存),**120 755** prompt tokens、**34 853** completion tokens | `examples/output/b5_smoke/smoke.report.md` §2 表 4 | git | 可复现性与成本章 | 直接可引 |
| A-15 | 官方中文版页边界落在**词中**(`…协议中包` / `含惠益分享条款。`);原件重锚为语料样张 `examples/input/Courier-zh.pdf`,sha256 `2975c623b0bc604a4deb15f36229de512d295f69e171462f083b3c7d494bbaf1`(本会话按登记值现场复核),该样张的 notes 自述含 zh p10→p11 的官方词中切断 | `corpus/manifest.json`(sha 与 notes);引文原文 `examples/output/b5_smoke/smoke.report.md` §1d | git(登记)/ worktree(原件) | 四方对照表 | 直接可引(旧 sha256 `fa789f8a…46a7d3ac` 指向已淘汰的 `parallel/courier_official_zh.md`,一律不得再引) |

## B 分类线(页面类型)

| # | 数字 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| B-01 | raw 词表整体一致率 **0.903 (28/31)**;分刊物 6/8, 3/4, 8/8, 8/8, 3/3(v1) | batch-b2.7 · `examples/output/b2_7/run_all.full.log`:292–299 | git | 调参落点的原始数字 | 直接可引(须标注 v1) |
| B-02 | LOPO **holdout 0.938** 与整体 0.903 的区分 | 唯一出处是 `plans/PLAN_B2_7.md`:22 的**转述**;调参会话的逐折矩阵从未落盘 | none | 泛化性论证的核心数字 | **needs-recompute**(见 D3 GAP-02) |
| B-03 | 分位数候选词表:v1 **0.903 (28/31)**,v2 **0.788 (26/33)**,未采纳 | `spec_checks/spec_check_b2_7.py`:109–124(冻结表,batch-b7.5.1 重述为 v2) | git | 词表选型的负结果 | 直接可引 |
| B-04 | 换血后 kind 与 policy 一致率均 **0.879 (29/33)**,门限 0.70,4 处 miss | batch-b7.5.1 · `examples/output/b7_5/refresh.report.md` §2;冻结表 `spec_checks/spec_check_b2_7.py`:109–116;witness `examples/output/run_all.b8_3.log`:130 | git | **论文正文该引这一条** | 直接可引 |
| B-05 | 分刊物 binding:0.778 (7/9), 0.750 (3/4), 1.000 (8/8), 0.889 (8/9), 1.000 (3/3) | `examples/output/run_all.b8_3.log`:123–127 | git | 逐刊物分解 | 直接可引 |
| B-06 | Courier-zh 观察基线:kind **0.250 (2/8)**,边界 **0.714 (5/7)** | `examples/output/run_all.b8_3.log`:129 与 507 | git | zh 侧未标定的基线,后续标定的对照起点 | 直接可引(须标注"该分布未参与任何调参") |
| B-07 | 三处 miss 的特征级归因:`max_font_size_ratio` **4.286**(Aramco p8/p9);`numeric_token_density` **0.0503** 对门限 0.08(FD p7);`mean_paragraph_chars` **98.6** 对 `article_body` 的 110 与 `sidebar_heavy` 惩罚的 140(zh p8) | `examples/output/b7_5/refresh.report.md` §3、§4 | git | "误判可归因到单一阈值"的论证 | 直接可引 |
| B-08 | 迁移零漂移:两条被替换样张与后继共享的 **25** 页判定全部未变 | `examples/output/b7_5/refresh.report.md` §3 | git | 换血未污染结论 | 直接可引 |
| B-09 | 页型覆盖 **11 / 15**;未覆盖 `back_cover` `contributors` `interview` `letters_page` | `examples/output/b7_5/refresh.report.md` §1 | git | 语料局限 | 直接可引 |
| B-10 | 语料规模:6 样张 / 5 刊物 / **41** 页 | `corpus/manifest.json`,本会话现场求和 | git | 语料章 | 直接可引 |

## C VLM 线(兜底消融)

| # | 数字 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| C-01 | 四点曲线(combined kind agreement,v1 语料,确定性基线一律 28/31 = 0.9032):`gpt-4o` **28/31 (0.9032)**、`gpt-4o-mini` **26/31 (0.8387)**、`gpt-5.6-sol` **28/31 (0.9032)**、`gpt-5.6-terra` **28/31 (0.9032)** | `examples/output/vlm_ablation/gpt-4o/vlm_eval.report.json` 等四份(`agreement.combined` 与 `agreement.deterministic`) | git | 消融曲线:四档模型无一超过确定性基线 | 直接可引(须标注 v1 语料 + 每模型各自的最小方差设定) |
| C-02 | 路由页 **18 / 31**;routed 一致率 deterministic **15/18 (0.8333)**,combined 同为 15/18(`gpt-4o-mini` 降至 13/18) | `examples/output/vlm_ablation/gpt-4o/vlm_eval.summary.txt` 及同级另三档 | git | 兜底只作用于 18 页,分母须说明 | 直接可引 |
| C-03 | 词表约束:accepted **18/18**,refused **0**,越界率 0.0(四档一致) | `examples/output/vlm_ablation/gpt-4o/vlm_eval.summary.txt` 及同级另三档 | git | 受约束输出可用性 | 直接可引 |
| C-04 | 结论措辞"四档模型均无 **policy 级**增益" | 措辞出处 `CLAUDE.md`:30 与 `plans/PLAN_B4.md`:14;**产物只报 kind agreement 与 label_set_coverage,没有 policy 列** | git | 关账结论 | **需重述**(见 D3 GAP-03) |
| C-05 | 现行 `enabled: false` | `configs/vlm.json` | git | 默认全自动、无网络 | 直接可引 |

## D HITL 线(人工两遍式仲裁)

| # | 数字 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| D-01 | 四条人名裁决、**8** 个落点全部由拉丁原形改为裁决目标 | batch-b7.3 · `examples/output/b7_3/smoke.report.md` §1 | git | 裁决到达每一处 prompt | 直接可引 |
| D-02 | 对照项:`biopiracy`(7 处)、`spinifex`(1 处)未裁决,两遍逐字相同 | `examples/output/b7_3/smoke.report.md` §1 | git | 变量隔离 | 直接可引 |
| D-03 | 页型传导链:p1 `editorial` 0.867 / `deterministic` → `toc` 1.0 / `human`;文章数 4→3;页 1 转为 unassigned,原因 `not_chain_eligible` | `examples/output/b7_3/smoke.report.md` §4;checkpoint 07/09/11 各 1 `human` + 7 `deterministic` | git | Page IR → policy → 分组的传导实录 | 直接可引 |
| D-04 | 扰动台账:132 段中 **18** 段变(自身命中 7 + 同批溢出 3 + 简报块变化 8);**prompt 未变而译文变 = 0** | `examples/output/b7_3/smoke.report.md` §6 | git | 无不可解释扰动 | 直接可引 |
| D-05 | 术语裁决的爆炸半径是 **batch 而非段落**(词表块按批构建) | `examples/output/b7_3/smoke.report.md` §6 | git | HITL 的方法论代价 | 直接可引 |
| D-06 | 词表重建:抽取 **145**、丢弃 **4**、重建并迁入用户词表 **141**,自动槽清空(W-B7-01) | `examples/output/b7_3/smoke.report.md` §7 | git | 与上游 glossary 选择规则的耦合 | 直接可引 |
| D-07 | 刊名三态:**4** 处统一到裁决名;**1** 处 offered-but-unmatched(`p1#9`);**1** 处 never-offered(`p6#15`,`fallback_line` 无 prompt) | batch-b7.5.2 · `examples/output/b7_5/refresh.report.md` §5 | git | 人机所见不一致的界面陷阱 | 直接可引 |
| D-08 | 两遍成本:pass1 51 请求 / 51 缓存 / **0** 上行;pass2 53 / 49 / **4**,5137 in + 1180 out;132 段中 **27** 段差异,4 条对照段逐字节相同 | `examples/output/b7_5/refresh.report.md` §5 | git | 冻结重放的可控性 | 直接可引 |
| D-09 | **123** 条 prompt 中裁决源串 `CourierT H E UNESCO` 零命中 | `examples/output/b7_5/refresh.report.md` §5;`examples/output/b7_5/prompt_inputs.evidence.json` | git | 裁决静默失配的直接证据 | 直接可引 |
| D-10 | 现行裁决单:6 条术语 / 1 条页型 / 3 条首字下沉 | `reviews/Courier-en.decisions.json` | git | 裁决单形态 | 直接可引 |

## E ReAct 线(检测—修复—复检)

| # | 数字 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| E-01 | 防御纵深实录(`p6#15`):检出 → 决策 → 带裁决送出 → 写回 → 单段重排 → **回滚**;residue ratio **1.000 → 0.630** 对门限 0.60;stop 原因 `finding_count_did_not_strictly_decrease` | batch-b8.3 · `examples/output/b8/smoke.report.md` §2 | git | 有界修复与守卫的完整链路 | 直接可引 |
| E-02 | 爆炸半径四证:132 段逐段摘要 0 变;pages 8→8、paragraphs 132→132、`touched_refs` 空;逐页文本 0 差异;页 6 栅格 `d06294a6b05e9374…`、裁剪 `0d419706e8117591…` | `examples/output/b8/smoke.report.md` §4;两枚哈希本会话在 `examples/output/b8_4/smoke/raster/` 现场 sha256 复核通过 | git | 守恒的最强形式(像素级) | 直接可引 |
| E-03 | b8.3 回归面:**6/6 conserved,0 段修复落地** | `examples/output/b8/smoke.report.md` §7 | git | v1 修复能力的下界 | 直接可引(已被 batch-b8.4 更新,见 E-06) |
| E-04 | b8.3 成本:**292** 次 API 调用、**229 462** prompt tokens、**58** 分钟 | `examples/output/b8/smoke.report.md` §7 | git | 成本章 | 直接可引 |
| E-05 | 拒绝分类学三案例:(a) 收敛守卫回滚(b8.3 `p6#15`);(b) 写回时盒面积增长被拒,**746 pt² → 69 700 pt²**(b8.4 `p6#15`);(c) 适用性规则按 `layout_label` 拒绝(`abandon` 段落译者已看过) | (a) `examples/output/b8/smoke.report.md` §2e;(b) `examples/output/b8_4/smoke.report.md` §2c;(c) `examples/output/b8/smoke.report.md` §7 | git | 三种拒绝各自的成因不同,不可合并叙述 | 直接可引 |
| E-06 | **3 处修复落地**且盒不变:CERNCourier-en `p2#32`、FD-en-v2 `p5#14`、FD-en-v2 `p5#9` | batch-b8.4 · `examples/output/b8_4/smoke.report.md` §3;本会话从 `examples/output/b8_4/smoke/evidence.json` 的 `landed` 段现场复核 `box_held: true` ×3 | git | **v1 修复不是零落地**——推翻 E-03 的表述 | 直接可引 |
| E-07 | 决策质量 named/eligible:b8.3 **18 / 5 (28%)** → b8.4 **15 / 9 (60%)**;`FD-en-v2` 反向(8 named / 7 eligible) | `examples/output/b8_4/smoke.report.md` §5;`examples/output/b8_4/smoke/evidence.json` `decision_quality` | git | prompt 暴露适用性规则的效果 | 直接可引(**单样本单模型,不得作显著性主张**) |
| E-08 | 阅读序修正影响面:冻结 fixture 90 段中 **3** 段改变,均为竖排 `fallback_line` | `examples/output/b8_4/smoke.report.md` §2a | git | 修正是定向的而非全局重写 | 直接可引 |
| E-09 | `escalation_surfacing` 在 6+6 次真跑中**零触发** | `examples/output/b8/smoke.report.md` §7;`examples/output/b8_4/smoke.report.md` §9.4 | git | 该检测器只有合成覆盖 | **needs-recompute**(须以合成覆盖声明替代,见 D3 GAP-04) |
| E-10 | 语料检测普查:`fragment_cluster` 3 处(CERN 2 / FD 1)、`text_figure_overlap` **0** | batch-b8.1 · `examples/output/b8/corpus_detection.md` | git | report-only 检测器的产出稀薄 | 直接可引 |
| E-11 | b8.4 成本:**16** 次 API 调用、**30 635** prompt tokens、**26.6** 分钟 | `examples/output/b8_4/smoke.report.md` §1 | git | 成本章 | 直接可引 |
| E-12 | 措辞出入两处:b8.3 §7 写"19, 24 and 28"(只数 residue),b8.4 §5 写"19, 25 and 32"(数全部 findings);b8.4 的 commit message 只写 "landed repair",未载主角 `p6#15` 被拒 | `examples/output/b8/smoke.report.md` §7;`examples/output/b8_4/smoke.report.md` §5;`git show 6ab55bb` | git | 引用前必须统一口径 | **需重述**(见 D3 GAP-05) |
| E-13 | E-06 三处落地的逐处摘录(batch-e1 会话一现场读出):CERNCourier-en `p2#32` 由 `Volume 66 Number 4  July/August 2026` 变为 `第66卷第4期 2026年7月/8月`;FD-en-v2 `p5#14` 由 `ADVISORS TO THE EDITOR` 变为 `编辑顾问`;FD-en-v2 `p5#9` 由 `PRODUCTION MANAGER` 变为 `制作经理`。三处 `box_before` 与 `box_after` 四个坐标逐值相等,`vertical` 均为 false,`box_held` 均为 true;光栅对照 `examples/output/b8_4/smoke/raster/b8_3.p2_32.png` 与 `examples/output/b8_4/smoke/raster/b8_4.p2_32.png`(另两处同名以 `p5_14` / `p5_9` 结尾,页级图以 `.page2.png` / `.page5.png` 结尾) | `examples/output/b8_4/smoke/evidence.json` 的 `landed` 数组;同数据的表格形式 `examples/output/b8_4/smoke.report.md` §3 | git | E-06 的可摘录形式:修复落地这一承诺的候选证据主角(三处并列,选定权在用户) | 直接可引 |

## F 上游基线(比较基准)

batch-e1 会话一按 D3 GAP-07 的优先级做了**分级入库**:`examples/baseline/manifest.json`、
`examples/baseline/baseline.report.md`、`examples/baseline/logs/`、
`examples/baseline/integrity/tree_sha256_after.txt` 与其 before 对照、
`examples/baseline/cache/cache.v1.db` 已进 git,下列条目的出处因此都是 `git`。
**六份基线成品 PDF(`examples/baseline/pdf/`)按体积不入库**,仍只存在于工作区;它们不是
任何一行的直接出处(逐份 sha256 载于已入库的 manifest),其存续由 `spec_checks/spec_check_e0.py`
的工作区档以显式"路径 + sha256"清单断言。

| # | 数字 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F-01 | 六样张全部 exit 0,页数 1:1 守恒,总耗时 **801.4 s**;逐样张耗时 134.89 / 86.83 / 144.10 / 151.46 / 140.46 / 143.66 s,输出 sha256 全载 | `examples/baseline/manifest.json`;摘要表 `examples/baseline/baseline.report.md` §Results | git | 上游可跑通、成本可比 | 直接可引 |
| F-02 | 版本对:上游为 main(post-`v0.6.4`-tag),**408 / 410** 文件与 fork 基线 `17480db` 逐字节相同,唯一差异是 `README.md`(两处链接改写,散文级) | `examples/baseline/manifest.json` 的 `version_pair.identity_evidence` | git | "同版本比较"的措辞依据 | 直接可引 |
| F-03 | 零改动证明:**415** 个文件的 SHA-256 在 `pip install -e` 前后一致 | `examples/baseline/integrity/tree_sha256_after.txt`;结论在 `examples/baseline/manifest.json` 的 `tree_integrity` | git | 上游未被污染 | 直接可引 |
| F-04 | 上游 fallback 警告矩阵(六样张 × same-as-input / too long-short / fell back / length mismatch) | `examples/baseline/baseline.report.md` §Results | git | 上游自陈的失败面 | 直接可引 |
| F-05 | **五缺陷家族**:未擦除原文 / 首字下沉 / display 与 chrome 文本漏译 / 文本流损坏 / 整块静默漏译 | `examples/baseline/baseline.report.md` §Cross-cutting patterns | git | **E3 对照轴的来源**,映射见 D3 GAP-08 | 直接可引 |
| F-06 | 警告数不追踪可见质量:Vogue-en 零警告却含全批最明显的整块漏译;CERNCourier-en 19 次 fallback 却产出全批最干净的一页 | `examples/baseline/baseline.report.md` §Results 末段 | git | 论证"须用几何/覆盖指标而非引擎自陈" | 直接可引 |
| F-07 | 缓存:批前 75 行(全部 `gpt-4o-mini` 或 fork 专有引擎,模型进 key 故不可命中)→ 批后 337 行,新增 **262**(220 en→zh + 42 zh→en);冻结拷贝 sha256 `0e2f4b00…`,以 SQLite backup API 而非文件拷贝取得 | `examples/baseline/manifest.json` 的 `translation_cache` | git | "输出是新翻译而非缓存重放" | 直接可引(**必须连同 manifest 的 attribution caveat 一起引:归因一致但不排他**) |

## G 方法论与基础设施特属

| # | 数字 / 命题 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| G-01 | 采样方差:同一 prompt 绕过缓存重发两次,`gpt-4o` 在 `temperature=0` 下返回**三个不同答案**,与冻结样本相似度 **0.989** 与 **0.995**,差异为词级选择(盗→剽、现在→目前) | batch-b5.3 · `examples/output/b5_smoke/smoke.report.md` §3.2 | git | 已知局限章;一切单跑差异的解释上限 | 直接可引(底层 `determinism.json` 已失效,引用限于报告原文) |
| G-02 | U+001A:该文件经 PyMuPDF 抽取层,源与输出**均无低于 U+0020 的字符**;本次运行因此**不复现**该条件 | `examples/baseline/baseline.report.md` §6 | worktree | 修正措辞:**不得**引作"上游能承受 U+001A",只能说"这一文件经这一路径未触发" | 直接可引(措辞受限) |
| G-03 | checkpoint 的可逆转义层(引导符自转义、规范形式在还原后比较)是 fork 特有,上游无此层;相关豁免 W-B0-02 | `CLAUDE.md`:28;`WAIVERS.md` W-B0-02 行 | git | 基础设施贡献的定位 | 直接可引 |
| G-04 | term consistency 语料表:**19** 个合格词;Courier +0.125、AramcoWorld +0.032、两样张持平、Vogue 无可测;38 行候选中 **4** 行仍不可用 | batch-b6.3 · `examples/output/b6_smoke/names_fix.report.md` §"Dual-mode table" | git | LTCR 的现有近似实现与其已知缺陷 | 直接可引(**报告自陈"不构成主张",引用时必须带上**) |
| G-05 | `max_tokens=2048` 非链感知:超长链会截断、`json.loads` 失败并以 `translation_unavailable` 逃生 | batch-b5.3 · `examples/output/b5_smoke/smoke.report.md` §0 | git | 设计局限 | 直接可引 |
| G-06 | 评估协议:A/B 一律以缓存冻结重放为准;显著性主张需三跑设计 | `CLAUDE.md`:31 | git | 评估章方法学 | 直接可引 |

---

## 状态汇总

分组行数:A 15、B 10、C 5、D 10、E 13、F 7、G 6,**合计 66 条**。

计数规则:一行按其状态单元格中**最先出现**的那个状态词归类(A-13 因此归入"直接可引",
其"归因需三跑"的半条在 D3 GAP-01 里与 A-12 合并处理)。

| 状态 | 条数 | 条目 |
| --- | ---: | --- |
| 直接可引 | 61 | 其余全部 |
| 需三跑 | 1 | A-12 |
| needs-recompute | 2 | B-02、E-09 |
| 需重述 | 2 | C-04、E-12 |

needs-recompute 与需三跑的完整清单、重算来源与 E2 运行矩阵见 `docs/eval/gap_register.md` §1。
