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
| A-09 | A/B 缺陷对(**已按 GAP-13 重述,以下为可引形式**):切断损害的确定性证据是**两项**——(1) 悬空从句被**虚构收束**,off 臂页 7 以 `以及一种复合材料。` 收尾;(2) 专利句被**切成两半**,off 臂 `p8#8` 以 `这种草已经被申请了专利。` 起头,与页 7 的收尾内容重复且逻辑断裂。**被撤下的是** `the grass`→`草地` 这一词级误译:R1 两个独立 off 臂均译作 `这种草`,该观察落在重复采样方差内,一律不得引作缺陷证据 | `examples/output/b5_smoke/smoke.report.md` §1b;三跑复核 batch-e2.1 · `docs/eval/results_e2/README.md` §5;重述合同 `docs/eval/gap_register.md` GAP-13 | git | 切断损害翻译质量的存在性论证 | 直接可引(**只能引重述后的两项**;引用时须连同"第三项观察未复现"一并陈述。判官侧的第三项候选见 A-23) |
| A-10 | 零外溢:五样张 A/B 渲染,四份逐像素相同;唯一含链样张仅在页 **2, 3, 7, 8** 有差异,最大差异比 **0.0289** | `examples/output/b5_smoke/smoke.report.md` §2 表 3 | git | 爆炸半径与链成员严格重合 | 直接可引 |
| A-11 | spill 集合两模式逐样张逐段相同;**无正文段外溢** | `examples/output/b5_smoke/smoke.report.md` §2 表 2 | git | 链翻译不引入版式回归 | 直接可引 |
| A-12 | 邻段漂移:123 段匹配,**15 段变**(4 成员 + 11 邻段),集中在页 2/7/8 | `examples/output/b5_smoke/smoke.report.md` §3.1;归因由 batch-e2.1 · `docs/eval/results_e2/drift_attribution.json` 给出 | git | 重组效应的规模 | 直接可引(**归因已定,见 A-18**;规模数字仍引 b5.3 原文,其 123 段分母是按源文匹配的结果,R1 按段位匹配得 132) |
| A-13 | 重组机制:页 2 一批 6→5、页 3 由 2 批→1 批、页 7 [6,3]→[6,4]、页 8 [3,6]→[3,6,1];cross-column 跟踪组 14→12,cross-page 真对稳定在 5 | `examples/output/b5_smoke/smoke.report.md` §3.1;独立复现 batch-e2.1 · `docs/eval/results_e2/drift_attribution.json` 的 `recomposed_pages` 与 `batch` 列 | git | 机制可见性(与 A-12 的归因分开陈述) | 直接可引(**机制已在 R1 独立复现**:页 2 一批 6→5、页 3 由 2→1、页 7 `[2,2,2,3,6]`→`[2,2,4,6]`、页 8 `[2,2,2,3,6]`→`[1,2,2,3,6]`,受影响段落 27 段全部落在页 2/3/7/8) |
| A-14 | 成本:十一跑合计 **449** 次 translate(216 上行 / 233 缓存),**120 755** prompt tokens、**34 853** completion tokens | `examples/output/b5_smoke/smoke.report.md` §2 表 4 | git | 可复现性与成本章 | 直接可引 |
| A-15 | 官方中文版页边界落在**词中**(`…协议中包` / `含惠益分享条款。`);原件重锚为语料样张 `examples/input/Courier-zh.pdf`,sha256 `2975c623b0bc604a4deb15f36229de512d295f69e171462f083b3c7d494bbaf1`(本会话按登记值现场复核),该样张的 notes 自述含 zh p10→p11 的官方词中切断 | `corpus/manifest.json`(sha 与 notes);引文原文 `examples/output/b5_smoke/smoke.report.md` §1d | git(登记)/ worktree(原件) | 四方对照表 | 直接可引(旧 sha256 `fa789f8a…46a7d3ac` 指向已淘汰的 `parallel/courier_official_zh.md`,一律不得再引) |
| A-16 | M1 分层实测(上游 / fork_full_il / fork_full_pdf 三列):AramcoWorld-en-v2 `6->7`(linked)上游 **open** → fork **closed**,是 M1 独立成立的唯一正例;Courier-en `7->8`(linked)三列**全部 closed**;Courier-zh `7->8`(linked)三列**全部 open**;trap 档 open 计入 `source_inherited_open` 不进分子(Courier-en 2 条) | batch-e1.2 · `docs/eval/results_e1/eval_corpus.md` §2–§3 与 `docs/eval/results_e1/eval_corpus.json` | git | 主结果表的 M1 一列 | 直接可引(主数为 `mbr_linkable`,定义见 `docs/eval/metric_contract.md` §2c.1) |
| A-17 | M1 在 Courier-en `7->8` 零判别力:上游末字符 `。` 来自**虚构收束**(A-09),fork 末字符 `。` 来自链重排后的真实句末;几何量无法区分二者 | batch-e1.2 · `docs/eval/results_e1/eval_report.Courier-en.json`(逐边界 tail 末字符)+ A-09 原文 | git | 指标局限的自陈;该边界的优劣**必须**引 A-09 的语义证据 | 直接可引 |
| A-18 | R1 三跑归因(Courier-en):A-12 集 **15** 段 = **4** 链成员 + **8** 重组归因 + **3** 与重复采样不可分辨。判据:既变更**又**落在被重组批次里的段落恰 15 段(与 A-12 的 4+11 分解逐数吻合);11 段邻段中 8 段在两个独立 off 臂上逐字节相同而 on 臂不同,3 段两个 off 臂本身就不同 | batch-e2.1 · `docs/eval/results_e2/drift_attribution.json` 的 `changed_and_recomposed_verdicts`;表在同目录 `drift_attribution.md` §1 | git | **GAP-01 的关账数字**:重组效应存在且可定位,但不是全部 | 直接可引(单样张单模型,**不作显著性主张**;`gap01` 列按 GAP-01 原文规则并列给出,可由三列译文复算) |
| A-19 | 配置内跑间方差:同一全栈配置的两次独立运行,132 段中 **43** 段译文不同,即 **0.3258**;两臂批次组成**逐段相同**,翻译前文档逐段相同 | batch-e2.1 · `docs/eval/results_e2/drift_attribution.json` 的 `noise_population` / `noise_rate` / `premises` | git | 一切单跑差异的解释上限,取代 G-01 的两点相似度作定量基线 | 直接可引(该率是**整段是否逐字节相同**的比例,不是相似度;与 G-01 的 0.989/0.995 不是同一个量) |
| A-20 | 链 A/B 指标级(三臂 × 两路径):`mbr_linkable` 三臂同为 0.4000(IL)/0.2000(PDF),七条边界逐条判决三臂全同;M2 三臂全 hold(8→8 页、132→132 段);LTCR 0.482143 / 0.428571 / 0.446429,合格词条数三臂均为 3(**两 off 臂之差 0.0536 大于 off 与 on 之差 0.0357 与 0.0179**);几何组 IL 路径 delta 全 0.0000、PDF 路径 `overlap_delta` −0.0406~−0.0410、`image_placement_iou` 1.0000、页数差 0 | batch-e2.1 · `docs/eval/results_e2/eval_report.Courier-en.json`;表在 `docs/eval/results_e2/README.md` §4 | git | 兑现 E1.2 遗留 1(冻结产物里没有 chain_on/chain_off 的指标级 A/B) | 直接可引(**M1 与 M3 在本 A/B 上均无判别力**,须与 A-17、A-18 一并陈述) |
| A-21 | R1 成本:三跑合计 **124** 次 API 调用(chain_on 1 / off₁ 62 / off₂ 61)、**105 759** prompt tokens、**22 701** completion tokens、**245.0** s 壁钟;chain_on 的 54 次翻译请求 **54 次全部命中缓存**,那 1 次调用是 ReAct 决策而非翻译 | batch-e2.1 · `docs/eval/results_e2/drift_attribution.json` 的 `runs`;工作区原件 `examples/output/e2/r1/runs.json` | git(台账)/ worktree(原件) | 成本章;冻结重放可控性的第二个实录(继 D-08) | 直接可引 |
| A-22 | M10 判官运行事实(R2):测试点 **5**(裁定单全部 `link: true` 正样本)× 可用臂 = **14** 行,`judge_refused` **0** 行;判官 `gpt-5.6-terra`(异族于被测 `gpt-4o`),`max_completion_tokens=1024`、不发 `temperature`,逐行钉版;**14** 次请求对应 **13** 个不同 prompt(`Courier-en 2->3` 两个 off 臂窗口逐字节相同,一个 cache key 服务两行;多出的一次是某一行首次尝试未产出可用回复、有界重试后通过),16 256 prompt / 6 806 completion tokens;`--offline` 重放 **14/14** 命中缓存、0 请求、两份 JSON 逐字节相同 | batch-e2.2 · `docs/eval/results_e2/splice_judgements.json`;协议 `docs/eval/splice_protocol.md`;成本原件 `examples/output/e2/r2/judge_cost.json` | git(表)/ worktree(成本原件) | M10 的实现与可复现性;GAP-03 方案 a 的兑现 | 直接可引(**定性微镜,不作比率**:点集只有 5 条正样本、无负控,每行只问一次)。**14 行不等于 14 个有效观察**:人工裁决把 6 行判为 `PROTOCOL-INVALID`(窗口取的是页几何端点而非被裁定的那对链成员,GAP-14),**有效集 8 行 / 3 点**,论文主证据只能取这 8 行,见 A-25 |
| A-23 | 判官在 `Courier-en 7->8` 四臂上**全部**记 `accuracy/mistranslation` **critical**,但落点不同:`upstream` / `chain_off_1` / `chain_off_2` 三行的 span 在 **head**(`草地已经被申请了专利。` / `这种草已经被申请了专利。` ×2),判词是"专利被安在草上而不是由草制成的复合材料上,由跨页处把未完短语断开后重启造成";`chain_on` 那一行的 span 在 **tail**(`并已为这种草的复合材料申请了专利。`),判词是专利状态"已获得"被写成"申请",**与边界无关** | batch-e2.2 · `docs/eval/results_e2/splice_judgements.json` 的 `Courier-en 7->8` 四行;表在 `docs/eval/results_e2/README.md` §8b | git | 切断损害的**第三项候选证据**(谓述层的先行词错误,三处独立产物复现),与 A-09 重述后的两项同向 | 直接可引,但**四行里只有三行经人工确认**:`upstream` / `chain_off_1` / `chain_off_2` 三行的 critical 由裁决确认为拼接归因(裁决把机制写作"虚构收束 + head 另起一句自足句",先行词丢失的**表层措辞**在两臂间不稳定——`草地` 对 `这种草`,与 GAP-13 一致);`chain_on` 那一行被**人工推翻**:该行 tail 收在真句末、head 另起一句,**没有拼接错误**,判官的 critical 是把四臂皆有的非拼接词汇问题(`申请` vs `已获得`)按 critical 计进了拼接,严重度亦偏高(GAP-16)。引用时须写"三臂确认、一臂推翻"。单判官、每行一次抽样,只作定性提示 |
| A-24 | 判官侧的两处方向性观察:(1) `Courier-en 2->3` 是本次唯一一处**链臂独有的缺陷**——两个 off 臂零错误,`chain_on` 页 3 首行排成 `动科学发现`,判官记 `accuracy/addition` (minor),span 即多出的 `动`;(2) `AramcoWorld-en-v2 6->7`(M1 唯一独立成立的正例,见 A-16)上判官与几何判决**同向**:上游臂 2 处错误、fork 臂 0 处 | batch-e2.2 · `docs/eval/results_e2/splice_judgements.json`;读法在 `docs/eval/results_e2/README.md` §8c | git | "链臂不是一律更好"的实录;M1 那一个正例的语义佐证 | 直接可引,但**须按裁决限定**:(2) `AramcoWorld-en-v2 6->7` 两行**人工确认**(上游拼接确实断句、fork 读作一句),是有效集里最干净的一对;(1) `Courier-en 2->3` 那一行**落在 `PROTOCOL-INVALID` 里**(GAP-14),不得作拼接点结论——但 `动科学发现` 这个缺陷**本身成立且是链臂独有**,只是成因被判官记错:它是合并标题链 `…如何推动科学发现` 被 `proportional` 策略切在词内(`推 / 动`)的残字,属设计行为的边界情形(GAP-18),不是"源文不支持的增字"。引用该缺陷须引 GAP-18 的机制而非判官的 `accuracy/addition`。`Courier-zh` 两臂方向不同、不构成对照(README §8d、A-26) |
| A-25 | 判官与人工的一致率:有效集 **8** 行(`Courier-en 7->8` 四臂 + `AramcoWorld-en-v2 6->7` 两臂 + `Courier-zh 7->8` 两臂)上一致 **6/8**;不一致两行,类型相反——`Courier-en 7->8` 的 `chain_on` 是**高估**(非拼接的词汇错误被按 critical 计进拼接,GAP-16),`Courier-zh 7->8` 的 `fork_full` 是**漏报**(未标目标语言不符 GAP-15,未标 `包` 跨边界重复 GAP-17)。另有 **6** 行标 `PROTOCOL-INVALID`(两个 `2->3` 点的全部臂,GAP-14),不进分母 | batch-e2.2 · `docs/eval/results_e2/splice_manual_review.json` 的 `human_review_scope` 与逐条 `human_agrees`;门禁 `spec_checks/spec_check_e2.py` 断言 14 由该文件重算 | git | **GAP-03 方案 (a) 的第二半**:异族判官的质量由人工抽验交代 | 直接可引(分母 8、每行一次抽样,**不作比率型主张**;该率只在"拼接归因"这一口径上成立,窗口内的非拼接观察按裁决不计) |
| A-26 | `Courier-zh` fork 臂窗口通篇中文的判定(本会话现场核实):**是段落未被译成另一种语言,不是源文误入窗口**。三项证据——(a) `auto_extractor_glossary.csv` 每行 `source == target`(如 `本土知识,本土知识`)、`tgt_lng` 为空,即该跑的目标语言等于源语言;(b) `checkpoint.09_il_translated` 的段落 `unicode` 字段本身就是中文,且带 `{v1}` 占位符与 `<style>` 标记,说明翻译往返**确实跑过**;(c) 两条裁定边界在 `chain_report.json` 里都是 `eligible: false`(`2->3` 记 `not_chain_eligible:head`,`7->8` 记 `not_chain_eligible:tail,head`),因为该样张八页全被判成 `sidebar_heavy`,与 B-06 的 kind 0.250 同因。**由此得到 GAP-17 的实例**:源文在切断处只有一个 `包`(`…协议中包` / `含惠益分享条款`),而 `p8#8` 的译文字段是 `包含惠益分享条款。…`——链未建立,残段按普通段落单独送译,引擎把残词 `含` 补全成 `包含`,`包` 于是跨边界出现两次 | batch-e2.2 · `examples/output/b8_4/smoke/Courier-zh/work/Courier-zh/` 的 `auto_extractor_glossary.csv`、`chain_report.json`、`checkpoint.08_chain_builder.xml` 与 `checkpoint.09_il_translated.xml`(逐段现场比对) | worktree | 回答裁决留下的待查项;**链失效时切断损害的表现形式**(与链生效时的虚构收束是同一机制的两面) | 直接可引(**该跑是 zh→zh**,故该样张的 fork 臂一律不得读作 zh→en 的性能;`包` 重复是单例观察,尚无自动检测,见 GAP-17) |

## B 分类线(页面类型)

| # | 数字 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| B-01 | raw 词表整体一致率 **0.903 (28/31)**;分刊物 6/8, 3/4, 8/8, 8/8, 3/3(v1) | batch-b2.7 · `examples/output/b2_7/run_all.full.log`:292–299 | git | 调参落点的原始数字 | 直接可引(须标注 v1) |
| B-02 | LOPO **holdout 0.938** 与整体 0.903 的区分 | 唯一出处是 `plans/PLAN_B2_7.md`:22 的**转述**;调参会话的逐折矩阵从未落盘,v1 语料已不存在 | none | 泛化性论证的核心数字 | 直接可引**仅作为负结果**:0.938 不可恢复、一律不得出现;替代品见 B-11 与 D3 GAP-02 |
| B-03 | 分位数候选词表:v1 **0.903 (28/31)**,v2 **0.788 (26/33)**,未采纳 | `spec_checks/spec_check_b2_7.py`:109–124(冻结表,batch-b7.5.1 重述为 v2) | git | 词表选型的负结果 | 直接可引 |
| B-04 | 换血后 kind 与 policy 一致率均 **0.879 (29/33)**,门限 0.70,4 处 miss | batch-b7.5.1 · `examples/output/b7_5/refresh.report.md` §2;冻结表 `spec_checks/spec_check_b2_7.py`:109–116;witness `examples/output/run_all.b8_3.log`:130 | git | **论文正文该引这一条** | 直接可引 |
| B-05 | 分刊物 binding:0.778 (7/9), 0.750 (3/4), 1.000 (8/8), 0.889 (8/9), 1.000 (3/3) | `examples/output/run_all.b8_3.log`:123–127 | git | 逐刊物分解 | 直接可引 |
| B-06 | Courier-zh 观察基线:kind **0.250 (2/8)**,边界 **0.714 (5/7)** | `examples/output/run_all.b8_3.log`:129 与 507 | git | zh 侧未标定的基线,后续标定的对照起点 | 直接可引(须标注"该分布未参与任何调参") |
| B-07 | 三处 miss 的特征级归因:`max_font_size_ratio` **4.286**(Aramco p8/p9);`numeric_token_density` **0.0503** 对门限 0.08(FD p7);`mean_paragraph_chars` **98.6** 对 `article_body` 的 110 与 `sidebar_heavy` 惩罚的 140(zh p8) | `examples/output/b7_5/refresh.report.md` §3、§4 | git | "误判可归因到单一阈值"的论证 | 直接可引 |
| B-08 | 迁移零漂移:两条被替换样张与后继共享的 **25** 页判定全部未变 | `examples/output/b7_5/refresh.report.md` §3 | git | 换血未污染结论 | 直接可引 |
| B-09 | 页型覆盖 **11 / 15**;未覆盖 `back_cover` `contributors` `interview` `letters_page` | `examples/output/b7_5/refresh.report.md` §1 | git | 语料局限 | 直接可引 |
| B-10 | 语料规模:6 样张 / 5 刊物 / **41** 页 | `corpus/manifest.json`,本会话现场求和 | git | 语料章 | 直接可引 |
| B-11 | v2 按刊物留一逐折矩阵(held-out kind / in-fold kind):aramcoworld **7/9** / 24/32、cern_courier **3/4** / 28/37、imf_fd **8/9** / 23/32、unesco_courier **10/16** / 21/25、vogue_us **3/3** / 28/38;binding 语料级 **29/33 = 0.879**(与 B-04 逐数相符);policy 列处处等于 kind 列 | batch-e1.2 · `docs/eval/results_e1/lopo_v2.json`(`tools/lopo.py` 确定性重算,二次运行逐位相等) | git | 泛化性论证的**替代**数字 | 直接可引(**必须同时标注 `refit_per_fold=false`:无调参器,任何折都不重拟合,矩阵是组合性的而非留出估计;不作留出主张**) |

## C VLM 线(兜底消融)

| # | 数字 | 出处 | 入库 | 论文用途 | 状态 |
| --- | --- | --- | --- | --- | --- |
| C-01 | 四点曲线(combined kind agreement,v1 语料,确定性基线一律 28/31 = 0.9032):`gpt-4o` **28/31 (0.9032)**、`gpt-4o-mini` **26/31 (0.8387)**、`gpt-5.6-sol` **28/31 (0.9032)**、`gpt-5.6-terra` **28/31 (0.9032)** | `examples/output/vlm_ablation/gpt-4o/vlm_eval.report.json` 等四份(`agreement.combined` 与 `agreement.deterministic`) | git | 消融曲线:四档模型无一超过确定性基线 | 直接可引(须标注 v1 语料 + 每模型各自的最小方差设定) |
| C-02 | 路由页 **18 / 31**;routed 一致率 deterministic **15/18 (0.8333)**,combined 同为 15/18(`gpt-4o-mini` 降至 13/18) | `examples/output/vlm_ablation/gpt-4o/vlm_eval.summary.txt` 及同级另三档 | git | 兜底只作用于 18 页,分母须说明 | 直接可引 |
| C-03 | 词表约束:accepted **18/18**,refused **0**,越界率 0.0(四档一致) | `examples/output/vlm_ablation/gpt-4o/vlm_eval.summary.txt` 及同级另三档 | git | 受约束输出可用性 | 直接可引 |
| C-04 | policy 级一致率(combined)四档:`gpt-4o` **28/31**、`gpt-4o-mini` **26/31**、`gpt-5.6-sol` **28/31**、`gpt-5.6-terra` **28/31**;对确定性层的 policy 增益 **0 / −2 / 0 / 0**——"四档模型均无 policy 级增益"至此有列可引 | batch-e1.2 · `docs/eval/results_e1/vlm_policy_c04.json`(由四份冻结报告离线重算,零请求零缓存查询;batch-e2.2 复跑该重算,**二次运行逐字节相同**,9 716 bytes) | git | 关账结论 | 直接可引(须标注 **v1 语料 31 页**分母,`unregistered_samples` 列出两份已换血样张)。**四档同源同口径:全部是离线重算,不是缓存重放。** GAP-10 曾写"terra 若要同口径需 18 次调用",batch-e2.2 现场核实该路径**不可执行**——18 个 routed page 中 **8 个**(AramcoWorld-en 5、FD-en 3)落在换血时移出的两份样张上,其 PDF 已不在 `examples/input/`,故四档都无法再实跑重现该分母,详见 C-06 |
| C-05 | 现行 `enabled: false` | `configs/vlm.json` | git | 默认全自动、无网络 | 直接可引 |
| C-06 | 消融不可重跑的量化:四档共用的 routed 页集 **18** 页,其中 **8** 页(`AramcoWorld-en.pdf` 5 页、`FD-en.pdf` 3 页)属于 batch-b7.5.1 换血移出的样张;两份 PDF 不在 `examples/input/`,因此 **C-01~C-04 的 31 页分母在今日语料上不可重建** | batch-e2.2 · 现场从 `examples/output/vlm_ablation/gpt-5.6-terra/vlm_eval.report.json` 的 `pages`(`source == "vlm"` 行)与 `corpus/manifest.json` 统计;结论落 `docs/eval/results_e2/README.md` §9 | git | 消融组一切数字的**存续性限定**;GAP-10 的关账依据 | 直接可引(这是"为什么四档只能离线重算"的答案,引 C 组任何一行时须与之并陈) |

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
| E-09 | `escalation_surfacing` 在 6+6 次真跑中**零触发**;`converged_with_residuals` 同样只有合成场景。**可引形式(合成覆盖声明,GAP-04 原文)**:"`escalation_surfacing` 与 `converged_with_residuals` 两条路径由合成场景覆盖并在门禁中逐次断言,**在真实语料的十二次运行中均未被触发**。本文因此把它们记为'机制已实现且有合成覆盖',而不记为'已被文档验证'。" | `examples/output/b8/smoke.report.md` §7;`examples/output/b8_4/smoke.report.md` §9.4;声明措辞 `docs/eval/gap_register.md` GAP-04 | git | 该检测器只有合成覆盖 | 直接可引(**只能按左列的声明形式引**;R3 不跑,batch-e2.2 按 GAP-04 的"不补的措辞"收口。此前的 `needs-recompute` 是"缺一次真触发",而不是"数字不可复算"——12 次零触发本身有出处且已复核) |
| E-10 | 语料检测普查:`fragment_cluster` 3 处(CERN 2 / FD 1)、`text_figure_overlap` **0** | batch-b8.1 · `examples/output/b8/corpus_detection.md` | git | report-only 检测器的产出稀薄 | 直接可引 |
| E-11 | b8.4 成本:**16** 次 API 调用、**30 635** prompt tokens、**26.6** 分钟 | `examples/output/b8_4/smoke.report.md` §1 | git | 成本章 | 直接可引 |
| E-12 | 措辞出入两处:b8.3 §7 写"19, 24 and 28"(只数 residue),b8.4 §5 写"19, 25 and 32"(数全部 findings);b8.4 的 commit message 只写 "landed repair",未载主角 `p6#15` 被拒。**可引形式(GAP-06 的统一口径)**:一律引**全部 findings** 的 **19 / 25 / 32**;凡引 b8.3 §7 那一句须加注"该处只计 residue,故写作 19 / 24 / 28";commit message 不改写历史,须引报告而非 commit | `examples/output/b8/smoke.report.md` §7;`examples/output/b8_4/smoke.report.md` §5;`git show 6ab55bb`;统一口径 `docs/eval/gap_register.md` GAP-06 | git | 引用前必须统一口径 | 直接可引(**只能按左列的统一口径引**;batch-e2.2 按 GAP-06 收口,该缺口是引用纪律而非可留的缺口) |
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
| G-07 | 上游几何路径的方法差异(同一份 fork 产物,IL 路径 vs PyMuPDF 抽取路径,门限 0.1):`overlap_*` 与 `alignment_*` 六样张几乎全部出界 → **not-comparable**;`image_placement_iou` **6/6** 可比;M1 比率不可比而逐边界判决一致 **30/35 (0.857)**;元素数比(PDF/IL)实测 **1.00–1.72** | batch-e1.2 · `docs/eval/results_e1/eval_corpus.md` §4;裁定表在 `docs/eval/metric_contract.md` §2c.2 | git | 上游列与 fork 列可否并排的前提条件 | 直接可引(**M4/M5 的上游列记 not-comparable,跨路径差值不得出现**) |
| G-08 | IL 路径的 before/after 几何差值是**结构性零**:六样张中四份的 `overlap_source` 与 `overlap_produced`、`alignment_source` 与 `alignment_produced` 在 6 位小数上完全相等,余两份差在第 4 位;成因是排版沿用源段落框 | batch-e1.2 · `docs/eval/results_e1/eval_corpus.json`(`fork_full_il` 各行) | git | 版面变化一律读 PDF 路径的理由 | 直接可引 |
| G-09 | 自动术语抽取本身被采样:同一配置的两次运行,**36** 个批次中 **10 个**(涉及 42 段)的 prompt 不同而**批次成员完全相同**,差异全在 glossary 块(如 `LINKS → LINKS` 一行在一臂在场、另一臂缺席)。**因此 prompt 字节不等不能作为"批次被重组"的判据**,归因用的是批次成员是否移动 | batch-e2.1 · `docs/eval/results_e2/drift_attribution.json` 的 `premises.off_arm_batches_with_a_differing_prompt` 与 `…_prompt_differences_with_identical_batch` | git | 归因方法学:两个混淆源必须分开;A/B 设计的已知陷阱 | 直接可引 |

---

## 状态汇总

分组行数:A 26、B 11、C 6、D 10、E 13、F 7、G 9,**合计 82 条**。

计数规则:一行按其状态单元格中**最先出现**的那个状态词归类。

| 状态 | 条数 | 条目 |
| --- | ---: | --- |
| 直接可引 | 82 | 全部 |
| 需三跑 | 0 | — |
| needs-recompute | 0 | — |
| 需重述 | 0 | — |

batch-e2.1 的变动:A-12 的"需三跑"由 R1 三跑消掉(归因见 A-18),`需三跑` 一档就此清零;
A-09 由"直接可引"降为"需重述",因为它的两半在三跑下证据强度不同;新增 A-18~A-21 与 G-09。

batch-e2.2 的变动,**四档状态就此全部收口**:

- **A-09** 按 GAP-13 的合同措辞重述后回到"直接可引",左列写死"能引哪两项、撤下哪一项";
- **E-12** 按 GAP-06 的统一口径(19 / 25 / 32)重述后回到"直接可引",`需重述` 清零;
- **E-09** 按 GAP-04 的合成覆盖声明收口,`needs-recompute` 清零。R3 不跑是用户裁定,
  代价写在左列:该路径只能作"机制已实现且有合成覆盖",不得作"已被文档验证";
- **新增 A-22~A-24**(M10 判官)与 **C-06**(消融不可重跑的量化)。C-06 是本会话对
  GAP-10 前提的现场核实结果,它把"terra 18 次补算"从待办改成声明。

人工裁决入库后(同批次追加):**A-25**(判官与人工一致 **6/8**,分母是有效集)与 **A-26**
(`Courier-zh` fork 臂的 zh→zh 判定与 `包` 跨边界重复)进表;A-22 加上有效集限定、A-23 的
四行改记"三臂确认一臂推翻"、A-24 的 `动科学发现` 改按 GAP-18 的机制陈述。裁决另开
GAP-14~GAP-18 五条,全部是**缺口**而非未关行——它们要么改材料要么改判官契约,不改任何
已落盘的数字。

**四档清零不等于零缺口**:留下的是**声明**而不是数字缺口——E-09 的合成覆盖声明、C-04/C-06
的 v1 分母不可重建、A-22~A-24 的"单判官、无负控、不作比率"。逐条见
`docs/eval/gap_register.md`。
