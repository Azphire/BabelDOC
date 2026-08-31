# B16 MAPE-K 修复报告:装饰物压字 —— 管线恢复源避让,回路处置涌现残余

批次 B16,分支 `migration/minimal-v0.6.4`。T5 定版重跑:Courier-en 与 ITU-zh 全文,温缓存(Courier 58 命中 / ITU 35 命中,翻译零花费,修复翻译请求 0;决策调用 Courier 2 轮 / ITU 5 轮)。

## 首表:每 kind 检出 / 提名 / 拒绝 / 接受 / 回滚

### Courier-en(termination: `all_candidates_refused`)

| kind | 检出 | 提名 | 拒绝 | 接受 | 回滚 |
|---|---|---|---|---|---|
| untranslated_residue | 5 | 3 | 3(均 `orphan_is_canonical_article_text`)| 0 | — |
| instruction_compliance | 1 | 0(no_op)| — | 0 | — |
| text_figure_overlap | **0**(B15 为隐性 3 处压字,见下)| — | — | 0 | — |

### ITU-zh(termination: `converged_all_treated`)

| kind | 检出 | 提名 | 拒绝 | 接受 | 回滚 |
|---|---|---|---|---|---|
| text_figure_overlap | 2(p1#1 封面、p3#24,均 pdf_xobject artwork)| 0(no_op)| 决策层拒:"neither finding reports an ornament-grade path" | 0 | — |
| text_text_collision | 1(p2#10+11 pull_quote)| 0(no_op)| 决策层拒:coverage 0.57 > 0.5 | 0 | — |
| fragment_cluster | 1 | 0(no_op,低严重度)| — | 0 | — |
| untranslated_residue | 7 | 0(no_op,ratio 不达)| — | 0 | — |
| instruction_compliance | 3 | 0(no_op)| — | 0 | — |

**接受修复:两样本合计 0。** 这是治因后的正确结果,不是回路失效(诚实条款照记):四处已知装饰物压字全部由 T1 治因解决,回路面前已无该形态;回路的决策层按新约束句正确辨认出 ITU 的两条 artwork 检出不是 ornament 形态并拒绝。零接受 ⟺ 零修复 PNG 对,双向门禁成立。

## 归因型三分法:已知压字点逐处去向

计划列三处;T0/T1 实查发现 **第四处**(Courier p5,B15 亦压字,此前无人编目)。四处全部落入 `healed_by_clearance`,无一处无声消失:

| # | 位置 | 装饰物(源 IL bbox)| B15 现象 | 归因 | B16 结果 |
|---|---|---|---|---|---|
| 1 | Courier p2#4 figure_caption | 三角 p2:pdf_curve#2 (275.91, 51.74, 281.57, 57.40) | 首行墨迹压三角(x=276.2 起)| **healed_by_clearance**:capture 实测 indent 10.46pt → 宽 12.46pt | 墨迹零相交 |
| 2 | Courier p5#11 figure_caption | 三角 p5:pdf_curve#4 (46.06, 51.74, 51.73, 57.40) | 首行墨迹压三角(x=45.9 起)| **healed_by_clearance**:实测 10.38pt → 宽 12.38pt | 墨迹零相交 |
| 3 | Courier p8#14 figure_caption | 三角 p8:pdf_curve#3 (416.22, 785.91, 421.89, 791.58) | 首行墨迹压三角(x=416.3 起)| **healed_by_clearance**:实测 9.68pt → 宽 11.68pt | 墨迹零相交 |
| 4 | ITU p5#1 plain text(pull quote)| 开引号 p5:pdf_curve#6 (109.84, 557.00, 128.85, 571.19) | "The World…" 压引号(flag 未被剥除,4 空格粗值 ≪ 实测)| **healed_by_clearance**:实测 71.01pt → 宽 73.01pt | 墨迹零相交 |

ITU p5 的闭引号 (275.0, 353.0)(pymupdf 空间)不压字,B16 亦无检出——反向断言成立。

### 前后 PNG 对照(300dpi 裁片,均在本目录)

| 位置 | 源版 | B15(修前)| B16(修后)|
|---|---|---|---|
| Courier p2 | [courier-p2-triangle-source.png](courier-p2-triangle-source.png) | [courier-p2-triangle-before.png](courier-p2-triangle-before.png) | [courier-p2-triangle-after.png](courier-p2-triangle-after.png) |
| Courier p5 | [courier-p5-triangle-source.png](courier-p5-triangle-source.png) | [courier-p5-triangle-before.png](courier-p5-triangle-before.png) | [courier-p5-triangle-after.png](courier-p5-triangle-after.png) |
| Courier p8 | [courier-p8-triangle-source.png](courier-p8-triangle-source.png) | [courier-p8-triangle-before.png](courier-p8-triangle-before.png) | [courier-p8-triangle-after.png](courier-p8-triangle-after.png) |
| ITU p5 | [itu-p5-quote-source.png](itu-p5-quote-source.png) | [itu-p5-quote-before.png](itu-p5-quote-before.png) | [itu-p5-quote-after.png](itu-p5-quote-after.png) |

## 归因链(治因证据)

上游 paragraph_finder.py:160-170 以 >1pt 阈值从源几何测得 `first_line_indent`;两条退行机制并存,B16 各治其一:

1. **剥除**(Courier 三处):indent_policy 把 figure_caption 的功能避让当风格缩进裁为 False(B15 实录 6 处 True→False,其中 3 处功能性)。T1 拆分语义:capture_clearance 在翻译前对每个 raised flag 测让开区(框左缘→首字符,首行墨带),与装饰物/artwork 相交者判功能避让,政策丧失清除权。T5 indent 报告:Courier `functional=3`,三行 before==after==True 带 functional_clearance 标记;其余 26 处纯风格缩进照旧裁量(cleared count 6→3,风格剥除保留)。
2. **粗值**(ITU p5):flag 幸存但排版只进 4 空格(typesetting.py 原 `space_width * 4`),不及实测 71pt。T1 让排版消费实测宽度(实测 + clearance_pt 2pt)。

检测盲区同批关闭(T2):`text_figure_overlap` 在 figure/xobject 之外纳入装饰级矢量路径(填充、bbox 面积 ≤600pt²、边 ≤40pt,configs/ornament_assets.json,几何条件、单源共用),判据为**字符墨迹**相交面积 ≥4pt²(iou 对 30pt² 的三角天然失灵;用段落框则会把治愈后的避让重新报成缺陷——单页实测验证过这两种错法)。中间态实证:T1 治因生效前的单页跑,检测器恰好产出 `text_figure_overlap:p2:p2#4`(相交 30.2pt²,bbox 与源三角逐位吻合);治因生效后同页零检出。

## 回路兜底(T3)与其证据

`text_figure_overlap` 从 `retypeset_article_region`(B12 全拒于 `region_target_has_no_canonical_owner`)改挂 `refit_or_reflow_owned_paragraph`;`retypeset_article_region` 保留给 fragment_cluster/abnormal_blank。动作语义:命中段落原框重排,首行让位至装饰物右缘 + `clearance_pt`(决策参数,默认 2,range 0..8,越界由 schema 拒绝并触发重问)。P5 落定:排版仅支持首行让位一种排除形态,故准入限定头部形态(`clearance_not_head_form` 拒绝装饰物在段落中部的形态)。确定性一票否决:`overlap_not_ornament` / `ornament_evidence_invalid` / `ornament_not_fixed_asset`(装饰物是锚,动的是文字)/ `clearance_no_fit`(容不下,fail closed);失败逐字节恢复段落与宽度存储。守恒:可见字符序列逐字节断言不变;装饰物路径对象不动。

夹具门禁全绿(tests/minimal/test_ornament_clearance_repair.py 9 项:命中重排零相交且字符集不变、无视宽度的渲染被拒并恢复、超框即拒不渲染、三类准入拒绝、映射与参数 schema);B12 振荡/收敛夹具在新映射下全绿(test_one_repair / test_repair_rollback,全量 427 passed,9 失败逐名等于基线)。

**设计偏差(登记 UPSTREAM_DIFF)**:计划的 `clear_finding` 字符串参数以"提名绑定"实现——回路本就把每次动作绑定到唯一被提名 finding,排除源直接读该 finding 自身证据,模型无法另指矩形;数值型参数机制不为冗余字段扩类型系统。fail-closed 意图由构造保证。

## 残余与拒绝清单(T5 后)

- Courier-en:untranslated_residue ×5(3 提名均拒于 `orphan_is_canonical_article_text`,正文残留归章节译文路径,非孤文)、instruction_compliance ×1。与 B15 基线逐条一致。
- ITU-zh:tfo p1#1(封面整页 xobject,iou 0.56)与 p3#24(iou 0.20)——artwork 形态,决策层照约束句拒;ttc p2#10+11(coverage 0.57 > 0.5 准入上限);fragment_cluster ×1(低severity);untranslated_residue ×7(ratio 不达);instruction_compliance ×3。与 B15 基线逐条一致——**清单扩展零误伤**。

## 附:批内暴露并修复的两个既有缺陷

1. **B14 幽灵崩溃复现并修复**:typesetting.py bare `pdf_character` composition 分支访问 slots 类不存在的 `paragraph.debug_info` → AttributeError;`--pages 2` Courier 单页跑确定性复现(全文跑不触发)。修法与相邻分支一致(不传该参),登记 UPSTREAM_DIFF。
2. **capture 首版形态错误**:首行按 composition[0].pdf_line 读取,在 styles 重包(pdf_same_style_characters 跨行)后 29/29 全 no_leading_line;改为按字符阅读序 + 垂直墨带几何圈定首行(重跑即对抗,B15 教训 4 再次生效)。

## T0 前提偏差(节录,全文见 [_t0_premise_findings.md](_t0_premise_findings.md))

- P1 部分不符:ITU-zh 基线本有 3 条检出(计划称两样本零检出);盲区本体成立,基线断言按实测集合执行(上表可见,B16 保持该 3 条不多不少)。
- P9 机制二分:Courier=剥除,ITU=粗值;修订件两分支恰好各治其一。
