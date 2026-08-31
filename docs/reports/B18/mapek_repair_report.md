# B18 回路修复报告(全语料十二样本,B16 硬规格)

运行:`examples/output/B18/T5/<sample>`(2026-08-31,HEAD = b18 交付码,温跑,逐样本顺序执行)。
本表数据源:各样本 `termination.json`(decisions/refusals/acceptances)、`issues.before/after.json`、`repair_decisions.jsonl`。

## 首表:每样本 × 每 kind 的检出 / 提名 / 拒绝 / 接受 / 回滚

"检出"取 issues.before 的 kind 计数(回路开工时在案的缺陷);"提名"为决策步选中动作的 issue 数;"拒绝"为确定性准入的 refusal 数;接受与回滚全语料均为 **0**(照实写零;B16 起治因优先,回路只在确定性准入达标时动手,本批没有提名过关)。

| 样本 | kind | 检出 | 提名 | 拒绝 | 接受 | 回滚 |
|---|---|---|---|---|---|---|
| ABB-zh | abnormal_blank | 1 | 0 | 0 | 0 | 0 |
| ABB-zh | out_of_page | 1 | 0 | 0 | 0 | 0 |
| ABB-zh | text_figure_overlap | 2 | 0 | 0 | 0 | 0 |
| Courier-zh | untranslated_residue | 6 | 1 | 1 | 0 | 0 |
| HuaweiTech-zh | fragment_cluster | 2 | 0 | 0 | 0 | 0 |
| HuaweiTech-zh | text_figure_overlap | 9 | 0 | 0 | 0 | 0 |
| HuaweiTech-zh | untranslated_residue | 3 | 0 | 0 | 0 | 0 |
| ITU-zh | fragment_cluster | 1 | 0 | 0 | 0 | 0 |
| ITU-zh | instruction_compliance | 2 | 0 | 0 | 0 | 0 |
| ITU-zh | text_figure_overlap | 2 | 0 | 0 | 0 | 0 |
| ITU-zh | text_text_collision | 1 | 0 | 0 | 0 | 0 |
| ITU-zh | untranslated_residue | 6 | 0 | 0 | 0 | 0 |
| WIPO-zh | text_figure_overlap | 1 | 0 | 0 | 0 | 0 |
| bull-zh | fragment_cluster | 1 | 0 | 0 | 0 | 0 |
| bull-zh | instruction_compliance | 4 | 0 | 0 | 0 | 0 |
| bull-zh | text_figure_overlap | 3 | 2 | 2 | 0 | 0 |
| bull-zh | text_text_collision | 1 | 0 | 0 | 0 | 0 |
| bull-zh | untranslated_residue | 11 | 0 | 0 | 0 | 0 |
| fd-zh | chain_conservation | 2 | 0 | 0 | 0 | 0 |
| fd-zh | fragment_cluster | 4 | 0 | 0 | 0 | 0 |
| fd-zh | instruction_compliance | 9 | 0 | 0 | 0 | 0 |
| fd-zh | out_of_page | 2 | 0 | 0 | 0 | 0 |
| fd-zh | text_figure_overlap | 7 | 0 | 0 | 0 | 0 |
| fd-zh | untranslated_residue | 2 | 0 | 0 | 0 | 0 |
| AramcoWorld-en-v2 | fragment_cluster | 1 | 0 | 0 | 0 | 0 |
| AramcoWorld-en-v2 | out_of_page | 3 | 0 | 0 | 0 | 0 |
| AramcoWorld-en-v2 | text_figure_overlap | 3 | 1 | 1 | 0 | 0 |
| AramcoWorld-en-v2 | untranslated_residue | 13 | 1 | 3 | 0 | 0 |
| CERNCourier-en | fragment_cluster | 7 | 0 | 0 | 0 | 0 |
| CERNCourier-en | text_figure_overlap | 8 | 1 | 1 | 0 | 0 |
| CERNCourier-en | text_text_collision | 6 | 0 | 0 | 0 | 0 |
| CERNCourier-en | untranslated_residue | 22 | 1 | 1 | 0 | 0 |
| Courier-en | untranslated_residue | 5 | 1 | 4 | 0 | 0 |
| FD-en-v2 | fragment_cluster | 5 | 0 | 0 | 0 | 0 |
| FD-en-v2 | out_of_page | 2 | 0 | 0 | 0 | 0 |
| FD-en-v2 | text_figure_overlap | 4 | 1 | 1 | 0 | 0 |
| FD-en-v2 | untranslated_residue | 7 | 1 | 2 | 0 | 0 |
| Vogue-en | fragment_cluster | 2 | 0 | 0 | 0 | 0 |
| Vogue-en | instruction_compliance | 1 | 0 | 0 | 0 | 0 |
| Vogue-en | untranslated_residue | 2 | 0 | 0 | 0 | 0 |

(提名数与拒绝数可不等:一次提名可点多个 issue_id,准入逐 id 记拒;Courier-en 的 4 拒来自逐迭代重复提名同类。未列 kind 的样本该 kind 检出为 0。)

## 接受案例章节

**零章节:全语料接受数为 0。** 双向门禁"每样本接受数 >0 ⟺ PNG 对存在"以全零成立——十二个 `work/<sample>/evidence/` 目录均无义务、也均无 PNG 对。回路诚实于零:每次提名都有确定性准入判词,拒绝理由闭表如下。

## 拒绝理由清单(全部 16 条)

| 样本 | kind → 动作 | issue | 理由 |
|---|---|---|---|
| Courier-zh | untranslated_residue → translate_orphan_text | p6#14 | orphan_is_canonical_article_text |
| bull-zh | text_figure_overlap → refit_or_reflow ×2 | p4#12, p4#2 | refit_target_has_no_canonical_owner |
| AramcoWorld-en-v2 | text_figure_overlap → refit_or_reflow | — | refit_role_not_allowed |
| AramcoWorld-en-v2 | untranslated_residue → translate_orphan_text ×3 | — | orphan_translation_unchanged / formula_paragraph / orphan_is_canonical_article_text |
| CERNCourier-en | text_figure_overlap → refit_or_reflow | — | refit_target_has_no_canonical_owner |
| CERNCourier-en | untranslated_residue → translate_orphan_text | — | formula_paragraph |
| Courier-en | untranslated_residue → translate_orphan_text ×4 | — | orphan_is_canonical_article_text ×4 |
| FD-en-v2 | text_figure_overlap → refit_or_reflow | — | refit_role_not_allowed |
| FD-en-v2 | untranslated_residue → translate_orphan_text ×2 | — | vertical_paragraph ×2 |

## 与 B17 的检出对照(逐 kind 零回归声明)

- fd-zh:residue 2(=B17)、instruction_compliance **10 → 9**(T4 术语梯子落实一条)、其余 kind 逐数一致。
- Courier-zh:issues.after **9 → 6**(T3 联排消除 abnormal_blank/chain_conservation 侧影;residue 6 条照片署名栏形态 = N-B17-4 原样)。
- Courier-en:instruction_compliance **2 → 0**(B12 起慢性 p1 违裁经级 4 落实)。
- ABB-zh:出现 1 abnormal_blank + p5 tfo(T1 单行化让竖排带空出,箱级检测器读作缺陷;墨迹级实测零相交)= N-B18-3,只记不修。
- 其余八样本(HuaweiTech/ITU/WIPO/bull/AW/CERN/FD/Vogue)上一次完整运行分布在 B14–B17 各批、管线代码不同,不构成逐数基线;本批计数为 b18 代码下的实测首表,照实入册,kind 闭表内无新增种类。
