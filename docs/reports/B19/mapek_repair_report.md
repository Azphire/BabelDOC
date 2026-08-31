# B19 回路修复报告

本批六次运行(T1 单页 + T2/T3/T4 五次全跑)的回路证据。规格沿用 B16/B18:
每个**被接受**的回路修复须带 before/after PNG 对(≥120dpi)+ 证据 + 决策 +
验收向量。本批**接受 0**,故 PNG 义务为零——按双向门禁,零照实写零。

## 底表:样本 × kind

检出取 `issues.after.json`;提名取 `termination.json` 的 decisions 中 action
非 `no_op` 者;拒绝取 `refusals`;接受取 `acceptances`;回滚取 `rolled_back`。

| 任务 | 样本 | kind | 检出 | 提名 | 拒绝 | 接受 | 回滚 |
|---|---|---|---|---|---|---|---|
| T1 | Courier-zh(p5 单页) | untranslated_residue | 3 | 0 | 0 | 0 | 0 |
| T2 | bull-zh | fragment_cluster | 1 | 0 | 0 | 0 | 0 |
| T2 | bull-zh | instruction_compliance | 4 | 0 | 0 | 0 | 0 |
| T2 | bull-zh | text_figure_overlap | 3 | 1 | 1 | 0 | 0 |
| T2 | bull-zh | untranslated_residue | 10 | 0 | 0 | 0 | 0 |
| T2 | Courier-en | instruction_compliance | 1 | 0 | 0 | 0 | 0 |
| T2 | Courier-en | untranslated_residue | 5 | 4 | 4 | 0 | 0 |
| T3 | CERNCourier-en | fragment_cluster | 7 | 0 | 0 | 0 | 0 |
| T3 | CERNCourier-en | text_figure_overlap | 8 | 1 | 1 | 0 | 0 |
| T3 | CERNCourier-en | text_text_collision | 4 | 0 | 0 | 0 | 0 |
| T3 | CERNCourier-en | untranslated_residue | 20 | 2 | 2 | 0 | 0 |
| T3 | Courier-en | instruction_compliance | 1 | 0 | 0 | 0 | 0 |
| T3 | Courier-en | untranslated_residue | 5 | 0 | 0 | 0 | 0 |
| T4 | Courier-zh | untranslated_residue | 6 | 1 | 1 | 0 | 0 |
| **合计** | | | **78** | **9** | **9** | **0** | **0** |

(提名数按 refusals 逐条计;bull-zh 与 CERN 的 `text_figure_overlap` 各一条决策
携一个 finding id,Courier-en 的 `translate_orphan_text` 一条决策携四个 id,
CERN 的携两个,故提名 9 = 决策 5 条所携 finding id 总数。)

## 九次提名的拒绝理由(闭表)

| 样本 | action | finding | 拒绝理由 |
|---|---|---|---|
| bull-zh | refit_or_reflow_owned_paragraph | text_figure_overlap:p4:p4#2 | `refit_target_has_no_canonical_owner` |
| Courier-en(T2) | translate_orphan_text | untranslated_residue:p3:p3#2 | `orphan_is_canonical_article_text` |
| Courier-en(T2) | translate_orphan_text | untranslated_residue:p5:p5#10 | `orphan_is_canonical_article_text` |
| Courier-en(T2) | translate_orphan_text | untranslated_residue:p6:p6#15 | `orphan_is_canonical_article_text` |
| Courier-en(T2) | translate_orphan_text | untranslated_residue:p8:p8#15 | `orphan_is_canonical_article_text` |
| CERNCourier-en | refit_or_reflow_owned_paragraph | text_figure_overlap:p2:p2#1 | `refit_target_has_no_canonical_owner` |
| CERNCourier-en | translate_orphan_text | untranslated_residue:p2:p2#39 | `formula_paragraph` |
| CERNCourier-en | translate_orphan_text | untranslated_residue:p2:p2#84 | `formula_paragraph` |
| Courier-zh(T4) | translate_orphan_text | untranslated_residue:p6:p6#14 | `orphan_is_canonical_article_text` |

全部由**确定性准入**拒绝,而非模型自我否决。`translator_requests` 六跑均为
**0**——被拒的提名不发请求,这正是准入先于执行的证据。

## 终止状态

| 运行 | termination | 迭代 | 回滚 | 新增检测轮 |
|---|---|---|---|---|
| T1 Courier-zh p5 | `converged_all_treated` | 1 | false | 0 |
| T2 bull-zh | `all_candidates_refused` | 1 | false | 0 |
| T2 Courier-en | `all_candidates_refused` | 1 | false | 0 |
| T3 CERNCourier-en | `all_candidates_refused` | 1 | false | 0 |
| T3 Courier-en | `converged_all_treated` | 1 | false | 0 |
| T4 Courier-zh | `all_candidates_refused` | 1 | false | 0 |

## 双向门禁

- **接受方向**:接受 0 → 应交付 PNG 对 0 → 实交付 0。成立。
- **拒绝方向**:提名 9 → 应有闭表理由 9 → 实有 9(上表逐条)。成立。
- 回滚 0,`affected_elements` 六跑均为 0:回路本批未改动任何元素,页面上
  一切变化都来自 T1–T4 的确定性通道,不是回路的功劳。这一点值得单独说,
  因为本批**修好的四处缺陷都不是回路修的**——首字绑定、重复墨迹、幻觉
  拦截、底边释放,全部发生在检测之前。

## 本批修复的四处,与回路的关系

回路只看成品。B18 的 bull-zh 上,首字缺陷在回路眼里是 p3 的一条
`untranslated_residue`(遗留的 `核`)与 p8 的一条 `text_text_collision`
(误译的 `Senegal` 压在正文上);T2 之后两条都不再检出——不是被修复,而是
**不再发生**。同理 T3 的两条幻觉从未被任何检测器看见(它们是语法通顺的中文,
检测器无从判别),T4 的 3.5pt 字号也不在任何 kind 的辖区内。

这是本批关于回路的主要观察,记入 N-B19:**回路的检出面与本批四类缺陷的
交集只有两条,且都是间接征状**。一个能读出"这段文字与它的源文无关"或
"这行字小到不可读"的检测器,现在仍然不存在。
