# batch-e1.2 冻结产物计算结果

本目录是 E1 会话二在**冻结产物**上算出的全部结果。零 API、零翻译运行:所有数字要么来自
已落盘的 checkpoint / PDF / 报告,要么来自它们的确定性重算。任何一项都可以用下面的命令
逐位复现。

## 1. 文件清单

| 文件 | 内容 | 生成命令 |
| --- | --- | --- |
| `eval_corpus.json` / `eval_corpus.md` | 全语料 × 全配置汇总(表头数字、分层表、逐边界判决表、方法差异表) | `python tools/eval_report.py --corpus --out docs/eval/results_e1` |
| `eval_report.<sample>.json` / `.md` | 逐样张逐配置全量记录(每条边界、每页几何、每个元素计数) | 同上 |
| `lopo_v2.json` | v2 语料按刊物留一的逐折矩阵 | `python tools/lopo.py` |
| `vlm_policy_c04.json` | 四档 VLM 模型的 **policy 级**一致率(台账 C-04 缺的那一列) | `python tools/vlm_classify_eval.py --from-report ...`(见 §5) |

三个配置列的含义:

- `upstream`:未改动的上游 BabelDOC 译后 PDF(`examples/baseline/pdf/`),几何走 PyMuPDF 抽取路径,
  源侧为 `examples/input/` 的原件;
- `fork_full_il`:fork 全栈跑(`examples/output/b8_4/smoke/`)的 IL 路径,源侧 `checkpoint.08_chain_builder`、
  译侧 `checkpoint.11_typesetting`;
- `fork_full_pdf`:**同一次** fork 跑的产物 PDF,走与 upstream 完全相同的抽取路径。

第三列的存在就是为了让第一列可读:`fork_full_il` 与 `fork_full_pdf` 之间的偏差即方法差异本身,
定量结论在 `docs/eval/metric_contract.md` §2c.2。

## 2. M1 分层结果(主数 MBR_linkable)

分层定义见合同 §2c.1。全语料 six samples × three configurations 的分层表在
`eval_corpus.md` §2,逐边界判决表在 §3。要点:

- **上游 vs fork 的唯一独立正例**:AramcoWorld-en-v2 `6->7`(linked,issue p34→p35 的中句切断)
  上游 `open`、fork `closed`。该处 M1 单独成立。
- **7->8 的对照(Courier-en,linked)**:三列全部 `closed`。上游末字符是 `。`——但那是译文把悬空
  从句**虚构收束**("…以及一种复合材料。",台账 A-09);fork 末字符也是 `。`,是链级联合翻译
  重排后的真实句末("…了专利。")。**M1 作为几何量在此边界零判别力**,优劣只能由 A-09 的语义
  证据承担。这一条必须原样写进论文,不得只引 M1 的"两侧都 closed"。
- **trap 档不进主数**:Courier-en 的 `5->6`、`6->7` 两条悬尾在三列全部 `open`,记入
  `source_inherited_open=2`,不进任何分子——它们的续接页根本不在节选内。
- Courier-zh `7->8`(官方版词中切断的同一处)三列**全部 open**:该 acute 正例在 b8_4 这一冻结
  配置下未被闭合,如实记录,不作它解。
- **`designed` 档在本语料上一次未触发**(18 次运行合计 0 条)。合同 §2b.3 设它是为了不把
  `proportional` 策略的设计行为记成缺陷;它没触发的原因是 tail 取"阅读序最后一个端点候选",
  而 Courier-en 页 2 的最后候选是图注(`figure_caption`)而非那条被切开的 display 标题成员。
  因此 `mbr_linkable` 与其 strict 形式在本语料上数值重合——该档留着是为了口径正确,不是因为
  它在本语料上起作用。

## 3. axis_unsupported 是否吞掉可测边界

**没有。** 18 次运行(6 样张 × 3 配置)的 `axis_unsupported_count` 全部为 **0**;同时每次运行
都确实见到 **2–6** 个竖排段落(实测为旋转的图片版权栏),即"该检查有对象可查而不是无物可吞"。
Courier-zh 单独看:IL 路径 6 个竖排段落、PDF 路径 3 个,`axis_unsupported` 均为 0,7 条边界
全部可判(closed/open)。逐运行数字见 `eval_corpus.md` §2 的 `axis unsupported` 与
`vertical paragraphs` 两列。

另有一档确实"吞"了边界,与轴无关:`no_tail`。IL 路径在 AramcoWorld-en-v2 `1->2` 与 FD-en-v2
`1->2` 各记 1 条(封面页无合格正文 tail),PDF 路径在同两处给出 `open`——因为抽取路径没有版面
标签可读,页码条与版权栏能充当 tail。这是方法差异而非分歧,合同 §2c.2 结论 3 已收录。

## 4. v2 LOPO(台账 B-02 / GAP-02)

`lopo_v2.json` 的 `protocol.refit_per_fold` = **false**,这是读这份矩阵的前提:
`configs/page_types.json` 是手工调出来的规则表,本仓库没有调参器,任何折都不重新拟合。
因此每折的 held-out 数就是该刊物自身的一致率、in-fold 数就是其余刊物的一致率,**矩阵是
组合性的,不是泛化性估计**;且词表调参时全部 v2 语料在场,没有任何一折免于调参接触。
按 GAP-02 的合同措辞:报告全语料一致率与逐刊物分布,不作留出集主张,0.938 一律不出现。

| held-out 刊物 | held-out kind | in-fold kind | held-out policy | in-fold policy |
| --- | --- | --- | --- | --- |
| aramcoworld | 7/9 | 24/32 | 7/9 | 24/32 |
| cern_courier | 3/4 | 28/37 | 3/4 | 28/37 |
| imf_fd | 8/9 | 23/32 | 8/9 | 23/32 |
| unesco_courier | 10/16 | 21/25 | 10/16 | 21/25 |
| vogue_us | 3/3 | 28/38 | 3/3 | 28/38 |

语料级:binding(`layout_generalization` 角色)**29/33 = 0.879**,observed-only(Courier-zh)
2/8,全体 31/41。binding 一列与台账 B-04 冻结的 0.879 (29/33) **逐数相符**,是这次重算对既有
数字的一次独立复核。kind 与 policy 两列在本语料上处处相等:没有一页是"名字错、policy 对"。

## 5. C-04 的 policy 列

`vlm_policy_c04.json` 由四份冻结消融报告离线重算,不发请求也不查回复缓存——报告里已有每页
判决,policy 列只是把判决经 `configs/page_types.json` 映射一次:

| 模型 | kind(combined) | policy(combined) | policy 增益 vs 确定性层 |
| --- | --- | --- | --- |
| gpt-4o | 28/31 (0.9032) | 28/31 (0.9032) | 0 |
| gpt-4o-mini | 26/31 (0.8387) | 26/31 (0.8387) | **−2** |
| gpt-5.6-sol | 28/31 (0.9032) | 28/31 (0.9032) | 0 |
| gpt-5.6-terra | 28/31 (0.9032) | 28/31 (0.9032) | 0 |

"四档模型均无 policy 级增益"从此有列可引:三档增益为 0,一档为负。**denominator 是 v1 语料
的 31 页**(报告的 `unregistered_samples` 字段列出 `AramcoWorld-en.pdf`、`FD-en.pdf` 两份已被
换血替换的样张),与 v2 的 29/33 不是同一分母,引用时必须标注。

复算命令:

```
python tools/vlm_classify_eval.py --out docs/eval/results_e1 --name vlm_policy_c04 \
  --from-report examples/output/vlm_ablation/gpt-4o/vlm_eval.report.json \
  --from-report examples/output/vlm_ablation/gpt-4o-mini/vlm_eval.report.json \
  --from-report examples/output/vlm_ablation/gpt-5.6-sol/vlm_eval.report.json \
  --from-report examples/output/vlm_ablation/gpt-5.6-terra/vlm_eval.report.json
```

## 6. 已知局限

1. fork 侧只有**一个**冻结配置带完整 checkpoint(b8_4 全栈跑);chain_off 等对照臂的
   checkpoint 已被产物清理,故本目录没有 chain_on/chain_off 的指标级 A/B。该 A/B 属 E2 的 R1 跑。
2. M4/M5 的上游列按合同 §2c.2 记 **not-comparable**,不是"算不出",而是两条路径的元素划分不同、
   两者都按 1/N 归一;跨路径差值一律不得引用。
3. IL 路径的 before/after 几何差值是结构性零(合同 §2c.3),故版面变化一律读 PDF 路径。
4. `upstream` 列的源 PDF 未入库(GAP-07 分级),其 sha256 随每条记录写在
   `eval_report.<sample>.json` 的 `source_pdf_sha256` / `produced_pdf_sha256` 中。
5. **M3 (LTCR) 在 zh→en 方向不可测**:Courier-zh 的合格词条数为 **0**。源侧词条抽取依赖
   首字母大写的专名连写(`babeldoc/magazine/metrics/ltcr.py` 的 `capitalised`),中文源文没有
   大小写可依,故该方向零候选。这是结构性限制而非本次运行的偶然,论文提 LTCR 时须限定
   en→zh 方向。PDF 抽取路径同样无 LTCR(没有源—译段落对应),两条 `absent` 理由逐条写在
   每份 `eval_report.<sample>.json` 里。
6. `mbr_linkable` 的分母在本语料上很小(全语料 linked 仅 5 条,单样张 0–2 条),**不足以支撑
   比率型主张**;主结果应按边界逐条陈述(§2),比率只作汇总参考。这与台账 A-04 对 GEMBA-MQM
   的同一条判断一致。
