# PLAN B9.6 — 决策 prompt 对 contain_in_page 的选中率修复(微批次,1 会话)

前置:batch-b9.5。b9.5 真实决策臂("on")在两个决策点上放过了合格的
`out_of_page` 发现,而同批的脚本决策臂("contain")证明机制本身是通的:
动作规则、导轨、变换、写回全部端到端可用,缺的只是模型选不中。

## 诊断(先于措辞)

两次落空决策的请求已按原样复现(见 §验证),因此诊断读的是原文而不是转述:

- Courier-en 迭代 1:请求里 `out_of_page:p1:p1#10` 的证据明写
  `layout_label='title'`、`overflow_ratio=0.013762`,两项条件都成立;模型答
  `none`,理由写"out_of_page finding does not have a layout_label of title or
  paragraph_title"——把请求里写着的字段读错了。
- CERNCourier-en 迭代 1 与 2:`out_of_page:p1:p1#2`(`title`,
  `overflow_ratio=0.033926`)在 40 条被展示的发现里排第 17 位,夹在 16 条
  `fragment_cluster` 与 31 条 `untranslated_residue` 之间;模型两轮都选
  `translate_orphan_lines`,从未提及它。

三条表述缺陷,与两次落空一一对应:

1. **条件读法未点明**。`out_of_page` 的证据是 15 个几何字段的平铺,其中
   `min_overflow_ratio=0.002` 是检测器自己的地板,与条件所指的
   `overflow_ratio` 只差一个前缀;条件与证据字段的对应关系全靠模型自己认。
2. **代价框架只写了一个动作的代价**。"a paragraph rewritten that was already
   correct costs a correct paragraph" 是 `translate_orphan_lines` 的代价;
   `contain_in_page` 一个字都不改。同段又说"evidence plainly describes the
   defect",而 `out_of_page` 的引文("信使T H E 联合国教科文组织")本身读起来
   毫无问题——把判据引回了模型对文本的观感,与开头"不是让你判检测器对不对"
   自相矛盾。
3. **跨动作如何取舍完全没写**。既有排序规则只管一个动作内部;发现按检测器
   分组呈现,于是"哪一类占满了列表"成了事实上的选择依据。

## 措辞(本批只动措辞)

`prompts/react_repair_decide.md` 新增/改写三处,`configs/repair_actions.json`
只改 `contain_in_page` 的 `description`(缺陷在前、机制在后,并写明它只搬墨、
不改字)。上限 2 轮,逐轮记哈希与动机,轮次证据落 `examples/output/b9_6/rounds/`。

## 验证(每轮三点,全部真实采样,绕缓存)

- **P1 CERN p1 真实重放**:b9.5 "on" 臂 CERNCourier-en 迭代 2 的请求,按
  `cache_key` 逐位复现(`f29131bd…`);断言决策点名 `out_of_page:p1:p1#2`。
- **P2 Courier-en 真实重放**:同法复现(`5d6fb5b8…`),断言点名
  `out_of_page:p1:p1#10`。两次落空各一点。
- **P3 合成决策用例**:一页里一条出页 `title` + 若干过不了孤行规则的残留 +
  一个碎片簇,已知正确选择是 `contain_in_page` 且只有它有合格发现。
- **零回归**:b8.4 的十九发现合成谱(只有 `untranslated_residue` 合格)真实
  重放,断言仍选 `translate_orphan_lines` 且命名恰为规则导出的合格集。

达标 = P1/P2/P3 均选中 containment 且零回归点不退。2 轮不达即如实报告,
F2 带 GAP-25 发车。

## 门禁

`spec_checks/spec_check_b9_6.py`:轮次记录完备且哈希两两不同、树上 prompt 即
最后一轮、四个验证点的冻结判定、`configs` 与 `prompts` 之外零改动(代码零改动
的负向断言)、b8.4 十九发现合成谱的机制面复跑(桩驱动,无 API)。

`spec_check_b8_4.check_03e` 的"树上文件等于最后一轮"这半条按其自身 docstring
交接给本批(它写明这半条属于最后改写 prompt 的那个批次);b8.4 的轮次目录
本身不动,本批轮次另起 `examples/output/b9_6/rounds/`。

## 负向

代码零改动(`babeldoc/` 不动一行);真值与裁决只读;`configs/repair_actions.json`
只动 `description` 字段,任何阈值、词表、上限不动;门禁无 API key。

## 明确不做

检测器改动;`resolve_collision` 自动化;上游众数锚定;F2。
