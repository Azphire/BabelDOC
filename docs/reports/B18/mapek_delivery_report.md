# B18 交付报告:单词不裸断、孪生可见性、跨栏标题联排、术语硬落实,收官全语料十二跑

分支 `migration/minimal-v0.6.4`,起点 `ca78529`(b17)。T0 复核见 [_t0_premise_findings.md](_t0_premise_findings.md)(P1–P5 全证实);T3 勘察见 [_t3_worknotes.md](_t3_worknotes.md);T5 预估见 [t5_run_estimates.md](t5_run_estimates.md);回路修复硬交付见 [mapek_repair_report.md](mapek_repair_report.md)。

## T1 拉丁词永不裸断(`597c419`)

**机制溯源(T0 实查)**:裸断有两个来源——min_scale 竭尽后 `use_english_line_break=False` 的自由断行兜底,以及 True 模式下词跑宽于行宽时的逐字符换行(ABB p5 的单字符堆叠正是后者)。词内断行从不越过 `_layout_typesetting_units`,故单点可治。

- **词单元**(全部有效字形 `can_break_line=False`,即任何换行都在劈词):唯一约束点在 `_find_optimal_scale_and_layout` 入口,改走 `_fit_single_word_unit`——先在确定性走廊(最近邻段落墨迹/框、页面 figure/curve/form 资产、cropbox 三者最近者,减 `functional_clearance_pt`,单源 configs/indent_policy.json)以政策字号试单行,再有界缩放至恰好进一行(min_scale 沿路径自身配置);bounded 分配保持既有 fail-closed。实现细节:wrap 判定把词跑首字宽双计(lookahead 自 `units[i:]` 含己),精确缩放按 `available/(total+max_width)` 估算再几何下探。
- **多词单元**:全梯保词完整(劈词判该 scale 失败),只余终局兜底可劈,且每一刀入 `word_fit.report.json`(kind `naked_break`,闭表 outcome)。slot 路径(`fit_text_to_slot`→`_legal_prefix_boundaries`)本就拒拉丁对内切点,B14 覆盖面核毕:无缺口。
- **实样(ABB 重跑)**:p6 `innovation` 单行 47.5pt(框内硬缩仅 ~35pt,+36%),p5 单行 15pt(原为逐字符堆叠);两页 innovation 与全页墨迹**墨迹级零相交**(图像/矢量/文本逐一相交测试);全跑 8 fit_policy / 2 fit_scaled / 1 corridor_exhausted / **0 劈词**。
- **全语料扫描(T5)**:十二样本劈词计数 **1**——HuaweiTech-zh p5(debug z54xq,scale 0.7,10 刀,"Currently, telecom operators are accelerating…"):多词段落的超长拉丁跑在窄框中到 min_scale 仍不进,走廊只惠及词单元 → 逐条归因,记 N-B18-1。词单元全语料 34 处 fit_policy / 16 fit_scaled / 2 corridor_exhausted(Courier-zh,兜底后单行未劈)。

## T2 孪生豁免加可见性条件(`303694c`)

- `bilingual_companion` → **`bilingual_companion_visible`**(SKIP_REASONS 闭表更名):豁免新增必要条件 = companion 可证可见。三判据落为两类既有事实——版心用 cropbox 几何;**有墨与未遮盖合并为一个渲染事实**:源页自身像素在 companion 框内偏离背景色(modal 色)的占比 ≥ `companion_ink_min_fraction`(0.02,range 0..0.5;zoom `companion_render_zoom`=2,range 1..4)。背景色填充、被不透明对象整体遮盖、Tr 裁剪,全都留不下非背景像素,一次光栅同判。判不出(源文件不可读、子集跑页号错位、退化框)→ 闭表 `unrenderable` → **不豁免**,单元照常入队(漏译比重译危害大)。
- **实样(fd 重跑)**:p3 `编者的话` 的 companion `EDITOR` 渲染实查 **visible**(ink_fraction 0.424 ≥ 0.02)——豁免保留,证据(companion 框/debug_id/占比/阈值)双向入 short_unit.refused 与 coverage 账单;unowned 0。residue 该条(豁免分支)照旧在报:检测器按内容说话,豁免的交付形态是**归因**,与 B17 一致、如今带可见性证明。
- 夹具:真实 PDF 光栅正反向(黑字可见/白盖不可见/出版心/不可读)+ 账单双向(可见记 skip、不可证走 unowned/入队)。

## T3 跨栏/跨页标题联合排版(`e8b7dfd`)

- **探针先行**(allocation_probe 永久入溢出 outcome):Courier 链走 slots 路径,title_min_scale 下容量 [53, 11] 字,proportional 切点分给成员二 17 字(仅进 12)→ 溢出。**可行域由容量决定**——纯框宽份额切点(35/53)同样不可行;计划的"份额"规则落为:可行词界区间 [len−cap₂, cap₁] 内,择最近框宽份额者。
- **分配侧**:cascade 全败的双成员 title 链走 `_attempt_joint_fit`——词界候选(非 CJK 空白;CJK 用翻译驱动自己的 tokenizer,不可得则 fail-closed)、二分取最大可行公共 scale(下至 title_min_scale)、`verify_redistribution` 逐字节守恒、strategy `joint_fit` 入 chains 记录;仍不可行 → 现行释放原样。
- **渲染侧**:已证明链成员组以公共 scale(各自 fitted 的较小者)钉排(`retypeset_bounded_text` 新 `initial_scale`;词单元分支 pinned);title 报告新增 `joint_fit` 结果类与 totals 键。基线取法(executor 落定):**源基线偏移**——title 的 source_box 即源墨迹框,包顶排版保持源基线相对框顶的实测偏移(为零),与全刊 title 渲染一致,取法写入每条 joint_fit 记录。
- **实样(Courier-zh 重跑)**:chain `Rm2XR` **joint_success**,切点 "…Changing **|** Times" 词界,双成员同 20pt:p2 两行 + p3 `Times` 跨栏连续呈现,孤立残行消失;`released_title_chains` 空;issues.after 9 → 6。B17 release 回归夹具全绿(释放兜底原样)。Courier-en 同获一对 joint_fit。
- 兼容:title totals 新键曾破 `verify_magazine_demo` 的精确字典比对——verifier 同步重建该键,并对旧报告(无键且零对)向后兼容(spec_check_demo_verifier_scope 16/16)。

## T4 人裁术语硬落实(`bdb7a88`)

五级梯子(`term_enforce.py`,报告 `term_enforce.report.json`):注入(现状)→ 逐单元后核(freeze_sources 在译前存术语单元源文,PLAN-A 归一化 `Glossary.normalize_source` 与 C1 同源)→ 变体确定性替换(闭集 = `dropped_from_auto` 的 auto_target + **源串本身仍站在译文里**的 pasteback 形态;替换断言只动变体跨度)→ 钉裁重译(`prompts/term_pin.md`,预算 `term_enforce_retry_budget`=20,range 0..60)→ 升级(闭表理由;C1 检测器一字未动)。守恒等式 `ruled == applied + substituted + retried_ok + escalated` 断言入报告。

**实样(Courier-en 重跑)**:B14 起慢性未采纳裁定 `CourierT H E UNESCO → 联合国教科文组织《信使》`(p1)**级 4 钉裁重译落实**(预算 1/20),终检 **instruction_compliance 0**(B12 以来首次);p6 同术语的 furniture 保留段按闭表升级(`unit_withheld_from_translation`)。

**全语料五级分布(T5)**:ruled **368** = applied 297 + substituted **21**(bull 17 + fd 3 + CERN 1)+ retried_ok **19** + escalated **31**;守恒等式十一样本全真(Courier-zh 决议无 terms,无账)。预算最高 bull 18/20。违裁清单(31 条升级,随成品交人工):25× `composition_not_rebuildable`(公式/占位符段落,级 3/4 拒touch,N-B18-2)+ 6× `unit_withheld_from_translation`(furniture/竖排保留段,落实与保护相撞的政策缺口,N-B18-4)。

## 守卫的第二个战果与一次误杀平反(`ac20875`)

Courier-en 首跑死于 B17 漂移守卫:drop-cap apply 在译前把视觉首字并进 owner(p5#5 "On the Purus River…"),这是**有记录、事务性的受认可源改写**——守卫比该 pass 年轻,两者从未在 drop-cap 样本上同场(Courier-en 上次完整运行在 b16)。修复:`CoverageSnapshot.refreeze_source`——事务提交后守卫 sha 跟随受认可文本,其后一切照防(夹具:refreeze 前拦、后放、再改再拦)。

## T5 全语料十二跑

- 顺序温跑 57 分钟(15:43–16:40),12/12 exit 0、status complete、**unowned 全 0**;缓存命中见底表(合计 662 hits)。级 4 实际 API 重译 **19** 次(预算计数合计 41,其中约 22 次是 opaque 组合在预算递增后、发请求前被拒的记账——预算先扣后查的次序瑕疵,并入 N-B18-2);其余翻译花费近零——在预估内。
- HITL 全走 reviews/*.decisions.json 既有授权代批;违裁清单如上交人工复核。
- 回路:16 次提名全部被确定性准入拒绝(理由闭表,见 mapek 报告),接受 0、回滚 0、PNG 义务 0,双向门禁以全零成立。
- 回归:tests/minimal **9 败逐名同基线 / 483 过**;spec_check 除基线项 `expectations_scope` 外全绿(b14_t2 需 work_dir 参数,带参全绿)。

### 全语料汇总底表(B17 版基础上增列)

| 样本 | 方向 | 检出(after, kind:数) | 接受 | 覆盖 owners(joint/none/ordinary/preserve) | unowned | 缓存 | 裸断 | 词单元(policy/scaled/exhausted) | 术语 R=A+S+T+E | 联排/释放 |
|---|---|---|---|---|---|---|---|---|---|---|
| ABB-zh | zh-en | abnormal_blank:1, oop:1, tfo:2 | 0 | 4/25/85/19 | 0 | 47 | 0 | 8/3/0 | 10=10+0+0+0 | 0/0 |
| Courier-zh | zh-en | residue:6 | 0 | 26/15/92/5 | 0 | 62 | 0 | 5/4/2 | 无裁定 | **2**/0 |
| HuaweiTech-zh | zh-en | frag:2, tfo:9, residue:3 | 0 | 0/44/207/26 | 0 | 43 | **1** | 3/2/0 | 40=39+0+1+0 | 0/0 |
| ITU-zh | zh-en | frag:1, C1:2, tfo:2, ttc:1, residue:6 | 0 | 2/22/73/0 | 0 | 35 | 0 | 2/2/0 | 51=45+0+2+4 | 0/0 |
| WIPO-zh | zh-en | tfo:1 | 0 | 4/9/28/0 | 0 | 20 | 0 | 1/0/0 | 19=17+0+2+0 | 0/0 |
| bull-zh | zh-en | frag:1, C1:4, tfo:3, ttc:1, residue:11 | 0 | 10/31/120/0 | 0 | 55 | 0 | 3/1/0 | 96=59+17+8+12 | 0/0 |
| fd-zh | zh-en | cc:2, frag:4, C1:9, oop:2, tfo:7, residue:2 | 0 | 4/48/175/4 | 0 | 75 | 0 | 12/4/0 | 55=36+3+4+12 | 0/0 |
| AramcoWorld-en-v2 | en-zh | frag:1, oop:3, tfo:3, residue:13 | 0 | 8/9/127/5 | 0 | 82 | 0 | 0/0/0 | 22=22+0+0+0 | 0/0 |
| CERNCourier-en | en-zh | frag:7, tfo:8, ttc:6, residue:22 | 0 | 0/55/179/3 | 0 | 82 | 0 | 0/0/0 | 33=31+1+1+0 | 0/0 |
| Courier-en | en-zh | residue:5 | 0 | 27/17/98/5 | 0 | 59 | 0 | 0/0/0 | 21=19+0+1+1 | **2**/0 |
| FD-en-v2 | en-zh | frag:5, oop:2, tfo:4, residue:7 | 0 | 6/34/149/12 | 0 | 83 | 0 | 0/0/0 | 14=14+0+0+0 | 0/0 |
| Vogue-en | en-zh | frag:2, C1:1, residue:2 | 0 | 0/17/35/3 | 0 | 19 | 0 | 0/0/0 | 7=5+0+0+2 | 0/0 |

(oop=out_of_page,tfo=text_figure_overlap,ttc=text_text_collision,frag=fragment_cluster,cc=chain_conservation,C1=instruction_compliance;联排数为 title 报告 joint_fit_members。en→zh 半区 word_fit 空表:中文段落合法任意断行,不构成词单元。)

## N-B18 清单(只记不修)

- **N-B18-1** 多词段落的超长拉丁跑无扩宽通道:走廊只惠及词单元;HuaweiTech p5(z54xq,scale 0.7,10 刀)是终局兜底的唯一实例。候选方向:多词段落在终局前借走廊扩 x2。
- **N-B18-2** 术语替换不入公式/占位符段落:级 3/4 对含 opaque composition 的段落拒改(25 例升级)。缺一条组合感知的替换通道(逐 run 定位术语跨度)。附带次序瑕疵:级 4 预算在 opaque 预检**之前**递增,不发请求也记账(~22 次)。
- **N-B18-3** 箱级检测器把 T1 的单行化读作缺陷:ABB p5#3 竖排带空出后 abnormal_blank(fill 1.4%)+ tfo(iou 按段落框算)双报,墨迹级实测零相交——B16"composition shape lies"教训的第三次现身,检测器需墨迹几何。
- **N-B18-4** 裁定术语落在 furniture/竖排保留段(6 例升级):落实与保护相撞,现为诚实升级;需政策裁决(人裁是否越过保护)。
- 既有 **N-B17-1..4**(切分尾行链缺口、畸形回复缓存、title 溢出重试策略空白、照片署名栏 residue)与 **formula_reclass 暗模块**状态原样带入,本批未动;N-B17-4 在 Courier-zh residue 6 条中继续可见。

## 红线自查

守恒:T3 联排 `verify_redistribution` 逐字节 + title 渲染 sha 复验;T4 替换断言只动变体跨度、守恒等式入报告。单点执行:T1 约束点唯一(全路径过 `_find_optimal_scale_and_layout`)。config 带 range:companion 两键、term 预算一键均有 `_allowed_range`。闭表:companion 可见性 4 词、word_fit outcome 4 词、term 升级理由 6 词、联排 strategy 入 chains 词表。无样本字面量;报告全为实测数;前提复核未触发停机。
